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
from PIL import Image, ImageDraw

from tests.helpers import (
    check,
    badge_probe_xy,
    card_plan,
    tick_marker,
    legacy_selection_body,
    legacy_youtube_selection_body,
    reset_last_publish,
    restore_last_publish,
    auto_restore_last_publish,
    stub_last_publish,
    install_fakes,
    _TMP_DATA_DIR,
    collect,
    evidence,
    facebook,
    headlines,
    imagesearch,
    imaging,
    names,
    names_learn,
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
from src import cards as cards_mod
from src import stages


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
    # (#1182) لا مربع على العنوان بعد الآن: الاعتماد بخيار «انشر» تحت الخبر.
    marked = tick_marker(body, f"<!-- go:publish:{drafts[0]['id']} -->") if drafts else body
    actions, _ = stages.read_actions(marked, 2)
    expected_first = {drafts[0]["id"]: "publish"} if drafts else {}
    check("قراءة خيار «انشر» تعمل", actions == expected_first, str(actions))

    marked_all = (tick_marker(marked, f"<!-- go:publish:{drafts[1]['id']} -->")
                  if len(drafts) > 1 else marked)
    check("اعتماد متعدد يعمل",
          len(stages.read_actions(marked_all, 2)[0]) == min(2, len(drafts)))

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
    from src import collect_finalize, decisions, feedback, preselect
    from src import publish as publish_mod

    if decisions.DECISIONS_FILE.exists():
        decisions.DECISIONS_FILE.unlink()

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

    read_1 = stages.read_actions(marked, 1)[0]
    now_selected = [i for i, a in read_1.items() if a == "publish"]
    check("تحليل «انشر فورًا» يلتقط المُعلَّم فقط", now_selected == [cand_a["id"]],
          str(now_selected))
    check("لا أحد عُلِّم على «صغ واعرض»",
          [i for i, a in read_1.items() if a == "go2"] == [])

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

    # Issue #954: غير المختار في Issue الاختيار (gate A) يُسجَّل في
    # state/decisions.json بقيمة decision=unselected/reject_tag=«لم يُختر»
    # -- سماته من شكل المرشح (_features_candidate) لا شكل المسودة، فالمختار
    # (صار مسودة كاملة) لا يُسجَّل هنا إطلاقًا -- نشره سيُسجَّل published
    # عبر publish_one/decisions.record_published لا هذا المسار.
    decisions_entries = decisions.load()
    check("المرشح غير المختار وحده سُجّل في decisions.json (لا المختار)",
          {e["id"] for e in decisions_entries} == {cand_b["id"]}, decisions_entries)
    unselected_entry = decisions_entries[0]
    check("قرار unselected بوسم «لم يُختر» وسمات المرشح (bucket=light)",
          unselected_entry["decision"] == "unselected"
          and unselected_entry["reject_tag"] == "لم يُختر"
          and unselected_entry["bucket"] == "light"
          and unselected_entry["origin"] == "news"
          and unselected_entry["category"] == "" and unselected_entry["body_len"] == 0,
          unselected_entry)

@auto_restore_last_publish
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
    reset_last_publish()

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

    # القارئ الموحَّد يحسم المزدوج بالأحوط فيعيد go2 للثالث (لا publish)، فيُفحص
    # الالتقاط الخام للمربعين على قضية بالشكل القديم (الجسم الجديد لا مربعات فيه)
    old_marked = legacy_selection_body([cand_now, cand_draft, cand_both])
    for key in (f"now:{cand_now['id']}", f"review:{cand_draft['id']}",
                f"now:{cand_both['id']}", f"review:{cand_both['id']}"):
        old_marked = tick_marker(old_marked, key)
    check("«انشر فورًا» يلتقط المرشح الأول والثالث (المزدوج)",
          preselect.parse_publish_now(old_marked) == [cand_now["id"], cand_both["id"]])
    check("«صغ واعرض» يلتقط المرشح الثاني والثالث (المزدوج)",
          preselect.parse_draft_review(old_marked)
          == [cand_draft["id"], cand_both["id"]])
    check("القارئ الموحَّد على القضية الجديدة: الأحوط للمزدوج = go2",
          stages.read_actions(marked, 1)[0]
          == {cand_now["id"]: "publish", cand_draft["id"]: "go2",
              cand_both["id"]: "go2"})

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
        check("مربع تبديل الصورة لم يعد يظهر في Issue «صغ واعرض» (#1182)",
              f"<!-- img:{cand_draft['id']} -->" not in opened["body"])
        check("حقل رابط الصورة يظهر في Issue «صغ واعرض»",
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
        if "أكثر من خيار انتقال" in text
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

    new_body = preselect.build_selection_issue_body([cand])
    check("خيار 🎴 في القضية الجديدة بعلامة go:go3 غير معلَّم (#1190)",
          f"- [ ] {load_config().path('stages.options.go3')}  <!-- go:go3:{cand['id']} -->"
          in new_body and f"sel-card:{cand['id']}" not in new_body, new_body)
    # القارئ القديم يبقى لقضايا فُتحت قبل التحديث: يُفحص على نص الباني القديم
    body = legacy_selection_body([cand])
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

def test_preselect_image_line() -> None:
    """Issue #1174: سطر 🖼️ لكل مرشح في قضية الاختيار — ثلاث صيغ، ولا يغيّر
    ما تقرؤه دوال القراءة (يُقارَن بنص القضية نفسه بعد حذف السطر)."""
    from src import preselect

    now = datetime.now(timezone.utc)

    def mk(n, image_url=None, members=()):
        art = Article(title=f"مرشح الصورة {n}", link=f"https://img.example/{n}",
                      summary="", source_name="IM", region="ri", weight=1.0,
                      published=now, bucket="serious", publisher="IM")
        art.image_url = image_url
        art.cluster_members = list(members)
        return preselect.build_candidate(art)

    c_a = mk("a", "https://cdn.pub.example/p/1.jpg")
    c_b = mk("b", None, [
        {"name": "X", "link": "https://img.example/b"},   # رابط الخبر نفسه
        {"name": "Y", "link": "https://y.example/b"},
        {"name": "Z", "link": "https://z.example/b"}])
    c_c = mk("c")
    c_e = mk("e")
    del c_e["article"]                                    # مرشح قديم بلا article

    def line_of(cand):
        body = preselect.build_selection_issue_body([cand])
        # سطر 🖼️ القائم وحده، لا سطر حقل الصورة (stages.image_field يحمل 🖼️ أيضًا)
        return [l for l in body.splitlines() if l.startswith("  🖼️")]

    check("صيغة 1: رابط الناشر والنطاق",
          line_of(c_a) == ["  🖼️ [صورة الناشر](https://cdn.pub.example/p/1.jpg)"
                           " · cdn.pub.example"], line_of(c_a))
    check("صيغة 2: N = 2 (يُستثنى رابط الخبر نفسه)",
          line_of(c_b) == ["  🖼️ بلا صورة من الناشر · ستُجرَّب صور ناشرَين آخرَين "
                           "ثم بحث الويب"], line_of(c_b))
    check("صيغة 3: بلا صورة ولا بدائل",
          line_of(c_c) == ["  🖼️ بلا صورة من الناشر ولا بدائل · بحث الويب وحده"],
          line_of(c_c))
    check("مرشح قديم بلا مفتاح article ← صيغة 3 بلا خطأ",
          line_of(c_e) == line_of(c_c))
    check("السطر بلا علامة HTML ولا مربع",
          all("<!--" not in l and "[ ]" not in l
              for c in (c_a, c_b, c_c) for l in line_of(c)))

    body = preselect.build_selection_issue_body([c_a, c_b, c_c])
    print("\n----- نص قضية الاختبار (d) -----\n" + body + "\n-----")
    check("جملة الشرح حاضرة",
          load_config().path("stages.explainer_stage1") in body
          and "سطر 🖼️ يبيّن" not in body)
    marked = tick_marker(body, f"now:{c_a['id']}")
    marked = tick_marker(marked, f"review:{c_b['id']}")
    marked = tick_marker(marked, f"sel-card:{c_c['id']}")
    marked = tick_marker(marked, f"sel-card:{c_b['id']}")
    stripped = "\n".join(l for l in marked.splitlines()
                         if not l.startswith("  🖼️"))
    check("السطر أُزيل فعلًا في النسخة المقارَنة",
          stripped != marked and "ناشر آخر" not in stripped)
    # القارئ الموحَّد (الأحوط: go2 يغلب go3 للمرشح b) بوجود السطر وبدونه
    check("القارئ الموحَّد نفسه بوجود السطر وبدونه",
          stages.read_actions(marked, 1) == stages.read_actions(stripped, 1)
          == ({c_a["id"]: "publish", c_b["id"]: "go2", c_c["id"]: "go3"},
              [{"id": c_b["id"], "marked": ["go2", "go3"]}]),
          str(stages.read_actions(marked, 1)))
    check("all_candidate_ids نفسها",
          preselect.all_candidate_ids(marked)
          == preselect.all_candidate_ids(stripped)
          == [c_a["id"], c_b["id"], c_c["id"]])

def test_preselect_image_line_count_and_cap() -> None:
    """Issue #1178: صيغة العدد العربية لـN = 1/2/3، وسقف واحد من الإعداد
    (collect.related_links_max) يحكم النسخ في _write_selected والعرض معًا."""
    from src import collect_finalize, preselect

    now = datetime.now(timezone.utc)

    def mk(n, k):
        art = Article(title=f"مرشح العدد {n}", link=f"https://cnt.example/{n}",
                      summary="", source_name="CN", region="ri", weight=1.0,
                      published=now, bucket="serious", publisher="CN")
        art.cluster_members = [{"name": "CN", "link": art.link}] + [
            {"name": f"P{i}", "link": f"https://p{i}.example/{n}"}
            for i in range(k)]
        return art, preselect.build_candidate(art)

    def line_of(cand, cfg=None):
        body = preselect.build_selection_issue_body([cand], None, cfg)
        # سطر 🖼️ القائم وحده، لا سطر حقل الصورة (#1190)
        return [l for l in body.splitlines() if l.startswith("  🖼️")]

    for n, expect in ((1, "صورة ناشر آخر"), (2, "صور ناشرَين آخرَين"),
                      (3, "صور 3 ناشرين آخرين")):
        _, cand = mk(f"n{n}", n)
        check(f"صيغة العدد N = {n} حرفيًا",
              line_of(cand) == [f"  🖼️ بلا صورة من الناشر · ستُجرَّب {expect} "
                                "ثم بحث الويب"], line_of(cand))

    cfg = load_config()
    cfg["collect"] = {"related_links_max": 2}
    art, cand = mk("cap", 5)
    store.save_candidate(cand)
    check("سقف الإعداد = 2: سطر 🖼️ يقول «ناشرَين آخرَين» لعنقود من خمسة",
          line_of(cand, cfg) == ["  🖼️ بلا صورة من الناشر · ستُجرَّب صور "
                                 "ناشرَين آخرَين ثم بحث الويب"], line_of(cand, cfg))
    rd = collect_finalize._write_selected(
        cand["id"], store.load_history(), 0.5, {}, {}, cfg, [])
    rl = ((rd or {}).get("source") or {}).get("related_links")
    check("سقف الإعداد = 2: _write_selected ينسخ رابطين فقط",
          rl == ["https://p0.example/cap", "https://p1.example/cap"], rl)

    # (c) دوال قراءة القضية الأربع نفسها بالسقف المخصّص
    body = preselect.build_selection_issue_body([cand], None, cfg)
    marked = tick_marker(body, f"review:{cand['id']}")
    stripped = "\n".join(l for l in marked.splitlines()
                         if not l.startswith("  🖼️"))
    check("دوال القراءة الأربع نفسها بوجود السطر وبدونه",
          stages.read_actions(marked, 1)[0]
          == stages.read_actions(stripped, 1)[0] == {cand["id"]: "go2"}
          and preselect.all_candidate_ids(marked)
          == preselect.all_candidate_ids(stripped) == [cand["id"]])


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


def test_preselect_translate_titles_truncation_retry() -> None:
    """Issue #1063: preselect.translate_titles كانت ترسل سقفًا ثابتًا من
    preselect.translate.max_tokens (1500) لا يتحرك مع عدد العناوين المطلوب
    ترجمتها، والقطع (stop_reason=max_tokens) كان يقع ضمن except العام
    فتُعرض العناوين بلا ترجمة بتحذير عام لا يسمّي القطع سببًا.

    يغطي على مخرَج المرحلة (translate_titles) لا الدالة الداخلية وحدها:
    1) سقف الرد المحسوب (_translate_max_tokens): حالة يغلب فيها الحدّ
       الأدنى (max_tokens المضبوط)، وحالة يغلب فيها الحساب من عدد العناوين،
       وحالة تُقصّ عند max_tokens_cap.
    2) قطع مرة ثم نجاح إعادة المحاولة: الترجمات تصل فعلًا، والنداء الثاني
       بسقف مضاعف عن الأول، وERROR واحد فقط.
    3) قطع مستمر (كلتا المحاولتين): تُعرض العناوين بلا ترجمة كما اليوم
       (التدهور الآمن)، وERROR واحد فقط يسمّي القطع سببًا صريحًا.
    4) ترجمة جزئية بلا أي قطع: السلوك القائم يبقى حرفيًا — عنوان غير مذكور
       في الرد يُعرض بلا ترجمة، بلا إعادة محاولة ولا ERROR."""
    from src import preselect

    class _Block:
        def __init__(self, text):
            self.type = "text"
            self.text = text

    class _Resp:
        def __init__(self, content, stop_reason="end_turn"):
            self.content = content
            self.stop_reason = stop_reason

    class _SeqMessages:
        def __init__(self, responses):
            self._responses = list(responses)
            self.calls = []

        def create(self, **kw):
            self.calls.append(kw)
            if not self._responses:
                raise AssertionError("لا رد آخر متاح في التسلسل المزيَّف")
            return self._responses.pop(0)

    class _SeqClient:
        def __init__(self, responses):
            self.messages = _SeqMessages(responses)

    class _FakeLog:
        def __init__(self):
            self.errors, self.warnings = [], []

        def error(self, *a, **kw):
            self.errors.append(a)

        def warning(self, *a, **kw):
            self.warnings.append(a)

        def info(self, *a, **kw):
            pass

    real_client, real_log = preselect._client, preselect.log
    tcfg_base = {"enabled": True, "arabic_skip_ratio": 0.4}

    # ── 1) سقف الرد المحسوب ──
    check("preselect._translate_max_tokens: الحدّ الأدنى (max_tokens المضبوط) يغلب لعناوين قليلة",
          preselect._translate_max_tokens(3, {"max_tokens": 1500}) == 1500,
          preselect._translate_max_tokens(3, {"max_tokens": 1500}))
    check("preselect._translate_max_tokens: الحساب من عدد العناوين يغلب لدفعة كبيرة",
          preselect._translate_max_tokens(50, {"max_tokens": 1500}) == 60 * 50 + 300,
          preselect._translate_max_tokens(50, {"max_tokens": 1500}))
    check("preselect._translate_max_tokens: يُقصّ عند max_tokens_cap",
          preselect._translate_max_tokens(
              1000, {"max_tokens": 1500, "max_tokens_cap": 6000}) == 6000,
          preselect._translate_max_tokens(1000, {"max_tokens": 1500, "max_tokens_cap": 6000}))

    def _candidates(n, prefix):
        return [{"id": f"{prefix}{i}", "title": f"English headline number {i} long enough"}
                for i in range(n)]

    # ── 2) قطع مرة ثم نجاح إعادة المحاولة بسقف مضاعف ──
    retry_cands = _candidates(2, "tr")
    resp_truncated = _Resp([_Block('{"translations": {')], stop_reason="max_tokens")
    resp_ok = _Resp([_Block(json.dumps({"translations": {"1": "ترجمة أولى", "2": "ترجمة ثانية"}}))])
    fake_client1 = _SeqClient([resp_truncated, resp_ok])
    preselect._client, preselect.log = lambda: fake_client1, _FakeLog()
    cfg1 = load_config()
    cfg1["preselect"] = {"translate": dict(tcfg_base)}
    try:
        result1 = preselect.translate_titles(retry_cands, cfg1)
        fake_log1 = preselect.log
    finally:
        preselect._client, preselect.log = real_client, real_log
    check("قطع ثم نجاح: نداءان فقط (الأول مقطوع + الإعادة)",
          len(fake_client1.messages.calls) == 2, len(fake_client1.messages.calls))
    check("قطع ثم نجاح: النداء الثاني بسقف مضاعف عن الأول",
          fake_client1.messages.calls[1]["max_tokens"] ==
          fake_client1.messages.calls[0]["max_tokens"] * 2,
          [c["max_tokens"] for c in fake_client1.messages.calls])
    check("قطع ثم نجاح: الترجمات تصل فعلًا لكلا العنوانين",
          result1 == {"tr0": "ترجمة أولى", "tr1": "ترجمة ثانية"}, result1)
    check("قطع ثم نجاح: ERROR واحد فقط عند الاكتشاف",
          len(fake_log1.errors) == 1, len(fake_log1.errors))

    # ── 3) قطع مستمر (كلتا المحاولتين): بلا ترجمة، ERROR واحد فقط ──
    giveup_cands = _candidates(2, "gu")
    resp_t0 = _Resp([_Block("")], stop_reason="max_tokens")
    resp_t1 = _Resp([_Block("")], stop_reason="max_tokens")
    fake_client2 = _SeqClient([resp_t0, resp_t1])
    preselect._client, preselect.log = lambda: fake_client2, _FakeLog()
    cfg2 = load_config()
    cfg2["preselect"] = {"translate": dict(tcfg_base)}
    try:
        result2 = preselect.translate_titles(giveup_cands, cfg2)
        fake_log2 = preselect.log
    finally:
        preselect._client, preselect.log = real_client, real_log
    check("قطع مستمر: تُعرض العناوين بلا ترجمة (التدهور الآمن)", result2 == {}, result2)
    check("قطع مستمر: ERROR واحد فقط يسمّي القطع سببًا صريحًا",
          len(fake_log2.errors) == 1 and "max_tokens" in fake_log2.errors[0][0],
          fake_log2.errors)

    # ── 4) ترجمة جزئية بلا أي قطع: السلوك القائم يبقى حرفيًا ──
    partial_cands = _candidates(2, "pt")
    resp_partial = _Resp([_Block(json.dumps({"translations": {"1": "ترجمة أولى فقط"}}))])
    fake_client3 = _SeqClient([resp_partial])
    preselect._client, preselect.log = lambda: fake_client3, _FakeLog()
    cfg3 = load_config()
    cfg3["preselect"] = {"translate": dict(tcfg_base)}
    try:
        result3 = preselect.translate_titles(partial_cands, cfg3)
        fake_log3 = preselect.log
    finally:
        preselect._client, preselect.log = real_client, real_log
    check("ترجمة جزئية بلا قطع: نداء واحد فقط بلا إعادة محاولة",
          len(fake_client3.messages.calls) == 1, len(fake_client3.messages.calls))
    check("ترجمة جزئية بلا قطع: العنوان المذكور يُترجَم والآخر يبقى بلا ترجمة",
          result3 == {"pt0": "ترجمة أولى فقط"}, result3)
    check("ترجمة جزئية بلا قطع: لا ERROR ولا WARNING — ليست فشلًا",
          len(fake_log3.errors) == 0 and len(fake_log3.warnings) == 0,
          (fake_log3.errors, fake_log3.warnings))


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
    # (#1182) الصورة بحقل رابط بلا مربع img: — الصيغة الجديدة.
    field_text = load_config().path("stages.image_field", "")
    check("مربع الاستبدال لم يعد يُبنى", "<!-- img:abc123def456 -->" not in body)
    check("حقل الرابط معروض", "<!-- imgurl:abc123def456 -->" in body)
    check("حقل الرابط نص لا مربع",
          any(field_text in ln and "- [" not in ln and "imgurl:abc123def456" in ln
              for ln in body.splitlines()))
    check("تنبيه غياب الصورة يظهر", "بلا صورة للخبر" in body)
    check("لا تنبيه حين توجد صورة",
          "بلا صورة للخبر" not in
          review.build_issue_body([{**base, "has_photo": True}], "u/r"))

    check("الحقل الفارغ لا يُنفَّذ", review.parse_image_requests(body) == [])

    filled = body.replace(
        field_text + "  <!-- imgurl:abc123def456 -->",
        "الرابط: https://cdn.site/p.jpg  <!-- imgurl:abc123def456 -->")
    check("رابط في الحقل بلا أي مربع يُنفَّذ",
          review.parse_image_requests(filled)
          == [("abc123def456", "https://cdn.site/p.jpg")])
    notlink = body.replace(
        field_text + "  <!-- imgurl:abc123def456 -->",
        "هذه صورة جميلة  <!-- imgurl:abc123def456 -->")
    check("نص غير رابط في الحقل لا يُعدّ طلبًا",
          review.parse_image_requests(notlink) == [])
    check("رابط غير http(s) لا يُعدّ طلبًا",
          review.parse_image_requests(body.replace(
              field_text + "  <!-- imgurl:abc123def456 -->",
              "ftp://x/p.jpg  <!-- imgurl:abc123def456 -->")) == [])

    # اللصق قبل العلامة أو بعدها — كلاهما يعمل على الهاتف
    after = body.replace(
        field_text + "  <!-- imgurl:abc123def456 -->",
        "الرابط: <!-- imgurl:abc123def456 --> https://cdn.site/p.jpg")
    check("موضع اللصق لا يهم",
          review.parse_image_requests(after)
          == [("abc123def456", "https://cdn.site/p.jpg")])

    cleared = review.clear_image_request(filled, "abc123def456")
    check("الحقل يُفرَّغ بعد التنفيذ ويعود نصّه",
          review.parse_image_requests(cleared) == [] and field_text in cleared)
    check("الحقل يُنظَّف من الرابط", "cdn.site" not in cleared)
    kept = review.clear_image_request(filled, "abc123def456", keep_url=True)
    check("الرابط يبقى عند الفشل ليصحَّح", "cdn.site" in kept)

    # الصيغة القديمة (قضية مفتوحة قبل التحديث): مربع img: + imgurl كما كانت
    legacy = ("  - [ ] 🖼️ استبدل الصورة بالرابط أدناه  <!-- img:abc123def456 -->\n\n"
              "    الرابط:   <!-- imgurl:abc123def456 -->\n")
    legacy_filled = legacy.replace(
        "الرابط:   <!--", "الرابط: https://cdn.site/p.jpg  <!--")
    check("قديم: المربع الفارغ مع رابط لا يُنفَّذ",
          review.parse_image_requests(legacy_filled) == [])
    check("قديم: مربع معلَّم بلا رابط يُهمَل",
          review.parse_image_requests(
              legacy.replace("- [ ] 🖼️", "- [x] 🖼️")) == [])
    legacy_ticked = legacy_filled.replace("- [ ] 🖼️", "- [x] 🖼️")
    check("قديم: المربع المعلَّم مع الرابط يُنفَّذ",
          review.parse_image_requests(legacy_ticked)
          == [("abc123def456", "https://cdn.site/p.jpg")])
    legacy_cleared = review.clear_image_request(legacy_ticked, "abc123def456")
    check("قديم: يُفرَّغ المربع والرابط بعد التنفيذ",
          review.parse_image_requests(legacy_cleared) == []
          and "cdn.site" not in legacy_cleared and "- [ ] 🖼️" in legacy_cleared)
    check("قديم: لا تكرار عند الفشل",
          review.parse_image_requests(review.clear_image_request(
              legacy_ticked, "abc123def456", keep_url=True)) == [])

@auto_restore_last_publish
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
    reset_last_publish()

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
    marked_unedited = tick_marker(body_unedited, f"<!-- go:publish:{news_draft['id']} -->")

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
    marked_hl = tick_marker(body_hl, f"<!-- go:publish:{hl_news_draft['id']} -->")
    marked_hl = marked_hl.replace(
        f"- [x] 1. هل يتصاعد الموقف؟  <!-- hl:{hl_news_draft['id']}:0 -->",
        f"- [ ] 1. هل يتصاعد الموقف؟  <!-- hl:{hl_news_draft['id']}:0 -->")
    marked_hl = marked_hl.replace(
        f"- [ ] 2. بديل أول تقريري  <!-- hl:{hl_news_draft['id']}:1 -->",
        f"- [x] 2. بديل أول تقريري  <!-- hl:{hl_news_draft['id']}:1 -->")

    publish_calls.clear()
    reset_last_publish()
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
    marked_hl2 = tick_marker(body_hl2, f"<!-- go:publish:{hl_edit_draft['id']} -->")
    marked_hl2 = marked_hl2.replace(
        f"- [x] 1. هل يحدث كذا؟  <!-- hl:{hl_edit_draft['id']}:0 -->",
        f"- [ ] 1. هل يحدث كذا؟  <!-- hl:{hl_edit_draft['id']}:0 -->")
    marked_hl2 = marked_hl2.replace(
        f"- [ ] 2. بديل تقريري  <!-- hl:{hl_edit_draft['id']}:1 -->",
        f"- [x] 2. بديل تقريري  <!-- hl:{hl_edit_draft['id']}:1 -->")
    edited_hl2 = marked_hl2.replace("متن قديم.", "متن محرَّر يدويًا أيضًا.")

    publish_calls.clear()
    reset_last_publish()
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
    marked2 = tick_marker(body2, f"<!-- go:publish:{news_draft2['id']} -->")
    edited2 = marked2.replace("نص الخبر الأصلي الثاني.", "نص محرَّر يدويًا في الـIssue.")

    publish_calls.clear()
    reset_last_publish()
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

@auto_restore_last_publish
def test_setimage_stores_manual_link_without_card() -> None:
    """Issue #852 (يخلف Issue #749/#680): مسودة بلا حقل image بعد -- الحال
    العامة لكل مسار أخبار الآن، لا مسار التحليل وحده كما كانت قبل هذه
    المهمة -- apply_image لا يحاول إعادة بناء (rebuild_card يفترض بطاقة
    سابقة ليحسب مسارًا "تاليًا" لها)، بل يخزّن الرابط في manual_image
    وحده، فتلتقطه cards.ensure عند الاعتماد لاحقًا."""
    from src import setimage

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

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

@auto_restore_last_publish
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
    reset_last_publish()

    draft = {
        "id": "d0d0d0d0d0d0", "score": 4.0, "caption": "متن", "bucket": "serious",
        "source": {"link": "https://x/1", "publishers": ["BBC"]},
        "arabic": {"post_title": "خبر بلا بطاقة بعد", "category": ""},
        # بلا حقل image عمدًا
    }
    store.save_draft({**draft, "status": "pending", "id": "d0d0d0d0d0d0"})

    body = review.build_issue_body([draft], "u/r", "main")
    # (#1182) الحقل بلا مربع: يكفي لصق الرابط.
    filled = body.replace(
        f"{load_config().path('stages.image_field', '')}  <!-- imgurl:{draft['id']} -->",
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
          comments and "حُفظت الصورة — تُستعمل عند بناء البطاقة" in comments[0], comments)

@auto_restore_last_publish
def test_setimage_apply_image_keeps_origin_badge() -> None:
    """Issue #758: أسهل نقطة يضيع فيها وسم المسار بصمت — apply_image يعيد
    بناء البطاقة لمسودة قائمة بالفعل، فإن لم يمرّر store.origin_of(draft)
    إلى build_post_image يفقد التبديل اليدوي للصورة الملصق الثاني (مثلًا
    «تحليل» على مسودة origin=analysis معتمدة) دون أي خطأ ظاهر."""
    from src import setimage

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

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
    H = int(cfg.path("image.height", 1350))
    # الشارة فوق أول سطر من العنوان محاذاة لليمين (Issue #1161)
    probe_xy = badge_probe_xy(cfg, ["تحليل"], 0, "مقال تحليل معتمد")
    analysis_bg = imaging.hex_rgb(cfg.path("cards.analysis.bg"))

    out_path = DRAFTS_DIR / Path(updated["image"]).relative_to("drafts")
    with Image.open(out_path) as im:
        pixel = im.convert("RGB").getpixel(probe_xy)
    check("apply_image يحافظ على ملصق «تحليل» بعد تبديل الصورة يدويًا (Issue #758)",
          all(abs(a - b) <= 6 for a, b in zip(pixel, analysis_bg)), (pixel, analysis_bg))

@auto_restore_last_publish
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
    reset_last_publish()

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
            # category فارغة عمدًا: شارة category تُرسم أولًا فتزيح
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
        body = tick_marker(body, f"<!-- go:publish:{d['id']} -->")

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
    # بوابة الفاصل (Issue #1010) تنشر الأول فورًا وتؤجِّل الباقي غير العاجل
    # داخل نفس دفعة --now -- لم تعد الثلاث السليمة تُنشر معًا بلا فاصل؛ هذا
    # الاختبار يتحقّق من بناء البطاقات والعناوين لا من توقيت النشر (تختبره
    # test_publish_gap_gate_core_scenarios وأخواتها).
    check("publish.main: الأول (chosen) نُشر فورًا، والرابعة فشل بناؤها فبقيت معلَّقة",
          len(publish_calls) == 1, publish_calls)

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
    check("الفهرس الافتراضي (٠): أجَّلتها البوابة (منشور آخر خرج للتوّ في نفس الدفعة)",
          persisted_default.get("status") == "queued", persisted_default.get("status"))

    persisted_long = store.load_draft(draft_long["id"])[1]
    check("عنوان يتجاوز الحدّ: البطاقة بُنيت رغم ذلك (بعنوان arabic.image_headline بدلًا)",
          bool(persisted_long.get("image")), persisted_long.get("image"))
    check("عنوان يتجاوز الحدّ: العنوان المختار وصل النص المخزَّن رغم ذلك "
          "(أجَّلتها البوابة قبل الوصول لفيسبوك، فالتحقّق من المخزَّن لا publish_calls)",
          persisted_long.get("caption", "").startswith(long_headline),
          persisted_long.get("caption", "")[:40])

    persisted_fail = store.load_draft(draft_fail["id"])[1]
    check("فشل بناء حقيقي: المسودة تبقى pending بلا نشر (لا تُسقَط صامتًا)",
          persisted_fail.get("status") == "pending", persisted_fail.get("status"))
    check("فشل بناء حقيقي: لا حقل image ظهر", "image" not in persisted_fail, persisted_fail)
    check("فشل بناء حقيقي: تعليق على الـIssue يذكر اسم المسودة (بعد تطبيق العنوان المختار)",
          comments and any("عنوان بديل قصير ٤" in c for c in comments), comments)

    # البطاقات المبنية تحمل ملصق مسار المسودة (origin=request، نفس مبدأ
    # #758) -- نفس أسلوب فحص البكسل في test_setimage_apply_image_keeps_origin_badge
    W = int(cfg.path("image.width", 1080))
    H = int(cfg.path("image.height", 1350))
    probe_xy = badge_probe_xy(cfg, ["هام"], 0, "عنوان بديل مختار")
    # cards.request له لون bg مستقل منذ Issue #954 (بنفسجي، لا يسقط إلى
    # brand.accent_color بعد الآن -- كان يطابق شارة التصنيف بلونها).
    request_bg = imaging.hex_rgb(cfg.path("cards.request.bg"))
    out_path = DRAFTS_DIR / Path(persisted_chosen["image"]).relative_to("drafts")
    with Image.open(out_path) as im:
        pixel = im.convert("RGB").getpixel(probe_xy)
    check("البطاقة المبنية عند الاعتماد تحمل ملصق «هام» (origin=request، Issue #954)",
          all(abs(a - b) <= 6 for a, b in zip(pixel, request_bg)), (pixel, request_bg))
    check("cards.request.badge == «هام» وcards.verify/article ما زالا «تحقيق» (Issue #952)",
          cfg.path("cards.request.badge") == "هام"
          and cfg.path("cards.verify.badge") == "تحقيق"
          and cfg.path("cards.article.badge") == "تحقيق",
          (cfg.path("cards.request.badge"), cfg.path("cards.verify.badge"),
           cfg.path("cards.article.badge")))

@auto_restore_last_publish
def test_card_second_badge_offset_with_nonempty_category() -> None:
    """Issue #954: test_publish_builds_cards_at_approval وtest_setimage_apply_image_keeps_origin_badge
    يتركان category فارغة عمدًا (تعليقهما يقول ذلك صراحة)، فيقع probe_xy
    فعليًا على بداية صف الملصقات كلها -- وهو موضع الشارة الثانية بمحض غياب
    الأولى، لا دليل أنها تنزاح فعلًا حين تُرسم شارة تصنيف حقيقية قبلها.
    هنا category غير فارغة عمدًا، والإحداثية الصحيحة للشارة الثانية تُحسب
    من plan_card_layout في src/imaging.py (تُرسم شارة category ثم تُزاح
    الشارة التالية بعرضها + int(W * 0.014)) لا بالتخمين.
    البطاقة تُبنى عبر cards.ensure -- المسار الفعلي الوحيد لبناء بطاقة عند
    الاعتماد لكل المسارات (CLAUDE.md، «توقيت البطاقة»)."""
    from src import cards

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    cfg = load_config()
    W = int(cfg.path("image.width", 1080))
    H = int(cfg.path("image.height", 1350))
    category = "تصنيف تجريبي"
    # الشارة الثانية (الأصل) على يسار التصنيف، والمجموعة محاذاة لليمين (Issue #1161)
    probe_xy = badge_probe_xy(cfg, [category, "هام"], 1, "سؤال تجريبي؟")

    draft = {
        "id": "cardoffset01", "status": "pending", "origin": "request",
        "bucket": "serious",
        "arabic": {"post_title": "سؤال تجريبي؟", "category": category, "urgent": False},
        "caption": "متن الخبر", "source": {"publishers": ["مصدر"],
                                            "image_candidates": ["https://cdn.example/ok.jpg"]},
    }
    path = store.save_draft(draft)

    built = cards.ensure(path, draft, cfg)
    check("cards.ensure بنى البطاقة بنجاح (مسار الاعتماد الفعلي)", built is not None, built)

    request_bg = imaging.hex_rgb(cfg.path("cards.request.bg"))
    accent_color = imaging.hex_rgb(cfg.path("brand.accent_color", "#F0B429"))
    out_path = DRAFTS_DIR / Path(built).relative_to("drafts")
    with Image.open(out_path) as im:
        pixel = im.convert("RGB").getpixel(probe_xy)
    check("الشارة الثانية بعد شارة تصنيف حقيقية تحمل لون cards.request.bg المستقل "
          "لا brand.accent_color (Issue #954)",
          all(abs(a - b) <= 6 for a, b in zip(pixel, request_bg))
          and not all(abs(a - b) <= 6 for a, b in zip(pixel, accent_color)),
          (pixel, request_bg, accent_color, probe_xy))

@auto_restore_last_publish
def test_tall_card_layout_1161() -> None:
    """Issue #1161 (يخلف تصميم #1158 المربع): بطاقة عمودية 1080×1350 على
    مخرَج الأنبوب — تُبنى فعليًا عبر cards.ensure بصور تُولَّد هنا (لا ملف من
    drafts/). شريط علوي = شريط سفلي (W×0.082 بالبكسل)، صورة 4:3 تمامًا تبدأ
    عند الشريط بتدرّجين (لا خطوط ذهبية)، عنوان محاذى لليمين، والشارات مجموعة
    واحدة محاذاة لليمين فوق أول سطر منه. وتبقى أحكام #1158 التي لم تتغيّر: المعرّف
    LTR، ولا «صورة:» في أي مسار، ولا «المصدر:» في التحليل."""
    from src import cards

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()
    cfg = load_config()
    # Issue #1165: هذا الاختبار يقيس هندسة #1161 من استدعاءات draw_text بأسطر
    # كاملة؛ المدّ يرسم الأسطر كلمة كلمة فيُعطَّل هنا (هندسته مغطّاة في
    # test_title_kashida_1165) والهندسة نفسها لا تتأثر بالمدّ.
    cfg["image"]["title_justify"] = False
    W = int(cfg.path("image.width", 1080))
    H = int(cfg.path("image.height", 1350))
    bar = int(W * 0.082)
    photo_h = round(W * 3 / 4)
    photo_top = bar
    photo_bottom = photo_top + photo_h
    margin = int(W * 0.06)
    primary = imaging.hex_rgb(cfg.path("brand.primary_color", "#12203A"))
    accent = imaging.hex_rgb(cfg.path("brand.accent_color", "#F0B429"))
    breaking_bg = imaging.hex_rgb(cfg.path("cards.breaking.bg"))
    analysis_bg = imaging.hex_rgb(cfg.path("cards.analysis.bg"))

    def close(px, rgb, tol=8):
        return all(abs(a - b) <= tol for a, b in zip(px, rgb))

    # صورة متدرّجة ناعمة بنسبة 4:3: القصّ/التحجيم وحدهما يعيدانها، فأي فرق عن
    # cover(المصدر) خارج التدرّجين يكشف تعتيمًا أو تركيبًا. تُولَّد هنا لا من drafts/.
    gw, gh = 1600, 1200
    grad = Image.new("RGB", (gw, gh))
    gp = grad.load()
    for yy in range(gh):
        for xx in range(gw):
            gp[xx, yy] = (60 + xx * 120 // gw, 90 + yy * 100 // gh, 160)

    drawn: list[tuple] = []     # (النص، x، y، حجم الخط، anchor)
    ltr: list[str] = []
    real_draw, real_ltr = imaging.draw_text, imaging.draw_text_ltr
    real_dl = imaging.download_image

    def spy(draw, xy, text, font, *a, **k):
        anchor = k.get("anchor", a[1] if len(a) > 1 else None)
        drawn.append((text, xy[0], xy[1], getattr(font, "size", None), anchor))
        return real_draw(draw, xy, text, font, *a, **k)

    def spy_ltr(draw, xy, text, *a, **k):
        ltr.append(text)
        return real_ltr(draw, xy, text, *a, **k)

    def build(id_, headline, origin="news", category="سياسة", urgent=False,
              publishers=("الجزيرة",), image=True, **kw):
        drawn.clear()
        ltr.clear()
        draft = {
            "id": id_, "status": "pending", "origin": origin, "bucket": "serious",
            "arabic": {"post_title": headline, "category": category, "urgent": urgent},
            "caption": "متن", "source": {"publishers": list(publishers)},
        }
        path = store.save_draft(draft)
        imaging.draw_text, imaging.draw_text_ltr = spy, spy_ltr
        imaging.download_image = ((lambda *a, **k: grad.copy()) if image
                                  else (lambda *a, **k: None))
        try:
            rel = cards.ensure(
                path, draft, cfg, check_headline_limit=False,
                image_urls=["https://cdn.example/ok.jpg"] if image else None,
                allow_search_fallback=False, **kw)
        finally:
            imaging.draw_text, imaging.draw_text_ltr = real_draw, real_ltr
            imaging.download_image = real_dl
        with Image.open(DRAFTS_DIR / Path(rel).relative_to("drafts")) as built:
            return built.convert("RGB")

    def head_lines(first_word):
        return [d for d in drawn if d[0] and str(d[0]).split()[0].startswith(first_word)]

    def mad(a, b):
        da, db = a.tobytes(), b.tobytes()
        return sum(abs(x - y) for x, y in zip(da, db)) / len(da)

    def row_mean(img, y):
        row = img.crop((0, y, W, y + 1)).resize((1, 1), Image.BOX)
        return row.getpixel((0, 0))

    # ── الأبعاد وصندوق الصورة ──
    im = build("tl0000000001", "عنوان قصير")

    def px(y, x=5):
        return im.getpixel((x, y))

    check("(#1161) أبعاد البطاقة 1080×1350 (عمودي 4:5)", im.size == (1080, 1350)
          and (W, H) == (1080, 1350), (im.size, W, H))
    check("(#1161) الشريط العلوي = W×0.082 = 88 بكسلًا ثابتة لا تكبر مع الطول الجديد",
          bar == 88 and close(px(0), primary) and close(px(bar - 2), primary), bar)
    check("(#1161) صندوق الصورة 1080×810 (4:3 تمامًا) يبدأ عند y=bar",
          photo_h == 810 and photo_top == bar
          and photo_h * 4 == W * 3, (photo_h, photo_top))
    footer_bg = imaging.mix(primary, (0, 0, 0), 0.28)
    check("(#1161) الشريط السفلي بارتفاع bar نفسه ولونه الحالي",
          close(px(H - bar - 2), primary) and close(px(H - bar + 2), footer_bg)
          and close(px(H - 1), footer_bg),
          (px(H - bar - 2), px(H - bar + 2), px(H - 1)))

    # ── لا خطوط ذهبية: لا accent عند حافتي الصورة العلوية والسفلية ──
    edge_rows = (bar - 1, bar, bar + 1, photo_bottom - 2, photo_bottom - 1,
                 photo_bottom, photo_bottom + 1)
    check("(#1161) لا لون accent في السطرين عند حافتي الصورة (الخطّان الذهبيان محذوفان)",
          not any(close(px(y, x), accent, 20) for y in edge_rows
                  for x in (5, W // 2, W - 6)),
          [px(y) for y in edge_rows])

    # ── التدرّجان ──
    ref = imaging.cover(grad, W, photo_h)
    box = im.crop((0, photo_top, W, photo_bottom))
    n_top, n_bot = round(photo_h * 0.14), round(photo_h * 0.30)
    check("(#1161) التدرّج العلوي: أول سطر من الصورة ≈ primary",
          close(box.getpixel((W // 2, 0)), primary, 6), box.getpixel((W // 2, 0)))
    check("(#1161) التدرّج السفلي: آخر سطر من الصورة ≈ primary",
          close(box.getpixel((W // 2, photo_h - 1)), primary, 6),
          box.getpixel((W // 2, photo_h - 1)))
    mid_a, mid_b = n_top + 8, photo_h - n_bot - 8
    check("(#1161) منتصف الصورة (خارج التدرّجين) ≈ الصورة المصدر بعد القصّ "
          "(فرق JPEG/unsharp فقط) — لا تعتيم آخر",
          mad(box.crop((0, mid_a, W, mid_b)), ref.crop((0, mid_a, W, mid_b))) < 3.0,
          mad(box.crop((0, mid_a, W, mid_b)), ref.crop((0, mid_a, W, mid_b))))
    steps = [max(abs(a - b) for a, b in zip(row_mean(box, y), row_mean(box, y + 1)))
             for y in range(0, photo_h - 1)]
    check("(#1161) التدرّجان ناعمان: لا قفزة لونية بين صفّين متتاليين (≤ 6 درجات)",
          max(steps) <= 6, (max(steps), steps.index(max(steps))))

    # ── العنوان القصير: الحجم الابتدائي ومحاذاة لليمين ──
    start = int(W * 0.095)
    short = head_lines("عنوان")
    check("(#1161) عنوان قصير يأخذ الحجم الابتدائي W×0.095",
          bool(short) and short[0][3] == start, short)
    check("(#1161) العنوان محاذى لليمين عند الهامش الأيمن (x = W−margin، anchor rm)",
          bool(short) and all(abs(d[1] - (W - margin)) <= 12 and d[4] == "rm" for d in short), short)
    plan_s = card_plan(cfg, "عنوان قصير", ["سياسة"])
    zone_top, zone_bottom = photo_bottom, H - bar
    zone_h = zone_bottom - zone_top
    check("(#1161) العنوان متوسط عموديًا في منطقته (من أسفل الصورة إلى الشريط السفلي)",
          bool(short) and abs(short[0][2] - (zone_top + zone_bottom) / 2) <= 2,
          (short, (zone_top + zone_bottom) / 2))

    # ── الشارات: محاذاة لليمين وحافتها السفلية فوق أول سطر بـW×0.022، تحت بداية التدرّج ──
    fade_start = photo_bottom - n_bot
    gap = int(W * 0.022)

    def check_badges(label, img, headline, texts, colors):
        lines = head_lines(headline.split()[0])
        line_h = int(lines[0][3] * 1.45)
        block_top = lines[0][2] - line_h // 2      # أعلى صندوق أول سطر مرسوم فعلًا
        plan = card_plan(cfg, headline, texts)
        boxes = plan["badges"]
        check(f"(#1161) [{label}] الشارات محاذاة لليمين: الأولى تنتهي عند W−margin",
              boxes[0]["x1"] == W - margin and all(
                  boxes[i + 1]["x1"] < boxes[i]["x0"] for i in range(len(boxes) - 1)), boxes)
        check(f"(#1161) [{label}] الحافة السفلية للشارات فوق أول سطر للعنوان بـW×0.022 بالضبط",
              all(b["y1"] == block_top - gap for b in boxes)
              and plan["block_top"] == block_top, (boxes, block_top, gap))
        check(f"(#1161) [{label}] الشارات كلها تحت بداية التدرّج السفلي",
              all(b["y0"] >= fade_start for b in boxes), (boxes, fade_start))
        bad = []
        for b, rgb in zip(boxes, colors):
            xm, ym = (b["x0"] + b["x1"]) // 2, (b["y0"] + b["y1"]) // 2
            # بكسل جسم الشارة قرب حافتها (فوق النص) بلونها المطلوب
            if not close(img.getpixel((b["x0"] + 12, ym)), rgb, 10):
                bad.append(("body", b["text"], img.getpixel((b["x0"] + 12, ym)), rgb))
            if close(img.getpixel((xm, b["y1"] + 4)), rgb, 10):
                bad.append(("below", b["text"]))
        check(f"(#1161) [{label}] الشارات مرسومة فعلًا بألوانها في مواضعها", not bad, bad)

    check_badges("قصير", im, "عنوان قصير", ["سياسة"], [accent])

    # ── عنوان 170 حرفًا: يتّسع كاملًا بلا قصّ، والشارات في مكانها ──
    words = [f"كلمة{i}" for i in range(1, 60)]
    long_headline = ""
    for w in words:
        if len(long_headline) + len(w) + 1 > 170:
            break
        long_headline = f"{long_headline} {w}".strip()
    check("(#1161) شرط الاختبار: عنوان طويل بنحو 170 حرفًا",
          160 <= len(long_headline) <= 170, len(long_headline))
    im_l = build("tl0000000002", long_headline, category="سياسة")
    lines = head_lines("كلمة")
    joined = " ".join(d[0] for d in lines)
    check("(#1161) عنوان 170 حرفًا يتّسع كاملًا: كل كلماته مرسومة بلا قصّ",
          joined.split() == long_headline.split(), (joined, long_headline))
    sizes = {d[3] for d in lines}
    size = next(iter(sizes)) if sizes else 0
    line_h = int(size * 1.45)
    check("(#1161) العنوان الطويل صغّر حجمه عن الابتدائي بخطوة 2",
          len(sizes) == 1 and size < start and (start - size) % 2 == 0, sizes)
    pad = zone_h * 0.08
    block_top = lines[0][2] - line_h // 2
    check("(#1161) العنوان الطويل محاذى لليمين وكتلته داخل المنطقة بحشوة 8% أعلى وأسفل",
          all(abs(d[1] - (W - margin)) <= 12 and d[4] == "rm" for d in lines)
          and block_top >= zone_top + pad - 1
          and block_top + len(lines) * line_h <= zone_bottom - pad + 1,
          (block_top, len(lines), line_h, pad))
    check_badges("170 حرفًا", im_l, long_headline, ["سياسة"], [accent])

    # ── عاجل + تصنيف: «عاجل» أقصى اليمين ثم التصنيف ──
    im_u = build("tl0000000004", "عنوان عاجل", category="سياسة", urgent=True,
                 publishers=("الجزيرة", "BBC"))
    check_badges("عاجل+تصنيف", im_u, "عنوان عاجل", ["عاجل", "سياسة"], [breaking_bg, accent])
    plan_u = card_plan(cfg, "عنوان عاجل", ["عاجل", "سياسة"])["badges"]
    check("(#1161) «عاجل» أقصى اليمين والتصنيف على يساره بفاصل W×0.014",
          plan_u[0]["x1"] == W - margin
          and plan_u[0]["x0"] - plan_u[1]["x1"] == int(W * 0.014), plan_u)

    # ── تحليل: شارة الأصل على يسار التصنيف ──
    im_a = build("tl0000000008", "هل يمكن لدستور جديد توحيد تركيا؟", origin="analysis",
                 category="سياسة")
    check_badges("تحليل", im_a, "هل يمكن لدستور جديد توحيد تركيا؟", ["سياسة", "تحليل"], [accent, analysis_bg])

    # ── قيد الشارات: تحت بداية التدرّج وإلا يصغر العنوان خطوة أخرى ──
    cfg_c = load_config()
    # بداية التدرّج = حافة الصورة السفلية ومسافة الشارات كبيرة، فتعلو الشارات
    # عن بداية التدرّج ما لم يصغر العنوان فيهبط أول سطر والشارات معه
    cfg_c["image"]["fade_bottom_ratio"] = 0.0
    cfg_c["image"]["badge_gap_ratio"] = 0.10
    probe_draw = ImageDraw.Draw(Image.new("RGB", (W, H)))
    free = imaging.plan_card_layout(probe_draw, "عنوان قصير", ["سياسة"], cfg)
    forced = imaging.plan_card_layout(probe_draw, "عنوان قصير", ["سياسة"], cfg_c)
    check("(#1161) شارات فوق بداية التدرّج ⇒ يصغر العنوان حتى تقع تحتها",
          forced["font"].size < free["font"].size
          and all(b["y0"] >= forced["fade_start"] for b in forced["badges"]),
          (forced["font"].size, free["font"].size))

    # ── المعرّف والشعار في الشريط العلوي (حكم #1158 باقٍ) ──
    check("(#1158) المعرّف brand.handle يُرسم LTR بلا قلب bidi: «@almujez» (الآن في السفلي، #1167)",
          ltr == ["@almujez"] and not any("almujez" in d[0] for d in drawn), (ltr, drawn))
    left = int(W * 0.06)
    check("(#1167) التاريخ في الزاوية العلوية اليسرى (بكسلات نصّ فوق الشريط)",
          any(not close(im_u.getpixel((x, bar // 2)), primary, 12)
              for x in range(left, left + 140)), None)
    right = W - left
    check("(#1158) الشعار في أقصى يمين الشريط العلوي",
          any(not close(im_u.getpixel((x, bar // 2)), primary, 12)
              for x in range(right - 120, right)), None)
    check("(#1161) لا شيء في وسط الشريط العلوي (الشارات انتقلت)",
          all(close(im_u.getpixel((x, bar // 2)), primary, 6)
              for x in range(int(W * 0.35), int(W * 0.65), 7)), None)

    # ── سطر المصدر: لا «صورة:» في أي مسار، ولا «المصدر:» في التحليل (#1158) ──
    def prov():
        return [{"url": "https://cdn.example/n.jpg", "publisher": "ناشر آخر"}]

    drawn.clear()
    real_dl2 = imaging.download_image
    imaging.download_image = lambda url, *a, **k: grad.copy()
    imaging.draw_text = spy
    try:
        draft_n = {"id": "tl0000000005", "status": "pending", "origin": "news",
                   "bucket": "serious",
                   "arabic": {"post_title": "خبر", "category": "سياسة", "urgent": False},
                   "caption": "متن", "source": {"publishers": ["الجزيرة"]}}
        path_n = store.save_draft(draft_n)
        cards.ensure(path_n, draft_n, cfg, image_urls=None, allow_search_fallback=False,
                     news_photo_provider=prov)
        texts_n = [d[0] for d in drawn]
        drawn.clear()
        line = "تحليل لتغطية قناتي سي إن إن ترك و خلق تي في"
        draft_a = {"id": "tl0000000006", "status": "pending", "origin": "analysis",
                   "arabic": {"post_title": "تحليل", "category": ""},
                   "caption": "متن", "source": {"publishers": [line]}}
        path_a = store.save_draft(draft_a)
        cards.ensure(path_a, draft_a, cfg, image_urls=None, allow_search_fallback=False,
                     news_photo_provider=prov, **cards.analysis_card_kwargs())
        texts_a = [d[0] for d in drawn]
    finally:
        imaging.draw_text = real_draw
        imaging.download_image = real_dl2
    check("(#1158) خبر بصورة ناشر آخر: لا «صورة:» والسطر «المصدر: الجزيرة»",
          not any("صورة:" in t for t in texts_n) and "المصدر: الجزيرة" in texts_n, texts_n)
    check("(#1158) التحليل: النص الممرَّر كما هو بلا «المصدر:» ولا «صورة:»",
          line in texts_a
          and not any(t.startswith("المصدر") or "صورة:" in t for t in texts_a), texts_a)
    info_n = store.load_draft("tl0000000005")[1].get("image_info") or {}
    check("(#1158) ناشر الصورة يبقى داخليًا في image_info رغم حذفه من البطاقة",
          info_n.get("news_photo_publisher") == "ناشر آخر", info_n)

    # ── بلا صورة: الخلفية المصمَّمة داخل الصندوق نفسه وعليها التدرّجان ──
    im_p = build("tl0000000007", long_headline, image=False)
    box_p = im_p.crop((0, photo_top, W, photo_bottom))
    check("(#1161) بلا صورة: الخلفية المصمَّمة في صندوق 4:3 نفسه وعليها التدرّجان "
          "(الحافتان ≈ primary بلا accent، والمنتصف ليس primary)",
          close(box_p.getpixel((5, 0)), primary, 6)
          and close(box_p.getpixel((5, photo_h - 1)), primary, 6)
          and not close(box_p.getpixel((5, photo_h // 2)), primary, 4)
          and not any(close(im_p.getpixel((5, y)), accent, 20) for y in edge_rows),
          (box_p.getpixel((5, 0)), box_p.getpixel((5, photo_h // 2))))
    lines_p = head_lines("كلمة")
    check("(#1161) بلا صورة: عنوان 170 حرفًا محاذى لليمين ويتّسع كاملًا",
          " ".join(d[0] for d in lines_p).split() == long_headline.split()
          and all(abs(d[1] - (W - margin)) <= 12 for d in lines_p), None)


@auto_restore_last_publish
def test_publish_card_search_term_from_image_query_en() -> None:
    """Issue #941: البطاقات لمسار article.py كانت تخرج بلا صورة تعبيرية لأن
    البحث الاحتياطي (imagesearch.find_images، Wikimedia/Openverse) كان يجري
    دومًا بعبارة عربية (source.title أو العنوان)، وكلا المصدرين فهرسة
    إنجليزية أساسًا. cards.ensure يقبل الآن search_term= صريحًا (بدل
    الاعتماد دومًا على العنوان العربي)، وpublish.main يمرّر
    card_draft.get('image_query_en') إليه عند بناء البطاقات عند الاعتماد.
    (أ) وحدة مباشرة على cards.ensure، (ب) تكامل كامل عبر publish.main."""
    from src import cards, publish as publish_mod

    # ── (أ) cards.ensure: search_term الصريح يصل بحث الصورة الاحتياطي حرفيًا،
    # وغيابه يعود لسلوك source.title القائم بلا أي تغيير ──
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()
    unit_draft = {
        "id": "aa00000000aa",
        "arabic": {"post_title": "عنوان عربي", "category": "", "urgent": False},
        "source": {"title": "عنوان المصدر العربي", "publishers": []},
    }
    unit_path = store.save_draft(unit_draft)
    real_cards_find = cards.find_images
    search_calls: list = []
    cards.find_images = lambda term, cfg: (search_calls.append(term) or [])  # type: ignore
    try:
        cards.ensure(unit_path, unit_draft, load_config(), headline="عنوان عربي",
                     search_term="Strait of Hormuz tanker")
    finally:
        cards.find_images = real_cards_find  # type: ignore
    check("cards.ensure: search_term الممرَّر صراحةً يصل بحث الصورة الاحتياطي حرفيًا",
          search_calls == ["Strait of Hormuz tanker"], search_calls)

    # بطاقة أُنشئت فعلًا في المحاولة السابقة -- نزع image كي لا يقصر ensure()
    # على فحص «موجودة مسبقًا» ويتخطّى بحث الاحتياط في هذه المحاولة الثانية.
    unit_draft["image"] = None
    search_calls.clear()
    cards.find_images = lambda term, cfg: (search_calls.append(term) or [])  # type: ignore
    try:
        cards.ensure(unit_path, unit_draft, load_config(), headline="عنوان عربي")
    finally:
        cards.find_images = real_cards_find  # type: ignore
    check("cards.ensure: بلا search_term يعود لـsource.title كما كان قبل هذه المهمة (بلا انهيار)",
          search_calls == ["عنوان المصدر العربي"], search_calls)

    # ── (ب) تكامل: publish.main يمرّر card_draft.get('image_query_en') فعليًا
    # عند بناء البطاقة عند الاعتماد (نحو src/publish.py:749) ──
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    art_draft = {
        "id": "ee00000000ee", "status": "pending", "score": 5.0, "bucket": "serious",
        "state_media": False, "origin": "article",
        "caption": "عنوان المقال؟\nمتن المقال.",
        # بلا source.image_candidates عمدًا -- يفرغ urls فتصل cards.ensure
        # إلى بحثها الاحتياطي (allow_search_fallback الافتراضي True).
        "source": {"link": "https://x/1", "publishers": ["BBC"]},
        "arabic": {"post_title": "عنوان المقال؟", "category": "", "urgent": False,
                   "image_headline": "عنوان المقال؟"},
        "headlines": ["عنوان المقال؟"], "headline_selected": 0,
        "image_query_en": "Strait of Hormuz tanker",
    }
    store.save_draft(art_draft)

    body = review.build_issue_body([art_draft], "u/r", "main")
    body = tick_marker(body, f"<!-- go:publish:{art_draft['id']} -->")

    real_fetch = publish_mod.fetch_issue
    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    real_comment = review.comment
    real_close = review.close_issue
    real_cards_find2 = cards.find_images
    publish_mod.ROOT = DRAFTS_DIR.parent

    fallback_terms: list = []
    cards.find_images = lambda term, cfg: (fallback_terms.append(term) or [])  # type: ignore
    facebook.publish_photo = lambda *a, **kw: {"url": "https://fb.example/1", "id": "1"}
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: None
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "approved"}]}
    sys.argv = ["publish", "--issue", "8941", "--now"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo
        review.comment = real_comment
        review.close_issue = real_close
        cards.find_images = real_cards_find2

    check("publish.main ينتهي بنجاح", code == 0, f"exit={code}")
    check("publish.main: مرّر image_query_en فعليًا كـsearch_term إلى بحث الصورة "
          "الاحتياطي عند بناء البطاقة (Issue #941)",
          "Strait of Hormuz tanker" in fallback_terms, fallback_terms)

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
    # +2 (Issue #1182): لا مربع 🎴 تحت العنوان بعد الآن — سطر «بديل» يلي
    # العنوان مباشرة (سطر العنوان ثم فراغ).
    check("build_issue_body: سطر «بديل» يظهر بعد عنوان مسودة المقال "
          "مباشرة ويذكر رقم التحقيق (3، ترتيبه الثالث في القائمة)",
          "🔀 بديل للمنشور رقم 3" in lines[article_idx + 2], lines[article_idx:article_idx + 5])
    check("build_issue_body: سطر «بديل» يظهر بعد عنوان مسودة التحقيق "
          "مباشرة ويذكر رقم المقال (1، ترتيبه الأول في القائمة)",
          "🔀 بديل للمنشور رقم 1" in lines[investigation_idx + 2],
          lines[investigation_idx:investigation_idx + 5])
    plain_block = "\n".join(lines[plain_idx:plain_idx + 4])
    check("build_issue_body: مسودة بلا sibling_id لا تحمل سطر «بديل» إطلاقًا",
          "🔀 بديل" not in plain_block, plain_block)

@auto_restore_last_publish
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
    reset_last_publish()
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

@auto_restore_last_publish
def test_setimage_rebuild_card_analysis_no_duplicate_badge() -> None:
    """Issue #1044: setimage.rebuild_card لم تكن تمرّر category=""/urgent=False/
    bucket=""/origin="analysis" لمسودة أصلها analysis (خلاف
    youtube_publish.ensure_title_card)، فتسقط cards.ensure لبديل المسودة —
    draft["arabic"]["category"] == "تحليل" (القيمة الفعلية لكل مسودات
    التحليل الـ57 على القرص وقت الإبلاغ) وbucket="serious" الافتراضي —
    فتُرسم شارتان بالكلمة نفسها (كهرمانية للتصنيف، زرقاء للمسار) على كل
    بطاقة تحليل يُعاد بناؤها عبر /صورة. الاختبار على البطاقة المبنيّة
    فعليًا (لا الدالة معزولة): بطاقة أولى عبر cards.ensure (المسار الحقيقي
    الوحيد لبناء بطاقة، بنفس وسائط ensure_title_card عبر
    cards.analysis_card_kwargs())، ثم تبديل الصورة عبر setimage.apply_image
    (طريق /صورة الحقيقي، لا rebuild_card معزولة)."""
    from src import cards, setimage

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    cfg = load_config()
    draft = {
        "id": "an0000000001", "status": "pending", "origin": "analysis",
        "bucket": "serious",
        # category == "تحليل" عمدًا -- الحالة الحقيقية لكل مسودات التحليل
        # على القرص (تقرير المهمة)، لا category فارغة كما في اختبارات
        # #758 الأقدم التي لم تكن لتكشف هذا الخلل.
        "arabic": {"post_title": "مقال تحليل حقيقي", "category": "تحليل"},
        "caption": "متن", "source": {"publishers": ["Ch1", "Ch2"]},
    }
    path = store.save_draft(draft)
    built_first = cards.ensure(path, draft, cfg, **cards.analysis_card_kwargs())
    check("بطاقة أولى بُنيت فعليًا للمسودة (نفس وسائط ensure_title_card)",
          built_first is not None, built_first)
    draft = store.load_draft(draft["id"])[1]

    updated = setimage.apply_image(draft["id"], "https://cdn.example/an-new.jpg", cfg)
    check("apply_image (طريق /صورة الحقيقي) ينجح على مسودة تحليل قائمة",
          updated is not None, updated)

    # إحداثيات الشارتين محسوبة من plan_card_layout في src/imaging.py
    # لا بالتخمين -- نفس صيغة test_card_second_badge_offset_with_nonempty_category.
    W = int(cfg.path("image.width", 1080))
    H = int(cfg.path("image.height", 1350))
    # شارة المسار وحدها محاذاة لليمين (Issue #1161)؛ «المنزاحة» نقطة على يسارها
    # مباشرة (حيث كانت ستقع شارة ثانية لو رُسمت) بدل نقطة ثابتة من التخطيط القديم.
    headline_3010 = "مقال تحليل حقيقي"
    first_badge_xy = badge_probe_xy(cfg, ["تحليل"], 0, headline_3010)
    stale_badge_box = card_plan(cfg, headline_3010, ["تحليل", "تحليل"])["badges"][1]
    stale_second_badge_xy = (stale_badge_box["x0"] + 10,
                             (stale_badge_box["y0"] + stale_badge_box["y1"]) // 2)

    analysis_bg = imaging.hex_rgb(cfg.path("cards.analysis.bg"))
    accent_color = imaging.hex_rgb(cfg.path("brand.accent_color", "#F0B429"))
    primary_color = imaging.hex_rgb(cfg.path("brand.primary_color", "#12203A"))

    out_path = DRAFTS_DIR / Path(updated["image"]).relative_to("drafts")
    with Image.open(out_path) as im:
        rgb = im.convert("RGB")
        first_pixel = rgb.getpixel(first_badge_xy)
        stale_pixel = rgb.getpixel(stale_second_badge_xy)

    check("موضع الشارة الأولى يحمل لون خلفية شارة المسار الزرقاء (cards.analysis.bg) "
          "لا لون brand.accent_color (شارة تصنيف كانت لتُرسم هناك قبل الإصلاح)",
          all(abs(a - b) <= 6 for a, b in zip(first_pixel, analysis_bg))
          and not all(abs(a - b) <= 6 for a, b in zip(first_pixel, accent_color)),
          (first_pixel, analysis_bg, accent_color))
    check("لا شارة ثانية زائدة في الموضع الذي كانت ستنزاح إليه شارة المسار لولا الإصلاح "
          "(خلفية الترويسة العادية وحدها هناك -- شارة واحدة فقط على البطاقة)",
          all(abs(a - b) <= 6 for a, b in zip(stale_pixel, primary_color)),
          (stale_pixel, primary_color, analysis_bg))

@auto_restore_last_publish
def test_setimage_rebuild_card_news_category_and_path_badges_unaffected() -> None:
    """Issue #1044: مسار الأخبار في rebuild_card لا يتغيّر -- تثبيت سلوك قائم.
    مسودة origin != "analysis" وعليها تصنيف حقيقي: تبديل الصورة عبر
    setimage.apply_image (نفس الطريق الحقيقي) يُبقي شارتي التصنيف (كهرمانية،
    عند بداية صف الملصقات) والمسار (لون cards.<origin>.bg المستقل، بعد
    التصنيف مباشرة) كما كانتا قبل هذه المهمة -- extra في rebuild_card يبقى
    فارغًا لأي origin غير analysis فتُستعمل قيم المسودة كما اليوم."""
    from src import cards, setimage

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    cfg = load_config()
    category = "تصنيف تجريبي"
    draft = {
        "id": "nw0000000001", "status": "pending", "origin": "request",
        "bucket": "serious",
        "arabic": {"post_title": "خبر عليه تصنيف حقيقي", "category": category,
                   "urgent": False},
        "caption": "متن", "source": {"publishers": ["مصدر"],
                                      "image_candidates": ["https://cdn.example/ok.jpg"]},
    }
    path = store.save_draft(draft)
    built_first = cards.ensure(path, draft, cfg)
    check("بطاقة أولى بُنيت فعليًا للمسودة (مسار الأخبار العادي)",
          built_first is not None, built_first)
    draft = store.load_draft(draft["id"])[1]

    updated = setimage.apply_image(draft["id"], "https://cdn.example/nw-new.jpg", cfg)
    check("apply_image ينجح على مسودة أخبار قائمة عليها تصنيف حقيقي",
          updated is not None, updated)

    W = int(cfg.path("image.width", 1080))
    H = int(cfg.path("image.height", 1350))
    first_badge_xy = badge_probe_xy(cfg, [category, "هام"], 0, "خبر عليه تصنيف حقيقي")
    second_badge_xy = badge_probe_xy(cfg, [category, "هام"], 1, "خبر عليه تصنيف حقيقي")

    accent_color = imaging.hex_rgb(cfg.path("brand.accent_color", "#F0B429"))
    request_bg = imaging.hex_rgb(cfg.path("cards.request.bg"))

    out_path = DRAFTS_DIR / Path(updated["image"]).relative_to("drafts")
    with Image.open(out_path) as im:
        rgb = im.convert("RGB")
        first_pixel = rgb.getpixel(first_badge_xy)
        second_pixel = rgb.getpixel(second_badge_xy)

    check("مسار الأخبار (بعد تبديل الصورة): شارة التصنيف ما زالت بلون brand.accent_color",
          all(abs(a - b) <= 6 for a, b in zip(first_pixel, accent_color)),
          (first_pixel, accent_color))
    check("مسار الأخبار (بعد تبديل الصورة): شارة المسار الثانية ما زالت بلون "
          "cards.request.bg المستقل، منزاحة بعد شارة التصنيف كما اليوم",
          all(abs(a - b) <= 6 for a, b in zip(second_pixel, request_bg)),
          (second_pixel, request_bg))

@auto_restore_last_publish
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
    reset_last_publish()
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
          "ما لا تعلّمه يُسجَّل مرفوضًا" in body and "لم يُعتمد" not in body, body)
    check("لا REJECT_CHOICES ولا parse_rejects بعد الآن في review.py",
          not hasattr(review, "REJECT_CHOICES") and not hasattr(review, "parse_rejects"))

    cand = preselect.build_candidate(
        Article(title="مرشح تجريبي", link="https://x/cand", summary="",
               source_name="P", region="r", weight=1.0,
               published=datetime.now(timezone.utc), bucket="serious", publisher="P"))
    selection_body = preselect.build_selection_issue_body([cand])
    check("لا مربع رفض واحد في Issue الاختيار", "<!-- crj:" not in selection_body,
          selection_body)
    check("خيارا المصير (انشر فورًا/صغ واعرض) باقيان بعلامتي go: (#1190)",
          f"<!-- go:publish:{cand['id']} -->" in selection_body
          and f"<!-- go:go2:{cand['id']} -->" in selection_body,
          selection_body)
    check("لا CREJECT_MARKER ولا parse_candidate_rejects بعد الآن في preselect.py",
          not hasattr(preselect, "CREJECT_MARKER")
          and not hasattr(preselect, "parse_candidate_rejects"))

@auto_restore_last_publish
def test_publish_unapproved_becomes_rejected() -> None:
    """Issue #841، البند 2: عدم الاعتماد داخل Issue موسوم approved يصير
    رفضًا ضمنيًا (status=rejected، وسم feedback «لم يُعتمد») — بصرف النظر
    عن الأصل (أخبار أو تحليل)، مقيَّدًا بمعرّفات هذا الـIssue وحده."""
    from src import feedback
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

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

@auto_restore_last_publish
def test_decisions_records_rejected_unchecked_via_publish() -> None:
    """Issue #954: عدم الاعتماد داخل Issue المراجعة الأولية الموسوم approved
    يُسجَّل أيضًا في state/decisions.json (لا في feedback.py وحدها) بقيمة
    decision=rejected_unchecked وreject_tag=«لم يُعتمد» — على مخرَج
    publish.main الفعلي لا نداء decisions.record_rejected_unchecked مباشرة.
    إعادة تشغيل publish.main على نفس الـIssue (publish.yml يُشغّل مساري
    urgent وnormal لنفس حدث approved، Issue #745) يجب ألا تضيف قيدًا ثانيًا."""
    from src import decisions
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()
    if decisions.DECISIONS_FILE.exists():
        decisions.DECISIONS_FILE.unlink()

    approved_draft = {
        "id": "dc0100000001", "status": "pending", "origin": "news",
        "arabic": {"post_title": "خبر معتمد ينشر"}, "caption": "خبر معتمد ينشر\nمتن.",
        "bucket": "serious",
        "source": {"link": "https://x/dcpub1", "publishers": ["BBC"],
                   "image_candidates": ["https://cdn.example/ok.jpg"]},
    }
    reject_draft = {
        "id": "dc0200000002", "status": "pending", "origin": "news",
        "arabic": {"post_title": "خبر لم يُعتمد"}, "caption": "خبر لم يُعتمد\nمتن.",
        "bucket": "serious",
        "source": {"link": "https://x/dcpub2", "publishers": ["BBC"],
                   "image_candidates": ["https://cdn.example/ok.jpg"]},
    }
    for d in (approved_draft, reject_draft):
        store.save_draft(d)

    body = (
        f"- [x] **1. خبر معتمد ينشر**  <!-- draft:{approved_draft['id']} -->\n"
        f"- [ ] **2. خبر لم يُعتمد**  <!-- draft:{reject_draft['id']} -->\n"
    )

    real_fetch = publish_mod.fetch_issue
    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    real_comment = review.comment
    real_close = review.close_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "approved"}]}
    publish_mod.ROOT = DRAFTS_DIR.parent
    publish_calls: list = []

    def fake_publish_photo(image_path, caption, api_version, first_comment=None):
        publish_calls.append(caption)
        return {"url": "https://fb.example/dc", "id": "1"}

    facebook.publish_photo = fake_publish_photo
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: None

    sys.argv = ["publish", "--issue", "9541", "--now"]
    try:
        code1 = publish_mod.main()
        code2 = publish_mod.main()   # محاكاة مساري urgent ثم normal لنفس حدث approved
    finally:
        publish_mod.fetch_issue = real_fetch
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo
        review.comment = real_comment
        review.close_issue = real_close

    check("كلتا التشغيلتين تنتهيان بنجاح", code1 == 0 and code2 == 0, (code1, code2))
    check("النشر وقع مرة واحدة فقط رغم تشغيل publish.main مرتين",
          publish_calls == [approved_draft["caption"]], publish_calls)

    entries = decisions.load()
    pub_entries = [e for e in entries if e["id"] == approved_draft["id"]]
    rej_entries = [e for e in entries if e["id"] == reject_draft["id"]]
    check("المعتمَد سُجّل مرة واحدة بقرار published",
          len(pub_entries) == 1 and pub_entries[0]["decision"] == "published", pub_entries)
    check("غير المعتمَد سُجّل مرة واحدة فقط بقرار rejected_unchecked رغم التشغيلتين",
          len(rej_entries) == 1 and rej_entries[0]["decision"] == "rejected_unchecked"
          and rej_entries[0]["reject_tag"] == "لم يُعتمد", rej_entries)

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

    # (#1182) مربعا 🎴/↩️ حلّ محلّهما خياران من كتلة الانتقال (go3 / go2).
    body = review.build_issue_body([draft], "u/r", "main")
    check("خيار go3 يظهر في المرحلة 2 غير معلَّم",
          f"<!-- go:go3:{draft['id']} -->" in body
          and f"<!-- card:{draft['id']} -->" not in body, body[:800])
    check("كتلة الانتقال تذكر المرحلة 3", "مرحلة عرض البطاقة والمراجعة النهائية" in body)
    check("لا خيار مرحلة 2 داخل قضية المرحلة 2", f"<!-- go:go2:{draft['id']} -->" not in body)
    check("قراءة المرحلة 2 فارغة قبل التعليم", stages.read_actions(body, 2)[0] == {})

    marked = tick_marker(body, f"<!-- go:go3:{draft['id']} -->")
    check("go3 يُقرأ من المرحلة 2",
          stages.read_actions(marked, 2) == ({draft["id"]: "go3"}, []))

    final_body = review.build_final_review_body([draft], "u/r", "main")
    check("لا مربع 🎴 في المراجعة النهائية",
          f"<!-- card:{draft['id']} -->" not in final_body
          and f"<!-- go:go3:{draft['id']} -->" not in final_body, final_body[:800])
    check("لا مربعات عناوين في المراجعة النهائية", "<!-- hl:" not in final_body,
          final_body[:800])
    check("معرّف الخبر موجود في المراجعة النهائية بلا مربع",
          f"<!-- draft:{draft['id']} -->" in final_body
          and not any("- [" in ln and "draft:" in ln for ln in final_body.splitlines()))
    check("خيارا publish وgo2 في المرحلة 3 غير معلَّمين",
          f"- [ ] ↩️ عد إلى مرحلة عرض النص واختيار العناوين  <!-- go:go2:{draft['id']} -->"
          in final_body and f"<!-- go:publish:{draft['id']} -->" in final_body,
          final_body[:900])
    check("حقل الصورة اليدوية موجود في المراجعة النهائية بلا مربع img",
          f"<!-- img:{draft['id']} -->" not in final_body
          and f"<!-- imgurl:{draft['id']} -->" in final_body)
    check("البطاقة المبنيّة تظهر (رابط raw.githubusercontent.com)",
          "raw.githubusercontent.com" in final_body and draft["image"] in final_body)

    check("قراءة المرحلة 3 فارغة قبل التعليم", stages.read_actions(final_body, 3)[0] == {})
    marked_back = tick_marker(final_body, f"<!-- go:go2:{draft['id']} -->")
    check("go2 يُقرأ من المرحلة 3",
          stages.read_actions(marked_back, 3)[0] == {draft["id"]: "go2"})

@auto_restore_last_publish
def test_publish_card_request_defers_to_final_review() -> None:
    """Issue #858، الجزء الثاني، البند 1-2: معتمَد بلا 🎴 يُنشر فورًا كسابقًا؛
    معتمَد مع 🎴 لا يُنشر -- بطاقته تُبنى فعلًا (cards.ensure يقع أعلاه في
    publish.main، قبل هذا التفرّع، وقبل الفرق بين المسارين) لكنه يبقى pending
    ويُجمَّع في Issue مراجعة نهائية واحد بوسم final-review، وتعليق على
    الـIssue الأولي يذكر رقمه."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

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
    # (#1182) go3 وحده = ما كان ✔️ + 🎴 معًا.
    body = tick_marker(body, f"<!-- go:publish:{draft_direct['id']} -->")
    body = tick_marker(body, f"<!-- go:go3:{draft_card['id']} -->")

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

@auto_restore_last_publish
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
    reset_last_publish()

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
    body = tick_marker(body, f"<!-- go:publish:{approved_draft['id']} -->")
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

@auto_restore_last_publish
def test_decisions_records_rejected_unchecked_via_final_review() -> None:
    """Issue #954: نفس مبدأ test_decisions_records_rejected_unchecked_via_publish
    لكن عبر مسار المراجعة النهائية (cmd_final_review، gate C) -- عدم
    الاعتماد هناك أيضًا يُسجَّل rejected_unchecked في decisions.json، وتشغيل
    publish.main مرتين على نفس الـIssue النهائي (urgent ثم normal) لا يضيف
    قيدًا ثانيًا."""
    from src import decisions
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()
    if decisions.DECISIONS_FILE.exists():
        decisions.DECISIONS_FILE.unlink()

    approved_draft = {
        "id": "dc0300000001", "status": "pending", "origin": "news",
        "arabic": {"post_title": "خبر جاهز للنشر النهائي"},
        "caption": "خبر جاهز للنشر النهائي\nمتن.",
        "image": "drafts/dcfin1.jpg", "bucket": "serious",
        "source": {"link": "https://x/dcfin1", "publishers": ["BBC"]},
    }
    pending_draft = {
        "id": "dc0400000002", "status": "pending", "origin": "news",
        "arabic": {"post_title": "خبر لم يُعلَّم في النهائي"}, "caption": "متن ٢",
        "image": "drafts/dcfin2.jpg", "bucket": "serious",
        "source": {"link": "https://x/dcfin2", "publishers": ["BBC"]},
    }
    for d in (approved_draft, pending_draft):
        store.save_draft(d)
    (DRAFTS_DIR / "dcfin1.jpg").write_bytes(b"\xff\xd8\xff")
    (DRAFTS_DIR / "dcfin2.jpg").write_bytes(b"\xff\xd8\xff")

    body = review.build_final_review_body([approved_draft, pending_draft], "u/r", "main")
    body = tick_marker(body, f"<!-- go:publish:{approved_draft['id']} -->")

    real_fetch = publish_mod.fetch_issue
    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    real_comment = review.comment
    real_close = review.close_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "final-review"}]}
    publish_mod.ROOT = DRAFTS_DIR.parent

    def fake_publish_photo(image_path, caption, api_version, first_comment=None):
        return {"url": "https://fb.example/dcfin", "id": "1"}

    facebook.publish_photo = fake_publish_photo
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: None

    sys.argv = ["publish", "--issue", "9542", "--now"]
    try:
        code1 = publish_mod.main()
        code2 = publish_mod.main()   # محاكاة مساري urgent ثم normal لنفس حدث approved
    finally:
        publish_mod.fetch_issue = real_fetch
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo
        review.comment = real_comment
        review.close_issue = real_close

    check("كلتا التشغيلتين على الـIssue النهائي تنتهيان بنجاح", code1 == 0 and code2 == 0,
          (code1, code2))

    entries = decisions.load()
    pub_entries = [e for e in entries if e["id"] == approved_draft["id"]]
    rej_entries = [e for e in entries if e["id"] == pending_draft["id"]]
    check("المعتمَد في المراجعة النهائية سُجّل مرة واحدة بقرار published",
          len(pub_entries) == 1 and pub_entries[0]["decision"] == "published", pub_entries)
    check("غير المعلَّم في المراجعة النهائية سُجّل مرة واحدة فقط بقرار rejected_unchecked",
          len(rej_entries) == 1 and rej_entries[0]["decision"] == "rejected_unchecked"
          and rej_entries[0]["reject_tag"] == "لم يُعتمد", rej_entries)

@auto_restore_last_publish
def test_publish_final_review_double_publish_guard() -> None:
    """Issue #858، الجزء الثاني، البند 3: مسودة نُشرت فعلًا (مثلًا عبر
    تشغيل urgent سابق لنفس حدث وسم approved وصل هذا الـIssue النهائي قبل
    تشغيل normal، Issue #745) لا يجوز أن تُنشر ثانية -- الحارس على
    status == "published" مباشرة، نفس مبدأ youtube_publish.publish_ids."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    already_published = {
        "id": "fa0000000003", "status": "published", "origin": "news",
        "arabic": {"post_title": "خبر نُشر مسبقًا"}, "caption": "متن",
        "image": "drafts/fr3.jpg", "bucket": "serious",
        "source": {"link": "https://x/fr3", "publishers": ["BBC"]},
    }
    store.save_draft(already_published)

    body = review.build_final_review_body([already_published], "u/r", "main")
    body = tick_marker(body, f"<!-- go:publish:{already_published['id']} -->")

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

@auto_restore_last_publish
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
    reset_last_publish()

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
    body = tick_marker(body, f"<!-- go:go2:{back_only['id']} -->")
    body = tick_marker(body, f"<!-- go:go2:{back_and_approved['id']} -->")
    body = tick_marker(body, f"<!-- go:publish:{back_and_approved['id']} -->")

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

@auto_restore_last_publish
def test_publish_final_review_excludes_analysis_origin_from_news_path() -> None:
    """Issue #858 الأصلي، الجزء الثاني، البند 5 (ضيّق نطاقه Issue #1000):
    التقاطع الخاص بمسار الأخبار وحده (``card_requests = review.parse_card_requests(body)
    & set(news_ids)`` في ``publish.main``) لا يلتقط معرّف مسودة تحليل أبدًا،
    حتى لو حمل جسم الـIssue مربع 🎴 له -- ``news_ids`` تُبنى من التوجيه
    بالأصل (``store.origin_of``) لا من محتوى المربعات، فمعرّف تحليل لا يصل
    هذا التقاطع إطلاقًا بصرف النظر عمّا عُلِّم عليه. هذا لا يعني أن 🎴
    بلا أثر لمسودة تحليل -- انظر
    ``test_publish_analysis_card_request_routes_to_own_final_review`` أدناه
    لمسارها الخاص (عبر ``youtube_publish.publish_ids``)، الذي صار الآن
    يعالج 🎴 فعليًا (Issue #1000) بعد أن كان خارج النطاق صراحةً في #858/#860."""
    from src import publish as publish_mod
    from src import youtube_publish as yp

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    yt_draft = {
        "id": "aa0000000006", "status": "pending", "origin": "analysis",
        "arabic": {"post_title": "مقال تحليل", "urgent": False},
        "headlines": ["عنوان ١", "عنوان ٢", "عنوان ٣"], "headline_selected": 0,
        "caption": "متن", "source": {"link": "", "publishers": []},
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
        create_issue_calls.append(labels), {"number": 9977, "html_url": "#"})[1]

    real_comment = review.comment
    real_close = review.close_issue
    real_ensure_labels = review.ensure_labels
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: None
    review.ensure_labels = lambda: None

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
        review.ensure_labels = real_ensure_labels

    check("publish.main ينتهي بنجاح", code == 0, f"exit={code}")
    check("مسودة التحليل سلكت مسارها الخاص (بطاقة عنوان بُنيت عبره)",
          card_calls == [yt_draft["id"]], card_calls)
    check("🎴 يمنع النشر المباشر لمسودة التحليل أيضًا -- لم تُنشر عبر publish_one",
          published_ids == [], published_ids)
    check("Issue مراجعة نهائي واحد فُتح عبر مسار التحليل الخاص (لا مسار الأخبار)"
          " -- بوسم final-review",
          create_issue_calls == [["final-review"]], create_issue_calls)
    persisted = store.load_draft(yt_draft["id"])[1]
    check("المسودة تبقى pending بانتظار الـIssue النهائي", persisted.get("status") == "pending",
          persisted.get("status"))
    check("review_issue أصبح رقم الـIssue النهائي المفتوح عبر مسار التحليل",
          persisted.get("review_issue") == 9977, persisted.get("review_issue"))

@auto_restore_last_publish
def test_publish_analysis_card_request_routes_to_own_final_review() -> None:
    """Issue #1000: إدخال مسار التحليل في دورة المراجعة الموحَّدة، الجزء الأول
    -- مقال معتمَد مع 🎴 في Issue مراجعة التحليل (youtube-review) لا يُنشر
    فورًا: بطاقته تُبنى (ensure_title_card عبر youtube_publish.publish_ids)
    ثم يُجمَّع في Issue مراجعة نهائية واحد بوسم final-review (عبر
    publish.open_final_review -- نفس دالة مسار الأخبار حرفيًا، لا باني نصّ
    ثالث)، وتعليق على Issue التحليل الأصلي يذكر رقمه. غير المؤشَّر بـ🎴 يُنشر
    فورًا كما كان دومًا."""
    from src import publish as publish_mod
    from src import youtube_publish as yp

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    direct_draft = {
        "id": "bb0000000001", "status": "pending", "origin": "analysis",
        "title": "مقال ينشر فورًا",
        "arabic": {"post_title": "مقال ينشر فورًا", "urgent": False},
        "headlines": ["عنوان ١"], "headline_selected": 0,
        "caption": "متن ١", "source": {"link": "", "publishers": ["الجزيرة"]},
        "tier": "c", "blocs": ["arabic"], "channels": ["الجزيرة"],
        "agreement": "agreement", "warnings": [], "score": 1,
    }
    card_draft = {
        "id": "bb0000000002", "status": "pending", "origin": "analysis",
        "title": "مقال بانتظار مراجعة نهائية",
        "arabic": {"post_title": "مقال بانتظار مراجعة نهائية", "urgent": False},
        "headlines": ["عنوان ٢"], "headline_selected": 0,
        "caption": "متن ٢", "source": {"link": "", "publishers": ["الجزيرة"]},
        "tier": "a", "blocs": ["arabic"], "channels": ["الجزيرة"],
        "agreement": "agreement", "warnings": [], "score": 2,
    }
    for d in (direct_draft, card_draft):
        store.save_draft(d)

    body = yp.build_review_body([direct_draft, card_draft], "user/trendnews", "main", load_config())
    # Issue #1187: الانتقال بعلامات go: (لا draft:/card:) — publish ثم go3.
    body = tick_marker(body, f"<!-- go:publish:{direct_draft['id']} -->")
    body = tick_marker(body, f"<!-- go:go3:{card_draft['id']} -->")
    check("خيار go3 (بطاقة المرحلة 3) يظهر فعليًا في جسم Issue مراجعة التحليل الحقيقي (لا محاكاة)",
          f"<!-- go:go3:{card_draft['id']} -->" in body, body[:600])

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

    def fake_create_issue(title, body, labels=None):
        create_issue_calls.append({"title": title, "body": body, "labels": labels})
        return {"number": 9978, "html_url": "https://x/issues/9978"}

    review.create_issue = fake_create_issue

    comments: list = []
    real_comment = review.comment
    real_close = review.close_issue
    real_ensure_labels = review.ensure_labels
    review.comment = lambda issue_number, text: comments.append((issue_number, text))
    review.close_issue = lambda issue_number: None
    review.ensure_labels = lambda: None

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "youtube-review"}, {"name": "approved"}]}

    sys.argv = ["publish", "--issue", "7001", "--skip-urgent"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        yp.ensure_title_card = real_ensure_title_card
        publish_mod.publish_one = real_publish_one
        review.create_issue = real_create_issue
        review.comment = real_comment
        review.close_issue = real_close
        review.ensure_labels = real_ensure_labels

    check("publish.main ينتهي بنجاح", code == 0, f"exit={code}")
    check("كلا المقالين بُنيت بطاقتهما", set(card_calls) == {direct_draft["id"], card_draft["id"]},
          card_calls)
    check("بلا 🎴: نُشر فورًا عبر publish_one", published_ids == [direct_draft["id"]],
          published_ids)
    check("مع 🎴: لم يُنشر إطلاقًا", card_draft["id"] not in published_ids, published_ids)

    persisted_direct = store.load_draft(direct_draft["id"])[1]
    check("بلا 🎴: الحالة published", persisted_direct.get("status") == "published",
          persisted_direct.get("status"))
    persisted_card = store.load_draft(card_draft["id"])[1]
    check("مع 🎴: الحالة تبقى pending", persisted_card.get("status") == "pending",
          persisted_card.get("status"))

    check("Issue مراجعة نهائي واحد فُتح", len(create_issue_calls) == 1, create_issue_calls)
    if create_issue_calls:
        opened = create_issue_calls[0]
        check("بوسم final-review", opened["labels"] == ["final-review"], opened["labels"])
        check("جسمه يحوي معرّف المقال المؤجَّل فقط -- لا المنشور مباشرة",
              f"<!-- draft:{card_draft['id']} -->" in opened["body"]
              and f"<!-- draft:{direct_draft['id']} -->" not in opened["body"],
              opened["body"][:400])
    check("review_issue للمقال المؤجَّل أصبح رقم الـIssue النهائي",
          persisted_card.get("review_issue") == 9978, persisted_card.get("review_issue"))
    check("تعليق على Issue مراجعة التحليل الأصلي يذكر رقم الـIssue النهائي",
          any(i == 7001 and "9978" in t for i, t in comments), comments)

@auto_restore_last_publish
def test_publish_final_review_analysis_origin_routes_through_publish_ids() -> None:
    """Issue #1000، ثم #1008: cmd_final_review (المعالج الفعلي لـIssue وسمه
    final-review) يفصل مسودة origin=='analysis' عن الباقي ويُنشرها عبر
    youtube_publish.publish_ids -- لا publish_one مباشرة كالمسار العام (Issue
    #1008: النشر المباشر بلا سقف كان يتجاوز youtube.publish.max_per_run/
    spacing_minutes لأي دفعة تحليل تصل Issue نهائي). مسودة واحدة هنا وحدها
    (تحت السقف الافتراضي 3)، فتُنشر فورًا رغم التوجيه الجديد -- سقف/تباعد
    دفعة أكبر من واحدة مغطّى في
    test_publish_final_review_analysis_cap_and_spacing_across_two_runs أدناه.
    يغطّي أربع سلوكيات معًا: النشر الفعلي عبر publish_ids (وبالتالي
    publish_one داخلها)، حارس النشر المزدوج (status=='published')، الرفض
    الضمني لغير المعلَّم (#841)، و↩️ التي تُبقي المسودة pending بلا حقل image
    فتصبح مؤهَّلة تلقائيًا لـ``youtube_publish.pending_youtube_drafts()``
    (مراجعة التحليل التالية) لا لمراجعة الأخبار العامة -- بنية قائمة
    (استبعاد origin=='analysis' في src.open_review.main، فلترة
    origin=='analysis' في pending_youtube_drafts) بلا أي تعديل جديد هنا."""
    from src import feedback, youtube_publish as yp
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    # معرّفات hex فعليًا (اصطلاح المشروع، وID_MARKER/CARD_MARKER/BACK_MARKER
    # في review.py لا تطابق إلا [0-9a-f]+ -- "an..." كانت تسقط بصمت من كل
    # مربعات هذا الاختبار.
    approved_analysis = {
        "id": "aa1000000001", "status": "pending", "origin": "analysis",
        "arabic": {"post_title": "مقال تحليل جاهز للنشر النهائي"},
        "caption": "مقال تحليل جاهز للنشر النهائي\nمتن.",
        "image": "drafts/aa1.jpg", "source": {"link": "", "publishers": ["الجزيرة"]},
    }
    already_published = {
        "id": "aa1000000002", "status": "published", "origin": "analysis",
        "arabic": {"post_title": "مقال نُشر مسبقًا"}, "caption": "متن",
        "image": "drafts/aa2.jpg", "source": {"link": "", "publishers": ["الجزيرة"]},
    }
    back_analysis = {
        "id": "aa1000000003", "status": "pending", "origin": "analysis",
        "arabic": {"post_title": "مقال يعود لمراجعة التحليل"}, "caption": "متن ٣",
        "image": "drafts/aa3.jpg", "image_info": {"used_original": True},
        "review_issue": 5001, "source": {"link": "", "publishers": ["الجزيرة"]},
    }
    unchecked_analysis = {
        "id": "aa1000000004", "status": "pending", "origin": "analysis",
        "arabic": {"post_title": "مقال لم يُعلَّم"}, "caption": "متن ٤",
        "image": "drafts/aa4.jpg", "source": {"link": "", "publishers": ["الجزيرة"]},
    }
    for d in (approved_analysis, already_published, back_analysis, unchecked_analysis):
        store.save_draft(d)
    for name in ("aa1.jpg", "aa2.jpg", "aa3.jpg", "aa4.jpg"):
        (DRAFTS_DIR / name).write_bytes(b"\xff\xd8\xff")

    body = review.build_final_review_body(
        [approved_analysis, already_published, back_analysis, unchecked_analysis],
        "u/r", "main")
    body = tick_marker(body, f"<!-- go:publish:{approved_analysis['id']} -->")
    body = tick_marker(body, f"<!-- go:publish:{already_published['id']} -->")
    body = tick_marker(body, f"<!-- go:go2:{back_analysis['id']} -->")

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "final-review"}]}

    real_root = publish_mod.ROOT
    publish_mod.ROOT = DRAFTS_DIR.parent
    real_publish_photo = facebook.publish_photo
    publish_calls: list = []

    def fake_publish_photo(image_path, caption, api_version, first_comment=None):
        publish_calls.append(caption)
        return {"url": "https://fb.example/an", "id": "1"}

    facebook.publish_photo = fake_publish_photo

    real_comment = review.comment
    real_close = review.close_issue
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: None

    rejections_before = len(feedback.load())

    sys.argv = ["publish", "--issue", "5099", "--now"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo
        review.comment = real_comment
        review.close_issue = real_close

    check("publish.main ينتهي بنجاح على Issue نهائي بمسودات تحليل", code == 0, f"exit={code}")
    check("مسودة التحليل المعلَّمة نُشرت فعليًا عبر publish_one -- بلا أي استثناء origin",
          store.load_draft(approved_analysis["id"])[1]["status"] == "published",
          store.load_draft(approved_analysis["id"])[1].get("status"))
    check("نداء فيسبوك وقع مرة واحدة فقط -- للمعلَّمة الجديدة لا المنشورة مسبقًا",
          publish_calls == [approved_analysis["caption"]], publish_calls)
    check("حارس النشر المزدوج: المسودة المنشورة مسبقًا لم تُنشر ثانية",
          store.load_draft(already_published["id"])[1]["status"] == "published")

    persisted_back = store.load_draft(back_analysis["id"])[1]
    check("↩️: حقل image حُذف بنيويًا من مسودة التحليل أيضًا",
          "image" not in persisted_back, persisted_back)
    check("↩️: review_issue حُذف", "review_issue" not in persisted_back, persisted_back)
    check("↩️: الحالة تبقى pending", persisted_back.get("status") == "pending",
          persisted_back.get("status"))

    check("الرفض الضمني: غير المعلَّم في الـIssue النهائي صار rejected رغم origin=analysis",
          store.load_draft(unchecked_analysis["id"])[1]["status"] == "rejected",
          store.load_draft(unchecked_analysis["id"])[1].get("status"))

    rejections_after = feedback.load()
    new_entries = rejections_after[rejections_before:]
    check("رفض واحد فقط سُجِّل في feedback بوسم «لم يُعتمد»",
          len(new_entries) == 1 and new_entries[0]["tag"] == "لم يُعتمد", new_entries)

    # ↩️ يجب أن يُعيد المسودة لمراجعة التحليل التالية (youtube_publish) لا
    # لمراجعة الأخبار العامة (src.open_review) -- بنية قائمة بلا أي تعديل
    # جديد هنا: pending_youtube_drafts تفلتر origin=='analysis' صراحة،
    # وopen_review.main يستبعده صراحة (انظر توثيق الوحدتين).
    yt_pending_ids = {d["id"] for _, d in yp.pending_youtube_drafts()}
    check("↩️: المسودة مؤهَّلة الآن لمراجعة التحليل التالية (youtube-review)",
          back_analysis["id"] in yt_pending_ids, yt_pending_ids)

    news_pending_ids = {d["id"] for _, d in store.pending_drafts()
                        if store.origin_of(d) != "analysis"}
    check("↩️: المسودة غير مؤهَّلة لمراجعة الأخبار العامة (open_review.main يستبعد analysis)",
          back_analysis["id"] not in news_pending_ids, news_pending_ids)

@auto_restore_last_publish
def test_publish_final_review_analysis_cap_and_spacing_across_two_runs() -> None:
    """Issue #1008: خمس مسودات تحليل معتمَدة في Issue نهائي واحد تُحترم
    سقفها وتباعدها (youtube.publish.max_per_run=3/spacing_minutes=40) بدل
    الخروج دفعة واحدة عبر publish_one في حلقة بلا سقف كما كانت cmd_final_review
    تفعل. الباقي فوق السقف يُعامَل بنفس آلية cmd_revival حرفيًا (Issue #961):
    الـIssue لا يُغلق، وسم approved يُزال، وسطر ⏳ لكل باقية + سطر ختامي يطلب
    إعادة الوسم. تشغيلة ثانية بنفس جسم الـIssue تُكمل الباقي وتُغلقه، بلا
    رفض ضمني جديد (لا رفض هنا أصلًا -- كل الخمسة معتمَدة)."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    def _hex_id(i: int) -> str:
        return f"aa2{i:09x}"

    drafts = []
    for i in range(5):
        d = {
            "id": _hex_id(i), "status": "pending", "origin": "analysis",
            "arabic": {"post_title": f"مقال تحليل {i}", "urgent": False},
            "caption": f"مقال تحليل {i}\nمتن.",
            "image": f"drafts/cap{i}.jpg", "source": {"link": "", "publishers": ["الجزيرة"]},
        }
        store.save_draft(d)
        drafts.append(d)
        (DRAFTS_DIR / f"cap{i}.jpg").write_bytes(b"\xff\xd8\xff")

    body = review.build_final_review_body(drafts, "u/r", "main")
    for d in drafts:
        body = tick_marker(body, f"<!-- go:publish:{d['id']} -->")

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "final-review"}]}

    published_ids: list = []
    real_publish_one = publish_mod.publish_one

    def fake_publish_one(path, draft, cfg):
        published_ids.append(draft["id"])
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['id']}"

    publish_mod.publish_one = fake_publish_one

    real_sleep = youtube_publish.time.sleep
    sleep_calls: list = []
    youtube_publish.time.sleep = lambda s: sleep_calls.append(s)

    comments: list = []
    closed_issues: list = []
    removed_labels: list = []
    real_comment = review.comment
    real_close = review.close_issue
    real_remove_label = review.remove_label
    review.comment = lambda issue_number, text: comments.append((issue_number, text))
    review.close_issue = lambda issue_number: closed_issues.append(issue_number)
    review.remove_label = lambda issue_number, label: removed_labels.append((issue_number, label))

    sys.argv = ["publish", "--issue", "6001"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        publish_mod.publish_one = real_publish_one
        youtube_publish.time.sleep = real_sleep
        review.comment = real_comment
        review.close_issue = real_close
        review.remove_label = real_remove_label

    check("publish.main ينتهي بنجاح (التشغيلة الأولى)", code == 0, f"exit={code}")
    check("التشغيلة الأولى: ثلاث مسودات نُشرت (سقف 3)",
          published_ids == [_hex_id(0), _hex_id(1), _hex_id(2)], published_ids)
    statuses1 = {d["id"]: store.load_draft(d["id"])[1]["status"] for d in drafts}
    check("التشغيلة الأولى: الاثنتان الباقيتان بلا تغيير (pending)",
          statuses1[_hex_id(3)] == "pending" and statuses1[_hex_id(4)] == "pending",
          statuses1)
    check("التشغيلة الأولى: الـIssue لم يُغلق", closed_issues == [], closed_issues)
    check("التشغيلة الأولى: وسم approved أُزيل", removed_labels == [(6001, "approved")],
          removed_labels)
    check("التشغيلة الأولى: التعليق يحوي سطرَي ⏳ للمسودتين الباقيتين",
          comments and all(f"⏳ مقال تحليل {i}" in comments[-1][1] for i in (3, 4)),
          comments)
    check("التشغيلة الأولى: سطر إعادة الوسم موجود",
          comments and "أعد وضع وسم `approved`" in comments[-1][1], comments)

    # التشغيلة الثانية: نفس جسم الـIssue -- تنشر الباقيتين وتُغلق الـIssue.
    published_ids.clear()
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "final-review"}]}
    publish_mod.publish_one = fake_publish_one
    youtube_publish.time.sleep = lambda s: sleep_calls.append(s)
    review.comment = lambda issue_number, text: comments.append((issue_number, text))
    review.close_issue = lambda issue_number: closed_issues.append(issue_number)
    review.remove_label = lambda issue_number, label: removed_labels.append((issue_number, label))

    from src import feedback
    rejections_before = len(feedback.load())

    sys.argv = ["publish", "--issue", "6001"]
    try:
        code2 = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        publish_mod.publish_one = real_publish_one
        youtube_publish.time.sleep = real_sleep
        review.comment = real_comment
        review.close_issue = real_close
        review.remove_label = real_remove_label

    check("publish.main ينتهي بنجاح (التشغيلة الثانية)", code2 == 0, f"exit={code2}")
    check("التشغيلة الثانية: الاثنتان الباقيتان نُشرتا",
          set(published_ids) == {_hex_id(3), _hex_id(4)}, published_ids)
    check("التشغيلة الثانية: الـIssue أُغلق", closed_issues == [6001], closed_issues)

    rejections_after = feedback.load()
    check("لا رفض ضمني جديد عبر التشغيلتين (كل الخمسة معتمَدة أصلًا)",
          len(rejections_after) == rejections_before,
          (rejections_before, len(rejections_after)))

@auto_restore_last_publish
def test_publish_final_review_news_origin_immediate_no_cap() -> None:
    """Issue #1008: مسار الأخبار في cmd_final_review لا يتغيّر إطلاقًا --
    تثبيت السلوك القائم منذ #858: دفعة أخبار أكبر من سقف التحليل (3) تُنشر
    كلها فورًا في نفس التشغيلة، بلا سقف ولا فاصل، خلافًا لمسودات التحليل."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    def _hex_id(i: int) -> str:
        return f"fb3{i:09x}"

    drafts = []
    for i in range(4):
        d = {
            "id": _hex_id(i), "status": "pending", "origin": "news",
            "arabic": {"post_title": f"خبر {i}", "urgent": False},
            "caption": f"خبر {i}\nمتن.", "bucket": "serious",
            "image": f"drafts/news{i}.jpg",
            "source": {"link": f"https://x/{i}", "publishers": ["BBC"]},
        }
        store.save_draft(d)
        drafts.append(d)
        (DRAFTS_DIR / f"news{i}.jpg").write_bytes(b"\xff\xd8\xff")

    body = review.build_final_review_body(drafts, "u/r", "main")
    for d in drafts:
        body = tick_marker(body, f"<!-- go:publish:{d['id']} -->")

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "final-review"}]}

    published_ids: list = []
    real_publish_one = publish_mod.publish_one

    def fake_publish_one(path, draft, cfg):
        published_ids.append(draft["id"])
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['id']}"

    publish_mod.publish_one = fake_publish_one

    closed_issues: list = []
    removed_labels: list = []
    real_comment = review.comment
    real_close = review.close_issue
    real_remove_label = review.remove_label
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: closed_issues.append(issue_number)
    review.remove_label = lambda issue_number, label: removed_labels.append((issue_number, label))

    sys.argv = ["publish", "--issue", "6002"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        publish_mod.publish_one = real_publish_one
        review.comment = real_comment
        review.close_issue = real_close
        review.remove_label = real_remove_label

    check("publish.main ينتهي بنجاح", code == 0, f"exit={code}")
    check("الأربعة نُشرت في نفس التشغيلة -- بلا سقف لمسار الأخبار",
          set(published_ids) == {d["id"] for d in drafts}, published_ids)
    check("الـIssue أُغلق فورًا", closed_issues == [6002], closed_issues)
    check("لا إزالة وسم -- لا شيء ينتظر تشغيلة لاحقة", removed_labels == [], removed_labels)

@auto_restore_last_publish
def test_publish_final_review_mixed_origin_news_immediate_analysis_capped() -> None:
    """Issue #1008: Issue نهائي يخلط الأصلين معًا -- الأخبار تُنشر فورًا بلا
    سقف، والتحليل يخضع لسقف/تباعد youtube.publish.max_per_run/spacing_minutes
    في نفس التشغيلة، بصرف النظر عن ترتيب المعرّفات في جسم الـIssue."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    news_drafts = []
    for i in range(2):
        d = {
            "id": f"fc4{i:09x}", "status": "pending", "origin": "news",
            "arabic": {"post_title": f"خبر مختلط {i}", "urgent": False},
            "caption": f"خبر مختلط {i}\nمتن.", "bucket": "serious",
            "image": f"drafts/mixnews{i}.jpg",
            "source": {"link": f"https://x/mix{i}", "publishers": ["BBC"]},
        }
        store.save_draft(d)
        news_drafts.append(d)
        (DRAFTS_DIR / f"mixnews{i}.jpg").write_bytes(b"\xff\xd8\xff")

    analysis_drafts = []
    for i in range(4):
        d = {
            "id": f"fc5{i:09x}", "status": "pending", "origin": "analysis",
            "arabic": {"post_title": f"تحليل مختلط {i}", "urgent": False},
            "caption": f"تحليل مختلط {i}\nمتن.",
            "image": f"drafts/mixan{i}.jpg",
            "source": {"link": "", "publishers": ["الجزيرة"]},
        }
        store.save_draft(d)
        analysis_drafts.append(d)
        (DRAFTS_DIR / f"mixan{i}.jpg").write_bytes(b"\xff\xd8\xff")

    all_drafts = news_drafts + analysis_drafts
    body = review.build_final_review_body(all_drafts, "u/r", "main")
    for d in all_drafts:
        body = tick_marker(body, f"<!-- go:publish:{d['id']} -->")

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "final-review"}]}

    published_ids: list = []
    real_publish_one = publish_mod.publish_one

    def fake_publish_one(path, draft, cfg):
        published_ids.append(draft["id"])
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['id']}"

    publish_mod.publish_one = fake_publish_one

    real_sleep = youtube_publish.time.sleep
    youtube_publish.time.sleep = lambda s: None

    closed_issues: list = []
    removed_labels: list = []
    real_comment = review.comment
    real_close = review.close_issue
    real_remove_label = review.remove_label
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: closed_issues.append(issue_number)
    review.remove_label = lambda issue_number, label: removed_labels.append((issue_number, label))

    sys.argv = ["publish", "--issue", "6003"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        publish_mod.publish_one = real_publish_one
        youtube_publish.time.sleep = real_sleep
        review.comment = real_comment
        review.close_issue = real_close
        review.remove_label = real_remove_label

    check("publish.main ينتهي بنجاح", code == 0, f"exit={code}")
    check("الخبران نُشرا فورًا", all(d["id"] in published_ids for d in news_drafts),
          published_ids)
    check("التحليل: ثلاثة فقط نُشرت (سقف 3) من أربعة معتمَدة",
          sum(1 for d in analysis_drafts if d["id"] in published_ids) == 3, published_ids)
    check("الـIssue لم يُغلق -- تحليل باقٍ فوق السقف", closed_issues == [], closed_issues)
    check("وسم approved أُزيل", removed_labels == [(6003, "approved")], removed_labels)

@auto_restore_last_publish
def test_publish_final_review_analysis_already_published_skipped() -> None:
    """Issue #1008: مسودة تحليل status=='published' في Issue نهائي معتمَد لا
    تُنشر ثانية -- لا عبر publish_one مباشرة ولا عبر youtube_publish.publish_ids
    (نفس حارس النشر المزدوج القائم أصلًا في cmd_revival/publish.main،
    والمطبَّق الآن أيضًا في التوجيه الجديد داخل cmd_final_review)."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    already = {
        "id": "fd6000000001", "status": "published", "origin": "analysis",
        "arabic": {"post_title": "تحليل منشور مسبقًا"}, "caption": "متن",
        "image": "drafts/pub1.jpg", "source": {"link": "", "publishers": ["الجزيرة"]},
    }
    store.save_draft(already)
    (DRAFTS_DIR / "pub1.jpg").write_bytes(b"\xff\xd8\xff")

    body = review.build_final_review_body([already], "u/r", "main")
    body = tick_marker(body, f"<!-- go:publish:{already['id']} -->")

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "final-review"}]}

    publish_calls: list = []
    real_publish_one = publish_mod.publish_one

    def fake_publish_one(path, draft, cfg):
        publish_calls.append(draft["id"])
        return True, f"- ✅ {draft['id']}"

    publish_mod.publish_one = fake_publish_one

    called_publish_ids: list = []
    real_publish_ids = youtube_publish.publish_ids

    def fake_publish_ids(ids, headline_choices, cfg, body="", issue_number=None):
        called_publish_ids.append(list(ids))
        return real_publish_ids(ids, headline_choices, cfg, body=body, issue_number=issue_number)

    youtube_publish.publish_ids = fake_publish_ids

    real_comment = review.comment
    real_close = review.close_issue
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: None

    sys.argv = ["publish", "--issue", "6004"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        publish_mod.publish_one = real_publish_one
        youtube_publish.publish_ids = real_publish_ids
        review.comment = real_comment
        review.close_issue = real_close

    check("publish.main ينتهي بنجاح", code == 0, f"exit={code}")
    check("publish_one لم يُستدعَ للمسودة المنشورة مسبقًا", publish_calls == [], publish_calls)
    check("youtube_publish.publish_ids لم يُستدعَ أصلًا -- استُبعدت قبل الفصل",
          called_publish_ids == [], called_publish_ids)
    check("الحالة بقيت published",
          store.load_draft(already["id"])[1]["status"] == "published")

@auto_restore_last_publish
def test_publish_final_review_analysis_unchecked_rejected_once_across_two_runs() -> None:
    """Issue #1008: مسودة تحليل ظهرت في جسم Issue نهائي لكن لم تُعلَّم ✔️
    تصير rejected مرة واحدة فقط رغم تشغيلتين متتاليتين على نفس الجسم -- نفس
    مبدأ الرفض الضمني القائم (#841): يُحسب مرة واحدة عند أول اعتماد، ولا
    يتكرر لمسودة بقيت pending... ثم rejected من دفعة سابقة."""
    from src import feedback
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    unchecked = {
        "id": "fe7000000001", "status": "pending", "origin": "analysis",
        "arabic": {"post_title": "تحليل لم يُعلَّم في النهائي"}, "caption": "متن",
        "image": "drafts/unch.jpg", "source": {"link": "", "publishers": ["الجزيرة"]},
    }
    store.save_draft(unchecked)
    (DRAFTS_DIR / "unch.jpg").write_bytes(b"\xff\xd8\xff")

    # لا اعتماد ✔️ على هذا المعرّف إطلاقًا -- يبقى ضمن all_draft_ids فقط.
    body = review.build_final_review_body([unchecked], "u/r", "main")

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "final-review"}]}

    real_comment = review.comment
    real_close = review.close_issue
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: None

    rejections_before = len(feedback.load())

    sys.argv = ["publish", "--issue", "6005"]
    try:
        code1 = publish_mod.main()
        code2 = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        review.comment = real_comment
        review.close_issue = real_close

    check("التشغيلتان تنتهيان بنجاح", code1 == 0 and code2 == 0, (code1, code2))
    check("المسودة صارت rejected",
          store.load_draft(unchecked["id"])[1]["status"] == "rejected",
          store.load_draft(unchecked["id"])[1].get("status"))
    rejections_after = feedback.load()
    new_entries = rejections_after[rejections_before:]
    check("رفض واحد فقط سُجِّل رغم تشغيلتين", len(new_entries) == 1, new_entries)

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

@auto_restore_last_publish
def test_burst_inline_cap_zero_defers_without_sleep() -> None:
    """Issue #315: finalize يستدعي cmd_burst داخل مهمة urgent (سقفها 20
    دقيقة)، وأصغر فاصل يحسبه spaced_slots هو 30 دقيقة — أي sleep واحد
    يتجاوز السقف حتمًا. inline_cap_minutes=0 يجب أن يمنع أي sleep تمامًا:
    يُنشر المستحق الآن فقط (wait<=0)، والبقية queued بلا انتظار."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

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

@auto_restore_last_publish
def test_burst_urgent_still_immediate_with_inline_cap_zero() -> None:
    """العاجل يخرج فورًا مهما كان حجم الدفعة — inline_cap_minutes=0 يمسّ
    البقية العادية فقط، ولا يغيّر منطق العاجل (wait=0 بلا شرط) إطلاقًا."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

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

@auto_restore_last_publish
def test_due_publishes_one_at_a_time() -> None:
    """Issue #327 البند 2: لو فاتت queue.yml تشغيلة أو أكثر، تتراكم عدة
    مسودات مستحقة معًا. cmd_due يجب ألا ينشرها كلها في حلقة واحدة بلا
    فاصل — هذا هو النمط الآلي الذي صُمم spaced_slots لتجنّبه أصلًا.
    ينشر الأقدم موعدًا فقط، ويترك الباقي queued للتشغيلة التالية."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

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

@auto_restore_last_publish
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
    reset_last_publish()

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
    # بوابة الفاصل (Issue #1010): g2 تُعالَج فعليًا (لم تتوقف الدفعة عند
    # المعطوبة) لكنها تصير queued لا published — g1 نشر للتوّ في نفس
    # الدفعة، فأقل من gap_min مرّ. المهم هنا أنها ليست عالقة pending ولا
    # سقطت مع المعطوبة، لا توقيت نشرها الدقيق.
    g2_status = store.load_draft("g2")[1]["status"]
    check("المسودة الثالثة عولجت رغم تعطّب ما قبلها في نفس الدفعة "
          "(لم تبقَ pending) — أجّلتها البوابة إذ نُشر g1 للتوّ",
          g2_status == "queued", g2_status)

@auto_restore_last_publish
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
    reset_last_publish()

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

@auto_restore_last_publish
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
    reset_last_publish()

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

@auto_restore_last_publish
def test_publish_routes_news_origin_unaffected() -> None:
    """Issue #740 (ضابط): مسودة أخبار عادية (origin != youtube) معتمَدة
    بوسم approved يجب أن تسلك مسار الأخبار تمامًا كسابقًا — التوجيه بالأصل
    لا يغيّر سلوك المسار العام، ولا يستدعي منطق يوتيوب إطلاقًا."""
    from src import publish as publish_mod
    from src import youtube_publish as yp

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

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

@auto_restore_last_publish
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
    reset_last_publish()

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

@auto_restore_last_publish
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
    reset_last_publish()

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

@auto_restore_last_publish
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
    reset_last_publish()

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

@auto_restore_last_publish
def test_open_review_orders_drafts_by_score() -> None:
    """Issue #874، الشاهد الحرفي: أربع مسودات بدرجات 20.4، 29.8، 16.9، 17.9
    محفوظة بترتيب مسار ملف عشوائي يجب أن تظهر في نص Issue المراجعة الأولية
    مرتَّبة تنازليًا 29.8، 20.4، 17.9، 16.9 -- لا بترتيب القراءة من القرص."""
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

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

@auto_restore_last_publish
def test_publish_final_review_orders_by_score() -> None:
    """Issue #874: مسودات المراجعة النهائية (🎴) تُعرض مرتَّبة تنازليًا
    بالدرجة أيضًا -- سواء عبر publish.py (مسار الاعتماد الأولي مع 🎴) أو
    collect_finalize.py (مسار 🎴 المباشر من preselect)."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

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
        body = tick_marker(body, f"<!-- go:go3:{d['id']} -->")   # (#1182) ✔️+🎴

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

def test_names_unify_variant_spellings_through_real_pipeline() -> None:
    """Issue #1070: توحيد رسم أسماء الأعلام نقطة تطبيقه الوحيدة
    store.save_draft/update_draft (src/names.py)، فتُختبر هنا على مخرَج
    الأنبوب الفعلي لا على normalize_names وحدها -- مسودة تُحفظ برسوم
    بديلة في العنوان والمتن والتعليقين وheadlines، تُقرأ من القرص بعد
    الحفظ وبعد update_draft، ثم تُبنى بطاقتها عبر المسار الحقيقي
    (cards.ensure) للتأكد من أن العنوان المستعمل فعليًا موحَّد."""
    from src import cards

    cfg = load_config()
    aliases = cfg.path("names.aliases") or {}
    check("معجم names.aliases يحوي المداخل الثلاثة المبدئية",
          bool(aliases.get("نتنياهو")) and bool(aliases.get("ترامب"))
          and bool(aliases.get("أردوغان")), aliases)

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    draft = {
        "id": "nm1100000011", "status": "pending", "score": 1.0, "bucket": "serious",
        "state_media": False, "origin": "news",
        "source": {
            "title": "نتانياهو يبحث عن ترمب", "link": "https://example.com/نتانياهو-ترمب",
            "publisher": "نتانياهو نيوز", "publishers": ["نتانياهو نيوز"],
            "image_candidates": ["https://cdn.example/ok.jpg"],
        },
        "arabic": {
            "post_title": "نتانياهو يهاجم إردوغان",
            "body": "قال نتانياهو إن ترمب وإردوغان يلتقيان قريبًا",
            "caption": "تعليق فيه نتانياهو وترمب",
            "category": "", "urgent": False,
        },
        "caption": "تعليق منفصل فيه اردوغان",
        "headlines": ["نتانياهو وترمب", "اردوغان يردّ"],
        "headline_selected": 0,
    }
    path = store.save_draft(draft)
    reloaded = json.loads(path.read_text(encoding="utf-8"))

    check("post_title يُوحَّد بعد save_draft",
          reloaded["arabic"]["post_title"] == "نتنياهو يهاجم أردوغان",
          reloaded["arabic"]["post_title"])
    check("arabic.body يُوحَّد بعد save_draft",
          reloaded["arabic"]["body"] == "قال نتنياهو إن ترامب وأردوغان يلتقيان قريبًا",
          reloaded["arabic"]["body"])
    check("arabic.caption يُوحَّد بعد save_draft",
          reloaded["arabic"]["caption"] == "تعليق فيه نتنياهو وترامب",
          reloaded["arabic"]["caption"])
    check("caption (الحقل العلوي) يُوحَّد بعد save_draft",
          reloaded["caption"] == "تعليق منفصل فيه أردوغان", reloaded["caption"])
    check("headlines تُوحَّد كلها بعد save_draft",
          reloaded["headlines"] == ["نتنياهو وترامب", "أردوغان يردّ"], reloaded["headlines"])

    check("source.title لا يتغيّر رغم مطابقته لرسم بديل",
          reloaded["source"]["title"] == "نتانياهو يبحث عن ترمب", reloaded["source"]["title"])
    check("source.link لا يتغيّر", reloaded["source"]["link"] == "https://example.com/نتانياهو-ترمب",
          reloaded["source"]["link"])
    check("source.publisher/publishers لا يتغيّران",
          reloaded["source"]["publisher"] == "نتانياهو نيوز"
          and reloaded["source"]["publishers"] == ["نتانياهو نيوز"], reloaded["source"])
    check("id لا يتغيّر", reloaded["id"] == "nm1100000011", reloaded["id"])

    # تعديل يدوي (مثلًا من مراجع في review.py) على عنوان فيه رسم بديل --
    # update_draft يُوحِّده أيضًا، لا save_draft وحدها.
    store.update_draft(
        path, arabic={**reloaded["arabic"], "post_title": "نتانياهو يجتمع مع ترمب"})
    reloaded2 = json.loads(path.read_text(encoding="utf-8"))
    check("update_draft يوحّد عنوانًا معدَّلًا يدويًا",
          reloaded2["arabic"]["post_title"] == "نتنياهو يجتمع مع ترامب",
          reloaded2["arabic"]["post_title"])
    check("update_draft لا يمسّ source",
          reloaded2["source"]["title"] == "نتانياهو يبحث عن ترمب", reloaded2["source"]["title"])

    # البطاقة المبنيّة عبر المسار الحقيقي (cards.ensure تشتق chosen_headline
    # من arabic.post_title المخزَّن) تحمل الرسم المعتمد -- لا حاجة لقراءة
    # بكسلات الصورة، يكفي رصد النص الممرَّر فعليًا لباني الصورة.
    real_build = cards._default_build_post_image
    captured: list = []

    def spy_build(**kwargs):
        captured.append(kwargs.get("headline"))
        return real_build(**kwargs)

    cards._default_build_post_image = spy_build
    try:
        cards.ensure(path, reloaded2, cfg)
    finally:
        cards._default_build_post_image = real_build
    check("البطاقة الحقيقية تُبنى بعنوان الرسم المعتمد",
          bool(captured) and captured[0] == "نتنياهو يجتمع مع ترامب", captured)


def test_names_longest_variant_first_and_empty_config_noop() -> None:
    """Issue #1070: مدخل فيه رسمان أحدهما يحتوي الآخر -- الأطول يُستبدل
    أولًا (حتى لو كُتب الأقصر أولًا في القائمة) فلا استبدال جزئي مشوَّه.
    ومعجم فارغ أو غائب تمامًا -- لا تغيير في أي نص. كلاهما على مخرَج
    store.save_draft الفعلي، لا normalize_names وحدها."""
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    real_load_config = store.load_config

    def _draft(id_, text):
        return {
            "id": id_, "status": "pending", "score": 1.0, "bucket": "serious",
            "state_media": False, "origin": "news",
            "source": {"title": text, "link": f"https://example.com/{id_}",
                       "publisher": "س", "publishers": ["س"]},
            "arabic": {"post_title": text, "body": "", "caption": "",
                       "category": "", "urgent": False},
            "caption": "", "headlines": [], "headline_selected": 0,
        }

    try:
        # "قاهرة" رسم بديل مُحتوًى داخل "قاهرةجديدة" -- مكتوب في المعجم
        # بالترتيب الأقصر ثم الأطول عمدًا، لفحص أن الأطول يُستبدل فعلًا
        # أولًا رغم ذلك.
        store.load_config = lambda path=None: {
            "names": {"aliases": {"القاهرة": ["قاهرة", "قاهرةجديدة"]}}}
        d1 = _draft("nm2200000022", "زرت قاهرةجديدة أمس")
        p1 = store.save_draft(d1)
        r1 = json.loads(p1.read_text(encoding="utf-8"))
        check("الرسم الأطول يُستبدل أولًا فلا يبقى ذيل من الرسم الأقصر",
              r1["arabic"]["post_title"] == "زرت القاهرة أمس", r1["arabic"]["post_title"])

        # معجم غائب تمامًا (لا مفتاح names إطلاقًا)
        store.load_config = lambda path=None: {}
        d2 = _draft("nm3300000033", "نتانياهو وترمب")
        p2 = store.save_draft(d2)
        r2 = json.loads(p2.read_text(encoding="utf-8"))
        check("غياب قسم names كليًا -- لا تغيير في النص",
              r2["arabic"]["post_title"] == "نتانياهو وترمب", r2["arabic"]["post_title"])

        # قسم names فارغ (aliases فارغة)
        store.load_config = lambda path=None: {"names": {"aliases": {}}}
        d3 = _draft("nm4400000044", "نتانياهو وترمب")
        p3 = store.save_draft(d3)
        r3 = json.loads(p3.read_text(encoding="utf-8"))
        check("قسم names موجود لكنه فارغ -- لا تغيير في النص",
              r3["arabic"]["post_title"] == "نتانياهو وترمب", r3["arabic"]["post_title"])
    finally:
        store.load_config = real_load_config


# ──────────────── معجم أسماء يتعلّم نفسه (Issue #1074) ────────────────
# مساعدات مشتركة بين اختبارات src/names.py: record_seen/seen_totals،
# وsrc/names_learn.py: find_candidates/run/دمج الطبقة المتعلَّمة في
# src/names.normalize_names. فاكة نموذج تقرأ الأزواج من محتوى الرسالة
# نفسها (لا تفترض ترتيب الفهارس) بدل رد ثابت مسبق التركيب.

class _FakeVerdictBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeVerdictResp:
    def __init__(self, content, stop_reason: str = "end_turn") -> None:
        self.content = content
        self.stop_reason = stop_reason


class _FakeVerdictMessages:
    def __init__(self, responder) -> None:
        self._responder = responder

    def create(self, **kw):
        return self._responder(kw)


class _FakeVerdictClient:
    def __init__(self, responder) -> None:
        self.messages = _FakeVerdictMessages(responder)


def _fake_verdict_maker(pair_verdicts: dict, calls: list):
    """رادّ زائف لـnames_learn._ask_batch: يقرأ قائمة الأزواج من محتوى
    الرسالة نفسها فيردّ حكم كل زوج من ``pair_verdicts`` (مفتاحها
    frozenset بكلمتي الزوج، والقيمة الافتراضية "different" لزوج غير
    مذكور) -- بلا افتراض أي ترتيب فهارس ثابت بين تشغيلة وأخرى."""
    def _respond(kw):
        calls.append(1)
        content = kw["messages"][0]["content"]
        verdicts = []
        for line in content.splitlines():
            m = re.match(r'\s*(\d+)\.\s*"(.+)"\s*مقابل\s*"(.+)"\s*$', line)
            if not m:
                continue
            i, a, b = int(m.group(1)), m.group(2), m.group(3)
            verdict = pair_verdicts.get(frozenset((a, b)), "different")
            verdicts.append({"i": i, "verdict": verdict})
        text = json.dumps({"verdicts": verdicts}, ensure_ascii=False)
        return _FakeVerdictResp([_FakeVerdictBlock(text)])
    return _respond


def _forbid_client():
    raise AssertionError("لا يجوز نداء النموذج في هذا السيناريو")


def _set_seen(totals: dict) -> None:
    names.SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    names.SEEN_FILE.write_text(
        json.dumps({"2020-01": totals}, ensure_ascii=False, indent=2), encoding="utf-8")


def _clear_names_learn_state() -> None:
    names.SEEN_FILE.unlink(missing_ok=True)
    names_learn.LEARNED_FILE.unlink(missing_ok=True)


def test_names_seen_records_raw_spelling_before_normalization() -> None:
    """Issue #1074 (سيناريو 1): record_seen تُستدعى من store.save_draft
    قبل normalize_draft -- تُعدّ في state/names_seen.json بالرسم الخام
    «نتانياهو» لا الرسم المعتمد «نتنياهو» الذي يخرج به المتن بعد التوحيد
    (المعجم اليدوي الحقيقي في config.yaml يوحّدهما فعلًا، وهذا بالضبط ما
    يجعل الفارق بين العدّ والمتن قابلًا للفحص)."""
    _clear_names_learn_state()
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        draft = {
            "id": "sn1000000001", "status": "pending", "score": 1.0, "bucket": "serious",
            "state_media": False, "origin": "news",
            "source": {"title": "خبر", "link": "https://example.com/sn1000000001",
                       "publisher": "س", "publishers": ["س"]},
            "arabic": {"post_title": "نتانياهو يبحث عن حل", "body": "قال نتانياهو إن الأمر مهم",
                       "caption": "", "category": "", "urgent": False},
            "caption": "", "headlines": ["نتانياهو يرد"], "headline_selected": 0,
        }
        path = store.save_draft(draft)
        reloaded = json.loads(path.read_text(encoding="utf-8"))
        check("المتن يُوحَّد فعلًا (المعجم اليدوي الحقيقي نتنياهو/نتانياهو)",
              reloaded["arabic"]["post_title"] == "نتنياهو يبحث عن حل",
              reloaded["arabic"]["post_title"])

        totals = names.seen_totals()
        check("العدّ سجّل الرسم الخام «نتانياهو» لا المعتمد",
              totals.get("نتانياهو", 0) == 3, totals)
        check("الرسم المعتمد «نتنياهو» لم يُعدّ من هذه المسودة (لم يرد خامًا)",
              totals.get("نتنياهو", 0) == 0, totals)
    finally:
        _clear_names_learn_state()


def test_names_learn_cycle_writes_learned_and_next_draft_normalized() -> None:
    """Issue #1074 (سيناريو 2): دورة تعلّم بنموذج مزيَّف يرد same_name --
    المدخل يُكتب في names_learned.json بالمعتمد الأكثر ورودًا، والمسودة
    التالية (رسم أقل ورودًا فقط، بلا أي معجم يدوي لهذا الاسم) تُحفظ
    موحَّدة عبر الطبقة المتعلَّمة وحدها."""
    real_load_config = store.load_config
    _clear_names_learn_state()
    try:
        hi, lo = "زيلينسكي", "زيلينيسكي"
        _set_seen({hi: 70, lo: 2})
        cfg = dict(load_config())

        calls: list = []
        real_client = names_learn._client
        names_learn._client = lambda: _FakeVerdictClient(
            _fake_verdict_maker({frozenset((hi, lo)): "same_name"}, calls))
        try:
            names_learn.run(cfg)
        finally:
            names_learn._client = real_client

        check("نداء نموذج واحد لدفعة المرشحين", len(calls) == 1, calls)

        data = names_learn.load_learned()
        entry = (data.get("entries") or {}).get(hi)
        check("المدخل المتعلَّم يُكتب بالمعتمد الأكثر ورودًا",
              entry is not None and entry.get("variants") == [lo], data)
        check("عدّا الرسمين محفوظان كما وردا",
              bool(entry) and entry.get("counts") == {hi: 70, lo: 2}, entry)
        check("حكم same_name محفوظ", bool(entry) and entry.get("verdict") == "same_name", entry)

        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        store.load_config = lambda path=None: {"names": {}}  # بلا معجم يدوي لهذا الاسم
        draft = {
            "id": "nl2000000001", "status": "pending", "score": 1.0, "bucket": "serious",
            "state_media": False, "origin": "news",
            "source": {"title": "خبر", "link": "https://example.com/nl2000000001",
                       "publisher": "س", "publishers": ["س"]},
            "arabic": {"post_title": f"تصريح {lo} اليوم", "body": f"قال {lo} إن الاتفاق قريب",
                       "caption": "", "category": "", "urgent": False},
            "caption": "", "headlines": [f"{lo} يعلّق"], "headline_selected": 0,
        }
        p = store.save_draft(draft)
        r = json.loads(p.read_text(encoding="utf-8"))
        check("المسودة التالية تُحفظ موحَّدة عبر الطبقة المتعلَّمة وحدها",
              r["arabic"]["post_title"] == f"تصريح {hi} اليوم"
              and r["arabic"]["body"] == f"قال {hi} إن الاتفاق قريب"
              and r["headlines"] == [f"{hi} يعلّق"], r)
    finally:
        store.load_config = real_load_config
        _clear_names_learn_state()


def test_names_learn_rejects_inflection_and_different_and_remembers_rejection() -> None:
    """Issue #1074 (سيناريو 3): النموذج يرد inflection على «سعودية/سعودي»
    وdifferent على «اليمن/الأمن» -- لا مدخل يُكتب لأي منهما، والزوجان
    يُسجَّلان مرفوضين فلا يُسألان ثانية في تشغيلة لاحقة (بعد تخطّي بوابة
    24 ساعة يدويًا) -- يُثبَت بعدّ نداءات النموذج: يبقى عند 1."""
    _clear_names_learn_state()
    try:
        _set_seen({"سعودية": 20, "سعودي": 5, "اليمن": 30, "الأمن": 6})
        cfg = dict(load_config())

        calls: list = []
        real_client = names_learn._client
        names_learn._client = lambda: _FakeVerdictClient(_fake_verdict_maker(
            {frozenset(("سعودية", "سعودي")): "inflection",
             frozenset(("اليمن", "الأمن")): "different"}, calls))
        try:
            names_learn.run(cfg)
            check("نداء واحد للدفعة كلها (زوجان معًا)", len(calls) == 1, calls)

            data = names_learn.load_learned()
            check("inflection/different: لا مدخل متعلَّم يُكتب",
                  data.get("entries") == {}, data)
            check("الزوجان يُسجَّلان مرفوضين",
                  len(data.get("rejected_pairs") or []) == 2, data)

            data["last_run"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
            names_learn.save_learned(data)
            names_learn.run(cfg)
            check("زوج مرفوض سلفًا لا يُسأل عنه ثانية", len(calls) == 1, calls)
        finally:
            names_learn._client = real_client
    finally:
        _clear_names_learn_state()


def test_names_learn_numeric_gate_blocks_weak_pair_before_model_call() -> None:
    """Issue #1074 (سيناريو 4): زوج لا يجتاز الحواجز العددية (هنا 3 مقابل
    2 -- لا يبلغ الأكثر عتبة 5 ولا النسبة 3×) لا يصل إلى النموذج إطلاقًا
    -- يُثبَت بجعل _client يرفع استثناءً لو استُدعي أصلًا."""
    _clear_names_learn_state()
    try:
        _set_seen({"زيلينسكي": 3, "زيلينيسكي": 2})
        cfg = dict(load_config())

        real_client = names_learn._client
        names_learn._client = _forbid_client
        try:
            names_learn.run(cfg)
        finally:
            names_learn._client = real_client

        data = names_learn.load_learned()
        check("زوج ضعيف عدديًا: لا تعلّم ولا رفض (لم يصل للنموذج أصلًا)",
              data.get("entries") == {} and data.get("rejected_pairs") == [], data)
    finally:
        _clear_names_learn_state()


def test_names_learn_blocklist_blocks_new_and_disables_existing() -> None:
    """Issue #1074 (سيناريو 5): اسم في names.blocklist لا يُتعلَّم (لا يصل
    للنموذج)، وإن كان متعلَّمًا سلفًا فلا يُطبَّق في normalize_names رغم
    بقائه مخزَّنًا في names_learned.json."""
    real_load_config = store.load_config
    _clear_names_learn_state()
    try:
        hi, lo = "زيلينسكي", "زيلينيسكي"

        # أ) منع التعلّم الجديد
        _set_seen({hi: 70, lo: 2})
        real_client = names_learn._client
        names_learn._client = _forbid_client
        try:
            names_learn.run({"names": {"blocklist": [lo]}})
        finally:
            names_learn._client = real_client
        data = names_learn.load_learned()
        check("اسم في blocklist لا يُتعلَّم (لم يصل للنموذج)",
              data.get("entries") == {}, data)

        # ب) إلغاء تطبيق مدخل متعلَّم سلفًا
        names_learn.save_learned({
            "entries": {hi: {
                "variants": [lo], "counts": {hi: 70, lo: 2},
                "learned_at": datetime.now(timezone.utc).isoformat(),
                "verdict": "same_name",
            }},
            "rejected_pairs": [], "last_run": datetime.now(timezone.utc).isoformat(),
        })

        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

        def _draft(id_):
            return {
                "id": id_, "status": "pending", "score": 1.0, "bucket": "serious",
                "state_media": False, "origin": "news",
                "source": {"title": "خبر", "link": f"https://example.com/{id_}",
                           "publisher": "س", "publishers": ["س"]},
                "arabic": {"post_title": f"تصريح {lo} اليوم", "body": "", "caption": "",
                           "category": "", "urgent": False},
                "caption": "", "headlines": [], "headline_selected": 0,
            }

        store.load_config = lambda path=None: {"names": {"blocklist": [lo]}}
        p1 = store.save_draft(_draft("nl5000000001"))
        r1 = json.loads(p1.read_text(encoding="utf-8"))
        check("اسم في blocklist يُلغي تطبيق مدخل متعلَّم سلفًا رغم تخزينه",
              r1["arabic"]["post_title"] == f"تصريح {lo} اليوم", r1["arabic"]["post_title"])

        # بلا blocklist، المدخل المتعلَّم نفسه يُطبَّق فعليًا -- تحقّق سلبي
        # أن الإلغاء أعلاه سببه blocklist تحديدًا لا خلل آخر في التخزين.
        store.load_config = lambda path=None: {"names": {}}
        p2 = store.save_draft(_draft("nl5000000002"))
        r2 = json.loads(p2.read_text(encoding="utf-8"))
        check("بلا blocklist، المدخل المتعلَّم نفسه يُطبَّق فعلًا",
              r2["arabic"]["post_title"] == f"تصريح {hi} اليوم", r2["arabic"]["post_title"])
    finally:
        store.load_config = real_load_config
        _clear_names_learn_state()


def test_names_learn_manual_alias_overrides_learned_conflict() -> None:
    """Issue #1074 (سيناريو 6): تعارض بين مدخل متعلَّم ومعجم يدوي على
    الرسم البديل نفسه -- اليدوي يغلب دائمًا."""
    real_load_config = store.load_config
    _clear_names_learn_state()
    try:
        hi, lo = "زيلينسكي", "زيلينيسكي"
        names_learn.save_learned({
            "entries": {hi: {
                "variants": [lo], "counts": {hi: 70, lo: 2},
                "learned_at": datetime.now(timezone.utc).isoformat(),
                "verdict": "same_name",
            }},
            "rejected_pairs": [], "last_run": datetime.now(timezone.utc).isoformat(),
        })

        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

        manual_canonical = "زيلينسكي الرئيس"
        store.load_config = lambda path=None: {
            "names": {"aliases": {manual_canonical: [lo]}}}

        draft = {
            "id": "nl6000000001", "status": "pending", "score": 1.0, "bucket": "serious",
            "state_media": False, "origin": "news",
            "source": {"title": "خبر", "link": "https://example.com/nl6000000001",
                       "publisher": "س", "publishers": ["س"]},
            "arabic": {"post_title": f"تصريح {lo} اليوم", "body": "", "caption": "",
                       "category": "", "urgent": False},
            "caption": "", "headlines": [], "headline_selected": 0,
        }
        p = store.save_draft(draft)
        r = json.loads(p.read_text(encoding="utf-8"))
        check("عند التعارض يغلب المعجم اليدوي على المتعلَّم",
              r["arabic"]["post_title"] == f"تصريح {manual_canonical} اليوم",
              r["arabic"]["post_title"])
    finally:
        store.load_config = real_load_config
        _clear_names_learn_state()


def test_names_learn_disabled_flag_keeps_manual_only() -> None:
    """Issue #1074 (سيناريو 7): names.learned_enabled=false يوقف طبقة
    التعلّم كلها (لا تطبيق للمتعلَّم المخزَّن سلفًا) بلا مسّ المعجم اليدوي،
    الذي يستمر يعمل بلا تغيير في نفس المسودة."""
    real_load_config = store.load_config
    _clear_names_learn_state()
    try:
        hi, lo = "زيلينسكي", "زيلينيسكي"
        names_learn.save_learned({
            "entries": {hi: {
                "variants": [lo], "counts": {hi: 70, lo: 2},
                "learned_at": datetime.now(timezone.utc).isoformat(),
                "verdict": "same_name",
            }},
            "rejected_pairs": [], "last_run": datetime.now(timezone.utc).isoformat(),
        })

        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

        store.load_config = lambda path=None: {
            "names": {"learned_enabled": False, "aliases": {"ترامب": ["ترمب"]}}}

        draft = {
            "id": "nl7000000001", "status": "pending", "score": 1.0, "bucket": "serious",
            "state_media": False, "origin": "news",
            "source": {"title": "خبر", "link": "https://example.com/nl7000000001",
                       "publisher": "س", "publishers": ["س"]},
            "arabic": {"post_title": f"{lo} وترمب يتفقان", "body": "", "caption": "",
                       "category": "", "urgent": False},
            "caption": "", "headlines": [], "headline_selected": 0,
        }
        p = store.save_draft(draft)
        r = json.loads(p.read_text(encoding="utf-8"))
        check("learned_enabled=false: المتعلَّم لا يُطبَّق", lo in r["arabic"]["post_title"],
              r["arabic"]["post_title"])
        check("learned_enabled=false: اليدوي يستمر يعمل",
              "ترامب" in r["arabic"]["post_title"] and "ترمب" not in r["arabic"]["post_title"],
              r["arabic"]["post_title"])
    finally:
        store.load_config = real_load_config
        _clear_names_learn_state()


def test_names_learn_model_failure_no_learning_logs_error_and_collect_survives() -> None:
    """Issue #1074 (سيناريو 8): فشل نداء النموذج (عطل شبكة) ⇒ لا تعلّم
    هذه الدورة، لا تخمين ولا قبول افتراضي، وسطر ERROR واحد بالضبط --
    ودورة الجمع (عبر collect.run_names_learning، مسار الاستدعاء الحقيقي
    من collect.main) لا تتعطل بسببه."""
    from anthropic import APIError
    import httpx as _httpx

    _clear_names_learn_state()
    try:
        _set_seen({"زيلينسكي": 70, "زيلينيسكي": 2})
        cfg = dict(load_config())

        err = APIError("عطل شبكة اختباري",
                       request=_httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
                       body=None)

        class _RaisingMessages:
            def create(self, **kw):
                raise err

        class _RaisingClient:
            def __init__(self) -> None:
                self.messages = _RaisingMessages()

        real_client = names_learn._client
        names_learn._client = lambda: _RaisingClient()

        error_lines: list = []

        class _Handler(logging.Handler):
            def emit(self, record):
                if record.levelno == logging.ERROR:
                    error_lines.append(record.getMessage())

        handler = _Handler()
        names_learn.log.addHandler(handler)
        try:
            collect.run_names_learning(cfg)
        finally:
            names_learn._client = real_client
            names_learn.log.removeHandler(handler)

        data = names_learn.load_learned()
        check("فشل النداء: لا مدخل متعلَّم يُكتب", data.get("entries") == {}, data)
        check("فشل النداء: لا زوج يُسجَّل مرفوضًا (فشل تقني لا حكم لغوي)",
              data.get("rejected_pairs") == [], data)
        check("فشل النداء: سطر ERROR واحد بالضبط", len(error_lines) == 1, error_lines)
    finally:
        _clear_names_learn_state()


def test_names_learn_runs_at_most_once_per_24_hours() -> None:
    """Issue #1074 (سيناريو 9): التعلّم لا يعمل مرتين خلال 24 ساعة --
    تشغيلة ثانية فورية لا تستدعي النموذج إطلاقًا، وبعد تعديل last_run
    يدويًا إلى ما قبل 25 ساعة تعمل التشغيلة التالية من جديد فعليًا."""
    _clear_names_learn_state()
    try:
        hi1, lo1 = "زيلينسكي", "زيلينيسكي"
        _set_seen({hi1: 70, lo1: 2})
        cfg = dict(load_config())

        calls: list = []
        real_client = names_learn._client
        names_learn._client = lambda: _FakeVerdictClient(_fake_verdict_maker(
            {frozenset((hi1, lo1)): "same_name",
             frozenset(("مايكروسوفت", "ميكروسوفت")): "same_name"}, calls))
        try:
            names_learn.run(cfg)
            check("أول تشغيلة: نداء نموذج واحد", len(calls) == 1, calls)

            names_learn.run(cfg)
            check("تشغيلة ثانية خلال 24 ساعة: لا نداء إضافي", len(calls) == 1, calls)

            data = names_learn.load_learned()
            data["last_run"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
            names_learn.save_learned(data)

            # زوج جديد (الأول محكوم عليه سلفًا فلن يُرشَّح ثانية) كي يثبت
            # الاستدعاء الفعلي للنموذج بعد تخطّي البوابة، لا مجرد مرور
            # التشغيلة بلا مرشحين.
            hi2, lo2 = "مايكروسوفت", "ميكروسوفت"
            _set_seen({hi1: 70, lo1: 2, hi2: 6, lo2: 2})
            names_learn.run(cfg)
            check("بعد مرور 24 ساعة: التشغيلة التالية تعمل مجددًا",
                  len(calls) == 2, calls)
        finally:
            names_learn._client = real_client
    finally:
        _clear_names_learn_state()


def test_names_learn_levenshtein_true_edit_distance_passes_where_positional_would_fail() -> None:
    """Issue #1074 (سيناريو 10): مسافة ليفنشتاين الحقيقية بين «نتنياهو» و
    «نتانياهو» = 1 (إدراج حرف واحد) فتجتاز عتبة 2، بينما مقارنة حرف-بحرف
    موضعية (كانت السبب الموثَّق لضياع هذه الحالة في القياس الأصلي) تُخرج
    عدة اختلافات وهميّة لأن الإدراج يُزيح كل ما بعده. يُختبَر أولًا مباشرة
    على المسافة نفسها للتوثيق، ثم على مخرَج find_candidates الفعلي
    (بوابة الترشيح التي يستعملها run())."""
    a, b = "نتنياهو", "نتانياهو"
    positional_diffs = (sum(1 for x, y in zip(a, b) if x != y)
                        + abs(len(a) - len(b)))
    real_distance = names_learn._levenshtein(
        names_learn._unify_structure(a), names_learn._unify_structure(b))
    check("ليفنشتاين الحقيقية بين نتنياهو/نتانياهو = 1", real_distance == 1, real_distance)
    check("المقارنة الموضعية الساذجة كانت ستُخرج أكثر من اختلاف واحد ⇐ تفوّت الحالة",
          positional_diffs > 1, positional_diffs)

    _clear_names_learn_state()
    try:
        _set_seen({a: 70, b: 2})
        candidates = names_learn.find_candidates(
            names.seen_totals(), {"entries": {}, "rejected_pairs": []}, set())
        check("الزوج يجتاز بوابة الترشيح الفعلية فيصل ليكون مرشَّحًا لنداء النموذج",
              (a, b, 70, 2) in candidates, candidates)
    finally:
        _clear_names_learn_state()


def test_insights_learned_names_section_format_and_empty_when_nothing_this_week() -> None:
    """Issue #1074 (الإبلاغ الأسبوعي): سطر واحد بالشكل المطلوب حرفيًا لكل
    اسم وُحِّد خلال آخر 7 أيام، وجملة إلغاء عبر blocklist، ولا قسم إطلاقًا
    إن لم يتعلّم شيئًا هذا الأسبوع (مدخل قديم خارج النافذة لا يظهر)."""
    from src import insights

    _clear_names_learn_state()
    try:
        now = datetime.now(timezone.utc)
        names_learn.save_learned({
            "entries": {
                "نتنياهو": {
                    "variants": ["نتانياهو"],
                    "counts": {"نتنياهو": 70, "نتانياهو": 2},
                    "learned_at": now.isoformat(),
                    "verdict": "same_name",
                },
                "قديم": {
                    "variants": ["قديم2"],
                    "counts": {"قديم": 10, "قديم2": 3},
                    "learned_at": (now - timedelta(days=30)).isoformat(),
                    "verdict": "same_name",
                },
            },
            "rejected_pairs": [], "last_run": now.isoformat(),
        })

        cfg = load_config()
        lines = insights.learned_names_section(cfg)
        check("سطر بالشكل المطلوب حرفيًا",
              "- 📝 وُحّد الرسم: نتانياهو ← نتنياهو (70 مقابل 2)" in lines, lines)
        check("مدخل خارج نافذة الأسبوع لا يظهر", not any("قديم" in ln for ln in lines), lines)
        check("جملة إلغاء التعلّم عبر blocklist مذكورة",
              any("names.blocklist" in ln for ln in lines), lines)

        names_learn.save_learned(
            {"entries": {}, "rejected_pairs": [], "last_run": now.isoformat()})
        empty_lines = insights.learned_names_section(cfg)
        check("لا مدخلات متعلَّمة هذا الأسبوع ⇐ لا قسم إطلاقًا", empty_lines == [], empty_lines)
    finally:
        _clear_names_learn_state()


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

@auto_restore_last_publish
def test_request_writes_request_origin() -> None:
    """مواضع الكتابة السبعة (Issue #749) — request.py يمرّر origin="request"
    عبر extra إلى radar.build_draft، فيُكتب الحقل "request" لا "breaking"
    (القيمة الافتراضية في radar.py نفسها لمساره العاجل)."""
    from src import request as rq

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

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

@auto_restore_last_publish
def test_decisions() -> None:
    """Issue #583 — المرحلة الأولى: سجل قرارات تراكمي (state/decisions.json)،
    جمع بلا أي تحليل أو تأثير على الفرز/الترتيب."""
    from src import decisions

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()
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

    # Issue #954: الرفض الضمني (عُرض على المراجع فلم يُعلَّمه) — قيمة
    # decision منفصلة عن rejected_explicit، بوسم «لم يُعتمد» الثابت دومًا.
    unchecked_draft = dict(published_draft, id="dec_unchecked1")
    decisions.record_rejected_unchecked(unchecked_draft)
    rec3 = next(e for e in decisions.load() if e["id"] == "dec_unchecked1")
    check("الرفض الضمني (مراجعة) يُسجَّل بقرار rejected_unchecked ووسم «لم يُعتمد»",
          rec3["decision"] == "rejected_unchecked" and rec3["reject_tag"] == "لم يُعتمد",
          str(rec3))
    before_dup = len(decisions.load())
    decisions.record_rejected_unchecked(unchecked_draft)
    check("لا تكرار عند تسجيل الرفض الضمني نفسه مرتين",
          len(decisions.load()) == before_dup)

    # Issue #954: مرشح preselect غير مختار — سماته من شكل المرشح لا شكل
    # المسودة (لا arabic ولا source في مرشح لم يُصَغ بعد).
    cand = {
        "id": "dec_cand1", "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending", "score": 2.5, "trend_score": 0.3, "velocity": 0.1,
        "bucket": "light", "state_media": True, "region": "mena",
        "publishers": ["Reuters", "AFP", "AP"],
        "article": {"image_url": "https://x/img.jpg"},
    }
    decisions.record_unselected(cand)
    rec4 = next(e for e in decisions.load() if e["id"] == "dec_cand1")
    check("مرشح غير مختار يُسجَّل بقرار unselected ووسم «لم يُختر»",
          rec4["decision"] == "unselected" and rec4["reject_tag"] == "لم يُختر", str(rec4))
    check("سمات المرشح: bucket/region/state_media/source_count/has_photo من شكل المرشح",
          rec4["bucket"] == "light" and rec4["region"] == "mena"
          and rec4["state_media"] is True and rec4["source_count"] == 3
          and rec4["has_photo"] is True and rec4["category"] == ""
          and rec4["angle"] == "" and rec4["body_len"] == 0
          and rec4["origin"] == "news",
          str(rec4))
    before_dup2 = len(decisions.load())
    decisions.record_unselected(cand)
    check("لا تكرار عند تسجيل نفس المرشح غير المختار مرتين",
          len(decisions.load()) == before_dup2)

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

    # Issue #954: collect.drop_stale_candidates تُسقط مرشحين معلَّقين لم
    # يُربطوا بعد بـIssue اختيار (selection_issue فارغ) — لم يُعرضا على
    # مراجع إطلاقًا، فليسا قرارًا منه، ويجب ألا يُسجَّلا في decisions.json
    # (خلافًا لـfeedback.py الذي يسجّلهما «لم يُختر» لفائدة الفرز الأولي).
    from src import preselect

    decisions_before_stale = len(decisions.load())
    stale_art = Article(
        title="مرشح معلَّق من تشغيلة سابقة", link="https://stale.example/a",
        summary="", source_name="S", region="r", weight=1.0,
        published=datetime.now(timezone.utc), bucket="serious", publisher="S")
    stale_cand = preselect.build_candidate(stale_art)
    store.save_candidate(stale_cand)
    dropped = collect.drop_stale_candidates()
    check("drop_stale_candidates أسقط المرشح المعلَّق فعليًا", dropped == 1, dropped)
    check("drop_stale_candidates لا يضيف قيدًا في decisions.json (لم يُعرض على مراجع)",
          len(decisions.load()) == decisions_before_stale, decisions.load())

@auto_restore_last_publish
def test_decisions_scan_since_ignores_old_batch() -> None:
    """Issue #954: config.yaml: decisions.scan_since يمنع تسجيل الدفعة
    القديمة من المسودات المعلَّقة دفعة واحدة عند أول فحص بعد نشر الميزة —
    مسودة created_at فيها أقدم من scan_since (أو غير قابل للقراءة) تُتخطى
    كليًا، فلا تُسجَّل حتى لو كانت مرتبطة بـIssue مغلق فعلًا. بلا هذا
    المفتاح في cfg، السلوك القديم كما هو (مغطًى في test_decisions أعلاه:
    مسودة قديمة مغلقة تُسجَّل dismissed_closed بلا أي تصفية)."""
    from src import decisions

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()
    if decisions.DECISIONS_FILE.exists():
        decisions.DECISIONS_FILE.unlink()

    since = datetime(2026, 9, 16, tzinfo=timezone.utc)
    before_since = {
        "id": "dec_scan_old", "created_at": (since - timedelta(days=1)).isoformat(),
        "status": "pending", "review_issue": 601, "score": 1.0, "bucket": "serious",
        "source": {}, "arabic": {},
    }
    after_since = {
        "id": "dec_scan_new", "created_at": (since + timedelta(days=1)).isoformat(),
        "status": "pending", "review_issue": 601, "score": 1.0, "bucket": "serious",
        "source": {}, "arabic": {},
    }
    for d in (before_since, after_since):
        store.save_draft(d)

    saved_repo = os.environ.get("GITHUB_REPOSITORY")
    saved_token = os.environ.get("GITHUB_TOKEN")
    os.environ["GITHUB_REPOSITORY"] = "u/r"
    os.environ["GITHUB_TOKEN"] = "tok"

    real_fetch_issue = decisions._fetch_issue
    decisions._fetch_issue = lambda n: {"state": "closed"}

    cfg = load_config()
    cfg["decisions"] = {"ignore_timeout_hours": 48, "scan_since": since.isoformat()}
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

    check("scan سجّل قرارًا واحدًا فقط (اللاحق لـscan_since)", n == 1, n)
    entries = decisions.load()
    check("المسودة الأقدم من scan_since لم تُسجَّل رغم إغلاق الـIssue",
          not any(e["id"] == "dec_scan_old" for e in entries), entries)
    check("المسودة اللاحقة لـscan_since سُجّلت dismissed_closed",
          any(e["id"] == "dec_scan_new" and e["decision"] == "dismissed_closed"
              for e in entries), entries)

@auto_restore_last_publish
def test_decisions_candidate_scan() -> None:
    """Issue #1135: decisions.scan يفحص أيضًا المرشحين المعلَّقين المرتبطين
    بـIssue اختيار، والاختبار على مخرَج الأنبوب: finalize ثم scan بـfakes ثم
    فحص decisions.json وملفات المرشحين — لا الدالة وحدها."""
    import shutil as _sh
    import tempfile
    from src import collect_finalize, decisions, preselect

    backup = Path(tempfile.mkdtemp()) / "cands"
    if store.CANDIDATES_DIR.exists():
        _sh.copytree(store.CANDIDATES_DIR, backup)
    _sh.rmtree(store.CANDIDATES_DIR, ignore_errors=True)
    if decisions.DECISIONS_FILE.exists():
        decisions.DECISIONS_FILE.unlink()

    now = datetime.now(timezone.utc)

    def put(cid, issue, created, folder):
        art = Article(title=f"مرشح {cid}", link=f"https://x.example/{cid}",
                      summary="", source_name="A", region="r", weight=1.0,
                      published=now, bucket="serious", publisher="A")
        cand = preselect.build_candidate(art)
        cand.update(id=cid, created_at=created.isoformat(), selection_issue=issue,
                    publishers=["A", "B"])
        d = store.CANDIDATES_DIR / folder
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{cid}.json"
        path.write_text(json.dumps(cand, ensure_ascii=False), encoding="utf-8")
        return path

    def status(path):
        return json.loads(path.read_text(encoding="utf-8"))["status"]

    def unmarked_body(cid):
        return preselect.build_selection_issue_body([store.load_candidate(cid)[1]])

    recent = now - timedelta(hours=1)
    p_a1 = put("1135a1", 7101, recent, "2026-09-20")
    p_a2 = put("1135a2", 7101, recent, "2026-09-20")
    p_b = put("1135b0", 7102, recent, "2026-09-20")
    p_c1 = put("1135c1", 7103, now - timedelta(hours=100), "2026-09-20")
    p_c2 = put("1135c2", 7104, recent, "2026-09-20")
    p_d = put("1135d0", 7105, now - timedelta(days=20), "2026-09-20")
    # المعرّف نفسه في Issueين: الأقدم في مجلد أقدم — التحميل القديم (أقدم
    # نسخة) كان سيحدّث ملف 7106 بدل ملف 7107
    p_e1 = put("1135e0", 7106, recent, "2026-09-20")
    p_e2 = put("1135e0", 7107, recent, "2026-09-25")
    p_f = put("1135f0", 7108, recent, "2026-09-25")
    p_g = put("1135e9", 7109, recent, "2026-09-25")

    # g: قيد قديم بلا selection_issue للمعرّف نفسه
    decisions.save([{"id": "1135e9", "decision": "unselected",
                     "reject_tag": "لم يُختر", "created_at": "", "decided_at": ""}])

    # المرور بـfinalize الحقيقي (لا شيء مختار ⇒ كل المعروضين غير مختارين)
    # تعليقات Issue ووسومه خارج موضوع الاختبار (شبكة) — تُستبدل مؤقتًا
    from src import review as _review
    real_comment, real_remove = _review.comment, _review.remove_label
    _review.comment = lambda *a, **k: None
    _review.remove_label = lambda *a, **k: None
    try:
        code_e = collect_finalize.finalize(7107, unmarked_body("1135e0"), load_config())
        collect_finalize.finalize(7108, unmarked_body("1135f0"), load_config())
    finally:
        _review.comment, _review.remove_label = real_comment, real_remove
    check("finalize لـ e في Issue 7107 نجح", code_e == 0)
    check("finalize حدّث نسخة Issue 7107 لا أقدم نسخة",
          status(p_e2) == "unselected" and status(p_e1) == "pending",
          (status(p_e2), status(p_e1)))
    # f: نُشر الخبر نفسه بعد أن لم يُختر
    decisions.record_published({"id": "1135f0", "created_at": recent.isoformat(),
                                "status": "pending", "source": {}, "arabic": {}})

    calls: list[int] = []

    def fake_fetch(n):
        calls.append(n)
        closed = {7101, 7102, 7105, 7106, 7109}
        labels = [{"name": "approved"}] if n == 7102 else []
        return {"state": "closed" if n in closed else "open", "labels": labels}

    saved_env = {k: os.environ.get(k) for k in ("GITHUB_REPOSITORY", "GITHUB_TOKEN")}
    os.environ["GITHUB_REPOSITORY"] = "u/r"
    os.environ["GITHUB_TOKEN"] = "tok"
    real_fetch = decisions._fetch_issue
    decisions._fetch_issue = fake_fetch
    cfg = load_config()
    cfg["decisions"] = {"ignore_timeout_hours": 48,
                        "scan_since": (now - timedelta(days=10)).isoformat()}
    try:
        n1 = decisions.scan(cfg)
        entries1 = decisions.load()
        calls_first = list(calls)
        n2 = decisions.scan(cfg)
        entries2 = decisions.load()
    finally:
        decisions._fetch_issue = real_fetch
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def dec(cid, issue=None):
        return [e for e in entries1 if e["id"] == cid
                and (issue is None or e.get("selection_issue") == issue)]

    check("a: Issue مغلق بلا approved ← dismissed_closed (ملف المرشح أيضًا)",
          [e["decision"] for e in dec("1135a1")] == ["dismissed_closed"]
          and status(p_a1) == "dismissed_closed", dec("1135a1"))
    check("b: Issue مغلق مع approved ← unselected بوسم «لم يُختر»",
          [(e["decision"], e["reject_tag"]) for e in dec("1135b0")]
          == [("unselected", "لم يُختر")] and status(p_b) == "unselected",
          dec("1135b0"))
    check("c: Issue مفتوح بعد المهلة ← ignored_timeout",
          [e["decision"] for e in dec("1135c1")] == ["ignored_timeout"]
          and status(p_c1) == "ignored_timeout", dec("1135c1"))
    check("c: Issue مفتوح قبل المهلة ← لا شيء والمرشح يبقى pending",
          not dec("1135c2") and status(p_c2) == "pending")
    check("d: مرشح أقدم من scan_since ← لا شيء",
          not dec("1135d0") and status(p_d) == "pending")
    check("قيد المرشح يحمل selection_issue وسمات المرشح",
          dec("1135a1")[0]["selection_issue"] == 7101
          and dec("1135a1")[0]["bucket"] == "serious"
          and dec("1135a1")[0]["source_count"] == 2, dec("1135a1"))
    e_entries = dec("1135e0")
    check("e: قيدان للمعرّف نفسه بـselection_issue مختلفين (7106 و7107)",
          sorted(e.get("selection_issue") for e in e_entries) == [7106, 7107],
          e_entries)
    check("e: نسخة Issue الأول حُسمت dismissed_closed بعد scan",
          status(p_e1) == "dismissed_closed", status(p_e1))
    f_entries = dec("1135f0")
    check("f: unselected ثم published كلاهما موجود",
          sorted(e["decision"] for e in f_entries) == ["published", "unselected"],
          f_entries)
    check("g: قيد قديم بلا selection_issue ← لا استكمال رجعي",
          len(dec("1135e9")) == 1 and "selection_issue" not in dec("1135e9")[0]
          and status(p_g) == "pending", dec("1135e9"))
    check("h: طلب API واحد لكل Issue لا لكل مرشح",
          sorted(calls_first) == [7101, 7102, 7103, 7104, 7106],
          calls_first)
    check("scan الأول سجّل خمسة قرارات (a1/a2/b/c1 وe في Issue 7106)",
          n1 == 5, n1)
    check("i: scan ثانٍ لا يضيف قيودًا مكرَّرة", n2 == 0 and len(entries2) == len(entries1),
          (n2, len(entries2), len(entries1)))
    pairs = [(e["id"], e.get("selection_issue"), e["decision"]) for e in entries2]
    check("i: لا زوج (id، selection_issue، decision) مكرَّر",
          len(pairs) == len(set(pairs)), pairs)

    # record_published يمنعه published سابق فقط
    before = len(decisions.load())
    decisions.record_published({"id": "1135f0", "created_at": "", "source": {},
                                "arabic": {}})
    check("record_published لا يكرّر published للمعرّف نفسه",
          len(decisions.load()) == before)

    _sh.rmtree(store.CANDIDATES_DIR, ignore_errors=True)
    if backup.exists():
        _sh.copytree(backup, store.CANDIDATES_DIR)
    if decisions.DECISIONS_FILE.exists():
        decisions.DECISIONS_FILE.unlink()


def test_store_load_candidate_prefers_selection_issue() -> None:
    """Issue #1135: load_candidate يفضّل نسخة Issue الاختيار المطلوب، ويبقى
    السلوك القديم (أقدم نسخة) حين لا يُمرَّر المعامل أو لا تطابق نسخة."""
    import shutil as _sh
    _sh.rmtree(store.CANDIDATES_DIR / "2026-01-01", ignore_errors=True)
    _sh.rmtree(store.CANDIDATES_DIR / "2026-01-02", ignore_errors=True)
    for folder, issue in (("2026-01-01", 1), ("2026-01-02", 2)):
        d = store.CANDIDATES_DIR / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / "lc1135.json").write_text(
            json.dumps({"id": "lc1135", "selection_issue": issue}), encoding="utf-8")
    try:
        check("بلا معامل ← أقدم نسخة (السلوك القديم)",
              store.load_candidate("lc1135")[1]["selection_issue"] == 1)
        check("بمعامل ← النسخة المطابقة",
              store.load_candidate("lc1135", 2)[1]["selection_issue"] == 2)
        check("معامل بلا مطابقة ← أقدم نسخة",
              store.load_candidate("lc1135", 99)[1]["selection_issue"] == 1)
        check("معرّف غير موجود ← None", store.load_candidate("nope1135", 2) is None)
    finally:
        _sh.rmtree(store.CANDIDATES_DIR / "2026-01-01", ignore_errors=True)
        _sh.rmtree(store.CANDIDATES_DIR / "2026-01-02", ignore_errors=True)


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

@auto_restore_last_publish
def test_insights_collect_includes_analysis_origin() -> None:
    """Issue #749: insights.collect لا يستثني مسار التحليل (هو نفسه تحليلي،
    واستبعاده يُعمي التقرير الأسبوعي عن مسار يجري توسيعه)، ولا ينهار على
    مسودة بلا حقل image — لا شيء في collect() يقرأ draft["image"] مباشرة،
    فتُعامَل مسودة تحليل بلا هذا الحقل كأي مسودة أخرى بلا أي حراسة إضافية."""
    from src import insights

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

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

@auto_restore_last_publish
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
    reset_last_publish()

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


@auto_restore_last_publish
def test_retention_sweep_ages_and_statuses() -> None:
    """Issue #956: src/retention.py يحذف من drafts/ وstate/candidates/ ما
    تجاوز نافذة retention.days، بقاعدة عمر مختلفة بحسب حالة المسودة —
    يُختبَر على مخرَج الأنبوب (ملفات فعلية على القرص بعد استدعاء
    retention.main() كما يُستدعى من سطر الأوامر)، لا على دالة السحب وحدها.
    --dry-run يُختبَر أولًا على نفس التجهيزة كاملةً (لا يحذف شيئًا)، ثم
    الحذف الحقيقي على التجهيزة ذاتها بعده مباشرة."""
    from src import retention

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()
    shutil.rmtree(store.CANDIDATES_DIR, ignore_errors=True)

    now = datetime.now(timezone.utc)

    def draft_folder(days_ago: int) -> Path:
        folder = store.draft_dir(now - timedelta(days=days_ago))
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def write_draft(folder: Path, draft_id: str, **fields) -> None:
        data = {"id": draft_id, **fields}
        (folder / f"{draft_id}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def write_image(folder: Path, draft_id: str) -> None:
        (folder / f"{draft_id}.jpg").write_bytes(b"\xff\xd8\xff")

    # ① منشورة، مجلدها قبل 31 يومًا، وpublished_at قبل 29 يومًا ← تبقى
    # (العمر يُقاس من published_at لا من تاريخ المجلد لهذه الحالة وحدها).
    f1 = draft_folder(31)
    write_draft(f1, "kept_pub_recent", status="published",
               published_at=(now - timedelta(days=29)).isoformat())
    write_image(f1, "kept_pub_recent")

    # ② منشورة، published_at قبل 31 يومًا ← تُحذف مع صورتها.
    f2 = draft_folder(33)
    write_draft(f2, "del_pub_old", status="published",
               published_at=(now - timedelta(days=31)).isoformat())
    write_image(f2, "del_pub_old")

    # ③ queued، مجلدها قبل 40 يومًا ← تبقى مهما كان عمرها (لا تُحذف أبدًا).
    f3 = draft_folder(40)
    write_draft(f3, "kept_queued", status="queued",
               publish_at=(now + timedelta(hours=2)).isoformat())
    write_image(f3, "kept_queued")

    # ④ pending وfailed وrejected، مجلدها قبل 31 يومًا ← تُحذف جميعًا (العمر
    # من تاريخ المجلد لكل حالة غير published/queued).
    f4 = draft_folder(34)
    write_draft(f4, "del_pending", status="pending")
    write_draft(f4, "del_failed", status="failed", error="خطأ ما")
    write_draft(f4, "del_rejected", status="rejected")
    for did in ("del_pending", "del_failed", "del_rejected"):
        write_image(f4, did)

    # ⑤ pending، مجلدها قبل 29 يومًا ← تبقى.
    f5 = draft_folder(29)
    write_draft(f5, "kept_pending_recent", status="pending")

    # ⑥ JSON تالف في مجلد قديم ← يبقى بلا حذف، ويُسجَّل تحذير.
    f6 = draft_folder(36)
    (f6 / "corrupt.json").write_text("{هذا ليس JSON صالحًا", encoding="utf-8")

    # ⑧ مجلد يصير فارغًا تمامًا بعد حذف مسودته الوحيدة ← المجلد نفسه يُحذف.
    f8 = draft_folder(32)
    write_draft(f8, "del_alone", status="pending")

    # ⑦ مرشحو preselect: مجلد قبل 31 يومًا يُحذف بكامله، وآخر قبل 29 يومًا يبقى.
    cand_old = store.candidate_dir(now - timedelta(days=31))
    cand_old.mkdir(parents=True, exist_ok=True)
    (cand_old / "cand_old.json").write_text(
        json.dumps({"id": "cand_old"}, ensure_ascii=False), encoding="utf-8")
    cand_recent = store.candidate_dir(now - timedelta(days=29))
    cand_recent.mkdir(parents=True, exist_ok=True)
    (cand_recent / "cand_recent.json").write_text(
        json.dumps({"id": "cand_recent"}, ensure_ascii=False), encoding="utf-8")

    # ── --dry-run على التجهيزة كاملة: لا شيء يُحذف فعليًا ──
    dry_code = retention.main(["--dry-run"])
    check("retention.main --dry-run ينتهي بنجاح", dry_code == 0, f"exit={dry_code}")
    all_paths = [
        f1 / "kept_pub_recent.json", f1 / "kept_pub_recent.jpg",
        f2 / "del_pub_old.json", f2 / "del_pub_old.jpg",
        f3 / "kept_queued.json", f3 / "kept_queued.jpg",
        f4 / "del_pending.json", f4 / "del_failed.json", f4 / "del_rejected.json",
        f5 / "kept_pending_recent.json", f6 / "corrupt.json",
        f8 / "del_alone.json", cand_old / "cand_old.json",
        cand_recent / "cand_recent.json",
    ]
    check("--dry-run لا يحذف أي ملف من التجهيزة كاملةً",
          all(p.exists() for p in all_paths),
          [str(p) for p in all_paths if not p.exists()])
    check("--dry-run لا يحذف مجلد المرشحين القديم أيضًا", cand_old.exists())

    # ── الحذف الحقيقي على نفس التجهيزة ──
    code = retention.main([])
    check("retention.main الحقيقي ينتهي بنجاح", code == 0, f"exit={code}")

    check("① منشورة حديثة العمر (من published_at) رغم قدم مجلدها ← باقية",
          (f1 / "kept_pub_recent.json").exists())
    check("① صورتها باقية أيضًا", (f1 / "kept_pub_recent.jpg").exists())

    check("② منشورة قديمة العمر (من published_at) ← حُذفت",
          not (f2 / "del_pub_old.json").exists())
    check("② صورتها حُذفت معها", not (f2 / "del_pub_old.jpg").exists())

    check("③ queued تبقى مهما بلغ عمر مجلدها",
          (f3 / "kept_queued.json").exists() and (f3 / "kept_queued.jpg").exists())

    check("④ pending/failed/rejected قديمة (عمر مجلد) ← حُذفت جميعًا",
          not any((f4 / f"{did}.json").exists()
                  for did in ("del_pending", "del_failed", "del_rejected")))
    check("④ صورها حُذفت معها",
          not any((f4 / f"{did}.jpg").exists()
                  for did in ("del_pending", "del_failed", "del_rejected")))

    check("⑤ pending حديثة العمر (مجلد) ← باقية",
          (f5 / "kept_pending_recent.json").exists())

    check("⑥ JSON تالف في مجلد قديم ← يبقى بلا حذف", (f6 / "corrupt.json").exists())

    check("⑧ مجلد يوم صار فارغًا تمامًا بعد حذف مسودته الوحيدة ← حُذف هو نفسه",
          not f8.exists())

    check("⑦ مجلد مرشحين أقدم من النافذة ← يُحذف بكامله", not cand_old.exists())
    check("⑦ مجلد مرشحين أحدث من النافذة ← يبقى", cand_recent.exists())


@auto_restore_last_publish
def test_retention_publish_survives_deleted_draft() -> None:
    """publish.main لا ينهار حين يشير Issue معتمَد إلى معرّف مسودة حذفتها
    retention.py بالفعل — كل نداء store.load_draft على طول المسار العام
    (المسار الوحيد الذي يبلغه Issue بوسم approved بلا وسوم خاصة) يتحقق من
    ``found`` قبل استعماله فيتخطّى المعرّف المفقود بصمت بدل الانهيار."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    body = "- [x] **1. مسودة حُذفت سلفًا**  <!-- draft:already_gone_00001 -->"

    real_fetch = publish_mod.fetch_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body, "labels": [{"name": "approved"}],
    }
    real_comment = review.comment
    real_close = review.close_issue
    real_remove_label = review.remove_label
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: None
    review.remove_label = lambda issue_number, label: None

    sys.argv = ["publish", "--issue", "9500"]
    try:
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        review.comment = real_comment
        review.close_issue = real_close
        review.remove_label = real_remove_label

    check("publish.main لا ينهار حين يشير Issue معتمَد إلى مسودة محذوفة سلفًا",
          code == 0, f"exit={code}")


@auto_restore_last_publish
def test_retention_insights_still_counts_kept_draft() -> None:
    """بعد تشغيلة حذف حقيقية، insights.collect(30, …) يظل يحسب مسودة
    منشورة لم تتجاوز نافذة الاحتفاظ بعد — الحذف الدوري لا يقتطع من نافذة
    تقرير الأداء الأسبوعي نفسها (كلتاهما 30 يومًا بالضبط عمدًا)."""
    from src import insights
    from src import retention

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    now = datetime.now(timezone.utc)
    folder = store.draft_dir(now - timedelta(days=31))
    folder.mkdir(parents=True, exist_ok=True)
    draft = {
        "id": "ins_kept", "status": "published",
        "published_at": (now - timedelta(days=29)).isoformat(),
        "arabic": {"post_title": "خبر باقٍ", "urgent": False},
        "facebook": {"post_id": "42"},
    }
    (folder / "ins_kept.json").write_text(
        json.dumps(draft, ensure_ascii=False), encoding="utf-8")

    code = retention.main([])
    check("retention.main ينتهي بنجاح قبل فحص insights", code == 0, f"exit={code}")
    check("المسودة الباقية لم تُحذف فعلًا (شرط مسبق للفحص التالي)",
          (folder / "ins_kept.json").exists())

    real_fetch_metrics = facebook.fetch_metrics
    facebook.fetch_metrics = lambda post_id, api_version: {
        "reactions": 1, "comments": 0, "shares": 0}
    try:
        rows = insights.collect(30, "v21.0")
    finally:
        facebook.fetch_metrics = real_fetch_metrics

    check("insights.collect(30) ما زال يحسب المسودة الباقية بعد الحذف الدوري",
          any(r["id"] == "ins_kept" for r in rows), rows)


def test_retention_config_days_at_least_30() -> None:
    """التقرير الأسبوعي (insights.py، عبر insights.yml) يقرأ افتراضيًا آخر
    30 يومًا من المنشورات — نافذة الاحتفاظ يجب ألا تقلّ عن ذلك، وإلا حذفت
    مسودات منشورة ما زال التقرير الأسبوعي بحاجة إليها قبل أن يقرأها."""
    cfg = load_config()
    days = cfg.path("retention.days")
    check("retention.days معرَّف في config.yaml", days is not None, days)
    check("retention.days ≥ 30 (نافذة تقرير الأداء الأسبوعي)",
          isinstance(days, int) and days >= 30, days)


# ──────────────────────── إحياء منشورات فشل نشرها (Issue #959) ────────────


def _revival_env(repo: str = "u/r", ref: str = "main"):
    """يضبط GITHUB_REPOSITORY/GITHUB_REF_NAME مؤقتًا ويعيد دالة استعادة —
    نفس النمط المكرّر في بقية اختبارات open_review في هذا الملف."""
    real_repo = os.environ.get("GITHUB_REPOSITORY")
    real_ref = os.environ.get("GITHUB_REF_NAME")
    os.environ["GITHUB_REPOSITORY"] = repo
    os.environ["GITHUB_REF_NAME"] = ref

    def restore():
        if real_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo
        if real_ref is None:
            os.environ.pop("GITHUB_REF_NAME", None)
        else:
            os.environ["GITHUB_REF_NAME"] = real_ref

    return restore


@auto_restore_last_publish
def test_publish_one_facebook_failure_tags_stage() -> None:
    """Issue #959 جزء أ: فشل facebook.FacebookError عند نشر الصورة تحديدًا
    (لا «حقول مفقودة» ولا «الصورة مفقودة») هو الفشل الوحيد الذي يُعلَّم
    بـfailed_stage="facebook" وfailed_at — الحقل الذي يجعل
    open_review._revivable_drafts تعتبر المسودة قابلة للإحياء لاحقًا."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    draft = {
        "id": "fb_fail_0001", "status": "pending",
        "arabic": {"post_title": "خبر فشل نشره على فيسبوك", "urgent": False},
        "caption": "متن", "source": {}, "image": "drafts/fb_fail.jpg",
    }
    path = store.save_draft(draft)
    (DRAFTS_DIR / "fb_fail.jpg").write_bytes(b"\xff\xd8\xff")

    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    publish_mod.ROOT = DRAFTS_DIR.parent
    before = datetime.now(timezone.utc)

    def raise_fb(*a, **k):
        raise facebook.FacebookError("خطأ فيسبوك: (#1) الخدمة غير متاحة")

    facebook.publish_photo = raise_fb
    try:
        ok, line = publish_mod.publish_one(path, draft, load_config())
    finally:
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo

    check("publish_one يعيد فشلًا عند FacebookError", not ok, line)
    updated = store.load_draft(draft["id"])[1]
    check("الحالة failed", updated.get("status") == "failed", updated.get("status"))
    check("failed_stage=facebook", updated.get("failed_stage") == "facebook",
          updated.get("failed_stage"))
    failed_at = updated.get("failed_at")
    check("failed_at مكتوب وقابل للتحليل", bool(failed_at), failed_at)
    if failed_at:
        parsed = datetime.fromisoformat(failed_at)
        check("failed_at بتوقيت UTC قريب من لحظة الفشل",
              abs((parsed - before).total_seconds()) < 30, failed_at)

    # «الصورة مفقودة» لا يحمل failed_stage — لها طريق /صورة القائم أصلًا.
    draft2 = {
        "id": "img_missing0001", "status": "pending",
        "arabic": {"post_title": "خبر بلا صورة على القرص", "urgent": False},
        "caption": "متن", "source": {}, "image": "drafts/does-not-exist.jpg",
    }
    path2 = store.save_draft(draft2)
    publish_mod.ROOT = DRAFTS_DIR.parent
    try:
        ok2, _ = publish_mod.publish_one(path2, draft2, load_config())
    finally:
        publish_mod.ROOT = real_root
    updated2 = store.load_draft(draft2["id"])[1]
    check("«الصورة مفقودة» أيضًا failed", not ok2 and updated2.get("status") == "failed",
          updated2.get("status"))
    check("«الصورة مفقودة» بلا failed_stage", "failed_stage" not in updated2, updated2)


def test_publish_gap_gate_core_scenarios() -> None:
    """Issue #1010: بوابة الفاصل الواحدة داخل publish_one — عبر الدالة
    الحقيقية مباشرة (لا معزولة) في أربع حالات: بلا منشور سابق تُنشر فورًا،
    عاجل يتجاوز البوابة دومًا مهما قرُب آخر منشور، وغير عاجل يُنشر فورًا إن
    مرّ على آخر منشور أكثر من gap_min أو يُؤجَّل إن مرّ أقل. التأجيل ليس
    فشلًا: لا failed، ولا failed_stage، ولا error، ولا قيد رفض في
    decisions، ولا يدخل failed_drafts (فلا يفتح له open_review Issue إحياء
    — تلك تفحص failed_stage=='facebook' حصرًا)."""
    from src import decisions
    from src import publish as publish_mod

    # Issue #1015: المصدر أصبح published_at في drafts/ نفسها لا ملف حالة،
    # فلا سبيل لـ«تجميد» زمن نشر فعلي عبر استدعاء واحد — كل سيناريو يمحو
    # drafts/ أولًا (بلا هذا يبقى منشور سيناريو سابق الأحدث فعليًا فيفوز في
    # حساب last_publish_at الحقيقي على القيمة المصطنعة عبر stub_last_publish
    # أدناه)، ثم يثبّت المسودة المنشورة الوحيدة التي يريد قياس البوابة تجاهها.
    restore_last_publish()

    cfg = load_config()
    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    publish_mod.ROOT = DRAFTS_DIR.parent
    facebook.publish_photo = lambda *a, **k: {"url": "https://fb.example/gate", "id": "1"}

    def reset_drafts_dir() -> None:
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        (DRAFTS_DIR / "gate.jpg").write_bytes(b"\xff\xd8\xff")

    def make(did: str, urgent: bool):
        d = {
            "id": did, "status": "pending",
            "arabic": {"post_title": f"خبر {did}", "urgent": urgent},
            "image": "drafts/gate.jpg", "caption": "متن", "source": {},
        }
        return store.save_draft(d), d

    try:
        # 1) لا منشور سابق ⇒ مسودة عادية تُنشر فورًا
        reset_drafts_dir()
        path1, draft1 = make("gate_none", False)
        ok1, line1 = publish_mod.publish_one(path1, draft1, cfg)
        check("لا منشور سابق: مسودة عادية تُنشر فورًا", ok1, line1)
        check("حالتها published بعد ذلك",
              store.load_draft("gate_none")[1].get("status") == "published")
        check("لا ملف حالة last_publish.json — المصدر published_at وحده",
              not (STATE_DIR / "last_publish.json").exists())

        # 2) آخر منشور قبل 5 دقائق (أقل من gap_min=30) ⇒ queued لا published
        reset_drafts_dir()
        last5 = datetime.now(timezone.utc) - timedelta(minutes=5)
        stub_last_publish(last5)
        path2, draft2 = make("gate_5min", False)
        ok2, line2 = publish_mod.publish_one(path2, draft2, cfg)
        check("آخر منشور قبل 5 دقائق: لا تُنشر مسودة عادية", not ok2, line2)
        updated2 = store.load_draft("gate_5min")[1]
        check("تصير queued", updated2.get("status") == "queued", updated2.get("status"))
        pub_at = updated2.get("publish_at")
        check("publish_at محفوظ", bool(pub_at), updated2)
        if pub_at:
            when = datetime.fromisoformat(pub_at)
            delta_min = (when - last5).total_seconds() / 60
            check("الموعد الجديد بين 30 و60 دقيقة بعد آخر منشور فعلي",
                  30 <= delta_min <= 60, delta_min)
        check("التأجيل ليس فشلًا: لا status=failed", updated2.get("status") != "failed",
              updated2)
        check("التأجيل ليس فشلًا: بلا failed_stage", "failed_stage" not in updated2, updated2)
        check("التأجيل ليس فشلًا: بلا error", "error" not in updated2, updated2)
        check("المؤجَّلة لا تدخل failed_drafts (فلا Issue إحياء لها)",
              all(d.get("id") != "gate_5min" for _, d in store.failed_drafts()),
              [d.get("id") for _, d in store.failed_drafts()])
        deciding_entries = [e for e in decisions.load() if e.get("id") == "gate_5min"]
        check("المؤجَّلة لا تُسجَّل مرفوضة في decisions", deciding_entries == [],
              deciding_entries)

        # 3) عاجل قبل دقيقة واحدة فقط ⇒ يتجاوز البوابة وينشر فورًا رغم ذلك
        reset_drafts_dir()
        stub_last_publish(datetime.now(timezone.utc) - timedelta(minutes=1))
        path3, draft3 = make("gate_urgent", True)
        ok3, line3 = publish_mod.publish_one(path3, draft3, cfg)
        check("عاجل قبل دقيقة: يتجاوز البوابة وينشر فورًا", ok3, line3)
        check("حالتها published", store.load_draft("gate_urgent")[1].get("status") == "published")

        # 4) آخر منشور قبل 45 دقيقة (أكثر من gap_min=30) ⇒ فورًا
        reset_drafts_dir()
        stub_last_publish(datetime.now(timezone.utc) - timedelta(minutes=45))
        path4, draft4 = make("gate_45min", False)
        ok4, line4 = publish_mod.publish_one(path4, draft4, cfg)
        check("آخر منشور قبل 45 دقيقة: مسودة عادية تُنشر فورًا", ok4, line4)
        check("حالتها published", store.load_draft("gate_45min")[1].get("status") == "published")
        check("بعد نشر ناجح لا يوجد أي ملف state/last_publish.json",
              not (STATE_DIR / "last_publish.json").exists())
    finally:
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo


def test_publish_ids_direct_defers_non_urgent_after_recent_publish() -> None:
    """Issue #1008 (لم يُصلَح هناك) + #1010: مسار النشر المباشر بالمعرّفات
    (``publish --ids`` ← ``cmd_now``، ``issue_number=None``) كان ينشر
    مسودة غير عاجلة فورًا بلا أي فاصل، متجاوزًا فاصل النشر الذي يطبّقه
    ``cmd_burst``/``cmd_schedule`` عبر Issue مراجعة. الآن البوابة داخل
    ``publish_one`` نفسها تحرس هذا المسار أيضًا — لا حاجة لأي تعديل على
    ``cmd_now``."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    restore_last_publish()

    stub_last_publish(datetime.now(timezone.utc) - timedelta(minutes=2))

    draft = {
        "id": "ids_direct_0001", "status": "pending",
        "arabic": {"post_title": "خبر عبر --ids مباشرة", "urgent": False},
        "image": "drafts/ids.jpg", "caption": "متن", "source": {},
    }
    store.save_draft(draft)
    (DRAFTS_DIR / "ids.jpg").write_bytes(b"\xff\xd8\xff")

    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    publish_mod.ROOT = DRAFTS_DIR.parent
    publish_calls: list = []
    facebook.publish_photo = lambda *a, **k: (publish_calls.append(1),
                                              {"url": "#", "id": "1"})[1]
    try:
        code = publish_mod.cmd_now(["ids_direct_0001"], load_config(), None)
    finally:
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo

    check("cmd_now (--ids) ينتهي بنجاح", code == 0, f"exit={code}")
    check("لا نداء فعلي لفيسبوك — البوابة أجّلت قبل الوصول للشبكة",
          publish_calls == [], publish_calls)
    updated = store.load_draft("ids_direct_0001")[1]
    check("--ids لمسودة غير عاجلة بعد منشور حديث: تصير مجدولة لا منشورة",
          updated.get("status") == "queued", updated.get("status"))


def test_due_captures_gap_gate_deferred_draft_on_later_run() -> None:
    """Issue #1010: مسودة أجّلتها البوابة (queued بموعد مستقبلي) يلتقطها
    ``cmd_due`` في تشغيلة لاحقة حين يحين موعدها فعلًا — تمامًا كأي مسودة
    queued عادية أخرى، بلا أي منطق خاص إضافي في cmd_due نفسها."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    restore_last_publish()

    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    publish_mod.ROOT = DRAFTS_DIR.parent
    (DRAFTS_DIR / "due_gate.jpg").write_bytes(b"\xff\xd8\xff")
    facebook.publish_photo = lambda *a, **k: {"url": "https://fb.example/dg", "id": "1"}

    draft = {
        "id": "due_gate_0001", "status": "pending",
        "arabic": {"post_title": "خبر يؤجَّل بالبوابة", "urgent": False},
        "image": "drafts/due_gate.jpg", "caption": "متن", "source": {},
    }
    path = store.save_draft(draft)

    try:
        # يؤجَّل أولًا لأن منشورًا آخر خرج قبل لحظات (أقل من gap_min) —
        # stub_last_publish تُعيد كتابة مسودة published واحدة بمعرّف ثابت،
        # فاستدعاؤها ثانية أدناه يستبدل هذا الموعد لا يضيف إليه.
        stub_last_publish(datetime.now(timezone.utc) - timedelta(minutes=1))
        ok, _ = publish_mod.publish_one(path, draft, load_config())
        check("أُجِّلت أولًا (وقت غير مناسب بعد)", not ok)
        deferred = store.load_draft("due_gate_0001")[1]
        check("صارت queued بموعد مستقبلي", deferred.get("status") == "queued",
              deferred.get("status"))

        # محاكاة تقدّم الساعة: موعدها صار في الماضي (مستحق)، وآخر منشور فعلي
        # صار بعيدًا كفاية — لا حاجة لمحاكاة datetime.now نفسها، فقط الحالتان
        # اللتان تقرأهما البوابة وcmd_due فعليًا.
        store.update_draft(
            path, publish_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
        stub_last_publish(datetime.now(timezone.utc) - timedelta(minutes=40))

        code = publish_mod.cmd_due(load_config())
        check("cmd_due ينتهي بنجاح", code == 0, f"exit={code}")
        published = store.load_draft("due_gate_0001")[1]
        check("cmd_due نشرها فعليًا في التشغيلة اللاحقة", published.get("status") == "published",
              published.get("status"))
    finally:
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo


@auto_restore_last_publish
def test_queued_drafts_includes_gap_deferred_analysis_and_guards_missing_image() -> None:
    """Issue #1010: ``queued_drafts`` لم يعد يستثني أصل ``analysis`` بإطلاق
    — مسودة تحليل أجّلتها البوابة (``youtube_publish.publish_ids`` يبني
    البطاقة عبر ``ensure_title_card`` قبل أي محاولة نشر، فحقل ``image``
    موجود دومًا حين التأجيل طبيعي) تدخل الطابور العام ويلتقطها ``cmd_due``
    مثل أي مسودة أخرى، مسودةً واحدة في كل تشغيلة. مسودة تحليل queued بلا
    ``image`` (عطب بنيوي لا تأجيل طبيعي) تبقى مستبعدة كما كانت — الحارس
    القديم أُبقي بشرط إضافي بدل حذفه بالكامل."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    now = datetime.now(timezone.utc)
    with_image = {
        "id": "an_queued_ok01", "status": "queued", "origin": "analysis",
        "publish_at": (now - timedelta(minutes=1)).isoformat(),
        "arabic": {"post_title": "تحليل مؤجَّل بالبوابة", "urgent": False},
        "image": "drafts/an_ok.jpg", "caption": "متن", "source": {},
    }
    without_image = {
        "id": "an_queued_bad01", "status": "queued", "origin": "analysis",
        "publish_at": (now - timedelta(minutes=1)).isoformat(),
        "arabic": {"post_title": "تحليل متسرّب بلا بطاقة", "urgent": False},
        "caption": "متن", "source": {},
    }
    store.save_draft(with_image)
    store.save_draft(without_image)

    rows = publish_mod.queued_drafts()
    ids = {d["id"] for _, d in rows}
    check("مسودة تحليل مؤجَّلة (ببطاقة) تدخل الطابور العام",
          "an_queued_ok01" in ids, ids)
    check("مسودة تحليل بلا بطاقة تبقى مستبعدة (عطب بنيوي)",
          "an_queued_bad01" not in ids, ids)

    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    publish_mod.ROOT = DRAFTS_DIR.parent
    (DRAFTS_DIR / "an_ok.jpg").write_bytes(b"\xff\xd8\xff")
    facebook.publish_photo = lambda *a, **k: {"url": "https://fb.example/an", "id": "1"}
    try:
        code = publish_mod.cmd_due(load_config())
    finally:
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo

    check("cmd_due ينتهي بنجاح", code == 0, f"exit={code}")
    check("cmd_due ينشر مسودة التحليل المؤجَّلة مثل أي مسودة queued أخرى",
          store.load_draft("an_queued_ok01")[1].get("status") == "published",
          store.load_draft("an_queued_ok01")[1].get("status"))
    check("المسودة المعطوبة (بلا بطاقة) لم تُلمَس",
          store.load_draft("an_queued_bad01")[1].get("status") == "queued",
          store.load_draft("an_queued_bad01")[1].get("status"))


@auto_restore_last_publish
def test_open_review_revival_issue_single_and_no_duplicate() -> None:
    """Issue #959 جزء ب: open_review.main يجمع مسودات failed القابلة
    للإحياء (فشل فيسبوك فقط، بلا revival_issue، revival_offers < 2) في
    Issue واحد مستقل — لا فشل الصورة، ولا فشل الحقول (عطب بنيوي)، ولا فشل
    قديم بلا failed_stage، ولا ما عُرض مرتين بالفعل. تشغيل ثانٍ لا يفتح
    Issue جديدًا لنفس المسودة."""
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    now_iso = datetime.now(timezone.utc).isoformat()

    def make(did: str, **extra) -> dict:
        d = {
            "id": did, "status": "failed",
            "arabic": {"post_title": f"مسودة {did}", "urgent": False},
            "caption": "متن", "source": {}, "image": f"drafts/{did}.jpg",
        }
        d.update(extra)
        return d

    fb_fail = make("facebbb0001", failed_stage="facebook", failed_at=now_iso,
                    error="خطأ فيسبوك: (#1) الخدمة غير متاحة")
    img_fail = make("facebbb0002", error="الصورة مفقودة")
    fields_fail = make("facebbb0003", error="حقول مفقودة: image")
    old_fail = make("facebbb0004", error="خطأ قديم من قبل هذه الميزة")
    twice_fail = make("facebbb0005", failed_stage="facebook", failed_at=now_iso,
                       error="خطأ فيسبوك تكرر", revival_offers=2)
    for d in (fb_fail, img_fail, fields_fail, old_fail, twice_fail):
        store.save_draft(d)

    create_issue_calls: list = []

    def fake_create_issue(title, body, labels=None):
        create_issue_calls.append({"title": title, "body": body, "labels": labels})
        return {"number": 9200, "html_url": "https://github.com/u/r/issues/9200"}

    real_create_issue = review.create_issue
    real_ensure_labels = review.ensure_labels
    review.create_issue = fake_create_issue
    review.ensure_labels = lambda: None
    restore_env = _revival_env()
    try:
        code = open_review.main()
        check("open_review.main ينتهي بنجاح", code == 0, f"exit={code}")
        check("Issue إحياء واحد فُتح", len(create_issue_calls) == 1,
              str(len(create_issue_calls)))
        call = create_issue_calls[0] if create_issue_calls else {}
        check("وسم failed-review", call.get("labels") == ["failed-review"],
              call.get("labels"))
        body = call.get("body", "")
        check("المسودة القابلة للإحياء وحدها ظاهرة في الجسم",
              set(review.all_revival_ids(body)) == {fb_fail["id"]},
              review.all_revival_ids(body))

        updated_fb = store.load_draft(fb_fail["id"])[1]
        check("revival_issue كُتب على المسودة القابلة للإحياء",
              updated_fb.get("revival_issue") == 9200, updated_fb.get("revival_issue"))
        check("revival_offers زاد بواحد", updated_fb.get("revival_offers") == 1,
              updated_fb.get("revival_offers"))

        for excluded in (img_fail, fields_fail, old_fail, twice_fail):
            fresh = store.load_draft(excluded["id"])[1]
            check(f"{excluded['id']} لم يُلمَس (لا revival_issue)",
                  "revival_issue" not in fresh, fresh)

        # تشغيل ثانٍ: لا Issue جديد لنفس المسودة (revival_issue مكتوب الآن)
        create_issue_calls.clear()
        code2 = open_review.main()
        check("تشغيل ثانٍ ينتهي بنجاح بلا مسودات/مرشحين جدد", code2 == 0, f"exit={code2}")
        check("لا Issue جديد في التشغيل الثاني", create_issue_calls == [], create_issue_calls)
    finally:
        review.create_issue = real_create_issue
        review.ensure_labels = real_ensure_labels
        restore_env()


@auto_restore_last_publish
def test_publish_revival_issue_full_flow() -> None:
    """Issue #959 جزء ج: اعتماد Issue إحياء يضم مسودة معلَّمة (أخبار)،
    وأخرى غير معلَّمة، ومعرّفًا محذوفًا، ومسودة تحليل معلَّمة — في مسار
    --skip-urgent. المعلَّمة تصير queued بموعد بعد آخر موعد محجوز، وغير
    المعلَّمة تموت نهائيًا (revival_declined)، ومسودة التحليل تُوجَّه عبر
    youtube_publish.publish_ids (مزيَّفة) بلا queued. تكرار التشغيل ومسار
    --urgent-only لا يغيّران شيئًا."""
    from src import publish as publish_mod
    from src import youtube_publish as yp

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    now_iso = datetime.now(timezone.utc).isoformat()

    # منشور محجوز في الطابور مسبقًا — الموعد الجديد يجب أن يبدأ بعده.
    booked_time = datetime.now(timezone.utc) + timedelta(hours=5)
    booked_draft = {
        "id": "beefbeef0001", "status": "queued",
        "publish_at": booked_time.isoformat(),
        "arabic": {"post_title": "منشور محجوز بالفعل", "urgent": False},
        "caption": "متن", "source": {}, "image": "drafts/booked.jpg",
    }
    marked = {
        "id": "feedbeef0011", "status": "failed", "failed_stage": "facebook",
        "failed_at": now_iso, "error": "خطأ فيسبوك تجريبي", "revival_issue": 9300,
        "revival_offers": 1,
        "arabic": {"post_title": "خبر أول سيُعاد نشره", "urgent": False},
        "caption": "متن1", "source": {}, "image": "drafts/rev1.jpg",
    }
    declined = {
        "id": "feedbeef0012", "status": "failed", "failed_stage": "facebook",
        "failed_at": now_iso, "error": "خطأ فيسبوك آخر", "revival_issue": 9300,
        "revival_offers": 1,
        "arabic": {"post_title": "خبر ثانٍ لن يُعاد", "urgent": False},
        "caption": "متن2", "source": {}, "image": "drafts/rev2.jpg",
    }
    analysis_marked = {
        "id": "feedbeef0013", "status": "failed", "failed_stage": "facebook",
        "failed_at": now_iso, "error": "خطأ فيسبوك تحليل", "revival_issue": 9300,
        "revival_offers": 1, "origin": "analysis",
        "arabic": {"post_title": "مقال تحليل سيُعاد نشره", "urgent": False,
                   "category": "تحليل"},
        "caption": "متن3", "source": {}, "image": "drafts/rev3.jpg",
    }
    deleted_id = "feedbeef00ff"  # لا مسودة على القرص إطلاقًا
    for d in (booked_draft, marked, declined, analysis_marked):
        store.save_draft(d)

    body = review.build_revival_body([marked, declined, analysis_marked], "u/r", "main")
    body = tick_marker(body, f"<!-- revive:{marked['id']} -->")
    body = tick_marker(body, f"<!-- revive:{analysis_marked['id']} -->")
    body += f"\n- [x] ♻️ أعد المحاولة  <!-- revive:{deleted_id} -->\n"

    real_fetch = publish_mod.fetch_issue
    real_comment = review.comment
    real_close = review.close_issue
    real_publish_ids = yp.publish_ids

    comments: list = []
    closed: list = []
    yt_calls: list = []

    def fake_publish_ids(ids, headline_choices, cfg):
        yt_calls.append(list(ids))
        for did in ids:
            found = store.load_draft(did)
            if found:
                store.update_draft(found[0], status="published")
        return ([f"- ✅ {i}" for i in ids], len(ids), len(ids), [])

    def make_fetch(issue_labels):
        return lambda n: {"number": n, "body": body, "labels": issue_labels}

    review.comment = lambda issue_number, text: comments.append((issue_number, text))
    review.close_issue = lambda issue_number: closed.append(issue_number)
    yp.publish_ids = fake_publish_ids
    publish_mod.fetch_issue = make_fetch(
        [{"name": "failed-review"}, {"name": "approved"}])

    try:
        sys.argv = ["publish", "--issue", "9300", "--skip-urgent"]
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        review.comment = real_comment
        review.close_issue = real_close
        yp.publish_ids = real_publish_ids

    check("publish.main (--skip-urgent) على Issue الإحياء ينتهي بنجاح",
          code == 0, f"exit={code}")

    updated_marked = store.load_draft(marked["id"])[1]
    check("المسودة المعلَّمة صارت queued",
          updated_marked.get("status") == "queued", updated_marked.get("status"))
    check("error زال", "error" not in updated_marked, updated_marked)
    check("failed_stage زال", "failed_stage" not in updated_marked, updated_marked)
    check("revival_issue زال", "revival_issue" not in updated_marked, updated_marked)
    check("revival_offers بقي كما هو (1)",
          updated_marked.get("revival_offers") == 1, updated_marked.get("revival_offers"))
    publish_at = updated_marked.get("publish_at")
    check("publish_at مكتوب", bool(publish_at), publish_at)
    if publish_at:
        check("publish_at بعد آخر موعد محجوز",
              datetime.fromisoformat(publish_at) > booked_time, publish_at)

    updated_declined = store.load_draft(declined["id"])[1]
    check("غير المعلَّمة تبقى failed",
          updated_declined.get("status") == "failed", updated_declined.get("status"))
    check("revival_declined=true", updated_declined.get("revival_declined") is True,
          updated_declined.get("revival_declined"))

    updated_analysis = store.load_draft(analysis_marked["id"])[1]
    check("مسودة analysis وُجِّهت إلى publish_ids المزيَّفة",
          yt_calls == [[analysis_marked["id"]]], yt_calls)
    check("مسودة analysis نُشرت عبر publish_ids ولم تصر queued",
          updated_analysis.get("status") == "published", updated_analysis.get("status"))

    check("تعليق نُشر على الـIssue", bool(comments), comments)
    check("الـIssue أُغلق", closed == [9300], closed)

    # تكرار التشغيل لا يغيّر شيئًا
    comments.clear()
    closed.clear()
    yt_calls.clear()
    publish_mod.fetch_issue = make_fetch(
        [{"name": "failed-review"}, {"name": "approved"}])
    review.comment = lambda issue_number, text: comments.append((issue_number, text))
    review.close_issue = lambda issue_number: closed.append(issue_number)
    yp.publish_ids = fake_publish_ids
    try:
        sys.argv = ["publish", "--issue", "9300", "--skip-urgent"]
        code_repeat = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        review.comment = real_comment
        review.close_issue = real_close
        yp.publish_ids = real_publish_ids

    check("تكرار التشغيل ينتهي بنجاح", code_repeat == 0, f"exit={code_repeat}")
    check("تكرار التشغيل: حالة المعلَّمة لم تتغيّر",
          store.load_draft(marked["id"])[1].get("status") == "queued")
    check("تكرار التشغيل: publish_at لم يتغيّر",
          store.load_draft(marked["id"])[1].get("publish_at") == publish_at)
    check("تكرار التشغيل: لا نداء جديد لـpublish_ids", yt_calls == [], yt_calls)

    # مسار --urgent-only لا يغيّر شيئًا
    comments.clear()
    closed.clear()
    yt_calls.clear()
    publish_mod.fetch_issue = make_fetch(
        [{"name": "failed-review"}, {"name": "approved"}])
    review.comment = lambda issue_number, text: comments.append((issue_number, text))
    review.close_issue = lambda issue_number: closed.append(issue_number)
    yp.publish_ids = fake_publish_ids
    try:
        sys.argv = ["publish", "--issue", "9300", "--urgent-only"]
        code_urgent = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        review.comment = real_comment
        review.close_issue = real_close
        yp.publish_ids = real_publish_ids

    check("مسار --urgent-only ينتهي بنجاح بلا فعل شيء", code_urgent == 0,
          f"exit={code_urgent}")
    check("--urgent-only: لا تعليق ولا إغلاق", comments == [] and closed == [],
          (comments, closed))
    check("--urgent-only: لا نداء publish_ids", yt_calls == [], yt_calls)


@auto_restore_last_publish
def test_revival_end_to_end() -> None:
    """من البداية إلى النهاية (Issue #959): فشل نشر فيسبوك ← فتح Issue
    الإحياء (open_review) ← اعتماده (publish.main --skip-urgent) ←
    publish --due بعد حلول الموعد مع facebook ناجح مزيَّف ← المسودة
    published."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    draft = {
        "id": "eeeebeef0001", "status": "pending",
        "arabic": {"post_title": "خبر من البداية للنهاية", "urgent": False},
        "caption": "متن", "source": {}, "image": "drafts/e2e.jpg",
    }
    path = store.save_draft(draft)
    (DRAFTS_DIR / "e2e.jpg").write_bytes(b"\xff\xd8\xff")

    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    publish_mod.ROOT = DRAFTS_DIR.parent

    def raise_fb(*a, **k):
        raise facebook.FacebookError("عطل مؤقت في فيسبوك")

    facebook.publish_photo = raise_fb
    try:
        ok, _ = publish_mod.publish_one(path, draft, load_config())
    finally:
        facebook.publish_photo = real_publish_photo

    check("النشر الأول فشل فعليًا", not ok)
    failed_draft = store.load_draft(draft["id"])[1]
    check("failed_stage=facebook بعد الفشل الأول",
          failed_draft.get("failed_stage") == "facebook", failed_draft)

    real_create_issue = review.create_issue
    real_ensure_labels = review.ensure_labels
    created: dict = {}

    def fake_create_issue(title, body, labels=None):
        created["title"], created["body"], created["labels"] = title, body, labels
        return {"number": 9400, "html_url": "https://github.com/u/r/issues/9400"}

    review.create_issue = fake_create_issue
    review.ensure_labels = lambda: None
    restore_env = _revival_env()
    try:
        code_open = open_review.main()
    finally:
        review.create_issue = real_create_issue
        review.ensure_labels = real_ensure_labels
        restore_env()

    check("open_review.main فتح Issue الإحياء بنجاح",
          code_open == 0 and created.get("labels") == ["failed-review"],
          created.get("labels"))

    body = tick_marker(created.get("body", ""), f"<!-- revive:{draft['id']} -->")

    real_fetch = publish_mod.fetch_issue
    real_comment = review.comment
    real_close = review.close_issue
    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body,
        "labels": [{"name": "failed-review"}, {"name": "approved"}],
    }
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: None
    try:
        sys.argv = ["publish", "--issue", "9400", "--skip-urgent"]
        code_approve = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        review.comment = real_comment
        review.close_issue = real_close

    check("الاعتماد نجح", code_approve == 0, f"exit={code_approve}")
    queued_draft = store.load_draft(draft["id"])[1]
    check("المسودة صارت queued بعد الاعتماد",
          queued_draft.get("status") == "queued", queued_draft.get("status"))

    # محاكاة حلول الموعد
    store.update_draft(
        path, publish_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())

    facebook.publish_photo = lambda *a, **k: {"url": "https://fb.example/final", "id": "999"}
    try:
        code_due = publish_mod.cmd_due(load_config())
    finally:
        facebook.publish_photo = real_publish_photo
        publish_mod.ROOT = real_root

    check("cmd_due ينتهي بنجاح", code_due == 0, f"exit={code_due}")
    final_draft = store.load_draft(draft["id"])[1]
    check("المسودة نُشرت أخيرًا (published)",
          final_draft.get("status") == "published", final_draft.get("status"))


@auto_restore_last_publish
def test_open_review_revival_offered_twice_then_stops() -> None:
    """الفشل الثاني يُعرض مرة أخيرة، والثالث لا يُعرض (Issue #959) — عبر
    الأنبوب الفعلي: publish_one يفشل، open_review.main يعرض، publish.main
    يعتمد فيعيد queued، يفشل ثانية، ثم ثالثة."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    draft = {
        "id": "cececebe0001", "status": "pending",
        "arabic": {"post_title": "خبر يفشل مرارًا", "urgent": False},
        "caption": "متن", "source": {}, "image": "drafts/thrice.jpg",
    }
    path = store.save_draft(draft)
    (DRAFTS_DIR / "thrice.jpg").write_bytes(b"\xff\xd8\xff")

    real_root = publish_mod.ROOT
    real_publish_photo = facebook.publish_photo
    real_create_issue = review.create_issue
    real_ensure_labels = review.ensure_labels
    real_fetch = publish_mod.fetch_issue
    real_comment = review.comment
    real_close = review.close_issue
    publish_mod.ROOT = DRAFTS_DIR.parent
    review.ensure_labels = lambda: None
    review.comment = lambda issue_number, text: None
    review.close_issue = lambda issue_number: None
    restore_env = _revival_env()

    def fail_once(msg: str) -> None:
        def raise_fb(*a, **k):
            raise facebook.FacebookError(msg)
        facebook.publish_photo = raise_fb
        try:
            publish_mod.publish_one(path, store.load_draft(draft["id"])[1], load_config())
        finally:
            facebook.publish_photo = real_publish_photo

    issue_counter = [9500]
    create_issue_calls: list = []

    def fake_create_issue(title, body, labels=None):
        issue_counter[0] += 1
        create_issue_calls.append(issue_counter[0])
        return {"number": issue_counter[0],
                "html_url": f"https://github.com/u/r/issues/{issue_counter[0]}"}

    def approve(issue_number: int) -> None:
        body = tick_marker(
            review.build_revival_body([store.load_draft(draft["id"])[1]], "u/r", "main"),
            f"<!-- revive:{draft['id']} -->")
        publish_mod.fetch_issue = lambda n: {
            "number": n, "body": body,
            "labels": [{"name": "failed-review"}, {"name": "approved"}],
        }
        try:
            sys.argv = ["publish", "--issue", str(issue_number), "--skip-urgent"]
            publish_mod.main()
        finally:
            publish_mod.fetch_issue = real_fetch

    try:
        review.create_issue = fake_create_issue

        # فشل أول ← يُعرض أول مرة.
        fail_once("فشل أول")
        code1 = open_review.main()
        check("open_review الأول ينتهي بنجاح", code1 == 0, f"exit={code1}")
        check("عُرضت أول مرة", len(create_issue_calls) == 1, create_issue_calls)
        d1 = store.load_draft(draft["id"])[1]
        check("revival_offers=1 بعد العرض الأول", d1.get("revival_offers") == 1,
              d1.get("revival_offers"))

        # اعتماد ← queued ← فشل ثانية ← يُعرض مرة أخيرة.
        approve(create_issue_calls[0])
        d1b = store.load_draft(draft["id"])[1]
        check("صارت queued بعد الاعتماد الأول", d1b.get("status") == "queued",
              d1b.get("status"))
        fail_once("فشل ثانٍ")
        code2 = open_review.main()
        check("open_review الثاني ينتهي بنجاح", code2 == 0, f"exit={code2}")
        check("عُرضت مرة أخيرة (ثانية)", len(create_issue_calls) == 2, create_issue_calls)
        d2 = store.load_draft(draft["id"])[1]
        check("revival_offers=2 بعد العرض الثاني", d2.get("revival_offers") == 2,
              d2.get("revival_offers"))

        # اعتماد ← queued ← فشل ثالثة ← لا عرض ثالث (سقف عرضين).
        approve(create_issue_calls[1])
        fail_once("فشل ثالث")
        code3 = open_review.main()
        check("open_review الثالث ينتهي بنجاح", code3 == 0, f"exit={code3}")
        check("لا عرض ثالث (السقف عرضان)", len(create_issue_calls) == 2,
              create_issue_calls)
    finally:
        publish_mod.ROOT = real_root
        facebook.publish_photo = real_publish_photo
        review.create_issue = real_create_issue
        review.ensure_labels = real_ensure_labels
        publish_mod.fetch_issue = real_fetch
        review.comment = real_comment
        review.close_issue = real_close
        restore_env()


# ──────────── إحياء دفعة تحليل تتجاوز سقف التشغيلة (Issue #961) ────────────


def _analysis_draft(idx: int, issue_number: int) -> dict:
    # REVIVE_MARKER (review.py) لا يطابق إلا معرّفًا سداسي عشريًا صغيرًا
    # ([0-9a-f]+) -- المعرّف هنا مبني ليطابق ذلك حرفيًا.
    return {
        "id": f"aa11beef{idx:04d}", "status": "failed", "failed_stage": "facebook",
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "error": f"خطأ فيسبوك تحليل {idx}", "revival_issue": issue_number,
        "revival_offers": 1, "origin": "analysis",
        "arabic": {"post_title": f"مقال تحليل رقم {idx}", "urgent": False,
                   "category": "تحليل"},
        "caption": f"متن تحليل {idx}", "source": {}, "image": f"drafts/an{idx}.jpg",
    }


@auto_restore_last_publish
def test_publish_revival_analysis_batch_cap_defers_remainder() -> None:
    """Issue #961: دفعة إحياء تحليل تتجاوز سقف التشغيلة (youtube.publish.
    max_per_run الافتراضي 3، أربع مسودات معلَّمة) لا تُفقد الرابعة الزائدة —
    تبقى تمامًا كما كانت (failed/failed_stage/revival_issue/error) بانتظار
    تشغيلة تالية، والـIssue لا يُغلق، ووسم approved يُزال، والتعليق يخبر
    عنها صراحة. تشغيلة ثانية بنفس جسم الـIssue تُكمل الرابعة وتغلق الـIssue."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    issue_number = 9400
    drafts = [_analysis_draft(i, issue_number) for i in range(1, 5)]
    for d in drafts:
        store.save_draft(d)

    body = review.build_revival_body(drafts, "u/r", "main")
    for d in drafts:
        body = tick_marker(body, f"<!-- revive:{d['id']} -->")

    real_fetch = publish_mod.fetch_issue
    real_comment = review.comment
    real_close = review.close_issue
    real_remove_label = review.remove_label
    real_ensure_title_card = youtube_publish.ensure_title_card
    real_publish_one = publish_mod.publish_one
    real_sleep = youtube_publish.time.sleep

    comments: list = []
    closed: list = []
    removed_labels: list = []
    published_ids: list = []

    def fake_publish_one(path, draft, cfg):
        store.update_draft(path, status="published")
        published_ids.append(draft["id"])
        return True, f"- ✅ {draft['arabic']['post_title'][:50]}"

    def run():
        comments.clear(); closed.clear(); removed_labels.clear(); published_ids.clear()
        publish_mod.fetch_issue = lambda n: {
            "number": n, "body": body,
            "labels": [{"name": "failed-review"}, {"name": "approved"}]}
        review.comment = lambda n, t: comments.append((n, t))
        review.close_issue = lambda n: closed.append(n)
        review.remove_label = lambda n, l: removed_labels.append((n, l))
        youtube_publish.ensure_title_card = lambda path, draft, cfg: True
        publish_mod.publish_one = fake_publish_one
        youtube_publish.time.sleep = lambda s: None
        try:
            sys.argv = ["publish", "--issue", str(issue_number), "--skip-urgent"]
            return publish_mod.main()
        finally:
            publish_mod.fetch_issue = real_fetch
            review.comment = real_comment
            review.close_issue = real_close
            review.remove_label = real_remove_label
            youtube_publish.ensure_title_card = real_ensure_title_card
            publish_mod.publish_one = real_publish_one
            youtube_publish.time.sleep = real_sleep

    code1 = run()
    check("التشغيلة الأولى تنتهي بنجاح", code1 == 0, f"exit={code1}")
    check("ثلاث مسودات نُشرت في التشغيلة الأولى",
          published_ids == [d["id"] for d in drafts[:3]], published_ids)

    fourth = store.load_draft(drafts[3]["id"])[1]
    check("الرابعة بقيت failed", fourth.get("status") == "failed", fourth.get("status"))
    check("الرابعة بقي failed_stage=facebook",
          fourth.get("failed_stage") == "facebook", fourth.get("failed_stage"))
    check("الرابعة بقي revival_issue", fourth.get("revival_issue") == issue_number,
          fourth.get("revival_issue"))
    check("الرابعة بقي error", "error" in fourth, fourth)

    for i in range(3):
        d = store.load_draft(drafts[i]["id"])[1]
        check(f"المسودة {i + 1} صارت published وحقولها الثلاثة زالت",
              d.get("status") == "published" and "failed_stage" not in d
              and "revival_issue" not in d and "error" not in d, d)

    check("الـIssue لم يُغلق في التشغيلة الأولى", closed == [], closed)
    check("وسم approved أُزيل", removed_labels == [(issue_number, "approved")],
          removed_labels)
    check("التعليق يحوي سطر ⏳ للرابعة",
          any("⏳" in t and "مقال تحليل رقم 4" in t for _, t in comments), comments)
    check("التعليق يطلب إعادة وسم approved لمتابعة الباقي",
          any("أعد وضع وسم" in t for _, t in comments), comments)

    code2 = run()
    check("التشغيلة الثانية تنتهي بنجاح", code2 == 0, f"exit={code2}")
    check("الرابعة نُشرت في التشغيلة الثانية",
          published_ids == [drafts[3]["id"]], published_ids)
    fourth2 = store.load_draft(drafts[3]["id"])[1]
    check("الرابعة صارت published", fourth2.get("status") == "published",
          fourth2.get("status"))
    check("الـIssue أُغلق في التشغيلة الثانية", closed == [issue_number], closed)


@auto_restore_last_publish
def test_publish_revival_analysis_batch_seven_drafts_three_runs() -> None:
    """نفس سيناريو سقف الدفعة أعلاه بسبع مسودات معلَّمة: تشغيلتان لا تكفيان
    (٣+٣=٦)، والثالثة تُكمل السابعة وتُغلق الـIssue -- لا قبلها إطلاقًا."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    issue_number = 9410
    drafts = [_analysis_draft(i, issue_number) for i in range(1, 8)]
    for d in drafts:
        store.save_draft(d)

    body = review.build_revival_body(drafts, "u/r", "main")
    for d in drafts:
        body = tick_marker(body, f"<!-- revive:{d['id']} -->")

    real_fetch = publish_mod.fetch_issue
    real_comment = review.comment
    real_close = review.close_issue
    real_remove_label = review.remove_label
    real_ensure_title_card = youtube_publish.ensure_title_card
    real_publish_one = publish_mod.publish_one
    real_sleep = youtube_publish.time.sleep

    closed: list = []

    def fake_publish_one(path, draft, cfg):
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['arabic']['post_title'][:50]}"

    def run():
        closed.clear()
        publish_mod.fetch_issue = lambda n: {
            "number": n, "body": body,
            "labels": [{"name": "failed-review"}, {"name": "approved"}]}
        review.comment = lambda n, t: None
        review.close_issue = lambda n: closed.append(n)
        review.remove_label = lambda n, l: None
        youtube_publish.ensure_title_card = lambda path, draft, cfg: True
        publish_mod.publish_one = fake_publish_one
        youtube_publish.time.sleep = lambda s: None
        try:
            sys.argv = ["publish", "--issue", str(issue_number), "--skip-urgent"]
            return publish_mod.main()
        finally:
            publish_mod.fetch_issue = real_fetch
            review.comment = real_comment
            review.close_issue = real_close
            review.remove_label = real_remove_label
            youtube_publish.ensure_title_card = real_ensure_title_card
            publish_mod.publish_one = real_publish_one
            youtube_publish.time.sleep = real_sleep

    run()
    check("لا إغلاق بعد التشغيلة الأولى (سبع مسودات)", closed == [], closed)
    run()
    check("لا إغلاق بعد التشغيلة الثانية (سبع مسودات)", closed == [], closed)
    run()
    check("إغلاق بعد التشغيلة الثالثة فقط (سبع مسودات)",
          closed == [issue_number], closed)

    for d in drafts:
        final = store.load_draft(d["id"])[1]
        check(f"{d['id']} صارت published بعد ثلاث تشغيلات",
              final.get("status") == "published", final.get("status"))


@auto_restore_last_publish
def test_publish_revival_mixed_news_and_analysis_batch() -> None:
    """دفعة إحياء مختلطة: خبر معلَّم يُجدول queued فورًا (لا سقف دفعة عليه)،
    وخبر غير معلَّم يموت نهائيًا، وأربع مسودات تحليل تخضع لسقف الدفعة كما في
    الاختبارين أعلاه. تكرار التشغيل على نفس جسم الـIssue لا يُعيد جدولة الخبر
    المعلَّم (يصير «غير مطابق» بدل ذلك) ولا يُحيي غير المعلَّم."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    issue_number = 9420
    now_iso = datetime.now(timezone.utc).isoformat()
    news_marked = {
        "id": "aa22beef0001", "status": "failed", "failed_stage": "facebook",
        "failed_at": now_iso, "error": "خطأ فيسبوك خبر", "revival_issue": issue_number,
        "revival_offers": 1,
        "arabic": {"post_title": "خبر معلَّم للإحياء", "urgent": False},
        "caption": "متن خبر", "source": {}, "image": "drafts/news1.jpg",
    }
    news_unmarked = {
        "id": "aa22beef0002", "status": "failed", "failed_stage": "facebook",
        "failed_at": now_iso, "error": "خطأ فيسبوك خبر آخر", "revival_issue": issue_number,
        "revival_offers": 1,
        "arabic": {"post_title": "خبر غير معلَّم", "urgent": False},
        "caption": "متن خبر٢", "source": {}, "image": "drafts/news2.jpg",
    }
    analysis_drafts = [_analysis_draft(i, issue_number) for i in range(1, 5)]
    all_drafts = [news_marked, news_unmarked] + analysis_drafts
    for d in all_drafts:
        store.save_draft(d)

    body = review.build_revival_body(all_drafts, "u/r", "main")
    body = tick_marker(body, f"<!-- revive:{news_marked['id']} -->")
    for d in analysis_drafts:
        body = tick_marker(body, f"<!-- revive:{d['id']} -->")
    # news_unmarked يبقى بلا تعليم عمدًا -- يجب أن يموت نهائيًا.

    real_fetch = publish_mod.fetch_issue
    real_comment = review.comment
    real_close = review.close_issue
    real_remove_label = review.remove_label
    real_ensure_title_card = youtube_publish.ensure_title_card
    real_publish_one = publish_mod.publish_one
    real_sleep = youtube_publish.time.sleep

    def fake_publish_one(path, draft, cfg):
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['arabic']['post_title'][:50]}"

    def run():
        publish_mod.fetch_issue = lambda n: {
            "number": n, "body": body,
            "labels": [{"name": "failed-review"}, {"name": "approved"}]}
        review.comment = lambda n, t: None
        review.close_issue = lambda n: None
        review.remove_label = lambda n, l: None
        youtube_publish.ensure_title_card = lambda path, draft, cfg: True
        publish_mod.publish_one = fake_publish_one
        youtube_publish.time.sleep = lambda s: None
        try:
            sys.argv = ["publish", "--issue", str(issue_number), "--skip-urgent"]
            return publish_mod.main()
        finally:
            publish_mod.fetch_issue = real_fetch
            review.comment = real_comment
            review.close_issue = real_close
            review.remove_label = real_remove_label
            youtube_publish.ensure_title_card = real_ensure_title_card
            publish_mod.publish_one = real_publish_one
            youtube_publish.time.sleep = real_sleep

    run()
    marked_after1 = store.load_draft(news_marked["id"])[1]
    check("الخبر المعلَّم صار queued في التشغيلة الأولى",
          marked_after1.get("status") == "queued", marked_after1.get("status"))
    publish_at_1 = marked_after1.get("publish_at")
    check("publish_at مكتوب للخبر المعلَّم", bool(publish_at_1), marked_after1)

    unmarked_after1 = store.load_draft(news_unmarked["id"])[1]
    check("الخبر غير المعلَّم مات نهائيًا (revival_declined)",
          unmarked_after1.get("status") == "failed"
          and unmarked_after1.get("revival_declined") is True, unmarked_after1)

    run()
    marked_after2 = store.load_draft(news_marked["id"])[1]
    check("الخبر المعلَّم لم يتكرر جدولته في التشغيلة الثانية",
          marked_after2.get("status") == "queued"
          and marked_after2.get("publish_at") == publish_at_1, marked_after2)


@auto_restore_last_publish
def test_publish_revival_batch_member_fails_again_stays_offered() -> None:
    """مسودة تحليل ضمن الدفعة نفسها (لا تتجاوز السقف) فشلت ثانية أثناء
    التشغيلة: ليست ضمن «الباقي» (remaining خاص بما تجاوز سقف الدفعة فقط، لا
    بما حُووِل وفشل)، وتحمل failed_stage من جديد بلا revival_issue -- فتُعرض
    مرة أخيرة عبر open_review._revivable_drafts (Issue #961، البند ٥: سلوك
    قائم لا يتغيّر)."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()

    issue_number = 9430
    drafts = [_analysis_draft(i, issue_number) for i in range(1, 3)]  # اثنتان ضمن السقف
    failing_id = drafts[1]["id"]
    for d in drafts:
        store.save_draft(d)

    body = review.build_revival_body(drafts, "u/r", "main")
    for d in drafts:
        body = tick_marker(body, f"<!-- revive:{d['id']} -->")

    real_fetch = publish_mod.fetch_issue
    real_comment = review.comment
    real_close = review.close_issue
    real_remove_label = review.remove_label
    real_ensure_title_card = youtube_publish.ensure_title_card
    real_publish_one = publish_mod.publish_one
    real_sleep = youtube_publish.time.sleep

    comments: list = []

    def fake_publish_one(path, draft, cfg):
        if draft["id"] == failing_id:
            store.update_draft(
                path, status="failed", error="فشل فيسبوك ثانٍ",
                failed_stage="facebook",
                failed_at=datetime.now(timezone.utc).isoformat(),
            )
            return False, f"- ❌ {draft['arabic']['post_title'][:50]}"
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['arabic']['post_title'][:50]}"

    publish_mod.fetch_issue = lambda n: {
        "number": n, "body": body,
        "labels": [{"name": "failed-review"}, {"name": "approved"}]}
    review.comment = lambda n, t: comments.append(t)
    review.close_issue = lambda n: None
    review.remove_label = lambda n, l: None
    youtube_publish.ensure_title_card = lambda path, draft, cfg: True
    publish_mod.publish_one = fake_publish_one
    youtube_publish.time.sleep = lambda s: None
    try:
        sys.argv = ["publish", "--issue", str(issue_number), "--skip-urgent"]
        code = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real_fetch
        review.comment = real_comment
        review.close_issue = real_close
        review.remove_label = real_remove_label
        youtube_publish.ensure_title_card = real_ensure_title_card
        publish_mod.publish_one = real_publish_one
        youtube_publish.time.sleep = real_sleep

    check("التشغيلة تنتهي بنجاح", code == 0, f"exit={code}")
    check("لا سطر ⏳ للمسودة الفاشلة ثانية (ليست ضمن الباقي)",
          not any("⏳" in t for t in comments), comments)

    failed_again = store.load_draft(failing_id)[1]
    check("فشلت ثانية بـfailed_stage من جديد",
          failed_again.get("status") == "failed"
          and failed_again.get("failed_stage") == "facebook", failed_again)
    check("بلا revival_issue بعد الفشل الثاني",
          "revival_issue" not in failed_again, failed_again)

    revivable_ids = {d["id"] for _, d in open_review._revivable_drafts()}
    check("open_review._revivable_drafts تعيدها للعرض مرة أخيرة",
          failing_id in revivable_ids, revivable_ids)


def test_web_search_stage() -> None:
    """مرحلة «بحث صور الويب» (Brave) على مخرَج الأنبوب: cards.ensure كاملة ثم
    فحص المسودة المحفوظة والبطاقة. requests.get وdownload_image مزيَّفان،
    والصور تُولَّد هنا، وBRAVE_API_KEY مضبوط داخل الاختبار فقط ويُحذف بعده."""
    from src import cards, imagesearch, sources

    cfg = load_config()
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    good = Image.new("RGB", (1000, 700), (200, 120, 40))
    ImageDraw.Draw(good).ellipse([350, 150, 650, 450], fill=(240, 220, 190))
    real_dl, real_page = imaging.download_image, sources.image_from_page
    real_find, real_get = cards.find_images, imagesearch.requests.get
    real_key = os.environ.get("BRAVE_API_KEY")
    usage_file = imagesearch.BRAVE_USAGE_FILE
    state = {"find": 0, "brave": [], "dl": [], "results": []}

    def fake_dl(url, timeout=20, failures=None):
        state["dl"].append(url)
        if "good" in url:
            return good.copy()
        if failures is not None:
            failures.append({"url": url, "reason": "رفض"})
        return None

    def fake_get(url, **kw):
        state["brave"].append((url, kw))

        class R:
            status_code = 200

            def json(self_):
                return {"results": state["results"]}
        return R()

    def result(page, orig, thumb):
        return {"url": page, "properties": {"url": orig}, "thumbnail": {"src": thumb}}

    def run(did, *, key="k-test", usage=None, origin="news", results=None,
            extra=None, news_ok=False, publisher_ok=False, source_title="Original Title"):
        state.update(find=0, brave=[], dl=[])
        state["results"] = results if results is not None else [
            result("https://www.bbc.com/a", "https://img.example/good-1.jpg",
                   "https://img.example/thumb-1.jpg")]
        usage_file.unlink(missing_ok=True)
        if usage is not None:
            usage_file.parent.mkdir(parents=True, exist_ok=True)
            usage_file.write_text(json.dumps({imagesearch._month_key(): usage}))
        if key is None:
            os.environ.pop("BRAVE_API_KEY", None)
        else:
            os.environ["BRAVE_API_KEY"] = key
        img = "https://pub.example/good-pub.jpg" if publisher_ok else "https://pub.example/bad.jpg"
        draft = {
            "id": did, "status": "pending", "origin": origin, "bucket": "serious",
            "source": {"title": source_title, "link": "https://pub.example/a",
                       "publisher": "ناشر", "publishers": ["ناشر"],
                       "image_url": img, "image_candidates": [img]},
            "arabic": {"post_title": "عنوان عربي", "image_headline": "عنوان البطاقة",
                       "category": "عالم", "urgent": False},
            **(extra or {}),
        }
        path = store.save_draft(draft)
        imaging.download_image = fake_dl  # type: ignore
        sources.image_from_page = lambda url, timeout=12: None  # type: ignore
        imagesearch.requests.get = fake_get  # type: ignore

        def fake_find(term, cfg_):
            state["find"] += 1
            return ["https://free.example/good-free.jpg"]
        cards.find_images = fake_find  # type: ignore
        kw = {}
        if news_ok:
            kw["news_photo_provider"] = lambda: [{"url": "https://news.example/good-n.jpg",
                                                  "publisher": "ن"}]
        try:
            rel = cards.ensure(path, draft, cfg, **kw)
        finally:
            imaging.download_image = real_dl  # type: ignore
            sources.image_from_page = real_page  # type: ignore
            cards.find_images = real_find  # type: ignore
            imagesearch.requests.get = real_get  # type: ignore
        return rel, json.loads(path.read_text(encoding="utf-8"))

    def q_of_first_call():
        return state["brave"][0][1]["params"]["q"] if state["brave"] else None

    try:
        # a) المرحلتان 1 و2 تفشلان وBrave يعيد صورة صالحة
        rel, saved = run("web_a")
        info = saved.get("image_info") or {}
        card_file = DRAFTS_DIR / Path(rel).relative_to("drafts") if rel else None
        check("بحث الويب (a): بُنيت البطاقة", bool(card_file) and card_file.exists(), rel)
        check("بحث الويب (a): kind=web_search والنطاق محفوظ والرابط المختار",
              info.get("kind") == "web_search" and info.get("web_search_domain") == "www.bbc.com"
              and info.get("chosen_url") == "https://img.example/good-1.jpg", info)
        check("بحث الويب (a): البديل الحر لم يُستدعَ ولا وسم تعبيرية",
              state["find"] == 0 and info.get("fallback_tried") is False
              and info.get("illustrative") is False, (state["find"], info))
        check("بحث الويب (a): has_photo صحيح (لا «بلا صورة للخبر» للمراجع)",
              saved.get("has_photo") is True, saved.get("has_photo"))
        check("بحث الويب (a): web_search_query وweb_search_tried وskipped",
              info.get("web_search_query") == "Original Title"
              and info.get("web_search_tried") == 1 and info.get("web_search_skipped") is None, info)
        if card_file and card_file.exists():
            shutil.copy(card_file, "/tmp/web_search_card_a.jpg")
        # j) سطر المراجعة
        line = review.image_source_line(saved)
        check("بحث الويب (j): image_source_line يعرض النطاق وتنبيه المراجعة",
              line == "🖼️ **المصدر:** صورة من بحث الويب (النطاق: www.bbc.com) — راجعها قبل الاعتماد",
              line)
        # i) معاملات الطلب
        rel, saved = run("web_i")
        url, kw = state["brave"][0]
        check("بحث الويب (i): العنوان والترويسة والمعاملات",
              url == "https://api.search.brave.com/res/v1/images/search"
              and kw["headers"]["X-Subscription-Token"] == "k-test"
              and kw["params"]["safesearch"] == "strict" and kw["params"]["count"] == 10
              and kw["params"]["q"] == "Original Title", (url, kw))
        check("بحث الويب: العدّاد زاد 1 وحُفظ فورًا",
              imagesearch.brave_usage() == 1, imagesearch.brave_usage())

        # b) نجاح المرحلة 1 ← لا طلب
        rel, saved = run("web_b", publisher_ok=True)
        check("بحث الويب (b): نجاح صورة الناشر ⇒ لا طلب إلى Brave والعدّاد صفر",
              not state["brave"] and imagesearch.brave_usage() == 0
              and saved["image_info"]["kind"] is None, (state["brave"], saved["image_info"]))
        rel, saved = run("web_b2", news_ok=True)
        check("بحث الويب (b): نجاح صورة الخبر (المرحلة 2) ⇒ لا طلب أيضًا",
              not state["brave"] and saved["image_info"]["kind"] == "news_photo", saved["image_info"])

        # c) نتيجة من gettyimages تُتخطى
        rel, saved = run("web_c", results=[
            result("https://www.gettyimages.com/x", "https://img.example/good-getty.jpg", "https://t/x"),
            result("https://www.reuters.com/y", "https://img.example/good-2.jpg", "https://t/y")])
        info = saved["image_info"]
        check("بحث الويب (c): gettyimages تُتخطى إلى التالية",
              info.get("web_search_domain") == "www.reuters.com"
              and not any("getty" in u for u in state["dl"]), (info, state["dl"]))

        # إحكام الاستبعاد: نطاق properties.url يُفحص أيضًا والنتيجة تُستبعد كاملة
        rel, saved = run("web_c2", results=[
            result("https://www.bbc.com/a", "https://media.gettyimages.com/good-x.jpg",
                   "https://imgs.search.brave.com/good-thumb-x"),
            result("https://www.reuters.com/y", "https://img.example/good-2.jpg", "https://t/y")])
        info = saved["image_info"]
        check("استبعاد الوكالات: أصل على gettyimages وصفحة إخبارية ⇒ تُستبعد بأصلها ومصغّرتها",
              info.get("web_search_domain") == "www.reuters.com"
              and "https://media.gettyimages.com/good-x.jpg" not in state["dl"]
              and "https://imgs.search.brave.com/good-thumb-x" not in state["dl"], (info, state["dl"]))
        rel, saved = run("web_c3", results=[
            result("https://www.gettyimages.com/x", "https://img.example/good-o.jpg", "https://t/x"),
            result("https://www.reuters.com/y", "https://img.example/good-2.jpg", "https://t/y")])
        check("استبعاد الوكالات: صفحة gettyimages وصورة على نطاق آخر ⇒ تُستبعد",
              saved["image_info"].get("web_search_domain") == "www.reuters.com"
              and "https://img.example/good-o.jpg" not in state["dl"], state["dl"])
        rel, saved = run("web_c4", results=[
            result("https://www.bbc.com/a", "https://img.example/good-ok.jpg", "https://t/ok")])
        check("استبعاد الوكالات: نتيجة سليمة النطاقين تُقبل",
              saved["image_info"].get("web_search_domain") == "www.bbc.com"
              and saved["image_info"].get("chosen_url") == "https://img.example/good-ok.jpg",
              saved["image_info"])
        rel, saved = run("web_c5", results=[
            *[result("https://www.bbc.com/a%d" % i, "https://media.gettyimages.com/%d.jpg" % i,
                     "https://t/%d" % i) for i in range(6)],
            result("https://www.reuters.com/y", "https://img.example/good-7.jpg", "https://t/y")])
        check("استبعاد الوكالات: ست نتائج مستبعدة لا تستهلك max_tries والسليمة تُقبل",
              saved["image_info"].get("web_search_domain") == "www.reuters.com"
              and saved["image_info"].get("kind") == "web_search", saved["image_info"])

        # d) الأصل يفشل والمصغّرة تنجح
        rel, saved = run("web_d", results=[
            result("https://www.bbc.com/a", "https://img.example/bad-orig.jpg",
                   "https://img.example/good-thumb.jpg")])
        info = saved["image_info"]
        check("بحث الويب (d): الأصل يفشل فتُستعمل المصغّرة",
              info.get("kind") == "web_search" and info.get("chosen_url").endswith("good-thumb.jpg")
              and info.get("web_search_tried") == 2, info)

        # e) السقف
        rel, saved = run("web_e", usage=800)
        info = saved["image_info"]
        check("بحث الويب (e): السقف ⇒ لا طلب وskipped=cap والسلسلة تكمل للحرة",
              not state["brave"] and info.get("web_search_skipped") == "cap"
              and state["find"] == 1 and info.get("illustrative") is True
              and imagesearch.brave_usage() == 800, (info, state))
        check("بحث الويب (e): سطر المصدر يذكر توقف بحث الويب",
              review.image_source_line(saved).endswith("(بحث الويب متوقف: بلغ السقف الشهري)"),
              review.image_source_line(saved))

        # f) بلا مفتاح
        rel, saved = run("web_f", key=None)
        info = saved["image_info"]
        check("بحث الويب (f): بلا مفتاح ⇒ لا طلب وskipped=no_key وبناء ناجح بلا خطأ",
              bool(rel) and not state["brave"] and info.get("web_search_skipped") == "no_key"
              and state["find"] == 1, (rel, info))

        # g) manual_image
        rel, saved = run("web_g", extra={"manual_image": "https://manual.example/bad.jpg"})
        check("بحث الويب (g): manual_image ⇒ لا طلب",
              not state["brave"] and saved["image_info"].get("web_search_skipped") is None,
              state["brave"])

        # setimage.rebuild_card (allow_search_fallback=False): لا بحث ويب أيضًا
        real_run_kw = cards.ensure
        cards.ensure = lambda *a, **k: real_run_kw(*a, allow_search_fallback=False, **k)  # type: ignore
        try:
            rel, saved = run("web_g2", publisher_ok=False)
        finally:
            cards.ensure = real_run_kw  # type: ignore
        check("بحث الويب: allow_search_fallback=False (إعادة بناء setimage) ⇒ لا طلب",
              not state["brave"], state["brave"])

        # h) عبارة البحث
        run("web_h1", origin="analysis", extra={"image_query_en": "Gaza ceasefire talks"})
        check("بحث الويب (h): تحليل بـimage_query_en يستعملها",
              q_of_first_call() == "Gaza ceasefire talks", state["brave"])
        run("web_h2", origin="analysis")
        check("بحث الويب (h): تحليل بلا image_query_en يستعمل العنوان العربي",
              q_of_first_call() == "عنوان عربي", state["brave"])
        run("web_h3", source_title="Original News Title")
        check("بحث الويب (h): خبر يستعمل source.title",
              q_of_first_call() == "Original News Title", state["brave"])
    finally:
        if real_key is None:
            os.environ.pop("BRAVE_API_KEY", None)
        else:
            os.environ["BRAVE_API_KEY"] = real_key
        usage_file.unlink(missing_ok=True)
        imaging.download_image = real_dl  # type: ignore
        imagesearch.requests.get = real_get  # type: ignore


def test_news_card_image_chain() -> None:
    """Issue #1153 — سلّم صورة بطاقة الأخبار على مخرَج الأنبوب: cards.ensure
    كاملة ثم فحص المسودة المحفوظة والبطاقة الناتجة. التحميل وجلب og:image
    مزيَّفان، والصور تُولَّد هنا لا من drafts/."""
    from src import cards, collect_finalize, preselect, sources

    cfg = load_config()
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    good = Image.new("RGB", (900, 600), (30, 160, 60))
    GOOD_PAGE_IMG = "https://cdn.example.org/other-publisher/photo.jpg"
    real_dl, real_page = imaging.download_image, sources.image_from_page
    real_find, real_draw = cards.find_images, imaging.draw_text
    state = {"find": 0, "drawn": []}

    def fake_dl(url, timeout=20, failures=None):
        if "other-publisher" in url or "free-photo" in url:
            return good.copy()
        if failures is not None:
            failures.append({"url": url, "reason": "HTTP 403، حجم 0 بايت (دون 15000)"})
        return None

    def fake_find(term, cfg_):
        state["find"] += 1
        return ["https://x.example.org/free-photo.jpg"]

    def run(did, *, manual=None, news_provider=None, related=True,
            page_img=GOOD_PAGE_IMG, publishers=("Africanews",),
            related_names=("الجزيرة",), image_url="https://africanews.example/bad.jpg",
            origin="news"):
        state["find"] = 0
        state["drawn"] = []
        draft = {
            "id": did, "status": "pending", "origin": origin, "bucket": "serious",
            "source": {"title": "خبر", "link": "https://africanews.example/a",
                       "publisher": publishers[0], "publishers": list(publishers),
                       "image_url": image_url, "image_candidates": [image_url]},
            "arabic": {"post_title": "عنوان", "image_headline": "عنوان البطاقة",
                       "category": "عالم", "urgent": False},
        }
        if related:
            draft["source"]["related_links"] = ["https://aljazeera.example/a"]
            draft["source"]["related_publishers"] = list(related_names)
        if manual:
            draft["manual_image"] = manual
        path = store.save_draft(draft)
        imaging.download_image = fake_dl  # type: ignore
        sources.image_from_page = lambda url, timeout=12: page_img  # type: ignore
        cards.find_images = fake_find  # type: ignore
        imaging.draw_text = (  # type: ignore
            lambda d, xy, text, *a, **k: (state["drawn"].append(text),
                                          real_draw(d, xy, text, *a, **k))[1])
        try:
            kw = {"news_photo_provider": news_provider} if news_provider else {}
            rel = cards.ensure(path, draft, cfg, **kw)
        finally:
            imaging.download_image = real_dl  # type: ignore
            sources.image_from_page = real_page  # type: ignore
            cards.find_images = real_find  # type: ignore
            imaging.draw_text = real_draw  # type: ignore
        return rel, json.loads(path.read_text(encoding="utf-8"))

    # a) صورة الناشر تفشل ومقال ناشر آخر صورته صالحة
    rel, saved = run("chain_a")
    info = saved.get("image_info") or {}
    check("سلّم الأخبار (a): بُنيت بطاقة فعلًا",
          bool(rel) and (DRAFTS_DIR / Path(rel).relative_to("drafts")).exists(), rel)
    check("سلّم الأخبار (a): kind=news_photo وناشر الصورة الجزيرة",
          info.get("kind") == "news_photo" and info.get("news_photo_publisher") == "الجزيرة"
          and info.get("chosen_url") == GOOD_PAGE_IMG, info)
    check("سلّم الأخبار (a): لم يُستدعَ البديل الحر (نجحت صورة الناشر الآخر)",
          state["find"] == 0 and info.get("fallback_tried") is False, (state, info))
    # Issue #1158: «صورة: …» حُذف من البطاقة كليًا؛ المصدر يبقى في image_info
    check("سلّم الأخبار (a): لا «صورة: …» على البطاقة رغم أن الناشر ليس من ناشري الخبر "
          "(ناشر الصورة داخلي في image_info فقط)",
          not any("صورة:" in str(t) for t in state["drawn"]), state["drawn"])
    # d) أسباب الفشل محفوظة في المسودة
    fails = info.get("candidate_failures") or []
    check("سلّم الأخبار (d): candidate_failures تحمل رابط صورة الناشر وسببه",
          any("africanews.example/bad.jpg" in f["url"] and "403" in f["reason"]
              for f in fails), fails)

    # b) كل الصور ومقالات الناشرين تفشل ⇒ البديل الحر يُستدعى
    rel, saved = run("chain_b", page_img="https://nowhere.example/none.jpg")
    info = saved.get("image_info") or {}
    check("سلّم الأخبار (b): فشل الكل ⇒ البديل الحر يُستدعى وfallback_tried=True",
          state["find"] == 1 and info.get("fallback_tried") is True
          and info.get("fallback_candidates") == 1, (state, info))
    check("سلّم الأخبار (b): صورة الحرة تعبيرية", info.get("illustrative") is True, info)
    check("سلّم الأخبار (d): كل فشل محفوظ بسببه (صور الناشر والمقال الآخر)",
          len(info.get("candidate_failures") or []) >= 2
          and all(f.get("reason") for f in info["candidate_failures"]), info)
    rel, saved = run("chain_b2", page_img=None)
    fails = (saved.get("image_info") or {}).get("candidate_failures") or []
    check("سلّم الأخبار (d): صفحة بلا og:image تُسجَّل سببًا",
          any("og:image" in f["reason"] for f in fails), fails)
    # إصلاح البوابة: صور ناشر فاشلة بلا روابط أخرى ⇒ الحرة تُجرَّب أيضًا
    rel, saved = run("chain_b3", related=False)
    check("سلّم الأخبار (بوابة): صور ناشر فاشلة بلا روابط أخرى ⇒ الحرة تُجرَّب",
          state["find"] == 1 and saved["image_info"]["fallback_tried"] is True, state)

    # c) manual_image يفشل ⇒ لا بديل حر ولا مقال آخر
    rel, saved = run("chain_c", manual="https://manual.example/bad.jpg")
    info = saved.get("image_info") or {}
    check("سلّم الأخبار (c): manual_image فاشلة ⇒ لا بديل حر",
          state["find"] == 0 and info.get("fallback_tried") is False
          and info.get("illustrative") is False, (state, info))
    check("سلّم الأخبار (c): manual_image فاشلة ⇒ لا صورة مقال آخر أيضًا",
          info.get("kind") is None and info.get("manual") is True, info)

    # d) قصّ الرابط الطويل إلى 120 حرفًا
    long_url = "https://africanews.example/" + "x" * 300 + ".jpg"
    rel, saved = run("chain_d", related=False, image_url=long_url)
    fails = (saved.get("image_info") or {}).get("candidate_failures") or []
    check("سلّم الأخبار (d): الرابط الطويل يُقصّ إلى 120 حرفًا",
          bool(fails) and all(len(f["url"]) <= 120 for f in fails), fails)

    # e) ناشر الصورة بين ناشري الخبر ⇒ لا «صورة: …» مكرر
    rel, saved = run("chain_e", publishers=("Africanews", "الجزيرة"))
    info = saved.get("image_info") or {}
    check("سلّم الأخبار (e): ناشر الصورة بين ناشري الخبر ⇒ لا «صورة: …» مكرر",
          info.get("kind") == "news_photo"
          and not any("صورة:" in str(t) for t in state["drawn"]),
          (info, state["drawn"]))

    # f) مسار التحليل: المزوّد الممرَّر هو المستعمل ولا تُجلب صفحات related_links
    called = {"n": 0}
    page_calls = {"n": 0}
    own_url = "https://cdn.example.org/other-publisher/analysis.jpg"

    def own_provider():
        called["n"] += 1
        return [{"url": own_url, "publisher": "تحليلي"}]

    def counting_page(*a, **k):
        page_calls["n"] += 1
        return GOOD_PAGE_IMG

    real_page = sources.image_from_page
    sources.image_from_page = counting_page  # type: ignore
    imaging.download_image = fake_dl  # type: ignore
    try:
        d = {"id": "chain_f", "status": "pending", "origin": "analysis",
             "source": {"related_links": ["https://aljazeera.example/a"]},
             "arabic": {"post_title": "ع", "category": ""}}
        p2 = store.save_draft(d)
        cards.ensure(p2, d, cfg, news_photo_provider=own_provider, image_urls=None,
                     allow_search_fallback=False, check_headline_limit=False,
                     **cards.analysis_card_kwargs())
    finally:
        sources.image_from_page = real_page  # type: ignore
        imaging.download_image = real_dl  # type: ignore
    info = d.get("image_info") or {}
    check("سلّم الأخبار (f): مزوّد التحليل الممرَّر هو المستعمل",
          called["n"] == 1 and info.get("news_photo_publisher") == "تحليلي"
          and info.get("chosen_url") == own_url, (called, info))
    check("سلّم الأخبار (f): مزوّد مُمرَّر ⇒ لا جلب لصفحات related_links",
          page_calls["n"] == 0, page_calls)

    # 1) _write_selected: related_links من cluster_members (دون الرئيسي، حدّ 3)
    art = Article(title="خبر لاختبار الروابط ذات الصلة", link="https://m.example/main",
                  summary="", source_name="M", region="r1", weight=1.0,
                  published=datetime.now(timezone.utc), bucket="serious", publisher="M")
    art.cluster_members = [
        {"name": "M", "link": "https://m.example/main"},
        {"name": "A", "link": "https://a.example/1"},
        {"name": "A2", "link": "https://a.example/1"},
        {"name": "B", "link": "https://b.example/2"},
        {"name": "C", "link": "https://c.example/3"},
        {"name": "D", "link": "https://d.example/4"},
    ]
    cand = preselect.build_candidate(art)
    store.save_candidate(cand)
    rd = collect_finalize._write_selected(
        cand["id"], store.load_history(), 0.5, {}, {}, cfg, [])
    src_d = (rd or {}).get("source") or {}
    check("_write_selected: related_links = روابط العنقود دون الرئيسي ودون تكرار وبحدّ 3",
          src_d.get("related_links") == ["https://a.example/1", "https://b.example/2",
                                        "https://c.example/3"], src_d.get("related_links"))
    check("_write_selected: أسماء الناشرين موازية للروابط",
          src_d.get("related_publishers") == ["A", "B", "C"], src_d.get("related_publishers"))

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)


def test_decisions_unselected_then_rejected() -> None:
    """Issue #1153 (بند مؤجَّل من #1135): «unselected» السابق لا يمنع الرفض
    اللاحق للمعرّف نفسه؛ أي قيد آخر يبقى مانعًا."""
    from src import decisions

    if decisions.DECISIONS_FILE.exists():
        decisions.DECISIONS_FILE.unlink()
    cand = {"id": "g1153", "created_at": datetime.now(timezone.utc).isoformat(),
            "selection_issue": 7, "article": {}, "publishers": ["A"]}
    decisions.record_unselected(cand)
    draft = {"id": "g1153", "created_at": cand["created_at"], "status": "pending",
             "source": {"publishers": ["A"]}, "arabic": {}}
    decisions.record_rejected_unchecked(draft)
    kinds = [e["decision"] for e in decisions.load() if e["id"] == "g1153"]
    check("سجل القرارات (g): unselected ثم rejected_unchecked ⇒ القيدان موجودان",
          kinds == ["unselected", "rejected_unchecked"], kinds)
    decisions.record_rejected_unchecked(draft)
    decisions.record_rejected(draft, "ضعيف")
    kinds = [e["decision"] for e in decisions.load() if e["id"] == "g1153"]
    check("سجل القرارات (g): rejected_unchecked يبقى مانعًا لما بعده",
          kinds == ["unselected", "rejected_unchecked"], kinds)
    d2 = dict(draft, id="g1153b")
    decisions.record_unselected(dict(cand, id="g1153b"))
    decisions.record_rejected(d2, "ضعيف")
    kinds = [e["decision"] for e in decisions.load() if e["id"] == "g1153b"]
    check("سجل القرارات (g): unselected ثم rejected_explicit ⇒ القيدان موجودان",
          kinds == ["unselected", "rejected_explicit"], kinds)
    d3 = dict(draft, id="g1153c")
    decisions.record_published(d3)
    decisions.record_rejected(d3, "ضعيف")
    check("سجل القرارات (g): published يبقى مانعًا للرفض",
          [e["decision"] for e in decisions.load() if e["id"] == "g1153c"] == ["published"])


def test_title_kashida_1165() -> None:
    """Issue #1165: ضبط عنوان البطاقة بالمدّ على مخرَج الأنبوب — بطاقات تُبنى
    فعليًا عبر cards.ensure بصورة تُولَّد هنا (لا ملف من drafts/). كل سطر عدا
    الأخير يلتصق بحدّي منطقة العنوان، والأخير محاذى لليمين بلا مدّ، والمدّ على
    الصورة وحدها (نص المسودة المحفوظ خالٍ من ـ)."""
    from src import cards

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    W = int(cfg.path("image.width", 1080))
    margin = int(W * 0.06)
    algeria = "الجزائر تقرّ الإعدام لمفتعلي حرائق الغابات"
    photo = Image.new("RGB", (1600, 1200), (60, 90, 160))
    real_dl, real_raqm = imaging.download_image, imaging.HAS_RAQM
    tat = "ـ"

    def build(id_, headline, cfg_=None, raqm=True):
        draft = {
            "id": id_, "status": "pending", "origin": "news", "bucket": "serious",
            "arabic": {"post_title": headline, "category": "سياسة", "urgent": False},
            "caption": "متن", "source": {"publishers": ["الجزيرة"]},
        }
        path = store.save_draft(draft)
        imaging.download_image = lambda *a, **k: photo.copy()
        imaging.HAS_RAQM = real_raqm and raqm
        try:
            rel = cards.ensure(path, draft, cfg_ or cfg, check_headline_limit=False,
                               image_urls=["https://cdn.example/ok.jpg"],
                               allow_search_fallback=False)
        finally:
            imaging.download_image, imaging.HAS_RAQM = real_dl, real_raqm
        with Image.open(DRAFTS_DIR / Path(rel).relative_to("drafts")) as built:
            return built.convert("RGB"), json.loads(Path(path).read_text(encoding="utf-8"))

    def ink_cols(im, plan, i, lo=235):
        """أعمدة الحبر الأبيض في صندوق السطر i: (أقصى يسار، أقصى يمين)."""
        top = plan["block_top"] + i * plan["line_h"]
        cols = [x for x in range(W) for y in range(top, top + plan["line_h"], 2)
                if min(im.getpixel((x, y))) >= lo]
        return (min(cols), max(cols)) if cols else (None, None)

    plan = card_plan(cfg, algeria, ["سياسة"])
    check("(#1165) عنوان الجزائر سطران بالحجم النهائي", len(plan["lines"]) == 2,
          plan["lines"])
    for name, raqm in (("Raqm", True), ("الاحتياطي بلا Raqm", False)):
        if raqm and not real_raqm:
            continue
        im, _ = build("kg" + ("1" if raqm else "2") + "00000001", algeria, raqm=raqm)
        imaging.HAS_RAQM = real_raqm and raqm
        try:
            plan_r = card_plan(cfg, algeria, ["سياسة"])
        finally:
            imaging.HAS_RAQM = real_raqm
        l0, r0 = ink_cols(im, plan_r, 0)
        l1, _ = ink_cols(im, plan_r, 1)
        check("(#1165-a/f) %s: السطر الأول يلامس حدّي المنطقة ±3" % name,
              l0 is not None and abs(l0 - margin) <= 3 and abs(r0 - (W - margin)) <= 3,
              (l0, r0, margin, W - margin))
        check("(#1165-a) %s: السطر الثاني لا يلامس الحدّ الأيسر" % name,
              l1 is not None and l1 > l0 + 2, (l1, l0))

    # b) المواضع وk المتساوي — على نفس خط البطاقة
    d = ImageDraw.Draw(Image.new("RGB", (W, 10)))
    jl = imaging.justify_line(d, plan["lines"][0], plan["font"], W - 2 * margin)
    k = jl["k"] if jl else 0
    check("(#1165-b) المدّ: الجزائر بين ئ/ر، تقرّ بين ق/ر، الإعدام بين ع/د، وk متساوٍ",
          jl is not None and k >= 1
          and jl["words"] == ["الجزائ" + tat * k + "ر", "تق" + tat * k + "رّ",
                              "الإع" + tat * k + "دام"],
          jl and jl["words"])
    check("(#1165-b) المدّ بعد الشدّة التابعة لحرفها لا قبلها",
          imaging.kashida_word("بَّر", 2) == "بَّ" + tat * 2 + "ر",
          imaging.kashida_word("بَّر", 2))
    # c) لام-ألف ولاتيني
    check("(#1165-c) لا مدّ بين اللام والألف: «السلام» لا يصبح «السلـام»",
          "ل" + tat not in imaging.kashida_word("السلام", 3)
          and tat + "ا" not in imaging.kashida_word("السلام", 3)
          and imaging.kashida_word("السلام", 3) != "السلام",
          imaging.kashida_word("السلام", 3))
    check("(#1165-c) لا مدّ في كلمة لاتينية ولا في أرقام",
          imaging.kashida_slot("Trump") is None and imaging.kashida_slot("2025") is None)
    # d) سطر واحد
    short = "عنوان قصير"
    p_short = card_plan(cfg, short, ["سياسة"])
    im_s, _ = build("kg300000001", short)
    l_s, r_s = ink_cols(im_s, p_short, 0)
    check("(#1165-d) عنوان من سطر واحد: لا مدّ، محاذى لليمين ولا يلامس الحدّ الأيسر",
          len(p_short["lines"]) == 1 and l_s > margin + 100
          and r_s >= W - margin - 12, (p_short["lines"], l_s, r_s))
    # e) المسودة المحفوظة
    _, saved = build("kg400000001", algeria)
    check("(#1165-e) نص العنوان المحفوظ في المسودة خالٍ من ـ",
          tat not in json.dumps(saved, ensure_ascii=False)
          and saved["arabic"]["post_title"] == algeria, saved["arabic"]["post_title"])
    # g) الإيقاف
    cfg_off = load_config()
    cfg_off["image"]["title_justify"] = False
    im_off, _ = build("kg500000001", algeria, cfg_=cfg_off)
    l_off, _ = ink_cols(im_off, plan, 0)
    check("(#1165-g) title_justify=false: السطر الأول لا يلامس الحدّ الأيسر (محاذاة لليمين)",
          l_off > margin + 20, (l_off, margin))


@auto_restore_last_publish
def test_card_swap_1167() -> None:
    """Issue #1167 على مخرَج الأنبوب (cards.ensure بصور تُولَّد هنا): (أ) التاريخ
    في ربع الشريط العلوي الأيسر والمعرّف أبيض في ربع السفلي الأيسر ويُقرأ «@…»،
    (ب) شارة التصنيف #E4B030، (ج) الحبر الأيمن لكل أسطر العنوان (ومنها الأخير)
    عند W−margin ±2 مع title_justify صحيحًا وخاطئًا، (د) سطر المصدر لا يتداخل
    مع المعرّف لثلاثة ناشرين طويلي الأسماء."""
    from src import cards

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()
    W, H = 1080, 1350
    bar, margin = int(W * 0.082), int(W * 0.06)
    grad = Image.new("RGB", (1600, 1200), (90, 110, 150))
    real_dl = imaging.download_image
    counter = [0]

    def build(headline, justify=True, urgent=False, publishers=("Axios",)):
        counter[0] += 1
        cfg = load_config()
        cfg["image"]["title_justify"] = justify
        draft = {"id": f"sw00000000{counter[0]:02d}", "status": "pending",
                 "origin": "news", "bucket": "serious",
                 "arabic": {"post_title": headline, "category": "سياسة", "urgent": urgent},
                 "caption": "متن", "source": {"publishers": list(publishers)}}
        path = store.save_draft(draft)
        imaging.download_image = lambda *a, **k: grad.copy()
        try:
            rel = cards.ensure(path, draft, cfg, check_headline_limit=False,
                               image_urls=["https://cdn.example/ok.jpg"],
                               allow_search_fallback=False)
        finally:
            imaging.download_image = real_dl
        with Image.open(DRAFTS_DIR / Path(rel).relative_to("drafts")) as built:
            return built.convert("RGB"), cfg

    def ink_cols(img, y0, y1, x0, x1, pred):
        xs = [x for x in range(x0, x1) for y in range(y0, y1, 2)
              if pred(img.getpixel((x, y)))]
        return (min(xs), max(xs)) if xs else None

    head = "واشنطن تنشر صواريخ باتريوت لحماية منشآت نفطية سعودية وقطرية"
    ltr_log: list = []
    real_ltr = imaging.draw_text_ltr
    imaging.draw_text_ltr = lambda d, xy, t, *a, **k: (
        ltr_log.append(t), real_ltr(d, xy, t, *a, **k))[1]
    try:
        im, cfg = build(head, publishers=("Axios", "The Express Tribune"))
    finally:
        imaging.draw_text_ltr = real_ltr
    primary = imaging.hex_rgb(cfg.path("brand.primary_color"))
    footer_bg = imaging.mix(primary, (0, 0, 0), 0.28)
    far = lambda px, bg: max(abs(a - b) for a, b in zip(px, bg)) > 40
    white = lambda p: all(c >= 235 for c in p)

    # (أ) التاريخ علويًا يسارًا، والمعرّف سفليًا يسارًا بالأبيض
    date_ink = ink_cols(im, 10, bar - 10, 0, W // 2, lambda p: far(p, primary))
    check("(#1167-أ) التاريخ في الربع الأيسر من الشريط العلوي",
          date_ink is not None and date_ink[1] < W // 4 + margin, date_ink)
    ft = H - bar
    h_ink = ink_cols(im, ft + 8, H - 8, 0, W, white)
    check("(#1167-أ) المعرّف بحبر أبيض في الربع الأيسر من الشريط السفلي",
          h_ink is not None and h_ink[1] < W // 4 + margin, h_ink)
    check("(#1167-أ) لا حبر أبيض في الشريط العلوي (المعرّف انتقل إلى السفلي)",
          ink_cols(im, 10, bar - 10, 0, W // 2, white) is None, None)
    check("(#1167-أ) المعرّف يُرسم LTR فيُقرأ «@almujez» لا «almujez@»",
          ltr_log == ["@almujez"], ltr_log)

    # (ب) لون شارة التصنيف
    check("(#1167-ب) brand.accent_color = #E4B030",
          cfg.path("brand.accent_color") == "#E4B030", cfg.path("brand.accent_color"))
    b = card_plan(cfg, head, ["سياسة"])["badges"][0]
    px = im.getpixel((b["x0"] + 12, (b["y0"] + b["y1"]) // 2))
    check("(#1167-ب) شارة التصنيف مرسومة بـ#E4B030",
          all(abs(a - c) <= 8 for a, c in zip(px, (0xE4, 0xB0, 0x30))), px)

    # (ج) الحبر الأيمن لكل سطر عند W−margin ±2
    for cur, label in ((head, "سطران"), ("عنوان قصير", "سطر واحد")):
        for just in (True, False):
            img, c = build(cur, justify=just)
            p = card_plan(c, cur, ["سياسة"])
            edges = []
            for i in range(len(p["lines"])):
                y0 = p["block_top"] + i * p["line_h"]
                ink = ink_cols(img, y0 + p["line_h"] // 4, y0 + p["line_h"] * 3 // 4,
                               0, W, lambda q: all(v >= 225 for v in q))
                edges.append(ink[1] if ink else None)
            check(f"(#1167-ج) [{label}، justify={just}] الحبر الأيمن لكل الأسطر عند W−margin ±2",
                  bool(edges) and all(e is not None and abs(e - (W - margin)) <= 2
                                      for e in edges), (edges, W - margin))
            if cur == head and just:
                check("(#1167-ج) شرط الاختبار: عنوان باتريوت يلتف على سطرين فأكثر",
                      len(p["lines"]) >= 2, p["lines"])

    # (د) سطر المصدر لا يتداخل مع المعرّف لثلاثة ناشرين طويلي الأسماء
    longs = ("The Express Tribune Pakistan Edition", "Middle East Monitor Daily",
             "Al-Quds Al-Arabi International")
    img3, _ = build(head, publishers=longs)
    h3 = ink_cols(img3, ft + 8, H - 8, 0, W // 4 + margin, white)
    src = ink_cols(img3, ft + 8, H - 8, W // 3, W,
                   lambda q: far(q, footer_bg) and not white(q))
    check("(#1167-د) سطر المصدر يبدأ يمين نهاية المعرّف بفاصل",
          h3 is not None and src is not None and src[0] > h3[1] + 10, (h3, src))


def _stage_news_draft(id_: str, title: str, *, urgent: bool = False,
                      image: str | None = None, **extra) -> dict:
    return {
        "id": id_, "status": "pending", "score": 5.0, "bucket": "serious",
        "state_media": False, "origin": "news",
        "caption": f"{title}\nمتن الخبر.",
        "source": {"link": f"https://x/{id_}", "publishers": ["BBC"],
                   "image_candidates": ["https://cdn.example/ok.jpg"]},
        "arabic": {"post_title": title, "category": "", "urgent": urgent},
        **({"image": image} if image else {}), **extra,
    }


@auto_restore_last_publish
def test_stages_2_3_pipeline() -> None:
    """Issue #1182 (المهمة 2أ): قضايا المرحلتين 2 و3 تُبنى بالبانيين الحقيقيين،
    تُعلَّم مربعاتها، ثم تُمرَّر إلى المستهلكين الحقيقيين (publish/setimage)
    بالـfakes القائمة، ويُفحص أثرها على المسودات والسجل والقضايا المفتوحة."""
    from src import decisions, feedback
    from src import publish as publish_mod
    import src.setimage as setimage_mod

    cfg = load_config()
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()
    if decisions.DECISIONS_FILE.exists():
        decisions.DECISIONS_FILE.unlink()

    def run_publish(body: str, label: str, argv: list[str]) -> dict:
        """publish.main على قضية وهمية بالوسم المعطى؛ يعيد ما التُقط."""
        out = {"comments": [], "created": [], "published": [], "closed": []}
        # بوابة الفاصل (#1010) تؤجّل غير العاجل بعد نشر سابق في الاختبار نفسه؛
        # كل تشغيل هنا يحاكي قضية مستقلة، فيبدأ بلا «آخر نشر».
        reset_last_publish()
        real = {k: getattr(m, k) for m, k in (
            (publish_mod, "fetch_issue"), (publish_mod, "ROOT"),
            (facebook, "publish_photo"), (review, "comment"),
            (review, "close_issue"), (review, "create_issue"),
            (review, "ensure_labels"), (review, "remove_label"))}
        publish_mod.ROOT = DRAFTS_DIR.parent
        publish_mod.fetch_issue = lambda n: {
            "number": n, "body": body, "labels": [{"name": label}]}
        facebook.publish_photo = lambda image_path, caption, api_version, first_comment=None: (
            out["published"].append(caption) or {"url": "https://fb.example/s", "id": "1"})
        review.comment = lambda n, t: out["comments"].append((n, t))
        review.close_issue = lambda n: out["closed"].append(n)
        review.ensure_labels = lambda: None
        review.remove_label = lambda n, lbl: None

        def fake_create_issue(title, body, labels=None):
            out["created"].append({"title": title, "body": body, "labels": labels})
            return {"number": 9700 + len(out["created"]), "html_url": "https://x/i"}
        review.create_issue = fake_create_issue
        real_repo = os.environ.get("GITHUB_REPOSITORY")
        os.environ["GITHUB_REPOSITORY"] = "user/trendnews"
        sys.argv = ["publish", "--issue", "8200", *argv]
        try:
            out["code"] = publish_mod.main()
        finally:
            publish_mod.fetch_issue = real["fetch_issue"]
            publish_mod.ROOT = real["ROOT"]
            facebook.publish_photo = real["publish_photo"]
            review.comment = real["comment"]
            review.close_issue = real["close_issue"]
            review.create_issue = real["create_issue"]
            review.ensure_labels = real["ensure_labels"]
            review.remove_label = real["remove_label"]
            if real_repo is None:
                os.environ.pop("GITHUB_REPOSITORY", None)
            else:
                os.environ["GITHUB_REPOSITORY"] = real_repo
        return out

    def state(draft_id: str) -> dict:
        return store.load_draft(draft_id)[1]

    # ── المرحلة 2: a publish · b go3 · c go3+publish · d بلا تعليم ──
    d_pub = _stage_news_draft("e1820000000a", "خبر ينشر")
    d_go3 = _stage_news_draft("e1820000000b", "خبر إلى البطاقة")
    d_both = _stage_news_draft("e1820000000c", "خبر بتعارض")
    d_none = _stage_news_draft("e1820000000d", "خبر بلا تعليم")
    for d in (d_pub, d_go3, d_both, d_none):
        store.save_draft(d)
    body2 = review.build_issue_body([d_pub, d_go3, d_both, d_none], "u/r", "main")
    body2 = tick_marker(body2, f"<!-- go:publish:{d_pub['id']} -->")
    body2 = tick_marker(body2, f"<!-- go:go3:{d_go3['id']} -->")
    body2 = tick_marker(body2, f"<!-- go:go3:{d_both['id']} -->")
    body2 = tick_marker(body2, f"<!-- go:publish:{d_both['id']} -->")
    res = run_publish(body2, "approved", ["--now"])
    check("(#1182-أ) المرحلة 2: publish ← المسودة تُنشر كما كان draft: وحده",
          res["code"] == 0 and state(d_pub["id"])["status"] == "published"
          and res["published"] == [d_pub["caption"]], (res["code"], res["published"]))
    check("(#1182-ب) المرحلة 2: go3 ← بطاقة مبنيّة، بقيت pending، وفي قضية المرحلة 3",
          state(d_go3["id"])["status"] == "pending" and bool(state(d_go3["id"]).get("image"))
          and len(res["created"]) == 1
          and res["created"][0]["labels"] == ["final-review"]
          and f"<!-- draft:{d_go3['id']} -->" in res["created"][0]["body"],
          [(c["title"], c["labels"]) for c in res["created"]])
    check("(#1182-ج) تعارض go3+publish ← go3 (لا نشر) والمسودة في قضية المرحلة 3",
          state(d_both["id"])["status"] == "pending"
          and f"<!-- draft:{d_both['id']} -->" in res["created"][0]["body"],
          state(d_both["id"]).get("status"))
    conflict_notes = [t for n, t in res["comments"] if "أكثر من خيار انتقال" in t]
    check("(#1182-ج) تنبيه تعارض واحد يذكر الخبر والمعلَّمات",
          len(conflict_notes) == 1 and "خبر بتعارض" in conflict_notes[0]
          and cfg.path("stages.options.go3") in conflict_notes[0]
          and cfg.path("stages.options.publish") in conflict_notes[0]
          and "خبر ينشر" not in conflict_notes[0], conflict_notes)
    check("(#1182-د) المرحلة 2 بلا تعليم ← rejected_unchecked",
          state(d_none["id"])["status"] == "rejected"
          and any(e["id"] == d_none["id"] and e["decision"] == "rejected_unchecked"
                  for e in decisions.load())
          and any(e.get("tag") == "لم يُعتمد" for e in feedback.load()),
          state(d_none["id"]).get("status"))

    # ── المرحلة 3: e publish · go2 ← back · غير معلَّم ← رفض ──
    stage3 = []
    for n, title in (("1", "نهائي ينشر"), ("2", "نهائي يعود"), ("3", "نهائي لم يُعلَّم")):
        d = _stage_news_draft(f"e18200000f{n}", title, image=f"drafts/s3{n}.jpg",
                              image_info={"used_original": True},
                              review_issue=9999)
        store.save_draft(d)
        (DRAFTS_DIR / f"s3{n}.jpg").write_bytes(b"\xff\xd8\xff")
        stage3.append(d)
    body3 = review.build_final_review_body(stage3, "u/r", "main")
    body3 = tick_marker(body3, f"<!-- go:publish:{stage3[0]['id']} -->")
    body3 = tick_marker(body3, f"<!-- go:go2:{stage3[1]['id']} -->")
    res3 = run_publish(body3, "final-review", ["--now"])
    check("(#1182-هـ) المرحلة 3: publish ← نشر",
          state(stage3[0]["id"])["status"] == "published"
          and res3["published"] == [stage3[0]["caption"]], res3["published"])
    back = state(stage3[1]["id"])
    check("(#1182-هـ) المرحلة 3: go2 ← عودة إلى المرحلة 2 كما كان back:",
          back["status"] == "pending" and "image" not in back
          and "review_issue" not in back, back)
    check("(#1182-هـ) المرحلة 3: غير المعلَّم ← مرفوض",
          state(stage3[2]["id"])["status"] == "rejected")

    # ── و: رابط في حقل الصورة بلا أي مربع ← setimage يطبّقه ويمسح الحقل ──
    d_img = _stage_news_draft("e1820000001f", "خبر بحقل صورة")
    store.save_draft(d_img)
    body_img = review.build_issue_body([d_img], "u/r", "main")
    field = stages.image_field(d_img["id"], cfg)
    check("(#1182-و) حقل الصورة في القضية المبنيّة بلا مربع",
          field in body_img and f"<!-- img:{d_img['id']} -->" not in body_img)
    pasted = body_img.replace(field, field.replace("هنا:", "هنا: https://cdn.example/new.jpg"))
    sync_path = _TMP_DATA_DIR / "stages_2_3_sync.json"
    real_sync_file = setimage_mod.SYNC_FILE
    setimage_mod.SYNC_FILE = sync_path
    real_fetch_body = review.fetch_issue_body
    real_update = review.update_issue_body
    real_comment = review.comment
    updated: list = []
    review.fetch_issue_body = lambda n: pasted
    review.update_issue_body = lambda n, b: updated.append(b)
    review.comment = lambda n, t: None
    try:
        sys.argv = ["setimage", "--from-issue", "--issue", "8201", "--body", ""]
        code_img = setimage_mod.main()
        setimage_mod.sync_issue(8201)
        # نص غير رابط في الحقل: لا شيء يُطبَّق
        review.fetch_issue_body = lambda n: body_img.replace(
            field, field.replace("هنا:", "هنا: صورة جميلة"))
        sys.argv = ["setimage", "--from-issue", "--issue", "8202", "--body", ""]
        code_text = setimage_mod.main()
    finally:
        setimage_mod.SYNC_FILE = real_sync_file
        review.fetch_issue_body = real_fetch_body
        review.update_issue_body = real_update
        review.comment = real_comment
        sync_path.unlink(missing_ok=True)
    check("(#1182-و) رابط في الحقل بلا مربع ← setimage يطبّقه (manual_image)",
          code_img == 0 and state(d_img["id"]).get("manual_image")
          == "https://cdn.example/new.jpg", state(d_img["id"]).get("manual_image"))
    check("(#1182-و) وبعد التطبيق يُمسح الحقل ويعود نصّه",
          bool(updated) and "new.jpg" not in updated[-1] and field in updated[-1],
          updated[-1][-400:] if updated else None)
    check("(#1182-و) نص غير رابط في الحقل ← لا شيء (لا أمر صالح)", code_text == 2, code_text)

    # ── ز: قضايا مبنية بالباني القديم (نص ثابت منسوخ) ──
    l_pub, l_card, l_card_only, l_none = (
        _stage_news_draft(f"e18200000a{n}", f"قديم {n}") for n in "1234")
    for d in (l_pub, l_card, l_card_only, l_none):
        store.save_draft(d)
    legacy2 = legacy_stage2_body([(d["id"], d["arabic"]["post_title"])
                                  for d in (l_pub, l_card, l_card_only, l_none)])
    legacy2 = tick_marker(legacy2, f"draft:{l_pub['id']}")
    legacy2 = tick_marker(legacy2, f"draft:{l_card['id']}")
    legacy2 = tick_marker(legacy2, f"card:{l_card['id']}")
    legacy2 = tick_marker(legacy2, f"card:{l_card_only['id']}")
    resl = run_publish(legacy2, "approved", ["--now"])
    check("(#1182-ز) قديم المرحلة 2: draft وحده ← نُشر",
          state(l_pub["id"])["status"] == "published"
          and resl["published"] == [l_pub["caption"]], resl["published"])
    check("(#1182-ز) قديم المرحلة 2: draft+card ← قضية مرحلة 3 بلا نشر",
          state(l_card["id"])["status"] == "pending"
          and len(resl["created"]) == 1
          and f"<!-- draft:{l_card['id']} -->" in resl["created"][0]["body"])
    check("(#1182-ز) قديم المرحلة 2: card وحده بلا draft ← مرفوض كغير معلَّم",
          state(l_card_only["id"])["status"] == "rejected"
          and state(l_none["id"])["status"] == "rejected")
    check("(#1182-ز) قديم: لا تنبيه تعارض (لا تعارض في الترجمة القديمة)",
          not [t for n, t in resl["comments"] if "أكثر من خيار" in t])

    old3 = []
    for n, title in (("1", "قديم نهائي ينشر"), ("2", "قديم نهائي يعود"),
                     ("3", "قديم يجمع ✔️ و↩️"), ("4", "قديم لم يُعلَّم")):
        d = _stage_news_draft(f"e18200000b{n}", title, image=f"drafts/l3{n}.jpg",
                              image_info={"used_original": True}, review_issue=9998)
        store.save_draft(d)
        (DRAFTS_DIR / f"l3{n}.jpg").write_bytes(b"\xff\xd8\xff")
        old3.append(d)
    legacy3 = legacy_stage3_body([(d["id"], d["arabic"]["post_title"]) for d in old3])
    legacy3 = tick_marker(legacy3, f"draft:{old3[0]['id']}")
    legacy3 = tick_marker(legacy3, f"back:{old3[1]['id']}")
    legacy3 = tick_marker(legacy3, f"draft:{old3[2]['id']}")
    legacy3 = tick_marker(legacy3, f"back:{old3[2]['id']}")
    resl3 = run_publish(legacy3, "final-review", ["--now"])
    check("(#1182-ز) قديم المرحلة 3: draft ← نشر",
          state(old3[0]["id"])["status"] == "published")
    check("(#1182-ز) قديم المرحلة 3: back ← عودة، وback يغلب draft",
          all(state(d["id"])["status"] == "pending" and "image" not in state(d["id"])
              for d in old3[1:3]))
    check("(#1182-ز) قديم المرحلة 3: غير المعلَّم ← مرفوض",
          state(old3[3]["id"])["status"] == "rejected")
    legacy_img = legacy_stage2_body([("e18200000c1", "قديم")]).replace(
        "- [ ] 🖼️", "- [x] 🖼️").replace(
        "الرابط:   <!--", "الرابط: https://cdn.example/old.jpg  <!--")
    check("(#1182-ز) قديم: img: معلَّم + imgurl ← يُنفَّذ كما كان",
          review.parse_image_requests(legacy_img)
          == [("e18200000c1", "https://cdn.example/old.jpg")])

    # ── ح: مسودة عاجلة ──
    urgent = _stage_news_draft("e18200000d1", "خبر عاجل", urgent=True)
    normal = _stage_news_draft("e18200000d2", "خبر عادي بجانبه")
    for d in (urgent, normal):
        store.save_draft(d)
    body_u = review.build_issue_body([urgent, normal], "u/r", "main")
    urgent_text = "🚀 انشر فورًا (عاجل: بلا انتظار)"
    urgent_lines = [ln for ln in body_u.splitlines()
                    if f"go:publish:{urgent['id']}" in ln]
    normal_lines = [ln for ln in body_u.splitlines()
                    if f"go:publish:{normal['id']}" in ln]
    check("(#1182-ح) المسودة العاجلة ← «🚀 انشر فورًا (عاجل: بلا انتظار)»",
          len(urgent_lines) == 1 and urgent_text in urgent_lines[0], urgent_lines)
    check("(#1182-ح) المسودة العادية ← «🚀 انشر فورًا» بلا لاحقة العاجل",
          len(normal_lines) == 1 and "عاجل" not in normal_lines[0], normal_lines)
    check("(#1182-ح) قضية المرحلة 3 لعاجل تحمل النص نفسه",
          urgent_text in review.build_final_review_body([urgent], "u/r", "main"))
    body_u = tick_marker(body_u, f"<!-- go:publish:{urgent['id']} -->")
    body_u = tick_marker(body_u, f"<!-- go:publish:{normal['id']} -->")
    res_u = run_publish(body_u, "approved", ["--urgent-only"])
    check("(#1182-ح) job urgent: العاجل يُنشر بلا انتظار، والعادي لا يُنشر فيه",
          state(urgent["id"])["status"] == "published"
          and state(normal["id"])["status"] == "pending"
          and res_u["published"] == [urgent["caption"]], res_u["published"])
    res_n = run_publish(body_u, "approved", ["--skip-urgent", "--now"])
    check("(#1182-ح) job العادي بعدها ينشر العادي ولا يعيد العاجل",
          state(normal["id"])["status"] == "published"
          and res_n["published"] == [normal["caption"]], res_n["published"])

    # ── ط/ي: بلا go1، وترتيب الأقسام ──
    full = _stage_news_draft(
        "e18200000e1", "خبر كامل الأقسام", image="drafts/full.jpg",
        headlines=["عنوان ١", "عنوان ٢"], headline_selected=0,
        reel_spec={"headline": "ع"}, sibling_id="e18200000e2",
        has_photo=False)
    full2 = _stage_news_draft("e18200000e2", "خبر عاجل ثانٍ", urgent=True)
    final_body = review.build_final_review_body([full, full2], "u/r", "main")
    issue_body = review.build_issue_body([full, full2], "u/r", "main")
    # Issue #1184 (المهمة 2ب، البند أ): مسودات الأخبار تحمل الآن سطر go1 في
    # المرحلتين؛ غير الأخبار (الأصل ≠ news) لا تحمله. كان الفحص السابق «لا
    # go1 لأي قضية» (has_stage1=False مؤقتًا) وانتهى أجله بهذه المهمة.
    check("(#1182-ط/#1184-أ) سطر go1 لكل خبر أخبار في المرحلتين",
          f"go:go1:{full['id']}" in issue_body and f"go:go1:{full2['id']}" in issue_body
          and f"go:go1:{full['id']}" in final_body and f"go:go1:{full2['id']}" in final_body,
          issue_body[-600:])
    non_news = [dict(full, origin=o) for o in ("breaking", "request", "article", "analysis")]
    check("(#1182-ط/#1184-أ) بلا سطر go1 لمسودة رادار/طلب/مقال/تحليل",
          all("go:go1:" not in review.build_issue_body([d], "u/r", "main")
              and "go:go1:" not in review.build_final_review_body([d], "u/r", "main")
              for d in non_news))
    check("(#1182-ط) رأس المرحلتين من stages.stage_header وبلا الرأسين القديمين",
          issue_body.startswith(stages.stage_header(2, cfg))
          and final_body.startswith(stages.stage_header(3, cfg))
          and "مسودات بانتظار المراجعة" not in issue_body
          and "مراجعة نهائية قبل النشر" not in final_body)
    check("(#1182-ط) الشرح الموحَّد تحت الرأس في القضيتين، وملاحظة تحرير النص في المرحلة 2 فقط",
          cfg.path("stages.explainer") in issue_body and cfg.path("stages.explainer") in final_body
          and "حرّر هذا الـIssue واكتب داخل كتلة النص" in issue_body
          and "حرّر هذا الـIssue واكتب داخل كتلة النص" not in final_body)

    def first(lines: list[str], needle: str, start: int = 0) -> int:
        return next((i for i in range(start, len(lines)) if needle in lines[i]), -1)

    lines2 = issue_body.splitlines()
    start = first(lines2, f"<!-- draft:{full['id']} -->")
    end = first(lines2, f"<!-- draft:{full2['id']} -->")
    sect = lines2[start:end]
    pos = [first(sect, n) for n in (
        "**1. خبر كامل الأقسام**", "<img", "<details>", "hl:" + full["id"],
        "imgurl:" + full["id"], "go:go3:" + full["id"])]
    check("(#1182-ي) ترتيب أقسام الخبر في المرحلة 2: العنوان ← الصورة ← النص ← العناوين "
          "← حقل الصورة ← الانتقال (الريل القديم أُزيل في #1336)", -1 not in pos and pos == sorted(pos), pos)
    check("(#1182-ي) لا سطر «- [ ]» قبل سطر عنوان الخبر الأول",
          not any(re.match(r"\s*[-*]\s*\[", ln) for ln in lines2[:start]))
    check("(#1182-ي) لا سطر «- [ ]» بين بداية الخبر وسطر عنوانه",
          not re.match(r"\s*[-*]\s*\[", lines2[start]))
    lines3 = final_body.splitlines()
    s3 = first(lines3, f"<!-- draft:{full['id']} -->")
    e3 = first(lines3, f"<!-- draft:{full2['id']} -->")
    sect3 = lines3[s3:e3]
    pos3 = [first(sect3, n) for n in (
        "**1. خبر كامل الأقسام**", "<img", "<details>", "imgurl:" + full["id"],
        "go:publish:" + full["id"])]
    check("(#1182-ي) ترتيب أقسام الخبر في المرحلة 3: العنوان ← الصورة ← النص ← حقل الصورة "
          "← الانتقال", -1 not in pos3 and pos3 == sorted(pos3), pos3)
    check("(#1182-ي) لا سطر «- [ ]» قبل سطر عنوان الخبر الأول في المرحلة 3",
          not any(re.match(r"\s*[-*]\s*\[", ln) for ln in lines3[:s3]))
    check("(#1182-ي) المرحلة 2 بلا خيار المرحلة 2، والمرحلة 3 بلا خيار المرحلة 3",
          "go:go2:" not in issue_body and "go:go3:" not in final_body)


def legacy_stage2_body(items: list[tuple[str, str]]) -> str:
    """نص ثابت منسوخ من review.build_issue_body قبل Issue #1182: مربع draft:
    على العنوان ثم 🎴 card: ثم img:/imgurl: — قضية مفتوحة قبل التحديث."""
    parts = ["### 📋 مسودات بانتظار المراجعة", ""]
    for idx, (draft_id, title) in enumerate(items, start=1):
        parts += [
            f"- [ ] **{idx}. {title}**  <!-- draft:{draft_id} -->", "",
            f"  - [ ] 🎴 اعرض البطاقة قبل النشر  <!-- card:{draft_id} -->", "",
            f"  - [ ] 🖼️ استبدل الصورة بالرابط أدناه  <!-- img:{draft_id} -->", "",
            f"    الرابط:   <!-- imgurl:{draft_id} -->", "",
            f"  - [ ] 🎬 انشره كريل بدل الصورة  <!-- reel:{draft_id} -->", "",
            "---", ""]       # كتلة cap محذوفة عمدًا: لا تعديل نص في الترجمة
    return "\n".join(parts)


def legacy_youtube_review_body(items: list[tuple[str, str]]) -> str:
    """نص ثابت منسوخ من youtube_publish.build_review_body قبل Issue #1187: مربع
    draft: على عنوان المقال ثم 🎴 card: ثم الشارات والعناوين hl: والنص — قضية
    youtube-review مفتوحة قبل التحديث."""
    parts = ["### 📰 مراجعة مقالات تحليلية من القنوات", "",
             "**1 مقالات · الكتل المتقاطعة: 1=1 · خلاف قنوات=0 · تنبيهات=0**", "",
             "**كيف تعتمد؟** ✔️ ضع علامة على المقالات التي توافق عليها، ثم أضف "
             "الوسم `approved` إلى هذا الـ Issue.", "", "---", ""]
    for idx, (draft_id, title) in enumerate(items, start=1):
        parts += [
            f"- [ ] **{idx}. {title}**  <!-- draft:{draft_id} -->", "",
            f"  - [ ] 🎴 اعرض البطاقة قبل النشر  <!-- card:{draft_id} -->", "",
            "  تقاطع 1 كتل · عربية · الجزيرة · اتفاق", "",
            "  الدرجة 1 — قناة واحدة · كتلة واحدة · اتفاق بين المصادر", "",
            "  🖼️ **المصدر:** البطاقة لم تُبنَ بعد — تُبنى عند الاعتماد", "",
            "  🏷️ **العناوين المقترحة** (علّم المختار، الأول افتراضي):", "",
            f"  - [x] 1. {title}  <!-- hl:{draft_id}:0 -->", "",
            "  <details><summary>📝 نص المقال كاملًا</summary>", "",
            f"  <!-- cap:{draft_id} -->", "  ```", "  متن المقال", "  ```",
            f"  <!-- /cap:{draft_id} -->", "", "  </details>", "", "---", ""]
    return "\n".join(parts)


def legacy_stage3_body(items: list[tuple[str, str]]) -> str:
    """نص ثابت منسوخ من review.build_final_review_body قبل Issue #1182."""
    parts = ["### 🎴 مراجعة نهائية قبل النشر", ""]
    for idx, (draft_id, title) in enumerate(items, start=1):
        parts += [
            f"- [ ] **{idx}. {title}**  <!-- draft:{draft_id} -->", "",
            f"  - [ ] 🖼️ استبدل الصورة بالرابط أدناه  <!-- img:{draft_id} -->", "",
            f"    الرابط:   <!-- imgurl:{draft_id} -->", "",
            f"  - [ ] ↩️ أعده للمراجعة الأولية  <!-- back:{draft_id} -->", "",
            "---", ""]
    return "\n".join(parts)


def _run_publish_issue(body: str, label: str, argv: list[str]) -> dict:
    """publish.main على قضية وهمية بالوسم المعطى؛ يعيد ما التُقط (تعليقات،
    قضايا مُنشأة، منشورات، إغلاقات). نسخة وحدة من مُشغِّل test_stages_2_3_pipeline."""
    from src import publish as publish_mod
    out = {"comments": [], "created": [], "published": [], "closed": []}
    reset_last_publish()
    real = {k: getattr(m, k) for m, k in (
        (publish_mod, "fetch_issue"), (publish_mod, "ROOT"),
        (facebook, "publish_photo"), (review, "comment"),
        (review, "close_issue"), (review, "create_issue"),
        (review, "ensure_labels"), (review, "remove_label"))}
    publish_mod.ROOT = DRAFTS_DIR.parent
    publish_mod.fetch_issue = lambda n: {"number": n, "body": body, "labels": [{"name": label}]}
    facebook.publish_photo = lambda image_path, caption, api_version, first_comment=None: (
        out["published"].append(caption) or {"url": "https://fb.example/s", "id": "1"})
    review.comment = lambda n, t: out["comments"].append((n, t))
    review.close_issue = lambda n: out["closed"].append(n)
    review.ensure_labels = lambda: None
    review.remove_label = lambda n, lbl: None

    def fake_create_issue(title, body, labels=None):
        out["created"].append({"title": title, "body": body, "labels": labels})
        return {"number": 9800 + len(out["created"]), "html_url": "https://x/i"}
    review.create_issue = fake_create_issue
    real_repo = os.environ.get("GITHUB_REPOSITORY")
    os.environ["GITHUB_REPOSITORY"] = "user/trendnews"
    sys.argv = ["publish", "--issue", "8300", *argv]
    try:
        out["code"] = publish_mod.main()
    finally:
        publish_mod.fetch_issue = real["fetch_issue"]
        publish_mod.ROOT = real["ROOT"]
        facebook.publish_photo = real["publish_photo"]
        review.comment = real["comment"]
        review.close_issue = real["close_issue"]
        review.create_issue = real["create_issue"]
        review.ensure_labels = real["ensure_labels"]
        review.remove_label = real["remove_label"]
        if real_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo
    return out


@auto_restore_last_publish
def test_stage1_return_pipeline() -> None:
    """Issue #1184 (المهمة 2ب): خيار go1 (عد إلى الترشيح) من المرحلتين 2 و3، بالبناة
    والمستهلكين الحقيقيين (publish.main، collect.drop_stale_candidates،
    open_review.main، collect_finalize.finalize)، مع عدّاد لنداءات الكاتب. ثم
    إصلاح رابط الصورة الفاشل في setimage (البند هـ)."""
    from src import cards, collect_finalize, decisions, preselect
    from src import publish as publish_mod
    import src.setimage as setimage_mod

    cfg = load_config()
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    shutil.rmtree(store.CANDIDATES_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()
    if decisions.DECISIONS_FILE.exists():
        decisions.DECISIONS_FILE.unlink()

    def state(draft_id: str) -> dict:
        return store.load_draft(draft_id)[1]

    def cand_state(cid: str) -> dict:
        return store.latest_candidate(cid)[1]

    def make_news(n: str, title: str, *, stage3: bool = False,
                  score: float = 1.0) -> tuple[dict, dict]:
        """مرشح (selected في قضية ترشيح قديمة) + مسودته المصوغة، بالمعرّف نفسه."""
        art = Article(title=title, link=f"https://ret.example/{n}", summary="",
                      source_name="P1", region="r1", weight=1.0,
                      published=datetime.now(timezone.utc), bucket="serious",
                      publisher="P1")
        cand = preselect.build_candidate(art)
        cand.update(status="selected", selection_issue=7000 + int(n), score=score)
        store.save_candidate(cand)
        extra = {"headlines": ["عنوان بديل ١", "عنوان بديل ٢", "عنوان بديل ٣"],
                 "headline_selected": 0, "reel_spec": {"headline": title}}
        if stage3:
            extra.update(image=f"drafts/r{n}.jpg", image_info={"used_original": True},
                         review_issue=9999)
            (DRAFTS_DIR / f"r{n}.jpg").write_bytes(b"\xff\xd8\xff")
        draft = _stage_news_draft(cand["id"], title, **extra)
        store.save_draft(draft)
        return cand, draft

    # عدّاد نداءات الكاتب والعناوين وبناء البطاقة — يُمرِّر للحقيقي كي لا يتغير السلوك
    calls = {"write": 0, "headlines": 0, "build": 0}
    real_write = collect_finalize.write_arabic
    real_hl = collect_finalize.headlines_mod.headlines_for_post
    real_build = cards._default_build_post_image

    def counting_write(*a, **k):
        calls["write"] += 1
        return real_write(*a, **k)

    def counting_hl(*a, **k):
        calls["headlines"] += 1
        return real_hl(*a, **k)

    def counting_build(*a, **k):
        calls["build"] += 1
        return real_build(*a, **k)

    def run_open_review() -> dict:
        out = {"created": []}
        real_create, real_labels = review.create_issue, review.ensure_labels

        def fake_create(title, body, labels=None):
            out["created"].append({"title": title, "body": body, "labels": labels})
            return {"number": 7500 + len(out["created"]), "html_url": "https://x/i"}
        review.create_issue = fake_create
        review.ensure_labels = lambda: None
        real_repo = os.environ.get("GITHUB_REPOSITORY")
        os.environ["GITHUB_REPOSITORY"] = "u/r"
        try:
            out["code"] = open_review.main()
        finally:
            review.create_issue, review.ensure_labels = real_create, real_labels
            if real_repo is None:
                os.environ.pop("GITHUB_REPOSITORY", None)
            else:
                os.environ["GITHUB_REPOSITORY"] = real_repo
        return out

    def run_finalize(number: int, body: str) -> dict:
        """finalize الحقيقية؛ cmd_burst تُحوَّل إلى cmd_now الحقيقية (نشر فعلي عبر
        publish_one) كي يكون «نُشر أم لا» حتميًا بلا نوم ولا جدولة."""
        out = {"comments": [], "created": [], "published": [], "closed": []}
        real = {k: getattr(m, k) for m, k in (
            (publish_mod, "ROOT"), (publish_mod, "cmd_burst"),
            (facebook, "publish_photo"), (review, "comment"),
            (review, "close_issue"), (review, "create_issue"),
            (review, "ensure_labels"))}
        publish_mod.ROOT = DRAFTS_DIR.parent
        publish_mod.cmd_burst = (lambda ids, cfg, issue, **kw:
                                 publish_mod.cmd_now(ids, cfg, issue))
        facebook.publish_photo = lambda image_path, caption, api_version, first_comment=None: (
            out["published"].append(caption) or {"url": "https://fb.example/s", "id": "1"})
        review.comment = lambda n, t: out["comments"].append((n, t))
        review.close_issue = lambda n: out["closed"].append(n)
        review.ensure_labels = lambda: None

        def fake_create(title, body, labels=None):
            out["created"].append({"title": title, "body": body, "labels": labels})
            return {"number": 7600 + len(out["created"]), "html_url": "https://x/i"}
        review.create_issue = fake_create
        real_repo = os.environ.get("GITHUB_REPOSITORY")
        os.environ["GITHUB_REPOSITORY"] = "u/r"
        reset_last_publish()
        try:
            out["code"] = collect_finalize.finalize(number, body, cfg)
        finally:
            publish_mod.ROOT, publish_mod.cmd_burst = real["ROOT"], real["cmd_burst"]
            facebook.publish_photo = real["publish_photo"]
            review.comment, review.close_issue = real["comment"], real["close_issue"]
            review.create_issue, review.ensure_labels = real["create_issue"], real["ensure_labels"]
            if real_repo is None:
                os.environ.pop("GITHUB_REPOSITORY", None)
            else:
                os.environ["GITHUB_REPOSITORY"] = real_repo
        return out

    collect_finalize.write_arabic = counting_write
    collect_finalize.headlines_mod.headlines_for_post = counting_hl
    cards._default_build_post_image = counting_build
    try:
        # ── أ: المرحلة 2، go1 ──
        cand_a, draft_a = make_news("1", "خبر المرحلة الثانية العائد", score=1.0)
        # نسخة أقدم للمرشح نفسه (ظهور سابق في قضية أخرى): لا تُحيا، الأحدث وحدها
        old_dir = store.CANDIDATES_DIR / "2020-01-01"
        old_dir.mkdir(parents=True, exist_ok=True)
        old_copy = dict(cand_a, created_at="2020-01-01T00:00:00+00:00",
                        selection_issue=6000, status="selected")
        (old_dir / f"{cand_a['id']}.json").write_text(
            json.dumps(old_copy, ensure_ascii=False), encoding="utf-8")
        body2 = review.build_issue_body([draft_a], "u/r", "main")
        go1_line = next((ln for ln in body2.splitlines()
                         if f"go:go1:{cand_a['id']}" in ln), "")
        check("(#1184-أ) قضية المرحلة 2 لخبر أخبار فيها خيار «↩️ عد إلى مرحلة ترشيح المواضيع المتاحة»",
              cfg.path("stages.options.go1") in go1_line and go1_line.lstrip().startswith("- [ ]"),
              go1_line)
        res = _run_publish_issue(tick_marker(body2, f"<!-- go:go1:{cand_a['id']} -->"),
                                 "approved", ["--now"])
        da, ca = state(cand_a["id"]), cand_state(cand_a["id"])
        check("(#1184-أ) go1 من المرحلة 2 ← المسودة returned بمرحلتها ولحظتها، بلا نشر",
              da["status"] == "returned" and da["returned_from_stage"] == 2
              and bool(da.get("returned_at")) and res["published"] == [], da.get("status"))
        check("(#1184-أ) نص المسودة وعناوينها محفوظة كما هي",
              da["caption"] == draft_a["caption"] and da["headlines"] == draft_a["headlines"]
              and da["arabic"]["post_title"] == draft_a["arabic"]["post_title"])
        check("(#1184-أ) المرشح (الأحدث وحده): pending بلا selection_issue وreturned ومرحلته",
              ca["status"] == "pending" and ca["selection_issue"] is None
              and ca["returned"] is True and ca["returned_from_stage"] == 2
              and bool(ca.get("returned_at")), ca)
        old_after = json.loads((old_dir / f"{cand_a['id']}.json").read_text(encoding="utf-8"))
        check("(#1184-أ) النسخة الأقدم للمرشح لا تُمسّ",
              old_after["status"] == "selected" and old_after["selection_issue"] == 6000,
              old_after)
        rec = [e for e in decisions.load() if e["id"] == cand_a["id"]]
        check("(#1184-أ) السجل: قرار «returned» بقضية الترشيح التي جاء منها ومرحلة العودة",
              len(rec) == 1 and rec[0]["decision"] == "returned"
              and rec[0].get("returned_from_stage") == 2
              and rec[0].get("selection_issue") == 7001, rec)
        check("(#1184-أ) returned لا تظهر في قوائم المراجعة/الإحياء/النشر/الطابور",
              cand_a["id"] not in [d["id"] for _, d in store.pending_drafts()]
              and cand_a["id"] not in [d["id"] for _, d in store.failed_drafts()]
              and cand_a["id"] not in [d["id"] for _, d in publish_mod.queued_drafts()]
              and cand_a["id"] not in [d["id"] for _, d in open_review._revivable_drafts()])
        check("(#1184-أ) القضية أُغلقت (كل ما عُلِّم عودة)", res["closed"] == [8300], res["closed"])

        # ── ب: الظهور في الترشيح التالي ──
        fresh = {"id": "ff0000000001", "status": "pending", "title": "خبر جديد عالي الدرجة",
                 "score": 50.0, "publishers": ["Reuters"], "link": "https://ret.example/fresh",
                 "bucket": "serious", "selection_issue": None}
        stale = dict(fresh, id="ff0000000002", title="خبر معلق قديم", score=3.0,
                     link="https://ret.example/stale")
        store.save_candidate(stale)
        dropped = collect.drop_stale_candidates()
        check("(#1184-ب) drop_stale_candidates لا تُسقط المرشح المُعاد وتُسقط العادي بلا ربط",
              cand_state(cand_a["id"])["status"] == "pending" and dropped == 1
              and cand_state("ff0000000002")["status"] == "unselected",
              (cand_state(cand_a["id"])["status"], dropped))
        store.save_candidate(fresh)
        res_or = run_open_review()
        sel_body = res_or["created"][0]["body"] if res_or["created"] else ""
        cand_ids = re.findall(r"<!--\s*cand:([0-9a-zA-Z]+)\s*-->", sel_body)
        badge = cfg.path("stages.returned_badge").format(stage=2)
        title_line = next((ln for ln in sel_body.splitlines()
                           if f"cand:{cand_a['id']}" in ln), "")
        check("(#1184-ب) قضية ترشيح جديدة، المُعاد في أعلاها (فوق أعلى درجة) بـ«↩️ أعدته من المرحلة 2»",
              len(res_or["created"]) == 1 and res_or["created"][0]["labels"] == ["pending-selection"]
              and cand_ids == [cand_a["id"], "ff0000000001"]
              and badge == "↩️ أعدته من المرحلة 2" and badge in title_line,
              (cand_ids, title_line))
        check("(#1184-ب) غير المُعاد بلا شارة",
              not any(badge in ln for ln in sel_body.splitlines()
                      if "cand:ff0000000001" in ln))
        ca = cand_state(cand_a["id"])
        check("(#1184-ب) بعد الربط: selection_issue الجديد وإزالة returned (مرشح عادي)",
              ca["selection_issue"] == 7501 and not ca.get("returned"), ca)
        print("\n----- قضية الترشيح من (ب) كما بُنيت -----\n" + sel_body + "\n-----")

        # ── ج: تقدّمه ثانية 📝 ← المسودة نفسها بلا صياغة ──
        calls.update(write=0, headlines=0, build=0)
        res_f = run_finalize(7501, tick_marker(sel_body, f"review:{cand_a['id']}"))
        dc = state(cand_a["id"])
        check("(#1184-ج) 📝 ← المسودة نفسها pending بنصها وعناوينها",
              dc["status"] == "pending" and dc["caption"] == draft_a["caption"]
              and dc["headlines"] == draft_a["headlines"]
              and dc["arabic"]["post_title"] == draft_a["arabic"]["post_title"],
              dc.get("status"))
        check("(#1184-ج) عدّاد الكاتب = 0 ولا عناوين جديدة ولا بناء بطاقة",
              calls == {"write": 0, "headlines": 0, "build": 0}, calls)
        check("(#1184-ج) مسودة واحدة بالمعرّف وأُزيلت علامات العودة",
              len(list(DRAFTS_DIR.glob(f"*/{cand_a['id']}.json"))) == 1
              and "returned_from_stage" not in dc and "returned_at" not in dc)
        review_issue = next((c for c in res_f["created"] if c["labels"] == ["pending-review"]), None)
        check("(#1184-ج) فُتحت قضية المرحلة 2 وفيها المسودة، وربطت review_issue",
              review_issue is not None and f"<!-- draft:{cand_a['id']} -->" in review_issue["body"]
              and dc.get("review_issue") == 7601 and cand_state(cand_a["id"])["status"] == "selected",
              [(c["title"], c["labels"]) for c in res_f["created"]])
        if review_issue:
            print("\n----- خبر المرحلة 2 بخيار go1 ظاهرًا -----\n"
                  + review_issue["body"] + "\n-----")

        # ── و: بعد (أ)، رفض لاحق للخبر نفسه في مرحلة 2 جديدة بلا تعليم ──
        res_rej = _run_publish_issue((review_issue or {}).get("body", ""), "approved", ["--now"])
        check("(#1184-و) رفض لاحق بلا تعليم ← rejected_unchecked يُسجَّل رغم «returned» السابق",
              state(cand_a["id"])["status"] == "rejected"
              and any(e["id"] == cand_a["id"] and e["decision"] == "rejected_unchecked"
                      for e in decisions.load())
              and any(e["id"] == cand_a["id"] and e["decision"] == "returned"
                      for e in decisions.load()), res_rej["code"])

        # ── د: المرحلة 3، go1 ثم 🚀 ← تُنشر ببطاقتها القائمة ──
        cand_d, draft_d = make_news("2", "خبر المرحلة الثالثة العائد", stage3=True, score=2.0)
        body3 = review.build_final_review_body([draft_d], "u/r", "main")
        check("(#1184-د) قضية المرحلة 3 لخبر أخبار فيها خيار go1",
              f"go:go1:{cand_d['id']}" in body3)
        res3 = _run_publish_issue(tick_marker(body3, f"<!-- go:go1:{cand_d['id']} -->"),
                                  "final-review", ["--now"])
        dd, cd = state(cand_d["id"]), cand_state(cand_d["id"])
        check("(#1184-د) go1 من المرحلة 3 ← returned بـreturned_from_stage=3 وصورتها باقية",
              dd["status"] == "returned" and dd["returned_from_stage"] == 3
              and dd.get("image") == draft_d["image"] and res3["published"] == [], dd)
        check("(#1184-د) المرشح pending بلا selection_issue وreturned من المرحلة 3، والسجل returned",
              cd["status"] == "pending" and cd["selection_issue"] is None
              and cd["returned"] is True and cd["returned_from_stage"] == 3
              and any(e["id"] == cand_d["id"] and e["decision"] == "returned"
                      and e.get("returned_from_stage") == 3 for e in decisions.load()), cd)
        res_or3 = run_open_review()
        sel3 = res_or3["created"][0]["body"] if res_or3["created"] else ""
        check("(#1184-د) يظهر في قضية الترشيح بـ«↩️ أعدته من المرحلة 3»",
              cfg.path("stages.returned_badge").format(stage=3) in sel3
              and f"cand:{cand_d['id']}" in sel3, sel3[:300])
        sel3_no = int(cand_state(cand_d["id"])["selection_issue"])
        calls.update(write=0, headlines=0, build=0)
        res_now = run_finalize(sel3_no, tick_marker(sel3, f"now:{cand_d['id']}"))
        check("(#1184-د) 🚀 ← تُنشر ببطاقتها القائمة دون إعادة بناء ولا نداء كاتب",
              state(cand_d["id"])["status"] == "published"
              and res_now["published"] == [draft_d["caption"]]
              and calls == {"write": 0, "headlines": 0, "build": 0}
              and state(cand_d["id"])["image"] == draft_d["image"],
              (calls, res_now["published"]))

        # ── هـ: go1 + publish معًا ← go1، وتعليق التعارض ──
        cand_e, draft_e = make_news("3", "خبر بتعارض العودة")
        body_e = review.build_issue_body([draft_e], "u/r", "main")
        body_e = tick_marker(body_e, f"<!-- go:go1:{cand_e['id']} -->")
        body_e = tick_marker(body_e, f"<!-- go:publish:{cand_e['id']} -->")
        res_e = _run_publish_issue(body_e, "approved", ["--now"])
        notes = [t for n, t in res_e["comments"] if "أكثر من خيار انتقال" in t]
        check("(#1184-هـ) go1+publish ← عودة (لا نشر)، وتعليق التعارض يذكر الخيارين",
              state(cand_e["id"])["status"] == "returned" and res_e["published"] == []
              and len(notes) == 1 and cfg.path("stages.options.go1") in notes[0]
              and cfg.path("stages.options.publish") in notes[0], notes)

        # ── ز: التحليل والرادار والطلب والمقال بلا سطر go1 ──
        for origin in ("analysis", "breaking", "request", "article"):
            d = _stage_news_draft(f"e1840000{origin[:2]}", f"خبر {origin}", origin=origin,
                                  image="drafts/x.jpg")
            check(f"(#1184-ز) أصل {origin}: لا سطر go1 في المرحلتين 2 و3",
                  "go:go1:" not in review.build_issue_body([d], "u/r", "main")
                  and "go:go1:" not in review.build_final_review_body([d], "u/r", "main"))

        # ── ح: رابط صورة فاشل في الحقل ──
        d_img = _stage_news_draft("e1840000009f", "خبر برابط صورة فاشل",
                                  image="drafts/h.jpg", image_info={"used_original": True})
        (DRAFTS_DIR / "h.jpg").write_bytes(b"\xff\xd8\xff")
        store.save_draft(d_img)
        body_h = review.build_issue_body([d_img], "u/r", "main")
        field = stages.image_field(d_img["id"], cfg)
        bad_url = "https://cdn.example/not-an-image.html"
        pasted = body_h.replace(field, field.replace("هنا:", f"هنا: {bad_url}"))
        sync_path = _TMP_DATA_DIR / "stage1_return_sync.json"
        real_sync, real_fetch = setimage_mod.SYNC_FILE, review.fetch_issue_body
        real_upd, real_cmt = review.update_issue_body, review.comment
        real_rebuild = setimage_mod.rebuild_card
        attempts: list = []
        updated: list = []
        comments: list = []
        setimage_mod.SYNC_FILE = sync_path
        setimage_mod.rebuild_card = lambda *a, **k: attempts.append(1)  # None = فشل البناء
        review.update_issue_body = lambda n, b: updated.append(b)
        review.comment = lambda n, t: comments.append(t)
        try:
            review.fetch_issue_body = lambda n: pasted
            sys.argv = ["setimage", "--from-issue", "--issue", "8400", "--body", ""]
            code_fail = setimage_mod.main()
            setimage_mod.sync_issue(8400)
            after_fail = updated[-1] if updated else ""
            # تعديل تالٍ للقضية: يُقرأ جسمها كما تركه sync_issue
            review.fetch_issue_body = lambda n: after_fail
            sys.argv = ["setimage", "--from-issue", "--issue", "8401", "--body", ""]
            code_again = setimage_mod.main()
            attempts_after_edit = len(attempts)
            # الصيغة القديمة (مربع img:): يبقى الرابط كما كان
            legacy = legacy_stage2_body([("e1840000009e", "قديم")]).replace(
                "- [ ] 🖼️", "- [x] 🖼️").replace(
                "الرابط:   <!--", f"الرابط: {bad_url}  <!--")
            d_old = _stage_news_draft("e1840000009e", "قديم", image="drafts/h.jpg",
                                      image_info={"used_original": True})
            store.save_draft(d_old)
            review.fetch_issue_body = lambda n: legacy
            sys.argv = ["setimage", "--from-issue", "--issue", "8402", "--body", ""]
            setimage_mod.main()
            setimage_mod.sync_issue(8402)
            legacy_after = updated[-1]
        finally:
            setimage_mod.SYNC_FILE = real_sync
            setimage_mod.rebuild_card = real_rebuild
            review.fetch_issue_body, review.update_issue_body = real_fetch, real_upd
            review.comment = real_cmt
            sync_path.unlink(missing_ok=True)
        check("(#1184-ح) رابط فاشل في الحقل الجديد ← يُمسح الحقل ويعود نصّه",
              code_fail == 1 and bad_url not in after_fail and field in after_fail,
              after_fail[-300:])
        check("(#1184-ح) تعليق الفشل يحوي الرابط الفاشل والسبب",
              any(bad_url in c and "السبب" in c and d_img["id"] in c for c in comments), comments)
        check("(#1184-ح) تعديل تالٍ للقضية لا يعيد المحاولة (لا أمر صالح، ولا بناء ثانٍ)",
              code_again == 2 and attempts_after_edit == 1, (code_again, attempts_after_edit))
        check("(#1184-ح) الصيغة القديمة (img:) لا تتغير: الرابط يبقى بعد الفشل",
              bad_url in legacy_after, legacy_after[-300:])
    finally:
        collect_finalize.write_arabic = real_write
        collect_finalize.headlines_mod.headlines_for_post = real_hl
        cards._default_build_post_image = real_build


def test_stages_module() -> None:
    """Issue #1180 (المهمة 1 من 4): src/stages.py — نص مبني ثم مقروء ذهابًا
    وإيابًا، وترجمة العلامات القديمة مطابقة لما يفعله القارئ الحالي لنص قضية
    بنته البناة الفعليون. الوحدة غير مستدعاة من أي باني بعد."""
    from src import preselect, stages
    from src import youtube_cluster as ycl
    from src import youtube_publish as yp

    cfg = load_config()
    hdr = "⬇️ **الانتقال (علّم واحدًا):**"
    t_go1 = "↩️ عد إلى مرحلة ترشيح المواضيع المتاحة"
    t_go2f = "📝 تقدّم إلى مرحلة عرض النص واختيار العناوين"
    t_go2b = "↩️ عد إلى مرحلة عرض النص واختيار العناوين"
    t_go3 = "🎴 تقدّم إلى مرحلة عرض البطاقة والمراجعة النهائية"

    def box(text, action, i="ab12"):
        return f"- [ ] {text}  <!-- go:{action}:{i} -->"

    # (أ) الأسطر والترتيب والنصوص حرفيًا
    check("(#1180-أ) رأس المرحلة 1",
          stages.stage_header(1, cfg) == "### المرحلة 1 من 4: مرحلة ترشيح المواضيع المتاحة")
    check("(#1180-أ) رأس المرحلة 4",
          stages.stage_header(4, cfg) == "### المرحلة 4 من 4: مرحلة النشر")
    check("(#1180-أ) خيارات المرحلة 1: بلا go1 ولا خيار المرحلة نفسها",
          stages.options_block(1, "ab12", cfg) == [
              hdr, box(t_go2f, "go2"), box(t_go3, "go3"),
              box("🚀 انشر فورًا", "publish")])
    check("(#1180-أ) خيارات المرحلة 2: بلا go2",
          stages.options_block(2, "ab12", cfg) == [
              hdr, box(t_go1, "go1"), box(t_go3, "go3"),
              box("🚀 انشر فورًا", "publish")])
    check("(#1180-أ) خيارات المرحلة 3: go2 بنص العودة، بلا go3",
          stages.options_block(3, "ab12", cfg) == [
              hdr, box(t_go1, "go1"), box(t_go2b, "go2"),
              box("🚀 انشر فورًا", "publish")])
    check("(#1180-أ) has_stage1=False يحذف go1 فقط",
          stages.options_block(2, "ab12", cfg, has_stage1=False) == [
              hdr, box(t_go3, "go3"), box("🚀 انشر فورًا", "publish")])
    check("(#1180-أ) urgent يضيف لاحقة العاجل على النشر وحده",
          stages.options_block(3, "ab12", cfg, urgent=True)[-1]
          == box("🚀 انشر فورًا (عاجل: بلا انتظار)", "publish")
          and stages.options_block(3, "ab12", cfg, urgent=True)[:-1]
          == stages.options_block(3, "ab12", cfg)[:-1])

    # (ب) مربع واحد
    body = "\n".join(stages.options_block(2, "ab12", cfg))
    check("(#1180-ب) بلا تعليم لا إجراء",
          stages.parse_actions(body) == ({}, []))
    one = tick_marker(body, "go:go3:ab12")
    check("(#1180-ب) مربع واحد يعيده parse_actions بلا تعارض",
          stages.parse_actions(one) == ({"ab12": "go3"}, []))

    # (ج) مربعان: الأبكر يغلب والتعارض مُبلَّغ
    two = tick_marker(one, "go:publish:ab12")
    check("(#1180-ج) go3 + publish: go3 يغلب والتعارض مُبلَّغ",
          stages.parse_actions(two) == (
              {"ab12": "go3"}, [{"id": "ab12", "marked": ["go3", "publish"]}]),
          str(stages.parse_actions(two)))

    # (د) خبران بخيارين مختلفين
    two_items = "\n".join(stages.options_block(2, "aa01", cfg)
                          + stages.options_block(2, "bb02", cfg))
    two_items = tick_marker(two_items, "go:go1:aa01")
    two_items = tick_marker(two_items, "go:publish:bb02")
    check("(#1180-د) خبران بخيارين مختلفين",
          stages.parse_actions(two_items) == ({"aa01": "go1", "bb02": "publish"}, []))

    # (هـ) legacy_actions على نصوص البناة الفعليين
    now = datetime.now(timezone.utc)
    cands = []
    for n in range(4):
        art = Article(title=f"مرشح قديم {n}", link=f"https://leg.example/{n}",
                      summary="", source_name="L", region="rl", weight=1.0,
                      published=now, bucket="serious", publisher="L")
        cands.append(preselect.build_candidate(art))
    c0, c1, c2, c3 = (c["id"] for c in cands)
    # (#1190) الباني الجديد لا يبني المربعات القديمة: الترجمة القديمة تُفحص على
    # نص ثابت منسوخ من الباني القديم
    sel = legacy_selection_body(cands)
    sel = tick_marker(sel, f"now:{c0}")
    sel = tick_marker(sel, f"review:{c1}")
    sel = tick_marker(sel, f"sel-card:{c2}")
    sel = tick_marker(sel, f"now:{c3}")          # 🚀 + 🎴 ← 🎴 يغلب
    sel = tick_marker(sel, f"sel-card:{c3}")
    check("(#1180-هـ) المرحلة 1 أخبار: now/review/sel-card وقاعدة الأحوط",
          stages.legacy_actions(sel, 1)
          == {c0: "publish", c1: "go2", c2: "go3", c3: "go3"},
          str(stages.legacy_actions(sel, 1)))
    check("(#1180-هـ) المرحلة 1 أخبار: القارئ الحالي يرى المعلَّم نفسه",
          preselect.parse_publish_now(sel) == [c0, c3]
          and preselect.parse_draft_review(sel) == [c1]
          and preselect.selected_card_ids(sel) == [c2, c3])
    both = tick_marker(tick_marker(
        legacy_selection_body(cands[:1]), f"review:{c0}"), f"sel-card:{c0}")
    check("(#1180-هـ) المرحلة 1: 📝 تغلب 🎴",
          stages.legacy_actions(both, 1) == {c0: "go2"})

    topics = [{"id": "a1b1", "title": "ق", "event": "", "layer": 2, "blocs": ["arabic"],
               "channels": ["ق1"], "agreement": "agreement", "point_ids": [0]},
              {"id": "a1b2", "title": "ك", "event": "", "layer": 2, "blocs": ["arabic"],
               "channels": ["ق1"], "agreement": "agreement", "point_ids": [0]}]
    tsel = tick_marker(legacy_youtube_selection_body("2099-01-01", topics), "topic:a1b1")
    check("(#1180-هـ) المرحلة 1 تحليل: topic: معلَّم ← go2 ومطابق للقارئ الحالي",
          stages.legacy_actions(tsel, 1) == {"a1b1": "go2"}
          and ycl._checked_topic_ids(tsel) == {"a1b1"})

    def mk(i, title):
        return {"id": i, "status": "pending", "origin": "news",
                "arabic": {"post_title": title}, "caption": "متن",
                "image": f"drafts/{i}.jpg", "image_info": {"used_original": True},
                "bucket": "serious", "score": 1, "headlines": [title],
                "source": {"link": f"https://x/{i}", "publishers": ["BBC"]}}
    d_pub, d_card, d_cardonly, d_none = (mk(f"c0000000000{n}", f"خبر {n}") for n in range(4))
    # (#1182) البانيان الجديدان لا يبنيان العلامات القديمة: الترجمة تُفحص على
    # نص ثابت منسوخ من الباني القديم (قضية مفتوحة قبل التحديث).
    rev = legacy_stage2_body([(d["id"], d["arabic"]["post_title"])
                              for d in (d_pub, d_card, d_cardonly, d_none)])
    rev = tick_marker(rev, f"draft:{d_pub['id']}")
    rev = tick_marker(rev, f"draft:{d_card['id']}")
    rev = tick_marker(rev, f"card:{d_card['id']}")
    rev = tick_marker(rev, f"card:{d_cardonly['id']}")
    check("(#1180-هـ) المرحلة 2: draft وحده publish، draft+card go3، card وحده لا شيء",
          stages.legacy_actions(rev, 2) == {d_pub["id"]: "publish", d_card["id"]: "go3"},
          str(stages.legacy_actions(rev, 2)))
    check("(#1180-هـ) المرحلة 2: القارئ الحالي يرى المعلَّم نفسه",
          review.parse_approved(rev) == [d_pub["id"], d_card["id"]]
          and review.parse_card_requests(rev) == {d_card["id"], d_cardonly["id"]})

    yd = {"id": "bb0000000009", "status": "pending", "origin": "analysis",
          "title": "مقال", "arabic": {"post_title": "مقال", "urgent": False},
          "headlines": ["ع"], "headline_selected": 0, "caption": "م",
          "source": {"link": "", "publishers": ["ق"]}, "tier": "c",
          "blocs": ["arabic"], "channels": ["ق"], "agreement": "agreement",
          "warnings": [], "score": 1}
    # (#1187) باني التحليل لم يعد يبني العلامات القديمة: الترجمة تُفحص على نص
    # ثابت منسوخ من بانيه القديم (قضية youtube-review مفتوحة قبل التحديث).
    ybody = legacy_youtube_review_body([(yd["id"], "مقال")])
    y_draft = tick_marker(ybody, f"draft:{yd['id']}")
    check("(#1180-هـ) المرحلة 2 تحليل: draft وحده publish",
          stages.legacy_actions(y_draft, 2) == {yd["id"]: "publish"})
    check("(#1180-هـ) المرحلة 2 تحليل: draft+card go3",
          stages.legacy_actions(tick_marker(y_draft, f"card:{yd['id']}"), 2)
          == {yd["id"]: "go3"})

    f_pub, f_back, f_both = (mk(f"d0000000000{n}", f"نهائي {n}") for n in range(3))
    fin = legacy_stage3_body([(d["id"], d["arabic"]["post_title"])
                              for d in (f_pub, f_back, f_both)])
    fin = tick_marker(fin, f"draft:{f_pub['id']}")
    fin = tick_marker(fin, f"back:{f_back['id']}")
    fin = tick_marker(fin, f"draft:{f_both['id']}")
    fin = tick_marker(fin, f"back:{f_both['id']}")
    check("(#1180-هـ) المرحلة 3: draft publish، back go2، back يغلب draft",
          stages.legacy_actions(fin, 3) == {
              f_pub["id"]: "publish", f_back["id"]: "go2", f_both["id"]: "go2"},
          str(stages.legacy_actions(fin, 3)))
    back_ids = review.parse_back_requests(fin)
    check("(#1180-هـ) المرحلة 3: القارئ الحالي (approved ناقص back) نفسه",
          [i for i in review.parse_approved(fin) if i not in back_ids] == [f_pub["id"]]
          and back_ids == {f_back["id"], f_both["id"]})

    # (و) image_field يُقرأ بالقارئ القائم لـimgurl
    field = stages.image_field("ab12", cfg)
    check("(#1180-و) سطر حقل الصورة بالنص والعلامة القائمة",
          field == "🖼️ لاستبدال الصورة الصق الرابط هنا:  <!-- imgurl:ab12 -->", field)
    pasted = field.replace("هنا:", "هنا: https://img.example/p.jpg")
    img_box = "- [x] 🖼️ استبدل  <!-- img:ab12 -->"
    check("(#1180-و) parse_image_requests القائم يعيد الرابط الملصوق",
          review.parse_image_requests(img_box + "\n" + pasted)
          == [("ab12", "https://img.example/p.jpg")])
    # (#1182) القارئ صار يقبل الحقل وحده بلا مربع img:
    check("(#1180-و) القارئ يعيد الرابط من الحقل وحده بلا مربع img: (#1182)",
          review.parse_image_requests(pasted) == [("ab12", "https://img.example/p.jpg")])


class _FakeBlock:
    def __init__(self, type_, input_=None, text=None):
        self.type, self.input, self.text = type_, input_, text


class _FakeResp:
    def __init__(self, content, stop_reason="end_turn"):
        self.content, self.stop_reason, self.usage = content, stop_reason, None


class _CountingClient:
    """عميل نموذج وهمي بردود مرتّبة؛ calls يعدّ كل نداء (مقال Opus أو عناوين)."""

    class _Messages:
        def __init__(self, responses):
            self._responses = list(responses)
            self.calls: list = []

        def create(self, **kw):
            self.calls.append(kw)
            return self._responses.pop(0)

    def __init__(self, responses):
        self.messages = _CountingClient._Messages(responses)


def _analysis_article_responses(title: str, headlines: list[str]) -> list:
    text = (f"# {title}\n\n" + "كلمة " * 260 + "\n\nمرجّح أن يقع هذا التطوّر فعلًا. وفق ما عرضته قناة الجزيرة وقناة CNN Türk وقناة ثالثة.")
    return [_FakeResp([_FakeBlock("text", text=text)]),
            _FakeResp([_FakeBlock("tool_use", input_={"headlines": headlines})])]


@auto_restore_last_publish
def test_analysis_stages_pipeline() -> None:
    """Issue #1187 (المهمة 3): مسار التحليل في المرحلتين 2 و3 — قضايا بالبناة
    الحقيقيين، تُعلَّم، ثم تُمرَّر إلى publish.main وyoutube_cluster.open_selection
    وpublish.cmd_youtube_selection وsetimage الحقيقية بالـfakes القائمة، مع عدّاد
    لنداءات النموذج (المقال Opus والعناوين). مواضع الاختبار a–h في الطلب."""
    from src import decisions, youtube_cluster as ycl, youtube_extract
    from src import publish as publish_mod
    import src.setimage as setimage_mod
    yp = youtube_publish

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(ycl.TOPICS_DIR, ignore_errors=True)
    ycl.TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    ycl.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()
    if decisions.DECISIONS_FILE.exists():
        decisions.DECISIONS_FILE.unlink()

    D1, D2, D3 = "2099-10-01", "2099-10-02", "2099-10-03"
    points = [
        {"video_id": "sw0", "bloc": "arabic", "channel": "الجزيرة", "speaker": "متحدث",
         "statement": "قول", "quote_arabic": "اقتباس", "type": "fact",
         "video_title": "فيديو", "video_url": "https://youtube.com/watch?v=sw0", "timestamp": 1},
        {"video_id": "sw1", "bloc": "turkish", "channel": "CNN Türk", "speaker": "متحدث٢",
         "statement": "قول٢", "quote_arabic": "اقتباس٢", "type": "fact",
         "video_title": "فيديو٢", "video_url": "https://youtube.com/watch?v=sw1", "timestamp": 2},
    ]
    for day in (D1, D2, D3):
        (ycl.POINTS_DIR / f"{day}.json").write_text(
            json.dumps({"points": points}, ensure_ascii=False), encoding="utf-8")

    def mk_topic(title: str) -> dict:
        return {"title": title, "event": f"حدث {title}", "layer": "a",
                "blocs": ["arabic", "turkish"], "channels": ["الجزيرة", "CNN Türk"],
                "agreement": "cross_source", "point_ids": [0, 1]}

    def write_topics(day: str, titles: list[str]) -> None:
        (ycl.TOPICS_DIR / f"{day}.json").write_text(
            json.dumps({"run_date": day, "topics": [mk_topic(t) for t in titles]},
                       ensure_ascii=False), encoding="utf-8")

    def topics_file(day: str) -> dict:
        return json.loads((ycl.TOPICS_DIR / f"{day}.json").read_text(encoding="utf-8"))

    def state(draft_id: str) -> dict:
        return store.load_draft(draft_id)[1]

    # ── fakes: القضايا والتعليقات والشبكة ──
    created: list[dict] = []
    comments: list[tuple] = []

    def fake_create_issue(title, body, labels=None):
        created.append({"title": title, "body": body, "labels": labels,
                        "number": 5000 + len(created) + 1})
        return {"number": 5000 + len(created), "html_url": "https://x/i"}

    photo_calls = {"free": 0, "news": 0}

    def fake_free(*a, **k):
        photo_calls["free"] += 1
        return ["https://example.com/photo.jpg"]

    def fake_news(*a, **k):
        photo_calls["news"] += 1
        return []

    real = {
        "create_issue": review.create_issue, "ensure_labels": review.ensure_labels,
        "comment": review.comment, "remove_label": review.remove_label,
        "close_issue": review.close_issue,
        "yp_photo": yp._photo_candidates,
        "ex_photo": youtube_extract.photo_candidates,
        "ex_news_ok": youtube_extract.news_photo_available,
        "ex_news": youtube_extract.news_photo_candidates,
        "find_images": imagesearch.find_images,
        "repo": os.environ.get("GITHUB_REPOSITORY"),
    }
    seen_backup = ycl.SEEN_PATH.read_text(encoding="utf-8") if ycl.SEEN_PATH.exists() else None
    review.create_issue = fake_create_issue
    review.ensure_labels = lambda: None
    review.comment = lambda n, t: comments.append((n, t))
    review.remove_label = lambda n, lbl: None
    review.close_issue = lambda n: None
    yp._photo_candidates = fake_free
    youtube_extract.photo_candidates = fake_free
    youtube_extract.news_photo_available = lambda *a, **k: False
    youtube_extract.news_photo_candidates = fake_news
    imagesearch.find_images = lambda *a, **k: []
    os.environ["GITHUB_REPOSITORY"] = "user/trendnews"

    def cfg_with(count: int, cap: int):
        c = load_config()
        c.setdefault("youtube", {}).setdefault("article", {}).update(count=count, max_per_run=cap)
        return c

    def resume(sel: dict, body: str, ticks: list[str], cfg_r, client) -> dict:
        """يعلّم المواضيع ثم publish.cmd_youtube_selection الحقيقية."""
        for t in sel["topics"]:
            if t["id"] in ticks:
                body = tick_marker(body, f"<!-- topic:{t['id']} -->")
        comments.clear()
        n0 = len(created)
        code = publish_mod.cmd_youtube_selection(sel["issue"]["number"], body, cfg_r, client=client)
        return {"code": code, "new_issues": created[n0:], "number": sel["issue"]["number"]}

    try:
        # ═══ ج: الكتابة عبر الاختيار تحفظ topic_id/topic_date ═══
        write_topics(D1, ["موضوع أول", "موضوع ثانٍ"])
        client1 = _CountingClient(
            _analysis_article_responses("هل يقع التطوّر الأول؟", ["هل يقع التطوّر الأول؟", "بديل ١", "بديل ٢"])
            + _analysis_article_responses("هل يقع التطوّر الثاني؟", ["هل يقع التطوّر الثاني؟", "بديل ١", "بديل ٢"]))
        n_issues = len(created)
        sel1 = ycl.open_selection(cfg_with(5, 5), date_str=D1)
        topic1 = next(t for t in sel1["topics"] if t["title"] == "موضوع أول")
        topic2 = next(t for t in sel1["topics"] if t["title"] == "موضوع ثانٍ")
        r1 = resume(sel1, created[n_issues]["body"], [topic1["id"], topic2["id"]],
                    cfg_with(5, 5), client1)
        drafts_now = {d["topic_id"]: d for _, d in store.pending_drafts()
                      if store.origin_of(d) == "analysis" and d.get("topic_id")}
        d_t1, d_t2 = drafts_now.get(topic1["id"]), drafts_now.get(topic2["id"])
        check("(#1187-ج) مسودتا التحليل المكتوبتان تحملان topic_id وtopic_date (تاريخ ملف الموضوع)",
              d_t1 is not None and d_t2 is not None
              and d_t1["topic_date"] == D1 and d_t2["topic_date"] == D1,
              list(drafts_now))
        review_issue = next((c for c in r1["new_issues"] if c["labels"] == ["youtube-review"]), None)
        check("(#1187-ج) فُتحت قضية مرحلة 2 (youtube-review) للمسودتين",
              review_issue is not None and f"<!-- draft:{d_t1['id']} -->" in review_issue["body"]
              and f"<!-- draft:{d_t2['id']} -->" in review_issue["body"], len(created))
        S2 = review_issue["body"]
        hl_t1 = list(d_t1["headlines"])
        cap_t1 = d_t1["caption"]

        # ═══ أ: الشكل الجديد للمرحلة 2 ═══
        cfg = load_config()
        lines = S2.splitlines()
        first_title = next(i for i, ln in enumerate(lines) if "<!-- draft:" in ln)
        check("(#1187-أ) الرأس stages.stage_header(2) ثم الشرح الموحَّد",
              lines[0] == stages.stage_header(2, cfg) and cfg.path("stages.explainer") in S2, lines[:4])
        check("(#1187-أ) لا سطر «- [ ]» قبل عنوان المقال الأول، والعنوان نفسه بلا مربع",
              not any(re.match(r"\s*[-*]\s*\[", ln) for ln in lines[:first_title + 1])
              and lines[first_title].startswith("**"), lines[first_title])
        item_end = next((i for i, ln in enumerate(lines) if i > first_title and ln.strip() == "---"),
                        len(lines))
        item = "\n".join(lines[first_title:item_end])

        def pos(needle: str) -> int:
            return item.find(needle)
        first_id = re.search(r"<!-- draft:([0-9a-f]+) -->", lines[first_title]).group(1)
        marks = [pos(f"draft:{first_id}"), pos("تقاطع "), pos("الدرجة "), pos("🖼️ **المصدر:**"),
                 pos("<details>"), pos("العناوين المقترحة"), pos(f"imgurl:{first_id}"),
                 pos(cfg.path("stages.options_header"))]
        check("(#1187-أ) ترتيب أقسام المقال: العنوان ← الشارات والقنوات ← مصدر الصورة ← النص ← "
              "العناوين ← حقل الصورة ← الانتقال",
              -1 not in marks and marks == sorted(marks), marks)
        check("(#1187-أ) كتلة الانتقال: publish وgo3 وgo1 (المقال يحمل topic_id) بلا go2",
              all(f"<!-- go:{a}:{d_t1['id']} -->" in S2 for a in ("publish", "go3", "go1"))
              and f"<!-- go:go2:{d_t1['id']} -->" not in S2)
        check("(#1187-أ) لا علامات قديمة: لا card: ولا img: في القضية الجديدة",
              f"card:{d_t1['id']}" not in S2 and f"img:{d_t1['id']}" not in S2)
        check("(#1187-أ) مربعات العناوين hl: كما هي (الأول معلَّم)",
              f"- [x] 1. {hl_t1[0]}  <!-- hl:{d_t1['id']}:0 -->" in S2
              and f"<!-- hl:{d_t1['id']}:2 -->" in S2)
        check("(#1187-أ) قبل التعليم لا إجراء مقروء", stages.read_actions(S2, 2)[0] == {})
        single = yp.build_review_body([d_t1], "user/trendnews", "main", cfg)
        print("\n----- قضية المرحلة 2 للتحليل بمقال واحد كما بُنيت -----\n" + single + "\n-----")

        # ═══ ح: مقال تحليل قديم بلا topic_id ═══
        old = yp.build_draft_from_text(
            {"id": "ab0000000000", "title": "قديم", "layer": "a", "blocs": ["arabic"],
             "channels": ["الجزيرة"], "agreement": "agreement", "event": "ح"},
            "# قديم\n\nمتن", [], "2099-09-01", cfg)
        old.pop("topic_id")
        old.pop("topic_date")
        old["id"] = "ab0000000001"
        store.save_draft(old)
        old3 = dict(old, image="drafts/old.jpg", image_info={"used_original": True})
        body_old = yp.build_review_body([old], "u/r", "main", cfg)
        check("(#1187-ح) مقال قديم بلا topic_id: لا go1 في المرحلة 2 ولا 3",
              "go:go1:" not in body_old
              and "go:go1:" not in review.build_final_review_body([old3], "u/r", "main", cfg))
        check("(#1187-ح) المقال الجديد (topic_id) في المرحلة 3 فيه go1",
              f"go:go1:{d_t1['id']}" in review.build_final_review_body(
                  [dict(d_t1, image="drafts/x.jpg")], "u/r", "main", cfg))
        forged = body_old.replace(
            f"<!-- go:publish:{old['id']} -->",
            f"<!-- go:publish:{old['id']} -->\n  - [x] مزوَّر  <!-- go:go1:{old['id']} -->")
        res_old = _run_publish_issue(forged, "youtube-review", ["--skip-urgent"])
        check("(#1187-ح) go1 مزوَّر على مقال قديم: يبقى pending ويُبلَّغ بسببه",
              state(old["id"])["status"] == "pending"
              and any("بلا رابطة موضوع" in t for n, t in res_old["comments"]),
              [t for n, t in res_old["comments"]])

        # ═══ ب: publish وgo3 وبلا تعليم (قضية بالباني الحقيقي) ═══
        def mk_analysis(n: str, title: str) -> dict:
            d = yp.build_draft_from_text(
                {"id": f"cc00000000{n}", "title": title, "layer": "a", "blocs": ["arabic"],
                 "channels": ["الجزيرة"], "agreement": "agreement", "event": "ح"},
                f"# {title}\n\nمتن {title}\n\n---\n\n{youtube_article.HEADLINES_HEADER}\n\n"
                f"1. {title}\n2. بديل\n3. بديل ثالث\n", [], "2099-09-05", cfg)
            store.save_draft(d)
            return d
        p_pub, p_go3, p_none = (mk_analysis(n, t) for n, t in
                                (("1", "مقال ينشر"), ("2", "مقال إلى البطاقة"), ("3", "مقال بلا تعليم")))
        body_b = yp.build_review_body([p_pub, p_go3, p_none], "u/r", "main", cfg)
        body_b = tick_marker(body_b, f"<!-- go:publish:{p_pub['id']} -->")
        body_b = tick_marker(body_b, f"<!-- go:go3:{p_go3['id']} -->")
        res_b = _run_publish_issue(body_b, "youtube-review", ["--skip-urgent"])
        check("(#1187-b) publish ← نُشر كما اليوم (بطاقة بُنيت ونُشر)",
              state(p_pub["id"])["status"] == "published" and bool(state(p_pub["id"]).get("image"))
              and len(res_b["published"]) == 1, (state(p_pub["id"])["status"], res_b["published"]))
        check("(#1187-b) go3 ← بطاقة مبنيّة وبقيت pending، وفي قضية مرحلة 3 (final-review) لا نشر",
              state(p_go3["id"])["status"] == "pending" and bool(state(p_go3["id"]).get("image"))
              and len(res_b["created"]) == 1 and res_b["created"][0]["labels"] == ["final-review"]
              and f"<!-- draft:{p_go3['id']} -->" in res_b["created"][0]["body"]
              and len(res_b["published"]) == 1, [c["labels"] for c in res_b["created"]])
        check("(#1187-b) بلا تعليم ← rejected_unchecked كما اليوم",
              state(p_none["id"])["status"] == "rejected"
              and any(e["id"] == p_none["id"] and e["decision"] == "rejected_unchecked"
                      for e in decisions.load()))

        # ═══ ج(اختبار c): قضية youtube-review بالشكل القديم ═══
        l_pub, l_card, l_none = (mk_analysis(n, f"قديم {n}") for n in "456")
        legacy = legacy_youtube_review_body([(d["id"], d["title"]) for d in (l_pub, l_card, l_none)])
        legacy = tick_marker(legacy, f"draft:{l_pub['id']}")
        legacy = tick_marker(legacy, f"draft:{l_card['id']}")
        legacy = tick_marker(legacy, f"card:{l_card['id']}")
        res_c = _run_publish_issue(legacy, "youtube-review", ["--skip-urgent"])
        check("(#1187-c) القضية القديمة: draft وحده ← نشر",
              state(l_pub["id"])["status"] == "published", state(l_pub["id"])["status"])
        check("(#1187-c) القضية القديمة: draft+card ← بطاقة وقضية مرحلة 3 بلا نشر",
              state(l_card["id"])["status"] == "pending" and bool(state(l_card["id"]).get("image"))
              and len(res_c["created"]) == 1 and res_c["created"][0]["labels"] == ["final-review"])
        check("(#1187-c) القضية القديمة: بلا تعليم ← مرفوض",
              state(l_none["id"])["status"] == "rejected")
        check("(#1187-c) القضية القديمة: القارئ الموحَّد يرى publish وgo3 بلا تعارض",
              stages.read_actions(legacy, 2) == (
                  {l_pub["id"]: "publish", l_card["id"]: "go3"}, []))

        # ═══ د: رابط صورة في المرحلة 2 ═══
        d_img = mk_analysis("7", "مقال بصورة يدوية")
        body_d = yp.build_review_body([d_img], "u/r", "main", cfg)
        field = stages.image_field(d_img["id"], cfg)
        mine = "https://cdn.example/mine.jpg"
        pasted = body_d.replace(field, field.replace("هنا:", f"هنا: {mine}"))
        sync_path = _TMP_DATA_DIR / "analysis_stage_sync.json"
        real_sync, real_fetch = setimage_mod.SYNC_FILE, review.fetch_issue_body
        real_upd = review.update_issue_body
        updated: list = []
        builds = {"n": 0}
        real_build = cards_mod._default_build_post_image
        cards_mod._default_build_post_image = lambda *a, **k: (
            builds.__setitem__("n", builds["n"] + 1) or real_build(*a, **k))
        setimage_mod.SYNC_FILE = sync_path
        review.fetch_issue_body = lambda n: pasted
        review.update_issue_body = lambda n, b: updated.append(b)
        comments.clear()
        try:
            sys.argv = ["setimage", "--from-issue", "--issue", "8500", "--body", ""]
            code_d = setimage_mod.main()
            setimage_mod.sync_issue(8500)
        finally:
            setimage_mod.SYNC_FILE = real_sync
            review.fetch_issue_body = real_fetch
            review.update_issue_body = real_upd
            sync_path.unlink(missing_ok=True)
        dd = state(d_img["id"])
        check("(#1187-d) رابط في الحقل ← manual_image محفوظة بلا بناء بطاقة",
              code_d == 0 and dd.get("manual_image") == mine and "image" not in dd
              and builds["n"] == 0, (code_d, dd.get("manual_image"), builds["n"]))
        check("(#1187-d) التعليق «حُفظت الصورة — تُستعمل عند بناء البطاقة» ومُسح الحقل",
              any("حُفظت الصورة — تُستعمل عند بناء البطاقة" in t for n, t in comments)
              and bool(updated) and mine not in updated[-1] and field in updated[-1], comments)
        check("(#1187-d) سطر مصدر الصورة في القضية يقول إن الرابط اليدوي سيُستعمل",
              "رابط وضعتَه يدويًا — يُستعمل عند بناء البطاقة" in yp.build_review_body(
                  [dd], "u/r", "main", cfg))
        photo_calls.update(free=0, news=0)
        res_d = _run_publish_issue(tick_marker(body_d, f"<!-- go:go3:{d_img['id']} -->"),
                                   "youtube-review", ["--skip-urgent"])
        dd = state(d_img["id"])
        check("(#1187-d) go3 ← البطاقة بصورتك: manual في image_info ورابطه المختار، "
              "ولا مزوّد خبر ولا حرّ استُدعي",
              bool(dd.get("image")) and dd["image_info"].get("manual") is True
              and dd["image_info"].get("chosen_url") == mine
              and photo_calls == {"free": 0, "news": 0}
              and len(res_d["created"]) == 1 and res_d["created"][0]["labels"] == ["final-review"],
              (dd.get("image_info"), photo_calls))
        cards_mod._default_build_post_image = real_build

        # الفشل: بطاقة قائمة ورابط لا يُبنى ← يُمسح الحقل والتعليق فيه الرابط والسبب
        d_fail = mk_analysis("8", "مقال برابط فاشل")
        store.update_draft(store.load_draft(d_fail["id"])[0], image="drafts/f.jpg",
                           image_info={"used_original": True})
        (DRAFTS_DIR / "f.jpg").write_bytes(b"\xff\xd8\xff")
        body_f = yp.build_review_body([state(d_fail["id"])], "u/r", "main", cfg)
        bad = "https://cdn.example/not-an-image.html"
        fail_field = stages.image_field(d_fail["id"], cfg)
        pasted_f = body_f.replace(fail_field, fail_field.replace("هنا:", f"هنا: {bad}"))
        real_rebuild = setimage_mod.rebuild_card
        setimage_mod.rebuild_card = lambda *a, **k: None
        setimage_mod.SYNC_FILE = sync_path
        review.fetch_issue_body = lambda n: pasted_f
        review.update_issue_body = lambda n, b: updated.append(b)
        comments.clear()
        try:
            sys.argv = ["setimage", "--from-issue", "--issue", "8501", "--body", ""]
            code_fail = setimage_mod.main()
            setimage_mod.sync_issue(8501)
        finally:
            setimage_mod.rebuild_card = real_rebuild
            setimage_mod.SYNC_FILE = real_sync
            review.fetch_issue_body = real_fetch
            review.update_issue_body = real_upd
            sync_path.unlink(missing_ok=True)
        check("(#1187-d) فشل الرابط: الحقل يُمسح والتعليق يحوي الرابط والسبب",
              code_fail == 1 and bad not in updated[-1]
              and any(bad in t and "السبب" in t for n, t in comments), comments)

        # ═══ e: go1 من المرحلة 2 لمقال topic_date بالأمس ═══
        body_e = tick_marker(S2, f"<!-- go:go1:{d_t1['id']} -->")
        body_e = tick_marker(body_e, f"<!-- go:go3:{d_t2['id']} -->")
        res_e = _run_publish_issue(body_e, "youtube-review", ["--skip-urgent"])
        de = state(d_t1["id"])
        check("(#1187-e) go1 من المرحلة 2 ← المسودة returned بمرحلتها ولحظتها، نصّها وعناوينها محفوظة",
              de["status"] == "returned" and de["returned_from_stage"] == 2
              and bool(de.get("returned_at")) and de["caption"] == cap_t1
              and de["headlines"] == hl_t1 and res_e["published"] == [], de.get("status"))
        tf = next(t for t in topics_file(D1)["topics"] if t["id"] == topic1["id"])
        check("(#1187-e) الموضوع في ملف أمس: returned وreturned=true ومرحلته ولحظته وdraft_id",
              tf["selection_status"] == "returned" and tf["returned"] is True
              and tf["returned_from_stage"] == 2 and bool(tf.get("returned_at"))
              and tf["draft_id"] == d_t1["id"], tf)
        rec = [e for e in decisions.load() if e["id"] == d_t1["id"]]
        check("(#1187-e) السجل: «returned» بقضية الاختيار التي جاء منها، وغير مانع للرفض اللاحق",
              len(rec) == 1 and rec[0]["decision"] == "returned"
              and rec[0].get("returned_from_stage") == 2
              and rec[0].get("selection_issue") == r1["number"]
              and "returned" in decisions._NON_BLOCKING, rec)
        check("(#1187-e) returned خارج قوائم المراجعة والنشر والطابور",
              d_t1["id"] not in [d["id"] for _, d in store.pending_drafts()]
              and d_t1["id"] not in [d["id"] for _, d in yp.pending_youtube_drafts()]
              and d_t1["id"] not in [d["id"] for _, d in publish_mod.queued_drafts()])
        check("(#1187-e) المقال الآخر (go3) بُنيت بطاقته وفُتحت له قضية المرحلة 3",
              bool(state(d_t2["id"]).get("image")) and len(res_e["created"]) == 1
              and res_e["created"][0]["labels"] == ["final-review"])
        S3 = res_e["created"][0]["body"]

        write_topics(D2, ["موضوع اليوم أ", "موضوع اليوم ب"])
        # سقف العرض 1: المُعاد يظهر خارجه (مُعاد + موضوع جديد واحد)
        n_before = len(created)
        sel_e = ycl.open_selection(cfg_with(1, 1), date_str=D2)
        sel_body = created[n_before]["body"]
        badge = cfg.path("stages.returned_badge").format(stage=2)
        order = re.findall(r"<!--\s*topic:([0-9a-f]+)\s*-->", sel_body)
        title_line = next((ln for ln in sel_body.splitlines() if f"topic:{topic1['id']}" in ln), "")
        check("(#1187-e) open_selection اليوم: الموضوع المُعاد في أعلى القضية بـ«↩️ أعدته من المرحلة 2» "
              "وخارج سقف count",
              len(order) == 2 and order[0] == topic1["id"] and badge == "↩️ أعدته من المرحلة 2"
              and badge in title_line and "موضوع اليوم أ" in sel_body
              and "موضوع اليوم ب" not in sel_body
              and created[n_before]["labels"] == ["youtube-selection"], (order, title_line))
        f1 = topics_file(D1)["topics"]
        f2 = topics_file(D2)["topics"]
        moved = next(t for t in f1 if t["id"] == topic1["id"])
        check("(#1187-e) ملف اليوم: النسخة في البداية بمعرّفها نفسه pending ومرتبطة بالقضية "
              "وفيها returned_from_stage وdraft_id؛ ونسخة أمس «moved»",
              f2[0]["id"] == topic1["id"] and f2[0]["selection_status"] == "pending"
              and f2[0]["selection_issue"] == sel_e["issue"]["number"]
              and f2[0]["returned_from_stage"] == 2 and f2[0]["draft_id"] == d_t1["id"]
              and moved["selection_status"] == "moved", (f2[0], moved))
        print("\n----- قضية ترشيح التحليل من (e) كما بُنيت -----\n" + sel_body + "\n-----")

        # ═══ f: اختياره ثانية ← المسودة نفسها بلا نداء نموذج ═══
        first_fresh = next(t for t in sel_e["topics"] if t["id"] != topic1["id"])
        client2 = _CountingClient(_analysis_article_responses(
            "هل يقع تطوّر اليوم؟", ["هل يقع تطوّر اليوم؟", "بديل ١", "بديل ٢"]))
        rf = resume(sel_e, sel_body, [topic1["id"], first_fresh["id"]], cfg_with(1, 1), client2)
        df = state(d_t1["id"])
        review_f = next((c for c in rf["new_issues"] if c["labels"] == ["youtube-review"]), None)
        check("(#1187-f) المسودة نفسها pending، نصّها وعناوينها كما كانت، وعلامات العودة أُزيلت",
              rf["code"] == 0 and df["status"] == "pending" and df["caption"] == cap_t1
              and df["headlines"] == hl_t1 and "returned_from_stage" not in df
              and "returned_at" not in df and len(list(DRAFTS_DIR.glob(f"*/{d_t1['id']}.json"))) == 1,
              df.get("status"))
        check("(#1187-f) نداءات النموذج: مقال اليوم الجديد وحده (2) — المُعاد 0 مقال Opus و0 عناوين، "
              "ولم يُحتسب ضمن max_per_run=1 فكُتب الجديد أيضًا",
              len(client2.messages.calls) == 2, len(client2.messages.calls))
        check("(#1187-f) فُتحت قضية مرحلة 2 جديدة فيها المسودة المُعادة وربطت review_issue",
              review_f is not None and f"<!-- draft:{d_t1['id']} -->" in review_f["body"]
              and df.get("review_issue") == review_f["number"], [c["labels"] for c in rf["new_issues"]])
        tf2 = topics_file(D2)["topics"]
        check("(#1187-f) الموضوع المُعاد في ملف اليوم attempted، وتاريخ موضوع المسودة صار D2",
              next(t for t in tf2 if t["id"] == topic1["id"])["selection_status"] == "attempted"
              and df["topic_date"] == D2, df.get("topic_date"))

        # ═══ g: go1 من المرحلة 3 ═══
        check("(#1187-g) قضية المرحلة 3 لمقال التحليل فيها go1", f"go:go1:{d_t2['id']}" in S3)
        res_g = _run_publish_issue(tick_marker(S3, f"<!-- go:go1:{d_t2['id']} -->"),
                                   "final-review", ["--skip-urgent"])
        dg = state(d_t2["id"])
        tg = next(t for t in topics_file(D1)["topics"]
                  if t["id"] == topic2["id"] and t["selection_status"] != "moved")
        check("(#1187-g) go1 من المرحلة 3 ← returned بـreturned_from_stage=3 وبطاقتها باقية، بلا نشر",
              dg["status"] == "returned" and dg["returned_from_stage"] == 3
              and bool(dg.get("image")) and res_g["published"] == [], dg.get("status"))
        check("(#1187-g) الموضوع returned من المرحلة 3 والسجل returned",
              tg["selection_status"] == "returned" and tg["returned_from_stage"] == 3
              and tg["draft_id"] == d_t2["id"]
              and any(e["id"] == d_t2["id"] and e["decision"] == "returned"
                      and e.get("returned_from_stage") == 3 for e in decisions.load()), tg)
        n_before = len(created)
        sel_g = ycl.open_selection(cfg_with(5, 5), date_str=D3)
        badge3 = cfg.path("stages.returned_badge").format(stage=3)
        sel_g_body = created[n_before]["body"]
        check("(#1187-g) يظهر في قضية ترشيح جديدة بـ«↩️ أعدته من المرحلة 3» ونسخة D1 «moved»؛ "
              "والمُعاد سابقًا (attempted) لا يعود",
              badge3 in sel_g_body and f"topic:{topic2['id']}" in sel_g_body
              and f"topic:{topic1['id']}" not in sel_g_body
              and next(t for t in topics_file(D1)["topics"] if t["id"] == topic2["id"])
              ["selection_status"] == "moved", sel_g_body[:300])
        client3 = _CountingClient([])
        rg = resume(sel_g, sel_g_body, [topic2["id"]], cfg_with(5, 5), client3)
        dg = state(d_t2["id"])
        check("(#1187-g) اختياره ← المسودة نفسها pending بلا أي نداء نموذج وفي قضية مرحلة 2 جديدة",
              dg["status"] == "pending" and len(client3.messages.calls) == 0
              and any(c["labels"] == ["youtube-review"] and f"draft:{d_t2['id']}" in c["body"]
                      for c in rg["new_issues"]), (dg.get("status"), len(client3.messages.calls)))

        # ═══ إعادة تشغيل العنقدة لليوم نفسه لا تمحو موضوعًا أُعيد ═══
        D4 = "2099-10-04"
        (ycl.TOPICS_DIR / f"{D4}.json").write_text(json.dumps({"run_date": D4, "topics": [
            {**mk_topic("أُعيد اليوم"), "id": "aa0000000001", "selection_status": "returned",
             "returned": True, "returned_from_stage": 2, "draft_id": "x"},
            {**mk_topic("قديم عُرض"), "id": "aa0000000002", "selection_status": "attempted"}]},
            ensure_ascii=False), encoding="utf-8")
        ycl.save_output({"run_date": D4, "topics": [mk_topic("نتيجة عنقدة جديدة")]})
        kept = topics_file(D4)["topics"]
        check("(#1187-ط) save_output لتشغيلة ثانية لليوم نفسه تحفظ المواضيع returned وحدها "
              "في البداية وتمحو الحالات الأخرى كما كانت",
              [t.get("title") for t in kept] == ["أُعيد اليوم", "نتيجة عنقدة جديدة"], kept)
    finally:
        review.create_issue = real["create_issue"]
        review.ensure_labels = real["ensure_labels"]
        review.comment = real["comment"]
        review.remove_label = real["remove_label"]
        review.close_issue = real["close_issue"]
        yp._photo_candidates = real["yp_photo"]
        youtube_extract.photo_candidates = real["ex_photo"]
        youtube_extract.news_photo_available = real["ex_news_ok"]
        youtube_extract.news_photo_candidates = real["ex_news"]
        imagesearch.find_images = real["find_images"]
        if real["repo"] is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real["repo"]
        if seen_backup is None:
            ycl.SEEN_PATH.unlink(missing_ok=True)
        else:
            ycl.SEEN_PATH.write_text(seen_backup, encoding="utf-8")


@auto_restore_last_publish
def test_stage1_unified_pipeline() -> None:
    """Issue #1190 (المهمة 4 من 4): المرحلة 1 (قضيتا ترشيح الأخبار والتحليل) بالوحدة
    المشتركة. قضايا بالبناة الحقيقيين، تُعلَّم، ثم تُمرَّر إلى collect_finalize.finalize
    وpublish.cmd_youtube_selection وsetimage الحقيقية بالـfakes القائمة، مع عدّاد لنداءات
    الكاتب (الأخبار) ونداءات النموذج (التحليل). مواضع الاختبار a–i في الطلب."""
    from src import collect_finalize, decisions, preselect, youtube_cluster as ycl
    from src import youtube_extract
    from src import publish as publish_mod
    import src.setimage as setimage_mod

    cfg = load_config()
    cfg.setdefault("youtube", {}).setdefault("publish", {}).update(spacing_minutes=0, max_per_run=3)
    now = datetime.now(timezone.utc)
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    shutil.rmtree(store.CANDIDATES_DIR, ignore_errors=True)
    shutil.rmtree(ycl.TOPICS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    ycl.TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    ycl.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    reset_last_publish()
    if decisions.DECISIONS_FILE.exists():
        decisions.DECISIONS_FILE.unlink()

    # ── مشترك: التقاط التعليقات والقضايا والنشر، وعدّاد الكاتب ──
    cap: dict = {}

    def reset_cap() -> None:
        cap.clear()
        cap.update(comments=[], created=[], published=[], closed=[], removed=[], updated=[])

    reset_cap()
    counter = {"issue": 7700}

    def fake_create(title, body, labels=None):
        counter["issue"] += 1
        cap["created"].append({"title": title, "body": body, "labels": labels,
                               "number": counter["issue"]})
        return {"number": counter["issue"], "html_url": "https://x/i"}

    calls = {"write": 0, "build": []}
    real_write = collect_finalize.write_arabic
    real_build = cards_mod._default_build_post_image

    def counting_write(*a, **k):
        calls["write"] += 1
        return real_write(*a, **k)

    def counting_build(*a, **k):
        calls["build"].append(k.get("image_urls"))
        return real_build(*a, **k)

    photo = {"free": 0, "news": 0}

    def fake_free(*a, **k):
        photo["free"] += 1
        return ["https://example.com/photo.jpg"]

    def fake_news(*a, **k):
        photo["news"] += 1
        return []

    patched = [
        (publish_mod, "ROOT"), (publish_mod, "cmd_burst"), (facebook, "publish_photo"),
        (review, "comment"), (review, "close_issue"), (review, "create_issue"),
        (review, "ensure_labels"), (review, "remove_label"),
        (review, "fetch_issue_body"), (review, "update_issue_body"),
        (youtube_publish, "_photo_candidates"),
        (youtube_extract, "photo_candidates"), (youtube_extract, "news_photo_available"),
        (youtube_extract, "news_photo_candidates"), (imagesearch, "find_images"),
        (setimage_mod, "SYNC_FILE"), (setimage_mod, "download_image")]
    real = [getattr(m, k) for m, k in patched]
    real_repo = os.environ.get("GITHUB_REPOSITORY")
    real_argv = sys.argv
    seen_backup = ycl.SEEN_PATH.read_text(encoding="utf-8") if ycl.SEEN_PATH.exists() else None
    sync_path = _TMP_DATA_DIR / "stage1_sync.json"
    fetch_real, update_real = review.fetch_issue_body, review.update_issue_body

    publish_mod.ROOT = DRAFTS_DIR.parent
    publish_mod.cmd_burst = (lambda ids, cfg_, issue, **kw: publish_mod.cmd_now(ids, cfg_, issue))
    facebook.publish_photo = lambda image_path, caption, api_version, first_comment=None: (
        cap["published"].append(caption) or dict(url="https://fb.example/s", id="1"))
    review.comment = lambda n, t: cap["comments"].append((n, t))
    review.close_issue = lambda n: cap["closed"].append(n)
    review.ensure_labels = lambda: None
    review.remove_label = lambda n, lbl: cap["removed"].append((n, lbl))
    review.create_issue = fake_create
    youtube_publish._photo_candidates = fake_free
    youtube_extract.photo_candidates = fake_free
    youtube_extract.news_photo_available = lambda *a, **k: False
    youtube_extract.news_photo_candidates = fake_news
    imagesearch.find_images = lambda *a, **k: []
    os.environ["GITHUB_REPOSITORY"] = "u/r"
    collect_finalize.write_arabic = counting_write
    cards_mod._default_build_post_image = counting_build

    def state(draft_id: str) -> dict:
        return store.load_draft(draft_id)[1]

    def cand_state(cid: str) -> dict:
        return store.load_candidate(cid)[1]

    def all_drafts() -> list[dict]:
        return [json.loads(p.read_text(encoding="utf-8")) for p in DRAFTS_DIR.glob("*/*.json")]

    # ── الأخبار: مرشحون حقيقيون وقضية بالباني الحقيقي ──
    def mk_cand(tag: str, title: str, *, image: str | None = None, issue: int = 0,
                returned: bool = False) -> dict:
        art = Article(title=title, link=f"https://s1.example/{tag}", summary="",
                      source_name="P1", region="r1", weight=1.0, published=now,
                      bucket="serious", publisher="P1")
        art.image_url = image
        cand = preselect.build_candidate(art)
        cand["selection_issue"] = issue or None
        if returned:
            cand.update(returned=True, returned_from_stage=2, returned_at=now.isoformat())
        store.save_candidate(cand)
        return cand

    def run_finalize(number: int, body: str) -> dict:
        reset_cap()
        reset_last_publish()
        cap["code"] = collect_finalize.finalize(number, body, cfg)
        return dict(cap)

    def run_setimage(number: int, body: str) -> dict:
        """setimage الحقيقية على قضية (main ثم sync_issue) — الشبكة مزيَّفة."""
        reset_cap()
        setimage_mod.SYNC_FILE = sync_path
        review.fetch_issue_body = lambda n: body
        review.update_issue_body = lambda n, b: cap["updated"].append(b)
        try:
            sys.argv = ["setimage", "--from-issue", "--issue", str(number), "--body", ""]
            cap["code"] = setimage_mod.main()
            setimage_mod.sync_issue(number)
        finally:
            sys.argv = real_argv
            review.fetch_issue_body = fetch_real
            review.update_issue_body = update_real
            sync_path.unlink(missing_ok=True)
        return dict(cap)

    fixture_img = Image.open("/tmp/_fixture_photo.jpg").convert("RGB")

    def download_stub(url, timeout=20, failures=None):
        if "bad" in url:
            if failures is not None:
                failures.append(dict(url=url, reason="HTTP 404، حجم 0 بايت (دون 15000)"))
            return None
        return fixture_img

    setimage_mod.download_image = download_stub

    def fill_field(body: str, item_id: str, url: str) -> str:
        field = stages.image_field(item_id, cfg)
        assert field in body, item_id
        return body.replace(field, field.replace("هنا:", f"هنا: {url}"))

    def segment(lines: list[str], start: int) -> str:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == "---"),
                   len(lines))
        return "\n".join(lines[start:end])

    try:
        # ═══ أ: الشكل — الأخبار: خبران، أحدهما مُعاد وبصورة ═══
        pub_img = "https://cdn.pub.example/p/ret.jpg"
        c_ret = mk_cand("ret", "خبر مُعاد بصورة ناشر", image=pub_img, issue=9101, returned=True)
        d_ret = _stage_news_draft(
            c_ret["id"], "خبر مُعاد بصورة ناشر",
            headlines=["عنوان ١", "عنوان ٢", "عنوان ٣"], headline_selected=0,
            reel_spec={"headline": "خبر مُعاد بصورة ناشر"})
        d_ret["status"] = "returned"
        d_ret["returned_from_stage"] = 2
        store.save_draft(d_ret)
        c_plain = mk_cand("plain", "خبر عادي بلا صورة", issue=9101)
        news_body = preselect.build_selection_issue_body([c_ret, c_plain], {}, cfg)
        print("\n----- قضية ترشيح الأخبار (خبران: الأول مُعاد وبصورة) كما بُنيت -----\n"
              + news_body + "\n-----")
        nlines = news_body.splitlines()
        check("(#1190-أ) الأخبار: الرأس stages.stage_header(1) ثم شرح المرحلة 1 الموحَّد",
              nlines[0] == stages.stage_header(1, cfg)
              and cfg.path("stages.explainer_stage1") in news_body, nlines[:4])
        check("(#1190-أ) فقرات الشرح القديمة (🚀/📝/🎴 والأحوط) حُذفت",
              "ثلاثة مربعات" not in news_body and "الأحوط يغلب" not in news_body
              and "سطر 🖼️ يبيّن" not in news_body)
        titles_at = [i for i, ln in enumerate(nlines) if "<!-- cand:" in ln]

        def box_before_title(lines: list[str], t: int) -> bool:
            prev = max([i for i in range(t) if lines[i].strip() == "---"], default=0)
            return any(re.match(r"\s*[-*]\s*\[", lines[j]) for j in range(prev, t + 1))
        check("(#1190-أ) لا «- [ ]» قبل سطر عنوان أي خبر ولا عليه",
              len(titles_at) == 2 and not any(box_before_title(nlines, t) for t in titles_at),
              titles_at)
        badge = cfg.path("stages.returned_badge").format(stage=2)
        check("(#1190-أ) الخبر المُعاد: «**1. ↩️ أعدته من المرحلة 2 · العنوان**» بعلامة cand: وحدها",
              nlines[titles_at[0]].startswith(f"**1. {badge} · خبر مُعاد")
              and nlines[titles_at[0]].rstrip().endswith(f"<!-- cand:{c_ret['id']} -->"))
        seg_ret = segment(nlines, titles_at[0])
        marks = [seg_ret.find(f"cand:{c_ret['id']}"), seg_ret.find("🏷️"),
                 seg_ret.find(f'<img src="{pub_img}" width="520"'),
                 seg_ret.find("🖼️ [صورة الناشر]"), seg_ret.find("↳ [الخبر الأصلي]"),
                 seg_ret.find(f"imgurl:{c_ret['id']}"),
                 seg_ret.find(cfg.path("stages.options_header"))]
        check("(#1190-أ) ترتيب أقسام الخبر: العنوان ← الشارات والمصادر ← الصورة معروضة ← سطر 🖼️ ← "
              "الخبر الأصلي ← حقل الصورة ← الانتقال",
              -1 not in marks and marks == sorted(marks), marks)
        seg_plain = segment(nlines, titles_at[1])
        check("(#1190-أ) خبر بلا صورة ناشر: لا <img> ويبقى سطر 🖼️ القائم",
              "<img" not in seg_plain and "🖼️ بلا صورة من الناشر" in seg_plain)
        check("(#1190-أ) كتلة الانتقال: go2 وgo3 وpublish بلا go1 (المرحلة 1)",
              all(f"<!-- go:{a}:{c_ret['id']} -->" in news_body for a in ("go2", "go3", "publish"))
              and "go:go1:" not in news_body)
        check("(#1190-أ) قبل التعليم لا إجراء مقروء من القضية",
              stages.read_actions(news_body, 1) == ({}, []))

        # ═══ أ: الشكل — التحليل: موضوع واحد ═══
        D1, D2, D3 = "2099-10-01", "2099-10-02", "2099-10-03"
        points = [
            {"video_id": "sw0", "bloc": "arabic", "channel": "الجزيرة", "speaker": "متحدث",
             "statement": "قول", "quote_arabic": "اقتباس", "type": "fact",
             "video_title": "فيديو", "video_url": "https://youtube.com/watch?v=sw0", "timestamp": 1},
            {"video_id": "sw1", "bloc": "turkish", "channel": "CNN Türk", "speaker": "متحدث٢",
             "statement": "قول٢", "quote_arabic": "اقتباس٢", "type": "fact",
             "video_title": "فيديو٢", "video_url": "https://youtube.com/watch?v=sw1", "timestamp": 2},
        ]
        for day in (D1, D2, D3):
            (ycl.POINTS_DIR / f"{day}.json").write_text(
                json.dumps(dict(points=points), ensure_ascii=False), encoding="utf-8")

        def mk_topic(title: str, single: bool = False) -> dict:
            if single:      # كتلة وقناة واحدة ← يمرّ بحارس المحظورات
                return dict(title=title, event=f"حدث {title}", layer=1, blocs=["arabic"],
                            channels=["الجزيرة"], agreement="agreement", point_ids=[0])
            return dict(title=title, event=f"حدث {title}", layer="a",
                        blocs=["arabic", "turkish"], channels=["الجزيرة", "CNN Türk"],
                        agreement="cross_source", point_ids=[0, 1])

        def write_topics(day: str, specs: list) -> None:
            topics = [mk_topic(*s) if isinstance(s, tuple) else mk_topic(s) for s in specs]
            (ycl.TOPICS_DIR / f"{day}.json").write_text(
                json.dumps(dict(run_date=day, topics=topics), ensure_ascii=False),
                encoding="utf-8")

        def topics_file(day: str) -> dict:
            return json.loads((ycl.TOPICS_DIR / f"{day}.json").read_text(encoding="utf-8"))

        def cfg_with(cap_articles: int, cap_publish: int = 3):
            c = load_config()
            c.setdefault("youtube", {}).setdefault("article", {}).update(
                count=9, max_per_run=cap_articles)
            c["youtube"].setdefault("publish", {}).update(
                spacing_minutes=0, max_per_run=cap_publish)
            return c

        def open_sel(day: str, cfg_a) -> dict:
            n0 = len(cap["created"])
            sel = ycl.open_selection(cfg_a, date_str=day)
            return dict(topics=sel["topics"], body=cap["created"][n0]["body"],
                        number=sel["issue"]["number"])

        def run_sel(sel: dict, ticks: dict, cfg_a, client, body: str | None = None) -> dict:
            """يعلّم المواضيع ثم publish.cmd_youtube_selection الحقيقية."""
            text = body if body is not None else sel["body"]
            for tid, action in ticks.items():
                text = tick_marker(text, f"<!-- go:{action}:{tid} -->")
            reset_cap()
            reset_last_publish()
            cap["code"] = publish_mod.cmd_youtube_selection(
                sel["number"], text, cfg_a, client=client)
            return dict(cap)

        write_topics(D1, ["موضوع التحليل الأول"])
        sel_a = open_sel(D1, cfg_with(5))
        topic_a = sel_a["topics"][0]
        print("\n----- قضية ترشيح التحليل (موضوع واحد) كما بُنيت -----\n"
              + sel_a["body"] + "\n-----")
        alines = sel_a["body"].splitlines()
        a_title = next(i for i, ln in enumerate(alines) if "<!-- topic:" in ln)
        check("(#1190-أ) التحليل: الرأس stages.stage_header(1) ثم شرح المرحلة 1 الموحَّد",
              next(ln for ln in alines if ln.startswith("###")) == stages.stage_header(1, cfg)
              and cfg.path("stages.explainer_stage1") in sel_a["body"]
              and "<!-- selection-date:" in alines[0], alines[:5])
        check("(#1190-أ) لا «- [ ]» قبل عنوان الموضوع ولا عليه، وعنوانه «**1. …**» بعلامة topic: وحدها",
              not any(re.match(r"\s*[-*]\s*\[", ln) for ln in alines[:a_title + 1])
              and alines[a_title].startswith("**1. موضوع التحليل الأول**")
              and alines[a_title].rstrip().endswith(f"<!-- topic:{topic_a['id']} -->"),
              alines[a_title])
        seg_a = segment(alines, a_title)
        marks = [seg_a.find("topic:"), seg_a.find("حدث موضوع"), seg_a.find("تقاطع "),
                 seg_a.find("«قول»"), seg_a.find(f"imgurl:{topic_a['id']}"),
                 seg_a.find(cfg.path("stages.options_header"))]
        check("(#1190-أ) ترتيب أقسام الموضوع: العنوان ← الحدث ← الكتل والقنوات والنقاط ← الاقتباسات ← "
              "حقل الصورة ← الانتقال",
              -1 not in marks and marks == sorted(marks), marks)
        check("(#1190-أ) كتلة الانتقال للتحليل: go2 وgo3 وpublish بلا go1",
              all(f"<!-- go:{a}:{topic_a['id']} -->" in sel_a["body"]
                  for a in ("go2", "go3", "publish")) and "go:go1:" not in sel_a["body"])
        check("(#1190-أ) علامة selection-date باقية وقراءة الإجراءات الموحَّدة فارغة قبل التعليم",
              ycl.SELECTION_DATE_RE.search(sel_a["body"]).group(1) == D1
              and stages.read_actions(sel_a["body"], 1) == ({}, []))

        # ═══ ب: الأخبار go2/go3/publish ← السلوك نفسه تمامًا لـ📝/🎴/🚀 القديمة ═══
        def scenario(kind: str, number: int) -> dict:
            roles = {"go2": "review", "go3": "sel-card", "publish": "now"}
            # صورة ناشر لكل خبر كي تُبنى البطاقة حتميًا (لا تتوقف النتيجة على بحث صور)
            cs = {r: mk_cand(f"{kind}-{r}", f"خبر {kind} دور {r} فريد", issue=number,
                             image=f"https://cdn.pub.example/p/{kind}-{r}.jpg")
                  for r in roles}
            order = [cs["go2"], cs["go3"], cs["publish"]]
            if kind == "new":
                body = preselect.build_selection_issue_body(order, {}, cfg)
                for r in roles:
                    body = tick_marker(body, f"<!-- go:{r}:{cs[r]['id']} -->")
            else:
                body = legacy_selection_body(order)
                for r, box in roles.items():
                    body = tick_marker(body, f"{box}:{cs[r]['id']}")
            calls["write"] = 0
            out = run_finalize(number, body)
            final_body = next((c["body"] for c in out["created"]
                               if c["labels"] == ["final-review"]), "")
            review_body = next((c["body"] for c in out["created"]
                                if c["labels"] == ["pending-review"]), "")
            return dict(
                writes=calls["write"], code=out["code"],
                labels=sorted(c["labels"][0] for c in out["created"]),
                published=len(out["published"]),
                status={r: state(cs[r]["id"])["status"] for r in roles},
                has_image={r: bool(state(cs[r]["id"]).get("image")) for r in roles},
                cand={r: cand_state(cs[r]["id"])["status"] for r in roles},
                closed=out["closed"] == [number],
                in_final=f"<!-- draft:{cs['go3']['id']} -->" in final_body,
                in_review=f"<!-- draft:{cs['go2']['id']} -->" in review_body)
        new_res, old_res = scenario("new", 9201), scenario("legacy", 9202)
        check("(#1190-ب) الأخبار: go2/go3/publish ← النتيجة نفسها تمامًا لـ📝/🎴/🚀 على القضية القديمة",
              new_res == old_res, (new_res, old_res))
        check("(#1190-ب) تفصيل النتيجة: ثلاث صياغات، go2 مسودة بلا بطاقة، go3 ببطاقة في قضية نهائية، "
              "publish نُشر",
              new_res["writes"] == 3 and new_res["labels"] == ["final-review", "pending-review"]
              and new_res["status"] == dict(go2="pending", go3="pending", publish="published")
              and new_res["has_image"] == dict(go2=False, go3=True, publish=True)
              and new_res["published"] == 1 and new_res["in_final"] and new_res["in_review"]
              and new_res["closed"], new_res)

        # ═══ ج: تعارض go2 + publish ← go2 وتعليق التعارض؛ بلا تعليم ← «لم يُختر» ═══
        c_conf = mk_cand("conf", "خبر عُلِّم عليه خياران معًا", issue=9301)
        c_none = mk_cand("none", "خبر ترك بلا تعليم", issue=9301)
        body_c = preselect.build_selection_issue_body([c_conf, c_none], {}, cfg)
        body_c = tick_marker(body_c, f"<!-- go:go2:{c_conf['id']} -->")
        body_c = tick_marker(body_c, f"<!-- go:publish:{c_conf['id']} -->")
        calls["write"] = 0
        out_c = run_finalize(9301, body_c)
        conflict_text = [t for _, t in out_c["comments"] if "أكثر من خيار انتقال" in t]
        check("(#1190-ج) go2 + publish ← go2 وحده (مسودة للمرحلة 2) بلا نشر وبصياغة واحدة",
              state(c_conf["id"])["status"] == "pending" and out_c["published"] == []
              and calls["write"] == 1
              and [c["labels"] for c in out_c["created"]] == [["pending-review"]],
              (calls, [c["labels"] for c in out_c["created"]]))
        check("(#1190-ج) تعليق التعارض يسمّي الخبر بعنوانه وخياريه والمنفَّذ",
              len(conflict_text) == 1 and c_conf["title"] in conflict_text[0]
              and stages.action_label("go2", 1, cfg) in conflict_text[0]
              and stages.action_label("publish", 1, cfg) in conflict_text[0], conflict_text)
        check("(#1190-ج) غير المُعلَّم ← «لم يُختر»: حالة المرشح وسجل القرارات",
              cand_state(c_none["id"])["status"] == "unselected"
              and any(e["id"] == c_none["id"] and e["decision"] == "unselected"
                      and e["reject_tag"] == "لم يُختر" for e in decisions.load()))
        body_empty = preselect.build_selection_issue_body(
            [mk_cand("none2", "خبر وحيد بلا تعليم", issue=9302)], {}, cfg)
        out_e = run_finalize(9302, body_empty)
        check("(#1190-ج) قضية بلا أي تعليم: تعليق «لم يُعلَّم على أي مرشح» وإزالة approved ولا صياغة",
              any("لم يُعلَّم على أي مرشح" in t for _, t in out_e["comments"])
              and (9302, "approved") in out_e["removed"] and out_e["created"] == [],
              out_e["comments"])

        # ═══ د: التحليل go2/go3/publish ═══
        write_topics(D1, ["تحليل ينتقل إلى المرحلة 2", "تحليل ينتقل إلى المرحلة 3", "تحليل ينشر"])
        cfg_d = cfg_with(5)
        sel_d = open_sel(D1, cfg_d)
        t_go2, t_go3, t_pub = sel_d["topics"]
        client_d = _CountingClient(
            _analysis_article_responses("هل ينتقل الأول؟", ["هل ينتقل الأول؟", "بديل ١", "بديل ٢"])
            + _analysis_article_responses("هل ينتقل الثاني؟", ["هل ينتقل الثاني؟", "بديل ١", "بديل ٢"])
            + _analysis_article_responses("هل ينشر الثالث؟", ["هل ينشر الثالث؟", "بديل ١", "بديل ٢"]))
        out_d = run_sel(sel_d, {t_go2["id"]: "go2", t_go3["id"]: "go3", t_pub["id"]: "publish"},
                        cfg_d, client_d)
        by_topic = {d["topic_id"]: d for d in all_drafts() if d.get("topic_id")}
        d_go2, d_go3, d_pub = (by_topic[t["id"]] for t in (t_go2, t_go3, t_pub))
        labels_d = [c["labels"] for c in out_d["created"]]
        check("(#1190-د) نداءات النموذج: مقال وعناوين لكل من الثلاثة (6) — الكتابة واحدة في الحالات الثلاث",
              len(client_d.messages.calls) == 6, len(client_d.messages.calls))
        check("(#1190-د) go2 ← كتابة ثم قضية المرحلة 2 (youtube-review) بلا بطاقة",
              state(d_go2["id"])["status"] == "pending" and "image" not in state(d_go2["id"])
              and any(c["labels"] == ["youtube-review"]
                      and f"<!-- draft:{d_go2['id']} -->" in c["body"] for c in out_d["created"])
              and state(d_go2["id"]).get("review_issue") is not None, labels_d)
        check("(#1190-د) go3 ← كتابة ثم بطاقة ثم قضية المرحلة 3 (final-review) بلا نشر",
              state(d_go3["id"])["status"] == "pending" and bool(state(d_go3["id"]).get("image"))
              and any(c["labels"] == ["final-review"]
                      and f"<!-- draft:{d_go3['id']} -->" in c["body"] for c in out_d["created"])
              and not any(f"<!-- draft:{d_go3['id']} -->" in c["body"]
                          for c in out_d["created"] if c["labels"] == ["youtube-review"]), labels_d)
        check("(#1190-د) publish ← كتابة ثم نشر (بطاقة بُنيت ونُشر) ولا قضية لمسودته",
              state(d_pub["id"])["status"] == "published" and bool(state(d_pub["id"]).get("image"))
              and len(out_d["published"]) == 1
              and not any(f"<!-- draft:{d_pub['id']} -->" in c["body"] for c in out_d["created"]),
              (state(d_pub["id"])["status"], len(out_d["published"])))
        check("(#1190-د) ترتيب القضايا: المرحلة 3 قبل المرحلة 2 (go3/publish قبل open_review)",
              labels_d == [["final-review"], ["youtube-review"]], labels_d)
        check("(#1190-د) الموضوعات الثلاثة attempted والـIssue أُغلق (لا شيء ينتظر)",
              {t["selection_status"] for t in topics_file(D1)["topics"]} == {"attempted"}
              and sel_d["number"] in out_d["closed"])

        # سقف النشر (youtube.publish.max_per_run): الفائض لا يضيع بل يصل قضية المرحلة 2
        write_topics(D1, ["تحليل ينشر أول", "تحليل ينشر ثانٍ"])
        cfg_cap = cfg_with(5, cap_publish=1)
        sel_cap = open_sel(D1, cfg_cap)
        c1, c2 = sel_cap["topics"]
        client_cap = _CountingClient(
            _analysis_article_responses("هل ينشر الأول؟", ["هل ينشر الأول؟", "بديل ١", "بديل ٢"])
            + _analysis_article_responses("هل ينشر الثاني؟", ["هل ينشر الثاني؟", "بديل ١", "بديل ٢"]))
        out_cap = run_sel(sel_cap, {c1["id"]: "publish", c2["id"]: "publish"}, cfg_cap, client_cap)
        by_topic = {d["topic_id"]: d for d in all_drafts() if d.get("topic_id")}
        st_cap = sorted(by_topic[t["id"]]["status"] for t in (c1, c2))
        check("(#1190-د) publish بسقف النشر (1): نُشر واحد والثاني بقي pending وأُرسل لقضية المرحلة 2",
              st_cap == ["pending", "published"] and len(out_cap["published"]) == 1
              and any("تجاوز سقف النشر" in t for _, t in out_cap["comments"])
              and any(c["labels"] == ["youtube-review"] for c in out_cap["created"]),
              (st_cap, [c["labels"] for c in out_cap["created"]]))

        # ═══ هـ: حارس المحظورات يرفض موضوعًا ← لا نشر، ويُسجَّل كما اليوم ═══
        write_topics(D1, [("ممنوع بنشر", True), ("ممنوع بمرحلة 2", True)])
        cfg_g = cfg_with(5)
        sel_g = open_sel(D1, cfg_g)
        g1, g2 = sel_g["topics"]

        def block():
            return _FakeResp([_FakeBlock("tool_use", input_=dict(
                blocked=True, category=youtube_article.FORBIDDEN_CATEGORIES[0],
                reason="اتهام مسمّى بلا مصدر ثانٍ"))])
        client_g = _CountingClient([block(), block()])
        drafts_before = len(all_drafts())
        out_g = run_sel(sel_g, {g1["id"]: "publish", g2["id"]: "go2"}, cfg_g, client_g)
        skip_lines = [ln for _, t in out_g["comments"] for ln in t.splitlines() if "⏭️" in ln]
        check("(#1190-هـ) publish مع حارس يرفض ← لا مسودة ولا نشر ولا قضية، ونداء الحارس وحده",
              len(all_drafts()) == drafts_before and out_g["published"] == []
              and out_g["created"] == [] and len(client_g.messages.calls) == 2,
              (len(all_drafts()), drafts_before, len(client_g.messages.calls)))
        check("(#1190-هـ) يُسجَّل كما اليوم: سطر ⏭️ بسبب «محظورة» لكل من publish وgo2 وحالة attempted",
              len(skip_lines) == 2 and all("محظورة" in ln for ln in skip_lines)
              and {t["selection_status"] for t in topics_file(D1)["topics"]} == {"attempted"},
              skip_lines)

        # ═══ و: قضيتا ترشيح بالشكل القديم ← تعملان كما كانتا ═══
        # (قضية الأخبار القديمة غُطّيت في (ب) مقارنةً بالجديدة؛ هنا قضية التحليل القديمة)
        write_topics(D1, ["تحليل بقضية قديمة"])
        sel_old = open_sel(D1, cfg_with(5))
        old_tid = sel_old["topics"][0]["id"]
        old_body = legacy_youtube_selection_body(D1, sel_old["topics"])
        old_body = tick_marker(old_body, f"topic:{old_tid}")
        check("(#1190-و) قضية التحليل القديمة: القارئ الموحَّد يعيد go2 للمعلَّم عبر legacy_actions",
              stages.read_actions(old_body, 1) == ({old_tid: "go2"}, []))
        client_o = _CountingClient(_analysis_article_responses(
            "هل تعمل القديمة؟", ["هل تعمل القديمة؟", "بديل ١", "بديل ٢"]))
        out_o = run_sel(sel_old, {}, cfg_with(5), client_o, body=old_body)
        d_old = next(d for d in all_drafts() if d.get("topic_id") == old_tid)
        check("(#1190-و) قضية التحليل القديمة ← كتابة ثم قضية المرحلة 2 كما كانت",
              len(client_o.messages.calls) == 2 and state(d_old["id"])["status"] == "pending"
              and any(c["labels"] == ["youtube-review"] for c in out_o["created"])
              and out_o["published"] == [])
        legacy_conf = legacy_selection_body([mk_cand("lc", "خبر بقضية قديمة متعارضة", issue=9401)])
        lc_id = preselect.all_candidate_ids(legacy_conf)[0]
        legacy_conf = tick_marker(tick_marker(legacy_conf, f"now:{lc_id}"), f"review:{lc_id}")
        out_lc = run_finalize(9401, legacy_conf)
        check("(#1190-و) قضية الأخبار القديمة بتعارض: تعليق التعارض باقٍ والأحوط go2",
              any("أكثر من خيار انتقال" in t for _, t in out_lc["comments"])
              and state(lc_id)["status"] == "pending" and out_lc["published"] == [])

        # ═══ ز: رابط صورة في ترشيح أخبار ═══
        mine, mine_b = "https://cdn.example/mine.jpg", "https://cdn.example/mine-b.jpg"
        c_go2 = mk_cand("img2", "خبر بصورة المراجع ينتقل للمرحلة 2",
                        image="https://cdn.pub.example/p/a.jpg", issue=9501)
        c_go3 = mk_cand("img3", "خبر بصورة المراجع ينتقل للبطاقة", issue=9501)
        body_g = preselect.build_selection_issue_body([c_go2, c_go3], {}, cfg)
        pasted = fill_field(fill_field(body_g, c_go2["id"], mine), c_go3["id"], mine_b)
        out_gi = run_setimage(9501, pasted)
        upd = out_gi["updated"][-1] if out_gi["updated"] else ""
        check("(#1190-ز) رابط صالح ← manual_image على المرشح (بالتحميل الفوري بقواعد download_image)",
              out_gi["code"] == 0 and cand_state(c_go2["id"]).get("manual_image") == mine
              and cand_state(c_go3["id"]).get("manual_image") == mine_b,
              (out_gi["code"], cand_state(c_go2["id"]).get("manual_image")))
        check("(#1190-ز) التعليق «حُفظت الصورة — تُستعمل عند الصياغة» ومُسح الحقلان",
              any("حُفظت الصورة — تُستعمل عند الصياغة" in t for _, t in out_gi["comments"])
              and stages.image_field(c_go2["id"], cfg) in upd
              and f"هنا: {mine}" not in upd and f"هنا: {mine_b}" not in upd, out_gi["comments"])
        check("(#1190-ز) الصورة اليدوية تُعرض في القضية بدل صورة الناشر (استبدال وإدراج)",
              f'<img src="{mine}" width="520" />' in upd
              and f'<img src="{mine_b}" width="520" />' in upd
              and "https://cdn.pub.example/p/a.jpg" not in upd
              and f"🖼️ [صورتك]({mine})" in upd, upd)
        check("(#1190-ز) القضية بعد التبديل ما زالت تُقرأ كاملة (المعرّفات والخيارات سليمة)",
              preselect.all_candidate_ids(upd) == [c_go2["id"], c_go3["id"]]
              and f"<!-- go:go2:{c_go2['id']} -->" in upd)
        calls["build"].clear()
        calls["write"] = 0
        upd = tick_marker(tick_marker(upd, f"<!-- go:go2:{c_go2['id']} -->"),
                          f"<!-- go:go3:{c_go3['id']} -->")
        run_finalize(9501, upd)
        check("(#1190-ز) go2 ← المسودة تحمل manual_image ونُفِّذت صياغتان",
              state(c_go2["id"]).get("manual_image") == mine and calls["write"] == 2
              and state(c_go3["id"]).get("manual_image") == mine_b, calls["write"])
        check("(#1190-ز) go3 ← بطاقتها بُنيت بالرابط اليدوي وحده (يغلب صورة الناشر)",
              bool(state(c_go3["id"]).get("image")) and calls["build"] == [[mine_b]],
              calls["build"])
        path_go2, draft_go2 = store.load_draft(c_go2["id"])
        calls["build"].clear()
        cards_mod.ensure(path_go2, draft_go2, cfg)
        check("(#1190-ز) بطاقة go2 عند اعتماد المرحلة 2 تُبنى بالرابط اليدوي لا بصورة الناشر",
              calls["build"] == [[mine]], calls["build"])

        # فشل الرابط: يُمسح الحقل والتعليق فيه الرابط والسبب
        c_bad = mk_cand("imgbad", "خبر برابط صورة فاشل", issue=9502)
        body_bad = preselect.build_selection_issue_body([c_bad], {}, cfg)
        bad = "https://cdn.example/bad-photo.html"
        out_bad = run_setimage(9502, fill_field(body_bad, c_bad["id"], bad))
        check("(#1190-ز) رابط فاشل ← لا manual_image والحقل يُمسح",
              out_bad["code"] == 1 and "manual_image" not in cand_state(c_bad["id"])
              and bad not in out_bad["updated"][-1]
              and stages.image_field(c_bad["id"], cfg) in out_bad["updated"][-1],
              out_bad["code"])
        check("(#1190-ز) تعليق الفشل فيه الرابط والسبب",
              any(bad in t and "HTTP 404" in t and "السبب" in t for _, t in out_bad["comments"]),
              out_bad["comments"])

        # مرشح مُعاد بصورة المراجع ← go3 ← بلا كتابة، والبطاقة تُعاد حول الرابط
        out_rs = run_setimage(9101, fill_field(news_body, c_ret["id"], mine))
        check("(#1190-ز) رابط على مرشح مُعاد (له مسودة returned بمعرّفه) يُحفظ على المرشح لا المسودة",
              cand_state(c_ret["id"]).get("manual_image") == mine
              and "manual_image" not in state(c_ret["id"])
              and state(c_ret["id"])["status"] == "returned", out_rs["comments"])
        body_rs = tick_marker(out_rs["updated"][-1], f"<!-- go:go3:{c_ret['id']} -->")
        calls["write"], calls["build"] = 0, []
        out_rf = run_finalize(9101, body_rs)
        check("(#1190-ط) خبر مُعاد يُختار بـgo3 ← بلا كتابة (العدّاد 0) والبطاقة بالرابط اليدوي",
              calls["write"] == 0 and state(c_ret["id"])["status"] == "pending"
              and state(c_ret["id"]).get("manual_image") == mine
              and calls["build"] == [[mine]]
              and any(c["labels"] == ["final-review"] for c in out_rf["created"]),
              (calls, [c["labels"] for c in out_rf["created"]]))

        # ═══ ح: رابط صورة في ترشيح تحليل ═══
        write_topics(D1, ["تحليل بصورة المراجع"])
        cfg_h = cfg_with(5)
        sel_h = open_sel(D1, cfg_h)
        th = sel_h["topics"][0]
        calls["build"].clear()
        out_hi = run_setimage(sel_h["number"], fill_field(sel_h["body"], th["id"], mine))
        topic_saved = next(t for t in topics_file(D1)["topics"] if t["id"] == th["id"])
        check("(#1190-ح) رابط في ترشيح تحليل ← manual_image على الموضوع بلا تحميل ولا بناء",
              out_hi["code"] == 0 and topic_saved.get("manual_image") == mine
              and calls["build"] == [], (out_hi["code"], topic_saved.get("manual_image")))
        check("(#1190-ح) التعليق «حُفظت الصورة — تُستعمل عند بناء البطاقة» ومُسح الحقل",
              any("حُفظت الصورة — تُستعمل عند بناء البطاقة" in t for _, t in out_hi["comments"])
              and f"هنا: {mine}" not in out_hi["updated"][-1], out_hi["comments"])
        client_h = _CountingClient(_analysis_article_responses(
            "هل تظهر صورتي؟", ["هل تظهر صورتي؟", "بديل ١", "بديل ٢"]))
        photo.update(free=0, news=0)
        out_h = run_sel(sel_h, {th["id"]: "go3"}, cfg_h, client_h, body=out_hi["updated"][-1])
        d_h = next(d for d in all_drafts() if d.get("topic_id") == th["id"])
        check("(#1190-ح) الكتابة تنقل manual_image من الموضوع إلى المسودة",
              d_h.get("manual_image") == mine, d_h.get("manual_image"))
        check("(#1190-ح) go3 ← البطاقة بالرابط اليدوي (manual) ولا مزوّد خبر استُدعي، وقضية المرحلة 3",
              bool(d_h.get("image")) and d_h["image_info"].get("manual") is True
              and d_h["image_info"].get("chosen_url") == mine and photo["news"] == 0
              and any(c["labels"] == ["final-review"] for c in out_h["created"]),
              (d_h.get("image_info"), photo))

        # ═══ ط: موضوع مُعاد يُختار بـgo3 أو publish ← بلا كتابة (العدّاد 0) ═══
        write_topics(D1, ["تحليل يعود من المرحلة 2", "تحليل يعود من المرحلة 3"])
        cfg_i = cfg_with(5)
        sel_i0 = open_sel(D1, cfg_i)
        ti2, ti3 = sel_i0["topics"]
        client_i0 = _CountingClient(
            _analysis_article_responses("هل يعود الأول؟", ["هل يعود الأول؟", "بديل ١", "بديل ٢"])
            + _analysis_article_responses("هل يعود الثاني؟", ["هل يعود الثاني؟", "بديل ١", "بديل ٢"]))
        run_sel(sel_i0, {ti2["id"]: "go2", ti3["id"]: "go3"}, cfg_i, client_i0)
        by_topic = {d["topic_id"]: d for d in all_drafts() if d.get("topic_id")}
        di2, di3 = by_topic[ti2["id"]], by_topic[ti3["id"]]
        reset_cap()
        publish_mod.return_to_selection([di2["id"]], 2)
        publish_mod.return_to_selection([di3["id"]], 3)
        check("(#1190-ط) تمهيد: المسودتان returned والموضوعان returned في ملف تاريخهما",
              state(di2["id"])["status"] == "returned" and state(di3["id"])["status"] == "returned"
              and {t["selection_status"] for t in topics_file(D1)["topics"]} == {"returned"})
        sel_i = open_sel(D2, cfg_i)
        badge2, badge3 = (cfg.path("stages.returned_badge").format(stage=n) for n in (2, 3))
        check("(#1190-ط) قضية الترشيح التالية: الموضوعان المُعادان بشارتيهما وبلا مربع على العنوان",
              len(sel_i["topics"]) == 2 and badge2 in sel_i["body"] and badge3 in sel_i["body"]
              and not any(re.match(r"\s*[-*]\s*\[", ln) and "<!-- topic:" in ln
                          for ln in sel_i["body"].splitlines()))
        client_i = _CountingClient([])         # أي نداء نموذج ينهار فيفشل الاختبار
        out_i = run_sel(sel_i, {ti2["id"]: "go3", ti3["id"]: "publish"}, cfg_i, client_i)
        check("(#1190-ط) المُعاد يُختار بـgo3 أو publish ← عدّاد النموذج 0 (بلا كتابة)",
              len(client_i.messages.calls) == 0 and out_i["code"] == 0,
              len(client_i.messages.calls))
        check("(#1190-ط) المُعاد بـgo3 ← بطاقة وقضية المرحلة 3 بلا نشر",
              state(di2["id"])["status"] == "pending" and bool(state(di2["id"]).get("image"))
              and any(c["labels"] == ["final-review"]
                      and f"<!-- draft:{di2['id']} -->" in c["body"] for c in out_i["created"]),
              state(di2["id"]).get("status"))
        check("(#1190-ط) المُعاد بـpublish ← نُشر بسقف النشر بلا كتابة",
              state(di3["id"])["status"] == "published" and len(out_i["published"]) == 1,
              state(di3["id"])["status"])
        check("(#1190-ط) لا نسخة مسودة ثانية: مسودة واحدة لكل موضوع مُعاد",
              len([d for d in all_drafts() if d.get("topic_id") in (ti2["id"], ti3["id"])]) == 2)
    finally:
        sys.argv = real_argv
        collect_finalize.write_arabic = real_write
        cards_mod._default_build_post_image = real_build
        for (m, k), v in zip(patched, real):
            setattr(m, k, v)
        if real_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo
        if seen_backup is None:
            ycl.SEEN_PATH.unlink(missing_ok=True)
        else:
            ycl.SEEN_PATH.write_text(seen_backup, encoding="utf-8")
