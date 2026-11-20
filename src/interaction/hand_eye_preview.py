"""同屏识别手势和 MediaPipe 眼部关键点，眼动确认结果交给串口层。

cli() → 选择模拟或实际串口 → main() 或 keyboard_serial.main()
main() → HandGestureDetector() / create_face_landmarker() → 打开摄像头或录像
  每帧 → read_detection_input() → MediaPipe 眼部关键点与 ONNX 手势分类
       → update_eyes() → 已有的眨眼与视线状态机
       → WheelchairControl.update() → WheelchairLink → 串口或模拟
       → render_preview() → 眼部关键点、手势框和状态栏
       → pressed_key() → Q 退出 / S 停止 / C 重新校准 / I 反转左右
"""

from argparse import ArgumentParser
from pathlib import Path
import sys
import time

import cv2

# 保持从任意工作目录直接运行脚本的入口。
SRC_DIR = str(Path(__file__).resolve().parents[1])
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from camera.video_input import frame_delay_ms, open_camera as open_video_camera, open_video  # noqa: E402
from common import preview_ui  # noqa: E402
from common.paths import FACE_MODEL, GESTURE_MODEL  # noqa: E402
from hardware.serial_link import PROTOCOLS, WheelchairLink  # noqa: E402
from hardware.serial_mode import select_serial_port  # noqa: E402
from interaction import keyboard_serial  # noqa: E402
from interaction.blink_state import BlinkDetector  # noqa: E402
from interaction.gaze_blink_state import GazeBlinkDetector  # noqa: E402
from interaction.wheelchair_control import WheelchairControl  # noqa: E402
from vision.eye_geometry import average_ear  # noqa: E402
from vision.hand_gesture_detector import HandGesture, HandGestureDetector  # noqa: E402
from vision.landmark_drawing import draw_eye_points, draw_iris_points  # noqa: E402
from vision.mediapipe_video import create_face_landmarker, read_detection_input  # noqa: E402

WINDOW_NAME = "Hand Gestures and MediaPipe Eyes"
CAMERA_INDEX = 0
PREVIEW_WIDTH, PREVIEW_HEIGHT = 960, 540
PANEL_HEIGHT = 128


# ============================ 1) 判定逻辑 ============================


def update_eyes(now: float, face_result, blink, gaze):
    """将同帧的人脸结果送入两套状态机，返回眼部绘制和面板所需的数据。"""
    face = face_result.face_landmarks[0] if face_result.face_landmarks else None
    ear = average_ear(face) if face is not None else None
    return face, blink.update(now, ear), gaze.update(now, face)


# ============================ 2) 设备与画面 ============================


def open_camera() -> cv2.VideoCapture:
    """打开手眼预览使用的摄像头。"""
    return open_video_camera(
        CAMERA_INDEX, PREVIEW_WIDTH, PREVIEW_HEIGHT,
        error_message="摄像头无法打开：请关闭占用摄像头的软件，或将 CAMERA_INDEX 改为 1。",
    )


def draw_gestures(frame, gestures: list[HandGesture]) -> None:
    """把原图方向上的手势检测框映射到镜像预览图。"""
    height, width = frame.shape[:2]
    for gesture in gestures:
        x1, y1, x2, y2 = gesture.box
        left, top = round((1 - x2) * (width - 1)), round(y1 * (height - 1))
        right, bottom = round((1 - x1) * (width - 1)), round(y2 * (height - 1))
        color = (0, 255, 0)
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        cv2.putText(frame, f"{gesture.label} {gesture.confidence:.2f}", (left, max(16, top - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)


def render_preview(frame, face, gestures, blink_status, gaze_status, link_status):
    """绘制眼部、手势检测结果和视频上方的状态栏。"""
    height, width = frame.shape[:2]
    scale = min(PREVIEW_WIDTH / width, PREVIEW_HEIGHT / height)
    if scale != 1:
        frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))))
    else:
        frame = frame.copy()
    if face is not None:
        draw_eye_points(frame, face)
        draw_iris_points(frame, face)
    draw_gestures(frame, gestures)

    # 视频保持原宽高比，面板放在视频外，以免挡住关键点。
    side_padding = PREVIEW_WIDTH - frame.shape[1]
    frame = cv2.copyMakeBorder(
        frame, PANEL_HEIGHT, 0, side_padding // 2, side_padding - side_padding // 2,
        cv2.BORDER_CONSTANT, value=(18, 18, 18),
    )
    eye_text = "已检测" if face is not None else "未检测"
    gaze_text = gaze_status.raw_direction or "--"
    link_text = f"串口 {link_status.mode}" if link_status.connected else "模拟"
    if not link_status.connected and link_status.last_error:
        link_text = "模拟（串口未连接）"
    if link_status.is_low_battery:
        link_text += " / 低电锁定"
    gesture_text = f"{gestures[0].label} {gestures[0].confidence:.2f}" if gestures else "--"
    return preview_ui.draw_chinese_status(frame, (
        f"眼睛 {eye_text}  |  手势 {gesture_text}  |  {link_text}  |  指令 {link_status.intent or '--'}",
        f"视线 {gaze_text}  |  眨眼 {blink_status.blink_count} 次",
        gaze_status.message,
        "Q 退出  |  S 停止  |  C 重新校准  |  I 反转左右",
    ))


