"""هوك «المواجهة» بورق الكوتشينة (قرار صاحب المشروع 8/11).

السبب: أول وجه بشري في الريلين المنشورين ظهر قرب الثانية 25، وقبله شعار كبير وصورة ثابتة أو كحلي ونص ينزل بصوت آلي، ونصف الريلات
افتتح بلا لقطة لأن بحث يوتيوب لم يجد شيئًا. أقوى ما في الريل وجوه المحللين وأصواتهم، ومقاطعهم منزَّلة أصلًا للوحة الإجابات. فالهوك
الآن جملتان قصيرتان من إجابتين معتمدتين لمتحدثَين من كتلتين مختلفتين، تُعرضان في ورقتي كوتشينة مروحةً تتبادلان الأمام، ثم عنوان
الهوك فوقهما بصوت الراوي.

قسمان: (1) الاختيار في مرحلة السيناريو `plan` — نداء نموذج واحد يقترح الأزواج والعلاقة وعنوان الهوك، والكود يقرّر: الجملة قطعة متصلة
حرفية من كلام المقطع الأصلي، وترجمتها قطعة متصلة حرفية من ترجمته المعتمدة، ومدتها في الحدود، والكتلتان مختلفتان، والعلاقة بترتيب
تفضيل صاحب المشروع (`reel.render.clash.relations`). (2) التركيب `render_scene` — المتحدث يجب أن يبقى بعد حرّاس القائل في التركيب
وموثَّقًا، وإلا تُعرض الورقة الباقية وحدها أو يعود الهوك القديم. لا بروكسي إضافي ولا بحث.
"""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

log = logging.getLogger(__name__)

RELATIONS = ("opposite", "same_words", "partial_opposite", "partial_agree")

_LINE = {
    "type": "object",
    "properties": {
        "point_id": {"type": "string"},
        "first_words": {"type": "string", "description": "أول 2–4 كلمات من الجملة حرفيًا بلغة الكلام الأصلية"},
        "last_words": {"type": "string", "description": "آخر 2–4 كلمات من الجملة حرفيًا بلغة الكلام الأصلية"},
        "text_ar": {"type": "string", "description": "ترجمة الجملة: قطعة متصلة حرفية من الترجمة العربية المعطاة للمقطع"},
    },
    "required": ["point_id", "first_words", "last_words", "text_ar"],
}

TOOL = {
    "name": "pick_clash",
    "description": "اختيار جملتين لافتتاح الريل وعلاقتهما وعنوان الهوك",
    "input_schema": {
        "type": "object",
        "properties": {
            "pairs": {"type": "array", "items": {
                "type": "object",
                "properties": {"a": _LINE, "b": _LINE, "relation": {"type": "string", "enum": list(RELATIONS)},
                               "why": {"type": "string"}},
                "required": ["a", "b", "relation"]}},
            "single": _LINE,
            "hook_text": {"type": "string"},
        },
        "required": ["pairs", "hook_text"],
    },
}


def ccfg(cfg) -> dict:
    return cfg.path("reel.render.clash") or {}


def enabled(cfg) -> bool:
    return bool(ccfg(cfg).get("enabled"))


def channel_bloc(scene: dict, cfg) -> str:
    """كتلة قناة المقطع من channels[].bloc؛ قناة غير معروفة كتلتها اسمها، فلا تُعدّ قناتان مجهولتان كتلة واحدة."""
    orig = (scene.get("channel_original") or "").strip()
    display = (scene.get("channel_display") or "").strip()
    for ch in cfg.get("channels") or []:
        if not isinstance(ch, dict):
            continue
        name = str(ch.get("name") or "").strip()
        names = {name, str(ch.get("name_ar") or "").strip()} - {""}
        if (orig and orig == name) or (display and display in names):
            return str(ch.get("bloc") or name)
    return "?" + (orig or display)


def candidates(script: dict, cfg) -> list[dict]:
    """مقاطع الإجابات في السيناريو بما يلزم الاختيار. المقدّم لا يدخل: الهوك صوت محلل."""
    from . import reel_script
    out, seen = [], set()
    for s in script.get("scenes") or []:
        if s.get("kind") not in reel_script.CLIP_KINDS or not s.get("point_id") or s["point_id"] in seen:
            continue
        if not (s.get("quote_original") or "").strip() or not (s.get("quote_arabic") or "").strip():
            continue
        seen.add(s["point_id"])
        out.append({"point_id": s["point_id"], "speaker": s.get("speaker_name") or s.get("speaker_text") or "",
                    "channel": s.get("channel_display", ""), "bloc": channel_bloc(s, cfg),
                    "quote_original": s.get("quote_original", ""), "quote_arabic": s.get("quote_arabic", ""),
                    "verified": bool(s.get("speaker_verified") and s.get("speaker_name"))})
    return out


