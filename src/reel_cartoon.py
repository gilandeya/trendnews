"""كاريكاتير الهوك (طلب صاحب المشروع 23/11): رسم كاريكاتيري يلخّص ما يقوله المحللون عن سؤال الريل (مثلًا القادة الثلاثة يقتسمون
كعكة خريطة العالم، أو منصة تتويج بترتيب يحكم به التحليل) يظهر في الهوك تحت سؤاله.

قطع لا لوحة (قرار صاحب المشروع 25/11، قضية 2007): الرسم بخلفيته غطّى الشاشة كلها فغابت خلفية الهوك المعتادة (لقطة الحدث). صار الرسم
2–5 قطع بلا خلفية (السفينة، ليبيا بمن عليها، البحر…) تدخل مع دخول السؤال من خارج الشاشة وتتجمّع في مواضعها فوق الخلفية المعتادة.
كل قطعة تُرسم وحدها على لون مفتاح مسطّح (key_color) ويُزال اللون في الكود بالمتصل بحافة الصورة وحده، فلا يُمحى لون مشابه داخل الرسم.

الخطوتان: Claude يكتب فكرة الرسم من مادة الريل نفسها (السؤال وإجابات المحللين ومواقفهم)، فالترتيب أو المفارقة تقولها الإجابات لا
النموذج؛ ثم Gemini يرسمها (`reel.cartoon.model`، مفتاح GEMINI_API_KEY القائم). القرار لصاحب المشروع: تُعرض في قضية مراجعة
السيناريو بمربع غير معلَّم، ولا تدخل الريل إلا إن علّمه. لا يرفع أبدًا: أي عطل ← بلا كاريكاتير وسطر بسببه."""
from __future__ import annotations

import base64
import logging
import os
import re
from pathlib import Path
from typing import Any

from . import llm

log = logging.getLogger(__name__)

CONCEPT_TOOL = {
    "name": "cartoon_concept",
    "description": "فكرة رسم كاريكاتيري واحد يلخّص ما تقوله إجابات المحللين عن سؤال الريل، مقسومًا قطعًا بلا خلفية",
    "input_schema": {"type": "object", "properties": {
        "feasible": {"type": "boolean", "description": "false إن لم تحمل الإجابات فكرة يرسمها كاريكاتير بأمانة"},
        "idea_ar": {"type": "string", "description": "الفكرة بالعربية بجملة واحدة للمراجع"},
        "basis_ar": {"type": "string", "description": "أي إجابات (بأرقامها) تقول ما يرسمه الكاريكاتير"},
        "prompt_en": {"type": "string", "description": "وصف المشهد كاملًا بالإنجليزية (أسلوب مشترك للقطع)"},
        "pieces": {"type": "array", "description": "قطع الرسم بلا خلفية، كل قطعة شيء واحد أو مجموعة متماسكة", "items": {
            "type": "object", "properties": {
                "name_ar": {"type": "string"},
                "person_ar": {"type": "string", "description": "اسم الشخص الذي ترسمه القطعة بالعربية كما يرد في نص الريل"},
                "person_en": {"type": "string", "description": "اسمه بحروفه اللاتينية المعروفة"},
                "prompt_en": {"type": "string", "description": "وصف القطعة وحدها بالإنجليزية: الشخص بملامحه وموقعه وما يحمله، بلا أرضية ولا سماء"},
                "x": {"type": "number", "description": "مركز القطعة أفقيًا في منطقة الرسم: 0 يسار، 1 يمين"},
                "y": {"type": "number", "description": "مركزها رأسيًا في منطقة الرسم: 0 أعلى، 1 أسفل"},
                "width": {"type": "number", "description": "عرضها نسبةً من عرض منطقة الرسم (0.15–0.9)"},
                "enter": {"type": "string", "enum": ["left", "right", "bottom"],
                          "description": "من أين تدخل الشاشة (لا من الأعلى أبدًا)"},
                "cue_ar": {"type": "string", "description": "كلمة أو عبارة قصيرة من عنوان الريل تدخل القطعة عند نطقها: اسم صاحبها أو "
                                                            "موضوعه (إيران لقائد إيراني)، حرفيًا كما في العنوان؛ فارغ إن لم يرد"}},
            "required": ["name_ar", "person_ar", "person_en", "prompt_en", "enter"]}}},
        "required": ["feasible", "idea_ar", "basis_ar", "prompt_en", "pieces"]},
}

OK_RE = re.compile(r"^\s*-\s*\[([ xX])\][^\n]*?<!--\s*cartoonok:([0-9a-f]+)\s*-->", re.MULTILINE)


def ccfg(cfg) -> dict:
    return cfg.path("reel.cartoon") or {}


def enabled(cfg) -> bool:
    return bool(ccfg(cfg).get("enabled", False))


def _create(client, **kwargs):
    """نقطة نداء Claude (يزيّفها الاختبار)."""
    return llm.create(client, **kwargs)


def _generate(body: dict, model: str, key: str, timeout: int):
    """نقطة نداء Gemini (يزيّفها الاختبار): (رمز HTTP، الرد، الثواني)."""
    from . import gemini
    return gemini.generate(body, model, key, timeout=timeout)


def material(script: dict) -> str:
    """مدخل فكرة الرسم: سؤال الريل وسياقه، ولكل سؤال إجاباته بقائليها ومواقفها وترجمتها (ما سيسمعه المشاهد)."""
    scenes = script.get("scenes") or []
    lines = [f"سؤال الريل: {script.get('title', '')}"]
    ctx = " ".join(s.get("text", "") for s in scenes if s.get("kind") == "narration" and s.get("role") == "context")
    if ctx:
        lines.append(f"السياق: {ctx}")
    n = 0
    for s in scenes:
        if s.get("kind") == "narration" and s.get("role") == "question":
            lines.append(f"\n## {s.get('text', '')}")
        elif s.get("kind") in ("clip", "cold_open_clip") and s.get("role") != "context":
            n += 1
            who = s.get("speaker_name") or s.get("channel_display") or "متحدث"
            stance = f" · الموقف: {s['stance']}" if s.get("stance") else ""
            lines.append(f"[{n}] {who} ({s.get('channel_display', '')}){stance}: «{s.get('quote_arabic', '')}»")
    return "\n".join(lines)


def concept(script: dict, cfg, client=None) -> tuple[dict | None, str]:
    """(الفكرة، "") أو (None، السبب). الرد المقطوع لا يُقبل."""
    from .meta_topics import _tool_input
    c = ccfg(cfg)
    resp = _create(client, cfg=cfg, model=c.get("concept_model", "claude-sonnet-5"),
                   max_tokens=int(c.get("max_tokens", 2000)), system=str(c.get("concept_system", "")),
                   tools=[CONCEPT_TOOL], tool_choice={"type": "tool", "name": CONCEPT_TOOL["name"]},
                   messages=[{"role": "user", "content": material(script)}])
    if str(getattr(resp, "stop_reason", "") or "") == "max_tokens":
        return None, "الرد مقطوع"
    got = _tool_input(resp, CONCEPT_TOOL["name"]) or {}
    if not got.get("feasible"):
        return None, str(got.get("idea_ar") or "لا فكرة يرسمها كاريكاتير بأمانة")
    prompt = " ".join(str(got.get("prompt_en") or "").split())
    if not prompt:
        return None, "وصف رسم فارغ"
    pieces = clean_pieces(llm.tool_json(got.get("pieces"), list) or [], cfg)
    lo, hi = int(c.get("min_pieces", 2)), int(c.get("max_pieces", 5))
    if len(pieces) < lo:
        return None, f"قطع الرسم أقل من {lo}"
    return {"idea_ar": " ".join(str(got.get("idea_ar") or "").split()),
            "basis_ar": " ".join(str(got.get("basis_ar") or "").split()), "prompt_en": prompt, "pieces": pieces[:hi]}, ""


