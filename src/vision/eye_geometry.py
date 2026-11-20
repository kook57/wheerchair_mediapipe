"""把 MediaPipe 的眼周关键点转换成判定层使用的标量。

average_ear() → eye_aspect_ratio() → distance()；gaze_score() 计算归一化虹膜横向位置。
"""

import math

# 眼轮廓顺序为外眼角、上外、上内、内眼角、下内、下外。
LEFT_EYE = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]
LEFT_IRIS = [468, 469, 470, 471, 472]
RIGHT_IRIS = [473, 474, 475, 476, 477]
LEFT_CORNERS = (33, 133)
RIGHT_CORNERS = (362, 263)


def distance(a, b) -> float:
    """返回两个关键点在图像平面的距离。"""
    return math.hypot(a.x - b.x, a.y - b.y)


def eye_aspect_ratio(landmarks, indices) -> float:
    """返回单眼开合比，眼角几乎重合时返回 0。"""
    p0, p1, p2, p3, p4, p5 = [landmarks[i] for i in indices]
    horizontal = distance(p0, p3)
    if horizontal < 1e-6:
        return 0.0
    return (distance(p1, p5) + distance(p2, p4)) / (2.0 * horizontal)


def average_ear(landmarks) -> float:
    """对双眼开合比取平均，以减小轻微侧头的影响。"""
    return (eye_aspect_ratio(landmarks, LEFT_EYE) + eye_aspect_ratio(landmarks, RIGHT_EYE)) / 2.0


def gaze_score(landmarks, *, include_minimum: bool = False) -> float | None:
    """返回虹膜在可用眼睛中的平均横向位置，眼角跨度不足时返回 None。"""
    ratios = []
    for iris, corners in ((LEFT_IRIS, LEFT_CORNERS), (RIGHT_IRIS, RIGHT_CORNERS)):
        a, b = landmarks[corners[0]].x, landmarks[corners[1]].x
        span = abs(a - b)
        if span > 1e-5 or (include_minimum and span == 1e-5):
            iris_x = sum(landmarks[i].x for i in iris) / len(iris)
            ratios.append((iris_x - min(a, b)) / span)
    return sum(ratios) / len(ratios) if ratios else None
