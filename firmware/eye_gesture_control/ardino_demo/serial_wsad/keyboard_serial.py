"""Windows 鍵盘测试。main() 选择输出模式，control() 轮询按键并输出指令。"""

import argparse
from contextlib import nullcontext
import ctypes
import os
from pathlib import Path
import sys
import time

SRC_DIR = str(Path(__file__).resolve().parents[4] / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from hardware.serial_mode import select_serial_port  # noqa: E402

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    raise SystemExit(
        'Missing pyserial. Install with: '
        r'D:\Anaconda_envs\mul_pro\python.exe -m pip install pyserial'
    )


KEY_CODES = {key: ord(key) for key in "1234FSX"}
KEY_CODES.update({"SPACE": 0x20, "ESC": 0x1B})
LABELS = {
    "1": "M1前进",
    "2": "M2前进",
    "3": "M1后退",
    "4": "M2后退",
    "F": "两路前进",
    "S": "停止",
}


def command_for_keys(keys):
    """Stop on release, conflicting movement keys, or explicit stop."""
    if set(keys).intersection({"S", "X", "SPACE"}):
        return "S"
    movement = set(keys).intersection("1234F")
    return next(iter(movement)) if len(movement) == 1 else "S"


def make_key_reader():
    if os.name != "nt":
        raise RuntimeError("此脚本使用 Windows 键盘接口，请在 Windows 上运行。")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    get_key_state = user32.GetAsyncKeyState
    get_key_state.argtypes = [ctypes.c_int]
    get_key_state.restype = ctypes.c_short

    def read_keys():
        # High bit reflects whether the key is currently held down.
        return {key for key, code in KEY_CODES.items() if get_key_state(code) & 0x8000}

    return read_keys


def send_command(connection, command):
    """发送或模拟一个 ASCII 指令。connection 为 None 时只打印。"""
    if connection is None:
        print(f"[模拟] 指令 {command}  {LABELS[command]}", flush=True)
        return
    data = command.encode("ascii")
    if connection.write(data) != len(data):
        raise serial.SerialTimeoutException("串口指令未完整发送")
    print(f"[TX] {command}  {LABELS[command]}", flush=True)


def control(connection, read_keys, poll_seconds):
    """模拟与串口模式共用按键轮询、指令去重和退出停车。"""
    try:
        if connection is None:
            print("键盘模拟模式。")
        else:
            # Opening many Arduino boards resets them. Let setup() finish first.
            print("串口已打开，等待开发板启动 2 秒……")
            time.sleep(2.0)
            connection.reset_input_buffer()
        send_command(connection, "S")
        last_command = "S"
        last_keys = None
        last_status_time = 0.0
        print("已就绪：1=M1前进，2=M2前进，3=M1后退，4=M2后退，F=两路前进。")
        print("S/X/空格或松键发送 S 停止，Esc 退出；无需按回车。")
        print("原固件单电机运行约 1 秒，F 运行约 2 秒；按住不重复发送。")
        print("原固件在动作结束后处理新的串口指令，包括停止指令。")
        print("持续检测键盘：每 100 ms 打印当前状态，按键变化时立即打印。")
        print("键盘为全局检测，切换到其他窗口后仍会响应这些按键。")
        print("同时按多个动作键时发送 S。串口监视器须先关闭。")
        while True:
            keys = read_keys()
            if "ESC" in keys:
                break
            command = command_for_keys(keys)
            if command != last_command:
                send_command(connection, command)
                last_command = command
            now = time.monotonic()
            if keys != last_keys or now - last_status_time >= 0.1:
                held = "+".join(sorted(keys)) if keys else "无按键"
                print(f"[KEY] {held} -> {command}  {LABELS[command]}", flush=True)
                last_keys = set(keys)
                last_status_time = now
            # Drain the Arduino acknowledgements without blocking polling.
            if connection is not None:
                waiting = connection.in_waiting
                if waiting:
                    connection.read(min(waiting, 4096))
            time.sleep(poll_seconds)
    finally:
        # Runs on Esc, Ctrl+C, and ordinary Python exceptions while open.
        try:
            send_command(connection, "S")
            if connection is not None:
                connection.flush()
                print("已发送停止指令。")
        except (serial.SerialException, OSError) as error:
            print(f"停止指令未能发送：{error}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="实时检测 1/2/3/4/F/S，匹配原始 ardino_demo.ino")
    parser.add_argument("--port", help="直接连接指定串口，例如 COM3")
    parser.add_argument("--baud", type=int, default=9600, help="波特率，默认 9600")
    parser.add_argument("--poll-ms", type=float, default=10, help="键盘检测间隔，默认 10 ms")
    parser.add_argument("--list-ports", action="store_true", help="仅列出串口，不连接")
    args = parser.parse_args()
    if args.baud <= 0 or args.poll_ms <= 0:
        parser.error("--baud 和 --poll-ms 必须大于 0")
    if args.list_ports:
        ports = list(list_ports.comports())
        for port in ports:
            print(f"{port.device}: {port.description}")
        if not ports:
            print("未找到串口。")
        return 0
    try:
        port = select_serial_port(args.port)
        read_keys = make_key_reader()
        connection = None
        if port is not None:
            print(f"正在连接 {port}，波特率 {args.baud}……")
            try:
                connection = serial.Serial(port, args.baud, timeout=0, write_timeout=0.5)
            except (serial.SerialException, OSError) as error:
                print(f"串口未连接，已切到模拟模式。{error}")
        with (connection if connection is not None else nullcontext()) as link:
            control(link, read_keys, args.poll_ms / 1000.0)
        return 0
    except (KeyboardInterrupt, EOFError):
        print("已退出。")
        return 0
    except (serial.SerialException, OSError, RuntimeError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
