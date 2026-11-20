"""WheelchairLink 的行为测试：全部用注入的假串口，不需要真硬件。

锁定的行为（与 firmware/wheelchair_controller.ino 的协议和安全机制对应）：
  1. 模拟模式（port=None）：不碰串口，其余行为一致
  2. 意图翻译：左转/前进/右转/停 → L/F/R/S，变化时立即下发
  3. 心跳：当前指令每 1 秒重发一次（配合固件 3 秒急停）
  4. 电池回报解析 + 低电锁（跌破 19.0 落锁、回升过 19.5 解锁，与固件一致）
  5. 低电时非停止意图被强制为"停"
  6. close() 先发"停"再挂断
"""
from unittest.mock import Mock

import pytest

from hardware.serial_link import COMMAND_MAP, FIRMWARE_LOW_MSG, FIRMWARE_RECOVERED_MSG, WheelchairLink


class FakeSerial:
    """假串口：write 记录到 tx，read 从预置的 rx 里取。"""

    def __init__(self, rx: bytes = b""):
        self._rx = bytearray(rx)
        self.tx = []          # 每次write的原始bytes
        self.closed = False

    @property
    def in_waiting(self) -> int:
        return len(self._rx)

    def read(self, n=-1):
        if n in (-1, None):
            n = len(self._rx)
        out = bytes(self._rx[:n])
        del self._rx[:n]
        return out

    def write(self, data) -> int:
        self.tx.append(bytes(data))
        return len(data)

    def close(self) -> None:
        self.closed = True

    def reset_input_buffer(self) -> None:
        self._rx.clear()

    @property
    def written(self) -> bytes:
        return b"".join(self.tx)


def make_link(rx: bytes = b"", *, firmware: str | None = "wheelchair") -> tuple[WheelchairLink, FakeSerial]:
    fake = FakeSerial()
    link = WheelchairLink("COM9", firmware=firmware, port_factory=lambda port, **kw: fake)
    link.open()
    if rx:
        # open() 会清空输入缓冲（清掉上次残留是正确行为），所以测试数据要在 open 之后灌
        fake._rx.extend(rx)
    return link, fake


def sent_letters(fake: FakeSerial) -> list[str]:
    """把 write 进去的 b"F\\n" 还原成 ["F", ...]，方便断言。"""
    return [chunk[:-1].decode("ascii") for chunk in fake.tx if chunk.endswith(b"\n")]


def movement_letters(fake: FakeSerial) -> list[str]:
    """只看运动指令，滤掉 GET_DATA 轮询（第一次 update 就会发一次拿电池）。"""
    return [x for x in sent_letters(fake) if x != "GET_DATA"]


# ---------------------------- 模拟模式 ----------------------------


def test_simulated_mode_counts_without_serial():
    link = WheelchairLink(None)
    link.open()
    link.set_intent("前进", now=0.0)
    info = link.update(0.0)
    assert info.mode == "模拟"
    assert info.connected is False
    assert info.intent == "F"
    assert info.send_count == 1


# ---------------------------- 意图翻译与心跳 ----------------------------


def test_intent_maps_to_protocol_letters():
    assert COMMAND_MAP == {"左转": "L", "右转": "R", "前进": "F", "停": "S"}
    link, fake = make_link()
    link.set_intent("前进", now=0.0)
    assert sent_letters(fake) == ["F"]
    link.set_intent("左转", now=0.1)
    assert sent_letters(fake) == ["F", "L"]


def test_duplicate_intent_is_not_resent_immediately():
    link, fake = make_link()
    link.set_intent("前进", now=0.0)
    link.set_intent("前进", now=0.2)          # 相同意图：跳过
    assert sent_letters(fake) == ["F"]


def test_heartbeat_resends_current_command_every_second():
    link, fake = make_link()
    link.set_intent("前进", now=0.0)
    link.update(0.0)
    link.update(0.5)                           # 未到 1 秒：不发
    assert movement_letters(fake) == ["F"]
    link.update(1.05)                          # 到 1 秒：心跳重发
    assert movement_letters(fake) == ["F", "F"]
    link.update(1.6)                           # 间隔不足：仍只有两次
    assert movement_letters(fake) == ["F", "F"]


def test_battery_poll_sends_get_data():
    link, fake = make_link()
    link.update(0.0)                           # 无意图也要轮询电池
    link.update(1.0)                           # 轮询间隔 2 秒：不发
    link.update(2.05)                          # 发 GET_DATA
    assert "GET_DATA" in sent_letters(fake)


def test_terminal_prints_every_successful_serial_write(capsys):
    link, fake = make_link()
    link.set_intent("前进", now=0.0)
    link.update(0.0)
    link.update(1.05)
    link.close()

    assert sent_letters(fake) == ["F", "GET_DATA", "F", "S"]
    assert capsys.readouterr().out.splitlines() == [
        "[串口 COM9] 已发送 F",
        "[串口 COM9] 已发送 GET_DATA",
        "[串口 COM9] 已发送 F",
        "[串口 COM9] 已发送 S",
    ]


def test_terminal_labels_simulated_intents(capsys):
    link = WheelchairLink(None)
    link.set_intent("右转", now=0.0)
    link.set_intent("右转", now=0.1)
    link.set_intent("停", now=0.2)

    assert capsys.readouterr().out.splitlines() == ["[模拟] 指令 R", "[模拟] 指令 S"]


