"""以合成视频帧和假串口跑演示入口，输出写入 pytest 临时目录。

录像用例通过 FrameSource → 摄像头预览入口 → MP4/JPG 落盘。
视觉用例通过预览入口 → MediaPipe 或合成关键点 → 状态和渲染。
串口用例通过主演示 → 方向确认 → WheelchairLink → FakeSerial。

设置 WHEELCHAIR_TEST_MEDIA_DIR 并放入 MediaPipe 的 portrait.jpg 和
thumb_up.jpg 时，也验证真实样图的关键点。默认用空白帧验证模型和截图。
"""

from os import environ
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

import blink_preview
import gaze_blink_confirm_demo as demo
import gaze_direction_preview
from camera import camera_preview
from vision import landmarks_preview

from test_gaze_blink import eye_landmarks
from test_serial_link import FakeSerial, make_link, movement_letters


class FrameSource:
    """提供 VideoCapture 主流程使用的接口和预设画面。"""

    def __init__(self, frames, fps=30.0):
        self.frames = iter(frames)
        height, width = frames[0].shape[:2]
        self.properties = {
            cv2.CAP_PROP_FPS: fps,
            cv2.CAP_PROP_FRAME_WIDTH: width,
            cv2.CAP_PROP_FRAME_HEIGHT: height,
        }
        self.released = False

    def read(self):
        frame = next(self.frames, None)
        return frame is not None, frame

    def get(self, property_id):
        return self.properties[property_id]

    def release(self):
        self.released = True


def simulate_window(monkeypatch, keys):
    """按指定顺序模拟按键，记录应用提交的画面。"""
    show = Mock()
    close = Mock()
    monkeypatch.setattr(cv2, "imshow", show)
    monkeypatch.setattr(cv2, "waitKey", Mock(side_effect=keys))
    monkeypatch.setattr(cv2, "getWindowProperty", lambda title, prop: 1.0)
    monkeypatch.setattr(cv2, "destroyAllWindows", close)
    return show, close


def simulate_clock(monkeypatch, module, frame_count, interval=0.1):
    times = iter(index * interval for index in range(frame_count + 1))
    monkeypatch.setattr(module, "time", SimpleNamespace(perf_counter=lambda: next(times)))


@pytest.mark.parametrize("stop_key", ["R", "Q"], ids=["stop-recording", "quit-while-recording"])
def test_camera_preview_saves_photo_and_playable_video(tmp_path, monkeypatch, stop_key):
    keys = [ord("R"), ord("R"), -1, ord("S"), -1, ord(stop_key)]
    if stop_key == "R":
        keys.extend([-1, ord("Q")])
    frames = [np.full((240, 320, 3), 30 + index * 18, dtype=np.uint8) for index in range(len(keys))]
    source = FrameSource(frames, fps=0.0)
    video_dir = tmp_path / "videos"
    snapshot_dir = tmp_path / "snapshots"
    monkeypatch.setattr(camera_preview, "open_camera", lambda: source)
    monkeypatch.setattr(camera_preview, "VIDEO_DIR", video_dir)
    monkeypatch.setattr(camera_preview, "SNAPSHOT_DIR", snapshot_dir)
    show, close = simulate_window(monkeypatch, keys)

    camera_preview.main()

    assert show.call_count == len(keys)
    assert np.any(show.call_args_list[0].args[1] != frames[0])
    assert source.released
    close.assert_called_once()
    snapshot_path, = snapshot_dir.glob("snapshot_*.jpg")
    snapshot = cv2.imread(str(snapshot_path))
    assert snapshot is not None and snapshot.shape == frames[3].shape
    assert float(snapshot.mean()) == pytest.approx(float(frames[3].mean()), abs=3)

    video_path, = video_dir.glob("camera_test_*.mp4")
    video = cv2.VideoCapture(str(video_path))
    try:
        assert video.isOpened()
        assert video.get(cv2.CAP_PROP_FPS) == pytest.approx(30.0)
        for expected in frames[1:6]:
            ok, recorded = video.read()
            assert ok and recorded.shape == expected.shape
            assert float(recorded.mean()) == pytest.approx(float(expected.mean()), abs=6)
        assert not video.read()[0]
    finally:
        video.release()


