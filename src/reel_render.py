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
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw

from . import imaging, reel_clips, reel_script, store, tts
from .config import REELS_DIR, load_config

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
            comment=self.comment or comment)


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


def frame_narration(cfg, sentence: str, boxes=None) -> Image.Image:
    p = _Pen(cfg, boxes)
    p.block(sentence, TAJAWAL_XB, None, p.white, 860, start=72, minimum=40)
    return p.rgb()


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


def frame_outro(cfg, channels: str, boxes=None) -> Image.Image:
    p = _Pen(cfg, boxes)
    t = cfg.path("reel.render.texts")
    y = p.line(t["follow"], p.font(CAIRO, 112, "Black"), p.white, 560)
    p.rule(y + 10)
    y = p.block(t["tagline"], TAJAWAL_B, None, p.white, 0, start=52, minimum=36, max_lines=3, y_top=y + 60)
    p.line(cfg.path("brand.handle") or "@almujez", p.font(TAJAWAL_B, 54), p.gold, y + 20, ltr=True)
    p.block(t["clips_from"].format(channels=channels), TAJAWAL_R, None, (200, 208, 224), 0, start=36, minimum=26,
            max_lines=4, y_top=1180)
    return p.rgb()


def frame_clip_overlay(cfg, scene: dict, boxes=None) -> Image.Image:
    """شفافة بحجم الشاشة: الترجمة في صندوق داكن فوق الشريط، والشريط السفلي بحافته الذهبية على اليمين."""
    p = _Pen(cfg, boxes, transparent=True)
    band = cfg.path("reel.render.band")
    top, height, edge = int(band["top"]), int(band["height"]), int(band["edge"])
    navy_a = p.navy + (round(255 * float(band["alpha"])),)
    p.d.rectangle((0, top, p.w, top + height), fill=navy_a)
    p.d.rectangle((p.w - edge, top, p.w, top + height), fill=p.gold + (255,))
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
    return p.img


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
            deps.download_clip(vid, wstart, wend, int(rcfg["clip_height"]), out)
        except Exception as exc:  # noqa: BLE001 -- فشل كل درجات التنزيل يحذف المشهد لا الريل
            _drop(dropped, scene, "فشل تنزيل المقطع: " + reel_clips.scrub_text(str(exc))[:120])
            if approx and approx[-1]["point_id"] == scene.get("point_id", ""):
                approx.pop()     # لم يُركَّب فلا نافذة تقديرية تُراجَع
            continue
        if not out.exists():
            found = sorted(tmp.glob(f"clip_{i}.*"))
            if not found:
                _drop(dropped, scene, "لم يُنتج التنزيل ملفًا")
                if approx and approx[-1]["point_id"] == scene.get("point_id", ""):
                    approx.pop()
                continue
            out = found[0]
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


def _timed_scene(frames: list[tuple[Path, float]], audio: Path, out: Path, cfg, deps: Deps, tmp: Path, tail: float) -> float:
    """مشهد صوتي بإطارات متتابعة (جملة لكل إطار بمدتها الفعلية)؛ يعيد مدته."""
    rcfg = cfg.path("reel.render")
    frames = list(frames)
    frames[-1] = (frames[-1][0], frames[-1][1] + tail)
    total = sum(d for _, d in frames)
    lst = tmp / (out.stem + "_frames.txt")
    body = "".join(f"file '{f}'\nduration {_fmt(d)}\n" for f, d in frames) + f"file '{frames[-1][0]}'\n"
    lst.write_text(body, encoding="utf-8")
    deps.run(_base("-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(audio), "-vf",
                   f"fps={rcfg['fps']},format=yuv420p", "-af", "apad", "-t", _fmt(total), *_enc(rcfg), str(out)))
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


