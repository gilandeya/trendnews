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
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw

from . import imaging, reel_broll, reel_clips, reel_hook_search, reel_script, store, tts
from .config import MUSIC_DIR, REELS_DIR, load_config

log = logging.getLogger("trendnews.reel_render")

CAIRO = "assets/fonts/Cairo.ttf"
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


def probe_stream_durations(path) -> tuple[float | None, float | None]:
    """(مدة مسار الصورة، مدة مسار الصوت) كلٌّ على حدة بـffprobe (Issue #1436): مدة الحاوية هي الأطول بين المسارين فلا تكشف
    مشهدًا صوته أطول من صورته. مسار غائب أو N/A ← None لذاك المسار؛ عطل ffprobe كله ← (None, None) فيرجع المستدعي للمقيسة."""
    out: list[float | None] = []
    for sel in ("v:0", "a:0"):
        try:
            proc = subprocess.run(["ffprobe", "-v", "error", "-select_streams", sel, "-show_entries", "stream=duration",
                                   "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60)
            out.append(float((proc.stdout or "").strip().splitlines()[0].strip(",")) if proc.returncode == 0 else None)
        except Exception:  # noqa: BLE001 -- غياب القياس يعني الرجوع إلى مدة الحاوية لا فشل التركيب
            out.append(None)
    return out[0], out[1]


def scene_fix_plan(v: float, a: float, tol: float = 0.05) -> dict:
    """ما يلزم لتساوي مسارَي مشهد: صوت أطول ← تمديد الصورة بتثبيت آخر إطار، صورة أطول ← تمديد الصوت بصمت؛ ضمن tol لا شيء."""
    diff = a - v
    if diff > tol:
        return {"pad_video": round(diff, 3), "pad_audio": 0.0}
    if -diff > tol:
        return {"pad_video": 0.0, "pad_audio": round(-diff, 3)}
    return {"pad_video": 0.0, "pad_audio": 0.0}


class ShortRender(RuntimeError):
    """ريل نهائي أقصر من المتوقع (Issue #1436): يُعامَل عطل تركيب لكن لا يُمسّ ملف ريل سابق."""


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


# ───────────────────── لوحة إجابات السؤال: القصّ والتخطيط (Issue #1615، P2c-1) ─────────────────────

def _even(v: float, hi: float | None = None) -> int:
    """أقرب عدد زوجي (ترميز yuv420p يرفض الأبعاد الفردية)، وبعد التقريب لا يتجاوز hi (ينقص 2 إن تجاوزه)."""
    r = 2 * round(v / 2)
    if hi is not None and r > hi:
        r -= 2
    return int(max(r, 0))


def content_box(frames, cfg) -> tuple[int, int, int, int]:
    """مستطيل الصورة الفعلية (x، y، w، h) بإزالة الأشرطة السوداء من أطراف المقطع (الحماية 1). صف أو عمود أسود = متوسط سطوعه ≤
    panel.bars.threshold في كل اللقطات (الأقصى بينها، فلا يُحسب أسود صفٌّ ظهر فيه شيء في لقطة). الشريط صفوف أو أعمدة سوداء متصلة من
    الحافة نحو الداخل، وما دون panel.bars.min_fraction من البعد لا يُعتمد (حافة داكنة طبيعية). يبقى أقل من نصف العرض أو الارتفاع
    (صورة سوداء كلها أو شبهها) ← الكشف مهمل والإطار كاملًا؛ وأي عطل ← الإطار كاملًا ولا يرفع. الأعمدة تُقاس على الصفوف الباقية
    وحدها كي لا يلوّثها الشريط الأفقي. الأبعاد بمقاس اللقطات نفسه."""
    try:
        import numpy as np
        bc = cfg.path("reel.render.panel.bars") or {}
        thr, min_frac = float(bc.get("threshold", 24)), float(bc.get("min_fraction", 0.03))
        arrs = [np.asarray(f, dtype=np.float64) for f in frames]
        if not arrs or any(a.ndim != 2 for a in arrs):
            raise ValueError("لقطات غير صالحة")
        h, w = arrs[0].shape
        full = (0, 0, int(w), int(h))

        def edges(means, size):
            keep = np.flatnonzero(means > thr)
            if keep.size == 0:
                return size, 0
            a, b = int(keep[0]), int(size - 1 - keep[-1])
            return (a if a >= min_frac * size else 0), (b if b >= min_frac * size else 0)
        top, bottom = edges(np.max([a.mean(axis=1) for a in arrs], axis=0), h)
        if h - top - bottom < h / 2:
            return full
        left, right = edges(np.max([a[top:h - bottom].mean(axis=0) for a in arrs], axis=0), w)
        if w - left - right < w / 2:
            return full
        return (int(left), int(top), int(w - left - right), int(h - top - bottom))
    except Exception as exc:  # noqa: BLE001 -- كشف الأشرطة تحسين لا شرط
        log.warning("تعذّر كشف الأشرطة السوداء فالإطار كاملًا: %s", str(exc)[:100])
        try:
            h, w = frames[0].shape
            return (0, 0, int(w), int(h))
        except Exception:  # noqa: BLE001
            return (0, 0, 0, 0)


def fit_crop(src_w: int, src_h: int, content: tuple, box_w: int, box_h: int, center_x: float | None, cfg) -> dict:
    """نافذة قصّ بنسبة الصندوق box_w:box_h داخل content (x، y، w، h) (P2c-1). الأصل الارتفاع الكامل: h = ارتفاع الصورة وw = h×نسبة
    الصندوق متمركزة على center_x (المتكلم ثم أكبر وجه، وبلاه منتصف الصورة) ومحصورة داخلها، mode=full_height. مصدر أضيق من الصندوق
    (Shorts، الحماية 2) يملأ العرض ويُقصّ من الارتفاع حول panel.vertical_anchor من ارتفاع الصورة (الوجوه في أعلى الكادر غالبًا)،
    mode=fill_width. القيم زوجية ولا تتجاوز content. تُحسب مرة لكل مقطع ولكل مقاس ولا تلاحق الوجه (الحماية 3). src_w/src_h للتوقيع
    ومطابقة نداءات القصّ الأخرى؛ الحدود من content."""
    cx, cy, cw, ch = (int(v) for v in content)
    anchor = float(cfg.path("reel.render.panel.vertical_anchor", 0.4))

    def place(lo: int, hi_end: int, size: int, center: float) -> int:
        pos = _even(center - size / 2)
        first = lo + lo % 2
        last = hi_end - size
        last -= last % 2
        return min(max(pos, first), max(last, first))
    if cw * box_h >= ch * box_w:
        h = _even(ch, ch)
        w = _even(h * box_w / box_h, cw)
        mid = cx + cw / 2 if center_x is None else float(center_x)
        return {"x": place(cx, cx + cw, w, mid), "y": cy + cy % 2, "w": w, "h": h, "mode": "full_height"}
    w = _even(cw, cw)
    h = _even(w * box_h / box_w, ch)
    return {"x": cx + cx % 2, "y": place(cy, cy + ch, h, cy + ch * anchor), "w": w, "h": h, "mode": "fill_width"}


def panel_layout(n: int, cfg) -> dict:
    """تخطيط لوحة n إجابات على الشاشة (P2c-1): tiles مستطيلات (x، y، w، h) بلا تداخل تغطي الشاشة (n=1 بلا بلاطات؛ 2 نصفان فوق
    بعض؛ 3 أثلاث؛ 4 شبكة 2×2 بترتيب من الأعلى ومن اليمين؛ ما فوق 4 صفوف متساوية)، وframe الإطار البارز من panel.frame متمركزًا أفقيًا."""
    rc = cfg.path("reel.render")
    W, H = int(rc["width"]), int(rc["height"])
    fc = rc["panel"]["frame"]
    fw, fh = int(fc["width"]), int(fc["height"])
    if n <= 1:
        tiles: list = []
    elif n == 4:
        tiles = [(W // 2, 0, W // 2, H // 2), (0, 0, W // 2, H // 2), (W // 2, H // 2, W // 2, H // 2), (0, H // 2, W // 2, H // 2)]
    else:
        th = H // n
        tiles = [(0, k * th, W, th if k < n - 1 else H - k * th) for k in range(n)]
    return {"tiles": tiles, "frame": ((W - fw) // 2, int(fc["top"]), fw, fh)}


# ───────────────────── حركة الانبثاق في لوحة الإجابات (Issue #1618، P2c-2) ─────────────────────

def pop_progress(t: float, a: float, b: float, cfg) -> float:
    """معامل انبثاق بلاطة الإجابة عند الزمن t بين 0 (في البلاطة) و1 (في الإطار البارز) لإجابة نافذتها [a، b] (دالة خالصة).
    يكبر في أول pop.grow بتباطؤ في الآخر (1−(1−p)³)، يثبت على 1، ثم يعود في آخر pop.shrink بتسارع (1−q³)؛ وخارج النافذة 0.
    الكبر قبل الكلام والعودة بعده لأن المقطع يبدأ قبل كلامه وينتهي بعده بثانية."""
    pc = cfg.path("reel.render.panel.pop")
    grow, shrink = float(pc["grow"]), float(pc["shrink"])
    if t <= a or t >= b:
        return 0.0
    p = min(max((t - a) / grow, 0.0), 1.0)
    q = min(max((t - (b - shrink)) / shrink, 0.0), 1.0)
    return (1 - (1 - p) ** 3) * (1 - q ** 3)


def _pop_expr(cfg, a: float, b: float, var: str = "t") -> str:
    """تعبير ffmpeg لدالة pop_progress نفسها بالمعادلة حرفًا بحرف، بلا if/lt (القصّ بـmin/max) ليُقيَّم بالمتغير t في الاختبار.
    الضرب up×down: قبل a يكون up=0 وبعد b يكون down=0، فلا حاجة لتفرّع."""
    pc = cfg.path("reel.render.panel.pop")
    grow, shrink = _fmt(float(pc["grow"])), _fmt(float(pc["shrink"]))
    return (f"((1-pow(1-min(max(({var}-{_fmt(a)})/{grow},0),1),3))"
            f"*(1-pow(min(max(({var}-({_fmt(b)}-{shrink}))/{shrink},0),1),3)))")


def pop_start_rect(tile: tuple, tile_crop: dict | None, frame_crop: dict | None, frame: tuple | None = None) -> tuple:
    """مستطيل (x، y، w، h) على شاشة الريل الذي يشغله الإطار البارز وهو لا يزال في بلاطته قبل الكبر (دالة خالصة). منطقة frame_crop
    من المصدر بإحداثيات البلاطة: s = ارتفاع البلاطة ÷ ارتفاع tile_crop، فأول إطار من الانبثاق مطابق لما في البلاطة بكسلًا ببكسل
    في البلاطات المكدّسة؛ وفي شبكة 2×2 البلاطة أضيق من نسبة الإطار فيخرج المستطيل أعرض منها وتخفيه الشفافية. بلا قصّ محسوب
    (تعبير القصّ الاحتياطي) يتمركز المستطيل في البلاطة بارتفاعها ونسبة الإطار frame (أو البلاطة نفسها)."""
    tx, ty, tw, th = tile
    if tile_crop and frame_crop and tile_crop.get("h"):
        s = th / tile_crop["h"]
        x = tx + (frame_crop["x"] - tile_crop["x"]) * s
        y = ty + (frame_crop["y"] - tile_crop["y"]) * s
        w, h = _even(frame_crop["w"] * s), _even(frame_crop["h"] * s)
        cx, cy = x + w / 2, y + h / 2
        if x >= tx - 1 and y >= ty - 1 and x + w <= tx + tw + 1 and y + h <= ty + th + 1:
            return int(round(x)), int(round(y)), w, h
    else:
        fw, fh = (frame[2], frame[3]) if frame else (tw, th)
        w, h = _even(th * fw / fh), _even(th)
        cx, cy = tx + tw / 2, ty + th / 2
    # مستطيل خارج البلاطة (مصدر عمودي، أو شبكة 2×2) كان يبدأ أكبر من بلاطته فيبدو الانبثاق تصغيرًا: يُصغَّر بنسبة الإطار
    # ويُحصر مركزه كي يقع كله داخلها، وشفافية pop.fade تخفي فرق المحتوى
    f = min(1.0, tw / w, th / h)
    w, h = _even(w * f), _even(h * f)
    cx = min(max(cx, tx + w / 2), tx + tw - w / 2)
    cy = min(max(cy, ty + h / 2), ty + th - h / 2)
    return int(round(cx - w / 2)), int(round(cy - h / 2)), w, h


def frame_tile_labels(cfg, tiles: list, scenes: list) -> Image.Image:
    """طبقة RGBA بحجم الشاشة عليها اسم قناة كل بلاطة (channel_display) بالأبيض على رقعة كحلية بشفافية panel.label.alpha، في أسفل
    البلاطة ووسطها على بعد panel.label.bottom من حافتها السفلى؛ تُظهر للمشاهد من يتكلم قبل أن يبدأ الكلام (P2c-2)."""
    lc = cfg.path("reel.render.panel.label")
    pen = _Pen(cfg, None, transparent=True)
    navy = pen.navy + (round(255 * float(lc["alpha"])),)
    size, pad = int(lc["size"]), int(lc["pad"])
    for (tx, ty, tw, th), scene in zip(tiles, scenes):
        text = (scene.get("channel_display") or "").strip()
        if not text:
            continue
        font = pick_font(text, *pen.face(text, "display")[:1], size, pen.face(text, "display")[1])
        if font is None:
            continue
        w, h = imaging.measure(pen.d, text, font)
        cx, cy = tx + tw // 2, ty + th - int(lc["bottom"])
        half_w = min(w / 2 + pad, tw / 2)
        pen.d.rectangle((cx - half_w, cy - h / 2 - pad, cx + half_w, cy + h / 2 + pad), fill=navy)
        imaging.draw_text(pen.d, (cx, cy), text, font, pen.white, anchor="mm")
    return pen.img


def _detect_face_tracks(clip, cfg) -> tuple[int, int, list, list]:
    """لقطات من المقطع المنزَّل بمعدل speaker.fps على مدته كلها (سقفها speaker.max_frames) ← (عرض، ارتفاع، إطارات رمادية،
    صناديق كل وجه في كل لقطة). يرفع إن تعذّر قراءة المقطع؛ والمستدعي يعود إلى السلوك القديم."""
    import io

    import numpy as np
    sc = cfg.path("reel.render.speaker") or {}
    dur = probe_duration(clip)
    if not dur:
        raise RuntimeError("مدة المقطع مجهولة")
    # المعدل يُخفَّض لمقطع طويل كي تغطي لقطات السقف المقطع كله لا أوله
    rate = min(float(sc.get("fps", 5)), int(sc.get("max_frames", 60)) / dur)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(clip), "-vf", f"fps={rate:.4f}",
                          "-frames:v", str(int(sc.get("max_frames", 60))), "-f", "image2pipe", "-vcodec", "png", "-"],
                         capture_output=True, timeout=300).stdout
    sig = b"\x89PNG\r\n\x1a\n"
    pngs = [sig + part for part in raw.split(sig) if part]
    if not pngs:
        raise RuntimeError("تعذّر استخراج لقطات")
    frames, boxes, size = [], [], None
    for blob in pngs:
        img = Image.open(io.BytesIO(blob)).convert("RGB")
        size = img.size
        frames.append(np.asarray(img.convert("L")))
        boxes.append(list(imaging.face_boxes(img)))
    return size[0], size[1], frames, boxes


def _region_diff(fa, box_a, fb, box_b, top: float, bottom: float, width: float, search: float) -> float | None:
    """أصغر متوسط فرق مطلق بين منطقة من صندوق اللقطة a ومناطق اللقطة b المزاحة حول إزاحة الصندوقين الابتدائية (Issue #1427).
    البحث بدقة اللقطة الأصلية بلا تصغير: حركة رأس تُزيح الوجه كله فتجد المقارنةُ المنطقةَ نفسها في مكانها الجديد فلا تُحسب
    كلامًا، وحركة الفم وحدها تبقى فرقًا لا إزاحة تزيله. None إن لم تبقَ منطقة صالحة (أقل من 4 بكسل)."""
    import numpy as np
    ga, gb = np.asarray(fa, dtype=np.float32), np.asarray(fb, dtype=np.float32)
    x, y, w, h = box_a
    off_x = int(round((box_b[0] + box_b[2] / 2) - (x + w / 2)))
    off_y = int(round((box_b[1] + box_b[3] / 2) - (y + h / 2)))
    rad = max(3, int(round(search * w)))
    margin = rad + max(abs(off_x), abs(off_y))
    # تُقصّ المنطقة إلى ما يبقى داخل اللقطة لكل الإزاحات، فلا يُقرأ خارجها ولا يُحسب فرق على حشو
    x0, x1 = int(x + w * (1 - width) / 2), int(x + w * (1 + width) / 2)
    y0, y1 = int(y + h * top), int(y + h * bottom)
    x0, y0 = max(x0, margin), max(y0, margin)
    x1, y1 = min(x1, ga.shape[1] - margin, gb.shape[1] - margin), min(y1, ga.shape[0] - margin, gb.shape[0] - margin)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    ref = ga[y0:y1, x0:x1]
    best = None
    for dy in range(-rad, rad + 1):
        for dx in range(-rad, rad + 1):
            cand = gb[y0 + off_y + dy:y1 + off_y + dy, x0 + off_x + dx:x1 + off_x + dx]
            d = float(np.abs(cand - ref).mean())
            if best is None or d < best:
                best = d
    return best


def speaker_track(frames, boxes_per_frame, cfg) -> dict:
    """اختيار الوجه المتكلم (Issue #1427): تُربط الوجوه في مسارات عبر اللقطات، وتُحسب لكل مسار درجة = حركة الفم ÷ (حركة
    العينين + 1) بوسيط الأزواج المتتالية. {source: "speaker"|"face", center, speaker_score, tracks}؛ "face" = غير محسوم
    فيبقى أكبر وجه. دالة نقية: لا ffmpeg ولا كاشف."""
    import statistics

    import numpy as np
    sc = cfg.path("reel.render.speaker") or {}
    undecided = {"source": "face", "center": None, "speaker_score": None, "tracks": 0}
    n = len(frames)
    if n == 0:
        return undecided
    link = float(sc.get("link", 0.12)) * np.asarray(frames[0]).shape[1]
    tracks: list[dict] = []
    for k, boxes in enumerate(boxes_per_frame):
        used: set[int] = set()
        for box in boxes:
            cx = box[0] + box[2] / 2
            best = None
            for ti, t in enumerate(tracks):
                d = abs(cx - t["last"])
                if ti not in used and d < link and (best is None or d < best[0]):
                    best = (d, ti)
            if best is None:
                tracks.append({"last": cx, "obs": {}})
                ti = len(tracks) - 1
            else:
                ti = best[1]
            used.add(ti)
            tracks[ti]["obs"][k] = (box, cx)
            tracks[ti]["last"] = cx
    valid = [t for t in tracks if len(t["obs"]) / n >= float(sc.get("min_presence", 0.4))]
    if not valid:
        return undecided
    search = float(sc.get("search", 0.05))
    mtop, mwidth = float(sc.get("mouth_top", 0.6667)), float(sc.get("mouth_width", 0.6))
    e0, e1 = (float(v) for v in sc.get("eyes", [0.2, 0.45]))

    def score(t):
        vals = []
        for k, (box, _) in t["obs"].items():
            nxt = t["obs"].get(k + 1)
            if nxt is None:
                continue
            mouth = _region_diff(frames[k], box, frames[k + 1], nxt[0], mtop, 1.0, mwidth, search)
            eyes = _region_diff(frames[k], box, frames[k + 1], nxt[0], e0, e1, 1.0, search)
            if mouth is None or eyes is None:
                continue
            vals.append(mouth / (eyes + 1))
        return statistics.median(vals) if vals else 0.0

    ranked = sorted(((score(t), t) for t in valid), key=lambda st: -st[0])
    top, second = ranked[0][0], (ranked[1][0] if len(ranked) > 1 else None)

    def median(vals):
        vals = sorted(vals)
        return vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2

    # مسارات المرشَّحين للرؤية (Issue #1431) مرقّمة من اليمين إلى اليسار بوسيط الموضع والحجم؛ المستدعي يرسمها ويختار منها
    gcfg = sc.get("gesture") or {}
    g_width, g_below = float(gcfg.get("width", 3.0)), float(gcfg.get("below", 2.5))
    half = np.asarray(frames[0]).shape[1] / 2

    def gesture(t):
        # الإيماء (Issue #1434): حركة الجسد تحت الوجه بالتعويض عن الحركة نفسه؛ يد تتحرك أو إشارة إلى خريطة لا تظهر في الفم
        vals = []
        for k, (box, _) in t["obs"].items():
            nxt = t["obs"].get(k + 1)
            if nxt is None:
                continue
            d = _region_diff(frames[k], box, frames[k + 1], nxt[0], 1.0, 1.0 + g_below, g_width, search)
            if d is not None:
                vals.append(d)
        return statistics.median(vals) if vals else 0.0

    track_list = sorted(({"center": median([c for _, c in t["obs"].values()]),
                          "box": tuple(median([b[i] for b, _ in t["obs"].values()]) for i in range(4)), "score": s,
                          "gesture": gesture(t)} for s, t in ranked), key=lambda x: -x["center"])
    for tr in track_list:
        tr["centrality"] = 1 - abs(tr["center"] - half) / half
    # عاد شرط التفوق (Issue #1431): حركة الفم وحدها خدعتها لقطات أرشيفية لشخص يتكلم، فلا يكفي أن يكون الأعلى أعلى بهامش
    # ضئيل؛ يلزم ≥ talk_min و≥ margin × الثاني، وإلا يبقى أكبر وجه. مسار واحد لا ثاني له فيُحسم مباشرة
    if second is None or (top >= float(sc.get("talk_min", 0.3)) and top >= float(sc.get("margin", 1.25)) * second):
        mid = median([c for _, c in ranked[0][1]["obs"].values()])
        return {"source": "speaker", "center": mid, "speaker_score": top, "tracks": len(valid), "track_list": track_list}
    return {**undecided, "tracks": len(valid), "track_list": track_list}


def _run(cmd: list[str], timeout: int = 600) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = " ".join(reel_clips.scrub_text(proc.stderr or "").split())[-300:]
        raise RuntimeError(f"ffmpeg فشل ({proc.returncode}): {tail}")


class TranscriptUnavailable(RuntimeError):
    """تعذّر جلب نص الفيديو؛ يحمل السبب الذي أعادته `youtube_extract.fetch_transcript` (R8) فيصل إلى `render_approx` والتعليق."""


@dataclass
class Deps:
    """كل ما يلمس الشبكة أو العملية الخارجية؛ الحقل الفارغ يُملأ بالحقيقي في `resolved` والاختبارات تحقن مزيَّفات."""
    fetch_transcript: Callable[[str], str | None] | None = None
    download_clip: Callable[..., dict] | None = None
    synthesize: Callable[[str, str], dict] | None = None
    diacritize: Callable[[str], tuple] | None = None     # (نص، تنبيه) أو (نص، تنبيه، أعلام)
    run: Callable[[list], None] | None = None
    probe: Callable[[Any], float | None] | None = None
    load_points: Callable[[str], list[dict]] | None = None
    comment: Callable[[int, str], None] | None = None
    # (ملف المقطع، نِسب العيّنات) ← (عرض المصدر، ارتفاعه، مراكز أكبر وجه أفقيًا لكل لقطة فيها وجه)
    faces: Callable[[Any, list], tuple[int, int, list[float]]] | None = None
    # (ملف المقطع، cfg) ← (عرض المصدر، ارتفاعه، إطارات رمادية، صناديق كل وجه في كل إطار) لاختيار الوجه المتكلم (Issue #1427)؛
    # None أو عطل ← السلوك القديم (أكبر وجه عبر faces)
    face_tracks: Callable[[Any, Any], tuple | None] | None = None
    # (ملف المقطع، cfg) ← قائمة نتائج اللقطات الثلاث من شريط القناة (أو None)؛ لا يُرفع منه شيء مقبول
    read_chyron: Callable[[Any, Any], list | None] | None = None
    # (ملف المقطع، المسارات، المشهد، cfg) ← قائمة نتائج اللقطات الثلاث {speaker, archive, reason} (أو None)؛ يرفع عند العطل
    # والمستدعي يعود إلى حركة الفم (Issue #1431)
    pick_speaker: Callable[[Any, list, dict, Any], list | None] | None = None
    # انتظار بين إعادات التنزيل؛ حقن الاختبار يمنع الانتظار الحقيقي
    sleep: Callable[[float], None] | None = None
    # أنواع مسارات الملف؛ مقطع بلا صورة أو بلا صوت لا يُقبل (Issue #1406)
    streams: Callable[[Any], set] | None = None
    # (ملف المقطع، نِسب اللقطات) ← إطارات رمادية (مصفوفات) بمقاس المصدر لكاشف شريط الأسفل (Issue #1408)
    frames: Callable[[Any, list], list] | None = None
    # رابط ← صورة خلفية الراوي منزَّلة (أو None) بقواعد imaging.download_image؛ ومزوّدات اختيارها (Issue #1411)
    bg_image: Callable[[str], Any] | None = None
    bg_providers: dict | None = None
    # ملف مشهد ← (مدة الصورة، مدة الصوت) منفصلتين (Issue #1436)؛ المزيَّفات القديمة تحقن probe وحده فتُعطى مدتين متساويتين منه
    stream_durations: Callable[[Any], tuple] | None = None
    # بحث لقطة الهوك الآلي (Issue #1440، R5c2): (عبارة، بعد، قبل، العدد) ← [{video_id, channel, title}]؛ معرّفات ← {id: مدة ث}؛
    # (فيديو، ثوانٍ، ارتفاع، ملف) ← تنزيل أول ثوانيه؛ (ملف، ثوانٍ، cfg) ← لقطة كل ثانية؛ (صفيحة jpeg، الحدث، أول ثانية، العدد، cfg)
    # ← نتائج الثواني؛ (سيناريو، مسودة، cfg) ← عبارات. المزيَّفات القديمة تحقن download_clip ولا تعرفها: تبقى None فتُتخطى الخطوة
    # R5c3: البحث نفسه انتقل إلى مرحلة السيناريو؛ yt_search/yt_details/make_queries/judge_titles هنا لمسودة قديمة بلا hook_search وحدها
    yt_search: Callable[..., list] | None = None
    yt_details: Callable[[list], dict] | None = None
    judge_titles: Callable[..., dict] | None = None
    scan_download: Callable[..., dict] | None = None
    scan_frames: Callable[[Any, int, Any], list] | None = None
    classify_sheet: Callable[..., list] | None = None
    make_queries: Callable[[dict, dict, Any], list] | None = None
    # (جمل تحتاج لقطة [{n,dur,visual,text}]، السلاسل، cfg) ← [{n, chain}] (Issue #1452، R5d2)؛ None ← لا لقطات حدث (الصورة وحدها)
    assign_broll: Callable[[list, list, Any], list] | None = None
    # (ملف المقطع، cfg) ← قائمة graphics_top لكل لقطة من ثلاث (أو {graphics_top, what})؛ نموذج يرى اللقطات (Issue #1646، Q3).
    # None للمزيَّفات القديمة ← لا نداء ويبقى الكاشف وحده
    read_lower_graphics: Callable[[Any, Any], list | None] | None = None
    # (أسطر النص، أول سطر في الاقتباس، آخره، الاقتباس، cfg) ← {start_line, end_line, complete, display_text, reason} (Issue #1660، Q6)؛
    # None للمزيَّفات القديمة ← النافذة القديمة، وعطل النداء له المعاملة نفسها
    pick_span: Callable[..., dict] | None = None
    # (ملف المقطع، cfg) ← [(بداية، نهاية)] لفترات الصمت بثواني الملف (silencedetect)؛ None ← لا ضبط على الصمت فيبقى التقدير
    detect_silence: Callable[[Any, Any], list] | None = None

    def resolved(self, cfg) -> "Deps":
        # جلسة واحدة للتركيب كله كالجمع (R8)؛ تُنشأ عند أول جلب لا عند الاستيراد
        session_box: list = []

        def fetch(video_id):
            import requests

            from . import proxy_config, youtube_extract
            if not session_box:
                session_box.append(requests.Session())
            backoff = list(cfg.path("reel.render.transcript_backoff_seconds", [15, 45]))
            # _fetch_once يُقرأ وقت الاستدعاء لا عند تعريف الدالة كي يبقى قابلًا للحقن
            text, info, _ = youtube_extract.fetch_transcript(
                video_id, proxy_config.get_proxy_config(), session_box[0], backoff,
                fetch_once=youtube_extract._fetch_once)
            if text is None:
                # fetch_transcript لا ترفع عند الفشل بل تعيد سببه؛ بلا رفعه هنا يضيع السبب الحقيقي (قضيتا #1620 و#1634)
                raise TranscriptUnavailable(info or "")
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
        real = self.download_clip is None
        return replace(
            self,
            fetch_transcript=self.fetch_transcript or fetch,
            download_clip=self.download_clip or download,
            synthesize=self.synthesize or (lambda text, voice: tts.synthesize(text, voice, cfg)),
            diacritize=self.diacritize or (lambda text: tts.diacritize_full(text, cfg)),
            run=self.run or (lambda cmd: _run(cmd, timeout)),
            probe=self.probe or probe_duration,
            load_points=self.load_points or points,
            faces=self.faces or _detect_faces,
            # مزيَّفات الاختبار القديمة تحقن faces أو download_clip ولا تعرف الحقلين الجديدين: تُعطى سلوكًا لا يغيّر شيئًا
            # فلا يلمس أي اختبار ffmpeg حقيقيًا ولا شبكة؛ الحقيقيان لا يُستعملان إلا حين لا حقن إطلاقًا
            face_tracks=self.face_tracks or (_detect_face_tracks if self.faces is None else (lambda clip, c: None)),
            read_chyron=self.read_chyron or (_real_read_chyron if self.download_clip is None else (lambda clip, c: None)),
            read_lower_graphics=self.read_lower_graphics or (
                _real_read_lower_graphics if self.download_clip is None and self.faces is None else None),
            pick_span=self.pick_span or ((lambda segs, a, b, q, c: reel_clips.thought_span(segs, a, b, q, c)) if real else None),
            detect_silence=self.detect_silence or (_real_detect_silence if real else None),
            pick_speaker=self.pick_speaker or (_real_pick_speaker if self.download_clip is None else (lambda *a: None)),
            sleep=self.sleep or time.sleep,
            streams=self.streams or probe_streams,
            stream_durations=self.stream_durations or (
                probe_stream_durations if self.probe is None else (lambda p: (self.probe(p), self.probe(p)))),
            frames=self.frames or (lambda clip, fractions: _extract_gray_frames(clip, fractions)),
            bg_image=self.bg_image or (lambda url: imaging.download_image(url)),
            comment=self.comment or comment,
            # الحقيقي لا يُملأ إلا حين لا حقن إطلاقًا (download_clip=None)؛ وإلا None وتُتخطى الخطوة بلا أي نداء شبكة
            yt_search=self.yt_search or (reel_hook_search.real_yt_search if real else None),
            yt_details=self.yt_details or (reel_hook_search.real_yt_details if real else None),
            judge_titles=self.judge_titles or (
                (lambda items, event, c: reel_hook_search.call_judge_titles(items, event, c)) if real else None),
            scan_download=self.scan_download or (reel_hook_search.real_scan_download if real else None),
            scan_frames=self.scan_frames or (reel_hook_search.real_scan_frames if real else None),
            classify_sheet=self.classify_sheet or (
                (lambda jpeg, event, first, n, c, labels=None: reel_hook_search.call_classify_model(
                    jpeg, event, first, n, c, labels=labels)) if real else None),
            assign_broll=self.assign_broll or ((lambda needy, chains, c: reel_broll.assign(needy, chains, c)) if real else None),
            make_queries=self.make_queries or (
                (lambda script, draft, c, broad=False: reel_hook_search.call_make_queries(script, draft, c, broad=broad))
                if real else None))


# ───────────────────── صورة خلفية الراوي (Issue #1411، R3b-2b) ─────────────────────


def _default_providers() -> dict:
    """المزوّدات الحقيقية؛ دالة لا ثابت كي يستبدلها الاختبار فتبقى الخلفية الكحلية في كل اختبار لا يحقن مزوّدات."""
    from . import imagesearch, youtube_extract
    return {"news": youtube_extract.news_photo_candidates, "web": imagesearch.search_web_images,
            "free": youtube_extract.photo_candidates, "download": lambda url: imaging.download_image(url)}


_URL_YM = re.compile(r"/((?:19|20)\d\d)/(0?[1-9]|1[0-2])(?:/|$)")
_URL_Y = re.compile(r"/((?:19|20)\d\d)(?:/|$)")


def stale_url_reason(url: str, draft_date: str | None) -> str | None:
    """سبب رفض رابط يدل على تاريخ قديم (Issue #1423): /YYYY/MM/ أقدم من الشهر السابق لتاريخ المسودة، أو /YYYY/ وحدها بسنة
    أقدم من سنة المسودة. الشهر السابق لا الحالي كي تُقبل صورة نُشرت قبيل الخبر. تاريخ مسودة غير مقروء ← لا رفض."""
    from urllib.parse import urlparse
    m = re.match(r"(\d{4})-(\d{2})", draft_date or "")
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    py, pm = (y, mo - 1) if mo > 1 else (y - 1, 12)
    path = urlparse(url).path
    found = _URL_YM.search(path)
    if found:
        uy, um = int(found.group(1)), int(found.group(2))
        return f"رابطها يدل على {uy}/{um:02d} وهو أقدم من {py}/{pm:02d}" if (uy, um) < (py, pm) else None
    found = _URL_Y.search(path)
    if found and int(found.group(1)) < y:
        return f"رابطها يدل على سنة {found.group(1)} وهي أقدم من {y}"
    return None


def face_reason(cfg, img) -> str | None:
    """سبب رفض صورة فيها وجه بمساحة ≥ image.face_min_ratio (لا نعرض شخصًا لا يتكلم في الريل)؛ عطل الكشف ← لا رفض."""
    try:
        iw, ih = img.size
        faces = imaging.face_boxes(img.convert("RGB"))
    except Exception as exc:  # noqa: BLE001 -- الكشف تحسين لا شرط (وحقن الاختبار قد يعيد غير صورة)
        log.debug("تعذّر كشف الوجوه في مرشّح الخلفية: %s", str(exc)[:100])
        return None
    ratio = float(cfg.path("image.face_min_ratio", 0.02))
    return "فيها وجه كبير" if any(fw * fh >= ratio * iw * ih for _, _, fw, fh in faces) else None


def pick_background(draft: dict, cfg, providers: dict | None = None, draft_date: str | None = None) -> dict:
    """يختار صورة خلفية الراوي بسلّم كسول: يدوية ← صورة خبر ← بحث ويب ← حرة (بحارس الوجه القائم) ← لا شيء.
    لا تُستدعى درجة إن نجحت السابقة؛ المرشّح يُقبل إن نجح تنزيله ولم يكن فيه وجه كبير ولم يدل رابطه على تاريخ قديم
    (كل رفض يُسجَّل بسببه). draft_date تاريخ مجلد المسودة (YYYY-MM-DD) وإلا اليوم. يعيد {url, kind, publisher} والرابط
    وحده لا الملف. عطل أي مزوّد يُسجَّل ويُنتقل إلى الدرجة التالية، فالاختيار لا يرفع أبدًا."""
    pv = {**_default_providers(), **(providers or {})}
    manual = (draft.get("manual_image") or "").strip()
    if manual:
        return {"url": manual, "kind": "manual", "publisher": ""}
    draft_date = draft_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
            if not url:
                return False
            reason = stale_url_reason(url, draft_date)
            if not reason:
                img = pv["download"](url)
                if img is None:
                    return False
                reason = face_reason(cfg, img)
            if reason:
                log.info("رُفض مرشّح خلفية الراوي %s: %s", url[:80], reason)
                return False
            return True
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
    """يحوّل الصورة المنزَّلة إلى طبقة خلفية 1080×1920 مظلَّلة بالكحلي shade_a. الاقتطاع الأفقي يتوسّط مراكز الوجوه
    كاقتطاع المقاطع، وإلا المنتصف. تخطيط واحد "A" (حُذف تخطيط الصندوق السفلي في Issue #1423: صورة فيها وجه كبير تُرفض
    عند الاختيار، واليدوية تُعرض بالتخطيط نفسه). يعيد {"layout": "A", "image": RGB}."""
    b = cfg.path("reel.render.background")
    w, h = int(cfg.path("reel.render.width")), int(cfg.path("reel.render.height"))
    img = img.convert("RGB")
    iw, ih = img.size
    try:
        faces = imaging.face_boxes(img)
    except Exception as exc:  # noqa: BLE001 -- الكشف تحسين لا شرط
        log.warning("تعذّر كشف الوجوه في خلفية الراوي: %s", str(exc)[:100])
        faces = []
    scale = max(w / iw, h / ih)
    sw, sh = max(w, round(iw * scale)), max(h, round(ih * scale))
    cx = sum(x + fw / 2 for x, _, fw, _ in faces) / len(faces) if faces else iw / 2
    left = min(max(round(cx * scale - w / 2), 0), sw - w)
    top = (sh - h) // 2
    raw = img.resize((sw, sh), Image.LANCZOS).crop((left, top, left + w, top + h))
    navy = imaging.hex_rgb(cfg.path("brand.primary_color"))
    out = Image.blend(raw, Image.new("RGB", raw.size, navy), float(b["shade_a"]))
    # wide: الصورة كاملة بنسبتها مكبَّرة لتغطي (العرض×pan_zoom، الارتفاع×pan_zoom)؛ raw مقتطعة مسبقًا 1080 عرضًا فلا مدى أفقيًا
    # فيها يكفي حركة بطيئة طوال المشهد (Issue #1447، متابعة R5d1). مركز الوجوه بإحداثياتها لتتمركز نافذة الحركة حوله
    zoom = max(float(cfg.path("reel.render.narration_bg.pan_zoom", 1.12)), float(cfg.path("reel.render.hook.pan_zoom", 1.12)))
    wscale = max(w * zoom / iw, h * zoom / ih)
    wide = img.resize((max(w, round(iw * wscale)), max(h, round(ih * wscale))), Image.LANCZOS)
    # raw للهوك وحده: يُظلَّل بـhook.shade فقط، فلا يتراكب على تظليل الراوي shade_a فتكاد الصورة لا تُرى (Issue #1429)
    return {"layout": "A", "image": out, "raw": raw, "wide": wide, "wide_cx": cx * wscale}


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


def _fit(draw, text, font_path, max_width, max_lines, start, minimum, weight, line_factor):
    """imaging.fit_text بمعامل مسافة اختياري؛ بلا معامل يبقى النداء القديم نفسه."""
    if line_factor is None:
        return imaging.fit_text(draw, text, font_path, max_width, max_lines, start, minimum, weight)
    return imaging.fit_text(draw, text, font_path, max_width, max_lines, start, minimum, weight, line_factor=line_factor)


_ARABIC_RE = re.compile("[\u0600-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeff]")
_LATIN_RE = re.compile("[A-Za-z\u00c0-\u024f]")


def latin_only(text: str) -> bool:
    """سطر لاتيني خالص: فيه حرف لاتيني ولا حرف عربي. المختلط يبقى بخط العربية كاملًا (Issue #1441)."""
    return bool(_LATIN_RE.search(text)) and not _ARABIC_RE.search(text)


def face(cfg, text: str, kind: str) -> tuple[str, str | None]:
    """(مسار الخط، الوزن) لنص في الريل (Issue #1441): اللاتيني الخالص Kalam-Bold، وغيره Playpen بوزن العناوين (display)
    أو النصوص (body)."""
    f = cfg.path("reel.render.fonts")
    if latin_only(text):
        return f["latin"], None
    return f["arabic"], f["display_weight" if kind == "display" else "body_weight"]


def size_pair(cfg, key: str) -> tuple[int, int]:
    """(حجم البداية، الأدنى) لنص كبير من reel.render.sizes."""
    s = cfg.path("reel.render.sizes")[key]
    return int(s[0]), int(s[1])


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
        # الهامشان متساويان بعرض عمود الأزرار فيقع مركز النص في منتصف الشاشة تمامًا (كان x0=60 يزيحه 35 بكسل يسارًا)
        self.x1 = self.w - int(r["safe"]["right_col_width"])
        self.x0 = int(r["safe"]["right_col_width"])
        self.cx = (self.x0 + self.x1) // 2
        self.max_w = self.x1 - self.x0
        self.cfg = cfg

    def font(self, path: str, size: int, weight: str | None = None):
        return imaging.load_font(path, size, weight)

    def face(self, text: str, kind: str) -> tuple[str, str | None]:
        return face(self.cfg, text, kind)

    def fnt(self, text: str, kind: str, size: int):
        return imaging.load_font(*self.face(text, kind)[:1], size, self.face(text, kind)[1])

    def ink(self, text: str, font, xy, anchor: str, ltr: bool = False) -> tuple:
        """صندوق الحبر الفعلي لنص يُرسم عند xy بالمرساة نفسها (النص المحضَّر والخيارات نفسها كالرسم).
        التقدّم بـsize×1.45 من نقطة الرسم لا من الحبر هو ما أخفى تداخل الشريط السفلي عن اختبار المنطقة الآمنة."""
        if ltr:
            kw = {"direction": "ltr", "language": "en"} if imaging.HAS_RAQM else {}
            return self.d.textbbox(xy, text, font=font, anchor=anchor, **kw)
        return self.d.textbbox(xy, imaging._prepare(text), font=font, anchor=anchor, **imaging._kwargs())

    def line(self, text: str, font, fill, y: int, *, align: str = "center", ltr: bool = False, dx: int = 0) -> int:
        """سطر واحد؛ يعيد y التالي. المحاذاة وسطية أو يمينية عند الحدّ الآمن."""
        _, h = imaging.measure(self.d, text, font)
        lh = int(font.size * 1.45) if hasattr(font, "size") else h
        xy, anchor = ((self.cx, y), "ma") if align == "center" else ((self.x1 - dx, y), "ra")
        if ltr:
            imaging.draw_text_ltr(self.d, xy, text, font, fill, anchor=anchor)
        else:
            imaging.draw_text(self.d, xy, text, font, fill, anchor=anchor)
        self.boxes.append(tuple(self.ink(text, font, xy, anchor, ltr)))
        return y + lh

    def ink_line(self, text: str, font_path: str, weight: str | None, size: int, fill, *, prev_bottom: int | None,
                 gap: int, limit: int, min_size: int | None = None, ltr: bool = False, warn: bool = True,
                 y_top: int | None = None) -> int | None:
        """سطر يمينيّ يوضع بحبره: أعلى حبره = prev_bottom + gap (أو y_top)، ويُصغَّر بخطوة 2 حتى min_size إن تجاوز حبره
        الحدّ السفلي limit أو خرج عن x0..x1 أفقيًا (كان التصغير للحد السفلي وحده فبدأ حبر سطر طويل عند x=−294).
        يعيد أسفل حبره، أو None (مع تحذير إن warn) إن لم يسعه الحدّان أو غاب حرفه من كل الخطوط."""
        for sz in range(size, (min_size if min_size is not None else size) - 1, -2):
            font = pick_font(text, font_path, sz, weight)
            if font is None:
                return None
            left0, top0, right0, bottom0 = self.ink(text, font, (self.x1, 0), "ra", ltr)
            y = (y_top if y_top is not None else prev_bottom + gap) - top0
            # حبر Playpen وKalam يتجاوز مرساة اليمين بكسلين أحيانًا (انحياز جانبي): يُزاح السطر يسارًا بالتجاوز فلا يتخطى حبره x1
            over = max(0, right0 - self.x1)
            if y + bottom0 <= limit and left0 - over >= self.x0:
                return self.line_at(text, font, fill, y, ltr, over)
        if warn:
            log.warning("سطر لا يسع الشريط السفلي فحُذف: %r", text[:40])
        return None

    def line_at(self, text: str, font, fill, y: int, ltr: bool, over: int = 0) -> int:
        self.line(text, font, fill, y, align="right", ltr=ltr, dx=over)
        return int(self.boxes[-1][3])

    def text_line(self, text: str, font_path: str, weight: str | None, size: int, fill, y: int, *,
                  align: str = "center", ltr: bool = False) -> int:
        """سطر بحارس الخط: ينتقل إلى Cairo عند حرف غائب، ويُحذف السطر إن بقي ناقصًا. يعيد y التالي."""
        font = pick_font(text, font_path, size, weight)
        if font is None:
            return y
        return self.line(text, font, fill, y, align=align, ltr=ltr)

    def block(self, text: str, font_path: str, weight: str | None, fill, y_mid: int, *, start: int, minimum: int,
              max_lines: int = 8, align: str = "center", y_top: int | None = None,
              line_factor: float | None = None) -> int:
        """نص متعدد الأسطر يُصغَّر ليسع العرض الآمن؛ يتمركز رأسيًا حول y_mid (أو يبدأ من y_top)."""
        font, lines, lh = _fit(self.d, text, font_path, self.max_w, max_lines, start, minimum, weight, line_factor)
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
                    minimum: int, max_lines: int = 8, line_factor: float | None = None) -> None:
        """block وسطيّ بالتخطيط نفسه (حجم الخط وتقسيم الأسطر من الجملة كاملة) لكن يُرسم منه ما كُتب حتى prefix.
        الحروف لا تتحرك: السطر الجزئي يُحاذى بحافة حبره اليمنى عند حافة السطر نفسه مكتملًا، ولا يبدأ سطر قبل اكتمال سابقه.
        العدّ بالحروف غير المسافة لأن prefix قد تتغير مسافاته، وتقسيم الأسطر لا يغيّر الحروف نفسها."""
        font, lines, lh = _fit(self.d, text, font_path, self.max_w, max_lines, start, minimum, weight, line_factor)
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
    bfont = p.fnt(badge, "display", 54)
    bw, bh = imaging.measure(p.d, badge, bfont)
    top = 520
    p.d.rounded_rectangle((p.cx - bw // 2 - 40, top, p.cx + bw // 2 + 40, top + bh + 50), radius=28,
                          fill=imaging.hex_rgb(r.get("badge_bg", "#8EC5FF")))
    p.line(badge, bfont, p.navy, top + 14)
    (fpath, fw), lf = p.face(title, "display"), float(cfg.path("reel.render.fonts.line_factor"))
    y_top, below = top + bh + 110, 206      # below: القاعدة والتاريخ والمعرّف تحت العنوان
    start, minimum = 96, 52
    # العنوان الأكبر لا يدفع التاريخ والمعرّف خارج المنطقة الآمنة: يُصغَّر (max_lines كما هو) حتى يسعهما
    floor = 52           # الحجم القديم: أدنى ما يُصغَّر إليه العنوان الطويل جدًا ليبقى كل شيء في المنطقة الآمنة
    while start > floor:
        _, lines_, lh_ = _fit(p.d, title, fpath, p.max_w, 6, start, min(minimum, start), fw, lf)
        if y_top + lh_ * len(lines_) + below <= p._safe()[1]:
            break
        start -= 2
    y = p.block(title, fpath, fw, p.white, 0, start=start, minimum=min(minimum, start), max_lines=6, y_top=y_top,
                line_factor=lf)
    p.rule(y + 30)
    y = p.line(date_text, p.fnt(date_text, "body", 44), p.gold, y + 70)
    handle = cfg.path("brand.handle") or "@almujez"
    p.line(handle, p.fnt(handle, "body", 44), p.white, y + 10, ltr=True)
    return p.rgb()


def frame_hook_text(cfg, title: str, boxes=None, transparent: bool = True) -> Image.Image:
    """نص الهوك (Issue #1429): عنوان السيناريو بالرقعة أبيض متمركزًا رأسيًا حول hook.text_y داخل المنطقة الآمنة. شفاف فوق
    خلفية متحركة، وبلا خلفية يُرسم على الكحلي الثابت."""
    p = _Pen(cfg, boxes, transparent=transparent)
    (fpath, fw), lf = p.face(title, "display"), float(cfg.path("reel.render.fonts.line_factor"))
    start, minimum = size_pair(cfg, "hook")
    p.block(title, fpath, fw, p.white, int(cfg.path("reel.render.hook.text_y", 1180)), start=start,
            minimum=minimum, max_lines=4, line_factor=lf)
    return p.img if transparent else p.rgb()


def _narration_pen(cfg, sentence: str, boxes, bg: dict | None):
    """لوحة الراوي ومعاملات نصها. بلا خلفية: كحلي، وسط الشاشة. بخلفية: لوحة شفافة والنص كما هو (تخطيط واحد).
    الأحجام 160/140 وأربعة أسطر (Issue #1423): حروف الرقعة أصغر بصريًا من Tajawal (حبر «ومن»: XB 72 ← 56 بكسل، الرقعة 108
    ← 60)، فـ«أكبر 50%» في #1419 لم يتحقق؛ والجملة التي لا تسع تُقسم إلى مقاطع (narration_segments)."""
    # بخلفية: إطار شفاف بلا صورة (الخلفية تيار فيديو مستقل يتحرك تحته، Issue #1447)؛ بلا خلفية: الكحلي كما كان
    p = _Pen(cfg, boxes, transparent=bg is not None)
    start, minimum = size_pair(cfg, "narration")
    return p, dict(y_mid=860, start=start, minimum=minimum, max_lines=4)


def _narration_font(cfg, bg: dict | None, text: str = "") -> tuple[str, str | None, float | None]:
    """خط الراوي ووزنه ومعامل مسافته: Playpen Bold (Issue #1441)."""
    path, weight = face(cfg, text, "body")
    return path, weight, float(cfg.path("reel.render.fonts.line_factor"))


def frame_narration(cfg, sentence: str, boxes=None, bg: dict | None = None) -> Image.Image:
    p, kw = _narration_pen(cfg, sentence, boxes, bg)
    fpath, fw, lf = _narration_font(cfg, bg, sentence)
    p.block(sentence, fpath, fw, p.white, kw["y_mid"], start=kw["start"], minimum=kw["minimum"],
            max_lines=kw["max_lines"], line_factor=lf)
    return p.img if bg is not None else p.rgb()


def frame_narration_typed(cfg, sentence: str, prefix: str, boxes=None, bg: dict | None = None) -> Image.Image:
    """إطار الراوي وقد كُتب من الجملة ما قبل prefix. الجملة كاملة ← frame_narration نفسه بالبكسل."""
    if sum(1 for c in prefix if not c.isspace()) >= sum(1 for c in sentence if not c.isspace()):
        return frame_narration(cfg, sentence, boxes, bg)
    p, kw = _narration_pen(cfg, sentence, boxes, bg)
    fpath, fw, lf = _narration_font(cfg, bg, sentence)
    p.typed_block(sentence, prefix, fpath, fw, p.white, kw["y_mid"], start=kw["start"], minimum=kw["minimum"],
                  max_lines=kw["max_lines"], line_factor=lf)
    return p.img if bg is not None else p.rgb()


# ───────────── ظهور الراوي سطرًا فسطرًا (Issue #1419) ─────────────


def _nonspace(text: str) -> int:
    return sum(1 for c in text if not c.isspace())


def _fits(draw, text: str, font, max_w: int, max_lines: int) -> bool:
    return len(imaging.wrap(draw, text, font, max_w)) <= max_lines


def _split_mid(draw, text: str, font, max_w: int, max_lines: int) -> list[str]:
    """مقطع بلا فاصلة لا يسع: يُقسم عند أقرب مسافة لمنتصفه، ويتكرر على كل نصف حتى يسع. كلمة واحدة لا تُقسم أبدًا."""
    if _fits(draw, text, font, max_w, max_lines) or " " not in text:
        return [text]
    mid = len(text) / 2
    cut = min((i for i, c in enumerate(text) if c == " "), key=lambda i: abs(i - mid))
    return (_split_mid(draw, text[:cut], font, max_w, max_lines)
            + _split_mid(draw, text[cut + 1:], font, max_w, max_lines))


def narration_segments(cfg, sentence: str, bg: dict | None = None) -> list[str]:
    """وحدات العرض «مقاطع» من الجملة: تسع الجملة خمسة أسطر بأصغر حجم (80) فمقطع واحد، وإلا تُقسم عند «،» و«؛» إلى أقل
    عدد من المقاطع يسع كلًّا منها (تقسيم جشع من أولها)، والمقطع الذي لا يسعه فاصلة يُقسم عند مسافة. لا كلمة تُحذف
    أو تتكرر: وصل المقاطع بمسافة يساوي الجملة بعد توحيد مسافاتها."""
    sentence = " ".join(sentence.split())
    p, kw = _narration_pen(cfg, sentence, [], bg)
    fpath, fw, _ = _narration_font(cfg, bg, sentence)
    font = imaging.load_font(fpath, kw["minimum"], fw)
    if _fits(p.d, sentence, font, p.max_w, kw["max_lines"]):
        return [sentence]
    clauses = re.split(r"(?<=[،؛])\s+", sentence)
    out: list[str] = []
    cur = ""
    for clause in clauses:
        joined = f"{cur} {clause}".strip()
        if _fits(p.d, joined, font, p.max_w, kw["max_lines"]):
            cur = joined
            continue
        if cur:
            out.append(cur)
        cur = ""
        if _fits(p.d, clause, font, p.max_w, kw["max_lines"]):
            cur = clause
        else:
            out.extend(_split_mid(p.d, clause, font, p.max_w, kw["max_lines"]))
    if cur:
        out.append(cur)
    return out


def narration_lines(cfg, segment: str, bg: dict | None = None) -> list[str]:
    """أسطر المقطع كما ستُرسم (حجم الخط من المقطع كاملًا فلا يتغير بين الإطارات)."""
    p, kw = _narration_pen(cfg, segment, [], bg)
    fpath, fw, lf = _narration_font(cfg, bg, segment)
    return _fit(p.d, segment, fpath, p.max_w, kw["max_lines"], kw["start"], kw["minimum"], fw, lf)[1]


def reveal_steps(line_chars: list[int], speech_seconds: float, hold_seconds: float, fps: float,
                 fade: float) -> list[tuple[tuple, float]]:
    """خطوات ظهور أسطر مقطع: [(شفافية كل سطر 0..1، المدة)]. السطر k يبدأ عند نسبة حروف ما قبله (غير المسافة) من مدة
    الكلام ويتلاشى خلال fade بإطارات على fps؛ ما استقر من الحالات المتتالية يُدمج. آخر حالة (كل الأسطر كاملة) تبقى
    حتى نهاية الصمت. المجموع = الكلام + الصمت."""
    frame = 1.0 / fps
    speech = max(float(speech_seconds), 0.0)
    total = speech + max(float(hold_seconds), 0.0)
    n = len(line_chars)
    all_chars = sum(line_chars) or 1
    starts = [speech * sum(line_chars[:k]) / all_chars for k in range(n)]
    fade = max(float(fade), frame)
    full = (1.0,) * n
    steps: list[list] = []
    i = 0
    while i * frame < total - 1e-9:
        t = i * frame
        state = tuple(round(min(max((t - s) / fade, 0.0), 1.0), 4) for s in starts)
        if state == full:
            break
        dur = min(frame, total - t)
        if steps and steps[-1][0] == state:
            steps[-1][1] += dur
        else:
            steps.append([state, dur])
        i += 1
    rest = total - sum(d for _, d in steps)
    if rest > 1e-9:
        steps.append([full, rest])
    return [(s, d) for s, d in steps] or [(full, max(total, frame))]


def frame_narration_reveal(cfg, segment: str, alphas, boxes=None, bg: dict | None = None) -> Image.Image:
    """إطار مقطع الراوي وسطوره بشفافياتها: التخطيط (حجم الخط وأماكن الأسطر) من المقطع كاملًا فلا يتحرك سطر بعد اكتمال
    ظهوره، والسطر الظاهر جزئيًا يصعد reveal.rise بكسل إلى موضعه. كل الشفافيات 1 ← frame_narration نفسه بالبكسل."""
    p, kw = _narration_pen(cfg, segment, boxes, bg)
    fpath, fw, lf = _narration_font(cfg, bg, segment)
    font, lines, lh = _fit(p.d, segment, fpath, p.max_w, kw["max_lines"], kw["start"], kw["minimum"], fw, lf)
    total = lh * len(lines)
    safe = p._safe()
    y = max(safe[0], min(int(kw["y_mid"] - total / 2), safe[1] - total))
    rise = float(cfg.path("reel.render.reveal.rise", 0) or 0)
    for k, ln in enumerate(lines):
        a = float(alphas[k]) if k < len(alphas) else 1.0
        if a > 0:
            yy = y + round(rise * (1 - a))
            xy = (p.cx, yy)
            if a >= 1.0:
                imaging.draw_text(p.d, xy, ln, font, p.white, anchor="ma")
            else:
                layer = Image.new("RGBA", p.img.size, (0, 0, 0, 0))
                imaging.draw_text(ImageDraw.Draw(layer), xy, ln, font, p.white, anchor="ma")
                layer.putalpha(layer.getchannel("A").point(lambda v, a=a: int(v * a)))
                p.img.alpha_composite(layer)
            p.boxes.append(tuple(p.ink(ln, font, xy, "ma")))
        y += lh
    return p.img if bg is not None else p.rgb()


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
    qfont = p.fnt("؟", "display", 170)
    # مركز الحبر الفعلي لا مركز مربع الخط عند مركز الدائرة (Issue #1429): الذيل السفلي كان يخرج منها بإزاحة ثابتة
    ink = p.ink("؟", qfont, (p.cx, 0), "ma")
    imaging.draw_text(p.d, (p.cx + p.cx - (ink[0] + ink[2]) / 2, cy - (ink[1] + ink[3]) / 2), "؟", qfont, p.navy, anchor="ma")
    (fpath, fw), lf = p.face(question, "display"), float(cfg.path("reel.render.fonts.line_factor"))
    start, minimum = size_pair(cfg, "question")
    share_text = cfg.path("reel.render.texts.share")
    share_font = p.fnt(share_text, "body", 46)
    # السؤال يبدأ بحبره تحت الدائرة بـ50 بكسلًا (لا يتمركز حول نقطة فيلامسها حين يطول) وينتهي حبره قبل «شاركونا» بـ30
    top_ink = cy + r + 50
    bottom_ink = p.ink(share_text, share_font, (p.cx, 1250), "ma")[1] - 30
    best = None
    for max_lines in range(8, 0, -1):
        for size in range(start, min(minimum, start) - 1, -2):
            font, lines_, lh_ = _fit(p.d, question, fpath, p.max_w, max_lines, size, min(minimum, size), fw, lf)
            if not lines_:
                continue
            y = top_ink - min(p.ink(ln, font, (p.cx, 0), "ma")[1] for ln in lines_)
            low = y + (len(lines_) - 1) * lh_ + max(p.ink(ln, font, (p.cx, 0), "ma")[3] for ln in lines_)
            best = (font, lines_, lh_, y)
            if low <= bottom_ink:
                break
        else:
            continue
        break
    if best is not None:        # أصغر محاولة تُعتمد إن لم يسع شيء (سؤال شاذ الطول) ولا يُحذف النص
        font, lines_, lh_, y = best
        for ln in lines_:
            imaging.draw_text(p.d, (p.cx, y), ln, font, p.white, anchor="ma")
            p.boxes.append(tuple(p.ink(ln, font, (p.cx, y), "ma")))
            y += lh_
    p.line(share_text, share_font, p.gold, 1250)
    return p.rgb()


def _logo_ratio(cfg) -> float | None:
    """ارتفاع الشعار ÷ عرضه بعد قصّ هوامشه الشفافة (كما يُركَّب)، أو None إن غاب الملف."""
    src = imaging.find_logo(cfg.path("brand.logo"))
    if src is None:
        return None
    try:
        img = Image.open(src).convert("RGBA")
        bbox = img.getchannel("A").getbbox() or (0, 0, *img.size)
        return (bbox[3] - bbox[1]) / max(bbox[2] - bbox[0], 1)
    except Exception:  # noqa: BLE001 -- ملف تالف يعامَل كغائب فتعود العبارة
        return None


def frame_outro(cfg, channels: str, boxes=None, credit: str = "", transparent: bool = False) -> Image.Image:
    p = _Pen(cfg, boxes, transparent=transparent)
    t = cfg.path("reel.render.texts")
    ratio = _logo_ratio(cfg)
    if ratio is not None:
        # الشعار الكبير (يبلغه الشعار المتحرك في التمريرة الأخيرة) يحلّ محلّ «تابعوا الموجز»؛ الإطار يترك له موضعه ويرسم
        # ما بعده يُزاح بارتفاعه (Issue #1592، R5h)
        oc = cfg.path("reel.render.outro")
        y = int(oc["logo_top"]) + round(int(oc["logo_width"]) * ratio)
    else:
        # بلا شعار: العبارة كما كانت احتياطًا، بحجم 162 يُصغَّر عند الحاجة حتى يسع العرض الآمن
        size, (ffont, fweight) = int(cfg.path("reel.render.sizes.follow")), p.face(t["follow"], "display")
        while size > 40:
            font = pick_font(t["follow"], ffont, size, fweight)
            if font is None:
                break
            box = p.ink(t["follow"], font, (p.cx, 0), "ma")
            if box[2] - box[0] <= p.max_w:
                break
            size -= 2
        y = p.text_line(t["follow"], ffont, fweight, size, p.white, 560)
    # لا خط ذهبي تحت الشعار الكبير (P1a، Issue #1600): الشعار يكفي فاصلًا، وما تحته يبقى في مواضعه
    y = p.block(t["tagline"], *p.face(t["tagline"], "body"), p.white, 0, start=52, minimum=36, max_lines=3, y_top=y + 60)
    handle = cfg.path("brand.handle") or "@almujez"
    p.line(handle, p.fnt(handle, "body", 54), p.gold, y + 20, ltr=True)
    clips = t["clips_from"].format(channels=channels)
    y = p.block(clips, *p.face(clips, "body"), (200, 208, 224), 0, start=36, minimum=26, max_lines=4, y_top=1180)
    if credit:
        _credit_line(p, cfg, credit, y)
    return p.img if transparent else p.rgb()


def _credit_line(p: "_Pen", cfg, credit: str, y: int) -> None:
    """سطر مصدر الصورة المستقل بخط سطر «المقاطع من» نفسه، يُصغَّر حتى يسع عرض النص الآمن فلا يُقسم أبدًا.
    اسم لاتيني بقي بلا مقابل عربي (نطاق موقع) يُرسم وحده LTR ملاصقًا لـ«الصورة:» على يسارها: سطر bidi واحد يقلب النقاط
    والشرطات في النطاق."""
    label, _, name = credit.partition(": ")
    latin = bool(name) and bool(re.search(r"[A-Za-z]", name)) and not re.search(r"[؀-ۿ]", name)
    fill = (200, 208, 224)
    for size in range(36, 15, -2):
        font = p.fnt(credit, "body", size)
        if not latin:
            if imaging.measure(p.d, credit, font)[0] <= p.max_w:
                p.line(credit, font, fill, y)
                return
            continue
        nfont = p.fnt(name, "body", size)       # اسم الناشر اللاتيني بـKalam وبطاقة «الصورة:» بـPlaypen
        lw = p.ink(label + ":", font, (0, 0), "la")
        nw = p.ink(name, nfont, (0, 0), "la", True)
        gap = max(size // 4, 6)
        total = (lw[2] - lw[0]) + gap + (nw[2] - nw[0])
        if total <= p.max_w:
            right = p.cx + total // 2
            imaging.draw_text(p.d, (right, y), label + ":", font, fill, anchor="ra")
            p.boxes.append(tuple(p.ink(label + ":", font, (right, y), "ra")))
            xy = (right - (lw[2] - lw[0]) - gap, y)
            imaging.draw_text_ltr(p.d, xy, name, nfont, fill, anchor="ra")
            p.boxes.append(tuple(p.ink(name, nfont, xy, "ra", True)))
            return
    log.warning("سطر مصدر الصورة لا يسع الشاشة فحُذف: %r", credit[:40])


_ARABIC_CHARS = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")


def channel_original_of(scene: dict, point: dict | None = None) -> str:
    """اسم القناة الأصلي: من المشهد، وإلا (سيناريو قديم) من حقل channel في نقطة المقطع."""
    return scene.get("channel_original") or (point or {}).get("channel") or ""


def channel_label(scene: dict) -> str:
    """القناة في الشريط السفلي: «{اللاتيني} {العربي}». اللاتيني هو channel_original بلا حروفه العربية؛ فإن لم يبق فيه حرف
    لاتيني، أو كان العربي يحويه أصلًا (قناة بلا name_ar)، يُستعمل channel_display وحده فلا يتكرر الاسم."""
    display = (scene.get("channel_display") or "").strip()
    latin = " ".join(_ARABIC_CHARS.sub(" ", scene.get("channel_original") or "").split())
    if not re.search(r"[A-Za-z]", latin):
        return display
    if not display or latin.casefold() in display.casefold():
        return display or latin
    return f"{latin} {display}"


def frame_clip_overlay(cfg, scene: dict, boxes=None) -> Image.Image:
    """الطبقتان مدموجتان في صورة شفافة واحدة (الشكل النهائي الثابت للشريط بعد انتهاء حركته)."""
    static, band = frame_clip_layers(cfg, scene, boxes)
    return Image.alpha_composite(static, band)


def frame_clip_layers(cfg, scene: dict, boxes=None, cover: bool | None = None,
                      quote: bool = True) -> tuple[Image.Image, Image.Image]:
    """طبقتان شفافتان بحجم الشاشة (Issue #1400): الثابتة (صندوق الترجمة والغطاء الكحلي المعتم من أسفل الشريط)
    وطبقة الشريط (المستطيل والحافة الذهبية والنصوص) التي تدخل متحركة من اليمين. الغطاء يخفي شريط القناة الأصلية
    المقصوص؛ شفافية 0.94 أبقته ظاهرًا باهتًا فهو معتم تمامًا."""
    st = _Pen(cfg, boxes, transparent=True)
    bd = _Pen(cfg, st.boxes, transparent=True)
    p = st
    draw_quote = quote
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
    if quote and draw_quote:
        # الشكل الثابت الكامل (بلا حالات): كل أسطر الاقتباس معًا كما كان قبل R5h، لمن لا يمرّر تيار الحالات
        font, lines, lh = imaging.fit_text(p.d, quote, *p.face(quote, "body")[:1], p.max_w, 3, 46, 30, p.face(quote, "body")[1])
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
    channel = channel_label(scene)
    y = top + 30
    if verified:
        # كل سطر يُصغَّر بخطوة 2 حتى يقع حبره بين x0 وx1 وفوق الحد السفلي؛ حدود التصغير من الإعداد
        mins = band.get("min_sizes") or {}
        gap, limit = int(band.get("line_gap", 12)), top + height - 16
        bottom = p.ink_line(scene["speaker_name"], *p.face(scene["speaker_name"], "display"), 56, p.white, prev_bottom=None, gap=gap, limit=limit,
                            min_size=int(mins.get("name", 40)), y_top=y)
        bottom = y if bottom is None else bottom
        latin = (scene.get("speaker_name_latin") or "").strip()
        # السطر الذهبي للاسم اللاتيني فقط: حين وضع السيناريو الاسم العربي نفسه هنا تكرّر الاسم في سطرين
        has_latin = bool(re.search(r"[A-Za-z]", latin)) and latin.casefold() != scene["speaker_name"].strip().casefold()
        if has_latin:
            # Kalam-Bold للاتيني الخالص (يغطي ş ğ İ)
            nb = p.ink_line(latin, *p.face(latin, "body"), 34, p.gold, prev_bottom=bottom, gap=gap,
                            limit=limit, min_size=int(mins.get("latin", 26)), ltr=True)
            bottom = bottom if nb is None else nb
        # الصفة · القناة حتى min_sizes.role؛ إن لم يسع حُذفت الصفة وبقيت القناة من 40، وإن لم تسع القناة اللاتينية
        # والعربية معًا بقي channel_display وحده
        role = scene.get("speaker_role", "")
        display = (scene.get("channel_display") or "").strip()
        role_min = int(mins.get("role", 26))
        grey = (214, 222, 238)
        # بلا سطر لاتيني والصفة والقناة لا تسعان معًا عند الحد الأدنى: الصفة في سطر والقناة تحته (Issue #1423) بدل حذف الصفة
        if role and channel and not has_latin:
            if p.ink_line(" · ".join((role, channel)), *p.face(" · ".join((role, channel)), "body"), 40, grey, prev_bottom=bottom, gap=gap,
                          limit=limit, min_size=role_min, warn=False) is not None:
                return st.img, bd.img
            rb = p.ink_line(role, *p.face(role, "body"), 40, grey, prev_bottom=bottom, gap=gap, limit=limit,
                            min_size=role_min, warn=False)
            if rb is not None:
                # لا يسع اسم القناة الكامل تحت الصفة: الاسم العربي وحده، وإلا تبقى الصفة (الرسم لا يُتراجع عنه)
                for txt in (channel, display):
                    if txt and p.ink_line(txt, *p.face(txt, "body"), 40, grey, prev_bottom=rb, gap=gap, limit=limit,
                                          min_size=role_min, warn=txt == display) is not None:
                        break
                return st.img, bd.img
        tries = [" · ".join(x for x in (role, channel) if x)]
        if role and channel:
            tries.append(channel)
        if display and display != channel:
            tries.append(display)
        for i, txt in enumerate(tries):
            if txt and p.ink_line(txt, *p.face(txt, "body"), 40, grey, prev_bottom=bottom, gap=gap, limit=limit,
                                  min_size=role_min, warn=i == len(tries) - 1) is not None:
                break
    else:
        # غير الموثَّق مذيعًا كان أو ضيفًا: القناة بصيغتها وحدها، فـ«ضيف على» ادّعاء لا نعرفه (Issue #1450)
        label = channel or (scene.get("channel_display") or "").strip()
        p.ink_line(label, *p.face(label, "display"), 52, p.white, prev_bottom=None, gap=0, limit=top + height - 16,
                   min_size=int(band.get("min_sizes", {}).get("guest", 30)), y_top=top + 80)
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
    # صفة طويلة وقناة لاتينية طويلة: أسوأ حالة لعرض الشريط
    frame_clip_overlay(cfg, {"speaker_verified": True, "speaker_name": "الاسم العربي الكامل للمتحدث",
                             "speaker_name_latin": "Full Latin Name", "speaker_role": " ".join(["محلل"] * 20),
                             "channel_original": "A Very Long Latin Channel Name International Edition",
                             "channel_display": "قناة طويلة الاسم جدًا للتجربة"}, boxes)
    return boxes


# ───────────────────────────── التركيب ─────────────────────────────


def _enc(rcfg: dict) -> list[str]:
    return ["-c:v", "libx264", "-preset", str(rcfg.get("preset", "veryfast")), "-crf", str(rcfg.get("crf", 22)), "-pix_fmt", "yuv420p",
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
    # الإطارات ملفات مؤقتة تُحذف بعد التركيب فضغطها الأعلى هدر وقت؛ البكسلات نفسها بلا تغيير
    img.save(path, compress_level=1)
    return path



# ───────────────────── ترجمة المتحدث سطرًا فسطرًا كلمةً كلمة (Issue #1592، R5h) ─────────────────────

def quote_layout(cfg, text: str) -> list[dict]:
    """أسطر الترجمة: تقسيم بالعرض الآمن بالحجم الأول من sizes.quote؛ كلمة وحدها أطول من العرض تُصغَّر بخطوة 2 حتى الأدنى
    وتبقى في سطر منفرد. كل سطر {words، size، width}."""
    p = _Pen(cfg, [], transparent=True)
    big, small = (int(v) for v in cfg.path("reel.render.sizes.quote"))
    path, weight = p.face(text, "body")
    limit = p.max_w - 4        # هامش لفرق الحبر عن التقدّم فلا يتجاوز الحبر max_w

    def width(s: str, size: int) -> int:
        return imaging.measure(p.d, s, imaging.load_font(path, size, weight))[0]

    lines: list[dict] = []
    cur: list[str] = []
    for word in text.split():
        if width(word, big) > limit:
            if cur:
                lines.append({"words": cur, "size": big})
                cur = []
            size = big
            while size > small and width(word, size) > limit:
                size -= 2
            lines.append({"words": [word], "size": size})
            continue
        if cur and width(" ".join(cur + [word]), big) > limit:
            lines.append({"words": cur, "size": big})
            cur = []
        cur.append(word)
    if cur:
        lines.append({"words": cur, "size": big})
    for ln in lines:
        ln["width"] = width(" ".join(ln["words"]), ln["size"])
    return lines


def quote_states(layout: list[dict], mode: str = "word") -> list[tuple[int, int]]:
    """تتابع الحالات: (فهرس السطر، عدد كلماته الظاهرة). word: السطر يكتمل كلمةً كلمة ثم يحلّ محلّه التالي بكلمته الأولى.
    line (Q4، Issue #1654، لكلام غير عربي): حالة واحدة لكل سطر يظهر كاملًا مرة واحدة."""
    if mode == "line":
        return [(i, len(ln["words"])) for i, ln in enumerate(layout)]
    return [(i, k) for i, ln in enumerate(layout) for k in range(1, len(ln["words"]) + 1)]


def frame_quote_state(cfg, layout: list[dict], line: int, shown: int) -> Image.Image:
    """طبقة شفافة بحجم الشاشة: الصندوق الداكن بارتفاع سطر واحد فوق الشريط في موضعه القديم، وأول `shown` كلمة من السطر في
    مواضعها النهائية (محاذاة يمينية على حافة السطر الكامل، فلا يتحرك السطر وتمتلئ الكلمات من اليمين)."""
    p = _Pen(cfg, [], transparent=True)
    ln = layout[line]
    size = ln["size"]
    top = int(cfg.path("reel.render.band.top"))
    lh = int(int(cfg.path("reel.render.sizes.quote")[0]) * float(cfg.path("reel.render.fonts.line_factor", 1.62)))
    box_h = lh + 36
    by = top - 24 - box_h
    p.d.rectangle((p.x0 - 24, by, p.x1 + 24, by + box_h), fill=(8, 14, 28, 175))
    text = " ".join(ln["words"])
    path, weight = p.face(text, "body")
    font = imaging.load_font(path, size, weight)
    right = p.cx + ln["width"] // 2
    imaging.draw_text(p.d, (right, by + 18 + (lh - int(size * float(cfg.path("reel.render.fonts.line_factor", 1.62)))) // 2),
                      " ".join(ln["words"][:shown]), font, p.white, anchor="ra")
    return p.img


def quote_frames(cfg, text: str, times: list[float], clip_seconds: float, tmp: Path, tag: str,
                 mode: str = "word") -> list[tuple[Path, float]]:
    """ملفات تيار الحالات [(png، مدة)]: أولها شفاف إلى أول كلمة، ثم حالة لكل كلمة حتى زمن التي بعدها، والأخيرة إلى نهاية المقطع
    (وزيادة ثانية احتياطًا كي لا ينتهي التيار قبل المقطع)."""
    layout = quote_layout(cfg, text)
    states = quote_states(layout, mode)
    if mode == "line":
        # السطر يظهر كاملًا عند زمن أول كلمة فيه ويبقى حتى أول كلمة من التالي (التوقيت نفسه quote_word_times)
        firsts = [sum(len(l["words"]) for l in layout[:i]) for i in range(len(layout))]
        times = [times[min(f, len(times) - 1)] for f in firsts]
    p = _Pen(cfg, [], transparent=True)
    frames = [(_save(p.img, tmp / f"{tag}_empty.png"), max(times[0], 0.04))]
    for j, (ln, shown) in enumerate(states):
        end = times[j + 1] if j + 1 < len(times) else clip_seconds + 1.0
        frames.append((_save(frame_quote_state(cfg, layout, ln, shown), tmp / f"{tag}_{j:03d}.png"), max(end - times[j], 0.04)))
    return frames


# ───────────────────── العنوان ينزل كلمة كلمة مع صوت الراوي (Issue #1600، P1a) ─────────────────────

def narration_word_times(parts: list[tuple[str, float]], start: float, cfg) -> list[float]:
    """زمن ظهور كل كلمة من الجمل المنطوقة. parts ما تعيده _speech: [(نص الجملة، مدتها مع صمتها)]. مدة نطق الجملة = مدتها −
    reel.tts.sentence_silence، والكلمة k تظهر عند بداية جملتها + (حروف ما قبلها بلا مسافات ÷ حروف الجملة) × مدة النطق؛ والجملة
    التالية تبدأ بعد مدة السابقة كاملة بصمتها. التناسب بالحروف لأن زمن نطق الكلمة يتبع طولها تقريبًا، فلا حاجة لتوقيت كلمات من TTS."""
    silence = float(cfg.path("reel.tts.sentence_silence", 0.35))
    out: list[float] = []
    cursor = float(start)
    for text, dur in parts:
        words = str(text).split()
        speak = max(float(dur) - silence, 0.0)
        total = sum(len(w) for w in words) or 1
        before = 0
        for w in words:
            out.append(cursor + before / total * speak)
            before += len(w)
        cursor += float(dur)
    return out


def word_layout(cfg, text: str, top: int, size_key: str = "hook") -> dict:
    """تخطيط عنوان الهوك كلمةً كلمة: الحجم الذي يسع (sizes.hook، حتى 4 أسطر) ثم موضع كل كلمة النهائي داخل سطرها المتمركز
    (الأولى عند اليمين). كل كلمة {line، text، xy، box} وbox حبرها الفعلي كما يظهر في الحالة الأخيرة (الألفا > 40، كما يقيس الفحص).
    يعيد {words، font، lh، lines، tiles} وtiles بلاطة RGBA بهامش لكل كلمة مع موضع لصقها."""
    import numpy as np
    p = _Pen(cfg, [], transparent=True)
    fpath, fw = p.face(text, "display")
    start, minimum = size_pair(cfg, size_key)
    font, lines, lh = _fit(p.d, text, fpath, p.max_w, 4, start, minimum, fw, float(cfg.path("reel.render.fonts.line_factor")))
    kw = imaging._kwargs()

    def adv(s: str) -> float:
        return p.d.textlength(imaging._prepare(s), font=font, **kw)
    words: list[dict] = []
    tiles: list[tuple[Image.Image, tuple[int, int]]] = []
    for j, ln in enumerate(lines):
        right = p.cx + adv(ln) / 2
        toks = ln.split()
        for k, tok in enumerate(toks):
            x = right - (adv(" ".join(toks[:k]) + " ") if k else 0)
            xy = (int(round(x)), int(top + j * lh))
            wp = _Pen(cfg, [], transparent=True)
            imaging.draw_text(wp.d, xy, tok, font, wp.white, anchor="ra")
            ys, xs = np.nonzero(np.asarray(wp.img)[..., 3] > 40)
            if len(xs):
                box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
            else:
                box = (xy[0], xy[1], xy[0] + 1, xy[1] + 1)
            pad = 6
            crop = (max(box[0] - pad, 0), max(box[1] - pad, 0), min(box[2] + pad, wp.w), min(box[3] + pad, wp.h))
            words.append({"line": j, "text": tok, "xy": xy, "box": box})
            tiles.append((wp.img.crop(crop), (crop[0], crop[1])))
    return {"words": words, "font": font, "lh": lh, "lines": lines, "tiles": tiles}


def word_drop_frames(cfg, text: str, times: list[float], seconds: float, top: int, tmp: Path, tag: str,
                     size_key: str = "hook", label: Image.Image | None = None,
                     label_at: float | None = None) -> list[tuple[Path, float]]:
    """تيار حالات PNG [(ملف، مدة)] لعنوان تنزل كلماته: الكلمة k تبدأ عند times[k] فتنزل من words.drop_px بكسل فوق موضعها النهائي
    مع شفافية 0←1 خلال words.drop ثانية بتسارع ease-out، وبقية الكلمات ثابتة في مواضعها؛ السطر لا يتحرك. لكل إطار زمنه
    البدئي (لا نهايته) فلا تظهر كلمة قبل زمنها. الإطارات المتطابقة تُدمج في مدة واحدة. مشتركة مع السؤال الأخير في P1a-2."""
    rcfg, wc = cfg.path("reel.render"), cfg.path("reel.render.words")
    fps = float(rcfg["fps"])
    drop, drop_px = float(wc["drop"]), float(wc["drop_px"])
    lay = word_layout(cfg, text, top, size_key)
    tiles = lay["tiles"]
    n_total = max(int(math.ceil(seconds * fps - 1e-9)), 1)
    base = Image.new("RGBA", (int(rcfg["width"]), int(rcfg["height"])), (0, 0, 0, 0))
    frames: list[tuple[Path, float]] = []
    prev_key = None
    for f in range(n_total):
        t = f / fps
        eases = tuple(round(_ease_out(min(max((t - tm) / drop, 0.0), 1.0)), 3) if t >= tm else -1.0
                      for tm in times[:len(tiles)])
        # «برأيك..» تظهر مع أول كلمة (P1a-2)، أو عند label_at إن حُدِّد: منطوقة قبل السؤال بوقفة (Q5)
        lab = label is not None and ((t >= label_at) if label_at is not None else any(e >= 0 for e in eases))
        key = (lab, *eases)
        if key == prev_key:
            frames[-1] = (frames[-1][0], frames[-1][1] + 1 / fps)
            continue
        img = base.copy()
        if lab:
            img.alpha_composite(label)
        for (tile, (cx, cy)), e in zip(tiles, eases):
            if e < 0:
                continue
            if e < 1:
                tile = tile.copy()
                tile.putalpha(tile.getchannel("A").point(lambda v, e=e: int(v * e)))
            img.alpha_composite(tile, (cx, max(cy - int(round(drop_px * (1 - e))), 0)))
        frames.append((_save(img, tmp / f"{tag}_w{len(frames):03d}.png"), 1 / fps))
        prev_key = key
    frames[-1] = (frames[-1][0], frames[-1][1] + max(seconds - n_total / fps, 0.0))
    return frames


def closing_label_size(cfg, question: str) -> int:
    """حجم خط «برأيك..»: حجم خط السؤال تحتها كما يحسبه word_layout (sizes.question) لسطره الأول، فلا تصغر عنه (Q5)."""
    return int(word_layout(cfg, question, 0, "question")["font"].size)


def closing_label_layer(cfg, question: str) -> tuple[Image.Image, int]:
    """طبقة «برأيك..» الذهبية (reel.texts.closing_label) بخط display وبحجم السؤال نفسه متمركزة، أعلى حبرها عند closing.text_top.
    يعيد (الطبقة الشفافة، y الذي يبدأ منه السؤال = أسفل حبرها + closing.label_gap)."""
    cl = cfg.path("reel.render.closing")
    p = _Pen(cfg, [], transparent=True)
    text = cfg.path("reel.texts.closing_label")
    font = p.fnt(text, "display", closing_label_size(cfg, question))
    top0 = p.ink(text, font, (p.cx, 0), "ma")[1]
    y = int(cl["text_top"]) - top0
    imaging.draw_text(p.d, (p.cx, y), text, font, p.gold, anchor="ma")
    return p.img, int(p.ink(text, font, (p.cx, y), "ma")[3]) + int(cl["label_gap"])


def closing_text_frames(cfg, question: str, times: list[float], seconds: float, tmp: Path, tag: str,
                        label_at: float | None = None) -> list[tuple[Path, float]]:
    """تيار حالات نص الختام: «برأيك..» بالذهبي فوق السؤال الذي تنزل كلماته بأزمنة times (word_drop_frames بحجم sizes.question).
    لا دائرة ذهبية ولا «؟» منفصلة ولا «شاركونا» (Issue #1602). label_at زمن ظهور «برأيك..» (مع نطقها، Q5) وإلا مع أول كلمة."""
    label, top = closing_label_layer(cfg, question)
    return word_drop_frames(cfg, question, times, seconds, top, tmp, tag, size_key="question", label=label, label_at=label_at)


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


def _norm_words(text: str) -> list[str]:
    from . import youtube_extract
    return youtube_extract._normalize_for_anchor(str(text or "")).split()


def gate_window(g0: float, g1: float, silences: list, cfg) -> dict:
    """نافذة الصوت المسموع داخل المقطع (Issue #1660، Q6): g0 بداية الكلام وg1 نهايته من النص، يُنقل g0 إلى نهاية آخر صمت حقيقي يقع
    في [g0 − snap، g0 + snap] وg1 إلى بداية أول صمت في [g1 − snap، g1 + snap]؛ بلا صمت في المدى يبقى التقدير. دالة خالصة."""
    snap = float(cfg.path("reel.render.gate.snap", 0.6))
    c0 = [e for _, e in silences or [] if g0 - snap <= e <= g0 + snap]
    c1 = [b for b, _ in silences or [] if g1 - snap <= b <= g1 + snap]
    start, end = (max(c0) if c0 else g0), (min(c1) if c1 else g1)
    if end - start < 0.5:       # صمت يلتهم الكلام كله: التقدير أوثق
        start, end, c0, c1 = g0, g1, [], []
    return {"start": round(start, 2), "end": round(end, 2), "source": "silence" if (c0 or c1) else "transcript"}


def approx_gate(seconds: float, cfg) -> dict:
    """بوابة المقطع بنافذة تقديرية (بلا نص مجلوب): يُكتم ما قبل lead_seconds وما بعد نهاية النافذة − clip_tail_seconds."""
    lead = float(cfg.path("reel.script.lead_seconds", 1))
    tail = float(cfg.path("reel.script.clip_tail_seconds", 1.0))
    return {"start": lead, "end": round(max(float(seconds) - tail, lead), 2), "source": "approx"}


def gate_volume(start: float, end: float, cfg) -> str:
    """مرشح volume بتعبير زمني: 0 خارج [start، end] ويتصاعد/يتلاشى خلال gate.fade عند الطرفين. min/max بلا if (كتعابير اللوحة الأخرى)."""
    f = _fmt(float(cfg.path("reel.render.gate.fade", 0.12)))
    return f"volume='min(max(min((t-{_fmt(start)})/{f},({_fmt(end)}-t)/{f}),0),1)':eval=frame"


def _gate_filter(clip: dict, cfg) -> str:
    """مرشح بوابة المقطع (أو فارغ) مع الفاصلة اللاحقة؛ مطفأة أو بلا gate على المقطع ← فارغ فيبقى الأمر كما كان حرفًا."""
    g = clip.get("gate")
    if not g or not cfg.path("reel.render.gate.enabled", True):
        return ""
    return gate_volume(g["start"], g["end"], cfg) + ","


def _real_detect_silence(clip, cfg) -> list[tuple[float, float]]:
    """فترات الصمت في صوت المقطع (silencedetect) بثواني الملف؛ أي عطل ← [] فيبقى التقدير."""
    gc = cfg.path("reel.render.gate") or {}
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(clip), "-vn", "-af",
           f"silencedetect=noise={gc.get('noise_db', -32)}dB:d={gc.get('min_silence', 0.25)}", "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception:  # noqa: BLE001
        return []
    out, begin = [], None
    for ln in (proc.stderr or "").splitlines():
        m = re.search(r"silence_start:\s*(-?[\d.]+)", ln)
        if m:
            begin = max(float(m.group(1)), 0.0)
        m = re.search(r"silence_end:\s*(-?[\d.]+)", ln)
        if m and begin is not None:
            out.append((begin, float(m.group(1))))
            begin = None
    return out


def _decide_span(scene: dict, point: dict, segs: list, loc: dict, old: tuple[int, int], cfg, deps: Deps) -> dict:
    """فكرة المقطع (Issue #1660، Q6): نداء pick_span ثم تحقق الكود. يعيد action = drop (reason) أو ok أو fallback (rec، ومعهما window
    وdisplay وsegs وg0 وg1 للأول)؛ لا يرفع أبدًا (عطل النداء ← fallback)."""
    first, last = loc["first"], loc["last"]
    lines_q = " ".join(str(segs[k][1]) for k in range(first, last + 1))
    base = {"point_id": scene.get("point_id", ""), "complete": True, "changed_text": False, "reason": "", "source": "fallback",
            "lang": "ar" if reel_clips.is_arabic_audio(lines_q) else (scene.get("language") or "other")}
    try:
        raw = deps.pick_span(segs, first, last, point.get("quote_original", ""), cfg)
    except Exception as exc:  # noqa: BLE001 -- تحسين لا شرط: النافذة القديمة
        log.warning("تعذّر اختيار فكرة المقطع: %s", reel_clips.scrub_text(str(exc))[:150])
        return {"action": "fallback", "rec": {**base, "reason": "تعذّر النداء"}}
    if isinstance(raw, dict) and raw.get("complete") is False:
        try:
            a, b = int(raw["start_line"]), int(raw["end_line"])
            n = round(reel_clips.line_end(segs, b, cfg) - float(segs[a][0]))
        except (KeyError, TypeError, ValueError, IndexError):
            n = old[1] - old[0]
        return {"action": "drop", "reason": cfg.path("reel.render.texts.drop_incomplete").format(n=n)}
    info, why = reel_clips.check_span(raw, segs, first, last, cfg)
    if info is None:
        return {"action": "fallback", "rec": {**base, "reason": why}}
    a, b = info["start_line"], info["end_line"]
    lines_text = " ".join(str(segs[k][1]) for k in range(a, b + 1))
    arabic = reel_clips.is_arabic_audio(lines_text)
    display = reel_clips.resolve_display(raw.get("display_text"), lines_text, arabic)
    changed = bool(display) and _norm_words(display) != _norm_words(scene.get("quote_arabic", ""))
    lead, tail = float(cfg.path("reel.script.lead_seconds", 1)), float(cfg.path("reel.script.clip_tail_seconds", 1.0))
    wstart = int(max(0, info["start"] - lead))
    wend = int(math.ceil(info["end"] + tail))
    lang = "ar" if arabic else (scene.get("language") if scene.get("language") not in (None, "", "ar") else "other")
    rec = {"point_id": scene.get("point_id", ""), "start": wstart, "end": wend, "complete": True, "lang": lang,
           "changed_text": changed, "reason": " ".join(str(raw.get("reason") or "").split())[:150], "source": "model"}
    return {"action": "ok", "rec": rec, "window": (wstart, wend), "display": display, "segs": list(segs[a:b + 1]),
            "g0": info["start"], "g1": info["end"], "seconds": info["seconds"], "arabic": arabic}


def _span_and_gate(clip: dict, span_info: dict | None, scene: dict, segs: list, wstart: int, cfg, deps: Deps,
                   approx: list) -> None:
    """يملأ على المقطع المنزَّل: span (سجل render_spans) وdisplay_text (نص الأسطر المعروض بدل quote_arabic) وsegs المقصوصة لأسطر الفكرة،
    وgate = نافذة الصوت المسموع (Issue #1660، Q6). مطفأتان ← لا يُضاف شيء فيبقى كل ما بعده حرفًا كما كان."""
    res = (span_info or {}).get("res")
    if res:
        clip["span"] = res["rec"]
        if res["action"] == "ok":
            if res.get("display"):
                clip["display_text"] = res["display"]
            clip["segs"], clip["wstart"] = res["segs"], float(wstart)
    if not cfg.path("reel.render.gate.enabled", True):
        return
    secs = float(clip["seconds"])
    is_approx = bool(approx and approx[-1]["point_id"] == scene.get("point_id", "") and approx[-1]["start"] == wstart) or not segs
    if is_approx:
        clip["gate"] = approx_gate(secs, cfg)
        return
    loc = (span_info or {}).get("loc") or {}
    if res and res["action"] == "ok":
        g0, g1 = res["g0"] - wstart, res["g1"] - wstart
    else:
        g0, g1 = float(loc["start"]) - wstart, float(loc["end"]) - wstart
    g0, g1 = max(g0, 0.0), min(g1, secs)
    sil = []
    if deps.detect_silence is not None:
        try:
            sil = deps.detect_silence(clip["file"], cfg) or []
        except Exception as exc:  # noqa: BLE001 -- الضبط على الصمت تحسين: يبقى التقدير
            log.warning("تعذّر كشف الصمت: %s", reel_clips.scrub_text(str(exc))[:100])
    clip["gate"] = gate_window(g0, g1, sil, cfg)


def _fetch_clips(script: dict, draft: dict, cfg, deps: Deps, tmp: Path, notes: list | None = None) -> tuple[dict, list, list]:
    """لكل مشهد مقطع: نص الفيديو ← تحديد موضع الاقتباس ← تنزيل نافذته. يعيد ({فهرس المشهد: {file, seconds}}, المحذوف,
    المقاطع بنافذة تقديرية). تعذّر النص (استثناء أو فارغ) أو نص لا يحوي الاقتباس أو يكرره لا يُسقط المقطع بل يستعمل نافذة
    المشهد من طابع النقطة؛ ولا إسقاط إلا إن لم توجد نافذة (Issue #1438)."""
    rcfg, scfg = cfg.path("reel.render"), cfg.path("reel.script")
    by_id = {reel_script.point_key_id(p): p for p in deps.load_points(draft.get("topic_date", ""))}
    transcripts: dict[str, list] = {}
    fetch_reasons: dict[str, str] = {}     # سبب فشل جلب نص كل فيديو (Issue #1621، R6): بلا سببه لا يُعرف أهو حجب أم حدّ معدّل
    clips: dict[int, dict] = {}
    dropped: list = []
    approx: list = []
    from . import youtube_extract
    for i, scene in enumerate(script["scenes"]):
        if scene.get("kind") not in reel_script.CLIP_KINDS:
            continue
        span_info = None
        point = by_id.get(scene.get("point_id"))
        if not point or not point.get("video_id"):
            _drop(dropped, scene, "نقطة المقطع غير موجودة في نافذة النقاط")
            continue
        # سيناريوهات كُتبت قبل R5a بلا channel_original: الاسم اللاتيني للقناة يؤخذ من النقطة نفسها التي نقرؤها هنا
        scene["channel_original"] = channel_original_of(scene, point)
        if not scene.get("speaker_text"):
            scene["speaker_text"] = point.get("speaker", "") or ""    # قائل النقطة لحارس شريط القناة (R6)
        vid = point["video_id"]
        if vid not in transcripts:
            try:
                text = deps.fetch_transcript(vid)
            except Exception as exc:  # noqa: BLE001
                # رابط البروكسي يحمل المستخدم وكلمة المرور داخل الرابط نفسه، وscrub_text لا تعرفهما إلا من متغيرات البيئة
                safe = re.sub(r"(?<=://)[^/@\s]*@", "", reel_clips.scrub_text(str(exc)))
                log.warning("نص الفيديو %s: %s", vid, safe[:150])
                text = None
                # سبب fetch_transcript الجاهز لا يُسبق باسم الصنف؛ غيره من الاستثناءات يبقى بصيغة R6
                lead = "" if isinstance(exc, TranscriptUnavailable) else type(exc).__name__ + ": "
                fetch_reasons[vid] = "تعذّر جلب نص الفيديو: " + lead + " ".join(safe.split())[:80]
            transcripts[vid] = youtube_extract.parse_transcript_segments(text) if text else []
        if not transcripts[vid]:
            win = _approx_window(point, scene)
            why = fetch_reasons.get(vid, "تعذّر جلب نص الفيديو")
            if win is None:
                _drop(dropped, scene, why)
                continue
            wstart, wend = win
            approx.append({"point_id": scene.get("point_id", ""), "kind": scene.get("kind", ""),
                           "start": wstart, "end": wend, "reason": why,
                           "channel": scene.get("channel_display", "")})
        else:
            near = point.get("timestamp", scene.get("start"))
            loc = reel_clips.locate_quote(point.get("quote_original", ""), transcripts[vid], near=near, cfg=cfg)
            if loc["status"] != "found":
                # نص مجلوب لا يحوي الاقتباس (غالبًا مسار ترجمة بغير اللغة الأصلية) أو يكرره: طابع النقطة أُخذ من النص
                # الأصلي عند الاستخراج فهو أوثق، فيعامَل كفشل الجلب ولا يُحذف المقطع إلا بلا نافذة (Issue #1438)
                ambiguous = loc["status"] == "ambiguous"
                win = _approx_window(point, scene)
                if win is None:
                    _drop(dropped, scene, "موضع الاقتباس في الفيديو غير حاسم (يتكرر)" if ambiguous
                          else "الاقتباس غير موجود في نص الفيديو")
                    continue
                wstart, wend = win
                approx.append({"point_id": scene.get("point_id", ""), "kind": scene.get("kind", ""),
                               "start": wstart, "end": wend,
                               "reason": cfg.path("reel.render.texts.approx_ambiguous" if ambiguous
                                                  else "reel.render.texts.approx_not_found"),
                               "channel": scene.get("channel_display", "")})
            else:
                wstart = int(max(0, loc["start"] - float(scfg.get("lead_seconds", 1))))
                wend = int(math.ceil(loc["end"]))
                wend = min(wend, wstart + int(scfg.get("clip_max_seconds", 15)))
                if wend <= wstart:     # نافذة معدومة (اقتباس في آخر سطر) تُمدّ إلى الحد الأدنى لا تُسقط المقطع
                    wend = wstart + int(scfg.get("clip_min_seconds", 6))
                span_res = None
                if cfg.path("reel.render.span.enabled", True) and deps.pick_span is not None and loc.get("first") is not None:
                    span_res = _decide_span(scene, point, transcripts[vid], loc, (wstart, wend), cfg, deps)
                    if span_res["action"] == "drop":
                        _drop(dropped, scene, span_res["reason"])
                        continue
                    if span_res["action"] == "ok":
                        (nstart, nend), channel = span_res["window"], scene.get("channel_display", "")
                        if notes is not None:
                            t = cfg.path("reel.render.texts")
                            if (nend - nstart) - (wend - wstart) > 2:
                                notes.append(t["comment_span_extended"].format(channel=channel, n=round(span_res["seconds"])))
                            if span_res["arabic"] and span_res["rec"]["changed_text"]:
                                notes.append(t["comment_span_text"].format(channel=channel))
                        wstart, wend = nstart, nend
                span_info = {"res": span_res, "loc": loc}
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
        clips[i] = {"file": out, "seconds": float(secs), "video_id": vid}
        if transcripts[vid] and not (approx and approx[-1]["point_id"] == scene.get("point_id", "")
                                     and approx[-1]["start"] == wstart):
            # نافذة محسوبة من النص نفسه: مقاطعه تعطي منحنى تقدّم الكلام لتوقيت الترجمة؛ التقريبية بلا مقاطع فتوزَّع بالتساوي
            clips[i]["segs"] = transcripts[vid]
            clips[i]["wstart"] = float(wstart)
        _span_and_gate(clips[i], span_info, scene, transcripts[vid], wstart, cfg, deps, approx)
    return clips, dropped, approx


def _speech(text: str, voice: str, cfg, deps: Deps, tmp: Path, tag: str) -> tuple[Path, list[tuple[str, float]]]:
    """صوت مشهد: تشكيل النص كله ← جمل ← وقف ← نداء لكل جملة ← وصل بصمت. يعيد (ملف الصوت، [(نص الجملة للعرض، مدتها)])."""
    rcfg = cfg.path("reel.render")
    silence = float(cfg.path("reel.tts.sentence_silence", 0.35))
    res = deps.diacritize(text)       # ثنائية (المزيَّفات القديمة) أو ثلاثية (مع الأعلام)
    shown, warn = res[0], res[1]
    nouns = res[2] if len(res) > 2 else []
    if warn:
        log.warning("تشكيل %s: %s", tag, warn)
    shown = tts.apply_proper_nouns(shown, nouns)
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


def scene_seconds(body: float, tail: float, lead: float) -> float:
    """مدة مشهد صوتي: مدة كلامه + tail + lead. دالة واحدة يقرؤها _timed_scene وحساب مدة الراوي الكلية قبل التركيب (خطة حركة
    الخلفية تحتاجها قبل رسم أي مشهد) فلا تنحرف نسختان من الصيغة (Issue #1447)."""
    return body + (tail if tail > 0 else 0.0) + (lead if lead > 0 else 0.0)


def _still_bg_prefix(fps) -> str:
    """سابقة سلسلة الفلتر لصورة خلفية كبيرة (4096×2150) تُدخل بـ-i مرة واحدة: loop يكرّر إطارها المفكوك، وsetpts يعيد الزمن
    إلى زمن المشهد فيبقى t في crop صحيحًا. -loop 1 على PNG كبيرة يعيد فك ضغطها كل إطار (قيس: 30 ث بدل 4 ث لمقطع 11 ث)."""
    return f"[0:v]loop=loop=-1:size=1:start=0,setpts=N/{fps}/TB,"


def _timed_scene(frames: list[tuple[Path, float]], audio: Path, out: Path, cfg, deps: Deps, tmp: Path, tail: float,
                 lead: float = 0.0, bg_png: Path | None = None, bg_start: float = 0.0,
                 bg_pan: tuple[float, float] = (0.0, 0.0), broll: list | None = None) -> float:
    """مشهد صوتي بإطارات متتابعة (جملة لكل إطار بمدتها الفعلية)؛ يعيد مدته.
    lead: صمت في أول الصوت يمتد معه الإطار الأول، كي لا تقع أول كلمة في التلاشي المتقاطع مع المشهد السابق.
    bg_png: خلفية الراوي تيار مستقل بمدة المشهد كاملة (Issue #1447، R5d1)؛ الإطارات PNG شفافة تُركَّب فوقه في الأمر نفسه.
    bg_start: زمن بداية المشهد التراكمي بين مشاهد الراوي فتتصل حركة الصورة ولا تقفز.
    bg_pan: (x0، السرعة) من pan_plan المشتركة بين مشاهد الراوي كلها؛ bg_png مُكبَّرة سلفًا إلى أبعاد تلك الخطة.
    broll: [{a, b, clip, cexpr}] لقطات الحدث (Issue #1452، R5d2) تُركَّب فوق تيار الصورة المتحركة في زمن جملتها (a..b داخل المشهد)
    ثم يأتي التظليل فالنص: اللقطة صامتة فلا يُخرَج صوتها، وsetpts يؤخرها إلى a كي تبدأ مع جملتها لا مع المشهد."""
    rcfg = cfg.path("reel.render")
    frames = list(frames)
    total = scene_seconds(sum(d for _, d in frames), tail, lead)
    frames[-1] = (frames[-1][0], frames[-1][1] + tail)
    if lead > 0:
        frames[0] = (frames[0][0], frames[0][1] + lead)
    lst = tmp / (out.stem + "_frames.txt")
    body = "".join(f"file '{f}'\nduration {_fmt(d)}\n" for f, d in frames) + f"file '{frames[-1][0]}'\n"
    lst.write_text(body, encoding="utf-8")
    if bg_png is not None:
        w, h, fps = int(rcfg["width"]), int(rcfg["height"]), rcfg["fps"]
        pan = _pan_x_expr(bg_pan[0], bg_pan[1], bg_start)
        afilter = f"adelay={int(round(lead * 1000))}:all=1,apad" if lead > 0 else "apad"
        crop = f"{_still_bg_prefix(fps)}crop={w}:{h}:x='{pan}':y='(ih-oh)/2'"
        shade = _shade_filter(cfg, "narration_bg")
        extra: list[str] = []
        if broll:
            vg = crop + "[p0];"
            for j, bl in enumerate(broll):
                extra += ["-i", str(bl["clip"])]
                a, b = _fmt(bl["a"]), _fmt(bl["b"])
                vg += (f"[{3 + j}:v]{bl['cexpr']},scale={w}:{h},fps={fps},setpts=PTS-STARTPTS+{a}/TB[c{j}];"
                       f"[p{j}][c{j}]overlay=0:0:enable='between(t,{a},{b})'[p{j + 1}];")
            vg += f"[p{len(broll)}]{shade},fps={fps}[b];"
        else:
            vg = f"{crop},{shade},fps={fps}[b];"
        vg += f"[1:v]fps={fps},format=rgba[t];[b][t]overlay=0:0:shortest=1,format=yuv420p[v];[2:a]{afilter}[a]"
        deps.run(_base("-i", str(bg_png), "-f", "concat", "-safe", "0", "-i", str(lst),
                       "-i", str(audio), *extra, "-filter_complex", vg, "-map", "[v]", "-map", "[a]", "-t", _fmt(total),
                       *_enc(rcfg), str(out)))
        return total
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


# ───────────────────── تحديد المتكلم بالرؤية (Issue #1431، R5b2) ─────────────────────

PICK_SPEAKER_TOOL = {
    "name": "pick_speaker",
    "description": "يعيد لكل لقطة رقم المستطيل الذي يحيط بالمتكلم (0 إن لم يتضح) وأرقام ما هو أرشيفي أو خارج الحوار",
    "input_schema": {"type": "object", "properties": {"frames": {"type": "array", "items": {
        "type": "object",
        "properties": {"speaker": {"type": "integer"}, "archive": {"type": "array", "items": {"type": "integer"}},
                       "reason": {"type": "string"}},
        "required": ["speaker", "archive", "reason"]}}}, "required": ["frames"]},
}
_BOX_COLORS = [(230, 25, 75), (0, 130, 200), (60, 180, 75), (245, 130, 48), (145, 30, 180), (0, 200, 200)]


def annotated_jpeg(img, tracks: list, cfg) -> bytes:
    """لقطة كاملة بمستطيل ملوّن ورقم كبير لكل مسار عند وسيط موضعه وحجمه (الرقم بترتيب tracks)، مصغَّرة إلى عرض max_width
    بصيغة JPEG. الرسم قبل التصغير كي تبقى إحداثيات المسارات بدقة المصدر."""
    import io

    from PIL import ImageDraw, ImageFont
    vcfg = cfg.path("reel.render.speaker.vision") or {}
    img = img.convert("RGB").copy()
    draw = ImageDraw.Draw(img)
    for n, t in enumerate(tracks, 1):
        x, y, w, h = (float(v) for v in t["box"])
        color = _BOX_COLORS[(n - 1) % len(_BOX_COLORS)]
        draw.rectangle([x, y, x + w, y + h], outline=color, width=max(3, int(img.width * 0.005)))
        size = max(24, int(h * 0.4))
        try:
            font = ImageFont.load_default(size)
        except TypeError:   # Pillow قديم بلا حجم للخط الافتراضي
            font = ImageFont.load_default()
        # الرقم على خلفية بلون المستطيل فوق زاويته كي يُقرأ فوق أي لقطة
        tw = draw.textlength(str(n), font=font)
        draw.rectangle([x, y, x + tw + 12, y + size + 8], fill=color)
        draw.text((x + 6, y + 2), str(n), fill=(255, 255, 255), font=font)
    width = int(vcfg.get("max_width", 1280))
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _pick_jpegs(clip, tracks: list, cfg) -> list[bytes]:
    """لقطات كاملة عند نِسب مدة المقطع عليها مستطيلات المسارات؛ يرفع إن تعذّر استخراج لقطة."""
    import io
    vcfg = cfg.path("reel.render.speaker.vision") or {}
    dur = probe_duration(clip)
    if not dur:
        raise RuntimeError("مدة المقطع مجهولة")
    out = []
    for f in vcfg.get("frames", [0.25, 0.5, 0.75]):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{dur * float(f):.2f}", "-i", str(clip),
                              "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                             capture_output=True, timeout=60).stdout
        if not raw:
            raise RuntimeError("تعذّر استخراج لقطة")
        out.append(annotated_jpeg(Image.open(io.BytesIO(raw)), tracks, cfg))
    return out


def call_pick_speaker_model(jpegs: list[bytes], scene: dict, cfg, client=None) -> list[dict]:
    """نداء واحد بكل اللقطات وأداة إجبارية pick_speaker ← قائمة نتائج بعدد اللقطات. الرفض أو ردّ غير صالح يرفع."""
    import base64

    from . import llm
    vcfg = cfg.path("reel.render.speaker.vision") or {}
    if client is None:
        from anthropic import Anthropic

        from .config import env
        client = Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(b).decode("ascii")}} for b in jpegs]
    info = [f"الكلام: {scene.get('quote_arabic', '')}"]
    if scene.get("speaker_name"):
        info.append(f"اسم المتحدث: {scene['speaker_name']}")
    if scene.get("channel_display"):
        info.append(f"القناة: {scene['channel_display']}")
    info.append(f"اللقطات {len(jpegs)} بالترتيب؛ أعد نتيجة واحدة لكل لقطة.")
    content.append({"type": "text", "text": "\n".join(info)})
    resp = llm.create(client, cfg=cfg, model=vcfg.get("model", "haiku"), max_tokens=int(vcfg.get("max_tokens", 500)),
                      system=vcfg.get("system", ""), tools=[PICK_SPEAKER_TOOL],
                      tool_choice={"type": "tool", "name": PICK_SPEAKER_TOOL["name"]},
                      messages=[{"role": "user", "content": content}])
    if getattr(resp, "stop_reason", "") == "refusal":
        raise RuntimeError("رفض النموذج تحديد المتكلم")
    for b in getattr(resp, "content", None) or []:
        if getattr(b, "type", "") == "tool_use" and getattr(b, "name", "") == PICK_SPEAKER_TOOL["name"]:
            frames = (getattr(b, "input", None) or {}).get("frames")
            if isinstance(frames, list) and frames and all(isinstance(f, dict) for f in frames):
                return frames
    raise ValueError("ردّ غير صالح من محدِّد المتكلم")


def _real_pick_speaker(clip, tracks: list, scene: dict, cfg) -> list[dict]:
    return call_pick_speaker_model(_pick_jpegs(clip, tracks, cfg), scene, cfg)


def resolve_speaker_pick(frames: list, n_tracks: int) -> dict:
    """القبول (دالة نقية): الرقم نفسه غير 0 في لقطتين فأكثر ضمن 1..n_tracks. {pick (0 إن لم يُقبل), agree, archive}"""
    counts: dict[int, int] = {}
    archive: set[int] = set()
    for f in frames:
        if not isinstance(f, dict):
            continue
        try:
            s = int(f.get("speaker") or 0)
        except (TypeError, ValueError):
            s = 0
        if 1 <= s <= n_tracks:
            counts[s] = counts.get(s, 0) + 1
        for a in f.get("archive") or []:
            if isinstance(a, int) and not isinstance(a, bool):
                archive.add(a)
    best = max(counts.items(), key=lambda kv: kv[1]) if counts else (0, 0)
    return {"pick": best[0] if best[1] >= 2 else 0, "agree": best[1], "archive": sorted(archive)}


SPEAKER_SOURCES = ("speaker", "speaker_vision", "speaker_motion_override", "speaker_combined")


def motion_override(tracks: list, pick: int, cfg) -> int:
    """(Issue #1434، دالة نقية) رقم المسار (1-based) الذي يغلب اختيار الرؤية، أو 0: مسار آخر فمه وإيماؤه معًا ≥ override_margin ×
    المختار. الرؤية أخطأت مقدّمًا يحرك يديه عدّته أرشيفًا، وحركة الفم وحدها خدعتها لقطات أرشيفية؛ فلا يغلبها إلا الاثنان معًا."""
    m = float(cfg.path("reel.render.speaker.override_margin", 1.25))
    chosen = tracks[pick - 1]
    best = 0
    for i, t in enumerate(tracks, 1):
        if i == pick:
            continue
        if (t["score"] >= m * chosen["score"] and t.get("gesture", 0) >= m * chosen.get("gesture", 0)
                and (t["score"] > chosen["score"] or t.get("gesture", 0) > chosen.get("gesture", 0))
                and (not best or t["score"] > tracks[best - 1]["score"])):
            best = i
    return best


def combined_pick(tracks: list, cfg) -> int:
    """(Issue #1434، دالة نقية) رقم المسار (1-based) بالدرجة المركّبة = فم/أعلى_فم + إيماء/أعلى_إيماء + center_weight × القرب من
    الوسط، أو 0 إن لم يحسم: يلزم فم الأعلى ≥ talk_min ودرجته ≥ combined_margin × الثاني."""
    sc = cfg.path("reel.render.speaker") or {}
    top_m = max((t["score"] for t in tracks), default=0.0)
    top_g = max((t.get("gesture", 0.0) for t in tracks), default=0.0)
    cw = float(sc.get("center_weight", 0.5))
    comp = [(t["score"] / top_m if top_m > 0 else 0.0) + (t.get("gesture", 0.0) / top_g if top_g > 0 else 0.0)
            + cw * t.get("centrality", 0.0) for t in tracks]
    order = sorted(range(len(tracks)), key=lambda i: -comp[i])
    best = order[0]
    if tracks[best]["score"] < float(sc.get("talk_min", 0.3)):
        return 0
    if len(order) > 1 and comp[best] < float(sc.get("combined_margin", 1.15)) * comp[order[1]]:
        return 0
    return best + 1


def _speaker_crop(clip: dict, cfg, deps: Deps, scene: dict | None = None) -> tuple[dict | None, dict]:
    """(نافذة تتوسّط الوجه المتكلم أو None، بيانات للشفافية). الترتيب: الرؤية حين يوجد مساران صالحان فأكثر، ثم حركة الفم بشرط
    التفوق، وإلا None فيبقى أكبر وجه (لا حقن، لا مسارات، غير محسوم، أو عطل). البيانات {tracks, vision?} حين تعدّد الوجوه."""
    meta: dict = {}
    if getattr(deps, "face_tracks", None) is None:
        return None, meta
    try:
        got = deps.face_tracks(clip["file"], cfg)
        if not got:
            return None, meta
        sw, sh, frames, boxes = got
        res = speaker_track(frames, boxes, cfg)
        tracks = res.get("track_list") or []
        if res["tracks"] >= 2:
            meta["tracks"] = res["tracks"]
        attempted = False
        if (len(tracks) >= 2 and cfg.path("reel.render.speaker.vision.enabled", False)
                and getattr(deps, "pick_speaker", None) is not None):
            attempted = True
            try:
                voted = deps.pick_speaker(clip["file"], tracks, scene or {}, cfg)
                if isinstance(voted, list) and voted:
                    vis = resolve_speaker_pick(voted, len(tracks))
                    meta["vision"] = vis
                    if vis["pick"]:
                        over = motion_override(tracks, vis["pick"], cfg)
                        if over:
                            # حركة جسدية صريحة (فم وإيماء) تغلب الرؤية (Issue #1434)
                            vis["overridden_by"] = over
                        chosen = tracks[(over or vis["pick"]) - 1]
                        win = crop_window(int(sw), int(sh), [chosen["center"]], "face")
                        return {**win, "source": "speaker_motion_override" if over else "speaker_vision",
                                "speaker_score": round(float(chosen["score"]), 2), "tracks": res["tracks"]}, meta
            except Exception as exc:  # noqa: BLE001 -- الرؤية تحسين: العطل ← الفم واليدان والموقع
                log.warning("تعذّر تحديد المتكلم بالرؤية فالدرجة المركّبة: %s", str(exc)[:100])
        if attempted:
            # الرؤية لم تحسم (0 أو اختلاف أو عطل أو رفض) ← فم ويدان وقرب من الوسط (Issue #1434)
            pick = combined_pick(tracks, cfg)
            if not pick:
                return None, meta
            chosen = tracks[pick - 1]
            win = crop_window(int(sw), int(sh), [chosen["center"]], "face")
            return {**win, "source": "speaker_combined", "speaker_score": round(float(chosen["score"]), 2),
                    "tracks": res["tracks"]}, meta
        if res["source"] != "speaker":
            return None, meta
        win = crop_window(int(sw), int(sh), [res["center"]], "face")
        return {**win, "source": "speaker", "speaker_score": round(float(res["speaker_score"]), 2), "tracks": res["tracks"]}, meta
    except Exception as exc:  # noqa: BLE001 -- اختيار المتكلم تحسين: العطل ← السلوك الحالي
        log.warning("تعذّر اختيار الوجه المتكلم فأكبر وجه: %s", str(exc)[:100])
        return None, meta


def _crop_for(clip: dict, cfg, deps: Deps, scene: dict | None = None) -> dict:
    """نافذة الاقتطاع الثابتة للمقطع: الوجه المتكلم إن حُسم، وإلا أكبر وجه. تعذّر الكشف أو قراءة المقطع ← المنتصف بتعبير
    ffmpeg نفسه."""
    ccfg = cfg.path("reel.render.crop") or {}
    mode = ccfg.get("mode", "face")
    try:
        if mode != "face":
            raise RuntimeError("mode=center")
        picked, meta = _speaker_crop(clip, cfg, deps, scene)
        if picked is not None:
            return {**picked, **meta}
        sw, sh, centers = deps.faces(clip["file"], list(ccfg.get("samples", [0.2, 0.5, 0.8])))
        return {**crop_window(int(sw), int(sh), centers, mode), **meta}
    except Exception as exc:  # noqa: BLE001 -- الكشف تحسين لا شرط
        if mode == "face":
            log.warning("تعذّر كشف الوجه فنافذة المنتصف: %s", str(exc)[:100])
        return {"w": None, "h": None, "x": None, "source": "center"}


def _prepare_crop(clip: dict, cfg, deps: Deps, scene: dict | None, notes: list | None) -> dict:
    """نافذة الاقتطاع (_crop_for) وسجلّها clip["crop"] وسطر تحديد المتكلم لمقطع تعدّدت وجوهه؛ مشتركة بين مشهد المقطع الكامل
    ولوحة الإجابات (P2c-1) كي يبقى ما يُحفظ للمراجعة واحدًا."""
    crop = _crop_for(clip, cfg, deps, scene)
    clip["crop"] = {"x": crop["x"], "source": crop["source"],
                    **({"speaker_score": crop["speaker_score"], "tracks": crop["tracks"]}
                       if crop["source"] in SPEAKER_SOURCES else {}),
                    **({"tracks": crop["tracks"]} if "tracks" in crop and crop["source"] not in SPEAKER_SOURCES else {}),
                    **({"vision": crop["vision"]} if "vision" in crop else {}),
                    **({"quote_sync": clip["quote_sync"]} if clip.get("quote_sync") else {}),
                    **({"quote_mode": clip["quote_mode"]} if clip.get("quote_mode") else {}),
                    **({"gate": clip["gate"]} if clip.get("gate") else {})}
    if notes is not None and int(crop.get("tracks") or 0) >= 2:
        # سطر لكل مقطع تعدّدت وجوهه يبيّن بأي طريقة حُسم المتكلم، فيراجع صاحب المشروع القرار دون فتح الملف
        t = cfg.path("reel.render.texts")
        how = {"speaker_vision": t["speaker_how_vision"], "speaker": t["speaker_how_motion"],
               "speaker_motion_override": t["speaker_how_override"],
               "speaker_combined": t["speaker_how_combined"]}.get(crop["source"], t["speaker_how_face"])
        notes.append(t["comment_speaker_pick"].format(channel=(scene or {}).get("channel_display", ""), n=crop["tracks"], how=how))
    return crop


def _clip_scene(clip: dict, overlays: tuple[Path, Path], out: Path, cfg, deps: Deps, scene: dict | None = None,
                notes: list | None = None, qframes: list | None = None) -> float:
    """المقطع يملأ الشاشة الرأسية باقتطاع ثابت (يتبع الوجه)، ثم الطبقة الثابتة، ثم طبقة الشريط تدخل من اليمين
    بتباطؤ في آخر الحركة: x = W×(1−p)^3 مع p من 0 إلى 1 خلال slide_seconds بعد انتهاء الانتقال (قبلها خارج الشاشة)."""
    rcfg = cfg.path("reel.render")
    w, h = rcfg["width"], rcfg["height"]
    crop = _prepare_crop(clip, cfg, deps, scene, notes)
    if crop["x"] is None:      # أبعاد المصدر مجهولة: المنتصف بتعبير يحسبه ffmpeg
        cexpr = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0"
        clip["crop"]["x"] = "center"
    else:
        cexpr = f"crop={crop['w']}:{crop['h']}:{crop['x']}:0"
    if scene is not None and cfg.path("reel.render.band.cover") not in (True, False):
        # الغطاء والشريط المعتم فقط حين في أسفل المقطع شريط أخبار أو لافتة (Issue #1408)؛ القرار يُحفظ للمراجعة
        cover = detect_cover(clip["file"], crop["x"], crop["w"], cfg, deps.frames)
        # Q3: حكم النموذج على بداية الرسوم يجعل الغطاء المعتم القائم يخفي الشريط ولو فاته الكاشف (v1 بلا قصّ جديد)
        lg = lower_graphics(clip["file"], cfg, deps, detected=cover, key=clip.get("video_id"),
                            channel=scene.get("channel_display", ""), notes=notes)
        if lg["source"] in ("model", "fallback"):
            clip["crop"]["lower_graphics"] = lg
            cover = cover or lg["top"] < 1
        clip["crop"]["cover"] = cover
        overlays = tuple(_save(im, Path(ov).with_name(Path(ov).stem + "_auto.png"))
                         for im, ov in zip(frame_clip_layers(cfg, scene, cover=cover, quote=qframes is None), overlays))
    slide = float(cfg.path("reel.render.band.slide_seconds", 0) or 0)
    if slide > 0:
        pos = f"x='W*pow(1-min(max((t-{_fmt(transition_seconds(cfg))})/{_fmt(slide)},0),1),3)':y=0"
    else:
        pos = "0:0"
    loops = [x for ov in overlays for x in ("-loop", "1", "-framerate", str(rcfg["fps"]), "-i", str(ov))]
    if qframes:
        # الترجمة تيار حالات (concat بمدد الحالات) بين الطبقة الثابتة وطبقة الشريط، في موضع الصندوق القديم نفسه
        lst = out.with_name(out.stem + "_quote.txt")
        lst.write_text("".join(f"file '{f}'\nduration {_fmt(d)}\n" for f, d in qframes)
                       + f"file '{qframes[-1][0]}'\n", encoding="utf-8")
        loops += ["-f", "concat", "-safe", "0", "-i", str(lst)]
        graph = (f"[0:v]{cexpr},scale={w}:{h}[v0];"
                 f"[v0][1:v]overlay=0:0:shortest=1[v1];"
                 f"[3:v]fps={rcfg['fps']},format=rgba[q];"
                 f"[v1][q]overlay=0:0:shortest=1[v2];"
                 f"[v2][2:v]overlay={pos}:shortest=1,fps={rcfg['fps']},format=yuv420p[v]")
    else:
        graph = (f"[0:v]{cexpr},scale={w}:{h}[v0];"
                 f"[v0][1:v]overlay=0:0:shortest=1[v1];"
                 f"[v1][2:v]overlay={pos}:shortest=1,fps={rcfg['fps']},format=yuv420p[v]")
    deps.run(_base("-i", str(clip["file"]), *loops,
                   "-filter_complex", graph, "-map", "[v]", "-map", "0:a:0", "-af",
                   f"aresample={rcfg.get('audio_rate', 48000)},aformat=channel_layouts=stereo,{_gate_filter(clip, cfg)}{_loudnorm(cfg)}",
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


def quote_word_times(n_words: int, clip_seconds: float, segments: list, start_offset: float, cfg) -> list[float]:
    """زمن ظهور كل كلمة عربية من ترجمة كلام المتحدث داخل المقطع (Issue #1592، R5h). النص المجلوب يعطي منحنى تقدّم الكلام
    لا كلماته: كلمات كل مقطع موزّعة بالتساوي على مدته (حتى بداية التالي، والأخير حتى نهاية النافذة)، والكلمة k من n تظهر
    عند أول زمن يبلغ فيه التقدّم k/n؛ فيتبع النص سرعة المتحدث ووقفاته ولو كان كلامه بلغة أخرى. بلا مقاطع (نافذة تقريبية أو
    تعذّر الجلب) أو بلا كلمات فيها: توزيع متساوٍ من quote.lead إلى clip_seconds − quote.tail. لا كلمة قبل نهاية الانتقال،
    والأزمنة متزايدة وكلها ≤ clip_seconds − 0.1."""
    if n_words <= 0:
        return []
    trans = transition_seconds(cfg)
    hi = max(clip_seconds - 0.1, trans)
    lo = trans
    step = 0.04
    spans: list[tuple[float, float, int]] = []
    ordered = sorted(((float(s) - start_offset, str(t)) for s, t in segments or []), key=lambda x: x[0])
    for k, (st, text) in enumerate(ordered):
        en = ordered[k + 1][0] if k + 1 < len(ordered) else clip_seconds
        a, b = max(st, 0.0), min(en, clip_seconds)
        words = len(text.split())
        if b <= a or en <= st or words == 0:
            continue
        # الكلمات موزّعة على المقطع كله، فالجزء المقتطع بالنافذة يحمل حصته بنسبة التداخل
        spans.append((a, b, words * (b - a) / (en - st)))
    total = sum(w for _, _, w in spans)
    if total <= 0:
        qlead = float(cfg.path("reel.render.quote.lead", 0.3))
        qtail = float(cfg.path("reel.render.quote.tail", 0.4))
        start, end = max(qlead, trans), max(clip_seconds - qtail, max(qlead, trans))
        times = [start + (end - start) * k / n_words for k in range(n_words)]
    else:
        times = []
        for k in range(1, n_words + 1):
            need, acc, t = total * k / n_words, 0.0, spans[-1][1]
            for a, b, w in spans:
                if acc + w >= need - 1e-9:
                    t = a + (b - a) * ((need - acc) / w if w else 1.0)
                    break
                acc += w
            times.append(t)
    out: list[float] = []
    for t in times:
        t = max(t, lo, (out[-1] + step) if out else lo)
        out.append(t)
    for k in range(len(out) - 1, -1, -1):      # تحديد الأعلى من الآخر مع بقاء التزايد
        cap = hi if k == len(out) - 1 else out[k + 1] - step
        out[k] = min(out[k], cap)
    return out


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
    if cfg.path("reel.render.reveal.mode", "lines") == "lines":
        fade = float(cfg.path("reel.render.reveal.fade", 0.25))
        for k, (text, dur) in enumerate(parts):
            hold = min(silence, dur)
            segs = narration_segments(cfg, text, bg)
            counts = [_nonspace(s) for s in segs]
            for j, seg in enumerate(segs):
                lines = narration_lines(cfg, seg, bg)
                span = (dur - hold) * counts[j] / (sum(counts) or 1)
                # آخر مقطع وحده يحمل صمت ما بعد الجملة؛ ما قبله يُمسح عند بدء التالي
                steps = reveal_steps([_nonspace(ln) for ln in lines], span, hold if j == len(segs) - 1 else 0.0, fps, fade)
                for m, (alphas, d) in enumerate(steps):
                    im = frame_narration_reveal(cfg, seg, alphas, bg=bg)
                    frames.append((_save(im, tmp / f"nar_{i}_{k}_{j}_{m}.png"), d))
        return frames
    for k, (text, dur) in enumerate(parts):
        hold = min(silence, dur)
        steps = typewriter_steps(text, dur - hold, hold, fps)
        if k == 0 and lead > 0 and steps[0][0]:
            steps = [("", 0.0)] + steps    # lead يُضاف إلى هذه الخطوة الفارغة في _timed_scene
        for j, (prefix, d) in enumerate(steps):
            im = frame_narration_typed(cfg, text, prefix, bg=bg) if bg is not None else frame_narration_typed(cfg, text, prefix)
            frames.append((_save(im, tmp / f"nar_{i}_{k}_{j}.png"), d))
    return frames


# ───────────────────── اسم المتحدث وصفته من شريط القناة (Issue #1427، R5b) ─────────────────────

CHYRON_TOOL = {
    "name": "read_lower_third",
    "description": "يعيد لكل لقطة ما هو مكتوب على الشاشة من اسم المتحدث وصفته، بالترتيب نفسه",
    "input_schema": {"type": "object", "properties": {"frames": {"type": "array", "items": {
        "type": "object",
        "properties": {"has_caption": {"type": "boolean"}, "name_original": {"type": "string"},
                       "name_arabic": {"type": "string"}, "role_original": {"type": "string"},
                       "role_arabic": {"type": "string"}, "is_presenter": {"type": "boolean"},
                       "name_kind": {"type": "string", "enum": ["person", "program", "channel", "other"]}},
        "required": ["has_caption", "name_original", "name_arabic", "role_original", "role_arabic", "is_presenter",
                     "name_kind"]}}},
        "required": ["frames"]},
}
_LATIN_CHARS = re.compile(r"[A-Za-z\u00C0-\u024F]")


def _chyron_jpegs(clip, cfg) -> list[bytes]:
    """لقطات كاملة غير مقتطعة عند نِسب مدة المقطع، مصغَّرة إلى عرض max_width بصيغة JPEG؛ يرفع إن تعذّر استخراج لقطة."""
    import io
    ccfg = cfg.path("reel.render.chyron") or {}
    dur = probe_duration(clip)
    if not dur:
        raise RuntimeError("مدة المقطع مجهولة")
    out = []
    for f in ccfg.get("frames", [0.25, 0.5, 0.75]):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{dur * float(f):.2f}", "-i", str(clip),
                              "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                             capture_output=True, timeout=60).stdout
        if not raw:
            raise RuntimeError("تعذّر استخراج لقطة")
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        width = int(ccfg.get("max_width", 1280))
        if img.width > width:
            img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        out.append(buf.getvalue())
    return out


def call_chyron_model(jpegs: list[bytes], cfg, client=None) -> list[dict]:
    """نداء واحد بكل اللقطات وأداة إجبارية read_lower_third ← قائمة نتائج بعدد اللقطات. الرفض أو ردّ غير صالح يرفع."""
    import base64

    from . import llm
    ccfg = cfg.path("reel.render.chyron") or {}
    if client is None:
        from anthropic import Anthropic

        from .config import env
        client = Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(b).decode("ascii")}} for b in jpegs]
    content.append({"type": "text", "text": f"اللقطات {len(jpegs)} بالترتيب؛ أعد نتيجة واحدة لكل لقطة."})
    resp = llm.create(client, cfg=cfg, model=ccfg.get("model", "haiku"), max_tokens=int(ccfg.get("max_tokens", 600)),
                      system=ccfg.get("system", ""), tools=[CHYRON_TOOL],
                      tool_choice={"type": "tool", "name": CHYRON_TOOL["name"]},
                      messages=[{"role": "user", "content": content}])
    if getattr(resp, "stop_reason", "") == "refusal":
        raise RuntimeError("رفض النموذج قراءة اللقطات")
    for b in getattr(resp, "content", None) or []:
        if getattr(b, "type", "") == "tool_use" and getattr(b, "name", "") == CHYRON_TOOL["name"]:
            frames = (getattr(b, "input", None) or {}).get("frames")
            if isinstance(frames, list) and frames and all(isinstance(f, dict) for f in frames):
                return frames
    raise ValueError("ردّ غير صالح من قارئ الشريط")


def _real_read_chyron(clip, cfg) -> list[dict]:
    return call_chyron_model(_chyron_jpegs(clip, cfg), cfg)


# ───────────────────── بداية رسوم القناة السفلية: يحكم نموذج يرى اللقطات (Issue #1646، Q3) ─────────────────────

LOWER_GRAPHICS_TOOL = {
    "name": "locate_lower_graphics",
    "description": "يعيد لكل لقطة أعلى نقطة لرسوم القناة الثابتة في أسفل الإطار (1 = لا رسوم)",
    "input_schema": {"type": "object", "properties": {"frames": {"type": "array", "items": {
        "type": "object",
        "properties": {"graphics_top": {"type": "number", "minimum": 0, "maximum": 1}, "what": {"type": "string"}},
        "required": ["graphics_top", "what"]}}},
        "required": ["frames"]},
}


def call_lower_graphics_model(jpegs: list[bytes], cfg, client=None) -> list[dict]:
    """نداء واحد بكل اللقطات وأداة إجبارية locate_lower_graphics ← قائمة بعدد اللقطات. الرفض أو ردّ غير صالح يرفع."""
    import base64

    from . import llm
    lcfg = cfg.path("reel.render.lower_graphics") or {}
    if client is None:
        from anthropic import Anthropic

        from .config import env
        client = Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(b).decode("ascii")}} for b in jpegs]
    content.append({"type": "text", "text": f"اللقطات {len(jpegs)} بالترتيب؛ أعد نتيجة واحدة لكل لقطة."})
    resp = llm.create(client, cfg=cfg, model=lcfg.get("model", "haiku"), max_tokens=int(lcfg.get("max_tokens", 500)),
                      system=lcfg.get("system", ""), tools=[LOWER_GRAPHICS_TOOL],
                      tool_choice={"type": "tool", "name": LOWER_GRAPHICS_TOOL["name"]},
                      messages=[{"role": "user", "content": content}])
    if getattr(resp, "stop_reason", "") == "refusal":
        raise RuntimeError("رفض النموذج قراءة اللقطات")
    for b in getattr(resp, "content", None) or []:
        if getattr(b, "type", "") == "tool_use" and getattr(b, "name", "") == LOWER_GRAPHICS_TOOL["name"]:
            frames = (getattr(b, "input", None) or {}).get("frames")
            if isinstance(frames, list) and frames and all(isinstance(f, dict) for f in frames):
                return frames
    raise ValueError("ردّ غير صالح من محدّد رسوم القناة")


