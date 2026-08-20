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
    python -m src.article --issue 348 --baseline   # + سجّل خط أساس في state/
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
from itertools import zip_longest
from pathlib import Path

from anthropic import Anthropic, APIError

from . import evidence, extract, imaging, review, store, verify_draft, writer
from .config import DRAFTS_DIR, STATE_DIR, env, load_config
from .imagesearch import find_images
from .request import norm_tokens
from .sources import Article

log = logging.getLogger("article")

DRAFT_ORIGIN = "article"

# القاعدة 2: تمييز حدّي بمعيار دلالي واحد — واقعة تدّعي وقوع حدث/رقم محدَّد،
# أو رأي يقوّم أو يفسّر أو يطرح سؤالًا مفتوحًا كموقف. "تصريح" تصنيف ثالث
# أُضيف لاحقًا (تشخيص Issue #373، الجولة الثالثة عشرة، البند 1): نقل تصريح/
# مقابلة/بيان لمتحدث واحد بعينه في مناسبة واحدة — يُستخرَج كعنصر واحد بمكوّناته
# مجتمعة، لا يُفكَّك إلى عدة "واقعة" منفصلة كل منها يتنافس وحده على عتبة
# min_confirm_sources (الشاهد المُبلَّغ: تصريح واحد يفنّد إسلامًا مزعومًا
# استُخرج منه 4 "وقائع" مستقلة، فتوزّع سند مصدر واحد فعلي يؤيّد التصريح كاملًا
# على أربع محاولات منفصلة بلا أي منها يكتمل، رغم أن المصدر نفسه أيَّد ثلاثة
# مكوّنات في ثلاثة استعلامات مختلفة). يُعامَل كـ"واقعة" في كل مكان يفصل الرأي
# عن الحقيقة القابلة للتحقق (facts_raw أدناه)، ويختلف عنها فقط في نظام حكم
# السند (_support_sources(is_statement=True) — انظر توثيقها).
WRITEUP_KINDS = ["واقعة", "رأي", "تصريح"]

_DIGIT_RE = re.compile(r"\d")


def _client() -> Anthropic:
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


class _ModelCallResult(dict):
    """نتيجة نداء حكم ثنائي (_ask_naming_model/_ask_answer_model): dict
    فارغ عند الفشل، بنفس زيف None في كل فحص `if not result` قائم — لا كسر
    توافق. call_error (افتراضيًا None، عبر getattr فـ dict/lambda مزيَّفة
    في الاختبارات لا تعرفه تبقى تعمل) يحمل نص الاستثناء حين السبب فشل
    نداء تقني (رفض API، انقطاع شبكة...) لا حكم "لا" فعلي من النموذج —
    تشخيص Issue #373، الجولة الحادية عشرة، البند 2: كلاهما كان يظهر بنفس
    عبارة «لم توجد نصوص تجيب عنه» في trail/التقرير، فامتناع تقني بحت كان
    يُقرأ خطأً كحكم غياب سند."""
    call_error: str | None = None


class _ModelCallList(list):
    """نظير _ModelCallResult لنداء يعيد قائمة (_support_sources) — قائمة
    فارغة عند الفشل، بنفس زيف [] القائم، وcall_error لسبب الفشل التقني."""
    call_error: str | None = None


# ──────────────────────────── استخراج بنية الموجز ────────────────────────────

