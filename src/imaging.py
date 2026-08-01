"""بناء صورة المنشور: صورة الخبر الأصلية + طبقة تعتيم + عنوان عربي + إطار العلامة."""
from __future__ import annotations

import io
import logging
from pathlib import Path

import arabic_reshaper
import requests
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import resolve
from .sources import HEADERS

log = logging.getLogger(__name__)

# خطوط بديلة إذا لم تُنزّل خطوط Cairo
FALLBACK_FONTS = [
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]


# ──────────────────────────── أدوات النص العربي ────────────────────────────


def shape(text: str) -> str:
    """يوصل الحروف العربية ويطبّق اتجاه الكتابة من اليمين لليسار."""
    return get_display(arabic_reshaper.reshape(text))


def load_font(path: str | None, size: int) -> ImageFont.FreeTypeFont:
    candidates = [str(resolve(path))] if path else []
    candidates += FALLBACK_FONTS
    for cand in candidates:
        if Path(cand).exists():
            try:
                return ImageFont.truetype(cand, size)
            except OSError:
                continue
    log.warning("لم يُعثر على خط عربي — سيُستخدم الخط الافتراضي (قد لا يعرض العربية)")
    return ImageFont.load_default()


def text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def wrap_arabic(draw, text: str, font, max_width: int) -> list[str]:
    """
    يقسّم النص إلى أسطر بقياس عرض النسخة المُشكّلة.
    مهم: التقسيم يجري على النص المنطقي، والتشكيل يُطبّق عند الرسم فقط.
    """
    words = text.split()
    lines: list[str] = []
    current: list[str] = []

    for word in words:
        trial = current + [word]
        if text_width(draw, shape(" ".join(trial)), font) <= max_width or not current:
            current = trial
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def fit_font(draw, text: str, font_path: str | None, max_width: int,
             max_height: int, max_lines: int, start: int, minimum: int = 30):
    """يصغّر حجم الخط تدريجيًا حتى يستوعب الصندوق النص كاملًا."""
    size = start
    while size > minimum:
        font = load_font(font_path, size)
        lines = wrap_arabic(draw, text, font, max_width)
        line_h = int(size * 1.55)
        if len(lines) <= max_lines and len(lines) * line_h <= max_height:
            return font, lines, line_h
        size -= 3
    font = load_font(font_path, minimum)
    lines = wrap_arabic(draw, text, font, max_width)[:max_lines]
    return font, lines, int(minimum * 1.55)


# ──────────────────────────── الخلفية ────────────────────────────


def download_image(url: str, timeout: int = 20) -> Image.Image | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200 or len(resp.content) < 4096:
            return None
        img = Image.open(io.BytesIO(resp.content))
        img.load()
        if min(img.size) < 200:  # صورة صغيرة جدًا (أيقونة عادةً)
            return None
        return img.convert("RGB")
    except (requests.RequestException, OSError) as exc:
        log.debug("فشل تحميل الصورة %s: %s", url, exc)
        return None


def cover(img: Image.Image, width: int, height: int) -> Image.Image:
    """تكبير/تصغير مع قص من المركز للحفاظ على النسبة (مثل object-fit: cover)."""
    scale = max(width / img.width, height / img.height)
    new = (max(width, int(img.width * scale)), max(height, int(img.height * scale)))
    img = img.resize(new, Image.LANCZOS)
    left = (img.width - width) // 2
    top = int((img.height - height) * 0.35)  # ميل للأعلى: الوجوه غالبًا في الثلث الأعلى
    return img.crop((left, top, left + width, top + height))


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore


def gradient_background(width: int, height: int, color: str) -> Image.Image:
    """خلفية بديلة عند غياب صورة الخبر."""
    base = hex_rgb(color)
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        t = y / max(height - 1, 1)
        row = tuple(int(c * (0.55 + 0.9 * t)) for c in base)
        for x in range(width):
            px[x, y] = row  # type: ignore
    return img


def darken_bottom(img: Image.Image, strength: float = 0.92) -> Image.Image:
    """تدرّج تعتيم من الأسفل ليصبح النص مقروءًا فوق أي صورة."""
    width, height = img.size
    mask = Image.new("L", (width, height))
    mpx = mask.load()
    for y in range(height):
        t = y / max(height - 1, 1)
        # تعتيم خفيف في الأعلى (للشعار) وقوي في الأسفل (للعنوان)
        alpha = 0.30 + (strength - 0.30) * (t ** 2.1)
        value = int(255 * alpha)
        for x in range(width):
            mpx[x, y] = value  # type: ignore
    overlay = Image.new("RGB", (width, height), (5, 8, 18))
    return Image.composite(overlay, img, mask.point(lambda v: v))


