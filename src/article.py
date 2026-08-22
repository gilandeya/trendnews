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
from .request import _AR_MARKS, _AR_STOP, _AR_TRANS, _WORD_RE, STOPWORDS, has_arabic, norm_tokens
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
# "تقرير منقول" تصنيف رابع (تشخيص Issue #373، الجولة السادسة عشرة): نقل موجز
# لتقرير/تحليل نشرته منصة أو صحيفة واحدة بعينها — لا حدث وقع في العالم يحتاج
# رصدًا من زوايا مستقلة متعددة، بل نشرٌ وقع، ودليله الوحيد الممكن بطبيعة
# الحال هو المنشور نفسه أو ناقل يسمّي ناشره. الشاهد المُبلَّغ: تقرير تحليلي
# لمنصة يونانية متخصصة استُخرج "واقعة" عادية فسقط بعتبة مصدرين لن تتحقق أبدًا
# (تقرير منصة واحدة لن يعيد نشره مصدر مستقل ثانٍ بحكم طبيعته). عتبته المستقلة
# article.report_min_confirm=1 بشرط هوية مزدوج بنيوي — انظر
# _report_identity_kind — لا حكم نموذج، يمنع الالتفاف. عنصر بلا publisher
# محدَّد يعود إلى "واقعة" (normalize_statement).
# حدّ إضافي (تشخيص Issue #373، الجولة السابعة عشرة): "قنوات تيليغرام
# إسرائيلية" صُنِّفت publisher فمرّت بعتبة 1 — هذا التصنيف صُمِّم لكيان
# إعلامي مسمّى واحد (منصة/صحيفة/وكالة بعينها)، لا لوصف فئة جماعية مجهولة
# (قنوات، حسابات، ناشطون، مصادر مطلعة، وسائل إعلام). الضابط بنيوي لا قائمة
# أسماء ناشرين: publisher الذي يبدأ بصيغة جمع (_is_generic_source_publisher)
# يعني بالضرورة أكثر من كيان واحد — فلا يمكن أن يكون "اسمًا مفردًا محدَّدًا"
# مهما كان الوصف اللاحق ("تيليغرام"، "إسرائيلية"، "مطلعة"...)، فيُنزَل إلى
# "واقعة" بعتبتها الكاملة بالمثل تمامًا كعنصر بلا publisher إطلاقًا.
WRITEUP_KINDS = ["واقعة", "رأي", "تصريح", "تقرير منقول"]

# صنف نحوي مغلق صغير (نظير _AR_STOP/QUANTITY_ANCHOR_WORDS بنيويًا: فئة
# قواعدية محدودة الحجم، لا قائمة أسماء ناشرين مفتوحة النمو) — رؤوس أسماء
# جمعٍ شائعة تصف مصدرًا جماعيًا/مجهولًا لا كيانًا واحدًا بعينه. الرفض على
# الجمع فقط (لا الرأس المفرد المكافئ: "قناة الجزيرة" تمرّ لأن "قناة" مفرد
# ملتصق باسم علم، بينما "قنوات تيليغرام" جمع بلا أي اسم علم يخصّه). الصيغ
# السالمة (ون/ين/ات) وبعض جموع التكسير الشائعة في سياق التغطية الإخبارية
# لمصادر مجهولة كلاهما مُدرَج صراحة — لا اعتماد على نمط صرفي عام قد يخطئ
# أعلامًا حقيقية تنتهي بنفس اللاحقة (كـ"الإمارات" في اسم صحيفة).
# مُطبَّعة بنفس ترجمة _AR_TRANS (الهمزات/التاء المربوطة) عند تعريفها — لا
# عند الفحص فقط — كي تطابق تطبيع _publisher_head_word لنفسه (بلا هذا، كلمة
# كـ"وسائل"/"أطراف" تصل الفحص مُطبَّعة بعد ترجمة الهمزات فلا تطابق نصّها
# الأصلي في المجموعة).
GENERIC_SOURCE_PLURAL_HEADS = {w.translate(_AR_TRANS) for w in {
    "قنوات", "حسابات", "صفحات", "مصادر", "وسائل", "جهات", "أطراف",
    "ناشطون", "ناشطين", "أشخاص", "مواقع", "منصات", "مجموعات",
    "مستخدمون", "مستخدمين", "متابعون", "متابعين",
}}

_PUBLISHER_WORD_RE = re.compile(r"[\w']+", re.UNICODE)


def _publisher_head_word(publisher: str) -> str:
    """أول كلمة في publisher بعد تطبيع الهمزات وحذف أل التعريف — نفس تطبيع
    request.norm_tokens حرفيًا، لكن مُبقيًا على الترتيب (norm_tokens تعيد
    مجموعة بلا ترتيب، لا تصلح لاستخراج "أول" كلمة)."""
    text = _AR_MARKS.sub("", publisher or "")
    words = _PUBLISHER_WORD_RE.findall(text.translate(_AR_TRANS).lower())
    if not words:
        return ""
    head = words[0]
    if head.startswith("ال") and len(head) > 4:
        head = head[2:]
    return head


def _is_generic_source_publisher(publisher: str) -> bool:
    """صحيح إن كان أول اسم في publisher صيغة جمع تصف مصدرًا جماعيًا/مجهولًا
    — لا يصلح ناشرًا لـ"تقرير منقول" بحكم بنيته النحوية وحدها، بصرف النظر
    عمّا يليه من وصف. مفرد + اسم علم ("قناة الجزيرة") يمرّ."""
    return _publisher_head_word(publisher) in GENERIC_SOURCE_PLURAL_HEADS


def _fact_mandatory_query_prefix(f: dict) -> str:
    """اسم المتحدث (تصريح) أو الناشر (تقرير منقول) — يجب أن يدخل استعلام
    البحث عن هذا العنصر إلزامًا، لا مجرد كيان بين كيانات أخرى (طلب
    المراجعة، تشخيص Issue #373، تعليق العطل الثاني والعشرون، البند 1):
    entities لا تتضمّن بالضرورة اسم المتحدث/الناشر أصلًا (يُستخرَج في حقل
    speaker/publisher منفصل تمامًا) — استعلام واقعي فقد "Selçuk Bayraktar"
    (اسم العلم الذي تُفهرس به التغطية فعليًا) لهذا السبب بعينه ورجع صفر
    نتائج. يُستهلَك في مقدمة نص الاستعلام (المستدعي) كي يُختار قبل أي كيان
    آخر — الخبر يُفهرس باسم قائله/ناشره قبل أي شيء آخر."""
    if f.get("kind") == "تصريح":
        return (f.get("speaker") or "").strip()
    if f.get("kind") == "تقرير منقول":
        return (f.get("publisher") or "").strip()
    return ""

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
    فارغة عند الفشل، بنفس زيف [] القائم، وcall_error لسبب الفشل التقني.
    mentioned (طلب المراجعة، تشخيص Issue #373، حالة بايراكتار الرابعة):
    أسماء المصادر التي ناقشت الموضوع بلا مطابقة مضمون — تمييز "لم يُذكر
    إطلاقًا" عن "ذُكر ولم يطابق" في رسالة السقوط. [] افتراضيًا (فشل تقني،
    أو نداء قديم في اختبار لا يضبطها)."""
    call_error: str | None = None
    mentioned: list[str] = []


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
   - "تقرير منقول": الموجز ينقل مضمون تقرير أو تحليل أو دراسة نشرتها منصة
     أو صحيفة أو جهة إعلامية واحدة بعينها — لا حدثًا وقع في العالم يمكن أن
     يرصده أكثر من طرف مستقل، بل نشرًا وقع من طرف واحد بعينه. مثال: "نشر
     موقع كذا تقريرًا يفيد بأن..." أو "بحسب تحليل نشرته صحيفة كذا...".
     لهذا العنصر إلزامًا publisher (اسم المنصة/الصحيفة كما ورد في الموجز
     حرفيًا — لا اسمًا مخمَّنًا أو معرّبًا من عندك إن لم يذكره الموجز
     صراحة). publisher يجب أن يكون كيانًا إعلاميًا مسمّى واحدًا بعينه —
     اسم منصة أو صحيفة أو وكالة محدَّدة. "قنوات تيليغرام إسرائيلية"،
     "ناشطون"، "حسابات"، "مصادر مطلعة"، "وسائل إعلام" وصف فئة جماعية
     مجهولة لا ناشرًا واحدًا — لا تضعها في publisher؛ العنصر عندها "واقعة"
     عادية لا "تقرير منقول". فرّق بينه وبين "واقعة": إن كان الموجز ينقل
     حدثًا وقع فعليًا في العالم (لا مجرد نشر) وإن استشهد بمصدر واحد
     لذكره، فهو "واقعة" عادية لا "تقرير منقول" — هذا التصنيف خاص
     بادّعاءات مصدرها هو فعل النشر ذاته لا الحدث الذي يصفه المنشور.
   جملة سردية انتقالية عامة — بلا حدث أو رقم أو تصريح محدَّد، وبلا تقويم أو
   موقف أيضًا — لا تُدرَج ضمن statements إطلاقًا: لا "واقعة" (لا تدّعي وقوع
   شيء محدَّد) ولا "رأي" (ليست تقويمًا ولا موقفًا) ولا "تصريح" (لا تنقل
   تصريحًا بعينه). مثال: "مرّت الأيام وتغيرت الأحوال ومضى من مضى وبقي من
   بقي" — سرد عابر بلا مضمون قابل للتحقق، يُستبعد كليًا لا يُصنَّف بأي
   تصنيف.

   جملة وصفية بحتة عن كيان مذكور — تصف صفة ثابتة له (مساحة، عدد موظفين أو
   أفراد، تاريخ تأسيس أو بناء، طراز، اسم أو موقع قسم داخلي) بلا أي فعل
   حدوثي في أي جزء منها — لا تُدرَج ضمن statements إطلاقًا أيضًا، بنفس منطق
   الجملة السردية الانتقالية أعلاه: لا "واقعة" (لا حدث تدّعي وقوعه) ولا أي
   تصنيف آخر، ولا تُفصَل إلى أجزاء (انظر شرط الفصل أدناه). مثال: "القلعة
   طراز قوطي بُنيت عام 1827 ومساحتها 16 ألف قدم مربع" جملة وصفية بحتة بلا
   أي حدث — تُستبعد كليًا، لا تُستخرج كعنصر واحد ولا تُفصل لأجزاء.
   **مهم — لا تُفرط في هذا الاستبعاد:** يطال فقط جملة مستقلة وصفية بالكامل
   بلا أي حدث فيها إطلاقًا. لا يعني حذف تفصيلة وصفية واردة **داخل** جملة
   تحمل حدثًا (فعلًا) — تلك التفصيلة تبقى جزءًا من نص تلك الواقعة الحدثية
   نفسها كما وردت، لا تُنزَع منها ولا تُستبعد. مثال: "استحوذ زوكربيرغ على
   القلعة التي تبلغ مساحتها 440 فدانًا" واقعة واحدة كاملة (حدث الاستحواذ) —
   مساحة 440 فدانًا تبقى جزءًا من نص هذه الواقعة نفسها، فهي لم ترد في جملة
   منفصلة وصفية بحتة.

   جملة واحدة قد تحمل أكثر من ادّعاء "واقعة" مستقل — افصلها إلى عدة عناصر
   "واقعة"، عنصر لكل ادّعاء، حين يصدق **الشرطان معًا**:
   (1) لو أمكن تخيّل مصدر مستقل يؤكد جزءًا منها ويسكت عن جزء آخر بلا أي
   تناقض منطقي، فهما ادّعاءان مستقلان لا واحد؛
   (2) وكل جزء ناتج عن الفصل يصف **حدثًا** — فعلًا وقع أو يقع أو سيقع، أو
   مصدر فعل يدلّ على حدوث (فعل حدوثي صريح) — لا وصفًا ثابتًا لكيان مذكور في
   الجملة (مساحة، عدد موظفين أو أفراد، تاريخ تأسيس أو بناء كوصف، طراز
   معماري، اسم أو موقع قسم داخلي). إن فشل أي جزء الشرط الثاني، لا تُفصل
   الجملة كلها — أبقها عنصرًا واحدًا غير مفصول، أو استبعدها كليًا إن كانت
   الجملة بأكملها وصفية بحتة بلا أي حدث (القاعدة أعلاه).
   مثال (الشرطان معًا صادقان، يُفصل): "قُصف المطار بالتزامن مع زيارة وفد
   عسكري تركي للموقع للعمل على إعادة تأهيله" ثلاثة ادّعاءات، كل جزء منها
   حدث (قُصف، زار، العمل على التأهيل) — مصدر قد يؤكد القصف وحده بلا أي ذكر
   للوفد، فهما مستقلان.
   مثال (الشرط الثاني يفشل، لا يُفصل — بل يُستبعد كليًا لأنه وصفي بحت):
   "القلعة طراز قوطي بُنيت عام 1827 ومساحتها 16 ألف قدم مربع" — لا فعل
   حدوثي في أي جزء (طراز، بناء كتاريخ وصفي، مساحة كقياس)، كلها أوصاف ثابتة
   لكيان واحد لا أحداث.
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

   لكل عنصر أيضًا entities: 2-5 كيانات مميِّزة منه كما وردت في الموجز
   حرفيًا بلا أي إعادة صياغة — استعلام البحث سيُبنى منها وحدها. اختَرها
   بأولوية ثابتة صارمة، لا بحرية: **أسماء الأعلام (أشخاص، جهات، أماكن)
   ثم الأرقام ثم التواريخ أولًا دومًا** — هذه وحدها ما يُميّز الحدث عن
   غيره في نتائج بحث. لا تختر كلمة موضوعية عامة (اسم القطاع أو الموضوع
   العام، لا الحدث بعينه) ما دام في الجملة اسم علم أو رقم أو تاريخ يمكن
   اختياره بدلًا منها — فمثلًا في جملة عن تعطّل خط أنابيب نفط تربط دولتين،
   "النفط" و"شريان حياة" كلمتان موضوعيتان عامتان لا كيانان مميِّزان (لا
   تحدّدان هذا الحدث بعينه عن أي حدث آخر يخص النفط أو الشرايين)، بينما
   اسما الدولتين والتاريخ إن وردا هما الكيانات الصحيحة.
   القاعدة نفسها بصرف النظر عن أبجدية الموجز أو لغته — لا تفترض عربية: في
   جملة تركية عن تصريح مسؤول دفاع («Baykar'ın SİHA üretiminde yüzde
   90'ını yerlileştirdik»)، الكيانات الصحيحة «Baykar» و«90» و«Türkiye»
   بحروفها الأصلية كما وردت — لا كلمة موضوعية عامة مثل «stratejimizi»
   (استراتيجيتنا) رغم أنها الأقرب معنًى لموضوع الموجز؛ اسم علم أو رقم بأي
   أبجدية دومًا أولى من كلمة موضوعية عامة، عربية كانت الجملة أم لا.
   اختيار كيانات
   مختلفة لنفس الجملة بين استخراجين يبني استعلام بحث مختلفًا تمامًا فيقلب
   نتيجة التشغيلة كلها — الثبات هنا يقلّل هذا الأثر لا يُلغيه (لا سبيل
   لضبطه للحتمية الكاملة، انظر ملاحظة temperature في CLAUDE.md).
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
                        # للعنصر "تقرير منقول" فقط، لكن إلزامي *دلاليًا* له
                        # (normalize_statement يُنزِله إلى "واقعة" بلا publisher
                        # — تشخيص Issue #373، الجولة السادسة عشرة): اسم
                        # المنصة/الصحيفة الناشرة كما ورد في الموجز حرفيًا
                        "publisher": {"type": "string"},
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
    publisher = ""
    if isinstance(item, dict):
        raw_speaker = item.get("speaker")
        if isinstance(raw_speaker, str) and raw_speaker.strip():
            speaker = raw_speaker.strip()
        merged_excerpts = _as_entities(item.get("merged_excerpts"))
        raw_split_from = item.get("split_from")
        if isinstance(raw_split_from, str) and raw_split_from.strip():
            split_from = raw_split_from.strip()
        raw_publisher = item.get("publisher")
        if isinstance(raw_publisher, str) and raw_publisher.strip():
            publisher = raw_publisher.strip()
    # publisher إلزامي *دلاليًا* لـ"تقرير منقول" (تشخيص Issue #373، الجولة
    # السادسة عشرة، طلب المراجعة البند "publisher إلزامي"): عنصر بلا ناشر
    # محدَّد لا سند بنيويًا ممكن له (لا شيء يُطابَق عليه شرط الهوية أدناه)،
    # فيعود إلى "واقعة" بعتبتها العادية (min_confirm_sources) بدل عتبة
    # report_min_confirm=1 التي لا معنى لتخفيفها بلا هوية ناشر واضحة.
    # وبالمثل (تشخيص الجولة السابعة عشرة): publisher بصيغة جمع يصف فئة
    # جماعية مجهولة ("قنوات تيليغرام إسرائيلية") لا كيانًا واحدًا بعينه —
    # الفحص بنيوي (_is_generic_source_publisher) لا حكم نموذج، فيمنع
    # الالتفاف بتسمية فئة عوضًا عن ناشر فعلي للإفادة من عتبة 1.
    if kind == "تقرير منقول" and (not publisher or _is_generic_source_publisher(publisher)):
        kind = "واقعة"
    return {"text": text, "kind": kind, "entities": entities,
            "is_unnamed_event": is_unnamed_event, "is_reference": is_reference,
            "speaker": speaker, "merged_excerpts": merged_excerpts,
            "split_from": split_from, "publisher": publisher}


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


def _naming_language_mismatch(named_text: str, proper_nouns: list[str], dates: list[str],
                              docs: list[dict], cfg) -> bool:
    """تشخيصي فقط لبناء رسالة الرفض — لا يمسّ حكم _naming_consistent ولا
    يُستدعى داخلها: هل كيانات الواقعة الأصلية عربية بينما كل وثائق التسمية
    المرشَّحة بلغة أخرى، والرفض فعليًا سببه فشل فحص الكيانات لا تعارض تاريخ؟
    (تشخيص Issue #373، حالة موجز تركي «بايراكتار» — entities تُستخرَج حرفيًا
    فتصل وثائق صحيحة بلغة الموجز الأصلية، لكن التطابق الحرفي بين كيان عربي
    ووثيقة غير عربية مستحيل بنيويًا في _naming_consistent، فرسالة الرفض
    العامة كانت تُضلِّل نحو "عطل بحث" بدل تسمية السبب اللغوي المعروف. القيد
    نفسه — علاجه يتطلب لمس norm_tokens/_extract_dates المشتركتين، مؤجَّل
    عمدًا، انظر CLAUDE.md — لا يُعالَج هنا، فقط تُسمَّى رسالته صراحة).
    date_state != DATE_MISMATCH إلزامي: تعارض تاريخ صريح هو السبب الفعلي
    حينها، لا اختلاف اللغة، حتى لو صادف اختلاف اللغة أيضًا."""
    if not proper_nouns or not docs:
        return False
    if not any(has_arabic(e) for e in proper_nouns):
        return False
    if any(has_arabic(d.get("text", "")) for d in docs):
        return False
    acfg = cfg.get("article", {}) or {}
    window_days = int(acfg.get("naming_date_window_days", 2))
    return _dates_consistent(named_text, dates, docs, window_days) != DATE_MISMATCH


# توجيه لغوي موحَّد للأحكام الخمسة (تسمية/سند-واقعة/سند-تصريح/سند-تقرير/
# إجابة سؤال) — تشخيص Issue #373، حالة موجز تركي (بايراكتار): entities
# تُستخرَج حرفيًا فتبني استعلامًا بلغة الموجز الأصلية فيجد الوثائق الصحيحة
# فعلًا (تركية/إنجليزية)، لكن نص الواقعة/السؤال المحكوم عليه عربي (مترجَم
# داخل extract_brief) — فيقارن كل حكم نصًّا عربيًا بوثائق بلغة أخرى ويخفق
# رغم صحة المضمون. توجيه صريح أرخص وأقل هشاشة من ترجمة كل نص قبل كل حكم:
# النموذج يفهم اللغتين أصلًا، والمشكلة أن البرومبت لا يخبره أن اختلاف اللغة
# متوقَّع لا خلل. لا يمسّ فحص الأصالة (verify_draft.check_originality —
# تطابق حرفي بطبيعته، يبقى خاملًا بلا حل هنا بقرار) ولا DRAFT_SYSTEM_TEMPLATE
# (الصياغة النهائية عربية دومًا بصرف النظر عن لغة المصادر، بلا حاجة لتوجيه
# إضافي) ولا بوابة الاتساق _naming_consistent (تعتمد على دوال تطبيع مشتركة
# حساسة — انظر القيد المسجَّل في CLAUDE.md بدل لمسها هنا).
LANGUAGE_NOTE = """قد يكون النص الذي تحكم عليه بالعربية بينما نصوص المصادر
بلغة أخرى (تركية أو إنجليزية أو غيرها)، أو العكس — هذا متوقَّع ولا يعني
غياب التطابق. احكم على المضمون بعد فهمك لكل نص أيًّا كانت لغته، لا على
تطابق الألفاظ أو اتفاق اللغة."""


NAMING_SYSTEM = f"""أنت تقرأ نصوص مصادر إخبارية مستقلة لتحدّد الحدث المحدَّد
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

