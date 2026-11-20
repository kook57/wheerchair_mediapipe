"""眨眼状态机。BlinkDetector.update() 接收时间和开合比，返回 BlinkStatus。"""

from collections import deque
from dataclasses import dataclass


CALIBRATION_SECONDS = 3.0     # 校准时长：这段时间内请保持睁眼
CALIBRATION_MIN_SAMPLES = 10  # 样本下限：帧率过低时样本太少，基线不可靠
CLOSE_RATIO = 0.78          # 放宽：低于睁眼基线的 78% 即进入闭眼候选
REOPEN_RATIO = 0.88         # 高于睁眼基线的 88% 即认为重新睁眼
SMOOTHING_FRAMES = 3        # 轻度平滑：保留自然眨眼的快速变化
MIN_CLOSED_SECONDS = 0.04   # 过滤极短噪声
MAX_CLOSED_SECONDS = 0.80   # 允许较慢/较完整的自然眨眼
MIN_OPEN_SECONDS = 0.10     # 再次计数前只需短暂稳定睁眼
REFRACTORY_SECONDS = 0.30   # 防止一次眨眼多计，但不妨碍连续眨眼
MESSAGE_INITIAL = "请睁眼正视摄像头，正在校准"


@dataclass(frozen=True)
class BlinkStatus:
    """一帧的判定结果快照，供界面显示。

    调用关系：由 BlinkDetector._status() 产出 → 被 main() 接住 → 交给 show_status() 画出来。
    它只是"数据袋子"，自身不含任何逻辑。
    """

    blink_count: int
    state: str
    message: str
    ear: float | None
    baseline: float | None
    close_threshold: float | None
    is_calibrating: bool


