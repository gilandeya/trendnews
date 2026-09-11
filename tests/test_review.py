"""اختبارات مجال «المراجعة والنشر والاختيار» — تجزّأت من tests/test_pipeline.py (Issue #883): preselect.py، review.py/open_review.py، publish.py والجدولة (schedule.py)، setimage.py، الملاحظات (feedback.py)، طلب مقال (request.py)، العناوين المقترحة (headlines.py)، حقل origin وstore.origin_of، سجل القرارات (decisions.py)، وتقرير الأداء (insights.py). المساعدات المشتركة (check، الفاكات، install_fakes) في tests/helpers.py."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image

from tests.helpers import (
    check,
    tick_marker,
    install_fakes,
    _TMP_DATA_DIR,
    collect,
    evidence,
    facebook,
    headlines,
    imagesearch,
    imaging,
    open_review,
    review,
    store,
    trends,
    writer,
    youtube_article,
    youtube_publish,
    DRAFTS_DIR,
    STATE_DIR,
    load_config,
    Article,
)


def test_review_roundtrip() -> None:
    drafts = [d for _, d in store.pending_drafts()]
    # لا نُرجع مبكرًا عند غياب المسودات (نمط سابق كان يتخطى أربعة فحوص
    # بصمت) — الفحوص التالية تعمل بقيم افتراضية آمنة فتُظهر فشلها صراحة
    # بدل أن تختفي من التقرير.
    check("توجد مسودات لبناء الـ Issue", bool(drafts), f"{len(drafts)}")

    body = review.build_issue_body(drafts, "user/trendnews", "main")
    ids = review.all_draft_ids(body)
    check("معرفات المسودات مضمّنة في نص الـ Issue",
          len(ids) == len(drafts), f"{len(ids)} من {len(drafts)}")
    # البطاقة (image) لم تُبنَ بعد لمسودات الجمع الآن (Issue #852) -- لا
    # رابط raw.githubusercontent.com يظهر (لا شيء رُفع للمستودع)؛ بدلًا
    # منه أول مرشَّح صورة خام من source.image_candidates إن وُجد.
    check("لا روابط raw.githubusercontent.com قبل بناء أي بطاقة",
          "raw.githubusercontent.com" not in body, body[:400])
    has_candidates = any((d.get("source") or {}).get("image_candidates") for d in drafts)
    check("صورة المصدر الخام تُعرض حين تتوفر مرشَّحات (Issue #852)",
          not has_candidates or "<img" in body, body[:400])
    check("مربعات الاختيار فارغة ابتداءً", review.parse_approved(body) == [])

    # محاكاة تعليم المستخدم على المسودة الأولى
    marked = body.replace(f"- [ ] **1.", f"- [x] **1.", 1)
    approved = review.parse_approved(marked)
    expected_first = [drafts[0]["id"]] if drafts else []
    check("قراءة العلامة ✔️ تعمل", approved == expected_first, str(approved))

    marked_all = marked.replace("- [ ] **2.", "- [x] **2.", 1)
    check("اعتماد متعدد يعمل", len(review.parse_approved(marked_all)) == min(2, len(drafts)))

def test_preselect_no_spend_before_selection() -> None:
    """بناء Issue الاختيار لا يستدعي صياغة Sonnet ولا يبني صورة — فقط
    الترتيب والفرز الرخيصان (Haiku) سبقا هذه النقطة، تمامًا كالدورة
    القديمة قبلها. هذا هو التوفير الذي طلبه Issue #280: الإنفاق يقع بعد
    الاختيار البشري لا قبله."""
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    write_calls: list = []
    real_write = writer.write_arabic

    def _spy_write(*a, **kw):
        write_calls.append(1)
        return real_write(*a, **kw)

    writer.write_arabic = _spy_write
    collect.write_arabic = _spy_write

    cfg = load_config()
    cfg["preselect"] = {"enabled": True, "candidates_per_run": 5}
    real_load_config = collect.load_config
    collect.load_config = lambda path=None: cfg

    sys.argv = ["collect", "--limit", "5"]
    try:
        code = collect.main()
    finally:
        collect.load_config = real_load_config
        writer.write_arabic = real_write
        collect.write_arabic = real_write

    check("preselect انتهى بنجاح", code == 0, f"exit={code}")
    check("لا استدعاء لصياغة Sonnet أثناء بناء الاختيار", write_calls == [])
    # لا بناء صورة أثناء بناء الاختيار: collect.py لم يعد يستورد
    # build_post_image إطلاقًا (Issue #852) — البطاقة تُبنى عند الاعتماد
    # فقط في كل مسارات الأخبار الآن، لا داخل preselect ولا خارجه.

    pending = store.pending_candidates()
    check("مرشحون خام محفوظون بانتظار الاختيار", len(pending) > 0, str(len(pending)))
    if pending:
        _, cand = pending[0]
        for field in ("id", "title", "link", "publishers", "bucket", "score", "article"):
            check(f"حقل '{field}' موجود في المرشح", field in cand)
        check("لا حقل صياغة عربية في المرشح الخام", "arabic" not in cand)

    check("لا مسودات جاهزة أُنشئت في مرحلة preselect (بلا صياغة ولا صورة)",
          len(store.pending_drafts()) == 0, f"{len(store.pending_drafts())}")

    history = store.load_history()
    check("run_preselect سجّل مرشحيه في history.json فورًا (Issue #331) "
          "فلا يُعاد التقاطهم كـ«جدد» قبل أن يُبتّ في مصيرهم",
          pending and store.find_previous(
              history, pending[0][1]["title"], pending[0][1]["link"], 0.5) is not None)

def test_preselect_no_duplicate_across_runs() -> None:
    """Issue #331: تشغيلتان متتاليتان لـ collect (preselect.enabled=True)
    بفارق دقائق يجب ألا تُنتجا نفس المرشحين مرتين — قبل الإصلاح كان
    run_preselect لا يستدعي store.remember، فلا يدخل المرشحون ذاكرة
    التكرار إلا إن اختِيروا لاحقًا، فتُعاد تشغيلة قريبة زمنيًا التقاط
    نفس الأخبار من جديد بصفتها "جديدة" في Issue اختيار منفصل."""
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    cfg["preselect"] = {"enabled": True, "candidates_per_run": 5}
    real_load_config = collect.load_config
    collect.load_config = lambda path=None: cfg
    sys.argv = ["collect", "--limit", "5"]
    try:
        code1 = collect.main()
        first_titles = {c["title"] for _, c in store.pending_candidates()}
        code2 = collect.main()
        second_run_titles = {c["title"] for _, c in store.pending_candidates()} - first_titles
    finally:
        collect.load_config = real_load_config

    check("كلتا التشغيلتين انتهتا بنجاح", code1 == 0 and code2 == 0,
          f"{code1}, {code2}")
    check("التشغيلة الأولى أنتجت مرشحين", len(first_titles) > 0, str(len(first_titles)))
    check("التشغيلة الثانية (بعد قليل) لم تُعِد نفس مرشحي الأولى كمرشحين جدد",
          second_run_titles == set(), str(second_run_titles))

def test_preselect_finalize() -> None:
    """الاعتماد على Issue الاختيار يصوغ المختار وحده وينشره مباشرة، وغير
    المختار يُسجَّل في feedback ليتعلّم الفرز الأولي منه لاحقًا."""
    from src import collect_finalize, feedback, preselect
    from src import publish as publish_mod

    now = datetime.now(timezone.utc)
    art_a = Article(title="خبر أول يستحق الاختيار الآن", link="https://pre.example/a",
                    summary="", source_name="P1", region="r1", weight=1.0,
                    published=now, bucket="serious", publisher="P1")
    art_b = Article(title="خبر ثانٍ لن يختاره أحد", link="https://pre.example/b",
                    summary="", source_name="P2", region="r2", weight=1.0,
                    published=now, bucket="light", publisher="P2")

    cand_a = preselect.build_candidate(art_a)
    cand_b = preselect.build_candidate(art_b)
    store.save_candidate(cand_a)
    store.save_candidate(cand_b)

    body = preselect.build_selection_issue_body([cand_a, cand_b])
    marked = tick_marker(body, f"now:{cand_a['id']}")   # «انشر فورًا» للمرشح الأول فقط

    now_selected = preselect.parse_publish_now(marked)
    check("تحليل «انشر فورًا» يلتقط المُعلَّم فقط", now_selected == [cand_a["id"]],
          str(now_selected))
    check("لا أحد عُلِّم على «صغ واعرض»",
          preselect.parse_draft_review(marked) == [])

    captured: dict = {}

    def fake_burst(ids, cfg, issue_number, only_urgent=False, skip_urgent=False,
                   inline_cap_minutes=None):
        captured["ids"] = list(ids)
        captured["issue_number"] = issue_number
        captured["inline_cap_minutes"] = inline_cap_minutes
        return 0

    real_burst = publish_mod.cmd_burst
    publish_mod.cmd_burst = fake_burst

    rejections_before = len(feedback.load())

    try:
        code = collect_finalize.finalize(4242, marked, load_config())
    finally:
        publish_mod.cmd_burst = real_burst

    check("finalize انتهى بنجاح", code == 0, f"exit={code}")
    check("نُشر المختار وحده عبر cmd_burst",
          captured.get("ids") == [cand_a["id"]], str(captured))
    check("رقم الـ Issue مرَّر لـ cmd_burst", captured.get("issue_number") == 4242)
    check("finalize يمرّر inline_cap_minutes=0 كي لا ينام urgent (Issue #315)",
          captured.get("inline_cap_minutes") == 0, str(captured))

    check("صيغت مسودة للمختار", store.load_draft(cand_a["id"]) is not None)
    check("لم تُصَغ مسودة لغير المختار", store.load_draft(cand_b["id"]) is None)
    check("collect_finalize.py يكتب origin=news صراحةً (Issue #749)",
          store.load_draft(cand_a["id"])[1].get("origin") == "news",
          store.load_draft(cand_a["id"])[1].get("origin"))
    finalized_a = store.load_draft(cand_a["id"])[1]
    check("collect_finalize.py: يحفظ headlines/headline_selected (Issue #756)",
          isinstance(finalized_a.get("headlines"), list) and len(finalized_a["headlines"]) == 3
          and finalized_a.get("headline_selected") == 0, finalized_a.get("headlines"))

    rejections_after = feedback.load()
    check("عدد سجلات الرفض ازداد بواحد فقط (غير المختار وحده)",
          len(rejections_after) == rejections_before + 1,
          f"{len(rejections_after)} مقابل {rejections_before}")
    check("غير المختار سُجّل في feedback بسبب عام «لم يُختر»",
          any(e["id"] == cand_b["id"] and e["tag"] == "لم يُختر"
              for e in rejections_after),
          str(rejections_after[-3:]))

    updated_a = store.load_candidate(cand_a["id"])
    check("حالة المختار selected", updated_a and updated_a[1]["status"] == "selected")
    updated_b = store.load_candidate(cand_b["id"])
    check("حالة غير المختار unselected",
          updated_b and updated_b[1]["status"] == "unselected")

def test_preselect_now_builds_card_before_publish() -> None:
    """Issue #868: مسار 🚀 «انشر فورًا» يسلّم المعرّفات مباشرة إلى
    publish.cmd_burst/cmd_now/cmd_schedule بلا مرور بـpublish.main (حيث
    تُبنى البطاقة عمومًا عند الاعتماد، السطر ~745) — فكانت المسودة تخرج
    بلا بطاقة، يرفضها publish._missing_draft_fields (الشاهد الحقيقي: «🚀
    نُشر 0 من 1 · ❌ ... — حقول مفقودة: image»). الآن collect_finalize
    يبني البطاقة صراحةً (cards.ensure) قبل تسليم المعرّف للنشر، بنفس نمط
    مسار 🎴 (وradar.auto_publish) — فينشر فعليًا بلا رفض."""
    from src import collect_finalize, preselect, review
    from src import publish as publish_mod

    now = datetime.now(timezone.utc)
    art = Article(title="خبر عاجل يُنشر فورًا عبر 🚀", link="https://pre.example/nowcard-ok",
                 summary="", source_name="NC", region="rn", weight=1.0,
                 published=now, bucket="serious", publisher="NC",
                 image_candidates=["https://cdn.example/nowcard-ok.jpg"])
    cand = preselect.build_candidate(art)
    store.save_candidate(cand)

    body = preselect.build_selection_issue_body([cand])
    marked = tick_marker(body, f"now:{cand['id']}")

    real_comment = review.comment
    real_close = review.close_issue
    comment_calls: list = []
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))
    review.close_issue = lambda issue_number: None

    published_paths: list = []
    real_publish_photo = facebook.publish_photo
    real_root = publish_mod.ROOT
    # publish_one يبني مسار الصورة عبر publish.ROOT (لا DRAFTS_DIR) —
    # يجب توجيهه لمجلد الاختبار المؤقت (راجع test_radar_auto_publish_builds_card).
    publish_mod.ROOT = DRAFTS_DIR.parent

    def fake_publish_photo(image_path, caption, api_version, first_comment=None):
        published_paths.append(image_path)
        return {"url": "https://fb.example/nowcard", "id": "99"}

    facebook.publish_photo = fake_publish_photo

    try:
        code = collect_finalize.finalize(4868, marked, load_config())
    finally:
        review.comment = real_comment
        review.close_issue = real_close
        facebook.publish_photo = real_publish_photo
        publish_mod.ROOT = real_root

    check("finalize انتهى بنجاح", code == 0, f"exit={code}")
    check("نُشر فعلًا (لا رفض بحقول مفقودة)", len(published_paths) == 1, published_paths)

    saved = store.load_draft(cand["id"])
    check("المسودة محفوظة", saved is not None)
    if saved:
        check("البطاقة بُنيت فعلًا قبل النشر (حقل image ظهر — Issue #868)",
              bool(saved[1].get("image")), saved[1].get("image"))
        check("حالة المسودة published", saved[1].get("status") == "published",
              saved[1].get("status"))

    rejection_comments = [t for _, t in comment_calls if "حقول مفقودة" in t]
    check("لا تعليق برفض بحقول مفقودة (الشاهد قبل الإصلاح)", rejection_comments == [],
          rejection_comments)

def test_preselect_now_card_build_failure_keeps_pending() -> None:
    """Issue #868، الشق الثاني: فشل بناء البطاقة في مسار 🚀 لا يُسقط
    المسودة ولا ينشرها بلا صورة — تبقى pending بلا image، لا تدخل
    publish.cmd_burst إطلاقًا، ويُعلَّق بالسبب على Issue الاختيار باسمها
    (فتلتقطها أقرب مراجعة أولية). نفس معالجة الفشل القائمة في مسار 🎴
    حرفيًا (test_preselect_card_build_failure_keeps_pending)."""
    from src import cards, collect_finalize, preselect, review
    from src import publish as publish_mod

    now = datetime.now(timezone.utc)
    art = Article(title="خبر 🚀 تفشل صناعة بطاقته", link="https://pre.example/nowcard-fail",
                 summary="", source_name="NF", region="rf", weight=1.0,
                 published=now, bucket="serious", publisher="NF")
    cand = preselect.build_candidate(art)
    store.save_candidate(cand)

    body = preselect.build_selection_issue_body([cand])
    marked = tick_marker(body, f"now:{cand['id']}")

    real_ensure = cards.ensure
    ensure_calls: list = []
    cards.ensure = lambda *a, **kw: (ensure_calls.append(1), None)[1]

    comment_calls: list = []
    real_comment = review.comment
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))

    close_issue_calls: list = []
    real_close = review.close_issue
    review.close_issue = lambda issue_number: close_issue_calls.append(issue_number)

    burst_calls: list = []
    real_burst = publish_mod.cmd_burst
    publish_mod.cmd_burst = lambda *a, **kw: burst_calls.append(a) or 0

    try:
        code = collect_finalize.finalize(4869, marked, load_config())
    finally:
        cards.ensure = real_ensure
        review.comment = real_comment
        review.close_issue = real_close
        publish_mod.cmd_burst = real_burst

    check("finalize انتهى بنجاح رغم فشل بناء البطاقة", code == 0, f"exit={code}")
    check("cards.ensure استُدعيت فعلًا", ensure_calls == [1], ensure_calls)
    check("لا نداء لـcmd_burst إطلاقًا — لا شيء يستحق النشر", burst_calls == [], burst_calls)

    saved = store.load_draft(cand["id"])
    check("المسودة صيغت فعلًا رغم فشل البطاقة", saved is not None)
    if saved:
        check("بقيت pending", saved[1].get("status") == "pending", saved[1].get("status"))
        check("بلا حقل image", "image" not in saved[1], saved[1].get("image"))

    failure_comments = [t for _, t in comment_calls if "تعذّر بناء بطاقة" in t]
    check("عُلِّق بسبب فشل البطاقة على Issue الاختيار باسم المسودة",
          len(failure_comments) == 1, comment_calls)
    check("Issue الاختيار أُغلق (لا نشر مباشر متبقٍّ)",
          close_issue_calls == [4869], close_issue_calls)

def test_preselect_empty_selection_no_spend() -> None:
    """لا تعليم على أي مرشح = لا صياغة ولا نشر ولا إنفاق (Issue #280،
    البند 4). حتى وسم `approved` بالخطأ على Issue بلا أي تعليم يجب ألا
    يستدعي الصياغة أو النشر — فقط يعلّم البوت من الرفض الضمني."""
    from src import collect_finalize, feedback, preselect, review
    from src import publish as publish_mod

    # لا شبكة في الاختبارات (راجع تذييل الملف): finalize بلا اختيار يعلّق
    # على الـ Issue ويزيل الوسم — نُحاكي هذين بلا اتصال حقيقي بواجهة GitHub.
    comment_calls, remove_label_calls = [], []
    real_comment = review.comment
    real_remove_label = review.remove_label
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))
    review.remove_label = lambda issue_number, label: remove_label_calls.append(
        (issue_number, label))

    now = datetime.now(timezone.utc)
    art_c = Article(title="خبر ثالث بلا أي تعليم على الإطلاق",
                    link="https://pre.example/c", summary="", source_name="P3",
                    region="r3", weight=1.0, published=now, bucket="useful",
                    publisher="P3")
    cand_c = preselect.build_candidate(art_c)
    store.save_candidate(cand_c)

    body = preselect.build_selection_issue_body([cand_c])   # بلا أي تعليم

    write_calls: list = []
    real_write = collect_finalize.write_arabic

    def _spy_write(*a, **kw):
        write_calls.append(1)
        return real_write(*a, **kw)

    collect_finalize.write_arabic = _spy_write

    burst_calls, now_calls, schedule_calls = [], [], []
    real_burst = publish_mod.cmd_burst
    real_now = publish_mod.cmd_now
    real_schedule = publish_mod.cmd_schedule
    publish_mod.cmd_burst = lambda *a, **kw: burst_calls.append(1)
    publish_mod.cmd_now = lambda *a, **kw: now_calls.append(1)
    publish_mod.cmd_schedule = lambda *a, **kw: schedule_calls.append(1)

    rejections_before = len(feedback.load())

    try:
        code = collect_finalize.finalize(5252, body, load_config())
    finally:
        collect_finalize.write_arabic = real_write
        publish_mod.cmd_burst = real_burst
        publish_mod.cmd_now = real_now
        publish_mod.cmd_schedule = real_schedule
        review.comment = real_comment
        review.remove_label = real_remove_label

    check("finalize بلا تعليم ينتهي بنجاح", code == 0, f"exit={code}")
    check("لا استدعاء صياغة إطلاقًا", write_calls == [])
    check("لا استدعاء نشر من أي نوع",
          not burst_calls and not now_calls and not schedule_calls)
    check("لا مسودة أُنشئت", store.load_draft(cand_c["id"]) is None)
    check("تعليق توضيحي على الـ Issue بلا نشر فعلي (بلا شبكة)",
          len(comment_calls) == 1 and comment_calls[0][0] == 5252)
    check("وسم approved يُزال حتى يصحّح المراجع اختياره",
          remove_label_calls == [(5252, "approved")])

    rejections_after = feedback.load()
    check("المرشح غير المُعلَّم سُجّل كـ«لم يُختر»",
          any(e["id"] == cand_c["id"] and e["tag"] == "لم يُختر"
              for e in rejections_after))
    check("سجل رفض واحد فقط أُضيف", len(rejections_after) == rejections_before + 1)

    updated_c = store.load_candidate(cand_c["id"])
    check("حالة المرشح unselected", updated_c and updated_c[1]["status"] == "unselected")

def test_preselect_drops_stale_candidates() -> None:
    """مرشح معلَّق من تشغيلة preselect سابقة بلا selection_issue (خلل دفع
    state، أو تشغيلة توقفت قبل open_review) لا يجوز أن يتراكم مع الدفعة
    التالية — كان هذا سبب Issue #296 (5 مرشح ثم 10 ثم 22). يجب أن يُسقط
    ويُسجَّل في feedback قبل بناء أي دفعة جديدة."""
    from src import feedback
    from src import preselect as preselect_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    stale_art = Article(title="مرشح معلَّق من تشغيلة preselect سابقة",
                        link="https://pre.example/stale", summary="",
                        source_name="PS", region="rs", weight=1.0,
                        published=now, bucket="serious", publisher="PS")
    stale_cand = preselect_mod.build_candidate(stale_art)
    store.save_candidate(stale_cand)   # selection_issue: None — كأنه من تشغيلة سابقة لم تُربط

    check("المرشح القديم معلَّق فعلًا قبل التشغيلة",
          len(store.pending_candidates()) == 1)

    rejections_before = len(feedback.load())

    cfg = load_config()
    cfg["preselect"] = {"enabled": True, "candidates_per_run": 5}
    real_load_config = collect.load_config
    collect.load_config = lambda path=None: cfg

    sys.argv = ["collect", "--limit", "5"]
    try:
        code = collect.main()
    finally:
        collect.load_config = real_load_config

    check("preselect ينتهي بنجاح رغم وجود مرشح قديم معلَّق", code == 0, f"exit={code}")

    updated_stale = store.load_candidate(stale_cand["id"])
    check("المرشح القديم أُسقط (لم يعد pending)",
          updated_stale is not None and updated_stale[1]["status"] != "pending",
          str(updated_stale[1]["status"] if updated_stale else None))

    rejections_after = feedback.load()
    check("المرشح القديم سُجّل في feedback كـ«لم يُختر»",
          any(e["id"] == stale_cand["id"] and e["tag"] == "لم يُختر"
              for e in rejections_after),
          str(rejections_after[-3:]))
    check("سجل رفض واحد فقط أُضيف للمرشح القديم",
          len(rejections_after) >= rejections_before + 1)

    fresh = store.pending_candidates()
    check("القديم لم يعد ضمن المرشحين المعلَّقين", stale_cand["id"] not in
          {c["id"] for _, c in fresh})
    check("عدد الدفعة الجديدة لا يتجاوز candidates_per_run رغم وجود مرشح قديم مسبقًا",
          len(fresh) <= 5, str(len(fresh)))

def test_preselect_two_boxes_now_and_draft_review() -> None:
    """البند 1: «انشر فورًا» يصوغ وينشر مباشرة (سلوك preselect الأصلي)،
    و«صغ واعرض» يصوغ ويحفظ مسودة عادية في Issue مراجعة منفصل بعنوان
    مميّز (البند 3 من طلب الموافقة). تعليم المربعين معًا يُحسم لصالح «صغ
    واعرض» ويُعلَّق تنبيه يذكر عنوان الخبر لا معرّفه (البند 1 من طلب
    الموافقة)."""
    from src import collect_finalize, feedback, preselect, review
    from src import publish as publish_mod

    now = datetime.now(timezone.utc)
    art_now = Article(title="خبر يُنشر فورًا بلا عرض", link="https://pre.example/now",
                      summary="", source_name="PN", region="rn", weight=1.0,
                      published=now, bucket="serious", publisher="PN")
    art_draft = Article(title="خبر يُصاغ ويُعرض قبل النشر",
                        link="https://pre.example/draft", summary="",
                        source_name="PD", region="rd", weight=1.0,
                        published=now, bucket="serious", publisher="PD")
    art_both = Article(title="خبر عُلِّم عليه المربعان معًا بالخطأ",
                       link="https://pre.example/both", summary="",
                       source_name="PB", region="rb", weight=1.0,
                       published=now, bucket="serious", publisher="PB")

    cand_now = preselect.build_candidate(art_now)
    cand_draft = preselect.build_candidate(art_draft)
    cand_both = preselect.build_candidate(art_both)
    for c in (cand_now, cand_draft, cand_both):
        store.save_candidate(c)

    body = preselect.build_selection_issue_body([cand_now, cand_draft, cand_both])
    marked = body
    marked = tick_marker(marked, f"now:{cand_now['id']}")
    marked = tick_marker(marked, f"review:{cand_draft['id']}")
    marked = tick_marker(marked, f"now:{cand_both['id']}")
    marked = tick_marker(marked, f"review:{cand_both['id']}")

    check("«انشر فورًا» يلتقط المرشح الأول والثالث (المزدوج)",
          preselect.parse_publish_now(marked) == [cand_now["id"], cand_both["id"]])
    check("«صغ واعرض» يلتقط المرشح الثاني والثالث (المزدوج)",
          preselect.parse_draft_review(marked)
          == [cand_draft["id"], cand_both["id"]])

    burst_calls: list = []

    def fake_burst(ids, cfg, issue_number, only_urgent=False, skip_urgent=False,
                   inline_cap_minutes=None):
        burst_calls.append(list(ids))
        return 0

    create_issue_calls: list = []

    def fake_create_issue(title, body, labels=None):
        create_issue_calls.append({"title": title, "body": body, "labels": labels})
        return {"number": 9911, "html_url": "https://x/issues/9911"}

    comment_calls: list = []
    ensure_labels_calls: list = []

    real_burst = publish_mod.cmd_burst
    real_create_issue = review.create_issue
    real_comment = review.comment
    real_ensure_labels = review.ensure_labels
    publish_mod.cmd_burst = fake_burst
    review.create_issue = fake_create_issue
    review.comment = lambda issue_number, text: comment_calls.append(
        (issue_number, text))
    review.ensure_labels = lambda: ensure_labels_calls.append(1)

    rejections_before = len(feedback.load())

    real_repo = os.environ.get("GITHUB_REPOSITORY")
    real_ref = os.environ.get("GITHUB_REF_NAME")
    os.environ["GITHUB_REPOSITORY"] = "user/trendnews"
    os.environ["GITHUB_REF_NAME"] = "main"
    try:
        code = collect_finalize.finalize(4343, marked, load_config())
    finally:
        publish_mod.cmd_burst = real_burst
        review.create_issue = real_create_issue
        review.comment = real_comment
        review.ensure_labels = real_ensure_labels
        if real_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo
        if real_ref is None:
            os.environ.pop("GITHUB_REF_NAME", None)
        else:
            os.environ["GITHUB_REF_NAME"] = real_ref

    check("finalize انتهى بنجاح", code == 0, f"exit={code}")
    check("«انشر فورًا» فُوِّض للنشر وحده (لا المزدوج ولا «صغ واعرض»)",
          burst_calls == [[cand_now["id"]]], str(burst_calls))

    check("Issue مراجعة واحد فُتح لكل مسودات «صغ واعرض» في الدفعة",
          len(create_issue_calls) == 1, str(len(create_issue_calls)))
    if create_issue_calls:
        opened = create_issue_calls[0]
        check("عنوان Issue «صغ واعرض» مميّز عن Issue المراجعة العادي",
              opened["title"].startswith("📝 مسودات مطلوبة"), opened["title"])
        check("Issue «صغ واعرض» يحمل وسم pending-review كأي مراجعة عادية",
              opened["labels"] == ["pending-review"], str(opened["labels"]))
        check("جسم Issue «صغ واعرض» يضم مسودتي الثاني والمزدوج",
              f"<!-- draft:{cand_draft['id']} -->" in opened["body"]
              and f"<!-- draft:{cand_both['id']} -->" in opened["body"])
        # البند 4: خانة تبديل الصورة تظهر فعليًا الآن — المسودة تُعرض في
        # Issue مراجعة حقيقي بدل ألا تُعرض أبدًا كما قبل هذا التغيير.
        check("مربع تبديل الصورة يظهر في Issue «صغ واعرض»",
              f"<!-- img:{cand_draft['id']} -->" in opened["body"])
        check("فراغ رابط الصورة يظهر في Issue «صغ واعرض»",
              f"<!-- imgurl:{cand_draft['id']} -->" in opened["body"])

    check("مسودة صيغت للمنشور فورًا", store.load_draft(cand_now["id"]) is not None)
    draft_review_saved = store.load_draft(cand_draft["id"])
    both_review_saved = store.load_draft(cand_both["id"])
    check("مسودة صيغت للمرشح الثاني (صغ واعرض)", draft_review_saved is not None)
    check("مسودة صيغت للمرشح المزدوج (صغ واعرض تغلب)", both_review_saved is not None)
    if draft_review_saved:
        check("review_issue للمسودة الثانية مربوط بالـ Issue المفتوح",
              draft_review_saved[1].get("review_issue") == 9911,
              str(draft_review_saved[1].get("review_issue")))
    if both_review_saved:
        check("review_issue للمسودة المزدوجة مربوط بالـ Issue المفتوح أيضًا",
              both_review_saved[1].get("review_issue") == 9911)
        check("المزدوج لم يُنشر مباشرة (status ليست published/queued)",
              both_review_saved[1].get("status") not in ("published", "queued"))

    conflict_comments = [
        text for _, text in comment_calls
        if "المربعين معًا" in text
    ]
    check("تنبيه التعارض عُلِّق على Issue الاختيار الأصلي",
          len(conflict_comments) == 1, str(comment_calls))
    if conflict_comments:
        check("تنبيه التعارض يذكر عنوان الخبر لا معرّفه فقط",
              art_both.title in conflict_comments[0]
              and cand_both["id"] not in conflict_comments[0],
              conflict_comments[0])

    rejections_after = feedback.load()
    check("لا تسجيل رفض لأي من الثلاثة (كلهم اختيروا بطريقة أو بأخرى)",
          len(rejections_after) == rejections_before)

def test_preselect_draft_review_image_swap_works() -> None:
    """البند 4: مربع تبديل الصورة يعمل فعليًا في مسار «صغ واعرض» —
    setimage.apply_image يخزّن الرابط اليدوي في manual_image بلا محاولة
    بناء (Issue #852: المسودة الناتجة بلا حقل image حتى الاعتماد الآن،
    نفس مسار أي مسودة أخبار أخرى)، فتلتقطه cards.ensure لاحقًا."""
    from src import collect_finalize, preselect, review, setimage
    from src import publish as publish_mod

    now = datetime.now(timezone.utc)
    art = Article(title="خبر يحتاج تبديل صورته بعد الصياغة",
                 link="https://pre.example/imgswap", summary="",
                 source_name="PI", region="ri", weight=1.0,
                 published=now, bucket="serious", publisher="PI")
    cand = preselect.build_candidate(art)
    store.save_candidate(cand)

    body = preselect.build_selection_issue_body([cand])
    marked = tick_marker(body, f"review:{cand['id']}")

    real_burst = publish_mod.cmd_burst
    real_create_issue = review.create_issue
    real_comment = review.comment
    real_ensure_labels = review.ensure_labels
    real_close_issue = review.close_issue
    publish_mod.cmd_burst = lambda *a, **kw: 0
    review.create_issue = lambda title, body, labels=None: {
        "number": 9922, "html_url": "https://x/issues/9922"}
    review.comment = lambda issue_number, text: None
    review.ensure_labels = lambda: None
    close_issue_calls: list = []
    review.close_issue = lambda issue_number: close_issue_calls.append(issue_number)

    real_repo = os.environ.get("GITHUB_REPOSITORY")
    os.environ["GITHUB_REPOSITORY"] = "user/trendnews"
    try:
        code = collect_finalize.finalize(4344, marked, load_config())
    finally:
        publish_mod.cmd_burst = real_burst
        review.create_issue = real_create_issue
        review.comment = real_comment
        review.ensure_labels = real_ensure_labels
        review.close_issue = real_close_issue
        if real_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo

    check("Issue الاختيار الأصلي أُغلق (لا شيء «انشر فورًا» يبقى معلَّقًا)",
          close_issue_calls == [4344], str(close_issue_calls))

    check("finalize (صغ واعرض فقط) انتهى بنجاح", code == 0, f"exit={code}")
    saved = store.load_draft(cand["id"])
    check("مسودة «صغ واعرض» صيغت فعلًا", saved is not None)
    if not saved:
        return
    check("مسودة «صغ واعرض» بلا حقل image (Issue #852 -- البطاقة تُبنى عند الاعتماد)",
          "image" not in saved[1], saved[1].get("image"))

    updated = setimage.apply_image(cand["id"], "https://cdn.example/new-photo.jpg",
                                   load_config())
    check("setimage.apply_image ينجح (يخزّن الرابط بلا محاولة بناء)",
          updated is not None)
    if updated:
        check("لا حقل image بعد -- لم يُبنَ شيء هنا، البناء عند الاعتماد فقط",
              "image" not in updated, updated.get("image"))
        check("manual_image خُزّن للاستعمال لاحقًا في cards.ensure",
              updated.get("manual_image") == "https://cdn.example/new-photo.jpg",
              updated.get("manual_image"))
        reloaded = store.load_draft(cand["id"])
        check("التحديث محفوظ فعليًا في المسودة على القرص",
              reloaded is not None
              and reloaded[1].get("manual_image") == "https://cdn.example/new-photo.jpg")

def test_preselect_card_marker_and_selected_card_ids() -> None:
    """Issue #860، البند 1: المربع الثالث 🎴 يظهر بعلامة sel-card: غير
    معلَّم في جسم Issue الاختيار الخام، وselected_card_ids تقرأ المُعلَّم
    منها فقط وتتجاهل غيره (بنفس أسلوب parse_publish_now/parse_draft_review)."""
    from src import preselect

    now = datetime.now(timezone.utc)
    art = Article(title="مرشح لفحص مربع البطاقة الثالث",
                 link="https://pre.example/cardmarker", summary="",
                 source_name="PC", region="rc", weight=1.0,
                 published=now, bucket="serious", publisher="PC")
    cand = preselect.build_candidate(art)

    body = preselect.build_selection_issue_body([cand])
    check("علامة sel-card: تظهر في الجسم الخام غير معلَّمة",
          f"- [ ] 🎴 صُغ واعرض البطاقة (بلا مراجعة أولية)  <!-- sel-card:{cand['id']} -->"
          in body, body)
    check("selected_card_ids لا تلتقط شيئًا قبل التعليم",
          preselect.selected_card_ids(body) == [])

    marked = tick_marker(body, f"sel-card:{cand['id']}")
    check("selected_card_ids تلتقط المُعلَّم فقط",
          preselect.selected_card_ids(marked) == [cand["id"]])
    check("تعليم 🎴 لا يؤثر على قراءة now/review",
          preselect.parse_publish_now(marked) == []
          and preselect.parse_draft_review(marked) == [])

def test_preselect_card_only_and_three_way_conflicts() -> None:
    """Issue #860، البنود 2-4 من طلب الاختبارات: 🎴 وحده ⇒ مسودة ببطاقة
    وIssue final-review بلا مراجعة أولية؛ 📝 مع 🎴 ⇒ مراجعة أولية بلا
    بطاقة؛ 🚀 مع 🎴 (بلا 📝) ⇒ لا نشر مباشر (يذهب للبطاقة)؛ الثلاثة معًا
    ⇒ مراجعة أولية (📝 تغلب)؛ مرشح غير معلَّم يُسجَّل «لم يُختر» ومرشحو
    🎴 لا يُسجَّلون كذلك؛ ودفعة فيها 🎴 و📝 معًا تفتح Issueين لا واحدًا."""
    from src import collect_finalize, feedback, preselect, review
    from src import publish as publish_mod

    now = datetime.now(timezone.utc)

    def _art(slug, title):
        return Article(title=title, link=f"https://pre.example/{slug}",
                       summary="", source_name=slug, region="rc", weight=1.0,
                       published=now, bucket="serious", publisher=slug,
                       image_url="https://cdn.example/card-source.jpg")

    art_card_only = _art("cardonly", "خبر 🎴 وحده بلا مراجعة أولية")
    art_draft_card = _art("draftcard", "خبر 📝 مع 🎴 معًا")
    art_now_card = _art("nowcard", "خبر 🚀 مع 🎴 بلا 📝")
    art_triple = _art("triple", "خبر بالمربعات الثلاثة معًا")
    art_none = _art("none", "خبر لم يُعلَّم عليه شيء")

    cand_card_only = preselect.build_candidate(art_card_only)
    cand_draft_card = preselect.build_candidate(art_draft_card)
    cand_now_card = preselect.build_candidate(art_now_card)
    cand_triple = preselect.build_candidate(art_triple)
    cand_none = preselect.build_candidate(art_none)
    all_cands = [cand_card_only, cand_draft_card, cand_now_card, cand_triple, cand_none]
    for c in all_cands:
        store.save_candidate(c)

    body = preselect.build_selection_issue_body(all_cands)
    marked = body
    marked = tick_marker(marked, f"sel-card:{cand_card_only['id']}")
    marked = tick_marker(marked, f"review:{cand_draft_card['id']}")
    marked = tick_marker(marked, f"sel-card:{cand_draft_card['id']}")
    marked = tick_marker(marked, f"now:{cand_now_card['id']}")
    marked = tick_marker(marked, f"sel-card:{cand_now_card['id']}")
    marked = tick_marker(marked, f"now:{cand_triple['id']}")
    marked = tick_marker(marked, f"review:{cand_triple['id']}")
    marked = tick_marker(marked, f"sel-card:{cand_triple['id']}")
    # cand_none: بلا أي تعليم

    burst_calls: list = []

    def fake_burst(ids, cfg, issue_number, only_urgent=False, skip_urgent=False,
                   inline_cap_minutes=None):
        burst_calls.append(list(ids))
        return 0

    create_issue_calls: list = []

    def fake_create_issue(title, body, labels=None):
        create_issue_calls.append({"title": title, "body": body, "labels": labels})
        if labels == ["final-review"]:
            return {"number": 9944, "html_url": "https://x/issues/9944"}
        return {"number": 9933, "html_url": "https://x/issues/9933"}

    comment_calls: list = []

    real_burst = publish_mod.cmd_burst
    real_create_issue = review.create_issue
    real_comment = review.comment
    real_ensure_labels = review.ensure_labels
    real_close_issue = review.close_issue
    publish_mod.cmd_burst = fake_burst
    review.create_issue = fake_create_issue
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))
    review.ensure_labels = lambda: None
    close_issue_calls: list = []
    review.close_issue = lambda issue_number: close_issue_calls.append(issue_number)

    rejections_before = len(feedback.load())

    real_repo = os.environ.get("GITHUB_REPOSITORY")
    real_ref = os.environ.get("GITHUB_REF_NAME")
    os.environ["GITHUB_REPOSITORY"] = "user/trendnews"
    os.environ["GITHUB_REF_NAME"] = "main"
    try:
        code = collect_finalize.finalize(4860, marked, load_config())
    finally:
        publish_mod.cmd_burst = real_burst
        review.create_issue = real_create_issue
        review.comment = real_comment
        review.ensure_labels = real_ensure_labels
        review.close_issue = real_close_issue
        if real_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo
        if real_ref is None:
            os.environ.pop("GITHUB_REF_NAME", None)
        else:
            os.environ["GITHUB_REF_NAME"] = real_ref

    check("finalize انتهى بنجاح", code == 0, f"exit={code}")
    check("لا نشر مباشر إطلاقًا في هذه الدفعة (🚀 مع 🎴 ⇒ لا نشر مباشر)",
          burst_calls == [], burst_calls)
    check("Issue الاختيار أُغلق (لا مرشح انتهى بنشر مباشر)",
          close_issue_calls == [4860], close_issue_calls)

    check("Issueان اثنان فُتحا -- مراجعة أولية ومراجعة نهائية معًا",
          len(create_issue_calls) == 2, create_issue_calls)
    pending_issue = next((c for c in create_issue_calls
                          if c["labels"] == ["pending-review"]), None)
    final_issue = next((c for c in create_issue_calls
                        if c["labels"] == ["final-review"]), None)
    check("Issue مراجعة أولية بوسم pending-review فُتح", pending_issue is not None)
    check("Issue مراجعة نهائية بوسم final-review فُتح", final_issue is not None)

    if pending_issue:
        check("مراجعة أولية تضم 📝+🎴 و🚀+📝+🎴 (📝 تغلب في الحالتين)",
              f"<!-- draft:{cand_draft_card['id']} -->" in pending_issue["body"]
              and f"<!-- draft:{cand_triple['id']} -->" in pending_issue["body"],
              pending_issue["body"])
        check("مراجعة أولية لا تضم 🎴 وحده ولا 🚀+🎴",
              f"<!-- draft:{cand_card_only['id']} -->" not in pending_issue["body"]
              and f"<!-- draft:{cand_now_card['id']} -->" not in pending_issue["body"])

    if final_issue:
        check("مراجعة نهائية تضم 🎴 وحده و🚀+🎴 (بلا 📝)",
              f"<!-- draft:{cand_card_only['id']} -->" in final_issue["body"]
              and f"<!-- draft:{cand_now_card['id']} -->" in final_issue["body"],
              final_issue["body"])
        check("مراجعة نهائية لا تضم من فيه 📝",
              f"<!-- draft:{cand_draft_card['id']} -->" not in final_issue["body"]
              and f"<!-- draft:{cand_triple['id']} -->" not in final_issue["body"])
        check("مراجعة نهائية بلا مربعات عناوين (لا اختيار عنوان)",
              "headline" not in final_issue["body"].lower())

    card_only_saved = store.load_draft(cand_card_only["id"])
    now_card_saved = store.load_draft(cand_now_card["id"])
    draft_card_saved = store.load_draft(cand_draft_card["id"])
    triple_saved = store.load_draft(cand_triple["id"])

    check("مسودة 🎴 وحده صيغت وبُنيت بطاقتها فعلًا",
          card_only_saved is not None and bool(card_only_saved[1].get("image")),
          card_only_saved[1] if card_only_saved else None)
    check("مسودة 🚀+🎴 صيغت وبُنيت بطاقتها فعلًا (لم تُنشر مباشرة)",
          now_card_saved is not None and bool(now_card_saved[1].get("image"))
          and now_card_saved[1].get("status") != "published",
          now_card_saved[1] if now_card_saved else None)
    check("مسودة 📝+🎴 صيغت بلا بطاقة (تُبنى عند الاعتماد لاحقًا)",
          draft_card_saved is not None and "image" not in draft_card_saved[1],
          draft_card_saved[1] if draft_card_saved else None)
    check("مسودة الثلاثة معًا صيغت بلا بطاقة أيضًا",
          triple_saved is not None and "image" not in triple_saved[1],
          triple_saved[1] if triple_saved else None)

    rejections_after = feedback.load()
    new_entries = rejections_after[rejections_before:]
    check("رفض واحد فقط سُجِّل -- المرشح غير المعلَّم وحده",
          len(new_entries) == 1 and new_entries[0]["id"] == cand_none["id"]
          and new_entries[0]["tag"] == "لم يُختر", new_entries)
    check("مرشحو 🎴 (وحده أو مع غيره) لم يُسجَّلوا «لم يُختر»",
          not any(e["id"] in (cand_card_only["id"], cand_now_card["id"],
                              cand_draft_card["id"], cand_triple["id"])
                  for e in new_entries), new_entries)

def test_preselect_card_build_failure_keeps_pending() -> None:
    """Issue #860، البند 3 (قرارات محسومة): فشل بناء البطاقة لمسودة 🎴 —
    تبقى pending بلا image ويُعلَّق بالسبب على Issue الاختيار، فتلتقطها
    المراجعة الأولية التالية. لا Issue مراجعة نهائية يُفتح لها ولا تُسقَط."""
    from src import cards, collect_finalize, preselect, review
    from src import publish as publish_mod

    now = datetime.now(timezone.utc)
    art = Article(title="خبر 🎴 تفشل صناعة بطاقته",
                 link="https://pre.example/cardfail", summary="",
                 source_name="CF", region="rc", weight=1.0,
                 published=now, bucket="serious", publisher="CF")
    cand = preselect.build_candidate(art)
    store.save_candidate(cand)

    body = preselect.build_selection_issue_body([cand])
    marked = tick_marker(body, f"sel-card:{cand['id']}")

    real_ensure = cards.ensure
    ensure_calls: list = []
    cards.ensure = lambda *a, **kw: (ensure_calls.append(1), None)[1]

    create_issue_calls: list = []
    real_create_issue = review.create_issue
    review.create_issue = lambda title, body, labels=None: create_issue_calls.append(
        {"title": title, "labels": labels}) or {"number": 1, "html_url": "https://x/1"}

    comment_calls: list = []
    real_comment = review.comment
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))

    real_close = review.close_issue
    close_issue_calls: list = []
    review.close_issue = lambda issue_number: close_issue_calls.append(issue_number)

    real_burst = publish_mod.cmd_burst
    publish_mod.cmd_burst = lambda *a, **kw: 0

    try:
        code = collect_finalize.finalize(4861, marked, load_config())
    finally:
        cards.ensure = real_ensure
        review.create_issue = real_create_issue
        review.comment = real_comment
        review.close_issue = real_close
        publish_mod.cmd_burst = real_burst

    check("finalize انتهى بنجاح رغم فشل بناء البطاقة", code == 0, f"exit={code}")
    check("cards.ensure استُدعيت فعلًا", ensure_calls == [1], ensure_calls)
    check("لا Issue مراجعة نهائية فُتح للمسودة الفاشلة", create_issue_calls == [],
          create_issue_calls)

    saved = store.load_draft(cand["id"])
    check("المسودة صيغت فعلًا رغم فشل البطاقة", saved is not None)
    if saved:
        check("بقيت pending", saved[1].get("status") == "pending", saved[1].get("status"))
        check("بلا حقل image", "image" not in saved[1], saved[1].get("image"))

    failure_comments = [t for _, t in comment_calls if "تعذّر بناء بطاقة" in t]
    check("عُلِّق بسبب فشل البطاقة على Issue الاختيار",
          len(failure_comments) == 1, comment_calls)
    check("Issue الاختيار أُغلق (لا نشر مباشر متبقٍّ)",
          close_issue_calls == [4861], close_issue_calls)

def test_preselect_translate_titles() -> None:
    """استدعاء Haiku واحد للدفعة كلها، تخطّي العربي أصلًا بعتبة من
    config.yaml، تسجيل عدد المُترجَم والمتخطَّى، وفشل صامت لا يوقف
    المسار (تُعرض العناوين الأصلية بلا ترجمة)."""
    from src import preselect

    class _Block:
        def __init__(self, text):
            self.type = "text"
            self.text = text

    class _Resp:
        def __init__(self, content):
            self.content = content

    class _Messages:
        def __init__(self, resp):
            self._resp = resp
            self.calls = 0

        def create(self, **kw):
            self.calls += 1
            self.last_kwargs = kw
            return self._resp

    class _FakeClient:
        def __init__(self, resp):
            self.messages = _Messages(resp)

    cand_en1 = {"id": "t1", "title": "Volcano erupts in Iceland"}
    cand_en2 = {"id": "t2", "title": "Central bank raises interest rates"}
    cand_ar = {"id": "t3", "title": "زلزال يضرب اليابان"}   # عربي أصلًا — يُتخطّى

    resp = _Resp([_Block(
        '{"translations": {"1": "بركان يثور في آيسلندا", '
        '"2": "البنك المركزي يرفع الفائدة"}}')])
    fake_client = _FakeClient(resp)

    cfg = load_config()
    cfg["preselect"] = {
        "translate": {"enabled": True, "model": "claude-haiku-4-5-20251001",
                      "arabic_skip_ratio": 0.4},
    }

    real_client = preselect._client
    preselect._client = lambda: fake_client
    try:
        translations = preselect.translate_titles(
            [cand_en1, cand_en2, cand_ar], cfg)
    finally:
        preselect._client = real_client

    check("استدعاء واحد فقط للدفعة كلها (لا استدعاء لكل عنوان)",
          fake_client.messages.calls == 1, str(fake_client.messages.calls))
    check("العنوان العربي أصلًا لم يُرسَل ضمن الدفعة",
          "زلزال" not in fake_client.messages.last_kwargs["messages"][0]["content"])
    check("العنوانان الإنجليزيان تُرجما", translations == {
        "t1": "بركان يثور في آيسلندا", "t2": "البنك المركزي يرفع الفائدة"})
    check("العنوان العربي أصلًا بلا ترجمة (تُخطّي لا فشل)", "t3" not in translations)

    # عتبة arabic_skip_ratio من config.yaml لا من الكود: عتبة 0.0 تعني "لا
    # عنوان غير عربي كفاية للترجمة" — حتى العنوان الإنجليزي البحت (نسبته
    # العربية 0.0) يُستبعد لأن الفحص شرطه < العتبة لا ≤، فيثبت أن العتبة
    # الفعلية المستخدمة هي قيمة config.yaml لا القيمة الافتراضية 0.4 التي
    # كانت سترسله.
    cfg_zero = load_config()
    cfg_zero["preselect"] = {"translate": {"enabled": True, "arabic_skip_ratio": 0.0}}
    fake_client2 = _FakeClient(_Resp([_Block('{"translations": {}}')]))
    preselect._client = lambda: fake_client2
    try:
        result_zero = preselect.translate_titles([cand_en1], cfg_zero)
    finally:
        preselect._client = real_client
    check("عتبة arabic_skip_ratio=0.0 من config.yaml تمنع حتى الإنجليزي من الترجمة",
          fake_client2.messages.calls == 0 and result_zero == {},
          str((fake_client2.messages.calls, result_zero)))

    # تعطيل الترجمة من config.yaml بلا أي تعديل كود
    cfg_off = load_config()
    cfg_off["preselect"] = {"translate": {"enabled": False}}
    check("enabled: false لا يستدعي أي عميل",
          preselect.translate_titles([cand_en1], cfg_off) == {})

    # فشل الاستدعاء (عطل API) لا يوقف المسار — يعيد {} بصمت
    def _raise(*a, **kw):
        raise RuntimeError("متغير البيئة ANTHROPIC_API_KEY غير موجود")

    preselect._client = _raise
    try:
        result = preselect.translate_titles([cand_en1], cfg)
    finally:
        preselect._client = real_client
    check("فشل الاستدعاء يعيد {} بصمت بلا استثناء يوقف المسار", result == {})

def test_finalize_format_mismatch_no_silent_fail() -> None:
    """جسم Issue بلا أي معرّف <!-- cand:ID --> إطلاقًا (صيغة "مسودات" لا
    "مرشحين" — أحد أعراض Issue #296: وسم pending-selection على Issue من
    نوع آخر) يجب ألا يُعامَل كأن المراجع لم يعلّم شيئًا. يجب تعليق سبب
    واضح وعدم إزالة approved — إزالته كانت ستُخفي العطل صامتًا."""
    from src import collect_finalize, review

    comment_calls, remove_label_calls = [], []
    real_comment = review.comment
    real_remove_label = review.remove_label
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))
    review.remove_label = lambda issue_number, label: remove_label_calls.append(
        (issue_number, label))

    body = "- [x] **1. عنوان مسودة عادية جاهزة للنشر**  <!-- draft:abc123 -->"

    try:
        code = collect_finalize.finalize(6161, body, load_config())
    finally:
        review.comment = real_comment
        review.remove_label = real_remove_label

    check("finalize يعيد رمز فشل عند عدم تطابق الصيغة", code != 0, f"exit={code}")
    check("تعليق بسبب واضح يذكر «صيغة»",
          bool(comment_calls) and comment_calls[0][0] == 6161
          and "صيغة" in comment_calls[0][1], str(comment_calls))
    check("approved لا يُزال عند عدم تطابق الصيغة (لا يُخفى العطل)",
          remove_label_calls == [])

def test_publish_conflicting_labels_no_dispatch() -> None:
    """Issue يحمل pending-selection وpending-review معًا (Issue #296) —
    التفويض القديم كان يفوز لـ pending-selection بلا شرط، فيتجاهل
    pending-review بصمت. الآن يُرفض الحسم التلقائي وتُعلَّق تنبيه صريح."""
    from src import publish
    from src import collect_finalize as cf_mod
    from src import review

    real_fetch = publish.fetch_issue
    publish.fetch_issue = lambda n: {
        "number": n,
        "body": "لا يهم لهذا الاختبار",
        "labels": [{"name": "pending-selection"}, {"name": "pending-review"},
                   {"name": "approved"}],
    }

    comment_calls: list = []
    real_comment = review.comment
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))

    finalize_calls: list = []
    real_finalize = cf_mod.finalize
    cf_mod.finalize = lambda *a, **kw: finalize_calls.append(1) or 0

    sys.argv = ["publish", "--issue", "9001"]
    try:
        code = publish.main()
    finally:
        publish.fetch_issue = real_fetch
        review.comment = real_comment
        cf_mod.finalize = real_finalize

    check("publish يرفض التفويض عند تعارض الوسمين", code != 0, f"exit={code}")
    check("لا استدعاء لـ collect_finalize.finalize", finalize_calls == [])
    check("تعليق تنبيه صريح على الـ Issue بدل الصمت",
          len(comment_calls) == 1 and comment_calls[0][0] == 9001)

def test_writer_classifies_write_errors() -> None:
    """Issue #308 البند 1: تصنيف سبب فشل الصياغة التقني — دالة مستقلة قابلة
    للاختبار بلا شبكة ولا عميل Anthropic حقيقي."""
    from src.writer import classify_write_error

    check("رسالة سقف الإنفاق تُصنَّف بدقة",
          classify_write_error(
              Exception("You have reached your specified API usage limits"))
          == "سقف الإنفاق")
    check("رسالة رصيد منخفض تُصنَّف كسقف إنفاق أيضًا",
          classify_write_error(Exception("Your credit balance is too low"))
          == "سقف الإنفاق")
    check("عطل API عام بلا إشارة لسقف الإنفاق يُصنَّف عامًا",
          classify_write_error(Exception("Internal server error, try again"))
          == "عطل API")

def test_finalize_external_failure_keeps_approved_no_feedback() -> None:
    """Issue #308 البند 1+2: فشل الصياغة لعطل خارجي (سقف إنفاق/API) يجب أن
    يذكر السبب صراحة في التعليق، يُبقي وسم approved (لا يُخفي العطل بإزالته
    وكأنه رفض تحريري)، ولا يُسجَّل المرشح المعتمد في feedback — العطل عارض
    تقني لا قرار بشري، وتسجيله يعلّم الفرز الأولي درسًا خاطئًا."""
    from src import collect_finalize, feedback, preselect, review
    from src.writer import WriteFailure

    now = datetime.now(timezone.utc)
    art_d = Article(title="خبر رابع يصطدم بسقف الإنفاق عند الصياغة",
                    link="https://pre.example/d", summary="", source_name="P4",
                    region="r4", weight=1.0, published=now, bucket="serious",
                    publisher="P4")
    cand_d = preselect.build_candidate(art_d)
    store.save_candidate(cand_d)

    body = preselect.build_selection_issue_body([cand_d])
    marked = tick_marker(body, f"now:{cand_d['id']}")

    comment_calls, remove_label_calls = [], []
    real_comment = review.comment
    real_remove_label = review.remove_label
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))
    review.remove_label = lambda issue_number, label: remove_label_calls.append(
        (issue_number, label))

    real_write = collect_finalize.write_arabic

    def _raise_write_failure(*a, **kw):
        raise WriteFailure("سقف الإنفاق",
                           "You have reached your specified API usage limits")

    collect_finalize.write_arabic = _raise_write_failure

    rejections_before = len(feedback.load())

    try:
        code = collect_finalize.finalize(8001, marked, load_config())
    finally:
        collect_finalize.write_arabic = real_write
        review.comment = real_comment
        review.remove_label = real_remove_label

    check("finalize يعيد رمز فشل عند عطل خارجي", code != 0, f"exit={code}")
    check("approved لا يُزال عند فشل خارجي", remove_label_calls == [])
    check("التعليق يذكر السبب صراحة (سقف الإنفاق)",
          bool(comment_calls) and "سقف الإنفاق" in comment_calls[0][1],
          str(comment_calls))
    check("لا تسجيل جديد في feedback عند فشل خارجي",
          len(feedback.load()) == rejections_before)

    updated_d = store.load_candidate(cand_d["id"])
    check("حالة المرشح لم تتحوّل إلى write_failed عند عطل خارجي",
          updated_d and updated_d[1]["status"] == "pending",
          str(updated_d[1]["status"] if updated_d else None))

def test_finalize_editorial_rejection_removes_approved() -> None:
    """Issue #308 البند 1+2 (تباين ضابط): الرفض التحريري البحت (newsworthy
    =false، يعاد None بلا استثناء) يبقى بالسلوك السابق — يُزال approved
    لأنه قرار بشري منته يحتاج اختيار مرشح آخر، لا عطل يستحق إعادة محاولة."""
    from src import collect_finalize, preselect, review

    now = datetime.now(timezone.utc)
    art_e = Article(title="خبر خامس يرفضه النموذج تحريريًا",
                    link="https://pre.example/e", summary="", source_name="P5",
                    region="r5", weight=1.0, published=now, bucket="light",
                    publisher="P5")
    cand_e = preselect.build_candidate(art_e)
    store.save_candidate(cand_e)

    body = preselect.build_selection_issue_body([cand_e])
    marked = tick_marker(body, f"now:{cand_e['id']}")

    comment_calls, remove_label_calls = [], []
    real_comment = review.comment
    real_remove_label = review.remove_label
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))
    review.remove_label = lambda issue_number, label: remove_label_calls.append(
        (issue_number, label))

    real_write = collect_finalize.write_arabic
    collect_finalize.write_arabic = lambda *a, **kw: None

    try:
        code = collect_finalize.finalize(8002, marked, load_config())
    finally:
        collect_finalize.write_arabic = real_write
        review.comment = real_comment
        review.remove_label = real_remove_label

    check("finalize ينتهي بنجاح عند رفض تحريري بحت", code == 0, f"exit={code}")
    check("approved يُزال عند رفض تحريري (قرار بشري لا عطل)",
          remove_label_calls == [(8002, "approved")])
    check("التعليق لا يذكر سببًا خارجيًا",
          bool(comment_calls) and "سقف الإنفاق" not in comment_calls[0][1]
          and "عطل API" not in comment_calls[0][1], str(comment_calls))

    updated_e = store.load_candidate(cand_e["id"])
    check("حالة المرشح write_failed عند رفض تحريري",
          updated_e and updated_e[1]["status"] == "write_failed",
          str(updated_e[1]["status"] if updated_e else None))

def test_publish_pending_selection_single_dispatch() -> None:
    """Issue #308 البند 3 (الأهم): publish.yml يُشغّل مساري urgent وnormal
    لنفس حدث وسم approved معًا — كلاهما يستدعي publish.main() لنفس Issue
    pending-selection. finalize لا يميّز عاجلًا من عادي داخليًا (ينشر
    الاثنين معًا في تفويضة واحدة)، فتنفيذه مرتين يعني صياغة الخبر ونشره
    مرتين فعليًا لو نجحا معًا. مسار العادي (--skip-urgent) يجب أن يتخطّى
    finalize تمامًا ويترك المسار السريع (بلا --skip-urgent) ينفّذه وحده."""
    from src import publish
    from src import collect_finalize as cf_mod

    real_fetch = publish.fetch_issue
    publish.fetch_issue = lambda n: {
        "number": n,
        "body": "لا يهم لهذا الاختبار",
        "labels": [{"name": "pending-selection"}, {"name": "approved"}],
    }

    finalize_calls: list = []
    real_finalize = cf_mod.finalize
    cf_mod.finalize = lambda *a, **kw: finalize_calls.append(1) or 0

    try:
        # محاكاة تشغيلتي publish.yml لنفس حدث الوسم: العاجل أولًا (بلا
        # skip-urgent)، ثم العادي (needs: urgent) بـ --skip-urgent
        sys.argv = ["publish", "--issue", "7001", "--urgent-only"]
        code_urgent = publish.main()
        sys.argv = ["publish", "--issue", "7001", "--skip-urgent"]
        code_normal = publish.main()
    finally:
        publish.fetch_issue = real_fetch
        cf_mod.finalize = real_finalize

    check("مسار العاجل ينتهي بنجاح", code_urgent == 0, f"exit={code_urgent}")
    check("مسار العادي يتخطّى بنجاح بلا خطأ", code_normal == 0, f"exit={code_normal}")
    check("finalize نُفِّذ مرة واحدة فقط رغم تشغيل المسارين معًا",
          finalize_calls == [1], str(finalize_calls))

def test_manual_image() -> None:
    """صورة يدوية: أمر التعليق، ومسار جديد، وتلميح في الـ Issue."""
    from src import review, setimage

    cmds = setimage.parse_commands(
        "ممتاز /صورة a1b2c3d4e5f6 https://ex.com/p.jpg شكرًا")
    check("الأمر يُقرأ من وسط التعليق",
          cmds == [("a1b2c3d4e5f6", "https://ex.com/p.jpg")])
    check("الصيغة الإنجليزية مقبولة",
          setimage.parse_commands("/image abc123def456 https://ex.com/x.png")
          == [("abc123def456", "https://ex.com/x.png")])
    check("القوس اللاصق يُقصّ من الرابط",
          setimage.parse_commands("(/صورة abc123def456 https://ex.com/x.png)")
          [0][1].endswith(".png"))
    check("التعليق بلا أمر لا يُنتج شيئًا",
          setimage.parse_commands("صورة جميلة جدًا") == [])

    check("المسار الجديد لا يستبدل القديم",
          setimage.next_image_path("drafts/d/ab.jpg") == "drafts/d/ab-v2.jpg")
    check("النسخ تتتابع",
          setimage.next_image_path("drafts/d/ab-v2.jpg") == "drafts/d/ab-v3.jpg")

    base = {"id": "abc123def456", "score": 9.0, "caption": "متن",
            "image": "drafts/d/abc123def456.jpg", "bucket": "serious",
            "source": {"link": "https://x/1", "publishers": ["BBC"]},
            "arabic": {"post_title": "عنوان", "category": "سياسة"}}

    body = review.build_issue_body([{**base, "has_photo": False}], "u/r")
    check("مربع الاستبدال معروض", "<!-- img:abc123def456 -->" in body)
    check("فراغ الرابط معروض", "<!-- imgurl:abc123def456 -->" in body)
    check("المربع قابل للنقر (خارج <details>)",
          any("- [ ]" in ln and "img:abc123def456" in ln
              for ln in body.splitlines()))
    check("تنبيه غياب الصورة يظهر", "بلا صورة للخبر" in body)
    check("لا تنبيه حين توجد صورة",
          "بلا صورة للخبر" not in
          review.build_issue_body([{**base, "has_photo": True}], "u/r"))

    check("المربع الفارغ لا يُنفَّذ", review.parse_image_requests(body) == [])
    ticked = body.replace("- [ ] 🖼️ استبدل", "- [x] 🖼️ استبدل")
    check("مربع معلَّم بلا رابط يُهمَل",
          review.parse_image_requests(ticked) == [])

    filled = ticked.replace(
        "الرابط:   <!-- imgurl:abc123def456 -->",
        "الرابط: https://cdn.site/p.jpg  <!-- imgurl:abc123def456 -->")
    check("المربع المعلَّم مع الرابط يُنفَّذ",
          review.parse_image_requests(filled)
          == [("abc123def456", "https://cdn.site/p.jpg")])

    # اللصق قبل العلامة أو بعدها — كلاهما يعمل على الهاتف
    after = ticked.replace(
        "الرابط:   <!-- imgurl:abc123def456 -->",
        "الرابط: <!-- imgurl:abc123def456 --> https://cdn.site/p.jpg")
    check("موضع اللصق لا يهم",
          review.parse_image_requests(after)
          == [("abc123def456", "https://cdn.site/p.jpg")])

    cleared = review.clear_image_request(filled, "abc123def456")
    check("المربع يُفرَّغ بعد التنفيذ",
          review.parse_image_requests(cleared) == [])
    check("الفراغ يُنظَّف من الرابط", "cdn.site" not in cleared)
    kept = review.clear_image_request(filled, "abc123def456", keep_url=True)
    check("الرابط يبقى عند الفشل ليصحَّح", "cdn.site" in kept)
    check("لا تكرار عند الفشل", review.parse_image_requests(kept) == [])

def test_editable_caption_and_image_source() -> None:
    """Issue #752: تعديل نصّ أي منشور داخل Issue المراجعة نفسه، ورؤية مصدر
    صورته قبل الاعتماد — في مساري الأخبار والتحليل معًا. يغطّي: تسامح
    review.parse_captions مع اختلاف المسافات البادئة، تطبيق التعديل في
    publish.main قبل فصل analysis_ids/news_ids (نصّ غير معدَّل لا يكتب
    شيئًا، ومعدَّل يُحفَظ ويصل publish_one)، وصول النصّ المحرَّر إلى
    youtube_publish._apply_headline لمسار التحليل تحديدًا (الترتيب الذي
    طلبته المهمة)، وreview.image_source_line في حالاتها الست (تصحيح Issue
    #756 على #752) بما فيها مسودة قديمة فعليًا بلا image_info، وبطاقة تحليل
    لم تُبنَ بعد بعد (غياب image_info وimage معًا -- Issue #680)."""
    from src import publish as publish_mod
    from src import youtube_publish as yp

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── parse_captions: تسامح المحاذاة (مسافتان، بلا مسافات، مسافات زائدة) ──
    body_two_spaces = (
        "  <!-- cap:abc123abcdef -->\n"
        "  ```\n"
        "  السطر الأول\n"
        "  السطر الثاني\n"
        "  ```\n"
        "  <!-- /cap:abc123abcdef -->\n"
    )
    check("parse_captions: مسافتان بادئتان قياسيتان",
          review.parse_captions(body_two_spaces) ==
          {"abc123abcdef": "السطر الأول\nالسطر الثاني"},
          review.parse_captions(body_two_spaces))

    body_no_spaces = (
        "<!-- cap:abc123abcdef -->\n"
        "```\n"
        "السطر الأول\n"
        "السطر الثاني\n"
        "```\n"
        "<!-- /cap:abc123abcdef -->\n"
    )
    check("parse_captions: بلا أي مسافة بادئة (اختفت أثناء التحرير على الهاتف)",
          review.parse_captions(body_no_spaces) ==
          {"abc123abcdef": "السطر الأول\nالسطر الثاني"},
          review.parse_captions(body_no_spaces))

    body_extra_spaces = (
        "  <!-- cap:abc123abcdef -->\n"
        "    ```\n"
        "    السطر الأول\n"
        "    السطر الثاني\n"
        "    ```\n"
        "  <!-- /cap:abc123abcdef -->\n"
    )
    check("parse_captions: مسافات زائدة تُقشَّر حتى اثنتين فقط لا أكثر "
          "(إزاحة أعمق قد تكون مقصودة في النص نفسه)",
          review.parse_captions(body_extra_spaces) ==
          {"abc123abcdef": "  السطر الأول\n  السطر الثاني"},
          review.parse_captions(body_extra_spaces))

    check("parse_captions: بلا كتلة cap إطلاقًا يعيد قاموسًا فارغًا",
          review.parse_captions("نص Issue بلا أي كتلة نصّ") == {})

    # ── image_source_line: الحالات الست (تصحيح Issue #756 على #752) ──
    check("image_source_line: يدوية",
          review.image_source_line({"image_info": {
              "manual": True, "used_original": True, "illustrative": False,
              "composite": False, "chosen_url": "https://x/m.jpg"}})
          == "🖼️ **المصدر:** رابط وضعتَه يدويًا — المسؤولية عليك")
    check("image_source_line: ناشر (صورة واحدة، بلا تركيب)",
          review.image_source_line({"image_info": {
              "used_original": True, "illustrative": False, "composite": False}})
          == "🖼️ **المصدر:** صورة الناشر — أصلية")
    check("image_source_line: ناشر مع تركيب صورتين",
          review.image_source_line({"image_info": {
              "used_original": True, "illustrative": False, "composite": True}})
          == "🖼️ **المصدر:** صورة الناشر — أصلية · مدمجة من صورتين")
    check("image_source_line: تعبيرية حرة",
          review.image_source_line({"image_info": {
              "used_original": True, "illustrative": True, "composite": False}})
          == "🖼️ **المصدر:** صورة تعبيرية حرة (ويكيميديا/Openverse) — ليست من مكان الحدث")
    check("image_source_line: بلا صورة (خلفية مصممة)",
          review.image_source_line({"image_info": {
              "used_original": False, "illustrative": False, "composite": False}})
          == "🖼️ **المصدر:** بلا صورة — البطاقة على خلفية مصممة")
    check("image_source_line: غياب image_info وimage معًا -- بطاقة لم تُبنَ بعد "
          "(مسودة تحليل قبل الاعتماد، Issue #680)، لا مسودة سابقة",
          review.image_source_line({"has_photo": True}) ==
          "🖼️ **المصدر:** البطاقة لم تُبنَ بعد — تُبنى عند الاعتماد")
    check("image_source_line: غياب image_info مع وجود image -- مسودة سابقة فعليًا "
          "(من قبل حقل image_info)",
          review.image_source_line({"has_photo": True, "image": "drafts/x.jpg"}) ==
          "🖼️ **المصدر:** غير مسجَّل (مسودة سابقة)")

    # ── نصّ غير معدَّل عبر build_issue_body/publish.main لا يكتب شيئًا ──
    news_draft = {
        "id": "ca1100000001", "status": "pending", "score": 5.0, "bucket": "serious",
        "state_media": False, "image": "drafts/cap1.jpg",
        "caption": "نص الخبر الأصلي.",
        "source": {"link": "https://x/1", "publishers": ["BBC"]},
        "arabic": {"post_title": "عنوان الخبر", "category": "سياسة", "urgent": False},
    }
    store.save_draft(news_draft)
    (DRAFTS_DIR / "cap1.jpg").write_bytes(b"\xff\xd8\xff")

    body_unedited = review.build_issue_body([news_draft], "u/r", "main")
    check("build_issue_body: كتلة cap محفوفة بعلامتي البداية والنهاية",
          f"<!-- cap:{news_draft['id']} -->" in body_unedited and
          f"<!-- /cap:{news_draft['id']} -->" in body_unedited, None)
    check("build_issue_body: التلميح الجديد لتعديل النص ظاهر، والقديم (فتح ملف json) غائب",
          "حرّر هذا الـIssue واكتب داخل كتلة النص مباشرة" in body_unedited and
          "افتح ملف" not in body_unedited, None)
    check("build_issue_body: سطر مصدر الصورة ظاهر تحت سطر الشارات",
          "🖼️ **المصدر:** غير مسجَّل (مسودة سابقة)" in body_unedited, body_unedited)
    marked_unedited = body_unedited.replace("- [ ] **1.", "- [x] **1.", 1)

    real_fetch = publish_mod.fetch_issue
    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    real_comment = review.comment
    real_close = review.close_issue
    publish_mod.ROOT = DRAFTS_DIR.parent
    publish_calls: list = []

    def fake_publish_photo(image_path, caption, api_version, first_comment=None):
        publish_calls.append(caption)
        return {"url": "https://fb.example/1", "id": "1"}

    facebook.publish_photo = fake_publish_photo
    comments: list = []
    review.comment = lambda issue_number, text: comments.append(text)
    review.close_issue = lambda issue_number: None

    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": marked_unedited, "labels": [{"name": "approved"}]}
    sys.argv = ["publish", "--issue", "9001", "--now"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch

    check("publish.main (نص غير معدَّل): ينتهي بنجاح", code == 0, f"exit={code}")
    check("نص غير معدَّل: caption_edited غائب بعد النشر",
          "caption_edited" not in store.load_draft(news_draft["id"])[1],
          store.load_draft(news_draft["id"])[1])
    check("نص غير معدَّل: النص المنشور فعليًا مطابق للأصلي",
          publish_calls == ["نص الخبر الأصلي."], publish_calls)

    # ── عناوين مقترحة لمسار الأخبار (Issue #756) — عرض وقراءة وتطبيق ──
    hl_news_draft = {
        "id": "ca4400000004", "status": "pending", "score": 5.0, "bucket": "serious",
        "state_media": False, "image": "drafts/cap4.jpg",
        "caption": "عنوان تجريبي فقط\nمتن الخبر التجريبي.",
        "source": {"link": "https://x/4", "publishers": ["BBC"]},
        "arabic": {"post_title": "عنوان تجريبي فقط", "category": "سياسة", "urgent": False},
        "headlines": ["هل يتصاعد الموقف؟", "بديل أول تقريري", "بديل ثانٍ ترجيحي"],
        "headline_selected": 0,
    }
    store.save_draft(hl_news_draft)
    (DRAFTS_DIR / "cap4.jpg").write_bytes(b"\xff\xd8\xff")

    no_hl_draft = {
        "id": "ca5500000005", "status": "pending", "score": 5.0, "bucket": "serious",
        "state_media": False, "image": "drafts/cap5.jpg",
        "caption": "خبر بلا عناوين مقترحة.",
        "source": {"link": "https://x/5", "publishers": ["BBC"]},
        "arabic": {"post_title": "خبر بلا عناوين مقترحة", "category": "سياسة", "urgent": False},
        "headlines": [],
    }
    store.save_draft(no_hl_draft)
    (DRAFTS_DIR / "cap5.jpg").write_bytes(b"\xff\xd8\xff")

    body_hl = review.build_issue_body([hl_news_draft, no_hl_draft], "u/r", "main")
    check("build_issue_body: مسودة بعناوين مقترحة تعرض المربعات الثلاثة",
          f"<!-- hl:{hl_news_draft['id']}:0 -->" in body_hl and
          f"<!-- hl:{hl_news_draft['id']}:1 -->" in body_hl and
          f"<!-- hl:{hl_news_draft['id']}:2 -->" in body_hl, body_hl)
    check("build_issue_body: العنوان الأول معلَّم افتراضيًا",
          f"- [x] 1. هل يتصاعد الموقف؟  <!-- hl:{hl_news_draft['id']}:0 -->" in body_hl, body_hl)
    check("build_issue_body: سطر «علّم واحدًا» ظاهر فوق المربعات",
          "📰 **العنوان:** علّم واحدًا" in body_hl, body_hl)
    check("build_issue_body: مسودة بقائمة عناوين فارغة لا تعرض أي مربع hl إطلاقًا",
          f"<!-- hl:{no_hl_draft['id']}:" not in body_hl, body_hl)
    check("build_issue_body: جملة التعارض (تحرير + عنوان معًا) ظاهرة في التعليمات",
          "لو عدّلت النص وعلّمت عنوانًا معًا" in body_hl, body_hl)

    # اختيار عنوان بديل (الفهرس ١) بلا تعديل نصّ -- يستبدل السطر الأول فقط
    # ويحدّث arabic.post_title وheadline_selected
    marked_hl = body_hl.replace("- [ ] **1.", "- [x] **1.", 1)
    marked_hl = marked_hl.replace(
        f"- [x] 1. هل يتصاعد الموقف؟  <!-- hl:{hl_news_draft['id']}:0 -->",
        f"- [ ] 1. هل يتصاعد الموقف؟  <!-- hl:{hl_news_draft['id']}:0 -->")
    marked_hl = marked_hl.replace(
        f"- [ ] 2. بديل أول تقريري  <!-- hl:{hl_news_draft['id']}:1 -->",
        f"- [x] 2. بديل أول تقريري  <!-- hl:{hl_news_draft['id']}:1 -->")

    publish_calls.clear()
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": marked_hl, "labels": [{"name": "approved"}]}
    sys.argv = ["publish", "--issue", "9004", "--now"]
    try:
        code4 = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch

    persisted4 = store.load_draft(hl_news_draft["id"])[1]
    check("publish.main (اختيار عنوان بديل): ينتهي بنجاح", code4 == 0, f"exit={code4}")
    check("اختيار عنوان بديل: caption المخزَّن باستبدال السطر الأول فقط",
          persisted4.get("caption") == "بديل أول تقريري\nمتن الخبر التجريبي.", persisted4)
    check("اختيار عنوان بديل: arabic.post_title تحدَّث للعنوان المختار",
          persisted4.get("arabic", {}).get("post_title") == "بديل أول تقريري", persisted4)
    check("اختيار عنوان بديل: headline_selected=1 محفوظ", persisted4.get("headline_selected") == 1,
          persisted4)
    check("اختيار عنوان بديل: النص المنشور فعليًا يحمل العنوان الجديد",
          publish_calls == ["بديل أول تقريري\nمتن الخبر التجريبي."], publish_calls)

    # تعديل النص يدويًا واختيار عنوان معًا -- الترتيب الملزم: التحرير أولًا
    # ثم العنوان المختار يستبدل السطر الأول من النص *المحرَّر* لا الأصلي
    hl_edit_draft = {
        "id": "ca6600000006", "status": "pending", "score": 5.0, "bucket": "serious",
        "state_media": False, "image": "drafts/cap6.jpg",
        "caption": "عنوان قديم\nمتن قديم.",
        "source": {"link": "https://x/6", "publishers": ["BBC"]},
        "arabic": {"post_title": "عنوان قديم", "category": "سياسة", "urgent": False},
        "headlines": ["هل يحدث كذا؟", "بديل تقريري", "بديل ترجيحي"],
        "headline_selected": 0,
    }
    store.save_draft(hl_edit_draft)
    (DRAFTS_DIR / "cap6.jpg").write_bytes(b"\xff\xd8\xff")

    body_hl2 = review.build_issue_body([hl_edit_draft], "u/r", "main")
    marked_hl2 = body_hl2.replace("- [ ] **1.", "- [x] **1.", 1)
    marked_hl2 = marked_hl2.replace(
        f"- [x] 1. هل يحدث كذا؟  <!-- hl:{hl_edit_draft['id']}:0 -->",
        f"- [ ] 1. هل يحدث كذا؟  <!-- hl:{hl_edit_draft['id']}:0 -->")
    marked_hl2 = marked_hl2.replace(
        f"- [ ] 2. بديل تقريري  <!-- hl:{hl_edit_draft['id']}:1 -->",
        f"- [x] 2. بديل تقريري  <!-- hl:{hl_edit_draft['id']}:1 -->")
    edited_hl2 = marked_hl2.replace("متن قديم.", "متن محرَّر يدويًا أيضًا.")

    publish_calls.clear()
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": edited_hl2, "labels": [{"name": "approved"}]}
    sys.argv = ["publish", "--issue", "9005", "--now"]
    try:
        code5 = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch

    persisted5 = store.load_draft(hl_edit_draft["id"])[1]
    check("publish.main (تحرير + اختيار عنوان معًا): ينتهي بنجاح", code5 == 0, f"exit={code5}")
    check("تحرير + عنوان معًا: النص المحرَّر بسطره الأول مستبدَلًا بالعنوان المختار",
          persisted5.get("caption") == "بديل تقريري\nمتن محرَّر يدويًا أيضًا.", persisted5)
    check("تحرير + عنوان معًا: النص المنشور فعليًا يطابق ذلك",
          publish_calls == ["بديل تقريري\nمتن محرَّر يدويًا أيضًا."], publish_calls)

    # ── نصّ معدَّل يُحفَظ فعليًا ويصل publish_one (لا الأصلي) ──
    news_draft2 = {
        "id": "ca2200000002", "status": "pending", "score": 5.0, "bucket": "serious",
        "state_media": False, "image": "drafts/cap2.jpg",
        "caption": "نص الخبر الأصلي الثاني.",
        "source": {"link": "https://x/2", "publishers": ["BBC"]},
        "arabic": {"post_title": "عنوان الخبر الثاني", "category": "سياسة", "urgent": False},
    }
    store.save_draft(news_draft2)
    (DRAFTS_DIR / "cap2.jpg").write_bytes(b"\xff\xd8\xff")

    body2 = review.build_issue_body([news_draft2], "u/r", "main")
    marked2 = body2.replace("- [ ] **1.", "- [x] **1.", 1)
    edited2 = marked2.replace("نص الخبر الأصلي الثاني.", "نص محرَّر يدويًا في الـIssue.")

    publish_calls.clear()
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": edited2, "labels": [{"name": "approved"}]}
    sys.argv = ["publish", "--issue", "9002", "--now"]
    try:
        code2 = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo

    persisted2 = store.load_draft(news_draft2["id"])[1]
    check("publish.main (نص معدَّل): ينتهي بنجاح", code2 == 0, f"exit={code2}")
    check("نص معدَّل: caption_edited=True", persisted2.get("caption_edited") is True, persisted2)
    check("نص معدَّل: caption المخزَّن يطابق التعديل لا الأصل",
          persisted2.get("caption") == "نص محرَّر يدويًا في الـIssue.", persisted2)
    check("نص معدَّل: publish_one نشر النص الجديد لا الأصلي",
          publish_calls == ["نص محرَّر يدويًا في الـIssue."], publish_calls)

    # ── مسودة تحليل معدَّلة النص: التعديل يصل youtube_publish._apply_headline ──
    yt_draft = {
        "id": "ca3abcdefabc", "status": "pending", "origin": "youtube",
        "arabic": {"post_title": "العنوان الافتراضي", "urgent": False},
        "headlines": ["العنوان الافتراضي", "بديل ١", "بديل ٢"], "headline_selected": 0,
        "caption": "# العنوان الافتراضي\nنص المقال الأصلي.",
        "channels": ["قناة تجريبية"], "source": {},
    }
    store.save_draft(yt_draft)

    yt_body = (
        f"- [x] **1. مقال**  <!-- draft:{yt_draft['id']} -->\n"
        f"  <!-- cap:{yt_draft['id']} -->\n"
        "  ```\n"
        "  # العنوان الافتراضي\n"
        "  نص محرَّر يدويًا قبل الاعتماد.\n"
        "  ```\n"
        f"  <!-- /cap:{yt_draft['id']} -->\n"
    )
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": yt_body, "labels": [{"name": "approved"}]}

    apply_headline_calls: list = []
    real_apply_headline = yp._apply_headline

    def spy_apply_headline(caption, headline):
        apply_headline_calls.append(caption)
        return real_apply_headline(caption, headline)

    yp._apply_headline = spy_apply_headline

    real_find_images = imagesearch.find_images
    imagesearch.find_images = lambda *a, **k: []

    real_publish_one_yt = yp.publish.publish_one
    published_captions: list = []

    def fake_publish_one_yt(path, draft, cfg):
        published_captions.append(draft["caption"])
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['id']}"

    yp.publish.publish_one = fake_publish_one_yt
    review.comment = lambda issue_number, text: comments.append(text)
    review.close_issue = lambda issue_number: None

    sys.argv = ["publish", "--issue", "9003"]
    try:
        code3 = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        yp._apply_headline = real_apply_headline
        imagesearch.find_images = real_find_images
        yp.publish.publish_one = real_publish_one_yt
        review.comment = real_comment
        review.close_issue = real_close

    check("publish.main (مقال تحليل، نص معدَّل): ينتهي بنجاح", code3 == 0, f"exit={code3}")
    check("التعديل وصل _apply_headline بالنصّ الجديد لا الأصلي (الترتيب المطلوب في المهمة)",
          apply_headline_calls == ["# العنوان الافتراضي\nنص محرَّر يدويًا قبل الاعتماد."],
          apply_headline_calls)
    check("caption المنشورة فعليًا (بعد استبدال سطر العنوان) تحمل النصّ المحرَّر",
          published_captions and "نص محرَّر يدويًا قبل الاعتماد." in published_captions[0],
          published_captions)
    check("مسودة التحليل على القرص: caption_edited=True",
          store.load_draft(yt_draft["id"])[1].get("caption_edited") is True,
          store.load_draft(yt_draft["id"])[1])

def test_setimage_revives_failed_draft_only_when_image_was_the_cause() -> None:
    """Issue #742: `failed` ليست نهائية إن زال سببها. `/صورة` الناجح يعيد
    الحالة إلى `pending` ويمسح `error` فقط إن كان الفشل الأصلي بسبب الصورة
    تحديدًا (حقول مفقودة تضم image، أو "الصورة مفقودة") — أي سبب آخر
    (استثناء فيسبوك مثلًا) يبقى failed لأن السبب الفعلي لم يزُل."""
    from src import setimage

    cfg = load_config()

    def make_failed(draft_id: str, error: str) -> dict:
        return {
            "id": draft_id, "score": 5.0, "caption": "متن",
            "image": f"drafts/d/{draft_id}.jpg", "bucket": "serious",
            "status": "failed", "error": error,
            "source": {"link": "https://x/1", "publishers": ["BBC"]},
            "arabic": {"post_title": "عنوان تجريبي", "category": "سياسة"},
        }

    missing_image = make_failed("f1000000f1f1", "حقول مفقودة: image")
    missing_image_multi = make_failed("f2000000f2f2", "حقول مفقودة: caption, image")
    missing_photo = make_failed("f3000000f3f3", "الصورة مفقودة")
    other_cause = make_failed("f4000000f4f4", "خطأ فيسبوك: (#1) الخدمة غير متاحة")
    for d in (missing_image, missing_image_multi, missing_photo, other_cause):
        store.save_draft(d)

    check("_image_related_failure: حقول مفقودة تضم image",
          setimage._image_related_failure("حقول مفقودة: image"))
    check("_image_related_failure: حقول مفقودة تضم image ضمن أكثر من حقل",
          setimage._image_related_failure("حقول مفقودة: caption, image"))
    check("_image_related_failure: الصورة مفقودة",
          setimage._image_related_failure("الصورة مفقودة"))
    check("_image_related_failure: سبب آخر لا يُحيي",
          not setimage._image_related_failure("خطأ فيسبوك: (#1) الخدمة غير متاحة"))
    check("_image_related_failure: بلا error لا يُحيي",
          not setimage._image_related_failure(None))

    for d in (missing_image, missing_image_multi, missing_photo):
        updated = setimage.apply_image(d["id"], "https://cdn.example/revive.jpg", cfg)
        check(f"apply_image ينجح على {d['id']}", updated is not None)
        if updated:
            check(f"{d['id']}: الحالة تعود pending",
                  updated["status"] == "pending", updated.get("status"))
            check(f"{d['id']}: error يُمسح", updated.get("error") is None,
                  updated.get("error"))

    updated_other = setimage.apply_image(
        other_cause["id"], "https://cdn.example/revive-other.jpg", cfg)
    check("apply_image ينجح على المسودة الأخرى (الصورة تُبنى رغم ذلك)",
          updated_other is not None)
    if updated_other:
        check("الحالة تبقى failed (السبب ليس الصورة)",
              updated_other["status"] == "failed", updated_other.get("status"))
        check("error يبقى كما هو",
              updated_other.get("error") == "خطأ فيسبوك: (#1) الخدمة غير متاحة",
              updated_other.get("error"))

def test_setimage_stores_manual_link_without_card() -> None:
    """Issue #852 (يخلف Issue #749/#680): مسودة بلا حقل image بعد -- الحال
    العامة لكل مسار أخبار الآن، لا مسار التحليل وحده كما كانت قبل هذه
    المهمة -- apply_image لا يحاول إعادة بناء (rebuild_card يفترض بطاقة
    سابقة ليحسب مسارًا "تاليًا" لها)، بل يخزّن الرابط في manual_image
    وحده، فتلتقطه cards.ensure عند الاعتماد لاحقًا."""
    from src import setimage

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    draft = {
        "id": "cafe00000001", "status": "pending", "origin": "analysis",
        "arabic": {"post_title": "مقال تحليل"}, "caption": "متن",
        "source": {"publishers": ["Ch1"]},
        # بلا حقل image عمدًا
    }
    store.save_draft(draft)

    result = setimage.apply_image(draft["id"], "https://cdn.example/x.jpg", load_config())
    check("apply_image ينجح (يخزّن الرابط بلا محاولة بناء) على مسودة بلا بطاقة",
          result is not None, result)
    check("لا حقل image أُضيف -- البناء يبقى مؤجَّلًا لحظة الاعتماد",
          result is not None and "image" not in result, result)
    check("manual_image خُزّن للاستعمال لاحقًا في cards.ensure",
          result is not None and result.get("manual_image") == "https://cdn.example/x.jpg",
          result)
    persisted = store.load_draft(draft["id"])
    check("التحديث محفوظ فعليًا على القرص",
          persisted is not None and persisted[1].get("manual_image") == "https://cdn.example/x.jpg",
          persisted[1] if persisted else None)

    # الرابط اليدوي يُستعمل فعليًا عند الاعتماد (cards.ensure) -- إغلاق
    # الحلقة: manual_image ليس مجرد حقل محفوظ بلا أثر.
    from src import cards
    path, fresh = store.load_draft(draft["id"])
    new_rel = cards.ensure(path, fresh, load_config())
    check("cards.ensure ينجح عند الاعتماد مستعملًا الرابط اليدوي", new_rel is not None, new_rel)
    if new_rel:
        built = store.load_draft(draft["id"])[1]
        check("البطاقة بُنيت فعليًا من manual_image (image_info.manual=True)",
              built.get("image_info", {}).get("manual") is True, built.get("image_info"))
        check("image_info.chosen_url هو الرابط اليدوي بعينه",
              built.get("image_info", {}).get("chosen_url") == "https://cdn.example/x.jpg",
              built.get("image_info"))

def test_setimage_cli_sync_handles_cardless_draft() -> None:
    """Issue #852: setimage.main()/sync_issue() (مسار /صورة الكامل عبر
    الـIssue) لم يكونا يتوقعان مسودة بلا حقل image من apply_image --
    ``updated["image"]`` في main() كان لينهار بـKeyError، وsync_issue()
    كانت لتستبدل مسار صورة غير موجود في نص الـIssue. الآن: "new" تكون
    None حين لم تُبنَ بطاقة، فلا استبدال نص ولا انهيار، وتعليق مختلف
    يوضّح أن الرابط خُزّن للبناء لاحقًا لا أنه استُبدل."""
    import src.setimage as setimage_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    draft = {
        "id": "d0d0d0d0d0d0", "score": 4.0, "caption": "متن", "bucket": "serious",
        "source": {"link": "https://x/1", "publishers": ["BBC"]},
        "arabic": {"post_title": "خبر بلا بطاقة بعد", "category": ""},
        # بلا حقل image عمدًا
    }
    store.save_draft({**draft, "status": "pending", "id": "d0d0d0d0d0d0"})

    body = review.build_issue_body([draft], "u/r", "main")
    ticked = body.replace("- [ ] 🖼️ استبدل", "- [x] 🖼️ استبدل")
    filled = ticked.replace(
        f"الرابط:   <!-- imgurl:{draft['id']} -->",
        f"الرابط: https://cdn.example/cli-sync.jpg  <!-- imgurl:{draft['id']} -->")

    sync_path = _TMP_DATA_DIR / "image_sync_test.json"
    real_sync_file = setimage_mod.SYNC_FILE
    setimage_mod.SYNC_FILE = sync_path

    sys.argv = ["setimage", "--from-issue", "--issue", "4242", "--body", ""]
    real_fetch_body = review.fetch_issue_body
    review.fetch_issue_body = lambda issue_number: filled
    try:
        code = setimage_mod.main()
    finally:
        review.fetch_issue_body = real_fetch_body
    check("setimage.main() لا ينهار على مسودة بلا بطاقة (Issue #852)",
          code == 0, f"exit={code}")

    data = json.loads(sync_path.read_text(encoding="utf-8"))
    check("done تحمل مدخلة واحدة بـ new=None (لم تُبنَ بطاقة)",
          len(data.get("done", [])) == 1 and data["done"][0].get("new") is None, data)

    comments: list = []
    updated_bodies: list = []
    real_comment = review.comment
    real_update_body = review.update_issue_body
    review.fetch_issue_body = lambda issue_number: filled
    review.comment = lambda issue_number, text: comments.append(text)
    review.update_issue_body = lambda issue_number, b: updated_bodies.append(b)
    try:
        setimage_mod.sync_issue(4242)
    finally:
        review.fetch_issue_body = real_fetch_body
        review.comment = real_comment
        review.update_issue_body = real_update_body
        setimage_mod.SYNC_FILE = real_sync_file
        sync_path.unlink(missing_ok=True)

    check("sync_issue() لا ينهار بلا مسار صورة يُستبدَل", updated_bodies != [], updated_bodies)
    check("خانة الطلب تُفرَّغ رغم عدم بناء بطاقة",
          updated_bodies and review.parse_image_requests(updated_bodies[0]) == [],
          updated_bodies)
    check("تعليق يوضّح أن الرابط خُزّن للبناء لاحقًا لا «حُدّثت الصورة»",
          comments and "ستُبنى البطاقة به عند الاعتماد" in comments[0], comments)

def test_setimage_apply_image_keeps_origin_badge() -> None:
    """Issue #758: أسهل نقطة يضيع فيها وسم المسار بصمت — apply_image يعيد
    بناء البطاقة لمسودة قائمة بالفعل، فإن لم يمرّر store.origin_of(draft)
    إلى build_post_image يفقد التبديل اليدوي للصورة الملصق الثاني (مثلًا
    «تحليل» على مسودة origin=analysis معتمدة) دون أي خطأ ظاهر."""
    from src import setimage

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    draft = {
        "id": "beef00000002", "status": "pending", "origin": "analysis",
        "bucket": "serious",
        "image": "drafts/2026-01-01/beef00000002.jpg",
        "arabic": {"post_title": "مقال تحليل معتمد", "category": ""},
        "caption": "متن", "source": {"publishers": ["Ch1", "Ch2"]},
    }
    store.save_draft(draft)

    updated = setimage.apply_image(draft["id"], "https://cdn.example/new.jpg", cfg)
    check("apply_image ينجح على مسودة تحليل قائمة (لها بطاقة أصلًا)",
          updated is not None, updated)

    W = int(cfg.path("image.width", 1080))
    H = int(cfg.path("image.height", 1080))
    margin = int(W * 0.06)
    rule = max(4, W // 240)
    header_h = int(H * 0.160) if (cfg.path("brand.name") or cfg.path("brand.logo")) else 0
    inner_top = int(header_h * 0.14)
    inner_bot = header_h - rule - int(header_h * 0.14)
    handle_in_header = bool(cfg.path("brand.handle") and header_h)
    by = ((inner_top + inner_bot) // 2 if not handle_in_header
          else inner_top + int((inner_bot - inner_top) * 0.34))
    probe_xy = (margin + 10, by)
    analysis_bg = imaging.hex_rgb(cfg.path("cards.analysis.bg"))

    out_path = DRAFTS_DIR / Path(updated["image"]).relative_to("drafts")
    with Image.open(out_path) as im:
        pixel = im.convert("RGB").getpixel(probe_xy)
    check("apply_image يحافظ على ملصق «تحليل» بعد تبديل الصورة يدويًا (Issue #758)",
          all(abs(a - b) <= 6 for a, b in zip(pixel, analysis_bg)), (pixel, analysis_bg))

def test_publish_builds_cards_at_approval() -> None:
    """Issue #852، الجزء الأول: البطاقة لم تعد تُبنى عند الجمع -- تُبنى
    الآن في publish.main نفسها، بعد اختيار العنوان مباشرة (الترتيب
    الملزم: تعديل النص ← اختيار العنوان ← cards.ensure ← الرفض التلقائي
    ← النشر). كل المسودات هنا تصل بلا حقل image إطلاقًا، مطابقةً لما
    يخرجه src.collect وأخواتها الآن. فهرس مختار غير الافتراضي يصل فعليًا
    إلى البطاقة؛ عنوان يتجاوز image.headline_max_chars لا يُستعمل عليها
    (يُستبدَل بـarabic.image_headline، والبطاقة تُبنى به بدلًا)؛ وفشل بناء
    حقيقي يُبقي المسودة pending بلا نشر ويُعلَّق على الـIssue باسمها
    وسببها -- لا يوقف نشر بقية الدفعة. البطاقات المبنية تحمل ملصق مسار
    المسودة (نفس مبدأ #758)."""
    from src import cards, publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    max_chars = int(cfg.path("image.headline_max_chars", 90))
    long_headline = ("عنوان طويل جدًا يتجاوز الحدّ المسموح به لطول العنوان "
                     "المرسوم فعليًا على بطاقة الخبر مهما بلغ رقم الإعداد ")
    long_headline = (long_headline * 3)[:max_chars + 30]

    def _draft(id_, headlines, idx):
        return {
            "id": id_, "status": "pending", "score": 5.0, "bucket": "serious",
            "state_media": False, "origin": "request",
            "caption": f"{headlines[0]}\nمتن الخبر.",
            "source": {"link": f"https://x/{id_}", "publishers": ["BBC"],
                       "image_candidates": ["https://cdn.example/ok.jpg"]},
            # category فارغة عمدًا: badge_left يرسم شارة category أولًا فتزيح
            # موضع ملصق origin يمينًا (src/imaging.py) -- probe_xy أدناه
            # يفترض margin+10 كموضع الملصق مباشرة (نفس صيغة
            # test_setimage_apply_image_keeps_origin_badge).
            "arabic": {"post_title": headlines[0], "category": "", "urgent": False,
                       "image_headline": headlines[0]},
            "headlines": headlines, "headline_selected": idx,
        }

    # بلا حقل image عمدًا في الأربعة -- الحال الطبيعية بعد Issue #852.
    draft_chosen = _draft("cc1100000011", ["عنوان قصير أصلي", "عنوان بديل مختار"], 1)
    draft_default = _draft("cc2200000022", ["عنوان افتراضي", "عنوان بديل آخر"], 0)
    draft_long = _draft("cc3300000033", ["عنوان قصير أصلي ٣", long_headline], 1)
    draft_fail = _draft("cc4400000044", ["عنوان قصير أصلي ٤", "عنوان بديل قصير ٤"], 1)
    for d in (draft_chosen, draft_default, draft_long, draft_fail):
        store.save_draft(d)

    body = review.build_issue_body(
        [draft_chosen, draft_default, draft_long, draft_fail], "u/r", "main")
    for d in (draft_chosen, draft_default, draft_long, draft_fail):
        body = tick_marker(body, f"<!-- draft:{d['id']} -->")

    def select_headline(text: str, draft_id: str, idx: int) -> str:
        marker = f"<!-- hl:{draft_id}:"
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if marker not in line:
                continue
            n = int(line.split(marker, 1)[1].split(" ")[0])
            lines[i] = (line.replace("- [ ]", "- [x]", 1) if n == idx
                       else line.replace("- [x]", "- [ ]", 1))
        return "\n".join(lines)

    body = select_headline(body, draft_chosen["id"], 1)
    body = select_headline(body, draft_long["id"], 1)
    body = select_headline(body, draft_fail["id"], 1)
    # draft_default تبقى على الفهرس ٠ الافتراضي بلا أي تعديل على مربعاتها

    real_fetch = publish_mod.fetch_issue
    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    real_comment = review.comment
    real_close = review.close_issue
    real_build = cards._default_build_post_image
    publish_mod.ROOT = DRAFTS_DIR.parent
    publish_calls: list = []
    build_headlines: list = []
    comments: list = []

    def fake_publish_photo(image_path, caption, api_version, first_comment=None):
        publish_calls.append(caption)
        return {"url": "https://fb.example/1", "id": "1"}

    def spy_build(**kwargs):
        build_headlines.append(kwargs.get("headline"))
        # عطل بناء حقيقي مقصود على مسودة draft_fail وحدها -- عبر out_path
        # لا رابط الشبكة (النموذج العام لا يفحّص الروابط مسبقًا كـ
        # setimage.rebuild_card، فرابط "تعذّر" وحده لا يُسقط البناء -- يعود
        # ببساطة إلى الخلفية المصممة).
        if "cc4400000044" in str(kwargs.get("out_path")):
            raise RuntimeError("عطل بناء اختباري")
        return real_build(**kwargs)

    cards._default_build_post_image = spy_build
    facebook.publish_photo = fake_publish_photo
    review.comment = lambda issue_number, text: comments.append(text)
    review.close_issue = lambda issue_number: None
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "approved"}]}
    sys.argv = ["publish", "--issue", "8852", "--now"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo
        review.comment = real_comment
        review.close_issue = real_close
        cards._default_build_post_image = real_build

    check("publish.main ينتهي بنجاح رغم فشل بناء بطاقة واحدة", code == 0, f"exit={code}")
    check("publish.main: الثلاثة السليمة نُشرت (الرابعة فشل بناؤها فبقيت معلَّقة)",
          len(publish_calls) == 3, publish_calls)

    check("العنوان المختار (فهرس ١) وصل فعليًا إلى بناء البطاقة",
          "عنوان بديل مختار" in build_headlines, build_headlines)
    check("عنوان يتجاوز الحدّ لم يصل للبطاقة إطلاقًا -- استُبدل بـarabic.image_headline",
          long_headline not in build_headlines and "عنوان قصير أصلي ٣" in build_headlines,
          build_headlines)

    persisted_chosen = store.load_draft(draft_chosen["id"])[1]
    check("فهرس ١: البطاقة بُنيت فعلًا (حقل image ظهر -- لم يكن موجودًا قبل الاعتماد)",
          bool(persisted_chosen.get("image")), persisted_chosen.get("image"))
    check("فهرس ١: حالة المسودة published", persisted_chosen.get("status") == "published",
          persisted_chosen.get("status"))
    check("فهرس ١: النص المنشور يحمل العنوان المختار",
          any(c.startswith("عنوان بديل مختار") for c in publish_calls), publish_calls)

    persisted_default = store.load_draft(draft_default["id"])[1]
    check("الفهرس الافتراضي (٠): البطاقة بُنيت أيضًا (لم تُبنَ عند الجمع أصلًا)",
          bool(persisted_default.get("image")), persisted_default.get("image"))

    persisted_long = store.load_draft(draft_long["id"])[1]
    check("عنوان يتجاوز الحدّ: البطاقة بُنيت رغم ذلك (بعنوان arabic.image_headline بدلًا)",
          bool(persisted_long.get("image")), persisted_long.get("image"))
    check("عنوان يتجاوز الحدّ: النص المنشور أخذ العنوان المختار رغم ذلك",
          any(c.startswith(long_headline) for c in publish_calls),
          [c[:40] for c in publish_calls])

    persisted_fail = store.load_draft(draft_fail["id"])[1]
    check("فشل بناء حقيقي: المسودة تبقى pending بلا نشر (لا تُسقَط صامتًا)",
          persisted_fail.get("status") == "pending", persisted_fail.get("status"))
    check("فشل بناء حقيقي: لا حقل image ظهر", "image" not in persisted_fail, persisted_fail)
    check("فشل بناء حقيقي: تعليق على الـIssue يذكر اسم المسودة (بعد تطبيق العنوان المختار)",
          comments and any("عنوان بديل قصير ٤" in c for c in comments), comments)

    # البطاقات المبنية تحمل ملصق مسار المسودة (origin=request، نفس مبدأ
    # #758) -- نفس أسلوب فحص البكسل في test_setimage_apply_image_keeps_origin_badge
    W = int(cfg.path("image.width", 1080))
    H = int(cfg.path("image.height", 1080))
    margin = int(W * 0.06)
    rule = max(4, W // 240)
    header_h = int(H * 0.160) if (cfg.path("brand.name") or cfg.path("brand.logo")) else 0
    inner_top = int(header_h * 0.14)
    inner_bot = header_h - rule - int(header_h * 0.14)
    handle_in_header = bool(cfg.path("brand.handle") and header_h)
    by = ((inner_top + inner_bot) // 2 if not handle_in_header
          else inner_top + int((inner_bot - inner_top) * 0.34))
    probe_xy = (margin + 10, by)
    request_bg = imaging.hex_rgb(cfg.path("cards.request.bg"))
    out_path = DRAFTS_DIR / Path(persisted_chosen["image"]).relative_to("drafts")
    with Image.open(out_path) as im:
        pixel = im.convert("RGB").getpixel(probe_xy)
    check("البطاقة المبنية عند الاعتماد تحمل ملصق «تحقيق» (origin=request، Issue #758)",
          all(abs(a - b) <= 6 for a, b in zip(pixel, request_bg)), (pixel, request_bg))

def test_request_search() -> None:
    """الطلب اليدوي: كلمات → بحث → مرشحون."""
    from src import request as rq

    feeds = rq.search_feeds("زلزال هرات", 7, rq.DEFAULT_LOCALES)
    check("لكل لغة خلاصة بحث", len(feeds) == len(rq.DEFAULT_LOCALES))
    check("النافذة الزمنية داخل الاستعلام",
          all("when%3A7d" in f["url"] for f in feeds))
    check("الاستعلام مُرمَّز في الرابط",
          all("news.google.com/rss/search" in f["url"] for f in feeds))

    # البند 5 (تعليق التنفيذ على PR #340): days=None يُسقط قيد when: تمامًا
    # — واقعة مرجعية (verify.py) مصدرها المؤيِّد قد يكون بعمر الواقعة نفسها
    feeds_unrestricted = rq.search_feeds("كتاب صدر 2009", None, rq.DEFAULT_LOCALES)
    check("days=None يبني استعلامًا بلا قيد when: إطلاقًا",
          all("when%3A" not in f["url"] for f in feeds_unrestricted),
          [f["url"] for f in feeds_unrestricted])

    # التطبيع العربي: أل التعريف والهمزة والتاء المربوطة لا تفرّق
    check("أل التعريف تُسقط",
          "زلزال" in rq.norm_tokens("الزلزال"))
    check("الهمزة تُطبَّع",
          rq.norm_tokens("إسرائيل") == rq.norm_tokens("اسرائيل"))
    check("حروف الجر تُستبعد", "على" not in rq.norm_tokens("على الحدود"))

    wanted = rq.norm_tokens("زلزال هرات")
    art = Article(title="زلزال قوي يضرب هرات", link="https://x/1", summary="",
                  source_name="s", region="global", weight=1.0,
                  published=datetime.now(timezone.utc))
    off = Article(title="ارتفاع أسعار النفط", link="https://x/2", summary="",
                  source_name="s", region="global", weight=1.0,
                  published=datetime.now(timezone.utc))
    latin = Article(title="Strong earthquake hits Herat", link="https://x/3",
                    summary="", source_name="s", region="global", weight=1.0,
                    published=datetime.now(timezone.utc))
    check("المطابق يمرّ", rq.relevant(art, wanted, 1))
    check("غير المطابق يُستبعد", not rq.relevant(off, wanted, 1))
    check("اختلاف اللغة لا يُسقط النتيجة", rq.relevant(latin, wanted, 1))

    # البحث كاملًا بخلاصة مُصطنعة — بلا شبكة
    cfg = load_config()
    original = rq.fetch_source
    rq.fetch_source = lambda src, max_age_hours: [art, off]
    try:
        found = rq.find("زلزال هرات", cfg, days=7)
    finally:
        rq.fetch_source = original
    titles = [a.title for a in found]
    check("نتيجة الطلب مرشّحة", "زلزال قوي يضرب هرات" in titles)
    check("غير المطابق لا يصل للترتيب", "ارتفاع أسعار النفط" not in titles)

    check("نافذة الطلب أوسع من نافذة الدورة",
          int((load_config().get("request", {}) or {}).get("days", 7)) * 24
          > int((cfg.get("selection", {}) or {}).get("max_age_hours", 18)))

def test_request_and_radar_headlines() -> None:
    """Issue #756: radar.build_draft المشتركة مع مسار العاجل لا تولّد عناوين
    ولا تحفظها إطلاقًا (لا كلفة نداء يدفعها العاجل بلا استعمال)، بينما
    request.py يولّدها بنفسه بعد بناء المسودة ويحفظها في drafts.

    radar.py يستورد write_arabic/build_post_image عبر ``from .writer import
    ...`` على مستوى الوحدة، وrequest.py يستورد radar بالمثل — كلاهما يُحمَّل
    فعليًا (سلسلة import عابرة من evidence.py) عند استيراد وحدات هذا الملف
    في القمة، أي **قبل** أن يستبدل install_fakes() writer.write_arabic
    بالفاكة العامة؛ فالاسم المرتبط داخل radar.py يبقى يشير إلى الدالة
    الحقيقية بصرف النظر عمّا يُستبدَل لاحقًا على وحدة writer نفسها (نفس
    السبب الذي يجعل كل اختبار رادار آخر في هذا الملف يستبدل
    radar.write_arabic محليًا بدل الاعتماد على الفاكة العامة)."""
    from src import radar
    from src import request as rq

    def fake_write(article, cfg, retries=3, previous_post=None, source_docs=None):
        return {"urgent": bool(cfg), "category": "عالم", "angle": "خبر",
                "image_headline": "عنوان تجريبي", "post_title": "عنوان تجريبي",
                "post_body": "متن تجريبي لفحص العناوين.", "hashtags": []}

    # radar.build_draft لم تعد تبني بطاقة إطلاقًا (Issue #852) -- لا حاجة
    # لتمويه build_post_image هنا بعد الآن.
    real_write = radar.write_arabic
    radar.write_arabic = fake_write
    try:
        cfg = load_config()
        art_radar = Article(title="عاجل تجريبي لفحص استبعاد العناوين", link="https://x/radar-hl",
                            summary="", source_name="s", region="global", weight=1.0,
                            published=datetime.now(timezone.utc))
        radar_draft = radar.build_draft(art_radar, cfg, urgent=True)
        check("radar.build_draft لا تحفظ headlines إطلاقًا",
              radar_draft is not None and "headlines" not in radar_draft, radar_draft)
        check("radar.build_draft لا تحفظ headline_selected إطلاقًا",
              radar_draft is not None and "headline_selected" not in radar_draft, radar_draft)
        check("radar.build_draft بلا حقل image (Issue #852 -- البطاقة تُبنى عند الاعتماد)",
              radar_draft is not None and "image" not in radar_draft, radar_draft)
        check("radar.build_draft تحفظ source.image_candidates لاستعمالها لاحقًا",
              radar_draft is not None
              and "image_candidates" in (radar_draft.get("source") or {}), radar_draft)

        art_req = Article(title="طلب تجريبي لفحص حفظ العناوين", link="https://x/request-hl",
                          summary="", source_name="s", region="global", weight=1.0,
                          published=datetime.now(timezone.utc))
        real_fetch_source = rq.fetch_source
        rq.fetch_source = lambda src, max_age_hours: [art_req]
        sys.argv = ["request", "--query", "طلب تجريبي لفحص حفظ العناوين", "--limit", "1"]
        try:
            code = rq.main()
        finally:
            rq.fetch_source = real_fetch_source
    finally:
        radar.write_arabic = real_write

    check("request.main() ينتهي بنجاح", code == 0, f"exit={code}")
    req_draft = store.load_draft(art_req.uid)
    check("مسودة الطلب صيغت فعليًا", req_draft is not None, req_draft)
    if req_draft:
        req_data = req_draft[1]
        check("request.py: يحفظ headlines/headline_selected (Issue #756)",
              isinstance(req_data.get("headlines"), list) and len(req_data["headlines"]) == 3
              and req_data.get("headline_selected") == 0, req_data.get("headlines"))
        check("request.py يكتب origin=request كما كان", req_data.get("origin") == "request",
              req_data.get("origin"))

def test_headlines_module() -> None:
    """Issue #756: المولّد المشترك (src/headlines.py) -- التحقّق العام
    (سؤال أول + حدّ كلمات) وحلقة إعادة المحاولة، مستقلَّين عن أي مسار
    بعينه. فحص الاسم غير الموثَّق تحليليّ بحت ويبقى مختبَرًا في
    test_youtube_article عبر ya._validate_headlines (لا تعديل هناك)."""
    good = ["هل يتصاعد الموقف بعد الحدث؟", "الحدث يفتح الباب لتطورات جديدة",
            "تصعيد مرجّح بعد الحدث الأخير"]
    ok, reason = headlines.validate_headlines(good, 15)
    check("validate_headlines: ثلاثة عناوين صالحة تُقبَل", ok, reason)

    not_question = ["تطوّر متوقّع بعد الحدث", "عنوان ثانٍ", "عنوان ثالث"]
    ok, reason = headlines.validate_headlines(not_question, 15)
    check("validate_headlines: العنوان الأول بلا علامة استفهام يُرفَض",
          not ok and "سؤال" in reason, reason)

    too_long = ["هل " + " ".join(["كلمة"] * 20) + "؟", "قصير", "قصير أيضًا"]
    ok, reason = headlines.validate_headlines(too_long, 15)
    check("validate_headlines: عنوان يتجاوز سقف الكلمات يُرفَض",
          not ok and "15 كلمة" in reason, reason)

    class _Block:
        def __init__(self, type_, input_=None, text=None):
            self.type, self.input, self.text = type_, input_, text

    class _Resp:
        def __init__(self, content):
            self.content = content

    class _Messages:
        def __init__(self, responses):
            self._responses = list(responses)
            self.calls: list = []

        def create(self, **kw):
            self.calls.append(kw)
            return self._responses.pop(0)

    class _Client:
        def __init__(self, responses):
            self.messages = _Messages(responses)

    hl_cfg = load_config()
    hl_cfg["headlines"] = {"model": "m", "max_tokens": 300, "max_retries": 2, "max_words": 15}

    success_client = _Client([_Resp([_Block("tool_use", input_={"headlines": good})])])
    result, error = headlines.propose_headlines("محتوى تجريبي", hl_cfg, "headlines",
                                                 client=success_client)
    check("propose_headlines: محاولة أولى صالحة تُقبَل بلا إعادة",
          error is None and result == good, (result, error))
    check("propose_headlines: يقرأ cfg_prefix.model/max_tokens من config.yaml",
          success_client.messages.calls[0]["model"] == "m"
          and success_client.messages.calls[0]["max_tokens"] == 300,
          success_client.messages.calls[0])

    retry_client = _Client([
        _Resp([_Block("tool_use", input_={"headlines": not_question})]),
        _Resp([_Block("tool_use", input_={"headlines": good})]),
    ])
    result2, error2 = headlines.propose_headlines("محتوى تجريبي", hl_cfg, "headlines",
                                                   client=retry_client)
    check("propose_headlines: إعادة محاولة بعد عنوان أول بلا صيغة سؤال تنجح",
          error2 is None and result2 == good, (result2, error2))

    bad_client = _Client([
        _Resp([_Block("tool_use", input_={"headlines": not_question})]),
        _Resp([_Block("tool_use", input_={"headlines": not_question})]),
    ])
    result3, error3 = headlines.propose_headlines("محتوى تجريبي", hl_cfg, "headlines",
                                                   client=bad_client)
    check("propose_headlines: فشل كل المحاولات يعيد سببًا صريحًا لا قائمة",
          result3 is None and error3 is not None, error3)

    # extra_validate يشارك ميزانية إعادة المحاولة نفسها (لا محاولات إضافية) --
    # يستعملها youtube_article.generate_headlines لفحص الاسم غير الموثَّق.
    # كلتا المحاولتين هنا تجتاز التحقّق العام (headlines صالحة بنيويًا) ثم
    # تُرفَضان بـextra_validate، فتُستهلَك ميزانية max_retries=2 كاملة.
    extra_calls: list = []

    def extra_reject_always(hls):
        extra_calls.append(hls)
        return False, "رفض إضافي مخصَّص"

    extra_client = _Client([
        _Resp([_Block("tool_use", input_={"headlines": good})]),
        _Resp([_Block("tool_use", input_={"headlines": good})]),
    ])
    result4, error4 = headlines.propose_headlines(
        "محتوى تجريبي", hl_cfg, "headlines", client=extra_client,
        extra_validate=extra_reject_always)
    check("propose_headlines: extra_validate يرفض حتى بعد نجاح التحقّق العام",
          result4 is None and "رفض إضافي مخصَّص" in error4, error4)
    check("propose_headlines: extra_validate استُدعي في كل محاولة اجتازت التحقّق العام",
          len(extra_calls) == 2, extra_calls)

def test_headlines_failure_keeps_draft_with_empty_list() -> None:
    """Issue #756: فشل نداء العناوين لا يُسقِط مسودة صيغت بنجاح فعليًا --
    نفس مبدأ مسار التحليل (youtube_article.run). تُحفَظ headlines=[] بلا
    تكرار العنوان الأصلي ثلاثًا، ومسودة بقائمة فارغة لا تُعرَض لها مربعات
    عناوين إطلاقًا في نص Issue المراجعة."""
    from src import collect_finalize, preselect

    art = Article(title="خبر لفحص فشل توليد العناوين عمدًا",
                 link="https://hlfail.example/a", summary="", source_name="P1",
                 region="r1", weight=1.0, published=datetime.now(timezone.utc),
                 bucket="serious", publisher="P1")
    cand = preselect.build_candidate(art)
    store.save_candidate(cand)

    real_headlines_for_post = headlines.headlines_for_post
    headlines.headlines_for_post = lambda *a, **kw: (None, "فشل تجريبي مقصود")
    try:
        draft = collect_finalize._write_selected(
            cand["id"], store.load_history(), 0.5, {}, {}, load_config(), [])
    finally:
        headlines.headlines_for_post = real_headlines_for_post

    check("فشل نداء العناوين لا يُسقِط مسودة صالحة فعليًا", draft is not None, draft)
    if draft:
        check("headlines=[] عند فشل النداء (لا تكرار العنوان الأصلي ثلاثًا)",
              draft.get("headlines") == [], draft.get("headlines"))
        body = review.build_issue_body([draft], "u/r", "main")
        check("مسودة بـ[] لا تُعرَض لها مربعات عناوين إطلاقًا",
              f"<!-- hl:{draft['id']}:" not in body and "📰 **العنوان:**" not in body, body)

def test_review_sibling_alternate_line() -> None:
    """review.build_issue_body: مسودة تحمل sibling_id (مقال ومنشور تحقيق من
    نفس المدخل، Issue #765) تُعرض بسطر 🔀 يذكر رقم المنشور المقابل صراحة
    (تصحيح Issue #769 -- المسودتان قد لا تتجاوران بين مسودات الأخبار، فسطر
    «بديل لنفس المدخل» العام لا يقول أيّهما يقابل أيّهما). يظهر لهما فقط،
    لا لأي مسودة أخرى بلا sibling_id."""
    base = {
        "score": 1.0, "bucket": "serious", "state_media": False,
        "source": {"link": "https://x/1", "publishers": ["Ch"]},
        "caption": "متن", "image": "drafts/2026-01-01/a.jpg",
        "arabic": {"post_title": "", "category": ""},
    }
    draft_article = {**base, "id": "sib00000001", "arabic": {**base["arabic"], "post_title": "عنوان المقال"},
                     "sibling_id": "sib00000002"}
    draft_investigation = {**base, "id": "sib00000002",
                           "arabic": {**base["arabic"], "post_title": "عنوان التحقيق"},
                           "sibling_id": "sib00000001"}
    draft_plain = {**base, "id": "sib00000003",
                   "arabic": {**base["arabic"], "post_title": "عنوان عادي بلا أخت"}}

    # الترتيب هنا مقصود: المقال (idx 1) والتحقيق (idx 2) لا يتجاوران --
    # مسودة عادية بينهما -- كي يثبت الاختبار أن الرقم المذكور يتبع sibling_id
    # الفعلي لا مجرد "المسودة التالية/السابقة".
    body = review.build_issue_body(
        [draft_article, draft_plain, draft_investigation], "u/r", "main")

    check("build_issue_body: سطر «بديل للمنشور رقم» يظهر مرتين فقط (لمسودتين "
          "متبادلتَي sibling_id)",
          body.count("🔀 بديل للمنشور رقم") == 2, body)
    check("build_issue_body: لا يظهر السطر العام «بديل لنفس المدخل» بعد الآن",
          "🔀 بديل لنفس المدخل" not in body, body)

    lines = body.splitlines()
    article_idx = next(i for i, ln in enumerate(lines) if "sib00000001" in ln)
    investigation_idx = next(i for i, ln in enumerate(lines) if "sib00000002" in ln)
    plain_idx = next(i for i, ln in enumerate(lines) if "sib00000003" in ln)
    # +4 لا +2: مربع 🎴 «اعرض البطاقة قبل النشر» (Issue #858) يقع الآن مباشرة
    # تحت مربع الاعتماد (سطران: المربع ثم فراغ) قبل سطر «بديل».
    check("build_issue_body: سطر «بديل» يظهر بعد عنوان مسودة المقال ومربع 🎴 "
          "مباشرة ويذكر رقم التحقيق (3، ترتيبه الثالث في القائمة)",
          "🔀 بديل للمنشور رقم 3" in lines[article_idx + 4], lines[article_idx:article_idx + 5])
    check("build_issue_body: سطر «بديل» يظهر بعد عنوان مسودة التحقيق ومربع 🎴 "
          "مباشرة ويذكر رقم المقال (1، ترتيبه الأول في القائمة)",
          "🔀 بديل للمنشور رقم 1" in lines[investigation_idx + 4],
          lines[investigation_idx:investigation_idx + 5])
    plain_block = "\n".join(lines[plain_idx:plain_idx + 4])
    check("build_issue_body: مسودة بلا sibling_id لا تحمل سطر «بديل» إطلاقًا",
          "🔀 بديل" not in plain_block, plain_block)

def test_setimage_rebuild_card_uses_all_image_candidates() -> None:
    """تصحيح من #760 (Issue #765، بند أول): rebuild_card حين لا manual_image
    كانت تمرّر [url] فقط (أول عنصر في image_candidates) لـbuild_post_image
    بصرف النظر عن عدد المرشحين الفعلي -- بطاقة مدمجة من صورتين (imaging.
    build_post_image يدمج أول مرشَّحين ناجحين) تنهار صامتة إلى صورة واحدة
    عند أي إعادة بناء (اختيار عنوان غير افتراضي، مثلًا). مسار apply_image
    (رابط يدوي) يبقى صورة واحدة كما هو -- الإصلاح لا يمسّه."""
    from src import setimage

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_config()

    draft = {
        "id": "cc5500000005", "status": "pending", "bucket": "serious",
        "image": "drafts/rb5.jpg",
        "arabic": {"post_title": "عنوان", "category": ""},
        "source": {"publishers": ["A", "B"],
                   "image_candidates": ["https://cdn.example/one.jpg",
                                        "https://cdn.example/two.jpg"]},
    }
    store.save_draft(draft)

    calls: list = []
    real_build = setimage.build_post_image

    def spy_build(**kwargs):
        calls.append(kwargs.get("image_urls"))
        return real_build(**kwargs)

    setimage.build_post_image = spy_build
    try:
        new_rel = setimage.rebuild_card(Path("drafts/dummy.json"), draft, "عنوان جديد", cfg)
    finally:
        setimage.build_post_image = real_build

    check("rebuild_card بلا manual_image: يمرّر image_candidates كاملة لا أول رابط فقط",
          calls and calls[0] == draft["source"]["image_candidates"], calls)
    check("rebuild_card: نجح البناء فعليًا", new_rel is not None, new_rel)

    calls.clear()
    setimage.build_post_image = spy_build
    try:
        updated = setimage.apply_image(draft["id"], "https://cdn.example/manual.jpg", cfg)
    finally:
        setimage.build_post_image = real_build

    check("apply_image (رابط يدوي): يمرّر رابطًا واحدًا فقط -- الإصلاح لا يمسّ هذا المسار",
          calls and calls[0] == ["https://cdn.example/manual.jpg"], calls)
    check("apply_image: نجح التحديث فعليًا", updated is not None, updated)

def test_publish_investigation_requires_review() -> None:
    """بند 3، Issue #765: منشور تحقيق لا يُنشر تلقائيًا أبدًا -- publish.
    cmd_now (نشر مباشر بمعرّف عبر --ids، issue_number=None) يرفض مسودة
    تحمل is_investigation=True صراحة، لأن هذا المسار لا يقرأ مربعات اعتماد
    Issue أصلًا. المسار المعتاد (ids من review.parse_approved، issue_number
    حقيقي) يبقى يعمل بلا تغيير -- الحظر بـissue_number is None وحده، لا
    بـis_investigation وحده."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_config()

    inv_draft = {
        "id": "inv00000001", "status": "pending", "bucket": "serious",
        "is_investigation": True, "origin": "article",
        "score": 0.0, "state_media": False,
        "image": "drafts/2026-01-01/inv00000001.jpg",
        "arabic": {"post_title": "عنوان تحقيق", "category": "عالم", "urgent": False},
        "caption": "عنوان تحقيق\nمتن.",
        "source": {"link": "https://x/inv1", "publishers": ["Ch"]},
    }
    store.save_draft(inv_draft)
    image_path = DRAFTS_DIR / "2026-01-01" / "inv00000001.jpg"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"\xff\xd8\xff")

    real_publish_photo = facebook.publish_photo
    real_root = publish_mod.ROOT
    publish_mod.ROOT = DRAFTS_DIR.parent
    calls: list = []

    def fake_publish_photo(image_path, caption, api_version, first_comment=None):
        calls.append(caption)
        return {"url": "https://fb.example/1", "id": "1"}

    facebook.publish_photo = fake_publish_photo
    try:
        code_direct = publish_mod.cmd_now(["inv00000001"], cfg, None)
    finally:
        facebook.publish_photo = real_publish_photo

    check("cmd_now(--ids مباشر، issue_number=None): يرفض مسودة تحقيق -- لا نشر",
          not calls, calls)
    check("cmd_now: تعيد 0 (لا تفشل التشغيلة) رغم الرفض",
          code_direct == 0, code_direct)
    persisted = store.load_draft("inv00000001")[1]
    check("cmd_now (--ids مباشر): مسودة التحقيق تبقى pending -- لم تُنشر",
          persisted["status"] == "pending", persisted["status"])

    # ── المسار المعتاد (issue_number حقيقي، قادم فعليًا من review.parse_approved
    # في المسار الطبيعي) ينشر بلا عائق -- الحظر خاص بـ--ids المباشر وحده ──
    real_comment = review.comment
    real_close = review.close_issue
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: None
    facebook.publish_photo = fake_publish_photo
    try:
        code_reviewed = publish_mod.cmd_now(["inv00000001"], cfg, 9765)
    finally:
        facebook.publish_photo = real_publish_photo
        review.comment = real_comment
        review.close_issue = real_close
        publish_mod.ROOT = real_root

    check("cmd_now (issue_number حقيقي -- المسار المعتاد بعد المراجعة): ينشر مسودة "
          "التحقيق بلا عائق",
          len(calls) == 1, calls)
    check("cmd_now: تعيد 0",
          code_reviewed == 0, code_reviewed)

def test_no_reject_boxes_in_review_issues() -> None:
    """Issue #841: خيارات سبب الاستبعاد حُذفت من واجهتي المراجعة كلتيهما —
    عدم الاعتماد يصير رفضًا بذاته، والسبب يُسأل عنه لاحقًا في التقرير
    الأسبوعي، لا عبر مربعات في الواجهة."""
    from src import preselect, review

    draft = {"id": "abcd12", "score": 9.1, "caption": "متن\nسطر",
             "image": "assets/x.jpg", "bucket": "serious",
             "source": {"link": "https://x/1", "publishers": ["BBC", "Reuters"]},
             "arabic": {"post_title": "عنوان", "category": "سياسة"}}
    body = review.build_issue_body([draft], "u/r", "main")

    check("لا مربع رفض واحد في Issue المراجعة", "<!-- rj:" not in body, body)
    check("لا سطر التعليمات القديم عن سبب الرفض",
          "رفضتَ خبرًا" not in body and "لرفضه" not in body, body)
    check("سطر التعليمات الجديد يقول القاعدة صراحة",
          "لن يُنشر" in body and "لم يُعتمد" not in body, body)
    check("لا REJECT_CHOICES ولا parse_rejects بعد الآن في review.py",
          not hasattr(review, "REJECT_CHOICES") and not hasattr(review, "parse_rejects"))

    cand = preselect.build_candidate(
        Article(title="مرشح تجريبي", link="https://x/cand", summary="",
               source_name="P", region="r", weight=1.0,
               published=datetime.now(timezone.utc), bucket="serious", publisher="P"))
    selection_body = preselect.build_selection_issue_body([cand])
    check("لا مربع رفض واحد في Issue الاختيار", "<!-- crj:" not in selection_body,
          selection_body)
    check("مربعا المصير (انشر فورًا/صغ واعرض) باقيان",
          f"<!-- now:{cand['id']} -->" in selection_body
          and f"<!-- review:{cand['id']} -->" in selection_body,
          selection_body)
    check("لا CREJECT_MARKER ولا parse_candidate_rejects بعد الآن في preselect.py",
          not hasattr(preselect, "CREJECT_MARKER")
          and not hasattr(preselect, "parse_candidate_rejects"))

def test_publish_unapproved_becomes_rejected() -> None:
    """Issue #841، البند 2: عدم الاعتماد داخل Issue موسوم approved يصير
    رفضًا ضمنيًا (status=rejected، وسم feedback «لم يُعتمد») — بصرف النظر
    عن الأصل (أخبار أو تحليل)، مقيَّدًا بمعرّفات هذا الـIssue وحده."""
    from src import feedback
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    approved_draft = {
        "id": "aa00000001", "status": "pending", "origin": "news",
        "arabic": {"post_title": "خبر معتمد"}, "caption": "متن",
        "image": "drafts/a.jpg", "bucket": "serious",
        "source": {"link": "https://x/1", "publishers": ["BBC"]},
    }
    news_reject = {
        "id": "bb00000002", "status": "pending", "origin": "news",
        "arabic": {"post_title": "خبر لم يُعتمد"}, "caption": "متن",
        "image": "drafts/b.jpg", "bucket": "serious",
        "source": {"link": "https://x/2", "publishers": ["BBC"]},
    }
    analysis_reject = {
        "id": "cc00000003", "status": "pending", "origin": "analysis",
        "arabic": {"post_title": "تحليل لم يُعتمد"}, "caption": "متن",
        "source": {"publishers": ["Ch1"]},
        # بلا حقل image عمدًا — مسودة تحليل قبل الاعتماد (Issue #680)
    }
    outside_pending = {
        "id": "dd00000004", "status": "pending", "origin": "news",
        "arabic": {"post_title": "خبر معلَّق خارج هذا الـIssue"}, "caption": "متن",
        "image": "drafts/d.jpg", "bucket": "serious",
        "source": {"link": "https://x/4", "publishers": ["BBC"]},
    }
    for d in (approved_draft, news_reject, analysis_reject, outside_pending):
        store.save_draft(d)

    body = (
        f"- [x] **1. خبر معتمد**  <!-- draft:{approved_draft['id']} -->\n"
        f"- [ ] **2. خبر لم يُعتمد**  <!-- draft:{news_reject['id']} -->\n"
        f"- [ ] **3. تحليل لم يُعتمد**  <!-- draft:{analysis_reject['id']} -->\n"
    )

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "approved"}],
    }

    published_ids: list = []
    real_publish_one = publish_mod.publish_one

    def fake_publish_one(path, draft, cfg):
        published_ids.append(draft["id"])
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['id']}"

    publish_mod.publish_one = fake_publish_one

    real_comment = review.comment
    real_close = review.close_issue
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: None

    rejections_before = len(feedback.load())

    sys.argv = ["publish", "--issue", "8841", "--now"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        publish_mod.publish_one = real_publish_one
        review.comment = real_comment
        review.close_issue = real_close

    check("publish.main ينتهي بنجاح", code == 0, f"exit={code}")
    check("المعتمَد وحده نُشر", published_ids == [approved_draft["id"]], published_ids)

    check("خبر لم يُعتمد سُجّل rejected",
          store.load_draft(news_reject["id"])[1]["status"] == "rejected",
          store.load_draft(news_reject["id"])[1].get("status"))
    check("مسودة تحليل غير معلَّمة تُرفض كغيرها (لا استثناء لمسار التحليل)",
          store.load_draft(analysis_reject["id"])[1]["status"] == "rejected",
          store.load_draft(analysis_reject["id"])[1].get("status"))
    check("مسودة معلَّقة خارج هذا الـIssue لا تُمسّ",
          store.load_draft(outside_pending["id"])[1]["status"] == "pending",
          store.load_draft(outside_pending["id"])[1].get("status"))

    rejections_after = feedback.load()
    new_entries = rejections_after[rejections_before:]
    check("سُجّل رفضان فقط في feedback (المعتمَد والخارجي لا يُسجَّلان)",
          len(new_entries) == 2, new_entries)
    check("كلا الرفضين بوسم «لم يُعتمد»",
          all(e["tag"] == "لم يُعتمد" for e in new_entries), new_entries)
    check("كلا الرفضين يحملان معرّفَي المسودتين غير المعتمَدتين",
          {e["id"] for e in new_entries} == {news_reject["id"], analysis_reject["id"]},
          new_entries)

    guidance = feedback.screening_guidance(rejections_after, limit=12, days=21)
    check("screening_guidance تستبعد مدخلة «لم يُعتمد» (لا تصف شيئًا للفرز)",
          "خبر لم يُعتمد" not in guidance, guidance)

def test_review_card_and_back_boxes() -> None:
    """Issue #858، الجزء الثاني، البند 1 و4 و6: مربع 🎴 «اعرض البطاقة قبل
    النشر» يظهر في نص المراجعة الأولية غير معلَّم افتراضيًا ولا يظهر إطلاقًا
    في نص المراجعة النهائية؛ parse_card_requests تقرأ المعلَّم فقط وتتجاهل
    غيره؛ الأخير يحمل بدلًا منه مربع اعتماد وصورة يدوية ومربع ↩️ العودة،
    وبلا أي مربع عنوان (hl:)."""
    draft = {
        "id": "ab0000000001", "score": 4.0, "bucket": "serious",
        "state_media": False, "origin": "news",
        "caption": "عنوان الخبر\nمتن الخبر.",
        "image": "drafts/2020-01-01/ab0000000001.jpg",
        "source": {"link": "https://x/rv1", "publishers": ["BBC"]},
        "arabic": {"post_title": "عنوان الخبر", "category": "عالم", "urgent": False},
        "headlines": ["عنوان ١", "عنوان ٢"], "headline_selected": 0,
    }

    body = review.build_issue_body([draft], "u/r", "main")
    check("مربع 🎴 يظهر في المراجعة الأولية غير معلَّم",
          f"- [ ] 🎴 اعرض البطاقة قبل النشر  <!-- card:{draft['id']} -->" in body,
          body[:800])
    check("سطر التعليمات يذكر قاعدة 🎴",
          "مع 🎴" in body and "Issue ثانٍ" in body, body[:400])
    check("parse_card_requests فارغة قبل التعليم", review.parse_card_requests(body) == set())

    marked = tick_marker(body, f"<!-- card:{draft['id']} -->")
    check("parse_card_requests تقرأ المعلَّم",
          review.parse_card_requests(marked) == {draft["id"]})
    check("تعليم مربع 🎴 وحده لا يُعتبر اعتمادًا", review.parse_approved(marked) == [])

    final_body = review.build_final_review_body([draft], "u/r", "main")
    check("لا مربع 🎴 في المراجعة النهائية",
          f"<!-- card:{draft['id']} -->" not in final_body, final_body[:800])
    check("لا مربعات عناوين في المراجعة النهائية", "<!-- hl:" not in final_body,
          final_body[:800])
    check("مربع اعتماد موجود في المراجعة النهائية",
          f"<!-- draft:{draft['id']} -->" in final_body)
    check("مربع ↩️ للعودة موجود، غير معلَّم افتراضيًا",
          f"- [ ] ↩️ أعده للمراجعة الأولية  <!-- back:{draft['id']} -->" in final_body,
          final_body[:800])
    check("مربع الصورة اليدوية موجود في المراجعة النهائية",
          f"<!-- img:{draft['id']} -->" in final_body
          and f"<!-- imgurl:{draft['id']} -->" in final_body)
    check("البطاقة المبنيّة تظهر (رابط raw.githubusercontent.com)",
          "raw.githubusercontent.com" in final_body and draft["image"] in final_body)

    check("parse_back_requests فارغة قبل التعليم", review.parse_back_requests(final_body) == set())
    marked_back = tick_marker(final_body, f"<!-- back:{draft['id']} -->")
    check("parse_back_requests تقرأ المعلَّم",
          review.parse_back_requests(marked_back) == {draft["id"]})

def test_publish_card_request_defers_to_final_review() -> None:
    """Issue #858، الجزء الثاني، البند 1-2: معتمَد بلا 🎴 يُنشر فورًا كسابقًا؛
    معتمَد مع 🎴 لا يُنشر -- بطاقته تُبنى فعلًا (cards.ensure يقع أعلاه في
    publish.main، قبل هذا التفرّع، وقبل الفرق بين المسارين) لكنه يبقى pending
    ويُجمَّع في Issue مراجعة نهائية واحد بوسم final-review، وتعليق على
    الـIssue الأولي يذكر رقمه."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    def _draft(id_, title):
        return {
            "id": id_, "status": "pending", "score": 5.0, "bucket": "serious",
            "state_media": False, "origin": "news",
            "caption": f"{title}\nمتن الخبر.",
            "source": {"link": f"https://x/{id_}", "publishers": ["BBC"],
                       "image_candidates": ["https://cdn.example/ok.jpg"]},
            "arabic": {"post_title": title, "category": "", "urgent": False},
        }

    draft_direct = _draft("cd0000000001", "خبر ينشر فورًا")
    draft_card = _draft("cd0000000002", "خبر بانتظار مراجعة نهائية")
    for d in (draft_direct, draft_card):
        store.save_draft(d)

    body = review.build_issue_body([draft_direct, draft_card], "u/r", "main")
    body = tick_marker(body, f"<!-- draft:{draft_direct['id']} -->")
    body = tick_marker(body, f"<!-- draft:{draft_card['id']} -->")
    body = tick_marker(body, f"<!-- card:{draft_card['id']} -->")

    real_fetch = publish_mod.fetch_issue
    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    real_comment = review.comment
    real_close = review.close_issue
    real_create_issue = review.create_issue
    real_ensure_labels = review.ensure_labels
    publish_mod.ROOT = DRAFTS_DIR.parent

    publish_calls: list = []
    facebook.publish_photo = lambda image_path, caption, api_version, first_comment=None: (
        publish_calls.append(caption) or {"url": "https://fb.example/cd", "id": "1"})

    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "approved"}]}
    comments: list = []
    review.comment = lambda issue_number, text: comments.append((issue_number, text))
    review.close_issue = lambda issue_number: None
    create_issue_calls: list = []

    def fake_create_issue(title, body, labels=None):
        create_issue_calls.append({"title": title, "body": body, "labels": labels})
        return {"number": 9933, "html_url": "https://x/issues/9933"}

    review.create_issue = fake_create_issue
    ensure_labels_calls: list = []
    review.ensure_labels = lambda: ensure_labels_calls.append(1)

    real_repo = os.environ.get("GITHUB_REPOSITORY")
    os.environ["GITHUB_REPOSITORY"] = "user/trendnews"
    sys.argv = ["publish", "--issue", "8858", "--now"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo
        review.comment = real_comment
        review.close_issue = real_close
        review.create_issue = real_create_issue
        review.ensure_labels = real_ensure_labels
        if real_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo

    check("publish.main ينتهي بنجاح", code == 0, f"exit={code}")
    check("المعتمَد بلا 🎴 نُشر فورًا",
          store.load_draft(draft_direct["id"])[1]["status"] == "published",
          store.load_draft(draft_direct["id"])[1].get("status"))
    check("نُشر منشور واحد فقط عبر فيسبوك (المؤجَّل لم يُنشر)",
          publish_calls == [draft_direct["caption"]], publish_calls)

    persisted_card = store.load_draft(draft_card["id"])[1]
    check("المعتمَد مع 🎴 لم يُنشر -- بقي pending",
          persisted_card.get("status") == "pending", persisted_card.get("status"))
    check("بطاقته بُنيت فعلًا رغم عدم النشر",
          bool(persisted_card.get("image")), persisted_card.get("image"))

    check("Issue مراجعة نهائي واحد فُتح", len(create_issue_calls) == 1, create_issue_calls)
    if create_issue_calls:
        opened = create_issue_calls[0]
        check("بوسم final-review", opened["labels"] == ["final-review"], opened["labels"])
        check("عنوانه يبدأ بـ🎴 مراجعة نهائية", opened["title"].startswith("🎴 مراجعة نهائية"),
              opened["title"])
        check("جسمه يحوي معرّف المنشور المؤجَّل",
              f"<!-- draft:{draft_card['id']} -->" in opened["body"])
        check("جسمه يعرض رابط البطاقة المبنيّة فعليًا",
              "raw.githubusercontent.com" in opened["body"]
              and persisted_card["image"] in opened["body"], opened["body"][:300])
        check("لا مربع 🎴 في جسم الـIssue النهائي",
              f"<!-- card:{draft_card['id']} -->" not in opened["body"])

    check("review_issue للمسودة المؤجَّلة أصبح رقم الـIssue النهائي",
          persisted_card.get("review_issue") == 9933, persisted_card.get("review_issue"))
    check("ensure_labels نُودي عند فتح الـIssue النهائي", ensure_labels_calls == [1])
    check("تعليق على الـIssue الأولي يذكر رقم الـIssue النهائي",
          any(i == 8858 and "9933" in t for i, t in comments), comments)

def test_publish_final_review_approve_publishes_without_rebuild() -> None:
    """Issue #858، الجزء الثاني، البند 3: اعتماد Issue المراجعة النهائية
    ينشر البطاقة المبنيّة كما هي -- بلا أي استدعاء لـcards.ensure (لا إعادة
    بناء) وبلا تطبيق أي تعديل نص وارد في نص الـIssue (بخلاف المسار الأولي).
    ما لم يُعلَّم في هذا الـIssue يصير rejected بنفس آلية الرفض التلقائي
    (Issue #841)، والـIssue يُغلق بعد الاعتماد."""
    from src import cards, feedback
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    approved_draft = {
        "id": "fa0000000001", "status": "pending", "origin": "news",
        "arabic": {"post_title": "خبر جاهز للنشر النهائي"},
        "caption": "خبر جاهز للنشر النهائي\nمتن.",
        "image": "drafts/fr1.jpg", "bucket": "serious",
        "source": {"link": "https://x/fr1", "publishers": ["BBC"]},
    }
    pending_draft = {
        "id": "fa0000000002", "status": "pending", "origin": "news",
        "arabic": {"post_title": "خبر لم يُعلَّم في النهائي"}, "caption": "متن ٢",
        "image": "drafts/fr2.jpg", "bucket": "serious",
        "source": {"link": "https://x/fr2", "publishers": ["BBC"]},
    }
    for d in (approved_draft, pending_draft):
        store.save_draft(d)
    (DRAFTS_DIR / "fr1.jpg").write_bytes(b"\xff\xd8\xff")
    (DRAFTS_DIR / "fr2.jpg").write_bytes(b"\xff\xd8\xff")

    body = review.build_final_review_body([approved_draft, pending_draft], "u/r", "main")
    body = tick_marker(body, f"<!-- draft:{approved_draft['id']} -->")
    # محاولة تسريب تعديل نص عبر كتلة cap -- يجب ألا يصل النشر (بلا تعديل
    # نص على الـIssue النهائي، خلافًا للمراجعة الأولية).
    body = body.replace(approved_draft["caption"], "نص محرَّر تسلّل خطأً")

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "final-review"}]}

    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    publish_mod.ROOT = DRAFTS_DIR.parent
    publish_calls: list = []

    def fake_publish_photo(image_path, caption, api_version, first_comment=None):
        publish_calls.append(caption)
        return {"url": "https://fb.example/fr", "id": "1"}

    facebook.publish_photo = fake_publish_photo

    ensure_calls: list = []
    real_ensure = cards.ensure
    cards.ensure = lambda *a, **kw: (ensure_calls.append(1), None)[1]

    comments: list = []
    real_comment = review.comment
    review.comment = lambda issue_number, text: comments.append(text)
    closed: list = []
    real_close = review.close_issue
    review.close_issue = lambda issue_number: closed.append(issue_number)

    rejections_before = len(feedback.load())

    sys.argv = ["publish", "--issue", "8858", "--now"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo
        cards.ensure = real_ensure
        review.comment = real_comment
        review.close_issue = real_close

    check("publish.main ينتهي بنجاح على Issue نهائي", code == 0, f"exit={code}")
    check("لا استدعاء لـcards.ensure -- البطاقة مبنيّة مسبقًا",
          ensure_calls == [], ensure_calls)
    check("المعلَّم نُشر فعليًا",
          store.load_draft(approved_draft["id"])[1]["status"] == "published",
          store.load_draft(approved_draft["id"])[1].get("status"))
    check("النص المنشور هو الأصلي -- التعديل المتسرّب في نص الـIssue لم يُطبَّق",
          publish_calls == [approved_draft["caption"]], publish_calls)
    check("غير المعلَّم صار rejected",
          store.load_draft(pending_draft["id"])[1]["status"] == "rejected",
          store.load_draft(pending_draft["id"])[1].get("status"))
    check("تعليق تقرير نُشر على الـIssue النهائي", bool(comments), comments)
    check("الـIssue النهائي أُغلق", closed == [8858], closed)

    rejections_after = feedback.load()
    new_entries = rejections_after[rejections_before:]
    check("رفض واحد فقط سُجِّل في feedback", len(new_entries) == 1, new_entries)
    check("الرفض بوسم «لم يُعتمد»",
          bool(new_entries) and new_entries[0]["tag"] == "لم يُعتمد", new_entries)

def test_publish_final_review_double_publish_guard() -> None:
    """Issue #858، الجزء الثاني، البند 3: مسودة نُشرت فعلًا (مثلًا عبر
    تشغيل urgent سابق لنفس حدث وسم approved وصل هذا الـIssue النهائي قبل
    تشغيل normal، Issue #745) لا يجوز أن تُنشر ثانية -- الحارس على
    status == "published" مباشرة، نفس مبدأ youtube_publish.publish_ids."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    already_published = {
        "id": "fa0000000003", "status": "published", "origin": "news",
        "arabic": {"post_title": "خبر نُشر مسبقًا"}, "caption": "متن",
        "image": "drafts/fr3.jpg", "bucket": "serious",
        "source": {"link": "https://x/fr3", "publishers": ["BBC"]},
    }
    store.save_draft(already_published)

    body = review.build_final_review_body([already_published], "u/r", "main")
    body = tick_marker(body, f"<!-- draft:{already_published['id']} -->")

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "final-review"}]}

    publish_calls: list = []
    real_publish_photo = facebook.publish_photo
    facebook.publish_photo = lambda *a, **k: (publish_calls.append(1), {"url": "#", "id": "1"})[1]

    real_comment = review.comment
    real_close = review.close_issue
    review.comment = lambda issue_number, text: None
    closed: list = []
    review.close_issue = lambda issue_number: closed.append(issue_number)

    sys.argv = ["publish", "--issue", "8859", "--now"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        facebook.publish_photo = real_publish_photo
        review.comment = real_comment
        review.close_issue = real_close

    check("publish.main ينتهي بنجاح", code == 0, f"exit={code}")
    check("لا نشر ثانٍ فعليًا عبر فيسبوك", publish_calls == [], publish_calls)
    check("حالة المسودة تبقى published (لا تغيير)",
          store.load_draft(already_published["id"])[1]["status"] == "published")

def test_publish_final_review_back_request() -> None:
    """Issue #858، الجزء الثاني، البند 4: ↩️ في الـIssue النهائي يحذف حقل
    image (وimage_info وreview_issue معه) ويُبقي المسودة pending بلا رفض،
    فتعود مؤهَّلة لأقرب Issue مراجعة أولية بمربعات العنوان وتعديل النص
    كاملة. ↩️ يغلب ✔️ إن اجتمعا على نفس المنشور -- نفس مبدأ «الرفض يغلب
    الاعتماد» القائم قبل Issue #841."""
    from src import feedback
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    back_only = {
        "id": "fa0000000004", "status": "pending", "origin": "news",
        "arabic": {"post_title": "خبر يعود للمراجعة الأولية"}, "caption": "متن ٤",
        "image": "drafts/fr4.jpg", "image_info": {"used_original": True},
        "review_issue": 8858, "bucket": "serious",
        "source": {"link": "https://x/fr4", "publishers": ["BBC"]},
    }
    back_and_approved = {
        "id": "fa0000000005", "status": "pending", "origin": "news",
        "arabic": {"post_title": "خبر معلَّم بـ↩️ و✔️ معًا"}, "caption": "متن ٥",
        "image": "drafts/fr5.jpg", "image_info": {"used_original": True},
        "review_issue": 8858, "bucket": "serious",
        "source": {"link": "https://x/fr5", "publishers": ["BBC"]},
    }
    for d in (back_only, back_and_approved):
        store.save_draft(d)

    body = review.build_final_review_body([back_only, back_and_approved], "u/r", "main")
    body = tick_marker(body, f"<!-- back:{back_only['id']} -->")
    body = tick_marker(body, f"<!-- back:{back_and_approved['id']} -->")
    body = tick_marker(body, f"<!-- draft:{back_and_approved['id']} -->")

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "final-review"}]}

    publish_calls: list = []
    real_publish_photo = facebook.publish_photo
    facebook.publish_photo = lambda *a, **k: (publish_calls.append(1), {"url": "#", "id": "1"})[1]

    real_comment = review.comment
    real_close = review.close_issue
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: None

    rejections_before = len(feedback.load())

    sys.argv = ["publish", "--issue", "8858", "--now"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        facebook.publish_photo = real_publish_photo
        review.comment = real_comment
        review.close_issue = real_close

    check("publish.main ينتهي بنجاح", code == 0, f"exit={code}")
    check("لا نشر فعلي لأي من المسودتين", publish_calls == [], publish_calls)

    persisted_back = store.load_draft(back_only["id"])[1]
    check("↩️ وحدها: حقل image حُذف بنيويًا", "image" not in persisted_back, persisted_back)
    check("↩️ وحدها: حقل image_info حُذف أيضًا", "image_info" not in persisted_back, persisted_back)
    check("↩️ وحدها: review_issue حُذف -- تؤهَّل لأقرب مراجعة أولية جديدة",
          "review_issue" not in persisted_back, persisted_back)
    check("↩️ وحدها: الحالة تبقى pending", persisted_back.get("status") == "pending",
          persisted_back.get("status"))

    persisted_both = store.load_draft(back_and_approved["id"])[1]
    check("↩️ مع ✔️ معًا: يغلب ↩️ -- لا نشر، وحقل image حُذف أيضًا",
          "image" not in persisted_both and persisted_both.get("status") == "pending",
          persisted_both)

    rejections_after = feedback.load()
    check("لا تسجيل رفض لأي من الاثنتين", len(rejections_after) == rejections_before)

def test_publish_final_review_excludes_analysis_origin() -> None:
    """Issue #858، الجزء الثاني، البند 5: مسودة تحليل (origin=analysis) لا
    تدخل قائمة المراجعة النهائية إطلاقًا -- حتى لو حمل جسم الـIssue مربع 🎴
    لها خطأً (لا يبنيه youtube_publish فعليًا؛ محاكى هنا فقط ليثبت أن
    التوجيه لا يعتمد عليه): التقاطع مع news_ids وحده (publish.main) هو ما
    يحدّد مرشّحي المراجعة النهائية، ومسار التحليل مستبعَد منه بنيويًا."""
    from src import publish as publish_mod
    from src import youtube_publish as yp

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    yt_draft = {
        "id": "aa0000000006", "status": "pending", "origin": "analysis",
        "arabic": {"post_title": "مقال تحليل", "urgent": False},
        "headlines": ["عنوان ١", "عنوان ٢", "عنوان ٣"], "headline_selected": 0,
        "caption": "متن", "source": {},
    }
    store.save_draft(yt_draft)

    body = (f"- [x] **1. مقال تحليل**  <!-- draft:{yt_draft['id']} -->\n"
            f"  - [x] 🎴 اعرض البطاقة قبل النشر  <!-- card:{yt_draft['id']} -->\n")

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "approved"}]}

    card_calls: list = []
    real_ensure_title_card = yp.ensure_title_card

    def fake_ensure_title_card(path, draft, cfg):
        card_calls.append(draft["id"])
        store.update_draft(path, image="drafts/x.jpg")
        draft["image"] = "drafts/x.jpg"
        return True

    yp.ensure_title_card = fake_ensure_title_card

    published_ids: list = []
    real_publish_one = publish_mod.publish_one

    def fake_publish_one(path, draft, cfg):
        published_ids.append(draft["id"])
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['id']}"

    publish_mod.publish_one = fake_publish_one

    create_issue_calls: list = []
    real_create_issue = review.create_issue
    review.create_issue = lambda title, body, labels=None: (
        create_issue_calls.append(1), {"number": 1, "html_url": "#"})[1]

    real_comment = review.comment
    real_close = review.close_issue
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: None

    sys.argv = ["publish", "--issue", "8860"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        yp.ensure_title_card = real_ensure_title_card
        publish_mod.publish_one = real_publish_one
        review.create_issue = real_create_issue
        review.comment = real_comment
        review.close_issue = real_close

    check("publish.main ينتهي بنجاح", code == 0, f"exit={code}")
    check("مسودة التحليل سلكت مسارها الخاص (بطاقة عنوان بُنيت عبره)",
          card_calls == [yt_draft["id"]], card_calls)
    check("نُشرت عبر مسار التحليل لا مسار الأخبار",
          published_ids == [yt_draft["id"]], published_ids)
    check("لا Issue مراجعة نهائي فُتح لها إطلاقًا رغم مربع 🎴 المُحاكى",
          create_issue_calls == [], create_issue_calls)

def test_first_comment() -> None:
    from src.publish import first_comment_for

    cfg = load_config()
    draft = {"source": {"link": "https://bbc.com/a", "publishers": ["BBC", "Reuters"]}}

    text = first_comment_for(draft, cfg)
    check("التعليق الأول يحوي الرابط", text and "https://bbc.com/a" in text)
    check("التعليق الأول يحوي المصادر", text and "BBC" in text)

    cfg2 = load_config()
    cfg2["facebook"]["link_in_first_comment"] = False
    check("تعطيل الميزة يلغي التعليق", first_comment_for(draft, cfg2) is None)

    check("مسودة بلا رابط لا تُنتج تعليقًا",
          first_comment_for({"source": {}}, cfg) is None)

    # المتن يجب ألا يحوي الرابط عند تفعيل الميزة
    art = Article(title="T", link="https://bbc.com/a", summary="", source_name="BBC",
                  region="uk", weight=1.0, published=datetime.now(timezone.utc))
    art.cluster_sources = ["BBC"]
    body = writer.build_caption(
        {"post_title": "عنوان", "post_body": "متن", "hashtags": ["أخبار"]}, art, cfg)
    check("متن المنشور بلا رابط خارجي", "https://bbc.com/a" not in body, body[-60:])
    body2 = writer.build_caption(
        {"post_title": "عنوان", "post_body": "متن", "hashtags": ["أخبار"]}, art, cfg2)
    check("المتن يحوي الرابط عند التعطيل", "https://bbc.com/a" in body2)

def test_burst_inline_cap_zero_defers_without_sleep() -> None:
    """Issue #315: finalize يستدعي cmd_burst داخل مهمة urgent (سقفها 20
    دقيقة)، وأصغر فاصل يحسبه spaced_slots هو 30 دقيقة — أي sleep واحد
    يتجاوز السقف حتمًا. inline_cap_minutes=0 يجب أن يمنع أي sleep تمامًا:
    يُنشر المستحق الآن فقط (wait<=0)، والبقية queued بلا انتظار."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    drafts = []
    for i, score in enumerate([0.9, 0.5, 0.3]):
        d = {
            "id": f"burst{i}", "status": "pending", "score": score,
            "arabic": {"post_title": f"خبر {i}", "urgent": False},
            "image": "drafts/x.jpg", "caption": "متن", "source": {},
        }
        store.save_draft(d)
        drafts.append(d)

    sleep_calls: list = []
    real_sleep = publish_mod.time.sleep
    publish_mod.time.sleep = lambda s: sleep_calls.append(s)

    published_calls: list = []
    real_publish_one = publish_mod.publish_one

    def fake_publish_one(path, draft, cfg):
        published_calls.append(draft["id"])
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['id']}"

    publish_mod.publish_one = fake_publish_one

    try:
        code = publish_mod.cmd_burst(
            [d["id"] for d in drafts], cfg, None, inline_cap_minutes=0)
    finally:
        publish_mod.time.sleep = real_sleep
        publish_mod.publish_one = real_publish_one

    check("cmd_burst بلا انتظار داخلي ينتهي بنجاح", code == 0, f"exit={code}")
    check("لا استدعاء sleep إطلاقًا (لا يتجاوز سقف مهمة urgent)",
          sleep_calls == [], str(sleep_calls))
    check("الأعلى مؤشرًا وحده نُشر فورًا (wait<=0)",
          published_calls == ["burst0"], str(published_calls))

    statuses = {d["id"]: store.load_draft(d["id"])[1]["status"] for d in drafts}
    check("البقية عُلّمت queued لا published",
          statuses["burst0"] == "published"
          and statuses["burst1"] == "queued"
          and statuses["burst2"] == "queued", str(statuses))
    check("موعد نشر مؤجَّل محفوظ للمتبقي (يلتقطه سيّر نشر الطابور)",
          "publish_at" in store.load_draft("burst1")[1])

def test_burst_urgent_still_immediate_with_inline_cap_zero() -> None:
    """العاجل يخرج فورًا مهما كان حجم الدفعة — inline_cap_minutes=0 يمسّ
    البقية العادية فقط، ولا يغيّر منطق العاجل (wait=0 بلا شرط) إطلاقًا."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    urgent = {"id": "urg0", "status": "pending", "score": 0.1,
              "arabic": {"post_title": "عاجل", "urgent": True},
              "image": "drafts/x.jpg", "caption": "متن", "source": {}}
    normal = {"id": "norm0", "status": "pending", "score": 0.9,
              "arabic": {"post_title": "عادي", "urgent": False},
              "image": "drafts/x.jpg", "caption": "متن", "source": {}}
    store.save_draft(urgent)
    store.save_draft(normal)

    real_sleep = publish_mod.time.sleep
    publish_mod.time.sleep = lambda s: (_ for _ in ()).throw(
        AssertionError(f"sleep({s}) استُدعي رغم inline_cap_minutes=0"))

    published_calls: list = []
    real_publish_one = publish_mod.publish_one

    def fake_publish_one(path, draft, cfg):
        published_calls.append(draft["id"])
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['id']}"

    publish_mod.publish_one = fake_publish_one

    try:
        code = publish_mod.cmd_burst(
            ["urg0", "norm0"], load_config(), None, inline_cap_minutes=0)
    finally:
        publish_mod.time.sleep = real_sleep
        publish_mod.publish_one = real_publish_one

    check("cmd_burst مع عاجل ينتهي بنجاح", code == 0, f"exit={code}")
    check("العاجل نُشر فورًا رغم inline_cap_minutes=0",
          "urg0" in published_calls, str(published_calls))
    check("العادي أُجِّل للطابور بلا نشر فوري",
          "norm0" not in published_calls, str(published_calls))

