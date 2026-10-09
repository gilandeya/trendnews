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
                          link="https://www.nasa.gov/news/release")]
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
                      link="https://data.worldbank.org/indicator/SP.POP.TOTL"),
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
                             link="https://www.state.gov/releases/x")],
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
    check("(g81) 8e645204c867: كل مؤيِّديها من خارج مصادرنا ⇒ ليست confirmed",
          by_id["8e645204c867"]["verdict"] != "confirmed", by_id["8e645204c867"]["verdict"])

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
    check("(g87) rules_version 6", res["rules_version"] == 6, res["rules_version"])


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

    def run_write(item_, bodies):
        seq = list(bodies)

        def respond(prompt, system):
            return {**good, "post_body": seq.pop(0) if len(seq) > 1 else seq[0]}
        with ImportantWriteRig(respond, gap_sources=gap_src) as rig_:
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

    with ImportantWriteRig(respond93, gap_sources=gap_src) as rig:
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
    with ImportantWriteRig(lambda p, s: {**good, "post_body": _b2_body(330, tag="ب")}, gap_sources=gap_src) as rig:
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
                               gap_sources=gap) as rig:
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
    from tests.helpers import ImportantWriteRig, important_b2_result

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
        with ImportantWriteRig(respond, gap_sources=gap) as rig:
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
    check("(g107) rules_version 6 (رُفعت في #1316)", cfg.path("important.rules_version") == 6)

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
    check("(g118) rules_version 6", icfg.get("rules_version") == 6)

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
                                               "breaking": True}
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
        check("g143: طُبّق على العنوان 1 وعلى post_title وعلى caption",
              again["headlines"][0] == new_h and again["arabic"]["post_title"] == new_h
              and again["caption"].startswith(new_h) and out["headlines"][0] == new_h, again["headlines"])
        check("g143: سطر «✏️ كان … صار» ظاهر في عرض المراجعة", "✏️ كان" in lines and new_h in lines, lines[:300])
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
        gap_src = [{"publisher": "BBC", "link": "https://www.bbc.com/arabic/a1",
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
    check("g159: المفتاح افتراضيًا مطفأ", load_config().path("reel.enabled") is False)
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

    # ── g169) استبعاد: بلا timestamp، متحدث غير مسمّى، اسم في name_unresolved ──
    valid = reel_script.valid_clips(points, unresolved, cfg)
    check("g169: الصالحة ثلاث فقط (بلا timestamp ولا «محلل عسكري» ولا اسم غير محسوم)",
          [c["speaker_name"] for c in valid] == ["إسحاق بريك", "ليلى حداد", "سامر النجار"],
          [c["speaker_name"] for c in valid])
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

    def fake_create(client, **kw):
        calls.append(kw)
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
        out = reel_script.write_for_draft(d170, topic, [pa, pd, pe, pf], "", unresolved, cfg)
        check("g170: لا نداء نموذج", not calls, len(calls))
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
        check("g172: نداء واحد وscript_status ready",
              len(calls) == 1 and d172["script_status"] == "ready" and out["status"] == "ready", out)
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
        prompt = json.dumps(calls[0].get("messages"), ensure_ascii=False)
        check("g172: مدخل النموذج: النص ومعرّفات الصالحة وتاريخ الفيديو وجنس الراوي، لا غير الصالحة",
              "نص مقال الموضوع" in prompt and a_id in prompt and "2099-10-30" in prompt and "male" in prompt
              and "محلل عسكري" not in prompt and "فارع المسلمي" not in prompt)
        check("g172: لا temperature ويُستعمل نموذج المقال",
              "temperature" not in calls[0] and calls[0]["model"] == cfg.path("youtube.article.model"))

        # ── g175) names_audit على السيناريو، والمحرر يستقبل المقاطع بتواريخها ──
        check("g175: names_audit مرّ على نص السيناريو كله ومصدره اقتباسات النقاط الأصلية",
              len(audits) == 1 and "عنوان الشاشة" in audits[0]["title"] and narr1 in audits[0]["body"]
              and HE40 in audits[0]["sources"], audits)
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
        retry_msg = json.dumps(calls[1]["messages"], ensure_ascii=False) if len(calls) > 1 else ""
        check("g173: نداءان بالضبط (إعادة واحدة) ثم failed",
              len(calls) == 2 and d173["script_status"] == "failed", (len(calls), d173.get("script_status")))
        check("g173: الإعادة تذكر سبب الرفض الأول", "ffffffffffff" in retry_msg, retry_msg[-300:])
        check("g173: السبب النهائي (الترتيب) محفوظ ولا script",
              "الترتيب" in d173["script_error"] and not d173.get("script"), d173.get("script_error"))
        calls.clear()
        queue[:] = [{"title": "ع", "question": "س؟", "scenes": bad_scenes},
                    {"title": "ع", "question": "س؟", "scenes": good_scenes()}]
        d173b = new_draft("e3e3e3e3e3e3")
        reel_script.write_for_draft(d173b, topic, points, "", unresolved, cfg)
        check("g173: الإعادة الناجحة تُقبل (نداءان وready)", len(calls) == 2 and d173b["script_status"] == "ready")
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
        check("g178: التعليق «سيُركَّب الريل حين تُفعَّل مرحلة التركيب»",
              any("سيُركَّب الريل حين تُفعَّل مرحلة التركيب" in m for m in run1), run1)
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
