"""Read WeChat's visible, dashed-underlined IME composition with local OCR."""

import asyncio
import ctypes as c
from ctypes import wintypes as w
from functools import lru_cache
from itertools import groupby
import re
from unicodedata import normalize

from PIL import Image, ImageDraw, ImageOps, ImageStat
import winrt.windows.foundation.collections  # Required to access OCR result collections.
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

from composition import PINYIN_TAIL, PinyinPreview
import windows


class BitmapHeader(c.Structure):
    _fields_ = [
        ("size", w.DWORD), ("width", w.LONG), ("height", w.LONG),
        ("planes", w.WORD), ("bits_per_pixel", w.WORD), ("compression", w.DWORD),
        ("image_size", w.DWORD), ("x_pixels_per_meter", w.LONG), ("y_pixels_per_meter", w.LONG),
        ("colors_used", w.DWORD), ("colors_important", w.DWORD),
    ]


gdi = c.WinDLL("gdi32", use_last_error=True)
get_dc = windows.bind(windows.user, "GetDC", w.HDC, w.HWND)
release_dc = windows.bind(windows.user, "ReleaseDC", c.c_int, w.HWND, w.HDC)
create_dc = windows.bind(gdi, "CreateCompatibleDC", w.HDC, w.HDC)
create_dib = windows.bind(gdi, "CreateDIBSection", w.HBITMAP, w.HDC, c.c_void_p, w.UINT, c.POINTER(c.c_void_p), w.HANDLE, w.DWORD)
select_object = windows.bind(gdi, "SelectObject", w.HGDIOBJ, w.HDC, w.HGDIOBJ)
bit_blt = windows.bind(gdi, "BitBlt", w.BOOL, w.HDC, c.c_int, c.c_int, c.c_int, c.c_int, w.HDC, c.c_int, c.c_int, w.DWORD)
delete_object = windows.bind(gdi, "DeleteObject", w.BOOL, w.HGDIOBJ)
delete_dc = windows.bind(gdi, "DeleteDC", w.BOOL, w.HDC)


def capture_strip(left, top, width, height):
    """Copy just the rectangle around the composition into memory."""
    desktop = get_dc(None)
    if not desktop:
        return None
    memory = bitmap = previous = None
    try:
        memory = create_dc(desktop)
        header = BitmapHeader(c.sizeof(BitmapHeader), width, -height, 1, 32)
        pixels = c.c_void_p()
        bitmap = create_dib(desktop, c.byref(header), 0, c.byref(pixels), None, 0)
        if not memory or not bitmap:
            return None
        previous = select_object(memory, bitmap)
        if not previous or not bit_blt(memory, 0, 0, width, height, desktop, left, top, 0x00CC0020):
            return None
        return Image.frombytes("RGB", (width, height), c.string_at(pixels, width * height * 4), "raw", "BGRX")
    finally:
        if previous:
            select_object(memory, previous)
        if bitmap:
            delete_object(bitmap)
        if memory:
            delete_dc(memory)
        release_dc(None, desktop)


@lru_cache(maxsize=8)
def dash_pattern(dpi):
    scale = dpi / 96
    dash_min, dash_max = round(3 * scale), round(5 * scale)
    gap_min, gap_max = max(1, round(scale)), round(3 * scale)
    return re.compile(
        rb"(?<!\x01)\x01{%d,%d}(?:\x00{%d,%d}\x01{1,%d})+(?!\x01)"
        % (dash_min, dash_max, gap_min, gap_max, dash_max)
    )


DARK_PIXELS = bytes(int(value < 100) for value in range(256))


def remove_underline(gray, left, right, top, bottom, text_height, scale):
    image_top = max(0, top - text_height)
    strokes = []
    if bottom + 1 < gray.height:
        for x in range(left, right):
            above = gray.getpixel((x, top - 1))
            below = gray.getpixel((x, bottom + 1))
            if max(above, below) < 145:
                strokes.append((x, max(above, below)))
    if not strokes:
        return gray.crop((left, image_top, right, top))

    margin = min(left, round(3 * scale))
    image_bottom = min(gray.height, bottom + round(3 * scale) + 1)
    glyphs = gray.crop((left - margin, image_top, right, image_bottom))
    draw = ImageDraw.Draw(glyphs)
    first = top - image_top
    last = bottom - image_top
    if margin:
        draw.rectangle((0, 0, margin - 1, first - 1), fill=255)
    draw.rectangle((0, first, glyphs.width - 1, last), fill=255)
    for x, shade in strokes:
        # Preserve the stem of a letter that crosses the underline.
        draw.line((x - left + margin, first, x - left + margin, last), fill=shade)
    return glyphs


