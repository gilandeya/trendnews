"""فتح Issue للمراجعة يعرض المسودات التي لم تُراجَع بعد، أو Issue الاختيار
قبل الصياغة إن كانت preselect مفعّلة (Issue #280) — واحد فقط لكل تشغيلة:
كل تشغيلة تنتج إما مسودات جاهزة (الدورة القديمة) أو مرشحين خامًا (preselect)،
لا كليهما معًا، فلا داعي لفتح أكثر من Issue واحد هنا.

يُشغّل بعد رفع الصور إلى المستودع، حتى تظهر معاينات الصور في الـ Issue.

    python -m src.open_review
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from . import preselect, review, store
from .config import load_config

log = logging.getLogger("open_review")


def _missing_review_fields(draft: dict) -> list[str]:
    """الحقول التي يعتمد عليها ``review.build_issue_body`` بلا شرط لكل
    مسودة. مسودة يوتيوب متسرّبة (أو أي مسودة عامة معطوبة أخرى) قد تفتقد
    ``image`` تحديدًا — عمدًا، لا خطأً (Issue #680) — قبل أن تُبنى بطاقتها
    لحظة الاعتماد؛ نفس مبدأ ``publish._missing_draft_fields`` (Issue #707)
    منقول إلى نقطة فتح الـ Issue بدل نقطة النشر فقط."""
    missing = []
    if not draft.get("image"):
        missing.append("image")
    if not draft.get("caption"):
        missing.append("caption")
    if not (draft.get("arabic") or {}).get("post_title"):
        missing.append("arabic.post_title")
    if "score" not in draft:
        missing.append("score")
    if not (draft.get("source") or {}).get("link"):
        missing.append("source.link")
    return missing


def _valid_review_drafts(rows: list[tuple]) -> list[tuple]:
    """يستبعد أي مسودة ناقصة الحقول ويسجّلها ``failed`` بدل ترك
    ``review.build_issue_body`` يرفع ``KeyError`` فيُسقط بناء الـ Issue
    كاملًا لأجل مسودة واحدة معطوبة (Issue #707)."""
    valid = []
    for path, d in rows:
        missing = _missing_review_fields(d)
        if not missing:
            valid.append((path, d))
            continue
        detail = f"حقول مفقودة: {', '.join(missing)}"
        log.warning("مسودة %s ناقصة الحقول (%s) — تُستبعد من الـ Issue العام",
                    d.get("id", "?"), detail)
        store.update_draft(path, status="failed", error=detail)
    return valid


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")

    # مسار يوتيوب (src/youtube_publish.py) يبني مسوداته بلا حقل image
    # عمدًا حتى الاعتماد (Issue #680)، وله Issue مراجعة خاص
    # (youtube_publish.open_review يفلتر origin == "youtube" صراحة).
    # نافذة سباق ضيقة بين حفظ تلك المسودة (status=pending) وربطها
    # بـreview_issue الخاص بها تعني أن هذا المسار العام قد يلتقطها أولًا
    # ويُدرجها في Issue المراجعة العام خطأً — فتفشل build_issue_body بـ
    # KeyError وتُسقط الدفعة كلها (Issue #707). استبعادها هنا صراحة يمنع
    # ذلك دون أي تعديل على مسار يوتيوب نفسه.
    fresh_drafts = _valid_review_drafts([
        (path, d) for path, d in store.pending_drafts()
        if not d.get("review_issue") and d.get("origin") != "youtube"
    ])
    fresh_candidates = [
        (path, c) for path, c in store.pending_candidates()
        if not c.get("selection_issue")
    ]
    if not fresh_drafts and not fresh_candidates:
        log.info("لا مسودات ولا مرشحين جدد يحتاجون فتح Issue")
        return 0

    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        log.error("GITHUB_REPOSITORY غير موجود — هذا الأمر يعمل داخل GitHub Actions")
        return 1

    branch = os.environ.get("GITHUB_REF_NAME", "main")
    review.ensure_labels()

    if fresh_drafts:
        drafts = [d for _, d in fresh_drafts]
        issue = review.create_issue(
            title=(f"📰 مسودات {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC "
                   f"— {len(drafts)} منشور"),
            body=review.build_issue_body(drafts, repo, branch),
            labels=["pending-review"],
        )
        for path, _ in fresh_drafts:
            store.update_draft(path, review_issue=issue["number"])
    else:
        cands = [c for _, c in fresh_candidates]
        cfg = load_config()
        translations = preselect.translate_titles(cands, cfg)
        issue = review.create_issue(
            title=(f"🗳️ اختيار {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC "
                   f"— {len(cands)} مرشح"),
            body=preselect.build_selection_issue_body(cands, translations),
            labels=["pending-selection"],
        )
        for path, _ in fresh_candidates:
            store.update_candidate(path, selection_issue=issue["number"])

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"\n➡️ [Issue #{issue['number']} للمراجعة]({issue['html_url']})\n")

    log.info("للمراجعة: %s", issue["html_url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