def _num(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def clean_pieces(raw: list, cfg) -> list[dict]:
    """قطع الفكرة بعد التحقق (دالة خالصة): وصف غير فارغ، ومواضع داخل [0، 1]، وعرض بين min/max_width، واتجاه دخول معروف
    (وإلا من الأسفل)."""
    c = ccfg(cfg)
    lo_w, hi_w = float(c.get("min_width", 0.15)), float(c.get("max_width", 0.9))
    out = []
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        prompt = " ".join(str(p.get("prompt_en") or "").split())
        if not prompt:
            continue
        enter = str(p.get("enter") or "bottom")
        person_ar = " ".join(str(p.get("person_ar") or "").split())
        # قضية 2013: قطع بلا معنى (ميزان، خريطة صغيرة، مجلس إدارة) كثّرت الصور؛ القطعة شخص من الحدث يُعرف باسمه فيتبع الراوي
        if c.get("persons_only", False) and not person_ar:
            continue
        out.append({"name_ar": " ".join(str(p.get("name_ar") or "").split()), "prompt_en": prompt, "person_ar": person_ar,
                    "person_en": " ".join(str(p.get("person_en") or "").split()),
                    "cue_ar": " ".join(str(p.get("cue_ar") or "").split()),
                    "x": min(max(_num(p.get("x"), 0.5), 0.0), 1.0), "y": min(max(_num(p.get("y"), 0.5), 0.0), 1.0),
                    "width": min(max(_num(p.get("width"), 0.4), lo_w), hi_w),
                    # قضية 2020: دخول من الأعلى مرفوض (طلب صاحب المشروع)، فالأعلى وما لا يُعرف من الأسفل
                    "enter": enter if enter in ("left", "right", "bottom") else "bottom"})
    return out


def area_px(cfg, w: int, h: int) -> tuple[int, int, int, int]:
    """منطقة القطع بالبكسل (يسار، أعلى، يمين، أسفل) من reel.cartoon.area بنسب الشاشة: تحت عنوان السؤال وفوق نص منشور فيسبوك."""
    a = ccfg(cfg).get("area") or {}
    return (round(float(a.get("left", 0.04)) * w), round(float(a.get("top", 0.5)) * h),
            round(float(a.get("right", 0.96)) * w), round(float(a.get("bottom", 0.92)) * h))


def place(size: tuple[int, int], spec: dict, cfg, w: int, h: int) -> tuple[int, int, int, int]:
    """موضع القطعة النهائي (x، y، عرض، ارتفاع) بالبكسل (دالة خالصة): عرضها width من عرض المنطقة بنسبتها، تُصغَّر إن تجاوز ارتفاعها
    المنطقة، ومركزها (x، y) في المنطقة ثم تُحصر كلها داخلها."""
    al, at, ar, ab = area_px(cfg, w, h)
    aw, ah = max(ar - al, 1), max(ab - at, 1)
    sw, sh = max(int(size[0]), 1), max(int(size[1]), 1)
    pw = max(float(spec.get("width", 0.4)) * aw, 2.0)
    ph = pw * sh / sw
    if ph > ah:
        pw, ph = pw * ah / ph, float(ah)
    pw, ph = max(int(round(pw)), 2), max(int(round(ph)), 2)
    cx = al + float(spec.get("x", 0.5)) * aw
    cy = at + float(spec.get("y", 0.5)) * ah
    x = int(round(min(max(cx - pw / 2, al), ar - pw)))
    y = int(round(min(max(cy - ph / 2, at), ab - ph)))
    return x, y, pw, ph


def row_layout(sizes: list[tuple[int, int]], band: tuple[int, int], cfg, w: int) -> list[tuple[int, int, int, int]]:
    """مواضع القطع (x، y، عرض، ارتفاع) صفًّا واحدًا في الحزام [أعلى، أسفل] تحت النص (دالة خالصة): لكل قطعة خانة بعرض متساوٍ بين
    هامشي cast.side، تُصغَّر فيها بنسبتها حتى تسع الخانة وارتفاع الحزام (وcast.max_height)، وتقف على أسفل الحزام، والصف كله في
    وسط الشاشة. القطع لا تتداخل أبدًا ولا تنزل على النص (قضية 2013: قطع النموذج بمواضعه غطّت عنوان الهوك وبعضها بعضًا)."""
    k = ccfg(cfg).get("cast") or {}
    n = len(sizes)
    if not n:
        return []
    side, gap = int(k.get("side", 60)), int(k.get("gap", 30))
    top, bottom = int(band[0]), int(band[1])
    bh = max(min(bottom - top, int(k.get("max_height", 520))), 2)
    slot = max((w - 2 * side - gap * (n - 1)) / n, 2.0)
    dims = []
    if k.get("same_height", False):
        # قضية 2020: الشخص الثالث رُسم نصف جسد عريضًا فبدا أكبر من صاحبيه بعد تصغير كل قطعة لخانتها وحدها؛ ارتفاع واحد للصف كله
        # (أعلى ما تسعه كل القطع في خاناتها) فيتناسب الأشخاص
        ph = min([bh] + [slot * max(int(sh), 1) / max(int(sw), 1) for sw, sh in sizes])
        for sw, sh in sizes:
            sw, sh = max(int(sw), 1), max(int(sh), 1)
            dims.append((max(int(round(sw * ph / sh)), 2), max(int(round(ph)), 2)))
    for sw, sh in ([] if dims else sizes):
        sw, sh = max(int(sw), 1), max(int(sh), 1)
        sc = min(slot / sw, bh / sh)
        dims.append((max(int(round(sw * sc)), 2), max(int(round(sh * sc)), 2)))
    total = sum(d[0] for d in dims) + gap * (n - 1)
    x = int(round((w - total) / 2))
    out = []
    for pw, ph in dims:
        out.append((x, bottom - ph, pw, ph))
        x += pw + gap
    return out


def start_pos(enter: str, box: tuple[int, int, int, int], w: int, h: int) -> tuple[int, int]:
    """موضع القطعة قبل دخولها: خارج الشاشة تمامًا من جهة enter وعلى خط موضعها النهائي (دالة خالصة). لا دخول من الأعلى (قضية
    2020): «top» يُعامل كالأسفل."""
    x, y, pw, ph = box
    return {"left": (-pw, y), "right": (w, y)}.get(enter, (x, h))


def row_enter(k: int, n: int, cfg) -> str:
    """جهة دخول القطعة k من n في الصف (قضية 2020، طلب صاحب المشروع): الطرفان من جهتيهما (الأولى في الصف يسارًا، والأخيرة يمينًا)
    وما بينهما من الأسفل (cast.edge_sides)، وقطعة واحدة من الأسفل. قضية 2027: كان الطرفان من جهتيهما في ثلاث فأكثر وحدها، فدخلت
    قطعتان من الأسفل وصاحب المشروع يريد كل واحدة من جهتها. دالة خالصة."""
    if bool((ccfg(cfg).get("cast") or {}).get("edge_sides", True)) and n >= 2:
        if k == 0:
            return "left"
        if k == n - 1:
            return "right"
    return "bottom"


def cutout(img, cfg, crop: bool = True):
    """القطعة بلا خلفية (RGBA مقصوصة إلى حدودها) أو None. crop=False (طبقات المشهد، 28/11): الصورة بمقاسها كاملة بلا قصّ ولا فحص
    الحواف، لأن موضع الطبقة في لوحة المشهد هو ما يجعل الطبقات تعود صورة واحدة، والقدمان على حافة المشهد طبيعيتان. لون المفتاح (key_color) يُزال حيث يتصل بحافة الصورة وحدها، فلون مشابه
    داخل الرسم (علم أو بحر) لا يُمحى؛ ثم تنعيم الحافة وإزالة أثر اللون عنها. تغطية خارج [min_cover، max_cover] ← None (المولّد لم
    يرسم على اللون المسطّح أو لم يرسم شيئًا)."""
    import cv2
    import numpy as np
    from PIL import Image
    c = ccfg(cfg)
    rgb = np.asarray(img.convert("RGB")).astype(np.int32)
    from . import imaging
    key = np.array(imaging.hex_rgb(str(c.get("key_color", "#FF00FF"))), np.int32)
    near = (np.sqrt(((rgb - key) ** 2).sum(axis=2)) <= float(c.get("key_tolerance", 110))).astype(np.uint8)
    n, labels = cv2.connectedComponents(near, connectivity=4)
    edge = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    bg = np.isin(labels, list(edge)) & (near > 0)
    # قضية 2039: لون المفتاح بقي فاقعًا بين ساقي نتنياهو لأن الفراغ محاط بالرسم لا يتصل بالحافة؛ الفراغ المسطّح بلون المفتاح يُزال
    bg = bg | key_holes(rgb, ~bg, cfg)
    alpha = np.where(bg, 0.0, 1.0).astype(np.float32)
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
    cover = float((alpha > 0.5).mean())
    if not float(c.get("min_cover", 0.03)) <= cover <= float(c.get("max_cover", 0.95)):
        return None
    if crop and cropped(alpha > 0.5, cfg):
        return None
    # قضية 2020: هالة وردية بقيت حول القطع؛ ما قرب الخلفية (despill_px) ولونه يميل إلى لون المفتاح يُزال أيضًا
    dpx = int(c.get("despill_px", 3))
    if dpx > 0:
        near_bg = cv2.dilate(bg.astype(np.uint8), np.ones((2 * dpx + 1, 2 * dpx + 1), np.uint8)) > 0
        dist = np.sqrt(((rgb - key) ** 2).sum(axis=2))
        spill = near_bg & (dist <= float(c.get("despill_tolerance", 200)))
        alpha = np.where(spill, 0.0, alpha).astype(np.float32)
    out = rgb.astype(np.float32)
    # أثر اللون على الحافة: حيث الشفافية جزئية تُخفَّض كل قناة يبرزها لون المفتاح إلى أعلى القنوات الأخرى، فلا تبقى هالة بلونه
    soft = (alpha > 0) & (alpha < 1)
    strong = [k for k in range(3) if key[k] >= 200]
    weak = [k for k in range(3) if key[k] < 200]
    if strong and weak:
        cap = np.max(out[..., weak], axis=2)
        for k in strong:
            out[..., k] = np.where(soft, np.minimum(out[..., k], cap), out[..., k])
    rgba = np.dstack([np.clip(out, 0, 255), alpha * 255]).astype(np.uint8)
    rgba = drop_key_islands(rgba, key, cfg)
    if not crop:
        return Image.fromarray(rgba, "RGBA")
    ys, xs = np.where(alpha > 0.02)
    pad = int(c.get("trim_pad", 4))
    y0, y1 = max(int(ys.min()) - pad, 0), min(int(ys.max()) + pad + 1, rgba.shape[0])
    x0, x1 = max(int(xs.min()) - pad, 0), min(int(xs.max()) + pad + 1, rgba.shape[1])
    return Image.fromarray(rgba[y0:y1, x0:x1], "RGBA")


def drop_key_islands(rgba, key, cfg):
    """يحذف جزر الرسم الصغيرة المصبوغة بلون المفتاح (دالة خالصة على مصفوفة RGBA). السيناريو 2054: ترس ونبتة وبقعة تحت القدم رُسمت
    «باهتة» فاقتربت من لون المفتاح فمحا القصّ بعضها وأبقى بقعًا بنفسجية. الجزيرة = مجموعة رسم متصلة ليست أكبرها، مساحتها ≤ max_share
    من الأكبر، ومتوسط ميلها إلى لون المفتاح (أدنى قنواته القوية ناقص أعلى قنواته الضعيفة) ≥ min_tint؛ قطرات الماء والرذاذ الرمادية
    ميلها قرب الصفر فتبقى. البرومبت يمنع هذه الألوان، وهذا حارس الكود لما يخالفه المولّد. enabled: false ← كما هي."""
    import cv2
    import numpy as np
    ic = ccfg(cfg).get("islands") or {}
    if not ic.get("enabled", False):
        return rgba
    mask = (rgba[..., 3] > 127).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 2:
        return rgba
    strong = [k for k in range(3) if key[k] >= 200]
    weak = [k for k in range(3) if key[k] < 200]
    if not strong or not weak:
        return rgba
    rgb = rgba[..., :3].astype(np.float32)
    tint = rgb[..., strong].min(axis=2) - rgb[..., weak].max(axis=2)
    largest = int(stats[1:, cv2.CC_STAT_AREA].max())
    out = rgba.copy()
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area >= largest or area > float(ic.get("max_share", 0.05)) * largest:
            continue
        sel = labels == i
        if float(tint[sel].mean()) >= float(ic.get("min_tint", 25)):
            out[..., 3][sel] = 0
    return out


def key_holes(rgb, valid, cfg):
    """فراغات بلون المفتاح محاطة بالرسم (بين الساقين، تحت الذراع) لا تتصل بحافة الصورة فتبقى بعد إزالة الخلفية (قضية 2039).
    تُعدّ فراغًا كل مجموعة متصلة داخل valid من بكسلات قريبة من لون المفتاح (holes.tolerance) مساحتها ≥ holes.min_px ومتوسط بُعدها
    عن اللون ≤ holes.mean_distance: الخلفية المسطّحة بعيدها عنه صفر تقريبًا، أما شيء مرسوم بلون قريب (ربطة وردية مظلّلة) فمتوسط
    بُعده أكبر فيبقى. دالة خالصة؛ holes.enabled: false ← لا شيء."""
    import cv2
    import numpy as np
    from . import imaging
    c = ccfg(cfg)
    h = c.get("holes") or {}
    rgb = np.asarray(rgb).astype(np.int32)
    empty = np.zeros(rgb.shape[:2], bool)
    if not h.get("enabled", False):
        return empty
    key = np.array(imaging.hex_rgb(str(c.get("key_color", "#FF00FF"))), np.int32)
    dist = np.sqrt(((rgb - key) ** 2).sum(axis=2))
    near = ((dist <= float(h.get("tolerance", c.get("key_tolerance", 110)))) & np.asarray(valid, bool)).astype(np.uint8)
    n, labels = cv2.connectedComponents(near, connectivity=4)
    out = empty
    min_px, mean_lim = int(h.get("min_px", 20)), float(h.get("mean_distance", 60))
    for k in range(1, n):
        comp = labels == k
        if int(comp.sum()) >= min_px and float(dist[comp].mean()) <= mean_lim:
            out = out | comp
    return out


def clear_key_holes(img, cfg):
    """قطعة محفوظة قبل إصلاح قضية 2039 (RGBA): فراغاتها بلون المفتاح تُجعل شفافة وتُزال هالتها حولها؛ None إن لم يكن فيها فراغ.
    يُطبَّق عند التركيب فيُصلح القطع المرسومة سلفًا بلا رسم جديد."""
    import cv2
    import numpy as np
    from PIL import Image
    from . import imaging
    c = ccfg(cfg)
    arr = np.asarray(img.convert("RGBA")).astype(np.float32)
    rgb, alpha = arr[..., :3], arr[..., 3] / 255.0
    holes = key_holes(rgb, alpha > 0.5, cfg)
    if not holes.any():
        return None
    key = np.array(imaging.hex_rgb(str(c.get("key_color", "#FF00FF"))), np.float32)
    dpx = int(c.get("despill_px", 3))
    ring = cv2.dilate(holes.astype(np.uint8), np.ones((2 * dpx + 1, 2 * dpx + 1), np.uint8)) > 0 if dpx > 0 else holes
    dist = np.sqrt(((rgb - key) ** 2).sum(axis=2))
    alpha = np.where(holes | (ring & (dist <= float(c.get("despill_tolerance", 200)))), 0.0, alpha)
    alpha = cv2.GaussianBlur(alpha.astype(np.float32), (3, 3), 0) * (alpha > 0)
    soft = ring & (alpha > 0)
    strong = [k for k in range(3) if key[k] >= 200]
    weak = [k for k in range(3) if key[k] < 200]
    if strong and weak:
        cap = np.max(rgb[..., weak], axis=2)
        for k in strong:
            rgb[..., k] = np.where(soft, np.minimum(rgb[..., k], cap), rgb[..., k])
    return Image.fromarray(np.dstack([np.clip(rgb, 0, 255), alpha * 255]).astype(np.uint8), "RGBA")


_CLEANED: dict = {}


def clean_file(path: Path, cfg) -> Path:
    """ملف القطعة كما يدخل التركيب: نسخة بلا فراغات بلون المفتاح في مجلد مؤقت إن وُجدت (لا يُكتب فوق ملف المسودة)، وإلا الملف نفسه.
    أي عطل ← الملف نفسه (القطعة تُركَّب كما كانت)."""
    try:
        stamp = (str(path), path.stat().st_mtime)
        if stamp in _CLEANED:
            return _CLEANED[stamp]
        from PIL import Image
        import tempfile
        fixed = clear_key_holes(Image.open(path), cfg)
        out = path
        if fixed is not None:
            out = Path(tempfile.mkdtemp(prefix="cartoon_")) / path.name
            fixed.save(out)
            log.info("قطعة الكاريكاتير %s: أُزيل لون المفتاح من فراغ داخلها", path.name)
        _CLEANED[stamp] = out
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("تعذّر تنظيف قطعة الكاريكاتير %s: %s", path, str(exc)[:120])
        return path


def cropped(mask, cfg) -> bool:
    """هل قصّ إطارُ الصورة القطعةَ؟ (قضية 2020: قائد إيراني رُسم مبتورًا عند ساقيه) جانب من الصورة يغطّي الرسم أكثر من
    edge_max من طوله ← مقصوصة (القدمان على الحافة السفلى تمسّان قليلًا ولا تُرفضان). دالة خالصة."""
    import numpy as np
    m = np.asarray(mask, bool)
    if not m.size:
        return False
    lim = float(ccfg(cfg).get("edge_max", 0.15))
    return any(float(side.mean()) > lim for side in (m[0], m[-1], m[:, 0], m[:, -1]))


def piece_x(p: dict) -> float:
    try:
        return float(p.get("x", 0.5))
    except (TypeError, ValueError):
        return 0.5


def row_order(pieces: list[dict]) -> list[dict]:
    """ترتيب القطع في الصف من يسار المشهد إلى يمينه بموضعها x الذي تخيّله النموذج (قضية 2027)، ترتيبًا ثابتًا (التساوي يُبقي ترتيب
    الكتابة). يُحسم مرة واحدة في plan قبل الرسم والمعاينة ويُحفظ بهذا الترتيب، فالمعاينة التي يعتمدها المراجع والريل صفٌّ واحد."""
    return sorted(pieces, key=piece_x)


def facing_side(k: int, n: int) -> str:
    """جهة القطعة k من n في الصف (دالة خالصة): left/right للطرفين وmiddle لما بينهما ولقطعة وحيدة."""
    if n >= 2 and k == 0:
        return "left"
    if n >= 2 and k == n - 1:
        return "right"
    return "middle"


def image_prompt(piece: dict, con: dict, cfg, side: str = "") -> str:
    """وصف القطعة وحدها مع المشهد كله (ليتّسق أسلوب القطع) وقواعد الشكل الثابتة (قطعة واحدة على لون مفتاح مسطّح، بلا كتابة).
    side موضعها في الصف (facing_side): قضية 2044 — رُسم نتنياهو يهمس ويشير إلى يمين الصورة وهو في يمين الصف فبدا يشير إلى الفراغ؛
    كل قطعة تُرسم وحدها فلا تعرف أين يقف صاحبها، فيُقال لها أن تتجه نحو وسط المشهد (reel.cartoon.facing)."""
    c = ccfg(cfg)
    face = str((c.get("facing") or {}).get(side) or "")
    return (f"{piece['prompt_en']}\n\nThis is one cut-out element of a larger cartoon scene: {con['prompt_en']}\n"
            f"Draw ONLY this element.\n{face}\n\n{c.get('style', '')}\n{c.get('piece_style', '')}").strip()


def read_image(resp: dict) -> tuple[bytes | None, str, dict]:
    """(بايتات الصورة، سبب التوقف، الاستهلاك). أجزاء التفكير (thought) تُهمل؛ بلا صورة ← None."""
    cands = (resp or {}).get("candidates") or []
    finish = (cands[0].get("finishReason") if cands else "") or "no_candidates"
    usage = (resp or {}).get("usageMetadata") or {}
    for p in ((cands[0].get("content") or {}).get("parts") or []) if cands else []:
        data = p.get("inlineData") or p.get("inline_data")
        if data and not p.get("thought") and data.get("data"):
            try:
                return base64.b64decode(data["data"]), finish, usage
            except ValueError:
                return None, "bad_base64", usage
    return None, finish, usage


def _draw_piece(piece: dict, con: dict, cfg, key: str, side: str = "") -> tuple[Any, float, str]:
    """(القطعة RGBA أو None، الكلفة، سبب الفشل): نداء Gemini واحد للقطعة ثم إزالة اللون."""
    from io import BytesIO

    from PIL import Image
    c = ccfg(cfg)
    model = str(c.get("model", "gemini-3.1-flash-image"))
    body = {"contents": [{"parts": [{"text": image_prompt(piece, con, cfg, side)}]}],
            "generationConfig": {"responseModalities": ["IMAGE"],
                                 "imageConfig": {"aspectRatio": str(c.get("piece_aspect", "1:1"))}}}
    usd, why = 0.0, ""
    # قطعة مقصوصة أو لم تنفصل عن خلفيتها تُرسم ثانيةً حتى piece_tries (قضية 2020)، وكل محاولة مدفوعة
    for _ in range(max(int(c.get("piece_tries", 2)), 1)):
        code, resp, _ = _generate(body, model, key, int(c.get("timeout", 180)))
        if code != 200 or not isinstance(resp, dict):
            return None, usd, f"HTTP {code}: {str(resp)[:150]}"
        img, finish, usage = read_image(resp)
        usd = round(usd + int(usage.get("candidatesTokenCount") or 0) * float(c.get("usd_per_mtok_output", 30)) / 1e6
                    + float(c.get("usd_per_image", 0)), 4)
        if not img:
            return None, usd, f"بلا صورة: {finish}"
        cut = cutout(Image.open(BytesIO(img)), cfg)
        if cut is not None:
            return cut, usd, ""
        why = "لم تُفصل القطعة عن خلفيتها أو قصّها إطار الصورة"
    return None, usd, why


def row_mode(cfg) -> bool:
    return str(ccfg(cfg).get("layout", "model")) == "row"


def preview(pieces: list[dict], cfg, w: int, h: int):
    """صورة المراجعة: القطع في مواضعها النهائية فوق لون العلامة (الخلفية الفعلية في الريل لقطة الهوك المعتادة)."""
    from PIL import Image

    from . import imaging
    base = Image.new("RGBA", (w, h), (*imaging.hex_rgb(str(cfg.path("brand.primary_color") or "#12203A")), 255))
    imgs = [Image.open(p["file"]).convert("RGBA") for p in pieces]
    if row_mode(cfg):
        al, at, ar, ab = area_px(cfg, w, h)
        boxes = row_layout([im.size for im in imgs], (at, ab), cfg, w)
    else:
        boxes = [place(im.size, p, cfg, w, h) for im, p in zip(imgs, pieces)]
    for img, (x, y, pw, ph) in zip(imgs, boxes):
        base.alpha_composite(img.resize((pw, ph), Image.LANCZOS), (x, y))
    return base.convert("RGB")


def draw_thinker(draft: dict, cfg, key: str) -> None:
    """كاريكاتير قائل الاقتباس تحت نصه (قضية 2007، طلب صاحب المشروع): قطعة واحدة بأسلوب قطع الهوك تُرسم إن اقتُرح اقتباس، وتُحفظ في
    draft["reel_quote"]["cartoon"] = {path, cost_usd} أو {error}؛ تظهر في مشهد الاقتباس إن وافقت عليه (لا تتبع موافقة رسم الهوك)."""
    q = draft.get("reel_quote")
    c = ccfg(cfg)
    if not isinstance(q, dict) or q.get("status") != "ready" or not c.get("thinker", {}).get("enabled", False):
        return
    name = q.get("speaker_en") or q.get("speaker_ar") or ""
    piece = {"name_ar": q.get("speaker_ar", ""), "person_ar": q.get("speaker_ar", ""), "person_en": q.get("speaker_en", ""),
             "prompt_en": str(c["thinker"].get("prompt", "{name}")).format(name=name)}
    con = {"prompt_en": str(c["thinker"].get("scene", "")).format(name=name)}
    try:
        img, usd, err = _draw_piece(piece, con, cfg, key)
        from . import costs, store
        costs.add("gemini", usd)
        if img is None:
            q["cartoon"] = {"error": err, "cost_usd": usd}
            return
        out_dir = store.draft_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{draft['id']}-thinker.png"
        img.save(path, "PNG")
        q["cartoon"] = {"path": f"drafts/{out_dir.name}/{path.name}", "cost_usd": usd}
    except Exception as exc:  # noqa: BLE001 -- إضافة: الاقتباس صالح بلا رسم
        q["cartoon"] = {"error": f"{type(exc).__name__}: {str(exc)[:150]}"}


def plan(draft: dict, cfg: Any, client=None) -> dict | None:
    """يكتب الفكرة بقطعها ويرسم كل قطعة وحدها ويحفظها PNG شفافة بجوار المسودة (drafts/<اليوم>/<id>-cartoon-<k>.png) ومعاينتها
    (…-cartoon.png، في path) فيودِعها publish.yml مع drafts وتُعرض في القضية. draft["hook_cartoon"] = {status: ready|none, idea_ar,
    basis_ar, prompt_en, pieces: [{name_ar, x, y, width, enter, path}], path, model, cost_usd, error}. أقل من min_pieces قطعة ناجحة
    ← none بسببه. لا يرفع أبدًا."""
    if not enabled(cfg) or not draft.get("script"):
        return None
    c = ccfg(cfg)
    rec: dict = {"status": "none"}
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        rec["error"] = "no_key"
        draft["hook_cartoon"] = rec
        return rec
    draw_thinker(draft, cfg, key)
    try:
        # 28/11: المشهد المبني قطعةً قطعة أولًا؛ فشله (لا مخطط، لا صورة) ← القطع المنفصلة كما كانت، وسببه في scene_error
        # السيناريو 2054: مشهد رُسم وقرأه المشاهد غير المقصود ← لا كاريكاتير (stop)، لا القطع المنفصلة التي لا تُقرأ
        outcome = _plan_scene(draft, cfg, client, key, rec) if scene_mode(cfg) else ""
        if outcome:
            draft["hook_cartoon"] = rec
            return rec
        # القضية 2059: المشهد سقط فرجعت القطع المنفصلة (لا تمرّ بالقراءة ولا بحارس الأسماء) فخرجت تشكيلة رجال بلا أسماء أحدهم يصوّب
        # على الآخر. الهوك بلا رسم أفضل من رسم لم يُفحص: fallback_pieces false ← لا كاريكاتير بسبب المشهد
        if scene_mode(cfg) and not scfg(cfg).get("fallback_pieces", True):
            rec["error"] = str((ccfg(cfg).get("texts") or {}).get("scene_no_fallback", "لم يُرسم المشهد: {why}")).format(
                why=rec.get("scene_error", ""))
            draft["hook_cartoon"] = rec
            return rec
        con, why = concept(draft["script"], cfg, client)
        if not con:
            rec["error"] = why
            draft["hook_cartoon"] = rec
            return rec
        rec.update({k: v for k, v in con.items() if k != "pieces"})
        from . import costs, store
        out_dir = store.draft_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        done, failed, usd = [], [], 0.0
        # قضية 2044: الترتيب يُحسم قبل الرسم (كل قطعة تُرسم متجهة نحو وسط الصف) ويُحفظ، فالمعاينة والريل بترتيب واحد
        ordered = row_order(con["pieces"]) if row_mode(cfg) else list(con["pieces"])
        for k, piece in enumerate(ordered):
            side = facing_side(k, len(ordered)) if row_mode(cfg) else ""
            img, cost, err = _draw_piece(piece, con, cfg, key, side)
            usd += cost
            if img is None:
                failed.append(f"{piece.get('name_ar') or k + 1}: {err}")
                continue
            path = out_dir / f"{draft['id']}-cartoon-{k}.png"
            img.save(path, "PNG")
            done.append({**piece, "path": f"drafts/{out_dir.name}/{path.name}", "file": path})
        usd = round(usd, 4)
        rec["cost_usd"] = usd
        costs.add("gemini", usd)
        if failed:
            rec["failed"] = failed
        if len(done) < int(c.get("min_pieces", 2)):
            rec["error"] = "؛ ".join(failed) or "لا قطعة"
        else:
            w, h = int(cfg.path("reel.render.width")), int(cfg.path("reel.render.height"))
            prev = out_dir / f"{draft['id']}-cartoon.png"
            preview(done, cfg, w, h).save(prev, "PNG")
            # المسار بصيغة حقل image نفسها (drafts/…) لأن raw_url وقارئ التركيب يحلّانه هكذا
            rec.update(status="ready", path=f"drafts/{out_dir.name}/{prev.name}", model=str(c.get("model", "")),
                       pieces=[{k: v for k, v in p.items() if k != "file"} for p in done])
    except Exception as exc:  # noqa: BLE001 -- الكاريكاتير إضافة: السيناريو صالح بدونه
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
        log.warning("تعذّر رسم كاريكاتير الهوك: %s", str(exc)[:150])
    draft["hook_cartoon"] = rec
    return rec


def local_path(rec_or_path) -> Path | None:
    """ملف على القرص من مساره المحفوظ (drafts/…) أو من سجلّ فيه path؛ None إن غاب."""
    from .config import DRAFTS_DIR
    rel = rec_or_path.get("path") if isinstance(rec_or_path, dict) else rec_or_path
    if not rel:
        return None
    path = DRAFTS_DIR / Path(rel).relative_to("drafts")
    return path if path.exists() else None


def usable(draft: dict, cfg) -> list[dict] | None:
    """قطع الكاريكاتير التي تدخل الريل [{…الموضع والاتجاه، file}] إن كان جاهزًا وعلّمه المراجع وبقي من ملفاتها min_pieces؛ وإلا None.
    كاريكاتير قديم بلوحة واحدة (قبل 25/11، بلا pieces) لا يدخل: كان يغطي خلفية الهوك كلها."""
    rec = draft.get("hook_cartoon")
    if not enabled(cfg) or not isinstance(rec, dict) or rec.get("status") != "ready" or not rec.get("approved"):
        return None
    out = []
    for p in rec.get("pieces") or []:
        f = local_path(p.get("path")) if isinstance(p, dict) else None
        if f is not None:
            out.append({**p, "file": clean_file(f, cfg)})
    # قضية 2044: لا يُعاد ترتيب القطع هنا. كانت تُرتَّب بـx (قضية 2027) والمعاينة التي اعتمدها المراجع بترتيب الكتابة، فظهر ترامب
    # ونتنياهو في الريل متعاكسين عمّا اعتُمد. الترتيب يُحسم في plan قبل الرسم والمعاينة ويُحفظ؛ ما حُفظ هو ما عُرض
    return out if len(out) >= int(ccfg(cfg).get("min_pieces", 2)) else None


def cast_pieces(draft: dict, cfg) -> list[dict]:
    """أشخاص الرسم الذين يتبعون الراوي (قضية 2013): قطع الهوك المعتمدة التي لها person_ar، وقائل الاقتباس إن رُسم وأُدرج الاقتباس
    في الريل. [{person_ar, person_en, file, quote}]؛ cast.enabled: false ← []."""
    if not enabled(cfg) or not (ccfg(cfg).get("cast") or {}).get("enabled", False):
        return []
    out = []
    rec = draft.get("hook_cartoon") if isinstance(draft.get("hook_cartoon"), dict) else {}
    # 28/11: طبقات المشهد مرسومة في وضع (يمسك حبلًا، يهمس) فلا تنتقل إلى السياق: ترامب يمسك حبلًا بلا مرشد. قائل الاقتباس كما هو
    hook = [] if rec.get("mode") in ("scene", "whole") else (usable(draft, cfg) or [])
    for p in hook:
        if p.get("person_ar"):
            out.append({"person_ar": p["person_ar"], "person_en": p.get("person_en", ""), "file": p["file"]})
    q = draft.get("reel_quote")
    if isinstance(q, dict) and q.get("approved") and isinstance(q.get("cartoon"), dict):
        f = local_path(q["cartoon"].get("path"))
        if f is not None:
            out.append({"person_ar": q.get("speaker_ar", ""), "person_en": q.get("speaker_en", ""), "file": clean_file(f, cfg),
                        "quote": True})
    return out


def parse_ok(body: str) -> set[str]:
    return {did for mark, did in OK_RE.findall(body or "") if mark.lower() == "x"}


def review_lines(d: dict, cfg, image_url: str = "") -> list[str]:
    """سطور الكاريكاتير في قضية السيناريو: الفكرة وأساسها والصورة ومربعه (معلَّم مع default_checked)، أو سبب غيابه."""
    rec = d.get("hook_cartoon")
    if not isinstance(rec, dict) or not enabled(cfg):
        return []
    t = ccfg(cfg).get("texts") or {}
    if rec.get("status") != "ready":
        # القضية 2059: السبب وحده لا يقول ماذا حاولنا؛ الفكرة معه كي يُعرف أن الرسم تُرك عن قصد
        idea = [f"  <sub>{t.get('tried', 'الفكرة التي جُرّبت')}: {rec['idea_ar']}</sub>"] if rec.get("idea_ar") else []
        return [f"  {t.get('none', '🎨 لا كاريكاتير للهوك')}: {rec.get('error', '')}", *idea, ""]
    out = [f"  {t.get('header', '🎨 كاريكاتير مقترح للهوك')}: {rec.get('idea_ar', '')}",
           f"  <sub>{t.get('basis', 'الأساس')}: {rec.get('basis_ar', '')}</sub>"]
    names = [p.get("name_ar") for p in rec.get("pieces") or [] if isinstance(p, dict) and p.get("name_ar")]
    if rec.get("mode") in ("scene", "whole"):
        out += scene_review_lines(rec, cfg)
    elif names:
        out.append(f"  <sub>{t.get('pieces', 'القطع')}: {' · '.join(names)}</sub>")
    if rec.get("scene_error") and rec.get("mode") not in ("scene", "whole"):
        out.append("  <sub>" + str(t.get("scene_failed", "⚠️ تعذّر رسم المشهد فاستُعملت القطع المنفصلة: {why}")).format(
            why=rec["scene_error"]) + "</sub>")
    out.append("")
    if image_url:
        out += [f'  <img src="{image_url}" width="270">', ""]
    # قضية 2031 (طلب صاحب المشروع): المربع معلَّم من البداية فيدخل الرسم ما لم يُلغِ المراجع تعليمه؛ 28/11: إلا مشهدًا ينسب فعلًا إلى
    # شخص حقيقي (accusatory) فيبقى غير معلَّم حتى يراه المراجع
    mark = "x" if ccfg(cfg).get("default_checked", True) else " "
    if scfg(cfg).get("unchecked_if_accusatory", True) and any(r.get("accusatory") for r in rec.get("relations") or []):
        mark = " "
    out += [f"  - [{mark}] {t.get('approve', 'استعمله خلفيةً للهوك')} <!-- cartoonok:{d['id']} -->", ""]
    return out


# ───────────── المشهد المبني قطعةً قطعة (طلب صاحب المشروع 28/11) ─────────────
# القطع المرسومة كلٌّ وحدها لا تصنع مشهدًا: لا يعرف ترامب أن في يده حبلًا ينتهي عند المرشد، ولا يعرف نتنياهو أين أذن ترامب ليهمس
# فيها، ويختلف المقياس والخط بين القطع. فالمشهد يُرسم كاملًا في صورة واحدة أولًا، ثم تُعزل كل قطعة بتعديل الصورة نفسها («أبقِ X وحده
# وأكمل المحجوب منه») فتبقى في موضعها ومقياسها وأسلوبها، والكود يتحقق أن الطبقات تعود الصورة نفسها. وفي الهوك تنزل كل قطعة عند نطق
# كلمتها في السؤال، بترتيب العمق لا بترتيب الدخول. أي فشل في العزل ← المشهد كاملًا قطعة واحدة؛ فشل المشهد ← القطع المنفصلة كما كانت.

SCENE_TOOL = {
    "name": "cartoon_scene",
    "description": "مشهد كاريكاتيري واحد يعبّر عن سؤال الهوك كما تجيب عنه إجابات المحللين، مقسومًا قطعًا تنزل كل منها عند كلمتها في السؤال",
    "input_schema": {"type": "object", "properties": {
        "feasible": {"type": "boolean", "description": "false إن لم تحمل الإجابات فكرة يرسمها مشهد بأمانة"},
        "idea_ar": {"type": "string", "description": "المشهد بالعربية بجملة واحدة للمراجع"},
        "basis_ar": {"type": "string", "description": "أي إجابات (بأرقامها) يقوم عليها المشهد وما تقوله"},
        "prompt_en": {"type": "string", "description": "وصف المشهد كاملًا بالإنجليزية: كل عنصر وموضعه وعلاقته بالآخرين"},
        "pieces": {"type": "array", "description": "عناصر المشهد التي تنزل منفصلة (2–5)", "items": {
            "type": "object", "properties": {
                "name_ar": {"type": "string", "description": "اسم العنصر بالعربية (ترامب، الحبل، الكرسي…)"},
                "person_ar": {"type": "string", "description": "اسم الشخص إن كان العنصر شخصًا، وإلا فارغ"},
                "element_en": {"type": "string", "description": "العنصر بالإنجليزية كما يظهر في المشهد، ليُعزل وحده من الصورة"},
                "trigger_ar": {"type": "string", "description": "كلمة من سؤال الهوك حرفيًا ينزل العنصر عند نطقها"},
                "enter": {"type": "string", "enum": ["left", "right", "bottom"]},
                "z": {"type": "integer", "description": "العمق: الأصغر خلف الأكبر (نتنياهو خلف ترامب: أصغر)"}},
            "required": ["name_ar", "element_en", "trigger_ar", "enter", "z"]}},
        "relations": {"type": "array", "description": "كل علاقة يرسمها المشهد بين عنصرين (يهمس، يمسك، مربوط)", "items": {
            "type": "object", "properties": {
                "a_ar": {"type": "string"}, "verb_ar": {"type": "string"}, "b_ar": {"type": "string"},
                "basis": {"type": "array", "items": {"type": "integer"}, "description": "أرقام الإجابات التي تقول هذه العلاقة"},
                "accusatory": {"type": "boolean", "description": "true إن كانت العلاقة تنسب فعلًا أو مسؤولية إلى شخص حقيقي"}},
            "required": ["a_ar", "verb_ar", "b_ar", "basis", "accusatory"]}}},
        "required": ["feasible", "idea_ar", "basis_ar", "prompt_en", "pieces", "relations"]},
}


def scfg(cfg) -> dict:
    return ccfg(cfg).get("scene") or {}


def scene_mode(cfg) -> bool:
    return bool(scfg(cfg).get("enabled", False))


def answer_count(script: dict) -> int:
    """عدد الإجابات المرقّمة في مدخل الفكرة (material): أرقام basis تُقبل ضمنها."""
    return sum(1 for s in script.get("scenes") or [] if s.get("kind") in ("clip", "cold_open_clip") and s.get("role") != "context")


def person_problem(person: str, source: str, cfg) -> str:
    """سبب رفض شخص في المشهد أو "" (دالة خالصة). القضية 2059: «قائد التحالف السعودي» و«محارب حوثي» رُسما قوالب بلا اسم، فصار الرسم
    يمثّل شعبًا لا شخصًا. الشخص المرسوم شخص عام يرد اسمه في مادة الريل، والاسم الذي فيه كلمة جماعة أو صفة عامة (scene.group_words) ليس
    اسم شخص؛ وما لا اسم له يُرسم شيئًا بألوان علمه لا رجلًا."""
    from . import reel_figures
    person = " ".join(str(person or "").split())
    if not person:
        return ""
    words = set(person.split())
    if words & set(scfg(cfg).get("group_words") or []):
        return f"«{person}» ليس اسم شخص (جماعة أو صفة عامة): ارسم شيئًا بألوان علمه لا رجلًا"
    if not reel_figures.name_in_sentence(person, source, cfg):
        return f"«{person}» لا يرد شخصًا في مادة الريل"
    return ""


def scene_problems(got: dict, title: str, n_answers: int, cfg, source: str = "") -> list[str]:
    """ما يرفضه الكود من مخطط المشهد (دالة خالصة): عدد القطع، وكلمة نزول ليست حرفيًا في السؤال، وعلاقة بلا إجابة تسندها، وشخص ليس
    شخصًا عامًا مسمّى في المادة (source؛ فارغ ← لا فحص). الحكم بمعنى الكلمة (الأمريكي ← ترامب) للنموذج، ووجودها في النص للكود. طرف العلاقة
    لا يُشترط أن يكون عنصرًا (القضية 2059: «صاروخ الحوثيين» يحمله محارب فأسقط المشهد كله، وطرفاها للعرض والقراءة وحدهما)."""
    from . import reel_figures
    sc = scfg(cfg)
    out: list[str] = []
    pieces = [p for p in llm.tool_json(got.get("pieces"), list) or [] if isinstance(p, dict)]
    lo, hi = int(sc.get("min_pieces", 2)), int(sc.get("max_pieces", 5))
    if not lo <= len(pieces) <= hi:
        out.append(f"عدد العناصر {len(pieces)} والمطلوب بين {lo} و{hi}")
    for p in pieces:
        trig = " ".join(str(p.get("trigger_ar") or "").split())
        if not trig or reel_figures.mention_index(trig, title, cfg) is None:
            out.append(f"كلمة نزول «{p.get('name_ar', '')}» ليست في السؤال حرفيًا: «{trig}»")
    for r in llm.tool_json(got.get("relations"), list) or []:
        if not isinstance(r, dict):
            continue
        basis = [b for b in (r.get("basis") or []) if isinstance(b, int) and 1 <= b <= n_answers]
        label = f"{r.get('a_ar', '')} {r.get('verb_ar', '')} {r.get('b_ar', '')}"
        if not basis:
            out.append(f"علاقة «{label}» بلا إجابة تسندها")
    if source:
        out += [w for w in (person_problem(p.get("person_ar", ""), source, cfg) for p in pieces) if w]
    return out


def clean_scene(got: dict, title: str, cfg) -> dict:
    """المخطط المقبول (دالة خالصة): القطع بعمقها وجهتها، وكلمة نزول لا ترد في السؤال تُفرَّغ (تنزل القطعة بعد السؤال)."""
    from . import reel_figures
    pieces = []
    for k, p in enumerate([p for p in llm.tool_json(got.get("pieces"), list) or [] if isinstance(p, dict)]):
        trig = " ".join(str(p.get("trigger_ar") or "").split())
        if trig and reel_figures.mention_index(trig, title, cfg) is None:
            trig = ""
        enter = str(p.get("enter") or "bottom")
        z = p.get("z")
        pieces.append({"name_ar": " ".join(str(p.get("name_ar") or "").split()),
                       "person_ar": " ".join(str(p.get("person_ar") or "").split()),
                       "element_en": " ".join(str(p.get("element_en") or "").split()), "trigger_ar": trig,
                       "enter": enter if enter in ("left", "right", "bottom") else "bottom",
                       "z": int(z) if isinstance(z, (int, float)) else k})
    rels = [{"a_ar": str(r.get("a_ar", "")), "verb_ar": str(r.get("verb_ar", "")), "b_ar": str(r.get("b_ar", "")),
             "basis": [b for b in (r.get("basis") or []) if isinstance(b, int)], "accusatory": bool(r.get("accusatory"))}
            for r in llm.tool_json(got.get("relations"), list) or [] if isinstance(r, dict)]
    return {"idea_ar": " ".join(str(got.get("idea_ar") or "").split()),
            "basis_ar": " ".join(str(got.get("basis_ar") or "").split()),
            "prompt_en": " ".join(str(got.get("prompt_en") or "").split()),
            "pieces": [p for p in pieces if p["element_en"]][: int(scfg(cfg).get("max_pieces", 5))], "relations": rels}


def scene_concept(script: dict, cfg, client=None) -> tuple[dict | None, str]:
    """(المخطط، "") أو (None، السبب). المخالفة تُعاد مرة في المحادثة بأسبابها (نهج Q8)؛ بقاء علاقة بلا أساس أو عدد قطع خارج الحد ←
    None (القطع المنفصلة كما كانت)، وكلمة نزول ليست في السؤال ← تُفرَّغ وحدها."""
    from .meta_topics import _tool_input
    c, sc = ccfg(cfg), scfg(cfg)
    title = str(script.get("title") or "")
    n = answer_count(script)
    messages: list = [{"role": "user", "content": f"سؤال الهوك (الكلمات التي ينزل عندها كل عنصر من هنا حرفيًا): {title}\n\n"
                                                  + material(script)}]
    got, problems = {}, ["لا رد"]
    for _ in range(2):
        resp = _create(client, cfg=cfg, model=c.get("concept_model", "claude-sonnet-5"),
                       max_tokens=int(c.get("max_tokens", 2000)), system=llm.with_notes(str(sc.get("system", "")), cfg),
                       tools=[SCENE_TOOL], tool_choice={"type": "tool", "name": SCENE_TOOL["name"]}, messages=messages)
        if str(getattr(resp, "stop_reason", "") or "") == "max_tokens":
            return None, "الرد مقطوع"
        got = _tool_input(resp, SCENE_TOOL["name"]) or {}
        if not got.get("feasible"):
            return None, str(got.get("idea_ar") or "لا مشهد يرسمه كاريكاتير بأمانة")
        problems = scene_problems(got, title, n, cfg, source=material(script))
        if not problems:
            break
        block = next((b for b in getattr(resp, "content", []) or [] if getattr(b, "type", "") == "tool_use"), None)
        if block is None:
            break
        messages += [{"role": "assistant", "content": [{"type": "tool_use", "id": block.id, "name": block.name, "input": got}]},
                     {"role": "user", "content": [{"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                                   "content": "صحّح: " + "؛ ".join(problems)}]}]
    hard = [p for p in problems if not p.startswith("كلمة نزول")]
    if hard:
        return None, "؛ ".join(hard)[:300]
    con = clean_scene(got, title, cfg)
    if not con["prompt_en"] or len(con["pieces"]) < int(sc.get("min_pieces", 2)):
        return None, "مشهد بلا وصف أو بعناصر أقل من الحد"
    return con, ""


def _image_body(parts: list, aspect: str) -> dict:
    return {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect}}}


def _cost(usage: dict, c: dict) -> float:
    return int(usage.get("candidatesTokenCount") or 0) * float(c.get("usd_per_mtok_output", 30)) / 1e6 + float(c.get("usd_per_image", 0))


def _gen_image(parts: list, cfg, key: str) -> tuple[Any, float, str]:
    """(صورة PIL أو None، الكلفة، السبب): نداء Gemini واحد بمدخلات نصية أو صورة."""
    from io import BytesIO

    from PIL import Image
    c = ccfg(cfg)
    code, resp, _ = _generate(_image_body(parts, str(scfg(cfg).get("aspect", "1:1"))), str(c.get("model", "")), key,
                              int(c.get("timeout", 180)))
    if code != 200 or not isinstance(resp, dict):
        return None, 0.0, f"HTTP {code}: {str(resp)[:150]}"
    img, finish, usage = read_image(resp)
    usd = _cost(usage, c)
    if not img:
        return None, usd, f"بلا صورة: {finish}"
    return Image.open(BytesIO(img)).convert("RGB"), usd, ""


def scene_prompt(con: dict, cfg) -> str:
    sc, c = scfg(cfg), ccfg(cfg)
    return f"{con['prompt_en']}\n\n{c.get('style', '')}\n{sc.get('scene_style', '')}".strip()


def isolate_prompt(piece: dict, con: dict, cfg) -> str:
    others = ", ".join(p["element_en"] for p in con["pieces"] if p is not piece)
    return str(scfg(cfg).get("isolate_prompt", "Keep only {element}.")).format(element=piece["element_en"], others=others)


def layer_problems(scene, lay, k: int, cfg) -> list[tuple[str, str]]:
    """مخالفات طبقة واحدة مقابل رسم المشهد (دالة خالصة): [(الرمز، النص)] — outside: نسبتها داخل رسم المشهد < min_inside (أزاحها
    المولّد أو رسم غيرها)، whole: مساحتها من رسم المشهد > max_layer_share (أعاد المشهد كله)، empty: لا رسم. الرمز يختار تلميح إعادة العزل."""
    import numpy as np
    sc = scfg(cfg)
    smask = np.asarray(scene)[..., 3] > 127
    m = np.asarray(lay)[..., 3] > 127
    area = int(m.sum())
    if area == 0:
        return [("empty", f"الطبقة {k + 1} فارغة")]
    out = []
    inside = round(float((m & smask).sum()) / area, 3)
    share = round(area / max(int(smask.sum()), 1), 3)
    if inside < float(sc.get("min_inside", 0.85)):
        out.append(("outside", f"الطبقة {k + 1} خارج موضعها في المشهد ({inside})"))
    if share > float(sc.get("max_layer_share", 0.8)):
        out.append(("whole", f"الطبقة {k + 1} تكاد تكون المشهد كله ({share})"))
    return out


def verify_layers(scene, layers: list, cfg) -> dict:
    """هل تعود الطبقات المعزولة صورة المشهد نفسها؟ (دالة خالصة على مصفوفات RGBA بمقاس واحد، مرتّبة بالعمق من الخلف).
    inside: نسبة كل طبقة الواقعة داخل رسم المشهد (طبقة أزاحها المولّد أو رسم غيرها تقع خارجه) ≥ scene.min_inside؛ share: مساحتها من
    رسم المشهد ≤ max_layer_share (لا طبقة تعيد المشهد كله)؛ iou بين اتحاد الطبقات ورسم المشهد ≥ min_iou (لا عنصر ضاع)؛ diff متوسط
    فرق ألوان تركيب الطبقات عن المشهد داخل رسمه ≤ max_diff (لم يُعِد المولّد رسم العنصر بثياب أخرى). يعيد {ok, reasons، والأرقام}."""
    import numpy as np
    sc = scfg(cfg)
    s = np.asarray(scene, np.float32)
    smask = s[..., 3] > 127
    sarea = max(int(smask.sum()), 1)
    union = np.zeros(smask.shape, bool)
    comp = np.zeros(s.shape[:2] + (3,), np.float32)
    inside, share, reasons = [], [], []
    for k, lay in enumerate(layers):
        a = np.asarray(lay, np.float32)
        m = a[..., 3] > 127
        area = max(int(m.sum()), 1)
        inside.append(round(float((m & smask).sum()) / area, 3))
        share.append(round(area / sarea, 3))
        union |= m
        al = a[..., 3:4] / 255.0
        comp = comp * (1 - al) + a[..., :3] * al
        reasons += [text for _, text in layer_problems(scene, lay, k, cfg)]
    iou = round(float((union & smask).sum()) / max(int((union | smask).sum()), 1), 3)
    diff = round(float(np.abs(comp[smask & union] - s[..., :3][smask & union]).mean()) if (smask & union).any() else 255.0, 1)
    if iou < float(sc.get("min_iou", 0.75)):
        reasons.append(f"الطبقات لا تغطي المشهد ({iou})")
    if diff > float(sc.get("max_diff", 45)):
        reasons.append(f"الطبقات تختلف عن المشهد لونًا ({diff})")
    return {"ok": not reasons, "reasons": reasons, "inside": inside, "share": share, "iou": iou, "diff": diff}


def residual_layer(scene, layers: list, cfg) -> tuple[Any, int | None]:
    """ما بقي من رسم المشهد خارج الطبقات السليمة حين فشل عزل عنصر واحد (دالة خالصة). السيناريو 2054: فشل عزل عنصر فسقطت معه طبقتان
    سليمتان ونزل المشهد كله قطعة واحدة. البقية تُقصّ من بكسلات المشهد نفسه (لا رسم جديد)، والمجموعات أصغر من residual_min_share من رسم
    المشهد تُهمل (حواف التنعيم). يعيد (طبقة RGBA بمقاس المشهد أو None إن لم يبقَ شيء، فهرس الطبقة التي تلامسها البقية أكثر أو None إن
    لم تلامس شيئًا): الملامسة تعني أن العنصر متشابك بغيره (الحبل بين اليدين) فيُدمج معه، وغير الملامس عنصر قائم وحده فيصير طبقته."""
    import cv2
    import numpy as np
    from PIL import Image
    sc = scfg(cfg)
    s = np.asarray(scene)
    smask = s[..., 3] > 127
    masks = [np.asarray(L)[..., 3] > 127 for L in layers]
    union = np.zeros(smask.shape, bool)
    for m in masks:
        union |= m
    rest = (smask & ~union).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(rest, connectivity=8)
    floor = float(sc.get("residual_min_share", 0.01)) * max(int(smask.sum()), 1)
    keep = np.zeros(smask.shape, bool)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= floor:
            keep |= labels == i
    if not keep.any():
        return None, None
    px = int(sc.get("contact_px", 3))
    grown = cv2.dilate(keep.astype(np.uint8), np.ones((2 * px + 1, 2 * px + 1), np.uint8)) > 0
    contact = [int((grown & m).sum()) for m in masks]
    into = max(range(len(masks)), key=lambda k: contact[k]) if contact and max(contact) > 0 else None
    out = np.zeros_like(s)
    out[keep] = s[keep]
    return Image.fromarray(out, "RGBA"), into


def merge_layers(base, extra):
    """طبقة واحدة من طبقتين بمقاس واحد: الإضافة تُرسم فوق الأصل حيث لها رسم."""
    from PIL import Image
    out = base.copy()
    out.alpha_composite(extra)
    return out if out.mode == "RGBA" else out.convert("RGBA")


def earliest_trigger(triggers: list[str], title: str, cfg) -> str:
    """أسبق كلمة نزول في السؤال (دالة خالصة): القطعة المدموجة تنزل عند أسبق كلمتي عنصريها فلا تتأخر عن ذكر أحدهما."""
    from . import reel_figures
    best, at = "", None
    for t in triggers:
        j = reel_figures.mention_index(t, title, cfg) if t else None
        if j is not None and (at is None or j < at):
            best, at = t, j
    return best


# ───────────── القراءة العمياء (السيناريو 2054) ─────────────
# الفكرة كُتبت «الناقلة تنفلت من قبضته» والمولّد رسم ترامب يجرّ ناقلة مربوطة، فقرأها المشاهد «الحصار ينجح» على سؤال مفتوح، ولا شيء في
# السلسلة يقرأ الصورة بعد رسمها. نموذج يرى الصورة وحدها بلا الفكرة ولا الأسماء يقول ما يفهمه مشاهد لم يقرأ شيئًا (إن لم يعرف أن
# الناقلة إيرانية فالمشاهد لن يعرف)، ثم حكم نصي يقارن القراءة بالفكرة والسؤال.

READ_TOOL = {
    "name": "read_cartoon",
    "description": "ما يفهمه مشاهد يرى هذا الكاريكاتير لثانيتين ولم يقرأ عنه شيئًا",
    "input_schema": {"type": "object", "properties": {
        "reading_ar": {"type": "string", "description": "جملة أو جملتان: من في الرسم (كما يُعرف من ملامحه أو ألوانه فقط)، وماذا يحدث، ومن يغلب"},
        "unknown_ar": {"type": "string", "description": "ما لا يُعرف من الرسم (طرف لا يدل عليه شيء)، وإلا فارغ"}},
        "required": ["reading_ar", "unknown_ar"]},
}

JUDGE_TOOL = {
    "name": "judge_reading",
    "description": "هل يفهم المشاهد من الرسم ما أُريد منه؟",
    "input_schema": {"type": "object", "properties": {
        "verdict": {"type": "string", "enum": ["match", "contradicts", "decides_open", "unclear", "unsafe"]},
        "reason_ar": {"type": "string", "description": "السبب بجملة واحدة"}},
        "required": ["verdict", "reason_ar"]},
}


def rdcfg(cfg) -> dict:
    return scfg(cfg).get("reading") or {}


def _jpeg_block(img, cfg) -> dict:
    from io import BytesIO
    buf = BytesIO()
    im = img.convert("RGB")
    side = int(rdcfg(cfg).get("max_side", 800))
    im.thumbnail((side, side))
    im.save(buf, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(buf.getvalue()).decode()}}


def read_scene(img, con: dict, title: str, cfg, client=None) -> dict:
    """{reading, unknown, verdict, reason} أو {error}. القراءة بلا الفكرة ولا الأسماء، والحكم يراها مع الفكرة والسؤال وعلاقاته. لا يرفع."""
    from .meta_topics import _tool_input
    rd = rdcfg(cfg)
    try:
        r1 = _create(client, cfg=cfg, model=rd.get("read_model", "claude-sonnet-5"), max_tokens=int(rd.get("max_tokens", 800)),
                     system=str(rd.get("read_system", "")), tools=[READ_TOOL],
                     tool_choice={"type": "tool", "name": READ_TOOL["name"]},
                     messages=[{"role": "user", "content": [_jpeg_block(img, cfg), {"type": "text", "text": str(rd.get("read_prompt", ""))}]}])
        got = _tool_input(r1, READ_TOOL["name"]) or {}
        reading = " ".join(str(got.get("reading_ar") or "").split())
        if not reading:
            return {"error": "لم تُرجع القراءة"}
        unknown = " ".join(str(got.get("unknown_ar") or "").split())
        rels = "؛ ".join(f"{r['a_ar']} {r['verb_ar']} {r['b_ar']}" for r in con.get("relations") or [])
        msg = (f"سؤال الهوك: {title}\nالفكرة المقصودة: {con.get('idea_ar', '')}\nالعلاقات المقصودة: {rels}\n\n"
               f"ما فهمه مشاهد لم يقرأ شيئًا: {reading}\nما لم يعرفه: {unknown or 'لا شيء'}")
        r2 = _create(client, cfg=cfg, model=rd.get("judge_model", "claude-sonnet-5"), max_tokens=int(rd.get("max_tokens", 800)),
                     system=str(rd.get("judge_system", "")), tools=[JUDGE_TOOL],
                     tool_choice={"type": "tool", "name": JUDGE_TOOL["name"]}, messages=[{"role": "user", "content": msg}])
        verdict = _tool_input(r2, JUDGE_TOOL["name"]) or {}
        v = str(verdict.get("verdict") or "")
        if v not in ("match", "contradicts", "decides_open", "unclear", "unsafe"):
            return {"reading": reading, "unknown": unknown, "error": "لم يُرجع الحكم"}
        return {"reading": reading, "unknown": unknown, "verdict": v, "reason": " ".join(str(verdict.get("reason_ar") or "").split())}
    except Exception as exc:  # noqa: BLE001 -- القراءة تحسين: عطلها لا يُسقط الرسم
        log.warning("تعذّرت قراءة الكاريكاتير: %s", str(exc)[:150])
        return {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}


def _png_part(img) -> dict:
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, "PNG")
    return {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(buf.getvalue()).decode()}}


