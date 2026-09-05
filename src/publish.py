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
import random
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

import requests

from . import decisions, facebook, review, store
from .config import ROOT, env, load_config
from .reel import build_reel, has_ffmpeg
from .schedule import assign_slots, describe, is_due, spaced_slots

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
        if data.get("status") != "queued":
            continue
        if store.origin_of(data) == "analysis":
            # مسار التحليل له طابور ونشر خاصّان بسقف وتباعد مختلفين
            # (youtube_publish.publish_approved)، ولا تُبنى بطاقته (حقل
            # image) إلا بعد اعتماد صريح هناك. لو تسرّبت مسودة منه إلى هذا
            # الطابور العام (خلطًا في فتح Issue المراجعة العام — Issue
            # #707)، فهي ناقصة الحقول بنيويًا ويجب ألا تُعالَج هنا أصلًا.
            continue
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


def ensure_reel(path, draft: dict, cfg) -> Path | None:
    """
    يبني الريل عند الحاجة فقط.

    كان يُبنى لكل مسودة أثناء الجمع، فتُهدر دقائق حوسبة على ريلز لا
    تُنشر أصلًا. الآن يُبنى لحظة النشر، وللمعتمَد فقط.
    """
    existing = draft.get("reel")
    if existing and (ROOT / existing).exists():
        return ROOT / existing

    spec = draft.get("reel_spec") or {}
    if not spec:
        log.warning("لا مواصفات ريل في المسودة — سيُنشر كصورة")
        return None
    if not has_ffmpeg():
        log.warning("⚠️ ffmpeg غير مثبّت — سيُنشر كصورة")
        return None

    relative = f"{Path(draft['image']).parent}/{draft['id']}.mp4"
    log.info("بناء الريل عند الطلب…")
    built = build_reel(
        spec.get("headline", draft["arabic"]["post_title"]),
        spec.get("category", ""),
        bool(spec.get("urgent")),
        spec.get("image_candidates") or [],
        cfg, ROOT / relative,
    )
    if not built:
        log.warning("تعذّر بناء الريل — سيُنشر كصورة")
        return None

    store.update_draft(path, reel=relative)
    return ROOT / relative


def _missing_draft_fields(draft: dict) -> list[str]:
    """الحقول التي يعتمد عليها ``publish_one`` بلا شرط. مسودة يوتيوب لم
    تُعتمَد بعد (أو أي مسودة معطوبة أخرى) قد تفتقد ``image`` تحديدًا —
    عمدًا، لا خطأً (Issue #680) — قبل أن تُبنى بطاقتها لحظة الاعتماد."""
    missing = []
    if not draft.get("image"):
        missing.append("image")
    if not draft.get("caption"):
        missing.append("caption")
    if not (draft.get("arabic") or {}).get("post_title"):
        missing.append("arabic.post_title")
    return missing


def publish_one(path, draft: dict, cfg) -> tuple[bool, str]:
    """ينشر مسودة واحدة صورةً أو ريلًا. يعيد (نجح، سطر التقرير).

    مسودة ناقصة حقلًا أساسيًا (مثلًا مسودة يوتيوب تسرّبت إلى الطابور العام
    بلا حقل image — Issue #707) تُسجَّل failed وتُتخطى بدل أن تُسقط
    ``KeyError`` كامل الدفعة: مسودة واحدة معطوبة يجب ألا توقف بقية
    المنشورات السليمة في نفس التشغيلة.
    """
    missing = _missing_draft_fields(draft)
    if missing:
        title = draft.get("id", "?")
        detail = f"حقول مفقودة: {', '.join(missing)}"
        log.warning("مسودة %s ناقصة الحقول (%s) — تُتخطى بلا نشر", title, detail)
        store.update_draft(path, status="failed", error=detail)
        return False, f"- ❌ `{title}` — {detail}"

    api_version = cfg.path("facebook.api_version", "v21.0")
    image_path = ROOT / draft["image"]
    title = draft["arabic"]["post_title"][:60]
    comment = first_comment_for(draft, cfg)

    reel_path = ensure_reel(path, draft, cfg) if draft.get("publish_as_reel") else None

    if reel_path:
        try:
            res = facebook.publish_reel(reel_path, draft["caption"],
                                        api_version, first_comment=comment)
            store.update_draft(
                path, status="published",
                published_at=datetime.now(timezone.utc).isoformat(),
                facebook=res)
            decisions.record_published(draft)
            return True, f"- 🎬 [{title}]({res.get('url') or '#'})"
        except facebook.FacebookError as exc:
            log.warning("فشل نشر الريل — سيُنشر كصورة: %s", exc)

    if not image_path.exists():
        store.update_draft(path, status="failed", error="الصورة مفقودة")
        return False, f"- ❌ {title} — الصورة مفقودة"

    try:
        res = facebook.publish_photo(
            image_path, draft["caption"], api_version, first_comment=comment,
        )
    except facebook.FacebookError as exc:
        store.update_draft(path, status="failed", error=str(exc))
        return False, f"- ❌ {title} — {exc}"

    store.update_draft(
        path, status="published",
        published_at=datetime.now(timezone.utc).isoformat(),
        facebook=res,
    )
    decisions.record_published(draft)
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


