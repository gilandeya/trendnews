"""صوت Google Cloud TTS لعينات الريل (Issue #1347، R3a). قياس فقط حتى الآن.

المفتاح من GOOGLE_TTS_API_KEY في الترويسة X-Goog-Api-Key لا في الرابط، ولا يُطبع ولا يُسجَّل:
الرابط يظهر في سجلات الأخطاء والاستثناءات، والترويسة لا تظهر فيها.
"""
from __future__ import annotations

import base64
import logging
import os

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
