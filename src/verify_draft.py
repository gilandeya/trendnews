"""صياغة مسودة خبر من الوقائع المؤكَّدة وحدها — المرحلة الثانية من مسار
التحقق (Issue #334)، تُستدعى من verify.py بعد بناء تقرير المرحلة الأولى.

معزولة عمدًا في وحدة مستقلة عن verify.py: الضمان البنيوي للقاعدة الملزمة
الأولى («المقال مصدر إلهام لا معلومة») هو أن دالّة الصياغة هنا لا تقبل نص
مقال في توقيعها أصلًا — لا مراجعة يدوية تضمن ذلك، بل الاستيراد نفسه. لو
عاشت هذه الدالة داخل verify.py حيث `body: str` (نص المقال) في نطاق كل
دالّة تقريبًا، أي تعديل مستقبِل سهل الخطأ بتمرير `body` إليها بالغلط.

تسلسل القرار في attempt():
  0) _write_access_reason() — هل يعلن هذا التشغيل صلاحية كتابة أصلًا؟
     (تعليق ما قبل الدمج على Issue #334، نقطة 1 — انظر تذييل الدالة)
  1) sufficiency() — هل يكفي المؤكَّد لخبر قائم بذاته؟ (القاعدة 7)
  2) _validate_sources() — لكل واقعة مؤكَّدة مصدر بنص ورابط صالحين فعلًا؟
  3) _draft_from_facts() — الصياغة، من الوقائع ومقتطفات مصادرها حصرًا
  4) check_originality() — فحص بعدي: لا نسخ حرفي من المقال ولا من المصادر
كل بند يمتنع برسالة سبب محددة — لا فشل صامت، ولا رجوع لمحتوى غير مؤكَّد.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
from datetime import datetime, timezone

from . import evidence, extract, headlines as headlines_mod, imaging, review, store, writer
from . import verify
from .config import DRAFTS_DIR
from .imagesearch import find_images
from .request import _AR_STOP, _AR_TRANS
from .sources import Article

log = logging.getLogger("verify_draft")

DRAFT_ORIGIN = "verify"
WRITE_ENABLED_ENV = "VERIFY_DRAFT_WRITE_ENABLED"


# ──────────────────────── صلاحية الكتابة (دفاع في العمق) ────────────────────


def _write_access_reason() -> str:
    """يمنع إنفاق أي تكلفة نموذج أو بناء صورة قبل التأكد أن هذا التشغيل
    يستطيع فعليًا حفظ ما يُنتَج. لا اعتماد على افتراض أن
    `.github/workflows/verify.yml` يحمل تعديل contents:write + خطوات
    الرفع: العدد المذكور دُمج تاريخيًا من دونه فعلًا (GitHub App لا يملك
    صلاحية تعديل ملفات workflow — تعليق ما قبل الدمج على Issue #334، نقطة
    1)، وحينها ينفّذ verify.py القديم `src.verify` بلا أي خطوة رفع أو فتح
    Issue مراجعة: attempt() كانت ستصوغ محتوى مكلفًا (نداء نموذج + بحث/بناء
    صورة) ثم store.save_draft() يكتبه محليًا في نسخة العامل المؤقتة فقط —
    يُهمَل صامتًا حين ينتهي التشغيل، بينما يقرأ البشر في التقرير "✅ صيغت
    مسودة... ستظهر في أقرب Issue مراجعة" التي لن تُفتح أبدًا. فحص فاعل هنا
    يمنع هذا التناقض الصامت تحديدًا.

    التصريح مقصود لا فحص صلاحية حي عبر GitHub API: خطوة "تنفيذ التحقق" في
    verify.yml تُعلن `VERIFY_DRAFT_WRITE_ENABLED=true` صراحةً إلى جانب
    `permissions.contents: write` — إن غاب المتغيّر فالملف المطبَّق فعليًا
    ليس الملف المعتمد. لا يلغي هذا حاجة خطوة "رفع مسودة المؤكَّد" في
    الـ workflow لفحصها الخاص (git push يفشل بخطأ صريح إن كانت الصلاحية
    الفعلية غائبة رغم إعلان المتغيّر خطأً) — هذا دفاع أول أرخص وأبكر، لا
    بديل عنه."""
    if os.environ.get(WRITE_ENABLED_ENV) != "true":
        return (
            "صلاحية الكتابة غير معلَنة لهذا التشغيل "
            f"(متغيّر البيئة {WRITE_ENABLED_ENV} غائب أو ليس \"true\") — "
            "تأكد أن .github/workflows/verify.yml يحمل التعديل الذي يضبط "
            "permissions.contents: write ويُعلن هذا المتغيّر في خطوة "
            "«تنفيذ التحقق» (راجع تعليق ما قبل الدمج على Issue #334)؛ بلا "
            "هذا التعديل تُصاغ المسودة ثم تُهمَل صامتًا لأن لا خطوة تحفظها"
        )
    return ""


# ──────────────────────────── الكفاية (القاعدة 7) ────────────────────────────


def _central_fact(facts: list[dict]) -> dict:
    """الواقعة المحورية: أول ادّعاء **ليس** مُحدِّد إسناد/يقين منفصل
    (is_qualifier) — لا facts[0] الخام (البند 1، Issue #339). فصل مُحدِّدات
    الإسناد في extract_claims (رسميًا/تأكيدًا/بحسب بيان رسمي...) يغيّر
    ترتيب الاستخراج: مُحدِّد كـ"الانضمام معلَن رسميًا" قد يخرج قبل ادّعاء
    الحدث نفسه في claims، فاعتماد الموضع الخام وحده كان سيجعل مُحدِّدًا
    مفصولًا هو "الواقعة المحورية" خطأً — بالضبط العطل الذي طلب فصل
    المُحدِّدات حله أصلًا. تراجع لـ facts[0] فقط حين تكون كل الوقائع
    المستخرجة مُحدِّدات (حافة نادرة لا يُفترض وقوعها عمليًا) بدل الانهيار
    على قائمة غير فارغة."""
    for f in facts:
        if not f.get("is_qualifier"):
            return f
    return facts[0]


def sufficiency(facts: list[dict], cfg) -> tuple[bool, str]:
    """معيار الكفاية: دالّة نقية بلا نموذج (تعليق الموافقة على Issue #334،
    نقطة 2). الواقعة المحورية = أول ادّعاء ليس مُحدِّد إسناد مفصول عن حدثه
    (_central_fact، Issue #339 — لا facts[0] الخام كما كان، فذلك أعاد
    مُحدِّدًا مفصولًا مثل "الواقعة المحورية" خطأً حين يخرج قبل ادّعاء
    الحدث نفسه). شرط منفصل عن العدّ: عدد كافٍ من التفاصيل الهامشية
    المؤكَّدة لا يعوّض واقعة محورية غير مؤكَّدة."""
    vd_cfg = cfg.get("verify_draft", {}) or {}
    min_confirmed_facts = int(vd_cfg.get("min_confirmed_facts", 2))

    if not facts:
        return False, "لا وقائع مستخرجة من المقال"

    central = _central_fact(facts)
    if central["status"] != verify.STATUS_CONFIRMED:
        return False, (f"الواقعة المحورية (index {central.get('index', 0)}) "
                       f"«{central['text']}» غير مؤكَّدة (حكمها: {central['status']})")

    confirmed = [f for f in facts if f["status"] == verify.STATUS_CONFIRMED]
    if len(confirmed) < min_confirmed_facts:
        return False, (f"عدد الوقائع المؤكَّدة ({len(confirmed)}) دون الحد الأدنى "
                       f"({min_confirmed_facts}) رغم أن الواقعة المحورية مؤكَّدة")

    return True, (f"{len(confirmed)} واقعة مؤكَّدة، منها الواقعة المحورية "
                  f"«{central['text']}»")


def _validate_sources(confirmed: list[dict]) -> str:
    """يمنع صياغة مسودة من واقعة مؤكَّدة بلا مصدر بنص ورابط صالحين فعليًا —
    القسم «لا فشل صامت»: رسالة الامتناع تذكر المرحلة ومعرّف الواقعة ورابط
    كل مصدر مسجَّل لها والسبب، لا «فشل التحقق» رسالة عامة. يعيد نص السبب،
    أو فارغًا إن كانت كل واقعة مؤكَّدة تملك مصدرًا صالحًا واحدًا على الأقل."""
    for f in confirmed:
        usable = [s for s in f.get("sources", []) if s.get("text") and s.get("link")]
        if usable:
            continue
        bad = f.get("sources") or []
        bad_desc = "، ".join(
            f"{s.get('name', '؟')} ({s.get('link') or 'بلا رابط'})" for s in bad
        ) or "لا مصادر مسجَّلة إطلاقًا"
        return (f"مرحلة صياغة المسودة — الواقعة (index {f.get('index', '؟')}) "
               f"«{f['text']}»: لا مصدر مؤيِّد بنص ورابط صالحين للاستشهاد "
               f"({bad_desc})")
    return ""


# ──────────────────────────── فحص التطابق البعدي (القاعدة 1) ────────────────

QUOTE_RE = re.compile(r'[«"“]([^»"”]{4,})[»"”]')
_WORD_RE = re.compile(r"[\w']+", re.UNICODE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!؟?])\s+|\n+")
TRIM_MIN_CORE_FLOOR = 4  # لا نزول تحت هذا مهما ضبطه config.yaml — نواة من
# ثلاث كلمات فأقل تتكرر صدفة كثيرًا (تشخيص Issue #373، الجولة الثالثة عشرة)


def _normalized_words(text: str) -> list[str]:
    """تتابع كلمات مطبَّع يحفظ الترتيب — الترتيب جوهر فحص النسخ هنا، فلا
    نحوّله لمجموعة كما تفعل request.norm_tokens، ولا نحذف كلمات الوقف (حذفها
    يكسر التجاور فيُفرغ مفهوم «التتابع» من معناه). التطبيع (تشكيل/تطويل +
    توحيد الهمزات والتاء المربوطة) نفسه المستعمل في verify.py وrequest.py —
    الدلالة نفسها يجب أن تُطابَق بصرف النظر عن مصدرها.

    تجريد بادئة «الـ» (تشخيص Issue #373، الجولة الثالثة عشرة) بنفس شرط
    request.norm_tokens بالضبط: تطبيع شكل الكلمة نفسها (كتوحيد الهمزات)،
    لا حذف كلمة — لا يكسر التجاور. بلاه، "المحكمة" و"محكمة" تُعامَلان
    كلمتين مختلفتين فيفشل تطابق تتابع حرفي واحد بينهما بفارق أداة تعريف لا
    صلة له بكونه نسخًا أم لا."""
    text = verify._TASHKEEL_RE.sub("", text or "")
    out = []
    for raw in _WORD_RE.findall(text.lower()):
        word = raw.translate(_AR_TRANS)
        if word.startswith("ال") and len(word) > 4:
            word = word[2:]
        out.append(word)
    return out


def _contains_run(haystack: list[str], needle: list[str]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    n = len(needle)
    return any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


def _ngram_set(words: list[str], n: int) -> set[tuple[str, ...]]:
    if n <= 0 or len(words) < n:
        return set()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def _quoted_spans(text: str) -> list[str]:
    return [m.group(1).strip() for m in QUOTE_RE.finditer(text or "")]


def _ngram_counts(words: list[str], n: int) -> dict[tuple[str, ...], int]:
    if n <= 0 or len(words) < n:
        return {}
    out: dict[tuple[str, ...], int] = {}
    for i in range(len(words) - n + 1):
        key = tuple(words[i:i + n])
        out[key] = out.get(key, 0) + 1
    return out


def _count_run(haystack: list[str], needle: list[str]) -> int:
    """عدد مرات ورود `needle` كتتابع متجاور داخل `haystack` — نظير
    `_contains_run` لكنه يعدّ لا يفحص وجودًا فقط، تحتاجه إشارة (أ) المقلَّمة
    (`_trim_exempt`) على أطوال متغيّرة لا الطول الثابت `n` الذي تُحسب عنده
    `_ngram_counts` مسبقًا."""
    if not needle or len(needle) > len(haystack):
        return 0
    n = len(needle)
    return sum(1 for i in range(len(haystack) - n + 1) if haystack[i:i + n] == needle)


def _trim_exempt(window: tuple[str, ...], only_name: str,
                 source_word_lists: list[tuple[str, list[str]]],
                 extra_word_lists: list[tuple[str, list[str]]],
                 min_core: int, repeat_min_count: int
                 ) -> tuple[list[str], tuple[str, ...], tuple[str, ...], str, str, int | None] | None:
    """يحاول تقليم نافذة رُفضت بطولها الكامل من طرفيها — بكلمات وظيفية فقط
    مؤهَّلة (`request._AR_STOP`، فئة مغلقة: موصولات/أفعال ناقصة/حروف جر/
    أدوات ربط، لا قائمة جديدة) — قبل الاستسلام (تشخيص Issue #373، الجولة
    الثانية عشرة): اسم مؤسسة من سبع كلمات قد يحمل ذيلًا نحويًا («الذي كان»)
    لا صلة له بالنسخ يمنع النافذة كلها من اجتياز إشارتَي (أ)/(ب) رغم أن
    نواتها (5 كلمات فأكثر) اسم جامد لا بديل لصياغته.

    لا يجوز تقليم كلمة مضمون (غير وظيفية) من أي طرف — التقليم يتوقف عند أول
    كلمة غير مؤهَّلة من كل طرف، فلا سبيل لتقليم عشوائي يُخفي جزءًا فريدًا من
    جملة منسوخة فعليًا خلف كلمة وظيفية عابرة في المنتصف.

    يجرّب كل تقليم ممكن (يسار/يمين/كليهما) بالأطول أولًا (أقل تدخّل)، ويعيد
    أول نواة تستوفي إشارة (أ) [تكرار ≥ repeat_min_count داخل نص المصدر
    الوحيد نفسه] أو (ب) [ورود حرفي في وثيقة أخرى بهوية ناشر مختلفة]، أو
    None إن لم تنجُ أي نواة."""
    n = len(window)
    if n <= min_core:
        return None
    left_max = 0
    for w in window:
        if w not in _AR_STOP:
            break
        left_max += 1
    right_max = 0
    for w in reversed(window):
        if w not in _AR_STOP:
            break
        right_max += 1
    combos = [(l, r, n - l - r) for l in range(left_max + 1) for r in range(right_max + 1)
             if not (l == 0 and r == 0) and n - l - r >= min_core]
    combos.sort(key=lambda t: -t[2])  # الأطول (أقل تقليم) أولًا
    source_words = next((words for name, words in source_word_lists if name == only_name), [])
    for l, r, _core_len in combos:
        core = list(window[l:n - r])
        repeat_count = _count_run(source_words, core)
        if repeat_count >= repeat_min_count:
            return core, window[:l], window[n - r:], "أ", only_name, repeat_count
        other = next((name for name, words in extra_word_lists
                     if name != only_name and _contains_run(words, core)), None)
        if other:
            return core, window[:l], window[n - r:], "ب", other, None
    return None


# فئة مغلقة صغيرة من كلمات الكمية العربية الشائعة — نظير _AR_STOP الموسَّعة
# نحويًا لكن لغرض مختلف: هذه لا تُقلَّم، بل تُستعمَل كنقطة ارتساء لنواة
# رقمية/كمية (تشخيص Issue #373، تعليق الموافقة الخامس عشر، البند 2). أي
# رقم مكتوب بالأرقام (\d) يُعامَل ارتساءً أيضًا بلا حاجة لإدراجه هنا.
#
# مكتوبة بإملائها الطبيعي (بالهمزات/التاء المربوطة) للقراءة، ثم تُطبَّع
# بنفس _AR_TRANS عند التحميل — window يصل مُطبَّعًا دومًا (_normalized_words)،
# فمقارنة إملاء خام بكلمة مُطبَّعة (مثلًا "أطنان" الخام مقابل "اطنان"
# المُطبَّعة) كانت لتفشل صامتًا بلا هذا التطبيع.
QUANTITY_ANCHOR_WORDS = frozenset(
    w.translate(_AR_TRANS) for w in {
        "طن", "أطنان", "كيلوغرام", "كيلوجرام", "كجم", "غرام", "كيلومتر",
        "متر", "لتر", "برميل", "براميل", "غالون", "مليون", "مليار", "ألف",
        "آلاف", "مئة", "مئات", "عشرة", "عشرات", "بضع", "عدة", "دولار",
        "دولارات", "جنيه", "جنيهات", "يورو", "رأس", "رؤوس", "قطعة", "قطع",
    }
)
_QTY_DIGIT_RE = re.compile(r"\d")


def _is_quantity_anchor(word: str) -> bool:
    """يقبل الكلمة بإملائها الخام أو المُطبَّع (`_AR_TRANS` مُطبَّقة هنا
    أيضًا) — window يصل مُطبَّعًا دومًا فعليًا، لكن الدالة تبقى صحيحة بمعزل
    عن مصدر الاستدعاء بلا الاعتماد على أن المستدعي طبَّع الكلمة أولًا."""
    normalized = (word or "").translate(_AR_TRANS)
    return bool(_QTY_DIGIT_RE.search(normalized)) or normalized in QUANTITY_ANCHOR_WORDS


def _quantity_exempt(window: tuple[str, ...], only_name: str,
                     source_word_lists: list[tuple[str, list[str]]],
                     extra_word_lists: list[tuple[str, list[str]]],
                     min_core: int, repeat_min_count: int
                     ) -> tuple[list[str], tuple[str, ...], tuple[str, ...], str, str, int | None] | None:
    """يُجرَّب بعد فشل `_trim_exempt` (تشخيص Issue #373، تعليق الموافقة
    الخامس عشر، البند 2): «عدة أطنان من مواد نووية مخزنة» صياغة كمّية جامدة
    لا بديل لها، لكن الكلمة الملاصقة في النافذة المرفوضة قد تكون جزءًا من
    فاعل/بناء الجملة المحيطة (يختلف فعليًا بين مصدرين مستقلين) لا كلمة
    وظيفية — فيفشل `_trim_exempt` (يُقلِّم من طرفَي النافذة فقط، وبكلمات
    وظيفية فقط مؤهَّلة).

    خلافًا لـ`_trim_exempt`، هذا يبحث عن نافذة فرعية **تبدأ عند كلمة رقم/
    كمية** (`_is_quantity_anchor`) بأي طول ≥ `min_core` داخل النافذة
    المرفوضة، بصرف النظر عن موضعها (لا حصرًا من الطرفين). لا حاجة لتصنيف
    الكلمات المحيطة (فعل من إنشاء الكاتب أم لا) لتحديد ما يُستبعَد: طول
    التطابق الحرفي نفسه عبر مصدر مستقل آخر (أو تكراره داخل المصدر نفسه) هو
    الدليل الوحيد المطلوب — صياغة من إنشاء الكاتب لن تتكرر حرفيًا في مصدر
    آخر أصلًا، فإشارتا (أ)/(ب) نفسهما (لا تصنيف لغوي إضافي) هما ما يثبتان
    غياب الفعل من إنشاء الكاتب بالفعل. تفشل تلقائيًا (تعيد None فورًا) حين
    لا تحمل النافذة أي كلمة رقم/كمية إطلاقًا — لا تمسّ أي جملة سردية عادية
    بلا رقم، ولا تُخفِّف عتبة `min_core` (نفس `TRIM_MIN_CORE_FLOOR`)."""
    n = len(window)
    if not any(_is_quantity_anchor(w) for w in window):
        return None
    source_words = next((words for name, words in source_word_lists if name == only_name), [])
    spans = [(start, length)
            for start, w in enumerate(window) if _is_quantity_anchor(w)
            for length in range(n - start, min_core - 1, -1)]
    spans.sort(key=lambda t: -t[1])  # الأطول (أقل إسقاط) أولًا
    for start, length in spans:
        core = list(window[start:start + length])
        repeat_count = _count_run(source_words, core)
        if repeat_count >= repeat_min_count:
            return core, window[:start], window[start + length:], "أ", only_name, repeat_count
        other = next((name for name, words in extra_word_lists
                     if name != only_name and _contains_run(words, core)), None)
        if other:
            return core, window[:start], window[start + length:], "ب", other, None
    return None


# فئة مغلقة صغيرة من كلمات ربط التسمية/اللقب العربية الشائعة — نظير
# QUANTITY_ANCHOR_WORDS بنيويًا لكن لغرض مختلف: هذه لا تُقلَّم، بل نقطة
# ارتساء لنواة تربط بين ذِكرَي اسم للكيان نفسه (تشخيص Issue #373، تعليق
# الموافقة السادس عشر — الحالة الخامسة: «هوي كا يان معروف بالصينية باسم
# شو»). تعميم أوسع (أي موضع، بلا ارتساء) رُفض بعد اختبار فعلي: كسر فِكستر
# قائمًا («فرع الأمن السياسي في درعا الوطني الجديد» — ذيل من صفتين، لا
# يجوز تقليمه مهما تكرّرت النواة بلا الذيل، ضابط متعمَّد من الجولة الثانية
# عشرة) — أي تعميم هنا يجب أن يبقى **مرتسيًا** عند فئة مغلقة، لا حرًّا،
# فلا يمسّ ذلك الضابط (لا كلمة من هذه القائمة تظهر في ذلك الفِكستر أصلًا).
#
# مكتوبة بإملائها الطبيعي، تُطبَّع بنفس _AR_TRANS عند التحميل (window يصل
# مُطبَّعًا دومًا).
NAME_LINK_ANCHOR_WORDS = frozenset(
    w.translate(_AR_TRANS) for w in {
        "معروف", "معروفة", "المعروف", "المعروفة", "يعرف", "تعرف", "يُعرف",
        "تُعرف", "يعرَف", "يدعى", "يُدعى", "تدعى", "تُدعى", "الملقب",
        "الملقبة", "الملقّب", "الملقّبة", "ملقب", "لقبه", "لقبها", "كنيته",
        "كنيتها", "اسمه", "اسمها", "الشهير", "الشهيرة", "يشتهر", "تشتهر",
    }
)


def _is_name_link_anchor(word: str) -> bool:
    """تقبل الكلمة بإملائها الخام أو المُطبَّع، نظير `_is_quantity_anchor`."""
    return (word or "").translate(_AR_TRANS) in NAME_LINK_ANCHOR_WORDS


def _name_link_exempt(window: tuple[str, ...], only_name: str,
                      source_word_lists: list[tuple[str, list[str]]],
                      extra_word_lists: list[tuple[str, list[str]]],
                      min_core: int, repeat_min_count: int
                      ) -> tuple[list[str], tuple[str, ...], tuple[str, ...], str, str, int | None] | None:
    """يُجرَّب أخيرًا بعد فشل `_trim_exempt` وَ`_quantity_exempt` (تشخيص
    Issue #373، تعليق الموافقة السادس عشر): «هوي كا يان معروف بالصينية باسم
    شو» — اسم شخص بلغتين مربوطان بعبارة تسمية جامدة («معروف بـ... باسم») لا
    بديل لصياغتها. النواة المحتملة تقع بين عنقودَي اسم علم في **منتصف**
    النافذة، لا طرفها (فلا يلتقطها `_trim_exempt`، يقلّم من الطرفين فقط)
    ولا عند رقم (`_quantity_exempt`).

    خلافًا لتعميم أوسع (أي موضع بداية بلا قيد) جُرِّب وأُسقِط لأنه كسر
    ضابطًا متعمَّدًا قائمًا (تعليق الموافقة الثاني عشر: ذيل من كلمات مضمون
    — صفتان مثلًا — لا يجوز تقليمه مهما تكرّرت النواة بلا الذيل، احترازًا
    من رخصة تقليم حرّة قد تُنقذ جملة منسوخة فعليًا في حالة أخرى غير
    مختبَرة)، هذه الدالة تبقى **مرتسية** عند فئة مغلقة صغيرة من كلمات ربط
    التسمية (`_is_name_link_anchor`) — نظير `_quantity_exempt` حرفيًا: نواة
    تبدأ عند كلمة ربط تسمية، بأي طول ≥ min_core، بلا تصنيف لغوي لباقي
    الكلمات. التطابق الحرفي المتكرر فعليًا (داخل المصدر نفسه أو في وثيقة
    أخرى) يبقى الدليل الوحيد — لا تُفعَّل إطلاقًا حين لا تحمل النافذة كلمة
    ربط تسمية (لا خطر على جملة سردية عادية بلا تسمية بديلة)."""
    n = len(window)
    anchors = [i for i, w in enumerate(window) if _is_name_link_anchor(w)]
    if not anchors:
        return None
    source_words = next((words for name, words in source_word_lists if name == only_name), [])
    spans = [(start, length)
            for start in anchors
            for length in range(n - start, min_core - 1, -1)]
    spans.sort(key=lambda t: -t[1])  # الأطول (أقل إسقاط) أولًا
    for start, length in spans:
        core = list(window[start:start + length])
        repeat_count = _count_run(source_words, core)
        if repeat_count >= repeat_min_count:
            return core, window[:start], window[start + length:], "أ", only_name, repeat_count
        other = next((name for name, words in extra_word_lists
                     if name != only_name and _contains_run(words, core)), None)
        if other:
            return core, window[:start], window[start + length:], "ب", other, None
    return None


def _name_link_note(only_name: str, n: int, phrase: str, left_words: tuple[str, ...],
                    right_words: tuple[str, ...], core: list[str], signal: str,
                    evidence_name: str, evidence_count: int | None) -> str:
    parts = []
    if left_words:
        parts.append(f"من اليسار «{' '.join(left_words)}»")
    if right_words:
        parts.append(f"من اليمين «{' '.join(right_words)}»")
    dropped_desc = "، ".join(parts)
    core_phrase = " ".join(core)
    if signal == "أ":
        evidence_desc = f"تكررت {evidence_count} مرات داخل نص هذا المصدر نفسه"
    else:
        evidence_desc = f"وردت أيضًا في وثيقة أخرى مقروءة بهوية ناشر مختلفة ({evidence_name})"
    return (f"⚠️ تطابق لفظي مع مصدر واحد ({only_name}) على {n} كلمة متتالية — "
           f"«{phrase}» — مُعفى: نواة ربط تسمية جامدة «{core_phrase}» "
           f"({len(core)} كلمة) لا صياغة بديلة لها (أُسقط {dropped_desc}) "
           f"{evidence_desc} (إشارة {signal} — نواة ربط تسمية)")


def _quantity_note(only_name: str, n: int, phrase: str, left_words: tuple[str, ...],
                   right_words: tuple[str, ...], core: list[str], signal: str,
                   evidence_name: str, evidence_count: int | None) -> str:
    parts = []
    if left_words:
        parts.append(f"من اليسار «{' '.join(left_words)}»")
    if right_words:
        parts.append(f"من اليمين «{' '.join(right_words)}»")
    dropped_desc = "، ".join(parts)
    core_phrase = " ".join(core)
    if signal == "أ":
        evidence_desc = f"تكررت {evidence_count} مرات داخل نص هذا المصدر نفسه"
    else:
        evidence_desc = f"وردت أيضًا في وثيقة أخرى مقروءة بهوية ناشر مختلفة ({evidence_name})"
    return (f"⚠️ تطابق لفظي مع مصدر واحد ({only_name}) على {n} كلمة متتالية — "
           f"«{phrase}» — مُعفى: نواة رقم/كمية جامدة «{core_phrase}» ({len(core)} كلمة) "
           f"لا صياغة بديلة لها (أُسقط {dropped_desc}) {evidence_desc} "
           f"(إشارة {signal} — نواة كمّية)")


def _trim_note(only_name: str, n: int, phrase: str, left_words: tuple[str, ...],
               right_words: tuple[str, ...], core: list[str], signal: str,
               evidence_name: str, evidence_count: int | None) -> str:
    parts = []
    if left_words:
        parts.append(f"من اليسار «{' '.join(left_words)}»")
    if right_words:
        parts.append(f"من اليمين «{' '.join(right_words)}»")
    trimmed_desc = "، ".join(parts)
    core_phrase = " ".join(core)
    if signal == "أ":
        evidence_desc = f"تكررت {evidence_count} مرات داخل نص هذا المصدر نفسه"
    else:
        evidence_desc = f"وردت أيضًا في وثيقة أخرى مقروءة بهوية ناشر مختلفة ({evidence_name})"
    return (f"⚠️ تطابق لفظي مع مصدر واحد ({only_name}) على {n} كلمة متتالية — "
           f"«{phrase}» — مُعفى بعد تقليم كلمات وظيفية ({trimmed_desc}): النواة "
           f"«{core_phrase}» ({len(core)} كلمة) {evidence_desc} (إشارة {signal} مقلَّمة)")


def _sentence_containing(raw_text: str, window: tuple[str, ...]) -> str:
    """أول جملة **خام** (بلا تطبيع) من `raw_text` تحوي `window` كتتابع حرفي
    بعد التطبيع — تُعرض للمراجع البشري عند الرفض النهائي وحده (تشخيص
    Issue #373، تعليق الموافقة الثالث عشر، البند 3): «الحكم البشري هو
    المعيار الذي لا يخطئ هنا» — بدل عرض التتابع المقتطَع (7 كلمات فقط) الذي
    قد يبدو نسخًا أو صياغة قياسية بمعزل عن سياقه، نعرض الجملة كاملة فيحكم
    القارئ بنفسه. عرض فقط — لا تشارك في قرار الرفض/الإعفاء، وفشلها الصامت
    (نص فارغ حين لا نجد حدود جملة واضحة) لا يغيّر أي حكم."""
    if not raw_text:
        return ""
    needle = list(window)
    for sent in _SENTENCE_SPLIT_RE.split(raw_text):
        sent = sent.strip()
        if sent and _contains_run(_normalized_words(sent), needle):
            return sent
    return ""


def check_originality(draft_text: str, article_body: str, source_docs: list[dict],
                      max_shared_run_words: int, *, repeat_min_count: int = 2,
                      extra_docs: list[dict] | None = None, min_core: int = 5
                      ) -> tuple[bool, str, list[str]]:
    """غلاف رقيق حول `_check_originality_full` يُبقي التوقيع العام (3-tuple)
    كما هو تمامًا — لا تغيير سلوكي، ولا حاجة لتعديل أي مستدعٍ قائم (بما
    فيه اختبارات tests/test_pipeline.py الثمانية والعشرون التي تفكّك القيمة
    المُعادة إلى ثلاثة متغيّرات). `article.py` وحده يحتاج معلومة "التتابع
    المخالف" الإضافية (لمحاولة صياغة ثانية، تشخيص Issue #373، تعليق العطل
    الحادي والعشرون، البند 2) فيستدعي `_check_originality_full` مباشرة —
    نظير استدعائه القائم أصلًا لدوال خاصة أخرى هنا (`_image_candidates`)."""
    ok, reason, notes, _offending = _check_originality_full(
        draft_text, article_body, source_docs, max_shared_run_words,
        repeat_min_count=repeat_min_count, extra_docs=extra_docs, min_core=min_core)
    return ok, reason, notes


def _check_originality_full(draft_text: str, article_body: str, source_docs: list[dict],
                            max_shared_run_words: int, *, repeat_min_count: int = 2,
                            extra_docs: list[dict] | None = None, min_core: int = 5
                            ) -> tuple[bool, str, list[str], dict | None]:
    """يتحقق أن نص المسودة لا يحمل نسخًا حرفيًا من المقال الملصق ولا من
    مقتطفات المصادر المؤكِّدة (تعليق الموافقة على Issue #334، نقطة 3):
    القاعدة 1 تمنع نقل جملة من المقال، والمقتطفات تدخل البرومبت هنا كنصوص
    كاملة (خطر نسخ أعلى من ملخصات RSS القصيرة التي يتلقاها writer.py عادة)
    فالنسخ من مصدر مؤكِّد يُفحص بالصرامة نفسها.

    source_docs/extra_docs: [{"name": هوية الناشر الموحَّدة (لا الاسم
    الخام — على المستدعي تمرير evidence._canonical_publisher نفسها، فهذه
    الدالة لا تستورد evidence لتبقى مستقلة قابلة للاختبار بلا cfg), "text":
    ..., "link": رابط المصدر (اختياري — "link" غائب أو فارغ لا يكسر شيئًا،
    فقط لا يظهر رابط في رسالة الرفض)}]. source_docs هي المقتطفات
    المؤكِّدة/المسندة فعليًا لهذا المحتوى — عليها وحدها يسري استثناء
    "مصدرين مستقلين" الأصلي. extra_docs (اختياري) تجميع أوسع — أي وثيقة
    قُرئت خلال هذا التشغيل ولو لم تؤيِّد هذه الواقعة بعينها — تُستعمل حصرًا
    لإشارة (ب) أدناه، لا لإشارة (أ) ولا للاستثناء الأصلي.

    اقتباس بين علامتي تنصيص يُستثنى من الفحص بشرط وجوده حرفيًا (بعد
    التطبيع) في أحد مقتطفات المصادر المؤكِّدة — اقتباس منسوب مشروع. اقتباس
    غير موجود في أي مقتطف يُرفض مباشرة بوصفه نسخًا من المقال الملصق، بلا
    حاجة لفحص التتابع عليه — بلا `offending` (القيمة الرابعة أدناه): اقتباس
    مختلَق عطل مضمون لا صياغة يمكن "إصلاحها" بإعادة الترتيب.

    القيمة الرابعة المُعادة (`offending`): عند الرفض النهائي على تتابع من
    مصدر واحد أو من المقال الملصق تحديدًا (لا رفض الاقتباس)، قاموس
    {"phrase": التتابع الخام, "draft_sentence": جملة المسودة الكاملة,
    "match_kind": "source" أو "brief", "source_name"/"source_link": عند
    match_kind=="source"} — يتيح لمستدعٍ (article.py وحده، تشخيص Issue
    #373، تعليق العطل الحادي والعشرون، البند 2) محاولة صياغة ثانية واحدة
    تُمرَّر إليها الجملة المخالفة بعينها كتوجيه صريح لإعادة بنائها. الرفض
    يبقى نهائيًا **داخل هذه الدالة نفسها** بلا إعادة محاولة ضمنية — مدخلات
    فحص واحد لا تتغيّر بين نداءين متطابقين؛ التغيّر الوحيد الممكن هو مسودة
    ثانية مختلفة فعليًا من `article.py`، تُفحَص هنا من جديد بصرامة كاملة لا
    استثناء لموضع الجملة المُصلَحة وحده. `None` حين لا يوجد `offending`
    ذو معنى (نجاح الفحص، أو رفض الاقتباس).

    استثناء عابر للمصادر (تعليق التنفيذ على PR #340، البند 2): تتابع كلمات
    وارد حرفيًا في مصدرين مستقلين مؤكِّدين فأكثر (بعد توحيد هوية الناشر —
    لا تُحسب نسختا ناشر واحد بلغتين مصدرين اثنين) ليس نسخًا من أيّهما — هو
    على الأرجح صياغة الحدث نفسه كما تكرّرت في تغطيات مستقلة (تصريح رسمي
    منقول حرفيًا، رقم بصياغته القياسية...)، لا دليل نسخ عن مصدر بعينه.

    إشارتان إضافيتان (تشخيص Issue #373، الجولة العاشرة — بديل عن جعل
    النموذج شاهدًا على نفسه بتصنيف تتابعه "مصطلح رسمي"، مرفوض: الفحص كله
    وُجد لأننا لا نثق بمخرَج النموذج) تُعفيان تتابعًا ورد في مصدر واحد فقط
    من الرفض، بلا رفع عتبة max_shared_run_words:
      (أ) تكرار داخل المصدر الواحد نفسه ≥ repeat_min_count — اسم مؤسسة
          يتكرر في الخبر عنها؛ الجملة المنسوخة لا تتكرر.
      (ب) ورود في وثيقة أخرى مقروءة (extra_docs) بهوية ناشر مختلفة عن
          المصدر الوحيد — لا يكفي ورودها في نسخة أخرى للناشر نفسه (توحيد
          الهوية يمنع هذا) لأن ذلك ليس دليل انتشار مستقلًا، بل نفس الناشر
          يكرر عبارته.
    كلا الإشارتين يُسجَّلان في القيمة الثالثة المُعادة (سطر تبليغ لكل
    إعفاء، بلا إعفاء صامت) — لا يُسقطان الفحص، فقط يُعفيان الحالة المحدَّدة.

    تقليم حدّي (تشخيص Issue #373، الجولة الثانية عشرة): نافذة فشلت
    الإشارتين أعلاه بطولها الكامل قد تحمل نواة (اسم مؤسسة/كيان لا بديل
    لصياغته) يمنعها فقط ذيل أو صدر نحوي («الذي كان»، «في») من إشارة (أ)/(ب)
    — `_trim_exempt` تقلّم من الطرفين كلمات وظيفية فقط (`request._AR_STOP`،
    فئة مغلقة: موصولات/أفعال ناقصة/حروف جر/أدوات ربط — لا كلمة مضمون تُقلَّم
    مهما بلغ الرفض) حتى `min_core` كلمة، وتفحص كل نواة مرشَّحة على إشارة (أ)
    أو (ب) بالطول المقلَّم لا الطول الأصلي. لا يمسّ هذا عتبة
    max_shared_run_words نفسها — نافذة بلا نواة صالحة تُرفض كما هي دومًا.
    `min_core` مضبوط بحد أدنى صريح (`TRIM_MIN_CORE_FLOOR` = 4) لا ينزل عنه
    بصرف النظر عمّا يضبطه config.yaml — نواة من ثلاث كلمات فأقل تتكرر صدفة
    كثيرًا (تعليق الموافقة الثالث عشر على Issue #373، البند 2).

    نواة رقم/كمية (تشخيص Issue #373، تعليق الموافقة الخامس عشر، البند 2):
    نافذة فشل تقليمها الحدّي (`_trim_exempt` — يُقلِّم من الطرفين فقط بكلمات
    وظيفية) قد تحمل مع ذلك نواة كمّية جامدة («عدة أطنان من مواد نووية
    مخزنة») تمنعها فقط كلمة *مضمون* ملاصقة من فاعل/بناء جملة محيطة يختلف
    فعليًا بين مصدرين. `_quantity_exempt` تبحث عن نافذة فرعية تبدأ عند رقم/
    كمية (`_is_quantity_anchor`) بأي طول ≥ `min_core` داخل النافذة، وتفحصها
    على إشارة (أ)/(ب) نفسيهما — بلا تصنيف لغوي لـ«هل هذه فعل؟»: التطابق
    الحرفي عبر مصدر مستقل آخر هو الدليل الوحيد، فصياغة من إنشاء الكاتب لن
    تتكرر حرفيًا هناك أصلًا. لا تُفعَّل إطلاقًا حين لا تحمل النافذة أي رقم/
    كلمة كمية (لا خطر على جملة سردية عادية بلا رقم).

    نواة ربط تسمية (تشخيص Issue #373، تعليق الموافقة السادس عشر): نافذة
    فشل تقليمها الحدّي وارتساؤها الكمّي معًا قد تحمل مع ذلك نواة لا بديل
    لها تقع في **منتصف** النافذة — بين عنقودَي اسم علم، لا طرفها ولا عند
    رقم («هوي كا يان معروف بالصينية باسم شو»: الرابط «معروف بالصينية باسم»
    بين اسمَي الشخص بلغتيه). `_name_link_exempt` ترتسي عند فئة مغلقة صغيرة
    من كلمات ربط التسمية/اللقب (`NAME_LINK_ANCHOR_WORDS` — نظير
    `_quantity_exempt` حرفيًا، لا تعميم حرّ) وتفحص كل نواة ابتداءً منها على
    إشارتَي (أ)/(ب) نفسيهما بلا تصنيف لغوي إضافي (لا تصنيف "اسم علم" — فقط
    كلمة الربط نفسها من فئة مغلقة). تعميم أوسع (أي موضع بداية بلا ارتساء)
    جُرِّب وأُسقِط: كسر فِعليًا ضابطًا متعمَّدًا قائمًا (تعليق الموافقة
    الثاني عشر — ذيل من كلمات مضمون لا يجوز تقليمه مهما تكرّرت النواة بلا
    الذيل)، فبقي الحل مرتسيًا عند فئة مغلقة كسابقتها لا حرًّا. لا تُفعَّل
    إطلاقًا حين لا تحمل النافذة كلمة ربط تسمية (لا خطر على جملة سردية
    عادية بلا تسمية بديلة).

    عند الرفض النهائي (بلا أي إعفاء نجح) على تتابع من مصدر واحد أو من
    المقال الملصق، رسالة السبب تُرفَق بأول جملة خام تحوي التتابع كاملة —
    لا التتابع المقتطَع (7 كلمات) وحده — عبر `_sentence_containing`
    (تشخيص Issue #373، تعليق الموافقة الثالث عشر، البند 3): يقرر المراجع
    البشري نفسه إن كانت صياغة قياسية أم نسخًا فعليًا من سياقها الكامل، بلا
    أي تصنيف آلي إضافي يخاطر بخطأ. تعليق الموافقة الرابع عشر (البند 4)
    وسّع هذا: تُعرَض جملة المسودة نفسها أيضًا (لا جملة المصدر وحدها) —
    بلا سياق جملة المسودة، تتابع النسخ المُقتَطَع قد يبدو مطابقًا لفظيًا
    بمعزل عن كونه فعليًا جزءًا من جملة معاد صياغتها حول النواة المشتركة —
    ورابط المصدر إلى جانب اسمه حين رُفض على مصدر واحد (لا رابط للمقال
    الملصق نفسه — لا حقل رابط له أصلًا).

    لا إضعاف للتطبيع نفسه: المطابقة الحرفية بعد التطبيع كما هي، فقط قرار
    الرفض يفحص أولًا عدد المصادر المستقلة التي يظهر التتابع فيها بالضبط."""
    min_core = max(TRIM_MIN_CORE_FLOOR, int(min_core))
    source_texts = [d.get("text", "") for d in source_docs]
    source_link_map = {d["name"]: d.get("link", "") for d in source_docs}
    quotes = _quoted_spans(draft_text)
    normalized_sources = [_normalized_words(s) for s in source_texts]
    cleaned = draft_text
    for q in quotes:
        q_words = _normalized_words(q)
        if not q_words or not any(_contains_run(src_words, q_words)
                                  for src_words in normalized_sources):
            return False, (f"اقتباس بين علامتي تنصيص غير موجود حرفيًا في أي "
                           f"مقتطف مصدر مؤكِّد — يُفترض نسخه من المقال الملصق: "
                           f"«{q[:80]}»"), [], None
        cleaned = cleaned.replace(q, " ")

    notes: list[str] = []
    candidate_words = _normalized_words(cleaned)
    n = max_shared_run_words
    if n > 0 and len(candidate_words) >= n:
        article_ngrams = _ngram_set(_normalized_words(article_body), n)
        source_text_map = {d["name"]: d.get("text", "") for d in source_docs}
        source_word_lists = [(d["name"], _normalized_words(d.get("text", "")))
                             for d in source_docs]
        extra_word_lists = [(d["name"], _normalized_words(d.get("text", "")))
                            for d in (extra_docs or [])]
        source_counts = [(name, _ngram_counts(words, n)) for name, words in source_word_lists]
        extra_counts = [(name, _ngram_counts(words, n)) for name, words in extra_word_lists]
        for i in range(len(candidate_words) - n + 1):
            window = tuple(candidate_words[i:i + n])
            phrase = " ".join(window)
            hit_names = {name for name, counts in source_counts if window in counts}
            if len(hit_names) >= 2:
                continue  # وارد في مصدرين مستقلين فأكثر — مستثنى من الرفض
            if len(hit_names) == 1:
                only_name = next(iter(hit_names))
                repeat_count = next(c for name, c in source_counts
                                    if name == only_name)[window]
                if repeat_count >= repeat_min_count:
                    note = (f"⚠️ تطابق لفظي مع مصدر واحد ({only_name}) على {n} كلمة "
                           f"متتالية — «{phrase}» — مُعفى: تكرر {repeat_count} مرات "
                           f"داخل نص هذا المصدر نفسه (إشارة أ)")
                    if note not in notes:
                        notes.append(note)
                    continue
                other_hit = next((name for name, counts in extra_counts
                                  if window in counts and name != only_name), None)
                if other_hit:
                    note = (f"⚠️ تطابق لفظي مع مصدر واحد ({only_name}) على {n} كلمة "
                           f"متتالية — «{phrase}» — مُعفى: ورد أيضًا في وثيقة أخرى "
                           f"مقروءة بهوية ناشر مختلفة ({other_hit}) (إشارة ب)")
                    if note not in notes:
                        notes.append(note)
                    continue
                trimmed = _trim_exempt(window, only_name, source_word_lists,
                                       extra_word_lists, min_core, repeat_min_count)
                if trimmed:
                    core, left_words, right_words, signal, ev_name, ev_count = trimmed
                    note = _trim_note(only_name, n, phrase, left_words, right_words,
                                      core, signal, ev_name, ev_count)
                    if note not in notes:
                        notes.append(note)
                    continue
                qty = _quantity_exempt(window, only_name, source_word_lists,
                                       extra_word_lists, min_core, repeat_min_count)
                if qty:
                    core, left_words, right_words, signal, ev_name, ev_count = qty
                    note = _quantity_note(only_name, n, phrase, left_words, right_words,
                                          core, signal, ev_name, ev_count)
                    if note not in notes:
                        notes.append(note)
                    continue
                name_link = _name_link_exempt(window, only_name, source_word_lists,
                                              extra_word_lists, min_core, repeat_min_count)
                if name_link:
                    core, left_words, right_words, signal, ev_name, ev_count = name_link
                    note = _name_link_note(only_name, n, phrase, left_words, right_words,
                                           core, signal, ev_name, ev_count)
                    if note not in notes:
                        notes.append(note)
                    continue
                draft_sentence = _sentence_containing(draft_text, window)
                draft_part = (f" — الجملة الكاملة في المسودة: «{draft_sentence}»"
                             if draft_sentence else "")
                sentence = _sentence_containing(source_text_map.get(only_name, ""), window)
                sentence_part = (f" — الجملة المقابلة في المصدر: «{sentence}»"
                                 if sentence else "")
                link = source_link_map.get(only_name, "")
                source_desc = f"{only_name} ({link})" if link else only_name
                offending = {"phrase": phrase, "draft_sentence": draft_sentence,
                            "match_kind": "source", "source_name": only_name,
                            "source_link": link}
                return False, (f"تطابق لفظي مع مقتطف مصدر مؤكِّد ({source_desc}): "
                               f"{n} كلمة متتالية مشتركة — «{phrase}»"
                               f"{draft_part}{sentence_part}"), notes, offending
            if window in article_ngrams:
                draft_sentence = _sentence_containing(draft_text, window)
                draft_part = (f" — الجملة الكاملة في المسودة: «{draft_sentence}»"
                             if draft_sentence else "")
                sentence = _sentence_containing(article_body, window)
                sentence_part = (f" — الجملة المقابلة في المقال الملصق: «{sentence}»"
                                 if sentence else "")
                offending = {"phrase": phrase, "draft_sentence": draft_sentence,
                            "match_kind": "brief"}
                return False, (f"تطابق لفظي مع المقال الملصق: {n} كلمة متتالية "
                               f"مشتركة — «{phrase}»{draft_part}{sentence_part}"), notes, offending
    return True, "", notes, None


# ──────────────────────────── الصياغة من الوقائع ────────────────────────────

# لا نستدعي writer.write_arabic هنا رغم استيراد writer.py كاملة: توقيعها
# يتمحور حول Article (عنوان/رابط/ناشر المقال المصدر يدخل برومبتها مباشرة)
# — وهذا بالضبط ما تمنعه القاعدة الملزمة الأولى بنيويًا هنا. الفرق إذن في
# *بناء البرومبت* لا في آلية نداء الشبكة نفسها؛ نداء الشبكة (الطلب، إعادة
# المحاولة، تصنيف العطل، استخراج JSON) مستخرج فعليًا إلى writer._call_model
# ويُستعمل من المسارين معًا (لا نسختين تتباعدان — تعليق ما قبل الدمج على
# Issue #334، نقطة 2)، وتنظيف الحقول النهائية إلى writer._post_from_data
# للسبب نفسه. النظام المستعمل writer.SYSTEM_PROMPT كما هو (القاعدة 5) —
# لا نسخة معدّلة ولا غلاف يعيد صياغة قواعد التحرير.
DRAFT_USER_TEMPLATE = """وقائع مؤكَّدة بمصدرين مستقلين فأكثر — لا مصدر واحد ولا
أي حالة أضعف. ابنِ منها منشورًا مستقلًا بلا أي رجوع لمصدر آخر غير المذكور
أدناه:

{facts_block}

نصوص المصادر المستقلة التي أيّدت هذه الوقائع تحديدًا:

{source_texts}
املأ حقول أداة publish_post من هذه الوقائع والنصوص وحدها — لا معرفة سابقة
ولا مصدر ثالث. القواعد التحريرية كما هي دومًا:

• image_headline — عنوان مكثّف يُكتب على الصورة، بحد أقصى {max_chars} حرفًا، بلا نقطة
• post_title — عنوان المنشور: جملة واحدة جاذبة ودقيقة
• post_body — متن المنشور، {post_length}
• hashtags — {hashtags_count} هاشتاقات عربية، بلا رمز # وبـ _ بدل المسافة
• category — التصنيف الأنسب
• analysis — فقرة «خلف الخبر»: نص واحد متصل بحد أقصى {analysis_max_words} كلمة
  إن حملت نصوص المصادر تحليلًا فعليًا يتجاوز الوقائع أعلاه، وإلا اتركه فارغًا.

نبرة الكتابة المطلوبة: {tone}"""


def _canonical_docs(items: list[dict], cfg) -> list[dict]:
    """[{"name": هوية ناشر موحَّدة, "text": ..., "link": ...}] من قائمة
    مصادر خام (حقل "sources" لأي واقعة) — evidence._canonical_publisher
    تمنع نسختي ناشر واحد بلغتين (مثال حقيقي: "الجزيرة نت"/"Al Jazeera") من
    العدّ كمصدرين مستقلين في check_originality (تشخيص Issue #373، الجولة
    العاشرة، بند التوحيد في إشارة ب). "link" (تعليق الموافقة الرابع عشر،
    البند 4) يصل رسالة الرفض النهائي فيرى المراجع البشري مصدر التطابق
    ورابطه معًا، لا اسمًا مجردًا."""
    out = []
    for it in items:
        text = it.get("text")
        if not text:
            continue
        out.append({"name": evidence._canonical_publisher(it.get("name", ""), cfg),
                    "text": text, "link": it.get("link", "")})
    return out


def _source_docs(confirmed: list[dict]) -> list[dict]:
    """مقتطفات المصادر المؤيِّدة للوقائع المؤكَّدة، بلا تكرار اسم واحد — هذا
    ما يصل البرومبت، لا نص المقال الملصق ولا ملخصات RSS القصيرة."""
    seen: set[str] = set()
    out = []
    for f in confirmed:
        for s in f.get("sources", []):
            if s["name"] in seen or not s.get("text"):
                continue
            seen.add(s["name"])
            out.append({"name": s["name"], "text": s["text"]})
    return out


def _draft_from_facts(confirmed: list[dict], cfg,
                      retries: int = 3) -> tuple[dict | None, str]:
    """يستدعي النموذج للصياغة من الوقائع المؤكَّدة ومقتطفات مصادرها حصرًا.
    الضمان البنيوي للقاعدة 1: توقيعها لا يقبل نص مقال أو عنوانه أو زاويته
    في أي معامل — لا مدخل هنا غير `confirmed` (نصوص وقائع + مقتطفات مصادر
    مؤكِّدة فقط) و`cfg`."""
    w = cfg.get("writer", {})
    docs = _source_docs(confirmed)
    facts_block = "\n".join(f"- {f['text']}" for f in confirmed)
    max_words = int(w.get("analysis_max_words", 120))
    prompt = DRAFT_USER_TEMPLATE.format(
        facts_block=facts_block,
        source_texts=extract.format_for_prompt(docs),
        max_chars=cfg.path("image.headline_max_chars", 95),
        post_length=w.get("post_length", "60 إلى 90 كلمة"),
        hashtags_count=w.get("hashtags_count", 4),
        analysis_max_words=max_words,
        tone=w.get("tone", "خبري رصين، عربي فصيح مبسّط، بلا مبالغة أو إثارة"),
    )

    try:
        data = writer._call_model(prompt, cfg, retries)
    except writer.WriteFailure as exc:
        log.warning("فشل تقني في صياغة مسودة التحقق (%s): %s", exc.reason, exc.detail)
        return None, f"مرحلة صياغة المسودة — فشل تقني ({exc.reason}): {exc.detail}"

    if not data.get("newsworthy", True):
        # امتناع مشروع لا التفاف عليه ولا إعادة صياغة (تعليق الموافقة على
        # Issue #334): السبب يُنقل حرفيًا كما أعاده النموذج، لا يُعمَّم
        reject_reason = str(data.get("reject_reason") or "").strip() or "بلا سبب محدد من النموذج"
        return None, f"مرحلة صياغة المسودة — رفض تحريري (newsworthy=false): {reject_reason}"

    written = writer._post_from_data(data, max_words, len(docs) >= 2)
    return written, ""


# ──────────────────────────── بناء المسودة والصورة ──────────────────────────


def _image_candidates(confirmed: list[dict]) -> list[tuple[str, str, str]]:
    """(رابط الصورة، اسم المصدر، رابط المصدر) لكل صورة مرشحة من مصادر
    مؤيِّدة مؤكَّدة فقط — لا صورة المقال الملصق (لا رابط له أصلًا: verify.py
    يستقبل نصًا خامًا بلا رابط مقال) ولا أي مصدر غير مؤكَّد."""
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for f in confirmed:
        for s in f.get("sources", []):
            for url in s.get("image_candidates") or []:
                if url in seen:
                    continue
                seen.add(url)
                out.append((url, s["name"], s.get("link", "")))
    return out


def _synthetic_article(confirmed: list[dict], primary_link: str,
                       publishers: list[str]) -> Article:
    """لا نص مقال ولا عنوانه الفعلي في أي حقل هنا (القاعدة 2): العنوان نص
    الواقعة المحورية المؤكَّدة، وهو أصلًا إعادة صياغة عن المصادر لا نقل
    حرفي عن المقال (EXTRACT_SYSTEM يمنع ذلك). الرابط رابط مصدر مؤكِّد لا
    رابط المقال الملصق — لا رابط له أصلًا."""
    central = confirmed[0]
    return Article(
        title=central["text"],
        link=primary_link,
        summary="؛ ".join(f["text"] for f in confirmed[1:]),
        source_name=publishers[0] if publishers else "",
        region="global",
        weight=1.0,
        published=datetime.now(timezone.utc),
        publisher=publishers[0] if publishers else "",
        cluster_sources=publishers,
    )


def attempt(result: dict, article_body: str, issue_number: int, cfg) -> dict:
    """يحاول بناء مسودة من المؤكَّد وحده بعد تقرير المرحلة الأولى. يعيد
    قاموس outcome بحقل `produced` ورسالة `reason` محددة دومًا (نجاحًا أو
    امتناعًا) — لا فشل صامت، ولا رجوع لمحتوى غير مؤكَّد كخطة بديلة."""
    facts = result.get("facts") or []
    central = _central_fact(facts) if facts else None
    outcome: dict = {
        "produced": False, "reason": "",
        "central_text": central["text"] if central else "",
        "central_index": central.get("index", 0) if central else 0,
        "confirmed_count": 0, "draft_id": None,
        "image_source_name": None, "image_source_link": None,
        "originality_notes": [],
    }

    write_access_error = _write_access_reason()
    if write_access_error:
        outcome["reason"] = write_access_error
        return outcome

    ok, reason = sufficiency(facts, cfg)
    if not ok:
        outcome["reason"] = reason
        return outcome

    confirmed = [f for f in facts if f["status"] == verify.STATUS_CONFIRMED]
    # الواقعة المحورية (الحدث نفسه لا مُحدِّد إسناد مفصول عنه) يجب أن تتصدر
    # confirmed: _synthetic_article وimage/central_fact_text أدناه يعتمدان
    # confirmed[0] كعنوان/استعلام صورة الحدث — موضعها الخام في facts قد لا
    # يكون صفرًا بعد فصل المُحدِّدات (Issue #339)، فبلا هذا الترتيب يعود
    # نفس العطل من زاوية أخرى: عنوان المسودة يصير نص مُحدِّد لا نص الحدث
    if central is not None and any(f is central for f in confirmed):
        confirmed = [central] + [f for f in confirmed if f is not central]
    outcome["confirmed_count"] = len(confirmed)

    source_error = _validate_sources(confirmed)
    if source_error:
        outcome["reason"] = source_error
        return outcome

    vd_cfg = cfg.get("verify_draft", {}) or {}
    max_shared_run_words = int(vd_cfg.get("max_shared_run_words", 7))
    repeat_min_count = int(vd_cfg.get("repeat_within_source_min_count", 2))
    trim_min_core = int(vd_cfg.get("trim_min_core", 5))

    written, write_reason = _draft_from_facts(confirmed, cfg)
    if written is None:
        outcome["reason"] = write_reason
        return outcome

    source_docs = _canonical_docs(
        [s for f in confirmed for s in f.get("sources", [])], cfg)
    # المجمع الأوسع لإشارة (ب): مصادر كل الوقائع التي بحث عنها verify.py في
    # المرحلة الأولى (result["facts"]) — لا confirmed وحدها — فوثيقة أيّدت
    # واقعة أخرى لم تبلغ عتبة "مؤكَّدة" (مصدر واحد فقط، أو مُخالَف...) تبقى
    # دليلًا صالحًا على أن التتابع صياغة قياسية متكررة عبر التغطية، لا نسخ
    extra_docs = _canonical_docs(
        [s for f in facts for s in f.get("sources", [])], cfg)
    draft_text = "\n".join(filter(None, [
        written["image_headline"], written["post_title"],
        written["post_body"], written.get("analysis", ""),
    ]))
    ok_orig, orig_reason, originality_notes = check_originality(
        draft_text, article_body, source_docs, max_shared_run_words,
        repeat_min_count=repeat_min_count, extra_docs=extra_docs, min_core=trim_min_core)
    outcome["originality_notes"] = originality_notes
    if not ok_orig:
        outcome["reason"] = f"مرحلة صياغة المسودة — امتناع: {orig_reason}"
        return outcome

    # عناوين مقترحة (Issue #756) -- بعد نجاح الصياغة وفحص النسخ معًا (لا
    # قيمة لعناوين مسودة كانت ستُرفض أصلًا)، بنفس آلية مسار التحليل: فشل
    # النداء لا يُسقِط مسودة صالحة فعليًا -- headlines فارغة بلا مربعات.
    headlines, hl_error = headlines_mod.headlines_for_post(
        written["post_title"], written["post_body"], cfg)
    if hl_error:
        log.warning("فشلت اقتراحات العناوين لمسودة التحقق (Issue #%s): %s",
                    issue_number, hl_error)
        headlines = []

    publishers: list[str] = []
    for f in confirmed:
        for s in f.get("sources", []):
            if s["name"] not in publishers:
                publishers.append(s["name"])
    primary_link = next(
        (s.get("link") for f in confirmed for s in f.get("sources", [])
         if s.get("link")), "")

    art = _synthetic_article(confirmed, primary_link, publishers)
    draft_id = hashlib.sha1(
        f"verify:{issue_number}:{confirmed[0]['text']}".encode("utf-8")
    ).hexdigest()[:12]

    image_ranked = _image_candidates(confirmed)
    image_urls = [u for u, _, _ in image_ranked]
    central_fact_text = confirmed[0]["text"]

    image_name = f"{datetime.now(timezone.utc):%Y-%m-%d}/{draft_id}.jpg"
    image_rel = f"drafts/{image_name}"
    shot: dict = {}
    try:
        imaging.build_post_image(
            headline=written["image_headline"] or written["post_title"],
            category=written["category"],
            urgent=written["urgent"],
            image_urls=image_urls,
            publisher=publishers,
            bucket="serious",
            origin=DRAFT_ORIGIN,
            # كسول: لا يُستدعى إلا إن فشلت كل صور المصادر المؤكِّدة فعليًا —
            # موضوع البحث الوقائع المؤكَّدة لا زاوية المقال أو عنوانه
            fallback_provider=lambda: find_images(central_fact_text, cfg),
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
        "verify_issue": issue_number,
        "score": 0.0,
        "bucket": "serious",
        "analysed_sources": [d["name"] for d in _source_docs(confirmed)],
        "trend_score": 0.0,
        "velocity": 0.0,
        "age_hours": 0.0,
        "is_followup": False,
        "state_media": False,
        "has_photo": bool(shot.get("used_original")),
        "image_info": {
            "used_original": bool(shot.get("used_original")),
            "illustrative": bool(shot.get("illustrative")),
            "composite": bool(shot.get("composite")),
            "chosen_url": shot.get("chosen_url"),
            "candidates_tried": shot.get("candidates_tried"),
            "manual": False,
        },
        "source": {
            "title": central_fact_text,
            "link": primary_link,
            "publisher": publishers[0] if publishers else "",
            "publishers": publishers,
            "region": "global",
            "image_url": image_urls[0] if image_urls else None,
            "image_candidates": image_urls,
        },
        "arabic": written,
        "caption": writer.build_caption(written, art, cfg),
        "headlines": headlines,
        "headline_selected": 0,
        "image": image_rel,
        "reel": None,
        "reel_spec": {
            "headline": written["image_headline"] or written["post_title"],
            "category": written["category"],
            "urgent": written["urgent"],
            "image_candidates": image_urls,
        },
    }
    store.save_draft(draft)

    if shot.get("used_original") and image_ranked:
        outcome["image_source_name"] = image_ranked[0][1]
        outcome["image_source_link"] = image_ranked[0][2]

    outcome.update({
        "produced": True,
        "reason": f"صيغت مسودة من {len(confirmed)} واقعة مؤكَّدة",
        "draft_id": draft_id,
    })
    return outcome


def build_report_section(outcome: dict) -> str:
    lines = ["#### 📝 مسودة من المؤكَّد", ""]
    if outcome["produced"]:
        lines.append(f"✅ {outcome['reason']} (المعرّف `{outcome['draft_id']}`) — "
                     "ستظهر في أقرب Issue مراجعة يفتحه البوت بعد رفع المسودة.")
        if outcome.get("image_source_link"):
            name = outcome.get("image_source_name") or "مصدر مؤكِّد"
            lines.append(f"🖼️ مصدر الصورة: [{name}]({outcome['image_source_link']})")
    else:
        lines.append(f"❌ لم تُصَغ مسودة — {outcome['reason']}")
    if outcome.get("originality_notes"):
        lines += ["", "**تتابعات أُعفيت من فحص النسخ اللفظي:**"]
        lines += [f"- {note}" for note in outcome["originality_notes"]]
    if outcome.get("central_text"):
        lines += ["", f"<sub>الواقعة المحورية (index {outcome['central_index']}): "
                      f"«{outcome['central_text']}»</sub>"]
    return "\n".join(lines)


# ──────────────────────────── ربط المسودة بتعليق Issue التحقق ───────────────


def main() -> int:
    """يربط مسودة أُنتجت أثناء التحقق بـ Issue مراجعتها بعد فتحه. خطوة
    منفصلة عن `python -m src.verify` لأن فتح Issue المراجعة يجب أن يقع بعد
    رفع الصور إلى المستودع (القيد الموثَّق في CLAUDE.md)، وهذا يقع في خطوة
    لاحقة من verify.yml بعد أن تنتهي src.verify من عملها.

        python -m src.verify_draft --link --issue 132 --draft-id abcdef123456
    """
    parser = argparse.ArgumentParser(description="ربط مسودة تحقق بـ Issue مراجعتها")
    parser.add_argument("--link", action="store_true", required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--draft-id", required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")

    loaded = store.load_draft(args.draft_id)
    if not loaded:
        log.error("تعذّر العثور على مسودة %s بعد الرفع — لا رابط سيُضاف "
                 "لتعليق Issue #%d", args.draft_id, args.issue)
        review.comment(args.issue,
                       f"⚠️ تعذّر العثور على مسودة `{args.draft_id}` بعد رفعها "
                       "للمستودع — راجع سجلات Actions.")
        return 1

    _, draft = loaded
    review_issue = draft.get("review_issue")
    if not review_issue:
        log.error("مسودة %s محفوظة بلا review_issue بعد open_review.main()",
                 args.draft_id)
        return 1

    review.comment(args.issue, f"➡️ راجع المسودة في Issue #{review_issue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
