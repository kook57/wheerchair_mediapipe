"""两种视觉演示将眼动确认交给 WheelchairControl，再由 WheelchairLink 发送指令。"""

from hardware.serial_link import LinkStatus, WheelchairLink

FACE_LOST_STOP_SECONDS = 2.0


class WheelchairControl:
    """在方向确认时下发运动意图，并在持续丢失人脸时停车。"""

    def __init__(self, link: WheelchairLink):
        self._link = link
        self._previous_state: str | None = None
        self._face_lost_since: float | None = None

    def update(self, now: float, state: str, direction: str | None, *, face_present: bool) -> LinkStatus:
        """先处理停车和固件回包，再接受这一帧的新确认。"""
        if face_present:
            self._face_lost_since = None
        else:
            if self._face_lost_since is None:
                self._face_lost_since = now
            if now - self._face_lost_since >= FACE_LOST_STOP_SECONDS:
                # 先停车，避免同一帧的心跳重发之前的运动指令。
                self._link.set_intent("停", now=now)

        link_status = self._link.update(now)
        if face_present and self._previous_state == "等待眨眼" and state == "确认成功" and direction:
            self._link.set_intent(direction, now=now, retrigger=True)
        self._previous_state = state
        return link_status
