"""تخزين المسودات وذاكرة المنشورات السابقة (لمنع التكرار)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import DRAFTS_DIR, STATE_DIR
from .rank import similarity, tokens

log = logging.getLogger(__name__)

HISTORY_FILE = STATE_DIR / "history.json"


# ──────────────────────────── ذاكرة التكرار ────────────────────────────


def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("ملف السجل تالف — سيُعاد إنشاؤه")
        return []


def save_history(entries: list[dict], keep_days: int) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    fresh = [
        e for e in entries
        if datetime.fromisoformat(e["seen_at"]) >= cutoff
    ]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def remember(entries: list[dict], title: str, link: str,
             posted_title: str | None = None, region: str = "",
             score: float = 0.0, bucket: str = "") -> None:
    entries.append({
        "score": round(float(score), 2),
        "bucket": bucket,
        "tokens": sorted(tokens(title)),
        "link": link,
        "title": title[:160],
        "posted_title": (posted_title or "")[:160],
        "region": region,
        "seen_at": datetime.now(timezone.utc).isoformat(),
    })


def peak_score(entries: list[dict], hours: int = 24) -> float:
    """
    أعلى مؤشر سُجّل لمسودة خلال آخر ساعات محددة.

    يُستخدم لقياس «قوة اليوم»: إن كان أفضل ما لدينا الآن نصف ما أنتجناه
    صباحًا، فاليوم فقير — ويصبح فرض التنويع أجدى من مطاردة الأقوى.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    best = 0.0
    for entry in entries:
        try:
            when = datetime.fromisoformat(entry.get("seen_at", ""))
        except ValueError:
            continue
        if when >= cutoff:
            best = max(best, float(entry.get("score", 0) or 0))
    return best


def recent_regions(entries: list[dict], count: int) -> list[str]:
    """
    مناطق آخر المسودات المولّدة.

    تُستخدم للتناوب: تصنيف «الخفيف» يضم غرائب وطعامًا وثقافة وآثارًا،
    وله فتحة واحدة في كل دفعة. بلا تناوب سيبتلع أقواها كل الفتحات
    فلا يرى القارئ بقية الموضوعات أبدًا.
    """
    ordered = sorted(entries, key=lambda e: e.get("seen_at", ""), reverse=True)
    return [e.get("region", "") for e in ordered[:count] if e.get("region")]


def find_previous(entries: list[dict], title: str, link: str,
                  threshold: float) -> dict | None:
    """يعيد المنشور السابق عن الحدث نفسه إن وُجد."""
    sig = tokens(title)
    for entry in entries:
        if entry.get("link") == link:
            return entry
        if similarity(sig, set(entry.get("tokens", []))) >= threshold:
            return entry
    return None


def is_duplicate(entries: list[dict], title: str, link: str,
                 threshold: float) -> bool:
    return find_previous(entries, title, link, threshold) is not None


# ──────────────────────────── المسودات ────────────────────────────


def draft_dir(when: datetime | None = None) -> Path:
    when = when or datetime.now(timezone.utc)
    return DRAFTS_DIR / when.strftime("%Y-%m-%d")


def save_draft(draft: dict) -> Path:
    folder = draft_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{draft['id']}.json"
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_draft(draft_id: str) -> tuple[Path, dict] | None:
    for path in sorted(DRAFTS_DIR.glob(f"*/{draft_id}.json")):
        return path, json.loads(path.read_text(encoding="utf-8"))
    return None


def pending_drafts() -> list[tuple[Path, dict]]:
    out = []
    for path in sorted(DRAFTS_DIR.glob("*/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("status") == "pending":
            out.append((path, data))
    return out


def update_draft(path: Path, **changes) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


# ──────────────────────────── مرشّحو الاختيار (preselect) ─────────────────
# بنية مطابقة لتخزين المسودات أعلاه، لكن في state/ لا drafts/: مرشّح غير
# مختار بلا صياغة ولا صورة — حجمه تافه، وبقاؤه في drafts/ لا يفيد شيئًا
# (Issue #280).

CANDIDATES_DIR = STATE_DIR / "candidates"


def candidate_dir(when: datetime | None = None) -> Path:
    when = when or datetime.now(timezone.utc)
    return CANDIDATES_DIR / when.strftime("%Y-%m-%d")


def save_candidate(candidate: dict) -> Path:
    folder = candidate_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{candidate['id']}.json"
    path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_candidate(candidate_id: str) -> tuple[Path, dict] | None:
    for path in sorted(CANDIDATES_DIR.glob(f"*/{candidate_id}.json")):
        return path, json.loads(path.read_text(encoding="utf-8"))
    return None


def pending_candidates() -> list[tuple[Path, dict]]:
    out = []
    for path in sorted(CANDIDATES_DIR.glob("*/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("status") == "pending":
            out.append((path, data))
    return out


def update_candidate(path: Path, **changes) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
