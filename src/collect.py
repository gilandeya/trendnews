"""جمع الأخبار الرائجة → صياغة عربية → توليد صورة → مسودات + Issue للمراجعة.

الاستخدام:
    python -m src.collect              # التشغيل الكامل
    python -m src.collect --limit 2    # عدد أقل من المسودات (للتجربة)

هذا الملف يولّد المسودات فقط. فتح Issue المراجعة يجري عبر src.open_review
بعد رفع الصور إلى المستودع، حتى تظهر المعاينات بشكل صحيح.

إن كان `config.yaml: preselect.enabled: true` (Issue #280)، يتوقف الأنبوب
بعد الترتيب والفرز ويحفظ مرشحين خامًا بلا صياغة ولا صورة بدل توليد مسودات
كاملة — src.open_review يفتح عندها Issue اختيار لا Issue مراجعة، و
src.collect_finalize يصوغ المختار فقط وينشره عند وسم `approved` عليه.
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import decisions, feedback, preselect, store
from .config import DRAFTS_DIR, load_config
from .imagesearch import find_images
from .imaging import build_post_image
from .rank import rank
from .screen import screen
from .trends import trending_signatures
from .velocity import load as load_velocity, save as save_velocity
from .extract import gather as gather_texts
from .sources import enrich_image, fetch_all
from .writer import WriteFailure, build_caption, usage_summary, write_arabic

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


def drop_stale_candidates() -> int:
    """يُسقط مرشحين معلَّقين من تشغيلة preselect سابقة لم يُربطوا بعد بـ
    Issue اختيار (selection_issue فارغ) — عادة لأن open_review.py لم
    يُشغَّل بعدها (تشغيلة توقفت مبكرًا) أو دفع state تجاه المستودع فشل.
    بلا هذا الإسقاط تتراكم هذه الملفات مع كل دفعة preselect جديدة فيتضخم
    عدد المرشحين المعروضين تصاعديًا (Issue #296: 5 ثم 10 ثم 22) بدل أن
    يبقى ثابتًا عند العدد المطلوب في كل تشغيلة. تُسجَّل في feedback كـ
    "لم يُختر" حتى يستفيد الفرز الأولي منها كما يستفيد من أي مرشح مرفوض."""
    stale = [(p, c) for p, c in store.pending_candidates()
             if not c.get("selection_issue")]
    if not stale:
        return 0
    entries = feedback.load()
    for path, cand in stale:
        feedback.record_candidate(
            entries, cand, "لم يُختر",
            "مرشح معلَّق من تشغيلة سابقة أُسقط قبل فتح Issue اختيار له")
        store.update_candidate(path, status="unselected")
    feedback.save(entries)
    log.warning("أُسقط %d مرشحًا معلَّقًا من تشغيلة سابقة قبل بناء الدفعة الجديدة",
               len(stale))
    return len(stale)


def run_preselect(candidates: list, selection: dict, dedupe_days: int,
                  dupe_threshold: float, count: int) -> int:
    """يبني مرشحين خامًا للاختيار بلا صياغة ولا صورة ولا استدعاء نموذج
    إضافي — الترتيب والفرز (Haiku) سبقا هذه النقطة أصلًا. الصياغة الفعلية
    تقع لاحقًا في collect_finalize، للمختار فقط، بعد أن يعلّم المراجع."""
    drop_stale_candidates()
    history = store.load_history()
    cooldown = int(selection.get("region_cooldown", 0))
    cooling = set(store.recent_regions(history, cooldown)) if cooldown else set()

    chosen: list = []
    for art in candidates:
        if len(chosen) >= count:
            break
        if art.region in cooling:
            continue
        previous = store.find_previous(history, art.title, art.link, dupe_threshold)
        if previous:
            if not selection.get("allow_followups", True):
                continue
            hours = (datetime.now(timezone.utc)
                     - datetime.fromisoformat(previous["seen_at"])).total_seconds() / 3600
            if hours < float(selection.get("followup_min_hours", 10)):
                continue
        chosen.append(art)

    if not chosen:
        store.save_history(history, dedupe_days)
        log.warning("لا مرشحين للعرض بعد الاستبعاد")
        step_summary("### ℹ️ لا مرشحين لهذه الدورة")
        return 0

    for art in chosen:
        store.save_candidate(preselect.build_candidate(art))
        # لا بد من تذكّره فورًا (بلا صياغة بعد: posted_title=None) — بلا
        # هذا لا يدخل history.json إلا إن اختِير لاحقًا وصِيغ فعليًا، فتُعيد
        # التشغيلة التالية ترشيحه من جديد بصفته "جديدًا" رغم عرضه للتو
        # وانتظاره في Issue اختيار لم يُبتّ فيه بعد (Issue #331؛ نفس نمط
        # preselect_fallback في radar.py من #312).
        store.remember(history, art.title, art.link, None,
                       region=art.region, score=art.score, bucket=art.bucket)

    store.save_history(history, dedupe_days)

    lines = [
        f"### 🗳️ {len(chosen)} مرشح بانتظار الاختيار (بلا صياغة بعد)",
        "",
        *[f"- `{a.score:.1f}` [{a.bucket}] {a.title}" for a in chosen],
    ]
    step_summary("\n".join(lines))
    log.info("preselect: %d مرشح محفوظ بانتظار فتح Issue الاختيار", len(chosen))
    return 0


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

    # يعمل كل تشغيلة، حتى بلا مسودة جديدة (Issue #583 — المرحلة الأولى):
    # إغلاق Issue بلا اعتماد أو انقضاء مهلة قد يقعان بين تشغيلة وأخرى بلا
    # أي حدث آخر يستدعي الفحص. مُحاط بـ try/except عمدًا — جمع بيانات
    # للمراجعة المستقبلية لا يجوز أن يُسقط تشغيلة جمع حقيقية.
    try:
        decisions.scan(cfg)
    except Exception as exc:  # noqa: BLE001
        log.warning("تعذّر فحص القرارات الضمنية: %s", exc)

    selection = cfg.get("selection", {})
    target = args.limit or int(selection.get("drafts_per_run", 5))
    dedupe_days = int(selection.get("dedupe_memory_days", 5))
    # عتبة أخفض من title_similarity (المخصصة لتجميع cluster() داخل نفس
    # التشغيلة) لأن صياغة العنوان تتفاوت أكثر عبر تشغيلات متباعدة زمنيًا
    dupe_threshold = float(selection.get("dedupe_title_similarity", 0.5))

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
        merge_cfg=cfg,
    )
    save_velocity(vel_entries)
    log.info("مرشّحون بعد الترتيب: %d", len(candidates))

    # 4) فرز أولي رخيص: يستبعد غير الصالح قبل أي قراءة مكلفة
    # الأفق يتناسب مع المطلوب: فرز 60 مرشحًا لإنتاج مسودتين إسراف
    per_draft = int(selection.get("screen_per_draft", 8))
    horizon = min(int(selection.get("screen_horizon_max", 90)),
                  max(20, target * per_draft))
    candidates = screen(candidates[:horizon], cfg) + candidates[horizon:]

    # 4.5) نقطة توقف قبل الصياغة (Issue #280): بديل لدورة "صُغ ثم راجِع"
    # لا إضافة إليها — يوقف الأنبوب هنا ويفتح Issue اختيار خام (بلا صياغة
    # ولا صورة) بدل توليد الدفعة كاملة ثم انتظار رفض نصفها في المراجعة.
    preselect_cfg = cfg.get("preselect", {}) or {}
    if preselect_cfg.get("enabled", False):
        return run_preselect(candidates, selection, dedupe_days, dupe_threshold,
                             int(preselect_cfg.get("candidates_per_run", 5)))

    # 5) التوليد — المؤشر يحكم ما دام قويًا، والحصص تتدخل حين يضعف
    history = store.load_history()

    quotas: dict = dict(selection.get("quotas") or {})
    if quotas and target < sum(quotas.values()):
        total = sum(quotas.values())
        scaled = {k: max(1, round(v * target / total)) for k, v in quotas.items()}
        log.info("حصص مضغوطة لدفعة من %d: %s ← %s", target, quotas, scaled)
        quotas = scaled

    # قوة اليوم: أعلى مؤشر سُجّل خلال آخر 24 ساعة
    window = int(selection.get("peak_window_hours", 24))
    ratio = float(selection.get("quota_trigger_ratio", 0.5))
    peak = store.peak_score(history, window)
    best_now = max((a.score for a in candidates), default=0.0)

    strong_day = peak > 0 and best_now >= peak * ratio
    if strong_day:
        # أفضل ما لدينا الآن يقارب ذروة اليوم: اترك المؤشر يحكم وحده،
        # فالخبر القوي أهم من التنويع.
        log.info("يوم قوي (%.1f من ذروة %.1f) — المؤشر يحكم بلا حصص",
                 best_now, peak)
        quotas = {}
    elif peak > 0:
        log.info("يوم ضعيف (%.1f من ذروة %.1f) — الحصص تفتح باب التنويع",
                 best_now, peak)
    else:
        log.info("لا ذروة مسجّلة بعد — الحصص مفعّلة")

    filled: dict[str, int] = {k: 0 for k in quotas}
    log.info("حصص الدفعة: %s", quotas or "بلا حصص (المؤشر وحده)")

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

    cooldown = 0 if strong_day else int(selection.get("region_cooldown", 0))
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

            previous = store.find_previous(history, art.title, art.link, dupe_threshold)
            prev_title = None
            if previous:
                already_posted = bool(previous.get("posted_title"))
                verb = "نُشر" if already_posted else "عُرض ولم يُنشر بعد"
                if not selection.get("allow_followups", True):
                    log.info("مكرر (%s): %s", verb, art.title[:60])
                    continue
                hours = (datetime.now(timezone.utc)
                         - datetime.fromisoformat(previous["seen_at"])).total_seconds() / 3600
                if hours < float(selection.get("followup_min_hours", 10)):
                    log.info("مكرر (%s قبل %.1f ساعة): %s", verb, hours, art.title[:55])
                    continue
                # posted_title فارغ يعني أن أحدث مطابقة مجرد عرض معلَّق لم
                # يُنشر فعلًا — لا نمرّره للنموذج كأنه "نشرنا سابقًا" (Issue #331)
                prev_title = previous.get("posted_title") or None
                if prev_title:
                    log.info("متابعة محتملة لخبر سابق: %s", prev_title[:55])

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
                # الفشليات (سبب كل رابط تعذّر جلبه) غير مستهلَكة هنا — لا
                # trail في مسار الجمع الأساسي كما في article.py؛ اقرأ
                # src.extract.gather للتفاصيل إن احتجتها
                docs, _fetch_failures = gather_texts(art.cluster_members, limit=want)
                if analysable and len(docs) < int(acfg.get("min_sources", 2)):
                    log.info("مصادر غير كافية للتحليل (%d) — وقائع بلا تحليل",
                             len(docs))
                if not docs:
                    log.info("تعذّرت قراءة نص الخبر — قد يُرفض لغياب التفاصيل")

            try:
                written = write_arabic(art, cfg, previous_post=prev_title,
                                       source_docs=docs or None)
            except WriteFailure as exc:
                # عطل تقني (سقف إنفاق أو API) لا رفض تحريري — نتخطّى هذا
                # الخبر في هذه الدفعة فقط، فقد ينجح في التشغيلة التالية
                log.error("فشل تقني في الصياغة (%s): %s", exc.reason, art.title[:60])
                rejected += 1
                rejections.append((art.title[:70], art.bucket, bool(docs)))
                continue
            if not written:
                rejected += 1
                rejections.append((art.title[:70], art.bucket, bool(docs)))
                continue

            headline = written["image_headline"] or written["post_title"]

            # الاسم النسبي داخل drafts/ يبقى بصيغة "drafts/..." دومًا — هذا
            # ما يُحفظ في المسودة ويُستعمل لبناء رابط raw.githubusercontent.com
            # بعد الدفع؛ أما مسار الكتابة الفعلي فيتبع DRAFTS_DIR (تُستبدل
            # بمجلد مؤقت في الاختبارات) لا ROOT مباشرة.
            image_name = f"{datetime.now(timezone.utc):%Y-%m-%d}/{art.uid}.jpg"
            image_rel = f"drafts/{image_name}"
            shot: dict = {}
            try:
                build_post_image(
                    headline=headline,
                    category=written["category"],
                    urgent=written["urgent"],
                    image_urls=art.image_candidates or ([art.image_url] if art.image_url else []),
                    publisher=art.cluster_sources or [art.publisher],
                    bucket=art.bucket,
                    # كسول: لا يُستدعى إلا إن فشلت كل صور الناشر فعليًا
                    fallback_provider=lambda t=art.title: find_images(t, cfg),
                    cfg=cfg,
                    out_path=DRAFTS_DIR / image_name,
                    report=shot,
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
                "bucket": art.bucket,
                "analysed_sources": [d["name"] for d in docs],
                "trend_score": round(art.trend_score, 2),
                "velocity": round(art.velocity, 2),
                "age_hours": round(art.age_hours, 1),
                "is_followup": bool(prev_title),
                "state_media": art.state_media,
                "has_photo": bool(shot.get("used_original")),
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
                # الريل لا يُبنى الآن: يُبنى عند اختياره في المراجعة فقط.
                # توليده لكل مسودة يهدر دقائق حوسبة على ريلز لن تُنشر.
                "reel": None,
                "reel_spec": {
                    "headline": headline,
                    "category": written["category"],
                    "urgent": written["urgent"],
                    "image_candidates": art.image_candidates,
                },
            }
            if quotas:
                filled[art.bucket] = filled.get(art.bucket, 0) + 1
            store.save_draft(draft)
            store.remember(history, art.title, art.link, written["post_title"],
                           region=art.region, score=art.score, bucket=art.bucket)
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
