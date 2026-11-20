"""第 4 步：预览左、中、右视线方向。

启动：open_camera() → create_detector() → GazeDirectionDetector()。
每帧：read_frame() → GazeDirectionDetector.update() → show_status() → pressed_key()。
关键点先换算为虹膜横向位置，再由状态机校准并判断稳定方向。Q 退出，C 校准，I 反转左右。
"""
from pathlib import Path
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw

# 兼容直接运行此脚本。
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.video_input import open_camera as open_video_camera  # noqa: E402
from common import preview_ui  # noqa: E402
from common.preview_ui import chinese_font  # noqa: E402
from common.paths import FACE_MODEL  # noqa: E402
from vision.landmark_drawing import draw_iris_points  # noqa: E402
from vision.mediapipe_video import create_face_landmarker, read_face_frame  # noqa: E402
from interaction.gaze_direction_state import GazeDirectionDetector, GazeStatus, gaze_score  # noqa: E402
from vision.eye_geometry import LEFT_CORNERS, LEFT_IRIS, RIGHT_CORNERS, RIGHT_IRIS  # noqa: E402

# ---- 运行参数 ----
CAMERA_INDEX = 0
WIDTH, HEIGHT = 960, 540
KEY_DEBOUNCE_SECONDS = 0.25   # 两次按键响应的最小间隔：按住不放时不再连发

MESSAGE_RECALIBRATE = "重新校准：请看屏幕正中间"

# ---- 路径与窗口 ----
WINDOW_NAME = "Gaze Direction | Q quit | C recalibrate | I invert | visual test only"


# ============================ 摄像头与画面 ============================


def open_camera() -> cv2.VideoCapture:
    """启动预览时按本入口的分辨率打开摄像头。"""
    return open_video_camera(
        CAMERA_INDEX, WIDTH, HEIGHT,
        error_message="摄像头无法打开，请关闭占用摄像头的软件后重试。",
    )


def create_detector():
    """为本入口创建一个 VIDEO 人脸检测器。"""
    return create_face_landmarker(FACE_MODEL)


def draw_text(frame, text, xy, size, color):
    """在画面上画一行中文（OpenCV 自带字体画不了中文，所以用 PIL + 系统字体）。

    调用关系：被 show_status() 和 draw_cards() 调用；内部调用 chinese_font()。
    注意它不修改传入的 frame，而是返回一张画好字的新图。
    """
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    ImageDraw.Draw(image).text(xy, text, font=chinese_font(size), fill=color)
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def draw_cards(frame, candidate: str):
    """画底部三张卡片：左 / 中 / 右；名称与 candidate 相同的那张用实心绿色高亮。

    调用关系：被 show_status() 调用；candidate 由状态机算好（放在 GazeStatus.candidate 里），
    还没稳定时是 "无"，此时三张卡片都不高亮。
    """
    cards = [("左", 35, 390, 280, 515), ("中", 340, 390, 585, 515), ("右", 645, 390, 890, 515)]
    for label, x1, y1, x2, y2 in cards:
        active = label == candidate
        color = (0, 170, 0) if active else (70, 70, 70)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, -1 if active else 2)
        frame = draw_text(frame, label, (x1 + 98, y1 + 35), 48, (255, 255, 255))
    return frame


# ============================ 主流程 ============================


def read_frame(cap, detector, started: float):
    """返回镜像帧、当前时间和第一张脸的关键点。"""
    return read_face_frame(cap, detector, started, clock=time.perf_counter)


def show_status(frame, status) -> None:
    """铺黑色底板 + 三行中文 + 底部三张卡片，然后推给窗口。

    调用关系：被 main() 每帧调用（循环第三步）；内部调用 draw_text() 和 draw_cards()。
    它只读 status，不改任何状态——所以调它不会影响判定。
    """
    cv2.rectangle(frame, (0, 0), (650, 105), (0, 0, 0), -1)
    score_text = "--" if status.score is None else f"{status.score:.3f}"
    base_text = "--" if status.center is None else f"{status.center:.3f}"
    frame = draw_text(frame, f"虹膜位置：{score_text}｜正视基准：{base_text}", (14, 10), 20, (0, 255, 0))
    frame = draw_text(frame, f"当前方向：{status.raw_direction}｜稳定候选：{status.candidate}", (14, 38), 28, (255, 255, 0))
    frame = draw_text(frame, status.message, (14, 74), 18, (255, 255, 255))
    frame = draw_cards(frame, status.candidate)
    cv2.imshow(WINDOW_NAME, frame)


def window_is_alive() -> bool:
    """检查该入口的预览窗口是否仍然打开。"""
    return preview_ui.window_is_alive(WINDOW_NAME)


def pressed_key(now: float, key_available_at: float):
    """按该入口的去抖间隔读取窗口按键。"""
    return preview_ui.pressed_key(
        now, key_available_at, debounce_seconds=KEY_DEBOUNCE_SECONDS,
    )


def main() -> None:
    """程序入口：建好摄像头和识别器后，每帧走一遍 看→判→报→控。"""
    # ==================== 启动阶段（下面每个调用只执行一次）====================
    cap = open_camera()                          # ① 打开摄像头
    detector = create_detector()                 # ② 建识别器
    started = time.perf_counter()                # 给 MediaPipe 算毫秒时间戳用
    flow = GazeDirectionDetector(started)        # ③ 建状态机；校准从此刻开始计时
    key_available_at = 0.0                       # 按键防抖：下次允许响应的时间点
    chinese_font(20)                             # ④ 提前加载字体，字体缺失时立刻报错

    print("视线方向预览已启动：请先点一下视频窗口让它获得焦点，然后 Q 退出、C 重新校准、I 反转左右。")
    try:
        # ================= 每帧循环：看 → 判 → 报 → 控 =================
        while True:
            # ---- ① 看：取一帧并识别，拿回 478 个关键点 ----
            frame, now, landmarks = read_frame(cap, detector, started)
            if landmarks is not None:
                draw_iris_points(frame, landmarks)  # 顺便把虹膜上的点画出来（只为肉眼检查）

            # ---- ② 判：校准 / 方向选择，全在 GazeDirectionDetector 里 ----
            status = flow.update(now, landmarks)

            # ---- ③ 报：三行中文 + 三张卡片，推给窗口 ----
            show_status(frame, status)

            # ---- ④ 控：先看窗口还活着没，再读键盘 ----
            if not window_is_alive():            # 窗口被点 ✕ 关掉就退出
                print("窗口已关闭，退出。")
                break
            key, key_available_at = pressed_key(now, key_available_at)
            if key == "q":
                break
            if key == "c":
                flow.reset(now, MESSAGE_RECALIBRATE)  # 回到校准起点
            if key == "i":
                flow.toggle_invert()                   # 左右方向反转 / 恢复
    finally:
        # 不调用 detector.close()：实测它要卡约 42 秒（MediaPipe 1.0.1 拆推理图的等待）。
        # 配合 create_detector() 里的保活引用，进程 1 秒内干净退出，内存由系统回收。
        cap.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
