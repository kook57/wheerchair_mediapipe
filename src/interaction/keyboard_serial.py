"""Windows 终端键盘控制，由手眼预览的 --keyboard 入口调用。

main() → 打开 WheelchairLink → run_keyboard()
  每轮 → read_key() → 按所选固件解释按键
       → 处理停车超时 → link.update() → 发送当前方向
  退出 → 发送停止并关闭串口
"""

import sys
import time

from hardware.serial_link import MOTOR_TEST_FIRMWARE, WheelchairLink

ARROW_KEYS = {"H": "up", "K": "left", "M": "right", "P": "down"}
KEY_COMMANDS = {
    "w": "F", "f": "F", "up": "F",
    "a": "L", "l": "L", "left": "L",
    "d": "R", "r": "R", "right": "R",
    "s": "S", " ": "S", "down": "S",
}
MOTOR_TEST_KEYS = {
    "1": "1", "2": "2", "3": "3", "4": "4",
    "w": "F", "f": "F", "up": "F",
    "s": "S", "x": "S", " ": "S", "down": "S",
}
KEY_IDLE_STOP_SECONDS = 0.7
POLL_INTERVAL_SECONDS = 0.02


def read_key(console) -> str | None:
    """从 Windows 终端取一个按键，方向键包含前缀与扫描码。"""
    if not console.kbhit():
        return None
    key = console.getwch()
    if key in ("\x00", "\xe0"):
        return ARROW_KEYS.get(console.getwch())
    return key.lower()


def run_keyboard(console, link: WheelchairLink) -> None:
    """将当前控制键交给串口层。方向键停止重复后清除运动意图。"""
    commands = MOTOR_TEST_KEYS if link.firmware == MOTOR_TEST_FIRMWARE else KEY_COMMANDS
    stop_at = None
    while True:
        key = read_key(console)
        if key in ("q", "\x1b"):
            return

        now = time.perf_counter()
        command = commands.get(key)
        if command == "S" or (stop_at is not None and now >= stop_at):
            link.set_intent("S", now=now)
            stop_at = None
        link.update(now)
        if command is not None and command != "S":
            link.set_intent(command, now=now)
            stop_at = now + KEY_IDLE_STOP_SECONDS
        time.sleep(POLL_INTERVAL_SECONDS)


def main(serial_port: str | None = None, *, firmware: str | None = None) -> None:
    """启动终端键盘模式，指定端口时打开串口，否则使用模拟。"""
    if sys.platform != "win32" or not sys.stdin.isatty():
        raise SystemExit("键盘模式请从 Windows 的交互式终端运行。")
    import msvcrt

    link = WheelchairLink(serial_port, firmware=firmware)
    try:
        link.open()
        if link.connected:
            link.set_intent("S")
            print(f"已连接串口 {link.mode}。")
        elif link.last_error:
            print(f"串口未连接，已切到模拟模式。{link.last_error}")
        else:
            print("键盘模拟模式。")
        if link.firmware == MOTOR_TEST_FIRMWARE:
            print("1/2 单电机前进 | 3/4 单电机后退 | W/F/↑ 双电机前进 | S/X/空格/↓ 停止 | Q/Esc 退出")
        else:
            print("W/F/↑ 前进 | A/L/← 左转 | D/R/→ 右转 | S/空格/↓ 停止 | Q/Esc 退出")
        try:
            run_keyboard(msvcrt, link)
        except KeyboardInterrupt:
            pass
    finally:
        try:
            link.set_intent("S")
        finally:
            link.close()
