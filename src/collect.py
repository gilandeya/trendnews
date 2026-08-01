"""جمع الأخبار الرائجة → صياغة عربية → توليد صورة → مسودات + Issue للمراجعة.

الاستخدام:
    python -m src.collect              # التشغيل الكامل
    python -m src.collect --limit 2    # عدد أقل من المسودات (للتجربة)

هذا الملف يولّد المسودات فقط. فتح Issue المراجعة يجري عبر src.open_review
بعد رفع الصور إلى المستودع، حتى تظهر المعاينات بشكل صحيح.
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from . import store
from .config import ROOT, load_config
from .imaging import build_post_image
from .rank import rank
from .sources import enrich_image, fetch_all
from .writer import build_caption, write_arabic

log = logging.getLogger("collect")


def step_summary(text: str) -> None:
    """يكتب ملخصًا يظهر في صفحة تشغيل GitHub Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="جمع الأخبار الرائجة وتوليد مسودات")
    parser.add_argument("--limit", type=int, default=None, help="عدد المسودات")
    parser.add_argument("--config", default=None, help="مسار ملف إعدادات بديل")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = load_config(args.config)
    selection = cfg.get("selection", {})
    target = args.limit or int(selection.get("drafts_per_run", 5))
    dedupe_days = int(selection.get("dedupe_memory_days", 5))
    sim_threshold = float(selection.get("title_similarity", 0.62))

    # 1) الجمع
    articles = fetch_all(cfg.get("sources", []), int(selection.get("max_age_hours", 18)))
    if not articles:
        log.error("لم يُجلب أي خبر — تحقّق من المصادر أو الاتصال")
        step_summary("### ⚠️ لم يُجلب أي خبر")
        return 1

    # 2) الترتيب حسب الترند
    candidates = rank(articles, selection)
    log.info("مرشّحون بعد الترتيب: %d", len(candidates))

    # 3) التوليد
    history = store.load_history()
    drafts: list[dict] = []
    rejected = 0

    for art in candidates:
        if len(drafts) >= target:
            break

        if store.is_duplicate(history, art.title, art.link, sim_threshold):
            log.info("مكرر (نُشر سابقًا): %s", art.title[:60])
            continue

        log.info("── معالجة [%.1f]: %s", art.score, art.title[:70])

        art = enrich_image(art)
        written = write_arabic(art, cfg)
        if not written:
            rejected += 1
            continue

        headline = written["image_headline"] or written["post_title"]
        image_rel = f"drafts/{datetime.now(timezone.utc):%Y-%m-%d}/{art.uid}.jpg"
        try:
            build_post_image(
                headline=headline,
                category=written["category"],
                urgent=written["urgent"],
                image_url=art.image_url,
                publisher=art.publisher,
                cfg=cfg,
                out_path=ROOT / image_rel,
            )
        except Exception as exc:  # noqa: BLE001 — لا نُسقط الدفعة كلها بسبب صورة
            log.error("فشل توليد الصورة: %s", exc)
            continue

        draft = {
            "id": art.uid,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "review_issue": None,
            "score": round(art.score, 2),
            "source": {
                "title": art.title,
                "link": art.link,
                "publisher": art.publisher,
                "publishers": art.cluster_sources or [art.publisher],
                "region": art.region,
                "image_url": art.image_url,
            },
            "arabic": written,
            "caption": build_caption(written, art, cfg),
            "image": image_rel,
        }
        store.save_draft(draft)
        store.remember(history, art.title, art.link)
        drafts.append(draft)
        log.info("✓ مسودة جاهزة: %s", written["post_title"][:60])

    store.save_history(history, dedupe_days)

    if not drafts:
        log.warning("لم تُنتج أي مسودة (%d خبر مرفوض)", rejected)
        step_summary(f"### ℹ️ لا مسودات جديدة\nمرفوض: {rejected} · مرشّحون: {len(candidates)}")
        return 0

    # 4) الملخص — فتح الـ Issue يجري في خطوة لاحقة (بعد رفع الصور للمستودع)
    lines = [
        f"### ✅ {len(drafts)} مسودة جاهزة",
        "",
        *[f"- `{d['score']:.1f}` {d['arabic']['post_title']}" for d in drafts],
    ]
    if rejected:
        lines += ["", f"<sub>رُفض {rejected} خبر لعدم استحقاق النشر</sub>"]
    step_summary("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
