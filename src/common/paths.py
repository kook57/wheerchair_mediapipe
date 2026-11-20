"""摄像头和视觉入口使用的项目路径。"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = PROJECT_ROOT / "models"
DATA_DIR = PROJECT_ROOT / "data"

FACE_MODEL = MODEL_DIR / "face_landmarker.task"
HAND_MODEL = MODEL_DIR / "hand_landmarker.task"
GESTURE_MODEL = MODEL_DIR / "gesture_best.onnx"

RAW_VIDEOS_DIR = DATA_DIR / "raw_videos"
CAMERA_SNAPSHOTS_DIR = DATA_DIR / "snapshots"
LANDMARK_SNAPSHOTS_DIR = DATA_DIR / "landmark_snapshots"