def cmd_burst(ids: list[str], cfg, issue_number: int | None,
              only_urgent: bool = False, skip_urgent: bool = False,
              inline_cap_minutes: float | None = None) -> int:
    """
    ينشر المعتمَد وفق أربع قواعد:

      1. منشور واحد فقط           → فورًا
      2. عاجل                     → فورًا مهما كان العدد
      3. أكثر من واحد وليس عاجلًا → الأعلى مؤشرًا فورًا
      4. البقية                   → فاصل عشوائي 30-60 دقيقة

    الفاصل عشوائي لا ثابت: النشر على إيقاع منتظم تمامًا نمط آلي واضح.

    ``inline_cap_minutes`` يتجاوز ``facebook.max_inline_minutes`` من
    الإعداد عند تمريره صراحة (Issue #315): استدعاء collect_finalize.finalize
    يمرّر 0 لأنه يعمل داخل مهمة urgent (سقفها 20 دقيقة في publish.yml)،
    وأصغر فاصل يحسبه spaced_slots هو 30 دقيقة — أي sleep واحد يتجاوز
    السقف حتمًا. بصفر، يُنشر المستحق الآن فقط (wait<=0) والبقية تُعلَّم
    queued بلا انتظار، ويلتقطها سيّر queue.yml كل 30 دقيقة.
    """
    fcfg = cfg.get("facebook", {}) or {}
    gap_min = float(fcfg.get("gap_min_minutes", 30))
    gap_max = float(fcfg.get("gap_max_minutes", 60))
    tzname = fcfg.get("timezone", "UTC")
    max_inline = (float(inline_cap_minutes) if inline_cap_minutes is not None
                 else float(fcfg.get("max_inline_minutes", 120)))

    lines: list[str] = []
    pending = collect_pending(ids, lines)      # مرتّبة تنازليًا بالمؤشر
    if not pending:
        text = "### ℹ️ لا جديد للنشر\n" + "\n".join(lines)
        if issue_number:
            review.comment(issue_number, text)
        return 0

    urgent = [t for t in pending if t[1]["arabic"].get("urgent")]
    normal = [t for t in pending if not t[1]["arabic"].get("urgent")]

    # مساران مستقلان: العاجل لا يقف خلف طابور العادي.
    # القاعدة كانت تعمل داخل التشغيل الواحد، لكن قفل التزامن كان يوقف
    # تشغيل العاجل خلف تشغيل عادي قد ينتظر ساعتين قبل منشوره التالي.
    if only_urgent:
        normal = []
        if not urgent:
            log.info("لا عاجل في هذه الدفعة — المسار السريع ينتهي")
            return 0
    elif skip_urgent:
        urgent = []
        if not normal:
            log.info("لا عادي في هذه الدفعة")
            return 0

    now = datetime.now(timezone.utc)
    plan: list[tuple] = [(item, now) for item in urgent]   # كل عاجل فورًا

    if normal:
        # الأعلى مؤشرًا فوري إن لم يسبقه عاجل، وإلا فبعد فاصل
        first = now if not urgent else None
        slots = spaced_slots(len(normal), gap_min, gap_max,
                             now=first or now)
        if urgent:
            shift = slots[0] - now
            offset = timedelta(minutes=random.uniform(gap_min, gap_max))
            slots = [t - shift + offset for t in slots]
        plan += list(zip(normal, slots))

    for (path, _), when in plan:
        store.update_draft(path, status="queued", publish_at=when.isoformat())

    log.info("عاجل: %d (فوري) · عادي: %d (فاصل %g-%g دقيقة)",
             len(urgent), len(normal), gap_min, gap_max)

    published, deferred_count = 0, 0
    for (path, draft), when in plan:
        wait = (when - datetime.now(timezone.utc)).total_seconds()
        if wait > max_inline * 60:
            deferred_count += 1
            lines.append(f"🕐 {draft['arabic']['post_title'][:50]} → "
                         f"**{describe(when, tzname)}**")
            continue

        fresh = store.load_draft(draft["id"])
        if not fresh or fresh[1].get("status") == "published":
            continue

        # الفاصل بعد النشر الفعلي فقط (Issue #740): مسودة ستُتخطى حتمًا
        # (ناقصة حقلًا أساسيًا — مثلًا مسودة يوتيوب تسرّبت إلى هذا الطابور
        # قبل التوجيه بالأصل أعلاه، أو أي تعطّب بيانات آخر) لا تستحق انتظار
        # موعدها المجدول: عطل حقيقي وقع حين انتظر السير 30-60 دقيقة كاملة
        # قبل كل مسودة من أربع خرجت failed فورًا بلا نشر.
        if wait > 0 and not _missing_draft_fields(fresh[1]):
            log.info("انتظار %.0f دقيقة قبل المنشور التالي…", wait / 60)
            time.sleep(wait)

        ok, line = publish_one(fresh[0], fresh[1], cfg)
        published += ok
        mark = "🔴 عاجل " if draft["arabic"].get("urgent") else ""
        lines.append(mark + line.lstrip("- "))
        log.info("(%d/%d) %s", len(lines), len(plan), line[:70])

    header = (f"### {'🔴 عاجل' if only_urgent else '🚀'} نُشر {published} "
              f"من {len(plan)}\n"
              f"<sub>العاجل والأعلى مؤشرًا فورًا، والبقية بفاصل "
              f"{gap_min:g}-{gap_max:g} دقيقة"
              + (f" · {deferred_count} في الطابور" if deferred_count else "")
              + f" (بتوقيت {tzname}).</sub>\n")
    text = header + "\n".join(f"- {l}" for l in lines)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    if issue_number:
        review.comment(issue_number, text)
        # المسار السريع لا يغلق الـ Issue: العادي ما زال ينتظر نشره
        if published and not only_urgent:
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
    """ينشر أقدم مسودة مستحقة فقط — لا الدفعة كاملة دفعة واحدة.

    قوائم الانتظار تُبنى بفواصل عشوائية 30-60 دقيقة (spaced_slots) كي لا
    يبدو النشر آليًا. لو فاتت queue.yml تشغيلة أو أكثر (جدولة GitHub غير
    مضمونة — Issue #327)، يتراكم أكثر من منشور مستحق معًا؛ نشرها كلها في
    حلقة واحدة بلا فاصل ينتج بالضبط النمط الآلي الذي صُمم spaced_slots
    لتجنبه. لذا تشغيلة واحدة تنشر الأقدم فقط، وتترك الباقي فيلتقطه
    التشغيلات التالية — فالفاصل بين المنشورات المتراكمة يصبح فاصل
    التشغيلات نفسه بدل صفر.
    """
    rows = queued_drafts()
    due = [(p, d) for p, d in rows if is_due(d.get("publish_at", ""))]
    if not due:
        log.info("لا شيء مستحق الآن (%d في الطابور)", len(rows))
        if rows:
            tzname = cfg.path("facebook.timezone", "UTC")
            nxt = datetime.fromisoformat(rows[0][1]["publish_at"])
            log.info("التالي: %s", describe(nxt, tzname))
        return 0

    if len(due) > 1:
        log.info("%d منشورًا مستحقًا معًا — يُنشر الأقدم فقط، والبقية "
                 "تنتظر التشغيلة التالية", len(due))

    path, draft = due[0]
    ok, line = publish_one(path, draft, cfg)
    report([line], int(ok), 1)
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
    parser.add_argument("--urgent-only", action="store_true",
                        help="نشر العاجل فقط — للمسار السريع")
    parser.add_argument("--skip-urgent", action="store_true",
                        help="تخطّي العاجل — للمسار العادي")
    parser.add_argument("--verify", action="store_true", help="فحص التوكن")
    parser.add_argument("--diagnose", action="store_true",
                        help="فحص شامل لأسباب ضعف الوصول")
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

    if args.diagnose:
        for line in facebook.diagnose(cfg.path("facebook.api_version", "v21.0")):
            print(line)
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

    # Issue #280: وسم approved على Issue اختيار (pending-selection) يعني
    # "اصغ وانشر المختار فقط" لا "انشر مسودات جاهزة" — مسار مختلف تمامًا
    # يعيد استعمال نفس محفّز الوسم بلا سير عمل إضافي (لا يتضاعف عدد الـ
    # Issues). لا حاجة لتمييز شبيه في cmd_now/cmd_burst/cmd_schedule نفسها،
    # فهي تُستدعى من collect_finalize.finalize بعد الصياغة كمسودات عادية.
    labels = {l.get("name") for l in issue.get("labels", [])}
    # Issue #296: الاثنان معًا يعني Issue خُلط أصله (لا أحد في الكود ينشئ
    # Issue بالوسمين معًا عمدًا) — التفويض القديم كان يفوز لـ
    # pending-selection بلا شرط ويتجاهل الاحتمال الآخر بصمت، فيصطدم أحيانًا
    # بجسم Issue بصيغة "مراجعة مسودات" (draft:) لا "اختيار مرشحين" (cand:)
    # فلا يُنتج شيئًا ويُزيل approved بصمت. الآن نرفض الحسم التلقائي.
    if "pending-selection" in labels and "pending-review" in labels:
        log.error("Issue #%s يحمل pending-selection وpending-review معًا "
                  "— لا تفويض تلقائي آمن", args.issue)
        review.comment(
            args.issue,
            "⚠️ هذا الـ Issue يحمل الوسمين `pending-selection` و`pending-review` "
            "معًا — تعارض لا يمكن حسمه تلقائيًا (لا يتضح أهو Issue اختيار "
            "مرشحين أم مراجعة مسودات جاهزة). لم يُنفَّذ أي شيء. أزل أحد "
            "الوسمين يدويًا بحسب صيغة جسم الـ Issue الفعلية "
            "(مربعات `<!-- cand:... -->` = اختيار مرشحين، "
            "`<!-- draft:... -->` = مراجعة مسودات) ثم أعد وسم `approved`.",
        )
        return 1
    if "pending-selection" in labels:
        # Issue #308: publish.yml يُشغّل مساري urgent وnormal لنفس حدث وسم
        # approved معًا (needs: لا يمنع التشغيل، فقط يرتّب التتابع)، وكلاهما
        # يصل هذا الفرع. finalize لا يفرّق عاجلًا من عادي داخليًا — تفويضة
        # واحدة تكفي وتغطي الاثنين معًا (تُشغِّل cmd_burst بلا تقسيم). دون
        # هذا الشرط كانت التشغيلتان تصوغان الخبر وتنشرانه مرتين مستقلتين.
        # المسار السريع (بلا --skip-urgent) هو من ينفّذها؛ المسار العادي
        # (--skip-urgent) يتخطّاها بصمت.
        if args.skip_urgent:
            log.info("Issue #%s: pending-selection — تخطّي المسار العادي "
                     "(المسار السريع ينفّذ finalize وحده)", args.issue)
            return 0
        from . import collect_finalize
        return collect_finalize.finalize(args.issue, body, cfg)

    ids = review.parse_approved(body)
    reels = review.parse_reels(body)

    # مربعا الاعتماد والرفض قد يُعلَّمان معًا: مراجع اعتمد أولًا ثم عدل
    # عن رأيه فعلّم السبب دون أن يمسح ✔️. النشر حينها خطأ لا يُستدرك،
    # فالرفض يغلب — وعكسه ينشر خبرًا رُفض صراحةً.
    rejected = {did for did, _ in review.parse_rejects(body)}
    blocked = [i for i in ids if i in rejected]
    if blocked:
        ids = [i for i in ids if i not in rejected]
        log.warning("أُسقط %d منشورًا معلَّمًا بالاعتماد والرفض معًا", len(blocked))
        review.comment(
            args.issue,
            f"⚠️ {len(blocked)} منشورًا يحمل ✔️ وسبب رفض معًا — لم يُنشر. "
            "امسح سبب الرفض إن كنت تريد نشره.",
        )

    log.info("الـ Issue #%s: %d معتمد من %d (%d كريل)",
             args.issue, len(ids), len(review.all_draft_ids(body)), len(reels))

    if not ids:
        log.warning("لم يُعلَّم على أي منشور")
        review.comment(args.issue,
                       "⚠️ لم يُعلَّم على أي منشور. أضف ✔️ ثم أعد وسم `approved`.")
        review.remove_label(args.issue, "approved")
        return 0

    # التوجيه بالأصل لا بالوسم (Issue #740): وسم approved واحد كافٍ للمسارين
    # معًا الآن — القرار بالأصل الفعلي المخزَّن في كل مسودة معتمَدة، لا بعنوان
    # أو وسم الـIssue نفسه. عطل حقيقي وقع حين وُسم Issue مراجعة يوتيوب
    # (`youtube-review`، يستعمل نفس صيغة <!-- draft:id --> وreview.parse_approved
    # المشتركة) بـ`approved` سهوًا بدل `youtube-approved`: منطق الأخبار التقط
    # مسودات يوتيوب الناقصة حقل image بنيويًا (Issue #680) فسجّلها failed
    # وأهدر ساعات في فاصل النشر (Issue #707/#740). التمييز هنا برمجي لكل
    # معرّف على حدة، لا حسمًا واحدًا لكل الدفعة، فإن اجتمع الأصلان يومًا في
    # نفس الـIssue (لا يُصمَّم لذلك، لكن لا افتراض يمنعه) يُعالَج كل جزء
    # بمنطقه الصحيح.
    analysis_ids, news_ids = [], []
    for draft_id in ids:
        found = store.load_draft(draft_id)
        origin = store.origin_of(found[1]) if found else None
        (analysis_ids if origin == "analysis" else news_ids).append(draft_id)

    # Issue #745: publish.yml يُشغّل urgent (--urgent-only، مهلة ٢٠ دقيقة)
    # ثم normal (--skip-urgent، مهلة ١٥٠) على نفس حدث وسم approved، وكلاهما
    # يصل هذا الفرع — توجيه التحليل كان يقع قبل انقسام urgent/skip فيعمل في
    # الاثنتين. مقال التحليل ليس عاجلًا أبدًا (دفعة ٣ منشورات × ٤٠ دقيقة
    # تباعدًا لا تحتمل سقف ٢٠ دقيقة)، فيُحصر التوجيه بالمسار العادي وحده —
    # نفس نمط حراسة urgent/skip في pending-selection أعلاه (Issue #308)،
    # لكن بالاتجاه المعاكس: هناك السريع ينفّذ والعادي يتخطّى؛ هنا العكس.
    if analysis_ids and args.urgent_only:
        log.info("Issue #%s: %d مسودة تحليل — تُؤجَّل للمسار العادي "
                 "(المسار السريع لا يعالج توجيه التحليل)",
                 args.issue, len(analysis_ids))
    elif analysis_ids:
        # استيراد مؤجَّل — لا على مستوى الوحدة: youtube_publish.py يستورد
        # publish (لإعادة استعمال publish_one بلا تكرار منطقها)، فاستيراد
        # youtube_publish من publish على مستوى الوحدة يسبّب دورانًا
        # (كل وحدة تحاول تحميل الأخرى غير المكتملة بعد أثناء الإقلاع).
        # الاستيراد هنا يقع بعد اكتمال تحميل كلا الوحدتين فعليًا فلا دوران.
        from . import youtube_publish
        yt_lines, yt_published, yt_attempted, yt_remaining = youtube_publish.publish_ids(
            analysis_ids, youtube_publish.parse_headline_choice(body), cfg)
        youtube_publish.report_batch(
            args.issue, yt_lines, yt_published, yt_attempted, yt_remaining, cfg)

    if not news_ids:
        return 0

    for draft_id in reels & set(news_ids):
        found = store.load_draft(draft_id)
        if found:
            store.update_draft(found[0], publish_as_reel=True)

    if args.now or not cfg.path("facebook.schedule_enabled", True):
        return cmd_now(news_ids, cfg, args.issue)
    if cfg.path("facebook.schedule_mode", "burst") == "burst":
        return cmd_burst(news_ids, cfg, args.issue,
                         only_urgent=args.urgent_only,
                         skip_urgent=args.skip_urgent)
    return cmd_schedule(news_ids, cfg, args.issue)


if __name__ == "__main__":
    raise SystemExit(main())
