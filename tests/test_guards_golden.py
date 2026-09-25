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

from tests.helpers import check, load_config, evidence, store, DRAFTS_DIR


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