def _norm(text: str) -> list[str]:
    from . import youtube_extract
    return youtube_extract._normalize_for_anchor(re.sub(r"[^\w\s]", " ", str(text or ""))).split()


def locate(text: str, first: str, last: str) -> tuple[int, int, int] | None:
    """(أول كلمة، آخر كلمة، عدد كلمات النص) لقطعة تبدأ بكلمات first وتنتهي بكلمات last في text بعد التطبيع؛ أول ظهور لـfirst ثم أول
    ظهور لـlast يبدأ عنده أو بعده. غياب أيهما ← None (لا تخمين: الجملة يجب أن تكون حرفيًا في الكلام)."""
    toks, f, la = _norm(text), _norm(first), _norm(last)
    if not toks or not f or not la:
        return None
    for i in range(len(toks) - len(f) + 1):
        if toks[i:i + len(f)] != f:
            continue
        for j in range(i, len(toks) - len(la) + 1):
            if toks[j:j + len(la)] == la:
                return i, j + len(la) - 1, len(toks)
        return None
    return None


def contiguous_in(part: str, whole: str) -> bool:
    """القطعة كلماتٌ متصلة من النص كله بعد التطبيع (التشكيل والهمزات والترقيم لا تمنع المطابقة)."""
    p, w = _norm(part), _norm(whole)
    if not p:
        return False
    return any(w[i:i + len(p)] == p for i in range(len(w) - len(p) + 1))


def check_line(line: dict, cands: dict, cfg) -> tuple[dict | None, str]:
    """يتحقق من جملة مقترحة ويعيد (السجل، "") أو (None، السبب)."""
    from . import youtube_bites
    c = ccfg(cfg)
    cand = cands.get(str((line or {}).get("point_id") or ""))
    if cand is None:
        return None, "مقطع ليس في السيناريو"
    loc = locate(cand["quote_original"], line.get("first_words", ""), line.get("last_words", ""))
    if loc is None:
        return None, "الجملة ليست حرفيًا في كلام المقطع"
    i, j, total = loc
    words = j - i + 1
    lo, hi = (float(x) for x in c.get("line_seconds", [1.5, 4.5]))
    secs = words / float(c.get("words_per_second", 2.6))
    if not lo <= secs <= hi:
        return None, f"مدة الجملة {secs:.1f} ث خارج [{lo:g}، {hi:g}]"
    text_ar = " ".join(str(line.get("text_ar") or "").split())
    if not contiguous_in(text_ar, cand["quote_arabic"]):
        return None, "ترجمة الجملة ليست قطعة من الترجمة المعتمدة"
    if not youtube_bites.screen_text_ok(text_ar, cfg):
        return None, "ترجمة لا تصلح للشاشة"
    original = " ".join(cand["quote_original"].split())
    return {"point_id": cand["point_id"], "first_words": line["first_words"], "last_words": line["last_words"],
            "text_ar": text_ar, "word_from": i, "word_to": j, "words_total": total, "est_seconds": round(secs, 2),
            "original_words": words, "channel": cand["channel"], "bloc": cand["bloc"], "speaker": cand["speaker"],
            "original": original}, ""


def hook_text_ok(text: str, cfg) -> bool:
    words = str(text or "").split()
    return 0 < len(words) <= int(ccfg(cfg).get("hook_text_max_words", 6)) and bool(re.search("[؀-ۿ]", text))


