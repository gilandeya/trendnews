"""حالات مرجعية (golden) للحُرّاس التحريرية — Issue #893.

القاعدة: فحص الأصالة وحده يحمل اليوم أربعة إعفاءات، كلٌّ منها أُضيف لمعالجة
تشغيلة حقيقية وقعت فعلًا (شواهد Issue #373 المتكررة في CLAUDE.md) — ولا موضع
واحد يجمع "هذا النص الحقيقي مرّ/رُفض ولماذا" في جدول واحد قابل للقراءة. بلا
هذا الملف، أي تعديل لاحق على حارس تحريري (فحص الأصالة، حارس الموضوع، حارس
الكلمات النافية، حارس صيغة العنوان...) يُقاس بالحدس لا بشاهد فعلي، ويخاطر
بكسر إعفاء أُضيف أصلًا لحالة حقيقية موثَّقة في Issue.

**أي مهمة مستقبلية تمسّ حارسًا تحريريًا (تعديل عتبة، إضافة/حذف إعفاء، إعادة
كتابة منطق) تضيف حالتها هنا أولًا — نصًّا حقيقيًا وحكمًا متوقَّعًا ورقم
الـIssue — قبل تعديل الحارس نفسه، لا بعده.** هذا الملف يثبّت السلوك القائم
فقط؛ لا يُصلح أي عطل يكشفه — عطل مكشوف هنا يُسجَّل في وصف الـPR ويُترك
لتشغيلة لاحقة مخصَّصة لإصلاحه.
"""
from __future__ import annotations

import shutil

from tests.helpers import (check, load_config, evidence, store, DRAFTS_DIR, ImportantRig,
                           ImportantWriteRig, NamesAuditRig, NAMES_AUDIT_SOURCE, names_audit_doubt,
                           names_audit_draft, names_audit_hit, important_doc, important_fixture_point,
                           important_good_data, important_marked_body, important_point,
                           important_stance, important_synthetic_point, brave_result)


def test_guards_golden() -> None:
    """جدول حالات مرجعية موثَّقة (نصّ حقيقي ← حكم متوقَّع ← Issue) لأربعة
    حُرّاس تحريرية مستقلة. لا تغيير سلوكي على أي حارس هنا — كل استدعاء أدناه
    على الدالة الحقيقية بلا تعديل."""
    from src import article, headlines, verify_draft

    # ── فحص الأصالة (verify_draft.check_originality): الإعفاء الرابع — واقعة
    # مسندة (Issue #865، شاهد تشغيلة مضيق هرمز — نفس نصوص
    # test_article.test_check_originality_grounded حرفيًا) ──
    run = "أعلن أمين المجلس الأعلى للأمن القومي الإيراني"
    draft = f"{run} تصريحات مهمة اليوم بشأن مضيق هرمز."
    single_source = [{"name": "وكالة إيرانية",
                      "text": f"وذكرت وكالة الأنباء أن {run} في تصريح رسمي اليوم.",
                      "link": "https://ir-agency/1"}]
    grounded_texts = [f"{run} محسن رضائي أن إيران ستقيم منطقة محظورة في مضيق هرمز."]

    ok1, reason1, _notes1, _off1 = verify_draft._check_originality_full(
        draft, "", single_source, 7, grounded_texts=grounded_texts)
    check("(#865) «أعلن أمين المجلس الأعلى للأمن القومي الإيراني» وارد بالكامل "
          "في واقعة مسندة ⇒ يمرّ", ok1 is True, (ok1, reason1))

    ok2, reason2, _notes2 = verify_draft.check_originality(draft, "", single_source, 7)
    check("(#865) نفس التتابع بلا تمرير أي وقائع مسندة ⇒ يُرفض",
          ok2 is False, (ok2, reason2))

    unrelated_grounded = ["نص واقعة مسندة أخرى لا صلة له بالتتابع المرفوض إطلاقًا."]
    ok3, reason3, _notes3, _off3 = verify_draft._check_originality_full(
        draft, "", single_source, 7, grounded_texts=unrelated_grounded)
    check("(#865) تتابع من وثيقة مصدر غير وارد في أي واقعة مسندة ⇒ يُرفض رغم "
          "تمرير وقائع مسندة أخرى", ok3 is False, (ok3, reason3))

    # ── حارس الموضوع لوقائع المصادر (article._source_fact_duplicate_index،
    # Issue #824 — نصوص الشاهد الفعلي المرفق في الـIssue حرفيًا) ──
    cfg_topic = load_config()
    cfg_topic["article"]["source_extract_enabled"] = True

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images
    real_extract_source_facts = article._extract_source_facts
    real_client_fn = article._client

    debt_total = {"text": "إجمالي دين فيستل بلغ 147.59 مليار ليرة", "entities": ["فيستل"]}
    tug_fact = {"text": "باعت فيستل حصتها في شركة توغ للدفاع", "entities": ["فيستل", "توغ"]}

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "ديون فيستل التركية وخسائرها",
        "statements": [
            {"text": "تجاوزت ديون فيستل 105 مليارات ليرة", "kind": "واقعة",
             "entities": ["فيستل"], "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1", "from_text": True},
         {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1", "from_text": True}],
        evidence.EVIDENCE_FULL_TEXT)
    article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
        is_report=False, publisher="": [d["name"] for d in docs]
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار الحارس؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "اقتصاد",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختباري بلا أي تشابه لفظي مع مصدر.",
         "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []
    article._extract_source_facts = lambda topic, brief_texts, docs, cfg: [debt_total, tug_fact]

    class _GuardBlock:
        def __init__(self, input_):
            self.type = "tool_use"
            self.input = input_

    class _GuardResp:
        def __init__(self, input_):
            self.content = [_GuardBlock(input_)]
            self.usage = None

    class _GuardMessages:
        def create(self, **kw):
            prompt = kw["messages"][0]["content"]
            # يحاكي حكم النموذج الفعلي المسجَّل في Issue #824: واقعة «توغ»
            # موضوع مختلف رغم مشاركة الكيان، وواقعة الدين نفس الموضوع.
            on_topic = tug_fact["text"] not in prompt
            reason = "" if on_topic else "نفس الكيان بموضوع مختلف"
            return _GuardResp({"duplicate_index": -1, "on_topic": on_topic,
                              "on_topic_reason": reason})

    class _GuardClient:
        def __init__(self):
            self.messages = _GuardMessages()

    article._client = lambda: _GuardClient()

    try:
        out = article._write_article("موجز اختبار حارس الموضوع (golden)", 9893, cfg_topic)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images
        article._extract_source_facts = real_extract_source_facts
        article._client = real_client_fn

    source_texts = [g["text"] for g in out.get("source_origin_facts", [])]
    off_topic_texts = {f["text"] for f in out.get("same_entity_off_topic_facts", [])}
    check("(#824) واقعة «بيع حصة فيستل في توغ» مع موجز عن الديون ⇒ تُحجب بحارس الموضوع",
          tug_fact["text"] not in source_texts and tug_fact["text"] in off_topic_texts,
          (source_texts, off_topic_texts))
    check("(#824) واقعة «إجمالي دين فيستل ١٤٧٫٥٩ مليار ليرة» مع نفس الموجز ⇒ تدخل "
          "(رغم انعدام التطابق اللفظي «ديون»/«الدين»)",
          debt_total["text"] in source_texts, source_texts)

    # ── حارس الكلمات النافية في منشور «تحقيق» (article.draft_investigation،
    # Issue #765) ──
    real_draft_text = article._draft_investigation_text
    real_unsourced = article._unsourced_entities
    real_find_images2 = article.find_images
    article._unsourced_entities = lambda *a, **k: []
    article.find_images = lambda topic, cfg, terms=None: []
    cfg = load_config()

    def _base_outcome(**overrides) -> dict:
        out = article._new_outcome()
        out.update({
            "produced": True, "reason": "صيغ مقال اختباري", "draft_id": "art_golden0001",
            "question": "هل وقع الحدث فعلًا؟",
            "sources": [{"name": "مصدر أول", "link": "https://s1/1"},
                       {"name": "مصدر ثانٍ", "link": "https://s2/1"}],
            "report_statements": [
                {"publisher": "منصة تقارير", "text": "نشرت منصة تقارير أن كذا وقع",
                 "sources": [{"name": "ناقل مستقل", "link": "https://c/1", "kind": "carrier"}]},
            ],
            "dropped": [
                {"text": "ادّعى الموجز أن شخصًا مجهولًا فعل كذا",
                 "reason": "سند غير كافٍ (0 من 2 مصادر مستقلة مطلوبة)"},
            ],
            "diffs": [
                {"brief": "الموجز قال إن الحدث وقع في المكان أ",
                 "sources_say": "المصادر المستقلة تقول إنه وقع في المكان ب"},
            ],
        })
        out.update(overrides)
        return out

    article_draft = {
        "id": "art_golden0001", "status": "pending", "origin": "article",
        "bucket": "serious",
        "image": "drafts/2026-01-01/art_golden0001.jpg",
        "arabic": {"post_title": "عنوان المقال", "category": "عالم"},
        "caption": "متن المقال", "source": {"publishers": ["مصدر أول"]},
    }

    try:
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        store.save_draft(article_draft)

        def _always_forbidden(report_statements, dropped, diffs, sources, question, cfg,
                              retries=3, avoid_note=""):
            return ({"angle": "تحقيق", "analysis": "", "urgent": False, "category": "عالم",
                    "image_headline": "عنوان", "post_title": "عنوان تحقيق",
                    "post_body": "هذا الادّعاء كاذب.", "hashtags": []}, "")

        article._draft_investigation_text = _always_forbidden
        result_forbidden = article.draft_investigation(_base_outcome(), cfg)
        check("(#765) منشور تحقيق يحوي «كاذب»/«مفبرك»/«شائعة» ⇒ يُرفض ثم يُعاد "
              "المحاولة مرة واحدة ثم يمتنع نهائيًا (بلا مسودة)",
              result_forbidden is None, result_forbidden)

        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        store.save_draft(article_draft)

        calls_ok: list = []

        def _abstains_properly(report_statements, dropped, diffs, sources, question, cfg,
                               retries=3, avoid_note=""):
            calls_ok.append(avoid_note)
            return ({"angle": "تحقيق", "analysis": "", "urgent": False, "category": "عالم",
                    "image_headline": "عنوان تحقيق", "post_title": "عنوان تحقيق",
                    "post_body": "لم نجد مصدرًا مستقلًا يؤكد هذا الادّعاء.",
                    "hashtags": ["تحقيق"]}, "")

        article._draft_investigation_text = _abstains_properly
        result_ok = article.draft_investigation(_base_outcome(), cfg)
        check("(#765) منشور تحقيق يقول «لم نجد مصدرًا مستقلًا» ⇒ يمرّ من أول محاولة",
              result_ok is not None and len(calls_ok) == 1, (result_ok, calls_ok))
    finally:
        article._draft_investigation_text = real_draft_text
        article._unsourced_entities = real_unsourced
        article.find_images = real_find_images2

    # ── حارس صيغة العنوان الأول (headlines.validate_headlines، Issue #756) ──
    bad_headlines = ["هذا عنوان تقريري بلا علامة استفهام", "عنوان بديل ثانٍ", "عنوان بديل ثالث"]
    ok8, reason8 = headlines.validate_headlines(bad_headlines, max_words=15)
    check("(#756) عنوان أول لا ينتهي بعلامة استفهام ⇒ يُرفض", ok8 is False, reason8)

    # ── حارس بنية مقال التحليل (youtube_article._validate_article_text) --
    # القاعدة معكوسة (Issue #941): وجود قسم ## المصادر صار سبب رفض لا شرط
    # قبول (كان إلزاميًا في النسخة الثالثة/الرابعة، Issue #690/#695) -- المتن
    # لا يجوز أن يسمّي مصادره/قنواته إطلاقًا بعد اليوم ──
    from src import youtube_article as ya_golden
    golden_filler = " ".join(["كلمة"] * 260)
    golden_likelihood = "وهذا مرجّح بقوة، ولا يسندها إلا مصدر واحد."
    golden_body = f"# سؤال تجريبي عن قضية ما؟\n\n{golden_filler}\n\n{golden_likelihood}\n"

    ok_no_sources, reason_no_sources = ya_golden._validate_article_text(golden_body, cfg)
    check("(#941) مقال بلا أي قسم ## (بما فيها المصادر) ⇒ يمرّ (القاعدة معكوسة)",
          ok_no_sources, reason_no_sources)

    golden_with_sources = golden_body + "\n---\n## المصادر\nقناة تجريبية — عنوان — رابط\n"
    ok_with_sources, reason_with_sources = ya_golden._validate_article_text(
        golden_with_sources, cfg)
    check("(#941) مقال فيه ## المصادر ⇒ يُرفض الآن (عكس القاعدة القديمة)",
          ok_with_sources is False and "##" in reason_with_sources, reason_with_sources)

    # ── حارس سند التصريح (article._support_statement_parts عبر _write_article
    # الحقيقية، Issue #1050): يفصل فشل نداء تقني (قطع الرد) عن حكم حقيقي بلا
    # مؤيِّد — لا حارس نموذج بذاته، لكن سلوك المستدعي (article.py:3397 وما
    # حولها) يعتمد كليًا على أن _support_statement_parts تضبط call_error في
    # كل مسار فشل تقني؛ الحالة الأولى أدناه كانت تفشل *قبل* إصلاح Issue
    # #1050 (القطع لم يكن يضبط call_error) وتنجح بعده. article._client وحدها
    # مُموَّهة هنا — _support_statement_parts الحقيقية تُنفَّذ بلا تعديل ──
    real_client_golden = article._client
    real_extract_brief3 = article.extract_brief
    real_search3 = evidence.search
    real_gather_evidence3 = evidence.gather_evidence
    real_support_sources3 = article._support_sources
    real_choose_question3 = article._choose_question
    real_draft_article3 = article._draft_article
    real_find_images3 = article.find_images

    golden_statement_text = "متحدث الاختبار يعلن أمرين دفعة واحدة"
    golden_p1, golden_p2 = "أعلن الأمر الأول", "أعلن الأمر الثاني"
    # واقعة عادية مجاورة مسنَدة دومًا (عبر article._support_sources المموَّهة
    # لا article._client) — بلا هذه، سقوط التصريح الوحيد في الموجز يُفعِّل
    # شبكة أمان درجة ج (Issue #814: "لا واقعة أ/ب في التشغيلة كلها ⇒ يُصاغ
    # المقال من وقائع الموجز نفسها") فتُزال من outcome['dropped'] فورًا
    # (article.py:3989-3990) قبل أن يبلغها هذا الاختبار، فيختبر شبكة الأمان
    # لا حارس السند المقصود هنا
    golden_plain_fact = "واقعة عادية مسنَدة في نفس الموجز"

    def _install_statement_brief():
        # speaker/entities فارغان عمدًا (لا تخفيفًا عابرًا): query_text في
        # article._search_fact_support يُبنى من mandatory_name+entities_text+
        # f["text"] معًا — بقاؤهما فارغين يجعل query_text مطابقًا لـf["text"]
        # حرفيًا فيبقى سُلَّم البحث بمحاولة واحدة (search_texts بعنصر واحد لا
        # اثنين)، فعدد نداءات _support_statement_parts يبقى متوقَّعًا بدقة
        # لكل سيناريو أدناه بلا تشعب في عدد المحاولات
        article.extract_brief = lambda body, cfg, retries=3: ({
            "topic": "اختبار حارس سند التصريح",
            "statements": [
                {"text": golden_statement_text, "kind": "تصريح",
                 "entities": [], "is_unnamed_event": False,
                 "is_reference": False, "speaker": "",
                 "merged_excerpts": [golden_p1, golden_p2]},
                {"text": golden_plain_fact, "kind": "واقعة", "entities": [],
                 "is_unnamed_event": False, "is_reference": False},
            ],
            "questions": [],
        }, None)
        evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
        evidence.gather_evidence = lambda articles, cfg, claim_text="": (
            [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1", "from_text": True},
             {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1", "from_text": True}],
            evidence.EVIDENCE_FULL_TEXT)
        article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
            is_report=False, publisher="": (["مصدر أول", "مصدر ثانٍ"]
                                             if fact_text == golden_plain_fact else [])
        article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختباري؟", "")
        article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
            {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
             "image_headline": "عنوان", "post_title": question,
             "post_body": "متن اختباري.", "hashtags": ["اختبار"]}, "")
        article.find_images = lambda title, cfg, terms=None: []

    class _GoldenBlock:
        def __init__(self, input_):
            self.type = "tool_use"
            self.input = input_

    class _GoldenResp:
        def __init__(self, content, stop_reason="end_turn"):
            self.content = content
            self.stop_reason = stop_reason
            self.usage = None

    class _GoldenMessages:
        def __init__(self, responses):
            self._responses = list(responses)
            self.calls = []

        def create(self, **kw):
            self.calls.append(kw)
            return self._responses.pop(0)

    class _GoldenClient:
        def __init__(self, responses):
            self.messages = _GoldenMessages(responses)

    cfg_golden = load_config()
    # مرحلة استخراج وقائع من المصادر (source_extract_enabled) تستدعي النموذج
    # أيضًا عبر نفس article._client المموَّه هنا — تُعطَّل صراحة (نظير
    # test_article_split_statements) فلا تستهلك ردود _GoldenClient المُعدَّة
    # حصرًا لسند التصريح
    cfg_golden["article"]["source_extract_enabled"] = False

    # حالة 1 — فشل تقني (قطع الرد مرتين، لا يبقى إلا الاستسلام النهائي):
    # call_error يُضبط ⇒ لا تُحسب أجزاء التصريح غير مسنودة (سبب السقوط
    # يذكر «فشل نداء» صراحة لا «سند غير كافٍ»)، ولا يُكتب part_support (يبقى
    # [] كقيمته الابتدائية، لا قائمة بأجزاء "غير مؤيَّدة" توهم بحكم حقيقي).
    _install_statement_brief()
    truncated_client = _GoldenClient([
        _GoldenResp([], stop_reason="max_tokens"),
        _GoldenResp([], stop_reason="max_tokens"),
    ])
    article._client = lambda: truncated_client
    out_truncated = article._write_article("موجز اختبار حارس السند (تقني)", 10501, cfg_golden)
    article._client = real_client_golden

    check("(#1050) فشل نداء تقني (قطع مرتين) ⇒ سبب السقوط «فشل نداء» لا «سند "
          "غير كافٍ» — لا يُقرأ كحكم حقيقي",
          any(d["text"] == golden_statement_text
              and d["reason"].startswith("⚠️ فشل نداء الحكم على السند تقنيًا")
              for d in out_truncated["dropped"]),
          out_truncated["dropped"])
    check("(#1050) فشل نداء تقني ⇒ part_support يبقى [] (لا يُكتب بلاغ سند "
          "زائف لأجزاء لم تُفحص فعليًا)",
          all(m["part_support"] == [] for m in out_truncated["merged_statements"]
              if m["text"] == golden_statement_text),
          out_truncated["merged_statements"])

    # (#1058) نظير التمييز أعلاه لكن في التقرير النصّي نفسه (build_report) لا
    # في outcome وحده: part_support == [] كان يعني اختفاء كل أسطر «•» لهذا
    # التصريح من التقرير بصمت تام، بلا أي أثر يفرّق فشل النداء التقني عن حكم
    # حقيقي بلا مؤيِّد لأي جزء (نظير سطر ⚠️ الظاهر بالفعل لـsource_facts_summary
    # في نفس التقرير عند call_error، article.py:5188 وما بعدها)
    check("(#1058) فشل نداء تقني ⇒ part_support_error مضبوط في outcome",
          any(m.get("part_support_error") for m in out_truncated["merged_statements"]
              if m["text"] == golden_statement_text),
          out_truncated["merged_statements"])
    report_truncated = article.build_report(out_truncated)
    check("(#1058) فشل نداء تقني ⇒ التقرير يحمل سطر تحذير صريح بدل الاختفاء الصامت",
          "تعذّر الحكم على أجزاء هذا التصريح" in report_truncated, report_truncated)
    check("(#1058) فشل نداء تقني ⇒ لا سطر «•» واحد لهذا التصريح (part_support فارغة "
          "فعلًا، لا بلاغ مخترع لأجزاء لم تُفحص)",
          f"«{golden_p1}»" not in report_truncated and f"«{golden_p2}»" not in report_truncated,
          report_truncated)

    # حالة 2 — حكم حقيقي بلا مؤيِّد (رد سليم، stop_reason=end_turn، قائمة
    # فارغة فعليًا لكل جزء): يبقى كما هو اليوم تمامًا — نداء واحد، سبب
    # السقوط «سند غير كافٍ»، وpart_support مكتوب فعليًا بقوائم فارغة (لا [])
    _install_statement_brief()
    real_judgment_client = _GoldenClient([
        _GoldenResp([_GoldenBlock({"parts": [
            {"index": 1, "supporting": []}, {"index": 2, "supporting": []}]})]),
    ])
    article._client = lambda: real_judgment_client
    out_real = article._write_article("موجز اختبار حارس السند (حكم حقيقي)", 10502, cfg_golden)
    article._client = real_client_golden

    check("(#1050) حكم حقيقي بلا مؤيِّد ⇒ نداء واحد فقط (بلا إعادة محاولة، "
          "لا قطع وقع)", len(real_judgment_client.messages.calls) == 1,
          len(real_judgment_client.messages.calls))
    check("(#1050) حكم حقيقي بلا مؤيِّد ⇒ سبب السقوط «سند غير كافٍ» لا «فشل نداء»",
          any(d["text"] == golden_statement_text
              and d["reason"].startswith("سند غير كافٍ")
              for d in out_real["dropped"]),
          out_real["dropped"])
    check("(#1050) حكم حقيقي بلا مؤيِّد ⇒ part_support مكتوب فعليًا (جزءان "
          "بقائمة مؤيِّدين فارغة لكل منهما) — يتمايز عن [] حالة الفشل التقني",
          any(m["part_support"] == [{"excerpt": golden_p1, "supporting": []},
                                    {"excerpt": golden_p2, "supporting": []}]
              for m in out_real["merged_statements"]),
          out_real["merged_statements"])

    # (#1058) نظير حالة الفشل أعلاه: حكم حقيقي بلا مؤيِّد لا يضبط
    # part_support_error، والتقرير يعرض «✗ لا مصدر» لكل جزء كسابق عهده تمامًا
    # — بلا سطر التحذير الجديد (السطران لا يظهران معًا)
    check("(#1058) حكم حقيقي بلا مؤيِّد ⇒ part_support_error يبقى None",
          all(m.get("part_support_error") is None for m in out_real["merged_statements"]
              if m["text"] == golden_statement_text),
          out_real["merged_statements"])
    report_real = article.build_report(out_real)
    check("(#1058) حكم حقيقي بلا مؤيِّد ⇒ لا سطر تحذير «تعذّر الحكم»",
          "تعذّر الحكم على أجزاء هذا التصريح" not in report_real, report_real)
    check("(#1058) حكم حقيقي بلا مؤيِّد ⇒ التقرير يعرض «✗ لا مصدر» لكلا الجزأين "
          "كما اليوم حرفيًا",
          f"«{golden_p1}» — ✗ لا مصدر" in report_real and
          f"«{golden_p2}» — ✗ لا مصدر" in report_real,
          report_real)

    article.extract_brief = real_extract_brief3
    evidence.search = real_search3
    evidence.gather_evidence = real_gather_evidence3
    article._support_sources = real_support_sources3
    article._choose_question = real_choose_question3
    article._draft_article = real_draft_article3
    article.find_images = real_find_images3

    # ── حارس سند الواقعة (article._support_sources عبر _write_article
    # الحقيقية، Issue #1052 — النظير المباشر لحارس سند التصريح أعلاه): نفس
    # عطل Issue #1050 (سقف 400 ثابت، وقطع الرد لا يضبط call_error) كان قائمًا
    # هنا أيضًا. article._support_sources وحدها حقيقية هنا؛
    # article._support_statement_parts مموَّهة كي تُسنِد واقعة مرافقة (تصريح)
    # دومًا — بلا هذه، سقوط واقعتنا الوحيدة قيد الاختبار يُفعِّل شبكة أمان
    # درجة ج (Issue #814) فتُزال من outcome['dropped'] فورًا (article.py
    # ~4033-4045) قبل أن يبلغها هذا الاختبار، فيختبر شبكة الأمان لا حارس
    # السند المقصود هنا — نفس السبب الموثَّق أعلاه لـgolden_plain_fact، بالضبط
    # مقلوبًا (هناك التصريح قيد الاختبار والواقعة مرافقة، هنا العكس) ──
    real_client_golden2 = article._client
    real_extract_brief4 = article.extract_brief
    real_search4 = evidence.search
    real_gather_evidence4 = evidence.gather_evidence
    real_support_statement_parts4 = article._support_statement_parts
    real_choose_question4 = article._choose_question
    real_draft_article4 = article._draft_article
    real_find_images4 = article.find_images

    golden_source_fact_text = "واقعة اختبار حارس سند الواقعة وقعت أمس"
    golden_companion_statement = "متحدث مرافق يعلن أمرًا واحدًا"

    def _install_source_fact_brief():
        article.extract_brief = lambda body, cfg, retries=3: ({
            "topic": "اختبار حارس سند الواقعة",
            "statements": [
                {"text": golden_source_fact_text, "kind": "واقعة", "entities": [],
                 "is_unnamed_event": False, "is_reference": False},
                {"text": golden_companion_statement, "kind": "تصريح",
                 "entities": [], "is_unnamed_event": False,
                 "is_reference": False, "speaker": "",
                 "merged_excerpts": [golden_companion_statement]},
            ],
            "questions": [],
        }, None)
        evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
        evidence.gather_evidence = lambda articles, cfg, claim_text="": (
            [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1", "from_text": True},
             {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1", "from_text": True}],
            evidence.EVIDENCE_FULL_TEXT)
        # الواقعة المرافقة (تصريح) مسنَدة دومًا عبر _support_statement_parts
        # المموَّهة — لا تستهلك ردود _GoldenClient2 المُعدَّة حصرًا لـ
        # _support_sources الحقيقية (واقعتنا قيد الاختبار فقط تستدعي العميل)
        article._support_statement_parts = lambda parts, docs, cfg: (
            article._PartSupportList([["مصدر أول", "مصدر ثانٍ"]]))
        article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختباري؟", "")
        article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
            {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
             "image_headline": "عنوان", "post_title": question,
             "post_body": "متن اختباري.", "hashtags": ["اختبار"]}, "")
        article.find_images = lambda title, cfg, terms=None: []

    class _GoldenBlock2:
        def __init__(self, input_):
            self.type = "tool_use"
            self.input = input_

    class _GoldenResp2:
        def __init__(self, content, stop_reason="end_turn"):
            self.content = content
            self.stop_reason = stop_reason
            self.usage = None

    class _GoldenMessages2:
        def __init__(self, responses):
            self._responses = list(responses)
            self.calls = []

        def create(self, **kw):
            self.calls.append(kw)
            return self._responses.pop(0)

    class _GoldenClient2:
        def __init__(self, responses):
            self.messages = _GoldenMessages2(responses)

    cfg_golden2 = load_config()
    cfg_golden2["article"]["source_extract_enabled"] = False

    # حالة 1 — فشل تقني (قطع الرد مرتين): call_error يُضبط ⇒ الواقعة تسقط
    # بسبب «فشل نداء» لا «سند غير كافٍ»، وتبقى في outcome['dropped'] (لا
    # تُبتلَع في شبكة أمان درجة ج بفضل الواقعة المرافقة المسنَدة دومًا أعلاه)
    _install_source_fact_brief()
    truncated_client2 = _GoldenClient2([
        _GoldenResp2([], stop_reason="max_tokens"),
        _GoldenResp2([], stop_reason="max_tokens"),
    ])
    article._client = lambda: truncated_client2
    out_truncated2 = article._write_article(
        "موجز اختبار حارس سند الواقعة (تقني)", 10503, cfg_golden2)
    article._client = real_client_golden2

    check("(#1052) فشل نداء تقني (قطع مرتين) في _support_sources ⇒ سبب سقوط "
          "الواقعة «فشل نداء» لا «سند غير كافٍ»",
          any(d["text"] == golden_source_fact_text
              and d["reason"].startswith("⚠️ فشل نداء الحكم على السند تقنيًا")
              for d in out_truncated2["dropped"]),
          out_truncated2["dropped"])
    check("(#1052) فشل نداء تقني ⇒ نداءان فقط (نداء أول + إعادة محاولة واحدة، "
          "لا صمتًا بقائمة فارغة)",
          len(truncated_client2.messages.calls) == 2,
          len(truncated_client2.messages.calls))

    # حالة 2 — حكم حقيقي بقائمة supporting فارغة: يبقى كما هو اليوم حرفيًا —
    # نداء واحد، سبب السقوط «سند غير كافٍ»، بلا call_error
    _install_source_fact_brief()
    real_judgment_client2 = _GoldenClient2([
        _GoldenResp2([_GoldenBlock2({"supporting": [], "mentioned": []})]),
    ])
    article._client = lambda: real_judgment_client2
    out_real2 = article._write_article(
        "موجز اختبار حارس سند الواقعة (حكم حقيقي)", 10504, cfg_golden2)
    article._client = real_client_golden2

    check("(#1052) حكم حقيقي بقائمة supporting فارغة ⇒ نداء واحد فقط (بلا "
          "إعادة محاولة، لا قطع وقع)",
          len(real_judgment_client2.messages.calls) == 1,
          len(real_judgment_client2.messages.calls))
    check("(#1052) حكم حقيقي بقائمة supporting فارغة ⇒ سبب السقوط «سند غير "
          "كافٍ» لا «فشل نداء» — يبقى كما هو اليوم",
          any(d["text"] == golden_source_fact_text
              and d["reason"].startswith("سند غير كافٍ")
              for d in out_real2["dropped"]),
          out_real2["dropped"])

    article.extract_brief = real_extract_brief4
    evidence.search = real_search4
    evidence.gather_evidence = real_gather_evidence4
    article._support_statement_parts = real_support_statement_parts4
    article._choose_question = real_choose_question4
    article._draft_article = real_draft_article4
    article.find_images = real_find_images4

    # ── حارس تسمية الحدث المبهم (article._ask_naming_model عبر _write_article
    # الحقيقية، Issue #1061 — نظير حارسَي سند التصريح/الواقعة أعلاه بالضبط):
    # نفس عطل Issue #1050/#1052 كان قائمًا هنا أيضًا — call_error يُضبط عند
    # APIError فقط، فالقطع (stop_reason=max_tokens) أو غياب كتلة tool_use
    # صالحة كانا يُقرآن بصمت كحكم "لم يُسمَّ من هذه النتائج" حقيقي.
    # article._ask_naming_model الحقيقية تُنفَّذ بلا تعديل — article._client
    # وحدها مموَّهة، بردٍّ مقطوع دومًا بصرف النظر عن عدد النداءات (تسمية+سياق
    # مرحلة «مرجعي») كي لا يعتمد الاختبار على عدّ دقيق للنداءات عبر سلّم
    # الاتساع كله ──
    real_client_golden5 = article._client
    real_extract_brief5 = article.extract_brief
    real_search5 = evidence.search
    real_gather_evidence5 = evidence.gather_evidence

    golden_unnamed_text = "أشار موجزي إلى تطورات غامضة وقعت مؤخرًا"

    def _install_unnamed_event_brief():
        # topic="" (لا موجز عام) يُسقط مرحلة «موضوع» الثالثة في _name_event —
        # تبقى مرحلة «مباشر» وحدها ذات صلة لهذا الاختبار (مرحلة «سياق» تتوقف
        # من تلقاء نفسها بلا مصطلحات سياق مستخلَصة حين يُخفق _ask_context_model
        # على نفس العميل المقطوع دومًا أدناه)
        article.extract_brief = lambda body, cfg, retries=3: ({
            "topic": "",
            "statements": [
                {"text": golden_unnamed_text, "kind": "واقعة",
                 "entities": ["كيان تجريبي", "10 أيلول"],
                 "is_unnamed_event": True, "is_reference": False},
            ],
            "questions": [],
        }, None)
        evidence.search = lambda query, cfg, days, **kwargs: [object()]
        evidence.gather_evidence = lambda ranked, cfg, query, **kwargs: (
            [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"},
             {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1"}],
            evidence.EVIDENCE_FULL_TEXT)

    class _GoldenResp5:
        def __init__(self, content, stop_reason="end_turn"):
            self.content = content
            self.stop_reason = stop_reason
            self.usage = None

    class _AlwaysCutMessages5:
        def __init__(self):
            self.calls = []

        def create(self, **kw):
            self.calls.append(kw)
            return _GoldenResp5([], stop_reason="max_tokens")

    class _AlwaysCutClient5:
        def __init__(self):
            self.messages = _AlwaysCutMessages5()

    cfg_golden5 = load_config()
    cfg_golden5["article"]["source_extract_enabled"] = False

    _install_unnamed_event_brief()
    client_golden5 = _AlwaysCutClient5()
    article._client = lambda: client_golden5
    out_naming = article._write_article("موجز اختبار حارس التسمية (تقني)", 10505, cfg_golden5)
    article._client = real_client_golden5

    naming_trail = [t for t in out_naming["trail"] if t["stage"] == "مباشر"]
    check("(#1061) حارس التسمية: فشل نداء تقني مستمر ⇒ trail «مباشر» يكتب "
          "«⚠️ فشل نداء النموذج تقنيًا» لا «لم يُسمَّ من هذه النتائج»",
          bool(naming_trail)
          and "⚠️ فشل نداء النموذج تقنيًا" in naming_trail[0]["outcome"]
          and "لم يُسمَّ من هذه النتائج" not in naming_trail[0]["outcome"],
          naming_trail if naming_trail else out_naming["trail"])
    report_naming = article.build_report(out_naming)
    check("(#1061) حارس التسمية: التقرير الظاهر (build_report) يحمل عبارة فشل "
          "النداء التقنية صراحة لا حكمًا على المصادر",
          "⚠️ فشل نداء النموذج تقنيًا" in report_naming
          and "لم يُسمَّ من هذه النتائج" not in report_naming,
          report_naming)

    article.extract_brief = real_extract_brief5
    evidence.search = real_search5
    evidence.gather_evidence = real_gather_evidence5

    # ── حارس الإجابة عن سؤال الموجز (article._ask_answer_model عبر
    # _write_article الحقيقية، Issue #1061 — النظير الثاني هنا بالضبط، لسؤال
    # الموجز بدل واقعة مبهمة): article._ask_answer_model الحقيقية تُنفَّذ بلا
    # تعديل — article._client وحدها مموَّهة، بردٍّ مقطوع دومًا. الموجز يحمل
    # رأيًا لا واقعة (kind: "رأي") كي لا تدخل _ground_brief_facts أي نداء
    # نموذج مستقل يُشوِّش عدّ نداءات الإجابة ──
    real_client_golden6 = article._client
    real_extract_brief6 = article.extract_brief
    real_search6 = evidence.search
    real_gather_evidence6 = evidence.gather_evidence
    real_build_query_for_claim6 = evidence.build_query_for_claim
    real_entities_text6 = evidence._entities_text
    real_readable_only6 = evidence.readable_only

    golden_question_text = "هل وقع الحدث المذكور في الموجز فعلًا؟"

    def _install_question_brief():
        article.extract_brief = lambda body, cfg, retries=3: ({
            "topic": "",
            "statements": [
                {"text": "رأي تجريبي لا يحتاج سندًا", "kind": "رأي",
                 "entities": [], "is_unnamed_event": False, "is_reference": False},
            ],
            "questions": [
                {"text": golden_question_text, "entities": [], "is_reference": False},
            ],
        }, None)
        evidence.build_query_for_claim = lambda q, max_words: "استعلام اختبار الإجابة"
        evidence.search = lambda query, cfg, days, **kwargs: [object()]
        evidence._entities_text = lambda q: ""
        evidence.gather_evidence = lambda ranked, cfg, query, **kwargs: (
            [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"}],
            evidence.EVIDENCE_FULL_TEXT)
        evidence.readable_only = lambda docs: docs

    class _GoldenResp6:
        def __init__(self, content, stop_reason="end_turn"):
            self.content = content
            self.stop_reason = stop_reason
            self.usage = None

    class _AlwaysCutMessages6:
        def __init__(self):
            self.calls = []

        def create(self, **kw):
            self.calls.append(kw)
            return _GoldenResp6([], stop_reason="max_tokens")

    class _AlwaysCutClient6:
        def __init__(self):
            self.messages = _AlwaysCutMessages6()

    cfg_golden6 = load_config()
    cfg_golden6["article"]["source_extract_enabled"] = False

    _install_question_brief()
    client_golden6 = _AlwaysCutClient6()
    article._client = lambda: client_golden6
    out_answer = article._write_article("موجز اختبار حارس الإجابة (تقني)", 10506, cfg_golden6)
    article._client = real_client_golden6

    answer_trail = [t for t in out_answer["trail"] if t["stage"] == "سؤال"]
    check("(#1061) حارس الإجابة: فشل نداء تقني مستمر ⇒ trail «سؤال» يكتب «⚠️ "
          "فشل نداء النموذج تقنيًا» لا «لم تُجب عنه النصوص المقروءة»",
          bool(answer_trail)
          and "⚠️ فشل نداء النموذج تقنيًا" in answer_trail[0]["outcome"]
          and "لم تُجب عنه النصوص المقروءة" not in answer_trail[0]["outcome"],
          answer_trail if answer_trail else out_answer["trail"])
    check("(#1061) حارس الإجابة: unanswered يكتب فشل نداء صريح — لا «بُحث ولم "
          "توجد نصوص تجيب عنه بوضوح» ولا عطل تسمية مصدر",
          bool(out_answer["unanswered"])
          and "⚠️ فشل نداء الإجابة تقنيًا" in out_answer["unanswered"][0]["reason"],
          out_answer["unanswered"])
    report_answer = article.build_report(out_answer)
    check("(#1061) حارس الإجابة: التقرير الظاهر (build_report) يحمل عبارة فشل "
          "النداء التقنية صراحة لا حكمًا على المصادر",
          "⚠️ فشل نداء النموذج تقنيًا" in report_answer
          and "لم تُجب عنه النصوص المقروءة" not in report_answer,
          report_answer)

    article.extract_brief = real_extract_brief6
    evidence.search = real_search6
    evidence.gather_evidence = real_gather_evidence6
    evidence.build_query_for_claim = real_build_query_for_claim6
    evidence._entities_text = real_entities_text6
    evidence.readable_only = real_readable_only6

    # ── حارس سياق الكيان المبهم (article._ask_context_model عبر _write_article
    # الحقيقية، Issue #1063 — نظير حارسَي التسمية/الإجابة أعلاه بالضبط، لكن
    # لمرحلة «مرجعي» الاحتياطية في _name_event لا مرحلة «مباشر»): نفس عطل
    # Issue #1061 كان قائمًا هنا أيضًا — سقف 200 ثابت والقطع كان يُقرأ بصمت
    # كـ"لا سياق مستخلَص" حقيقي. مرحلة «مباشر» تُفشَل عمدًا بلا وثائق (بحث
    # مزيَّف يعيد نتائج فقط حين unrestricted=True، أي لمرحلة «مرجعي» وحدها)
    # كي يصل التنفيذ إلى _ask_context_model على العميل المقطوع دومًا أدناه
    # بلا تعقيد إضافي في عدّ النداءات ──
    real_client_golden7 = article._client
    real_extract_brief7 = article.extract_brief
    real_search7 = evidence.search
    real_gather_evidence7 = evidence.gather_evidence

    golden_context_text = "أشار موجزي إلى تطورات غامضة وقعت مؤخرًا في الإقليم"

    def _install_context_failure_brief():
        article.extract_brief = lambda body, cfg, retries=3: ({
            "topic": "",
            "statements": [
                {"text": golden_context_text, "kind": "واقعة",
                 "entities": ["كيان تجريبي", "10 أيلول"],
                 "is_unnamed_event": True, "is_reference": False},
            ],
            "questions": [],
        }, None)

        def search_stub(query, cfg, days, **kwargs):
            # unrestricted=True حصرًا لمرحلة «مرجعي» — مرحلة «مباشر» (بلا هذا
            # المفتاح) تعود بلا نتائج فتُفشَل بـ"لا وثائق للتسمية" العادية،
            # لا بفشل نداء نموذج، فيبقى العدّ دقيقًا لحارس السياق وحده.
            return [object()] if kwargs.get("unrestricted") else []

        def gather_stub(ranked, cfg, query, **kwargs):
            if not ranked:
                return [], evidence.EVIDENCE_NO_RESULTS
            return ([{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"}],
                    evidence.EVIDENCE_FULL_TEXT)

        evidence.search = search_stub
        evidence.gather_evidence = gather_stub

    class _GoldenResp7:
        def __init__(self, content, stop_reason="end_turn"):
            self.content = content
            self.stop_reason = stop_reason
            self.usage = None

    class _AlwaysCutMessages7:
        def __init__(self):
            self.calls = []

        def create(self, **kw):
            self.calls.append(kw)
            return _GoldenResp7([], stop_reason="max_tokens")

    class _AlwaysCutClient7:
        def __init__(self):
            self.messages = _AlwaysCutMessages7()

    cfg_golden7 = load_config()
    cfg_golden7["article"]["source_extract_enabled"] = False

    _install_context_failure_brief()
    client_golden7 = _AlwaysCutClient7()
    article._client = lambda: client_golden7
    out_context = article._write_article("موجز اختبار حارس السياق (تقني)", 10507, cfg_golden7)
    article._client = real_client_golden7

    context_trail = [t for t in out_context["trail"] if t["stage"] == "مرجعي"]
    check("(#1063) حارس سياق الكيان: فشل نداء تقني مستمر ⇒ trail «مرجعي» يكتب "
          "«⚠️ فشل نداء النموذج تقنيًا» لا «لا سياق مستخلَص»",
          bool(context_trail)
          and "⚠️ فشل نداء النموذج تقنيًا" in context_trail[0]["outcome"]
          and "لا سياق مستخلَص" not in context_trail[0]["outcome"],
          context_trail if context_trail else out_context["trail"])
    report_context = article.build_report(out_context)
    check("(#1063) حارس سياق الكيان: التقرير الظاهر (build_report) يحمل عبارة فشل "
          "النداء التقنية صراحة لا حكمًا على السياق",
          "⚠️ فشل نداء النموذج تقنيًا" in report_context
          and "لا سياق مستخلَص" not in report_context,
          report_context)

    article.extract_brief = real_extract_brief7
    evidence.search = real_search7
    evidence.gather_evidence = real_gather_evidence7

    # ── بطاقة مقال التحليل: وجه ممنوع صورةً رئيسية (Issue #680) -- على
    # البطاقة المبنيّة فعليًا (Pillow، بلا شبكة) لا على دالة منفردة. حالة
    # خلفية الفيديو المعتّمة التي كانت تُستثنى من فحص الوجه (Issue #1092)
    # حُذفت من هنا بعد إلغاء ذلك المسار كليًا (Issue #1095) -- انظر
    # tests/test_youtube.py:test_youtube_image_news_photo للدرجة الثانية
    # الجديدة (صورة خبر عن الموضوع). ──
    from src import imaging as imaging_golden
    from src import youtube_extract as yext_golden
    from PIL import Image as _GoldenImage

    cfg_card_golden = load_config()
    face_url = "https://example.com/golden-face.jpg"
    real_imagesearch_find = None
    real_download_golden = imaging_golden.download_image
    real_face_score_golden = imaging_golden.face_score

    face_image = _GoldenImage.new("RGB", (800, 600), (255, 0, 0))  # أحمر صريح مميَّز

    # الحالة الأولى (#680 القائمة): مرشَّح فيه وجه (face_score مرتفع) يصل
    # youtube_extract.photo_candidates -- يُستبعَد فيُعاد قائمة فارغة، فلا
    # يمكن أن يصل fallback_urls في build_post_image أصلًا (لا سبيل بنيوي
    # لتسريبه صورةً رئيسية). imaging_golden.download_image/face_score
    # مموَّهتان محليًا هنا فقط (لا imagesearch.find_images -- تُمرَّر الروابط
    # الخام مباشرة عبر معامل ``urls`` وهميّ محاكاةً لمخرجها).
    try:
        from src import imagesearch as imagesearch_golden
        real_imagesearch_find = imagesearch_golden.find_images
        imagesearch_golden.find_images = lambda *a, **k: [face_url]  # type: ignore
        imaging_golden.download_image = lambda *a, **k: face_image  # type: ignore
        imaging_golden.face_score = lambda img: 0.5  # type: ignore
        clean = yext_golden.photo_candidates("عنوان تجريبي", "حدث تجريبي", cfg_card_golden)
    finally:
        if real_imagesearch_find is not None:
            imagesearch_golden.find_images = real_imagesearch_find  # type: ignore
        imaging_golden.download_image = real_download_golden  # type: ignore
        imaging_golden.face_score = real_face_score_golden  # type: ignore
    check("(#680/#1092) مرشَّح فيه وجه ظاهر يُستبعَد من photo_candidates -- "
          "لا سبيل بنيوي لوصوله fallback_urls فيصير صورةً رئيسية في بطاقة تحليل",
          clean == [], clean)

    card_path_1 = DRAFTS_DIR / "golden_1092_main_face_rejected.jpg"
    card_path_1.parent.mkdir(parents=True, exist_ok=True)
    report_1: dict = {}
    try:
        imaging_golden.download_image = lambda *a, **k: face_image  # type: ignore
        imaging_golden.face_score = lambda img: 0.9  # type: ignore
        # fallback_urls=[] (النتيجة الفعلية من photo_candidates أعلاه) --
        # الصورة الرئيسية تبني الخلفية المصممة العادية، لا صورة الوجه، حتى
        # لو نجح تحميلها لو وصلت (لم تصل أصلًا).
        imaging_golden.build_post_image(
            headline="بطاقة تحليل تجريبية", category="", urgent=False,
            image_urls=None, fallback_urls=[], publisher=[], cfg=cfg_card_golden,
            out_path=card_path_1, bucket="", report=report_1, origin="analysis")
    finally:
        imaging_golden.download_image = real_download_golden  # type: ignore
        imaging_golden.face_score = real_face_score_golden  # type: ignore
        card_path_1.unlink(missing_ok=True)
    check("(#680/#1092) بطاقة تحليل مبنيّة فعليًا بلا مرشَّح رئيسي (وجه مرفوض) "
          "⇒ used_original=False -- خلفية مصممة لا صورة الوجه",
          report_1.get("used_original") is False and report_1.get("kind") is None,
          report_1)

    # ── اسم ناشر بحروف لا يعرفها خط التذييل (Issue #1145): «ערוץ 14» كان
    # يُرسم مربعات فارغة (منشور 2026-10-01، المسودة 96cdae9dca18). القرار
    # التحريري: الاسم غير العربي/اللاتيني يُعرض باسمه العربي name_ar دائمًا.
    from src import imaging as imaging_1145
    resolver = getattr(imaging_1145, "resolve_publisher_names", None)
    cfg_1145 = load_config()
    got_1145 = resolver(["ערוץ 14"], cfg_1145) if resolver else None
    check("(#1145) «ערוץ 14» يُستبدل باسمه العربي «القناة 14» قبل رسم سطر المصدر",
          got_1145 == ["القناة 14"], got_1145)

    # ── تصميم البطاقة المربعة الجديد (Issue #1158): حالتان ذهبيتان على الدالة
    # الحقيقية. (1) التحليل يعرض نصّ مساره كما هو بلا بادئة «المصدر:»؛
    # (2) «صورة: …» لناشر الصورة لم يعد يُرسم على أي بطاقة (يبقى داخليًا في
    # image_info فقط). نلتقط ما رُسم فعلًا عبر draw_text. ──
    from src import imaging as imaging_1158
    cfg_1158 = load_config()
    drawn_1158: list[str] = []
    real_draw_1158 = imaging_1158.draw_text
    real_download_1158 = imaging_1158.download_image

    def spy_1158(draw, xy, text, *a, **k):
        drawn_1158.append(text)
        return real_draw_1158(draw, xy, text, *a, **k)

    photo_1158 = _GoldenImage.new("RGB", (900, 600), (30, 90, 160))
    imaging_1158.draw_text = spy_1158  # type: ignore
    imaging_1158.download_image = lambda *a, **k: photo_1158  # type: ignore
    out_1158 = DRAFTS_DIR / "golden_1158.jpg"
    try:
        analysis_line = "تحليل لتغطية سي إن إن ترك وخلق تي في"
        imaging_1158.build_post_image(
            headline="عنوان تحليل تجريبي", category="", urgent=False,
            image_urls=None, fallback_urls=["https://example.com/x.jpg"],
            publisher=[analysis_line], cfg=cfg_1158, out_path=out_1158,
            bucket="", origin="analysis")
        analysis_drawn = list(drawn_1158)
        drawn_1158.clear()
        imaging_1158.build_post_image(
            headline="عنوان خبر تجريبي", category="سياسة", urgent=False,
            image_urls=None, publisher=["الجزيرة"], cfg=cfg_1158, out_path=out_1158,
            bucket="serious", origin="news",
            news_photo_provider=lambda: [{"url": "https://example.com/p.jpg",
                                          "publisher": "ناشر آخر"}])
        news_drawn = list(drawn_1158)
    finally:
        imaging_1158.draw_text = real_draw_1158  # type: ignore
        imaging_1158.download_image = real_download_1158  # type: ignore
        out_1158.unlink(missing_ok=True)
    check("(#1158) بطاقة التحليل: سطر المصدر يُرسم كما مرّره المسار بلا «المصدر:»",
          analysis_line in analysis_drawn
          and not any(str(t).startswith("المصدر:") for t in analysis_drawn),
          analysis_drawn)
    check("(#1158) بطاقة خبر بصورة ناشر آخر: لا «صورة:» على البطاقة، والمصدر باقٍ",
          not any("صورة:" in str(t) for t in news_drawn)
          and "المصدر: الجزيرة" in news_drawn,
          news_drawn)


def test_important_false_guard() -> None:
    """حارس حكم «false» لمسار «هام» (Issue #1194) — لا يصدر إلا بنفي صريح
    من مصدرين مستقلين أو من جهة تدقيق واحدة؛ غياب المصادر أو نفي مصدر واحد
    غير مدقِّق أو نفي نسختين من خبر واحد لا يكفي أبدًا. تجري الحالات على
    الأنبوب كله (نص ← important.judge ← الملف المحفوظ) بمزيَّفات الشبكة
    والنموذج، لا على دالة الحكم وحدها."""
    try:
        from src import important
    except ImportError as exc:
        check("(#1194) src/important.py موجودة", False, str(exc))
        return

    cfg = load_config()
    denial = "تنفي المصادر وقوع الحادثة وتؤكد أنها لم تحدث إطلاقًا في المنطقة."
    cut = "لم تحدث إطلاقًا"

    def run(case: int, docs, classify) -> dict:
        marker = f"كلمةحارس{case}"
        pt = important_point(marker, f"وقعت حادثة {marker} في المدينة")
        with ImportantRig([pt], {marker: docs}, classify):
            important.judge("نص الـIssue كاملًا", 94000 + case, cfg)
        return important.load_saved(94000 + case)["points"][0]

    def refute_all(point, names):
        return {"sources": [important_stance(n, "refutes", cut) for n in names]}

    # g1) صفر مصادر ← not_found لا false
    p1 = run(1, [], refute_all)
    check("(g1) صفر مصادر ⇒ not_found لا false", p1["verdict"] == "not_found", p1["verdict"])

    # g2) مصدر واحد غير مدقِّق ينفي صراحة ← not_found بملاحظة «نفي غير كافٍ»
    p2 = run(2, [important_doc("وكالة الأنباء الشرقية", denial)], refute_all)
    check("(g2) نفي مصدر واحد غير مدقِّق ⇒ not_found بملاحظة «نفي غير كافٍ»",
          p2["verdict"] == "not_found" and "نفي غير كافٍ" in (p2.get("note") or ""),
          (p2["verdict"], p2.get("note")))

    # g3) مصدران ينفيان لكنهما إعادة نشر للخبر نفسه ← not_found (مستقل واحد)
    original = important_doc("صحيفة الشرق", denial)
    reprint = important_doc("موقع الغرب", "نقلًا عن صحيفة الشرق: " + denial)
    p3 = run(3, [original, reprint], refute_all)
    check("(g3) نافيان أحدهما إعادة نشر للآخر ⇒ not_found (مصدر مستقل واحد فقط)",
          p3["verdict"] == "not_found", p3["verdict"])

    # g4) مصدران مستقلان ينفيان صراحة ← false
    p4 = run(4, [important_doc("صحيفة الشرق", denial),
                 important_doc("موقع الغرب", "مصدر مستقل يكتب: " + denial)],
             refute_all)
    check("(g4) مصدران مستقلان ينفيان صراحة ⇒ false مع refuted_by",
          p4["verdict"] == "false" and len(p4.get("refuted_by") or []) == 2,
          (p4["verdict"], p4.get("refuted_by")))

    # g5) جهة تدقيق واحدة من القائمة تنفي ← false
    p5 = run(5, [important_doc("Misbar", denial)], refute_all)
    check("(g5) جهة تدقيق واحدة من القائمة تنفي ⇒ false",
          p5["verdict"] == "false", p5["verdict"])

    # g6) مصدران يؤيدان الحدث ويختلفان مع النقطة في الرقم ← inaccurate لا false
    num_text = "وقعت الحادثة وأسفرت عن ثلاثة قتلى بحسب الحصيلة الرسمية."

    def conflict_all(point, names):
        return {"sources": [important_stance(
            n, "conflicts_detail", "ثلاثة قتلى", detail="عدد القتلى",
            correct_form="ثلاثة قتلى") for n in names]}

    p6 = run(6, [important_doc("صحيفة الشرق", num_text),
                 important_doc("موقع الغرب", "تقرير مستقل: " + num_text)],
             conflict_all)
    check("(g6) مصدران يؤيدان الحدث ويخالفان الرقم ⇒ inaccurate لا false",
          p6["verdict"] == "inaccurate", p6["verdict"])

    # ── Issue #1198 (المهمة 1ب): الحالات الثلاث التالية تُكتب قبل أي كود ──
    # g7) مدقّق معروف بنطاقه وحده، والناشر باسم «مسبار» ← false
    p7 = run(7, [important_doc("مسبار", denial, link="https://misbar.com/factcheck/x")],
             refute_all)
    check("(g7) ناشر باسم «مسبار» على نطاق misbar.com ينفي ⇒ false",
          p7["verdict"] == "false", (p7["verdict"], p7.get("note")))
    p7b = run(17, [important_doc("موقع التحقق الشرقي", denial,
                                 link="https://www.misbar.com/factcheck/y")],
              refute_all)
    check("(g7) النطاق وحده (اسم ناشر غير معروف) يكفي لجهة التدقيق ⇒ false",
          p7b["verdict"] == "false", (p7b["verdict"], p7b.get("note")))

    # g8) asserted يقول «كذبة» ولا مصدر ينفي ← لا false (asserted ليس دليلًا)
    marker8 = "كلمةحارس8"
    pt8 = important_point(marker8, f"وقعت حادثة {marker8} في المدينة",
                          asserted="النص الملصق يصفها بأنها كذبة مفضوحة")
    seen_8: list[str] = []

    def classify_8(point, names):
        seen_8.append(point)
        return {"sources": [important_stance(n, "irrelevant") for n in names]}

    with ImportantRig([pt8], {marker8: [important_doc("صحيفة الشرق", "نص عن الحادثة.")]},
                      classify_8):
        important.judge("نص الـIssue كاملًا", 94008, cfg)
    p8 = important.load_saved(94008)["points"][0]
    check("(g8) asserted «كذبة» بلا مصدر ينفي ⇒ لا false",
          p8["verdict"] != "false", p8["verdict"])
    check("(g8) asserted لا يصل نداء التصنيف",
          seen_8 and all("كذبة" not in s for s in seen_8), seen_8)

    # g9) نتيجة من نطاق مستبعد (facebook.com) تنفي ← لا تُحسب
    p9 = run(9, [important_doc("صفحة فيسبوك أ", denial, link="https://www.facebook.com/p/1"),
                 important_doc("صفحة فيسبوك ب", denial, link="https://m.facebook.com/p/2")],
             refute_all)
    check("(g9) نفي من facebook.com لا يُحسب ⇒ لا false ولا أدلة منه",
          p9["verdict"] != "false" and not p9["evidence"], (p9["verdict"], p9["evidence"]))

    # ── Issue #1200 (المهمة 1ج): g10–g12 تُكتب قبل أي كود ──
    # g10) مصدران مستقلان «يخالفان في تفصيل» لكن same_event=false ← لا inaccurate
    def conflict_other(point, names):
        return {"sources": [important_stance(
            n, "conflicts_detail", "ثلاثة قتلى", detail="عدد القتلى",
            correct_form="ثلاثة قتلى", same_event=False) for n in names]}

    p10 = run(10, [important_doc("صحيفة الشرق", num_text),
                   important_doc("موقع الغرب", "تقرير مستقل: " + num_text)],
              conflict_other)
    check("(g10) مخالفة تفصيل من مصدرين مستقلين بلا same_event ⇒ لا inaccurate",
          p10["verdict"] != "inaccurate" and p10["correction"] is None,
          (p10["verdict"], p10["correction"]))

    # g11) مدقّق ينفي بمقتطف حرفي لكن same_event=false ← لا false
    def refute_other(point, names):
        return {"sources": [important_stance(n, "refutes", cut, same_event=False)
                            for n in names]}

    p11 = run(11, [important_doc("Misbar", denial,
                                 link="https://misbar.com/factcheck/z")], refute_other)
    check("(g11) مدقّق ينفي بمقتطف حرفي وsame_event=false ⇒ لا false",
          p11["verdict"] != "false" and not p11["refuted_by"],
          (p11["verdict"], p11["refuted_by"]))

    # g12) nearest من بلد آخر بلا كيان مشترك ← null
    marker12 = "كلمةحارس12"
    pt12 = important_point(marker12, f"وقعت حادثة {marker12} في تركيا", entities=["تركيا"])

    def classify_12(point, names):
        return {"sources": [important_stance(n, "irrelevant") for n in names],
                "nearest_events": [{"title": "احتجاجات في سوريا على رفع أسعار المحروقات",
                                    "description": "احتجاجات واسعة في محافظات سورية",
                                    "sources": list(names)}]}

    with ImportantRig([pt12], {marker12: [
            important_doc("صحيفة الشرق", "احتجاجات سوريا على المحروقات."),
            important_doc("موقع الغرب", "تقرير مستقل عن احتجاجات سوريا.")]}, classify_12):
        important.judge("نص الـIssue كاملًا", 94012, cfg)
    p12 = important.load_saved(94012)["points"][0]
    check("(g12) nearest من بلد آخر بلا كيان مشترك ⇒ null",
          p12["nearest"] is None, p12["nearest"])

    # ── Issue #1203 (المهمة 1د): g13–g16 تُكتب قبل أي كود ──
    def run_claim(case: int, claim: dict, docs, classify) -> dict:
        marker = f"كلمةحارس{case}"
        claim = {"entities": [marker], "queries": [{"lang": "ar", "q": claim["claim"]}],
                 **claim, "claim": claim["claim"].replace("@", marker)}
        claim["queries"] = [{"lang": "ar", "q": claim["claim"]}]
        with ImportantRig([claim], {marker: docs}, classify):
            important.judge("نص الـIssue كاملًا", 94000 + case, cfg)
        return important.load_saved(94000 + case)["points"][0]

    video_txt = ("الفيديو الذي انتشر قديم ولم يحدث إرسال 450 ألف جندي إلى سوريا، "
                 "فالمشاهد تعود إلى عرض عسكري سابق.")
    circ = {"claim": "@ أرسلت 450 ألف جندي إلى سوريا", "framing": "circulating",
            "circulating_context": "فيديو انتشر صيف 2026", "numbers": ["450 ألف"]}

    # g13) ادّعاء circulating، مصدران مستقلان يؤكدان انتشار الفيديو وينفيان مضمونه ← false
    p13 = run_claim(13, circ, [
        important_doc("صحيفة الشرق", video_txt),
        important_doc("موقع الغرب", "تحقق مستقل: " + video_txt)],
        lambda pt, names: {"sources": [important_stance(
            n, "refutes", "ولم يحدث إرسال 450 ألف جندي إلى سوريا") for n in names]})
    check("(g13) circulating: مصدران يؤكدان الانتشار وينفيان المضمون ⇒ false لا confirmed",
          p13["verdict"] == "false" and len(p13.get("refuted_by") or []) == 2,
          (p13["verdict"], p13.get("refuted_by")))

    # g14) ادّعاء circulating، مصدران يؤكدان الانتشار فقط بلا كلمة عن المضمون ← not_found
    spread = "انتشر مقطع فيديو على مواقع التواصل الاجتماعي خلال الصيف وتداوله كثيرون."
    p14 = run_claim(14, circ, [
        important_doc("صحيفة الشرق", spread),
        important_doc("موقع الغرب", "ذكرت وسيلة مستقلة: " + spread)],
        lambda pt, names: {"sources": [important_stance(
            n, "supports", "انتشر مقطع فيديو على مواقع التواصل الاجتماعي") for n in names]})
    check("(g14) circulating: تأكيد الانتشار وحده ⇒ لا confirmed ولا false (not_found)",
          p14["verdict"] == "not_found" and not p14.get("refuted_by"),
          (p14["verdict"], p14.get("refuted_by")))

    # g15) مصدران من news-pravda.com (شبكة دعاية) يؤيدان ← لا يُحسبان
    p15 = run(15, [
        important_doc("News-pravda", "وقعت الحادثة فعلًا بحسب التقرير.",
                      link="https://syria.news-pravda.com/syria/2026/09/11/1.html"),
        important_doc("News-pravda EN", "الحادثة وقعت وفق ما نشر الموقع.",
                      link="https://news-pravda.com/world/2026/09/12/2.html")],
        lambda pt, names: {"sources": [important_stance(n, "supports", "الحادثة") for n in names]})
    check("(g15) مصدران من news-pravda.com يؤيدان ⇒ لا يُحسبان (لا confirmed ولا أدلة)",
          p15["verdict"] != "confirmed" and not p15["evidence"], (p15["verdict"], p15["evidence"]))

    # g16) «86.1 مليون» و«86 مليوناً و92 ألفاً و168» يخالفان «85.7 مليون» ← inaccurate
    pop = {"claim": "بلغ عدد سكان @ في نهاية 2025 نحو 85.7 مليون نسمة", "numbers": ["85.7 مليون"]}
    forms = {"موقع الأرقام": "86.1 مليون نسمة",
             "صحيفة الشرق": "86 مليوناً و92 ألفاً و168 نسمة"}

    def conflict_pop(pt, names):
        return {"sources": [important_stance(
            n, "conflicts_detail", forms[n], detail="العدد 85.7 مليونًا غير دقيق",
            correct_form=forms[n]) for n in names]}

    p16 = run_claim(16, pop, [
        important_doc(n, f"بلغ عدد السكان {t} نهاية 2025 بحسب الإحصاء.") for n, t in forms.items()],
        conflict_pop)
    check("(g16) صيغتان متفقتان عدديًا تخالفان 85.7 مليون ⇒ inaccurate والصحيح 86,092,168",
          p16["verdict"] == "inaccurate"
          and (p16.get("correction") or {}).get("correct_value") == "86,092,168",
          (p16["verdict"], p16.get("correction")))

    # ── Issue #1205 (المهمة 1هـ): g17–g20 تُكتب قبل أي كود ──
    # g17) مصدران متفقان على رقم لكن as_of لكليهما «أكتوبر 2026» والنقطة «نهاية 2025» ← لا inaccurate
    oct_forms = {"موقع الأرقام": "86 مليوناً و92 ألفاً و168 نسمة",
                 "صحيفة الشرق": "86 مليوناً و92 ألفاً و168 نسمة"}
    pop17 = {"claim": "بلغ عدد سكان @ في نهاية 2025 نحو 85.7 مليون نسمة",
             "numbers": ["85.7 مليون"], "dates": ["نهاية 2025"]}

    def conflict_oct(pt, names):
        return {"sources": [important_stance(
            n, "conflicts_detail", oct_forms[n], detail="العدد غير دقيق",
            correct_form=oct_forms[n], as_of="أكتوبر 2026") for n in names]}

    p17 = run_claim(17, pop17, [
        important_doc(n, f"بلغ عدد السكان {t} في أكتوبر 2026 بحسب الإحصاء.")
        for n, t in oct_forms.items()], conflict_oct)
    check("(g17) مصدران متفقان لكن as_of «أكتوبر 2026» والنقطة «نهاية 2025» ⇒ لا inaccurate",
          p17["verdict"] != "inaccurate" and not p17.get("correction"),
          (p17["verdict"], p17.get("correction")))

    # g18) correct_value ضمن الهامش من رقم النقطة ← supports لا inaccurate
    pop18 = {"claim": "بلغ عدد سكان @ نحو 86,092,168 نسمة", "numbers": ["86,092,168"]}
    forms18 = {"موقع الأرقام": "86.1 مليون نسمة", "صحيفة الشرق": "86.1 مليون نسمة"}

    def conflict_margin(pt, names):
        return {"sources": [important_stance(
            n, "conflicts_detail", forms18[n], detail="الرقم مختلف",
            correct_form=forms18[n]) for n in names]}

    p18 = run_claim(18, pop18, [
        important_doc(n, f"بلغ عدد السكان {t} بحسب الإحصاء.") for n, t in forms18.items()],
        conflict_margin)
    check("(g18) «86.1 مليون» مقابل 86,092,168 ضمن الهامش ⇒ supports لا inaccurate",
          p18["verdict"] == "confirmed" and not p18.get("correction")
          and {e["stance"] for e in p18["evidence"]} == {"supports"},
          (p18["verdict"], p18.get("correction"), p18["evidence"]))

    # g19) وثيقة واحدة من datareportal.com تؤيد بمقتطف يحمل الرقم ← confirmed، و«تنفي» ← لا false
    pop19 = {"claim": "بلغ عدد مستخدمي الإنترنت في @ نحو 77.5 مليون مستخدم", "numbers": ["77.5 مليون"]}
    dr_text = "Turkey had 77.5 million internet users at the start of 2026."
    dr_link = "https://datareportal.com/reports/digital-2026-turkey"
    p19 = run_claim(19, pop19, [important_doc("Global Digital Insights", dr_text, link=dr_link)],
                    lambda pt, names: {"sources": [important_stance(
                        n, "supports", "Turkey had 77.5 million internet users") for n in names]})
    check("(g19) وثيقة واحدة من datareportal.com تؤيد بمقتطف يحمل الرقم ⇒ confirmed بـprimary_source",
          p19["verdict"] == "confirmed" and p19.get("primary_source") is True,
          (p19["verdict"], p19.get("primary_source")))
    p19b = run_claim(19, pop19, [important_doc("Global Digital Insights", dr_text, link=dr_link)],
                     lambda pt, names: {"sources": [important_stance(
                         n, "refutes", "Turkey had 77.5 million internet users") for n in names]})
    check("(g19) الوثيقة نفسها «تنفي» ⇒ لا false (الجهة الأصلية لا تُحسب للنفي)",
          p19b["verdict"] != "false" and not p19b.get("refuted_by"),
          (p19b["verdict"], p19b.get("refuted_by")))

    # g20) مصدر واحد مستقل ينفي + لا مدقّق ← not_found (البحث الموجَّه لا يغيّر الحارس)
    p20 = run(20, [important_doc("وكالة الأنباء الشرقية", denial)], refute_all)
    check("(g20) نفي مصدر واحد مستقل بلا مدقّق ⇒ not_found",
          p20["verdict"] == "not_found" and not p20.get("refuted_by"),
          (p20["verdict"], p20.get("refuted_by")))

    # ── Issue #1207 (المهمة 1و): g21–g25 تُكتب قبل أي كود ──
    # نفي المدقّق الواحد يحتاج حكمًا صريحًا: verdict_label ضمن false_labels ومقتطفًا جملة حكم لا سؤالًا
    teyit_link = "https://teyit.org/analiz/turkiye-450-bin-asker-suriye"
    q_title = "Türkiye'nin Suriye'ye 450 bin asker gönderdiğini mi gösteriyor?"
    claim_1207 = {"claim": "@ أرسلت 450 ألف جندي إلى سوريا", "numbers": ["450 ألف"]}

    def one_checker(case: int, page: str, excerpt: str, label: str, stance: str = "refutes") -> dict:
        return run_claim(case, claim_1207, [important_doc("Teyit", page, link=teyit_link)],
                         lambda pt, names: {"sources": [important_stance(
                             n, stance, excerpt, verdict_label=label) for n in names]})

    # g21) مدقّق واحد، المقتطف عنوانه السؤالي، بلا verdict_label ← لا false
    p21 = one_checker(21, q_title + " Eski bir video.", q_title, "")
    check("(g21) مدقّق واحد ومقتطفه عنوان سؤالي بلا verdict_label ⇒ لا false",
          p21["verdict"] != "false" and not p21.get("refuted_by"),
          (p21["verdict"], p21.get("refuted_by")))
    p21b = one_checker(21, q_title + " Eski bir video.", q_title, "Yanlış")
    check("(g21) حتى مع verdict_label «Yanlış» المقتطف السؤالي ليس جملة حكم ⇒ لا false",
          p21b["verdict"] != "false", p21b["verdict"])

    # g22) verdict_label «Yanıltıcı» (مضلِّل) ومقتطف حكم ← لا false
    p22 = one_checker(22, "Bu iddia yanıltıcı. Eski bir video.", "Bu iddia yanıltıcı", "Yanıltıcı")
    check("(g22) مدقّق واحد بحكم «Yanıltıcı» ⇒ لا false",
          p22["verdict"] != "false" and not p22.get("refuted_by"),
          (p22["verdict"], p22.get("refuted_by")))

    # g23) verdict_label «Yanlış» ومقتطف حكم ← false
    p23 = one_checker(23, "Bu iddia için İddia yanlış. Eski bir video.", "İddia yanlış", "Yanlış")
    check("(g23) مدقّق واحد بحكم «Yanlış» ومقتطف «İddia yanlış» ⇒ false",
          p23["verdict"] == "false"
          and [r["excerpt"] for r in p23.get("refuted_by") or []] == ["İddia yanlış"],
          (p23["verdict"], p23.get("refuted_by")))

    # g24) مدقّق بعنوان سؤالي وحكمه «Doğru» ← supports لا false
    p24 = one_checker(24, q_title + " Evet, doğru.", q_title, "Doğru")
    check("(g24) عنوان سؤالي وحكم «Doğru» ⇒ supports لا false",
          p24["verdict"] != "false" and not p24.get("refuted_by")
          and {e["stance"] for e in p24["evidence"]} == {"supports"},
          (p24["verdict"], p24["evidence"]))

    # g25) صيغتا تصحيح «85.7 مليون» و«86.1 مليون» لا تتفقان (الهامش نفسه: نصف وحدة الأقل دقة)
    icfg_1207 = cfg.get("important", {})
    check("(g25) صيغتا تصحيح «85.7 مليون» و«86.1 مليون» لا تتفقان",
          not important._agree("85.7 مليون", "86.1 مليون", icfg_1207)
          and important._agree("86.1 مليون", "86 مليوناً و92 ألفاً و168", icfg_1207),
          (important._agree("85.7 مليون", "86.1 مليون", icfg_1207),
           important._agree("86.1 مليون", "86 مليوناً و92 ألفاً و168", icfg_1207)))

    # ── Issue #1210 (المهمة 1ز): g26–g30 تُكتب قبل أي كود ──
    # حكم المدقّق يُقرأ من ClaimReview في HTML الخام لا من النص المستخرج (226 حرفًا = العنوان)
    from tests.helpers import claim_review_html
    short_page = (q_title + " Teyit " * 40)[:226]
    claimed_ok = "Türkiye'nin Suriye'ye 450 bin asker gönderdiği"
    claimed_other = "Erdoğan'ın yarın istifa edeceği"

    def lazy_title_refutes(pt, names):
        # النموذج كما في التجربة الخامسة: ينفي بمقتطف العنوان السؤالي ولا يذكر حكمًا
        return {"sources": [important_stance(n, "refutes", q_title, verdict_label="")
                            for n in names]}

    def run_cr(case: int, html: str, link: str = teyit_link, name: str = "Teyit",
               same_event: bool = True):
        marker = f"كلمةحارس{case}"
        claim = {"entities": [marker], "claim": claim_1207["claim"].replace("@", marker),
                 "numbers": ["450 ألف"]}
        claim["queries"] = [{"lang": "ar", "q": claim["claim"]}]
        docs = [important_doc(name, short_page, link=link, html=html)]

        def fn(pt, names):
            out = lazy_title_refutes(pt, names)
            for s in out["sources"]:
                s["same_event"] = same_event
            return out
        rig = ImportantRig([claim], {marker: docs}, fn)
        with rig:
            important.judge("نص الـIssue كاملًا", 94000 + case, cfg)
        return important.load_saved(94000 + case)["points"][0], rig

    check("(g26) نص صفحة Teyit المستخرَج 226 حرفًا", len(short_page) == 226, len(short_page))
    p26, rig26 = run_cr(26, claim_review_html("Yanlış", claimed_ok))
    check("(g26) ClaimReview «Yanlış» في HTML الخام وclaimReviewed مطابق ⇒ false",
          p26["verdict"] == "false"
          and [r["excerpt"] for r in p26.get("refuted_by") or []] == ["Yanlış"],
          (p26["verdict"], p26.get("refuted_by")))
    check("(g26) نداء التصنيف يرى سطر «بيانات التدقيق المنظَّمة» بالادّعاء والحكم",
          "بيانات التدقيق المنظَّمة" in rig26.last_content and claimed_ok in rig26.last_content
          and "الحكم: Yanlış" in rig26.last_content, rig26.last_content[-300:])

    p27, _ = run_cr(27, claim_review_html("Yanlış", claimed_other), same_event=False)
    check("(g27) ClaimReview «Yanlış» لكن claimReviewed عن ادّعاء آخر (same_event=false) ⇒ لا false",
          p27["verdict"] != "false" and not p27.get("refuted_by"),
          (p27["verdict"], p27.get("refuted_by")))

    p28, _ = run_cr(28, claim_review_html("Yanıltıcı", claimed_ok))
    check("(g28) ClaimReview «Yanıltıcı» ⇒ لا false",
          p28["verdict"] != "false" and not p28.get("refuted_by"),
          (p28["verdict"], p28.get("refuted_by")))

    p29, rig29 = run_cr(29, claim_review_html("Yanlış", claimed_ok),
                        link="https://haberler.example/analiz/video", name="Haberler")
    check("(g29) ClaimReview في صفحة نطاقها ليس في fact_check_domains ⇒ يُتجاهل",
          p29["verdict"] != "false" and not p29.get("refuted_by")
          and "بيانات التدقيق المنظَّمة" not in rig29.last_content
          and all(d.get("claim_review") is None for d in p29["read_docs"]),
          (p29["verdict"], [d.get("claim_review") for d in p29["read_docs"]]))

    p30, _ = run_cr(30, claim_review_html("Doğru", claimed_ok))
    check("(g30) ClaimReview «Doğru» ⇒ supports لا false",
          p30["verdict"] != "false" and not p30.get("refuted_by")
          and {e["stance"] for e in p30["evidence"]} == {"supports"},
          (p30["verdict"], p30["evidence"]))

    # ── Issue #1214 (المهمة 1ط): g31–g35 تُكتب قبل أي كود ──
    # «أدلة متعارضة» تُحسب من supports الصريحة وحدها؛ وشرط as_of للأرقام وحدها (detail_kind)
    sun = {"claim": "@ أكدت أن الشمس ستشرق من المغرب"}
    refuters_1214 = ["صحيفة الشرق", "موقع الغرب"]
    conflictors_1214 = ["وكالة الشمال", "قناة الجنوب", "مجلة الوسط"]

    def mixed(case: int, refute: list[str], conflict: list[str], support: list[str]):
        stance_of = {**{n: "refutes" for n in refute}, **{n: "conflicts_detail" for n in conflict},
                     **{n: "supports" for n in support}}
        docs = [important_doc(n, ("مصدر مستقل يكتب: " + denial) if s == "refutes"
                              else f"تقرير {n} مستقل عن الشمس والمغرب والأرصاد.")
                for n, s in stance_of.items()]

        def fn(pt, names):
            out = []
            for n in names:
                s = stance_of[n]
                out.append(important_stance(
                    n, s, cut if s == "refutes" else "الشمس تشرق من المشرق",
                    detail="جهة الشروق", correct_form="الشمس تشرق من المشرق",
                    detail_kind="other") if s != "supports" else important_stance(
                    n, s, "الشمس والمغرب"))
            return {"sources": out}
        return run_claim(case, sun, docs, fn)

    p31 = mixed(31, refuters_1214, conflictors_1214, [])
    check("(g31) نافيان مستقلان + ثلاثة conflicts_detail متفقة + صفر supports ⇒ false",
          p31["verdict"] == "false" and len(p31.get("refuted_by") or []) == 2,
          (p31["verdict"], p31.get("note")))

    p32 = mixed(32, refuters_1214, [], ["مجلة الوسط", "قناة الجنوب"])
    check("(g32) نافيان مستقلان + مؤيدان مستقلان ⇒ لا false («أدلة متعارضة»)",
          p32["verdict"] != "false" and "أدلة متعارضة" in (p32.get("note") or ""),
          (p32["verdict"], p32.get("note")))

    p33 = mixed(33, ["صحيفة الشرق"], conflictors_1214, [])
    check("(g33) نافٍ واحد غير مدقّق + ثلاثة conflicts_detail ⇒ لا false",
          p33["verdict"] != "false" and not p33.get("refuted_by"),
          (p33["verdict"], p33.get("refuted_by")))

    # g34) نقطة تاريخ: التصحيح يسري رغم as_of 2021 ≠ زمن النقطة (الخطأ هو التاريخ نفسه)
    launch = {"claim": "أُطلق تلسكوب @ في 25 ديسمبر 2023", "dates": ["25 ديسمبر 2023"]}
    date_forms = {"موقع الأرقام": "25 ديسمبر 2021", "صحيفة الشرق": "December 25, 2021"}

    def conflict_date(pt, names):
        return {"sources": [important_stance(
            n, "conflicts_detail", date_forms[n], detail="تاريخ الإطلاق",
            correct_form=date_forms[n], as_of="2021", detail_kind="date") for n in names]}

    p34 = run_claim(34, launch, [
        important_doc(n, f"أُطلق التلسكوب في {t} من غويانا الفرنسية.") for n, t in date_forms.items()],
        conflict_date)
    check("(g34) تاريخ «25 ديسمبر 2023» ومصدران مستقلان detail_kind=date بـ2021 ⇒ inaccurate بتصحيح 2021",
          p34["verdict"] == "inaccurate"
          and "2021" in (p34.get("correction") or {}).get("correct", "")
          and (p34.get("correction") or {}).get("detail_kind") == "date",
          (p34["verdict"], p34.get("correction")))

    # g35) رقم إحصائي: شرط as_of باقٍ
    stat = {"claim": "بلغ عدد سكان @ في نهاية 2025 نحو 85.7 مليون نسمة",
            "numbers": ["85.7 مليون"], "dates": ["نهاية 2025"]}

    def conflict_num(pt, names):
        return {"sources": [important_stance(
            n, "conflicts_detail", "86.1 مليون", detail="العدد غير دقيق",
            correct_form="86.1 مليون", as_of="أكتوبر 2026", detail_kind="number")
            for n in names]}

    p35 = run_claim(35, stat, [
        important_doc(n, "بلغ عدد السكان 86.1 مليون في أكتوبر 2026 بحسب الإحصاء.")
        for n in ("موقع الأرقام", "صحيفة الشرق")], conflict_num)
    check("(g35) رقم إحصائي ومصدران detail_kind=number لكن as_of لزمن آخر ⇒ لا inaccurate",
          p35["verdict"] != "inaccurate" and not p35.get("correction"),
          (p35["verdict"], p35.get("correction")))

    # ── Issue #1225 (المهمة 3ب): g42–g43 تُكتبان قبل أي كود ──
    # g42) confirmed + مصدران مستقلان بـsuperseded_by متفق ← inaccurate بتصحيح الأحدث
    sup_claim = {"claim": "اكتشاف @ أبعد مجرة معروفة حتى الآن بتلسكوب جيمس ويب",
                 "numbers": [], "dates": []}
    newer = {"fact": "تجاوزتها المجرة MoM-z14 المرصودة", "date": "16 مايو 2025"}
    sup_text = "رصد التلسكوب مجرة هي أبعد مجرة معروفة حتى الآن بحسب الإعلان."

    def sup_all(n_sup):
        def classify(pt, names):
            rows = []
            for i, n in enumerate(names):
                kw = {"superseded_by": newer} if i < n_sup else {}
                rows.append(important_stance(n, "supports", "أبعد مجرة معروفة حتى الآن", **kw))
            return {"sources": rows}
        return classify

    docs3 = [important_doc(n, sup_text) for n in ("صحيفة الشرق", "موقع الغرب", "مجلة الفضاء")]
    p42 = run_claim(42, sup_claim, docs3, sup_all(2))
    cor = p42.get("correction") or {}
    check("(g42) مصدران مستقلان بـsuperseded_by متفق ⇒ inaccurate بتصحيح الحقيقة الأحدث بتاريخها",
          p42["verdict"] == "inaccurate" and "MoM-z14" in cor.get("correct", "")
          and "مايو 2025" in cor.get("correct", "") and cor.get("detail_kind") == "superseded",
          (p42["verdict"], cor))

    # g43) confirmed + مصدر واحد بـsuperseded_by ← يبقى confirmed مع note «قد يكون متجاوَزًا»
    p43 = run_claim(43, sup_claim, docs3, sup_all(1))
    check("(g43) مصدر واحد بـsuperseded_by ⇒ confirmed مع note «قد يكون متجاوَزًا» باسم الناشر",
          p43["verdict"] == "confirmed" and "قد يكون متجاوَزًا" in (p43.get("note") or "")
          and "MoM-z14" in (p43.get("note") or ""), (p43["verdict"], p43.get("note")))

    # ── Issue #1229 (المهمة 3ج): g44–g46 تُكتب قبل أي كود — شائعة «ناسا/الشمس من المغرب» حُكم
    # عليها confirmed ونُشرت. تجري على الحارس الحقيقي لـ«المؤيِّد المعروف» (strict_known=True) ──
    def run_strict(case: int, claim_text: str, docs, classify) -> dict:
        marker = f"كلمةحارس{case}"
        claim = claim_text.replace("@", marker)
        pt = {"entities": [marker], "claim": claim, "queries": [{"lang": "ar", "q": claim}]}
        with ImportantRig([pt], {marker: docs}, classify, strict_known=True):
            important.judge("نص الـIssue كاملًا", 94000 + case, cfg)
        return important.load_saved(94000 + case)["points"][0]

    event = "وقعت الحادثة الكبرى في المدينة بحسب التقارير المتداولة."

    def by_name(rules):
        def classify(point, names):
            rows = []
            for n in names:
                stance, excerpt, extra = rules.get(n, ("irrelevant", "", {}))
                rows.append(important_stance(n, stance, excerpt, **extra))
            return {"sources": rows}
        return classify

    sup = ("supports", "وقعت الحادثة الكبرى في المدينة", {})
    # g44) مصدران مستقلان غير معروفين يؤيدان + نفي من fatabyyano.net بلا verdict_label ← not_found
    unknown = [important_doc("موقع الشرق الإخباري", event),
               important_doc("منصة الغرب الرقمية", "تغطية مستقلة: " + event)]
    fact = important_doc("Fatabyyano", "ادّعاء مضلّل لم تقع الحادثة أصلًا.",
                         link="https://fatabyyano.net/en/x/")
    rules44 = {"موقع الشرق الإخباري": sup, "منصة الغرب الرقمية": sup,
               "Fatabyyano": ("refutes", "لم تقع الحادثة", {"verdict_label": ""})}
    p44 = run_strict(44, "وقعت الحادثة @ في المدينة", unknown + [fact], by_name(rules44))
    # #1288: القديم not_found بـ«أدلة متعارضة»؛ الجديد not_found بلا تلك العبارة — المؤيِّدان من خارج
    # مصادرنا مستبعدان فلا يؤيدان، والنفي وحده بلا حكم صريح «نفي غير كافٍ»
    check("(g44) مؤيِّدان من خارج مصادرنا + نفي من fatabyyano.net بلا verdict_label ⇒ not_found لا confirmed",
          p44["verdict"] == "not_found" and p44["outside_docs"] == 2
          and "أدلة متعارضة" not in (p44.get("note") or ""),
          (p44["verdict"], p44.get("note"), p44.get("outside_docs")))
    # ضابطة g44: نفي حرفي من مصدر مستقل (لا مدقّق) يمنع confirmed ولو كان المؤيِّدان معروفَين
    known2 = [important_doc("Reuters", event), important_doc("BBC", "تغطية مستقلة: " + event)]
    denier = important_doc("France24", "تؤكد المصادر أن الحادثة لم تقع إطلاقًا.")
    rules44b = {"Reuters": sup, "BBC": sup,
                "France24": ("refutes", "الحادثة لم تقع إطلاقًا", {"verdict_label": ""})}
    p44b = run_strict(144, "وقعت الحادثة @ في المدينة", known2 + [denier], by_name(rules44b))
    check("(g44) ضابطة: refutes بمقتطف حرفي من مصدر مستقل يمنع confirmed ولو كان المؤيِّدان معروفَين",
          p44b["verdict"] == "not_found" and "أدلة متعارضة" in (p44b.get("note") or ""),
          (p44b["verdict"], p44b.get("note")))

    # g45) مصدران مستقلان غير معروفين يؤيدان بلا أي نفي ← confirmed بتنبيه «من خارج مصادرنا المسجّلة»
    # (Issue #1282: كان not_found «تأييد من مصادر غير معروفة فقط»؛ أُلغي الشرط 2 بعد حادثة #1278)
    rules45 = {"موقع الشرق الإخباري": sup, "منصة الغرب الرقمية": sup}
    p45 = run_strict(45, "وقعت الحادثة @ في المدينة", unknown, by_name(rules45))
    # #1288: القديم confirmed بتنبيه «من خارج مصادرنا المسجّلة»؛ الجديد not_found (الموقعان مستبعدان والتنبيه أُلغي)
    check("(g45) مؤيِّدان مستقلان من خارج مصادرنا بلا نفي ⇒ not_found لا confirmed ولا تنبيه قديم",
          p45["verdict"] == "not_found" and p45["outside_docs"] == 2 and not p45.get("warnings")
          and "من خارج مصادرنا المسجّلة" not in (p45.get("note") or ""),
          (p45["verdict"], p45.get("note")))
    # ضابطة g45: مؤيِّد معروف واحد (BBC بالاسم) بين اثنين يكفي ⇒ confirmed
    mixed = [important_doc("BBC", event), important_doc("منصة الغرب الرقمية", "تغطية مستقلة: " + event)]
    p45b = run_strict(145, "وقعت الحادثة @ في المدينة", mixed,
                      by_name({"BBC": sup, "منصة الغرب الرقمية": sup}))
    check("(g45) ضابطة: مؤيِّد معروف واحد بين المؤيِّدين ⇒ confirmed بمصدر واحد (الآخر مستبعد)",
          p45b["verdict"] == "confirmed" and p45b["support_level"] == "single" and p45b["outside_docs"] == 1,
          (p45b["verdict"], p45b.get("note")))

    # g46) «أكدت ناسا…» + مؤيِّدان معروفان لا ينقلان عن ناسا + لا nasa.gov ← not_found
    claim46 = "أكدت ناسا أن @ سيحدث غدًا"
    plain = [important_doc("Reuters", "تتحدث التقارير عن أن الأمر سيحدث غدًا في المنطقة."),
             important_doc("BBC", "تقرير مستقل: تتحدث الأنباء عن أن الأمر سيحدث غدًا في المنطقة.")]
    s46 = ("supports", "الأمر سيحدث غدًا", {})
    p46 = run_strict(46, claim46, plain, by_name({"Reuters": s46, "BBC": s46}))
    check("(g46) ادّعاء منسوب لناسا + مؤيِّدان معروفان لا ينقلان عنها ولا nasa.gov ⇒ not_found",
          p46["verdict"] == "not_found" and "ناسا" in (p46.get("note") or ""),
          (p46["verdict"], p46.get("note")))
    # ضابطتا g46: نطاق الجهة نفسها مؤيِّدًا، أو معروف يسمّيها صراحة ⇒ confirmed
    nasa = [important_doc("Reuters", "تتحدث التقارير عن أن الأمر سيحدث غدًا في المنطقة."),
            important_doc("NASA", "بيان رسمي: الأمر سيحدث غدًا في المنطقة.",
                          link="https://www.nasa.gov/news/release/2026/10/05/x")]
    p46b = run_strict(146, claim46, nasa, by_name({"Reuters": s46, "NASA": s46}))
    check("(g46) ضابطة: أحد المؤيِّدين من نطاق nasa.gov ⇒ confirmed", p46b["verdict"] == "confirmed",
          (p46b["verdict"], p46b.get("note")))
    cites = [important_doc("Reuters", "قالت ناسا إن الأمر سيحدث غدًا في المنطقة بحسب بيانها."),
             important_doc("BBC", "تقرير مستقل: الأمر سيحدث غدًا بحسب ناسا.")]
    p46c = run_strict(246, claim46, cites, by_name({
        "Reuters": ("supports", "قالت ناسا إن الأمر سيحدث غدًا", {}),
        "BBC": ("supports", "الأمر سيحدث غدًا بحسب ناسا", {})}))
    check("(g46) ضابطة: مؤيِّد معروف ينقل عن ناسا صراحة ⇒ confirmed", p46c["verdict"] == "confirmed",
          (p46c["verdict"], p46c.get("note")))


def test_important_write_guards() -> None:
    """حارس الكتابة التحريري لمسار «هام» (Issue #1221، g36–g39) — يمسّ ما يُنشر، فتُكتب
    حالاته قبل الكود. تجري على الأنبوب كله: قضية ترشيح معلَّمة ← important_finalize ←
    كاتب مزيَّف يعيد عمدًا نصًّا مخالفًا ← الفحص في الكود بعد الكتابة لا في الموجّه وحده.
    كل حالة تتبعها ضابطة: النص السليم نفسه يُقبل (فالحارس ليس رفضًا شاملًا)."""
    import copy
    from datetime import datetime, timezone

    from src import important, important_finalize

    cfg = load_config()

    def run(case: int, point: dict, data: dict):
        number, sel = 96000 + case, 96500 + case
        point = copy.deepcopy(point)
        point["selection_issue"] = sel
        result = {"issue": number, "created_at": datetime.now(timezone.utc).isoformat(),
                  "topic": "", "error": None, "selection_issue": sel, "points": [point]}
        important.save(result)
        body = important_marked_body(result, {point["id"]: "go2"}, cfg)
        with ImportantWriteRig(lambda prompt, system: data) as rig:
            code = important_finalize.finalize(sel, body, cfg)
        saved = important.load_saved(number)["points"][0]
        return rig, code, saved, store.load_draft(saved["draft_id"]) if saved.get("draft_id") else None

    def rejected(name, rig, saved, draft, reason):
        notes = " ".join(t for _, t in rig.comments)
        check(f"({name}) المسودة لا تُقبل: لا مسودة ولا قضية مرحلة 2 والنقطة «failed» بسبب الكتابة الفاشلة",
              draft is None and rig.created == [] and saved["status"] == "failed"
              and reason in (saved.get("write_error") or ""), (saved["status"], saved.get("write_error")))
        check(f"({name}) والسبب «{reason}» في تعليق القضية، ومحاولة إعادة واحدة فقط (نداءان)",
              reason in notes and len(rig.calls) == 2, (len(rig.calls), notes[:200]))

    def accepted(name, rig, saved, draft):
        check(f"({name}) ضابطة: النص السليم يُقبل مسودةً origin=important بحكمها وشارتها ومعرّف نقطتها",
              draft is not None and draft[1]["origin"] == "important" and saved["status"] == "written"
              and draft[1]["point_id"] == saved["id"] and draft[1]["verdict"] == saved["verdict"],
              (saved["status"], saved.get("write_error")))

    # g36) false: العنوان يكرّر الشائعة حرفيًا
    fals = important_synthetic_point("false")
    bad = {**important_good_data(fals), "post_title": fals["claim"]}
    rig, _code, saved, draft = run(36, fals, bad)
    rejected("g36", rig, saved, draft, "عنوان التفنيد يكرّر الادّعاء")
    rig, _code, saved, draft = run(36, fals, important_good_data(fals))
    accepted("g36", rig, saved, draft)

    # g37) not_found بأقرب حدث: النص يذكر النقطة الأصلية
    near = important_synthetic_point("not_found")
    good = important_good_data(near)
    bad = {**good, "post_body": good["post_body"] + " علمًا أن " + near["text"] + "."}
    rig, _code, saved, draft = run(37, near, bad)
    rejected("g37", rig, saved, draft, "المقال يذكر النقطة الأصلية")
    rig, _code, saved, draft = run(37, near, good)
    accepted("g37", rig, saved, draft)
    check("(g37) المقال عن nearest وحده: عنوانه عنوان الحدث الأقرب لا نص النقطة",
          draft[1]["arabic"]["post_title"] == near["nearest"]["title"]
          and draft[1]["source"]["publishers"] == ["مصدر أ", "مصدر ب"], draft[1]["source"])

    # g38) inaccurate: النص لا يحوي correction.correct
    inacc = important_fixture_point(1201, "inaccurate")
    good = important_good_data(inacc)
    bad = {**good, "post_title": "عدد سكان تركيا ارتفع قليلًا",
           "post_body": "ارتفع عدد السكان بحسب آخر الإحصاءات الرسمية. أما الرقم المتداول فخطأ شائع."}
    rig, _code, saved, draft = run(38, inacc, bad)
    rejected("g38", rig, saved, draft, "الصيغة الصحيحة غائبة")
    rig, _code, saved, draft = run(38, inacc, good)
    accepted("g38", rig, saved, draft)

    # g39) false: النص لا يسمّي المدقّق
    good = important_good_data(fals)
    bad = {**good, "post_body": good["post_body"].replace("Fatabyyano", "جهة معنية")}
    rig, _code, saved, draft = run(39, fals, bad)
    rejected("g39", rig, saved, draft, "لا يسمّي المدقّق")
    rig, _code, saved, draft = run(39, fals, good)
    accepted("g39", rig, saved, draft)

    # ── Issue #1225: g40–g41 (اقتباس الادّعاء المصحَّح) تُكتبان قبل أي كود ──
    # g40) inaccurate: الكاتب يقتبس claim حرفيًا بين علامتي تنصيص ← لا رفض
    inacc = important_fixture_point(1225, "inaccurate")
    good = important_good_data(inacc)
    quoted = {**good, "post_body": good["post_body"] + f" وقد تردّد أن «{inacc['claim']}» وهذا غير دقيق."}
    rig, _code, saved, draft = run(40, inacc, quoted)
    accepted("g40", rig, saved, draft)
    # g41) inaccurate: الكاتب يقتبس جملة أخرى من جسم الـIssue غير claim ← رفض كما الآن
    other = {**good, "post_body": good["post_body"] + " وكتب صاحب النص «أبعد مجرة معروفة تحمل اسم JADES حتى الآن» بلا سند."}
    rig, _code, saved, draft = run(41, inacc, other)
    rejected("g41", rig, saved, draft, "اقتباس بين علامتي تنصيص")

    # ── Issue #1229: g47–g48 تُكتبان قبل أي كود ──
    # g47) كتابة بلا وقائع مسندة ← فشل كتابة، لا مسودة، ولا «بحسب معلومات المحرر» أبدًا
    def clean(point):
        # الأصل الحقيقي كُتب ثم فشل/نُشر: يبدأ هنا نظيفًا بلا أثر كتابة سابقة
        stale = ("draft_id", "written_at", "write_error", "failed_at", "write_failed", "action")
        return {k: v for k, v in point.items() if k not in stale}

    conf = clean(important_fixture_point(1229, "confirmed"))
    for case, ev in ((47, []), (147, [{"publisher": "موقع", "link": "https://m.example/1",
                                       "stance": "supports", "excerpt": ""}])):
        rig, _code, saved, draft = run(case, {**conf, "evidence": ev}, important_good_data(conf))
        notes = " ".join(t for _, t in rig.comments)
        check("(g47) نقطة بلا وقائع مسندة ← failed بسبب «لا وقائع مسندة»، لا مسودة ولا نداء كاتب",
              draft is None and saved["status"] == "failed" and rig.calls == []
              and "لا وقائع مسندة" in (saved.get("write_error") or ""),
              (saved["status"], saved.get("write_error"), len(rig.calls)))
        check("(g47) والسبب في تعليق قضية الترشيح ولا قضية مرحلة 2", "لا وقائع مسندة" in notes
              and rig.created == [], notes[:200])
    tagged = {**important_good_data(conf),
              "post_body": important_good_data(conf)["post_body"] + " وبحسب معلومات المحرر فالأمر كذلك."}
    rig, _code, saved, draft = run(247, conf, tagged)
    rejected("g47", rig, saved, draft, "موجز المحرر")
    check("(g47) توجيه الكاتب يمنع عبارة المحرر ونسبة الرأي صراحة (لا درجة ج)",
          rig.calls and "ممنوع ذكر عبارة" in rig.calls[0]["system"]
          and "بحسب معلومات المحرر" in rig.calls[0]["system"], rig.calls[:1])
    opinion = {**tagged, "post_body": tagged["post_body"].replace("وبحسب معلومات المحرر", "وترى الصفحة أن")}
    rig, _code, saved, draft = run(347, conf, opinion)
    rejected("g47", rig, saved, draft, "موجز المحرر")
    rig, _code, saved, draft = run(447, conf, important_good_data(conf))
    accepted("g47", rig, saved, draft)

    # g48) inaccurate بتصحيح مطابق لمقتطف BBC بسبع كلمات فأكثر ← لا رفض نسخ (هو المعلومة الصحيحة)
    bbc = clean(important_fixture_point(1229, "inaccurate", 1))
    shared = [s for s in bbc["correction"]["sources"] if s["publisher"] == "BBC"][0]["excerpt"]
    from src import important_write
    cw, sw = important_write._norm(bbc["correction"]["correct"]).split(), important_write._norm(shared)
    check("(g48) fixture: تصحيح 04ae7eae0358 يطابق مقتطف BBC بسبع كلمات متتالية فأكثر",
          bbc["id"] == "04ae7eae0358"
          and any(" ".join(cw[i:i + 7]) in sw for i in range(len(cw) - 6)), (cw, sw))
    rig, _code, saved, draft = run(48, bbc, important_good_data(bbc))
    accepted("g48", rig, saved, draft)
    check("(g48) لا رفض نسخ لفظي (محاولة واحدة)", len(rig.calls) == 1 and not saved.get("write_error"),
          (len(rig.calls), saved.get("write_error")))
    # ضابطة g48: نسخ تتابع آخر من BBC ليس هو التصحيح يبقى مرفوضًا
    good = important_good_data(bbc)
    copied = {**good, "post_body": good["post_body"] + " ويوجد حاليا على بعد نحو 1.6 مليون كيلومتر من الأرض."}
    rig, _code, saved, draft = run(148, bbc, copied)
    rejected("g48", rig, saved, draft, "نسخ لفظي")

    # ── Issue #1233: g50–g51 تُكتبان قبل أي كود ──
    # g50) inaccurate وfalse: العنوان الافتراضي (post_title وأول عنوان في headlines) وسطر العنوان في
    # النص جمل خبرية — لا «؟» تُلحق بجملة خبرية (شاهد 602ac9017f8e) ولا سؤال حقيقي
    from src import headlines as headlines_mod
    for case, point in ((50, important_fixture_point(1201, "inaccurate")),
                        (150, important_synthetic_point("false"))):
        good = important_good_data(point)
        verdict = point["verdict"]
        appended = {**good, "post_title": good["post_title"] + "؟",
                    "image_headline": good["image_headline"] + "؟"}
        rig, _code, saved, draft = run(case, point, appended)
        accepted(f"g50/{verdict}", rig, saved, draft)
        if draft:
            d = draft[1]
            check(f"(g50/{verdict}) جملة خبرية أُلحقت بها «؟» ← تُنزَع: العنوان الافتراضي وسطر العنوان بلا «؟»",
                  not d["arabic"]["post_title"].rstrip().endswith(("؟", "?"))
                  and not d["arabic"]["image_headline"].rstrip().endswith(("؟", "?"))
                  and d["arabic"]["post_title"] == good["post_title"], d["arabic"]["post_title"])
            check(f"(g50/{verdict}) وأول عنوان في headlines ليس سؤالًا (قاعدة السؤال لا تسري على هذا الحكم)",
                  d["headlines"] and not d["headlines"][0].rstrip().endswith(("؟", "?")), d["headlines"])
        real_q = {**good, "post_title": "هل " + good["post_title"] + "؟"}
        rig, _code, saved, draft = run(case + 1, point, real_q)
        rejected(f"g50/{verdict}", rig, saved, draft, "العنوان سؤال")
        q_body = {**good, "post_body": "هل " + good["post_body"].split(".")[0] + "؟ " + good["post_body"]}
        rig, _code, saved, draft = run(case + 2, point, q_body)
        rejected(f"g50/{verdict}", rig, saved, draft, "العنوان سؤال")

    # g50) على المولِّد الحقيقي: بمعامل first_question=False يُقبل أول عنوان خبري ويُرفض السؤال،
    # والافتراضي (الأخبار وغيرها) على حاله: أول عنوان سؤال إلزامي
    import types

    def fake_client(rows):
        def create(**kw):
            return types.SimpleNamespace(content=[types.SimpleNamespace(
                type="tool_use", input={"headlines": next(rows)})])
        return types.SimpleNamespace(messages=types.SimpleNamespace(create=create))

    stmt = ["المجرة الأبعد هي MoM-z14", "رقم قياسي جديد لمجرة MoM-z14", "MoM-z14 تزيح JADES عن الصدارة"]
    ques = ["هل MoM-z14 الأبعد؟"] + stmt[1:]
    got, err = headlines_mod.propose_headlines("x", cfg, "headlines", first_question=False,
                                                client=fake_client(iter([stmt])))
    check("(g50) first_question=False: عناوين خبرية تُقبل", got == stmt and not err, (got, err))
    got, err = headlines_mod.propose_headlines("x", cfg, "headlines", first_question=False,
                                                client=fake_client(iter([ques, ques])))
    check("(g50) first_question=False: أول عنوان سؤال يُرفض", got is None and err, (got, err))
    got, err = headlines_mod.propose_headlines("x", cfg, "headlines", client=fake_client(iter([stmt, stmt])))
    check("(g50) الافتراضي بلا تغيير: أول عنوان خبري يُرفض (قاعدة السؤال)", got is None and err, (got, err))
    got, err = headlines_mod.propose_headlines("x", cfg, "headlines", client=fake_client(iter([ques])))
    check("(g50) الافتراضي بلا تغيير: أول عنوان سؤال يُقبل", got == ques and not err, (got, err))

    # g51) جملة بلا سند في الأدلة ← تنبيه في warnings وفي قسم قضية المرحلة 2، والمسودة تُنشأ (لا رفض)
    unsourced_sentence = "وكانت لحظة الإطلاق قد تمت في موعدها المحدد."
    point = important_fixture_point(1201, "inaccurate")
    good = important_good_data(point)
    flagged = {**good, "post_body": good["post_body"] + " " + unsourced_sentence}
    rig, _code, saved, draft = run(51, point, flagged)
    accepted("g51", rig, saved, draft)
    if draft:
        d = draft[1]
        check("(g51) الجملة بلا السند في draft['warnings']",
              any("تمت في موعدها المحدد" in w for w in d.get("warnings") or []), d.get("warnings"))
        check("(g51) وهي في قسم «⚠️ تنبيهات للمراجعة» بقضية المرحلة 2 بالجملة نفسها",
              rig.created and "⚠️ تنبيهات للمراجعة" in rig.created[0]["body"]
              and "تمت في موعدها المحدد" in rig.created[0]["body"], [c["body"][:300] for c in rig.created])
        check("(g51) والتنبيه لا يدخل النص المنشور (caption/post_body)",
              "تنبيهات للمراجعة" not in d["caption"] and "تنبيهات" not in d["arabic"]["post_body"], d["caption"][-200:])
    sourced = {**good, "post_body": f"{point['correction']['correct']}. أما الرقم المتداول فخطأ شائع."}
    rig, _code, saved, draft = run(151, point, sourced)
    accepted("g51", rig, saved, draft)
    check("(g51) ضابطة: النص السليم بلا تنبيهات ولا قسم تنبيهات في القضية",
          draft is not None and not draft[1].get("warnings")
          and all("⚠️ تنبيهات للمراجعة" not in c["body"] for c in rig.created),
          (draft and draft[1].get("warnings")))
    for n in (36, 37, 38, 39, 40, 41, 47, 147, 247, 347, 447, 48, 148, 50, 51, 52, 150, 151, 152, 153):
        important.saved_path(96000 + n).unlink(missing_ok=True)


def test_names_audit_guards() -> None:
    """حارس تدقيق أسماء الأشخاص (Issue #1252، g52–g56) — يعدّل نصًّا منشورًا آليًا، فتُكتب حالاته
    قبل الكود. الكشف (Haiku) وطلب Brave مزيَّفان؛ الاستقلال والعدّاد والمعتمد المحفوظ يجري على
    الكود الحقيقي. القاعدة: لا تصحيح إلا برسم يظهر حرفيًا في نطاقين عربيين مستقلين."""
    import json

    from src import names_audit

    cfg = load_config()
    wrong, right = "فريدة المسلمي", "فارع المسلمي"
    two = [names_audit_hit("https://www.aljazeera.net/a", right),
           names_audit_hit("https://www.alaraby.co.uk/b", right)]

    def fields(d: dict) -> str:
        return " ".join([d["caption"], d["arabic"]["analysis"], d["arabic"]["post_title"],
                         d["arabic"]["image_headline"], *d["headlines"]])

    # g52) الاسم الخاطئ مع أصله اللاتيني في المصدر، والرسم المرشّح في نطاقين عربيين مستقلين
    d = names_audit_draft()
    with NamesAuditRig([names_audit_doubt()], {right: two}) as rig:
        report = names_audit.run(d, NAMES_AUDIT_SOURCE, cfg)
        saved = json.loads(names_audit.VERIFIED_FILE.read_text(encoding="utf-8"))
    check("g52: يُصحَّح الاسم في التعليق والتحليل والعنوان المقترح", wrong not in fields(d) and fields(d).count(right) == 3,
          fields(d))
    check("g52: يُحفظ في names_verified بأصله اللاتيني ومصدريه وتاريخه",
          any(e["arabic"] == right and e["latin"] == "Farea al-Muslimi" and len(e["sources"]) == 2 and e["at"]
              for e in saved["entries"].values()), saved)
    check("g52: التقرير يحمل التصحيح بالنطاقين", len(report["corrections"]) == 1
          and report["corrections"][0]["from"] == wrong and report["corrections"][0]["to"] == right, report)
    check("g52: بلا تنبيه «لم يُحسم»", not d.get("warnings"), d.get("warnings"))
    check("g52: الحقول غير النصية لا تُمسّ", d["source"]["publisher"] == "Free Malaysia Today", d["source"])

    # g53) الرسم المرشّح في نطاق واحد فقط ← لا تغيير، وتنبيه
    d = names_audit_draft()
    before = fields(d)
    with NamesAuditRig([names_audit_doubt()], {right: two[:1]}) as rig:
        report = names_audit.run(d, NAMES_AUDIT_SOURCE, cfg)
        verified_exists = names_audit.VERIFIED_FILE.exists()
    check("g53: نطاق واحد لا يكفي — النص كما هو", fields(d) == before, fields(d))
    check("g53: تنبيه «اسم لم يُحسم» بالرسم والأصل اللاتيني",
          any(w.startswith(f"اسم لم يُحسم: {wrong} (Farea al-Muslimi) — ") for w in d.get("warnings", [])),
          d.get("warnings"))
    check("g53: لا يُحفظ شيء في names_verified", not verified_exists)

    # g54) اسم مشهور سليم ← لا نداء بحث ولا تغيير (والمشهور في معجم الأسماء لا يُدقَّق حتى لو شكّ الكاشف)
    d = names_audit_draft()
    d["arabic"]["analysis"] += " وقال ترامب إن أردوغان يتابع الأمر."
    before = fields(d)
    sound = [{"arabic": "ترامب", "latin": "Trump", "gender": "male", "verdict": "sound"},
             {"arabic": "أردوغان", "latin": "Erdogan", "gender": "male", "verdict": "sound"}]
    with NamesAuditRig(sound, {}) as rig:
        names_audit.run(d, ["Trump said Erdogan was watching."], cfg)
    check("g54: سليم ← لا طلب بحث ولا تغيير ولا تنبيه",
          rig.http_calls == [] and fields(d) == before and not d.get("warnings"), rig.http_calls)
    doubtful_famous = [{**sound[0], "verdict": "doubtful", "candidates": ["ترمب"], "reason": "x"}]
    with NamesAuditRig(doubtful_famous, {}) as rig:
        names_audit.run(d, ["Trump said Erdogan was watching."], cfg)
    check("g54: مشهور في names.aliases لا يُبحث عنه ولو شكّ الكاشف", rig.http_calls == [] and fields(d) == before,
          rig.http_calls)

    # g55) نتائج من موقعين على النطاق نفسه ← لا تُعدّ مستقلة
    d = names_audit_draft()
    before = fields(d)
    same = [names_audit_hit("https://www.aljazeera.net/a", right),
            names_audit_hit("https://mubasher.aljazeera.net/b", right)]
    with NamesAuditRig([names_audit_doubt()], {right: same}) as rig:
        names_audit.run(d, NAMES_AUDIT_SOURCE, cfg)
    check("g55: موقعان على نطاق واحد ← نطاق واحد مستقل: لا تغيير", fields(d) == before, fields(d))
    check("g55: وتنبيه بدل التصحيح", any("اسم لم يُحسم" in w for w in d.get("warnings", [])), d.get("warnings"))

    # g56) اسم محفوظ في names_verified ← يُستعمل بلا أي نداء Brave
    d = names_audit_draft()
    with NamesAuditRig([names_audit_doubt()], {right: two}) as rig:
        names_audit.save_verified({"entries": {"farea al muslimi": {
            "latin": "Farea al-Muslimi", "arabic": right, "sources": ["تصحيح المراجع"],
            "source_kind": "تصحيح المراجع", "at": "2026-10-05T00:00:00+00:00", "wrong": []}}})
        names_audit.run(d, NAMES_AUDIT_SOURCE, cfg)
    check("g56: المحفوظ يُستعمل مباشرة بلا طلب Brave", rig.http_calls == [] and wrong not in fields(d)
          and right in d["caption"], rig.http_calls)


def test_analysis_attribution_guards() -> None:
    """حارس النسبة والاقتباس في مقال التحليل (Issue #1272، g57–g61): كُتبت قبل الكود. الشاهد
    المنشور drafts/2026-10-07/fe2a7c6fc1a0: «بحسب ما عرضه مقدّم برنامج على الجزيرة» بلا اسم،
    واقتباس لترامب يصل جملتين بـ«...»، وقناة ILTV لا تُذكر. الحارس على الكود الحقيقي بلا نموذج."""
    from src import youtube_article as ya
    from src import youtube_publish

    cfg = load_config()
    filler = " ".join(["كلمة"] * 280)

    def article(extra: str) -> str:
        return f"# عنوان تجريبي لقضية ما؟\n\n{filler}\n\n{extra}\n"

    def bad(text: str, points=None) -> list:
        return ya.article_violations(text, cfg, points)

    # g57) النسبة إلى دور بلا اسم علم
    v = bad(article("وبحسب ما عرضه مقدّم برنامج على الجزيرة، فإن الأمر كذلك."))
    check("g57: «بحسب ما عرضه مقدّم برنامج…» ← رفض", len(v) == 1 and "بلا اسم" in v[0], v)
    v = bad(article("وبحسب ما عرضته قناة الجزيرة، فإن الأمر كذلك."))
    check("g57: «بحسب ما عرضته قناة الجزيرة» ← قبول", v == [], v)
    v = bad(article("مهدي مهدوي آزاد، مقدّم برنامج تحليلي على قناة إيران إنترناشيونال، يقول إن الأمر كذلك."))
    check("g57: متحدث مسمّى ثم صفته ← قبول", v == [], v)

    # g58) اقتباس يصل كلامين بـ«...»
    v = bad(article("وقال: «أعتقد أن إيران مسؤولة... نعتقد أن هناك تهديدًا»."))
    check("g58: «» يحوي «...» ← رفض", len(v) == 1 and "..." in v[0], v)

    # g59) قناة في النقاط غائبة عن المتن
    pts = [{"channel": "ILTV"}, {"channel": "الجزيرة"}]
    v = bad(article("وفي حديث لقناة الجزيرة قيل كذا."), pts)
    check("g59: ILTV غائبة عن المتن ← رفض بذكرها", len(v) == 1 and "ILTV" in v[0], v)
    v = bad(article("وفي حديث لقناة الجزيرة وقناة ILTV قيل كذا."), pts)
    check("g59: حضور القناتين ← قبول", v == [], v)

    # g60) اقتباس أطول من السقف
    long_quote = " ".join(["جملة"] * 30)
    v = bad(article(f"وقال خبير مسمّى: «{long_quote}»."))
    check("g60: اقتباس من 30 كلمة ← رفض", len(v) == 1 and "30" in v[0], v)
    ok_quote = " ".join(["جملة"] * 20)
    check("g60: اقتباس من 20 كلمة ← قبول", bad(article(f"وقال خبير مسمّى: «{ok_quote}».")) == [])

    # g61) «» بعد اسم شخصية عامة في الجملة نفسها ← قبول + تنبيه مراجعة لا يُنشر
    text = article("وقال الرئيس ترامب إن الأمر كما يلي: «هذا ما نراه اليوم». ثم انتهى الحديث.")
    check("g61: «» بعد «ترامب» ← قبول", bad(text) == [], bad(text))
    warns = ya.figure_quote_warnings(text, cfg)
    review = ya._append_warnings(text, warns)
    check("g61: التنبيه في نص المراجعة", "اقتباس مباشر منسوب لشخصية عامة" in review, review[-200:])
    published, _ = youtube_publish.split_warnings(review)
    check("g61: التنبيه غائب عن النص المنشور", "اقتباس مباشر" not in published, published[-200:])
    other = article("وقال خبير مسمّى: «هذا ما نراه اليوم». ثم انتهى الحديث.")
    check("g61: «» بلا اسم شخصية عامة ← لا تنبيه", ya.figure_quote_warnings(other, cfg) == [])

    # ── g62–g65: ذكر القناة بصيغها المقبولة (mention_forms، Issue #1272) ──
    def chan_bad(extra: str, channel: str) -> list:
        return [x for x in bad(article(extra), [{"channel": channel}]) if "غائبة" in x]

    v = chan_bad("وتحدّثت الدول العربية عن الأمر.", "العربية")
    check("g62: «العربية» وحدها في «الدول العربية» ← قناة غائبة (العربية)",
          len(v) == 1 and "(العربية)" in v[0], v)
    check("g62: «قناة العربية» ← لا مخالفة", chan_bad("وفق ما عرضته قناة العربية.", "العربية") == [])
    check("g63: «سي إن إن ترك» لقناة CNN Türk ← لا مخالفة",
          chan_bad("وفق ما عرضته قناة سي إن إن ترك.", "CNN Türk") == [])
    check("g64: «ايران انترناشيونال» بلا همزة ← لا مخالفة",
          chan_bad("وفق ما عرضته قناة ايران انترناشيونال.", "Iran International") == [])
    check("g65: «Haaretz» باللاتينية ← لا مخالفة", chan_bad("وفق ما نشرته Haaretz.", "Haaretz") == [])
    check("g65: لا ذكر لهآرتس ← مخالفة",
          len(chan_bad("وفق ما نشرته صحيفة.", "Haaretz")) == 1)

    # إعداد: كل mention_forms تحوي الاسم المعروض للقناة نفسها بعد الطيّ
    for ch in cfg.path("channels", []):
        forms = ch.get("mention_forms")
        if forms:
            shown = ya._fold_mention(ya.display_channel_name(ch["name"], cfg))
            # «قناة العربية» تحوي «العربية» ولا تساويها عمدًا: الاسم وحده يرد في «الدول العربية»
            check("إعداد: mention_forms لـ" + ch["name"] + " تحوي الاسم المعروض",
                  any(shown in ya._fold_mention(f) for f in forms), forms)
    check("إعداد: ILTV وAll Israel News بلا name_ar كما قُرِّر",
          all(ch.get("name_ar") is None for ch in cfg.path("channels", [])
              if ch["name"] in ("ILTV", "All Israel News")))


def test_analysis_attribution_pipeline() -> None:
    """Issue #1272 (الاختبارات a–d على مخرج الأنبوب)."""
    import json
    from pathlib import Path
    from src import youtube_article as ya

    cfg = load_config()
    real = Path(__file__).resolve().parent.parent / "drafts" / "2026-10-07" / "fe2a7c6fc1a0.json"
    published = json.loads(real.read_text(encoding="utf-8"))["caption"]

    # (a) النص المنشور الحقيقي مع قناتين ILTV والجزيرة ← المخالفات الثلاث
    v = ya.article_violations(published, cfg, [{"channel": "ILTV"}, {"channel": "الجزيرة"}])
    print("   (a) مخالفات النص المنشور fe2a7c6fc1a0:")
    for line in v:
        print("      -", line)
    check("(a) النسبة بلا اسم علم", any("بلا اسم علم" in x for x in v), v)
    check("(a) الوصل بـ«...»", any("..." in x and "اقتباس" in x for x in v), v)
    check("(a) غياب ILTV", any("ILTV" in x and "غائبة" in x for x in v), v)
    check("(a) المخالفات الثلاث المطلوبة + اقتباس طويل رابع حقيقي (45 كلمة)",
          len(v) == 4 and any("45 كلمة" in x for x in v), v)

    # (b) draft_article بعميل مزيَّف: ردّ يخالف g57 ثم ردّ سليم
    class _B:
        type = "text"

        def __init__(self, t):
            self.text = t

    class _R:
        stop_reason = "end_turn"
        usage = None

        def __init__(self, t):
            self.content = [_B(t)]

    class _M:
        def __init__(self, texts):
            self.texts, self.calls = list(texts), []

        def create(self, **kw):
            self.calls.append(kw)
            return _R(self.texts.pop(0))

    class _C:
        def __init__(self, texts):
            self.messages = _M(texts)

    filler = " ".join(["كلمة"] * 280)
    bad_text = "# عنوان لقضية ما؟\n\n" + filler + "\n\nوبحسب ما عرضه مقدّم برنامج على الجزيرة، فإن الأمر كذلك.\n"
    good_text = "# عنوان لقضية ما؟\n\n" + filler + "\n\nوبحسب ما عرضته قناة الجزيرة، فإن الأمر كذلك.\n"
    client = _C([bad_text, good_text])
    topic = {"title": "قضية", "agreement": "agreement"}
    out, reason = ya.draft_article(topic, [{"channel": "الجزيرة", "speaker": "س", "type": "fact"}],
                                   cfg, client=client)
    calls = client.messages.calls
    check("(b) الردّ السليم بعد المخالف يُقبَل", out == good_text.strip() and reason is None, reason)
    check("(b) نداءان فقط", len(calls) == 2, len(calls))
    last = calls[1]["messages"][-1]["content"]
    check("(b) النداء الثاني يحمل سبب الرفض",
          "رُفضت المحاولة السابقة لهذا السبب" in last and "بلا اسم علم" in last
          and "صحّحه دون تغيير ما سواه" in last, last)
    c2 = _C([bad_text] * 10)
    out2, _ = ya.draft_article(topic, [{"channel": "الجزيرة"}], cfg, client=c2)
    check("(b) عدد النداءات لا يتجاوز max_retries",
          out2 is None and len(c2.messages.calls) == cfg.path("youtube.article.max_retries", 3),
          len(c2.messages.calls))

    # (c) _points_block يعرض «القناة 14»
    block = ya._points_block([{"channel": "ערוץ 14", "bloc": "israeli", "speaker": "س"}], cfg)
    check("(c) _points_block يعرض «القناة 14» لا الاسم العبري",
          "القناة: القناة 14" in block and "ערוץ" not in block, block)

    # (d) مقال بلا عبارة ترجيح مقبول
    ok, why = ya._validate_article_text("# عنوان لقضية ما؟\n\n" + filler + "\n", cfg)
    check("(d) مقال بلا عبارة ترجيح ← مقبول", ok, why)


def test_important_1282_guards() -> None:
    """Issue #1282 (حادثة #1278): g66–g75 — ثلاثة أقسام «ما ثبت / ما كُذِّب / أقرب ما وُجد» ولا تسقط
    نقطة إلا بلا أثر إطلاقًا. تُكتب قبل الكود، على الدوال الحقيقية بالأدوات القائمة
    (ImportantRig وstrict_known=True) وبمقتطفات حقيقية من state/important/1278.json."""
    import copy
    from datetime import datetime, timezone

    from src import important, important_finalize, important_issue

    cfg = load_config()

    def run(case, points, docs_by_marker, classify):
        with ImportantRig(points, docs_by_marker, classify, strict_known=True):
            important.judge("نص الـIssue كاملًا", 97000 + case, cfg)
        return important.load_saved(97000 + case)["points"]

    def one(case, claim, docs, classify, entities=None, **pt_extra):
        marker = f"كلمةحارس{case}"
        pt = {"claim": claim, "entities": entities if entities is not None else [marker],
              "queries": [{"lang": "ar", "q": f"{marker} {claim}"}], **pt_extra}
        return run(case, [pt], {marker: docs}, classify)[0]

    def by_name(rules):
        def classify(point, names):
            rows = []
            for n in names:
                stance, excerpt, extra = rules.get(n, ("irrelevant", "", {}))
                rows.append(important_stance(n, stance, excerpt, **extra))
            return {"sources": rows}
        return classify

    # g66) 8e645204c867: ثلاثة مؤيِّدين خارج مصادرنا بمقتطفاتهم الحقيقية، بلا نفي ← confirmed + تنبيه
    c66 = "لن يتعافى حزب الله أبداً في ظل إدارة ترمب"
    ex66 = {
        "إرم نيوز": 'وقالت الخارجية الأمريكية في بيان صحفي إن "حزب الله لن يتعافى أبداً في ظل إدارة '
                    'الرئيس دونالد ترامب".',
        "Lebanon 24": 'وتابع "وفي ظل إدارة ترامب، لن يتمكّن «حزب الله» أبدًا من التعافي أو إعادة بناء '
                      'بنيته التحتية الإرهابية".',
        "LBCIV7": "الخارجية الأميركية: في ظل إدارة الرئيس ترامب لن يتمكن حزب الله من التعافي أو إعادة "
                  "بناء بنيته التحتية الإرهابية"}
    docs66 = [important_doc(n, t) for n, t in ex66.items()]
    p66 = one(66, c66, docs66, by_name({n: ("supports", t, {}) for n, t in ex66.items()}))
    warn = " ".join(p66.get("warnings") or [])
    # #1288: القديم confirmed بتنبيه الأسماء الثلاثة؛ الجديد not_found — الثلاثة خارج مصادرنا فتُستبعد
    check("(g66) ثلاثة مؤيِّدين من خارج مصادرنا بمقتطفات حرفية بلا نفي ⇒ not_found (مستبعدون)",
          p66["verdict"] == "not_found" and p66["outside_docs"] == 3, (p66["verdict"], p66.get("note")))
    check("(g66) ولا تنبيه «من خارج مصادرنا المسجّلة» (أُلغي) ولا أدلة",
          not warn and not p66["evidence"], (warn, p66["evidence"]))
    check("(g66) الاقتباسات بين علامات التنصيص لا تجعلها نسخًا (ثلاث مجموعات مستقلة)",
          len(important._independent_groups(
              list(ex66), {d["name"]: d for d in docs66}, cfg, excerpts=ex66)) == 3, None)

    # g67) bd4e7be00831: نص واحد خارج التنصيص عند الأمناء نت وTarebhtoday وYemenfuture ← مجموعة واحدة
    ex67 = {
        "BBC": "تتعامل روسيا مع الحوثيين بوصفهم جزءًا من تحالفها الاستراتيجي مع إيران، ولا تجري "
                      "قنوات التعاون الأساسية بين موسكو والجماعة بمعزل عن طهران. ... ويمنح النفوذ الحوثي "
                      "عند الممرات البحرية روسيا وإيران قدرة على الضغط على الولايات المتحدة وحلفائها "
                      "ورفع كلفة تحركاتهم الإقليمية",
        "Reuters": "من الفيتو إلى الطائرات المسيّرة.. روسيا تتحول إلى شريك حرب للحوثيين ... تتعامل "
                       "روسيا مع الحوثيين بوصفهم جزءًا من تحالفها الاستراتيجي مع إيران",
        "CNN Arabic": "تتعامل روسيا مع الحوثيين بوصفهم جزءًا من تحالفها الاستراتيجي مع إيران، ولا تجري "
                       "قنوات التعاون الأساسية بين موسكو والجماعة بمعزل عن طهران. ... ويمنح النفوذ الحوثي "
                       "عند الممرات البحرية روسيا وإيران قدرة على الضغط على الولايات المتحدة وحلفائها"}
    docs67 = [important_doc(n, t) for n, t in ex67.items()]
    p67 = one(67, "روسيا تتدخل عبر إيران بدعم ميليشيات الحوثي لتعطيل الملاحة", docs67,
              by_name({n: ("supports", t, {}) for n, t in ex67.items()}))
    # #1288: القديم not_found بـsingle_source؛ الجديد confirmed بـsupport_level == single (مجموعة مستقلة
    # واحدة من مصادرنا تكفي، والنسبة صريحة). الناشرون صاروا معروفين كي تبقى قاعدة النسخ هي المختبَرة
    check("(g67) نص واحد عند ثلاثة مصادر معروفة ⇒ مجموعة واحدة ⇒ confirmed بـsingle",
          p67["verdict"] == "confirmed" and p67["support_level"] == "single",
          (p67["verdict"], p67.get("support_level")))

    # g68) fixture 9185665f38b8 (Fatabyyano «خبر كاذب» + مواقع تعيد نشر الشائعة) ← false
    fx = important_fixture_point(1229, "confirmed")
    by_pub = {e["publisher"]: e for e in fx["evidence"]}
    other_event = {x["publisher"] for x in fx["read_docs"] if x["stance"] == "related_other"}
    docs68, st68 = [], {}
    for d in fx["read_docs"]:
        if d["stance"] == "deduped":
            continue
        ev = by_pub.get(d["publisher"])
        text = (ev["excerpt"] if ev else f"{d['publisher']}: نص لا صلة له بالادّعاء.") + " " + d["publisher"]
        docs68.append(important_doc(d["publisher"], text, link=d["link"]))
        if ev and d["stance"] in ("supports", "refutes"):
            st68[d["publisher"]] = (d["stance"], ev["excerpt"])
        elif d["stance"] == "related_other":
            st68[d["publisher"]] = ("supports", "")

    def classify68(point, names):
        return {"sources": [important_stance(n, *st68.get(n, ("irrelevant", "")),
                                             same_event=n not in other_event, verdict_label="")
                            for n in names]}

    p68 = one(68, fx["claim"], docs68, classify68)
    refs = p68.get("refuted_by") or []
    check("(g68) 9185665f38b8 ← false (مدقّق بمقتطف «كاذب» صريح ولو بلغ التأييد عتبته)",
          fx["id"] == "9185665f38b8" and p68["verdict"] == "false", (p68["verdict"], p68.get("note")))
    check("(g68) وrefuted_by فيه Fatabyyano بمقتطف «خبر كاذب»",
          any(r["publisher"] == "Fatabyyano" and "خبر كاذب" in r["excerpt"] for r in refs), refs)

    # g69) مدقّق بمقتطف «لم تقع الحادثة» (بلا كلمة صريحة ولا label) + مؤيِّدان ← أدلة متعارضة
    event = "وقعت الحادثة الكبرى في المدينة بحسب التقارير المتداولة."
    sup = ("supports", "وقعت الحادثة الكبرى في المدينة", {})
    two = [important_doc("Reuters", event),
           important_doc("BBC", "تغطية مستقلة: " + event)]
    fact = important_doc("Fatabyyano", "ادّعاء مضلّل لم تقع الحادثة أصلًا.",
                         link="https://fatabyyano.net/en/x/")
    p69 = one(69, "وقعت الحادثة كلمةحارس69 في المدينة", two + [fact],
              by_name({"Reuters": sup, "BBC": sup,
                       "Fatabyyano": ("refutes", "لم تقع الحادثة", {"verdict_label": ""})}))
    check("(g69) مدقّق بمقتطف بلا كلمة صريحة ولا label + مؤيِّدان ⇒ not_found «أدلة متعارضة» (سلوك g44)",
          p69["verdict"] == "not_found" and "أدلة متعارضة" in (p69.get("note") or ""),
          (p69["verdict"], p69.get("note")))

    # g70) مقتطف سؤالي «هل هذا خبر كاذب؟» ← ليس false
    q_text = "هل هذا خبر كاذب؟ يتحقق فريقنا من الادّعاء المتداول."
    p70 = one(70, "وقعت الحادثة كلمةحارس70 في المدينة",
              [important_doc("Fatabyyano", q_text, link="https://fatabyyano.net/en/y/")],
              by_name({"Fatabyyano": ("refutes", "هل هذا خبر كاذب؟", {"verdict_label": ""})}))
    check("(g70) مقتطف سؤالي «هل هذا خبر كاذب؟» من مدقّق ⇒ ليس false",
          p70["verdict"] != "false" and not p70.get("refuted_by"), (p70["verdict"], p70.get("note")))

    # g71) مدقّق بكلمة صريحة + مؤيِّد من primary_data_domains ← أدلة متعارضة (لا false)
    p71 = one(71, "بلغ عدد سكان البلد 85 مليون نسمة كلمةحارس71", [
        important_doc("البنك الدولي", "بلغ عدد سكان البلد 85 مليون نسمة في العام الأخير كلمةحارس71.",
                      link="https://data.worldbank.org/2026/10/05/indicator/SP.POP.TOTL"),
        important_doc("Fatabyyano", "الرقم المتداول كاذب كلمةحارس71.", link="https://fatabyyano.net/en/z/")],
        by_name({"البنك الدولي": ("supports", "بلغ عدد سكان البلد 85 مليون نسمة", {}),
                 "Fatabyyano": ("refutes", "الرقم المتداول كاذب", {"verdict_label": ""})}),
        numbers=["85 مليون"])
    check("(g71) مدقّق بكلمة صريحة + مؤيِّد من جهة البيانات الأصلية ⇒ not_found «أدلة متعارضة»",
          p71["verdict"] == "not_found" and "أدلة متعارضة" in (p71.get("note") or ""),
          (p71["verdict"], p71.get("note")))

    # g72) 24246e81cd44: BBC وYoum7 (تنقل عن BBC صراحة) ← مجموعة واحدة ← single_source، وتُكتب
    bbc = ("تُظهر البيانات أن روسيا واصلت جني مليارات الدولارات من صادرات الوقود الأحفوري إلى الغرب، "
           "ما ساعد في تمويل غزوها الشامل لأوكرانيا")
    youm = ("كشفت هيئة الإذاعة البريطانية BBC أن روسيا واصلت جنى مليارات الدولارات من صادرات الوقود "
            "الأحفورى إلى الغرب، بحسب ما أظهرت بيانات، مما ساعد موسكو فى تمويل عمليتها العسكرية فى أوكرانيا")
    claim72 = "روسيا تستخدم أموال بيع الغاز في تأمين تكاليف الحرب في أوكرانيا"
    p72 = one(72, claim72, [important_doc("BBC", bbc, link="https://www.bbc.com/arabic/articles/cwynvm70zvzo"),
                            important_doc("Youm7", youm, link="https://www.youm7.com/story/2025/5/30/x")],
              by_name({"BBC": ("supports", bbc, {}), "Youm7": ("supports", youm, {})}))
    near = p72.get("nearest") or {}
    # #1288: القديم not_found بـsingle_source؛ الجديد confirmed بـsingle (Youm7 خارج مصادرنا فتُستبعد وتبقى BBC)
    check("(g72) BBC وYoum7 ⇒ Youm7 مستبعدة وBBC وحدها ⇒ confirmed بـsingle ناشره BBC",
          p72["verdict"] == "confirmed" and p72["support_level"] == "single"
          and p72["support_publisher"] == "BBC" and p72["outside_docs"] == 1,
          (p72["verdict"], p72.get("support_level"), near))
    sel = 97500
    p72 = copy.deepcopy(p72)
    p72["selection_issue"] = sel
    result = {"issue": 97072, "created_at": datetime.now(timezone.utc).isoformat(), "topic": "",
              "error": None, "selection_issue": sel, "points": [p72]}
    important.save(result)
    body = important_marked_body(result, {p72["id"]: "go2"}, cfg)
    data = {"category": "اقتصاد", "hashtags": ["روسيا"], "image_query_en": "oil gas russia",
            "post_title": "عوائد الوقود الأحفوري تواصل تمويل الحرب في أوكرانيا بحسب بي بي سي",
            "image_headline": "عوائد الوقود الأحفوري تموّل الحرب في أوكرانيا",
            "post_body": "بحسب BBC، ظلّت موسكو تحصّل عوائد ضخمة من بيع الوقود إلى الغرب، وبحسبها "
                         "أسهم ذلك في تغطية نفقات العمليات العسكرية في أوكرانيا."}
    with ImportantWriteRig(lambda prompt, system: data) as rig:
        important_finalize.finalize(sel, body, cfg)
    saved = important.load_saved(97072)["points"][0]
    check("(g72) write_point يكتبها بلا خطأ «لا وقائع مسندة»",
          saved.get("status") == "written" and "لا وقائع مسندة" not in (saved.get("write_error") or ""),
          (saved.get("status"), saved.get("write_error")))
    check("(g72) وتعليمات الكاتب فيها confirmed_single (نسبة إلى BBC وحده)",
          any("أوردها BBC وحده" in c["prompt"] for c in rig.calls), [c["prompt"][:80] for c in rig.calls])

    # g73) nearest_events بحدث من مصدر واحد بكيان مشترك ← single_source؛ وضابطتها ← dropped
    marker73 = "كلمةحارس73"
    ev_doc = important_doc("Reuters", f"أعلنت شركة الطاقة عن اتفاق جديد لتوريد الغاز يخص {marker73} هذا الأسبوع.")
    rel = {"Reuters": ("related_other", "", {"same_event": False})}

    def classify73(point, names):
        out = by_name(rel)(point, names)
        out["nearest_events"] = [{"title": f"اتفاق توريد غاز جديد في {marker73}",
                                  "description": "اتفاق جديد لتوريد الغاز.", "sources": ["Reuters"]}]
        return out

    p73 = one(73, f"ادّعاء لا يطابق أي حدث {marker73}", [ev_doc], classify73)
    check("(g73) حدث أقرب من مصدر واحد بكيان مشترك ⇒ single_source ولا يسقط",
          p73["verdict"] == "not_found" and (p73.get("nearest") or {}).get("kind") == "single_source"
          and not p73.get("dropped_reason") and p73["nearest"]["sources"][0].get("excerpt"),
          (p73["verdict"], p73.get("nearest")))
    cold = important_doc("Reuters", "أعلنت شركة الطاقة عن اتفاق جديد لتوريد الغاز هذا الأسبوع.")
    p73b = one(173, "ادّعاء لا يطابق أي حدث كلمةحارس173", [cold], by_name(rel))
    check("(g73) ضابطة: لا حدث ولا وثيقة تشارك كيانًا ⇒ dropped بـNO_TRACE_REASON",
          p73b["verdict"] == "not_found" and p73b.get("nearest") is None
          and p73b.get("dropped_reason") == important.NO_TRACE_REASON, (p73b.get("dropped_reason"),))

    # g74) نقطتان في نص واحد؛ الثانية بلا وثيقة من بحثها ووثيقة pool الأولى تؤيدها ← المخزون المشترك
    m1, m2 = "كلمةأولى74", "كلمةثانية74"
    shared_doc = important_doc("Reuters",
                               f"تؤكد المنصة أن الواقعة {m1} والواقعة {m2} حدثتا فعلًا هذا الشهر.")
    c74a, c74b = f"حدثت الواقعة {m1} هذا الشهر", f"حدثت الواقعة {m2} هذا الشهر"

    def classify74(point, names):
        return {"sources": [important_stance(n, "supports", f"الواقعة {m1 if m1 in point else m2} حدثتا فعلًا")
                            for n in names]}

    pts = [{"claim": c74a, "entities": [m1], "queries": [{"lang": "ar", "q": f"{m1} {c74a}"}]},
           {"claim": c74b, "entities": [m2], "queries": [{"lang": "ar", "q": f"{m2} {c74b}"}]}]
    out74 = run(74, pts, {m1: [shared_doc]}, classify74)
    second = [p for p in out74 if m2 in p["text"]][0]
    # #1288: القديم not_found بـsingle_source بعد المشاركة؛ الجديد confirmed بـsingle (مصدر واحد من مصادرنا يكفي)
    check("(g74) الثانية بلا وثيقة من بحثها ⇒ بعد المخزون المشترك لا تسقط، وshared_from فيه اسم الوثيقة",
          second["verdict"] == "confirmed" and second["support_level"] == "single"
          and not second.get("dropped_reason") and "Reuters" in (second.get("shared_from") or []),
          (second["verdict"], second.get("dropped_reason"), second.get("shared_from"), second.get("nearest")))

    # g75) confirm_blocked بنفي ← لا يظهر أي من مؤيِّديها في nearest.sources
    ev75 = "وقعت الحادثة الكبرى في المدينة بحسب التقارير المتداولة"
    docs75 = [important_doc("Reuters", ev75 + " كلمةحارس75."),
              important_doc("BBC", "تغطية مستقلة: " + ev75 + " كلمةحارس75."),
              important_doc("France24", "تؤكد المصادر أن الحادثة لم تقع إطلاقًا كلمةحارس75."),
              important_doc("CNN Arabic", "تقرير قريب عن كلمةحارس75 في المدينة نفسها.")]

    def classify75(point, names):
        out = by_name({"Reuters": sup, "BBC": sup,
                       "France24": ("refutes", "الحادثة لم تقع إطلاقًا", {"verdict_label": ""}),
                       "CNN Arabic": ("related_other", "", {"same_event": False})})(point, names)
        out["nearest_events"] = [{"title": "حدث كلمةحارس75 قريب", "description": "",
                                  "sources": ["Reuters", "BBC"]}]
        return out

    p75 = one(75, "وقعت الحادثة كلمةحارس75 في المدينة", docs75, classify75)
    named = [s["publisher"] for s in (p75.get("nearest") or {}).get("sources", [])]
    check("(g75) نقطة منعها نفيٌ ⇒ لا يظهر مؤيِّدوها في nearest.sources",
          p75["verdict"] == "not_found" and "Reuters" not in named
          and "BBC" not in named, (p75["verdict"], p75.get("nearest")))

    # عرض الأقسام الثلاثة في قضية الترشيح بترقيم متصل وعناوين من config
    sample = {"issue": 97099, "points": [
        {**important_synthetic_point("not_found")},
        {**important_synthetic_point("false")},
        {**important_fixture_point(1229, "inaccurate")}]}
    text = important_issue.build_selection_body(sample, cfg)
    titles = [cfg.path("important.section_titles.confirmed"), cfg.path("important.section_titles.false"),
              cfg.path("important.section_titles.not_found")]
    pos = [text.find(t) for t in titles]
    check("(g66+) الأقسام الثلاثة بعناوين config وبترتيب ما ثبت ثم ما كُذِّب ثم ما لم يُحسم",
          all(p >= 0 for p in pos) and pos == sorted(pos), pos)
    check("(g66+) الترقيم متصل عبر الأقسام", all(f"**{k}. " in text for k in (1, 2, 3)), text[:300])


def test_important_1288_guards() -> None:
    """Issue #1288: g76–g82 — مصادرنا وحدها، وموقع الجهة نفسها، والمصدر الواحد بنسبة صريحة. تُكتب قبل الكود
    وتجري على الحارس الحقيقي لـ«مصدرنا» (strict_known=True) وعلى الدوال الحقيقية."""
    import json

    from src import important, important_write
    from tests.helpers import IMPORTANT_FIXTURES

    cfg = load_config()

    def run(case, points, docs_by_marker, classify):
        with ImportantRig(points, docs_by_marker, classify, strict_known=True):
            important.judge("نص الـIssue كاملًا", 98000 + case, cfg)
        return important.load_saved(98000 + case)["points"]

    def one(case, claim, docs, classify, **pt_extra):
        marker = f"كلمةحارس{case}"
        text = claim.replace("@", marker)
        pt = {"claim": text, "entities": [marker], "queries": [{"lang": "ar", "q": text}], **pt_extra}
        return run(case, [pt], {marker: docs}, classify)[0]

    def by_name(rules):
        def classify(point, names):
            rows = []
            for n in names:
                stance, excerpt, extra = rules.get(n, ("irrelevant", "", {}))
                rows.append(important_stance(n, stance, excerpt, **extra))
            return {"sources": rows}
        return classify

    event = "وقعت الحادثة الكبرى في المدينة بحسب التقارير المتداولة"
    sup = ("supports", "وقعت الحادثة الكبرى في المدينة", {})

    # g76) مؤيِّدان من خارج مصادرنا وحدهما ← not_found، وevidence فارغ، وread_docs بموقف outside
    p76 = one(76, "وقعت الحادثة @ في المدينة",
              [important_doc("موقع الشرق الإخباري", event + "."),
               important_doc("منصة الغرب الرقمية", "تغطية مستقلة: " + event + ".")],
              by_name({"موقع الشرق الإخباري": sup, "منصة الغرب الرقمية": sup}))
    outside76 = [d for d in p76["read_docs"] if d["stance"] == "outside"]
    check("(g76) مؤيِّدان من خارج مصادرنا وحدهما ⇒ not_found",
          p76["verdict"] == "not_found", (p76["verdict"], p76.get("note")))
    check("(g76) وevidence فارغ، وread_docs بموقف outside للوثيقتين، وoutside_docs == 2",
          p76["evidence"] == [] and len(outside76) == 2 and p76["outside_docs"] == 2,
          (p76["evidence"], [d["stance"] for d in p76["read_docs"]], p76["outside_docs"]))

    # g77) BBC وحدها تؤيد ← confirmed بمصدر واحد، وتعليمات الكاتب فيها «بحسب BBC»
    p77 = one(77, "وقعت الحادثة @ في المدينة", [important_doc("BBC", event + ".")], by_name({"BBC": sup}))
    ins77 = important_write.instructions(p77, cfg)
    check("(g77) BBC وحدها تؤيد ⇒ confirmed وsupport_level == single",
          p77["verdict"] == "confirmed" and p77["support_level"] == "single",
          (p77["verdict"], p77.get("support_level")))
    check("(g77) وتعليمات الكاتب فيها «بحسب BBC»", "بحسب BBC" in ins77, ins77)

    # g78) BBC وReuters مستقلتان ← confirmed بـmulti
    p78 = one(78, "وقعت الحادثة @ في المدينة",
              [important_doc("BBC", event + "."), important_doc("Reuters", "تغطية مستقلة: " + event + ".")],
              by_name({"BBC": sup, "Reuters": sup}))
    check("(g78) BBC وReuters مستقلتان ⇒ confirmed وsupport_level == multi",
          p78["verdict"] == "confirmed" and p78["support_level"] == "multi",
          (p78["verdict"], p78.get("support_level")))

    # g79) وثيقة من state.gov تؤيد نقطة تنسب القول إلى وزارة الخارجية الأميركية ← primary
    stmt = "الولايات المتحدة ستفرض عقوبات جديدة على الأفراد المعنيين"
    p79 = one(79, f"وزارة الخارجية الأميركية تصرّح بأن {stmt} @",
              [important_doc("State Department", f"بيان رسمي: {stmt} كلمةحارس79.",
                             link="https://www.state.gov/releases/2026/10/05/x")],
              by_name({"State Department": ("supports", stmt, {})}))
    check("(g79) وثيقة state.gov تؤيد «وزارة الخارجية الأميركية تصرّح…» ⇒ confirmed وsupport_level == primary",
          p79["verdict"] == "confirmed" and p79["support_level"] == "primary",
          (p79["verdict"], p79.get("support_level"), p79.get("note")))

    # g80) موقع من خارج مصادرنا «ينفي» بكلمة صريحة ← لا أثر له؛ ومدقّق من مصادرنا بالكلمة نفسها ← false (كـg68)
    p80 = one(80, "وقعت الحادثة @ في المدينة",
              [important_doc("BBC", event + " كلمةحارس80."),
               important_doc("موقع النفي المجهول", "الرقم المتداول كاذب كلمةحارس80.")],
              by_name({"BBC": sup,
                       "موقع النفي المجهول": ("refutes", "الرقم المتداول كاذب", {"verdict_label": ""})}))
    check("(g80) موقع من خارج مصادرنا «ينفي» بكلمة صريحة ⇒ لا أثر له (confirmed بـBBC بلا refuted_by)",
          p80["verdict"] == "confirmed" and not p80.get("refuted_by") and p80["outside_docs"] == 1,
          (p80["verdict"], p80.get("refuted_by"), p80["outside_docs"]))
    p80b = one(180, "وقعت الحادثة @ في المدينة",
               [important_doc("Fatabyyano", "الرقم المتداول كاذب كلمةحارس180.",
                              link="https://fatabyyano.net/en/q/")],
               by_name({"Fatabyyano": ("refutes", "الرقم المتداول كاذب", {"verdict_label": ""})}))
    check("(g80) ومدقّق من مصادرنا بكلمة صريحة ⇒ false (سلوك g68 نفسه)",
          p80b["verdict"] == "false" and p80b["refuted_by"][0]["publisher"] == "Fatabyyano",
          (p80b["verdict"], p80b.get("note")))

    # g81) fixture 1278 القديم: 24246e81cd44 ← confirmed بـsingle، 8e645204c867 ← ليست confirmed
    fx = json.loads((IMPORTANT_FIXTURES / "1278.json").read_text(encoding="utf-8"))
    chosen = {p["id"]: p for p in fx["points"] if p["id"] in ("24246e81cd44", "8e645204c867")}
    ents = {"24246e81cd44": ["روسيا", "أوكرانيا"], "8e645204c867": ["حزب الله", "ترمب"]}
    rules, docs_by_marker, rig_points = {}, {}, []
    for i, (pid, p) in enumerate(chosen.items()):
        marker = f"نقطةg81{i}"
        by_pub = {e["publisher"]: e for e in p["evidence"]}
        docs, stance = [], {}
        for d in p["read_docs"]:
            if d["stance"] == "deduped":
                continue
            ev = by_pub.get(d["publisher"])
            docs.append(important_doc(d["publisher"],
                                      ev["excerpt"] if ev else f"{d['publisher']}: تقرير عن {ents[pid][-1]}.",
                                      link=d["link"]))
            stance[d["publisher"]] = (d["stance"], ev["excerpt"] if ev else "", d["same_event"] is not False)
        rules[p["claim"]] = stance
        docs_by_marker[marker] = docs
        rig_points.append({"claim": p["claim"], "entities": [marker, *ents[pid]],
                           "queries": [{"lang": "ar", "q": f"{marker} {p['claim']}"}]})

    def classify81(point, names):
        rows = []
        for n in names:
            kind, excerpt, same = rules[point].get(n, ("irrelevant", "", False))
            rows.append(important_stance(n, kind, excerpt, same_event=same, verdict_label=""))
        return {"sources": rows}

    with ImportantRig(rig_points, docs_by_marker, classify81, strict_known=True):
        important.judge("نص g81", 98081, cfg)
    by_id = {p["id"]: p for p in important.load_saved(98081)["points"]}
    check("(g81) 24246e81cd44: BBC تبقى وYoum7 تُستبعد ⇒ confirmed وsupport_level == single",
          by_id["24246e81cd44"]["verdict"] == "confirmed"
          and by_id["24246e81cd44"]["support_level"] == "single",
          (by_id["24246e81cd44"]["verdict"], by_id["24246e81cd44"].get("support_level")))
    check("(g81) 8e645204c867: مؤيِّدها LBCIV7 صارت وسيلة لبنانية من مصادرنا (#1345) ⇒ confirmed",
          by_id["8e645204c867"]["verdict"] == "confirmed", by_id["8e645204c867"]["verdict"])
    # بديل يحفظ غرض #1288: مؤيِّدو النقطة من lebanon24.com وeremnews.com وalmanar.com.lb وحدها ⇒ ليست confirmed
    # وموقفهم "outside" (الإعلام الحزبي والمواقع غير المسجَّلة تبقى خارج مصادرنا)
    alt_marker = "نقطةg81"
    pid8 = "8e645204c867"
    p8 = chosen[pid8]
    alt_docs, alt_stance = [], {}
    for d in p8["read_docs"]:
        if d["publisher"] in ("إرم نيوز", "Lebanon 24"):
            ev = {e["publisher"]: e for e in p8["evidence"]}[d["publisher"]]
            alt_docs.append(important_doc(d["publisher"], ev["excerpt"], link=d["link"]))
            alt_stance[d["publisher"]] = ("supports", ev["excerpt"], True)
    first_ev = next(e for e in p8["evidence"] if e["publisher"] == "إرم نيوز")
    alt_docs.append(important_doc("المنار", first_ev["excerpt"], link="https://www.almanar.com.lb/2026/10/07/x"))
    alt_stance["المنار"] = ("supports", first_ev["excerpt"], True)

    def classify81b(point, names):
        rows = []
        for n in names:
            kind, excerpt, same = alt_stance.get(n, ("irrelevant", "", False))
            rows.append(important_stance(n, kind, excerpt, same_event=same, verdict_label=""))
        return {"sources": rows}
    with ImportantRig([{"claim": p8["claim"], "entities": [alt_marker, "حزب الله", "ترمب"],
                        "queries": [{"lang": "ar", "q": f"{alt_marker} {p8['claim']}"}]}],
                      {alt_marker: alt_docs}, classify81b, strict_known=True):
        important.judge("نص g81 البديل", 98181, cfg)
    alt = important.load_saved(98181)["points"][0]
    stances = {d["publisher"]: d["stance"] for d in alt["read_docs"]}
    check("(g81) بديل #1288: مؤيِّدو lebanon24 وeremnews وalmanar وحدها ⇒ ليست confirmed",
          alt["verdict"] != "confirmed", alt["verdict"])
    check("(g81) بديل #1288: موقف الثلاثة outside",
          all(stances.get(n) == "outside" for n in ("إرم نيوز", "Lebanon 24", "المنار")), stances)

    # g82) نقطة نصها «الخارجية الأميركية» ← site_queries فيها عبارة site:state.gov
    p82 = one(82, "الخارجية الأميركية أعلنت عن @ في المدينة",
              [important_doc("BBC", event + " كلمةحارس82.")], by_name({"BBC": sup}))
    check("(g82) نقطة فيها «الخارجية الأميركية» ⇒ site_queries فيها عبارة site:state.gov",
          any("site:state.gov" in q for q in p82["site_queries"]), p82["site_queries"])


def test_important_1291_guards() -> None:
    """Issue #1291 (B1): g83–g87 — تصحيح بمصدر قديم، تنظيف نصوص القوائم، نسبة الأحكام إلى الوسائل،
    خطة المنشورات الثلاثة، والخبر الرئيسي. حالات g83/g84 من ملف 1278b الحقيقي (نسخة state/important/1278.json)."""
    import json
    from datetime import date
    from pathlib import Path

    from src import important, important_issue, important_write

    cfg = load_config()
    icfg = cfg.get("important", {}) or {}
    fx = json.loads((Path(__file__).parent / "fixtures" / "important" / "1278b.json").read_text(encoding="utf-8"))
    by_id = {p["id"][:6]: p for p in fx["points"]}

    # g83) 146b90: مقتطف state.gov الحقيقي بتاريخ 20 آذار/مارس 2026 لا يصحّح تصريحًا من أكتوبر 2026
    p146 = by_id["146b90"]
    src = p146["correction"]["sources"][0]
    name = src["publisher"]
    doc = {"name": name, "link": src["link"], "text": src["excerpt"], "from_text": True}
    pool = {name: doc}
    f146 = {"text": p146["text"], "dates": [], "entities": ["الخارجية الأميركية", "حزب الله"],
            "framing": "circulating"}
    today = date(2026, 10, 8)

    def verdict_for(as_of):
        data = {"sources": [important_stance(name, "conflicts_detail", src["excerpt"],
                                             detail=p146["correction"]["error"],
                                             correct_form=p146["correction"]["correct"],
                                             as_of=as_of, detail_kind="other")]}
        stances = important._read_stances(data, pool, f146, icfg, now=today)
        return stances, important.decide(stances, pool, cfg, f146)

    st, dec = verdict_for("20 آذار/مارس 2026")
    check("(g83) تصحيح تصريح بمصدر عمره ~200 يوم ⇒ ليست inaccurate",
          dec["verdict"] != "inaccurate", dec["verdict"])
    check("(g83) state.gov ليس في correction والموقف related_other",
          not dec.get("correction") and st[name]["stance"] == "related_other", (dec.get("correction"), st[name]))
    st2, dec2 = verdict_for("5 تشرين الأول/أكتوبر 2026")
    check("(g83) ضابطة: المقتطف نفسه بـas_of «5 تشرين الأول/أكتوبر 2026» ⇒ inaccurate كما الآن",
          dec2["verdict"] == "inaccurate" and dec2["correction"]
          and dec2["correction"]["sources"][0]["publisher"] == name, dec2)
    st3, dec3 = verdict_for("")
    check("(g83) ضابطة: تاريخ مجهول ⇒ السلوك السابق (inaccurate)", dec3["verdict"] == "inaccurate", dec3["verdict"])

    # g84) 577c16: عنوان nearest الحقيقي بنصوص القوائم ينظَّف إلى عنوان الخبر
    dirty = by_id["577c16"]["nearest"]["title"]
    clean = important.clean_page_text(dirty, icfg)
    check("(g84) clean_page_text على عنوان 577c16 الحقيقي ⇒ «فرض عقوبات على شبكة عالمية تدعم تمويل حزب الله»",
          clean == "فرض عقوبات على شبكة عالمية تدعم تمويل حزب الله", clean)
    ex = by_id["577c16"]["nearest"]["sources"][0]["excerpt"]
    cex = important.select_excerpt(ex, {"entities": []}, icfg)
    check("(g84) مقتطف 577c16 لا يبدأ بنصوص القوائم",
          cex.startswith("فرض عقوبات") and "hide" not in cex[:120], cex[:120])
    check("(g84) جملة عادية في وسط النص تحوي «Menu» لا تُمسّ",
          important.clean_page_text("خبر أول\nطلبت Menu جديدة", icfg) == "خبر أول\nطلبت Menu جديدة", None)

    # g85) الوسيلة ناقلة لا حَكَم
    def viol(t):
        return important_write.outlet_judgment_violations(t, cfg)

    check("(g85) «وتعدّ BBC وDW الحزب ركيزة…» ⇒ مخالفة",
          len(viol("وتعدّ BBC وDW الحزب ركيزة أساسية في الاستراتيجية الإيرانية.")) == 1, None)
    check("(g85) «الجزيرة تعتبر أن…» ⇒ مخالفة", len(viol("الجزيرة تعتبر أن…")) == 1, None)
    check("(g85) «أفادت BBC بأن الحزب دخل الحرب في 2 مارس.» ⇒ لا مخالفة",
          viol("أفادت BBC بأن الحزب دخل الحرب في 2 مارس.") == [], None)
    check("(g85) «قال المتحدث تومي بيغوت إن الأموال غير موجودة.» ⇒ لا مخالفة",
          viol("قال المتحدث تومي بيغوت إن الأموال غير موجودة.") == [], None)
    v = viol("الجزيرة تعتبر أن الحزب ضعيف.")[0]
    check("(g85) نص المخالفة يحمل الجملة",
          v.startswith("حكم منسوب إلى وسيلة إعلام (") and "انسبه إلى قائله" in v, v)
    pt = {"verdict": "confirmed", "claim": "س", "text": "س"}
    got = important_write.check_text(pt, {"post_title": "عنوان", "post_body": "تعتبر رويترز أن الحزب ضعيف."}, cfg)
    check("(g85) check_text يرفض الحكم المنسوب إلى وسيلة", (got or "").startswith("حكم منسوب"), got)
    note = icfg["writer_instructions"]["attribution_note"]
    check("(g85) attribution_note تدخل تعليمات كل حكم",
          all(note in important_write.instructions(
              {"verdict": vd, "claim": "س", "text": "س", "correction": {"correct": "ص"},
               "refuted_by": [{"publisher": "ف", "verdict_label": ""}], "nearest": {"title": "ع"}}, cfg)
              for vd in ("confirmed", "inaccurate", "false", "not_found")), None)

    # g86) خطة المنشورات الثلاثة
    def mk(verdict, n=0, **k):
        return {"id": f"{verdict}{n}", "verdict": verdict, **k}

    pts = ([mk("confirmed", i) for i in range(4)] + [mk("not_found", i) for i in range(3)]
           + [mk("false", i) for i in range(2)] + [mk("inaccurate")]
           + [mk("not_found", 9, call_error=True)]
           + [mk("confirmed", 8, about_main=False), mk("false", 8, about_main=False)])
    on, off = important.split_off_topic(pts)
    plan = important.plan_articles(on)
    check("(g86) verified 4 · nearest 3 · refuted 3 · off_topic 2 (وcall_error خارج القوائم)",
          (len(plan["verified"]), len(plan["nearest"]), len(plan["refuted"]), len(off)) == (4, 3, 3, 2)
          and "not_found9" not in sum(plan.values(), []), plan)
    check("(g86) plan_articles تتجاهل about_main=false بنفسها", important.plan_articles(pts) == plan, None)

    # g87) الخبر الرئيسي: نقطتان خارجه لا بحث ولا تصنيف لهما
    def rig_run(case, main_story):
        pts_ = [{"claim": f"واقعة رئيسية {i} كلمةرئيسية{case}", "entities": [f"كلمةرئيسية{case}"],
                 "queries": [{"lang": "ar", "q": f"كلمةرئيسية{case} {i}"}], "about_main": True}
                for i in range(2)]
        pts_ += [{"claim": f"موضوع آخر {i} كلمةجانبية{case}", "entities": [f"كلمةجانبية{case}"],
                  "queries": [{"lang": "ar", "q": f"كلمةجانبية{case} {i}"}], "about_main": False}
                 for i in range(2)]
        docs = {f"كلمةرئيسية{case}": [important_doc("BBC", f"نص عن كلمةرئيسية{case}")],
                f"كلمةجانبية{case}": [important_doc("Reuters", f"نص عن كلمةجانبية{case}")]}

        def classify(point, names):
            return {"sources": [important_stance(n, "supports", "نص عن") for n in names]}
        with ImportantRig(pts_, docs, classify, main_story=main_story) as rig:
            important.judge("نص", 98700 + case, cfg)
        return rig, important.load_saved(98700 + case)

    rig, res = rig_run(1, "الولايات المتحدة تواصل الضغط على حزب الله مالياً")
    check("(g87) لا بحث عن النقطتين الخارجتين ولا نداء تصنيف لهما",
          not any("كلمةجانبية1" in q for q in rig.queries)
          and rig.calls.count("classify_sources") <= 2, (rig.queries, rig.calls))
    check("(g87) النقطتان في off_topic ولا في points",
          len(res["off_topic"]) == 2 and len(res["points"]) == 2
          and all("موضوع آخر" in o["text"] for o in res["off_topic"]), res["off_topic"])
    check("(g87) main_story وarticles محفوظان",
          res["main_story"].startswith("الولايات المتحدة")
          and set(res["articles"]) == {"verified", "nearest", "refuted"}, res.get("articles"))
    body = important_issue.build_selection_body(res, cfg)
    check("(g87) القضية: سطر «📌 الخبر الرئيسي» وكتلة «خارج الموضوع الرئيسي (2)»",
          "📌 الخبر الرئيسي: الولايات المتحدة تواصل" in body
          and "<summary>خارج الموضوع الرئيسي (2)</summary>" in body and "موضوع آخر 0" in body, body[:400])
    rig2, res2 = rig_run(2, "")
    check("(g87) ضابطة: main_story فارغ ⇒ كل النقاط تُحكم ولا off_topic",
          len(res2["points"]) == 4 and res2["off_topic"] == []
          and any("كلمةجانبية2" in q for q in rig2.queries), (len(res2["points"]), res2["off_topic"]))
    # #1309: رُفع rules_version إلى 5 بحارس التصحيح بلا تفصيل في النقطة
    check("(g87) rules_version 7", res["rules_version"] == 7, res["rules_version"])


def _b2_body(words: int, tag: str = "", extra: str = "") -> str:
    """متن مزيَّف بعدد كلمات معلوم وكلمات فريدة (لا تتابع مشترك مع المصادر فيمرّ فحص الأصالة)."""
    sentences = []
    n = 0
    k = 0
    while n < words:
        sentences.append(f"الفقرة{tag}{k} تتناول جانبًا{k} مختلفًا{tag}{k} من القصة{k}.")
        n += 5
        k += 1
    return " ".join(sentences) + (" " + extra if extra else "")


def test_important_1293_guards() -> None:
    """Issue #1293 (B2): g88–g94 — ثلاثة منشورات حول الخبر الرئيسي: قضية الترشيح وعناصرها، شروط الظهور،
    البحث المكمِّل ومصادرنا وسقوف Brave، الكتابة وفحوصها، الترتيب وsibling_texts، go1 وإعادة الاستعمال،
    وتوافق القضية القديمة (علامات النقاط)."""
    import json
    import re
    import sys

    from src import cards, imagesearch, important, important_finalize, important_gap, important_issue, \
        important_write, publish
    from tests.helpers import (IMPORTANT_FIXTURES, important_b2_result, important_items_marked_body,
                               tick_marker)

    cfg = load_config()
    icfg = cfg.get("important", {}) or {}
    kind_order = ("verified", "nearest", "refuted")

    # ── g88) خطة {verified: 2، nearest: 2، refuted: 1} ← ثلاثة عناصر بثلاث كتل go: ولا علامة لنقطة منفردة ──
    result = important_b2_result(88000)
    items = result["article_items"]
    body = important_issue.build_selection_body(result, cfg)
    go_ids = re.findall(r"<!-- go:(?:go2|go3|publish):([0-9a-f]+) -->", body)
    check("(g88) ثلاثة عناصر بمعرّف point_id(issue:kind) وبترتيب verified ثم nearest ثم refuted",
          [i["kind"] for i in items] == list(kind_order)
          and [i["id"] for i in items] == [important.point_id(f"88000:{k}") for k in kind_order]
          and [len(i["point_ids"]) for i in items] == [2, 2, 1], items)
    check("(g88) القضية فيها ثلاث كتل go: (3 خيارات لكل عنصر) بمعرّفات العناصر وحدها",
          len(go_ids) == 9 and set(go_ids) == {i["id"] for i in items}, go_ids)
    check("(g88) لا علامة go: ولا imgurl لأي نقطة منفردة",
          not any(p["id"] in go_ids or f"imgurl:{p['id']}" in body for p in result["points"])
          and body.count("imgurl:") == 3, [p["id"] for p in result["points"]])
    titles = icfg["article_titles"]
    check("(g88) عناوين العناصر الثلاثة من الإعداد بترتيبها",
          all(titles[k] in body for k in kind_order)
          and body.index(titles["verified"]) < body.index(titles["nearest"]) < body.index(titles["refuted"]),
          body[:400])
    check("(g88) النقاط الأعضاء مسرودة تحت عناصرها (أيقونة ونص)",
          all(p["claim"] in body for p in result["points"] if p["verdict"] in ("confirmed", "false"))
          and "- ✅ " in body and "- ❌ " in body and "- 🔍 " in body
          and body.index(result["points"][0]["claim"]) < body.index(titles["nearest"]), body[:300])
    check("(g88) سطر الخبر الرئيسي والسطر الأخير «وسم approved = تنفيذ ما عُلِّم عليه لكل منشور»",
          "📌 الخبر الرئيسي: تطوّرات الخبر الرئيسي في الاختبار" in body
          and "وسم `approved` = تنفيذ ما عُلِّم عليه لكل منشور" in body.splitlines()[-1], body.splitlines()[-1])
    print("──── جسم قضية الترشيح بثلاثة منشورات (g88) ────")
    print(body)

    # ── g89) شروط الظهور ──
    def plan_result(issue, points):
        r = {"issue": issue, "main_story": "خبر", "off_topic": [], "points": points,
             "articles": important.plan_articles(points)}
        important.ensure_article_items(r)
        return r

    conf = important_fixture_point(1209, "confirmed", 0)
    fl = important_synthetic_point("false")
    text_nf = "قيل إن قوات دخلت مدينة المخا صباح اليوم"
    nf_bare = important_synthetic_point("not_found", id=important.point_id(text_nf), text=text_nf, claim=text_nf,
                                        nearest=None, status="dropped", dropped_reason=important.NO_TRACE_REASON)
    only_nf = plan_result(88001, [nf_bare])
    check("(g89) verified وrefuted فارغتان ← لا عنصر أول ولا ثالث، والثاني موجود ولو لنقطة بلا nearest",
          [i["kind"] for i in only_nf["article_items"]] == ["nearest"]
          and only_nf["article_items"][0]["point_ids"] == [nf_bare["id"]], only_nf["article_items"])
    no_ref = plan_result(88002, [conf, nf_bare])
    check("(g89) refuted فارغة ← لا عنصر ثالث",
          [i["kind"] for i in no_ref["article_items"]] == ["verified", "nearest"])
    no_ver = plan_result(88003, [fl, nf_bare])
    check("(g89) verified فارغة ← لا عنصر أول",
          [i["kind"] for i in no_ver["article_items"]] == ["nearest", "refuted"])
    ce = dict(nf_bare, id="ce" + "0" * 10, text="نقطة فشل نداؤها", claim="نقطة فشل نداؤها",
              call_error="انقطع النداء", dropped_reason=None, status="offered")
    with_err = plan_result(88004, [conf, ce])
    ebody = important_issue.build_selection_body(with_err, cfg)
    check("(g89) نقطة call_error لا تدخل منشورًا وتظهر في كتلة «نقاط لم تدخل أي منشور (1)» بسببها",
          [i["kind"] for i in with_err["article_items"]] == ["verified"]
          and "<summary>نقاط لم تدخل أي منشور (1)</summary>" in ebody
          and "- نقطة فشل نداؤها — انقطع النداء" in ebody, ebody[-500:])

    # ── g90) البحث المكمِّل: مصادرنا وحدها، وسقف Brave لكل منشور، والسقف الشهري ──
    imagesearch.BRAVE_USAGE_FILE.unlink(missing_ok=True)
    bbc = {"name": "BBC", "link": "https://www.bbc.com/arabic/a1",
           "text": "بي بي سي: تفصيل مؤكد عن الخبر الرئيسي وأرقامه."}
    ext = {"name": "مدونة مجهولة", "link": "https://random-blog.example/p",
           "text": "مدونة: كلام لا سند له عن الخبر."}
    gov = {"name": "State Department", "link": "https://www.state.gov/briefing",
           "text": "الخارجية: بيان رسمي عن الخبر الرئيسي."}
    questions = [{"question": f"سؤال القارئ رقم {k}؟", "query_ar": f"MARK{k} عربي طويل جدا جدا جدا جدا جدا جدا جدا",
                  "query_en": f"MARK{k} english"} for k in range(1, 6)]
    docs_by_marker = {"MARK1": [bbc, ext], "MARK2": [gov], "MARK3": [ext], "MARK4": [], "MARK5": []}
    brave = {f"MARK{k}": [brave_result(f"https://brave-{k}.example/x", "عنوان", "وصف", "موقع")]
             for k in range(1, 6)}
    item = result["article_items"][0]
    members = important_write.item_members(result, item)
    with ImportantRig([], docs_by_marker, lambda *a: {}, brave_results=brave, brave_key="k",
                      strict_known=True, gap=questions) as rig:
        got = important_gap.gather(result, item, members, cfg)
        pubs = {g["publisher"] for g in got}
        check("(g90) مدخل الكاتب فيه BBC وState Department وحدهما (الموقع الخارجي يُرمى)",
              pubs == {"BBC", "State Department"}, got)
        check("(g90) نداء أسئلة واحد وعبارات البحث ≤ 8 كلمات",
              len(rig.gap_requests) == 1 and all(len(q.split()) <= 8 for q in rig.queries), rig.queries)
        check("(g90) طلبات Brave ≤ important.gap.max_brave (4)",
              0 < len(rig.brave_calls) <= int(icfg["gap"]["max_brave"]) == 4, rig.brave_calls)
    imagesearch.BRAVE_USAGE_FILE.write_text(json.dumps({important._usage_key(): int(icfg["brave_monthly_cap"])}))
    with ImportantRig([], docs_by_marker, lambda *a: {}, brave_results=brave, brave_key="k",
                      strict_known=True, gap=questions) as rig:
        got_capped = important_gap.gather(result, item, members, cfg)
        check("(g90) بلوغ السقف الشهري يمنع طلب Brave ويبقى Google",
              rig.brave_calls == [] and {g["publisher"] for g in got_capped} == {"BBC", "State Department"},
              rig.brave_calls)
    imagesearch.BRAVE_USAGE_FILE.unlink(missing_ok=True)

    # ── g91) write_article بكاتب مزيَّف ──
    gap_src = [{"publisher": "BBC", "link": "https://www.bbc.com/arabic/a1",
                "excerpt": "بي بي سي: تفصيل مؤكد عن الخبر الرئيسي وأرقامه.", "question": "س؟"},
               {"publisher": "State Department", "link": "https://www.state.gov/briefing",
                "excerpt": "الخارجية: بيان رسمي عن الخبر الرئيسي.", "question": "س؟"}]
    good = {"category": "عالم", "hashtags": ["هام"], "image_query_en": "news story",
            "post_title": "تطوّرات الخبر الرئيسي بين المؤكَّد والمتداول",
            "image_headline": "تطوّرات الخبر الرئيسي"}

    from tests.helpers import fresh_date, freshen_nearest
    gap_fresh = [dict(g_, published=fresh_date()) for g_ in gap_src]   # مصدر «الأقرب» يحتاج تاريخًا حديثًا (#1345)

    def run_write(item_, bodies):
        seq = list(bodies)

        def respond(prompt, system):
            return {**good, "post_body": seq.pop(0) if len(seq) > 1 else seq[0]}
        with ImportantWriteRig(respond, gap_sources=gap_fresh if item_["kind"] == "nearest" else gap_src) as rig_:
            rig_.next = 88600
            return important_write.write_article(result, item_, cfg, [], 88100), rig_

    # #1309: الطول لم يعد رفضًا (تنبيه فقط) فصار الرفض الذي تُختبر به إعادة الكتابة عبارة «بحسب معلومات المحرر»
    (d1, why1, _t), rig1 = run_write(items[0], [_b2_body(330, extra="بحسب معلومات المحرر وقع ذلك."), _b2_body(330)])
    check("(g91) عبارة المحرر ← رفض وإعادة كتابة واحدة بذكر العلّة ثم مسودة",
          d1 is not None and len(rig1.calls) == 2 and "محاولتك السابقة رُفضت" in rig1.calls[1]["prompt"]
          and "محاولتك السابقة رُفضت" not in rig1.calls[0]["prompt"], (why1, len(rig1.calls)))
    check("(g91) المسودة: ثلاثة عناوين، بطاقة important لـverified، والحقول article_kind/point_ids/main_story/gap_sources",
          d1 and len(d1["headlines"]) == 3 and cards.card_origin(d1) == "important" and d1["origin"] == "important"
          and d1["article_kind"] == "verified" and d1["point_ids"] == items[0]["point_ids"]
          and d1["main_story"] == result["main_story"] and d1["gap_sources"] == gap_src
          and d1["point_id"] == items[0]["id"], d1 and {k: d1.get(k) for k in ("article_kind", "point_ids")})
    check("(g91) تعليمات الكاتب: الطول الأقصى 450 والخبر الرئيسي ومقتطفا BBC وState Department في المدخل",
          "الطول الأقصى 450 كلمة" in rig1.calls[0]["prompt"] and result["main_story"] in rig1.calls[0]["prompt"]
          and "بي بي سي: تفصيل مؤكد" in rig1.calls[0]["prompt"]
          and "الخارجية: بيان رسمي" in rig1.calls[0]["prompt"], rig1.calls[0]["prompt"][:300])
    (d2, why2, _t), rig2 = run_write(items[0], [_b2_body(330, extra="وتعدّ BBC هذه الخطوة تصعيدًا خطيرًا.")])
    # #1304: نسبة الحكم إلى وسيلة لم تعد سبب فشل — بعد المحاولات الثلاث تُحفظ المسودة بتنبيه «لم يجتز الفحص»
    check("(g91) «وتعدّ BBC…» ← ثلاث محاولات ثم مسودة محفوظة بتنبيه «لم يجتز الفحص» بسبب حكم الوسيلة (#1304)",
          d2 is not None and len(rig2.calls) == 3
          and any(w.startswith("⚠️ لم يجتز الفحص: حكم منسوب إلى وسيلة") for w in d2.get("warnings", [])),
          (why2, len(rig2.calls), d2 and d2.get("warnings")))
    (d3, why3, _t), _r = run_write(items[0], [_b2_body(330, extra="وقال «عبارة مختلقة لا وجود لها في أي مقتطف».")])
    check("(g91) اقتباس « » ليس في أي مقتطف ← يُحوَّل بعد المحاولات الثلاث إلى كلام غير مباشر بتنبيه (#1298) لا يُسقِط المنشور",
          d3 is not None and "«" not in d3["arabic"]["post_body"]
          and any("فحُوِّل" in w for w in d3.get("warnings", [])), why3)
    (d4, why4, _t), _r = run_write(items[0], [_b2_body(330, extra="وقالت «بيان رسمي عن الخبر الرئيسي» أيضًا.")])
    check("(g91) اقتباس موجود حرفيًا في مقتطف ← يمرّ", d4 is not None, why4)
    (d5, why5, _t), _r = run_write(items[2], [_b2_body(330)])
    check("(g91) منشور refuted ← بطاقة important_false («تفنيد»)",
          d5 and cards.card_origin(d5) == "important_false" and d5["article_kind"] == "refuted"
          and d5["badge"] == "تفنيد", d5 and cards.card_origin(d5))
    (d6, why6, _t), _r = run_write(items[1], [_b2_body(330)])
    check("(g91) منشور nearest ← بطاقة important", d6 and cards.card_origin(d6) == "important", why6)
    check("(g91) العنوان سؤال ← رفض",
          important_write.check_article({"post_title": "هل تغيّر الخبر؟", "post_body": _b2_body(330)}, [], cfg)
          == important_write.REASON_TITLE_QUESTION
          and important_write.check_article({"post_title": "ماذا جرى", "post_body": _b2_body(330)}, [], cfg)
          == important_write.REASON_TITLE_QUESTION)

    # ── g92 + g93) التوزيع: الترتيب وsibling_texts، وبطاقتا important وimportant_false، وgo1 وإعادة الاستعمال ──
    result93 = important_b2_result(88200)
    items93 = {i["kind"]: i for i in result93["article_items"]}
    sel = 88300
    for i in result93["article_items"]:
        i["selection_issue"] = sel
    important.save(result93)
    body93 = important_items_marked_body(result93, {items93["refuted"]["id"]: "go2",
                                                    items93["verified"]["id"]: "go2",
                                                    items93["nearest"]["id"]: "go2"}, cfg)
    writes_seen: list = []

    def respond93(prompt, system):
        writes_seen.append(1)
        n = len(writes_seen)
        return {**good, "post_title": f"عنوان منشور رقم {n}", "post_body": _b2_body(330, tag=f"م{n}x")}

    with ImportantWriteRig(respond93, gap_sources=gap_fresh) as rig:
        # أرقام قضايا مزيَّفة فريدة: finalize يبحث عن ملف الحكم برقم قضية الترشيح عبر كل state/important، فتصادم
        # العدّاد الافتراضي (7000) مع ملف اختبار آخر يخلط الملفين
        rig.next = 88700
        code = important_finalize.finalize(sel, body93, cfg)
        saved = important.load_saved(88200)
        saved_items = {i["kind"]: i for i in saved["article_items"]}
        drafts = {k: store.load_draft(saved_items[k]["draft_id"])[1] for k in kind_order}
        writer_calls = [c for c in rig.calls if "أنت محرر يكتب مقالًا" in (c["system"] or "")]
        check("(g92) الكتابة بترتيب verified ثم nearest ثم refuted ولو عُلِّمت بعكسه",
              code == 0 and rig.gap_calls == [(k, items93[k]["point_ids"]) for k in kind_order], rig.gap_calls)
        check("(g92) كتابة الثاني: مدخل الكاتب يحوي نص الأول (sibling_texts) ولا يحويه مدخل الأول؛ والثالث يحوي الاثنين",
              drafts["verified"]["arabic"]["post_title"] in writer_calls[1]["prompt"]
              and "الفقرةم1x0" in writer_calls[1]["prompt"]
              and drafts["verified"]["arabic"]["post_title"] not in writer_calls[0]["prompt"]
              and all(drafts[k]["arabic"]["post_title"] in writer_calls[2]["prompt"] for k in ("verified", "nearest")),
              [c["prompt"][-300:] for c in writer_calls[:2]])
        check("(g93) المسودات: بطاقتا important وimportant_false وحالة العناصر written",
              cards.card_origin(drafts["verified"]) == "important"
              and cards.card_origin(drafts["nearest"]) == "important"
              and cards.card_origin(drafts["refuted"]) == "important_false"
              and all(i["status"] == "written" for i in saved_items.values()), None)
        hit = important_finalize.find_point(items93["verified"]["id"], sel)
        check("(g93) صورة المرحلة 1 لعنصر منشور: find_point يجد العنصر بمعرّفه (setimage يحفظ manual_image عليه)",
              hit is not None and hit[1]["kind"] == "verified", hit and hit[1])
        stage2 = [c for c in rig.created if c["labels"] == ["pending-review"]]
        check("(g93) قضية المرحلة 2 للمسودات الثلاث وفيها مربع go1",
              len(stage2) == 1 and all(f"<!-- draft:{d['id']} -->" in stage2[0]["body"] for d in drafts.values())
              and f"go:go1:{drafts['verified']['id']}" in stage2[0]["body"], stage2[:1])
        # go1 على مسودة verified
        stage2_body = tick_marker(stage2[0]["body"], f"go:go1:{drafts['verified']['id']}")
        writes = len(rig.calls)
        real_fetch, old_argv = publish.fetch_issue, sys.argv
        publish.fetch_issue = lambda n: {"number": n, "body": stage2_body,
                                         "labels": [{"name": "pending-review"}, {"name": "approved"}]}
        sys.argv = ["publish", "--issue", "88401", "--skip-urgent"]
        try:
            publish.main()
        finally:
            publish.fetch_issue, sys.argv = real_fetch, old_argv
        reopened = [c for c in rig.created if c["labels"] == ["important-selection"]]
        returned = store.load_draft(drafts["verified"]["id"])[1]
        item_after = {i["kind"]: i for i in important.load_saved(88200)["article_items"]}["verified"]
        new_sel = reopened[0]["number"] if reopened else 0
        check("(g93) go1 على verified ← قضية ترشيح جديدة بالعنصر نفسه (معرّفه) وشارة «أعدته من المرحلة 2»",
              len(reopened) == 1 and f"go:go2:{items93['verified']['id']}" in reopened[0]["body"]
              and "↩️ أعدته من المرحلة 2 · " in reopened[0]["body"]
              and f"go:go2:{items93['nearest']['id']}" not in reopened[0]["body"]
              and returned["status"] == "returned" and item_after["status"] == "offered"
              and item_after["selection_issue"] == new_sel, (reopened[:1], item_after))
        created_before = len(rig.created)
        code_r = important_finalize.finalize(
            new_sel, tick_marker(reopened[0]["body"], f"go:go2:{items93['verified']['id']}"), cfg)
        back = store.load_draft(drafts["verified"]["id"])[1]
        check("(g93) إعادة اختيار العنصر تعيد المسودة نفسها بلا نداء نموذج وقضية مرحلة 2 جديدة",
              code_r == 0 and len(rig.calls) == writes and back["status"] == "pending"
              and back["arabic"] == drafts["verified"]["arabic"]
              and len(rig.created) == created_before + 1 and rig.created[-1]["labels"] == ["pending-review"],
              (code_r, len(rig.calls), writes))
    # اختيار verified وrefuted فقط ← مسودتان ببطاقتين، والثاني غير المعلَّم «لم يُختر»
    result_b = important_b2_result(88210)
    items_b = {i["kind"]: i for i in result_b["article_items"]}
    for i in result_b["article_items"]:
        i["selection_issue"] = sel + 1
    important.save(result_b)
    body_b = important_items_marked_body(result_b, {items_b["verified"]["id"]: "go2",
                                                    items_b["refuted"]["id"]: "go3"}, cfg)
    with ImportantWriteRig(lambda p, s: {**good, "post_body": _b2_body(330, tag="ب")}, gap_sources=gap_fresh) as rig:
        rig.next = 88800
        important_finalize.finalize(sel + 1, body_b, cfg)
        saved_b = {i["kind"]: i for i in important.load_saved(88210)["article_items"]}
        d_v = store.load_draft(saved_b["verified"]["draft_id"])[1]
        d_r = store.load_draft(saved_b["refuted"]["draft_id"])[1]
        check("(g93) اختيار verified وrefuted ← مسودتان ببطاقتي important وimportant_false، وnearest «لم يُختر»",
              saved_b["nearest"]["status"] == "unselected" and "draft_id" not in saved_b["nearest"]
              and cards.card_origin(d_v) == "important" and cards.card_origin(d_r) == "important_false"
              and [k for k, _ in rig.gap_calls] == ["verified", "refuted"], rig.gap_calls)

    # ── g94) قضية قديمة بعلامات نقاط (fixture 1278.json) ← تُعرض وتُكتب بالمسار القديم ──
    fx = json.loads((IMPORTANT_FIXTURES / "1278.json").read_text(encoding="utf-8"))
    old_body = important_issue.build_selection_body(fx, cfg)
    check("(g94) fixture 1278 قديم بلا articles ← قضيته بعلامات النقاط لا العناصر",
          "articles" not in fx and all(f"go:go2:{p['id']}" in old_body
                                       for p in fx["points"] if p.get("status") != "dropped"), list(fx))
    old = json.loads(json.dumps(fx))
    old["issue"] = 88500
    # نقطة 24246e القديمة بلا nearest.kind فلا تصلح للكتابة الآن؛ تُضاف إلى ملف 1278 نقطة مؤكَّدة صالحة للكتابة
    chosen_pt = important_fixture_point(1209, "confirmed")
    old["points"].append(chosen_pt)
    for p in old["points"]:
        p["selection_issue"] = 88600
    important.save(old)
    body_old = important_marked_body(old, {chosen_pt["id"]: "go2"}, cfg)
    with ImportantWriteRig(lambda p, s: important_good_data(chosen_pt)) as rig:
        rig.next = 88900
        important_finalize.finalize(88600, body_old, cfg)
        saved_old = {p["id"]: p for p in important.load_saved(88500)["points"]}
        d_old = store.load_draft(saved_old[chosen_pt["id"]]["draft_id"])[1]
        check("(g94) القضية القديمة تُكتب بالمسار القديم: نقطة ← مسودة بمعرّفها بلا article_kind وبنداء كاتب واحد",
              d_old["point_id"] == chosen_pt["id"] and "article_kind" not in d_old
              and saved_old[chosen_pt["id"]]["status"] == "written" and len(rig.calls) == 1, d_old.get("point_id"))


def test_important_1304_guards() -> None:
    """Issue #1304 (B4): g100–g106 — لا يسقط منشور إلا بلا وقائع أو بعطل تقني: إصلاح العنوان السؤال آليًا،
    عتبة نسخ 12 للمنشورات الطويلة (شاهد 1300.json)، أسماء المصادر بالعربية، الخبر نفسه أول أسئلة البحث
    المكمِّل، تحويل publish/go3 إلى go2 لمنشور فيه تنبيه فحص، تنبيه الزمن النسبي، وبلا مقتطف فشل."""
    import copy
    import json

    from src import headlines as headlines_mod, important, important_finalize, important_gap, important_write
    from tests.helpers import (IMPORTANT_FIXTURES, ImportantRig, ImportantWriteRig, important_b2_result,
                               important_items_marked_body)

    cfg = load_config()
    result = important_b2_result(90400)
    gap = [{"publisher": "State Department", "link": "https://www.state.gov/briefing",
            "excerpt": "الخارجية: بيان رسمي عن الخبر الرئيسي.", "question": "س؟"}]
    good = {"category": "عالم", "hashtags": ["هام"], "image_query_en": "news story",
            "post_title": "تطوّرات الخبر الرئيسي بين المؤكَّد والمتداول", "image_headline": "تطوّرات الخبر الرئيسي"}

    def run(kind, respond, res=None, gap_sources=gap, issue=90100):
        src_res = res or result
        item = {i["kind"]: i for i in src_res["article_items"]}[kind]
        with ImportantWriteRig(respond, gap_sources=gap_sources) as rig:
            rig.next = 90600
            out = important_write.write_article(src_res, item, cfg, [], issue)
        return out, rig, item

    # ── g100) عنوان سؤالي في المحاولات الثلاث ← عنوان خبري من headlines_for_post، لا فشل ──
    q_title = "هل تخنق واشنطن حزب الله ماليًا وتدعم إعمار لبنان؟"
    asked: list = []
    real_hl = headlines_mod.headlines_for_post

    def fake_hl(post_title, post_body, cfg_, client=None, first_question=True, system=None):
        asked.append((first_question, system))
        return ["واشنطن تشدد الخناق المالي على حزب الله", "عنوان بديل ثانٍ", "عنوان بديل ثالث"], None
    headlines_mod.headlines_for_post = fake_hl
    try:
        (d100, why100, tech100), rig100, _it = run(
            "verified", lambda p, sy: {**good, "post_title": q_title, "image_headline": q_title,
                                       "post_body": _b2_body(330)})
        arabic100 = d100["arabic"] if d100 else {}
        check("(g100) ثلاث محاولات بعنوان سؤالي ← مسودة بعنوان خبري من headlines_for_post لا فشل",
              d100 is not None and len(rig100.calls) == 3 and not tech100
              and arabic100["post_title"] == "واشنطن تشدد الخناق المالي على حزب الله"
              and arabic100["image_headline"] == arabic100["post_title"]
              and not any(w.startswith("⚠️ لم يجتز الفحص") for w in d100.get("warnings", [])),
              (why100, arabic100.get("post_title"), d100 and d100.get("warnings")))
        check("(g100) العناوين طُلبت بلا قاعدة «الأول سؤال» وبنظام important.headline_system",
              (False, cfg.path("important.headline_system")) in asked, asked)
        headlines_mod.headlines_for_post = lambda *a, **k: ([q_title, "هل هذا ثانٍ؟", "هل ثالث؟"], None)
        (d100b, _w, _t), _r, _i = run("verified", lambda p, sy: {**good, "post_title": q_title,
                                                                 "image_headline": q_title,
                                                                 "post_body": _b2_body(330)})
        check("(g100) المولِّد لم يعد عنوانًا خبريًا ← يبقى العنوان السؤال ومعه تنبيه «لم يجتز الفحص: العنوان سؤال»",
              d100b is not None and d100b["arabic"]["post_title"] == q_title and any(
                  w == important_write.WARN_FAILED_CHECK.format(reason=important_write.REASON_TITLE_QUESTION)
                  for w in d100b.get("warnings", [])), d100b and d100b.get("warnings"))
    finally:
        headlines_mod.headlines_for_post = real_hl

    # ── g101) last_attempt الحقيقي لمنشور nearest من 1300.json ← يجتاز الأصالة بالعتبة 12 ──
    real = json.loads((IMPORTANT_FIXTURES / "1300.json").read_text(encoding="utf-8"))
    near = next(i for i in real["article_items"] if i["kind"] == "nearest")
    copied = near["last_attempt"]["post_body"]
    real_gap = copy.deepcopy(near["gap_sources"])
    from tests.helpers import fresh_date
    for g_ in real_gap:       # مقتطفات الشاهد الحقيقي تاريخها قديم؛ التاريخ الحديث يُضاف في الإعداد لا في الملف (#1345)
        g_["published"] = fresh_date()
    (d101, why101, _t), _r, _i = run(
        "nearest", lambda p, sy: {**good, "post_title": near["last_attempt"]["post_title"],
                                  "image_headline": near["last_attempt"]["post_title"],
                                  "post_body": copied}, res=copy.deepcopy(real), gap_sources=real_gap, issue=1300)
    shared = [w for w in (d101 or {}).get("warnings", []) if "نسخ لفظي" in w]
    check("(g101) نص 1300.json الحقيقي ← مسودة لا فشل، والتتابع الذي أسقطه (7 كلمات «شبكة مالية عالمية تقدم الدعم…») "
          "لم يعد يُبلَّغ عنه؛ يبقى تنبيه واحد لتتابع حقيقي من 12 كلمة في جملة أخرى من النص نفسه",
          d101 is not None and len(shared) == 1 and "12 كلمة" in shared[0] and "7 كلمة" not in shared[0],
          (why101, shared))
    sentence7 = ("فرضت الولايات المتحدة في 20 آذار/مارس 2026 عقوبات جديدة استهدفت شبكة مالية عالمية "
                 "تقدم الدعم لحزب الله، بحسب بيان صادر عن النائب الأول للمتحدث الرسمي.")
    (d101c, why101c, _t), _r, _i = run(
        "nearest", lambda p, sy: {**good, "post_title": "عنوان خبري عادي لمنشور تجريبي",
                                  "image_headline": "عنوان خبري عادي", "post_body": _b2_body(330, extra=sentence7)},
        res=copy.deepcopy(real), gap_sources=copy.deepcopy(real_gap), issue=1300)
    check("(g101) الجملة المنسوبة صراحة بتتابع 7 كلمات مع مقتطف state.gov ← تجتاز الأصالة بالعتبة 12 بلا تنبيه نسخ",
          d101c is not None and not any("نسخ لفظي" in w for w in d101c.get("warnings", [])),
          (why101c, d101c and d101c.get("warnings")))
    check("(g101) العتبة من important.article_max_shared_run_words (12) لا article.max_shared_run_words (7)",
          cfg.path("important.article_max_shared_run_words") == 12 and cfg.path("article.max_shared_run_words") == 7)
    state_gov = next(g for g in real_gap if "state.gov" in g["link"])
    run15 = " ".join(state_gov["excerpt"].split()[40:55])
    (d101b, why101b, _t), _r, _i = run(
        "nearest", lambda p, sy: {**good, "post_title": "عنوان خبري عادي لمنشور تجريبي",
                                  "image_headline": "عنوان خبري عادي",
                                  "post_body": _b2_body(330, extra=run15)},
        res=copy.deepcopy(real), gap_sources=real_gap, issue=1300)
    check("(g101) ضابطة: نسخ 15 كلمة متتالية ← مسودة محفوظة فيها «لم يجتز الفحص: نسخ لفظي…»",
          d101b is not None and any(w.startswith("⚠️ لم يجتز الفحص: نسخ لفظي") for w in d101b.get("warnings", [])),
          (why101b, d101b and d101b.get("warnings"), run15))

    # ── g102) U.S. Department of State في المتن ← عربيه في المسودة، ومدخل الكاتب يحمل العربي ──
    gap102 = [{"publisher": "U.S. Department of State", "link": "https://www.state.gov/briefing",
               "excerpt": "الخارجية: بيان رسمي عن الخبر الرئيسي.", "question": "س؟"},
              {"publisher": "Obscure Wire", "link": "https://www.bbc.com/arabic/z",
               "excerpt": "مصدر ثانٍ: تفصيل عن الخبر الرئيسي.", "question": "س؟"}]
    (d102, why102, _t), rig102, _i = run(
        "verified", lambda p, sy: {**good, "post_body": _b2_body(
            330, extra="وبحسب U.S. Department of State فالخطوة رسمية، وأفاد Obscure Wire بتفصيل آخر.")},
        gap_sources=gap102)
    body102 = d102["arabic"]["post_body"] if d102 else ""
    check("(g102) «وبحسب U.S. Department of State» ← «وبحسب وزارة الخارجية الأميركية» في المسودة",
          d102 is not None and "وبحسب وزارة الخارجية الأميركية" in body102
          and "U.S. Department of State" not in body102, (why102, body102[-160:]))
    first_prompt = rig102.calls[0]["prompt"]
    check("(g102) مدخل الكاتب يحمل الاسم العربي لا اللاتيني",
          "وزارة الخارجية الأميركية" in first_prompt and "U.S. Department of State" not in first_prompt,
          first_prompt[:300])
    check("(g102) اسم لاتيني بلا مقابل في المتن ← تنبيه «اسم مصدر بغير العربية»",
          "اسم مصدر بغير العربية: Obscure Wire" in (d102 or {}).get("warnings", []), (d102 or {}).get("warnings"))
    check("(g102) publisher_ar: الخريطة، ثم الاسم كما هو",
          important_write.publisher_ar("BBC", cfg) == "بي بي سي"
          and important_write.publisher_ar("U.S. Department of State (.gov)", cfg) == "وزارة الخارجية الأميركية"
          and important_write.publisher_ar("مجهول", cfg) == "مجهول")

    # ── g103) أول سؤال بحث مكمِّل = سؤال الخبر نفسه من الكود، وعبارتاه من main_story ──
    main103 = "فرض عقوبات أميركية جديدة على شبكة تمويل حزب الله في لبنان وأوروبا"
    with ImportantRig([], {}, lambda *a: {}, gap=[
            {"question": "من فرض العقوبات؟", "query_ar": "عقوبات حزب الله", "query_en": "Hezbollah sanctions"}],
            gap_main_story_en="Hezbollah financing sanctions news update today by US officials this week"):
        res103 = important_b2_result(90300, main_story=main103)
        it103 = res103["article_items"][0]
        qs = important_gap.gap_questions(res103, it103, important_write.item_members(res103, it103), cfg)
    check("(g103) أول سؤال «ما آخر ما نُشر عن: {main_story}؟» ثم أسئلة النموذج",
          len(qs) == 2 and qs[0]["question"] == f"ما آخر ما نُشر عن: {main103}؟"
          and qs[1]["question"] == "من فرض العقوبات؟", qs)
    check("(g103) عبارتا السؤال الأول من main_story: العربية مقصوصة إلى 8 كلمات والإنجليزية من main_story_en",
          qs[0]["query_ar"] == " ".join(main103.split()[:8]) and len(qs[0]["query_en"].split()) == 8
          and qs[0]["query_en"].startswith("Hezbollah financing"), qs[0])
    check("(g103) GAP_SCHEMA يطلب main_story_en",
          "main_story_en" in important_gap.GAP_SCHEMA["input_schema"]["properties"]
          and "main_story_en" in important_gap.GAP_SCHEMA["input_schema"]["required"])

    # ── g104) publish/go3 لمنشور فيه «لم يجتز الفحص» ← go2 + تعليق؛ وبلا تنبيه يبقى كما هو ──
    def staged(issue, actions, body_words):
        res = important_b2_result(issue)
        its = {i["kind"]: i for i in res["article_items"]}
        for i in res["article_items"]:
            i["selection_issue"] = issue + 1
        important.save(res)
        body = important_items_marked_body(res, {its[k]["id"]: a for k, a in actions.items()}, cfg)
        with ImportantWriteRig(lambda p, sy: {**good, "post_body": _b2_body(body_words)},
                               gap_sources=[dict(g_, published=fresh_date()) for g_ in gap]) as rig:
            rig.next = issue + 500
            code = important_finalize.finalize(issue + 1, body, cfg)
        return code, rig

    code_w, rig_w = staged(90410, {"verified": "publish", "nearest": "go3"}, 80)
    moved = [t for _n, t in rig_w.comments if "إلى المراجعة لأن فيه تنبيهات فحص" in t and t.startswith("📝 حُوِّل ")]
    check("(g104) publish وgo3 لمنشورين فيهما تنبيه فحص ← تعليقان بالتحويل، ولا نشر ولا بطاقة",
          code_w == 0 and len(moved) == 2 and rig_w.published == [] and rig_w.builds == [],
          (code_w, rig_w.comments, rig_w.published))
    check("(g104) فُتحت قضية مرحلة 2 للمنشورين المحوَّلين",
          any("pending-review" in (c.get("labels") or []) for c in rig_w.created), [c["labels"] for c in rig_w.created])
    code_ok, rig_ok = staged(90430, {"verified": "publish"}, 330)
    check("(g104) بلا تنبيه فحص ← publish كما هو: نشر ولا تعليق تحويل",
          not [t for _n, t in rig_ok.comments if "إلى المراجعة لأن فيه تنبيهات فحص" in t] and rig_ok.published,
          (rig_ok.comments, rig_ok.published))

    # ── g105) «الشهر الماضي» في المتن ← تنبيه الزمن النسبي؛ وتعليمة النهي في الموجّه ──
    (d105, why105, _t), rig105, _i = run(
        "verified", lambda p, sy: {**good, "post_body": _b2_body(330, extra="وكانت رويترز نقلت الشهر الماضي خبرًا مشابهًا.")})
    check("(g105) «الشهر الماضي» ← «زمن نسبي في المتن: «الشهر الماضي» — تحقّق من التاريخ»",
          d105 is not None and "زمن نسبي في المتن: «الشهر الماضي» — تحقّق من التاريخ" in d105.get("warnings", []),
          (why105, d105 and d105.get("warnings")))
    check("(g105) بلا عبارة زمن نسبي ← لا تنبيه، والموجّه ينهى عن نقلها",
          not important_write.relative_time_warnings({"post_title": "ت", "post_body": _b2_body(50)}, cfg)
          and "لا تنقل عبارات الزمن النسبي" in rig105.calls[0]["prompt"], rig105.calls[0]["prompt"][:200])

    # ── g106) بلا أي مقتطف ← فشل بـNO_FACTS_REASON ولا نداء كاتب ──
    res106 = copy.deepcopy(result)
    for p in res106["points"]:
        p["evidence"], p["nearest"], p["refuted_by"], p["correction"] = [], None, [], None
    (d106, why106, tech106), rig106, _i = run("nearest", lambda p, sy: {**good, "post_body": _b2_body(330)},
                                              res=res106, gap_sources=[])
    check("(g106) بلا مقتطف ← NO_FACTS_REASON وبلا نداء كاتب ولا عطل تقني",
          d106 is None and why106 == important_write.NO_FACTS_REASON and not tech106 and rig106.calls == [],
          (why106, len(rig106.calls)))


def test_important_1298_guards() -> None:
    """Issue #1298 (B3): g95–g99 — فحص اقتباس واحد للمنشورات الثلاثة، وتحويل الاقتباس بدل إسقاط المنشور،
    وحفظ أثر المحاولة الفاشلة (last_attempt وgap_sources)، وnearest لا تعامل نقاطها كمعروفة."""
    import copy

    from src import important_write
    from tests.helpers import ImportantWriteRig, fresh_date, important_b2_result

    cfg = load_config()
    result = important_b2_result(89000)
    items = {i["kind"]: i for i in result["article_items"]}
    gap = [{"publisher": "State Department", "link": "https://www.state.gov/briefing",
            "excerpt": "الخارجية: عقوبات لصالح الفريق المالي التابع لحزب الله في لبنان.", "question": "س؟"}]
    good = {"category": "عالم", "hashtags": ["هام"], "image_query_en": "news story",
            "post_title": "تطوّرات الخبر الرئيسي بين المؤكَّد والمتداول", "image_headline": "تطوّرات الخبر الرئيسي"}
    bad_quote = "وفرضت عقوبات على «الفريق المالي لحزب الله» في لبنان."

    def run(kind, bodies, res=None):
        src_res = res or result
        item = {i["kind"]: i for i in src_res["article_items"]}[kind]
        seq = list(bodies)

        def respond(prompt, system):
            return {**good, "post_body": seq.pop(0) if len(seq) > 1 else seq[0]}
        # مقتطفات «الأقرب» تحتاج تاريخًا حديثًا محسوبًا وقت التشغيل (#1345)
        with ImportantWriteRig(respond, gap_sources=[dict(g_, published=fresh_date()) for g_ in gap]
                               if kind == "nearest" else gap) as rig:
            rig.next = 89600
            out = important_write.write_article(src_res, item, cfg, [], 89100)
        return out, rig, item

    # ── g95) الفحص الموحَّد: اقتباس مختصَر يُرفض بسبب الاقتباس لا بسبب الأصالة ──
    sources = [gap[0]["excerpt"]]
    written = {"post_title": "عقوبات جديدة", "post_body": _b2_body(330, extra=bad_quote)}
    why95 = important_write.check_article(written, sources, cfg)
    check("(g95) «الفريق المالي لحزب الله» مقابل «…الفريق المالي التابع لحزب الله» ← رفض بسبب الاقتباس",
          why95 is not None and why95.startswith("اقتباس بين « »") and "الفريق المالي لحزب الله" in why95
          and "انقله حرفيًا من المقتطف كما هو" in why95 and "الأصالة" not in why95, why95)
    check("(g95) الاقتباس الحرفي من المقتطف يمرّ",
          important_write.check_article({"post_title": "عقوبات جديدة", "post_body": _b2_body(
              330, extra="وفرضت عقوبات «لصالح الفريق المالي التابع لحزب الله» فعلًا.")}, sources, cfg) is None)

    # ── g96) كاتب يقتبس خطأً في المحاولات الثلاث ← مسودة بلا علامتين وتنبيه تحويل ──
    (d96, why96, _t), rig96, _it = run("verified", [_b2_body(330, extra=bad_quote)])
    body96 = d96["arabic"]["post_body"] if d96 else ""
    check("(g96) ثلاث محاولات ثم مسودة محفوظة: النص بلا « » حول الجملة والعبارة باقية",
          d96 is not None and len(rig96.calls) == 3 and "«" not in body96
          and "عقوبات على الفريق المالي لحزب الله في لبنان" in body96, (why96, len(rig96.calls)))
    check("(g96) warnings فيها تنبيه التحويل بنصّه",
          d96 and any(w == important_write.REASON_QUOTE_CONVERTED.format(quote="الفريق المالي لحزب الله")
                      for w in d96.get("warnings", [])), d96 and d96.get("warnings"))

    # ── g97) 120 كلمة في المحاولات الثلاث ← مسودة بتنبيه «لم يجتز الفحص» (#1304: الطول لم يعد سبب فشل) ──
    # #1309: 80 جملة-كلمات (~110 كلمة فعلية) تحت حدّ التنبيه 150؛ كان 120 اسميًا يتجاوزه بعدّ \w+ فلا تنبيه
    (d97, why97, tech97), _r, it97 = run("verified", [_b2_body(80)])
    check("(g97) ~110 كلمة ← مسودة محفوظة لا فشل، وفيها تنبيه الطول بالقالب",
          d97 is not None and not tech97 and any(
              w.startswith("⚠️ لم يجتز الفحص: عدد كلمات") and w.endswith("— راجعه قبل النشر")
              for w in d97.get("warnings", [])), (why97, d97 and d97.get("warnings")))
    check("(g97) نجاح الكتابة لا يترك last_attempt، وgap_sources محفوظة على العنصر",
          "last_attempt" not in it97 and it97.get("gap_sources") == gap, it97.get("last_attempt"))

    # ── g98) nearest لا تعامل نقاطها معروفة، وverified لا يقتبس نص نقطة عضو ──
    claim = "حزب الله لن يتعافى أبداً"
    res98 = copy.deepcopy(result)
    near = next(i for i in res98["article_items"] if i["kind"] == "nearest")
    for p in res98["points"]:
        if p["id"] in near["point_ids"]:
            p["claim"] = claim
    (d98, why98, _t), _r, _it = run("nearest", [_b2_body(330, extra=f"{claim}.")], res=res98)
    check("(g98) nearest: جملة تقرّر نص النقطة العضو بلا سند ← مسودة فيها تنبيه unsourced لها",
          d98 is not None and any("يتعافى" in w for w in d98.get("warnings", [])), (why98, d98 and d98.get("warnings")))
    quoted_claim = {"post_title": "عقوبات جديدة", "post_body": _b2_body(330, extra=f"وقيل «{claim}» أيضًا.")}
    check("(g98) verified: اقتباس نص نقطة عضو حرفيًا ← رفض (النص المسموح مقتطفات المصادر وحدها)",
          (important_write.check_article(quoted_claim, sources, cfg) or "").startswith("اقتباس بين « »"))

    # ── g99) refuted يقتبس claim العضو مرة واحدة ← مقبول ──
    ref_claim = next(p for p in result["points"] if p["id"] in items["refuted"]["point_ids"])["claim"]
    (d99, why99, _t), _r, _it = run("refuted", [_b2_body(300, extra=f"وتداول الناس «{ref_claim}».")])
    check("(g99) refuted: اقتباس claim العضو حرفيًا ← مسودة بلا تحويل ولا تنبيه تحويل",
          d99 is not None and f"«{ref_claim}»" in d99["arabic"]["post_body"]
          and not any("فحُوِّل" in w for w in d99.get("warnings", [])), why99)


def test_important_1309_guards() -> None:
    """Issue #1309 (B5): g107–g114 على شاهد حقيقي (tests/fixtures/important/1306/: نتيجة الحكم والمسودات الثلاث
    ea1ea7937cc8 وdaec2c113f1c وbbf1c1239a95) — حارس التصحيح بلا تفصيل، أسئلة البحث المكمِّل لكل منشور، فلتر الصلة،
    تاريخ كل مصدر، تنبيه الفقرة الخارجة عن الموضوع والتكرار والتفنيد الناقص، والعنوان الافتراضي."""
    import copy
    import json
    from datetime import datetime, timedelta, timezone

    from src import headlines as headlines_mod, important, important_gap, important_write
    from tests.helpers import (IMPORTANT_FIXTURES, ImportantRig, ImportantWriteRig, important_b2_result,
                               important_synthetic_point)

    cfg = load_config()
    icfg = cfg.get("important", {}) or {}
    fx = IMPORTANT_FIXTURES / "1306"
    real = json.loads((fx / "1306.json").read_text(encoding="utf-8"))
    drafts = {k: json.loads((fx / f"{k}.json").read_text(encoding="utf-8"))
              for k in ("ea1ea7937cc8", "daec2c113f1c", "bbf1c1239a95")}
    items = {i["kind"]: i for i in real["article_items"]}
    p916 = next(p for p in real["points"] if p["id"].startswith("916580"))
    ev = p916["evidence"][0]

    # ── g107) تفصيل date/number/name في نقطة بلا ما يخالفه ← لا تصحيح؛ ضابطة بنقطة فيها تاريخ ──
    pool = {"BBC": {"name": "BBC", "link": ev["link"], "text": ev["excerpt"]}}

    def judged(f, kind="date", error=None):
        src = {"source": "BBC", "stance": "conflicts_detail", "same_event": True,
               "excerpt": ev["excerpt"], "detail": error or ev["detail"],
               "correct_form": ev["correct_form"], "as_of": ev["as_of"], "detail_kind": kind}
        st = important._read_stances({"sources": [src]}, pool, f, icfg)
        return st, important.decide(st, pool, cfg, f)

    f_no_date = {"text": p916["claim"], "entities": ["حزب الله", "لبنان", "إيران"], "numbers": [], "dates": []}
    st, dec = judged(f_no_date)
    check("(g107) النقطة 916580 بمقتطف BBC الحقيقي وdetail_kind=date بلا dates ← ليست inaccurate ولا تصحيح",
          dec["verdict"] != "inaccurate" and st["BBC"]["stance"] == "related_other" and not dec.get("correction"),
          (dec["verdict"], st["BBC"]["stance"]))
    st_c, dec_c = judged({**f_no_date, "dates": ["2 مارس 2026"]})
    check("(g107) ضابطة: النقطة نفسها وفيها تاريخ ← inaccurate كما كان",
          dec_c["verdict"] == "inaccurate" and (dec_c["correction"] or {}).get("detail_kind") == "date", dec_c["verdict"])
    check("(g107) number بلا numbers في النقطة ← لا تصحيح؛ ومعها numbers ← تصحيح",
          judged(f_no_date, "number")[0]["BBC"]["stance"] == "related_other"
          and judged({**f_no_date, "numbers": ["6"]}, "number")[0]["BBC"]["stance"] == "conflicts_detail")
    check("(g107) name بخطأ لا يرد في claim ← لا تصحيح؛ وكلمة ≥ 4 أحرف من الخطأ واردة في claim ← تصحيح",
          judged(f_no_date, "name", "الصواريخ الباليستية")[0]["BBC"]["stance"] == "related_other"
          and judged(f_no_date, "name", "دور لبنان في الحرب")[0]["BBC"]["stance"] == "conflicts_detail")
    check("(g107) rules_version 7 (رُفعت في #1345)", cfg.path("important.rules_version") == 7)

    # ── g108) أسئلة البحث المكمِّل لكل منشور ──
    qs_by, reqs_by = {}, {}
    for kind in ("verified", "nearest", "refuted"):
        with ImportantRig([], {}, lambda *a: {}, gap=[
                {"question": "سؤال من نص النقطة؟", "query_ar": "حزب الله بيان", "query_en": "Hezbollah statement"}],
                gap_main_story_en="US policy on Hezbollah and Lebanon") as rig_:
            qs_by[kind] = important_gap.gap_questions(
                real, items[kind], important_write.item_members(real, items[kind]), cfg)
            reqs_by[kind] = list(rig_.gap_requests)
    fixed_q = icfg.get("gap", {}).get("main_question").format(main_story=real["main_story"])
    check("(g108) verified فيه السؤال الثابت أولًا وفي مدخل النموذج الخبر الرئيسي",
          qs_by["verified"][0]["question"] == fixed_q and real["main_story"] in reqs_by["verified"][0],
          qs_by["verified"])
    check("(g108) nearest وrefuted ليس فيهما السؤال الثابت ولا الخبر الرئيسي في مدخل النموذج",
          all(fixed_q not in [q["question"] for q in qs_by[k]] and real["main_story"] not in reqs_by[k][0]
              for k in ("nearest", "refuted")), (qs_by["nearest"], qs_by["refuted"]))
    check("(g108) أسئلتهما من claims أعضائهما: كل claim في مدخل النموذج",
          all(m["claim"] in reqs_by[k][0] for k in ("nearest", "refuted")
              for m in important_write.item_members(real, items[k])))

    # ── g109) فلتر الصلة بوثائق gap الحقيقية: اليونان وجنوب أفريقيا ودرعا تُرمى ──
    def gap_doc(kind, link_part):
        g = next(g for g in items[kind]["gap_sources"] if link_part in g["link"])
        return {"name": g["publisher"], "link": g["link"], "text": g["excerpt"]}

    greece = gap_doc("refuted", "gretsiyi")
    safrica = gap_doc("verified", "south-african")
    daraa = gap_doc("nearest", "israeli-army-prepares")
    sanctions = gap_doc("verified", "sanctioning-a-global-network")
    iranintl = gap_doc("verified", "iranintl")

    class StubSearch:
        docs: list = []
        dates: dict = {}

        def __init__(self, cfg_, body):
            self.brave = {"requests": 0, "skipped": None}
            self.days = 21

        def resolve_link(self, link):
            return link, True

        def run(self, *a, **k):
            return [], list(StubSearch.docs), []

        def run_brave(self, *a, **k):
            return [], [], []

        def published_of(self, d):
            return StubSearch.dates.get(d["link"], "")

    q_one = [{"question": "س؟", "query_ar": "حزب الله", "query_en": ""}]
    real_search = important._PointSearch
    important._PointSearch = StubSearch
    try:
        StubSearch.docs = [greece, safrica, daraa, sanctions]
        stats: dict = {}
        out = important_gap.search_gap(q_one, cfg, ["حزب الله"], stats)
        kept_links = [g["link"] for g in out]
        check("(g109) كيان محوري «حزب الله» ← الوثائق الثلاث (اليونان وجنوب أفريقيا ودرعا) تُرمى وتُعدّ",
              not any(d["link"] in kept_links for d in (greece, safrica, daraa)) and stats["off_topic"] == 3,
              (kept_links, stats))
        check("(g109) ووثيقة عقوبات حزب الله (State Dept) تبقى", sanctions["link"] in kept_links, (kept_links, stats))
        out_all = important_gap.search_gap(q_one, cfg, [], {})
        check("(g109) بلا كيان محوري (نتيجة قديمة بلا entities) ← لا فلتر",
              len(out_all) >= 3, [g["link"] for g in out_all])

        # ── g110) وثيقة أقدم من 120 يومًا تُرمى؛ ومدخل الكاتب يحمل تاريخ النشر ──
        today = datetime.now(timezone.utc).date()
        recent = (today - timedelta(days=10)).isoformat()
        StubSearch.docs = [sanctions, iranintl]
        StubSearch.dates = {sanctions["link"]: "2025-01-05", iranintl["link"]: recent}
        stats = {}
        # بلا كيان محوري: وثيقة Iran International عن مقابلة «تايم» لا تذكر حزب الله فتُرمى بفلتر الصلة لا بالعمر
        out = important_gap.search_gap(q_one, cfg, [], stats)
    finally:
        important._PointSearch = real_search
    check("(g110) وثيقة published أقدم من 120 يومًا ← تُرمى، والحديثة تبقى بتاريخها",
          [g["link"] for g in out] == [iranintl["link"]] and stats["too_old"] == 1
          and out[0]["published"] == recent, (out, stats))
    members_v = copy.deepcopy(important_write.item_members(real, items["verified"]))
    ev_link = important_write.ordered_sources(members_v[0], cfg)[0]["link"]
    members_v[0]["read_docs"] = [{"publisher": "x", "link": ev_link, "published": "2026-03-20"}]
    grounded = important_write.article_grounded(members_v, [dict(out[0])], cfg)
    texts = [s_["text"] for f in grounded for s_ in f["sources"]]
    check("(g110) مدخل الكاتب: مقتطف البحث المكمِّل «(نُشر: YYYY-MM-DD)»",
          any(t.endswith(f"(نُشر: {recent})") for t in texts), texts)
    check("(g110) وأدلة العضو بتاريخ read_docs بالرابط",
          any(t.endswith("(نُشر: 2026-03-20)") for t in texts), texts)
    check("(g110) ما بلا تاريخ ← «(تاريخ غير معروف)»", any(t.endswith("(تاريخ غير معروف)") for t in texts), texts)
    s_ = important._PointSearch(cfg, "")
    s_._keep_html("https://x.example/a",
                  '<html><head><meta property="article:published_time" content="2026-03-20T10:00:00Z">'
                  "</head><body><p>خبر</p></body></html>")
    check("(g110) htmldate على HTML الصفحة المقروءة ← تاريخها",
          s_.published_of({"link": "https://x.example/a"}) == "2026-03-20", s_.dates)
    common = icfg["article_instructions"]["common"]
    check("(g110) تعليمات common: تاريخ المصدر وعتبة 14 يومًا والطول الأقصى بلا أدنى",
          "14 يومًا" in common and "ولا حدّ أدنى ملزم" in common)

    # ── g111) الفقرة اليونانية في نص bbf1c1239a95 الحقيقي ← تنبيه خارج الموضوع ──
    bbf = drafts["bbf1c1239a95"]["arabic"]
    warns111 = important_write.off_topic_warnings(bbf, ["حزب الله"], cfg)
    greek_para = next((p for p in bbf["post_body"].split("\n") if "اليونان" in p), "")
    check("(g111) فقرة اليونان ← «⚠️ فقرة قد تكون خارج الموضوع: «أول 12 كلمة…»»",
          bool(greek_para)
          and important_write.WARN_OFF_TOPIC.format(start=" ".join(greek_para.split()[:12])) in warns111,
          (greek_para[:80], warns111))
    check("(g111) فقرة تذكر حزب الله لا تُنبَّه، وبلا كيان محوري لا تنبيه",
          important_write.off_topic_warnings({"post_body": "فرضت واشنطن عقوبات على حزب الله."}, ["حزب الله"], cfg) == []
          and important_write.off_topic_warnings(bbf, [], cfg) == [])

    # ── g112) ea1ea… وbbf1c… الحقيقيان يبدآن بالفقرتين نفسيهما ← تنبيه التكرار ──
    ea = drafts["ea1ea7937cc8"]["arabic"]
    sib = f"{ea['post_title']}\n{ea['post_body']}"
    warns112 = important_write.repeat_warnings(bbf, [sib])
    check("(g112) نصا ea1ea… وbbf1c… ← تنبيه تكرار بتتابع 12 كلمة",
          len(warns112) == 1 and warns112[0].startswith("⚠️ تكرار مع منشور آخر من النص نفسه: «"), warns112)
    check("(g112) نص غير متشابه ← لا تنبيه",
          important_write.repeat_warnings(
              {"post_title": "ت", "post_body": "نص مختلف تمامًا عن كل ما سبق " * 3}, [sib]) == [])

    # ── g113) منشور التفنيد بلا الصيغة الصحيحة أو جهة النفي ──
    false_pt = important_synthetic_point("false")
    members_r = [copy.deepcopy(p916), false_pt]
    warns113 = important_write.refutation_warnings(
        "refuted", members_r, {"post_title": "ت", "post_body": "كلام عام."}, cfg)
    check("(g113) refuted بلا الصيغة الصحيحة ولا اسم جهة النفي ← تنبيه يذكر النقطتين",
          len(warns113) == 1
          and warns113[0].startswith("⚠️ منشور التفنيد لا يذكر الصيغة الصحيحة أو جهة النفي لـ: ")
          and p916["claim"] in warns113[0] and false_pt["claim"] in warns113[0], warns113)
    ok_body = f"{p916['correction']['correct']}. وكذّبت Fatabyyano الادّعاء."
    check("(g113) المتن يذكر الصيغة الصحيحة واسم المدقّق ← لا تنبيه؛ وغير refuted لا تنبيه",
          important_write.refutation_warnings("refuted", members_r, {"post_title": "ت", "post_body": ok_body}, cfg) == []
          and important_write.refutation_warnings("verified", members_r, {"post_title": "ت", "post_body": "ن"}, cfg) == [])

    # ── g114) العنوان الافتراضي = أول عنوان خبري من headlines_for_post دائمًا ──
    result = important_b2_result(91400)
    good = {"category": "عالم", "hashtags": ["هام"], "image_query_en": "news story",
            "post_title": "ما السياسة الأميركية الجديدة تجاه حزب الله", "image_headline": "السياسة الأميركية"}
    gap = [{"publisher": "State Department", "link": "https://www.state.gov/briefing",
            "excerpt": "الخارجية: بيان رسمي عن الخبر الرئيسي.", "question": "س؟"}]
    real_hl = headlines_mod.headlines_for_post
    try:
        headlines_mod.headlines_for_post = lambda *a, **k: (
            ["هل تغيّرت السياسة؟", "واشنطن تعدّل سياستها تجاه حزب الله", "عنوان ثالث"], None)
        item = {i["kind"]: i for i in result["article_items"]}["verified"]
        with ImportantWriteRig(lambda p, sy: {**good, "post_body": _b2_body(330)}, gap_sources=gap) as rig:
            rig.next = 91600
            d114, why114, _t = important_write.write_article(result, item, cfg, [], 91100)
        check("(g114) الكاتب كتب عنوانًا ← post_title = أول عنوان خبري من القائمة المعروضة نفسها",
              d114 is not None and d114["arabic"]["post_title"] == "واشنطن تعدّل سياستها تجاه حزب الله"
              and d114["arabic"]["post_title"] in d114["headlines"], (why114, d114 and d114["arabic"]["post_title"]))
        headlines_mod.headlines_for_post = lambda *a, **k: ([], "تعذّر")
        with ImportantWriteRig(lambda p, sy: {**good, "post_title": "تحوّل في السياسة الأميركية",
                                              "post_body": _b2_body(330)}, gap_sources=gap) as rig:
            rig.next = 91700
            d114b, _w, _t = important_write.write_article(result, item, cfg, [], 91100)
        check("(g114) المولّد لم يُعِد عنوانًا ← يبقى عنوان الكاتب",
              d114b is not None and d114b["arabic"]["post_title"] == "تحوّل في السياسة الأميركية")
    finally:
        headlines_mod.headlines_for_post = real_hl
    check("(g114) publisher_ar: الأسماء الجديدة بالعربية",
          [important_write.publisher_ar(n, cfg) for n in ("Cyprus Mail", "UA.NEWS", "The Sunday Guardian",
                                                          "The Express Tribune", "Anadolu Agency", "AA", "Time")]
          == ["سايبرس ميل", "يو إيه نيوز", "صنداي غارديان", "إكسبرس تريبيون", "الأناضول", "الأناضول", "تايم"])
    check("(g114) الطول: تحت 150 أو فوق 540 تنبيه فقط، وبينهما لا شيء",
          important_write.length_reasons({"post_body": _b2_body(40)}, cfg) != []
          and important_write.length_reasons({"post_body": _b2_body(200)}, cfg) == []
          and important_write.length_reasons({"post_body": _b2_body(900)}, cfg) != [])


def test_important_1316_guards() -> None:
    """Issue #1316 (B6): g116–g122 على الشاهد الحقيقي tests/fixtures/important/1312.json — تاريخ موثوق للمصدر،
    استبعاد صفحات الفهارس، تحويل النقل الحرفي المنسوب إلى اقتباس، أسماء كيانات، واستبدال أسماء الناشرين
    الحسّاس للحالة."""
    import json
    from unittest import mock

    from src import important, important_gap, important_write, verify_draft
    from tests.helpers import IMPORTANT_FIXTURES

    cfg = load_config()
    icfg = cfg.get("important", {}) or {}
    real = json.loads((IMPORTANT_FIXTURES / "1312.json").read_text(encoding="utf-8"))
    items = {i["kind"]: i for i in real["article_items"]}
    p809 = next(p for p in real["points"] if p["id"] == "80943d3f4957")
    state_ev = next(e for e in p809["evidence"] if "state.gov" in e["link"])

    # ── g116) ترتيب التاريخ: الرابط ← نتيجة جوجل ← htmldate، والمستقبلي/القديم يُهمل ──
    def dated(link, html=None, art=None, found="__real__"):
        s_ = important._PointSearch(cfg, "")
        if art:
            s_.art_dates[link] = art
        if html is not None:
            if found == "__real__":
                s_._keep_html(link, html)
            else:
                with mock.patch("htmldate.find_date", return_value=found):
                    s_._keep_html(link, html)
        return s_.published_of({"link": link})

    aj = "https://www.aljazeera.net/news/2026/9/29/%D8%A8%D9%8A%D8%B3%D9%86%D8%AA"
    check("(g116) تاريخ في الرابط /2026/9/29/ يغلب htmldate (2022-04-01) ← 2026-09-29",
          dated(aj, "<html><body>x</body></html>", found="2022-04-01") == "2026-09-29")
    html_noise = ("<html><body><article><p>بيان عن عقوبات على شبكة تمويل.</p></article>"
                  "<ul><li><a href='/a'>April 1, 2022</a></li><li><a href='/b'>Related story</a></li></ul>"
                  "<footer>© 2022</footer></body></html>")
    check("(g116) HTML لا تاريخ فيه إلا «April 1, 2022» في روابط ذات صلة و«© 2022» والرابط بلا تاريخ ← فارغ",
          dated("https://www.state.gov/translations/x/sanctions", html_noise) == "")
    meta = ('<html><head><meta property="article:published_time" content="2026-03-05T10:00:00Z"></head>'
            "<body><p>خبر</p></body></html>")
    check("(g116) meta article:published_time ← 2026-03-05",
          dated("https://x.example/news/story", meta) == "2026-03-05")
    check("(g116) تاريخ الرابط بعد اليوم يُهمل وينتقل إلى تاريخ جوجل",
          dated("https://x.example/2099/1/1/story", art="2026-02-01") == "2026-02-01")
    check("(g116) تاريخ قبل min_doc_year يُهمل ← فارغ؛ وصيغ الرابط الأخرى",
          dated("https://x.example/1990/1/1/story") == ""
          and important.url_date("https://x.example/a/2026-04-02-story") == "2026-04-02"
          and important.url_date("https://x.example/a/story-20260402.html") == "2026-04-02"
          and important.url_date("https://x.example/a/id12026040299") == "")
    check("(g116) min_doc_year في config وتعليمة «تاريخ غير معروف» في common",
          icfg.get("min_doc_year") == 2000
          and "مقتطف عليه (تاريخ غير معروف): لا تذكر لحدثه تاريخًا إلا إن ورد التاريخ في المقتطف نفسه"
          in icfg["article_instructions"]["common"])

    # ── g117) مقتطف state.gov الحقيقي بلا تاريخ موثوق ← «(تاريخ غير معروف)» والتعليمة مرسَلة ──
    members = [p809]
    grounded = important_write.article_grounded(members, [], cfg)
    state_texts = [s_["text"] for f in grounded for s_ in f["sources"] if s_["link"] == state_ev["link"]]
    check("(g117) مدخل الكاتب لمقتطف state.gov يحمل «(تاريخ غير معروف)»",
          bool(state_texts) and all(t.endswith("(تاريخ غير معروف)") for t in state_texts), state_texts)
    sent = important_write.article_instructions(real, items["verified"], members, [], cfg)
    check("(g117) والتعليمة موجودة في التعليمات المرسَلة", "مقتطف عليه (تاريخ غير معروف)" in sent)

    # ── g118) صفحات الفهارس ──
    bbc_topics = "https://www.bbc.com/arabic/topics/cdr56gdp0w1t"
    check("(g118) /topics/ مستبعد، المقال باقٍ، ونطاق فيه topics بلا المسار باقٍ",
          important.is_listing_url(bbc_topics, icfg)
          and not important.is_listing_url("https://www.bbc.com/arabic/articles/c627zld10y0o", icfg)
          and not important.is_listing_url("https://topics.example.com/news/1", icfg))

    class StubSearch:
        docs: list = []

        def __init__(self, cfg_, body):
            self.brave = {"requests": 0, "skipped": None}
            self.days = 21

        def resolve_link(self, link):
            return link, True

        def run(self, *a, **k):
            return [], list(StubSearch.docs), []

        def run_brave(self, *a, **k):
            return [], [], []

        def published_of(self, d):
            return ""

    saved = items["nearest"]["gap_sources"]
    StubSearch.docs = [{"name": g["publisher"], "link": g["link"], "text": g["excerpt"]} for g in saved]
    real_search = important._PointSearch
    important._PointSearch = StubSearch
    try:
        stats: dict = {}
        out = important_gap.search_gap([{"question": "س؟", "query_ar": "حزب الله", "query_en": ""}],
                                       cfg, [], stats)
    finally:
        important._PointSearch = real_search
    kept = [g["link"] for g in out]
    check("(g118) إعادة فلتر البحث المكمِّل على gap_sources المحفوظة لـnearest ترمي رابط bbc topics وحده",
          bbc_topics not in kept and stats["listing"] == 1
          and all(g["link"] in kept for g in saved if g["link"] != bbc_topics), (kept, stats))
    check("(g118) rules_version 7", icfg.get("rules_version") == 7)

    # ── g119–g121) النقل الحرفي المنسوب ──
    publisher = "وزارة الخارجية الأميركية"
    sentence = ("ففي أول أبريل/نيسان 2022، قالت وزارة الخارجية الأميركية إن الهجوم المتهور الذي شنه حزب الله على "
                "إسرائيل يثبت مرة أخرى أنه يمنح الأولوية لممارسة الإرهاب نيابة عن النظام الإيراني، على حساب "
                "سلامة الشعب اللبناني وأمنه.")
    src = [(publisher, state_ev["excerpt"])]
    docs = [{"name": publisher, "text": state_ev["excerpt"]}]

    def originality(body):
        ok, _why, _n = verify_draft.check_originality(body, "", docs, 12, allowed_quotes=[], exempt_texts=[])
        return ok

    written = {"post_title": "ت", "post_body": f"افتتاحية قصيرة.\n\n{sentence}"}
    check("(g119) قبل التحويل: النسخ الحرفي يُبلَّغ عنه (ضابطة)", not originality(written["post_body"]))
    conv, starts = important_write.quote_attributed_copies(written, src, cfg)
    body = conv["post_body"]
    check("(g119) المقطع بعد «إن» صار بين « » وقبله «إن» خارجه",
          "قالت وزارة الخارجية الأميركية إن «الهجوم المتهور" in body and body.rstrip().endswith("وأمنه»."), body)
    check("(g119) quote_violations فارغة وفحص الأصالة لا يبلّغ عن الجملة",
          important_write.quote_violations(body, [state_ev["excerpt"]]) == [] and originality(body), body)
    warn = icfg["quote_converted_warning"].format(start=starts[0]) if starts else ""
    check("(g119) تنبيه ℹ️ بأول 12 كلمة، والعنوان لا يُمسّ",
          len(starts) == 1 and warn.startswith("ℹ️ نقل حرفي منسوب حُوِّل إلى اقتباس: «الهجوم المتهور")
          and conv["post_title"] == "ت", (starts, warn))
    again, starts2 = important_write.quote_attributed_copies(conv, src, cfg)
    check("(g119) المقطع داخل « » أصلًا ← لا تحويل ثانٍ", starts2 == [] and again["post_body"] == body)

    unattributed = {"post_title": "ت", "post_body": sentence.replace(publisher, "الإدارة الأميركية")}
    conv120, starts120 = important_write.quote_attributed_copies(unattributed, src, cfg)
    check("(g120) الجملة بلا ذكر للخارجية ← لا تحويل ويبقى سبب الأصالة",
          starts120 == [] and conv120 == unattributed and not originality(conv120["post_body"]))

    bbc_gap = next(g for g in saved if g["link"] == bbc_topics)
    bbc_sentence = ("تتواصل الضغوط الأميركية على حزب الله في إطار مسار بدأ في 19 حزيران/يونيو 2025، حين زار توم "
                    "براك بيروت لأول مرة حاملاً خريطة طريق أميركية مفصلة، وتضمّنت مطالب واضحة بنزع سلاح حزب الله "
                    "والفصائل المسلحة كافة في لبنان بشكل كامل بحلول تشرين الثاني/نوفمبر 2025.")
    conv121, starts121 = important_write.quote_attributed_copies(
        {"post_title": "ت", "post_body": bbc_sentence}, [("بي بي سي", bbc_gap["excerpt"])], cfg)
    check("(g121) جملة بي بي سي في nearest بلا ذكر بي بي سي ← لا تحويل", starts121 == [], conv121["post_body"])

    # ── g122) أسماء كيانات وحسّاسية الحالة ──
    check("(g122أ) pivot «لبنان» يقبل مقتطفًا فيه Lebanon، و«الحوثيون» يقبل Houthis",
          important_gap.mentions_pivot("Hezbollah said Lebanon would not disarm.", ["لبنان"], icfg)
          and important_gap.mentions_pivot("The Houthis launched a missile.", ["الحوثيون"], icfg)
          and important_gap.mentions_pivot("Yemen talks resumed.", ["اليمن"], icfg)
          and important_gap.mentions_pivot("Hamas leaders met.", ["حماس"], icfg)
          and not important_gap.mentions_pivot("Greece bought arms.", ["لبنان"], icfg))
    out122, _w = important_write.arabize_publishers(
        {"post_title": "Time ينشر", "post_body": "نشرت Time خبرًا من AA. في ذلك time مبكر وهذا aa صغير."},
        ["Time", "AA"], cfg)
    check("(g122ب) «Time» ← «تايم»، «AA» ← «الأناضول»، و«time» و«aa» داخل المتن تبقيان",
          out122["post_title"] == "تايم ينشر"
          and out122["post_body"] == "نشرت تايم خبرًا من الأناضول. في ذلك time مبكر وهذا aa صغير.", out122)


def test_names_placeholder_guards() -> None:
    """g115 (Issue #1315): الرمز الوسيط في names.normalize_names كان الرقم نفسه فكان يفسد كل رقم مطابق
    في النص («2025» ← «2أمريكي25»). تُختبر عبر store.save_draft الفعلي لا normalize_names وحدها."""
    import json
    from datetime import datetime, timezone
    from src import names, names_learn

    real_load_config = store.load_config

    def _save(id_: str, text: str, cfg: dict) -> str:
        store.load_config = lambda path=None: cfg
        draft = {
            "id": id_, "status": "pending", "score": 1.0, "bucket": "serious",
            "state_media": False, "origin": "news",
            "source": {"title": text, "link": f"https://example.com/{id_}",
                       "publisher": "س", "publishers": ["س"]},
            "arabic": {"post_title": text, "body": text, "caption": "",
                       "category": "", "urgent": False},
            "caption": "", "headlines": [], "headline_selected": 0,
        }
        p = store.save_draft(draft)
        return json.loads(p.read_text(encoding="utf-8"))["arabic"]["post_title"]

    def _clear() -> None:
        names.SEEN_FILE.unlink(missing_ok=True)
        names_learn.LEARNED_FILE.unlink(missing_ok=True)

    _clear()
    try:
        # أ) معجم متعلَّم
        now = datetime.now(timezone.utc).isoformat()
        names_learn.save_learned({
            "entries": {"أمريكي": {
                "variants": ["أميركي"], "counts": {"أمريكي": 70, "أميركي": 9},
                "learned_at": now, "verdict": "same_name"}},
            "rejected_pairs": [], "last_run": now})
        got = _save("g115a00000001", "في 7 أغسطس 2025 قال مسؤول أميركي إن 200 مليون دولار وصلت", {})
        check("(g115أ) معجم متعلَّم: الأرقام سليمة والاسم موحَّد",
              got == "في 7 أغسطس 2025 قال مسؤول أمريكي إن 200 مليون دولار وصلت", got)
        _clear()

        # ب) معجم يدوي
        got = _save("g115b00000002", "قال ترمب 10 كلمات عام 2010",
                    {"names": {"aliases": {"ترامب": ["ترمب"]}}})
        check("(g115ب) معجم يدوي: «10» و«2010» سليمة",
              got == "قال ترامب 10 كلمات عام 2010", got)

        # ج) مدخل ببديلين وأرقام 0 و1 و10
        got = _save("g115c00000003", "نتانياهو 0 ونيتنياهو 1 و10 مرات",
                    {"names": {"aliases": {"نتنياهو": ["نتانياهو", "نيتنياهو"]}}})
        check("(g115ج) بديلان معًا: الأرقام 0 و1 و10 سليمة والاسمان موحَّدان",
              got == "نتنياهو 0 ونتنياهو 1 و10 مرات", got)

        # د) أرقام هندية
        got = _save("g115d00000004", "عام ٢٠٢٥ قال ترمب",
                    {"names": {"aliases": {"ترامب": ["ترمب"]}}})
        check("(g115د) الأرقام الهندية سليمة", got == "عام ٢٠٢٥ قال ترامب", got)
    finally:
        store.load_config = real_load_config
        _clear()


def test_names_audit_1322_guards() -> None:
    """حارس المحاذاة وتوحيد رسوم الأصل الواحد في تدقيق الأسماء (Issue #1322، g123–g127)؛ الشواهد
    نسخ حرفية من drafts/2026-10-09 في tests/fixtures/names_audit/1322/. الكشف وBrave مزيَّفان فقط."""
    import json
    from pathlib import Path

    from src import names_audit

    cfg = load_config()
    fx = Path(__file__).parent / "fixtures" / "names_audit" / "1322"
    for name in ("9e692088a75a", "9cc353cd1d4d", "8ec39e3d9456"):
        check(f"g123: الشاهد {name} موجود", (fx / f"{name}.json").exists())

    def hit(name: str) -> list:
        return [names_audit_hit("https://www.aljazeera.net/a", name),
                names_audit_hit("https://www.alaraby.co.uk/b", name)]

    def simple(text: str) -> dict:
        d = names_audit_draft()
        d["arabic"].update({"analysis": text, "post_body": text, "post_title": "عنوان", "image_headline": "عنوان"})
        d["caption"], d["headlines"] = text, [text]
        return d

    # g123) مرشّح ليس رسمًا للاسم نفسه ← يُرفض والنص بلا تغيير وتنبيه
    d = simple("قال سلتشوك بايراقتاروغلو إن الأمر كذلك ورئيس أركان الجيش التركي حاضر.")
    before = d["caption"]
    item = names_audit_doubt("سلتشوك بايراقتاروغلو", "Selçuk Bayraktaroğlu", ["أركان الجيش التركي"])
    with NamesAuditRig([item], {"أركان الجيش التركي": hit("أركان الجيش التركي")}) as rig:
        names_audit.run(d, ["Selçuk Bayraktaroğlu spoke."], cfg)
        exists = names_audit.VERIFIED_FILE.exists()
    check("g123: النص بلا تغيير", d["caption"] == before, d["caption"])
    check("g123: تنبيه «اسم لم يُحسم» بسبب الحارس",
          any(w.startswith("اسم لم يُحسم: سلتشوك") and "ليس رسمًا آخر للاسم نفسه" in w for w in d.get("warnings", [])),
          d.get("warnings"))
    check("g123: لا بحث ولا حفظ", rig.http_calls == [] and not exists, rig.http_calls)

    # g124) المحاذاة: الاسم الأول يبقى، والملتصق يطابق المفصول
    check("g124: «عباس عراقتشي» + «عراقجي» = «عباس عراقجي»",
          names_audit.align_spelling("عباس عراقتشي", "عراقجي", cfg) == "عباس عراقجي")
    check("g124: «هكان فيدان» + «هاكان فيدان» مقبول",
          names_audit.align_spelling("هكان فيدان", "هاكان فيدان", cfg) == "هاكان فيدان")
    check("g124: «إماموغلو» + «إمام أوغلو» مقبول",
          names_audit.align_spelling("إماموغلو", "إمام أوغلو", cfg) == "إمام أوغلو")
    d = simple("تحدث عباس عراقتشي أمس.")
    item = names_audit_doubt("عباس عراقتشي", "Abbas Araghchi", ["عراقجي"])
    with NamesAuditRig([item], {"عراقجي": hit("عراقجي")}) as rig:
        names_audit.run(d, ["Abbas Araghchi spoke."], cfg)
    check("g124: عبر التدقيق يبقى الاسم الأول", d["caption"] == "تحدث عباس عراقجي أمس.", d["caption"])

    # g125) رسمان للأصل نفسه في المسودة: اعتماد أحدهما يوحّد الآخر
    d = simple("قال حقان فيدان إن الحدث مهم. وأضاف هكان فيدان أيضًا.")
    items = [names_audit_doubt("هكان فيدان", "Hakan Fidan", ["هاكان فيدان"]),
             dict(arabic="حقان فيدان", latin="Hakan Fidan", gender="male", verdict="sound")]
    with NamesAuditRig(items, {"هاكان فيدان": hit("هاكان فيدان")}) as rig:
        names_audit.run(d, ["Hakan Fidan said it."], cfg)
    check("g125: لا يبقى «حقان» ولا «هكان»", "حقان" not in d["caption"] and "هكان" not in d["caption"]
          and d["caption"].count("هاكان فيدان") == 2, d["caption"])

    # g126) مدخل محفوظ يفشل الحارس ← يُتجاهل: لا تصحيح ولا names_note
    d = simple("قال سلتشوك بايراقتاروغلو شيئًا.")
    before = d["caption"]
    entry = dict(latin="Selçuk Bayraktaroğlu", arabic="أركان الجيش التركي", sources=["x.net"],
                 source_kind="بحث", at="2026-10-08T00:00:00+00:00", wrong=["سلتشوك بايراقتاروغلو"])
    with NamesAuditRig([], {}) as rig:
        names_audit.save_verified(dict(entries={"selcuk bayraktaroglu": entry}))
        names_audit.run(d, ["Selçuk Bayraktaroğlu said."], cfg)
        note = names_audit.names_note(["Selçuk Bayraktaroğlu said."], cfg)
    check("g126: لا تصحيح من المدخل الفاسد", d["caption"] == before, d["caption"])
    check("g126: لا names_note", note == "", note)

    # g127) المعجم اليدوي عبر store.save_draft الفعلي
    real_load = store.load_config
    try:
        store.load_config = lambda path=None: cfg
        d = simple("التقى أكرم إماموغلو بالوزير عباس عراقتشي.")
        d.update({"id": "g127000000001", "status": "pending", "origin": "news"})
        d["arabic"]["body"] = d["arabic"]["post_title"] = d["caption"]
        p = store.save_draft(d)
        got = json.loads(p.read_text(encoding="utf-8"))["arabic"]["body"]
    finally:
        store.load_config = real_load
    check("g127: «إماموغلو» ← «إمام أوغلو» و«عراقتشي» ← «عراقجي»",
          got == "التقى أكرم إمام أوغلو بالوزير عباس عراقجي.", got)


def test_analysis_editor_guards() -> None:
    """«المحرر الأخير» لمقالات التحليل وفحوصه الآلية (Issue #1326، g128–g140). الشواهد نسخ حرفية من
    drafts/2026-10-09 في tests/fixtures/analysis/1322/ (المسودات وحدها). نموذج المحرر مزيَّف:
    server_tool_use ثم report_review؛ والكود الحقيقي هو الذي يطبّق ويفحص ويعرض ويبوّب."""
    import copy
    import json
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    from src import imagesearch, names_audit, review
    from src import youtube_article as ya
    from src import youtube_editor as ye
    from tests.helpers import editor_response

    cfg = load_config()
    fx = Path(__file__).parent / "fixtures" / "analysis" / "1322"

    def load(name: str) -> dict:
        return copy.deepcopy(json.loads((fx / f"{name}.json").read_text(encoding="utf-8")))

    for n in ("8ec39e3d9456", "d96e19b97bd2", "9e692088a75a", "9cc353cd1d4d"):
        check(f"g128: الشاهد {n} موجود", (fx / f"{n}.json").exists())

    pts = [{"channel": "هابر ترك", "speaker": "ناطق", "video_url": "https://www.youtube.com/watch?v=abc",
            "timestamp": 754, "statement": "قول", "type": "claim", "video_published": "2026-10-09"},
           {"channel": "سي إن إن ترك", "speaker": "محمد شيمشك، خبير الشؤون اليمنية",
            "video_url": "https://www.youtube.com/watch?v=xyz", "timestamp": 90, "statement": "قول آخر",
            "type": "claim", "video_published": "2026-10-09"}]

    def reset_counter() -> None:
        imagesearch.BRAVE_USAGE_FILE.unlink(missing_ok=True)

    def run_editor(draft: dict, responses, points=None):
        """responses: قائمة ردود تُستهلك بالترتيب؛ تعيد (التقرير، سجل نداءات _create)."""
        calls: list = []
        it = iter(responses)
        saved = ye._create

        def fake(client, **kw):
            calls.append(kw)
            r = next(it)
            if isinstance(r, Exception):
                raise r
            return r
        ye._create = fake
        try:
            rev = ye.run(draft, points if points is not None else pts, cfg)
        finally:
            ye._create = saved
        return rev, calls

    # g128) العناوين تُبنى من متن المقال المكتوب
    d8 = load("8ec39e3d9456")
    sent: list = []

    class _Block:
        type = "tool_use"
        input = {"headlines": ["عنوان أول يخص إزمير؟", "عنوان ثانٍ", "عنوان ثالث"]}

    class _Resp:
        content = [_Block()]

    class _Msgs:
        def create(self, **kw):
            sent.append(kw["messages"][0]["content"])
            return _Resp()

    class _Client:
        messages = _Msgs()
    topic = {"title": "عنوان القضية القديم عن إسطنبول", "event": "", "id": "t1"}
    hl, err, _ = ya.generate_headlines(topic, pts, cfg, _Client(), article_text=d8["caption"])
    check("g128: نداء العناوين نجح", hl is not None, err)
    check("g128: رسالة النداء تحوي متن المقال", bool(sent) and "رئيس بلدية إزمير الكبرى جميل توغاي" in sent[0],
          sent[:1])
    check("g128: عنوان القضية القديم غائب عن الرسالة", bool(sent) and "عنوان القضية القديم" not in sent[0])
    check("g128: «الأول سؤال» باقية", hl is not None and hl[0].endswith("؟"))

    # g129) headline_contradicts مع fix ← طُبّق وسطر «✏️ كان/صار» ظاهر
    reset_counter()
    d = load("8ec39e3d9456")
    old_h1 = d["headlines"][0]
    new_h1 = "هل ينضم رئيس بلدية إزمير جميل توغاي إلى العدالة والتنمية فعلًا؟"
    note = {"category": "headline_contradicts", "severity": "high", "location": "headline_1",
            "original": old_h1, "fix": new_h1, "note": "العنوان يتحدث عن عمدة إسطنبول والمتن عن إزمير",
            "sources": ["https://www.aljazeera.net/x"]}
    rev, calls = run_editor(d, [editor_response([note], searches=1)])
    check("g129: الإصلاح طُبّق على العنوان 1", d["headlines"][0] == new_h1, d["headlines"])
    check("g129: الافتراضي سؤال", d["arabic"]["post_title"] == new_h1 and d["headline_selected"] == 0)
    lines = "\n".join(review.warnings_block(d))
    check("g129: سطر «✏️ كان … صار» ظاهر مع المصدر",
          "✏️ كان" in lines and new_h1 in lines and "aljazeera.net/x" in lines, lines[:300])
    check("g129: النداء الأول فيه أداة البحث والتقرير",
          [t.get("name") for t in calls[0]["tools"]] == ["web_search", "report_review"]
          and calls[0]["tools"][0]["max_uses"] == 3, calls[0]["tools"])
    check("g129: العدّاد الشهري زاد بما استُعمل", ye.search_usage() == 1, ye.search_usage())

    # g130) original غير موجود حرفيًا ← لا تطبيق وتظهر ⚠️
    d = load("8ec39e3d9456")
    before = (d["caption"], list(d["headlines"]))
    note = {"category": "headline_contradicts", "severity": "low", "location": "headline_1",
            "original": "نص ليس في المقال إطلاقًا", "fix": "بديل", "note": "ملاحظة", "sources": []}
    run_editor(d, [editor_response([note])])
    check("g130: لا تطبيق", (d["caption"], d["headlines"]) == before)
    check("g130: الملاحظة ⚠️ ظاهرة", "⚠️ ملاحظة" in "\n".join(ye.render_lines(d, cfg)), ye.render_lines(d, cfg))

    # g131) fix يُدخل «المعطيات المتداولة» ← أُلغي التطبيق وتظهر الملاحظة
    d = load("8ec39e3d9456")
    body_before = d["caption"]
    note = {"category": "vague_attribution", "severity": "low", "location": "body",
            "original": "انتقل رئيس بلدية إزمير الكبرى جميل توغاي",
            "fix": "أفادت المعطيات المتداولة بأن رئيس بلدية إزمير الكبرى جميل توغاي انتقل",
            "note": "نسبة", "sources": []}
    run_editor(d, [editor_response([note])])
    check("g131: التطبيق أُلغي والنص كما هو", d["caption"] == body_before)
    check("g131: الملاحظة معروضة", len(d["editor_review"]["notes"]) == 1 and not d["editor_review"]["applied"])

    # g132) name_doubtful ← لا تطبيق أبدًا، ⛔ مع رابط الفيديو والطابع، وpublish من الاختيار ← go2
    d = load("d96e19b97bd2")
    cap = d["caption"]
    note = {"category": "name_doubtful", "severity": "high", "location": "body",
            "original": "محمد شيمشك", "fix": "محمد شمشك", "note": "اسم المتحدث غير محسوم", "sources": []}
    run_editor(d, [editor_response([note])])
    check("g132: لا تطبيق أبدًا", d["caption"] == cap and not d["editor_review"]["applied"])
    out = "\n".join(ye.render_lines(d, cfg))
    check("g132: ⛔ مع رابط الفيديو والطابع", "⛔" in out and "watch?v=xyz&t=90s" in out, out)
    check("g132: publish من الاختيار ← go2", ye.gate_action("publish", d, 1, cfg)[0] == "go2")
    check("g132: go3 من الاختيار ← go2", ye.gate_action("go3", d, 1, cfg)[0] == "go2")
    check("g132: publish من المرحلة 2 ← go3", ye.gate_action("publish", d, 2, cfg)[0] == "go3")
    check("g132: المرحلة 3 قرارك", ye.gate_action("publish", d, 3, cfg)[0] == "publish")
    d2 = load("d96e19b97bd2")
    run_editor(d2, [editor_response([])])
    check("g132: اسم متحدث غير محسوم يمنع النشر المباشر وحده",
          ye.gate_action("publish", d2, 1, cfg)[0] == "go2" and bool(d2["editor_review"]["speaker_unresolved"]),
          d2["editor_review"])
    d3 = load("8ec39e3d9456")
    d3["name_unresolved"] = []
    run_editor(d3, [editor_response([])])
    check("g132: بلا ملاحظات ولا اسم غير محسوم ← يمضي كما هو", ye.gate_action("publish", d3, 1, cfg)[0] == "publish")

    # g133) stale_time ← بمصدر يُطبَّق، وبلا مصدر لا
    note = {"category": "stale_time", "severity": "low", "location": "body",
            "original": "قبل ساعات", "fix": "في 5 أكتوبر/تشرين الأول", "note": "الإعلان أقدم", "sources": []}
    d = load("d96e19b97bd2")
    run_editor(d, [editor_response([dict(note, sources=["https://www.aljazeera.net/s"])])])
    check("g133: بمصدر ← طُبّق", "في 5 أكتوبر/تشرين الأول" in d["caption"] and "قبل ساعات" not in d["caption"])
    d = load("d96e19b97bd2")
    run_editor(d, [editor_response([note])])
    check("g133: بلا مصدر ← لا تطبيق", "قبل ساعات" in d["caption"] and not d["editor_review"]["applied"])

    # g134) العدّاد بلغ السقف ← بلا أداة بحث والمراجعة تعمل
    reset_counter()
    imagesearch.BRAVE_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    imagesearch.BRAVE_USAGE_FILE.write_text(json.dumps({ye._usage_key(): 300}), encoding="utf-8")
    d = load("8ec39e3d9456")
    note = {"category": "other", "severity": "low", "location": "body", "original": "", "fix": "",
            "note": "ملاحظة عامة", "sources": []}
    rev, calls = run_editor(d, [editor_response([note])])
    check("g134: لا web_search في tools", [t.get("name") for t in calls[0]["tools"]] == ["report_review"],
          calls[0]["tools"])
    check("g134: المراجعة تعمل", rev["error"] is None and len(rev["notes"]) == 1 and rev["search_skipped"] == "cap")
    reset_counter()

    # g135) عطل في النداء ← المسودة محفوظة مع تنبيه
    d = load("8ec39e3d9456")
    cap = d["caption"]
    rev, _ = run_editor(d, [RuntimeError("انقطع الاتصال")])
    check("g135: لا استثناء والنص كما هو", d["caption"] == cap and bool(rev["error"]))
    check("g135: تنبيه «تعذّرت مراجعة المحرر»", any("تعذّرت مراجعة المحرر" in w for w in d["warnings"]), d["warnings"])

    # g136) عدم استدعاء report_review ← نداء ثانٍ إجباري بلا بحث
    d = load("8ec39e3d9456")
    rev, calls = run_editor(d, [editor_response([], report=False), editor_response([])])
    check("g136: نداءان", len(calls) == 2, len(calls))
    check("g136: الثاني بلا بحث وبإلزام report_review",
          [t.get("name") for t in calls[1]["tools"]] == ["report_review"]
          and calls[1]["tool_choice"] == {"type": "tool", "name": "report_review"}, calls[1])
    check("g136: لا خطأ", rev["error"] is None)

    # g137) الفقرة الأولى من d96e19b97bd2 ← رفض (نسبة مجهولة)
    d = load("d96e19b97bd2")
    v = ya.article_violations(d["caption"], cfg)
    check("g137: نسبة مجهولة مرفوضة", any("نسبة مجهولة" in x for x in v), v)

    # g138) المتحدث المسمّى لا يُحذف اسمه
    filler = " ".join(["كلمة"] * 280)

    def art(extra: str) -> str:
        return f"# عنوان تجريبي؟\n\n{filler}\n\n{extra}\n"
    v = ya.article_violations(art("وقال محلل عسكري في قناة الجزيرة إن الأمر كذلك."),
                              cfg, [{"channel": "الجزيرة", "speaker": "محلل عسكري"}])
    check("g138: «محلل عسكري» غير مسمّى ← لا مخالفة", v == [], v)
    pt = [{"channel": "الجزيرة", "speaker": "أحمد كاراهان، محلل عسكري"}]
    v = ya.article_violations(art("وقال محلل عسكري في قناة الجزيرة إن الأمر كذلك."), cfg, pt)
    check("g138: اسم مسمّى غائب ← مخالفة", len(v) == 1 and "كاراهان" in v[0], v)
    v = ya.article_violations(art("وقال أحمد كاراهان في قناة الجزيرة إن الأمر كذلك."), cfg, pt)
    check("g138: اسمه حاضر ← قبول", v == [], v)

    # g139) الزمن النسبي وعمر الفيديو
    w = ya.relative_time_warnings(art("أُعلن ذلك قبل ساعات."), cfg)
    check("g139: «قبل ساعات» ← تنبيه زمن نسبي", len(w) == 1 and "قبل ساعات" in w[0], w)
    check("g139: بلا زمن نسبي ← لا تنبيه", ya.relative_time_warnings(art("أُعلن ذلك في 5 أكتوبر."), cfg) == [])
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    old = [{"video_published": (now - timedelta(days=4)).strftime("%Y-%m-%d")}]
    sw = ya.stale_video_warning(old, cfg, now)
    check("g139: فيديو عمره 4 أيام ← تنبيه ⏳", sw is not None and "⏳" in sw and "4" in sw, sw)
    fresh = [{"video_published": (now - timedelta(days=1)).strftime("%Y-%m-%d")}]
    check("g139: فيديو عمره يوم ← لا تنبيه", ya.stale_video_warning(fresh, cfg, now) is None)

    # g140) الأرقام الهندية، وسدّ ثغرة C1
    d = load("8ec39e3d9456")
    fixed = ya.normalize_digits(d["caption"])
    check("g140: «٦٢ في المئة» ← «62 في المئة»", "62 في المئة" in fixed and "٦٢" not in fixed)
    entries = {
        "selcuk bayraktaroglu": {"latin": "Selçuk Bayraktaroğlu", "arabic": "قائد أركان الجيش التركي",
                                 "wrong": []},
        "imamoglu": {"latin": "İmamoğlu", "arabic": "إمام أوغلو", "wrong": []},
        "abbas araghchi": {"latin": "Abbas Araghchi", "arabic": "عباس عراقجي", "wrong": []}}
    usable = names_audit._usable(entries, cfg)
    check("g140: مدخل بلا wrong يختلف عدد كلمات رسمه بأكثر من 1 ← يُتجاهل",
          "selcuk bayraktaroglu" not in usable, list(usable))
    check("g140: المداخل السليمة تبقى", "imamoglu" in usable and "abbas araghchi" in usable, list(usable))


def test_editor_shared_1327_guards() -> None:
    """Issue #1331 (D1): g141–g150 — المحرر الأخير المشترك (src/editor.py) بمُكيِّفَي التحليل و«هام»، وإصلاحات «هام»
    من القضية #1327. الشواهد نسخ حرفية في tests/fixtures/important/1327/ (حكم القضية ومسودتا verified وnearest).
    نموذج المحرر مزيَّف (editor._create)؛ والكود الحقيقي هو الذي يبني الرسالة ويطبّق ويبوّب ويعرض."""
    import copy
    import json
    import re
    from datetime import datetime, timezone

    from src import (editor, imagesearch, important, important_editor, important_finalize, important_gap,
                     important_write, review)
    from src import youtube_editor as ye
    from tests.helpers import (IMPORTANT_FIXTURES, editor_response, important_b2_result,
                               important_items_marked_body)

    cfg = load_config()
    fx = IMPORTANT_FIXTURES / "1327"
    real = json.loads((fx / "1327.json").read_text(encoding="utf-8"))
    items = {i["kind"]: i for i in real["article_items"]}

    def install(name: str) -> dict:
        """يعيد المسودة الأصلية للشاهد إلى المخزن (كل حالة تبدأ من الحقيقي) ويعيد نسخة منها."""
        d = json.loads((fx / f"{name}.json").read_text(encoding="utf-8"))
        store.save_draft(copy.deepcopy(d))
        return store.load_draft(d["id"])[1]

    saved_create, saved_ye = editor._create, ye._create
    sent: list = []

    def fake_editor(notes_by_kind: dict, searches: int = 0):
        """notes_by_kind: {نوع المنشور: ملاحظات}؛ يسجّل نداءات المحرر كلها."""
        def fake(client, **kw):
            sent.append(kw)
            msg = kw["messages"][0]["content"]
            for kind, notes in notes_by_kind.items():
                if f"نوع المنشور: {kind}" in msg:
                    return editor_response(notes, searches=searches)
            return editor_response([], searches=searches)
        return fake

    def reset_counter() -> None:
        imagesearch.BRAVE_USAGE_FILE.unlink(missing_ok=True)

    reset_counter()
    try:
        # g141) المحرر المشترك بمُكيِّف التحليل: الغلاف الرقيق والمُكيِّف والإعداد العام (وg128–g140 تمرّ بلا تعديل)
        check("g141: فئتا stale_as_new وsibling_duplicate في الفئات، وsibling_duplicate لا تُطبَّق أبدًا",
              "stale_as_new" in editor.CATEGORIES and "sibling_duplicate" in editor.CATEGORIES
              and "sibling_duplicate" in editor.NEVER_APPLIED)
        check("g141: كتلة editor عامة (paths وsystem_extra وstale_days 14) وyoutube.review.editor حُذفت",
              cfg.path("youtube.review.editor") is None
              and cfg.path("editor.paths") == {"analysis": True, "important": True, "news": True,
                                               "breaking": True, "reel": True}
              and cfg.path("editor.stale_days") == 14 and cfg.path("editor.monthly_search_cap") == 300
              and set(cfg.path("editor.system_extra")) >= {"analysis", "important"}
              and "قارن تاريخ كل حدث بتاريخ اليوم المعطى" in cfg.path("editor.system"),
              cfg.path("editor.paths"))
        check("g141: youtube_editor غلاف رقيق على المحرر المشترك (مُكيِّف التحليل)",
              ye.ADAPTER.name == "analysis" and ye.gate_action is editor.gate_action
              and ye.render_lines is editor.render_lines and not hasattr(ye, "_converse"))
        fxa = IMPORTANT_FIXTURES.parent / "analysis" / "1322" / "8ec39e3d9456.json"
        da = json.loads(fxa.read_text(encoding="utf-8"))
        da2 = copy.deepcopy(da)
        note_a = {"category": "headline_contradicts", "severity": "high", "location": "headline_1",
                  "original": da["headlines"][0], "fix": "عنوان بديل مصحَّح", "note": "ملاحظة", "sources": []}
        pts_a = [{"channel": "هابر ترك", "speaker": "ناطق", "video_url": "https://www.youtube.com/watch?v=abc",
                  "timestamp": 1, "statement": "قول", "type": "claim", "video_published": "2026-10-09"}]
        ye._create = lambda client, **kw: editor_response([note_a])
        editor._create = lambda client, **kw: editor_response([note_a])
        r1 = ye.run(da, pts_a, cfg)
        r2 = editor.run(da2, ye.ADAPTER, pts_a, cfg)
        check("g141: الغلاف والمحرر المشترك بمُكيِّف التحليل يعطيان النتيجة نفسها",
              da["headlines"] == da2["headlines"] and da["headlines"][0] == "عنوان بديل مصحَّح"
              and len(r1["applied"]) == len(r2["applied"]) == 1, (da["headlines"], da2["headlines"]))
        ye._create = saved_ye
        reset_counter()

        # g142) رسالة المحرر لـd4dbc7461dc2: الشقيق والتاريخ والخبر الرئيسي وتاريخ كل مصدر
        install("e4aac1357cd5")
        near = install("d4dbc7461dc2")
        sibling = json.loads((fx / "e4aac1357cd5.json").read_text(encoding="utf-8"))
        sent.clear()
        editor._create = fake_editor({})
        important_editor.review(near, real, items["nearest"], cfg)
        msg = sent[0]["messages"][0]["content"] if sent else ""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sources_part = msg.split("مقتطفات المصادر المعطاة للكاتب", 1)[-1].split("المنشورات الشقيقة", 1)[0]
        dated = sources_part.count("(نُشر:") + sources_part.count("(تاريخ غير معروف)")
        check("g142: الرسالة فيها تاريخ اليوم والخبر الرئيسي ونوع المنشور",
              f"تاريخ اليوم: {today}" in msg and real["main_story"] in msg and "نوع المنشور: nearest" in msg,
              msg[:200])
        check("g142: عنوان الشقيق e4aac1357cd5 ومتنه ومعرّفه في الرسالة",
              sibling["arabic"]["post_title"] in msg and sibling["arabic"]["post_body"][:60] in msg
              and "[e4aac1357cd5]" in msg, msg[-300:])
        n_sources = len(re.findall(r"^- [^\n|]+ \| https?://", sources_part, flags=re.M))
        check("g142: لكل مصدر «(نُشر: …)» أو «(تاريخ غير معروف)»",
              n_sources > 1 and dated >= n_sources, (dated, n_sources))

        # g143) stale_as_new على العنوان ← يُطبَّق على العنوان وعلى post_title (المختار) وسطر «✏️ كان/صار»
        d = install("e4aac1357cd5")
        old_h = d["headlines"][0]
        new_h = "الولايات المتحدة فرضت عقوبات في آذار/مارس على شبكة مالية عالمية تدعم حزب الله"
        note = {"category": "stale_as_new", "severity": "low", "location": "headline_1", "original": old_h,
                "fix": new_h, "note": "عقوبات 20 آذار/مارس عمرها أكثر من 14 يومًا", "sources": []}
        editor._create = fake_editor({"verified": [note]})
        out = important_editor.review(d, real, items["verified"], cfg)
        again = store.load_draft(d["id"])[1]
        lines = "\n".join(review.warnings_block(again))
        from src import date_style as _ds
        exp_h = _ds.normalize_text(new_h, cfg)
        check("g143: طُبّق على العنوان 1 وعلى post_title وعلى caption (بصيغة الأشهر الموحَّدة)",
              again["headlines"][0] == exp_h and again["arabic"]["post_title"] == exp_h
              and again["caption"].startswith(exp_h) and out["headlines"][0] == exp_h, again["headlines"])
        check("g143: fix المطبَّق في editor_review.applied مطبَّع بصيغة الأشهر فيطابق النص المحفوظ",
              again["editor_review"]["applied"][0]["fix"] == exp_h and exp_h != new_h,
              again["editor_review"]["applied"])
        check("g143: سطر «✏️ كان … صار» ظاهر في عرض المراجعة", "✏️ كان" in lines and exp_h in lines, lines[:300])
        d = install("e4aac1357cd5")
        body_note = dict(note, location="body", original="عقوبات جديدة", fix="عقوبات")
        editor._create = fake_editor({"verified": [body_note]})
        important_editor.review(d, real, items["verified"], cfg)
        again = store.load_draft(d["id"])[1]
        check("g143: stale_as_new في المتن لا تُطبَّق (العناوين وh1 وحدها)",
              not again["editor_review"]["applied"] and len(again["editor_review"]["notes"]) == 1
              and again["arabic"]["post_body"] == d["arabic"]["post_body"])

        # g144) sibling_duplicate high ← لا تطبيق، وpublish من قضية الترشيح ← go2 مع التعليق
        d = install("d4dbc7461dc2")
        dup = {"category": "sibling_duplicate", "severity": "high", "location": "body", "original": "",
               "fix": "", "note": "يعيد بيان 20 مارس نفسه الذي بُني عليه المنشور الأول", "sources": []}
        editor._create = fake_editor({"nearest": [dup]})
        important_editor.review(d, real, items["nearest"], cfg)
        again = store.load_draft(d["id"])[1]
        check("g144: لا تطبيق والملاحظة high معروضة",
              not again["editor_review"]["applied"] and again["arabic"]["post_body"] == d["arabic"]["post_body"]
              and again["editor_review"]["notes"][0]["severity"] == "high")
        check("g144: publish/go3 من المرحلة 1 ← go2",
              editor.gate_action("publish", again, 1, cfg)[0] == "go2"
              and editor.gate_action("go3", again, 1, cfg)[0] == "go2")

        good = {"category": "عالم", "hashtags": ["هام"], "image_query_en": "news story",
                "post_title": "تطوّرات الخبر الرئيسي بين المؤكَّد والمتداول",
                "image_headline": "تطوّرات الخبر الرئيسي"}
        from tests.helpers import fresh_date
        gap_src = [{"publisher": "BBC", "link": "https://www.bbc.com/arabic/a1", "published": fresh_date(),
                    "excerpt": "بي بي سي: تفصيل مؤكد عن الخبر الرئيسي وأرقامه.", "question": "س؟"}]
        writes: list = []

        def respond(prompt, system):
            writes.append(1)
            return {**good, "post_title": f"عنوان منشور رقم {len(writes)}",
                    "post_body": _b2_body(330, tag=f"ش{len(writes)}x")}

        res = important_b2_result(88800)
        its = {i["kind"]: i for i in res["article_items"]}
        for i in res["article_items"]:
            i["selection_issue"] = 88810
        important.save(res)
        body = important_items_marked_body(res, {its["nearest"]["id"]: "publish", its["verified"]["id"]: "go2",
                                                 its["refuted"]["id"]: "go2"}, cfg)
        editor._create = fake_editor({"nearest": [dup]})
        sent.clear()
        with ImportantWriteRig(respond, gap_sources=gap_src) as rig:
            rig.next = 88900
            code = important_finalize.finalize(88810, body, cfg)
            near_id = important.load_saved(88800)["article_items"][1]["draft_id"]
            stage2 = [c for c in rig.created if c["labels"] == ["pending-review"]]
            check("g144: قضية الترشيح ← nearest المعلَّم publish حُوِّل إلى go2 مع تعليق، ولم يُنشر شيء",
                  code == 0 and not rig.published
                  and any("حُوِّل" in t and "تنبيهات فحص" in t for _n, t in rig.comments)
                  and len(stage2) == 1 and f"<!-- draft:{near_id} -->" in stage2[0]["body"],
                  (code, rig.comments, [c["labels"] for c in rig.created]))
            order = [s["messages"][0]["content"].split("نوع المنشور: ")[1].split()[0] for s in sent]
            check("g144: المحرر مرّ بالمنشورات الثلاثة بترتيب verified ← nearest ← refuted بعد كتابتها كلها",
                  len(writes) == 3 and order == ["verified", "nearest", "refuted"], (len(writes), order))

        # g145) البحث المكمِّل لـnearest يستبعد روابط الشقيق
        state_link = next(g["link"] for g in items["verified"]["gap_sources"] if "state.gov" in g["link"])
        r145 = copy.deepcopy(real)
        it145 = next(i for i in r145["article_items"] if i["kind"] == "nearest")
        members145 = important_write.item_members(r145, it145)
        check("g145: روابط الشقيق تشمل state.gov لـnearest وتخلو لـverified",
              state_link in important_gap.sibling_links(r145, it145)
              and important_gap.sibling_links(r145, items["verified"]) == set())

        class Stub:
            def __init__(self, cfg_, body_):
                self.brave = {"requests": 0, "skipped": None}
                self.days = 21

            def resolve_link(self, link):
                return link, True

            def run(self, *a, **k):
                docs = [{"name": g["publisher"], "link": g["link"], "text": g["excerpt"]}
                        for g in items["verified"]["gap_sources"]]
                return [], docs, []

            def run_brave(self, *a, **k):
                return [], [], []

            def published_of(self, d_):
                return ""

        real_search, real_q = important._PointSearch, important_gap.gap_questions
        important._PointSearch = Stub
        important_gap.gap_questions = lambda *a, **k: [{"question": "س؟", "query_ar": "حزب الله", "query_en": ""}]
        try:
            got145 = important_gap.gather(r145, it145, members145, cfg)
            it_v = copy.deepcopy(items["verified"])
            got_v = important_gap.gather(r145, it_v, important_write.item_members(r145, it_v), cfg)
        finally:
            important._PointSearch, important_gap.gap_questions = real_search, real_q
        check("g145: nearest — رابط state.gov مستبعد وgap_dropped_sibling ≥ 1",
              all(g["link"] != state_link for g in got145) and it145.get("gap_dropped_sibling", 0) >= 1,
              ([g["link"] for g in got145], it145.get("gap_dropped_sibling")))
        check("g145: verified نفسه لا يُستبعد منه شيء (gap_dropped_sibling = 0)",
              it_v.get("gap_dropped_sibling") == 0 and any(g["link"] == state_link for g in got_v),
              it_v.get("gap_dropped_sibling"))

        # g146) النقل الحرفي المنسوب: «بيان وزارة الخارجية» ← اقتباس؛ وبعد «في» لا
        excerpt = next(g["excerpt"] for g in items["verified"]["gap_sources"] if "state.gov" in g["link"])
        publisher = "U.S. Department of State"
        s_verified = ("وبحسب بيان وزارة الخارجية، فإن الهجوم المتهور الذي شنه حزب الله على إسرائيل يثبت مرة أخرى "
                      "أنه يمنح الأولوية لممارسة الإرهاب نيابة عن النظام الإيراني، على حساب سلامة الشعب "
                      "اللبناني وأمنه.")
        conv, starts = important_write.quote_attributed_copies(
            {"post_title": "ت", "post_body": s_verified}, [(publisher, excerpt)], cfg)
        check("g146: verified — «فإن «الهجوم المتهور…»» بعد التحويل",
              "فإن «الهجوم المتهور" in conv["post_body"] and conv["post_body"].rstrip().endswith("وأمنه».")
              and len(starts) == 1, conv["post_body"])
        s_near = ("وأوضح البيان أن وزارة الخارجية الأميركية صنّفت حزب الله ككيان إرهابي بموجب الأمر التنفيذي نفسه "
                  "في 31 تشرين الأول/أكتوبر 2001، وكمنظمة إرهابية أجنبية بموجب المادة 219 من قانون الهجرة "
                  "والجنسية بتاريخ 8 تشرين الأول/أكتوبر 1997.")
        conv2, starts2 = important_write.quote_attributed_copies(
            {"post_title": "ت", "post_body": s_near}, [(publisher, excerpt)], cfg)
        check("g146: nearest — المقطع بعد «في» لا يتحوّل (لا اقتباس مبتور)",
              starts2 == [] and "«" not in conv2["post_body"], conv2["post_body"])
        colon = "قال بيان وزارة الخارجية: " + s_verified.split("فإن ", 1)[1]
        check("g146: ما بعد نقطتين يتحوّل",
              important_write.quote_attributed_copies({"post_title": "ت", "post_body": colon},
                                                      [(publisher, excerpt)], cfg)[1] != [])

        # g147) الاسم المركّب الملتصق بحرف العطف، وفقرة بيسنت
        check("g147: «وحزب الله» و«لحزب الله» تطابقان «حزب الله»، و«حزب الله» وحدها كما كانت",
              important._mentions("المنظومة التابعة لإيران وحزب الله في لبنان", ["حزب الله"])
              and important._mentions("دعم لحزب الله", ["حزب الله"])
              and important._mentions("هاجم حزب الله", ["حزب الله"])
              and not important._mentions("واشنطن وحزبا الله", ["حزب الله"]))
        nd = json.loads((fx / "d4dbc7461dc2.json").read_text(encoding="utf-8"))
        pivots = important_gap.pivot_entities(important_write.item_members(real, items["nearest"]))
        offs = important_write.off_topic_warnings(
            {"post_title": nd["arabic"]["post_title"], "post_body": nd["arabic"]["post_body"]}, pivots, cfg)
        check("g147: فقرة بيسنت (فيها «وحزب الله») لا تُنبَّه «خارج الموضوع»",
              not any("بيسنت" in w for w in offs), (pivots, offs))

        # g148) توحيد اسم المتحدث عبر store.save_draft الفعلي
        real_load = store.load_config
        try:
            store.load_config = lambda path=None: cfg
            d148 = {"id": "g148000000001", "status": "pending", "origin": "important", "score": 1.0,
                    "bucket": "serious", "state_media": False,
                    "source": {"title": "ت", "link": "https://example.com/g148", "publisher": "س",
                               "publishers": ["س"]},
                    "arabic": {"post_title": 'قال توماس "تومي" بيغوت', "body": "ب", "caption": "ت", "urgent": False},
                    "caption": 'المتحدث توماس “تومي” بيغوت وتوماس تومي بيغوت', "headlines": ['توماس "تومي" بيغوت'],
                    "headline_selected": 0}
            p148 = store.save_draft(d148)
        finally:
            store.load_config = real_load
        saved148 = json.loads(p148.read_text(encoding="utf-8"))
        check("g148: «توماس \"تومي\" بيغوت» ← «تومي بيغوت» في العنوان والتعليق والعناوين",
              saved148["arabic"]["post_title"] == "قال تومي بيغوت"
              and saved148["caption"] == "المتحدث تومي بيغوت وتومي بيغوت"
              and saved148["headlines"] == ["تومي بيغوت"], saved148["arabic"]["post_title"])

        # g149) editor.paths.important=false ← لا نداء، والكتابة كما كانت
        cfg149 = copy.deepcopy(cfg)
        cfg149["editor"]["paths"]["important"] = False
        res149 = important_b2_result(88820)
        for i in res149["article_items"]:
            i["selection_issue"] = 88830
        important.save(res149)
        body149 = important_items_marked_body(res149, {i["id"]: "go2" for i in res149["article_items"]}, cfg149)
        writes.clear()
        sent.clear()
        editor._create = fake_editor({})
        with ImportantWriteRig(respond, gap_sources=gap_src) as rig:
            rig.next = 88950
            code149 = important_finalize.finalize(88830, body149, cfg149)
            saved149 = important.load_saved(88820)["article_items"]
            d149 = [store.load_draft(i["draft_id"])[1] for i in saved149 if i.get("draft_id")]
        check("g149: لا نداء محرر لـ«هام» والمسودات الثلاث مكتوبة بلا editor_review",
              code149 == 0 and sent == [] and len(d149) == 3 and not any("editor_review" in x for x in d149)
              and len(writes) == 3, (code149, len(sent), len(d149)))

        # g150) العدّاد مشترك: بلوغه من التحليل ← محرر «هام» بلا web_search
        reset_counter()
        imagesearch.BRAVE_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        imagesearch.BRAVE_USAGE_FILE.write_text(json.dumps({editor.usage_key(): 299}), encoding="utf-8")
        da3 = json.loads(fxa.read_text(encoding="utf-8"))
        ye._create = lambda client, **kw: editor_response([], searches=1)
        ye.run(da3, pts_a, cfg)
        ye._create = saved_ye
        check("g150: محرر التحليل رفع العدّاد المشترك إلى 300", editor.search_usage() == 300, editor.search_usage())
        d = install("d4dbc7461dc2")
        sent.clear()
        editor._create = fake_editor({})
        important_editor.review(d, real, items["nearest"], cfg)
        tool_names = [t.get("name") for t in sent[0]["tools"]] if sent else None
        er = store.load_draft(d["id"])[1].get("editor_review") or {}
        check("g150: محرر «هام» بلا web_search والمراجعة تعمل (search_skipped=cap)",
              tool_names == ["report_review"] and er.get("search_skipped") == "cap" and er.get("error") is None,
              (tool_names, er))
        reset_counter()
        imagesearch.BRAVE_USAGE_FILE.write_text(json.dumps({editor.usage_key(): 3}), encoding="utf-8")
        sent.clear()
        important_editor.review(install("d4dbc7461dc2"), real, items["nearest"], cfg)
        check("g150: تحت السقف ← أداة البحث موجودة لـ«هام»",
              [t.get("name") for t in sent[0]["tools"]] == ["web_search", "report_review"])
    finally:
        editor._create, ye._create = saved_create, saved_ye
        reset_counter()


def test_editor_news_breaking_guards() -> None:
    """Issue #1334 (D2): g151–g158 — المحرر الأخير لمسارَي الأخبار والرادار وبواباتهما وتوحيد الأسماء في كل الحقول.
    الشاهد نسخة حرفية من drafts/2026-10-08/eadf3a9544e6.json في tests/fixtures/editor/news/. نموذج المحرر مزيَّف
    (editor._create)؛ والكود الحقيقي هو الذي يبني الرسالة ويطبّق ويبوّب."""
    import copy
    import json
    import os
    import sys
    import tempfile
    from datetime import datetime, timezone
    from pathlib import Path

    from src import (collect_finalize, editor, facebook, headlines as headlines_mod, preselect, radar, review,
                     youtube_publish)
    from src import publish as publish_mod
    from src.config import STATE_DIR
    from src.sources import Article
    from tests.helpers import editor_response, tick_marker

    cfg = load_config()
    root = Path(__file__).resolve().parent
    real = json.loads((root / "fixtures/editor/news/eadf3a9544e6.json").read_text(encoding="utf-8"))
    src = real["source"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    TASS = "https://tass.com/world/2199053"
    HIGH = {"category": "other", "severity": "high", "location": "body", "original": "", "fix": "",
            "note": "العنوان يخالف المتن", "sources": []}
    sent: list = []
    counter = [0]

    def fake_editor(notes=None, fail: bool = False):
        def fake(client, **kw):
            sent.append(kw)
            if fail:
                raise RuntimeError("عطل نداء المحرر")
            return editor_response(list(notes or []))
        return fake

    def make_art() -> Article:
        """خبر الشاهد برابط فريد لكل حالة (المعرّف من الرابط) كي لا تتداخل الحالات."""
        counter[0] += 1
        link = f"{src['link']}?case={counter[0]}"
        art = Article(title=src["title"], link=link, summary="Houthi missile hits Riyadh airport.",
                      source_name="Mehr News", region="ir", weight=1.0,
                      published=datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc), bucket="serious",
                      publisher="Mehr News", score=40.0, group_sources=9)
        art.cluster_sources = list(src["publishers"])
        art.cluster_members = [{"name": "Mehr News", "link": link}, {"name": "TASS", "link": TASS}]
        return art

    def docs_for(art) -> list[dict]:
        return [{"name": "Mehr News", "link": art.link, "text": "Yemen strikes Riyadh airport with a missile."},
                {"name": "TASS", "link": TASS, "text": "Houthis said they hit King Khalid airport."}]

    def written_for() -> dict:
        w = copy.deepcopy(real["arabic"])
        w["post_title"] = real["headlines"][0]
        w["image_headline"] = w["post_title"]     # عنوان البطاقة يتبع العنوان المختار
        return w

    class Run:
        pass

    def finalize_case(marker: str, notes=None, fail: bool = False, run_cfg=None) -> Run:
        art = make_art()
        cand = preselect.build_candidate(art)
        store.save_candidate(cand)
        out = Run()
        out.art, out.comments, out.dispatched, out.id = art, [], [], art.uid
        written, docs = written_for(), docs_for(art)
        heads = [written["post_title"], *real["headlines"][1:]]
        names = ["write_arabic", "gather_texts"]
        saved = [getattr(collect_finalize, n) for n in names]
        saved_misc = (headlines_mod.headlines_for_post, publish_mod.cmd_burst, publish_mod.cmd_now,
                      publish_mod.cmd_schedule, review.comment, review.close_issue, review.remove_label,
                      review.ensure_labels, collect_finalize.cards.ensure, editor._create)
        old_repo = os.environ.get("GITHUB_REPOSITORY")
        collect_finalize.write_arabic = lambda a, c, previous_post=None, source_docs=None: copy.deepcopy(written)
        collect_finalize.gather_texts = lambda members, limit=2: (docs, [])
        headlines_mod.headlines_for_post = lambda *a, **k: (list(heads), None)

        def record(ids, *a, **k):
            out.dispatched.append(list(ids))
            return 0

        publish_mod.cmd_burst = publish_mod.cmd_now = publish_mod.cmd_schedule = record
        review.comment = lambda n, text: out.comments.append(text)
        review.close_issue = review.remove_label = lambda *a, **k: None
        review.ensure_labels = lambda *a, **k: None
        collect_finalize.cards.ensure = lambda path, draft, c, **kw: path
        editor._create = fake_editor(notes, fail)
        os.environ.pop("GITHUB_REPOSITORY", None)      # لا قضايا حقيقية
        sent.clear()
        try:
            body = tick_marker(preselect.build_selection_issue_body([cand]), f"<!-- go:{marker}:{art.uid} -->")
            out.code = collect_finalize.finalize(9000 + counter[0], body, run_cfg or cfg)
        finally:
            for n, v in zip(names, saved):
                setattr(collect_finalize, n, v)
            (headlines_mod.headlines_for_post, publish_mod.cmd_burst, publish_mod.cmd_now,
             publish_mod.cmd_schedule, review.comment, review.close_issue, review.remove_label,
             review.ensure_labels, collect_finalize.cards.ensure, editor._create) = saved_misc
            if old_repo is not None:
                os.environ["GITHUB_REPOSITORY"] = old_repo
        found = store.load_draft(art.uid)
        out.draft = found[1] if found else None
        return out

    saved_create = editor._create
    try:
        # g151) رسالة المحرر: ناشر كل مصدر وتاريخه وتاريخ اليوم؛ وإصلاح العنوان 1 يصل العناوين والتعليق والبطاقة
        new_h = "الحوثيون يعلنون استهداف مطار الملك خالد بصاروخ باليستي"
        fix = {"category": "headline_overclaims", "severity": "low", "location": "headline_1",
               "original": real["headlines"][0], "fix": new_h, "note": "العنوان يبالغ", "sources": []}
        r = finalize_case("go2", [fix])
        msg = sent[0]["messages"][0]["content"] if sent else ""
        check("g151: الرسالة فيها تاريخ اليوم والناشران وتاريخ كل مصدر (المعروف وغير المعروف)",
              f"تاريخ اليوم: {today}" in msg and "Mehr News | " in msg and f"TASS | {TASS}" in msg
              and "(نُشر: 2026-10-08)" in msg and "(تاريخ غير معروف)" in msg, msg[:400])
        check("g151: الرسالة فيها عنوان الخبر الأصلي وملخصه ونص doc",
              src["title"] in msg and "Houthi missile hits Riyadh airport." in msg
              and "Houthis said they hit King Khalid airport." in msg)
        d = r.draft or {}
        check("g151: طُبّق الإصلاح على العناوين وعلى post_title وعلى caption وعلى عنوان البطاقة",
              d.get("headlines", [""])[0] == new_h and d["arabic"]["post_title"] == new_h
              and d["caption"].startswith(new_h) and d["arabic"]["image_headline"] == new_h
              and d["reel_spec"]["headline"] == new_h, d.get("headlines"))
        check("g151: editor_review محفوظ على المسودة وسطر ✏️ في عرض المراجعة",
              len((d.get("editor_review") or {}).get("applied", [])) == 1
              and "✏️ كان" in "\n".join(review.warnings_block(d)))

        # g152) publish/go3 من قضية الترشيح مع ملاحظة high ← go2 مع التعليق؛ وgo2 بلا تغيير
        for act in ("publish", "go3"):
            r = finalize_case(act, [HIGH])
            check(f"g152: {act} + ملاحظة high ← لا نشر ومسودة pending وتعليق «حُوِّل»",
                  r.code == 0 and not r.dispatched and r.draft and r.draft["status"] == "pending"
                  and any("حُوِّل" in c and "لأن المحرر وجد: العنوان يخالف المتن" in c for c in r.comments),
                  (r.code, r.dispatched, r.comments))
        r = finalize_case("go2", [HIGH])
        check("g152: go2 بلا تغيير (لا تعليق تحويل)",
              r.draft is not None and not any("حُوِّل" in c for c in r.comments), r.comments)
        r = finalize_case("publish", [])
        check("g152: publish بلا ملاحظات يمضي إلى النشر",
              r.dispatched == [[r.id]] and not any("حُوِّل" in c for c in r.comments), (r.dispatched, r.comments))

        # g153) publish من المرحلة 2 لمسودة خبر فيها ملاحظة high ← go3؛ ومسودة تحليل كما كانت
        def put(base: dict, did: str, er=None) -> None:
            dd = copy.deepcopy(base)
            dd.update(id=did, status="pending")
            for k in ("image", "facebook", "published_at"):
                dd.pop(k, None)
            if er is not None:
                dd["editor_review"] = er
            store.save_draft(dd)

        ana = json.loads((root / "fixtures/analysis/1322/8ec39e3d9456.json").read_text(encoding="utf-8"))
        put(real, "153a00000001", {"notes": [HIGH], "applied": []})
        put(real, "153b00000002")
        put(ana, "153c00000003", {"notes": [HIGH], "applied": []})
        calls: dict = {"final": [], "burst": [], "yt": [], "comments": []}
        saved53 = (publish_mod.fetch_issue, publish_mod.open_final_review, publish_mod.cmd_burst,
                   publish_mod.cards.ensure, review.comment, youtube_publish.publish_ids, sys.argv)
        stage2 = review.build_issue_body([store.load_draft(i)[1] for i in ("153a00000001", "153b00000002")],
                                         "u/r", "main")
        for i in ("153a00000001", "153b00000002"):
            stage2 = tick_marker(stage2, f"<!-- go:publish:{i} -->")
        ana_body = tick_marker(review.build_issue_body([store.load_draft("153c00000003")[1]], "u/r", "main"),
                               "<!-- go:publish:153c00000003 -->")
        box = {"body": stage2}
        publish_mod.fetch_issue = lambda n: {"number": n, "body": box["body"],
                                             "labels": [{"name": "pending-review"}, {"name": "approved"}]}
        publish_mod.open_final_review = lambda issue, ids, c: calls["final"].append(sorted(ids))
        publish_mod.cmd_burst = lambda ids, *a, **k: calls["burst"].append(list(ids)) or 0
        publish_mod.cards.ensure = lambda path, draft, c, **kw: path
        review.comment = lambda n, text: calls["comments"].append(text)

        def fake_publish_ids(ids, *a, **k):
            calls["yt"].append((list(ids), sorted(k.get("go3_ids") or [])))
            return [], [], [], []

        youtube_publish.publish_ids = fake_publish_ids
        sys.argv = ["publish", "--issue", "93530", "--skip-urgent"]
        try:
            publish_mod.main()
            box["body"] = ana_body
            publish_mod.main()
        finally:
            (publish_mod.fetch_issue, publish_mod.open_final_review, publish_mod.cmd_burst,
             publish_mod.cards.ensure, review.comment, youtube_publish.publish_ids, sys.argv) = saved53
        check("g153: مسودة الخبر ذات editor_review high ← مرحلة 3 لا النشر، والعادية تُنشر",
              calls["final"] == [["153a00000001"]] and calls["burst"] == [["153b00000002"]],
              (calls["final"], calls["burst"]))
        check("g153: تعليق «حُوِّل … لأن المحرر وجد» على القضية",
              any("حُوِّل" in c and "العنوان يخالف المتن" in c for c in calls["comments"]), calls["comments"])
        check("g153: مسودة التحليل كما كانت: تُمرَّر إلى publish_ids بخيار go3",
              bool(calls["yt"]) and calls["yt"][-1][1] == ["153c00000003"], calls["yt"])

        # الرادار: مستوفٍ للنشر التلقائي
        def run_radar(notes=None, fail: bool = False, run_cfg=None) -> Run:
            shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
            shutil.rmtree(STATE_DIR, ignore_errors=True)
            DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
            rc = copy.deepcopy(run_cfg or cfg)
            rc["radar"] = {**(rc.get("radar") or {}), "enabled": True, "auto_publish": True,
                           "auto_publish_daily_limit": 3, "auto_publish_min_score": 0.0,
                           "auto_publish_min_sources": 1, "preselect_fallback": False, "max_per_run": 1}
            art = make_art()
            out = Run()
            out.art, out.published = art, []
            summary = Path(tempfile.mkdtemp()) / "summary.md"
            saved_r = (radar.scan, radar.write_arabic, radar.gather_texts, radar.merge.find_duplicate_event,
                       radar.load_config, facebook.publish_photo, publish_mod.ROOT, editor._create, sys.argv)
            old_env = {k: os.environ.get(k) for k in ("GITHUB_STEP_SUMMARY", "GITHUB_REPOSITORY")}
            radar.scan = lambda c: [art]
            radar.write_arabic = lambda a, c, retries=3, previous_post=None, source_docs=None: written_for()
            radar.gather_texts = lambda members, limit=2: (docs_for(art), [])
            radar.merge.find_duplicate_event = lambda title, recent, c: (True, None)
            radar.load_config = lambda path=None: rc
            publish_mod.ROOT = DRAFTS_DIR.parent

            def fake_photo(image_path, caption, api_version, first_comment=None):
                out.published.append(image_path)
                return {"url": "https://fb.example/r", "id": "1"}

            facebook.publish_photo = fake_photo
            editor._create = fake_editor(notes, fail)
            os.environ["GITHUB_STEP_SUMMARY"] = str(summary)
            os.environ.pop("GITHUB_REPOSITORY", None)
            sys.argv = ["radar"]
            sent.clear()
            try:
                out.code = radar.main()
            finally:
                (radar.scan, radar.write_arabic, radar.gather_texts, radar.merge.find_duplicate_event,
                 radar.load_config, publish_mod.ROOT, editor._create, sys.argv) = (
                    saved_r[0], saved_r[1], saved_r[2], saved_r[3], saved_r[4], saved_r[6], saved_r[7], saved_r[8])
                facebook.publish_photo = saved_r[5]
                for k, v in old_env.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            found = store.load_draft(art.uid)
            out.draft = found[1] if found else None
            out.counter = radar.auto_published_today(radar._load_state())
            out.report = summary.read_text(encoding="utf-8") if summary.exists() else ""
            return out

        # g154) مستوفٍ + ملاحظة high ← لا نشر، pending، العدّاد بلا زيادة، وسطر التقرير فيه «المحرر:»
        r = run_radar([HIGH])
        check("g154: لا يُستدعى نشر والمسودة pending والعدّاد صفر",
              r.code == 0 and not r.published and r.draft and r.draft["status"] == "pending"
              and r.counter == 0, (r.code, r.published, r.draft and r.draft["status"], r.counter))
        check("g154: التقرير «📋 بانتظار مراجعتك» والسبب «المحرر: …»",
              "📋 بانتظار مراجعتك" in r.report and "المحرر: العنوان يخالف المتن" in r.report
              and "نُشر تلقائيًا" not in r.report, r.report)
        check("g154: قرار النشر التلقائي المحفوظ على المسودة يحمل السبب",
              (r.draft or {}).get("auto_publish_decision", "").startswith("المحرر:"))

        # g155) مستوفٍ + عطل في نداء المحرر ← لا نشر تلقائي بالسبب نفسه
        r = run_radar(fail=True)
        check("g155: عطل المحرر ← لا نشر والمسودة pending والعدّاد صفر وفي المسودة editor_review.error",
              not r.published and r.draft and r.draft["status"] == "pending" and r.counter == 0
              and (r.draft.get("editor_review") or {}).get("error"), (r.published, r.counter))
        check("g155: سطر التقرير «المحرر: تعذّرت مراجعة المحرر»",
              "📋 بانتظار مراجعتك" in r.report and "المحرر: تعذّرت مراجعة المحرر" in r.report, r.report)
        cfg155 = copy.deepcopy(cfg)
        cfg155["editor"]["block_auto_publish_on_error"] = False
        r = run_radar(fail=True, run_cfg=cfg155)
        check("g155: block_auto_publish_on_error=false ← يُنشر كما قبل D2", len(r.published) == 1, r.published)

        # g156) مستوفٍ + محرر بلا ملاحظات ← يُنشر كما كان
        r = run_radar([])
        check("g156: يُنشر تلقائيًا مرة واحدة والعدّاد 1 والحالة published",
              len(r.published) == 1 and r.counter == 1 and r.draft and r.draft["status"] == "published",
              (r.published, r.counter))
        check("g156: التقرير «نُشر تلقائيًا» ومراجعة المحرر محفوظة بلا ملاحظات",
              "🚀 **نُشر تلقائيًا**" in r.report and (r.draft["editor_review"]["notes"] == []), r.report)
        check("g156: نداء محرر واحد وفيه system_extra الخاص بالمسار",
              len(sent) == 1 and "الخبر قصير: لا تقترح إطالة" in sent[0]["system"], len(sent))

        # g157) paths.news = breaking = false ← لا نداء، والسلوك كما قبل D2
        cfg157 = copy.deepcopy(cfg)
        cfg157["editor"]["paths"]["news"] = cfg157["editor"]["paths"]["breaking"] = False
        r = run_radar([HIGH], run_cfg=cfg157)
        check("g157: الرادار — لا نداء للمحرر ويُنشر ولا editor_review",
              not sent and len(r.published) == 1 and "editor_review" not in (r.draft or {}),
              (len(sent), r.published))
        r = finalize_case("publish", [HIGH], run_cfg=cfg157)
        check("g157: الأخبار — لا نداء ولا تحويل وتمضي المسودة إلى النشر",
              not sent and r.dispatched == [[r.id]] and not any("حُوِّل" in c for c in r.comments)
              and "editor_review" not in (r.draft or {}), (len(sent), r.dispatched))

        # g158) توحيد الأسماء في post_body وimage_headline وanalysis عبر store.save_draft الفعلي
        d158 = {"id": "g158name0001", "status": "pending", "origin": "news",
                "source": {"title": "t", "link": "https://x/158", "publisher": "p", "publishers": ["p"]},
                "arabic": {"post_title": "عنوان", "category": "عالم", "urgent": False, "hashtags": [],
                           "post_body": 'قال توماس "تومي" بيغوت إن الأمر انتهى.',
                           "image_headline": "ترمب يردّ على بيغوت",
                           "analysis": "ويرى ترمب أن الأمر انتهى."},
                "caption": "عنوان", "headlines": ["عنوان"]}
        store.save_draft(d158)
        got = store.load_draft("g158name0001")[1]["arabic"]
        check("g158: «توماس \"تومي\" بيغوت» ← «تومي بيغوت» في post_body",
              "تومي بيغوت" in got["post_body"] and "توماس" not in got["post_body"], got["post_body"])
        check("g158: «ترمب» ← «ترامب» في image_headline وفي analysis",
              got["image_headline"] == "ترامب يردّ على بيغوت" and "ترامب" in got["analysis"]
              and "ترمب" not in got["analysis"], (got["image_headline"], got["analysis"]))
    finally:
        editor._create = saved_create


def test_reel_structure_guards() -> None:
    """هيكل «مقال/ريل» في مسار التحليل خلف reel.enabled، وإزالة خيار الريل القديم من الأخبار
    (Issue #1336، R1، g159–g168). الكاتب (youtube_article._write_one_topic) مزيَّف ويُعدّ؛ باقي
    الأنبوب (open_selection/finalize_selection/cmd_youtube_selection/open_review/publish.main) حقيقي.
    مرجع g159 ملف tests/fixtures/reel/stage1_before.md ولّدته الشيفرة قبل التعديل على المدخل نفسه."""
    import json
    import os
    import re
    from pathlib import Path

    from src import decisions, imagesearch, review
    from src import publish as publish_mod
    from src import youtube_article as ya
    from src import youtube_cluster as ycl
    from src import youtube_extract
    from src import youtube_publish as yp
    from src.important import point_id
    from tests import test_review as tr
    from tests.helpers import legacy_youtube_selection_body, restore_last_publish, tick_marker

    fx = Path(__file__).parent / "fixtures" / "reel"
    D = "2099-11-01"

    def cfg_with(enabled: bool, cap: int = 5):
        c = load_config()
        c.setdefault("reel", {})["enabled"] = enabled
        c.setdefault("youtube", {}).setdefault("article", {}).update(count=5, max_per_run=cap)
        return c

    cfg_off, cfg_on = cfg_with(False), cfg_with(True)
    T = cfg_on.path("reel.texts")
    # مقارنة جسم المرحلة 1 بالمرجع تتطلب الإعداد الافتراضي نفسه (سقف max_per_run يظهر في سطر الجسم)
    body_off_cfg, body_on_cfg = load_config(), load_config()
    body_off_cfg.setdefault("reel", {})["enabled"] = False
    body_on_cfg.setdefault("reel", {})["enabled"] = True

    # ── g159) المفتاح مطفأ ← الجسم حرفيًا كما قبل التعديل ولا علامات fmt: ──
    base_topics = [
        {"id": "aaaa1111bbbb", "title": "موضوع أول", "event": "حدث أول", "layer": "a",
         "blocs": ["arabic", "turkish"], "channels": ["الجزيرة", "CNN Türk"],
         "agreement": "cross_source", "point_ids": [0, 1]},
        {"id": "cccc2222dddd", "title": "موضوع ثانٍ", "event": "حدث ثانٍ", "layer": "b",
         "blocs": ["arabic"], "channels": ["الجزيرة"], "agreement": "agreement",
         "point_ids": [0], "returned_from_stage": 2},
    ]
    base_points = [{"statement": "قول", "speaker": "متحدث", "channel": "الجزيرة"},
                   {"statement": "قول٢", "speaker": "متحدث٢", "channel": "CNN Türk"}]
    before = (fx / "stage1_before.md").read_text(encoding="utf-8")
    off_body = ycl.build_selection_body("2099-01-01", base_topics, base_points, body_off_cfg)
    check("g159: reel.enabled=false ← الجسم مطابق حرفيًا لما قبل التعديل", off_body == before)
    check("g159: لا علامات fmt: ولا كتلة صيغة", "fmt:" not in off_body and T["format_header"] not in off_body)

    # ── g160) المفتاح مشغَّل ← كتلة الصيغة في كل موضوع والمقال معلَّم والانتقال كما هو ──
    on_body = ycl.build_selection_body("2099-01-01", base_topics, base_points, body_on_cfg)
    ok160 = True
    stripped = on_body
    for t in base_topics:
        tid = t["id"]
        art = f"- [x] {T['article']}  <!-- fmt:article:{tid} -->"
        reel_line = f"- [ ] {T['reel']}  <!-- fmt:reel:{tid} -->"
        block = "\n".join([T["format_header"], art, reel_line, T["stage1_note"], ""]) + "\n"
        ok160 = ok160 and block in on_body and all(f"<!-- go:{a}:{tid} -->" in on_body
                                                    for a in ("go2", "go3", "publish"))
        ok160 = ok160 and f"<!-- go:go1:{tid} -->" not in on_body
        i_field, i_block = on_body.find(f"imgurl:{tid}"), on_body.find(block)
        i_opts = on_body.find(f"go:go2:{tid}")
        ok160 = ok160 and 0 < i_field < i_block < i_opts
        stripped = stripped.replace(block, "")
    check("g160: كتلة صيغ (مقال معلَّم/ريل لا) بعد حقل الصورة وقبل الانتقال لكل موضوع", ok160)
    check("g160: حذف الكتل يعيد الجسم القديم حرفيًا (كتلة الانتقال لم تتغير)", stripped == before)
    check("g160: قراءة الصيغ من الجسم الجديد",
          ycl.parse_formats(on_body) == {"article": {t["id"] for t in base_topics}, "reel": set()},
          ycl.parse_formats(on_body))
    check("g160: جسم بلا علامات fmt: ← None (قضية قديمة)", ycl.parse_formats(before) is None)

    # ═════ بيئة الأنبوب: الكاتب مزيَّف ويُعدّ، باقي الأنبوب حقيقي ═════
    created: list[dict] = []
    comments: list[str] = []
    writes = {"n": 0}

    def fake_create_issue(title, body, labels=None):
        created.append({"title": title, "body": body, "labels": labels})
        return {"number": 6000 + len(created), "html_url": "https://x/i"}

    def fake_write(topic, points, cfg, client):
        writes["n"] += 1
        return {"item": {"text": f"متن مقال {topic['title']}", "video_ids": ["v1"]},
                "skip_reason": None, "reason_kind": None, "seen_keys": set()}

    real = {"create_issue": review.create_issue, "ensure_labels": review.ensure_labels,
            "comment": review.comment, "remove_label": review.remove_label,
            "close_issue": review.close_issue, "write": ya._write_one_topic,
            "yp_photo": yp._photo_candidates, "ex_news_ok": youtube_extract.news_photo_available,
            "find_images": imagesearch.find_images, "repo": os.environ.get("GITHUB_REPOSITORY")}
    # كتابة السيناريو (R2) خارج نطاق اختبار الهيكل: تُعزل لتبقى مسودة الريل awaiting_script كما ثبّتها R1
    real["write_reel_script"] = publish_mod._write_reel_script
    publish_mod._write_reel_script = lambda *a, **k: None
    review.create_issue = fake_create_issue
    review.ensure_labels = lambda: None
    review.comment = lambda n, t: comments.append(t)
    review.remove_label = lambda n, lbl: None
    review.close_issue = lambda n: None
    ya._write_one_topic = fake_write
    yp._photo_candidates = lambda *a, **k: ["https://example.com/p.jpg"]
    youtube_extract.news_photo_available = lambda *a, **k: False
    imagesearch.find_images = lambda *a, **k: []
    os.environ["GITHUB_REPOSITORY"] = "user/trendnews"

    def fresh(titles: list[str], cfg_x):
        """يصفّر drafts/ والمواضيع ويفتح قضية اختيار؛ يعيد (sel, body)."""
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(ycl.TOPICS_DIR, ignore_errors=True)
        ycl.TOPICS_DIR.mkdir(parents=True, exist_ok=True)
        ycl.POINTS_DIR.mkdir(parents=True, exist_ok=True)
        if decisions.DECISIONS_FILE.exists():
            decisions.DECISIONS_FILE.unlink()
        pts = [{"video_id": "g0", "bloc": "arabic", "channel": "الجزيرة", "speaker": "متحدث",
                "statement": "قول", "quote_arabic": "اقتباس", "type": "fact", "video_title": "ف",
                "video_url": "https://youtube.com/watch?v=g0", "timestamp": 1},
               {"video_id": "g1", "bloc": "turkish", "channel": "CNN Türk", "speaker": "متحدث٢",
                "statement": "قول٢", "quote_arabic": "اقتباس٢", "type": "fact", "video_title": "ف٢",
                "video_url": "https://youtube.com/watch?v=g1", "timestamp": 2}]
        (ycl.POINTS_DIR / f"{D}.json").write_text(json.dumps({"points": pts}, ensure_ascii=False),
                                                  encoding="utf-8")
        topics = [{"title": t, "event": f"حدث {t}", "layer": "a", "blocs": ["arabic", "turkish"],
                   "channels": ["الجزيرة", "CNN Türk"], "agreement": "cross_source", "point_ids": [0, 1]}
                  for t in titles]
        (ycl.TOPICS_DIR / f"{D}.json").write_text(
            json.dumps({"run_date": D, "topics": topics}, ensure_ascii=False), encoding="utf-8")
        created.clear()
        writes["n"] = 0
        sel = ycl.open_selection(cfg_x, date_str=D)
        return sel, created[-1]["body"]

    def tick(body: str, kind: str, tid: str) -> str:
        return tick_marker(body, f"{kind}:{tid}")

    def untick_article(body: str, tid: str) -> str:
        return body.replace(f"- [x] {T['article']}  <!-- fmt:article:{tid} -->",
                            f"- [ ] {T['article']}  <!-- fmt:article:{tid} -->")

    def go(sel, body: str, cfg_x) -> list[dict]:
        comments.clear()
        n0 = len(created)
        publish_mod.cmd_youtube_selection(sel["issue"]["number"], body, cfg_x, client=None)
        return created[n0:]

    def drafts_of(tid: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for p in sorted(DRAFTS_DIR.glob("*/*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("topic_id") == tid:
                out[d.get("format") or "article"] = d
        return out

    try:
        # ── g161) ريل وحده بلا أي انتقال ← لا كتابة مقال، ومسودة ريل pending ──
        sel, body = fresh(["موضوع ريل"], cfg_on)
        tid = sel["topics"][0]["id"]
        new = go(sel, tick(body, "fmt:reel", tid), cfg_on)
        got = drafts_of(tid)
        rd = got.get("reel") or {}
        check("g161: لا نداء كاتب", writes["n"] == 0, writes)
        check("g161: لا مسودة مقال", "article" not in got, list(got))
        check("g161: مسودة الريل بمعرّف point_id(topic:reel) وformat reel وpending",
              rd.get("id") == point_id(f"{tid}:reel") and re.fullmatch(r"[0-9a-f]+", rd.get("id", "-"))
              and rd.get("format") == "reel" and rd.get("status") == "pending", rd)
        check("g161: origin analysis وtopic_id وtopic_date وscript_status awaiting_script",
              rd.get("origin") == "analysis" and rd.get("topic_id") == tid and rd.get("topic_date") == D
              and rd.get("script_status") == "awaiting_script", rd)
        check("g161: بلا caption ولا عناوين بعد", not rd.get("caption") and not rd.get("headlines"), rd)
        check("g161: فُتحت قضية مرحلة 2 فيها بند الريل",
              any(c["labels"] == ["youtube-review"] and f"<!-- draft:{rd.get('id')} -->" in c["body"]
                  for c in new), [c["labels"] for c in new])
        check("g161: الموضوع حُسم attempted",
              next(t for t in ycl._load_topics_raw(D)["topics"] if t["id"] == tid)["selection_status"]
              == "attempted")

        # ── g162) الاثنان معلَّمان + go2 للمقال، وسقف max_per_run=1 لا يمسّ الريل ──
        cfg_cap1 = cfg_with(True, cap=1)
        sel, body = fresh(["موضوع أ", "موضوع ب"], cfg_cap1)
        ta, tb = (t["id"] for t in sel["topics"])
        b2 = tick(tick(tick(body, "go:go2", ta), "fmt:reel", ta), "fmt:reel", tb)
        new = go(sel, b2, cfg_cap1)
        da, db = drafts_of(ta), drafts_of(tb)
        check("g162: مقال الموضوع أ كُتب (نداء واحد) وformat article",
              writes["n"] == 1 and da.get("article", {}).get("format") == "article", writes)
        check("g162: مسودة ريل للموضوعين رغم السقف=1 (لا كتابة فلا سقف)",
              "reel" in da and "reel" in db and "article" not in db)
        check("g162: sibling_id متبادل بين مقال أ وريله",
              da["article"].get("sibling_id") == da["reel"]["id"]
              and da["reel"].get("sibling_id") == da["article"]["id"], (da["article"].get("sibling_id"),))
        check("g162: ريل ب بلا sibling_id", not db["reel"].get("sibling_id"))
        s2 = next((c["body"] for c in new if c["labels"] == ["youtube-review"]), "")
        check("g162: المقال والريلان في قضية المرحلة 2",
              all(f"<!-- draft:{x['id']} -->" in s2 for x in (da["article"], da["reel"], db["reel"])))
        check("g162: المقال pending بانتظار المرحلة 2 (go2)", da["article"]["status"] == "pending")
        art_a, reel_a = da["article"], da["reel"]

        # ── g163) مقال غير معلَّم + go2 ← لا مقال وتعليق تعارض ──
        sel, body = fresh(["موضوع ج"], cfg_on)
        tc = sel["topics"][0]["id"]
        go(sel, untick_article(tick(body, "go:go2", tc), tc), cfg_on)
        check("g163: لا مقال ولا نداء كاتب ولا مسودة", writes["n"] == 0 and not drafts_of(tc), writes)
        conflict = T["article_unchecked_conflict"].format(title="موضوع ج")
        check("g163: تعليق التعارض يذكر الموضوع", any(conflict in c for c in comments), comments)
        check("g163: الموضوع unselected",
              next(t for t in ycl._load_topics_raw(D)["topics"] if t["id"] == tc)["selection_status"]
              == "unselected")

        # ── g164) قضية اختيار قديمة (بلا fmt:) ← مقال فقط كما كانت، ولا ريل ──
        sel, _ = fresh(["موضوع د"], cfg_off)
        td = sel["topics"][0]["id"]
        legacy_sel = tick_marker(legacy_youtube_selection_body(D, sel["topics"]), f"topic:{td}")
        res = ycl.finalize_selection(sel["issue"]["number"], legacy_sel, cfg_off)
        check("g164: قديمة ← الموضوع للكتابة وبلا ريل",
              [t["id"] for t in res["to_write"]] == [td] and not res.get("reel_topics"), res)
        sel, body_off = fresh(["موضوع د"], cfg_off)
        td = sel["topics"][0]["id"]
        check("g164: جسم المفتاح المطفأ بلا fmt:", "fmt:" not in body_off)
        go(sel, tick(body_off, "go:go2", td), cfg_off)
        got = drafts_of(td)
        check("g164: مقال وحده (نداء واحد) وبلا مسودة ريل ولا sibling_id",
              writes["n"] == 1 and list(got) == ["article"] and not got["article"].get("sibling_id"), list(got))
        sel, _ = fresh(["موضوع هـ"], cfg_on)
        te = sel["topics"][0]["id"]
        legacy_on = tick_marker(legacy_youtube_selection_body(D, sel["topics"]), f"topic:{te}")
        go(sel, legacy_on, cfg_on)
        check("g164: قضية قديمة بالمفتاح المشغَّل ← مقال فقط (يُقرأ كما كان)",
              writes["n"] == 1 and list(drafts_of(te)) == ["article"], list(drafts_of(te)))

        # ── g165) المرحلة 2: بندان متجاوران تحت سطر الموضوع ──
        topic_line = T["topic_line"].format(title=art_a["title"])
        s2 = yp.build_review_body([art_a, reel_a], "u/r", "main", cfg_on)
        lines = s2.splitlines()
        i_topic = next((i for i, ln in enumerate(lines) if ln.strip() == topic_line), -1)
        i_art = next((i for i, ln in enumerate(lines) if f"<!-- draft:{art_a['id']} -->" in ln), -1)
        i_reel = next((i for i, ln in enumerate(lines) if f"<!-- draft:{reel_a['id']} -->" in ln), -1)
        check("g165: سطر الموضوع مرة واحدة قبل البندين المتجاورين",
              s2.count(topic_line) == 1 and 0 <= i_topic < i_art < i_reel, (i_topic, i_art, i_reel))
        art_part = "\n".join(lines[i_art:i_reel])
        reel_part = "\n".join(lines[i_reel:])
        check("g165: بند المقال بخياراته القائمة (go1/go3/publish)",
              all(f"<!-- go:{a}:{art_a['id']} -->" in art_part for a in ("go1", "go3", "publish")))
        check("g165: بند الريل سطر ⏳ من config وخيار go1 وحده",
              T["script_pending"] in reel_part and f"<!-- go:go1:{reel_a['id']} -->" in reel_part
              and f"go:go3:{reel_a['id']}" not in s2 and f"go:publish:{reel_a['id']}" not in s2
              and f"go:go2:{reel_a['id']}" not in s2)
        check("g165: بند الريل بلا عناوين ولا كتلة نص ولا حقل صورة",
              f"hl:{reel_a['id']}" not in s2 and f"imgurl:{reel_a['id']}" not in s2
              and f"cap:{reel_a['id']}" not in s2)
        check("g165: مع الصيغتين معًا لا خيار «➕ أضف»",
              "addfmt:" not in s2 and T["add_reel"] not in s2 and T["add_article"] not in s2)
        s2_art_only = yp.build_review_body([art_a], "u/r", "main", cfg_on)
        s2_reel_only = yp.build_review_body([reel_a], "u/r", "main", cfg_on)
        check("g165: مقال وحده ← «➕ أضف ريلًا» فقط بعلامة addfmt",
              f"- [ ] {T['add_reel']}  <!-- addfmt:reel:{art_a['topic_id']} -->" in s2_art_only
              and "addfmt:article" not in s2_art_only)
        check("g165: ريل وحده ← «➕ أضف مقالًا» فقط",
              f"- [ ] {T['add_article']}  <!-- addfmt:article:{reel_a['topic_id']} -->" in s2_reel_only
              and "addfmt:reel" not in s2_reel_only)
        s2_off = yp.build_review_body([art_a], "u/r", "main", cfg_off)
        check("g165: المفتاح مطفأ ← لا سطر موضوع ولا addfmt",
              topic_line not in s2_off and "addfmt:" not in s2_off and T["script_pending"] not in s2_off)
        check("g165: معرّفا البندين يجدهما review.all_draft_ids",
              review.all_draft_ids(s2) == [art_a["id"], reel_a["id"]])

        # ── g166) «➕ أضف ريلًا» ← مسودة ريل جديدة بلا أثر على المقال ──
        sel, body = fresh(["موضوع و"], cfg_on)
        tf = sel["topics"][0]["id"]
        go(sel, tick(body, "go:go2", tf), cfg_on)
        art_f = drafts_of(tf)["article"]
        art_path = store.load_draft(art_f["id"])[0]
        art_obj_before = json.loads(art_path.read_text(encoding="utf-8"))
        s2f = yp.build_review_body([art_f], "u/r", "main", cfg_on)
        n0 = len(created)
        publish_mod.cmd_add_formats(7001, tick(s2f, "addfmt:reel", tf), cfg_on, client=None)
        got = drafts_of(tf)
        check("g166: ظهرت مسودة ريل بمعرّف point_id وscript_status awaiting_script",
              got.get("reel", {}).get("id") == point_id(f"{tf}:reel")
              and got["reel"].get("script_status") == "awaiting_script"
              and got["reel"].get("topic_date") == D, got.get("reel"))
        art_obj = json.loads(art_path.read_text(encoding="utf-8"))
        sibling_after = art_obj.pop("sibling_id", None)
        art_obj_before.pop("sibling_id", None)
        check("g166: المقال لم يتغير سوى sibling_id (ولا كتابة جديدة)",
              art_obj == art_obj_before and writes["n"] == 1, writes)
        check("g166: الشقيقان متبادلان",
              sibling_after == got["reel"]["id"] and got["reel"].get("sibling_id") == art_f["id"])
        nxt = next((c["body"] for c in created[n0:] if c["labels"] == ["youtube-review"]), "")
        check("g166: يظهر الريل في قضية المرحلة 2 التالية",
              f"<!-- draft:{got['reel']['id']} -->" in nxt and f"<!-- draft:{art_f['id']} -->" not in nxt,
              nxt[:200])
        n1 = len(created)
        publish_mod.cmd_add_formats(7001, tick(s2f, "addfmt:reel", tf), cfg_on, client=None)
        check("g166: تكرار «أضف» لا ينشئ مسودة ثانية ولا قضية", len(created) == n1
              and len([p for p in DRAFTS_DIR.glob("*/*.json")
                       if json.loads(p.read_text(encoding="utf-8")).get("format") == "reel"]) == 1)

        # ── g167) «➕ أضف مقالًا» لموضوع له ريل فقط ← يُكتب المقال (كاتب مزيَّف) ويدخل المرحلة 2 ──
        sel, body = fresh(["موضوع ز"], cfg_on)
        tg = sel["topics"][0]["id"]
        go(sel, tick(body, "fmt:reel", tg), cfg_on)
        check("g167: تمهيد: ريل فقط", list(drafts_of(tg)) == ["reel"] and writes["n"] == 0)
        reel_g = drafts_of(tg)["reel"]
        s2g = yp.build_review_body([reel_g], "u/r", "main", cfg_on)
        n0 = len(created)
        publish_mod.cmd_add_formats(7002, tick(s2g, "addfmt:article", tg), cfg_on, client=None)
        got = drafts_of(tg)
        check("g167: كُتب المقال بنداء كاتب واحد وformat article وpending",
              writes["n"] == 1 and got.get("article", {}).get("format") == "article"
              and got["article"]["status"] == "pending", (writes, list(got)))
        check("g167: sibling_id متبادل",
              got["article"].get("sibling_id") == reel_g["id"]
              and got["reel"].get("sibling_id") == got["article"]["id"])
        nxt = next((c["body"] for c in created[n0:] if c["labels"] == ["youtube-review"]), "")
        check("g167: المقال في قضية المرحلة 2 التالية",
              f"<!-- draft:{got['article']['id']} -->" in nxt, nxt[:200])
        publish_mod.cmd_add_formats(7002, tick(s2g, "addfmt:article", tg), cfg_on, client=None)
        check("g167: تكرار «أضف مقالًا» لا يعيد الكتابة", writes["n"] == 1, writes)
    finally:
        publish_mod._write_reel_script = real["write_reel_script"]
        review.create_issue = real["create_issue"]
        review.ensure_labels = real["ensure_labels"]
        review.comment = real["comment"]
        review.remove_label = real["remove_label"]
        review.close_issue = real["close_issue"]
        ya._write_one_topic = real["write"]
        yp._photo_candidates = real["yp_photo"]
        youtube_extract.news_photo_available = real["ex_news_ok"]
        imagesearch.find_images = real["find_images"]
        if real["repo"] is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real["repo"]

    # ── g168) الأخبار: لا سطر «🎬 انشره كريل»، وقضية قديمة بمربع معلَّم ← صورة عادية ──
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    news = tr._stage_news_draft("e1336000001", "خبر فيه مواصفات ريل",
                                reel_spec={"headline": "خبر فيه مواصفات ريل"})
    news_body = review.build_issue_body([news], "u/r", "main")
    check("g168: قضية مرحلة 2 للأخبار بلا سطر «🎬 انشره كريل» ولا علامة reel:",
          "انشره كريل" not in news_body and "<!-- reel:" not in news_body and "🎬" not in news_body)
    check("g168: بقية البند سليمة (الانتقال وحقل الصورة)",
          f"go:publish:{news['id']}" in news_body and f"imgurl:{news['id']}" in news_body)
    check("g168: review.parse_reels محذوفة", not hasattr(review, "parse_reels"))
    store.save_draft(news)
    legacy_body = tr.legacy_stage2_body([(news["id"], "خبر فيه مواصفات ريل")])
    legacy_body = tick_marker(tick_marker(legacy_body, f"draft:{news['id']}"), f"reel:{news['id']}")
    reel_calls: list = []
    from src import facebook as fb_mod
    real_reel = fb_mod.publish_reel
    fb_mod.publish_reel = lambda *a, **k: reel_calls.append(a) or {"id": "x"}
    try:
        out = tr._run_publish_issue(legacy_body, "approved", ["--now"])
    finally:
        fb_mod.publish_reel = real_reel
        restore_last_publish()
    got = store.load_draft(news["id"])[1]
    check("g168: قديمة بمربع reel معلَّم ← نُشرت صورة عادية",
          got["status"] == "published" and len(out["published"]) == 1 and not reel_calls,
          (got["status"], out["published"]))
    check("g168: publish_as_reel لا يُكتب", "publish_as_reel" not in got, list(got))


def test_reel_script_guards() -> None:
    """كاتب سيناريو الريل وعرضه في المرحلة 2 وقراءته ومروره بالمحرر (Issue #1338، R2، g169–g180).
    نداء النموذج مزيَّف ويُعدّ (reel_script._create)، والمحرر وتدقيق الأسماء يُلتقَط مدخلهما؛ باقي الأنبوب
    (التحقق، العرض، publish.main) حقيقي."""
    import json
    import re
    import sys
    from types import SimpleNamespace

    from src import names_audit, review
    from src import publish as publish_mod
    from src import reel_editor, reel_script
    from src import youtube_article as ya
    from src import youtube_publish as yp
    from tests.helpers import tick_marker

    def cfg_with(enabled: bool):
        c = load_config()
        c.setdefault("reel", {})["enabled"] = enabled
        return c

    cfg, cfg_off = cfg_with(True), cfg_with(False)
    T = cfg.path("reel.texts")
    D = "2099-11-02"
    HE40 = " ".join(["שלום"] * 40)
    AR20 = " ".join(["كلمة"] * 20)

    def pt(i, speaker, ts, quote, channel="الجزيرة"):
        return {"video_id": f"v{i}", "bloc": "arabic", "channel": channel, "speaker": speaker,
                "statement": f"قول {i}", "quote_arabic": f"اقتباس عربي {i}", "quote_original": quote,
                "type": "fact", "video_title": f"فيديو {i}", "video_url": f"https://youtube.com/watch?v=v{i}",
                "timestamp": ts, "video_published": "2099-10-30"}

    pa = pt(1, "إسحاق بريك", 100, HE40, "CNN Türk")
    pb = pt(2, "ليلى حداد", 200, "five words only in quote")
    pc = pt(3, "سامر النجار", 300, AR20)
    pd = pt(4, "رامي خوري", None, "no timestamp quote here")
    pe = pt(5, "محلل عسكري", 400, "unnamed analyst quote here")
    pf = pt(6, "فارع المسلمي", 500, "unresolved name quote here")
    points = [pa, pb, pc, pd, pe, pf]
    unresolved = [{"arabic": "فارع المسلمي", "latin": "Farea", "reason": "x"}]

    # ── g169) استبعاد بلا timestamp وحده؛ المتحدث بلا اسم والاسم غير المحسوم لا يُستبعدان بعد R2c ──
    valid = reel_script.valid_clips(points, unresolved, cfg)
    check("g169: الصالحة خمس (بلا timestamp وحده؛ «محلل عسكري» والاسم غير المحسوم يبقيان)",
          [c["speaker_text"] for c in valid] == ["إسحاق بريك", "ليلى حداد", "سامر النجار", "محلل عسكري",
                                                 "فارع المسلمي"],
          [c["speaker_text"] for c in valid])
    check("g169: المقطع يحمل رابطًا وقناة معروضة ولغة ومعرّفًا ستّ عشريًا",
          all(c["video_url"] and c["channel_display"] and c["language"] and re.fullmatch(r"[0-9a-f]+", c["point_id"])
              for c in valid), valid[:1])
    check("g169: لغة الاقتباس تُكتشف (غير عربي للأول، عربي للثالث)",
          valid[0]["language"] != "ar" and valid[2]["language"] == "ar", [c["language"] for c in valid])

    # ── g171) نافذة المقطع ──
    s40, e40 = reel_script.clip_window(pa, cfg)
    s5, e5 = reel_script.clip_window(pb, cfg)
    check("g171: 40 كلمة ← 15 ثانية، وبدايته timestamp − 1",
          round(e40 - s40, 1) == 15 and s40 == 99, (s40, e40))
    check("g171: 5 كلمات ← 6 ثوانٍ (الحد الأدنى)", round(e5 - s5, 1) == 6, (s5, e5))
    check("g171: نافذة الصالحة هي نفسها", (valid[0]["start"], valid[0]["end"]) == (s40, e40))

    # ═════ بيئة الكتابة: النموذج مزيَّف ويُعدّ ═════
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    calls: list[dict] = []
    queue: list[dict] = []
    a_id, b_id, c_id = (valid[0]["point_id"], valid[1]["point_id"], valid[2]["point_id"])
    narr1 = " ".join(f"س{i}" for i in range(36))
    narr2 = " ".join(f"ص{i}" for i in range(36))

    def good_scenes():
        return [{"kind": "cold_open_clip", "point_id": a_id},
                {"kind": "title_card", "text": "عنوان الشاشة"},
                {"kind": "clip", "point_id": b_id},
                {"kind": "narration", "text": narr1},
                {"kind": "clip", "point_id": c_id},
                {"kind": "narration", "text": narr2},
                {"kind": "question", "text": "ما رأيك؟"},
                {"kind": "outro"}]

    def wcalls():
        """نداءات الكتابة وحدها (report_reel_script)؛ نداء التعرّف report_speakers يسبقها (Issue #1377)."""
        return [c for c in calls if c["tools"][0]["name"] == "report_reel_script"]

    def fake_create(client, **kw):
        calls.append(kw)
        if kw["tools"][0]["name"] == "report_speakers":
            # الافتراضي: name_latin = عنوان الفيديو كما وضعه الاختبار فيوثَّق، والاسم العربي من نص speaker
            rows = [{"point_id": reel_script.point_key_id(p), "name_latin": p.get("video_title", ""),
                     "name_arabic": p.get("speaker", ""), "role_arabic": ""} for p in points]
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="report_speakers",
                                                            input={"speakers": rows})],
                                   stop_reason="tool_use", usage=SimpleNamespace(input_tokens=1, output_tokens=1))
        data = queue.pop(0) if queue else {"title": "عنوان الشاشة", "question": "ما رأيك؟", "scenes": good_scenes()}
        block = SimpleNamespace(type="tool_use", name="report_reel_script", input=data)
        return SimpleNamespace(content=[block], stop_reason="tool_use",
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    audits: list[dict] = []
    edits: list[dict] = []
    real = {"create": reel_script._create, "audit": names_audit.run, "hl": ya.generate_headlines,
            "ed_create": reel_editor._create}

    def fake_audit(draft, sources, c):
        audits.append({"title": draft["arabic"]["post_title"], "body": draft["arabic"]["post_body"],
                       "sources": list(sources)})
        return {}

    def fake_ed_create(client, **kw):
        edits.append(kw)
        block = SimpleNamespace(type="tool_use", name="report_review", input={"notes": []})
        return SimpleNamespace(content=[block], usage=SimpleNamespace(server_tool_use=None))

    reel_script._create = fake_create
    names_audit.run = fake_audit
    ya.generate_headlines = lambda *a, **k: (["هل يتغير الموقف؟", "عنوان ب", "عنوان ج"], None, None)
    reel_editor._create = fake_ed_create

    def new_draft(i="e1e1e1e1e1e1", **extra):
        d = yp.build_reel_draft({"id": "aaaa1111bbbb", "title": "موضوع الريل", "layer": "a", "blocs": ["arabic"],
                                 "channels": ["الجزيرة"], "agreement": "agreement", "event": "حدث"}, D, cfg)
        d["id"] = i
        d.update(extra)
        return d

    def reset_drafts():
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    topic = {"id": "aaaa1111bbbb", "title": "موضوع الريل", "event": "حدث الموضوع"}
    try:
        # ── g170) مقطع صالح واحد ← لا نداء، failed بالسبب، تعليق ──
        d170 = new_draft()
        out = reel_script.write_for_draft(d170, topic, [pa, pd], "", unresolved, cfg)
        check("g170: لا نداء نموذج (لا تعرّف ولا كتابة)", not calls, len(calls))
        check("g170: script_status failed وسبب «لا مقاطع كافية»",
              d170["script_status"] == "failed" and "لا مقاطع كافية" in d170["script_error"]
              and out["status"] == "failed", d170.get("script_error"))
        store.save_draft(d170)
        cm: list[str] = []
        real_comment = review.comment
        review.comment = lambda n, t: cm.append(t)
        try:
            publish_mod._report_reel_script(d170, 9100, cfg)
        finally:
            review.comment = real_comment
        check("g170: تعليق على القضية بالسبب", len(cm) == 1 and "لا مقاطع كافية" in cm[0], cm)

        # ── g174) تناوب الراوي ──
        reset_drafts()
        check("g174: أول ريل ← female", reel_script.next_narrator(cfg, "zzzz") == "female")
        store.save_draft(new_draft("a0a0a0a0a0a0", script={"narrator": "female", "scenes": []},
                                   script_status="ready", created_at="2099-01-01T00:00:00+00:00"))
        check("g174: آخر ريل female ← male", reel_script.next_narrator(cfg, "zzzz") == "male")
        path_old = store.load_draft("a0a0a0a0a0a0")[0]
        store.update_draft(path_old, script={"narrator": "male", "scenes": []})
        check("g174: آخر ريل male ← female", reel_script.next_narrator(cfg, "zzzz") == "female")
        store.update_draft(path_old, script={"narrator": "female", "scenes": []})

        # ── g172) سيناريو صحيح ──
        d172 = new_draft()
        out = reel_script.write_for_draft(d172, topic, points, "نص مقال الموضوع", unresolved, cfg)
        sc = d172.get("script") or {}
        kinds = [s["kind"] for s in sc.get("scenes", [])]
        check("g172: نداءان بالترتيب (report_speakers ثم report_reel_script) وscript_status ready",
              [c["tools"][0]["name"] for c in calls] == ["report_speakers", "report_reel_script"] and d172["script_status"] == "ready" and out["status"] == "ready", out)
        check("g172: الترتيب الإلزامي للمشاهد",
              kinds == ["cold_open_clip", "title_card", "clip", "narration", "clip", "narration", "question",
                        "outro"], kinds)
        est = reel_script.estimate_seconds(sc, cfg)
        check("g172: المدة المقدَّرة بين 60 و120", 60 <= est <= 120, est)
        check("g174: الراوي male بعد ريل female محفوظ", sc.get("narrator") == "male", sc.get("narrator"))
        cold = sc["scenes"][0]
        check("g172: المقطع مملوء بالكود من النقطة (رابط/نافذة/متحدث/قناة/ترجمة)",
              cold["video_url"] == pa["video_url"] and cold["start"] == s40 and cold["end"] == e40
              and cold["speaker_name"] == "إسحاق بريك" and cold["channel_display"]
              and cold["quote_arabic"] == pa["quote_arabic"] and cold["language"] != "ar", cold)
        check("g172: العناوين الثلاثة في headlines والشاشة title مستقل",
              d172["headlines"] == ["هل يتغير الموقف؟", "عنوان ب", "عنوان ج"] and sc["title"] == "عنوان الشاشة")
        prompt = json.dumps(wcalls()[0].get("messages"), ensure_ascii=False)
        check("g172: مدخل النموذج: النص ومعرّفات الصالحة وتاريخ الفيديو وجنس الراوي، لا غير الصالحة",
              "نص مقال الموضوع" in prompt and a_id in prompt and "2099-10-30" in prompt and "male" in prompt
              and "رامي خوري" not in prompt)
        check("g172: لا temperature ويُستعمل نموذج المقال",
              "temperature" not in wcalls()[0] and wcalls()[0]["model"] == cfg.path("youtube.article.model"))

        # ── g175) names_audit على السيناريو، والمحرر يستقبل المقاطع بتواريخها ──
        check("g175: names_audit مرّ على نص السيناريو كله ومصدره اقتباسات النقاط الأصلية",
              len(audits) == 2 and "عنوان الشاشة" in audits[-1]["title"] and narr1 in audits[-1]["body"]
              and HE40 in audits[-1]["sources"], audits)
        check("g175: تدقيق المتحدثين يسبق تدقيق الراوي (مسودة وسيطة بلا عنوان)",
              audits[-2]["title"] == "" and "إسحاق بريك" in audits[-2]["body"], audits[-2])
        msg = json.dumps(edits[0]["messages"], ensure_ascii=False) if edits else ""
        check("g175: المحرر بمُكيِّف reel: مقاطع بتواريخها وسطور القراءة فقط",
              len(edits) == 1 and "2099-10-30" in msg and pa["video_url"] in msg and a_id in msg, msg[:300])
        check("g175: editor_review محفوظ على المسودة", "editor_review" in d172, list(d172))
        check("g175: مسار reel في editor.paths", cfg.path("editor.paths.reel") is True)

        # ── g173) مقطع ليس من الصالحة، أو ترتيب خاطئ ← إعادة واحدة بالسبب ثم failed ──
        calls.clear()
        bad_scenes = good_scenes()
        bad_scenes[2] = {"kind": "clip", "point_id": "ffffffffffff"}
        wrong_order = list(reversed(good_scenes()))
        queue[:] = [{"title": "ع", "question": "س؟", "scenes": bad_scenes},
                    {"title": "ع", "question": "س؟", "scenes": wrong_order}]
        d173 = new_draft("e2e2e2e2e2e2")
        reel_script.write_for_draft(d173, topic, points, "", unresolved, cfg)
        retry_msg = json.dumps(wcalls()[1]["messages"], ensure_ascii=False) if len(wcalls()) > 1 else ""
        check("g173: نداءا كتابة بالضبط (إعادة واحدة) ثم failed",
              len(wcalls()) == 2 and d173["script_status"] == "failed", (len(wcalls()), d173.get("script_status")))
        check("g173: الإعادة تذكر سبب الرفض الأول", "ffffffffffff" in retry_msg, retry_msg[-300:])
        check("g173: السبب النهائي (الترتيب) محفوظ ولا script",
              "الترتيب" in d173["script_error"] and not d173.get("script"), d173.get("script_error"))
        calls.clear()
        queue[:] = [{"title": "ع", "question": "س؟", "scenes": bad_scenes},
                    {"title": "ع", "question": "س؟", "scenes": good_scenes()}]
        d173b = new_draft("e3e3e3e3e3e3")
        reel_script.write_for_draft(d173b, topic, points, "", unresolved, cfg)
        check("g173: الإعادة الناجحة تُقبل (نداءا كتابة وready)", len(wcalls()) == 2 and d173b["script_status"] == "ready")
        short = good_scenes()
        short[3]["text"] = "قصير"
        short[5]["text"] = "قصير"
        queue[:] = [{"title": "ع", "question": "س؟", "scenes": short}] * 2
        d173c = new_draft("e4e4e4e4e4e4")
        reel_script.write_for_draft(d173c, topic, points, "", unresolved, cfg)
        check("g173: مدة تحت 60 ← failed بسبب المدة",
              d173c["script_status"] == "failed" and "المدة" in d173c["script_error"], d173c.get("script_error"))

        # ═════ المرحلة 2: العرض والقراءة ═════
        reset_drafts()
        queue.clear()
        rd = new_draft("c1c1c1c1c1c1")
        reel_script.write_for_draft(rd, topic, points, "", unresolved, cfg)
        store.save_draft(rd)
        reel_id = rd["id"]

        # ── g176) العرض ──
        s2 = yp.build_review_body([store.load_draft(reel_id)[1]], "u/r", "main", cfg)
        check("g176: جدول زمني بمقطع يبدأ [0:00 ورابط الفيديو &t=",
              "[0:00–0:15] 🎥 مقطع" in s2 and "https://youtube.com/watch?v=v1&t=99" in s2, s2[:1500])
        check("g176: المقطع: الاسم · الصفة · القناة · «الاقتباس»",
              "إسحاق بريك" in s2 and "«" + pa["quote_arabic"] + "»" in s2
              and rd["script"]["scenes"][0]["channel_display"] in s2)
        i_blk = s2.find(f"<!-- reelscript:{reel_id} -->")
        blk = s2[i_blk:s2.find("```", s2.find("```text", i_blk) + 7)] if i_blk >= 0 else ""
        check("g176: كتلة ```text قابلة للتعديل بسطر لكل [n] للعنوان والراوي والسؤال",
              "```text" in blk and "[2] عنوان الشاشة" in blk and f"[4] {narr1}" in blk
              and "[7] ما رأيك؟" in blk and "[1]" not in blk and "[3]" not in blk, blk)
        check("g176: عناوين hl: الثلاثة، والعنوان وجنس الراوي والمدة المقدَّرة",
              all(f"<!-- hl:{reel_id}:{k} -->" in s2 for k in range(3)) and "موضوع الريل" in s2
              and T["narrator_" + rd["script"]["narrator"]] in s2 and "ث" in s2)
        check("g176: خيارا go1 وgo3 فقط، ونص go3 من config",
              f"<!-- go:go1:{reel_id} -->" in s2 and f"<!-- go:go3:{reel_id} -->" in s2
              and f"go:go2:{reel_id}" not in s2 and f"go:publish:{reel_id}" not in s2
              and T["go3"] in s2, s2[-600:])
        failed = new_draft("c2c2c2c2c2c2", script_status="failed", script_error="لا مقاطع كافية: 1 من 2")
        s2f = yp.build_review_body([failed], "u/r", "main", cfg)
        check("g176: المسودة الفاشلة تُعرض بسببها مع go1 وحده",
              "لا مقاطع كافية: 1 من 2" in s2f and f"go:go1:{failed['id']}" in s2f
              and f"go:go3:{failed['id']}" not in s2f and "reelscript" not in s2f)

        def run_main(body, number):
            msgs: list[str] = []
            saved = (publish_mod.fetch_issue, review.comment, review.close_issue, review.remove_label, sys.argv)
            real_load = publish_mod.load_config
            publish_mod.load_config = lambda *a, **k: cfg     # main يقرأ الإعداد بنفسه: المفتاح مشغَّل هنا
            publish_mod.fetch_issue = lambda n: {"number": n, "body": body,
                                                 "labels": [{"name": "youtube-review"}, {"name": "approved"}]}
            review.comment = lambda n, t: msgs.append(t)
            review.close_issue = lambda n: None
            review.remove_label = lambda n, lbl: None
            sys.argv = ["publish", "--issue", str(number), "--skip-urgent"]
            try:
                publish_mod.main()
            finally:
                (publish_mod.fetch_issue, review.comment, review.close_issue, review.remove_label, sys.argv) = saved
                publish_mod.load_config = real_load
            return msgs

        # ── g177) تعديل سطر الراوي [4] ← يُطبَّق على المشهد 4 ──
        edited = s2.replace(f"[4] {narr1}", "[4] نص راوٍ معدَّل بيد المراجع")
        edited = edited.replace("[7] ما رأيك؟", "[7] سؤال معدَّل؟")
        run1 = run_main(tick_marker(edited, f"go:go3:{reel_id}"), 9101)
        got = store.load_draft(reel_id)[1]
        scenes = got["script"]["scenes"]
        check("g177: المشهد 4 صار النص المعدَّل والسؤال والباقي كما هو",
              scenes[3]["text"] == "نص راوٍ معدَّل بيد المراجع" and scenes[6]["text"] == "سؤال معدَّل؟"
              and got["script"]["question"] == "سؤال معدَّل؟" and scenes[5]["text"] == narr2, scenes[3])

        # ── g178) go3 للريل ← approved_script وrender_status queued وتعليق ولا نشر ──
        check("g178: status approved_script وrender_status queued",
              got["status"] == "approved_script" and got["render_status"] == "queued", got["status"])
        check("g178: التعليق «✅ اعتُمد السيناريو — شغّل «🎬 تركيب الريل» من Actions لتركيبه»",
              any("✅ اعتُمد السيناريو — شغّل «🎬 تركيب الريل» من Actions لتركيبه" in m for m in run1), run1)
        check("g178: لا نشر ولا بطاقة",
              not got.get("image") and not got.get("published_at") and got["status"] != "published")

        # سطر محذوف أو رقم غير موجود ← يُتجاهل مع تنبيه
        store.update_draft(store.load_draft(reel_id)[0], status="pending", remove=["render_status"])
        odd = s2.replace(f"[4] {narr1}\n", "").replace("[2] عنوان الشاشة",
                                                       "[99] لا مشهد بهذا الرقم\n[2] عنوان الشاشة")
        run2 = run_main(tick_marker(odd, f"go:go3:{reel_id}"), 9102)
        got2 = store.load_draft(reel_id)[1]
        check("g177: سطر محذوف/رقم غير موجود ← يُتجاهل مع تنبيه ويبقى النص",
              got2["script"]["scenes"][3]["text"] == "نص راوٍ معدَّل بيد المراجع"
              and any("99" in m and "[4]" in m for m in run2), run2)

        # ترك الريل بلا تعليم = رفضه
        store.update_draft(store.load_draft(reel_id)[0], status="pending", remove=["render_status"])
        run_main(s2, 9103)
        check("g178: ريل بلا تعليم ← مرفوض", store.load_draft(reel_id)[1]["status"] == "rejected")

        # ── g179) ملاحظة high غير مطبَّقة ← go3 لا يُنفَّذ ويبقى pending مع تعليق البوابة ──
        gd = new_draft("c3c3c3c3c3c3")
        reel_script.write_for_draft(gd, topic, points, "", unresolved, cfg)
        gd["editor_review"] = {"applied": [], "error": None, "speaker_unresolved": [],
                               "notes": [{"category": "other", "severity": "high", "location": "body",
                                          "original": "", "fix": "", "note": "ادّعاء بلا سند", "sources": []}]}
        store.save_draft(gd)
        s2g = yp.build_review_body([store.load_draft(gd["id"])[1]], "u/r", "main", cfg)
        run3 = run_main(tick_marker(s2g, f"go:go3:{gd['id']}"), 9104)
        gg = store.load_draft(gd["id"])[1]
        check("g179: go3 لم يُنفَّذ والبند pending في المرحلة 2",
              gg["status"] == "pending" and "render_status" not in gg, gg["status"])
        check("g179: تعليق البوابة بسبب المحرر", any("ادّعاء بلا سند" in m for m in run3), run3)
        check("g179: قسم المحرر في العرض", "ادّعاء بلا سند" in s2g)

        # ── g180) reel.enabled=false ← لا شيء من هذا ──
        off_body = yp.build_review_body([store.load_draft(reel_id)[1]], "u/r", "main", cfg_off)
        check("g180: المفتاح مطفأ ← لا جدول ولا كتلة تعديل",
              "reelscript" not in off_body and "🎥 مقطع" not in off_body, off_body[:300])
        calls.clear()
        d180 = new_draft("c4c4c4c4c4c4")
        res = publish_mod._write_reel_script(d180, D, cfg_off, None, None)
        check("g180: لا كتابة سيناريو ولا نداء",
              not calls and res is None and d180.get("script_status") == "awaiting_script",
              (len(calls), d180.get("script_status")))
    finally:
        reel_script._create = real["create"]
        names_audit.run = real["audit"]
        ya.generate_headlines = real["hl"]
        reel_editor._create = real["ed_create"]


def test_reel_speaker_audit_guards() -> None:
    """تدقيق أسماء المتحدثين في مقاطع الريل قبل كتابة السيناريو (Issue #1343، g181–g185)."""
    import json
    from types import SimpleNamespace

    from src import names_audit, reel_editor, reel_script
    from src import youtube_article as ya
    from src import youtube_publish as yp

    cfg = load_config()
    cfg.setdefault("reel", {})["enabled"] = True
    D = "2099-11-02"

    def pt(i, speaker, ts):
        return {"video_id": f"w{i}", "bloc": "arabic", "channel": "الجزيرة", "speaker": speaker,
                "statement": f"قول {i}", "quote_arabic": f"اقتباس {i}", "quote_original": " ".join(["كلمة"] * 20),
                "type": "fact", "video_title": f"فيديو {i}", "video_url": f"https://youtube.com/watch?v=w{i}",
                "timestamp": ts, "video_published": "2099-10-30",
                "video_description": "Dışişleri Bakanı Hakan Fidan" if i == 1 else ""}

    pa, pb, pc = pt(1, "حقان فيدان", 100), pt(2, "ليلى حداد", 200), pt(3, "مجهول الهوية", 300)


    pa, pb, pc = pt(1, "حقان فيدان", 100), pt(2, "ليلى حداد", 200), pt(3, "مجهول الهوية", 300)
    ids = {p["speaker"]: reel_script.point_key_id(p) for p in (pa, pb, pc)}
    calls: list = []
    narr = " ".join(f"س{i}" for i in range(45))
    narr2 = " ".join(f"ص{i}" for i in range(45))

    def fake_create(client, **kw):
        calls.append(kw)
        if kw["tools"][0]["name"] == "report_speakers":
            # فيدان موثَّق من الوصف (R2c)؛ الباقون بلا اسم لاتيني فيبقون ضيوفًا غير موثَّقين
            rows = [{"point_id": ids["حقان فيدان"], "name_latin": "Hakan Fidan", "name_arabic": "حقان فيدان",
                     "role_arabic": "وزير الخارجية"}]
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="report_speakers",
                                                            input={"speakers": rows})],
                                   stop_reason="tool_use", usage=SimpleNamespace(input_tokens=1, output_tokens=1))
        scenes = [{"kind": "cold_open_clip", "point_id": ids["حقان فيدان"]}, {"kind": "title_card", "text": "ع"},
                  {"kind": "narration", "text": narr}, {"kind": "clip", "point_id": ids["ليلى حداد"]},
                  {"kind": "narration", "text": narr2}, {"kind": "clip", "point_id": ids["مجهول الهوية"]},
                  {"kind": "narration", "text": " ".join(f"ض{i}" for i in range(20))}, {"kind": "question", "text": "ما رأيك؟"},
                  {"kind": "outro"}]
        data = {"title": "ع", "question": "ما رأيك؟", "scenes": scenes}
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="report_reel_script", input=data)],
                               stop_reason="tool_use", usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    def fake_audit(draft, sources, c):
        body = draft["arabic"]["post_body"]
        if draft["arabic"]["post_title"] == "":  # تدقيق المتحدثين (مسودة وسيطة بلا عنوان)
            draft["arabic"]["post_body"] = body.replace("حقان", "هاكان")
            if "مجهول" in body:
                draft["name_unresolved"] = [{"arabic": "مجهول الهوية", "latin": "X", "reason": "x"}]
            draft["name_corrections"] = [{"from": "حقان فيدان", "to": "هاكان فيدان"}]
        else:  # تدقيق نص الراوي
            draft["name_unresolved"] = [{"arabic": "اسم راوٍ", "latin": "Y", "reason": "y"}]
        return {}

    real = {"create": reel_script._create, "audit": names_audit.run, "hl": ya.generate_headlines,
            "ed": reel_editor._create}
    reel_script._create = fake_create
    names_audit.run = fake_audit
    ya.generate_headlines = lambda *a, **k: (["هل؟", "ب", "ج"], None, None)
    reel_editor._create = lambda client, **kw: SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name="report_review", input={"notes": []})],
        usage=SimpleNamespace(server_tool_use=None))
    topic = {"id": "aaaa1111bbbb", "title": "موضوع", "event": "حدث"}

    def new_draft(i):
        d = yp.build_reel_draft({"id": "aaaa1111bbbb", "title": "موضوع", "layer": "a", "blocs": ["arabic"],
                                 "channels": ["الجزيرة"], "agreement": "agreement", "event": "حدث"}, D, cfg)
        d["id"] = i
        return d

    try:
        # أ + ب + د: ثلاثة مقاطع، بلا مسودة مقال شقيقة (unresolved فارغة)، أحدها غير محسوم
        d = new_draft("f1f1f1f1f1f1")
        out = reel_script.write_for_draft(d, topic, [pa, pb, pc], "", [], cfg)
        sc = d.get("script") or {}
        clips = [s for s in sc.get("scenes", []) if s["kind"] in reel_script.CLIP_KINDS]
        tl = "\n".join(reel_script.timeline_lines(sc, cfg))
        check("g181: «حقان فيدان» ← «هاكان فيدان» في الشريط السفلي",
              out["status"] == "ready" and bool(clips) and clips[0]["speaker_name"] == "هاكان فيدان", out)
        check("g181: الجدول الزمني يعرض المصحَّح", "هاكان فيدان" in tl and "حقان" not in tl, tl)
        # R2c (#1377): لا استبعاد بالاسم؛ المقطع يبقى بشريط «ضيف على X» ولا يظهر اسمه في مشهد ولا في مدخل الكاتب
        check("g182/g184: غير المحسوم يبقى بشريط «ضيف على X» ولا يظهر اسمه في مشهد ولا في مدخل الكاتب",
              len(clips) == 3 and "مجهول" not in json.dumps(sc, ensure_ascii=False)
              and "ضيف على" in reel_script.speaker_band({"channel_display": "الجزيرة"}, cfg)
              and "مجهول" not in json.dumps(calls[-1].get("messages"), ensure_ascii=False), len(clips))
        names = [x.get("arabic") for x in d.get("name_unresolved") or []]
        # R2c: تدقيق المتحدثين يخص الموثَّق وحده، فغير الموثَّق «مجهول الهوية» لا يدخل المدقق أصلًا
        check("g185: name_unresolved يحمل تدقيق الراوي ولا يحمل غير الموثَّق (لا اسم له يُدقَّق)",
              "اسم راوٍ" in names and "مجهول الهوية" not in names, names)
        check("g185: name_corrections باقية", bool(d.get("name_corrections")), d.get("name_corrections"))

        # ج: مقطعان صالحان أحدهما غير محسوم ← فشل بلا نداء
        calls.clear()
        d2 = new_draft("f2f2f2f2f2f2")
        out = reel_script.write_for_draft(d2, topic, [pa, pc], "", [], cfg)
        check("g183: المقطع غير المحسوم لا يُستبعد (R2c): لا «لا مقاطع كافية» ولا «غير محسومة» وقد نودي النموذج",
              "لا مقاطع كافية" not in (d2.get("script_error") or "")
              and "غير محسومة" not in (d2.get("script_error") or "") and bool(calls),
              (d2.get("script_error"), len(calls)))
    finally:
        reel_script._create = real["create"]
        names_audit.run = real["audit"]
        ya.generate_headlines = real["hl"]
        reel_editor._create = real["ed"]


def test_reel_identity_r2c_guards() -> None:
    """هوية متحدث الريل من عنوان الفيديو ووصفه لا من رسم الاسم في الصحافة العربية (Issue #1377، R2c، g186–g192).
    الحادثة: ريل f75f529f4845 فشل «0 صالحًا من 2» لاسم تركي لا تكتب عنه الصحافة العربية. التوثيق يقرّره الكود."""
    import json
    from types import SimpleNamespace

    from src import names_audit, reel_editor, reel_script
    from src import youtube_article as ya
    from src import youtube_extract as ye
    from src import youtube_publish as yp

    cfg = load_config()
    cfg.setdefault("reel", {})["enabled"] = True
    D = "2099-11-03"
    SPEAKER = "نيهال بينجه سو كاراجا كاتبة صحافية هابرتورك"
    DESC = "Bugünün konuğu\nKonuk: Nihal Bengisu Karaca\nProgram"

    def pt(i, speaker, ts, desc="", title="Gündem Özel"):
        return {"video_id": f"r{i}", "bloc": "turkish", "channel": "هابرتورك", "speaker": speaker,
                "statement": f"قول {i}", "quote_arabic": f"اقتباس {i}", "quote_original": " ".join(["kelime"] * 20),
                "type": "fact", "video_title": title, "video_description": desc,
                "video_url": f"https://youtube.com/watch?v=r{i}", "timestamp": ts, "video_published": "2099-10-30"}

    pa = pt(1, SPEAKER, 100, DESC)
    pb = pt(2, "جميل إبراهيم", 200, "")
    ids = {p["speaker"]: reel_script.point_key_id(p) for p in (pa, pb)}
    answer = {"speakers": [
        {"point_id": ids[SPEAKER], "name_latin": "Nihal Bengisu Karaca", "name_arabic": "نهال بنكيسو قره جا",
         "role_arabic": "كاتبة صحفية"},
        {"point_id": ids["جميل إبراهيم"], "name_latin": "Çetiner Çetin", "name_arabic": "تشتينر تشتين",
         "role_arabic": "محلل"}]}
    mode = {"fail": False}
    calls: list = []
    narr = " ".join(f"س{i}" for i in range(45))
    narr2 = " ".join(f"ص{i}" for i in range(45))

    def fake_create(client, **kw):
        calls.append(kw)
        tools = kw.get("tools") or []
        if tools and tools[0]["name"] == "report_speakers":
            if mode["fail"]:
                raise RuntimeError("boom")
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="report_speakers", input=answer)],
                                   stop_reason="tool_use", usage=SimpleNamespace(input_tokens=1, output_tokens=1))
        scenes = [{"kind": "cold_open_clip", "point_id": ids[SPEAKER]}, {"kind": "title_card", "text": "ع"},
                  {"kind": "narration", "text": narr}, {"kind": "clip", "point_id": ids["جميل إبراهيم"]},
                  {"kind": "narration", "text": narr2}, {"kind": "question", "text": "ما رأيك؟"},
                  {"kind": "outro"}]
        data = {"title": "ع", "question": "ما رأيك؟", "scenes": scenes}
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="report_reel_script", input=data)],
                               stop_reason="tool_use", usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    real = {"create": reel_script._create, "audit": names_audit.run, "hl": ya.generate_headlines,
            "ed": reel_editor._create}
    reel_script._create = fake_create
    names_audit.run = lambda draft, sources, c: {}
    ya.generate_headlines = lambda *a, **k: (["هل؟", "ب", "ج"], None, None)
    reel_editor._create = lambda client, **kw: SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name="report_review", input={"notes": []})],
        usage=SimpleNamespace(server_tool_use=None))
    try:
        # ── أ) موثَّق: الاسم من الوصف، والصفة والقناة لا تدخلان الاسم ──
        valid = reel_script.valid_clips([pa, pb], [], cfg)
        got = {c["point_id"]: c for c in reel_script.identify_speakers(valid, [pa, pb], cfg)}
        a = got[ids[SPEAKER]]
        check("g186: الاسم اللاتيني في وصف الفيديو ← موثَّق من الوصف",
              a["speaker_verified"] is True and a["speaker_verified_from"] == "description", a)
        check("g186: speaker_name بلا «كاتبة» ولا «هابرتورك» والصفة وحدها في speaker_role",
              a["speaker_name"] == "نهال بنكيسو قره جا" and "كاتبة" not in a["speaker_name"]
              and "هابرتورك" not in a["speaker_name"] and a["speaker_role"] == "كاتبة صحفية"
              and a["speaker_name_latin"] == "Nihal Bengisu Karaca", a)

        # ── ب) اسم لا يرد في العنوان ولا الوصف ← غير موثَّق ولو قال النموذج ──
        b = got[ids["جميل إبراهيم"]]
        band = reel_script.speaker_band(b, cfg)
        check("g187: «Çetiner Çetin» غائب عن العنوان والوصف ← غير موثَّق بلا اسم ولا صفة",
              b["speaker_verified"] is False and b["speaker_name"] == "" and b["speaker_role"] == "", b)
        check("g187: الشريط «ضيف على هابرتورك»", band == "ضيف على هابرتورك", band)

        # ── ج) المطابقة: حروف صغيرة، وتركية، وكلمات متتالية ──
        v = reel_script.verify_latin
        check("g188: وصف بحروف صغيرة ← موثَّق", v("Nihal Bengisu Karaca", "", "nihal bengisu karaca") == "description")
        check("g188: وصف بحروف تركية كبيرة (İ/Ç) ← موثَّق",
              v("Nihal Bengisu Karaca", "", "NİHAL BENGİSU KARACA") == "description")
        check("g188: «Çetiner» مقابل «Cetiner» (علامات لاتينية) ← موثَّق من العنوان",
              v("Çetiner Çetin", "Cetiner Cetin ile gündem", "") == "title")
        check("g188: كلمات غير متتالية ← غير موثَّق", v("Nihal Karaca", "", "Nihal Bengisu Karaca") == "")
        check("g188: اسم فارغ ← غير موثَّق", v("", "x", "x") == "")
        check("g188: «Işık Kuşçu» مقابل «ISIK KUSCU» (ı/İ التركيتان) ← موثَّق",
              v("Işık Kuşçu", "", "ISIK KUSCU") == "description"
              and v("İsmail Işık", "", "ISMAIL ISIK") == "description")

        # ── د) مسودة شقيقة name_unresolved فيها الاسم ← لا يُستبعد المقطع ──
        unresolved = [{"arabic": "نيهال بينجه سو كاراجا", "latin": "Nihal", "reason": "x"},
                      {"arabic": "جميل إبراهيم", "latin": "J", "reason": "x"}]
        check("g189: valid_clips لا تستبعد بـname_unresolved ولا بـrole_words",
              len(reel_script.valid_clips([pa, pb, pt(3, "محلل عسكري", 300)], unresolved, cfg)) == 3)
        topic = {"id": "aaaa1111bbbb", "title": "موضوع", "event": "حدث"}
        d = yp.build_reel_draft({"id": "aaaa1111bbbb", "title": "موضوع", "layer": "a", "blocs": ["turkish"],
                                 "channels": ["هابرتورك"], "agreement": "agreement", "event": "حدث"}, D, cfg)
        d["id"] = "c1c1c1c1c1c1"
        out = reel_script.write_for_draft(d, topic, [pa, pb], "", unresolved, cfg)
        clips = [s for s in (d.get("script") or {}).get("scenes", []) if s["kind"] in reel_script.CLIP_KINDS]
        tl = "\n".join(reel_script.timeline_lines(d.get("script") or {}, cfg))
        check("g189: السيناريو يُكتب بمقطعين رغم name_unresolved", out["status"] == "ready" and len(clips) == 2, out)
        check("g189: شريط الموثَّق باسمه وصفته وقناته وعلامة الوصف في المرحلة 2",
              "نهال بنكيسو قره جا" in tl and "كاتبة صحفية" in tl and "✅ موثَّق من وصف الفيديو" in tl, tl)
        check("g189: شريط غير الموثَّق «ضيف على هابرتورك» و«👤 ضيف غير مسمّى»",
              "ضيف على هابرتورك" in tl and "👤 ضيف غير مسمّى" in tl, tl)
        check("g189: الموثَّق الذي اسمه في name_unresolved يُبلَّغ للمحرر تنبيهًا",
              reel_editor.ADAPTER.speakers_unresolved(
                  {"name_unresolved": [{"arabic": "نهال بنكيسو قره جا", "latin": "N", "reason": "x"},
                                       {"arabic": "تشتينر تشتين", "latin": "C", "reason": "x"}]},
                  {"valid": reel_script.identify_speakers(valid, [pa, pb], cfg)})
              == ["نهال بنكيسو قره جا"])

        # ── هـ) الراوي يسمّي متحدثًا غير موثَّق ← رفض ──
        mode["fail"] = True
        unv = reel_script.identify_speakers(reel_script.valid_clips([pa, pb], [], cfg), [pa, pb], cfg)
        mode["fail"] = False
        script = {"narrator": "female", "title": "ع", "question": "ما رأيك؟", "scenes": [
            {"kind": "cold_open_clip", "point_id": ids[SPEAKER], "start": 99, "end": 114},
            {"kind": "title_card", "text": "ع"},
            {"kind": "narration", "text": narr + " كاراجا"},
            {"kind": "clip", "point_id": ids["جميل إبراهيم"], "start": 199, "end": 214},
            {"kind": "narration", "text": narr2}, {"kind": "question", "text": "ما رأيك؟"}, {"kind": "outro"}]}
        reasons = reel_script.validate(script, unv, cfg, 2)
        check("g190: «كاراجا» في كلام الراوي لمتحدث غير موثَّق ← «سُمّي متحدث غير موثَّق»",
              any("سُمّي متحدث غير موثَّق" in r for r in reasons), reasons)
        script["scenes"][2]["text"] = narr
        check("g190: الراوي بلا الاسم ← لا رفض لهذا السبب",
              not any("سُمّي متحدث غير موثَّق" in r for r in reel_script.validate(script, unv, cfg, 2)))

        # ── و) فشل identify_speakers ← الكل غير موثَّق والسيناريو يُكتب ──
        check("g191: فشل النداء ← كل المقاطع غير موثَّقة", all(not c["speaker_verified"] for c in unv), unv)
        mode["fail"] = True
        d2 = yp.build_reel_draft({"id": "aaaa1111bbbb", "title": "موضوع", "layer": "a", "blocs": ["turkish"],
                                  "channels": ["هابرتورك"], "agreement": "agreement", "event": "حدث"}, D, cfg)
        d2["id"] = "c2c2c2c2c2c2"
        out2 = reel_script.write_for_draft(d2, topic, [pa, pb], "", [], cfg)
        mode["fail"] = False
        check("g191: السيناريو يُكتب (ready) بلا فشل", out2["status"] == "ready", out2)
        check("g191: مدخل الكاتب فيه تعليمة عدم تسمية غير الموثَّق وشريط «ضيف على»",
              "ضيف على هابرتورك" in json.dumps(calls[-1].get("messages"), ensure_ascii=False)
              or any("ضيف على هابرتورك" in json.dumps(c.get("messages"), ensure_ascii=False) for c in calls))
    finally:
        reel_script._create = real["create"]
        names_audit.run = real["audit"]
        ya.generate_headlines = real["hl"]
        reel_editor._create = real["ed"]

    # ── ز) الاستخراج يحفظ وصف الفيديو مقصوصًا ──
    mx = int(cfg.path("youtube.extract.description_max_chars", 0))
    vid = SimpleNamespace(description="و" * (mx + 500) if mx else "و" * 5000)
    clipped = ye.video_description(vid, cfg)
    check("g192: description_max_chars = 1500 والوصف يُقصّ إليه", mx == 1500 and len(clipped) == 1500, (mx, len(clipped)))
    check("g192: وصف قصير يبقى كما هو ونقطة قديمة بلا وصف تعمل",
          ye.video_description(SimpleNamespace(description="Konuk: X"), cfg) == "Konuk: X"
          and reel_script.valid_clips([{**pb, "video_description": None}], [], cfg)[0]["video_description"] == "")


def test_important_h7_guards() -> None:
    """Issue #1345 (هام-7): الحالات الذهبية أ–ز على شاهد حقيقي (tests/fixtures/important/1339/: نتيجة الحكم
    1339.json والمسودتان b20c26059d4c و4421a96074e8 كما حُفظتا). تُكتب قبل الكود: مصادر لبنانية، مؤيِّد جهة بلا
    تاريخ، تاريخ المصدر في التصنيف، «الأقرب» القديم، حذف المحرر، وصيغة الأشهر."""
    import copy
    import json
    from datetime import datetime, timedelta, timezone

    from src import article, date_style, editor, important, important_editor, important_write
    from tests.helpers import IMPORTANT_FIXTURES, ImportantWriteRig

    cfg = load_config()
    fx = IMPORTANT_FIXTURES / "1339"
    real = json.loads((fx / "1339.json").read_text(encoding="utf-8"))
    d4421 = json.loads((fx / "4421a96074e8.json").read_text(encoding="utf-8"))

    # ── أ) المصادر اللبنانية المقبولة والحزبية المستبعدة ──
    ours = ["https://www.lbcgroup.tv/news/x", "https://www.elnashra.com/news/show/1", "https://www.mtv.com.lb/news/1",
            "https://www.annahar.com/arabic/article/1"]
    outs = ["https://www.almanar.com.lb/1", "https://al-akhbar.com/Politics/1", "https://www.kataeb.org/news/1"]
    check("(h7-أ) lbcgroup.tv وelnashra.com وmtv.com.lb وannahar.com من مصادرنا",
          all(important._is_our_source("", u, cfg) for u in ours),
          [important._is_our_source("", u, cfg) for u in ours])
    check("(h7-أ) almanar.com.lb وal-akhbar.com وkataeb.org خارج مصادرنا",
          not any(important._is_our_source("", u, cfg) for u in outs),
          [important._is_our_source("", u, cfg) for u in outs])
    pa = cfg.path("important.publisher_ar") or {}
    check("(h7-أ) أسماء الناشرين اللبنانيين بالعربية",
          all(v in pa.values() for v in ("إل بي سي آي", "النهار", "لوريان لوجور", "المدن", "النشرة", "إم تي في")),
          list(pa.values())[-12:])

    # ── ب) مؤيِّد من موقع الجهة بلا تاريخ لا يكفي وحده ──
    ev = "فرضت الولايات المتحدة عقوبات جديدة على شبكة التمويل المعنية"

    def judge(case, docs, rules):
        marker = f"كلمةسبعة{case}"
        pt = {"claim": f"{ev} {marker}", "entities": [marker], "queries": [{"lang": "ar", "q": marker}]}

        def classify(point, names):
            return {"sources": [important_stance(n, *rules.get(n, ("irrelevant", ""))) for n in names]}
        with ImportantRig([pt], {marker: [dict(d, text=d["text"] + f" {marker}") for d in docs]}, classify,
                          strict_known=True):
            important.judge("نص الـIssue كاملًا", 98700 + case, cfg)
        return important.load_saved(98700 + case)["points"][0]

    state_doc = important_doc("U.S. Department of State", ev + ".", link="https://www.state.gov/translations/abc")
    p_b1 = judge(1, [state_doc], {"U.S. Department of State": ("supports", ev)})
    check("(h7-ب) مؤيِّد وحيد صفحة state.gov بلا تاريخ ← not_found",
          p_b1["verdict"] == "not_found", (p_b1["verdict"], p_b1.get("note")))
    check("(h7-ب) مع تنبيه «مؤيِّد من موقع الجهة بلا تاريخ معروف»",
          any("مؤيِّد من موقع الجهة بلا تاريخ معروف" in w and "U.S. Department of State" in w
              and "لم يُعتمد وحده" in w for w in p_b1.get("warnings") or []), p_b1.get("warnings"))
    lbc_doc = important_doc("LBCI", ev + ".", link="https://www.lbcgroup.tv/news/2026/10/07/x")
    p_b2 = judge(2, [state_doc, lbc_doc], {"U.S. Department of State": ("supports", ev), "LBCI": ("supports", ev)})
    check("(h7-ب) النقطة نفسها مع مؤيِّد إضافي من lbcgroup.tv مؤرَّخ ← confirmed",
          p_b2["verdict"] == "confirmed", (p_b2["verdict"], p_b2.get("note")))

    # ── ج) مدخل _classify يحمل تاريخ كل وثيقة وتاريخ اليوم ──
    sent: list = []
    saved = (article._ask_model_with_retry, article._client)
    article._ask_model_with_retry = lambda client, model, **kw: sent.append(kw) or ({"sources": []}, None)
    article._client = lambda: None
    try:
        important._classify("نقطة للاختبار", [
            {"name": "LBCI", "text": "نص أول", "link": "https://a.example/1", "doc_published": "2026-10-07"},
            {"name": "مجهول", "text": "نص ثانٍ", "link": "https://b.example/2", "doc_published": ""}], cfg)
    finally:
        article._ask_model_with_retry, article._client = saved
    blob = json.dumps(sent[0]["messages"], ensure_ascii=False) if sent else ""
    today = datetime.now(timezone.utc).date().isoformat()
    check("(h7-ج) المدخل فيه «(نُشر: 2026-10-07)» و«(تاريخ غير معروف)» وتاريخ اليوم",
          "(نُشر: 2026-10-07)" in blob and "(تاريخ غير معروف)" in blob and today in blob, blob[:400])
    check("(h7-ج) CLASSIFY_SYSTEM يمنع واقعة سابقة مشابهة من same_event",
          "واقعة سابقة مشابهة" in important.CLASSIFY_SYSTEM, "")

    # ── د) «الأقرب» القديم لا يُكتب ──
    result = copy.deepcopy(real)
    item = next(i for i in result["article_items"] if i["kind"] == "nearest")

    def respond(p, sy):
        return {"category": "عالم", "hashtags": ["هام"], "image_query_en": "news", "post_title": "عنوان خبري",
                "image_headline": "عنوان", "post_body": "نص " * 60}
    with ImportantWriteRig(respond, gap_sources=[]) as rig_d1:
        rig_d1.next = 98800
        out1 = important_write.write_article(result, item, cfg, [], 98750)
    check("(h7-د) مقتطفات BBC 2025-08-05 + الجزيرة بلا تاريخ ← لا نداء كاتب وسبب «لا مصدر حديث»",
          out1[0] is None and not rig_d1.calls and "لا مصدر حديث" in out1[1] and not out1[2], (out1[1], len(rig_d1.calls)))
    fresh = (datetime.now(timezone.utc).date() - timedelta(days=3)).isoformat()
    gap = [{"publisher": "LBCI", "link": "https://www.lbcgroup.tv/news/x",
            "excerpt": "أعلنت واشنطن موقفًا جديدًا من حزب الله وتمويله", "published": fresh, "question": "س؟"}]
    with ImportantWriteRig(respond, gap_sources=gap) as rig_d2:
        rig_d2.next = 98900
        out2 = important_write.write_article(copy.deepcopy(real), copy.deepcopy(item), cfg, [], 98751)
    check("(h7-د) مع مقتطف إضافي مؤرَّخ قبل 3 أيام ← يُنادى الكاتب",
          len(rig_d2.calls) >= 1 and "لا مصدر حديث" not in (out2[1] or ""), (out2[1], len(rig_d2.calls)))

    # ── هـ) حذف المحرر لا يقصّ وسط جملة ──
    clause = ("يبقى الربط الذي تطرحه الخطة الأمريكية واضحاً: استمرار سياسة خنق حزب الله مالياً يسير بالتوازي "
              "مع ملفات الانسحاب الإسرائيلي ووقف الاعتداءات على لبنان")
    broken = d4421["arabic"]["post_body"]
    before_body = broken.replace("الأمريكي، ،", f"الأمريكي، {clause}،", 1)
    check("(h7-هـ) المتن المُعاد بناؤه قبل الحذف يحوي المقطع", clause in before_body, before_body[-300:])

    def apply(body, original, fix=""):
        d = {"arabic": {"post_title": "عنوان", "post_body": body}, "headlines": ["عنوان"], "caption": ""}
        note = {"category": "unattributed_opinion", "severity": "high", "location": "body", "original": original,
                "fix": fix, "note": "رأي بلا نسبة", "sources": []}
        res = editor.apply_review(d, important_editor.ADAPTER, {}, [note], cfg)
        return d["arabic"]["post_body"], res
    new_body, res = apply(before_body, clause)
    check("(h7-هـ) fix فارغ على مقطع وسط جملة ← لا يُطبَّق ويبقى المتن كما هو والملاحظة معروضة",
          new_body == before_body and not res["applied"] and len(res["notes"]) == 1, (new_body[-200:], res))
    whole = "جملة أولى سليمة. هذه جملة كاملة من رأي الكاتب بلا نسبة. جملة ثالثة سليمة."
    new_whole, res_w = apply(whole, "هذه جملة كاملة من رأي الكاتب بلا نسبة.")
    check("(h7-هـ) جملة كاملة بـfix فارغ ← تُحذف",
          len(res_w["applied"]) == 1 and "هذه جملة كاملة" not in new_whole and "جملة ثالثة سليمة" in new_whole, new_whole)
    comma_body = "بين الضغطين، يرى المحلل أن الأمر كذلك، وهذا واضح."
    new_v, res_v = apply(comma_body, "يرى المحلل أن الأمر كذلك،", "")
    check("(h7-هـ) صمام «، ،»: تطبيق يُنتج فاصلتين متجاورتين ← يُلغى",
          not res_v["applied"] and new_v == comma_body, (new_v, res_v))
    junk_body = "مقدمة،\nرأي الكاتب بلا نسبة.\n، تتمة"
    new_f, res_f = apply(junk_body, "رأي الكاتب بلا نسبة.")
    check("(h7-هـ) صمام: حذف جملة كاملة يُنتج «،» ثم «،» ← يُلغى ويصير ملاحظة",
          not res_f["applied"] and len(res_f["notes"]) == 1 and new_f == junk_body, (new_f, res_f))

    # ── و) صيغة الأشهر ──
    def fx_(t):
        return date_style.normalize_text(t, cfg)
    check("(h7-و) «7-8 تشرين الأول/أكتوبر 2026» ← «7-8 أكتوبر/تشرين الأول 2026»",
          fx_("7-8 تشرين الأول/أكتوبر 2026") == "7-8 أكتوبر/تشرين الأول 2026", fx_("7-8 تشرين الأول/أكتوبر 2026"))
    check("(h7-و) «في 20 مارس 2026» ← «في 20 مارس/آذار 2026»",
          fx_("في 20 مارس 2026") == "في 20 مارس/آذار 2026", fx_("في 20 مارس 2026"))
    check("(h7-و) «مارس الضغط» بلا تغيير", fx_("مارس الضغط على الحزب") == "مارس الضغط على الحزب", "")
    q = "قال: «في 2 آذار 2026» وأضاف"
    check("(h7-و) داخل « » بلا تغيير", fx_(q) == q, fx_(q))
    check("(h7-و) «مايو/أيار» بلا تغيير", fx_("في 3 مايو/أيار 2026") == "في 3 مايو/أيار 2026", fx_("في 3 مايو/أيار 2026"))
    check("(h7-و) «شامي / ميلادي» بمسافات ← «ميلادي/شامي»",
          fx_("في 5 كانون الثاني / يناير 2026") == "في 5 يناير/كانون الثاني 2026", fx_("في 5 كانون الثاني / يناير 2026"))
    check("(h7-و) الإعداد والتعليمة في editor.system وarticle_instructions.common",
          "أكتوبر/تشرين الأول" in cfg.path("editor.system")
          and "أكتوبر/تشرين الأول" in cfg.path("important.article_instructions.common")
          and cfg.path("important.rules_version") == 7 and cfg.path("date_style.enabled") is True, "")

    # ── ح) فشل «الأقرب» القديم لا يفتح قضية ترشيح جديدة ──
    from src import important_finalize
    from tests.helpers import important_items_marked_body
    res8 = copy.deepcopy(real)
    res8["issue"] = 98990
    for it in res8["article_items"]:
        it["selection_issue"] = None
        it["status"] = "offered"
    near8 = next(i for i in res8["article_items"] if i["kind"] == "nearest")
    near8["selection_issue"] = 98991
    res8["selection_issue"] = 98991
    with ImportantWriteRig(respond, gap_sources=[]) as rig_h:
        rig_h.next = 99000
        important.save(res8)
        body8 = important_items_marked_body(res8, {near8["id"]: "go2"}, cfg)
        created_before = len(getattr(rig_h, "created", []) or [])
        important_finalize.run(98991, body8, cfg)
        saved8 = important.load_saved(98990)
        n8 = next(i for i in saved8["article_items"] if i["id"] == near8["id"])
        comments = " ".join(str(c) for c in (getattr(rig_h, "comments", []) or []))
    check("(h7-ح) «الأقرب» القديم: لا نداء كاتب", not rig_h.calls, len(rig_h.calls))
    check("(h7-ح) لا قضية ترشيح جديدة (selection_issue لم يُمسح ولا write_failed)",
          not n8.get("write_failed") and n8.get("selection_issue") == 98991
          and len(getattr(rig_h, "created", []) or []) == created_before, n8)
    check("(h7-ح) التعليق على قضية الترشيح موجود بسبب «لا مصدر حديث»", "لا مصدر حديث" in comments, comments[:300])

    # ── ز) عبر store.save_draft الحقيقي ──
    draft = {"id": "h7h7h7h7h7h7", "created_at": "2026-10-09T00:00:00+00:00", "status": "pending",
             "arabic": {"post_title": "عنوان", "post_body": "صدر البيان في 7 تشرين الأول/أكتوبر 2026 رسميًا."},
             "caption": "بيان 7 تشرين الأول/أكتوبر 2026", "headlines": ["بيان تشرين الأول/أكتوبر"]}
    path = store.save_draft(draft)
    saved_d = json.loads(path.read_text(encoding="utf-8"))
    check("(h7-ز) save_draft: post_body وheadlines وcaption بـ«أكتوبر/تشرين الأول»",
          "7 أكتوبر/تشرين الأول 2026" in saved_d["arabic"]["post_body"]
          and saved_d["headlines"] == ["بيان أكتوبر/تشرين الأول"]
          and "7 أكتوبر/تشرين الأول 2026" in saved_d["caption"], saved_d)


def test_reel_probe_r3a_guards() -> None:
    """قياس الريل قبل التركيب (Issue #1347، R3a): محدِّد الاقتباس، سلّم التنزيل، وصوت Google.
    المنزِّل والشبكة مزيَّفان؛ لا yt-dlp ولا طلب حقيقي."""
    import base64
    import os
    import tempfile
    from pathlib import Path

    from src import reel_clips, tts
    from tools import reel_clip_probe as rp

    cfg = load_config()
    line = "واحد اثنان ثلاثة اربعة خمسة ستة"
    segs = [(10, "واحد اثنان ثلاثة شيء آخر تمامًا"), (40, "كلام لا صلة له هنا"),
            (69, line + " سبعة ثمانية"), (90, "ختام")]
    quote = line
    got = reel_clips.locate_quote(quote, segs, 72, cfg)
    check("g181-أ: تكرار أول 3 كلمات مبكرًا ← found عند 69 لا 10",
          got["status"] == "found" and got["start"] == 69, got)

    two = [(20, "بداية الاقتباس هنا ثم"), (24, "يكتمل في السطر التالي كما ترى"), (60, "غير ذلك")]
    got = reel_clips.locate_quote("بداية الاقتباس هنا ثم يكتمل في السطر التالي", two, 22, cfg)
    check("g181-ب: اقتباس عابر لسطرين ← found وstart = بداية السطر الأول",
          got["status"] == "found" and got["start"] == 20, got)
    check("g181-ب: end = min(التالي، بداية الأخير + كلماته ÷ speaker_wps + clip_tail) = 27.6", got["end"] == 27.6, got)

    got = reel_clips.locate_quote("عبارة غير موجودة إطلاقًا في النص كله", segs, 50, cfg)
    check("g181-ج: غائب ← missing", got["status"] == "missing", got)
    amb = [(5, "واحد اثنان ثلاثة اولى"), (80, "واحد اثنان ثلاثة ثانية")]
    got = reel_clips.locate_quote("واحد اثنان ثلاثة مختلف تمامًا بعد ذلك", amb, 50, cfg)
    check("g181-ج: 3 كلمات بموضعين ← ambiguous", got["status"] == "ambiguous" and got["matches"] == 2, got)

    # نص يوتيوب أسطر قصيرة والاقتباس يمتد عدّة أسطر (الدرجات full/8/5/3)
    yt = [(10, "the situation is"), (30, "the situation on the ground"),
          (60, "we have to understand that the"), (62, "situation on the ground is very"),
          (65, "different from what they told us")]
    q = "the situation on the ground is very different from what they told us"
    got = reel_clips.locate_quote(q, yt, 63, cfg)
    check("g181-ط: اقتباس عبر 3 أسطر ← found وstart=60 وlevel=full",
          got["status"] == "found" and got["start"] == 60 and got.get("level") == "full", got)
    five = [(100, "one two"), (103, "three four"), (106, "five six"), (109, "seven eight"), (112, "nine ten"),
            (130, "unrelated")]
    got = reel_clips.locate_quote("one two three four five six seven eight nine ten", five, 100, cfg)
    check("g181-ي: اقتباس عبر 5 أسطر ← full وend محدود بالسقف = 113.9",
          got["status"] == "found" and got.get("level") == "full" and got["end"] == 113.9, got)
    two8 = [(10, "alpha beta gamma delta epsilon zeta eta theta iota"), (50, "filler words here"),
            (90, "alpha beta gamma delta epsilon zeta eta theta kappa")]
    got = reel_clips.locate_quote("alpha beta gamma delta epsilon zeta eta theta changed", two8, 88, cfg)
    check("g181-ك: آخر كلمة معدّلة وأول 8 بموضعين ← found بالأقرب وlevel=8",
          got["status"] == "found" and got["start"] == 90 and got.get("level") == "8", got)
    two5 = [(10, "alpha beta gamma delta epsilon one"), (50, "filler"),
            (90, "alpha beta gamma delta epsilon two")]
    got = reel_clips.locate_quote("alpha beta gamma delta epsilon zeta eta theta", two5, 88, cfg)
    check("g181-ل: أول 5 بموضعين ولا أطول ← ambiguous",
          got["status"] == "ambiguous" and got["matches"] == 2, got)

    tmp = Path(tempfile.mkdtemp())
    try:
        os.environ["WEBSHARE_PROXY_PASSWORD"] = "pw-FAKE-1"
        os.environ["GOOGLE_TTS_API_KEY"] = "gkey-FAKE-2"
        pt = {"channel": "c1", "language": "ar", "timestamp": 70, "video_id": "v1",
              "quote_original": "عبارة غير موجودة إطلاقًا في النص كله"}
        calls = []

        def never(vid, start, end, height, out_path, proxy):
            calls.append(vid)
            out_path.write_bytes(b"x")
            return {"bytes": 1}

        fetch = lambda vid: (segs, 100, "ar")
        rows = rp.run_probe([pt], 12, tmp / "a", downloader=never, transcript_fetcher=fetch)
        check("g181-د: missing لا يستدعي المنزِّل", not calls and rows and not rows[0]["ok"]
              and rows[0]["error"] == "rejected_missing", (calls, rows))

        def fake_runner(tier, vid, start, end, height, out_path, proxy, capture):
            capture.write("proxy pw-FAKE-1 key gkey-FAKE-2 failing")
            if tier == "a":
                raise RuntimeError("ffmpeg exited with code 8 pw-FAKE-1")
            out_path.write_bytes(b"x" * 10)
            return {"bytes": 10, "format_id": "18", "protocol": "https"}

        good = dict(pt, quote_original=quote)
        down = lambda vid, s, e, h, o, p: reel_clips.download_clip(vid, s, e, h, o, p, runner=fake_runner)
        rows = rp.run_probe([good], 12, tmp / "b", downloader=down, transcript_fetcher=fetch)
        r = rows[0]
        blob = str(r.get("failures"))
        check("g181-هـ: فشل (أ) ونجاح (ب) ← ok ودرجة b", r["ok"] and r["tier"] == "b", r)
        check("g181-هـ: error_tail محفوظ بلا أسرار",
              "code 8" in blob and "pw-FAKE-1" not in blob and "gkey-FAKE-2" not in blob, blob)
        check("g181-هـ: النافذة تبدأ من start الجديد ناقص lead", r["window_start"] == 68, r["window_start"])
        report = str(rp.build_report("2026-10-09", type("A", (), {"clips": 1, "seconds": 12})(), rows,
                                     rp.summarize(rows)))
        check("g181: التقرير بلا اقتباس", "اثنان ثلاثة" not in report)

        sent = {}

        def fake_post(url, headers, body, timeout):
            sent.update(url=url, headers=headers, body=body)
            return {"audioContent": base64.b64encode(b"MP3DATA").decode()}

        real = tts._post
        tts._post = fake_post
        try:
            res = tts.synthesize("نص", "ar-XA-Chirp3-HD-Kore", cfg)
            check("g181-و: المفتاح في الترويسة لا الرابط",
                  sent["headers"].get("X-Goog-Api-Key") == "gkey-FAKE-2" and "gkey-FAKE-2" not in sent["url"], sent)
            check("g181-و: الجسم بالصوت وar-XA وMP3",
                  sent["body"]["voice"] == {"languageCode": "ar-XA", "name": "ar-XA-Chirp3-HD-Kore"}
                  and sent["body"]["audioConfig"] == {"audioEncoding": "MP3"}
                  and sent["body"]["input"]["text"] == "نص" and res["audio"] == b"MP3DATA", sent)
            sent.clear()
            os.environ.pop("GOOGLE_TTS_API_KEY")
            res = tts.synthesize("نص", "ar-XA-Chirp3-HD-Kore", cfg)
            check("g181-و: بلا مفتاح ← skipped no_key بلا طلب",
                  res.get("skipped") == "no_key" and not sent, (res, sent))
        finally:
            tts._post = real
        check("g181-و: 800 حرف Chirp3-HD = 0.024$",
              abs(tts.estimate_cost(800, "ar-XA-Chirp3-HD-Kore", cfg) - 0.024) < 1e-9)
        check("g181-و: Wavenet بسعر 4", abs(tts.estimate_cost(1000000, "ar-XA-Wavenet-A", cfg) - 4) < 1e-9)
    finally:
        os.environ.pop("WEBSHARE_PROXY_PASSWORD", None)
        os.environ.pop("GOOGLE_TTS_API_KEY", None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_reel_tts_r3a3_guards() -> None:
    """قياس الصوت وحده: التشكيل بحارس حرفي ونبرة السؤال الختامي (Issue #1375، R3a-3).
    نموذج التشكيل والمنزِّل وgoogle وffmpeg مزيَّفة كلها."""
    import tempfile
    from pathlib import Path
    from types import SimpleNamespace

    from src import tts
    from tools import reel_clip_probe as rp

    cfg = load_config()

    class FakeModel:
        def __init__(self, outputs):
            self.outputs, self.calls = list(outputs), []
            self.messages = self

        def create(self, **kw):
            self.calls.append(kw)
            out = self.outputs[min(len(self.calls) - 1, len(self.outputs) - 1)]
            block = SimpleNamespace(type="tool_use", name="report_diacritized", input=dict(text=out))
            return SimpleNamespace(content=[block], stop_reason="tool_use",
                                   usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    orig = "قال وزير الخارجية"
    ok = "قَالَ وَزِيرُ الخَارِجِيَّةِ"
    m = FakeModel([ok])
    got, warn = tts.diacritize(orig, cfg, client=m)
    check("r3a3-أ: تشكيل سليم يُقبل بنداء واحد", got == ok and warn is None and len(m.calls) == 1, (got, warn))

    m = FakeModel(["قَالَ وُزَرَاءُ الخَارِجِيَّةِ"])
    got, warn = tts.diacritize(orig, cfg, client=m)
    check("r3a3-ب: حرف مغيَّر ← إعادة واحدة ثم الأصل وتنبيه",
          len(m.calls) == 2 and got == orig and warn and "تعذّر التشكيل" in warn, (got, warn, len(m.calls)))

    m = FakeModel(["قَالَ الخَارِجِيَّةِ"])
    got, warn = tts.diacritize(orig, cfg, client=m)
    check("r3a3-ج: كلمة محذوفة ← الرفض نفسه",
          len(m.calls) == 2 and got == orig and warn and "تعذّر التشكيل" in warn, (got, warn, len(m.calls)))

    off = load_config()
    off["reel"]["tts"]["diacritize"]["enabled"] = False
    m = FakeModel([ok])
    got, warn = tts.diacritize(orig, off, client=m)
    check("r3a3-ز: enabled=false ← الأصل بلا نداء", got == orig and warn is None and not m.calls, (got, m.calls))

    check("r3a3: أصوات القياس وأصوات الراوي من الإعداد",
          cfg.path("reel.tts.voices.female") == ["ar-XA-Chirp3-HD-Aoede"]
          and cfg.path("reel.tts.voices.male") == ["ar-XA-Chirp3-HD-Charon"]
          and cfg.path("reel.tts.narrator_voices.male") == "ar-XA-Chirp3-HD-Charon"
          and cfg.path("reel.tts.diacritize.enabled") is True)

    # د: --clips 0 ← لا منزِّل ولا جالب نص ولا اختيار نقاط ولا بروكسي
    tmp = Path(tempfile.mkdtemp())
    calls = dict(dl=0, fetch=0, probe=0)

    def bump(key, ret=None):
        def fn(*a, **k):
            calls[key] += 1
            return ret
        return fn

    names = ("download_clip", "fetch_segments", "run_probe", "proxy_url", "audio_duration", "concat_audio")
    saved = [getattr(rp, n) for n in names]
    saved_tts = (tts.synthesize, tts.diacritize)
    fake_concat = lambda parts, target, silence=0.4: Path(target).write_bytes(b"x")
    try:
        rp.download_clip, rp.fetch_segments = bump("dl"), bump("fetch")
        rp.run_probe, rp.proxy_url = bump("probe", []), bump("dl")
        rp.audio_duration = lambda p: 10.0
        rp.concat_audio = fake_concat
        tts.synthesize = lambda text, voice, c: dict(ok=True, audio=b"MP3", chars=len(text))
        tts.diacritize = lambda text, c, client=None: (text, None)
        rc = rp.main(["--clips", "0", "--out-root", str(tmp / "o"), "--report-dir", str(tmp / "r")])
        check("r3a3-د: --clips 0 ← صفر منزِّل وجالب نص وبروكسي واختيار",
              rc == 0 and calls == dict(dl=0, fetch=0, probe=0), calls)
        files = sorted(p.name for p in (tmp / "o").glob("*/tts/*.mp3"))
        check("r3a3: ثمانية ملفات (صوتان × A–D)",
              len(files) == 8 and "ar-XA-Chirp3-HD-Charon_D.mp3" in files, files)

        lines = list(cfg.path("reel.tts.sample_lines"))
        sent = []

        def synth(text, voice, c):
            sent.append(text)
            return dict(ok=True, audio=b"MP3", chars=len(text))

        common = dict(synth=synth, duration=lambda p: 10.0, diacritize=lambda t, c: (t, None), concat=fake_concat,
                      voices=[("male", "v")])
        rp.run_tts(lines, tmp / "p2", cfg, samples=("C",), **common)
        check("r3a3-هـ: C = سطور + 1 والأخير «شاركونا رأيكم.» وحدها",
              len(sent) == len(lines) + 1 and sent[-1] == "شاركونا رأيكم.", sent)
        sent.clear()
        rp.run_tts(lines, tmp / "p3", cfg, samples=("D",), **common)
        check("r3a3-و: D ← سطر السؤال ينتهي بـ? لا ؟ والبقية كما هي",
              sent[-2].endswith("?") and "؟" not in sent[-2] and sent[:-2] == lines[:-1], sent)
    finally:
        for n, f in zip(names, saved):
            setattr(rp, n, f)
        tts.synthesize, tts.diacritize = saved_tts
        shutil.rmtree(tmp, ignore_errors=True)


def test_reel_render_r3b1_guards() -> None:
    """محرك تركيب الريل: من السيناريو المعتمد إلى mp4 بلا نشر (Issue #1381، R3b-1).
    نص الفيديو والمنزِّل والصوت والتشكيل ومشغّل ffmpeg مزيَّفة كلها؛ والتركيب الحقيقي يُجرَّب إن وُجد ffmpeg."""
    import json
    import shutil as _shutil
    import subprocess
    import tempfile
    from pathlib import Path

    from src import reel_clips, reel_render, reel_script, tts
    from src.config import ROOT

    cfg = load_config()

    # ── أ) apply_waqf ──
    cases = [("الْجَنُوبِيَّةِ.", "الْجَنُوبِيَّهْ."), ("دُولَارٍ.", "دُولَارْ."), ("كِتَابًا.", "كِتَابَا."),
             ("عَلِيٌّ.", "عَلِيّْ."), ("التَّصْعِيدِ؟", "التَّصْعِيدْ؟"),
             ("مُصْطَفَى.", "مُصْطَفَى."), ("رَأْيَكُمْ.", "رَأْيَكُمْ.")]
    for src_text, want in cases:
        got = tts.apply_waqf(src_text)
        check(f"r3b1-أ: waqf {src_text}", got == want, (got, want))
    mid = "ذَهَبَ الرَّجُلُ إِلَى السُّوقِ."
    check("r3b1-أ: كلمة وسط الجملة لا تُمسّ", tts.apply_waqf(mid) == "ذَهَبَ الرَّجُلُ إِلَى السُّوقْ.",
          tts.apply_waqf(mid))

    # ── ب) تقسيم الجمل ──
    got = tts.split_sentences("جملة أولى. وثانية؟ وثالثة!")
    check("r3b1-ب: ثلاث جمل", got == ["جملة أولى.", "وثانية؟", "وثالثة!"], got)
    check("r3b1-ب: نقطة بين رقمين لا تقسم", tts.split_sentences("قيمتها 1.4 مليار دولار.")
          == ["قيمتها 1.4 مليار دولار."])
    check("r3b1-ب: الفاصلة العربية لا تقسم", len(tts.split_sentences("أولًا، ثانيًا، ثالثًا.")) == 1)

    # ── ج) locate_quote: نهاية الدرجة full ──
    segs = [(10, "alpha beta gamma delta"), (14, "epsilon zeta eta theta"), (18, "next line here")]
    got = reel_clips.locate_quote("alpha beta gamma delta epsilon zeta eta theta", segs, near=10, cfg=cfg)
    check("r3b1-ج: end = min(التالي 18، 14+4÷2.3+1 = 16.7)", got["status"] == "found" and got["level"] == "full"
          and got["start"] == 10 and got["end"] == 16.7, got)
    last = [(10, "one two three"), (14, "alpha beta gamma delta")]
    got = reel_clips.locate_quote("alpha beta gamma delta", last, near=14, cfg=cfg)
    want = round(14 + 4 / float(cfg.path("reel.script.speaker_wps")) + float(cfg.path("reel.script.clip_tail_seconds")), 1)
    check("r3b1-ج: آخر سطر ← بدايته + كلماته ÷ speaker_wps + clip_tail", got["end"] == want, (got, want))

    # ── د) معدلا الكلام ──
    c2 = load_config()
    c2["reel"]["script"]["narration_wps"] = 1.0
    c2["reel"]["script"]["speaker_wps"] = 4.0
    check("r3b1-د: الإعدادان موجودان وspeech_rate_wps محذوف",
          cfg.path("reel.script.narration_wps") == 1.7 and cfg.path("reel.script.speaker_wps") == 2.3
          and cfg.path("reel.script.speech_rate_wps") is None)
    script = {"scenes": [{"kind": "narration", "text": " ".join(["كلمة"] * 10)}]}
    est = reel_script.estimate_seconds(script, c2)
    check("r3b1-د: estimate_seconds تستعمل narration_wps",
          abs(est - (10 / 1.0 + float(c2.path("reel.script.fixed_seconds")))) < 1e-6, est)
    pt = {"timestamp": 100, "quote_original": " ".join(["w"] * 20)}
    s, e = reel_script.clip_window(pt, c2)
    check("r3b1-د: clip_window تستعمل speaker_wps (20÷4=5 ← حد أدنى 6)", round(e - s, 1) == 6.0, (s, e))
    c2["reel"]["script"]["speaker_wps"] = 2.0
    s, e = reel_script.clip_window(pt, c2)
    check("r3b1-د: clip_window (20÷2=10)", round(e - s, 1) == 10.0, (s, e))

    # ── هـ) التركيب بمزيَّفات ──
    D = "2099-12-01"
    transcripts = {
        "v1": "[00:10] alpha beta gamma delta\n[00:14] epsilon zeta eta theta\n[00:18] tail line",
        "v2": "[00:30] iota kappa lambda mu\n[00:34] nu xi omicron pi\n[00:38] tail two",
        "v3": "[01:00] unrelated words only\n[01:04] nothing here",
    }
    quotes = {"v1": "alpha beta gamma delta epsilon zeta eta theta", "v2": "iota kappa lambda mu nu xi omicron pi",
              "v3": "rho sigma tau upsilon phi chi psi omega"}
    stamps = {"v1": 10, "v2": 30, "v3": 60}
    points = [{"video_id": v, "statement": f"statement {v}", "quote_original": q, "quote_arabic": f"ترجمة {v}",
               "speaker": "متحدث", "channel": "قناة", "video_url": f"https://youtube.com/watch?v={v}",
               "timestamp": stamps[v]} for v, q in quotes.items()]
    ids = {p["video_id"]: reel_script.point_key_id(p) for p in points}

    def clip_scene(v, kind="clip"):
        return {"kind": kind, "point_id": ids[v], "video_url": f"https://youtube.com/watch?v={v}", "start": 9,
                "end": 20, "speaker_name": "", "speaker_role": "", "speaker_verified": False,
                "speaker_name_latin": "", "channel_display": "قناة", "quote_arabic": f"ترجمة {v}", "language": "en"}

    def make_draft(did, vids):
        scenes = [clip_scene(vids[0], "cold_open_clip"), {"kind": "title_card", "text": "عنوان الريل"},
                  {"kind": "narration", "text": "جملة أولى. وثانية؟"}]
        for v in vids[1:]:
            scenes += [clip_scene(v), {"kind": "narration", "text": "ربط قصير."}]
        scenes += [{"kind": "question", "text": "هل يتغير الموقف؟"}, {"kind": "outro"}]
        d = {"id": did, "origin": "analysis", "format": "reel", "status": "approved_script",
             "render_status": "queued", "topic_id": "t1", "topic_date": D, "review_issue": 4242, "title": "ريل",
             "script_status": "ready", "script": {"narrator": "female", "title": "عنوان الريل",
                                                   "question": "هل يتغير الموقف؟", "scenes": scenes}}
        path = store.save_draft(d)
        return path, d

    def make_deps(log, faces=None):
        def run(cmd):
            log["cmds"].append(list(cmd))
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(b"x")

        def download(video_id, start, end, height, out_path):
            log["downloads"].append((video_id, start, end, height))
            Path(out_path).write_bytes(b"clip")
            return {"tier": "a", "bytes": 4, "failures": []}

        def synth(text, voice):
            log["synth"].append((text, voice))
            return {"ok": True, "audio": b"mp3", "chars": len(text)}

        def comment(issue, text):
            log["comments"].append((issue, text))

        return reel_render.Deps(
            fetch_transcript=lambda vid: transcripts.get(vid), download_clip=download, synthesize=synth,
            diacritize=lambda text: (text, None), run=run, probe=lambda p: 2.0,
            load_points=lambda date: points, comment=comment, faces=faces)

    tmp = Path(tempfile.mkdtemp())
    try:
        log = {"cmds": [], "downloads": [], "synth": [], "comments": []}
        path, d = make_draft("r3b1000000a1", ["v1", "v2", "v3"])
        reel_render.render_draft(path, d, cfg, make_deps(log), reels_dir=tmp / "reels", workdir=tmp / "work")
        saved = json.loads(path.read_text(encoding="utf-8"))
        check("r3b1-هـ: مقطع missing يُحذف والباقي يُركَّب", saved.get("render_status") == "rendered",
              saved.get("render_error"))
        dropped = saved.get("render_dropped") or []
        check("r3b1-هـ: render_dropped فيه سبب المحذوف", len(dropped) == 1 and ids["v3"] in json.dumps(dropped)
              and dropped[0].get("reason"), dropped)
        check("r3b1-هـ: التنزيل بـ720 وللموجود وحده", sorted(x[0] for x in log["downloads"]) == ["v1", "v2"]
              and all(x[3] == 720 for x in log["downloads"]), log["downloads"])
        v1 = next(x for x in log["downloads"] if x[0] == "v1")
        check("r3b1-هـ: نافذة v1 من 10−lead حتى ceil(16.7)=17 (قاعدة سقف النهاية)", v1[1] == 9 and v1[2] == 17, v1)
        voice = cfg.path("reel.tts.narrator_voices.female")
        # 6 = نداء الهوك الجديد (عنوان السيناريو يقرؤه الراوي، Issue #1429) + الخمسة السابقة
        check("r3b1-هـ: صوت الراوي من الإعداد وجملة لكل نداء", len(log["synth"]) == 6
              and all(v == voice for _, v in log["synth"]), log["synth"])
        check("r3b1-هـ: تعليق على قضية المراجعة برابطين", len(log["comments"]) == 1
              and log["comments"][0][0] == 4242
              and cfg.path("reel.render.data_link_base") in log["comments"][0][1], log["comments"])
        check("r3b1-هـ: المجلد المؤقت للمقاطع حُذف", not (tmp / "work").exists() or not any((tmp / "work").iterdir()))

        # ── و) تمريرة الشعار مرة واحدة ──
        # الهوك (Issue #1429): الشعار يبدأ كبيرًا ويصل 168 في الزاوية بتعابير t، فالأمر بـeval=frame لا overlay ثابت
        logo_cmds = [c for c in log["cmds"] if "eval=frame" in " ".join(c) and "overlay=x=" in " ".join(c)]
        lg = cfg.path("reel.render.logo")
        check("r3b1-و: الإعداد 108/54/168", (lg["top"], lg["right"], lg["width"]) == (108, 54, 168), lg)
        check("r3b1-و: تمريرة شعار واحدة تنتهي بعرض 168", len(logo_cmds) == 1 and "(168-" in " ".join(logo_cmds[0]),
              len(logo_cmds))
        check("r3b1-و: الشعار في أمر واحد فقط (لا في المشاهد)",
              sum(1 for c in log["cmds"] if "logo" in " ".join(c).lower()) == 1)

        # ── ز) حقول المسودة بلا اقتباس أصلي ──
        raw = path.read_text(encoding="utf-8")
        check("r3b1-ز: حقول التركيب", saved.get("reel_file") and saved.get("reel_gif")
              and saved.get("duration_seconds") and saved.get("rendered_at")
              and saved["reel_file"].endswith(".mp4"),
              {k: saved.get(k) for k in ("reel_file", "reel_gif", "duration_seconds", "rendered_at")})
        check("r3b1-ز: لا quote_original في JSON المسودة", "quote_original" not in raw)
        check("r3b1-ز: لا نص الاقتباس الأصلي في المسودة", not any(q in raw for q in quotes.values()))

        # ── مقطعان من ثلاثة missing ← failed ──
        log2 = {"cmds": [], "downloads": [], "synth": [], "comments": []}
        saved_tr = dict(transcripts)
        transcripts["v2"] = "[00:30] unrelated words\n[00:34] other words"
        path2, d2 = make_draft("r3b1000000a2", ["v1", "v2", "v3"])
        reel_render.render_draft(path2, d2, cfg, make_deps(log2), reels_dir=tmp / "reels", workdir=tmp / "work")
        s2 = json.loads(path2.read_text(encoding="utf-8"))
        check("r3b1-هـ: أقل من min_clips ← failed بالسبب", s2.get("render_status") == "failed"
              and s2.get("render_error") and len(s2.get("render_dropped") or []) == 2, s2.get("render_error"))
        check("r3b1-هـ: لا شعار عند الفشل", not any("overlay=W-w-54:108" in " ".join(c) for c in log2["cmds"]))
        transcripts.update(saved_tr)

        # ── --retry ──
        reel_render.retry(path2.stem, cfg)
        s2 = json.loads(path2.read_text(encoding="utf-8"))
        check("r3b1-هـ: retry يعيد failed إلى queued", s2.get("render_status") == "queued"
              and "render_error" not in s2, s2.get("render_status"))
        picked = [p.stem for p, _ in reel_render.queued_reels()]
        check("r3b1-هـ: queued_reels تلتقط المسودة", path2.stem in picked and path.stem not in picked, picked)

        # ── المنطقة الآمنة ──
        boxes = reel_render.layout_boxes(cfg)
        sz = cfg.path("reel.render.safe")
        bad = [b for b in boxes if b[1] < sz["top"] or b[3] > 1920 - sz["bottom"]
               or (b[2] > 1080 - sz["right_col_width"] and b[3] > sz["right_col_from"] and b[1] < sz["right_col_to"])]
        check("r3b1-و: لا نص خارج المنطقة الآمنة", boxes and not bad, bad[:3])

        # ── م) نافذة الاقتطاع تتبع الوجه ──
        check("r3b1-م: crop في config", cfg.path("reel.render.crop.mode") == "face"
              and cfg.path("reel.render.crop.samples") == [0.2, 0.5, 0.8], cfg.path("reel.render.crop"))
        cases_m = [([1100], 875, "face"), ([300], 98, "face"), ([300, 320, 1000], 118, "face"), ([], 437, "center")]
        for centers, want_x, want_src in cases_m:
            got = reel_render.crop_window(1280, 720, centers)
            check(f"r3b1-م: مراكز {centers} ← عرض 405 وx={want_x}",
                  got["w"] == 405 and got["x"] == want_x and got["source"] == want_src, got)
        got = reel_render.crop_window(1280, 720, [300], mode="center")
        check("r3b1-م: mode=center يلغي الكشف", got["x"] == 437 and got["source"] == "center", got)
        for centers, want_x, want_src in cases_m:
            logm = {"cmds": [], "downloads": [], "synth": [], "comments": []}
            pm, dm = make_draft("r3b1000000m%d" % want_x, ["v1", "v2"])
            reel_render.render_draft(pm, dm, cfg, make_deps(logm, faces=lambda f, fr, c=centers: (1280, 720, c)),
                                     reels_dir=tmp / "reels", workdir=tmp / "work")
            joined_m = [" ".join(c) for c in logm["cmds"]]
            clip_cmds = [c for c in joined_m if f"crop=405:720:{want_x}:0" in c]
            check(f"r3b1-م: مرشّح ffmpeg فيه crop=405:720:{want_x}:0 ثم scale=1080:1920",
                  len(clip_cmds) == 2 and all("scale=1080:1920" in c and c.index("crop=") < c.index("scale=1080:1920")
                                              for c in clip_cmds), joined_m[:3])
            check("r3b1-م: لا boxblur", not any("boxblur" in c for c in joined_m))
            sm = json.loads(pm.read_text(encoding="utf-8"))
            crops = list((sm.get("render_crops") or {}).values())
            check("r3b1-م: render_crops على المسودة لكل مقطع",
                  len(crops) == 2 and all(c.get("x") == want_x and c.get("source") == want_src for c in crops),
                  sm.get("render_crops"))

        # ── ي/ك/ل) الخطوط وحارس الحروف ──
        from src import imaging as _im
        for name in ("Ayşe Demir", "Işık Kuşçu", "Doğan"):
            f = reel_render.pick_font(name, reel_render.TAJAWAL_R, 34)
            cps = _im._font_codepoints(f) if f is not None else set()
            check(f"r3b1-ي: «{name}» بخط يحوي كل حروفها", f is not None and all(ord(c) in cps for c in name if c != " "),
                  getattr(f, "path", None))
        boxes_k: list = []
        pen = reel_render._Pen(cfg, boxes_k)
        try:
            ok = True
            y2 = pen.text_line("ab\U00013000cd", reel_render.CAIRO, "Black", 40, (255, 255, 255), 500)
        except Exception as exc:  # noqa: BLE001
            ok, y2 = False, exc
        check("r3b1-ك: حرف غائب من كل الخطوط ← السطر لا يُرسم ولا استثناء", ok and not boxes_k, (y2, boxes_k))
        boxes_l: list = []
        reel_render.frame_clip_overlay(cfg, {"kind": "clip", "speaker_verified": True, "speaker_name": "عائشة دميرال",
                                             "speaker_name_latin": "Ayşe Demir", "speaker_role": "باحثة",
                                             "channel_display": "قناة", "quote_arabic": "ترجمة"}, boxes_l)
        ar_box, la_box = boxes_l[-3], boxes_l[-2]
        check("r3b1-ل: أعلى اللاتيني ≥ أسفل العربي + 10", la_box[1] >= ar_box[3] + 10, (ar_box, la_box))
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)

    # ── ح) المتطلبات و.gitignore ──
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    check("r3b1-ح: yt-dlp[default] في requirements", "yt-dlp[default]" in reqs)
    check("r3b1-ح: state/reels/ في .gitignore", "state/reels/" in (ROOT / ".gitignore").read_text(encoding="utf-8"))
    check("r3b1-ح: قالب workflow موجود", (ROOT / "tools/workflows/reel-render.yml").exists())

    # ── ط) تركيب حقيقي إن وُجد ffmpeg ──
    if not _shutil.which("ffmpeg"):
        print("  ⚠️ r3b1-ط: ffmpeg غير موجود — تخطّي اختبار الدخان (تنبيه لا فشل)")
        return
    work = Path(tempfile.mkdtemp())
    try:
        def ff(*args):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)

        clip_src = work / "src.mp4"
        ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=3", "-f", "lavfi",
           "-i", "sine=frequency=440:duration=3", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", str(clip_src))
        tone = work / "tone.wav"
        ff("-f", "lavfi", "-i", "sine=frequency=300:duration=1", str(tone))

        def run_real(cmd):
            subprocess.run(cmd, check=True, capture_output=True)

        def dl(video_id, start, end, height, out_path):
            _shutil.copy(clip_src, out_path)
            return {"tier": "a", "bytes": 1, "failures": []}

        deps = reel_render.Deps(
            fetch_transcript=lambda vid: transcripts.get(vid), download_clip=dl,
            synthesize=lambda text, voice: {"ok": True, "audio": tone.read_bytes(), "chars": len(text)},
            diacritize=lambda text: (text, None), run=run_real, probe=reel_render.probe_duration,
            load_points=lambda date: points, comment=lambda i, t: None)
        scenes = [clip_scene("v1", "cold_open_clip"), {"kind": "title_card", "text": "عنوان"},
                  {"kind": "narration", "text": "جملة واحدة."}, clip_scene("v2"),
                  {"kind": "question", "text": "هل؟"}, {"kind": "outro"}]
        d = {"id": "r3b1000000b1", "origin": "analysis", "format": "reel", "status": "approved_script",
             "render_status": "queued", "topic_id": "t1", "topic_date": D, "title": "ريل",
             "script": {"narrator": "male", "title": "عنوان", "question": "هل؟", "scenes": scenes}}
        sp = store.save_draft(d)
        reel_render.render_draft(sp, d, cfg, deps, reels_dir=work / "reels", workdir=work / "w")
        sd = json.loads(sp.read_text(encoding="utf-8"))
        check("r3b1-ط: التركيب الحقيقي نجح", sd.get("render_status") == "rendered", sd.get("render_error"))
        if sd.get("render_status") == "rendered":
            mp4 = work / "reels" / Path(sd["reel_file"]).relative_to(cfg.path("reel.render.repo_subdir"))
            info = subprocess.run(["ffmpeg", "-i", str(mp4)], capture_output=True, text=True).stderr
            check("r3b1-ط: المقاس 1080×1920", "1080x1920" in info, info[-300:])
            # الهوك (R5c1) بدل بطاقة العنوان: صوت العنوان (نغمة ثانية + صمت الجملة) + hook.tail بين حدّي الهوك
            hk = cfg.path("reel.render.hook")
            hook_sec = min(max(1.0 + float(cfg.path("reel.tts.sentence_silence", 0.35)) + float(hk["tail"]),
                               float(hk["min_seconds"])), float(hk["max_seconds"]))
            expected = (hook_sec + 3.0 + 3.0 + 1.35 + 1.35
                        + float(cfg.path("reel.render.question_tail_seconds"))
                        + float(cfg.path("reel.render.outro_seconds")))
            # R3b-1d: صمت بداية الراوي والسؤال يزيد، وخمسة انتقالات تأكل مدتها
            tsec = float(cfg.path("reel.render.transition.seconds"))
            expected += 2 * tsec - 5 * tsec
            real = reel_render.probe_duration(mp4)
            check("r3b1-ط: المدة = مجموع المشاهد ±0.5", real is not None and abs(real - expected) <= 0.5,
                  (real, expected))
    finally:
        _shutil.rmtree(work, ignore_errors=True)


def test_face_detection_f1_guards() -> None:
    """كشف الوجوه بـYuNet (cv2.FaceDetectorYN) بعد حذف OpenCV 5 للـCascadeClassifier (Issue #1383، F1).
    كان face_boxes/face_score يعيدان «لا وجه» دائمًا بصمت فتعطّل فحص وجوه الصور المجانية واقتطاع الريل."""
    import logging
    from pathlib import Path

    from PIL import Image

    from src import imaging, reel_render

    cfg = load_config()
    fx = Path(__file__).parent / "fixtures" / "faces" / "astronaut.jpg"
    face = Image.open(fx).convert("RGB")

    def on_bg(x: int) -> Image.Image:
        bg = Image.new("RGB", (1280, 720), (90, 90, 90))
        bg.paste(face, (x, 100))
        return bg

    # ── أ) الصندوق بإحداثيات الصورة الأصلية ──
    right, left = imaging.face_boxes(on_bg(820)), imaging.face_boxes(on_bg(60))
    cx_r = [x + w / 2 for x, _, w, _ in right]
    cx_l = [x + w / 2 for x, _, w, _ in left]
    check("f1-أ: وجه عند x=820 ← مركزه الأفقي بين 900 و1100",
          len(right) >= 1 and 900 <= cx_r[0] <= 1100, right)
    check("f1-أ: وجه عند x=60 ← مركزه الأفقي بين 160 و320",
          len(left) >= 1 and 160 <= cx_l[0] <= 320, left)

    # ── ب) بلا وجه ──
    check("f1-ب: خلفية بلا وجه ← قائمة فارغة",
          imaging.face_boxes(Image.new("RGB", (1280, 720), (90, 90, 90))) == [])

    # ── ج) face_score ──
    score = imaging.face_score(on_bg(820))
    check("f1-ج: face_score للصورة (أ) بين 0 و1", 0 < score < 1, score)

    # ── د) النموذج غائب ← فارغة + تحذير مرة واحدة، بلا استثناء ──
    records: list = []

    class _H(logging.Handler):
        def emit(self, record):
            records.append(record)

    h = _H(level=logging.WARNING)
    lg = logging.getLogger("src.imaging")
    old_model, old_flag = imaging.YUNET_MODEL, getattr(imaging, "_face_warned", False)
    lg.addHandler(h)
    try:
        imaging.YUNET_MODEL = Path("/nonexistent/yunet.onnx")
        imaging._face_warned = False
        try:
            got1, got2, sc = imaging.face_boxes(on_bg(820)), imaging.face_boxes(on_bg(60)), imaging.face_score(on_bg(820))
            ok = True
        except Exception as exc:  # noqa: BLE001
            got1 = got2 = sc = exc
            ok = False
    finally:
        imaging.YUNET_MODEL, imaging._face_warned = old_model, old_flag
        lg.removeHandler(h)
    check("f1-د: النموذج غائب ← قوائم فارغة وface_score=0 بلا استثناء", ok and got1 == [] and got2 == [] and sc == 0.0,
          (got1, got2, sc))
    check("f1-د: تحذير واحد مسجَّل للتشغيلة", len(records) == 1, [r.getMessage() for r in records])

    # ── هـ) crop_window بمراكز الوجه الحقيقية ──
    win = reel_render.crop_window(1280, 720, cx_r)
    want_x = int(max(0, min(cx_r[0] - 405 // 2, 1280 - 405)))
    check("f1-هـ: مراكز حقيقية ← source=face وx محصور", win["source"] == "face" and win["x"] == want_x
          and 0 <= win["x"] <= 1280 - 405 and win["x"] != 437, win)
    check("f1-هـ: config يحمل عتبتي الكاشف", cfg.path("image.face_score_threshold") == 0.6
          and cfg.path("image.face_nms_threshold") == 0.3, cfg.path("image"))


def test_reel_lowerthird_f1b_guards() -> None:
    """تداخل سطور الشريط السفلي وتسريع كشف الوجوه (Issue #1383، F1b، g193–g194).
    كان حبر اللاتيني يتداخل مع سطر الصفة بنحو 10 px لأن _Pen.line يتقدّم من نقطة الرسم لا من الحبر،
    وصندوقه المسجَّل ليس صندوق الحبر فلم يلتقطه اختبار المنطقة الآمنة."""
    from pathlib import Path

    import numpy as np
    from PIL import Image

    from src import config as _config, imaging, reel_render

    cfg = load_config()
    band = cfg.path("reel.render.band")
    top, height, edge = int(band["top"]), int(band["height"]), int(band["edge"])
    scene = {"kind": "clip", "speaker_verified": True, "speaker_name": "عائشة دمير",
             "speaker_name_latin": "Ayşe Demir", "speaker_role": "كاتبة صحفية",
             "channel_display": "هابرتورك", "quote_arabic": "ترجمة قصيرة"}

    def band_arr(sc, boxes=None):
        img = reel_render.frame_clip_overlay(cfg, sc, boxes).convert("RGBA")
        return np.array(img)[top:top + height, :img.width - edge - 4, :].astype(int)

    def rows(mask):
        r = np.where(mask.any(axis=1))[0]
        return (int(r[0]), int(r[-1])) if len(r) else None

    def measure(sc, boxes=None):
        a = band_arr(sc, boxes)
        gold = (a[..., 0] > 200) & (a[..., 1] > 140) & (a[..., 1] < 210) & (a[..., 2] < 100) & (a[..., 3] > 200)
        white = (a[..., 0] > 240) & (a[..., 1] > 240) & (a[..., 2] > 240) & (a[..., 3] > 200)
        blank = band_arr({**sc, "speaker_role": "", "channel_display": ""})
        diff = (a != blank).any(axis=2)
        return rows(white), rows(gold), rows(diff)

    boxes_a: list = []
    ar, la, role = measure(scene, boxes_a)
    ok = bool(ar and la and role)
    check("g193-أ: عربي ← لاتيني بفاصل ≥10 px", ok and ar[1] + 10 <= la[0], (ar, la, role))
    check("g193-أ: لاتيني ← صفة بفاصل ≥10 px", ok and la[1] + 10 <= role[0], (ar, la, role))
    check("g193-ب: أسفل حبر آخر سطر ≤ band.top+height−16", ok and role[1] <= height - 16, role)

    long_role = " ".join(["كلمة"] * 40)
    ar2, la2, role2 = measure({**scene, "speaker_role": long_role})
    inside = bool(ar2 and la2) and (role2 is None or (la2[1] + 10 <= role2[0] and role2[1] <= height - 16))
    check("g193-ج: صفة طويلة جدًا ← لا تداخل وكل الحبر داخل الشريط", inside, (ar2, la2, role2))

    lb = [b for b in boxes_a if la and b[1] - top <= la[0] and b[3] - top >= la[1]]
    check("g193-د: صندوق اللاتيني المسجَّل يحوي كل صفوفه الذهبية", bool(lb), (boxes_a[-3:], la))

    # ── g194: كشف الوجوه ──
    import cv2
    face = Image.open(Path(__file__).parent / "fixtures" / "faces" / "astronaut.jpg").convert("RGB")
    calls = {"load": 0, "create": 0}
    real_load, real_create = _config.load_config, cv2.FaceDetectorYN.create

    def counting_load(*a, **k):
        calls["load"] += 1
        return real_load(*a, **k)

    def counting_create(*a, **k):
        calls["create"] += 1
        return real_create(*a, **k)

    # تصفير أي ذاكرة على مستوى الوحدة ليُقاس أول نداء حقيقي
    reset = getattr(imaging, "_reset_face_cache", None)
    if reset:
        reset()
    _config.load_config = counting_load
    cv2.FaceDetectorYN.create = staticmethod(counting_create)
    try:
        results = [imaging.face_boxes(face) for _ in range(5)]
    finally:
        _config.load_config = real_load
        cv2.FaceDetectorYN.create = real_create
    check("g194-أ: خمسة نداءات ← ≤ 1 قراءة config والنتيجة نفسها", calls["load"] <= 1
          and all(r == results[0] for r in results) and bool(results[0]), (calls, results[:2]))
    check("g194-ب: FaceDetectorYN.create مرة واحدة", calls["create"] <= 1, calls)


def test_reel_script_r2d_guards() -> None:
    """سببان أسقطا سيناريو ريل حقيقيًا (Issue #1388، R2d، g195–g199): هيكل العنوان والسؤال والختام يبنيه الكود لا النموذج،
    وحارس الاسم يحرس ما سمّاه التعرّف اسمًا لا وصف المتحدث المستخرج (المسودة 1c251f64c82a)."""
    import json
    from types import SimpleNamespace

    from src import reel_script
    from src import youtube_publish as yp

    cfg = load_config()
    valid = [{"point_id": f"p{i}", "video_url": f"https://youtu.be/v{i}", "start": 10 * i, "end": 10 * i + 12,
              "speaker_name": "", "speaker_role": "", "speaker_verified": False, "speaker_verified_from": "",
              "speaker_name_latin": "", "channel_display": "قناة", "quote_arabic": "ق", "language": "ar",
              "video_published": "", "speaker_text": "محلل", "video_title": "حدث", "video_description": "",
              "statement": "س"} for i in range(3)]
    narr = "تناولت الحلقة تطورات الحدث وتبعاته على المنطقة وفق ما عرضه المتحدثون في المقاطع التالية."
    model_scenes = [{"kind": "cold_open_clip", "point_id": "p0"}, {"kind": "title_card", "text": "ع"},
                    {"kind": "narration", "text": narr}, {"kind": "clip", "point_id": "p1"},
                    {"kind": "narration", "text": narr}, {"kind": "clip", "point_id": "p2"},
                    {"kind": "narration", "text": narr}]

    def kinds(s):
        return [x["kind"] for x in s["scenes"]]

    # ── g195: شكل الحادثة: لا question ولا outro ──
    s = reel_script._build({"title": "عنوان", "question": "هل تتسع الهجمات؟", "scenes": model_scenes}, valid, "female")
    check("g195: آخر مشهدين question بنص الحقل ثم outro",
          kinds(s)[-2:] == ["question", "outro"] and s["scenes"][-2].get("text") == "هل تتسع الهجمات؟", kinds(s))
    reasons = reel_script.validate(s, valid, cfg, 3)
    check("g195: validate لا تعيد سبب الترتيب", not any("الترتيب الإلزامي" in r for r in reasons), reasons)

    # ── g196: question وoutro في الوسط ومكرَّران وبلا title_card ──
    messy = [model_scenes[0], {"kind": "question", "text": "وسط"}, model_scenes[2], {"kind": "outro"},
             model_scenes[3], model_scenes[4], {"kind": "question", "text": "آخر"}, model_scenes[5],
             {"kind": "outro"}, model_scenes[6]]
    s = reel_script._build({"title": "عنوان", "question": "سؤال الحقل", "scenes": messy}, valid, "female")
    check("g196: title_card واحد في الموضع الثاني بنص title",
          kinds(s).count("title_card") == 1 and kinds(s)[1:2] == ["title_card"]
          and s["scenes"][1].get("text") == "عنوان", kinds(s))
    check("g196: question وoutro واحد في الآخر والوسط بترتيبه",
          kinds(s) == ["cold_open_clip", "title_card", "narration", "clip", "narration", "clip", "narration",
                       "question", "outro"] and s["scenes"][-2].get("text") == "سؤال الحقل", kinds(s))
    s2 = reel_script._build({"title": "عنوان", "question": "", "scenes": messy}, valid, "female")
    check("g196: حقل question فارغ ← نص أول question أعاده النموذج", s2["scenes"][-2].get("text") == "وسط", s2["scenes"][-2])

    # ── التعرّف: مزيَّف يعيد الصفوف المعطاة ──
    real_create = reel_script._create

    def identify(rows, fail=False):
        def fake(client, **kw):
            if fail:
                raise RuntimeError("down")
            blk = SimpleNamespace(type="tool_use", name=reel_script.SPEAKERS_TOOL["name"], input={"speakers": rows})
            return SimpleNamespace(content=[blk])
        reel_script._create = fake
        try:
            clips = [dict(valid[0], speaker_text="خبير في شؤون الطاقة من السعودية"),
                     dict(valid[1], speaker_text="ضيفة")]
            return reel_script.identify_speakers(clips, [], cfg)
        finally:
            reel_script._create = real_create

    def script_with(text):
        return {"narrator": "female", "title": "ع", "question": "ما رأيك؟",
                "scenes": [{"kind": "narration", "text": text}]}

    # ── g197: التعرّف نجح بـname_arabic فارغ والوصف يحوي «السعودية» ──
    got = identify([{"point_id": "p0", "name_latin": "", "name_arabic": "", "role_arabic": ""}])
    check("g197: speaker_identity_ran وspeaker_name_guess فارغ",
          got[0].get("speaker_identity_ran") is True and got[0].get("speaker_name_guess") == "", got[0])
    r = reel_script._unverified_name_violations(script_with("استهدفت منشآت الطاقة في السعودية"), got, cfg)
    check("g197: وصف بلا اسم ← لا «سُمّي متحدث غير موثَّق»", r == [], r)

    # ── g198: الاسم المقترح غير الموثَّق يُحرس ──
    got = identify([{"point_id": "p0", "name_latin": "Nihal Karaca", "name_arabic": "نهال بنكيسو قره جا",
                     "role_arabic": ""}])
    r = reel_script._unverified_name_violations(script_with("وقالت نهال إن الهجمات ستتسع"), got, cfg)
    check("g198: «نهال» لغير موثَّق ← «سُمّي متحدث غير موثَّق: نهال»", len(r) == 1 and r[0].endswith("نهال"), r)

    got = identify([], fail=True)
    check("g198: فشل التعرّف ← لا speaker_identity_ran والحارس على speaker_text احتياطًا",
          not got[0].get("speaker_identity_ran")
          and bool(reel_script._unverified_name_violations(script_with("في السعودية"), got, cfg)), got[0])

    # ── g199: الحقلان للحارس وحده ──
    guessed = dict(valid[0], speaker_identity_ran=True, speaker_name_guess="اسمسري")
    s = reel_script._build({"title": "عنوان", "question": "س", "scenes": model_scenes}, [guessed] + valid[1:], "female")
    dumped = json.dumps(s, ensure_ascii=False)
    check("g199: لا speaker_name_guess ولا speaker_identity_ran في مشاهد السيناريو",
          "speaker_name_guess" not in dumped and "speaker_identity_ran" not in dumped and "اسمسري" not in dumped, dumped[:200])
    d = yp.build_reel_draft({"id": "aaaa1111bbbb", "title": "موضوع", "layer": "a", "blocs": ["turkish"],
                             "channels": ["قناة"], "agreement": "agreement", "event": "حدث"}, "2026-10-13", cfg)
    d.update(script=s, script_status="ready")
    try:
        body = yp.build_review_body([d], "o/r", "main", cfg)
    except Exception as exc:  # noqa: BLE001 — يظهر في التفصيل ويُفشل الفحص
        body = f"ERR {type(exc).__name__}: {exc}"
    check("g199: نص قضية المرحلة 2 بلا speaker_name_guess",
          not body.startswith("ERR") and "اسمسري" not in body and "speaker_name_guess" not in body, body[:200])


def test_analysis_go1_reopen_guards() -> None:
    """Issue #1392 (A-go1، g200–g205): go1 في التحليل يفتح قضية الاختيار فورًا، وإعادة العنقدة في اليوم نفسه لا تمحو
    المواضيع المعروضة (الشاهد: موضوع 27f23b12cc2a ضاع من ملف 2026-10-13 فصار go1 اللاحق «موضوعها غير موجود»)."""
    import json
    import os
    from datetime import datetime, timedelta, timezone

    from src import publish as publish_mod
    from src import review
    from src import youtube_cluster as ycl
    from src import youtube_publish as yp
    from tests.helpers import tick_marker
    from tests.test_review import _run_publish_issue

    cfg = load_config()
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    fixed = "2099-10-10"
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    shutil.rmtree(ycl.TOPICS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    ycl.TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    ycl.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    points = [dict(video_id=f"g20{i}", bloc="arabic", channel="الجزيرة", speaker="متحدث",
                   statement=f"قول{i}", quote_arabic="اقتباس", type="fact", video_title="فيديو",
                   video_url=f"https://youtube.com/watch?v=g20{i}", timestamp=i + 1) for i in range(2)]
    for day in (today, yesterday, fixed):
        (ycl.POINTS_DIR / f"{day}.json").write_text(json.dumps(dict(points=points), ensure_ascii=False),
                                                    encoding="utf-8")

    def mk_topic(title: str, **extra) -> dict:
        return dict(title=title, event=f"حدث {title}", layer="a", blocs=["arabic"],
                    channels=["الجزيرة"], agreement="agreement", point_ids=[0, 1], **extra)

    def write_file(day: str, topics: list) -> None:
        (ycl.TOPICS_DIR / f"{day}.json").write_text(
            json.dumps(dict(run_date=day, topics=topics), ensure_ascii=False), encoding="utf-8")

    def read_file(day: str) -> list:
        return json.loads((ycl.TOPICS_DIR / f"{day}.json").read_text(encoding="utf-8"))["topics"]

    def state(did: str) -> dict:
        return store.load_draft(did)[1]

    def mk_draft(topic: dict, day: str) -> dict:
        d = yp.build_draft_from_text(
            topic, f"# {topic['title']}\n\nمتن {topic['title']}\n\n---\n\n"
            f"{yp.youtube_article.HEADLINES_HEADER}\n\n1. {topic['title']}\n2. بديل\n3. بديل ثالث\n", [], day, cfg)
        store.save_draft(d)
        return d

    def setup(n: int) -> list:
        """n موضوعًا مختارًا في ملف أمس بمقال pending لكلٍّ؛ وفي ملف اليوم موضوع لم يُعرض."""
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        rows = [mk_topic(f"موضوع {i}", id=f"a{i}0000000000", selection_status="attempted",
                         selection_issue=77) for i in range(n)]
        write_file(yesterday, rows)
        write_file(today, [mk_topic("موضوع لم يُعرض")])
        return [mk_draft(t, yesterday) for t in rows]

    def review_body(drafts: list) -> str:
        return yp.build_review_body(drafts, "u/r", "main", cfg)

    def selections(res: dict) -> list:
        return [c for c in res["created"] if c["labels"] == ["youtube-selection"]]

    # ── g200: go1 من المرحلة 2 (المسار العادي) ← قضية اختيار فورية بالمُعاد وحده ──
    drafts = setup(1)
    tid = drafts[0]["topic_id"]
    real_run = ycl.run

    def no_cluster(*a, **k):
        raise AssertionError("لا عنقدة ولا نداء نموذج عند go1")
    ycl.run = no_cluster
    try:
        res = _run_publish_issue(tick_marker(review_body(drafts), f"<!-- go:go1:{drafts[0]['id']} -->"),
                                 "youtube-review", ["--skip-urgent"])
    finally:
        ycl.run = real_run
    sel = selections(res)
    badge = cfg.path("stages.returned_badge").format(stage=2)
    check("g200: قضية youtube-selection واحدة فيها المُعاد وحده بشارة الإعادة ولو بقي في اليوم موضوع لم يُعرض",
          len(sel) == 1 and f"topic:{tid}" in sel[0]["body"] and badge in sel[0]["body"]
          and "موضوع لم يُعرض" not in sel[0]["body"] and "↩️ إعادة ترشيح مواضيع التحليل" in sel[0]["title"],
          [(c["title"], c["labels"]) for c in res["created"]])
    number = 9800 + res["created"].index(sel[0]) + 1 if sel else None
    copy = next((t for t in read_file(today) if t.get("id") == tid), {})
    orig = next((t for t in read_file(yesterday) if t.get("id") == tid), {})
    check("g200: النسخة pending وselection_issue = رقم القضية الجديدة، والأصل moved",
          copy.get("selection_status") == "pending" and copy.get("selection_issue") == number
          and orig.get("selection_status") == "moved", (copy, orig))
    check("g200: تعليق قضية المرحلة 2 يحمل «#رقمها»",
          any(f"#{number}" in t and "أُعيد موضوعها إلى الترشيح" in t for _, t in res["comments"]),
          [t for _, t in res["comments"]])

    # ── g201: بندان من موضوعين ← قضية واحدة فيها الموضوعان ──
    drafts = setup(2)
    body = review_body(drafts)
    for d in drafts:
        body = tick_marker(body, f"<!-- go:go1:{d['id']} -->")
    res = _run_publish_issue(body, "youtube-review", ["--skip-urgent"])
    sel = selections(res)
    check("g201: قضية إعادة واحدة فيها الموضوعان",
          len(sel) == 1 and all(f"topic:{d['topic_id']}" in sel[0]["body"] for d in drafts), len(sel))

    # ── g202: المسار السريع لا يفتح، والمسار العادي مرتين لا يفتح ثانية ──
    drafts = setup(1)
    body = tick_marker(review_body(drafts), f"<!-- go:go1:{drafts[0]['id']} -->")
    res_u = _run_publish_issue(body, "youtube-review", ["--urgent-only"])
    check("g202: --urgent-only لا يفتح قضية ولا يعيد المسودة",
          not selections(res_u) and state(drafts[0]["id"])["status"] == "pending",
          [c["labels"] for c in res_u["created"]])
    res_n1 = _run_publish_issue(body, "youtube-review", ["--skip-urgent"])
    res_n2 = _run_publish_issue(body, "youtube-review", ["--skip-urgent"])
    check("g202: المسار العادي يفتح قضية واحدة، وتشغيله ثانية للحدث نفسه لا يفتح أخرى",
          len(selections(res_n1)) == 1 and not selections(res_n2),
          ([c["labels"] for c in res_n1["created"]], [c["labels"] for c in res_n2["created"]]))

    # ── fakes مشتركة لـg203–g205 (استدعاء مباشر لا عبر publish.main) ──
    created: list = []
    real = {k: getattr(review, k) for k in ("create_issue", "ensure_labels", "comment", "close_issue",
                                            "remove_label")}

    def fake_create(title, body, labels=None):
        created.append(dict(title=title, body=body, labels=labels))
        return {"number": 9900 + len(created), "html_url": "https://x/i"}
    review.create_issue = fake_create
    review.ensure_labels = lambda: None
    review.comment = lambda n, t: None
    review.close_issue = lambda n: None
    review.remove_label = lambda n, lbl: None
    real_repo = os.environ.get("GITHUB_REPOSITORY")
    os.environ["GITHUB_REPOSITORY"] = "user/trendnews"
    real_script = publish_mod._write_reel_script
    real_photo = yp._photo_candidates
    yp._photo_candidates = lambda *a, **k: ["https://example.com/photo.jpg"]
    try:
        # ── g203: اعتماد قضية الإعادة بـ🎬 ريل وحده لموضوع ريله rejected بفشل سيناريو ──
        cfg_reel = load_config()
        cfg_reel.setdefault("reel", {})["enabled"] = True
        drafts = setup(1)
        d_art = drafts[0]
        topic_like = dict(id=d_art["topic_id"], title=d_art["title"], layer="a", blocs=["arabic"],
                          channels=["الجزيرة"], agreement="agreement", event="ح")
        reel = yp.build_reel_draft(topic_like, yesterday, cfg_reel)
        reel.update(status="rejected", script_status="failed", script_error="عطل")
        store.save_draft(reel)
        publish_mod.return_to_selection([d_art["id"]], 2)
        # go1 فتح قضية الإعادة فورًا؛ جسمها يُعاد بناؤه بإعداد الريل من النسخة المحفوظة ليحمل علامات fmt:
        copy = next(t for t in read_file(today) if t["id"] == d_art["topic_id"])
        body = ycl.build_selection_body(today, [copy], points, cfg_reel)
        body = tick_marker(body, f"<!-- fmt:reel:{d_art['topic_id']} -->")
        wrote: list = []
        publish_mod._write_reel_script = lambda draft, *a, **k: wrote.append(draft["id"])
        publish_mod.cmd_youtube_selection(copy["selection_issue"], body, cfg_reel, client=None)
        check("g203: الريل المرفوض بفشل السيناريو يعود pending ويُكتب سيناريوه",
              state(reel["id"])["status"] == "pending" and wrote == [reel["id"]],
              (state(reel["id"]).get("status"), wrote))
        check("g203: المقال المُعاد يبقى returned بلا كتابة", state(d_art["id"])["status"] == "returned",
              state(d_art["id"])["status"])
        publish_mod._write_reel_script = real_script

        # ── g204/g205: ملف يوم فيه selected وpending في قضية مفتوحة وموضوع لم يُعرض ──
        ids = [ycl._topic_id(fixed, 0), ycl._topic_id(fixed, 1)]
        write_file(fixed, [
            mk_topic("مختار", id=ids[0], selection_status="selected", selection_issue=11,
                     selected_formats=["article"]),
            mk_topic("معلّق", id=ids[1], selection_status="pending", selection_issue=12, created_at="t"),
            mk_topic("لم يُعرض قديم")])
        ycl.save_output(dict(run_date=fixed, topics=[mk_topic("جديد أ"), mk_topic("جديد ب")]))
        by_title = {t["title"]: t for t in read_file(fixed)}
        check("g204: المختار والمعلّق باقيان بحقولهما والموضوع الذي لم يُعرض استُبدل",
              by_title.get("مختار", {}).get("selection_status") == "selected"
              and by_title["مختار"].get("selection_issue") == 11
              and by_title.get("معلّق", {}).get("selection_issue") == 12
              and "لم يُعرض قديم" not in by_title and "جديد أ" in by_title, list(by_title))
        out = ycl.open_selection(cfg, date_str=fixed, now=now)
        all_ids = [t["id"] for t in read_file(fixed)]
        check("g204: لا معرّف مكرر بين القديم والجديد بعد open_selection",
              len(all_ids) == len(set(all_ids)) and len(out["topics"]) == 2, all_ids)
        pend_body = ycl.build_selection_body(fixed, [by_title["معلّق"]], points, cfg)
        pend_body = tick_marker(pend_body, f"<!-- go:go2:{ids[1]} -->")
        fin = ycl.finalize_selection(12, pend_body, cfg)
        check("g204: finalize_selection للقضية المفتوحة تجد موضوعها",
              [t["id"] for t in fin["to_write"]] == [ids[1]], fin)
        got = ycl.mark_topic_returned(fixed, ids[0], "dr", 2, now.isoformat())
        check("g205: mark_topic_returned لموضوع selected بقي بعد التشغيلة الثانية ينجح", got is not None, got)
    finally:
        publish_mod._write_reel_script = real_script
        yp._photo_candidates = real_photo
        for k, v in real.items():
            setattr(review, k, v)
        if real_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo
        for day in (today, yesterday, fixed):
            (ycl.TOPICS_DIR / f"{day}.json").unlink(missing_ok=True)


def test_reel_render_r3b1c_guards() -> None:
    """Issue #1394 (R3b-1c، g206–g211): نافذة احتياطية عند تعذّر جلب النص، وتوحيد الصوت بـloudnorm، ونص «من قناة X».
    الشاهد: الريل 1c251f64c82a سقط مقطعه الافتتاحي لفشل جلب نص فيديو، وتفاوت الصوت −23…−14 LUFS، والشريط «ضيف» على مذيعة."""
    import json
    import tempfile
    from pathlib import Path

    from src import reel_render, reel_script

    cfg = load_config()
    D = "2099-12-02"
    transcripts = {
        "v1": "[00:10] alpha beta gamma delta\n[00:14] epsilon zeta eta theta\n[00:18] tail line",
        "v2": "[00:30] iota kappa lambda mu\n[00:34] nu xi omicron pi\n[00:38] tail two",
    }
    quotes = {"v1": "alpha beta gamma delta epsilon zeta eta theta", "v2": "iota kappa lambda mu nu xi omicron pi"}
    stamps = {"v1": 10, "v2": 30}
    points = [{"video_id": v, "statement": "statement " + v, "quote_original": q, "quote_arabic": "ترجمة " + v,
               "speaker": "متحدث", "channel": "قناة", "video_url": "https://youtube.com/watch?v=" + v,
               "timestamp": stamps[v]} for v, q in quotes.items()]
    ids = {p["video_id"]: reel_script.point_key_id(p) for p in points}

    def clip_scene(v, kind="clip"):
        return {"kind": kind, "point_id": ids[v], "video_url": "https://youtube.com/watch?v=" + v, "start": 9,
                "end": 20, "speaker_name": "", "speaker_role": "", "speaker_verified": False,
                "speaker_name_latin": "", "channel_display": "قناة", "quote_arabic": "ترجمة " + v, "language": "en"}

    def make_draft(did):
        scenes = [clip_scene("v1", "cold_open_clip"), {"kind": "title_card", "text": "عنوان"},
                  {"kind": "narration", "text": "جملة أولى. وثانية؟"}, clip_scene("v2"),
                  {"kind": "question", "text": "هل يتغير الموقف؟"}, {"kind": "outro"}]
        d = {"id": did, "origin": "analysis", "format": "reel", "status": "approved_script",
             "render_status": "queued", "topic_id": "t1", "topic_date": D, "review_issue": 4243, "title": "ريل",
             "script_status": "ready", "script": {"narrator": "female", "title": "عنوان",
                                                   "question": "هل يتغير الموقف؟", "scenes": scenes}}
        return store.save_draft(d), d

    def make_deps(log, fetch, pts=None):
        def run(cmd):
            log["cmds"].append(list(cmd))
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(b"x")

        def download(video_id, start, end, height, out_path):
            log["downloads"].append((video_id, start, end))
            Path(out_path).write_bytes(b"clip")
            return {"tier": "a", "bytes": 4, "failures": []}

        return reel_render.Deps(
            fetch_transcript=fetch, download_clip=download,
            synthesize=lambda text, voice: {"ok": True, "audio": b"mp3", "chars": len(text)},
            diacritize=lambda text: (text, None), run=run, probe=lambda p: 2.0,
            load_points=lambda date: pts if pts is not None else points,
            comment=lambda issue, text: log["comments"].append(text),
            faces=lambda f, fr: (1280, 720, []))

    def new_log():
        return {"cmds": [], "downloads": [], "comments": []}

    tmp = Path(tempfile.mkdtemp())
    try:
        def render(did, fetch, pts=None, c=cfg):
            log = new_log()
            path, d = make_draft(did)
            reel_render.render_draft(path, d, c, make_deps(log, fetch, pts), reels_dir=tmp / "reels",
                                     workdir=tmp / "work")
            return log, json.loads(path.read_text(encoding="utf-8"))

        # ── g206) fetch_transcript يرفع لفيديو الافتتاح ← نافذة المشهد لا إسقاط ──
        def boom_v1(vid):
            if vid == "v1":
                raise RuntimeError("blocked")
            return transcripts.get(vid)

        log, s = render("r3b1c00000a1", boom_v1)
        approx = s.get("render_approx") or []
        check("g206: المقطع الافتتاحي لا يُسقط ويُنزَّل بنافذة المشهد 9–20",
              s.get("render_status") == "rendered" and ("v1", 9, 20) in log["downloads"]
              and not any(ids["v1"] in json.dumps(x) for x in (s.get("render_dropped") or [])),
              (s.get("render_status"), s.get("render_error"), log["downloads"], s.get("render_dropped")))
        check("g206: render_approx فيه المقطع بسببه ونافذته",
              len(approx) == 1 and approx[0].get("point_id") == ids["v1"] and approx[0].get("kind") == "cold_open_clip"
              and approx[0].get("start") == 9 and approx[0].get("end") == 20 and approx[0].get("reason"), approx)
        check("g206: تعليق التركيب فيه «⚠️ نافذة تقديرية»",
              log["comments"] and "⚠️ نافذة تقديرية" in log["comments"][0] and "تعذّر جلب نص الفيديو" in log["comments"][0],
              log["comments"])

        # ── g207) fetch_transcript يعيد None ← السلوك نفسه ──
        log, s = render("r3b1c00000a2", lambda vid: None if vid == "v1" else transcripts.get(vid))
        check("g207: None ← نافذة احتياطية أيضًا",
              s.get("render_status") == "rendered" and ("v1", 9, 20) in log["downloads"]
              and len(s.get("render_approx") or []) == 1 and not s.get("render_dropped"),
              (s.get("render_status"), s.get("render_approx"), s.get("render_dropped")))

        # ── g208) النص متاح والاقتباس غير موجود ← إسقاط بلا render_approx ──
        bad = dict(transcripts, v1="[00:10] unrelated words here\n[00:14] nothing at all")
        log, s = render("r3b1c00000a3", lambda vid: bad.get(vid))
        check("g208: اقتباس غائب من نص متاح ← يبقى إسقاطًا بلا render_approx",
              len(s.get("render_dropped") or []) == 1 and ids["v1"] in json.dumps(s["render_dropped"])
              and not s.get("render_approx") and all(x[0] != "v1" for x in log["downloads"]),
              (s.get("render_dropped"), s.get("render_approx"), log["downloads"]))

        # ── g209) بلا timestamp في النقطة مع فشل النص ← إسقاط ──
        no_ts = [dict(p) for p in points]
        no_ts[0].pop("timestamp")
        log = new_log()
        path, d = make_draft("r3b1c00000a4")
        d["script"]["scenes"][0]["point_id"] = reel_script.point_key_id(no_ts[0])
        store.update_draft(path, script=d["script"])
        reel_render.render_draft(path, d, cfg, make_deps(log, lambda vid: None if vid == "v1" else transcripts.get(vid),
                                                         no_ts), reels_dir=tmp / "reels", workdir=tmp / "work")
        s = json.loads(path.read_text(encoding="utf-8"))
        check("g209: بلا timestamp ← يُسقط ولا نافذة تقديرية",
              len(s.get("render_dropped") or []) == 1 and not s.get("render_approx")
              and all(x[0] != "v1" for x in log["downloads"]),
              (s.get("render_dropped"), s.get("render_approx")))

        # ── g210) loudnorm لكل مقطع وكل جملة راوٍ وللملف النهائي ──
        def loud_checks(c, target, tag):
            log, s = render("r3b1c0000" + tag, lambda vid: transcripts.get(vid), c=c)
            joined = [" ".join(x) for x in log["cmds"]]
            want = "loudnorm=I=" + str(target) + ":TP=" + str(c.path("reel.render.loudness.true_peak")) + ":LRA=11"
            clip_cmds = [x for x in joined if "crop=" in x]
            sent_cmds = [x for x in joined if ".mp3" in x]
            final = [x for x in joined if "overlay=W-w-" in x or ("overlay=x=" in x and "eval=frame" in x)]
            check("g210: مقطعان بمرشح " + want, len(clip_cmds) == 2 and all(want in x for x in clip_cmds), clip_cmds[:1])
            # 4 = ثلاث جمل راوٍ + جملة الهوك (عنوان السيناريو، Issue #1429)
            check("g210: كل جملة راوٍ (4) بمرشح " + want, len(sent_cmds) == 4 and all(want in x for x in sent_cmds),
                  sent_cmds[:1])
            check("g210: أمر الملف النهائي يحمله (" + str(target) + ")", len(final) == 1 and want in final[0], final)

        check("g210: الإعداد -16 و-1.5",
              cfg.path("reel.render.loudness.target_lufs") == -16 and cfg.path("reel.render.loudness.true_peak") == -1.5,
              cfg.path("reel.render.loudness"))
        loud_checks(cfg, -16, "b1")
        cfg2 = load_config()
        cfg2["reel"]["render"]["loudness"]["target_lufs"] = -18
        loud_checks(cfg2, -18, "b2")

        # ── g211) «من قناة X» للمتحدث غير الموثَّق ──
        seen: list = []
        orig_draw = reel_render.imaging.draw_text

        def spy(d_, xy, text, *a, **k):
            seen.append(text)
            return orig_draw(d_, xy, text, *a, **k)

        reel_render.imaging.draw_text = spy
        try:
            reel_render.frame_clip_overlay(cfg, {"kind": "clip", "speaker_verified": False,
                                                 "channel_display": "الجزيرة", "quote_arabic": ""})
        finally:
            reel_render.imaging.draw_text = orig_draw
        check("g211: النص المرسوم «ضيف على الجزيرة»", "ضيف على الجزيرة" in seen and not any("من قناة" in t for t in seen), seen)
        check("g211: شارة المرحلة 2 من المفتاح نفسه",
              reel_script.speaker_band({"channel_display": "الجزيرة"}, cfg) == "ضيف على الجزيرة"
              and cfg.path("reel.texts.guest_label") == "ضيف على {channel}", cfg.path("reel.texts.guest_label"))
        check("g211: نص اعتماد السيناريو الجديد",
              "✅ اعتُمد السيناريو — شغّل «🎬 تركيب الريل» من Actions لتركيبه" in cfg.path("reel.texts.script_approved")
              and "مرحلة التركيب" not in cfg.path("reel.texts.script_approved"), cfg.path("reel.texts.script_approved"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reel_transitions_r3b1d_guards() -> None:
    """Issue #1397 (R3b-1d، g212–g218): انتقال «دفع من اليمين» بين مشاهد الريل (fade للختام) بـxfade/acrossfade،
    والشعار مرة واحدة بعد الضمّ، وصمت بداية الراوي والسؤال، وإعادة تركيب المعتمد عند تغيّر reel.render.version."""
    import json
    import logging
    import re
    import tempfile
    from pathlib import Path

    from src import reel_render, reel_script

    D = "2099-12-03"
    transcripts = {
        "v1": "[00:10] alpha beta gamma delta\n[00:14] epsilon zeta eta theta\n[00:18] tail line",
        "v2": "[00:30] iota kappa lambda mu\n[00:34] nu xi omicron pi\n[00:38] tail two",
    }
    quotes = {"v1": "alpha beta gamma delta epsilon zeta eta theta", "v2": "iota kappa lambda mu nu xi omicron pi"}
    points = [{"video_id": v, "statement": "s " + v, "quote_original": q, "quote_arabic": "ترجمة " + v,
               "speaker": "متحدث", "channel": "قناة", "video_url": "https://youtube.com/watch?v=" + v,
               "timestamp": t} for (v, q), t in zip(quotes.items(), (10, 30))]
    ids = {p["video_id"]: reel_script.point_key_id(p) for p in points}

    def clip_scene(v, kind="clip"):
        return {"kind": kind, "point_id": ids[v], "video_url": "https://youtube.com/watch?v=" + v, "start": 9,
                "end": 20, "speaker_name": "", "speaker_role": "", "speaker_verified": False,
                "speaker_name_latin": "", "channel_display": "قناة", "quote_arabic": "ترجمة " + v, "language": "en"}

    def make_draft(did, scenes, **extra):
        d = {"id": did, "origin": "analysis", "format": "reel", "status": "approved_script",
             "render_status": "queued", "topic_id": "t1", "topic_date": D, "title": "ريل", "script_status": "ready",
             "script": {"narrator": "female", "title": "عنوان", "question": "هل؟", "scenes": scenes}}
        d.update(extra)
        return store.save_draft(d), d

    five = [clip_scene("v1", "cold_open_clip"), {"kind": "title_card", "text": "عنوان"}, clip_scene("v2"),
            clip_scene("v1"), {"kind": "outro"}]
    mixed = [clip_scene("v1", "cold_open_clip"), {"kind": "narration", "text": "جملة واحدة."}, clip_scene("v2"),
             {"kind": "question", "text": "هل؟"}, {"kind": "outro"}]
    durs = {0: 10.0, 1: 2.5, 2: 8.0, 3: 12.0, 4: 3.0}

    def make_deps(log, scene_durs=None):
        def run(cmd):
            log["cmds"].append(list(cmd))
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(b"x")

        def probe(p):
            name = Path(p).name
            if scene_durs and name.startswith("scene_"):
                return scene_durs[int(name[6:8])]
            return 41.0 if "reels" in Path(p).parts else 2.0

        def download(video_id, start, end, height, out_path):
            Path(out_path).write_bytes(b"clip")
            return {"tier": "a", "bytes": 4, "failures": []}

        return reel_render.Deps(
            fetch_transcript=lambda vid: transcripts.get(vid), download_clip=download,
            synthesize=lambda text, voice: {"ok": True, "audio": b"mp3", "chars": len(text)},
            diacritize=lambda text: (text, None), run=run, probe=probe, load_points=lambda date: points,
            comment=lambda i, t: log["comments"].append((i, t)), faces=lambda f, fr: (1280, 720, []))

    tmp = Path(tempfile.mkdtemp())
    try:
        def render(did, scenes, c, scene_durs=None):
            log = {"cmds": [], "comments": []}
            path, d = make_draft(did, scenes)
            reel_render.render_draft(path, d, c, make_deps(log, scene_durs), reels_dir=tmp / "reels",
                                     workdir=tmp / "work")
            return log, [" ".join(x) for x in log["cmds"]], json.loads(path.read_text(encoding="utf-8"))

        cfg = load_config()
        tr = cfg.path("reel.render.transition") or {}
        check("g212: الإعداد transition وversion",
              (tr.get("type"), tr.get("outro_type"), tr.get("seconds")) == ("slideleft", "fade", 0.35)
              and cfg.path("reel.render.version") == 14, tr)

        # ── g212/g213: أمر ضمّ واحد بأربعة xfade وأربعة acrossfade ──
        log, cmds, saved = render("r3b1d0000a01", five, cfg, durs)
        joins = [c for c in cmds if "xfade" in c]
        j = joins[0] if joins else ""
        xf = re.findall(r"xfade=transition=(\w+):duration=([\d.]+):offset=([\d.]+)", j)
        check("g212: أمر ضمّ واحد وفيه أربعة xfade", len(joins) == 1 and len(xf) == 4, (len(joins), xf))
        check("g212: الأنواع والـoffsets والمدة",
              # الهوك (2.5 ث) يتقدّم إلى أول الريل ثم cold_open_clip (Issue #1429)
              xf == [("slideleft", "0.350", "2.150"), ("slideleft", "0.350", "11.800"),
                     ("slideleft", "0.350", "19.450"), ("fade", "0.350", "31.100")], xf)
        check("g213: أربعة acrossfade بـd=0.350", re.findall(r"acrossfade=d=([\d.]+)", j) == ["0.350"] * 4, j[:300])
        check("g212: duration_seconds من probe الملف النهائي لا مجموع المدد", saved.get("duration_seconds") == 41.0,
              saved.get("duration_seconds"))

        # ── g214: صمت بداية الراوي والسؤال وحدهما ──
        log, cmds, saved = render("r3b1d0000a02", mixed, cfg)
        spoken = [c for c in cmds if "_frames.txt" in c]
        check("g214: مشهدا الراوي والسؤال بـadelay=350", len(spoken) == 2 and all("adelay=350" in c for c in spoken), spoken)
        check("g214: المقطع بلا صمت مضاف", not any("adelay" in c for c in cmds if "crop=" in c))

        # ── g215: الشعار بعد الضمّ وإطار الراوي بلا شعار ──
        log, cmds, _ = render("r3b1d0000a03", five, cfg, durs)
        ji = next((i for i, c in enumerate(cmds) if "xfade" in c), -1)
        li = next((i for i, c in enumerate(cmds) if "overlay=W-w-" in c or ("overlay=x=" in c and "eval=frame" in c)), -1)
        lg = cfg.path("reel.render.logo")
        # بوجود هوك يصل الشعار موضع الإعداد (1080−right−width ، top) بتعابير زمنية (Issue #1429)
        check("g215: الضمّ ثم الشعار وبموضع الإعداد",
              0 <= ji < li and (f"overlay=W-w-{lg['right']}:{lg['top']}" in cmds[li]
                                or ("eval=frame" in cmds[li] and f"({1080 - lg['right'] - lg['width']}-" in cmds[li]
                                    and f"({lg['top']}-" in cmds[li])), (ji, li))
        check("g215: لا أمر قبل الضمّ يذكر الشعار", not any("logo" in c.lower() for c in cmds[:max(ji, 0)]), cmds[:2])
        img = reel_render.frame_narration(cfg, "جملة قصيرة")
        navy = reel_render.imaging.hex_rgb(cfg.path("brand.primary_color"))
        x1 = 1080 - lg["right"]
        box = img.crop((x1 - lg["width"], lg["top"], x1, lg["top"] + lg["width"]))
        check("g215: صندوق الشعار بلون الخلفية في إطار الراوي", set(box.getdata()) == {navy}, set(box.getdata()))

        # ── g216: seconds = 0 ← concat كما اليوم ──
        c0 = load_config()
        c0["reel"]["render"]["transition"]["seconds"] = 0
        log, cmds, saved = render("r3b1d0000a04", mixed, c0)
        check("g216: concat -c copy بلا xfade ولا acrossfade ولا صمت",
              any("-f concat" in c and "-c copy" in c and "scenes.txt" in c for c in cmds)
              and not any(w in c for c in cmds for w in ("xfade", "acrossfade", "adelay")), [c[:80] for c in cmds])

        # ── g217: seconds = 1.2 ← 0.9 مع تحذير ──
        c1 = load_config()
        c1["reel"]["render"]["transition"]["seconds"] = 1.2
        warns: list = []

        class _H(logging.Handler):
            def emit(self, record):
                warns.append(record.getMessage())
        h = _H(level=logging.WARNING)
        lgr = logging.getLogger("trendnews.reel_render")
        lgr.addHandler(h)
        try:
            log, cmds, saved = render("r3b1d0000a05", five, c1, durs)
        finally:
            lgr.removeHandler(h)
        j = next((c for c in cmds if "xfade" in c), "")
        check("g217: الانتقال 0.900 مع تحذير",
              "duration=0.900" in j and "acrossfade=d=0.900" in j and "duration=1.200" not in j
              and any("انتقال" in w for w in warns), (j[:200], warns))

        # ── g218: إعادة تركيب المعتمد بنسخة أقدم ──
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        c2 = load_config()
        c2["reel"]["render"]["max_per_run"] = 50
        p_old, _ = make_draft("r3b1d0000b01", mixed, render_status="rendered", approved_script_at="2099-01-01")
        p_pub, _ = make_draft("r3b1d0000b02", mixed, status="published", render_status="rendered")
        p_rej, _ = make_draft("r3b1d0000b03", mixed, status="rejected", render_status="rendered")
        p_new, _ = make_draft("r3b1d0000b04", mixed, render_status="rendered", render_version=14)
        picked = [p.stem for p, _ in reel_render.pending_batch(c2)]
        check("g218: يلتقط القديم النسخة وحده", picked == [p_old.stem], picked)
        for p, d in reel_render.pending_batch(c2):
            reel_render.render_draft(p, d, c2, make_deps({"cmds": [], "comments": []}), reels_dir=tmp / "reels",
                                     workdir=tmp / "work")
        s = json.loads(p_old.read_text(encoding="utf-8"))
        check("g218: render_version = 14 بعد التركيب", s.get("render_status") == "rendered" and s.get("render_version") == 14, s)
        left = reel_render.pending_batch(c2)
        check("g218: التشغيلة الثانية لا تعيدها", left == [], [p.stem for p, _ in left])
        check("g218: المنشور والمرفوض لم يُمسّا",
              all(json.loads(p.read_text(encoding="utf-8")).get("render_version") is None for p in (p_pub, p_rej)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reel_typewriter_r3b2a_guards() -> None:
    """Issue #1400 (R3b-2a، g219–g225): كتابة نص الراوي حرفًا حرفًا متزامنة مع الصوت، والشريط السفلي يدخل متحركًا
    من اليمين، والغطاء الكحلي المعتم تحت الشريط، وreel.render.version = 3."""
    import json
    import re
    import tempfile
    from pathlib import Path

    from PIL import Image, ImageChops

    from src import reel_render, reel_script, tts

    FPS = 30

    def step_checks(tag, text, speech, hold, steps):
        prefixes, ds = [p for p, _ in steps], [d for _, d in steps]
        incr = all(len(a) < len(b) and b.startswith(a) for a, b in zip(prefixes, prefixes[1:]))
        check(f"{tag}: البادئات متزايدة وآخرها النص كاملًا", incr and prefixes[-1] == text, prefixes[-2:])
        check(f"{tag}: لا بادئة تنتهي بمسافة", not any(p.endswith(" ") for p in prefixes))
        check(f"{tag}: مجموع المدد = الكلام + الصمت", abs(sum(ds) - (speech + hold)) <= 0.001, sum(ds))
        check(f"{tag}: النص الكامل عند نهاية الكلام ويبقى hold",
              abs(sum(ds[:-1]) - speech) <= 1 / FPS + 1e-6 and abs(ds[-1] - hold) <= 1e-6, (sum(ds[:-1]), ds[-1]))
        check(f"{tag}: لا مدة أقل من إطار", min(ds) >= 1 / FPS - 1e-6, min(ds))

    # ── g219 ──
    text = "أعلن الحزب إخلاء مواقعه."
    step_checks("g219", text, 2.0, 0.35, reel_render.typewriter_steps(text, 2.0, 0.35, FPS))

    # ── g220: جملة 300 حرف في 3 ثوانٍ ──
    long_text = " ".join(["كلمةطويلة"] * 30)[:300].rstrip()
    steps = reel_render.typewriter_steps(long_text, 3.0, 0.35, FPS)
    check("g220: عدد الخطوات ≤ 91", len(steps) <= 91, len(steps))
    step_checks("g220", long_text, 3.0, 0.35, steps)

    cfg = load_config()
    navy = reel_render.imaging.hex_rgb(cfg.path("brand.primary_color"))

    # ── g221: جملة من سطرين ──
    probe = reel_render._Pen(cfg, None)
    sentence = ""
    for n in range(1, 40):
        cand = " ".join(["مستشفى"] * n)
        _, lines, _ = reel_render.imaging.fit_text(probe.d, cand, *reel_render.display_font(cfg)[:1], probe.max_w, 5, 108,
                                                   80, None, line_factor=reel_render.display_font(cfg)[1])
        if len(lines) == 2:
            sentence = cand
            break
    full_boxes: list = []
    full = reel_render.frame_narration(cfg, sentence, full_boxes)
    last = reel_render.frame_narration_typed(cfg, sentence, sentence)
    check("g221: الإطار الأخير مطابق بالبكسل لـframe_narration", last.tobytes() == full.tobytes())
    prefix = sentence[:len(sentence) // 4].rstrip()
    part = reel_render.frame_narration_typed(cfg, sentence, prefix)
    bg = Image.new("RGB", full.size, navy)

    def region_bbox(img, box):
        y0, y1 = int(box[1]), int(box[3]) + 1
        return ImageChops.difference(img.crop((0, y0, img.size[0], y1)), bg.crop((0, y0, img.size[0], y1))).getbbox()

    check("g221: سطران في الإطار الكامل", len(full_boxes) == 2, full_boxes)
    b_full, b_part = region_bbox(full, full_boxes[0]), region_bbox(part, full_boxes[0])
    check("g221: حافة حبر السطر الأول اليمنى ثابتة (±2px)",
          bool(b_full and b_part) and abs(b_full[2] - b_part[2]) <= 2, (b_full, b_part))
    check("g221: لا حبر في صفوف السطر الثاني", region_bbox(part, full_boxes[1]) is None)

    D = "2099-12-04"
    quote = "alpha beta gamma delta epsilon zeta eta theta"
    points = [{"video_id": "v1", "statement": "s", "quote_original": quote, "quote_arabic": "ترجمة",
               "speaker": "متحدث", "channel": "قناة", "video_url": "https://youtube.com/watch?v=v1", "timestamp": 10}]
    pid = reel_script.point_key_id(points[0])
    clip = {"kind": "clip", "point_id": pid, "video_url": "https://youtube.com/watch?v=v1", "start": 9, "end": 20,
            "speaker_name": "", "speaker_role": "", "speaker_verified": False, "speaker_name_latin": "",
            "channel_display": "قناة", "quote_arabic": "ترجمة", "language": "en"}
    scenes = [dict(clip, kind="cold_open_clip"),
              {"kind": "narration", "text": "جملة أولى قصيرة. وجملة ثانية أطول قليلًا."}, dict(clip),
              {"kind": "question", "text": "هل؟"}, {"kind": "outro"}]
    transcripts = {"v1": "[00:10] alpha beta gamma delta\n[00:14] epsilon zeta eta theta\n[00:18] tail line"}

    def make_draft(did, **extra):
        d = {"id": did, "origin": "analysis", "format": "reel", "status": "approved_script",
             "render_status": "queued", "topic_id": "t1", "topic_date": D, "title": "ريل", "script_status": "ready",
             "script": {"narrator": "female", "title": "عنوان", "question": "هل؟", "scenes": scenes}}
        d.update(extra)
        return store.save_draft(d), d

    def make_deps(log):
        def run(cmd):
            log["cmds"].append(list(cmd))
            for a in cmd:
                if str(a).endswith("_frames.txt"):
                    log["lists"].append(Path(a).read_text(encoding="utf-8"))
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(b"x")

        def download(video_id, start, end, height, out_path):
            Path(out_path).write_bytes(b"clip")
            return {"tier": "a", "bytes": 4, "failures": []}

        return reel_render.Deps(
            fetch_transcript=lambda vid: transcripts.get(vid), download_clip=download,
            synthesize=lambda t, voice: {"ok": True, "audio": b"mp3", "chars": len(t)},
            diacritize=lambda t: (t, None), run=run,
            probe=lambda p: 41.0 if "reels" in Path(p).parts else 2.0, load_points=lambda date: points,
            comment=lambda i, t: None, faces=lambda f, fr: (1280, 720, []))

    tmp = Path(tempfile.mkdtemp())
    try:
        def render(did, c):
            log = {"cmds": [], "lists": []}
            path, d = make_draft(did)
            reel_render.render_draft(path, d, c, make_deps(log), reels_dir=tmp / "reels", workdir=tmp / "work")
            return log, [" ".join(x) for x in log["cmds"]]

        def entries(body):
            return [float(x) for x in re.findall(r"duration ([\d.]+)", body)]

        sents = [tts.strip_tashkeel(s) for s in tts.split_sentences(scenes[1]["text"])]
        silence = float(cfg.path("reel.tts.sentence_silence", 0.35))
        expect = [reel_render.typewriter_steps(s, 2.0 - silence, silence, FPS) for s in sents]

        # ── g222 ──
        # الكتابة حرفًا حرفًا باقية بـreveal.mode=typewriter؛ الافتراضي lines له g269
        import copy as _copy
        cfg_tw = _copy.deepcopy(cfg)
        cfg_tw["reel"]["render"]["reveal"]["mode"] = "typewriter"
        log, cmds = render("r3b2a0000a01", cfg_tw)
        check("g222: مشهدا الراوي والسؤال لكلٍّ قائمة إطارات", len(log["lists"]) == 2, len(log["lists"]))
        nar, ques = (log["lists"] + ["", ""])[:2]
        d_nar = entries(nar)
        want_n = sum(len(e) for e in expect)
        check("g222: صور الراوي بعدد خطوات جمله", len(d_nar) == want_n, (len(d_nar), want_n))
        lead = reel_render.transition_seconds(cfg)
        check("g222: مدة أول خطوة تتضمن lead", abs(d_nar[0] - (expect[0][0][1] + lead)) < 0.002, (d_nar[0], lead))
        check("g222: السؤال صورة واحدة", len(entries(ques)) == 1, entries(ques))
        check("g222: الشعار والانتقالات بلا تغيير",
              any("xfade" in c for c in cmds) and any("overlay=W-w-" in c for c in cmds))

        # ── g223 ──
        clip_cmds = [c for c in cmds if "crop=" in c]
        fc = clip_cmds[0] if clip_cmds else ""
        check("g223: overlay ثانٍ في أمر المقطع", fc.count("overlay=") == 2 and fc.count("-loop 1") == 2, fc[:300])
        mx = re.search(r"overlay=x='([^']+)'", fc)
        slide = cfg.path("reel.render.band.slide_seconds")
        check("g223: slide_seconds في الإعداد 0.4", slide == 0.4, slide)
        check("g223: تعبير x يحمل البدء 0.350 والمدة 0.400",
              bool(mx) and "0.350" in mx.group(1) and "0.400" in mx.group(1) and "pow(" in mx.group(1),
              mx and mx.group(1))
        static, band = reel_render.frame_clip_layers(cfg, dict(clip))
        check("g223: الطبقة الثابتة عند (540،1700) كحلي معتم", static.getpixel((540, 1700)) == navy + (255,),
              static.getpixel((540, 1700)))
        check("g223: صندوق الترجمة في الثابتة وحدها",
              static.getpixel((540, 1215))[3] > 0 and band.getpixel((540, 1215))[3] == 0,
              (static.getpixel((540, 1215)), band.getpixel((540, 1215))))
        check("g223: الشريط في طبقته ولا غطاء فيها",
              band.getpixel((300, 1380))[3] > 0 and band.getpixel((540, 1700))[3] == 0)

        # ── g224 ──
        c_off = load_config()
        c_off["reel"]["render"]["typewriter"] = {"enabled": False}
        c_off["reel"]["render"]["band"]["cover"] = False
        log, cmds = render("r3b2a0000a02", c_off)
        check("g224: بلا كتابة ← إطار لكل جملة", len(entries(log["lists"][0])) == len(sents), entries(log["lists"][0]))
        static_off, _ = reel_render.frame_clip_layers(c_off, dict(clip))
        check("g224: بلا غطاء ← الثابتة شفافة عند (540،1700)", static_off.getpixel((540, 1700))[3] == 0)

        # ── g225 ──
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        p_old, _ = make_draft("r3b2a0000b01", render_status="rendered", render_version=2,
                              approved_script_at="2099-01-01")
        picked = [p.stem for p, _ in reel_render.pending_batch(cfg)]
        check("g225: --pending يلتقط الريل بنسخة 2", picked == [p_old.stem], picked)
        for p, d in reel_render.pending_batch(cfg):
            reel_render.render_draft(p, d, cfg, make_deps({"cmds": [], "lists": []}), reels_dir=tmp / "reels",
                                     workdir=tmp / "work")
        s = json.loads(p_old.read_text(encoding="utf-8"))
        check("g225: render_version = 8 بعد التركيب",
              s.get("render_status") == "rendered" and s.get("render_version") == 14, s)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reel_no_partial_r3b2a2_guards() -> None:
    """Issue #1404 (R3b-2a2، g226–g230): لا يُحفظ ريل سقط منه مقطع بعطل تنزيل — إعادة السلّم ثم طابور بمحاولات؛
    الإسقاط التحريري يبقى؛ reel.render.version = 4."""
    import json
    import tempfile
    from pathlib import Path

    from src import reel_render, reel_script

    D = "2099-12-05"
    q1, q2 = "alpha beta gamma delta epsilon zeta", "one two three four five six"
    points = [{"video_id": "v1", "statement": "s", "quote_original": q1, "quote_arabic": "ترجمة",
               "speaker": "متحدث", "channel": "قناة", "video_url": "https://youtube.com/watch?v=v1", "timestamp": 10},
              {"video_id": "v2", "statement": "s2", "quote_original": q2, "quote_arabic": "ترجمة٢",
               "speaker": "متحدث٢", "channel": "قناة٢", "video_url": "https://youtube.com/watch?v=v2", "timestamp": 10}]
    pid1, pid2 = reel_script.point_key_id(points[0]), reel_script.point_key_id(points[1])

    def clip(pid, url, ch, kind="clip"):
        return {"kind": kind, "point_id": pid, "video_url": url, "start": 9, "end": 20, "speaker_name": "",
                "speaker_role": "", "speaker_verified": False, "speaker_name_latin": "", "channel_display": ch,
                "quote_arabic": "ترجمة", "language": "en"}

    scenes = [clip(pid1, "https://youtube.com/watch?v=v1", "قناة", "cold_open_clip"),
              {"kind": "narration", "text": "جملة أولى قصيرة."},
              clip(pid2, "https://youtube.com/watch?v=v2", "قناة٢"),
              {"kind": "narration", "text": "جملة ثانية."},
              clip(pid1, "https://youtube.com/watch?v=v1", "قناة"),
              {"kind": "question", "text": "هل؟"}, {"kind": "outro"}]
    transcripts = {"v1": "[00:10] alpha beta gamma delta\n[00:14] epsilon zeta eta theta\n[00:18] tail line",
                   "v2": "[00:10] one two three four\n[00:14] five six seven eight\n[00:18] tail line"}

    def make_draft(did, **extra):
        d = {"id": did, "origin": "analysis", "format": "reel", "status": "approved_script",
             "render_status": "queued", "topic_id": "t1", "topic_date": D, "title": "ريل", "script_status": "ready",
             "review_issue": 77, "reel_file": "reels/old.mp4", "reel_gif": "reels/old.gif",
             "script": {"narrator": "female", "title": "عنوان", "question": "هل؟", "scenes": scenes}}
        d.update(extra)
        return store.save_draft(d), d

    def make_deps(log, fail_v2=0, trans=None):
        """fail_v2: عدد مرات فشل تنزيل v2 قبل النجاح؛ -1 ← دائمًا."""
        left = {"n": fail_v2}

        def run(cmd):
            log["cmds"].append(list(cmd))
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(b"x")

        def download(video_id, start, end, height, out_path):
            if video_id == "v2" and left["n"] != 0:
                if left["n"] > 0:
                    left["n"] -= 1
                raise RuntimeError("فشلت كل الدرجات: ERROR: ffmpeg exited with code 8")
            Path(out_path).write_bytes(b"clip")
            return {"tier": "a", "bytes": 4, "failures": []}

        return reel_render.Deps(
            fetch_transcript=lambda vid: (trans or transcripts).get(vid), download_clip=download,
            synthesize=lambda t, voice: {"ok": True, "audio": b"mp3", "chars": len(t)},
            diacritize=lambda t: (t, None), run=run,
            probe=lambda p: 41.0 if "reels" in Path(p).parts else 2.0, load_points=lambda date: points,
            comment=lambda i, t: log["comments"].append(t), faces=lambda f, fr: (1280, 720, []),
            sleep=lambda s: log["sleeps"].append(s))

    def run_one(did, fail_v2, trans=None, **extra):
        log = {"cmds": [], "comments": [], "sleeps": []}
        path, d = make_draft(did, **extra)
        reel_render.render_draft(path, d, cfg, make_deps(log, fail_v2, trans), reels_dir=tmp / "reels",
                                 workdir=tmp / "work")
        return log, json.loads(path.read_text(encoding="utf-8")), [" ".join(c) for c in log["cmds"]]

    cfg = load_config()
    tmp = Path(tempfile.mkdtemp())
    try:
        # ── g226 ──
        log, s, _ = run_one("r3b2a2000a01", 2)
        check("g226: مركَّب كاملًا بلا render_dropped",
              s.get("render_status") == "rendered" and not s.get("render_dropped"), s)
        check("g226: الانتظار مرتين بـ20", log["sleeps"] == [20, 20], log["sleeps"])

        # ── g227 ──
        log, s, cmds = run_one("r3b2a2000b01", -1)
        check("g227: لا أمر ضمّ ولا شعار", not any("xfade" in c or "overlay=W-w-" in c for c in cmds), cmds[:3])
        check("g227: reel_file السابق باقٍ",
              s.get("reel_file") == "reels/old.mp4" and s.get("reel_gif") == "reels/old.gif", s)
        check("g227: queued ومحاولة 1", s.get("render_status") == "queued" and s.get("render_attempts") == 1, s)
        check("g227: التعليق «محاولة 1 من 3»",
              any("محاولة 1 من 3" in c and "قناة٢" in c for c in log["comments"]), log["comments"])
        check("g227: انتظار بين الإعادات فقط", log["sleeps"] == [20, 20], log["sleeps"])

        # ── g228 ──
        log, s, _ = run_one("r3b2a2000c01", -1, render_attempts=2)
        check("g228: failed وrender_error بالسبب",
              s.get("render_status") == "failed" and "ffmpeg exited with code 8" in (s.get("render_error") or ""), s)
        check("g228: التعليق «بعد 3 محاولات»", any("بعد 3 محاولات" in c for c in log["comments"]), log["comments"])
        check("g228: reel_file السابق باقٍ", s.get("reel_file") == "reels/old.mp4", s)

        # ── g229 ──
        bad = dict(transcripts, v2="[00:10] nothing relevant here\n[00:14] at all\n[00:18] tail line")
        log, s, _ = run_one("r3b2a2000d01", 0, trans=bad)
        check("g229: الاقتباس غير الموجود إسقاط والباقي يُركَّب",
              s.get("render_status") == "rendered" and len(s.get("render_dropped") or []) == 1
              and "الاقتباس غير موجود" in s["render_dropped"][0]["reason"], s)
        check("g229: لا انتظار", log["sleeps"] == [], log["sleeps"])

        # ── g230 ──
        log, s, _ = run_one("r3b2a2000e01", 0, render_attempts=2)
        check("g230: render_attempts = 0 وrender_version = 9",
              s.get("render_attempts") == 0 and s.get("render_version") == 14 and s.get("render_status") == "rendered", s)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)



def test_reel_clip_streams_r3b2a3_guards() -> None:
    """Issue #1406 (R3b-2a3، g231–g234): مقطع بلا مسار صورة أو صوت يُعدّ فشل تنزيل (تسري الإعادات)، والريل الفاشل
    بنسخة أقدم يُعاد تلقائيًا في --pending، وretry يصفّر المحاولات؛ reel.render.version = 5."""
    import json
    import tempfile
    from pathlib import Path

    from src import reel_render, reel_script

    D = "2099-12-06"
    q1, q2 = "alpha beta gamma delta epsilon zeta", "one two three four five six"
    points = [{"video_id": "v1", "statement": "s", "quote_original": q1, "quote_arabic": "ترجمة",
               "speaker": "متحدث", "channel": "قناة", "video_url": "https://youtube.com/watch?v=v1", "timestamp": 10},
              {"video_id": "v2", "statement": "s2", "quote_original": q2, "quote_arabic": "ترجمة٢",
               "speaker": "متحدث٢", "channel": "قناة٢", "video_url": "https://youtube.com/watch?v=v2", "timestamp": 10}]
    pid1, pid2 = reel_script.point_key_id(points[0]), reel_script.point_key_id(points[1])

    def clip(pid, url, ch, kind="clip"):
        return {"kind": kind, "point_id": pid, "video_url": url, "start": 9, "end": 20, "speaker_name": "",
                "speaker_role": "", "speaker_verified": False, "speaker_name_latin": "", "channel_display": ch,
                "quote_arabic": "ترجمة", "language": "en"}

    # مقطع v2 في الفهرس 3 فيكون ملفه clip_3.*
    scenes = [clip(pid1, "https://youtube.com/watch?v=v1", "قناة", "cold_open_clip"),
              {"kind": "narration", "text": "جملة أولى قصيرة."}, {"kind": "narration", "text": "جملة ثانية."},
              clip(pid2, "https://youtube.com/watch?v=v2", "قناة٢"),
              {"kind": "question", "text": "هل؟"}, {"kind": "outro"}]
    transcripts = {"v1": "[00:10] alpha beta gamma delta\n[00:14] epsilon zeta eta theta\n[00:18] tail line",
                   "v2": "[00:10] one two three four\n[00:14] five six seven eight\n[00:18] tail line"}

    def make_draft(did, **extra):
        d = {"id": did, "origin": "analysis", "format": "reel", "status": "approved_script",
             "render_status": "queued", "topic_id": "t1", "topic_date": D, "title": "ريل", "script_status": "ready",
             "review_issue": 78, "approved_script_at": "1999-01-01T00:00:00",
             "script": {"narrator": "female", "title": "عنوان", "question": "هل؟", "scenes": scenes}}
        d.update(extra)
        return store.save_draft(d), d

    def make_deps(log, v2_plan):
        """v2_plan: ما تنتجه محاولات تنزيل v2 بالترتيب ("part" جزء صوت وحده، "full" الملف الكامل)؛ الأخيرة تتكرر."""
        calls = {"n": 0}

        def run(cmd):
            log["cmds"].append(list(cmd))
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(b"x")

        def download(video_id, start, end, height, out_path):
            out_path = Path(out_path)
            if video_id == "v2":
                log["leftover"].append(sorted(p.name for p in out_path.parent.glob(f"{out_path.stem}.*")))
                kind = v2_plan[min(calls["n"], len(v2_plan) - 1)]
                calls["n"] += 1
                if kind == "part":
                    (out_path.parent / f"{out_path.stem}.f140.m4a").write_bytes(b"audio")
                    return {"tier": "a", "bytes": 5, "failures": []}
            out_path.write_bytes(b"clip")
            return {"tier": "a", "bytes": 4, "failures": []}

        def streams(p):
            return {"audio"} if str(p).endswith(".m4a") else {"video", "audio"}

        return reel_render.Deps(
            fetch_transcript=lambda vid: transcripts.get(vid), download_clip=download,
            synthesize=lambda t, voice: {"ok": True, "audio": b"mp3", "chars": len(t)},
            diacritize=lambda t: (t, None), run=run, streams=streams,
            probe=lambda p: 41.0 if "reels" in Path(p).parts else 2.0, load_points=lambda date: points,
            comment=lambda i, t: log["comments"].append(t), faces=lambda f, fr: (1280, 720, []),
            sleep=lambda s: log["sleeps"].append(s))

    def run_one(did, plan, **extra):
        log = {"cmds": [], "comments": [], "sleeps": [], "leftover": []}
        path, d = make_draft(did, **extra)
        reel_render.render_draft(path, d, cfg, make_deps(log, plan), reels_dir=tmp / "reels", workdir=tmp / "work")
        return log, json.loads(path.read_text(encoding="utf-8")), [" ".join(c) for c in log["cmds"]]

    cfg = load_config()
    check("g231: reel.render.version = 14", cfg.path("reel.render.version") == 14,cfg.path("reel.render.version"))
    tmp = Path(tempfile.mkdtemp())
    try:
        # ── g231 ──
        log, s, cmds = run_one("r3b2a3000a01", ["part"])
        check("g231: queued ومحاولة 1", s.get("render_status") == "queued" and s.get("render_attempts") == 1, s)
        check("g231: لا أمر ffmpeg لمشهد المقطع", not any("clip_3" in c for c in cmds), cmds[:3])
        check("g231: التعليق يحمل المحاولة 1 من 3", any("محاولة 1 من 3" in c for c in log["comments"]), log["comments"])
        check("g231: الإعادات جرت (انتظار مرتين)", log["sleeps"] == [20, 20], log["sleeps"])
        _, s2, _ = run_one("r3b2a3000a02", ["part"], render_attempts=2)
        check("g231: السبب «المقطع بلا صورة أو بلا صوت» عند الاستنفاد",
              s2.get("render_status") == "failed" and "المقطع بلا صورة أو بلا صوت" in (s2.get("render_error") or ""), s2)

        # ── g232 ──
        log, s, cmds = run_one("r3b2a3000b01", ["part", "full"])
        check("g232: مركَّب", s.get("render_status") == "rendered", s)
        check("g232: مشهد المقطع يقرأ clip_3.mp4 لا m4a",
              any("clip_3.mp4" in c for c in cmds) and not any(".m4a" in c for c in cmds), cmds[:4])
        check("g232: الجزئي حُذف قبل الإعادة", log["leftover"][1] == [], log["leftover"])

        # ── g233 ──
        p_old, _ = make_draft("r3b2a3000c01", status="approved_script", render_status="failed", render_version=4,
                              render_attempts=3, render_error="ffmpeg فشل", approved_script_at="1998-01-01T00:00:00")
        p_new, _ = make_draft("r3b2a3000c02", status="approved_script", render_status="failed", render_version=14,
                              render_attempts=3, render_error="ffmpeg فشل", approved_script_at="1999-01-02T00:00:00")
        ids = [p.stem for p, _d in reel_render.queued_reels(cfg)]
        check("g233: failed بنسخة 4 تُلتقط وبنسخة 5 لا", "r3b2a3000c01" in ids and "r3b2a3000c02" not in ids, ids)
        c2 = load_config()
        c2["reel"]["render"]["max_per_run"] = 500      # مسودات اختبارات سابقة منتظرة في المجلد نفسه
        batch = reel_render.pending_batch(c2)
        got = {p.stem: d for p, d in batch}
        check("g233: pending_batch تلتقط القديمة", "r3b2a3000c01" in got, list(got))
        s = json.loads(p_old.read_text(encoding="utf-8"))
        check("g233: render_attempts = 0 وrender_error محذوف قبل التركيب",
              s.get("render_attempts") == 0 and "render_error" not in s and s.get("render_status") == "queued", s)
        s = json.loads(p_new.read_text(encoding="utf-8"))
        check("g233: بنسخة 5 باقية failed", s.get("render_status") == "failed" and s.get("render_attempts") == 3, s)

        # ── g234 ──
        p, _ = make_draft("r3b2a3000d01", status="approved_script", render_status="failed", render_attempts=3,
                          render_error="x")
        ok = reel_render.retry("r3b2a3000d01", cfg)
        s = json.loads(p.read_text(encoding="utf-8"))
        check("g234: retry ← queued وrender_attempts = 0",
              ok and s.get("render_status") == "queued" and s.get("render_attempts") == 0, s)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reel_cover_auto_r3b2a4_guards() -> None:
    """Issue #1408 (R3b-2a4، g235–g242): الغطاء الكحلي والشريط المعتم تمامًا فقط حين في أسفل المقطع شريط أخبار أو لافتة
    (كاشف حواف أفقية مستقيمة في الإطارات)؛ لا شيء في أسفله ← بلا غطاء وشريط بشفافيته؛ true/false كما هما بلا كاشف."""
    import json
    import tempfile
    from pathlib import Path

    import numpy as np

    from src import reel_render, reel_script

    cfg = load_config()
    H, W = 720, 1280
    rng = np.random.default_rng(7)

    def noise():
        # ضجيج طبيعي مُنعَّم: لا فرق بين صفين يقترب من عتبة الحافة
        a = rng.uniform(90, 150, (H, W))
        for _ in range(6):
            a = (a + np.roll(a, 1, 0) + np.roll(a, -1, 0) + np.roll(a, 1, 1) + np.roll(a, -1, 1)) / 5
        return a

    def frames(rows=None, x0=0, x1=W, which=None):
        out = []
        for k in range(6):
            f = noise()
            if rows and k in (which if which is not None else range(6)):
                f[rows[0]:rows[1], x0:x1] = 235.0
            out.append(f.astype(np.uint8))
        return out

    cw = int(H * 9 / 16)
    d = reel_render.has_bottom_graphics
    check("g235: ضجيج بلا خط مستقيم ← False", d(frames(), 0, cw, cfg) is False)
    check("g236: شريط ثابت بعرض الإطار ← True", d(frames(rows=(600, 660)), 0, cw, cfg) is True)
    check("g237: الشريط في إطارين من ستة ← False", d(frames(rows=(600, 660), which={0, 1}), 0, cw, cfg) is False)
    left = frames(rows=(600, 660), x1=400)
    check("g238: شريط في النصف الأيسر والنافذة عند 700 ← False", d(left, 700, cw, cfg) is False)
    check("g238: الشريط نفسه والنافذة عند 0 ← True", d(left, 0, cw, cfg) is True)
    check("g239: الشريط فوق المنطقة ← False", d(frames(rows=(200, 260)), 0, cw, cfg) is False)

    def boom(*a):
        raise RuntimeError("x")

    check("g240: دالة استخراج ترفع ← True", reel_render.detect_cover("clip.mp4", 0, cw, cfg, boom) is True)
    check("g240: إطارات فاسدة ← True", d([None] * 6, 0, cw, cfg) is True)

    D = "2099-12-07"
    quote = "alpha beta gamma delta epsilon zeta eta theta"
    points = [{"video_id": "v1", "statement": "s", "quote_original": quote, "quote_arabic": "ترجمة",
               "speaker": "متحدث", "channel": "قناة", "video_url": "https://youtube.com/watch?v=v1", "timestamp": 10},
              {"video_id": "v2", "statement": "s2", "quote_original": quote, "quote_arabic": "ترجمة٢",
               "speaker": "متحدث٢", "channel": "قناة٢", "video_url": "https://youtube.com/watch?v=v2", "timestamp": 10}]
    clip = {"kind": "clip", "video_url": "https://youtube.com/watch?v=v1", "start": 9, "end": 20, "speaker_name": "",
            "speaker_role": "", "speaker_verified": False, "speaker_name_latin": "", "channel_display": "قناة",
            "quote_arabic": "ترجمة", "language": "en"}
    scenes = [dict(clip, kind="cold_open_clip", point_id=reel_script.point_key_id(points[0])),
              {"kind": "narration", "text": "جملة."},
              dict(clip, video_url="https://youtube.com/watch?v=v2", point_id=reel_script.point_key_id(points[1])),
              {"kind": "question", "text": "هل؟"}, {"kind": "outro"}]
    transcripts = {v: "[00:10] alpha beta gamma delta\n[00:14] epsilon zeta eta theta\n[00:18] tail line"
                   for v in ("v1", "v2")}
    bar = frames(rows=(600, 660))
    plain = frames()
    calls = {"n": 0}

    def make_deps():
        def run(cmd):
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(b"x")

        def download(video_id, start, end, height, out_path):
            Path(out_path).write_bytes(b"clip")
            return {"tier": "a", "bytes": 4, "failures": []}

        def get_frames(path, fractions):
            calls["n"] += 1
            return bar if "clip_0" in Path(path).name else plain

        return reel_render.Deps(
            fetch_transcript=lambda vid: transcripts.get(vid), download_clip=download,
            synthesize=lambda t, voice: {"ok": True, "audio": b"mp3", "chars": len(t)},
            diacritize=lambda t: (t, None), run=run,
            probe=lambda p: 41.0 if "reels" in Path(p).parts else 2.0, load_points=lambda date: points,
            comment=lambda i, t: None, faces=lambda f, fr: (W, H, []), frames=get_frames)

    tmp = Path(tempfile.mkdtemp())
    try:
        def render(did, c):
            d0 = {"id": did, "origin": "analysis", "format": "reel", "status": "approved_script",
                  "render_status": "queued", "topic_id": "t1", "topic_date": D, "title": "ريل", "script_status": "ready",
                  "script": {"narrator": "female", "title": "عنوان", "question": "هل؟", "scenes": scenes}}
            path = store.save_draft(d0)
            reel_render.render_draft(path, d0, c, make_deps(), reels_dir=tmp / "reels", workdir=tmp / "work")
            return json.loads(path.read_text(encoding="utf-8"))

        top = int(cfg.path("reel.render.band.top"))
        alpha = float(cfg.path("reel.render.band.alpha"))
        check("g241: الإعداد الافتراضي auto", cfg.path("reel.render.band.cover") == "auto", cfg.path("reel.render.band.cover"))
        check("g241: reel.render.version = 14", cfg.path("reel.render.version") == 14)
        s = render("r3b2a4000a01", cfg)
        crops = s.get("render_crops") or {}
        check("g241: render_crops يحمل cover لكل مقطع",
              crops.get("0", {}).get("cover") is True and crops.get("2", {}).get("cover") is False, crops)
        st1, bd1 = reel_render.frame_clip_layers(cfg, dict(clip), cover=True)
        st0, bd0 = reel_render.frame_clip_layers(cfg, dict(clip), cover=False)
        check("g241: كشاف True ← ثابتة معتمة وشريط alpha 255",
              st1.getpixel((540, 1700))[3] == 255 and bd1.getpixel((540, top + 10))[3] == 255,
              (st1.getpixel((540, 1700)), bd1.getpixel((540, top + 10))))
        check("g241: كشاف False ← ثابتة شفافة وشريط round(255×0.94)",
              st0.getpixel((540, 1700))[3] == 0 and bd0.getpixel((540, top + 10))[3] == round(255 * alpha),
              (st0.getpixel((540, 1700)), bd0.getpixel((540, top + 10))))

        for val in (True, False):
            c = load_config()
            c["reel"]["render"]["band"]["cover"] = val
            calls["n"] = 0
            render("r3b2a4000b0" + str(int(val)), c)
            st, bd = reel_render.frame_clip_layers(c, dict(clip))
            check("g242: cover=" + str(val) + " ← بلا استدعاء الكاشف", calls["n"] == 0, calls["n"])
            check("g242: cover=" + str(val) + " ← السلوك الحالي حرفيًا",
                  (st.getpixel((540, 1700))[3] == 255) is val and bd.getpixel((540, top + 10))[3] == round(255 * alpha))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reel_background_r3b2b_guards() -> None:
    """Issue #1411 (R3b-2b، g243–g251): صورة خلفية واحدة لمشاهد الراوي. تُختار عند كتابة السيناريو بسلّم كسول
    (يدوية ← خبر ← بحث ويب ← حرة ← لا شيء)، وتُعرض في المرحلة 2، وتُركَّب بشكلين: (أ) بلا أشخاص مظلَّلة بالكحلي (0.72)
    و(ب) فيها أشخاص بتظليل خفيف وصندوق سفلي كحلي بخط ذهبي؛ فشل التنزيل ← الكحلي الحالي حرفيًا."""
    import json
    import tempfile
    from pathlib import Path

    import numpy as np
    from PIL import Image

    from src import imaging, reel_render, reel_script, stages, youtube_publish

    cfg = load_config()
    sentence = " ".join(["جملة تجريبية للراوي"] * 7)
    astro = Image.open("tests/fixtures/faces/astronaut.jpg").convert("RGB")
    xs = np.linspace(20, 235, 1400, dtype=np.uint8)
    grad = Image.fromarray(np.stack([np.tile(xs, (800, 1)), np.tile(xs[::-1], (800, 1)),
                                     np.full((800, 1400), 140, np.uint8)], axis=2))

    def guarded(name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 -- الحالة الفاشلة تُسجَّل ولا توقف بقية الحالات
            check(name + ": استثناء", False, repr(exc))

    def mask(a, b, thr=40):
        return np.abs(np.asarray(a.convert("RGB"), dtype=int) - np.asarray(b.convert("RGB"), dtype=int)).max(axis=2) > thr

    def bbox(m):
        ys, xs_ = np.where(m)
        return None if len(ys) == 0 else (int(xs_.min()), int(ys.min()), int(xs_.max()), int(ys.max()))

    # ── g243: السلّم الكسول ──
    def g243():
        def rig(news=None, web=None, free=None, ok=lambda u: True):
            calls = {"news": 0, "web": 0, "free": 0}

            def n(*a):
                calls["news"] += 1
                return news or []

            def w(q, c, state=None):
                calls["web"] += 1
                if web == "cap" and state is not None:
                    state["skipped"] = "cap"
                    return []
                return web or []

            def f(*a):
                calls["free"] += 1
                return free or []

            return calls, {"news": n, "web": w, "free": f, "download": lambda u: object() if ok(u) else None}

        base = {"id": "r3b2b000g243", "title": "عنوان", "event": "حدث"}
        calls, pv = rig()
        r = reel_render.pick_background(dict(base, manual_image="https://m/x.jpg"), cfg, pv)
        check("g243: manual ← kind manual ولا مزوّد", r["kind"] == "manual" and r["url"] == "https://m/x.jpg"
              and sum(calls.values()) == 0, (r, calls))
        calls, pv = rig(news=[{"url": "https://n/1.jpg", "publisher": "Reuters"}],
                        web=[{"url": "https://w/1.jpg", "domain": "w"}], free=["https://f/1.jpg"])
        r = reel_render.pick_background(dict(base), cfg, pv)
        check("g243: صورة خبر ← news_photo بلا ويب ولا حرة", r["kind"] == "news_photo" and r["publisher"] == "Reuters"
              and calls == {"news": 1, "web": 0, "free": 0}, (r, calls))
        calls, pv = rig(news=[], web=[{"url": "https://w/1.jpg", "domain": "w.com"}], free=["https://f/1.jpg"])
        r = reel_render.pick_background(dict(base), cfg, pv)
        check("g243: خبر فارغ ← web_search بلا حرة", r["kind"] == "web_search" and r["publisher"] == "w.com"
              and calls["free"] == 0, (r, calls))
        calls, pv = rig(news=[{"url": "https://n/1.jpg", "publisher": "R"}],
                        web=[{"url": "https://w/1.jpg", "domain": "w.com"}], ok=lambda u: "n/" not in u)
        r = reel_render.pick_background(dict(base), cfg, pv)
        check("g243: فشل تنزيل مرشّح الخبر ← الدرجة التالية", r["kind"] == "web_search", r)
        calls, pv = rig(web="cap", free=["https://f/1.jpg"])
        r = reel_render.pick_background(dict(base), cfg, pv)
        check("g243: الويب متخطّى بالسقف ← free", r["kind"] == "free" and r["url"] == "https://f/1.jpg", (r, calls))
        calls, pv = rig()
        r = reel_render.pick_background(dict(base), cfg, pv)
        check("g243: الكل فارغ ← none", r["kind"] == "none" and not r["url"], r)
    guarded("g243", g243)

    # ── g244: kind none ← إطارات اليوم بالبكسل ──
    def g244():
        tmp0 = Path(tempfile.mkdtemp())
        try:
            parts = [(sentence, 2.0), ("جملة ثانية قصيرة.", 1.2)]
            fps = float(cfg.path("reel.render.fps"))
            silence = float(cfg.path("reel.tts.sentence_silence", 0.35))
            import copy as _copy
            cfg_tw = _copy.deepcopy(cfg)
            cfg_tw["reel"]["render"]["reveal"]["mode"] = "typewriter"     # الاختبار للكتابة حرفًا حرفًا
            made = reel_render._narration_frames(parts, 1, cfg_tw, tmp0, 0.0, None)
            expected = []
            for text, dur in parts:
                hold = min(silence, dur)
                for prefix, _ in reel_render.typewriter_steps(text, dur - hold, hold, fps):
                    expected.append(reel_render.frame_narration_typed(cfg, text, prefix))
            same = len(made) == len(expected) and all(
                not mask(Image.open(p), e, 0).any() for (p, _), e in zip(made, expected))
            check("g244: بلا خلفية ← إطارات الراوي مطابقة بالبكسل لإطارات اليوم", same, (len(made), len(expected)))
            full = reel_render.frame_narration(cfg, sentence)
            check("g244: bg=None ← frame_narration نفسه",
                  not mask(reel_render.frame_narration(cfg, sentence, bg=None), full, 0).any())
        finally:
            shutil.rmtree(tmp0, ignore_errors=True)
    guarded("g244", g244)

    # ── g245: اختيار الشكل ──
    def g245():
        check("g245: صورة رائد فضاء ← layout A أيضًا (حُذف B في #1423)", reel_render.prepare_background(cfg, astro)["layout"] == "A")
        check("g245: تدرّج لوني بلا وجه ← layout A", reel_render.prepare_background(cfg, grad)["layout"] == "A")
    guarded("g245", g245)

    # ── g246: الشكل (أ) ──
    def g246():
        bg = reel_render.prepare_background(cfg, grad)
        empty = reel_render.frame_narration_typed(cfg, sentence, "", bg=bg)
        full = reel_render.frame_narration(cfg, sentence, bg=bg)
        plain = reel_render.frame_narration(cfg, sentence)
        navy = Image.new("RGB", plain.size, imaging.hex_rgb(cfg.path("brand.primary_color")))
        ink_bg, ink_plain = bbox(mask(full, empty)), bbox(mask(plain, navy))
        close = ink_bg and ink_plain and all(abs(a - b) <= 3 for a, b in zip(ink_bg, ink_plain))
        check("g246: حبر النص في مواضع frame_narration نفسها", bool(close), (ink_bg, ink_plain))
        arr = np.asarray(empty, dtype=float)
        check("g246: الخلفية ليست لونًا واحدًا", arr.std() > 3, arr.std())

        def lum(a):
            return float(np.asarray(a.convert("L"), dtype=float).mean())
        orig = grad.resize(empty.size)
        check("g246: الإضاءة أقل من الصورة الأصلية", lum(empty) < lum(orig) - 20, (lum(empty), lum(orig)))
    guarded("g246", g246)

    # ── g247: صورة فيها وجه تُعرض بالتخطيط الوحيد A (حُذف الصندوق السفلي في #1423) ──
    def g247():
        bg = reel_render.prepare_background(cfg, astro)
        empty = reel_render.frame_narration_typed(cfg, sentence, "", bg=bg)
        full = reel_render.frame_narration(cfg, sentence, bg=bg)
        gold = imaging.hex_rgb(cfg.path("brand.accent_color"))
        row = [tuple(int(v) for v in np.asarray(empty.convert("RGB"))[1200, x]) for x in (100, 400, 700, 900)]
        check("g247: لا صندوق ذهبي عند y=1200", not all(p == gold for p in row), row)
        m = mask(full, empty)
        rows = np.where(m.any(axis=1))[0]
        check("g247: كل الحبر داخل المنطقة الآمنة 230–1480", len(rows) > 0 and rows.min() >= 230 and rows.max() <= 1480,
              (rows.min() if len(rows) else None, rows.max() if len(rows) else None))
        last = reel_render.frame_narration_typed(cfg, sentence, sentence, bg=bg)
        check("g247: الإطار الأخير مطابق للكامل", not mask(last, full, 0).any())
    guarded("g247", g247)

    # ── أدوات التركيب بمزيَّفات ──
    D = "2099-12-07"
    quote = "alpha beta gamma delta epsilon zeta eta theta"
    points = [{"video_id": v, "statement": "s", "quote_original": quote, "quote_arabic": "ترجمة", "speaker": "متحدث",
               "channel": "قناة", "video_url": "https://youtube.com/watch?v=" + v, "timestamp": 10} for v in ("v1", "v2")]
    clip = {"kind": "clip", "start": 9, "end": 20, "speaker_name": "", "speaker_role": "", "speaker_verified": False,
            "speaker_name_latin": "", "channel_display": "قناة", "quote_arabic": "ترجمة", "language": "en"}
    scenes = [dict(clip, kind="cold_open_clip", video_url=points[0]["video_url"], point_id=reel_script.point_key_id(points[0])),
              {"kind": "narration", "text": sentence},
              dict(clip, video_url=points[1]["video_url"], point_id=reel_script.point_key_id(points[1])),
              {"kind": "question", "text": "هل؟"}, {"kind": "outro"}]
    transcripts = {v: "[00:10] alpha beta gamma delta\n[00:14] epsilon zeta eta theta\n[00:18] tail line"
                   for v in ("v1", "v2")}
    tmp = Path(tempfile.mkdtemp())
    comments: list = []

    def make_deps(bg_image=None, providers=None):
        def run(cmd):
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(b"x")

        def download(video_id, start, end, height, out_path):
            Path(out_path).write_bytes(b"clip")
            return {"tier": "a", "bytes": 4, "failures": []}

        return reel_render.Deps(
            fetch_transcript=lambda vid: transcripts.get(vid), download_clip=download,
            synthesize=lambda t, voice: {"ok": True, "audio": b"mp3", "chars": len(t)}, diacritize=lambda t: (t, None),
            run=run, probe=lambda p: 41.0 if "reels" in Path(p).parts else 2.0, load_points=lambda date: points,
            comment=lambda i, t: comments.append((i, t)), faces=lambda f, fr: (1280, 720, []),
            bg_image=bg_image, bg_providers=providers)

    def render(did, c, deps, **extra):
        d0 = {"id": did, "origin": "analysis", "format": "reel", "status": "approved_script", "render_status": "queued",
              "topic_id": "t1", "topic_date": D, "title": "ريل", "script_status": "ready", "review_issue": 5,
              "script": {"narrator": "female", "title": "عنوان", "question": "هل؟", "scenes": scenes}, **extra}
        path = store.save_draft(d0)
        reel_render.render_draft(path, d0, c, deps, reels_dir=tmp / "reels", workdir=tmp / "work")
        return path, json.loads(path.read_text(encoding="utf-8"))

    try:
        # ── g248: بند المرحلة 2 ──
        def g248():
            d = {"id": "r3b2b000g248", "title": "ريل", "format": "reel", "script_status": "ready",
                 "headlines": ["أ", "ب", "ج"], "headline_selected": 0,
                 "script": {"narrator": "female", "title": "عنوان", "question": "هل؟", "scenes": scenes},
                 "reel_bg": {"url": "https://img.example/bg.jpg", "kind": "news_photo", "publisher": "Reuters"}}
            text = "\n".join(youtube_publish._reel_item_lines(1, d, cfg))
            check("g248: «خلفية الراوي» وصورة بالرابط", "خلفية الراوي" in text and "<img" in text
                  and "https://img.example/bg.jpg" in text and "Reuters" in text)
            check("g248: حقل الصورة لمعرّف المسودة", stages.image_field(d["id"], cfg) in text)
            text2 = "\n".join(youtube_publish._reel_item_lines(1, {**d, "manual_image": "https://img.example/manual.jpg"}, cfg))
            check("g248: manual_image يُعرض بدل المحفوظ", "https://img.example/manual.jpg" in text2
                  and "https://img.example/bg.jpg" not in text2)
            d3 = {k: v for k, v in d.items() if k != "reel_bg"}
            text3 = "\n".join(youtube_publish._reel_item_lines(1, d3, cfg))
            check("g248: بلا صورة ← خلفية كحلية", "خلفية كحلية" in text3 and "<img" not in text3)
        guarded("g248", g248)

        news_pv = {"news": lambda *a: [{"url": "https://n/1.jpg", "publisher": "Reuters"}], "web": lambda *a: [],
                   "free": lambda *a: [], "download": lambda u: astro}

        # ── g249: الختام ──
        def g249():
            oc = reel_render.outro_credit
            check("g249: news_photo ← «الصورة: رويترز» (الاسم بالعربية منذ #1413)",
                  "الصورة: رويترز" in oc(cfg, {"kind": "news_photo", "publisher": "Reuters"}))
            check("g249: web_search ← «الصورة: x.com»",
                  "الصورة: x.com" in oc(cfg, {"kind": "web_search", "publisher": "x.com"}))
            check("g249: free ← «صورة تعبيرية»", "صورة تعبيرية" in oc(cfg, {"kind": "free", "publisher": ""}))
            check("g249: none وmanual ← لا شيء", oc(cfg, {"kind": "none"}) == "" and oc(cfg, {"kind": "manual"}) == "")
            seen: list = []
            real = reel_render.frame_outro

            def spy(cfg_, channels, boxes=None, credit=""):
                seen.append(credit)
                return real(cfg_, channels, boxes, credit)
            reel_render.frame_outro = spy
            try:
                render("r3b2b000g249", cfg, make_deps(bg_image=lambda u: grad, providers=news_pv))
            finally:
                reel_render.frame_outro = real
            check("g249: التركيب يمرّر الاعتماد إلى الختام", any("الصورة: رويترز" in c for c in seen), seen)
        guarded("g249", g249)

        # ── g250: فشل التنزيل ──
        def g250():
            calls: list = []
            r_n, r_t = reel_render.frame_narration, reel_render.frame_narration_typed

            def spy_n(c, s, boxes=None, bg=None):
                calls.append(bg)
                return r_n(c, s, boxes, bg)

            def spy_t(c, s, p, boxes=None, bg=None):
                calls.append(bg)
                return r_t(c, s, p, boxes, bg)
            r_r = reel_render.frame_narration_reveal

            def spy_r(c, s, a, boxes=None, bg=None):
                calls.append(bg)
                return r_r(c, s, a, boxes, bg)
            reel_render.frame_narration, reel_render.frame_narration_typed = spy_n, spy_t
            reel_render.frame_narration_reveal = spy_r
            comments.clear()
            try:
                _, d = render("r3b2b000g250", cfg, make_deps(bg_image=lambda u: None),
                              reel_bg={"url": "https://img.example/bad.jpg", "kind": "news_photo", "publisher": "R"})
            finally:
                reel_render.frame_narration, reel_render.frame_narration_typed = r_n, r_t
                reel_render.frame_narration_reveal = r_r
            check("g250: التركيب نجح بإطارات كحلية",
                  d.get("render_status") == "rendered" and calls and all(b is None for b in calls),
                  (d.get("render_status"), len(calls)))
            check("g250: التعليق فيه «تعذّر تنزيل صورة خلفية الراوي»",
                  any("تعذّر تنزيل صورة خلفية الراوي" in t for _, t in comments), comments)
        guarded("g250", g250)

        # ── g251: --pending ──
        def g251():
            check("g251: reel.render.version = 14", cfg.path("reel.render.version") == 14, cfg.path("reel.render.version"))
            d0 = {"id": "r3b2b000g251", "origin": "analysis", "format": "reel", "status": "approved_script",
                  "render_status": "rendered", "render_version": 6, "topic_id": "t1", "topic_date": D, "title": "ريل",
                  "script_status": "ready", "approved_script_at": "2000-01-01T00:00:00+00:00",
                  "script": {"narrator": "female", "title": "عنوان", "question": "هل؟", "scenes": scenes}}
            path = store.save_draft(d0)
            c2 = load_config()
            c2["reel"]["render"]["max_per_run"] = 500
            batch = {p.stem: d for p, d in reel_render.pending_batch(c2)}
            check("g251: --pending يعيد ريل النسخة 6", "r3b2b000g251" in batch, list(batch)[:3])
            reel_render.render_draft(path, batch.get("r3b2b000g251", d0), c2,
                                     make_deps(bg_image=lambda u: grad, providers=news_pv),
                                     reels_dir=tmp / "reels", workdir=tmp / "work")
            d = json.loads(path.read_text(encoding="utf-8"))
            bg = d.get("reel_bg") or {}
            check("g251: اختار الخلفية وحفظها", bg.get("kind") == "news_photo" and bg.get("url") == "https://n/1.jpg", bg)
            check("g251: الشكل محفوظ والنسخة 14", bg.get("layout") == "A" and d.get("render_version") == 14,
                  (bg.get("layout"), d.get("render_version")))
        guarded("g251", g251)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reel_music_r3b2c_guards() -> None:
    """Issue #1413 (R3b-2c، g252–g256): موسيقى خلفية تتناوب بين مقطوعات المستودع الخاص (MUSIC_DIR) وتُمزج تحت الكلام في أمر
    الشعار الأخير نفسه، واسم مصدر الصورة بالعربية في سطر مستقل تحت «المقاطع من» لا ملحقًا به."""
    import json
    import tempfile
    from pathlib import Path

    from src import imaging, reel_render, reel_script

    cfg = load_config()
    D = "2099-12-08"
    quote = "alpha beta gamma delta epsilon zeta eta theta"
    points = [{"video_id": v, "statement": "s", "quote_original": quote, "quote_arabic": "ترجمة", "speaker": "متحدث",
               "channel": "قناة", "video_url": "https://youtube.com/watch?v=" + v, "timestamp": 10} for v in ("v1", "v2")]
    clip = {"kind": "clip", "start": 9, "end": 20, "speaker_name": "", "speaker_role": "", "speaker_verified": False,
            "speaker_name_latin": "", "channel_display": "قناة", "quote_arabic": "ترجمة", "language": "en"}
    scenes = [dict(clip, kind="cold_open_clip", video_url=points[0]["video_url"], point_id=reel_script.point_key_id(points[0])),
              {"kind": "narration", "text": "جملة تجريبية للراوي"},
              dict(clip, video_url=points[1]["video_url"], point_id=reel_script.point_key_id(points[1])),
              {"kind": "question", "text": "هل؟"}, {"kind": "outro"}]
    transcripts = {v: "[00:10] alpha beta gamma delta\n[00:14] epsilon zeta eta theta\n[00:18] tail line"
                   for v in ("v1", "v2")}
    tmp = Path(tempfile.mkdtemp())
    music = tmp / "music"
    real_dir = getattr(reel_render, "MUSIC_DIR", None)
    cmds: list = []

    def guarded(name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 -- الحالة الفاشلة تُسجَّل ولا توقف بقية الحالات
            check(name + ": استثناء", False, repr(exc))

    def make_deps(providers=None):
        def run(cmd):
            cmds.append(list(cmd))
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(b"x")

        def download(video_id, start, end, height, out_path):
            Path(out_path).write_bytes(b"clip")
            return {"tier": "a", "bytes": 4, "failures": []}

        empty = {"news": lambda *a: [], "web": lambda *a, **k: [], "free": lambda *a: [], "download": lambda u: None}
        return reel_render.Deps(
            fetch_transcript=lambda vid: transcripts.get(vid), download_clip=download,
            synthesize=lambda t, voice: {"ok": True, "audio": b"mp3", "chars": len(t)}, diacritize=lambda t: (t, None),
            run=run, probe=lambda p: 40.0, load_points=lambda date: points, comment=lambda i, t: None,
            streams=lambda p: {"video", "audio"},
            faces=lambda f, fr: (1280, 720, []), bg_image=(lambda u: __import__("PIL.Image").Image.new("RGB", (1400, 800), (90, 120, 160))) if providers
            else (lambda u: None),
            bg_providers=providers or empty)

    def new_draft(did, **extra):
        return {"id": did, "origin": "analysis", "format": "reel", "status": "approved_script", "render_status": "queued",
                "topic_id": "t1", "topic_date": D, "title": "ريل", "script_status": "ready",
                "script": {"narrator": "female", "title": "عنوان", "question": "هل؟", "scenes": scenes}, **extra}

    def render(did, c=cfg, **extra):
        d0 = new_draft(did, **extra)
        path = store.save_draft(d0)
        cmds.clear()
        reel_render.render_draft(path, d0, c, make_deps(), reels_dir=tmp / "reels", workdir=tmp / "work")
        return path, json.loads(path.read_text(encoding="utf-8"))

    def final_cmd():
        return next((c for c in cmds if any("overlay=W-w-" in str(x) for x in c)), [])

    def seed(did, name, at):
        return store.save_draft({"id": did, "origin": "analysis", "format": "reel", "status": "approved_script",
                                 "render_status": "rendered", "reel_music": name, "rendered_at": at, "title": "ريل"})

    try:
        music.mkdir()
        for n in ("a.mp3", "b.mp3", "c.mp3"):
            (music / n).write_bytes(b"ID3")
        reel_render.MUSIC_DIR = music

        # ── g252: التناوب بالاسم ──
        def g252():
            pm = reel_render.pick_music
            check("g252: لا ريل سابق ← a.mp3", pm({"id": "r3b2c00g252x"}, cfg) == "a.mp3")
            p1 = seed("r3b2c00g252a", "b.mp3", "2099-01-01T00:00:00+00:00")
            check("g252: آخر ريل b.mp3 ← c.mp3", pm({"id": "r3b2c00g252x"}, cfg) == "c.mp3")
            p2 = seed("r3b2c00g252b", "c.mp3", "2099-02-01T00:00:00+00:00")
            check("g252: الأحدث c.mp3 ← a.mp3 (دورة)", pm({"id": "r3b2c00g252x"}, cfg) == "a.mp3")
            check("g252: إعادة تركيب reel_music = b.mp3 تبقيه",
                  pm({"id": "r3b2c00g252x", "reel_music": "b.mp3"}, cfg) == "b.mp3")
            check("g252: مقطوعة محفوظة لم تعد موجودة ← تناوب عادي",
                  pm({"id": "r3b2c00g252x", "reel_music": "gone.mp3"}, cfg) == "a.mp3")
            p1.unlink()
            p2.unlink()
            check("g252: بعد الحذف ← a.mp3", pm({"id": "r3b2c00g252x"}, cfg) == "a.mp3")
            p3 = seed("r3b2c00g252c", "a.mp3", "2099-03-01T00:00:00+00:00")
            check("g252: إعادة تركيب a.mp3 تبقيه a.mp3",
                  pm({"id": "r3b2c00g252x", "reel_music": "a.mp3"}, cfg) == "a.mp3")
            p3.unlink()
        guarded("g252", g252)

        # ── g253: مرشحات المزج ──
        def g253():
            path, d = render("r3b2c00g253a")
            cmd = final_cmd()
            i = cmd.index("-stream_loop") if "-stream_loop" in cmd else -1
            check("g253: -stream_loop -1 قبل ملف المقطوعة", i >= 0 and cmd[i + 1] == "-1" and cmd[i + 2] == "-i"
                  and str(cmd[i + 3]).endswith("a.mp3"), cmd[:14])
            fc = str(cmd[cmd.index("-filter_complex") + 1]) if "-filter_complex" in cmd else ""
            check("g253: loudnorm المقطوعة −26", "loudnorm=I=-26:TP=-3:LRA=11" in fc, fc)
            check("g253: ظهور تدريجي 1.5", "afade=t=in:d=1.5" in fc, fc)
            check("g253: اختفاء تدريجي st = 40 − 3", "afade=t=out:st=37" in fc and ":d=3" in fc, fc)
            check("g253: sidechaincompress بقيم duck",
                  "sidechaincompress=threshold=0.03:ratio=8:attack=30:release=500:makeup=1" in fc, fc)
            check("g253: asplit للصوت", "asplit=2" in fc, fc)
            k = fc.find("amix=inputs=2:normalize=0")
            check("g253: amix ثم loudnorm النهائي −16", k >= 0 and "loudnorm=I=-16" in fc[k:], fc)
            check("g253: حُفظ reel_music", d.get("reel_music") == "a.mp3", d.get("reel_music"))
            check("g253: لا -af منفصل (المزج في filter_complex)", "-af" not in cmd, cmd)
        guarded("g253", g253)

        # ── g254: بلا موسيقى = أمر اليوم حرفيًا ──
        def g254():
            rc = cfg.path("reel.render")
            lg = rc["logo"]
            scale = "[1:v]scale=" + str(lg["width"]) + ":-1[lg];[0:v][lg]overlay=W-w-" + str(lg["right"]) + ":" \
                + str(lg["top"]) + "[v]"
            want = ["-filter_complex", scale, "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", str(rc.get("crf", 22)), "-pix_fmt", "yuv420p", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                    "-c:a", "aac", "-b:a", "128k", "-ar", str(rc.get("audio_rate", 48000)), "-ac", "2",
                    "-movflags", "+faststart"]

            def tail(cmd):
                return cmd[cmd.index("-filter_complex"):-1] if "-filter_complex" in cmd else None

            reel_render.MUSIC_DIR = tmp / "nonexistent"
            _, d = render("r3b2c00g254a")
            check("g254: مجلد غير موجود ← أمر اليوم", tail(final_cmd()) == want and "reel_music" not in d,
                  tail(final_cmd()))
            empty = tmp / "empty"
            empty.mkdir()
            reel_render.MUSIC_DIR = empty
            _, d = render("r3b2c00g254b")
            check("g254: مجلد فارغ ← أمر اليوم", tail(final_cmd()) == want and "reel_music" not in d)
            reel_render.MUSIC_DIR = music
            c2 = load_config()
            c2["reel"]["music"]["enabled"] = False
            _, d = render("r3b2c00g254c", c2)
            check("g254: enabled=false ← أمر اليوم", tail(final_cmd()) == want and "reel_music" not in d)
            reel_render.MUSIC_DIR = music
        guarded("g254", g254)

        # ── g255: سطر مصدر الصورة ──
        def g255():
            oc = reel_render.outro_credit
            got = oc(cfg, {"kind": "news_photo", "publisher": "Al Jazeera"})
            check("g255: Al Jazeera ← «الصورة: الجزيرة»", got == "الصورة: الجزيرة", got)
            check("g255: free ← «صورة تعبيرية»", oc(cfg, {"kind": "free"}) == "صورة تعبيرية")
            check("g255: none وmanual ← لا سطر", oc(cfg, {"kind": "none"}) == "" and oc(cfg, {"kind": "manual"}) == "")
            base: list = []
            reel_render.frame_outro(cfg, "قناة", base)
            ar: list = []
            reel_render.frame_outro(cfg, "قناة", ar, "الصورة: الجزيرة")
            check("g255: العربي سطر مستقل واحد تحت «المقاطع من»",
                  len(ar) == len(base) + 1 and ar[-1][1] >= base[-1][3] - 2, (len(ar), len(base), ar[-1:], base[-1:]))
            seen: list = []
            real = imaging.draw_text_ltr

            def spy_ltr(d, xy, text, *a, **k):
                seen.append(text)
                return real(d, xy, text, *a, **k)
            imaging.draw_text_ltr = spy_ltr
            try:
                la: list = []
                reel_render.frame_outro(cfg, "قناة", la, "الصورة: www.example-news.com")
                long: list = []
                reel_render.frame_outro(cfg, "قناة", long, "الصورة: " + "www.very-long-example-news-domain-name" * 2 + ".com")
            finally:
                imaging.draw_text_ltr = real
            check("g255: الاسم اللاتيني مرسوم LTR وسطر واحد بصندوقين متجاورين",
                  any("example-news" in s for s in seen) and len(la) == len(base) + 2
                  and abs(la[-1][3] - la[-2][3]) < 40 and la[-1][2] <= la[-2][0] + 30, (seen, la[-2:]))
            check("g255: الاسم الطويل يُصغَّر ولا يتجاوز الحدود",
                  len(long) == len(base) + 2 and min(b[0] for b in long[-2:]) >= 0, long[-2:])
            seen2: list = []
            real_outro = reel_render.frame_outro

            def spy(c, ch, boxes=None, credit=""):
                seen2.append(credit)
                return real_outro(c, ch, boxes, credit)
            reel_render.frame_outro = spy
            try:
                pv = {"news": lambda *a: [{"url": "https://n/1.jpg", "publisher": "Al Jazeera"}],
                      "web": lambda *a, **k: [], "free": lambda *a: [], "download": lambda u: object()}
                d0 = new_draft("r3b2c00g255")
                path = store.save_draft(d0)
                reel_render.render_draft(path, d0, cfg, make_deps(pv), reels_dir=tmp / "reels", workdir=tmp / "work")
            finally:
                reel_render.frame_outro = real_outro
            check("g255: التركيب يمرّر «الصورة: الجزيرة» وحدها", "الصورة: الجزيرة" in seen2, seen2)
        guarded("g255", g255)

        # ── g256: --pending ──
        def g256():
            check("g256: reel.render.version = 14", cfg.path("reel.render.version") == 14, cfg.path("reel.render.version"))
            d0 = new_draft("r3b2c00g256", render_status="rendered", render_version=7,
                           approved_script_at="2000-01-01T00:00:00+00:00")
            path = store.save_draft(d0)
            c2 = load_config()
            c2["reel"]["render"]["max_per_run"] = 500
            batch = {p.stem: d for p, d in reel_render.pending_batch(c2)}
            check("g256: --pending يعيد ريل النسخة 7", "r3b2c00g256" in batch, list(batch)[:3])
            reel_render.render_draft(path, batch.get("r3b2c00g256", d0), c2, make_deps(),
                                     reels_dir=tmp / "reels", workdir=tmp / "work")
            d = json.loads(path.read_text(encoding="utf-8"))
            check("g256: reel_music وrender_version = 8", d.get("reel_music") in ("a.mp3", "b.mp3", "c.mp3")
                  and d.get("render_version") == 14, (d.get("reel_music"), d.get("render_version")))
        guarded("g256", g256)
    finally:
        if real_dir is not None:
            reel_render.MUSIC_DIR = real_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_llm_haiku55_guards() -> None:
    """Issue #1416 (LLM-1، g257–g263): كل نداء Haiku يمر بنقطة تحويل واحدة `src/llm.py`؛ التراجع إلى 4.5 بسطر `llm.haiku_model`."""
    import importlib.util
    import logging
    import math
    from pathlib import Path
    from types import SimpleNamespace

    import anthropic
    import httpx

    from src import llm, merge, names_audit, preselect, screen, writer, youtube_extract
    from src.sources import Article

    cfg = load_config()
    root = Path(__file__).resolve().parent.parent
    OLD = "claude-haiku-4-5-20251001"
    NEW = "claude-haiku-5-5"
    KEYS = ["preselect.translate.model", "headlines.model", "important.extract_model", "important.gap.model",
            "merge.model", "screening.model", "names.audit.model", "youtube.extract.model",
            "youtube.extract.topic_guard_model", "youtube.cluster.merge_model", "youtube.article.guard_model",
            "youtube.review.headlines.model"]

    class Fake:
        """عميل مزيَّف يسجّل kwargs كل نداء؛ ``script`` قائمة ردود/استثناءات تُستهلك بالترتيب."""

        def __init__(self, script=None, tool=None):
            self.calls: list[dict] = []
            self.script = list(script or [])
            self.tool = tool
            self.messages = self

        def create(self, **kw):
            self.calls.append(kw)
            if self.script:
                item = self.script.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
            if self.tool is not None:
                blocks = [SimpleNamespace(type="tool_use", input=self.tool)]
            else:
                blocks = [SimpleNamespace(type="text", text="{}")]
            return SimpleNamespace(content=blocks, stop_reason="end_turn",
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=5))

    def bad_request(msg: str):
        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        return anthropic.BadRequestError(msg, response=httpx.Response(400, request=req), body=None)

    class Capture(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.records: list[logging.LogRecord] = []

        def emit(self, record):
            self.records.append(record)

    def capture():
        h = Capture()
        lg = logging.getLogger("src.llm")
        lg.addHandler(h)
        old = lg.level
        lg.setLevel(logging.DEBUG)
        return h, lambda: (lg.removeHandler(h), lg.setLevel(old))

    def articles():
        from datetime import datetime, timezone
        return [Article(title="عنوان تجريبي", link="https://a/1", summary="ملخص", source_name="مصدر",
                        region="intl", weight=1.0, published=datetime.now(timezone.utc))]

    def run_sites():
        """نداء واحد عبر كل موقع من المواقع الخمسة؛ يعيد kwargs كل نداء وسقف max_tokens القديم (قبل الضرب)."""
        out, old_tokens = {}, {}
        scfg = cfg.get("screening", {}) or {}
        batch = articles()
        f = Fake()
        screen._screen_call(f, cfg.path("screening.model"), batch, "s", scfg)
        out["screen"] = f.calls[-1]
        old_tokens["screen"] = screen._max_tokens_for(len(batch), scfg)

        f = Fake()
        real = merge._client
        merge._client = lambda: f
        try:
            merge._group_titles(["a b c", "d e f"], cfg)
        finally:
            merge._client = real
        out["merge"] = f.calls[-1]
        old_tokens["merge"] = merge._group_titles_max_tokens(2, cfg.get("merge", {}) or {})

        f = Fake()
        real = preselect._client
        preselect._client = lambda: f
        try:
            preselect.translate_titles([{"id": "c1", "title": "English headline about oil prices"}], cfg)
        finally:
            preselect._client = real
        out["preselect"] = f.calls[-1]
        old_tokens["preselect"] = preselect._translate_max_tokens(1, cfg.path("preselect.translate", {}) or {})

        f = Fake(tool={"category": "political_analysis"})
        youtube_extract.classify_topic("عنوان", "نص", cfg, client=f)
        out["topic"] = f.calls[-1]
        old_tokens["topic"] = 50

        # install_fakes يستبدل names_audit._detect في الحزمة الكاملة، فنحمّل نسخة معزولة من الملف لنختبر الدالة الحقيقية
        spec = importlib.util.spec_from_file_location("src._names_audit_real", root / "src" / "names_audit.py")
        real_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(real_mod)
        f = Fake(tool={"names": []})
        real_mod._client = lambda: f
        real_mod._detect(["text"], "نص", cfg)
        out["names"] = f.calls[-1]
        old_tokens["names"] = int(cfg.path("names.audit.max_tokens", 1500))
        return out, old_tokens

    # ── g257: لا اسم 4.5 حرفيًا خارج PRICES وتعليق التراجع، والمفاتيح كلها «haiku» ──
    leaks = [p.name for p in sorted((root / "src").glob("*.py"))
             if p.name != "writer.py" and OLD in p.read_text(encoding="utf-8")]
    wr = (root / "src" / "writer.py").read_text(encoding="utf-8")
    check("g257: اسم 4.5 في src/ لا يرد إلا في writer.PRICES", not leaks and wr.count(OLD) == 1, (leaks, wr.count(OLD)))
    code_hits = [ln for ln in (root / "config.yaml").read_text(encoding="utf-8").splitlines()
                 if OLD in ln and OLD not in ln.partition("#")[2]]
    check("g257: اسم 4.5 في config.yaml تعليقًا فقط", not code_hits, code_hits)
    bad = {k: cfg.path(k) for k in KEYS if cfg.path(k) != "haiku"}
    check("g257: مفاتيح النماذج الاثنا عشر قيمتها haiku", not bad, bad)
    check("g257: resolve('haiku') = claude-haiku-5-5", llm.resolve("haiku", cfg) == NEW, llm.resolve("haiku", cfg))
    check("g257: resolve لا يمسّ غير haiku", llm.resolve("claude-sonnet-5", cfg) == "claude-sonnet-5")
    check("g257: كتلة llm في config",
          (cfg.path("llm.haiku_effort"), cfg.path("llm.haiku_thinking"), cfg.path("llm.haiku_token_factor"))
          == ("low", "disabled", 1.3), cfg.path("llm"))

    # ── g258: haiku_params ──
    want = {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}}
    check("g258: haiku → thinking disabled وeffort low", llm.haiku_params("haiku", cfg) == want,
          llm.haiku_params("haiku", cfg))
    for m in (OLD, "claude-sonnet-5", "claude-opus-5"):
        check("g258: " + m + " → فارغ", llm.haiku_params(m, cfg) == {}, llm.haiku_params(m, cfg))

    # ── g259: خمسة مواقع تصل بنموذج 5.5 ومعاملاته وسقف مضروب ──
    out, old = run_sites()
    for name, kw in out.items():
        check(f"g259: {name} → model", kw.get("model") == NEW, kw.get("model"))
        check(f"g259: {name} → thinking disabled", kw.get("thinking") == {"type": "disabled"}, kw.get("thinking"))
        check(f"g259: {name} → effort low", kw.get("output_config") == {"effort": "low"}, kw.get("output_config"))
        expect = math.ceil(old[name] * 1.3)
        check(f"g259: {name} → max_tokens {old[name]}×1.3", kw.get("max_tokens") == expect, (kw.get("max_tokens"), expect))
    check("g259: حارس الموضوع 50 ← 65", out["topic"].get("max_tokens") == 65, out["topic"].get("max_tokens"))

    # ── g260: 400 يذكر output_config ← إعادة واحدة بلا المعاملات، وlog.error مرة واحدة ──
    llm._reset_for_tests()
    h, undo = capture()
    try:
        ok = SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")], stop_reason="end_turn",
                             usage=SimpleNamespace(input_tokens=1, output_tokens=1))
        f = Fake([bad_request("output_config.effort: not supported"), ok, ok])
        r = llm.create(f, cfg=cfg, model="haiku", max_tokens=100, messages=[])
        check("g260: النداء الثاني ينجح ويُعاد رده", r is ok and len(f.calls) == 2, len(f.calls))
        second = f.calls[1] if len(f.calls) > 1 else {}
        check("g260: الثاني بلا thinking ولا output_config",
              "thinking" not in second and "output_config" not in second, list(second))
        check("g260: الثاني بالسقف المضروب نفسه", second.get("max_tokens") == 130, second.get("max_tokens"))
        llm.create(f, cfg=cfg, model="haiku", max_tokens=100, messages=[])
        errs = [x for x in h.records if x.levelno == logging.ERROR]
        check("g260: log.error مرة واحدة لكل عملية", len(errs) == 1, len(errs))
        f2 = Fake([bad_request("messages: invalid")])
        raised = False
        try:
            llm.create(f2, cfg=cfg, model="haiku", max_tokens=100, messages=[])
        except anthropic.BadRequestError:
            raised = True
        check("g260: 400 آخر يُرفع بلا إعادة", raised and len(f2.calls) == 1, len(f2.calls))
    finally:
        undo()

    # ── g261: refusal ← طريق الفشل القائم بلا استثناء ──
    h, undo = capture()
    try:
        refusal = SimpleNamespace(content=[], stop_reason="refusal",
                                  usage=SimpleNamespace(input_tokens=1, output_tokens=0))
        err = None
        res = None
        try:
            res = screen._screen_call(Fake([refusal]), cfg.path("screening.model"), articles(), "s",
                                      cfg.get("screening", {}) or {})
        except Exception as exc:  # noqa: BLE001
            err = exc
        check("g261: screen يسلك طريق فشله بلا استثناء", err is None and res is not None and res[0] is None, (err, res))
        warns = [x for x in h.records if x.levelno == logging.WARNING and "refusal" in x.getMessage()]
        check("g261: log.warning فيه refusal", len(warns) == 1, [x.getMessage() for x in h.records])
    finally:
        undo()

    # ── g262: تكلفة «haiku» بسعر 5.5 ──
    before = writer.USAGE["cost"]
    writer.record_usage(SimpleNamespace(usage=SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000)), "haiku")
    cost = writer.USAGE["cost"] - before
    check("g262: مليون إدخال + مليون إخراج = 0.60$", abs(cost - 0.60) < 0.001, cost)

    # ── g263: التراجع بسطر llm.haiku_model ──
    old_default = llm._DEFAULT
    rolled = load_config()
    rolled["llm"]["haiku_model"] = OLD
    llm._DEFAULT = rolled
    try:
        out, olds = run_sites()
    finally:
        llm._DEFAULT = old_default
    for name, kw in out.items():
        check(f"g263: {name} → model 4.5", kw.get("model") == OLD, kw.get("model"))
        check(f"g263: {name} بلا thinking ولا output_config",
              "thinking" not in kw and "output_config" not in kw, list(kw))
        check(f"g263: {name} بسقف غير مضروب", kw.get("max_tokens") == olds[name], (kw.get("max_tokens"), olds[name]))

    # ── g264: writer._call_model يمر بـllm.create ← «haiku» يُحلّ، وSonnet لا يُمسّ ──
    llm._reset_for_tests()
    tool_resp = SimpleNamespace(content=[SimpleNamespace(type="tool_use", input={})], stop_reason="end_turn",
                                usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    old_client = writer._client
    try:
        for wmodel in ("haiku", "claude-sonnet-5"):
            wcfg = load_config()
            wcfg["writer"]["model"] = wmodel
            wcfg["writer"]["max_tokens"] = 3000
            fw = Fake([tool_resp])
            writer._client = lambda fw=fw: fw
            try:
                writer._call_model("نص", wcfg, retries=1)
            except Exception:  # noqa: BLE001 — المهم kwargs النداء لا تفسير الرد
                pass
            kw = fw.calls[0] if fw.calls else {}
            if wmodel == "haiku":
                check("g264: writer.model=haiku ← النموذج المحلول", kw.get("model") == NEW, kw.get("model"))
                check("g264: thinking disabled", kw.get("thinking") == {"type": "disabled"}, kw.get("thinking"))
                check("g264: effort low", kw.get("output_config") == {"effort": "low"}, kw.get("output_config"))
                check("g264: max_tokens = ceil(3000×1.3) = 3900", kw.get("max_tokens") == 3900, kw.get("max_tokens"))
                check("g264: system ما زال يحمل cache_control",
                      bool(kw.get("system")) and "cache_control" in kw["system"][0], kw.get("system"))
            else:
                check("g264: Sonnet بلا thinking ولا output_config",
                      kw.get("model") == "claude-sonnet-5" and "thinking" not in kw and "output_config" not in kw, list(kw))
                check("g264: Sonnet بسقف غير مضروب", kw.get("max_tokens") == 3000, kw.get("max_tokens"))
    finally:
        writer._client = old_client

    # ── g265: بعد رفض 400 مرة تُرسل النداءات التالية بلا المعاملات مباشرة (3 طلبات لا 4) ──
    llm._reset_for_tests()
    h, undo = capture()
    try:
        ok = SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")], stop_reason="end_turn",
                             usage=SimpleNamespace(input_tokens=1, output_tokens=1))
        f = Fake([bad_request("output_config.effort: not supported"), ok, ok])
        llm.create(f, cfg=cfg, model="haiku", max_tokens=100, messages=[])
        llm.create(f, cfg=cfg, model="haiku", max_tokens=100, messages=[])
        check("g265: مجموع الطلبات 3 لا 4", len(f.calls) == 3, len(f.calls))
        third = f.calls[2] if len(f.calls) > 2 else {}
        check("g265: الثالث بلا thinking ولا output_config", "thinking" not in third and "output_config" not in third, list(third))
        check("g265: الثالث بسقف مضروب 130", third.get("max_tokens") == 130, third.get("max_tokens"))
        errs = [x for x in h.records if x.levelno == logging.ERROR]
        check("g265: log.error مرة واحدة", len(errs) == 1, len(errs))
    finally:
        undo()


def test_reel_text_r5a_guards() -> None:
    """Issue #1419 (R5a، g266–g277): توسيط نص الريل، وخط الرقعة للنصوص الكبيرة وحدها، وظهور الراوي سطرًا فسطرًا بخط أكبر،
    وشريط المتحدث الجديد (الاسم اللاتيني للقناة)."""
    import copy
    import hashlib
    import tempfile
    from pathlib import Path

    from PIL import Image, ImageDraw

    from src import imaging, reel_render, reel_script

    cfg = load_config()
    W = int(cfg.path("reel.render.width"))
    aref = cfg.path("reel.render.fonts.display")
    factor = float(cfg.path("reel.render.fonts.display_line_factor", 1.85))
    long_text = " ".join(["كلمة"] * 40)

    # ── g266: التوسيط ──
    pen = reel_render._Pen(cfg, [])
    check("g266: cx == 540", pen.cx == 540, pen.cx)
    check("g266: الهامشان متساويان x0 == W − x1", pen.x0 == W - pen.x1, (pen.x0, pen.x1))
    check("g266: max_w == 820", pen.max_w == 820, pen.max_w)
    for name, fn in (("frame_title", lambda b: reel_render.frame_title(cfg, long_text, "2099/01/01", b)),
                     ("frame_question", lambda b: reel_render.frame_question(cfg, long_text, b)),
                     ("frame_narration", lambda b: reel_render.frame_narration(cfg, long_text, b))):
        boxes: list = []
        fn(boxes)
        off = [round((b[0] + b[2]) / 2 - 540, 1) for b in boxes]
        check(f"g266: {name} مركز حبر كل سطر ضمن ±4 من 540", bool(boxes) and all(abs(o) <= 4 for o in off), off)

    # ── g267: ملف الخط والرخصة وحارس المسار ──
    def sha(path: str) -> str:
        p = Path(path)
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""

    check("g267: بصمة ArefRuqaa-Bold.ttf",
          sha("assets/fonts/ArefRuqaa-Bold.ttf") == "247071015b7eefd63f94d6e47949c5d10294ed31bd432f809ba9a219d93f91bb",
          sha("assets/fonts/ArefRuqaa-Bold.ttf"))
    check("g267: بصمة ArefRuqaa-OFL.txt",
          sha("assets/fonts/ArefRuqaa-OFL.txt") == "41ac14451a624c69490e24b9aaaaa1f65dc9dc17c3f6f38172fc43d5ba654a1b",
          sha("assets/fonts/ArefRuqaa-OFL.txt"))
    check("g267: إعداد الخط", aref == "assets/fonts/ArefRuqaa-Bold.ttf", aref)

    def record(fn):
        fits, loads = [], []
        o_fit, o_load = imaging.fit_text, imaging.load_font

        def fit_spy(draw, text, font_path, *a, **k):
            fits.append(font_path)
            return o_fit(draw, text, font_path, *a, **k)

        def load_spy(path, *a, **k):
            loads.append(path)
            return o_load(path, *a, **k)

        imaging.fit_text, imaging.load_font = fit_spy, load_spy
        try:
            fn()
        finally:
            imaging.fit_text, imaging.load_font = o_fit, o_load
        return fits, loads

    fits, loads = record(lambda: reel_render.frame_title(cfg, "عنوان قصير", "2099/01/01"))
    check("g267: عنوان frame_title بالرقعة وحدها في fit_text", fits and set(fits) == {aref}, fits)
    check("g267: الشارة بـCairo والتاريخ والمعرّف بـTajawal", reel_render.CAIRO in loads and reel_render.TAJAWAL_B in loads, loads)
    fits, loads = record(lambda: reel_render.frame_question(cfg, "سؤال قصير"))
    check("g267: السؤال بالرقعة وعلامة الاستفهام وشاركونا بخطيهما", fits and set(fits) == {aref} and reel_render.CAIRO in loads
          and reel_render.TAJAWAL_B in loads, (fits, loads))
    fits, loads = record(lambda: reel_render.frame_narration(cfg, "جملة قصيرة"))
    check("g267: الراوي بالرقعة", fits == [aref], fits)
    fits, loads = record(lambda: reel_render.frame_outro(cfg, "الجزيرة", credit="الصورة: وكالة"))
    check("g267: «تابعوا الموجز» بالرقعة والباقي بخطه", aref in loads and fits == [reel_render.TAJAWAL_B, reel_render.TAJAWAL_R],
          (fits, loads))
    fits, loads = record(lambda: reel_render.frame_clip_overlay(
        cfg, {"quote_arabic": "ترجمة", "speaker_verified": True, "speaker_name": "اسم", "speaker_role": "صفة",
              "channel_display": "قناة"}))
    check("g267: صندوق الترجمة والشريط السفلي بلا رقعة", aref not in fits + loads
          and fits == [reel_render.TAJAWAL_B], (fits, loads))

    # ── g268: لا تداخل بين صندوقَي حبر سطرين متتاليين بالرقعة ──
    sentence = ("وفي الثالث عشر من أكتوبر 2026، قدّمت ميساء شجاع الدين، الباحثة في مركز صنعاء للدراسات الاستراتيجية، "
                "قراءة لحجم الترسانة الصاروخية")
    for size in (108, 80):
        boxes = []
        pn = reel_render._Pen(cfg, boxes)
        pn.block(sentence, aref, None, pn.white, 860, start=size, minimum=size, max_lines=12, line_factor=factor)
        ok = len(boxes) >= 2 and all(boxes[i][3] < boxes[i + 1][1] for i in range(len(boxes) - 1))
        check(f"g268: لا تداخل أسطر بالحجم {size}", ok, boxes)

    # ── g269: دالة التوقيت ──
    chars, speech, hold, fps, fade = [30, 25, 45], 6.0, 0.35, 30.0, 0.25
    steps = reel_render.reveal_steps(chars, speech, hold, fps, fade)
    t, first = 0.0, [None] * 3
    for alphas, d in steps:
        for k, a in enumerate(alphas):
            if a > 0 and first[k] is None:
                first[k] = t
        t += d
    want = [speech * sum(chars[:k]) / sum(chars) for k in range(3)]
    check("g269: بداية ظهور كل سطر عند نسبة حروفه ±إطار",
          all(f is not None and abs(f - w) <= 1 / fps + 1e-6 for f, w in zip(first, want)), (first, want))
    check("g269: الأسطر كلها ظاهرة كاملة في آخر إطار", all(a == 1.0 for a in steps[-1][0]), steps[-1])
    check("g269: مجموع المدد = الكلام + الصمت", abs(sum(d for _, d in steps) - (speech + hold)) < 1e-6,
          sum(d for _, d in steps))
    seg = "جملة قصيرة نسبيا تكفي لثلاثة أسطر على الأقل في الشاشة هذه وهي طويلة بما يكفي لتقسم " * 2
    n_lines = len(reel_render.narration_lines(cfg, seg))
    st = reel_render.reveal_steps([10] * n_lines, 3.0, 0.35, fps, fade)
    ref = None
    stable = True
    for alphas, _ in st:
        if alphas[0] != 1.0:
            continue
        bx: list = []
        reel_render.frame_narration_reveal(cfg, seg, alphas, bx)
        ref = ref or bx[0]
        stable = stable and tuple(bx[0]) == tuple(ref)
    check("g269: صندوق حبر السطر الأول ثابت بعد اكتمال تلاشيه", ref is not None and stable, ref)

    # ── g270: التقسيم إلى مقاطع ──
    def fits5(text: str) -> bool:
        d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        font = imaging.load_font(aref, 80, None)
        return len(imaging.wrap(d, text, font, 820)) <= 5

    clauses = ["وفي الثالث عشر من أكتوبر 2026 قدّمت ميساء شجاع الدين",
               "الباحثة في مركز صنعاء للدراسات الاستراتيجية",
               "قراءة لحجم الترسانة الصاروخية للجماعة",
               "بحسب ما أعلنته مصادر مطلعة في العاصمة صنعاء",
               "ثم تحدثت عن أثر ذلك في مسار المفاوضات"]
    longs = "، ".join(clauses * 2)
    check("g270: الجملة الطويلة لا تسع 5 أسطر", not fits5(longs))
    segs = reel_render.narration_segments(cfg, longs)
    check("g270: عدة مقاطع يسع كلًّا منها", len(segs) > 1 and all(fits5(s) for s in segs), [len(s) for s in segs])
    check("g270: وصل المقاطع = الجملة", " ".join(segs).split() == longs.split())
    check("g270: التقسيم عند الفاصلة", all(s.endswith("،") for s in segs[:-1]), segs)
    nocomma = " ".join(["كلمة"] * 120)
    segs2 = reel_render.narration_segments(cfg, nocomma)
    check("g270: بلا فاصلة تُقسم عند مسافة", len(segs2) > 1 and all(fits5(s) for s in segs2)
          and " ".join(segs2).split() == nocomma.split(), len(segs2))
    check("g270: الجملة القصيرة مقطع واحد", reel_render.narration_segments(cfg, "جملة قصيرة") == ["جملة قصيرة"])

    # ── g271: أحجام الراوي والوضع القديم ──
    bgA = {"image": Image.new("RGB", (1080, 1920), (10, 10, 10)), "layout": "A"}
    for label, bg in (("بلا خلفية", None), ("التخطيط A", bgA)):
        _, kw = reel_render._narration_pen(cfg, "جملة", [], bg)
        check(f"g271: حجم الراوي {label}", (kw["start"], kw["minimum"], kw["max_lines"]) == (160, 140, 4), kw)
    c2 = copy.deepcopy(cfg)
    c2["reel"]["render"]["reveal"]["mode"] = "typewriter"
    with tempfile.TemporaryDirectory() as td:
        got = reel_render._narration_frames([("جملة قصيرة للتجربة", 2.0)], 0, c2, Path(td), 0.0)
    exp = reel_render.typewriter_steps("جملة قصيرة للتجربة", 2.0 - 0.35, 0.35, 30.0)
    check("g271: mode=typewriter يعطي خطوات typewriter_steps نفسها",
          [round(d, 6) for _, d in got] == [round(d, 6) for _, d in exp], (len(got), len(exp)))
    check("g271: الإعداد الافتراضي lines", cfg.path("reel.render.reveal.mode") == "lines"
          and cfg.path("reel.render.reveal.fade") == 0.25 and cfg.path("reel.render.reveal.rise") == 18)

    # ── g272–g273: الشريط السفلي ──
    def drawn(scene) -> list[tuple]:
        out = []
        o1, o2 = imaging.draw_text, imaging.draw_text_ltr

        def s1(d, xy, text, font, fill, **k):
            out.append((text, fill))
            return o1(d, xy, text, font, fill, **k)

        def s2(d, xy, text, font, fill, **k):
            out.append((text, fill))
            return o2(d, xy, text, font, fill, **k)

        imaging.draw_text, imaging.draw_text_ltr = s1, s2
        try:
            reel_render.frame_clip_overlay(cfg, scene)
        finally:
            imaging.draw_text, imaging.draw_text_ltr = o1, o2
        return out

    gold = imaging.hex_rgb(cfg.path("brand.accent_color"))
    base = {"speaker_verified": True, "speaker_name": "ميساء شجاع الدين",
            "speaker_role": "باحثة في مركز صنعاء للدراسات الاستراتيجية",
            "channel_original": "FRANCE 24 Arabic", "channel_display": "فرانس 24 عربي"}
    d1 = drawn({**base, "speaker_name_latin": "ميساء شجاع الدين"})
    check("g272: لا سطر ذهبي حين اللاتيني عربي", not any(f == gold for _, f in d1), d1)
    # الصفة الطويلة لا تسع العرض عند 26 فتُحذف وتبقى القناة (قرار المتابعة): السطر إما كامل أو القناة وحدها
    check("g272: السطر الثالث بالصفة والقناة اللاتينية ثم العربية (أو القناة وحدها إن لم تسع الصفة)",
          any(t in ("باحثة في مركز صنعاء للدراسات الاستراتيجية · FRANCE 24 Arabic فرانس 24 عربي",
                    "FRANCE 24 Arabic فرانس 24 عربي") for t, _ in d1), d1)
    d2 = drawn({**base, "speaker_name_latin": "Ahmet Kayapaşa"})
    check("g272: السطر الذهبي يظهر للاسم اللاتيني", ("Ahmet Kayapaşa", gold) in d2, d2)
    guest = {"speaker_verified": False, "speaker_name": "", "channel_original": "CNN TÜRK", "channel_display": "سي إن إن ترك"}
    d3 = drawn(guest)
    check("g273: ضيف على CNN TÜRK سي إن إن ترك", any(t == "ضيف على CNN TÜRK سي إن إن ترك" for t, _ in d3), d3)
    d4 = drawn({**guest, "channel_original": "الجزيرة", "channel_display": "الجزيرة"})
    check("g273: اسم القناة العربي وحده ← ضيف على الجزيرة", any(t == "ضيف على الجزيرة" for t, _ in d4), d4)
    check("g273: القناة من النقطة حين تغيب من المشهد",
          reel_render.channel_original_of({"channel_display": "x"}, {"channel": "CNN TÜRK"}) == "CNN TÜRK"
          and reel_render.channel_original_of({"channel_original": "A"}, {"channel": "B"}) == "A")
    check("g273: لا «من قناة» في أي نص مرسوم",
          not any("من قناة" in t for t, _ in d1 + d2 + d3 + d4) and "من قناة" not in cfg.path("reel.texts.guest_label"))

    # ── g274: النسخة وحقل القناة الأصلية ──
    check("g274: render_version == 14", int(cfg.path("reel.render.version")) == 14, cfg.path("reel.render.version"))
    pts = [{"timestamp": 100, "quote_original": "some words here", "video_url": "https://youtu.be/x",
            "channel": "FRANCE 24 Arabic", "quote_arabic": "ترجمة", "speaker": "ميساء", "video_id": "x"}]
    clips = reel_script.valid_clips(pts, [], cfg)
    check("g274: valid_clips تضع channel_original", bool(clips) and clips[0].get("channel_original") == "FRANCE 24 Arabic", clips)

    # ── g275–g277: الشريط السفلي يسع العرض (متابعة #1419) ──
    def band_boxes(scene) -> tuple[list, list]:
        bx: list = []
        reel_render.frame_clip_overlay(cfg, scene, bx)
        band_top = int(cfg.path("reel.render.band.top"))
        return [b for b in bx if b[1] >= band_top], drawn(scene)

    maysaa = {**base, "speaker_name_latin": "Maysaa Shuja al-Deen"}
    bx, dr = band_boxes(maysaa)
    texts = [t for t, _ in dr]
    third = [t for t in texts if "فرانس 24 عربي" in t]
    check("g275: ثلاثة أسطر مرسومة للمتحدث الموثَّق",
          "ميساء شجاع الدين" in texts and "Maysaa Shuja al-Deen" in texts and len(third) == 1, texts)
    check("g275: كل صناديق الشريط بين 0 وW", bool(bx) and all(0 <= b[0] and b[2] <= W for b in bx), bx)
    check("g275: الصفة كاملة أو محذوفة والقناة كاملة", bool(third) and third[0] in (
        "باحثة في مركز صنعاء للدراسات الاستراتيجية · FRANCE 24 Arabic فرانس 24 عربي",
        "FRANCE 24 Arabic فرانس 24 عربي", "فرانس 24 عربي"), third)

    long_role = " ".join(["محلل"] * 20)
    bx2, dr2 = band_boxes({**maysaa, "speaker_role": long_role})
    t2 = [t for t, _ in dr2]
    check("g276: صفة من 20 كلمة ← السطر الثالث بلا صفة والقناة كاملة",
          any(t in ("FRANCE 24 Arabic فرانس 24 عربي", "فرانس 24 عربي") for t in t2)
          and not any("محلل" in t for t in t2), t2)
    check("g276: صناديق الصفة الطويلة بين 0 وW", all(0 <= b[0] and b[2] <= W for b in bx2), bx2)
    long_name = "محمد عبدالرحمن بن علي الأنصاري الحسيني"
    bx3, dr3 = band_boxes({**maysaa, "speaker_name": long_name})
    check("g276: اسم من 6 كلمات طويلة يُصغَّر ويبقى بين الحدّين",
          any(t == long_name for t, _ in dr3) and all(0 <= b[0] and b[2] <= W for b in bx3), bx3)

    lb: list = []
    reel_render.frame_clip_overlay(cfg, {"speaker_verified": True, "speaker_name": "الاسم العربي الكامل للمتحدث",
                                         "speaker_name_latin": "Full Latin Name", "speaker_role": long_role,
                                         "channel_original": "A Very Long Latin Channel Name International Edition",
                                         "channel_display": "قناة طويلة الاسم جدًا للتجربة"}, lb)
    allb = reel_render.layout_boxes(cfg) + lb
    check("g277: لا صندوق في layout_boxes يتجاوز 0 أو W أفقيًا",
          all(b[0] >= 0 and b[2] <= W for b in allb), [b for b in allb if b[0] < 0 or b[2] > W])
    import inspect
    check("g277: layout_boxes تضم مشهد الصفة الطويلة والقناة اللاتينية الطويلة",
          "channel_original" in inspect.getsource(reel_render.layout_boxes))


def test_reel_r5a2_guards() -> None:
    """Issue #1423 (R5a2، g280–g285): الحجم البصري الفعلي للرقعة، والوقف وأسماء الأعلام، وصورة الخلفية (بلا وجه ولا تاريخ
    قديم ولا تخطيط ب)، وسطر الصفة في الشريط السفلي، وترتيب التركيب."""
    import json
    import tempfile
    from pathlib import Path

    import numpy as np
    from PIL import Image, ImageDraw

    from src import imaging, reel_render, tts

    cfg = load_config()
    W = int(cfg.path("reel.render.width"))
    aref = cfg.path("reel.render.fonts.display")

    def guarded(name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 -- الحالة الفاشلة تُسجَّل ولا توقف بقية الحالات
            check(name + ": استثناء", False, repr(exc))

    def ink_h(font_path, size, text="ومن"):
        d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        font = imaging.load_font(font_path, size, None)
        b = d.textbbox((0, 0), imaging._prepare(text), font=font, anchor="la", **imaging._kwargs())
        return b[3] - b[1]

    # ── g280: الحجم البصري ──
    def g280():
        _, kw = reel_render._narration_pen(cfg, "جملة", [], None)
        base_h = ink_h(reel_render.TAJAWAL_XB, 72)
        new_h = ink_h(aref, kw["start"])
        check("g280: ارتفاع حبر «ومن» بالراوي ≥ 1.45× Tajawal-ExtraBold 72", new_h >= 1.45 * base_h, (new_h, base_h))
        check("g280: الراوي start 160 / minimum 140 / 4 أسطر",
              (kw["start"], kw["minimum"], kw["max_lines"]) == (160, 140, 4), kw)
        sizes, line_counts = [], []
        longs = "، ".join(["وفي الثالث عشر من أكتوبر قدّمت الباحثة قراءة لحجم الترسانة الصاروخية للجماعة"] * 4)
        lf = float(cfg.path("reel.render.fonts.display_line_factor"))
        for seg in reel_render.narration_segments(cfg, longs):
            lines = reel_render.narration_lines(cfg, seg)
            p, k = reel_render._narration_pen(cfg, seg, [], None)
            fnt, _, _ = reel_render._fit(p.d, seg, aref, p.max_w, k["max_lines"], k["start"], k["minimum"], None, lf)
            sizes.append(fnt.size)
            line_counts.append(len(lines))
        check("g280: كل مقطع مرسوم ≥ 140 وكل مقطع ≤ 4 أسطر",
              bool(sizes) and min(sizes) >= 140 and max(line_counts) <= 4, (sizes, line_counts))
        scale = float(cfg.path("reel.render.fonts.display_scale", 0))
        check("g280: display_scale = 1.45", scale == 1.45, scale)
        rec: list = []
        o_fit, o_pick = reel_render._fit, reel_render.pick_font

        def fit_rec(d, t, fp, mw, ml, st, mn, wt, lf_):
            rec.append(("fit", st, mn))
            return o_fit(d, t, fp, mw, ml, st, mn, wt, lf_)

        def pick_rec(t, fp, sz, wt=None):
            rec.append(("pick", sz, 0))
            return o_pick(t, fp, sz, wt)

        reel_render._fit, reel_render.pick_font = fit_rec, pick_rec
        try:
            for name, fn, want in (
                    ("العنوان", lambda b: reel_render.frame_title(cfg, "عنوان", "2099/01/01", b), ("fit", 139, 75)),
                    ("السؤال", lambda b: reel_render.frame_question(cfg, "هل تتجه المنطقة إلى تسوية؟", b), ("fit", 110, 64)),
                    ("تابعوا الموجز", lambda b: reel_render.frame_outro(cfg, "الجزيرة", b), ("pick", 162, 0))):
                rec.clear()
                fn([])
                check(f"g280: {name} بحجم ≥ display_scale × القديم", want in rec, rec)
        finally:
            reel_render._fit, reel_render.pick_font = o_fit, o_pick
        check("g280: كل صناديق layout_boxes داخل العرض الآمن أفقيًا",
              all(b[0] >= 0 and b[2] <= W for b in reel_render.layout_boxes(cfg)))
    guarded("g280", g280)

    # ── g281: الوقف ──
    def g281():
        out = tts.apply_waqf("تُعلنُ الحكومةُ الخطةَ،")
        check("g281: «الخطةَ،» ← «الخطهْ،» والباقي كما هو", out == "تُعلنُ الحكومةُ الخطهْ،", out)
        o2 = tts.apply_waqf("قال الوزير")
        check("g281: كلمة أخيرة بلا تشكيل تأخذ سكونًا", o2 == "قال الوزيرْ", o2)
        a, b = tts.apply_waqf("قال الوزيرُ؛ ثم"), tts.apply_waqf("قال الوزيرُ, ثم")
        check("g281: «؛» و«,» موضعا وقف", a == "قال الوزيرْ؛ ثمْ" and b == "قال الوزيرْ, ثمْ", (a, b))
        o3 = tts.apply_waqf("وصلت رسالةٌ.")
        check("g281: رسالةٌ ← رسالهْ", o3 == "وصلت رسالهْ.", o3)
        sent = "تُعلنُ الحكومةُ الخطةَ."
        got: list = []
        tmp = Path(tempfile.mkdtemp())
        try:
            def synth(t, v):
                got.append(t)
                return {"ok": True, "audio": b"x"}
            deps = reel_render.Deps(synthesize=synth, diacritize=lambda t: (sent, None),
                                    run=lambda cmd: None, probe=lambda p: 1.0)
            _, parts = reel_render._speech("تعلن الحكومة الخطة.", "v", cfg, deps, tmp, "t")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        check("g281: الصوت بـ«الخطهْ» والمعروض «الخطة»",
              got == ["تُعلنُ الحكومةُ الخطهْ."] and parts[0][0] == "تعلن الحكومة الخطة.", (got, parts))
    guarded("g281", g281)

    # ── g282: الأعلام ──
    def g282():
        text = "قالت قناةُ سِي إِنْ إِنْ تُرْكٍ إنّ مطارَ الملكِ خالدٍ استُهدفَ."
        nouns = [{"text": "سي إن إن ترك", "foreign": True}, {"text": "مطار الملك خالد", "foreign": False}]
        out = tts.apply_proper_nouns(text, nouns)
        check("g282: الأجنبي: وقف على كل كلماته", "سِيْ إِنْ إِنْ تُرْكْ" in out, out)
        check("g282: العربي: وقف على الأخيرة وحركات ما قبلها تبقى", "مطارَ الملكِ خالدْ" in out, out)
        check("g282: النص عدا الحركات لم يتغير", tts.strip_tashkeel(out) == tts.strip_tashkeel(text), out)
        same = tts.apply_proper_nouns(text, [{"text": "اسم غير موجود", "foreign": True}])
        check("g282: عَلَم غير موجود يُتجاهل بلا استثناء", same == text, same)
    guarded("g282", g282)

    # ── g283: الخلفية ──
    def g283():
        astro = Image.open("tests/fixtures/faces/astronaut.jpg").convert("RGB")
        xs = np.linspace(20, 235, 1400, dtype=np.uint8)
        grad = Image.fromarray(np.stack([np.tile(xs, (800, 1)), np.tile(xs[::-1], (800, 1)),
                                         np.full((800, 1400), 140, np.uint8)], axis=2))
        faced = {"https://n/face.jpg": astro}

        def pv(urls):
            return {"news": lambda *a: [{"url": u, "publisher": "R"} for u in urls],
                    "web": lambda *a, **k: [], "free": lambda *a: [],
                    "download": lambda u: faced.get(u, grad)}
        base = {"id": "r5a2000g283", "title": "عنوان", "event": "حدث"}
        r = reel_render.pick_background(base, cfg, pv(["https://n/face.jpg", "https://n/ok.jpg"]), draft_date="2026-10-14")
        check("g283: وجه كبير ثم بلا وجه ← الثاني", r["url"] == "https://n/ok.jpg", r)
        r = reel_render.pick_background(base, cfg, pv(["https://n/2021/10/a.jpg"]), draft_date="2026-10-14")
        check("g283: /2021/10/ لمسودة 2026-10-14 ← يُرفض", r["kind"] == "none", r)
        r = reel_render.pick_background(base, cfg, pv(["https://n/2026/09/a.jpg"]), draft_date="2026-10-14")
        check("g283: /2026/09/ ← يُقبل", r["url"] == "https://n/2026/09/a.jpg", r)
        r = reel_render.pick_background(base, cfg, pv(["https://n/2024/a.jpg"]), draft_date="2026-10-14")
        check("g283: /2024/ وحدها لسنة 2026 ← يُرفض", r["kind"] == "none", r)
        r = reel_render.pick_background(dict(base, manual_image="https://n/face.jpg"), cfg, pv([]), draft_date="2026-10-14")
        check("g283: manual لا يُرفض", r["kind"] == "manual", r)
        check("g283: prepare_background لا ينتج B أبدًا",
              reel_render.prepare_background(cfg, astro)["layout"] == "A"
              and reel_render.prepare_background(cfg, grad)["layout"] == "A")
        path = store.save_draft({"id": "r5a2000g283b", "origin": "analysis", "format": "reel", "title": "ريل",
                                 "status": "approved_script", "render_status": "queued", "script": {"scenes": []},
                                 "reel_bg": {"url": "https://n/face.jpg", "kind": "news_photo", "publisher": "R"}})
        draft = json.loads(path.read_text(encoding="utf-8"))
        deps = reel_render.Deps(bg_image=lambda u: faced.get(u, grad), bg_providers=pv(["https://n/ok.jpg"]))
        bg, saved = reel_render._resolve_background(path, draft, cfg, deps, [])
        now = json.loads(path.read_text(encoding="utf-8")).get("reel_bg") or {}
        check("g283: reel_bg محفوظ بوجه ← يُستبدل ويُحفظ الجديد",
              saved.get("url") == "https://n/ok.jpg" and now.get("url") == "https://n/ok.jpg", (saved, now))
        check("g283: التخطيط A", bg is not None and bg["layout"] == "A", bg and bg["layout"])
        mpath = store.save_draft({"id": "r5a2000g283c", "origin": "analysis", "format": "reel", "title": "ريل",
                                  "status": "approved_script", "render_status": "queued", "script": {"scenes": []},
                                  "manual_image": "https://n/face.jpg"})
        mdraft = json.loads(mpath.read_text(encoding="utf-8"))
        bg2, _ = reel_render._resolve_background(mpath, mdraft, cfg, deps, [])
        check("g283: manual بوجه ← يُقبل بالتخطيط A",
              bg2 is not None and bg2["layout"] == "A" and bg2["used"]["kind"] == "manual", bg2 and bg2["layout"])
        b = cfg.path("reel.render.background") or {}
        check("g283: مفاتيح التخطيط B محذوفة من config",
              not any(k in b for k in ("shade_b", "box_alpha", "box_top", "box_bottom", "gold_px", "pad",
                                       "text_start", "text_min", "text_lines")), list(b))
    guarded("g283", g283)

    # ── g284: سطر الصفة ──
    def g284():
        scene = {"speaker_verified": True, "speaker_name": "ميساء شجاع الدين", "speaker_name_latin": "ميساء شجاع الدين",
                 "speaker_role": "باحثة في مركز صنعاء للدراسات الاستراتيجية",
                 "channel_original": "FRANCE 24 Arabic", "channel_display": "فرانس 24 عربي"}
        drawn: list = []
        o1, o2 = imaging.draw_text, imaging.draw_text_ltr

        def d1(d, xy, t, f, fill, **k):
            drawn.append(t)
            return o1(d, xy, t, f, fill, **k)

        def d2(d, xy, t, f, fill, **k):
            drawn.append(t)
            return o2(d, xy, t, f, fill, **k)
        imaging.draw_text, imaging.draw_text_ltr = d1, d2
        bx: list = []
        try:
            reel_render.frame_clip_overlay(cfg, scene, bx)
        finally:
            imaging.draw_text, imaging.draw_text_ltr = o1, o2
        role, chan = scene["speaker_role"], "FRANCE 24 Arabic فرانس 24 عربي"
        check("g284: سطر الصفة كاملًا وسطر القناة تحته",
              role in drawn and chan in drawn and drawn.index(chan) > drawn.index(role)
              and not any(" · " in t for t in drawn), drawn)
        band = cfg.path("reel.render.band")
        top, limit = int(band["top"]), int(band["top"]) + int(band["height"])
        x0 = int(cfg.path("reel.render.safe.right_col_width"))
        x1 = W - x0
        inside = [b for b in bx if b[1] >= top]
        check("g284: كل الصناديق بين x0 وx1 وفوق الحد السفلي",
              bool(inside) and all(b[0] >= x0 and b[2] <= x1 and b[3] <= limit for b in inside), inside)
    guarded("g284", g284)

    # ── g285: ترتيب التركيب والنسخة ──
    def g285():
        def fresh():
            shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
            DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

        def mk(did, status, ver, at):
            return store.save_draft({"id": did, "origin": "analysis", "format": "reel", "title": "ريل",
                                     "status": "approved_script", "render_status": status, "render_version": ver,
                                     "approved_script_at": at, "script": {"scenes": []}})
        fresh()
        mk("r5a2000g285a", "queued", 10, "2099-01-01T00:00:00+00:00")
        mk("r5a2000g285b", "rendered", 1, "2099-01-02T00:00:00+00:00")
        order = [p.stem for p, _ in reel_render.queued_reels(cfg)]
        check("g285: queued أمس قبل stale اليوم", order == ["r5a2000g285a", "r5a2000g285b"], order)
        fresh()
        mk("r5a2000g285c", "queued", 10, "2099-01-01T00:00:00+00:00")
        mk("r5a2000g285d", "rendered", 1, "2099-01-05T00:00:00+00:00")
        mk("r5a2000g285e", "rendered", 1, "2099-01-09T00:00:00+00:00")
        order = [p.stem for p, _ in reel_render.queued_reels(cfg)]
        check("g285: المنتظر أولًا ثم المعاد تركيبه الأحدث اعتمادًا أولًا",
              order == ["r5a2000g285c", "r5a2000g285e", "r5a2000g285d"], order)
        fresh()
        mk("r5a2000g285f", "queued", 10, "2099-01-01T00:00:00+00:00")
        mk("r5a2000g285g", "queued", 10, "2099-01-03T00:00:00+00:00")
        mk("r5a2000g285h", "rendered", 1, "2099-01-09T00:00:00+00:00")
        order = [p.stem for p, _ in reel_render.queued_reels(cfg)]
        check("g285: داخل المنتظر الأحدث اعتمادًا أولًا والمعاد تركيبه بعده",
              order == ["r5a2000g285g", "r5a2000g285f", "r5a2000g285h"], order)
        fresh()
        check("g285: render_version == 14", int(cfg.path("reel.render.version")) == 14, cfg.path("reel.render.version"))
        check("g285: max_per_run == 1", int(cfg.path("reel.render.max_per_run")) == 1)
    guarded("g285", g285)

    # ── g286: موضع السؤال تحت الدائرة الذهبية وفوق «شاركونا» ──
    def g286():
        circle_bottom = 520 + 120
        long_q = "كيف تقرأون مسار التصعيد بعد استهداف مطار الملك خالد الدولي وما الذي ينتظر المنطقة؟"
        boxes: list = []
        reel_render.frame_question(cfg, long_q, boxes)
        q, share = boxes[:-1], boxes[-1]
        top, bottom = min(b[1] for b in q), max(b[3] for b in q)
        check("g286: أعلى حبر السؤال الطويل ≥ 690 (أسفل الدائرة + 50)", top >= circle_bottom + 50, (top, circle_bottom))
        check("g286: أسفل حبر السؤال ≤ أعلى حبر «شاركونا» − 30", bottom <= share[1] - 30, (bottom, share))
        boxes2: list = []
        reel_render.frame_question(cfg, "هل تتجه المنطقة إلى تسوية؟", boxes2)
        q2 = boxes2[:-1]
        h2 = max(b[3] for b in q2) - min(b[1] for b in q2)
        check("g286: سؤال قصير من 4 كلمات بسطر واحد وأعلى حبره ≥ 690",
              len(q2) == 1 and min(b[1] for b in q2) >= circle_bottom + 50, q2)
        full_h = ink_h(aref, reel_render.scaled(cfg, 76), "هل تتجه المنطقة إلى تسوية؟")
        check("g286: السؤال القصير بالحجم الكامل (ارتفاع حبره = ارتفاع الحجم الكامل)",
              abs(h2 - full_h) <= 2, (h2, full_h))
    guarded("g286", g286)


def test_reel_speaker_r5b_guards() -> None:
    """Issue #1427 (R5b، g287–g294): اختيار الوجه المتكلم من حركة الفم حين يظهر أكثر من وجه، وقراءة اسم المتحدث وصفته من
    شريط القناة بـHaiku (ثلاث لقطات، لقطتان متفقتان)، والمذيع يُعرض بقناته وحدها. لا نداء شبكة في أي حالة."""
    import json
    import tempfile
    from pathlib import Path

    import numpy as np

    from src import imaging, llm, reel_render, reel_script

    cfg = load_config()
    SW, SH = 640, 360

    def guarded(name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 -- الحالة الفاشلة تُسجَّل ولا توقف بقية الحالات
            check(name + ": استثناء", False, repr(exc))

    def synth(n, faces):
        """إطارات رمادية 640×360 وصناديق وجوه (x, 100, 100, 120). كل وجه: x، النمط (mouth فم وحده، head فم وعينان معًا،
        still ثابت)، lo/hi شدّة التبديل، وframes الإطارات التي يظهر فيها (الافتراضي كلها)."""
        frames, boxes = [], []
        for k in range(n):
            im = np.full((SH, SW), 100, np.uint8)
            bx = []
            for f in faces:
                if k not in f.get("frames", range(n)):
                    continue
                x = f["x"]
                bx.append((x, 100, 100, 120))
                val = f.get("hi", 200) if k % 2 else f.get("lo", 60)
                if f["mode"] in ("mouth", "head"):
                    im[180:220, x + 20:x + 80] = val
                if f["mode"] == "head":
                    im[124:154, x:x + 100] = val
            frames.append(im)
            boxes.append(bx)
        return frames, boxes

    def crop_of(frames, boxes, faces_fallback=None):
        deps = reel_render.Deps(face_tracks=lambda f, c: (SW, SH, frames, boxes),
                                faces=lambda f, fr: (SW, SH, faces_fallback or []))
        return reel_render._crop_for({"file": "x.mp4"}, cfg, deps)

    # ── g287: الفم المتحرك يحدد المتكلم ──
    def g287():
        fr, bx = synth(20, [{"x": 120, "mode": "still"}, {"x": 420, "mode": "mouth"}])
        res = reel_render.speaker_track(fr, bx, cfg)
        check("g287: المتكلم الأيمن بمسارين", res.get("source") == "speaker" and res.get("tracks") == 2
              and abs(res["center"] - 470) < 1, res)
        c = crop_of(fr, bx)
        w = int(SH * 9 / 16)
        check("g287: النافذة تتوسّط مركزه وsource == speaker",
              c["source"] == "speaker" and c["x"] == int(470 - w // 2) and c.get("tracks") == 2
              and c.get("speaker_score", 0) > 100, c)
        fr, bx = synth(20, [{"x": 120, "mode": "mouth"}, {"x": 420, "mode": "still"}])
        c = crop_of(fr, bx)
        check("g287: بعكس الحركة ← الأيسر", c["source"] == "speaker" and c["x"] == int(170 - w // 2), c)
    guarded("g287", g287)

    # ── g288: تعادل الحركة ← أكبر وجه، ووجه واحد ← هو ──
    def g288():
        fr, bx = synth(20, [{"x": 120, "mode": "mouth"}, {"x": 420, "mode": "mouth"}])
        check("g288: النسبة < 1.25 ← غير محسوم", reel_render.speaker_track(fr, bx, cfg).get("source") == "face")
        c = crop_of(fr, bx, faces_fallback=[470])
        w = int(SH * 9 / 16)
        check("g288: السلوك القديم أكبر وجه وsource == face", c["source"] == "face" and c["x"] == int(470 - w // 2), c)
        fr, bx = synth(20, [{"x": 120, "mode": "still"}, {"x": 420, "mode": "still"}])
        check("g288: صفر مقابل صفر ← غير محسوم", reel_render.speaker_track(fr, bx, cfg).get("source") == "face")
        fr, bx = synth(20, [{"x": 420, "mode": "still"}])
        res = reel_render.speaker_track(fr, bx, cfg)
        check("g288: وجه واحد ← هو بلا مقارنة", res.get("source") == "speaker" and res.get("tracks") == 1, res)
    guarded("g288", g288)

    # ── g289: حركة الرأس لا تُحسب كلامًا، والمسار العابر يُهمل ──
    def g289():
        fr, bx = synth(20, [{"x": 120, "mode": "head"}, {"x": 420, "mode": "mouth"}])
        res = reel_render.speaker_track(fr, bx, cfg)
        check("g289: حركة الرأس كاملة في الأيسر ← الأيمن", res.get("source") == "speaker" and abs(res["center"] - 470) < 1, res)
        fr, bx = synth(20, [{"x": 120, "mode": "still"}, {"x": 420, "mode": "mouth", "lo": 80, "hi": 160},
                            {"x": 270, "mode": "mouth", "frames": range(6)}])
        res = reel_render.speaker_track(fr, bx, cfg)
        check("g289: مسار 30% من الإطارات مُهمل (مساران لا ثلاثة) والأيمن المتكلم",
              res.get("tracks") == 2 and res.get("source") == "speaker" and abs(res["center"] - 470) < 1, res)
    guarded("g289", g289)

    # ── g295–g296: حركة رأس بالإزاحة (وجه يتبعه صندوقه) لا تُحسب كلامًا، حتى قرب حافة اللقطة (Issue #1427 متابعة) ──
    def shifted_head(base_y, dy_of):
        """وجه أيسر = رقعة نسيج عشوائي ثابت المحتوى (فمها قوي التباين وعيناها شبه ثابتتين) تُزاح بين اللقطات وصندوقها يتبعها،
        ووجه أيمن ثابت الموضع يتبدّل فمه وحده بفرق ضعيف؛ بلا تعويض الإزاحة تتفوق درجة الأيسر خطأً."""
        rng = np.random.default_rng(7)
        tex = np.clip(100 + rng.integers(-1, 2, (120, 100)), 0, 255)
        tex[24:54, :] = 100 + rng.integers(-1, 2, (30, 100))
        tex[80:120, 20:80] = 100 + rng.integers(-100, 101, (40, 60))
        tex = tex.astype(np.uint8)
        frames, boxes = [], []
        for k in range(20):
            im = np.full((SH, SW), 100, np.uint8)
            x, y = 120 + ((k * 11) % 31) - 15, base_y + dy_of(k)
            im[y:y + 120, x:x + 100] = tex
            im[180:220, 440:500] = 105 if k % 2 else 95
            frames.append(im)
            # الكاشف الحقيقي لا يتبع الوجه بدقة البكسل: خطأ ±2 في الصندوق يفصله عن الرقعة
            ex, ey = (k * 5) % 5 - 2, (k * 3) % 5 - 2
            boxes.append([(x + ex, y + ey, 100, 120), (420, 100, 100, 120)])
        return frames, boxes

    def g295():
        fr, bx = shifted_head(100, lambda k: ((k * 7) % 31) - 15)
        res = reel_render.speaker_track(fr, bx, cfg)
        check("g295: حركة رأس بالإزاحة ±15 ← المتكلم الأيمن", res.get("source") == "speaker" and abs(res["center"] - 470) < 1, res)
    guarded("g295", g295)

    def g296():
        fr, bx = shifted_head(232, lambda k: -((k * 7) % 16))
        check("g296: أسفل صندوق الأيسر على 8 بكسل من الحافة", 350 <= max(b[0][1] + 120 for b in bx) <= 354, bx[0])
        res = reel_render.speaker_track(fr, bx, cfg)
        check("g296: قرب الحافة السفلية ← الأيمن بلا استثناء", res.get("source") == "speaker" and abs(res["center"] - 470) < 1, res)
    guarded("g296", g296)

    # ── قالب تركيب ريل بمشهدَي مقطع لـg290–g293 ──
    D = "2099-12-08"
    quote = "alpha beta gamma delta epsilon zeta eta theta"
    points = [{"video_id": "v1", "statement": "s", "quote_original": quote, "quote_arabic": "ترجمة", "speaker": "متحدث",
               "channel": "CNN TÜRK", "video_url": "https://youtube.com/watch?v=v1", "timestamp": 10},
              {"video_id": "v2", "statement": "s2", "quote_original": quote, "quote_arabic": "ترجمة٢", "speaker": "متحدث٢",
               "channel": "CNN TÜRK", "video_url": "https://youtube.com/watch?v=v2", "timestamp": 10}]
    clip = {"kind": "clip", "start": 9, "end": 20, "speaker_name": "", "speaker_role": "", "speaker_verified": False,
            "speaker_name_latin": "", "channel_display": "سي إن إن ترك", "channel_original": "CNN TÜRK",
            "quote_arabic": "ترجمة", "language": "tr"}
    transcripts = {v: "[00:10] alpha beta gamma delta\n[00:14] epsilon zeta eta theta\n[00:18] tail line" for v in ("v1", "v2")}

    def scenes_for(**over):
        return [dict(clip, kind="cold_open_clip", video_url=points[0]["video_url"],
                     point_id=reel_script.point_key_id(points[0]), **over),
                {"kind": "narration", "text": "جملة."},
                dict(clip, video_url=points[1]["video_url"], point_id=reel_script.point_key_id(points[1]), **over),
                {"kind": "question", "text": "هل؟"}, {"kind": "outro"}]

    def rendered(did, scenes, read_chyron, tmp):
        comments = []

        def run(cmd):
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(b"x")

        def download(video_id, start, end, height, out_path):
            Path(out_path).write_bytes(b"clip")
            return {"tier": "a", "bytes": 4, "failures": []}
        deps = reel_render.Deps(
            fetch_transcript=lambda vid: transcripts.get(vid), download_clip=download,
            synthesize=lambda t, voice: {"ok": True, "audio": b"mp3", "chars": len(t)},
            diacritize=lambda t: (t, None), run=run, probe=lambda p: 41.0 if "reels" in Path(p).parts else 2.0,
            load_points=lambda date: points, comment=lambda i, t: comments.append(t),
            faces=lambda f, fr: (SW, SH, []), frames=lambda p, fr: [np.full((SH, SW), 100, np.uint8)] * len(fr),
            streams=lambda p: {"video", "audio"}, read_chyron=read_chyron)
        d0 = {"id": did, "origin": "analysis", "format": "reel", "status": "approved_script", "render_status": "queued",
              "topic_id": "t1", "topic_date": D, "title": "ريل", "script_status": "ready", "review_issue": 4243,
              "script": {"narrator": "female", "title": "عنوان", "question": "هل؟", "scenes": scenes}}
        path = store.save_draft(d0)
        drawn: list = []
        o1, o2 = imaging.draw_text, imaging.draw_text_ltr

        def d1(d, xy, t, f, fill, **k):
            drawn.append(t)
            return o1(d, xy, t, f, fill, **k)

        def d2(d, xy, t, f, fill, **k):
            drawn.append(t)
            return o2(d, xy, t, f, fill, **k)
        imaging.draw_text, imaging.draw_text_ltr = d1, d2
        try:
            reel_render.render_draft(path, d0, cfg, deps, reels_dir=tmp / "reels", workdir=tmp / "work")
        finally:
            imaging.draw_text, imaging.draw_text_ltr = o1, o2
        return json.loads(path.read_text(encoding="utf-8")), drawn, comments

    def name_frame(name="Ahmet Kayapınar", ar="أحمد كايابينار", role="محلل سياسي", pres=False):
        return {"has_caption": bool(name), "name_original": name, "name_arabic": ar, "role_original": "Siyaset analisti",
                "role_arabic": role, "is_presenter": pres}

    empty = {"has_caption": False, "name_original": "", "name_arabic": "", "role_original": "", "role_arabic": "",
             "is_presenter": False}
    guest = "ضيف على"

    tmp = Path(tempfile.mkdtemp())
    try:
        # ── g290: اسم متطابق في لقطتين ← موثَّق من الشريط ──
        def g290():
            s, drawn, comments = rendered("r5b000g290a1", scenes_for(),
                                          lambda f, c: [name_frame(), name_frame(), empty], tmp)
            check("g290: التركيب نجح", s.get("render_status") == "rendered", s.get("render_error"))
            want = ["أحمد كايابينار", "Ahmet Kayapınar", "محلل سياسي · CNN TÜRK سي إن إن ترك"]
            pos = [drawn.index(t) if t in drawn else -1 for t in want]
            check("g290: الشريط: الاسم العربي ثم اللاتيني ثم «الصفة · القناة»",
                  all(p >= 0 for p in pos) and pos == sorted(pos), (pos, drawn))
            check("g290: بلا «ضيف على»", not any(str(t).startswith(guest) for t in drawn), drawn)
            sp = (s.get("render_speakers") or {}).get("0") or {}
            check("g290: render_speakers محفوظ",
                  sp.get("name_original") == "Ahmet Kayapınar" and sp.get("name_arabic") == "أحمد كايابينار"
                  and sp.get("role_arabic") == "محلل سياسي" and sp.get("is_presenter") is False
                  and sp.get("frames_agreeing") == 2 and sp.get("accepted") is True, s.get("render_speakers"))
            line = "👤 من شريط القناة: أحمد كايابينار (Ahmet Kayapınar) — محلل سياسي"
            check("g290: سطر 👤 في التعليق", any(line in c for c in comments), comments)
        guarded("g290", g290)

        # ── g291: لقطة واحدة أو اسمان مختلفان ← لا قبول ──
        def g291():
            for tag, res in (("لقطة واحدة", [name_frame(), empty, empty]),
                             ("اسمان", [name_frame(), name_frame("Mehmet Yilmaz", "محمد يلماز"), empty])):
                s, drawn, comments = rendered("r5b000g291" + ("a" if tag == "لقطة واحدة" else "b"), scenes_for(),
                                              lambda f, c, r=res: r, tmp)
                sp = (s.get("render_speakers") or {}).get("0") or {}
                check(f"g291: {tag} ← لا قبول و«ضيف على»",
                      s.get("render_status") == "rendered" and sp.get("accepted") is False
                      and any(str(t).startswith(guest) for t in drawn) and "أحمد كايابينار" not in drawn
                      and not any("من شريط القناة" in c for c in comments), (sp, drawn))
        guarded("g291", g291)

        # ── g292: مذيع القناة ← القناة وحدها ──
        def g292():
            s, drawn, _ = rendered("r5b000g292a1", scenes_for(),
                                   lambda f, c: [empty, dict(empty, is_presenter=True), dict(empty, is_presenter=True)], tmp)
            check("g292: الشريط «CNN TÜRK سي إن إن ترك» وحده بلا «ضيف على»",
                  s.get("render_status") == "rendered" and "CNN TÜRK سي إن إن ترك" in drawn
                  and not any(str(t).startswith(guest) for t in drawn), drawn)
            sp = (s.get("render_speakers") or {}).get("0") or {}
            check("g292: render_speakers.is_presenter صحيحة وغير مقبول", sp.get("is_presenter") is True
                  and sp.get("accepted") is False, sp)
            cl = dict(clip, channel_display="الجزيرة", channel_original="", speaker_presenter=True)
            d: list = []
            o1 = imaging.draw_text
            imaging.draw_text = lambda dr, xy, t, f, fill, **k: (d.append(t), o1(dr, xy, t, f, fill, **k))[1]
            try:
                reel_render.frame_clip_overlay(cfg, cl, [])
            finally:
                imaging.draw_text = o1
            check("g292: «الجزيرة» وحدها", "الجزيرة" in d and not any(str(t).startswith(guest) for t in d), d)
        guarded("g292", g292)

        # ── g293: الموثَّق لا يُرسل، والعطل لا يُسقط ──
        def g293():
            n = {"c": 0}

            def counting(f, c):
                n["c"] += 1
                return [name_frame()] * 3
            s, drawn, _ = rendered("r5b000g293a1",
                                   scenes_for(speaker_name="فلان الفلاني", speaker_verified=True,
                                              speaker_verified_from="description"), counting, tmp)
            check("g293: موثَّق من الوصف ← لا نداء", n["c"] == 0 and s.get("render_status") == "rendered"
                  and "فلان الفلاني" in drawn and not s.get("render_speakers"), (n, s.get("render_speakers")))

            def boom(f, c):
                raise RuntimeError("api down")
            s, drawn, _ = rendered("r5b000g293b1", scenes_for(), boom, tmp)
            check("g293: استثناء النداء ← «ضيف على» والتركيب ينجح",
                  s.get("render_status") == "rendered" and any(str(t).startswith(guest) for t in drawn),
                  (s.get("render_status"), s.get("render_error")))
            s, drawn, _ = rendered("r5b000g293c1", scenes_for(), lambda f, c: None, tmp)
            check("g293: None ← «ضيف على»", s.get("render_status") == "rendered"
                  and any(str(t).startswith(guest) for t in drawn))
        guarded("g293", g293)

        # ── g294: النداء الحقيقي بعميل مزيَّف ──
        def g294():
            seen: dict = {}

            class Block:
                type = "tool_use"
                name = "read_lower_third"
                input = {"frames": [name_frame(), name_frame(), empty]}

            class Resp:
                stop_reason = "tool_use"
                content = [Block()]

            class Msgs:
                def create(self, **kw):
                    seen.update(kw)
                    return Resp()

            class Client:
                messages = Msgs()
            out = reel_render.call_chyron_model([b"\xff\xd8a", b"\xff\xd8b", b"\xff\xd8c"], cfg, Client())
            blocks = [b for m in seen.get("messages", []) for b in (m["content"] if isinstance(m["content"], list) else [])
                      if b.get("type") == "image"]
            check("g294: النموذج haiku المحلول", seen.get("model") == llm.resolve("haiku"), seen.get("model"))
            check("g294: ثلاث كتل image base64 بصيغة jpeg",
                  len(blocks) == 3 and all(b["source"]["type"] == "base64" and b["source"]["media_type"] == "image/jpeg"
                                           for b in blocks), blocks)
            tools = seen.get("tools") or []
            tc = seen.get("tool_choice") or {}
            check("g294: أداة إجبارية read_lower_third", [t["name"] for t in tools] == ["read_lower_third"]
                  and tc.get("type") == "tool" and tc.get("name") == "read_lower_third", (tools and tools[0]["name"], tc))
            check("g294: الناتج ثلاثة إطارات", isinstance(out, list) and len(out) == 3
                  and out[0]["name_original"] == "Ahmet Kayapınar", out)
            check("g294: render_version == 14", int(cfg.path("reel.render.version")) == 14, cfg.path("reel.render.version"))
            check("g294: إعداد chyron", (cfg.path("reel.render.chyron") or {}).get("frames") == [0.25, 0.5, 0.75]
                  and cfg.path("reel.render.chyron.max_width") == 1280, cfg.path("reel.render.chyron"))
        guarded("g294", g294)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reel_hook_r5c1_guards() -> None:
    """Issue #1429 (R5c1، g298–g304): الهوك (عنوان السيناريو يقرؤه الراوي فوق خلفية متحركة) يُنقل إلى أول الريل بدل بطاقة العنوان،
    والشعار الكبير الذي ينتقل إلى الزاوية، واختيار المتكلم الأعلى حركة بلا شرط margin، ومركز «؟» في دائرة السؤال. لا شبكة."""
    import json
    import re
    import tempfile
    from pathlib import Path

    import numpy as np
    from PIL import Image

    from src import imaging, reel_render, reel_script, tts

    cfg = load_config()
    SW, SH = 640, 360

    def guarded(name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 -- الحالة الفاشلة تُسجَّل ولا توقف بقية الحالات
            check(name + ": استثناء", False, repr(exc))

    D = "2099-12-08"
    quote = "alpha beta gamma delta epsilon zeta eta theta"
    points = [{"video_id": "v1", "statement": "s", "quote_original": quote, "quote_arabic": "ترجمة", "speaker": "متحدث",
               "channel": "CNN TÜRK", "video_url": "https://youtube.com/watch?v=v1", "timestamp": 10},
              {"video_id": "v2", "statement": "s2", "quote_original": quote, "quote_arabic": "ترجمة٢", "speaker": "متحدث٢",
               "channel": "CNN TÜRK", "video_url": "https://youtube.com/watch?v=v2", "timestamp": 10}]
    clip = {"kind": "clip", "start": 9, "end": 20, "speaker_name": "", "speaker_role": "", "speaker_verified": False,
            "speaker_name_latin": "", "channel_display": "سي إن إن ترك", "channel_original": "CNN TÜRK",
            "quote_arabic": "ترجمة", "language": "tr"}
    transcripts = {v: "[00:10] alpha beta gamma delta\n[00:14] epsilon zeta eta theta\n[00:18] tail line" for v in ("v1", "v2")}
    title = "عنوان الهوك"
    xs = np.linspace(20, 235, 1400, dtype=np.uint8)
    grad = Image.fromarray(np.stack([np.tile(xs, (800, 1)), np.tile(xs[::-1], (800, 1)),
                                     np.full((800, 1400), 140, np.uint8)], axis=2))
    empty_pv = {"news": lambda *a: [], "web": lambda *a, **k: [], "free": lambda *a: []}

    def scenes():
        return [dict(clip, kind="cold_open_clip", video_url=points[0]["video_url"],
                     point_id=reel_script.point_key_id(points[0])),
                {"kind": "title_card", "text": title},
                {"kind": "narration", "text": "جملة."},
                dict(clip, video_url=points[1]["video_url"], point_id=reel_script.point_key_id(points[1])),
                {"kind": "question", "text": "هل؟"}, {"kind": "outro"}]

    def render(did, tmp, *, hook_audio=2.0, extra=None, with_bg=False, hook_dl_fail=False):
        cmds, comments, synths, downloads, joined = [], [], [], [], {}
        titled: list = []

        def run(cmd):
            cmds.append([str(c) for c in cmd])
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(b"x")

        def download(video_id, start, end, height, out_path):
            downloads.append((video_id, start, end))
            if hook_dl_fail and video_id == "hv1":
                raise RuntimeError("down")
            Path(out_path).write_bytes(b"clip")
            return {"tier": "a", "bytes": 4, "failures": []}

        def probe(p):
            name = Path(p).name
            if "reels" in Path(p).parts:
                return 41.0
            return hook_audio if name.startswith("s01_") else 2.0
        deps = reel_render.Deps(
            fetch_transcript=lambda vid: transcripts.get(vid), download_clip=download,
            synthesize=lambda t, voice: (synths.append(t), {"ok": True, "audio": b"mp3", "chars": len(t)})[1],
            diacritize=lambda t: (t, None), run=run, probe=probe, sleep=lambda s: None,
            load_points=lambda date: points, comment=lambda i, t: comments.append(t),
            faces=lambda f, fr: (SW, SH, []), frames=lambda p, fr: [np.full((SH, SW), 100, np.uint8)] * len(fr),
            streams=lambda p: {"video", "audio"}, read_chyron=lambda f, c: None,
            bg_image=(lambda u: grad) if with_bg else (lambda u: None), bg_providers=empty_pv)
        d0 = {"id": did, "origin": "analysis", "format": "reel", "status": "approved_script", "render_status": "queued",
              "topic_id": "t1", "topic_date": D, "title": "ريل", "script_status": "ready", "review_issue": 4243,
              "script": {"narrator": "female", "title": title, "question": "هل؟", "scenes": scenes()}, **(extra or {})}
        if with_bg:
            d0["reel_bg"] = {"url": "https://n/ok.jpg", "kind": "news_photo", "publisher": "R"}
        path = store.save_draft(d0)
        o_join, o_title = reel_render._join, reel_render.frame_title

        def spy_join(files, kinds, durs, c, dp, t):
            joined.update(kinds=list(kinds), durs=list(durs))
            return o_join(files, kinds, durs, c, dp, t)

        def spy_title(*a, **k):
            titled.append(1)
            return o_title(*a, **k)
        reel_render._join, reel_render.frame_title = spy_join, spy_title
        try:
            reel_render.render_draft(path, d0, cfg, deps, reels_dir=tmp / "reels", workdir=tmp / "work")
        finally:
            reel_render._join, reel_render.frame_title = o_join, o_title
        state = json.loads(path.read_text(encoding="utf-8"))
        return {"state": state, "cmds": cmds, "comments": comments, "synths": synths, "downloads": downloads,
                "joined": joined, "title_calls": len(titled)}

    def final_cmd(r):
        """تمريرة الشعار الأخيرة: الأمر الذي ملفه الناتج mp4 داخل مجلد reels."""
        found = [c for c in r["cmds"] if c[-1].endswith(".mp4") and "reels" in Path(c[-1]).parts]
        return found[-1] if found else []

    tmp = Path(tempfile.mkdtemp())
    try:
        # ── g298: ترتيب المشاهد ──
        def g298():
            r = render("r5c1000g298a1", tmp)
            kinds = r["joined"].get("kinds", [])
            check("g298: التركيب نجح", r["state"].get("render_status") == "rendered", r["state"].get("render_error"))
            check("g298: أول مشهد hook ثم cold_open_clip", kinds[:2] == ["hook", "cold_open_clip"], kinds)
            check("g298: title_card لا يبقى مشهدًا والباقي بترتيبه",
                  kinds == ["hook", "cold_open_clip", "narration", "clip", "question", "outro"], kinds)
            check("g298: frame_title لا يُستدعى", r["title_calls"] == 0, r["title_calls"])
        guarded("g298", g298)

        # ── g299: مدة الهوك وصوت العنوان ──
        def g299():
            for n, (audio, want) in enumerate(((1.5, 3.5), (4.0, 4.8), (9.0, 7.0))):
                r = render(f"r5c1000g299a{n}", tmp, hook_audio=audio)
                durs = r["joined"].get("durs") or [0]
                check(f"g299: صوت {audio} ث ← مدة الهوك {want}", abs(durs[0] - want) < 0.05, durs)
                first = r["synths"][0] if r["synths"] else ""
                check(f"g299: أول توليد صوتي نصه العنوان", tts.strip_tashkeel(first) == title, r["synths"][:1])
        guarded("g299", g299)

        # ── g300: خلفية الهوك ──
        def g300():
            w = int(cfg.path("reel.render.width"))
            img_w = 1210
            check("g300: pan_x(0) أقصى اليمين", abs(reel_render.pan_x(0, cfg, img_w) - (img_w - w)) < 1e-6,
                  reel_render.pan_x(0, cfg, img_w))
            check("g300: pan_x يتناقص 40 بكسل/ث", abs(reel_render.pan_x(1, cfg, img_w) - (img_w - w - 40)) < 1e-6)
            check("g300: pan_x لا ينزل عن 0", reel_render.pan_x(60, cfg, img_w) == 0, reel_render.pan_x(60, cfg, img_w))
            timed = re.compile(r"crop=1080:1920:x='[^']*\bt\b[^']*'")
            center = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0"
            hv = {"video_id": "hv1", "start": 5, "end": 12}
            r = render("r5c1000g300a1", tmp, extra={"hook_video": hv}, with_bg=True)
            check("g300: hook_video ← تنزيل بنافذته", ("hv1", 5, 12) in r["downloads"], r["downloads"])
            check("g300: hook_video ← crop من المنتصف", any(center in " ".join(c) and "-stream_loop" in c for c in r["cmds"]))
            check("g300: hook_video ← لا crop زمني", not any(timed.search(" ".join(c)) for c in r["cmds"]))
            r = render("r5c1000g300b1", tmp, with_bg=True)
            check("g300: بلا hook_video مع reel_bg ← crop زمني", any(timed.search(" ".join(c)) for c in r["cmds"]))
            check("g300: بلا تنزيل للهوك", not any(d[0] == "hv1" for d in r["downloads"]), r["downloads"])
            r = render("r5c1000g300c1", tmp, extra={"hook_video": hv}, with_bg=True, hook_dl_fail=True)
            note = cfg.path("reel.render.texts.comment_hook_video_failed")
            check("g300: فشل تنزيل hook_video ← التركيب ينجح", r["state"].get("render_status") == "rendered",
                  r["state"].get("render_error"))
            check("g300: فشل التنزيل ← خلفية الصورة المتحركة", any(timed.search(" ".join(c)) for c in r["cmds"]))
            check("g300: فشل التنزيل ← سطر في التعليق", bool(note) and any(note in c for c in r["comments"]), r["comments"])
            r = render("r5c1000g300d1", tmp)
            check("g300: بلا صورة ← كحلي ثابت (لا crop زمني) والتركيب ينجح",
                  r["state"].get("render_status") == "rendered" and not any(timed.search(" ".join(c)) for c in r["cmds"]),
                  r["state"].get("render_error"))
        guarded("g300", g300)

        # ── g301: حالة الشعار وأمر التمريرة الأخيرة ──
        def g301():
            end = 5.0
            x, y, wd, a = reel_render.logo_state(0, cfg, end)
            check("g301: t=0 شفاف بعرض 336", a == 0 and abs(wd - 336) < 1e-6, (x, y, wd, a))
            x, y, wd, a = reel_render.logo_state(0.5, cfg, end)
            check("g301: t=0.5 بعرض 560 وسط الشاشة وأعلاه 420",
                  abs(wd - 560) < 1e-6 and abs(x - (1080 - 560) / 2) < 1e-6 and abs(y - 420) < 1e-6 and abs(a - 1) < 1e-6,
                  (x, y, wd, a))
            x, y, wd, a = reel_render.logo_state(end + 0.3, cfg, end)
            check("g301: منتصف الحركة بعرض بين 168 و560", 168 < wd < 560, wd)
            x, y, wd, a = reel_render.logo_state(end + 0.6, cfg, end)
            check("g301: بعد الحركة في الزاوية", abs(wd - 168) < 1e-6 and abs(x - (1080 - 54 - 168)) < 1e-6
                  and abs(y - 108) < 1e-6 and abs(a - 1) < 1e-6, (x, y, wd, a))
            x, y, wd, a = reel_render.logo_state(30, cfg, end)
            check("g301: يبقى في الزاوية حتى النهاية", abs(wd - 168) < 1e-6 and abs(x - 858) < 1e-6 and abs(y - 108) < 1e-6)
            r = render("r5c1000g301a1", tmp)
            g = " ".join(final_cmd(r))
            check("g301: الأمر الأخير فيه eval=frame", "eval=frame" in g, g[-300:])
            check("g301: تعابير overlay بالزمن t", re.search(r"overlay=x='[^']*\bt\b", g) is not None, g[-300:])
            check("g301: overlay الزاوية الثابت لا يعمل إلا بعد الانتقال (enable)",
                  re.search(r"overlay=W-w-54:108:enable='gte\(t,", g) is not None, g[-300:])
        guarded("g301", g301)

        # ── g302: المتكلم بلا شرط margin ──
        def g302():
            frames = [np.full((SH, SW), 100, np.uint8) for _ in range(20)]
            boxes = [[(120, 100, 100, 120), (420, 100, 100, 120)] for _ in range(20)]
            o = reel_render._region_diff
            mtop = float(cfg.path("reel.render.speaker.mouth_top"))

            def fake(left, right):
                def diff(fa, box_a, fb, box_b, top, bottom, width, search):
                    if abs(top - mtop) > 1e-6:
                        return 0.0
                    return left if box_a[0] < 300 else right
                return diff
            try:
                for tag, (l, rt), want, center in (("1.0 و0.9", (0.9, 1.0), "face", None),      # عاد margin (Issue #1431)
                                                   ("1.0 و0.5", (0.5, 1.0), "speaker", 470),
                                                   ("0.2 و0.1", (0.1, 0.2), "face", None),
                                                   ("1.0 و1.0", (1.0, 1.0), "face", None)):
                    reel_render._region_diff = fake(l, rt)
                    res = reel_render.speaker_track(frames, boxes, cfg)
                    ok = res.get("source") == want and (center is None or abs(res["center"] - center) < 1)
                    check(f"g302: درجتان {tag} ← {want}", ok, res)
            finally:
                reel_render._region_diff = o
            check("g302: talk_min في الإعداد", float(cfg.path("reel.render.speaker.talk_min", 0)) == 0.3,
                  cfg.path("reel.render.speaker"))
        guarded("g302", g302)

        # ── g303: مركز «؟» في الدائرة ──
        def g303():
            img = reel_render.frame_question(cfg, "هل تتجه المنطقة إلى تسوية؟").convert("RGB")
            arr = np.asarray(img).astype(int)
            cx, cy, r = 540, 520, 120
            yy, xx = np.mgrid[0:arr.shape[0], 0:arr.shape[1]]
            inside = (xx - cx) ** 2 + (yy - cy) ** 2 <= (r - 4) ** 2
            ink = inside & (arr[:, :, 0] < 150)
            ys, xs_ = np.nonzero(ink)
            check("g303: وُجد حبر داخل الدائرة", len(ys) > 200, len(ys))
            mx, my = (xs_.min() + xs_.max()) / 2, (ys.min() + ys.max()) / 2
            check("g303: مركز حبر «؟» ضمن ±6 من مركز الدائرة", abs(mx - cx) <= 6 and abs(my - cy) <= 6, (mx, my))
            # الذيل داخل الدائرة: لا حبر خارجها قرب حدّها السفلي
            check("g303: حبر الدائرة كله داخل حدّها (±4)", ys.max() < cy + r - 4 and ys.min() > cy - r + 4)
        guarded("g303", g303)

        # ── g304: نص الهوك والنسخة ──
        def g304():
            long_title = " ".join(["كلمة"] * 7 + ["عنوان"] * 7)
            seen: list = []
            o_fit = reel_render._fit

            def spy(d, t, fp, mw, ml, st, mn, wt, lf):
                seen.append((fp, ml, st, mn))
                return o_fit(d, t, fp, mw, ml, st, mn, wt, lf)
            reel_render._fit = spy
            boxes: list = []
            try:
                reel_render.frame_hook_text(cfg, long_title, boxes)
            finally:
                reel_render._fit = o_fit
            disp = cfg.path("reel.render.fonts.display")
            check("g304: بالرقعة وmax_lines 4 وحجم 139/75", any(s == (disp, 4, 139, 75) for s in seen), seen)
            x0 = int(cfg.path("reel.render.safe.right_col_width"))
            top, bottom = int(cfg.path("reel.render.safe.top")), 1920 - int(cfg.path("reel.render.safe.bottom"))
            check("g304: كل الصناديق داخل المنطقة الآمنة",
                  bool(boxes) and all(b[0] >= x0 and b[2] <= 1080 - x0 and b[1] >= top and b[3] <= bottom for b in boxes), boxes)
            check("g304: render_version == 14", int(cfg.path("reel.render.version")) == 14, cfg.path("reel.render.version"))
        guarded("g304", g304)

        # ── g305: خلفية الهوك الخام (بلا تظليل الكحلي المسبق) ──
        def g305():
            light = Image.new("RGB", (1400, 800), (230, 230, 230))
            bgd = reel_render.prepare_background(cfg, light)
            raw = bgd.get("raw")
            check("g305: prepare_background يعيد raw", raw is not None, list(bgd))
            if raw is None:
                return
            check("g305: raw بمقاس 1080×1920", raw.size == (1080, 1920), raw.size)
            check("g305: سطوع raw أعلى من image لصورة فاتحة",
                  np.asarray(raw.convert("L")).mean() > np.asarray(bgd["image"].convert("L")).mean() + 20)
            o_prep, o_save = reel_render.prepare_background, reel_render._save
            made, saved = [], {}

            def spy_prep(c, img):
                res = o_prep(c, img)
                made.append(res)
                return res

            def spy_save(img, path):
                out = o_save(img, path)
                saved[str(out)] = img
                return out
            reel_render.prepare_background, reel_render._save = spy_prep, spy_save
            try:
                r = render("r5c1000g305a1", tmp, with_bg=True)
            finally:
                reel_render.prepare_background, reel_render._save = o_prep, o_save
            hb = [a for c in r["cmds"] for a in c if re.search(r"hook_bg_\d+\.png$", a)]
            check("g305: أمر الهوك (ب) يقرأ hook_bg", bool(hb) and bool(made), (hb, len(made)))
            if hb and made:
                src = saved.get(hb[0])
                check("g305: الملف المحفوظ من raw لا من image", src is made[-1].get("raw") and src is not made[-1]["image"])
        guarded("g305", g305)

        # ── g306: التمريرة الأخيرة بلا geq وبمدخل شعار محدود ──
        def g306():
            r = render("r5c1000g306a1", tmp)
            c = final_cmd(r)
            g = " ".join(c)
            for needle in ("fade=t=in", "eof_action=pass", "enable='gte(t,"):
                check(f"g306: الأمر الأخير يحتوي {needle}", needle in g, g[-400:])
            check("g306: الأمر الأخير بلا geq", "geq" not in g, g[-400:])
            check("g306: overlay المتحرك بلا shortest", "eval=frame:shortest=1" not in g, g[-400:])
            hook_end = r["joined"]["durs"][0] - reel_render.transition_seconds(cfg)
            want = hook_end + float(cfg.path("reel.render.hook.logo_move")) + 0.1
            loops = [i for i, a in enumerate(c) if a == "-loop"]
            pre = bool(loops) and c[loops[0] + 4] == "-t" and abs(float(c[loops[0] + 5]) - want) <= 0.01
            check("g306: مدخل الشعار المتحرك مسبوق بـ -t = hook_end+logo_move+0.1", pre, (want, c[:12]))
            check("g306: alpha عند 0.25 تساوي 0.5", abs(reel_render.logo_state(0.25, cfg, 5.0)[3] - 0.5) < 1e-6,
                  reel_render.logo_state(0.25, cfg, 5.0))
        guarded("g306", g306)

        # ── g307: لا قفزة عند التبديل إلى الشعار الثابت ──
        def g307():
            end = 5.0
            move = float(cfg.path("reel.render.hook.logo_move"))
            x, y, wd, a = reel_render.logo_state(end + move, cfg, end)
            check("g307: آخر حالة متحركة = الثابت تمامًا",
                  (x, y, wd, a) == (1080 - 54 - 168, 108, 168, 1.0), (x, y, wd, a))
            r = render("r5c1000g307a1", tmp)
            g = " ".join(final_cmd(r))
            hook_end = r["joined"]["durs"][0] - reel_render.transition_seconds(cfg)
            check("g307: overlay ثابت بالموضع القديم", "overlay=W-w-54:108" in g, g[-400:])
            m = re.search(r"enable='gte\(t,([\d.]+)\)'", g)
            check("g307: يبدأ عند hook_end + logo_move", bool(m) and abs(float(m.group(1)) - (hook_end + move)) <= 0.01,
                  (m.group(1) if m else None, hook_end + move))
            check("g307: scale ثابت بعرض 168", "scale=168:-1" in g, g[-400:])
        guarded("g307", g307)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reel_speaker_vision_r5b2_guards() -> None:
    """Issue #1431 (R5b2، g308–g312): حين يظهر أكثر من وجه يحسم الرؤية (ثلاث لقطات بمستطيلات مرقّمة) من المتكلم، فإن لم تُقبل
    عادت حركة الفم بشرط التفوق margin وإلا أكبر وجه؛ مسار واحد لا نداء له. لا شبكة ولا ffmpeg."""
    import base64
    import io
    import json
    import tempfile
    from pathlib import Path

    import numpy as np
    from PIL import Image

    from src import llm, reel_render, reel_script

    cfg = load_config()
    SW, SH = 640, 360

    def guarded(name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 -- الحالة الفاشلة تُسجَّل ولا توقف بقية الحالات
            check(name + ": استثناء", False, repr(exc))

    D = "2099-12-09"
    quote = "alpha beta gamma delta epsilon zeta eta theta"
    points = [{"video_id": "v1", "statement": "s", "quote_original": quote, "quote_arabic": "ترجمة", "speaker": "متحدث",
               "channel": "CNN TÜRK", "video_url": "https://youtube.com/watch?v=v1", "timestamp": 10},
              {"video_id": "v2", "statement": "s2", "quote_original": quote, "quote_arabic": "ترجمة٢", "speaker": "متحدث٢",
               "channel": "CNN TÜRK", "video_url": "https://youtube.com/watch?v=v2", "timestamp": 10}]
    clip = {"kind": "clip", "start": 9, "end": 20, "speaker_name": "", "speaker_role": "", "speaker_verified": False,
            "speaker_name_latin": "", "channel_display": "سي إن إن ترك", "channel_original": "CNN TÜRK",
            "quote_arabic": "ترجمة", "language": "tr"}
    transcripts = {v: "[00:10] alpha beta gamma delta\n[00:14] epsilon zeta eta theta\n[00:18] tail line" for v in ("v1", "v2")}
    empty_pv = {"news": lambda *a: [], "web": lambda *a, **k: [], "free": lambda *a: []}
    two = [(120, 100, 100, 120), (420, 100, 100, 120)]      # مركزان 170 و470؛ الرقم 1 = الأيمن (470)
    FRAMES = [np.full((SH, SW), 100, np.uint8) for _ in range(20)]

    def scenes():
        return [dict(clip, kind="cold_open_clip", video_url=points[0]["video_url"],
                     point_id=reel_script.point_key_id(points[0])),
                {"kind": "narration", "text": "جملة."},
                dict(clip, video_url=points[1]["video_url"], point_id=reel_script.point_key_id(points[1])),
                {"kind": "question", "text": "هل؟"}, {"kind": "outro"}]

    def fake_diff(left, right):
        mtop = float(cfg.path("reel.render.speaker.mouth_top"))

        def diff(fa, box_a, fb, box_b, top, bottom, width, search):
            if abs(top - mtop) > 1e-6:
                return 0.0
            return left if box_a[0] < 300 else right
        return diff

    def render(did, tmp, *, boxes=two, pick=None, left=3.0, right=0.5):
        cmds, comments, calls = [], [], []

        def run(cmd):
            cmds.append([str(c) for c in cmd])
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(b"x")

        def download(video_id, start, end, height, out_path):
            Path(out_path).write_bytes(b"clip")
            return {"tier": "a", "bytes": 4, "failures": []}

        def spy_pick(f, tracks, scene, c):
            calls.append(len(tracks))
            return pick(f, tracks, scene, c)
        deps = reel_render.Deps(
            fetch_transcript=lambda vid: transcripts.get(vid), download_clip=download,
            synthesize=lambda t, voice: {"ok": True, "audio": b"mp3", "chars": len(t)},
            diacritize=lambda t: (t, None), run=run,
            probe=lambda p: 41.0 if "reels" in Path(p).parts else 2.0, sleep=lambda s: None,
            load_points=lambda date: points, comment=lambda i, t: comments.append(t),
            faces=lambda f, fr: (SW, SH, [170.0, 170.0]), frames=lambda p, fr: [np.full((SH, SW), 100, np.uint8)] * len(fr),
            streams=lambda p: {"video", "audio"}, read_chyron=lambda f, c: None,
            face_tracks=lambda f, c: (SW, SH, FRAMES, [list(boxes) for _ in FRAMES]),
            pick_speaker=spy_pick if pick else None, bg_image=lambda u: None, bg_providers=empty_pv)
        d0 = {"id": did, "origin": "analysis", "format": "reel", "status": "approved_script", "render_status": "queued",
              "topic_id": "t1", "topic_date": D, "title": "ريل", "script_status": "ready", "review_issue": 4244,
              "script": {"narrator": "female", "title": "عنوان", "question": "هل؟", "scenes": scenes()}}
        path = store.save_draft(d0)
        o = reel_render._region_diff
        reel_render._region_diff = fake_diff(left, right)
        try:
            reel_render.render_draft(path, d0, cfg, deps, reels_dir=tmp / "reels", workdir=tmp / "work")
        finally:
            reel_render._region_diff = o
        return {"state": json.loads(path.read_text(encoding="utf-8")), "comments": comments, "calls": calls}

    def votes(*nums):
        return lambda f, tracks, scene, c: [{"speaker": n, "archive": [], "reason": ""} for n in nums]

    def crop0(r):
        return (r["state"].get("render_crops") or {}).get("0") or {}

    tmp = Path(tempfile.mkdtemp())
    try:
        # ── g308: الرؤية تغلب حركة الفم (لقطات أرشيفية) ──
        def g308():
            want = reel_render.crop_window(SW, SH, [170.0], "face")["x"]
            r = render("r5b2000g308a1", tmp, pick=votes(2, 2, 0))        # حركة فم المسار الأيمن (1) أعلى بكثير
            c = crop0(r)
            check("g308: التركيب نجح", r["state"].get("render_status") == "rendered", r["state"].get("render_error"))
            check("g308: source == speaker_vision", c.get("source") == "speaker_vision", c)
            check("g308: النافذة تتوسّط المسار الثاني (الأيسر)", c.get("x") == want, (c.get("x"), want))
            check("g308: vision يحمل pick وagree وarchive",
                  c.get("vision", {}).get("pick") == 2 and c["vision"].get("agree") == 2 and "archive" in c["vision"], c)
        guarded("g308", g308)

        # ── g309: عدم قبول الرؤية ← حركة الفم بشرط التفوق ثم أكبر وجه ──
        def g309():
            for n, (tag, pk) in enumerate((("0 و0 و0", votes(0, 0, 0)), ("1 و2 و0 (اختلاف)", votes(1, 2, 0)))):
                r = render(f"r5b2000g309a{n}", tmp, pick=pk, left=1.0, right=0.9)
                check(f"g309: {tag}، 1.0 و0.9 ← face", crop0(r).get("source") == "face", crop0(r))
                r = render(f"r5b2000g309b{n}", tmp, pick=pk, left=0.5, right=1.0)
                c = crop0(r)
                check(f"g309: {tag}، 1.0 و0.5 ← speaker للأعلى (470)",
                      c.get("source") == "speaker_combined" and c.get("x") == reel_render.crop_window(SW, SH, [470.0], "face")["x"], c)
            check("g309: speaker.margin في الإعداد", float(cfg.path("reel.render.speaker.margin", 0)) == 1.25,
                  cfg.path("reel.render.speaker"))
        guarded("g309", g309)

        # ── g310: عطل الرؤية، ومسار واحد بلا نداء ──
        def g310():
            def boom(f, tracks, scene, c):
                raise RuntimeError("down")
            r = render("r5b2000g310a1", tmp, pick=boom, left=1.0, right=0.9)
            check("g310: استثناء ← التركيب ينجح", r["state"].get("render_status") == "rendered", r["state"].get("render_error"))
            check("g310: استثناء ← face (1.0 و0.9)", crop0(r).get("source") == "face", crop0(r))
            r = render("r5b2000g310b1", tmp, pick=boom, left=0.5, right=1.0)
            check("g310: استثناء ← speaker_combined (1.0 و0.5)", crop0(r).get("source") == "speaker_combined", crop0(r))
            r = render("r5b2000g310c1", tmp, boxes=two[:1], pick=votes(1, 1, 1))
            check("g310: مسار واحد ← لا نداء", r["calls"] == [], r["calls"])
            check("g310: مسار واحد ← التركيب ينجح", r["state"].get("render_status") == "rendered",
                  r["state"].get("render_error"))
        guarded("g310", g310)

        # ── g311: النداء الحقيقي ──
        def g311():
            tracks = [{"center": 470.0, "box": (420, 100, 100, 120)}, {"center": 170.0, "box": (120, 100, 100, 120)}]
            raw = Image.new("RGB", (SW, SH), (120, 120, 120))
            jpg = reel_render.annotated_jpeg(raw, tracks, cfg)
            sent = np.asarray(Image.open(io.BytesIO(jpg)).convert("RGB")).astype(int)
            base = np.asarray(raw).astype(int)
            region = (slice(94, 232), slice(114, 226))
            check("g311: المستطيل مرسوم (اللقطة تختلف في منطقته)",
                  np.abs(sent[region] - base[region]).mean() > 3, np.abs(sent[region] - base[region]).mean())
            check("g311: خارج المستطيل لا تغيير", np.abs(sent[:60, :60] - base[:60, :60]).mean() < 3)
            big = reel_render.annotated_jpeg(Image.new("RGB", (2560, 1440), (120, 120, 120)), tracks, cfg)
            check("g311: التصغير إلى عرض 1280", Image.open(io.BytesIO(big)).width == 1280)
            seen: dict = {}

            class Block:
                type = "tool_use"
                name = "pick_speaker"
                input = {"frames": [{"speaker": 2, "archive": [1], "reason": "r"}] * 3}

            class Resp:
                stop_reason = "tool_use"
                content = [Block()]

            class Msgs:
                def create(self, **kw):
                    seen.update(kw)
                    return Resp()

            class Client:
                messages = Msgs()
            out = reel_render.call_pick_speaker_model([jpg, jpg, jpg], dict(clip, speaker_name="فلان"), cfg, Client())
            blocks = [b for m in seen.get("messages", []) for b in (m["content"] if isinstance(m["content"], list) else [])
                      if b.get("type") == "image"]
            text = " ".join(b.get("text", "") for m in seen.get("messages", []) for b in
                            (m["content"] if isinstance(m["content"], list) else []) if b.get("type") == "text")
            check("g311: النموذج haiku المحلول", seen.get("model") == llm.resolve("haiku"), seen.get("model"))
            check("g311: ثلاث كتل image base64 jpeg",
                  len(blocks) == 3 and all(b["source"]["type"] == "base64" and b["source"]["media_type"] == "image/jpeg"
                                           for b in blocks), blocks)
            check("g311: الصورة المرسلة هي المشروحة", base64.b64decode(blocks[0]["source"]["data"]) == jpg if blocks else False)
            tc = seen.get("tool_choice") or {}
            check("g311: أداة إجبارية pick_speaker", [t["name"] for t in seen.get("tools") or []] == ["pick_speaker"]
                  and tc.get("type") == "tool" and tc.get("name") == "pick_speaker", tc)
            check("g311: quote_arabic واسم المتحدث والقناة في الرسالة",
                  all(s in text for s in ("ترجمة", "فلان", "سي إن إن ترك")), text)
            check("g311: تعليمة النظام من الإعداد", bool(seen.get("system")) and "مستطيلات" in str(seen.get("system")))
            check("g311: الناتج ثلاثة إطارات", isinstance(out, list) and len(out) == 3 and out[0]["speaker"] == 2, out)
        guarded("g311", g311)

        # ── g312: سطر 🎯 وrender_version ──
        def g312():
            r = render("r5b2000g312a1", tmp, pick=votes(2, 2, 2))
            lines = [ln for c in r["comments"] for ln in c.splitlines() if "🎯" in ln]
            check("g312: سطر 🎯 لكل مقطع بوجهين", len(lines) == 2, lines)
            check("g312: السطر يحمل القناة وعدد الوجوه والرؤية",
                  bool(lines) and "سي إن إن ترك" in lines[0] and "2 وجوه" in lines[0] and "بالرؤية" in lines[0], lines)
            r = render("r5b2000g312b1", tmp, pick=votes(0, 0, 0), left=0.5, right=1.0)
            check("g312: بالفم واليدين والموقع", any("بالفم واليدين والموقع" in c for c in r["comments"]), r["comments"])
            r = render("r5b2000g312c1", tmp, pick=votes(0, 0, 0), left=1.0, right=0.9)
            check("g312: أكبر وجه", any("أكبر وجه" in c and "🎯" in c for c in r["comments"]), r["comments"])
            r = render("r5b2000g312d1", tmp, boxes=two[:1], pick=votes(1, 1, 1))
            check("g312: لا سطر لمقطع بوجه واحد", not any("🎯" in c for c in r["comments"]), r["comments"])
            check("g312: render_version == 14", int(cfg.path("reel.render.version")) == 14, cfg.path("reel.render.version"))
        guarded("g312", g312)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reel_speaker_gesture_r5b3_guards() -> None:
    """Issue #1434 (R5b3، g313–g317): حركة اليدين (الجسد تحت الوجه) والقرب من الوسط في اختيار المتكلم، ولا تغلب الرؤية
    حركةً جسدية صريحة (فم وإيماء كلاهما ≥ override_margin ×). لا شبكة ولا ffmpeg."""
    import json
    import re
    import tempfile
    from pathlib import Path

    import numpy as np

    from src import reel_render, reel_script

    cfg = load_config()
    SW, SH = 640, 360

    def guarded(name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 -- الحالة الفاشلة تُسجَّل ولا توقف بقية الحالات
            check(name + ": استثناء", False, repr(exc))

    D = "2099-12-10"
    quote = "alpha beta gamma delta epsilon zeta eta theta"
    points = [{"video_id": "v1", "statement": "s", "quote_original": quote, "quote_arabic": "ترجمة", "speaker": "متحدث",
               "channel": "CNN TÜRK", "video_url": "https://youtube.com/watch?v=v1", "timestamp": 10},
              {"video_id": "v2", "statement": "s2", "quote_original": quote, "quote_arabic": "ترجمة٢", "speaker": "متحدث٢",
               "channel": "CNN TÜRK", "video_url": "https://youtube.com/watch?v=v2", "timestamp": 10}]
    clip = {"kind": "clip", "start": 9, "end": 20, "speaker_name": "", "speaker_role": "", "speaker_verified": False,
            "speaker_name_latin": "", "channel_display": "سي إن إن ترك", "channel_original": "CNN TÜRK",
            "quote_arabic": "ترجمة", "language": "tr"}
    transcripts = {v: "[00:10] alpha beta gamma delta\n[00:14] epsilon zeta eta theta\n[00:18] tail line" for v in ("v1", "v2")}
    empty_pv = {"news": lambda *a: [], "web": lambda *a, **k: [], "free": lambda *a: []}
    two = [(120, 100, 100, 120), (420, 100, 100, 120)]          # مركزان 170 و470 (متساويا البعد عن الوسط)
    mid = [(120, 100, 100, 120), (270, 100, 100, 120)]          # مركزان 170 و320 (الثاني في الوسط)
    FRAMES = [np.full((SH, SW), 100, np.uint8) for _ in range(20)]
    mtop = float(cfg.path("reel.render.speaker.mouth_top", 0.6667))

    def scenes():
        return [dict(clip, kind="cold_open_clip", video_url=points[0]["video_url"],
                     point_id=reel_script.point_key_id(points[0])),
                {"kind": "narration", "text": "جملة."},
                dict(clip, video_url=points[1]["video_url"], point_id=reel_script.point_key_id(points[1])),
                {"kind": "question", "text": "هل؟"}, {"kind": "outro"}]

    def fake_diff(vals):
        """vals: {x الصندوق الأول: (فم، إيماء)}؛ الفم بمنطقة mouth_top والإيماء بمنطقة تبدأ من أسفل الصندوق (top = 1.0)."""
        def diff(fa, box_a, fb, box_b, top, bottom, width, search):
            m, g = vals[int(box_a[0])]
            if abs(top - mtop) < 1e-6:
                return m
            if abs(top - 1.0) < 1e-6:
                return g
            return 0.0
        return diff

    def render(did, tmp, boxes, vals, pick, client=None):
        comments, calls = [], []

        def run(cmd):
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(b"x")

        def download(video_id, start, end, height, out_path):
            Path(out_path).write_bytes(b"clip")
            return {"tier": "a", "bytes": 4, "failures": []}

        def spy(f, tracks, scene, c):
            calls.append(tracks)
            return pick(f, tracks, scene, c)
        deps = reel_render.Deps(
            fetch_transcript=lambda vid: transcripts.get(vid), download_clip=download,
            synthesize=lambda t, voice: {"ok": True, "audio": b"mp3", "chars": len(t)},
            diacritize=lambda t: (t, None), run=run,
            probe=lambda p: 41.0 if "reels" in Path(p).parts else 2.0, sleep=lambda s: None,
            load_points=lambda date: points, comment=lambda i, t: comments.append(t),
            faces=lambda f, fr: (SW, SH, [170.0, 170.0]), frames=lambda p, fr: [np.full((SH, SW), 100, np.uint8)] * len(fr),
            streams=lambda p: {"video", "audio"}, read_chyron=lambda f, c: None,
            face_tracks=lambda f, c: (SW, SH, FRAMES, [list(boxes) for _ in FRAMES]),
            pick_speaker=spy, bg_image=lambda u: None, bg_providers=empty_pv)
        d0 = {"id": did, "origin": "analysis", "format": "reel", "status": "approved_script", "render_status": "queued",
              "topic_id": "t1", "topic_date": D, "title": "ريل", "script_status": "ready", "review_issue": 4244,
              "script": {"narrator": "female", "title": "عنوان", "question": "هل؟", "scenes": scenes()}}
        path = store.save_draft(d0)
        o = reel_render._region_diff
        reel_render._region_diff = fake_diff(vals)
        try:
            reel_render.render_draft(path, d0, cfg, deps, reels_dir=tmp / "reels", workdir=tmp / "work")
        finally:
            reel_render._region_diff = o
        return {"state": json.loads(path.read_text(encoding="utf-8")), "comments": comments, "calls": calls}

    def votes(*nums):
        return lambda f, tracks, scene, c: [{"speaker": n, "archive": [], "reason": ""} for n in nums]

    def crop0(r):
        return (r["state"].get("render_crops") or {}).get("0") or {}

    def win(center):
        return reel_render.crop_window(SW, SH, [center], "face")["x"]

    tmp = Path(tempfile.mkdtemp())
    try:
        # ── g313: حالة CNN — الرؤية تختار 2 والمسار 1 فمه 2.5× وإيماؤه 3× ← المسار 1 ──
        def g313():
            r = render("r5b3000g313a1", tmp, two, {420: (2.5, 3.0), 120: (1.0, 1.0)}, votes(2, 2, 2))
            c = crop0(r)
            check("g313: source == speaker_motion_override", c.get("source") == "speaker_motion_override", c)
            check("g313: النافذة تتوسّط المسار 1 (470)", c.get("x") == win(470.0), (c.get("x"), win(470.0)))
            check("g313: vision.overridden_by == 1", (c.get("vision") or {}).get("overridden_by") == 1, c)
        guarded("g313", g313)

        # ── g314: حالة فرانس 24 — الفم 2.5× والإيماء متساوٍ ← الرؤية تبقى (المسار 2) ──
        def g314():
            r = render("r5b3000g314a1", tmp, two, {420: (2.5, 1.0), 120: (1.0, 1.0)}, votes(2, 2, 2))
            c = crop0(r)
            check("g314: source == speaker_vision", c.get("source") == "speaker_vision", c)
            check("g314: النافذة تتوسّط المسار 2 (170)", c.get("x") == win(170.0), (c.get("x"), win(170.0)))
            check("g314: لا overridden_by", "overridden_by" not in (c.get("vision") or {}), c)
        guarded("g314", g314)

        # ── g315: الرؤية غير حاسمة ← الدرجة المركّبة؛ والمتقاربة ← face ──
        def g315():
            r = render("r5b3000g315a1", tmp, mid, {270: (1.0, 3.0), 120: (0.9, 0.5)}, votes(0, 0, 0))
            c = crop0(r)
            check("g315: الأوسط يحرك يديه ← speaker_combined", c.get("source") == "speaker_combined", c)
            check("g315: النافذة تتوسّط الأوسط (320)", c.get("x") == win(320.0), (c.get("x"), win(320.0)))
            r = render("r5b3000g315b1", tmp, two, {420: (1.0, 1.0), 120: (0.95, 1.0)}, votes(0, 0, 0))
            check("g315: درجات متقاربة في كل شيء ← face", crop0(r).get("source") == "face", crop0(r))
        guarded("g315", g315)

        # ── g316: درجة الإيماء على إطارات اصطناعية ──
        def g316():
            rng = np.random.default_rng(7)
            n = 6
            box_a, box_b = (120, 60, 100, 100), (420, 60, 100, 100)
            frames = []
            for _ in range(n):
                f = np.full((SH, SW), 100, np.uint8)
                f[170:300, 40:300] = rng.integers(0, 255, (130, 260), dtype=np.uint8)   # كتلة نسيج تتحرك تحت وجه الأيسر
                frames.append(f)
            res = reel_render.speaker_track(frames, [[box_a, box_b]] * n, cfg)
            tl = {int(t["center"]): t for t in res.get("track_list") or []}
            ga, gb = tl.get(170, {}).get("gesture"), tl.get(470, {}).get("gesture")
            check("g316: كل عنصر يحمل gesture", ga is not None and gb is not None, res.get("track_list"))
            check("g316: gesture المتحرك > 5 أضعاف الساكن",
                  ga is not None and gb is not None and ga > 5 * max(gb, 0.01), (ga, gb))
            tex = rng.integers(0, 255, (SH, SW), dtype=np.uint8)
            cam, cboxes = [], []
            for k in range(n):
                cam.append(np.roll(tex, shift=(2 * k, 3 * k), axis=(0, 1)))
                cboxes.append([(box_a[0] + 3 * k, box_a[1] + 2 * k, 100, 100), (box_b[0] + 3 * k, box_b[1] + 2 * k, 100, 100)])
            res2 = reel_render.speaker_track(cam, cboxes, cfg)
            g2 = [t.get("gesture") for t in res2.get("track_list") or []]
            check("g316: إزاحة اللقطة كلها لا ترفع gesture", bool(g2) and all(g is not None and g < 1.0 for g in g2), g2)
        guarded("g316", g316)

        # ── g317: التعليمة والرسالة وسطور 🎯 وrender_version ──
        def g317():
            system = str(cfg.path("reel.render.speaker.vision.system", ""))
            check("g317: التعليمة تحوي «يشير بيديه»", "يشير بيديه" in system, system[-200:])
            seen: dict = {}

            class Block:
                type = "tool_use"
                name = "pick_speaker"
                input = {"frames": [{"speaker": 2, "archive": [], "reason": "r"}] * 3}

            class Resp:
                stop_reason = "tool_use"
                content = [Block()]

            class Msgs:
                def create(self, **kw):
                    seen.update(kw)
                    return Resp()

            class Client:
                messages = Msgs()
            pick = lambda f, tracks, scene, c: reel_render.call_pick_speaker_model([b"x"] * 3, scene, c, Client)  # noqa: E731
            r = render("r5b3000g317a1", tmp, two, {420: (2.5, 3.0), 120: (1.0, 1.0)}, pick)
            text = " ".join(b.get("text", "") for m in seen.get("messages", []) for b in
                            (m["content"] if isinstance(m["content"], list) else []) if b.get("type") == "text")
            check("g317: رسالة النداء بلا درجات", bool(text) and not re.search(r"\d\.\d", text) and "2.5" not in text, text)
            check("g317: سطر 🎯 للتغليب", any("🎯" in c and "بالرؤية مع تغليب الحركة الجسدية" in c for c in r["comments"]),
                  r["comments"])
            r = render("r5b3000g317b1", tmp, mid, {270: (1.0, 3.0), 120: (0.9, 0.5)}, votes(0, 0, 0))
            check("g317: سطر 🎯 للمركّبة", any("🎯" in c and "بالفم واليدين والموقع" in c for c in r["comments"]),
                  r["comments"])
            check("g317: render_version == 14", int(cfg.path("reel.render.version")) == 14, cfg.path("reel.render.version"))
        guarded("g317", g317)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_speed_t1_guards() -> None:
    """Issue #1422 (T1، g278–g279): تسريع حزمة الاختبارات — preset الترميز من الإعداد (حقيقيه veryfast وفي الاختبارات ultrafast)
    وحفظ إطارات PNG المؤقتة بضغط خفيف دون تغيير البكسلات."""
    import random
    import tempfile
    from pathlib import Path

    from PIL import Image

    from src import config as real_config
    from src import reel_render

    # ── g278: preset من الإعداد ──
    real = real_config.load_config()
    test_cfg = load_config()
    real_preset = real.path("reel.render.preset")
    test_preset = test_cfg.path("reel.render.preset")
    check("g278: config.yaml الحقيقي preset == veryfast", real_preset == "veryfast", real_preset)
    check("g278: cfg اختبارات الريل preset == ultrafast", test_preset == "ultrafast", test_preset)
    for label, c in (("real", real), ("test", test_cfg)):
        enc = reel_render._enc(c.path("reel.render"))
        i = enc.index("-preset") if "-preset" in enc else -1
        check(f"g278: _enc({label}) يحمل -preset تليه قيمة الإعداد",
              i >= 0 and enc[i + 1] == c.path("reel.render.preset"), enc)

    # ── g279: _save بضغط خفيف وبكسلات مطابقة ──
    rnd = random.Random(1422)
    img = Image.frombytes("RGB", (1080, 1920), rnd.randbytes(1080 * 1920 * 3))
    seen: list[dict] = []
    real_save = Image.Image.save

    def spy(self, fp, *a, **kw):
        seen.append(kw)
        return real_save(self, fp, *a, **kw)

    with tempfile.TemporaryDirectory() as d:
        Image.Image.save = spy  # type: ignore
        try:
            out = reel_render._save(img, Path(d) / "f.png")
        finally:
            Image.Image.save = real_save  # type: ignore
        same = Image.open(out).convert("RGB").tobytes() == img.tobytes()
    check("g279: البكسلات مطابقة بعد الحفظ والقراءة", same)
    check("g279: الحفظ يمرّر compress_level=1", any(k.get("compress_level") == 1 for k in seen), seen)


def test_reel_truncation_r5e_guards() -> None:
    """Issue #1436 (R5e، g318–g322): توحيد طول صورة المشهد وصوته قبل الضمّ فلا يقع offset انتقال بعد نهاية الصورة فيُقطع
    الريل صامتًا، وحارس مدة نهائي يرفض ريلًا أقصر من المتوقع. لا شبكة؛ g321 وحده يحتاج ffmpeg حقيقيًا ويُتخطّى بتنبيه."""
    import json
    import shutil as _shutil
    import subprocess
    import tempfile
    from pathlib import Path

    import numpy as np

    from src import reel_render, reel_script

    cfg = load_config()
    secs = float(cfg.path("reel.render.transition.seconds"))

    def guarded(name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 -- الحالة الفاشلة تُسجَّل ولا توقف بقية الحالات
            check(name + ": استثناء", False, repr(exc))

    # ── g318: scene_fix_plan نقية ──
    def g318():
        p = reel_render.scene_fix_plan(5.0, 7.0)
        check("g318: صوت أطول ← pad_video 2 وpad_audio 0", p == {"pad_video": 2.0, "pad_audio": 0.0}, p)
        p = reel_render.scene_fix_plan(6.0, 4.5)
        check("g318: صورة أطول ← pad_audio 1.5", p == {"pad_video": 0.0, "pad_audio": 1.5}, p)
        p = reel_render.scene_fix_plan(5.0, 5.03)
        check("g318: فرق ضمن التسامح ← لا شيء", p == {"pad_video": 0.0, "pad_audio": 0.0}, p)
    guarded("g318", g318)

    # ── g319: _join يوحّد المشهد الثاني ويحسب offset من المدة الموحَّدة ──
    def g319():
        tmp = Path(tempfile.mkdtemp())
        try:
            def run_join(streams):
                cmds = []

                def run(cmd):
                    cmds.append(list(cmd))
                    Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
                    Path(cmd[-1]).write_bytes(b"x")
                files = [tmp / f"s{i}.mp4" for i in range(4)]
                for f in files:
                    f.write_bytes(b"x")
                deps = reel_render.Deps(run=run, probe=lambda p: 99.0,
                                        stream_durations=lambda p: streams[Path(p).name]).resolved(cfg)
                info: dict = {}
                reel_render._join(files, ["clip"] * 4, [5.0, 7.0, 6.0, 4.0], cfg, deps, tmp, info)
                return cmds, info
            uneven = {"s0.mp4": (5.0, 5.0), "s1.mp4": (5.0, 7.0), "s2.mp4": (6.0, 6.0), "s3.mp4": (4.0, 4.0)}
            cmds, info = run_join(uneven)
            fix = [c for c in cmds if any("tpad=stop_mode=clone" in x for x in c)]
            check("g319: أمر إعادة ترميز واحد للمشهد الثاني", len(fix) == 1 and "s1.mp4" in " ".join(fix[0]), fix)
            check("g319: tpad بفرق 2", bool(fix) and any("stop_duration=2" in x for x in fix[0]), fix)
            graph = " ".join(cmds[-1])
            check("g319: offset الانتقال الثاني من 7 لا 5", f"offset={reel_render._fmt(12 - 2 * secs)}" in graph
                  and f"offset={reel_render._fmt(10 - 2 * secs)}" not in graph, graph[-400:])
            check("g319: المتوقع = 22 − 3×انتقال", abs(info.get("expected", 0) - (22 - 3 * secs)) < 1e-6, info)
            even = {n: (5.0, 5.0) for n in uneven}
            cmds, _ = run_join(even)
            check("g319: المتساوية لا تُعاد ترميزها", not any("tpad" in " ".join(c) or "apad" in " ".join(c) for c in cmds), cmds)
        finally:
            _shutil.rmtree(tmp, ignore_errors=True)
    guarded("g319", g319)

    # ── g320: حارس المدة النهائي ──
    def g320():
        SW, SH = 640, 360
        quote = "alpha beta gamma delta epsilon zeta eta theta"
        D = "2099-12-11"
        points = [{"video_id": v, "statement": "s", "quote_original": quote, "quote_arabic": "ترجمة", "speaker": "متحدث",
                   "channel": "CNN TÜRK", "video_url": f"https://youtube.com/watch?v={v}", "timestamp": 10}
                  for v in ("v1", "v2")]
        clip = {"kind": "clip", "start": 9, "end": 20, "speaker_name": "", "speaker_role": "", "speaker_verified": False,
                "speaker_name_latin": "", "channel_display": "سي إن إن ترك", "channel_original": "CNN TÜRK",
                "quote_arabic": "ترجمة", "language": "tr"}
        tr = {v: "[00:10] alpha beta gamma delta\n[00:14] epsilon zeta eta theta\n[00:18] tail line" for v in ("v1", "v2")}
        tmp = Path(tempfile.mkdtemp())
        try:
            def render(did, final):
                def run(cmd):
                    Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
                    Path(cmd[-1]).write_bytes(b"x")

                def download(video_id, start, end, height, out_path):
                    Path(out_path).write_bytes(b"clip")
                    return {"tier": "a", "bytes": 4, "failures": []}
                comments = []
                deps = reel_render.Deps(
                    fetch_transcript=lambda vid: tr.get(vid), download_clip=download,
                    synthesize=lambda t, voice: {"ok": True, "audio": b"mp3", "chars": len(t)},
                    diacritize=lambda t: (t, None), run=run,
                    probe=lambda p: final if "reels" in Path(p).parts else 2.0, sleep=lambda s: None,
                    stream_durations=lambda p: (18.0, 18.0),
                    load_points=lambda date: points, comment=lambda i, t: comments.append(t),
                    faces=lambda f, fr: (SW, SH, []), frames=lambda p, fr: [np.full((SH, SW), 100, np.uint8)] * len(fr),
                    streams=lambda p: {"video", "audio"}, read_chyron=lambda f, c: None,
                    face_tracks=lambda f, c: None, bg_image=lambda u: None,
                    bg_providers={"news": lambda *a: [], "web": lambda *a, **k: [], "free": lambda *a: []})
                scenes = [dict(clip, kind="cold_open_clip", video_url=points[0]["video_url"],
                               point_id=reel_script.point_key_id(points[0])),
                          {"kind": "narration", "text": "جملة."},
                          dict(clip, video_url=points[1]["video_url"], point_id=reel_script.point_key_id(points[1])),
                          {"kind": "question", "text": "هل؟"}, {"kind": "outro"}]
                d0 = {"id": did, "origin": "analysis", "format": "reel", "status": "approved_script",
                      "render_status": "queued", "topic_id": "t1", "topic_date": D, "title": "ريل", "script_status": "ready",
                      "review_issue": 4436, "reel_file": "reels/old/old.mp4",
                      "script": {"narrator": "female", "title": "عنوان", "question": "هل؟", "scenes": scenes}}
                path = store.save_draft(d0)
                reel_render.render_draft(path, d0, cfg, deps, reels_dir=tmp / "reels", workdir=tmp / "work")
                return json.loads(path.read_text(encoding="utf-8")), comments

            s, comments = render("r5e000g320a1", 63.0)
            check("g320: مدة قصيرة ← failed", s.get("render_status") == "failed", s.get("render_status"))
            check("g320: render_error يحوي «أقصر من المتوقع»", "أقصر من المتوقع" in (s.get("render_error") or ""), s.get("render_error"))
            check("g320: reel_file القديم لم يتغير", s.get("reel_file") == "reels/old/old.mp4", s.get("reel_file"))
            check("g320: لا ملف جديد في reels_dir", not list((tmp / "reels").rglob("*.mp4")), list((tmp / "reels").rglob("*")))
            check("g320: سطر في تعليق التركيب", any("أقصر من المتوقع" in c for c in comments), comments)
            s, _ = render("r5e000g320b1", 88.0)
            check("g320: مدة ضمن التسامح ← rendered", s.get("render_status") == "rendered", (s.get("render_status"), s.get("render_error")))
        finally:
            _shutil.rmtree(tmp, ignore_errors=True)
    guarded("g320", g320)

    # ── g321: دخان بـffmpeg حقيقي ──
    def g321():
        if not _shutil.which("ffmpeg") or not _shutil.which("ffprobe"):
            print("  ⚠️ g321: ffmpeg غير موجود — تخطّي اختبار الدخان (تنبيه لا فشل)")
            return
        from PIL import Image
        work = Path(tempfile.mkdtemp())
        try:
            def ff(*args):
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True, capture_output=True)
            colors = ["red", "green", "blue", "yellow"]
            specs = [(5, 5), (5, 7), (6, 6), (4, 4)]
            files = []
            for i, (c, (v, a)) in enumerate(zip(colors, specs)):
                f = work / f"s{i}.mp4"
                ff("-f", "lavfi", "-i", f"color=c={c}:s=320x240:r=30:d={v}", "-f", "lavfi",
                   "-i", f"sine=frequency=300:sample_rate=48000:duration={a}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-ar", "48000", "-ac", "2", str(f))
                files.append(f)
            deps = reel_render.Deps(run=lambda cmd: subprocess.run(cmd, check=True, capture_output=True)).resolved(cfg)
            joined = reel_render._join(files, ["clip", "clip", "clip", "outro"], [5.0, 7.0, 6.0, 4.0], cfg, deps, work)
            dur = reel_render.probe_duration(joined)
            check("g321: مدة المضموم ≥ 20.5", dur is not None and dur >= 20.5, dur)
            png = work / "last.png"
            ff("-sseof", "-0.3", "-i", str(joined), "-frames:v", "1", str(png))
            r, g, b = Image.open(png).convert("RGB").getpixel((160, 120))
            check("g321: آخر إطار بلون المشهد الأخير (أصفر)", r > 180 and g > 180 and b < 90, (r, g, b))
        finally:
            _shutil.rmtree(work, ignore_errors=True)
    guarded("g321", g321)

    check("g322: render_version == 15", int(cfg.path("reel.render.version")) == 15, cfg.path("reel.render.version"))
