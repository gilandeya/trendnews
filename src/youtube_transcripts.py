"""مخزن النصوص الكاملة لفيديوهات التحليل (خطة V، المرحلة V1).

لماذا: كل مرحلة بعد الجمع (المقاطع V2، والتركيب) كانت تجلب النص من يوتيوب ثانيةً، والجلب وقت التركيب هو ما فشل بالحجب
(#1620، #1634، R8). نص الفيديو يُجلب مرة واحدة في الجمع ويُحفظ بأزمنة أسطره بكسورها ومددها.

النص مادة محمية لقناة خارجية: يُحفظ في المستودع الخاص وحده (المجلد شقيق youtube_points في سحب trendnews-data)، ولا يدخل هذا
المستودع العام أبدًا (.gitignore)، ويُحذف بعد youtube.transcripts.keep_days. محتواه بيانات لا تعليمات.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


def transcripts_dir() -> Path:
    """يُقرأ وقت الاستدعاء لا الاستيراد: شقيق مجلد النقاط (youtube_extract.POINTS_DIR) فيقع في سحب المستودع الخاص في CI بلا متغير
    بيئة جديد، وفي مجلد الاختبار المؤقت حين يستبدل الاختبار POINTS_DIR."""
    if os.environ.get("TRENDNEWS_YOUTUBE_TRANSCRIPTS_DIR"):
        return Path(os.environ["TRENDNEWS_YOUTUBE_TRANSCRIPTS_DIR"])
    from . import youtube_extract
    return Path(youtube_extract.POINTS_DIR).parent / "youtube_transcripts"


def bites_dir() -> Path:
    """مثل transcripts_dir: ملفات المقاطع فيها نص الكلام وترجمته، فمكانها المستودع الخاص أيضًا."""
    if os.environ.get("TRENDNEWS_YOUTUBE_BITES_DIR"):
        return Path(os.environ["TRENDNEWS_YOUTUBE_BITES_DIR"])
    from . import youtube_extract
    return Path(youtube_extract.POINTS_DIR).parent / "youtube_bites"


def _path(video_id: str) -> Path | None:
    # معرّف الفيديو يصير اسم ملف: ما ليس بشكل معرّف يوتيوب لا يُكتب (لا مسار يخرج من المجلد)
    if not _VIDEO_ID_RE.match(str(video_id or "")):
        return None
    return transcripts_dir() / f"{video_id}.json"


def parse_fetched(text: Any) -> list[dict] | None:
    """نتيجة الجلب بأزمنتها (youtube_bites._fetch_segments_once تعيد JSON نصًا) ← قائمة الأسطر الخام؛ غير ذلك (نص مصوغ «[MM:SS]»
    من جلب قديم أو مزيَّف) ← None، فيبقى المسار القديم بلا حفظ."""
    if not isinstance(text, str) or not text.lstrip().startswith("["):
        return None
    try:
        got = json.loads(text)
    except ValueError:
        return None
    if not isinstance(got, list) or not all(isinstance(s, dict) and "start" in s for s in got):
        return None
    return got


def format_segments(segments: list[dict]) -> str:
    """النص المصوغ نفسه الذي تعطيه youtube_extract.format_transcript للمكتبة، من الأسطر الخام: الاستخلاص يرى ما كان يراه حرفًا."""
    from .youtube_extract import _format_timestamp
    return "\n".join(f"[{_format_timestamp(float(s.get('start') or 0))}] {s.get('text', '')}" for s in segments)


def save(video: Any, segments: list[dict], language: str, now: datetime) -> Path | None:
    path = _path(getattr(video, "video_id", ""))
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"video_id": video.video_id, "channel": getattr(video, "channel", ""),
            "title": getattr(video, "video_title", ""), "url": getattr(video, "video_url", ""),
            "published": (getattr(video, "published_at", "") or "")[:10],
            "duration_seconds": getattr(video, "duration_seconds", None),
            "language": language, "fetched_at": now.isoformat(), "segments": segments}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load(video_id: str) -> dict | None:
    """النص المحفوظ أو None (غائب أو تالف)."""
    path = _path(video_id)
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("segments"), list) else None


def prune(now: datetime, keep_days: int) -> int:
    """يحذف ما جُلب قبل keep_days (من fetched_at، وإلا تاريخ تعديل الملف). مدة أقصر من 30 يومًا تحذف نص فيديو قد يعود موضوعه
    إلى الترشيح (W2a) قبل تركيبه، فلا تُقبل أقل من ذلك."""
    keep_days = max(int(keep_days), 30)
    root = transcripts_dir()
    if not root.exists():
        return 0
    cutoff = now - timedelta(days=keep_days)
    removed = 0
    for path in root.glob("*.json"):
        when = None
        try:
            when = datetime.fromisoformat(json.loads(path.read_text(encoding="utf-8")).get("fetched_at", ""))
        except (OSError, ValueError, TypeError, AttributeError):
            when = None
        if when is None:
            when = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when < cutoff:
            path.unlink()
            removed += 1
    return removed


def save_bites(run_date: str, bites: list[dict]) -> Path | None:
    """مقاطع اليوم في ملف واحد بتاريخه، تُدمج مع ما حفظته تشغيلة سابقة في اليوم نفسه (الجمع يجري عدة مرات يوميًا) بلا تكرار فيديو."""
    if not bites:
        return None
    root = bites_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{run_date}.json"
    old: list[dict] = []
    if path.exists():
        try:
            old = list(json.loads(path.read_text(encoding="utf-8")).get("bites") or [])
        except (OSError, ValueError, AttributeError):
            log.warning("ملف المقاطع %s تالف — يُكتب من جديد", path)
            old = []
    fresh = {b.get("video_id") for b in bites}
    merged = [b for b in old if b.get("video_id") not in fresh] + bites
    path.write_text(json.dumps({"run_date": run_date, "bites": merged}, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