def decide(raw: dict, cands_list: list[dict], cfg) -> dict:
    """القرار في الكود من اقتراح النموذج (دالة خالصة): أول زوج صالح بترتيب العلاقات المفضَّل (relations)، وإلا الجملة الواحدة، وإلا
    خطأ. زوج صالح = جملتان صالحتان من مقطعين مختلفين لمتحدثين من كتلتين مختلفتين. عنوان الهوك المرفوض يُترك فارغًا فيُعرض السؤال الرئيس."""
    cands = {c["point_id"]: c for c in cands_list}
    order = [r for r in (ccfg(cfg).get("relations") or RELATIONS) if r in RELATIONS]
    rejected: list[str] = []
    pairs = [p for p in (raw or {}).get("pairs") or [] if isinstance(p, dict)]
    out: dict = {}
    for rel in order:
        for p in pairs:
            if p.get("relation") != rel:
                continue
            a, why_a = check_line(p.get("a") or {}, cands, cfg)
            b, why_b = check_line(p.get("b") or {}, cands, cfg)
            if a is None or b is None:
                rejected.append(why_a or why_b)
                continue
            if a["point_id"] == b["point_id"]:
                rejected.append("الجملتان من مقطع واحد")
                continue
            if a["bloc"] == b["bloc"]:
                rejected.append("الجملتان من كتلة واحدة")
                continue
            out = {"mode": "pair", "relation": rel, "why": " ".join(str(p.get("why") or "").split())[:200], "a": a, "b": b}
            break
        if out:
            break
    if not out:
        single, why = check_line((raw or {}).get("single") or {}, cands, cfg) if (raw or {}).get("single") else (None, "")
        if single is not None:
            out = {"mode": "single", "relation": "single", "a": single}
        else:
            if why:
                rejected.append(why)
            return {"error": "لا زوج ولا جملة صالحة", "rejected": rejected[:6]}
    ht = " ".join(str((raw or {}).get("hook_text") or "").split())
    out["hook_text"] = ht if hook_text_ok(ht, cfg) else ""
    if rejected:
        out["rejected"] = rejected[:6]
    return out


def user_message(script: dict, cands: list[dict], cfg) -> str:
    lines = [f"سؤال الريل: {script.get('title', '')}", "", "المقاطع:"]
    for c in cands:
        lines += [f"- point_id: {c['point_id']} · المتحدث: {c['speaker'] or 'غير مسمّى'} · القناة: {c['channel']} · الكتلة: {c['bloc']}",
                  f"  الكلام الأصلي: {c['quote_original']}", f"  الترجمة المعتمدة: {c['quote_arabic']}"]
    lo, hi = ccfg(cfg).get("line_seconds", [1.5, 4.5])
    wps = float(ccfg(cfg).get("words_per_second", 2.6))
    lines += ["", f"طول كل جملة بين {math.ceil(float(lo) * wps)} و{int(float(hi) * wps)} كلمة من الكلام الأصلي."]
    return "\n".join(lines)


def _create(client, **kw):
    """نقطة النداء (يستبدلها الاختبار)."""
    from . import llm
    return llm.create(client, **kw)


def plan(draft: dict, cfg, client=None) -> None:
    """يملأ draft["hook_clash"] بعد سيناريو جاهز؛ لا يرفع أبدًا ولا يُسقط سيناريو صالحًا."""
    if not enabled(cfg):
        return
    script = draft.get("script") or {}
    cands = [c for c in candidates(script, cfg) if c["verified"]] if ccfg(cfg).get("verified_only", True) else candidates(script, cfg)
    if not cands:
        draft["hook_clash"] = {"error": "لا مقطع لمتحدث موثَّق"}
        return
    try:
        if client is None:
            from anthropic import Anthropic
            from .config import env
            client = Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
        c = ccfg(cfg)
        resp = _create(client, cfg=cfg, model=c.get("model", "claude-sonnet-5"), max_tokens=int(c.get("max_tokens", 2000)),
                       system=str(c.get("system", "")), tools=[TOOL], tool_choice={"type": "tool", "name": TOOL["name"]},
                       messages=[{"role": "user", "content": user_message(script, cands, cfg)}])
        if resp is None:
            return
        if getattr(resp, "stop_reason", "") == "max_tokens":
            draft["hook_clash"] = {"error": "رد مقطوع"}
            return
        raw = next((b.input for b in getattr(resp, "content", []) or [] if getattr(b, "type", "") == "tool_use"), None)
        if not isinstance(raw, dict):
            draft["hook_clash"] = {"error": "لا رد بالأداة"}
            return
        draft["hook_clash"] = decide(raw, cands, cfg)
    except Exception as exc:  # noqa: BLE001 -- الهوك تحسين: يعود الهوك القديم
        log.warning("تعذّر اختيار هوك المواجهة: %s", str(exc)[:150])
        draft["hook_clash"] = {"error": str(exc)[:150]}


def review_lines(draft: dict, cfg) -> list[str]:
    """سطور المرحلة 2: الجملتان بعلاقتهما وعنوان الهوك، أو سبب العودة إلى الهوك القديم."""
    hc = draft.get("hook_clash")
    if not isinstance(hc, dict) or not hc:
        return []
    t = cfg.path("reel.texts.clash") or {}
    if hc.get("error"):
        return [t.get("none", "🃏 لا هوك مواجهة ({reason}) — الهوك القديم").format(reason=hc["error"])]
    rel = (t.get("relations") or {}).get(hc.get("relation"), hc.get("relation", ""))
    out = [t.get("head", "🃏 هوك المواجهة: {relation}").format(relation=rel)]
    for k in ("a", "b"):
        x = hc.get(k)
        if isinstance(x, dict):
            out.append(t.get("line", "  {channel}: «{text}»").format(channel=x.get("channel", ""), text=x.get("text_ar", "")))
    if hc.get("hook_text"):
        out.append(t.get("hook_text", "  العنوان: {text}").format(text=hc["hook_text"]))
    return out


