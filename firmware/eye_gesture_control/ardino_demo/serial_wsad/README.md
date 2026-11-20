# 原始 Arduino 程序的键盘串口测试

keyboard_serial.py 当前匹配上一级的 ardino_demo.ino，波特率 9600。
原始 Arduino 源文件未修改。本目录的 serial_wsad.ino 是另一套 WSAD 协议，当前 Python 脚本不与它配套。

## 使用

1. 双击 `start_keyboard.bat`。按回车或输入 `1` 进入模拟，终端显示 `[模拟]` 指令。
2. 需要实际发送时，开发板烧录上一级的 `ardino_demo.ino`，关闭 Arduino 串口监视器。启动时选 `2`，再输入主控板串口，例如 `COM5`。
3. 进入所选模式后实时检测以下按键，无需按回车。

| 按键 | 发送的单字节 ASCII | 动作 |
| --- | --- | --- |
| 1 | 1 | M1 前进 1 秒 |
| 2 | 2 | M2 前进 1 秒 |
| 3 | 3 | M1 后退 1 秒 |
| 4 | 4 | M2 后退 1 秒 |
| F | F | 两路前进 2 秒 |
| S、X、空格、松开全部动作键 | S | 请求停止 |
| Esc / Ctrl+C | S，然后退出 | 请求停止并退出 |

同时按多个动作键时发送 S。只有指令变化时才发送；按住不会重复排队，松开再按可重新测试。
默认每 10 ms 检测一次键盘，每 100 ms 持续打印当前检测状态；按键变化时立即打印。
例如按住 1 会持续显示 [KEY] 1 -> 1  M1前进，松开显示 [KEY] 无按键 -> S  停止。
[TX] 表示已写入电脑串口，[KEY] 表示当前按键对应的指令，均不代表电机实际状态。

原 Arduino 程序在动作期间阻塞读取串口。松键发出的 `S` 要等当前动作结束后才会处理。
原程序没有两路同时后退或原地左右转指令，因此测试键同步改为 1/2/3/4/F/S。

键盘使用 Windows 全局检测，切换窗口后仍会响应。暂停控制请按 Esc 退出。

## 环境和命令

启动脚本固定使用 D:\Anaconda_envs\mul_pro\python.exe，不创建新环境。
该环境已安装 pyserial。如以后缺失，可在 PowerShell 执行：

```powershell
& 'D:\Anaconda_envs\mul_pro\python.exe' -m pip install -r .\requirements.txt
```

在本目录指定串口运行会跳过菜单：

```powershell
& 'D:\Anaconda_envs\mul_pro\python.exe' -u .\keyboard_serial.py --port COM5
```

加 --list-ports 只列出串口，不连接或发送指令。
原程序电机引脚：M1 为 4/6/9，M2 为 5/7/10，PWM 为 40。
