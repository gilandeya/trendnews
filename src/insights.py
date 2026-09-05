"""يجمع أداء المنشورات من فيسبوك ويحوّله إلى توصيات قابلة للتطبيق.

    python -m src.insights            # تقرير عن آخر 30 يومًا
    python -m src.insights --days 7

الفكرة: البوت يرتّب الأخبار بأوزان خمّناها أنا وأنت. بعد عشرات المنشورات
تصبح لديك بيانات حقيقية عن جمهورك — أي تصنيف يتفاعل معه، أي مصدر يأتي
بأفضل الأخبار، وهل إشارة Google Trends تستحق وزنها. هذا التقرير يحوّل
تلك البيانات إلى أرقام تضبط بها config.yaml.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from . import facebook, review, store
from .config import STATE_DIR, load_config
from .schedule import tz_of

log = logging.getLogger("insights")

PERF_FILE = STATE_DIR / "performance.json"
LAST_ISSUE_FILE = STATE_DIR / "insights_last_issue.json"
DECISIONS_FILE = STATE_DIR / "insight_decisions.json"

# ثمانية أسابيع — قيمة ثابتة في الكود لا في config.yaml عمدًا (Issue #769
# يمنع لمس config.yaml هنا صراحة، وهذه ليست قيمة تضبط الفرز أو الترتيب أو
# النشر كبقية ما في ذلك الملف، بل مدة إخفاء مقترح رفضه المستخدم في تقرير
# الأداء نفسه).
REJECT_SUPPRESS_DAYS = 56


def engagement(metrics: dict) -> int:
    """تفاعل مركّب: المشاركة أثقل من التعليق، والتعليق أثقل من الإعجاب."""
    return (
        metrics.get("reactions", 0)
        + metrics.get("comments", 0) * 3
        + metrics.get("shares", 0) * 5
    )


def collect(days: int, api_version: str) -> list[dict]:
    """يجلب مقاييس كل منشور نُشر خلال المدة."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows: list[dict] = []

    for path in sorted(store.DRAFTS_DIR.glob("*/*.json")):
        try:
            draft = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if draft.get("status") != "published":
            continue
        published_at = draft.get("published_at")
        if not published_at:
            continue
        try:
            when = datetime.fromisoformat(published_at)
        except ValueError:
            continue
        if when < cutoff:
            continue

        post_id = (draft.get("facebook") or {}).get("post_id")
        if not post_id:
            continue

        metrics = facebook.fetch_metrics(post_id, api_version)
        if metrics.get("error"):
            continue

        rows.append({
            "id": draft["id"],
            "title": draft["arabic"]["post_title"],
            "category": draft["arabic"].get("category", "؟"),
            "urgent": bool(draft["arabic"].get("urgent")),
            "trend_score": float(draft.get("trend_score", 0)),
            "state_media": bool(draft.get("state_media")),
            "publishers": (draft.get("source") or {}).get("publishers", []),
            "published_at": published_at,
            "has_photo": bool((draft.get("source") or {}).get("image_url")),
            **metrics,
            "engagement": engagement(metrics),
        })

    log.info("جُمعت مقاييس %d منشور", len(rows))
    return rows


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def analyse(rows: list[dict], timezone_name: str) -> dict:
    """يقسّم الأداء حسب التصنيف والمصدر والترند وساعة النشر."""
    if not rows:
        return {}

    overall = _avg([r["engagement"] for r in rows])
    tz = tz_of(timezone_name)

    by_category: dict[str, list[int]] = defaultdict(list)
    by_hour: dict[int, list[int]] = defaultdict(list)
    by_publisher: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        by_category[r["category"]].append(r["engagement"])
        by_publisher_keys = r["publishers"][:2] or ["؟"]
        for pub in by_publisher_keys:
            by_publisher[pub].append(r["engagement"])
        try:
            hour = datetime.fromisoformat(r["published_at"]).astimezone(tz).hour
            by_hour[hour].append(r["engagement"])
        except ValueError:
            pass

    trending = [r["engagement"] for r in rows if r["trend_score"] >= 0.5]
    not_trending = [r["engagement"] for r in rows if r["trend_score"] < 0.5]
    urgent = [r["engagement"] for r in rows if r["urgent"]]
    calm = [r["engagement"] for r in rows if not r["urgent"]]
    photo = [r["engagement"] for r in rows if r["has_photo"]]
    no_photo = [r["engagement"] for r in rows if not r["has_photo"]]

    return {
        "count": len(rows),
        "overall_avg": overall,
        "median": median([r["engagement"] for r in rows]),
        "top": sorted(rows, key=lambda r: -r["engagement"])[:5],
        # أدنى خمسة تفاعلًا — نظير "top" أعلاه (Issue #769، قسم "📉 أضعف
        # أداءً"). الترتيب تصاعدي فالأضعف فعليًا يتصدّر لا يذيّل.
        "bottom": sorted(rows, key=lambda r: r["engagement"])[:5],
        "categories": sorted(
            ((k, _avg(v), len(v)) for k, v in by_category.items()),
            key=lambda t: -t[1],
        ),
        "hours": sorted(
            ((k, _avg(v), len(v)) for k, v in by_hour.items() if len(v) >= 2),
            key=lambda t: -t[1],
        ),
        "publishers": sorted(
            ((k, _avg(v), len(v)) for k, v in by_publisher.items() if len(v) >= 2),
            key=lambda t: -t[1],
        )[:8],
        "trend": (_avg(trending), len(trending), _avg(not_trending), len(not_trending)),
        "urgent": (_avg(urgent), len(urgent), _avg(calm), len(calm)),
        "photo": (_avg(photo), len(photo), _avg(no_photo), len(no_photo)),
    }


