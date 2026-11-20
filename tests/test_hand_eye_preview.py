"""验证手眼预览的同帧检测、渲染和假串口输出。"""

from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

import gaze_blink_confirm_demo as gaze_demo
import hand_eye_preview as demo
from vision.hand_gesture_detector import HandGesture
from test_gaze_blink import eye_landmarks
from test_offline_workflows import FrameSource, simulate_window
from test_serial_link import FakeSerial, make_link, movement_letters


@pytest.mark.parametrize("entry", [demo, gaze_demo])
@pytest.mark.parametrize(("answers", "expected_port"), [
    ([""], None),
    (["1"], None),
    (["2", ""], None),
    (["invalid", "2", " COM9 "], "COM9"),
    ([EOFError()], None),
])
def test_visual_cli_uses_selected_output_mode(monkeypatch, entry, answers, expected_port):
    run = Mock()
    monkeypatch.setattr(entry, "main", run)
    monkeypatch.setattr(sys, "argv", [entry.__file__])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", Mock(side_effect=answers))

    entry.cli()

    model_option = {"gesture_model": demo.GESTURE_MODEL} if entry is demo else {}
    run.assert_called_once_with(None, serial_port=expected_port, firmware=None, **model_option)


@pytest.mark.parametrize("entry", [demo, gaze_demo])
@pytest.mark.parametrize(("options", "interactive", "video", "port"), [
    ([], False, None, None),
    (["--video", "sample.mp4"], True, Path("sample.mp4"), None),
    (["--serial-port", "COM9"], True, None, "COM9"),
])
def test_visual_cli_skips_menu_when_mode_is_already_known(monkeypatch, entry, options, interactive, video, port):
    run = Mock()
    prompt = Mock()
    monkeypatch.setattr(entry, "main", run)
    monkeypatch.setattr("builtins.input", prompt)
    monkeypatch.setattr(sys, "argv", [entry.__file__, *options])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: interactive))

    entry.cli()

    model_option = {"gesture_model": demo.GESTURE_MODEL} if entry is demo else {}
    run.assert_called_once_with(video, serial_port=port, firmware=None, **model_option)
    prompt.assert_not_called()