def _real_read_lower_graphics(clip, cfg) -> list[dict]:
    return call_lower_graphics_model(_chyron_jpegs(clip, cfg), cfg)


def _graphics_values(raw) -> list[float] | None:
    """قيم graphics_top من ردّ القارئ (أرقامًا أو عناصر فيها graphics_top)؛ None لمخرج غير صالح، وقائمة فارغة = لا نموذج."""
    if not isinstance(raw, list):
        return None
    vals = []
    for f in raw:
        v = f.get("graphics_top") if isinstance(f, dict) else f
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
            return None
        vals.append(float(v))
    return vals


def graphics_crop(frames_result, cfg, detected: bool = False, ticker_top: float | None = None) -> dict:
    """قرار القصّ من حكم النموذج (دالة خالصة): نطاق في لقطتين فأكثر ← أصغر قيمة − margin بحد أدنى min_top (clamped)؛ أقل من لقطتين ←
    1؛ فشل النداء أو مخرج غير صالح (None) ← fallback_top؛ والكاشف القديم شبكة أمان: كشف شريطًا والنموذج قال لا شيء ← ticker_top.
    قائمة فارغة = لا قارئ أصلًا. {top, source: model|detector|fallback|none, clamped, frames}."""
    lg = cfg.path("reel.render.lower_graphics") or {}
    vals = _graphics_values(frames_result)
    if vals is None:
        return {"top": round(float(lg.get("fallback_top", 0.80)), 4), "source": "fallback", "clamped": False, "frames": []}
    low = [v for v in vals if v < 1]
    if len(low) >= 2:
        top = min(low) - float(lg.get("margin", 0.02))
        floor = float(lg.get("min_top", 0.60))
        return {"top": round(max(top, floor), 4), "source": "model", "clamped": top < floor, "frames": vals}
    if detected:
        return {"top": round(float(ticker_top if ticker_top is not None else lg.get("fallback_top", 0.80)), 4),
                "source": "detector", "clamped": False, "frames": vals}
    return {"top": 1, "source": "model" if vals else "none", "clamped": False, "frames": vals}


