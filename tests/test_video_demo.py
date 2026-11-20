"""录像演示经过真实 MP4 解码、模型推理和界面渲染。"""

import cv2
import numpy as np
import pytest

import gaze_blink_confirm_demo as demo


def test_demo_plays_mp4_to_end_without_camera_or_serial(tmp_path, monkeypatch, capsys):
    path = tmp_path / "recording with spaces.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (320, 240))
    try:
        if not writer.isOpened():
            pytest.skip("当前 OpenCV 无法写入 MP4 测试录像")
        for _ in range(4):
            writer.write(np.zeros((240, 320, 3), dtype=np.uint8))
    finally:
        writer.release()

    def unexpected_camera():
        pytest.fail("录像模式尝试打开摄像头")

    link_type = demo.WheelchairLink

    def simulated_link(port, *, firmware=None):
        assert port is None
        return link_type(port, firmware=firmware)

    displayed = []
    monkeypatch.setattr(demo, "open_camera", unexpected_camera)
    monkeypatch.setattr(demo, "WheelchairLink", simulated_link)
    monkeypatch.setattr(demo, "window_is_alive", lambda: True)
    monkeypatch.setattr(cv2, "imshow", lambda title, frame: displayed.append(frame))
    monkeypatch.setattr(cv2, "waitKey", lambda delay: -1)
    monkeypatch.setattr(cv2, "destroyAllWindows", lambda: None)

    demo.main(path)

    assert len(displayed) == 4
    assert all(frame.shape == (demo.HEIGHT, demo.WIDTH, 3) and frame.any() for frame in displayed)
    assert "录像播放结束" in capsys.readouterr().out


def test_open_video_reports_missing_file(tmp_path):
    path = tmp_path / "missing.mp4"
    with pytest.raises(FileNotFoundError, match="missing.mp4"):
        demo.open_video(path)
