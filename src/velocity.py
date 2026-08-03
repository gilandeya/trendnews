"""قياس *سرعة* انتشار الخبر، لا حجم تغطيته فقط.

الفرق جوهري:
  • خبر انتقل من مصدرين إلى عشرة خلال ساعتين  ← ينفجر الآن
  • خبر ثابت عند عشرة مصادر منذ يومين        ← انتهى

المؤشر القديم يساوي بينهما. هذه الوحدة تحفظ عدد المصادر لكل خبر في كل
تشغيلة، فتعرف في التشغيلة التالية كم نما — وهذا هو الترند الحقيقي.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from .config import STATE_DIR
from .rank import similarity, tokens

log = logging.getLogger(__name__)

VELOCITY_FILE = STATE_DIR / "velocity.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load() -> list[dict]:
    if not VELOCITY_FILE.exists():
        return []
    try:
        return json.loads(VELOCITY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("ملف السرعة تالف — سيُعاد إنشاؤه")
        return []


def save(entries: list[dict], keep_hours: int = 96) -> None:
    cutoff = _now() - timedelta(hours=keep_hours)
    fresh = [
        e for e in entries
        if datetime.fromisoformat(e["last_seen"]) >= cutoff
    ]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    VELOCITY_FILE.write_text(
        json.dumps(fresh, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    log.info("سجل السرعة: %d خبر متتبَّع", len(fresh))


def _find(entries: list[dict], sig: set[str], threshold: float) -> dict | None:
    best, best_score = None, threshold
    for entry in entries:
        score = similarity(sig, set(entry.get("tokens", [])))
        if score >= best_score:
            best, best_score = entry, score
    return best


def observe(title: str, source_count: int, entries: list[dict],
            threshold: float = 0.55) -> dict:
    """
    يسجّل مشاهدة خبر ويعيد مقاييس سرعته.

    يعيد:
      velocity  — مصادر جديدة في الساعة (مطبّعة من 0 إلى 1)
      age_hours — منذ متى ونحن نتتبّع هذا الخبر
      stale     — هل توقّف نموه؟
      is_new    — أول مشاهدة
    """
    sig = tokens(title)
    now = _now()
    entry = _find(entries, sig, threshold)

    if entry is None:
        entries.append({
            "tokens": sorted(sig),
            "sources": source_count,
            "peak": source_count,
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
        })
        # أول مشاهدة: خبر يظهر فجأة عند عدة مصادر يستحق دفعة متواضعة
        return {
            "velocity": min(1.0, max(0, source_count - 1) / 5.0),
            "age_hours": 0.0,
            "stale": False,
            "is_new": True,
            "growth": source_count,
        }

    last = datetime.fromisoformat(entry["last_seen"])
    first = datetime.fromisoformat(entry["first_seen"])
    elapsed = max((now - last).total_seconds() / 3600, 0.25)
    age = (now - first).total_seconds() / 3600

    growth = source_count - entry["sources"]
    per_hour = growth / elapsed

    entry["tokens"] = sorted(set(entry["tokens"]) | sig)
    entry["sources"] = source_count
    entry["peak"] = max(entry.get("peak", 0), source_count)
    entry["last_seen"] = now.isoformat()

    # ثلاثة مصادر جديدة في الساعة = انفجار كامل
    velocity = max(0.0, min(1.0, per_hour / 3.0))
    stale = age >= 12 and growth <= 0

    return {
        "velocity": velocity,
        "age_hours": age,
        "stale": stale,
        "is_new": False,
        "growth": growth,
    }
