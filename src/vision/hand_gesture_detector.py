"""Adapt the best.onnx preprocessing and class mapping from gaze_wheelchair_pack/detect_all.py.

BGR frame → 640×640 RGB float tensor → YOLO candidates → confidence filter and NMS
→ hand gesture class, confidence and normalized box for visual output.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

GESTURE_LABELS = ("Stop", "Forward", "Backward", "Left", "Right", "Invalid")
INPUT_SIZE = 640
CONFIDENCE_THRESHOLD = 0.4
IOU_THRESHOLD = 0.5


@dataclass(frozen=True)
class HandGesture:
    class_id: int
    confidence: float
    box: tuple[float, float, float, float]

    @property
    def label(self) -> str:
        return GESTURE_LABELS[self.class_id]


def decode_gestures(output: np.ndarray) -> list[HandGesture]:
    """Decode best.onnx rows as centre x/y, width/height, objectness and six class scores."""
    if output.ndim != 3 or output.shape[0] != 1 or output.shape[2] != 5 + len(GESTURE_LABELS):
        raise ValueError(f"手势模型输出应为 (1, N, 11)，实际为 {output.shape}。")

    rows = output[0]
    class_ids = np.argmax(rows[:, 5:], axis=1)
    scores = rows[:, 4] * rows[np.arange(len(rows)), 5 + class_ids]
    valid = (scores > CONFIDENCE_THRESHOLD) & np.isfinite(rows).all(axis=1) & (rows[:, 2:4] > 0).all(axis=1)
    rows, class_ids, scores = rows[valid], class_ids[valid], scores[valid]
    if not len(rows):
        return []

    # OpenCV NMS takes top-left x/y and width/height, whereas the model uses box centres.
    boxes = rows[:, :4].copy()
    boxes[:, :2] -= boxes[:, 2:4] / 2
    keep = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), CONFIDENCE_THRESHOLD, IOU_THRESHOLD)
    gestures = []
    for index in sorted(np.asarray(keep).flat, key=lambda index: -scores[index]):
        x, y, width, height = boxes[index]
        x1, y1, x2, y2 = np.clip(np.array([x, y, x + width, y + height]) / INPUT_SIZE, 0, 1)
        box = (float(x1), float(y1), float(x2), float(y2))
        gestures.append(HandGesture(int(class_ids[index]), float(scores[index]), box))
    return gestures


class HandGestureDetector:
    """Load the pack's six-class model once and classify each preview frame on the CPU."""

    def __init__(self, model_path: Path) -> None:
        if not model_path.is_file():
            raise FileNotFoundError(f"找不到手势模型：{model_path}。用 --gesture-model 指定运行包中的 best.onnx。")
        try:
            import onnxruntime as ort
        except ImportError as error:
            raise RuntimeError("手势检测需要 onnxruntime，请使用当前 Python 环境安装。") from error

        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self._session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        model_input = self._session.get_inputs()[0]
        model_output = self._session.get_outputs()[0]
        if (model_input.shape != [1, 3, INPUT_SIZE, INPUT_SIZE]
                or len(model_output.shape) != 3 or model_output.shape[2] != 5 + len(GESTURE_LABELS)):
            raise ValueError(f"手势模型不兼容：{model_path}。请使用运行包的 best.onnx。")
        self._input_name = model_input.name
        self._output_name = model_output.name

    def detect(self, frame: np.ndarray) -> list[HandGesture]:
        """Return detected gestures in descending confidence order."""
        resized = cv2.resize(frame, (INPUT_SIZE, INPUT_SIZE))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        tensor = np.ascontiguousarray(rgb.transpose(2, 0, 1)[None])
        output, = self._session.run([self._output_name], {self._input_name: tensor})
        return decode_gestures(output)
