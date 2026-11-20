"""将归一化的人脸、眼睛和手部坐标绘制到预览帧。

各绘制入口通过 point() 换算像素坐标；draw_hands() 逐只调用 draw_hand()。
"""

import cv2
import numpy as np

from vision.eye_geometry import LEFT_EYE, LEFT_IRIS, RIGHT_EYE, RIGHT_IRIS

EYE_LOOPS = (LEFT_EYE, RIGHT_EYE)


def point(lm, width: int, height: int) -> tuple[int, int]:
    """把一个归一化关键点（0~1）换成屏幕像素坐标。

    调用关系：被 draw_face() 和 draw_hand() 调用；内部什么都不调用。
    """
    return int(lm.x * width), int(lm.y * height)


def draw_face(frame, face_landmarks) -> None:
    """绘制全部脸部点，并突出眼睛轮廓。

    调用关系：被 draw_results() 对每张脸调用一次；内部调用 point()。
    注意它直接在传入的 frame 上画（不返回新图），因为这里是"补充绘制"而不是产出一张新画面。
    """
    h, w = frame.shape[:2]
    for lm in face_landmarks:
        cv2.circle(frame, point(lm, w, h), 1, (0, 255, 0), -1)

    for loop in EYE_LOOPS:
        pts = [point(face_landmarks[i], w, h) for i in loop]
        cv2.polylines(frame, [np.array(pts, dtype=np.int32)], True, (0, 255, 255), 1)


def draw_hand(frame, landmarks, label: str) -> None:
    """绘制 21 个手部点与基础骨架连接。

    调用关系：由 draw_hands() 对每只手调用一次；内部调用 point()。
    label 是 LEFT / RIGHT / HAND（拿不到左右时用 HAND），画在手腕上方。
    """
    h, w = frame.shape[:2]
    links = [
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (5, 9), (9, 10), (10, 11), (11, 12),
        (9, 13), (13, 14), (14, 15), (15, 16),
        (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
    ]
    pts = [point(lm, w, h) for lm in landmarks]
    for a, b in links:
        cv2.line(frame, pts[a], pts[b], (255, 100, 0), 2)
    for p in pts:
        cv2.circle(frame, p, 4, (0, 0, 255), -1)
    cv2.putText(frame, label, (pts[0][0] + 8, pts[0][1] - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 100, 0), 2)


def draw_hands(frame, hand_result) -> None:
    """为关键点预览和手眼集成预览绘制手部骨架与左右手标签。"""
    for index, landmarks in enumerate(hand_result.hand_landmarks):
        label = "HAND"
        if index < len(hand_result.handedness) and hand_result.handedness[index]:
            label = hand_result.handedness[index][0].category_name.upper()
        draw_hand(frame, landmarks, label)


def draw_points(frame, landmarks, indices, *, radius: int = 3) -> None:
    """在帧上用黄色圆点标出指定的关键点。"""
    height, width = frame.shape[:2]
    for index in indices:
        cv2.circle(frame, point(landmarks[index], width, height), radius, (0, 255, 255), -1)


def draw_eye_points(frame, landmarks) -> None:
    """高亮双眼轮廓点。"""
    draw_points(frame, landmarks, LEFT_EYE + RIGHT_EYE)


def draw_iris_points(frame, landmarks) -> None:
    """高亮双眼虹膜点。"""
    draw_points(frame, landmarks, LEFT_IRIS + RIGHT_IRIS)