# ───────────────────────────── التركيب ─────────────────────────────

def timeline(da: float, db: float | None, speech: float, cfg) -> dict:
    """أزمنة المشهد (دالة خالصة): دخول الأوراق، المقطع الأول، التبديل، الثاني، ثم نزول الأوراق وعنوان الهوك بصوت الراوي."""
    c = ccfg(cfg)
    a0 = float(c.get("audio_at", 0.2))
    a1 = a0 + da
    if db is None:
        b0 = b1 = swap0 = swap1 = a1
    else:
        swap0, swap1 = a1, a1 + float(c.get("swap", 0.5))
        b0, b1 = swap1, swap1 + db
    q = c.get("question") or {}
    q0 = b1
    voice_at = q0 + float(q.get("settle", 0.4))
    total = voice_at + speech + float(q.get("tail", 0.7))
    return {"a0": a0, "a1": a1, "swap0": swap0, "swap1": swap1, "b0": b0, "b1": b1, "q0": q0, "voice_at": voice_at,
            "total": round(total, 3), "pair": db is not None}


def _ease(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def _lerp(p, q, t):
    return tuple(a + (b - a) * t for a, b in zip(p, q))


def poses(t: float, tl: dict, cfg) -> list[tuple[str, float, float, float, float, float]]:
    """(الورقة، x، y، الزاوية، المقياس، التعتيم) بترتيب الرسم (الأخير فوق) عند الزمن t (دالة خالصة). الأمامية تخرج يمينًا ثم تنزلق
    خلف الأخرى في نصف التبديل الثاني، كما تُقلب ورقة في اليد."""
    c = ccfg(cfg)
    fan = c.get("fan") or {}
    front, back, out = (tuple(float(v) for v in fan[k]) for k in ("front", "back", "out"))
    dim = float((c.get("card") or {}).get("dim", 0.5))
    k = _ease(t / float(c.get("enter", 0.35)))
    rise = (1 - k) * float(c.get("enter_px", 900))
    q = c.get("question") or {}
    s = _ease((t - tl["q0"]) / float(q.get("settle", 0.4))) if t > tl["q0"] else 0.0
    scale = 1 - (1 - float(q.get("shrink", 0.78))) * s
    drop = float(q.get("drop", 130)) * s
    if not tl["pair"]:
        single = (float(c.get("single_x", 540)), front[1], float(c.get("single_angle", -3)))
        return [("a", single[0], single[1] + rise + drop, single[2], scale, 0.0)]
    if t < tl["swap0"]:
        pa, pb, da, db, order = front, back, 0.0, dim, ("b", "a")
    elif t < tl["swap1"]:
        u = (t - tl["swap0"]) / (tl["swap1"] - tl["swap0"])
        pb, db = _lerp(back, front, _ease(u)), dim * (1 - _ease(u))
        pa = _lerp(front, out, _ease(u * 2)) if u < 0.5 else _lerp(out, back, _ease(u * 2 - 1))
        da = dim * _ease(u)
        order = ("b", "a") if u < 0.5 else ("a", "b")
    else:
        pa, pb, da, db, order = back, front, dim, 0.0, ("a", "b")
    ps = {"a": (pa, da), "b": (pb, db)}
    return [(n, ps[n][0][0], ps[n][0][1] + rise + drop, ps[n][0][2], scale, ps[n][1]) for n in order]


def span_times(clip: dict, line: dict, cfg) -> tuple[float, float, str]:
    """(بداية، نهاية) الجملة بثواني ملف المقطع المنزَّل، ومصدرها: «words» من كلمات التفريغ المطابَقة (Q13)، وإلا «estimate» بموضع
    الجملة من كلمات الاقتباس على نافذة الكلام المسموع. الهامشان من clash.pad."""
    from . import reel_clips
    c = ccfg(cfg)
    pad0, pad1 = (float(x) for x in c.get("pad", [0.15, 0.3]))
    trim = clip.get("trim") or (0.0, float(clip.get("seconds") or 0))
    t0 = t1 = None
    source = "estimate"
    segs = clip.get("segs") or []
    if clip.get("sync") == "words" and len(segs) > 1 and clip.get("wstart") is not None:
        off = float(clip["wstart"]) - float(trim[0])        # ثانية الفيديو التي يقابلها صفر الملف
        words = [(float(segs[k][0]) - off, float(segs[k + 1][0]) - off, str(segs[k][1])) for k in range(len(segs) - 1)
                 if str(segs[k][1]).strip()]
        res = reel_clips.align_quote(" ".join(line["original"].split()[line["word_from"]:line["word_to"] + 1]), words, cfg)
        if res:
            t0, t1, source = float(res["t0"]), float(res["t1"]), "words"
    if t0 is None:
        g = clip.get("gate") or {}
        ws = float(trim[0]) + float(g.get("start", 0.0))
        we = float(trim[0]) + float(g.get("end", clip.get("seconds") or 0))
        total = max(int(line["words_total"]), 1)
        t0 = ws + (we - ws) * line["word_from"] / total
        t1 = ws + (we - ws) * (line["word_to"] + 1) / total
    lo = 0.0
    hi = float(trim[1]) if trim and trim[1] else t1 + pad1
    return max(t0 - pad0, lo), min(t1 + pad1, hi), source


def _font(path: str, size: int, weight):
    from . import imaging
    return imaging.load_font(path, size, weight)


def _text_w(d, text, font) -> float:
    from . import imaging
    return d.textlength(imaging._prepare(text), font=font, **imaging._kwargs())


def _fit_line(d, text, path, weight, size, minimum, max_w):
    while size > minimum and _text_w(d, text, _font(path, size, weight)) > max_w:
        size -= 2
    f = _font(path, size, weight)
    return f if _text_w(d, text, f) <= max_w else None


def card_base(scene: dict, cfg) -> Image.Image:
    """الورقة بلا الفيديو: لون الورق وحوافه المدوّرة وإطار مكان الفيديو، ومعلومات شريط المحلل تحت الفيديو وحدها (قرار صاحب المشروع
    8/11: أعلى الورقة بلا معلومات فهامشه صغير، وأسفلها أوسع لثلاثة أسطر): الاسم ورسمه الأجنبي، الصفة، القناة وتوجّهها."""
    from . import imaging, reel_render
    c = ccfg(cfg)
    k = c.get("card") or {}
    w, h, m, vh = int(k["width"]), int(k["height"]), int(k["margin"]), int(k["video_height"])
    paper = imaging.hex_rgb(k.get("color", "#FAF8F2"))
    navy = imaging.hex_rgb(cfg.path("brand.primary_color"))
    gold = imaging.hex_rgb(cfg.path("brand.accent_color"))
    grey = tuple(int(x) for x in k.get("grey", [96, 104, 120]))
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], int(k.get("radius", 34)), fill=paper + (255,))
    d.rectangle([m - 3, m - 3, w - m + 2, m + vh + 2], fill=navy + (255,))
    info = c.get("info") or {}
    right, left = w - m, m
    fonts = cfg.path("reel.render.fonts")
    ys = [m + vh + int(info.get("top_gap", 34))]
    name = scene.get("speaker_name", "") if scene.get("speaker_verified") else ""
    latin = (scene.get("speaker_name_latin") or "").strip() if name else ""
    role = reel_render.band_role(scene.get("speaker_role", "")) if name else ""
    ch_ar, ch_lat = reel_render.band_channel_parts(scene, cfg)
    orient = reel_render.band_orientation(scene, cfg)
    rows = []
    if name:
        rows.append((name, latin, "", int(info.get("name_size", 50)), "display", navy))
    if role:
        rows.append((role, "", "", int(info.get("role_size", 36)), "body", grey))
    rows.append((ch_ar or ch_lat, ch_lat if ch_ar else "", orient, int(info.get("channel_size", 34)), "body", navy))
    y = ys[0]
    for ar, lat, ori, size, kind, color in rows:
        if not ar:
            continue
        path, weight = reel_render.face(cfg, ar, kind)
        minimum = int(size * 0.7)
        extra = (" " + lat if lat else "") + (f" ({ori})" if ori else "")
        f = _fit_line(d, ar + extra, path, weight, size, minimum, right - left)
        if f is None:
            lat, ori, extra = "", "", ""
            f = _fit_line(d, ar, path, weight, size, minimum, right - left)
            if f is None:
                continue
        imaging.draw_text(d, (right, y), ar, f, color, anchor="ra")
        x = right - _text_w(d, ar, f) - 14
        if lat:
            lf = reel_render.pick_font(lat, fonts["latin"], f.size, None)
            if lf is not None:
                d.text((x, y), lat, font=lf, fill=gold, anchor="ra")
                x -= d.textlength(lat, font=lf) + 14
        if ori:
            of = _font(path, max(int(f.size * 0.8), 20), weight)
            imaging.draw_text(d, (x, y + int(f.size * 0.12)), f"({ori})", of, grey, anchor="ra")
        y += int(size * float(info.get("line_factor", 1.5)))
    return img


