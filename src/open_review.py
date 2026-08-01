"""فتح Issue للمراجعة يعرض المسودات التي لم تُراجَع بعد.

يُشغّل بعد رفع الصور إلى المستودع، حتى تظهر معاينات الصور في الـ Issue.

    python -m src.open_review
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from . import review, store

log = logging.getLogger("open_review")


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")

    fresh = [
        (path, d) for path, d in store.pending_drafts()
        if not d.get("review_issue")
    ]
    if not fresh:
        log.info("لا مسودات جديدة تحتاج مراجعة")
        return 0

    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        log.error("GITHUB_REPOSITORY غير موجود — هذا الأمر يعمل داخل GitHub Actions")
        return 1

    branch = os.environ.get("GITHUB_REF_NAME", "main")
    drafts = [d for _, d in fresh]

    review.ensure_labels()
    issue = review.create_issue(
        title=(f"📰 مسودات {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC "
               f"— {len(drafts)} منشور"),
        body=review.build_issue_body(drafts, repo, branch),
        labels=["pending-review"],
    )

    for path, _ in fresh:
        store.update_draft(path, review_issue=issue["number"])

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"\n➡️ [Issue #{issue['number']} للمراجعة]({issue['html_url']})\n")

    log.info("للمراجعة: %s", issue["html_url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