def lower_graphics(clip_file, cfg, deps: "Deps", detected: bool = False, ticker_top: float | None = None, key=None,
                   channel: str = "", notes: list | None = None) -> dict:
    """بداية رسوم القناة السفلية لمقطع (Q3): نداء نموذج واحد لكل فيديو في التركيب كله (رسوم القناة ثابتة في البرنامج) مهما تعددت
    مقاطعه ونوافذه، ثم graphics_crop. بلا read_lower_graphics (مزيَّفات قديمة) لا نداء ويبقى الكاشف وحده. لا ترفع أبدًا."""
    lcfg = cfg.path("reel.render.lower_graphics") or {}
    reader = deps.read_lower_graphics if lcfg.get("enabled", True) else None
    memo = deps.__dict__.setdefault("_lg_memo", {})
    k = str(key or clip_file)
    if k not in memo:
        raw: Any = []
        if reader is not None:
            try:
                raw = reader(clip_file, cfg)
            except Exception as exc:  # noqa: BLE001 -- الحكم تحسين: العطل ← fallback_top
                log.warning("تعذّر تحديد شريط القناة بالنموذج: %s", re.sub(r"(?<=://)[^/@\s]*@", "", reel_clips.scrub_text(str(exc)))[:100])
                raw = None
        memo[k] = {"raw": raw, "noted": False}
    res = graphics_crop(memo[k]["raw"], cfg, detected, ticker_top)
    if notes is not None and not memo[k]["noted"] and res["source"] in ("model", "fallback") and (
            res["top"] < 1 or res["source"] == "fallback"):
        memo[k]["noted"] = True
        t = cfg.path("reel.render.texts")
        pct = round((1 - res["top"]) * 100)
        notes.append((t["comment_lower_graphics_failed"] if res["source"] == "fallback" else t["comment_lower_graphics"]
                      ).format(channel=channel, pct=pct))
    return res


