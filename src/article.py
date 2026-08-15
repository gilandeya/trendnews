"""مقال من المصادر: يبدأ من موجز تحريري ملصوق في Issue — فكرة كاتبه،
معلوماته، ورأيه — لا من مقال جاهز يُحاكَم كما في src/verify.py. المخرج
مقال عربي جديد مسنود بالمصادر يجيب عن سؤال، عبر دورة المراجعة المعتادة.

يستبدل هذا المسار — لا يُعطّل — مسار src/verify.py (Issue #348، الخلفية):
تشغيل حقيقي أثبت أن verify.py يخطئ في جوهره حين يشير الموجز إلى حدث دون
تسميته («حدث في 11 آب... ما أعاد قصة حمزة الخطيب») فيبحث عن الوصف المبهم
حرفيًا ويحكم "لا مصدر" رغم أن الحدث حقيقي ومغطّى — البحث عن ادّعاء بلا
كيان مسمّى لا يجد شيئًا. هذا المسار **يسمّي الحدث** أولًا (_name_event)
بدل أن يعلن غيابه.

الأنبوب (كل خطوة موثَّقة في الدالة المسؤولة عنها):
  1) extract_brief() — استخراج وقائع/آراء/أسئلة من الموجز، مع تعليم كل
     واقعة تصف حدثًا دون تسميته (is_unnamed_event)
  2) _name_event() — لكل واقعة مبهمة: سلّم بحث يسمّي الحدث من نتائج البحث
     نفسها، لا من معرفة النموذج (القاعدة 3)
  3) لكل واقعة (مسمّاة أصلًا أو بعد التسمية): بحث + قراءة + حكم سند
     (_support_sources) — القاعدة 1: بلا سند كافٍ (مصدران مستقلان
     فأكثر)، تسقط الواقعة وتُذكر في "ما سقط من موجزي"
  4) _sufficiency() — بوابة عددية على الوقائع **المُرشَّحة بالسند فقط**
     (القاعدة 7 + سدّ ثغرة الدائرة، انظر التوثيق في _write_article)
  5) _choose_question() — يختار السؤال-العنوان من الوقائع المُرشَّحة
     حصرًا (لا يرى ما لم يجتز السند بعد)
  6) _draft_article() — صياغة بالعربية ببرومبت مستقل (لا writer.SYSTEM_PROMPT
     — القاعدة 6)، يضمّ الآراء منسوبة تحريريًا (القاعدة 2) بلا نداء منفصل
  7) فحص أصالة (verify_draft.check_originality مُعاد استعمالها كما هي —
     القاعدة 5) ثم صورة ومسودة عبر المسار المعتاد

لا يعيد استعمال classify_fact/judge_fact ولا جدول الأحكام من verify.py:
تلك الدوال تجسّد بالضبط الخطأ الجوهري الموثَّق أعلاه (الحكم على صياغة
الموجز كما وردت لا على ما يكشفه البحث) — سقطت من هذا المسار عمدًا.

    python -m src.article --issue 348
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

from anthropic import Anthropic, APIError

from . import evidence, extract, imaging, review, store, verify_draft, writer
from .config import DRAFTS_DIR, env, load_config
from .imagesearch import find_images
from .request import norm_tokens
from .sources import Article

log = logging.getLogger("article")

DRAFT_ORIGIN = "article"

# القاعدة 2: تمييز حدّي بمعيار دلالي واحد — واقعة تدّعي وقوع حدث/رقم/تصريح
# محدَّد، أو رأي يقوّم أو يفسّر أو يطرح سؤالًا مفتوحًا كموقف. لا تصنيف ثالث
# (بخلاف CLAIM_KINDS في verify.py التي تضيف "تنبؤ" — هنا القاعدة 2 من
# الطلب تصريحًا لا تفرّق التنبؤ عن الرأي).
WRITEUP_KINDS = ["واقعة", "رأي"]

_DIGIT_RE = re.compile(r"\d")


def _client() -> Anthropic:
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


# ──────────────────────────── استخراج بنية الموجز ────────────────────────────

WRITEUP_EXTRACT_SYSTEM = """أنت تقرأ موجزًا تحريريًا كتبه صاحب صفحة إخبارية —
فكرته وما يعرفه ورأيه — لتستخرج بنيته فقط. لا تحكم على صحته الآن، فذلك يقع
لاحقًا ببحث في مصادر مستقلة.

استخرج:
1. topic: جملة واحدة تلخّص موضوع الموجز كما فهمتَه أنت.
2. statements: كل جملة تحمل معلومة أو موقفًا، مصنّفة:
   - "واقعة": تدّعي وقوع حدث أو رقم أو تصريح محدَّد — "حدث كذا في كذا"
   - "رأي": تقويم أو تفسير أو سؤال مفتوح يطرحه صاحب الموجز كموقف — لا
     ادّعاء وقوع بذاته
   جملة سردية انتقالية عامة — بلا حدث أو رقم أو تصريح محدَّد، وبلا تقويم أو
   موقف أيضًا — لا تُدرَج ضمن statements إطلاقًا: لا "واقعة" (لا تدّعي وقوع
   شيء محدَّد) ولا "رأي" (ليست تقويمًا ولا موقفًا). مثال: "مرّت الأيام
   وتغيرت الأحوال ومضى من مضى وبقي من بقي" — سرد عابر بلا مضمون قابل
   للتحقق، يُستبعد كليًا لا يُصنَّف بأي تصنيف.
   لكل عنصر أيضًا entities: 2-5 كيانات مميِّزة منه (أسماء أعلام، أرقام،
   تواريخ، أماكن) كما وردت في الموجز حرفيًا بلا أي إعادة صياغة — استعلام
   البحث سيُبنى منها وحدها.
   ولكل عنصر أيضًا is_unnamed_event: true حين تكون الواقعة **إشارة** إلى
   حدث بأثره أو بذكر ما أعاده أو ذكّر به، دون أن تسمّي الحدث نفسه: من فعل
   ماذا بالضبط. مثال: "حدث في 11 آب 2026 ما أعاد قصة حمزة الخطيب" لا تسمّي
   الحدث — تصفه بأثره (أنه ذكّر بقصة أخرى) لا بفعله. "أعلنت الحكومة رفع
   الدعم عن الوقود" تسمّي الحدث فعلًا (is_unnamed_event: false) رغم أنها
   واقعة أيضًا. مثال حدّي آخر: "انطلقت الاحتجاجات الأولى من قرية صغيرة في
   الجنوب" تسمّي الحدث أيضًا رغم قلة التفاصيل — فاعل واضح (الاحتجاجات
   الأولى) وفعل واضح (انطلقت من قرية في الجنوب)، فهي is_unnamed_event:
   false حتى لو كانت واقعة مرجعية عامة لا خبرًا حديثًا؛ الفارق عن المثال
   الأول هو غياب "من فعل ماذا" لا غياب التفاصيل. لا تخترع is_unnamed_event:
   true لواقعة مسمّاة بوضوح.
   ولكل عنصر أيضًا is_reference: true إن كانت حقيقته ثابتة لا تتعلق بدورة
   الأخبار الحالية (سيرة، تاريخ قديم، إحصاء رسمي منشور من قبل) — بحثها لا
   يُقيَّد بنافذة زمنية قصيرة.
3. questions: أسئلة يطرحها الموجز صراحة ولا يجيب عنها بنفسه. كل سؤال هو
   مهمة بحث فعلية لا حصيلة فشل — سيُبحث له سند بنفس آلية statements
   تمامًا، فلكل سؤال أيضًا entities (2-5 كيانات مميِّزة منه كما وردت في
   الموجز حرفيًا — الاستعلام يُبنى منها) وis_reference (true إن كان سؤالًا
   عن حقيقة ثابتة لا تتعلق بدورة الأخبار الحالية، كسيرة شخص أو تاريخ سابق
   — بحثه لا يُقيَّد بنافذة زمنية قصيرة).

لا تنقل جملة من الموجز حرفيًا: أعد صياغة كل عنصر وسؤال بإيجاز (فيما عدا
entities: تُنقل حرفيًا، لا تُعاد صياغتها أبدًا). لا تُجب عن الأسئلة من
معرفتك — استخرجها فقط.