def _isolate(scene_rgb, scene, piece: dict, con: dict, cfg, key: str, hint: str = "") -> tuple[Any, float, str]:
    """(طبقة RGBA بمقاس المشهد أو None، الكلفة، السبب): نداء عزل واحد بالصورة نفسها، وhint تلميح إعادة بعد مخالفة."""
    from PIL import Image
    text = isolate_prompt(piece, con, cfg) + (f"\n\n{hint}" if hint else "")
    img, cost, err = _gen_image([_png_part(scene_rgb), {"text": text}], cfg, key)
    if img is not None and abs(img.size[0] / img.size[1] - scene.size[0] / scene.size[1]) > 0.02:
        return None, cost, "مقاس الطبقة يخالف المشهد"
    lay = cutout(img.resize(scene.size, Image.LANCZOS), cfg, crop=False) if img is not None else None
    return lay, cost, ("" if lay is not None else (err or "لم تُفصل عن خلفيتها"))


def _draw_read(con: dict, title: str, cfg, client, key: str, rec: dict) -> tuple[Any, Any, float, str]:
    """يرسم المشهد ويقرؤه قراءة عمياء؛ غير المطابق يُعاد رسمه حتى max_redraws مرة بالقراءة وسببها. (صورة RGB، المشهد بلا خلفية، الكلفة،
    سبب الإيقاف): سبب غير فارغ مع مشهد ← القراءة خالفت بعد كل المحاولات (لا كاريكاتير)؛ بلا مشهد ← فشل الرسم نفسه."""
    rd = rdcfg(cfg)
    usd, note, attempts = 0.0, "", []
    tries = 1 + (int(rd.get("max_redraws", 1)) if rd.get("enabled", False) else 0)
    scene_rgb = scene = None
    for _ in range(tries):
        prompt = scene_prompt(con, cfg) + (f"\n\n{note}" if note else "")
        scene_rgb, cost, err = _gen_image([{"text": prompt}], cfg, key)
        usd += cost
        scene = cutout(scene_rgb, cfg, crop=False) if scene_rgb is not None else None
        if scene is None:
            return None, None, usd, err or "لم يُفصل المشهد عن خلفيته"
        if not rd.get("enabled", False):
            return scene_rgb, scene, usd, ""
        got = read_scene(scene, con, title, cfg, client)
        attempts.append(got)
        rec["reading"] = {**got, "attempts": len(attempts)}
        if got.get("error") or got.get("verdict") == "match":
            return scene_rgb, scene, usd, ""
        if got.get("verdict") == "unsafe":
            # القضية 2059: العنف من الفكرة نفسها (تبادل ضربات ← سلاح مصوَّب)، فإعادة الرسم تعيده؛ لا كاريكاتير بسببه
            t = ccfg(cfg).get("texts") or {}
            return scene_rgb, scene, usd, str(t.get("reading_unsafe", "لا يصلح للنشر: {reason}")).format(
                reading=got.get("reading", ""), reason=got.get("reason", ""))
        note = str(rd.get("redraw_note", "")).format(reading=got.get("reading", ""), reason=got.get("reason", ""),
                                                     idea=con.get("idea_ar", ""))
    last = attempts[-1] if attempts else {}
    t = ccfg(cfg).get("texts") or {}
    return scene_rgb, scene, usd, str(t.get("reading_failed", "يفهم المشاهد غير المقصود: {reading} ({reason})")).format(
        reading=last.get("reading", ""), reason=last.get("reason", ""))


