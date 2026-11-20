"""摄像头和录像输入。演示打开输入一遍，再按 frame_delay_ms 安排播放节奏。"""

from math import ceil, isfinite
from pathlib import Path

import cv2


def open_camera(index: int, width: int, height: int, *, error_message: str) -> cv2.VideoCapture:
    """优先以 DirectShow 打开摄像头，再尝试 OpenCV 的默认后端。"""
    capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not capture.isOpened():
        capture.release()
        capture = cv2.VideoCapture(index)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(error_message)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return capture


def open_video(path: Path) -> tuple[cv2.VideoCapture, float]:
    """打开录像并返回标称帧率，供演示计算帧时间。"""
    if not path.is_file():
        raise FileNotFoundError(f"找不到录像：{path}")
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"录像无法打开：{path}")
    fps = capture.get(cv2.CAP_PROP_FPS)
    if not isfinite(fps) or fps <= 0:
        capture.release()
        raise RuntimeError(f"无法读取录像帧率：{path}")
    return capture, fps


def frame_delay_ms(started: float, frame_count: int, fps: float | None, now: float) -> int:
    """计算 waitKey 的等待时间，使录像按原帧率推进，摄像头则尽快读取。"""
    if fps is None:
        return 1
    next_frame_at = started + frame_count / fps
    return max(1, ceil((next_frame_at - now) * 1000))
