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
    from . import costs
    costs.add("tts", estimate_cost(len(text), voice, cfg))   # كلفة الريل (costs): Google تسعّر بالحروف
    return {"ok": True, "audio": audio, "chars": len(text)}


# ───────────── ElevenLabs أولًا ما دام فيه رصيد، ثم Google (طلب صاحب المشروع 12/11) ─────────────

EL_API = "https://api.elevenlabs.io/v1"
EL_KEY_VAR = "ELEVENLABS_API_KEY"


def _el_cfg(cfg) -> dict:
    return cfg.path("reel.tts.elevenlabs") or {}


def _el_get(url: str, headers: dict, timeout: int) -> dict:
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _el_post(url: str, headers: dict, body: dict, timeout: int) -> bytes:
    resp = requests.post(url, headers=headers, json=body, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs HTTP {resp.status_code}: {(resp.text or '')[:150]}")
    return resp.content


def el_remaining(cfg, key: str, get=None) -> int | None:
    """الحروف الباقية في الاشتراك (character_limit − character_count)؛ None إن تعذّر السؤال (مفتاح بلا صلاحية قراءة المستخدم
    مثلًا)، فيُجرَّب الصوت ويُرجَع إلى Google عند رفضه."""
    get = get or _el_get
    try:
        data = get(f"{EL_API}/user/subscription", {"xi-api-key": key}, TIMEOUT)
        return int(data.get("character_limit") or 0) - int(data.get("character_count") or 0)
    except Exception as exc:  # noqa: BLE001
        log.info("رصيد ElevenLabs غير معروف: %s", str(exc).replace(key, "***")[:120])
        return None


def el_synthesize(text: str, voice_id: str, cfg, key: str, post=None, extra: dict | None = None) -> dict:
    """{ok, audio, chars} أو {ok: False, error}. mp3 كصوت Google فلا يتغير ما بعده في التركيب.
    extra يُدمج في جسم الطلب (model_id، previous_text/next_text، voice_settings تُدمج فوق إعدادات الإعداد): أداة قياس الصوت
    (tools/voice_probe.py) تجرّب به صيغًا قبل أن يُعتمد شيء في الإنتاج."""
    e = _el_cfg(cfg)
    post = post or _el_post
    body = {"text": text, "model_id": e.get("model", "eleven_multilingual_v2")}
    if e.get("voice_settings"):
        body["voice_settings"] = dict(e["voice_settings"])
    for k, v in (extra or {}).items():
        if k == "voice_settings" and isinstance(v, dict):
            body["voice_settings"] = {**body.get("voice_settings", {}), **v}
        elif v not in (None, ""):
            body[k] = v
    url = f"{EL_API}/text-to-speech/{voice_id}?output_format={e.get('output_format', 'mp3_44100_128')}"
    try:
        audio = post(url, {"xi-api-key": key, "Content-Type": "application/json"}, body, TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc).replace(key, "***")[:200]}
    if not audio:
        return {"ok": False, "error": "استجابة بلا صوت"}
    from . import costs
    costs.add("tts", len(text) * float(e.get("usd_per_1000_chars", 0)) / 1000)
    return {"ok": True, "audio": audio, "chars": len(text)}


