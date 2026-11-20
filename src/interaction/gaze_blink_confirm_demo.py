"""第 5 步：注视选方向并眨眼确认，默认模拟。

启动：cli() → 选择输出 → main() → 打开摄像头或录像 → 创建人脸检测器和串口链路。
每帧：read_frame() → GazeBlinkDetector.update() → WheelchairControl.update() → show_status() → pressed_key()。
人脸关键点用于计算虹膜位置与开合比。状态机从校准进入方向选择、等待眨眼和确认成功，
再由 WheelchairLink 把已确认的意图映射为固件指令。Q 退出，C 校准，I 反转左右。
"""
from argparse import ArgumentParser
from pathlib import Path
import math
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw

# 脚本直接运行时，把 src/ 加进搜索路径以引入录像和串口接口
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from camera.video_input import frame_delay_ms, open_camera as open_video_camera, open_video  # noqa: E402
from common import preview_ui  # noqa: E402
from common.preview_ui import chinese_font  # noqa: E402
from common.paths import FACE_MODEL as MODEL  # noqa: E402
from vision.landmark_drawing import draw_points as draw_landmark_points  # noqa: E402
from vision.mediapipe_video import create_face_landmarker, read_face_frame  # noqa: E402
from interaction.gaze_blink_state import GazeBlinkDetector, GazeBlinkStatus  # noqa: E402
from vision.eye_geometry import (  # noqa: E402
    LEFT_CORNERS, LEFT_EYE, LEFT_IRIS, RIGHT_CORNERS, RIGHT_EYE, RIGHT_IRIS,
    average_ear, distance, eye_aspect_ratio, gaze_score,
)
from hardware.serial_link import PROTOCOLS, WheelchairLink  # noqa: E402  ← 在 sys.path 之后导入
from hardware.serial_mode import select_serial_port  # noqa: E402
from interaction.wheelchair_control import WheelchairControl  # noqa: E402

# ---- 运行参数 ----
CAMERA_INDEX = 0
WIDTH, HEIGHT = 960, 540
KEY_DEBOUNCE_SECONDS = 0.25                          # 两次按键响应的最小间隔：按住不放时不再连发

# ---- 路径与窗口 ----
WINDOW = "Gaze Select + Blink Confirm | Q quit | C recalibrate | I invert | screen demo only"


cat = r'''
__        .-.
             .-"` .`'.    /\\|
     _(\-/)_" ,  .   ,\  /\\\/
    {(#b^d#)} .   ./,  |/\\\/
    `-.(Y).-`  ,  |  , |\.-`
         /~/,_/~~~\,__.-`
        ////~    // ~\\
jgs   ==`==`   ==`   ==`
'''


# ============================ 摄像头与画面 ============================


def open_camera() -> cv2.VideoCapture:
    """启动预览时按本入口的分辨率打开摄像头。"""
    return open_video_camera(
        CAMERA_INDEX, WIDTH, HEIGHT,
        error_message="摄像头无法打开。",
    )


def make_detector():
    """为本入口创建一个 VIDEO 人脸检测器。"""
    return create_face_landmarker(MODEL)


# ---- 界面配色（BGR）与几何常量 ----
PANEL_BG, PANEL_BORDER = (30, 30, 36), (90, 120, 160)   # 深色面板 + 蓝灰描边
STATE_COLORS = {                        # 每个状态一个指示灯颜色
    "校准": (60, 200, 255),             # 黄
    "选择方向": (120, 200, 120),        # 绿
    "等待眨眼": (40, 170, 255),         # 橙
    "确认成功": (90, 255, 130),         # 亮绿
}
BAR_BG = (62, 62, 70)                   # 进度条底槽
CARD_BG, CARD_BORDER = (45, 45, 52), (95, 95, 105)
CARD_CANDIDATE = (40, 180, 255)         # 琥珀色：已稳定候选
CARD_CONFIRM_FILL = (70, 170, 95)       # 绿色：等待眨眼 / 已确认
TEXT_VALUES, TEXT_MAIN, TEXT_HINT = (120, 255, 120), (255, 255, 255), (175, 175, 175)
CARD_RECTS = [("左转", 35, 390, 280, 515), ("前进", 340, 390, 585, 515), ("右转", 645, 390, 890, 515)]
PANEL_W, PANEL_H = 640, 164
BAR_X1, BAR_X2 = 70, 330


