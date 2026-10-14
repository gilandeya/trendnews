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
    "input_schema": {"type": "object", "properties": {
        "text": {"type": "string"},
        "proper_nouns": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "foreign": {"type": "boolean"}}, "required": ["text", "foreign"]}}},
        "required": ["text"]},
}


def strip_tashkeel(text: str) -> str:
    """بلا حركات ولا تطويل وبمسافات موحَّدة: أساس الحارس الحرفي لما يعيده النموذج."""
    return " ".join(_TASHKEEL_RE.sub("", text or "").split())


def _client():
    from anthropic import Anthropic
    from .config import env
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def _diacritize_once(text: str, dcfg: dict, client, reason: str | None) -> tuple[str, list]:
    from .writer import record_usage
    prompt = text if not reason else f"{text}\n\nرُفضت المحاولة السابقة لهذا السبب: {reason} — صحّحه."
    model = dcfg.get("model", "claude-sonnet-5")
    resp = client.messages.create(
        model=model, max_tokens=int(dcfg.get("max_tokens", 4000)), system=dcfg.get("system", ""),
        tools=[DIACRITIZE_TOOL], tool_choice={"type": "tool", "name": "report_diacritized"},
        messages=[{"role": "user", "content": prompt}])
    record_usage(resp, model)
    data = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None) or {}
    nouns = [n for n in (data.get("proper_nouns") or []) if isinstance(n, dict) and isinstance(n.get("text"), str)]
    return str(data.get("text") or ""), nouns


def diacritize_full(text: str, cfg, client=None) -> tuple[str, str | None, list]:
    """(النص المشكول، تنبيه أو None، الأعلام [{text, foreign}]). الحارس في الكود لا في النموذج: ما عدا الحركات يجب أن
    يطابق الأصل حرفيًا، وإلا إعادة واحدة بذكر السبب ثم الأصل بلا تشكيل مع تنبيه. فشل التشكيل يُبقي الأعلام فارغة.
    لا يرفع أبدًا."""
    dcfg = cfg.path("reel.tts.diacritize") or {}
    if not dcfg.get("enabled") or not text:
        return text, None, []
    want = strip_tashkeel(text)
    reason = None
    try:
        client = client or _client()
        for _ in range(2):
            out, nouns = _diacritize_once(text, dcfg, client, reason)
            if strip_tashkeel(out) == want:
                return out, None, nouns
            reason = "الناتج بعد حذف الحركات لا يطابق الأصل حرفيًا (حرف مغيَّر أو كلمة مضافة/محذوفة)"
    except Exception as exc:  # noqa: BLE001 -- عطل التشكيل لا يوقف القياس
        log.warning("تشكيل: %s", str(exc)[:200])
    return text, DIACRITIZE_WARNING, []


def diacritize(text: str, cfg, client=None) -> tuple[str, str | None]:
    """(النص المشكول، تنبيه أو None) للمستدعين الذين لا يحتاجون الأعلام؛ التوقيع القديم نفسه."""
    out, warn, _ = diacritize_full(text, cfg, client)
    return out, warn


# ───────────────────────────── الوقف والجمل (Issue #1381، R3b-1) ─────────────────────────────

_WORD_RE = re.compile("[ء-ي][ء-يً-ْٰ]*")
# كلمة يليها وقف: علامة ترقيم نهائية أو نهاية النص، بعد أي قوس/تنصيص إغلاق
_PAUSE_AFTER = re.compile(r"""(?:[»"”)\]]*\s*(?:[.؟!:?،؛,]|$))""")
_HARAKA = "ً-ِ"
_SUKUN, _SHADDA, _FATHA, _FATHATAN = "ْ", "ّ", "َ", "ً"
_SENTENCE_END = re.compile(r"(?<=[.؟!?])[»\"”)\]]*\s+")