def test_scheduling() -> None:
    from src.schedule import assign_slots, describe, is_due

    tz, peak = "Europe/Istanbul", [12, 18, 21]
    dawn = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)      # 03:00 محليًا
    slots = assign_slots(4, peak, tz, 120, now=dawn)

    check("الاعتماد فجرًا لا يُنشر فورًا", all(s > dawn for s in slots))
    hours = [s.astimezone(__import__("zoneinfo").ZoneInfo(tz)).hour for s in slots]
    check("كل المواعيد في ساعات الذروة", set(hours) <= set(peak), str(hours))
    check("المواعيد مرتبة تصاعديًا",
          all(slots[i] < slots[i + 1] for i in range(len(slots) - 1)))

    gaps = [(slots[i + 1] - slots[i]).total_seconds() / 60 for i in range(len(slots) - 1)]
    check("الفاصل الأدنى محترم", all(g >= 120 for g in gaps), str(gaps))

    evening = datetime(2026, 8, 1, 15, 30, tzinfo=timezone.utc)  # 18:30 محليًا
    quick = assign_slots(2, peak, tz, 120, now=evening)
    check("داخل الذروة يُنشر الأول فورًا", quick[0] == evening)

    taken = [datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)]
    avoid = assign_slots(1, peak, tz, 120, taken=taken, now=evening)
    check("لا تصادم مع موعد محجوز",
          abs((avoid[0] - taken[0]).total_seconds()) >= 7200)

    check("is_due يميّز الماضي", is_due(dawn, dawn + timedelta(hours=1)))
    check("is_due يميّز المستقبل", not is_due(dawn + timedelta(hours=1), dawn))
    check("صياغة الموعد بالتوقيت المحلي", "12:00" in describe(slots[0], tz))

