"""المرحلة الرابعة من مسار يوتيوب (Issue #646): كتابة مقالات عربية من أعلى
قضايا src/youtube_cluster.py، للقراءة فقط -- لا مسودات في drafts/، لا Issue
مراجعة، لا صور، لا نشر (خارج نطاق هذه المهمة صراحةً).

يأخذ أعلى ``youtube.article.count`` قضية (افتراضيًا ١٠) ويكتب لكل واحدة
مقالًا بنموذج أقوى من نموذج العنقدة -- نثر متّصل بلا عناوين أقسام (Issue
#690)، بنسبة صريحة لكل متحدث لا لقناته، وبلا أي معلومة من خارج النقاط
المرفقة (انظر prompts/youtube_article.md للقواعد التحريرية كاملة).

خرج المقال **نصّ عادي** (Markdown) لا إخراج مهيكل -- خلافًا لمرحلة العنقدة:
البنية هنا نثرية (عنوان + فقرات + رؤوس فرعية) لا بيانات مصنَّفة في حقول،
فلا فائدة من إجبارها في مخطّط tool_use؛ التحقّق من مطابقة البنية يقع بعد
الاستلام (_validate_article_text) لا أثناء الطلب.

قائمة المحظورات (skipped بسببها) تُطبَّق فقط على قضايا الطبقة (ج) -- مصدر
واحد -- عبر نداء حرّاس رخيص منفصل قبل إنفاق نداء الكتابة الأقوى، بنفس مبدأ
حارس الموضوع في src/youtube_extract.py: حكم دلالي رخيص قبل تكلفة كبيرة.

Issue #660 الإصلاح ٣: run() يوكِّد الآن وجود
state/youtube_topics_seen.json دومًا قبل نهاية التشغيلة (يكتب "{}" إن غاب)
-- تشغيلة بصفر مقالات ناجحة لا تستدعي youtube_cluster.mark_points_seen
أصلًا فلا يُنشَأ الملف، وخطوة `git add` على مسار غير موجود في الـworkflow
كانت تُسقِط خطوة الرفع كاملة (pathspec لم يطابق، exit code 128) وتُضيع كل
ما أُنتج قبلها.

Issue #662 (تنقية المخرج بعد أول تشغيلة كاملة ناجحة): (٣) تحذير "اسم علم
مشكوك في نسبته" الذي يحسبه src/youtube_extract.py لكل نقطة كان يضيع في
state/youtube_points/ (قائمة `failed` المنفصلة) ولا يصل المراجع الذي يقرأ
هذا المجلد فقط -- run() يعيد حسابه الآن لكل قضية (_collect_warnings،
باستدعاء youtube_extract.find_unsourced_name نفسها بلا تعديلها) ويضيفه ذيل
المقال (_append_warnings) وعمودًا في index.md. (٤) مؤشّر `agreement` الذي
يصل نداء الكتابة يبقى `dispute` حتى بعد تنقيح youtube_cluster.py لقيمته
المخزَّنة إلى cross_source/internal -- prompts/youtube_article.md خارج
النطاق (ممنوع تعديله) ولا يعرف القيمتين الجديدتين، فـ_MODEL_FACING_AGREEMENT
تُترجمهما إلى `dispute` عند بناء نداء النموذج فقط، بلا مساس بما يُخزَّن أو
يُعرَض في index.md.

Issue #680 (دورة المراجعة -- عناوين متعدّدة): run() يضيف الآن نداءً قصيرًا
رخيصًا منفصلًا بعد نجاح الكتابة (generate_headlines) يقترح ثلاثة عناوين
عربية بديلة لبطاقة/منشور المراجعة -- برومبت ونداء جديدان بالكامل هنا، **لا**
تعديل على prompts/youtube_article.md ولا على بنية المقال نفسها (خارج نطاق
الـIssue صراحةً). العناوين تُلحَق ذيل المقال (_append_headlines) بعد قسم
التحذيرات، ويقرؤها src/youtube_publish.py (split_headlines) عند بناء
مسودة المراجعة. فشل النداء أو عناوينه لا يُسقِط مقالًا ناجحًا فعليًا --
احتياط بعنوان المقال الأصلي مكرَّرًا ثلاثًا، بنفس مبدأ check_forbidden/
draft_article في عدم إسقاط عمل صالح بسبب عطل في خطوة إضافية لاحقة."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic, APIError

from . import headlines as headlines_mod
from . import youtube_cluster, youtube_extract
from .config import YOUTUBE_ARTICLES_DIR, Config, env, load_config

log = logging.getLogger(__name__)

ARTICLE_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "youtube_article.md"
# مستودع خاص منفصل لا state/ المحلي (Issue #724) -- انظر توثيق
# config.YOUTUBE_ARTICLES_DIR.
ARTICLES_DIR = YOUTUBE_ARTICLES_DIR

# قائمة المحظورات (نص الـIssue) -- لا يُكتب مقال بمصدر واحد (طبقة ج) عن أيّ
# من هذه الأبواب مهما كانت النسبة صريحة؛ تحتاج طبقة (أ) أو (ب) بدلًا منها.
FORBIDDEN_CATEGORIES = (
    "accusation_named",           # اتهام شخص أو جهة مسمّاة بجريمة أو فساد أو خيانة
    "health_medical",             # ادعاءات صحية أو دوائية أو علاجية
    "military_ops",               # حركات جيوش أو عمليات وشيكة أو مواقع منشآت
    "sectarian_generalization",   # ما يمسّ طائفة أو قومية أو دينًا بتعميم
    "market_moving_numbers",      # أرقام مالية محددة قابلة لتحريك سوق
    "minors",                     # ما يخصّ قاصرين
)

GUARD_SCHEMA = {
    "name": "check_forbidden_topic",
    "description": ("يفحص إن كانت قضية أحادية المصدر (طبقة ج) تقع ضمن قائمة "
                     "المحظورات التي تمنع الكتابة عنها بمصدر واحد"),
    "input_schema": {
        "type": "object",
        "properties": {
            "blocked": {"type": "boolean"},
            "category": {"type": "string", "enum": list(FORBIDDEN_CATEGORIES) + ["none"]},
            "reason": {"type": "string", "description": "شرح عربي قصير للسبب"},
        },
        "required": ["blocked", "category", "reason"],
    },
}

# Issue #658 العطل ٣: التشغيلة الأولى حظرت ٧ من ٨ قضايا طبقة (ج) -- خمس
# بسبب فارغ تمامًا (حارس صامت)، واثنتان بتعليل خاطئ: حجم اقتصاد دولة
# (إحصاء منشور) صُنِّف "رقمًا قابلًا لتحريك السوق"، وملاحقة قضائية علنية
# أعلنتها النيابة صُنِّفت "اتهامًا مسمّى". السبب: البنود كانت تصف الموضوع لا
# المعيار -- أُعيدت صياغتها أدناه بمعيار الممنوع الدقيق مقابل مسموح صريح
# لكل فئة، مع أمثلة حرفية من نفس التشغيلة.
GUARD_SYSTEM = """أنت حارس محظورات لقضايا أحادية المصدر (تناولتها قناة واحدة
فقط بلا تأكيد مستقل). لكل فئة معيار الممنوع فيها تحديدًا لا الموضوع كله --
نقل خبر من نفس الباب قد يكون مسموحًا تمامًا إن كان إحصاءً أو إجراءً رسميًا
معلنًا لا اتهامًا أو توصية أو تفصيلًا حسّاسًا:

- accusation_named: ممنوع اتهام يطلقه محلل أو صحفي من رأسه بجريمة أو فساد
  أو خيانة لشخص أو جهة مسمّاة. مسموح: إجراء قضائي أو رسمي معلن ومنسوب
  لجهته (نيابة عامة، محكمة، وزارة) -- نقل قرار رسمي ليس اتهامًا.
- market_moving_numbers: ممنوع توصية استثمارية أو توقّع سعر أصل أو
  "اشترِ/بِع". مسموح: إحصاءات اقتصادية منشورة (ناتج محلي، تضخم، احتياطيات،
  ميزانيات) ولو كانت أرقامًا كبيرة أو محدَّدة.
- health_medical: ممنوع نصيحة علاجية أو دوائية. مسموح: تغطية أزمة صحية
  عامة أو نقص أدوية كخبر.
- military_ops: ممنوع مواقع منشآت أو تفاصيل عمليات عسكرية وشيكة. مسموح:
  تغطية توتر عسكري أو تصريحات رسمية عنه.
- sectarian_generalization: ممنوع تعميم سلبي على جماعة أو طائفة أو قومية
  أو دين بأكمله. مسموح: نقل حدث يخصّ طرفًا بعينه بالاسم لا الجماعة كلها.
- minors: ما يخصّ قاصرين، بلا استثناء.

أمثلة حرفية للفصل بين المسموح والممنوع (من تشغيلة فعلية):
- "الاقتصاد الإيراني انخفض من ٦٥٠ إلى ٣٠٠ مليار دولار" ⇐ مسموح (إحصاء
  اقتصادي منشور، ليس توصية استثمارية).
- "النيابة العامة في أنقرة فتحت تحقيقًا مع فلان" ⇐ مسموح (إجراء رسمي معلن
  ومنسوب لجهته، ليس اتهامًا من محلل).
- "قال المحلل إن فلانًا سرق أموالًا" ⇐ ممنوع (اتهام أحادي يطلقه محلل من
  رأسه، بلا نسبة لجهة رسمية).

