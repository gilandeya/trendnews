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

    # ① مربعات الرفض في نص الـ Issue — الطريقة الأساسية
    boxed = review.parse_rejects(bodies[0] if bodies else "")

    # ② الأوامر النصية — للسبب الحر أو لمن يفضّلها
    typed = []
    for body in bodies:
        typed += feedback.parse_rejections(body)

    # ③ التعليقات الحرة تُربط بمن اختار «آخر»
    free_notes = [b.strip() for b in bodies[1:]
                  if b.strip() and "/reject" not in b
                  and not b.strip().startswith("###")]
    pending_other = [did for did, tag in boxed if tag == "آخر"]
    note_for_other = free_notes[-1][:200] if free_notes else ""

    commands: list[tuple[str, str, str]] = []
    seen_ids: set[str] = set()
    for did, tag in boxed:
        note = note_for_other if (tag == "آخر" and did in pending_other) else ""
        commands.append((did, tag, note))
        seen_ids.add(did)
    for did, tag, note in typed:
        if did not in seen_ids:
            commands.append((did, tag, note))
            seen_ids.add(did)

    if not commands:
        log.info("لا رفض مسجّل في هذا الـ Issue")
        return 0
    log.info("مربعات: %d · أوامر نصية: %d", len(boxed), len(typed))

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
        if not draft.get("image"):
            # مسودة تحليل قبل اعتمادها (Issue #680) لا بطاقة لها بنيويًا
            # بعد -- هذا المسار يفترض بطاقة مبنية (العنوان المعروض في
            # سطر التقرير أدناه من caption/arabic المبنيَّين فعليًا وقت
            # الاعتماد لا قبله)، فرفض واضح بدل تسجيل رفض على بيانات لم
            # تكتمل بعد (Issue #749).
            lines.append(f"- ⚠️ `{draft_id}` — لا بطاقة بعد لهذه المسودة "
                         "— البطاقة تُبنى عند الاعتماد")
            continue
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
