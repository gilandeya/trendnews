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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import store
from .config import DRAFTS_DIR, ROOT, load_config
from .imagesearch import find_images
from .imaging import build_post_image
from .reel import build_reel, has_ffmpeg
from .rank import rank
from .screen import screen
from .trends import trending_signatures
from .velocity import load as load_velocity, save as save_velocity
from .extract import gather as gather_texts
from .sources import enrich_image, fetch_all
from .writer import build_caption, usage_summary, write_arabic

log = logging.getLogger("collect")


def prune_reels(keep_days: int) -> None:
    """يحذف ملفات الريل القديمة — كل ريل يعادل عشرة أضعاف حجم الصورة."""
    if keep_days <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    removed = 0
    for path in DRAFTS_DIR.glob("*/*.mp4"):
        try:
            folder_date = datetime.strptime(path.parent.name, "%Y-%m-%d")
        except ValueError:
            continue
        if folder_date.replace(tzinfo=timezone.utc) < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    if removed:
        log.info("حُذف %d ريل قديم لتخفيف حجم المستودع", removed)


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

    # 2) إشارة الطلب من Google Trends
    tcfg = cfg.get("trends", {}) or {}
    signatures: list[set[str]] = []
    if tcfg.get("enabled", True):
        signatures = trending_signatures(tcfg.get("geos") or ["US"])

    # 3) الترتيب: تغطية + طلب + سرعة
    vel_entries = load_velocity()
    candidates = rank(
        articles, selection, signatures, float(tcfg.get("weight", 4.0)),
        velocity_entries=vel_entries,
        velocity_weight=float(selection.get("velocity_weight", 5.0)),
    )
    save_velocity(vel_entries)
    log.info("مرشّحون بعد الترتيب: %d", len(candidates))

    # 4) فرز أولي رخيص: يستبعد غير الصالح قبل أي قراءة مكلفة
    # الأفق يتناسب مع المطلوب: فرز 60 مرشحًا لإنتاج مسودتين إسراف
    per_draft = int(selection.get("screen_per_draft", 8))
    horizon = min(int(selection.get("screen_horizon_max", 90)),
                  max(20, target * per_draft))
    candidates = screen(candidates[:horizon], cfg) + candidates[horizon:]

    # 5) التوليد بحصص: دفعة متنوعة بدل ما تصادف أن يتصدّر
    quotas: dict = dict(selection.get("quotas") or {})
    if quotas and target < sum(quotas.values()):
        # دفعة صغيرة: نضغط الحصص بنسبها بدل تركها كما هي.
        # لولا ذلك لالتهم التصنيف الأول (خفيف=4) دفعةً من ثلاثة كاملة،
        # فتخرج كل الدفعات من نوع واحد.
        total = sum(quotas.values())
        scaled = {k: max(1, round(v * target / total)) for k, v in quotas.items()}
        log.info("حصص مضغوطة لدفعة من %d: %s ← %s", target, quotas, scaled)
        quotas = scaled
    filled: dict[str, int] = {k: 0 for k in quotas}
    log.info("حصص الدفعة: %s", quotas or "بلا حصص")

    history = store.load_history()
    drafts: list[dict] = []
    rejected = 0
    rejections: list[tuple] = []
    deferred: list = []

    def quota_open(bucket: str) -> bool:
        """هل بقيت فتحة لهذا التصنيف؟ (بلا حصص = مفتوح دائمًا)"""
        if not quotas:
            return True
        if bucket not in quotas:
            return False
        return filled[bucket] < quotas[bucket]

    cooldown = int(selection.get("region_cooldown", 0))
    cooling = set(store.recent_regions(history, cooldown)) if cooldown else set()
    if cooling:
        log.info("مناطق في فترة تناوب: %s", "، ".join(sorted(cooling)))

    def on_cooldown(art) -> bool:
        """أُخذ من هذه المنطقة مؤخرًا — أجّله ليظهر غيره."""
        return art.region in cooling

    # المرحلة 1: احترام الحصص. المرحلة 2: ملء ما تبقّى من المؤجَّل.
    for phase in (1, 2):
        pool = candidates if phase == 1 else deferred
        for art in pool:
            if len(drafts) >= target:
                break
            if phase == 1 and quotas and not quota_open(art.bucket):
                deferred.append(art)
                continue
            if phase == 1 and on_cooldown(art):
                deferred.append(art)
                continue

            previous = store.find_previous(history, art.title, art.link, sim_threshold)
            prev_title = None
            if previous:
                if not selection.get("allow_followups", True):
                    log.info("مكرر (نُشر سابقًا): %s", art.title[:60])
                    continue
                hours = (datetime.now(timezone.utc)
                         - datetime.fromisoformat(previous["seen_at"])).total_seconds() / 3600
                if hours < float(selection.get("followup_min_hours", 10)):
                    log.info("مكرر (نُشر قبل %.1f ساعة): %s", hours, art.title[:55])
                    continue
                prev_title = previous.get("posted_title") or previous.get("title")
                log.info("متابعة محتملة لخبر سابق: %s", (prev_title or "")[:55])

            log.info("── معالجة [%.1f · سرعة %.2f]: %s",
                     art.score, art.velocity, art.title[:65])

            art = enrich_image(art)

            # قراءة النص الكامل — لكل التصنيفات.
            # الخبر الخفيف يُكتب من العنوان والملخص فقط، وهما بضعة أسطر
            # لا تحوي وقائع — فيخرج المنشور إنشاءً بلا تفاصيل. القراءة
            # تعطي النموذج ما يقوله فعلًا.
            acfg = cfg.get("analysis", {}) or {}
            rcfg = cfg.get("reading", {}) or {}

            analysable = (
                acfg.get("enabled", True)
                and art.bucket in (acfg.get("buckets") or ["serious"])
                and art.score >= float(acfg.get("min_score", 0))
            )
            want = (int(acfg.get("max_sources", 2)) if analysable
                    else int(rcfg.get("max_sources", 1)))

            docs: list[dict] = []
            if rcfg.get("enabled", True) or analysable:
                docs = gather_texts(art.cluster_members, limit=want)
                if analysable and len(docs) < int(acfg.get("min_sources", 2)):
                    log.info("مصادر غير كافية للتحليل (%d) — وقائع بلا تحليل",
                             len(docs))
                if not docs:
                    log.info("تعذّرت قراءة نص الخبر — قد يُرفض لغياب التفاصيل")

            written = write_arabic(art, cfg, previous_post=prev_title,
                                   source_docs=docs or None)
            if not written:
                rejected += 1
                rejections.append((art.title[:70], art.bucket, bool(docs)))
                continue

            headline = written["image_headline"] or written["post_title"]

            image_rel = f"drafts/{datetime.now(timezone.utc):%Y-%m-%d}/{art.uid}.jpg"
            try:
                build_post_image(
                    headline=headline,
                    category=written["category"],
                    urgent=written["urgent"],
                    image_urls=art.image_candidates or ([art.image_url] if art.image_url else []),
                    publisher=art.publisher,
                    # كسول: لا يُستدعى إلا إن فشلت كل صور الناشر فعليًا
                    fallback_provider=lambda t=art.title: find_images(t, cfg),
                    cfg=cfg,
                    out_path=ROOT / image_rel,
                )
            except Exception as exc:  # noqa: BLE001 — لا نُسقط الدفعة كلها بسبب صورة
                log.error("فشل توليد الصورة: %s", exc)
                continue

            # الريل: يُنتَج بجانب الصورة، والاختيار عند المراجعة
            reel_rel = None
            rlcfg = cfg.get("reel", {}) or {}
            if not rlcfg.get("enabled", True):
                log.info("الريل معطّل في الإعدادات (reel.enabled=false)")
            elif not has_ffmpeg():
                # لا تتخطَّ بصمت: الصمت هنا يبدو كأن الميزة غير مثبتة
                log.warning("⚠️ ffmpeg غير مثبّت على هذا الخادم — لا ريلز. "
                            "أضف خطوة تثبيته إلى سير العمل.")
            else:
                candidate = f"drafts/{datetime.now(timezone.utc):%Y-%m-%d}/{art.uid}.mp4"
                if build_reel(headline, written["category"], written["urgent"],
                              art.image_candidates, cfg, ROOT / candidate):
                    reel_rel = candidate

            draft = {
                "id": art.uid,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "pending",
                "review_issue": None,
                "score": round(art.score, 2),
                "bucket": art.bucket,
                "analysed_sources": [d["name"] for d in docs],
                "trend_score": round(art.trend_score, 2),
                "velocity": round(art.velocity, 2),
                "age_hours": round(art.age_hours, 1),
                "is_followup": bool(prev_title),
                "state_media": art.state_media,
                "source": {
                    "title": art.title,
                    "link": art.link,
                    "publisher": art.publisher,
                    "publishers": art.cluster_sources or [art.publisher],
                    "region": art.region,
                    "image_url": art.image_url,
                    "image_candidates": art.image_candidates,
                },
                "arabic": written,
                "caption": build_caption(written, art, cfg),
                "image": image_rel,
                "reel": reel_rel,
            }
            if quotas:
                filled[art.bucket] = filled.get(art.bucket, 0) + 1
            store.save_draft(draft)
            store.remember(history, art.title, art.link, written["post_title"],
                           region=art.region)
            cooling.add(art.region)
            drafts.append(draft)
            log.info("✓ مسودة جاهزة: %s", written["post_title"][:60])


    store.save_history(history, dedupe_days)
    prune_reels(int((cfg.get("reel", {}) or {}).get("keep_days", 3)))
    log.info("الاستهلاك: %s", usage_summary())

    if not drafts:
        log.warning("لم تُنتج أي مسودة (%d خبر مرفوض)", rejected)
        step_summary(f"### ℹ️ لا مسودات جديدة\nمرفوض: {rejected} · مرشّحون: {len(candidates)}")
        return 0

    # 5) الملخص — فتح الـ Issue يجري في خطوة لاحقة (بعد رفع الصور للمستودع)
    lines = [
        f"### ✅ {len(drafts)} مسودة جاهزة",
        "",
        *[f"- `{d['score']:.1f}` {d['arabic']['post_title']}" for d in drafts],
    ]
    if rejected:
        no_text = sum(1 for _, _, had in rejections if not had)
        lines += ["", f"<sub>رُفض {rejected} خبر"
                  + (f" ({no_text} منها تعذّرت قراءة نصه)" if no_text else "")
                  + "</sub>"]
        lines += ["", "<details><summary>الأخبار المرفوضة</summary>", ""]
        lines += [f"- `{b}` {t}" for t, b, _ in rejections[:15]]
        lines += ["", "</details>"]
    lines += ["", f"<sub>💵 {usage_summary()}</sub>"]
    step_summary("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
