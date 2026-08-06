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
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from . import facebook, review, store
from .config import STATE_DIR, load_config
from .schedule import tz_of

log = logging.getLogger("insights")

PERF_FILE = STATE_DIR / "performance.json"


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
        "bottom": sorted(rows, key=lambda r: r["engagement"])[:3],
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


def recommendations(a: dict, cfg) -> list[str]:
    """يحوّل الأرقام إلى تعديلات ملموسة في config.yaml."""
    out: list[str] = []
    if a["count"] < 10:
        out.append(
            f"البيانات قليلة ({a['count']} منشور). التوصيات تصبح موثوقة بعد 20 منشورًا."
        )

    t_avg, t_n, n_avg, n_n = a["trend"]
    if t_n >= 3 and n_n >= 3:
        weight = float(cfg.path("trends.weight", 4.0))
        if t_avg > n_avg * 1.25:
            out.append(
                f"الأخبار الرائجة 🔥 تتفوق ({t_avg:.0f} مقابل {n_avg:.0f}). "
                f"ارفع `trends.weight` من {weight} إلى {min(weight + 2, 10):.0f}."
            )
        elif n_avg > t_avg * 1.25:
            out.append(
                f"الأخبار الرائجة تتأخر ({t_avg:.0f} مقابل {n_avg:.0f}). "
                f"اخفض `trends.weight` من {weight} إلى {max(weight - 2, 0):.0f}."
            )
        else:
            out.append("إشارة الترند متعادلة مع التغطية — اترك `trends.weight` كما هو.")

    if len(a["categories"]) >= 3:
        best = a["categories"][0]
        worst = a["categories"][-1]
        if best[2] >= 2 and worst[2] >= 2 and best[1] > worst[1] * 1.5:
            out.append(
                f"تصنيف «{best[0]}» يتفوق ({best[1]:.0f}) و«{worst[0]}» يتراجع "
                f"({worst[1]:.0f}). فكّر في زيادة مصادر الأول."
            )

    if a["hours"]:
        top_hours = [h for h, _, _ in a["hours"][:3]]
        current = cfg.path("facebook.peak_hours", [])
        if sorted(top_hours) != sorted(current[: len(top_hours)]):
            out.append(
                f"أفضل ساعات التفاعل فعليًا: {', '.join(map(str, top_hours))}. "
                f"الإعداد الحالي: {current}. حدّث `facebook.peak_hours`."
            )

    p_avg, p_n, np_avg, np_n = a["photo"]
    if p_n >= 3 and np_n >= 3 and p_avg > np_avg * 1.3:
        out.append(
            f"المنشورات بصورة خبر حقيقية تتفوق ({p_avg:.0f} مقابل {np_avg:.0f}). "
            "احذف المصادر التي لا توفّر صورًا."
        )

    if a["publishers"]:
        best_pub = a["publishers"][0]
        out.append(
            f"أفضل مصدر أداءً: {best_pub[0]} ({best_pub[1]:.0f} تفاعل، "
            f"{best_pub[2]} منشور). ارفع وزنه في `sources`."
        )

    return out or ["لا توصيات واضحة بعد — واصل النشر وأعد التقرير لاحقًا."]


def build_report(a: dict, recs: list[str], days: int) -> str:
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
    lines += [f"- {r}" for r in recs]

    from .feedback import load as load_rejections, summarise
    patterns = summarise(load_rejections(), days=min(days, 14))
    if patterns:
        lines += ["", "#### 🚫 أنماط الرفض", ""] + patterns
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
    report = build_report(a, recommendations(a, cfg), args.days)
    print(report)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report + "\n")

    if not args.no_issue and os.environ.get("GITHUB_REPOSITORY"):
        review.create_issue(
            title=f"📊 تقرير الأداء {datetime.now(timezone.utc):%Y-%m-%d}",
            body=report,
            labels=[],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
