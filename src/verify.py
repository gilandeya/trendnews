"""تحقّق من مقال ملصق: استخراج ادعاءاته والبحث عنها في مصادر مستقلة.

المرحلة الأولى من مسار التحقق: بحث وتقرير فقط — لا صياغة منشور هنا.
المقال الملصق مصدر إلهام لا معلومة: كل حكم في التقرير مبني على ما وجده
البحث في مصدر مستقل عنه، لا على نصه هو ولا على معرفة النموذج السابقة.

    python -m src.verify --issue 132
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re

from anthropic import Anthropic, APIError

from . import evidence, extract, review
from .config import env, load_config
from .evidence import (
    DEFAULT_PUBLISHER_WEIGHT,
    EVIDENCE_FULL_TEXT,
    EVIDENCE_HEADLINES_ONLY,
    EVIDENCE_NO_RESULTS,
    EVIDENCE_UNREADABLE,
    REFERENCE_MAX_AGE_HOURS,
    TRUSTED_PUBLISHER_WEIGHT,
    _canonical_name,
    _entities_text,
    _known_only,
    _publisher_weight,
    _TASHKEEL_RE,
    build_query,
    build_query_for_claim,
    gather_evidence,
    search,
)
from .request import norm_tokens
from .writer import _extract_json, record_usage, usage_summary

log = logging.getLogger("verify")

CLAIM_KINDS = ["واقعة", "رأي", "تنبؤ"]

STATUS_CONFIRMED = "مؤكدة"
STATUS_CONFIRMED_DISPUTED = "مؤكَّدة مع اعتراض مصدر"
STATUS_NEAR_CONFIRMED = "شبه مؤكَّدة — مصدر واحد قوي"
STATUS_SINGLE = "مصدر واحد"
STATUS_NONE = "لا مصدر"
STATUS_CONTRADICTED = "يخالفها مصدر"

# العلاج 4 (Issue #132 تعليق لاحق): عتبة min_confirm_sources الصلبة تقلب
# الحكم كليًا لأدنى فارق مصدر — واقعة أيّدتها بلومبرغ وحدها تظهر "مصدر
# واحد" نفسها التي تظهرها واقعة أيّدها موقع مجهول واحد، فيختفي فارق واضح في
# قوة السند. NEAR_CONFIRM_DEFAULT_MIN_WEIGHT عتبة وزن ناشر (قابلة للتحكم عبر
# verify.near_confirm_min_weight) تفرّق الحالتين — ناشر معروف في sources أو
# trusted_boost (وزنه أعلى من DEFAULT_PUBLISHER_WEIGHT الافتراضي لناشر
# مجهول) يستحق تصنيفًا وسيطًا لا مصدر واحد مبهمة.
#
# القيمة 1.0 لا تتحقق عمليًا (Issue #132 تعليق لاحق تالٍ): وزن sources في
# config.yaml يتوزّع فعليًا بين 0.7 و1.3 — عتبة 1.0 كانت تستبعد ناشرين
# مُدرَجين فعلًا بوزن متواضع (0.7-0.9، أكثر من نصف القائمة) فتعاملهم كناشر
# مجهول تمامًا رغم كونهم معروفين. العتبة الواقعية المبنية على هذا التوزيع
# الفعلي: أي قيمة بين DEFAULT_PUBLISHER_WEIGHT (0.6، وزن الناشر المجهول
# تمامًا) وأدنى وزن مُدرَج فعليًا في sources (0.7) — 0.65 هنا — تفرّق تمامًا
# بين "ناشر معروف" (أي وزن > 0.6، سواء من sources أو trusted_boost) و"ناشر
# مجهول تمامًا" (الوزن الافتراضي 0.6 بالضبط)، بدل عتبة عشوائية قد تستبعد
# ناشرين معروفين فعليًا كما فعلت 1.0.
NEAR_CONFIRM_DEFAULT_MIN_WEIGHT = 0.65


# ──────────────────────────── استخراج بنية المقال ────────────────────────────

EXTRACT_SYSTEM = """أنت محلل تحقق (fact-checker) يقرأ مقالًا ملصَقًا لاستخراج
بنيته فقط — لا تحكم على صحته الآن، فذلك يأتي بعد بحث لاحق في مصادر مستقلة.

استخرج:
1. topic: جملة واحدة تلخّص موضوع المقال كما فهمته أنت، لا كما كتبه المقال.
2. claims: كل ادّعاء محدد يحمل معلومة، مصنّفًا:
   - "واقعة": حدث أو رقم أو تصريح يمكن التحقق من وقوعه في مصدر مستقل
   - "رأي": تحليل أو تفسير أو موقف لا واقعة قائمة بذاتها
   - "تنبؤ": توقع لما سيحدث مستقبلًا
   ولكل ادّعاء أيضًا entities: 3-5 كيانات مميِّزة منه فقط — أسماء أعلام،
   أرقام، سنوات، أماكن. الكيانات، على عكس text، تُنقل من المقال **كما وردت
   فيه حرفيًا بلا أي إعادة صياغة** — استعلام البحث سيُبنى منها وحدها،
   فإعادة صياغتها بحرية (كما يُعاد صياغة text) تُغيّر الاستعلام عند كل
   استخراج جديد لنفس الحقيقة، بينما ثباتها الحرفي يبقي الاستعلام ثابتًا
   مهما تغيّرت صياغة text نفسها.
   ولكل ادّعاء أيضًا is_qualifier: true إن كان الادّعاء مُحدِّد إسناد أو
   يقين يصف *كيف* وقع حدث آخر — لا الحدث نفسه: "رسميًا"، "تأكيدًا"، "بحسب
   بيان رسمي"، "صراحة"، "بشكل معلن". حين يحمل حدث في المقال مُحدِّدًا كهذا،
   استخرج الحدث نفسه كادّعاء منفصل بـ is_qualifier: false، والمُحدِّد
   كادّعاء ثانٍ قائم بذاته بـ is_qualifier: true — لا ادّعاءً واحدًا يخلط
   الفعل بمُحدِّده. مثال: "مصر تدرس رسميًا الانضمام" يصير ادّعاءين: "مصر
   تدرس الانضمام" (is_qualifier: false) و"الدراسة معلَنة رسميًا من مصر"
   (is_qualifier: true) — لا ادّعاءً مركّبًا واحدًا. السبب: كل جزء يُحكَم
   عليه لاحقًا بمعزل عن الآخر مقابل مصادر مستقلة؛ فمصدر يؤيد وقوع الحدث
   نفسه دون تأييد رسميته لا يجوز أن يُحسب مؤيدًا لادّعاء مركّب يخلط
   الاثنين. حدث بلا أي مُحدِّد إسناد فعلي في المقال يعني is_qualifier:
   false لكل ادّعاءاته بلا استثناء — لا تخترع مُحدِّدًا لم يذكره المقال.
   ولكل ادّعاء أيضًا is_reference: true إن كانت حقيقته ثابتة لا تتعلق
   بدورة الأخبار الحالية — سنة صدور كتاب، تاريخ توقيع معاهدة، معلومة
   تاريخية أو سيرة ذاتية، إحصاء رسمي قديم منشور... لا حدث جارٍ أو تصريح
   حديث. الفارق عملي لا نظري: مصدر يؤيّد واقعة مرجعية كهذه غالبًا نصّ
   قديم بعمر الواقعة نفسها لا مقال حديث، فبحث يقيّد النتائج بنافذة زمنية
   قصيرة (آخر أيام أو أسابيع) لن يجد شيئًا مهما صحّت الواقعة — "لا نتائج
   بحث" حينها حكم مضلِّل لا دليل نفي. أي ادّعاء آخر (حدث جارٍ، تصريح، رقم
   من الشهر الحالي...) يعني is_reference: false.
