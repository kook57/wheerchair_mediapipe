# wheerchair_mediapipe

眼控轮椅视觉原型，使用 MediaPipe 检测眼睛并做注视选择、眨眼确认。手眼预览同时用 `gaze_wheelchair_pack` 的 ONNX 模型识别手势。默认使用屏幕模拟。

An eye-controlled wheelchair prototype. MediaPipe tracks the eyes for gaze selection and blink confirmation, and the hand-eye preview classifies gestures with the ONNX model from `gaze_wheelchair_pack`. The demos default to on-screen simulation.

## 从这里开始 / Start here

| 要做什么 / Task | 入口 / Entry point |
|---|---|
| 了解交互设计与历史记录 / Read the design and project history | [项目文档 / Project notes](docs/PROJECT.md) |
| 检查摄像头 / Check the camera | [摄像头预览 / Camera preview](src/camera/camera_preview.py) |
| 查看人脸和手部关键点 / Inspect face and hand landmarks | [关键点预览 / Landmark preview](src/vision/landmarks_preview.py) |
| 演示视线与眨眼交互 / Run the gaze and blink demo | [主程序 / Demo entry point](src/interaction/gaze_blink_confirm_demo.py) |
| 同屏检测手部与眼睛并演示方向指令 / Preview hands and eyes with direction commands | [手眼预览 / Hand and eye preview](src/interaction/hand_eye_preview.py) |
| 用键盘测试方向指令 / Test direction commands from the keyboard | [键盘模式 / Keyboard mode](docs/PROJECT.md#键盘模式--keyboard-mode) |
| 接手仓库或修改代码 / Work on the repository | [AGENTS.md](AGENTS.md) |
| 查看许可 / Read the license | [MIT License](LICENSE) |

## 代码导航 / Code map

摄像头或录像先进入共享输入模块。眼动状态机根据 MediaPipe 输出的虹膜位置和双眼开合比判断方向及眨眼，再把确认的方向交给控制层和串口。手眼预览在同一帧显示手势类别与置信度，终端会打印类别变化。

Camera or video frames go through the shared input module. The eye state machines process iris position and eye aspect ratio from MediaPipe landmarks, then pass confirmed directions to the control and serial layers. The hand-eye preview displays gesture labels and confidence on the same frame and logs class changes.

| 模块 / Module | 职责 / Responsibility |
|---|---|
| [`camera/video_input.py`](src/camera/video_input.py) | 摄像头、录像和播放节奏 / Camera, recordings, and playback timing |
| [`vision/`](src/vision/) | MediaPipe 推理、ONNX 手势、眼部几何和关键点绘制 / MediaPipe inference, ONNX gestures, eye geometry, and landmark drawing |
| [`interaction/`](src/interaction/) | 预览入口、眼动状态机、键盘和方向控制 / Demos, eye state machines, keyboard input, and direction control |
| [`hardware/`](src/hardware/) | 模式选择、串口发送和协议 / Mode selection, serial output, and protocols |
| [`common/`](src/common/) | 项目路径、窗口按键和中文字体 / Project paths, window input, and Chinese fonts |

## 分支 / Branches

| 分支 / Branch | 用途 / Purpose |
|---|---|
| `main` | 本仓库的 MediaPipe 基线 / Baseline for this repository's MediaPipe implementation |
| `chen/main` | 从本仓库 `main` 建立的 Chen 开发主线 / Chen's development branch based on this repository's `main` |

项目文档中的 `chen` 指原仓库的历史分支。`chen/main` 的起点是本仓库的 MediaPipe 代码。

The `chen` branch mentioned in the project notes refers to the original repository. The `chen/main` branch starts from the MediaPipe code in this repository.

## 运行与测试 / Run and test

Windows 上可使用已有的 Conda 或 venv 环境。若使用已配置的 `mul_pro`，先运行 `conda activate mul_pro`。在新环境中安装依赖可参考下方命令。

On Windows, use an existing Conda environment or venv. If `mul_pro` is already set up, run `conda activate mul_pro` first. Use the following command to install dependencies in a fresh environment.

```powershell
python -m pip install opencv-contrib-python mediapipe numpy pillow pyserial onnxruntime pytest
```

在仓库根目录运行主演示或离线测试。主演示默认打开摄像头，也可用 `--video` 播放已有的 MP4。录像模式只使用屏幕模拟，播放完自动退出。离线测试无需摄像头，缺少可用录像时会跳过使用本地录像的测试。`pytest` 仅用于测试。

Run the demo or the offline tests from the repository root. The demo opens the camera by default and accepts an MP4 file through `--video`. Video playback uses on-screen simulation and exits at the end. The offline tests run without a camera and skip the test that uses a local recording when none is available. `pytest` is only needed for tests.

在交互式终端启动主眼动演示、手眼预览或独立串口键盘测试时，按回车选模拟，输入 `2` 后填写主控板串口号即可实际发送。录像模式和显式指定 `--serial-port`（独立键盘测试使用 `--port`）时会跳过菜单。

When starting the main gaze demo, hand and eye preview, or standalone keyboard serial test in an interactive terminal, press Enter for simulation or enter `2` and supply the controller's serial port. Video playback and an explicit `--serial-port` (`--port` for the standalone test) skip the menu.

指定主板串口时，主眼动和手眼预览默认按 `ardino_demo.ino` 的 `motor-test` 协议发送。若要让模拟也使用这套指令，请明确指定 `--firmware motor-test`。

The gaze and hand-eye demos use the `ardino_demo.ino` `motor-test` protocol by default when a serial port is specified. Pass `--firmware motor-test` to use the same command set in simulation.

手眼预览默认读取仓库中的 [`models/gesture_best.onnx`](models/gesture_best.onnx)，权重来自 `gaze_wheelchair_pack` 的 `retinaface_arcface/best.onnx`。可用 `--gesture-model` 指定其他兼容权重。手势结果用于显示和日志，串口控制来自眼动确认或键盘。

The hand-eye preview loads the bundled [`models/gesture_best.onnx`](models/gesture_best.onnx) from `gaze_wheelchair_pack/retinaface_arcface/best.onnx`. Use `--gesture-model` to select other compatible weights. The preview displays and logs gestures. Confirmed eye movements or keyboard input drive the serial control path.

```powershell
python .\src\interaction\gaze_blink_confirm_demo.py
python .\src\interaction\gaze_blink_confirm_demo.py --video "C:\path\to\recording.mp4"
python .\src\interaction\hand_eye_preview.py
python .\src\interaction\hand_eye_preview.py --video "C:\path\to\recording.mp4"
python .\src\interaction\hand_eye_preview.py --keyboard --firmware motor-test
python -m pytest -q .\tests
```
