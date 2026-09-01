"""المرحلة الرابعة من مسار يوتيوب (Issue #646): كتابة مقالات عربية من أعلى
قضايا src/youtube_cluster.py، للقراءة فقط -- لا مسودات في drafts/، لا Issue
مراجعة، لا صور، لا نشر (خارج نطاق هذه المهمة صراحةً).

يأخذ أعلى ``youtube.article.count`` قضية (افتراضيًا ١٠) ويكتب لكل واحدة
مقالًا بنموذج أقوى من نموذج العنقدة -- مقال مقسَّم إلى أسئلة فرعية، بنسبة
صريحة لكل متحدث لا لقناته، وبلا أي معلومة من خارج النقاط المرفقة (انظر
prompts/youtube_article.md للقواعد التحريرية كاملة).

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
يُعرَض في index.md."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic, APIError

from . import youtube_cluster, youtube_extract
from .config import STATE_DIR, Config, env, load_config

log = logging.getLogger(__name__)

ARTICLE_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "youtube_article.md"
ARTICLES_DIR = STATE_DIR / "youtube_articles"

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


def _points_block(member_points: list[dict]) -> str:
    lines = []
    for i, p in enumerate(member_points, start=1):
        ts = f"{p['timestamp']}ث" if p.get("timestamp") is not None else "غير معروف"
        lines.append(
            f"{i}. القناة: {p.get('channel', '')} ({p.get('bloc', '')}) | "
            f"المتحدث: {p.get('speaker', '')} | النوع: {p.get('type', '')}\n"
            f"   القول: {p.get('statement', '')}\n"
            f"   الاقتباس العربي: {p.get('quote_arabic', '')}\n"
            f"   الفيديو: {p.get('video_title', '')} — {p.get('video_url', '')} "
            f"(الطابع: {ts})"
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


def _append_warnings(article_text: str, warnings: list[str]) -> str:
    """يضيف قسم تحذيرات في ذيل المقال بعد المصادر، فقط عند وجود تحذيرات
    فعلية (Issue #662 العطل ٣ بند ب) -- قسم فارغ دومًا نظريًا يفقد قيمته
    كإشارة، لا يميّز المراجع مقالًا يستحق انتباهًا من آخر لا يستحقّه."""
    if not warnings:
        return article_text
    lines = "\n".join(f"- {w}" for w in warnings)
    return f"{article_text.rstrip()}\n\n---\n{WARNINGS_HEADER}\n{lines}\n"


# البنية القديمة (عنوان + ٣ أسئلة فرعية + مصادر) استُبدلت ببرومبت "النسخة
# الثانية" (Issue #671) -- سلّم ترجيح + أقسام بأسماء حرفية ثابتة. ٧ من ٩
# مقالات فشلت التحقّق في التشغيلة التي كشفت العطل رغم بنية سليمة فعليًا،
# لأن الحارس كان يفحص أسماء أقسام قديمة لم يعُد البرومبت يستعملها -- العطل
# كان في الحارس لا في المخرج، فالفحوص هنا أُعيدت كتابتها من الصفر بدل تعديل
# القديمة تدريجيًا.
_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_ESTIMATE_LINE_RE = re.compile(r"^\*\*التقدير:\*\*.*$", re.MULTILINE)
MIN_SECTION_HEADINGS = 5
SOURCES_HEADING = "المصادر"

# نسخة احتياطية فقط لو غاب المفتاح من config.yaml -- المصدر الفعلي دومًا
# youtube.article.likelihood_terms (انظر draft_article) كي يبقى السلّم
# قابلًا للتعديل بلا مساس بالكود، كبقية القيم القابلة للضبط في المشروع.
DEFAULT_LIKELIHOOD_TERMS = [
    "شبه مؤكّد", "مرجّح بقوة", "مرجّح", "الاحتمالان متساويان", "مستبعد", "مستبعد جدًا",
]


def _found_sections_desc(text: str) -> str:
    """يصف الأقسام ## الموجودة فعليًا في النص -- تُلحَق بكل سبب رفض (لا
    بسبب فشل «قسم المصادر» وحده مثلًا) كي لا نعود للتخمين عند أي تعديل
    مستقبلي على البرومبت (نص الـIssue، البند ٤)."""
    headings = [h.strip() for h in _HEADING_RE.findall(text)]
    non_source = [h for h in headings if h != SOURCES_HEADING]
    has_sources = SOURCES_HEADING in headings
    found = (f"وجد {len(non_source)} أقسام ({' · '.join(non_source)})" if non_source
             else "لم يوجد أي قسم ##")
    return f"{found} و{'' if has_sources else 'لا '}قسم مصادر"


def _validate_article_text(text: str,
                            likelihood_terms: list[str] | None = None) -> tuple[bool, str]:
    likelihood_terms = likelihood_terms or DEFAULT_LIKELIHOOD_TERMS
    if not text.strip().startswith("#"):
        return False, f"لا يبدأ بعنوان رئيسي (# ): {_found_sections_desc(text)}"

    estimate_match = _ESTIMATE_LINE_RE.search(text)
    if not estimate_match:
        return False, f"لا يحوي سطر **التقدير:**: {_found_sections_desc(text)}"

    # سلّم الترجيح إلزامي داخل سطر التقدير نفسه (نص الـIssue، البند ٣) --
    # هذا ما يفرض السلّم آليًا، وهو ما فشل فيه سلّم كنت (١٩٦٤) في التطبيق
    # البشري لأن كل قارئ كان يفهم "مرجّح" بطريقة مختلفة.
    if not any(term in estimate_match.group(0) for term in likelihood_terms):
        return False, f"سطر التقدير بلا عبارة ترجيح من السلّم: {_found_sections_desc(text)}"

    headings = [h.strip() for h in _HEADING_RE.findall(text)]
    if len(headings) < MIN_SECTION_HEADINGS:
        return False, (f"أقسام ## أقل من {MIN_SECTION_HEADINGS} ({len(headings)}): "
                        f"{_found_sections_desc(text)}")

    if SOURCES_HEADING not in headings:
        return False, f"لا قسم مصادر: {_found_sections_desc(text)}"

    return True, ""


def draft_article(topic: dict, member_points: list[dict], cfg: Config,
                   client: Anthropic | None = None) -> tuple[str | None, str | None]:
    """نداء نموذج أقوى، إخراج نصّ عادي (لا tool_use) -- انظر توثيق أعلى
    الملف. يعيد (نصّ المقال، سبب الفشل بعد استنفاد المحاولات -- None عند
    النجاح)."""
    model = cfg.path("youtube.article.model", "claude-opus-5")
    max_tokens = cfg.path("youtube.article.max_tokens", 3000)
    max_retries = cfg.path("youtube.article.max_retries", 3)
    likelihood_terms = cfg.path("youtube.article.likelihood_terms", DEFAULT_LIKELIHOOD_TERMS)
    client = client or Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))

    model_agreement = _MODEL_FACING_AGREEMENT.get(topic["agreement"], topic["agreement"])
    user_content = (
        f"مؤشّر الخلاف بين المصادر لهذه القضية: {model_agreement}\n\n"
        f"النقاط المصدرية (المصدر الوحيد المسموح استعماله -- لا معلومة من "
        f"خارجها):\n{_points_block(member_points)}"
    )

    last_reason = ""
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=load_article_prompt(),
                messages=[{"role": "user", "content": user_content}],
                # لا تُضِف temperature -- نماذج هذا المشروع ترفضها بـ400.
            )
        except APIError as exc:
            return None, f"فشل نداء الكتابة: {exc}"

        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        ok, reason = _validate_article_text(text, likelihood_terms)
        if ok:
            return text, None
        last_reason = reason
        log.warning("محاولة %d/%d: مقال %r غير مطابق للبنية المطلوبة (%s)",
                    attempt, max_retries, topic["title"][:40], reason)

    return None, f"تعذّر الحصول على مقال مطابق للبنية بعد {max_retries} محاولة/محاولات: {last_reason}"


def _extract_headline(article_text: str) -> str:
    first_line = article_text.strip().splitlines()[0] if article_text.strip() else ""
    return first_line.lstrip("#").strip()


_SLUG_STRIP_RE = re.compile(r"[^\w]+", re.UNICODE)


def _slugify(title: str, max_len: int = 60) -> str:
    slug = _SLUG_STRIP_RE.sub("-", title).strip("-")
    return slug[:max_len] or "قضية"


def build_index(saved: list[dict]) -> str:
    lines = ["# فهرس مقالات يوتيوب", "",
             "| # | العنوان | الطبقة | الكتل | القنوات | الخلاف | تنبيهات |",
             "|---|---|---|---|---|---|---|"]
    for item in saved:
        warnings_count = item.get("warnings_count", 0)
        # ثلاثة تنبيهات فأكثر تُعلَّم بوضوح (نص الـIssue) -- ⚠️ + رقم بارز
        # لا مجرّد رقم صامت يغرق بين أعمدة الجدول الأخرى.
        marker = f"⚠️ **{warnings_count}**" if warnings_count >= 3 else str(warnings_count)
        lines.append(
            f"| {item['number']} | [{item['headline']}]({item['filename']}) | "
            f"{item['layer']} | {', '.join(item['blocs'])} | "
            f"{', '.join(item['channels'])} | {item['agreement']} | {marker} |")
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
            "layer": topic["layer"], "blocs": topic["blocs"],
            "channels": topic["channels"], "agreement": topic["agreement"],
            "warnings_count": len(item.get("warnings", [])),
        })
    (out_dir / "index.md").write_text(build_index(saved), encoding="utf-8")
    return saved


def run(cfg: Config | None = None, date_str: str | None = None,
        client: Anthropic | None = None, now: datetime | None = None) -> dict:
    cfg = cfg or load_config()
    now = now or datetime.now(timezone.utc)
    date_str = date_str or now.strftime("%Y-%m-%d")

    topics_result = youtube_cluster.load_topics(date_str)
    topics = topics_result.get("topics", [])
    # نفس بناء نافذة العنقدة بالضبط -- youtube_cluster.prepare_window_points
    # تُستدعى بنفس cfg من كلا المرحلتين (Issue #662) لضمان أن point_ids كل
    # قضية تشير لنفس النقاط في القائمتين فهرسًا بفهرس؛ اختلاف أي خطوة فلترة
    # هنا عن العنقدة كان سيربط قضية بنقاط خاطئة تمامًا (انظر توثيق الدالة).
    points, _ = youtube_cluster.prepare_window_points(date_str, cfg)
    count = cfg.path("youtube.article.count", 10)

    to_draft: list[dict] = []
    skipped: list[dict] = []
    guard_calls = 0
    blocked_count = 0
    blocked_no_reason_count = 0
    draft_failures = 0
    seen_keys_to_mark: set[str] = set()

    for topic in topics[:count]:
        member_points = [points[pid] for pid in topic["point_ids"] if 0 <= pid < len(points)]
        if not member_points:
            skipped.append({"title": topic["title"], "layer": topic["layer"],
                            "reason": "لا نقاط صالحة لهذه القضية (نقاط/قضايا من تشغيلات مختلفة؟)"})
            continue

        if topic["layer"] == "c":
            guard_calls += 1
            blocked, reason, guard_error, no_reason_override = check_forbidden(
                topic, member_points, cfg, client)
            if guard_error:
                log.warning("فشل حارس المحظورات لـ%r: %s", topic["title"], guard_error)
            if no_reason_override:
                blocked_no_reason_count += 1
                log.warning("حارس المحظورات حظر %r بلا سبب مكتوب -- قُبِلت (حارس صامت لا يُطاع)",
                            topic["title"])
            if blocked:
                blocked_count += 1
                skipped.append({"title": topic["title"], "layer": topic["layer"],
                                "reason": f"محظورة (طبقة ج، مصدر واحد): {reason}"})
                continue

        text, error = draft_article(topic, member_points, cfg, client)
        if error:
            draft_failures += 1
            skipped.append({"title": topic["title"], "layer": topic["layer"], "reason": error})
            log.warning("فشلت كتابة مقال لـ%r: %s", topic["title"], error)
            continue

        # التحذيرات تُنقَل مع النقاط عبر العنقدة إلى ذيل المقال (Issue #662
        # العطل ٣) -- بعد نجاح التحقّق من البنية (_validate_article_text
        # داخل draft_article)، لا قبله: قسم التحذيرات ليس جزءًا من البنية
        # المطلوبة من النموذج فلا يصح فحصه ضمنها.
        warnings = _collect_warnings(member_points, cfg)
        text = _append_warnings(text, warnings)
        to_draft.append({"topic": topic, "text": text, "warnings": warnings})
        # تُسجَّل فقط بعد نجاح الكتابة الفعلي -- قضية عُنقدت أو تجاوزت الحارس
        # لكن فشلت كتابتها لا قيمة في تسجيلها "مستهلكة" (Issue #658 العطل ١
        # بند ج، انظر youtube_cluster.filter_seen_topics).
        seen_keys_to_mark |= {youtube_cluster.point_key(p) for p in member_points}

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
            "topics_considered": min(len(topics), count),
            "articles_written": len(saved),
            "skipped": len(skipped),
            "guard_calls": guard_calls,
            "blocked_forbidden": blocked_count,
            "topics_blocked_no_reason": blocked_no_reason_count,
            "draft_failures": draft_failures,
        },
        "skipped": skipped,
        "articles": saved,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    result = run()
    stats = result["stats"]
    out_dir = ARTICLES_DIR / result["run_date"]
    print(f"مجلد المقالات: {out_dir}")
    print(f"قضايا فُحصت: {stats['topics_considered']} · مقالات كُتبت: {stats['articles_written']} "
          f"· تخطّي: {stats['skipped']}")
    print(f"نداءات حارس المحظورات: {stats['guard_calls']} · محظورة: {stats['blocked_forbidden']} "
          f"(بلا سبب مكتوب فقُبِلت: {stats['topics_blocked_no_reason']}) "
          f"· فشل كتابة: {stats['draft_failures']}")
    if result["skipped"]:
        for entry in result["skipped"]:
            print(f"  - {entry['title']} ({entry['layer']}): {entry['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
