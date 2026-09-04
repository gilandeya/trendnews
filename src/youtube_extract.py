"""المرحلة الثانية من مسار يوتيوب (Issue #631): سحب نص كل فيديو ناجٍ من
src/youtube_collect.py، واستخلاص ٥-٧ نقاط عربية قصيرة منه عبر نموذج رخيص.

قيد إلزامي من الـIssue: لا نص ترجمة كامل يُكتب على القرص أو يُطبَع أو
يُرفَع -- النص يمرّ في الذاكرة فقط بين fetch_transcript وextract_points ثم
يُهمَل. لا شيء في هذا الملف يستدعي print()/log على متغيّر النص نفسه.

Issue #635 (إصلاح خمسة أعطال بعد التشغيلة الأولى): الطوابع الزمنية كانت
مختلَقة (النموذج يخمّن أرقامًا مستديرة بلا سند)، تحليل JSON النصّي كان هشًّا
(١٩/٢٨ فشلت)، الترجمة إلى العربية لم تُطبَّق دومًا، أسماء الأعلام انكسرت
بخلط حروف، والحرّاس ميّزت المدة لا نوع المحتوى فمرّت نشرات ورياضة. الإصلاح:
أختام زمنية ظاهرة في النص المُدخَل + رفض أي طابع يتجاوز مدة الفيديو، إخراج
مهيكل (tool_use) بدل JSON نصّي، رفض أي حرف غير عربي في الحقول العربية، وحارس
تصنيف موضوع قبل إنفاق نداء الاستخلاص الكامل.

Issue #637 (إصلاح ثلاثة أعطال بعد التشغيلة الثانية -- الحرّاس أعلاه صحيحة،
العطل فيما تحرسه): (١) رفض «صيغة طابع غير صالحة» و«طابع يتجاوز مدة الفيديو»
كانا يشتركان في فئة عدّاد واحدة (points_rejected_timestamp) فتعذّر تمييز
سبب الفشل الفعلي -- فُصلا، وأُضيفت القيمة الخام قبل التحويل إلى رسالة رفض
تجاوز المدة (الرقم المحوَّل وحده لا يكفي للتشخيص). (٢) الفيديوهات الثقيلة
تحليليًا كانت تُخرج بلوك tool_use فارغًا بعد كل المحاولات -- على الأرجح
انقطاع الإخراج عند حدّ max_tokens قبل اكتمال البلوك -- فرُفع الحدّ، وأُضيف
حدّ أعلى لطول النص المُدخَل مع قصّ ذكي (نصف أول + نصف أخير) بدل قصّ من
النهاية فقط، وصار stop_reason يُفحَص ويُسجَّل صراحةً عند الفشل. (٣) عنوان
البروكسي كان يُحجَب مؤقتًا (429/RemoteDisconnected) رغم البروكسي -- وُسِّعت
الفواصل الزمنية، وأُضيف تراجع أُسّي عند الحجب المؤقت بدل إسقاط الفيديو من
أول محاولة فاشلة.

Issue #642 (ارتداد بعد التشغيلة الثالثة -- الحرّاس رفضت نقاطًا صحيحة تمامًا):
(١) صيغة الأختام الظاهرة في النص المُدخَل ([HH:MM:SS]) جعلت النموذج ينسخ
القوسين معها طاعةً حرفية لتعليمة "انسخ كما هو" -- فيُرفَض ختم سليم مثل
`00:00:11` بصفته "صيغة غير صالحة" لمجرّد وصوله `[00:00:11]`. الإصلاح:
parse_timestamp تُجرّد الأقواس والمسافات قبل أي تحليل. (٢) حارس اللغة كان
يسمح بفئة الترقيم فقط فيرفض رموزًا رياضية/علمية مشروعة تمامًا (`+`، `%`،
`°`...) بصفتها "حرفًا غير عربي" -- عُكس المعيار إلى "نرفض الحروف الأجنبية
فقط لا الرموز": أي حرف من فئة يونيكود "حرف" (L*) خارج نطاق العربية يُرفَض،
وأي رمز أو علامة ترقيم يُقبل بلا تعداد صريح. (٣) الفراغ الصادق (النموذج لم
يجد ختمًا واضحًا) كان يُرفَض بنفس فئة الصيغة الفاسدة، فيخسر الاستخلاص نقاطًا
صحيحة المحتوى بالكامل بلا حاجة -- صار الفراغ يُقبل صراحة (`timestamp: None`
+ عدّاد points_without_timestamp)، ومعه علامة حذف صريحة في القصّ الذكي
(TRUNCATION_MARKER) وقاعدة "لا تبنِ رقمًا من موضع المقطع" في البرومبت،
لمواجهة اختلاق الأختام الذي ظل قائمًا في الفيديوهات الطويلة رغم سلامة
الصيغة.

Issue #644 (حسم اختلاق الطوابع بعد التشغيلة الرابعة -- الحرّاس أعلاه لم
تعد تكفي وحدها): ٢٦ نقطة رُفضت بتجاوز مدة الفيديو رغم صيغة سليمة. التشخيص:
النموذج يقرأ عموديًا عبر الأسطر بدل أفقيًا -- خانة الساعة في `[HH:MM:SS]`
كانت تُملأ من ختم مجاور بينما الدقائق/الثواني (`MM:SS`) تُنسَخ بدقّة من
المقطع الصحيح (شاهد: `00:40:44` و`06:40:44` في نفس الفيديو، دقائق/ثوانٍ
متطابقة، ساعة مختلفة). النموذج بارع في النسخ الحرفي (`quote_original` دقيق
دومًا) وضعيف في نسخ أرقام متراصّة. الحل الجذري: لا نطلب رقمًا أصلًا.
(١) format_transcript لم تعد تنتج خانة ساعة (`[MM:SS]` فقط، الدقائق تتجاوز
٥٩ بلا سقف) -- كل فيديوهات المسار تحت ساعتين ونصف فخانة الساعة كانت عديمة
الفائدة وهي أصل الخلط العمودي. (٢) حقل `timestamp` حُذف من مخطّط
extract_points واستُبدل بـ`anchor_text` (أول ٤-٦ كلمات من المقطع، منسوخة
حرفيًا) -- الشيفرة تبحث عن هذه المرساة في المقاطع نفسها (resolve_timestamp)
وتحسب الطابع الحقيقي من مطابقتها، فتنقل مهمة التحديد الزمني من قدرة ضعيفة
(نسخ أرقام) إلى قدرة مثبتة قويًا (نسخ نصّ). فشل المطابقة ⇒ `timestamp: None`
مقبول (عدّاد points_timestamp_unresolved)، لا رفض.
"""
from __future__ import annotations

import json
import logging
import random
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from anthropic import Anthropic, APIError

from . import youtube_collect
from .config import DATA_REPO_DIR, Config, env, load_config
from .proxy_config import get_proxy_config

log = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "youtube_extract.md"
# مستودع خاص منفصل (Issue #722) -- انظر تعليق DATA_REPO_DIR في src/config.py.
POINTS_DIR = DATA_REPO_DIR / "youtube_points"

