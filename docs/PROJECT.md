# EyeWheelchairProject — 分支概览 / Branch Overview

## 项目状态：暂时封存 / Project status: temporarily shelved

**2026-10-18，项目组决定整体暂时封存本项目。** 经项目组自评，目前整体技术与工程能力尚未达到本项目要求，暂不具备继续推进、完成充分验证并负责任交付该项目的能力与条件。现阶段停止主动开发和交付推进，保留现有代码、模型、实验结果与文档，作为学习和后续复盘资料。待团队能力与验证条件达到要求后，再评估是否恢复。

**On 2026-10-18, the team decided to temporarily shelve the entire project.** Our current technical and engineering capabilities do not yet meet its requirements, and we are not ready to advance, adequately validate or responsibly deliver it. Active development and delivery are paused. Existing code, models, experiments and documentation are retained for study and review; resumption will be reconsidered when the team's capabilities and validation conditions are sufficient.

### 仓库归并声明 / Repository consolidation

- 原独立 YOLO 项目的归并记录见 [EyeWheelchairProject 历史归档](https://github.com/aaf12329/EyeWheelchairProject)。
- 下文标为「封存前」的设计和进度属于历史资料。当前入口与运行方法见 [根目录 README](../README.md)。

- The former YOLO project's consolidation is recorded in the [EyeWheelchairProject archive](https://github.com/aaf12329/EyeWheelchairProject).
- Sections marked as historical describe work before shelving. See the [root README](../README.md) for the current entry points and run instructions.

---

用普通 USB 摄像头实现“注视选方向 + 眨眼确认”的眼控轮椅原型。当前默认运行屏幕模拟，串口层与 Arduino 固件已实现，实机联调和台架验证仍待完成。

An eye-controlled wheelchair prototype using a USB camera for gaze selection and blink confirmation. Screen simulation is the default; the serial layer and Arduino firmware are implemented, with hardware integration and bench verification still pending.

## 分支结构及简述 / Branch Structure and Summary

以下为 **2026-10-12 核对远端后的分支状态**。树形图表示协作分工，各分支的实际差异见下表。

The following snapshot was checked against the remote on **2026-10-12**. The tree shows collaboration roles; the table describes the actual branch differences.

```text
EyeWheelchairProject
├─ main   主干 / Mainline
├─ huang  组员开发分支 / Contributor development branch
└─ chen   视觉检测迁移与对比验证 / Vision migration and comparison
```

| 分支 / Branch | 当前内容 / Current contents | 与主干的关系 / Relation to main |
|---|---|---|
| `main` | MediaPipe 人脸/手部关键点、眨眼与视线交互、默认模拟的串口层，以及按 Arduino IDE 规则分目录的固件。 / MediaPipe landmarks, blink/gaze interaction, simulated serial output, and firmware in Arduino IDE sketch folders. | 当前文档与运行说明的基准；由所有者维护和合并。 / Baseline for the documentation below; maintained and merged by the owner. |
| `huang` | 与主干采用相同的 MediaPipe 检测链路，供组员独立开发。 / Contributor branch using the same MediaPipe detection pipeline as main. | 落后 `main` 2 个提交，无独有提交；尚未包含主干最新的 README 同步与固件目录调整。 / 2 commits behind main, with no unique commits; missing the latest README update and firmware folder changes. |
| `chen` | 新增 `src/common/` 公共模块、YuNet + YOLO 眼动后端；眨眼/视线预览支持 YOLO 与 MediaPipe 同帧对比及逐帧 CSV；确认演示使用 YOLO，并补充接线与交接资料。 / Shared utilities, YuNet + YOLO backend, YOLO/MediaPipe comparison with per-frame CSV in blink/gaze previews, a YOLO confirmation demo, and wiring/handover notes. | 有 12 个独有提交，同时缺少 `main` 的 2 个独有提交，尚未合并；固件仍采用旧路径。 / 12 unique commits and missing 2 main-only commits; not merged, with firmware still at the old paths. |

上表是原项目的历史记录。下文的目录、依赖和运行方法适用于本仓库的 **`chen/main`**。眼动使用 MediaPipe，手眼预览另外运行 ONNX 手势模型。

The table records the original project's branches. The sections below describe this repository's **`chen/main`**. Eye tracking uses MediaPipe, and the hand-eye preview also runs an ONNX gesture model.

README 有中文版本和英文版本，中文在上，英文在下；协作流程见 [GIT_GUIDE.md](GIT_GUIDE.md)，开发与代码规范见 [Agent.md](Agent.md)。
The Chinese version appears first, followed by the English version; see [GIT_GUIDE.md](GIT_GUIDE.md) for the collaboration workflow and [Agent.md](Agent.md) for development and code standards.


## 中文版（Chinese）

# EyeWheelchairProject（眼控轮椅原型）

Eye-controlled wheelchair prototype — gaze + blink interaction. Python side runs as a pure screen simulation by default; the Arduino firmware and serial layer are written but not yet verified on the real chair.

用普通 USB 摄像头识别"眼睛在看哪个方向"和"有没有眨眼"，先把**眼控交互**这条路走通。

> ⚠️ **安全边界**：Python 端默认使用**模拟模式**。实际发送需要通过菜单或命令行明确指定主控板串口。Arduino 固件（`firmware/`）与串口输出层
> （`src/hardware/`）已经写好，但**未台架验证、默认关闭**；台架清单全过且加装物理急停按钮之前，
> 不进行任何载人测试。

---

## 交互设计（封存前设计）

最终要做的是"注视选方向 + 眨眼当确认键"，替代摇杆：

1. **校准（3 秒）**：睁眼看屏幕正中间，程序量出你自己的"睁眼基线"，并派生出两条判定线（闭眼线 / 睁眼线）。
   每个人的眼型、眼镜、坐姿距离都不同，所以阈值必须由本人现场标定，不能写死。
2. **选方向**：视线移到屏幕左 / 中 / 右（或左转 / 前进 / 右转），同一方向稳定停留约 0.7 秒才成为候选。
3. **眨眼确认**：一次自然眨眼（闭眼约 0.04~0.8 秒）才算数；闭得太短当噪声忽略，闭得太久（眯眼、闭目休息）不算。
   两次计数之间留 0.3 秒不应期，避免一次眨眼被数成两三次。

为什么用两个维度（视线 + 眨眼）：视线负责"选"，眨眼负责"确认"，避免视线一扫过就把指令发出去。

## 目录结构

```
wheerchair_mediapipe/
├─ src/
│  ├─ camera/
│  │  ├─ camera_preview.py            第 1 周：摄像头基线（预览 / 录像 / 截图）
│  │  └─ video_input.py               摄像头、录像和播放节奏
│  ├─ common/
│  │  ├─ paths.py                     模型和输出目录
│  │  └─ preview_ui.py                窗口检查、按键去抖和中文状态绘制
│  ├─ vision/
│  │  ├─ landmarks_preview.py         第 2 周：人脸 478 点 + 手部 21 点可视化
│  │  ├─ mediapipe_video.py           建检测器、预处理和单帧推理
│  │  ├─ eye_geometry.py              眼部索引、双眼开合比和虹膜位置
│  │  ├─ hand_gesture_detector.py     ONNX 手势分类、检测框与置信度
│  │  └─ landmark_drawing.py         眼睛、脸部和手部骨架绘制
│  ├─ interaction/
│  │  ├─ blink_preview.py             第 3 步：眨眼校准与计数（已重构，含测试）
│  │  ├─ gaze_direction_preview.py    第 4 步：视线方向选择（左 / 中 / 右）
│  │  ├─ gaze_blink_confirm_demo.py   第 5 步：视线选方向 + 眨眼确认（界面美化版，接串口层）
│  │  ├─ hand_eye_preview.py         同帧显示手势和眼睛，输出眼动确认指令
│  │  ├─ keyboard_serial.py           Windows 终端键盘输入与方向指令
│  │  ├─ *_state.py                   眨眼、视线方向和眨眼确认状态机
│  │  └─ wheelchair_control.py       两个演示共用的方向下发和丢脸停车逻辑
│  └─ hardware/
│     ├─ serial_mode.py               选择模拟或实际串口
│     └─ serial_link.py               串口输出层：意图→指令、心跳、电池、低电锁（默认模拟）
├─ tests/                             pytest：眨眼判定 / 串口链路 / 界面渲染 + 模型冒烟测试
├─ firmware/
│  ├─ wheelchair_controller/        Arduino 修订版固件，协议 wheelchair
│  └─ eye_gesture_control/
│     └─ ardino_demo/ardino_demo.ino 原始电机测试草图，协议 motor-test
├─ Related_materials/                 硬件照片、参考固件（ardino_demo.ino）等资料
├─ models/                            MediaPipe 模型文件（face / hand landmarker，已入库）
├─ data/                              录制素材（raw_videos / snapshots）
├─ docs/                             项目说明、开发规范、依赖和 Git 指南
└─ README.md
```

各演示入口可独立运行。手眼预览复用 MediaPipe 人脸检测器、眨眼与视线状态机、录像输入，并用 ONNX 输出手势分类。它与第 5 步演示共用方向下发逻辑，默认以屏幕模拟运行。

## 协作与分支（2026-09-30 起）

多人协作启动，分支规则如下：

| 分支 | 用途 | 规则 |
|---|---|---|
| `main` | 主干 | 由所有者维护与合并，**组员不要直接 push** |
| `huang` / `chen` | 组员开发分支 | 一人一分支，**只推自己的分支** |

- **组员上手**：先读 [GIT_GUIDE.md](GIT_GUIDE.md)（一次性配置、克隆、每日循环、
  提交信息格式、入库红线、问题急救、速查表），10 分钟可开工。
- **提交信息**：沿用本仓库惯例——`CH:` / `EN:` 双语、中文在前、一行说清做了什么。
- **干完活**：push 自己分支 → 所有者审核后合并进 main（`git switch main && git merge huang`）。
- **红线**：虚拟环境（`myvenv/` 等）、密钥、大体积原始数据永不入库（见 `.gitignore`）。

## 代码组织

`main()` 负责启动设备和组织每帧调用。状态机只接收时间、关键点或数字，通过 `update()` 返回快照，通过 `reset()` 重新校准。

```text
摄像头 / MP4 → video_input.py → BGR 帧 (H, W, 3)
  ├─ mediapipe_video.py → 镜像 RGB 图和毫秒时间戳 → 眼部关键点
  │        → eye_geometry.py → 双眼开合比 / 虹膜横向位置 → *_state.py
  │        → 已确认方向 → WheelchairControl → WheelchairLink → 模拟或串口
  └─ hand_gesture_detector.py → 手势类别 / 置信度 / 检测框 → 预览画面和终端
Windows 终端按键 → keyboard_serial.py → WheelchairLink → 模拟或串口
```

`common/paths.py` 集中管理模型、录像和截图路径。独立的 `landmarks_preview.py` 使用 MediaPipe 绘制手部骨架。原版固件的串口编码见 [电机测试固件](#原始电机测试固件--original-motor-test-firmware)。

## 环境准备

需要 Python 3.10 以上（开发环境是 3.13 / 3.14）。

```bash
python -m venv venv
venv\Scripts\python.exe -m pip install opencv-contrib-python mediapipe numpy pillow pyserial onnxruntime pytest
```

在 Git Bash 里把 `venv\Scripts\python.exe` 写成 `venv/Scripts/python.exe`，下文同理。

## 运行

以下命令从仓库根目录运行。

```bash
venv\Scripts\python.exe src\interaction\blink_preview.py
```

在终端启动主眼动演示或手眼预览时，按回车或选 `1` 进入模拟，选 `2` 后填写主控板串口进行实际发送。可以用 `--serial-port COM3` 跳过菜单直接连接，或用 `--video` 在模拟模式下播放录像。

```powershell
python .\src\interaction\gaze_blink_confirm_demo.py --video "C:\path\to\recording.mp4"
```

手眼预览在同一帧运行 MediaPipe 眼动检测和 `gaze_wheelchair_pack` 的 `best.onnx` 手势分类。开始时睁眼看画面正中约 3 秒以校准视线与眨眼。手势结果以检测框、类别和置信度显示，类别变化时在终端打印。

手势预览默认加载随仓库提供的 [`models/gesture_best.onnx`](../models/gesture_best.onnx)。这是 `gaze_wheelchair_pack` 的 `retinaface_arcface/best.onnx` 原始权重。可通过 `--gesture-model` 指定其他兼容模型。

| 类别 / Class | 显示 / Label |
|---|---|
| `0` | `Stop` |
| `1` | `Forward` |
| `2` | `Backward` |
| `3` | `Left` |
| `4` | `Right` |
| `5` | `Invalid` |

串口仍由眼动确认或键盘控制。`motor-test` 是实际连接时的默认协议，眼控可发送前进与停止。选择修订版固件的 `--firmware wheelchair` 可使用转向、心跳和电池查询。

```powershell
python .\src\interaction\hand_eye_preview.py
python .\src\interaction\hand_eye_preview.py --video "C:\path\to\recording.mp4"
python .\src\interaction\hand_eye_preview.py --serial-port COM3
```

| 脚本 | 按键 |
|---|---|
| `src/camera/camera_preview.py` | `Q` 退出 · `R` 开始/停止录像 · `S` 截图 |
| `src/vision/landmarks_preview.py` | `Q` 退出 · `S` 保存带关键点的截图 |
| `src/interaction/blink_preview.py` | `Q` 退出 · `C` 重新校准 |
| `src/interaction/gaze_direction_preview.py` | `Q` 退出 · `C` 重新校准 · `I` 反转左右 |
| `src/interaction/gaze_blink_confirm_demo.py` | `Q` 退出 · `C` 重新校准 · `I` 反转左右 |
| `src/interaction/hand_eye_preview.py` | `Q` 退出并停止 · `S` 停止 · `C` 停止并重新校准 · `I` 反转左右 |

两个使用前提：

- **先点一下视频窗口再按键**——OpenCV 的按键来自窗口焦点，焦点在终端上时按 Q 是没有反应的。
- 摄像头打不开时：关掉占用摄像头的软件（会议、相机 App），或把脚本顶部的 `CAMERA_INDEX` 从 `0` 改成 `1`。

### 键盘模式 / Keyboard mode

在 Windows 终端运行，按键从终端读取，无需摄像头。第一条命令打开模式菜单，按回车即可模拟原始固件。第二条直接连接串口，将 COM3 换成主控板串口。

Run this in an interactive Windows terminal. The first command opens the mode menu. Press Enter to simulate the original firmware. The second connects directly to the controller. Replace COM3 with its serial port.

```powershell
python .\src\interaction\hand_eye_preview.py --keyboard --firmware motor-test
python .\src\interaction\hand_eye_preview.py --keyboard --serial-port COM3
```

| 按键 / Keys | 原始固件指令 / Motor-test command |
|---|---|
| `1` / `2` | M1 / M2 单电机前进 / Run M1 or M2 forward |
| `3` / `4` | M1 / M2 单电机后退 / Run M1 or M2 backward |
| `W` / `F` / ↑ | `F` 双电机前进 / Both motors forward |
| `S` / `X` / 空格 / ↓ | `S` 请求停止 / Request stop |
| `Q` / `Esc` | 请求停止并退出 / Request stop and quit |

约 0.7 秒没有再收到动作键输入时，Python 发送停止请求。修订版轮椅固件用 `--firmware wheelchair`，其键盘模式使用 `A` / ← 左转、`D` / → 右转，并保留心跳和电池查询。

After about 0.7 seconds without another motion key event, Python sends a stop request. With the revised controller, use `--firmware wheelchair` for `A` / ← left and `D` / → right, plus its heartbeat and battery polling.

## 测试

```bash
venv\Scripts\python.exe -m pytest -q
```

离线测试覆盖眨眼判定、视线选方向、候选取消、主演示确认左转 / 前进 / 右转、串口模拟、界面渲染、模型推理和 MP4 播放。合成关键点用例会检查取消旧方向后，模拟链路只收到重新选择且眨眼确认的方向。
测试无需摄像头和实机。使用本地录像的用例在 `data/raw_videos` 没有可用文件时自动跳过。

改代码的习惯：**改动前后各跑一次 `pytest`**。它会把"这次改动有没有破坏原有行为"直接告诉你，不用开摄像头靠肉眼验证。

## 硬件与固件

视觉端（Python）之外，下位机方案已经成型：

| 部件 | 说明 |
|---|---|
| 主控 | Arduino Uno 兼容板（ATmega328P-AU，16MHz，5V 逻辑） |
| 电机驱动 | BTS7960 大电流双 H 桥模块（带散热片） |
| 电机 | 12-24V 直流电机 ×2（左右轮差速转向） |
| 电压传感器 | 0-25V 分压模块 → A0（监测电池） |
| 供电 | 锂电池组（满电约 25V）；电机电源直接取自电池，**不经过** Uno 的 5V 稳压 |

```
PC（Python + pyserial，9600 波特）──串口指令──▶ ATmega328P ──INA/INB/PWM──▶ BTS7960 ×2 ──▶ 左右电机
电池 ──▶ 0-25V 电压传感器（1:5 分压）──▶ A0
```

### 原始电机测试固件 / Original motor-test firmware

`ardino_demo.ino` 原样复制自 `eye_gesture_control` 的 `8124d30`。指定真实串口时 Python 默认使用此协议，9600 波特，发送单字节。 [原始固件](../firmware/eye_gesture_control/ardino_demo/ardino_demo.ino)

The sketch is copied unchanged from `eye_gesture_control` at `8124d30`. When a physical port is specified, Python defaults to this 9600-baud single-byte protocol.

同一目录下的 [串口键盘测试工具](../firmware/eye_gesture_control/ardino_demo/serial_wsad/README.md) 支持相同的启动菜单。该目录的 `keyboard_serial.py` 配合上一级的 `ardino_demo.ino` 使用，`serial_wsad.ino` 是独立的 WSAD 测试固件。

The [keyboard serial test tools](../firmware/eye_gesture_control/ardino_demo/serial_wsad/README.md) support the same startup menu. The directory's `keyboard_serial.py` pairs with the parent `ardino_demo.ino`, and `serial_wsad.ino` is a standalone WSAD test sketch.

| 串口字节 / Byte | 固件行为 / Action |
|---|---|
| `1` / `2` | M1 / M2 单电机前进约 1 秒 / Run M1 or M2 forward for about one second |
| `3` / `4` | M1 / M2 单电机后退约 1 秒 / Run M1 or M2 backward for about one second |
| `F` | 双电机前进约 2 秒 / Run both motors forward for about two seconds |
| `S` | 请求停止 / Request stop |

原始草图在动作期间阻塞处理串口，`S` 要等当前动作结束后才会被处理。Python 在动作期间拦截新的运动指令，跳过心跳和电池查询。该草图已通过 Uno 编译，实机串口和台架尚未测试。

The sketch reads the next serial command after the current pulse finishes. Python suppresses additional motion commands during a pulse and skips heartbeat and battery polling. The sketch compiled for Uno. Serial hardware and bench verification are pending.

### 修订版轮椅固件协议（`--firmware wheelchair`）

| 指令 | 动作 |
|---|---|
| `0` / `S` | 停止 |
| `1` / `F` | 前进 |
| `2` / `B` | 后退 |
| `L` / `R` | 原地左转 / 右转 |
| `3` / `4` | 左半速 / 右半速前进（弧线行驶） |
| `GET_DATA` | 回报 `BATTERY:百分比,电压×10`（如 `BATTERY:87,218` = 87%、21.8V） |

固件内置四层安全机制：**3 秒收不到指令自动急停**（因此 Python 端必须周期性重发当前指令当心跳）、
换向/转向**先减速停稳再执行**、低电（≤19.0V）**只允许停止指令**（回升到 19.5V 才解锁）、
**看门狗**（程序卡死 2 秒自动复位停机）。

两个固件文件按原项目归档版本恢复。 [归档提交 `de96851`](https://github.com/aaf12329/history_code/tree/de968515288c61432969fd85e9cd9e2ee9ef869d/EyeWheelchairProject)

- 原始参考草图按字节保留。 [原始参考草图](../Related_materials/ardino_demo/ardino_demo.ino)
- 修订版控制器包含看门狗、串口 char 缓冲、转向先停、
  PWM 频率修正（约 18kHz）、电池平均+迟滞、低电限流等，每处改动带【修订】标记，
  文件底部有 **7 条台架验证清单**（接线核对、噪音/温度、看门狗、长跑、转向先停、低电模拟、电压对表）。 [修订版控制器](../firmware/wheelchair_controller/wheelchair_controller.ino)

两个草图均通过 Arduino Uno 编译检查（Arduino AVR Boards 1.8.8、TimerOne 1.1.1）。台架验证仍待完成。

Python 端的串口输出层也已落地：`src/hardware/serial_link.py`
（`WheelchairLink` 类：意图翻译成协议字母、当前指令每 1 秒心跳重发、每 2 秒 `GET_DATA`
轮询电池、低电双重保险强制停车；`port=None` 时为**模拟模式**，无硬件也能跑全套测试）。
低电回报或固件低电告警会在下一条心跳之前将当前指令切为停止。解除低电锁后，原运动指令不会自动恢复。
终端会打印每条成功写入的协议指令，包括每次心跳和电池查询，例如 `[串口 COM3] 已发送 F` 和 `[串口 COM3] 已发送 GET_DATA`。屏幕模拟使用 `[模拟] 指令 F` 一类的提示。
`gaze_blink_confirm_demo.py` 默认使用屏幕模拟。与该修订版固件联调时使用 `--serial-port COM3 --firmware wheelchair`。

> ⚠️ 烧录前需在 Arduino IDE 安装 **TimerOne** 库；台架清单全部通过**且加装物理急停按钮**（直接切断
> 电机电源）之后，才允许载人测试。

## 进度（封存前记录）

| 阶段 | 内容 | 状态 |
|---|---|---|
| 第 1 周 | 摄像头基线（预览 / 录像 / 截图） | ⚠️ 重构版待实机完整验证 |
| 第 2 周 | MediaPipe 人脸与手部关键点可视化 | ✅ 已重构（初步测试通过） |
| 第 3 步 | 眨眼校准与计数（重构 + 单元测试） | ✅ 已实测通过 |
| 第 4 步 | 视线方向选择（左 / 中 / 右） | ✅ 已重构（初步测试通过） |
| 第 5 步 | 视线选方向 + 眨眼确认（屏幕演示） | ✅ 已重构（初步测试通过） |
| 代码整理 | 四个脚本统一为三段式结构 + 调用关系注释，判定逻辑可单测 | ✅ |
| 固件 | Arduino 控制器安全修订版（看门狗/char 缓冲/转向先停/PWM 频率），含台架清单 | 🔶 已写好，待台架验证 |
| 串口输出层 | `src/hardware/serial_link.py`（心跳/电池轮询/低电锁/模拟模式），含 12 条测试 | 🔶 已写好，待接实机 |
| 下一步 | 台架验证固件 → 插上 Arduino 实机联调串口层 | ⬜ 未开始 |

## 已知问题与注意事项

1. **退出行为**。Windows 上销毁 MediaPipe 检测器曾出现长时间阻塞，`mediapipe_video.py` 保留检测器引用，由系统在进程退出时回收。
2. **`camera_preview.py` 实机验证待完成**。离线测试覆盖预览流程、录像写入和截图保存。
3. **依赖未锁版本**：`requirements.md` 里没有写版本号，换机器或升级可能踩到 API 变化。
   当前开发环境实测为 mediapipe 1.0.1 + opencv 5.0.0，交付前建议锁定版本。
4. **左右镜像约定**：交互类脚本对画面做了水平镜像（`cv2.flip`），让屏幕里的"左/右"与使用者的体感一致；
   `camera_preview.py` 不做镜像，所以它录下来的视频是"对面看你"的视角，与截图视角相反。
   如果实机上发现左右判断相反，按 `I` 反转。
5. **窗口标题**使用英文。窗口内的中文状态由 Pillow 和系统字体绘制。
6. **中文字体**由 `preview_ui.py` 按 `msyh.ttc → simhei.ttf → arial.ttf` 顺序加载并缓存。摄像头和关键点独立预览只显示英文。
7. `data/raw_videos/` 里 2026-09-16 的录像文件都是 0 字节空壳（当时录屏未写入成功），已从版本库中删除。

### 当前分支的方向确认

- 校准结束后，持续注视正中约 0.7 秒即可选中「前进」。
- 等待眨眼时，睁眼注视另一个方向会取消原候选。人脸丢失会清除方向和眨眼的计时，重新检测到人脸后需要重新注视并眨眼。
- `blink_preview.py` 在 30 fps 下可能将单帧闭眼平滑后计为一次眨眼。

## 后续计划

1. **实机完整验证 `camera_preview.py`**：重构版还没完整跑过，用之前先测预览 / 录像 / 截图三项。
2. **台架验证修订版轮椅固件**：按文件底部 7 条清单逐项过
   （接线核对 → PWM 噪音/温度 → 看门狗 → 长跑 → 转向先停 → 低电模拟 → 电压对表），
   全过后加装物理急停按钮。
3. **实机联调修订版轮椅固件**：使用 `--serial-port` 和 `--firmware wheelchair`，验证心跳保活、`GET_DATA` 电池回报和低电强制停车。


## English Version
# EyeWheelchairProject (Eye-Controlled Wheelchair Prototype)

Eye-controlled wheelchair prototype — gaze + blink interaction. The Python side runs as a pure screen simulation by default; the Arduino firmware and serial layer are written but not yet verified on the real chair.

Using an ordinary USB camera to recognize "which direction the eyes are looking" and "whether there is a blink," the goal is to first get the **eye-control interaction** path working.

> ⚠️ **Safety boundary**: the Python programs default to **simulation**. Sending commands requires explicitly selecting the controller's port from the menu or command line. Bench verification of the Arduino firmware (`firmware/`) and serial layer (`src/hardware/`) is pending. Human ride testing requires a completed bench checklist and a physical e-stop button.

---

## Interaction Design

The final goal is "gaze to select direction + blink as confirmation key," replacing the joystick:

1. **Calibration (3 seconds)**: Keep your eyes open and look at the center of the screen; the program measures your own "open-eye baseline" and derives two decision lines (closed-eye line / open-eye line). Everyone's eye shape, glasses, and sitting distance are different, so the thresholds must be calibrated on-site by the user and cannot be hard-coded.
2. **Select direction**: Move your gaze to the left / center / right of the screen (or left turn / forward / right turn). The same direction must remain stable for about 0.7 seconds before becoming a candidate.
3. **Blink confirmation**: Only a natural blink (eyes closed for about 0.04–0.8 seconds) counts; too short is ignored as noise, too long (squinting, eyes closed resting) does not count. A 0.3-second refractory period is left between two counts to avoid a single blink being counted two or three times.

Why use two dimensions (gaze + blink): gaze is responsible for "selecting," blink is responsible for "confirming," preventing an instruction from being sent just because the gaze swept across.

## Directory Structure

```
wheerchair_mediapipe/
├─ src/
│  ├─ camera/
│  │  ├─ camera_preview.py            Week 1: Camera baseline (preview / record / snapshot)
│  │  └─ video_input.py               Camera, recordings, and playback timing
│  ├─ common/
│  │  ├─ paths.py                     Model and output paths
│  │  └─ preview_ui.py                Window state, key debounce, and status text
│  ├─ vision/
│  │  ├─ landmarks_preview.py         Week 2: Face 478 points + hand 21 points visualization
│  │  ├─ mediapipe_video.py           Detector setup, preprocessing, and per-frame inference
│  │  ├─ eye_geometry.py              Eye indices, eye aspect ratio, and iris position
│  │  ├─ hand_gesture_detector.py     ONNX gesture classes, boxes, and scores
│  │  └─ landmark_drawing.py         Eye, face, and hand overlays
│  ├─ interaction/
│  │  ├─ blink_preview.py             Step 3: Blink calibration and counting (refactored, with tests)
│  │  ├─ gaze_direction_preview.py    Step 4: Gaze direction selection (left / center / right)
│  │  ├─ gaze_blink_confirm_demo.py   Step 5: Gaze selects direction + blink confirmation (restyled UI, wired to the serial layer)
│  │  ├─ hand_eye_preview.py         Gesture and eye preview with gaze-confirmed direction commands
│  │  ├─ keyboard_serial.py           Windows terminal input and direction commands
│  │  ├─ *_state.py                   Blink, gaze direction, and blink confirmation state machines
│  │  └─ wheelchair_control.py       Direction output and face-loss stop shared by both demos
│  └─ hardware/
│     ├─ serial_mode.py               Choose simulation or physical serial output
│     └─ serial_link.py               Serial output layer: intent→command, heartbeat, battery, low-battery lock (simulated by default)
├─ tests/                             pytest: blink logic / serial link / UI rendering + model smoke test
├─ firmware/
│  ├─ wheelchair_controller/        Revised Arduino controller, using the wheelchair protocol
│  └─ eye_gesture_control/
│     └─ ardino_demo/ardino_demo.ino Original motor-test sketch
├─ Related_materials/                 Hardware photos, reference firmware (ardino_demo.ino), etc.
├─ models/                            MediaPipe model files (face / hand landmarker, checked in)
├─ data/                              Recorded materials (raw_videos / snapshots)
├─ docs/                             Project, development, dependency, and Git guides
└─ README.md
```

Each demo has a standalone entry point. The hand and eye preview reuses the face and hand detectors, the blink and gaze state machines, and video input. It shares direction output with the step 5 demo. Both default to on-screen simulation.

## Collaboration and Branches (since 2026-09-30)

Multi-contributor collaboration has started, with the following branch rules:

| Branch | Purpose | Rule |
|---|---|---|
| `main` | Trunk | Maintained and merged by the owner — **members do not push directly** |
| `huang` / `chen` | Per-member dev branches | One branch per member; **push only your own branch** |

- **New members**: read [GIT_GUIDE.md](GIT_GUIDE.md) first (one-time setup, clone, daily loop, commit message format, red lines, first aid, cheat sheet) — 10 minutes and you can start.
- **Commit messages** keep this repo's convention: `CH:` / `EN:` bilingual, Chinese first, one line saying what changed.
- **When done**: push your branch → the owner reviews and merges into main (`git switch main && git merge huang`).
- **Red lines**: virtualenvs (`myvenv/` etc.), secrets and large raw data files never get committed (see `.gitignore`).

## Code Organization

`main()` starts the devices and coordinates the frame loop. State machines take time, landmarks, or numeric measurements. `update()` returns a snapshot and `reset()` starts calibration again.

```text
Camera / MP4 → video_input.py → BGR frame (H, W, 3)
  ├─ mediapipe_video.py → mirrored RGB image and millisecond timestamp → eye landmarks
  │       → eye_geometry.py → eye aspect ratio / horizontal iris position → *_state.py
  │       → confirmed direction → WheelchairControl → WheelchairLink → simulation or serial
  └─ hand_gesture_detector.py → class / score / box → preview and terminal
Windows terminal keys → keyboard_serial.py → WheelchairLink → simulation or serial
```

`common/paths.py` is the registry for models, recordings, and snapshots. The standalone `landmarks_preview.py` still renders MediaPipe hand skeletons. The command bytes are documented in [Original motor-test firmware](#原始电机测试固件--original-motor-test-firmware).

## Environment Setup

Requires Python 3.10 or above (development environment is 3.13 / 3.14).

```bash
python -m venv venv
venv\Scripts\python.exe -m pip install opencv-contrib-python mediapipe numpy pillow pyserial onnxruntime pytest
```

In Git Bash, write `venv\Scripts\python.exe` as `venv/Scripts/python.exe`; the same applies below.

## Running

Run the commands below from the repository root.

```bash
venv\Scripts\python.exe src\interaction\blink_preview.py
```

When starting the main gaze demo or hand and eye preview in a terminal, press Enter or choose `1` for simulation. Choose `2` and enter the controller's serial port to send commands. Use `--serial-port COM3` to connect directly or `--video` to play a recording in simulation.

```powershell
python .\src\interaction\gaze_blink_confirm_demo.py --video "C:\path\to\recording.mp4"
```

The hand-eye preview runs MediaPipe eye tracking and `best.onnx` gesture detection from `gaze_wheelchair_pack` on the same frame. It draws gesture boxes, labels, and confidence scores, and logs class changes. Keep your eyes open and look at the centre for about three seconds to calibrate gaze and blinking.

The preview loads the bundled [`models/gesture_best.onnx`](../models/gesture_best.onnx) by default. It is an unchanged copy of `retinaface_arcface/best.onnx` from `gaze_wheelchair_pack`. Use `--gesture-model` to select another compatible model. Classes `0`–`5` are Stop, Forward, Backward, Left, Right, and Invalid.

Confirmed eye movements and keyboard input drive serial control. New serial connections default to `motor-test`, with forward and stop available from eye control. Select `--firmware wheelchair` on the revised controller for turning, heartbeat, and the battery query.

```powershell
python .\src\interaction\hand_eye_preview.py
python .\src\interaction\hand_eye_preview.py --video "C:\path\to\recording.mp4"
python .\src\interaction\hand_eye_preview.py --serial-port COM3
```

| Script | Keys |
|---|---|
| `src/camera/camera_preview.py` | `Q` quit · `R` start/stop recording · `S` snapshot |
| `src/vision/landmarks_preview.py` | `Q` quit · `S` save snapshot with landmarks |
| `src/interaction/blink_preview.py` | `Q` quit · `C` recalibrate |
| `src/interaction/gaze_direction_preview.py` | `Q` quit · `C` recalibrate · `I` invert left/right |
| `src/interaction/gaze_blink_confirm_demo.py` | `Q` quit · `C` recalibrate · `I` invert left/right |
| `src/interaction/hand_eye_preview.py` | `Q` stop and quit · `S` stop · `C` stop and recalibrate · `I` invert left/right |

Two prerequisites:

- **Click the video window first, then press keys** — OpenCV key events come from window focus; when focus is on the terminal, pressing Q has no effect.
- If the camera cannot open: close software occupying the camera (meetings, camera apps), or change `CAMERA_INDEX` at the top of the script from `0` to `1`.

See [Keyboard mode](#键盘模式--keyboard-mode) for terminal keyboard input and serial output.

## Testing

```bash
venv\Scripts\python.exe -m pytest -q
```

The offline suite covers blink detection, gaze selection, candidate cancellation, left/forward/right confirmation through the main demo, serial simulation, rendering, model inference, and MP4 playback. Synthetic landmark tests check that after a candidate is cancelled, the simulated link receives only the newly selected and confirmed direction.
The tests require no camera or target hardware. The case that uses a local recording skips when `data/raw_videos` contains no usable file.

Habit when changing code: **run `pytest` once before and after each change**. It will directly tell you "whether this change broke existing behavior," without needing to open the camera and verify by eye.

## Hardware and Firmware

Beyond the vision side (Python), the low-level controller design is now in place:

| Part | Notes |
|---|---|
| MCU | Arduino Uno compatible board (ATmega328P-AU, 16 MHz, 5 V logic) |
| Motor driver | BTS7960 high-current dual H-bridge module (with heatsinks) |
| Motors | 12–24 V DC motors ×2 (differential steering) |
| Voltage sensor | 0–25 V divider module → A0 (battery monitoring) |
| Power | Li-ion pack (~25 V full); motor power comes straight from the battery, **not** through the Uno's 5 V regulator |

```
PC (Python + pyserial, 9600 baud) ──commands──▶ ATmega328P ──INA/INB/PWM──▶ BTS7960 ×2 ──▶ left/right motors
Battery ──▶ 0–25 V voltage sensor (1:5 divider) ──▶ A0
```

See [Original motor-test firmware](#原始电机测试固件--original-motor-test-firmware) for the default hardware protocol and its single-byte commands.

### Revised wheelchair controller protocol (`--firmware wheelchair`)

| Command | Action |
|---|---|
| `0` / `S` | Stop |
| `1` / `F` | Forward |
| `2` / `B` | Backward |
| `L` / `R` | Pivot turn left / right |
| `3` / `4` | Half-speed left / right (arc driving) |
| `GET_DATA` | Replies `BATTERY:percent,voltage×10` (e.g. `BATTERY:87,218` = 87%, 21.8 V) |

The firmware has four built-in safety layers: **auto-stop after 3 s without a command** (so the Python side must periodically re-send the current command as a heartbeat), turns and direction changes **ramp to a full stop before executing**, low battery (≤19.0 V) **only accepts stop commands** (unlocks at 19.5 V), and a **watchdog** (a hung program resets within 2 s and stops the motors).

Both firmware sketches were restored from the original project archive. [Archived commit `de96851`](https://github.com/aaf12329/history_code/tree/de968515288c61432969fd85e9cd9e2ee9ef869d/EyeWheelchairProject)

- The original reference sketch is preserved byte-for-byte. [Reference sketch](../Related_materials/ardino_demo/ardino_demo.ino)
- The revised controller includes the watchdog, serial char buffer, stop-before-turn, PWM frequency fix (~18 kHz), battery averaging and hysteresis, and throttled low-battery warnings. The revision markers and seven-item bench checklist are in the sketch. [Revised controller](../firmware/wheelchair_controller/wheelchair_controller.ino)

Both sketches compiled for Arduino Uno with Arduino AVR Boards 1.8.8 and TimerOne 1.1.1. Bench verification is pending.

The Python serial output layer is also in place: `src/hardware/serial_link.py`
(the `WheelchairLink` class: intent → protocol letters, 1 s heartbeat re-send of the current
command, `GET_DATA` battery polling every 2 s, a second low-battery lock that forces stop;
with `port=None` it runs in a **simulated mode**, so the full test suite needs no hardware).
A low battery reading or firmware warning switches the current command to Stop before the next heartbeat. Clearing the low-battery lock leaves the Stop command in place.
The terminal prints every successful write, including heartbeats and battery queries. For example, `[串口 COM3] 已发送 F` identifies a serial write, and `[模拟] 指令 F` identifies a simulated command.
`gaze_blink_confirm_demo.py` defaults to on-screen simulation. For bench integration with the revised controller, use `--serial-port COM3 --firmware wheelchair`.

> ⚠️ Install the **TimerOne** library in the Arduino IDE before compiling. The bench checklist must fully pass **and a physical e-stop button** (cutting motor power directly) must be added before any human ride testing.

## Progress (historical snapshot before shelving)

| Stage | Content | Status |
|---|---|---|
| Week 1 | Camera baseline (preview / record / snapshot) | ⚠️ Refactored version awaits full on-device verification |
| Week 2 | MediaPipe face and hand landmark visualization | ✅ Refactored (preliminary tests pass) |
| Step 3 | Blink calibration and counting (refactor + unit tests) | ✅ Verified on the real device |
| Step 4 | Gaze direction selection (left / center / right) | ✅ Refactored (preliminary tests pass) |
| Step 5 | Gaze selects direction + blink confirmation (screen demo) | ✅ Refactored (preliminary tests pass) |
| Code tidy-up | Four scripts unified into the three-section layout with call-graph comments; decision logic unit-testable | ✅ |
| Firmware | Safety-revised Arduino controller (watchdog / char buffer / stop-before-turn / PWM frequency), with bench checklist | 🔶 Written, awaiting bench verification |
| Serial output layer | `src/hardware/serial_link.py` (heartbeat / battery polling / low-battery lock / simulated mode), 12 tests | 🔶 Written, awaiting on-device integration |
| Next | Bench-verify the firmware → plug in the Arduino and integrate the serial layer | ⬜ Not started |

## Known Issues and Notes

1. Destroying a MediaPipe landmarker on Windows previously caused a long delay. `mediapipe_video.py` retains references so the system reclaims them when the process exits.
2. Live camera verification of `camera_preview.py` is pending. Offline tests cover the preview flow, recording, and snapshot capture.
3. **Dependencies are not version-locked**: `requirements.md` lists no version numbers, so another machine or an upgrade may hit API changes. The development environment measures mediapipe 1.0.1 + opencv 5.0.0; lock the versions before delivery.
4. **Left-right mirror convention**: interaction scripts mirror the image horizontally (`cv2.flip`) so that "left/right" on the screen matches the user's felt left/right; `camera_preview.py` does not mirror, so recorded video is from the "person facing you" perspective — the opposite of the snapshots. If left/right turns out reversed on the real device, press `I` to invert.
5. Window titles use English. Pillow and system fonts render the Chinese status text inside the window.
6. `preview_ui.py` tries `msyh.ttc → simhei.ttf → arial.ttf` and caches the selected font. The camera and standalone landmark previews use English.
7. The 2026-09-16 recording files in `data/raw_videos/` are all 0-byte empty shells (the recording never wrote any data) and have been deleted from the repository.

### Direction confirmation on this branch

- After calibration, look at the centre for about 0.7 seconds to select Forward.
- During blink confirmation, looking in a different direction with your eyes open cancels the candidate. Losing the face clears the dwell and blink timers. After the face is reacquired, select the direction and blink again.
- At 30 fps, smoothing in `blink_preview.py` can make a single closed frame count as a blink.

## Future Plans

1. **Fully verify `camera_preview.py` on the real machine**: the refactored version has never been run end to end — test preview / record / snapshot first.
2. **Bench-verify `firmware/wheelchair_controller/wheelchair_controller.ino`**: work through the 7-item checklist at the end of the file (wiring check → PWM noise/temperature → watchdog → long run → stop-before-turn → low-battery simulation → voltage cross-check); then add a physical e-stop button.
3. **On-device integration of the revised controller**: use the correct `--serial-port` with `--firmware wheelchair`, and verify the heartbeat, `GET_DATA` battery replies, and forced stop on low battery.