3. questions: أسئلة يثيرها المقال ولا يجيب عنها هو نفسه — فجوات في الرواية
   تستحق بحثًا مستقلًا، لا أسئلة بلاغية.

لا تنقل جملة من المقال حرفيًا: أعد صياغة كل ادّعاء وسؤال بإيجاز يكفي لبناء
استعلام بحث منه (فيما عدا entities: تُنقل حرفيًا كما هي، لا تُعاد صياغتها
أبدًا). لا تُجب عن الأسئلة من معرفتك — استخرجها فقط، فالبحث سيتولى الإجابة.

كل عنصر في claims يجب أن يكون كائنًا {"text": ..., "kind": ..., "entities":
[...], "is_qualifier": ..., "is_reference": ...} — لا نصًا مجردًا أبدًا، حتى
لو بدا ذلك مختصرًا. مثال دقيق على الشكل المطلوب:
{
  "topic": "ارتفاع أسعار الوقود وتأثيره على النقل",
  "claims": [
    {"text": "ارتفعت أسعار الوقود بنسبة 12٪ الشهر الماضي", "kind": "واقعة",
     "entities": ["12٪", "الوقود"], "is_qualifier": false, "is_reference": false},
    {"text": "الارتفاع نتيجة سياسات حكومية غير مدروسة", "kind": "رأي",
     "entities": ["سياسات حكومية"], "is_qualifier": false, "is_reference": false},
    {"text": "الأسعار ستتضاعف خلال عام", "kind": "تنبؤ", "entities": ["عام"],
     "is_qualifier": false, "is_reference": false}
  ],
  "questions": ["ما مصدر البيانات التي استند إليها المقال في نسبة الارتفاع؟"]
}
لا تُعِد claims أو questions كقائمة نصوص مجردة أو بشكل مختلف عن هذا أبدًا."""

EXTRACT_SCHEMA = {
    "name": "extract_claims",
    "description": "يستخرج بنية مقال: موضوعه ووقائعه وأسئلته المفتوحة",
    "input_schema": {
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "kind": {"type": "string", "enum": CLAIM_KINDS},
                        "entities": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": ("3-5 كيانات مميِّزة (أسماء أعلام، "
                                            "أرقام، سنوات، أماكن) كما وردت في "
                                            "المقال حرفيًا بلا إعادة صياغة"),
                        },
                        "is_qualifier": {
                            "type": "boolean",
                            "description": ("true إن كان هذا ادّعاء مُحدِّد "
                                            "إسناد/يقين (رسميًا، تأكيدًا، "
                                            "بحسب بيان رسمي...) منفصلًا عن "
                                            "ادّعاء الحدث نفسه، لا الحدث "
                                            "بذاته"),
                        },
                        "is_reference": {
                            "type": "boolean",
                            "description": ("true إن كانت حقيقة الادّعاء "
                                            "ثابتة لا تتعلق بدورة الأخبار "
                                            "الحالية (سنة صدور كتاب، تاريخ "
                                            "معاهدة، معلومة تاريخية...) — "
                                            "بحثها لا يُقيَّد بنافذة زمنية "
                                            "قصيرة"),
                        },
                    },
                    "required": ["text", "kind", "entities", "is_qualifier",
                                "is_reference"],
                },
            },
            "questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["topic", "claims", "questions"],
    },
}


def _as_text(value) -> str:
    """يستخرج نصًا من قيمة قد تكون نصًا أو قاموسًا بحقل نصي — بلا افتراض شكل.
    قائمة أسماء الحقول موسّعة (Issue #132 تعليق لاحق) لتقبل أسماء بديلة
    شائعة يستعملها النموذج أحيانًا رغم مخطط الأداة."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "claim", "question", "content", "statement",
                    "fact", "description", "title"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return ""


# أسماء حقول بديلة شائعة يقبلها كل حقل رئيسي في رد الاستخراج (Issue #132
# تعليق لاحق: رد بـ 1858 توكن إخراج ضاع بصمت لأن حقل claims وصل باسم آخر —
# فالتزام النموذج بأسماء مخطط الأداة ليس مضمونًا حتى مع tool_choice إجباري)
TOPIC_ALT_KEYS = ("topic", "title", "subject", "headline", "main_topic")
CLAIMS_ALT_KEYS = ("claims", "facts", "statements", "assertions")
QUESTIONS_ALT_KEYS = ("questions", "open_questions", "unanswered_questions")


def _first_present(data: dict, keys: tuple[str, ...]):
    """يعيد أول قيمة موجودة تحت أي من الأسماء البديلة لحقل، أو None إن غاب
    الحقل تمامًا تحت كل الأسماء المعروفة."""
    for key in keys:
        if key in data:
            return data[key]
    return None


def _coerce_json_string(value):
    """قيمة قد تصل نصًا مكتوبًا بصيغة JSON بدل الكائن/القائمة الفعليين —
    النموذج أحيانًا يُعيد ترميز جزء من البنية كسلسلة نصية بدل توزيعه على
    حقول الأداة (Issue #132 تعليق لاحق). نحاول تحليلها كـ JSON قبل رفضها
    كليًا؛ فشل التحليل يعيد القيمة كما وصلت بلا تغيير."""
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in "[{":
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _recover_stuffed_json(extracted: dict) -> dict:
    """احتياط لعطل رُصد فعليًا (Issue #132 تعليق لاحق): النموذج حشر بنية
    الرد الكاملة (topic + claims + questions) داخل حقل claims وحده، كنص
    يبدأ بمصفوفة الادّعاءات ثم يتبعها بقية الحقول — أي أن الحرف `{`
    الافتتاحي للكائن الكامل غاب من رد النموذج نفسه، لا من تحليلنا له.
    نحاول إعادة بناء الكائن الكامل من ذلك النص بإضافة اسم الحقل والقوس
    الناقصين قبل رفضه؛ الحقول الأخرى غير المتأثرة (لو وُجدت) تُستبدل بما
    يحمله الحقل المحشور، فهو الأحدث وربما الأكمل."""
    for key, value in extracted.items():
        if not isinstance(value, str):
            continue
        text = value.strip()
        if text[:1] not in "[{":
            continue
        candidates = [text]
        if text[:1] == "[":
            candidates.append(f'{{"{key}": {text}')
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and len(parsed) > 1:
                log.warning(
                    "تعافيت من بنية محشورة في حقل %r وحده — الحقول بعد "
                    "إعادة البناء: %s", key, sorted(parsed.keys()))
                return parsed
    return extracted


def _as_entities(value) -> list[str]:
    """يطبّع حقل entities (العلاج 2، Issue #132 تعليق لاحق): قائمة نصوص فقط
    تُقبل — أي شكل آخر (غياب، نص مفرد، عناصر غير نصية) يُعامَل كقائمة فارغة
    بلا انهيار. قائمة فارغة تعني سقوط build_query_for_claim لبناء الاستعلام
    من نص الادّعاء كاملًا، كما كان سلوكها قبل هذا العلاج."""
    if not isinstance(value, list):
        return []
    return [e.strip() for e in value if isinstance(e, str) and e.strip()]


def _as_is_qualifier(value) -> bool:
    """يطبّع حقل is_qualifier (البند 1، Issue #339): True صريحة فقط تُقبل —
    أي شكل آخر (غياب، نص، رقم) يُعامَل كـ False. هذا يعني أن ردًا لم يلتزم
    بالحقل الجديد (نموذج أقدم، أو رد لم يتبع المخطط) يعامل كل ادّعاءاته
    كأحداث لا مُحدِّدات، وهو السلوك قبل هذا الحقل بالضبط — لا انهيار ولا
    فصل زائف."""
    return value is True


def _as_is_reference(value) -> bool:
    """يطبّع حقل is_reference (البند 5، تعليق التنفيذ على PR #340): True
    صريحة فقط تُقبل، بنفس منطق _as_is_qualifier — رد لم يلتزم بالحقل
    الجديد يعامل كل ادّعاءاته كأخبار جارية لا وقائع مرجعية، وهو سلوك
    البحث المقيَّد بنافذة زمنية قبل هذا الحقل بالضبط."""
    return value is True


def normalize_claim(item) -> dict | None:
    """يطبّع عنصر ادّعاء واحدًا من رد النموذج، الذي قد يخالف مخطط الأداة
    (Issue #134: النموذج أعاد claims كقائمة نصوص لا كقائمة قواميس):
    نص مجرد يصير {"text": النص, "kind": "واقعة", "entities": [],
    "is_qualifier": False, "is_reference": False}؛ قاموس بحقل kind غائب أو
    غير معروف يُملأ بالقيمة نفسها. عنصر بلا نص قابل للاستخراج يُستبعد."""
    text = _as_text(item)
    if not text:
        return None
    kind = item.get("kind") if isinstance(item, dict) else None
    if kind not in CLAIM_KINDS:
        kind = "واقعة"
    entities = _as_entities(item.get("entities")) if isinstance(item, dict) else []
    is_qualifier = _as_is_qualifier(
        item.get("is_qualifier")) if isinstance(item, dict) else False
    is_reference = _as_is_reference(
        item.get("is_reference")) if isinstance(item, dict) else False
    return {"text": text, "kind": kind, "entities": entities,
            "is_qualifier": is_qualifier, "is_reference": is_reference}


def normalize_claims(raw) -> list[dict]:
    raw = _coerce_json_string(raw)
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        norm = normalize_claim(item)
        if norm:
            out.append(norm)
    return out


def normalize_question(item) -> str | None:
    """سؤال قد يصل نصًا مجردًا (الشكل المطلوب) أو قاموسًا — كلاهما مقبول."""
    text = _as_text(item)
    return text or None


def normalize_questions(raw) -> list[str]:
    raw = _coerce_json_string(raw)
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        norm = normalize_question(item)
        if norm:
            out.append(norm)
    return out


def _client() -> Anthropic:
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def _response_preview(resp) -> str:
    """يبني معاينة نصية من رد النموذج للتسجيل عند الفشل — لا للنشر."""
    parts = []
    for block in resp.content:
        kind = getattr(block, "type", "")
        if kind == "text":
            parts.append(block.text)
        elif kind == "tool_use":
            parts.append(json.dumps(block.input, ensure_ascii=False))
    return "".join(parts)


def extract_claims(article_text: str, cfg, retries: int = 3) -> tuple[dict | None, str | None]:
    """يستخرج بنية المقال. يرجع (data, None) عند النجاح، أو (None, سبب محدد)
    عند الفشل — السبب يصل لتقرير الـ Issue بدل "حاول مجددًا" المبهمة، بينما
    تفاصيل الرد الكاملة (أول 500 حرف) تُسجَّل في السجل فقط لا في التعليق."""
    vcfg = cfg.get("verify", {}) or {}
    model = vcfg.get("model", "claude-sonnet-5")
    max_tokens = int(vcfg.get("extract_max_tokens", 4000))
    client = _client()

    reason = "تعذّر الاتصال بالنموذج"
    for attempt in range(1, retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                tools=[EXTRACT_SCHEMA],
                tool_choice={"type": "tool", "name": "extract_claims"},
                system=EXTRACT_SYSTEM,
                messages=[{"role": "user", "content": article_text}],
            )
            record_usage(resp, model)
        except APIError as exc:
            log.warning("محاولة %d/%d فشلت في استخراج البنية: %s", attempt, retries, exc)
            reason = "تعذّر الاتصال بالنموذج"
            continue

        if getattr(resp, "stop_reason", "") == "max_tokens":
            # الرد بُتر قبل اكتمال JSON — رفع verify.extract_max_tokens هو
            # الحل، لا إعادة محاولة عبثية (writer.py يتبع النمط نفسه)
            log.error("محاولة %d/%d: استخراج البنية مبتور (max_tokens) — "
                     "أول 500 حرف من الرد: %r",
                     attempt, retries, _response_preview(resp)[:500])
            reason = "الرد مبتور — تجاوز سقف التوكنات"
            continue

        data = next((b.input for b in resp.content
                    if getattr(b, "type", "") == "tool_use"), None)
        if isinstance(data, dict):
            # نسجّل الرد الخام الكامل عند كل نجاح لا الفشل فقط (Issue #132
            # تعليق لاحق: استدعاء ناجح 1858 توكن أنتج تقريرًا فارغًا، ولم يكن
            # هناك سجل يُظهر أسماء الحقول الفعلية التي أعادها النموذج)
            log.info("نجح استخراج البنية — الرد الخام الكامل: %s",
                     json.dumps(data, ensure_ascii=False))
            data = _recover_stuffed_json(data)
            return data, None

        # احتياط: نموذج ردّ نصًا (ربما محاطًا بأسوار ```json```) رغم الأداة
        text = "".join(b.text for b in resp.content
                       if getattr(b, "type", "") == "text")
        try:
            data = _extract_json(text) if text.strip() else None
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            log.info("نجح استخراج البنية (رد نصي) — الرد الخام الكامل: %s",
                     json.dumps(data, ensure_ascii=False))
            data = _recover_stuffed_json(data)
            return data, None

        log.error("محاولة %d/%d: رد استخراج البنية لم يكن JSON صالحًا — "
                 "أول 500 حرف من الرد: %r",
                 attempt, retries, _response_preview(resp)[:500])
        reason = "الرد لم يكن JSON صالحًا"

    log.error("تعذّر استخراج بنية المقال بعد %d محاولات: %s", retries, reason)
    return None, reason


# ──────────────────────────── البحث عن الأدلة ────────────────────────────
# بناء الاستعلام (build_query/build_query_for_claim)، والبحث والقراءة
# (search/gather_evidence)، وثوابت evidence_basis: انتقلت إلى src/evidence.py
# (Issue #348، تعليق الموافقة على التشخيص، البند 1) — عامة بطبيعتها، يستوردها
# هذا الملف أعلاه بلا تعريف مزدوج، ويستهلكها أيضًا src/article.py مباشرة.


# ──────────────────────────── الحكم على الوقائع ────────────────────────────

def _format_evidence(docs: list[dict]) -> str:
    """يصوغ نصوص الأدلة لإدراجها في طلب الحكم، معلَّمة باسم كل مصدر
    وأساس دليله (نص كامل أو عنوان وملخص فقط عند تعذّر استخراج النص —
    Issue #132 تعليق لاحق). يختلف عن extract.format_for_prompt بإضافة
    وسم الأساس هذا، فلا يُعاد استعمالها كما هي."""
    if not docs:
        return ""
    blocks = []
    for i, d in enumerate(docs, start=1):
        basis = "نص المقال الكامل" if d.get("from_text", True) else \
            "عنوان الخبر وملخصه فقط — لا نص المقال الكامل"
        blocks.append(f"--- المصدر {i}: {d['name']} ({basis}) ---\n{d['text']}")
    return "\n\n".join(blocks)


JUDGE_FACT_SYSTEM = """أنت تقارن ادّعاءً بنصوص مصادر مستقلة عن الحدث نفسه.
لكل نص مصدر معطى حدّد: هل يؤيد الادّعاء صراحة، أم يخالفه صراحة، أم لا علاقة
له به.

قواعد صارمة:
- احكم من النصوص المعطاة فقط. لا تستخدم معرفتك الخاصة عن الموضوع.
- التأييد يعني أن النص يذكر المعلومة نفسها أو ما يقاربها بوضوح، لا مجرد
  ذكر الموضوع العام دون التفصيلة المدّعاة.
- مُحدِّدات الإسناد أو اليقين في الادّعاء نفسه (رسميًا، تأكيدًا، بحسب بيان
  رسمي، صراحة، بشكل معلن...) تفصيلة يجب تأييدها صراحة تمامًا كأي رقم أو
  تاريخ — لا فارقًا شكليًا في الصياغة يُتسامح معه. مصدر يذكر توقعًا أو
  ترجيحًا من طرف ثالث، أو يسند الخبر لمصدر غير رسمي، لا يؤيد ادّعاءً يصفه
  المصدر بـ"رسميًا" أو "تأكيدًا" أو ما شابه.
- المخالفة تعني تناقضًا حقيقيًا (رقم مختلف بوضوح، نفي صريح) لا فارقًا شكليًا
  في الصياغة أو الوحدة أو رقمًا محدَّثًا مقابل رقم قديم.
- مصدر لم يذكر الادّعاء إطلاقًا لا يُحسب مؤيدًا ولا مخالفًا.
- مصدر معلَّم "عنوان وملخص فقط" نصه قصير وقد يبسّط أو يبالغ — لا تعتبره
  تأييدًا لتفصيلة دقيقة (رقم، تاريخ...) لم يذكرها العنوان صراحة بنفس الدقة.
- أخرج اسم المصدر مجردًا تمامًا كما ورد في وسم "--- المصدر: <الاسم> ---"
  فقط — بلا أي إضافة أو وصف بين قوسين أو غيره (مثل "(نص المقال الكامل)")،
  وبلا اختراع أسماء جديدة."""

JUDGE_FACT_SCHEMA = {
    "name": "judge_claim",
    "description": "يحدد أي المصادر المعطاة يؤيد الادّعاء أو يخالفه",
    "input_schema": {
        "type": "object",
        "properties": {
            "supporting": {"type": "array", "items": {"type": "string"}},
            "contradicting": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["supporting", "contradicting"],
    },
}


# مطابقة أسماء المصادر (_tokens_match/_canonical_name/_known_only) ووزن
# الناشر (_publisher_weight): انتقلت إلى src/evidence.py مع بقية محرك
# البحث والقراءة (Issue #348، تعليق الموافقة على التشخيص، البند 1).


def judge_fact(claim_text: str, docs: list[dict], cfg, retries: int = 2) -> dict:
    """يعيد {"supporting":[...], "contradicting":[...], "call_error": None}
    عادةً. استنفاد كل المحاولات بسبب فشل نداء تقني (لا رد نموذج فارغ/حكم
    شرعي) يعيد call_error بنص آخر استثناء — تفريق عن «لا سند» فعلي (تشخيص
    Issue #373، الجولة الحادية عشرة، البند 2: كلاهما كان يظهر بنفس
    supporting=[] المجرَّدة في التقرير)."""
    vcfg = cfg.get("verify", {}) or {}
    model = vcfg.get("model", "claude-sonnet-5")
    client = _client()
    prompt = (f"الادّعاء: {claim_text}\n\n"
             f"نصوص المصادر:\n\n{_format_evidence(docs)}")

    last_error: str | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=500,
                tools=[JUDGE_FACT_SCHEMA],
                tool_choice={"type": "tool", "name": "judge_claim"},
                system=JUDGE_FACT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                # لا تُضِف temperature: نماذج هذا المشروع ترفضها بـ400
                # ("temperature is deprecated for this model") — Issue #373،
                # الجولة الحادية عشرة.
            )
            record_usage(resp, model)
            data = next((b.input for b in resp.content
                        if getattr(b, "type", "") == "tool_use"), None)
            if data is not None:
                supporting = _known_only(data.get("supporting"), docs)
                contradicting = _known_only(data.get("contradicting"), docs)
                # تسجيل دائم لا عند الفشل فقط (Issue #132 تعليق لاحق: طُلب
                # توفره حتى لو لم يكن هو سبب عطل بعينه، لتشخيص أي تذبذب
                # مستقبلي — رد النموذج الحرفي، وأسماء docs المعطاة له، وما
                # بقي بعد استبعاد الأسماء المختلَقة — من السجل مباشرة بلا
                # تخمين في الجولة القادمة)
                log.info(
                    "حكم واقعة %r — رد النموذج الحرفي: supporting=%s "
                    "contradicting=%s؛ أسماء المصادر المعطاة: %s؛ بعد "
                    "_known_only: supporting=%s contradicting=%s",
                    claim_text[:80], data.get("supporting"), data.get("contradicting"),
                    sorted(d["name"] for d in docs), supporting, contradicting)
                return {"supporting": supporting, "contradicting": contradicting,
                        "call_error": None}
        except APIError as exc:
            last_error = str(exc)
            log.warning("محاولة %d/%d فشلت في الحكم على واقعة: %s", attempt, retries, exc)
    return {"supporting": [], "contradicting": [], "call_error": last_error}


def classify_fact(supporting: list[str], contradicting: list[str],
                  min_confirm: int, weights: dict[str, float] | None = None,
                  near_confirm_min_weight: float = NEAR_CONFIRM_DEFAULT_MIN_WEIGHT) -> str:
    """
    التصنيف بكود لا بالنموذج: النموذج يحدد من أيّد ومن خالف فقط، والعدّ
    يحدّد الحكم — فلا يقع الحكم النهائي رهن صياغة النموذج له في كل استدعاء.

    العلاج 4 (Issue #132 تعليق لاحق): حين تكون الواقعة عند حافة العتبة —
    مصدر واحد فقط مؤيّد لا مصدران — نميّز بين مصدر واحد "قوي" (وزنه ≥
    near_confirm_min_weight، أي معروف في sources أو trusted_boost) ومصدر
    واحد مجهول الوزن الافتراضي: الأول STATUS_NEAR_CONFIRMED لا STATUS_SINGLE
    المبهمة، فالتقرير يعكس فارق قوة السند بدل إخفائه خلف "مصدر واحد" واحدة
    لكلتا الحالتين. weights غائب (توافقًا خلفيًا) يعني عدم وجود أي مصدر
    "قوي" معروف — كل مصدر واحد يبقى STATUS_SINGLE كما كان قبل هذا العلاج.
    لا يغيّر هذا الحكم النهائي: الواقعة لا تزال تحتاج min_confirm مصادر
    فعلية لتُصبح "مؤكَّدة".

    البند 2 (تعليق التنفيذ على Issue #339): واقعة بلغت min_confirm مصادر
    مؤيِّدة كانت تُعاد STATUS_CONFIRMED فورًا بلا أي فحص لـ contradicting —
    فواقعة أيّدها مصدران وخالفها ثالث كانت تدخل مسار المسودة بصمت بلا أي
    أثر للاعتراض. القاعدة 3 («المؤكَّد وحده يدخل المسودة») تعني أن
    المعترَض عليه ليس مؤكَّدًا رغم كفاية العدد، فحالة رابعة صريحة
    STATUS_CONFIRMED_DISPUTED تحمل هذا الفارق في التقرير، وتُستبعد تلقائيًا
    من مسار verify_draft.attempt (يفلتر status == STATUS_CONFIRMED حرفيًا،
    فلا يشمل هذه الحالة الجديدة بلا أي تعديل إضافي هناك).

    البند 4 (تعليق التنفيذ على PR #340): بلوغ min_confirm مصادر لا يكفي
    وحده لـ"مؤكَّدة" إن كانت كلها مجهولة الوزن — شرط إضافي: مصدر واحد
    معروف (وزنه ≥ near_confirm_min_weight) على الأقل بين المؤيِّدين،
    بإعادة استعمال العتبة نفسها المستعملة أعلاه للحالة الوسيطة بدل عتبة
    مجموع أوزان منفصلة. حد أدنى للمجموع كان سيسمح لعدد كافٍ من مصادر
    مجهولة بتعويض غياب أي مصدر معروف فعليًا (ثلاثة مصادر مجهولة، كل منها
    بالوزن الافتراضي 0.6، مجموعها 1.8 يتجاوز أي عتبة معقولة رغم كونها
    كلها مجهولة الهوية) — بينما شرط "مصدر معروف واحد" يفحص هوية السند لا
    كمّه. عدد كافٍ بلا أي مصدر معروف ينزل لـSTATUS_NEAR_CONFIRMED لا
    STATUS_SINGLE: العدد نفسه سند أقوى من مصدر واحد مبهم، لكنه دون يقين
    STATUS_CONFIRMED الكامل. weights غائب (توافقًا خلفيًا) يعني عدم وجود
    أي مصدر معروف — يسري هذا الشرط حتى حين لا قاموس أوزان أصلًا.
    """
    unique_supporting = set(supporting)
    weights = weights or {}
    if len(unique_supporting) >= min_confirm:
        has_known_source = any(weights.get(name, 0.0) >= near_confirm_min_weight
                               for name in unique_supporting)
        if has_known_source:
            return STATUS_CONFIRMED_DISPUTED if contradicting else STATUS_CONFIRMED
        if not contradicting:
            return STATUS_NEAR_CONFIRMED
    if contradicting:
        return STATUS_CONTRADICTED
    if len(unique_supporting) == 1:
        weight = weights.get(next(iter(unique_supporting)), 0.0)
        if weight >= near_confirm_min_weight:
            return STATUS_NEAR_CONFIRMED
        return STATUS_SINGLE
    if unique_supporting:
        return STATUS_SINGLE
    return STATUS_NONE


# ──────────────────────────── الحكم على الأسئلة ────────────────────────────

JUDGE_QUESTION_SYSTEM = """أنت تبحث في نصوص مصادر مستقلة عن جواب لسؤال أثاره
مقال آخر. أجب فقط إن وجدت الجواب صراحة في النصوص المعطاة، ولا تستخدم معرفتك
الخاصة عن الموضوع مهما بدت لك صحيحة. انسب الجواب لمن قاله في المصدر — لا
تصغه كحقيقة مطلقة من عندك. مصدر معلَّم "عنوان وملخص فقط" نصه قصير — لا تبنِ
عليه جوابًا تفصيليًا لم يذكره صراحة بنفس الدقة. اكتب اسم المصدر في source
مجردًا تمامًا كما ورد في وسمه، بلا أي إضافة أو وصف بين قوسين أو غيره."""

JUDGE_QUESTION_SCHEMA = {
    "name": "answer_question",
    "description": "يجيب عن سؤال من نصوص مصادر معطاة فقط، أو يقر بغياب الجواب",
    "input_schema": {
        "type": "object",
        "properties": {
            "answered": {"type": "boolean"},
            "answer": {"type": "string"},
            "source": {"type": "string"},
        },
        "required": ["answered"],
    },
}


def judge_question(question: str, docs: list[dict], cfg, retries: int = 2) -> dict:
    vcfg = cfg.get("verify", {}) or {}
    model = vcfg.get("model", "claude-sonnet-5")
    client = _client()
    prompt = (f"السؤال: {question}\n\n"
             f"نصوص المصادر:\n\n{_format_evidence(docs)}")

    for attempt in range(1, retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=400,
                tools=[JUDGE_QUESTION_SCHEMA],
                tool_choice={"type": "tool", "name": "answer_question"},
                system=JUDGE_QUESTION_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            record_usage(resp, model)
            data = next((b.input for b in resp.content
                        if getattr(b, "type", "") == "tool_use"), None)
            if data is not None:
                # نفس المطابقة المتسامحة المستعملة لأسماء الوقائع
                # (_canonical_name) — العطل نفسه ممكن هنا: مصدر مؤيد فعليًا
                # لكن باسم مذيَّل بوصف بين قوسين (Issue #132 تعليق لاحق)
                canonical_source = _canonical_name(data.get("source"), docs)
                return {
                    "answered": bool(data.get("answered")) and canonical_source is not None,
                    "answer": str(data.get("answer") or ""),
                    "source": canonical_source or "",
                }
        except APIError as exc:
            log.warning("محاولة %d/%d فشلت في الإجابة عن سؤال: %s", attempt, retries, exc)
    return {"answered": False, "answer": "", "source": ""}


# ──────────────────────────── التنسيق الكامل ────────────────────────────


def _fact_sources(names: list[str], docs: list[dict], ranked: list[Article]) -> list[dict]:
    """يحتفظ بمقتطف/رابط/صور كل مصدر مؤيِّد فعليًا لواقعة، بدل أن تُهدر docs
    بعد judge_fact كما كانت (Issue #334 نقطة 1 من الموافقة). حقل بيانات
    فقط، لا حكم — لا يمسّ classify_fact ولا أي عتبة تصنيف. يستهلكه
    verify_draft.py لاحقًا لبناء مسودة من المؤكَّد وحده.

    صور كل مصدر تُؤخذ من الممثّل (Article) الذي يحمل اسمه في `ranked` —
    أعضاء cluster_members لا يحملون صورًا خاصة بهم، فمصدر مندمج في مجموعة
    ممثَّلة بغيره قد يعود بقائمة صور فارغة هنا؛ هذا تقريب مقبول (يسقط
    verify_draft.py لبديل البحث الحر عند فراغها) لا اختراع لصورة لا نملكها."""
    docs_by_name = {d["name"]: d for d in docs}
    images_by_name: dict[str, list[str]] = {}
    for a in ranked:
        # getattr لا وصول مباشر: بعض الاختبارات تمرّر عناصر مؤقتة غير
        # Article إلى search() المزيَّفة (فقط لتفعيل مسار القراءة) — صور
        # مفقودة هنا تُعامَل كقائمة فارغة (يسقط verify_draft.py لاحقًا لبديل
        # البحث الحر)، لا انهيارًا في مسار لا يمسّ أي حكم أصلًا
        name = getattr(a, "publisher", "") or getattr(a, "source_name", "")
        if name and name not in images_by_name:
            images_by_name[name] = getattr(a, "image_candidates", None) or []

    out = []
    for name in names:
        doc = docs_by_name.get(name)
        if not doc:
            continue
        out.append({
            "name": name,
            "link": doc.get("link", ""),
            "text": doc.get("text", ""),
            "image_candidates": images_by_name.get(name, []),
        })
    return out


def verify_article(body: str, cfg) -> dict:
    """يلتقط أي انهيار غير متوقع (رد نموذج بشكل لم يُتوقَّع رغم التطبيع، خطأ
    شبكة لم يُلتقط في طبقة أدنى...) فلا يصل traceback إلى تعليق الـ Issue —
    المستخدم لا يقرأ سجلات Actions."""
    try:
        return _verify_article(body, cfg)
    except Exception:
        log.exception("انهيار غير متوقع أثناء التحقق من المقال")
        return {"ok": False,
                "reason": "حدث خطأ غير متوقع أثناء التحقق — راجع سجلات Actions للتفاصيل"}


def _verify_article(body: str, cfg) -> dict:
    vcfg = cfg.get("verify", {}) or {}
    days = int(vcfg.get("days", 14))
    max_claims = int(vcfg.get("max_claims", 8))
    max_questions = int(vcfg.get("max_questions", 5))
    min_confirm = int(vcfg.get("min_confirm_sources", 2))
    query_max_words = int(vcfg.get("query_max_words", 5))
    near_confirm_min_weight = float(
        vcfg.get("near_confirm_min_weight", NEAR_CONFIRM_DEFAULT_MIN_WEIGHT))

    extracted, extract_error = extract_claims(body, cfg)
    if not extracted:
        return {"ok": False, "reason": extract_error or "تعذّر استخراج بنية المقال"}

    raw_topic = _first_present(extracted, TOPIC_ALT_KEYS)
    raw_claims = _first_present(extracted, CLAIMS_ALT_KEYS)
    raw_questions = _first_present(extracted, QUESTIONS_ALT_KEYS)

    claims = normalize_claims(raw_claims)
    if not claims:
        # الاستدعاء نجح ورد النموذج غير فارغ (Issue #132 تعليق لاحق: 1858
        # توكن إخراج)، لكن التطبيع لم يجد ادّعاءً واحدًا صالحًا — سواء لغياب
        # حقل claims/facts/statements تمامًا تحت كل الأسماء المعروفة، أو
        # لعناصر بشكل غريب لا نص فيه. هذا تطبيع أسقط كل شيء، لا نجاحًا
        # صامتًا: تقرير فارغ يبدو مشروعًا أسوأ من فشل صريح يُطلب فيه إعادة
        # المحاولة أو مراجعة السجل.
        log.error("تعذّر تفسير بنية رد الاستخراج رغم نجاح الاستدعاء — "
                 "أسماء الحقول في الرد: %s؛ الرد الكامل: %s",
                 sorted(extracted.keys()),
                 json.dumps(extracted, ensure_ascii=False))
        return {"ok": False, "reason": "تعذّرت قراءة بنية الرد"}

    facts = [c for c in claims if c["kind"] == "واقعة"][:max_claims]
    other_claims = [c for c in claims if c["kind"] != "واقعة"]
    questions = normalize_questions(raw_questions)[:max_questions]

    fact_results = []
    for claim in facts:
        text = claim.get("text", "")
        # الاستعلام يُبنى من entities الادّعاء لا نص text المعاد صياغته —
        # العلاج 2 (Issue #132 تعليق لاحق)، انظر build_query_for_claim
        # واقعة مرجعية (is_reference، البند 5 تعليق التنفيذ على PR #340)
        # تُبحث بلا قيد when: — مصدرها المؤيِّد الفعلي بعمر الواقعة نفسها
        ranked = search(build_query_for_claim(claim, query_max_words), cfg, days,
                        unrestricted=claim.get("is_reference", False))
        # ترتيب صلة القراءة في gather_evidence يعتمد على entities الثابتة
        # أيضًا لا text وحدها (Issue #132 تعليق لاحق تالٍ: نفس نتائج البحث
        # بالضبط رُتِّبت بشكل مختلف جوهريًا بين تشغيلين لنفس المقال لأن
        # gather_evidence كانت تحسب الصلة من claim["text"] المعاد صياغته —
        # الحقل المتذبذب نفسه الذي عولج في الاستعلام أعلاه، لكنه بقي يُستعمل
        # هنا بلا تعديل). entities فارغة تسقط لـtext كما كان قبل هذا الإصلاح.
        relevance_text = _entities_text(claim) or text
        docs, evidence_basis = gather_evidence(ranked, cfg, relevance_text)
        judged = (judge_fact(text, docs, cfg) if docs
                 else {"supporting": [], "contradicting": [], "call_error": None})
        # وزن كل مصدر مؤيد يُعرَض في التقرير (Issue #132 تعليق لاحق): العدد
        # وحده لا يُظهر قوة السند — وكالة كبرى ومصدر مجهول يُحسبان مصدرًا
        # واحدًا لكل منهما رغم فارق الموثوقية. تُحسب قبل التصنيف لأن
        # classify_fact تحتاجها للتمييز بين مصدر واحد "قوي" وآخر مجهول
        # (العلاج 4، STATUS_NEAR_CONFIRMED)
        supporting_weighted = sorted(
            ({"name": n, "weight": _publisher_weight(n, cfg)}
             for n in judged["supporting"]),
            key=lambda s: -s["weight"])
        weights_by_name = {s["name"]: s["weight"] for s in supporting_weighted}
        status = classify_fact(judged["supporting"], judged["contradicting"],
                               min_confirm, weights_by_name, near_confirm_min_weight)
        fact_results.append({
            "text": text,
            "index": len(fact_results),
            "status": status,
            "is_qualifier": claim.get("is_qualifier", False),
            "is_reference": claim.get("is_reference", False),
            "supporting": judged["supporting"],
            "supporting_weighted": supporting_weighted,
            "contradicting": judged["contradicting"],
            "evidence_basis": evidence_basis,
            "sources": _fact_sources(judged["supporting"], docs, ranked),
            # فشل نداء الحكم تقنيًا (لا حكم "لا سند" شرعي) — يُفرَّق صراحة
            # في build_report بدل الظهور بنفس عبارة "لا مصادر مؤيِّدة"
            # (تشخيص Issue #373، الجولة الحادية عشرة، البند 2)
            "judge_error": judged.get("call_error"),
        })

    question_results = []
    for text in questions:
        # legacy_sort=True: هذا الاستدعاء وحده يبني الاستعلام من نص السؤال
        # الخام بلا entities (خلافًا لـ build_query_for_claim أعلاه)، فقد
        # يطول لعشرين كلمة — السلوك الافتراضي الجديد لـbuild_query (حفظ
        # ترتيب الورود) قد يُسقط رقمًا/تاريخًا مميِّزًا يرد متأخرًا في
        # جملة كهذه. verify.py مسار متقاعد ينتظر الحذف (src/article.py
        # يوثّق الاستبدال)، فأُبقي سلوكه القديم هنا خلف هذا المعامل الصريح
        # بدل توسيع مخطط أسئلته بـentities (Issue #361 تعليق الموافقة
        # الثالث، البند 1: أي عمل إضافي في هذا المسار مهدور).
        ranked = search(build_query(text, query_max_words, legacy_sort=True), cfg, days)
        docs, evidence_basis = gather_evidence(ranked, cfg, text)
        judged = (judge_question(text, docs, cfg) if docs
                 else {"answered": False, "answer": "", "source": ""})
        question_results.append({
            "text": text,
            "answered": bool(judged.get("answered")),
            "answer": judged.get("answer", ""),
            "source": judged.get("source", ""),
            "evidence_basis": evidence_basis,
        })

    # اشتقاق مبني على وجود contradicting فعليًا لا على الحالة النهائية وحدها
    # (البند 2، Issue #339): STATUS_CONFIRMED_DISPUTED تحمل contradicting
    # غير فارغة أيضًا رغم أن حالتها ليست STATUS_CONTRADICTED — فلتره
    # بالحالة وحدها كان يُخرجها من هذا القسم بينما عمود "المصادر المخالفة"
    # في جدول الوقائع (build_report) يعرض f['contradicting'] مباشرة بلا أي
    # شرط، فيظهر العمود مآهولًا والقسم يقول "لم يظهر أي تناقض" لنفس الواقعة.
    contradictions = [f for f in fact_results if f.get("contradicting")]
    confirmed = [f for f in fact_results if f["status"] == STATUS_CONFIRMED]
    near_confirmed = [f for f in fact_results if f["status"] == STATUS_NEAR_CONFIRMED]

    if not fact_results:
        verdict, verdict_reason = False, "لم يُستخرج من المقال أي واقعة قابلة للتحقق"
    elif confirmed:
        verdict = True
        verdict_reason = (f"{len(confirmed)} واقعة مؤكَّدة بمصدرين مستقلين فأكثر "
                          f"من أصل {len(fact_results)}")
    else:
        verdict = False
        verdict_reason = ("لا واقعة واحدة مؤكَّدة بمصدرين مستقلين — المصادر "
                          "المستقلة لا تكفي لخبر قائم بذاته")
        if near_confirmed:
            # العلاج 4 (Issue #132 تعليق لاحق): الحكم النهائي يبقى صارمًا
            # (لا يكفي مصدر واحد للنشر)، لكن التقرير يعكس عدم اليقين بدل
            # إخفائه خلف "لا" مطلقة حين توجد واقعة بمصدر قوي واحد تستحق
            # مراجعة يدوية قبل إسقاطها كليًا
            verdict_reason += (f"؛ توجد {len(near_confirmed)} واقعة شبه "
                              "مؤكَّدة بمصدر واحد قوي تستحق مراجعة يدوية")

    return {
        "ok": True,
        "topic": _as_text(raw_topic) or "(لم يُستخرج موضوع محدد)",
        "facts": fact_results,
        "opinions": other_claims,
        "questions": question_results,
        "contradictions": contradictions,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
    }


def build_report(result: dict) -> str:
    if not result.get("ok"):
        return f"### 🔎 تعذّر التحقق\n\n{result.get('reason', '')}"

    lines = ["### 🔎 تقرير التحقق", "", f"**الموضوع:** {result['topic']}", ""]

    # عمود "الأدلة" يميّز صراحة بين لا نتائج بحث / نتائج بلا نص مقروء
    # (عناوين فقط) / نص مقروء — الثلاثة كانت تظهر "لا مصدر" نفسها فتبدو
    # متطابقة رغم اختلاف السبب جذريًا (Issue #132 تعليق لاحق).
    lines += ["#### الوقائع", ""]
    if result["facts"]:
        lines += ["| الواقعة | الحكم | الأدلة | المصادر المؤيدة (وزن الموثوقية) | المصادر المخالفة |",
                  "|---|---|---|---|---|"]
        for f in result["facts"]:
            # وزن كل مصدر مؤيد بجانب اسمه — العدد وحده لا يُظهر قوة السند
            # (Issue #132 تعليق لاحق)
            weighted = f.get("supporting_weighted") or [
                {"name": n, "weight": None} for n in f["supporting"]]
            supporting_str = "، ".join(
                f"{s['name']} ({s['weight']:.1f}×)" if s["weight"] is not None
                else s["name"]
                for s in weighted) or "—"
            # فشل نداء الحكم تقنيًا (لا حكم "لا سند" شرعي من النموذج) —
            # يُضاف صراحة إلى عمود الأدلة بدل الظهور بنفس "—" المجرَّدة
            # لواقعة بُحث لها فعلًا ولم توجد نصوص (تشخيص Issue #373، الجولة
            # الحادية عشرة، البند 2)
            evidence_cell = f.get("evidence_basis", "—")
            if f.get("judge_error"):
                evidence_cell += f" — ⚠️ فشل نداء الحكم تقنيًا: {f['judge_error']}"
            lines.append(
                f"| {f['text']} | {f['status']} | {evidence_cell} | "
                f"{supporting_str} | "
                f"{'، '.join(f['contradicting']) or '—'} |"
            )
    else:
        lines.append("لم يستخرج من المقال أي واقعة قابلة للتحقق.")
    lines.append("")

    lines += ["#### الأسئلة المطروحة", ""]
    if result["questions"]:
        for q in result["questions"]:
            basis = q.get("evidence_basis", "")
            basis_note = f" ({basis})" if basis and basis != EVIDENCE_FULL_TEXT else ""
            if q["answered"]:
                lines.append(f"- **{q['text']}** — {q['answer']} "
                             f"(بحسب {q['source']}){basis_note}")
            else:
                lines.append(f"- **{q['text']}** — لم توجد إجابة في المصادر "
                             f"المستقلة{basis_note}")
    else:
        lines.append("لم يثر المقال أسئلة مفتوحة تستحق بحثًا مستقلًا.")
    lines.append("")

    lines += ["#### ⚠️ أين خالفت المصادر المقال", ""]
    if result["contradictions"]:
        for f in result["contradictions"]:
            lines.append(f"- **{f['text']}** — تخالفه: {'، '.join(f['contradicting'])}")
    else:
        lines.append("لم يظهر أي تناقض بين المقال والمصادر المستقلة.")
    lines.append("")

    verdict_icon = "✅" if result["verdict"] else "❌"
    verdict_word = "نعم" if result["verdict"] else "لا"
    lines += ["#### الحكم النهائي", "",
             f"{verdict_icon} **{verdict_word}** — {result['verdict_reason']}"]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="تحقق من مقال ملصق في Issue")
    parser.add_argument("--issue", type=int, required=True, help="رقم الـ Issue")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")

    cfg = load_config()
    body = review.fetch_issue_body(args.issue)
    if not body.strip():
        review.comment(args.issue,
                       "### 🔎 لا نص\nالـ Issue لا يحوي نص مقال للتحقق منه.")
        return 0

    result = verify_article(body, cfg)
    report = build_report(result)

    # استيراد داخلي: verify_draft.py يستورد verify.py عند التحميل (يحتاج
    # STATUS_CONFIRMED و_TASHKEEL_RE)، فاستيراده هنا في نطاق الدالة لا أعلى
    # الملف يتفادى حلقة استيراد بين الوحدتين (Issue #334)
    from . import verify_draft
    if result.get("ok"):
        draft_outcome = verify_draft.attempt(result, body, args.issue, cfg)
    else:
        draft_outcome = {
            "produced": False,
            "reason": "تخطّي صياغة المسودة — تعذّر التحقق من المقال أصلًا",
            "central_text": "", "central_index": 0,
            "draft_id": None,
        }
    draft_section = verify_draft.build_report_section(draft_outcome)

    review.comment(args.issue,
                   f"{report}\n\n{draft_section}\n\n<sub>💵 {usage_summary()}</sub>")

    # يمرَّر إلى الخطوة التالية في verify.yml (رفع المسودة إلى المستودع)
    # عبر GITHUB_OUTPUT — لا مسار موازٍ، بل تمرير معرّف بين خطوتين لنفس المهمة
    draft_id = draft_outcome.get("draft_id")
    output_path = os.environ.get("GITHUB_OUTPUT")
    if draft_id and output_path:
        with open(output_path, "a", encoding="utf-8") as fh:
            fh.write(f"draft_id={draft_id}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
