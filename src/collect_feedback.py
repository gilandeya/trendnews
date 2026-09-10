"""يقرأ أوامر /reject من تعليقات المراجعة ويسجّلها.

    python -m src.collect_feedback --issue 42
"""
from __future__ import annotations

import argparse
import logging
import os

import requests

from . import decisions, feedback, review, store
from .config import env

log = logging.getLogger("feedback")


def fetch_comments(issue_number: int) -> list[str]:
    repo = env("GITHUB_REPOSITORY", required=True)
    token = env("GITHUB_TOKEN", required=True)
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json"}
    bodies: list[str] = []

    issue = requests.get(f"https://api.github.com/repos/{repo}/issues/{issue_number}",
                         headers=headers, timeout=45)
    issue.raise_for_status()
    bodies.append(issue.json().get("body") or "")

    comments = requests.get(
        f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
        headers=headers, params={"per_page": "100"}, timeout=45)
    comments.raise_for_status()
    bodies += [c.get("body") or "" for c in comments.json()]
    return bodies


def main() -> int:
    parser = argparse.ArgumentParser(description="تسجيل أسباب الرفض")
    parser.add_argument("--issue", type=int, required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")

    bodies = fetch_comments(args.issue)

    # الأوامر النصية /reject — الطريقة الوحيدة المتبقية لتسجيل سبب رفض
    # حقيقي (Issue #841): مربعات أسباب الرفض حُذفت من واجهة المراجعة — عدم
    # الاعتماد وحده يُسجَّل رفضًا تلقائيًا بوسم «لم يُعتمد» في publish.py،
    # وهذا المسار يبقى فقط لمن يكتب سببًا حقيقيًا يدويًا في تعليق.
    commands: list[tuple[str, str, str]] = []
    seen_ids: set[str] = set()
    for body in bodies:
        for did, tag, note in feedback.parse_rejections(body):
            if did not in seen_ids:
                commands.append((did, tag, note))
                seen_ids.add(did)

    if not commands:
        log.info("لا رفض مسجّل في هذا الـ Issue")
        return 0
    log.info("أوامر نصية: %d", len(commands))

    entries = feedback.load()
    known = {e["id"] for e in entries}
    lines: list[str] = []
    saved = 0

    for draft_id, tag, note in commands:
        if draft_id in known:
            continue
        found = store.load_draft(draft_id)
        if not found:
            lines.append(f"- ❓ `{draft_id}` — لا توجد مسودة بهذا المعرّف")
            continue
        path, draft = found
        feedback.record(entries, draft, tag, note)
        known.add(draft_id)
        store.update_draft(path, status="rejected", reject_tag=tag,
                           reject_note=note)
        decisions.record_rejected(draft, tag)
        reason = feedback.REASONS.get(tag, tag)
        lines.append(f"- 🚫 {draft['arabic']['post_title'][:55]} — {reason}"
                     + (f" ({note})" if note else ""))
        saved += 1

    feedback.save(entries)
    log.info("سُجّل %d رفض · الإجمالي المحفوظ: %d", saved, len(entries))

    if not saved:
        return 0

    missing_note = [c for c in commands if c[1] == "آخر" and not c[2]]
    text = (f"### 🚫 سُجّل {saved} رفض\n" + "\n".join(lines)
            + ("\n\n⚠️ اخترتَ «غير ذلك» بلا سبب مكتوب. اكتب السبب في تعليق "
               "ثم أعد وسم `rejected` ليُسجَّل." if missing_note else "")
            + "\n\n<sub>ستُمرَّر هذه الأسباب إلى الفرز الأولي في الدفعات "
              "القادمة لاستبعاد ما يشبهها — بلا تعميم على مصدر أو بلد.</sub>")
    review.comment(args.issue, text)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