def test_due_publishes_one_at_a_time() -> None:
    """Issue #327 البند 2: لو فاتت queue.yml تشغيلة أو أكثر، تتراكم عدة
    مسودات مستحقة معًا. cmd_due يجب ألا ينشرها كلها في حلقة واحدة بلا
    فاصل — هذا هو النمط الآلي الذي صُمم spaced_slots لتجنّبه أصلًا.
    ينشر الأقدم موعدًا فقط، ويترك الباقي queued للتشغيلة التالية."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    ids = ["due_old", "due_mid", "due_new"]
    for i, did in enumerate(ids):
        d = {
            "id": did, "status": "queued",
            "publish_at": (now - timedelta(minutes=90 - i * 10)).isoformat(),
            "arabic": {"post_title": f"خبر {did}", "urgent": False},
            "image": "drafts/x.jpg", "caption": "متن", "source": {},
        }
        store.save_draft(d)

    published_calls: list = []
    real_publish_one = publish_mod.publish_one

    def fake_publish_one(path, draft, cfg):
        published_calls.append(draft["id"])
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['id']}"

    publish_mod.publish_one = fake_publish_one

    comment_calls: list = []
    real_comment = review.comment
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))

    try:
        code = publish_mod.cmd_due(load_config())
    finally:
        publish_mod.publish_one = real_publish_one
        review.comment = real_comment

    check("cmd_due ينتهي بنجاح", code == 0, f"exit={code}")
    check("منشور واحد فقط نُشر رغم ثلاثة مستحقة معًا",
          published_calls == ["due_old"], str(published_calls))

    statuses = {did: store.load_draft(did)[1]["status"] for did in ids}
    check("الأقدم وحده published والبقية ما زالت queued بانتظار التشغيلة التالية",
          statuses == {"due_old": "published", "due_mid": "queued",
                       "due_new": "queued"}, str(statuses))

def test_publish_skips_broken_draft_without_stopping_batch() -> None:
    """Issue #707: مسودة يوتيوب تُبنى بلا حقل image عمدًا حتى الاعتماد
    (Issue #680)، بينما الأنبوب العام يفترض وجوده. لو تسرّبت مسودة كهذه
    إلى الطابور العام (خلطًا في فتح Issue المراجعة، لا مقصودًا)، كانت
    ``publish_one`` ترفع ``KeyError`` وتُسقط الدفعة كلها بدل تخطّي مسودة
    واحدة. الآن: (أ) ``queued_drafts`` يتجاهل مسودات ``origin: youtube``
    فلا تدخل طابور ``cmd_queue``/``cmd_due`` أصلًا، و(ب) ``publish_one``
    يتخطى أي مسودة ناقصة حقلًا أساسيًا (بصرف النظر عن الأصل) ويسجّلها
    ``failed`` بدل رفع استثناء — فمسودة معطوبة واحدة لا توقف بقية دفعة
    منشورات سليمة."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    # (أ) مسودة يوتيوب متسرّبة إلى الطابور العام (status=queued) بلا حقل
    # image — نفس الحالة الموصوفة في العطل.
    yt_leaked = {
        "id": "yt_leaked", "status": "queued", "origin": "youtube",
        "publish_at": datetime.now(timezone.utc).isoformat(),
        "arabic": {"post_title": "مقال يوتيوب", "urgent": False},
        "caption": "متن", "source": {},
    }
    store.save_draft(yt_leaked)
    rows = publish_mod.queued_drafts()
    check("queued_drafts يتجاهل مسودة يوتيوب المتسرّبة",
          all(d["id"] != "yt_leaked" for _, d in rows),
          str([d["id"] for _, d in rows]))

    # (ب) دفعة من ثلاث مسودات عامة، الوسطى ناقصة حقل image (تعطّب بيانات
    # لا صلة له بيوتيوب — الفحص في publish_one عام لا خاص بالأصل).
    def make(did: str, with_image: bool) -> dict:
        d = {
            "id": did, "status": "pending",
            "arabic": {"post_title": f"خبر {did}", "urgent": False},
            "caption": "متن", "source": {},
        }
        if with_image:
            d["image"] = "drafts/batch.jpg"
        return d

    for d in (make("g1", True), make("bad", False), make("g2", True)):
        store.save_draft(d)

    (DRAFTS_DIR / "batch.jpg").write_bytes(b"\xff\xd8\xff")  # JPEG وهمية يكفي وجودها

    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    publish_mod.ROOT = DRAFTS_DIR.parent  # كي يوافق "drafts/batch.jpg" مسار DRAFTS_DIR المؤقت
    facebook.publish_photo = lambda *a, **k: {"url": "https://fb.example/x", "id": "1"}
    try:
        code = publish_mod.cmd_now(["g1", "bad", "g2"], load_config(), None)
    finally:
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo

    check("cmd_now ينتهي بنجاح رغم مسودة معطوبة بينها", code == 0, f"exit={code}")
    check("المسودة الأولى نُشرت", store.load_draft("g1")[1]["status"] == "published")
    check("المسودة الناقصة سُجّلت failed بلا استثناء",
          store.load_draft("bad")[1]["status"] == "failed",
          store.load_draft("bad")[1].get("status"))
    check("المسودة الثالثة نُشرت رغم تعطّب ما قبلها في نفس الدفعة",
          store.load_draft("g2")[1]["status"] == "published")

def test_burst_skips_broken_draft_without_spacing_sleep() -> None:
    """Issue #740، العطل الثاني الفعلي: أربع مسودات (خرجت failed فورًا داخل
    publish_one لنقصان حقل أساسي) انتظر لها cmd_burst فاصل النشر الكامل
    (30-60 دقيقة) قبل كل واحدة، كأنها ستُنشر فعلًا — نحو ثلاث ساعات جمود
    لأربع مسودات لم تُنشر شيئًا. الآن: مسودة ستُتخطى حتمًا (ناقصة حقلًا
    أساسيًا) تمرّ فورًا بلا أي sleep — الفاصل يُطبَّق فقط قبل مسودة قابلة
    للنشر فعليًا."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    good = {
        "id": "spacing_good", "status": "pending", "score": 0.9,
        "arabic": {"post_title": "خبر سليم", "urgent": False},
        "image": "drafts/x.jpg", "caption": "متن", "source": {},
    }
    bad = {
        "id": "spacing_bad", "status": "pending", "score": 0.1,
        "arabic": {"post_title": "مسودة ناقصة", "urgent": False},
        "caption": "متن", "source": {},
        # بلا حقل image عمدًا -- ستُسجَّل failed فورًا داخل publish_one
    }
    store.save_draft(good)
    store.save_draft(bad)
    (DRAFTS_DIR / "x.jpg").write_bytes(b"\xff\xd8\xff")

    sleep_calls: list = []
    real_sleep = publish_mod.time.sleep
    publish_mod.time.sleep = lambda s: sleep_calls.append(s)

    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    publish_mod.ROOT = DRAFTS_DIR.parent
    facebook.publish_photo = lambda *a, **k: {"url": "https://fb.example/z", "id": "3"}

    try:
        code = publish_mod.cmd_burst(["spacing_good", "spacing_bad"], load_config(), None)
    finally:
        publish_mod.time.sleep = real_sleep
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo

    check("cmd_burst ينتهي بنجاح", code == 0, f"exit={code}")
    check("لا استدعاء sleep إطلاقًا رغم فاصل 30-60 دقيقة المجدول قبل المسودة الناقصة",
          sleep_calls == [], str(sleep_calls))
    check("المسودة السليمة (الأعلى مؤشرًا) نُشرت فورًا",
          store.load_draft("spacing_good")[1]["status"] == "published",
          store.load_draft("spacing_good")[1].get("status"))
    check("المسودة الناقصة سُجّلت failed بلا انتظار",
          store.load_draft("spacing_bad")[1]["status"] == "failed",
          store.load_draft("spacing_bad")[1].get("status"))

def test_publish_routes_youtube_origin_by_field_not_label() -> None:
    """Issue #740، العطل الأول الفعلي: مراجع وسم Issue مراجعة يوتيوب
    (`youtube-review`، يستعمل نفس صيغة ``<!-- draft:id -->`` وreview.parse_approved
    المشتركة مع المسار العام) بـ`approved` سهوًا بدل `youtube-approved` —
    فالتقط publish.yml (سير نشر الأخبار) أربع مسودات يوتيوب الناقصة حقل
    image بنيويًا (Issue #680) وسجّلها failed. الآن publish.main يقرأ حقل
    origin لكل مسودة معتمَدة على حدة، بصرف النظر عن وسم/عنوان الـIssue،
    ويوجّه مسودة origin=youtube إلى youtube_publish.publish_ids (بطاقة
    تُبنى، سقف يُطبَّق) فتُنشر بدل أن تُسجَّل failed."""
    from src import publish as publish_mod
    from src import youtube_publish as yp

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    yt_draft = {
        "id": "abc123abcdef", "status": "pending", "origin": "youtube",
        "arabic": {"post_title": "مقال يوتيوب", "urgent": False},
        "headlines": ["عنوان ١", "عنوان ٢", "عنوان ٣"], "headline_selected": 0,
        "caption": "متن", "source": {},
        # بلا حقل image عمدًا -- ensure_title_card يضيفه لاحقًا (Issue #680)
    }
    store.save_draft(yt_draft)

    body = f"- [x] **1. مقال يوتيوب**  <!-- draft:{yt_draft['id']} -->"

    real_fetch = publish_mod.fetch_issue
    # الوسم approved -- هو الخاطئ فعليًا (لا youtube-approved) -- ونفس عنوان
    # Issue مراجعة يوتيوب. التوجيه بالأصل يجب ألا يعتمد على أيّهما.
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "approved"}],
    }

    card_calls: list = []
    real_ensure_title_card = yp.ensure_title_card

    def fake_ensure_title_card(path, draft, cfg):
        card_calls.append(draft["id"])
        store.update_draft(path, image="drafts/x.jpg")
        draft["image"] = "drafts/x.jpg"
        return True

    yp.ensure_title_card = fake_ensure_title_card

    published_ids: list = []
    real_publish_one = publish_mod.publish_one

    def fake_publish_one(path, draft, cfg):
        published_ids.append(draft["id"])
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['id']}"

    publish_mod.publish_one = fake_publish_one

    comments: list = []
    real_comment = review.comment
    review.comment = lambda issue_number, text: comments.append(text)
    closed: list = []
    real_close = review.close_issue
    review.close_issue = lambda issue_number: closed.append(issue_number)

    sys.argv = ["publish", "--issue", "7401"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        yp.ensure_title_card = real_ensure_title_card
        publish_mod.publish_one = real_publish_one
        review.comment = real_comment
        review.close_issue = real_close

    check("publish.main ينتهي بنجاح", code == 0, f"exit={code}")
    check("مسودة يوتيوب المعتمَدة بوسم approved سلكت مسار يوتيوب (بطاقة بُنيت)",
          card_calls == [yt_draft["id"]], card_calls)
    check("النشر تمّ فعليًا عبر publish_one -- لا failed",
          published_ids == [yt_draft["id"]], published_ids)
    check("حالة المسودة published لا failed",
          store.load_draft(yt_draft["id"])[1]["status"] == "published",
          store.load_draft(yt_draft["id"])[1].get("status"))
    check("تعليق تقرير نُشر على الـIssue", bool(comments), comments)
    check("الـIssue أُغلق (سقف يغطي المعتمَد كله)", closed == [7401], closed)

def test_publish_routes_news_origin_unaffected() -> None:
    """Issue #740 (ضابط): مسودة أخبار عادية (origin != youtube) معتمَدة
    بوسم approved يجب أن تسلك مسار الأخبار تمامًا كسابقًا — التوجيه بالأصل
    لا يغيّر سلوك المسار العام، ولا يستدعي منطق يوتيوب إطلاقًا."""
    from src import publish as publish_mod
    from src import youtube_publish as yp

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    news_draft = {
        "id": "beef00000001", "status": "pending",
        "arabic": {"post_title": "خبر عادي", "urgent": False},
        "image": "drafts/n.jpg", "caption": "متن", "source": {},
    }
    store.save_draft(news_draft)
    (DRAFTS_DIR / "n.jpg").write_bytes(b"\xff\xd8\xff")

    body = f"- [x] **1. خبر عادي**  <!-- draft:{news_draft['id']} -->"

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "approved"}],
    }

    yt_calls: list = []
    real_publish_ids = yp.publish_ids
    yp.publish_ids = lambda *a, **kw: (yt_calls.append(1), ([], 0, 0, []))[1]

    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    publish_mod.ROOT = DRAFTS_DIR.parent
    facebook.publish_photo = lambda *a, **k: {"url": "https://fb.example/y", "id": "2"}

    comments: list = []
    real_comment = review.comment
    review.comment = lambda issue_number, text: comments.append(text)
    real_close = review.close_issue
    review.close_issue = lambda issue_number: None

    sys.argv = ["publish", "--issue", "7402", "--now"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        yp.publish_ids = real_publish_ids
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo
        review.comment = real_comment
        review.close_issue = real_close

    check("publish.main ينتهي بنجاح (مسودة أخبار عادية)", code == 0, f"exit={code}")
    check("لا استدعاء لمنطق يوتيوب إطلاقًا", yt_calls == [], yt_calls)
    check("المسودة الإخبارية نُشرت عبر مسار الأخبار كسابقًا",
          store.load_draft(news_draft["id"])[1]["status"] == "published",
          store.load_draft(news_draft["id"])[1].get("status"))

def test_publish_routes_mixed_origins_in_same_issue() -> None:
    """Issue #745: بعد توحيد وسم الاعتماد إلى `approved` وحده، صار اجتماع
    مسودة ``origin: "youtube"`` ومسودة أخبار عادية معًا، معتمَدتين معًا في
    نفس الـIssue بنفس الوسم، ممكنًا فعليًا لا نظريًا فقط -- تحقّق أن كل
    واحدة تسلك منطقها الخاص (publish.py السطور ٥٩١-٦٢٣: youtube_ids/news_ids
    مفصولتان بالأصل المخزَّن في كل مسودة، لا افتراض عدم الاجتماع)."""
    from src import publish as publish_mod
    from src import youtube_publish as yp

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    yt_draft = {
        "id": "abc123abcdef", "status": "pending", "origin": "youtube",
        "arabic": {"post_title": "مقال يوتيوب", "urgent": False},
        "headlines": ["عنوان ١", "عنوان ٢", "عنوان ٣"], "headline_selected": 0,
        "caption": "متن يوتيوب", "source": {},
    }
    store.save_draft(yt_draft)

    news_draft = {
        "id": "beef00000002", "status": "pending",
        "arabic": {"post_title": "خبر عادي", "urgent": False},
        "image": "drafts/n2.jpg", "caption": "متن خبر", "source": {},
    }
    store.save_draft(news_draft)
    (DRAFTS_DIR / "n2.jpg").write_bytes(b"\xff\xd8\xff")

    body = (f"- [x] **1. مقال يوتيوب**  <!-- draft:{yt_draft['id']} -->\n"
            f"- [x] **2. خبر عادي**  <!-- draft:{news_draft['id']} -->")

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "approved"}],
    }

    yt_card_calls: list = []
    real_ensure_title_card = yp.ensure_title_card

    def fake_ensure_title_card(path, draft, cfg):
        yt_card_calls.append(draft["id"])
        store.update_draft(path, image="drafts/x.jpg")
        draft["image"] = "drafts/x.jpg"
        return True

    yp.ensure_title_card = fake_ensure_title_card

    published_ids: list = []
    real_publish_one = publish_mod.publish_one

    def fake_publish_one(path, draft, cfg):
        published_ids.append(draft["id"])
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['id']}"

    publish_mod.publish_one = fake_publish_one

    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    publish_mod.ROOT = DRAFTS_DIR.parent
    facebook.publish_photo = lambda *a, **k: {"url": "https://fb.example/mix", "id": "9"}

    comments: list = []
    real_comment = review.comment
    review.comment = lambda issue_number, text: comments.append(text)
    closed: list = []
    real_close = review.close_issue
    review.close_issue = lambda issue_number: closed.append(issue_number)

    sys.argv = ["publish", "--issue", "7450", "--now"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        yp.ensure_title_card = real_ensure_title_card
        publish_mod.publish_one = real_publish_one
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo
        review.comment = real_comment
        review.close_issue = real_close

    check("publish.main ينتهي بنجاح (وسم approved موحَّد لأصلين معًا)",
          code == 0, f"exit={code}")
    check("مسودة يوتيوب وحدها سلكت منطقها (بطاقة عنوان بُنيت عبر ensure_title_card، لا مسودة الأخبار التي تملك image مسبقًا)",
          yt_card_calls == [yt_draft["id"]], yt_card_calls)
    check("كلتا المسودتين نُشرتا فعليًا عبر publish_one (المشتركة بين المسارين)، اليوتيوب أولًا ثم الأخبار (ترتيب publish.main)",
          published_ids == [yt_draft["id"], news_draft["id"]], published_ids)
    check("مسودة يوتيوب انتهت published لا failed",
          store.load_draft(yt_draft["id"])[1]["status"] == "published",
          store.load_draft(yt_draft["id"])[1].get("status"))
    check("مسودة الأخبار انتهت published أيضًا",
          store.load_draft(news_draft["id"])[1]["status"] == "published",
          store.load_draft(news_draft["id"])[1].get("status"))

def test_publish_urgent_only_defers_youtube_to_normal_job() -> None:
    """Issue #745: publish.yml يُشغّل urgent (--urgent-only، مهلة ٢٠ دقيقة)
    ثم normal (--skip-urgent، مهلة ١٥٠) على نفس حدث وسم approved، وكتلة
    youtube_ids كانت تقع قبل انقسام urgent/skip فتعمل في الاثنتين -- دفعة
    تحليل (٣ منشورات × ٤٠ دقيقة تباعدًا) لا تحتمل سقف ٢٠ دقيقة فتُقتل
    وظيفة urgent في منتصفها. الآن: --urgent-only لا يستدعي publish_ids
    إطلاقًا (يُؤجَّل للمسار العادي)، و--skip-urgent على نفس الـIssue
    يستدعيه مرة واحدة."""
    from src import publish as publish_mod
    from src import youtube_publish as yp

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    yt_draft = {
        "id": "abc123abcdef", "status": "pending", "origin": "youtube",
        "arabic": {"post_title": "مقال يوتيوب", "urgent": False},
        "headlines": ["عنوان ١", "عنوان ٢", "عنوان ٣"], "headline_selected": 0,
        "caption": "متن يوتيوب", "source": {},
    }
    store.save_draft(yt_draft)

    body = f"- [x] **1. مقال يوتيوب**  <!-- draft:{yt_draft['id']} -->"

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "approved"}],
    }

    yt_calls: list = []
    real_publish_ids = yp.publish_ids
    yp.publish_ids = lambda *a, **kw: (yt_calls.append(1), ([], 0, 0, []))[1]

    comments: list = []
    real_comment = review.comment
    review.comment = lambda issue_number, text: comments.append(text)

    sys.argv = ["publish", "--issue", "7460", "--urgent-only"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        yp.publish_ids = real_publish_ids
        review.comment = real_comment

    check("publish.main ينتهي بنجاح (--urgent-only، مسودة يوتيوب فقط)",
          code == 0, f"exit={code}")
    check("--urgent-only لا يستدعي publish_ids إطلاقًا (يُؤجَّل للمسار العادي)",
          yt_calls == [], yt_calls)
    check("لا تعليق على الـIssue عند التأجيل (ضجيج -- الوظيفة العادية تعالجها بعد دقائق)",
          comments == [], comments)
    check("مسودة يوتيوب بقيت pending (لم تُنشر بعد، لم تُحاول)",
          store.load_draft(yt_draft["id"])[1]["status"] == "pending",
          store.load_draft(yt_draft["id"])[1].get("status"))

    yt_calls.clear()
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "approved"}],
    }
    real_publish_ids2 = yp.publish_ids
    yp.publish_ids = lambda *a, **kw: (yt_calls.append(1), ([], 0, 0, []))[1]
    real_report_batch = yp.report_batch
    yp.report_batch = lambda *a, **kw: None

    sys.argv = ["publish", "--issue", "7460", "--skip-urgent"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        yp.publish_ids = real_publish_ids2
        yp.report_batch = real_report_batch
        review.comment = real_comment

    check("publish.main ينتهي بنجاح (--skip-urgent، نفس الـIssue)",
          code == 0, f"exit={code}")
    check("--skip-urgent يستدعي publish_ids مرة واحدة (لا مرتين)",
          yt_calls == [1], yt_calls)

def test_open_review_excludes_youtube_and_broken_drafts() -> None:
    """متابعة Issue #707: تسرّب مسودة يوتيوب لم يقف عند ``publish.py``
    وحده — ``open_review.py`` (المسار العام) كان يجمع كل مسودة ``pending``
    بلا تمييز أصل عبر ``store.pending_drafts()`` الخام، فمسودة يوتيوب لم
    تُربَط بعد بـreview_issue خاصّها (نافذة سباق موثّقة في
    ``youtube_publish.py``) قد تدخل Issue المراجعة العام خطأً، وتُسقط
    ``review.build_issue_body`` كاملة بـ``KeyError`` لأنها ناقصة حقلًا
    تعتمده بلا شرط -- نفس فشل ``publish.py`` لكن عند فتح الـ Issue لا عند
    النشر. الآن: (أ) مسودات ``origin: youtube`` تُستبعد صراحة فلا تُلمَس
    إطلاقًا (يبقى مسارها الخاص هو من يربطها بـreview_issue لاحقًا)، و(ب)
    أي مسودة عامة أخرى ناقصة حقلًا أساسيًا (caption/arabic.post_title/
    score/source.link -- ``image`` لم تعد منها، Issue #852) تُستبعد من
    نص الـ Issue وتُسجَّل ``failed`` بدل أن تُسقط بناء الـ Issue للمسودات
    السليمة معها."""
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    yt_leaked = {
        "id": "facade01", "status": "pending", "origin": "youtube",
        "arabic": {"post_title": "مقال يوتيوب"}, "caption": "متن",
        "source": {},
    }
    bad = {
        "id": "baaaad01", "status": "pending",
        "arabic": {"post_title": "خبر ناقص"}, "caption": "متن",
        "source": {"link": "https://example.com/bad"},
        # بلا حقل score عمدًا -- image لم تعد من الحقول المطلوبة (Issue
        # #852)، فحقل آخر لا يزال مطلوبًا (caption/arabic.post_title/score/
        # source.link) هو ما يجب أن يُسقط هذه المسودة الآن.
    }
    good = {
        "id": "600dcafe", "status": "pending",
        "arabic": {"post_title": "خبر سليم"}, "caption": "متن",
        "score": 2.0, "image": "drafts/or.jpg",
        "source": {"link": "https://example.com/good", "publishers": ["Reuters"]},
    }
    # مسودة سليمة بلا بطاقة بعد (Issue #852) -- الحال الطبيعية الآن لكل
    # مسودة أخبار قبل الاعتماد؛ يجب أن تُدرَج في الـIssue بلا اعتبارها
    # ناقصة، بعرض أول مرشَّح صورة خام بدلًا من البطاقة.
    good_no_card = {
        "id": "900dcafe", "status": "pending",
        "arabic": {"post_title": "خبر سليم بلا بطاقة بعد"}, "caption": "متن",
        "score": 3.0,
        "source": {"link": "https://example.com/good2", "publishers": ["AP"],
                   "image_candidates": ["https://cdn.example/raw-source.jpg"]},
    }
    for d in (yt_leaked, bad, good, good_no_card):
        store.save_draft(d)

    create_issue_calls: list = []

    def fake_create_issue(title, body, labels=None):
        create_issue_calls.append({"title": title, "body": body, "labels": labels})
        return {"number": 707, "html_url": "https://github.com/u/r/issues/707"}

    real_create_issue = review.create_issue
    real_ensure_labels = review.ensure_labels
    review.create_issue = fake_create_issue
    review.ensure_labels = lambda: None

    real_repo = os.environ.get("GITHUB_REPOSITORY")
    real_ref = os.environ.get("GITHUB_REF_NAME")
    os.environ["GITHUB_REPOSITORY"] = "u/r"
    os.environ["GITHUB_REF_NAME"] = "main"
    try:
        code = open_review.main()
    finally:
        review.create_issue = real_create_issue
        review.ensure_labels = real_ensure_labels
        if real_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo
        if real_ref is None:
            os.environ.pop("GITHUB_REF_NAME", None)
        else:
            os.environ["GITHUB_REF_NAME"] = real_ref

    check("open_review.main() ينتهي بنجاح رغم مسودة يوتيوب متسرّبة وأخرى ناقصة",
          code == 0, f"exit={code}")
    check("Issue واحد فُتح لا أكثر", len(create_issue_calls) == 1,
          str(len(create_issue_calls)))
    body = create_issue_calls[0]["body"] if create_issue_calls else ""
    check("المسودتان السليمتان (بطاقة أو بلا بطاقة) ظاهرتان في نص الـ Issue",
          set(review.all_draft_ids(body)) == {"600dcafe", "900dcafe"},
          str(review.all_draft_ids(body)))

    check("مسودة يوتيوب المتسرّبة لم تُلمَس إطلاقًا (لا review_issue، تبقى pending)",
          store.load_draft("facade01")[1] == yt_leaked,
          store.load_draft("facade01")[1])
    check("المسودة الناقصة سُجّلت failed بلا استثناء يُسقط بناء الـ Issue",
          store.load_draft("baaaad01")[1]["status"] == "failed",
          store.load_draft("baaaad01")[1].get("status"))
    check("المسودة السليمة رُبطت بالـ Issue المفتوح",
          store.load_draft("600dcafe")[1].get("review_issue") == 707,
          store.load_draft("600dcafe")[1].get("review_issue"))
    check("المسودة السليمة بلا بطاقة لم تُعامَل كمتسرّبة -- رُبطت بالـIssue أيضًا",
          store.load_draft("900dcafe")[1].get("review_issue") == 707,
          store.load_draft("900dcafe")[1].get("review_issue"))
    check("مسودة بلا بطاقة: صورة المصدر الخام تُعرض بدلًا من البطاقة",
          "https://cdn.example/raw-source.jpg" in body, body)

def test_review_sort_by_score() -> None:
    """Issue #874: العرض يُرتَّب تنازليًا بحقل ``score`` — لا بترتيب
    القراءة من القرص. الشاهد الحرفي من الـIssue: مرشحون بدرجات 20.4، 29.8،
    16.9، 17.9 كما وردوا من القرص يجب أن يظهروا 29.8، 20.4، 17.9، 16.9.
    عنصر بلا درجة رقمية يُعامَل كأدنى قيمة (الذيل، بلا انهيار)، وعنصران
    بنفس الدرجة يحتفظان بترتيبهما النسبي (استقرار ``sorted``)."""
    rows = [
        {"id": "a", "score": 20.4},
        {"id": "b", "score": 29.8},
        {"id": "c", "score": 16.9},
        {"id": "d", "score": 17.9},
    ]
    ordered = review.sort_by_score(rows)
    check("الشاهد الحرفي: 29.8 ثم 20.4 ثم 17.9 ثم 16.9",
          [r["id"] for r in ordered] == ["b", "a", "d", "c"],
          [r["id"] for r in ordered])

    with_missing = [
        {"id": "x", "score": 5.0},
        {"id": "y"},  # بلا حقل score إطلاقًا
        {"id": "z", "score": "غير رقمي"},  # درجة غير رقمية
        {"id": "w", "score": 9.0},
    ]
    ordered2 = review.sort_by_score(with_missing)
    check("عنصر بلا score رقمي يقع في الذيل بلا انهيار",
          [r["id"] for r in ordered2] == ["w", "x", "y", "z"],
          [r["id"] for r in ordered2])

    tied = [
        {"id": "first", "score": 5.0},
        {"id": "second", "score": 5.0},
        {"id": "third", "score": 5.0},
    ]
    ordered3 = review.sort_by_score(tied)
    check("تعادل الدرجة يحافظ على الترتيب الأصلي (استقرار sorted)",
          [r["id"] for r in ordered3] == ["first", "second", "third"],
          [r["id"] for r in ordered3])

    # عبر مفتاح غير مباشر (صفوف (path, dict) كما في open_review.py)
    tuple_rows = [("pa", {"score": 1.0}), ("pb", {"score": 9.0})]
    ordered4 = review.sort_by_score(tuple_rows, key=lambda row: row[1])
    check("يعمل عبر key= لصفوف (path, dict)",
          [p for p, _ in ordered4] == ["pb", "pa"], ordered4)

def test_open_review_orders_drafts_by_score() -> None:
    """Issue #874، الشاهد الحرفي: أربع مسودات بدرجات 20.4، 29.8، 16.9، 17.9
    محفوظة بترتيب مسار ملف عشوائي يجب أن تظهر في نص Issue المراجعة الأولية
    مرتَّبة تنازليًا 29.8، 20.4، 17.9، 16.9 -- لا بترتيب القراءة من القرص."""
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    def _draft(id_, score):
        return {
            "id": id_, "status": "pending", "score": score,
            "arabic": {"post_title": f"خبر {id_}"}, "caption": "متن",
            "source": {"link": f"https://example.com/{id_}", "publishers": ["Reuters"]},
        }

    # ترتيب الحفظ هنا هو نفسه ترتيب الشاهد في الـIssue (20.4 ثم 29.8 ثم
    # 16.9 ثم 17.9) -- عمدًا مختلف عن ترتيب الدرجة، ليثبت أن الترتيب
    # المعروض من الدرجة لا من ترتيب القراءة (مسار الملف).
    ids_and_scores = [
        ("dead0204", 20.4), ("dead0298", 29.8),
        ("dead0169", 16.9), ("dead0179", 17.9),
    ]
    for id_, score in ids_and_scores:
        store.save_draft(_draft(id_, score))

    create_issue_calls: list = []

    def fake_create_issue(title, body, labels=None):
        create_issue_calls.append({"title": title, "body": body, "labels": labels})
        return {"number": 874, "html_url": "https://github.com/u/r/issues/874"}

    real_create_issue = review.create_issue
    real_ensure_labels = review.ensure_labels
    review.create_issue = fake_create_issue
    review.ensure_labels = lambda: None

    real_repo = os.environ.get("GITHUB_REPOSITORY")
    real_ref = os.environ.get("GITHUB_REF_NAME")
    os.environ["GITHUB_REPOSITORY"] = "u/r"
    os.environ["GITHUB_REF_NAME"] = "main"
    try:
        code = open_review.main()
    finally:
        review.create_issue = real_create_issue
        review.ensure_labels = real_ensure_labels
        if real_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo
        if real_ref is None:
            os.environ.pop("GITHUB_REF_NAME", None)
        else:
            os.environ["GITHUB_REF_NAME"] = real_ref

    check("open_review.main ينتهي بنجاح", code == 0, f"exit={code}")
    check("Issue واحد فُتح", len(create_issue_calls) == 1, len(create_issue_calls))
    body = create_issue_calls[0]["body"] if create_issue_calls else ""
    check("المسودات مرتَّبة تنازليًا بالدرجة: 29.8 ثم 20.4 ثم 17.9 ثم 16.9",
          review.all_draft_ids(body) ==
          ["dead0298", "dead0204", "dead0179", "dead0169"],
          review.all_draft_ids(body))

def test_open_review_orders_candidates_by_score() -> None:
    """نفس الشاهد الحرفي، لكن لمرشحي preselect (Issue الاختيار) -- عناوين
    عربية عمدًا كي يتخطّى translate_titles الترجمة بلا استدعاء شبكة."""
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    def _candidate(id_, score):
        return {
            "id": id_, "status": "pending", "title": f"عنوان خبر {id_}", "score": score,
            "publishers": ["Reuters"], "link": f"https://example.com/{id_}",
            "bucket": "serious",
        }

    ids_and_scores = [
        ("cafe0204", 20.4), ("cafe0298", 29.8),
        ("cafe0169", 16.9), ("cafe0179", 17.9),
    ]
    for id_, score in ids_and_scores:
        store.save_candidate(_candidate(id_, score))

    create_issue_calls: list = []

    def fake_create_issue(title, body, labels=None):
        create_issue_calls.append({"title": title, "body": body, "labels": labels})
        return {"number": 875, "html_url": "https://github.com/u/r/issues/875"}

    real_create_issue = review.create_issue
    real_ensure_labels = review.ensure_labels
    review.create_issue = fake_create_issue
    review.ensure_labels = lambda: None

    real_repo = os.environ.get("GITHUB_REPOSITORY")
    real_ref = os.environ.get("GITHUB_REF_NAME")
    os.environ["GITHUB_REPOSITORY"] = "u/r"
    os.environ["GITHUB_REF_NAME"] = "main"
    try:
        code = open_review.main()
    finally:
        review.create_issue = real_create_issue
        review.ensure_labels = real_ensure_labels
        if real_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo
        if real_ref is None:
            os.environ.pop("GITHUB_REF_NAME", None)
        else:
            os.environ["GITHUB_REF_NAME"] = real_ref

    check("open_review.main ينتهي بنجاح (مسار المرشحين)", code == 0, f"exit={code}")
    check("Issue اختيار واحد فُتح", len(create_issue_calls) == 1, len(create_issue_calls))
    body = create_issue_calls[0]["body"] if create_issue_calls else ""
    cand_marker = re.compile(r"<!--\s*cand:([0-9a-zA-Z]+)\s*-->")
    check("المرشحون مرتَّبون تنازليًا بالدرجة: 29.8 ثم 20.4 ثم 17.9 ثم 16.9",
          cand_marker.findall(body) ==
          ["cafe0298", "cafe0204", "cafe0179", "cafe0169"],
          cand_marker.findall(body))

def test_publish_final_review_orders_by_score() -> None:
    """Issue #874: مسودات المراجعة النهائية (🎴) تُعرض مرتَّبة تنازليًا
    بالدرجة أيضًا -- سواء عبر publish.py (مسار الاعتماد الأولي مع 🎴) أو
    collect_finalize.py (مسار 🎴 المباشر من preselect)."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    def _draft(id_, score):
        return {
            "id": id_, "status": "pending", "score": score, "bucket": "serious",
            "state_media": False, "origin": "news",
            "caption": f"خبر {id_}\nمتن الخبر.",
            "source": {"link": f"https://x/{id_}", "publishers": ["BBC"],
                       "image_candidates": ["https://cdn.example/ok.jpg"]},
            "arabic": {"post_title": f"خبر {id_}", "category": "", "urgent": False},
        }

    # ترتيب الحفظ (=ترتيب مسار الملف) مختلف عمدًا عن ترتيب الدرجة.
    ids_and_scores = [
        ("face0204", 20.4), ("face0298", 29.8),
        ("face0169", 16.9), ("face0179", 17.9),
    ]
    drafts = [_draft(id_, score) for id_, score in ids_and_scores]
    for d in drafts:
        store.save_draft(d)

    body = review.build_issue_body(drafts, "u/r", "main")
    for d in drafts:
        body = tick_marker(body, f"<!-- draft:{d['id']} -->")
        body = tick_marker(body, f"<!-- card:{d['id']} -->")

    real_fetch = publish_mod.fetch_issue
    real_root = publish_mod.ROOT
    real_comment = review.comment
    real_create_issue = review.create_issue
    real_ensure_labels = review.ensure_labels
    publish_mod.ROOT = DRAFTS_DIR.parent

    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "approved"}]}
    review.comment = lambda issue_number, text: None
    create_issue_calls: list = []

    def fake_create_issue(title, body, labels=None):
        create_issue_calls.append({"title": title, "body": body, "labels": labels})
        return {"number": 9934, "html_url": "https://x/issues/9934"}

    review.create_issue = fake_create_issue
    review.ensure_labels = lambda: None

    real_repo = os.environ.get("GITHUB_REPOSITORY")
    os.environ["GITHUB_REPOSITORY"] = "user/trendnews"
    sys.argv = ["publish", "--issue", "8859", "--now"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        publish_mod.ROOT = real_root
        review.comment = real_comment
        review.create_issue = real_create_issue
        review.ensure_labels = real_ensure_labels
        if real_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo

    check("publish.main ينتهي بنجاح", code == 0, f"exit={code}")
    check("Issue مراجعة نهائي واحد فُتح", len(create_issue_calls) == 1, create_issue_calls)
    body_out = create_issue_calls[0]["body"] if create_issue_calls else ""
    check("مسودات المراجعة النهائية مرتَّبة تنازليًا بالدرجة: "
          "29.8 ثم 20.4 ثم 17.9 ثم 16.9",
          review.all_draft_ids(body_out) ==
          ["face0298", "face0204", "face0179", "face0169"],
          review.all_draft_ids(body_out))

def test_collect_finalize_card_review_orders_by_score() -> None:
    """Issue #874: نفس الترتيب التنازلي بالدرجة، لكن لمسار 🎴 المباشر من
    Issue الاختيار (collect_finalize.py، لا publish.py)."""
    from src import collect_finalize, preselect
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)

    def _art(slug, title, score):
        # art.score (لا حقل score في قاموس المرشح وحده) هو ما ينتقل فعليًا
        # إلى حقل "score" في المسودة الناتجة (collect_finalize._build_draft:
        # ``"score": round(art.score, 2)``) -- ضبطه هنا إلزامي، لا يكفي
        # ضبط cand["score"] بعد بناء المرشح.
        return Article(title=title, link=f"https://pre.example/{slug}",
                       summary="", source_name=slug, region="rc", weight=1.0,
                       published=now, bucket="serious", publisher=slug,
                       image_url="https://cdn.example/card-source.jpg",
                       score=score)

    # ترتيب البناء/الحفظ هنا (20.4 ثم 29.8 ثم 16.9 ثم 17.9) هو نفسه الشاهد
    # الحرفي في الـIssue، ومختلف عمدًا عن ترتيب الدرجة تنازليًا. معرّف
    # المرشح (art.uid) يبقى كما بناه build_candidate -- الصياغة تُبقي نفس
    # المعرّف للمسودة الناتجة (Issue #860)، فلا داعي لتخصيصه يدويًا.
    specs = [("beef0204", 20.4), ("beef0298", 29.8),
             ("beef0169", 16.9), ("beef0179", 17.9)]
    cands = []
    for slug, score in specs:
        cand = preselect.build_candidate(_art(slug, f"خبر {slug}", score))
        store.save_candidate(cand)
        cands.append(cand)
    expected_order = [c["id"] for c in
                      sorted(cands, key=lambda c: c["score"], reverse=True)]

    body = preselect.build_selection_issue_body(cands)
    for c in cands:
        body = tick_marker(body, f"sel-card:{c['id']}")

    real_burst = publish_mod.cmd_burst
    real_create_issue = review.create_issue
    real_comment = review.comment
    real_ensure_labels = review.ensure_labels
    real_close_issue = review.close_issue
    real_write = collect_finalize.write_arabic
    publish_mod.cmd_burst = lambda *a, **kw: 0
    collect_finalize.write_arabic = writer.write_arabic
    create_issue_calls: list = []

    def fake_create_issue(title, body, labels=None):
        create_issue_calls.append({"title": title, "body": body, "labels": labels})
        return {"number": 9945, "html_url": "https://x/issues/9945"}

    review.create_issue = fake_create_issue
    review.comment = lambda issue_number, text: None
    review.ensure_labels = lambda: None
    review.close_issue = lambda issue_number: None

    real_repo = os.environ.get("GITHUB_REPOSITORY")
    real_ref = os.environ.get("GITHUB_REF_NAME")
    os.environ["GITHUB_REPOSITORY"] = "user/trendnews"
    os.environ["GITHUB_REF_NAME"] = "main"
    try:
        code = collect_finalize.finalize(4874, body, load_config())
    finally:
        publish_mod.cmd_burst = real_burst
        review.create_issue = real_create_issue
        review.comment = real_comment
        review.ensure_labels = real_ensure_labels
        review.close_issue = real_close_issue
        collect_finalize.write_arabic = real_write
        if real_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo
        if real_ref is None:
            os.environ.pop("GITHUB_REF_NAME", None)
        else:
            os.environ["GITHUB_REF_NAME"] = real_ref

    check("collect_finalize.finalize ينتهي بنجاح", code == 0, f"exit={code}")
    final_issue = next((c for c in create_issue_calls
                        if c["labels"] == ["final-review"]), None)
    check("Issue مراجعة نهائية بوسم final-review فُتح", final_issue is not None,
          create_issue_calls)
    if final_issue:
        check("مسودات 🎴 مرتَّبة تنازليًا بالدرجة: 29.8 ثم 20.4 ثم 17.9 ثم 16.9",
              review.all_draft_ids(final_issue["body"]) == expected_order,
              review.all_draft_ids(final_issue["body"]))