def _pil_text(frame, items):
    """一次 PIL 往返画完全部中文（旧版每帧最多 4 次 BGR↔RGB 转换，这里只做 1 次）。

    items = [(x, y, 文本, 字号, BGR颜色), ...]
    调用关系：被 render_overlay() 调用；内部调用 chinese_font()（带缓存）。
    """
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    for x, y, text, size, color in items:
        draw.text((x, y), text, font=chinese_font(size), fill=(color[2], color[1], color[0]))
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def _card_mode(status) -> str:
    """三张卡片该用哪种画法：none=普通 / candidate=琥珀候选 / confirmed=绿色已确认。"""
    if status.state in ("等待眨眼", "确认成功") and status.active:
        return "confirmed"
    if status.state == "选择方向" and status.active:
        return "candidate"
    return "none"


def _draw_panel(frame, status):
    """状态面板的底板、状态指示灯和两条进度条（文字统一在 _pil_text 里画）。"""
    color = STATE_COLORS.get(status.state, TEXT_MAIN)
    cv2.rectangle(frame, (0, 0), (PANEL_W, PANEL_H), PANEL_BG, -1)
    cv2.rectangle(frame, (0, 0), (PANEL_W, PANEL_H), PANEL_BORDER, 1)
    cv2.circle(frame, (26, 32), 8, color, -1)                     # 状态指示灯
    for y, progress in ((80, status.calibration_progress), (100, status.stability_progress)):
        cv2.rectangle(frame, (BAR_X1, y), (BAR_X2, y + 8), BAR_BG, -1)       # 进度条底槽
        if progress is not None:
            fill_w = int((BAR_X2 - BAR_X1) * max(0.0, min(1.0, progress)))
            if fill_w > 0:
                cv2.rectangle(frame, (BAR_X1, y), (BAR_X1 + fill_w, y + 8), color, -1)
    return frame


def _draw_cards(frame, status, now, mode):
    """底部三张卡片：普通 / 已稳定候选（琥珀边+顶部色条）/ 等待确认与已确认（绿底+呼吸灯+对勾）。"""
    pulse = 0.5 + 0.5 * math.sin(now * 6.0)                       # 呼吸灯相位
    for label, x1, y1, x2, y2 in CARD_RECTS:
        if label != status.active:
            cv2.rectangle(frame, (x1, y1), (x2, y2), CARD_BG, -1)
            cv2.rectangle(frame, (x1, y1), (x2, y2), CARD_BORDER, 2)
        elif mode == "confirmed":
            cv2.rectangle(frame, (x1, y1), (x2, y2), CARD_CONFIRM_FILL, -1)
            glow = tuple(int(c * (0.65 + 0.35 * pulse)) for c in (150, 255, 190))
            cv2.rectangle(frame, (x1, y1), (x2, y2), glow, 4)     # 边框随呼吸明暗
            if status.state == "确认成功":                        # 右上角对勾
                pts = np.array([(x2 - 52, y1 + 34), (x2 - 40, y1 + 46), (x2 - 16, y1 + 12)])
                cv2.polylines(frame, [pts], False, (255, 255, 255), 4)
        else:  # candidate
            cv2.rectangle(frame, (x1, y1), (x2, y2), CARD_BG, -1)
            cv2.rectangle(frame, (x1, y1), (x2, y2), CARD_CANDIDATE, 4)
            cv2.rectangle(frame, (x1, y1), (x2, y1 + 8), CARD_CANDIDATE, -1)  # 顶部色条
    return frame


def _draw_chips(frame, link_info):
    """右上角两枚角标的底板：帧率、硬件链路状态（模式/电量）。文字在 _pil_text 里画。"""
    cv2.rectangle(frame, (WIDTH - 120, 8), (WIDTH - 8, 40), PANEL_BG, -1)
    cv2.rectangle(frame, (WIDTH - 340, 8), (WIDTH - 128, 40), PANEL_BG, -1)
    return frame