استخدم أداة extract_brief دائمًا."""

WRITEUP_EXTRACT_SCHEMA = {
    "name": "extract_brief",
    "description": "يستخرج بنية موجز تحريري: موضوعه ووقائعه وآراؤه وأسئلته",
    "input_schema": {
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "statements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "kind": {"type": "string", "enum": WRITEUP_KINDS},
                        "entities": {"type": "array", "items": {"type": "string"}},
                        "is_unnamed_event": {"type": "boolean"},
                        "is_reference": {"type": "boolean"},
                    },
                    "required": ["text", "kind", "entities", "is_unnamed_event",
                                "is_reference"],
                },
            },
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "entities": {"type": "array", "items": {"type": "string"}},
                        "is_reference": {"type": "boolean"},
                    },
                    "required": ["text", "entities", "is_reference"],
                },
            },
        },
        "required": ["topic", "statements", "questions"],
    },
}


def _as_text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "statement", "content", "question"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return ""


def _as_entities(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [e.strip() for e in value if isinstance(e, str) and e.strip()]


def normalize_statement(item) -> dict | None:
    """يطبّع عنصر بنية موجز واحدًا — نفس فلسفة verify.normalize_claim: رد
    النموذج قد يخالف مخطط الأداة، فلا نفترض شكلًا بلا تحقق."""
    text = _as_text(item)
    if not text:
        return None
    kind = item.get("kind") if isinstance(item, dict) else None
    if kind not in WRITEUP_KINDS:
        kind = "واقعة"
    entities = _as_entities(item.get("entities")) if isinstance(item, dict) else []
    is_unnamed_event = bool(isinstance(item, dict) and item.get("is_unnamed_event") is True)
    is_reference = bool(isinstance(item, dict) and item.get("is_reference") is True)
    return {"text": text, "kind": kind, "entities": entities,
            "is_unnamed_event": is_unnamed_event, "is_reference": is_reference}


def normalize_statements(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        norm = normalize_statement(item)
        if norm:
            out.append(norm)
    return out


def normalize_question(item) -> dict | None:
    """يطبّع سؤالًا واحدًا من الموجز بنفس بنية normalize_statement (نصًا +
    entities + is_reference) — تناظرًا كاملًا مع statements، فالسؤال مهمة
    بحث فعلية يُبنى استعلامها من كياناته لا من نصه الخام (Issue #132: بناء
    الاستعلام من نص جملة معاد صياغته أثبت ضعفه مرارًا)."""
    text = _as_text(item)
    if not text:
        return None
    entities = _as_entities(item.get("entities")) if isinstance(item, dict) else []
    is_reference = bool(isinstance(item, dict) and item.get("is_reference") is True)
    return {"text": text, "entities": entities, "is_reference": is_reference}


def normalize_questions(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        norm = normalize_question(item)
        if norm:
            out.append(norm)
    return out


def extract_brief(body: str, cfg, retries: int = 3) -> tuple[dict | None, str | None]:
    """يستخرج بنية الموجز. يرجع (data, None) عند النجاح، أو (None, سبب
    محدد) عند الفشل — لا فشل صامت."""
    acfg = cfg.get("article", {}) or {}
    model = acfg.get("model", "claude-sonnet-5")
    max_tokens = int(acfg.get("extract_max_tokens", 3000))
    client = _client()

    reason = "تعذّر الاتصال بالنموذج"
    for attempt in range(1, retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                tools=[WRITEUP_EXTRACT_SCHEMA],
                tool_choice={"type": "tool", "name": "extract_brief"},
                system=WRITEUP_EXTRACT_SYSTEM,
                messages=[{"role": "user", "content": body}],
            )
            writer.record_usage(resp, model)
        except APIError as exc:
            log.warning("محاولة %d/%d فشلت في استخراج بنية الموجز: %s", attempt, retries, exc)
            reason = "تعذّر الاتصال بالنموذج"
            continue

        if getattr(resp, "stop_reason", "") == "max_tokens":
            log.error("محاولة %d/%d: استخراج بنية الموجز مبتور (max_tokens)",
                     attempt, retries)
            reason = "الرد مبتور — تجاوز سقف التوكنات"
            continue

        data = next((b.input for b in resp.content
                    if getattr(b, "type", "") == "tool_use"), None)
        if isinstance(data, dict):
            return data, None

        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        try:
            data = writer._extract_json(text) if text.strip() else None
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return data, None

        reason = "الرد لم يكن JSON صالحًا"

    log.error("تعذّر استخراج بنية الموجز بعد %d محاولات: %s", retries, reason)
    return None, reason


# ──────────────────────────── تسمية الحدث المبهم ────────────────────────────


def _narrow_for_context(text: str, max_chars: int = 400) -> str:
    """نافذة رخيصة قبل نداء استخلاص السياق (تعليق الموافقة الثاني، البند 3،
    الخيار ج كمرشِّح أولي قبل الخيار أ): الأعراف الصحفية تضع السياق
    الجغرافي/السياسي (دولة، جهة) في مطلع الخبر عادة، فتضييق النص المُرسَل
    للنموذج إلى مطلعه فقط يقلّل تلقائيًا احتمال التقاط مقارنة استطرادية من
    منتصف المقال، ويرخّص النداء (نص أقصر)."""
    return (text or "")[:max_chars]


CONTEXT_SYSTEM = """أنت تقرأ نصوص مصادر إخبارية مرجعية عن كيان واحد (شخص أو
جهة) لتستخلص سياقه المميِّز فقط — دولة أو مدينة أو جهة يرتبط بها هذا الكيان
تحديدًا في هذه النصوص، لا ذكرًا عرضيًا ولا مقارنة استطرادية بكيان آخر ورد
في نفس النص.

اقرأ النصوص المعطاة فقط. استخرج 1-3 كلمات أو تعبيرات سياق قصيرة (اسم بلد،
مدينة، أو جهة) ترتبط بالكيان في هذه النصوص تحديدًا — لا من معرفتك الخاصة
عن الكيان. إن لم تجد النصوص سياقًا مميِّزًا واضحًا، أعد قائمة فارغة بدل
التخمين.

