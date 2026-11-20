"""视线方向状态机。GazeDirectionDetector.update() 将关键点转成 GazeStatus。"""

from collections import deque
from dataclasses import dataclass

from vision.eye_geometry import gaze_score as iris_position


CALIBRATION_SECONDS = 3.0     # 校准时长：这段时间请看屏幕正中间
CALIBRATION_MIN_SAMPLES = 10  # 样本下限：帧率过低时样本太少，基准不可靠
SIDE_THRESHOLD = 0.075        # 相对于正视基准的水平偏移：超过它才算看左/看右
STABLE_SECONDS = 0.70         # 同方向稳定停留多久才成为候选
SMOOTHING_FRAMES = 5          # 虹膜位置平滑：最近几帧取平均
MESSAGE_INITIAL = "请看屏幕正中间，正在校准"

def gaze_score(landmarks) -> float | None:
    """计算预览的虹膜位置，接受恰好达到最小跨度的眼角。"""
    return iris_position(landmarks, include_minimum=True)


@dataclass(frozen=True)
class GazeStatus:
    """一帧的判定结果快照，供界面显示。

    调用关系：由 GazeDirectionDetector._status() 产出 → 被 main() 接住 → 交给 show_status()。
    它只是"数据袋子"，自身不含任何逻辑。
    """

    score: float | None          # 本帧的虹膜位置（平滑后；没人脸或不可用时是 None）
    center: float | None         # 正视基准（校准完成前是 None）
    raw_direction: str           # 这一帧视线落在哪个方向：左 / 中 / 右
    candidate: str               # 稳定停留够久的方向；还没稳定时是 "无"
    message: str                 # 屏幕上第三行显示的提示语


class GazeDirectionDetector:
    """视线方向的校准 + 选择状态机。原来散在 main() 里的状态，现在全在这个对象里。

    调用关系：main() 在启动时建一个；之后每帧调 update()；
    按 C 调 reset()，按 I 调 toggle_invert()。update() 内部按阶段分派：
      校准没完成（center 还是 None）→ _update_calibration()
      校准完成                      → _update_selection()
    两种情况都由 _status(...) 打包成 GazeStatus 返回。

    用法：`GazeDirectionDetector(time.perf_counter())`，之后每帧调用
    `update(now, landmarks)`；没检测到人脸时传 None。
    注意它只依赖关键点对象上的 .x 属性，不 import cv2 或 mediapipe，
    所以测试时可以喂"只有 x、y 的假点"。
    """

    def __init__(
        self,
        now: float,
        *,
        calibration_seconds: float = CALIBRATION_SECONDS,
        calibration_min_samples: int = CALIBRATION_MIN_SAMPLES,
        side_threshold: float = SIDE_THRESHOLD,
        stable_seconds: float = STABLE_SECONDS,
        smoothing_frames: int = SMOOTHING_FRAMES,
    ) -> None:
        self._calibration_seconds = calibration_seconds
        self._calibration_min_samples = calibration_min_samples
        self._side_threshold = side_threshold
        self._stable_seconds = stable_seconds
        # 平滑用的滚动队列：最近几帧虹膜位置
        self._history: deque[float] = deque(maxlen=smoothing_frames)
        self._invert = False  # 按 I 切换：左右方向是否反转
        self.reset(now)

    def reset(self, now: float, message: str = MESSAGE_INITIAL) -> None:
        """回到校准起点。构造时和按 C 重新校准时都走这里，避免两处手抄不一致。"""
        self._calibration_started = now           # 校准阶段的起始时间
        self._calibration_values: list[float] = []  # 校准期间攒的虹膜位置
        self._center: float | None = None         # 正视基准；它等于 None 就表示"还在校准"
        self._history.clear()
        # ---- 状态机的两个方向变量 ----
        #   _raw_direction : 这一帧视线落在哪个方向（会抖）
        #   _candidate     : 稳定停留够久的那个方向；还没稳定时是 "无"
        self._raw_direction = "中"
        self._candidate = "无"
        self._direction_since: float | None = None  # 当前方向从什么时候开始
        self._message = message

    def toggle_invert(self) -> None:
        """按 I 时调用：把左右方向反过来，并更新屏幕提示。"""
        self._invert = not self._invert
        self._message = "左右方向已反转" if self._invert else "左右方向已恢复"

    def update(self, now: float, landmarks) -> GazeStatus:
        """吃一帧数据，返回本帧状态。landmarks 传 None 表示这帧没检测到人脸。"""
        if landmarks is None:
            # 没人脸：候选作废、方向重新计时；但"校准"不打断（否则一转头就白校准了）
            self._message = "未检测到人脸：请正对摄像头"
            self._candidate = "无"
            self._direction_since = None
            return self._status(score=None)

        score = gaze_score(landmarks)
        if score is not None:
            self._history.append(score)
            score = sum(self._history) / len(self._history)  # 最近几帧取平均，抹掉抖动

        if self._center is None and score is not None:
            self._update_calibration(now, score)
        elif self._center is not None and score is not None:
            self._update_selection(now, score)
        return self._status(score=score)

    def _update_calibration(self, now: float, score: float) -> None:
        """校准阶段：攒样本，够 3 秒且样本足够后算出正视基准 _center。"""
        self._calibration_values.append(score)
        elapsed = now - self._calibration_started
        self._message = f"校准中：请看屏幕正中间 {max(0, self._calibration_seconds - elapsed):.1f} 秒"
        if elapsed < self._calibration_seconds or len(self._calibration_values) < self._calibration_min_samples:
            return
        # 掐掉头尾各 10%（偶发眨眼的极值），用中间 80% 的平均值当正视基准
        values = sorted(self._calibration_values)
        trim = max(1, len(values) // 10)
        kept = values[trim:-trim] or values
        self._center = sum(kept) / len(kept)
        self._message = "校准完成：依次看屏幕左、中、右区域"

    def _update_selection(self, now: float, score: float) -> None:
        """校准完成后：把偏移量分成 左/中/右，稳定停留够久就记为候选。"""
        offset = score - self._center
        if self._invert:
            offset = -offset
        if offset < -self._side_threshold:
            new_direction = "左"
        elif offset > self._side_threshold:
            new_direction = "右"
        else:
            new_direction = "中"

        if self._direction_since is None or new_direction != self._raw_direction:
            # 初次有效注视或方向变化时重新计时
            self._raw_direction = new_direction
            self._direction_since = now
            self._candidate = "无"
        elif now - self._direction_since >= self._stable_seconds:
            # 同一方向稳定停留够久 → 成为候选
            self._candidate = self._raw_direction
        self._message = "只是在选择候选方向；本程序不会移动轮椅"

    def _status(self, score: float | None) -> GazeStatus:
        """把当前内部状态打包成 GazeStatus（界面唯一能读到的东西）。"""
        return GazeStatus(
            score=score,
            center=self._center,
            raw_direction=self._raw_direction,
            candidate=self._candidate,
            message=self._message,
        )