def caption_layer(text: str, shown: int, cfg) -> Image.Image | None:
    """شريط الترجمة أسفل مكان الفيديو: الأسطر من النص كله (فلا تقفز الكلمات حين تُضاف)، وفي كل سطر أول كلماته الظاهرة من اليمين."""
    from . import imaging, reel_render
    c = ccfg(cfg)
    k, cap = c.get("card") or {}, c.get("caption") or {}
    vw = int(k["width"]) - 2 * int(k["margin"])
    words = text.split()
    if shown <= 0 or not words:
        return None
    path, weight = reel_render.face(cfg, text, "body")
    size = int(cap.get("size", 44))
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    font = _font(path, size, weight)
    lines = imaging.wrap(probe, text, font, vw - 2 * int(cap.get("pad", 22)))
    while len(lines) > int(cap.get("max_lines", 2)) and size > int(cap.get("min_size", 30)):
        size -= 2
        font = _font(path, size, weight)
        lines = imaging.wrap(probe, text, font, vw - 2 * int(cap.get("pad", 22)))
    lh = int(size * 1.45)
    bh = lh * len(lines) + 2 * int(cap.get("pad_y", 14))
    navy = imaging.hex_rgb(cfg.path("brand.primary_color"))
    img = Image.new("RGBA", (vw, bh), navy + (int(255 * float(cap.get("alpha", 0.72))),))
    d = ImageDraw.Draw(img)
    left = shown
    for j, ln in enumerate(lines):
        toks = ln.split()
        part = " ".join(toks[:max(min(left, len(toks)), 0)])
        left -= len(toks)
        if part:
            imaging.draw_text(d, (vw - int(cap.get("pad", 22)), int(cap.get("pad_y", 14)) + j * lh), part, font,
                              (255, 255, 255), anchor="ra")
    return img


