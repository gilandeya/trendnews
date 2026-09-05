"""رادار العاجل: يلتقط الأخبار المتسارعة خارج الدورة المجدولة.

يعمل كل ربع ساعة على مصادر مختارة. الفحص نفسه **مجاني تمامًا** — قراءة
RSS وحساب السرعة لا يستدعيان أي نموذج. التكلفة تقع فقط عند العثور على
خبر يستحق، فيُصاغ ويُنشر أو يُعرض للمراجعة.

    python -m src.radar            # فحص عادي
    python -m src.radar --dry-run  # فحص بلا صياغة (مجاني تمامًا)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import merge, preselect, review, store
from .config import ROOT, STATE_DIR, load_config
from .extract import gather as gather_texts
from .imagesearch import find_images
from .imaging import build_post_image
from .rank import rank
from .screen import screen
from .sources import enrich_image, fetch_all
from .velocity import load as load_velocity, save as save_velocity
from .writer import WriteFailure, build_caption, usage_summary, write_arabic

log = logging.getLogger("radar")

RADAR_STATE = STATE_DIR / "radar.json"


# ──────────────────────────── حدّ يومي ────────────────────────────


def _load_state() -> dict:
    if not RADAR_STATE.exists():
        return {"auto_published": []}
    try:
        return json.loads(RADAR_STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"auto_published": []}


def _save_state(state: dict) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    state["auto_published"] = [
        t for t in state.get("auto_published", [])
        if datetime.fromisoformat(t) >= cutoff
    ]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    RADAR_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                           encoding="utf-8")


def auto_published_today(state: dict) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    return sum(1 for t in state.get("auto_published", [])
               if datetime.fromisoformat(t) >= cutoff)


# ──────────────────────────── الفحص ────────────────────────────


def radar_sources(cfg) -> list[dict]:
    """مصادر الرادار: الموسومة صراحةً، وإلا الأعلى وزنًا."""
    all_sources = cfg.get("sources", []) or []
    marked = [s for s in all_sources if s.get("radar")]
    if marked:
        return marked
    limit = int(cfg.path("radar.max_sources", 25))
    return sorted(all_sources, key=lambda s: -float(s.get("weight", 1)))[:limit]


def scan(cfg) -> list:
    """يعيد المرشحين الذين تجاوزوا عتبتي السرعة والمؤشر."""
    rcfg = cfg.get("radar", {}) or {}
    selection = dict(cfg.get("selection", {}) or {})
    selection["region_diversity"] = False       # لا تنويع هنا — السرعة تحكم

    sources = radar_sources(cfg)
    articles = fetch_all(sources, int(rcfg.get("max_age_hours", 6)))
    if not articles:
        log.info("لا أخبار حديثة")
        return []

    vel = load_velocity()
    ranked = rank(articles, selection, None, 0.0,
                  velocity_entries=vel,
                  velocity_weight=float(selection.get("velocity_weight", 5.0)),
                  merge_cfg=cfg)
    save_velocity(vel)

    min_vel = float(rcfg.get("min_velocity", 0.7))
    min_score = float(rcfg.get("min_score", 16))
    min_sources = int(rcfg.get("min_sources", 2))

    hits = [
        a for a in ranked
        if a.velocity >= min_vel
        and a.score >= min_score
        and a.group_sources >= min_sources
    ]
    log.info("فحص %d مصدر · %d خبر · %d تجاوز العتبات (سرعة≥%.2f، مؤشر≥%.0f)",
             len(sources), len(articles), len(hits), min_vel, min_score)
    if not hits:
        return []

    # فرز الجدارة: السرعة والتغطية لا تكفيان. خبر محلي تافه قد ينتشر
    # بسرعة أيضًا — والرادار قد ينشره تلقائيًا. استدعاء واحد رخيص
    # بـ Haiku يمنع ذلك، ولا يقع إلا حين توجد التقاطات أصلًا.
    # عناوين ما نُشر مؤخرًا تُمرَّر أيضًا: هذا مسار الرادار وحده (لا
    # collect.py)، فتوسيع السؤال إلى «هل هذا تحديث لخبر سابق؟» هنا فقط
    # لا يمسّ تكلفة الفرز العادي (Issue #303).
    recent_titles = store.recent_published_titles(
        int(rcfg.get("auto_publish_dedupe_days", 3)))
    worthy = screen(hits[: int(rcfg.get("screen_top", 10))], cfg,
                    recent_titles=recent_titles) + \
        hits[int(rcfg.get("screen_top", 10)):]
    if len(worthy) < len(hits):
        log.info("فرز الجدارة: مرّ %d من %d", len(worthy), len(hits))

    for a in worthy[:5]:
        log.info("  🔥 [%.1f · سرعة %.2f · %d مصدر] %s",
                 a.score, a.velocity, a.group_sources, a.title[:60])
    return worthy


# ──────────────────────────── المعالجة ────────────────────────────


def build_draft(art, cfg, urgent: bool = True,
                extra: dict | None = None,
                docs: list[dict] | None = None) -> dict | None:
    """يصوغ الخبر ويبني صورته — نفس مسار الدورة العادية.

    `urgent` معامل لا ثابت: الرادار لا يلتقط إلا العاجل، لكن الطلبات
    اليدوية قد تكون عن حدث هادئ فلا يصح وسمه بـ«عاجل».

    `docs` اختياري: يمرَّره `gate_check` إن كان استخرجها أصلًا لفحص
    شرط النشر التلقائي، فلا يُعاد استخراج النص مرتين لنفس الخبر.
    """
    art = enrich_image(art)
    if docs is None:
        acfg = cfg.get("analysis", {}) or {}
        docs, _fetch_failures = gather_texts(art.cluster_members,
                                            limit=int(acfg.get("max_sources", 2)))

    try:
        written = write_arabic(art, cfg, source_docs=docs or None)
    except WriteFailure as exc:
        log.info("فشل تقني في الصياغة (%s) — تخطّي هذه الجولة", exc.reason)
        return None
    if not written:
        log.info("رُفض الخبر عند الصياغة")
        return None

    headline = written["image_headline"] or written["post_title"]
    image_rel = f"drafts/{datetime.now(timezone.utc):%Y-%m-%d}/{art.uid}.jpg"
    shot: dict = {}
    try:
        build_post_image(
            headline=headline, category=written["category"],
            urgent=urgent,
            image_urls=art.image_candidates,
            publisher=art.cluster_sources or [art.publisher],
            bucket=art.bucket,
            fallback_provider=lambda t=art.title: find_images(t, cfg),
            cfg=cfg, out_path=ROOT / image_rel, report=shot,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("فشل توليد الصورة: %s", exc)
        return None

    written["urgent"] = urgent
    draft = {
        "id": art.uid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "review_issue": None,
        "origin": "breaking",
        "from_radar": urgent and not (extra or {}).get("from_request"),
        "score": round(art.score, 2),
        "bucket": art.bucket,
        "velocity": round(art.velocity, 2),
        "trend_score": round(art.trend_score, 2),
        "age_hours": round(art.age_hours, 1),
        "state_media": art.state_media,
        "has_photo": bool(shot.get("used_original")),
        "analysed_sources": [d["name"] for d in docs],
        "source": {
            "title": art.title, "link": art.link,
            "publisher": art.publisher,
            "publishers": art.cluster_sources or [art.publisher],
            "region": art.region, "image_url": art.image_url,
            "image_candidates": art.image_candidates,
        },
        "arabic": written,
        "caption": build_caption(written, art, cfg),
        "image": image_rel,
        "reel": None,
        "reel_spec": {
            "headline": headline, "category": written["category"],
            "urgent": urgent, "image_candidates": art.image_candidates,
        },
    }
    draft.update(extra or {})
    return draft


def gate_check(art, cfg, state: dict) -> tuple[bool, str, list[dict]]:
    """
    هل يُنشر هذا تلقائيًا بلا مراجعة؟ يُحسم *قبل* الصياغة (Issue #312) —
    الصياغة والصورة مكلفتان، وتُهدران على كل ما كان مصيره الرفض لاحقًا.

    النشر بلا مراجعة يعني أن أي خطأ يخرج للجمهور. لذلك كل الشروط التالية
    مجتمعة لا واحد منها — score/group_sources للتأكيد من عدة مصادر
    مستقلة، وفحص التكرار الدلالي في الأخير لأنه لا يميّز تحديث خبر منشور
    عن خبر جديد فعلًا (Issue #303). لا شيء هنا يعتمد على draft: bucket
    مقدَّر أصلًا في rank()، وقراءة النص (extract.gather) لا تستدعي نموذجًا.

    تعيد أيضًا `docs` (نصوص المصادر إن استُخرجت) لتمريرها إلى build_draft
    فتُجنَّب إعادة الاستخراج لما يجتاز الحارس فعلًا.
    """
    a = cfg.get("radar", {}) or {}
    if not a.get("auto_publish", False):
        return False, "النشر التلقائي معطّل", []

    limit = int(a.get("auto_publish_daily_limit", 3))
    if auto_published_today(state) >= limit:
        return False, f"بلغ الحد اليومي ({limit})", []

    if art.score < float(a.get("auto_publish_min_score", 26)):
        return False, f"المؤشر {art.score:.1f} دون عتبة النشر التلقائي", []
    if art.group_sources < int(a.get("auto_publish_min_sources", 4)):
        return False, f"مصادر غير كافية للتأكيد ({art.group_sources})", []
    if art.state_media:
        return False, "إعلام رسمي منفرد — يحتاج مراجعة", []
    if art.bucket == "light":
        return False, "محتوى خفيف — لا يُنشر بلا مراجعة", []

    acfg = cfg.get("analysis", {}) or {}
    docs, _fetch_failures = gather_texts(art.cluster_members,
                                        limit=int(acfg.get("max_sources", 2)))
    if not docs:
        return False, "تعذّرت قراءة نص الخبر", docs

    # الشرط الأهم عمليًا (Issue #303): score وgroup_sources لا يميّزان
    # التكرار — تحديث حصيلة ضحايا لخبر منشور يحقق عتبات عددية عالية مثل
    # أي خبر جديد. آخر ما تُفحص لأنها أغلى الشروط (استدعاء نموذج).
    recent = store.recent_published_titles(int(a.get("auto_publish_dedupe_days", 3)))
    confirmed, matched = merge.find_duplicate_event(art.title, recent, cfg)
    if not confirmed:
        return False, "تعذّر التأكد من عدم التكرار — يحتاج مراجعة", docs
    if matched:
        return False, f"يبدو تحديثًا لخبر نُشر سابقًا: {matched[:70]}", docs

    return True, "استوفى كل شروط النشر التلقائي", docs


# ──────────────────────────── التشغيل ────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="رادار الأخبار العاجلة")
    parser.add_argument("--dry-run", action="store_true",
                        help="فحص فقط بلا صياغة (مجاني تمامًا)")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
                        datefmt="%H:%M:%S")
    cfg = load_config(args.config)
    rcfg = cfg.get("radar", {}) or {}
    if not rcfg.get("enabled", True):
        log.info("الرادار معطّل")
        return 0

    hits = scan(cfg)
    if not hits:
        return 0
    if args.dry_run:
        log.info("dry-run: توقف قبل الصياغة")
        return 0

    history = store.load_history()
    state = _load_state()
    # عتبة ذاكرة التكرار عبر التشغيلات، لا عتبة cluster() — انظر تعليق
    # selection.dedupe_title_similarity في config.yaml
    sim = float(cfg.path("selection.dedupe_title_similarity", 0.5))
    made: list[tuple] = []

    for art in hits[: int(rcfg.get("max_per_run", 1))]:
        if store.find_previous(history, art.title, art.link, sim):
            log.info("التُقط سابقًا: %s", art.title[:60])
            continue

        ok, why, docs = gate_check(art, cfg, state)

        # من لا يستوفي شروط النشر التلقائي: يُحفظ مرشحًا خامًا (بلا صياغة
        # ولا صورة) ليظهر مع مرشحي preselect في أقرب Issue اختيار يفتحه
        # collect.py، بدل إهدار الصياغة على ما سيُرفض غالبًا (Issue #312).
        if not ok and rcfg.get("preselect_fallback", True):
            store.save_candidate(preselect.build_candidate(art))
            # لا بد من تذكّره فورًا: الرادار يفحص كل 15 دقيقة، وبلا هذا
            # سيُعاد التقاطه وحفظه كمرشح مكرر في كل تشغيلة حتى يُختار.
            store.remember(history, art.title, art.link, None,
                           region=art.region, score=art.score, bucket=art.bucket)
            log.info("📥 مرشح preselect (بلا صياغة): %s — %s", art.title[:60], why)
            continue

        draft = build_draft(art, cfg, docs=docs)
        if not draft:
            continue

        draft["auto_publish_decision"] = why
        store.save_draft(draft)
        store.remember(history, art.title, art.link, draft["arabic"]["post_title"],
                       region=art.region, score=art.score, bucket=art.bucket)
        made.append((draft, ok, why))
        log.info("%s %s", "🚀 نشر تلقائي:" if ok else "📋 للمراجعة:", why)

    store.save_history(history, int(cfg.path("selection.dedupe_memory_days", 5)))
    _save_state(state)
    log.info("الاستهلاك: %s", usage_summary())

    if not made:
        return 0

    # النشر التلقائي للمستوفين
    published: list[dict] = []
    for draft, ok, _ in made:
        if not ok:
            continue
        from .publish import publish_one
        found = store.load_draft(draft["id"])
        if not found:
            continue
        success, line = publish_one(found[0], found[1], cfg)
        if success:
            state.setdefault("auto_published", []).append(
                datetime.now(timezone.utc).isoformat())
            published.append(draft)
            log.info("نُشر تلقائيًا: %s", line[:80])
    _save_state(state)

    # تقرير: كل ما التقطه الرادار يُسجَّل حتى المنشور تلقائيًا
    repo = os.environ.get("GITHUB_REPOSITORY")
    lines = ["### 🚨 رادار العاجل", ""]
    for draft, ok, why in made:
        mark = "🚀 **نُشر تلقائيًا**" if draft in published else "📋 بانتظار مراجعتك"
        lines += [
            f"- {mark} · `{draft['score']:.1f}` · سرعة `{draft['velocity']:.2f}`",
            f"  **{draft['arabic']['post_title']}**",
            f"  <sub>{why} · المصادر: "
            f"{'، '.join(draft['source']['publishers'][:3])}</sub>",
            "",
        ]
    text = "\n".join(lines)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")

    if repo and any(not ok for _, ok, _ in made):
        review.ensure_labels()
        branch = os.environ.get("GITHUB_REF_NAME", "main")
        pending = [d for d, ok, _ in made if not ok]
        issue = review.create_issue(
            title=f"🚨 عاجل — {pending[0]['arabic']['post_title'][:60]}",
            body=review.build_issue_body(pending, repo, branch),
            labels=["pending-review"],
        )
        for d in pending:
            found = store.load_draft(d["id"])
            if found:
                store.update_draft(found[0], review_issue=issue["number"])
        log.info("Issue العاجل: %s", issue["html_url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