class BlinkDetector:
    """眨眼校准 + 计数状态机。原来散在 main() 里的状态，现在全在这个对象里。

    调用关系：main() 在启动时 new 一个；之后每帧调 update()；
    按 C 时调 reset() 重新校准。update() 内部按阶段分派：
      baseline 还是 None  → _update_calibration()
      baseline 已有值      → _update_counting()
      两种情况都由 _status(ear) 打包成 BlinkStatus 返回。

    用法：`BlinkDetector(time.perf_counter())`，之后每帧调用
    `update(now, 原始开合值)`；没检测到人脸时传 None。平滑、校准、阈值比较
    都在内部完成，外面只读返回的 BlinkStatus。
    """

    def __init__(
        self,
        now: float,
        *,
        calibration_seconds: float = CALIBRATION_SECONDS,
        calibration_min_samples: int = CALIBRATION_MIN_SAMPLES,
        close_ratio: float = CLOSE_RATIO,
        reopen_ratio: float = REOPEN_RATIO,
        smoothing_frames: int = SMOOTHING_FRAMES,
        min_closed_seconds: float = MIN_CLOSED_SECONDS,
        max_closed_seconds: float = MAX_CLOSED_SECONDS,
        min_open_seconds: float = MIN_OPEN_SECONDS,
        refractory_seconds: float = REFRACTORY_SECONDS,
    ) -> None:
        self._calibration_seconds = calibration_seconds
        self._calibration_min_samples = calibration_min_samples
        self._close_ratio = close_ratio
        self._reopen_ratio = reopen_ratio
        self._min_closed_seconds = min_closed_seconds
        self._max_closed_seconds = max_closed_seconds
        self._min_open_seconds = min_open_seconds
        self._refractory_seconds = refractory_seconds
        self._history: deque[float] = deque(maxlen=smoothing_frames)  # 最近几帧原始开合值，用于平滑
        self.reset(now)

    def reset(self, now: float, message: str = MESSAGE_INITIAL) -> None:
        """这里在进行初始化（还没有开始收集用户是否睁眼）。

        调用关系：被 __init__（建对象时）和 main() 的 C 键分支调用，
        两条路走的是同一份代码，避免两处手抄不一致。
        """
        self._calibration_started_at = now  # 校准阶段的起始时间
        self._calibration_values: list[float] = []  # 校准期间每帧的开合值
        self._baseline: float | None = None  # 睁眼基线，校准完成前是 None
        self._close_threshold: float | None = None  # 闭眼判定线
        self._reopen_threshold: float | None = None  # 重新睁眼判定线
        self._blink_count = 0  # 眨眼计数
        self._is_closed = False  # 是否处于“闭眼候选”状态
        self._closed_since: float | None = None  # 闭眼开始的时间戳
        self._open_since: float | None = None  # 稳定睁眼开始的时间戳
        self._last_blink_at = float("-inf")  # 上次计数时间；负无穷让第一次眨眼不受不应期限制
        self._history.clear()
        self._state = "正在校准"
        self._message = message

    def update(self, now: float, ear_raw: float | None) -> BlinkStatus:
        """吃一帧数据，返回本帧状态。ear_raw 为 None 表示这帧没检测到人脸。

        调用关系：被 main() 每帧调用一次；内部先做 3 帧平滑，再按阶段分派——
        校准没完成 → _update_calibration()；已完成 → _update_counting()；
        两个分支的最后都经 _status() 打包成 BlinkStatus 返回。
        """
        if ear_raw is None:
            # 人脸消失期间的时序不可信，未完成的状态全部清空，人脸回来重新开始。
            self._history.clear()
            self._is_closed = False
            self._closed_since = None
            self._open_since = None
            self._state = "未检测到人脸"
            self._message = "未检测到人脸：请正对摄像头"
            return self._status(ear=None)

        self._history.append(ear_raw)
        ear = sum(self._history) / len(self._history)

        if self._baseline is None:
            self._update_calibration(now, ear)
        else:
            self._update_counting(now, ear)
        return self._status(ear=ear)

    def _update_calibration(self, now: float, ear: float) -> None:
        """校准阶段：攒够时间和样本后，算出睁眼基线与两条判定线。

        调用关系：只被 update() 调用，且只在 baseline 还是 None 时进入。
        写完之后 baseline 有了值，下一帧起 update() 就会改走 _update_counting()。
        """
        self._calibration_values.append(ear)
        elapsed = now - self._calibration_started_at
        remaining = max(0.0, self._calibration_seconds - elapsed)
        self._message = f"校准中：请保持睁眼 {remaining:.1f}s"
        if elapsed < self._calibration_seconds or len(self._calibration_values) < self._calibration_min_samples:
            return

        # 用中间 80% 的平均值，降低偶发眨眼影响。
        values = sorted(self._calibration_values)
        trim = max(1, len(values) // 10)
        kept = values[trim:-trim] or values
        self._baseline = sum(kept) / len(kept)
        self._close_threshold = self._baseline * self._close_ratio
        self._reopen_threshold = self._baseline * self._reopen_ratio
        self._message = "校准完成：现在请自然眨眼"
        self._state = "已准备好"

    def _update_counting(self, now: float, ear: float) -> None:
        """收集数据完成后的计数状态机。

        调用关系：只被 update() 调用，且只在 baseline 已有值时进入。
        眨眼计数 +1 就发生在这里（下面那段 min ≤ duration ≤ max 的判断里）。
        """
        # 必须先记录“闭眼前是否已稳定睁眼”，再处理当前闭眼帧。
        # 否则一闭眼就会先清空 open_since，导致永远无法进入计数。
        was_stably_open = (
            self._open_since is not None
            and now - self._open_since >= self._min_open_seconds
            and now - self._last_blink_at >= self._refractory_seconds
        )

        if self._is_closed:
            if ear >= self._reopen_threshold:
                duration = now - self._closed_since if self._closed_since is not None else 0.0
                self._is_closed = False
                self._closed_since = None
                self._open_since = now
                if self._min_closed_seconds <= duration <= self._max_closed_seconds:
                    self._blink_count += 1
                    self._last_blink_at = now
                    self._message = f"检测到一次眨眼（闭眼 {duration:.2f}s）"
                    self._state = "已确认"
                else:
                    self._message = f"忽略非自然眨眼（{duration:.2f}s）"
                    self._state = "已准备好"
            else:
                self._state = "闭眼候选中"
        elif ear >= self._reopen_threshold:
            if self._open_since is None:
                self._open_since = now
            self._state = "已准备好" if was_stably_open else "等待稳定睁眼"
        elif ear < self._close_threshold and was_stably_open:
            self._is_closed = True
            self._closed_since = now
            self._open_since = None
            self._state = "闭眼候选中"
        else:
            # 落在两条判定线之间的灰色地带：保持现状，睁眼计时作废。
            self._open_since = None
            self._state = "等待稳定睁眼"

    def _status(self, ear: float | None) -> BlinkStatus:
        """把当前内部状态打包成 BlinkStatus（界面唯一能读到的东西）。

        调用关系：被 update() 调用；产物交给 main() → show_status() 显示。
        """
        return BlinkStatus(
            blink_count=self._blink_count,
            state=self._state,
            message=self._message,
            ear=ear,
            baseline=self._baseline,
            close_threshold=self._close_threshold,
            is_calibrating=self._baseline is None,
        )
