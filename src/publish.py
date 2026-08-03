"""جدولة المسودات المعتمدة ونشرها في أوقات الذروة.

    python -m src.publish --issue 12       # يجدول ما عُلّم عليه في الـ Issue
    python -m src.publish --issue 12 --now # ينشر فورًا بلا جدولة
    python -m src.publish --due            # ينشر ما حان وقته من الطابور
    python -m src.publish --ids a1b2,c3d4  # نشر فوري لمعرفات محددة
    python -m src.publish --verify         # فحص صلاحيات فيسبوك
    python -m src.publish --queue          # عرض الطابور
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone

import requests

from . import facebook, review, store
from .config import ROOT, env, load_config
from .schedule import assign_slots, burst_slots, describe, is_due

log = logging.getLogger("publish")


# ──────────────────────────── مساعدات ────────────────────────────


def fetch_issue(issue_number: int) -> dict:
    repo = env("GITHUB_REPOSITORY", required=True)
    token = env("GITHUB_TOKEN", required=True)
    resp = requests.get(
        f"https://api.github.com/repos/{repo}/issues/{issue_number}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"},
        timeout=45,
    )
    resp.raise_for_status()
    return resp.json()


def queued_drafts() -> list[tuple]:
    out = []
    for path in sorted(store.DRAFTS_DIR.glob("*/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("status") == "queued":
            out.append((path, data))
    out.sort(key=lambda t: t[1].get("publish_at", ""))
    return out


def booked_times() -> list[datetime]:
    times = []
    for _, d in queued_drafts():
        try:
            times.append(datetime.fromisoformat(d["publish_at"]))
        except (KeyError, ValueError):
            pass
    return times


def first_comment_for(draft: dict, cfg) -> str | None:
    """نص التعليق الأول: رابط المصدر خارج متن المنشور."""
    if not cfg.path("facebook.link_in_first_comment", True):
        return None
    link = (draft.get("source") or {}).get("link")
    if not link:
        return None
    publishers = "، ".join((draft.get("source") or {}).get("publishers", [])[:3])
    prefix = cfg.path("facebook.comment_prefix", "المصدر")
    return f"{prefix}: {publishers}\n{link}" if publishers else f"{prefix}: {link}"


def publish_one(path, draft: dict, cfg) -> tuple[bool, str]:
    """ينشر مسودة واحدة. يعيد (نجح، سطر التقرير)."""
    api_version = cfg.path("facebook.api_version", "v21.0")
    image_path = ROOT / draft["image"]
    title = draft["arabic"]["post_title"][:60]

    if not image_path.exists():
        store.update_draft(path, status="failed", error="الصورة مفقودة")
        return False, f"- ❌ {title} — الصورة مفقودة"

    try:
        res = facebook.publish_photo(
            image_path, draft["caption"], api_version,
            first_comment=first_comment_for(draft, cfg),
        )
    except facebook.FacebookError as exc:
        store.update_draft(path, status="failed", error=str(exc))
        return False, f"- ❌ {title} — {exc}"

    store.update_draft(
        path, status="published",
        published_at=datetime.now(timezone.utc).isoformat(),
        facebook=res,
    )
    note = " ⚠️ بلا تعليق" if res.get("comment_error") else ""
    return True, f"- ✅ [{title}]({res.get('url') or '#'}){note}"


def report(lines: list[str], published: int, total: int,
           issue_number: int | None = None, close: bool = False) -> None:
    text = f"### 🚀 نُشر {published} من {total}\n" + "\n".join(lines)
    log.info("النتيجة: %d/%d", published, total)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")

    if issue_number:
        review.comment(issue_number, text)
        if close and published:
            review.close_issue(issue_number)


# ──────────────────────────── الأوامر ────────────────────────────


def collect_pending(ids: list[str], lines: list[str]) -> list[tuple]:
    """يجمع المسودات القابلة للنشر، مرتبة بالأعلى ترندًا أولًا."""
    pending: list[tuple] = []
    for draft_id in ids:
        found = store.load_draft(draft_id)
        if not found:
            lines.append(f"- ❌ `{draft_id}` — المسودة غير موجودة")
            continue
        path, draft = found
        status = draft.get("status")
        if status in ("published", "queued"):
            lines.append(f"- ↩️ {draft['arabic']['post_title'][:50]} — {status}")
            continue
        pending.append((path, draft))

    # الأعلى مؤشرًا أولًا — هو الذي يخرج فورًا في نمط الدفعة
    pending.sort(key=lambda t: -float(t[1].get("score", 0)))
    return pending


def cmd_burst(ids: list[str], cfg, issue_number: int | None) -> int:
    """
    الأعلى ترندًا يُنشر فورًا، والباقي بفاصل ثابت — كله في تشغيل واحد.

    نسجّل مواعيد الجميع في الطابور أولًا، ثم ننشر بالتتابع. فإن انقطع
    التشغيل لأي سبب، يلتقط سيّر «نشر الطابور» ما تبقّى بدل ضياعه.
    """
    fcfg = cfg.get("facebook", {}) or {}
    gap = float(fcfg.get("burst_gap_minutes", 5))
    tzname = fcfg.get("timezone", "UTC")

    lines: list[str] = []
    pending = collect_pending(ids, lines)
    if not pending:
        text = "### ℹ️ لا جديد للنشر\n" + "\n".join(lines)
        if issue_number:
            review.comment(issue_number, text)
        return 0

    slots = burst_slots(len(pending), gap)
    for (path, _), when in zip(pending, slots):
        store.update_draft(path, status="queued", publish_at=when.isoformat())

    log.info("دفعة من %d منشور — الأول فورًا ثم كل %d دقائق", len(pending), gap)
    published = 0

    for index, ((path, draft), when) in enumerate(zip(pending, slots)):
        if index:
            wait = (when - datetime.now(timezone.utc)).total_seconds()
            if wait > 0:
                log.info("انتظار %.0f ثانية قبل المنشور التالي…", wait)
                time.sleep(wait)

        fresh = store.load_draft(draft["id"])
        if not fresh or fresh[1].get("status") == "published":
            continue
        ok, line = publish_one(fresh[0], fresh[1], cfg)
        published += ok
        lines.append(("⚡ " if index == 0 else f"⏱️ +{index * gap:g}د ") + line.lstrip("- "))
        log.info("(%d/%d) %s", index + 1, len(pending), line[:70])

    header = (f"### 🚀 نُشر {published} من {len(pending)}\n"
              f"<sub>الأعلى مؤشرًا فورًا، ثم منشور كل {gap:g} دقائق "
              f"(بتوقيت {tzname}).</sub>\n")
    text = header + "\n".join(f"- {l}" for l in lines)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    if issue_number:
        review.comment(issue_number, text)
        if published:
            review.close_issue(issue_number)
    return 0


def cmd_schedule(ids: list[str], cfg, issue_number: int | None) -> int:
    """يضع المسودات المعتمدة في الطابور بمواعيد ذروة."""
    fcfg = cfg.get("facebook", {}) or {}
    tzname = fcfg.get("timezone", "UTC")

    lines: list[str] = []
    pending = collect_pending(ids, lines)

    if not pending:
        text = "### ℹ️ لا جديد للجدولة\n" + "\n".join(lines)
        if issue_number:
            review.comment(issue_number, text)
        log.info("لا مسودات جديدة")
        return 0

    slots = assign_slots(
        len(pending),
        fcfg.get("peak_hours") or [18],
        tzname,
        int(fcfg.get("min_gap_minutes", 120)),
        taken=booked_times(),
    )

    for (path, draft), when in zip(pending, slots):
        store.update_draft(path, status="queued", publish_at=when.isoformat())
        lines.append(
            f"- 🕐 {draft['arabic']['post_title'][:55]} → **{describe(when, tzname)}**"
        )

    text = (f"### 🗓️ جُدول {len(pending)} منشور\n"
            + "\n".join(lines)
            + f"\n\n<sub>المواعيد بتوقيت {tzname}. ينشر البوت كلًا منها في وقته "
              "تلقائيًا. لإلغاء منشور، غيّر `status` في ملفه إلى `cancelled`.</sub>")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    if issue_number:
        review.comment(issue_number, text)
        review.close_issue(issue_number)
    log.info("جُدول %d منشور", len(pending))
    return 0


def cmd_due(cfg) -> int:
    """ينشر كل ما حان وقته في الطابور."""
    rows = queued_drafts()
    due = [(p, d) for p, d in rows if is_due(d.get("publish_at", ""))]
    if not due:
        log.info("لا شيء مستحق الآن (%d في الطابور)", len(rows))
        if rows:
            tzname = cfg.path("facebook.timezone", "UTC")
            nxt = datetime.fromisoformat(rows[0][1]["publish_at"])
            log.info("التالي: %s", describe(nxt, tzname))
        return 0

    lines, published = [], 0
    for path, draft in due:
        ok, line = publish_one(path, draft, cfg)
        published += ok
        lines.append(line)

    report(lines, published, len(due))
    return 0


def cmd_now(ids: list[str], cfg, issue_number: int | None) -> int:
    """نشر فوري بلا جدولة."""
    lines, published, total = [], 0, 0
    for draft_id in ids:
        found = store.load_draft(draft_id)
        if not found:
            lines.append(f"- ❌ `{draft_id}` — غير موجودة")
            continue
        path, draft = found
        if draft.get("status") == "published":
            lines.append(f"- ↩️ `{draft_id}` — منشور مسبقًا")
            continue
        total += 1
        ok, line = publish_one(path, draft, cfg)
        published += ok
        lines.append(line)

    report(lines, published, total, issue_number, close=True)
    return 0


def cmd_queue(cfg) -> int:
    tzname = cfg.path("facebook.timezone", "UTC")
    rows = queued_drafts()
    if not rows:
        print("الطابور فارغ.")
        return 0
    print(f"\n{len(rows)} منشور في الطابور (بتوقيت {tzname}):\n")
    for _, d in rows:
        when = datetime.fromisoformat(d["publish_at"])
        mark = "⏰ مستحق" if is_due(when) else "      "
        print(f"  {mark} {describe(when, tzname)}  {d['arabic']['post_title'][:55]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="جدولة ونشر المسودات المعتمدة")
    parser.add_argument("--issue", type=int, help="رقم Issue المراجعة")
    parser.add_argument("--ids", help="معرفات مفصولة بفواصل (نشر فوري)")
    parser.add_argument("--due", action="store_true", help="نشر ما حان وقته")
    parser.add_argument("--now", action="store_true", help="نشر فوري بلا جدولة")
    parser.add_argument("--queue", action="store_true", help="عرض الطابور")
    parser.add_argument("--verify", action="store_true", help="فحص التوكن")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")
    cfg = load_config(args.config)

    if args.verify:
        info = facebook.verify_token(cfg.path("facebook.api_version", "v21.0"))
        log.info("✅ التوكن صالح — الصفحة: %s (%s متابع)",
                 info.get("name"), info.get("fan_count", "?"))
        return 0

    if args.queue:
        return cmd_queue(cfg)
    if args.due:
        return cmd_due(cfg)
    if args.ids:
        return cmd_now([i.strip() for i in args.ids.split(",") if i.strip()], cfg, None)

    if not args.issue:
        parser.error("حدّد --issue أو --ids أو --due أو --queue")
        return 2

    issue = fetch_issue(args.issue)
    body = issue.get("body") or ""
    ids = review.parse_approved(body)
    log.info("الـ Issue #%s: %d معتمد من %d",
             args.issue, len(ids), len(review.all_draft_ids(body)))

    if not ids:
        log.warning("لم يُعلَّم على أي منشور")
        review.comment(args.issue,
                       "⚠️ لم يُعلَّم على أي منشور. أضف ✔️ ثم أعد وسم `approved`.")
        review.remove_label(args.issue, "approved")
        return 0

    if args.now or not cfg.path("facebook.schedule_enabled", True):
        return cmd_now(ids, cfg, args.issue)
    if cfg.path("facebook.schedule_mode", "burst") == "burst":
        return cmd_burst(ids, cfg, args.issue)
    return cmd_schedule(ids, cfg, args.issue)


if __name__ == "__main__":
    raise SystemExit(main())
