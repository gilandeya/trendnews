"""المرحلة الثانية من مسار يوتيوب (Issue #631): سحب نص كل فيديو ناجٍ من
src/youtube_collect.py، واستخلاص ٥-٧ نقاط عربية قصيرة منه عبر نموذج رخيص.

قيد إلزامي من الـIssue: لا نص ترجمة كامل يُكتب على القرص أو يُطبَع أو
يُرفَع -- النص يمرّ في الذاكرة فقط بين fetch_transcript وextract_points ثم
يُهمَل. لا شيء في هذا الملف يستدعي print()/log على متغيّر النص نفسه.

Issue #635 (إصلاح خمسة أعطال بعد التشغيلة الأولى): الطوابع الزمنية كانت
مختلَقة (النموذج يخمّن أرقامًا مستديرة بلا سند)، تحليل JSON النصّي كان هشًّا
(١٩/٢٨ فشلت)، الترجمة إلى العربية لم تُطبَّق دومًا، أسماء الأعلام انكسرت
بخلط حروف، والحرّاس ميّزت المدة لا نوع المحتوى فمرّت نشرات ورياضة. الإصلاح:
أختام زمنية ظاهرة في النص المُدخَل + رفض أي طابع يتجاوز مدة الفيديو، إخراج
مهيكل (tool_use) بدل JSON نصّي، رفض أي حرف غير عربي في الحقول العربية، وحارس
تصنيف موضوع قبل إنفاق نداء الاستخلاص الكامل.
"""
from __future__ import annotations

import json
import logging
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from anthropic import Anthropic, APIError

from . import youtube_collect
from .config import STATE_DIR, Config, env, load_config
from .proxy_config import get_proxy_config

log = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "youtube_extract.md"
POINTS_DIR = STATE_DIR / "youtube_points"

REQUIRED_FIELDS = ["statement", "speaker", "quote_original", "quote_arabic",
                    "timestamp", "type", "topic_hint"]
VALID_TYPES = {"fact", "opinion", "forecast"}

EXTRACT_POINTS_SCHEMA = {
    "name": "extract_points",
    "description": "يستخرج نقاطًا إخبارية عربية موثّقة بطابعها الزمني الحرفي من نص فيديو",
    "input_schema": {
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {"type": "string",
                                      "description": "جملة عربية قصيرة تلخّص النقطة"},
                        "speaker": {"type": "string",
                                    "description": "اسم القائل بالعربية + صفته"},
                        "quote_original": {"type": "string",
                                            "description": "اقتباس حرفي من النص بلغته الأصلية"},
                        "quote_arabic": {"type": "string",
                                          "description": "ترجمة الاقتباس إلى العربية الفصحى"},
                        "timestamp": {
                            "type": "string",
                            "description": (
                                "الختم الزمني المنسوخ حرفيًا من قبل المقطع المقتبَس مباشرة، "
                                "بصيغة MM:SS أو HH:MM:SS كما ظهر في النص تمامًا. لا تقدّره ولا "
                                "تحسبه ولا تقرّبه؛ إن لم تجد ختمًا واضحًا لهذا المقطع اترك الحقل "
                                "نصًّا فارغًا."),
                        },
                        "type": {"type": "string", "enum": sorted(VALID_TYPES)},
                        "topic_hint": {"type": "string", "description": "كلمتان أو ثلاث للموضوع"},
                    },
                    "required": REQUIRED_FIELDS,
                },
            },
        },
        "required": ["points"],
    },
}

TOPIC_CATEGORIES = ("political_analysis", "news_bulletin", "other")

TOPIC_SCHEMA = {
    "name": "classify_video_topic",
    "description": "يصنّف نوع فيديو يوتيوب من عنوانه ومقتطف من نصه، قبل إنفاق نداء الاستخلاص الكامل",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": list(TOPIC_CATEGORIES)},
        },
        "required": ["category"],
    },
}

TOPIC_SYSTEM = """أنت حارس تصنيف يفصل التحليل السياسي عن غيره قبل استخلاص نقاط منه.
تستلم عنوان فيديو ومقتطفًا من أول نصّه، وتصنّفه إلى واحدة من ثلاث فئات فقط:

- political_analysis: حوار أو تحليل أو مقابلة سياسية -- نقاش متعمّق أو تفسير
  أو حوار بين متحدثين حول شأن سياسي أو دبلوماسي أو اقتصادي.
- news_bulletin: نشرة أخبار متتابعة -- سرد أخبار قصيرة الواحدة تلو الأخرى
  بلا تحليل أو نقاش متعمّق، حتى لو كان موضوعها سياسيًا.
- other: أي شيء آخر -- رياضة، فن، سينما، منوّعات، طقس، حوادث فردية (حريق،
  حادث سير) بلا بعد سياسي أو دبلوماسي.

عند الشك بين political_analysis وnews_bulletin: افحص هل هناك نقاش أو تفسير
متصل أطول من مجرّد عرض خبر ثم الانتقال لآخر -- إن كان الجواب نعم فـ
political_analysis."""


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