{LANGUAGE_NOTE}

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
            if _naming_language_mismatch(named["text"], proper_nouns, dates, docs, cfg):
                entry["outcome"] = ("رُفض — الوثائق بلغة غير عربية فلم يقع تطابق "
                                    "الكيانات حرفيًا (بوابة الاتساق؛ قيد لغوي "
                                    "معروف، انظر CLAUDE.md)")
            else:
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

# mentioned إلى جانب supporting (طلب المراجعة، تشخيص Issue #373، حالة
# بايراكتار الرابعة): حين يرجع الحكم صفرًا، "لم يُقرأ نص يتحدث عن الموضوع
# إطلاقًا" و"قُرئ نص يتحدث عنه لكن لم يطابق مضمون الواقعة/التصريح" عطلان
# مختلفان تمامًا يحتاجان تشخيصًا مختلفًا — الأول عطل بحث محتمل، الثاني عطل
# حكم. النموذج يميّز بينهما داخليًا أصلًا (البرومبت ينص صراحة: "مصدر لم يذكر
# ... إطلاقًا لا يُحسب مؤيدًا ولا مخالفًا") لكن التمييز لم يكن يخرج كحقل
# منفصل. mentioned تجمع كل مصدر ناقش الموضوع العام ولو لم يطابقه حرفيًا —
# فرق mentioned - supporting هو "ذكره ولم يطابقه"، وغياب أي مصدر عن mentioned
# كليًا هو "لم يُذكر إطلاقًا".
MENTIONED_NOTE = """أخرج أيضًا في mentioned أسماء كل المصادر التي ناقشت
الموضوع العام (الحدث/المتحدث/التقرير) ولو لم تطابق مضمونه بالضبط أو خالفته
— لا المصادر المؤيِّدة وحدها. مصدر لم يتطرق للموضوع إطلاقًا لا يدخل
mentioned أيضًا."""

SUPPORT_SYSTEM = f"""أنت تتحقق هل نصوص مصادر مستقلة تسند واقعة بعينها.

احكم من النصوص المعطاة فقط — لا تستخدم معرفتك الخاصة عن الموضوع. التأييد
يعني أن النص يذكر الواقعة نفسها أو ما يقاربها بوضوح، لا مجرد ذكر موضوع
عام قريب منها. مصدر لم يذكر الواقعة إطلاقًا لا يُحسب مؤيدًا ولا مخالفًا.
أخرج اسم المصدر مجردًا تمامًا كما ورد في وسم '--- المصدر: <الاسم> ---'
فقط، بلا اختراع أسماء جديدة.

{MENTIONED_NOTE}

{LANGUAGE_NOTE}

استخدم أداة support_fact دائمًا."""

SUPPORT_SCHEMA = {
    "name": "support_fact",
    "description": "يحدد أي المصادر المعطاة يسند واقعة بعينها، وأيها ناقشها بلا مطابقة",
    "input_schema": {
        "type": "object",
        "properties": {
            "supporting": {"type": "array", "items": {"type": "string"}},
            "mentioned": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["supporting", "mentioned"],
    },
}

# فحص سند "تصريح" (البند 1، تشخيص Issue #373، الجولة الثالثة عشرة): نظام
# منفصل عن SUPPORT_SYSTEM — بلا تخفيف في عتبة min_confirm_sources نفسها،
# لكن بمعيار تأييد أدق: مضمون التصريح يجب أن يرد في النص، لا مجرد وقوع
# المقابلة/الظهور الإعلامي. مصدر يذكر أن المتحدث "أدلى بتصريحات" أو "تحدث
# في مقابلة" بلا نقل مضمونها لا يُحسب مؤيدًا — التساهل هنا كان سيُبطل جوهر
# القاعدة 1 (سند فعلي لا وقوع حدث عام قريب منه).
STATEMENT_SUPPORT_SYSTEM = f"""أنت تتحقق هل نصوص مصادر مستقلة تسند مضمون
تصريح منسوب لمتحدث بعينه — لا مجرد وقوع مقابلة أو ظهور إعلامي له.

احكم من النصوص المعطاة فقط — لا تستخدم معرفتك الخاصة عن الموضوع. التأييد
يعني أن النص يذكر مضمون التصريح نفسه (ما قاله المتحدث فعليًا) بوضوح يقارب
التصريح المعطى — لا مجرد أنه "أدلى بتصريحات" أو "تحدث في مقابلة" أو "ظهر
إعلاميًا" بلا نقل مضمون ذلك الظهور. مصدر يذكر وقوع المقابلة وحده بلا مضمونها
لا يُحسب مؤيدًا. مصدر لم يذكر التصريح إطلاقًا لا يُحسب مؤيدًا ولا مخالفًا.
أخرج اسم المصدر مجردًا تمامًا كما ورد في وسم '--- المصدر: <الاسم> ---'
فقط، بلا اختراع أسماء جديدة.

{MENTIONED_NOTE}

{LANGUAGE_NOTE}

استخدم أداة support_fact دائمًا."""

# فحص سند "تقرير منقول" (نوع رابع، تشخيص Issue #373، الجولة السادسة عشرة):
# نظير STATEMENT_SUPPORT_SYSTEM لكن على مضمون *تقرير نشرته منصة* بدل كلام
# متحدث — يُستدعى فقط على الوثائق التي اجتازت شرط الهوية البنيوي أصلًا
# (_report_identity_kind، يُطبَّق داخل _support_sources قبل هذا النداء) —
# فحص المضمون هنا مكمّل لا بديل عن شرط الهوية، لا يغني عنه.
REPORT_SUPPORT_SYSTEM = f"""أنت تتحقق هل نص مصدر يعكس مضمون تقرير نشرته منصة
بعينها — لا مجرد ذكر عابر لاسمها.

احكم من النص المعطى فقط — لا تستخدم معرفتك الخاصة عن الموضوع. التأييد يعني
أن النص (سواء كان هو التقرير الأصلي نفسه، أو ناقلًا يسمّي الناشر وينقل
مضمون تقريره) يذكر مضمون التقرير الموصوف بوضوح يقارب ما يُعطى لك — لا مجرد
أن اسم المنصة ورد عرضًا بلا نقل مضمون ما نشرته. مصدر لم يذكر مضمون التقرير
إطلاقًا لا يُحسب مؤيدًا. أخرج اسم المصدر مجردًا تمامًا كما ورد في وسم
'--- المصدر: <الاسم> ---' فقط، بلا اختراع أسماء جديدة.

{MENTIONED_NOTE}

{LANGUAGE_NOTE}

استخدم أداة support_fact دائمًا."""


class _PartSupportList(list):
    """نتيجة _support_statement_parts: قائمة بطول عدد أجزاء التصريح
    (merged_excerpts)، كل عنصر قائمة أسماء المصادر المؤيِّدة لذلك الجزء
    تحديدًا — لا حكم شمولي واحد. قائمة فارغة عند الفشل (نظير
    _ModelCallList)، وcall_error لسبب الفشل التقني — استعمل
    getattr(result, "call_error", None) للتمييز عن حكم "لا مؤيِّد لأي جزء"
    فعلي من النموذج."""
    call_error: str | None = None


# معيار الأغلبية لسند "تصريح" مُدمَج من عدة دعاوى (طلب المراجعة، تعليق
# العطل الرابع والعشرون، تشخيص Issue #373): STATEMENT_SUPPORT_SYSTEM أعلاه
# يحكم على التصريح **كوحدة واحدة** — شاهد فعلي (خمس دعاوى مُدمَجة، مصدران
# يغطيان الموضوع فعليًا): الحكم رجع "ذكره 2 مصدر لكن لم يطابق مضمونه
# أيٌّ منها"، لأن كل مصدر أيّد جزءًا مختلفًا من الخمسة لا التصريح بأكمله،
# فرفضه الحكم الشمولي كليًا رغم أن كل جزء منه مُغطًّى فعليًا. العلاج: حكم
# على كل جزء (merged_excerpts) منفردًا هنا، ثم حساب عددي في الكود (لا
# تصنيف "جوهري/هامشي" من النموذج، _statement_majority أدناه) يقرر أي مصدر
# يُعامَل كمؤيِّد للتصريح ككل — من أيّد أغلبية أجزائه (N//2+1 فأكثر من N).
# محصور بمسار is_statement=True وحده (لا يمسّ SUPPORT_SYSTEM/
# REPORT_SUPPORT_SYSTEM)؛ min_confirm_sources بلا تغيير — هذا المعيار
# يقرر *من يُحسب مؤيدًا*، لا *كم مؤيدًا يلزم*.
STATEMENT_PART_SUPPORT_SYSTEM = f"""أنت تتحقق هل نصوص مصادر مستقلة تسند
أجزاء تصريح منسوب لمتحدث بعينه — كل جزء منفردًا بمعزل عن الأجزاء الأخرى،
لا التصريح كوحدة واحدة.

التصريح مقسَّم أدناه إلى أجزاء مرقّمة كما وردت في الموجز. احكم من النصوص
المعطاة فقط — لا تستخدم معرفتك الخاصة عن الموضوع. لكل جزء، أخرج في
parts[i].supporting أسماء كل مصدر يذكر مضمون **ذلك الجزء تحديدًا** (ما
قاله المتحدث فعليًا فيه) بوضوح يقاربه — لا مجرد أنه "أدلى بتصريحات" أو
"تحدث في مقابلة" بلا نقل مضمون ذلك الجزء بعينه. مصدر لم يذكر مضمون هذا
الجزء تحديدًا لا يدخل قائمته، حتى لو أيّد أجزاء أخرى من نفس التصريح —
احكم على كل جزء بمعزل تام عن الأجزاء الأخرى، لا حكمًا واحدًا على مجملها.
أخرج عنصرًا في parts لكل جزء بنفس رقمه وترتيبه كما وردت الأجزاء أدناه،
حتى لو كانت supporting فارغة. أخرج اسم المصدر مجردًا تمامًا كما ورد في
وسم '--- المصدر: <الاسم> ---' فقط، بلا اختراع أسماء جديدة.

{LANGUAGE_NOTE}

استخدم أداة support_statement_parts دائمًا."""

STATEMENT_PART_SUPPORT_SCHEMA = {
    "name": "support_statement_parts",
    "description": ("يحدد أي المصادر المعطاة يسند مضمون كل جزء مرقّم من "
                    "تصريح، جزءًا جزءًا لا التصريح كوحدة واحدة"),
    "input_schema": {
        "type": "object",
        "properties": {
            "parts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "supporting": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["index", "supporting"],
                },
            },
        },
        "required": ["parts"],
    },
}


def _support_statement_parts(merged_excerpts: list[str], docs: list[dict],
                             cfg) -> _PartSupportList:
    """يحكم على كل جزء من أجزاء تصريح مُدمَج (merged_excerpts) منفردًا —
    معيار الأغلبية (_statement_majority أدناه) يُبنى من نتيجتها مباشرة.
    يعيد قائمة بطول len(merged_excerpts)، كل عنصر قائمة أسماء المصادر
    المؤيِّدة لذلك الجزء تحديدًا (من docs فعليًا، لا مُختلَقة عبر
    evidence._known_only). فشل نداء تقني يعيد _PartSupportList فارغة
    بـcall_error مضبوطًا — استعمل getattr(result, "call_error", None)
    للتمييز عن حكم "لا مؤيِّد لأي جزء" فعلي من النموذج."""
    if not docs or not merged_excerpts:
        return _PartSupportList()
    acfg = cfg.get("article", {}) or {}
    model = acfg.get("model", "claude-sonnet-5")
    client = _client()
    numbered = "\n".join(f"{i}. {ex}" for i, ex in enumerate(merged_excerpts, start=1))
    prompt = f"أجزاء التصريح:\n{numbered}\n\nنصوص المصادر:\n\n{_format_docs(docs)}"
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=600,
            tools=[STATEMENT_PART_SUPPORT_SCHEMA],
            tool_choice={"type": "tool", "name": "support_statement_parts"},
            system=STATEMENT_PART_SUPPORT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            # لا تُضِف temperature — انظر توثيق _ask_naming_model أعلاه.
        )
        writer.record_usage(resp, model)
    except APIError as exc:
        log.warning("فشل نداء الحكم الجزئي على سند التصريح: %s", exc)
        fail = _PartSupportList()
        fail.call_error = str(exc)
        return fail
    data = next((b.input for b in resp.content
                if getattr(b, "type", "") == "tool_use"), None)
    raw_parts = data.get("parts") if isinstance(data, dict) else None
    by_index: dict[int, list[str]] = {}
    if isinstance(raw_parts, list):
        for item in raw_parts:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            if not isinstance(idx, int):
                continue
            by_index[idx] = evidence._known_only(item.get("supporting"), docs)
    return _PartSupportList(
        by_index.get(i, []) for i in range(1, len(merged_excerpts) + 1)
    )


