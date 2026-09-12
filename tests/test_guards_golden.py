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