def test_origin_of_synonyms() -> None:
    """Issue #749: store.origin_of هي الدالّة الوحيدة التي تحسم أصل مسودة —
    بثلاثة مرادفات للقديم على القرص (لا تُعدَّل المسودات القديمة نفسها،
    الدالّة وحدها تتكفّل بها)، وتمرّر القيم المعيارية الست كما هي."""
    check("origin_of: مرادف youtube القديم ← analysis",
          store.origin_of({"origin": "youtube"}) == "analysis")
    check("origin_of: مرادف collect القديم (decisions.py سابقًا) ← news",
          store.origin_of({"origin": "collect"}) == "news")
    check("origin_of: الغياب (المسار العادي/الرادار القديمان) ← news",
          store.origin_of({}) == "news")
    check("CANONICAL_ORIGINS يطابق القيم الست في CLAUDE.md",
          store.CANONICAL_ORIGINS
          == {"news", "breaking", "request", "verify", "article", "analysis"},
          store.CANONICAL_ORIGINS)
    for value in store.CANONICAL_ORIGINS:
        check(f"origin_of: القيمة المعيارية «{value}» تمرّ كما هي",
              store.origin_of({"origin": value}) == value)

    # CANONICAL_ORIGINS كانت ثابتة ميتة (تصحيح لاحق لـ#749) — الآن تُستعمل
    # لتسجيل تحذير عند قيمة غير معيارية وغير مرادفة، بلا أي تغيير في القيمة
    # المُعادة (لا تغيير سلوك).
    class _ListHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.messages: list[str] = []

        def emit(self, record):
            self.messages.append(record.getMessage())

    log_handler = _ListHandler()
    store.log.addHandler(log_handler)
    try:
        result = store.origin_of({"origin": "typo_value"})
    finally:
        store.log.removeHandler(log_handler)
    check("origin_of: قيمة غير معيارية تُعاد كما هي بلا تغيير سلوك",
          result == "typo_value", result)
    check("origin_of: قيمة غير معيارية وغير مرادفة تُسجَّل بتحذير",
          any("typo_value" in m for m in log_handler.messages), log_handler.messages)