WRITEUP_EXTRACT_SYSTEM = """أنت تقرأ موجزًا تحريريًا كتبه صاحب صفحة إخبارية —
فكرته وما يعرفه ورأيه — لتستخرج بنيته فقط. لا تحكم على صحته الآن، فذلك يقع
لاحقًا ببحث في مصادر مستقلة.

استخرج:
1. topic: جملة واحدة تلخّص موضوع الموجز كما فهمتَه أنت.
2. statements: كل جملة تحمل معلومة أو موقفًا، مصنّفة:
   - "واقعة": تدّعي وقوع حدث أو رقم محدَّد — "حدث كذا في كذا"
   - "رأي": تقويم أو تفسير أو سؤال مفتوح يطرحه صاحب الموجز كموقف — لا
     ادّعاء وقوع بذاته
   - "تصريح": نقل تصريح أو مقابلة أو بيان لمتحدث واحد بعينه في مناسبة واحدة
     بعينها — كل الجمل التي تنقل مكوّنات هذا التصريح نفسه (ما قاله، ملابساته،
     ما أعلن أنه سيفعله لاحقًا...) تُستخرَج كعنصر "تصريح" واحد لا عدة "واقعة"
     منفصلة: نصه يلخّص مضمون التصريح بأجزائه معًا لا جزءًا واحدًا منه.
     اشترط دومًا **متحدث واحد بعينه ومناسبة واحدة بعينها**: إن نقل الموجز
     تصريحين لمتحدثين مختلفين، أو لنفس المتحدث في مناسبتين مختلفتين، فكل
     تصريح عنصر "تصريح" مستقل بذاته — لا تدمجهما معًا. ولا تُدرِج جملة
     سردية عامة لا تنقل تصريحًا بذاته (كخلفية أو سياق محيط) داخل عنصر
     "تصريح" — تلك تبقى "واقعة" أو تُستبعد بحسب القاعدة أدناه. لكل عنصر
     "تصريح" أيضًا: speaker (اسم المتحدث كما ورد في الموجز حرفيًا)،
     وmerged_excerpts (كل جملة من الموجز حرفيًا كما وردت دُمجت في هذا
     العنصر — للمراجعة البشرية، لا تُعِد صياغتها).
   جملة سردية انتقالية عامة — بلا حدث أو رقم أو تصريح محدَّد، وبلا تقويم أو
   موقف أيضًا — لا تُدرَج ضمن statements إطلاقًا: لا "واقعة" (لا تدّعي وقوع
   شيء محدَّد) ولا "رأي" (ليست تقويمًا ولا موقفًا) ولا "تصريح" (لا تنقل
   تصريحًا بعينه). مثال: "مرّت الأيام وتغيرت الأحوال ومضى من مضى وبقي من
   بقي" — سرد عابر بلا مضمون قابل للتحقق، يُستبعد كليًا لا يُصنَّف بأي
   تصنيف.

   جملة واحدة قد تحمل أكثر من ادّعاء "واقعة" مستقل — افصلها إلى عدة عناصر
   "واقعة"، عنصر لكل ادّعاء، حين يصدق هذا المعيار: لو أمكن تخيّل مصدر مستقل
   يؤكد جزءًا منها ويسكت عن جزء آخر بلا أي تناقض منطقي، فهما ادّعاءان
   مستقلان لا واحد — لكلٍّ سنده الخاص لاحقًا. مثال: "قُصف المطار بالتزامن
   مع زيارة وفد عسكري تركي للموقع للعمل على إعادة تأهيله" ثلاثة ادّعاءات
   (القصف، الزيارة، الغرض من الزيارة) — مصدر قد يؤكد القصف وحده بلا أي ذكر
   للوفد، فهما مستقلان.
   لا تفصل مع ذلك:
   - جملة تصف حدثًا واحدًا بتفاصيله الملازمة له دلاليًا (فاعل وفعل ومكان
     لنفس الحدث) — "انطلقت الاحتجاجات من قرية في الجنوب" تبقى عنصرًا واحدًا.
   - عنصر "تصريح" (أعلاه) — يبقى موحَّدًا بمكوّناته دومًا مهما تعدّدت.
   - رقم أو وصف لا بديل صياغي له ملتصق باسم علم أو حدث بعينه، فهو وحدة
     دلالية واحدة لا تُفكَّك (مثال: "عدة أطنان من مواد نووية مخزَّنة" تبقى
     عنصرًا واحدًا رغم احتوائها رقمًا وفعلًا).
   كل عنصر ناتج عن فصل يحمل كيانات الموقع والتاريخ **المشتركة** بين كل أجزاء
   الجملة الأصلية إلى جانب كيانه المميِّز الخاص في entities — لا كيانه وحده:
   بحث "زيارة وفد عسكري تركي" بلا "مطار أبو الظهور" يبحث عن أي زيارة تركية
   في أي مكان. ولكل عنصر ناتج عن فصل أيضًا split_from: نص الجملة الأصلية
   المركّبة في الموجز حرفيًا كما وردت — اتركه فارغًا لعنصر لم يُفصَل من
   جملة مركّبة.

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
entities وmerged_excerpts لعنصر "تصريح": تُنقل حرفيًا، لا تُعاد صياغتها
أبدًا). لا تُجب عن الأسئلة من معرفتك — استخرجها فقط.

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
                        # للعنصر "تصريح" فقط (اختياريان — لا معنى لهما لواقعة/
                        # رأي، فلا نُلزم بهما كل عنصر): اسم المتحدث، وجمل
                        # الموجز الحرفية التي دُمجت في هذا التصريح الواحد —
                        # تبليغ لا منع (تشخيص Issue #373، الجولة الثالثة عشرة)
                        "speaker": {"type": "string"},
                        "merged_excerpts": {"type": "array", "items": {"type": "string"}},
                        # لعنصر ناتج عن فصل جملة مركّبة إلى عدة "واقعة" فقط
                        # (اختياري — فارغ لعنصر لم يُفصَل): نص الجملة الأصلية
                        # حرفيًا، لتجميع أجزائها في التقرير (split_statements)
                        # — تشخيص Issue #373، الجولة الخامسة عشرة
                        "split_from": {"type": "string"},
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
    speaker = ""
    merged_excerpts: list[str] = []
    split_from = ""
    if isinstance(item, dict):
        raw_speaker = item.get("speaker")
        if isinstance(raw_speaker, str) and raw_speaker.strip():
            speaker = raw_speaker.strip()
        merged_excerpts = _as_entities(item.get("merged_excerpts"))
        raw_split_from = item.get("split_from")
        if isinstance(raw_split_from, str) and raw_split_from.strip():
            split_from = raw_split_from.strip()
    return {"text": text, "kind": kind, "entities": entities,
            "is_unnamed_event": is_unnamed_event, "is_reference": is_reference,
            "speaker": speaker, "merged_excerpts": merged_excerpts,
            "split_from": split_from}


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


# الحالات الثلاث لاتساق التاريخ (تشخيص Issue #373، الجولة الخامسة، البند
# 2): بوول واحد كان يخلط "لا معلومة تاريخ لتُفحص" بـ"تاريخ فُحص وطابق" —
# كلاهما True في التصميم القديم. الفرق حاسم للدمج مع فحص الكيانات في
# _naming_consistent: تخفيف يقبل تسمية بالتاريخ وحده حين يتفق التاريخ صراحةً
# يجب ألا يتحول عرضًا إلى قبول تلقائي لكل حالة "لا تاريخ في dates أصلًا".
DATE_NO_INFO = "no_info"
DATE_MATCH = "match"
DATE_MISMATCH = "mismatch"


def _dates_consistent(named_text: str, dates: list[str], docs: list[dict],
                      window_days: int) -> str:
    """بوابة اتساق التاريخ (تعليق التنفيذ على Issue #364، البند 2): لا تكفي
    مطابقة الكيانات وحدها (فشل «لبّاد» في التشخيص المعتمَد سبق أن غطّته
    _naming_consistent) — حدثٌ لا يقع في تاريخ الإشارة المبهمة الأصلية، أو
    نافذة ضيقة حوله، لا يصلح تسميةً له حتى لو ذكر الكيانات الصحيحة (تشخيص
    التشغيل الحقيقي: حديث جنبلاط 2011 عن حمزة الخطيب ذُكر بثقة رغم أنه ليس
    الحدث المقصود بتاريخ 11 آب 2026).

    التطابق بسنة+شهر إلزامي حين يتوفران في الجانبين؛ فارق اليوم وحده مسموح
    به ضمن window_days (تقارير الوكالات قد تسجّل يوم النشر لا يوم الحدث
    نفسه بفارق يوم أو يومين) — لا فارق شهر أو سنة مهما صغر.

    تعيد إحدى ثلاث حالات صريحة (تشخيص Issue #373، الجولة الخامسة، البند 2 —
    بدل bool واحد كان يُعامِل "لا معلومة" و"تطابق فعلي" معاملة واحدة True):
    DATE_NO_INFO حين لا يحمل الموجز تاريخًا منظَّمًا فعليًا ضمن dates أصلًا
    (مثلًا entity رقمي هو مدة لا تاريخ تقويمي، كـ"15 عامًا") — لا قيد، الحكم
    يرجع لفحص الكيانات وحده كما كان قبل هذا العلاج؛ DATE_MATCH حين يتفق
    تاريخ منظَّم في target مع أحد تواريخ dates ضمن الشروط أعلاه؛ DATE_MISMATCH
    حين يحمل الموجز تاريخًا منظَّمًا فعليًا لكن لا شيء في target يطابقه (بما
    فيها غياب أي تاريخ في target كليًا)."""
    original: list[tuple[int, int | None, int | None]] = []
    for d in dates:
        original += _extract_dates(d)
    if not original:
        return DATE_NO_INFO
    target_text = named_text + " " + " ".join(d.get("text", "") for d in docs)
    target = _extract_dates(target_text)
    for oy, om, od in original:
        for ty, tm, td in target:
            if oy != ty:
                continue
            if om is not None and tm is not None and om != tm:
                continue
            if od is not None and td is not None and abs(od - td) > window_days:
                continue
            return DATE_MATCH
    return DATE_MISMATCH


def _naming_consistent(named_text: str, proper_nouns: list[str], dates: list[str],
                       docs: list[dict], cfg) -> bool:
    """بوابة اتساق (تعليق الموافقة الثاني، البند 2؛ وسّعت بتعليق التنفيذ
    على Issue #364 لتفحص التاريخ لا الكيانات وحدها؛ وخُفِّفت بتعليق التنفيذ
    على Issue #373 الجولة الخامسة، البند 2، لتقبل تاريخًا صريحًا مطابقًا
    وحده بلا كيان): كيانات الواقعة الأصلية يجب أن تُذكر صراحة إما في نص
    التسمية نفسه أو في الوثائق التي استُعملت لتسميته — إلا حين يحسم تاريخ
    منظَّم صريح الأمر (انظر أدناه).

    الدمج مع _dates_consistent (ثلاث حالات، لا bool — انظر توثيقها): تاريخ
    صريح **مطابق** (DATE_MATCH) يكفي وحده للقبول، حتى لو غاب ذكر الكيان
    كليًا — هذا بالضبط تخفيف Issue #373 (خبر حكم الإعدام بحق الأسد لم يذكر
    «حمزة الخطيب» في عنوانه قط، لكن تاريخه 11 آب 2026 يطابق تاريخ الإشارة
    المبهمة الأصلية). تاريخ صريح **غير مطابق** (DATE_MISMATCH) يرفض التسمية
    دومًا — حتى لو ذُكر الكيان الصحيح: هذا بالضبط ما يمنع فشل جنبلاط
    (تحقَّق أعلاه) من الانتكاس؛ تخفيف "تاريخ وحده يكفي" لا يعني أن كيانًا
    صحيحًا بتاريخ متعارض يصير مقبولًا — العكس: تعارض تاريخ صريح دليل حاسم
    أنه حدث آخر، لا احتمال يوازنه ذكر الكيان. غياب أي تاريخ منظَّم أصلًا
    (DATE_NO_INFO) يبقي الحكم بيد فحص الكيانات وحده — بلا تغيير عن السلوك
    قبل هذا العلاج (يحمي فشل «لبّاد»: لا تاريخ في dates أصلًا، فالرفض هنا
    قائم على غياب الكيان لا التاريخ)."""
    entity_ok = True
    if proper_nouns:
        entity_tokens: set[str] = set()
        for e in proper_nouns:
            entity_tokens |= norm_tokens(e)
        if entity_tokens:
            docs_tokens: set[str] = set()
            for d in docs:
                docs_tokens |= norm_tokens(d.get("text", ""))
            entity_ok = bool(entity_tokens & norm_tokens(named_text)) or bool(entity_tokens & docs_tokens)

    acfg = cfg.get("article", {}) or {}
    window_days = int(acfg.get("naming_date_window_days", 2))
    date_state = _dates_consistent(named_text, dates, docs, window_days)
    if date_state == DATE_MATCH:
        return True
    if date_state == DATE_MISMATCH:
        return False
    return entity_ok  # DATE_NO_INFO — تراجع لفحص الكيانات وحده كما كان


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
    {"text":..., "supporting":[...]} عند النجاح، أو قيمة فارغة (None أو
    _ModelCallResult فارغ) — لا تخمين بلا نصوص تسنده. فشل نداء تقني (لا
    حكم "لا" من النموذج) يعيد _ModelCallResult فارغة بـcall_error مضبوطًا
    بنص الاستثناء — استعمل getattr(result, "call_error", None) للتمييز."""
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
            # لا تُضِف temperature: نماذج هذا المشروع ترفضها بـ400
            # ("temperature is deprecated for this model") — Issue #373،
            # الجولة الحادية عشرة. جُرِّبت لتخفيف تذبذب الحكم بين نداءين
            # متطابقين تقريبًا وكسرت النداء صامتًا (يعود ضمن except أدناه
            # بنفس شكل "لا نتيجة" الشرعي) قبل أن تُكتشف كسبب الانهيار.
        )
        writer.record_usage(resp, model)
    except APIError as exc:
        log.warning("فشل نداء تسمية الحدث: %s", exc)
        fail = _ModelCallResult()
        fail.call_error = str(exc)
        return fail

    data = next((b.input for b in resp.content
                if getattr(b, "type", "") == "tool_use"), None)
    if not isinstance(data, dict) or not data.get("named"):
        return None
    text = str(data.get("text") or "").strip()
    if not text:
        return None
    return {"text": text, "supporting": evidence._known_only(data.get("supporting"), docs)}


