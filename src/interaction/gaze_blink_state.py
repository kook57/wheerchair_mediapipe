"""视线与眨眼确认状态机。关键点 → 开合比和虹膜位置 → GazeBlinkStatus。"""

from collections import deque
from dataclasses import dataclass
import math

from vision.eye_geometry import average_ear, gaze_score


CALIBRATION_SECONDS = 3.0                            # 校准时长：这段时间请看屏幕正中间
CALIBRATION_MIN_SAMPLES = 10                         # 样本下限：帧率过低时样本太少，标尺不可靠
SIDE_THRESHOLD = 0.075                               # 虹膜偏移超过它才算"看左/看右"
SELECT_STABLE_SECONDS = 0.70                         # 同一方向要稳定停留这么久才成为候选
CLOSE_RATIO, REOPEN_RATIO = 0.78, 0.88               # 闭眼线 / 睁眼线（相对睁眼基线的百分比）
MIN_CLOSED_SECONDS, MAX_CLOSED_SECONDS = 0.04, 0.80  # 一次自然眨眼的闭眼时长范围
MIN_OPEN_SECONDS, REFRACTORY_SECONDS = 0.10, 0.30    # 需要稳定睁眼多久 / 两次计数的最小间隔
GAZE_SMOOTHING_FRAMES = 5                            # 虹膜位置平滑：最近几帧取平均
EAR_SMOOTHING_FRAMES = 3                             # 眼睛开合值平滑：最近几帧取平均


@dataclass(frozen=True)
class GazeBlinkStatus:
    """一帧的判定结果快照，供界面显示。

    调用关系：由 GazeBlinkDetector._status() 产出 → 被 main() 接住 → 交给 show_status()。
    它只是"数据袋子"，自身不含任何逻辑。
    """

    state: str            # 四个状态里的哪一个：校准 / 选择方向 / 等待眨眼 / 确认成功
    message: str          # 屏幕上第三行显示的提示语
    score: float | None   # 本帧的虹膜位置（没人脸时是 None）
    ear: float | None     # 本帧的眼睛开合值（没人脸时是 None）
    active: str | None    # 该高亮哪张卡片：左转 / 前进 / 右转 / None
    calibration_progress: float | None = None  # 校准进度 0~1（仅校准状态有值）
    stability_progress: float | None = None    # 方向稳定进度 0~1（仅选择方向状态有值）
    raw_direction: str | None = None           # 本次有效注视对应的方向