REQUIRED_FIELDS = ["statement", "speaker", "quote_original", "quote_arabic",
                    "anchor_text", "type", "topic_hint"]
VALID_TYPES = {"fact", "opinion", "forecast"}

EXTRACT_POINTS_SCHEMA = {
    "name": "extract_points",
    "description": "يستخرج نقاطًا إخبارية عربية موثّقة بمرساة نصّية من نص فيديو",
    "input_schema": {
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {"type": "string",
                                      "description": "جملة عربية قصيرة تلخّص النقطة"},
                        "speaker": {"type": "string",
                                    "description": "اسم القائل بالعربية + صفته"},
                        "quote_original": {"type": "string",
                                            "description": "اقتباس حرفي من النص بلغته الأصلية"},
                        "quote_arabic": {"type": "string",
                                          "description": "ترجمة الاقتباس إلى العربية الفصحى"},
                        "anchor_text": {
                            "type": "string",
                            "description": (
                                "أول أربع إلى ست كلمات من السطر الذي أُخذ منه quote_original، "
                                "منسوخة حرفيًا من النص المُدخَل بلغته الأصلية بلا أي تعديل ولا "
                                "ترجمة، وبلا الختم الزمني نفسه. تُستعمَل لتحديد موضع الاقتباس "
                                "آليًا عبر بحث نصّي في الشيفرة -- لا تحسب رقمًا ولا تنسخ ختمًا، "
                                "انسخ الكلمات فقط."),
                        },
                        "type": {"type": "string", "enum": sorted(VALID_TYPES)},
                        "topic_hint": {"type": "string", "description": "كلمتان أو ثلاث للموضوع"},
                    },
                    "required": REQUIRED_FIELDS,
                },
            },
        },
        "required": ["points"],
    },
}

TOPIC_CATEGORIES = ("political_analysis", "news_bulletin", "other")

TOPIC_SCHEMA = {
    "name": "classify_video_topic",
    "description": "يصنّف نوع فيديو يوتيوب من عنوانه ومقتطف من نصه، قبل إنفاق نداء الاستخلاص الكامل",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": list(TOPIC_CATEGORIES)},
        },
        "required": ["category"],
    },
}

TOPIC_SYSTEM = """أنت حارس تصنيف يفصل التحليل السياسي عن غيره قبل استخلاص نقاط منه.
تستلم عنوان فيديو ومقتطفًا من أول نصّه، وتصنّفه إلى واحدة من ثلاث فئات فقط:

- political_analysis: نقاش أو تحليل أو مقابلة تدور حول حدث سياسي أو
  اقتصادي أو دولي جارٍ، وتقدّم قراءة له -- لا مجرّد حوار يلامس السياسة
  عرضًا.
- news_bulletin: نشرة أخبار متتابعة -- سرد أخبار قصيرة الواحدة تلو الأخرى
  بلا تحليل أو نقاش متعمّق، حتى لو كان موضوعها سياسيًا.
- other: أي شيء آخر -- رياضة، فن، سينما، منوّعات، طقس، حوادث فردية (حريق،
  حادث سير) بلا بعد سياسي أو دبلوماسي، وأيضًا **المقابلات الشخصية وحكايات
  المسار المهني والسير الذاتية** -- ولو كان الضيف سياسيًا أو صحفيًا وذكر
  السياسة عرضًا أثناء الحديث عن نفسه (Issue #639: مقابلة صحفي عن بداياته
  ودراسته وتأمينه الاجتماعي صُنِّفت خطأً political_analysis لمجرّد لمسها
  حرية الصحافة، رغم أن محتواها سيرة ذاتية لا تحليل حدث).

المعيار الحاسم عند مقابلة أو حوار: هل يدور حول حدث خارجي جارٍ، أم حول
الضيف نفسه (بداياته، مسيرته، رأيه الشخصي في حياته)؟ الأول
political_analysis، والثاني other. مثالان حرفيان:
- "مقابلة مع صحفي عن بداياته وحياته المهنية" ⇐ other.
- "مقابلة مع محلل عن تداعيات العقوبات على إيران" ⇐ political_analysis.

عند الشك بين political_analysis وnews_bulletin: افحص هل هناك نقاش أو تفسير
متصل أطول من مجرّد عرض خبر ثم الانتقال لآخر -- إن كان الجواب نعم فـ
political_analysis."""


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


# ──────────────────────────── التحقق من نقطة ────────────────────────────

# حروف خاصة بالفارسية/الأردية غائبة عن العربية الفصحى -- تقع داخل نطاق
# يونيكود العربي نفسه (٠٦٠٠-٠٦FF) فلا يكفي فحص المدى وحده، يلزم استثناء صريح.
# مكتوبة بترميز \u صراحة (لا حروفًا حرفية) لتفادي خطأ كتابة صامت بسبب اتجاه
# النص من اليمين لليسار عند تحرير هذا الملف لاحقًا:
# PEH TCHEH JEH KEHEH GAF FARSI-YEH VE YEH-BARREE AE TTEHEH DDAL RREH
# NOON-GHUNNA HEH-DOACHASHMEE HEH-WITH-YEH-ABOVE HEH-GOAL
# بقيت هنا كشبكة أمان إضافية بعد normalize_persian_chars أدناه -- تلك تُطبِّع
# الحروف الفارسية الشائعة قبل هذا الفحص (العطل ٢أ)، وهذا الفحص يبقى ليلتقط
# ما لم يُطبَّع (كحروف أردية خارج نطاق هذا الـIssue) أو أي استدعاء مباشر
# لهذه الدالة يتجاوز التطبيع.
_PERSIAN_ONLY_RE = re.compile(
    "[پچژکگیۋےە"
    "ٹڈڑںھۀہ]"
)

# نطاقات يونيكود الخاصة بالعربية (الأساسي + الملحق + الامتداد أ + أشكال
# العرض التقديمي أ/ب) -- العطل ٢ب (Issue #639): بدل قائمة أبجديات محظورة
# (تفوّت الصينية والكيريلية واليونانية وأي أبجدية لم تُدرَج صراحة)، عُكس
# المنطق فصار الفحص أدناه يسمح بالعربية والأرقام والترقيم والمسافات فقط
# ويرفض أي شيء آخر -- لا فرق حينها بين حرف صيني وحرف لاتيني، كلاهما مرفوض
# بنفس الآلية. مكتوبة بترميز \u صراحة (بداية/نهاية كل نطاق) لنفس سبب
# _PERSIAN_ONLY_RE أعلاه -- المدى نفسه، لا حرف حرفي واحد، فالخطر أكبر لو
# انعكس اتجاه النص أثناء تحرير لاحق.
_ARABIC_BLOCK_RE = re.compile(
    "[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
)

