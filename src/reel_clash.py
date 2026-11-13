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
        if s.get("role") == "context":     # أطراف الحدث في السياق لا يواجَهون بالمحللين (12/11)
            continue
        if not (s.get("quote_original") or "").strip() or not (s.get("quote_arabic") or "").strip():
            continue
        seen.add(s["point_id"])
        out.append({"point_id": s["point_id"], "speaker": s.get("speaker_name") or s.get("speaker_text") or "",
                    "channel": s.get("channel_display", ""), "bloc": channel_bloc(s, cfg),
                    "quote_original": s.get("quote_original", ""), "quote_arabic": s.get("quote_arabic", ""),
                    "language": str(s.get("language") or ""),
                    "verified": bool(s.get("speaker_verified") and s.get("speaker_name"))})
    return out


def _norm(text: str) -> list[str]:
    from . import youtube_extract
    return youtube_extract._normalize_for_anchor(re.sub(r"[^\w\s]", " ", str(text or ""))).split()


def _token_map(text: str) -> tuple[list[str], list[str], list[int]]:
    """(الكلمات كما كُتبت، الكلمات المطبَّعة، رقم الكلمة المكتوبة لكل مطبَّعة): التطبيع قد يقسم كلمة («U.S.» ← «u s») فلا تُقتطع
    الجملة بأرقام المطبَّعة من النص المكتوب مباشرة."""
    raw = str(text or "").split()
    norm, owner = [], []
    for k, w in enumerate(raw):
        for t in _norm(w):
            norm.append(t)
            owner.append(k)
    return raw, norm, owner


def locate(text: str, first: str, last: str) -> tuple[int, int, int] | None:
    """(أول كلمة، آخر كلمة، عدد الكلمات) بأرقام الكلمات المكتوبة في text لقطعة تبدأ بكلمات first وتنتهي بكلمات last بعد التطبيع؛
    أول ظهور لـfirst ثم أول ظهور لـlast يبدأ عنده أو بعده. غياب أيهما ← None (لا تخمين: الجملة يجب أن تكون حرفيًا في الكلام)."""
    raw, toks, owner = _token_map(text)
    f, la = _norm(first), _norm(last)
    if not toks or not f or not la:
        return None
    for i in range(len(toks) - len(f) + 1):
        if toks[i:i + len(f)] != f:
            continue
        for j in range(i, len(toks) - len(la) + 1):
            if toks[j:j + len(la)] == la:
                return owner[i], owner[j + len(la) - 1], len(raw)
        return None
    return None


def contiguous_in(part: str, whole: str) -> bool:
    """القطعة كلماتٌ متصلة من النص كله بعد التطبيع (التشكيل والهمزات والترقيم لا تمنع المطابقة)."""
    p, w = _norm(part), _norm(whole)
    if not p:
        return False
    return any(w[i:i + len(p)] == p for i in range(len(w) - len(p) + 1))


def is_arabic_speech(cand: dict, cfg) -> bool:
    """المتكلم يتكلم العربية: لغة المقطع «ar»، أو بلا لغة وكلامه الأصلي عربي."""
    from . import youtube_bites
    lang = (cand.get("language") or "").lower()
    if lang:
        return lang.startswith("ar")
    return youtube_bites.is_arabic_text(cand.get("quote_original", ""), cfg)


def check_line(line: dict, cands: dict, cfg) -> tuple[dict | None, str]:
    """يتحقق من جملة مقترحة ويعيد (السجل، "") أو (None، السبب). ما يُكتب على الشاشة هو ما يُسمع بالضبط (قرار صاحب المشروع 8/11):
    متكلم بالعربية ← كلماته نفسها من كلامه الأصلي (والترجمة المعتمدة إن طابقتها بعد التطبيع لأنها بترقيمها)؛ متكلم بغيرها ← ترجمة
    القطعة نفسها، قطعةً متصلة حرفية من ترجمته المعتمدة."""
    from . import youtube_bites
    c = ccfg(cfg)
    cand = cands.get(str((line or {}).get("point_id") or ""))
    if cand is None:
        return None, "مقطع ليس في السيناريو"
    loc = locate(cand["quote_original"], line.get("first_words", ""), line.get("last_words", ""))
    if loc is None:
        return None, "الجملة ليست حرفيًا في كلام المقطع"
    i, j, total = loc
    raw = cand["quote_original"].split()
    sub = " ".join(raw[i:j + 1])
    words = j - i + 1
    lo, hi = (float(x) for x in c.get("line_seconds", [1.5, 4.5]))
    secs = words / float(c.get("words_per_second", 2.6))
    if not lo <= secs <= hi:
        return None, f"مدة الجملة {secs:.1f} ث خارج [{lo:g}، {hi:g}]"
    text_ar = " ".join(str(line.get("text_ar") or "").split())
    arabic = is_arabic_speech(cand, cfg)
    if arabic:
        shown = text_ar if text_ar and _norm(text_ar) == _norm(sub) else sub
    else:
        if not contiguous_in(text_ar, cand["quote_arabic"]):
            return None, "ترجمة الجملة ليست قطعة من الترجمة المعتمدة"
        shown = text_ar
    if not youtube_bites.screen_text_ok(shown, cfg):
        return None, "نص لا يصلح للشاشة"
    return {"point_id": cand["point_id"], "first_words": line["first_words"], "last_words": line["last_words"],
            "text_ar": shown, "sub_original": sub, "arabic": arabic, "word_from": i, "word_to": j, "words_total": total,
            "est_seconds": round(secs, 2), "original_words": words, "channel": cand["channel"], "bloc": cand["bloc"],
            "speaker": cand["speaker"]}, ""


