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

from . import cards, decisions, facebook, feedback, review, store
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
        if store.origin_of(data) == "analysis" and not data.get("image"):
            # مسار التحليل صار يدخل هذا الطابور العام أيضًا منذ بوابة الفاصل
            # (Issue #1010): مسودة تحليل تؤجّلها البوابة داخل
            # youtube_publish.publish_ids مرّت أصلًا بـensure_title_card قبل
            # محاولة النشر، فحقل image موجود دومًا حين التأجيل طبيعي. غيابه
            # هنا عطب بنيوي بحت — تسرّب من فتح Issue مراجعة عام قبل الاعتماد
            # (نفس علّة الاستثناء القديم، Issue #707/#680) — فتُتخطى بسطر
            # سجل بدل أن تُعالَج هنا بلا بطاقة.
            log.warning("مسودة تحليل %s بلا صورة — تُتخطّى من الطابور العام",
                       data.get("id"))
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


def _is_urgent(draft: dict) -> bool:
    return bool((draft.get("arabic") or {}).get("urgent"))


def _gap_defer_until(cfg) -> datetime | None:
    """موعد التأجيل إن مرّ على آخر منشور فعلي أقل من
    ``facebook.gap_min_minutes``، أو ``None`` إن لا داعي للتأجيل (Issue
    #1010). المصدر ``store.last_publish_at`` — لا «الآن» ولا مواعيد الطابور
    المحجوزة وحدها — فدفعة اعتُمدت للتو لا يمكنها تجاهل نشر خرج فعلًا قبل
    لحظات من دفعة أخرى مستقلة تمامًا (Issue، أو /صورة، أو --ids مباشرة)."""
    fcfg = cfg.get("facebook", {}) or {}
    gap_min = float(fcfg.get("gap_min_minutes", 30))
    gap_max = float(fcfg.get("gap_max_minutes", 60))
    last = store.last_publish_at()
    if last is None:
        return None
    now = datetime.now(timezone.utc)
    if now - last >= timedelta(minutes=gap_min):
        return None
    return last + timedelta(minutes=random.uniform(gap_min, gap_max))


