"""المرحلة الثانية من مسار يوتيوب (Issue #631): سحب نص كل فيديو ناجٍ من
src/youtube_collect.py، واستخلاص ٥-٧ نقاط عربية قصيرة منه عبر نموذج رخيص.

قيد إلزامي من الـIssue: لا نص ترجمة كامل يُكتب على القرص أو يُطبَع أو
يُرفَع -- النص يمرّ في الذاكرة فقط بين fetch_transcript وextract_points ثم
يُهمَل. لا شيء في هذا الملف يستدعي print()/log على متغيّر النص نفسه.
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


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


# ──────────────────────────── تحليل مخرج النموذج ────────────────────────────


def parse_points(text: str) -> list[dict]:
    """يحلّل مخرج النموذج JSON، بتنظيف أسيجة ```json إن وُجدت. يقبل مصفوفة
    مباشرة أو كائنًا بمفتاح "points"."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end == -1:
            start, end = cleaned.find("["), cleaned.rfind("]")
            if start == -1 or end == -1:
                raise
        data = json.loads(cleaned[start:end + 1])
    if isinstance(data, dict):
        data = data.get("points", [])
    if not isinstance(data, list):
        raise ValueError("مخرج النموذج ليس قائمة نقاط")
    return data


def validate_point(point: Any) -> tuple[bool, str]:
    """يتحقق من الحقول الإلزامية والتصنيف لنقطة واحدة. يعيد (صالحة، سبب
    الرفض إن لم تكن)."""
    if not isinstance(point, dict):
        return False, "عنصر ليس كائن JSON"
    for name in REQUIRED_FIELDS:
        if name not in point:
            return False, f"حقل ناقص: {name}"
    for name in ("statement", "speaker", "quote_original", "quote_arabic", "type", "topic_hint"):
        value = point.get(name)
        if not isinstance(value, str) or not value.strip():
            return False, f"حقل فارغ أو غير نصّي: {name}"
    if point["type"] not in VALID_TYPES:
        return False, f"تصنيف غير صالح: {point['type']}"
    timestamp = point.get("timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return False, "timestamp ليس رقمًا"
    if timestamp < 0:
        return False, "timestamp سالب"
    return True, ""


# ──────────────────────────── سحب النص ────────────────────────────


def fetch_transcript(video_id: str, proxy_config, session: requests.Session | None = None
                      ) -> tuple[str | None, str | None]:
    """يعيد (النص المسلسل، رمز اللغة) عند النجاح، أو (None، سبب الفشل).
    بلغته الأصلية دومًا -- لا نطلب ترجمة يوتيوب الآلية الرديئة؛ الترجمة إلى
    العربية تقع لاحقًا داخل نموذج الاستخلاص على النص الأصلي."""
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
        text = " ".join(segment.text for segment in fetched)
        return text, transcript.language_code
    except (IpBlocked, RequestBlocked) as exc:
        return None, f"محجوب من يوتيوب: {exc}"
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as exc:
        return None, f"لا نص متاح: {exc}"
    except Exception as exc:  # noqa: BLE001 -- الفشل الصامت ممنوع، كل عطل يُسجَّل
        return None, f"خطأ غير متوقَّع أثناء سحب النص: {exc}"


# ──────────────────────────── الاستخلاص عبر النموذج ────────────────────────────


def extract_points(video_title: str, transcript_text: str, language: str, cfg: Config,
                    client: Anthropic | None = None) -> tuple[list[dict], str | None]:
    """نداء نموذج رخيص واحد لكل فيديو. يعيد (النقاط الصالحة، سبب فشل النداء
    أو التحليل إن حدث -- None عند النجاح ولو بلا نقاط)."""
    model = cfg.path("youtube.extract.model", "claude-haiku-4-5-20251001")
    max_tokens = cfg.path("youtube.extract.max_tokens", 2000)
    client = client or Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=load_prompt(),
            messages=[{"role": "user", "content":
                       f"لغة النص الأصلية: {language}\n\nالنص الكامل للفيديو:\n{transcript_text}"}],
        )
    except APIError as exc:
        return [], f"فشل نداء النموذج: {exc}"

    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    try:
        raw_points = parse_points(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return [], f"تعذّر تحليل مخرج النموذج: {exc}"

    valid: list[dict] = []
    for raw in raw_points:
        ok, reason = validate_point(raw)
        if ok:
            valid.append(raw)
        else:
            log.warning("نقطة مرفوضة من %r (%s)", video_title[:60], reason)
    return valid, None


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
            valid_points, error = extract_points(
                video.video_title, text, lang_or_reason, cfg, anthropic_client)
            if error:
                failed.append({"channel": video.channel, "video_id": video.video_id,
                               "title": video.video_title, "reason": error})
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
            "points_extracted": len(points),
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
    print(f"نقاط مستخلَصة: {stats['points_extracted']}")
    print(f"استهلاك البروكسي التقديري: {stats['proxy_bandwidth_mb']} ميجابايت")
    if result["failed"]:
        print(f"تعذّر: {len(result['failed'])}")
        for entry in result["failed"]:
            label = entry.get("title") or entry.get("video_id") or "?"
            print(f"  - {entry['channel']}: {label}: {entry['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