def _fold_name(text: str) -> str:
    """توحيد للمقارنة وحدها: مسافات وحالة أحرف، وحذف «ال» من أول الكلمة الأولى فيطابق «النقاش» «نقاش» (Issue #1450)."""
    words = " ".join(str(text or "").split()).casefold().split(" ")
    if words and words[0].startswith("ال") and len(words[0]) > 3:
        words[0] = words[0][2:]
    return " ".join(w for w in words if w)


def _chyron_reject_reason(frame: dict, cfg, channels: list) -> str:
    """لماذا لا تُعدّ هذه اللقطة اسمَ شخص؛ فارغ إن كانت كذلك. name_kind الغائب يُقبل (توافقًا مع المزيَّفات القديمة)، وnot_names
    شبكة أمان لا بديل عن name_kind لأن النموذج يخطئ في تصنيف اسم برنامج شخصًا."""
    kind = frame.get("name_kind")
    if kind in ("program", "channel"):
        return kind
    if kind not in (None, "", "person"):
        return "not_names"
    forms = {_fold_name(frame.get("name_original")), _fold_name(frame.get("name_arabic"))} - {""}
    banned = {_fold_name(n) for n in (cfg.path("reel.render.chyron.not_names") or [])} - {""}
    if forms & banned:
        return "not_names"
    for ch in channels:
        ch = _fold_name(ch)
        if len(ch) >= 3 and any(ch in form for form in forms):
            return "channel"
    return ""