# ──────────────────────────── التحقق من نقطة ────────────────────────────

_HEBREW_RE = re.compile("[֐-׿]")
_LATIN_RE = re.compile("[A-Za-z]")
# حروف خاصة بالفارسية/الأردية غائبة عن العربية الفصحى -- تقع داخل نطاق
# يونيكود العربي نفسه (٠٦٠٠-٠٦FF) فلا يكفي فحص المدى وحده، يلزم استثناء صريح.
# مكتوبة بترميز \u صراحة (لا حروفًا حرفية) لتفادي خطأ كتابة صامت بسبب اتجاه
# النص من اليمين لليسار عند تحرير هذا الملف لاحقًا:
# PEH TCHEH JEH KEHEH GAF FARSI-YEH VE YEH-BARREE AE TTEHEH DDAL RREH
# NOON-GHUNNA HEH-DOACHASHMEE HEH-WITH-YEH-ABOVE HEH-GOAL
_PERSIAN_ONLY_RE = re.compile(
    "[پچژکگیۋےە"
    "ٹڈڑںھۀہ]"
)

_TIMESTAMP_RE = re.compile(r"^(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)$")


def find_non_arabic_char(text: str) -> str | None:
    """يعيد أول حرف عبري أو لاتيني أو فارسي/أردي غير عربي في النص، أو None
    إن كان عربيًا فصيحًا حصرًا (الأرقام وعلامات الترقيم مسموحة دومًا).
    يُستعمَل لرفض نقاط لم تُترجَم فعلًا (العطل ٣)، ويلتقط تلقائيًا خلط الحروف
    داخل أسماء الأعلام (العطل ٤) لأن الحرف اللاتيني المخلوط يقع ضمن الفحص
    نفسه."""
    for pattern in (_HEBREW_RE, _LATIN_RE, _PERSIAN_ONLY_RE):
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def parse_timestamp(raw: Any) -> int | None:
    """يحلّل طابعًا زمنيًا نصّيًا "[HH:]MM:SS" -- كما يُفترَض أن ينسخه النموذج
    حرفيًا من الختم الظاهر قبل المقطع -- إلى ثوانٍ. يعيد None لأي صيغة غير
    مطابقة أو حقل فارغ/غير نصّي؛ لا نحاول تخمين رقم من نص لا يطابق الصيغة
    (هذا التخمين هو أصل العطل ١)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    match = _TIMESTAMP_RE.match(raw.strip())
    if not match:
        return None
    hours = int(match.group(1)) if match.group(1) else 0
    minutes, seconds = int(match.group(2)), int(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def validate_point(point: Any) -> tuple[bool, str, str]:
    """يتحقق من الحقول الإلزامية والتصنيف واللغة وصيغة الطابع الزمني لنقطة
    واحدة. يعيد (صالحة، سبب الرفض، فئة الرفض) -- الفئة "" عند النجاح، وإلا
    واحدة من "timestamp"/"language"/"other" لتغذية عدّادات stats في run().

    عند النجاح يُستبدَل point["timestamp"] النصّي بعدد الثواني المحلَّل --
    تطبيع لا تحقّق شكلي إضافي، فبقية الأنبوب (المقارنة بمدة الفيديو، ثم
    الإخراج النهائي) يحتاج رقمًا لا نصًّا."""
    if not isinstance(point, dict):
        return False, "عنصر ليس كائن JSON", "other"
    for name in REQUIRED_FIELDS:
        if name not in point:
            return False, f"حقل ناقص: {name}", "other"
    for name in ("statement", "speaker", "quote_original", "quote_arabic", "type", "topic_hint"):
        value = point.get(name)
        if not isinstance(value, str) or not value.strip():
            return False, f"حقل فارغ أو غير نصّي: {name}", "other"
    if point["type"] not in VALID_TYPES:
        return False, f"تصنيف غير صالح: {point['type']}", "other"

    # العطل ٣+٤: أي حرف عبري/لاتيني/فارسي-غير-عربي هنا يعني أن الترجمة لم
    # تقع فعلًا أو أن اسم علم انكسر بخلط حروف. quote_original مستثنى عمدًا
    # -- هو بلغة الفيديو الأصلية، الدليل لا الترجمة.
    for name in ("statement", "speaker", "quote_arabic"):
        bad_char = find_non_arabic_char(point[name])
        if bad_char:
            return False, f"حرف غير عربي ({bad_char!r}) في {name}", "language"

    seconds = parse_timestamp(point.get("timestamp"))
    if seconds is None:
        return (False, f"طابع زمني غير صالح الصيغة أو فارغ: {point.get('timestamp')!r}",
                "timestamp")
    point["timestamp"] = seconds

    return True, "", ""


# ──────────────────────────── سحب النص ────────────────────────────


def _format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_transcript(fetched) -> str:
    """يصوغ مقاطع الترجمة بختم زمني ظاهر قبل كل مقطع (العطل ١) -- بلا هذا
    كان النموذج يمرَّر نصًّا متصلًا بلا أختام فيؤلّف طوابع مستديرة الشكل
    (٦٠، ١٨٠، ٣٦٠٠) لا سند فعلي لها في النص."""
    return "\n".join(f"[{_format_timestamp(segment.start)}] {segment.text}"
                      for segment in fetched)


def fetch_transcript(video_id: str, proxy_config, session: requests.Session | None = None
                      ) -> tuple[str | None, str | None]:
    """يعيد (النص المصوغ بأختامه الزمنية، رمز اللغة) عند النجاح، أو (None،
    سبب الفشل). بلغته الأصلية دومًا -- لا نطلب ترجمة يوتيوب الآلية الرديئة؛
    الترجمة إلى العربية تقع لاحقًا داخل نموذج الاستخلاص على النص الأصلي."""
    from youtube_transcript_api import (
        IpBlocked,
        NoTranscriptFound,
        RequestBlocked,
        TranscriptsDisabled,
        VideoUnavailable,
        YouTubeTranscriptApi,
    )

    try:
        ytt_api = (YouTubeTranscriptApi(proxy_config=proxy_config, http_client=session)
                   if session is not None else YouTubeTranscriptApi(proxy_config=proxy_config))
        transcript_list = ytt_api.list(video_id)
        try:
            transcript = next(iter(transcript_list))
        except StopIteration:
            return None, "لا نص متاح: لا مسارات ترجمة للفيديو"
        fetched = transcript.fetch()
        text = format_transcript(fetched)
        return text, transcript.language_code
    except (IpBlocked, RequestBlocked) as exc:
        return None, f"محجوب من يوتيوب: {exc}"
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as exc:
        return None, f"لا نص متاح: {exc}"
    except Exception as exc:  # noqa: BLE001 -- الفشل الصامت ممنوع، كل عطل يُسجَّل
        return None, f"خطأ غير متوقَّع أثناء سحب النص: {exc}"


# ──────────────────────────── حارس الموضوع ────────────────────────────


def classify_topic(video_title: str, transcript_excerpt: str, cfg: Config,
                    client: Anthropic | None = None) -> tuple[str, str | None]:
    """نداء قصير جدًا (العنوان + مقتطف من أول النص) يصنّف الفيديو قبل إنفاق
    نداء الاستخلاص الكامل عليه (العطل ٥) -- الحرّاس السابقة ميّزت المدة لا
    نوع المحتوى، فمرّت نشرات ورياضة نجت في المدة لكنها لا تحمل تحليلًا.
    يعيد (التصنيف، سبب فشل النداء إن حدث). فشل النداء لا يُسقِط الفيديو
    ويُفترَض معه أنه صالح للاستخلاص -- عطل شبكي عابر ليس دليلًا على أن
    الفيديو نشرة أو رياضة، وإسقاطه صامتًا لهذا السبب يناقض مبدأ المشروع في
    عدم الفشل الصامت."""
    model = cfg.path("youtube.extract.topic_guard_model",
                      cfg.path("youtube.extract.model", "claude-haiku-4-5-20251001"))
    excerpt_chars = cfg.path("youtube.extract.topic_guard_excerpt_chars", 2000)
    client = client or Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=50,
            tools=[TOPIC_SCHEMA],
            tool_choice={"type": "tool", "name": "classify_video_topic"},
            system=TOPIC_SYSTEM,
            messages=[{"role": "user", "content":
                       f"العنوان: {video_title}\n\nمقتطف من النص:\n{transcript_excerpt[:excerpt_chars]}"}],
            # لا تُضِف temperature -- نماذج هذا المشروع ترفضها بـ400.
        )
    except APIError as exc:
        return "political_analysis", f"فشل نداء حارس الموضوع: {exc}"

    data = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
    category = data.get("category") if isinstance(data, dict) else None
    if category not in TOPIC_CATEGORIES:
        return "political_analysis", None
    return category, None


# ──────────────────────────── الاستخلاص عبر النموذج ────────────────────────────


def extract_points(video_title: str, transcript_text: str, language: str, duration_seconds: int,
                    cfg: Config, client: Anthropic | None = None
                    ) -> tuple[list[dict], list[dict], str | None]:
    """نداء نموذج رخيص واحد لكل فيديو عبر إخراج مهيكل (tool_use بمخطط
    مُعرَّف) بدل طلب JSON نصًّا (العطل ٢) -- النموذج يملأ حقولًا مُعرَّفة
    فلا يستطيع كسر البنية أصلًا. عند غياب إخراج مهيكل صالح: محاولة واحدة
    إضافية، ثم فشل مسجَّل مع أول ٥٠٠ حرف من أي نص مخرَج للتشخيص.

    يعيد (النقاط الصالحة، النقاط المرفوضة كل منها بسببها وفئتها، سبب فشل
    النداء العام إن حدث -- None عند النجاح ولو بلا نقاط)."""
    model = cfg.path("youtube.extract.model", "claude-haiku-4-5-20251001")
    max_tokens = cfg.path("youtube.extract.max_tokens", 2000)
    max_retries = cfg.path("youtube.extract.max_retries", 2)
    client = client or Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))

    raw_points: list | None = None
    last_snippet = ""
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                tools=[EXTRACT_POINTS_SCHEMA],
                tool_choice={"type": "tool", "name": "extract_points"},
                system=load_prompt(),
                messages=[{"role": "user", "content":
                           f"لغة النص الأصلية: {language}\n\nالنص الكامل للفيديو، مع أختامه "
                           f"الزمنية الظاهرة قبل كل مقطع:\n{transcript_text}"}],
                # لا تُضِف temperature -- نماذج هذا المشروع ترفضها بـ400.
            )
        except APIError as exc:
            return [], [], f"فشل نداء النموذج: {exc}"

        data = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
        candidate = data.get("points") if isinstance(data, dict) else None
        if isinstance(candidate, list):
            raw_points = candidate
            break
        last_snippet = "".join(b.text for b in resp.content
                                if getattr(b, "type", "") == "text")[:500]
        log.warning("محاولة %d/%d: لم يُعِد النموذج إخراجًا مهيكلًا صالحًا لـ%r",
                    attempt, max_retries, video_title[:60])

    if raw_points is None:
        return ([], [],
                f"تعذّر الحصول على إخراج مهيكل صالح بعد {max_retries} محاولة/محاولات: "
                f"{last_snippet!r}")

    valid: list[dict] = []
    rejected: list[dict] = []
    for raw in raw_points:
        ok, reason, kind = validate_point(raw)
        if not ok:
            rejected.append({"reason": reason, "kind": kind})
            log.warning("نقطة مرفوضة من %r (%s)", video_title[:60], reason)
            continue
        # الحارس الأخير الإلزامي (العطل ١، بند ج): لا تنازل عنه مهما كانت
        # صيغة الطابع سليمة -- سليم الصيغة لا يعني داخل مدة الفيديو فعلًا.
        if raw["timestamp"] > duration_seconds:
            reason = (f"طابع زمني {raw['timestamp']}ث يتجاوز مدة الفيديو "
                      f"{duration_seconds}ث")
            rejected.append({"reason": reason, "kind": "timestamp"})
            log.warning("نقطة مرفوضة من %r (%s)", video_title[:60], reason)
            continue
        valid.append(raw)
    return valid, rejected, None


# ──────────────────────────── التشغيلة الكاملة ────────────────────────────


def run(cfg: Config | None = None, youtube_api_key: str | None = None,
        anthropic_client: Anthropic | None = None, now: datetime | None = None) -> dict:
    cfg = cfg or load_config()
    now = now or datetime.now(timezone.utc)

    collected = youtube_collect.run(cfg, api_key=youtube_api_key, now=now)
    videos = collected["videos"]
    failed: list[dict] = list(collected["failed"])
    points: list[dict] = []
    transcripts_ok = 0
    transcripts_failed = 0
    videos_rejected_topic = 0
    points_rejected_timestamp = 0
    points_rejected_language = 0

    proxy_cfg = get_proxy_config()
    total_bytes = 0
    session = requests.Session()

    def _track_bytes(response, *args, **kwargs):  # noqa: ANN001 -- توقيع خطّاف requests
        nonlocal total_bytes
        total_bytes += len(response.content)

    session.hooks["response"].append(_track_bytes)

    sleep_range = tuple(cfg.path("youtube.extract.transcript_sleep_range", [2.0, 5.0]))

    for i, video in enumerate(videos):
        print(f"استخلاص: {video.video_title[:60]} ({video.channel})", file=sys.stderr)
        text, lang_or_reason = fetch_transcript(video.video_id, proxy_cfg, session)
        if text is None:
            transcripts_failed += 1
            failed.append({"channel": video.channel, "video_id": video.video_id,
                           "title": video.video_title, "reason": lang_or_reason})
        else:
            transcripts_ok += 1
            category, classify_error = classify_topic(video.video_title, text, cfg,
                                                        anthropic_client)
            if classify_error:
                log.warning("حارس الموضوع فشل لـ%r، يُستخلَص احتياطيًا بدل إسقاطه صامتًا: %s",
                            video.video_title[:60], classify_error)
            if category != "political_analysis":
                videos_rejected_topic += 1
                failed.append({"channel": video.channel, "video_id": video.video_id,
                               "title": video.video_title,
                               "reason": f"أُهمل قبل الاستخلاص -- حارس الموضوع صنّفه: {category}"})
                print(f"  → أُهمل (حارس الموضوع: {category})", file=sys.stderr)
            else:
                valid_points, rejected_points, error = extract_points(
                    video.video_title, text, lang_or_reason, video.duration_seconds,
                    cfg, anthropic_client)
                if error:
                    failed.append({"channel": video.channel, "video_id": video.video_id,
                                   "title": video.video_title, "reason": error})
                for r in rejected_points:
                    failed.append({"channel": video.channel, "video_id": video.video_id,
                                   "title": video.video_title,
                                   "reason": f"نقطة مرفوضة ({r['kind']}): {r['reason']}"})
                    if r["kind"] == "timestamp":
                        points_rejected_timestamp += 1
                    elif r["kind"] == "language":
                        points_rejected_language += 1
                for p in valid_points:
                    points.append({
                        "video_id": video.video_id,
                        "channel": video.channel,
                        "bloc": video.bloc,
                        "language": lang_or_reason,
                        "video_title": video.video_title,
                        "video_url": video.video_url,
                        "duration_seconds": video.duration_seconds,
                        "statement": p["statement"],
                        "speaker": p["speaker"],
                        "quote_original": p["quote_original"],
                        "quote_arabic": p["quote_arabic"],
                        "timestamp": p["timestamp"],
                        "type": p["type"],
                        "topic_hint": p["topic_hint"],
                    })
                print(f"  → {len(valid_points)} نقطة", file=sys.stderr)
        text = None  # إهمال صريح -- لا يُحتفَظ بالنص بعد هذه النقطة
        if i < len(videos) - 1:
            time.sleep(random.uniform(*sleep_range))

    return {
        "run_date": now.strftime("%Y-%m-%d"),
        "stats": {
            "channels_checked": collected["stats"]["channels_checked"],
            "videos_found": collected["stats"]["videos_found"],
            "passed_guards": collected["stats"]["passed_guards"],
            "transcripts_ok": transcripts_ok,
            "transcripts_failed": transcripts_failed,
            "videos_rejected_topic": videos_rejected_topic,
            "points_extracted": len(points),
            "points_rejected_timestamp": points_rejected_timestamp,
            "points_rejected_language": points_rejected_language,
            "proxy_bandwidth_mb": round(total_bytes / (1024 * 1024), 3),
        },
        "failed": failed,
        "points": points,
    }


def save_output(result: dict) -> Path:
    POINTS_DIR.mkdir(parents=True, exist_ok=True)
    path = POINTS_DIR / f"{result['run_date']}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    result = run()
    path = save_output(result)
    stats = result["stats"]
    print(f"ملف النقاط: {path}")
    print(f"القنوات: {stats['channels_checked']} · ضمن النافذة: {stats['videos_found']} "
          f"· ناجية بعد الحرّاس: {stats['passed_guards']}")
    print(f"نصوص ناجحة: {stats['transcripts_ok']} · فاشلة: {stats['transcripts_failed']}")
    print(f"أُهمل قبل الاستخلاص (حارس الموضوع): {stats['videos_rejected_topic']}")
    print(f"نقاط مستخلَصة: {stats['points_extracted']} "
          f"· مرفوضة (طابع زمني): {stats['points_rejected_timestamp']} "
          f"· مرفوضة (لغة): {stats['points_rejected_language']}")
    print(f"استهلاك البروكسي التقديري: {stats['proxy_bandwidth_mb']} ميجابايت")
    if result["failed"]:
        print(f"تعذّر: {len(result['failed'])}")
        for entry in result["failed"]:
            label = entry.get("title") or entry.get("video_id") or "?"
            print(f"  - {entry['channel']}: {label}: {entry['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
