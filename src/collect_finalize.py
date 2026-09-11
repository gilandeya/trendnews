"""يُشغَّل عند وسم `approved` على Issue اختيار (`pending-selection`) —
Issue #280: يصوغ المختارين فقط ويبني صورهم. غير المختارين يُسجَّلون في
feedback.py ليتعلّم screen.py منهم.

Issue #319: كل مرشح مُعلَّم بأحد مربعين — 🚀 «انشر فورًا» يُنشر مباشرة
كالسابق، و📝 «صغ واعرض عليّ قبل النشر» يُحفظ كمسودة عادية وتُفتح له Issue
مراجعة (`pending-review`) منفصل بدل النشر المباشر. المربعان معًا على نفس
المرشح يُحسمان لصالح «صغ واعرض» (الأحوط).

Issue #860: مربع ثالث 🎴 «صُغ واعرض البطاقة» يُصاغ بنفس `_build_draft`
تمامًا ثم تُبنى بطاقته فورًا (`cards.ensure`) وتُفتح له Issue مراجعة نهائية
واحد بوسم `final-review` (`review.build_final_review_body`، نفسه الذي بناه
Issue #858) — بلا مرور بالمراجعة الأولية إطلاقًا. الأحوط يغلب عند تعارض
المربعات الثلاثة: 📝 تغلب 🚀 و🎴 معًا، و🎴 تغلب 🚀 وحدها.

يُستدعى من src.publish.main() حين يحمل Issue الموسوم `approved` وسم
`pending-selection` أيضًا — لا سير عمل مستقل، حتى لا يتضاعف عدد الـ
Issues التي تحتاج مراجعة (استبدال لدورة المراجعة القديمة لا إضافة إليها).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from . import cards, feedback, headlines as headlines_mod, preselect, review, store
from .extract import gather as gather_texts
from .writer import WriteFailure, build_caption, write_arabic

log = logging.getLogger("collect_finalize")


def _build_draft(art, written: dict, docs: list[dict], prev_title: str | None,
                 cfg) -> dict:
    headline = written["image_headline"] or written["post_title"]

    # عناوين مقترحة (Issue #756) -- بعد نجاح الصياغة، بنفس آلية
    # مسار التحليل القائمة (youtube_article.generate_headlines) لكن بكتلة
    # config.yaml العامة (headlines، لا youtube.review.headlines -- الازدواج
    # مقصود). فشل النداء لا يُسقِط مسودة صيغت بنجاح فعليًا (نفس مبدأ مسار
    # التحليل): تُحفَظ headlines فارغة ولا تُعرَض لها مربعات في المراجعة.
    headlines, hl_error = headlines_mod.headlines_for_post(
        written["post_title"], written["post_body"], cfg)
    if hl_error:
        log.warning("فشلت اقتراحات العناوين لـ%r: %s", art.title[:60], hl_error)
        headlines = []

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
        "headlines": headlines,
        "headline_selected": 0,
        # بلا حقل image عمدًا (Issue #852) -- البطاقة تُبنى عند الاعتماد
        # (cards.ensure) لا هنا، نفس مبدأ src/collect.py.
        "reel": None,
        "reel_spec": {
            "headline": headline,
            "category": written["category"],
            "urgent": written["urgent"],
            "image_candidates": art.image_candidates,
        },
    }


def _candidate_titles(ids: list[str]) -> list[str]:
    """عناوين المرشحين — لرسائل تنبيه التعارض وحدها (لا معرّفاتهم، فالمعرّف
    لا يعني شيئًا للمراجع)، تُقرأ *قبل* أي حلقة صياغة تُغيّر حالة المرشح."""
    titles: list[str] = []
    for cid in ids:
        found = store.load_candidate(cid)
        if found:
            titles.append(found[1].get("title", cid))
    return titles


def _record_rejections(unselected_ids: list[str]) -> None:
    if not unselected_ids:
        return
    entries = feedback.load()
    for cid in unselected_ids:
        found = store.load_candidate(cid)
        if not found:
            continue
        path, cand = found
        feedback.record_candidate(entries, cand, "لم يُختر", "لم يُختر ضمن مرشحي دفعته")
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
    now_raw = preselect.parse_publish_now(body)
    draft_raw = preselect.parse_draft_review(body)
    card_raw = preselect.selected_card_ids(body)

    # ثلاثة مربعات مستقلة لكل مرشح (Issue #860 فوق أساس #319 البند 1):
    # الأحوط يغلب عند التداخل — draft_ids = draft_raw دومًا (📝 تغلب كل
    # شيء)؛ card_ids تُستبعد منها ما وقع في draft_raw (📝 تغلب 🎴)؛
    # now_ids تُستبعد منها ما وقع في draft_raw أو card_raw (📝 و🎴 كلاهما
    # يغلب 🚀).
    now_set = set(now_raw)
    draft_set = set(draft_raw)
    card_raw_set = set(card_raw)

    draft_ids = draft_raw
    card_ids = [i for i in card_raw if i not in draft_set]
    now_ids = [i for i in now_raw if i not in draft_set and i not in card_raw_set]

    # تعارضات للتنبيه والسجل فقط — لا تؤثر على القرار أعلاه (محسوم بالفعل
    # بالاستبعاد). draft_conflict_ids: عُلِّم 📝 مع 🚀 و/أو 🎴 على نفس
    # المرشح. card_conflict_ids: عُلِّم 🚀 مع 🎴 بلا 📝 — أي مرشح فيه 📝
    # معًا يقع في draft_conflict_ids فقط، لا تكرار.
    draft_conflict_ids = [i for i in draft_raw if i in now_set or i in card_raw_set]
    card_conflict_ids = [i for i in card_raw if i in now_set and i not in draft_set]

    log.info("Issue اختيار #%s: %d معرّف مرشح في الجسم، "
             "%d انشر فورًا، %d صغ واعرض (منها %d بمربع آخر معًا)، "
             "%d صُغ واعرض البطاقة (منها %d مع 🚀 بلا 📝)",
             issue_number, len(all_ids), len(now_ids), len(draft_ids),
             len(draft_conflict_ids), len(card_ids), len(card_conflict_ids))

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

    if not now_ids and not draft_ids and not card_ids:
        log.warning("لم يُختر أي مرشح من أصل %d — لا صياغة ولا نشر", len(all_ids))
        _record_rejections(all_ids)
        review.comment(
            issue_number,
            "⚠️ لم يُعلَّم على أي مرشح. لم تُصَغ أي مسودة ولم يُنفق شيء.",
        )
        review.remove_label(issue_number, "approved")
        return 0

    if draft_conflict_ids:
        titles_list = "، ".join(f"«{t}»" for t in _candidate_titles(draft_conflict_ids))
        review.comment(
            issue_number,
            f"⚠️ علّمت المربعين معًا (📝 مع 🚀 و/أو 🎴) على: {titles_list} — "
            "عوملت كـ«📝 صغ واعرض عليّ قبل النشر» (الأحوط: المراجعة الأولية "
            "أوسع، فيها العناوين وتعديل النص).",
        )
    if card_conflict_ids:
        titles_list = "، ".join(f"«{t}»" for t in _candidate_titles(card_conflict_ids))
        review.comment(
            issue_number,
            f"⚠️ علّمت 🚀 مع 🎴 بلا 📝 على: {titles_list} — عوملت كـ«🎴 صُغ "
            "واعرض البطاقة» (الأحوط: مراجعة نهائية للبطاقة بدل نشر مباشر "
            "بلا عرض).",
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

    # «انشر فورًا» (Issue #868): نفس مبدأ بناء بطاقة 🎴 أسفله تمامًا — قبل
    # #852 كانت البطاقة تُبنى مع الصياغة نفسها، فلم يكن هذا المسار يحتاج
    # استدعاءً خاصًا؛ بعده صارت البطاقة تُبنى فقط عند الاعتماد
    # (publish.main، السطر ~745) أو في مسار 🎴 صراحة — وهذا المسار يُسلِّم
    # المعرّفات مباشرة إلى publish.cmd_now/cmd_burst/cmd_schedule بلا مرور
    # بـpublish.main إطلاقًا، فبقي بلا استدعاء (الشاهد: 🚀 نُشر 0 من 1 —
    # حقول مفقودة: image). now_written يُحسَب بصرف النظر عن نجاح البطاقة
    # (مطابقًا لـ card_written أسفله) لأن فشل البناء وحده لا يعني "لم
    # تُصَغ مسودة" — فلا يُخلَط مع فشل الصياغة التقني (write_errors).
    now_drafts: list[dict] = []
    now_written = 0
    for cid in now_ids:
        draft = _write_selected(cid, history, dupe_threshold, acfg, rcfg, cfg,
                                write_errors)
        if not draft:
            continue
        now_written += 1
        found = store.load_draft(draft["id"])
        if not found:
            continue
        now_path, now_draft = found
        if cards.ensure(now_path, now_draft, cfg) is None:
            log.warning("تعذّر بناء بطاقة المسودة 🚀 %s — تُترك pending بلا صورة",
                       draft["id"])
            review.comment(
                issue_number,
                f"⚠️ تعذّر بناء بطاقة **{now_draft['arabic']['post_title'][:60]}** "
                "🚀 — بقيت المسودة معلَّقة بلا صورة، وستظهر في أقرب Issue "
                "مراجعة أولية.",
            )
            continue
        now_drafts.append(now_draft)
        log.info("✓ صيغت مسودة (نشر فوري) وبُنيت بطاقتها: %s",
                 now_draft["arabic"]["post_title"][:60])
    now_published_ids = [d["id"] for d in now_drafts]

    review_drafts: list[dict] = []
    for cid in draft_ids:
        draft = _write_selected(cid, history, dupe_threshold, acfg, rcfg, cfg,
                                write_errors)
        if draft:
            review_drafts.append(draft)
            log.info("✓ صيغت مسودة (بانتظار مراجعتك): %s",
                     draft["arabic"]["post_title"][:60])

    # «صُغ واعرض البطاقة» (Issue #860): نفس _write_selected تمامًا (لا شكل
    # مسودة جديدًا)، ثم بطاقتها تُبنى فورًا هنا (لا عند اعتماد لاحق) —
    # مباشرة بالعنوان الافتراضي (arabic.image_headline)، فلا مربع عناوين
    # لها أصلًا في المراجعة النهائية. card_written يُحسَب بصرف النظر عن
    # نجاح البطاقة (تدخل total_drafted بمجرد كتابتها، مثل now_written/
    # review_drafts) — فشل البناء وحده لا يعني "لم تُصَغ مسودة".
    card_drafts: list[dict] = []
    card_written = 0
    for cid in card_ids:
        draft = _write_selected(cid, history, dupe_threshold, acfg, rcfg, cfg,
                                write_errors)
        if not draft:
            continue
        card_written += 1
        found = store.load_draft(draft["id"])
        if not found:
            continue
        card_path, card_draft = found
        if cards.ensure(card_path, card_draft, cfg) is None:
            log.warning("تعذّر بناء بطاقة المسودة 🎴 %s — تُترك pending بلا صورة",
                       draft["id"])
            review.comment(
                issue_number,
                f"⚠️ تعذّر بناء بطاقة **{card_draft['arabic']['post_title'][:60]}** "
                "🎴 — بقيت المسودة معلَّقة بلا صورة، وستظهر في أقرب Issue "
                "مراجعة أولية.",
            )
            continue
        card_drafts.append(card_draft)
        log.info("✓ صيغت مسودة 🎴 وبُنيت بطاقتها: %s",
                 card_draft["arabic"]["post_title"][:60])

    store.save_history(history, dedupe_days)

    selected_ids = now_ids + draft_ids + card_ids
    unselected = [i for i in all_ids if i not in selected_ids]
    _record_rejections(unselected)

    total_drafted = now_written + len(review_drafts) + card_written
    log.info("صيغت %d مسودة من %d معتمد (فشلت الصياغة لـ %d) — %d غير مختار سُجّل في feedback",
             total_drafted, len(selected_ids), len(selected_ids) - total_drafted,
             len(unselected))

    if not now_written and not review_drafts and not card_written:
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

    # «صُغ واعرض البطاقة»: Issue مراجعة نهائية واحد يجمع مسودات 🎴 كلها في
    # هذه الدفعة (لا Issue لكل مسودة) — نفس build_final_review_body الذي
    # بناه Issue #858 لمسار المراجعة الأولية، بوسم final-review. مسودة
    # فشل بناء بطاقتها (أعلاه) لا تدخل هذا الـIssue أصلًا — بقيت pending
    # بلا image وعُلِّق بسببها على Issue الاختيار بدل ذلك.
    if card_drafts:
        # تنازليًا بالدرجة للعرض فقط (Issue #874) — لا يمسّ ترتيب البناء
        # أعلاه (بترتيب المرشحين كما وردت من مربعات الاختيار).
        card_drafts = review.sort_by_score(card_drafts)
        repo = os.environ.get("GITHUB_REPOSITORY")
        if repo:
            review.ensure_labels()
            branch = os.environ.get("GITHUB_REF_NAME", "main")
            final_issue = review.create_issue(
                title=(f"🎴 مراجعة نهائية "
                       f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC "
                       f"— {len(card_drafts)} منشور"),
                body=review.build_final_review_body(card_drafts, repo, branch),
                labels=["final-review"],
            )
            for d in card_drafts:
                found = store.load_draft(d["id"])
                if found:
                    store.update_draft(found[0], review_issue=final_issue["number"])
            review.comment(
                issue_number,
                f"🎴 صيغت {len(card_drafts)} مسودة ببطاقتها بانتظار مراجعة "
                f"نهائية في Issue #{final_issue['number']}.",
            )
            log.info("Issue مراجعة نهائية «🎴»: %s", final_issue["html_url"])
        else:
            log.error("GITHUB_REPOSITORY غير موجود — تعذّر فتح Issue مراجعة "
                      "نهائية لـ %d مسودة 🎴", len(card_drafts))

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
