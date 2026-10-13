"""صوت Google Cloud TTS لعينات الريل (Issue #1347، R3a). قياس فقط حتى الآن.

المفتاح من GOOGLE_TTS_API_KEY في الترويسة X-Goog-Api-Key لا في الرابط، ولا يُطبع ولا يُسجَّل:
الرابط يظهر في سجلات الأخطاء والاستثناءات، والترويسة لا تظهر فيها.
"""
from __future__ import annotations

import base64
import logging
import os
import re

import requests

log = logging.getLogger("trendnews.tts")

URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
KEY_VAR = "GOOGLE_TTS_API_KEY"
TIMEOUT = 60


def _post(url: str, headers: dict, body: dict, timeout: int) -> dict:
    resp = requests.post(url, headers=headers, json=body, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def synthesize(text: str, voice: str, cfg) -> dict:
    """{ok, audio, chars} عند النجاح، {ok: False, skipped: "no_key"} بلا مفتاح (بلا طلب ولا خطأ)،
    {ok: False, error} عند فشل الطلب."""
    key = os.environ.get(KEY_VAR)
    if not key:
        return {"ok": False, "skipped": "no_key"}
    body = {"input": {"text": text},
            "voice": {"languageCode": "ar-XA", "name": voice},
            "audioConfig": {"audioEncoding": "MP3"}}
    try:
        data = _post(URL, {"X-Goog-Api-Key": key, "Content-Type": "application/json"}, body, TIMEOUT)
        audio = base64.b64decode(data.get("audioContent") or "")
    except Exception as exc:  # noqa: BLE001 -- فشل صوت لا يوقف بقية العينات
        return {"ok": False, "error": str(exc).replace(key, "***")[:200]}
    if not audio:
        return {"ok": False, "error": "استجابة بلا صوت"}
    return {"ok": True, "audio": audio, "chars": len(text)}


def estimate_cost(chars: int, voice: str, cfg) -> float:
    prices = cfg.path("reel.tts.price_per_million") or {}
    family = "chirp3_hd" if "Chirp3-HD" in voice else "wavenet"
    return chars * float(prices.get(family, 0)) / 1_000_000


def all_voices(cfg) -> list[tuple[str, str]]:
    """(الجنس، الصوت) لكل أصوات الإعداد."""
    voices = cfg.path("reel.tts.voices") or {}
    return [(gender, v) for gender in ("female", "male") for v in voices.get(gender, [])]


# ───────────────────────────── التشكيل (Issue #1375، R3a-3) ─────────────────────────────

_TASHKEEL_RE = re.compile("[ً-ْٰـ]")
DIACRITIZE_WARNING = "تعذّر التشكيل: غيّر النموذج النص"
DIACRITIZE_TOOL = {
    "name": "report_diacritized",
    "description": "النص العربي نفسه مشكولًا",
    "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
}


def strip_tashkeel(text: str) -> str:
    """بلا حركات ولا تطويل وبمسافات موحَّدة: أساس الحارس الحرفي لما يعيده النموذج."""
    return " ".join(_TASHKEEL_RE.sub("", text or "").split())


def _client():
    from anthropic import Anthropic
    from .config import env
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def _diacritize_once(text: str, dcfg: dict, client, reason: str | None) -> str:
    from .writer import record_usage
    prompt = text if not reason else f"{text}\n\nرُفضت المحاولة السابقة لهذا السبب: {reason} — صحّحه."
    model = dcfg.get("model", "claude-sonnet-5")
    resp = client.messages.create(
        model=model, max_tokens=int(dcfg.get("max_tokens", 4000)), system=dcfg.get("system", ""),
        tools=[DIACRITIZE_TOOL], tool_choice={"type": "tool", "name": "report_diacritized"},
        messages=[{"role": "user", "content": prompt}])
    record_usage(resp, model)
    data = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None) or {}
    return str(data.get("text") or "")


def diacritize(text: str, cfg, client=None) -> tuple[str, str | None]:
    """(النص المشكول، تنبيه أو None). الحارس في الكود لا في النموذج: ما عدا الحركات يجب أن يطابق
    الأصل حرفيًا، وإلا إعادة واحدة بذكر السبب ثم الأصل بلا تشكيل مع تنبيه. لا يرفع أبدًا."""
    dcfg = cfg.path("reel.tts.diacritize") or {}
    if not dcfg.get("enabled") or not text:
        return text, None
    want = strip_tashkeel(text)
    reason = None
    try:
        client = client or _client()
        for _ in range(2):
            out = _diacritize_once(text, dcfg, client, reason)
            if strip_tashkeel(out) == want:
                return out, None
            reason = "الناتج بعد حذف الحركات لا يطابق الأصل حرفيًا (حرف مغيَّر أو كلمة مضافة/محذوفة)"
    except Exception as exc:  # noqa: BLE001 -- عطل التشكيل لا يوقف القياس
        log.warning("تشكيل: %s", str(exc)[:200])
    return text, DIACRITIZE_WARNING