def hook_text_ok(text: str, cfg) -> bool:
    words = str(text or "").split()
    return 0 < len(words) <= int(ccfg(cfg).get("hook_text_max_words", 6)) and bool(re.search("[؀-ۿ]", text))


def decide(raw: dict, cands_list: list[dict], cfg) -> dict:
    """القرار في الكود من اقتراح النموذج (دالة خالصة): أول زوج صالح بترتيب العلاقات المفضَّل (relations)، وإلا الجملة الواحدة، وإلا
    خطأ. زوج صالح = جملتان صالحتان من مقطعين مختلفين لمتحدثين من كتلتين مختلفتين. عنوان الهوك المرفوض يُترك فارغًا فيُعرض السؤال الرئيس."""
    cands = {c["point_id"]: c for c in cands_list}
    order = [r for r in (ccfg(cfg).get("relations") or RELATIONS) if r in RELATIONS]
    from .llm import tool_json
    rejected: list[str] = []
    raw = dict(raw or {})
    # الأزواج وأجزاؤها قد تصل نصًا JSON (أداة متداخلة)، فتبدو فارغة ويسقط الهوك بلا سبب مرفوض (ريل 12/11)
    pairs = []
    for p in tool_json(raw.get("pairs"), list) or []:
        p = tool_json(p, dict)
        if p:
            pairs.append({**p, "a": tool_json(p.get("a"), dict) or {}, "b": tool_json(p.get("b"), dict) or {}})
    raw["single"] = tool_json(raw.get("single"), dict)
    out: dict = {}
    # علاقة خارج القائمة كانت تُتخطّى بصمت فيخرج «لا زوج» بلا سبب مرفوض
    for p in pairs:
        if p.get("relation") not in order:
            rejected.append(f"علاقة غير معروفة: {str(p.get('relation'))[:30]}")
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
            # شكل الرد بلا كلام المتحدثين (المسودة في المستودع العام): ما يلزم لمعرفة لماذا لم يبقَ شيء
            shape = {"pairs": len(pairs), "relations": sorted({str(p.get("relation")) for p in pairs}),
                     "single": bool(raw.get("single")), "pairs_type": type(raw.get("pairs")).__name__}
            return {"error": "لا زوج ولا جملة صالحة", "rejected": rejected[:6], "shape": shape}
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
    """أزمنة المشهد (دالة خالصة): دخول الأوراق، المقطع الأول، التبديل، الثاني، ثم نزول الأوراق وعنوان الهوك بصوت الراوي.
    الورقة الثانية تبدأ قبل نهاية التبديل بقليل (swap_lead) كي لا يُرى سكون بين الصوتين."""
    c = ccfg(cfg)
    a0 = float(c.get("audio_at", 0.2))
    a1 = a0 + da
    if db is None:
        b0 = b1 = swap0 = swap1 = a1
    else:
        swap0, swap1 = a1, a1 + float(c.get("swap", 0.6))
        b0 = swap1 - min(float(c.get("swap_lead", 0.1)), swap1 - swap0)
        b1 = b0 + db
    q = c.get("question") or {}
    q0 = b1
    voice_at = q0 + float(q.get("settle", 0.45))
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
    k = _ease(t / float(c.get("enter", 0.45)))
    rise = (1 - k) * float(c.get("enter_px", 1100))
    q = c.get("question") or {}
    s = _ease((t - tl["q0"]) / float(q.get("settle", 0.45))) if t > tl["q0"] else 0.0
    scale = 1 - (1 - float(q.get("shrink", 0.82))) * s
    drop = float(q.get("drop", 40)) * s
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