def test_landmarks_preview_runs_both_models_and_saves_overlay(tmp_path, monkeypatch):
    media_dir = environ.get("WHEELCHAIR_TEST_MEDIA_DIR")
    if media_dir:
        paths = [Path(media_dir) / name for name in ("portrait.jpg", "thumb_up.jpg")]
        frames = [cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR) for path in paths]
        assert all(frame is not None for frame in frames)
    else:
        frames = [np.zeros((540, 960, 3), dtype=np.uint8)] * 2
    source = FrameSource(frames)
    monkeypatch.setattr(landmarks_preview, "open_camera", lambda: source)
    monkeypatch.setattr(landmarks_preview, "SNAPSHOT_DIR", tmp_path)
    simulate_clock(monkeypatch, landmarks_preview, len(frames), interval=0.4)
    show, close = simulate_window(monkeypatch, [ord("S"), ord("Q")])
    draw_results = Mock(wraps=landmarks_preview.draw_results)
    monkeypatch.setattr(landmarks_preview, "draw_results", draw_results)

    landmarks_preview.main()

    assert show.call_count == draw_results.call_count == 2
    face_result = draw_results.call_args_list[0].args[1]
    hand_result = draw_results.call_args_list[1].args[2]
    if media_dir:
        assert len(face_result.face_landmarks[0]) == 478
        assert len(hand_result.hand_landmarks[0]) == 21
        assert hand_result.handedness[0][0].category_name in {"Left", "Right"}
    else:
        assert not face_result.face_landmarks
        assert not hand_result.hand_landmarks
    assert np.any(show.call_args_list[0].args[1] != cv2.flip(frames[0], 1))
    snapshot_path, = tmp_path.glob("landmarks_*.jpg")
    snapshot = cv2.imread(str(snapshot_path))
    assert snapshot is not None and snapshot.shape == frames[0].shape
    assert snapshot.any()
    assert source.released
    close.assert_called_once()


def run_landmark_preview(monkeypatch, module, detector_factory, landmarks, keys):
    """调用预览入口，用合成关键点替代推理输出，保留状态机和渲染。"""
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    source = FrameSource([frame] * len(landmarks))
    detect = Mock(side_effect=[SimpleNamespace(face_landmarks=[points]) for points in landmarks])
    detector = SimpleNamespace(detect_for_video=detect)
    show_status = Mock(wraps=module.show_status)
    monkeypatch.setattr(module, "open_camera", lambda: source)
    monkeypatch.setattr(module, detector_factory, lambda: detector)
    monkeypatch.setattr(module, "show_status", show_status)
    simulate_clock(monkeypatch, module, len(landmarks))
    show, close = simulate_window(monkeypatch, keys)

    module.main()

    assert detect.call_count == show_status.call_count == show.call_count == len(keys)
    assert show.call_args.args[1].any()
    assert source.released
    close.assert_called_once()
    return [call.args[1] for call in show_status.call_args_list]


def test_blink_preview_counts_one_blink_and_recalibrates(monkeypatch):
    eyes_open = eye_landmarks(0.5, 0.3)
    eyes_closed = eye_landmarks(0.5, 0.0)
    blink_frames = [eyes_open] * 38 + [eyes_closed] * 3 + [eyes_open] * 8
    # C 和 Q 间留出按键防抖时间。
    keys = [-1] * (len(blink_frames) - 1) + [ord("C")] + [-1] * 3 + [ord("Q")]
    statuses = run_landmark_preview(
        monkeypatch, blink_preview, "face_detector", blink_frames + [eyes_open] * 4, keys,
    )

    assert statuses[0].is_calibrating
    assert statuses[len(blink_frames) - 1].blink_count == 1
    assert statuses[-1].is_calibrating
    assert statuses[-1].blink_count == 0