# ============================ 3) 主流程 ============================


def main(
    video: Path | None = None, *, serial_port: str | None = None, firmware: str | None = None,
    gesture_model: Path = GESTURE_MODEL,
) -> None:
    """对同一输入帧运行手势识别和眼动判定，再更新预览及串口。"""
    if video is not None and serial_port is not None:
        raise ValueError("录像模式使用模拟，不能同时指定串口。")
    gesture_detector = HandGestureDetector(gesture_model)
    link = WheelchairLink(serial_port, firmware=firmware)
    capture, fps = (open_camera(), None) if video is None else open_video(video)
    try:
        face_detector = create_face_landmarker(FACE_MODEL)
        link.open()
        playback_started = time.perf_counter()
        started = playback_started if fps is None else 0.0
        blink = BlinkDetector(started)
        gaze = GazeBlinkDetector(started)
        control = WheelchairControl(link)
        frame_count = 0
        key_available_at = 0.0
        previous_gesture_class = None
        if link.connected:
            link.set_intent("停", now=started)
        elif link.last_error:
            print(f"串口未连接，已切到模拟模式。{link.last_error}")
        else:
            print("模拟模式，终端会显示模拟指令。")
        print("手势与眼睛预览已启动。请睁眼看正中校准，点击窗口后按 Q 退出或 S 停止。")

        while True:
            video_time = frame_count / fps if fps is not None else None
            result = read_detection_input(capture, started, clock=time.perf_counter, video_time=video_time)
            if result is None:
                if frame_count == 0:
                    raise RuntimeError(f"录像没有可读取的画面：{video}")
                print("录像播放结束。")
                break
            frame, now, image, timestamp_ms = result
            frame_count += 1
            face_result = face_detector.detect_for_video(image, timestamp_ms)
            face, blink_status, gaze_status = update_eyes(now, face_result, blink, gaze)
            link_status = control.update(now, gaze_status.state, gaze_status.active, face_present=face is not None)

            # The source detector uses the unmirrored camera image.
            gestures = gesture_detector.detect(cv2.flip(frame, 1))
            primary = gestures[0] if gestures else None
            if primary is not None and primary.class_id != previous_gesture_class:
                print(f"[手势] {primary.class_id} {primary.label} {primary.confidence:.2f}", flush=True)
            previous_gesture_class = primary.class_id if primary is not None else None
            preview = render_preview(frame, face, gestures, blink_status, gaze_status, link_status)
            cv2.imshow(WINDOW_NAME, preview)

            if not preview_ui.window_is_alive(WINDOW_NAME):
                break
            key_time = time.perf_counter()
            delay = frame_delay_ms(playback_started, frame_count, fps, key_time)
            key, key_available_at = preview_ui.pressed_key(
                key_time, key_available_at, delay, immediate_keys="sq",
            )
            if key == "q":
                break
            if key in ("s", "c"):
                link.set_intent("停", now=now)
                gaze.reset(now)
                if key == "c":
                    blink.reset(now)
            if key == "i":
                gaze.toggle_invert()
    finally:
        try:
            link.set_intent("停")
        finally:
            link.close()
            capture.release()
            cv2.destroyAllWindows()


def cli() -> None:
    """解析命令行，必要时询问串口模式，然后启动键盘或视觉入口。"""
    parser = ArgumentParser(description="ONNX 手势与 MediaPipe 眼动集成预览")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--video", type=Path, help="在模拟模式下播放录像")
    source.add_argument("--keyboard", action="store_true", help="在 Windows 终端使用键盘控制，不打开摄像头")
    parser.add_argument("--serial-port", help="连接指定串口，例如 COM3")
    parser.add_argument("--firmware", choices=PROTOCOLS, help="固件协议，指定串口时默认 motor-test")
    parser.add_argument("--gesture-model", type=Path, default=GESTURE_MODEL, help="手势模型 best.onnx 的路径")
    args = parser.parse_args()
    if args.video is not None and args.serial_port is not None:
        parser.error("录像模式使用模拟，不能同时指定串口。")

    serial_port = None if args.video is not None else select_serial_port(args.serial_port, firmware=args.firmware)
    if args.keyboard:
        keyboard_serial.main(serial_port, firmware=args.firmware)
    else:
        main(args.video, serial_port=serial_port, firmware=args.firmware, gesture_model=args.gesture_model)


if __name__ == "__main__":
    cli()