تستلم ملخّص نقاط قضية واحدة. اضبط blocked=true وcategory بالفئة المطابقة
إن انطبق **المعيار الممنوع تحديدًا** أعلاه على مضمون القضية، وإلا
blocked=false وcategory="none". الحكم على المضمون لا على درجة يقين
الصياغة -- اتهام "مزعوم" يبقى اتهامًا إن كان من محلل لا جهة رسمية. اكتب في
reason دومًا شرحًا عربيًا قصيرًا يذكر أيّ شقّ من المعيار انطبق -- قرار
blocked=true بلا سبب مكتوب لا قيمة له ويُتجاهَل من الشيفرة."""


# مؤشّر الخلاف الذي يصل النموذج في نداء الكتابة (Issue #662 العطل ٤) --
# prompts/youtube_article.md خارج النطاق (ممنوع تعديله)، وقاعدته السابعة
# تتحدّث صراحة عن قيمة `dispute` فقط ("إن كان مؤشّر القضية dispute..."). بدل
# تعديل البرومبت، القيم الجديدة cross_source/internal (تنقيح برمجي لاحق
# لـdispute، انظر youtube_cluster._agreement_type_for) تُعاد إلى `dispute`
# عند بناء نداء الكتابة فقط -- المخرج المخزَّن (index.md، stats) يبقى يعرض
# القيمة المُنقَّحة الفعلية، والنموذج وحده يرى الاسم الذي يفهمه برومبته.
_MODEL_FACING_AGREEMENT = {"cross_source": "dispute", "internal": "dispute"}


def load_article_prompt() -> str:
    return ARTICLE_PROMPT_PATH.read_text(encoding="utf-8")


def _topic_summary(topic: dict, member_points: list[dict]) -> str:
    lines = [f"القضية: {topic['title']}"]
    for p in member_points:
        lines.append(f"- ({p.get('speaker', '')} عبر {p.get('channel', '')}): "
                     f"{p.get('statement', '')}")
    return "\n".join(lines)


def check_forbidden(topic: dict, member_points: list[dict], cfg: Config,
                     client: Anthropic | None = None) -> tuple[bool, str, str | None, bool]:
    """يعيد (محظورة، السبب، سبب فشل النداء إن حدث -- None عند النجاح، هل
    قُبِلت القضية بتجاوز حظر بلا سبب مكتوب). فشل النداء لا يحظر القضية
    تلقائيًا -- نفس مبدأ classify_topic في src/youtube_extract.py: عطل شبكي
    عابر ليس دليل حظر، وإسقاط القضية صامتًا لهذا السبب يناقض مبدأ المشروع
    في عدم الفشل الصامت.

    Issue #658 العطل ٣ بند أ: خمس من سبع قضايا حُظرت في التشغيلة الأولى
    بسبب فارغ تمامًا -- حارس صامت لا يُطاع. blocked=true بلا reason مكتوب
    يُعامَل هنا كأنه blocked=false (تُقبَل القضية)، والعنصر الرابع المُعاد
    يُخبر الطالب بأن هذا التجاوز وقع تحديدًا، لتغذية عدّاد
    topics_blocked_no_reason في run() -- تمييزًا عن حظر عادي بسبب مكتوب."""
    model = cfg.path("youtube.article.guard_model",
                      cfg.path("youtube.extract.model", "claude-haiku-4-5-20251001"))
    client = client or Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=200,
            tools=[GUARD_SCHEMA],
            tool_choice={"type": "tool", "name": "check_forbidden_topic"},
            system=GUARD_SYSTEM,
            messages=[{"role": "user", "content": _topic_summary(topic, member_points)}],
            # لا تُضِف temperature -- نماذج هذا المشروع ترفضها بـ400.
        )
    except APIError as exc:
        return False, "", f"فشل نداء حارس المحظورات: {exc}", False

    data = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
    if not isinstance(data, dict):
        return False, "", None, False
    category = data.get("category")
    reason = str(data.get("reason", "")).strip()
    blocked = bool(data.get("blocked")) and category in FORBIDDEN_CATEGORIES
    if blocked and not reason:
        return False, "", None, True
    return blocked, reason, None, False


def _points_block(member_points: list[dict], cfg: Config | None = None) -> str:
    # اسم القناة المعروض name_ar إن وُجد (Issue #1272): الخط لا يملك حروفًا عبرية، فـ«ערוץ 14»
    # تصير «القناة 14»، وهو الاسم نفسه الذي يفحص article_violations وروده في المتن.
    cfg = cfg or load_config()
    lines = []
    for i, p in enumerate(member_points, start=1):
        ts = f"{p['timestamp']}ث" if p.get("timestamp") is not None else "غير معروف"
        lines.append(
            f"{i}. القناة: {display_channel_name(p.get('channel', ''), cfg)} ({p.get('bloc', '')}) | "
            f"المتحدث: {p.get('speaker', '')} | النوع: {p.get('type', '')}\n"
            f"   القول: {p.get('statement', '')}\n"
            f"   الاقتباس العربي: {p.get('quote_arabic', '')}\n"
            f"   الفيديو: {p.get('video_title', '')} — {p.get('video_url', '')} "
            f"(الطابع: {ts})"
            + (f" (نُشر الفيديو: {p['video_published']})" if p.get("video_published") else "")
        )
    return "\n".join(lines)


# ── تحذيرات المراجعة (Issue #662 العطل ٣) ──
#
# youtube_extract.extract_points يحسب تحذير "اسم علم مشكوك في نسبته"
# (_unsourced_name) لكل نقطة، لكن مخرج تلك المرحلة المحفوظ
# (state/youtube_points/) لا يحمله على النقطة نفسها -- يُسجَّل فقط في قائمة
# `failed` المنفصلة، فلا يصل إلى هذه المرحلة عبر point_ids. بدل تعديل
# مرحلتَي الجمع/الاستخلاص (خارج النطاق صراحة)، يُعاد حساب نفس التحذير هنا
# باستدعاء youtube_extract.find_unsourced_name (دالة نقية جاهزة، بلا أي
# تعديل عليها) على statement/quote_original المحفوظين فعليًا مع كل نقطة --
# نفس المدخلات ونفس المنطق بالضبط، لا إعادة تطبيق حرفي منسوخ.

WARNINGS_HEADER = "⚠️ تنبيهات للمراجعة (لا تُنشر):"


def _arabic_point_count_phrase(n: int) -> str:
    """صياغة عربية لعدد النقاط (مفرد/مثنى/جمع) -- شاهد صياغة الـIssue
    الحرفية: "نقطة" للمفرد، "نقطتين" للمثنى، "٣ نقاط" للجمع القليل."""
    if n == 1:
        return "نقطة"
    if n == 2:
        return "نقطتين"
    if 3 <= n <= 10:
        return f"{n} نقاط"
    return f"{n} نقطة"


def _collect_warnings(member_points: list[dict], cfg: Config) -> list[str]:
    """يعيد سطرًا واحدًا لكل اسم علم مشكوك ظهر في نقاط القضية (مجمَّعًا حسب
    الاسم، لا سطرًا لكل نقطة) -- ترتيب أول ظهور، لا أبجديًا، فالأسماء
    الأهمّ غالبًا الأسبق ظهورًا في نقاط القضية الأعلى ترتيبًا."""
    known_figures = cfg.path("youtube.extract.known_figures", [])
    counts: dict[str, int] = {}
    order: list[str] = []
    for p in member_points:
        name = youtube_extract.find_unsourced_name(
            p.get("statement", ""), p.get("quote_original", ""), known_figures)
        if not name:
            continue
        if name not in counts:
            order.append(name)
        counts[name] = counts.get(name, 0) + 1
    return [f"اسم {name!r} ورد في {_arabic_point_count_phrase(counts[name])} بلا نظير "
            f"له في الاقتباس الأصلي" for name in order]


def _video_ids_by_contribution(member_points: list[dict]) -> list[str]:
    """معرّفات الفيديوهات المصدرية لقضية واحدة، مرتَّبة تنازليًا بعدد النقاط
    التي ساهم بها كل فيديو (الأكثر مساهمة أولًا -- طلب المراجعة على Issue
    #1092) -- ترتيب أول ظهور كاسر تعادل عند تساوي المساهمة (sorted مستقرّة)،
    لا أبجديًا ولا عشوائيًا. تصل drafts/ عبر index.md (source_videos، انظر
    src/youtube_publish.py:build_draft) بوصفها المصدر الثاني لصورة البطاقة
    (خلفية معتّمة عند تعذّر صورة حرة الترخيص)."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for p in member_points:
        vid = p.get("video_id")
        if not vid:
            continue
        if vid not in counts:
            order.append(vid)
        counts[vid] = counts.get(vid, 0) + 1
    return sorted(order, key=lambda v: -counts[v])


def _append_warnings(article_text: str, warnings: list[str]) -> str:
    """يضيف قسم تحذيرات في ذيل المقال (بعد متنه مباشرة -- لا قسم ## مصادر
    يفصلهما بعد اليوم، Issue #941)، فقط عند وجود تحذيرات فعلية (Issue #662
    العطل ٣ بند ب) -- قسم فارغ دومًا نظريًا يفقد قيمته كإشارة، لا يميّز
    المراجع مقالًا يستحق انتباهًا من آخر لا يستحقّه."""
    if not warnings:
        return article_text
    lines = "\n".join(f"- {w}" for w in warnings)
    return f"{article_text.rstrip()}\n\n---\n{WARNINGS_HEADER}\n{lines}\n"


# ── عناوين مقترحة لبطاقة/منشور المراجعة (Issue #680) ──
#
# نداء قصير رخيص منفصل بعد نجاح الكتابة -- لا علاقة له ببنية المقال نفسها
# (## الأقسام، سطر التقدير...) ولا بـprompts/youtube_article.md، فكلاهما
# خارج نطاق الـIssue صراحةً. الغرض: إعطاء المراجع خيارًا بدل عنوان واحد
# مفروض، مع إبقاء الافتراضي صيغة سؤال (أقل حسمًا من عنوان تقريري لمادة
# تحليلية غير مؤكَّدة بطبيعتها).

# مخطط الأداة وحلقة إعادة المحاولة والتحقّق العام (سؤال أول + حدّ كلمات)
# مستخرجة إلى src/headlines.py (Issue #756) -- مشتركة الآن مع مسارات
# الأخبار/الطلب/التحقق/المقال. HEADLINE_SCHEMA يبقى اسمًا هنا (لا نسخة
# ثانية) لأنه لا يفترق عن مخطط headlines_mod حرفيًا؛ HEADLINE_SYSTEM يبقى
# نصًّا خاصًا بهذا المسار (يمرَّر صراحةً إلى propose_headlines عبر معامل
# system) لأنه يذكر "الاقتباسات الأصلية" تحديدًا -- ما لا نظير له في
# مسارات الأخبار.
HEADLINE_SCHEMA = headlines_mod.HEADLINE_SCHEMA

HEADLINE_SYSTEM = """أنت تقترح ثلاثة عناوين عربية بديلة لبطاقة عرض ومنشور مقال
تحليلي، من النقاط المصدرية المرفقة فقط -- لا معلومة من خارجها.

قواعد صارمة تنطبق على كل عنوان من الثلاثة:
1. لا يتجاوز خمس عشرة كلمة.
2. لا يقرّر حكمًا لم تثبته المادة المرفقة -- صياغة استفهامية أو مرجّحة عند
   عدم اليقين، لا جازمة أبعد ممّا تسمح به النقاط نفسها.
3. لا يحمل اسم عَلَم (شخص، دولة، منظمة) لم يرد في الاقتباسات الأصلية
   المرفقة -- لا تخترع نسبة قول لجهة لم تُذكر فيها.

العنوان الأول **يجب** أن يكون بصيغة سؤال ينتهي بعلامة استفهام (؟) -- هو
الخيار الافتراضي في مراجعة المحرِّر. الثاني والثالث بصيغتين مختلفتين عنه
وعن بعضهما (تقريرية أو ترجيحية)، لا تكرارًا لنفس المعنى بكلمات مختلفة.

أعد أيضًا image_query_en: من ثلاث إلى خمس كلمات إنجليزية تصف موضوع القضية
(الحدث نفسه) لا أشخاصها -- مثال: "Strait of Hormuz tanker" لا اسم محلل أو
مسؤول مذكور في النقاط. تُستعمَل هذه الكلمات لاحقًا للبحث عن صورة تعبيرية حرة
الترخيص، فلا قيمة لها إن كانت اسم شخص لا موضوعًا يمكن تصويره.

أعد الثلاثة عبر الأداة المعرَّفة (propose_headlines) حصرًا، بلا أي نص خارجها."""

# حقل اختياري (Issue #941) يُدمَج في نسخة معدَّلة من headlines_mod.HEADLINE_SCHEMA
# لهذا النداء وحده عبر propose_headlines(extra_properties=...) -- لا يمسّ
# المخطط المشترك مع بقية المسارات (collect/verify_draft/request)، ولا يستدعي
# نداء نموذج إضافيًا: نفس نداء العناوين القائم يعيد هذا الحقل معه.
IMAGE_QUERY_EXTRA_PROPERTY = {
    "image_query_en": {
        "type": "string",
        "description": ("من ثلاث إلى خمس كلمات إنجليزية تصف موضوع القضية (الحدث) لا "
                        "أشخاصها -- مثال: Strait of Hormuz tanker لا اسم شخص"),
    },
}


def _validate_headlines(headlines: list[str], quotes_original: str, known_figures: list,
                         max_words: int) -> tuple[bool, str]:
    """تحقّق برمجي بعد الاستلام، بنفس مبدأ _validate_article_text: لا نثق
    بطاعة النموذج للقواعد المكتوبة في البرومبت وحدها. اسم العَلَم غير
    الموثَّق يُفحَص بإعادة استعمال youtube_extract.find_unsourced_name نفسها
    بلا تعديل -- نفس الدالة المستعملة لتحذيرات المراجعة أعلاه، ونفس تحفّظها
    المُوثَّق (لا استخراج أعلام عامّ، مطابقة قائمة صغيرة فقط)."""
    if not headlines[0].rstrip().endswith("؟"):
        return False, "العنوان الأول ليس بصيغة سؤال (لا ينتهي بـ؟)"
    for i, h in enumerate(headlines, start=1):
        if len(h.split()) > max_words:
            return False, f"العنوان {i} يتجاوز {max_words} كلمة"
        unsourced = youtube_extract.find_unsourced_name(h, quotes_original, known_figures)
        if unsourced:
            return False, f"العنوان {i} يحمل اسمًا غير موثَّق بالاقتباسات الأصلية ({unsourced!r})"
    return True, ""


def generate_headlines(topic: dict, member_points: list[dict], cfg: Config,
                        client: Anthropic | None = None, article_text: str | None = None
                        ) -> tuple[list[str] | None, str | None, str | None]:
    """غلاف رقيق فوق headlines_mod.propose_headlines (Issue #756) -- يبني
    مدخلات هذا المسار (نقاط القضية) ثم ينادي المشترك بكتلة config.yaml
    الخاصة به (youtube.review.headlines -- منفصلة عمدًا عن الكتلة العامة
    headlines، انظر توثيق config.yaml) ونظامه النصّي الخاص (HEADLINE_SYSTEM
    أعلاه). فحص الاسم غير الموثَّق (_validate_headlines) تحليليّ بحت فيبقى
    هنا كـ``extra_validate`` يشارك ميزانية إعادة المحاولة نفسها مع التحقّق
    العام، لا محاولات إضافية منفصلة. يعيد (ثلاثة عناوين، سبب فشل نهائي إن
    حدث -- None عند النجاح، image_query_en إن أعاده النموذج وإلا None).

    image_query_en (Issue #941) يصل عبر ``extra_properties``/``extra_result``
    في propose_headlines -- بلا نداء نموذج إضافي، ونفس ميزانية إعادة المحاولة.
    غيابه (فشل النداء كله، أو نجاح بلا هذا الحقل تحديدًا) يعيد None هنا؛
    المستدعي (run() أدناه) يعامله كاحتياط للبحث بالعربية كما كان، لا انهيارًا."""
    known_figures = cfg.path("youtube.extract.known_figures", [])
    max_words = cfg.path("youtube.review.headlines.max_words", 15)

    # quote_original لا quote_arabic -- نفس ما تستعمله _collect_warnings/
    # find_unsourced_name: aliases في known_figures صيغ لاتينية تُقارَن
    # بالاقتباس الأصلي بلغة الفيديو، لا بترجمته العربية.
    quotes_original = " ".join(p.get("quote_original", "") for p in member_points)
    # العناوين تُبنى من المقال المكتوب نفسه لا من عنوان القضية (Issue #1326): عنوان القضية يسبق الكتابة،
    # فكان عنوانان يتحدثان عن «عمدة إسطنبول» والمتن عن رئيس بلدية إزمير. بلا نص مقال (استدعاء قديم)
    # يبقى سلوك عنوان القضية كما كان.
    if article_text:
        user_content = (f"المقال المكتوب (العناوين يجب أن تصف ما فيه فعلًا لا ما سبقه):\n{article_text}\n\n"
                        f"النقاط المصدرية:\n{_points_block(member_points, cfg)}")
    else:
        user_content = f"القضية: {topic['title']}\n\nالنقاط المصدرية:\n{_points_block(member_points, cfg)}"

    def extra_validate(hls: list[str]) -> tuple[bool, str]:
        return _validate_headlines(hls, quotes_original, known_figures, max_words)

    extra: dict = {}
    headlines, error = headlines_mod.propose_headlines(
        user_content, cfg, "youtube.review.headlines",
        system=HEADLINE_SYSTEM, client=client, extra_validate=extra_validate,
        extra_properties=IMAGE_QUERY_EXTRA_PROPERTY, extra_result=extra)
    image_query_en = str(extra.get("image_query_en") or "").strip() or None
    return headlines, error, image_query_en


HEADLINES_HEADER = "🏷️ عناوين مقترحة (الأول سؤال وهو الافتراضي):"


def _append_headlines(article_text: str, headlines: list[str]) -> str:
    """يضيف قسم العناوين المقترحة في ذيل المقال، بعد قسم التحذيرات إن وُجد
    (run() يستدعي _append_warnings أولًا) -- ترتيب ثابت يعتمده
    youtube_publish.split_headlines عند القراءة. خلافًا لقسم التحذيرات،
    يُضاف دومًا (ثلاثة عناوين مضمونة دومًا -- انظر احتياط run() عند فشل
    generate_headlines)."""
    lines = "\n".join(f"{i}. {h}" for i, h in enumerate(headlines, start=1))
    return f"{article_text.rstrip()}\n\n---\n{HEADLINES_HEADER}\n{lines}\n"


# ── كلمات بحث الصورة الإنجليزية (Issue #941) ──
#
# youtube_article وyoutube_publish عمليتان منفصلتان (سيران CLI متتاليان في
# youtube-articles.yml، لا نداء دالة مباشر) -- الحقل الوحيد الذي يصلهما معًا
# هو نصّ ملف المقال نفسه على القرص. بنفس آلية WARNINGS_HEADER/HEADLINES_HEADER
# تمامًا: قسم مذيَّل يُقرأ لاحقًا بدالة split مقابلة في youtube_publish.py.

IMAGE_QUERY_HEADER = "🖼️ كلمات بحث الصورة (إنجليزية):"


def _append_image_query(article_text: str, image_query_en: str | None) -> str:
    """يضيف القسم فقط عند توفّر قيمة فعلية (فشل نداء العناوين، أو نجاحه بلا
    هذا الحقل تحديدًا، كلاهما يُعيد None من generate_headlines) -- غيابه هنا
    يعني عودة youtube_publish إلى البحث بالعربية كسلوكها الحالي، لا انهيارًا."""
    if not image_query_en:
        return article_text
    return f"{article_text.rstrip()}\n\n---\n{IMAGE_QUERY_HEADER}\n{image_query_en}\n"


# Issue #695 (البرومبت الرابع): النسخة الرابعة من prompts/youtube_article.md
# (يستبدلها المالك مباشرةً -- خارج نطاق هذا التعديل) تعكس بند "الأطروحة نثرًا"
# بالكامل: سطر `**التقدير:**` كان إلزاميًا فصار ممنوعًا (آخر ما تبقّى من هيكل
# المذكّرة)، وصار وجوده سببًا للرفض لا غيابه. عبارة سلّم الترجيح لم تعد
# محصورة داخل سطر التقدير (الذي زال أصلًا) فتُقبَل في أي موضع من "المتن"
# (كل ما بعد العنوان الرئيسي حتى نهاية النص -- Issue #941 ألغى قسم
# ## المصادر الذي كان يحدّ "المتن" سابقًا، فصار المتن النص كله) لكنها تبقى
# مطلوبة: وجودها هو الدليل
# الآلي الوحيد على أن الحكم مذكور، لا مجرّد سرد وقائع بلا خلاصة. النسب
# المئوية والطوابع الزمنية المقوّسة ([٩:٥٣]) صارتا ممنوعتين تمامًا في المتن
# (نصّ دليل War on the Rocks: النسب "لغة تقرير استخباري"، والطوابع المقوّسة
# "تكسر القراءة" -- يجب أن يُدفَن الطابع تحت رابط الاقتباس بدل ذلك).
_PERCENT_RE = re.compile(r"[0-9٠-٩][0-9٠-٩,.\-–—\s]*[%٪]")
_BRACKET_TIMESTAMP_RE = re.compile(r"\[[0-9٠-٩]{1,2}:[0-9٠-٩]{2}(?::[0-9٠-٩]{2})?\]")

# "يفترض أن" وحدها ليست ممنوعة (نصّ الـIssue) -- المشكلة تكرارها في صيغة عرض
# مصادر متقابلة ("فلان يفترض... وفلان يفترض...")، وقسم الافتراضات الكامنة
# يبقى مطلوبًا مدمجًا في السرد. لذا حدّ تكرار (youtube.article.max_assumption_phrases)
# لا منع تام مثل بقية banned_phrases أدناه.
ASSUMPTION_PHRASE = "يفترض أن"

# مؤشّر «فاعل الجملة متحدث» (نصّ الـIssue، البند ٣): محاولة قياس هل المقال
# يكتب عن مصادره لا عن الحدث. لا مكتبة تحليل نحوي عربي في هذا المشروع
# (requirements.txt خالٍ منها)، فالقياس هنا معجميّ سطحي بديل -- صدر الجملة
# (أول ست كلمات) يحوي كلمة من اسم أحد المتحدثين -- لا تحليل فعلي للفاعل
# النحوي. هذا تقريب ضعيف عمدًا لا مموَّه: العربية غالبًا فعلية الترتيب
# (فعل-فاعل-مفعول) فقد يقع الفاعل الحقيقي بعد الفعل لا في صدر الجملة، وقد
# يُذكر اسم متحدث في جملة هو فيها مفعول به أو مضاف إليه لا فاعلاً، وحقل
# "speaker" في نقاط الاختبار نفسها قد يحمل لقبًا عامًّا ("ناطق"، "متحدث") لا
# اسم علم -- فيطابق أي جملة تبدأ بذلك اللقب العام خطأً. لهذا يبقى الإخراج هنا
# **تحذيرًا استرشاديًا فقط يظهر في stats وذيل المقال** لا حارس رفض -- نصّ
# الـIssue نفسه يشترط هذا بالضبط متى تبيّن أن القياس غير موثوق آليًا، وحارس
# يرفض مقالات صحيحة أسوأ من ترك العيب بلا قياس أصلًا.
_SENTENCE_SPLIT_RE = re.compile(r"[.!؟]+|\n+")
_WORD_STRIP_CHARS = "،:؛\"'«»()[]"


def _speaker_subject_ratio(article_text: str, member_points: list[dict]) -> tuple[float, int]:
    """يعيد (نسبة الجمل التي يبدو فاعلها متحدثًا، عدد الجمل الكلي) -- انظر
    التعليق أعلاه لحدود هذا القياس المعجمي الصريحة. لا استبعاد لأي جزء من
    النص هنا (Issue #941): قسم ## المصادر الذي كان يُستبعَد صار ممنوعًا كليًا
    من بنية المقال نفسها (_validate_article_text)، فمقال صالح لا يحمله أصلًا
    -- النص المستلَم هنا "متن" كامل بلا حاجة لقصّ أي مدى منه."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(article_text) if s.strip()]
    name_tokens = {
        tok.strip(_WORD_STRIP_CHARS) for p in member_points
        for tok in str(p.get("speaker", "")).split() if len(tok) > 2
    }
    if not sentences or not name_tokens:
        return 0.0, len(sentences)
    speaker_led = sum(
        1 for s in sentences
        if any(w.strip(_WORD_STRIP_CHARS) in name_tokens for w in s.split()[:6])
    )
    return speaker_led / len(sentences), len(sentences)


def _speaker_subject_warning(article_text: str, member_points: list[dict],
                              cfg: Config) -> str | None:
    """يعيد سطر تحذير عند تجاوز الحدّ الاسترشادي، أو None دون ذلك. لا يُستدعى
    من _validate_article_text عمدًا -- ليس حارس رفض (انظر التعليق أعلاه)،
    فتُلحَق نتيجته بذيل المقال عبر _collect_warnings/run() كأي تحذير مراجعة آخر."""
    ratio, sentence_count = _speaker_subject_ratio(article_text, member_points)
    if sentence_count == 0:
        return None
    threshold = cfg.path("youtube.article.max_speaker_subject_ratio", 0.35)
    if ratio <= threshold:
        return None
    return (f"مؤشّر فاعل الجملة متحدث (استرشادي غير موثوق لا رفض): {ratio:.2f} من "
            f"{sentence_count} جملة يتجاوز الحدّ الاسترشادي {threshold} -- راجع يدويًا هل "
            f"المقال عن الأشخاص لا عن الحدث")


# البنية "النسخة الثانية" (سطر تقدير + خمسة أقسام ## على الأقل بأسماء ثابتة +
# مصادر) استُبدلت ببنية "النسخة الثالثة" من prompts/youtube_article.md (Issue
# #690): نثر متّصل بلا أي عنوان قسم إطلاقًا عدا قسم المصادر. السبب بحثي لا
# ذوقي -- ورقة "The Last Fingerprint" (arXiv:2603.27006) وقياس على اثني عشر
# نموذجًا أثبتا أن فرض عناوين ## ثابتة (البنية القديمة) يغذّي توجّه النماذج
# البنيوي المستبطَن من بيانات التدريب المشبَعة بماركداون بدل مقاومته. الحارس
# هنا معكوس تمامًا عن سابقه: كان يفرض خمسة أقسام على الأقل، ويفرض الآن صفر
# أقسام عدا المصادر -- وأضاف حظر عناصر ماركداون إضافية (شرطة معترضة، قوائم،
# تغميق، فاصل أفقي) تنجو من تعليمة الكبت العامة في البرومبت لأنها علامات
# ترقيم/بنية مشروعة في آن، فتُمنع بالاسم في الكود لا في البرومبت وحده -- نفس
# مبدأ likelihood_terms أدناه: قاعدة قابلة للكسر النصّي تحتاج فرضًا آليًا، لا
# الثقة بطاعة النموذج وحدها.
#
# Issue #941 -- عكس إضافي لاحق: حتى قسم ## المصادر نفسه صار ممنوعًا لا
# إلزاميًا. الشاهد المقيس: البطاقات تخرج بلا صورة تعبيرية لأن البحث (Wikimedia/
# Openverse) يجري بعبارات عربية، ونصّ المقال يذيَّل بقسم مصادر يسمّي القنوات
# صراحةً رغم أن التصميم البصري (image_source_line أدناه في youtube_publish.py)
# يتعمَّد عدم نسبة المقال لقنواته. القاعدة صارت: صفر أقسام ## على الإطلاق --
# لا استثناء للمصادر بعد اليوم. سطر «المصدر:» على البطاقة (عدد القنوات، لا
# أسماؤها) يبقى المكان الوحيد الذي يظهر فيه أي إشارة لمصدر المقال.
_SECTION_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_ESTIMATE_LINE_RE = re.compile(r"^\*\*التقدير:\*\*.*$", re.MULTILINE)
_HR_RE = re.compile(r"^-{3,}[ \t]*$", re.MULTILINE)
_LIST_LINE_RE = re.compile(r"^[ \t]*(?:[-*][ \t]+|\d+\.[ \t]+)", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*[^*\n]+\*\*")
# تركيب التقابل "ليس... بل" / "لا... بل" (البصمة اللغوية الأوضح، نصّ الـIssue)
# داخل الجملة الواحدة -- محصور بحدود الجملة (نقطة/علامة استفهام/تعجّب/سطر
# جديد) حتى لا يمتدّ المطابقة عبر جمل غير مترابطة.
_CONTRAST_RE = re.compile(r"(?:ليس|لا)\b[^.؟!\n]*?\bبل\b")

# احتياطي إن غاب youtube.article.likelihood_terms من config.yaml -- القيمة
# الفعلية المستعملة دومًا تُقرأ من هناك (سلّم شيرمان كنت، النقطة ٣ من الـIssue).
DEFAULT_LIKELIHOOD_TERMS = (
    "شبه مؤكّد", "مرجّح بقوة", "مرجّح", "الاحتمالان متساويان", "مستبعد جدًا", "مستبعد",
)

# احتياطي إن غاب youtube.article.banned_phrases من config.yaml -- القائمة
# الفعلية تُقرأ من هناك دومًا (حارس التكرار القالبي، Issue #690 النقطة ٣؛
# مراجعة سبعة مقالات كشفت هذه العبارات تحديدًا متكرّرة في كل مقال). ثلاث
# أضيفت في Issue #695 (النسخة الرابعة): الثقة القالبية ("بثقة منخفضة/عالية")
# التي يستبدلها البرومبت الجديد بذكر مصدر الترجيح نثرًا، وصيغة "يبقى القارئ
# أمام" التي تُظهر عرض مصدرين متقابلين بدل حجّة عن الحدث. "يفترض أن" ليست
# هنا عمدًا -- لها حدّ تكرار لا منع تام، انظر ASSUMPTION_PHRASE أعلاه.
DEFAULT_BANNED_PHRASES = (
    "سند هذا التقدير", "لو افترضنا أن الرواية", "قشّة في الريح", "الأثر القريب أن",
    "يبقى مفتوحًا", "تحمل في طيّاتها", "في هذا السياق", "تجدر الإشارة",
    "من الجدير بالذكر", "الأيام القادمة كفيلة", "كل الاحتمالات مفتوحة",
    "بثقة منخفضة", "بثقة عالية", "يبقى القارئ أمام",
)


def _sections_desc(text: str) -> str:
    """يصف الأقسام ## الموجودة فعليًا في المقال -- تُلحَق بكل رسالة فشل
    (النقطة ٤ من الـIssue) بدل الاكتفاء بذكر الشرط المخفق وحده، وإلا نعود
    للتخمين عند أي تعديل مستقبلي على البرومبت."""
    titles = _SECTION_RE.findall(text)
    if not titles:
        return "لم يوجد أي قسم ## "
    return f"وجد {len(titles)} أقسام ({' · '.join(titles)})"


# ── قواعد النسبة والاقتباس (Issue #1272، قرار صاحب المشروع) ──
#
# شاهد المقال المنشور fe2a7c6fc1a0 (قناتاه ILTV والجزيرة): «بحسب ما عرضه مقدّم برنامج
# على الجزيرة» بلا اسم، واقتباس لترامب يصل جملتين بـ«...» فيبدو ربطًا لم تقله التغطية
# الموثّقة، وILTV لا تُذكر. القياس على 106 مقالات: 29 تنسب إلى «مقدّم برنامج» بلا اسم، 38
# لا تسمّي قناة، 10 فيها اقتباس فوق 25 كلمة، 2 فيها «...». سببان في البرومبت نفسه (منع
# أسماء القنوات #941 والأمر بـ«مقدّم برنامج على X») ألغاهما صاحب المشروع، وهذه الفحوص
# تفرض الباقي في الكود لا في طاعة النموذج وحدها.
_TASHKEEL_STRIP_RE = re.compile(r"[ً-ٰٟـ]")
_AR_LETTER = r"ء-ي"
# فعل نسبة بأشكاله (واو/فاء في أوله، مضارع بياء أو تاء) ثم اختياريًا «ما عرضه/قاله…».
_ATTRIBUTION_VERB = (
    r"(?:بحسب|وفق[اً]?|حسب|[يت]?قول|قال[ت]?|[يت]ر[ىي]|أشار[ت]?|[يت]شير|طرح[ت]?|[يت]طرح|"
    r"سأل[ت]?|[يت]سأل|لفت|[يت]لفت)")
_ATTRIBUTION_OBJECT = r"(?:ما\s+(?:عرض|قال|طرح|ذكر|أورد)(?:ه|ته|ها|وه)?\s+)?"
_QUOTE_RE = re.compile(r"«([^«»]*)»")
_ELLIPSIS_RE = re.compile(r"\.{3,}|…")
_SENTENCE_END_CHARS = ".!؟?\n"
FIGURE_QUOTE_WARNING = ("اقتباس مباشر منسوب لشخصية عامة: تحقّق من مطابقته لما نقلته الصحافة")


def _fold_roles(text: str) -> str:
    return _TASHKEEL_STRIP_RE.sub("", text)


def display_channel_name(name: str, cfg: Config) -> str:
    """اسم القناة كما يُعرض في المتن: name_ar من channels إن وُجد وإلا name (Issue #1272 --
    «ערוץ 14» تصير «القناة 14» فيكتبها النموذج بحروف يقرؤها القارئ)."""
    for ch in cfg.path("channels", []) or []:
        if isinstance(ch, dict) and ch.get("name") == name and ch.get("name_ar"):
            return ch["name_ar"]
    return name


def _unnamed_role_violations(body: str, cfg: Config) -> list[str]:
    words = cfg.path("youtube.article.unnamed_role_words", ["مقدّم", "مقدم", "مذيع", "مذيعة", "محاور", "الضيف"])
    roles = sorted({_fold_roles(w) for w in words if isinstance(w, str) and w}, key=len, reverse=True)
    if not roles:
        return []
    role_alt = "|".join(re.escape(r) for r in roles)
    pat = re.compile(
        rf"(?<![{_AR_LETTER}])[وف]?{_ATTRIBUTION_VERB}\s+{_ATTRIBUTION_OBJECT}"
        rf"(?:{role_alt})(?![{_AR_LETTER}])")
    folded = _fold_roles(body)
    return [f"نسبة إلى دور بلا اسم علم ({m.group(0).strip()!r}): انسب القول إلى القناة نفسها "
            f"أو اكتب اسم المتحدث أولًا"
            for m in pat.finditer(folded)][:1]


# ── نسبة مجهولة واسم المتحدث (Issue #1326، فحوص حاسمة في الكود لا تعتمد على المحرر) ──
#
# شاهد d96e19b97bd2: «أفادت المعطيات المتداولة…» لمصدر واحد غير محسوم الاسم، و«محلل عسكري في البرنامج
# ذاته» لمتحدث له اسم. النسبة إلى «المعطيات المتداولة» لا تعرّف القارئ بمن قال، واسم المتحدث المسمّى
# لا يجوز أن يسقط من المتن.
def _vague_attribution_violations(body: str, cfg: Config) -> list[str]:
    phrases = cfg.path("youtube.article.vague_attribution", []) or []
    folded = _fold_mention(body)
    found = [p for p in phrases if isinstance(p, str) and p and _fold_mention(p) in folded]
    return [f"نسبة مجهولة ({' · '.join(found)}): انسب القول إلى متحدث باسمه أو إلى قناته"] if found else []


def vague_phrases_in(text: str, cfg: Config) -> list[str]:
    return [p for p in (cfg.path("youtube.article.vague_attribution", []) or [])
            if isinstance(p, str) and p and _fold_mention(p) in _fold_mention(text)]


def _arabic_tokens(text: str) -> list[str]:
    toks = [t.strip(_WORD_STRIP_CHARS + ".,؟!-") for t in _fold_roles(text).replace("،", " ").split()]
    return [t for t in toks if t and re.search(f"[{_AR_LETTER}]", t)]


def speaker_name_tokens(speaker: str, channel: str, cfg: Config) -> list[str]:
    """ما يبقى من حقل speaker بعد حذف كلمات الأدوار واسم القناة؛ فارغ = متحدث غير مسمّى (صفته وحدها)."""
    roles = {_fold_mention(w) for w in (cfg.path("youtube.article.role_words", []) or []) if isinstance(w, str)}
    chan = {_fold_mention(t) for t in _arabic_tokens(display_channel_name(channel, cfg))}
    chan |= {_fold_mention(t) for t in _arabic_tokens(channel)}
    out = []
    for t in _arabic_tokens(speaker):
        # رقم لاصق بالصفة («متحدث 2») ليس اسمًا
        f = re.sub(r"[0-9]+", "", _fold_mention(t))
        bare = f[2:] if f.startswith("ال") and len(f) > 3 else f
        if f in roles or bare in roles or f in chan or len(f) < 2:
            continue
        out.append(t)
    return out


def _speaker_name_violations(body: str, member_points: list[dict], cfg: Config) -> list[str]:
    folded = _fold_mention(body)
    missing: list[str] = []
    for p in member_points or []:
        name = speaker_name_tokens(p.get("speaker", ""), p.get("channel", ""), cfg)
        if not name:
            continue
        full = _fold_mention(" ".join(name))
        if full in folded or _fold_mention(name[-1]) in folded:
            continue
        shown = " ".join(name)
        if shown not in missing:
            missing.append(shown)
    return [f"اسم متحدث مسمّى غاب عن المتن ({' · '.join(missing)}): اذكر اسمه عند أول نسبة إليه"] if missing else []


def relative_time_warnings(text: str, cfg: Config) -> list[str]:
    """تنبيه لكل عبارة زمن نسبي في المتن (قبل ساعات، اليوم…): القارئ يقرأ بعد النشر بأيام."""
    out = []
    folded = _fold_mention(text)
    for w in cfg.path("youtube.article.relative_time_words", []) or []:
        if not isinstance(w, str) or not w:
            continue
        if re.search(rf"(?<![{_AR_LETTER}]){re.escape(_fold_mention(w))}(?![{_AR_LETTER}])", folded):
            out.append(f"زمن نسبي في المتن: «{w}» — حوّله إلى تاريخ صريح من تاريخ الفيديو")
    return out


def stale_video_warning(member_points: list[dict], cfg: Config, now: datetime | None = None) -> str | None:
    """«⏳ أحدث فيديو منشور قبل N أيام» حين يتجاوز youtube.review.stale_days: مقال عن حدث قد تجاوزه تطور."""
    dates = []
    for p in member_points or []:
        try:
            dates.append(datetime.strptime(str(p.get("video_published") or "")[:10], "%Y-%m-%d"))
        except ValueError:
            continue
    if not dates:
        return None
    now = now or datetime.now(timezone.utc)
    age = (now.replace(tzinfo=None) - max(dates)).days
    if age > cfg.path("youtube.review.stale_days", 2):
        return f"⏳ أحدث فيديو منشور قبل {age} أيام — تحقّق أن الحدث لم يتجاوزه تطور"
    return None


_HINDI_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize_digits(text: str) -> str:
    """الأرقام الهندية ← لاتينية في عنوان المقال ومتنه بعد الكتابة (نمط واحد على البطاقة والمنشور)."""
    return text.translate(_HINDI_DIGITS)



def _quote_violations(body: str, cfg: Config) -> list[str]:
    max_words = cfg.path("youtube.article.max_quote_words", 25)
    out = []
    for m in _QUOTE_RE.finditer(body):
        q = m.group(1)
        if _ELLIPSIS_RE.search(q):
            out.append(f"اقتباس «» يحوي «...» يصل كلامين: لا يُقتبس إلا ما قبلها أو ما بعدها ({q[:40]!r})")
            continue
        n = len(q.split())
        if n > max_words:
            out.append(f"اقتباس «» من {n} كلمة (السقف {max_words}): انقل الزائد كلامًا غير مباشر منسوبًا")
    return out


_INDIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _fold_mention(text: str) -> str:
    """طيّ الطرفين قبل مقارنة ذكر القناة (Issue #1272): بلا تشكيل، أ/إ/آ ← ا، أرقام هندية ← لاتينية،
    casefold -- فـ«ايران انترناشيونال» بلا همزة تطابق «إيران إنترناشيونال»."""
    t = _TASHKEEL_STRIP_RE.sub("", text).translate(_INDIC_DIGITS)
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    return t.casefold()


def channel_mention_forms(name: str, cfg: Config) -> list[str]:
    """الصيغ المقبولة لذكر قناة في المتن: channels[].mention_forms إن وُجدت (قائمة كاملة)، وإلا
    [الاسم المعروض، name]. العربية مثلًا لا يكفيها «العربية» لأنها ترد في «الدول العربية»."""
    for ch in cfg.path("channels", []) or []:
        if isinstance(ch, dict) and ch.get("name") == name:
            forms = ch.get("mention_forms")
            if forms:
                return [f for f in forms if isinstance(f, str) and f]
            break
    return [display_channel_name(name, cfg), name]


def _missing_channels(body: str, member_points: list[dict], cfg: Config) -> list[str]:
    seen, missing = set(), []
    folded = _fold_mention(body)
    for p in member_points or []:
        name = (p.get("channel") or "").strip()
        if not name:
            continue
        shown = display_channel_name(name, cfg)
        if shown in seen:
            continue
        seen.add(shown)
        if not any(_fold_mention(f) in folded for f in channel_mention_forms(name, cfg)):
            missing.append(shown)
    return missing


def figure_quote_warnings(text: str, cfg: Config) -> list[str]:
    """تنبيه لا رفض (Issue #1272): «» في الجملة نفسها بعد اسم من youtube.extract.known_figures.
    اقتباس شخصية عامة المترجم آليًا قد لا يطابق ما نقلته الصحافة، فيراجعه البشر؛ يمرّ عبر
    _append_warnings فيظهر في المراجعة ويُنزَع قبل النشر (youtube_publish.split_warnings)."""
    figures = cfg.path("youtube.extract.known_figures", []) or []
    # محتوى الاقتباسات السابقة يُخفى كي لا تقطع نقطة داخله حدّ الجملة
    masked = _QUOTE_RE.sub(lambda m: "«" + "؛" * len(m.group(1)) + "»", text)
    names: list[str] = []
    for m in _QUOTE_RE.finditer(masked):
        before = masked[:m.start()]
        cut = max(before.rfind(c) for c in _SENTENCE_END_CHARS)
        sentence = before[cut + 1:]
        for fig in figures:
            ar = fig.get("ar") if isinstance(fig, dict) else None
            if ar and ar in sentence and ar not in names:
                names.append(ar)
    return [f"{FIGURE_QUOTE_WARNING} ({n})" for n in names]


def article_violations(text: str, cfg: Config, member_points: list[dict] | None = None) -> list[str]:
    """كل مخالفات المقال بترتيب الفحص (Issue #1272) -- القائمة الفارغة قبول. _validate_article_text
    يعيد أولها، فمن لا يمرّر member_points يبقى سلوكه (عدا ما ألغاه القرار) كما كان."""
    violations: list[str] = []
    desc = _sections_desc(text)

    if not text.strip().startswith("#"):
        violations.append(f"لا يبدأ بعنوان رئيسي (# ): {desc}")

    # Issue #695: عكس تام لسابقه -- سطر **التقدير:** كان إلزاميًا (النسخة
    # الثالثة) وصار ممنوعًا (الرابعة، "الأطروحة نثرًا لا صندوقًا"). وجوده هنا
    # سبب رفض وحده، بصرف النظر عن محتواه.
    estimate_match = _ESTIMATE_LINE_RE.search(text)
    if estimate_match:
        line_no = text[:estimate_match.start()].count("\n") + 1
        violations.append(f"صندوق تقدير مغمّق في السطر {line_no} (ممنوع في النسخة الرابعة): {desc}")

    # Issue #941: أي عنوان ## صار ممنوعًا كليًا، بلا استثناء للمصادر. (منع أسماء القنوات في
    # المتن الذي رافقه أُلغي في Issue #1272؛ منع القسم نفسه باقٍ.)
    if _SECTION_RE.search(text):
        violations.append(f"عنوان/عناوين ## ممنوعة كليًا (بما فيها ## المصادر): {desc}")

    word_count = len(text.split())
    min_words = cfg.path("youtube.article.min_words", 300)
    max_words = cfg.path("youtube.article.max_words", 750)
    if word_count < min_words:
        violations.append(f"قصير جدًا ({word_count} كلمة، الأدنى {min_words}): {desc}")
    if word_count > max_words:
        violations.append(f"طويل جدًا ({word_count} كلمة، الأعلى {max_words}): {desc}")

    # المتن: من نهاية العنوان الرئيسي حتى نهاية النص كاملًا (Issue #941 --
    # لا استثناء لأي فاصل أفقي بعد اليوم).
    title_line_end = text.find("\n")
    body_start = title_line_end if title_line_end != -1 else len(text)
    body_for_checks = text[body_start:]
    hr_matches = list(_HR_RE.finditer(body_for_checks))
    if hr_matches:
        violations.append(f"{len(hr_matches)} فاصل أفقي (---) في المتن (ممنوع كليًا الآن): {desc}")

    dash_count = body_for_checks.count("—")
    if dash_count:
        violations.append(f"{dash_count} شرطة معترضة (—) في المتن: {desc}")

    list_lines = len(_LIST_LINE_RE.findall(body_for_checks))
    if list_lines:
        violations.append(f"{list_lines} سطر قائمة في المتن: {desc}")

    bold_spans = len(_BOLD_RE.findall(body_for_checks))
    if bold_spans:
        violations.append(f"{bold_spans} نصّ غامق في المتن: {desc}")

    # Issue #695: النسب المئوية "لغة تقرير استخباري" والطوابع الزمنية المقوّسة
    # "تكسر القراءة" -- كلتاهما ممنوعة تمامًا في المتن.
    percent_matches = _PERCENT_RE.findall(body_for_checks)
    if percent_matches:
        violations.append(f"{len(percent_matches)} نسب مئوية في المتن "
                          f"({' · '.join(percent_matches)}): {desc}")

    timestamp_matches = _BRACKET_TIMESTAMP_RE.findall(body_for_checks)
    if timestamp_matches:
        violations.append(f"{len(timestamp_matches)} طوابع مقوّسة في المتن "
                          f"({' · '.join(timestamp_matches)}): {desc}")

    # Issue #1272 (بند 1f): حُذف شرط وجود عبارة من سلّم الترجيح -- الترجيح لم يعد إلزاميًا
    # (مقال fe2a7c6fc1a0 ختم بـ«مرجّح بقوة» استنادًا إلى متحدث واحد عن مبيعات شركته). السلّم
    # يبقى للبرومبت: لا تُستعمل عبارته إلا إن أسندها متحدثان مختلفان فأكثر.

    banned_phrases = cfg.path("youtube.article.banned_phrases", list(DEFAULT_BANNED_PHRASES))
    found_banned = [p for p in banned_phrases if p in text]
    if found_banned:
        violations.append(f"عبارة/عبارات محظورة وردت ({' · '.join(found_banned)}): {desc}")

    # "يفترض أن" حدّ تكرار لا منع تام (نصّ الـIssue) -- قسم الافتراضات
    # الكامنة يبقى مطلوبًا مدمجًا في السرد، والمرفوض تكرارها في صيغة عرض
    # مصادر متقابلة لا ذكرها أصلًا.
    max_assumption = cfg.path("youtube.article.max_assumption_phrases", 2)
    assumption_count = text.count(ASSUMPTION_PHRASE)
    if assumption_count > max_assumption:
        violations.append(f"عبارة {ASSUMPTION_PHRASE!r} تكرّرت {assumption_count} مرات "
                          f"(الحدّ {max_assumption}): {desc}")

    max_contrast = cfg.path("youtube.article.max_contrast_constructions", 1)
    contrast_count = len(_CONTRAST_RE.findall(text))
    if contrast_count > max_contrast:
        violations.append(f"تركيب التقابل تكرّر {contrast_count} مرات (الحدّ {max_contrast}): {desc}")

    violations += _unnamed_role_violations(body_for_checks, cfg)
    violations += _vague_attribution_violations(body_for_checks, cfg)
    violations += _quote_violations(body_for_checks, cfg)
    if member_points is not None:
        violations += _speaker_name_violations(body_for_checks, member_points, cfg)
        missing = _missing_channels(body_for_checks, member_points, cfg)
        if missing:
            violations.append(f"قناة/قنوات من النقاط غائبة عن المتن ({' · '.join(missing)}): "
                              f"عرّف كل متحدث بقناته عند أول ذكر")
    return violations


def _validate_article_text(text: str, cfg: Config,
                           member_points: list[dict] | None = None) -> tuple[bool, str]:
    violations = article_violations(text, cfg, member_points)
    return (False, violations[0]) if violations else (True, "")


def point_source_texts(member_points: list[dict]) -> list[str]:
    """نصوص النقاط بلغتها الأصلية (اقتباس المتحدث وعنوان الفيديو واسمه) — مدخل تدقيق الأسماء
    (Issue #1252) والوقاية منها؛ بيانات لا تعليمات كسائر محتوى النقاط."""
    return [t for p in member_points
            for t in (p.get("quote_original", ""), p.get("speaker", ""), p.get("video_title", "")) if t]


def draft_article(topic: dict, member_points: list[dict], cfg: Config,
                   client: Anthropic | None = None) -> tuple[str | None, str | None]:
    """نداء نموذج أقوى، إخراج نصّ عادي (لا tool_use) -- انظر توثيق أعلى
    الملف. يعيد (نصّ المقال، سبب الفشل بعد استنفاد المحاولات -- None عند
    النجاح)."""
    model = cfg.path("youtube.article.model", "claude-opus-5")
    max_tokens = cfg.path("youtube.article.max_tokens", 3000)
    max_retries = cfg.path("youtube.article.max_retries", 3)
    client = client or Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))

    model_agreement = _MODEL_FACING_AGREEMENT.get(topic["agreement"], topic["agreement"])
    user_content = (
        f"مؤشّر الخلاف بين المصادر لهذه القضية: {model_agreement}\n\n"
        f"النقاط المصدرية (المصدر الوحيد المسموح استعماله -- لا معلومة من "
        f"خارجها):\n{_points_block(member_points, cfg)}"
    )
    # الوقاية قبل الكتابة (Issue #1252): أسماء معتمدة سلفًا ورد أصلها اللاتيني في اقتباسات المتحدثين
    from . import names_audit
    name_note = names_audit.names_note(point_source_texts(member_points), cfg)
    if name_note:
        user_content += f"\n\n{name_note}"
    date_note = cfg.path("youtube.article.date_note", "")
    if date_note and any(p.get("video_published") for p in member_points):
        user_content += f"\n\n{date_note}"

    last_reason = ""
    last_resp = None
    messages = [{"role": "user", "content": user_content}]
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=load_article_prompt(),
                messages=list(messages),
                # لا تُضِف temperature -- نماذج هذا المشروع ترفضها بـ400.
            )
        except APIError as exc:
            return None, f"فشل نداء الكتابة: {exc}"

        last_resp = resp
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        ok, reason = _validate_article_text(text, cfg, member_points)
        if ok:
            return text, None
        last_reason = reason
        # إعادة المحاولة بالسبب (Issue #1272): المحاولة التالية تُخبَر بما رُفضت لأجله وتُعطى
        # نصّها السابق لتصحّحه وحده -- بلا هذا يعيد النموذج الكتابة من الصفر ويكرّر المخالفة.
        # عدد النداءات يبقى محكومًا بـmax_retries وحده.
        messages = [messages[0], {"role": "assistant", "content": text or "(لا نصّ)"},
                    {"role": "user", "content":
                     f"رُفضت المحاولة السابقة لهذا السبب: {reason} — صحّحه دون تغيير ما سواه"}]
        # فحص stop_reason صراحةً (Issue #662 تعليق المتابعة) -- أقسام ظهرت
        # بالترتيب الصحيح ثم انقطعت، ومحاولات أعادت صفر أقسام رغم إنتاج نصّ:
        # نفس نمط القطع المشخَّص سابقًا في youtube_cluster/youtube_extract،
        # وبلا هذا التسجيل نعود إلى التخمين في المرة القادمة.
        stop_reason = getattr(resp, "stop_reason", None)
        if stop_reason == "max_tokens":
            usage = getattr(resp, "usage", None)
            output_tokens = getattr(usage, "output_tokens", "؟") if usage is not None else "؟"
            log.warning("قُطع إخراج المقال (stop_reason: max_tokens) — %r، %s رمز مستهلك",
                        topic["title"][:40], output_tokens)
            last_reason = f"[stop_reason=max_tokens، {output_tokens} رمز مستهلك] {reason}"
        else:
            log.warning("محاولة %d/%d: مقال %r غير مطابق للبنية المطلوبة "
                        "(stop_reason=%s، %s)", attempt, max_retries, topic["title"][:40],
                        stop_reason, reason)

    usage_note = ""
    usage = getattr(last_resp, "usage", None)
    if usage is not None:
        usage_note = (f"، رموز مستهلكة: مدخل {getattr(usage, 'input_tokens', '؟')}"
                       f"/مخرج {getattr(usage, 'output_tokens', '؟')}")
    return None, (f"تعذّر الحصول على مقال مطابق للبنية بعد {max_retries} محاولة/محاولات"
                  f"{usage_note}: {last_reason}")


def _extract_headline(article_text: str) -> str:
    first_line = article_text.strip().splitlines()[0] if article_text.strip() else ""
    return first_line.lstrip("#").strip()


_SLUG_STRIP_RE = re.compile(r"[^\w]+", re.UNICODE)


def _slugify(title: str, max_len: int = 60) -> str:
    slug = _SLUG_STRIP_RE.sub("-", title).strip("-")
    return slug[:max_len] or "قضية"


def build_index(saved: list[dict]) -> str:
    # عمود «الفيديوهات» (Issue #1092) بين القنوات والخلاف -- معرّفات الفيديو
    # المصدرية مرتّبة أهميةً (item.get بلا مفتاح إلزامي: توافقًا مع مسودات/
    # اختبارات لا تحمله). src/youtube_publish.py:parse_index يقرأه بترتيب
    # الأعمدة نفسه بالضبط -- تغيير هذا الترتيب يحتاج تعديل _INDEX_ROW_RE هناك.
    lines = ["# فهرس مقالات يوتيوب", "",
             "| # | العنوان | الحدث | الطبقة | الكتل | القنوات | الفيديوهات | الخلاف | تنبيهات |",
             "|---|---|---|---|---|---|---|---|---|"]
    for item in saved:
        warnings_count = item.get("warnings_count", 0)
        # ثلاثة تنبيهات فأكثر تُعلَّم بوضوح (نص الـIssue) -- ⚠️ + رقم بارز
        # لا مجرّد رقم صامت يغرق بين أعمدة الجدول الأخرى.
        marker = f"⚠️ **{warnings_count}**" if warnings_count >= 3 else str(warnings_count)
        lines.append(
            f"| {item['number']} | [{item['headline']}]({item['filename']}) | "
            f"{item['event']} | {item['layer']} | {', '.join(item['blocs'])} | "
            f"{', '.join(item['channels'])} | {', '.join(item.get('video_ids', []))} | "
            f"{item['agreement']} | {marker} |")
    return "\n".join(lines) + "\n"


def save_articles(date_str: str, articles: list[dict]) -> list[dict]:
    """يكتب ملفات المقالات المرقَّمة + index.md. الترقيم متتابع بلا فجوات
    (أول مقال ناجح 01، الثاني 02...) بصرف النظر عن رتبة قضيته الأصلية --
    قضية تخطّاها الحظر أو فشلت كتابتها لا تترك فجوة رقمية في القائمة التي
    يقرؤها المالك أولًا. `item["warnings"]` اختياري (Issue #662 العطل ٣
    بند ج) -- غيابه يعني صفر تنبيهات، لا عطلًا."""
    out_dir = ARTICLES_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict] = []
    for i, item in enumerate(articles, start=1):
        topic = item["topic"]
        headline = _extract_headline(item["text"]) or topic["title"]
        slug = _slugify(headline)
        filename = f"{i:02d}-{slug}.md"
        (out_dir / filename).write_text(item["text"], encoding="utf-8")
        saved.append({
            "number": i, "filename": filename, "headline": headline,
            # event القضية (جملة عربية قصيرة، انظر CLUSTER_SCHEMA في
            # youtube_cluster.py) يصل هنا -- طلب المراجعة على Issue #680:
            # مصدر الكلمات المفتاحية لبحث صورة تعبيرية في
            # youtube_publish.ensure_title_card عبر parse_index لاحقًا.
            "event": topic["event"],
            "layer": topic["layer"], "blocs": topic["blocs"],
            "channels": topic["channels"], "agreement": topic["agreement"],
            "warnings_count": len(item.get("warnings", [])),
            # معرّفات الفيديو المصدرية مرتّبة أهميةً (Issue #1092،
            # _video_ids_by_contribution) -- اختياري (item.get) لا إلزامي:
            # مقالات قديمة/اختبارات لا تحمل هذا المفتاح تخرج بعمود فارغ فقط.
            "video_ids": item.get("video_ids", []),
        })
    (out_dir / "index.md").write_text(build_index(saved), encoding="utf-8")
    return saved


def _write_one_topic(topic: dict, points: list[dict], cfg: Config,
                     client: Anthropic | None) -> dict:
    """خطّ أنابيب قضية واحدة كاملًا -- حارس المحظورات (طبقة ج فقط) ← بوابة
    توفّر صورة ← الكتابة ← التحذيرات ← العناوين المقترحة ← كلمات بحث الصورة.
    مستخرجة من حلقة run() أدناه (Issue #1104، بوابة الاختيار قبل الكتابة)
    كي تعيد استعمالها أيضًا src/youtube_cluster.py:finalize_selection عبر
    src/publish.py -- بلا مضاعفة نفس المنطق. **لا كتابة ملفات هنا إطلاقًا**
    (لا save_articles ولا mark_points_seen) -- مسؤولية المستدعي وحده، فكل
    من run() (كتابة على القرص عبر ملف .md/index.md) وبوابة الاختيار (مسودة
    drafts/ مباشرة بلا ملف وسيط، انظر youtube_publish.build_draft_from_text)
    تحتاج تأجيل الكتابة الفعلية إلى ما بعد هذه الدالة.

    يعيد قاموسًا: ``item`` (جاهز لـsave_articles/build_draft_from_text، أو
    None عند التخطّي)، ``skip_reason`` (نصّ أو None)، ``reason_kind`` (فئة
    التخطّي: no_points/blocked/no_image/draft_failed/None عند النجاح --
    يميّز المستدعي بين حالات التخطّي المختلفة بلا مطابقة نصّية هشّة على
    skip_reason)، ``seen_keys`` (نقاط تُسجَّل مستهلكة سواء نجحت الكتابة أو
    تخطّتها بوابة الصورة تحديدًا -- فارغة في كل تخطٍّ آخر، نفس تمييز التصميم
    الأصلي)، وguard_called/blocked_no_reason/headline_failed/speaker_warning
    لإحصاءات run() أدناه."""
    out = {
        "item": None, "skip_reason": None, "reason_kind": None,
        "seen_keys": set(), "guard_called": False, "blocked_no_reason": False,
        "headline_failed": False, "speaker_warning": False,
    }

    member_points = [points[pid] for pid in topic["point_ids"] if 0 <= pid < len(points)]
    if not member_points:
        out["skip_reason"] = "لا نقاط صالحة لهذه القضية (نقاط/قضايا من تشغيلات مختلفة؟)"
        out["reason_kind"] = "no_points"
        return out

    # مصدر واحد فعليًا: كتلة واحدة وقناة واحدة (كانت طبقة ج قبل ترقيم #1121)
    if youtube_cluster.layer_num(topic["layer"]) < 2 and len(topic.get("channels") or []) < 2:
        out["guard_called"] = True
        blocked, reason, guard_error, no_reason_override = check_forbidden(
            topic, member_points, cfg, client)
        if guard_error:
            log.warning("فشل حارس المحظورات لـ%r: %s", topic["title"], guard_error)
        if no_reason_override:
            out["blocked_no_reason"] = True
            log.warning("حارس المحظورات حظر %r بلا سبب مكتوب -- قُبِلت (حارس صامت لا يُطاع)",
                        topic["title"])
        if blocked:
            out["skip_reason"] = f"محظورة (كتلة وقناة واحدة، مصدر واحد): {reason}"
            out["reason_kind"] = "blocked"
            return out

    # بوابة توفّر صورة (Issue #1092، قرار محسوم لصاحب المشروع؛ الدرجة
    # الثانية استُبدلت في Issue #1095 بصورة خبر عن الموضوع بدل خلفية
    # الفيديو المعتّمة): ستة عشر مقالًا كاملًا (قراءة نصوص + عنقدة + صياغة
    # ~2800 حرف + بطاقة) خرجت بلا صورة ورُفضت كلّها -- الوفر المقصود هنا هو
    # *قبل* نداء الصياغة لا بعده. الدرجتان بالضبط كما تُجرَّبان لاحقًا عند
    # الاعتماد (نفس الدالتين، youtube_extract.photo_candidates/
    # news_photo_available) -- معاينة لا وعد (نتيجة بحث أو رابط قد يتعطّل
    # بين اللحظتين)، لكنها الأفضل المتاحة بلا بناء بطاقة كاملة الآن.
    video_ids = _video_ids_by_contribution(member_points)
    has_free_photo = bool(youtube_extract.photo_candidates(
        topic["title"], topic.get("event", ""), cfg))
    has_news_photo = (not has_free_photo
                      and youtube_extract.news_photo_available(
                          topic["title"], topic.get("event", ""), cfg))
    if not (has_free_photo or has_news_photo):
        out["skip_reason"] = "لا صورة متاحة (لا صورة حرة الترخيص ولا صورة خبر صالحة)"
        out["reason_kind"] = "no_image"
        # نفس معاملة مقال كُتب ونُشر فعليًا (Issue #658 العطل ١ بند ج) --
        # هذه القضية بعينها لا تُقترَح مجددًا بلا داعٍ طالما نقاطها لم
        # تتجدّد، ولا تُحسَب فشلًا تقنيًا لأنها لم تصل نداء الصياغة أصلًا.
        out["seen_keys"] = {youtube_cluster.point_key(p) for p in member_points}
        return out

    text, error = draft_article(topic, member_points, cfg, client)
    if error:
        out["skip_reason"] = error
        out["reason_kind"] = "draft_failed"
        log.warning("فشلت كتابة مقال لـ%r: %s", topic["title"], error)
        return out

    text = normalize_digits(text)
    article_text = text

    # التحذيرات تُنقَل مع النقاط عبر العنقدة إلى ذيل المقال (Issue #662
    # العطل ٣) -- بعد نجاح التحقّق من البنية (_validate_article_text داخل
    # draft_article)، لا قبله: قسم التحذيرات ليس جزءًا من البنية المطلوبة
    # من النموذج فلا يصح فحصه ضمنها.
    warnings = _collect_warnings(member_points, cfg)
    # اقتباس مباشر لشخصية عامة (Issue #1272): تنبيه مراجعة لا رفض، يُنزَع قبل النشر
    warnings = [*warnings, *figure_quote_warnings(text, cfg)]
    # زمن نسبي وعمر الفيديو (Issue #1326): تنبيها مراجعة لا رفض
    warnings = [*warnings, *relative_time_warnings(text, cfg)]
    stale = stale_video_warning(member_points, cfg)
    if stale:
        warnings.append(stale)
    # مؤشّر "فاعل الجملة متحدث" (Issue #695، البند ٣) -- تحذير استرشادي لا
    # رفض (انظر توثيق _speaker_subject_warning)، فيُلحَق بنفس قائمة تحذيرات
    # المراجعة الموجودة بدل حارس رفض منفصل.
    speaker_warning = _speaker_subject_warning(text, member_points, cfg)
    if speaker_warning:
        warnings = [*warnings, speaker_warning]
        out["speaker_warning"] = True
    text = _append_warnings(text, warnings)

    # عناوين مقترحة (Issue #680) -- فشل هذا النداء الإضافي لا يُسقِط مقالًا
    # كُتب فعلًا واجتاز التحقّق؛ احتياط بعنوانه الأصلي مكرَّرًا ثلاثًا (نفس
    # مبدأ عدم إسقاط عمل صالح بسبب خطوة لاحقة، انظر توثيق الوحدة أعلاه).
    headlines, hl_error, image_query_en = generate_headlines(
        topic, member_points, cfg, client, article_text=article_text)
    if headlines:
        headlines = [normalize_digits(h) for h in headlines]
    if hl_error:
        out["headline_failed"] = True
        log.warning("فشلت اقتراحات العناوين لـ%r -- استُعمل العنوان الأصلي مكرَّرًا: %s",
                    topic["title"], hl_error)
        fallback = _extract_headline(text) or topic["title"]
        headlines = [fallback, fallback, fallback]
    text = _append_headlines(text, headlines)
    # كلمات بحث الصورة الإنجليزية (Issue #941) -- غيابها (فشل النداء، أو
    # نجاحه بلا هذا الحقل) لا يُضيف القسم إطلاقًا؛ youtube_publish يعود
    # للبحث بالعربية كما كان (انظر _append_image_query).
    text = _append_image_query(text, image_query_en)

    out["item"] = {"topic": topic, "text": text, "warnings": warnings,
                   "headlines": headlines, "video_ids": video_ids}
    # تُسجَّل فقط بعد نجاح الكتابة الفعلي -- قضية عُنقدت أو تجاوزت الحارس لكن
    # فشلت كتابتها لا قيمة في تسجيلها "مستهلكة" (Issue #658 العطل ١ بند ج،
    # انظر youtube_cluster.filter_seen_topics).
    out["seen_keys"] = {youtube_cluster.point_key(p) for p in member_points}
    return out


def run(cfg: Config | None = None, date_str: str | None = None,
        client: Anthropic | None = None, now: datetime | None = None,
        topics_override: list[dict] | None = None) -> dict:
    """**Issue #1104 (بوابة الاختيار قبل الكتابة):** لم تعد هذه الدالة
    تكتب تلقائيًا أعلى youtube.article.count قضية من ملف العنقدة -- قياس
    ٩١ مقالًا/٣٠ يومًا أظهر أن ٧٢٪ من إنفاق Opus كان يذهب لمقالات لا تُنشر،
    لأن الاختيار كان يقع بعد الصياغة لا قبلها. الكتابة الفعلية تقع الآن
    فقط لموضوعات مُعلَّمة صراحة في Issue اختيار
    (youtube_cluster.open_selection) بعد اعتمادها -- ``topics_override``
    هو القناة الوحيدة لتمرير تلك الموضوعات هنا (src/publish.py، عبر
    src/youtube_cluster.py:finalize_selection). **بلا topics_override
    (الاستدعاء الافتراضي من main()، وهو ما تبقّى من خطوة "الكتابة" القديمة
    في youtube-articles.yml) هذه الدالة لا تكتب شيئًا إطلاقًا بتصميم --
    صفر نداء نموذج، صفر مقال** (ولذا هذه الخطوة تحديدًا صارت بلا عمل فعليًا
    في الـworkflow؛ لم تُحذَف لأن هذه المهمة ممنوعة من تعديل ملفات
    .github/workflows/)."""
    cfg = cfg or load_config()
    now = now or datetime.now(timezone.utc)
    date_str = date_str or now.strftime("%Y-%m-%d")

    topics = topics_override or []
    # نفس بناء نافذة العنقدة بالضبط -- youtube_cluster.prepare_window_points
    # تُستدعى بنفس cfg من كلا المرحلتين (Issue #662) لضمان أن point_ids كل
    # قضية تشير لنفس النقاط في القائمتين فهرسًا بفهرس؛ اختلاف أي خطوة فلترة
    # هنا عن العنقدة كان سيربط قضية بنقاط خاطئة تمامًا (انظر توثيق الدالة).
    # يُحسَب حتى بلا topics (تكلفة قراءة/فلترة فقط، لا نداء نموذج) كي يبقى
    # سلوك الدالة قابلًا للتنبؤ بصرف النظر عن topics_override.
    points, _ = youtube_cluster.prepare_window_points(date_str, cfg)

    to_draft: list[dict] = []
    skipped: list[dict] = []
    guard_calls = 0
    blocked_count = 0
    blocked_no_reason_count = 0
    draft_failures = 0
    headline_failures = 0
    speaker_subject_warnings = 0
    no_image_skipped_count = 0
    seen_keys_to_mark: set[str] = set()

    for topic in topics:
        r = _write_one_topic(topic, points, cfg, client)
        if r["guard_called"]:
            guard_calls += 1
        if r["blocked_no_reason"]:
            blocked_no_reason_count += 1

        if r["reason_kind"] is not None:
            skipped.append({"title": topic["title"], "layer": topic["layer"],
                            "reason": r["skip_reason"]})
            if r["reason_kind"] == "blocked":
                blocked_count += 1
            elif r["reason_kind"] == "no_image":
                no_image_skipped_count += 1
                seen_keys_to_mark |= r["seen_keys"]
            elif r["reason_kind"] == "draft_failed":
                draft_failures += 1
            continue

        if r["headline_failed"]:
            headline_failures += 1
        if r["speaker_warning"]:
            speaker_subject_warnings += 1
        to_draft.append(r["item"])
        seen_keys_to_mark |= r["seen_keys"]

    saved = save_articles(date_str, to_draft)
    if seen_keys_to_mark:
        retention_days = cfg.path("youtube.seen_retention_days", 14)
        youtube_cluster.mark_points_seen(seen_keys_to_mark, date_str, retention_days)

    # Issue #660 الإصلاح ٣: mark_points_seen (وبالتالي SEEN_PATH) لا يُكتب
    # إطلاقًا إن كانت seen_keys_to_mark فارغة -- صفر مقالات ناجحة (فشلت
    # العنقدة، أو صفر قضايا عبرت الحرّاس/الكتابة). خطوة `git add
    # state/youtube_topics_seen.json` في الـworkflow تسقط بخطأ (pathspec لم
    # يطابق أي ملف، exit code 128) على مسار غير موجود، فتفشل خطوة الرفع
    # كاملة وتُضيع كل ما أُنتج قبلها. توكيد وجود الملف هنا يحلّ المشكلة من
    # جذرها -- لا حاجة لتعديل الـworkflow (والتوكن لا يستطيع تعديله أصلًا).
    if not youtube_cluster.SEEN_PATH.exists():
        youtube_cluster.SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        youtube_cluster.SEEN_PATH.write_text("{}", encoding="utf-8")

    return {
        "run_date": date_str,
        "stats": {
            "topics_considered": len(topics),
            "articles_written": len(saved),
            "skipped": len(skipped),
            "guard_calls": guard_calls,
            "blocked_forbidden": blocked_count,
            "topics_blocked_no_reason": blocked_no_reason_count,
            "draft_failures": draft_failures,
            "headline_failures": headline_failures,
            "speaker_subject_warnings": speaker_subject_warnings,
            "no_image_skipped": no_image_skipped_count,
        },
        "skipped": skipped,
        "articles": saved,
    }


def main() -> int:
    """Issue #1104: بلا topics_override هذه الدالة لا تكتب شيئًا إطلاقًا
    بتصميم (انظر توثيق run() أعلاه) -- خطوة "الكتابة" التي تستدعيها في
    youtube-articles.yml (python -m src.youtube_article، بلا خيارات) بقيت
    قائمة بلا تعديل على الـworkflow، لكنها صارت بلا عمل فعليًا: 0 قضايا
    فُحصت، 0 مقال كُتب، في كل تشغيلة. الكتابة الفعلية تقع الآن عند اعتماد
    Issue اختيار المواضيع (src/publish.py:cmd_youtube_selection)."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    result = run()
    stats = result["stats"]
    out_dir = ARTICLES_DIR / result["run_date"]
    print(f"مجلد المقالات: {out_dir}")
    print(f"قضايا فُحصت: {stats['topics_considered']} · مقالات كُتبت: {stats['articles_written']} "
          f"· تخطّي: {stats['skipped']}")
    print(f"نداءات حارس المحظورات: {stats['guard_calls']} · محظورة: {stats['blocked_forbidden']} "
          f"(بلا سبب مكتوب فقُبِلت: {stats['topics_blocked_no_reason']}) "
          f"· فشل كتابة: {stats['draft_failures']} "
          f"· فشل اقتراح عناوين (احتياط بالعنوان الأصلي): {stats['headline_failures']} "
          f"· تحذير فاعل الجملة متحدث (استرشادي): {stats['speaker_subject_warnings']}")
    # Issue #1092: الوفر المقصود -- امتناع عن نداء الصياغة قبله لا بعده، حين
    # لا صورة حرة الترخيص ولا صورة فيديو صالحة معًا.
    if stats["no_image_skipped"]:
        print(f"⏭️ تُخطّي {stats['no_image_skipped']} موضوعًا: لا صورة متاحة")
    if result["skipped"]:
        for entry in result["skipped"]:
            print(f"  - {entry['title']} ({entry['layer']}): {entry['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