def resolve_chyron(frames: list, cfg, channel: str | list = "") -> dict:
    """القبول من نتائج اللقطات (دالة نقية): اسم شخص متطابق بعد توحيد المسافات وحالة الأحرف في لقطتين فأكثر؛ الصفة من أول لقطة
    فيها ذلك الاسم. اسم البرنامج أو القناة لا يُعدّ (Issue #1450). is_presenter صحيحة إن قالتها لقطتان فأكثر.
    {name_original, name_arabic, role_arabic, is_presenter, frames_agreeing, accepted, rejected}؛ rejected سبب إسقاط الاسم
    الأكثر تكرارًا: program | channel | not_names، وفارغ إن لم يُسقَط شيء."""
    channels = [channel] if isinstance(channel, str) else list(channel or [])
    valid: dict[str, list[dict]] = {}
    invalid: dict[str, list[dict]] = {}
    for f in frames:
        name = " ".join(str(f.get("name_original") or "").split())
        if name:
            (invalid if _chyron_reject_reason(f, cfg, channels) else valid).setdefault(name.casefold(), []).append(f)
    best = max(valid.values(), key=len) if valid else []
    rejected = ""
    if len(best) < 2 and invalid:
        # لا اسم شخص مقبول: يبقى الأكثر تكرارًا بين المرفوضات سببًا وللتعليق اسمًا
        worst = max(invalid.values(), key=len)
        if not best:
            best = worst
        rejected = _chyron_reject_reason(worst[0], cfg, channels)
    first = best[0] if best else {}
    agreeing = len(best)
    name_ar = " ".join(str(first.get("name_arabic") or "").split())
    return {"name_original": " ".join(str(first.get("name_original") or "").split()), "name_arabic": name_ar,
            "role_arabic": " ".join(str(first.get("role_arabic") or "").split()),
            "is_presenter": sum(1 for f in frames if f.get("is_presenter") is True) >= 2,
            "frames_agreeing": agreeing, "rejected": rejected,
            "accepted": agreeing >= 2 and bool(name_ar) and not rejected}


_AR_LETTERS = re.compile(r"[\u0600-\u06FF]")


def _speaker_words(text: str) -> set[str]:
    """كلمات الاسم للمقارنة: توحيد التشكيل والترقيم وحالة الأحرف (youtube_extract._normalize_for_anchor) وحذف «ال» من أول الكلمة، وما دون
    3 أحرف يُهمل (R6)."""
    from . import youtube_extract
    out = set()
    for w in youtube_extract._normalize_for_anchor(text or "").split():
        w = w[2:] if w.startswith("ال") and len(w) > 4 else w
        if len(w) >= 3:
            out.add(w)
    return out


def speaker_matches(name_arabic: str, name_original: str, speaker_text: str, cfg) -> bool | None:
    """هل اسم الشريط هو قائل الاقتباس؟ (Issue #1621، R6) دالة خالصة. كلمات اسم القائل من speaker_text بعد حذف الصفات وكلمات الدور
    (youtube_article.speaker_name_tokens) وكلمات «لم يُذكر اسمه»؛ تتفق إن اشترك الطرفان في كلمة من 3 أحرف فأكثر: الاسم العربي من
    الشريط والاسم الأصلي إن كان عربي الحروف. None = لا مقارنة (قائل بلا اسم علم، أو شريط بلا كلمات صالحة) فيبقى السلوك كما كان.
    القاعدة لا تغيّر لحالات النقل المختلف للاسم نفسه («براء» مقابل «بار»): تلك تُحذف احتياطًا، ونسبة الكلام إلى غير قائله أسوأ."""
    from . import youtube_article
    skip = _speaker_words(" ".join(cfg.path("reel.render.chyron.unnamed_words", []) or []))
    spoken = _speaker_words(" ".join(youtube_article.speaker_name_tokens(speaker_text or "", "", cfg))) - skip
    chyron = _speaker_words(name_arabic or "")
    if name_original and _AR_LETTERS.search(name_original):
        chyron |= _speaker_words(name_original)
    if not spoken or not chyron:
        return None
    return bool(spoken & chyron)


def _apply_chyron(scene: dict, clip: dict, cfg, deps: Deps, speakers: dict, notes: list, index: int) -> dict | None:
    """يوثّق متحدث مقطع غير موثَّق من شريط القناة. الموثَّق من العنوان أو الوصف لا يُمسّ ولا يُرسل؛ ولا يُرفع فشل أبدًا
    (العطل أو الرفض أو الردّ غير الصالح يُبقي «ضيف على»). اسم شخص مقبول يُقارَن بقائل النقطة (speaker_text): الخلاف (R6) لا يُطبَّق على
    المشهد ويُعاد {chyron, speaker} فيحذف _assemble المقطع من اللوحة؛ يُستدعى مرتين لكل مقطع (قبل بناء اللوحة وفي _clip_layers) فالقراءة تُحفظ
    في speakers ولا تُعاد."""
    if not cfg.path("reel.render.chyron.enabled", False) or scene.get("speaker_verified") and scene.get("speaker_name"):
        return None
    if str(index) in speakers:
        return speakers[str(index)].get("mismatch")
    if getattr(deps, "read_chyron", None) is None:
        return None
    try:
        frames = deps.read_chyron(clip["file"], cfg)
        if not isinstance(frames, list) or not frames:
            return None
        res = resolve_chyron([f for f in frames if isinstance(f, dict)], cfg,
                             [scene.get("channel_original") or "", scene.get("channel_display") or ""])
    except Exception as exc:  # noqa: BLE001 -- القراءة تحسين لا شرط
        log.warning("تعذّرت قراءة شريط القناة فيبقى «ضيف على»: %s", str(exc)[:120])
        return None
    speakers[str(index)] = res
    if res["accepted"] and speaker_matches(res["name_arabic"], res["name_original"], scene.get("speaker_text", ""), cfg) is False:
        mismatch = {"chyron": res["name_arabic"], "speaker": " ".join(str(scene.get("speaker_text") or "").split())}
        res["mismatch"] = mismatch
        log.warning("شريط القناة %s لا يطابق قائل النقطة %s", mismatch["chyron"], mismatch["speaker"])
        return mismatch
    if res["accepted"]:
        scene.update(speaker_verified=True, speaker_verified_from="chyron", speaker_name=res["name_arabic"],
                     speaker_name_latin=res["name_original"] if _LATIN_CHARS.search(res["name_original"]) else "",
                     speaker_role=res["role_arabic"])
        line = cfg.path("reel.render.texts.comment_chyron").format(
            name_arabic=res["name_arabic"], name_original=res["name_original"], role_arabic=res["role_arabic"])
        if line not in notes:
            notes.append(line)
    else:
        if res["is_presenter"]:
            scene["speaker_presenter"] = True
        if res.get("rejected") in ("program", "channel", "not_names"):
            # اسم البرنامج يُعرض لو قُبل اسمًا لشخص فيُنبَّه المراجع إلى أن الشريط عُوملَ كأنه بلا اسم
            line = cfg.path("reel.render.texts.comment_chyron_program").format(name=res["name_arabic"] or res["name_original"])
            if line not in notes:
                notes.append(line)
    return None


# ───────────────────── الهوك والشعار الكبير (Issue #1429، R5c1) ─────────────────────


def pan_x(t: float, x0: float, speed: float) -> float:
    """إزاحة x لنافذة 1080 عند الزمن t: تبدأ من x0 وتتناقص بسرعة ثابتة ولا تنزل عن 0. pan_plan تضمن ألا يبلغ x(T) الصفر قبل
    نهاية المشهد، فالـmax هنا شبكة أمان لا سلوكًا عاديًا (Issue #1447)."""
    return max(float(x0) - float(speed) * t, 0.0)


def _pan_x_expr(x0: float, speed: float, t0: float = 0.0) -> str:
    """تعبير crop الزمني نفسه الذي تحسبه pan_x حرفًا بحرف (x0 ناقص السرعة × t ولا أقل من 0). t0 زمن بداية المشهد التراكمي
    فتتصل الحركة بين مشاهد الراوي (الإزاحة تبدأ من حيث انتهت في السابق)؛ 0 يعطي تعبير الهوك."""
    at = "t" if not t0 else f"(t+{_fmt(t0)})"
    return f"max({_fmt(x0)}-{_fmt(speed)}*{at},0)"


def pan_plan(cfg, key: str, wide_w: float, wide_h: float, seconds: float, cx: float) -> dict:
    """خطة حركة الخلفية فوق الصورة الكاملة wide (Issue #1447، متابعة R5d1): الحركة لا تتوقف أبدًا من أول المشهد حتى آخره.
    key: narration_bg أو hook. تُفضَّل السرعة البطيئة المحددة في الإعداد؛ إن لم يكفِ عرض الصورة لها طوال seconds تُكبَّر الصورة
    حتى max_zoom، فإن بقي المدى قاصرًا خُفّضت السرعة لتغطي المدة (وسطر تحذير إن نزلت دون min_speed، فالبقاء داخل حدود
    الصورة أولى من السرعة). النافذة (إزاحتها اليسرى) تقطع مقطعًا متمركزًا حول cx ومقصوصًا داخل الحدود، تبدأ من يمينه وتنتهي
    عند يساره. يعيد dict(zoom, speed, x0, img_w, img_h) والقيم مقرَّبة إلى ثلاث خانات كي يطابق تعبير ffmpeg حساب بايثون."""
    kc = cfg.path(f"reel.render.{key}")
    w = float(cfg.path("reel.render.width"))
    pref, floor, max_zoom = float(kc["pan_speed"]), float(kc.get("min_speed", 8)), float(kc.get("max_zoom", 1.5))
    seconds = max(float(seconds), 0.001)
    wide_w, wide_h = float(wide_w), float(wide_h)
    zoom = max(1.0, w / wide_w)    # لا صورة أضيق من النافذة
    need = pref * seconds
    if wide_w * zoom - w < need:
        zoom = max(zoom, min((need + w) / wide_w, max_zoom))
    speed = pref
    room = wide_w * zoom - w
    if room < need:
        speed = math.floor(room / seconds * 1000) / 1000
        if speed < floor:
            log.warning("مدى حركة الخلفية لا يكفي %.1f ثانية بسرعة %s فنزلت السرعة إلى %s", seconds, _fmt(floor), _fmt(speed))
    img_w, img_h = round(wide_w * zoom), round(wide_h * zoom)
    span = speed * seconds
    lo = math.ceil(span * 1000) / 1000
    hi = math.floor((img_w - w) * 1000) / 1000
    x0 = min(max(float(cx) * zoom - w / 2 + span / 2, lo), max(hi, lo))
    return {"zoom": zoom, "speed": speed, "x0": round(x0, 3), "img_w": img_w, "img_h": img_h}


def _wide_of(bg: dict) -> tuple[Image.Image, float]:
    """(الصورة الكاملة، مركز الوجوه فيها)؛ خلفية بلا wide (قديمة) تقع على raw بمنتصفها."""
    if bg.get("wide") is not None:
        return bg["wide"], float(bg.get("wide_cx", bg["wide"].size[0] / 2))
    old = bg.get("raw") or bg["image"]
    return old, old.size[0] / 2


def _pan_background(wide: Image.Image, plan: dict, tmp: Path, name: str) -> Path:
    """صورة الخلفية مُكبَّرة مرة واحدة في بايثون إلى أبعاد الخطة، فيقصّ ffmpeg وحده كل إطار ولا يعيد تكبير صورة كبيرة."""
    if wide.size != (plan["img_w"], plan["img_h"]):
        wide = wide.resize((plan["img_w"], plan["img_h"]), Image.LANCZOS)
    return _save(wide, tmp / name)


def _ease_out(p: float) -> float:
    return 1 - (1 - p) ** 3


def _ease_in_out(p: float) -> float:
    return p * p * (3 - 2 * p)


def logo_state(t: float, cfg, hook_end: float, outro_start: float | None = None) -> tuple[float, float, float, float]:
    """(x, y, العرض, الشفافية) للشعار عند الزمن t. افتتاح P1a (Issue #1600): الشعار كبير ثابت من الإطار الأول بلا ظهور ولا تكبير
    وفي موضع شعار الخاتمة نفسه (outro.logo_width متمركزًا وأعلاه outro.logo_top) كي يطابق أول إطار آخر إطار؛ عند hook_end (بدء
    الانتقال إلى المشهد التالي) ينتقل خلال hook.logo_move بتسارع ease-in-out إلى موضع الزاوية (reel.render.logo) ويبقى فيه.
    مرحلة الخاتمة (Issue #1592، R5h): عند outro_start يتحرك من الزاوية خلال outro.logo_move بالتسارع نفسه إلى الهندسة الكبيرة نفسها
    ويثبت؛ بلا outro_start لا مرحلة (السلوك القديم)."""
    hk, lg, oc = cfg.path("reel.render.hook"), cfg.path("reel.render.logo"), cfg.path("reel.render.outro")
    w = float(cfg.path("reel.render.width"))
    big_w = float(oc["logo_width"])
    big_x, big_y = (w - big_w) / 2, float(oc["logo_top"])
    e2 = _ease_in_out(min(max((t - hook_end) / float(hk["logo_move"]), 0.0), 1.0))
    small_w = float(lg["width"])
    small_x, small_y = w - float(lg["right"]) - small_w, float(lg["top"])
    x, y, lw = (big_x + (small_x - big_x) * e2, big_y + (small_y - big_y) * e2, big_w + (small_w - big_w) * e2)
    if outro_start is not None:
        e3 = _ease_in_out(min(max((t - outro_start) / float(oc["logo_move"]), 0.0), 1.0))
        x, y, lw = x + (big_x - x) * e3, y + (big_y - y) * e3, lw + (big_w - lw) * e3
    return (x, y, lw, 1.0)


def _logo_exprs(cfg, hook_end: float, outro_start: float | None = None) -> dict:
    """تعابير ffmpeg (بالمتغير t) لدالة logo_state نفسها: w وx وy للمرشحين scale وoverlay (الشفافية ثابتة 1 فلا fade)."""
    hk, lg, oc = cfg.path("reel.render.hook"), cfg.path("reel.render.logo"), cfg.path("reel.render.outro")
    w = int(cfg.path("reel.render.width"))
    big_w, big_y = int(oc["logo_width"]), int(oc["logo_top"])
    big_x = f"(({w}-{big_w})/2)"
    p2 = f"min(max((t-{_fmt(hook_end)})/{_fmt(float(hk['logo_move']))},0),1)"
    e2 = f"({p2}*{p2}*(3-2*{p2}))"
    small_w, small_x = int(lg["width"]), w - int(lg["right"]) - int(lg["width"])
    out = {"w": f"({big_w}+({small_w}-{big_w})*{e2})",
           "x": f"({big_x}+({small_x}-{big_x})*{e2})",
           "y": f"({big_y}+({int(lg['top'])}-{big_y})*{e2})"}
    if outro_start is not None:
        p3 = f"min(max((t-{_fmt(outro_start)})/{_fmt(float(oc['logo_move']))},0),1)"
        e3 = f"({p3}*{p3}*(3-2*{p3}))"
        out = {"w": f"({out['w']}+({big_w}-{out['w']})*{e3})",
               "x": f"({out['x']}+({big_x}-{out['x']})*{e3})",
               "y": f"({out['y']}+({big_y}-{out['y']})*{e3})"}
    return out


def fog_alpha(t: float, cfg, strong: float) -> float:
    """مضروب شفافية الضباب عند الزمن t (P1a، Issue #1600): يزول خطيًا من loop.fog_start إلى 0 خلال loop.fog_out (تمهيد للإعادة
    المتصلة: الختام سينتهي بالقيمة نفسها)، يبقى 0 حتى strong (اللقطة نظيفة)، ثم يظهر 0←1 خلال hook.fog_in ويثبت على 1."""
    lp, hk = cfg.path("reel.render.loop"), cfg.path("reel.render.hook")
    fog_out, fog_in = float(lp["fog_out"]), float(hk["fog_in"])
    fade_out = max(float(lp["fog_start"]) * (1 - t / fog_out), 0.0)
    return fade_out + min(max((t - strong) / fog_in, 0.0), 1.0)


def _fog_alpha_expr(cfg, strong: float, var: str = "t") -> str:
    """تعبير ffmpeg لدالة fog_alpha نفسها بالمعادلة حرفًا بحرف، بلا if/lt ليُقيَّم بالمتغير t في الاختبار؛ var="T" لمرشح geq."""
    lp, hk = cfg.path("reel.render.loop"), cfg.path("reel.render.hook")
    return (f"(max({_fmt(float(lp['fog_start']))}*(1-{var}/{_fmt(float(lp['fog_out']))}),0)"
            f"+min(max(({var}-{_fmt(strong)})/{_fmt(float(hk['fog_in']))},0),1))")


def fog_layer(cfg) -> Image.Image:
    """طبقة الضباب الكحلي بمقاس الشاشة (P1a): لون brand.primary_color، شفافيتها fog.base + fog.center × قناع إهليلجي مموّه بين
    fog.top وfog.bottom بعرض الشاشة + fog.side من كل جانب. الشفافية الزمنية تُضرب فيها بمرشح ffmpeg لا هنا."""
    from PIL import ImageFilter
    w, h = int(cfg.path("reel.render.width")), int(cfg.path("reel.render.height"))
    fg = cfg.path("reel.render.fog")
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse((-int(fg["side"]), int(fg["top"]), w + int(fg["side"]), int(fg["bottom"])), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(float(fg["blur"])))
    base, center = float(fg["base"]), float(fg["center"])
    alpha = mask.point(lambda v: round(min(max(base + center * v / 255, 0.0), 1.0) * 255))
    layer = Image.new("RGBA", (w, h), (*imaging.hex_rgb(cfg.path("brand.primary_color")), 0))
    layer.putalpha(alpha)
    return layer


# ───────────────────── ختام الريل الجديد (Issue #1602، P1a-2) ─────────────────────

def closing_question_text(q: str, cfg) -> str:
    """نص سؤال الختام المعروض والمقروء معًا: تُحذف واو العطف من أوله إن تبعتها مباشرةً إحدى أدوات reel.closing.question_words،
    لأن السؤال يأتي بعد «برأيك..» فلا معطوف عليه. كلمة تبدأ بالواو ولا تعقبها أداة كاملة («وزير») لا تُمسّ."""
    text = str(q or "").strip()
    words = list(cfg.path("reel.closing.question_words", []) or [])
    if text.startswith("و") and text[1:].split(" ", 1)[0].rstrip("؟?،,.!") in words:
        return text[1:]
    return text


def closing_plan(question_seconds: float, cfg, lead: float, label_seconds: float = 0.0) -> dict:
    """أزمنة مشهد الختام نسبةً إلى بدايته (دالة خالصة). voice: بدء الراوي قراءة السؤال؛ logo: بدء نزول الشعار من الزاوية وبدء اختفاء
    السؤال؛ info_in: استقرار الشعار وبدء ظهور المعلومات تحته؛ info_out: بدء اختفائها؛ total: مدة المشهد. lead مدة الانتقال إلى المشهد."""
    cl, oc, hk = cfg.path("reel.render.closing"), cfg.path("reel.render.outro"), cfg.path("reel.render.hook")
    voice = float(lead) + float(hk["voice_delay"])
    # Q5: الراوي يقرأ «برأيك» (label_seconds بصمتها) ثم وقفة label_pause ثم السؤال؛ بلا نطق لها (0) يبقى الحساب القديم حرفًا
    question = voice + (float(label_seconds) + float(cl["label_pause"]) if label_seconds > 0 else 0.0)
    logo = question + float(question_seconds) + float(cl["question_tail"])
    info_in = logo + float(oc["logo_move"])
    info_out = info_in + float(cl["info_in"]) + float(cl["info_hold"])
    return {"lead": float(lead), "voice": voice, "question": question, "logo": logo, "info_in": info_in, "info_out": info_out,
            "total": info_out + float(cl["info_out"])}


def closing_logo_offset(total: float, cfg) -> float:
    """موضع بدء نزول الشعار من بداية مشهد الختام معروفًا مدته الكلية: كل ما بعده ثابت في الإعداد (logo_move + info_in + info_hold +
    info_out)، فلا حاجة لتمرير الخطة من _assemble إلى التمريرة الأخيرة."""
    cl, oc = cfg.path("reel.render.closing"), cfg.path("reel.render.outro")
    return float(total) - (float(oc["logo_move"]) + float(cl["info_in"]) + float(cl["info_hold"]) + float(cl["info_out"]))


def closing_fog_alpha(t: float, cfg, plan: dict) -> float:
    """مضروب شفافية الضباب في الختام: يظهر 0←1 خلال closing.fog_in بعد lead ويبقى 1 حتى info_out ثم ينخفض خطيًا إلى loop.fog_start
    عند total تمامًا، فيحمل آخر إطار ضباب أول إطار من الهوك (الإعادة المتصلة)."""
    cl, fs = cfg.path("reel.render.closing"), float(cfg.path("reel.render.loop.fog_start"))
    up = min(max((t - plan["lead"]) / float(cl["fog_in"]), 0.0), 1.0)
    down = 1 - (1 - fs) * min(max((t - plan["info_out"]) / (plan["total"] - plan["info_out"]), 0.0), 1.0)
    return up * down


def _closing_fog_expr(cfg, plan: dict, var: str = "t") -> str:
    """تعبير ffmpeg لدالة closing_fog_alpha نفسها بالصياغة المتبعة في fog_alpha (بلا if)؛ var="T" لمرشح geq."""
    cl, fs = cfg.path("reel.render.closing"), float(cfg.path("reel.render.loop.fog_start"))
    return (f"(min(max(({var}-{_fmt(plan['lead'])})/{_fmt(float(cl['fog_in']))},0),1)"
            f"*(1-(1-{_fmt(fs)})*min(max(({var}-{_fmt(plan['info_out'])})/{_fmt(plan['total'] - plan['info_out'])},0),1)))")


def qcard_fog_alpha(t: float, cfg, lead: float) -> float:
    """مضروب شفافية ضباب بطاقة السؤال (P2b، Issue #1613): qcard.fog_from من أول إطار حتى lead (لا إطار عاريًا بعد مشهد السياق
    المظلَّل)، ثم يشتد خطيًا إلى 1 خلال qcard.fog_in، ثم 1 حتى نهاية المشهد."""
    f0 = float(cfg.path("reel.render.qcard.fog_from"))
    return f0 + (1.0 - f0) * min(max((t - lead) / float(cfg.path("reel.render.qcard.fog_in")), 0.0), 1.0)


def _qcard_fog_expr(cfg, lead: float, var: str = "t") -> str:
    """تعبير ffmpeg لدالة qcard_fog_alpha نفسها بالمعادلة حرفًا بحرف، بلا if/lt؛ var="T" لمرشح geq."""
    f0 = _fmt(float(cfg.path("reel.render.qcard.fog_from")))
    return (f"({f0}+(1-{f0})*min(max(({var}-{_fmt(lead)})/{_fmt(float(cfg.path('reel.render.qcard.fog_in')))},0),1))")


def _shade_filter(cfg, key: str = "hook") -> str:
    r, g, b = imaging.hex_rgb(cfg.path("brand.primary_color"))
    return f"drawbox=x=0:y=0:w=iw:h=ih:color=0x{r:02X}{g:02X}{b:02X}@{_fmt(float(cfg.path(f'reel.render.{key}.shade')))}:t=fill"


def _hook_crop(clip: Path, cfg, deps: Deps, crops: dict | None, video_id=None, channel: str = "",
               notes: list | None = None) -> str:
    """تعبير اقتطاع 9:16 للقطة الهوك (Issue #1447، R5d1). كاشف شريط الأسفل نفسه يُطبَّق على العرض الكامل (لا على نافذة 9:16)
    لأن الشريط يمتد على عرض الكادر؛ Q3: حكم النموذج على بداية الرسوم (lower_graphics) يغلب والكاشف شبكة أمان، فيُقتطع أعلى top من
    ارتفاع المصدر بعرض ذلك الارتفاع ×9/16 في الوسط فيخرج الشريط من الكادر (top = 1 ← الاقتطاع القديم). تعذّر قراءة أبعاد المصدر ←
    الاقتطاع القديم. القرار يُحفظ في crops["hook"] للمراجعة."""
    default = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0"
    try:
        sw, sh, _ = deps.faces(clip, list((cfg.path("reel.render.crop") or {}).get("samples", [0.2, 0.5, 0.8])))
        sw, sh = int(sw), int(sh)
        ticker = detect_cover(clip, 0, sw, cfg, deps.frames)
    except Exception as exc:  # noqa: BLE001 -- الكشف تحسين لا شرط
        log.warning("تعذّر كشف شريط القناة في لقطة الهوك: %s", str(exc)[:100])
        return default
    lg = lower_graphics(clip, cfg, deps, detected=bool(ticker), ticker_top=float(cfg.path("reel.render.hook.ticker_crop")),
                        key=video_id, channel=channel, notes=notes)
    if crops is not None:
        crops["hook"] = {"ticker": bool(ticker), **({"lower_graphics": lg} if lg["source"] != "none" else {})}
    if lg["top"] >= 1:
        return default
    ch = round(sh * lg["top"])
    cw = round(ch * 9 / 16)
    return f"crop={cw}:{ch}:{(sw - cw) // 2}:0"