def _fingerprint(text: str) -> str:
    """بصمة مستقرة لنص مقترح بلا key (Issue #769) — تُجرَّد الأرقام أولًا
    كي لا يتغيّر المعرّف لمجرد أن متوسطًا تحرّك من 42 إلى 45؛ فقط تغيّر
    الكلمات نفسها (تصنيف مختلف مثلًا) يُنتج بصمة مختلفة، وهذا مقصود."""
    stripped = re.sub(r"\d+", "", text)
    return hashlib.sha1(stripped.encode("utf-8")).hexdigest()[:12]


def _rec(text: str, key: str | None = None, current=None, suggested=None) -> dict:
    """يبني مقترحًا كخيار (قبول/رفض) لا نصًّا فقط (Issue #769). id ثابت
    عبر الأسابيع: من key إن وُجد (تعديل إعداد فعلي)، وإلا من بصمة النص —
    شرط عمل الحلقة المغلقة في state/insight_decisions.json بالكامل."""
    rec_id = key if key else f"fp_{_fingerprint(text)}"
    return {"id": rec_id, "text": text, "key": key, "current": current, "suggested": suggested}


def recommendations(a: dict, cfg) -> list[dict]:
    """يحوّل الأرقام إلى تعديلات ملموسة في config.yaml — كخيارات (Issue
    #769)، لا كنصوص فقط: كل مقترح قابل للقبول أو الرفض في تقرير الأداء،
    ومقترحه key/current/suggested (حين تقابله قيمة إعداد فعلية) يُتيح
    تتبّع تطبيقه لاحقًا. القبول لا يعدّل config.yaml تلقائيًا (قرار محسوم،
    انظر توثيق src/insights.py الأعلى) — التقرير يذكّر فقط."""
    out: list[dict] = []
    if a["count"] < 10:
        out.append(_rec(
            f"البيانات قليلة ({a['count']} منشور). التوصيات تصبح موثوقة بعد 20 منشورًا."
        ))

    t_avg, t_n, n_avg, n_n = a["trend"]
    if t_n >= 3 and n_n >= 3:
        weight = float(cfg.path("trends.weight", 4.0))
        if t_avg > n_avg * 1.25:
            suggested = min(weight + 2, 10)
            out.append(_rec(
                f"الأخبار الرائجة 🔥 تتفوق ({t_avg:.0f} مقابل {n_avg:.0f}). "
                f"ارفع `trends.weight` من {weight} إلى {suggested:.0f}.",
                key="trends.weight", current=weight, suggested=suggested,
            ))
        elif n_avg > t_avg * 1.25:
            suggested = max(weight - 2, 0)
            out.append(_rec(
                f"الأخبار الرائجة تتأخر ({t_avg:.0f} مقابل {n_avg:.0f}). "
                f"اخفض `trends.weight` من {weight} إلى {suggested:.0f}.",
                key="trends.weight", current=weight, suggested=suggested,
            ))
        else:
            out.append(_rec("إشارة الترند متعادلة مع التغطية — اترك `trends.weight` كما هو."))

    if len(a["categories"]) >= 3:
        best = a["categories"][0]
        worst = a["categories"][-1]
        if best[2] >= 2 and worst[2] >= 2 and best[1] > worst[1] * 1.5:
            out.append(_rec(
                f"تصنيف «{best[0]}» يتفوق ({best[1]:.0f}) و«{worst[0]}» يتراجع "
                f"({worst[1]:.0f}). فكّر في زيادة مصادر الأول."
            ))

    if a["hours"]:
        top_hours = [h for h, _, _ in a["hours"][:3]]
        current = cfg.path("facebook.peak_hours", [])
        if sorted(top_hours) != sorted(current[: len(top_hours)]):
            out.append(_rec(
                f"أفضل ساعات التفاعل فعليًا: {', '.join(map(str, top_hours))}. "
                f"الإعداد الحالي: {current}. حدّث `facebook.peak_hours`.",
                key="facebook.peak_hours", current=current, suggested=sorted(top_hours),
            ))

    p_avg, p_n, np_avg, np_n = a["photo"]
    if p_n >= 3 and np_n >= 3 and p_avg > np_avg * 1.3:
        out.append(_rec(
            f"المنشورات بصورة خبر حقيقية تتفوق ({p_avg:.0f} مقابل {np_avg:.0f}). "
            "احذف المصادر التي لا توفّر صورًا."
        ))

    if a["publishers"]:
        best_pub = a["publishers"][0]
        out.append(_rec(
            f"أفضل مصدر أداءً: {best_pub[0]} ({best_pub[1]:.0f} تفاعل، "
            f"{best_pub[2]} منشور). ارفع وزنه في `sources`."
        ))

    return out or [_rec("لا توصيات واضحة بعد — واصل النشر وأعد التقرير لاحقًا.")]


