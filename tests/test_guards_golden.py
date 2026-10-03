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
                           ImportantWriteRig, important_doc, important_fixture_point,
                           important_good_data, important_marked_body, important_point,
                           important_stance, important_synthetic_point)


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
        analysis_line = "تحليل لتغطية CNN Türk وHalk TV"
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
        check(f"({name}) المسودة لا تُقبل: لا مسودة ولا قضية مرحلة 2 والنقطة «selected» بسبب الكتابة الفاشلة",
              draft is None and rig.created == [] and saved["status"] == "selected"
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
    for n in (36, 37, 38, 39):
        important.saved_path(96000 + n).unlink(missing_ok=True)