def _statement_majority(merged_excerpts: list[str],
                        parts_support: list[list[str]]
                        ) -> tuple[set[str], set[str], list[str]]:
    """معيار الأغلبية (طلب المراجعة): مصدر يُسنِد التصريح ككل إن أيّد
    N//2+1 جزءًا فأكثر من N جزءًا — حساب عددي في الكود على نتيجة
    _support_statement_parts، لا تصنيف "جوهري/هامشي" من النموذج. يعيد
    (المصادر المؤيِّدة بالأغلبية، كل مصدر ذُكر في جزء واحد فأكثر
    [mentioned، لرسالة _support_gap_detail]، الأجزاء التي أيّدها مصدر واحد
    فأكثر بصرف النظر عن الأغلبية — هذه وحدها تدخل نص الصياغة لاحقًا: جزء
    لم يؤيِّده أي مصدر لا يدخل المتن حتى لو اجتاز التصريح ككل بأغلبية
    أجزاء أخرى، وإلا نُشرت دعوى رفضتها المصادر تحت غطاء أغلبية)."""
    n = len(merged_excerpts)
    if n == 0:
        return set(), set(), []
    majority_needed = n // 2 + 1
    counts: dict[str, int] = {}
    mentioned: set[str] = set()
    included_excerpts: list[str] = []
    for excerpt, supporters in zip_longest(merged_excerpts, parts_support, fillvalue=[]):
        supporters = supporters or []
        if supporters:
            included_excerpts.append(excerpt)
        for name in supporters:
            counts[name] = counts.get(name, 0) + 1
            mentioned.add(name)
    supporting = {name for name, c in counts.items() if c >= majority_needed}
    return supporting, mentioned, included_excerpts


def _report_identity_kind(publisher: str, doc: dict, cfg) -> str | None:
    """شرط الهوية المزدوج البنيوي لـ"تقرير منقول" (لا حكم نموذج — طلب
    المراجعة، تشخيص Issue #373 الجولة السادسة عشرة): يعيد "original" إن
    كانت الوثيقة من الناشر المُصرَّح به في الموجز نفسه (توحيد عبر
    evidence._tokens_match، نفس منطق _canonical_publisher)، أو "carrier" إن
    سمّته صراحةً داخل نصها (ناقل موثَّق — منصة أجنبية متخصصة قد لا تظهر في
    نتائج بحث عربية أصلًا)، أو None إن لم تطابق أيًّا. هذا الشرط — لا حكم
    نموذج يصنّف الوثيقة بنفسه — هو ما يمنع الالتفاف: خبر عادي مُصنَّف زورًا
    كـ"تقرير منقول" لن يجد وثيقة واحدة تطابق هوية ناشر بعينه محدَّد سلفًا
    بهذه الدقة."""
    if not publisher:
        return None
    if evidence._tokens_match(publisher, doc.get("name", "")):
        return "original"
    text_tokens = norm_tokens(doc.get("text", "") or "")
    pub_tokens = norm_tokens(publisher)
    if pub_tokens and pub_tokens <= text_tokens:
        return "carrier"
    return None


def _support_sources(fact_text: str, docs: list[dict], cfg,
                     is_statement: bool = False, is_report: bool = False,
                     publisher: str = "") -> list[str]:
    """يعيد أسماء المصادر (من docs فعليًا، لا مُختلَقة) التي تسند fact_text
    — القاعدة 1: هذه القائمة (بعد عدّها) هي ما يقرر مصير الواقعة. فشل نداء
    تقني يعيد _ModelCallList فارغة بـcall_error مضبوطًا (لا [] عاديًا) —
    استعمل getattr(result, "call_error", None) للتمييز عن حكم "لا مصادر"
    فعلي من النموذج.

    is_statement=True (kind == "تصريح") يستعمل STATEMENT_SUPPORT_SYSTEM بدل
    SUPPORT_SYSTEM — نفس العتبة (min_confirm_sources) بلا أي تخفيف، لكن
    معيار تأييد أدق يفحص مضمون التصريح لا وقوع المقابلة وحدها.

    is_report=True (kind == "تقرير منقول"، الجولة السادسة عشرة): docs تُصفَّى
    أولًا بشرط الهوية البنيوي (_report_identity_kind) — قبل أي نداء نموذج —
    فلا يصل REPORT_SUPPORT_SYSTEM إلا وثائق تطابق هوية publisher فعلًا؛
    عتبتها (report_min_confirm) مستقلة تُطبَّق خارج هذه الدالة."""
    if is_report:
        docs = [d for d in docs if _report_identity_kind(publisher, d, cfg)]
    if not docs:
        return []
    acfg = cfg.get("article", {}) or {}
    model = acfg.get("model", "claude-sonnet-5")
    client = _client()
    if is_report:
        system, label = REPORT_SUPPORT_SYSTEM, "التقرير المنقول"
    elif is_statement:
        system, label = STATEMENT_SUPPORT_SYSTEM, "التصريح"
    else:
        system, label = SUPPORT_SYSTEM, "الواقعة"
    prompt = f"{label}: {fact_text}\n\nنصوص المصادر:\n\n{_format_docs(docs)}"
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            tools=[SUPPORT_SCHEMA],
            tool_choice={"type": "tool", "name": "support_fact"},
            system=system,
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
    result = _ModelCallList(evidence._known_only(data.get("supporting"), docs))
    result.mentioned = evidence._known_only(data.get("mentioned"), docs)
    return result


# ──────────────────────── الإجابة عن أسئلة الموجز (البند 5) ──────────────────

ANSWER_SYSTEM = f"""أنت تجيب عن سؤال طرحه صاحب موجز تحريري، من نصوص مصادر
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

{LANGUAGE_NOTE}

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


# ─────────────────── وقائع من المصادر (لا الموجز فقط) ───────────────────
# الموجز يحصر ما يمكن أن يقوله المقال على ما كتبه صاحبه — حتى حين تحمل
# الوثائق المقروءة فعلًا أثناء البحث عن سند لوقائع الموجز وأسئلته وقائع
# أخرى ذات صلة مباشرة بنفس الحدث لم يذكرها هو (طلب المراجعة). بعد اكتمال
# تلك الحلقة (all_read_docs مكتملة)، نداء واحد على أفضل الوثائق المقروءة
# (بالوزن ثم الصلة — البند 3، انظر _rank_docs_for_source_extract) يستخرج
# وقائع إضافية غائبة عن وقائع الموجز المسندة أصلًا.
#
# الدمج ضد التكرار هو الخطوة الأخطر هنا (طلب المراجعة، البند 1 — إن فشل،
# تضخّم grounded بوقائع مكرَّرة واجتاز مقالٌ عتبةً لم يستحقها): قبل أي بحث
# سند مستقل، كل واقعة مستخرَجة تُقارَن بوقائع الموجز المسندة عبر
# _source_fact_duplicate_index — حكم دلالي (نفس الحدث بصياغتين مختلفتين)
# لا فحص بنيوي (تشارك الكيانات وحده لا يكفي: شخص واحد قد يكون طرفًا في
# حدثين مختلفين تمامًا، فتشاركهما الكيانات لا يعني أنهما نفس الواقعة —
# انظر SOURCE_FACT_DEDUP_SYSTEM وفِكستَي test_article_source_facts في
# tests/test_pipeline.py المبنيَّين قبل أي وصل بالأنبوب الرئيسي). واقعة
# مكرَّرة تُدمَج (لا تُعدّ)؛ واقعة ناجية من الدمج تخضع لنفس دورة البحث/
# القراءة/السند الكاملة كأي "واقعة" عادية (القاعدة 1 — لا استثناء لمجرد
# أنها وُجدت في وثيقة مقروءة أصلًا) قبل أن تدخل grounded بوسم
# origin: "source"، مميَّزةً في التقرير عن origin: "brief" لكل ما سواها.

SOURCE_EXTRACT_SYSTEM = f"""أنت تقرأ نصوص مصادر إخبارية مستقلة قُرئت أثناء
التحقق من موجز تحريري، لتستخرج منها وقائع إضافية **غائبة عن الموجز نفسه**
— معلومات حقيقية ذات صلة مباشرة بموضوعه لم يذكرها كاتب الموجز، لا لأنه
أخطأ بل لأنه لا يعرفها.

موضوع الموجز ووقائعه التي استُخرجت منه أصلًا معطاة لك أدناه — لا تكرّرها،
ولا واقعة تصف نفس الحدث بصياغة مختلفة (تلك مذكورة بالفعل، ستُقارَن لاحقًا
دلاليًا لا حرفيًا فلا تعتمد على اختلاف اللفظ لتفادي التكرار).

اقرأ نصوص المصادر فقط. استخرج حتى خمس وقائع إضافية — كل واحدة تدّعي وقوع
حدث أو رقم محدَّد (بنفس معيار "واقعة": فاعل وفعل، لا جملة وصفية بحتة أو
سردية عامة) مذكورة صراحة في نص واحد على الأقل من المصادر المعطاة. إن لم
تجد النصوص شيئًا إضافيًا حقيقيًا يستحق الذكر، أعد قائمة فارغة — لا تخترع
واقعة لمجرد ملء العدد.

لكل واقعة: text (بإيجاز، بصياغتك من النص لا نقلًا حرفيًا)، وentities
(2-5 كيانات مميِّزة منها كما وردت في نص المصدر — سيُبنى منها استعلام بحث
سند مستقل). **text وentities كلاهما بالعربية دومًا** — حتى إن كانت نصوص
المصادر بلغة أخرى (تركية أو إنجليزية أو غيرها): ترجم الكيانات، لا تنقلها
بأبجديتها الأصلية (خلافًا لاستخراج كيانات الموجز نفسه في مسار آخر، الذي
يحتفظ بأبجدية الموجز الأصلية — هنا المصدر أجنبي والمقال عربي دومًا، فكيان
بأبجدية لن يطابقها بحث عربي لاحقًا عديم الفائدة).

{LANGUAGE_NOTE}

استخدم أداة extract_source_facts دائمًا."""

SOURCE_EXTRACT_SCHEMA = {
    "name": "extract_source_facts",
    "description": "يستخرج وقائع إضافية من نصوص مصادر مقروءة، غائبة عن موجز تحريري",
    "input_schema": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "entities": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "entities"],
                },
            },
        },
        "required": ["facts"],
    },
}


def _rank_docs_for_source_extract(docs: list[dict], wanted: set[str], cfg,
                                  max_docs: int) -> list[dict]:
    """توحيد هوية الناشر ثم فرز الوثائق المرشَّحة لاستخراج وقائع المصادر
    بالوزن والصلة معًا (طلب المراجعة، البند 3) — نفس منطق
    evidence._candidate_score/_candidate_sort_key المستعمَل لاختيار مرشّحي
    القراءة، لا فرزًا جديدًا: وثيقة موثوقة تتصدَّر على مجهولة عند التزاحم
    على سقف عدد الوثائق في البرومبت. الصلة هنا عدّ تشارك توكنز نص الوثيقة
    مع wanted (كيانات كل وقائع/أسئلة الموجز مجتمعة) — لا Article كامل بحقل
    relevance جاهز، لأن docs هنا نصوص مقروءة مجمَّعة عبر التشغيلة كلها
    (all_read_docs) لا نتيجة بحث استعلام واحد. توحيد الهوية أولًا
    (canonical) كي لا تُحسب نسخة ناشر واحد بلغتين مرشَّحين منفصلين
    يستهلكان فتحتين من السقف لنفس المحتوى فعليًا."""
    seen: dict[str, dict] = {}
    for d in docs:
        if not d.get("text"):
            continue
        canonical = evidence._canonical_publisher(d.get("name", ""), cfg)
        existing = seen.get(canonical)
        if existing is None or len(d["text"]) > len(existing["text"]):
            seen[canonical] = {**d, "name": canonical}
    scored = []
    for d in seen.values():
        weight = evidence._publisher_weight(d["name"], cfg)
        relevance = len(wanted & norm_tokens(d.get("text", "")))
        scored.append((weight, relevance, d))
    scored.sort(key=lambda t: evidence._candidate_sort_key(t[0], t[1]))
    return [d for _, _, d in scored[:max_docs]]


def _extract_source_facts(topic: str, brief_fact_texts: list[str], docs: list[dict],
                          cfg) -> list[dict]:
    """يستخرج وقائع إضافية من وثائق مقروءة فعلًا، غائبة عن وقائع الموجز
    المسندة أصلًا (brief_fact_texts) — يعيد _ModelCallList: فارغة مع
    call_error عند فشل تقني، فارغة عادية عند عدم وجود شيء إضافي، أو قائمة
    {"text":..., "entities":[...]} عند النجاح."""
    if not docs:
        return _ModelCallList()
    acfg = cfg.get("article", {}) or {}
    model = acfg.get("model", "claude-sonnet-5")
    max_tokens = int(acfg.get("source_extract_max_tokens", 2000))
    client = _client()
    brief_block = "\n".join(f"- {t}" for t in brief_fact_texts) or "لا وقائع"
    prompt = (f"موضوع الموجز: {topic}\n\nوقائع استُخرجت من الموجز أصلًا "
             f"(لا تكرّرها):\n{brief_block}\n\nنصوص مصادر مقروءة:\n\n"
             f"{_format_docs(docs)}")
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            tools=[SOURCE_EXTRACT_SCHEMA],
            tool_choice={"type": "tool", "name": "extract_source_facts"},
            system=SOURCE_EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            # لا تُضِف temperature — انظر توثيق _ask_naming_model أعلاه.
        )
        writer.record_usage(resp, model)
    except APIError as exc:
        log.warning("فشل نداء استخراج وقائع من المصادر: %s", exc)
        fail = _ModelCallList()
        fail.call_error = str(exc)
        return fail
    data = next((b.input for b in resp.content
                if getattr(b, "type", "") == "tool_use"), None)
    raw = data.get("facts") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return _ModelCallList()
    out = _ModelCallList()
    for item in raw:
        text = _as_text(item)
        if not text:
            continue
        out.append({"text": text,
                    "entities": _as_entities(item.get("entities")
                                             if isinstance(item, dict) else None)})
    return out


SOURCE_FACT_DEDUP_SYSTEM = """أنت تقارن واقعة واحدة جديدة بقائمة وقائع
مؤكَّدة سابقًا من نفس المقال، لتحدد إن كانت **نفس الحدث بعينه** بصياغة
مختلفة (يجب دمجها، لا عدّها مرتين) أم حدثًا مختلفًا فعليًا.

المعيار: قارن الفعل/الحدث نفسه لا الكيانات المشتركة وحدها. شخص أو جهة
واحدة قد تكون طرفًا في عدة أحداث مختلفة تمامًا (زار مكانًا يوم الاثنين،
والتقى مسؤولًا يوم الثلاثاء لبحث ملف آخر) — هذان حدثان مستقلان رغم
اشتراكهما في الفاعل، ولا يجوز دمجهما. لا تدمج إلا حين يصف النصان **نفس
الفعل الواحد** الذي وقع، بصرف النظر عن اختلاف الصياغة أو ترتيب الكلمات أو
تفاصيل إضافية في أحدهما.

إن كانت الواقعة الجديدة تكرارًا لواحدة من القائمة، أعد رقمها كـ
duplicate_index (0 هو الأول في القائمة). إن لم تكن تكرارًا لأي واقعة في
القائمة، أعد duplicate_index: -1.