def underlined_text(image, anchor, dpi):
    """Identify the active dashed underline and return only the glyphs above it."""
    scale = dpi / 96
    gray = ImageOps.grayscale(image)
    sample = gray.crop((max(0, anchor - 12), 0, min(gray.width, anchor + 12), gray.height))
    if ImageStat.Stat(sample).median[0] < 128:
        gray = ImageOps.invert(gray)
    pixels = gray.tobytes().translate(DARK_PIXELS)
    width = gray.width
    tolerance = round(5 * scale)
    text_height = round(18 * scale)
    for y in range(gray.height - 1, text_height, -1):
        row = pixels[y * width:(y + 1) * width]
        for match in dash_pattern(dpi).finditer(row):
            left, right = match.span()
            if left - tolerance <= anchor <= right + tolerance:
                top = y
                dashes = match.group(0)
                minimum_overlap = sum(dashes) * 0.8
                while top > 0:
                    previous_row = pixels[(top - 1) * width + left:(top - 1) * width + right]
                    if sum(a and b for a, b in zip(previous_row, dashes)) < minimum_overlap:
                        break
                    top -= 1
                right = min(width, max(right, anchor))
                return remove_underline(gray, left, right, top, y, text_height, scale)
    return None


def split_syllables(glyphs):
    """Separate visible apostrophes so the recognizer cannot merge syllables."""
    ink = glyphs.point(lambda value: 255 if value < 145 else 0)
    columns, _ = ink.getprojection()
    parts = []
    previous = 0
    for has_ink, group in groupby(range(ink.width), key=columns.__getitem__):
        indices = list(group)
        left, right = indices[0], indices[-1] + 1
        if not has_ink or right - left > glyphs.height * 0.22 or left < 3 or right > ink.width - 3:
            continue
        box = ink.crop((left, 0, right, ink.height)).getbbox()
        if box and box[3] <= glyphs.height * 0.66 and box[3] - box[1] <= glyphs.height * 0.29:
            parts.append(glyphs.crop((previous, 0, left, glyphs.height)))
            previous = right
    parts.append(glyphs.crop((previous, 0, glyphs.width, glyphs.height)))
    return parts


def normalize_reading(reading, syllable_count):
    compact = "".join(reading.split())
    if compact.count("'") == syllable_count - 1:
        return compact
    words = re.split(r"[\s']+", reading.strip())
    return "'".join(words) if len(words) == syllable_count else ""


class WeChatPreviewReader:
    def __init__(self):
        try:
            self.engine = OcrEngine.try_create_from_language(Language("en-US"))
            if self.engine is None:
                self.engine = OcrEngine.try_create_from_user_profile_languages()
        except OSError:
            self.engine = None
        self.last_image = None
        self.last_preview = None

    def clear(self):
        self.last_image = self.last_preview = None

    def read(self, foreground, candidate):
        if self.engine is None:
            return None, None
        bounds = w.RECT()
        if not windows.get_window_rect(foreground, c.byref(bounds)):
            return None, None
        dpi = windows.get_dpi(foreground) or 96
        scale = dpi / 96
        radius = round(320 * scale)
        left = max(bounds.left, candidate.left - radius)
        right = min(bounds.right, candidate.left + radius)
        top = max(bounds.top, candidate.top - round(34 * scale))
        bottom = min(bounds.bottom, candidate.top - round(4 * scale))
        if right <= left or bottom - top < round(18 * scale) or not left <= candidate.left < right:
            return None, None
        strip = capture_strip(left, top, right - left, bottom - top)
        glyphs = underlined_text(strip, candidate.left - left, dpi) if strip is not None else None
        if glyphs is None:
            self.clear()
            return None, None

        frame = (foreground, glyphs.size, glyphs.tobytes())
        if frame != self.last_image:
            self.last_image = frame
            try:
                text = asyncio.run(self.read_pinyin(glyphs))
                self.last_preview = PinyinPreview(text, None) if text else None
            except OSError:
                self.last_preview = None
        return self.last_preview, top

    async def read_pinyin(self, glyphs):
        parts = split_syllables(glyphs)
        readings = await self.read_both_scales(ImageOps.expand(glyphs, border=6, fill=255))
        first, second = (normalize_reading(reading, len(parts)) for reading in readings)
        if first == second and PINYIN_TAIL.fullmatch(first):
            return first
        if len(parts) > 1:
            gap = glyphs.height
            spaced = Image.new("L", (glyphs.width + gap * (len(parts) - 1) + 12, glyphs.height + 12), 255)
            x = 6
            for part in parts:
                spaced.paste(part, (x, 6))
                x += part.width + gap
            first, second = (reading.split() for reading in await self.read_both_scales(spaced))
            if first == second and len(first) == len(parts) and all(re.fullmatch(r"[a-zü]+", syllable) for syllable in first):
                if all(len(syllable) == 1 or syllable in ("ch", "sh", "zh", "ng") or re.search(r"[aeiouü]", syllable)
                       for syllable in first[:-1]):
                    return "'".join(first)
        return ""

    async def read_both_scales(self, image):
        readings = []
        for requested in (2, 4):
            scale = min(requested, OcrEngine.max_image_dimension / max(image.size))
            enlarged = image.resize(
                (round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS
            ).convert("RGB")
            with DataWriter() as writer:
                writer.write_bytes(enlarged.tobytes("raw", "BGRX"))
                buffer = writer.detach_buffer()
            with SoftwareBitmap(BitmapPixelFormat.BGRA8, enlarged.width, enlarged.height, BitmapAlphaMode.IGNORE) as bitmap:
                bitmap.copy_from_buffer(buffer)
                result = await self.engine.recognize_async(bitmap)
            readings.append(normalize("NFKC", result.text).lower().replace("’", "'"))
        return readings
