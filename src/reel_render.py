"""تركيب الريل: من سيناريو معتمد إلى ملف mp4 بلا نشر (Issue #1381، R3b-1).

يستهلك مسودات `format="reel"` بـ`render_status="queued"` (تنتجها `publish.approve_reel_scripts` بعد go3):
مقاطع حقيقية من يوتيوب بنافذة دقيقة ← صوت الراوي جملةً جملة ← صور مشاهد بأدوات `imaging` نفسها التي ترسم
البطاقات (تشكيل الحروف واتجاهها صحيحان، لا drawtext) ← ffmpeg يجمع المشاهد ثم تمريرة شعار واحدة.
لا نشر ولا قضية مرحلة 3 هنا (R3b-2/R4).

`quote_original` يُقرأ من نقاط المستودع الخاص وقت التركيب فقط ولا يُكتب في `drafts/` ولا في أي سجل.
"""
from __future__ import annotations

import argparse
import logging
import math
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw

from . import imaging, reel_clips, reel_script, store, tts
from .config import MUSIC_DIR, REELS_DIR, load_config

log = logging.getLogger("trendnews.reel_render")

CAIRO = "assets/fonts/Cairo.ttf"
TAJAWAL_XB = "assets/fonts/Tajawal-ExtraBold.ttf"
TAJAWAL_B = "assets/fonts/Tajawal-Bold.ttf"
TAJAWAL_R = "assets/fonts/Tajawal-Regular.ttf"
SAMPLE_DATE = "2099/01/01"


# ───────────────────────────── الاعتماديات القابلة للحقن ─────────────────────────────


def probe_duration(path) -> float | None:
    """مدة ملف وسائط بالثواني من ffmpeg نفسه (لا ffprobe: يكفي ما نحتاجه أصلًا لتركيبه)."""
    try:
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=60)
    except Exception:  # noqa: BLE001 -- غياب المدة يعني الرجوع إلى المقدَّرة لا فشل التركيب
        return None
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def probe_streams(path) -> set[str]:
    """أنواع مسارات ملف وسائط ({"video","audio"}) بـffprobe؛ تعذّر القراءة يرفع فيُعدّ المقطع غير صالح (Issue #1406)."""
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError("ffprobe فشل: " + " ".join((proc.stderr or "").split())[-150:])
    return {ln.strip() for ln in proc.stdout.splitlines() if ln.strip()}


def _detect_faces(clip, fractions) -> tuple[int, int, list[float]]:
    """لقطات من المقطع المنزَّل عند نِسب مدته، ومركز أكبر وجه في كل منها بكاشف imaging.
    يرفع إن تعذّر قراءة المقطع؛ والمستدعي يعود إلى نافذة المنتصف."""
    import io
    dur = probe_duration(clip)
    if not dur:
        raise RuntimeError("مدة المقطع مجهولة")
    centers, size = [], None
    for f in fractions:
        out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{dur * float(f):.2f}", "-i", str(clip),
                              "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                             capture_output=True, timeout=60).stdout
        if not out:
            continue
        img = Image.open(io.BytesIO(out)).convert("RGB")
        size = img.size
        boxes = imaging.face_boxes(img)
        if boxes:
            x, _, w, _ = max(boxes, key=lambda b: b[2] * b[3])
            centers.append(x + w / 2)
    if size is None:
        raise RuntimeError("تعذّر استخراج لقطة")
    return size[0], size[1], centers


def _extract_gray_frames(clip, fractions) -> list:
    """لقطات رمادية من المقطع المنزَّل بمقاسه الأصلي عند نِسب مدته؛ يرفع إن تعذّر أي استخراج
    (الكاشف يعدّ العطل «غطاء» لأنه الأحوط)."""
    import io

    import numpy as np
    dur = probe_duration(clip)
    if not dur:
        raise RuntimeError("مدة المقطع مجهولة")
    out = []
    for f in fractions:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{dur * float(f):.2f}", "-i", str(clip),
                              "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                             capture_output=True, timeout=60).stdout
        if not raw:
            raise RuntimeError("تعذّر استخراج لقطة")
        out.append(np.asarray(Image.open(io.BytesIO(raw)).convert("L")))
    return out


def has_bottom_graphics(frames, crop_x, crop_w, cfg) -> bool:
    """هل في أسفل المقطع شريط أخبار أو لافتة؟ صف «حافة» = نسبة أعمدة نافذة الاقتطاع التي فيها |I(y)−I(y−2)| > grad
    بلغت row_fraction؛ والقرار True إن كان صف واحد حافةً في frame_fraction فأكثر من الإطارات. الشريط ثابت المكان
    في كل اللقطات، أما حواف المشهد فتتحرك. أي عطل في القراءة ← True (الأحوط: غطاء)."""
    try:
        import numpy as np
        dcfg = cfg.path("reel.render.band.cover_detect") or {}
        grad, row_frac = float(dcfg.get("grad", 25)), float(dcfg.get("row_fraction", 0.7))
        frame_frac = float(dcfg.get("frame_fraction", 0.8))
        top_frac = int(cfg.path("reel.render.band.top")) / int(cfg.path("reel.render.height"))
        if not frames:
            return True
        counts = None
        for fr in frames:
            g = np.asarray(fr, dtype=np.int16)
            if g.ndim != 2:
                return True
            h, w = g.shape
            cw = int(crop_w) if crop_w else int(h * 9 / 16)
            x0 = int(crop_x) if crop_x is not None else (w - cw) // 2
            y0 = max(2, int(h * top_frac))
            diff = np.abs(g[y0:, x0:x0 + cw] - g[y0 - 2:-2, x0:x0 + cw]) > grad
            edge = (diff.mean(axis=1) >= row_frac).astype(int)
            counts = edge if counts is None else counts + edge
        return bool(counts.max() / len(frames) >= frame_frac)
    except Exception as exc:  # noqa: BLE001 -- الكاشف تحسين: العطل ← غطاء
        log.warning("تعذّر كشف شريط الأسفل فالغطاء: %s", str(exc)[:100])
        return True


def detect_cover(clip_file, crop_x, crop_w, cfg, extractor) -> bool:
    """لقطات samples عند ((k+0.5)/samples) من المدة بدالة الاستخراج ثم الكاشف؛ عطل الاستخراج ← True."""
    try:
        n = max(1, int(cfg.path("reel.render.band.cover_detect.samples", 6)))
        return has_bottom_graphics(extractor(clip_file, [(k + 0.5) / n for k in range(n)]), crop_x, crop_w, cfg)
    except Exception as exc:  # noqa: BLE001
        log.warning("تعذّر استخراج لقطات الكاشف فالغطاء: %s", str(exc)[:100])
        return True


