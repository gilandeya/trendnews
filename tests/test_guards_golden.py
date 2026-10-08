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
    check("(g87) rules_version 4", res["rules_version"] == 4, res["rules_version"])


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

    (d1, why1, _t), rig1 = run_write(items[0], [_b2_body(120), _b2_body(330)])
    check("(g91) 120 كلمة ← رفض وإعادة كتابة واحدة بذكر العلّة ثم مسودة",
          d1 is not None and len(rig1.calls) == 2 and "عدد كلمات" in rig1.calls[1]["prompt"]
          and "عدد كلمات" not in rig1.calls[0]["prompt"], (why1, len(rig1.calls)))
    check("(g91) المسودة: ثلاثة عناوين، بطاقة important لـverified، والحقول article_kind/point_ids/main_story/gap_sources",
          d1 and len(d1["headlines"]) == 3 and cards.card_origin(d1) == "important" and d1["origin"] == "important"
          and d1["article_kind"] == "verified" and d1["point_ids"] == items[0]["point_ids"]
          and d1["main_story"] == result["main_story"] and d1["gap_sources"] == gap_src
          and d1["point_id"] == items[0]["id"], d1 and {k: d1.get(k) for k in ("article_kind", "point_ids")})
    check("(g91) تعليمات الكاتب: 300 إلى 450 كلمة والخبر الرئيسي ومقتطفا BBC وState Department في المدخل",
          "300 إلى 450 كلمة" in rig1.calls[0]["prompt"] and result["main_story"] in rig1.calls[0]["prompt"]
          and "بي بي سي: تفصيل مؤكد" in rig1.calls[0]["prompt"]
          and "الخارجية: بيان رسمي" in rig1.calls[0]["prompt"], rig1.calls[0]["prompt"][:300])
    (d2, why2, _t), rig2 = run_write(items[0], [_b2_body(330, extra="وتعدّ BBC هذه الخطوة تصعيدًا خطيرًا.")])
    check("(g91) «وتعدّ BBC…» ← رفض في المحاولات الثلاث (important.article_write_attempts) وفشل كتابة بسبب حكم الوسيلة",
          d2 is None and len(rig2.calls) == 3 and "حكم منسوب إلى وسيلة" in why2, (why2, len(rig2.calls)))
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

    # ── g97) 120 كلمة في المحاولات الثلاث ← فشل كتابة وأثر على العنصر ──
    (d97, why97, tech97), _r, it97 = run("verified", [_b2_body(120)])
    check("(g97) فشل كتابة (لا مسودة ولا عطل تقني) بسبب الطول",
          d97 is None and not tech97 and "عدد كلمات" in why97, why97)
    check("(g97) على العنصر last_attempt: النص والسبب (يذكر الطول) وgap_sources محفوظة",
          it97.get("last_attempt", {}).get("post_body") == _b2_body(120)
          and "عدد كلمات" in it97["last_attempt"]["reason"] and it97["last_attempt"]["post_title"] == good["post_title"]
          and it97.get("gap_sources") == gap, it97.get("last_attempt"))

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