@pytest.mark.parametrize("write_error", [OSError("disconnected"), None], ids=["exception", "partial"])
def test_terminal_does_not_report_unsent_serial_commands(capsys, monkeypatch, write_error):
    link, fake = make_link()
    monkeypatch.setattr(fake, "write", Mock(return_value=1, side_effect=write_error))
    link.set_intent("前进", now=0.0)

    info = link.update(0.0)
    assert info.connected is False
    assert info.send_count == 0
    assert "串口写入失败" in info.last_error
    assert capsys.readouterr().out == ""


# ---------------------------- 电池回报与低电锁 ----------------------------


def test_battery_reply_is_parsed():
    link, _ = make_link(rx=b"BATTERY:87,218\n")
    info = link.update(0.0)
    assert info.battery == (87, 21.8)
    assert info.is_low_battery is False


def test_low_battery_locks_intent_to_stop():
    link, fake = make_link(rx=b"BATTERY:10,188\n")
    info = link.update(0.0)
    assert info.is_low_battery is True
    link.set_intent("前进", now=0.1)           # 低电时的非停止意图
    info = link.update(0.2)
    assert info.intent == "S"
    assert movement_letters(fake) == ["S"]     # 前进没发出去，发的是停（滤掉 GET_DATA 轮询）


def test_low_battery_hysteresis_direction():
    link, _ = make_link()
    link._handle_line("BATTERY:0,189")         # 18.9V → 落锁
    assert link.update(0.0).is_low_battery is True
    link._handle_line("BATTERY:0,192")         # 19.2V：在迟滞区间内 → 仍锁
    assert link.update(0.0).is_low_battery is True
    link._handle_line("BATTERY:0,196")         # 19.6V：过解锁线 → 解锁
    assert link.update(0.0).is_low_battery is False


def test_firmware_low_message_also_locks():
    link, _ = make_link()
    link._handle_line("Low battery voltage, please charge")
    assert link.update(0.0).is_low_battery is True
    link._handle_line("Battery voltage recovered")
    assert link.update(0.0).is_low_battery is False


def test_low_warning_stops_active_movement_before_heartbeat():
    link, fake = make_link(rx=f"{FIRMWARE_LOW_MSG}\n".encode())
    link.set_intent("前进", now=0.0)

    info = link.update(1.05)  # 低电告警与原运动心跳在同一次更新到达
    assert info.is_low_battery is True
    assert info.intent == "S"
    assert movement_letters(fake) == ["F", "S"]

    link.update(2.2)
    assert movement_letters(fake) == ["F", "S", "S"]

    fake._rx.extend(f"{FIRMWARE_RECOVERED_MSG}\n".encode())
    info = link.update(3.3)
    assert info.is_low_battery is False
    assert info.intent == "S"
    assert movement_letters(fake) == ["F", "S", "S", "S"]


def test_other_firmware_lines_are_kept_as_message():
    link, _ = make_link(rx=b"Direction changed\n")
    info = link.update(0.0)
    assert info.firmware_message == "Direction changed"


# ---------------------------- 生命周期 ----------------------------


def test_close_sends_stop_then_closes():
    link, fake = make_link()
    link.set_intent("前进", now=0.0)
    assert sent_letters(fake) == ["F"]
    link.close()
    assert sent_letters(fake)[-1] == "S"
    assert fake.closed is True
    assert link.update(0.1).connected is False


def test_open_failure_falls_back_to_simulated():
    def broken_factory(port, **kw):
        raise OSError("port not found")
    link = WheelchairLink("COM99", port_factory=broken_factory)
    link.open()
    info = link.update(0.0)
    assert info.connected is False
    assert "COM99" in info.last_error
    assert info.mode == "模拟"


@pytest.mark.parametrize("command", ["1", "2", "3", "4", "F"])
def test_original_controller_protocol_sends_only_single_bytes(command):
    link, port = make_link(firmware=None)
    assert link.firmware == "motor-test"
    link.set_intent(command, now=0.0)
    link.update(5.0)
    link.close()

    assert port.tx == [command.encode("ascii"), b"S"]


def test_motor_test_does_not_queue_motion_during_blocking_firmware_pulse(capsys):
    link, port = make_link(firmware="motor-test")
    link.set_intent("前进", now=0.0)
    link.update(1.0)
    link.set_intent("停", now=1.1)
    link.set_intent("1", now=1.2)
    link.set_intent("左转", now=2.1)
    link.set_intent("3", now=2.2)
    link.set_intent("4", now=2.9)
    link.update(8.0)

    assert port.tx == [b"F", b"S", b"3"]
    assert "motor-test 固件不支持指令：左转" in capsys.readouterr().out
    link.close()


def test_motor_test_allows_fresh_confirmation_after_previous_pulse():
    link, port = make_link(firmware="motor-test")
    link.set_intent("前进", now=0.0, retrigger=True)
    link.set_intent("前进", now=1.5, retrigger=True)
    link.set_intent("前进", now=2.2)
    link.set_intent("前进", now=2.3, retrigger=True)
    link.close()

    assert port.tx == [b"F", b"F", b"S"]
