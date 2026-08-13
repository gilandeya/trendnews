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


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")

    fresh_drafts = [
        (path, d) for path, d in store.pending_drafts()
        if not d.get("review_issue")
    ]
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
