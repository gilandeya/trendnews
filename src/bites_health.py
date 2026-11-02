"""أرقام صحة مكتبة المقاطع (المرحلة «هـ» من خطة المقاطع الموثَّقة).

كل خطوة في الجمع (فحص النهاية، تفريغ الصوت، اسم المتكلم) تُعرف الآن من سطرها في سجل التشغيلة فقط، ولا يُرى أين يضيع المقطع
عبر الأيام. هنا رقم واحد لكل يوم: كم مقطعًا جُمع، وكم يصلح للريل، ولماذا سقط الباقي. يُحسب من ملفات المقاطع في المستودع الخاص
بعد خطوة التفريغ ويُحفظ هناك (health.json بجانب ملفات الأيام)، وسطره يُكتب في ملخص التشغيلة. أرقام وحدها: لا كلام قنوات.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("trendnews")

HEALTH_FILE = "health.json"


def usable(b: dict, cfg: Any) -> tuple[bool, str]:
    """(صالح للريل؟، سبب السقوط) بشروط `reel_script.valid_clips` نفسها على المقطع المحفوظ، وبالترتيب الذي يسقط به هناك."""
    if b.get("start") is None or not str(b.get("text_original") or "").strip() or not b.get("video_id"):
        return False, "no_text"
    if b.get("incomplete"):
        return False, "incomplete"
    if (b.get("audio") or {}).get("status") == "no_match" and cfg.path("reel.script.exclude_audio_no_match", True):
        return False, "audio_no_match"
    return True, ""


def measure(bites: list[dict], cfg: Any) -> dict:
    """أرقام يوم واحد (دالة خالصة). النسب تُحسب عند العرض لا هنا كي تُجمع الأيام بالجمع."""
    out: dict = {"bites": len(bites), "videos": len({b.get("video_id") for b in bites}), "usable": 0,
                 "dropped": Counter(), "incomplete_why": Counter(), "audio": Counter(), "types": Counter(),
                 "named": 0, "hosts": 0, "rescued": 0, "end_checked": 0}
    for b in bites:
        ok, why = usable(b, cfg)
        out["usable"] += int(ok)
        if not ok:
            out["dropped"][why] += 1
        if b.get("incomplete"):
            whys = [k for k, v in ((b.get("end_check") or {}).get("why") or {}).items() if v]
            out["incomplete_why"][whys[0] if whys else "unknown"] += 1
        a = b.get("audio") or {}
        out["audio"][a.get("status") or "none"] += 1
        out["rescued"] += int(bool(a.get("rescued")))
        out["types"][str(b.get("type") or "")] += 1
        out["named"] += int(bool(str(b.get("speaker") or "").strip()))
        out["hosts"] += int(bool(b.get("is_host")))
        out["end_checked"] += int(bool(b.get("end_checked")))
    return {k: (dict(v) if isinstance(v, Counter) else v) for k, v in out.items()}


def snapshot(cfg: Any, now: datetime, days: int | None = None, root: Path | None = None) -> dict:
    """{التاريخ: أرقامه} لآخر days أيام لها ملف مقاطع، ويُدمج في health.json بجانبها (اليوم يُستبدل رقمه بالأحدث)."""
    from . import youtube_transcripts
    root = root or youtube_transcripts.bites_dir()
    days = int(days if days is not None else cfg.path("youtube.bites.health.days", 3))
    path = root / HEALTH_FILE
    try:
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        saved = {}
    for d in range(days):
        day = (now - timedelta(days=d)).strftime("%Y-%m-%d")
        f = root / f"{day}.json"
        if not f.exists():
            continue
        try:
            bites = json.loads(f.read_text(encoding="utf-8")).get("bites") or []
        except (OSError, ValueError):
            continue
        saved[day] = {**measure(bites, cfg), "measured_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    keep = int(cfg.path("youtube.bites.health.keep_days", 60))
    cut = (now - timedelta(days=keep)).strftime("%Y-%m-%d")
    saved = {k: v for k, v in sorted(saved.items()) if k >= cut}
    root.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
    return saved


def _pct(n: int, total: int) -> str:
    return f"{round(100 * n / total)}%" if total else "—"


def line(day: str, m: dict, cfg: Any) -> str:
    """سطر اليوم للمراجع: الصالح من الكل، وأسباب السقوط، وحالات التفريغ."""
    t = cfg.path("youtube.bites.health.texts") or {}
    names = t.get("reasons") or {}
    total = int(m.get("bites") or 0)
    dropped = "، ".join(f"{names.get(k, k)} {v}" for k, v in sorted((m.get("dropped") or {}).items(), key=lambda kv: -kv[1]))
    why = "، ".join(f"{names.get(k, k)} {v}" for k, v in sorted((m.get("incomplete_why") or {}).items(), key=lambda kv: -kv[1]))
    audio = "، ".join(f"{names.get(k, k)} {v}" for k, v in sorted((m.get("audio") or {}).items(), key=lambda kv: -kv[1]))
    return t.get("line", "{day}: {usable} من {bites} صالح ({pct})").format(
        day=day, usable=m.get("usable", 0), bites=total, pct=_pct(int(m.get("usable") or 0), total),
        videos=m.get("videos", 0), dropped=dropped or "—", why=why or "—", audio=audio or "—",
        named=_pct(int(m.get("named") or 0), total), rescued=m.get("rescued", 0))


def report(cfg: Any, now: datetime | None = None) -> list[str]:
    """يحسب ويحفظ ويعيد سطور الأيام المقيسة (الأحدث أولًا). لا يرفع: أرقام الصحة لا تُفشل الجمع."""
    now = now or datetime.now(timezone.utc)
    try:
        saved = snapshot(cfg, now)
    except Exception as exc:  # noqa: BLE001
        log.warning("تعذّر حساب صحة المقاطع: %s", str(exc)[:150])
        return []
    days = int(cfg.path("youtube.bites.health.days", 3))
    recent = [(now - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(days)]
    return [line(d, saved[d], cfg) for d in recent if d in saved]


def main() -> int:
    from .config import load_config
    logging.basicConfig(level=logging.INFO)
    cfg = load_config()
    lines = report(cfg)
    for ln in lines:
        print(ln, file=sys.stderr)
    # ملخص تشغيلة Actions (إن وُجد) يحمل السطور فتُرى بلا فتح السجل
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and lines:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(["### صحة مكتبة المقاطع", *[f"- {ln}" for ln in lines], ""]) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
