"""يُشغَّل عند وسم `approved` على Issue اختيار (`pending-selection`) —
Issue #280: يصوغ المختارين فقط ويبني صورهم. غير المختارين يُسجَّلون في
feedback.py ليتعلّم screen.py منهم.

Issue #319: كل مرشح مُعلَّم بأحد مربعين — 🚀 «انشر فورًا» يُنشر مباشرة
كالسابق، و📝 «صغ واعرض عليّ قبل النشر» يُحفظ كمسودة عادية وتُفتح له Issue
مراجعة (`pending-review`) منفصل بدل النشر المباشر. المربعان معًا على نفس
المرشح يُحسمان لصالح «صغ واعرض» (الأحوط).

يُستدعى من src.publish.main() حين يحمل Issue الموسوم `approved` وسم
`pending-selection` أيضًا — لا سير عمل مستقل، حتى لا يتضاعف عدد الـ
Issues التي تحتاج مراجعة (استبدال لدورة المراجعة القديمة لا إضافة إليها).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from . import feedback, preselect, review, store
from .config import DRAFTS_DIR
from .extract import gather as gather_texts
from .imagesearch import find_images
from .imaging import build_post_image
from .writer import WriteFailure, build_caption, write_arabic

log = logging.getLogger("collect_finalize")


def _build_draft(art, written: dict, docs: list[dict], prev_title: str | None,
                 cfg) -> dict:
    headline = written["image_headline"] or written["post_title"]
    image_name = f"{datetime.now(timezone.utc):%Y-%m-%d}/{art.uid}.jpg"
    image_rel = f"drafts/{image_name}"
    shot: dict = {}
    build_post_image(
        headline=headline,
        category=written["category"],
        urgent=written["urgent"],
        image_urls=art.image_candidates or ([art.image_url] if art.image_url else []),
        publisher=art.cluster_sources or [art.publisher],
        bucket=art.bucket,
        fallback_provider=lambda t=art.title: find_images(t, cfg),
        cfg=cfg,
        out_path=DRAFTS_DIR / image_name,
        report=shot,
    )
    return {
        "id": art.uid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "review_issue": None,
        "origin": "news",
        "score": round(art.score, 2),
        "bucket": art.bucket,
        "analysed_sources": [d["name"] for d in docs],
        "trend_score": round(art.trend_score, 2),
        "velocity": round(art.velocity, 2),
        "age_hours": round(art.age_hours, 1),
        "is_followup": bool(prev_title),
        "state_media": art.state_media,
        "has_photo": bool(shot.get("used_original")),
        "image_info": {
            "used_original": bool(shot.get("used_original")),
            "illustrative": bool(shot.get("illustrative")),
            "composite": bool(shot.get("composite")),
            "chosen_url": shot.get("chosen_url"),
            "candidates_tried": shot.get("candidates_tried"),
            "manual": False,
        },
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
        "reel": None,
        "reel_spec": {
            "headline": headline,
            "category": written["category"],
            "urgent": written["urgent"],
            "image_candidates": art.image_candidates,
        },
    }


def _record_rejections(unselected_ids: list[str], rejects: dict[str, str]) -> None:
    if not unselected_ids:
        return
    entries = feedback.load()
    for cid in unselected_ids:
        found = store.load_candidate(cid)
        if not found:
            continue
        path, cand = found
        tag = rejects.get(cid) or "لم يُختر"
        note = "" if cid in rejects else "لم يُختر ضمن مرشحي دفعته"
        feedback.record_candidate(entries, cand, tag, note)
        store.update_candidate(path, status="unselected")
    feedback.save(entries)
    log.info("سُجّل %d مرشحًا غير مختار في feedback", len(unselected_ids))


def _write_selected(cid: str, history: list[dict], dupe_threshold: float,
                    acfg: dict, rcfg: dict, cfg,
                    write_errors: list[tuple[str, WriteFailure]]) -> dict | None:
    """يصوغ مرشحًا واحدًا معتمدًا ويبني مسودته — مشتركة بين مساري «انشر
    فورًا» و«صغ واعرض»، فكلاهما يبني نفس شكل المسودة (`_build_draft`) ولا
    يفترق إلا فيما يحدث بعدها (نشر مباشر أم Issue مراجعة)."""
    found = store.load_candidate(cid)
    if not found:
        log.warning("مرشح غير موجود: %s", cid)
        return None
    path, cand = found
    art = preselect.article_from_dict(cand["article"])

    analysable = (
        acfg.get("enabled", True)
        and art.bucket in (acfg.get("buckets") or ["serious"])
        and art.score >= float(acfg.get("min_score", 0))
    )
    want = (int(acfg.get("max_sources", 2)) if analysable
           else int(rcfg.get("max_sources", 1)))
    docs: list[dict] = []
    if rcfg.get("enabled", True) or analysable:
        docs, _fetch_failures = gather_texts(art.cluster_members, limit=want)

    previous = store.find_previous(history, art.title, art.link, dupe_threshold)
    prev_title = None
    if previous:
        # posted_title فارغ = أحدث مطابقة مجرد عرض preselect معلَّق (قد
        # يكون عرض هذا المرشح نفسه قبل اعتماده) لا نشر فعلي — لا نمرّره
        # للنموذج كسياق "نشرنا سابقًا" (Issue #331)
        prev_title = previous.get("posted_title") or None

    try:
        written = write_arabic(art, cfg, previous_post=prev_title,
                               source_docs=docs or None)
    except WriteFailure as exc:
        log.error("فشل تقني في صياغة المرشح المعتمد (%s): %s",
                 exc.reason, art.title[:60])
        write_errors.append((cid, exc))
        return None
    if not written:
        log.warning("رفض الصياغة تحريريًا للمرشح المعتمد: %s", art.title[:60])
        store.update_candidate(path, status="write_failed")
        return None

    draft = _build_draft(art, written, docs, prev_title, cfg)
    store.save_draft(draft)
    store.remember(history, art.title, art.link, written["post_title"],
                   region=art.region, score=art.score, bucket=art.bucket)
    store.update_candidate(path, status="selected")
    return draft


def finalize(issue_number: int, body: str, cfg) -> int:
    all_ids = preselect.all_candidate_ids(body)
    rejects = dict(preselect.parse_candidate_rejects(body))
    # الاعتماد والرفض قد يُعلَّمان معًا — الرفض يغلب (كنمط publish.py نفسه)
    now_raw = [i for i in preselect.parse_publish_now(body) if i not in rejects]
    draft_raw = [i for i in preselect.parse_draft_review(body) if i not in rejects]

    # المربعان معًا على نفس المرشح (Issue #319 البند 1): «صغ واعرض» تغلب
    # (الأحوط) — تُستبعد من now_ids فقط، وتبقى في draft_ids كما هي أصلًا.
    conflict_ids = [i for i in now_raw if i in draft_raw]
    now_ids = [i for i in now_raw if i not in conflict_ids]
    draft_ids = draft_raw

    # عناوين التعارض (لا معرّفاته) تُقرأ *قبل* أي حلقة صياغة تُغيّر حالة
    # المرشح — المعرّف لا يعني شيئًا للمراجع، والعنوان هو ما يتذكره.
    conflict_titles: list[str] = []
    for cid in conflict_ids:
        found = store.load_candidate(cid)
        if found:
            conflict_titles.append(found[1].get("title", cid))

    log.info("Issue اختيار #%s: %d معرّف مرشح في الجسم، %d رفض صريح، "
             "%d انشر فورًا، %d صغ واعرض (منها %d بالمربعين معًا)",
             issue_number, len(all_ids), len(rejects), len(now_ids),
             len(draft_ids), len(conflict_ids))

    # جسم بلا أي معرّف <!-- cand:ID --> مطلقًا يعني الصيغة نفسها خاطئة —
    # على الأرجح Issue "مراجعة مسودات" (draft:) حمل وسم pending-selection
    # خطأً (Issue #296)، لا أن المراجع ترك كل المرشحين بلا تعليم. الفرق
    # جوهري: الحالة الأولى عطل يحتاج تدخلًا يدويًا ويجب ألا تُزيل approved
    # بصمت (فتُخفي العطل)، والثانية اختيار بشري صريح بلا تعليم يُسجَّل
    # ويُزال approved بأمان.
    if not all_ids:
        log.error("Issue #%s: لا معرّف <!-- cand:ID --> واحد في الجسم — "
                  "صيغة الجسم لا تطابق Issue اختيار مرشحين", issue_number)
        review.comment(
            issue_number,
            "⚠️ لم يُعثر على أي معرّف مرشح (`<!-- cand:ID -->`) في جسم هذا "
            "الـ Issue — جسمه بصيغة مسودات لا مرشحين على الأرجح (وسم "
            "`pending-selection` وُضع على Issue من نوع آخر). لم تُصَغ أي "
            "مسودة ولم يُنفق شيء، ووسم `approved` تُرك كما هو حتى تُصحَّح "
            "الحالة يدويًا — إزالته كانت ستُخفي العطل.",
        )
        return 1

    if not now_ids and not draft_ids:
        log.warning("لم يُختر أي مرشح من أصل %d — لا صياغة ولا نشر", len(all_ids))
        _record_rejections(all_ids, rejects)
        review.comment(
            issue_number,
            "⚠️ لم يُعلَّم على أي مرشح. لم تُصَغ أي مسودة ولم يُنفق شيء.",
        )
        review.remove_label(issue_number, "approved")
        return 0

    if conflict_titles:
        titles_list = "، ".join(f"«{t}»" for t in conflict_titles)
        review.comment(
            issue_number,
            f"⚠️ علّمت المربعين معًا (🚀 و📝) على: {titles_list} — عوملا "
            "كـ«📝 صغ واعرض عليّ قبل النشر» (الأحوط: مسودة تراجعها أولًا "
            "بدل نشر مباشر قد لا تريده).",
        )

    history = store.load_history()
    dedupe_days = int(cfg.path("selection.dedupe_memory_days", 5))
    dupe_threshold = float(cfg.path("selection.dedupe_title_similarity", 0.5))
    acfg = cfg.get("analysis", {}) or {}
    rcfg = cfg.get("reading", {}) or {}

    # فشل تقني (سقف إنفاق أو عطل API) يُجمَع منفصلًا عن الرفض التحريري —
    # لا يُغيَّر status المرشح (يبقى قابلًا لإعادة المحاولة بلا إعادة
    # تعليم) ولا يدخل _record_rejections لاحقًا (Issue #308)
    write_errors: list[tuple[str, WriteFailure]] = []

    now_drafts: list[dict] = []
    now_published_ids: list[str] = []
    for cid in now_ids:
        draft = _write_selected(cid, history, dupe_threshold, acfg, rcfg, cfg,
                                write_errors)
        if draft:
            now_drafts.append(draft)
            now_published_ids.append(draft["id"])
            log.info("✓ صيغت مسودة (نشر فوري): %s",
                     draft["arabic"]["post_title"][:60])

    review_drafts: list[dict] = []
    for cid in draft_ids:
        draft = _write_selected(cid, history, dupe_threshold, acfg, rcfg, cfg,
                                write_errors)
        if draft:
            review_drafts.append(draft)
            log.info("✓ صيغت مسودة (بانتظار مراجعتك): %s",
                     draft["arabic"]["post_title"][:60])

    store.save_history(history, dedupe_days)

    selected_ids = now_ids + draft_ids
    unselected = [i for i in all_ids if i not in selected_ids]
    _record_rejections(unselected, rejects)

    total_drafted = len(now_drafts) + len(review_drafts)
    log.info("صيغت %d مسودة من %d معتمد (فشلت الصياغة لـ %d) — %d غير مختار سُجّل في feedback",
             total_drafted, len(selected_ids), len(selected_ids) - total_drafted,
             len(unselected))

    if not now_drafts and not review_drafts:
        if write_errors:
            # عطل تقني لا قرار تحريري: approved يبقى كما هو ليعيد المراجع
            # تشغيل النشر لاحقًا بلا إعادة تعليم، ولا شيء يُسجَّل في
            # feedback — الفشل عارض لا يعكس رأيًا في صلاحية الخبر
            reasons = sorted({exc.reason for _, exc in write_errors})
            detail = write_errors[0][1].detail
            review.comment(
                issue_number,
                f"⚠️ تعذّرت صياغة كل المختارين بسبب عطل خارجي: "
                f"{'، '.join(reasons)} — لم يُنشر شيء.\n"
                f"تفصيل السبب: {detail}\n\n"
                "وسم `approved` تُرك كما هو ولم يُسجَّل أي مرشح كمرفوض — "
                "العطل تقني لا قرار تحرير. أعد تشغيل النشر لاحقًا (بلا "
                "حاجة لإعادة الاختيار) حين يزول السبب.",
            )
            log.error("تعذّرت صياغة كل المختارين لعطل خارجي (%s) — approved أُبقي",
                      "، ".join(reasons))
            return 1
        review.comment(
            issue_number,
            "⚠️ تعذّرت صياغة كل المختارين تحريريًا (رُفضوا كأخبار غير "
            "صالحة للنشر) — لم يُنشر شيء.",
        )
        review.remove_label(issue_number, "approved")
        return 0

    # «صغ واعرض»: Issue مراجعة عادي واحد لكل مسودات هذه الدفعة معًا (لا
    # Issue لكل خبر) — نفس نمط radar.py حين يفتح Issue العاجل مباشرة، لأن
    # finalize يعمل من publish.yml لا من collect.yml فـ open_review.py لا
    # يُشغَّل بعده. العنوان يحمل بادئة مميّزة («📝 مسودات مطلوبة») حتى
    # تُميَّز في قائمة الـ Issues عن Issue المراجعة العادي («📰 مسودات»).
    if review_drafts:
        repo = os.environ.get("GITHUB_REPOSITORY")
        if repo:
            review.ensure_labels()
            branch = os.environ.get("GITHUB_REF_NAME", "main")
            review_issue = review.create_issue(
                title=(f"📝 مسودات مطلوبة "
                       f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC "
                       f"— {len(review_drafts)} منشور"),
                body=review.build_issue_body(review_drafts, repo, branch),
                labels=["pending-review"],
            )
            for d in review_drafts:
                found = store.load_draft(d["id"])
                if found:
                    store.update_draft(found[0], review_issue=review_issue["number"])
            review.comment(
                issue_number,
                f"📝 صيغت {len(review_drafts)} مسودة بانتظار مراجعتك في "
                f"Issue #{review_issue['number']}.",
            )
            log.info("Issue مراجعة «صغ واعرض»: %s", review_issue["html_url"])
        else:
            log.error("GITHUB_REPOSITORY غير موجود — تعذّر فتح Issue مراجعة "
                      "لـ %d مسودة «صغ واعرض»", len(review_drafts))

    if not now_published_ids:
        # لا شيء يبقى معلَّقًا على Issue الاختيار نفسه: كل ما فيه إما
        # "صغ واعرض" (انتقل لـ Issue مراجعة منفصل) أو فشل صياغة مُبلَّغ
        # أعلاه — بلا هذا كان يبقى approved+مفتوحًا للأبد بلا سبب.
        review.close_issue(issue_number)
        log.info("لا مرشح «انشر فورًا» في هذه الدفعة — أُغلق Issue الاختيار "
                 "بلا تفويض نشر")
        return 0

    from . import publish as publish_mod
    if not cfg.path("facebook.schedule_enabled", True):
        mode = "فوري (schedule_enabled=false)"
        log.info("تفويض %d مسودة إلى publish.cmd_now (%s)",
                 len(now_published_ids), mode)
        return publish_mod.cmd_now(now_published_ids, cfg, issue_number)
    if cfg.path("facebook.schedule_mode", "burst") == "burst":
        # يعمل داخل مهمة urgent (سقفها 20 دقيقة) — بلا هذا القيد كان
        # cmd_burst ينام 30-60 دقيقة على المنشور الثاني فتُلغى المهمة قبل
        # أن يكمل (Issue #315). المستحق الآن فقط يُنشر هنا، والبقية تُعلَّم
        # queued بلا انتظار ويلتقطها سيّر queue.yml كل 30 دقيقة.
        inline_cap = float(cfg.path("facebook.finalize_inline_minutes", 0))
        log.info("تفويض %d مسودة إلى publish.cmd_burst (burst، بلا انتظار داخلي)",
                 len(now_published_ids))
        return publish_mod.cmd_burst(now_published_ids, cfg, issue_number,
                                     inline_cap_minutes=inline_cap)
    log.info("تفويض %d مسودة إلى publish.cmd_schedule (schedule)",
             len(now_published_ids))
    return publish_mod.cmd_schedule(now_published_ids, cfg, issue_number)