def test_keyboard_cli_uses_selected_port_and_firmware(monkeypatch):
    run = Mock()
    monkeypatch.setattr(demo.keyboard_serial, "main", run)
    monkeypatch.setattr(sys, "argv", [demo.__file__, "--keyboard", "--firmware", "wheelchair"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", Mock(side_effect=["2", "COM9"]))

    demo.cli()

    run.assert_called_once_with("COM9", firmware="wheelchair")


def test_mode_selection_can_be_cancelled_before_startup(monkeypatch):
    run = Mock()
    monkeypatch.setattr(demo, "main", run)
    monkeypatch.setattr(sys, "argv", [demo.__file__])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", Mock(side_effect=["2", KeyboardInterrupt()]))

    with pytest.raises(SystemExit) as exit_info:
        demo.cli()

    assert exit_info.value.code == 0
    run.assert_not_called()


def test_video_preview_draws_gestures_and_eyes_together_and_independently(tmp_path, monkeypatch, capsys):
    video = tmp_path / "sample.mp4"
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[0, 0] = (10, 20, 30)
    source = FrameSource([frame] * 3)
    eyes = SimpleNamespace(face_landmarks=[eye_landmarks(0.5, 0.3)])
    no_face = SimpleNamespace(face_landmarks=[])
    gesture = HandGesture(1, 0.87, (0.65, 0.65, 0.8, 0.8))
    face_detector = SimpleNamespace(detect_for_video=Mock(side_effect=[eyes, no_face, eyes]))
    gesture_detector = SimpleNamespace(detect=Mock(side_effect=[[gesture], [gesture], []]))
    create_face_detector = Mock(return_value=face_detector)
    create_gesture_detector = Mock(return_value=gesture_detector)
    open_video = Mock(return_value=(source, 10.0))
    open_camera = Mock(side_effect=AssertionError("录像模式不应打开摄像头"))
    make_link_for_mode = Mock(wraps=demo.WheelchairLink)
    monkeypatch.setattr(demo, "open_video", open_video)
    monkeypatch.setattr(demo, "create_face_landmarker", create_face_detector)
    monkeypatch.setattr(demo, "HandGestureDetector", create_gesture_detector)
    monkeypatch.setattr(demo, "open_camera", open_camera)
    monkeypatch.setattr(demo, "WheelchairLink", make_link_for_mode)
    show, close = simulate_window(monkeypatch, [-1] * 3)

    demo.main(video)

    open_video.assert_called_once_with(video)
    open_camera.assert_not_called()
    make_link_for_mode.assert_called_once_with(None, firmware=None)
    create_face_detector.assert_called_once_with(demo.FACE_MODEL)
    create_gesture_detector.assert_called_once_with(demo.GESTURE_MODEL)
    close.assert_called_once()
    assert source.released
    terminal = capsys.readouterr().out
    assert "录像播放结束" in terminal
    assert terminal.count("[手势] 1 Forward 0.87") == 1

    face_inputs = face_detector.detect_for_video.call_args_list
    assert [call.args[1] for call in face_inputs] == [0, 100, 200]
    assert all(tuple(call.args[0].numpy_view()[0, -1]) == (30, 20, 10) for call in face_inputs)
    assert len(gesture_detector.detect.call_args_list) == 3
    assert all(np.array_equal(call.args[0], frame) for call in gesture_detector.detect.call_args_list)

    displayed = [call.args[1][demo.PANEL_HEIGHT:] for call in show.call_args_list]
    has_eyes = [np.any(np.all(pixels == (0, 255, 255), axis=-1)) for pixels in displayed]
    has_gestures = [np.any(np.all(pixels == (0, 255, 0), axis=-1)) for pixels in displayed]
    assert has_eyes == [True, False, True]
    assert has_gestures == [True, True, False]


def test_video_cannot_open_serial_port(tmp_path, monkeypatch):
    transport = Mock()
    monkeypatch.setattr(demo, "WheelchairLink", transport)
    with pytest.raises(ValueError, match="不能同时指定串口"):
        demo.main(tmp_path / "sample.mp4", serial_port="COM9")
    transport.assert_not_called()


@pytest.mark.parametrize("firmware", [None, "wheelchair"])
def test_live_preview_sends_confirmed_direction_and_processes_stop_key(monkeypatch, capsys, firmware):
    eyes_open = SimpleNamespace(face_landmarks=[eye_landmarks(0.5, 0.3)])
    eyes_closed = SimpleNamespace(face_landmarks=[eye_landmarks(0.5, 0.0)])
    before_blink = [eyes_open] * 130
    landmarks = before_blink + [eyes_closed] * 5 + [eyes_open] * 10
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    capture = FrameSource([frame] * len(landmarks))
    read_frame = capture.read
    frame_number = 0

    def read_at_recorded_rate():
        nonlocal frame_number
        frame_number += 1
        return read_frame()

    clock = SimpleNamespace(perf_counter=lambda: frame_number / 30)
    face_detector = SimpleNamespace(detect_for_video=Mock(side_effect=landmarks))
    gesture = HandGesture(3, 0.92, (0.1, 0.1, 0.3, 0.3))
    gesture_detector = SimpleNamespace(detect=Mock(return_value=[gesture]))
    port = FakeSerial()
    link = demo.WheelchairLink("COM9", firmware=firmware, port_factory=lambda *args, **kwargs: port)
    open_transport = Mock(return_value=link)
    displayed = Mock(return_value=frame)
    monkeypatch.setattr(capture, "read", read_at_recorded_rate)
    monkeypatch.setattr(demo, "time", clock)
    monkeypatch.setattr(demo, "open_camera", lambda: capture)
    monkeypatch.setattr(demo, "create_face_landmarker", Mock(return_value=face_detector))
    monkeypatch.setattr(demo, "HandGestureDetector", Mock(return_value=gesture_detector))
    monkeypatch.setattr(demo, "WheelchairLink", open_transport)
    monkeypatch.setattr(demo, "render_preview", displayed)
    # S 和 Q 都应在上一次按键不到 0.25 秒时响应。
    simulate_window(monkeypatch, [-1] * (len(landmarks) - 3) + [ord("X"), ord("S"), ord("Q")])

    demo.main(serial_port="COM9", firmware=firmware)

    open_transport.assert_called_once_with("COM9", firmware=firmware)
    assert displayed.call_args_list[len(before_blink) - 1].args[4].state == "等待眨眼"
    confirmed = displayed.call_args_list[-2].args[4]
    assert (confirmed.state, confirmed.active) == ("确认成功", "前进")
    assert displayed.call_args.args[4].state == "校准"
    assert displayed.call_args.args[5].intent == "S"
    if firmware is None:
        assert port.tx == [b"S", b"F", b"S"]
    commands = movement_letters(port) if firmware else [payload.decode("ascii") for payload in port.tx]
    first_movement = commands.index("F")
    assert commands[0] == "S"
    assert all(command == "S" for command in commands[:first_movement])
    assert commands[first_movement:] == ["F", "S"]
    terminal = capsys.readouterr().out
    assert "[手势] 3 Left 0.92" in terminal
    assert "[串口 COM9] 已发送 F" in terminal
    assert capture.released and port.closed


def test_lost_face_stops_before_the_next_motion_heartbeat():
    link, port = make_link()
    control = demo.WheelchairControl(link)
    control.update(0.0, "等待眨眼", "前进", face_present=True)
    assert movement_letters(port) == []
    control.update(0.1, "确认成功", "前进", face_present=True)
    control.update(0.3, "选择方向", None, face_present=False)
    control.update(1.2, "选择方向", None, face_present=False)
    control.update(2.31, "选择方向", None, face_present=False)

    assert movement_letters(port) == ["F", "F", "S"]
    link.close()
