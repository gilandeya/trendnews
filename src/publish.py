"""نشر المسودات المعتمدة على فيسبوك.

الاستخدام:
    python -m src.publish --issue 12          # ينشر ما عُلّم عليه في الـ Issue
    python -m src.publish --ids a1b2,c3d4     # نشر معرفات محددة يدويًا
    python -m src.publish --all-pending       # نشر كل المسودات المعلّقة
    python -m src.publish --verify            # فحص صلاحيات فيسبوك فقط
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone

import requests

from . import facebook, review, store
from .config import ROOT, env, load_config

log = logging.getLogger("publish")


def fetch_issue(issue_number: int) -> dict:
    repo = env("GITHUB_REPOSITORY", required=True)
    token = env("GITHUB_TOKEN", required=True)
    resp = requests.get(
        f"https://api.github.com/repos/{repo}/issues/{issue_number}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=45,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="نشر المسودات المعتمدة")
    parser.add_argument("--issue", type=int, help="رقم الـ Issue الذي يحمل الاعتماد")
    parser.add_argument("--ids", help="معرفات مسودات مفصولة بفواصل")
    parser.add_argument("--all-pending", action="store_true", help="نشر كل المعلّق")
    parser.add_argument("--verify", action="store_true", help="فحص التوكن فقط")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = load_config(args.config)
    api_version = cfg.path("facebook.api_version", "v21.0")

    if args.verify:
        info = facebook.verify_token(api_version)
        log.info("✅ التوكن صالح — الصفحة: %s (%s متابع)",
                 info.get("name"), info.get("fan_count", "?"))
        return 0

    # ── تحديد ما يُنشر ─────────────────────────────────────────
    issue_number: int | None = args.issue
    if args.ids:
        ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    elif args.all_pending:
        ids = [d["id"] for _, d in store.pending_drafts()]
    elif issue_number:
        issue = fetch_issue(issue_number)
        ids = review.parse_approved(issue.get("body") or "")
        total = len(review.all_draft_ids(issue.get("body") or ""))
        log.info("الـ Issue #%s: %d معتمد من %d", issue_number, len(ids), total)
    else:
        parser.error("حدّد --issue أو --ids أو --all-pending")
        return 2

    if not ids:
        log.warning("لا توجد مسودات معتمدة — لم يُعلَّم على أي منشور")
        if issue_number:
            review.comment(issue_number,
                           "⚠️ لم يُعلَّم على أي منشور. أضف ✔️ ثم أعد وسم `approved`.")
            review.remove_label(issue_number, "approved")
        return 0

    # ── النشر ─────────────────────────────────────────────────
    results: list[str] = []
    published = 0

    for draft_id in ids:
        found = store.load_draft(draft_id)
        if not found:
            log.error("المسودة %s غير موجودة", draft_id)
            results.append(f"- ❌ `{draft_id}` — الملف غير موجود")
            continue

        path, draft = found
        if draft.get("status") == "published":
            log.info("%s منشور مسبقًا — تخطي", draft_id)
            results.append(f"- ↩️ `{draft_id}` — منشور مسبقًا")
            continue

        image_path = ROOT / draft["image"]
        if not image_path.exists():
            log.error("صورة المسودة مفقودة: %s", image_path)
            results.append(f"- ❌ `{draft_id}` — الصورة مفقودة")
            continue

        try:
            if cfg.path("facebook.publish_as_photo", True):
                res = facebook.publish_photo(image_path, draft["caption"], api_version)
            else:
                res = facebook.publish_link(draft["source"]["link"],
                                            draft["caption"], api_version)
        except facebook.FacebookError as exc:
            log.error("فشل نشر %s: %s", draft_id, exc)
            store.update_draft(path, status="failed", error=str(exc))
            results.append(f"- ❌ {draft['arabic']['post_title'][:50]} — {exc}")
            continue

        store.update_draft(
            path,
            status="published",
            published_at=datetime.now(timezone.utc).isoformat(),
            facebook=res,
        )
        published += 1
        results.append(
            f"- ✅ [{draft['arabic']['post_title'][:60]}]({res.get('url') or '#'})"
        )

    # ── التقرير ───────────────────────────────────────────────
    report = f"### 🚀 نُشر {published} من {len(ids)}\n" + "\n".join(results)
    log.info("النتيجة: %d/%d", published, len(ids))

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(report + "\n")

    if issue_number:
        review.comment(issue_number, report)
        if published:
            review.close_issue(issue_number)

    return 0 if published or not ids else 1


if __name__ == "__main__":
    raise SystemExit(main())
