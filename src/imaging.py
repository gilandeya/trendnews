"""بناء كارت الخبر: ترويسة العلامة + صورة الخبر + شريط العنوان + تذييل.

التشكيل العربي يتم عبر HarfBuzz/Raqm المدمج في Pillow (direction="rtl")، وهو
يستخدم جداول OpenType داخل الخط نفسه. لا نستخدم arabic-reshaper لأنه يحوّل
النص إلى "Presentation Forms" القديمة، وأغلب الخطوط العربية الحديثة لا تغطيها
كاملة (Tajawal مثلًا يغطي 89 من 141 شكلًا) فتظهر مربعات مكان الحروف الناقصة.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

from .config import resolve
from .sources import HEADERS

log = logging.getLogger(__name__)

HAS_RAQM = features.check("raqm")

FALLBACK_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
]

_font_cache: dict[tuple[str | None, int, str | None], ImageFont.FreeTypeFont] = {}


# ──────────────────────────── النص العربي ────────────────────────────


def load_font(path: str | None, size: int, weight: str | None = None):
    """
    يحمّل خطًا بالحجم المطلوب.

    إن كان الخط متغيرًا (Variable Font) وطُلب وزن، يُضبط الوزن — مثل
    "Black" أو "ExtraBold" أو "Bold". يُتجاهل الوزن بهدوء مع الخطوط الثابتة.
    """
    key = (path, size, weight)
    if key in _font_cache:
        return _font_cache[key]

    for cand in ([str(resolve(path))] if path else []) + FALLBACK_FONTS:
        if not Path(cand).exists():
            continue
        try:
            font = ImageFont.truetype(cand, size)
        except OSError:
            continue
        if weight:
            try:
                font.set_variation_by_name(weight)
            except Exception:  # noqa: BLE001 — خط ثابت أو وزن غير متاح
                pass
        _font_cache[key] = font
        return font

    log.warning("لم يُعثر على خط — سيُستخدم الافتراضي")
    font = ImageFont.load_default()
    _font_cache[key] = font
    return font


def _prepare(text: str) -> str:
    """احتياطي فقط: إن غاب Raqm نعود لـ arabic-reshaper رغم نقصه."""
    if HAS_RAQM:
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(text))
    except ImportError:
        return text


def _kwargs() -> dict:
    return {"direction": "rtl", "language": "ar"} if HAS_RAQM else {}


def draw_text(draw: ImageDraw.ImageDraw, xy, text: str, font, fill,
              anchor: str = "ra", shadow: tuple | None = None) -> None:
    prepared = _prepare(text)
    if shadow:
        offset, color = shadow
        draw.text((xy[0] + offset, xy[1] + offset), prepared, font=font,
                  fill=color, anchor=anchor, **_kwargs())
    draw.text(xy, prepared, font=font, fill=fill, anchor=anchor, **_kwargs())


def measure(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), _prepare(text), font=font, anchor="la", **_kwargs())
    return box[2] - box[0], box[3] - box[1]


def wrap(draw, text: str, font, max_width: int) -> list[str]:
    """تقسيم النص إلى أسطر. القياس يتم على النص المُشكّل فعليًا."""
    lines: list[str] = []
    current: list[str] = []
    for word in text.split():
        trial = current + [word]
        if measure(draw, " ".join(trial), font)[0] <= max_width or not current:
            current = trial
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def fit_text(draw, text: str, font_path: str | None, max_width: int,
             max_lines: int, start: int, minimum: int, weight: str | None = None):
    """يصغّر الخط حتى يستوعب الصندوق النص ضمن عدد الأسطر المسموح."""
    size = start
    while size > minimum:
        font = load_font(font_path, size, weight)
        lines = wrap(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines, int(size * 1.62)
        size -= 2
    font = load_font(font_path, minimum, weight)
    return font, wrap(draw, text, font, max_width)[:max_lines], int(minimum * 1.62)


# ──────────────────────────── الألوان ────────────────────────────


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore


def mix(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


# ──────────────────────────── الصورة الأصلية ────────────────────────────

BAD_URL_HINTS = (
    "logo", "placeholder", "default", "avatar", "icon", "sprite",
    "blank", "gstatic.com", "news.google.com", "/favicon",
)


def looks_bad(url: str) -> bool:
    low = url.lower()
    return any(hint in low for hint in BAD_URL_HINTS)


def download_image(url: str, timeout: int = 20) -> Image.Image | None:
    """يحمّل صورة الخبر ويرفض الشعارات والأيقونات والصور الصغيرة."""
    if not url or looks_bad(url):
        log.info("رُفضت الصورة (رابط مشبوه): %s", (url or "")[:80])
        return None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200 or len(resp.content) < 15_000:
            log.info("رُفضت الصورة (حجم صغير %d بايت)", len(resp.content))
            return None
        img = Image.open(io.BytesIO(resp.content))
        img.load()
    except (requests.RequestException, OSError) as exc:
        log.info("تعذّر تحميل الصورة: %s", exc)
        return None

    w, h = img.size
    if w < 420 or h < 260:
        log.info("رُفضت الصورة (أبعاد صغيرة %dx%d)", w, h)
        return None
    if not 0.9 <= (w / h) <= 3.2:  # نسبة غريبة = بانر أو شعار عمودي
        log.info("رُفضت الصورة (نسبة غير ملائمة %.2f)", w / h)
        return None
    return img.convert("RGB")


def cover(img: Image.Image, width: int, height: int) -> Image.Image:
    scale = max(width / img.width, height / img.height)
    img = img.resize(
        (max(width, round(img.width * scale)), max(height, round(img.height * scale))),
        Image.LANCZOS,
    )
    left = (img.width - width) // 2
    top = int((img.height - height) * 0.30)  # الوجوه غالبًا في الثلث الأعلى
    return img.crop((left, top, left + width, top + height))


def placeholder(width: int, height: int, primary: tuple, accent: tuple) -> Image.Image:
    """خلفية بديلة أنيقة عند غياب صورة صالحة للخبر."""
    img = Image.new("RGB", (width, height))
    px = img.load()
    light = mix(primary, (255, 255, 255), 0.18)
    dark = mix(primary, (0, 0, 0), 0.35)
    for y in range(height):
        row = mix(light, dark, y / max(height - 1, 1))
        for x in range(width):
            px[x, y] = row  # type: ignore

    d = ImageDraw.Draw(img, "RGBA")
    step = 78
    for i in range(-height, width, step):  # خطوط قطرية خفيفة
        d.line([(i, height), (i + height, 0)], fill=(*accent, 16), width=2)
    return img


# ──────────────────────────── الكارت ────────────────────────────


_last_logo_size: list[int] = [0, 0]   # (عرض، ارتفاع) آخر شعار لُصق فعليًا


def find_logo(relative: str) -> Path | None:
    """يبحث عن ملف الشعار، ويجرّب امتدادات وحالات أحرف بديلة."""
    direct = resolve(relative)
    if direct.exists():
        return direct

    stem = direct.stem
    folder = direct.parent
    if folder.is_dir():
        for f in sorted(folder.iterdir()):
            if f.is_file() and f.stem.lower() == stem.lower() and \
               f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                log.info("عُثر على الشعار باسم مختلف: %s", f.name)
                return f
        available = [f.name for f in folder.iterdir() if f.is_file()][:12]
        log.error("الشعار '%s' غير موجود. محتويات %s: %s",
                  relative, folder.name, available or "فارغ")
    else:
        log.error("المجلد غير موجود: %s", folder)
    return None


def paste_logo(canvas: Image.Image, logo_path: Path, box: tuple[int, int, int, int]) -> bool:
    """يركّب شعار العلامة داخل الصندوق مع الحفاظ على النسبة والشفافية."""
    try:
        logo = Image.open(logo_path)
        logo.load()
    except (OSError, ValueError) as exc:
        log.warning("تعذّر فتح الشعار %s: %s", logo_path, exc)
        return False

    logo = logo.convert("RGBA")
    x0, y0, x1, y1 = box
    max_w, max_h = x1 - x0, y1 - y0
    scale = min(max_w / logo.width, max_h / logo.height)
    if scale <= 0:
        return False
    logo = logo.resize(
        (max(1, round(logo.width * scale)), max(1, round(logo.height * scale))),
        Image.LANCZOS,
    )
    # ملتصق باليمين، متوسط عموديًا
    pos = (x1 - logo.width, y0 + (max_h - logo.height) // 2)
    canvas.paste(logo, pos, logo)
    _last_logo_size[0], _last_logo_size[1] = logo.width, logo.height
    return True


def badge_left(draw, left: int, center_y: int, text: str, font, bg, fg,
               pad_x: int = 22, pad_y: int = 11) -> int:
    """يرسم ملصقًا بمحاذاة اليسار ومركز عمودي، ويعيد حدّه الأيمن."""
    tw, th = measure(draw, text, font)
    w, h = tw + pad_x * 2, th + pad_y * 2
    y0 = center_y - h // 2
    draw.rounded_rectangle([left, y0, left + w, y0 + h], radius=h // 2, fill=bg)
    draw_text(draw, (left + w // 2, center_y), text, font, fg, anchor="mm")
    return left + w


def build_post_image(
    headline: str,
    category: str,
    urgent: bool,
    image_urls: list[str] | str | None,
    publisher: str,
    cfg,
    out_path: Path,
    fallback_urls: list[str] | None = None,
) -> Path:
    W = int(cfg.path("image.width", 1080))
    H = int(cfg.path("image.height", 1080))
    primary = hex_rgb(cfg.path("brand.primary_color", "#12203A"))
    accent = hex_rgb(cfg.path("brand.accent_color", "#F0B429"))
    brand_name = cfg.path("brand.name", "")
    tagline = cfg.path("brand.tagline", "")
    handle = cfg.path("brand.handle", "")
    f_head = cfg.path("image.font_headline")
    f_body = cfg.path("image.font_body")
    head_weight = cfg.path("image.font_headline_weight") or None
    f_body = f_body or f_head              # فارغ = استخدم خط العنوان نفسه
    body_weight = cfg.path("image.font_body_weight") or None

    canvas = Image.new("RGB", (W, H), primary)
    draw = ImageDraw.Draw(canvas)
    margin = int(W * 0.06)
    rule = max(4, W // 240)

    # ── قياس شريط العنوان أولًا لنعرف المساحة المتبقية للصورة ──
    head_font, head_lines, line_h = fit_text(
        draw, headline, f_head,
        max_width=W - margin * 2,
        max_lines=4,
        start=int(W * 0.052),
        minimum=int(W * 0.032),
        weight=head_weight,
    )
    band_pad = int(H * 0.045)
    band_h = len(head_lines) * line_h + band_pad * 2

    header_h = int(H * 0.160) if (brand_name or cfg.path("brand.logo")) else 0
    footer_h = int(H * 0.082) if (handle or publisher) else 0
    photo_top = header_h
    photo_h = H - header_h - band_h - footer_h

    # ── 1) الصورة أو البديل: نجرّب المرشحين بالترتيب ──
    candidates = (
        [image_urls] if isinstance(image_urls, str)
        else list(image_urls or [])
    )
    source = None
    illustrative = False
    for url in candidates[:6]:
        source = download_image(url)
        if source is not None:
            log.info("اعتُمدت صورة الخبر: %s", url[:90])
            break

    # لا صورة من الناشر → صورة حرة الترخيص، تُوسم "تعبيرية"
    if source is None and fallback_urls:
        for url in fallback_urls[:6]:
            source = download_image(url)
            if source is not None:
                illustrative = True
                log.info("اعتُمدت صورة تعبيرية حرة: %s", url[:90])
                break

    if source is None:
        log.info("لا صورة متاحة — سيُستخدم البديل المصمم")
    used_original = source is not None
    photo = (
        cover(source, W, photo_h) if source
        else placeholder(W, photo_h, primary, accent)
    )
    if used_original and cfg.path("image.sharpen", True):
        photo = photo.filter(ImageFilter.UnsharpMask(radius=2, percent=55, threshold=3))

    # تعتيم متدرّج أعلى الصورة وأسفلها ليمتزج بالشريطين
    overlay = Image.new("RGBA", (W, photo_h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    fade = int(photo_h * 0.22)
    for i in range(fade):
        a = int(150 * (1 - i / fade) ** 1.7)
        od.line([(0, i), (W, i)], fill=(*mix(primary, (0, 0, 0), 0.3), a))
        od.line([(0, photo_h - 1 - i), (W, photo_h - 1 - i)],
                fill=(*mix(primary, (0, 0, 0), 0.3), a))
    photo = Image.alpha_composite(photo.convert("RGBA"), overlay).convert("RGB")
    canvas.paste(photo, (0, photo_top))

    # ── 2) الترويسة: الشعار واسم الصفحة يمينًا، الملصقات يسارًا ──
    if header_h:
        draw.rectangle([0, 0, W, header_h], fill=primary)
        draw.rectangle([0, header_h - rule, W, header_h], fill=accent)

        inner_top = int(header_h * 0.14)
        inner_bot = header_h - rule - int(header_h * 0.14)
        text_right = W - margin

        # الشعار في أقصى اليمين
        logo_rel = cfg.path("brand.logo")
        if logo_rel:
            logo_file = find_logo(logo_rel)
            if logo_file:
                scale = float(cfg.path("brand.logo_scale", 1.0))
                # الصندوق يرتفع مع scale لكنه لا يتجاوز الترويسة،
                # وعرضه سخيّ حتى لا تُسحق الشعارات العريضة.
                box_h = min((inner_bot - inner_top) * scale, header_h - rule * 2)
                box_w = W * float(cfg.path("brand.logo_max_width", 0.42))
                center_y = (inner_top + inner_bot) / 2
                if paste_logo(
                    canvas, logo_file,
                    (int(text_right - box_w), int(center_y - box_h / 2),
                     int(text_right), int(center_y + box_h / 2)),
                ):
                    draw = ImageDraw.Draw(canvas)   # إعادة الربط بعد اللصق
                    used_w = _last_logo_size[0] or int(box_h)
                    text_right -= used_w + int(W * 0.022)

        # اسم الصفحة، وتحته الشعار الفرعي — بمحاذاة اليمين
        if brand_name:
            nf = load_font(f_head, int(W * 0.050), head_weight)
            if tagline:
                draw_text(draw, (text_right, inner_top + int(header_h * 0.30)),
                          brand_name, nf, accent, anchor="rm")
                tf = load_font(f_body, int(W * 0.024), body_weight)
                draw_text(draw, (text_right, inner_top + int(header_h * 0.68)),
                          tagline, tf, mix(accent, (255, 255, 255), 0.55), anchor="rm")
            else:
                draw_text(draw, (text_right, (inner_top + inner_bot) // 2),
                          brand_name, nf, accent, anchor="rm")

        # الملصقات في أقصى اليسار
        bdg_font = load_font(f_body, int(W * 0.026), body_weight)
        bx = margin
        by = (inner_top + inner_bot) // 2
        if urgent:
            bx = badge_left(draw, bx, by, "عاجل", bdg_font,
                            (206, 32, 39), (255, 255, 255)) + int(W * 0.014)
        if category:
            badge_left(draw, bx, by, category, bdg_font, accent, primary)

    # وسم الصورة التعبيرية: إخفاء أنها ليست من مكان الحدث تضليل
    if illustrative:
        tag_font = load_font(f_body, int(W * 0.021), body_weight)
        label = "صورة تعبيرية"
        tw, th = measure(draw, label, tag_font)
        pad = int(W * 0.012)
        bx, by = margin, photo_top + photo_h - int(W * 0.028) - th - pad * 2
        draw.rounded_rectangle(
            [bx, by, bx + tw + pad * 2, by + th + pad * 2],
            radius=int(W * 0.008), fill=(0, 0, 0, 255),
        )
        draw_text(draw, (bx + pad + tw // 2, by + pad + th // 2), label,
                  tag_font, (225, 228, 235), anchor="mm")

    # ── 4) شريط العنوان ──
    band_top = photo_top + photo_h
    draw.rectangle([0, band_top, W, band_top + band_h], fill=primary)
    draw.rectangle([0, band_top, W, band_top + rule], fill=accent)

    y = band_top + band_pad + line_h // 2
    for line in head_lines:
        draw_text(draw, (W // 2, y), line, head_font, (255, 255, 255), anchor="mm")
        y += line_h

    # ── 5) التذييل ──
    if footer_h:
        ft_top = H - footer_h
        draw.rectangle([0, ft_top, W, H], fill=mix(primary, (0, 0, 0), 0.28))
        ff = load_font(f_body, int(W * 0.024), body_weight)
        mid = ft_top + footer_h // 2
        if handle:
            draw_text(draw, (margin, mid), handle, ff,
                      mix(accent, (255, 255, 255), 0.3), anchor="lm")
        if publisher and used_original:
            draw_text(draw, (W - margin, mid), f"المصدر: {publisher}", ff,
                      (168, 180, 200), anchor="rm")
        elif not used_original:
            draw_text(draw, (W - margin, mid),
                      f"{datetime.now(timezone.utc):%Y/%m/%d}", ff,
                      (168, 180, 200), anchor="rm")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=90, optimize=True, subsampling=0)
    log.info("الصورة جاهزة: %s (صورة أصلية=%s، أسطر=%d)",
             out_path.name, used_original, len(head_lines))
    return out_path