def _topic_words(topic: str, exclude: list[str], max_words: int) -> list[str]:
    """كلمات من موضوع الموجز العام (topic من extract_brief) — الدرجة
    الثالثة في سلّم _name_event (البند 2، تشخيص Issue #373): مباشر
    (كيان+تاريخ) ثم سياق (سياق مكتشَف+تاريخ) قد يفشلان معًا لأن صفحة تجمع
    الاسم الحرفي بالتاريخ حرفيًا نادرة حتى لحدث غطّته عشرات المصادر —
    اقتران الاسم بالتاريخ يطلب صفحة نادرة، بينما التغطية الفعلية تصف الحدث
    بفعله لا بربطه صراحة بالإشارة المبهمة الأصلية.

    الكلمة من topic — ملخَّص محرَّر كتبه استخراج الموجز — لا من نص الواقعة
    المبهم نفسه: البحث بالوصف المبهم حرفيًا ممنوع بنيويًا (القاعدة 3،
    توثيق _name_event أعلاه) لا تفصيل تنفيذي قابل للتساهل. exclude تُسقط
    كلمات كيانات الواقعة الأصلية (مجرَّبة أصلًا في المرحلة الأولى) كي لا
    تكرّر هذه الدرجة استعلامًا سبق تجربته بالضبط."""
    exclude_norm: set[str] = set()
    for e in exclude:
        exclude_norm |= norm_tokens(e)
    out: list[str] = []
    # 12 كلمة مرشَّحة من topic كافية دومًا: topic "جملة واحدة" محرَّرة (توثيق
    # extract_brief أعلاه) — سقف ثابت سخي بدل معتمِد على len(exclude) حتى لا
    # يُفرغ استبعاد كلمات الكيانات مجموعة المرشحين قبل بلوغ max_words
    for word in evidence.build_query(topic, 12).split():
        if norm_tokens(word) & exclude_norm:
            continue
        out.append(word)
        if len(out) >= max_words:
            break
    return out


def _name_event(statement: dict, cfg, topic: str = "") -> tuple[str | None, list[dict], list[str], list[dict]]:
    """سلّم اتساع لتسمية حدث أشار إليه الموجز دون تسميته (القسم 3 من
    التشخيص المعتمَد على Issue #348، مقلوب الترتيب في تعليق الموافقة
    الثاني، البند 1): كيانات + تاريخ مباشرةً أولًا (الأبسط يُجرَّب قبل
    الأذكى، ويوفّر في الحالات السهلة دورة بحث كاملة) ⟵ عند الفشل: بحث
    مرجعي غير مقيَّد زمنيًا عن سيرة الكيانات لاستخلاص سياق (بلد/جهة) بنداء
    نموذج على تلك النصوص فعلًا (البند 3، لا معرفة النموذج — القاعدة 3) ⟵
    استعلامات تاريخ+سياق مبنية من ذلك السياق المكتشَف ⟵ عند فشل الاثنتين
    معًا: تاريخ + كلمة من موضوع الموجز العام (topic)، درجة أخيرة قبل
    الاستسلام (البند 2، تشخيص Issue #373 — انظر _topic_words).

    بحث بالوصف المبهم حرفيًا ممنوع بنيويًا لا معالَج بإعادة محاولة: كل
    استعلام يُبنى من الكيانات والتاريخ (أو السياق/الموضوع المستخلَص) فقط،
    لا من نص الواقعة المبهم.

    مرحلتا «مباشر» و«سياق» (لا «مرجعي» — بحث عن سيرة الكيان نفسه، فلتر
    الصلة فيه مفيد كما هو) تبحثان بـrequire_relevance=False وتقيسان
    الصلة بـgather_evidence(loose_relevance=True) (البند 1، تشخيص Issue
    #373 — انظر توثيق evidence.search/gather_evidence): الحدث المطلوب قد
    لا يحمل اسم الكيان الذي قاد إليه في عنوانه إطلاقًا، فمطابقة كلمة واحدة
    في العنوان/الملخص فلتر خاطئ لهاتين المرحلتين تحديدًا — التاريخ هو
    الرابط، لا الاسم. بوابة الاتساق أدناه (_naming_consistent) تصير الحارس
    الوحيد على الدقة بدلًا من ذلك، وقد أثبتت أنها تعمل (فشل «لبّاد» في
    التشخيص المعتمَد بالضبط).

    كل تسمية مرشَّحة تمرّ ببوابة اتساق (_naming_consistent، البند 2) قبل
    قبولها: كيانات الواقعة الأصلية يجب أن تُذكر في نص التسمية أو وثائقها،
    وإلا تُرفض ويتابع السلّم — لا إرجاع فوري لتسمية قد تصف حدثًا آخر
    (فشل «لبّاد» في التشخيص المعتمَد).

    يعيد (النص المسمّى أو None، نصوص المصادر التي سمّته، أسماء المصادر
    المؤيِّدة من دورة الاكتشاف هذه فقط، سجلّ trail كامل الخطوات — كل
    استعلام مع مصادره وحصيلته، البند 4).

    تنبيه (تشخيص Issue #373، الجولة السادسة — يُبطل ما وثَّقته نسخة سابقة
    من هذا التعليق): هذه الدالة **اكتشاف فقط**، لا سند. النصوص والمصادر
    المؤيِّدة التي تعيدها لم تعد تُستعمَل وحدها للحكم على كفاية سند الحدث
    المسمّى — استعلام الاكتشاف (كيان الإشارة المبهمة+تاريخها) يبحث عن
    الرابط بين الإشارة والحدث فيبقى ضيقًا بنيويًا حتى حين ينجح (شاهد حقيقي:
    حدث غطّته عشرات المصادر أعاد 4 نتائج فقط من استعلام "حمزة الخطيب 11
    آب"، وتعذّر جلب أغلبها). المستدعي (_write_article) يفتح دورة سند ثانية
    مستقلة بعد نجاح هذه الدالة، مبنية من كيانات النص المسمّى **نفسه** لا
    كيانات الإشارة المبهمة، ويدمج نتائجها مع ما تعيده هذه الدالة
    (_merge_named_evidence) قبل الحكم على الكفاية."""
    acfg = cfg.get("article", {}) or {}
    days = int(acfg.get("days", 21))
    query_max_words = int(acfg.get("query_max_words", 5))
    max_context_terms = int(acfg.get("naming_max_context_terms", 3))
    max_topic_words = int(acfg.get("naming_max_topic_words", 2))

    entities = statement.get("entities") or []
    dates = [e for e in entities if _DIGIT_RE.search(e)]
    proper_nouns = [e for e in entities if not _DIGIT_RE.search(e)]
    trail: list[dict] = []
    if not dates or not proper_nouns:
        return None, [], [], trail

    def _try(stage_name: str, query: str):
        # require_relevance=False/loose_relevance=True حصرًا لمرحلتَي
        # «مباشر» و«سياق» (البند 1 أعلاه) — الاستدعاء الوحيد لكلتيهما
        ranked = evidence.search(query, cfg, days, require_relevance=False)
        docs, basis = evidence.gather_evidence(ranked, cfg, query, loose_relevance=True)
        entry = {"stage": stage_name, "query": query, "basis": basis,
                 "sources": [d["name"] for d in docs],
                 "raw_count": getattr(ranked, "raw_count", None),
                 "matched_count": getattr(ranked, "matched_count", None),
                 "fetch_failures": getattr(docs, "fetch_failures", []),
                 # عدد المرشحين الذين دخلوا الفرز بلا تصفية بالصلة (يساوي
                 # raw_count دومًا هنا بحكم require_relevance=False) — البند
                 # 1، طلب التنفيذ على Issue #373
                 "unfiltered_relevance": True,
                 # أعلى 5 مرشّحين بعد الفرز (اسم/وزن/صلة/درجة مركّبة) — رصد
                 # صرف بلا تعديل الصيغة (تشخيص Issue #373، الجولة الثالثة
                 # عشرة، البند 2، الخيار (و))
                 "top_candidates": getattr(docs, "top_candidates", []),
                 "outcome": ""}
        trail.append(entry)
        if not docs:
            entry["outcome"] = "لا وثائق للتسمية"
            return None
        named = _ask_naming_model(statement["text"], entities, docs, cfg)
        call_error = getattr(named, "call_error", None)
        if call_error:
            # فشل نداء تقني (رفض API، انقطاع شبكة...) لا حكم "لم يُسمَّ" من
            # النموذج — يُفرَّق صراحة في trail بدل الظهور بنفس عبارة الحكم
            # الشرعي (تشخيص Issue #373، الجولة الحادية عشرة، البند 2)
            entry["outcome"] = f"⚠️ فشل نداء النموذج تقنيًا: {call_error}"
            entry["call_error"] = call_error
            return None
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
                      "top_candidates": getattr(docs, "top_candidates", []),
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

    # المرحلة 3 (البند 2، تشخيص Issue #373): تاريخ + كلمة من موضوع الموجز
    # العام — درجة أخيرة قبل الاستسلام، استعلام واحد لكل تاريخ (لا تقاطع
    # كامل مع الكلمات) تفاديًا لتضخّم عدد نداءات البحث
    topic_words = _topic_words(topic, entities, max_topic_words) if topic else []
    for date in dates:
        for term in topic_words:
            result = _try("موضوع", evidence.build_query(f"{term} {date}", query_max_words))
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