# Issue #644 الإصلاح ١: صياغة النص لم تعد تنتج خانة ساعة (انظر
# format_transcript أدناه) -- طابع MM:SS يمكن أن تتجاوز دقائقه ٥٩ بلا سقف
# (فيديو ساعة ونصف ⇐ [90:xx])، فبات المخطّطان منفصلَين بدل مخطّط واحد بخانة
# ساعة اختيارية: HH:MM:SS (توافقًا مع مدخلات قديمة محتملة فقط، لا تُنتَج بعد
# الآن) بدقائق/ثوانٍ محدودة ٠-٥٩ كما يجب فعليًا داخل الساعة، وMM:SS بدقائق
# غير محدودة صراحة.
_TIMESTAMP_HMS_RE = re.compile(r"^(\d{1,2}):([0-5]\d):([0-5]\d)$")
_TIMESTAMP_MS_RE = re.compile(r"^(\d+):([0-5]\d)$")

# تطبيع الحروف الفارسية/التركية الشائعة إلى مقابلها العربي (العطل ٢أ،
# Issue #639) -- الحرف الفارسي "ی" مثلًا يشبه العربي "ي" بصريًا فلا ينتبه
# النموذج للفرق، وسابقًا كان هذا يعني رفض نقاط صحيحة المحتوى بالكامل. تطبيع
# لا حذف: النقطة تُقبَل بعده عاديًا بدل خسارتها. "چ" مستثناة من هذا الجدول
# لأن مقابلها العربي حرفان لا حرف واحد (str.translate لا يدعم هذا).
_PERSIAN_NORMALIZE_MAP = str.maketrans({
    "ی": "ي",
    "ک": "ك",
    "پ": "ب",
    "گ": "غ",
    "ژ": "ج",
    # صيغ فارسية/أردية بديلة لحرفي الهاء والتاء المربوطة العربيين -- الهمزة
    # المدمجة في "ۀ" (heh + hamza + yeh) تُحذف بتحويلها إلى هاء عادية بلا
    # نظير عربي مباشر لها.
    "ھ": "ه",
    "ہ": "ه",
    "ۀ": "ه",
})


def normalize_persian_chars(text: str) -> str:
    """يطبّع الحروف الفارسية/التركية الشائعة (انظر الجدول أعلاه) إلى مقابلها
    العربي، ويحذف الفاصل غير الظاهر ‌ (ZWNJ) الذي لا مقابل له في
    العربية. يُستدعى قبل فحص اللغة (validate_point) لا بدلًا منه -- تطبيع لا
    تحقّق، فحروف فارسية/أردية أخرى خارج هذا الجدول تبقى تُرفَض كما كانت."""
    text = text.replace("چ", "تش")
    text = text.translate(_PERSIAN_NORMALIZE_MAP)
    return text.replace("‌", "")


def find_non_arabic_char(text: str) -> str | None:
    """يعيد أول حرف غير عربي في النص، أو None إن كان عربيًا فصيحًا (مع
    الأرقام وعلامات الترقيم والمسافات والرموز) حصرًا. العطل ٢ب (Issue #639):
    فحص قائم على السماح لا الحظر -- أي حرف ليس عربيًا ولا رقمًا ولا ترقيمًا
    ولا مسافة ولا رمزًا يُرفَض، صينيًا كان أو كيريليًا أو يونانيًا أو لاتينيًا
    أو عبريًا، بلا حاجة لتعداد كل أبجدية محتملة صراحة. الحروف الفارسية/الأردية
    التي لم يطبّعها normalize_persian_chars (تقع داخل نطاق يونيكود العربي
    نفسه فلا يكفي فحص النطاق وحده) تُفحَص أولًا صراحة.

    Issue #642 العطل ٢: المعيار "نرفض الحروف الأجنبية، لا الرموز" -- الفحص
    السابق كان يسمح بفئة يونيكود الترقيم (P*) فقط، فرمز رياضي/عملة/علمي مثل
    `+` أو `$` أو `°` (فئة Sm/Sc/So/Sk) كان يُرفَض بصفته "حرفًا غير عربي" رغم
    كونه مشروعًا تمامًا في نص عربي، وهو ما ظلم نقاطًا صحيحة. عُكس المعيار:
    أي حرف من فئة "حرف" (L*) خارج نطاق العربية هو أبجدية أجنبية فيُرفَض،
    وأي شيء آخر (ترقيم أو رمز) مسموح -- بلا تعداد صريح لكل رمز محتمل."""
    match = _PERSIAN_ONLY_RE.search(text)
    if match:
        return match.group(0)
    for ch in text:
        if ch.isspace() or ch.isdigit():
            continue
        if _ARABIC_BLOCK_RE.match(ch):
            continue
        if not unicodedata.category(ch).startswith("L"):
            continue
        return ch
    return None


def parse_timestamp(raw: Any) -> int | None:
    """يحلّل طابعًا زمنيًا نصّيًا "MM:SS" (الصيغة المُنتَجة الآن، دقائق بلا
    سقف) أو "HH:MM:SS" (توافقًا مع صيغة قديمة، لم تعد تُنتَج -- انظر Issue
    #644) إلى ثوانٍ. يعيد None لأي صيغة غير مطابقة أو حقل فارغ/غير نصّي؛ لا
    نحاول تخمين رقم من نص لا يطابق الصيغة.

    Issue #642 العطل ١: النص المصوغ (format_transcript) يضع كل ختم بين
    قوسين مربّعين (`[12:34]`) ليظهر للنموذج، والبرومبت يأمره بنسخ الختم
    "كما هو" -- فينسخه القوسين معهما وهو يطيع التعليمة حرفيًا. تُجرَّد الأقواس
    المربّعة والمسافات الزائدة هنا أولًا -- هذا التجريد هو الضمان الفعلي، لا
    تعليمة البرومبت وحدها.

    Issue #644: بعد حذف خانة الساعة من format_transcript، الصيغة المُنتَجة
    فعليًا MM:SS بدقائق قد تتجاوز ٥٩ (فيديو ساعة ونصف ⇐ [90:xx]) -- فمخطّط
    HH:MM:SS القديم (دقائق/ثوانٍ محدودة ٠-٥٩ داخل الساعة) لم يعد يكفي وحده،
    ويُجرَّب أولًا لأنه أكثر تحديدًا (ثلاثة أجزاء)، ثم MM:SS بدقائق غير
    محدودة كمخطّط بديل."""
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip().replace("[", "").replace("]", "").strip()
    if not cleaned:
        return None
    match = _TIMESTAMP_HMS_RE.match(cleaned)
    if match:
        hours, minutes, seconds = (int(g) for g in match.groups())
        return hours * 3600 + minutes * 60 + seconds
    match = _TIMESTAMP_MS_RE.match(cleaned)
    if match:
        minutes, seconds = (int(g) for g in match.groups())
        return minutes * 60 + seconds
    return None