def _waqf_word(word: str, taa: bool = True) -> str:
    """وقف كلمة واحدة: الحركة أو التنوين الأخير ← سكون، والشدة تبقى، وما ينتهي بألف أو ألف مقصورة أو سكون يبقى.
    الحرف الأخير بلا حركة يأخذ سكونًا أيضًا وإلا خمّن صوت جوجل حركة الإعراب (Issue #1423). التاء المربوطة تصير «هْ»
    (taa=True: نص الصوت وحده، فالمعروض لا يتغير؛ أعلام الأسماء تُسكَّن تاؤها فقط).
    تنوين الفتح قبل ألف أخيرة (كِتَابًا) يصير فتحة على الحرف قبلها (كِتَابَا) لأن الألف لا تُسكَّن."""
    m = re.match(f"^(.*?)([ء-ي])([{_HARAKA}ّْٰ]*)$", word, re.S)
    if not m:
        return word
    head, letter, tail = m.groups()
    if letter == "ة" and taa:
        return head + "ه" + _SUKUN
    if _SUKUN in tail or letter == "ى":
        return word
    if letter == "ا":
        prev = re.match(f"^(.*[ء-ي])([{_HARAKA}ّْٰ]*)$", head, re.S)
        if prev is None:
            return word
        body, marks = prev.groups()
        if _FATHATAN in tail and not re.search(f"[{_HARAKA}]", marks):
            return body + marks + _FATHA + letter     # تنوين على الألف نفسها
        if _FATHATAN in marks:
            return body + marks.replace(_FATHATAN, _FATHA) + letter
        return word
    return head + letter + (_SHADDA if _SHADDA in tail else "") + _SUKUN


def apply_waqf(sentence: str) -> str:
    """يسكّن آخر كلمة قبل كل وقف (. ؟ ! : ، ؛ , أو نهاية الجملة) لأن TTS يقرأ إعراب الحرف الأخير فيبدو الوقف مصطنعًا.
    كلمات وسط الجملة لا تُمسّ."""
    out, pos = [], 0
    for m in _WORD_RE.finditer(sentence):
        if _PAUSE_AFTER.match(sentence, m.end()):
            out.append(sentence[pos:m.start()])
            out.append(_waqf_word(m.group()))
            pos = m.end()
    out.append(sentence[pos:])
    return "".join(out)


def apply_proper_nouns(text: str, nouns: list) -> str:
    """وقف على أعلام النص (Issue #1423): الأجنبي المنقول على آخر حرف من كل كلماته (سيْ إنْ إنْ تركْ) والعربي على كلمته
    الأخيرة وحدها (مطارِ الملكِ خالدْ). العَلَم يُطابَق بـstrip_tashkeel كلمةً كلمة؛ غير الموجود يُتجاهل بسطر log.
    الحركات وحدها تتغير فما عداها حرفيًا كما هو، وتاء مربوطة في علم تبقى (التحويل إلى «هْ» في apply_waqf وحده)."""
    words = [(m.start(), m.end(), strip_tashkeel(m.group())) for m in _WORD_RE.finditer(text or "")]
    wanted: dict[int, bool] = {}
    for n in nouns or []:
        toks = strip_tashkeel(str((n or {}).get("text") or "")).split()
        foreign = bool((n or {}).get("foreign"))
        hit = False
        for i in range(len(words) - len(toks) + 1):
            if toks and [w[2] for w in words[i:i + len(toks)]] == toks:
                hit = True
                for k in (range(i, i + len(toks)) if foreign else [i + len(toks) - 1]):
                    wanted[k] = True
        if not hit:
            log.info("علم غير موجود في النص المشكول فتُجوهل: %r", str((n or {}).get("text"))[:40])
    out, pos = [], 0
    for i, (st, en, _) in enumerate(words):
        if i in wanted:
            out.append(text[pos:st])
            out.append(_waqf_word(text[st:en], taa=False))
            pos = en
    out.append(text[pos:])
    return "".join(out)


def split_sentences(text: str) -> list[str]:
    """جمل عند . ؟ ! ؛ لا عند نقطة بين رقمين (1.4: ليس بعدها فراغ) ولا عند الفاصلة العربية «،»."""
    parts = _SENTENCE_END.split((text or "").strip())
    return [p.strip() for p in parts if p and p.strip()]
