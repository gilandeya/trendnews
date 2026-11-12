"""الفيديو الأصلي لكلام محلل تعيد قناة بثه من برنامج قناة أخرى (طلب صاحب المشروع بعد قضية 1856).

السبب: Gemini يعلّم المقطع `setting: other_channel` حين تعيد القناة بث مقطع من برنامج قناة أخرى (الميادين وفوكس نيوز في 1856)،
فيظهر في الريل شعار قناة وشريطها تحت اسم قناة أخرى. الأولى عرض الفيديو الأصلي من قناته؛ وإن تعذّر يبقى المنقول ويُعرض باسم
مصدره (relay_view).

النموذج يقترح والكود يقرّر: البحث بواجهة يوتيوب (لا بروكسي) عن اسم المتحدث وقناة المصدر في نافذة تاريخ الموضوع، ونداء Gemini
واحد على المرشّح الأقرب يعيد موضع الكلام نفسه فيه؛ يُقبل إن كانت المدة في حدود المقطع وكان الكلام المسموع يطابق كلام المقطع
المنقول بنسبة `min_text_ratio`، وإلا يبقى المنقول كما هو. لا يرفع أبدًا.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from . import gemini

log = logging.getLogger(__name__)

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "found": {"type": "BOOLEAN"},
        "start": {"type": "STRING"}, "end": {"type": "STRING"},
        "text_original": {"type": "STRING"},
        "speaker_on_screen": {"type": "BOOLEAN"},
        "reason": {"type": "STRING"},
    },
    "required": ["found"],
}


def _ocfg(cfg) -> dict:
    return cfg.path("youtube.meta_topics.qa.original") or {}


def _norm_words(text: str) -> list[str]:
    from .youtube_extract import _normalize_for_anchor
    return [w for w in _normalize_for_anchor(text or "").split() if w]


def text_ratio(expected: str, heard: str) -> float:
    """نسبة كلمات المقطع المنقول الواردة في الكلام المسموع بالترتيب (أطول تتابع مشترك ÷ كلمات المنقول). دالة خالصة."""
    a, b = _norm_words(expected), _norm_words(heard)
    if not a or not b:
        return 0.0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1] / len(a)


def _fold(s: str) -> str:
    return " ".join(_norm_words(s))


def channel_matches(title: str, source: str) -> bool:
    """قناة النتيجة هي قناة المصدر: أحد الاسمين بعد التطبيع يحوي الآخر (Fox News ↔ Fox News Channel). دالة خالصة."""
    a, b = _fold(title), _fold(source)
    return bool(a and b) and (a in b or b in a)


def known_channel(title: str, cfg) -> dict:
    """القناة من قائمة القنوات إن عُرفت باسمها أو اسمها العربي أو اللاتيني؛ فيُعرف كتلتها وتوجّهها. غير ذلك {}."""
    for ch in cfg.get("channels") or []:
        for k in ("name", "name_ar", "name_latin"):
            if ch.get(k) and channel_matches(title, ch[k]):
                return ch
    return {}


def pick_candidate(results: list[dict], bite: dict, details: dict, cfg) -> dict | None:
    """أول نتيجة صالحة: ليست الفيديو المنقول نفسه، وقناتها قناة المصدر (إلا إن أُعفي الشرط)، ومدتها دون `max_minutes`. خالصة."""
    o = _ocfg(cfg)
    cap = float(o.get("max_minutes", 120)) * 60
    src = bite.get("source_channel") or ""
    need = bool(o.get("require_channel_match", True))
    ranked = sorted(results, key=lambda r: not channel_matches(r.get("channel", ""), src))
    for r in ranked:
        vid = r.get("video_id")
        if not vid or vid == bite.get("video_id"):
            continue
        if need and not channel_matches(r.get("channel", ""), src):
            continue
        dur = (details.get(vid) or {}).get("duration")
        if dur and dur > cap:
            continue
        return {**r, "duration": dur}
    return None


def build_request(cand: dict, bite: dict, cfg) -> dict:
    """بلا temperature (قاعدة المشروع). الكلام المطلوب بلغته وترجمته واسم المتحدث في الرسالة."""
    o = _ocfg(cfg)
    lines = [f"المتحدث: {bite.get('speaker') or bite.get('speaker_original') or '—'}",
             f"الكلام المطلوب بلغته: {bite.get('text_original', '')}",
             f"ترجمته: {bite.get('text_ar', '')}"]
    return {
        "system_instruction": {"parts": [{"text": o.get("system", "")}]},
        "contents": [{"role": "user", "parts": [gemini.video_part(cand["video_id"], o.get("max_minutes", 0), cand.get("duration")),
                                                {"text": "\n".join(lines)}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA,
                             "mediaResolution": o.get("media_resolution", "MEDIA_RESOLUTION_LOW"),
                             "maxOutputTokens": int(o.get("max_output_tokens") or 4096)},
    }


def decide(data: dict, bite: dict, cand: dict, cfg) -> tuple[dict | None, str]:
    """(المقطع الأصلي أو None، السبب). دالة خالصة: الكود يقبل ما يطابق كلام المنقول فقط."""
    o = _ocfg(cfg)
    if not data.get("found"):
        return None, "لم يُعثر على الكلام"   # سبب النموذج لا يُحفظ: قد يقتبس الكلام، والسجل في الملف العام
    dur = cand.get("duration")
    t0, t1 = gemini.parse_clock(data.get("start"), dur), gemini.parse_clock(data.get("end"), dur)
    if t0 is None or t1 is None or t1 <= t0:
        return None, "زمن غير صالح"
    lo = float(cfg.path("youtube.meta_topics.qa.gemini.min_seconds", 8))
    hi = float(cfg.path("youtube.bites.end_check.complete_max_seconds", 40))
    if not lo <= t1 - t0 <= hi:
        return None, f"المدة {t1 - t0:.0f} ث خارج [{lo:g}، {hi:g}]"
    if dur and t1 > float(dur) + 1:
        return None, "بعد نهاية الفيديو"
    heard = " ".join(str(data.get("text_original") or "").split())
    ratio = text_ratio(bite.get("text_original", ""), heard)
    if ratio < float(o.get("min_text_ratio", 0.6)):
        return None, f"الكلام لا يطابق المنقول ({ratio:.2f})"
    if o.get("require_speaker_on_screen", True) and data.get("speaker_on_screen") is False:
        return None, "المتحدث لا يظهر في الأصلي"
    ch = known_channel(cand.get("channel", ""), cfg)
    new = dict(bite)
    new.update(video_id=cand["video_id"], bite_id=f"{cand['video_id']}:g{int(t0)}", start=round(t0, 1), end=round(t1, 1),
               seconds=round(t1 - t0, 1), text_original=heard, first_words="", last_words="",
               channel=ch.get("name") or cand.get("channel", ""), setting="studio", source_channel="",
               original_of={"video_id": bite.get("video_id"), "bite_id": bite.get("bite_id"), "channel": bite.get("channel", ""),
                            "ratio": round(ratio, 2)})
    # كتلة القناة الأصلية وتوجّهها إن عُرفت؛ وإلا تبقى كتلة الناقلة (الريل يحتاج كتلة لكل مقطع، وهي أقرب تخمين لا أكثر)
    if ch:
        new["bloc"], new["orientation"] = ch.get("bloc", new.get("bloc")), ch.get("orientation", new.get("orientation"))
    return new, f"تطابق {ratio:.2f}"


def _window(date: str, cfg) -> tuple[str, str]:
    o = _ocfg(cfg)
    day = datetime.strptime(date, "%Y-%m-%d")
    after = day - timedelta(days=int(o.get("window_days", 3)))
    before = day + timedelta(days=1)
    return after.strftime("%Y-%m-%dT00:00:00Z"), before.strftime("%Y-%m-%dT00:00:00Z")


def _queries(bite: dict) -> list[str]:
    who = bite.get("speaker_original") or bite.get("speaker") or ""
    src = bite.get("source_channel") or ""
    out = []
    for q in (f"{who} {src}", who):
        q = " ".join(q.split())
        if q and q not in out:
            out.append(q)
    return out


def find_originals(bites: list[dict], date: str, cfg, key: str, post=None, search=None, details=None,
                   stats: dict | None = None) -> list[dict]:
    """يعيد قائمة المقاطع بعد استبدال ما وُجد أصله. search/details يُحقنان في الاختبار؛ الحقيقيان من reel_hook_search
    (يحتاجان YOUTUBE_API_KEY، وبلاه لا بحث). كل محاولة تُسجَّل في stats["originals"]."""
    o = _ocfg(cfg)
    stats = stats if stats is not None else {}
    log_rows = stats.setdefault("originals", [])
    if not o.get("enabled") or not key:
        return bites
    if search is None or details is None:
        if not os.environ.get("YOUTUBE_API_KEY", "").strip():
            log.info("الفيديو الأصلي: لا YOUTUBE_API_KEY — يبقى المنقول")
            return bites
        from . import reel_hook_search
        search = search or reel_hook_search.real_yt_search
        details = details or reel_hook_search.real_yt_details
    after, before = _window(date, cfg)
    cap, out, tried = int(o.get("max_per_topic", 4)), [], 0
    taken = {(b.get("video_id"), b.get("bite_id")) for b in bites}
    for b in bites:
        if b.get("setting") != "other_channel" or not (b.get("speaker") or b.get("speaker_original")) or tried >= cap:
            out.append(b)
            continue
        tried += 1
        row = {"bite_id": b.get("bite_id"), "source_channel": b.get("source_channel", ""), "found": False}
        try:
            results: list[dict] = []
            for q in _queries(b):
                results += search(q, after, before, int(o.get("max_results", 5)))
                if any(channel_matches(r.get("channel", ""), b.get("source_channel", "")) for r in results):
                    break
            ids = list(dict.fromkeys(r["video_id"] for r in results if r.get("video_id")))
            cand = pick_candidate(results, b, details(ids) if ids else {}, cfg)
            if cand is None:
                row["reason"] = "لا مرشّح من قناة المصدر"
                log_rows.append(row)
                out.append(b)
                continue
            row["candidate"] = cand["video_id"]
            code, resp, _sec = gemini.generate(build_request(cand, b, cfg), o.get("model", "gemini-3.8-flash"), key, post=post)
            if code != 200:
                row["reason"] = f"Gemini HTTP {code}"
                log_rows.append(row)
                out.append(b)
                continue
            data, finish, usage = _read(resp)
            cost = gemini.cost_usd(usage, cfg.path("youtube.meta_topics.qa.gemini.price_per_mtok") or {})
            stats["gemini_cost"] = round(stats.get("gemini_cost", 0.0) + cost, 4)
            from . import costs
            costs.add("gemini", cost)
            if data is None:
                row["reason"] = f"لا ناتج مقبول ({finish})"
                log_rows.append(row)
                out.append(b)
                continue
            new, why = decide(data, b, cand, cfg)
            row["reason"] = why
            if new and (new["video_id"], new["bite_id"]) not in taken:
                row.update(found=True, video_id=new["video_id"], channel=new["channel"])
                taken.add((new["video_id"], new["bite_id"]))
                out.append(new)
            else:
                out.append(b)
        except Exception as exc:  # noqa: BLE001 — مقطع واحد لا يوقف الموضوع
            row["reason"] = f"{type(exc).__name__}: {str(exc)[:100]}"
            log.warning("الفيديو الأصلي %s: %s", b.get("bite_id"), row["reason"])
            out.append(b)
        log_rows.append(row)
    stats["originals_found"] = sum(1 for r in log_rows if r.get("found"))
    return out


def _read(resp: dict) -> tuple[dict | None, str, dict]:
    """read_response يشترط قائمة تحت مفتاح؛ هذا الرد كائن واحد، فيُقرأ هنا بالقاعدة نفسها: المقطوع لا يُقبل."""
    import json
    cands = resp.get("candidates") or []
    finish = (cands[0].get("finishReason") if cands else "") or ""
    usage = resp.get("usageMetadata") or {}
    if not cands or finish == "MAX_TOKENS":
        return None, finish or "no_candidates", usage
    text = "".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts") or [] if not p.get("thought"))
    try:
        data = json.loads(text)
    except ValueError:
        return None, f"{finish}:invalid_json", usage
    return (data if isinstance(data, dict) else None), finish, usage