def validate_point(point: Any) -> tuple[bool, str, str, bool]:
    """يتحقق من الحقول الإلزامية والتصنيف واللغة لنقطة واحدة. يعيد (صالحة،
    سبب الرفض، فئة الرفض، طُبِّعت) -- الفئة "" عند النجاح، وإلا واحدة من
    "language"/"other" لتغذية عدّادات stats في run(). العنصر الرابع (طُبِّعت)
    يخبر الطالب إن غيّر normalize_persian_chars أدناه أيًّا من الحقول
    الثلاثة -- يُستعمَل في extract_points لتغذية عدّاد points_normalized عند
    النجاح فقط (Issue #639 العطل ٢أ).

    Issue #644 (الإصلاح ٢): لم تعد هذه الدالة تتحقق من طابع زمني أصلًا --
    النموذج لم يعد يُطلَب منه رقمًا (`timestamp` حُذف من المخطّط)، بل
    `anchor_text` نصّي يُعامَل كأي حقل نصّي إلزامي آخر هنا (لا فحص لغة عليه،
    مثل quote_original، لأنه منسوخ حرفيًا بلغة الفيديو الأصلية). تحويل
    anchor_text إلى طابع زمني فعلي يقع لاحقًا في extract_points عبر
    resolve_timestamp، بعد أن تنجح هذه الدالة -- فئة الرفض "timestamp_format"
    القديمة (نص لا يطابق [HH:]MM:SS) لم تعد ممكنة الحدوث: لا رقم يُطلَب من
    النموذج فلا صيغة رقمية ليُخطئ فيها.

    كذلك تُستبدَل الحقول الثلاثة العربية بنسختها المطبَّعة فارسيًا -- سواء
    نجحت النقطة أم فشلت لاحقًا، فالتطبيع تصحيح للنص لا حكم عليه."""
    if not isinstance(point, dict):
        return False, "عنصر ليس كائن JSON", "other", False
    for name in REQUIRED_FIELDS:
        if name not in point:
            return False, f"حقل ناقص: {name}", "other", False
    for name in ("statement", "speaker", "quote_original", "quote_arabic",
                 "anchor_text", "type", "topic_hint"):
        value = point.get(name)
        if not isinstance(value, str) or not value.strip():
            return False, f"حقل فارغ أو غير نصّي: {name}", "other", False
    if point["type"] not in VALID_TYPES:
        return False, f"تصنيف غير صالح: {point['type']}", "other", False

    # تطبيع فارسي/تركي قبل فحص اللغة (Issue #639 العطل ٢أ) -- بلا هذا
    # حروف فارسية بصريًا قريبة من نظيرها العربي (ی مقابل ي) كانت تُخسِر
    # نقاطًا صحيحة المحتوى بالكامل بدل تصحيحها.
    normalized = False
    for name in ("statement", "speaker", "quote_arabic"):
        fixed = normalize_persian_chars(point[name])
        if fixed != point[name]:
            normalized = True
        point[name] = fixed

    # العطل ٣+٤ (الأصلي) + العطل ٢ب (Issue #639): أي حرف هنا خارج العربية
    # والأرقام والترقيم يعني أن الترجمة لم تقع فعلًا أو أن اسم علم انكسر
    # بخلط حروف. quote_original وanchor_text مستثنيان عمدًا -- بلغة الفيديو
    # الأصلية، الدليل لا الترجمة.
    for name in ("statement", "speaker", "quote_arabic"):
        bad_char = find_non_arabic_char(point[name])
        if bad_char:
            return False, f"حرف غير عربي ({bad_char!r}) في {name}", "language", normalized

    return True, "", "", normalized


# ──────────────────────── استخراج الطابع بالبحث النصّي ────────────────────────
#
# Issue #644 الإصلاح ٢ (الحل الجذري): بدل أن يعيد النموذج طابعًا زمنيًا
# (رقم -- والنموذج ضعيف في نسخ الأرقام المتراصّة، شاهد الـIssue: نفس
# الدقائق/الثواني `40:44` مع ساعتين مختلفتين في نفس الفيديو)، يعيد مرساة
# نصّية (anchor_text -- والنموذج بارع في النسخ الحرفي، quote_original دقيق
# في كل تشغيلة سابقة). الشيفرة تبحث عن هذه المرساة في المقاطع وتحسب الطابع
# من مقطعها -- حساب برمجي لا يخطئ، لا نسخ نموذج لرقم.

# تطبيع خفيف للمقارنة (توحيد المسافات، حذف الترقيم، تجاهل التشكيل) -- كافٍ
# لمطابقة مرساة منسوخة حرفيًا تقريبًا رغم فروق تنسيقية طفيفة (علامة ترقيم
# لاصقة، مسافة مضاعفة)، لا محاولة تطابق لغوي عميق.
# نطاق التشكيل مكتوب بترميز \u صراحة (لا حروفًا حرفية) لنفس سبب
# _PERSIAN_ONLY_RE أعلاه -- تفادي خطأ كتابة صامت بسبب اتجاه النص من اليمين
# لليسار عند تحرير هذا الملف لاحقًا.
_ARABIC_DIACRITICS_RE = re.compile("[\u064B-\u065F\u0670\u06D6-\u06ED]")
_ANCHOR_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)
_TRANSCRIPT_LINE_RE = re.compile(r"^\[(\d+:[0-5]\d)\]\s?(.*)$")


def _normalize_for_anchor(text: str) -> str:
    text = _ARABIC_DIACRITICS_RE.sub("", text)
    text = _ANCHOR_PUNCTUATION_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def parse_transcript_segments(transcript_text: str) -> list[tuple[int, str]]:
    """يحلّل النص المصوغ (أسطر `[MM:SS] نص`، انظر format_transcript) إلى
    قائمة (ثوانٍ، نص المقطع) -- تُستهلَك في resolve_timestamp للبحث عن
    anchor_text وإرجاع طابع مقطعها. أسطر لا تطابق الصيغة (كعلامة الحذف
    TRUNCATION_MARKER في نص مقصوص) تُهمَل بصمت -- علامات بنيوية لا مقاطع
    فعلية لها طابع."""
    segments: list[tuple[int, str]] = []
    for line in transcript_text.splitlines():
        match = _TRANSCRIPT_LINE_RE.match(line)
        if not match:
            continue
        seconds = parse_timestamp(match.group(1))
        if seconds is None:
            continue
        segments.append((seconds, match.group(2)))
    return segments


def resolve_timestamp(anchor_text: Any, transcript_segments: list[tuple[int, str]]) -> int | None:
    """يبحث عن anchor_text (أول ٤-٦ كلمات من مقطع بعينه، كما نسخها النموذج)
    داخل نصوص transcript_segments ويعيد طابع المقطع المطابق -- الشيفرة تحسب
    الرقم من مطابقة نصّية، لا النموذج من ذاكرته أو تقديره. عند فشل التطابق
    التام، محاولة ثانية بأول ٣ كلمات فقط من المرساة (تحسّبًا لاختلاف طفيف
    كإسقاط كلمة أخيرة)، وإلا None -- فراغ صادق أفضل من طابع خاطئ، تمامًا
    كمبدأ الحقل الفارغ القديم الذي حلّت هذه الدالة محله."""
    if not isinstance(anchor_text, str) or not anchor_text.strip():
        return None
    normalized_anchor = _normalize_for_anchor(anchor_text)
    if not normalized_anchor:
        return None

    def _search(anchor: str) -> int | None:
        for seconds, text in transcript_segments:
            if anchor in _normalize_for_anchor(text):
                return seconds
        return None

    found = _search(normalized_anchor)
    if found is not None:
        return found

    words = normalized_anchor.split(" ")
    if len(words) > 3:
        found = _search(" ".join(words[:3]))
        if found is not None:
            return found

    return None


