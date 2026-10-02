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
_preloaded: dict[str, Image.Image] = {}   # صور حُمّلت مسبقًا لترتيب الوجوه


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


# ───────────────────── أسماء الناشرين في التذييل (Issue #1145) ─────────────────────


def _display_names(cfg) -> dict[str, str]:
    """name -> name_ar لكل مصدر/قناة في الإعداد. الاستبدال هنا لا في المصدر
    نفسه: name يبقى مفتاح مطابقة في بقية الأنبوب (استبعاد، تجميع، تاريخ)."""
    out: dict[str, str] = {}
    for key in ("sources", "channels"):
        for item in (cfg.path(key) or []) if cfg else []:
            if isinstance(item, dict) and item.get("name") and item.get("name_ar"):
                out[str(item["name"])] = str(item["name_ar"])
    return out


def resolve_publisher_names(names: list[str], cfg) -> list[str]:
    """يستبدل كل اسم ناشر بـname_ar إن وُجد. المطابقة تامة أولًا؛ وإن وردت
    الأسماء داخل عبارة أطول («صورة: ערוץ 14»، «تحليل لتغطية ערוץ 14») تُستبدل
    كجزء نصي، الأطول أولًا حتى لا يفسد اسم قصير اسمًا يحويه."""
    mapping = _display_names(cfg)
    ordered = sorted(mapping, key=len, reverse=True)
    out = []
    for n in names:
        n = str(n)
        if n in mapping:
            out.append(mapping[n])
            continue
        for orig in ordered:
            if orig in n:
                n = n.replace(orig, mapping[orig])
        out.append(n)
    return out


def _font_codepoints(font) -> set[int] | None:
    """مجموعة رموز الخط الفعلي (بعد أي رجوع إلى خط احتياطي) أو None إن تعذّر."""
    path = getattr(font, "path", None)
    if not path or not isinstance(path, (str, Path)):
        return None
    try:
        from fontTools.ttLib import TTFont

        with TTFont(str(path), lazy=True) as tt:
            return set(tt.getBestCmap() or {})
    except Exception:  # noqa: BLE001
        return None


def drop_unrenderable_names(names: list[str], font) -> list[str]:
    """حارس: اسم فيه حرف ليس في الخط المستعمل فعلًا يُحذف ويُسجَّل باسمه —
    لا يجوز أن يُرسم مربع فارغ. الفراغات وأحرف التحكم/التشكيل غير المرئية
    لا تُعدّ نقصًا."""
    cps = _font_codepoints(font)
    if cps is None:
        return list(names)
    kept = []
    for n in names:
        missing = sorted({c for c in n if not c.isspace() and ord(c) not in cps
                          and ord(c) not in (0x200C, 0x200D, 0x200E, 0x200F, 0x061C)})
        if missing:
            log.warning("حُذف اسم الناشر %r من سطر المصدر: حروف غير موجودة في الخط %s",
                        n, "".join(missing))
            continue
        kept.append(n)
    return kept


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


def download_image(url: str, timeout: int = 20,
                   failures: list | None = None) -> Image.Image | None:
    """يحمّل صورة الخبر ويرفض الشعارات والأيقونات والصور الصغيرة.

    failures (اختياري): إن مُرِّرت، يُلحَق بها {"url":..., "reason":...} عند كل
    رفض — يستهلكها build_post_image لتسجيل سبب فشل كل مرشَّح في report، بدل
    أن يبقى الفشل في سجل log وحده بلا أثر في تقرير المسودة (تشخيص Issue
    #373: «الصورة غائبة ولا سبب في التقرير»)."""
    def _record(reason: str) -> None:
        if failures is not None:
            failures.append({"url": url, "reason": reason})

    if not url or looks_bad(url):
        log.info("رُفضت الصورة (رابط مشبوه): %s", (url or "")[:80])
        _record("رابط مشبوه")
        return None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200 or len(resp.content) < 15_000:
            log.info("رُفضت الصورة (حجم صغير %d بايت)", len(resp.content))
            _record(f"HTTP {resp.status_code}، حجم {len(resp.content)} بايت (دون 15000)")
            return None
        img = Image.open(io.BytesIO(resp.content))
        img.load()
    except (requests.RequestException, OSError) as exc:
        log.info("تعذّر تحميل الصورة: %s", exc)
        _record(f"تعذّر التحميل: {exc}")
        return None

    w, h = img.size
    if w < 420 or h < 260:
        log.info("رُفضت الصورة (أبعاد صغيرة %dx%d)", w, h)
        _record(f"أبعاد صغيرة {w}×{h}")
        return None
    if not 0.9 <= (w / h) <= 3.2:  # نسبة غريبة = بانر أو شعار عمودي
        log.info("رُفضت الصورة (نسبة غير ملائمة %.2f)", w / h)
        _record(f"نسبة غير ملائمة {w / h:.2f}")
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


def dim_photo(photo: Image.Image, primary: tuple) -> Image.Image:
    """تعتيم متدرّج أعلى الصورة وأسفلها ليمتزج بما يجاورها من شرائط."""
    W, H = photo.size
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    fade = int(H * 0.22)
    for i in range(fade):
        a = int(150 * (1 - i / fade) ** 1.7)
        od.line([(0, i), (W, i)], fill=(*mix(primary, (0, 0, 0), 0.3), a))
        od.line([(0, H - 1 - i), (W, H - 1 - i)],
                fill=(*mix(primary, (0, 0, 0), 0.3), a))
    return Image.alpha_composite(photo.convert("RGBA"), overlay).convert("RGB")


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