class _Card:
    """ورقة واحدة: قاعدتها وإطارات فيديو جملتها (JPEG) ونص ترجمتها وزمن عرضها."""

    def __init__(self, scene: dict, frames: list[Path], text: str, start: float, seconds: float, cfg):
        k = ccfg(cfg).get("card") or {}
        self.base = card_base(scene, cfg)
        self.frames = frames
        self.text = text
        self.start, self.seconds = start, seconds
        self.m, self.vw, self.vh = int(k["margin"]), int(k["width"]) - 2 * int(k["margin"]), int(k["video_height"])
        self._cache: dict = {}
        self.cfg = cfg

    def frame_at(self, t: float) -> Path:
        fps = float(self.cfg.path("reel.render.fps"))
        idx = int((t - self.start) * fps)
        return self.frames[min(max(idx, 0), len(self.frames) - 1)]

    def shown_at(self, t: float) -> int:
        n = len(self.text.split())
        if t < self.start:
            return 0
        return min(n, int((t - self.start) / max(self.seconds * 0.9, 0.1) * n) + 1)

    def image(self, t: float) -> Image.Image:
        f, shown = self.frame_at(t), self.shown_at(t)
        key = (str(f), shown)
        if key in self._cache:
            return self._cache[key]
        img = self.base.copy()
        v = Image.open(f).convert("RGB").resize((self.vw, self.vh))
        img.paste(v, (self.m, self.m))
        cap = caption_layer(self.text, shown, self.cfg)
        if cap is not None:
            img.alpha_composite(cap, (self.m, self.m + self.vh - cap.height))
        self._cache = {key: img}
        return img


def _place(canvas: Image.Image, card: Image.Image, cx: float, cy: float, ang: float, scale: float, dim: float, navy,
           shadows: dict) -> None:
    im = card if abs(scale - 1) < 1e-3 else card.resize((int(card.width * scale), int(card.height * scale)))
    if dim > 0.01:
        im = im.copy()
        veil = Image.new("RGBA", im.size, navy + (int(255 * dim),))
        veil.putalpha(Image.eval(im.getchannel("A"), lambda a, dd=dim: int(a * dd)))
        im.alpha_composite(veil)
    r = im.rotate(ang, resample=Image.BICUBIC, expand=True)
    key = (round(ang, 1), round(scale, 2))
    sh = shadows.get(key)
    if sh is None:
        sh = Image.new("RGBA", r.size, (0, 0, 0, 0))
        sh.putalpha(r.getchannel("A").point(lambda a: int(a * 0.55)))
        sh = sh.filter(ImageFilter.GaussianBlur(22))
        shadows[key] = sh
    canvas.alpha_composite(sh, (int(cx - r.width / 2 + 16), int(cy - r.height / 2 + 26)))
    canvas.alpha_composite(r, (int(cx - r.width / 2), int(cy - r.height / 2)))