def test_feedback_records_origin_and_screening_guidance_excludes_analysis() -> None:
    """Issue #749 (تصحيح لاحق): feedback.record يسجّل أصل المسودة عبر
    store.origin_of، وscreening_guidance يبني توجيهه من مدخلات news/breaking/
    غياب الحقل فقط — رفض مقال تحليل لا يجوز أن يُبرمج فرز الأخبار."""
    from src import feedback

    analysis_draft = {
        "id": "an1", "origin": "analysis",
        "arabic": {"post_title": "عنوان تحليل حصري لا يتكرر فرز"},
        "source": {"title": "عنوان تحليل حصري لا يتكرر فرز", "publishers": [], "region": ""},
        "bucket": "",
    }
    news_draft = {
        "id": "nw1", "origin": "news",
        "arabic": {"post_title": "خبر عادي"},
        "source": {"title": "خبر عادي", "publishers": ["BBC"], "region": "eu"},
        "bucket": "serious",
    }
    legacy_draft = {   # سجل قديم بلا حقل origin أصلًا
        "id": "lg1",
        "arabic": {"post_title": "خبر قديم قبل هذا الحقل"},
        "source": {"title": "خبر قديم قبل هذا الحقل", "publishers": [], "region": ""},
        "bucket": "",
    }

    entries: list = []
    feedback.record(entries, analysis_draft, "تافه", "")
    feedback.record(entries, news_draft, "محلي", "")
    feedback.record(entries, legacy_draft, "قديم", "")

    check("feedback.record يسجّل origin=analysis عبر store.origin_of",
          entries[0]["origin"] == "analysis", entries[0])
    check("feedback.record يسجّل origin=news عبر store.origin_of",
          entries[1]["origin"] == "news", entries[1])

    guidance = feedback.screening_guidance(entries, limit=12, days=21)
    check("screening_guidance يستبعد مدخلة origin=analysis",
          "تحليل حصري" not in guidance, guidance)
    check("screening_guidance يضمّ مدخلة news",
          "خبر عادي" in guidance, guidance)
    check("screening_guidance يضمّ مدخلة قديمة بلا حقل origin (لا انقطاع في التغذية)",
          "خبر قديم قبل هذا الحقل" in guidance, guidance)