def _clip_scene(clip: dict, overlay: Path, out: Path, cfg, deps: Deps) -> float:
    """المقطع يملأ الشاشة الرأسية باقتطاع ثابت (يتبع الوجه)، ثم الشريط والترجمة؛ صوته كما هو."""
    rcfg = cfg.path("reel.render")
    w, h = rcfg["width"], rcfg["height"]
    crop = _crop_for(clip, cfg, deps)
    clip["crop"] = {"x": crop["x"], "source": crop["source"]}
    if crop["x"] is None:      # أبعاد المصدر مجهولة: المنتصف بتعبير يحسبه ffmpeg
        cexpr = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0"
        clip["crop"]["x"] = "center"
    else:
        cexpr = f"crop={crop['w']}:{crop['h']}:{crop['x']}:0"
    graph = (f"[0:v]{cexpr},scale={w}:{h}[v0];"
             f"[v0][1:v]overlay=0:0:shortest=1,fps={rcfg['fps']},format=yuv420p[v]")
    deps.run(_base("-i", str(clip["file"]), "-loop", "1", "-framerate", str(rcfg["fps"]), "-i", str(overlay),
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


def _assemble(script: dict, clips: dict, cfg, deps: Deps, tmp: Path, voice: str) -> tuple[list[Path], float]:
    rcfg = cfg.path("reel.render")
    date_text = datetime.now().strftime("%Y/%m/%d")
    channels = "، ".join(dict.fromkeys(s.get("channel_display", "") for i, s in enumerate(script["scenes"])
                                        if i in clips and s.get("channel_display")))
    scene_files: list[Path] = []
    total = 0.0
    for i, scene in enumerate(script["scenes"]):
        kind, out = scene.get("kind"), tmp / f"scene_{i:02d}.mp4"
        if kind in reel_script.CLIP_KINDS:
            if i not in clips:
                continue
            overlay = _save(frame_clip_overlay(cfg, scene), tmp / f"overlay_{i}.png")
            total += _clip_scene(clips[i], overlay, out, cfg, deps)
        elif kind == "title_card":
            png = _save(frame_title(cfg, scene.get("text") or script.get("title", ""), date_text), tmp / f"title_{i}.png")
            total += _still_scene(png, float(rcfg["title_seconds"]), out, cfg, deps)
        elif kind == "outro":
            png = _save(frame_outro(cfg, channels), tmp / f"outro_{i}.png")
            total += _still_scene(png, float(rcfg["outro_seconds"]), out, cfg, deps)
        elif kind in ("narration", "question"):
            audio, parts = _speech(scene.get("text", ""), voice, cfg, deps, tmp, f"s{i:02d}")
            if kind == "narration":
                frames = [(_save(frame_narration(cfg, text), tmp / f"nar_{i}_{k}.png"), dur)
                          for k, (text, dur) in enumerate(parts)]
                tail = 0.0
            else:
                png = _save(frame_question(cfg, scene.get("text", "")), tmp / f"q_{i}.png")
                frames = [(png, sum(d for _, d in parts))]
                tail = float(rcfg["question_tail_seconds"])
            total += _timed_scene(frames, audio, out, cfg, deps, tmp, tail)
        else:
            continue
        scene_files.append(out)
    return scene_files, total


def _render(path: Path, draft: dict, cfg, deps: Deps, reels_dir: Path, tmp: Path, dropped: list,
            approx: list) -> dict:
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
    scene_files, total = _assemble(script, clips, cfg, deps, tmp, voice)

    lst = tmp / "scenes.txt"
    lst.write_text("".join(f"file '{f}'\n" for f in scene_files), encoding="utf-8")
    joined = tmp / "joined.mp4"
    deps.run(_base("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)))

    rel_dir = f"{path.parent.name}"
    dest = reels_dir / rel_dir / f"{path.stem}.mp4"
    gif = reels_dir / rel_dir / f"{path.stem}.gif"
    dest.parent.mkdir(parents=True, exist_ok=True)
    lg = rcfg["logo"]
    logo = _trimmed_logo(cfg, tmp)
    # الشعار مرة واحدة فوق الفيديو المجمَّع كله: مكانه وحجمه ثابتان في كل لحظة بلا استثناء
    deps.run(_base("-i", str(joined), "-i", str(logo), "-filter_complex",
                   f"[1:v]scale={lg['width']}:-1[lg];[0:v][lg]overlay=W-w-{lg['right']}:{lg['top']}[v]",
                   "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(rcfg.get("crf", 22)),
                   "-pix_fmt", "yuv420p", "-af", _loudnorm(cfg), "-c:a", "aac", "-b:a", "128k",
                   "-ar", str(rcfg.get("audio_rate", 48000)), "-ac", "2", "-movflags", "+faststart", str(dest)))
    g = rcfg["gif"]
    deps.run(_base("-t", str(g["seconds"]), "-i", str(dest), "-vf",
                   f"fps={g['fps']},scale={g['width']}:{g['height']}:flags=lanczos,split[x][y];[x]palettegen[p];"
                   f"[y][p]paletteuse", "-loop", "0", str(gif)))
    sub = rcfg.get("repo_subdir", "reels")
    return {"reel_file": f"{sub}/{rel_dir}/{dest.name}", "reel_gif": f"{sub}/{rel_dir}/{gif.name}",
            "duration_seconds": round(total, 1),
            "render_crops": {str(i): c["crop"] for i, c in clips.items() if "crop" in c}}


def _mmss(sec) -> str:
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def _comment_text(cfg, draft: dict, result: dict, dropped: list, approx: list | None = None) -> str:
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
    try:
        result = {"render_status": "rendered", **_render(path, draft, cfg, deps, reels_dir, tmp, dropped, approx)}
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
            deps.comment(int(issue), _comment_text(cfg, draft, result, dropped, approx))
        except Exception as exc:  # noqa: BLE001 -- التعليق إخبار لا شرط للتركيب
            log.warning("تعذّر التعليق على القضية %s: %s", issue, str(exc)[:150])
    return result


# ───────────────────────────── الطابور ─────────────────────────────


def queued_reels() -> list[tuple[Path, dict]]:
    """مسودات الريل المنتظرة التركيب، الأقدم اعتمادًا أولًا."""
    import json
    out = []
    for p in sorted(store.DRAFTS_DIR.glob("*/*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if d.get("format") == "reel" and d.get("render_status") == "queued":
            out.append((p, d))
    out.sort(key=lambda pd: (pd[1].get("approved_script_at") or "", pd[0].name))
    return out


def retry(draft_id: str, cfg) -> bool:
    """يعيد ريلًا failed إلى queued (failed يجب أن يُحيا بإصلاح سببه)."""
    found = store.load_draft(draft_id)
    if not found or found[1].get("render_status") != "failed":
        return False
    store.update_draft(found[0], remove=["render_error", "render_dropped", "render_approx"],
                       render_status="queued")
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
        batch = queued_reels()[: int(cfg.path("reel.render.max_per_run", 1))]
        for path, draft in batch:
            res = render_draft(path, draft, cfg)
            print(f"{path.stem}: {res['render_status']} {res.get('render_error', '')}")
        if not batch:
            print("لا ريل منتظر التركيب")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