استخدم أداة check_duplicate دائمًا."""

SOURCE_FACT_DEDUP_SCHEMA = {
    "name": "check_duplicate",
    "description": "يحدد إن كانت واقعة جديدة تكرارًا دلاليًا لواحدة من قائمة وقائع سابقة",
    "input_schema": {
        "type": "object",
        "properties": {"duplicate_index": {"type": "integer"}},
        "required": ["duplicate_index"],
    },
}


def _source_fact_duplicate_index(candidate_text: str, existing_texts: list[str],
                                 cfg) -> dict:
    """يحكم هل candidate_text (واقعة استُخرجت من مصدر) تكرار دلالي لأحد
    existing_texts (وقائع الموجز المسندة أصلًا، أو وقائع مصادر سابقة أُضيفت
    في نفس التشغيلة) — البند 1 (الأخطر في هذا التصميم): إن فشل هذا الحكم،
    تضخّم grounded بوقائع مكرَّرة واجتاز مقالٌ عتبةً لم يستحقها. حكم دلالي
    (نفس الحدث بصياغتين مختلفتين) لا يمكن أن يكون فحصًا بنيويًا بحتًا —
    تشارك الكيانات وحده لا يكفي (نفس الشخص في حدثين مختلفين يجب ألا
    يندمجا)، فنداء نموذج مطلوب هنا كما في _support_sources/_ask_naming_model
    لأحكام دلالية مماثلة عبر هذا الملف.

    يعيد {"duplicate": bool, "index": int|None, "call_error": str|None} —
    فشل تقني يعيد duplicate=False مع call_error مضبوطًا: المستدعي يُسقط
    الواقعة تحوطًا بدل تخمين حكم دمج لم يقع فعليًا (انظر _write_article) —
    إسقاط فرصة أرخص من مخاطرة تضخيم العدّ بوقيعة قد تكون مكرَّرة فعلًا."""
    if not existing_texts:
        return {"duplicate": False, "index": None, "call_error": None}
    acfg = cfg.get("article", {}) or {}
    model = acfg.get("model", "claude-sonnet-5")
    client = _client()
    existing_block = "\n".join(f"{i}. {t}" for i, t in enumerate(existing_texts))
    prompt = f"الواقعة الجديدة: {candidate_text}\n\nالوقائع السابقة:\n{existing_block}"
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=100,
            tools=[SOURCE_FACT_DEDUP_SCHEMA],
            tool_choice={"type": "tool", "name": "check_duplicate"},
            system=SOURCE_FACT_DEDUP_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            # لا تُضِف temperature — انظر توثيق _ask_naming_model أعلاه.
        )
        writer.record_usage(resp, model)
    except APIError as exc:
        log.warning("فشل نداء تحقّق تكرار واقعة من المصادر: %s", exc)
        return {"duplicate": False, "index": None, "call_error": str(exc)}
    data = next((b.input for b in resp.content
                if getattr(b, "type", "") == "tool_use"), None)
    idx = data.get("duplicate_index") if isinstance(data, dict) else None
    if not isinstance(idx, int) or idx < 0 or idx >= len(existing_texts):
        return {"duplicate": False, "index": None, "call_error": None}
    return {"duplicate": True, "index": idx, "call_error": None}


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


def _reprint_fallback_images(excluded_reprints: list[dict],
                             ranked: list[Article]) -> list[dict]:
    """صور مرشَّحة من وثائق استُبعدت كإعادة نشر للموجز الملصق — الاستبعاد
    يخصّ عدّ السند (لا تُحتسب مصدرًا مستقلًا مؤيِّدًا) لا صلاحيتها كمصدر
    صورة (طلب المراجعة، تشخيص Issue #373، مراجعة بشرية بعد أول نشر، البند
    1: «مسودة بلا صورة لا تُنشر» — إسقاط صورة متاحة فعليًا لمجرد أن نصها
    استُبعد من عدّ الاستقلالية كلفة بلا مبرر). نفس بنية _grounded_sources
    (اسم → صور من ranked، وranked غير مُصفَّى بالاستبعاد أصلًا — الفلترة
    تقع فقط على docs) لكن لأسماء excluded_reprints لا للأسماء المسنِدة."""
    if not excluded_reprints:
        return []
    links = {e["name"]: e.get("link", "") for e in excluded_reprints}
    seen: set[str] = set()
    out = []
    for a in ranked:
        name = getattr(a, "publisher", "") or getattr(a, "source_name", "")
        if name in links and name not in seen:
            seen.add(name)
            imgs = getattr(a, "image_candidates", None) or []
            if imgs:
                out.append({"name": name, "link": links.get(name, ""),
                            "image_candidates": imgs})
    return out


def _pool_image_candidates(pool: list[dict]) -> list[tuple[str, str, str]]:
    """(رابط، اسم، رابط المصدر) من مجمّع مصادر {"name","link","image_candidates"}
    — نفس منطق verify_draft._image_candidates لكن على مجمّع صور احتياطي
    (مثل _reprint_fallback_images أعلاه) لا على وقائع مسندة."""
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for s in pool:
        for url in s.get("image_candidates") or []:
            if url in seen:
                continue
            seen.add(url)
            out.append((url, s["name"], s.get("link", "")))
    return out


def _image_search_terms(grounded: list[dict], limit: int = 3) -> list[str]:
    """عبارات بحث لاحتياط الصورة الحرة (imagesearch.find_images) من entities
    الوقائع المسندة (حقل بنيوي مُستخرَج مسبقًا وقت extract_brief — لا نص
    حر مُشتَق الآن) — لا central_text نفسه: imagesearch.keywords() تستخرج
    فقط أحرفًا لاتينية كبيرة، فنص عربي محض (central_text دومًا عربي هنا)
    يعيد منها قائمة فارغة دومًا بصرف النظر عن محتواه، فيُسقط find_images
    إلى صفر نتائج **قبل أي نداء شبكة** — عطل بنيوي مؤكَّد (طلب المراجعة،
    تشخيص Issue #373، مراجعة بشرية بعد أول نشر، البند 1)، لا عطل وليد
    استبعاد إعادات النشر."""
    seen: list[str] = []
    for f in grounded:
        for e in f.get("entities") or []:
            e = str(e).strip()
            if e and e not in seen:
                seen.append(e)
    return seen[:limit]


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
    خبر فعلي لا خلفية وحدها.

    **ضابط ثالث (طلب المراجعة، تشخيص Issue #373 الجولة السادسة عشرة)،
    نظير شرط "واقعة غير مرجعية" أعلاه بالضبط**: يُشترط أيضًا وجود واقعة
    واحدة على الأقل ليست "تقرير منقول" ضمن `grounded`. "تقرير منقول"
    عتبته report_min_confirm=1 (لا 2) لأن نشر منصة واحدة لا يمكن أن يرصده
    مصدر مستقل ثانٍ بطبيعته — سهولة نسبية في اجتياز السند تماثل سهولة
    الوقائع المرجعية أعلاه لنفس السبب البنيوي (عتبة أدنى ← اجتياز أسهل، لا
    قوة خبر أعلى). مقال مبنيّ بالكامل على "قالت منصة كذا" بلا واقعة واحدة
    مسندة بمصدرين مستقلين حقيقيين ليس خبرًا قائمًا بذاته."""
    acfg = cfg.get("article", {}) or {}
    min_grounded = int(acfg.get("min_grounded_facts", 2))
    if len(grounded) < min_grounded:
        return False, (f"عدد الوقائع المسندة ({len(grounded)}) دون الحد الأدنى "
                       f"({min_grounded}) — القاعدة 7: لا مقال")
    if not any(not g.get("is_reference") for g in grounded):
        return False, ("كل الوقائع المسندة خلفية/مرجعية (سيرة أو تاريخ سابق موثَّق "
                       "سلفًا) — لا خبر جديد فعلي يستحق مقالًا (تعليق الموافقة، البند 6)")
    if not any(g.get("kind") != "تقرير منقول" for g in grounded):
        return False, ("كل الوقائع المسندة تقارير منقولة عن منصة/منصات واحدة بعتبة "
                       "مصدر واحد لكلٍّ — لا واقعة مسندة بمصدرين مستقلين حقيقيين "
                       "تقوم عليها القصة (نظير شرط الوقائع المرجعية، البند 6)")
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
6. لا تذكر اسم المصدر داخل المتن — يُكتب أسفل المنشور تلقائيًا. استثناء
   وحيد: القاعدة 9 أدناه (نسبة "تقرير منقول" لاسم ناشره) — هناك اسم الناشر
   جزء من الواقعة نفسها لا استشهادًا زائدًا.
7. استوعب الوقائع المسندة المعطاة كلها في المتن — لا تختصرها في جملة واحدة
   حين تحتمل فقرة. هذا مقال مطوَّل عن مصادر عدة قُرئت فعليًا، لا خبر عاجل
   مقتضب: كل واقعة معطاة تستحق مساحتها في المتن، لا حذفًا انتقائيًا.
8. الوقائع المعلَّمة بـ"[تصريح لـ...]" تنقل كلام متحدث بعينه — مصدران
   مستقلان أكّدا أنه قال هذا الكلام، لا أن مضمونه صحيح بالضرورة. حين تحمل
   رقمًا أو ادّعاءً عن قدرة عسكرية أو أمنية، وضّح ذلك في صلب الجملة نفسها
   لا في حاشية منفصلة — بصيغة كـ"وزعم فلان أن..." أو "وبحسب ادّعاء
   فلان..." — لا تصغها كأنها معلومة مؤكَّدة من مصدر مستقل.
9. الوقائع المعلَّمة بـ"[تقرير منقول عن ...]" مصدرها نشرٌ من منصة واحدة
   بعينها لا حدث يمكن أن يرصده أكثر من طرف مستقل — إلزامًا لا اختياريًا،
   انسب كل مضمونها في صلب الجملة نفسها لاسم تلك المنصة صراحة، بصيغة كـ
   "وبحسب تقرير نشرته منصة..." أو "وذكرت صحيفة... في تقرير لها أن..." —
   لا تقدّمه خبرًا مؤكَّدًا من مصدر مستقل ولا تُسقط اسم الناشر من الجملة.
10. استثناء من القاعدة 9 لا يُنسب بل يُحذف كليًا: واقعة معلَّمة بـ"[تقرير
    منقول عن ...]" تدّعي نية عسكرية أو تخطيطًا لهجوم بين دول (لا بيانًا
    رسميًا صادرًا عن جهة الدولة نفسها) لا تدخل المتن إطلاقًا مهما كان
    سندها — لا منسوبة لاسم الناشر ولا بصيغة متحفِّظة. احذفها من المتن
    كليًا؛ هذا نوع محتوى لا تكفي فيه النسبة، فتجاهله كأنه لم يُسند.