# فحص سند "تصريح" (البند 1، تشخيص Issue #373، الجولة الثالثة عشرة): نظام
# منفصل عن SUPPORT_SYSTEM — بلا تخفيف في عتبة min_confirm_sources نفسها،
# لكن بمعيار تأييد أدق: مضمون التصريح يجب أن يرد في النص، لا مجرد وقوع
# المقابلة/الظهور الإعلامي. مصدر يذكر أن المتحدث "أدلى بتصريحات" أو "تحدث
# في مقابلة" بلا نقل مضمونها لا يُحسب مؤيدًا — التساهل هنا كان سيُبطل جوهر
# القاعدة 1 (سند فعلي لا وقوع حدث عام قريب منه).
STATEMENT_SUPPORT_SYSTEM = """أنت تتحقق هل نصوص مصادر مستقلة تسند مضمون
تصريح منسوب لمتحدث بعينه — لا مجرد وقوع مقابلة أو ظهور إعلامي له.

احكم من النصوص المعطاة فقط — لا تستخدم معرفتك الخاصة عن الموضوع. التأييد
يعني أن النص يذكر مضمون التصريح نفسه (ما قاله المتحدث فعليًا) بوضوح يقارب
التصريح المعطى — لا مجرد أنه "أدلى بتصريحات" أو "تحدث في مقابلة" أو "ظهر
إعلاميًا" بلا نقل مضمون ذلك الظهور. مصدر يذكر وقوع المقابلة وحده بلا مضمونها
لا يُحسب مؤيدًا. مصدر لم يذكر التصريح إطلاقًا لا يُحسب مؤيدًا ولا مخالفًا.
أخرج اسم المصدر مجردًا تمامًا كما ورد في وسم '--- المصدر: <الاسم> ---'
فقط، بلا اختراع أسماء جديدة.

استخدم أداة support_fact دائمًا."""


def _support_sources(fact_text: str, docs: list[dict], cfg,
                     is_statement: bool = False) -> list[str]:
    """يعيد أسماء المصادر (من docs فعليًا، لا مُختلَقة) التي تسند fact_text
    — القاعدة 1: هذه القائمة (بعد عدّها) هي ما يقرر مصير الواقعة. فشل نداء
    تقني يعيد _ModelCallList فارغة بـcall_error مضبوطًا (لا [] عاديًا) —
    استعمل getattr(result, "call_error", None) للتمييز عن حكم "لا مصادر"
    فعلي من النموذج.

    is_statement=True (kind == "تصريح") يستعمل STATEMENT_SUPPORT_SYSTEM بدل
    SUPPORT_SYSTEM — نفس العتبة (min_confirm_sources) بلا أي تخفيف، لكن
    معيار تأييد أدق يفحص مضمون التصريح لا وقوع المقابلة وحدها."""
    if not docs:
        return []
    acfg = cfg.get("article", {}) or {}
    model = acfg.get("model", "claude-sonnet-5")
    client = _client()
    label = "التصريح" if is_statement else "الواقعة"
    prompt = f"{label}: {fact_text}\n\nنصوص المصادر:\n\n{_format_docs(docs)}"
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            tools=[SUPPORT_SCHEMA],
            tool_choice={"type": "tool", "name": "support_fact"},
            system=STATEMENT_SUPPORT_SYSTEM if is_statement else SUPPORT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            # لا تُضِف temperature — انظر توثيق _ask_naming_model أعلاه.
        )
        writer.record_usage(resp, model)
    except APIError as exc:
        log.warning("فشل نداء الحكم على السند: %s", exc)
        fail = _ModelCallList()
        fail.call_error = str(exc)
        return fail
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

