"""交互式入口共用的串口模式选择，不打开设备。"""

import sys


def select_serial_port(port: str | None, *, firmware: str | None = None) -> str | None:
    """直接使用已指定的串口，或让交互式用户选择模拟或实际发送。"""
    if port is not None or sys.stdin is None or not sys.stdin.isatty():
        return port

    print("1. 模拟模式（默认）\n2. 实际发送到主控板")
    try:
        while True:
            choice = input("选择模式 [1/2]（回车选 1）：").strip()
            if choice in ("", "1"):
                return None
            if choice == "2":
                break
            print("请输入 1 或 2。")

        sketch = "wheelchair_controller.ino" if firmware == "wheelchair" else "ardino_demo.ino"
        print(f"请确认主控板烧录的是 {sketch}。")
        return input("输入主板串口（如 COM5，留空进入模拟模式）：").strip() or None
    except EOFError:
        return None
    except KeyboardInterrupt:
        print("\n已取消启动。")
        raise SystemExit(0) from None
