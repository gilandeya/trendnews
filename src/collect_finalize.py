"""يُشغَّل عند وسم `approved` على Issue اختيار (`pending-selection`) —
Issue #280: يصوغ المختارين فقط، يبني صورهم، وينشرهم مباشرة بلا مراجعة
ثانية ولا Issue إضافي. غير المختارين يُسجَّلون في feedback.py ليتعلّم
screen.py منهم.

يُستدعى من src.publish.main() حين يحمل Issue الموسوم `approved` وسم
`pending-selection` أيضًا — لا سير عمل مستقل، حتى لا يتضاعف عدد الـ
Issues التي تحتاج مراجعة (استبدال لدورة المراجعة القديمة لا إضافة إليها).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from . import feedback, preselect, review, store
from .config import DRAFTS_DIR
from .extract import gather as gather_texts
from .imagesearch import find_images
from .imaging import build_post_image
from .writer import build_caption, write_arabic

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


def finalize(issue_number: int, body: str, cfg) -> int:
    all_ids = preselect.all_candidate_ids(body)
    rejects = dict(preselect.parse_candidate_rejects(body))
    # الاعتماد والرفض قد يُعلَّمان معًا — الرفض يغلب (كنمط publish.py نفسه)
    selected = [i for i in preselect.parse_selected(body) if i not in rejects]

    log.info("Issue اختيار #%s: %d معرّف مرشح في الجسم، %d رفض صريح، %d معتمد",
             issue_number, len(all_ids), len(rejects), len(selected))

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

    if not selected:
        log.warning("لم يُختر أي مرشح من أصل %d — لا صياغة ولا نشر", len(all_ids))
        _record_rejections(all_ids, rejects)
        review.comment(
            issue_number,
            "⚠️ لم يُعلَّم على أي مرشح. لم تُصَغ أي مسودة ولم يُنفق شيء.",
        )
        review.remove_label(issue_number, "approved")
        return 0

    history = store.load_history()
    dedupe_days = int(cfg.path("selection.dedupe_memory_days", 5))
    dupe_threshold = float(cfg.path("selection.dedupe_title_similarity", 0.5))
    acfg = cfg.get("analysis", {}) or {}
    rcfg = cfg.get("reading", {}) or {}

    drafts: list[dict] = []
    published_ids: list[str] = []

    for cid in selected:
        found = store.load_candidate(cid)
        if not found:
            log.warning("مرشح غير موجود: %s", cid)
            continue
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
            docs = gather_texts(art.cluster_members, limit=want)

        previous = store.find_previous(history, art.title, art.link, dupe_threshold)
        prev_title = None
        if previous:
            prev_title = previous.get("posted_title") or previous.get("title")

        written = write_arabic(art, cfg, previous_post=prev_title,
                               source_docs=docs or None)
        if not written:
            log.warning("رفض الصياغة للمرشح المعتمد: %s", art.title[:60])
            store.update_candidate(path, status="write_failed")
            continue

        draft = _build_draft(art, written, docs, prev_title, cfg)
        store.save_draft(draft)
        store.remember(history, art.title, art.link, written["post_title"],
                       region=art.region, score=art.score, bucket=art.bucket)
        store.update_candidate(path, status="selected")
        drafts.append(draft)
        published_ids.append(draft["id"])
        log.info("✓ صيغت مسودة المرشح المعتمد: %s", written["post_title"][:60])

    store.save_history(history, dedupe_days)

    unselected = [i for i in all_ids if i not in selected]
    _record_rejections(unselected, rejects)

    log.info("صيغت %d مسودة من %d معتمد (فشلت الصياغة لـ %d) — %d غير مختار سُجّل في feedback",
             len(drafts), len(selected), len(selected) - len(drafts), len(unselected))

    if not drafts:
        review.comment(issue_number, "⚠️ تعذّرت صياغة كل المختارين — لم يُنشر شيء.")
        review.remove_label(issue_number, "approved")
        return 0

    from . import publish as publish_mod
    if not cfg.path("facebook.schedule_enabled", True):
        mode = "فوري (schedule_enabled=false)"
        dispatch = publish_mod.cmd_now
    elif cfg.path("facebook.schedule_mode", "burst") == "burst":
        mode = "burst"
        dispatch = publish_mod.cmd_burst
    else:
        mode = "schedule"
        dispatch = publish_mod.cmd_schedule
    log.info("تفويض %d مسودة إلى publish.%s (%s)",
             len(published_ids), dispatch.__name__, mode)
    return dispatch(published_ids, cfg, issue_number)
