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
             posted_title: str | None = None) -> None:
    entries.append({
        "tokens": sorted(tokens(title)),
        "link": link,
        "title": title[:160],
        "posted_title": (posted_title or "")[:160],
        "seen_at": datetime.now(timezone.utc).isoformat(),
    })


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