def crop_window(src_w: int, src_h: int, centers: list, mode: str = "face") -> dict:
    """نافذة اقتطاع عرضها ارتفاع_المصدر×9÷16: تتوسّط وسيط مراكز الوجوه وتُحصر في حدود الصورة،
    ولا وجه (أو mode=center) ← المنتصف. {w, x, source}"""
    w = int(src_h * 9 / 16)
    if mode == "face" and centers:
        cs = sorted(centers)
        mid = cs[len(cs) // 2] if len(cs) % 2 else (cs[len(cs) // 2 - 1] + cs[len(cs) // 2]) / 2
        return {"w": w, "h": src_h, "x": int(max(0, min(mid - w // 2, src_w - w))), "source": "face"}
    return {"w": w, "h": src_h, "x": (src_w - w) // 2, "source": "center"}


def _run(cmd: list[str], timeout: int = 600) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = " ".join(reel_clips.scrub_text(proc.stderr or "").split())[-300:]
        raise RuntimeError(f"ffmpeg فشل ({proc.returncode}): {tail}")


@dataclass
class Deps:
    """كل ما يلمس الشبكة أو العملية الخارجية؛ الحقل الفارغ يُملأ بالحقيقي في `resolved` والاختبارات تحقن مزيَّفات."""
    fetch_transcript: Callable[[str], str | None] | None = None
    download_clip: Callable[..., dict] | None = None
    synthesize: Callable[[str, str], dict] | None = None
    diacritize: Callable[[str], tuple[str, str | None]] | None = None
    run: Callable[[list], None] | None = None
    probe: Callable[[Any], float | None] | None = None
    load_points: Callable[[str], list[dict]] | None = None
    comment: Callable[[int, str], None] | None = None
    # (ملف المقطع، نِسب العيّنات) ← (عرض المصدر، ارتفاعه، مراكز أكبر وجه أفقيًا لكل لقطة فيها وجه)
    faces: Callable[[Any, list], tuple[int, int, list[float]]] | None = None
    # انتظار بين إعادات التنزيل؛ حقن الاختبار يمنع الانتظار الحقيقي
    sleep: Callable[[float], None] | None = None
    # أنواع مسارات الملف؛ مقطع بلا صورة أو بلا صوت لا يُقبل (Issue #1406)
    streams: Callable[[Any], set] | None = None
    # (ملف المقطع، نِسب اللقطات) ← إطارات رمادية (مصفوفات) بمقاس المصدر لكاشف شريط الأسفل (Issue #1408)
    frames: Callable[[Any, list], list] | None = None
    # رابط ← صورة خلفية الراوي منزَّلة (أو None) بقواعد imaging.download_image؛ ومزوّدات اختيارها (Issue #1411)
    bg_image: Callable[[str], Any] | None = None
    bg_providers: dict | None = None

    def resolved(self, cfg) -> "Deps":
        def fetch(video_id):
            from . import proxy_config, youtube_extract
            text, _info, _ = youtube_extract.fetch_transcript(video_id, proxy_config.get_proxy_config())
            return text

        def download(video_id, start, end, height, out_path):
            from . import proxy_config
            pc = proxy_config.get_proxy_config()
            return reel_clips.download_clip(video_id, start, end, height, out_path, pc.url if pc else None)

        def points(date):
            from . import youtube_cluster
            return youtube_cluster.prepare_window_points(date, cfg)[0]

        def comment(issue, text):
            from . import review
            review.comment(issue, text)

        timeout = int(cfg.path("reel.render.ffmpeg_timeout", 600))
        return replace(
            self,
            fetch_transcript=self.fetch_transcript or fetch,
            download_clip=self.download_clip or download,
            synthesize=self.synthesize or (lambda text, voice: tts.synthesize(text, voice, cfg)),
            diacritize=self.diacritize or (lambda text: tts.diacritize(text, cfg)),
            run=self.run or (lambda cmd: _run(cmd, timeout)),
            probe=self.probe or probe_duration,
            load_points=self.load_points or points,
            faces=self.faces or _detect_faces,
            sleep=self.sleep or time.sleep,
            streams=self.streams or probe_streams,
            frames=self.frames or (lambda clip, fractions: _extract_gray_frames(clip, fractions)),
            bg_image=self.bg_image or (lambda url: imaging.download_image(url)),
            comment=self.comment or comment)


# ───────────────────── صورة خلفية الراوي (Issue #1411، R3b-2b) ─────────────────────


def _default_providers() -> dict:
    """المزوّدات الحقيقية؛ دالة لا ثابت كي يستبدلها الاختبار فتبقى الخلفية الكحلية في كل اختبار لا يحقن مزوّدات."""
    from . import imagesearch, youtube_extract
    return {"news": youtube_extract.news_photo_candidates, "web": imagesearch.search_web_images,
            "free": youtube_extract.photo_candidates, "download": lambda url: imaging.download_image(url)}


def pick_background(draft: dict, cfg, providers: dict | None = None) -> dict:
    """يختار صورة خلفية الراوي بسلّم كسول: يدوية ← صورة خبر ← بحث ويب ← حرة (بحارس الوجه القائم) ← لا شيء.
    لا تُستدعى درجة إن نجحت السابقة؛ المرشّح يُقبل إن نجح تنزيله فقط. يعيد {url, kind, publisher} والرابط وحده لا الملف.
    عطل أي مزوّد يُسجَّل ويُنتقل إلى الدرجة التالية، فالاختيار لا يرفع أبدًا."""
    pv = {**_default_providers(), **(providers or {})}
    manual = (draft.get("manual_image") or "").strip()
    if manual:
        return {"url": manual, "kind": "manual", "publisher": ""}
    tries = int(cfg.path("reel.render.background.max_tries", 5))
    title = draft.get("title") or (draft.get("script") or {}).get("title", "")
    event = draft.get("event") or ""
    query_en = draft.get("image_query_en")
    if not query_en and draft.get("sibling_id"):
        try:
            found = store.load_draft(draft["sibling_id"])
            query_en = (found[1].get("image_query_en") if found else None)
        except Exception as exc:  # noqa: BLE001 -- عبارة البحث تحسين لا شرط
            log.warning("تعذّرت قراءة المقال الشقيق لعبارة الصورة: %s", str(exc)[:100])

    def usable(url: str) -> bool:
        try:
            return bool(url) and pv["download"](url) is not None
        except Exception as exc:  # noqa: BLE001
            log.warning("تعذّر تنزيل مرشّح الخلفية: %s", str(exc)[:100])
            return False

    def safe(name, call):
        try:
            return call() or []
        except Exception as exc:  # noqa: BLE001 -- مزوّد معطّل لا يُسقط الاختيار
            log.warning("مزوّد صور الخلفية %s فشل: %s", name, str(exc)[:100])
            return []

    for cand in safe("news", lambda: pv["news"](title, event, cfg, query_en))[:tries]:
        if usable(cand.get("url", "")):
            return {"url": cand["url"], "kind": "news_photo", "publisher": cand.get("publisher", "")}
    state: dict = {}
    for cand in safe("web", lambda: pv["web"](query_en or title, cfg, state))[:tries]:
        if usable(cand.get("url", "")):
            return {"url": cand["url"], "kind": "web_search", "publisher": cand.get("domain", "")}
    for url in safe("free", lambda: pv["free"](title, event, cfg, query_en))[:tries]:
        if usable(url):
            return {"url": url, "kind": "free", "publisher": ""}
    return {"url": "", "kind": "none", "publisher": ""}


def prepare_background(cfg, img: Image.Image) -> dict:
    """يحوّل الصورة المنزَّلة إلى طبقة خلفية 1080×1920 مظلَّلة ويقرّر الشكل منها: (ب) إن أعاد الكشف وجهًا مساحته
    ≥ image.face_min_ratio من مساحة الصورة وإلا (أ). الاقتطاع الأفقي يتوسّط مراكز الوجوه كاقتطاع المقاطع، وإلا المنتصف.
    يعيد {"layout": "A"|"B", "image": RGB}."""
    b = cfg.path("reel.render.background")
    w, h = int(cfg.path("reel.render.width")), int(cfg.path("reel.render.height"))
    img = img.convert("RGB")
    iw, ih = img.size
    try:
        faces = imaging.face_boxes(img)
    except Exception as exc:  # noqa: BLE001 -- الكشف تحسين لا شرط
        log.warning("تعذّر كشف الوجوه في خلفية الراوي: %s", str(exc)[:100])
        faces = []
    ratio = float(cfg.path("image.face_min_ratio", 0.02))
    layout = "B" if any(fw * fh >= ratio * iw * ih for _, _, fw, fh in faces) else "A"
    scale = max(w / iw, h / ih)
    sw, sh = max(w, round(iw * scale)), max(h, round(ih * scale))
    cx = sum(x + fw / 2 for x, _, fw, _ in faces) / len(faces) if faces else iw / 2
    left = min(max(round(cx * scale - w / 2), 0), sw - w)
    top = (sh - h) // 2
    out = img.resize((sw, sh), Image.LANCZOS).crop((left, top, left + w, top + h))
    navy = imaging.hex_rgb(cfg.path("brand.primary_color"))
    out = Image.blend(out, Image.new("RGB", out.size, navy), float(b["shade_a"] if layout == "A" else b["shade_b"]))
    if layout == "B":
        bx0, bx1, by0, by1 = 36, w - 36, int(b["box_top"]), int(b["box_bottom"])
        region = out.crop((bx0, by0, bx1, by1))
        out.paste(Image.blend(region, Image.new("RGB", region.size, navy), float(b["box_alpha"])), (bx0, by0))
        ImageDraw.Draw(out).rectangle((bx0, by0, bx1 - 1, by0 + int(b["gold_px"]) - 1),
                                      fill=imaging.hex_rgb(cfg.path("brand.accent_color")))
    return {"layout": layout, "image": out}


def outro_credit(cfg, bg: dict | None) -> str:
    """نص سطر مصدر الصورة المستقل تحت «المقاطع من» في الختام: «الصورة: الناشر» لصورة الخبر وبحث الويب (الناشر بالعربية
    عبر publisher_ar حين له مقابل)، و«صورة تعبيرية» للحرة؛ لا شيء لـnone ولا manual (ولا حين لم تُستعمل صورة أصلًا)."""
    from .important_write import publisher_ar  # متأخر: important_write يستورد وحدات أثقل
    t = cfg.path("reel.render.texts")
    kind, publisher = (bg or {}).get("kind"), (bg or {}).get("publisher", "")
    if kind in ("news_photo", "web_search") and publisher:
        return t["bg_credit_publisher"].format(publisher=publisher_ar(publisher, cfg))
    if kind == "free":
        return t["bg_credit_free"]
    return ""


# ───────────────────────────── رسم الإطارات ─────────────────────────────


_INVISIBLE = {0x200C, 0x200D, 0x200E, 0x200F, 0x061C}


def _lacks(text: str, font) -> bool:
    """هل في النص حرف مرئي غائب من خريطة رموز الخط؟ خط لا تُقرأ خريطته يُعدّ كافيًا."""
    cps = imaging._font_codepoints(font)
    if cps is None:
        return False
    return any(not c.isspace() and ord(c) not in cps and ord(c) not in _INVISIBLE for c in text)


def pick_font(text: str, path: str, size: int, weight: str | None = None):
    """الخط المطلوب إن غطّى كل حروف النص وإلا Cairo؛ وإن بقي ناقصًا None فلا يُرسم مربع أبدًا."""
    font = imaging.load_font(path, size, weight)
    if not _lacks(text, font):
        return font
    alt = imaging.load_font(CAIRO, size, "Bold")
    if not _lacks(text, alt):
        return alt
    log.warning("نص بحروف غائبة من كل الخطوط لم يُرسم: %r", text[:40])
    return None


class _Pen:
    """لوحة 1080×1920 ترسم نصًا عربيًا بأدوات imaging وتسجّل صندوق كل نص لفحص المنطقة الآمنة."""

    def __init__(self, cfg, boxes: list | None, transparent: bool = False):
        r = cfg.path("reel.render")
        self.w, self.h = int(r["width"]), int(r["height"])
        self.navy = imaging.hex_rgb(cfg.path("brand.primary_color"))
        self.gold = imaging.hex_rgb(cfg.path("brand.accent_color"))
        self.white = (255, 255, 255)
        self.img = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0) if transparent else self.navy + (255,))
        self.d = ImageDraw.Draw(self.img)
        self.boxes = boxes if boxes is not None else []
        # الحدّ الأيمن للنص يحجز عمود الأزرار على يمين الشاشة؛ والأيسر هامش متماثل
        self.x1 = self.w - int(r["safe"]["right_col_width"])
        self.x0 = 60
        self.cx = (self.x0 + self.x1) // 2
        self.max_w = self.x1 - self.x0

    def font(self, path: str, size: int, weight: str | None = None):
        return imaging.load_font(path, size, weight)

    def ink(self, text: str, font, xy, anchor: str, ltr: bool = False) -> tuple:
        """صندوق الحبر الفعلي لنص يُرسم عند xy بالمرساة نفسها (النص المحضَّر والخيارات نفسها كالرسم).
        التقدّم بـsize×1.45 من نقطة الرسم لا من الحبر هو ما أخفى تداخل الشريط السفلي عن اختبار المنطقة الآمنة."""
        if ltr:
            kw = {"direction": "ltr", "language": "en"} if imaging.HAS_RAQM else {}
            return self.d.textbbox(xy, text, font=font, anchor=anchor, **kw)
        return self.d.textbbox(xy, imaging._prepare(text), font=font, anchor=anchor, **imaging._kwargs())

    def line(self, text: str, font, fill, y: int, *, align: str = "center", ltr: bool = False) -> int:
        """سطر واحد؛ يعيد y التالي. المحاذاة وسطية أو يمينية عند الحدّ الآمن."""
        _, h = imaging.measure(self.d, text, font)
        lh = int(font.size * 1.45) if hasattr(font, "size") else h
        xy, anchor = ((self.cx, y), "ma") if align == "center" else ((self.x1, y), "ra")
        if ltr:
            imaging.draw_text_ltr(self.d, xy, text, font, fill, anchor=anchor)
        else:
            imaging.draw_text(self.d, xy, text, font, fill, anchor=anchor)
        self.boxes.append(tuple(self.ink(text, font, xy, anchor, ltr)))
        return y + lh

    def ink_line(self, text: str, font_path: str, weight: str | None, size: int, fill, *, prev_bottom: int,
                 gap: int, limit: int, min_size: int | None = None, ltr: bool = False) -> int | None:
        """سطر يمينيّ يوضع بحبره: أعلى حبره = prev_bottom + gap، ويُصغَّر بخطوة 2 حتى min_size إن تجاوز حبره limit.
        يعيد أسفل حبره، أو None (مع تحذير) إن لم يسعه الحدّ أو غاب حرفه من كل الخطوط."""
        for sz in range(size, (min_size if min_size is not None else size) - 1, -2):
            font = pick_font(text, font_path, sz, weight)
            if font is None:
                return None
            top0, bottom0 = self.ink(text, font, (self.x1, 0), "ra", ltr)[1::2]
            y = prev_bottom + gap - top0
            if y + bottom0 <= limit:
                return self.line_at(text, font, fill, y, ltr)
        log.warning("سطر لا يسع الشريط السفلي فحُذف: %r", text[:40])
        return None

    def line_at(self, text: str, font, fill, y: int, ltr: bool) -> int:
        self.line(text, font, fill, y, align="right", ltr=ltr)
        return int(self.boxes[-1][3])

    def text_line(self, text: str, font_path: str, weight: str | None, size: int, fill, y: int, *,
                  align: str = "center", ltr: bool = False) -> int:
        """سطر بحارس الخط: ينتقل إلى Cairo عند حرف غائب، ويُحذف السطر إن بقي ناقصًا. يعيد y التالي."""
        font = pick_font(text, font_path, size, weight)
        if font is None:
            return y
        return self.line(text, font, fill, y, align=align, ltr=ltr)

    def block(self, text: str, font_path: str, weight: str | None, fill, y_mid: int, *, start: int, minimum: int,
              max_lines: int = 8, align: str = "center", y_top: int | None = None) -> int:
        """نص متعدد الأسطر يُصغَّر ليسع العرض الآمن؛ يتمركز رأسيًا حول y_mid (أو يبدأ من y_top)."""
        font, lines, lh = imaging.fit_text(self.d, text, font_path, self.max_w, max_lines, start, minimum, weight)
        total = lh * len(lines)
        safe = self._safe()
        y = y_top if y_top is not None else int(y_mid - total / 2)
        y = max(safe[0], min(y, safe[1] - total))
        for ln in lines:
            xy, anchor = ((self.cx, y), "ma") if align == "center" else ((self.x1, y), "ra")
            imaging.draw_text(self.d, xy, ln, font, fill, anchor=anchor)
            self.boxes.append(tuple(self.ink(ln, font, xy, anchor)))
            y += lh
        return y

    def typed_block(self, text: str, prefix: str, font_path: str, weight: str | None, fill, y_mid: int, *, start: int,
                    minimum: int, max_lines: int = 8) -> None:
        """block وسطيّ بالتخطيط نفسه (حجم الخط وتقسيم الأسطر من الجملة كاملة) لكن يُرسم منه ما كُتب حتى prefix.
        الحروف لا تتحرك: السطر الجزئي يُحاذى بحافة حبره اليمنى عند حافة السطر نفسه مكتملًا، ولا يبدأ سطر قبل اكتمال سابقه.
        العدّ بالحروف غير المسافة لأن prefix قد تتغير مسافاته، وتقسيم الأسطر لا يغيّر الحروف نفسها."""
        font, lines, lh = imaging.fit_text(self.d, text, font_path, self.max_w, max_lines, start, minimum, weight)
        total = lh * len(lines)
        safe = self._safe()
        y = max(safe[0], min(int(y_mid - total / 2), safe[1] - total))
        shown = sum(1 for c in prefix if not c.isspace())
        for ln in lines:
            if shown <= 0:
                break
            n = sum(1 for c in ln if not c.isspace())
            full_xy = (self.cx, y)
            if shown >= n:
                imaging.draw_text(self.d, full_xy, ln, font, fill, anchor="ma")
                self.boxes.append(tuple(self.ink(ln, font, full_xy, "ma")))
            else:
                seen, cut = 0, len(ln)
                for i, c in enumerate(ln):
                    seen += 0 if c.isspace() else 1
                    if seen == shown:
                        cut = i + 1
                        break
                part = ln[:cut]
                right = self.ink(ln, font, full_xy, "ma")[2]
                # الحبر الفعلي لا نقطة المرساة هو ما يُطابَق: حرف أول السطر قد يتغيّر انحناؤه بين الجزئي والكامل
                right_now = self.ink(part, font, (right, y), "ra")[2]
                xy = (right + (right - right_now), y)
                imaging.draw_text(self.d, xy, part, font, fill, anchor="ra")
                self.boxes.append(tuple(self.ink(part, font, xy, "ra")))
                break
            shown -= n
            y += lh

    def _safe(self) -> tuple[int, int]:
        return 230, 1480

    def rule(self, y: int, width: int = 320) -> None:
        self.d.rectangle((self.cx - width // 2, y, self.cx + width // 2, y + 6), fill=self.gold)

    def rgb(self) -> Image.Image:
        return self.img.convert("RGB")


def frame_title(cfg, title: str, date_text: str, boxes=None) -> Image.Image:
    p = _Pen(cfg, boxes)
    r = cfg.path("reel.render")
    badge = r.get("badge_text", "تحليل")
    bfont = p.font(CAIRO, 54, "Black")
    bw, bh = imaging.measure(p.d, badge, bfont)
    top = 520
    p.d.rounded_rectangle((p.cx - bw // 2 - 40, top, p.cx + bw // 2 + 40, top + bh + 50), radius=28,
                          fill=imaging.hex_rgb(r.get("badge_bg", "#8EC5FF")))
    p.line(badge, bfont, p.navy, top + 14)
    y = p.block(title, CAIRO, "Black", p.white, 0, start=96, minimum=52, max_lines=6, y_top=top + bh + 110)
    p.rule(y + 30)
    y = p.line(date_text, p.font(TAJAWAL_B, 44), p.gold, y + 70)
    p.line(cfg.path("brand.handle") or "@almujez", p.font(TAJAWAL_B, 44), p.white, y + 10, ltr=True)
    return p.rgb()


def _narration_pen(cfg, sentence: str, boxes, bg: dict | None):
    """لوحة الراوي ومعاملات نصها. بلا خلفية: القيم الأصلية حرفيًا (كحلي، وسط الشاشة). (أ): الصورة المظلَّلة والنص
    كما هو. (ب): النص في الصندوق السفلي بأكبر حجم ≤ text_start يسعه أربعة أسطر داخل ارتفاع الصندوق؛ التخطيط من الجملة
    كاملة فلا يتحرك سطر بين إطارات الكتابة."""
    p = _Pen(cfg, boxes)
    if bg is None:
        return p, dict(y_mid=860, start=72, minimum=40, max_lines=8)
    p.img = bg["image"].convert("RGBA")
    p.d = ImageDraw.Draw(p.img)
    if bg["layout"] != "B":
        return p, dict(y_mid=860, start=72, minimum=40, max_lines=8)
    b = cfg.path("reel.render.background")
    top, bottom = int(b["box_top"]) + int(b["gold_px"]), int(b["box_bottom"])
    avail = bottom - top - 2 * int(b["pad"])
    lo, lines = int(b["text_min"]), int(b["text_lines"])
    size = int(b["text_start"])
    while True:
        font, wrapped, lh = imaging.fit_text(p.d, sentence, TAJAWAL_XB, p.max_w, lines, size, lo, None)
        if lh * len(wrapped) <= avail or size <= lo:
            break
        size -= 2
    if len(imaging.wrap(p.d, sentence, font, p.max_w)) > lines:
        log.warning("جملة الراوي أطول من أسطر الصندوق السفلي فقُصّت: %r", sentence[:40])
    return p, dict(y_mid=(top + bottom) // 2, start=size, minimum=lo, max_lines=lines)


def frame_narration(cfg, sentence: str, boxes=None, bg: dict | None = None) -> Image.Image:
    p, kw = _narration_pen(cfg, sentence, boxes, bg)
    p.block(sentence, TAJAWAL_XB, None, p.white, kw["y_mid"], start=kw["start"], minimum=kw["minimum"],
            max_lines=kw["max_lines"])
    return p.rgb()


def frame_narration_typed(cfg, sentence: str, prefix: str, boxes=None, bg: dict | None = None) -> Image.Image:
    """إطار الراوي وقد كُتب من الجملة ما قبل prefix. الجملة كاملة ← frame_narration نفسه بالبكسل."""
    if sum(1 for c in prefix if not c.isspace()) >= sum(1 for c in sentence if not c.isspace()):
        return frame_narration(cfg, sentence, boxes, bg)
    p, kw = _narration_pen(cfg, sentence, boxes, bg)
    p.typed_block(sentence, prefix, TAJAWAL_XB, None, p.white, kw["y_mid"], start=kw["start"], minimum=kw["minimum"],
                  max_lines=kw["max_lines"])
    return p.rgb()


def typewriter_steps(text: str, speech_seconds: float, hold_seconds: float, fps: float) -> list[tuple[str, float]]:
    """خطوات الكتابة حرفًا حرفًا: [(البادئة، المدة)]. الحرف k من N (غير المسافة) يظهر عند k/N من speech_seconds،
    والمسافة تظهر مع الحرف الذي يليها. أول خطوة بادئتها فارغة (يمتد معها صمت الانتقال)، وآخر خطوة النص كاملًا تبقى
    hold_seconds. لا خطوة أقصر من إطار: الأحرف التي تقع في إطار واحد تُدمج فيظهر آخرها. المجموع = speech + hold."""
    text = text.strip()
    frame = 1.0 / fps
    speech = max(float(speech_seconds), 0.0)
    hold = max(float(hold_seconds), frame)
    idx = [i for i, c in enumerate(text) if not c.isspace()]
    if not idx or speech < frame:
        return [(text, speech + hold)]
    n = len(idx)
    groups: dict[int, str] = {}
    for k, i in enumerate(idx, 1):
        # أول حرف لا يسبق الإطار الأول كي تبقى الخطوة الفارغة بمدة إطار على الأقل
        groups[max(1, round(k / n * speech * fps))] = text[: i + 1]
    ordered = sorted(groups.items())
    starts = [0.0] + [f / fps for f, _ in ordered]
    prefixes = [""] + [p for _, p in ordered]
    starts[-1] = speech        # النص الكامل يظهر عند نهاية الكلام تمامًا لا عند أقرب إطار
    for i in range(len(starts) - 2, 0, -1):
        if starts[i + 1] - starts[i] < frame - 1e-9:
            del starts[i], prefixes[i]
    durs = [starts[i + 1] - starts[i] for i in range(len(starts) - 1)] + [hold]
    return list(zip(prefixes, durs))


def frame_question(cfg, question: str, boxes=None) -> Image.Image:
    p = _Pen(cfg, boxes)
    r = 120
    cy = 520
    p.d.ellipse((p.cx - r, cy - r, p.cx + r, cy + r), fill=p.gold)
    qfont = p.font(CAIRO, 170, "Black")
    qw, qh = imaging.measure(p.d, "؟", qfont)
    imaging.draw_text(p.d, (p.cx, cy - qh // 2 - 26), "؟", qfont, p.navy, anchor="ma")
    p.block(question, CAIRO, "Black", p.white, 930, start=76, minimum=44)
    p.line(cfg.path("reel.render.texts.share"), p.font(TAJAWAL_B, 46), p.gold, 1250)
    return p.rgb()


def frame_outro(cfg, channels: str, boxes=None, credit: str = "") -> Image.Image:
    p = _Pen(cfg, boxes)
    t = cfg.path("reel.render.texts")
    y = p.line(t["follow"], p.font(CAIRO, 112, "Black"), p.white, 560)
    p.rule(y + 10)
    y = p.block(t["tagline"], TAJAWAL_B, None, p.white, 0, start=52, minimum=36, max_lines=3, y_top=y + 60)
    p.line(cfg.path("brand.handle") or "@almujez", p.font(TAJAWAL_B, 54), p.gold, y + 20, ltr=True)
    y = p.block(t["clips_from"].format(channels=channels), TAJAWAL_R, None, (200, 208, 224), 0, start=36, minimum=26,
                max_lines=4, y_top=1180)
    if credit:
        _credit_line(p, cfg, credit, y)
    return p.rgb()


def _credit_line(p: "_Pen", cfg, credit: str, y: int) -> None:
    """سطر مصدر الصورة المستقل بخط سطر «المقاطع من» نفسه، يُصغَّر حتى يسع عرض النص الآمن فلا يُقسم أبدًا.
    اسم لاتيني بقي بلا مقابل عربي (نطاق موقع) يُرسم وحده LTR ملاصقًا لـ«الصورة:» على يسارها: سطر bidi واحد يقلب النقاط
    والشرطات في النطاق."""
    label, _, name = credit.partition(": ")
    latin = bool(name) and bool(re.search(r"[A-Za-z]", name)) and not re.search(r"[؀-ۿ]", name)
    fill = (200, 208, 224)
    for size in range(36, 15, -2):
        font = p.font(TAJAWAL_R, size)
        if not latin:
            if imaging.measure(p.d, credit, font)[0] <= p.max_w:
                p.line(credit, font, fill, y)
                return
            continue
        lw = p.ink(label + ":", font, (0, 0), "la")
        nw = p.ink(name, font, (0, 0), "la", True)
        gap = max(size // 4, 6)
        total = (lw[2] - lw[0]) + gap + (nw[2] - nw[0])
        if total <= p.max_w:
            right = p.cx + total // 2
            imaging.draw_text(p.d, (right, y), label + ":", font, fill, anchor="ra")
            p.boxes.append(tuple(p.ink(label + ":", font, (right, y), "ra")))
            xy = (right - (lw[2] - lw[0]) - gap, y)
            imaging.draw_text_ltr(p.d, xy, name, font, fill, anchor="ra")
            p.boxes.append(tuple(p.ink(name, font, xy, "ra", True)))
            return
    log.warning("سطر مصدر الصورة لا يسع الشاشة فحُذف: %r", credit[:40])


def frame_clip_overlay(cfg, scene: dict, boxes=None) -> Image.Image:
    """الطبقتان مدموجتان في صورة شفافة واحدة (الشكل النهائي الثابت للشريط بعد انتهاء حركته)."""
    static, band = frame_clip_layers(cfg, scene, boxes)
    return Image.alpha_composite(static, band)


def frame_clip_layers(cfg, scene: dict, boxes=None, cover: bool | None = None) -> tuple[Image.Image, Image.Image]:
    """طبقتان شفافتان بحجم الشاشة (Issue #1400): الثابتة (صندوق الترجمة والغطاء الكحلي المعتم من أسفل الشريط)
    وطبقة الشريط (المستطيل والحافة الذهبية والنصوص) التي تدخل متحركة من اليمين. الغطاء يخفي شريط القناة الأصلية
    المقصوص؛ شفافية 0.94 أبقته ظاهرًا باهتًا فهو معتم تمامًا."""
    st = _Pen(cfg, boxes, transparent=True)
    bd = _Pen(cfg, st.boxes, transparent=True)
    p = st
    band = cfg.path("reel.render.band")
    top, height, edge = int(band["top"]), int(band["height"]), int(band["edge"])
    # cover: true/false ثابتان كما كانا (شفافية الشريط من الإعداد)؛ auto: القرار للمقطع (cover) فالمعتم تمامًا مع الغطاء،
    # وبلا قرار مُمرَّر يُفترض الغطاء (الأحوط)
    mode = band.get("cover")
    if mode is True or mode is False:
        use_cover, opaque = mode, False
    else:
        use_cover = True if cover is None else bool(cover)
        opaque = use_cover
    navy_a = p.navy + (255 if opaque else round(255 * float(band["alpha"])),)
    if use_cover:
        # الصف top+height للشريط نفسه، فيبدأ الغطاء بعده
        st.d.rectangle((0, top + height + 1, st.w, st.h), fill=st.navy + (255,))
    bd.d.rectangle((0, top, bd.w, top + height), fill=navy_a)
    bd.d.rectangle((bd.w - edge, top, bd.w, top + height), fill=bd.gold + (255,))
    quote = (scene.get("quote_arabic") or "").strip()
    if quote:
        font, lines, lh = imaging.fit_text(p.d, quote, TAJAWAL_B, p.max_w, 3, 46, 30, None)
        box_h = lh * len(lines) + 36
        by = top - 24 - box_h
        p.d.rectangle((p.x0 - 24, by, p.x1 + 24, by + box_h), fill=(8, 14, 28, 175))
        y = by + 18
        for ln in lines:
            w, h = imaging.measure(p.d, ln, font)
            imaging.draw_text(p.d, (p.cx, y), ln, font, p.white, anchor="ma")
            p.boxes.append((p.cx - w / 2, y, p.cx + w / 2, y + int(lh * 0.8)))
            y += lh
    p = bd
    verified = scene.get("speaker_verified") and scene.get("speaker_name")
    channel = scene.get("channel_display", "")
    y = top + 30
    if verified:
        n0 = len(p.boxes)
        p.text_line(scene["speaker_name"], CAIRO, "Black", 56, p.white, y, align="right")
        # كل سطر بعد الأول يوضع بحبره: أعلى حبره = أسفل حبر السابق + line_gap، فلا يتداخل سطران أبدًا
        bottom = int(p.boxes[-1][3]) if len(p.boxes) > n0 else y
        gap, limit = int(band.get("line_gap", 12)), top + height - 16
        if scene.get("speaker_name_latin"):
            # بـCairo لأن Tajawal يفتقد ş ğ İ
            nb = p.ink_line(scene["speaker_name_latin"], CAIRO, "Bold", 34, p.gold, prev_bottom=bottom, gap=gap,
                            limit=limit, ltr=True)
            bottom = bottom if nb is None else nb
        role_line = " · ".join(x for x in (scene.get("speaker_role", ""), channel) if x)
        if role_line:
            p.ink_line(role_line, TAJAWAL_B, None, 40, (214, 222, 238), prev_bottom=bottom, gap=gap, limit=limit,
                       min_size=30)
    else:
        label = cfg.path("reel.texts.guest_label", "ضيف على قناة {channel}").format(channel=channel)
        p.line(label, p.font(CAIRO, 52, "Black"), p.white, top + 80, align="right")
    return st.img, bd.img


def layout_boxes(cfg) -> list[tuple]:
    """صناديق كل النصوص في كل أنواع الإطارات بنصوص طويلة تمثيلية، لفحص المنطقة الآمنة في الاختبار."""
    boxes: list = []
    long_text = " ".join(["كلمة"] * 40)
    frame_title(cfg, long_text, SAMPLE_DATE, boxes)
    frame_narration(cfg, long_text, boxes)
    frame_question(cfg, long_text, boxes)
    frame_outro(cfg, "الجزيرة، العربية، CNN Türk", boxes)
    base = {"quote_arabic": long_text, "channel_display": "قناة طويلة الاسم جدًا للتجربة"}
    frame_clip_overlay(cfg, base, boxes)
    frame_clip_overlay(cfg, {**base, "speaker_verified": True, "speaker_name": "الاسم العربي الكامل للمتحدث",
                             "speaker_name_latin": "Full Latin Name", "speaker_role": "محلل سياسي"}, boxes)
    return boxes


# ───────────────────────────── التركيب ─────────────────────────────


def _enc(rcfg: dict) -> list[str]:
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(rcfg.get("crf", 22)), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", str(rcfg.get("audio_rate", 48000)), "-ac", "2"]


def _base(*args) -> list[str]:
    return ["ffmpeg", "-y", "-loglevel", "error", *args]


def _loudnorm(cfg) -> str:
    """مرشح توحيد الصوت أحادي المرور؛ الهدف والذروة من الإعداد. LRA ثابت 11 (القيمة الافتراضية للمرشح نفسه)."""
    lc = cfg.path("reel.render.loudness")
    return f"loudnorm=I={lc['target_lufs']}:TP={lc['true_peak']}:LRA=11"


def _fmt(x: float) -> str:
    return f"{x:.3f}"


def pick_music(draft: dict, cfg) -> str | None:
    """اسم مقطوعة الريل (Issue #1413): تناوب بالاسم بعد مقطوعة آخر ريل مُركَّب (أحدث rendered_at بين مسودات الريل التي تحمل
    reel_music)، وأول ريل يأخذ الأولى. إعادة تركيب ريل يبقي مقطوعته المحفوظة ما دامت موجودة كي لا يتبدّل صوته بلا سبب.
    لا مجلد أو لا mp3 أو music.enabled=false ← None (ريل بلا موسيقى كما كان)، وسطر log.info واحد عند غياب الملفات."""
    import json
    mcfg = cfg.path("reel.music") or {}
    if not mcfg.get("enabled"):
        return None
    files = sorted(p.name for p in Path(MUSIC_DIR).glob("*.mp3")) if Path(MUSIC_DIR).is_dir() else []
    if not files:
        log.info("لا مقطوعات موسيقى في %s — ريل بلا موسيقى", MUSIC_DIR)
        return None
    kept = draft.get("reel_music")
    if kept in files:
        return kept
    last, last_at = None, ""
    for p in store.DRAFTS_DIR.glob("*/*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if d.get("format") == "reel" and d.get("reel_music") and (d.get("rendered_at") or "") >= last_at \
                and d.get("id") != draft.get("id"):
            last, last_at = d["reel_music"], d.get("rendered_at") or ""
    # آخر مقطوعة لم تعد موجودة ← الأولى؛ وإلا التالية بدورة مغلقة
    return files[(files.index(last) + 1) % len(files)] if last in files else files[0]


def _music_mix(cfg, music: Path, seconds: float) -> tuple[list[str], str]:
    """(مدخل المقطوعة، مرشحات الصوت في filter_complex). المرشحات مطابقة للمزج الذي سمعه صاحب المشروع: الموسيقى
    loudnorm إلى bed_lufs بظهور/اختفاء تدريجيين، ومفتاح الضغط الجانبي هو نسخة من الصوت فتنخفض تحت أي كلام، ثم المزج
    فـloudnorm النهائي كما كان. -stream_loop -1 يكرّر المقطوعة إن كان الريل أطول منها، وamix duration=first يقصّ الصوت
    بطول الفيديو (الصوت الأصلي هو الأول)."""
    m = cfg.path("reel.music")
    dk = m["duck"]
    fade_out = float(m["fade_out"])
    start = max(seconds - fade_out, 0.0)
    rate = cfg.path("reel.render.audio_rate", 48000)
    audio = (f"[2:a]aresample={rate},aformat=channel_layouts=stereo,loudnorm=I={m['bed_lufs']}:TP=-3:LRA=11,"
             f"afade=t=in:d={m['fade_in']},afade=t=out:st={_fmt(start)}:d={m['fade_out']}[music];"
             f"[0:a]asplit=2[voice][key];"
             f"[music][key]sidechaincompress=threshold={dk['threshold']}:ratio={dk['ratio']}:attack={dk['attack']}:"
             f"release={dk['release']}:makeup=1[bed];"
             f"[voice][bed]amix=inputs=2:normalize=0:duration=first,{_loudnorm(cfg)}[a]")
    return ["-stream_loop", "-1", "-i", str(music)], audio


def _save(img: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def _drop(dropped: list, scene: dict, reason: str) -> None:
    dropped.append({"point_id": scene.get("point_id", ""), "kind": scene.get("kind", ""), "reason": reason})


def _approx_window(point: dict, scene: dict) -> tuple[int, int] | None:
    """نافذة احتياطية من المشهد المحفوظ عند تعذّر نص الفيديو: تتطلب timestamp في النقطة (حُسم من النص عند الاستخراج)
    وstart/end في المشهد؛ غير ذلك None فيُسقط المقطع كما كان."""
    if point.get("timestamp") is None or scene.get("start") is None or scene.get("end") is None:
        return None
    start, end = int(math.floor(float(scene["start"]))), int(math.ceil(float(scene["end"])))
    return (start, end) if end > start else None


class ClipDownloadFailed(RuntimeError):
    """مقطع لم يُنزَّل بعد كل الإعادات: الريل لا يُركَّب ناقصًا بل يُعاد في تشغيلة لاحقة (Issue #1404)."""

    def __init__(self, channel: str, reason: str):
        super().__init__(reason)
        self.channel, self.reason = channel, reason


NO_STREAMS_REASON = "المقطع بلا صورة أو بلا صوت"


def _clip_files(out: Path) -> list[Path]:
    found = [out] if out.exists() else []
    return found + [p for p in sorted(out.parent.glob(f"{out.stem}.*")) if p != out]


def _download_with_retries(deps: Deps, rcfg, vid: str, wstart: int, wend: int, out: Path) -> Path | None:
    """السلّم كاملًا ثم إعادته download_retries مرة بانتظار retry_wait_seconds قبل كل إعادة: العطل عابر عادة
    (المقطع نفسه نزل في تركيبين سابقين)، فإسقاطه يترك راويًا بلا مقطع. يعيد الملف المقبول (فيه صورة وصوت معًا)؛
    فشل جزء الصورة يترك جزء الصوت وحده وكان يُحسب نجاحًا (Issue #1406)، فيُعدّ الآن فشل محاولة. لا ملف إطلاقًا ← None
    (إسقاط كما كان)."""
    retries = int(rcfg.get("download_retries", 2))
    for attempt in range(retries + 1):
        for p in _clip_files(out):      # بقايا محاولة سابقة تُحذف كي لا يلتقطها الاحتياط
            p.unlink(missing_ok=True)
        try:
            deps.download_clip(vid, wstart, wend, int(rcfg["clip_height"]), out)
            files = _clip_files(out)
            if not files:
                return None
            for f in files:
                try:
                    if {"video", "audio"} <= set(deps.streams(f)):
                        return f
                except Exception:  # noqa: BLE001 -- ملف لا يُقرأ ليس مقبولًا
                    continue
            raise RuntimeError(NO_STREAMS_REASON)
        except Exception:  # noqa: BLE001
            if attempt >= retries:
                raise
            deps.sleep(float(rcfg.get("retry_wait_seconds", 20)))
    return None


def _fetch_clips(script: dict, draft: dict, cfg, deps: Deps, tmp: Path) -> tuple[dict, list, list]:
    """لكل مشهد مقطع: نص الفيديو ← تحديد موضع الاقتباس ← تنزيل نافذته. يعيد ({فهرس المشهد: {file, seconds}}, المحذوف,
    المقاطع بنافذة تقديرية). تعذّر النص (استثناء أو فارغ) لا يُسقط المقطع بل يستعمل نافذة المشهد؛ أما نص متاح لا يطابق
    الاقتباس فيبقى إسقاطًا لأن النص هناك ولا يؤيد المقطع."""
    rcfg, scfg = cfg.path("reel.render"), cfg.path("reel.script")
    by_id = {reel_script.point_key_id(p): p for p in deps.load_points(draft.get("topic_date", ""))}
    transcripts: dict[str, list] = {}
    clips: dict[int, dict] = {}
    dropped: list = []
    approx: list = []
    from . import youtube_extract
    for i, scene in enumerate(script["scenes"]):
        if scene.get("kind") not in reel_script.CLIP_KINDS:
            continue
        point = by_id.get(scene.get("point_id"))
        if not point or not point.get("video_id"):
            _drop(dropped, scene, "نقطة المقطع غير موجودة في نافذة النقاط")
            continue
        vid = point["video_id"]
        if vid not in transcripts:
            try:
                text = deps.fetch_transcript(vid)
            except Exception as exc:  # noqa: BLE001
                log.warning("نص الفيديو %s: %s", vid, str(exc)[:150])
                text = None
            transcripts[vid] = youtube_extract.parse_transcript_segments(text) if text else []
        if not transcripts[vid]:
            win = _approx_window(point, scene)
            if win is None:
                _drop(dropped, scene, "تعذّر جلب نص الفيديو")
                continue
            wstart, wend = win
            approx.append({"point_id": scene.get("point_id", ""), "kind": scene.get("kind", ""),
                           "start": wstart, "end": wend, "reason": "تعذّر جلب نص الفيديو",
                           "channel": scene.get("channel_display", "")})
        else:
            near = point.get("timestamp", scene.get("start"))
            loc = reel_clips.locate_quote(point.get("quote_original", ""), transcripts[vid], near=near, cfg=cfg)
            if loc["status"] == "ambiguous":
                _drop(dropped, scene, "موضع الاقتباس في الفيديو غير حاسم (يتكرر)")
                continue
            if loc["status"] != "found":
                _drop(dropped, scene, "الاقتباس غير موجود في نص الفيديو")
                continue
            wstart = int(max(0, loc["start"] - float(scfg.get("lead_seconds", 1))))
            wend = int(math.ceil(loc["end"]))
            wend = min(wend, wstart + int(scfg.get("clip_max_seconds", 15)))
            if wend <= wstart:     # نافذة معدومة (اقتباس في آخر سطر) تُمدّ إلى الحد الأدنى لا تُسقط المقطع
                wend = wstart + int(scfg.get("clip_min_seconds", 6))
        out = tmp / f"clip_{i}.mp4"
        try:
            got = _download_with_retries(deps, rcfg, vid, wstart, wend, out)
        except Exception as exc:  # noqa: BLE001 -- عطل تنزيل لا إسقاط تحريري: الريل كله يؤجَّل
            raise ClipDownloadFailed(scene.get("channel_display", ""),
                                     "فشل تنزيل المقطع: " + reel_clips.scrub_text(str(exc))[:120]) from exc
        if got is None:
            _drop(dropped, scene, "لم يُنتج التنزيل ملفًا")
            if approx and approx[-1]["point_id"] == scene.get("point_id", ""):
                approx.pop()
            continue
        out = got
        secs = deps.probe(out) or float(wend - wstart)
        clips[i] = {"file": out, "seconds": float(secs)}
    return clips, dropped, approx


def _speech(text: str, voice: str, cfg, deps: Deps, tmp: Path, tag: str) -> tuple[Path, list[tuple[str, float]]]:
    """صوت مشهد: تشكيل النص كله ← جمل ← وقف ← نداء لكل جملة ← وصل بصمت. يعيد (ملف الصوت، [(نص الجملة للعرض، مدتها)])."""
    rcfg = cfg.path("reel.render")
    silence = float(cfg.path("reel.tts.sentence_silence", 0.35))
    shown, warn = deps.diacritize(text)
    if warn:
        log.warning("تشكيل %s: %s", tag, warn)
    sentences = tts.split_sentences(shown)
    if not sentences:
        raise RuntimeError(f"مشهد {tag} بلا جمل")
    wavs, parts = [], []
    for k, sentence in enumerate(sentences):
        res = deps.synthesize(tts.apply_waqf(sentence), voice)
        if not res.get("ok"):
            raise RuntimeError("تعذّر توليد الصوت: " + str(res.get("error") or res.get("skipped") or "?")[:120])
        mp3 = tmp / f"{tag}_{k}.mp3"
        mp3.write_bytes(res["audio"])
        wav = tmp / f"{tag}_{k}.wav"
        deps.run(_base("-i", str(mp3), "-af",
                       f"aresample={rcfg.get('audio_rate', 48000)},aformat=channel_layouts=stereo,{_loudnorm(cfg)},"
                       f"apad=pad_dur={silence}",
                       str(wav)))
        dur = deps.probe(wav)
        parts.append((tts.strip_tashkeel(sentence), float(dur or 0)))
        wavs.append(wav)
    lst = tmp / f"{tag}_audio.txt"
    lst.write_text("".join(f"file '{w}'\n" for w in wavs), encoding="utf-8")
    audio = tmp / f"{tag}_audio.wav"
    deps.run(_base("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(audio)))
    return audio, parts


def _timed_scene(frames: list[tuple[Path, float]], audio: Path, out: Path, cfg, deps: Deps, tmp: Path, tail: float,
                 lead: float = 0.0) -> float:
    """مشهد صوتي بإطارات متتابعة (جملة لكل إطار بمدتها الفعلية)؛ يعيد مدته.
    lead: صمت في أول الصوت يمتد معه الإطار الأول، كي لا تقع أول كلمة في التلاشي المتقاطع مع المشهد السابق."""
    rcfg = cfg.path("reel.render")
    frames = list(frames)
    frames[-1] = (frames[-1][0], frames[-1][1] + tail)
    if lead > 0:
        frames[0] = (frames[0][0], frames[0][1] + lead)
    total = sum(d for _, d in frames)
    lst = tmp / (out.stem + "_frames.txt")
    body = "".join(f"file '{f}'\nduration {_fmt(d)}\n" for f, d in frames) + f"file '{frames[-1][0]}'\n"
    lst.write_text(body, encoding="utf-8")
    deps.run(_base("-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(audio), "-vf",
                   f"fps={rcfg['fps']},format=yuv420p", "-af",
                   f"adelay={int(round(lead * 1000))}:all=1,apad" if lead > 0 else "apad", "-t", _fmt(total), *_enc(rcfg), str(out)))
    return total


def _still_scene(png: Path, seconds: float, out: Path, cfg, deps: Deps) -> float:
    """مشهد صامت بصورة ثابتة (العنوان والختام)."""
    rcfg = cfg.path("reel.render")
    deps.run(_base("-loop", "1", "-framerate", str(rcfg["fps"]), "-i", str(png), "-f", "lavfi", "-i",
                   f"anullsrc=r={rcfg.get('audio_rate', 48000)}:cl=stereo", "-t", _fmt(seconds), "-vf",
                   "format=yuv420p", *_enc(rcfg), str(out)))
    return seconds


def _crop_for(clip: dict, cfg, deps: Deps) -> dict:
    """نافذة الاقتطاع الثابتة للمقطع. تعذّر الكشف أو قراءة المقطع ← المنتصف بتعبير ffmpeg نفسه."""
    ccfg = cfg.path("reel.render.crop") or {}
    mode = ccfg.get("mode", "face")
    try:
        if mode != "face":
            raise RuntimeError("mode=center")
        sw, sh, centers = deps.faces(clip["file"], list(ccfg.get("samples", [0.2, 0.5, 0.8])))
        return crop_window(int(sw), int(sh), centers, mode)
    except Exception as exc:  # noqa: BLE001 -- الكشف تحسين لا شرط
        if mode == "face":
            log.warning("تعذّر كشف الوجه فنافذة المنتصف: %s", str(exc)[:100])
        return {"w": None, "h": None, "x": None, "source": "center"}


def _clip_scene(clip: dict, overlays: tuple[Path, Path], out: Path, cfg, deps: Deps, scene: dict | None = None) -> float:
    """المقطع يملأ الشاشة الرأسية باقتطاع ثابت (يتبع الوجه)، ثم الطبقة الثابتة، ثم طبقة الشريط تدخل من اليمين
    بتباطؤ في آخر الحركة: x = W×(1−p)^3 مع p من 0 إلى 1 خلال slide_seconds بعد انتهاء الانتقال (قبلها خارج الشاشة)."""
    rcfg = cfg.path("reel.render")
    w, h = rcfg["width"], rcfg["height"]
    crop = _crop_for(clip, cfg, deps)
    clip["crop"] = {"x": crop["x"], "source": crop["source"]}
    if crop["x"] is None:      # أبعاد المصدر مجهولة: المنتصف بتعبير يحسبه ffmpeg
        cexpr = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0"
        clip["crop"]["x"] = "center"
    else:
        cexpr = f"crop={crop['w']}:{crop['h']}:{crop['x']}:0"
    if scene is not None and cfg.path("reel.render.band.cover") not in (True, False):
        # الغطاء والشريط المعتم فقط حين في أسفل المقطع شريط أخبار أو لافتة (Issue #1408)؛ القرار يُحفظ للمراجعة
        cover = detect_cover(clip["file"], crop["x"], crop["w"], cfg, deps.frames)
        clip["crop"]["cover"] = cover
        overlays = tuple(_save(im, Path(ov).with_name(Path(ov).stem + "_auto.png"))
                         for im, ov in zip(frame_clip_layers(cfg, scene, cover=cover), overlays))
    slide = float(cfg.path("reel.render.band.slide_seconds", 0) or 0)
    if slide > 0:
        pos = f"x='W*pow(1-min(max((t-{_fmt(transition_seconds(cfg))})/{_fmt(slide)},0),1),3)':y=0"
    else:
        pos = "0:0"
    graph = (f"[0:v]{cexpr},scale={w}:{h}[v0];"
             f"[v0][1:v]overlay=0:0:shortest=1[v1];"
             f"[v1][2:v]overlay={pos}:shortest=1,fps={rcfg['fps']},format=yuv420p[v]")
    loops = [x for ov in overlays for x in ("-loop", "1", "-framerate", str(rcfg["fps"]), "-i", str(ov))]
    deps.run(_base("-i", str(clip["file"]), *loops,
                   "-filter_complex", graph, "-map", "[v]", "-map", "0:a:0", "-af",
                   f"aresample={rcfg.get('audio_rate', 48000)},aformat=channel_layouts=stereo,{_loudnorm(cfg)}",
                   "-t", _fmt(clip["seconds"]), *_enc(rcfg), str(out)))
    return clip["seconds"]


def _trimmed_logo(cfg, tmp: Path) -> Path:
    src = imaging.find_logo(cfg.path("brand.logo"))
    if src is None:
        raise RuntimeError("الشعار غير موجود")
    img = Image.open(src).convert("RGBA")
    bbox = img.getchannel("A").getbbox()
    if bbox:
        img = img.crop(bbox)
    return _save(img, tmp / "logo_trimmed.png")


def transition_seconds(cfg) -> float:
    """مدة الانتقال الفعلية: 0 تعني بلا انتقال. تُخفَّض إلى min(lead_seconds، clip_tail_seconds) − 0.1 إن بلغتهما،
    لأن المقطع يبدأ قبل كلامه بـlead وينتهي بعده بـtail فلا يقع كلام في التلاشي إلا إن تجاوزته المدة."""
    seconds = float(cfg.path("reel.render.transition.seconds", 0) or 0)
    if seconds <= 0:
        return 0.0
    cap = min(float(cfg.path("reel.script.lead_seconds", 1)), float(cfg.path("reel.script.clip_tail_seconds", 1.0)))
    if seconds >= cap:
        reduced = round(cap - 0.1, 3)
        log.warning("مدة الانتقال %s تبلغ حدّ المقطع %s فخُفّضت إلى %s", seconds, cap, reduced)
        return reduced
    return seconds


def _narration_frames(parts: list[tuple[str, float]], i: int, cfg, tmp: Path, lead: float,
                      bg: dict | None = None) -> list[tuple[Path, float]]:
    """إطارات مشهد الراوي. مع typewriter: خطوة لكل حرف (typewriter_steps) بمدة كلام الجملة = مدة صوتها − الصمت بعدها،
    ويبقى النص كاملًا خلال الصمت. بدونه: إطار كامل لكل جملة كما كان. أول إطار فارغ كي يقع صمت الانتقال بلا نص."""
    if not cfg.path("reel.render.typewriter.enabled", False):
        return [(_save(frame_narration(cfg, text, bg=bg) if bg is not None else frame_narration(cfg, text),
                       tmp / f"nar_{i}_{k}.png"), dur) for k, (text, dur) in enumerate(parts)]
    silence = float(cfg.path("reel.tts.sentence_silence", 0.35))
    fps = float(cfg.path("reel.render.fps"))
    frames: list[tuple[Path, float]] = []
    for k, (text, dur) in enumerate(parts):
        hold = min(silence, dur)
        steps = typewriter_steps(text, dur - hold, hold, fps)
        if k == 0 and lead > 0 and steps[0][0]:
            steps = [("", 0.0)] + steps    # lead يُضاف إلى هذه الخطوة الفارغة في _timed_scene
        for j, (prefix, d) in enumerate(steps):
            im = frame_narration_typed(cfg, text, prefix, bg=bg) if bg is not None else frame_narration_typed(cfg, text, prefix)
            frames.append((_save(im, tmp / f"nar_{i}_{k}_{j}.png"), d))
    return frames


def _assemble(script: dict, clips: dict, cfg, deps: Deps, tmp: Path, voice: str, bg: dict | None = None,
              credit: str = "") -> tuple[list[Path], list[str], list[float]]:
    rcfg = cfg.path("reel.render")
    lead = transition_seconds(cfg)
    date_text = datetime.now().strftime("%Y/%m/%d")
    channels = "، ".join(dict.fromkeys(s.get("channel_display", "") for i, s in enumerate(script["scenes"])
                                        if i in clips and s.get("channel_display")))
    scene_files: list[Path] = []
    kinds: list[str] = []
    durs: list[float] = []
    for i, scene in enumerate(script["scenes"]):
        kind, out = scene.get("kind"), tmp / f"scene_{i:02d}.mp4"
        if kind in reel_script.CLIP_KINDS:
            if i not in clips:
                continue
            static, band = frame_clip_layers(cfg, scene)
            overlays = (_save(static, tmp / f"overlay_{i}_static.png"), _save(band, tmp / f"overlay_{i}_band.png"))
            dur = _clip_scene(clips[i], overlays, out, cfg, deps, scene)
        elif kind == "title_card":
            png = _save(frame_title(cfg, scene.get("text") or script.get("title", ""), date_text), tmp / f"title_{i}.png")
            dur = _still_scene(png, float(rcfg["title_seconds"]), out, cfg, deps)
        elif kind == "outro":
            png = _save(frame_outro(cfg, channels, credit=credit) if credit else frame_outro(cfg, channels),
                        tmp / f"outro_{i}.png")
            dur = _still_scene(png, float(rcfg["outro_seconds"]), out, cfg, deps)
        elif kind in ("narration", "question"):
            audio, parts = _speech(scene.get("text", ""), voice, cfg, deps, tmp, f"s{i:02d}")
            if kind == "narration":
                frames = _narration_frames(parts, i, cfg, tmp, lead, bg)
                tail = 0.0
            else:
                png = _save(frame_question(cfg, scene.get("text", "")), tmp / f"q_{i}.png")
                frames = [(png, sum(d for _, d in parts))]
                tail = float(rcfg["question_tail_seconds"])
            dur = _timed_scene(frames, audio, out, cfg, deps, tmp, tail, lead)
        else:
            continue
        scene_files.append(out)
        kinds.append(kind)
        durs.append(dur)
    return scene_files, kinds, durs


def _join(scene_files: list[Path], kinds: list[str], durs: list[float], cfg, deps: Deps, tmp: Path) -> Path:
    """يضمّ ملفات المشاهد: بانتقالات xfade/acrossfade بأمر واحد، أو concat -c copy حين لا انتقال (seconds=0 أو مشهد واحد).
    الانتقال رقم k يبدأ عند مجموع مدد أول k مشهدًا ناقص k×seconds لأن كل انتقال يأكل مدته من الطول الكلي."""
    rcfg = cfg.path("reel.render")
    joined = tmp / "joined.mp4"
    secs = transition_seconds(cfg)
    if secs <= 0 or len(scene_files) < 2:
        lst = tmp / "scenes.txt"
        lst.write_text("".join(f"file '{f}'\n" for f in scene_files), encoding="utf-8")
        deps.run(_base("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)))
        return joined
    # مدة الملف المقيسة هي الحقيقية؛ المحسوبة احتياط إن تعذّر القياس
    real = [float(deps.probe(f) or d) for f, d in zip(scene_files, durs)]
    tcfg = cfg.path("reel.render.transition")
    vparts, aparts = [], []
    vprev, aprev, acc = "0:v", "0:a", 0.0
    for k in range(1, len(scene_files)):
        acc += real[k - 1]
        kind = tcfg.get("outro_type", "fade") if kinds[k] == "outro" else tcfg.get("type", "slideleft")
        vparts.append(f"[{vprev}][{k}:v]xfade=transition={kind}:duration={_fmt(secs)}:offset={_fmt(acc - k * secs)}[v{k}]")
        aparts.append(f"[{aprev}][{k}:a]acrossfade=d={_fmt(secs)}[a{k}]")
        vprev, aprev = f"v{k}", f"a{k}"
    last = len(scene_files) - 1
    inputs = [x for f in scene_files for x in ("-i", str(f))]
    deps.run(_base(*inputs, "-filter_complex", ";".join(vparts + aparts), "-map", f"[v{last}]", "-map", f"[a{last}]",
                   *_enc(rcfg), str(joined)))
    return joined


def _resolve_background(path: Path, draft: dict, cfg, deps: Deps, notes: list) -> tuple[dict | None, dict]:
    """خلفية الراوي للتركيب: (الطبقة المحضَّرة أو None، reel_bg المحفوظ). manual_image يغلب reel_bg؛ مسودة بلا reel_bg
    (سيناريو قديم) تختار الآن وتُحفظ فورًا. فشل التنزيل ← None (الخلفية الكحلية) وسطر في التعليق، لا فشل تركيب."""
    stored = draft.get("reel_bg") if isinstance(draft.get("reel_bg"), dict) and draft["reel_bg"].get("kind") else None
    if stored is None:
        providers = {**(deps.bg_providers or {}), "download": deps.bg_image}
        stored = pick_background(draft, cfg, providers)
        store.update_draft(path, reel_bg=stored)
    manual = (draft.get("manual_image") or "").strip()
    used = {"url": manual, "kind": "manual", "publisher": ""} if manual else stored
    if not used.get("url"):
        return None, stored
    try:
        img = deps.bg_image(used["url"])
    except Exception as exc:  # noqa: BLE001
        log.warning("تعذّر تنزيل صورة خلفية الراوي: %s", str(exc)[:100])
        img = None
    if img is None:
        notes.append(cfg.path("reel.render.texts.comment_bg_failed"))
        return None, stored
    prepared = prepare_background(cfg, img)
    prepared["used"] = used
    return prepared, stored


def _render(path: Path, draft: dict, cfg, deps: Deps, reels_dir: Path, tmp: Path, dropped: list,
            approx: list, notes: list | None = None) -> dict:
    rcfg, scfg = cfg.path("reel.render"), cfg.path("reel.script")
    script = draft.get("script") or {}
    if not script.get("scenes"):
        raise RuntimeError("لا سيناريو معتمد")
    clips, drops, approx_found = _fetch_clips(script, draft, cfg, deps, tmp)
    dropped.extend(drops)
    approx.extend(approx_found)
    wanted = sum(1 for s in script["scenes"] if s.get("kind") in reel_script.CLIP_KINDS)
    need = int(scfg.get("min_clips", 2))
    if len(clips) < need:
        raise RuntimeError(f"بقي {len(clips)} مقطعًا من {wanted} بعد الحذف والأدنى المطلوب {need}")
    voice = cfg.path(f"reel.tts.narrator_voices.{script.get('narrator', 'female')}")
    notes = notes if notes is not None else []
    bg, bg_saved = _resolve_background(path, draft, cfg, deps, notes)
    scene_files, kinds, durs = _assemble(script, clips, cfg, deps, tmp, voice, bg,
                                         outro_credit(cfg, bg["used"]) if bg else "")
    joined = _join(scene_files, kinds, durs, cfg, deps, tmp)

    rel_dir = f"{path.parent.name}"
    dest = reels_dir / rel_dir / f"{path.stem}.mp4"
    gif = reels_dir / rel_dir / f"{path.stem}.gif"
    dest.parent.mkdir(parents=True, exist_ok=True)
    lg = rcfg["logo"]
    logo = _trimmed_logo(cfg, tmp)
    # الشعار مرة واحدة فوق الفيديو المجمَّع كله: مكانه وحجمه ثابتان في كل لحظة بلا استثناء
    video_f = f"[1:v]scale={lg['width']}:-1[lg];[0:v][lg]overlay=W-w-{lg['right']}:{lg['top']}[v]"
    music = pick_music(draft, cfg)
    if music:
        # المدة المقيسة للمجمَّع تحدد بداية الاختفاء التدريجي؛ فشل القياس ← مجموع المدد ناقص الانتقالات
        seconds = deps.probe(joined) or (sum(durs) - transition_seconds(cfg) * max(len(durs) - 1, 0))
        music_in, audio_f = _music_mix(cfg, Path(MUSIC_DIR) / music, float(seconds))
        deps.run(_base("-i", str(joined), "-i", str(logo), *music_in, "-filter_complex", video_f + ";" + audio_f,
                       "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
                       "-crf", str(rcfg.get("crf", 22)), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                       "-ar", str(rcfg.get("audio_rate", 48000)), "-ac", "2", "-movflags", "+faststart", str(dest)))
    else:
        deps.run(_base("-i", str(joined), "-i", str(logo), "-filter_complex", video_f,
                       "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-preset", "veryfast",
                       "-crf", str(rcfg.get("crf", 22)), "-pix_fmt", "yuv420p", "-af", _loudnorm(cfg), "-c:a", "aac",
                       "-b:a", "128k", "-ar", str(rcfg.get("audio_rate", 48000)), "-ac", "2", "-movflags", "+faststart",
                       str(dest)))
    # مدة الملف النهائي المقيسة لا مجموع المدد: الانتقالات تقصّر الطول الكلي
    total = deps.probe(dest) or (sum(durs) - transition_seconds(cfg) * max(len(durs) - 1, 0))
    g = rcfg["gif"]
    deps.run(_base("-t", str(g["seconds"]), "-i", str(dest), "-vf",
                   f"fps={g['fps']},scale={g['width']}:{g['height']}:flags=lanczos,split[x][y];[x]palettegen[p];"
                   f"[y][p]paletteuse", "-loop", "0", str(gif)))
    sub = rcfg.get("repo_subdir", "reels")
    return {"reel_file": f"{sub}/{rel_dir}/{dest.name}", "reel_gif": f"{sub}/{rel_dir}/{gif.name}",
            "duration_seconds": round(total, 1), "render_version": int(rcfg.get("version", 1)),
            "render_attempts": 0, **({"reel_music": music} if music else {}),
            # الشكل المستعمل في هذا التركيب يُحفظ مع reel_bg؛ بلا صورة منزَّلة لا شكل
            "reel_bg": {**{k: v for k, v in bg_saved.items() if k != "layout"}, **({"layout": bg["layout"]} if bg else {})},
            "render_crops": {str(i): c["crop"] for i, c in clips.items() if "crop" in c}}


def _mmss(sec) -> str:
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def _comment_text(cfg, draft: dict, result: dict, dropped: list, approx: list | None = None,
                  notes: list | None = None) -> str:
    t = cfg.path("reel.render.texts")
    base = cfg.path("reel.render.data_link_base")
    if result.get("render_status") == "failed":
        text = t["comment_failed"].format(reason=result.get("render_error", "?"))
    else:
        text = t["comment"].format(seconds=result["duration_seconds"], video=base + result["reel_file"],
                                   gif=base + result["reel_gif"])
    if dropped:
        details = "؛ ".join(f"{d['kind']} ({d['reason']})" for d in dropped)
        text += "\n" + t["comment_dropped"].format(n=len(dropped), details=details)
    for a in approx or []:
        text += "\n" + t["comment_approx"].format(
            channel=a.get("channel", ""), window=f"{_mmss(a['start'])}–{_mmss(a['end'])}", reason=a["reason"])
    for n in notes or []:
        text += "\n" + n
    return text


def render_draft(path: Path, draft: dict, cfg, deps: Deps | None = None, *, reels_dir: Path | None = None,
                 workdir: Path | None = None) -> dict:
    """يركّب مسودة ريل واحدة ويحدّث حقولها. لا يرفع أبدًا: أي عطل ← render_status="failed" وrender_error بسببه.
    المجلد المؤقت للمقاطع الخام يُحذف نجح التركيب أو فشل."""
    deps = (deps or Deps()).resolved(cfg)
    reels_dir = Path(reels_dir) if reels_dir else REELS_DIR
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="reel_render_"))
    tmp.mkdir(parents=True, exist_ok=True)
    dropped: list = []
    approx: list = []
    notes: list = []
    try:
        result = {"render_status": "rendered", **_render(path, draft, cfg, deps, reels_dir, tmp, dropped, approx, notes)}
    except ClipDownloadFailed as exc:
        # لا ريل ناقص: لا ملف جديد ولا مساس بـreel_file السابق؛ يُعاد في التشغيلة التالية حتى max_attempts
        shutil.rmtree(tmp, ignore_errors=True)
        t = cfg.path("reel.render.texts")
        limit = int(cfg.path("reel.render.max_attempts", 3))
        attempts = int(draft.get("render_attempts") or 0) + 1
        if attempts < limit:
            changes = {"render_status": "queued", "render_attempts": attempts}
            text = t["comment_download_retry"].format(channel=exc.channel, n=attempts, max=limit)
        else:
            changes = {"render_status": "failed", "render_attempts": attempts, "render_error": exc.reason}
            text = t["comment_download_failed"].format(channel=exc.channel, max=limit, reason=exc.reason)
        log.warning("تأجيل تركيب الريل %s: %s", path.stem, exc.reason)
        store.update_draft(path, **changes)
        issue = draft.get("review_issue")
        if issue:
            try:
                deps.comment(int(issue), text)
            except Exception as cexc:  # noqa: BLE001
                log.warning("تعذّر التعليق على القضية %s: %s", issue, str(cexc)[:150])
        return changes
    except Exception as exc:  # noqa: BLE001 -- failed يجب أن يحمل سببه ويُحيى بـ--retry
        reason = reel_clips.scrub_text(str(exc))
        reason = " ".join(reason.split())[:300] or exc.__class__.__name__
        log.error("فشل تركيب الريل %s: %s", path.stem, reason)
        result = {"render_status": "failed", "render_error": reason}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # القناة حقل عرض للتعليق وحده؛ المحفوظ على المسودة {point_id, kind, start, end, reason}
    approx_saved = [{k: v for k, v in a.items() if k != "channel"} for a in approx]
    changes = {**result, "render_dropped": dropped, "render_approx": approx_saved,
               "rendered_at": datetime.now(timezone.utc).isoformat()}
    remove = ["render_error"] if result["render_status"] == "rendered" else ["reel_file", "reel_gif", "duration_seconds"]
    store.update_draft(path, remove=remove, **changes)
    issue = draft.get("review_issue")
    if issue:
        try:
            deps.comment(int(issue), _comment_text(cfg, draft, result, dropped, approx, notes))
        except Exception as exc:  # noqa: BLE001 -- التعليق إخبار لا شرط للتركيب
            log.warning("تعذّر التعليق على القضية %s: %s", issue, str(exc)[:150])
    return result


# ───────────────────────────── الطابور ─────────────────────────────


def queued_reels(cfg=None) -> list[tuple[Path, dict]]:
    """مسودات الريل المنتظرة التركيب، الأقدم اعتمادًا أولًا. مع cfg تُضاف المعتمدة المُركَّبة بنسخة أقدم من
    reel.render.version (أو بلا نسخة) فتُعاد كأنها queued؛ المنشور والمرفوض وغير المعتمد لا يُمسّ."""
    import json
    version = int(cfg.path("reel.render.version", 1)) if cfg is not None else None
    out = []
    for p in sorted(store.DRAFTS_DIR.glob("*/*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if d.get("format") != "reel":
            continue
        stale = (version is not None and d.get("status") == "approved_script" and d.get("render_status") == "rendered"
                 and int(d.get("render_version") or 0) < version)
        # failed بنسخة أقدم يُحيا تلقائيًا (Issue #1406): سببه قد يكون عطلًا أُصلح في النسخة الجديدة
        revive = (version is not None and d.get("status") == "approved_script" and d.get("render_status") == "failed"
                  and int(d.get("render_version") or 0) < version)
        if d.get("render_status") == "queued" or stale or revive:
            out.append((p, d))
    out.sort(key=lambda pd: (pd[1].get("approved_script_at") or "", pd[0].name))
    return out


def pending_batch(cfg) -> list[tuple[Path, dict]]:
    """ما تركّبه تشغيلة --pending: المنتظر ثم المعتمد بنسخة أقدم، حتى reel.render.max_per_run."""
    out = []
    for path, d in queued_reels(cfg)[: int(cfg.path("reel.render.max_per_run", 1))]:
        if d.get("render_status") == "failed":
            d = store.update_draft(path, remove=["render_error"], render_status="queued", render_attempts=0)
        out.append((path, d))
    return out


def retry(draft_id: str, cfg) -> bool:
    """يعيد ريلًا failed إلى queued (failed يجب أن يُحيا بإصلاح سببه)."""
    found = store.load_draft(draft_id)
    if not found or found[1].get("render_status") != "failed":
        return False
    store.update_draft(found[0], remove=["render_error", "render_dropped", "render_approx"],
                       render_status="queued", render_attempts=0)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="تركيب الريل mp4 من السيناريو المعتمد (بلا نشر)")
    ap.add_argument("--pending", action="store_true", help="ركّب المنتظر (حتى reel.render.max_per_run)")
    ap.add_argument("--retry", metavar="ID", help="أعد ريلًا failed إلى queued")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config()
    if args.retry:
        ok = retry(args.retry, cfg)
        print(f"{'أُعيد إلى queued' if ok else 'لا ريل failed بهذا المعرّف'}: {args.retry}")
    if args.pending:
        batch = pending_batch(cfg)
        for path, draft in batch:
            res = render_draft(path, draft, cfg)
            print(f"{path.stem}: {res['render_status']} {res.get('render_error', '')}")
        if not batch:
            print("لا ريل منتظر التركيب")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