def face_score(img: Image.Image) -> float:
    """
    مقياس حضور الوجوه في الصورة: نسبة أكبر وجه إلى مساحة الصورة.

    يُستخدم لترتيب الصورتين في القالب المركّب: الصورة ذات الوجه الأكبر
    هي اللقطة القريبة، فتذهب إلى **الدائرة**، والمشهد الواسع (مبنى،
    شارع، بحر) يذهب إلى الخلفية حيث تتسع مساحته.

    يعيد 0.0 إن تعذّر الكشف، فلا يتعطّل شيء بغياب المكتبة.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return 0.0

    try:
        small = img.convert("L")
        scale = 480 / max(small.size)
        if scale < 1:
            small = small.resize((max(int(small.width * scale), 1),
                                  max(int(small.height * scale), 1)))
        grey = np.array(small)
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(grey, scaleFactor=1.1, minNeighbors=5,
                                         minSize=(24, 24))
    except Exception:  # noqa: BLE001 — الكشف تحسين لا شرط
        return 0.0

    if len(faces) == 0:
        return 0.0
    area = grey.shape[0] * grey.shape[1]
    return max(w * h for _, _, w, h in faces) / max(area, 1)


def visual_hash(img: Image.Image, size: int = 10) -> list[int]:
    """
    بصمة بصرية بسيطة (difference hash) تصف *محتوى* الصورة لا رابطها.

    نصغّر الصورة إلى شبكة رمادية صغيرة ونقارن كل بكسل بجاره: النتيجة
    سلسلة بتات تبقى شبه ثابتة رغم اختلاف الحجم أو القصّ أو الضغط.
    """
    grey = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = grey.load()
    return [1 if px[x, y] > px[x + 1, y] else 0
            for y in range(size) for x in range(size)]


def visual_distance(a: list[int], b: list[int]) -> float:
    """نسبة البتات المختلفة بين بصمتين: 0 = متطابقتان، 1 = مختلفتان تمامًا."""
    if not a or not b or len(a) != len(b):
        return 1.0
    return sum(x != y for x, y in zip(a, b)) / len(a)


def closeness(img: Image.Image, grid: int = 32) -> float:
    """
    تقدير قُرب الموضوع من الكاميرا: 0 = مشهد واسع، 1 = لقطة قريبة.

    اللقطة القريبة (وجه، شخص) فيها موضوع كبير متجانس وخلفية ناعمة، فتقلّ
    التفاصيل الدقيقة. أما المشهد الواسع (مبنى، شارع، حشد) فمليء بالحواف:
    نوافذ وأعمدة وأشخاص صغار.

    نقيس ذلك بكثافة الحواف: كلما قلّت، اقتربت الكاميرا.
    """
    grey = img.convert("L").resize((grid, grid), Image.LANCZOS)
    px = grey.load()
    edges = 0
    for y in range(grid):
        for x in range(grid - 1):
            if abs(px[x, y] - px[x + 1, y]) > 10:
                edges += 1
    for y in range(grid - 1):
        for x in range(grid):
            if abs(px[x, y] - px[x, y + 1]) > 10:
                edges += 1
    density = edges / (2 * grid * (grid - 1))
    return max(0.0, min(1.0, 1.0 - density * 2.4))


def palette(img: Image.Image, buckets: int = 4) -> list[float]:
    """
    توزيع ألوان الصورة كبصمة: نسبة البكسلات في كل خانة لونية.

    صورتان لنفس المشهد من زاويتين تتشاركان لوحة الألوان (سماء الغروب،
    زرقة البحر، أخضر الملعب) حتى لو اختلف ترتيب العناصر — وهو ما لا
    تلتقطه بصمة الشكل وحدها.
    """
    small = img.convert("RGB").resize((48, 48), Image.LANCZOS)
    px = small.load()
    step = 256 // buckets
    hist = [0] * (buckets ** 3)
    for y in range(48):
        for x in range(48):
            r, g, b = px[x, y]
            hist[(r // step) * buckets * buckets
                 + (g // step) * buckets + (b // step)] += 1
    total = 48 * 48
    return [c / total for c in hist]


def palette_distance(a: list[float], b: list[float]) -> float:
    """0 = لوحتان متطابقتان، 1 = مختلفتان تمامًا."""
    if not a or not b or len(a) != len(b):
        return 1.0
    return sum(abs(x - y) for x, y in zip(a, b)) / 2


def quiet_side(img: Image.Image, radius: int, margin: int,
               top: int) -> str:
    """
    أي جهة أهدأ لوضع الدائرة فوقها؟

    الدائرة تحجب ما تحتها. وضعها فوق موضوع الخبر يفسد الصورة — كما حدث
    حين غطّت اللاعب الذي يدور حوله الخبر. نقارن كثافة التفاصيل في
    الزاويتين ونختار الأقل ازدحامًا.
    """
    side = radius * 2
    box_h = min(side + margin, img.height)
    left = img.crop((margin, top, min(margin + side, img.width), top + box_h))
    right = img.crop((max(img.width - margin - side, 0), top,
                      max(img.width - margin, 1), top + box_h))

    def busy(region: Image.Image) -> float:
        grey = region.convert("L").resize((20, 20), Image.LANCZOS)
        px = grey.load()
        edges = sum(1 for y in range(20) for x in range(19)
                    if abs(px[x, y] - px[x + 1, y]) > 12)
        edges += sum(1 for y in range(19) for x in range(20)
                     if abs(px[x, y] - px[x, y + 1]) > 12)
        return edges / 760

    busy_left, busy_right = busy(left), busy(right)
    chosen = "left" if busy_left <= busy_right else "right"
    log.info("جهة الدائرة: %s (يسار %.2f · يمين %.2f)",
             "اليسار" if chosen == "left" else "اليمين", busy_left, busy_right)
    return chosen


def circular_inset(canvas: Image.Image, photo: Image.Image,
                  center: tuple[int, int], radius: int,
                  ring: tuple[int, int, int], ring_width: int) -> None:
    """
    يركّب صورة ثانية في دائرة بإطار — القالب الشائع في صفحات الغرائب.

    الفائدة أن الخبر يحمل غالبًا وجهًا ومكانًا: الوجه في الخلفية والمكان
    في الدائرة، فيفهم القارئ القصة من الصورة وحدها.
    """
    size = radius * 2
    thumb = cover(photo, size, size)

    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)   # حواف ناعمة

    cx, cy = center
    canvas.paste(thumb, (cx - radius, cy - radius), mask)

    d = ImageDraw.Draw(canvas)
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
              outline=ring, width=ring_width)


def fit_headline(draw, text: str, font_path: str | None, max_width: int,
                 max_height: float, start: int, weight: str | None = None):
    """عنوان البطاقة المربعة (Issue #1158): يصغّر بخطوة 2 حتى تتّسع كل
    الأسطر في max_height، بلا حدّ أدنى للحجم ولا حدّ لعدد الأسطر — لا يُقصّ
    النص أبدًا. fit_text القائمة تقصّ عند الحدّ الأدنى وتستعملها الريلز،
    فلا تُعدَّل. يعيد (الخط، الأسطر، ارتفاع السطر = 1.45 × الحجم)."""
    size = start
    while True:
        font = load_font(font_path, size, weight)
        lines = wrap(draw, text, font, max_width)
        line_h = int(size * 1.45)
        # size <= 2: ضمان إنهاء الحلقة لنص شاذّ لا يتّسع بأي حجم معقول
        if len(lines) * line_h <= max_height or size <= 2:
            return font, lines, line_h
        size -= 2


def fade_photo(photo: Image.Image, primary: tuple, top_ratio: float,
               bottom_ratio: float, power: float) -> Image.Image:
    """تدرّجا البطاقة العموديّة (Issue #1161): أعلى الصورة يذوب فيه primary
    (عتامة 255 عند حافة الشريط تنزل إلى 0 بمنحنى (1−t)^power)، وأسفلها تذوب
    الصورة في primary (0 ← 255 عند الحافة السفلية بمنحنى t^power). الغاية أن
    تلتحم الصورة بالشريط والعنوان بلا حدّ ظاهر فلا حاجة لخطوط فاصلة. دالة
    مستقلة عن dim_photo (تعتيم قديم لم يعد يُستعمل) ولا تمسّها الريلز."""
    w, h = photo.size
    n_top = max(2, round(h * top_ratio))
    n_bot = max(2, round(h * bottom_ratio))
    col = Image.new("L", (1, h), 0)
    for i in range(n_top):
        col.putpixel((0, i), round(255 * (1 - i / (n_top - 1)) ** power))
    for j in range(n_bot):
        col.putpixel((0, h - n_bot + j), round(255 * (j / (n_bot - 1)) ** power))
    mask = col.resize((w, h), Image.NEAREST)
    return Image.composite(Image.new("RGB", (w, h), primary), photo.convert("RGB"), mask)


def plan_card_layout(draw, headline: str, badge_texts: list[str], cfg) -> dict:
    """هندسة بطاقة 4:5 كلّها في مكان واحد (Issue #1161) كي يرسم بها
    build_post_image وتقيس بها الاختبارات من الدالة نفسها لا من نسخة ثانية.

    الشريطان بارتفاع ثابت بالبكسل (W×0.082) لا يكبر مع طول البطاقة؛ الصورة
    4:3 تمامًا تبدأ عند الشريط؛ منطقة العنوان من أسفل الصورة إلى الشريط
    السفلي بحشوة عمودية نسبية أعلى وأسفل. الشارات (badge_texts بترتيب
    اليمين ← اليسار) مجموعة واحدة محاذاة لليمين حافتها السفلية فوق أول سطر
    للعنوان بمسافة ثابتة، ويجب أن تقع كلها تحت بداية التدرّج السفلي — وإلا
    يصغر العنوان خطوة أخرى فيهبط أول سطر والشارات معه. «أول سطر» = أعلى
    صندوق سطره (block_top)، لا حبر الحروف، فالمسافة قابلة للقياس بلا تخمين."""
    W = int(cfg.path("image.width", 1080))
    H = int(cfg.path("image.height", 1350))
    f_head = cfg.path("image.font_headline")
    f_body = cfg.path("image.font_body") or f_head
    head_weight = cfg.path("image.font_headline_weight") or None
    body_weight = cfg.path("image.font_body_weight") or None
    margin = int(W * 0.06)
    bar = int(W * 0.082)
    photo_top, photo_h = bar, round(W * 3 / 4)
    photo_bottom = photo_top + photo_h
    fade_start = photo_bottom - round(
        photo_h * float(cfg.path("image.fade_bottom_ratio", 0.30)))
    zone_top, zone_bottom = photo_bottom, H - bar
    zone_h = zone_bottom - zone_top
    avail = zone_h * (1 - 2 * float(cfg.path("image.title_pad_ratio", 0.08)))
    gap_badge = int(W * float(cfg.path("image.badge_gap_ratio", 0.022)))

    bfont = load_font(f_body, int(W * 0.026), body_weight)
    pad_x, pad_y, gap = 22, 11, int(W * 0.014)
    sizes = []
    for t in badge_texts:
        tw, th = measure(draw, t, bfont)
        sizes.append((tw + pad_x * 2, th + pad_y * 2))
    tallest = max((h for _, h in sizes), default=0)

    size = int(W * float(cfg.path("image.title_start_ratio", 0.095)))
    while True:
        font, lines, line_h = fit_headline(
            draw, headline, f_head, W - margin * 2, avail, size, head_weight)
        block_top = zone_top + (zone_h - len(lines) * line_h) // 2
        badge_bottom = block_top - gap_badge
        cur = getattr(font, "size", size)
        if not sizes or badge_bottom - tallest >= fade_start or cur <= 2:
            break
        size = cur - 2

    badges, x1 = [], W - margin
    for text, (w, h) in zip(badge_texts, sizes):
        badges.append({"text": text, "x0": x1 - w, "x1": x1,
                       "y0": badge_bottom - h, "y1": badge_bottom})
        x1 -= w + gap
    return {
        "W": W, "H": H, "margin": margin, "bar": bar,
        "photo_top": photo_top, "photo_h": photo_h, "fade_start": fade_start,
        "zone_top": zone_top, "zone_bottom": zone_bottom,
        "font": font, "lines": lines, "line_h": line_h, "block_top": block_top,
        "badge_gap": gap_badge, "badges": badges, "badge_font": bfont,
    }


# ──────────────────────── ضبط العنوان بالمدّ (Issue #1165) ────────────────────────

TATWEEL = "\u0640"
_TASHKEEL = set("\u064B\u064C\u064D\u064E\u064F\u0650\u0651\u0652\u0670")
# ثنائيّة الاتصال: تتصل بما قبلها وما بعدها، فهي وحدها التي يُدرج المدّ بعدها
_DUAL_JOIN = set("بتثجحخسشصضطظعغفقكلمنهيىئ")
# ما يقبل الاتصال بحرف سابق: الثنائيّة + اليمينيّة (ا د ذ ر ز و ة ؤ ...)
_JOINS_PREV = _DUAL_JOIN | set("اأإآٱدذرزوؤة")
_ALEF = set("اأإآ")


def kashida_slot(word: str) -> int | None:
    """فهرس إدراج المدّ في الكلمة أو None. آخر موضع بين ثنائيّ الاتصال وحرف
    يقبل الاتصال من اليمين؛ يأتي بعد تشكيل الحرف الأول (الشدّة تلزم حرفها).
    اللام قبل أي ألف ممنوعة: «السلام» لا تصير «السلـام» لأن اللام-ألف
    رابطة واحدة. الأخير لأن آخر الكلمة أبعد عن بداية القراءة فيقلّ التشويه."""
    for i in range(len(word) - 2, -1, -1):
        c = word[i]
        if c not in _DUAL_JOIN:
            continue
        j = i + 1
        while j < len(word) and word[j] in _TASHKEEL:
            j += 1
        if j >= len(word):
            continue
        nxt = word[j]
        if nxt not in _JOINS_PREV or (c == "ل" and nxt in _ALEF):
            continue
        return j
    return None


def _ink(draw, text: str, font) -> tuple[float, float]:
    """(عرض الحبر الفعلي، إزاحة حافته اليمنى عن نقطة الرسم ra). نضبط بالحبر
    لا بصندوق textbbox ولا بالتقدّم: Raqm يترك هامشًا جانبيًا يصل ~9 بكسل
    داخل الصندوق فلا يلتصق السطر بالحافة الحقيقية. القياس برسم الكلمة على
    لوحة مؤقتة وأخذ bbox قناتها."""
    size = getattr(font, "size", 40)
    adv = int(draw.textlength(_prepare(text), font=font, **_kwargs())) + 1
    pad = size
    canvas = Image.new("L", (adv + pad * 2, size * 3), 0)
    anchor_x = adv + pad
    ImageDraw.Draw(canvas).text((anchor_x, size * 3 // 2), _prepare(text), font=font,
                                fill=255, anchor="rm", **_kwargs())
    box = canvas.getbbox()
    if not box:
        return float(adv), 0.0
    return float(box[2] - box[0]), float(box[2] - anchor_x)


def kashida_word(word: str, k: int) -> str:
    slot = kashida_slot(word) if k > 0 else None
    return word if slot is None else word[:slot] + TATWEEL * k + word[slot:]


def justify_line(draw, line: str, font, width: int, max_k: int = 8) -> dict | None:
    """يحسب ضبط سطر على width كاملًا: k واحد لكل الكلمات الصالحة (الأكبر الذي
    لا يتجاوز width) ثم يُوزَّع الباقي بالتساوي على المسافات فيلتصق السطر
    بالحافتين. None للسطر ذي الكلمة الواحدة أو إن تجاوز عرضه الطبيعي width.
    المدّ لا يغيّر تقسيم الأسطر ولا الحجم — يُحسب بعدهما فقط."""
    words = line.split()
    if len(words) < 2:
        return None
    space = draw.textlength(_prepare(" "), font=font, **_kwargs())
    has_tatweel = ord(TATWEEL) in (_font_codepoints(font) or {ord(TATWEEL)})
    valid = [has_tatweel and kashida_slot(w) is not None for w in words]

    def total(k: int) -> tuple[list[str], list[float], float]:
        forms = [kashida_word(w, k) if v else w for w, v in zip(words, valid)]
        widths = [_ink(draw, f, font)[0] for f in forms]
        return forms, widths, sum(widths) + space * (len(words) - 1)

    best_k, best = 0, total(0)
    if best[2] > width:
        return None
    if any(valid):
        for k in range(1, max(0, int(max_k)) + 1):
            trial = total(k)
            if trial[2] > width:
                break
            best_k, best = k, trial
    forms, widths, natural = best
    gap = space + (width - natural) / (len(words) - 1)
    return {"words": forms, "widths": widths, "gap": gap, "k": best_k,
            "valid": valid}


def draw_headline_lines(draw, lines: list[str], font, right: int, left: int,
                        y_first: int, line_h: int, fill, justify: bool = True,
                        max_k: int = 8) -> None:
    """يرسم أسطر العنوان. كل سطر عدا الأخير يُضبط بالمدّ على (right−left)؛
    الأخير (ومنه سطر العنوان الوحيد) والسطر ذو الكلمة الواحدة محاذاة لليمين.
    الرسم كلمة كلمة من اليمين بمواضع محسوبة (يعمل بـRaqm وبالاحتياطي معًا)،
    وعلى الصورة فقط: نص المسودة المحفوظ لا يلمسه شيء."""
    y = y_first
    for idx, line in enumerate(lines):
        plan = (justify_line(draw, line, font, right - left, max_k)
                if justify and idx < len(lines) - 1 else None)
        if plan is None:
            # محاذاة بالحبر لا بالتقدّم كبقية الأسطر: Raqm يترك هامشًا ~6 بكسل
            # فكان حبر الأخير يقع يسار W−margin (Issue #1167).
            draw_text(draw, (round(right - _ink(draw, line, font)[1]), y), line,
                      font, fill, anchor="rm")
        else:
            x = float(right)  # حافة الحبر اليمنى للكلمة الحالية
            for form, w in zip(plan["words"], plan["widths"]):
                draw_text(draw, (round(x - _ink(draw, form, font)[1]), y), form,
                          font, fill, anchor="rm")
                x -= w + plan["gap"]
        y += line_h


def draw_text_ltr(draw, xy, text: str, font, fill, anchor: str = "la") -> None:
    """نص لاتيني من اليسار لليمين بلا قلب bidi: draw_text تفرض اتجاه rtl
    فيُقلب «@almujez» إلى «almujez@» (الرمز المحايد يذهب لآخر السطر)."""
    kwargs = {"direction": "ltr", "language": "en"} if HAS_RAQM else {}
    draw.text(xy, text, font=font, fill=fill, anchor=anchor, **kwargs)


def paste_logo_trimmed(canvas: Image.Image, logo_path: Path, right: int,
                       center_y: int, height: int, max_width: int) -> int:
    """يلصق الشعار بعد قصّ هوامشه الشفافة (bbox قناة alpha) بالارتفاع
    المطلوب ملتصقًا بـright، ولا يتجاوز max_width. يعيد العرض المستعمل
    (0 عند الفشل). دالة مستقلة عن paste_logo التي تستعملها الريلز."""
    try:
        logo = Image.open(logo_path)
        logo.load()
    except (OSError, ValueError) as exc:
        log.warning("تعذّر فتح الشعار %s: %s", logo_path, exc)
        return 0
    logo = logo.convert("RGBA")
    bbox = logo.getchannel("A").getbbox()
    if bbox:
        logo = logo.crop(bbox)
    scale = min(height / logo.height, max_width / logo.width)
    if scale <= 0:
        return 0
    logo = logo.resize((max(1, round(logo.width * scale)),
                        max(1, round(logo.height * scale))), Image.LANCZOS)
    canvas.paste(logo, (right - logo.width, center_y - logo.height // 2), logo)
    return logo.width


def build_post_image(
    headline: str,
    category: str,
    urgent: bool,
    image_urls: list[str] | str | None,
    publisher: str | list[str],
    cfg,
    out_path: Path,
    fallback_urls: list[str] | None = None,
    fallback_provider=None,
    bucket: str = "",
    report: dict | None = None,
    badge: str | None = None,
    origin: str = "",
    news_photo_provider=None,
) -> Path:
    """يبني بطاقة الخبر.

    `report` قاموس يُملأ بما جرى: هل استُعملت صورة حقيقية للخبر أم
    الخلفية المصممة. المُستدعي يحتاج ذلك ليخبر المراجع أن هذه المسودة
    بلا صورة فيضيف واحدة — ولا سبيل لمعرفته من مسار الملف وحده.

    (تشخيص Issue #373، البند 1): يُملأ أيضًا بـcandidates_tried (كم مرشَّحًا
    من صور المصادر جُرِّب)، candidate_failures (سبب رفض كل مرشَّح، من
    مرشحات المصادر واحتياط find_images معًا)، وfallback_tried/
    fallback_candidates (هل استُدعي find_images وكم مرشَّحًا أعاد) — عطل
    الصورة كان يصل log وحده بلا أثر في تقرير المسودة الذي يراه المراجع.

    `badge`/`origin` (Issue #758، يخلف تصميم Issue #732): ملصق ثانٍ واحد
    في صف ملصقات الترويسة، بعد التصنيف مباشرة — محكوم بمسار المسودة
    (`origin`، قيم `store.origin_of` الست) لا بحكم الكاتب. `origin` يُبحث
    في جدول `config.yaml: cards` (badge/bg/fg لكل مسار)؛ `badge` صراحةً
    يبقى موجودًا ويفوز على الجدول إن مُرِّر (بلون accent/primary كسابقًا،
    التوافق مع Issue #732). لم يعد لـ`urgent` رسم خاص بها: حين يكون
    `origin == "news"` و`urgent` صحيحًا، يُقرأ ملصق "breaking" من الجدول
    بدلًا من "news" (خانة الأخبار فارغة أصلًا في الجدول) — لغيرها من
    المسارات (verify/article/request/analysis) ملصقها الخاص من الجدول
    يفوز دومًا بصرف النظر عن urgent. مسودة بلا origin أو بأصل غير مذكور
    في الجدول: لا ملصق ثانٍ، مع `log.warning` واحد بدل الانهيار أو التخمين.
    القالب الوحيد لكل مسارات النشر (أخبار وتحليل يوتيوب معًا) — لا نسخة
    بطاقة منفصلة لكل مسار، فلا تفترق الهويتان البصريتان مجددًا بصمت.

    `report["composite"]` (Issue #752): القيمة الفعلية لقرار "صورتان أم
    صورة واحدة" (choose_layout) — كانت تُسجَّل في السطر أعلاه للـlog فقط؛
    الآن تُحفَظ في المسودة (image_info.composite) ليعرضها review.image_source_line
    للمراجع قبل الاعتماد بدل أن تبقى أثرًا في سجلّ التشغيل وحده.

    `news_photo_provider` (Issue #1095، مسار التحليل وحده -- يخلف تصميم
    خلفية الفيديو الملغى، Issue #1092 -- youtube_publish.ensure_title_card):
    دالة بلا معاملات تعيد ``[{"url":..., "publisher":...}, ...]``. **سلّم
    الصورة (Issue #1123، قُلب ترتيبه): image_urls (صورة الناشر، مسار الأخبار)
    ← news_photo_provider (صورة خبر عن الموضوع) ← fallback_urls/
    fallback_provider (حرة الترخيص) ← بلا صورة.** صورة الخبر أقرب للحدث دومًا
    والحرة عامة بطبيعتها، فكان الترتيب السابق (حرة أولًا) مقلوبًا. الكسل باقٍ
    في الاتجاهين: `news_photo_provider` لا يُستدعى إن نجحت `image_urls`،
    و`fallback_provider` لا يُستدعى إن نجحت صورة الخبر -- بحث الأخبار وبحث
    الصور الحرة كلاهما عملية شبكة حقيقية، فاستدعاء أيٍّ منهما قبل التأكد من
    فشل الدرجات الأعلى يهدر نداءً لا حاجة له. مسار الأخبار لا يمرّر هذا
    المعامل أصلًا فترتيبه (الناشر ثم الحرة) لم يتغيّر. كل مرشَّح من نتيجتها
    يُجرَّب بالترتيب حتى ينجح تحميل واحد (نفس `download_image`، فنفس حدّ
    الأبعاد الأدنى يسري هنا أيضًا) -- **بلا فحص وجه إطلاقًا**، تمامًا كما
    لا يسري في مسار الأخبار: هذه صورة خبر عن الحدث نفسه لا صورة تعبيرية
    عامة. فحص الوجوه يبقى على الصورة الحرة وحدها (في
    youtube_extract.photo_candidates). الوسم «صورة تعبيرية» يتبع الصورة
    المستعملة فعلًا: للحرة فقط، لا لصورة الخبر.

    الصورة الناجحة هنا تُرسم **صورةً رئيسية عادية تمامًا** -- نفس الموضع
    والنسبة والمعالجة (`cover`/`sharpen`، بلا تعتيم منذ Issue #1158) للصورة
    الأصلية أو التعبيرية، لا خلفية مالئة ولا تعتيم موحَّد ولا تخطيط جديد
    إطلاقًا (الفشلان البصريان اللذان أنهيا تصميم خلفية الفيديو كانا بالضبط
    من اختراع تخطيط جديد -- الدرس المستفاد هنا هو استعمال القائم حرفيًا).
    ``report["kind"] = "news_photo"`` و``report["news_photo_publisher"]``
    عند النجاح يُميّزان الحالة صراحةً عن صورة الناشر الأصلية
    (`used_original` عادي، غير مضبوطة هنا) لمن يقرأ التقرير (راجع
    review.image_source_line) -- الفرق: هذه ليست صورة الناشر الذي يتحدّث
    المقال عنه (لا ناشر أصلي بنيويًا في مسار التحليل)، بل صورة ناشرٍ آخر
    يغطّي نفس الحدث."""
    W = int(cfg.path("image.width", 1080))
    H = int(cfg.path("image.height", 1350))
    primary = hex_rgb(cfg.path("brand.primary_color", "#12203A"))
    accent = hex_rgb(cfg.path("brand.accent_color", "#F0B429"))
    handle = cfg.path("brand.handle", "")
    f_head = cfg.path("image.font_headline")
    f_body = cfg.path("image.font_body")
    head_weight = cfg.path("image.font_headline_weight") or None
    f_body = f_body or f_head              # فارغ = استخدم خط العنوان نفسه
    body_weight = cfg.path("image.font_body_weight") or None

    # ── الملصق الثاني: من جدول cards: محكوم بـorigin (Issue #758) ──
    # badge الصريح يبقى ويفوز إن مُرِّر؛ خلاف ذلك يُبحث عن origin في الجدول.
    # لا رسم خاص بـurgent بعد الآن: حين origin == "news" وurgent صحيحة،
    # نقرأ ملصق "breaking" من الجدول بدلًا من "news" (خانتها فارغة أصلًا) —
    # فتحتفظ الأخبار العاجلة بملصقها بلا مزاحمة، وباقي المسارات (لها ملصقها
    # الخاص من الجدول) لا تتأثر بهذا التحويل إطلاقًا.
    badge_bg, badge_fg = accent, primary
    badge_is_breaking = False
    if badge is None:
        table_origin = "breaking" if (origin == "news" and urgent) else origin
        badge_is_breaking = table_origin == "breaking"
        card = cfg.path(f"cards.{table_origin}") if table_origin else None
        if card is None:
            log.warning("لا ملصق ثانٍ: أصل غير معروف أو غير مذكور في جدول cards: %r", origin)
        else:
            badge = card.get("badge")
            if badge:
                badge_bg = hex_rgb(card.get("bg") or cfg.path("brand.accent_color", "#F0B429"))
                badge_fg = hex_rgb(card.get("fg") or cfg.path("brand.primary_color", "#12203A"))

    canvas = Image.new("RGB", (W, H), primary)
    draw = ImageDraw.Draw(canvas)
    margin = int(W * 0.06)

    # المصادر كلها لا مصدرًا واحدًا: هذا هو الموضع الوحيد الذي تُذكر فيه
    # بعد أن رُفعت من متن المنشور، فلا يجوز أن يمثّلها ناشر واحد.
    publishers = ([publisher] if isinstance(publisher, str)
                  else [p for p in (publisher or []) if p])
    publishers = [p for p in publishers if str(p).strip()]

    # ── التخطيط (Issue #1161، يخلف #1158): شريط علوي ← صورة 4:3 بتدرّجين ←
    # عنوان محاذى لليمين ← شريط سفلي، بلا خطوط ذهبية (التدرّجان يلحمان الصورة
    # بما حولها). الشارات صارت فوق أول سطر من العنوان لا في الشريط العلوي.
    # الهندسة كلها في plan_card_layout كي تقيس بها الاختبارات من الدالة نفسها.
    # ترتيب الشارات من اليمين: «عاجل» ثم التصنيف ثم شارة الأصل.
    badge_items = []
    if badge and badge_is_breaking:
        badge_items.append((badge, badge_bg, badge_fg))
    if category:
        badge_items.append((category, accent, primary))
    if badge and not badge_is_breaking:
        badge_items.append((badge, badge_bg, badge_fg))
    plan = plan_card_layout(draw, headline, [t for t, _, _ in badge_items], cfg)
    bar, photo_h, photo_top = plan["bar"], plan["photo_h"], plan["photo_top"]
    head_font, head_lines, line_h = plan["font"], plan["lines"], plan["line_h"]

    # ── 1) الصورة أو البديل: نجرّب المرشحين بالترتيب ──
    candidates = (
        [image_urls] if isinstance(image_urls, str)
        else list(image_urls or [])
    )
    source = None
    illustrative = False
    chosen_url = None
    composite = False
    # تشخيص Issue #373 (البند 1): سبب رفض كل مرشَّح صورة، ليصل تقرير المسودة
    # — لا سجل log وحده الذي لا يراه المراجع البشري
    candidate_failures: list[dict] = []
    fallback_tried = False
    fallback_candidates_count = 0

    # ترتيب حسب الوجوه: الصورة التي تُظهر إنسانًا بوضوح تتصدّر الخلفية،
    # والسياق (مبنى، مكان، وثيقة) يذهب للدائرة. العكس يدفن الوجه — وهو
    # ما يوقف نظر القارئ — في زاوية صغيرة.
    ordered = list(candidates[:6])
    if len(ordered) > 1 and cfg.path("image.prefer_faces", True):
        loaded = [(u, download_image(u)) for u in ordered]
        valid = [(u, img) for u, img in loaded if img is not None]
        if len(valid) > 1:
            scored = [(face_score(img), u, img) for u, img in valid]
            scored.sort(key=lambda t: -t[0])
            if scored[0][0] >= float(cfg.path("image.face_min_ratio", 0.02)):
                ordered = [u for _, u, _ in scored]
                _preloaded.clear()
                _preloaded.update({u: img for _, u, img in scored})
                log.info("رُتّبت الصور بالوجوه: %s",
                         " · ".join(f"{sc:.2f}" for sc, _, _ in scored))

    for url in ordered:
        source = _preloaded.get(url) or download_image(url, failures=candidate_failures)
        if source is not None:
            chosen_url = url
            log.info("اعتُمدت صورة الخبر: %s", url[:90])
            break

    # الدرجة الثانية (Issue #1095، ثم قُلب ترتيبها في Issue #1123): صورة خبر
    # صحفي عن الموضوع نفسه -- تسبق الصورة الحرة الآن، فهي أقرب للحدث دومًا
    # والحرة عامة بطبيعتها (راجع صاحب المشروع أول مقال فاستبدل الحرة يدويًا
    # بصورة خبر). تُجرَّب فقط بعد فشل صورة الناشر، وبلا فحص وجه إطلاقًا (انظر
    # توثيق news_photo_provider أعلى الدالة). خلافًا لخلفية الفيديو الملغاة،
    # تُرسم صورةً رئيسية عادية تمامًا -- تمرّ عبر متغيّر `source` العام
    # فتُعامَل بنفس مسار الرسم أدناه حرفيًا، لا فرع تخطيط منفصل.
    news_photo_used = False
    news_photo_publisher = None
    if source is None and callable(news_photo_provider):
        news_cands = news_photo_provider() or []
        for cand in list(news_cands)[:6]:
            url = cand.get("url") if isinstance(cand, dict) else cand
            if not url:
                continue
            found = download_image(url, failures=candidate_failures)
            if found is not None:
                source = found
                chosen_url = url
                news_photo_used = True
                news_photo_publisher = cand.get("publisher") if isinstance(cand, dict) else None
                log.info("📰 اعتُمدت صورة خبر عن الموضوع: %s", url[:90])
                break

    # الدرجة الثالثة: بديل حر الترخيص، بعد فشل صورة الناشر وصورة الخبر معًا.
    # البحث كسول: لا يُنفَّذ إلا هنا، فلا نضيّع طلبات شبكة على ما نجح أعلاه.
    if source is None:
        alternatives = list(fallback_urls or [])
        if not alternatives and callable(fallback_provider):
            log.info("لا صورة ناشر ولا صورة خبر — البحث عن بديل حر الترخيص…")
            fallback_tried = True
            alternatives = fallback_provider() or []
        fallback_candidates_count = len(alternatives)

        for url in alternatives[:6]:
            source = download_image(url, failures=candidate_failures)
            if source is not None:
                illustrative = True
                log.info("✅ اعتُمدت صورة تعبيرية حرة: %s", url[:90])
                break

    if source is None:
        log.info("❌ لا صورة متاحة (ولا بديل حر) — سيُستخدم التصميم المتدرّج")
    used_original = source is not None and not news_photo_used

    # لا «صورة: {ناشر}» على البطاقة بعد الآن (Issue #1158): مصدر الصورة يبقى
    # داخليًا في report/image_info وreview.image_source_line للمراجع فقط.

    photo = (
        cover(source, W, photo_h) if source
        else placeholder(W, photo_h, primary, accent)
    )
    if source is not None and cfg.path("image.sharpen", True):
        photo = photo.filter(ImageFilter.UnsharpMask(radius=2, percent=55, threshold=3))

    # لا تعتيم غير التدرّجين (Issue #1161): fade_photo وحده يلحم الصورة بالشريط
    # والعنوان. كل ما بعده (الدائرة، quiet_side) يعمل على الصورة الخام نفسها،
    # فتبقى الدائرة المركّبة حادّة فوق التدرّج لا ذائبة معه.
    def paste_photo(img: Image.Image) -> None:
        canvas.paste(fade_photo(
            img, primary,
            float(cfg.path("image.fade_top_ratio", 0.14)),
            float(cfg.path("image.fade_bottom_ratio", 0.30)),
            float(cfg.path("image.fade_power", 1.6))), (0, photo_top))

    paste_photo(photo)

    # صورة ثانية في دائرة — تُستخدم حين يوفّر الخبر أكثر من صورة صالحة
    composite_ok = cfg.path("image.composite", True)
    skip = cfg.path("image.composite_skip_buckets") or []
    if composite_ok and bucket and bucket in skip:
        composite_ok = False
        log.info("القالب المركّب معطّل لتصنيف «%s»", bucket)

    if used_original and composite_ok:
        # الناشر يوفّر غالبًا عدة قصّات من الصورة نفسها بأحجام مختلفة.
        # نقارن البصمة البصرية لا الرابط، وإلا ظهرت الصورة مكررة.
        main_hash = visual_hash(source)
        min_diff = float(cfg.path("image.inset_min_difference", 0.28))
        second = None
        for url in candidates[1:6]:
            if url == chosen_url:
                continue
            found = download_image(url)
            if found is None:
                continue
            diff = visual_distance(main_hash, visual_hash(found))
            if diff < min_diff:
                log.info("تجاهل صورة مكررة بصريًا (فارق %.2f): %s", diff, url[:70])
                continue
            second = found
            break

        # قرار التخطيط: هل نستخدم صورتين؟ وأيّهما في الدائرة؟
        # الموضوع (إنسان ← حيوان ← جسم) للدائرة، والمشهد للخلفية.
        if second is not None:
            from .vision import choose_layout
            layout = choose_layout(source, second, cfg)
            log.info("تخطيط الصور: %s — %s",
                     "صورتان" if layout["composite"] else "صورة واحدة",
                     layout["reason"])
            composite = bool(layout["composite"])
            if not layout["composite"]:
                second = None
            elif layout["swap"]:
                source, second = second, source
                photo = cover(source, W, photo_h)
                if cfg.path("image.sharpen", True):
                    photo = photo.filter(
                        ImageFilter.UnsharpMask(radius=2, percent=55, threshold=3))
                paste_photo(photo)
                draw = ImageDraw.Draw(canvas)

        if second is not None:
            radius = int(W * float(cfg.path("image.inset_ratio", 0.20)))
            margin_in = int(W * 0.05)
            side = (quiet_side(photo, radius, margin_in, margin_in)
                    if cfg.path("image.inset_smart_side", True) else "left")
            cx = (margin_in + radius if side == "left"
                  else W - margin_in - radius)
            circular_inset(
                canvas, second,
                center=(cx, photo_top + margin_in + radius),
                radius=radius, ring=(255, 255, 255), ring_width=max(4, W // 180),
            )
            draw = ImageDraw.Draw(canvas)
            log.info("🖼️ قالب مركّب: صورتان")

    # ── 2) الترويسة: الشعار يمينًا والمعرّف يسارًا، لا شيء في الوسط ──
    # (الشارات انتقلت فوق العنوان، Issue #1161). لا خطوط ذهبية: التدرّجان
    # يلحمان الصورة بالشريط. حدود rectangle في Pillow شاملة، فنطرح 1 كي لا
    # يمسّ الشريط أول صف من الصورة.
    draw.rectangle([0, 0, W, bar - 1], fill=primary)
    bar_mid = bar // 2

    logo_rel = cfg.path("brand.logo")
    if logo_rel:
        logo_file = find_logo(logo_rel)
        if logo_file:
            # ارتفاع الشعار نسبة ثابتة من الشريط؛ brand.logo_scale للريلز وحدها
            if paste_logo_trimmed(
                canvas, logo_file, right=W - margin, center_y=bar_mid,
                height=int(bar * 0.72),
                max_width=int(W * float(cfg.path("brand.logo_max_width", 0.42))),
            ):
                draw = ImageDraw.Draw(canvas)   # إعادة الربط بعد اللصق

    # التاريخ يسارًا في الشريط العلوي (Issue #1167؛ كان في السفلي)، والمعرّف
    # انتقل إلى السفلي.
    ff = load_font(f_body, int(W * 0.024), body_weight)
    date_text = f"{datetime.now(timezone.utc):%Y/%m/%d}"
    draw_text(draw, (margin, bar_mid), date_text, ff, (168, 180, 200), anchor="lm")

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

    # ── 3) الشارات: مجموعة واحدة محاذاة لليمين فوق أول سطر من العنوان ──
    # المواضع من plan_card_layout (حافتها السفلية على مسافة ثابتة من الكتلة).
    # كل شارة تُرسم بجسمها المحسوب لا بارتفاع نصّها وحده، فتتساوى الحواف السفلية.
    for box, (text, bg, fg) in zip(plan["badges"], badge_items):
        draw.rounded_rectangle(
            [box["x0"], box["y0"], box["x1"], box["y1"]],
            radius=(box["y1"] - box["y0"]) // 2, fill=bg)
        draw_text(draw, ((box["x0"] + box["x1"]) // 2, (box["y0"] + box["y1"]) // 2),
                  text, plan["badge_font"], fg, anchor="mm")

    # ── 4) العنوان: محاذى لليمين عند الهامش، متوسط عموديًا في منطقته ──
    # fit_headline لا يقصّ نصًّا أبدًا، فالكتلة تتّسع دائمًا لارتفاع المنطقة.
    # المدّ يُضبط به كل سطر عدا الأخير على عرض المنطقة (Issue #1165).
    draw_headline_lines(
        draw, head_lines, head_font, W - margin, margin,
        plan["block_top"] + line_h // 2, line_h, (255, 255, 255),
        justify=bool(cfg.path("image.title_justify", True)),
        max_k=int(cfg.path("image.kashida_max_per_word", 8)))

    # ── 5) الشريط السفلي: المصدر يمينًا، المعرّف يسارًا ──
    ft_top = H - bar
    draw.rectangle([0, ft_top, W, H], fill=mix(primary, (0, 0, 0), 0.28))
    mid = ft_top + bar // 2
    # المعرّف أبيض ويُرسم LTR كي يُقرأ «@…» لا «…@»؛ لا يستعمل accent بعد الآن.
    if handle:
        draw_text_ltr(draw, (margin, mid), handle, ff, (255, 255, 255), anchor="lm")
        left_w = measure(draw, handle, ff)[0]
    else:
        left_w = 0

    # يمينًا: كل المصادر. المساحة محدودة، فنُسقط الأخير تباعًا حتى
    # تتّسع بدل أن يخرج النص من حدود الصورة أو يركب على ما يساره.
    # الاستبدال بالاسم العربي ثم الحارس على الخط المستعمل فعلًا هنا (ff):
    # كله قبل القياس كي لا يُقاس نص لن يُرسم.
    # التحليل يمرّر مساره سطرًا جاهزًا («تحليل لتغطية …») فيُعرض بلا بادئة
    # «المصدر:» التي تنسب المقال إلى القنوات نقلًا لا قراءةً (Issue #1158).
    prefix = "" if origin == "analysis" else "المصدر: "
    footer_names = drop_unrenderable_names(
        resolve_publisher_names(publishers, cfg), ff)
    if footer_names:
        avail = W - margin * 2 - left_w - int(W * 0.05)
        shown = list(footer_names)
        while shown:
            label = f"{prefix}{'، '.join(shown)}"
            if measure(draw, label, ff)[0] <= avail or len(shown) == 1:
                break
            shown.pop()
        if len(shown) < len(footer_names):
            label = f"{prefix}{'، '.join(shown)} +{len(footer_names) - len(shown)}"
        draw_text(draw, (W - margin, mid), label, ff,
                  (168, 180, 200), anchor="rm")

    if report is not None:
        report["used_original"] = bool(used_original)
        report["illustrative"] = bool(illustrative)
        report["composite"] = bool(composite)
        report["candidates_tried"] = len(ordered)
        report["candidate_failures"] = candidate_failures
        report["fallback_tried"] = fallback_tried
        report["fallback_candidates"] = fallback_candidates_count
        # المرشَّح الذي نجح فعليًا (تشخيص Issue #373، مراجعة بشرية بعد أول
        # نشر، البند 1): بلا هذا، المُستدعي لا يعرف أي مرشَّح من image_urls
        # هو من نجح فعلًا — كان يفترض دومًا أن الأول (image_ranked[0]) هو
        # الفائز، وهو خطأ حين ينجح مرشَّح لاحق (ترتيب الوجوه قد يعيد الترتيب
        # أيضًا) أو حين يأتي image_urls من مجمّع صور بديل (استبعاد إعادة نشر)
        report["chosen_url"] = chosen_url
        # Issue #1095: يميّز صورة الخبر عن الموضوع صراحةً عن كل الحالات
        # الأخرى -- None حين لم تُستعمَل (لا صورة خبر أصلًا، أو صورة
        # رئيسية/تعبيرية حرة نجحت أولًا)، كي لا يُقرأ used_original=False
        # هنا كـ"بلا صورة إطلاقًا" (انظر review.image_source_line).
        report["kind"] = "news_photo" if news_photo_used else None
        report["news_photo_publisher"] = news_photo_publisher if news_photo_used else None

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=90, optimize=True, subsampling=0)
    log.info("الصورة جاهزة: %s (صورة أصلية=%s، أسطر=%d)",
             out_path.name, used_original, len(head_lines))
    return out_path