# ──────────────────────── المقترحات كخيارات: قبول/رفض ────────────────────────

# مربعا قبول/رفض لكل مقترح: <!-- rec:المعرّف:yes --> / <!-- rec:المعرّف:no -->
# (Issue #769) — بنفس نمط علامات review.py (draft:/hl:/rj:).
REC_MARKER_RE = re.compile(
    r"^\s*-\s*\[([ xX])\]\s*.*?<!--\s*rec:([\w.\-]+):(yes|no)\s*-->", re.MULTILINE)


def parse_recommendation_choices(body: str) -> dict[str, str]:
    """يقرأ قرار المراجع (قبول/رفض) على مقترحات تقرير الأداء — بنفس أسلوب
    review.parse_headline_choice: معرّف المقترح ← "yes"/"no" لآخر مربع
    معلَّم في ترتيب الظهور (تسامح مع تعليم الاثنين خطأ)؛ مقترح لم يُعلَّم
    على أيّ من مربعيه لا يظهر في القاموس المُعاد إطلاقًا — يُتجاهل لا
    يُرفض ولا يُقبل."""
    chosen: dict[str, str] = {}
    for mark, rec_id, choice in REC_MARKER_RE.findall(body or ""):
        if mark.lower() == "x":
            chosen[rec_id] = choice
    return chosen


def _values_equal(current, suggested) -> bool:
    """مقارنة تتجاهل ترتيب القوائم (مثل facebook.peak_hours) — المستخدم
    قد يكتب الساعات بترتيب مختلف عن ترتيب الاقتراح ويبقى التطبيق فعليًا."""
    if isinstance(current, list) and isinstance(suggested, list):
        return sorted(current) == sorted(suggested)
    return current == suggested


# ──────────────────────── الحلقة المغلقة: حفظ وقراءة قراراتك ────────────────────────