سؤال بصيغة «كيف/لماذا» (بداية حدث، مساره، أو دوافعه) لا يشترط أن يحوي
النص جملة قائمة بذاتها بصياغة السؤال نفسها ("كيف بدأ..."، "لماذا وقع..."):
خلفية الحدث أو سياقه السردي (متى/كيف وقعت وقائعه الأولى، ما الذي أدّى
إليها) إجابة كافية إن كانت الوقائع التي يطلبها السؤال مذكورة فيها بوضوح
— نفس معيار الإجابة عن سؤال «من/ماذا» بالضبط، لا معيارًا أشدّ. لا ترفض
إجابة موجودة فعلًا في النص لمجرد أن صياغته سردية/خلفية لا صياغة سؤال
وجواب مباشرة.

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
    ترفضها كلها (لا تطابق أي doc معطى)، أو None حين يوجد سند مطابق فعليًا.

    فشل نداء تقني (لا حكم "لم تُجب" من النموذج) يعيد _ModelCallResult فارغة
    بـcall_error مضبوطًا بنص الاستثناء — استعمل
    getattr(result, "call_error", None) للتمييز."""
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
            # لا تُضِف temperature — انظر توثيق _ask_naming_model أعلاه.
        )
        writer.record_usage(resp, model)
    except APIError as exc:
        log.warning("فشل نداء الإجابة عن سؤال الموجز: %s", exc)
        fail = _ModelCallResult()
        fail.call_error = str(exc)
        return fail
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


def _merge_named_evidence(named_docs: list[dict], named_supporting: list[str],
                          support_docs: list[dict], support_supporting: list[str],
                          cfg) -> tuple[list[dict], list[str]]:
    """يدمج أدلة دورة اكتشاف حدث مبهم (named_docs/named_supporting — استعلام
    كيان الإشارة المبهمة+تاريخها، يبحث عن الرابط بين الإشارة والحدث) مع
    أدلة دورة سند ثانية مستقلة بُنيت من كيانات الحدث المسمّى نفسه بعد
    اكتشافه (support_docs/support_supporting) — تشخيص Issue #373، الجولة
    السادسة: استعلام الاكتشاف يبقى ضيقًا بنيويًا حتى حين ينجح (شاهد حقيقي:
    حدث غطّته عشرات المصادر أعاد 4 نتائج فقط من استعلام "حمزة الخطيب 11
    آب"، وتعذّر جلب أغلبها)، فلا يصلح وحده حكمًا على مدى تغطية الحدث الفعلي.

    الدورتان بحثان مستقلان قد يعيدان الناشر نفسه باسمين مختلفين (شاهد
    حقيقي موثَّق سلفًا: "الجزيرة نت" في دورة و"Al Jazeera" في الأخرى) —
    التوحيد داخل gather_evidence لكل دورة على حدة (evidence._canonical_publisher)
    لا يمنع هذا عبر الدورتين معًا. أول دورة تسجّل هوية ناشر تفوز بتمثيله؛ أي
    اسم خام لاحق لنفس الهوية يُستبدَل باسمها الناجي قبل عدّه في supporting —
    وإلا احتُسب مصدر واحد بلغتين مرتين، نقضًا لشرط «مصدران مستقلان» الجوهري
    في المشروع كله (نفس عطل التوحيد الذي عولج بين نتائج البحث الواحد، مكرَّر
    هنا بين نتيجتَي بحث منفصلتين)."""
    merged_docs: list[dict] = []
    survivor_by_canonical: dict[str, str] = {}
    name_to_survivor: dict[str, str] = {}
    for docs in (named_docs, support_docs):
        for d in docs:
            canonical = evidence._canonical_publisher(d["name"], cfg)
            survivor = survivor_by_canonical.get(canonical)
            if survivor is None:
                survivor_by_canonical[canonical] = d["name"]
                name_to_survivor[d["name"]] = d["name"]
                merged_docs.append(d)
            else:
                name_to_survivor[d["name"]] = survivor
    merged_supporting = [name_to_survivor[n] for n in named_supporting + support_supporting
                         if n in name_to_survivor]
    return merged_docs, list(dict.fromkeys(merged_supporting))


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
7. استوعب الوقائع المسندة المعطاة كلها في المتن — لا تختصرها في جملة واحدة
   حين تحتمل فقرة. هذا مقال مطوَّل عن مصادر عدة قُرئت فعليًا، لا خبر عاجل
   مقتضب: كل واقعة معطاة تستحق مساحتها في المتن، لا حذفًا انتقائيًا.
8. الوقائع المعلَّمة بـ"[تصريح لـ...]" تنقل كلام متحدث بعينه — مصدران
   مستقلان أكّدا أنه قال هذا الكلام، لا أن مضمونه صحيح بالضرورة. حين تحمل
   رقمًا أو ادّعاءً عن قدرة عسكرية أو أمنية، وضّح ذلك في صلب الجملة نفسها
   لا في حاشية منفصلة — بصيغة كـ"وزعم فلان أن..." أو "وبحسب ادّعاء
   فلان..." — لا تصغها كأنها معلومة مؤكَّدة من مصدر مستقل.

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


def _facts_block(grounded: list[dict]) -> str:
    """يُعلِّم كل واقعة من kind=='تصريح' بوسم "[تصريح لـ...]" ظاهر للنموذج —
    القاعدة 8 تعتمد عليه ليميّز كلام متحدث بعينه (مسنَد وقوعه، لا صحة
    مضمونه بالضرورة) عن واقعة مسندة من مصدر مستقل مباشرة."""
    lines = []
    for f in grounded:
        if f.get("kind") == "تصريح":
            speaker = f.get("speaker") or "؟"
            lines.append(f"- [تصريح لـ{speaker}] {f['text']}")
        else:
            lines.append(f"- {f['text']}")
    return "\n".join(lines)


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
    facts_block = _facts_block(grounded)
    phrase = acfg.get("opinion_attribution_phrase", "وترى الصفحة أن")
    system_text = DRAFT_SYSTEM_TEMPLATE.format(opinion_phrase=phrase)
    prompt = DRAFT_USER_TEMPLATE.format(
        question=question,
        facts_block=facts_block,
        source_texts=extract.format_for_prompt(docs),
        opinions_block=_opinions_block(opinions, cfg),
        max_chars=cfg.path("image.headline_max_chars", 95),
        # article.post_length مستقل عن writer.post_length (مراجعة بشرية بعد
        # أول نشر): هذا مسار منتج مختلف — تسعة مصادر مقروءة تستحق متنًا
        # أطول من منشور الجمع القصير، لا وريث قيمته
        post_length=acfg.get("post_length", "180 إلى 280 كلمة"),
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
           "trail": [], "draft_id": None, "grounded_count": 0,
           "image_source_name": None, "image_source_link": None,
           "image_report": {}, "opinion_note": "", "originality_notes": [],
           "merged_statements": [], "split_statements": []}


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
    # "تصريح" (البند 1، تشخيص Issue #373، الجولة الثالثة عشرة) واقعة قابلة
    # للتحقق كـ"واقعة" تمامًا — الفارق الوحيد نظام حكم السند
    # (_support_sources(is_statement=True))، لا مكانها هنا (لا تُعامَل كرأي)
    facts_raw = [s for s in statements if s["kind"] in ("واقعة", "تصريح")][:max_statements]
    opinions = [s for s in statements if s["kind"] == "رأي"]
    topic = str(extracted.get("topic") or "")

    # تبليغ الدمج لا منعه (البند 1): كل عنصر "تصريح" يذكر المتحدث وجمل
    # الموجز الحرفية التي دُمجت فيه — يظهر في التقرير بصرف النظر عن مصير
    # سنده لاحقًا، فيراجع المستخدم البشري أي دمج زائف (متحدثان مختلفان أو
    # مناسبتان مختلفتان دُمجا خطأً) ويصححه، بدل منع الدمج بحكم آلي هش
    outcome["merged_statements"] = [
        {"speaker": s["speaker"] or "؟", "text": s["text"],
         "merged_excerpts": s["merged_excerpts"]}
        for s in facts_raw if s["kind"] == "تصريح"
    ]

    # تبليغ الفصل لا منعه (البند 3، تشخيص Issue #373، الجولة الخامسة عشرة):
    # نظير merged_statements أعلاه لكن بالاتجاه المعاكس — عناصر "واقعة"
    # فُصِّلت من جملة مركّبة واحدة تُجمَع هنا بالجملة الأصلية، فيراجع
    # المستخدم البشري أي فصل خاطئ (تفكيك جملة كان يجب أن تبقى موحَّدة أو
    # العكس) دون حكم آلي إضافي يقرر بدلًا عنه
    split_groups: dict[str, list[str]] = {}
    for s in facts_raw:
        if s["split_from"]:
            split_groups.setdefault(s["split_from"], []).append(s["text"])
    outcome["split_statements"] = [
        {"original": original, "parts": parts}
        for original, parts in split_groups.items()
    ]

    opinion_note = ""
    # article.include_opinion (مراجعة بشرية بعد أول نشر): تعطيل الرأي قرار
    # تهيئة مسبق، لا نتيجة فحص سند — يجب أن يبقى مميَّزًا في التقرير عن "ما
    # سقط من موجزي" (تلك الفقرة مخصَّصة لوقائع رُفضت لانعدام سند فعلي)
    if opinions and not acfg.get("include_opinion", True):
        opinion_note = (f"{len(opinions)} رأي في موجزي أُسقط من المتن بقرار تهيئة "
                        "(article.include_opinion=false) — لا لانعدام سند")
        opinions = []

    dropped: list[dict] = []
    diffs: list[dict] = []
    grounded: list[dict] = []
    sources_seen: list[dict] = []
    trail: list[dict] = []
    # كل وثيقة قُرئت فعليًا خلال هذا التشغيل عبر أي مرحلة (واقعة/تسمية/سند/
    # سؤال)، ولو لم تؤيِّد ما استُخرجت لأجله بعينه — مجمَّع إشارة (ب) في فحص
    # الأصالة أدناه (تشخيص Issue #373، الجولة العاشرة): تتابع ورد في مصدر
    # واحد فقط ضمن المصادر المسنِدة قد يظهر أيضًا في وثيقة أخرى قُرئت هنا
    # لم تنتهِ مصدرًا مسنِدًا لأي واقعة (رُفضت صلة، لم تجتز بوابة الاتساق...)
    # — ورودها هناك أيضًا دليل أن التتابع صياغة قياسية متكررة، لا نسخ حرفي
    all_read_docs: list[dict] = []
    # البند 7 (تعليق الموافقة الثاني): الصلة بين حدث سُمّي حديثًا وكيان
    # الموجز الأصلي ليست بديهية — تُضاف سؤالًا يُبحث بنفس آلية أسئلة
    # الموجز (البند 5) حصرًا، لا تُفترض صامتة
    link_questions: list[dict] = []

    for f in facts_raw:
        if f.get("is_unnamed_event"):
            # تسمية الحدث أولًا (البند 3 من التشخيص) — اكتشاف فقط. استعلام
            # الاكتشاف (كيان الإشارة المبهمة+تاريخها) يبحث عن الرابط بين
            # الإشارة والحدث فيبقى ضيقًا بنيويًا حتى حين ينجح (تشخيص Issue
            # #373، الجولة السادسة: حدث غطّته عشرات المصادر أعاد 4 نتائج
            # فقط من استعلام "حمزة الخطيب 11 آب"، وتعذّر جلب أغلبها) — لا
            # يصلح وحده حكمًا على سند الحدث. دورة سند ثانية أدناه، مبنية من
            # كيانات النص المسمّى نفسه لا كيانات الإشارة المبهمة (انظر
            # _merge_named_evidence)، تُدمَج نتائجها مع أدلة الاكتشاف قبل
            # الحكم على الكفاية
            named_text, named_docs, named_supporting, name_trail = _name_event(f, cfg, topic=topic)
            trail.extend(name_trail)
            all_read_docs.extend(named_docs)
            if not named_text:
                dropped.append({
                    "text": f["text"],
                    "reason": ("تعذّر تسمية الحدث الذي أشار إليه موجزي — بحث موسّع "
                              "بالكيانات والتاريخ لم يكشف ما وقع فعليًا"),
                })
                continue
            diffs.append({"brief": f["text"], "sources_say": named_text})

            support_query = evidence.build_query(named_text, query_max_words)
            support_ranked = evidence.search(support_query, cfg, days)
            support_docs, support_basis = evidence.gather_evidence(support_ranked, cfg, named_text)
            all_read_docs.extend(support_docs)
            support_supporting = (_support_sources(named_text, support_docs, cfg)
                                  if support_docs else [])
            support_call_error = getattr(support_supporting, "call_error", None)
            trail.append({"stage": "سند", "query": support_query, "basis": support_basis,
                          "sources": [d["name"] for d in support_docs],
                          "raw_count": getattr(support_ranked, "raw_count", None),
                          "matched_count": getattr(support_ranked, "matched_count", None),
                          "fetch_failures": getattr(support_docs, "fetch_failures", []),
                          "top_candidates": getattr(support_docs, "top_candidates", []),
                          "call_error": support_call_error,
                          "outcome": (f"⚠️ فشل نداء النموذج تقنيًا: {support_call_error}"
                                     if support_call_error else
                                     f"{len(set(support_supporting))} مصدر مؤيِّد إضافي "
                                     "بكيانات الحدث المسمّى نفسه")})

            all_docs, all_supporting = _merge_named_evidence(
                named_docs, named_supporting, support_docs, support_supporting, cfg)
            unique = set(all_supporting)
            if len(unique) < min_confirm:
                dropped.append({
                    "text": named_text,
                    "reason": (f"سند غير كافٍ بعد تسمية الحدث ({len(unique)} من "
                              f"{min_confirm} مصادر مستقلة مطلوبة، شاملةً دورة سند "
                              "ثانية بكيانات الحدث نفسه)"),
                })
                continue
            # تشخيص Issue #373، الجولة السابعة (البند 1): كانت تُمرَّر ranked=[]
            # حرفيًا هنا — لا Article فيها image_candidates إطلاقًا مهما توفّرت
            # صور فعلية، فمصادر فرع الحدث المبهم كانت تصل الصياغة بلا صور
            # دومًا بصرف النظر عن حجم التغطية الفعلي. support_ranked (دورة
            # السند الثانية أعلاه) تحمل كائنات Article الحقيقية بصورها.
            fact_sources = _grounded_sources(all_supporting, all_docs, support_ranked)
            grounded.append({**f, "text": named_text, "sources": fact_sources})
            # سؤال الصلة يسأل عن الرابط بين طرفين — استعلامه يجب أن يشتمل
            # كيانات كليهما لا الإشارة المبهمة الأصلية وحدها (تشخيص Issue
            # #373، الجولة الثانية عشرة، البند 2): support_query أعلاه بُني
            # أصلًا من كيانات الحدث المسمّى نفسه (محكمة/إعدام/بشار الأسد...)،
            # نتشاركه هنا كنص متاح مجانًا بدل استخراج مستقل. تتشابك القائمتان
            # بدل التذييل (كيانات الحدث أولًا حتى تصلها) كي لا يُقصي سقف
            # query_max_words أحد الطرفين إن طال الآخر عند بناء الاستعلام
            # لاحقًا عبر evidence.build_query_for_claim.
            link_entities: list[str] = []
            for pair in zip_longest(support_query.split(), f.get("entities") or []):
                for w in pair:
                    if w:
                        link_entities.append(w)
            link_questions.append({
                "text": f"ما الصلة بين «{named_text}» و«{f['text']}»؟",
                "entities": link_entities,
                "is_reference": False,
                # أدلة مرحلتَي [تسمية]/[سند] (مُوحَّدة الهوية أصلًا عبر
                # _merge_named_evidence) تصل حلقة الأسئلة أدناه كإضافة لا
                # بديل عن بحث جديد — لا تُهدر لمجرد إعادة السؤال في حلقة
                # منفصلة (تشخيص Issue #373، الجولة الثانية عشرة، البند 2)
                "existing_docs": all_docs,
                "existing_supporting": all_supporting,
            })
        else:
            query = evidence.build_query_for_claim(f, query_max_words)
            ranked = evidence.search(query, cfg, days, unrestricted=f.get("is_reference", False))
            relevance_text = evidence._entities_text(f) or f["text"]
            docs, basis = evidence.gather_evidence(ranked, cfg, relevance_text)
            all_read_docs.extend(docs)
            # "تصريح" (البند 1، تشخيص Issue #373، الجولة الثالثة عشرة): فحص
            # المضمون لا وقوع المقابلة وحده — is_statement تختار
            # STATEMENT_SUPPORT_SYSTEM بدل SUPPORT_SYSTEM، بلا تخفيف في عتبة
            # min_confirm_sources نفسها
            is_statement = f["kind"] == "تصريح"
            supporting = (_support_sources(f["text"], docs, cfg, is_statement=is_statement)
                         if docs else [])
            fact_call_error = getattr(supporting, "call_error", None)
            unique = set(supporting)
            trail.append({"stage": "واقعة" if not is_statement else "تصريح",
                          "query": query, "basis": basis,
                          "sources": [d["name"] for d in docs],
                          "raw_count": getattr(ranked, "raw_count", None),
                          "matched_count": getattr(ranked, "matched_count", None),
                          "fetch_failures": getattr(docs, "fetch_failures", []),
                          "top_candidates": getattr(docs, "top_candidates", []),
                          "call_error": fact_call_error,
                          "outcome": (f"⚠️ فشل نداء النموذج تقنيًا: {fact_call_error}"
                                     if fact_call_error else
                                     f"مسندة بـ{len(unique)} مصدر مستقل" if len(unique) >= min_confirm
                                     else f"سند غير كافٍ ({len(unique)}/{min_confirm})")})
            if len(unique) < min_confirm:
                dropped.append({
                    "text": f["text"],
                    "reason": (f"⚠️ فشل نداء الحكم على السند تقنيًا: {fact_call_error}"
                              if fact_call_error else
                              f"سند غير كافٍ ({len(unique)} من {min_confirm} "
                              "مصادر مستقلة مطلوبة)"),
                })
                continue
            fact_sources = _grounded_sources(supporting, docs, ranked)
            grounded.append({**f, "sources": fact_sources})

        for s in grounded[-1]["sources"]:
            if not any(s["name"] == x["name"] for x in sources_seen):
                sources_seen.append({"name": s["name"], "link": s["link"]})

    outcome["dropped"] = dropped
    outcome["opinion_note"] = opinion_note
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
        all_read_docs.extend(docs)
        # سؤال الصلة يحمل أدلة [تسمية]/[سند] المُوحَّدة الهوية أصلًا —
        # البحث الجديد هنا إضافة لا بديل عنها (تشخيص Issue #373، الجولة
        # الثانية عشرة، البند 2): إهدارها كان يعتمد الحكم على تفاوت نتائج
        # بحث حي جديد وحده رغم توفّر سند مُثبَت فعلًا لنفس اللحظة. توحيد
        # الهوية عبر _canonical_publisher كالعادة كي لا تُحسب نسخة الجزيرة
        # نت/Al Jazeera مرتين لو ظهرت في الدورتين
        existing_docs = q.get("existing_docs") or []
        if existing_docs:
            seen_canonical: set[str] = set()
            docs_for_answer: list[dict] = []
            for d in list(existing_docs) + list(docs):
                canonical = evidence._canonical_publisher(d.get("name", ""), cfg)
                if canonical in seen_canonical:
                    continue
                seen_canonical.add(canonical)
                docs_for_answer.append(d)
        else:
            docs_for_answer = docs
        answer = _ask_answer_model(q["text"], docs_for_answer, cfg) if docs_for_answer else None
        answer_call_error = getattr(answer, "call_error", None)
        supporting = answer["supporting"] if answer else []
        unique = set(supporting)
        answered_ok = bool(answer) and len(unique) >= min_confirm
        trail.append({"stage": "سؤال", "query": query, "basis": basis,
                      "sources": [d["name"] for d in docs_for_answer],
                      "raw_count": getattr(ranked, "raw_count", None),
                      "matched_count": getattr(ranked, "matched_count", None),
                      "fetch_failures": getattr(docs, "fetch_failures", []),
                      "top_candidates": getattr(docs, "top_candidates", []),
                      "call_error": answer_call_error,
                      "reused_evidence_count": len(existing_docs),
                      "outcome": (f"⚠️ فشل نداء النموذج تقنيًا: {answer_call_error}"
                                 if answer_call_error else
                                 f"أُجيب ومسندة بـ{len(unique)} مصدر" if answered_ok
                                 else "لم تُجب عنه النصوص المقروءة" if not answer
                                 else f"سند غير كافٍ ({len(unique)}/{min_confirm})")})
        if not answered_ok:
            # تفريق «لم يسمِّ النموذج مصدرًا» عن «سمّى مصدرًا لم يُطابَق» في
            # التقرير نفسه (تعليق التنفيذ على Issue #364، البند 3) — كلاهما
            # عطل تسمية من رد النموذج، لا غياب سند فعلي كما توحي "0 من N"
            # المجردة. فشل نداء تقني (Issue #373، الجولة الحادية عشرة، البند
            # 2) سبب ثالث منفصل يُفحص أولًا — ليس "لم تُجب عنه النصوص" ولا
            # عطل تسمية، بل امتناع الاستدعاء نفسه عن الوقوع
            naming_issue = answer.get("naming_issue") if answer else None
            if answer_call_error:
                reason = f"⚠️ فشل نداء الإجابة تقنيًا: {answer_call_error}"
            elif not answer:
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
        fact_sources = _grounded_sources(supporting, docs_for_answer, ranked)
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
    # خط الأساس الثابت (تشخيص Issue #373، الجولة الرابعة، البند 3) يحتاج
    # عدد الوقائع المسندة فعليًا كعدد صريح — لا استخراجه لاحقًا من نص
    # outcome["reason"] الحر الذي لا يُكتب أصلًا حين تفشل مراحل لاحقة
    # (الكفاية/الصياغة) رغم أن grounded نفسها مكتملة هنا
    outcome["grounded_count"] = len(grounded)

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

    source_docs = [{"name": evidence._canonical_publisher(s["name"], cfg), "text": s["text"],
                   "link": s.get("link", "")}
                  for f in grounded for s in f.get("sources", []) if s.get("text")]
    # مجمع إشارة (ب) — كل وثيقة قُرئت خلال هذا التشغيل بأكمله (all_read_docs)،
    # بهوية ناشر موحَّدة أيضًا كي لا تُحسب نسختا ناشر واحد بلغتين مصدرين
    # منفصلين (تشخيص Issue #373، الجولة العاشرة، ضابط توحيد الناشر في ب)
    extra_docs = [{"name": evidence._canonical_publisher(d.get("name", ""), cfg),
                  "text": d.get("text", ""), "link": d.get("link", "")}
                 for d in all_read_docs if d.get("text")]
    draft_text = "\n".join(filter(None, [
        written["image_headline"], written["post_title"], written["post_body"],
    ]))
    max_shared = int(acfg.get("max_shared_run_words", 7))
    repeat_min_count = int(acfg.get("repeat_within_source_min_count", 2))
    trim_min_core = int(acfg.get("trim_min_core", 5))
    # فحص النسخ اللفظي (القاعدة 5) — verify_draft.check_originality مُعاد
    # استعمالها كما هي بعتبتها واستثناءاتها، لا نسخة موازية
    ok_orig, orig_reason, originality_notes = verify_draft.check_originality(
        draft_text, body, source_docs, max_shared,
        repeat_min_count=repeat_min_count, extra_docs=extra_docs, min_core=trim_min_core)
    outcome["originality_notes"] = originality_notes
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

    # تقرير الصورة (تشخيص Issue #373، البند 1): «الصورة غائبة ولا سبب في
    # التقرير» — shot يحمل الآن سبب رفض كل مرشَّح وحصيلة احتياط find_images
    # (imaging.build_post_image)؛ total_candidates عدد مرشحي المصادر
    # المسندة كلها قبل القصّ إلى أول 6 (candidates_tried داخل shot)
    outcome["image_report"] = {**shot, "total_candidates": len(image_urls)}

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

    # لا illustrative (تشخيص Issue #373، مراجعة بشرية بعد أول نشر، البند 1):
    # used_original يصير True أيضًا حين ينجح احتياط find_images (imaging.py
    # يضبطه بعد محاولتَي المصدر والاحتياط معًا) — عزو تلك الصورة التعبيرية
    # لأول مرشَّح في image_ranked (مصادر مسندة فعليًا) كان لينسب صورة حرة
    # لمصدر لم يوفّرها إطلاقًا
    if shot.get("used_original") and not shot.get("illustrative") and image_ranked:
        outcome["image_source_name"] = image_ranked[0][1]
        outcome["image_source_link"] = image_ranked[0][2]

    outcome.update({
        "produced": True,
        "reason": f"صيغ مقال من {len(grounded)} واقعة مسندة",
        "draft_id": draft_id,
    })
    return outcome


def _image_report_lines(ir: dict) -> list[str]:
    """سطر تشخيص الصورة (تشخيص Issue #373، البند 1، مراجعة بشرية بعد أول
    نشر): «الصورة غائبة» بلا سبب في التقرير عطل صمت — لا سبيل للمراجع
    لمعرفة كم مرشَّح صورة جُرِّب من المصادر المسندة، لماذا فشل كل واحد، وهل
    استُدعي احتياط find_images وماذا أعاد، إلا من هنا. ir فارغ (لا مفاتيح)
    حين لم يصل الإنتاج مرحلة بناء الصورة أصلًا — لا شيء يُعرض حينها."""
    if not ir:
        return []
    total = ir.get("total_candidates", 0)
    failures = ir.get("candidate_failures") or []
    # illustrative قبل used_original عمدًا: imaging.build_post_image يضبط
    # used_original=True أيضًا حين ينجح احتياط find_images وحده (يعني فقط
    # "لا خلفية مصمَّمة استُخدمت")، فحالة الاحتياط الناجح تحمل العلمين معًا
    # — illustrative هي الحالة الأدق لتمييزها عن صورة مصدر حقيقية
    if ir.get("illustrative"):
        head = (f"🖼️ فشلت صور المصادر المسندة كلها ({total} مرشَّحًا) — استُخدمت صورة "
               f"تعبيرية حرة من find_images (من {ir.get('fallback_candidates', 0)} مرشَّحًا).")
    elif ir.get("used_original"):
        head = f"🖼️ صورة من مصدر مسند مباشرة ({total} مرشَّحًا من المصادر المسندة)."
    else:
        head = (f"🖼️ فشلت صور المصادر المسندة كلها ({total} مرشَّحًا)" if total
               else "🖼️ لا صورة واحدة بين مرشَّحي المصادر المسندة (0)")
        if ir.get("fallback_tried"):
            head += (f" — استُدعي احتياط find_images أيضًا وأعاد "
                    f"{ir.get('fallback_candidates', 0)} مرشَّحًا، لم ينجح أي منها.")
        else:
            head += " — لم يُستدعَ احتياط find_images."
    lines = ["", head]
    for f in failures:
        lines.append(f"  - ⚠️ {f['url'][:90]}: {f['reason']}")
    return lines


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
        lines += _image_report_lines(outcome.get("image_report") or {})
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

    if outcome.get("opinion_note"):
        # مميَّز صراحة عن "ما سقط من موجزي" أعلاه: قرار تهيئة مسبق
        # (article.include_opinion=false)، لا نتيجة فحص سند
        lines += ["", f"💬 {outcome['opinion_note']}"]

    if outcome.get("merged_statements"):
        # تبليغ الدمج لا منعه (البند 1، تشخيص Issue #373، الجولة الثالثة
        # عشرة): كل "تصريح" مع جمل الموجز الحرفية التي دُمجت فيه، بصرف
        # النظر عن مصير سنده لاحقًا — يظهر دومًا فيراجعه المستخدم البشري
        # ويصحح دمجًا زائفًا (متحدثان/مناسبتان مختلفتان) إن وقع خطأً
        lines += ["", "**تصريحات دُمجت من عدة جمل (راجعها):**"]
        for m in outcome["merged_statements"]:
            excerpts = "؛ ".join(m["merged_excerpts"]) or "—"
            lines.append(f"- {m['speaker']}: «{m['text']}» — دُمج من: {excerpts}")

    if outcome.get("split_statements"):
        # نظير مقلوب لـ merged_statements أعلاه (البند 3، الجولة الخامسة
        # عشرة): جملة مركّبة واحدة فُصِّلت إلى عدة وقائع ذرّية، كلٌّ سنده
        # الخاص — تظهر الجملة الأصلية وكل جزء استُخرج منها فيراجعهما
        # المستخدم البشري
        lines += ["", "**وقائع فُصِّلت من جملة واحدة (راجعها):**"]
        for sp in outcome["split_statements"]:
            parts = "؛ ".join(sp["parts"]) or "—"
            lines.append(f"- «{sp['original']}» — فُصِّلت إلى: {parts}")

    if outcome.get("originality_notes"):
        # تبليغ صريح لا إعفاء صامت (تشخيص Issue #373، الجولة العاشرة، البند
        # 2): كل تتابع أُعفي من رفض النسخ اللفظي بإشارة (أ)/(ب) يظهر هنا
        # بدليله، فيبقى قابلًا لتصحيح المراجع البشري إن أخطأت الإشارة
        lines += ["", "**تتابعات أُعفيت من فحص النسخ اللفظي:**"]
        lines += [f"- {note}" for note in outcome["originality_notes"]]

    if outcome.get("diffs"):
        lines += ["", "**أين خالفت المصادرُ موجزي:**"]
        lines += [f"- موجزي: «{d['brief']}» — المصادر: «{d['sources_say']}»"
                 for d in outcome["diffs"]]

    if outcome.get("trail"):
        # مفتوح افتراضيًا (open) — لا مطويًا (تشخيص Issue #373، الجولة الثانية،
        # البند 1): "trail اختفى من التقرير" — لم يتأكد وجود عطل في التصيير
        # نفسه (بنية <details> ولوب العناصر تُنتج كل الأسطر فعليًا، تحقّقنا
        # بمحاكاة مباشرة)، لكن <details> مطوي افتراضيًا يجعل أي قارئ يفوّت
        # المحتوى دون نقرة صريحة — وهذا وحده كافٍ ليبدو "اختفى". لا مجازفة:
        # يُفتح دومًا فلا سبيل لتفويته.
        lines += ["", "<details open><summary><strong>سجلّ البحث الكامل (trail)</strong> "
                      f"— {len(outcome['trail'])} استعلامًا</summary>", ""]
        for t in outcome["trail"]:
            srcs = "، ".join(t.get("sources") or []) or "لا مصادر"
            # عدد النتائج قبل التصفية بالصلة وبعدها (البند 1، تعليق العطل
            # الثاني): يشرح لماذا سقط استعلام لمصدر واحد رغم تغطية واسعة —
            # None حين لم يُجرَ بحث أصلًا (fake/مسار بلا SearchResult).
            # "بلا تصفية صلة" لمرحلتَي «مباشر»/«سياق» (تشخيص Issue #373،
            # البند 1): matched يساوي raw دومًا هناك — فلتر relevant()
            # معطَّل عمدًا، والفرز بالوزن+الصلة الرخوة (لا هذا الفلتر) هو
            # ما يقرر أي مرشح يُقرأ، وبوابة الاتساق أدناه هي الحارس النهائي
            counts = ""
            if t.get("raw_count") is not None:
                counts = f" ({t['raw_count']} خام ← {t.get('matched_count', '؟')} مطابق"
                if t.get("unfiltered_relevance"):
                    counts += "، بلا تصفية صلة"
                counts += ")"
            lines.append(f"- **[{t['stage']}]** `{t['query']}`{counts} → {t['basis']} — "
                         f"{t.get('outcome', '')} (المصادر: {srcs})")
            for fail in t.get("fetch_failures") or []:
                name, reason, link = fail.get("name", "؟"), fail.get("reason", ""), fail.get("link", "")
                label = f"[{name}]({link})" if link else name
                lines.append(f"  - ⚠️ فشل جلب {label}: {reason}")
            # أعلى 5 مرشّحين بالدرجة المركّبة (البند 2، تشخيص Issue #373،
            # الجولة الثالثة عشرة، الخيار (و)): رصد صرف — يحسم برقم فعلي هل
            # تفوّق صلة لفظية عالية على فارق وزن ثابت هو ما يمنع مصدرًا
            # موثوقًا من الصعود، بدل تخمين تفسير بلا دليل
            for c in t.get("top_candidates") or []:
                lines.append(f"  - 🔎 {c['name']}: وزن={c['weight']} صلة={c['relevance']} "
                             f"درجة={c['score']}")
        lines.append("</details>")

    return "\n".join(lines)


BASELINE_LOG_PATH = STATE_DIR / "article_baseline.md"


def _trail_read_counts(trail: list[dict]) -> str:
    """ملخص «مرحلة×عدد مصادر مقروءة فعليًا» لكل استعلام — يُستهلك في سجل
    خط الأساس (record_baseline) وحده، لا في build_report (الذي يعرض
    الأسماء نفسها، لا العدّ المختصر)."""
    if not trail:
        return "بلا استعلامات"
    return "، ".join(f"{t['stage']}×{len(t.get('sources') or [])}" for t in trail)


def _question_outcomes(outcome: dict) -> str:
    """ملخص «✅/❌ نص السؤال» لكل سؤال من الموجز (تشخيص Issue #373، الجولة
    الثامنة، البند 3): نفس السؤال بنفس المصادر أُجيب في تشغيلة وعاد بلا
    إجابة في تالية — عدد grounded_count الكلي وحده لا يكشف *أي* سؤال بعينه
    تذبذب، فقط أن العدد الكلي هبط. لا تشخيص جذري هنا (الشاهد يطابق تذبذب
    حكم نموذج بين نداءين شبه متطابقين — لا نداء بدرجة حرارة صفرية في هذا
    المسار أصلًا؛ انظر _ask_answer_model)، بل رصد رقمي عبر تشغيلات متتالية
    كما طلب صاحب الـ Issue صراحة بدل مناقشة تفسيرات بلا دليل."""
    parts = [f"✅ {q['text']}" for q in outcome.get("answered_questions") or []]
    parts += [f"❌ {q['text']}" for q in outcome.get("unanswered") or []]
    return "؛ ".join(parts) if parts else "بلا أسئلة"


def record_baseline(outcome: dict, path: Path = BASELINE_LOG_PATH) -> str:
    """يُلحِق سطرًا بنتيجة تشغيلة على الموجز المرجعي الثابت في ملف
    بالمستودع (تشخيص Issue #373، الجولة الرابعة، البند 3): بلا سجل
    تراكمي مكتوب، كل تراجع محتمل بين تشغيلتين حيّتين يُناقَش بتفسيرات
    (تفاوت بحث حي؟ عطل حقيقي في الكود؟) بلا أي دليل يُقارَن رقميًا —
    بالضبط ما وقع في هذا الـ Issue أكثر من مرة.

    يُستدعى من main() عند --baseline (مقترنة بـ--issue أو بـ
    article.baseline_issue_number)، بعد تشغيلة فعلية حقيقية (شبكة + نموذج)
    — لا من مسار الاختبارات، التي تفترض بيئة بلا شبكة أصلًا (install_fakes).
    يُستدعى دومًا بصرف النظر عن نجاح الإنتاج (outcome["produced"] قد تكون
    False) — الفشل هو بالضبط ما يُتتبَّع هنا، لا استثناء يُسقَط.

    قيد معروف عولج بتعديل مقترَح على article.yml لا بالكود هنا (تعديل
    workflows خارج صلاحية هذا التغيير — انظر تعليق الموافقة على Issue #373،
    الجولة الخامسة): خطوة "رفع المسودة إلى المستودع" في article.yml مشروطة
    بـ steps.article.outputs.draft_id != ''، فتشغيلة --baseline تفشل كليًا
    (0 وقائع، بلا draft_id) كانت لتُسجَّل هنا محليًا في عامل CI لكن لا
    تُرفع للمستودع أبدًا — والفشل هو بالضبط ما نتتبعه. main() يكتب
    baseline=true إلى GITHUB_OUTPUT كلما استُعملت --baseline؛ شرط تلك
    الخطوة يحتاج `|| steps.article.outputs.baseline == 'true'` مضافًا إلى
    شرطها الحالي (git add -A drafts state تبقى كما هي — بلا تغيير في drafts
    حين لا مسودة، فالإضافة بلا أثر جانبي على مسار الإنتاج العادي)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = ("✅ " + outcome["reason"]) if outcome.get("produced") else ("❌ " + outcome["reason"])
    row = (f"| {ts} | {result} | {outcome.get('grounded_count', 0)} | "
          f"{_trail_read_counts(outcome.get('trail') or [])} | "
          f"{_question_outcomes(outcome)} |\n")
    with path.open("a", encoding="utf-8") as fh:
        if is_new:
            fh.write(
                "# خط أساس ثابت — مسار «مقال من المصادر»\n\n"
                "سطر واحد بعد كل تشغيلة `python -m src.article --issue N --baseline` على "
                "الموجز المرجعي الثابت (نص Issue رقم `article.baseline_issue_number` في "
                "`config.yaml` — يُقرأ حيًّا من الـ Issue في كل تشغيلة، لا نسخة مكرَّرة هنا) "
                "— انظر توثيق `record_baseline` في `src/article.py` (تشخيص Issue #373، "
                "الجولتان الرابعة والخامسة، البند 3). لا يُعاد كتابته، يُلحَق به فقط — "
                "للمقارنة عبر تشغيلات متتالية. عمود «أسئلة الموجز» (الجولة الثامنة، "
                "البند 3) يعرض حكم كل سؤال بعينه صراحة — تذبذب نموذج بين تشغيلتين على "
                "نفس السؤال بنفس المصادر يظهر هنا كسطرين متعارضين بدل أن يختفي خلف عدد "
                "«وقائع مسندة» الكلي وحده.\n\n"
                "| التاريخ (UTC) | النتيجة | وقائع مسندة | مصادر كل استعلام (مرحلة×عدد) | "
                "أسئلة الموجز (✅/❌) |\n"
                "|---|---|---|---|---|\n")
        fh.write(row)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="اكتب مقالًا من موجز ملصق في Issue")
    parser.add_argument("--issue", type=int, help="رقم الـ Issue")
    parser.add_argument(
        "--baseline", action="store_true",
        help="بعد التشغيلة العادية (تعليق على الـ Issue كالمعتاد)، سجّل النتيجة "
             "أيضًا في state/article_baseline.md — لمقارنة تشغيلات متتالية على "
             "نفس الموجز المرجعي عبر تغييرات الكود (تشخيص Issue #373، الجولة "
             "الخامسة، البند 3). بلا --issue صريح، يُستعمل "
             "article.baseline_issue_number من config.yaml — الموجز نفسه "
             "يُقرأ حيًّا من نص ذلك الـ Issue في كل مرة، لا من نسخة في "
             "config.yaml")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")

    cfg = load_config()

    issue_number = args.issue
    if issue_number is None and args.baseline:
        issue_number = cfg.path("article.baseline_issue_number")
    if issue_number is None:
        parser.error("--issue مطلوب (أو عرّف article.baseline_issue_number في "
                     "config.yaml عند استعمال --baseline بلا --issue)")

    output_path = os.environ.get("GITHUB_OUTPUT")

    body = review.fetch_issue_body(issue_number)
    if not body.strip():
        review.comment(issue_number,
                       "### 📰 لا نص\nالـ Issue لا يحوي موجزًا لكتابة مقال منه.")
        return 0

    outcome = write_article(body, issue_number, cfg)
    report = build_report(outcome)
    review.comment(issue_number, f"{report}\n\n<sub>💵 {writer.usage_summary()}</sub>")

    if args.baseline:
        # يُستدعى بصرف النظر عن outcome["produced"] عمدًا — تشغيلة تفشل
        # كليًا تُسجَّل هنا أيضًا (الفشل هو ما نتتبعه)، وbaseline=true في
        # GITHUB_OUTPUT يتيح لـarticle.yml رفعها للمستودع حتى بلا draft_id
        # (انظر توثيق record_baseline أعلاه لتعديل article.yml المقترَح)
        row = record_baseline(outcome)
        print(f"سُجِّل خط الأساس في {BASELINE_LOG_PATH}:\n{row.strip()}")
        if output_path:
            with open(output_path, "a", encoding="utf-8") as fh:
                fh.write("baseline=true\n")

    draft_id = outcome.get("draft_id")
    if draft_id and output_path:
        with open(output_path, "a", encoding="utf-8") as fh:
            fh.write(f"draft_id={draft_id}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
