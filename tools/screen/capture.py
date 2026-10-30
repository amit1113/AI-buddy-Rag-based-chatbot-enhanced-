"""Screenshot of one window (or the whole screen), shrunk and compressed for the model."""
import io
from dataclasses import dataclass

from PIL import Image

from core import config

MIN_WINDOW_PIXELS = 50


@dataclass
class Capture:
    jpeg: bytes
    size: tuple   # (width, height) of the image actually sent
    scope: str    # "window" or "screen"


def clamp_rect(rect, bounds):
    """Keep a window rectangle inside the visible desktop. None if nothing sensible is left."""
    left, top, right, bottom = rect
    b_left, b_top, b_right, b_bottom = bounds
    left, top = max(left, b_left), max(top, b_top)
    right, bottom = min(right, b_right), min(bottom, b_bottom)
    if right - left < MIN_WINDOW_PIXELS or bottom - top < MIN_WINDOW_PIXELS:
        return None
    return (left, top, right, bottom)


def to_jpeg(image, max_dimension, quality):
    """Shrink so the longest side is at most max_dimension, then encode as JPEG."""
    image = image.convert("RGB")
    scale = max_dimension / max(image.size)
    if scale < 1:
        resample = getattr(Image, "Resampling", Image).LANCZOS
        image = image.resize((round(image.width * scale), round(image.height * scale)), resample)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue(), image.size


def grab(region=None):
    """Grab a screen region (physical pixels). Falls back to the primary screen.
    Returns (PIL image, True if a window region was used)."""
    import mss

    with mss.mss() as sct:
        virtual = sct.monitors[0]  # all monitors combined
        bounds = (
            virtual["left"], virtual["top"],
            virtual["left"] + virtual["width"], virtual["top"] + virtual["height"],
        )
        box = clamp_rect(region, bounds) if region else None
        if box is None:
            primary = sct.monitors[1]
            area = {k: primary[k] for k in ("left", "top", "width", "height")}
        else:
            area = {"left": box[0], "top": box[1], "width": box[2] - box[0], "height": box[3] - box[1]}
        shot = sct.grab(area)
        return Image.frombytes("RGB", shot.size, shot.rgb), box is not None


def capture_active_window(info):
    """Capture the window described by info (or the whole screen if info is None)."""
    region = info.rect if info else None
    image, is_window = grab(region)
    jpeg, size = to_jpeg(image, config.SCREEN_MAX_DIMENSION, config.SCREEN_JPEG_QUALITY)
    if config.SAVE_LAST_CAPTURE:
        try:
            config.LAST_CAPTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
            config.LAST_CAPTURE_PATH.write_bytes(jpeg)
        except OSError:
            pass
    return Capture(jpeg=jpeg, size=size, scope="window" if is_window else "screen")