# ──────────────────────────── سحب النص ────────────────────────────


def _format_timestamp(seconds: float) -> str:
    """MM:SS بلا خانة ساعة (Issue #644 الإصلاح ١) -- خانة الساعة كانت عديمة
    الفائدة (كل فيديوهات المسار تحت ساعتين ونصف، config.yaml:
    youtube.max_duration_minutes) ووجودها هو ما دفع النموذج لقراءة الأعمدة
    عموديًا فيخلط ساعة ختم بدقائق وثواني ختم مجاور رغم تطابقهما تمامًا (شاهد
    الـIssue: `00:40:44` و`06:40:44` في نفس الفيديو). الدقائق هنا تتجاوز ٥٩
    بلا سقف (`divmod(total, 60)` لا `divmod(rem, 3600)` ثم ٦٠) -- فيديو ساعة
    ونصف ينتج [90:xx] لا [01:30:xx]، ولا مكان بعدها لخلط عمودي بين خانتين."""
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"


def format_transcript(fetched) -> str:
    """يصوغ مقاطع الترجمة بختم زمني ظاهر قبل كل مقطع (العطل ١) -- بلا هذا
    كان النموذج يمرَّر نصًّا متصلًا بلا أختام فيؤلّف طوابع مستديرة الشكل
    (٦٠، ١٨٠، ٣٦٠٠) لا سند فعلي لها في النص."""
    return "\n".join(f"[{_format_timestamp(segment.start)}] {segment.text}"
                      for segment in fetched)


def _fetch_once(video_id: str, proxy_config, session: requests.Session | None) -> tuple[str, str]:
    """محاولة سحب واحدة بلا أي تراجع -- منفصلة عن fetch_transcript كي يمكن
    حقن بديل مزيَّف لها في الاختبارات ففحص منطق التراجع الأُسّي بلا شبكة
    فعلية (Issue #637 العطل ٣)."""
    from youtube_transcript_api import YouTubeTranscriptApi

    ytt_api = (YouTubeTranscriptApi(proxy_config=proxy_config, http_client=session)
               if session is not None else YouTubeTranscriptApi(proxy_config=proxy_config))
    transcript_list = ytt_api.list(video_id)
    transcript = next(iter(transcript_list))  # قد يرفع StopIteration
    fetched = transcript.fetch()
    return format_transcript(fetched), transcript.language_code


def _should_retry(attempt: int, delays: list[float]) -> tuple[bool, float | None]:
    """قرار صِرف بلا أثر جانبي: هل تبقّت محاولة تراجع، وبعد كم ثانية --
    مفصولة عن fetch_transcript لفحصها بلا شبكة ولا time.sleep فعلي."""
    if attempt < len(delays):
        return True, delays[attempt]
    return False, None


def fetch_transcript(video_id: str, proxy_config, session: requests.Session | None = None,
                      backoff_seconds: list[float] | None = None,
                      fetch_once=_fetch_once,
                      ) -> tuple[str | None, str | None, bool]:
    """يعيد (النص المصوغ بأختامه الزمنية، رمز اللغة، أُرهق التراجع) عند
    النجاح، أو (None، سبب الفشل، أُرهق التراجع) عند الفشل. بلغته الأصلية
    دومًا -- لا نطلب ترجمة يوتيوب الآلية الرديئة؛ الترجمة إلى العربية تقع
    لاحقًا داخل نموذج الاستخلاص على النص الأصلي.

    Issue #637 العطل ٣: عنوان بروكسي واحد يُحجَب مؤقتًا (429 ⇐ IpBlocked
    من المكتبة) أو ينقطع اتصاله (RemoteDisconnected، يصل هنا مغلَّفًا بـ
    requests.exceptions.ConnectionError) رغم البروكسي إن أُرهق بطلبات
    متتابعة بلا فسحة كافية -- تراجع أُسّي محدود بـbackoff_seconds قبل
    إسقاط الفيديو نهائيًا، بدل إسقاطه من أول 429 عابر. العنصر الثالث
    المُعاد (أُرهق التراجع) يميّز هذا الإسقاط عن أعطال أخرى (لا نص متاح،
    فيديو غير متوفر) في stats: run() لا يرفع videos_rate_limited إلا هنا."""
    from youtube_transcript_api import (
        IpBlocked,
        NoTranscriptFound,
        RequestBlocked,
        TranscriptsDisabled,
        VideoUnavailable,
    )

    delays = list(backoff_seconds or [])
    attempt = 0
    while True:
        try:
            text, language_code = fetch_once(video_id, proxy_config, session)
            return text, language_code, False
        except StopIteration:
            return None, "لا نص متاح: لا مسارات ترجمة للفيديو", False
        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as exc:
            return None, f"لا نص متاح: {exc}", False
        except (IpBlocked, RequestBlocked) as exc:
            retry, delay = _should_retry(attempt, delays)
            if not retry:
                return None, f"محجوب من يوتيوب بعد {len(delays)} إعادة محاولة: {exc}", True
            log.warning("حجب مؤقت من يوتيوب لفيديو %s (محاولة %d/%d)، انتظار %sث",
                        video_id, attempt + 1, len(delays), delay)
            time.sleep(delay)
            attempt += 1
        except requests.exceptions.ConnectionError as exc:
            retry, delay = _should_retry(attempt, delays)
            if not retry:
                return None, f"انقطاع اتصال متكرر بعد {len(delays)} إعادة محاولة: {exc}", True
            log.warning("انقطاع اتصال لفيديو %s (محاولة %d/%d)، انتظار %sث",
                        video_id, attempt + 1, len(delays), delay)
            time.sleep(delay)
            attempt += 1
        except Exception as exc:  # noqa: BLE001 -- الفشل الصامت ممنوع، كل عطل يُسجَّل
            return None, f"خطأ غير متوقَّع أثناء سحب النص: {exc}", False


# ──────────────────────────── حارس الموضوع ────────────────────────────


def classify_topic(video_title: str, transcript_excerpt: str, cfg: Config,
                    client: Anthropic | None = None) -> tuple[str, str | None]:
    """نداء قصير جدًا (العنوان + مقتطف من أول النص) يصنّف الفيديو قبل إنفاق
    نداء الاستخلاص الكامل عليه (العطل ٥) -- الحرّاس السابقة ميّزت المدة لا
    نوع المحتوى، فمرّت نشرات ورياضة نجت في المدة لكنها لا تحمل تحليلًا.
    يعيد (التصنيف، سبب فشل النداء إن حدث). فشل النداء لا يُسقِط الفيديو
    ويُفترَض معه أنه صالح للاستخلاص -- عطل شبكي عابر ليس دليلًا على أن
    الفيديو نشرة أو رياضة، وإسقاطه صامتًا لهذا السبب يناقض مبدأ المشروع في
    عدم الفشل الصامت."""
    model = cfg.path("youtube.extract.topic_guard_model",
                      cfg.path("youtube.extract.model", "claude-haiku-4-5-20251001"))
    excerpt_chars = cfg.path("youtube.extract.topic_guard_excerpt_chars", 2000)
    client = client or Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=50,
            tools=[TOPIC_SCHEMA],
            tool_choice={"type": "tool", "name": "classify_video_topic"},
            system=TOPIC_SYSTEM,
            messages=[{"role": "user", "content":
                       f"العنوان: {video_title}\n\nمقتطف من النص:\n{transcript_excerpt[:excerpt_chars]}"}],
            # لا تُضِف temperature -- نماذج هذا المشروع ترفضها بـ400.
        )
    except APIError as exc:
        return "political_analysis", f"فشل نداء حارس الموضوع: {exc}"

    data = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
    category = data.get("category") if isinstance(data, dict) else None
    if category not in TOPIC_CATEGORIES:
        return "political_analysis", None
    return category, None


