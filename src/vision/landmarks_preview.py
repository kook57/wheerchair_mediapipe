"""第 2 步：同帧显示 MediaPipe 人脸和手部关键点。

启动：main() → open_camera() → create_detectors()。
每帧：read_and_detect() → draw_results() → 窗口显示与按键。
BGR 帧 → MediaPipe 单张 RGB 图和时间戳 → 人脸 478 点及每只手 21 点 → 显示。
按 S 保存带骨架的截图，按 Q 退出。
"""
from datetime import datetime
from pathlib import Path
import sys
import time

import cv2

# 兼容直接运行此脚本。
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.video_input import open_camera as open_video_camera  # noqa: E402
from common import preview_ui  # noqa: E402
from common.paths import FACE_MODEL, HAND_MODEL, LANDMARK_SNAPSHOTS_DIR as SNAPSHOT_DIR  # noqa: E402
from vision.landmark_drawing import EYE_LOOPS, draw_face, draw_hand, draw_hands, point  # noqa: E402
from vision.mediapipe_video import create_face_hand_landmarkers, read_face_hand_frame  # noqa: E402

# ---- 运行参数 ----
CAMERA_INDEX = 0
WIDTH, HEIGHT = 960, 540
KEY_DEBOUNCE_SECONDS = 0.25  # 两次按键响应的最小间隔：按住不放时不再连发

WINDOW_NAME = "MediaPipe Landmarks | Q quit | S snapshot"


# ============================ 1) 关键点绘制（不碰摄像头） ============================


def draw_results(frame, face_result, hand_result, fps: float) -> None:
    """把一帧的所有识别结果画到画面上：人脸点、手部骨架、左上角状态栏。

    调用关系：被 main() 每帧调用一次；内部调用 draw_face()（每张脸一次）
    和 draw_hands()，最后铺黑底画两行英文状态。
    它只读识别结果，不改任何状态——所以调它不会影响别的东西。
    """
    for landmarks in face_result.face_landmarks:
        draw_face(frame, landmarks)

    draw_hands(frame, hand_result)

    faces = len(face_result.face_landmarks)
    hands = len(hand_result.hand_landmarks)
    cv2.rectangle(frame, (0, 0), (410, 82), (0, 0, 0), -1)
    cv2.putText(frame, f"FACE: {faces} | HAND: {hands} | {fps:.1f} FPS", (14, 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(frame, "Q quit | S snapshot | VISUAL ONLY", (14, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 255), 2)


# ============================ 2) 摄像头与检测器 ============================


def open_camera() -> cv2.VideoCapture:
    """启动预览时按本入口的分辨率打开摄像头。"""
    return open_video_camera(
        CAMERA_INDEX, WIDTH, HEIGHT,
        error_message="摄像头无法打开：请关闭占用摄像头的软件，或将 CAMERA_INDEX 改为 1。",
    )


def create_detectors():
    """创建同帧预览使用的人脸和手部检测器。"""
    return create_face_hand_landmarkers(FACE_MODEL, HAND_MODEL)


# ============================ 3) 主流程 ============================


def read_and_detect(cap, face_detector, hand_detector, started: float, *, video_time: float | None = None):
    """对同一张推理图运行双模型，返回帧、当前时间及两个检测结果。"""
    return read_face_hand_frame(cap, face_detector, hand_detector, started, clock=time.perf_counter, video_time=video_time)


def stamp() -> str:
    """生成"年月日_时分秒"格式的时间戳，用来拼截图文件名。

    调用关系：只被 save_snapshot() 调用。
    """
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_snapshot(frame) -> Path:
    """把当前画面存成 jpg，返回保存路径。

    调用关系：被 main() 的 S 键分支调用；内部调用 stamp() 拼文件名。
    """
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"landmarks_{stamp()}.jpg"
    cv2.imwrite(str(path), frame)
    return path


def window_is_alive(window_name: str = WINDOW_NAME) -> bool:
    """检查该入口的预览窗口是否仍然打开。"""
    return preview_ui.window_is_alive(window_name)


def pressed_key(now: float, key_available_at: float, delay_ms: int = 1, *, immediate_keys: str = ""):
    """按该入口的去抖间隔读取窗口按键。"""
    return preview_ui.pressed_key(
        now, key_available_at, delay_ms, debounce_seconds=KEY_DEBOUNCE_SECONDS, immediate_keys=immediate_keys,
    )


def main() -> None:
    """程序入口：建好摄像头和两个识别器后，每帧走一遍 看→画→控。"""
    # ==================== 启动阶段（下面每个调用只执行一次）====================
    cap = open_camera()                       # ① 打开摄像头
    face_detector, hand_detector = create_detectors()  # ② 建两个识别器
    started = time.perf_counter()             # 给 MediaPipe 算毫秒时间戳 + 算帧率用
    frame_count = 0                           # 帧计数器（只用来算帧率）
    key_available_at = 0.0                    # 按键防抖：下次允许响应的时间点

    print("关键点预览已启动：请先点一下视频窗口让它获得焦点，然后 Q 退出、S 保存截图。")
    try:
        # ================= 每帧循环：看 → 画 → 控 =================
        while True:
            # ---- ① 看：取一帧并跑两个识别器 ----
            frame, now, face_result, hand_result = read_and_detect(cap, face_detector, hand_detector, started)

            # ---- ② 画：人脸点 + 手部骨架 + 左上角状态栏 ----
            frame_count += 1
            fps = frame_count / max(now - started, 0.001)
            draw_results(frame, face_result, hand_result, fps)
            cv2.imshow(WINDOW_NAME, frame)

            # ---- ③ 控：先看窗口还活着没，再读键盘 ----
            if not window_is_alive():            # 窗口被点 ✕ 关掉就退出
                print("窗口已关闭，退出。")
                break
            key, key_available_at = pressed_key(now, key_available_at)
            if key == "q":
                break
            if key == "s":
                print(f"截图已保存：{save_snapshot(frame)}")
    finally:
        # 不调用两个检测器的 close()：实测它要卡约 42 秒（MediaPipe 1.0.1 拆推理图的等待）。
        # 配合 create_detectors() 里的保活引用，进程 1 秒内干净退出，内存由系统回收。
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