class VoiceSession:
    """مزوّد الصوت لتركيب ريل واحد. يُحسم المزوّد عند أول جملة للريل كله: ElevenLabs إن كان مفعّلًا ومفتاحه موجودًا وباقي رصيده
    ≥ min_credits (كي لا ينفد وسط الريل فيتكلم الراوي بصوتين)، وإلا Google. رفضُ ElevenLabs لاحقًا (نفد الرصيد رغم التقدير، أو عطل)
    ينقل ما بقي من الريل إلى Google، ويُذكر ذلك في تعليق التركيب لأن الصوتين مختلفان. get/post يُحقنان في الاختبار."""

    def __init__(self, cfg, get=None, post=None, google=None):
        self.cfg, self._get, self._post = cfg, get, post
        self._google = google or (lambda text, voice: synthesize(text, voice, cfg))
        self.provider: str | None = None
        self.reason = ""
        self.remaining: int | None = None
        self.el_chars = 0
        self.mixed = False
        # صوت ElevenLabs المختار لراوي هذا الريل (script.narrator_voice، تناوب الأصوات 21/11)؛ فارغ ← صوت الجنس كما كان
        self.voice_id = ""

    def _decide(self) -> None:
        e = _el_cfg(self.cfg)
        key = os.environ.get(EL_KEY_VAR, "").strip()
        self.provider = "google"
        if not e.get("enabled"):
            return
        if not key:
            self.reason = "no_key"
            return
        self.remaining = el_remaining(self.cfg, key, self._get)
        if self.remaining is not None and self.remaining < int(e.get("min_credits", 3000)):
            self.reason = "credits"
            return
        self.provider = "elevenlabs"

    def _el_voice(self, voice: str) -> str:
        """صوت راوي الريل المحفوظ في السيناريو، وإلا: صوت Google للراوي ← جنسه في narrator_voices ← صوت ElevenLabs لذلك الجنس."""
        if self.voice_id:
            return self.voice_id
        narr = self.cfg.path("reel.tts.narrator_voices") or {}
        gender = next((g for g, v in narr.items() if v == voice), "female")
        return str((_el_cfg(self.cfg).get("voices") or {}).get(gender) or "")

    def multilingual(self) -> bool:
        """هل يقرأ مزوّد هذا الريل الحروف اللاتينية بنطقها؟ (ريل 1913) يُحسم المزوّد هنا إن لم يُحسم بعد، كما يُحسم عند أول
        جملة. أصوات Google العربية تتعثر في النص اللاتيني فتبقى الأسماء عندها بالعربية."""
        if self.provider is None:
            self._decide()
        return self.provider in (self.cfg.path("reel.tts.latin_names.providers") or [])

    def synthesize(self, text: str, voice: str) -> dict:
        if self.provider is None:
            self._decide()
        if self.provider == "elevenlabs":
            vid = self._el_voice(voice)
            res = el_synthesize(text, vid, self.cfg, os.environ.get(EL_KEY_VAR, "").strip(), self._post) if vid else \
                {"ok": False, "error": "لا صوت ElevenLabs لهذا الجنس في الإعداد"}
            if res.get("ok"):
                self.el_chars += len(text)
                return res
            log.warning("ElevenLabs رفض الجملة، يُكمل الريل بصوت Google: %s", res.get("error"))
            self.mixed = self.el_chars > 0
            self.provider, self.reason = "google", "error:" + str(res.get("error") or "")[:100]
        return self._google(text, voice)

    def note(self) -> str:
        """سطر تعليق التركيب: المزوّد الذي نطق الريل ولماذا. فارغ إن لم يُنطق شيء أو كان ElevenLabs مطفأً."""
        t = _el_cfg(self.cfg).get("texts") or {}
        if self.provider is None or not _el_cfg(self.cfg).get("enabled"):
            return ""
        if self.mixed:
            return t.get("mixed", "⚠️ الصوت: بدأ بـElevenLabs ثم أكمل بـGoogle ({reason}) — صوتان مختلفان").format(reason=self.reason)
        if self.provider == "elevenlabs":
            left = "" if self.remaining is None else str(self.remaining - self.el_chars)
            return t.get("used", "🎙️ الصوت: ElevenLabs (باقي الرصيد نحو {left} حرف)").format(left=left or "?")
        why = (t.get("reasons") or {}).get(self.reason.split(":")[0], self.reason)
        return t.get("fallback", "🎙️ الصوت: Google ({reason})").format(reason=why)


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
            "text": {"type": "string"}, "foreign": {"type": "boolean"}, "latin": {"type": "string"},
            "kind": {"type": "string", "enum": ["person", "place", "organization", "channel", "other"]}},
            "required": ["text", "foreign", "kind"]}},
        "numbers": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "spoken": {"type": "string"}}, "required": ["text", "spoken"]}}},
        "required": ["text"]},
}

_LATIN_RE = re.compile("[A-Za-z]")
_ARABIC_RE = re.compile("[ء-ي]")


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
    # الأرقام تُحمل مع الأعلام (kind: number) كي لا يتغير شكل ما يعيده diacritize_full لكل مستدعيه
    nouns += [{"text": str(n["text"]).strip(), "spoken": str(n["spoken"]).strip(), "kind": "number"}
              for n in (data.get("numbers") or []) if isinstance(n, dict) and n.get("text") and n.get("spoken")]
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
        if (n or {}).get("kind") == "number":
            continue
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