def test_gaze_preview_selects_inverts_and_recalibrates(monkeypatch):
    center = eye_landmarks(0.5, 0.3)
    left = eye_landmarks(0.2, 0.3)
    before_inverting = [center] * 34 + [left] * 14
    after_inverting = [left] * 14
    keys = (
        [-1] * (len(before_inverting) - 1) + [ord("I")]
        + [-1] * (len(after_inverting) - 1) + [ord("C")] + [-1] * 3 + [ord("Q")]
    )
    statuses = run_landmark_preview(
        monkeypatch, gaze_direction_preview, "create_detector",
        before_inverting + after_inverting + [center] * 4, keys,
    )

    assert statuses[len(before_inverting) - 1].candidate == "左"
    assert statuses[len(before_inverting) + len(after_inverting) - 1].candidate == "右"
    assert statuses[-1].center is None
    assert statuses[-1].candidate == "无"


def test_demo_converts_detected_blink_to_serial_bytes(monkeypatch):
    eyes_open = eye_landmarks(0.5, 0.3)
    eyes_closed = eye_landmarks(0.5, 0.0)
    before_blink = [eyes_open] * 130
    landmarks = before_blink + [eyes_closed] * 5 + [eyes_open] * 10
    frame = np.zeros((demo.HEIGHT, demo.WIDTH, 3), dtype=np.uint8)
    source = FrameSource([frame] * len(landmarks))
    read_frame = source.read
    frame_number = 0

    def read_at_recorded_rate():
        nonlocal frame_number
        frame_number += 1
        return read_frame()

    detect = Mock(side_effect=[SimpleNamespace(face_landmarks=[points]) for points in landmarks])
    detector = SimpleNamespace(detect_for_video=detect)
    port = FakeSerial()
    link = demo.WheelchairLink("test-port", firmware="wheelchair", port_factory=lambda *args, **kwargs: port)
    statuses = Mock()
    monkeypatch.setattr(source, "read", read_at_recorded_rate)
    monkeypatch.setattr(demo, "time", SimpleNamespace(perf_counter=lambda: frame_number / 30))
    monkeypatch.setattr(demo, "open_camera", lambda: source)
    monkeypatch.setattr(demo, "make_detector", lambda: detector)
    monkeypatch.setattr(demo, "show_status", statuses)
    monkeypatch.setattr(demo, "chinese_font", Mock())
    monkeypatch.setattr(demo, "WheelchairLink", Mock(return_value=link))
    simulate_window(monkeypatch, [-1] * (len(landmarks) - 1) + [ord("Q")])

    demo.main(serial_port="test-port", firmware="wheelchair")

    assert detect.call_count == len(landmarks)
    assert statuses.call_args_list[len(before_blink) - 1].args[1].state == "等待眨眼"
    confirmation = statuses.call_args.args[1]
    assert (confirmation.state, confirmation.active) == ("确认成功", "前进")
    assert b"GET_DATA\n" in port.tx
    assert [command for command in port.tx if command != b"GET_DATA\n"] == [b"F\n", b"S\n"]
    assert port.closed and source.released


@pytest.mark.parametrize("operation", ["read", "write"])
def test_serial_disconnect_reports_failure_and_closes_port(monkeypatch, operation):
    link, port = make_link(rx=b"pending")
    link.set_intent("前进", now=0.0)
    failed_call = Mock(side_effect=OSError("disconnected"))
    monkeypatch.setattr(port, operation, failed_call)

    status = link.update(1.05)
    assert not status.connected
    assert "disconnected" in status.last_error
    assert movement_letters(port) == ["F"]

    link.update(2.10)
    failed_call.assert_called_once()
    link.close()
    assert port.closed
