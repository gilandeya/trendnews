"""ذاكرة الصحافة المتقاطعة — من غطّى الحدث وبأي عنوان وبأي لغة.

بيانات فقط: لا نموذج ولا قضايا، ولا أثر على المرشحين أو ترتيبهم. تُستدعى من
rank.rank (عبر collect) بعد التجميع والدمج الدلالي بنتائجهما نفسها، لأن
cluster_members في المرشحين لا تحمل عنوان الناشر ولا منطقته ولا وقت نشره.
الملف: state/press/events.json، والإعداد في config.yaml: press."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from .config import STATE_DIR, load_config
from .rank import similarity, tokens

log = logging.getLogger("press_events")

EVENTS_FILE = STATE_DIR / "press" / "events.json"

# كشف اللغة بلا مكتبة: الخط يحسم ما له خط مميّز، وكلمات وظيفية شائعة تفرّق
# اللاتينيات. عتبة الغلبة تمنع عنوانًا عربيًا فيه اسم لاتيني من أن يُحسب لاتينيًا.
_SCRIPTS = [
    ("ar", re.compile(r"[؀-ۿ]")),
    ("zh", re.compile(r"[一-鿿]")),
    ("ko", re.compile(r"[가-힯]")),
    ("he", re.compile(r"[֐-׿]")),
    ("ru", re.compile(r"[Ѐ-ӿ]")),
    ("el", re.compile(r"[Ͱ-Ͽ]")),
]
_PERSIAN_LETTERS = re.compile(r"[پچژگ]")
_LATIN_STOP = {
    "en": {"the", "of", "and", "to", "in", "is", "for", "on", "with", "after", "says"},
    "fr": {"le", "la", "les", "des", "du", "une", "est", "pour", "dans", "sur", "et", "au"},
    "de": {"der", "die", "das", "und", "ist", "nicht", "mit", "für", "von", "auf", "zu", "den"},
    "es": {"el", "los", "las", "una", "del", "por", "con", "para", "que", "y", "en"},
    "pt": {"os", "uma", "não", "para", "com", "dos", "das", "em", "do", "da", "que"},
    "tr": {"bir", "ve", "bu", "için", "ile", "da", "de", "olarak", "daha", "çok"},
}
_TURKISH_LETTERS = re.compile(r"[ğışİĞŞ]")


def detect_language(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "und"
    # الكتابات غير اللاتينية: الأكثر حروفًا يغلب
    # أي هيراغانا/كاتاكانا تحسم اليابانية؛ فالعنوان الياباني غالبه كانجي
    if re.search(r"[぀-ヿ]", text):
        return "ja"
    best, best_n = None, 0
    for lang, rx in _SCRIPTS:
        n = len(rx.findall(text))
        if n > best_n:
            best, best_n = lang, n
    if best and best_n >= len(letters) * 0.4:
        if best == "ar" and _PERSIAN_LETTERS.search(text):
            return "fa"
        return best
    words = re.findall(r"[a-zà-ÿğışİ']+", text.lower())
    if _TURKISH_LETTERS.search(text):
        return "tr"
    scores = {lang: sum(w in stop for w in words) for lang, stop in _LATIN_STOP.items()}
    lang, n = max(scores.items(), key=lambda kv: kv[1])
    # بلا كلمات وظيفية معروفة ← الإنجليزية (لغة الخلاصات الأساسية)
    return lang if n > 0 else "en"


def _cfg(cfg) -> dict:
    p = (cfg.get("press", {}) or {})
    w = p.get("weights", {}) or {}
    return {
        "enabled": bool(p.get("enabled", True)),
        "min_outlets": int(p.get("min_outlets", 3)),
        "keep_days": int(p.get("keep_days", 7)),
        "max_events": int(p.get("max_events", 500)),
        "max_members": int(p.get("max_members", 30)),
        "w_outlets": float(w.get("outlets", 1)),
        "w_regions": float(w.get("regions", 2)),
        "w_languages": float(w.get("languages", 2)),
    }


def _member(art) -> dict:
    return {
        "outlet": art.source_name,
        "region": art.region,
        "bucket": art.bucket,
        "title": art.title,
        "language": detect_language(art.title),
        "link": art.link,
        "published": art.published.isoformat(),
    }


def score_event(members: list[dict], p: dict) -> float:
    return (p["w_outlets"] * len({m["outlet"] for m in members})
            + p["w_regions"] * len({m["region"] for m in members})
            + p["w_languages"] * len({m["language"] for m in members}))


def load_events() -> list[dict]:
    try:
        return json.loads(EVENTS_FILE.read_text(encoding="utf-8")).get("events", [])
    except (OSError, ValueError):
        return []


def save_events(events: list[dict]) -> None:
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    EVENTS_FILE.write_text(
        json.dumps({"events": events}, ensure_ascii=False, indent=1), encoding="utf-8")


def _new_id(members: list[dict], now: datetime) -> str:
    seed = "|".join(sorted(m["link"] for m in members)) + now.isoformat()
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def _match(members: list[dict], events: list[dict], threshold: float) -> dict | None:
    links = {m["link"] for m in members}
    sigs = [tokens(m["title"]) for m in members]
    for ev in events:
        if links & {m["link"] for m in ev["members"]}:
            return ev
    # التشابه الاسمي عبر التشغيلات (عتبة dedupe_title_similarity لا عتبة
    # العنقود الداخلية) — لا يُقارَن إلا بعناوين محفوظة بالتوقيع اللاتيني نفسه
    for ev in events:
        for m in ev["members"]:
            s = tokens(m["title"])
            if s and any(similarity(s, sig) >= threshold for sig in sigs if sig):
                return ev
    return None


def record(groups: list[list], cfg, now: datetime | None = None) -> int:
    """groups: قوائم Article الخام لكل عنقود نهائي. يعيد عدد الأحداث المحفوظة."""
    p = _cfg(cfg)
    if not p["enabled"]:
        return 0
    now = now or datetime.now(timezone.utc)
    threshold = float((cfg.get("selection", {}) or {}).get("dedupe_title_similarity", 0.5))
    events = load_events()

    for group in groups:
        if len({a.source_name for a in group}) < p["min_outlets"]:
            continue
        members = [_member(a) for a in group]
        ev = _match(members, events, threshold)
        if ev is None:
            ev = {"id": _new_id(members, now), "first_seen": now.isoformat(),
                  "members": []}
            events.append(ev)
        have = {m["link"] for m in ev["members"]}
        for m in members:
            if m["link"] not in have:
                have.add(m["link"])
                ev["members"].append(m)
        ev["members"] = ev["members"][:p["max_members"]]
        ev["last_seen"] = now.isoformat()

    cutoff = now - timedelta(days=p["keep_days"])
    events = [e for e in events if datetime.fromisoformat(e["last_seen"]) >= cutoff]
    for e in events:
        e["outlets"] = len({m["outlet"] for m in e["members"]})
        e["regions"] = len({m["region"] for m in e["members"]})
        e["languages"] = len({m["language"] for m in e["members"]})
        e["score"] = round(score_event(e["members"], p), 2)
    events.sort(key=lambda e: e["score"], reverse=True)
    save_events(events[:p["max_events"]])
    return min(len(events), p["max_events"])


def top_events(n: int, hours: int = 48, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    recent = [e for e in load_events()
              if datetime.fromisoformat(e["last_seen"]) >= cutoff]
    return sorted(recent, key=lambda e: e["score"], reverse=True)[:n]


def main() -> int:
    ap = argparse.ArgumentParser(description="أعلى أحداث ذاكرة الصحافة")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    load_config(args.config)
    for e in top_events(args.top):
        print(f"[{e['score']}] {e['id']} — ناشرون {e['outlets']} · "
              f"مناطق {e['regions']} · لغات {e['languages']}")
        seen: set[str] = set()
        for m in e["members"]:
            if m["region"] in seen:
                continue
            seen.add(m["region"])
            print(f"    {m['region']}: {m['title']}  ({m['outlet']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