class GazeBlinkDetector:
    """视线选择 + 眨眼确认的四状态机。原来散在 main() 里的状态，现在全在这个对象里。

    调用关系：main() 在启动时建一个；之后每帧调 update()；
    按 C 调 reset()，按 I 调 toggle_invert()。update() 内部按状态分派：
      校准没完成 → _update_calibration()
      选择方向 / 等待眨眼 → _update_selection()
      确认成功    → 纯计时，时间到就回选择方向
    每种情况的最后都由 _status() 打包成 GazeBlinkStatus 返回。

    用法：`GazeBlinkDetector(time.perf_counter())`，之后每帧调用
    `update(now, landmarks)`；没检测到人脸时传 None。
    注意它只依赖关键点对象上的 .x / .y 两个属性，不 import cv2 或 mediapipe，
    所以测试时可以喂"只有 x、y 的假点"。
    """

    def __init__(
        self,
        now: float,
        *,
        calibration_seconds: float = CALIBRATION_SECONDS,
        calibration_min_samples: int = CALIBRATION_MIN_SAMPLES,
        side_threshold: float = SIDE_THRESHOLD,
        select_stable_seconds: float = SELECT_STABLE_SECONDS,
        close_ratio: float = CLOSE_RATIO,
        reopen_ratio: float = REOPEN_RATIO,
        min_closed_seconds: float = MIN_CLOSED_SECONDS,
        max_closed_seconds: float = MAX_CLOSED_SECONDS,
        min_open_seconds: float = MIN_OPEN_SECONDS,
        refractory_seconds: float = REFRACTORY_SECONDS,
        gaze_smoothing_frames: int = GAZE_SMOOTHING_FRAMES,
        ear_smoothing_frames: int = EAR_SMOOTHING_FRAMES,
    ) -> None:
        self._calibration_seconds = calibration_seconds
        self._calibration_min_samples = calibration_min_samples
        self._side_threshold = side_threshold
        self._select_stable_seconds = select_stable_seconds
        self._close_ratio = close_ratio
        self._reopen_ratio = reopen_ratio
        self._min_closed_seconds = min_closed_seconds
        self._max_closed_seconds = max_closed_seconds
        self._min_open_seconds = min_open_seconds
        self._refractory_seconds = refractory_seconds
        # 平滑用的滚动队列：最近几帧虹膜位置、最近几帧开合值
        self._gaze_history: deque[float] = deque(maxlen=gaze_smoothing_frames)
        self._ear_history: deque[float] = deque(maxlen=ear_smoothing_frames)
        self._invert = False  # 按 I 切换：左右方向是否反转
        self.reset(now)

    def reset(self, now: float) -> None:
        """回到校准起点。构造时和按 C 重新校准时都走这里，避免两处手抄不一致。"""
        self._calibration_started = now          # 校准阶段的起始时间
        self._gaze_values: list[float] = []      # 校准期间攒的虹膜位置
        self._ear_values: list[float] = []       # 校准期间攒的开合值
        # 三个"标尺"，校准完成后才有值：
        #   _center      = 正视时虹膜该在的位置
        #   _close_line  = 闭眼判定线（低于它算闭眼）
        #   _reopen_line = 睁眼判定线（高于它算睁开）
        self._center: float | None = None
        self._close_line: float | None = None
        self._reopen_line: float | None = None
        self._gaze_history.clear()
        self._ear_history.clear()
        self._state = "校准"
        self._clear_selection()
        self._last_blink = float("-inf")  # 上次计数时刻；负无穷让第一次眨眼不受不应期限制
        self._message = "请睁眼看屏幕正中间，正在校准"

    def _clear_selection(self) -> None:
        """清除尚未完成的方向停留和眨眼，保留校准与已完成眨眼的时间。"""
        self._raw_choice = self._stable_choice = self._pending = None
        self._direction_since = self._open_since = self._closed_since = self._confirm_started = None
        self._is_closed = False

    def toggle_invert(self) -> None:
        """按 I 时调用：把左右方向反过来，并更新屏幕提示。"""
        self._invert = not self._invert
        if self._state in ("选择方向", "等待眨眼"):
            self._clear_selection()
            self._state = "选择方向"
        self._message = "左右方向已反转" if self._invert else "左右方向已恢复"

    def update(self, now: float, landmarks) -> GazeBlinkStatus:
        """吃一帧数据，返回本帧状态。landmarks 传 None 表示这帧没检测到人脸。"""
        score = gaze_score(landmarks) if landmarks is not None else None
        if score is None or not math.isfinite(score):
            # 无有效视线时丢弃候选、计时与平滑历史，已采集的校准样本仍可用。
            self._gaze_history.clear()
            self._ear_history.clear()
            if self._state != "校准":
                self._clear_selection()
                self._state = "选择方向"
            self._message = "未检测到有效视线：已暂停，请正对摄像头"
            return self._status(score=None, ear=None,
                                calibration_progress=None, stability_progress=None)

        self._ear_history.append(average_ear(landmarks))
        current_ear = sum(self._ear_history) / len(self._ear_history)
        # 闭眼期间的虹膜位置不用于切换方向。
        if self._reopen_line is None or current_ear >= self._reopen_line:
            self._gaze_history.append(score)
        score = sum(self._gaze_history) / len(self._gaze_history) if self._gaze_history else None

        # 校准结束的当帧仍显示满条，方向进度则按更新后的计时计算。
        calibration_progress = stability_progress = None
        if self._state == "校准":
            calibration_progress = min((now - self._calibration_started) / self._calibration_seconds, 1.0)

        # ---- 按状态分派 ----
        # 【状态一：校准】攒够 3 秒且样本足够 → 算出三个"标尺"，转入选择方向
        if self._state == "校准" and score is not None:
            self._update_calibration(now, score, current_ear)
        # 【状态二、三：选择方向 / 等待眨眼】视线偏移决定候选方向，顺便跑眨眼状态机
        elif self._state in ("选择方向", "等待眨眼") and self._center is not None:
            self._update_selection(now, score, current_ear)
        # 【状态四：确认成功】停 1.6 秒让人看清结果，然后自动回到"选择方向"
        elif self._state == "确认成功" and self._confirm_started is not None and now - self._confirm_started >= 1.6:
            self._clear_selection()
            self._state = "选择方向"
            self._message = "请继续选择下一项方向"
        if self._state == "选择方向" and self._direction_since is not None:
            stability_progress = min((now - self._direction_since) / self._select_stable_seconds, 1.0)
        return self._status(score=score, ear=current_ear,
                            calibration_progress=calibration_progress,
                            stability_progress=stability_progress)

    def _update_calibration(self, now: float, score: float, current_ear: float) -> None:
        """校准阶段：攒样本，够 3 秒且样本足够后算出三个标尺。"""
        self._gaze_values.append(score)
        self._ear_values.append(current_ear)
        elapsed = now - self._calibration_started
        self._message = f"校准中：请看正中间 {max(0, self._calibration_seconds - elapsed):.1f} 秒"
        if elapsed < self._calibration_seconds or len(self._gaze_values) < self._calibration_min_samples:
            return
        # _center = 正视时的虹膜位置；base = 睁眼时的开合值
        self._center = sum(self._gaze_values) / len(self._gaze_values)
        base = sum(self._ear_values) / len(self._ear_values)
        self._close_line, self._reopen_line = base * self._close_ratio, base * self._reopen_ratio
        self._state, self._message = "选择方向", "校准完成：看左转、前进或右转，稳定后等待眨眼"

    def _update_selection(self, now: float, score: float | None, current_ear: float) -> None:
        """选择方向 / 等待眨眼：先看视线选了哪个方向，再跑眨眼状态机。"""
        if current_ear >= self._reopen_line and score is not None:
            self._update_direction(now, score)
        elif self._state == "选择方向":
            self._direction_since = self._open_since = None
        if self._state != "等待眨眼":
            return

        # 眨眼状态机：仅在“等待眨眼”时才把一次眨眼当确认。
        # stable_open 三个条件：有睁眼起点、睁眼已满 0.1 秒、离上次计数已满 0.3 秒
        stable_open = (
            self._open_since is not None
            and now - self._open_since >= self._min_open_seconds
            and now - self._last_blink >= self._refractory_seconds
        )
        blink_confirmed = False
        if self._is_closed:
            # 本来闭着 → 现在睁开了：量一下这次闭了多久
            if current_ear >= self._reopen_line:
                duration = now - self._closed_since
                self._is_closed, self._closed_since, self._open_since = False, None, now
                # 闭眼时长落在自然眨眼窗口内 → 记一次"可用的眨眼"
                if self._min_closed_seconds <= duration <= self._max_closed_seconds:
                    self._last_blink, blink_confirmed = now, True
            # 否则持续闭眼，等待睁开。
        elif current_ear >= self._reopen_line:
            # 睁着眼：记下"开始睁眼"的时刻（只在还没有的时候记一次）
            if self._open_since is None:
                self._open_since = now
        elif current_ear < self._close_line and stable_open:
            # 掉到闭眼线以下，且刚才确实稳定睁着 → 进入闭眼候选
            self._is_closed, self._closed_since, self._open_since = True, now, None
            self._gaze_history.clear()  # 重新睁眼时用新的视线核对候选
        else:
            # 落在两条判定线之间的灰色地带 → 睁眼计时作废
            self._open_since = None

        # 【状态三 → 四】只有"等待眨眼"期间的眨眼才被当作确认
        if blink_confirmed:
            self._state, self._confirm_started = "确认成功", now
            # 是否真的发往硬件看右上角链路状态（模拟/串口），状态机保持纯逻辑
            self._message = f"已确认“{self._pending}”"

    def _update_direction(self, now: float, score: float) -> None:
        """用睁眼时的方向推进停留计时，或取消已离开的候选。"""
        offset = score - self._center
        if self._invert:
            offset = -offset
        new_choice = "前进"
        if offset < -self._side_threshold:
            new_choice = "左转"
        elif offset > self._side_threshold:
            new_choice = "右转"

        if self._state == "等待眨眼":
            if new_choice == self._pending:
                return
            self._clear_selection()
            self._state = "选择方向"
            self._message = "已取消原方向，请稳定注视要选择的方向"

        if self._open_since is None:
            self._open_since = now
        if self._direction_since is None or new_choice != self._raw_choice:
            self._raw_choice, self._direction_since = new_choice, now
        elif now - self._direction_since >= self._select_stable_seconds:
            self._stable_choice, self._pending, self._state = new_choice, new_choice, "等待眨眼"
            self._message = f"已选择“{self._pending}”，请自然眨眼确认"

    def _status(self, score: float | None, ear: float | None,
                calibration_progress: float | None, stability_progress: float | None) -> GazeBlinkStatus:
        """把当前内部状态打包成 GazeBlinkStatus（界面唯一能读到的东西）。

        两个进度由 update() 按"本帧进入时的状态"算好传进来（详见那里的注释）。
        """
        # 高亮哪张卡片：等待眨眼/确认成功时高亮 pending，其余时候高亮已稳定的候选
        active = self._pending if self._state in ("等待眨眼", "确认成功") else self._stable_choice
        return GazeBlinkStatus(
            state=self._state,
            message=self._message,
            score=score,
            ear=ear,
            active=active,
            calibration_progress=calibration_progress,
            stability_progress=stability_progress,
            raw_direction=self._raw_choice,
        )