# ──────────────────────────── حارس أسماء الأعلام ────────────────────────────


def find_unsourced_name(statement: str, quote_original: str, known_figures: list) -> str | None:
    """تحقّق بأفضل ما يمكن (Issue #639 العطل ١ بند ب) لا استخراج أعلام عامّ:
    يقارن statement بقائمة مرجعية صغيرة من config.yaml
    (youtube.extract.known_figures) بدل محاولة استخراج كل اسم عَلَم من نص
    عربي بلا حروف كبيرة تميّزه -- تلك مهمة تصنيف لغوي غير موثوقة، بينما
    مطابقة قائمة صغيرة بأسماء بدائلها (aliases) في quote_original بسيطة
    ومحدودة الأثر. يعيد أول اسم عربي من القائمة ظهر في statement بلا أي من
    أسمائه البديلة في quote_original -- إشارة لاحتمال نسبة مختلَقة (Issue
    الأصلي: النموذج أضاف "إدارة جو بايدن" ولم يذكر السياسي التركي بايدن
    إطلاقًا). لا تُستعمَل هذه الدالة لرفض النقطة -- الترجمة الصوتية تجعل
    غياب أي alias مطابق غير حاسم، فالمرجع هو استدعاء الطالب لها في
    extract_points ليُسجَّل تحذيرًا في failed لا رفضًا تلقائيًا."""
    quote_casefold = quote_original.casefold()
    for figure in known_figures or []:
        if not isinstance(figure, dict):
            continue
        ar_name = figure.get("ar")
        if not ar_name or ar_name not in statement:
            continue
        aliases = figure.get("aliases") or []
        if any(isinstance(alias, str) and alias.casefold() in quote_casefold
               for alias in aliases):
            continue
        return ar_name
    return None


# ──────────────────────────── الاستخلاص عبر النموذج ────────────────────────────


TRUNCATION_MARKER = "[... تم حذف جزء من النص ...]"