def test_feedback_screening_guidance_excludes_not_selected() -> None:
    """Issue #843 بند ١: screening_guidance كانت تستبعد وسم «لم يُعتمد»
    فقط ونسيت «لم يُختر» (Issue #280) رغم أنهما يقولان الشيء نفسه بالضبط
    — «لم يُنشر» لا «لماذا». القياس الذي كشف الخلل: ٦٦٤ من ٧٠٠ مدخلة في
    state/rejections.json موسومة «لم يُختر»، فخانات التوجيه الاثنتا عشرة
    كانت تمتلئ بها بلا أي سبب حقيقي."""
    from src import feedback

    now = datetime.now(timezone.utc).isoformat()
    entries = [
        {"id": "a", "tag": "لم يُختر", "note": "", "title": "خبر لم يُختر",
         "source_title": "خبر لم يُختر", "publishers": [], "region": "",
         "bucket": "", "origin": "news", "at": now},
        {"id": "b", "tag": "مكرر", "note": "", "title": "خبر مكرر",
         "source_title": "خبر مكرر", "publishers": [], "region": "",
         "bucket": "", "origin": "news", "at": now},
    ]
    guidance = feedback.screening_guidance(entries, limit=12, days=21)
    check("مدخلة «لم يُختر» لا تظهر في توجيه الفرز (لا تصف سببًا)",
          "خبر لم يُختر" not in guidance, guidance)
    check("مدخلة «مكرر» تظهر في توجيه الفرز (سبب حقيقي)",
          "خبر مكرر" in guidance, guidance)

