"""مقاطع موضوع واحد من فيديو يوتيوب بنداء Gemini واحد على رابطه (موافقة صاحب المشروع 6/11 بعد قياس gemini_probe).

السبب: رصيد بروكسي Webshare نفد فتوقفت خطوة الأسئلة (meta_qa) لأنها تجلب نص الفيديو عبره، وGemini يجلب الفيديو بنفسه ويرى
الشريط والوجه ويسمع الصوت في نداء واحد، فميّز المتحدثين في القياس أفضل من سلسلتنا. الناتج بشكل مقاطع `youtube_bites.extract`
نفسه فلا يتغير ما بعده (الأسئلة والاختيار والقضية والسيناريو)؛ والتركيب يضبط المقطع بالكلمات (Q13) من `text_original`.

النموذج يقترح والكود يقرّر: الزمن يُقرأ بـ`gemini.parse_clock`، والمدة والنوع والترجمة على الشاشة والتداخل تُفحص هنا، والاسم الذي
لا يعرف النموذج مصدره (`name_source: unknown`) لا يُكتب.
"""

from __future__ import annotations

import logging

from . import gemini, llm

log = logging.getLogger(__name__)

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "speakers": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "name_ar": {"type": "STRING"}, "name_original": {"type": "STRING"}, "role": {"type": "STRING"},
            "is_host": {"type": "BOOLEAN"},
            "name_source": {"type": "STRING", "enum": ["chyron", "introduced", "addressed", "unknown"]}},
            "required": ["name_ar", "is_host", "name_source"]}},
        "bites": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "start": {"type": "STRING"}, "end": {"type": "STRING"}, "speaker": {"type": "STRING"},
            "type": {"type": "STRING", "enum": ["opinion", "forecast", "fact", "report"]},
            "summary_ar": {"type": "STRING"}, "answers": {"type": "STRING"},
            "text_original": {"type": "STRING"}, "text_ar": {"type": "STRING"},
            "first_words": {"type": "STRING"}, "last_words": {"type": "STRING"},
            "voice": {"type": "STRING", "enum": ["actor", "analyst"]},
            # ريلا 13/11: الحقول الثلاثة الأولى في التعليمات منذ قضية 1856 ولم تكن في المخطط، والمخرج المقيَّد بمخطط لا يعيد غير
            # خصائصه، فكان كل مقطع «studio» بصوت أصلي: لم يُبحث عن أصل منقول قط، وتصريح رضائي الذي قرأه مقدّم BBC Persian بدا كلامه
            "audio": {"type": "STRING", "enum": ["original", "dubbed_ar", "dubbed_other"]},
            "setting": {"type": "STRING", "enum": ["studio", "external", "other_channel"]},
            "source_channel": {"type": "STRING"},
            # own = صاحب الكلام يُرى ويُسمع بصوته؛ read = يقرؤه غيره أو يرويه (مقدّم يقرأ تصريحًا، صوت راوٍ فوق صورته)
            "delivery": {"type": "STRING", "enum": ["own", "read"]}},
            "required": ["start", "end", "speaker", "type", "summary_ar", "text_original", "text_ar", "setting", "delivery"]}},
    },
    "required": ["speakers", "bites"],
}


def _gcfg(cfg) -> dict:
    return cfg.path("youtube.meta_topics.qa.gemini") or {}


