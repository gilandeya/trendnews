"""سجل تراكمي لقرارات المراجعة — المرحلة الأولى فقط (Issue #583): جمع بلا
أي تحليل أو تنبؤ أو تأثير على الفرز/الترتيب.

المراجع اليوم لا يستعمل شارة الرفض إطلاقًا (`/reject`)، فتجاهله الفعلي —
الأصوب لفهم أذواقه — لا يترك أثرًا مسجَّلاً. هذه الوحدة تستنتج إشارتين
إضافيتين من سلوك موجود أصلًا بلا أي تسجيل جديد وقت الجمع:

  • ``dismissed_closed`` — إشارة **صريحة**: أُغلق Issue المراجعة ومسودة ما
    فيه بقيت بلا اعتماد (``review.build_issue_body`` يقول صراحة "إغلاق
    الـ Issue = تجاهل الكل"، فقط لم يكن يُقرأ كبيانات حتى الآن).
  • ``ignored_timeout`` — إشارة **ضمنية**: بقي الـ Issue مفتوحًا أكثر من
    ``decisions.ignore_timeout_hours`` ساعة بلا أي بتّ — تخمين، لا فعل
    مقصود، ولذا ⚠️ لا يُعامَل بوزن إشارة ``dismissed_closed`` الصريحة في
    أي تقرير لاحق.

مع ``published`` (يُسجَّل لحظة النشر الفعلي) و``rejected_explicit`` (لحظة
تسجيل رفض صريح عبر `/reject`)، أربعتها تغطي كل مصير ممكن لمسودة بلا حاجة
لبناء جديد — كل حقل تلتقطه ``_features`` موجود أصلًا في ملف المسودة.

⚠️ قيد على أي عمل لاحق في هذا الاتجاه (مسجَّل أيضًا في CLAUDE.md): أي
انتقال مستقبلي من "عرض" (تقرير) إلى "تأثير" (فرز/ترتيب) يجب أن يكون خفض
أولوية لا حجبًا كليًا — نفس فلسفة ``verify.demoted_readers``. عيّنة صغيرة
تثبّت انحيازًا لا تكشف نمطًا؛ نظام يرشّح ما يتوقع أن المراجع سينشره قد
يضيّق تغطيته بدل تحسينها.

    python -m src.decisions --count     # عدد القرارات المتراكمة حتى الآن
    python -m src.decisions --scan      # تشغيل الفحص يدويًا بلا انتظار collect
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone

import requests

from . import store
from .config import STATE_DIR, env, load_config

log = logging.getLogger("decisions")

DECISIONS_FILE = STATE_DIR / "decisions.json"
API = "https://api.github.com"


# ──────────────────────────── التخزين ────────────────────────────


def load() -> list[dict]:
    if not DECISIONS_FILE.exists():
        return []
    try:
        return json.loads(DECISIONS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("ملف القرارات تالف — سيُعاد إنشاؤه")
        return []


def save(entries: list[dict]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    DECISIONS_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")


def _features(draft: dict) -> dict:
    """السمات المتاحة أصلًا في ملف المسودة — بلا أي حقل جديد يُكتب وقت
    الجمع (Issue #583). ``source_count`` من ``publishers`` (كل من التقط
    الخبر) لا ``analysed_sources`` (من حُلِّل نصّه فقط) — الأول موجود دومًا،
    والثاني قد يكون فارغًا حتى لمسودة كاملة."""
    ar = draft.get("arabic") or {}
    src = draft.get("source") or {}
    created_hour = None
    try:
        created_hour = datetime.fromisoformat(draft.get("created_at", "")).hour
    except (ValueError, TypeError):
        pass
    body = ar.get("post_body") or draft.get("caption") or ""
    return {
        # المسار العادي (collect.py) لا يكتب "origin" إطلاقًا — القيمة
        # الافتراضية هنا تميّزه عن article/verify بلا تعديل collect.py.
        "origin": draft.get("origin", "collect"),
        "category": ar.get("category", ""),
        "angle": ar.get("angle", ""),
        "urgent": bool(ar.get("urgent")),
        "bucket": draft.get("bucket", ""),
        "region": src.get("region", ""),
        "score": round(float(draft.get("score", 0) or 0), 2),
        "trend_score": round(float(draft.get("trend_score", 0) or 0), 2),
        "velocity": round(float(draft.get("velocity", 0) or 0), 2),
        "source_count": len(src.get("publishers") or []),
        "body_len": len(body),
        "has_photo": bool(draft.get("has_photo", True)),
        "state_media": bool(draft.get("state_media", False)),
        "created_hour": created_hour,
    }


def _append(entries: list[dict], draft: dict, decision: str,
            reject_tag: str | None = None) -> None:
    entries.append({
        "id": draft.get("id", ""),
        "created_at": draft.get("created_at", ""),
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "reject_tag": reject_tag,
        **_features(draft),
    })
    log.info("قرار مسجَّل: %s ← %s", draft.get("id", ""), decision)


def record_published(draft: dict) -> None:
    entries = load()
    if any(e.get("id") == draft.get("id") for e in entries):
        return
    _append(entries, draft, "published")
    save(entries)


def record_rejected(draft: dict, tag: str) -> None:
    """الرفض الصريح عبر `/reject` — نادر عمليًا (المراجع لا يستعمله اليوم)
    لكنه يُسجَّل للاكتمال: يُميَّز عن ``dismissed_closed``/``ignored_timeout``
    بأنه فعل مقصود موثَّق بسبب، لا استنتاج."""
    entries = load()
    if any(e.get("id") == draft.get("id") for e in entries):
        return
    _append(entries, draft, "rejected_explicit", reject_tag=tag)
    save(entries)


# ──────────────────────────── الفحص الدوري (الإشارتان الضمنيتان) ────────


def _fetch_issue(issue_number: int) -> dict:
    repo = env("GITHUB_REPOSITORY", required=True)
    token = env("GITHUB_TOKEN", required=True)
    resp = requests.get(
        f"{API}/repos/{repo}/issues/{issue_number}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"},
        timeout=45,
    )
    resp.raise_for_status()
    return resp.json()


def scan(cfg) -> int:
    """يفحص المسودات المعلَّقة المرتبطة بـ Issue مراجعة، ويسجّل قرارًا
    ضمنيًا لكل ما بُتَّ فيه فعلًا. يُشغَّل كل تشغيلة جمع (حتى بلا مسودة
    جديدة) — الإغلاق أو انقضاء المهلة قد يقعان بين تشغيلة وأخرى بلا أي
    حدث آخر يستدعي الفحص. يعيد عدد القرارات الجديدة."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo or not os.environ.get("GITHUB_TOKEN"):
        return 0  # بيئة محلية بلا Actions — لا شيء يُفحص

    pending = [(p, d) for p, d in store.pending_drafts() if d.get("review_issue")]
    if not pending:
        return 0

    entries = load()
    known = {e["id"] for e in entries}
    pending = [(p, d) for p, d in pending if d.get("id") not in known]
    if not pending:
        return 0

    timeout_hours = float(cfg.path("decisions.ignore_timeout_hours", 48))
    now = datetime.now(timezone.utc)

    by_issue: dict[int, list[dict]] = {}
    for _, draft in pending:
        by_issue.setdefault(draft["review_issue"], []).append(draft)

    recorded = 0
    for issue_number, drafts in by_issue.items():
        try:
            issue = _fetch_issue(issue_number)
        except requests.RequestException as exc:
            log.warning("تعذّر جلب Issue #%s للفحص: %s", issue_number, exc)
            continue

        closed = issue.get("state") == "closed"
        for draft in drafts:
            if closed:
                _append(entries, draft, "dismissed_closed")
                recorded += 1
                continue
            try:
                created = datetime.fromisoformat(draft["created_at"])
            except (KeyError, ValueError, TypeError):
                continue
            if (now - created).total_seconds() >= timeout_hours * 3600:
                _append(entries, draft, "ignored_timeout")
                recorded += 1

    if recorded:
        save(entries)
        log.info("قرارات ضمنية مسجَّلة هذه الدورة: %d", recorded)
    return recorded


# ──────────────────────────── الأمر ────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="سجل القرارات التراكمي — المرحلة الأولى: جمع بلا تحليل")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--count", action="store_true",
                       help="عدد القرارات المتراكمة حتى الآن")
    group.add_argument("--scan", action="store_true",
                       help="فحص المسودات المعلَّقة يدويًا الآن")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")

    if args.scan:
        n = scan(load_config(args.config))
        print(f"سُجّل {n} قرارًا ضمنيًا جديدًا.")
        return 0

    entries = load()
    print(f"إجمالي القرارات المسجَّلة: {len(entries)}")
    for decision, count in Counter(e["decision"] for e in entries).most_common():
        print(f"  {decision}: {count}")
    remaining = max(0, 30 - len(entries))
    if remaining:
        print(f"(يلزم {remaining} إضافيًا قبل مراجعة N=48 على أدلة)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