def render_overlay(frame, status, now, fps, link_info):
    """把本帧全部界面元素画好并返回新帧（纯绘制：不 imshow、不碰任何状态，可单测）。

    调用关系：被 show_status() 调用（main 每帧一次）；
    内部调用 _draw_panel / _draw_cards / _draw_chips / _pil_text。
    """
    mode = _card_mode(status)
    frame = _draw_panel(frame, status)
    frame = _draw_cards(frame, status, now, mode)
    frame = _draw_chips(frame, link_info)

    score_t = "--" if status.score is None else f"{status.score:.3f}"
    ear_t = "--" if status.ear is None else f"{status.ear:.3f}"
    items = [
        (44, 18, f"当前状态：{status.state}", 24, STATE_COLORS.get(status.state, TEXT_MAIN)),
        (16, 52, f"虹膜位置 {score_t}    眼睛开合 {ear_t}", 18, TEXT_VALUES),
        (16, 78, "校准", 15, TEXT_HINT),
        (16, 98, "稳定", 15, TEXT_HINT),
        (16, 118, status.message, 18, TEXT_MAIN),
        (16, 142, "Q 退出｜C 重新校准｜I 反转左右", 16, TEXT_HINT),
        (WIDTH - 108, 14, f"{fps:.0f} FPS", 18, TEXT_VALUES),
    ]
    hw_text, hw_color = "模拟模式", TEXT_HINT
    if link_info is not None:
        if link_info.connected:
            hw_text = f"{link_info.mode} 已发 {link_info.send_count}"
            if link_info.battery is not None:
                hw_text += f" 电 {link_info.battery[0]}% {link_info.battery[1]:.1f}V"
            hw_color = (60, 60, 255) if link_info.is_low_battery else (120, 255, 120)
        elif link_info.last_error:
            hw_text = "模拟（串口未连上）"
    items.append((WIDTH - 332, 14, hw_text, 16, hw_color))
    for label, x1, _, y1, _ in CARD_RECTS:
        tcolor = TEXT_MAIN
        if label == status.active:
            tcolor = (255, 255, 255) if mode == "confirmed" else CARD_CANDIDATE
        items.append((x1 + 90, y1 + 40, label, 40, tcolor))
    return _pil_text(frame, items)


# ============================ 主流程 ============================


def read_frame(cap, detector, started: float, *, video_time: float | None = None):
    """返回镜像帧、当前时间和第一张脸的关键点。"""
    return read_face_frame(cap, detector, started, clock=time.perf_counter, video_time=video_time)


def draw_points(frame, landmarks) -> None:
    """用原有的两像素标记标出虹膜和眼睛轮廓。"""
    draw_landmark_points(frame, landmarks, LEFT_IRIS + RIGHT_IRIS + LEFT_EYE + RIGHT_EYE, radius=2)


def show_status(frame, status, now, fps, link_info) -> None:
    """渲染整帧界面（render_overlay）并推给窗口。被 main() 每帧调用。"""
    cv2.imshow(WINDOW, render_overlay(frame, status, now, fps, link_info))


def window_is_alive() -> bool:
    """检查该入口的预览窗口是否仍然打开。"""
    return preview_ui.window_is_alive(WINDOW)


def pressed_key(now: float, key_available_at: float, delay_ms: int = 1):
    """按该入口的去抖间隔读取窗口按键。"""
    return preview_ui.pressed_key(
        now, key_available_at, delay_ms, debounce_seconds=KEY_DEBOUNCE_SECONDS,
    )


