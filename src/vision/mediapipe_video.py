"""视觉入口启动时创建检测器，每帧将镜像 BGR 图转成 MediaPipe RGB 图。

创建检测器 → read_detection_input() → detect_for_video(图像, 毫秒时间戳)。
单人脸入口通过 read_face_frame() 读取第一张脸的关键点。
"""

from collections.abc import Callable
from pathlib import Path

import cv2
import mediapipe as mp

# Windows 上回收检测器时可能长时间阻塞，保留引用到进程退出。
_active_detectors = []


def create_face_landmarker(model_path: Path):
    """用项目统一的 VIDEO 参数加载单人脸识别器。"""
    if not model_path.exists():
        raise FileNotFoundError(f"缺少模型文件：{model_path}")
    vision = mp.tasks.vision
    options = vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    detector = vision.FaceLandmarker.create_from_options(options)
    _active_detectors.append(detector)
    return detector


def create_hand_landmarker(model_path: Path):
    """为同帧预览加载至多两只手的 VIDEO 识别器。"""
    if not model_path.exists():
        raise FileNotFoundError(f"缺少模型文件：{model_path}")
    vision = mp.tasks.vision
    options = vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    detector = vision.HandLandmarker.create_from_options(options)
    _active_detectors.append(detector)
    return detector


def create_face_hand_landmarkers(face_model: Path, hand_model: Path):
    """验证两个模型文件后，为同帧预览创建检测器。"""
    missing = [path.name for path in (face_model, hand_model) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"缺少模型：{', '.join(missing)}")
    return create_face_landmarker(face_model), create_hand_landmarker(hand_model)


def read_detection_input(capture, started: float, *, clock: Callable[[], float], video_time: float | None = None):
    """返回镜像 BGR 帧、当前时间、RGB 推理图像和相对毫秒时间戳。"""
    ok, frame = capture.read()
    if not ok:
        if video_time is not None:
            return None
        raise RuntimeError("摄像头读取失败。")
    frame = cv2.flip(frame, 1)
    now = clock() if video_time is None else video_time
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    return frame, now, image, int((now - started) * 1000)


def read_face_frame(capture, detector, started: float, *, clock: Callable[[], float], video_time: float | None = None):
    """返回帧、当前时间和首张脸的关键点。录像到片尾时返回 None。"""
    prepared = read_detection_input(capture, started, clock=clock, video_time=video_time)
    if prepared is None:
        return None
    frame, now, image, timestamp_ms = prepared
    faces = detector.detect_for_video(image, timestamp_ms).face_landmarks
    return frame, now, faces[0] if faces else None


def read_face_hand_frame(
    capture, face_detector, hand_detector, started: float, *,
    clock: Callable[[], float], video_time: float | None = None,
):
    """用同一张推理图和时间戳取得人脸和手部结果。"""
    prepared = read_detection_input(capture, started, clock=clock, video_time=video_time)
    if prepared is None:
        return None
    frame, now, image, timestamp_ms = prepared
    face_result = face_detector.detect_for_video(image, timestamp_ms)
    hand_result = hand_detector.detect_for_video(image, timestamp_ms)
    return frame, now, face_result, hand_result