def test_radar_writes_breaking_origin() -> None:
    """مواضع الكتابة السبعة (Issue #749) — radar.py:build_draft يكتب
    origin=breaking صراحةً لكل مسودة عاجلة يبنيها الرادار مباشرة (لا عبر
    preselect_fallback، الذي يبني مرشحًا خامًا بلا هذا الحقل أصلًا)."""
    from src import radar
    from src.sources import Article

    art = Article(title="بركان يثور ويقذف الرماد لأميال في السماء",
                 link="https://example.com/radar-origin-check",
                 summary="", source_name="X", region="global", weight=1.0,
                 published=datetime.now(timezone.utc), score=30.0, group_sources=5)

    real_write = radar.write_arabic

    def fake_write(article, cfg, retries=3, previous_post=None, source_docs=None):
        return {"urgent": True, "category": "عالم", "angle": "خبر",
                "image_headline": "عنوان", "post_title": "عنوان", "post_body": "نص",
                "hashtags": []}

    # radar.build_draft لم تعد تبني بطاقة إطلاقًا (Issue #852) -- لا حاجة
    # لتمويه build_post_image هنا بعد الآن.
    radar.write_arabic = fake_write
    try:
        draft = radar.build_draft(art, load_config(), urgent=True, docs=[])
    finally:
        radar.write_arabic = real_write

    check("radar.build_draft ينتج مسودة", draft is not None, draft)
    check("radar.py يكتب origin=breaking صراحةً (Issue #749)",
          bool(draft) and draft.get("origin") == "breaking",
          draft.get("origin") if draft else None)

def test_request_writes_request_origin() -> None:
    """مواضع الكتابة السبعة (Issue #749) — request.py يمرّر origin="request"
    عبر extra إلى radar.build_draft، فيُكتب الحقل "request" لا "breaking"
    (القيمة الافتراضية في radar.py نفسها لمساره العاجل)."""
    from src import request as rq

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    art = Article(title="زلزال قوي يضرب هرات", link="https://example.com/request-origin-check",
                 summary="", source_name="s", region="global", weight=1.0,
                 published=datetime.now(timezone.utc))

    real_fetch_source = rq.fetch_source
    rq.fetch_source = lambda src, max_age_hours: [art]
    real_is_dup = store.is_duplicate
    store.is_duplicate = lambda *a, **kw: False

    captured: dict = {}
    real_build_draft = rq.radar.build_draft

    def fake_build_draft(article, cfg, urgent=False, extra=None, docs=None):
        captured["extra"] = extra
        return {"id": article.uid, "score": 1.0,
                # post_body لازم الآن (Issue #756) -- request.py يستدعي
                # headlines_mod.headlines_for_post(post_title, post_body, ...)
                # بعد نجاح build_draft، فغيابه كان يُسقط الاختبار بـ KeyError
                # لا علاقة له بما يختبره هذا التست فعليًا (توجيه origin).
                "arabic": {"post_title": article.title, "post_body": "نص تجريبي"},
                "origin": (extra or {}).get("origin", "breaking")}

    rq.radar.build_draft = fake_build_draft

    sys.argv = ["request", "--query", "زلزال هرات", "--days", "7"]
    try:
        code = rq.main()
    finally:
        rq.fetch_source = real_fetch_source
        store.is_duplicate = real_is_dup
        rq.radar.build_draft = real_build_draft

    check("request.main ينتهي بنجاح", code == 0, f"exit={code}")
    check("request.py يمرّر origin=request في extra إلى radar.build_draft",
          captured.get("extra", {}).get("origin") == "request", captured)
    saved = store.load_draft(art.uid)
    check("المسودة المحفوظة تحمل origin=request فعليًا",
          saved is not None and saved[1].get("origin") == "request",
          saved[1].get("origin") if saved else None)

def test_decisions() -> None:
    """Issue #583 — المرحلة الأولى: سجل قرارات تراكمي (state/decisions.json)،
    جمع بلا أي تحليل أو تأثير على الفرز/الترتيب."""
    from src import decisions

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    if decisions.DECISIONS_FILE.exists():
        decisions.DECISIONS_FILE.unlink()

    published_draft = {
        "id": "dec_pub1", "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending", "score": 5.5, "bucket": "serious",
        "trend_score": 0.4, "velocity": 0.2, "has_photo": True, "state_media": False,
        "source": {"region": "eu", "publishers": ["BBC", "Reuters"]},
        "arabic": {"category": "عالم", "angle": "خبر", "urgent": False,
                   "post_body": "نص المنشور هنا"},
    }
    decisions.record_published(published_draft)
    entries = decisions.load()
    check("النشر يُسجَّل بقرار published",
          any(e["id"] == "dec_pub1" and e["decision"] == "published" for e in entries))
    rec = next(e for e in entries if e["id"] == "dec_pub1")
    check("السمات تُستخرج من المسودة بلا حقول جديدة",
          rec["category"] == "عالم" and rec["source_count"] == 2
          and rec["bucket"] == "serious"
          # القيمة المعيارية عبر store.origin_of: مسودة بلا حقل origin ← news
          # (Issue #749 — كانت "collect" قبل توحيد القيم).
          and rec["origin"] == "news",
          str(rec))

    before = len(decisions.load())
    decisions.record_published(published_draft)
    check("لا تكرار عند تسجيل نفس المسودة مرتين", len(decisions.load()) == before)

    rejected_draft = dict(published_draft, id="dec_rej1")
    decisions.record_rejected(rejected_draft, "ضعيف")
    rec2 = next(e for e in decisions.load() if e["id"] == "dec_rej1")
    check("الرفض الصريح يُسجَّل بوسمه",
          rec2["decision"] == "rejected_explicit" and rec2["reject_tag"] == "ضعيف",
          str(rec2))

    # الفحص الدوري بلا بيئة Actions: لا شيء يُفحص، بلا عطل
    saved_repo = os.environ.pop("GITHUB_REPOSITORY", None)
    saved_token = os.environ.pop("GITHUB_TOKEN", None)
    check("scan بلا بيئة Actions يعيد صفرًا بأمان", decisions.scan(load_config()) == 0)

    now = datetime.now(timezone.utc)
    old_pending = {
        "id": "dec_old1", "created_at": (now - timedelta(hours=100)).isoformat(),
        "status": "pending", "review_issue": 501, "score": 1.0, "bucket": "serious",
        "source": {}, "arabic": {},
    }
    fresh_pending = {
        "id": "dec_fresh1", "created_at": now.isoformat(),
        "status": "pending", "review_issue": 502, "score": 1.0, "bucket": "serious",
        "source": {}, "arabic": {},
    }
    closed_pending = {
        "id": "dec_closed1", "created_at": now.isoformat(),
        "status": "pending", "review_issue": 503, "score": 1.0, "bucket": "serious",
        "source": {}, "arabic": {},
    }
    # مسودة تحليل قديمة بلا حقل image بنيويًا (Issue #680/#749): decisions.scan
    # يجب ألا يستثنيها (هي تحليلية، واستبعادها يُعمي التقرير الأسبوعي عن
    # مسار يجري توسيعه) ويجب ألا ينهار عليها — لا شيء في _features يقرأ image.
    analysis_pending = {
        "id": "dec_analysis1", "created_at": (now - timedelta(hours=100)).isoformat(),
        "status": "pending", "review_issue": 504, "origin": "analysis",
        "score": 1.0, "bucket": "serious",
        "source": {"publishers": ["Ch1"]}, "arabic": {"post_title": "تحليل"},
    }
    for d in (old_pending, fresh_pending, closed_pending, analysis_pending):
        store.save_draft(d)

    os.environ["GITHUB_REPOSITORY"] = "u/r"
    os.environ["GITHUB_TOKEN"] = "tok"

    real_fetch_issue = decisions._fetch_issue
    decisions._fetch_issue = lambda n: {"state": "closed" if n == 503 else "open"}

    cfg = load_config()
    cfg["decisions"] = {"ignore_timeout_hours": 48}
    try:
        n = decisions.scan(cfg)
    finally:
        decisions._fetch_issue = real_fetch_issue
        os.environ.pop("GITHUB_REPOSITORY", None)
        os.environ.pop("GITHUB_TOKEN", None)
        if saved_repo is not None:
            os.environ["GITHUB_REPOSITORY"] = saved_repo
        if saved_token is not None:
            os.environ["GITHUB_TOKEN"] = saved_token

    check("scan سجّل ثلاثة قرارات ضمنية (المهلة ×2 + الإغلاق)", n == 3, str(n))
    entries = decisions.load()
    check("مسودة قديمة مفتوحة ← ignored_timeout", any(
        e["id"] == "dec_old1" and e["decision"] == "ignored_timeout" for e in entries))
    check("مسودة حديثة مفتوحة لم تُبتّ بعد — لا تُسجَّل",
          not any(e["id"] == "dec_fresh1" for e in entries))
    check("مسودة Issue أُغلق ← dismissed_closed", any(
        e["id"] == "dec_closed1" and e["decision"] == "dismissed_closed" for e in entries))
    check("مسودة تحليل قديمة مفتوحة أيضًا ← ignored_timeout (لا استثناء لمسار التحليل)",
          any(e["id"] == "dec_analysis1" and e["decision"] == "ignored_timeout"
              for e in entries))
    rec_analysis = next(e for e in entries if e["id"] == "dec_analysis1")
    check("أصل المسودة التحليلية يُسجَّل analysis عبر store.origin_of",
          rec_analysis["origin"] == "analysis", str(rec_analysis))

