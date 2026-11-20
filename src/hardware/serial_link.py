"""把上层的运动意图翻译成所选固件的串口协议。

视觉与键盘入口 → WheelchairLink.open() → update() / set_intent() → _send()
wheelchair 使用换行协议、心跳与电池轮询。motor-test 对接原始 Arduino 电机
测试固件，使用单字节。port=None 时使用同样的协议映射做终端模拟。
"""
from dataclasses import dataclass, field
import time

HEARTBEAT_INTERVAL = 1.0        # 当前指令重发间隔（秒）
BATTERY_POLL_INTERVAL = 2.0     # GET_DATA 轮询间隔（秒）
MOTOR_TEST_FIRMWARE = "motor-test"
LOW_BATTERY_ENTER_V = 19.0      # 电压跌破它 → 视为低电（与固件同一阈值）
LOW_BATTERY_EXIT_V = 19.5       # 回升超过它 → 解除低电（迟滞，方向同固件）

# 界面意图 → 固件协议字母
COMMAND_MAP = {"左转": "L", "右转": "R", "前进": "F", "停": "S"}
VALID_COMMANDS = {"S", "F", "B", "L", "R", "3", "4"}

FIRMWARE_LOW_MSG = "Low battery voltage, please charge"
FIRMWARE_RECOVERED_MSG = "Battery voltage recovered"


@dataclass(frozen=True)
class SerialProtocol:
    """描述在串口线上实际使用的指令编码与固件能力。"""

    commands: dict[str, str]
    terminator: bytes = b"\n"
    heartbeat: bool = True
    battery: bool = True
    pulse_seconds: dict[str, float] = field(default_factory=dict)


PROTOCOLS = {
    "wheelchair": SerialProtocol({command: command for command in VALID_COMMANDS}),
    MOTOR_TEST_FIRMWARE: SerialProtocol(
        {command: command for command in ("1", "2", "3", "4", "F", "S")},
        terminator=b"",
        heartbeat=False,
        battery=False,
        pulse_seconds={"1": 1.0, "2": 1.0, "3": 1.0, "4": 1.0, "F": 2.0},
    ),
}


@dataclass(frozen=True)
class LinkStatus:
    """一帧的链路快照，供界面显示。由 WheelchairLink.update() 产出。"""

    mode: str                            # "模拟" 或 串口名（如 "COM3"）
    connected: bool                      # 串口是否真的打开
    intent: str                          # 当前指令的实际串口编码；"" = 无
    send_count: int                      # 已发送的指令条数（含心跳）
    battery: tuple[int, float] | None    # (百分比, 电压V)；没收到过回报时是 None
    is_low_battery: bool                 # 低电标志（电压或固件消息触发）
    firmware_message: str                # 固件最近发来的一行消息（如 "Direction changed"）
    last_error: str                      # 最近一次错误说明（空串 = 无错）