def latin_names(text: str, nouns: list, cfg=None) -> tuple[str, list]:
    """نص النطق وحده: كل عَلَم أجنبي يُكتب برسمه اللاتيني الأصلي («دونالد ترامب» ← «Donald Trump») فيقرأه الصوت متعدد اللغات
    بنطقه الأصلي لا بأسلوب عربي (ملاحظة صاحب المشروع، ريل 1913). يعيد (النص، [(العربي، اللاتيني)]).

    المعروض على الشاشة لا يتغير أبدًا: هذا النص يذهب إلى المزوّد وحده. لا يُستبدل إلا علم وسمه النموذج أجنبيًا ومعه رسم
    لاتيني خالص وردت كلماته كلها في النص؛ والأطول كلماتٍ أولًا فلا يُبتر علم داخل علم. دالة خالصة."""
    valid = []
    for n in nouns or []:
        if not isinstance(n, dict) or not n.get("foreign") or not latin_kind_ok(n, cfg):
            continue
        latin = " ".join(str(n.get("latin") or "").split())
        toks = strip_tashkeel(str(n.get("text") or "")).split()
        # رسم فيه حرف عربي ليس الرسم الأصلي، وبلا حرف لاتيني لا يُنطق بغير العربية
        if toks and latin and _LATIN_RE.search(latin) and not _ARABIC_RE.search(latin):
            valid.append((toks, latin))
    if not valid:
        return text, []
    words = [(m.start(), m.end(), strip_tashkeel(m.group())) for m in _WORD_RE.finditer(text or "")]
    spans: dict[int, tuple[int, str]] = {}
    taken: set[int] = set()
    for toks, latin in sorted(valid, key=lambda v: -len(v[0])):
        for i in range(len(words) - len(toks) + 1):
            if [w[2] for w in words[i:i + len(toks)]] != toks or any(k in taken for k in range(i, i + len(toks))):
                continue
            spans[i] = (len(toks), latin)
            taken.update(range(i, i + len(toks)))
    if not spans:
        return text, []
    out, pos, used = [], 0, []
    for i, (start, _, _) in enumerate(words):
        if i not in spans:
            continue
        count, latin = spans[i]
        end = words[i + count - 1][1]
        out.append(text[pos:start])
        out.append(latin)
        used.append((" ".join(w[2] for w in words[i:i + count]), latin))
        pos = end
    out.append(text[pos:])
    return "".join(out), used


def latin_kind_ok(noun: dict, cfg=None) -> bool:
    """هل يُنطق هذا العَلَم برسمه الأجنبي؟ (طلب صاحب المشروع 21/11): أسماء الأشخاص وحدها، والمدن والجهات تُقرأ بالعربية
    («شنتشن» لا «Shenzhen»). علم بلا kind (مزيَّف قديم) يبقى كما كان. reel.tts.latin_names.kinds فارغة ← كل الأنواع."""
    kinds = (cfg.path("reel.tts.latin_names.kinds") if cfg is not None else None) or []
    kind = noun.get("kind")
    return not kinds or not kind or kind in kinds


# ───────────── الأرقام بالكلمات في نص النطق (طلب صاحب المشروع 21/11: الأصوات تنطق الأرقام بشكل غريب) ─────────────
# الرقم مكتوبًا بالأرقام يقرؤه ElevenLabs بلغة أخرى أو خانةً خانة («2026»، «1.4»). النطق بالكلمات من نداء التشكيل نفسه
# (numbers[].spoken، بإعرابه في سياقه)، وما لم يُعِده يُكتب هنا بقاعدة بسيطة. المعروض على الشاشة يبقى بالأرقام.

# الحرف العربي قبل الرقم مباشرة (و1,200) حرف عطف لا جزء من الرقم، فالحدّ أرقام ونقطة وحدها
_NUM_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(%?)(?!\d)")
_ONES = ["صفر", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة", "عشرة", "أحد عشر",
         "اثنا عشر", "ثلاثة عشر", "أربعة عشر", "خمسة عشر", "ستة عشر", "سبعة عشر", "ثمانية عشر", "تسعة عشر"]
_TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
_HUNDREDS = ["", "مئة", "مئتان", "ثلاثمئة", "أربعمئة", "خمسمئة", "ستمئة", "سبعمئة", "ثمانمئة", "تسعمئة"]
_SCALES = [("", "", "", ""), ("ألف", "ألفان", "آلاف", "ألف"), ("مليون", "مليونان", "ملايين", "مليون"),
           ("مليار", "ملياران", "مليارات", "مليار")]


def _below_thousand(n: int) -> str:
    parts = []
    if n >= 100:
        parts.append(_HUNDREDS[n // 100])
        n %= 100
    if n >= 20:
        parts.append((_ONES[n % 10] + " و" if n % 10 else "") + _TENS[n // 10])
    elif n:
        parts.append(_ONES[n])
    return " و".join(parts)


def number_words(n: int) -> str:
    """عدد صحيح بالكلمات (مرفوعًا، مذكرًا): احتياط لما لم يُعِده نداء التشكيل. دالة خالصة."""
    if n < 20:
        return _ONES[n]
    groups, scale = [], 0
    while n and scale < len(_SCALES):
        n, chunk = divmod(n, 1000)
        if chunk:
            one, two, few, many = _SCALES[scale]
            if not scale:
                groups.append(_below_thousand(chunk))
            elif chunk == 1:
                groups.append(one)
            elif chunk == 2:
                groups.append(two)
            elif chunk <= 10:
                groups.append(_below_thousand(chunk) + " " + few)
            else:
                groups.append(_below_thousand(chunk) + " " + many)
        scale += 1
    return " و".join(reversed(groups))


def _number_token_words(whole: str, frac: str | None, pct: str) -> str:
    words = number_words(int(whole.replace(",", "")))
    if frac:
        words += " فاصلة " + (number_words(int(frac)) if not frac.startswith("0") else " ".join(_ONES[int(d)] for d in frac))
    if pct:
        words += " بالمئة"
    return words


def spoken_numbers(text: str, nouns: list | None = None) -> str:
    """نص النطق وحده: كل رقم بالكلمات — ما أعاده نداء التشكيل لذلك الرقم أولًا (بإعرابه)، وإلا number_words. والشرطة
    المائلة بين كلمتين («أكتوبر/تشرين الأول») تُقرأ وقفة لا «سلاش». نطق فيه رقم أو حرف لاتيني لا يُقبل. دالة خالصة."""
    given: dict[str, list[str]] = {}
    for n in nouns or []:
        if isinstance(n, dict) and n.get("kind") == "number":
            spoken = str(n.get("spoken") or "").strip()
            if spoken and not re.search(r"[0-9A-Za-z٠-٩]", spoken):
                given.setdefault(str(n.get("text") or "").strip().rstrip("%"), []).append(spoken)

    def sub(m: re.Match) -> str:
        key = m.group(1) + (("." + m.group(2)) if m.group(2) else "")
        if given.get(key):
            return given[key].pop(0) if len(given[key]) > 1 else given[key][0]
        return _number_token_words(m.group(1), m.group(2), m.group(3))

    text = re.sub(r"(?<=[ء-يً-ْ])\s*/\s*(?=[ء-ي])", "، ", text or "")
    return _NUM_RE.sub(sub, text)


def spoken_line(sentence: str, nouns: list, cfg, latin: bool = False) -> tuple[str, list]:
    """نص النطق لجملة واحدة كما يرسله التركيب وأداة القياس: الوقف ← الأسماء الأجنبية برسمها (latin) ← الأرقام بالكلمات.
    يعيد (النص، الأسماء المستبدلة). الأرقام بعد الوقف كي لا يُسكَّن آخر رقم بالقاعدة: نطقه من نداء التشكيل بحركته."""
    spoken, used = apply_waqf(sentence), []
    if latin:
        spoken, used = latin_names(spoken, nouns, cfg)
    if cfg is None or cfg.path("reel.tts.numbers.enabled", True):
        spoken = spoken_numbers(spoken, nouns)
    return spoken, used


def split_sentences(text: str) -> list[str]:
    """جمل عند . ؟ ! ؛ لا عند نقطة بين رقمين (1.4: ليس بعدها فراغ) ولا عند الفاصلة العربية «،»."""
    parts = _SENTENCE_END.split((text or "").strip())
    return [p.strip() for p in parts if p and p.strip()]
