"""Check the pack's model output contract, confidence filtering, NMS and labels."""

import numpy as np
import pytest

from vision.hand_gesture_detector import decode_gestures


def test_decode_prefers_strongest_overlap_and_keeps_different_boxes():
    rows = np.zeros((1, 4, 11), dtype=np.float32)
    rows[0, :, :5] = [
        [320, 320, 160, 160, 0.9],
        [325, 320, 160, 160, 0.8],
        [80, 80, 160, 160, 0.8],
        [520, 520, 80, 80, 0.3],
    ]
    rows[0, 0, 6] = 0.95  # Forward
    rows[0, 1, 8] = 0.9   # Overlapping Left
    rows[0, 2, 5] = 0.8   # Separate Stop
    rows[0, 3, 9] = 0.9   # Right below threshold

    gestures = decode_gestures(rows)

    assert [gesture.label for gesture in gestures] == ["Forward", "Stop"]
    assert gestures[0].confidence == pytest.approx(0.855)
    assert gestures[0].box == pytest.approx((0.375, 0.375, 0.625, 0.625))
    assert gestures[1].box == pytest.approx((0.0, 0.0, 0.25, 0.25))


def test_decode_rejects_other_model_output_layout():
    with pytest.raises(ValueError, match="手势模型输出"):
        decode_gestures(np.zeros((1, 9, 8400), dtype=np.float32))