def span_times(clip: dict, line: dict, cfg) -> tuple[float, float, list] | None:
    """(بداية، نهاية، كلمات الجملة [(بداية، نهاية، كلمة)]) بثواني ملف المقطع المنزَّل، أو None. الحدّان من كلمات الملف المسموعة
    (clip["heard"]، يملؤها ضبط Q13): الصوت يبدأ قبل أول كلمة بـpad[0] ويقف بعد آخرها بـpad[1]، ولا يدخل الهامش في كلمة مجاورة
    (يقف قبلها بـneighbor_gap) — فلا تُسمع كلمة لا تُكتب (قرار صاحب المشروع 8/11). بلا كلمات مسموعة أو لم تطابق الجملة ← None: لا
    ضمان للتطابق فلا تُعرض الجملة."""
    from . import reel_clips
    c = ccfg(cfg)
    heard = [(float(w[0]), float(w[1]), str(w[2])) for w in clip.get("heard") or [] if str(w[2]).strip()]
    if not heard:
        return None
    res = reel_clips.align_quote(line.get("sub_original", ""), heard, cfg)
    if not res or not res.get("words"):
        return None
    span = res["words"]
    a = next((k for k, w in enumerate(heard) if abs(w[0] - span[0][0]) < 1e-6 and w[2] == span[0][2]), None)
    b = a + len(span) - 1 if a is not None else None
    pad0, pad1 = (float(x) for x in c.get("pad", [0.08, 0.12]))
    gap = float(c.get("neighbor_gap", 0.02))
    t0, t1 = float(span[0][0]) - pad0, float(span[-1][1]) + pad1
    if a is not None and a > 0:
        t0 = max(t0, heard[a - 1][1] + gap)
    if b is not None and b + 1 < len(heard):
        t1 = min(t1, heard[b + 1][0] - gap)
    # الحدّ لا يقطع الكلمة نفسها ولو تلاصقت بجارتها في التفريغ
    t0 = max(min(t0, float(span[0][0])), 0.0)
    t1 = max(t1, float(span[-1][1]))
    return round(t0, 3), round(t1, 3), span


def caption_times(line: dict, span: list, t0: float, start: float, cfg) -> list[float]:
    """زمن ظهور كل كلمة من نص الشاشة (دالة خالصة) بثواني المشهد: start بداية الورقة وt0 بداية جملتها في الملف. متكلم بالعربية ←
    كل كلمة مع نطقها (عدد الكلمات المكتوبة يساوي المسموعة غالبًا، وإلا يُوزَّع بالتناسب على الكلمات المسموعة)؛ متكلم بغيرها ← السطر كله
    عند أول كلمة تُسمع، لأن ترتيب كلمات الترجمة لا يتبع ترتيب الكلام."""
    n = len(str(line.get("text_ar") or "").split())
    if n == 0 or not span:
        return []
    first = start + float(span[0][0]) - t0
    if not line.get("arabic"):
        return [round(first, 3)] * n
    m = len(span)
    return [round(start + float(span[min(int(k * m / n), m - 1)][0]) - t0, 3) if m != n else
            round(start + float(span[k][0]) - t0, 3) for k in range(n)]


def _font(path: str, size: int, weight):
    from . import imaging
    return imaging.load_font(path, size, weight)


def _has_ar(text: str) -> bool:
    return bool(re.search("[؀-ۿ]", text or ""))


def _part_w(d, text: str, font) -> float:
    from . import imaging
    if _has_ar(text):
        bb = d.textbbox((0, 0), imaging._prepare(text), font=font, anchor="ra", **imaging._kwargs())
    else:
        bb = d.textbbox((0, 0), text, font=font, anchor="ra")
    return bb[2] - bb[0]


def _shrink(d, text: str, path: str, weight, size: int, minimum: int, max_w: float):
    """أكبر حجم حتى minimum يسع فيه الجزء سطرًا؛ لا يسع ← None."""
    while True:
        f = _font(path, size, weight)
        if _part_w(d, text, f) <= max_w:
            return f
        if size <= minimum:
            return None
        size -= 2


def draw_parts(d, right: float, y: float, parts: list, line_h: int, left: float, gap: int = 14, draw: bool = True) -> int:
    """يرسم أجزاء سطر من اليمين (أو يقيسها فقط) ويعيد عدد الأسطر الإضافية. الأجزاء العربية على خط أساس واحد (حجمان من خط واحد)،
    واللاتيني (خط Kalam بمقاييس أخرى) يتوسّط حبر الجزء العربي الأول ارتفاعًا — ملاحظة صاحب المشروع 8/11: الرسم الأجنبي والتوجّه
    كانا أعلى قليلًا من الاسم. جزء لا يسع ما بقي من السطر ينزل إلى سطر تالٍ."""
    from . import imaging
    x, lines, base, mid = right, 0, None, None
    for text, font, color in parts:
        if not text:
            continue
        ar = _has_ar(text)
        prepared = imaging._prepare(text) if ar else text
        kw = imaging._kwargs() if ar else {}
        bb = d.textbbox((0, 0), prepared, font=font, anchor="ra", **kw)
        w = bb[2] - bb[0]
        if base is None:
            base = y + font.getmetrics()[0]
            mid = y + (bb[1] + bb[3]) / 2
        elif x - w < left:
            x, lines, base, mid = right, lines + 1, base + line_h, mid + line_h
        if draw:
            if ar:
                d.text((x, base), prepared, font=font, fill=color, anchor="rs", **kw)
            else:
                d.text((x, mid - (bb[1] + bb[3]) / 2), prepared, font=font, fill=color, anchor="ra")
        x -= w + gap
    return lines


