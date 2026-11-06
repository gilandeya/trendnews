"""قائل كل مقطع في الريل بنداء Gemini واحد لكل فيديو (موافقة صاحب المشروع 6/11 بعد قياس gemini_reel_probe).

السبب (قياس 6/11 على 18 مقطعًا من ثلاثة ريلات): حيث سمّى الطرفان المتكلم اتفقا 3 من 3، لكن سلسلتنا (الشريط وقائمة الضيوف وخريطة الوجوه)
حذفت مقطعين صحيحين لإبراهيم فريحات في ريل منشور بحجة «المتكلم مقدّم»، وعرضت 12 مقطعًا باسم القناة وحده وGemini قرأ اسم المتكلم من
الشريط في 11 منها. قاعدة صاحب المشروع: سلسلتنا والبروكسي أولًا ما لم يُخطئا ولو قليلًا، فإن أخطأا يعمل Gemini — وهذا موضع أخطأت فيه.

Gemini يرى الفيديو من رابطه (لا بروكسي)؛ والكود يقرّر: لا يُعتمد إلا اسم مصدره الشريط أو تعريف المقدّم (`accept_sources`) لنافذة يتكلم
فيها شخص واحد، وما سواه لا حكم له فتعمل حرّاس سلسلتنا كما كانت.
"""

from __future__ import annotations

import os

from . import gemini

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "speakers": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "name_ar": {"type": "STRING"}, "name_original": {"type": "STRING"}, "role": {"type": "STRING"},
            "is_host": {"type": "BOOLEAN"},
            "name_source": {"type": "STRING", "enum": ["chyron", "introduced", "addressed", "unknown"]}},
            "required": ["name_ar", "is_host", "name_source"]}},
        "windows": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "id": {"type": "STRING"}, "speaker": {"type": "STRING"}, "one_speaker": {"type": "BOOLEAN"},
            "evidence": {"type": "STRING"}},
            "required": ["id", "speaker", "one_speaker"]}},
    },
    "required": ["speakers", "windows"],
}


def _gcfg(cfg) -> dict:
    return cfg.path("reel.render.gemini_speaker") or {}


def clock(sec: float) -> str:
    """MM:SS بلا ساعات (الدقائق تتجاوز 59): Gemini أخطأ الساعة في أول قياس فكتب «1:10:25» يريد 10:25."""
    sec = int(round(max(sec, 0)))
    return f"{sec // 60}:{sec % 60:02d}"


def usable_windows(windows: list[dict], cfg) -> tuple[list[dict], list[dict]]:
    """(النوافذ المرسلة، الخارجة عن max_minutes). ما بعد السقف لا يُرسل ولا يُحكم عليه فتبقى له حرّاس سلسلتنا: كلفة الحلقة الطويلة كلها
    لا تُدفع من أجل نافذة في آخرها."""
    cap = float(_gcfg(cfg).get("max_minutes") or 0) * 60
    inside = [w for w in windows if not cap or w["end"] <= cap]
    return inside, [w for w in windows if w not in inside]


def build_request(video_id: str, windows: list[dict], cfg, system: str | None = None, tail: float | None = None) -> dict:
    """بلا temperature (قاعدة المشروع). من أول الحلقة لأن الضيوف يُعرَّفون فيه غالبًا، وتنتهي بعد آخر نافذة بـtail_seconds."""
    g = _gcfg(cfg)
    tail = float(g.get("tail_seconds", 60) if tail is None else tail)
    end = max(w["end"] for w in windows) + tail
    part = gemini.video_part(video_id)
    part["video_metadata"] = {"end_offset": f"{int(end)}s"}
    lines = ["النوافذ (من بداية الفيديو، MM:SS):"]
    lines += [f"- {w['id']}: {clock(w['start'])} – {clock(w['end'])}" for w in windows]
    return {"system_instruction": {"parts": [{"text": g.get("system", "") if system is None else system}]},
            "contents": [{"role": "user", "parts": [part, {"text": "\n".join(lines)}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA,
                                 "mediaResolution": g.get("media_resolution", "MEDIA_RESOLUTION_LOW"),
                                 "maxOutputTokens": int(g.get("max_output_tokens") or 65536)}}


def verdicts(data: dict, cfg) -> dict[str, dict]:
    """{معرّف النافذة: الحكم}. دالة خالصة. الحكم {name, name_original, role, is_host, source, evidence}؛ نافذة بأكثر من متكلم أو اسم مصدره
    ليس من accept_sources لا حكم لها (لا تخمين)."""
    accept = set(_gcfg(cfg).get("accept_sources") or ["chyron", "introduced"])
    people = {" ".join(str(s.get("name_ar") or "").split()): s for s in data.get("speakers") or [] if isinstance(s, dict)}
    out = {}
    for w in data.get("windows") or []:
        if not isinstance(w, dict) or not w.get("one_speaker"):
            continue
        name = " ".join(str(w.get("speaker") or "").split())
        rec = people.get(name) or {}
        if not name or rec.get("name_source") not in accept:
            continue
        out[str(w.get("id"))] = {"name": name, "name_original": " ".join(str(rec.get("name_original") or "").split()),
                                 "role": " ".join(str(rec.get("role") or "").split()), "is_host": bool(rec.get("is_host")),
                                 "source": rec.get("name_source"), "evidence": " ".join(str(w.get("evidence") or "").split())}
    return out


def judge(video_id: str, windows: list[dict], cfg, key: str | None = None, post=None) -> dict:
    """نداء واحد للفيديو: {verdicts, error, cost}. يرفع إن غاب المفتاح أو ردّ Gemini بغير 200 أو بلا ناتج مقبول (المستدعي يحوّل ذلك إلى
    «لا حكم» فتعمل حرّاس سلسلتنا)."""
    g = _gcfg(cfg)
    key = key if key is not None else os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("لا GEMINI_API_KEY")
    code, resp, _seconds = gemini.generate(build_request(video_id, windows, cfg), g.get("model", "gemini-3.8-flash"), key, post=post)
    if code != 200:
        raise RuntimeError(f"Gemini HTTP {code}: {str(resp)[:150]}")
    data, finish, usage = gemini.read_response(resp, "windows")
    if data is None:
        raise RuntimeError(f"Gemini: لا ناتج مقبول ({finish})")
    return {"verdicts": verdicts(data, cfg), "cost": gemini.cost_usd(usage, g.get("price_per_mtok") or {}), "speakers": data.get("speakers") or []}