def _plan_scene(draft: dict, cfg, client, key: str, rec: dict) -> str:
    """المشهد: المخطط ← الصورة كاملة ← القراءة العمياء ← عزل كل عنصر ← التحقق. يعيد "ready" (scene أو whole)، أو "stop" (رُسم المشهد
    وقرأه المشاهد غير المقصود: لا كاريكاتير، لأن القطع المنفصلة لا تُقرأ فتمرّ بالخطأ نفسه)، أو "" ليجرّب plan القطع المنفصلة. لا يرفع.
    عنصر فشل عزله يُعاد مرة بتلميح سببه، ثم يُقصّ من بكسلات المشهد ما بقي خارج الطبقات السليمة: يُدمج مع ما يلامسه أو يصير طبقته
    (السيناريو 2054: فشل عنصر واحد فنزل المشهد كله قطعة واحدة ورُميت طبقتان سليمتان)."""
    from . import costs, store
    con, why = scene_concept(draft["script"], cfg, client)
    if not con:
        rec["scene_error"] = why
        return ""
    sc = scfg(cfg)
    title = str(draft["script"].get("title") or "")
    rec.update({"idea_ar": con["idea_ar"], "basis_ar": con["basis_ar"], "prompt_en": con["prompt_en"],
                "relations": con["relations"], "model": str(ccfg(cfg).get("model", "")),
                "scene_pieces": [{k: p[k] for k in ("name_ar", "element_en", "trigger_ar", "enter", "z")} for p in con["pieces"]]})
    scene_rgb, scene, usd, stop = _draw_read(con, title, cfg, client, key, rec)
    if scene is None:
        costs.add("gemini", round(usd, 4))
        rec["cost_usd"] = round(usd, 4)
        rec["scene_error"] = stop
        return ""
    if stop:
        costs.add("gemini", round(usd, 4))
        rec.update(cost_usd=round(usd, 4), error=stop)
        return "stop"
    out_dir = store.draft_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    rel = f"drafts/{out_dir.name}"
    full = out_dir / f"{draft['id']}-cartoon-scene.png"
    scene.save(full, "PNG")
    hints = sc.get("retry_hints") or {}
    good, bad, layers_log = [], [], []
    for piece in sorted(con["pieces"], key=lambda p: p["z"]):
        lay, cost, err = _isolate(scene_rgb, scene, piece, con, cfg, key)
        usd += cost
        probs = layer_problems(scene, lay, len(good), cfg) if lay is not None else [("failed", err)]
        retried = False
        if probs:
            retried = True
            hint = str(hints.get(probs[0][0], hints.get("failed", ""))).format(element=piece["element_en"])
            lay, cost, err = _isolate(scene_rgb, scene, piece, con, cfg, key, hint)
            usd += cost
            probs = layer_problems(scene, lay, len(good), cfg) if lay is not None else [("failed", err)]
        layers_log.append({"name_ar": piece["name_ar"], "ok": not probs, "retried": retried, "reasons": [t for _, t in probs]})
        if probs:
            bad.append(piece)
        else:
            good.append([dict(piece), lay])
    t = ccfg(cfg).get("texts") or {}
    fallback = ""
    if bad and len(bad) > 1:
        fallback = "؛ ".join(f"{p['name_ar']}: {'، '.join(r for L in layers_log if L['name_ar'] == p['name_ar'] for r in L['reasons'])}"
                            for p in bad)[:300]
    elif bad and good:
        extra, into = residual_layer(scene, [lay for _, lay in good], cfg)
        piece = bad[0]
        entry = next(L for L in layers_log if L["name_ar"] == piece["name_ar"])
        if extra is None:
            entry["dropped"] = True
        elif into is None:
            good.append([dict(piece, from_scene=True), extra])
            good.sort(key=lambda g: g[0]["z"])
            entry["from_scene"] = True
        else:
            host = good[into][0]
            host["merged"] = host.get("merged", []) + [piece["name_ar"]]
            host["trigger_ar"] = earliest_trigger([host["trigger_ar"], piece["trigger_ar"]], title, cfg)
            good[into][1] = merge_layers(good[into][1], extra)
            entry["merged_into"] = host["name_ar"]
    elif bad:
        fallback = "؛ ".join(layers_log[-1]["reasons"])[:300]
    rec["layers"] = layers_log
    check = verify_layers(scene, [lay for _, lay in good], cfg) if len(good) >= 2 and not fallback else None
    usd = round(usd, 4)
    costs.add("gemini", usd)
    rec.update({"cost_usd": usd, "scene_path": f"{rel}/{full.name}"})
    if check is not None:
        rec["scene_check"] = {k: v for k, v in check.items() if k != "ok"}
    prev = out_dir / f"{draft['id']}-cartoon.png"
    w, h = int(cfg.path("reel.render.width")), int(cfg.path("reel.render.height"))
    if check is not None and check["ok"]:
        pieces = []
        for k, (piece, lay) in enumerate(good):
            path = out_dir / f"{draft['id']}-cartoon-{k}.png"
            lay.save(path, "PNG")
            pieces.append({**piece, "path": f"{rel}/{path.name}", "canvas": True})
        rec.update(status="ready", mode="scene", pieces=pieces)
    else:
        # سلّم التراجع الأخير: المشهد كاملًا قطعة واحدة تنزل عند أسبق كلمة نزول (طبقة واحدة باقية هي المشهد نفسه)
        rec["scene_fallback"] = fallback or "؛ ".join((check or {}).get("reasons") or []) or str(
            t.get("one_layer", "لم يبقَ إلا عنصر واحد"))
        rec["scene_fallback"] = rec["scene_fallback"][:300]
        first = earliest_trigger([p["trigger_ar"] for p in con["pieces"]], title, cfg)
        rec.update(status="ready", mode="whole", pieces=[{
            "name_ar": str(t.get("scene_whole_name", "المشهد")), "person_ar": "", "trigger_ar": first, "enter": "bottom", "z": 0,
            "path": f"{rel}/{full.name}", "canvas": True}])
    scene_preview(scene, cfg, w, h).save(prev, "PNG")
    rec["path"] = f"{rel}/{prev.name}"
    return "ready"