def _hook_scene(i: int, scene: dict, script: dict, draft: dict, bg: dict | None, voice: str, cfg, deps: Deps, tmp: Path,
                out: Path, notes: list, crops: dict | None = None, hook_info: dict | None = None) -> float:
    """مشهد الهوك (P1a، Issue #1600). S = hook.strong_seconds: [0، loop.fog_out] الضباب يزول، [fog_out، S] لقطة نظيفة والشعار الكبير
    وحده (صوت اللقطة الأصلي بمستوى ambient_clean)، [S، S + fog_in] الضباب يظهر، والراوي يبدأ عند S + voice_delay (وينخفض الصوت الأصلي
    إلى ambient) والعنوان ينزل كلمة كلمة تحت الشعار الكبير بتزامن كلامه. الخلفية بالأولوية: (أ) hook_video اليدوي/الآلي يُقتطع 9:16
    ويُثبَّت آخر إطاره (tpad) إن قصر عن المدة لأن قفزة stream_loop تظهر تحت الضباب (ب) صورة reel_bg المتحركة (ج) الكحلي الثابت.
    فشل تنزيل hook_video لا يفشل التركيب: سطر في التعليق وتنتقل الخلفية إلى (ب). المدة = S + voice_delay + الكلام + tail بحدّ أقصى
    hook.max_seconds وبلا حدّ أدنى. hook_info (اختياري) يُملأ بما استعمله المشهد فعلًا (mode: clip|image|navy مع ملف اللقطة وتعبير
    اقتطاعها أو صورة الخلفية وx0) كي يبني مشهد الختام آخر إطاره على أول إطار هنا (Issue #1602)."""
    rcfg, hk = cfg.path("reel.render"), cfg.path("reel.render.hook")
    w, h, fps = int(rcfg["width"]), int(rcfg["height"]), rcfg["fps"]
    title = script.get("title") or scene.get("text", "")
    audio, parts = _speech(title, voice, cfg, deps, tmp, f"s{i:02d}")
    speech = sum(d for _, d in parts)
    strong, delay = float(hk["strong_seconds"]), float(hk["voice_delay"])
    seconds = min(strong + delay + speech + float(hk["tail"]), float(hk["max_seconds"]))
    clip = None
    hv = draft.get("hook_video")
    if isinstance(hv, dict) and hv.get("video_id"):
        try:
            clip = _download_with_retries(deps, rcfg, str(hv["video_id"]), int(hv["start"]), int(hv["end"]),
                                          tmp / "hook_clip.mp4")
        except Exception as exc:  # noqa: BLE001 -- فيديو الهوك تحسين: الخلفية تنتقل إلى الصورة
            log.warning("تعذّر تنزيل فيديو الهوك: %s", reel_clips.scrub_text(str(exc))[:120])
        if clip is None:
            notes.append(cfg.path("reel.render.texts.comment_hook_video_failed"))
    cexpr = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0"
    if clip is not None:
        cexpr = _hook_crop(clip, cfg, deps, crops, video_id=hv.get("video_id"), channel=hv.get("channel", ""), notes=notes)
    # العنوان تحت الشعار الكبير مباشرة: أسفل الشعار + text_gap
    oc, ratio = cfg.path("reel.render.outro"), _logo_ratio(cfg)
    text_top = int(oc["logo_top"]) + (round(int(oc["logo_width"]) * ratio) if ratio is not None else 0) + int(hk["text_gap"])
    times = narration_word_times(parts, strong + delay, cfg)
    if len(times) != len(title.split()):
        # التشكيل/الأسماء قد تغيّر عدد الكلمات: يوزَّع الزمن على كلمات العنوان المعروض بالحروف على مدة الكلام كله
        times = narration_word_times([(title, speech)], strong + delay, cfg)
    frames = word_drop_frames(cfg, title, times, seconds, text_top, tmp, f"hw{i}")
    lst = tmp / f"hook_{i}_words.txt"
    lst.write_text("".join(f"file '{f}'\nduration {_fmt(d)}\n" for f, d in frames) + f"file '{frames[-1][0]}'\n", encoding="utf-8")
    fog_png = _save(fog_layer(cfg), tmp / f"hook_fog_{i}.png")
    rate = rcfg.get("audio_rate", 48000)
    adelay = f"adelay={int(round((strong + delay) * 1000))}:all=1"
    loop = ["-loop", "1", "-framerate", str(fps)]
    fog_in = [*loop, "-i", str(fog_png), "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(audio)]
    # الضباب: ألفا الطبقة تُستخرج وتُصغَّر ثم geq بالزمن T (تعبير fog_alpha نفسه) ثم تُكبَّر وتُدمج ثانيةً بالألوان — geq على نسخة
    # مصغَّرة لأن القناع ناعم (تمويه 170) فلا يظهر فقدان الدقة، وعلى الدقة الكاملة يبطئ التركيب كثيرًا
    expr = _fog_alpha_expr(cfg, strong, var="T")
    fog_f = (f"[1:v]format=rgba,split[fa][fb];[fa]alphaextract,scale={w // 8}:{h // 8},format=gray,"
             f"geq=lum='lum(X,Y)*{expr}',scale={w}:{h},format=gray[fm];[fb][fm]alphamerge[fog];"
             f"[b][fog]overlay=0:0:shortest=1[bf];[2:v]fps={fps},format=rgba[t];[bf][t]overlay=0:0:shortest=1,format=yuv420p[v]")
    sp = f"aresample={rate},aformat=channel_layouts=stereo,{adelay},apad"
    if clip is not None:
        if hook_info is not None:
            hook_info.update(mode="clip", clip=clip, cexpr=cexpr)
        inputs = ["-i", str(clip), *fog_in]
        vg = (f"[0:v]{cexpr},scale={w}:{h},tpad=stop_mode=clone:stop_duration={_fmt(seconds)},fps={fps}[b];" + fog_f)
        vol = f"if(lt(t,{_fmt(strong + delay)}),{_fmt(float(hk['ambient_clean']))},{_fmt(float(hk['ambient']))})"
        ag = (f"[0:a]aresample={rate},aformat=channel_layouts=stereo,volume='{vol}':eval=frame[am];"
              f"[3:a]{sp}[sp];[sp][am]amix=inputs=2:normalize=0:duration=first[a]")
    elif bg is not None:
        wide, wcx = _wide_of(bg)
        plan = pan_plan(cfg, "hook", wide.size[0], wide.size[1], seconds, wcx)
        bgpng = _pan_background(wide, plan, tmp, f"hook_bg_{i}.png")
        if hook_info is not None:
            hook_info.update(mode="image", bgpng=bgpng, x0=plan["x0"])
        inputs = ["-i", str(bgpng), *fog_in]
        vg = (f"{_still_bg_prefix(fps)}crop={w}:{h}:x='{_pan_x_expr(plan['x0'], plan['speed'])}':y='(ih-oh)/2',fps={fps}[b];" + fog_f)
        ag = f"[3:a]{sp}[a]"
    else:
        if hook_info is not None:
            hook_info.update(mode="navy")
        r, g, bl = imaging.hex_rgb(cfg.path("brand.primary_color"))
        inputs = ["-f", "lavfi", "-i", f"color=c=0x{r:02X}{g:02X}{bl:02X}:s={w}x{h}:r={fps}", *fog_in]
        vg = f"[0:v]fps={fps}[b];" + fog_f
        ag = f"[3:a]{sp}[a]"
    deps.run(_base(*inputs, "-filter_complex", vg + ";" + ag, "-map", "[v]", "-map", "[a]", "-t", _fmt(seconds),
                   *_enc(rcfg), str(out)))
    return seconds


def closing_uses_pre(entries: list | None, ws: int, we: int, cfg) -> tuple[bool, float]:
    """هل تصلح ثواني [ws، we) خلفيةً للختام؟ (Issue #1621، R6) دالة خالصة. تصلح فقط إن كانت مصنَّفة في مسح الهوك و event_footage في
    ≥ closing.pre_footage_ratio منها؛ غير المصنَّفة تُحسب غير لقطات، وبلا تصنيف (هوك يدوي) ← لا. تعيد (الصلاحية، النسبة): الثواني
    التي تسبق الهوك قد تكون مقدّمة مذيعة فيظهر وجهها تحت ضباب «برأيك»."""
    n = int(we) - int(ws)
    if not entries or n <= 0:
        return False, 0.0
    kinds = {int(e["sec"]): e.get("kind") for e in entries}
    ratio = sum(1 for sec in range(int(ws), int(we)) if kinds.get(sec) == "event_footage") / n
    return ratio >= float(cfg.path("reel.render.closing.pre_footage_ratio", 0.8)), ratio


def _pre_hook_entries(draft: dict, state) -> list | None:
    """ثواني فيديو الهوك المصنَّفة قبل بدايته ({sec, kind}) من مسح هذا التركيب؛ هوك يدوي أو بلا تصنيف ← None (الختام يجمّد)."""
    hv = draft.get("hook_video")
    if not isinstance(hv, dict) or hv.get("source") in (None, "", "manual") or hv.get("start") is None:
        return None
    classified = (getattr(state, "classified", None) or {}).get(hv.get("video_id")) or {}
    start = int(hv["start"])
    out = []
    for t, e in classified.items():
        for k in range(max(int(e.get("step") or 1), 1)):
            if int(t) + k < start:
                out.append({"sec": int(t) + k, "kind": e.get("kind")})
    return out or None


def _closing_scene(i: int, scene: dict, channels: str, credit: str, hook_info: dict, draft: dict, voice: str, cfg, deps: Deps,
                   tmp: Path, out: Path, notes: list, crops: dict | None, lead: float) -> float:
    """مشهد الختام الموحَّد (Issue #1602، P1a-2) بدل question+outro. الراوي يقرأ السؤال (بلا واو العطف) عند plan[voice] والسؤال تحت
    «برأيك..» ينزل كلمة كلمة ويختفي عند plan[logo]؛ الشعار ينزل من الزاوية (التمريرة الأخيرة) ثم تظهر المعلومات تحته وتختفي.
    الخلفية بالأولوية: (أ) pre_hook: النافذة [start − total، start] من فيديو الهوك نفسه مكتومة فآخر إطار هنا هو ما يسبق أول إطار
    من الهوك مباشرة (ب) freeze: أول إطار من الهوك (لقطته أو صورته عند بدء حركتها) يقترب من closing.freeze_zoom إلى 1.0 عند آخر
    إطار (ج) الكحلي الثابت بلا هوك. الضباب ينتهي بقيمة loop.fog_start فيطابق آخر إطار أول إطار. يعيد مدة المشهد."""
    rcfg, cl = cfg.path("reel.render"), cfg.path("reel.render.closing")
    w, h, fps = int(rcfg["width"]), int(rcfg["height"]), rcfg["fps"]
    text = closing_question_text(scene.get("text", ""), cfg)
    # Q5: «برأيك» تُقرأ أولًا ثم وقفة label_pause ثم السؤال؛ صوتاهما يُوصلان بصمت الوقفة في ملف واحد يبدأ عند plan[voice]
    label_text = str(cfg.path("reel.texts.closing_label") or "").strip(" .…")
    label_audio, lab_s = None, 0.0
    if label_text:
        label_audio, lparts = _speech(label_text, voice, cfg, deps, tmp, f"s{i:02d}l")
        lab_s = sum(d for _, d in lparts)
    audio, parts = _speech(text, voice, cfg, deps, tmp, f"s{i:02d}")
    q = sum(d for _, d in parts)
    plan = closing_plan(q, cfg, lead, label_seconds=lab_s)
    if label_audio is not None:
        joined = tmp / f"closing_{i}_voice.wav"
        deps.run(_base("-i", str(label_audio), "-f", "lavfi", "-t", _fmt(float(cl["label_pause"])), "-i",
                       f"anullsrc=r={rcfg.get('audio_rate', 48000)}:cl=stereo", "-i", str(audio), "-filter_complex",
                       "[0:a][1:a][2:a]concat=n=3:v=0:a=1[a]", "-map", "[a]", str(joined)))
        audio = joined
    total = plan["total"]
    times = narration_word_times(parts, plan["question"], cfg)
    if len(times) != len(text.split()):
        # التشكيل قد يغيّر عدد الكلمات: يوزَّع الزمن على كلمات السؤال المعروض بالحروف على مدة الكلام كله
        times = narration_word_times([(text, q)], plan["question"], cfg)
    qframes = closing_text_frames(cfg, text, times, total, tmp, f"cq{i}", label_at=plan["voice"] if label_text else None)
    lst = tmp / f"closing_{i}_words.txt"
    lst.write_text("".join(f"file '{f}'\nduration {_fmt(d)}\n" for f, d in qframes) + f"file '{qframes[-1][0]}'\n", encoding="utf-8")
    info_png = _save(frame_outro(cfg, channels, credit=credit, transparent=True), tmp / f"closing_info_{i}.png")
    fog_png = _save(fog_layer(cfg), tmp / f"closing_fog_{i}.png")
    mode, hv = hook_info.get("mode"), draft.get("hook_video")
    pre, ws, we, pre_ratio = None, 0, 0, None
    use_pre = False
    if mode == "clip" and isinstance(hv, dict) and hv.get("video_id") and hv.get("start") is not None and int(hv["start"]) >= total:
        ws, we = int(math.floor(int(hv["start"]) - total)), int(hv["start"])
        use_pre, pre_ratio = closing_uses_pre(hook_info.get("pre_entries"), ws, we, cfg)
        if not use_pre:
            log.info("نافذة ما قبل الهوك ليست لقطات حدث (%.0f%%) فيُجمَّد أول إطار", pre_ratio * 100)
    if use_pre:
        try:
            pre = _download_with_retries(deps, rcfg, str(hv["video_id"]), ws, we, tmp / f"closing_pre_{i}.mp4")
        except Exception as exc:  # noqa: BLE001 -- النافذة تحسين: يرجع الختام إلى التجميد
            log.warning("تعذّر تنزيل نافذة ما قبل الهوك: %s", reel_clips.scrub_text(str(exc))[:120])
    zf, tz = _fmt(float(cl["freeze_zoom"])), _fmt(total)
    # التكبير الزمني: 1.10 عند البداية و1.0 تمامًا عند آخر إطار (scale بتقييم كل إطار ثم اقتطاع مركزي بمقاس الشاشة)
    zexpr = f"max(1,1+({zf}-1)*(1-t/{tz}))"
    zoom = f"scale=w='trunc({w}*{zexpr}/2)*2':h='trunc({h}*{zexpr}/2)*2':eval=frame:flags=bilinear,crop={w}:{h}"
    if pre is not None:
        src = "pre_hook"
        # قصّ الهوك الفعلي نفسه بلا كشف ثانٍ لشريط القناة: كشف جديد قد يختلف فتظهر قفزة عند الإعادة المتصلة (P1b)
        dur = float(deps.probe(pre) or (we - ws))
        inputs = ["-i", str(pre)]
        base = (f"[0:v]trim=start={_fmt(max(dur - total, 0.0))},setpts=PTS-STARTPTS,{hook_info['cexpr']},"
                f"scale={w}:{h},tpad=stop_mode=clone:stop_duration={tz},fps={fps}[b]")
    elif mode == "clip":
        src = "freeze"
        inputs = ["-i", str(hook_info["clip"])]
        base = (f"[0:v]{hook_info['cexpr']},scale={w}:{h},trim=end_frame=1,setpts=PTS-STARTPTS,loop=loop=-1:size=1:start=0,"
                f"setpts=N/{fps}/TB,fps={fps},{zoom}[b]")
    elif mode == "image":
        src = "freeze"
        inputs = ["-i", str(hook_info["bgpng"])]
        base = f"{_still_bg_prefix(fps)}crop={w}:{h}:x={_fmt(hook_info['x0'])}:y='(ih-oh)/2',fps={fps},{zoom}[b]"
    else:
        src = "navy"
        r, g, bl = imaging.hex_rgb(cfg.path("brand.primary_color"))
        inputs = ["-f", "lavfi", "-i", f"color=c=0x{r:02X}{g:02X}{bl:02X}:s={w}x{h}:r={fps}"]
        base = f"[0:v]fps={fps}[b]"
    if crops is not None:
        crops["closing"] = {"source": src, **({"pre_footage": round(pre_ratio, 3)} if pre_ratio is not None else {})}
    if src == "freeze":
        notes.append(cfg.path("reel.render.texts.comment_closing_freeze"))
    expr = _closing_fog_expr(cfg, plan, var="T")
    vg = (base + ";"
          f"[1:v]format=rgba,split[fa][fb];[fa]alphaextract,scale={w // 8}:{h // 8},format=gray,"
          f"geq=lum='lum(X,Y)*{expr}',scale={w}:{h},format=gray[fm];[fb][fm]alphamerge[fog];[b][fog]overlay=0:0:shortest=1[bf];"
          f"[2:v]fps={fps},format=rgba,fade=t=out:st={_fmt(plan['logo'])}:d={_fmt(float(cl['question_fade']))}:alpha=1[t];"
          f"[4:v]fps={fps},format=rgba,fade=t=in:st={_fmt(plan['info_in'])}:d={_fmt(float(cl['info_in']))}:alpha=1,"
          f"fade=t=out:st={_fmt(plan['info_out'])}:d={_fmt(float(cl['info_out']))}:alpha=1[inf];"
          f"[bf][t]overlay=0:0:shortest=1[v1];[v1][inf]overlay=0:0:shortest=1,format=yuv420p[v]")
    rate = rcfg.get("audio_rate", 48000)
    ag = f"[3:a]aresample={rate},aformat=channel_layouts=stereo,adelay={int(round(plan['voice'] * 1000))}:all=1,apad[a]"
    loop = ["-loop", "1", "-framerate", str(fps)]
    deps.run(_base(*inputs, *loop, "-i", str(fog_png), "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(audio),
                   *loop, "-i", str(info_png), "-filter_complex", vg + ";" + ag, "-map", "[v]", "-map", "[a]", "-t", _fmt(total),
                   *_enc(rcfg), str(out)))
    return total


def _qcard_scene(i: int, scene: dict, audio: Path, parts: list, out: Path, cfg, deps: Deps, tmp: Path, lead: float,
                 nar_bg: Path | None = None, nar_plan: dict | None = None, bg_start: float = 0.0,
                 broll: list | None = None) -> float:
    """بطاقة السؤال (Issue #1613، P2b): مشهد الراوي ذو role=question. كلمات السؤال تنزل كلمة كلمة بتزامن صوت الراوي (يتأخر بـlead)
    عند qcard.text_top فوق خلفية الراوي نفسها: الصورة المتحركة من حيث انتهى ما قبلها (bg_start) ثم لقطات الحدث ثم الضباب الكحلي
    بدل التظليل، في أمر ffmpeg واحد. بلا خلفية: الكحلي الثابت والنص فوقه بلا ضباب. المدة = الكلام + qcard.tail + lead؛ آخر إطار
    يبقى حتى نهاية المشهد كي يستقر السؤال لحظة قبل الإجابات."""
    rcfg, qc = cfg.path("reel.render"), cfg.path("reel.render.qcard")
    w, h, fps = int(rcfg["width"]), int(rcfg["height"]), rcfg["fps"]
    text = scene.get("text", "")
    speech = sum(d for _, d in parts)
    seconds = scene_seconds(speech, float(qc["tail"]), lead)
    times = narration_word_times(parts, lead, cfg)
    if len(times) != len(text.split()):
        # التشكيل قد يغيّر عدد الكلمات: يوزَّع الزمن على كلمات السؤال المعروض بالحروف على مدة الكلام كله
        times = narration_word_times([(text, speech)], lead, cfg)
    frames = word_drop_frames(cfg, text, times, seconds, int(qc["text_top"]), tmp, f"qc{i}", size_key="question")
    lst = tmp / f"qcard_{i}_words.txt"
    lst.write_text("".join(f"file '{f}'\nduration {_fmt(d)}\n" for f, d in frames) + f"file '{frames[-1][0]}'\n", encoding="utf-8")
    afilter = f"adelay={int(round(lead * 1000))}:all=1,apad" if lead > 0 else "apad"
    if nar_bg is None or nar_plan is None:
        r, g, bl = imaging.hex_rgb(cfg.path("brand.primary_color"))
        vg = f"[0:v]fps={fps}[b];[1:v]fps={fps},format=rgba[t];[b][t]overlay=0:0:shortest=1,format=yuv420p[v];[2:a]{afilter}[a]"
        deps.run(_base("-f", "lavfi", "-i", f"color=c=0x{r:02X}{g:02X}{bl:02X}:s={w}x{h}:r={fps}",
                       "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(audio), "-filter_complex", vg,
                       "-map", "[v]", "-map", "[a]", "-t", _fmt(seconds), *_enc(rcfg), str(out)))
        return seconds
    pan = _pan_x_expr(nar_plan["x0"], nar_plan["speed"], bg_start)
    vg = f"{_still_bg_prefix(fps)}crop={w}:{h}:x='{pan}':y='(ih-oh)/2'"
    extra: list[str] = []
    cur = "[p0]"
    vg += "[p0];"
    for j, bl in enumerate(broll or []):
        extra += ["-i", str(bl["clip"])]
        a, b = _fmt(bl["a"]), _fmt(bl["b"])
        vg += (f"[{3 + j}:v]{bl['cexpr']},scale={w}:{h},fps={fps},setpts=PTS-STARTPTS+{a}/TB[c{j}];"
               f"{cur}[c{j}]overlay=0:0:enable='between(t,{a},{b})'[p{j + 1}];")
        cur = f"[p{j + 1}]"
    fog_i = 3 + len(broll or [])
    # الضباب: سلسلة P1a نفسها (ألفا الطبقة تُستخرج وتُصغَّر ÷8 ثم geq بالزمن T ثم تُكبَّر وتُدمج ثانيةً بالألوان)
    vg += (f"[{fog_i}:v]format=rgba,split[fa][fb];[fa]alphaextract,scale={w // 8}:{h // 8},format=gray,"
           f"geq=lum='lum(X,Y)*{_qcard_fog_expr(cfg, lead, var='T')}',scale={w}:{h},format=gray[fm];[fb][fm]alphamerge[fog];"
           f"{cur}fps={fps}[bb];[bb][fog]overlay=0:0:shortest=1[bf];"
           f"[1:v]fps={fps},format=rgba[t];[bf][t]overlay=0:0:shortest=1,format=yuv420p[v];[2:a]{afilter}[a]")
    fog_png = _save(fog_layer(cfg), tmp / f"qcard_fog_{i}.png")
    deps.run(_base("-i", str(nar_bg), "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(audio), *extra,
                   "-loop", "1", "-framerate", str(fps), "-i", str(fog_png), "-filter_complex", vg,
                   "-map", "[v]", "-map", "[a]", "-t", _fmt(seconds), *_enc(rcfg), str(out)))
    return seconds


def _clip_layers(i: int, scene: dict, clip: dict, cfg, deps: Deps, tmp: Path, speakers: dict, notes: list,
                 cover: bool | None = None) -> tuple[tuple[Path, Path], list | None]:
    """طبقتا المقطع (الثابتة والشريط) وتيار حالات الترجمة: اسم المتحدث المقروء من الشاشة يغيّر نص الشريط نفسه فيُطبَّق قبل رسمه،
    والترجمة كلمةً كلمة بتزامن كلامه (Issue #1592، R5h): النص المجلوب إن وُجد وإلا توزيع متساوٍ. مستخرجة من _assemble لتشترك فيها
    المشاهد الكاملة ولوحة الإجابات (P2c-1)؛ cover=False في اللوحة لأن الإطار لا يبلغ أسفل الشاشة فلا غطاء كحلي."""
    _apply_chyron(scene, clip, cfg, deps, speakers, notes, i)
    # Q6 (Issue #1660): النص المنطوق/المترجم لفكرة المقطع (display_text) يحلّ محل quote_arabic في المشهد المركَّب وحده
    qtext = (clip.get("display_text") or scene.get("quote_arabic") or "").strip()
    qframes = None
    if qtext:
        segs = clip.get("segs") or []
        times = quote_word_times(len(qtext.split()), clip["seconds"], segs, clip.get("wstart", 0.0), cfg)
        # Q4 (Issue #1654): كلام غير عربي تنزل ترجمته سطرًا كاملًا لا كلمة كلمة (قرار صاحب المشروع)؛ العربي كما كان.
        # Q6: لغة الصوت من النص المجلوب إن عُرفت (الصوت المدبلج عربي وإن كانت النقطة من غيره)
        lang = (clip.get("span") or {}).get("lang") or scene.get("language")
        mode = "line" if str(lang or "ar").lower() not in ("ar", "ara", "arabic", "") else "word"
        qframes = quote_frames(cfg, qtext, times, clip["seconds"], tmp, f"quote_{i}", mode)
        clip["quote_mode"] = mode
        clip["quote_sync"] = "transcript" if segs else "uniform"
    static, band = (frame_clip_layers(cfg, scene, quote=qframes is None) if cover is None
                    else frame_clip_layers(cfg, scene, cover=cover, quote=qframes is None))
    return (_save(static, tmp / f"overlay_{i}_static.png"), _save(band, tmp / f"overlay_{i}_band.png")), qframes


def _panel_crops(clip: dict, crop: dict, scene: dict, q, tile: tuple | None, frame: tuple, cfg, deps: Deps, notes: list) -> tuple:
    """قصّ المقطع لبلاطته وإطاره البارز (P2c-1): يكشف الأشرطة السوداء (content_box على لقطات deps.frames) وشريط الأخبار الأصلي
    (has_bottom_graphics على اللقطات مقصوصةً إلى المحتوى، فيُقصّ ارتفاع الصورة إلى panel.ticker_crop من أعلاها) ثم fit_crop لكل مقاس بمركز نافذة المتكلم
    الحالية. تعذّر قراءة أبعاد المصدر ← تعبير ffmpeg بالارتفاع الكامل متمركزًا بلا حفظ نوافذ. يملأ clip["crop"] بما يُراجَع
    ويضيف سطري التعليق (أشرطة أُزيلت، مصدر ضيق). يعيد (تعبير قصّ البلاطة أو None، تعبير قصّ الإطار)."""
    pc = cfg.path("reel.render.panel")
    channel = scene.get("channel_display", "")
    t = cfg.path("reel.render.texts")

    def fallback(bw, bh):
        return f"crop=ih*{bw}/{bh}:ih:(iw-ih*{bw}/{bh})/2:0"
    try:
        samples = list((cfg.path("reel.render.crop") or {}).get("samples", [0.2, 0.5, 0.8]))
        sw, sh, _ = deps.faces(clip["file"], samples)
        sw, sh = int(sw), int(sh)
        if sw <= 0 or sh <= 0:
            raise ValueError("أبعاد المصدر مجهولة")
        n = max(1, int(pc["bars"]["samples"]))
        frames = deps.frames(clip["file"], [(k + 0.5) / n for k in range(n)])
        bx, by, bw, bh = content_box(frames, cfg)
        bxs, bys, bws, bhs = bx, by, bw, bh
        fh_, fw_ = frames[0].shape
        sx, sy = sw / fw_, sh / fh_
        content = (round(bx * sx), round(by * sy), round(bw * sx), round(bh * sy))
        if content[2] <= 0 or content[3] <= 0:
            content = (0, 0, sw, sh)
        bars = [content[1], sh - content[1] - content[3], content[0], sw - content[0] - content[2]]
        # الكشف على اللقطات نفسها مقصوصةً إلى content لا على الإطار كاملًا: حدّ الشريط الأسود السفلي حافة أفقية ثابتة في كل اللقطات
        # فكان يُقرأ شريط أخبار ويُقصّ 20% من صورة سليمة؛ ولا استخراج ثانٍ
        ticker = bool(has_bottom_graphics([f[bys:bys + bhs, bxs:bxs + bws] for f in frames], 0, bws, cfg))
        # Q3: بداية رسوم القناة بحكم نموذج يرى اللقطات (نسبة من الارتفاع الكامل) فتُقصّ ما تحتها من المحتوى؛ الكاشف وحده (بلا نموذج) يبقى
        # بصيغته القديمة نسبةً من المحتوى. نداء واحد لكل فيديو مهما تعددت مقاطعه
        lg = lower_graphics(clip["file"], cfg, deps, detected=ticker, ticker_top=float(pc["ticker_crop"]), key=clip.get("video_id"),
                            channel=channel, notes=notes)
        if lg["top"] < 1:
            if lg["source"] == "detector":
                content = (content[0], content[1], content[2], round(content[3] * lg["top"]))
            else:
                content = (content[0], content[1], content[2], max(min(content[3], round(lg["top"] * sh) - content[1]), 2))
        cx = crop["x"] + crop["w"] / 2 if crop.get("x") is not None and crop.get("w") else None
        tile_crop = fit_crop(sw, sh, content, tile[2], tile[3], cx, cfg) if tile else None
        frame_crop = fit_crop(sw, sh, content, frame[2], frame[3], cx, cfg)
    except Exception as exc:  # noqa: BLE001 -- القصّ المحسوب تحسين لا شرط
        log.warning("تعذّر حساب قصّ اللوحة فالارتفاع الكامل المتمركز: %s", str(exc)[:100])
        clip["crop"].update(panel_q=q, tile_crop=None, frame_crop=None, bars=[0, 0, 0, 0], ticker=False)
        return (fallback(tile[2], tile[3]) if tile else None), fallback(frame[2], frame[3])
    clip["crop"].update(panel_q=q, tile_crop=tile_crop, frame_crop=frame_crop, bars=bars, ticker=ticker)
    if lg["source"] != "none":
        clip["crop"]["lower_graphics"] = lg
    if any(bars):
        notes.append(t["comment_bars"].format(channel=channel))
    if frame_crop["mode"] == "fill_width":
        notes.append(t["comment_vertical"].format(channel=channel))

    def expr(c):
        return f"crop={c['w']}:{c['h']}:{c['x']}:{c['y']}"
    return (expr(tile_crop) if tile_crop else None), expr(frame_crop)


def _panel_scene(members: list[tuple[int, dict]], clips: dict, out: Path, cfg, deps: Deps, tmp: Path, speakers: dict, notes: list,
                 nar_bg: Path | None = None, nar_plan: dict | None = None, bg_start: float = 0.0) -> float:
    """لوحة إجابات السؤال (Issue #1615، P2c-1): مقاطع السؤال الواحد في سيناريو v2 مشهد واحد بأمر ffmpeg واحد. البلاطات (n ≥ 2) تتحرك
    كلها صامتة طوال اللوحة (-stream_loop) تحت تظليل كحلي panel.grid_dim، والإجابة النشطة وحدها في الإطار البارز الثابت بصوتها: مدخل
    ثانٍ لمقطعها بلا تكرار يبدأ عند a_k ويُركَّب بـbetween(t,a_k,b_k). n = 1 بلا بلاطات: خلفية الراوي المتحركة من حيث انتهت بطاقة
    السؤال (bg_start) تحت الضباب الكحلي، وبلاها كحلي ثابت. طبقات العضو k (الشريط الثابت، ثم الترجمة، ثم الشريط المنزلق) مزاحة بـa_k
    ومحصورة في [a_k, b_k]؛ انزلاق الأول بعد الانتقال وما بعده من a_k مباشرة. الصوت صوت العضو k وحده في مجاله ثم concat.
    n ≥ 2 (Issue #1618، P2c-2): تبدأ اللوحة بـpanel.intro صامتة وعلى كل بلاطة اسم قناتها، ثم تنبثق بلاطة كل إجابة (تكبر إلى الإطار
    البارز ثم تعود) وطبقاتها الثلاث محصورة بين انتهاء الكبر وبدء العودة؛ المدة = intro + مجموع مدد المقاطع. n = 1 بلا تغيير."""
    rcfg = cfg.path("reel.render")
    W, H, fps = int(rcfg["width"]), int(rcfg["height"]), rcfg["fps"]
    lead = transition_seconds(cfg)
    n = len(members)
    lay = panel_layout(n, cfg)
    fx, fy, fw, fh = lay["frame"]
    inputs: list[str] = []
    count = 0

    def add(*args) -> int:
        nonlocal count
        inputs.extend(args)
        count += 1
        return count - 1
    pop = n >= 2
    # لوحة n ≥ 2 تبدأ بـintro صامتة تُعرَّف فيها القنوات على البلاطات قبل أي كلام؛ n = 1 بلا مقدمة فتبقى حرفًا كما كانت
    intro = float(cfg.path("reel.render.panel.intro")) if pop else 0.0
    grow = float(cfg.path("reel.render.panel.pop.grow")) if pop else 0.0
    shrink = float(cfg.path("reel.render.panel.pop.shrink")) if pop else 0.0
    starts, acc = [], intro
    for i, _ in members:
        starts.append(acc)
        acc += float(clips[i]["seconds"])
    total = acc
    r, g, b = imaging.hex_rgb(cfg.path("brand.primary_color"))
    navy = f"0x{r:02X}{g:02X}{b:02X}"
    prepared = []
    for k, (i, scene) in enumerate(members):
        clip = clips[i]
        crop = _prepare_crop(clip, cfg, deps, scene, notes)
        tile_expr, frame_expr = _panel_crops(clip, crop, scene, scene.get("q"), lay["tiles"][k] if n >= 2 else None, lay["frame"],
                                             cfg, deps, notes)
        overlays, qframes = _clip_layers(i, scene, clip, cfg, deps, tmp, speakers, notes, cover=False)
        # Q5: _prepare_crop بنى السجل قبل أن يضبط _clip_layers وضع الترجمة وتزامنها، فتُكتبان فيه الآن
        for key in ("quote_sync", "quote_mode"):
            if clip.get(key) and isinstance(clip.get("crop"), dict):
                clip["crop"][key] = clip[key]
        prepared.append((tile_expr, frame_expr, overlays, qframes))
    vg: list[str] = []
    if n >= 2:
        add("-f", "lavfi", "-i", f"color=c={navy}:s={W}x{H}:r={fps}")
        vg.append(f"[0:v]fps={fps}[b0]")
        for k, (i, _) in enumerate(members):
            ti = add("-stream_loop", "-1", "-i", str(clips[i]["file"]))
            tx, ty, tw, th = lay["tiles"][k]
            vg.append(f"[{ti}:v]{prepared[k][0]},scale={tw}:{th},fps={fps},setpts=PTS-STARTPTS[t{k}];"
                      f"[b{k}][t{k}]overlay={tx}:{ty}[b{k + 1}]")
        vg.append(f"[b{n}]drawbox=x=0:y=0:w=iw:h=ih:color={navy}@{_fmt(float(cfg.path('reel.render.panel.grid_dim')))}:t=fill[bdim]")
        # أسماء القنوات بعد تظليل الشبكة وقبل الإطارات، وتبقى حتى ينتهي أول كبر (intro + grow)
        labels_png = _save(frame_tile_labels(cfg, lay["tiles"], [sc for _, sc in members]), tmp / f"panel_labels_{members[0][0]}.png")
        li = add("-loop", "1", "-framerate", str(fps), "-i", str(labels_png))
        lbl_en = f"enable='between(t,0,{_fmt(intro + grow)})'"
        vg.append(f"[{li}:v]fps={fps},format=rgba[lbl];[bdim][lbl]overlay=0:0:{lbl_en}[base]")
    elif nar_bg is not None and nar_plan is not None:
        add("-i", str(nar_bg))
        pan = _pan_x_expr(nar_plan["x0"], nar_plan["speed"], bg_start)
        fog = add("-loop", "1", "-framerate", str(fps), "-i", str(_save(fog_layer(cfg), tmp / f"panel_fog_{members[0][0]}.png")))
        vg.append(f"{_still_bg_prefix(fps)}crop={W}:{H}:x='{pan}':y='(ih-oh)/2'[p0];"
                  f"[p0]fps={fps}[bb];[{fog}:v]format=rgba[fg];[bb][fg]overlay=0:0[base]")
    else:
        add("-f", "lavfi", "-i", f"color=c={navy}:s={W}x{H}:r={fps}")
        vg.append(f"[0:v]fps={fps}[base]")
    cur = "base"
    fidx = []
    for k, (i, _) in enumerate(members):
        a, bb = _fmt(starts[k]), _fmt(starts[k] + float(clips[i]["seconds"]))
        fi = add("-i", str(clips[i]["file"]))
        fidx.append(fi)
        if not pop:
            vg.append(f"[{fi}:v]{prepared[k][1]},scale={fw}:{fh},fps={fps},setpts=PTS-STARTPTS+{a}/TB[f{k}];"
                      f"[{cur}][f{k}]overlay={fx}:{fy}:enable='between(t,{a},{bb})'[o{k}]")
            cur = f"o{k}"
            continue
        # الانبثاق: الإطار يكبر من مستطيل بلاطته (pop_start_rect) إلى الإطار البارز بالمعامل k(t) ثم يعود، بتعبير في t لكل إطار
        crop_k = clips[i].get("crop") or {}
        sx, sy, sw, sh = pop_start_rect(lay["tiles"][k], crop_k.get("tile_crop"), crop_k.get("frame_crop"), lay["frame"])
        end_k = starts[k] + float(clips[i]["seconds"])
        kx = _pop_expr(cfg, starts[k], end_k)
        fade = float(cfg.path("reel.render.panel.pop.fade"))
        sw_e = f"trunc(({sw}+({fw}-{sw})*{kx})/2)*2"
        sh_e = f"trunc(({sh}+({fh}-{sh})*{kx})/2)*2"
        vg.append(f"[{fi}:v]{prepared[k][1]},scale={fw}:{fh},fps={fps},setpts=PTS-STARTPTS+{a}/TB,format=rgba,"
                  f"fade=t=in:st={a}:d={_fmt(fade)}:alpha=1,fade=t=out:st={_fmt(end_k - fade)}:d={_fmt(fade)}:alpha=1,"
                  f"scale=w='{sw_e}':h='{sh_e}':eval=frame[f{k}];"
                  f"[{cur}][f{k}]overlay=x='{sx}+({fx}-{sx})*{kx}':y='{sy}+({fy}-{sy})*{kx}':enable='between(t,{a},{bb})'[o{k}]")
        cur = f"o{k}"
    slide = float(rcfg.get("band", {}).get("slide_seconds", 0) or 0)
    for k, (i, _) in enumerate(members):
        a, bb = _fmt(starts[k]), _fmt(starts[k] + float(clips[i]["seconds"]))
        # في الانبثاق لا شريط ولا ترجمة والإطار يتحرك: الطبقات محصورة بين انتهاء الكبر وبدء العودة
        if pop:
            en = f"enable='between(t,{_fmt(starts[k] + grow)},{_fmt(starts[k] + float(clips[i]['seconds']) - shrink)})'"
        else:
            en = f"enable='between(t,{a},{bb})'"
        static_png, band_png = prepared[k][2]
        qframes = prepared[k][3]
        si = add("-loop", "1", "-framerate", str(fps), "-i", str(static_png))
        vg.append(f"[{si}:v]fps={fps},format=rgba,setpts=PTS-STARTPTS+{a}/TB[s{k}];[{cur}][s{k}]overlay=0:0:{en}[s{k}o]")
        cur = f"s{k}o"
        if qframes:
            lst = out.with_name(f"{out.stem}_quote{k}.txt")
            lst.write_text("".join(f"file '{f}'\nduration {_fmt(d)}\n" for f, d in qframes) + f"file '{qframes[-1][0]}'\n",
                           encoding="utf-8")
            qi = add("-f", "concat", "-safe", "0", "-i", str(lst))
            vg.append(f"[{qi}:v]fps={fps},format=rgba,setpts=PTS-STARTPTS+{a}/TB[q{k}];[{cur}][q{k}]overlay=0:0:{en}[q{k}o]")
            cur = f"q{k}o"
        bi = add("-loop", "1", "-framerate", str(fps), "-i", str(band_png))
        t0 = starts[k] + grow if pop else (lead if k == 0 else starts[k])
        pos = (f"x='W*pow(1-min(max((t-{_fmt(t0)})/{_fmt(slide)},0),1),3)':y=0" if slide > 0 else "0:0")
        vg.append(f"[{bi}:v]fps={fps},format=rgba,setpts=PTS-STARTPTS+{a}/TB[bd{k}];[{cur}][bd{k}]overlay={pos}:{en}[bd{k}o]")
        cur = f"bd{k}o"
    vg.append(f"[{cur}]fps={fps},format=yuv420p[v]")
    rate = rcfg.get("audio_rate", 48000)
    ag = []
    if pop:
        ag.append(f"anullsrc=r={rate}:cl=stereo,atrim=duration={_fmt(intro)},asetpts=PTS-STARTPTS[am_s]")
    for k, (i, _) in enumerate(members):
        sec = _fmt(float(clips[i]["seconds"]))
        ag.append(f"[{fidx[k]}:a]aresample={rate},aformat=channel_layouts=stereo,atrim=duration={sec},asetpts=PTS-STARTPTS,"
                  f"{_gate_filter(clips[i], cfg)}apad=whole_dur={sec}[am{k}]")
    ag.append(("[am_s]" if pop else "") + "".join(f"[am{k}]" for k in range(n)) + f"concat=n={n + (1 if pop else 0)}:v=0:a=1,{_loudnorm(cfg)}[a]")
    deps.run(_base(*inputs, "-filter_complex", ";".join(vg + ag), "-map", "[v]", "-map", "[a]", "-t", _fmt(total),
                   *_enc(rcfg), str(out)))
    return total


def _panel_groups(order: list, script: dict, clips: dict) -> dict[int, list[int]]:
    """مجموعات اللوحات في سيناريو v2: المقاطع المتتالية (kind=clip) ذات q الواحد، مرتبة بترتيب السيناريو، {فهرس أول عضو: فهارس
    الأعضاء}. مقطع لم يُنزَّل (ليس في clips) يُسقط من مجموعته ولوحة لم يبقَ فيها مقطع لا تُركَّب (P2c-1). v1 ← لا مجموعات."""
    if not reel_script.is_v2(script):
        return {}
    groups: dict[int, list[int]] = {}
    for members in _iter_runs(order):
        present = [i for i in members if i in clips]
        if present:
            groups[present[0]] = present
    return groups


def _iter_runs(order: list):
    """مقاطع متتالية ذات q واحد من order (kind=clip وq غير None)."""
    run, last = [], None
    for i, sc in order:
        if sc.get("kind") == "clip" and sc.get("q") is not None:
            if run and sc.get("q") != last:
                yield run
                run = []
            run.append(i)
            last = sc.get("q")
        elif run:
            yield run
            run, last = [], None
    if run:
        yield run


def _question_text(script: dict, first_member: int) -> str:
    """نص بطاقة السؤال الذي تتبعه الإجابات التي أولها هذا الفهرس (للتعليق وسجل المحذوف)."""
    q = script["scenes"][first_member].get("q")
    return next((sc.get("text", "") for sc in script["scenes"] if sc.get("kind") == "narration" and sc.get("role") == "question"
                 and sc.get("q") == q), "")


def _prune_mismatched(script: dict, clips: dict, cfg, deps: Deps, speakers: dict, notes: list,
                      dropped: list) -> tuple[dict, set[int]]:
    """حارس القائل (Issue #1621، R6): في سيناريو v2 يُقرأ شريط كل مقطع في لوحة قبل بنائها؛ مقطع يُظهر شريطه اسمًا غير قائل الاقتباس يُحذف
    (نسبة الكلام إلى غير قائله أسوأ من نقص إجابة)، فتُبنى اللوحة بمن بقي. سؤال سقطت كل إجاباته بهذا الحارس يسقط مشهد بطاقته أيضًا كي لا
    يبقى سؤال بلا جواب. يعيد (نسخة clips بعد الحذف، فهارس مشاهد البطاقات المحذوفة). v1 بلا تغيير."""
    if not reel_script.is_v2(script):
        return clips, set()
    clips = dict(clips)
    t = cfg.path("reel.render.texts")
    order = list(enumerate(script["scenes"]))
    dead_q: dict = {}
    min_answers = int(cfg.path("reel.render.min_answers", 2))
    for members in _iter_runs(order):
        gone = []
        for i in members:
            if i not in clips:
                continue
            mm = _apply_chyron(script["scenes"][i], clips[i], cfg, deps, speakers, notes, i)
            if mm:
                line = t["drop_speaker_mismatch"].format(**mm)
                _drop(dropped, script["scenes"][i], line)
                if line not in notes:
                    notes.append(line)
                clips.pop(i)
                gone.append(i)
        left = [i for i in members if i in clips]
        if gone and not left:
            dead_q[script["scenes"][members[0]].get("q")] = "empty"
        elif left and len(left) < min_answers <= len(members):
            # Q4 (Issue #1654): المطلوب منظوران؛ سؤال فقد إجابة بحارس القائل وبقيت له واحدة يُحذف كله بدل أن يُعرض بمنظور واحد
            for i in left:
                _drop(dropped, script["scenes"][i], t["drop_question_min"].format(text=_question_text(script, members[0])))
                clips.pop(i)
            dead_q[script["scenes"][members[0]].get("q")] = "min"
    dead = set()
    for i, sc in order:
        if sc.get("kind") == "narration" and sc.get("role") == "question" and sc.get("q") in dead_q:
            dead.add(i)
            key = "drop_question_empty" if dead_q[sc.get("q")] == "empty" else "drop_question_min"
            notes.append(t[key].format(text=sc.get("text", "")))
    if dead_q and not any(i in clips for i, sc in order if sc.get("kind") == "clip"):
        raise RuntimeError(t["fail_min_answers"])
    return clips, dead


def _transition_kind(cfg, kind: str) -> str:
    """نوع الانتقال إلى مشهد من هذا النوع: fade (transition.outro_type) للختام بصيغتيه outro وclosing، وغيره transition.type."""
    tcfg = cfg.path("reel.render.transition")
    return tcfg.get("outro_type", "fade") if kind in ("outro", "closing") else tcfg.get("type", "slideleft")


_TASHKEEL = re.compile("[ً-ٰٟـ]")


def _plain(text: str) -> str:
    """نص الجملة للمقارنة بالخطة: بلا تشكيل ولا تطويل وبمسافات موحَّدة."""
    return " ".join(_TASHKEEL.sub("", str(text or "")).split())


def _prepare_broll(script: dict, nar_idx: list[int], speech_cache: dict, plan: list, broll: dict, cfg, deps: Deps, tmp: Path,
                   lead: float, notes: list) -> dict[int, list[dict]]:
    """لقطات الحدث خلف الجمل (Issue #1452، R5d2): تقسم جمل الراوي بمددها الفعلية من تمريرة الصوت الأولى، وتطابق الخطة بالعدد
    ثم بالنص (المراجع قد يعدّل السيناريو في المرحلة 2)، ويسند النموذج، ويقرر المدقّق القطعي، وتُنزَّل النوافذ المقبولة.
    كل جملة لا تنال لقطة تبقى بالصورة المتحركة. يعيد {فهرس المشهد: [{a, b, clip, cexpr}]} ويملأ broll["result"] (render_broll)
    وbroll["channels"] (قنوات اللقطات المركَّبة فعلًا للخاتمة)."""
    t = cfg.path("reel.render.texts")
    rcfg = cfg.path("reel.render")
    reasons = t.get("broll_reasons", {})
    result: list[dict] = broll.setdefault("result", [])
    broll["channels"] = []
    by_scene: dict[int, dict[int, dict]] = {}
    for e in plan:
        try:
            by_scene.setdefault(int(e["scene"]), {})[int(e["sentence"])] = e
        except (TypeError, ValueError, KeyError):
            continue
    recs: list[dict] = []
    text_changed = False
    n = 0
    for i in nar_idx:
        parts = speech_cache[i][1]
        texts = tts.split_sentences(script["scenes"][i].get("text", ""))
        entries = by_scene.get(i, {})
        count_ok = len(entries) == len(parts) == len(texts)
        if not count_ok:
            notes.append(t["comment_broll_count"].format(scene=i))
        cursor = 0.0
        for k, (_, dur) in enumerate(parts):
            n += 1
            a = 0.0 if k == 0 else lead + cursor
            cursor += dur
            rec = {"n": n, "scene": i, "sentence": k, "a": a, "b": lead + cursor, "visual": "", "text": texts[k] if k < len(texts) else "",
                   "reason": None}
            e = entries.get(k)
            if not count_ok:
                rec["reason"] = "count"
            elif e is None or _plain(e.get("text")) != _plain(rec["text"]):
                rec["reason"] = "text"
                text_changed = True
            else:
                rec["visual"] = str(e.get("visual") or "").strip()
                if not rec["visual"]:
                    rec["reason"] = "no_visual"
            recs.append(rec)
    if text_changed:
        notes.append(t["comment_broll_text"])
    needy = [{"n": r["n"], "dur": r["b"] - r["a"], "visual": r["visual"], "text": r["text"]} for r in recs if not r["reason"]]
    chains = broll.get("chains") or []
    acc: dict[int, dict] = {}
    rej: dict[int, str] = {}
    if needy and not chains:
        rej = {x["n"]: "no_chains" for x in needy}
    if needy and chains:
        try:
            raw = deps.assign_broll(needy, chains, cfg) or []
            broll["assign"] = raw   # الردّ الخام يُحفظ للمراجعة: بدونه لا يُعرف ما الذي رُفض (Issue #1462)
            acc, rej = reel_broll.resolve(raw, needy, chains, broll.get("hook"))
        except Exception as exc:  # noqa: BLE001 -- الإسناد تحسين: الجمل كلها بالصورة
            log.warning("تعذّر إسناد لقطات الحدث: %s", reel_clips.scrub_text(str(exc))[:150])
            rej = {x["n"]: "no_match" for x in needy}
    # احتياط اللقطة قبل الصورة (Issue #1644، Q2): كل جملة بقيت بالصورة لسبب غير no_visual، وجملة بطاقة السؤال المجرّدة، تُسند إليها
    # سلسلة relevant لم تُستعمل (نفس المدقّق: الطول والتداخل). لا سلسلة تصلح ← الصورة كما كانت
    if chains:
        left = [{"n": r["n"], "dur": r["b"] - r["a"]} for r in recs
                if r["n"] not in acc and (r["reason"] != "no_visual" or script["scenes"][r["scene"]].get("role") == "question")]
        if left:
            acc.update(reel_broll.fallback(left, chains, list(acc.values()), broll.get("hook")))
    out: dict[int, list[dict]] = {}
    used_channels: list[str] = []
    n_fallback = 0
    for r in recs:
        entry = {"scene": r["scene"], "sentence": r["sentence"]}
        w = acc.get(r["n"])
        if w is not None:
            clip = None
            try:
                clip = _download_with_retries(deps, rcfg, w["video_id"], int(math.floor(w["start"])), int(math.ceil(w["end"])),
                                              tmp / f"broll_{r['n']}.mp4")
            except Exception as exc:  # noqa: BLE001
                log.warning("تعذّر تنزيل لقطة الحدث %s: %s", w["video_id"], reel_clips.scrub_text(str(exc))[:120])
            if clip is None:
                notes.append(t["comment_broll_failed"].format(n=r["n"], channel=w.get("channel", "")))
                r["reason"] = "download"
            else:
                out.setdefault(r["scene"], []).append({"a": r["a"], "b": r["b"], "clip": clip,
                                                       "cexpr": _hook_crop(clip, cfg, deps, None, video_id=w["video_id"],
                                                                           channel=w.get("channel", ""), notes=notes)})
                entry.update({"video_id": w["video_id"], "start": w["start"], "end": w["end"],
                              "channel": w.get("channel", ""), "desc": w.get("desc", "")})
                if w.get("fallback"):
                    entry["fallback"] = True
                    n_fallback += 1
                used_channels.append(w.get("channel", ""))
        else:
            r["reason"] = r["reason"] or rej.get(r["n"]) or "no_match"
        if "video_id" not in entry:
            entry["photo"] = reasons.get(r["reason"], r["reason"])
        result.append(entry)
    total, used = len(recs), len(used_channels)
    if recs and not chains:
        videos = (broll.get("scan") or {}).get("videos") or {}
        notes.append(t["comment_broll_scan"].format(
            s=sum(v.get("classified", 0) for v in videos.values()), n=len(videos),
            f=sum(v.get("footage_relevant", 0) + v.get("footage_other", 0) for v in videos.values()),
            min=int(cfg.path("reel.broll.min_seconds", 3))))
    if recs:
        counts = Counter(c for c in used_channels if c)
        names = f" ({'، '.join(f'{c} ×{k}' for c, k in counts.items())})" if counts else ""
        fb = t["comment_broll_fallback_part"].format(k=n_fallback) if n_fallback else ""
        notes.append(t["comment_broll"].format(used=used, total=total, fallback=fb, channels=names, photo=total - used))
    broll["channels"] = list(dict.fromkeys(c for c in used_channels if c))
    return out


def _assemble(script: dict, clips: dict, cfg, deps: Deps, tmp: Path, voice: str, bg: dict | None = None,
              credit: str = "", speakers: dict | None = None, notes: list | None = None, draft: dict | None = None,
              crops: dict | None = None, broll: dict | None = None,
              sources_out: list | None = None, dropped: list | None = None,
              pre_entries: list | None = None) -> tuple[list[Path], list[str], list[float]]:
    rcfg = cfg.path("reel.render")
    lead = transition_seconds(cfg)
    clips, dead_scenes = _prune_mismatched(script, clips, cfg, deps, speakers if speakers is not None else {},
                                           notes if notes is not None else [], dropped if dropped is not None else [])
    names = list(dict.fromkeys(s.get("channel_display", "") for i, s in enumerate(script["scenes"])
                               if i in clips and s.get("channel_display")))
    # قناة لقطة الهوك تُنسب في الختام إن لم تكن فيه (Issue #1440)
    hook_channel = ((draft or {}).get("hook_video") or {}).get("channel") if isinstance((draft or {}).get("hook_video"), dict) else None
    if hook_channel and hook_channel.casefold() not in (n.casefold() for n in names):
        names.append(hook_channel)
    scene_files: list[Path] = []
    kinds: list[str] = []
    durs: list[float] = []
    # مشهد title_card هوك يتقدّم إلى أول الريل ثم cold_open_clip ثم الباقي بترتيبه (Issue #1429)؛ الفهرس الأصلي يبقى لمفاتيح clips
    order = [x for x in enumerate(script["scenes"]) if x[0] not in dead_scenes]
    hooks = [x for x in order if x[1].get("kind") == "title_card"][:1]
    hook_idx = hooks[0][0] if hooks else None
    order = hooks + [x for x in order if x[0] != hook_idx]
    # لوحات إجابات السؤال (P2c-1، سيناريو v2 وحده): مقاطع q الواحد مشهد واحد؛ كل فهرس مقطع في run يُتخطى ما عدا أول الحاضرين
    groups = _panel_groups(order, script, clips)
    panel_skip = {i for run in _iter_runs(order) for i in run} if reel_script.is_v2(script) else set()
    nar_t = 0.0       # زمن مشاهد الراوي التراكمي: بداية خلفيتها المتحركة (الانتقال يأكل lead من كل مشهد)
    nar_bg: Path | None = None
    nar_plan: dict | None = None
    speech_cache: dict[int, tuple[Path, list[tuple[str, float]]]] = {}
    nar_idx = [i for i, sc in order if i != hook_idx and sc.get("kind") == "narration"]
    if bg is not None and nar_idx:
        # تمريرة أولى لأصوات الراوي: خطة الحركة تحتاج مدة الراوي الكلية T قبل رسم أي مشهد، والحلقة تعيد استعمال الأصوات نفسها
        # فلا يُوَلَّد صوت جملة مرتين. الانتقال يأكل lead من كل مشهد بعد الأول (Issue #1447، متابعة R5d1)
        for i in nar_idx:
            speech_cache[i] = _speech(script["scenes"][i].get("text", ""), voice, cfg, deps, tmp, f"s{i:02d}")
        # بطاقة السؤال تزيد qcard.tail على مدة مشهدها فتدخل في المدة الكلية كي لا تتجمد الحركة قبل نهاية الراوي (P2b)
        qtail = float(cfg.path("reel.render.qcard.tail"))
        # لوحة إجابة واحدة (n = 1) تتحرك فوق الخلفية نفسها فمدتها تدخل هنا أيضًا (P2c-1)
        single = [clips[g[0]]["seconds"] for g in groups.values() if len(g) == 1]
        total_nar = sum(scene_seconds(sum(d for _, d in speech_cache[i][1]),
                                      qtail if script["scenes"][i].get("role") == "question" else 0.0, lead)
                        for i in nar_idx) + sum(single) - lead * (len(nar_idx) + len(single) - 1)
        wide, wcx = _wide_of(bg)
        nar_plan = pan_plan(cfg, "narration_bg", wide.size[0], wide.size[1], total_nar, wcx)
        nar_bg = _pan_background(wide, nar_plan, tmp, "nar_bg.png")
    scene_broll: dict[int, list[dict]] = {}
    plan = (draft or {}).get("broll_plan")
    if broll is not None and plan and nar_bg is not None and deps.assign_broll is not None:
        scene_broll = _prepare_broll(script, nar_idx, speech_cache, plan, broll, cfg, deps, tmp, lead,
                                     notes if notes is not None else [])
        # قنوات اللقطات المركَّبة تُنسب في الخاتمة مع قناة الهوك
        for ch in broll.get("channels", []):
            if ch.casefold() not in (n.casefold() for n in names):
                names.append(ch)
    channels = "، ".join(names)
    # سطر «المقاطع من» نفسه يُحفظ لقضية المراجعة النهائية (Issue #1469، R4a) كي يطابق نصّ المنشور ما في الخاتمة
    if sources_out is not None:
        sources_out.append(channels)
    hook_info: dict = {"pre_entries": pre_entries}
    absorbed: set[int] = set()     # مشهد outro يدخل مشهد closing الموحَّد مع السؤال الذي قبله (Issue #1602)
    for pos, (i, scene) in enumerate(order):
        kind, out = scene.get("kind"), tmp / f"scene_{i:02d}.mp4"
        if i in absorbed:
            continue
        if i == hook_idx:
            kind = "hook"
            dur = _hook_scene(i, scene, script, draft or {}, bg, voice, cfg, deps, tmp, out,
                              notes if notes is not None else [], crops, hook_info)
        elif kind == "question" and pos + 1 < len(order) and order[pos + 1][1].get("kind") == "outro":
            absorbed.add(order[pos + 1][0])
            kind = "closing"
            dur = _closing_scene(i, scene, channels, credit, hook_info, draft or {}, voice, cfg, deps, tmp, out,
                                 notes if notes is not None else [], crops, lead)
        elif i in panel_skip:
            if i not in groups:
                continue
            kind = "panel"
            members = [(j, script["scenes"][j]) for j in groups[i]]
            on_bg = len(members) == 1 and bg is not None and nar_plan is not None
            dur = _panel_scene(members, clips, out, cfg, deps, tmp, speakers if speakers is not None else {},
                               notes if notes is not None else [], nar_bg if on_bg else None, nar_plan if on_bg else None, nar_t)
            if on_bg:
                nar_t += dur - lead
        elif kind in reel_script.CLIP_KINDS:
            if i not in clips:
                continue
            overlays, qframes = _clip_layers(i, scene, clips[i], cfg, deps, tmp, speakers if speakers is not None else {},
                                             notes if notes is not None else [])
            dur = _clip_scene(clips[i], overlays, out, cfg, deps, scene, notes, qframes=qframes)
        elif kind == "outro":
            png = _save(frame_outro(cfg, channels, credit=credit) if credit else frame_outro(cfg, channels),
                        tmp / f"outro_{i}.png")
            dur = _still_scene(png, float(rcfg["outro_seconds"]), out, cfg, deps)
        elif kind in ("narration", "question"):
            audio, parts = speech_cache.get(i) or _speech(scene.get("text", ""), voice, cfg, deps, tmp, f"s{i:02d}")
            if kind == "narration" and scene.get("role") == "question":
                # بطاقة سؤال سيناريو v2 (Issue #1613، P2b): تحتل مكان مشهد الراوي في تيار الخلفية وتقدّم nar_t بمدتها
                on_bg = bg is not None and nar_plan is not None
                dur = _qcard_scene(i, scene, audio, parts, out, cfg, deps, tmp, lead, nar_bg if on_bg else None, nar_plan, nar_t,
                                   scene_broll.get(i))
                if on_bg:
                    nar_t += dur - lead
                scene_files.append(out)
                kinds.append(kind)
                durs.append(dur)
                continue
            if kind == "narration":
                frames = _narration_frames(parts, i, cfg, tmp, lead, bg)
                tail = 0.0
                if bg is not None and nar_plan is not None:
                    dur = _timed_scene(frames, audio, out, cfg, deps, tmp, tail, lead, bg_png=nar_bg, bg_start=nar_t,
                                       bg_pan=(nar_plan["x0"], nar_plan["speed"]), broll=scene_broll.get(i))
                    nar_t += dur - lead
                    scene_files.append(out)
                    kinds.append(kind)
                    durs.append(dur)
                    continue
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


def _unify_scenes(scene_files: list[Path], durs: list[float], cfg, deps: Deps, tmp: Path) -> tuple[list[Path], list[float]]:
    """يوحّد طول صورة كل مشهد وصوته (Issue #1436): مقطع صوته أطول من صورته كان يضع offset الانتقال التالي بعد نهاية الصورة
    فيتوقف الفيديو ويضيع كل ما بعده. يُعاد ترميز المسار الأقصر وحده، والمتساويان لا يُلمسان. المدة الموحَّدة = الأطول."""
    rcfg = cfg.path("reel.render")
    out_files, unified = [], []
    for k, (f, d) in enumerate(zip(scene_files, durs)):
        v, a = deps.stream_durations(f)
        if not v or not a:
            # قياس المسارين تعذّر: مدة الحاوية المقيسة هي الأقرب، وإلا المحسوبة
            v = a = float(deps.probe(f) or d)
        plan = scene_fix_plan(float(v), float(a))
        fixed = Path(f)
        if plan["pad_video"] > 0:
            fixed = tmp / f"fix{k}.mp4"
            deps.run(_base("-i", str(f), "-vf", f"tpad=stop_mode=clone:stop_duration={_fmt(plan['pad_video'])}",
                           "-c:v", "libx264", "-preset", str(rcfg.get("preset", "veryfast")), "-crf", str(rcfg.get("crf", 22)),
                           "-pix_fmt", "yuv420p", "-c:a", "copy", str(fixed)))
        elif plan["pad_audio"] > 0:
            fixed = tmp / f"fix{k}.mp4"
            deps.run(_base("-i", str(f), "-af", f"apad=whole_dur={_fmt(float(v))}", "-c:v", "copy",
                           "-c:a", "aac", "-b:a", "128k", "-ar", str(rcfg.get("audio_rate", 48000)), "-ac", "2", str(fixed)))
        out_files.append(fixed)
        unified.append(max(float(v), float(a)))
    return out_files, unified


def _join(scene_files: list[Path], kinds: list[str], durs: list[float], cfg, deps: Deps, tmp: Path,
          info: dict | None = None) -> Path:
    """يضمّ ملفات المشاهد: بانتقالات xfade/acrossfade بأمر واحد، أو concat -c copy حين لا انتقال (seconds=0 أو مشهد واحد).
    الانتقال رقم k يبدأ عند مجموع مدد أول k مشهدًا ناقص k×seconds لأن كل انتقال يأكل مدته من الطول الكلي.
    المدد من _unify_scenes لا من الحاوية؛ info["expected"] يعيد المدة المتوقعة للضمّ لحارس المدة النهائي."""
    rcfg = cfg.path("reel.render")
    joined = tmp / "joined.mp4"
    secs = transition_seconds(cfg)
    scene_files, real = _unify_scenes(scene_files, durs, cfg, deps, tmp)
    if info is not None:
        info["expected"] = sum(real) - max(secs, 0.0) * max(len(real) - 1, 0) if len(real) > 1 else sum(real)
    if secs <= 0 or len(scene_files) < 2:
        lst = tmp / "scenes.txt"
        lst.write_text("".join(f"file '{f}'\n" for f in scene_files), encoding="utf-8")
        deps.run(_base("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)))
        return joined
    tcfg = cfg.path("reel.render.transition")
    vparts, aparts = [], []
    vprev, aprev, acc = "0:v", "0:a", 0.0
    for k in range(1, len(scene_files)):
        acc += real[k - 1]
        kind = _transition_kind(cfg, kinds[k])
        vparts.append(f"[{vprev}][{k}:v]xfade=transition={kind}:duration={_fmt(secs)}:offset={_fmt(acc - k * secs)}[v{k}]")
        aparts.append(f"[{aprev}][{k}:a]acrossfade=d={_fmt(secs)}[a{k}]")
        vprev, aprev = f"v{k}", f"a{k}"
    last = len(scene_files) - 1
    inputs = [x for f in scene_files for x in ("-i", str(f))]
    deps.run(_base(*inputs, "-filter_complex", ";".join(vparts + aparts), "-map", f"[v{last}]", "-map", f"[a{last}]",
                   *_enc(rcfg), str(joined)))
    return joined


def _resolve_background(path: Path, draft: dict, cfg, deps: Deps, notes: list) -> tuple[dict | None, dict]:
    """خلفية الراوي للتركيب: (الطبقة المحضَّرة أو None، reel_bg المحفوظ). manual_image يغلب reel_bg ولا يُرفض أبدًا؛
    مسودة بلا reel_bg (سيناريو قديم) تختار الآن وتُحفظ فورًا. reel_bg محفوظ يُعاد فحصه بقاعدتَي الوجه والتاريخ
    (Issue #1423): فإن سقط يُختار غيره ويُحفظ. فشل التنزيل ← None (الخلفية الكحلية) وسطر في التعليق، لا فشل تركيب."""
    stored = draft.get("reel_bg") if isinstance(draft.get("reel_bg"), dict) and draft["reel_bg"].get("kind") else None
    manual = (draft.get("manual_image") or "").strip()
    draft_date = path.parent.name
    if stored is not None and not manual and stored.get("url"):
        reason = stale_url_reason(stored["url"], draft_date)
        if not reason:
            try:
                img0 = deps.bg_image(stored["url"])
            except Exception as exc:  # noqa: BLE001
                log.warning("تعذّر تنزيل صورة خلفية الراوي: %s", str(exc)[:100])
                img0 = None
            reason = face_reason(cfg, img0) if img0 is not None else None
        if reason:
            log.info("سقطت خلفية الراوي المحفوظة %s: %s", stored["url"][:80], reason)
            stored = None
    if stored is None:
        providers = {**(deps.bg_providers or {}), "download": deps.bg_image}
        stored = pick_background(draft, cfg, providers, draft_date)
        store.update_draft(path, reel_bg=stored)
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


def _hook_note(cfg, hv: dict) -> str:
    return cfg.path("reel.render.texts.comment_hook_found").format(
        channel=hv.get("channel", ""), title=hv.get("title", ""), id=hv["video_id"], start=hv["start"], end=hv["end"],
        views=f"{int(hv.get('views') or 0):,}")


def _hook_searched(draft: dict) -> bool:
    """هل جرى بحث مرحلة السيناريو (R5c3) لهذه المسودة؟ مسودة R5c2 تحمل hook_search بلا attempts ولا skipped ولا error، فتُعدّ قديمة."""
    hs = draft.get("hook_search")
    return isinstance(hs, dict) and any(k in hs for k in ("attempts", "skipped", "error"))


def _ensure_broll_plan(path: Path, draft: dict, cfg) -> None:
    """مسودة سيناريوها جاهز بلا المفتاح broll_plan أصلًا (قديمة، أو ضاعت خطتها قبل #1458) تُكتب خطتها مرة واحدة وتُحفظ فلا
    تتكرر في التركيب التالي. مفتاح موجود، ولو فارغًا بعد عطل، لا يُعاد: الفشل المسجَّل لا يُكرَّر نداؤه في كل تركيب."""
    if "broll_plan" in draft or not cfg.path("reel.broll.enabled", False) or not (draft.get("script") or {}).get("scenes"):
        return
    reel_broll.write_plan(draft, cfg)
    store.update_draft(path, broll_plan=draft.get("broll_plan", []), **(
        {"broll_plan_error": draft["broll_plan_error"]} if "broll_plan_error" in draft else {}))


def _ensure_hook_candidates(path: Path, draft: dict, script: dict, cfg, deps: Deps, notes: list) -> None:
    """البحث الاحتياطي لمسودة قديمة بلا hook_search (R5c3): يُستدعى pick_hook_candidates مرة وتُحفظ نتيجته فلا يتكرر. يسبق حساب
    want_broll لأن _broll_wanted يشترط hook_candidates، وإلا ركّبت المسودة القديمة بلا لقطات حتى بخطة مكتوبة (#1458)."""
    hv = draft.get("hook_video")
    if isinstance(hv, dict) and hv.get("video_id"):
        return
    if not cfg.path("reel.hook_search.enabled", False) or deps.scan_download is None or deps.classify_sheet is None:
        return
    if not any(s.get("kind") == "title_card" for s in script.get("scenes", [])) or _hook_searched(draft):
        return
    if (deps.yt_search is None or deps.make_queries is None or deps.yt_details is None or deps.judge_titles is None
            or not os.environ.get("YOUTUBE_API_KEY", "").strip()):
        log.info("بحث لقطة الهوك: لا حقن أو YOUTUBE_API_KEY غائب — تخطٍّ")
        return
    draft.setdefault("topic_date", path.parent.name)
    reel_hook_search.pick_hook_candidates(draft, cfg, reel_hook_search.HookDeps(
        yt_search=deps.yt_search, yt_details=deps.yt_details, make_queries=deps.make_queries,
        judge_titles=deps.judge_titles))
    store.update_draft(path, hook_candidates=draft.get("hook_candidates", []), hook_search=draft.get("hook_search"))
    if (draft.get("hook_search") or {}).get("error"):
        notes.append(cfg.path("reel.render.texts")["comment_hook_failed"])


def _auto_hook(path: Path, draft: dict, script: dict, cfg, deps: Deps, tmp: Path, notes: list,
               state: "reel_hook_search.ScanState | None" = None, want_broll: bool = False) -> None:
    """الفحص البصري لمرشّحي لقطة الهوك (Issue #1445، R5c3) قبل مشهده. hook_video الموجود (اليدوي أولًا) يغلب؛ وإلا يُفحص
    draft.hook_candidates بترتيبهم ويُعتمد أول مرشّح فيه سلسلة صالحة. لا بحث هنا: البحث الاحتياطي في _ensure_hook_candidates قبله. أي عطل يُبقي الهوك بصورة الخبر وسطرًا في التعليق، ولا يُفشل التركيب."""
    t = cfg.path("reel.render.texts")
    hv = draft.get("hook_video")
    if isinstance(hv, dict) and hv.get("video_id"):
        if hv.get("source") == "auto":
            notes.append(_hook_note(cfg, hv))
        return
    if not cfg.path("reel.hook_search.enabled", False) or deps.scan_download is None or deps.classify_sheet is None:
        return
    if not any(s.get("kind") == "title_card" for s in script.get("scenes", [])):
        return
    if not _hook_searched(draft):
        return
    if (draft.get("hook_search") or {}).get("error") and t["comment_hook_failed"] in notes:
        return  # عطل بحث هذا التركيب سُجّل سطره في _ensure_hook_candidates
    cands = draft.get("hook_candidates") or []
    if not cands:
        if not (draft.get("hook_search") or {}).get("skipped"):
            notes.append(t["comment_hook_none"])
        return
    try:
        res = reel_hook_search.scan_candidates(draft, script, cands, cfg, deps, tmp, state=state, want_broll=want_broll)
    except Exception as exc:  # noqa: BLE001 -- لقطة الهوك تحسين: الهوك يبقى بصورة الخبر
        log.warning("تعذّر فحص مرشّحي لقطة الهوك: %s", reel_clips.scrub_text(str(exc))[:150])
        notes.append(t["comment_hook_failed"])
        return
    if res.get("hook_video"):
        draft["hook_video"] = res["hook_video"]
        search = dict(draft.get("hook_search") or {})
        search["picked"] = [res["hook_video"]["video_id"]]
        search["compared"] = res.get("compared", [])    # ما قورن بين المرشّحين: يفسّر لماذا هذا الفيديو (Q3)
        store.update_draft(path, hook_video=res["hook_video"], hook_search=search)
        notes.append(_hook_note(cfg, res["hook_video"]))
    else:
        notes.append(t["comment_hook_failed"] if res.get("errors") and res["errors"] >= len(cands)
                     else t["comment_hook_no_valid"])


def _broll_wanted(draft: dict, cfg, deps: Deps, bg: dict | None) -> bool:
    """هل تُطلب لقطات الحدث في هذا التركيب؟ تحتاج خطة غير فارغة وخلفية متحركة ومرشّحين وأدوات المسح والإسناد."""
    return bool(cfg.path("reel.broll.enabled", False) and draft.get("broll_plan") and draft.get("hook_candidates")
                and bg is not None and deps.scan_download is not None and deps.classify_sheet is not None
                and deps.scan_frames is not None and deps.assign_broll is not None)


def _scan_broll(draft: dict, script: dict, cfg, deps: Deps, tmp: Path, state: "reel_hook_search.ScanState") -> dict:
    """مسح اللقطات بعد اختيار الهوك (يستبعد نافذته). يعيد دائمًا {chains, hook, scan}: العطل أو انعدام السلاسل لا يفشل التركيب
    بل تبقى الجمل بالصورة ويُكتب سببها وتقرير الفحص (Issue #1460: الصمت كان يخفي سبب الصفر)."""
    hook = draft.get("hook_video") if isinstance(draft.get("hook_video"), dict) else None
    try:
        res = reel_hook_search.scan_broll(draft, script, draft.get("hook_candidates") or [], cfg, deps, tmp, state, hook=hook)
    except Exception as exc:  # noqa: BLE001 -- لقطات الحدث تحسين لا شرط
        log.warning("تعذّر مسح لقطات الحدث: %s", reel_clips.scrub_text(str(exc))[:150])
        return {"chains": [], "hook": hook, "scan": {"videos": {}, "sheets_used": state.sheets_used, "error": True}}
    return {"chains": res["chains"], "hook": hook, "scan": res.get("scan") or {}}


def _topic_hook(path: Path, draft: dict, script: dict, broll: dict, cfg, notes: list, deps: Deps) -> None:
    """هوك احتياطي من لقطات الموضوع (Issue #1462، R5d5): بلا hook_video بعد مسح الهوك ولا سلسلة relevant، تُعتمد أطول سلسلة ميدانية
    من سلاسل الجمل وتُزال نافذتها منها قبل الإسناد. وجود hook_video (يدوي أو آلي) يُبقي السلوك القديم حرفيًا."""
    hv = draft.get("hook_video")
    if (isinstance(hv, dict) and hv.get("video_id")) or not any(s.get("kind") == "title_card" for s in script.get("scenes", [])):
        return
    hook, rest, raw = reel_hook_search.topic_hook(broll.get("chains") or [], draft.get("hook_candidates") or [], cfg,
                                                  deps, script, draft)
    broll["hook_assign"] = raw   # الردّ الخام يُحفظ للمراجعة حتى حين لا يُسند شيء (Issue #1465)
    if hook is None:
        return
    broll["chains"], broll["hook"] = rest, hook
    draft["hook_video"] = hook
    search = dict(draft.get("hook_search") or {})
    search["picked"] = [hook["video_id"]]
    store.update_draft(path, hook_video=hook, hook_search=search)
    notes.append(cfg.path("reel.render.texts.comment_hook_topic").format(
        channel=hook["channel"], title=hook["title"], start=hook["start"], end=hook["end"]))


def _drop_stale_auto_hook(path: Path, draft: dict) -> None:
    """يحذف من المسودة (الذاكرة والقرص) هوكًا ليس اختيارًا ثابتًا فيُعاد اختياره في هذا التركيب:
    auto_topic (كان بالطول ثم بالمعنى، R5d5/R5d6) وauto بلا مفتاح impact (اختير بقاعدة أطول سلسلة قبل P1b، Issue #1606)
    بدل أن يبقيه خروج _auto_hook المبكر لوجود hook_video. اليدوي (بلا source) وauto ذو impact يبقيان."""
    hv = draft.get("hook_video")
    if not isinstance(hv, dict):
        return
    # Q3: auto بإصدار تركيب أقدم يُعاد اختياره أيضًا لأنه اختير قبل التصنيف الصارم للأستوديو والمقارنة بين المرشّحين
    cur = int(load_config().path("reel.render.version", 0) or 0)
    if hv.get("source") == "auto_topic" or (hv.get("source") == "auto" and (
            "impact" not in hv or int(hv.get("render_version") or 0) < cur)):
        draft.pop("hook_video", None)
        store.update_draft(path, remove=["hook_video"])


def _render(path: Path, draft: dict, cfg, deps: Deps, reels_dir: Path, tmp: Path, dropped: list,
            approx: list, notes: list | None = None) -> dict:
    rcfg, scfg = cfg.path("reel.render"), cfg.path("reel.script")
    script = draft.get("script") or {}
    if not script.get("scenes"):
        raise RuntimeError("لا سيناريو معتمد")
    notes = notes if notes is not None else []
    clips, drops, approx_found = _fetch_clips(script, draft, cfg, deps, tmp, notes)
    dropped.extend(drops)
    approx.extend(approx_found)
    wanted = sum(1 for s in script["scenes"] if s.get("kind") in reel_script.CLIP_KINDS)
    need = int(scfg.get("min_clips", 2))
    if len(clips) < need:
        raise RuntimeError(f"بقي {len(clips)} مقطعًا من {wanted} بعد الحذف والأدنى المطلوب {need}")
    voice = cfg.path(f"reel.tts.narrator_voices.{script.get('narrator', 'female')}")
    bg, bg_saved = _resolve_background(path, draft, cfg, deps, notes)
    _ensure_broll_plan(path, draft, cfg)
    _ensure_hook_candidates(path, draft, script, cfg, deps, notes)
    want_broll = _broll_wanted(draft, cfg, deps, bg)
    scan_state = reel_hook_search.ScanState()
    _drop_stale_auto_hook(path, draft)
    _auto_hook(path, draft, script, cfg, deps, tmp, notes, state=scan_state, want_broll=want_broll)
    broll = _scan_broll(draft, script, cfg, deps, tmp, scan_state) if want_broll else None
    if broll is not None:
        _topic_hook(path, draft, script, broll, cfg, notes, deps)
    pre_entries = _pre_hook_entries(draft, scan_state)
    speakers: dict = {}
    hook_crops: dict = {}
    sources_out: list = []
    scene_files, kinds, durs = _assemble(script, clips, cfg, deps, tmp, voice, bg,
                                         outro_credit(cfg, bg["used"]) if bg else "", speakers, notes, draft, hook_crops,
                                         broll=broll, sources_out=sources_out, dropped=dropped, pre_entries=pre_entries)
    join_info: dict = {}
    joined = _join(scene_files, kinds, durs, cfg, deps, tmp, join_info)

    rel_dir = f"{path.parent.name}"
    dest = reels_dir / rel_dir / f"{path.stem}.mp4"
    gif = reels_dir / rel_dir / f"{path.stem}.gif"
    # التمريرة الأخيرة تكتب إلى ملف مؤقت لا إلى dest: dest هو ملف الريل السابق نفسه، وفشل حارس المدة يجب ألا يُتلفه
    final = tmp / "final.mp4"
    music = _final_pass(joined, final, kinds, durs, cfg, deps, tmp, draft)
    # مدة الملف النهائي المقيسة لا مجموع المدد: الانتقالات تقصّر الطول الكلي
    measured = deps.probe(final)
    total = measured or (sum(durs) - transition_seconds(cfg) * max(len(durs) - 1, 0))
    # حارس المدة (Issue #1436): ريل أقصر من المتوقع مقطوع وليس ناقصًا بحدّ مقبول؛ لا يُحفظ ولا يُرفع ولا يُمسّ ملف سابق
    expected = join_info.get("expected")
    if measured and expected and expected - float(measured) > float(rcfg.get("duration_tolerance", 1.5)):
        raise ShortRender(rcfg["texts"]["error_short"].format(actual=round(float(measured), 1), expected=round(expected, 1)))
    # نجح الحارس: استبدال ذري لـdest ثم الـGIF منه
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(final, dest)
    g = rcfg["gif"]
    deps.run(_base("-t", str(g["seconds"]), "-i", str(dest), "-vf",
                   f"fps={g['fps']},scale={g['width']}:{g['height']}:flags=lanczos,split[x][y];[x]palettegen[p];"
                   f"[y][p]paletteuse", "-loop", "0", str(gif)))
    sub = rcfg.get("repo_subdir", "reels")
    return {"reel_file": f"{sub}/{rel_dir}/{dest.name}", "reel_gif": f"{sub}/{rel_dir}/{gif.name}",
            "duration_seconds": round(total, 1), "render_version": int(rcfg.get("version", 1)),
            "render_attempts": 0, **({"reel_music": music} if music else {}),
            "render_sources": sources_out[0] if sources_out else "",
            # الشكل المستعمل في هذا التركيب يُحفظ مع reel_bg؛ بلا صورة منزَّلة لا شكل
            "reel_bg": {**{k: v for k, v in bg_saved.items() if k != "layout"}, **({"layout": bg["layout"]} if bg else {})},
            "render_crops": {**{str(i): c["crop"] for i, c in clips.items() if "crop" in c}, **hook_crops},
            **({"render_speakers": speakers} if speakers else {}),
            **({"render_spans": [c["span"] for _, c in sorted(clips.items()) if c.get("span")]}
               if any(c.get("span") for c in clips.values()) else {}),
            **({"render_broll": broll["result"]} if broll and broll.get("result") else {}),
            **({"broll_scan": {**broll["scan"], "chains": broll.get("chains") or [], "assign": broll.get("assign") or [],
                           **({"hook_assign": broll["hook_assign"]} if "hook_assign" in broll else {})}}
               if broll and broll.get("result") and broll.get("scan") else {})}


def _outro_start(kinds: list[str], durs: list[float], cfg) -> float | None:
    """زمن انتهاء انتقال الختام في الريل المجمَّع (Issue #1592، R5h): الانتقال الأخير يبدأ عند مجموع مدد ما قبل الختام ناقص
    (n−1)×seconds وينتهي بعد seconds؛ ومنه تبدأ حركة الشعار. None إن لم يكن آخر المشاهد ختامًا أو غاب الشعار الكبير."""
    if len(kinds) < 2 or kinds[-1] not in ("outro", "closing") or _logo_ratio(cfg) is None:
        return None
    if kinds[-1] == "closing":
        # الشعار ينزل عند plan[logo] من بداية مشهد الختام لا عند انتهاء انتقاله (Issue #1602)؛ بدايته في المجمَّع = مجموع ما قبله
        # ناقص الانتقالات كلها
        return sum(durs[:-1]) - transition_seconds(cfg) * (len(kinds) - 1) + closing_logo_offset(durs[-1], cfg)
    return sum(durs[:-1]) - transition_seconds(cfg) * (len(kinds) - 2)


def shine_frames(cfg, logo: Path, tmp: Path) -> list[tuple[Path, float]]:
    """إطارات لمعة الشعار (P1a، Issue #1600): شريط قطري أبيض شفاف (shine.alpha) عرضه shine.band يعبر الشعار بعرض outro.logo_width من
    اليمين إلى اليسار خلال shine.seconds، محصور في حبر الشعار بضرب ألفاه فلا تظهر اللمعة على الشفاف. [(png، مدة)] بمقاس الشعار الكبير."""
    from PIL import ImageChops
    sc, rcfg = cfg.path("reel.render.shine"), cfg.path("reel.render")
    lw = int(cfg.path("reel.render.outro.logo_width"))
    src = Image.open(logo).convert("RGBA")
    lh = max(round(lw * src.size[1] / src.size[0]), 1)
    mask = src.resize((lw, lh), Image.LANCZOS).getchannel("A")
    fps = float(rcfg["fps"])
    n = max(int(round(float(sc["seconds"]) * fps)), 1)
    band, slant = int(sc["band"]), lh * 0.35
    alpha = round(float(sc["alpha"]) * 255)
    frames: list[tuple[Path, float]] = []
    for f in range(n):
        # مركز الشريط يقطع من خارج اليمين إلى خارج اليسار بحيث يغطي الشعار كله مرة واحدة
        c = (lw + band + slant) - (f + 0.5) / n * (lw + 2 * band + slant)
        band_mask = Image.new("L", (lw, lh), 0)
        ImageDraw.Draw(band_mask).polygon([(c + slant, 0), (c + slant + band, 0), (c + band, lh), (c, lh)], fill=alpha)
        layer = Image.new("RGBA", (lw, lh), (255, 255, 255, 0))
        layer.putalpha(ImageChops.multiply(band_mask, mask))
        frames.append((_save(layer, tmp / f"shine_{f:02d}.png"), 1 / fps))
    return frames


def _final_pass(joined: Path, final: Path, kinds: list[str], durs: list[float], cfg, deps: Deps, tmp: Path,
                draft: dict) -> str | None:
    """التمريرة الأخيرة (الشعار والموسيقى) مستخرجة من _render لتُختبر وحدها (Issue #1592، R5h). تمرّر outro_start إلى
    logo_state/_logo_exprs: عند الختام ينتقل الشعار من الزاوية إلى موضع عبارة «تابعوا الموجز» المحذوفة بتيار مدخل ثانٍ
    للشعار مزاح زمنيًا (setpts) ومكرَّر آخر إطاره (eof_action=repeat) فيثبت إلى النهاية."""
    rcfg = cfg.path("reel.render")
    lg = rcfg["logo"]
    logo = _trimmed_logo(cfg, tmp)
    # الشعار مرة واحدة فوق الفيديو المجمَّع كله: مكانه وحجمه ثابتان في كل لحظة بلا استثناء
    logo_in: list[str] = []
    logo_static: list[str] = []
    music = pick_music(draft, cfg)
    ostart = _outro_start(kinds, durs, cfg)
    outro_in: list[str] = []
    outro_f = ""
    tail = "vs" if ostart is not None else "v"      # مع الخاتمة يتبع خرج الشعار الصغير overlay الشعار الكبير فيصير v
    if kinds and kinds[0] == "hook":
        # شعار الهوك الكبير ينتقل إلى الزاوية (Issue #1429): مدخل متحرك مكرَّر بالإطارات ومحدود بـ-t فلا تعمل تعابير t وscale/overlay
        # بـeval=frame إلا على ثواني الهوك والانتقال، والشفافية بمرشح fade لا geq؛ بعدها overlay ثابت بالطريقة القديمة من مدخل
        # منفصل. آخر حالة متحركة تساوي الثابت تمامًا فلا قفزة عند التبديل؛ ما زال الشعار يُركَّب في هذه التمريرة الأخيرة وحدها
        hk = cfg.path("reel.render.hook")
        hook_end = durs[0] - transition_seconds(cfg)
        ex = _logo_exprs(cfg, hook_end)
        logo_in = ["-loop", "1", "-framerate", str(rcfg["fps"]), "-t", _fmt(hook_end + float(hk["logo_move"]) + 0.1)]
        # مدخل الموسيقى مثبَّت على الفهرس 2 في _music_mix فيأتي الشعار الثابت بعده
        logo_static = ["-i", str(logo)]
        static_idx = 3 if music else 2
        # مع الخاتمة يختفي الصغير الثابت عند outro_start ويتولى المدخل الأخير الحركة والثبات (Issue #1592)
        moved = _fmt(hook_end + float(hk["logo_move"]))
        enable = f"between(t,{moved},{_fmt(ostart)})" if ostart is not None else f"gte(t,{moved})"
        video_f = (f"[1:v]scale={int(cfg.path('reel.render.outro.logo_width'))}:-1,format=rgba[lg0];"
                   f"[lg0]scale=w='{ex['w']}':h=-1:eval=frame[lg];"
                   f"[0:v][lg]overlay=x='{ex['x']}':y='{ex['y']}':eval=frame:eof_action=pass[v1];"
                   f"[{static_idx}:v]scale={lg['width']}:-1[lgs];"
                   f"[v1][lgs]overlay=W-w-{lg['right']}:{lg['top']}:"
                   f"enable='{enable}'[{tail}]")
        o_idx = static_idx + 1
        hook_arg = hook_end
    else:
        enable = f":enable='lt(t,{_fmt(ostart)})'" if ostart is not None else ""
        video_f = f"[1:v]scale={lg['width']}:-1[lg];[0:v][lg]overlay=W-w-{lg['right']}:{lg['top']}{enable}[{tail}]"
        o_idx = 3 if music else 2
        hook_arg = -1000.0      # بلا هوك الشعار في الزاوية من البداية: مرحلة الهوك مكتملة دائمًا
    if ostart is not None:
        oc = cfg.path("reel.render.outro")
        ex = _logo_exprs(cfg, hook_arg, ostart)
        outro_in = ["-loop", "1", "-framerate", str(rcfg["fps"]), "-t", _fmt(float(oc["logo_move"]) + 0.1), "-i", str(logo)]
        outro_f = (f";[{o_idx}:v]format=rgba,setpts=PTS-STARTPTS+{_fmt(ostart)}/TB,scale={int(oc['logo_width'])}:-1,"
                   f"scale=w='{ex['w']}':h=-1:eval=frame[lgo];"
                   f"[vs][lgo]overlay=x='{ex['x']}':y='{ex['y']}':eval=frame:eof_action=repeat:"
                   f"enable='gte(t,{_fmt(ostart)})'[v]")
    video_f += outro_f
    # اللمعة (P1a): مرة في الافتتاح عند shine.start ومرة في الختام بعد استقرار الشعار (outro_start + outro.logo_move)؛ بلا شعار لا لمعة
    shine_in: list[str] = []
    starts: list[float] = []
    if kinds and kinds[0] == "hook":
        starts.append(float(cfg.path("reel.render.shine.start")))
    if ostart is not None:
        starts.append(ostart + float(cfg.path("reel.render.outro.logo_move")))
    if starts and _logo_ratio(cfg) is not None:
        sdur = float(cfg.path("reel.render.shine.seconds"))
        sframes = shine_frames(cfg, logo, tmp)
        slst = tmp / "shine_list.txt"
        slst.write_text("".join(f"file '{f}'\nduration {_fmt(d)}\n" for f, d in sframes) + f"file '{sframes[-1][0]}'\n", encoding="utf-8")
        shine_in = ["-f", "concat", "-safe", "0", "-i", str(slst)]
        si = 2 + (1 if music else 0) + (1 if kinds and kinds[0] == "hook" else 0) + (1 if ostart is not None else 0)
        oc = cfg.path("reel.render.outro")
        sx, sy = (int(rcfg["width"]) - int(oc["logo_width"])) // 2, int(oc["logo_top"])
        assert video_f.endswith("[v]")
        video_f = video_f[:-3] + "[vp]"
        labels = "".join(f"[s{k}]" for k in range(len(starts)))
        video_f += f";[{si}:v]format=rgba," + (f"split={len(starts)}{labels}" if len(starts) > 1 else "null[s0]")
        prev = "vp"
        for k, a in enumerate(starts):
            nxt = "v" if k == len(starts) - 1 else f"vq{k}"
            video_f += (f";[s{k}]setpts=PTS-STARTPTS+{_fmt(a)}/TB[t{k}];[{prev}][t{k}]overlay=x={sx}:y={sy}:eof_action=pass:"
                        f"enable='between(t,{_fmt(a)},{_fmt(a + sdur)})'[{nxt}]")
            prev = nxt
    if music:
        # المدة المقيسة للمجمَّع تحدد بداية الاختفاء التدريجي؛ فشل القياس ← مجموع المدد ناقص الانتقالات
        seconds = deps.probe(joined) or (sum(durs) - transition_seconds(cfg) * max(len(durs) - 1, 0))
        music_in, audio_f = _music_mix(cfg, Path(MUSIC_DIR) / music, float(seconds))
        deps.run(_base("-i", str(joined), *logo_in, "-i", str(logo), *music_in, *logo_static, *outro_in, *shine_in,
                       "-filter_complex", video_f + ";" + audio_f,
                       "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
                       "-crf", str(rcfg.get("crf", 22)), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                       "-ar", str(rcfg.get("audio_rate", 48000)), "-ac", "2", "-movflags", "+faststart", str(final)))
    else:
        deps.run(_base("-i", str(joined), *logo_in, "-i", str(logo), *logo_static, *outro_in, *shine_in, "-filter_complex", video_f,
                       "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-preset", "veryfast",
                       "-crf", str(rcfg.get("crf", 22)), "-pix_fmt", "yuv420p", "-af", _loudnorm(cfg), "-c:a", "aac",
                       "-b:a", "128k", "-ar", str(rcfg.get("audio_rate", 48000)), "-ac", "2", "-movflags", "+faststart",
                       str(final)))
    return music


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
    keep_files = False
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
        keep_files = isinstance(exc, ShortRender)
        result = {"render_status": "failed", "render_error": reason}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # القناة حقل عرض للتعليق وحده؛ المحفوظ على المسودة {point_id, kind, start, end, reason}
    approx_saved = [{k: v for k, v in a.items() if k != "channel"} for a in approx]
    changes = {**result, "render_dropped": dropped, "render_approx": approx_saved,
               "rendered_at": datetime.now(timezone.utc).isoformat()}
    remove = ((["render_error"] + ([] if "render_broll" in result else ["render_broll", "broll_scan"])
               + ([] if "render_spans" in result else ["render_spans"]))
              if result["render_status"] == "rendered"
              else [] if keep_files else ["reel_file", "reel_gif", "duration_seconds"])
    text = _comment_text(cfg, draft, result, dropped, approx, notes)
    ok = result["render_status"] == "rendered"
    if ok:
        changes["render_notes"] = text.split("\n")
    updated = store.update_draft(path, remove=remove, **changes)
    issue = draft.get("review_issue")
    # «انشر فورًا» من المرحلة 2 (Issue #1538، W4): تركيب ناجح لمسودة publish_on_render ينشر في الحال بلا قضية مراجعة
    # الفيديو، ويُعلَّق بالنتيجة على قضية المرحلة 2. فشل النشر يفتح قضية المراجعة بسطر الفشل (إعادة approved عليها تعيد
    # المحاولة). فشل التركيب لا يصل هنا: publish_on_render يبقى فيُنشر إن نجح تركيب لاحق.
    if ok and updated.get("publish_on_render"):
        published = _publish_on_render(path, updated, cfg, deps, text)
        if published:
            return result
        updated = store.load_draft(path.stem)[1] if store.load_draft(path.stem) else updated
    # تركيب ناجح ← قضية مراجعة الريل (Issue #1469، R4a): تُفتح أو يُعاد كتابة جسمها ويُعلَّق عليها بدل قضية المرحلة 2؛
    # فشل فتحها لا يُفشل التركيب والتعليق يبقى على قضية المرحلة 2 احتياطًا
    if ok and cfg.path("reel.review.enabled", True):
        try:
            from . import reel_review
            issue = reel_review.open_or_update(path, updated, cfg)
        except Exception as exc:  # noqa: BLE001
            log.warning("تعذّر فتح قضية مراجعة الريل %s: %s", path.stem, str(exc)[:150])
    if issue:
        try:
            deps.comment(int(issue), text)
        except Exception as exc:  # noqa: BLE001 -- التعليق إخبار لا شرط للتركيب
            log.warning("تعذّر التعليق على القضية %s: %s", issue, str(exc)[:150])
    return result


def _publish_on_render(path: Path, draft: dict, cfg, deps: Deps, notes_text: str) -> bool:
    """ينشر ريلًا اعتُمد بـ«انشر فورًا» بعد تركيبه (Issue #1538، W4). يعيد True إن نُشر (وانتهى الأمر)، وFalse إن فشل
    النشر فتُفتح قضية المراجعة بالمسار القائم. publish_on_render يُزال في الحالتين: التركيب نجح والمحاولة جرت."""
    from . import publish
    t = cfg.path("reel.review", {}) or {}
    title = (draft.get("script") or {}).get("title") or draft.get("title", draft["id"])
    d = store.update_draft(path, status="approved_reel")
    ok, info = False, ""
    try:
        ok, info = publish.publish_reel_draft(path, d, cfg)
    except Exception as exc:  # noqa: BLE001 -- عطل غير متوقع يُعامَل فشل نشر قابلًا لإعادة المحاولة
        info = " ".join(str(exc).split())[:300] or exc.__class__.__name__
        store.update_draft(path, status="failed", error=info, failed_stage="facebook_reel",
                           failed_at=datetime.now(timezone.utc).isoformat())
    store.update_draft(path, remove=["publish_on_render"])
    if not ok:
        log.warning("فشل نشر الريل %s بعد تركيبه: %s", path.stem, info[:150])
        return False
    issue = draft.get("stage2_issue") or draft.get("review_issue")
    if issue:
        line = t.get("published", "").format(title=title, url=info)
        if path_line := publish.reel_path_line(draft["id"], cfg):
            line += "\n" + path_line
        try:
            deps.comment(int(issue), line + "\n\n" + notes_text)
        except Exception as exc:  # noqa: BLE001 -- التعليق إخبار لا شرط للنشر
            log.warning("تعذّر التعليق على القضية %s: %s", issue, str(exc)[:150])
    return True


# ───────────────────────────── الطابور ─────────────────────────────


def _newest_first(stamp) -> tuple:
    """مفتاح فرز تنازلي لنص زمني: الأحدث أولًا، وبلا ختم آخرًا."""
    return (0, tuple(-ord(c) for c in stamp)) if stamp else (1, ())


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
        # superseded (Issue #1532) ليس منتظرًا للتركيب ولو بقي render_status="queued"
        if d.get("format") != "reel" or d.get("status") == "superseded":
            continue
        stale =(version is not None and d.get("status") == "approved_script" and d.get("render_status") == "rendered"
                 and int(d.get("render_version") or 0) < version)
        # failed بنسخة أقدم يُحيا تلقائيًا (Issue #1406): سببه قد يكون عطلًا أُصلح في النسخة الجديدة
        revive = (version is not None and d.get("status") == "approved_script" and d.get("render_status") == "failed"
                  and int(d.get("render_version") or 0) < version)
        if d.get("render_status") == "queued" or stale or revive:
            out.append((p, d))
    # مجموعتان (Issue #1423): المنتظر أولًا ثم المعاد تركيبه (stale وrevive)، وداخل كل مجموعة الأحدث اعتمادًا أولًا
    out.sort(key=lambda pd: (pd[1].get("render_status") != "queued", _newest_first(pd[1].get("approved_script_at")),
                             pd[0].name))
    return out


def pending_batch(cfg) -> list[tuple[Path, dict]]:
    """ما تركّبه تشغيلة --pending: المنتظر ثم المعتمد بنسخة أقدم، حتى reel.render.max_per_run."""
    out = []
    for path, d in queued_reels(cfg)[: int(cfg.path("reel.render.max_per_run", 1))]:
        if d.get("render_status") == "failed":
            d = store.update_draft(path, remove=["render_error"], render_status="queued", render_attempts=0)
        out.append((path, d))
    return out


def open_missing_reviews(cfg) -> int:
    """يفتح قضية المراجعة لكل ريل مركَّب قبل R4a ولا قضية له (Issue #1472، R4b). فتح قضية لا تركيب فيه ولا ffmpeg ولا
    يوتيوب، فلا يُحسب في reel.render.max_per_run؛ وعطل واحد لا يوقف الباقي. يعيد عدد ما فُتح."""
    import json
    if not cfg.path("reel.review.enabled", True):
        return 0
    from . import reel_review
    opened = 0
    for p in sorted(store.DRAFTS_DIR.glob("*/*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if (d.get("format") != "reel" or d.get("status") != "approved_script" or d.get("render_status") != "rendered"
                or d.get("reel_review_issue") or not d.get("reel_file")):
            continue
        try:
            reel_review.open_or_update(p, d, cfg)
            opened += 1
        except Exception as exc:  # noqa: BLE001 -- قضية لا تُفتح تُعاد في التشغيلة التالية
            log.warning("تعذّر فتح قضية مراجعة الريل %s: %s", p.stem, str(exc)[:150])
    return opened


def retry(draft_id: str, cfg) -> bool:
    """يعيد ريلًا failed إلى queued (failed يجب أن يُحيا بإصلاح سببه)."""
    found = store.load_draft(draft_id)
    if not found or found[1].get("render_status") != "failed":
        return False
    store.update_draft(found[0], remove=["render_error", "render_dropped", "render_approx", "render_spans"],
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
        opened = open_missing_reviews(cfg)
        if opened:
            print(f"فُتحت {opened} قضية مراجعة لريلات مركَّبة سابقًا")
        batch = pending_batch(cfg)
        for path, draft in batch:
            res = render_draft(path, draft, cfg)
            print(f"{path.stem}: {res['render_status']} {res.get('render_error', '')}")
        if not batch:
            print("لا ريل منتظر التركيب")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
