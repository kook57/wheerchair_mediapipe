"""预览入口共用的窗口检查、按键去抖和中文状态绘制。"""

from os import environ
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


KEY_DEBOUNCE_SECONDS = 0.25
_font_dir = Path(environ.get("WINDIR", r"C:\Windows")) / "Fonts"
FONT_CANDIDATES = tuple(_font_dir / name for name in ("msyh.ttc", "simhei.ttf", "arial.ttf"))
_font_cache: dict[tuple[Path, int], ImageFont.FreeTypeFont] = {}


def window_is_alive(window_name: str) -> bool:
    """查询窗口是否仍可见，用户关闭窗口后返回 False。"""
    try:
        return cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) >= 1
    except cv2.error:
        return False


def pressed_key(
    now: float, key_available_at: float, delay_ms: int = 1, *,
    debounce_seconds: float = KEY_DEBOUNCE_SECONDS, immediate_keys: str = "",
) -> tuple[str | None, float]:
    """刷新窗口并取一个按键。立即响应键可以跳过去抖等待。"""
    raw_key = cv2.waitKey(delay_ms)
    if raw_key == -1:
        return None, key_available_at
    key = chr(raw_key & 0xFF).lower()
    if key not in immediate_keys and now < key_available_at:
        return None, key_available_at
    return key, now + debounce_seconds


def chinese_font(size: int):
    """按候选顺序加载字体，并在预览窗口之间共用缓存。"""
    for path in FONT_CANDIDATES:
        if not path.exists():
            continue
        key = (path, size)
        if key not in _font_cache:
            _font_cache[key] = ImageFont.truetype(str(path), size)
        return _font_cache[key]
    raise FileNotFoundError("找不到可用的中文字体，请检查 FONT_CANDIDATES：" + "、".join(map(str, FONT_CANDIDATES)))


def draw_chinese_status(frame, lines):
    """绘制四行状态文字并返回新的 BGR 图像。"""
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    font_large = chinese_font(29)
    font_small = chinese_font(20)
    draw.text((14, 12), lines[0], font=font_small, fill=(0, 255, 0))
    draw.text((14, 39), lines[1], font=font_large, fill=(255, 255, 0))
    draw.text((14, 76), lines[2], font=font_small, fill=(255, 255, 255))
    draw.text((14, 103), lines[3], font=font_small, fill=(255, 210, 80))
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