def scene_preview(scene, cfg, w: int, h: int):
    """معاينة القضية: المشهد كاملًا في موضعه من حزام الرسم فوق لون العلامة."""
    from PIL import Image

    from . import imaging
    base = Image.new("RGBA", (w, h), (*imaging.hex_rgb(str(cfg.path("brand.primary_color") or "#12203A")), 255))
    al, at, ar, ab = area_px(cfg, w, h)
    x, y, pw, ph = canvas_box(scene.size, (al, at, ar, ab))
    base.alpha_composite(scene.resize((pw, ph), Image.LANCZOS), (x, y))
    return base.convert("RGB")


def canvas_box(size: tuple[int, int], area: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """موضع لوحة المشهد (x، y، عرض، ارتفاع) في المنطقة (دالة خالصة): أكبر مقياس يسعها، متوسطة أفقيًا وعلى أسفل المنطقة."""
    l, t, r, b = area
    cw, ch = max(int(size[0]), 1), max(int(size[1]), 1)
    sc = min((r - l) / cw, (b - t) / ch)
    pw, ph = max(int(round(cw * sc)), 2), max(int(round(ch * sc)), 2)
    return l + (r - l - pw) // 2, b - ph, pw, ph


def scene_cues(pieces: list[dict], title: str, times: list[float], fallback: float, cfg) -> list[float]:
    """زمن نزول كل طبقة (دالة خالصة): زمن كلمة نزولها في السؤال؛ قطعتان على كلمة واحدة تنزلان معًا، وكلمتان متلاصقتان تُفصلان بـ
    scene.min_gap بإزاحة اللاحقة للأمام لا للخلف (لا تظهر قطعة قبل كلمتها)؛ بلا كلمة ← fallback (بعد السؤال)."""
    from . import reel_figures
    gap = float(scfg(cfg).get("min_gap", 0.25))
    words = str(title or "").split()
    idx = []
    for p in pieces:
        j = reel_figures.mention_index(str(p.get("trigger_ar") or ""), title, cfg) if p.get("trigger_ar") else None
        idx.append(j if j is not None and len(times) == len(words) else None)
    at: dict[int, float] = {}
    last = None
    for j in sorted({j for j in idx if j is not None}):
        t = times[j] if last is None else max(times[j], last + gap)
        at[j] = last = t
    return [at[j] if j is not None else fallback for j in idx]


def scene_review_lines(rec: dict, cfg) -> list[str]:
    """سطور المشهد في قضية السيناريو: كل عنصر وكلمة نزوله وجهته، وكل علاقة وأساسها، وسبب التراجع إلى المشهد كاملًا إن وقع."""
    t = (ccfg(cfg).get("texts") or {})
    dirs = t.get("directions") or {"left": "من اليسار", "right": "من اليمين", "bottom": "من الأسفل"}
    out = []
    rd = rec.get("reading") or {}
    if rd.get("reading"):
        out.append("  <sub>" + str(t.get("reading", "👁️ يفهم المشاهد: {reading}")).format(reading=rd["reading"]) + "</sub>")
    for p in rec.get("pieces") or []:
        trig = p.get("trigger_ar") or t.get("no_trigger", "بعد السؤال")
        name = " + ".join([p.get("name_ar", "")] + list(p.get("merged") or []))
        out.append("  <sub>" + str(t.get("scene_piece", "⬇️ {name} ← عند «{trigger}» · {dir}")).format(
            name=name, trigger=trig, dir=dirs.get(p.get("enter", "bottom"), "")) + "</sub>")
    for L in rec.get("layers") or []:
        key = "layer_merged" if L.get("merged_into") else "layer_from_scene" if L.get("from_scene") else \
            "layer_dropped" if L.get("dropped") else ""
        if key:
            out.append("  <sub>" + str(t.get(key, "")).format(name=L.get("name_ar", ""), into=L.get("merged_into", "")) + "</sub>")
    for r in rec.get("relations") or []:
        out.append("  <sub>" + str(t.get("scene_relation", "🧵 {a} {verb} {b} ← الإجابة {basis}")).format(
            a=r.get("a_ar", ""), verb=r.get("verb_ar", ""), b=r.get("b_ar", ""),
            basis="، ".join(str(b) for b in r.get("basis") or []) or "—") + "</sub>")
    if rec.get("mode") == "whole":
        out.append("  <sub>" + str(t.get("scene_whole", "⚠️ تعذّر فصل العناصر فينزل المشهد كاملًا: {why}")).format(
            why=rec.get("scene_fallback", "")) + "</sub>")
    return out
