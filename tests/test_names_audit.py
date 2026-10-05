"""اختبارات تدقيق أسماء الأشخاص على مخرَج الأنبوب (Issue #1252): مسودة 4e1ba01e960a الحقيقية عبر
collect_finalize (🚀)، وتعليق التنبيه، والتعلّم من تحرير المرحلة 2 عبر publish.main، وعدّاد Brave الخاص
بالأسماء. حالات الحارس g52–g56 في tests/test_guards_golden.py:test_names_audit_guards."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from tests.helpers import (
    DRAFTS_DIR, NAMES_AUDIT_SOURCE, NamesAuditRig, check, facebook, imagesearch, load_config,
    names_audit_doubt, names_audit_draft, names_audit_hit, reset_last_publish, review, store,
    tick_marker, writer,
)
from src.sources import Article

WRONG, RIGHT = "فريدة المسلمي", "فارع المسلمي"
TWO_DOMAINS = [names_audit_hit("https://www.aljazeera.net/a", RIGHT),
               names_audit_hit("https://www.alaraby.co.uk/b", RIGHT)]
FMT_URL = "https://www.freemalaysiatoday.com/category/world/2026/10/04/houthis-cut-vital-supply-road"


def _written_from_real_draft() -> dict:
    """حقول الكتابة بما في مسودة 4e1ba01e960a الحقيقية (نصها كما نُشر، بالاسم الخاطئ)."""
    real = json.loads((Path(__file__).resolve().parent.parent
                       / "drafts/2026-10-04/4e1ba01e960a.json").read_text(encoding="utf-8"))
    return dict(real["arabic"])


def _candidate(link: str) -> dict:
    from src import preselect
    art = Article(title="Houthis cut vital supply road to Yemen’s Taiz", link=link,
                  summary="", source_name="Free Malaysia Today", region="my", weight=1.0,
                  published=datetime.now(timezone.utc), bucket="serious",
                  publisher="Free Malaysia Today")
    art.cluster_sources = ["Free Malaysia Today", "Malay Mail"]
    art.cluster_members = [{"name": "Free Malaysia Today", "link": link}]
    cand = preselect.build_candidate(art)
    store.save_candidate(cand)
    return cand


def _finalize_publish_now(cand: dict, issue: int, rig: NamesAuditRig, mark_published: bool):
    """🚀 على مرشح واحد، بالكاتب الحقيقي المزيَّف (نص المسودة الحقيقية) والمصدر الإنجليزي."""
    from src import collect_finalize, preselect
    from src import publish as publish_mod

    written = _written_from_real_draft()
    docs = [{"name": "Malay Mail", "link": FMT_URL, "text": NAMES_AUDIT_SOURCE[0]}]
    saved = (collect_finalize.write_arabic, collect_finalize.gather_texts, publish_mod.cmd_burst,
             review.comment, review.close_issue, collect_finalize.cards.ensure)
    comments: list[str] = []

    def fake_burst(ids, cfg, issue_number, only_urgent=False, skip_urgent=False,
                   inline_cap_minutes=None):
        if mark_published:
            for did in ids:
                path, _d = store.load_draft(did)
                store.update_draft(path, status="published",
                                   published_at=datetime.now(timezone.utc).isoformat(),
                                   facebook={"url": "https://fb.example/posts/777", "id": "777"})
        return 0

    collect_finalize.write_arabic = lambda art, cfg, previous_post=None, source_docs=None: dict(written)
    collect_finalize.gather_texts = lambda members, limit=2: (docs, [])
    publish_mod.cmd_burst = fake_burst
    collect_finalize.cards.ensure = lambda path, draft, cfg, **kw: path   # البطاقة ليست موضوع الاختبار
    review.comment = lambda n, text: comments.append(text)
    review.close_issue = lambda n: None
    try:
        body = preselect.build_selection_issue_body([cand])
        marked = tick_marker(body, f"now:{cand['id']}")
        code = collect_finalize.finalize(issue, marked, load_config())
    finally:
        (collect_finalize.write_arabic, collect_finalize.gather_texts, publish_mod.cmd_burst,
         review.comment, review.close_issue, collect_finalize.cards.ensure) = saved
    return code, comments


def test_names_audit_pipeline() -> None:
    """(a) 🚀 من الترشيح بنص 4e1ba01e960a الحقيقي: «فارع المسلمي» في المحفوظ وسطر ✏️ في القضية؛
    (b) نفسه بلا دليل بحث كافٍ: يُنشر كما هو وتعليق ⚠️ بالاسم ورابط المنشور؛ وقضيتا المرحلتين 2 و3
    تعرضان التنبيه والتصحيح لمسودة أخبار (لا «هام» وحدها)."""
    from src import names_audit

    # ── (a) ──
    cand = _candidate(FMT_URL + "-a")
    with NamesAuditRig([names_audit_doubt()], {RIGHT: TWO_DOMAINS}) as rig:
        code, comments = _finalize_publish_now(cand, 7001, rig, mark_published=False)
        saved_names = names_audit.load_verified()["entries"]
    draft = store.load_draft(cand["id"])[1]
    check("(a) finalize 🚀 انتهى بنجاح", code == 0, code)
    check("(a) «فارع المسلمي» في النص المحفوظ (التعليق والتحليل والعنوان المقترح) ولا أثر للخاطئ",
          RIGHT in draft["caption"] and RIGHT in draft["arabic"]["analysis"]
          and WRONG not in " ".join([draft["caption"], draft["arabic"]["analysis"], *draft["headlines"]]),
          draft["caption"][-200:])
    check("(a) النص غير الاسمي لم يتغيّر حرفًا", draft["arabic"]["post_title"] == _written_from_real_draft()["post_title"])
    check("(a) حُفظ الاسم في names_verified", any(e["arabic"] == RIGHT for e in saved_names.values()), saved_names)
    line = f"✏️ صُحّح اسم: {WRONG} ← {RIGHT} (مصدران: aljazeera.net، alaraby.co.uk)"
    check("(a) السطر ✏️ في قضية الترشيح", any(line in c for c in comments), comments)
    check("(a) لا تنبيه «لم يُحسم» ولا تعليق ⚠️", not draft.get("warnings") and not any("⚠️" in c for c in comments), comments)
    check("(a) نداء كشف واحد", len(rig.detect_calls) == 1, len(rig.detect_calls))

    # قضيتا المرحلتين 2 و3: التصحيح سطر والتنبيه قسم، لمسودة أخبار
    stage2 = review.build_issue_body([draft], "u/r", "main")
    stage3 = review.build_final_review_body([draft], "u/r", "main")
    check("(a) قضية المرحلة 2 تعرض سطر ✏️", line in stage2, stage2[:300])
    check("(a) قضية المرحلة 3 تعرض سطر ✏️", line in stage3)
    warned = {**draft, "warnings": ["اسم لم يُحسم: س (S) — سبب"]}
    check("(a) «⚠️ تنبيهات للمراجعة» لمسودة أخبار في المرحلتين 2 و3",
          "⚠️ تنبيهات للمراجعة" in review.build_issue_body([warned], "u/r", "main")
          and "⚠️ تنبيهات للمراجعة" in review.build_final_review_body([warned], "u/r", "main"))

    # ── (b) ──
    cand = _candidate(FMT_URL + "-b")
    with NamesAuditRig([names_audit_doubt()], {RIGHT: TWO_DOMAINS[:1]}) as rig:
        code, comments = _finalize_publish_now(cand, 7002, rig, mark_published=True)
    draft = store.load_draft(cand["id"])[1]
    check("(b) 🚀 مع اسم لم يُحسم: نُشر", code == 0 and draft["status"] == "published", draft["status"])
    check("(b) نُشر كما هو بلا تغيير", WRONG in draft["caption"] and RIGHT not in draft["caption"])
    expected = f"⚠️ نُشر وفيه اسم لم يُحسم: {WRONG} (Farea al-Muslimi) — "
    check("(b) تعليق التنبيه على القضية بالاسم ورابط المنشور",
          any(expected in c and "https://fb.example/posts/777" in c for c in comments), comments)
    check("(b) والتنبيه محفوظ في warnings المسودة",
          any(w.startswith(f"اسم لم يُحسم: {WRONG}") for w in draft.get("warnings", [])), draft.get("warnings"))


def test_names_audit_prevention_writer() -> None:
    """بند 2: أسماء names_verified التي يرد أصلها اللاتيني في المصدر تدخل برومبت الكاتب الحقيقي
    («اكتب هذه الأسماء هكذا»)؛ وبلا اسم محفوظ لا يتغيّر البرومبت."""
    from src import names_audit

    spec = importlib.util.spec_from_file_location("src.writer_real", writer.__file__)
    real = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real)
    prompts: list[str] = []
    real._call_model = lambda prompt, cfg, retries=3: (prompts.append(prompt) or {
        "newsworthy": True, "post_title": "t", "post_body": "b", "category": "عالم"})
    art = Article(title="Houthis cut road", link="https://x.example/1", summary="", source_name="s",
                  region="r", weight=1.0, published=datetime.now(timezone.utc), publisher="s")
    docs = [{"name": "Malay Mail", "text": NAMES_AUDIT_SOURCE[0], "link": "https://m.example/1"}]
    cfg = load_config()
    with NamesAuditRig([], {}) as rig:
        real.write_arabic(art, cfg, source_docs=docs)
        names_audit._remember("Farea al-Muslimi", RIGHT, WRONG, ["aljazeera.net", "alaraby.co.uk"], "بحث")
        real.write_arabic(art, cfg, source_docs=docs)
    check("بلا اسم محفوظ: لا قائمة أسماء في البرومبت", "اكتب هذه الأسماء هكذا" not in prompts[0])
    check("باسم محفوظ ورد أصله في المصدر: القائمة في البرومبت بالرسم المعتمد",
          "اكتب هذه الأسماء هكذا" in prompts[1] and f"Farea al-Muslimi ← {RIGHT}" in prompts[1], prompts[1][-400:])
    check("لا قائمة لاسم لم يرد أصله في المصدر",
          names_audit.names_note(["Nothing relevant here"], cfg) == "")


def test_names_audit_review_learning() -> None:
    """(c) المرحلة 2: المراجع يستبدل اسمًا في النص ثم يعتمد ← names_verified يحفظه («تصحيح المراجع»)
    والمسودة التالية بالاسم نفسه في المصدر تُكتب به بلا أي بحث."""
    from src import names_audit
    from src import publish as publish_mod

    draft = names_audit_draft()
    draft.update(id="ca5200000001", image="drafts/na.jpg")
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    (DRAFTS_DIR / "na.jpg").write_bytes(b"\xff\xd8\xff")
    # التدقيق الأول لم يحسم (نطاق واحد) فبقي الخاطئ في النص وسُجّل اسمه بأصله اللاتيني
    with NamesAuditRig([names_audit_doubt()], {RIGHT: TWO_DOMAINS[:1]}) as rig:
        names_audit.run(draft, NAMES_AUDIT_SOURCE, load_config())
        store.save_draft(draft)

        body = review.build_issue_body([draft], "u/r", "main")
        marked = tick_marker(body, f"<!-- go:publish:{draft['id']} -->")
        edited = marked.replace(WRONG, RIGHT)
        # بعد التحرير يرى الكاشف الرسم الجديد لأصله نفسه
        rig.detections = lambda texts, arabic: [
            {"arabic": RIGHT, "latin": "Farea al-Muslimi", "verdict": "sound"}]

        real = (publish_mod.fetch_issue, publish_mod.ROOT, facebook.publish_photo,
                review.comment, review.close_issue)
        publish_mod.ROOT = DRAFTS_DIR.parent
        facebook.publish_photo = lambda image_path, caption, api_version, first_comment=None: {
            "url": "https://fb.example/c", "id": "c"}
        review.comment = lambda n, t: None
        review.close_issue = lambda n: None
        publish_mod.fetch_issue = lambda n: {"number": n, "body": edited, "labels": [{"name": "approved"}]}
        reset_last_publish()
        sys.argv = ["publish", "--issue", "9052", "--now"]
        try:
            code = publish_mod.main()
        finally:
            (publish_mod.fetch_issue, publish_mod.ROOT, facebook.publish_photo,
             review.comment, review.close_issue) = real
        entries = names_audit.load_verified()["entries"]
        entry = entries.get("farea al muslimi") or {}
        check("(c) publish.main بعد تحرير الاسم انتهى بنجاح", code == 0, code)
        check("(c) names_verified يحفظ الاسم بمصدر «تصحيح المراجع» وأصله اللاتيني ورسمه الخاطئ السابق",
              entry.get("arabic") == RIGHT and entry.get("source_kind") == "تصحيح المراجع"
              and entry.get("wrong") == [WRONG], entries)
        check("(c) والنص المنشور هو المحرَّر", RIGHT in store.load_draft(draft["id"])[1]["caption"])

        # المسودة التالية: الاسم الخاطئ نفسه والمصدر نفسه — تُصحَّح بلا بحث ولا حاجة لحكم الكاشف بالشك
        rig.detections = [names_audit_doubt()]
        rig.http_calls.clear()
        nxt = names_audit_draft()
        nxt["id"] = "ca5200000002"
        names_audit.run(nxt, NAMES_AUDIT_SOURCE, load_config())
        check("(c) المسودة التالية تُكتب بالاسم المعتمد بلا أي طلب بحث",
              RIGHT in nxt["caption"] and WRONG not in nxt["caption"] and rig.http_calls == [], rig.http_calls)

        # البحث لا ينقض تصحيح المراجع
        names_audit._remember("Farea al-Muslimi", "فارعة المسلمي", RIGHT, ["x.com", "y.com"], "بحث")
        check("(c) تصحيح المراجع يغلب البحث: مدخل بحث لاحق لا ينقضه",
              names_audit.load_verified()["entries"]["farea al muslimi"]["arabic"] == RIGHT)


def test_names_audit_brave_counter() -> None:
    """(d) عدّاد Brave الخاص بالأسماء («names:YYYY-MM») منفصل عن عدّادي الصور و«هام»، وسقفه
    names.audit.brave_monthly_cap يُحترم، وبلوغه لا يوقف الكتابة: المشكوك فيه تنبيه والمسودة تُحفظ."""
    from src import names_audit

    cfg = copy.deepcopy(load_config())
    cfg["names"]["audit"]["brave_monthly_cap"] = 2
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    check("الإعداد: سقف الأسماء 100 وسقف صور البطاقات 300 والمجموع مع «هام» 1000",
          load_config().path("names.audit.brave_monthly_cap") == 100
          and load_config().path("image.web_search.monthly_cap") == 300
          and (load_config().path("names.audit.brave_monthly_cap")
               + load_config().path("image.web_search.monthly_cap")
               + load_config().path("important.brave_monthly_cap")) == 1000)

    draft = names_audit_draft()
    with NamesAuditRig([names_audit_doubt()], {RIGHT: TWO_DOMAINS}) as rig:
        imagesearch.BRAVE_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        imagesearch.BRAVE_USAGE_FILE.write_text(
            json.dumps({month: 5, f"important:{month}": 7}), encoding="utf-8")
        names_audit.run(draft, NAMES_AUDIT_SOURCE, cfg)
        usage = json.loads(imagesearch.BRAVE_USAGE_FILE.read_text(encoding="utf-8"))
        check("عدّاد الأسماء بمفتاحه الخاص، وعدّادا الصور و«هام» كما هما",
              usage.get(f"names:{month}") == 2 and usage.get(month) == 5
              and usage.get(f"important:{month}") == 7, usage)
        check("السقف يُحترم: طلبان فقط ولا ثالث بعد البلوغ", len(rig.http_calls) == 2, rig.http_calls)
        check("بلوغ السقف لا يوقف الكتابة: يتحوّل المشكوك إلى تنبيه بسببه والنص كما هو",
              any(w.startswith(f"اسم لم يُحسم: {WRONG}") and "بلغ سقف" in w for w in draft.get("warnings", []))
              and WRONG in draft["caption"], draft.get("warnings"))
        path = store.save_draft(draft)
        check("والمسودة تُحفظ", path.exists())

        # ذاكرة 7 أيام: الاستعلام نفسه لا يعيد طلبًا ولا يزيد العدّاد
        before = len(rig.http_calls)
        names_audit.run(names_audit_draft(), NAMES_AUDIT_SOURCE, cfg)
        usage2 = json.loads(imagesearch.BRAVE_USAGE_FILE.read_text(encoding="utf-8"))
        check("نتائج الاستعلام المخزَّنة (ذاكرة البحث) لا تُطلب ثانية ولا تُعدّ",
              len(rig.http_calls) == before and usage2.get(f"names:{month}") == 2, (before, usage2))

    with NamesAuditRig([names_audit_doubt()], {RIGHT: TWO_DOMAINS}, key=None) as rig:
        d2 = names_audit_draft()
        names_audit.run(d2, NAMES_AUDIT_SOURCE, cfg)
        check("بلا BRAVE_API_KEY: لا طلب، تنبيه، والنص كما هو",
              rig.http_calls == [] and WRONG in d2["caption"]
              and any("اسم لم يُحسم" in w for w in d2.get("warnings", [])), d2.get("warnings"))

    with NamesAuditRig([names_audit_doubt()], {}) as rig:
        names_audit._detect = lambda texts, arabic, cfg: (_ for _ in ()).throw(RuntimeError("boom"))
        d3 = names_audit_draft()
        before = json.dumps(d3, ensure_ascii=False)
        report = names_audit.run(d3, NAMES_AUDIT_SOURCE, cfg)
        check("فشل الكشف لا يكسر الكتابة: النص كما هو وتقرير فارغ",
              json.dumps(d3, ensure_ascii=False) == before and not report["corrections"], report)


def test_names_audit_other_sites() -> None:
    """مواضع الكتابة الأخرى المربوطة: الرادار (radar.build_draft، ومنه request.py) و«هام»
    (important_write.write_point) — كلاهما يمرّ بالتدقيق قبل الحفظ."""
    from src import important, important_finalize, radar
    from tests.helpers import (ImportantWriteRig, important_good_data, important_marked_body,
                               important_synthetic_point)

    cfg = load_config()

    # الرادار: build_draft يدقّق قبل أن يعيد المسودة
    written = names_audit_draft()["arabic"]
    art = Article(title="Houthis cut road", link="https://x.example/radar", summary="", source_name="s",
                  region="r", weight=1.0, published=datetime.now(timezone.utc), publisher="s")
    real = (radar.write_arabic, radar.enrich_image)
    radar.write_arabic = lambda a, c, source_docs=None: dict(written)
    radar.enrich_image = lambda a: a
    try:
        with NamesAuditRig([names_audit_doubt()], {RIGHT: TWO_DOMAINS}):
            d = radar.build_draft(art, cfg, docs=[{"name": "MM", "text": NAMES_AUDIT_SOURCE[0], "link": "x"}])
    finally:
        radar.write_arabic, radar.enrich_image = real
    check("الرادار: الاسم يُصحَّح قبل إعادة المسودة", d is not None and RIGHT in d["caption"]
          and WRONG not in d["caption"], d and d["caption"][-120:])

    # «هام»: write_point يدقّق بنصوص الأدلة قبل الحفظ، والتنبيه يُلحَق بتنبيهاته
    point = important_synthetic_point("confirmed")
    point["selection_issue"] = 96852
    result = {"issue": 96851, "created_at": datetime.now(timezone.utc).isoformat(), "topic": "",
              "error": None, "selection_issue": 96852, "points": [point]}
    important.save(result)
    body = important_marked_body(result, {point["id"]: "go2"}, cfg)
    data = important_good_data(point)
    data["post_body"] = f"{data['post_body']} وقال {WRONG} إن الأمر كذلك."
    with NamesAuditRig([names_audit_doubt()], {RIGHT: TWO_DOMAINS[:1]}) as rig:
        with ImportantWriteRig(lambda prompt, system: data):
            important_finalize.finalize(96852, body, cfg)
    saved = important.load_saved(96851)["points"][0]
    draft = store.load_draft(saved["draft_id"]) if saved.get("draft_id") else None
    check("«هام»: المسودة كُتبت ومرّت بالتدقيق (كشف واحد)", draft is not None and len(rig.detect_calls) == 1,
          (saved.get("status"), saved.get("write_error")))
    check("«هام»: اسم لم يُحسم ← تنبيه في warnings", draft is not None and any(
        w.startswith(f"اسم لم يُحسم: {WRONG}") for w in draft[1].get("warnings", [])),
          draft and draft[1].get("warnings"))
    important.saved_path(96851).unlink(missing_ok=True)