11. المتن نصٌّ إخباري للقارئ فقط — لا تشِر فيه إلى عملية إنتاجه ولا إلى
    مصطلحات بنية المشروع الداخلية (مثل "الوقائع المسندة"، "المصادر
    المستقلة"، "السؤال المختار"، "بوابة الاتساق"، "فحص الأصالة")، ولا
    تعلّق على كفاية الأدلة أو مطابقتها للسؤال المطروح. اكتب الوقائع نفسها
    مباشرة كخبر، لا كتقرير عن عملية التحقق منها أو اختيارها.
12. لا فقرة ختامية تلخّص ما سبق أو تعيد صياغته بكلمات مختلفة — المتن ينتهي
    بآخر واقعة معطاة مباشرة، لا بإعادة تكرار مضمون الفقرات السابقة.

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

وقائع مسندة بمصدرين مستقلين فأكثر — مضمون المتن كله (كل اسم علم ورقم
وتاريخ) يُبنى من هذه القائمة حصرًا، لا مما يلي بعدها:

{facts_block}

نصوص المصادر المستقلة التي أيّدت هذه الوقائع — اقرأها للأسلوب والسياق
اللغوي فقط (كيف يُروى الخبر عربيًا بطلاقة)، لا كمصدر مضمون إضافي: أي
تفصيلة فيها لم تظهر في الوقائع المسندة أعلاه ممنوع نقلها إلى المتن مهما
بدت صحيحة أو مفيدة للسياق — القاعدة 1 (لا تخترع تفصيلة ولا تُكمل من عندك
ما لم تذكره الوقائع المعطاة) تشمل هذه النصوص كما تشمل معرفتك الخاصة تمامًا:

{source_texts}
{opinions_block}{avoid_note}
املأ حقول أداة write_article من الوقائع المسندة أعلاه حصرًا (والرأي
المنسوب إن وُجد) — لا معرفة سابقة ولا مصدر ثالث ولا نقل من نصوص المصادر:

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
    مضمونه بالضرورة) عن واقعة مسندة من مصدر مستقل مباشرة. وكل واقعة من
    kind=='تقرير منقول' بوسم "[تقرير منقول عن ...]" نظيره — القاعدة 9
    تعتمد عليه لتنسب مضمونه لاسم ناشره صراحة في المتن (الجولة السادسة عشرة)."""
    lines = []
    for f in grounded:
        if f.get("kind") == "تصريح":
            speaker = f.get("speaker") or "؟"
            lines.append(f"- [تصريح لـ{speaker}] {f['text']}")
        elif f.get("kind") == "تقرير منقول":
            publisher = f.get("publisher") or "؟"
            lines.append(f"- [تقرير منقول عن {publisher}] {f['text']}")
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


def _build_avoid_note(offending: dict) -> str:
    """توجيه محاولة الصياغة الثانية (طلب المراجعة، تشخيص Issue #373، تعليق
    العطل الحادي والعشرون، البند 2): يذكر الجملة المخالفة بعينها كما رصدها
    فحص الأصالة (لا وصفًا عامًا) — النموذج يُعاد بناؤها من جديد، لا يُطلب
    منه "لا تنسخ" بلا تحديد ما نُسخ فعلًا."""
    if offending.get("match_kind") == "source" and offending.get("source_name"):
        loc = f"من مقتطف المصدر ({offending['source_name']})"
    else:
        loc = "من الموجز الملصق"
    sentence = offending.get("draft_sentence") or offending.get("phrase") or ""
    return (f"\nمحاولة سابقة رفضها فحص الأصالة لتطابقها الحرفي {loc} على الجملة "
           f"التالية تحديدًا — أعد صياغتها من جديد بالكامل، بترتيب وكلمات مختلفة "
           f"تمامًا، محافظًا على المعنى والوقائع نفسها فقط، لا نسخة معدَّلة قليلًا "
           f"عنها: «{sentence}»\n")


def _draft_article(grounded: list[dict], opinions: list[dict], question: str,
                   cfg, retries: int = 3, avoid_note: str = "") -> tuple[dict | None, str]:
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
        avoid_note=avoid_note,
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


def _report_attribution_ok(post_body: str, grounded: list[dict]) -> tuple[bool, str]:
    """يتحقق **بنيويًا** — لا بالبرومبت وحده (طلب المراجعة، تشخيص Issue
    #373 الجولة السادسة عشرة، البند 1: "أضف اختبارًا يثبت أن متنًا... بلا
    نسبة يُرفض — لا برومبت وحده") — أن مضمون كل عنصر "تقرير منقول" في
    grounded منسوب لاسم ناشره صراحة داخل post_body (القاعدة 9). القاعدة 9
    في DRAFT_SYSTEM_TEMPLATE توجيه للنموذج فقط؛ هذا الفحص اللاحق هو ما يضمن
    الالتزام الفعلي بصرف النظر عن التزام النموذج بالتوجيه.

    مطابقة توكنز متسامحة (norm_tokens، نفس منطق _report_identity_kind) لا
    تطابق حرفي صارم — اسم الناشر قد يُصرَّف نحويًا في المتن (مثال: "موقع
    ميليتير" قد يُذكر كـ"موقع ميليتير اليوناني")؛ المطلوب أن تكون كل كلمات
    اسم الناشر (بعد التطبيع) واردة في المتن، لا تطابق النص الكامل حرفيًا."""
    body_tokens = norm_tokens(post_body or "")
    for f in grounded:
        if f.get("kind") != "تقرير منقول":
            continue
        publisher = f.get("publisher") or ""
        pub_tokens = norm_tokens(publisher)
        if not pub_tokens or not (pub_tokens <= body_tokens):
            return False, (f"مضمون تقرير منقول عن «{publisher or '؟'}» ورد في المتن بلا "
                          "نسبة صريحة لاسم الناشر في صلب الجملة — القاعدة 9")
    return True, ""


# ─────────────── كيانات غير مسندة في المتن (بلاغ لا رفض) ────────────────
# طلب المراجعة على تشخيص "شو جيايين" (تشخيص Issue #373، الجولة السابعة
# عشرة، البند 2-ج): البرومبت وحده لا يكفي لمنع نقل تفصيلة من نص مصدر كامل
# لم تمرّ ببوابة السند (facts_block) — نفس الثغرة أثبتناها مرارًا في هذا
# الـ Issue لفحوصات أخرى (الأصالة، النسبة). فحص بنيوي لاحق لا حكم نموذج:
# يقارن كيانات المتن (أرقام، وتتابعات كلمات مضمون متتالية لا تظهر جذورها
# في أي مكان معروف) بمجمّع "المعروف" (الوقائع المسندة وكياناتها المصرَّحة
# والموجز والسؤال والرأي المنسوب) — لا يرفض المقال، فقط يُبلِغ في التقرير
# ليراجعه بشر (نفس نمط originality_notes/merged_statements/split_statements).

_ENTITY_MATCH_PREFIX_LEN = 4  # اشتقاقات الاسم: تطابق جذري لا حرفي فقط —
# "السوري" يُعامَل معروفًا إن كان "سوريا" معروفة (نفس أول 4 أحرف بعد
# التطبيع)، فلا يُبلَّغ عن صيغة نحوية مختلفة لاسم ورد فعلًا كأنه كيان جديد
_DIGIT_SEP_RE = re.compile(r"(?<=\d)[,٬](?=\d)")  # فواصل الآلاف (لاتينية/عربية)
_DIGIT_RUN_RE = re.compile(r"\d+")


def _extract_numbers(text: str) -> set[str]:
    """أرقام صرفة بعد حذف فواصل الآلاف — صيغ الأرقام المختلفة لنفس الرقم
    («500» و«500,000» لا تُخلَط، لكن «1,234» و«1234» تُطابَقان)."""
    normalized = _DIGIT_SEP_RE.sub("", text or "")
    return set(_DIGIT_RUN_RE.findall(normalized))


def _normalize_word(raw: str) -> str:
    word = _AR_MARKS.sub("", raw or "").lower().translate(_AR_TRANS)
    if word.startswith("ال") and len(word) > 4:
        word = word[2:]
    return word


# ─────────────── تسرّب مصطلحات بنية النظام إلى المتن (فحص بعدي) ─────────────
# طلب المراجعة (تشخيص Issue #373، تعليق العطل الثالث والعشرون): متن نُشر
# فعليًا انتهى بـ"بهذا تكون الوقائع المسندة قد أجابت..." — النموذج يتحدث عن
# آليته الداخلية للقارئ. القاعدة 11 في DRAFT_SYSTEM_TEMPLATE توجيه فقط؛
# البرومبت وحده أثبتنا مرارًا في هذا الـ Issue أنه لا يكفي (الأصالة، النسبة،
# الكيانات غير المسندة) — هذا فحص بنيوي لاحق: قائمة مغلقة صغيرة من مصطلحات
# النظام (لا قائمة مفتوحة تحتاج صيانة)، مطابَقة على النص بعد نفس تطبيع
# _normalize_word (تسقط التشكيل وتوحّد الهمزات) فلا يُفلت تصريف نحوي طفيف
# ("مسنَدة"/"مسندة") من الفحص.
_SYSTEM_JARGON_TERMS = [
    "الوقائع المسندة",  # normalize_word تُسقط "ال" فتطابق "وقائع مسندة" ضمنيًا
    "الوقائع المؤيدة",
    "السؤال المختار",
    "السؤال العنوان",
    "المصادر المستقلة",
    "مصدرين مستقلين",
    "بوابة الاتساق",
    "فحص الأصالة",
    "الموجز الملصق",
    "الوقائع المعطاة",
    "كفاية الأدلة",
    "الحد الأدنى من المصادر",
]


def _normalize_phrase(text: str) -> str:
    """نفس تطبيع _normalize_word لكل كلمة، مفصولة بمسافة واحدة — يجعل
    مطابقة مصطلح متعدد الكلمات غير حسّاسة للتشكيل/شكل الهمزة/عدد المسافات،
    دون حاجة لمطابقة حرفية صارمة (نظير منطق check_originality).

    التشكيل يُزال من النص كاملًا **قبل** التقطيع إلى كلمات لا بعده: _WORD_RE
    (\\w) لا يُطابق علامات التشكيل (تصنيف Unicode Mn)، فتشكيلة وسط كلمة
    ("المسنَدة") كانت لتقسمها _WORD_RE.findall إلى "المسن"+"دة" قبل أن تصل
    _normalize_word أصلًا — إزالة التشكيل أولًا تمنع هذا الانقسام الزائف."""
    stripped = _AR_MARKS.sub("", text or "")
    return " ".join(w for w in (_normalize_word(t) for t in _WORD_RE.findall(stripped)) if w)


_SYSTEM_JARGON_NORM = [(term, _normalize_phrase(term)) for term in _SYSTEM_JARGON_TERMS]


def _system_jargon_hits(text: str) -> list[str]:
    """قائمة المصطلحات (بصياغتها الأصلية) الموجودة فعليًا في text — فارغة
    يعني لا تسرّب. مصفوفة صغيرة مغلقة عمدًا (نظير GENERIC_SOURCE_PLURAL_HEADS)
    لا تصنيفًا لغويًا عامًا — نفس الحذر المتكرر في هذا الـ Issue من بناء
    أحكام لغوية هشة؛ قد تفوت صياغة مرادفة لم تُرصَد بعد، وهذا مقبول (فحص
    إضافي لا بديل عن القاعدة 11)، لا خطر إعفاء نسخ حقيقي كما في فحص الأصالة."""
    norm = _normalize_phrase(text)
    if not norm:
        return []
    return [term for term, needle in _SYSTEM_JARGON_NORM if needle and needle in norm]


def _build_jargon_avoid_note(hits: list[str]) -> str:
    quoted = "، ".join(f"«{h}»" for h in hits)
    return (f"\nمحاولة سابقة استعملت في المتن مصطلحات من بنية إنتاج المشروع الداخلية "
           f"لا من لغة الخبر ({quoted}) — المتن نص إخباري للقارئ، لا تقرير عن آلية "
           f"إنتاجه أو التحقق منه. أعد الصياغة بالكامل بلا أي إشارة إلى الوقائع بوصفها "
           f"«مسندة» أو «مؤيَّدة»، ولا إلى مصادرها بوصفها «مستقلة»، ولا أي تعليق على "
           f"كفاية الأدلة أو السؤال المختار — اكتب الخبر مباشرة كما يُكتب في أي مقال "
           f"صحفي عادي، بلا أي إشارة لعملية إنتاجه.\n")


# ملاحظة عطل مكتشَف أثناء بناء هذا الفلتر (بلا إصلاح في request._AR_STOP
# نفسها — نطاق هذه الجولة لا يمسّ norm_tokens العامة المستهلَكة في الصلة/
# بناء الاستعلام/فحص الأصالة، اتساقًا مع حذر متكرر في هذا الـ Issue من لمس
# دوال تطبيع مشتركة لإصلاح ضيق النطاق): كلمات _AR_STOP المكتوبة بألف مقصورة
# ("على") لا تُطابَق أبدًا فعليًا في norm_tokens نفسها — تُقارَن بعد
# request._AR_TRANS التي تحوّل "ى"←"ي" ("على"←"علي")، فتتسرّب كحرف مضمون
# في كل مكان يستهلك norm_tokens/_AR_STOP بصيغتها الحالية. أُصلح هنا محليًا
# فقط (مجموعة مُترجَمة مسبقًا) كي لا يُبلَّغ زورًا عن كل جملة تحوي "على".
_AR_STOP_NORM = frozenset(w.translate(_AR_TRANS) for w in _AR_STOP)


def _content_words(text: str) -> list[tuple[str, str]]:
    """[(الكلمة الخام، صيغتها المطبَّعة)] لكل كلمة مضمون — كلمات الوقف
    (STOPWORDS وrequest._AR_STOP، بعد تطبيع كليهما بنفس ترجمة الكلمة نفسها
    — انظر _AR_STOP_NORM أعلاه) تُسقَط فلا تكسر التجاور، نظير منطق نافذة
    verify_draft.check_originality."""
    out = []
    for raw in _WORD_RE.findall(text or ""):
        norm = _normalize_word(raw)
        if len(norm) > 2 and norm not in STOPWORDS and norm not in _AR_STOP_NORM:
            out.append((raw, norm))
    return out


def _word_known(norm: str, known: set[str]) -> bool:
    if norm in known:
        return True
    prefix = norm[:_ENTITY_MATCH_PREFIX_LEN]
    if len(prefix) < _ENTITY_MATCH_PREFIX_LEN:
        return False
    return any(k.startswith(prefix) for k in known)


def _known_entity_pool(grounded: list[dict], brief_text: str, question: str,
                       opinions: list[dict]) -> tuple[set[str], set[str]]:
    """كل ما يحق للمتن أن يستمد كياناته منه: الوقائع المسندة ونصوصها
    الحرفية، entities المستخرجة لكل واقعة (حقل بنيوي من مرحلة الاستخراج —
    لا نصًا حرًا)، اسم المتحدث/الناشر (تصريح/تقرير منقول — القاعدتان 8،9
    تُلزمان بذكرهما)، الموجز الأصلي، السؤال-العنوان، ونص الرأي المنسوب."""
    texts = [brief_text or "", question or ""]
    for f in grounded:
        texts.append(f.get("text") or "")
        texts.append(" ".join(str(e) for e in (f.get("entities") or [])))
        if f.get("speaker"):
            texts.append(str(f["speaker"]))
        if f.get("publisher"):
            texts.append(str(f["publisher"]))
    for o in opinions or []:
        texts.append(o.get("text") or "")
    joined = "\n".join(texts)
    return norm_tokens(joined), _extract_numbers(joined)


def _content_word_runs(text: str) -> list[list[tuple[str, str]]]:
    """قوائم كلمات المضمون المتجاورة فعليًا في النص — لا _content_words
    المسطّحة (التي كانت تُسقط كلمات الوقف من القائمة كليًا، فتلتصق كلمتا
    مضمون غير متجاورتين أصلًا في النص الخام؛ عطل مكتشَف من تقرير مراجعة
    حقيقي: «قادر العمل سواء» في المتن كانت أصلًا «قادر على العمل سواء» —
    «على» وقف أُسقط فقرَّب الكلمتين خطأً فبدتا تتابعًا صمّاء بلا معنى).
    كل قائمة فرعية هنا تتابع حقيقي متجاور (يقطعه أي وقف أو كلمة قصيرة)،
    فلا يمكن لكلمتين تفصل بينهما كلمة أخرى في النص أن تُحسبا متجاورتين."""
    runs: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    for raw in _WORD_RE.findall(text or ""):
        norm = _normalize_word(raw)
        if len(norm) > 2 and norm not in STOPWORDS and norm not in _AR_STOP_NORM:
            current.append((raw, norm))
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _phrase_in_source(run_norms: list[str], source_streams: list[list[str]]) -> bool:
    """هل يرد تتابع الكلمات المطبَّعة هذا متجاورًا حرفيًا في أحد تدفقات
    كلمات مضمون نصوص المصادر (المبنية بـ_content_words نفسها — إسقاط وقف
    متماثل في الجانبين، فلا يُطلَب تطابق حروف جر لم تنجُ من التطبيع)."""
    n = len(run_norms)
    for stream in source_streams:
        if n > len(stream):
            continue
        for i in range(len(stream) - n + 1):
            if stream[i:i + n] == run_norms:
                return True
    return False


# فئة مغلقة صغيرة لتمييز تتابع "تاريخ" عن غيره في تقرير _unsourced_entities
# (طلب المراجعة، مراجعة بشرية بعد أول نشر، البند 2: «حصره في اسم علم، رقم،
# تاريخ» — الأرقام مُصنَّفة أصلًا بذاتها؛ هذه الفئة تلتقط تواريخ مكتوبة
# بأسماء الأشهر لا بالأرقام وحدها، فتُوسَم "تاريخ" صراحة في التقرير بدل
# الرسالة العامة، بلا حكم لغوي إضافي — نفس نمط QUANTITY_ANCHOR_WORDS/
# NAME_LINK_ANCHOR_WORDS في verify_draft.py) — شهور ميلادية وهجرية وأدوات
# ربط تاريخ شائعة، مُطبَّعة بنفس _normalize_word المستعملة في هذه الوحدة
_DATE_ANCHOR_WORDS_RAW = {
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس",
    "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
    "كانون", "شباط", "آذار", "نيسان", "أيار", "حزيران", "تموز", "آب",
    "أيلول", "تشرين",
    "محرم", "صفر", "ربيع", "جمادى", "رجب", "شعبان", "رمضان", "شوال",
    "ذو", "القعدة", "الحجة",
    "عام", "سنة", "بتاريخ", "الموافق",
}
_DATE_ANCHOR_WORDS = frozenset(_normalize_word(w) for w in _DATE_ANCHOR_WORDS_RAW)


def _is_date_run(run_norms: list[str]) -> bool:
    """هل يحمل التتابع كلمة ربط تاريخ (شهر/سنة/أداة) — تسمية لا فحص إضافي،
    مطبَّقة بعد قرار الإبلاغ لا بدلًا منه."""
    return any(w in _DATE_ANCHOR_WORDS for w in run_norms)


def _unsourced_entities(post_body: str, grounded: list[dict], brief_text: str,
                        question: str, opinions: list[dict],
                        source_texts: list[str] | None = None, min_run: int = 2,
                        attribution_phrase: str = "") -> list[str]:
    """كيانات في المتن غائبة عن الوقائع المسندة وعن الموجز — بلاغ لا رفض.

    حصر النطاق (طلب المراجعة، تشخيص Issue #373، تعليق العطل الثاني
    والعشرون، البند 1 — الفحص السابق أُغرق بشظايا نحوية: «شركة مطار»،
    «قادر العمل سواء»، «حكومية تقدم مثل»، لا كيانات فعلية):

    - الأرقام: كما كانت — أي رقم في المتن غير وارد في المجمّع المعروف
      يُبلَّغ فردًا (تبقى بذاتها ضمن نطاق رقم/تاريخ).
    - الكلمات: تتابع كلمات مضمون **متجاور فعليًا في النص الخام** (عبر
      _content_word_runs — لا دمج عبر كلمات وقف مُسقَطة كما في العطل
      المذكور أعلاه) يُبلَّغ فقط حين (1) يبلغ طوله `min_run` كلمات فأكثر
      **و(2)** يرد `source_texts` حين مُمرَّرة فعليًا كتتابع متجاور حرفيًا
      في نص مصدر مقروء واحد على الأقل — إثبات بنيوي أنه فعلًا "تفصيلة
      منقولة من نص مصدر لم تمرّ ببوابة السند" (نمط «شو جيايين» الفعلي
      الذي بُني له هذا الفحص)، لا مجرد اختيار كلمات مختلف عن الموجز في
      إعادة صياغة مشروعة (القاعدة 5 تُلزم بإعادة صياغة كاملة، فتتابع كلمتين
      غير معروفتين لكن لا أصل له في أي مصدر مقروء غالبًا أسلوب الكاتب لا
      كيانًا مُختلَقًا). `source_texts=None` (لا بيانات مصادر متاحة، مثل
      نداء مباشر بلا سياق تشغيلة كاملة) يُبقي السلوك القديم (طول فقط) —
      كل نداء الإنتاج الفعلي يمرّرها فعليًا فيطبَّق الشرطان معًا.

    اسم الناشر/المتحدث (publisher/speaker) يبقى معفى عبر _known_entity_pool
    كما كان؛ صيغة نسبة الرأي الثابتة (article.opinion_attribution_phrase)
    تُضاف الآن أيضًا إلى المجمّع المعروف صراحة — كلماتها («وترى الصفحة أن»)
    ليست كيانًا، ولا ينبغي أن تُبلَّغ لمجرد أنها لا تظهر في نص الموجز/الرأي
    نفسه.

    الفئات الثلاث المطلوبة (طلب المراجعة، مراجعة بشرية بعد أول نشر، البند
    2 — «حصره في اسم علم، رقم، تاريخ»): رقم (كما كان)، تاريخ (تتابع يحمل
    كلمة ربط تاريخ — شهر/سنة/أداة، عبر _is_date_run، يُوسَم "تاريخ" صراحة
    في نص البلاغ لا الرسالة العامة)، واسم علم (الباقي). العربية بلا حالة
    أحرف (Capitalization)، فلا إشارة بنيوية رخيصة تُميّز اسم علم عن اسم
    عام بيقين — بناء تصنيف لغوي إضافي هنا (مثل معياري "تعريف/خبر" و"مصطلح
    رسمي" المرفوضين مرارًا في هذا الـ Issue) خطر مرفوض بنفس المنطق. الحارس
    الفعلي بدلًا من ذلك بنيوي محض: طول الحد الأدنى (min_run) **و**الورود
    الحرفي المتجاور في نص مصدر مقروء فعلًا (_phrase_in_source) — وهو تحديدًا
    ما أزال الشظايا النحوية المُبلَّغة («شركة مطار»، «قادر العمل سواء»،
    «حكومية تقدم مثل») في الجولة التي بنت هذا الفحص: تلك كانت نتاج عطل
    تجاور (كلمات غير متجاورة فعليًا في النص التصقت بالخطأ) لا غياب تصنيف
    لغوي، وقد أُصلح العطل بنيويًا (_content_word_runs) لا بتضييق الفئة. قد
    يُبلَّغ أحيانًا عن تفصيلة وصفية منقولة حرفيًا من مصدر لا اسم علم بعينه؛
    هذا مقصود ومقبول لأنه بلاغ للمراجعة البشرية لا رفض آلي."""
    known_words, known_numbers = _known_entity_pool(grounded, brief_text, question, opinions)
    if attribution_phrase:
        known_words = known_words | norm_tokens(attribution_phrase)

    body_numbers = _extract_numbers(post_body)
    notes = [f"رقم «{n}» غير وارد في الوقائع المسندة ولا في الموجز"
            for n in sorted(body_numbers - known_numbers)]

    source_streams = None
    if source_texts is not None:
        source_streams = [[norm for _, norm in _content_words(t)] for t in source_texts if t]

    for run in _content_word_runs(post_body):
        i, n = 0, len(run)
        while i < n:
            if _word_known(run[i][1], known_words):
                i += 1
                continue
            j = i
            while j < n and not _word_known(run[j][1], known_words):
                j += 1
            if j - i >= min_run:
                run_norms = [w[1] for w in run[i:j]]
                if source_streams is None or _phrase_in_source(run_norms, source_streams):
                    phrase = " ".join(w[0] for w in run[i:j])
                    label = "تاريخ" if _is_date_run(run_norms) else "اسم"
                    notes.append(f"{label} «{phrase}» غير وارد في الوقائع المسندة ولا في الموجز")
            i = j
    return notes


# ─────────── استبعاد إعادات نشر الموجز الملصق (طلب المراجعة، أولوية) ────────
# النسخة المعاد نشرها من الموجز الملصق تُحتسب اليوم "مصدرًا مستقلًا" في
# _support_sources وفحص الأصالة معًا (all_read_docs → extra_docs) — خلل في
# السند لا في الأصالة: نصٌّ واحد (الموجز نفسه) يبدو مصدرين حين يعيد ناشر
# آخر نشره حرفيًا ويظهر في نتائج البحث. الكشف بتتابع كلمات متجاور طويل فعليًا
# (لا تشابه كيسي/Jaccard — تعليل تشخيص Issue #373، تعليق العطل الحادي
# والعشرون، البند 1: تشابه المفردات وحده يرتفع زورًا بين تغطيتين مستقلتين
# لنفس الحدث تشتركان في نفس الكيانات، بخلاف تتابع متجاور طويل لا يقع صدفة).


def _longest_shared_run(a_words: list[str], b_words: list[str], min_len: int) -> int:
    """أطول تتابع كلمات متجاور مشترك بين القائمتين، إن بلغ min_len على
    الأقل — يبحث بنافذة ثابتة الطول (n=min_len) للكشف السريع، ثم يوسّع من
    الطرفين عند أول تطابق ليقدّم رقمًا فعليًا (لا مجرد ">=min_len") يُعرض في
    trail فيُضبَط الحد لاحقًا على أدلة حقيقية لا تخمين. يعيد 0 حين لا تتابع
    بهذا الطول أصلًا."""
    n = min_len
    if n <= 0 or len(a_words) < n or len(b_words) < n:
        return 0
    positions: dict[tuple[str, ...], list[int]] = {}
    for i in range(len(a_words) - n + 1):
        positions.setdefault(tuple(a_words[i:i + n]), []).append(i)
    for j in range(len(b_words) - n + 1):
        key = tuple(b_words[j:j + n])
        for i in positions.get(key, []):
            left = 0
            while (i - left - 1 >= 0 and j - left - 1 >= 0
                   and a_words[i - left - 1] == b_words[j - left - 1]):
                left += 1
            right = 0
            while (i + n + right < len(a_words) and j + n + right < len(b_words)
                   and a_words[i + n + right] == b_words[j + n + right]):
                right += 1
            return n + left + right
    return 0


def _reprint_filter(body_words: list[str], min_shared: int):
    """يبني دالّة تصفية مقيَّدة بـ body_words/min_shared (كلاهما ثابت طوال
    التشغيلة) — تُستهلَك حصرًا داخل _cached_search أدناه (طلب المراجعة: لا
    مراحل تسمية/سند/سؤال، التي تبحث بأدوات ونطاق مختلفَين تمامًا). تعيد
    (المستبقاة, المستبعدة) — المستبعدة قوائم {"name","link","shared_words"}
    للتبليغ الصريح في trail، لا استبعاد صامت."""
    def _filter(docs):
        if not body_words or min_shared <= 0:
            return docs, []
        kept, excluded = [], []
        for d in docs:
            shared = _longest_shared_run(
                body_words, verify_draft._normalized_words(d.get("text", "")), min_shared)
            if shared >= min_shared:
                excluded.append({"name": d.get("name", ""), "link": d.get("link", ""),
                                 "shared_words": shared})
            else:
                kept.append(d)
        return kept, excluded
    return _filter


# ─────── فجوات دمج التصريح (طلب المراجعة، تعليق العطل الرابع والعشرون) ──────
# شاهد: تصريح بايكرآر التركي دُمج من أربع جمل (merged_excerpts) لكن نص
# الواقعة المدموج (text) انكمش إلى الجملة الأولى وحدها — رقم 90% ووصف
# الشركة وريادة المسيّرات (الجمل 2-4) سقطت من text رغم ظهورها في
# merged_excerpts. البرومبت (WRITEUP_EXTRACT_SYSTEM أعلاه) يُلزم أصلًا بأن
# "نصه يلخّص مضمون التصريح بأجزائه معًا لا جزءًا واحدًا منه" — الانكماش هنا
# فشل اتّباع تعليمات من النموذج (تذبذب لا سبيل لضبطه، انظر ملاحظة
# temperature في CLAUDE.md)، لا عطل كود. فحص بنيوي لاحق لا حكم لغوي: تبليغ
# لا رفض، نظير originality_notes/unsourced_entities.
def _merged_statement_gaps(text: str, merged_excerpts: list) -> list[str]:
    """أي جملة مصدر (merged_excerpts) لا يظهر لها أثر في نص التصريح المدموج
    (text) — تبليغ لا رفض. إشارتان بلا حكم لغوي:
    - رقم ورد في الجملة المصدر ولم يرد في النص المدموج (الأرقام تعبر
      الترجمة سليمة بصرف النظر عن لغة الموجز — هي الإشارة الأقوى هنا،
      وهي بالضبط ما سقط في الشاهد المُبلَّغ).
    - تداخل كلمات مضمون (norm_tokens) بين الجملة المصدر والنص المدموج،
      لكن **فقط حين تشترك الجملتان الأبجدية نفسها** (كلتاهما عربية أو
      كلتاهما غير عربية): جملة أجنبية مقابل نص عربي مُترجَم لن تشترك
      ألفاظًا حرفيًا حتى لو نُقل مضمونها كاملًا (ترجمة لا نسخ)، فمقارنة
      الكلمات عبر لغتين مختلفتين مضلِّلة — تُسقَط لتفادي فجوات كاذبة على
      كل جملة في موجز أجنبي (تشخيص Issue #373، الشاهد التركي الرابع).
      عتبة التداخل ≥2 كلمة (لا كلمة واحدة تكفي) حين تحمل الجملة كلمتي
      مضمون فأكثر: كل الجمل المُدمَجة في تصريح واحد تشترك عادة اسم
      المتحدث نفسه (شرط الدمج أصلًا "متحدث واحد بعينه") — تطابق لفظي على
      الاسم وحده لا يثبت أن *مضمون* الجملة وصل النص المدموج، فيُخفي فجوة
      حقيقية (جملة سقط مضمونها كليًا لكن نجت من الفحص لمجرد ذكر الاسم
      نفسه مصادفة). جملة بكلمة مضمون واحدة فقط (بعد إسقاط الاسم لا معنى
      لعتبة أعلى من توفّرها) تكتفي بتلك الكلمة الواحدة."""
    text = text or ""
    text_numbers = _extract_numbers(text)
    text_words = norm_tokens(text)
    text_is_arabic = has_arabic(text)
    gaps: list[str] = []
    for excerpt in merged_excerpts or []:
        excerpt = (excerpt or "").strip()
        if not excerpt:
            continue
        if _extract_numbers(excerpt) - text_numbers:
            gaps.append(excerpt)
            continue
        if has_arabic(excerpt) != text_is_arabic:
            continue
        ex_words = norm_tokens(excerpt)
        if not ex_words:
            continue
        needed = min(2, len(ex_words))
        if len(ex_words & text_words) < needed:
            gaps.append(excerpt)
    return gaps


# ──────────────────────────── الأنبوب الكامل ────────────────────────────


def _new_outcome() -> dict:
    return {"produced": False, "reason": "", "question": "", "dropped": [],
           "sources": [], "unanswered": [], "answered_questions": [], "diffs": [],
           "trail": [], "draft_id": None, "grounded_count": 0,
           "image_source_name": None, "image_source_link": None,
           "image_report": {}, "opinion_note": "", "originality_notes": [],
           "merged_statements": [], "split_statements": [], "report_statements": [],
           "unsourced_entities": [],
           # وقائع من المصادر (لا الموجز فقط) — طلب المراجعة، انظر توثيق
           # _extract_source_facts/_source_fact_duplicate_index. source_origin_facts:
           # ما دخل المقال فعليًا بوسم origin="source" (يظهر في التقرير
           # ليراجعه المستخدم — البند 2)؛ source_facts_summary: عدد ما
           # استُخرج/اندمج/أُضيف (البند 5 — أثر ظاهر، لا ميزة صامتة)
           "source_origin_facts": [],
           "source_facts_summary": {"extracted": 0, "merged": 0, "added": 0},
           "originality_retry": {"attempted": False, "succeeded": False, "offending_phrase": ""},
           "jargon_retry": {"attempted": False, "succeeded": False, "detected": [], "remaining": []}}


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
    # عتبة سند مستقلة لـ"تقرير منقول" — نظير min_confirm أعلاه لكنها 1 لا 2
    # (تشخيص Issue #373، الجولة السادسة عشرة؛ انظر توثيق article.yaml)
    report_min_confirm = int(acfg.get("report_min_confirm", 1))
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
    # "تصريح" و"تقرير منقول" وقائع قابلة للتحقق كـ"واقعة" تمامًا — الفارق
    # الوحيد نظام حكم السند وعتبته (_support_sources(is_statement=True)
    # للأول، is_report=True بعتبة report_min_confirm للثاني — تشخيص Issue
    # #373، الجولتان الثالثة عشرة والسادسة عشرة)، لا مكانها هنا (لا تُعامَل
    # كرأي)
    facts_raw = [s for s in statements
                if s["kind"] in ("واقعة", "تصريح", "تقرير منقول")][:max_statements]
    opinions = [s for s in statements if s["kind"] == "رأي"]
    topic = str(extracted.get("topic") or "")

    # تبليغ الدمج لا منعه (البند 1): كل عنصر "تصريح" يذكر المتحدث وجمل
    # الموجز الحرفية التي دُمجت فيه — يظهر في التقرير بصرف النظر عن مصير
    # سنده لاحقًا، فيراجع المستخدم البشري أي دمج زائف (متحدثان مختلفان أو
    # مناسبتان مختلفتان دُمجا خطأً) ويصححه، بدل منع الدمج بحكم آلي هش.
    # part_support يُملأ لاحقًا داخل حلقة الوقائع (يحتاج docs المقروءة
    # فعليًا) — entry هنا dict مرجعي يُضاف مرة واحدة إلى القائمة ويُعدَّل
    # من داخل الحلقة لاحقًا لا يُعاد بناؤه (طلب المراجعة، معيار الأغلبية:
    # "اعرض في التقرير أي الأجزاء أيّدها كل مصدر وأيها لم يُؤيَّد")
    statement_reports: dict[int, dict] = {}
    outcome["merged_statements"] = []
    for s in facts_raw:
        if s["kind"] != "تصريح":
            continue
        entry = {"speaker": s["speaker"] or "؟", "text": s["text"],
                 "merged_excerpts": s["merged_excerpts"],
                 "gaps": _merged_statement_gaps(s["text"], s["merged_excerpts"]),
                 "part_support": []}
        statement_reports[id(s)] = entry
        outcome["merged_statements"].append(entry)

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
    # صور مرشَّحة من وثائق استُبعدت كإعادة نشر للموجز عبر التشغيلة كلها
    # (طلب المراجعة، تشخيص Issue #373، مراجعة بشرية بعد أول نشر، البند 1):
    # الاستبعاد يخصّ عدّ السند لا صلاحية الصورة — تُستهلَك كاحتياط ثانٍ عند
    # بناء صورة المسودة أدناه، فقط حين لا صورة من مصدر مسنِد فعليًا
    reprint_image_pool: list[dict] = []

    # ذاكرة استعلامات هذا التشغيل حصرًا لحلقة الوقائع أدناه (تشخيص Issue
    # #373، تعليق العطل العشرون، البند 1): وقائع متعددة تشترك في نفس
    # الكيانات (موجز يدور حول شخص واحد مثلًا) تبني نفس نص الاستعلام حرفيًا
    # عبر build_query_for_claim — بحث وقراءة مستقلَّان لكل واحدة منهما
    # يُعيدان نفس النتائج والمصادر حرفيًا، فهو إهدار استدعاءات مؤكَّد لا
    # احتمالي. المفتاح (query, unrestricted, relevance_text) لا query وحده:
    # relevance_text تُبنى من نفس entities التي بُني منها الاستعلام
    # (_entities_text) فتتطابق كلما تطابق الاستعلام فعليًا، لكن تمييزها
    # صراحة يمنع أي تطابق عرَضي مستقبلي إن تغيّر أحدهما بمعزل عن الآخر.
    # الحكم على السند يبقى مستقلًا لكل واقعة رغم مشاركة الوثائق —
    # _support_sources تُستدعى بنص كل واقعة بعينه خارج هذه الدالة، لا
    # تُخزَّن هنا
    search_cache: dict[tuple, tuple] = {}
    # استبعاد إعادات نشر الموجز الملصق (طلب المراجعة، أولوية — انظر
    # _longest_shared_run/_reprint_filter أعلاه): body_words تُحسب مرة واحدة
    # لكامل التشغيلة — لا تتغيّر بين استعلامات
    body_words = verify_draft._normalized_words(body)
    reprint_min_shared = int(acfg.get("brief_reprint_min_shared_words", 40))
    _filter_reprints = _reprint_filter(body_words, reprint_min_shared)

    def _cached_search(query: str, unrestricted: bool, relevance_text: str):
        key = (query, bool(unrestricted), relevance_text)
        if key in search_cache:
            ranked, docs, basis, excluded = search_cache[key]
            return ranked, docs, basis, True, excluded
        ranked = evidence.search(query, cfg, days, unrestricted=unrestricted)
        raw_docs, basis = evidence.gather_evidence(ranked, cfg, relevance_text)
        kept, excluded = _filter_reprints(raw_docs)
        docs = evidence._evidence_docs(kept, getattr(raw_docs, "fetch_failures", []),
                                       getattr(raw_docs, "top_candidates", []))
        search_cache[key] = (ranked, docs, basis, excluded)
        return ranked, docs, basis, False, excluded

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
            # اسم المتحدث (تصريح) أو الناشر (تقرير منقول) يدخل الاستعلام
            # إلزامًا بلا مزاحمة من كيانات أخرى (طلب المراجعة، تشخيص Issue
            # #373، تعليق العطل الثاني والعشرون، البند 1): entities لا تتضمّن
            # بالضرورة اسم المتحدث/الناشر (يُستخرَج في حقل speaker/publisher
            # منفصل) — شاهد فعلي (تصريح بايراكتار/Baykar): استعلام بلا
            # "Selçuk Bayraktar" (اسم العلم الذي تُفهرس به التغطية فعليًا)
            # رجع صفر نتائج، بينما تشغيلة أخرى بالاسم كاملًا وجدت 7. يُبنى
            # الاسم الإلزامي في مقدمة نص الاستعلام فيُختار قبل أي كيان آخر
            # (build_query تختار بترتيب الورود حتى الحد الأقصى) — دخول
            # مضمون لا مجرد مرشَّح ضمن الكيانات الأخرى
            mandatory_name = _fact_mandatory_query_prefix(f)
            entities_text = evidence._entities_text(f)
            query_text = (f"{mandatory_name} {entities_text}".strip() if mandatory_name
                         else (entities_text or f["text"]))
            query = evidence.build_query(query_text, query_max_words)
            relevance_text = query_text
            ranked, docs, basis, reused_query, excluded_reprints = _cached_search(
                query, f.get("is_reference", False), relevance_text)
            all_read_docs.extend(docs)
            reprint_image_pool.extend(_reprint_fallback_images(excluded_reprints, ranked))
            # "تصريح" (الجولة الثالثة عشرة، مُعدَّل بمعيار الأغلبية أدناه):
            # فحص المضمون لا وقوع المقابلة وحده، جزءًا جزءًا لا حكمًا شموليًا
            # واحدًا — انظر توثيق _support_statement_parts/_statement_majority
            # أعلاه. "تقرير منقول" (الجولة السادسة عشرة، بلا تغيير هنا):
            # is_report تختار REPORT_SUPPORT_SYSTEM **وعتبة report_min_confirm
            # المستقلة** (1 لا 2) — شرط الهوية المزدوج البنيوي يُطبَّق داخل
            # _support_sources نفسها (_report_identity_kind) قبل أي حكم نموذج
            is_statement = f["kind"] == "تصريح"
            is_report = f["kind"] == "تقرير منقول"
            fact_min_confirm = report_min_confirm if is_report else min_confirm
            # ما لم يُؤيَّد لا يدخل المتن (طلب المراجعة، معيار الأغلبية):
            # أجزاء merged_excerpts التي أيّدها مصدر واحد فأكثر — هذه وحدها
            # تُستعمل نصًّا للواقعة عند الصياغة لاحقًا إن اجتاز التصريح ككل،
            # لا التصريح المدموج كاملًا. تبقى [] لغير التصريح (fact_text
            # الأصلي يُستعمَل كما هو).
            included_excerpts: list[str] = []
            if is_statement:
                # عنصر بلا merged_excerpts فعلية (لم يُدمَج من أكثر من جملة)
                # يُعامَل كجزء واحد هو نصه الكامل — نفس أثر الحكم الشمولي
                # القديم بالضبط لهذه الحالة (N=1، الأغلبية=1 أي "أيّد الجزء
                # الوحيد")، فلا انحدار على التصريحات غير المُدمَجة فعليًا
                statement_parts = f.get("merged_excerpts") or [f["text"]]
                parts_support = (_support_statement_parts(statement_parts, docs, cfg)
                                 if docs else _PartSupportList())
                fact_call_error = getattr(parts_support, "call_error", None)
                if fact_call_error:
                    fact_mentioned: set[str] = set()
                    supporting = _ModelCallList()
                else:
                    maj_supporting, fact_mentioned, included_excerpts = _statement_majority(
                        statement_parts, parts_support)
                    supporting = _ModelCallList(maj_supporting)
                # التبليغ (طلب المراجعة): أي الأجزاء أيّدها كل مصدر وأيها لم
                # يُؤيَّد — نظير merged_statements، بصرف النظر عن مصير
                # التصريح لاحقًا (فشل تقني يترك القائمة فارغة، لا يُخترع بلاغ)
                report_entry = statement_reports.get(id(f))
                if report_entry is not None and not fact_call_error:
                    report_entry["part_support"] = [
                        {"excerpt": ex, "supporting": sup}
                        for ex, sup in zip_longest(statement_parts, parts_support,
                                                   fillvalue=[])
                    ]
            else:
                supporting = (_support_sources(f["text"], docs, cfg, is_statement=False,
                                              is_report=is_report, publisher=f.get("publisher", ""))
                             if docs else [])
                fact_call_error = getattr(supporting, "call_error", None)
                # mentioned (طلب المراجعة، تشخيص Issue #373، حالة بايراكتار
                # الرابعة): يفصل "لم يُقرأ نص يناقش الموضوع إطلاقًا" (عطل بحث
                # محتمل) عن "قُرئ نص يناقشه ولم يطابق مضمونه" (عطل حكم) —
                # تمييز كان يحتاج جولة تشخيص كاملة في كل مرة قبل هذا الحقل
                fact_mentioned = set(getattr(supporting, "mentioned", []) or [])
            unique = set(supporting)

            def _support_gap_detail() -> str:
                if not fact_mentioned:
                    return "لم يذكر أي من المصادر المقروءة الموضوع إطلاقًا"
                if unique:
                    return (f"ذكره {len(fact_mentioned)} مصدر وطابق مضمونه "
                            f"{len(unique)} منها فقط")
                return f"ذكره {len(fact_mentioned)} مصدر لكن لم يطابق مضمونه أيٌّ منها"

            stage = "تقرير" if is_report else ("تصريح" if is_statement else "واقعة")
            outcome_text = (f"⚠️ فشل نداء النموذج تقنيًا: {fact_call_error}"
                            if fact_call_error else
                            f"مسندة بـ{len(unique)} مصدر مستقل"
                            if len(unique) >= fact_min_confirm
                            else f"سند غير كافٍ ({len(unique)}/{fact_min_confirm}) — "
                                 f"{_support_gap_detail()}")
            if reused_query:
                # الشفافية أهم من اختصار السجل (طلب المراجعة، تشخيص Issue
                # #373، تعليق العطل العشرون، البند 1): لا يُحذف السطر رغم
                # عدم إجراء بحث/قراءة جديدين — يبقى ظاهرًا مع إشارة صريحة
                # أن نتائجه مُعادة من استعلام سابق بنفس النص حرفيًا
                outcome_text = f"🔁 مُعاد من استعلام سابق — {outcome_text}"
            if excluded_reprints:
                outcome_text = (f"🗞️ استُبعدت {len(excluded_reprints)} نسخة معاد "
                                f"نشرها من الموجز — {outcome_text}")
            # judged_by (طلب المراجعة، تعليق العطل الرابع والعشرون بعد ٢٤:
            # "بعد الدمج، النتيجة لم تتغير ولا أثر لمعيار الأغلبية"): بلاغ
            # بنيوي صريح لا مُستنتَج من stage — يُحسب مباشرة من فرع الكود
            # المُنفَّذ فعليًا (is_statement) لا من تصنيف "تصريح" نفسه، فلو
            # ارتدّ الحكم يومًا إلى SUPPORT_SYSTEM الشمولي (خطأ برمجي، أو
            # فرع is_statement توقّف عن التفعيل) لظهر "شمولي" هنا رغم أن
            # stage لا يزال "تصريح" — تناقض ظاهر في التقرير نفسه، لا حاجة
            # لإعادة تشخيص كاملة (كما وقع فعليًا حين ظُنّ المعيار غير مُفعَّل
            # بينما لم يكن كود المعيار قد دُمج أصلًا إلى main)
            judged_by = "أجزاء (معيار الأغلبية)" if is_statement else "شمولي"
            trail.append({"stage": stage,
                          "query": query, "basis": basis,
                          "sources": [d["name"] for d in docs],
                          "raw_count": getattr(ranked, "raw_count", None),
                          "matched_count": getattr(ranked, "matched_count", None),
                          "fetch_failures": getattr(docs, "fetch_failures", []),
                          "top_candidates": getattr(docs, "top_candidates", []),
                          "excluded_reprints": excluded_reprints,
                          "call_error": fact_call_error,
                          "reused_query": reused_query,
                          "judged_by": judged_by,
                          "outcome": outcome_text})
            if len(unique) < fact_min_confirm:
                if fact_call_error:
                    drop_reason = f"⚠️ فشل نداء الحكم على السند تقنيًا: {fact_call_error}"
                elif excluded_reprints:
                    # تمييز صريح (طلب المراجعة، البند 3): هبوط السند بعد
                    # استبعاد إعادات النشر صحيح لا انحدار — لكن رسالته يجب
                    # أن تُميَّز عن الرسالة العامة، وإلا يبدو عطل بحث كما
                    # ظُنّ مرارًا في هذا الـ Issue قبل أن يتأكد السبب الحقيقي
                    drop_reason = (f"سند غير كافٍ بعد استبعاد إعادات نشر الموجز "
                                   f"({len(unique)} من {fact_min_confirm} مصادر مستقلة "
                                   f"مطلوبة؛ استُبعدت {len(excluded_reprints)} نسخة "
                                   "معاد نشرها من عدّ الاستقلالية)")
                else:
                    drop_reason = (f"سند غير كافٍ ({len(unique)} من {fact_min_confirm} "
                                   f"مصادر مستقلة مطلوبة) — {_support_gap_detail()}")
                dropped.append({"text": f["text"], "reason": drop_reason})
                continue
            fact_sources = _grounded_sources(supporting, docs, ranked)
            # ما لم يُؤيَّد لا يدخل المتن (طلب المراجعة): التصريح قد يجتاز
            # العتبة بأغلبية عبر مصادر أيّدت أجزاء مختلفة منه، لكن جزءًا لم
            # يؤيِّده أي مصدر يبقى خارج ما يصل الصياغة — لا التصريح كاملًا
            # بصرف النظر عن اجتيازه ككل (included_excerpts فارغة لغير
            # التصريح، فيبقى f["text"] الأصلي كما هو دومًا لتلك الحالات)
            fact_text = ("؛ ".join(included_excerpts) if is_statement and included_excerpts
                        else f["text"])
            grounded.append({**f, "text": fact_text, "sources": fact_sources})

        for s in grounded[-1]["sources"]:
            if not any(s["name"] == x["name"] for x in sources_seen):
                sources_seen.append({"name": s["name"], "link": s["link"]})

    # قسم مراجعة "تقارير مُرحَّلة عن ناشر واحد" (طلب المراجعة البند 2،
    # تشخيص Issue #373، الجولة السادسة عشرة): يظهر لكل "تقرير منقول" مسنَد
    # فعليًا (بعد الحلقة أعلاه — الهوية غير قابلة للحساب قبل القراءة) اسم
    # ناشره ومصدره المسنِد، مع تمييز صريح إن كانت الوثيقة نفسها من الناشر
    # (original) أو ناقلًا يسمّيه (carrier) — ليراجعها المستخدم البشري كما
    # في merged_statements/split_statements أعلاه
    outcome["report_statements"] = [
        {"publisher": f.get("publisher") or "؟", "text": f["text"],
         "sources": [{"name": s["name"], "link": s.get("link", ""),
                      "kind": _report_identity_kind(f.get("publisher", ""), s, cfg) or "؟"}
                     for s in f.get("sources", [])]}
        for f in grounded if f.get("kind") == "تقرير منقول"
    ]

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

    # كل ما دخل grounded حتى هنا مصدره الموجز (وقائعه أو أسئلته) — يُوسَم
    # صراحة قبل مرحلة استخراج وقائع المصادر أدناه كي يبقى origin: "brief"
    # مميَّزًا عن origin: "source" في كل مكان يقرأ grounded لاحقًا (التقرير،
    # الصياغة)
    for g in grounded:
        g.setdefault("origin", "brief")

    # وقائع من المصادر (لا الموجز فقط، طلب المراجعة) — انظر توثيق
    # _extract_source_facts/_source_fact_duplicate_index أعلاه للتصميم
    # الكامل. all_read_docs مكتملة هنا (كل مراحل واقعة/تسمية/سند/سؤال قرأت
    # منها بالفعل)، فهذه المرحلة لا تبحث من جديد عن مصادر — تستثمر ما قُرئ
    # أصلًا لتكتشف وقائع لم يذكرها الموجز، ثم تبحث لها سندًا مستقلًا كأي
    # واقعة عادية إن نجت من الدمج ضد التكرار.
    # يشحن مُعطَّلًا افتراضيًا (source_extract_enabled=False) حتى بعد
    # تشغيل حي فعلي يُثبت سلوكه — نفس قرار article.include_opinion سابقًا
    # في هذا الـ Issue (يُضبط يدويًا في config.yaml بعد التحقق)، لا تراجعًا
    # عن التصميم: مرحلة جديدة تستدعي النموذج مرتين إضافيتين لكل واقعة
    # مستخرَجة (استخراج + دمج) تستحق تشغيلًا حيًّا واحدًا على الأقل قبل أن
    # تصبح افتراضية على كل تشغيلة إنتاج.
    source_extract_enabled = bool(acfg.get("source_extract_enabled", False))
    source_max_docs = int(acfg.get("source_extract_max_docs", 8))
    extracted_source_count = 0
    merged_source_count = 0
    if source_extract_enabled and all_read_docs:
        wanted_tokens: set[str] = set(norm_tokens(topic))
        for s in facts_raw + questions_from_brief:
            for e in s.get("entities") or []:
                wanted_tokens |= norm_tokens(e)
        ranked_docs = _rank_docs_for_source_extract(all_read_docs, wanted_tokens, cfg,
                                                     source_max_docs)
        brief_texts = [g["text"] for g in grounded]
        extracted = _extract_source_facts(topic, brief_texts, ranked_docs, cfg)
        extract_call_error = getattr(extracted, "call_error", None)
        extracted_source_count = 0 if extract_call_error else len(extracted)
        trail.append({"stage": "مصادر", "query": "", "basis": "",
                      "sources": [d["name"] for d in ranked_docs],
                      "raw_count": None, "matched_count": None,
                      "fetch_failures": [], "top_candidates": [],
                      "call_error": extract_call_error,
                      "outcome": (f"⚠️ فشل نداء النموذج تقنيًا: {extract_call_error}"
                                 if extract_call_error else
                                 f"{extracted_source_count} واقعة إضافية مستخرَجة من "
                                 f"{len(ranked_docs)} وثيقة مقروءة")})
        for sf in extracted:
            dup = _source_fact_duplicate_index(sf["text"], brief_texts, cfg)
            if dup["call_error"] or dup["duplicate"]:
                if dup["duplicate"]:
                    merged_source_count += 1
                continue
            query = evidence.build_query_for_claim(sf, query_max_words)
            relevance_text = evidence._entities_text(sf) or sf["text"]
            ranked, docs, basis, reused_query, excluded_reprints = _cached_search(
                query, False, relevance_text)
            all_read_docs.extend(docs)
            supporting = _support_sources(sf["text"], docs, cfg) if docs else []
            call_error = getattr(supporting, "call_error", None)
            unique = set(supporting)
            trail.append({"stage": "واقعة (من المصادر)", "query": query, "basis": basis,
                          "sources": [d["name"] for d in docs],
                          "raw_count": getattr(ranked, "raw_count", None),
                          "matched_count": getattr(ranked, "matched_count", None),
                          "fetch_failures": getattr(docs, "fetch_failures", []),
                          "top_candidates": getattr(docs, "top_candidates", []),
                          "excluded_reprints": excluded_reprints,
                          "call_error": call_error, "reused_query": reused_query,
                          "outcome": (f"⚠️ فشل نداء النموذج تقنيًا: {call_error}"
                                     if call_error else
                                     f"مسندة بـ{len(unique)} مصدر مستقل"
                                     if len(unique) >= min_confirm
                                     else f"سند غير كافٍ ({len(unique)}/{min_confirm})")})
            if len(unique) < min_confirm:
                continue
            fact_sources = _grounded_sources(supporting, docs, ranked)
            grounded.append({"text": sf["text"], "kind": "واقعة", "entities": sf["entities"],
                            "is_unnamed_event": False, "is_reference": False,
                            "speaker": "", "merged_excerpts": [], "split_from": "",
                            "publisher": "", "origin": "source", "sources": fact_sources})
            # واقعة مصدر أُضيفت للتو تدخل قائمة المقارنة أيضًا — واقعتان من
            # المصادر تصفان نفس الحدث في تشغيلة واحدة يجب ألا تُعدّا مرتين
            # بالمثل، لا وقائع الموجز الأصلية فقط
            brief_texts.append(sf["text"])
            for s in fact_sources:
                if not any(s["name"] == x["name"] for x in sources_seen):
                    sources_seen.append({"name": s["name"], "link": s["link"]})

    outcome["source_facts_summary"] = {
        "extracted": extracted_source_count, "merged": merged_source_count,
        "added": sum(1 for g in grounded if g.get("origin") == "source"),
    }
    outcome["source_origin_facts"] = [
        {"text": g["text"],
         "sources": [{"name": s["name"], "link": s.get("link", "")} for s in g.get("sources", [])]}
        for g in grounded if g.get("origin") == "source"
    ]

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
    max_shared = int(acfg.get("max_shared_run_words", 7))
    repeat_min_count = int(acfg.get("repeat_within_source_min_count", 2))
    trim_min_core = int(acfg.get("trim_min_core", 5))

    def _draft_text_of(candidate: dict) -> str:
        return "\n".join(filter(None, [
            candidate["image_headline"], candidate["post_title"], candidate["post_body"],
        ]))

    def _check_orig(candidate_text: str):
        return verify_draft._check_originality_full(
            candidate_text, body, source_docs, max_shared,
            repeat_min_count=repeat_min_count, extra_docs=extra_docs, min_core=trim_min_core)

    draft_text = _draft_text_of(written)
    ok_orig, orig_reason, originality_notes, offending = _check_orig(draft_text)

    # محاولة صياغة ثانية واحدة فقط عند رفض فحص الأصالة (طلب المراجعة،
    # تشخيص Issue #373، تعليق العطل الحادي والعشرون، البند 2): التوثيق
    # القديم ("الرفض نهائي بلا إعادة محاولة") افترض أن مدخلات الصياغة لا
    # تتغيّر بين محاولتين — لم يعد هذا صحيحًا: الفحص صار يعرف الجملة
    # المخالفة بعينها (offending)، فتُمرَّر توجيهًا صريحًا لإعادة بنائها من
    # جديد. فشل المحاولة الثانية امتناع نهائي كاليوم بالضبط — لا أسوأ من
    # الوضع الحالي، وأفضل عند النجاح. المسودة الثانية تُفحص فحص أصالة كامل
    # جديد (لا استثناء لموضع الجملة المُصلَحة وحده) فلا تفلت من أي عطل جديد
    retry_info = {"attempted": False, "succeeded": False, "offending_phrase": ""}
    if not ok_orig and offending:
        retry_info["attempted"] = True
        retry_info["offending_phrase"] = offending["phrase"]
        avoid_note = _build_avoid_note(offending)
        written2, w_reason2 = _draft_article(grounded, opinions, question, cfg,
                                             avoid_note=avoid_note)
        if written2 is not None:
            draft_text2 = _draft_text_of(written2)
            ok2, reason2, notes2, _off2 = _check_orig(draft_text2)
            if ok2:
                written, draft_text = written2, draft_text2
                ok_orig, orig_reason, originality_notes = True, "", notes2
                retry_info["succeeded"] = True
            else:
                orig_reason = (f"فشلت المحاولة الثانية (بعد إعادة صياغة الجملة "
                               f"المخالفة) أيضًا: {reason2}")
        else:
            orig_reason = f"فشلت المحاولة الثانية تقنيًا في الصياغة: {w_reason2}"
    outcome["originality_retry"] = retry_info
    outcome["originality_notes"] = originality_notes

    # تسرّب مصطلحات بنية النظام (طلب المراجعة، تشخيص Issue #373، تعليق
    # العطل الثالث والعشرون) — على المسودة الحالية (بعد أي نجاح لمحاولة
    # الأصالة الثانية)، بلا محاولة إن كانت المسودة أصلًا مرفوضة بالأصالة
    # (توفير كلفة نداء لن يُستفاد منه — النص سيُرفض على أي حال أدناه).
    # محاولة صياغة ثانية واحدة، بنفس آلية avoid_note القائمة؛ المسودة الجديدة
    # (إن نجحت في إسقاط المصطلحات) تُفحَص فحص أصالة كامل من جديد أيضًا — هي
    # نصّ مُولَّد من الصفر، لا امتداد للمسودة التي اجتازت الأصالة سابقًا.
    # detected: المصطلحات المرصودة أول مرة (للتقرير، ثابتة بلا تصفير) —
    # remaining: ما تبقّى منها بعد المحاولة (فارغة يعني نجاح أو زوال المصطلحات
    # ولو فشلت الأصالة لاحقًا) — الامتناع يُبنى على remaining حصرًا فلا
    # يُنسَب فشل ناتج عن الأصالة إلى تسرّب مصطلحات زالت فعليًا
    jargon_retry = {"attempted": False, "succeeded": False, "detected": [], "remaining": []}
    if ok_orig:
        jargon_hits = _system_jargon_hits(draft_text)
        if jargon_hits:
            jargon_retry["attempted"] = True
            jargon_retry["detected"] = jargon_hits
            jargon_retry["remaining"] = jargon_hits
            avoid_note_j = _build_jargon_avoid_note(jargon_hits)
            written_j, w_reason_j = _draft_article(
                grounded, opinions, question, cfg, avoid_note=avoid_note_j)
            if written_j is not None:
                draft_text_j = _draft_text_of(written_j)
                hits2 = _system_jargon_hits(draft_text_j)
                if hits2:
                    jargon_retry["remaining"] = hits2
                else:
                    ok_orig_j, orig_reason_j, notes_j, _off_j = _check_orig(draft_text_j)
                    if ok_orig_j:
                        written, draft_text = written_j, draft_text_j
                        originality_notes = notes_j
                        outcome["originality_notes"] = notes_j
                        jargon_retry["succeeded"] = True
                        jargon_retry["remaining"] = []
                    else:
                        ok_orig = False
                        orig_reason = (f"مسودة إعادة صياغة المصطلحات النظامية فشلت "
                                       f"فحص الأصالة أيضًا: {orig_reason_j}")
                        jargon_retry["remaining"] = []
    outcome["jargon_retry"] = jargon_retry

    if jargon_retry["attempted"] and jargon_retry["remaining"]:
        outcome["reason"] = (f"مرحلة الصياغة — امتناع: مصطلحات من بنية النظام تسرّبت "
                             f"إلى المتن ({'، '.join(jargon_retry['remaining'])})")
        return outcome

    # بلاغ لا رفض (طلب المراجعة، تشخيص Issue #373 الجولة السابعة عشرة،
    # البند 2-ج) — على المسودة النهائية (بعد أي محاولة ثانية ناجحة)، فلا
    # يضيع أثره حتى لو رُفض المقال لاحقًا في مرحلة النسبة/الأصالة.
    # source_texts (تشخيص Issue #373، تعليق العطل الثاني والعشرون، البند 1):
    # نفس مجمّع source_docs+extra_docs المستعمَل لفحص الأصالة — يقصر البلاغ
    # على تتابعات وردت حرفيًا في نص مصدر مقروء فعلًا، لا كل اختيار كلمات
    # مختلف عن الموجز. attribution_phrase يُعفي صيغة نسبة الرأي الثابتة.
    entity_min_run = int(acfg.get("unsourced_entity_min_run", 2))
    entity_source_texts = ([d["text"] for d in source_docs if d.get("text")]
                           + [d["text"] for d in extra_docs if d.get("text")])
    outcome["unsourced_entities"] = _unsourced_entities(
        written["post_body"], grounded, body, question, opinions,
        source_texts=entity_source_texts, min_run=entity_min_run,
        attribution_phrase=acfg.get("opinion_attribution_phrase", "وترى الصفحة أن"))

    # فحص بنيوي — لا اعتمادًا على البرومبت وحده (القاعدة 9، طلب المراجعة
    # البند 1، تشخيص Issue #373 الجولة السادسة عشرة) — على المسودة النهائية
    # أيضًا: محاولة ثانية أعادت صياغة المتن بالكامل، فقد تُسقط نسبة تقرير
    # منقول كانت موجودة في الأولى
    attrib_ok, attrib_reason = _report_attribution_ok(written["post_body"], grounded)
    if not attrib_ok:
        outcome["reason"] = f"مرحلة الصياغة — امتناع: {attrib_reason}"
        return outcome

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
    image_pool_source = "grounded" if image_ranked else "none"
    if not image_ranked and reprint_image_pool:
        # احتياط ثانٍ (طلب المراجعة، البند 1): وثيقة استُبعدت من عدّ
        # الاستقلالية تبقى مرشَّحًا صالحًا للصورة — الاستبعاد يخصّ السند لا
        # الصور. يُستهلَك فقط حين لا صورة من مصدر مسنِد فعليًا مباشرة، ويُوسَم
        # صراحة في التقرير أدناه فلا يبدو مصدرًا مسنِدًا بالخطأ.
        image_ranked = _pool_image_candidates(reprint_image_pool)
        image_pool_source = "excluded_reprint" if image_ranked else "none"
    image_urls = [u for u, _, _ in image_ranked]

    # عبارات بحث find_images الاحتياطي (طلب المراجعة، البند 1): من كيانات
    # الوقائع المسندة (entities) لا central_text العربي — imagesearch.keywords()
    # تستخرج فقط أحرفًا لاتينية كبيرة فتعيد قائمة فارغة لنص عربي دومًا،
    # مهما كان محتواه (انظر _image_search_terms). تُطبَع في التقرير أدناه
    # بصرف النظر عن النتيجة، فلا يبقى سبب رجوع find_images بصفر غامضًا.
    image_terms = _image_search_terms(grounded)

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
            fallback_provider=lambda: find_images(central_text, cfg, terms=image_terms or None),
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
    # المسندة كلها قبل القصّ إلى أول 6 (candidates_tried داخل shot).
    # image_pool_source/fallback_query_terms جديدان (طلب المراجعة، البند 1):
    # من أي مجمّع جاءت مرشَّحات image_urls، وما استعلام find_images الفعلي
    outcome["image_report"] = {**shot, "total_candidates": len(image_urls),
                               "image_pool_source": image_pool_source,
                               "fallback_query_terms": image_terms}

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
    # لمرشَّح من image_ranked (مصادر مسندة/احتياط استبعاد) كان لينسب صورة حرة
    # لمصدر لم يوفّرها إطلاقًا.
    # المطابقة بـ chosen_url لا image_ranked[0] (إصلاح عطل عزو مكتشَف أثناء
    # هذه الجولة): imaging.build_post_image قد يعيد ترتيب المرشحين بالوجوه
    # أو ينجح مرشَّح لاحق لا الأول — image_ranked[0] كانت تُنسَب دومًا بصرف
    # النظر عن أيّهما نجح فعلًا. chosen_url (جديد في تقرير imaging.py) هو
    # الرابط الذي نجح تحديدًا؛ ونحتاجها أيضًا هنا لتمييز مصدر احتياط
    # الاستبعاد الصحيح حين image_ranked من reprint_image_pool لا من grounded
    if shot.get("used_original") and not shot.get("illustrative") and image_ranked:
        chosen = shot.get("chosen_url")
        match = next((t for t in image_ranked if t[0] == chosen), None) or image_ranked[0]
        outcome["image_source_name"] = match[1]
        outcome["image_source_link"] = match[2]

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
    حين لم يصل الإنتاج مرحلة بناء الصورة أصلًا — لا شيء يُعرض حينها.

    pool_source (طلب المراجعة، مراجعة بشرية بعد أول نشر، البند 1) يميّز
    مرشَّحات "grounded" (مصادر مسندة فعليًا) عن "excluded_reprint" (وثيقة
    استُبعدت من عدّ الاستقلالية لكنها بقيت مرشَّحًا صالحًا للصورة) — وسمٌ
    صريح فلا يبدو الاستثناء صامتًا ولا يُظَنّ "مصدر مسند" خطأً."""
    if not ir:
        return []
    total = ir.get("total_candidates", 0)
    failures = ir.get("candidate_failures") or []
    pool = ir.get("image_pool_source", "grounded")
    pool_label = "مصادر مستبعدة كإعادة نشر" if pool == "excluded_reprint" else "المصادر المسندة"
    # illustrative قبل used_original عمدًا: imaging.build_post_image يضبط
    # used_original=True أيضًا حين ينجح احتياط find_images وحده (يعني فقط
    # "لا خلفية مصمَّمة استُخدمت")، فحالة الاحتياط الناجح تحمل العلمين معًا
    # — illustrative هي الحالة الأدق لتمييزها عن صورة مصدر حقيقية
    if ir.get("illustrative"):
        head = (f"🖼️ فشلت صور {pool_label} كلها ({total} مرشَّحًا) — استُخدمت صورة "
               f"تعبيرية حرة من find_images (من {ir.get('fallback_candidates', 0)} مرشَّحًا).")
    elif ir.get("used_original"):
        if pool == "excluded_reprint":
            head = (f"🖼️ صورة من مصدر استُبعد من عدّ الاستقلالية ({total} مرشَّحًا) — "
                    "ليس دليل إسناد، فقط أُتيحت صورته احتياطًا لغياب صور المصادر المسندة.")
        else:
            head = f"🖼️ صورة من مصدر مسند مباشرة ({total} مرشَّحًا من المصادر المسندة)."
    else:
        head = (f"🖼️ فشلت صور {pool_label} كلها ({total} مرشَّحًا)" if total
               else f"🖼️ لا صورة واحدة بين مرشَّحي {pool_label} (0)")
        if ir.get("fallback_tried"):
            head += (f" — استُدعي احتياط find_images أيضًا وأعاد "
                    f"{ir.get('fallback_candidates', 0)} مرشَّحًا، لم ينجح أي منها.")
        else:
            head += " — لم يُستدعَ احتياط find_images."
    lines = ["", head]
    # استعلام find_images الفعلي (طلب المراجعة، البند 1): يُطبَع دومًا حين
    # استُدعي الاحتياط — لا سبيل لتشخيص "لماذا رجع بصفر" بلا معرفة ما بُحث
    # عنه أصلًا
    if ir.get("fallback_tried"):
        terms = ir.get("fallback_query_terms") or []
        terms_text = "، ".join(terms) if terms else "(لا كيانات مستخرجة — لم يُبحث بشيء)"
        lines.append(f"  🔎 استعلام الصورة الاحتياطية: {terms_text}")
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
            # فجوة دمج (تشخيص Issue #373، تعليق العطل الرابع والعشرون):
            # جملة مصدر دخلت الدمج لكن لا أثر لها في النص المدموج — تبليغ
            # صريح بدل انكماش صامت (شاهد بايكرآر: 3 من 4 جمل سقطت)
            if m.get("gaps"):
                gaps_str = "؛ ".join(m["gaps"])
                lines.append(f"  ⚠️ فجوة دمج — لا أثر لها في النص المدموج: {gaps_str}")
            # معيار الأغلبية (طلب المراجعة، تعليق العطل الرابع والعشرون):
            # أي مصدر أيّد كل جزء وأيها لم يُؤيَّده أي مصدر — الأجزاء غير
            # المؤيَّدة (✗) لا تدخل متن المقال بصرف النظر عن اجتياز التصريح
            # ككل بأغلبية أجزاء أخرى
            for part in m.get("part_support") or []:
                supporters = part.get("supporting") or []
                mark = "؛ ".join(supporters) if supporters else "✗ لا مصدر"
                lines.append(f"  • «{part['excerpt']}» — {mark}")

    if outcome.get("split_statements"):
        # نظير مقلوب لـ merged_statements أعلاه (البند 3، الجولة الخامسة
        # عشرة): جملة مركّبة واحدة فُصِّلت إلى عدة وقائع ذرّية، كلٌّ سنده
        # الخاص — تظهر الجملة الأصلية وكل جزء استُخرج منها فيراجعهما
        # المستخدم البشري
        lines += ["", "**وقائع فُصِّلت من جملة واحدة (راجعها):**"]
        for sp in outcome["split_statements"]:
            parts = "؛ ".join(sp["parts"]) or "—"
            lines.append(f"- «{sp['original']}» — فُصِّلت إلى: {parts}")

    if outcome.get("report_statements"):
        # نوع رابع "تقرير منقول" (طلب المراجعة البند 2، تشخيص Issue #373،
        # الجولة السادسة عشرة): عتبته مصدر واحد فقط (report_min_confirm) —
        # يستحق مراجعة بشرية مخصَّصة، بتمييز صريح بين الوثيقة الأصلية
        # (original) والناقل الذي يسمّي الناشر (carrier)، لا عرض إعفاء صامت
        _kind_ar = {"original": "الوثيقة الأصلية", "carrier": "ناقل يسمّي الناشر"}
        lines += ["", "**تقارير مُرحَّلة عن ناشر واحد (راجعها):**"]
        for r in outcome["report_statements"]:
            for s in r["sources"]:
                label = f"[{s['name']}]({s['link']})" if s.get("link") else s["name"]
                kind_ar = _kind_ar.get(s["kind"], "؟")
                lines.append(f"- {r['publisher']}: «{r['text']}» — {label} ({kind_ar})")

    summary = outcome.get("source_facts_summary") or {}
    if summary.get("extracted"):
        # أثر ظاهر لا صامت (طلب المراجعة، البند 5 — "تعلّمنا من judged_by
        # أن الميزة بلا أثر ظاهر لا تُعرف إن كانت تعمل"): يظهر بصرف النظر
        # عن نجاح إضافة أي واقعة فعليًا، فتُعرف حصيلة كل تشغيلة رقميًا
        lines += ["", (f"🔎 استُخرجت {summary['extracted']} واقعة من المصادر المقروءة "
                       f"لم ترد في موجزي، اندمجت {summary.get('merged', 0)} منها مع "
                       f"وقائع موجزي (نفس الحدث بصياغة مختلفة)، وأُضيفت "
                       f"{summary.get('added', 0)} واقعة جديدة إلى المقال.")]

    if outcome.get("source_origin_facts"):
        # origin: "source" — طلب المراجعة، البند 2: هذا ما يراجعه المستخدم
        # أولًا في كل تشغيلة — واقعة دخلت المقال من مصدر مستقل قرأته الآلة،
        # لا من الموجز الذي لصقه هو، فتستحق تدقيقًا بشريًا مخصَّصًا
        lines += ["", "**وقائع من المصادر لم ترد في موجزي (راجعها):**"]
        for f in outcome["source_origin_facts"]:
            srcs = "، ".join(f"[{s['name']}]({s['link']})" if s.get("link") else s["name"]
                             for s in f["sources"]) or "—"
            lines.append(f"- «{f['text']}» — {srcs}")

    if outcome.get("originality_notes"):
        # تبليغ صريح لا إعفاء صامت (تشخيص Issue #373، الجولة العاشرة، البند
        # 2): كل تتابع أُعفي من رفض النسخ اللفظي بإشارة (أ)/(ب) يظهر هنا
        # بدليله، فيبقى قابلًا لتصحيح المراجع البشري إن أخطأت الإشارة
        lines += ["", "**تتابعات أُعفيت من فحص النسخ اللفظي:**"]
        lines += [f"- {note}" for note in outcome["originality_notes"]]

    retry = outcome.get("originality_retry") or {}
    if retry.get("attempted"):
        # شفافية محاولة الصياغة الثانية (طلب المراجعة، تشخيص Issue #373،
        # تعليق العطل الحادي والعشرون، البند 2) — لا نجاح صامت
        status = "✅ نجحت" if retry.get("succeeded") else "❌ فشلت أيضًا"
        lines += ["", f"🔁 محاولة صياغة ثانية بعد رفض الأصالة — {status}: "
                      f"أُعيدت صياغة الجملة المخالفة «{retry.get('offending_phrase', '')}»"]

    jargon_retry = outcome.get("jargon_retry") or {}
    if jargon_retry.get("attempted"):
        # شفافية محاولة الصياغة الثانية لإسقاط مصطلحات النظام (طلب المراجعة،
        # تشخيص Issue #373، تعليق العطل الثالث والعشرون) — لا نجاح صامت.
        # detected تُعرض دومًا (ما وُجد أول مرة)؛ الحالة تُبنى على remaining
        # (فارغة = زالت المصطلحات، ولو فشل المقال لاحقًا بسبب الأصالة)
        j_status = "✅ زالت" if not jargon_retry.get("remaining") else "❌ تكررت"
        detected_str = "، ".join(f"«{h}»" for h in jargon_retry.get("detected", []))
        lines += ["", f"🔁 محاولة صياغة ثانية بعد تسرّب مصطلحات نظام ({detected_str}) — "
                      f"{j_status}"]

    if outcome.get("unsourced_entities"):
        # فحص بنيوي بعدي — بلاغ لا رفض (طلب المراجعة، تشخيص Issue #373،
        # الجولة السابعة عشرة، البند 2-ج): كيان في المتن (اسم علم متتالٍ أو
        # رقم) غائب عن الوقائع المسندة وعن الموجز — قد يكون تسرَّب من نص
        # مصدر كامل قُرئ للأسلوب لا للمضمون (نمط "شو جيايين" المُبلَّغ)
        lines += ["", "**تفاصيل لم تجتز بوابة السند (راجعها):**"]
        lines += [f"- {note}" for note in outcome["unsourced_entities"]]

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
            # judged_by يظهر فقط لمرحلة «تصريح» — الحارس البنيوي الذي طلبته
            # المراجعة ضد ارتداد صامت لحكم معيار الأغلبية (انظر توثيق
            # judged_by عند بنائه أعلاه)؛ لا فائدة من طباعته لمراحل أخرى
            # يكون فيها "شمولي" دومًا وبلا معنى تشخيصي إضافي
            judged_suffix = (f" — حُكم بـ: {t.get('judged_by', '؟')}"
                            if t["stage"] == "تصريح" else "")
            lines.append(f"- **[{t['stage']}]** `{t['query']}`{counts} → {t['basis']} — "
                         f"{t.get('outcome', '')} (المصادر: {srcs}){judged_suffix}")
            for fail in t.get("fetch_failures") or []:
                name, reason, link = fail.get("name", "؟"), fail.get("reason", ""), fail.get("link", "")
                label = f"[{name}]({link})" if link else name
                lines.append(f"  - ⚠️ فشل جلب {label}: {reason}")
            # استبعاد إعادات نشر الموجز (طلب المراجعة، أولوية) — بدليل عدد
            # الكلمات المشتركة الفعلي لكل استبعاد، فيراجَع أول عشر حالات
            # ويُضبَط article.brief_reprint_min_shared_words على أدلة حقيقية
            for rep in t.get("excluded_reprints") or []:
                name, link = rep.get("name", "؟"), rep.get("link", "")
                label = f"[{name}]({link})" if link else name
                lines.append(f"  - 🗞️ استُبعدت كإعادة نشر حرفية للموجز الملصق: {label} "
                             f"— تتابع مشترك {rep.get('shared_words', '؟')} كلمة")
            # أعلى 5 مرشّحين بالدرجة المركّبة (البند 2، تشخيص Issue #373،
            # الجولة الثالثة عشرة، الخيار (و)): رصد صرف — يحسم برقم فعلي هل
            # تفوّق صلة لفظية عالية على فارق وزن ثابت هو ما يمنع مصدرًا
            # موثوقًا من الصعود، بدل تخمين تفسير بلا دليل.
            #
            # "صلة" المعروضة هي relevance_used (المقصوصة، المُستعملة فعليًا
            # في "درجة") لا العدد الخام — كي يبقى وزن+صلة=درجة دومًا كما
            # يُقرأ (تشخيص Issue #373، تعليق العطل العشرون، البند 2: عرض
            # الصلة الخامة كان يُنتج مجموعًا لا يطابق الدرجة المعروضة كلما
            # تجاوزت الصلة سقف RELEVANCE_CAP، فبدا الرقم خاطئًا رغم صحة
            # الحساب). العدد الخام يظهر بين قوسين فقط حين يختلف عن المقصوص.
            for c in t.get("top_candidates") or []:
                rel_used = c.get("relevance_used", c["relevance"])
                rel_display = (f"{rel_used} (خام {c['relevance']})"
                               if rel_used != c["relevance"] else str(rel_used))
                lines.append(f"  - 🔎 {c['name']}: وزن={c['weight']} صلة={rel_display} "
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