استخدم أداة extract_context دائمًا."""

CONTEXT_SCHEMA = {
    "name": "extract_context",
    "description": "يستخلص كلمات سياق مميِّزة (بلد/مدينة/جهة) لكيان من نصوص مصادر مرجعية",
    "input_schema": {
        "type": "object",
        "properties": {"terms": {"type": "array", "items": {"type": "string"}}},
        "required": ["terms"],
    },
}


def _ask_context_model(entity: str, exclude_entities: list[str], docs: list[dict],
                       cfg, max_terms: int) -> list[str]:
    """يستخلص سياق كيان من نصوص بحث مرجعي فعلية بنداء نموذج (تعليق الموافقة
    الثاني، البند 3، البديل أ) — لا بترجيح تكرار خام (كان يُخرج حشوًا لا
    كيانات مميِّزة فعليًا، فشل «لبّاد» في التشخيص المعتمَد). النصوص مصادر
    مقروءة لا معرفة نموذج (القاعدة 3) — النداء مقيَّد بها حصرًا."""
    if not docs:
        return []
    acfg = cfg.get("article", {}) or {}
    model = acfg.get("model", "claude-sonnet-5")
    client = _client()
    narrowed = [{"name": d["name"], "text": _narrow_for_context(d.get("text", ""))}
               for d in docs]
    prompt = f"الكيان: {entity}\n\nنصوص مصادر مرجعية:\n\n{_format_docs(narrowed)}"
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=200,
            tools=[CONTEXT_SCHEMA],
            tool_choice={"type": "tool", "name": "extract_context"},
            system=CONTEXT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        writer.record_usage(resp, model)
    except APIError as exc:
        log.warning("فشل نداء استخلاص سياق الكيان %r: %s", entity, exc)
        return []
    data = next((b.input for b in resp.content
                if getattr(b, "type", "") == "tool_use"), None)
    terms = data.get("terms") if isinstance(data, dict) else None
    if not isinstance(terms, list):
        return []
    exclude_norm: set[str] = set()
    for e in exclude_entities:
        exclude_norm |= norm_tokens(e)
    out: list[str] = []
    for t in terms:
        if not isinstance(t, str):
            continue
        t = t.strip()
        if not t or (norm_tokens(t) & exclude_norm):
            continue
        out.append(t)
        if len(out) >= max_terms:
            break
    return out


# مطابقة أسماء الأشهر العربية الشامية والحديثة معًا — الإعلام العربي
# يستعمل كلا التسميتين (آب/أغسطس) بحسب الناشر، وموجز الصفحة قد يستعمل أيًا
# منهما (تعليق التنفيذ على Issue #364، البند 2)
_AR_MONTHS = {
    "يناير": 1, "كانون الثاني": 1,
    "فبراير": 2, "شباط": 2,
    "مارس": 3, "آذار": 3,
    "أبريل": 4, "نيسان": 4,
    "مايو": 5, "أيار": 5,
    "يونيو": 6, "حزيران": 6,
    "يوليو": 7, "تموز": 7,
    "أغسطس": 8, "آب": 8,
    "سبتمبر": 9, "أيلول": 9,
    "أكتوبر": 10, "تشرين الأول": 10,
    "نوفمبر": 11, "تشرين الثاني": 11,
    "ديسمبر": 12, "كانون الأول": 12,
}
# الأسماء المكوَّنة من كلمتين ("تشرين الأول") يجب أن تُجرَّب قبل مفردة
# محتملة الالتباس — الفرز بالطول تنازليًا في البديل يضمن ذلك
_MONTH_ALT = "|".join(sorted((re.escape(m) for m in _AR_MONTHS), key=len, reverse=True))
_DATE_RE = re.compile(rf"(?:(?P<day>\d{{1,2}})\s+)?(?P<month>{_MONTH_ALT})\s+(?P<year>\d{{4}})")
_BARE_YEAR_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _extract_dates(text: str) -> list[tuple[int, int | None, int | None]]:
    """يستخرج (سنة، شهر أو None، يوم أو None) من نص عربي حر — لا يفترض بنية
    تاريخ منظَّمة (ISO أو غيره)، فالنص مصدر إخباري حر الصياغة. يُستعمل في
    _dates_consistent (بوابة الاتساق، البند 2) لمطابقة تاريخ الواقعة
    الأصلية بتاريخ التسمية المرشَّحة، لا لأي غرض عام آخر."""
    found: list[tuple[int, int | None, int | None]] = []
    matched_years: set[str] = set()
    for m in _DATE_RE.finditer(text or ""):
        year = m.group("year")
        matched_years.add(year)
        month = _AR_MONTHS[m.group("month")]
        day = int(m.group("day")) if m.group("day") else None
        found.append((int(year), month, day))
    for m in _BARE_YEAR_RE.finditer(text or ""):
        year = m.group(1)
        if year in matched_years or not (1900 <= int(year) <= 2100):
            continue
        matched_years.add(year)
        found.append((int(year), None, None))
    return found


def _dates_consistent(named_text: str, dates: list[str], docs: list[dict],
                      window_days: int) -> bool:
    """بوابة اتساق التاريخ (تعليق التنفيذ على Issue #364، البند 2): لا تكفي
    مطابقة الكيانات وحدها (فشل «لبّاد» في التشخيص المعتمَد سبق أن غطّته
    _naming_consistent) — حدثٌ لا يقع في تاريخ الإشارة المبهمة الأصلية، أو
    نافذة ضيقة حوله، لا يصلح تسميةً له حتى لو ذكر الكيانات الصحيحة (تشخيص
    التشغيل الحقيقي: حديث جنبلاط 2011 عن حمزة الخطيب ذُكر بثقة رغم أنه ليس
    الحدث المقصود بتاريخ 11 آب 2026).

    التطابق بسنة+شهر إلزامي حين يتوفران في الجانبين؛ فارق اليوم وحده مسموح
    به ضمن window_days (تقارير الوكالات قد تسجّل يوم النشر لا يوم الحدث
    نفسه بفارق يوم أو يومين) — لا فارق شهر أو سنة مهما صغر.

    إن لم يحمل موجز صاحب الصفحة تاريخًا منظَّمًا فعليًا ضمن dates (مثلًا
    entity رقمي هو مدة لا تاريخ تقويمي، كـ"15 عامًا")، لا قيد — نتراجع لفحص
    الكيانات وحده كما كان قبل هذا العلاج."""
    original: list[tuple[int, int | None, int | None]] = []
    for d in dates:
        original += _extract_dates(d)
    if not original:
        return True
    target_text = named_text + " " + " ".join(d.get("text", "") for d in docs)
    target = _extract_dates(target_text)
    if not target:
        return False
    for oy, om, od in original:
        for ty, tm, td in target:
            if oy != ty:
                continue
            if om is not None and tm is not None and om != tm:
                continue
            if od is not None and td is not None and abs(od - td) > window_days:
                continue
            return True
    return False


def _naming_consistent(named_text: str, proper_nouns: list[str], dates: list[str],
                       docs: list[dict], cfg) -> bool:
    """بوابة اتساق (تعليق الموافقة الثاني، البند 2؛ وسّعت بتعليق التنفيذ
    على Issue #364 لتفحص التاريخ لا الكيانات وحدها): كيانات الواقعة
    الأصلية يجب أن تُذكر صراحة إما في نص التسمية نفسه أو في الوثائق التي
    استُعملت لتسميته — وإلا التسمية غير موثوقة رغم أن النموذج أجاب بثقة.
    هذه بالضبط البوابة التي كانت ستمنع فشل «لبّاد» في التشخيص المعتمَد:
    وثائق فيديو متداول لا تذكر «حمزة الخطيب» ولا «درعا» إطلاقًا فكانت
    لتُرفض هنا.

    الكيان وحده لا يكفي (تشخيص التشغيل الحقيقي على Issue #364): حدث حقيقي
    عن الكيان الصحيح قد لا يكون الحدث المقصود إن وقع في تاريخ مختلف تمامًا
    عن تاريخ الإشارة المبهمة الأصلية — _dates_consistent تفحص هذا إضافةً،
    لا بديلًا عنه."""
    if proper_nouns:
        entity_tokens: set[str] = set()
        for e in proper_nouns:
            entity_tokens |= norm_tokens(e)
        if entity_tokens:
            docs_tokens: set[str] = set()
            for d in docs:
                docs_tokens |= norm_tokens(d.get("text", ""))
            if not (entity_tokens & norm_tokens(named_text)) and not (entity_tokens & docs_tokens):
                return False
    acfg = cfg.get("article", {}) or {}
    window_days = int(acfg.get("naming_date_window_days", 2))
    return _dates_consistent(named_text, dates, docs, window_days)


NAMING_SYSTEM = """أنت تقرأ نصوص مصادر إخبارية مستقلة لتحدّد الحدث المحدَّد
الذي تصفه، ردًا على إشارة مبهمة له في موجز لا يسمّيه صراحة — يذكر أثره أو
ما ذكّر به دون أن يذكر من فعل ماذا بالضبط.

اقرأ الإشارة المبهمة والكيانات المرتبطة بها، ثم نصوص المصادر المعطاة فقط.
إن ذكرت النصوص حدثًا محدَّدًا (من فعل ماذا، وبأي نتيجة) يتّسق مع الكيانات
المعطاة، اكتبه بصياغة واقعة صريحة جديدة تحلّ محل الإشارة المبهمة —
أعد صياغته بإيجاز من النصوص، لا تنقله حرفيًا من أي مصدر. إن لم تصف النصوص
حدثًا واضحًا يتّسق مع الكيانات، أقرّ بذلك صراحة (named: false) — لا تخمّن
ولا تستعن بمعرفتك الخاصة عن الموضوع لتُكمل ما لا تقوله النصوص المعطاة.

أخرج أسماء المصادر المؤيِّدة مجردة تمامًا كما وردت في وسم
'--- المصدر: <الاسم> ---'.

استخدم أداة name_event دائمًا."""

NAMING_SCHEMA = {
    "name": "name_event",
    "description": "يسمّي حدثًا محدَّدًا من نصوص مصادر، أو يقر بعدم وضوحه",
    "input_schema": {
        "type": "object",
        "properties": {
            "named": {"type": "boolean"},
            "text": {"type": "string"},
            "supporting": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["named"],
    },
}


def _format_docs(docs: list[dict]) -> str:
    return "\n\n".join(f"--- المصدر: {d['name']} ---\n{d['text']}" for d in docs)


def _ask_naming_model(vague_text: str, entities: list[str], docs: list[dict],
                      cfg) -> dict | None:
    """يسأل النموذج: هل تسمّي هذه النصوص حدثًا محدَّدًا؟ يعيد
    {"text":..., "supporting":[...]} عند النجاح، أو None — لا تخمين بلا
    نصوص تسنده."""
    if not docs:
        return None
    acfg = cfg.get("article", {}) or {}
    model = acfg.get("model", "claude-sonnet-5")
    client = _client()
    prompt = (f"الإشارة المبهمة: {vague_text}\n"
             f"الكيانات المرتبطة: {'، '.join(entities)}\n\n"
             f"نصوص المصادر:\n\n{_format_docs(docs)}")
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=500,
            tools=[NAMING_SCHEMA],
            tool_choice={"type": "tool", "name": "name_event"},
            system=NAMING_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        writer.record_usage(resp, model)
    except APIError as exc:
        log.warning("فشل نداء تسمية الحدث: %s", exc)
        return None

    data = next((b.input for b in resp.content
                if getattr(b, "type", "") == "tool_use"), None)
    if not isinstance(data, dict) or not data.get("named"):
        return None
    text = str(data.get("text") or "").strip()
    if not text:
        return None
    return {"text": text, "supporting": evidence._known_only(data.get("supporting"), docs)}


def _name_event(statement: dict, cfg) -> tuple[str | None, list[dict], list[str], list[dict]]:
    """سلّم اتساع لتسمية حدث أشار إليه الموجز دون تسميته (القسم 3 من
    التشخيص المعتمَد على Issue #348، مقلوب الترتيب في تعليق الموافقة
    الثاني، البند 1): كيانات + تاريخ مباشرةً أولًا (الأبسط يُجرَّب قبل
    الأذكى، ويوفّر في الحالات السهلة دورة بحث كاملة) ⟵ عند الفشل فقط: بحث
    مرجعي غير مقيَّد زمنيًا عن سيرة الكيانات لاستخلاص سياق (بلد/جهة) بنداء
    نموذج على تلك النصوص فعلًا (البند 3، لا معرفة النموذج — القاعدة 3) ⟵
    استعلامات تاريخ+سياق مبنية من ذلك السياق المكتشَف.

    بحث بالوصف المبهم حرفيًا ممنوع بنيويًا لا معالَج بإعادة محاولة: كل
    استعلام يُبنى من الكيانات والتاريخ (أو السياق المستخلَص) فقط، لا من
    نص الواقعة المبهم.

    كل تسمية مرشَّحة تمرّ ببوابة اتساق (_naming_consistent، البند 2) قبل
    قبولها: كيانات الواقعة الأصلية يجب أن تُذكر في نص التسمية أو وثائقها،
    وإلا تُرفض ويتابع السلّم — لا إرجاع فوري لتسمية قد تصف حدثًا آخر
    (فشل «لبّاد» في التشخيص المعتمَد).

    يعيد (النص المسمّى أو None، نصوص المصادر التي سمّته، أسماء المصادر
    المؤيِّدة، سجلّ trail كامل الخطوات — كل استعلام مع مصادره وحصيلته،
    البند 4) — النصوص والمصادر المؤيِّدة هنا **هي نفسها** أدلة الحكم على
    السند لاحقًا (لا نداء بحث أو حكم إضافي مكرَّر لنفس الحقيقة)."""
    acfg = cfg.get("article", {}) or {}
    days = int(acfg.get("days", 21))
    query_max_words = int(acfg.get("query_max_words", 5))
    max_context_terms = int(acfg.get("naming_max_context_terms", 3))

    entities = statement.get("entities") or []
    dates = [e for e in entities if _DIGIT_RE.search(e)]
    proper_nouns = [e for e in entities if not _DIGIT_RE.search(e)]
    trail: list[dict] = []
    if not dates or not proper_nouns:
        return None, [], [], trail

    def _try(stage_name: str, query: str):
        ranked = evidence.search(query, cfg, days)
        docs, basis = evidence.gather_evidence(ranked, cfg, query)
        entry = {"stage": stage_name, "query": query, "basis": basis,
                 "sources": [d["name"] for d in docs],
                 "raw_count": getattr(ranked, "raw_count", None),
                 "matched_count": getattr(ranked, "matched_count", None),
                 "fetch_failures": getattr(docs, "fetch_failures", []),
                 "outcome": ""}
        if stage_name == "مباشر":
            # البند 4 (تعليق الموافقة الثالث على Issue #361): مرحلة التسمية
            # المباشرة وحدها — لا كل استعلام — لأنها الفرضية المطروحة الآن
            # («خبر 11 آب موضوعه المحكمة، قد لا يذكر حمزة الخطيب في
            # العنوان»)؛ بلا معالجة لفلتر الصلة نفسه، عيّنة للتشخيص فقط
            entry["rejected_titles"] = getattr(ranked, "rejected_titles", [])
        trail.append(entry)
        if not docs:
            entry["outcome"] = "لا وثائق للتسمية"
            return None
        named = _ask_naming_model(statement["text"], entities, docs, cfg)
        if not named:
            entry["outcome"] = "لم يُسمَّ من هذه النتائج"
            return None
        if not _naming_consistent(named["text"], proper_nouns, dates, docs, cfg):
            entry["outcome"] = "رُفض — لا يذكر كيانات الواقعة الأصلية (بوابة الاتساق)"
            return None
        entry["outcome"] = "سُمّي الحدث"
        return named["text"], docs, named["supporting"]

    # المرحلة 1 (البند 1): كيانات + تاريخ مباشرةً — بلا أي بحث مرجعي مسبق
    for date in dates:
        for term in proper_nouns:
            result = _try("مباشر", evidence.build_query(f"{term} {date}", query_max_words))
            if result:
                text, docs, supporting = result
                return text, docs, supporting, trail

    # المرحلة 2 (احتياطية — البند 3): بحث مرجعي لاستخلاص سياق، ثم سياق+تاريخ
    context_terms: list[str] = []
    for entity in proper_nouns:
        ranked = evidence.search(entity, cfg, days, unrestricted=True)
        docs, basis = evidence.gather_evidence(ranked, cfg, entity)
        terms = _ask_context_model(entity, entities, docs, cfg, max_context_terms) if docs else []
        trail.append({"stage": "مرجعي", "query": entity, "basis": basis,
                      "sources": [d["name"] for d in docs],
                      "raw_count": getattr(ranked, "raw_count", None),
                      "matched_count": getattr(ranked, "matched_count", None),
                      "fetch_failures": getattr(docs, "fetch_failures", []),
                      "outcome": f"{len(terms)} كلمة سياق مستخلَصة" if terms
                                else "لا سياق مستخلَص"})
        context_terms += terms
    context_terms = list(dict.fromkeys(context_terms))

    for date in dates:
        for term in context_terms:
            result = _try("سياق", evidence.build_query(f"{term} {date}", query_max_words))
            if result:
                text, docs, supporting = result
                return text, docs, supporting, trail

    return None, [], [], trail


# ──────────────────────────── الحكم على السند (القاعدة 1) ────────────────────

SUPPORT_SYSTEM = """أنت تتحقق هل نصوص مصادر مستقلة تسند واقعة بعينها.

احكم من النصوص المعطاة فقط — لا تستخدم معرفتك الخاصة عن الموضوع. التأييد
يعني أن النص يذكر الواقعة نفسها أو ما يقاربها بوضوح، لا مجرد ذكر موضوع
عام قريب منها. مصدر لم يذكر الواقعة إطلاقًا لا يُحسب مؤيدًا ولا مخالفًا.
أخرج اسم المصدر مجردًا تمامًا كما ورد في وسم '--- المصدر: <الاسم> ---'
فقط، بلا اختراع أسماء جديدة.

استخدم أداة support_fact دائمًا."""

SUPPORT_SCHEMA = {
    "name": "support_fact",
    "description": "يحدد أي المصادر المعطاة يسند واقعة بعينها",
    "input_schema": {
        "type": "object",
        "properties": {"supporting": {"type": "array", "items": {"type": "string"}}},
        "required": ["supporting"],
    },
}


def _support_sources(fact_text: str, docs: list[dict], cfg) -> list[str]:
    """يعيد أسماء المصادر (من docs فعليًا، لا مُختلَقة) التي تسند fact_text
    — القاعدة 1: هذه القائمة (بعد عدّها) هي ما يقرر مصير الواقعة."""
    if not docs:
        return []
    acfg = cfg.get("article", {}) or {}
    model = acfg.get("model", "claude-sonnet-5")
    client = _client()
    prompt = f"الواقعة: {fact_text}\n\nنصوص المصادر:\n\n{_format_docs(docs)}"
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            tools=[SUPPORT_SCHEMA],
            tool_choice={"type": "tool", "name": "support_fact"},
            system=SUPPORT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        writer.record_usage(resp, model)
    except APIError as exc:
        log.warning("فشل نداء الحكم على السند: %s", exc)
        return []
    data = next((b.input for b in resp.content
                if getattr(b, "type", "") == "tool_use"), None)
    if not isinstance(data, dict):
        return []
    return evidence._known_only(data.get("supporting"), docs)


# ──────────────────────── الإجابة عن أسئلة الموجز (البند 5) ──────────────────

ANSWER_SYSTEM = """أنت تجيب عن سؤال طرحه صاحب موجز تحريري، من نصوص مصادر
مستقلة مُعطاة لك حصرًا — لا من معرفتك الخاصة.

اقرأ النصوص فقط. إن أجابت عن السؤال بوضوح، اكتب الإجابة بإيجاز بصياغتك من
هذه النصوص حصرًا — لا نقلًا حرفيًا من أي نص — وأخرج أسماء **كل** المصادر
التي أجابت فعلًا في supporting، مجردة تمامًا كما وردت في وسم '--- المصدر:
<الاسم> ---' فقط، بلا اختراع أسماء جديدة. إجابة answered:true بلا مصدر
واحد على الأقل في supporting تُعامَل كإجابة بلا سند — فلا تترك supporting
فارغة ما دام أحد النصوص المعطاة يسند الإجابة فعلًا. إن لم تُجب النصوص عن
السؤال بوضوح، أقرّ بذلك (answered: false, supporting: []) — لا تخمّن ولا
تستعن بمعرفتك الخاصة عمّا لا تقوله النصوص المعطاة.

استخدم أداة answer_question دائمًا."""

ANSWER_SCHEMA = {
    "name": "answer_question",
    "description": "يجيب عن سؤال من نصوص مصادر معطاة حصرًا، أو يقر بعدم كفايتها",
    "input_schema": {
        "type": "object",
        "properties": {
            "answered": {"type": "boolean"},
            "text": {"type": "string"},
            "supporting": {"type": "array", "items": {"type": "string"}},
        },
        # supporting إلزامي الآن (تعليق العطل الثاني على Issue #361، البند
        # 3): تناظرًا مع SUPPORT_SCHEMA التي تُلزم بها منذ البداية — كانت
        # ANSWER_SCHEMA الوحيدة بين شقيقاتها الثلاث (SUPPORT/NAMING/ANSWER)
        # التي لا تُلزم بحقل المصادر، فسمحت لردود answered:true بسند فارغ
        # بلا أي رفض من مخطط الأداة نفسه (تشخيص التشغيل الحقيقي: "النموذج
        # أجاب ولم يسمِّ أي مصدر").
        "required": ["answered", "supporting"],
    },
}


def _ask_answer_model(question_text: str, docs: list[dict], cfg) -> dict | None:
    """يجيب عن سؤال من الموجز من نصوص بحث فعلية — القاعدة 3: أسئلة الموجز
    مهمة بحث لا حصيلة فشل (البند 5)؛ يعيد {"text":..., "supporting":[...],
    "naming_issue":...} عند نجاح الإجابة، أو None بلا تخمين.

    naming_issue (تعليق التنفيذ على Issue #364، البند 3 — تشخيص لم يُحسم في
    التشغيل الحقيقي: answered:true رجع بسند فارغ لسؤال كانت وثائقه تعرّف
    الكيان بالضرورة، بلا وضوح إن كان النموذج لم يسمِّ مصدرًا أصلًا أو سمّى
    اسمًا لم يُطابَق): "no_source_named" حين لا يذكر رد النموذج أي اسم مصدر
    رغم الإجابة، أو "unmatched_source" حين يذكر أسماء لكن evidence._known_only
    ترفضها كلها (لا تطابق أي doc معطى)، أو None حين يوجد سند مطابق فعليًا."""
    if not docs:
        return None
    acfg = cfg.get("article", {}) or {}
    model = acfg.get("model", "claude-sonnet-5")
    client = _client()
    prompt = f"السؤال: {question_text}\n\nنصوص المصادر:\n\n{_format_docs(docs)}"
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            tools=[ANSWER_SCHEMA],
            tool_choice={"type": "tool", "name": "answer_question"},
            system=ANSWER_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        writer.record_usage(resp, model)
    except APIError as exc:
        log.warning("فشل نداء الإجابة عن سؤال الموجز: %s", exc)
        return None
    data = next((b.input for b in resp.content
                if getattr(b, "type", "") == "tool_use"), None)
    if not isinstance(data, dict) or not data.get("answered"):
        return None
    text = str(data.get("text") or "").strip()
    if not text:
        return None
    raw_supporting = data.get("supporting")
    supporting = evidence._known_only(raw_supporting, docs)
    naming_issue = None
    if not supporting:
        if isinstance(raw_supporting, list) and raw_supporting:
            naming_issue = "unmatched_source"
            log.warning("answered:true للسؤال %r لكن أسماء المصادر التي ذكرها "
                       "النموذج (%r) لم تطابق أي مصدر معطى — عطل تسمية مصدر "
                       "من النموذج نفسه، لا غياب سند فعلي (تشخيص Issue #364، "
                       "البند 3)", question_text, raw_supporting)
        else:
            naming_issue = "no_source_named"
            log.warning("answered:true للسؤال %r لكن النموذج لم يسمِّ أي مصدر "
                       "مؤيِّد رغم الإجابة (تشخيص Issue #364، البند 3)",
                       question_text)
    return {"text": text, "supporting": supporting, "naming_issue": naming_issue}


def _grounded_sources(names: list[str], docs: list[dict],
                      ranked: list[Article]) -> list[dict]:
    """مقتطف/رابط/صور كل مصدر أسند واقعة فعليًا — نفس بنية verify._fact_sources
    لتبقى قابلة للتمرير مباشرة إلى verify_draft._image_candidates/
    check_originality بلا تحويل شكل إضافي."""
    docs_by_name = {d["name"]: d for d in docs}
    images_by_name: dict[str, list[str]] = {}
    for a in ranked:
        name = getattr(a, "publisher", "") or getattr(a, "source_name", "")
        if name and name not in images_by_name:
            images_by_name[name] = getattr(a, "image_candidates", None) or []
    out = []
    for name in names:
        doc = docs_by_name.get(name)
        if not doc:
            continue
        out.append({"name": name, "link": doc.get("link", ""), "text": doc.get("text", ""),
                    "image_candidates": images_by_name.get(name, [])})
    return out


def _sufficiency(grounded: list[dict], cfg) -> tuple[bool, str]:
    """بوابة الكفاية (القاعدة 7): عددية بحتة — بلا فحص صلة إضافي (تعليق
    الموافقة، البند 3: السؤال يُشتق أصلًا من الوقائع المُرشَّحة، فأي واقعة
    لا تخدم الإجابة لا تُختار في مرحلة الصياغة، لا حاجة لبوابة صلة منفصلة
    قد ترفض حالات صحيحة كصلة لفظية ضعيفة بين سؤال وجوابه الصحيح).

    **ترتيب حاسم** (سدّ ثغرة الدائرة، آخر تعليق على Issue #348): `grounded`
    هنا يجب أن يكون مُرشَّحًا بالسند فعلًا (مصدران مستقلان فأكثر لكل عنصر)
    **قبل** أي اختيار سؤال — لا كل ما استُخرج من الموجز. لو كان الترشيح
    يقع بعد اختيار السؤال، لأمكن اشتقاق السؤال من واقعة ضعيفة السند فتمرّ
    هذه البوابة تلقائيًا بحكم أنها "اختيرت" لا لأنها "فُحصت". _write_article
    يستدعي هذه الدالة بعد حلقة السند مباشرة، وقبل _choose_question — بهذا
    الترتيب وحده الواقعة المحورية مضمونة بالبناء لا بالفحص.

    **البند 6 (تعليق الموافقة الثاني)**: منذ أن صارت أسئلة الموجز تُبحث
    فعليًا (البند 5)، إجاباتها المسندة تدخل `grounded` أيضًا — وأغلبها
    مرجعي (سيرة/خلفية موثَّقة بكثرة، تجتاز السند بسهولة). لو دخلت العدّ
    بلا تمييز، لأمكن اجتياز `min_grounded_facts` بخلفية محضة بينما الواقعة
    الإخبارية الفعلية سقطت لعجز سند — يُفرغ هذا العتبة من معناها (هل الخبر
    الجديد كافٍ لمقال). فالعدّ العددي وحده لا يكفي: يُشترط أيضًا وجود واقعة
    واحدة على الأقل غير مرجعية (`is_reference` غير صادقة) ضمن `grounded` —
    خبر فعلي لا خلفية وحدها."""
    acfg = cfg.get("article", {}) or {}
    min_grounded = int(acfg.get("min_grounded_facts", 2))
    if len(grounded) < min_grounded:
        return False, (f"عدد الوقائع المسندة ({len(grounded)}) دون الحد الأدنى "
                       f"({min_grounded}) — القاعدة 7: لا مقال")
    if not any(not g.get("is_reference") for g in grounded):
        return False, ("كل الوقائع المسندة خلفية/مرجعية (سيرة أو تاريخ سابق موثَّق "
                       "سلفًا) — لا خبر جديد فعلي يستحق مقالًا (تعليق الموافقة، البند 6)")
    return True, f"{len(grounded)} واقعة مسندة"


# ──────────────────────────── اختيار السؤال ────────────────────────────

CHOOSE_QUESTION_SYSTEM = """أنت تختار عنوان مقال بصيغة سؤال، من وقائع مسندة
بمصادر مستقلة معطاة لك حصرًا — لا من أي معلومة أخرى.

اقرأ الوقائع أولًا، ثم استنتج منها السؤال الذي تُجيب عنه فعلًا — لا سؤالًا
تتمناه أو تعده الوقائع بالإجابة عنه لاحقًا. صغه بصيغة استفهام جاذبة ودقيقة
بالعربية الفصيحة، بلا مبالغة ولا وعد يتجاوز ما تحمله الوقائع المعطاة.

إن كانت الوقائع المعطاة لا تكفي لسؤال قائم بذاته له إجابة واضحة فيها،
اضبط cannot_answer: true بدل اختلاق سؤال ضعيف الصلة.

استخدم أداة choose_question دائمًا."""

CHOOSE_QUESTION_SCHEMA = {
    "name": "choose_question",
    "description": "يختار عنوانًا بصيغة سؤال تُجيب عنه الوقائع المعطاة حصرًا",
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "cannot_answer": {
                "type": "boolean",
                "description": "true إن كانت الوقائع المعطاة لا تكفي لسؤال قائم بذاته",
            },
        },
        "required": ["question", "cannot_answer"],
    },
}


def _choose_question(grounded: list[dict], cfg, retries: int = 2) -> tuple[str | None, str]:
    """يختار السؤال من `grounded` حصرًا — القائمة التي مرّت بوابة الكفاية
    أعلاه بالفعل. الدالة لا ترى أي واقعة لم تجتز السند، فلا سبيل لاختيار
    سؤال يعتمد على واقعة ضعيفة السند (انظر توثيق _sufficiency)."""
    if not grounded:
        return None, "مرحلة اختيار السؤال — لا وقائع مسندة لاختيار سؤال منها"
    acfg = cfg.get("article", {}) or {}
    model = acfg.get("model", "claude-sonnet-5")
    client = _client()
    facts_block = "\n".join(f"- {f['text']}" for f in grounded)
    prompt = f"الوقائع المسندة المتاحة حصرًا:\n\n{facts_block}"

    for attempt in range(1, retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=300,
                tools=[CHOOSE_QUESTION_SCHEMA],
                tool_choice={"type": "tool", "name": "choose_question"},
                system=CHOOSE_QUESTION_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            writer.record_usage(resp, model)
        except APIError as exc:
            log.warning("محاولة %d/%d فشلت في اختيار السؤال: %s", attempt, retries, exc)
            continue
        data = next((b.input for b in resp.content
                    if getattr(b, "type", "") == "tool_use"), None)
        if not isinstance(data, dict):
            continue
        if data.get("cannot_answer"):
            return None, ("مرحلة اختيار السؤال — امتناع: الوقائع المسندة لا تكفي "
                          "لسؤال قائم بذاته (القاعدة 7)")
        question = str(data.get("question") or "").strip()
        if question:
            return question, ""

    return None, "مرحلة اختيار السؤال — تعذّر الحصول على رد صالح من النموذج"


# ──────────────────────────── الصياغة (برومبت مستقل — القاعدة 6) ────────────

# لا نستعمل writer.SYSTEM_PROMPT ولا writer._call_model هنا (القاعدة 6:
# "writer.py وSYSTEM_PROMPT لا تُمسّان ولا تُنسخ قواعدهما — سياستان
# معلنتان، لا واحدة مخفَّفة"). writer._call_model يُحمِّل writer.SYSTEM_PROMPT
# داخليًا بلا معامل يسمح باستبداله، فحتى استدعاؤه المجرد كان سيسحب سياسة
# verify_draft.py التحريرية إلى هذا المسار. الآلية المشتركة المُعاد
# استعمالها فعلًا: writer.record_usage/usage_summary (محاسبة، لا سياسة)،
# writer._extract_json (استخراج JSON احتياطي، ميكانيكي)، وwriter.WriteFailure/
# classify_write_error (تصنيف عطل الشبكة، ميكانيكي أيضًا).
DRAFT_SYSTEM_TEMPLATE = """أنت محرر يكتب مقالًا عربيًا لمنشور فيسبوك، عنوانه
سؤال يُجاب عنه من وقائع مسندة بمصادر مستقلة أُعطيتَها فقط — لا من معرفتك
الخاصة ولا من أي مصدر آخر.

القواعد:
1. كل واقعة تكتبها يجب أن تكون من الوقائع المعطاة حصرًا. لا تخترع تفصيلة
   ولا تُكمل من عندك ما لم تذكره الوقائع المعطاة.
2. الآراء المعطاة (إن وُجدت) رأي صاحب الموجز فقط — لا تنقلها حرفيًا، أعد
   صياغتها بإيجاز وانسبها صراحة بالصيغة: "{opinion_phrase} ..." — لا
   تقدّمها خبرًا ولا تخلطها بالوقائع المسندة.
3. لا تحليل من عندك ولا تفسير ثالث: كل تفسير في المتن إما من الوقائع
   المسندة نفسها، أو رأي منسوب صراحة لصاحب الموجز كما في القاعدة 2 —
   لا صوت ثالث تضيفه أنت.
4. المتن يجب أن يجيب عن السؤال المعطى صراحة بالوقائع المسندة — لا يفتح
   سؤالًا جديدًا ولا يتهرّب منه.
5. عربية فصيحة مبسّطة، بلا نسخ حرفي من أي نص مصدر — أعد الصياغة بالكامل.
6. لا تذكر اسم المصدر داخل المتن — يُكتب أسفل المنشور تلقائيًا.

استخدم أداة write_article دائمًا."""

ARTICLE_POST_SCHEMA = {
    "name": "write_article",
    "description": "يسلّم مقال «مقال من المصادر» الجاهز بحقوله المهيكلة",
    "input_schema": {
        "type": "object",
        "properties": {
            "image_headline": {"type": "string",
                               "description": "عنوان مكثّف يُكتب على الصورة"},
            "post_title": {"type": "string"},
            "post_body": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "category": {"type": "string", "enum": writer.CATEGORIES},
        },
        "required": ["post_title", "post_body", "category"],
    },
}

DRAFT_USER_TEMPLATE = """السؤال-العنوان: {question}

وقائع مسندة بمصدرين مستقلين فأكثر — ابنِ منها المتن حصرًا:

{facts_block}

نصوص المصادر المستقلة التي أيّدت هذه الوقائع:

{source_texts}
{opinions_block}
املأ حقول أداة write_article من هذه الوقائع والنصوص (والرأي المنسوب إن
وُجد) حصرًا — لا معرفة سابقة ولا مصدر ثالث:

• image_headline — عنوان مكثّف يُكتب على الصورة، بحد أقصى {max_chars} حرفًا، بلا نقطة
• post_title — طابق السؤال-العنوان أعلاه بصياغة جاذبة، بصيغة سؤال
• post_body — متن يجيب عن السؤال بالوقائع المسندة، {post_length}
• hashtags — {hashtags_count} هاشتاقات عربية، بلا رمز # وبـ _ بدل المسافة
• category — التصنيف الأنسب

نبرة الكتابة المطلوبة: {tone}"""


def _call_draft_model(prompt: str, system_text: str, cfg, retries: int = 3) -> dict:
    """نداء شبكة مستقل عن writer._call_model (انظر التوثيق أعلاه) — نفس
    نمط إعادة المحاولة/تصنيف العطل، بنظام توجيه مُمرَّر لا مُحمَّل داخليًا."""
    acfg = cfg.get("article", {}) or {}
    client = _client()
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            resp = client.messages.create(
                model=acfg.get("model", "claude-sonnet-5"),
                max_tokens=int(acfg.get("max_tokens", 3000)),
                tools=[ARTICLE_POST_SCHEMA],
                tool_choice={"type": "tool", "name": "write_article"},
                system=[{
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": prompt}],
            )
            writer.record_usage(resp, acfg.get("model", "claude-sonnet-5"))

            if getattr(resp, "stop_reason", "") == "max_tokens":
                raise ValueError("تجاوز الرد السقف — ارفع article.max_tokens")

            data = next((b.input for b in resp.content
                        if getattr(b, "type", "") == "tool_use"), None)
            if data is None:
                text = "".join(b.text for b in resp.content
                               if getattr(b, "type", "") == "text")
                data = writer._extract_json(text)
            return data
        except (APIError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            log.warning("محاولة %d/%d فشلت في صياغة المقال: %s", attempt, retries, exc)
            time.sleep(2 * attempt)

    reason = writer.classify_write_error(last_error) if last_error else "عطل API"
    raise writer.WriteFailure(reason, str(last_error) if last_error else "")


def _opinions_block(opinions: list[dict], cfg) -> str:
    """القاعدة 2 و5: رأي صاحب الموجز يدخل البرومبت كمادة خام يُطلب من
    النموذج إعادة صياغتها ونسبتها — لا نقلًا حرفيًا (يصطدم بالقاعدة 5)،
    ولا نداء صياغة منفصل لكل رأي (تعليق التنفيذ الأخير: مكلف بلا داعٍ ما
    دام برومبت الصياغة الواحد يعرف أصلًا أيّها رأي وأيّها واقعة)."""
    if not opinions:
        return ""
    acfg = cfg.get("article", {}) or {}
    phrase = acfg.get("opinion_attribution_phrase", "وترى الصفحة أن")
    lines = "\n".join(f"- {o['text']}" for o in opinions)
    return (f"\nرأي صاحب الموجز (أعد صياغته بإيجاز ضمن المتن، منسوبًا بصيغة "
           f"\"{phrase}...\" — لا تنقله حرفيًا ولا تقدّمه خبرًا):\n{lines}\n")


def _source_docs(grounded: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for f in grounded:
        for s in f.get("sources", []):
            if s["name"] in seen or not s.get("text"):
                continue
            seen.add(s["name"])
            out.append({"name": s["name"], "text": s["text"]})
    return out


def _draft_article(grounded: list[dict], opinions: list[dict], question: str,
                   cfg, retries: int = 3) -> tuple[dict | None, str]:
    w = cfg.get("writer", {})
    acfg = cfg.get("article", {}) or {}
    docs = _source_docs(grounded)
    facts_block = "\n".join(f"- {f['text']}" for f in grounded)
    phrase = acfg.get("opinion_attribution_phrase", "وترى الصفحة أن")
    system_text = DRAFT_SYSTEM_TEMPLATE.format(opinion_phrase=phrase)
    prompt = DRAFT_USER_TEMPLATE.format(
        question=question,
        facts_block=facts_block,
        source_texts=extract.format_for_prompt(docs),
        opinions_block=_opinions_block(opinions, cfg),
        max_chars=cfg.path("image.headline_max_chars", 95),
        post_length=w.get("post_length", "60 إلى 90 كلمة"),
        hashtags_count=w.get("hashtags_count", 4),
        tone=w.get("tone", "خبري رصين، عربي فصيح مبسّط، بلا مبالغة أو إثارة"),
    )

    try:
        data = _call_draft_model(prompt, system_text, cfg, retries)
    except writer.WriteFailure as exc:
        log.warning("فشل تقني في صياغة مقال من المصادر (%s): %s", exc.reason, exc.detail)
        return None, f"مرحلة الصياغة — فشل تقني ({exc.reason}): {exc.detail}"

    tags = [str(t).lstrip("#").replace(" ", "_") for t in (data.get("hashtags") or [])]
    category = data.get("category") if data.get("category") in writer.CATEGORIES else "عالم"
    written = {
        "angle": "تفسير",
        "analysis": "",  # لا تحليل من عندنا — القاعدة 3، لا صوت ثالث
        "urgent": False,
        "category": category,
        "image_headline": str(data.get("image_headline") or data.get("post_title", "")
                             ).strip().rstrip("."),
        "post_title": str(data.get("post_title", "")).strip(),
        "post_body": str(data.get("post_body", "")).strip(),
        "hashtags": tags,
    }
    if not written["post_title"] or not written["post_body"]:
        return None, "مرحلة الصياغة — رد ناقص: بلا عنوان أو متن"
    return written, ""


# ──────────────────────────── الأنبوب الكامل ────────────────────────────


def _new_outcome() -> dict:
    return {"produced": False, "reason": "", "question": "", "dropped": [],
           "sources": [], "unanswered": [], "answered_questions": [], "diffs": [],
           "trail": [], "draft_id": None,
           "image_source_name": None, "image_source_link": None}


def write_article(body: str, issue_number: int, cfg) -> dict:
    """يلتقط أي انهيار غير متوقع فلا يصل traceback إلى تعليق الـ Issue."""
    try:
        return _write_article(body, issue_number, cfg)
    except Exception:
        log.exception("انهيار غير متوقع أثناء كتابة مقال من المصادر")
        outcome = _new_outcome()
        outcome["reason"] = "حدث خطأ غير متوقع — راجع سجلات Actions للتفاصيل"
        return outcome


def _write_article(body: str, issue_number: int, cfg) -> dict:
    acfg = cfg.get("article", {}) or {}
    days = int(acfg.get("days", 21))
    query_max_words = int(acfg.get("query_max_words", 5))
    min_confirm = int(acfg.get("min_confirm_sources", 2))
    max_statements = int(acfg.get("max_statements", 8))
    max_questions = int(acfg.get("max_questions", 5))

    outcome = _new_outcome()

    extracted, err = extract_brief(body, cfg)
    if not extracted:
        outcome["reason"] = err or "تعذّر استخراج بنية الموجز"
        return outcome

    raw_statements = extracted.get("statements")
    if not isinstance(raw_statements, list):
        raw_statements = extracted.get("claims")  # احتياط اسم حقل شائع
    statements = normalize_statements(raw_statements)
    if not statements:
        outcome["reason"] = "تعذّرت قراءة بنية الرد — لا وقائع أو آراء صالحة"
        return outcome

    questions_from_brief = normalize_questions(extracted.get("questions"))[:max_questions]
    facts_raw = [s for s in statements if s["kind"] == "واقعة"][:max_statements]
    opinions = [s for s in statements if s["kind"] != "واقعة"]

    dropped: list[dict] = []
    diffs: list[dict] = []
    grounded: list[dict] = []
    sources_seen: list[dict] = []
    trail: list[dict] = []
    # البند 7 (تعليق الموافقة الثاني): الصلة بين حدث سُمّي حديثًا وكيان
    # الموجز الأصلي ليست بديهية — تُضاف سؤالًا يُبحث بنفس آلية أسئلة
    # الموجز (البند 5) حصرًا، لا تُفترض صامتة
    link_questions: list[dict] = []

    for f in facts_raw:
        if f.get("is_unnamed_event"):
            # تسمية الحدث أولًا (البند 3 من التشخيص) — الأدلة التي سمّته
            # هي نفسها أدلة الحكم على سنده، لا بحث إضافي مكرَّر (انظر
            # توثيق _name_event)
            named_text, named_docs, named_supporting, name_trail = _name_event(f, cfg)
            trail.extend(name_trail)
            if not named_text:
                dropped.append({
                    "text": f["text"],
                    "reason": ("تعذّر تسمية الحدث الذي أشار إليه موجزي — بحث موسّع "
                              "بالكيانات والتاريخ لم يكشف ما وقع فعليًا"),
                })
                continue
            diffs.append({"brief": f["text"], "sources_say": named_text})
            unique = set(named_supporting)
            if len(unique) < min_confirm:
                dropped.append({
                    "text": named_text,
                    "reason": (f"سند غير كافٍ بعد تسمية الحدث ({len(unique)} من "
                              f"{min_confirm} مصادر مستقلة مطلوبة)"),
                })
                continue
            fact_sources = _grounded_sources(named_supporting, named_docs, [])
            grounded.append({**f, "text": named_text, "sources": fact_sources})
            link_questions.append({
                "text": f"ما الصلة بين «{named_text}» و«{f['text']}»؟",
                "entities": f.get("entities") or [],
                "is_reference": False,
            })
        else:
            query = evidence.build_query_for_claim(f, query_max_words)
            ranked = evidence.search(query, cfg, days, unrestricted=f.get("is_reference", False))
            relevance_text = evidence._entities_text(f) or f["text"]
            docs, basis = evidence.gather_evidence(ranked, cfg, relevance_text)
            supporting = _support_sources(f["text"], docs, cfg) if docs else []
            unique = set(supporting)
            trail.append({"stage": "واقعة", "query": query, "basis": basis,
                          "sources": [d["name"] for d in docs],
                          "raw_count": getattr(ranked, "raw_count", None),
                          "matched_count": getattr(ranked, "matched_count", None),
                          "fetch_failures": getattr(docs, "fetch_failures", []),
                          "outcome": (f"مسندة بـ{len(unique)} مصدر مستقل" if len(unique) >= min_confirm
                                     else f"سند غير كافٍ ({len(unique)}/{min_confirm})")})
            if len(unique) < min_confirm:
                dropped.append({
                    "text": f["text"],
                    "reason": (f"سند غير كافٍ ({len(unique)} من {min_confirm} "
                              "مصادر مستقلة مطلوبة)"),
                })
                continue
            fact_sources = _grounded_sources(supporting, docs, ranked)
            grounded.append({**f, "sources": fact_sources})

        for s in grounded[-1]["sources"]:
            if not any(s["name"] == x["name"] for x in sources_seen):
                sources_seen.append({"name": s["name"], "link": s["link"]})

    outcome["dropped"] = dropped
    outcome["diffs"] = diffs

    # البند 5 + 7: أسئلة الموجز الصريحة وسؤال الصلة المُصنَّع (إن وُجد) —
    # كلاهما مهمة بحث فعلية بنفس آلية الوقائع (بحث ← قراءة ← حكم سند)، لا
    # حصيلة فشل تُنسخ بلا بحث
    unanswered: list[dict] = []
    answered_questions: list[dict] = []
    for q in questions_from_brief + link_questions:
        query = evidence.build_query_for_claim(q, query_max_words)
        ranked = evidence.search(query, cfg, days, unrestricted=q.get("is_reference", False))
        relevance_text = evidence._entities_text(q) or q["text"]
        docs, basis = evidence.gather_evidence(ranked, cfg, relevance_text)
        answer = _ask_answer_model(q["text"], docs, cfg) if docs else None
        supporting = answer["supporting"] if answer else []
        unique = set(supporting)
        answered_ok = bool(answer) and len(unique) >= min_confirm
        trail.append({"stage": "سؤال", "query": query, "basis": basis,
                      "sources": [d["name"] for d in docs],
                      "raw_count": getattr(ranked, "raw_count", None),
                      "matched_count": getattr(ranked, "matched_count", None),
                      "fetch_failures": getattr(docs, "fetch_failures", []),
                      "outcome": (f"أُجيب ومسندة بـ{len(unique)} مصدر" if answered_ok
                                 else "لم تُجب عنه النصوص المقروءة" if not answer
                                 else f"سند غير كافٍ ({len(unique)}/{min_confirm})")})
        if not answered_ok:
            # تفريق «لم يسمِّ النموذج مصدرًا» عن «سمّى مصدرًا لم يُطابَق» في
            # التقرير نفسه (تعليق التنفيذ على Issue #364، البند 3) — كلاهما
            # عطل تسمية من رد النموذج، لا غياب سند فعلي كما توحي "0 من N"
            # المجردة
            naming_issue = answer.get("naming_issue") if answer else None
            if not answer:
                reason = "بُحث ولم توجد نصوص تجيب عنه بوضوح"
            elif naming_issue == "no_source_named":
                reason = (f"سند غير كافٍ ({len(unique)} من {min_confirm} مصادر مستقلة "
                          "مطلوبة) — النموذج أجاب لكن لم يسمِّ أي مصدر مؤيِّد "
                          "(عطل تسمية من رد النموذج، لا غياب سند فعلي)")
            elif naming_issue == "unmatched_source":
                reason = (f"سند غير كافٍ ({len(unique)} من {min_confirm} مصادر مستقلة "
                          "مطلوبة) — النموذج سمّى مصادر لكنها لم تطابق أي مصدر "
                          "معطى (عطل تسمية من رد النموذج، لا غياب سند فعلي)")
            else:
                reason = f"سند غير كافٍ ({len(unique)} من {min_confirm} مصادر مستقلة مطلوبة)"
            unanswered.append({"text": q["text"], "reason": reason})
            continue
        fact_sources = _grounded_sources(supporting, docs, ranked)
        answered_questions.append({"text": q["text"], "answer": answer["text"],
                                   "sources": fact_sources})
        grounded.append({"text": answer["text"], "kind": "واقعة",
                         "entities": q.get("entities") or [], "is_unnamed_event": False,
                         "is_reference": q.get("is_reference", False), "sources": fact_sources})
        for s in fact_sources:
            if not any(s["name"] == x["name"] for x in sources_seen):
                sources_seen.append({"name": s["name"], "link": s["link"]})

    outcome["unanswered"] = unanswered
    outcome["answered_questions"] = answered_questions
    outcome["trail"] = trail

    ok, reason = _sufficiency(grounded, cfg)
    if not ok:
        outcome["reason"] = reason
        return outcome

    question, q_reason = _choose_question(grounded, cfg)
    if not question:
        outcome["reason"] = q_reason
        return outcome
    outcome["question"] = question

    written, w_reason = _draft_article(grounded, opinions, question, cfg)
    if written is None:
        outcome["reason"] = w_reason
        return outcome

    source_texts = [s["text"] for f in grounded for s in f.get("sources", []) if s.get("text")]
    draft_text = "\n".join(filter(None, [
        written["image_headline"], written["post_title"], written["post_body"],
    ]))
    max_shared = int(acfg.get("max_shared_run_words", 7))
    # فحص النسخ اللفظي (القاعدة 5) — verify_draft.check_originality مُعاد
    # استعمالها كما هي بعتبتها واستثناءاتها، لا نسخة موازية
    ok_orig, orig_reason = verify_draft.check_originality(
        draft_text, body, source_texts, max_shared)
    if not ok_orig:
        outcome["reason"] = f"مرحلة الصياغة — امتناع: {orig_reason}"
        return outcome

    outcome["sources"] = sources_seen

    publishers = [s["name"] for s in sources_seen]
    primary_link = sources_seen[0]["link"] if sources_seen else ""
    central_text = grounded[0]["text"]

    art = Article(
        title=central_text, link=primary_link, summary=question,
        source_name=publishers[0] if publishers else "", region="global",
        weight=1.0, published=datetime.now(timezone.utc),
        publisher=publishers[0] if publishers else "", cluster_sources=publishers,
    )

    draft_id = hashlib.sha1(
        f"article:{issue_number}:{question}".encode("utf-8")).hexdigest()[:12]

    # الصورة: نفس آلية verify_draft._image_candidates حرفيًا — مرشَّحات من
    # مصادر مسندة فعلًا فقط، وfallback_provider يبحث في Wikimedia/Openverse
    # حصرًا (imagesearch.find_images) لا Google Images (CLAUDE.md)
    image_ranked = verify_draft._image_candidates(grounded)
    image_urls = [u for u, _, _ in image_ranked]

    image_name = f"{datetime.now(timezone.utc):%Y-%m-%d}/{draft_id}.jpg"
    image_rel = f"drafts/{image_name}"
    shot: dict = {}
    try:
        imaging.build_post_image(
            headline=written["image_headline"] or written["post_title"],
            category=written["category"],
            urgent=False,
            image_urls=image_urls,
            publisher=publishers,
            bucket="serious",
            fallback_provider=lambda: find_images(central_text, cfg),
            cfg=cfg,
            out_path=DRAFTS_DIR / image_name,
            report=shot,
        )
    except Exception as exc:  # noqa: BLE001 — امتناع صريح مُسجَّل لا انهيار صامت
        outcome["reason"] = f"مرحلة بناء صورة المسودة — فشل: {exc}"
        return outcome

    draft = {
        "id": draft_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "review_issue": None,
        "origin": DRAFT_ORIGIN,
        "article_issue": issue_number,
        "score": 0.0,
        "bucket": "serious",
        "analysed_sources": publishers,
        "trend_score": 0.0,
        "velocity": 0.0,
        "age_hours": 0.0,
        "is_followup": False,
        "state_media": False,
        "has_photo": bool(shot.get("used_original")),
        "source": {
            "title": question,
            "link": primary_link,
            "publisher": publishers[0] if publishers else "",
            "publishers": publishers,
            "region": "global",
            "image_url": image_urls[0] if image_urls else None,
            "image_candidates": image_urls,
        },
        "arabic": written,
        "caption": writer.build_caption(written, art, cfg),
        "image": image_rel,
        "reel": None,
        "reel_spec": {
            "headline": written["image_headline"] or written["post_title"],
            "category": written["category"],
            "urgent": False,
            "image_candidates": image_urls,
        },
    }
    store.save_draft(draft)

    if shot.get("used_original") and image_ranked:
        outcome["image_source_name"] = image_ranked[0][1]
        outcome["image_source_link"] = image_ranked[0][2]

    outcome.update({
        "produced": True,
        "reason": f"صيغ مقال من {len(grounded)} واقعة مسندة",
        "draft_id": draft_id,
    })
    return outcome


def build_report(outcome: dict) -> str:
    """التقرير المختصر المطلوب: السؤال المختار، المصادر المقروءة بروابطها،
    الأسئلة المُجابة بحثًا وما بقي بلا إجابة، ما سقط من الموجز لانعدام
    السند، أين خالفت المصادرُ الموجز — لا جدول أحكام كما في
    verify.build_report — وسجلّ trail الكامل (تعليق الموافقة الثاني، البند
    4): كل استعلام بحث في كل مرحلة (تسمية/واقعة/سؤال) مع مصادره وحصيلته،
    فبلا هذا السجل الحكم على سلوك السلّم تخمين لا تحقق."""
    lines = ["### 📰 مقال من المصادر", ""]
    if outcome["produced"]:
        lines.append(f"✅ {outcome['reason']} (المعرّف `{outcome['draft_id']}`) — "
                     "ستظهر في أقرب Issue مراجعة يفتحه البوت بعد رفع المسودة.")
        if outcome.get("image_source_link"):
            name = outcome.get("image_source_name") or "مصدر مسند"
            lines.append(f"🖼️ مصدر الصورة: [{name}]({outcome['image_source_link']})")
    else:
        lines.append(f"❌ لم يُصَغ مقال — {outcome['reason']}")

    if outcome.get("question"):
        lines += ["", f"**السؤال المختار:** {outcome['question']}"]

    if outcome.get("sources"):
        lines += ["", "**المصادر المقروءة:**"]
        lines += [f"- [{s['name']}]({s['link']})" if s.get("link") else f"- {s['name']}"
                 for s in outcome["sources"]]

    if outcome.get("answered_questions"):
        lines += ["", "**أسئلتي التي أجبتُ عنها بحثًا:**"]
        lines += [f"- {q['text']} ← {q['answer']}" for q in outcome["answered_questions"]]

    if outcome.get("unanswered"):
        lines += ["", "**ما بقي بلا إجابة (بُحث فعليًا ولم يُوجد ما يكفي):**"]
        lines += [f"- {q['text']} — {q['reason']}" for q in outcome["unanswered"]]

    if outcome.get("dropped"):
        lines += ["", "**ما سقط من موجزي لانعدام السند:**"]
        lines += [f"- {d['text']} — {d['reason']}" for d in outcome["dropped"]]

    if outcome.get("diffs"):
        lines += ["", "**أين خالفت المصادرُ موجزي:**"]
        lines += [f"- موجزي: «{d['brief']}» — المصادر: «{d['sources_say']}»"
                 for d in outcome["diffs"]]

    if outcome.get("trail"):
        lines += ["", "<details><summary><strong>سجلّ البحث الكامل (trail)</strong> "
                      f"— {len(outcome['trail'])} استعلامًا</summary>", ""]
        for t in outcome["trail"]:
            srcs = "، ".join(t.get("sources") or []) or "لا مصادر"
            # عدد النتائج قبل التصفية بالصلة وبعدها (البند 1، تعليق العطل
            # الثاني): يشرح لماذا سقط استعلام لمصدر واحد رغم تغطية واسعة —
            # None حين لم يُجرَ بحث أصلًا (fake/مسار بلا SearchResult)
            counts = ""
            if t.get("raw_count") is not None:
                counts = f" ({t['raw_count']} خام ← {t.get('matched_count', '؟')} مطابق)"
            lines.append(f"- **[{t['stage']}]** `{t['query']}`{counts} → {t['basis']} — "
                         f"{t.get('outcome', '')} (المصادر: {srcs})")
            for fail in t.get("fetch_failures") or []:
                name, reason, link = fail.get("name", "؟"), fail.get("reason", ""), fail.get("link", "")
                label = f"[{name}]({link})" if link else name
                lines.append(f"  - ⚠️ فشل جلب {label}: {reason}")
            # عيّنة عناوين رفضها فلتر الصلة — مرحلة التسمية المباشرة وحدها
            # (البند 4، تعليق الموافقة الثالث على Issue #361)
            if t.get("rejected_titles"):
                lines.append("  - 🚫 عيّنة عناوين رُفضت بالصلة: " +
                             "؛ ".join(t["rejected_titles"]))
        lines.append("</details>")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="اكتب مقالًا من موجز ملصق في Issue")
    parser.add_argument("--issue", type=int, required=True, help="رقم الـ Issue")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")

    cfg = load_config()
    body = review.fetch_issue_body(args.issue)
    if not body.strip():
        review.comment(args.issue,
                       "### 📰 لا نص\nالـ Issue لا يحوي موجزًا لكتابة مقال منه.")
        return 0

    outcome = write_article(body, args.issue, cfg)
    report = build_report(outcome)
    review.comment(args.issue, f"{report}\n\n<sub>💵 {writer.usage_summary()}</sub>")

    draft_id = outcome.get("draft_id")
    output_path = os.environ.get("GITHUB_OUTPUT")
    if draft_id and output_path:
        with open(output_path, "a", encoding="utf-8") as fh:
            fh.write(f"draft_id={draft_id}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