def info_rows(scene: dict, cfg, d) -> list[tuple[list, int]]:
    """أسطر معلومات المحلل [(الأجزاء، ارتفاع السطر)] كما في شريط المتحدث: الاسم (أسود) ورسمه الأجنبي (كحلي)، الصفة (رمادي)،
    «قناة X» (أسود) ورسمها الأجنبي (كحلي) والتوجّه بين قوسين (رمادي). متحدث غير موثَّق ← سطر القناة وحده بحجم أكبر."""
    from . import imaging, reel_render
    c = ccfg(cfg)
    k, info = c.get("card") or {}, c.get("info") or {}
    navy = imaging.hex_rgb(cfg.path("brand.primary_color"))
    black = tuple(int(x) for x in info.get("black", [0, 0, 0]))
    grey = tuple(int(x) for x in k.get("grey", [214, 222, 238]))
    latin_path = cfg.path("reel.render.fonts.latin")
    w = int(k["width"]) - 2 * int(info.get("edge", 30))
    scene = reel_render.relay_view(scene)   # قضية 1856: مؤتمر صحفي أو مقطع منقول لا يُنسب إلى من أعاد بثه
    name = scene.get("speaker_name", "") if scene.get("speaker_verified") else ""
    rows: list = []

    def ar_font(text, size, kind, minimum):
        path, weight = reel_render.face(cfg, text, kind)
        if kind == "display":
            weight = info.get("bold_weight", weight)
        return _shrink(d, text, path, weight, size, minimum, w)

    def lat_font(text, size):
        return reel_render.pick_font(text, latin_path, size, None) if text else None

    ch_ar, ch_lat = reel_render.band_channel_parts(scene, cfg)
    if _has_ar(ch_ar) and re.search(r"[A-Za-z]", ch_ar) and not ch_lat:
        # قناة بلا اسم عربي («قناة All Israel News»): الكلمة العربية بالأسود والاسم الأجنبي بالكحلي كرسم أجنبي
        toks = ch_ar.split()
        k_ar = next((n for n, tok in enumerate(toks) if not _has_ar(tok)), len(toks))
        ch_ar, ch_lat = " ".join(toks[:k_ar]), " ".join(toks[k_ar:])
    orient = reel_render.band_orientation(scene, cfg)
    if name:
        latin = (scene.get("speaker_name_latin") or "").strip()
        f = ar_font(name, int(info.get("name_size", 46)), "display", int(info.get("min_size", 24)))
        if f is not None:
            lf = lat_font(latin, int(info.get("name_latin_size", 34)))
            rows.append(([(name, f, black), (latin if lf else "", lf, navy)], int(info.get("name_h", 66))))
        role = reel_render.band_role(scene.get("speaker_role", ""))
        if role:
            rf = ar_font(role, int(info.get("role_size", 30)), "body", int(info.get("min_size", 24)))
            if rf is not None:
                rows.append(([(role, rf, grey)], int(info.get("row_h", 50))))
        size, height = int(info.get("channel_size", 32)), int(info.get("row_h", 50))
    else:
        size, height = int(info.get("solo_size", 36)), int(info.get("solo_h", 56))
    first = ch_ar or ch_lat
    if first:
        if _has_ar(first):
            cf = ar_font(first, size, "display", int(info.get("min_size", 24)))
        else:
            cf = lat_font(first, size)
        parts = [(first, cf, black if _has_ar(first) else navy)] if cf is not None else []
        if ch_ar and ch_lat:
            lf = lat_font(ch_lat, int(info.get("channel_latin_size", 30)))
            if lf is not None:
                parts.append((ch_lat, lf, navy))
        if orient:
            of = ar_font(f"({orient})", int(info.get("orient_size", 30)), "body", int(info.get("min_size", 24)))
            if of is not None:
                parts.append((f"({orient})", of, grey))
        if parts:
            rows.append((parts, height))
    return rows


def _rounded(size: tuple[int, int], radius: int) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius, fill=255)
    return m


def card_base(scene: dict, cfg) -> Image.Image:
    """الورقة بلا الفيديو (قرار صاحب المشروع 8/11): ورق ذهبي بحواف مدوّرة، وأعلاه هامش صغير بلا معلومات، ومعلومات شريط المحلل
    تحت الفيديو وحدها في مساحة أوسع، كتلتها متوسطة ارتفاعًا فيها (ورقة بلا اسم لا تترك فراغًا تحت سطر القناة)."""
    from . import imaging
    c = ccfg(cfg)
    k, info = c.get("card") or {}, c.get("info") or {}
    m, vh, ih = int(k["margin"]), int(k["video_height"]), int(k["info_height"])
    w, h = int(k["width"]), m + vh + ih
    paper = imaging.hex_rgb(k.get("color") or cfg.path("brand.accent_color"))
    face = Image.new("RGBA", (w, h), paper + (255,))
    d = ImageDraw.Draw(face)
    edge = int(info.get("edge", 30))
    rows = info_rows(scene, cfg, d)
    total = sum(hh * (1 + draw_parts(d, w - edge, 0, parts, hh, edge, draw=False)) for parts, hh in rows)
    y = m + vh + (ih - total) // 2 + int(info.get("nudge", -4))
    for parts, hh in rows:
        y += hh * (1 + draw_parts(d, w - edge, y, parts, hh, edge))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(face, (0, 0), _rounded((w, h), int(k.get("radius", 38))))
    return out


