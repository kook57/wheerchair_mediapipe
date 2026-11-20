"""验证方向确认状态，以及主演示把确认结果交给模拟链路的流程。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

import gaze_blink_confirm_demo as demo
from interaction import gaze_blink_state, gaze_direction_state


@pytest.fixture
def feed(monkeypatch):
    monkeypatch.setattr(gaze_blink_state, "gaze_score", lambda frame: frame[0])
    monkeypatch.setattr(gaze_blink_state, "average_ear", lambda frame: frame[1])
    detector = gaze_blink_state.GazeBlinkDetector(0.0)
    frame_number = 0

    def feed_frames(frame, count):
        nonlocal frame_number
        for _ in range(count):
            status = detector.update(frame_number / 30, frame)
            frame_number += 1
        return status

    assert feed_frames((0.5, 0.30), 100).state == "选择方向"
    return feed_frames


def test_steadily_looking_center_after_calibration_selects_forward(feed):
    status = feed((0.5, 0.30), 30)
    assert (status.state, status.active) == ("等待眨眼", "前进")


def test_looking_away_cancels_old_direction_before_blink(feed):
    status = feed((0.2, 0.30), 35)
    assert (status.state, status.active) == ("等待眨眼", "左转")

    status = feed((0.8, 0.30), 6)
    assert (status.state, status.active) == ("选择方向", None)
    feed((0.8, 0.0), 5)
    status = feed((0.8, 0.30), 5)
    assert (status.state, status.active) == ("选择方向", None)


def test_face_loss_discards_old_dwell_and_unfinished_blink(feed):
    assert feed((0.2, 0.30), 35).state == "等待眨眼"
    feed((0.2, 0.0), 4)
    status = feed(None, 1)
    assert (status.state, status.active) == ("选择方向", None)

    status = feed((0.2, 0.30), 5)
    assert (status.state, status.active) == ("选择方向", None)
    status = feed((0.2, 0.30), 25)
    assert (status.state, status.active) == ("等待眨眼", "左转")


def test_gaze_preview_can_select_center_without_first_looking_sideways(monkeypatch):
    monkeypatch.setattr(gaze_direction_state, "gaze_score", lambda frame: frame)
    detector = gaze_direction_state.GazeDirectionDetector(0.0)
    for index in range(130):
        status = detector.update(index / 30, 0.5)
    assert (status.raw_direction, status.candidate) == ("中", "中")


def eye_landmarks(iris_position, ear):
    """按主演示的 MediaPipe 索引构造两只眼的轮廓和虹膜。"""
    landmarks = [SimpleNamespace(x=0.0, y=0.0)] * 478
    eye_width = 0.1
    eye_gap = ear * eye_width
    for start, eye, iris in ((0.25, demo.LEFT_EYE, demo.LEFT_IRIS),
                            (0.60, demo.RIGHT_EYE, demo.RIGHT_IRIS)):
        outline = ((0, 0), (0.3, -1), (0.7, -1), (1, 0), (0.7, 1), (0.3, 1))
        for index, (x, y) in zip(eye, outline):
            landmarks[index] = SimpleNamespace(x=start + x * eye_width, y=0.4 + y * eye_gap / 2)
        for index in iris:
            landmarks[index] = SimpleNamespace(x=start + iris_position * eye_width, y=0.4)
    return landmarks


@pytest.mark.parametrize("iris_position, direction", [(0.2, "左转"), (0.5, "前进"), (0.8, "右转")])
def test_demo_records_only_the_confirmed_direction(monkeypatch, iris_position, direction):
    first_position = 0.8 if iris_position == 0.2 else 0.2
    eyes_open = eye_landmarks(iris_position, 0.3)
    eyes_closed = eye_landmarks(iris_position, 0.0)
    frames = [eye_landmarks(0.5, 0.3)] * 100
    frames += [eye_landmarks(first_position, 0.3)] * 35
    first_candidate = len(frames) - 1
    frames += [eyes_open] * 8
    cancelled = len(frames) - 1
    frames += [eyes_closed] * 5  # 太早眨眼，原方向已取消
    frames += [eyes_open] * 35
    second_candidate = len(frames) - 1
    frames += [eyes_closed] * 5 + [eyes_open] * 10
    input_frames = iter(frames)
    frame = np.zeros((demo.HEIGHT, demo.WIDTH, 3), dtype=np.uint8)
    capture = Mock()
    statuses = []
    link = demo.WheelchairLink(None)
    set_intent = Mock(wraps=link.set_intent)
    monkeypatch.setattr(link, "set_intent", set_intent)
    monkeypatch.setattr(demo, "WheelchairLink", lambda port, **options: link)
    monkeypatch.setattr(demo, "open_video", lambda path: (capture, 30.0))
    monkeypatch.setattr(demo, "make_detector", Mock())
    monkeypatch.setattr(demo, "chinese_font", Mock())

    def read_frame(cap, detector, started, *, video_time):
        landmarks = next(input_frames, None)
        if landmarks is not None:
            return frame, video_time, landmarks
        return None

    monkeypatch.setattr(demo, "read_frame", read_frame)
    monkeypatch.setattr(demo, "draw_points", Mock())
    monkeypatch.setattr(demo, "show_status", lambda frame, status, now, fps, info: statuses.append(status))
    monkeypatch.setattr(demo, "window_is_alive", lambda: True)
    monkeypatch.setattr(demo, "pressed_key", lambda now, available_at, delay: (None, available_at))
    monkeypatch.setattr(demo.cv2, "destroyAllWindows", Mock())

    demo.main(Path("simulated.mp4"))

    first_direction = "左转" if first_position == 0.2 else "右转"
    assert (statuses[first_candidate].state, statuses[first_candidate].active) == ("等待眨眼", first_direction)
    assert (statuses[cancelled].state, statuses[cancelled].active) == ("选择方向", None)
    assert (statuses[second_candidate].state, statuses[second_candidate].active) == ("等待眨眼", direction)
    assert (statuses[-1].state, statuses[-1].active) == ("确认成功", direction)
    assert [call.args[0] for call in set_intent.call_args_list] == [direction, "停"]
    capture.release.assert_called_once()