def _truncate_transcript(text: str, max_chars: int) -> str:
    """يبقي النصف الأول والنصف الأخير من نص طويل معًا مع علامة حذف صريحة
    بينهما عند تجاوز max_chars، لا قصًّا من النهاية فقط (Issue #637 العطل ٢)
    -- خاتمة المواد التحليلية غالبًا تحمل الخلاصة، فقصّها يفقد أثمن جزء من
    المصدر بالضبط في الفيديوهات التي يستهدفها هذا الحدّ.

    Issue #642 العطل ٣ج: العلامة (TRUNCATION_MARKER) صريحة الصياغة عمدًا --
    "تم حذف جزء من النص"، لا مجرّد فاصل بصري -- ليعرف النموذج أن هناك فجوة
    حقيقية في الترجمة المصدرية فلا يستنتج تسلسلًا زمنيًا متصلًا عبرها، ولا
    يبني ختمًا لمقطع يقع داخلها (البرومبت يشرح هذا صراحة، انظر
    prompts/youtube_extract.md)."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + f"\n{TRUNCATION_MARKER}\n" + text[-half:]


def extract_points(video_title: str, transcript_text: str, language: str, duration_seconds: int,
                    cfg: Config, client: Anthropic | None = None
                    ) -> tuple[list[dict], list[dict], str | None, str | None]:
    """نداء نموذج رخيص واحد لكل فيديو عبر إخراج مهيكل (tool_use بمخطط
    مُعرَّف) بدل طلب JSON نصًّا (العطل ٢) -- النموذج يملأ حقولًا مُعرَّفة
    فلا يستطيع كسر البنية أصلًا. عند غياب إخراج مهيكل صالح: محاولة واحدة
    إضافية، ثم فشل مسجَّل مع أول ٥٠٠ حرف من أي نص مخرَج للتشخيص، ومعه طول
    النص المُرسَل وسبب التوقف (stop_reason) إن كان القطع بسبب max_tokens
    (Issue #637 العطل ٢).

    يعيد (النقاط الصالحة، النقاط المرفوضة كل منها بسببها وفئتها، سبب فشل
    النداء العام إن حدث -- None عند النجاح ولو بلا نقاط، ملاحظة قصّ النص إن
    وقع -- None إن لم يُقصّ شيء). كل نقطة صالحة قد تحمل مفتاحين داخليين
    مؤقتين لا يدخلان المخرج النهائي (يُستهلَكان في run() فقط ثم يُهمَلان عند
    بناء قاموس النقطة الأخير): "_normalized" (طُبِّعت فارسيًا وقُبِلت بعده --
    Issue #639 العطل ٢أ) و"_unsourced_name" (اسم عَلَم مشكوك في نسبته --
    العطل ١ بند ب). حقل "timestamp" في النقطة الصالحة قد يكون None -- بحث
    resolve_timestamp عن anchor_text فشل (Issue #644 الإصلاح ٢، عدّاد
    points_timestamp_unresolved في run()؛ حقل "anchor_text" الخام نفسه لا
    يدخل هو الآخر المخرج النهائي، أداة داخلية فقط).

    العنصر الرابع المُعاد (ملاحظة القصّ) يُسجَّل في run() ضمن failed لا فقط
    في log (Issue #642 العطل ٣د) -- بلا هذا لا نعرف كم مرة يقع القصّ فعليًا
    عبر التشغيلات، وهو الشاهد التشخيصي وراء اختلاق الأختام في الفيديوهات
    الطويلة (العطل ٣)."""
    model = cfg.path("youtube.extract.model", "claude-haiku-4-5-20251001")
    max_tokens = cfg.path("youtube.extract.max_tokens", 2000)
    max_retries = cfg.path("youtube.extract.max_retries", 2)
    max_transcript_chars = cfg.path("youtube.extract.max_transcript_chars", 60000)
    client = client or Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))

    sent_text = _truncate_transcript(transcript_text, max_transcript_chars)
    truncation_note = None
    if len(sent_text) < len(transcript_text):
        truncation_note = (f"نص الفيديو قُصّ من {len(transcript_text)} إلى {len(sent_text)} "
                            f"حرفًا (max_transcript_chars)")
        log.info("%s: %s", video_title[:60], truncation_note)

    raw_points: list | None = None
    last_snippet = ""
    last_resp = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                tools=[EXTRACT_POINTS_SCHEMA],
                tool_choice={"type": "tool", "name": "extract_points"},
                system=load_prompt(),
                messages=[{"role": "user", "content":
                           f"لغة النص الأصلية: {language}\n\nالنص الكامل للفيديو، مع أختامه "
                           f"الزمنية الظاهرة قبل كل مقطع:\n{sent_text}"}],
                # لا تُضِف temperature -- نماذج هذا المشروع ترفضها بـ400.
            )
        except APIError as exc:
            return [], [], f"فشل نداء النموذج: {exc}", truncation_note

        last_resp = resp
        data = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
        candidate = data.get("points") if isinstance(data, dict) else None
        if isinstance(candidate, list):
            raw_points = candidate
            break
        text_snippet = "".join(b.text for b in resp.content
                                if getattr(b, "type", "") == "text")[:500]
        stop_reason = getattr(resp, "stop_reason", None)
        if stop_reason == "max_tokens":
            last_snippet = (f"[قُطع الإخراج: stop_reason=max_tokens، طول النص المُرسَل "
                             f"{len(sent_text)} حرفًا] {text_snippet}")
        else:
            last_snippet = text_snippet
        log.warning("محاولة %d/%d: لم يُعِد النموذج إخراجًا مهيكلًا صالحًا لـ%r "
                    "(stop_reason=%s، طول النص %d حرفًا)",
                    attempt, max_retries, video_title[:60], stop_reason, len(sent_text))

    if raw_points is None:
        usage_note = ""
        usage = getattr(last_resp, "usage", None)
        if usage is not None:
            usage_note = (f"، رموز مستهلكة: مدخل {getattr(usage, 'input_tokens', '؟')}"
                          f"/مخرج {getattr(usage, 'output_tokens', '؟')}")
        return ([], [],
                f"تعذّر الحصول على إخراج مهيكل صالح بعد {max_retries} محاولة/محاولات "
                f"(طول النص المُرسَل {len(sent_text)} حرفًا{usage_note}): {last_snippet!r}",
                truncation_note)

    known_figures = cfg.path("youtube.extract.known_figures", [])
    # المقاطع تُحلَّل من sent_text لا transcript_text الكامل -- anchor_text
    # نُسِخ مما رآه النموذج فعليًا (Issue #644 الإصلاح ٢)، فالبحث في مقاطع
    # لم يرها أصلًا لا معنى له، وقد يطابق صدفة نصًّا مكرَّرًا في الجزء
    # المحذوف بالقصّ الذكي (_truncate_transcript).
    transcript_segments = parse_transcript_segments(sent_text)

    valid: list[dict] = []
    rejected: list[dict] = []
    for raw in raw_points:
        anchor_text = raw.get("anchor_text") if isinstance(raw, dict) else None
        ok, reason, kind, normalized = validate_point(raw)
        if not ok:
            rejected.append({"reason": reason, "kind": kind})
            log.warning("نقطة مرفوضة من %r (%s)", video_title[:60], reason)
            continue
        # Issue #644 الإصلاح ٢ (الحل الجذري): الطابع لم يعد يُطلَب رقمًا من
        # النموذج -- يُستخرَج ببحث نصّي عن anchor_text في مقاطع الفيديو نفسها
        # (resolve_timestamp)، فالشيفرة تحسب الرقم لا النموذج.
        resolved = resolve_timestamp(anchor_text, transcript_segments)
        # الحارس الأخير الإلزامي (العطل ١، بند ج) يبقى للأمان، لكنه الآن
        # مستحيل الحدوث بنيويًا: طابع مأخوذ من مقطع ينتمي فعلًا لهذا الفيديو
        # لا يمكن أن يتجاوز مدته (Issue #644 معايير القبول: توقّع صفر هنا).
        # طابع None (فشل البحث) لا يُقارَن بمدة الفيديو أصلًا -- لا قيمة
        # لمقارنته، وليس عطلًا يستوجب الرفض (نفس مبدأ Issue #642 العطل ٣ب).
        if resolved is not None and resolved > duration_seconds:
            reason = f"طابع محلول: {resolved}ث → مدة الفيديو: {duration_seconds}ث"
            rejected.append({"reason": reason, "kind": "timestamp"})
            log.warning("نقطة مرفوضة من %r (%s)", video_title[:60], reason)
            continue
        raw["timestamp"] = resolved
        # طُبِّعت وقُبِلت (Issue #639 العطل ٢أ) -- تُحسَب "أُنقذت" فقط هنا،
        # لا في validate_point نفسها، لأن نقطة طُبِّعت ثم رُفضت لسبب آخر لم
        # "تُنقَذ" فعليًا.
        raw["_normalized"] = normalized
        # تحذير لا رفض (Issue #639 العطل ١ بند ب) -- انظر توثيق
        # find_unsourced_name أعلاه لسبب عدم الرفض التلقائي.
        raw["_unsourced_name"] = find_unsourced_name(
            raw["statement"], raw["quote_original"], known_figures)
        valid.append(raw)
    return valid, rejected, None, truncation_note


# ──────────────────────────── التشغيلة الكاملة ────────────────────────────


def run(cfg: Config | None = None, youtube_api_key: str | None = None,
        anthropic_client: Anthropic | None = None, now: datetime | None = None) -> dict:
    cfg = cfg or load_config()
    now = now or datetime.now(timezone.utc)

    collected = youtube_collect.run(cfg, api_key=youtube_api_key, now=now)
    videos = collected["videos"]
    failed: list[dict] = list(collected["failed"])
    points: list[dict] = []
    transcripts_ok = 0
    transcripts_failed = 0
    videos_rejected_topic = 0
    videos_rate_limited = 0
    points_rejected_timestamp = 0
    points_rejected_language = 0
    points_normalized = 0
    points_flagged_unsourced_name = 0
    points_timestamp_resolved = 0
    points_timestamp_unresolved = 0
    transcript_sample_logged = False

    proxy_cfg = get_proxy_config()
    total_bytes = 0
    session = requests.Session()

    def _track_bytes(response, *args, **kwargs):  # noqa: ANN001 -- توقيع خطّاف requests
        nonlocal total_bytes
        total_bytes += len(response.content)

    session.hooks["response"].append(_track_bytes)

    sleep_range = tuple(cfg.path("youtube.extract.transcript_sleep_range", [5.0, 12.0]))
    channel_sleep_range = tuple(cfg.path("youtube.extract.channel_sleep_range", [10.0, 20.0]))
    backoff_seconds = list(cfg.path("youtube.extract.rate_limit_backoff_seconds", [15, 45, 90]))

    for i, video in enumerate(videos):
        print(f"استخلاص: {video.video_title[:60]} ({video.channel})", file=sys.stderr)
        text, lang_or_reason, rate_limited = fetch_transcript(
            video.video_id, proxy_cfg, session, backoff_seconds)
        if text is None:
            transcripts_failed += 1
            if rate_limited:
                videos_rate_limited += 1
            failed.append({"channel": video.channel, "video_id": video.video_id,
                           "title": video.video_title, "reason": lang_or_reason})
        else:
            transcripts_ok += 1
            # عيّنة تشخيصية مرة واحدة لكل تشغيلة (Issue #637 العطل ١ بند د):
            # تتحقّق من أن الأختام تُكتب فعلًا [00:12:34] كما يتوقّع البرومبت،
            # بلا تسجيل نص أي فيديو بعينه على نحو متكرر.
            if not transcript_sample_logged:
                log.info("عيّنة أول 300 حرف من نص مصوغ: %r", text[:300])
                transcript_sample_logged = True
            category, classify_error = classify_topic(video.video_title, text, cfg,
                                                        anthropic_client)
            if classify_error:
                log.warning("حارس الموضوع فشل لـ%r، يُستخلَص احتياطيًا بدل إسقاطه صامتًا: %s",
                            video.video_title[:60], classify_error)
            if category != "political_analysis":
                videos_rejected_topic += 1
                failed.append({"channel": video.channel, "video_id": video.video_id,
                               "title": video.video_title,
                               "reason": f"أُهمل قبل الاستخلاص -- حارس الموضوع صنّفه: {category}"})
                print(f"  → أُهمل (حارس الموضوع: {category})", file=sys.stderr)
            else:
                valid_points, rejected_points, error, truncation_note = extract_points(
                    video.video_title, text, lang_or_reason, video.duration_seconds,
                    cfg, anthropic_client)
                if error:
                    failed.append({"channel": video.channel, "video_id": video.video_id,
                                   "title": video.video_title, "reason": error})
                if truncation_note:
                    # Issue #642 العطل ٣د: يُسجَّل في failed لا في log فقط --
                    # لنعرف عبر التشغيلات كم مرة يقع القصّ فعليًا (الشاهد
                    # التشخيصي وراء اختلاق الأختام في الفيديوهات الطويلة).
                    failed.append({"channel": video.channel, "video_id": video.video_id,
                                   "title": video.video_title, "reason": truncation_note})
                for r in rejected_points:
                    failed.append({"channel": video.channel, "video_id": video.video_id,
                                   "title": video.video_title,
                                   "reason": f"نقطة مرفوضة ({r['kind']}): {r['reason']}"})
                    if r["kind"] == "timestamp":
                        points_rejected_timestamp += 1
                    elif r["kind"] == "language":
                        points_rejected_language += 1
                for p in valid_points:
                    if p.get("_normalized"):
                        points_normalized += 1
                    # Issue #644 الإصلاح ٢: نجاح/فشل resolve_timestamp في
                    # إيجاد anchor_text داخل المقاطع -- لا "تُرك فارغًا" من
                    # النموذج بعد الآن (لم يعد يُطلَب منه رقم أصلًا).
                    if p["timestamp"] is not None:
                        points_timestamp_resolved += 1
                    else:
                        points_timestamp_unresolved += 1
                    unsourced_name = p.get("_unsourced_name")
                    if unsourced_name:
                        points_flagged_unsourced_name += 1
                        # تحذير لا رفض (Issue #639 العطل ١ بند ب) -- النقطة
                        # تدخل points كما هي أدناه، هذا فقط يسجّل الشك
                        # للمراجعة اليدوية في failed.
                        failed.append({
                            "channel": video.channel, "video_id": video.video_id,
                            "title": video.video_title,
                            "reason": (f"اسم علم مشكوك في نسبته (unsourced_name): "
                                       f"{unsourced_name!r} ظهر في statement بلا نظير "
                                       f"له في quote_original -- statement: {p['statement']!r}")})
                    points.append({
                        "video_id": video.video_id,
                        "channel": video.channel,
                        "bloc": video.bloc,
                        "language": lang_or_reason,
                        "video_title": video.video_title,
                        "video_url": video.video_url,
                        "duration_seconds": video.duration_seconds,
                        "statement": p["statement"],
                        "speaker": p["speaker"],
                        "quote_original": p["quote_original"],
                        "quote_arabic": p["quote_arabic"],
                        "timestamp": p["timestamp"],
                        "type": p["type"],
                        "topic_hint": p["topic_hint"],
                    })
                print(f"  → {len(valid_points)} نقطة", file=sys.stderr)
        text = None  # إهمال صريح -- لا يُحتفَظ بالنص بعد هذه النقطة
        if i < len(videos) - 1:
            # فاصل أطول عند الانتقال إلى قناة مختلفة (Issue #637 العطل ٣) --
            # يوزّع الحمل على عنوان البروكسي بدل معدّل ثابت طوال التشغيلة.
            if videos[i + 1].channel != video.channel:
                time.sleep(random.uniform(*channel_sleep_range))
            else:
                time.sleep(random.uniform(*sleep_range))

    return {
        "run_date": now.strftime("%Y-%m-%d"),
        "stats": {
            "channels_checked": collected["stats"]["channels_checked"],
            "videos_found": collected["stats"]["videos_found"],
            "passed_guards": collected["stats"]["passed_guards"],
            "transcripts_ok": transcripts_ok,
            "transcripts_failed": transcripts_failed,
            "videos_rejected_topic": videos_rejected_topic,
            "videos_rate_limited": videos_rate_limited,
            "points_extracted": len(points),
            "points_rejected_timestamp": points_rejected_timestamp,
            "points_rejected_language": points_rejected_language,
            "points_normalized": points_normalized,
            "points_flagged_unsourced_name": points_flagged_unsourced_name,
            "points_timestamp_resolved": points_timestamp_resolved,
            "points_timestamp_unresolved": points_timestamp_unresolved,
            "proxy_bandwidth_mb": round(total_bytes / (1024 * 1024), 3),
        },
        "failed": failed,
        "points": points,
    }


def save_output(result: dict) -> Path:
    POINTS_DIR.mkdir(parents=True, exist_ok=True)
    path = POINTS_DIR / f"{result['run_date']}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    result = run()
    path = save_output(result)
    stats = result["stats"]
    print(f"ملف النقاط: {path}")
    print(f"القنوات: {stats['channels_checked']} · ضمن النافذة: {stats['videos_found']} "
          f"· ناجية بعد الحرّاس: {stats['passed_guards']}")
    print(f"نصوص ناجحة: {stats['transcripts_ok']} · فاشلة: {stats['transcripts_failed']} "
          f"· محجوبة مؤقتًا (تجاوزت التراجع): {stats['videos_rate_limited']}")
    print(f"أُهمل قبل الاستخلاص (حارس الموضوع): {stats['videos_rejected_topic']}")
    print(f"نقاط مستخلَصة: {stats['points_extracted']} "
          f"· مرفوضة (تجاوز مدة الفيديو): {stats['points_rejected_timestamp']} "
          f"· مرفوضة (لغة): {stats['points_rejected_language']}")
    print(f"مُطبَّعة فارسيًا فأُنقِذت: {stats['points_normalized']} "
          f"· أسماء أعلام مشكوكة (تحذير لا رفض): {stats['points_flagged_unsourced_name']} "
          f"· طابع محلول من المرساة: {stats['points_timestamp_resolved']} "
          f"· مرساة لم تُوجَد: {stats['points_timestamp_unresolved']}")
    print(f"استهلاك البروكسي التقديري: {stats['proxy_bandwidth_mb']} ميجابايت")
    if result["failed"]:
        print(f"تعذّر: {len(result['failed'])}")
        for entry in result["failed"]:
            label = entry.get("title") or entry.get("video_id") or "?"
            print(f"  - {entry['channel']}: {label}: {entry['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