def build_request(video_id: str, topic: str, meta: dict, cfg, duration: float | None = None) -> dict:
    """بلا temperature عمدًا (قاعدة المشروع). العنوان والوصف في الرسالة لأنهما يعرّفان الضيوف غالبًا، والحدث المطلوب يحصر المقاطع."""
    g = _gcfg(cfg)
    lines = [f"الحدث المطلوب: {topic}"]
    if meta.get("title"):
        lines.append(f"عنوان الفيديو: {meta['title']}")
    if meta.get("description"):
        lines.append(f"وصف الفيديو: {str(meta['description'])[:1500]}")
    lines.append("استخرج المقاطع بحسب التعليمات.")
    return {
        "system_instruction": {"parts": [{"text": llm.with_notes(g.get("system", ""), cfg)}]},
        "contents": [{"role": "user", "parts": [gemini.video_part(video_id, g.get("max_minutes", 0), duration),
                                                {"text": "\n".join(lines)}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA,
                             "mediaResolution": g.get("media_resolution", "MEDIA_RESOLUTION_LOW"),
                             "maxOutputTokens": int(g.get("max_output_tokens") or 65536)},
    }


def to_bites(data: dict, video_id: str, topic: str, cfg, duration: float | None = None) -> tuple[list[dict], list[dict]]:
    """(المقاطع المقبولة بشكل youtube_bites، المرفوضة بسببها). دالة خالصة."""
    from . import youtube_bites
    g = _gcfg(cfg)
    lo = float(g.get("min_seconds", 8))
    hi = float(cfg.path("youtube.bites.end_check.complete_max_seconds", 40))
    people = {}
    for s in data.get("speakers") or []:
        if isinstance(s, dict) and s.get("name_ar"):
            people[str(s["name_ar"]).strip()] = s
    raw = []
    for i, b in enumerate(data.get("bites") or []):
        if not isinstance(b, dict):
            continue
        t0, t1 = gemini.parse_clock(b.get("start"), duration), gemini.parse_clock(b.get("end"), duration)
        raw.append((t0 if t0 is not None else -1, i, b, t0, t1))
    ok, bad, last_end = [], [], -1.0
    for _k, i, b, t0, t1 in sorted(raw, key=lambda r: (r[0], r[1])):
        if t0 is None or t1 is None or t1 <= t0:
            bad.append({"index": i, "reason": "زمن غير صالح"})
            continue
        dur = t1 - t0
        if dur < lo or dur > hi:
            bad.append({"index": i, "reason": f"المدة {dur:.0f} ث خارج [{lo:g}، {hi:g}]"})
            continue
        if duration and t1 > float(duration) + 1:
            bad.append({"index": i, "reason": "بعد نهاية الفيديو"})
            continue
        kind = str(b.get("type") or "")
        if kind not in youtube_bites.VALID_TYPES:
            bad.append({"index": i, "reason": f"نوع غير معروف: {kind or '—'}"})
            continue
        text_ar = " ".join(str(b.get("text_ar") or "").split())
        original = " ".join(str(b.get("text_original") or "").split())
        if not original:
            bad.append({"index": i, "reason": "كلام بلا نص أصلي"})
            continue
        if not youtube_bites.screen_text_ok(text_ar, cfg):
            bad.append({"index": i, "reason": "الترجمة لا تصلح للشاشة"})
            continue
        if t0 < last_end:
            bad.append({"index": i, "reason": "يتداخل مع مقطع قبله"})
            continue
        # الحقل audio_track لا audio: audio سجل تفريغ الصوت (bite_audio) على المقطع نفسه
        # قضية 1856: صوت مدبلج بلغة غير العربية لا يُعرض (المشاهد يسمع المترجم لا المتحدث، والترجمة المكتوبة لا تطابق ما يُسمع)
        audio = str(b.get("audio") or "original")
        if audio in (g.get("reject_audio") or []):
            bad.append({"index": i, "reason": "ترجمة صوتية بلغة غير العربية فوق المتحدث"})
            continue
        setting = str(b.get("setting") or "")
        # «حصري للقناة» يُبنى على حكم النموذج وحده (13/11): مقطع بلا إطار معروف لا يُنسب إلى القناة في السياق
        setting_known = setting in ("studio", "external", "other_channel")
        if not setting_known:
            setting = "studio"
        name = " ".join(str(b.get("speaker") or "").split())
        rec = people.get(name, {})
        # اسم لا يعرف النموذج من أين جاء لا يُكتب تحت وجه: يُحسم بالشريط والخريطة في التركيب كأي متكلم مجهول
        known = rec.get("name_source") in ("chyron", "introduced", "addressed")
        speaker, speaker_orig = youtube_bites._arabic_speaker(
            {"speaker": name if known else "", "speaker_original": rec.get("name_original", "")}, cfg)
        last_end = t1
        ok.append({"bite_id": f"{video_id}:g{int(t0)}", "start": round(t0, 1), "end": round(t1, 1),
                   "seconds": round(dur, 1), "first_words": str(b.get("first_words") or ""),
                   "last_words": str(b.get("last_words") or ""), "speaker": speaker, "speaker_original": speaker_orig,
                   "speaker_role": " ".join(str(rec.get("role") or "").split()), "is_host": bool(rec.get("is_host")),
                   "name_source": rec.get("name_source") or "unknown", "type": kind, "event_hint": topic,
                   "summary_ar": " ".join(str(b.get("summary_ar") or "").split()), "text_ar": text_ar,
                   "answers": " ".join(str(b.get("answers") or "").split()), "text_original": original,
                   "source": "gemini", "audio_track": audio, "setting": setting,
                   "setting_source": "model" if setting_known else "",
                   "source_channel": " ".join(str(b.get("source_channel") or "").split()),
                   # طرف في الحدث يتكلم عنه (مسؤول، نائب، متحدث رسمي) أم محلل يعلّق عليه: الأول مادة السياق لا إجابة سؤال (12/11)
                   "voice": "actor" if str(b.get("voice") or "") == "actor" else "analyst",
                   "delivery": "read" if str(b.get("delivery") or "") == "read" else "own"})
    return ok, bad


def extract(video_id: str, topic: str, meta: dict, cfg, key: str, post=None) -> dict:
    """{bites, rejected, error, finish, usage, cost, seconds}. لا يرفع: العطل في error ويمضي الموضوع بالفيديوهات الأخرى."""
    g = _gcfg(cfg)
    duration = meta.get("duration_seconds")
    out = {"bites": [], "rejected": [], "error": "", "finish": "", "usage": {}, "cost": 0.0, "seconds": 0.0}
    try:
        body = build_request(video_id, topic, meta, cfg, duration)
        code, resp, seconds = gemini.generate(body, g.get("model", "gemini-3.8-flash"), key, post=post)
        out["seconds"] = seconds
        if code != 200:
            out["error"] = f"Gemini HTTP {code}: {resp}"[:200]
            return out
        data, finish, usage = gemini.read_response(resp, "bites")
        out.update(finish=finish, usage=usage, cost=gemini.cost_usd(usage, g.get("price_per_mtok") or {}))
        from . import costs
        costs.add("gemini", out["cost"])   # الرد المرفوض مدفوع أيضًا، فيُحسب قبل فحصه
        if data is None:
            out["error"] = f"Gemini: لا ناتج مقبول ({finish})"
            return out
        out["bites"], out["rejected"] = to_bites(data, video_id, topic, cfg, duration)
    except Exception as exc:  # noqa: BLE001 — فيديو واحد لا يوقف الموضوع
        out["error"] = f"Gemini {type(exc).__name__}: {str(exc)[:150]}"
        log.warning("مقاطع Gemini %s: %s", video_id, out["error"])
    return out