class WheelchairLink:
    """串口硬件链路。所有收发都不阻塞主循环（timeout=0 + 随到随收）。

    port=None 时为模拟模式：照常计数与计时，只是不碰真串口。
    测试时可以注入 port_factory 来替代 pyserial（见 tests/test_serial_link.py）。
    """

    def __init__(
        self,
        port: str | None = None,
        *,
        baudrate: int = 9600,
        firmware: str | None = None,
        heartbeat_interval: float = HEARTBEAT_INTERVAL,
        battery_poll_interval: float = BATTERY_POLL_INTERVAL,
        port_factory=None,
    ) -> None:
        if firmware is None:
            firmware = MOTOR_TEST_FIRMWARE if port is not None else "wheelchair"
        if firmware not in PROTOCOLS:
            raise ValueError(f"未知固件协议：{firmware}")
        self._firmware = firmware
        self._protocol = PROTOCOLS[firmware]
        self._pulse_until = float("-inf")
        self._port_path = port
        self._baudrate = baudrate
        self._heartbeat_interval = heartbeat_interval
        self._battery_poll_interval = battery_poll_interval
        self._port_factory = port_factory  # None → 用 pyserial
        self._port = None
        self._mode = "模拟"
        self._connected = False
        self._intent = ""
        self._send_count = 0
        self._last_sent_at = float("-inf")   # 上次下发当前指令的时刻（心跳用）
        self._last_poll_at = float("-inf")   # 上次 GET_DATA 的时刻
        self._battery = None
        self._is_low = False
        self._firmware_message = ""
        self._last_error = ""
        self._rx = b""                       # 串口接收拼行缓冲

    # ---- 只读属性（main 里判断用）----
    @property
    def firmware(self) -> str:
        return self._firmware

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def last_error(self) -> str:
        return self._last_error

    def open(self) -> None:
        """打开串口；port=None 或打开失败都落回模拟模式（不抛异常，错误记在 last_error）。"""
        if self._port_path is None:
            return
        try:
            import serial
            factory = self._port_factory or serial.Serial
            self._port = factory(self._port_path, baudrate=self._baudrate, timeout=0, write_timeout=1)
            self._port.reset_input_buffer()
            self._connected = True
            self._mode = self._port_path
        except Exception as exc:  # noqa: BLE001 —— 任何打不开的原因都退回模拟
            self._port = None
            self._connected = False
            self._mode = "模拟"
            self._last_error = f"无法打开串口 {self._port_path}：{exc}"

    def set_intent(self, intent, now: float | None = None, *, retrigger: bool = False) -> None:
        """将统一意图转成固件指令。新一次眼控确认可重新触发已结束的电机测试脉冲。"""
        command = COMMAND_MAP.get(intent, str(intent).strip().upper())
        letter = self._protocol.commands.get(command)
        if letter is None:
            self._last_error = f"{self._firmware} 固件不支持指令：{intent}"
            print(f"[指令] {self._last_error}", flush=True)
            return
        duration = self._protocol.pulse_seconds.get(command)
        if self._is_low and letter != "S":
            self._last_error = "低电量：意图已强制为停止"
            letter = "S"
            duration = None
        if letter == self._intent and not (retrigger and duration is not None):
            return
        now = time.perf_counter() if now is None else now
        if duration is not None:
            # 固件在 delay() 中无法处理串口。停止仍可发出，运动指令不排队。
            if now < self._pulse_until:
                return
            self._pulse_until = now + duration
        self._intent = letter
        self._send(letter, now)

    def update(self, now: float) -> LinkStatus:
        """先处理固件消息，再发心跳和电池轮询，返回本帧 LinkStatus。"""
        self._drain(now)
        if self._connected:
            if self._protocol.heartbeat and self._intent and now - self._last_sent_at >= self._heartbeat_interval:
                self._send(self._intent, now)                    # 心跳
            if self._protocol.battery and now - self._last_poll_at >= self._battery_poll_interval:
                self._last_poll_at = now
                self._send("GET_DATA", now, resets_heartbeat=False)
        return self._status()

    def close(self) -> None:
        """先发"停"再挂断；模拟模式下只是清引用。"""
        if self._connected and self._intent != "S":
            self._send("S", time.perf_counter())
        if self._port is not None:
            try:
                self._port.close()
            except Exception:  # noqa: BLE001 —— 关闭失败也无需上抛
                pass
            self._port = None
        self._connected = False

    # ---- 内部实现 ----
    def _send(self, letter: str, now: float, *, resets_heartbeat: bool = True) -> None:
        """发送一条协议指令，并在终端标明串口发送或模拟。"""
        if self._connected and self._port is not None:
            try:
                payload = letter.encode("ascii") + self._protocol.terminator
                written = self._port.write(payload)
                if written != len(payload):
                    raise OSError(f"指令只写入 {written}/{len(payload)} 字节")
            except Exception as exc:  # noqa: BLE001 —— 设备拔掉等情况
                self._connected = False
                self._last_error = f"串口写入失败：{exc}"
                return
            message = f"[串口 {self._mode}] 已发送 {letter}"
        else:
            message = f"[模拟] 指令 {letter}"
        self._send_count += 1                # 模拟模式也计数（界面显示"已发 N 条"）
        if resets_heartbeat:
            self._last_sent_at = now
        print(message, flush=True)

    def _drain(self, now: float) -> None:
        """把串口里已到达的字节全部收下来，按行交给 _handle_line。非阻塞。"""
        if not self._connected or self._port is None:
            return
        try:
            while self._port.in_waiting:
                self._rx += self._port.read(self._port.in_waiting)
        except Exception as exc:  # noqa: BLE001
            self._connected = False
            self._last_error = f"串口读取失败：{exc}"
            return
        if len(self._rx) > 256:              # 防御：垃圾数据再长也只留尾部
            self._rx = self._rx[-256:]
        while b"\n" in self._rx:
            raw, self._rx = self._rx.split(b"\n", 1)
            self._handle_line(raw.decode("utf-8", errors="ignore").strip(), now)

    def _handle_line(self, line: str, now: float | None = None) -> None:
        """处理固件发来的一行：BATTERY 回报 / 低电消息 / 其他消息。"""
        if not line:
            return
        if not self._protocol.battery:
            self._firmware_message = line
            return
        if line.startswith("BATTERY:"):
            try:
                pct_text, v_text = line[len("BATTERY:"):].split(",")
                voltage = int(v_text) / 10.0
                self._battery = (int(pct_text), voltage)
                # 与固件一致的迟滞：跌破 19.0 判低，回升过 19.5 才解除
                if not self._is_low and voltage <= LOW_BATTERY_ENTER_V:
                    self._is_low = True
                elif self._is_low and voltage >= LOW_BATTERY_EXIT_V:
                    self._is_low = False
            except ValueError:
                self._last_error = f"电池回报格式异常：{line}"
        else:
            self._firmware_message = line
            if line == FIRMWARE_LOW_MSG:
                self._is_low = True
            elif line == FIRMWARE_RECOVERED_MSG:
                self._is_low = False
        if self._is_low and self._intent != "S":
            self.set_intent("停", now=now)    # 数值回报和文本告警都立即覆盖旧指令

    def _status(self) -> LinkStatus:
        return LinkStatus(
            mode=self._mode,
            connected=self._connected,
            intent=self._intent,
            send_count=self._send_count,
            battery=self._battery,
            is_low_battery=self._is_low,
            firmware_message=self._firmware_message,
            last_error=self._last_error,
        )