def test_insights_analysis() -> None:
    from src.insights import analyse, engagement, recommendations

    check("المشاركة أثقل من الإعجاب",
          engagement({"shares": 1}) > engagement({"reactions": 4}))
    check("التعليق أثقل من الإعجاب",
          engagement({"comments": 1}) > engagement({"reactions": 2}))

    base = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc).isoformat()
    rows = []
    for i in range(6):   # رائجة وقوية
        rows.append({"id": f"t{i}", "title": "رائج", "category": "تقنية", "urgent": False,
                     "trend_score": 0.9, "state_media": False, "publishers": ["BBC"],
                     "published_at": base, "has_photo": True, "reactions": 100,
                     "comments": 10, "shares": 10, "engagement": 180})
    for i in range(6):   # غير رائجة وضعيفة
        rows.append({"id": f"n{i}", "title": "عادي", "category": "ثقافة", "urgent": False,
                     "trend_score": 0.0, "state_media": False, "publishers": ["TASS"],
                     "published_at": base, "has_photo": False, "reactions": 10,
                     "comments": 1, "shares": 0, "engagement": 13})

    a = analyse(rows, "Europe/Istanbul")
    check("التحليل يحسب العدد", a["count"] == 12)
    check("الأفضل أداءً في المقدمة", a["top"][0]["engagement"] == 180)
    check("التصنيف الأقوى أولًا", a["categories"][0][0] == "تقنية")
    check("مقارنة الترند محسوبة", a["trend"][0] > a["trend"][2])

    recs = recommendations(a, load_config())
    check("recommendations تعيد قواميس لا نصوصًا (Issue #769)",
          all(isinstance(r, dict) and "id" in r and "text" in r for r in recs), recs)
    joined = " ".join(r["text"] for r in recs)
    check("يوصي برفع وزن الترند", "ارفع" in joined and "trends.weight" in joined, joined[:120])
    check("يوصي بناءً على الصور", "صورة" in joined or "المصادر" in joined)
    trend_rec = next(r for r in recs if r["key"] == "trends.weight")
    check("مقترح trends.weight يحمل current/suggested رقميين",
          isinstance(trend_rec["current"], float) and isinstance(trend_rec["suggested"], float),
          trend_rec)

    check("لا انهيار مع بيانات فارغة", analyse([], "UTC") == {})

def test_insights_collect_includes_analysis_origin() -> None:
    """Issue #749: insights.collect لا يستثني مسار التحليل (هو نفسه تحليلي،
    واستبعاده يُعمي التقرير الأسبوعي عن مسار يجري توسيعه)، ولا ينهار على
    مسودة بلا حقل image — لا شيء في collect() يقرأ draft["image"] مباشرة،
    فتُعامَل مسودة تحليل بلا هذا الحقل كأي مسودة أخرى بلا أي حراسة إضافية."""
    from src import insights

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    analysis_draft = {
        "id": "ins_analysis1", "status": "published", "origin": "analysis",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "arabic": {"post_title": "مقال تحليل", "category": "تحليل", "urgent": False},
        "trend_score": 0.0, "state_media": False,
        "source": {"publishers": ["Ch1", "Ch2"]},
        "facebook": {"post_id": "999"},
        # بلا حقل image عمدًا — القيمة الفعلية بعد الاعتماد، لكن collect()
        # لا يفترضها أصلًا فلا يهم غيابها هنا.
    }
    store.save_draft(analysis_draft)

    real_fetch_metrics = facebook.fetch_metrics
    facebook.fetch_metrics = lambda post_id, api_version: {
        "reactions": 5, "comments": 1, "shares": 1}
    try:
        rows = insights.collect(30, "v21.0")
    finally:
        facebook.fetch_metrics = real_fetch_metrics

    check("insights.collect لا ينهار على مسودة تحليل بلا حقل image، وتظهر في المخرجات",
          any(r["id"] == "ins_analysis1" for r in rows), rows)

def test_insights_weakest_performing_section() -> None:
    """Issue #769: قسم «📉 أضعف أداءً» نظير «🏆 الأفضل أداءً» القائم -- يعرض
    أدنى خمسة تفاعلًا لا أعلاها، بنفس شكل الجدول."""
    from src.insights import analyse, build_report

    base = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc).isoformat()
    rows = [
        {"id": f"r{i}", "title": f"خبر {i}", "category": "عالم", "urgent": False,
         "trend_score": 0.0, "state_media": False, "publishers": ["X"],
         "published_at": base, "has_photo": True,
         "reactions": i * 10, "comments": 0, "shares": 0, "engagement": i * 10}
        for i in range(1, 8)
    ]
    a = analyse(rows, "UTC")
    check("bottom يحمل خمس مسودات لا ثلاثًا", len(a["bottom"]) == 5, a["bottom"])
    check("bottom تصاعدي -- الأدنى تفاعلًا أولًا",
          [r["engagement"] for r in a["bottom"]] == sorted(r["engagement"] for r in rows)[:5])

    report = build_report(a, [], 30)
    weakest_idx = report.index("#### 📉 أضعف أداءً")
    best_idx = report.index("#### 🏆 الأفضل أداءً")
    check("قسم «أضعف أداءً» يظهر بعد «الأفضل أداءً»", weakest_idx > best_idx)
    weakest_block = report[weakest_idx:report.index("####", weakest_idx + 5)]
    check("قسم «أضعف أداءً» يعرض القيمة الأدنى فعليًا (10) لا الأعلى (70)",
          "| 10 |" in weakest_block and "| 70 |" not in weakest_block, weakest_block)

def test_insights_rejections_section() -> None:
    """Issue #769: قائمة «🚫 ما رُفض» الكاملة تلتزم نافذة التقرير وسقف ٤٠
    مدخلة، وتُعلن الفائض بسطر «و N أخرى»."""
    from src.insights import rejections_section

    now = datetime.now(timezone.utc)
    entries = [
        {"id": f"rej{i}", "tag": "ضعيف", "note": "", "title": f"عنوان {i}",
         "source_title": "", "publishers": [], "region": "", "bucket": "",
         "origin": "news", "at": (now - timedelta(days=1)).isoformat()}
        for i in range(45)
    ]
    entries.append({
        "id": "old1", "tag": "قديم", "note": "", "title": "قديم جدًا خارج النافذة",
        "source_title": "", "publishers": [], "region": "", "bucket": "",
        "origin": "news", "at": (now - timedelta(days=90)).isoformat(),
    })

    lines = rejections_section(entries, days=30, limit=40)
    body = "\n".join(lines)
    check("قائمة المرفوضات مطوية داخل <details>", "<details>" in body and "</details>" in body)
    check("لا تتجاوز السقف ٤٠ مدخلة معروضة",
          sum(1 for ln in lines if ln.startswith("- **عنوان")) == 40, body)
    check("تُعلن الفائض بسطر «و N أخرى»", "و 5 أخرى" in body, body)
    check("مدخلة خارج نافذة الأيام لا تظهر", "قديم جدًا" not in body)
    check("لا قائمة إطلاقًا إن لم تكن هناك مرفوضات ضمن النافذة",
          rejections_section([], days=30) == [])

def test_insights_recommendation_ids_and_choice_parsing() -> None:
    """Issue #769: id المقترح لا يتغيّر حين تتغيّر أرقام نصّه وحدها؛
    parse_recommendation_choices تقرأ القبول والرفض وتتجاهل ما لم يُعلَّم."""
    from src.insights import parse_recommendation_choices, recommendations

    cfg = load_config()

    def make_a(best_avg, worst_avg):
        return {
            "count": 20,
            "categories": [("تقنية", best_avg, 3), ("اقتصاد", 5.0, 3), ("ثقافة", worst_avg, 3)],
            "hours": [], "trend": (0, 0, 0, 0), "photo": (0, 0, 0, 0), "publishers": [],
        }

    recs1 = recommendations(make_a(90.0, 10.0), cfg)
    recs2 = recommendations(make_a(120.0, 5.0), cfg)
    cat_rec1 = next(r for r in recs1 if "تصنيف" in r["text"])
    cat_rec2 = next(r for r in recs2 if "تصنيف" in r["text"])
    check("id المقترح بلا key ثابت رغم تغيّر الأرقام فيه فقط",
          cat_rec1["id"] == cat_rec2["id"], (cat_rec1, cat_rec2))

    body = (
        f"- [x] ✅ أقبل  <!-- rec:{cat_rec1['id']}:yes -->\n"
        f"- [ ] ❌ أرفض  <!-- rec:{cat_rec1['id']}:no -->\n"
        "- [ ] ✅ أقبل  <!-- rec:trends.weight:yes -->\n"
        "- [x] ❌ أرفض  <!-- rec:trends.weight:no -->\n"
        "- [ ] ✅ أقبل  <!-- rec:fp_untouched:yes -->\n"
        "- [ ] ❌ أرفض  <!-- rec:fp_untouched:no -->\n"
    )
    choices = parse_recommendation_choices(body)
    check("قبول مُعلَّم يُقرأ yes", choices.get(cat_rec1["id"]) == "yes", choices)
    check("رفض مُعلَّم يُقرأ no", choices.get("trends.weight") == "no", choices)
    check("مقترح لم يُعلَّم عليه لا يظهر في القرارات إطلاقًا",
          "fp_untouched" not in choices, choices)

def test_insights_sync_does_not_refresh_unchanged_decision() -> None:
    """Issue #769: sync_previous_decisions لا يُحدّث decided_at حين يقرأ
    القرار نفسه مرة أخرى (نفس Issue قد يُقرأ أكثر من مرة قبل فتح تقرير
    جديد، مثلًا أسبوع بلا مسودات) -- وإلا تمدَّدت نافذة الثمانية أسابيع
    بلا نهاية طالما لم يتغيّر شيء فعليًا."""
    from src import insights

    if insights.DECISIONS_FILE.exists():
        insights.DECISIONS_FILE.unlink()

    insights._save_last_issue(4242, [
        {"id": "fp_stale_rec", "text": "مقترح ثابت", "key": None, "suggested": None},
    ])
    fake_body = ("- [x] ❌ أرفض  <!-- rec:fp_stale_rec:no -->\n"
                 "- [ ] ✅ أقبل  <!-- rec:fp_stale_rec:yes -->\n")

    real_fetch_body = review.fetch_issue_body
    review.fetch_issue_body = lambda issue_number: fake_body  # type: ignore
    try:
        insights.sync_previous_decisions()
        first_decided_at = insights._load_decisions()["fp_stale_rec"]["decided_at"]

        insights.sync_previous_decisions()
        second_decided_at = insights._load_decisions()["fp_stale_rec"]["decided_at"]
    finally:
        review.fetch_issue_body = real_fetch_body

    check("قراءة نفس القرار مرتين لا تُحدّث decided_at",
          first_decided_at == second_decided_at,
          (first_decided_at, second_decided_at))

    if insights.LAST_ISSUE_FILE.exists():
        insights.LAST_ISSUE_FILE.unlink()
    if insights.DECISIONS_FILE.exists():
        insights.DECISIONS_FILE.unlink()

def test_insights_closed_loop() -> None:
    """Issue #769: الحلقة المغلقة -- مقترح مرفوض لا يظهر في التقرير التالي
    ويظهر بعد ثمانية أسابيع؛ مقترح مقبول ولم تتغيّر قيمته يظهر «لم تُطبَّق
    بعد»، وإن تغيّرت يظهر «طُبّقت» ويسقط من التتبّع؛ وغياب
    insights_last_issue.json لا يُسقط التشغيلة."""
    from src import insights

    if insights.LAST_ISSUE_FILE.exists():
        insights.LAST_ISSUE_FILE.unlink()
    if insights.DECISIONS_FILE.exists():
        insights.DECISIONS_FILE.unlink()

    # غياب insights_last_issue.json (أول تشغيلة بعد هذا التغيير) لا ينهار
    insights.sync_previous_decisions()

    cfg = load_config()
    now = datetime.now(timezone.utc)

    decisions = {
        "trends.weight": {
            "id": "trends.weight", "text": "مقترح رفع وزن الترند",
            "key": "trends.weight", "suggested": 999.0,
            "decision": "accepted", "decided_at": now.isoformat(), "reported": False,
        },
        "fp_reject_fresh": {
            "id": "fp_reject_fresh", "text": "مقترح رُفض للتو",
            "key": None, "suggested": None,
            "decision": "rejected", "decided_at": now.isoformat(), "reported": False,
        },
        "fp_reject_old": {
            "id": "fp_reject_old", "text": "مقترح رُفض قبل تسعة أسابيع",
            "key": None, "suggested": None,
            "decision": "rejected",
            "decided_at": (now - timedelta(days=63)).isoformat(), "reported": True,
        },
    }
    insights._save_decisions(decisions)

    hidden = insights.suppressed_ids(insights._load_decisions())
    check("مقترح رُفض حديثًا يبقى مخفيًا (أقل من ٨ أسابيع)",
          "fp_reject_fresh" in hidden, hidden)
    check("مقترح رُفض قبل تسعة أسابيع لم يعد مخفيًا",
          "fp_reject_old" not in hidden, hidden)

    lines = insights.decisions_report(cfg)
    body = "\n".join(lines)
    check("مقترح مقبول ولم تتغيّر قيمته يظهر «لم تُطبَّق بعد» (⏳)",
          "⏳" in body and "trends.weight" in body, body)
    check("مقترح رُفض للتو يظهر مرة واحدة في «قراراتك السابقة»",
          "رفضتَ" in body, body)

    stored = insights._load_decisions()
    check("مقترح لم يُطبَّق بعد يبقى في التتبّع", "trends.weight" in stored, stored)
    check("مقترح رُفض منتهي نافذة الإخفاء يُحذف من ملف التتبّع",
          "fp_reject_old" not in stored, stored)

    class FakeCfg:
        def path(self, dotted, default=None):
            return 999.0 if dotted == "trends.weight" else default

    lines2 = insights.decisions_report(FakeCfg())
    body2 = "\n".join(lines2)
    check("مقترح طُبّقت قيمته فعليًا يظهر «✅ طُبّقت»", "طُبّقت" in body2, body2)
    stored2 = insights._load_decisions()
    check("مقترح طُبّقت يُحذف من التتبّع", "trends.weight" not in stored2, stored2)

    if insights.LAST_ISSUE_FILE.exists():
        insights.LAST_ISSUE_FILE.unlink()
    if insights.DECISIONS_FILE.exists():
        insights.DECISIONS_FILE.unlink()

def _why_entry(entry_id: str, tag: str, title: str, when: datetime) -> dict:
    return {
        "id": entry_id, "tag": tag, "note": "", "title": title,
        "source_title": title, "publishers": [], "region": "", "bucket": "",
        "origin": "news", "at": when.isoformat(),
    }

def test_insights_why_not_published_section() -> None:
    """Issue #843 بند ١+٤: قسم «لماذا لم تنشر هذه؟» يعرض مدخلات
    NON_REASON_TAGS («لم يُعتمد»/«لم يُختر») حصرًا -- لا مدخلة بسبب حقيقي
    فعلي مثل «قديم» -- ويلتزم سقف ١٥ مدخلة معلنًا الفائض بسطر واحد."""
    from src import insights

    if insights.REASON_SHOWN_FILE.exists():
        insights.REASON_SHOWN_FILE.unlink()

    now = datetime.now(timezone.utc)
    entries = [
        _why_entry(f"e{i}", "لم يُعتمد" if i % 2 == 0 else "لم يُختر",
                   f"مدخلة بلا سبب {i}", now - timedelta(hours=i))
        for i in range(20)
    ]
    entries.append(_why_entry("real1", "قديم", "مدخلة بسبب حقيقي فعلي", now))

    lines = insights.why_not_published_section(entries, days=30)
    body = "\n".join(lines)

    check("القسم يظهر", "لماذا لم تنشر هذه؟" in body, body)
    check("مدخلة بسبب حقيقي فعلي (قديم) لا تظهر في هذا القسم",
          "مدخلة بسبب حقيقي فعلي" not in body, body)
    check("لا تتجاوز مدخلات NON_REASON_TAGS سقف ١٥ معروضة",
          sum(1 for ln in lines if ln.startswith("- **مدخلة بلا سبب")) == 15, body)
    check("تُعلن الفائض بسطر «و N أخرى لم تُعرض»", "و 5 أخرى لم تُعرض" in body, body)
    check("كل مدخلة معروضة تحمل صفّ مربعات بكل الأسباب التسعة الحقيقية",
          body.count("<!-- why:") == 15 * 9, body)
    check("لا قسم إطلاقًا إن لم تكن هناك مدخلات NON_REASON_TAGS ضمن النافذة",
          insights.why_not_published_section([], days=30) == [])

    if insights.REASON_SHOWN_FILE.exists():
        insights.REASON_SHOWN_FILE.unlink()

def test_insights_parse_reason_choices() -> None:
    """Issue #843 بند ٤: parse_reason_choices تقرأ المربع المعلَّم فقط
    وتتجاهل ما لم يُعلَّم -- بنفس أسلوب parse_recommendation_choices."""
    from src.insights import parse_reason_choices

    body = (
        "- **خبر ١**\n"
        "  - [x] نشرنا الحدث نفسه سابقًا  <!-- why:aaa111:مكرر -->\n"
        "  - [ ] خبر محلي صرف لا يعني القارئ العربي  <!-- why:aaa111:محلي -->\n"
        "- **خبر ٢**\n"
        "  - [ ] نشرنا الحدث نفسه سابقًا  <!-- why:bbb222:مكرر -->\n"
        "  - [ ] خبر محلي صرف لا يعني القارئ العربي  <!-- why:bbb222:محلي -->\n"
    )
    choices = parse_reason_choices(body)
    check("مربع معلَّم يُقرأ بالوسم الصحيح", choices.get("aaa111") == "مكرر", choices)
    check("مدخلة لم يُعلَّم أي مربع فيها لا تظهر في القرارات إطلاقًا",
          "bbb222" not in choices, choices)

def test_insights_reason_choice_updates_rejection_and_feeds_screening() -> None:
    """Issue #843 بند ٢+٤: إجابة على «لماذا لم تنشر هذه؟» تُحدّث وسم
    المدخلة في state/rejections.json من «لم يُعتمد» إلى السبب المختار،
    فتدخل feedback.screening_guidance تلقائيًا من بعدها -- ومدخلة أُجيبت
    لا تظهر في قسم التقرير التالي."""
    from src import feedback, insights

    if insights.LAST_ISSUE_FILE.exists():
        insights.LAST_ISSUE_FILE.unlink()
    if insights.REASON_SHOWN_FILE.exists():
        insights.REASON_SHOWN_FILE.unlink()

    entries = feedback.load()
    before = len(entries)
    now = datetime.now(timezone.utc)
    entries.append(_why_entry("draftXYZ", "لم يُعتمد", "خبر بانتظار سبب حقيقي", now))
    feedback.save(entries)

    target = feedback.load()[before]
    entry_id = insights._reason_entry_id(target)
    fake_body = f"- [x] نشرنا الحدث نفسه سابقًا  <!-- why:{entry_id}:مكرر -->\n"

    insights._save_last_issue(9191, [])
    real_fetch_body = review.fetch_issue_body
    review.fetch_issue_body = lambda issue_number: fake_body  # type: ignore
    try:
        insights.sync_previous_decisions()
    finally:
        review.fetch_issue_body = real_fetch_body

    updated = feedback.load()[before]
    check("وسم المدخلة تحدّث من «لم يُعتمد» إلى «مكرر»",
          updated["tag"] == "مكرر", updated)
    check("المدخلة تحمل ملاحظة أنها أُسندت لاحقًا", bool(updated.get("note")), updated)

    guidance = feedback.screening_guidance(feedback.load(), limit=50, days=21)
    check("المدخلة تدخل screening_guidance بعد إسناد سببها",
          "خبر بانتظار سبب حقيقي" in guidance, guidance)

    remaining = insights.why_not_published_section(feedback.load(), days=30)
    body = "\n".join(remaining)
    check("مدخلة أُجيبت عنها لا تظهر في قسم «لماذا لم تنشر هذه؟» التالي",
          "خبر بانتظار سبب حقيقي" not in body, body)

    if insights.LAST_ISSUE_FILE.exists():
        insights.LAST_ISSUE_FILE.unlink()
    if insights.REASON_SHOWN_FILE.exists():
        insights.REASON_SHOWN_FILE.unlink()

def test_insights_why_entry_shown_twice_then_drops() -> None:
    """Issue #843 بند ١: مدخلة تُركت بلا إجابة تُعرض مرة، ثم مرة واحدة
    أخرى في التقرير التالي، ثم تسقط نهائيًا في الثالث -- سؤالك عنها
    أسبوعين كافٍ."""
    from src import insights

    if insights.REASON_SHOWN_FILE.exists():
        insights.REASON_SHOWN_FILE.unlink()

    now = datetime.now(timezone.utc)
    entries = [_why_entry("left1", "لم يُختر", "مدخلة متروكة بلا إجابة", now)]

    body1 = "\n".join(insights.why_not_published_section(entries, days=30))
    check("التقرير الأول يعرض المدخلة المتروكة", "مدخلة متروكة بلا إجابة" in body1, body1)

    body2 = "\n".join(insights.why_not_published_section(entries, days=30))
    check("التقرير الثاني يعرضها مرة واحدة أخرى", "مدخلة متروكة بلا إجابة" in body2, body2)

    body3 = "\n".join(insights.why_not_published_section(entries, days=30))
    check("التقرير الثالث لا يعرضها بعد الآن (سقطت نهائيًا)",
          "مدخلة متروكة بلا إجابة" not in body3, body3)

    if insights.REASON_SHOWN_FILE.exists():
        insights.REASON_SHOWN_FILE.unlink()

def test_insights_reason_entry_id_stable_despite_order() -> None:
    """Issue #843 بند ٢: معرّف المدخلة (_reason_entry_id) مشتق من محتواها
    (معرّف المسودة + وقت تسجيلها) لا من ترتيبها في القائمة -- بلا هذا
    ينهار الربط بين تقرير وآخر إن تغيّر ترتيب المدخلات بين تشغيلتين."""
    from src import insights

    if insights.REASON_SHOWN_FILE.exists():
        insights.REASON_SHOWN_FILE.unlink()

    now = datetime.now(timezone.utc)
    e_a = _why_entry("aa", "لم يُعتمد", "مدخلة أ", now - timedelta(hours=1))
    e_b = _why_entry("bb", "لم يُختر", "مدخلة ب", now - timedelta(hours=2))
    e_c = _why_entry("cc", "لم يُعتمد", "مدخلة ج", now - timedelta(hours=3))

    id_before = insights._reason_entry_id(e_b)
    ordered = [e_a, e_b, e_c]
    shuffled = [e_c, e_b, e_a]
    id_in_ordered = insights._reason_entry_id(ordered[1])
    id_in_shuffled = insights._reason_entry_id(shuffled[1])

    check("المعرّف نفسه بصرف النظر عن موضع المدخلة في القائمة",
          id_before == id_in_ordered == id_in_shuffled,
          (id_before, id_in_ordered, id_in_shuffled))

    if insights.REASON_SHOWN_FILE.exists():
        insights.REASON_SHOWN_FILE.unlink()

def test_insights_why_section_missing_state_file() -> None:
    """Issue #843 بند ٢: غياب state/insight_reason_shown.json (أول تشغيلة
    بعد هذا التغيير) لا يُسقط بناء القسم."""
    from src import insights

    if insights.REASON_SHOWN_FILE.exists():
        insights.REASON_SHOWN_FILE.unlink()

    now = datetime.now(timezone.utc)
    entries = [_why_entry("nostate", "لم يُختر", "مدخلة بلا ملف حالة سابق", now)]
    lines = insights.why_not_published_section(entries, days=30)
    check("القسم يُبنى بنجاح رغم غياب ملف الحالة",
          "مدخلة بلا ملف حالة سابق" in "\n".join(lines), lines)

    if insights.REASON_SHOWN_FILE.exists():
        insights.REASON_SHOWN_FILE.unlink()

def test_insights_no_posts_still_shows_why_and_decisions() -> None:
    """Issue #847: الخروج المبكر في build_report (a فارغ لصفر منشورات) كان
    يُعيد سطر «لا منشورات» فقط ويتوقف قبل أي قسم -- فيحجب «❓ لماذا لم تنشر
    هذه؟» في الأسبوع الذي لا يُنشر فيه شيء، وهو أحوج الأسابيع إلى السؤال.
    الآن يواصل إلى «❓ لماذا لم تنشر هذه؟» و«📋 قراراتك السابقة» ويتخطّى
    أقسام الأداء وحدها؛ وحين لا مدخلات لهذين القسمين أيضًا يبقى السطر وحده
    بلا عناوين فارغة."""
    from src import feedback, insights

    if insights.REASON_SHOWN_FILE.exists():
        insights.REASON_SHOWN_FILE.unlink()

    now = datetime.now(timezone.utc)
    entries_with_reason = [
        _why_entry("np1", "لم يُعتمد", "خبر بلا سبب حقيقي هذا الأسبوع", now),
    ]

    real_load = feedback.load
    feedback.load = lambda: entries_with_reason  # type: ignore
    try:
        report = insights.build_report({}, [], 30)
    finally:
        feedback.load = real_load

    check("سطر «لا منشورات» موجود", "لا منشورات خلال آخر 30 يومًا" in report, report)
    check("قسم «لماذا لم تنشر هذه؟» ظاهر رغم صفر منشورات",
          "❓ لماذا لم تنشر هذه؟" in report, report)
    check("لا قسم أداء (مثلاً «الأفضل أداءً») يظهر بلا منشورات",
          "🏆 الأفضل أداءً" not in report, report)

    if insights.REASON_SHOWN_FILE.exists():
        insights.REASON_SHOWN_FILE.unlink()

    feedback.load = lambda: []  # type: ignore
    try:
        report_empty = insights.build_report({}, [], 30)
    finally:
        feedback.load = real_load

    check("صفر منشورات + صفر مدخلات: السطر وحده بلا أي عنوان قسم فارغ",
          report_empty.strip() == "### 📊 لا منشورات خلال آخر 30 يومًا", report_empty)

    if insights.REASON_SHOWN_FILE.exists():
        insights.REASON_SHOWN_FILE.unlink()

def test_collect_feedback_rejects_analysis_draft_without_image() -> None:
    """Issue #749 (تصحيح لاحق): لا src/collect_feedback.py ولا feedback.record
    يقرآن حقل image إطلاقًا — فمسودة تحليل قبل اعتمادها (Issue #680، بلا هذا
    الحقل بنيويًا) تُسجَّل رفضها بشكل عادي تمامًا كأي مسودة أخرى، ولا يجوز أن
    تبقى pending بعد رفضها الصريح (الحارس السابق كان يتخطّى
    store.update_draft(status="rejected") فتُترك المسودة عالقة قابلة
    للالتقاط مجددًا لاحقًا — عطل حقيقي، لا تحصين)."""
    from src import collect_feedback, feedback

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    analysis_draft = {
        "id": "eeee00000001", "status": "pending", "origin": "analysis",
        "arabic": {"post_title": "مقال تحليل بلا بطاقة"}, "caption": "متن",
        "source": {"publishers": ["Ch1"]},
        # بلا حقل image عمدًا
    }
    normal_draft = {
        "id": "beef00000003", "status": "pending", "origin": "news",
        "arabic": {"post_title": "خبر عادي"}, "caption": "متن",
        "image": "drafts/n3.jpg", "bucket": "serious",
        "source": {"link": "https://x/1", "publishers": ["BBC"]},
    }
    for d in (analysis_draft, normal_draft):
        store.save_draft(d)

    # مربعات الرفض حُذفت من واجهة المراجعة (Issue #841) — الطريقة الوحيدة
    # المتبقية لتسجيل سبب رفض حقيقي هي أمر /reject نصي في تعليق حرّ.
    body = "### إشعار"
    comment_a = f"/reject {analysis_draft['id']} مكرر"
    comment_b = f"/reject {normal_draft['id']} ضعيف"

    real_fetch_comments = collect_feedback.fetch_comments
    collect_feedback.fetch_comments = lambda issue_number: [body, comment_a, comment_b]
    comments: list = []
    real_comment = review.comment
    review.comment = lambda issue_number, text: comments.append(text)

    rejections_before = len(feedback.load())

    sys.argv = ["collect_feedback", "--issue", "9001"]
    try:
        code = collect_feedback.main()
    finally:
        collect_feedback.fetch_comments = real_fetch_comments
        review.comment = real_comment

    check("collect_feedback.main ينتهي بنجاح بلا انهيار", code == 0, f"exit={code}")
    check("كلا الرفضين يُسجَّلان في feedback (بطاقة أو بلا بطاقة سيّان)",
          len(feedback.load()) == rejections_before + 2,
          str(feedback.load()[-2:]))
    check("مسودة التحليل بلا بطاقة تُسجَّل rejected كأي مسودة أخرى",
          store.load_draft(analysis_draft["id"])[1]["status"] == "rejected",
          store.load_draft(analysis_draft["id"])[1].get("status"))
    check("المسودة العادية تُسجَّل rejected كسابقًا",
          store.load_draft(normal_draft["id"])[1]["status"] == "rejected",
          store.load_draft(normal_draft["id"])[1].get("status"))