def caption_lines(text: str, cfg) -> tuple[list[list[str]], Any]:
    """أسطر نص الشاشة من النص كله (فلا تقفز الكلمات حين تُضاف) والخط: سطر واحد إن وسع الحجم الأدنى، وإلا أسطر تُعرض واحدًا في كل لحظة
    كترجمة الريل."""
    from . import imaging, reel_render
    c = ccfg(cfg)
    k, cap = c.get("card") or {}, c.get("caption") or {}
    vw = int(k["width"]) - 2 * int(k["margin"]) - 2 * int(cap.get("side", 30))
    path, weight = reel_render.face(cfg, text, "body")
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    size, minimum = int(cap.get("size", 36)), int(cap.get("min_size", 28))
    while True:
        font = _font(path, size, weight)
        lines = imaging.wrap(probe, text, font, vw)
        if len(lines) == 1 or size <= minimum:
            return [ln.split() for ln in lines], font
        size -= 2


def caption_state(times: list[float], lines: list[list[str]], t: float) -> tuple[int, int]:
    """(رقم السطر المعروض، عدد كلماته الظاهرة) عند t (دالة خالصة): أول كلمة من السطر التالي تستبدل السطر كله، والأخير يبقى."""
    shown = sum(1 for x in times if t >= x)
    if shown <= 0:
        return -1, 0
    acc = 0
    for li, ln in enumerate(lines):
        if shown <= acc + len(ln) or li == len(lines) - 1:
            return li, min(shown - acc, len(ln))
        acc += len(ln)
    return -1, 0


