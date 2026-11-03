"""قياس: هل يكفي عنوان الفيديو ووصفه لمعرفة مواضيعه؟ (خطة «المواضيع من الوصف»، الخطوة 1)

قرار صاحب المشروع (3/11): أن تُستنتج المواضيع من العناوين والأوصاف وحدها، ولا يُجلب النص الكامل إلا لفيديوهات
الموضوع المختار. قبل البناء نقيس على فيديوهات حقيقية: كم منها يحمل وصفًا يصف مواضيعه، وكم فيه فهرس زمني يقسّم
الدقائق. هذه الخطوة تحفظ العنوان والوصف والمدة والفهرس لكل فيديو رفعته القنوات في آخر `days` أيام، ولا تقرر شيئًا.

تجري داخل الجمع (`youtube_extract.main`) لأن الجمع وحده يحمل مفتاح يوتيوب ويودع مجلد المقاطع في المستودع الخاص؛
والوصف كلام قناة فمكانه المستودع الخاص لا العام. لا بروكسي ولا نموذج: واجهة يوتيوب الرسمية وحدها (بضع وحدات من الحصة).
لا ترفع أبدًا: عطلها سطر في السجل ولا يمسّ الجمع.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("youtube_meta_probe")

# سطر فهرس زمني: «12:30 عنوان» أو «1:02:15 - عنوان» في أول السطر
_CHAPTER_RE = re.compile(r"^\s*[\(\[]?((?:\d{1,2}:)?\d{1,2}:\d{2})[\)\]]?\s*[-–—:|•]?\s*(.+?)\s*$")


def _seconds(stamp: str) -> int:
    parts = [int(p) for p in stamp.split(":")]
    total = 0
    for p in parts:
        total = total * 60 + p
    return total


def chapters(description: str) -> list[dict]:
    """فهرس زمني من الوصف: سطران فأكثر بطوابع تصاعدية أولها 0:00 (هكذا يعدّها يوتيوب فصولًا)، وإلا قائمة فارغة.
    طابع وحيد في الوصف («شاهد من 12:30») ليس فهرسًا."""
    rows = []
    for line in (description or "").splitlines():
        m = _CHAPTER_RE.match(line)
        if m and m.group(2).strip():
            rows.append({"start": _seconds(m.group(1)), "title": m.group(2).strip()})
    if len(rows) < 2 or rows[0]["start"] != 0:
        return []
    if any(b["start"] <= a["start"] for a, b in zip(rows, rows[1:])):
        return []
    return rows


def probe_dir() -> Path:
    from . import youtube_transcripts
    return youtube_transcripts.bites_dir() / "meta_probe"


def run(cfg: Any, now: datetime | None = None, api_key: str | None = None,
        fetch_ids: Callable | None = None, fetch_details: Callable | None = None) -> dict | None:
    """يجمع بيانات فيديوهات آخر `days` أيام لكل قناة نشطة ويدمجها في ملف اليوم (تشغيلات اليوم المتعددة تضيف ولا
    تكرر). يعيد ملخّصًا للسجل، أو None إن كان مطفأً أو بلا مفتاح."""
    pcfg = cfg.path("youtube.meta_probe") or {}
    if not pcfg.get("enabled"):
        return None
    from . import youtube_collect
    from .config import env
    api_key = api_key or env("YOUTUBE_API_KEY")
    if not api_key:
        log.info("قياس الوصف: لا مفتاح يوتيوب")
        return None
    now = now or datetime.now(timezone.utc)
    fetch_ids = fetch_ids or youtube_collect.fetch_playlist_video_ids
    fetch_details = fetch_details or youtube_collect.fetch_videos_details
    hours = float(pcfg.get("days", 3)) * 24

    path = probe_dir() / f"{now.strftime('%Y-%m-%d')}.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        saved = {}
    videos: dict = dict(saved.get("videos") or {})
    errors: list[str] = []
    for ch in cfg.get("channels", []):
        if not ch.get("active", True):
            continue
        try:
            ids = fetch_ids(youtube_collect.uploads_playlist_id(ch["channel_id"]), api_key, hours, now)
            items = fetch_details([i for i in ids if i not in videos], api_key) if ids else []
        except Exception as exc:  # noqa: BLE001 — قناة متعطلة لا توقف القياس
            errors.append(f"{ch.get('name')}: {str(exc)[:120]}")
            continue
        for it in items:
            sn = it.get("snippet") or {}
            desc = sn.get("description") or ""
            try:
                dur = youtube_collect.parse_iso8601_duration((it.get("contentDetails") or {}).get("duration") or "")
            except ValueError:
                dur = None
            videos[it.get("id")] = {
                "channel": ch.get("name"), "bloc": ch.get("bloc"), "orientation": ch.get("orientation"), "language": ch.get("language"),
                "published": sn.get("publishedAt"), "duration_seconds": dur,
                "live": sn.get("liveBroadcastContent") not in (None, "none"),
                "title": sn.get("title") or "", "description": desc, "tags": sn.get("tags") or [],
                "chapters": chapters(desc),
            }
    out = {"generated_at": now.isoformat(), "days": pcfg.get("days", 3), "videos": videos, "errors": errors}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"videos": len(videos), "with_chapters": sum(1 for v in videos.values() if v["chapters"]),
            "errors": len(errors), "path": str(path)}


def run_safe(cfg: Any) -> None:
    """غلاف الجمع: لا يرفع أبدًا، وسطر واحد في المخرجات."""
    try:
        res = run(cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"قياس الوصف: تعذّر — {str(exc)[:150]}")
        return
    if res:
        print(f"قياس الوصف: {res['videos']} فيديو، منها {res['with_chapters']} بفهرس زمني"
              + (f" · تعذّر {res['errors']} قناة" if res["errors"] else ""))