def draw_frames(cards: dict, tl: dict, cfg, out_dir: Path) -> int:
    """إطارات المشهد JPEG (الخلفية من فيديو الورقة النشطة مموّهة تحت كحلي، ثم الورقتان بأوضاعهما)؛ يعيد عددها."""
    from . import imaging
    rc = cfg.path("reel.render")
    w, h, fps = int(rc["width"]), int(rc["height"]), float(rc["fps"])
    c = ccfg(cfg)
    navy = imaging.hex_rgb(cfg.path("brand.primary_color"))
    shadows: dict = {}
    n = max(int(math.ceil(tl["total"] * fps)), 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        t = i / fps
        active = cards["b"] if ("b" in cards and t >= (tl["swap0"] + tl["swap1"]) / 2) else cards["a"]
        small = Image.open(active.frame_at(t)).convert("RGB").resize((w // 8, h // 8))
        bg = small.filter(ImageFilter.GaussianBlur(float(c.get("bg_blur", 3)))).resize((w, h)).convert("RGBA")
        bg.alpha_composite(Image.new("RGBA", (w, h), navy + (int(255 * float(c.get("bg_dim", 0.78))),)))
        for name, x, y, ang, sc, dim in poses(t, tl, cfg):
            if name in cards:
                _place(bg, cards[name].image(t), x, y, ang, sc, dim, navy, shadows)
        bg.convert("RGB").save(out_dir / f"{i:05d}.jpg", quality=int(c.get("jpeg_quality", 90)))
    return n


def render_scene(i: int, scene: dict, script: dict, draft: dict, clips: dict, cfg, deps, tmp: Path, out: Path, notes: list,
                 voice: str, crops: dict | None, hook_info: dict | None = None) -> float | None:
    """مشهد هوك المواجهة؛ None ← لا يصلح (لا ورقة لمتحدث موثَّق بعد حرّاس التركيب) فيعود الهوك القديم. يرفع عند عطل التركيب نفسه
    ويلتقطه المستدعي فيعود الهوك القديم أيضًا."""
    from . import reel_render as rr
    hc = draft.get("hook_clash")
    if not enabled(cfg) or not isinstance(hc, dict) or hc.get("error") or not isinstance(hc.get("a"), dict):
        return None
    c, rc = ccfg(cfg), cfg.path("reel.render")
    fps = rc["fps"]
    idx = {s.get("point_id"): j for j, s in enumerate(script.get("scenes") or [])
           if s.get("kind") in ("clip", "cold_open_clip") and s.get("point_id")}
    lines = []
    for k in ("a", "b"):
        x = hc.get(k)
        j = idx.get((x or {}).get("point_id"))
        if not isinstance(x, dict) or j is None or j not in clips:
            continue
        sc = script["scenes"][j]
        if c.get("verified_only", True) and not (sc.get("speaker_verified") and sc.get("speaker_name")):
            continue
        lines.append((x, j, sc))
    if not lines:
        return None
    k = c.get("card") or {}
    vw, vh = int(k["width"]) - 2 * int(k["margin"]), int(k["video_height"])
    rate = rc.get("audio_rate", 48000)
    parts_meta, spans = [], []
    for n, (x, j, sc) in enumerate(lines):
        clip = clips[j]
        t0, t1, src = span_times(clip, x, cfg)
        crop = rr._prepare_crop(clip, cfg, deps, sc, None)
        _, cexpr = rr._panel_crops(clip, crop, sc, None, None, (0, 0, vw, vh), cfg, deps, [])
        fdir = tmp / f"clash_{i}_{n}"
        fdir.mkdir(parents=True, exist_ok=True)
        deps.run(rr._base("-ss", rr._fmt(t0), "-t", rr._fmt(t1 - t0), "-i", str(clip["file"]),
                          "-vf", f"{cexpr},scale={vw}:{vh},fps={fps}", "-q:v", "3", str(fdir / "%04d.jpg")))
        wav = tmp / f"clash_{i}_{n}.wav"
        fade = float(c.get("audio_fade", 0.08))
        deps.run(rr._base("-ss", rr._fmt(t0), "-t", rr._fmt(t1 - t0), "-i", str(clip["file"]), "-vn",
                          "-af", f"aresample={rate},aformat=channel_layouts=stereo,{rr._loudnorm(cfg)},"
                                 f"afade=t=in:d={fade},afade=t=out:st={rr._fmt(max(t1 - t0 - fade, 0))}:d={fade}",
                          str(wav)))
        frames = sorted(fdir.glob("*.jpg"))
        if not frames:
            raise RuntimeError("لم تُستخرج إطارات ورقة المواجهة")
        spans.append((frames, wav, round(t1 - t0, 3), x, sc))
        parts_meta.append({"point_id": x["point_id"], "t0": round(t0, 2), "t1": round(t1, 2), "sync": src})
    title = hc.get("hook_text") or script.get("title") or scene.get("text", "")
    audio, parts = rr._speech(title, voice, cfg, deps, tmp, f"s{i:02d}")
    speech = sum(d for _, d in parts)
    tl = timeline(spans[0][2], spans[1][2] if len(spans) > 1 else None, speech, cfg)
    cards = {"a": _Card(spans[0][4], spans[0][0], spans[0][3]["text_ar"], tl["a0"], spans[0][2], cfg)}
    if len(spans) > 1:
        cards["b"] = _Card(spans[1][4], spans[1][0], spans[1][3]["text_ar"], tl["b0"], spans[1][2], cfg)
    vdir = tmp / f"clash_{i}_frames"
    draw_frames(cards, tl, cfg, vdir)
    if hook_info is not None:
        # الإعادة المتصلة: الختام يجمّد أول إطار هنا (الخلفية قبل دخول الأوراق) ويقترب منه حتى التكبير 1.0
        hook_info.update(mode="image", bgpng=vdir / "00000.jpg", x0=0.0)
    times = rr.narration_word_times(parts, tl["voice_at"], cfg)
    if len(times) != len(title.split()):
        times = rr.narration_word_times([(title, speech)], tl["voice_at"], cfg)
    q = c.get("question") or {}
    wframes = rr.word_drop_frames(cfg, title, times, tl["total"], int(q.get("top", 330)), tmp, f"cw{i}",
                                  size_key=str(q.get("size_key", "clash")))
    lst = tmp / f"clash_{i}_words.txt"
    lst.write_text("".join(f"file '{f}'\nduration {rr._fmt(d)}\n" for f, d in wframes) + f"file '{wframes[-1][0]}'\n",
                   encoding="utf-8")
    inputs = ["-framerate", str(fps), "-i", str(vdir / "%05d.jpg"), "-f", "concat", "-safe", "0", "-i", str(lst)]
    alab, af = [], []
    starts = [tl["a0"]] + ([tl["b0"]] if len(spans) > 1 else [])
    for n, (sp, st) in enumerate(zip(spans, starts)):
        inputs += ["-i", str(sp[1])]
        af.append(f"[{2 + n}:a]adelay={int(round(st * 1000))}:all=1,apad[c{n}]")
        alab.append(f"[c{n}]")
    inputs += ["-i", str(audio)]
    vi = 2 + len(spans)
    af.append(f"[{vi}:a]aresample={rate},aformat=channel_layouts=stereo,adelay={int(round(tl['voice_at'] * 1000))}:all=1,apad[nv]")
    alab.append("[nv]")
    graph = (f"[1:v]fps={fps},format=rgba[t];[0:v]format=rgba[b];[b][t]overlay=0:0:shortest=1,format=yuv420p[v];"
             + ";".join(af) + f";{''.join(alab)}amix=inputs={len(alab)}:normalize=0:duration=longest[a]")
    deps.run(rr._base(*inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-t", rr._fmt(tl["total"]),
                      *rr._enc(rc), str(out)))
    if crops is not None:
        crops["clash"] = {"mode": "pair" if len(spans) > 1 else "single", "relation": hc.get("relation"),
                          "cards": parts_meta, "hook_text": title, "seconds": tl["total"]}
    t = cfg.path("reel.render.texts")
    names = "، ".join(sp[4].get("channel_display", "") for sp in spans)
    rel = (cfg.path("reel.texts.clash.relations") or {}).get(hc.get("relation"), "")
    tpl = t.get("comment_clash" if len(spans) > 1 else "comment_clash_single") or ""
    if tpl:
        notes.append(tpl.format(channels=names, relation=rel))
    if any(p["sync"] != "words" for p in parts_meta) and t.get("comment_clash_estimate"):
        notes.append(t["comment_clash_estimate"])
    return tl["total"]