def caption_layer(lines: list[list[str]], font, li: int, shown: int, cfg) -> Image.Image | None:
    """صندوق نص الشاشة متوسطًا أفقيًا فوق أسفل الفيديو بعرض سطره كاملًا، والكلمات الظاهرة في مواضعها النهائية من اليمين."""
    from . import imaging
    if li < 0 or shown <= 0:
        return None
    cap = ccfg(cfg).get("caption") or {}
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    full = " ".join(lines[li])
    tw = imaging.measure(probe, full, font)[0]
    pad, bh = int(cap.get("pad_x", 22)), int(cap.get("box_h", 66))
    box = Image.new("RGBA", (tw + 2 * pad, bh), tuple(int(x) for x in cap.get("box", [18, 24, 38])) + (int(cap.get("alpha", 215)),))
    d = ImageDraw.Draw(box)
    part = " ".join(lines[li][:shown])
    imaging.draw_text(d, (pad + tw, bh // 2), part, font, (255, 255, 255), anchor="rm")
    return box


class _Card:
    """ورقة واحدة: قاعدتها وإطارات فيديو جملتها (JPEG) ونص شاشتها بأزمنة كلماته وزمن عرضها."""

    def __init__(self, scene: dict, frames: list[Path], text: str, times: list[float], start: float, until: float, cfg):
        k = ccfg(cfg).get("card") or {}
        self.base = card_base(scene, cfg)
        self.frames = frames
        self.times, self.start, self.until = times, start, until
        self.lines, self.font = caption_lines(text, cfg) if text.split() else ([], None)
        self.m, self.vw, self.vh = int(k["margin"]), int(k["width"]) - 2 * int(k["margin"]), int(k["video_height"])
        self.mask = _rounded((self.vw, self.vh), int(k.get("video_radius", 22)))
        self._cache: dict = {}
        self.cfg = cfg

    def frame_at(self, t: float) -> Path:
        fps = float(self.cfg.path("reel.render.fps"))
        idx = int((t - self.start) * fps)
        return self.frames[min(max(idx, 0), len(self.frames) - 1)]

    def caption_at(self, t: float) -> tuple[int, int]:
        if t >= self.until or not self.lines:
            return -1, 0
        return caption_state(self.times, self.lines, t)

    def image(self, t: float) -> Image.Image:
        f, (li, shown) = self.frame_at(t), self.caption_at(t)
        key = (str(f), li, shown)
        if key in self._cache:
            return self._cache[key]
        img = self.base.copy()
        v = Image.open(f).convert("RGB").resize((self.vw, self.vh))
        img.paste(v, (self.m, self.m), self.mask)
        cap = caption_layer(self.lines, self.font, li, shown, self.cfg)
        if cap is not None:
            bottom = int((ccfg(self.cfg).get("caption") or {}).get("bottom", 18))
            img.alpha_composite(cap, (self.m + (self.vw - cap.width) // 2, self.m + self.vh - cap.height - bottom))
        self._cache = {key: img}
        return img


def _place(canvas: Image.Image, card: Image.Image, cx: float, cy: float, ang: float, scale: float, dim: float, navy,
           shadows: dict) -> None:
    im = card if abs(scale - 1) < 1e-3 else card.resize((int(card.width * scale), int(card.height * scale)), Image.LANCZOS)
    if dim > 0.01:
        im = im.copy()
        veil = Image.new("RGBA", im.size, navy + (0,))
        veil.putalpha(im.getchannel("A").point(lambda a, dd=dim: int(a * dd)))
        im.alpha_composite(veil)
    r = im.rotate(ang, resample=Image.BICUBIC, expand=True)
    key = (round(ang, 1), round(scale, 2))
    sh = shadows.get(key)
    if sh is None:
        # الظل يُموَّه مصغَّرًا ثم يُكبَّر: النتيجة نفسها تقريبًا بجزء من الكلفة لكل إطار
        small = (max(r.width // 4, 1), max(r.height // 4, 1))
        sh = Image.new("RGBA", small, (0, 0, 0, 0))
        sh.putalpha(r.getchannel("A").resize(small).point(lambda a: int(a * 0.6)))
        sh = sh.filter(ImageFilter.GaussianBlur(6)).resize(r.size)
        shadows[key] = sh
    canvas.alpha_composite(sh, (int(cx - r.width / 2 + 18), int(cy - r.height / 2 + 30)))
    canvas.alpha_composite(r, (int(cx - r.width / 2), int(cy - r.height / 2)))


def footage_veil(cfg) -> Image.Image:
    """غطاء لقطة الحدث خلف الأوراق (خ3): طبقة ضباب الريل نفسها مضروبة في loop.fog_start، وهي ما ينتهي به ضباب الختام، فيطابق أول
    إطار هنا آخر إطار في الريل عند الإعادة. footage_fog يغيّر المعامل إن احتاجت الأوراق خلفية أعتم."""
    from . import reel_render as rr
    k = ccfg(cfg).get("footage_fog")
    f = float(k if k is not None else cfg.path("reel.render.loop.fog_start"))
    layer = rr.fog_layer(cfg)
    layer.putalpha(layer.getchannel("A").point(lambda a, ff=f: int(round(a * ff))))
    return layer


def draw_frames(cards: dict, tl: dict, cfg, out_dir: Path, footage: list[Path] | None = None) -> int:
    """إطارات المشهد JPEG؛ يعيد عددها. الخلفية لقطة الحدث (footage: إطارات فيديو الهوك مقصوصة 9:16) تحت ضباب الريل، وبلا لقطة
    فيديو الورقة النشطة مموّهًا تحت كحلي كما كان؛ ثم الورقتان بأوضاعهما."""
    from . import imaging
    rc = cfg.path("reel.render")
    w, h, fps = int(rc["width"]), int(rc["height"]), float(rc["fps"])
    c = ccfg(cfg)
    navy = imaging.hex_rgb(cfg.path("brand.primary_color"))
    shadows: dict = {}
    n = max(int(math.ceil(tl["total"] * fps)), 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    veil = (footage_veil(cfg) if footage else
            Image.new("RGBA", (w, h), navy + (int(255 * float(c.get("bg_dim", 0.76))),)))
    for i in range(n):
        t = i / fps
        active = cards["b"] if ("b" in cards and t >= (tl["swap0"] + tl["swap1"]) / 2) else cards["a"]
        if footage:
            # اللقطة أقصر من المشهد ← يثبت آخر إطارها (كما يفعل الهوك القديم بـtpad) لا تكرار يقفز
            bg = Image.open(footage[min(i, len(footage) - 1)]).convert("RGB").resize((w, h)).convert("RGBA")
        else:
            small = Image.open(active.frame_at(t)).convert("RGB").resize((w // 8, h // 8))
            bg = small.filter(ImageFilter.GaussianBlur(float(c.get("bg_blur", 3)))).resize((w, h)).convert("RGBA")
        bg.alpha_composite(veil)
        for name, x, y, ang, sc, dim in poses(t, tl, cfg):
            if name in cards:
                _place(bg, cards[name].image(t), x, y, ang, sc, dim, navy, shadows)
        bg.convert("RGB").save(out_dir / f"{i:05d}.jpg", quality=int(c.get("jpeg_quality", 90)))
    return n


def _usable_lines(hc: dict, script: dict, clips: dict, cfg, notes: list) -> list:
    """[(السجل، رقم المشهد، المشهد، (t0، t1، كلمات))] للجملتين بعد حرّاس التركيب: المقطع منزَّل، والمتحدث باقٍ موثَّقًا بعد حرّاس
    القائل، وكلمات الجملة مطابقة في الصوت ومدتها في الحدود. ما سقط يُذكر سببه في التعليق."""
    c = ccfg(cfg)
    t = cfg.path("reel.render.texts") or {}
    idx = {s.get("point_id"): j for j, s in enumerate(script.get("scenes") or [])
           if s.get("kind") in ("clip", "cold_open_clip") and s.get("point_id")}
    lo, hi = (float(x) for x in c.get("line_seconds", [1.5, 4.5]))
    slack = float(c.get("render_slack", 1.0))
    out = []
    for k in ("a", "b"):
        x = hc.get(k)
        if not isinstance(x, dict):
            continue
        j = idx.get(x.get("point_id"))
        why = ""
        if j is None or j not in clips:
            why = "المقطع لم يبقَ في الريل"
        else:
            sc = script["scenes"][j]
            if c.get("verified_only", True) and not (sc.get("speaker_verified") and sc.get("speaker_name")):
                why = "المتحدث لم يبقَ موثَّقًا"
            else:
                sp = span_times(clips[j], x, cfg)
                if sp is None:
                    why = "لم تُطابَق كلمات الجملة في الصوت"
                elif not lo - slack <= sp[1] - sp[0] <= hi + slack:
                    why = f"مدة الجملة المسموعة {sp[1] - sp[0]:.1f} ث"
        if why:
            if t.get("comment_clash_dropped"):
                notes.append(t["comment_clash_dropped"].format(channel=x.get("channel", ""), reason=why))
            continue
        out.append((x, j, sc, sp))
    return out


def _footage(i: int, draft: dict, total: float, cfg, deps, tmp: Path, notes: list, crops: dict | None):
    """إطارات لقطة الحدث خلف الأوراق (خ3، قرار صاحب المشروع 8/11): فيديو الهوك الذي اختاره المسح (hook_video، أقوى لقطة ميدانية
    في فيديوهات الموضوع) من بدايته بطول المشهد، مقصوصًا 9:16 بقصّ الهوك نفسه (بلا شريط القناة). يعيد (الإطارات، الملف، القصّ) أو
    None (لا hook_video، أو footage_bg مطفأ، أو فشل التنزيل) فتبقى الخلفية المموّهة القديمة."""
    from . import reel_render as rr
    c, rc = ccfg(cfg), cfg.path("reel.render")
    hv = (draft or {}).get("hook_video")
    if not c.get("footage_bg", True) or not isinstance(hv, dict) or not hv.get("video_id") or hv.get("start") is None:
        return None
    w, h, fps = int(rc["width"]), int(rc["height"]), rc["fps"]
    ws = int(hv["start"])
    # التنزيل يبدأ عند ثانية الهوك الصحيحة كما في _hook_scene، فأول إطار هو ما يلتحم به الختام؛ ويمتد بطول المشهد ولو جاوز نهاية
    # نافذة الهوك (الثواني بعد أقوى لقطة غالبًا من المشهد نفسه)، وما قصر يثبت آخر إطاره
    we = max(int(hv.get("end") or ws), ws + int(math.ceil(total)) + 1)
    clip = None
    try:
        clip = rr._download_with_retries(deps, rc, str(hv["video_id"]), ws, we, tmp / "clash_bg.mp4")
    except Exception as exc:  # noqa: BLE001 -- اللقطة تحسين: الخلفية القديمة
        log.warning("تعذّر تنزيل لقطة خلفية المواجهة: %s", rr.reel_clips.scrub_text(str(exc))[:120])
    t = cfg.path("reel.render.texts") or {}
    if clip is None:
        if t.get("comment_clash_bg_failed"):
            notes.append(t["comment_clash_bg_failed"])
        return None
    cexpr = rr._hook_crop(clip, cfg, deps, crops, video_id=hv.get("video_id"), channel=hv.get("channel", ""), notes=notes)
    fdir = tmp / f"clash_{i}_bg"
    fdir.mkdir(parents=True, exist_ok=True)
    deps.run(rr._base("-t", rr._fmt(total), "-i", str(clip), "-vf", f"{cexpr},scale={w}:{h},fps={fps}", "-q:v", "3",
                      str(fdir / "%05d.jpg")))
    frames = sorted(fdir.glob("*.jpg"))
    if not frames:
        return None
    if t.get("comment_clash_bg"):
        notes.append(t["comment_clash_bg"].format(channel=hv.get("channel", "")))
    return frames, clip, cexpr


def render_scene(i: int, scene: dict, script: dict, draft: dict, clips: dict, cfg, deps, tmp: Path, out: Path, notes: list,
                 voice: str, crops: dict | None, hook_info: dict | None = None) -> float | None:
    """مشهد هوك المواجهة؛ None ← لا يصلح (لا جملة باقية بعد حرّاس التركيب) فيعود الهوك القديم. يرفع عند عطل التركيب نفسه
    ويلتقطه المستدعي فيعود الهوك القديم أيضًا."""
    from . import reel_render as rr
    hc = draft.get("hook_clash")
    if not enabled(cfg) or not isinstance(hc, dict) or hc.get("error") or not isinstance(hc.get("a"), dict):
        return None
    c, rc = ccfg(cfg), cfg.path("reel.render")
    fps = rc["fps"]
    lines = _usable_lines(hc, script, clips, cfg, notes)
    if not lines:
        return None
    k = c.get("card") or {}
    vw, vh = int(k["width"]) - 2 * int(k["margin"]), int(k["video_height"])
    rate = rc.get("audio_rate", 48000)
    spans, meta = [], []
    for n, (x, j, sc, (t0, t1, words)) in enumerate(lines):
        clip = clips[j]
        crop = rr._prepare_crop(clip, cfg, deps, sc, None)
        _, cexpr = rr._panel_crops(clip, crop, sc, None, None, (0, 0, vw, vh), cfg, deps, [])
        fdir = tmp / f"clash_{i}_{n}"
        fdir.mkdir(parents=True, exist_ok=True)
        deps.run(rr._base("-ss", rr._fmt(t0), "-t", rr._fmt(t1 - t0), "-i", str(clip["file"]),
                          "-vf", f"{cexpr},scale={vw}:{vh},fps={fps}", "-q:v", "3", str(fdir / "%04d.jpg")))
        wav = tmp / f"clash_{i}_{n}.wav"
        fade = float(c.get("audio_fade", 0.04))
        deps.run(rr._base("-ss", rr._fmt(t0), "-t", rr._fmt(t1 - t0), "-i", str(clip["file"]), "-vn",
                          "-af", f"aresample={rate},aformat=channel_layouts=stereo,{rr._loudnorm(cfg)},"
                                 f"afade=t=in:d={fade},afade=t=out:st={rr._fmt(max(t1 - t0 - fade, 0))}:d={fade}",
                          str(wav)))
        frames = sorted(fdir.glob("*.jpg"))
        if not frames:
            raise RuntimeError("لم تُستخرج إطارات ورقة المواجهة")
        spans.append((frames, wav, round(t1 - t0, 3), x, sc, t0, words))
        meta.append({"point_id": x["point_id"], "t0": round(t0, 2), "t1": round(t1, 2), "text": x.get("text_ar", ""),
                     "mode": "words" if x.get("arabic") else "line"})
    title = hc.get("hook_text") or script.get("title") or scene.get("text", "")
    audio, parts = rr._speech(title, voice, cfg, deps, tmp, f"s{i:02d}")
    speech = sum(d for _, d in parts)
    tl = timeline(spans[0][2], spans[1][2] if len(spans) > 1 else None, speech, cfg)
    starts = [tl["a0"]] + ([tl["b0"]] if len(spans) > 1 else [])
    # نص الورقة يُرى ما دامت أمامية: الأولى حتى منتصف التبديل، والثانية (أو الوحيدة) حتى تنزل الأوراق لعنوان الهوك
    untils = ([(tl["swap0"] + tl["swap1"]) / 2, tl["q0"]] if len(spans) > 1 else [tl["q0"]])
    cards = {}
    for name, sp, st, until in zip(("a", "b"), spans, starts, untils):
        times = caption_times(sp[3], sp[6], sp[5], st, cfg)
        cards[name] = _Card(sp[4], sp[0], sp[3].get("text_ar", ""), times, st, until, cfg)
    vdir = tmp / f"clash_{i}_frames"
    foot = _footage(i, draft, tl["total"], cfg, deps, tmp, notes, crops)
    draw_frames(cards, tl, cfg, vdir, footage=foot[0] if foot else None)
    if hook_info is not None:
        if foot:
            # خ3: الهوك على لقطة الحدث نفسها، فيعامله الختام كهوك لقطة: نافذة ما قبل الهوك من الفيديو نفسه أو المزج إلى أول إطاره
            # (ضباب الختام ينتهي بما يغطّيه هنا) فيستمر الفيديو عند الإعادة
            hook_info.update(mode="clip", clip=foot[1], cexpr=foot[2])
        else:
            # الإعادة المتصلة: الختام يجمّد أول إطار هنا (الخلفية قبل دخول الأوراق) ويقترب منه حتى التكبير 1.0
            hook_info.update(mode="image", bgpng=vdir / "00000.jpg", x0=0.0)
    times = rr.narration_word_times(parts, tl["voice_at"], cfg)
    if len(times) != len(title.split()):
        times = rr.narration_word_times([(title, speech)], tl["voice_at"], cfg)
    q = c.get("question") or {}
    wframes = rr.word_drop_frames(cfg, title, times, tl["total"], int(q.get("top", 350)), tmp, f"cw{i}",
                                  size_key=str(q.get("size_key", "clash")))
    lst = tmp / f"clash_{i}_words.txt"
    lst.write_text("".join(f"file '{f}'\nduration {rr._fmt(d)}\n" for f, d in wframes) + f"file '{wframes[-1][0]}'\n",
                   encoding="utf-8")
    inputs = ["-framerate", str(fps), "-i", str(vdir / "%05d.jpg"), "-f", "concat", "-safe", "0", "-i", str(lst)]
    alab, af = [], []
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
        crops["clash"] = {"mode": "pair" if len(spans) > 1 else "single", "relation": hc.get("relation") if len(spans) > 1
                          else "single", "cards": meta, "hook_text": title, "seconds": tl["total"]}
    t = cfg.path("reel.render.texts")
    names = "، ".join(sp[4].get("channel_display", "") for sp in spans)
    rel = (cfg.path("reel.texts.clash.relations") or {}).get(hc.get("relation"), "")
    tpl = t.get("comment_clash" if len(spans) > 1 else "comment_clash_single") or ""
    if tpl:
        notes.append(tpl.format(channels=names, relation=rel))
    return tl["total"]