def publish_one(path, draft: dict, cfg) -> tuple[bool, str]:
    """ينشر مسودة واحدة صورةً أو ريلًا. يعيد (نجح، سطر التقرير).

    مسودة ناقصة حقلًا أساسيًا (مثلًا مسودة يوتيوب تسرّبت إلى الطابور العام
    بلا حقل image — Issue #707) تُسجَّل failed وتُتخطى بدل أن تُسقط
    ``KeyError`` كامل الدفعة: مسودة واحدة معطوبة يجب ألا توقف بقية
    المنشورات السليمة في نفس التشغيلة.

    بوابة الفاصل (Issue #1010) هي القاعدة الوحيدة لإيقاع الصفحة عبر كل
    المسارات عدا العاجل، وتسبق أي عمل شبكي هنا: مسودة عاجلة (``arabic.urgent``
    — نفس فحص العجلة الذي يوجّه urgent/normal في ``cmd_burst``) تتجاوزها
    دومًا بلا أي تغيير. غير ذلك، إن مرّ على آخر منشور فعلي أقل من
    ``facebook.gap_min_minutes``، لا تُنشر: تصير ``queued`` بموعد جديد ضمن
    ``gap_min_minutes``-``gap_max_minutes`` بعد ذلك المنشور، والتأجيل ليس
    فشلًا — لا ``failed``، ولا ``failed_stage``، ولا ``error``، ولا قيد في
    ``decisions`` (نظير مبدأ ``queued`` الطبيعي في المسار العادي).
    """
    missing = _missing_draft_fields(draft)
    if missing:
        title = draft.get("id", "?")
        detail = f"حقول مفقودة: {', '.join(missing)}"
        log.warning("مسودة %s ناقصة الحقول (%s) — تُتخطى بلا نشر", title, detail)
        store.update_draft(path, status="failed", error=detail)
        return False, f"- ❌ `{title}` — {detail}"

    title = draft["arabic"]["post_title"][:60]

    if not _is_urgent(draft):
        when = _gap_defer_until(cfg)
        if when is not None:
            tzname = cfg.path("facebook.timezone", "UTC")
            store.update_draft(path, status="queued", publish_at=when.isoformat())
            return False, f"- ⏳ {title} — مؤجَّل إلى {describe(when, tzname)}"

    api_version = cfg.path("facebook.api_version", "v21.0")
    image_path = ROOT / draft["image"]
    comment = first_comment_for(draft, cfg)

    reel_path = ensure_reel(path, draft, cfg) if draft.get("publish_as_reel") else None

    if reel_path:
        try:
            res = facebook.publish_reel(reel_path, draft["caption"],
                                        api_version, first_comment=comment)
            now = datetime.now(timezone.utc)
            store.update_draft(
                path, status="published",
                published_at=now.isoformat(),
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
        # failed_stage مقصور على هذا الموضع وحده (Issue #959): فشل هنا وحده
        # قابل للإحياء عبر Issue إحياء مستقل (open_review._revivable_drafts)
        # — «حقول مفقودة» (أعلاه) عطب بنيوي، و«الصورة مفقودة» (أسفله) لها
        # طريق /صورة القائم أصلًا، فكلاهما لا يحتاج مسارًا جديدًا.
        store.update_draft(
            path, status="failed", error=str(exc),
            failed_stage="facebook",
            failed_at=datetime.now(timezone.utc).isoformat(),
        )
        return False, f"- ❌ {title} — {exc}"

    now = datetime.now(timezone.utc)
    store.update_draft(
        path, status="published",
        published_at=now.isoformat(),
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
        # نقطة الانطلاق تحترم آخر منشور فعلي وآخر موعد محجوز معًا (Issue
        # #1010)، لا «الآن» وحدها — بوابة publish_one ستؤجِّل على أي حال إن
        # فاتها هذا، لكن حسابها هنا مسبقًا يمنع دورة تأجيل/إعادة جدولة لا
        # داعي لها لكل مسودة في الدفعة.
        last_pub = store.last_publish_at()
        booked = booked_times()
        start = now
        if last_pub is not None:
            start = max(start, last_pub + timedelta(minutes=gap_min))
        if booked:
            start = max(start, max(booked) + timedelta(minutes=gap_min))

        # الأعلى مؤشرًا فوري إن لم يسبقه عاجل ولا فاصل مستحق بعد، وإلا فبعد فاصل
        first = start if not urgent else None
        slots = spaced_slots(len(normal), gap_min, gap_max,
                             now=first or start)
        if urgent:
            shift = slots[0] - start
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
        # Issue #765، بند 3: منشور تحقيق يجب أن يمرّ بمراجعة Issue دومًا —
        # issue_number is None يعني هذا الاستدعاء جاء من --ids المباشر (نشر
        # فوري بمعرّف بلا قراءة مربعات اعتماد أصلًا)، لا من ids المُستخرجة
        # فعليًا عبر review.parse_approved في المسار المعتاد (args.issue حقيقي
        # دومًا هناك). لا نشر تلقائي يلتقط مسودة تحقيق خارج تلك القراءة.
        if draft.get("is_investigation") and issue_number is None:
            lines.append(f"- 🚫 `{draft_id}` — مسودة تحقيق: تتطلب مراجعة Issue فعلية، "
                         "لا نشرًا مباشرًا بالمعرّف")
            continue
        total += 1
        ok, line = publish_one(path, draft, cfg)
        published += ok
        lines.append(line)

    report(lines, published, total, issue_number, close=True)
    return 0


def open_final_review(primary_issue: int, draft_ids: list[str], cfg) -> None:
    """يفتح Issue مراجعة نهائية واحدًا يعرض بطاقة كل منشور عُلِّم عليه 🎴 في
    هذه الدفعة (Issue #858، الجزء الثاني) -- البطاقة مبنيّة مسبقًا فعليًا
    (publish.main يبنيها لكل معتمَد، بصرف النظر عن 🎴، قبل هذا التفرّع، انظر
    توثيق CLAUDE.md) فلا بناء هنا، فقط عرض للمراجع قبل النشر الفعلي.

    عامة لا خاصة بمسار الأخبار (اسمها بلا شرطة سفلية منذ Issue #1000): مسار
    التحليل يستدعيها أيضًا (youtube_publish.publish_ids) لمن عُلِّم عليه 🎴
    هناك -- نفس بناء review.build_final_review_body، لا باني نصّ ثالث
    (نصّ طلب الإصدار: "لا باني نصّ ثالث"). البطاقة هناك أيضًا مبنيّة مسبقًا
    (ensure_title_card) قبل هذا النداء، بنفس المبدأ."""
    rows = []
    for draft_id in draft_ids:
        found = store.load_draft(draft_id)
        if found:
            rows.append(found)
    if not rows:
        return

    # تنازليًا بالدرجة للعرض فقط (Issue #874) — لا علاقة بترتيب القراءة
    # أعلاه، المبني على draft_ids كما وردت من مربعات الاعتماد.
    rows = review.sort_by_score(rows, key=lambda row: row[1])

    repo = env("GITHUB_REPOSITORY") or ""
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    review.ensure_labels()
    drafts = [d for _, d in rows]
    issue = review.create_issue(
        title=(f"🎴 مراجعة نهائية {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC "
               f"— {len(drafts)} منشور"),
        body=review.build_final_review_body(drafts, repo, branch),
        labels=["final-review"],
    )
    for path, _ in rows:
        store.update_draft(path, review_issue=issue["number"])

    review.comment(
        primary_issue,
        f"🎴 {len(drafts)} منشور بانتظار مراجعة نهائية للبطاقة قبل النشر — "
        f"Issue #{issue['number']}.",
    )


def cmd_final_review(issue_number: int, body: str, cfg) -> int:
    """اعتماد Issue المراجعة النهائية (Issue #858، الجزء الثاني): المعلَّم
    يُنشر مباشرة بلا إعادة بناء بطاقة ولا اختيار عنوان ولا تعديل نص --
    البطاقة مبنيّة مسبقًا والعنوان محسوم منذ المراجعة الأولية. ما لم يُعلَّم
    (ولم يُعلَّم بـ↩️) يصير rejected بنفس آلية الرفض التلقائي في المسار
    العادي (Issue #841). ↩️ يغلب ✔️ على نفس المنشور -- نفس مبدأ «الرفض يغلب
    الاعتماد» القائم قبل Issue #841. حارس النشر المزدوج (status ==
    "published") ضروري هنا تحديدًا لأن publish.yml يُشغّل مساري urgent
    وnormal لنفس حدث وسم approved معًا (Issue #745)، وكلاهما قد يصل هذا
    الفرع لنفس الـIssue النهائي.

    **مسودات التحليل تُفصَل عن الباقي وتُنشر عبر youtube_publish.publish_ids
    (Issue #1008):** نشر المعلَّم هنا كان يستدعي publish_one في حلقة بلا سقف
    ولا فاصل -- دفعة تحليل واصلة من Issue نهائي (Issue #1000) كانت تخرج دفعة
    واحدة، متجاوزة youtube.publish.max_per_run/spacing_minutes اللذين يطبّقهما
    publish_ids في كل مسار تحليل آخر (المسار العادي، وcmd_revival). ``body``/
    ``issue_number`` فارغان في هذا النداء عمدًا -- جسم Issue المراجعة النهائية
    لا يحمل مربعات 🎴 إطلاقًا (البطاقة والعنوان محسومان مسبقًا، نفس مبدأ
    #858)، فتمرير جسمه الفعلي قد يُقرأ خطأً كمربع 🎴 من نصّ آخر ويعيد فتح
    Issue نهائي ثانٍ. مسار الأخبار يبقى بلا سقف دفعة كما كان منذ #858 -- كل
    معتمَد يُمرَّر إلى publish_one في حلقة واحدة بلا تقطيع؛ الفاصل بين
    المنشورات غير العاجلة صار مضمونًا من داخل publish_one نفسها (بوابة
    الفاصل، Issue #1010) لا من هذه الحلقة.

    الباقي فوق السقف يُعالَج بنفس آلية cmd_revival حرفيًا (Issue #961): الـ
    Issue لا يُغلق، وسم approved يُزال عبر review.remove_label، وسطر ⏳ لكل
    مسودة باقية + سطر ختامي يطلب إعادة الوسم لمتابعتها."""
    all_ids = review.all_draft_ids(body)
    back_ids = review.parse_back_requests(body)
    approved_ids = [i for i in review.parse_approved(body) if i not in back_ids]

    lines: list[str] = []

    for draft_id in back_ids:
        found = store.load_draft(draft_id)
        if not found:
            continue
        path, draft = found
        if draft.get("status") != "pending":
            continue
        store.update_draft(path, status="pending",
                           remove=["image", "image_info", "review_issue"])
        lines.append(f"- ↩️ {draft['arabic']['post_title'][:50]} — أُعيد للمراجعة الأولية")

    # عدم الاعتماد (ولا العودة) = رفض ضمني، بنفس مبدأ المسار العادي
    # (Issue #841) — مقيَّد بمعرّفات هذا الـIssue وحده.
    to_reject = [i for i in all_ids if i not in back_ids and i not in approved_ids]
    if to_reject:
        entries = feedback.load()
        rejected_now = 0
        for draft_id in to_reject:
            found = store.load_draft(draft_id)
            if not found or found[1].get("status") != "pending":
                continue
            store.update_draft(found[0], status="rejected")
            feedback.record(entries, found[1], tag="لم يُعتمد", note="")
            decisions.record_rejected_unchecked(found[1])
            rejected_now += 1
        if rejected_now:
            feedback.save(entries)
            log.info("الـIssue النهائي #%s: %d مسودة لم تُعتمد — سُجّلت مرفوضة",
                     issue_number, rejected_now)

    published = 0
    analysis_ids: list[str] = []
    news_pending: list[tuple] = []
    for draft_id in approved_ids:
        found = store.load_draft(draft_id)
        if not found:
            lines.append(f"- ❌ `{draft_id}` — المسودة غير موجودة")
            continue
        path, draft = found
        if draft.get("status") == "published":
            # حارس النشر المزدوج (Issue #858) -- نفس مبدأ فحص status في
            # youtube_publish.publish_ids.
            lines.append(f"- ↩️ {draft['arabic']['post_title'][:50]} — منشور مسبقًا")
            continue
        if store.origin_of(draft) == "analysis":
            analysis_ids.append(draft_id)
        else:
            news_pending.append((path, draft))

    # مسار الأخبار: بلا سقف دفعة -- بلا تغيير عن #858. الفاصل بين غير العاجل
    # تكفّلت به بوابة publish_one (Issue #1010): معتمَد قد يخرج queued بدل
    # published إن نُشر شيء آخر قبله بلحظات من دفعة مستقلة.
    for path, draft in news_pending:
        ok, line = publish_one(path, draft, cfg)
        published += ok
        lines.append(line)

    analysis_remaining: list[str] = []
    if analysis_ids:
        from . import youtube_publish
        yt_lines, yt_published, _, analysis_remaining = youtube_publish.publish_ids(
            analysis_ids, {}, cfg)
        lines += yt_lines
        published += yt_published
        if analysis_remaining:
            for rid in analysis_remaining:
                found = store.load_draft(rid)
                title = found[1]["arabic"]["post_title"][:50] if found else rid
                lines.append(f"- ⏳ {title} — ينتظر تشغيلة لاحقة")
            lines.append("أعد وضع وسم `approved` لمتابعة الباقي")

    report(lines, published, len(approved_ids), issue_number, close=not analysis_remaining)
    if analysis_remaining:
        # باقٍ من دفعة التحليل لم يُحاوَل بعد (نفس مبدأ cmd_revival، Issue
        # #961): الـIssue يبقى مفتوحًا وينتظر وسمًا جديدًا يعالج الباقي وحده.
        review.remove_label(issue_number, "approved")
    return 0


def cmd_revival(issue_number: int, body: str, cfg) -> int:
    """يعالج اعتماد Issue إحياء الفشل (Issue #959، وسم ``failed-review``،
    نصّه من ``review.build_revival_body``). المسار المستدعي (``main``) يحرس
    هذا فيشغّله في مسار normal (``--skip-urgent``) وحده — دفعة إحياء قد
    تضم مسودات تحليل، ونشرها (``youtube_publish.publish_ids``) بتباعده
    الخاص لا يحتمل سقف urgent الزمني (٢٠ دقيقة)، بنفس منطق تأجيل التحليل
    في المسار المعتاد (Issue #745).

    الحارس ``status == "failed" and revival_issue == issue_number`` (بعد
    استبعاد ``revival_declined`` سابقًا — إعادة تشغيل لهذا الـIssue بعينه لا
    تُعيد معالجة مسودة قُرِّر مصيرها فعلًا) يقصر المعالجة على مسودات هذا
    الـIssue وحده فيمنع الأثر المزدوج لو تكرر حدث الوسم (نفس الحارس في
    ``cmd_final_review``). معرّف بلا مسودة (حذفتها ``retention.py``) أو
    بمسودة لا تطابق الحارس يُتخطّى بسطر في التعليق، لا انهيارًا.

    مسودات تحليل معلَّمة قد تتجاوز سقف تشغيلة واحدة
    (``youtube.publish.max_per_run``، Issue #961): ``youtube_publish.publish_ids``
    يقتصر داخليًا على أول ``max_per_run`` معرّفًا ويعيد الباقي في ``remaining``
    بلا لمسها. مسودة خارج تلك الدفعة يجب ألا يُمسّ منها ``error``/``failed_stage``/
    ``revival_issue`` — تبقى تمامًا كما كانت (قابلة للعرض في تشغيلة إحياء لاحقة
    لنفس الـIssue) بدل أن تموت بصمت بلا وسم يعيدها. طالما بقي شيء من دفعة
    التحليل، الـIssue لا يُغلق ويُزال وسمه ليعيد المراجع وسمه لاحقًا فيعالج
    الباقي وحده (الحارس أعلاه يقصر كل تشغيلة تالية على ما لم يُحاوَل بعد)."""
    all_ids = review.all_revival_ids(body)
    approved_ids = set(review.parse_revival_ids(body))

    lines: list[str] = []
    matched: list[tuple] = []
    for draft_id in all_ids:
        found = store.load_draft(draft_id)
        if not found:
            lines.append(f"- ⏭️ `{draft_id}` — المسودة محذوفة (انتهت نافذة الاحتفاظ)")
            continue
        path, draft = found
        if (draft.get("status") != "failed"
                or draft.get("revival_issue") != issue_number
                or draft.get("revival_declined")):
            lines.append(f"- ⏭️ `{draft_id}` — غير مطابق (رُوجعت بالفعل)")
            continue
        if draft_id in approved_ids:
            matched.append((path, draft))
        else:
            store.update_draft(path, revival_declined=True)
            lines.append(f"- 🚫 {draft['arabic']['post_title'][:50]} — لم يُعلَّم، مات نهائيًا")

    analysis_remaining: list[str] = []
    if matched:
        analysis_rows = [(p, d) for p, d in matched if store.origin_of(d) == "analysis"]
        news_rows = [(p, d) for p, d in matched if store.origin_of(d) != "analysis"]

        if news_rows:
            # نفس دالة الفواصل ومفاتيح الإعداد اللتين يستعملهما مسار الاعتماد
            # العادي (cmd_burst) — بلا نشر فوري هنا: تبدأ بعد آخر منشور فعلي
            # وآخر موعد محجوز معًا (Issue #1010) حتى لا تتزاحم مع الطابور
            # القائم ولا مع دفعة أخرى نُشرت للتو من مسار مستقل تمامًا.
            fcfg = cfg.get("facebook", {}) or {}
            gap_min = float(fcfg.get("gap_min_minutes", 30))
            gap_max = float(fcfg.get("gap_max_minutes", 60))
            tzname = fcfg.get("timezone", "UTC")
            now = datetime.now(timezone.utc)
            last_pub = store.last_publish_at()
            booked = booked_times()
            start = now
            if last_pub is not None:
                start = max(start, last_pub + timedelta(minutes=gap_min))
            if booked:
                start = max(start, max(booked) + timedelta(minutes=gap_min))
            slots = spaced_slots(len(news_rows), gap_min, gap_max, now=start)
            for (path, draft), when in zip(news_rows, slots):
                store.update_draft(
                    path, status="queued", publish_at=when.isoformat(),
                    remove=["error", "failed_stage", "revival_issue"],
                )
                lines.append(f"- 🕐 {draft['arabic']['post_title'][:50]} → "
                             f"**{describe(when, tzname)}**")

        if analysis_rows:
            # نفس توجيه المعتمَد العادي لمسار التحليل (publish.main أدناه) —
            # لا منطق نشر جديد هنا: youtube_publish.publish_ids تنشر فورًا
            # (بسقفها وتباعدها الخاصّين)، لا queued/publish_at. الحقول الثلاثة
            # تُمسح فقط لمعرّفات الدفعة الفعلية (نفس تقطيع max_per_run الذي
            # تطبّقه publish_ids داخليًا — Issue #961) — مسودة تتجاوز سقف هذه
            # التشغيلة لا يُمسّ منها شيء، فتبقى قابلة للعرض إحياءً لاحقًا.
            from . import youtube_publish
            analysis_ids = [d["id"] for _, d in analysis_rows]
            max_per_run = int(cfg.path("youtube.publish.max_per_run", 3))
            batch_ids = set(analysis_ids[:max_per_run])
            for path, draft in analysis_rows:
                if draft["id"] in batch_ids:
                    store.update_draft(path, remove=["error", "failed_stage", "revival_issue"])
            yt_lines, _, _, analysis_remaining = youtube_publish.publish_ids(
                analysis_ids, {}, cfg)
            lines += yt_lines
            if analysis_remaining:
                by_id = {d["id"]: d for _, d in analysis_rows}
                for rid in analysis_remaining:
                    title = by_id[rid]["arabic"]["post_title"][:50]
                    lines.append(f"- ⏳ {title} — ينتظر تشغيلة لاحقة")
                lines.append("أعد وضع وسم `approved` لمتابعة الباقي")

    text = "### ♻️ نتيجة إحياء المنشورات الفاشلة\n" + "\n".join(lines)
    review.comment(issue_number, text)
    if analysis_remaining:
        # باقٍ من دفعة التحليل لم يُحاوَل بعد (Issue #961): الـIssue يبقى
        # مفتوحًا وينتظر وسمًا جديدًا يعالج الباقي وحده — إغلاقه هنا كان
        # يفقد المراجع أي أثر لبقية الدفعة (لا وسم approved قائم يعيد
        # تشغيلها، ولا Issue مفتوح يذكّر بها).
        review.remove_label(issue_number, "approved")
    else:
        review.close_issue(issue_number)
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

    # Issue #858، الجزء الثاني (+ Issue #1000 لمسار التحليل): Issue المراجعة
    # النهائية (وسم final-review) يُفتح إما من داخل هذه الدالة نفسها أدناه
    # (لمن عُلِّم عليه 🎴 في مسار الأخبار) أو من youtube_publish.publish_ids
    # (لمن عُلِّم عليه 🎴 في مسار التحليل -- عبر التوجيه بالأصل أدناه، أو عبر
    # publish_approved المستقلة عن main تمامًا). يميَّز بوسمه وحده -- لا
    # بمحتوى جسمه (يستعمل نفس صيغة <!-- draft:id --> المشتركة مع Issue
    # المراجعة الأولية لكلا المسارين). اعتماده لا يعيد بناء البطاقة ولا
    # يختار عنوانًا ولا يطبّق تعديل نص -- المسار العادي أدناه يفعل كل ذلك،
    # فيجب ألا يصله هذا النوع من الـIssues إطلاقًا؛ cmd_final_review نفسها
    # عامة بلا أي فحص origin، فتنشر مسودة تحليل عبر publish_one كأي مسودة
    # أخرى بلا استثناء.
    if "final-review" in labels:
        return cmd_final_review(args.issue, body, cfg)

    # Issue #959: Issue إحياء الفشل (وسم failed-review، يُفتح من
    # open_review._open_revival_issue) -- يعمل في المسار العادي وحده، بنفس
    # منطق تأجيل التحليل أدناه (Issue #745): دفعة إحياء قد تضم مسودات
    # تحليل، ونشرها بتباعده الخاص لا يحتمل سقف urgent الزمني.
    if "failed-review" in labels:
        if args.urgent_only:
            log.info("Issue #%s: failed-review — يُؤجَّل للمسار العادي "
                     "(المسار السريع لا يعالج الإحياء)", args.issue)
            return 0
        return cmd_revival(args.issue, body, cfg)

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

    # تطبيق تعديل النص اليدوي (Issue #752) — مباشرة بعد parse_approved وقبل
    # فصل analysis_ids/news_ids عمدًا: مسار التحليل يستبدل سطر العنوان في
    # caption عبر youtube_publish._apply_headline لاحقًا، فيجب أن يعمل على
    # النص المحرَّر لا الأصلي. المقارنة بعد توحيد نهايات الأسطر وقصّ الفراغ
    # الذيلي — لا فرق حقيقي في المحتوى لا يستحق تسجيل تعديل.
    captions = review.parse_captions(body)
    for draft_id in ids:
        edited = captions.get(draft_id)
        if edited is None:
            continue
        found = store.load_draft(draft_id)
        if not found:
            continue
        cap_path, cap_draft = found
        stored_norm = (cap_draft.get("caption") or "").replace("\r\n", "\n").rstrip()
        edited_norm = edited.replace("\r\n", "\n").rstrip()
        if edited_norm != stored_norm:
            store.update_draft(cap_path, caption=edited, caption_edited=True)
            log.info("نص المنشور %s عُدِّل يدويًا في الـ Issue", draft_id)

    # اختيار العنوان (Issue #756) -- بعد تطبيق تعديل النص اليدوي مباشرة
    # (ترتيب ملزم: لو حرّر المراجع النص وعلّم عنوانًا معًا، يُطبَّق التحرير
    # أولًا فيستبدل العنوان المختار سطره الأول من النص المحرَّر لا الأصلي)،
    # ولمسودات الأخبار وحدها -- مسار التحليل له تطبيقه الخاص عبر
    # youtube_publish.ensure_title_card/_apply_headline (يقرأ نفس
    # parse_headline_choice، لكن بعد التوجيه بالأصل أدناه لا هنا).
    headline_choices = review.parse_headline_choice(body)
    for draft_id, chosen_idx in headline_choices.items():
        if draft_id not in ids:
            continue
        found = store.load_draft(draft_id)
        if not found:
            continue
        hl_path, hl_draft = found
        if store.origin_of(hl_draft) == "analysis":
            continue
        headlines = hl_draft.get("headlines") or []
        if not (0 <= chosen_idx < len(headlines)):
            continue
        headline = headlines[chosen_idx]
        cap_lines = (hl_draft.get("caption") or "").splitlines()
        if not cap_lines:
            continue
        cap_lines[0] = headline
        new_caption = "\n".join(cap_lines)
        new_arabic = {**(hl_draft.get("arabic") or {}), "post_title": headline}
        hl_draft = store.update_draft(hl_path, caption=new_caption, arabic=new_arabic,
                                       headline_selected=chosen_idx)
        log.info("عنوان المنشور %s استُبدل بالعنوان المختار (%d)", draft_id, chosen_idx)

    # بناء البطاقة (Issue #852، الجزء الأول): البطاقة لم تُبنَ عند الجمع
    # بعد الآن لأيّ مسار أخبار — تُبنى هنا فقط، بعد اختيار العنوان مباشرة
    # (الترتيب ملزم: العنوان الذي اختير للتوّ أعلاه هو ما يصل البطاقة، وإلا
    # حملت عنوانًا قديمًا). مسار التحليل مستثنى (له بناؤه الخاص عبر
    # ensure_title_card بعد التوجيه بالأصل أدناه). فشل البناء لا يُسقط
    # المسودة صامتًا: تبقى pending بلا لمس (card_build_failed تستبعدها من
    # news_ids أدناه فلا يحاول publish_one نشرها أصلًا)، ويُكتب تعليق على
    # الـIssue باسمها وسببها — منشور معتمَد يختفي بلا أثر أسوأ من منشور
    # يتأخر.
    card_build_failed: set[str] = set()
    card_failure_lines: list[str] = []
    for draft_id in ids:
        found = store.load_draft(draft_id)
        if not found:
            continue
        card_path, card_draft = found
        if store.origin_of(card_draft) == "analysis":
            continue
        headlines = card_draft.get("headlines") or []
        chosen_idx = headline_choices.get(draft_id, 0)
        chosen_headline = (headlines[chosen_idx]
                           if 0 <= chosen_idx < len(headlines) else None)
        # search_term (Issue #941): مسار article.py يحمل image_query_en
        # (كلمات إنجليزية لبحث صورة تعبيرية) على حقل علوي في المسودة --
        # غيابه (مسارات أخرى، أو فشل النداء) يعيد cards.ensure لاعتماد
        # source.title/العنوان العربي كما كانت الحال قبل هذه المهمة.
        if cards.ensure(card_path, card_draft, cfg, headline=chosen_headline,
                        search_term=card_draft.get("image_query_en")) is not None:
            continue
        card_build_failed.add(draft_id)
        title = (card_draft.get("arabic") or {}).get("post_title", draft_id)
        card_failure_lines.append(f"- ⚠️ **{title}** — تعذّر بناء البطاقة، بقيت المسودة معلَّقة")
        log.warning("تعذّر بناء بطاقة %s عند الاعتماد — تُترك pending", draft_id)
    if card_failure_lines:
        review.comment(
            args.issue,
            "### 🖼️ فشل بناء بعض البطاقات\n" + "\n".join(card_failure_lines) +
            "\n\nراجع الروابط ثم أعد وسم `approved`، أو استعمل مربع الصورة "
            "اليدوية.",
        )

    reels = review.parse_reels(body)

    # عدم الاعتماد = رفض ضمني (Issue #841، البند 2): لا خيارات سبب استبعاد
    # في الواجهة بعد اليوم، فكل معرّف ظهر في هذا الـIssue
    # (review.all_draft_ids) ولم يُعلَّم ✔️ يُعامَل كأنه رُفض صراحة — السبب
    # الحقيقي يُسأل عنه لاحقًا في التقرير الأسبوعي (البند 3، غير مبني بعد).
    # النطاق مقيَّد بمعرّفات هذا الـIssue وحده، فلا تُمسّ مسودة معلَّقة
    # خارجه؛ ومسار التحليل لا يُستثنى — عدم الاعتماد رفض في كل المسارات.
    # status == "pending" يمنع إعادة الرفض/التسجيل عند إعادة تشغيل هذا
    # المسار لنفس الـIssue (مثلًا مسار urgent ثم normal لنفس حدث approved).
    unapproved = [i for i in review.all_draft_ids(body) if i not in ids]
    if unapproved:
        entries = feedback.load()
        rejected_now = 0
        for draft_id in unapproved:
            found = store.load_draft(draft_id)
            if not found or found[1].get("status") != "pending":
                continue
            store.update_draft(found[0], status="rejected")
            feedback.record(entries, found[1], tag="لم يُعتمد", note="")
            decisions.record_rejected_unchecked(found[1])
            rejected_now += 1
        if rejected_now:
            feedback.save(entries)
            log.info("الـIssue #%s: %d مسودة لم تُعتمد — سُجّلت مرفوضة",
                     args.issue, rejected_now)

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
        if draft_id in card_build_failed:
            # تُركت pending أعلاه (فشل بناء البطاقة، Issue #852) — لا تصل
            # publish_one أصلًا، وإلا سجّلها failed بحقل image مفقود، وهذا
            # بالضبط ما نتجنّبه: منشور معتمَد يختفي بلا أثر أسوأ من منشور
            # يتأخر.
            continue
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
            analysis_ids, youtube_publish.parse_headline_choice(body), cfg,
            body=body, issue_number=args.issue)
        youtube_publish.report_batch(
            args.issue, yt_lines, yt_published, yt_attempted, yt_remaining, cfg)

    if not news_ids:
        return 0

    # Issue #858، الجزء الثاني: معتمَد مع 🎴 لا يُنشر هنا -- بطاقته مبنيّة
    # فعلًا أعلاه (cards.ensure)، لكنه يُجمَّع بدل ذلك في Issue مراجعة نهائية
    # منفصل يعرضها للمراجع قبل النشر الفعلي (يبقى pending حتى ذلك الاعتماد).
    # نفس نمط حراسة urgent/skip الذي يؤجّل توجيه التحليل أعلاه (Issue #745):
    # المسار السريع لا يفتح Issues مراجعة جديدة، فيُترَك هذا التجميع للمسار
    # العادي فقط -- المسودة تبقى pending فيلتقطها ذلك التشغيل التالي.
    card_requests = review.parse_card_requests(body) & set(news_ids)
    if card_requests:
        news_ids = [i for i in news_ids if i not in card_requests]
        if args.urgent_only:
            log.info("Issue #%s: %d منشور مع 🎴 — يُؤجَّل فتح المراجعة "
                     "النهائية للمسار العادي (المسار السريع لا يفتحها)",
                     args.issue, len(card_requests))
        else:
            open_final_review(args.issue, list(card_requests), cfg)

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
