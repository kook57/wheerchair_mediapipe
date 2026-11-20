"""第 3 步：在摄像头画面上检查眨眼计数。

启动：open_camera() → face_detector() → BlinkDetector()。
每帧：read_frame() → average_ear() → BlinkDetector.update() → show_status() → pressed_key()。
检测输入是人脸关键点，判定输入是双眼开合比（EAR）。Q 退出，C 重新校准。
"""
from pathlib import Path
import sys
import time

import cv2

# 兼容直接运行此脚本。
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.video_input import open_camera as open_video_camera  # noqa: E402
from common import preview_ui  # noqa: E402
from common.preview_ui import chinese_font, draw_chinese_status  # noqa: E402
from common.paths import FACE_MODEL  # noqa: E402
from vision.landmark_drawing import draw_eye_points  # noqa: E402
from vision.mediapipe_video import create_face_landmarker, read_face_frame  # noqa: E402
from interaction.blink_state import BlinkDetector, BlinkStatus  # noqa: E402
from vision.eye_geometry import LEFT_EYE, RIGHT_EYE, average_ear, distance, eye_aspect_ratio  # noqa: E402


#默认参数设定：
#从第几个摄像头开
#画面高、宽（先写死成固定值）
#校准时长用前三秒去收集信息构建你的眼睛正常是什么样的，睁眼时多大闭眼时多大
CAMERA_INDEX = 0
WIDTH, HEIGHT = 960, 540
KEY_DEBOUNCE_SECONDS = 0.25 # 两次按键响应的最小间隔：按住不放时不再连发

MESSAGE_RECALIBRATE = "重新校准：请睁眼正视摄像头"

WELCOME_ART = (
    "/\\     /\\\\",
    "{  `---'  }",
    "{  O   O  }",
    "~~>  V  <~~",
    "\\\\  \\|/  /",
    "`-----'__",
)

WINDOW_NAME = "Blink Detection | Q quit | C recalibrate | visual test only"


# ============================ 摄像头与画面 ============================


def open_camera() -> cv2.VideoCapture:
    """启动预览时按本入口的分辨率打开摄像头。"""
    return open_video_camera(
        CAMERA_INDEX, WIDTH, HEIGHT,
        error_message="摄像头无法打开，请关闭占用摄像头的软件后重试。",
    )


#用模型去检测脸部特征返回一个对象（暂时理解成为一个结构体）
def face_detector():
    """为本入口创建一个 VIDEO 人脸检测器。"""
    return create_face_landmarker(FACE_MODEL)


# ============================ 主流程 ============================


def read_frame(cap, detector, program_started_at: float):
    """返回镜像帧、当前时间和第一张脸的关键点。"""
    return read_face_frame(cap, detector, program_started_at, clock=time.perf_counter)


def show_status(frame, status) -> None:
    """铺黑色底板 + 四行中文状态 + 推到窗口显示。

    调用关系：被 main() 每帧调用（循环第 4 步）；内部调用 draw_chinese_status()。
    它只读 status（BlinkStatus），不改任何状态——所以调它不会影响判定。
    """
    cv2.rectangle(frame, (0, 0), (560, 125), (0, 0, 0), -1)
    ear_text = "--" if status.ear is None else f"{status.ear:.3f}"
    base_text = "--" if status.baseline is None else f"{status.baseline:.3f}"
    close_text = "--" if status.close_threshold is None else f"{status.close_threshold:.3f}"
    frame = draw_chinese_status(frame, [
        f"眼睛开合值：{ear_text}｜睁眼基线：{base_text}｜闭眼线：{close_text}",
        f"眨眼次数：{status.blink_count}｜状态：{status.state}",
        status.message,
        "按 Q 退出｜按 C 重新校准｜仅视觉测试，不控制任何硬件",
    ])
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

    for i in WELCOME_ART:
        print(i)
    """程序入口：先建好四样东西，然后每帧走一遍 看→量→判→报→控。"""
    # ==================== 启动阶段（下面每个调用只执行一次）====================
    cap = open_camera()  # ① 打开摄像头
    detector = face_detector()  # ② 建识别器：调用函数创建MediaPipe人脸关键点检测器对象，用于后续检测人脸
    program_started_at = time.perf_counter()  # 记录程序启动的高精度时间戳，用于给MediaPipe提供视频时间（帧数不稳定毕竟是数字计算）
    blink = BlinkDetector(program_started_at)  # ③ 建眨眼状态机；校准起点 = 程序启动时刻，眨眼全部状态都在里面
    key_available_at = 0.0  # 按键防抖：下次允许响应的时间点
    chinese_font(20)  # ④ 提前加载字体，字体缺失时立刻报错

    print("眨眼预览已启动：请先点一下视频窗口让它获得焦点，然后 Q 退出、C 重新校准。")
    try:
        # ================= 每帧循环：看 → 量 → 判 → 报 → 控 =================
        while True:
            # ---- ① 看：读一帧并交给 MediaPipe，拿回 478 个关键点 ----
            frame, now, landmarks = read_frame(cap, detector, program_started_at)
            if landmarks is not None:
                draw_eye_points(frame, landmarks)  # 顺便把眼睛上的点画出来（只为肉眼检查）

            # ---- ② 量：把关键点换算成"眼睛张多开"这一个数 ----
            #ear是用于判定眼睛的状态标志；没检测到人脸时传 None
            ear_raw = average_ear(landmarks) if landmarks is not None else None

            # ---- ③ 判：校准 / 计数，全部判定逻辑都在 BlinkDetector 里 ----
            status = blink.update(now, ear_raw)

            # ---- ④ 报：把 status 画到窗口上 ----
            show_status(frame, status)

            # ---- ⑤ 控：先看窗口还活着没，再读键盘 ----
            if not window_is_alive():  # 窗口被点 ✕ 关掉就退出
                print("窗口已关闭，退出。")
                break
            key, key_available_at = pressed_key(now, key_available_at)
            if key == "q":
                break
            if key == "c":
                blink.reset(now, MESSAGE_RECALIBRATE)  # 回到校准起点，重新采集一次基线
    finally:
        # 不调用 detector.close()：实测它要卡约 42 秒（MediaPipe 1.0.1 拆推理图的等待）。
        # 配合 face_detector() 里的保活引用，进程 1 秒内干净退出，内存由系统回收。
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