def main(video: Path | None = None, *, serial_port: str | None = None, firmware: str | None = None) -> None:
    """初始化输入、识别器和串口适配，每帧走一遍看、判、连、报、控。"""
    print(cat)
    if video is not None and serial_port is not None:
        raise ValueError("录像模式使用模拟，不能同时指定串口。")
    link = WheelchairLink(serial_port, firmware=firmware)
    cap, video_fps = (open_camera(), None) if video is None else open_video(video)
    try:
        detector = make_detector()
        link.open()
        chinese_font(20)
        key_available_at = 0.0
        frame_count = 0
        control = WheelchairControl(link)

        print("视线选择演示已启动：请先点一下视频窗口让它获得焦点，然后 Q 退出、C 重新校准、I 反转左右。")
        if link.connected:
            print(f"硬件链路已连接：{link.mode}。确认成功的方向会真的发往固件（低电时被强制为停止）。")
        else:
            reason = f"（{link.last_error}）" if link.last_error else ""
            print(f"模拟模式{reason}，终端会显示模拟指令。")

        playback_started = time.perf_counter()
        started = playback_started if video_fps is None else 0.0
        flow = GazeBlinkDetector(started)
        # ================= 每帧循环：看 → 判 → 连 → 报 → 控 =================
        while True:
            # ---- ① 看：取一帧并识别，拿回 478 个关键点 ----
            video_time = frame_count / video_fps if video_fps is not None else None
            result = read_frame(cap, detector, started, video_time=video_time)
            if result is None:
                if frame_count == 0:
                    raise RuntimeError(f"录像没有可读取的画面：{video}")
                print("录像播放结束。")
                break
            frame, now, landmarks = result
            if video_fps is not None and frame.shape[:2] != (HEIGHT, WIDTH):
                frame = cv2.resize(frame, (WIDTH, HEIGHT))  # 面板和底部卡片使用固定坐标
            if landmarks is not None:
                draw_points(frame, landmarks)    # 顺便把关键点画出来（只为肉眼检查）

            # ---- ② 判：视线 + 眨眼，四状态机全在 GazeBlinkDetector 里 ----
            status = flow.update(now, landmarks)

            # ---- ③ 连：硬件链路（心跳/收电池）+ 状态变化时下发意图 ----
            link_info = control.update(now, status.state, status.active, face_present=landmarks is not None)

            # ---- ④ 报：状态面板 + 进度条 + 卡片 + 角标，推给窗口 ----
            frame_count += 1
            fps = video_fps if video_fps is not None else frame_count / max(now - started, 0.001)
            show_status(frame, status, now, fps, link_info)

            # ---- ⑤ 控：先看窗口还活着没，再读键盘 ----
            if not window_is_alive():            # 窗口被点 ✕ 关掉就退出
                print("窗口已关闭，退出。")
                break
            key_time = time.perf_counter()
            delay_ms = frame_delay_ms(playback_started, frame_count, video_fps, key_time)
            key, key_available_at = pressed_key(key_time, key_available_at, delay_ms)
            if key == "q":
                break
            if key == "c":
                flow.reset(now)                  # 回到校准起点，重新采集一次标尺
                link.set_intent("停")            # 校准期间不该挂着旧指令
            if key == "i":
                flow.toggle_invert()             # 左右方向反转 / 恢复
    finally:
        link.set_intent("停")                    # 无论怎么退出先叫停（模拟模式下是空操作）
        link.close()
        # 不调用 detector.close()：实测它要卡约 42 秒（MediaPipe 1.0.1 拆推理图的等待）。
        # 配合 make_detector() 里的保活引用，进程 1 秒内干净退出，内存由系统回收。
        cap.release()
        cv2.destroyAllWindows()


def cli() -> None:
    """解析录像和串口选项，按选定输出模式启动演示。"""
    parser = ArgumentParser(description="MediaPipe 视线选择与眨眼确认演示")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--video", type=Path, help="在屏幕模拟模式下播放录像，例如 MP4")
    source.add_argument("--serial-port", help="连接指定串口，例如 COM3")
    parser.add_argument("--firmware", choices=PROTOCOLS, help="固件协议，指定串口时默认 motor-test")
    args = parser.parse_args()
    serial_port = None if args.video is not None else select_serial_port(args.serial_port, firmware=args.firmware)
    main(args.video, serial_port=serial_port, firmware=args.firmware)


if __name__ == "__main__":
    cli()