def _load_last_issue() -> dict | None:
    if not LAST_ISSUE_FILE.exists():
        return None
    try:
        return json.loads(LAST_ISSUE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("ملف آخر Issue تقرير تالف — سيُتجاهل")
        return None


def _save_last_issue(issue_number: int, recs: list[dict]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "issue": issue_number,
        "recommendations": [
            {"id": r["id"], "text": r["text"], "key": r.get("key"),
             "suggested": r.get("suggested")}
            for r in recs
        ],
    }
    LAST_ISSUE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_decisions() -> dict:
    if not DECISIONS_FILE.exists():
        return {}
    try:
        return json.loads(DECISIONS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("ملف قرارات التوصيات تالف — سيُعاد إنشاؤه")
        return {}


def _save_decisions(decisions: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    DECISIONS_FILE.write_text(
        json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")


def sync_previous_decisions() -> None:
    """يُستدعى في بداية كل تشغيلة (Issue #769، الحلقة المغلقة): يقرأ نص
    Issue تقرير الأسبوع الماضي (معرّفه في state/insights_last_issue.json)،
    يحلّل مربعات القبول/الرفض، ويحفظ القرارات في state/insight_decisions.json
    مع تاريخها. أول تشغيلة بعد هذا التغيير لا تجد insights_last_issue.json
    فتتخطّى الخطوة بصمت؛ وأي عطل شبكة أو JSON تالف هنا لا يُسقط التشغيلة
    كلها — قراراتك ثانوية أمام التقرير نفسه، لا شرط لتوليده."""
    last = _load_last_issue()
    if not last:
        return
    try:
        issue_number = last["issue"]
        meta_by_id = {r["id"]: r for r in last.get("recommendations", [])}
    except (KeyError, TypeError):
        return

    try:
        body = review.fetch_issue_body(issue_number)
    except Exception as exc:  # noqa: BLE001 — عطل شبكة هنا لا يُسقط التشغيلة
        log.warning("تعذّر قراءة Issue #%s لتحليل قراراتك: %s", issue_number, exc)
        return

    choices = parse_recommendation_choices(body)
    if not choices:
        return

    decisions = _load_decisions()
    now = datetime.now(timezone.utc).isoformat()
    for rec_id, choice in choices.items():
        meta = meta_by_id.get(rec_id)
        if not meta:
            continue
        decision = "accepted" if choice == "yes" else "rejected"
        existing = decisions.get(rec_id)
        if existing and existing.get("decision") == decision:
            # نفس القرار السابق حرفيًا — لا تُحدَّث decided_at: نفس Issue قد
            # يُقرأ أكثر من مرة قبل أن يفتح تقرير جديد (لا مسودات هذا
            # الأسبوع مثلًا)، وتحديث التاريخ في كل قراءة كان سيمدّد نافذة
            # الثمانية أسابيع بلا نهاية طالما لم يتغيّر شيء فعليًا.
            continue
        decisions[rec_id] = {
            "id": rec_id,
            "text": meta.get("text", ""),
            "key": meta.get("key"),
            "suggested": meta.get("suggested"),
            "decision": decision,
            "decided_at": now,
            "reported": False,
        }
    _save_decisions(decisions)


def suppressed_ids(decisions: dict) -> set[str]:
    """معرّفات مقترحات رُفضت خلال آخر REJECT_SUPPRESS_DAYS يومًا — تُستبعد
    من recommendations() القادمة. رفضك إشارة، وتكرار عرض المرفوض عليك
    أسبوعيًا يجعلك تتوقف عن قراءة القسم كله."""
    now = datetime.now(timezone.utc)
    out = set()
    for rec_id, e in decisions.items():
        if e.get("decision") != "rejected":
            continue
        try:
            decided_at = datetime.fromisoformat(e["decided_at"])
        except (KeyError, ValueError):
            continue
        if (now - decided_at).days < REJECT_SUPPRESS_DAYS:
            out.add(rec_id)
    return out


def decisions_report(cfg) -> list[str]:
    """يبني قسم «📋 قراراتك السابقة» ويحدّث state/insight_decisions.json في
    الوقت نفسه (Issue #769): مقترح بلا key يُعرض مرة واحدة (قبول أو رفض
    مرفوض) فلا يتكرر بعدها — رفض مُعاد كل أسبوع نصًّا يفقد فائدته كإشارة؛
    مقترح مقبول وله key يُقارَن بقيمة الإعداد الحالية كل أسبوع حتى يُطبَّق
    فيُعرض ✅ ويُحذف من التتبّع، وقبلها يُعرض ⏳ في كل تقرير. مقترح مرفوض
    منتهي نافذة الإخفاء يُحذف من الملف؛ سقوطه من هنا هو ما يُتيح ظهوره
    مجددًا في recommendations() القادمة (انظر suppressed_ids)."""
    decisions = _load_decisions()
    if not decisions:
        return []

    now = datetime.now(timezone.utc)
    lines: list[str] = []
    remaining: dict = {}

    for rec_id, e in decisions.items():
        if e.get("decision") == "accepted" and e.get("key"):
            current = cfg.path(e["key"])
            if _values_equal(current, e.get("suggested")):
                lines.append(f"- ✅ طُبّقت: `{e['key']}` أصبحت {current}")
                continue  # طُبّقت فعلًا — لا حاجة لتتبّعها بعد الآن
            lines.append(
                f"- ⏳ قبلتَها ولم تُطبَّق بعد: `{e['key']}` ما زال {current}")
            remaining[rec_id] = e
            continue

        if e.get("decision") == "accepted":
            # بلا key: لا شيء لتتبّعه — يُعرض مرة ثم يسقط من الملف كليًا
            if not e.get("reported"):
                lines.append(f"- ✅ قبلتَ: {e['text']}")
            continue

        try:
            decided_at = datetime.fromisoformat(e["decided_at"])
        except (KeyError, ValueError):
            continue
        if (now - decided_at).days >= REJECT_SUPPRESS_DAYS:
            continue  # انتهت نافذة الإخفاء

        if not e.get("reported"):
            lines.append(f"- ❌ رفضتَ: {e['text']}")
            e = {**e, "reported": True}
        remaining[rec_id] = e

    _save_decisions(remaining)
    if not lines:
        return []
    return ["", "#### 📋 قراراتك السابقة", ""] + lines


def rejections_section(entries: list[dict], days: int, limit: int = 40) -> list[str]:
    """قائمة كاملة بما رُفض ضمن نافذة التقرير (Issue #769) — العنوان، سبب
    الرفض (tag+note)، المسار (origin)، والتاريخ. تفصيل يكمل «أنماط الرفض»
    الذي يلخّص فقط أعلاه، وكلاهما مطلوب معًا. مطوية داخل <details> كي لا
    يتضخّم نص الـIssue، وبسقف `limit` يليه سطر «و N أخرى» عند التجاوز."""
    from .feedback import REASONS

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = [e for e in entries if datetime.fromisoformat(e["at"]) >= cutoff]
    if not recent:
        return []

    recent = sorted(recent, key=lambda e: e["at"], reverse=True)
    shown, extra = recent[:limit], recent[limit:]

    lines = [
        "", "#### 🚫 ما رُفض", "",
        f"<details><summary>{len(recent)} مسودة مرفوضة خلال {days} يومًا "
        "— التفاصيل</summary>",
        "",
    ]
    for e in shown:
        reason = REASONS.get(e["tag"], e["tag"])
        note = f" — {e['note']}" if e.get("note") else ""
        origin = e.get("origin") or "؟"
        date = e["at"][:10]
        title = e.get("title") or e.get("source_title") or "(بلا عنوان)"
        lines.append(f"- **{title}** — {reason}{note} · المسار: `{origin}` · {date}")
    if extra:
        lines.append(f"- و {len(extra)} أخرى")
    lines += ["", "</details>"]
    return lines


def build_report(a: dict, recs: list[dict], days: int,
                  decisions_lines: list[str] | None = None) -> str:
    if not a:
        return f"### 📊 لا منشورات خلال آخر {days} يومًا"

    lines = [
        f"### 📊 تقرير الأداء — آخر {days} يومًا",
        "",
        f"**{a['count']} منشور** · متوسط التفاعل **{a['overall_avg']:.0f}** "
        f"· الوسيط {a['median']:.0f}",
        "",
        "<sub>التفاعل = إعجاب + (تعليق × 3) + (مشاركة × 5)</sub>",
        "",
        "#### 🏆 الأفضل أداءً",
        "| التفاعل | التصنيف | العنوان |",
        "|---|---|---|",
    ]
    lines += [f"| {r['engagement']} | {r['category']} | {r['title'][:60]} |"
              for r in a["top"]]

    lines += ["", "#### 📉 أضعف أداءً", "| التفاعل | التصنيف | العنوان |", "|---|---|---|"]
    lines += [f"| {r['engagement']} | {r['category']} | {r['title'][:60]} |"
              for r in a["bottom"]]

    lines += ["", "#### 📂 حسب التصنيف", "| التصنيف | متوسط التفاعل | عدد |", "|---|---|---|"]
    lines += [f"| {c} | {v:.0f} | {n} |" for c, v, n in a["categories"]]

    if a["hours"]:
        lines += ["", "#### 🕐 حسب ساعة النشر", "| الساعة | متوسط التفاعل | عدد |",
                  "|---|---|---|"]
        lines += [f"| {h}:00 | {v:.0f} | {n} |" for h, v, n in a["hours"]]

    if a["publishers"]:
        lines += ["", "#### 📰 حسب المصدر", "| المصدر | متوسط التفاعل | عدد |",
                  "|---|---|---|"]
        lines += [f"| {p} | {v:.0f} | {n} |" for p, v, n in a["publishers"]]

    t_avg, t_n, n_avg, n_n = a["trend"]
    u_avg, u_n, c_avg, c_n = a["urgent"]
    lines += [
        "", "#### 🔬 مقارنات",
        "| المقارنة | متوسط | مقابل | متوسط |",
        "|---|---|---|---|",
        f"| رائج 🔥 ({t_n}) | {t_avg:.0f} | غير رائج ({n_n}) | {n_avg:.0f} |",
        f"| عاجل ({u_n}) | {u_avg:.0f} | عادي ({c_n}) | {c_avg:.0f} |",
        "", "#### 💡 توصيات", "",
    ]
    for r in recs:
        lines.append(f"- {r['text']}")
        lines.append(f"  - [ ] ✅ أقبل  <!-- rec:{r['id']}:yes -->")
        lines.append(f"  - [ ] ❌ أرفض  <!-- rec:{r['id']}:no -->")
        lines.append("")

    if decisions_lines:
        lines += decisions_lines

    from .feedback import load as load_rejections, summarise
    entries = load_rejections()
    patterns = summarise(entries, days=min(days, 14))
    if patterns:
        lines += ["", "#### 🚫 أنماط الرفض", ""] + patterns
    lines += rejections_section(entries, days)

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="تقرير أداء المنشورات")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--no-issue", action="store_true", help="اطبع فقط بلا Issue")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")
    cfg = load_config()
    api_version = cfg.path("facebook.api_version", "v21.0")
    tzname = cfg.path("facebook.timezone", "UTC")

    # الحلقة المغلقة (Issue #769) — تُقرأ في بداية كل تشغيلة بصرف النظر عن
    # وجود مسودات هذه المرة، لأن قراراتك على تقرير الأسبوع الماضي مستقلة
    # عمّا يُجمَع اليوم.
    sync_previous_decisions()

    rows = collect(args.days, api_version)
    if not rows:
        log.warning("لا منشورات لتحليلها")
        return 0

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PERF_FILE.write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                    "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    a = analyse(rows, tzname)
    recs = recommendations(a, cfg)
    hidden = suppressed_ids(_load_decisions())
    visible_recs = [r for r in recs if r["id"] not in hidden]

    report = build_report(a, visible_recs, args.days, decisions_report(cfg))
    print(report)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report + "\n")

    if not args.no_issue and os.environ.get("GITHUB_REPOSITORY"):
        issue = review.create_issue(
            title=f"📊 تقرير الأداء {datetime.now(timezone.utc):%Y-%m-%d}",
            body=report,
            labels=[],
        )
        _save_last_issue(issue["number"], visible_recs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