# ──────────────────────────── البناء النهائي ────────────────────────────


def rounded_badge(draw, xy_right: int, y: int, text: str, font,
                  bg: tuple[int, int, int], fg: tuple[int, int, int],
                  pad_x: int = 20, pad_y: int = 10) -> int:
    """يرسم شارة بزوايا دائرية بمحاذاة اليمين، ويعيد الحد الأيسر لها."""
    shaped = shape(text)
    tw = text_width(draw, shaped, font)
    box = draw.textbbox((0, 0), shaped, font=font)
    th = box[3] - box[1]
    w = tw + pad_x * 2
    h = th + pad_y * 2
    x0 = xy_right - w
    draw.rounded_rectangle([x0, y, x0 + w, y + h], radius=h // 2, fill=bg)
    draw.text((x0 + pad_x, y + pad_y - box[1]), shaped, font=font, fill=fg)
    return x0


def build_post_image(
    headline: str,
    category: str,
    urgent: bool,
    image_url: str | None,
    publisher: str,
    cfg,
    out_path: Path,
) -> Path:
    W = int(cfg.path("image.width", 1200))
    H = int(cfg.path("image.height", 630))
    brand_name = cfg.path("brand.name", "")
    handle = cfg.path("brand.handle", "")
    primary = cfg.path("brand.primary_color", "#0F172A")
    accent = hex_rgb(cfg.path("brand.accent_color", "#F4B942"))
    font_bold = cfg.path("image.font_bold")
    font_reg = cfg.path("image.font_regular")

    # 1) الخلفية: صورة الخبر أو تدرّج بديل
    base = download_image(image_url) if image_url else None
    used_original = base is not None
    if base is None:
        if not cfg.path("image.fallback_gradient", True):
            raise RuntimeError("لا توجد صورة للخبر والتدرّج البديل معطّل")
        canvas = gradient_background(W, H, primary)
    else:
        canvas = cover(base, W, H)
        if cfg.path("image.blur_background", True):
            canvas = canvas.filter(ImageFilter.GaussianBlur(radius=1.2))

    canvas = darken_bottom(canvas)
    draw = ImageDraw.Draw(canvas)

    margin = 56
    right = W - margin

    # 2) الشارات في الأعلى (يمين → يسار)
    badge_font = load_font(font_bold, 30)
    cursor = right
    if urgent:
        cursor = rounded_badge(draw, cursor, margin - 8, "عاجل", badge_font,
                               (214, 40, 40), (255, 255, 255)) - 14
    rounded_badge(draw, cursor, margin - 8, category, badge_font, accent, hex_rgb(primary))

    # 3) الشريط السفلي للعلامة
    bar_h = 92
    bar_top = H - bar_h
    strip = Image.new("RGB", (W, bar_h), hex_rgb(primary))
    canvas.paste(strip, (0, bar_top))
    draw.rectangle([0, bar_top, W, bar_top + 5], fill=accent)

    if brand_name:
        bf = load_font(font_bold, 38)
        shaped = shape(brand_name)
        bw = text_width(draw, shaped, bf)
        draw.text((right - bw, bar_top + 26), shaped, font=bf, fill=(255, 255, 255))

    footer_font = load_font(font_reg, 26)
    footer_bits = [b for b in (handle, publisher if used_original else "") if b]
    if footer_bits:
        draw.text((margin, bar_top + 32), shape(" • ".join(footer_bits)),
                  font=footer_font, fill=(190, 198, 215))

    # 4) العنوان: يُرسم فوق الشريط، بمحاذاة اليمين
    box_bottom = bar_top - 40
    box_top = int(H * 0.30)
    max_w = W - margin * 2 - 26
    font, lines, line_h = fit_font(
        draw, headline, font_bold, max_w, box_bottom - box_top,
        max_lines=4, start=62, minimum=32,
    )

    total_h = len(lines) * line_h
    y = box_bottom - total_h

    # خط التمييز العمودي على يمين النص
    draw.rounded_rectangle([right - 8, y + 8, right, y + total_h - 10], radius=4, fill=accent)

    for line in lines:
        shaped = shape(line)
        lw = text_width(draw, shaped, font)
        x = right - 26 - lw
        draw.text((x + 2, y + 3), shaped, font=font, fill=(0, 0, 0))       # ظل خفيف
        draw.text((x, y), shaped, font=font, fill=(255, 255, 255))
        y += line_h

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=88, optimize=True)
    log.info("الصورة جاهزة: %s (أصلية=%s)", out_path.name, used_original)
    return out_path
