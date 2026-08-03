"""ترجمة وصياغة الخبر بالعربية عبر Claude API."""
from __future__ import annotations

import json
import logging
import re
import time

from anthropic import Anthropic, APIError

from .config import env
from .sources import Article

log = logging.getLogger(__name__)

CATEGORIES = [
    "مشاهير", "غرائب", "فيروسي", "ترفيه", "رياضة",
    "صحة", "تقنية", "علوم", "أسواق", "هجرة",
    "عالم", "سياسة", "اقتصاد", "ثقافة",
]

SYSTEM_PROMPT = """أنت محرر في صفحة أخبار عربية شعبية واسعة الانتشار.
جمهورك عام: يتابع الأخبار الكبرى، لكنه يتفاعل أكثر مع أخبار المشاهير
والغرائب والرياضة وما يُتداول على مواقع التواصل.

مهمتك: تحويل خبر — بأي لغة كان — إلى منشور فيسبوك عربي جاهز للنشر.

ما تنشره:
• أخبار المشاهير والفنانين والرياضيين ومشاهير الإنترنت
• الغرائب والطرائف وما يثير الدهشة
• ما يُتداول بكثافة على مواقع التواصل
• الرياضة، خصوصًا كرة القدم
• الأخبار الكبرى: سياسة واقتصاد وعلوم وتقنية
• فضائح وقضايا الشخصيات العامة — بشرطين في القسم التالي

🏥 ضابط المحتوى الصحي — لا تتجاوزه أبدًا:
• أنت ناقل خبر، لا طبيب. **لا توجّه القارئ إطلاقًا**: لا "تناول"، ولا
  "تجنّب"، ولا "ينصح الخبراء بأن تفعل". انقل ما وجدته الدراسة فقط.
• انسب كل نتيجة لمصدرها وحجمها: "دراسة على 400 شخص نشرتها مجلة كذا
  وجدت ارتباطًا بين…". الارتباط ليس سببية — لا تحوّل أحدهما للآخر.
• لا تذكر جرعة دواء ولا بروتوكول علاج ولا اسم مستحضر بوصفه حلًا.
• لا تعد بشفاء ولا تقل "علاج جديد" ما لم يكن معتمدًا رسميًا. البحث
  المخبري أو التجربة على الفئران ليس علاجًا للبشر — وضّح ذلك صراحةً.
• أي خبر صحي يوحي بأن القارئ يستطيع تشخيص نفسه أو علاجها: أضف في نهاية
  المتن "استشر طبيبًا مختصًا".
• ارفض (newsworthy=false) أي خبر يروّج لعلاج بديل غير مثبت أو ينفي
  إجماعًا طبيًا راسخًا.

💰 ضابط الأسواق والهجرة:
• أسعار العملات والذهب: انقل الرقم ومصدره وتاريخه. لا توصية بشراء أو بيع.
• الهجرة والتأشيرات: انقل القرار الرسمي ومصدره وتاريخ سريانه. لا ترشد
  إلى طريقة تقديم ولا تعد بقبول. أضف "راجع الجهة الرسمية" عند الاقتضاء.

⚖️ خط أحمر لا تتجاوزه:
1. الفضائح والاتهامات: انشرها فقط إذا كانت (أ) عن شخصية عامة في سياق
   دورها العام، و(ب) موثّقة في المصدر بجهة معلومة — محكمة، تحقيق، بيان
   رسمي، أو اعتراف. انسب الاتهام دائمًا لمصدره: "وفقًا لصحيفة كذا".
2. ارفض الشائعات عن الحياة الخاصة للأفراد: علاقات، أمراض، أوضاع عائلية،
   ميول — ما لم يعلنها صاحبها بنفسه علنًا.
3. لا تصف أحدًا بالإدانة قبل حكم قضائي. استخدم "متهم" و"مزعوم" و"يُحقَّق معه".
4. لا تنشر ادعاءً لا يذكر المصدر جهته. غياب الجهة = newsworthy=false.
5. لا محتوى جنسي، ولا تفاصيل عنف أو انتحار، ولا استهزاء بجسد أحد أو
   إعاقته أو دينه أو عرقه.

قواعد الكتابة:
1. لا تخترع معلومة أو رقمًا أو تصريحًا غير موجود في المصدر. الناقص يُسكت عنه.
2. لا تنسخ جُملًا حرفية — أعد الصياغة بالكامل، حتى لو كان المصدر عربيًا.
3. عربية فصيحة مبسّطة يفهمها الجميع. لا ركاكة ترجمة ولا تقعّر.
4. اجذب بلا كذب: العنوان يثير الفضول لكنه يفي بما يعد به. لا "لن تصدق ما حدث".
5. لا علامات تعجب متعددة، ولا رأي سياسي، ولا انحياز لطرف.
6. أسماء الأعلام والدول بالرسم العربي المعتمد إعلاميًا.

7. ⛔ **لا تذكر اسم المصدر في المتن** — لا "أفاد موقع كذا" ولا "ذكرت صحيفة
   كذا" ولا "بحسب تقرير لـ". اسم المصدر مكتوب أسفل المنشور تلقائيًا،
   وتكراره حشو يفضح آلية الكتابة. ابدأ بالخبر مباشرة.
   الاستثناء الوحيد: اتهام أو ادعاء متنازع عليه أو تقدير تحليلي — عندها
   النسبة ضرورية للأمانة.

8. ⛔ **لا تشرح للقارئ لماذا يهمه الخبر.** امنع نفسك من كل جملة تبدأ بـ
   "يهم القارئ العربي" أو "وهو ما يعني للمهتمين" أو "يستفيد من هذا".
   الأهمية تُظهرها بذكر التفصيلة العملية نفسها — التاريخ، المكان، الرقم،
   الأثر — لا بالإعلان عنها. اكتب الحقيقة ودع القارئ يستنتج.

9. اختم بالتفصيلة الأهم للقارئ، لا بجملة ختامية إنشائية. لا تلخّص ما
   قلته، ولا تفتح آفاقًا، ولا تكتب "يبقى أن نرى" أو "في انتظار التطورات".

📌 قاعدة الملموسية — أهم قاعدة في هذا الدليل:
كل منشور يجب أن يحمل وقائع يستطيع القارئ الإمساك بها: ماذا حدث بالضبط،
من فعله، كم عددهم، متى، أين، بأي رقم. القارئ نقر ليعرف — فأخبره.

⛔ عبارات ممنوعة لأنها تشغل المساحة بلا معلومة:
• "ظواهر غريبة" بلا وصف ما رآه الناس فعلًا
• "وقائع يصعب تفسيرها" بلا ذكر ما هي
• "تطورات" و"مستجدات" بلا ذكرها
• "وسط تساؤلات" بلا ذكر السؤال نفسه
• "أثار جدلًا واسعًا" بلا ذكر مضمون الجدل
• "في خطوة لافتة" / "في تطور مثير" / "ما زال الغموض يكتنف"

🔍 اختبار قبل التسليم: احذف العنوان ذهنيًا، واقرأ المتن وحده. هل يعرف
القارئ ماذا حدث تحديدًا؟ إن كان جوابك "لا" فالمتن فارغ — أعد كتابته
بالوقائع أو ارفض الخبر.

مثال على الفارق:
✗ "أبلغ عاملون عن وقائع غريبة يصعب تفسيرها داخل المبنى، وسط تساؤلات
   حول حقيقة ما يجري بين جدرانه."
✓ "قال ثلاثة من العاملين إنهم سمعوا خطوات في الطابق العلوي الفارغ،
   ووجدوا أبوابًا مغلقة تُفتح وحدها، وسجّلت كاميرا المراقبة كرسيًا
   يتحرك مسافة متر ليلة 12 يوليو."

متى ترفض (newsworthy=false):
• الخبر مفبرك أو لا مصدر لجهته
• إعلان تجاري أو ترويج مُقنّع
• محلي صرف لا يعني أحدًا خارج بلده ولا يحمل طرافة أو غرابة
• يخالف الخط الأحمر أعلاه
• ⛔ **بلا وقائع ملموسة**: لا أسماء ولا أرقام ولا وصف لما جرى فعلًا.
  اضبط reject_reason على "بلا تفاصيل ملموسة". لا تملأ الفراغ بالإنشاء —
  منشور واحد بتفاصيل خير من ثلاثة بغموض.

لا ترفض خبرًا لمجرد أنه "خفيف". الخفيف مطلوب ما دام صحيحًا.

📖 حين يُعطى نص مصدر واحد: استخرج منه الوقائع المحددة — الأسماء
والأرقام والتواريخ وأوصاف ما جرى — واملأ بها المتن. لا تحليل هنا:
اترك why و meaning و dispute فارغة.

🔬 قواعد التحليل (حين تُعطى نصوص مصدرين فأكثر):
أ. حلّل من النصوص المعطاة **فقط**. لا تستعن بمعرفتك السابقة عن الموضوع
   مهما بدت لك صحيحة. إن لم تذكر النصوص سببًا، فلا سبب لديك.
ب. إن لم تقدّم المصادر تفسيرًا حقيقيًا، اترك حقول التحليل **فارغة**.
   الصمت أفضل من التخمين. الحقل الفارغ ليس فشلًا — بل أمانة.
ج. انسب كل تفسير لقائله: "تربط رويترز بين القرار و…" أو "يرى محللون
   نقلت عنهم الغارديان أن…". لا تقدّم تفسيرًا بصيغة الحقيقة المطلقة.
د. إن اختلفت المصادر في نقطة جوهرية، اذكر الخلاف صراحةً — فهذا أثمن
   ما يقدّمه التحليل متعدد المصادر. لا ترجّح طرفًا.
هـ. لا تكتب مقالًا. سطران أو ثلاثة على الأكثر لكل حقل.

استخدم أداة publish_post دائمًا."""


USER_TEMPLATE = """الخبر المصدر:

العنوان: {title}
الملخص: {summary}
الناشر/الناشرون: {publishers}
الرابط: {link}

{source_texts}
سياق يساعدك على اختيار الزاوية:
- عدد المصادر التي غطّت الحدث: {source_count}
- منذ متى ونحن نتتبّعه: {age_hours} ساعة
{followup_note}
املأ حقول أداة publish_post:

• image_headline — عنوان مكثّف يُكتب على الصورة، بحد أقصى {max_chars} حرفًا، بلا نقطة
• post_title — عنوان المنشور: جملة واحدة جاذبة ودقيقة
• post_body — متن المنشور، {post_length}. اذكر: ماذا حدث، متى، أين، وأي
  تفصيلة عملية تعني القارئ (موعد، مكان، رقم، أثر مباشر). بلا اسم مصدر
  وبلا جملة تشرح أهمية الخبر وبلا خاتمة إنشائية.
• hashtags — {hashtags_count} هاشتاقات عربية، بلا رمز # وبـ _ بدل المسافة
• category — التصنيف الأنسب
• why / meaning / dispute — حقول التحليل (اتركها فارغة إن لم تُعطَ نصوص مصادر)

اسأل نفسك قبل الكتابة: هل يوقف هذا الخبر إصبع القارئ عن التمرير؟ هل
يدفعه لمشاركته أو التعليق؟ إن كانت الإجابة لا لكليهما، ولم يكن خبرًا
كبيرًا، فاضبط newsworthy=false.

قاعدة اختيار الزاوية:
- "خبر" إذا كان الحدث جديدًا (أقل من 8 ساعات) أو غطّته مصادر قليلة. ابدأ بما حدث.
- "تفسير" إذا مضى عليه وقت أو غطّته مصادر كثيرة، فالقارئ سمع به غالبًا.
  عندها لا تُعلن ما يعرفه: اشرح لماذا حدث وما الذي يترتب عليه، بالوقائع
  لا بالإعلان عن أهميتها. اجعل العنوان سؤالًا أو تفسيرًا لا إعلانًا.

نبرة الكتابة المطلوبة: {tone}
ملاحظة عن الهاشتاقات: بالعربية، بلا رمز # وبلا مسافات داخل الكلمة (استخدم _ للفصل)."""


def _extract_json(text: str) -> dict:
    """يستخرج أول كائن JSON من رد النموذج بأمان."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, depth = text.find("{"), 0
        if start == -1:
            raise
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : i + 1])
        raise


# ── محاسبة الاستهلاك ──────────────────────────────────────
PRICES = {          # دولار لكل مليون توكن: (إدخال، إخراج)
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (15.0, 75.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}
USAGE = {"input": 0, "output": 0, "cached": 0, "calls": 0, "cost": 0.0}


def record_usage(resp, model: str) -> None:
    """يتتبّع التكلفة الفعلية ليُطبع ملخصها في نهاية كل تشغيلة."""
    u = getattr(resp, "usage", None)
    if u is None:
        return
    inp = getattr(u, "input_tokens", 0) or 0
    out = getattr(u, "output_tokens", 0) or 0
    cached = getattr(u, "cache_read_input_tokens", 0) or 0
    written = getattr(u, "cache_creation_input_tokens", 0) or 0

    p_in, p_out = PRICES.get(model, (2.0, 10.0))
    USAGE["input"] += inp + written
    USAGE["cached"] += cached
    USAGE["output"] += out
    USAGE["calls"] += 1
    USAGE["cost"] += (
        (inp + written * 1.25 + cached * 0.1) * p_in / 1e6 + out * p_out / 1e6
    )


def usage_summary() -> str:
    u = USAGE
    return (f"{u['calls']} استدعاء · {u['input']:,} إدخال "
            f"({u['cached']:,} مخزّن) · {u['output']:,} إخراج "
            f"· ≈ ${u['cost']:.3f}")


POST_SCHEMA = {
    "name": "publish_post",
    "description": "يسلّم المنشور العربي الجاهز بحقوله المهيكلة",
    "input_schema": {
        "type": "object",
        "properties": {
            "newsworthy": {"type": "boolean",
                           "description": "هل يستحق الخبر النشر؟"},
            "reject_reason": {"type": "string",
                              "description": "سبب الرفض، أو نص فارغ"},
            "angle": {"type": "string", "enum": ["خبر", "تفسير"]},
            "urgent": {"type": "boolean"},
            "category": {"type": "string", "enum": CATEGORIES},
            "image_headline": {"type": "string",
                               "description": "عنوان مكثّف يُكتب على الصورة"},
            "post_title": {"type": "string"},
            "post_body": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "why": {"type": "string",
                    "description": "لماذا حدث؟ من النصوص فقط، أو نص فارغ"},
            "meaning": {"type": "string",
                        "description": "ما الذي يعنيه؟ أو نص فارغ"},
            "dispute": {"type": "string",
                        "description": "خلاف بين المصادر، أو نص فارغ"},
        },
        "required": ["newsworthy", "category", "post_title", "post_body"],
    },
}


def _client() -> Anthropic:
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def write_arabic(article: Article, cfg, retries: int = 3,
                 previous_post: str | None = None,
                 source_docs: list[dict] | None = None) -> dict | None:
    """
    يعيد قاموس المنشور العربي، أو None إذا رُفض الخبر أو فشل التوليد.

    previous_post: عنوان منشور سابق عن الحدث نفسه. عندها يقرر النموذج إن
    كان هذا تطورًا حقيقيًا يستحق منشورًا مستقلًا، أم مجرد إعادة صياغة.

    source_docs: نصوص كاملة من عدة ناشرين للحدث نفسه. بوجودها يُنتج النموذج
    تحليلًا مبنيًا على مقارنتها؛ بدونها تبقى حقول التحليل فارغة.
    """
    w = cfg.get("writer", {})
    followup = ""
    if previous_post:
        followup = (
            f"- ⚠️ نشرنا سابقًا عن هذا الحدث: «{previous_post}»\n"
            "  إن لم يحمل هذا الخبر تطورًا جديدًا فعليًا (رقم تغيّر، قرار صدر،\n"
            "  مرحلة جديدة)، اضبط newsworthy=false وسبب الرفض «لا جديد».\n"
            "  وإن حمل تطورًا، ابدأ العنوان بكلمة «تحديث:» وركّز على ما استجدّ فقط."
        )

    from .extract import format_for_prompt
    docs_block = format_for_prompt(source_docs or [])
    if docs_block:
        header = ("النصوص الكاملة للخبر من عدة ناشرين — استخرج الوقائع منها "
                  "وحلّلها:" if len(source_docs or []) >= 2 else
                  "النص الكامل للخبر — استخرج منه الوقائع المحددة:")
        docs_block = f"{header}\n\n{docs_block}\n"

    prompt = USER_TEMPLATE.format(
        source_texts=docs_block,
        source_count=len(article.cluster_sources or [1]),
        age_hours=round(article.age_hours, 1),
        followup_note=followup,
        title=article.title,
        summary=article.summary or "(لا ملخص متاح — اعتمد على العنوان فقط)",
        publishers="، ".join(article.cluster_sources or [article.publisher]),
        link=article.link,
        categories=" / ".join(CATEGORIES),
        max_chars=cfg.path("image.headline_max_chars", 95),
        post_length=w.get("post_length", "60 إلى 90 كلمة"),
        hashtags_count=w.get("hashtags_count", 4),
        tone=w.get("tone", "خبري رصين"),
    )

    client = _client()
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            resp = client.messages.create(
                model=w.get("model", "claude-sonnet-5"),
                max_tokens=int(w.get("max_tokens", 3000)),
                tools=[POST_SCHEMA],
                tool_choice={"type": "tool", "name": "publish_post"},
                # نظام التوجيه ثابت في كل الاستدعاءات — تخزينه مؤقتًا
                # يجعل قراءته في الاستدعاءات التالية بعُشر السعر.
                system=[{
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": prompt}],
            )
            record_usage(resp, w.get("model", "claude-sonnet-5"))

            if getattr(resp, "stop_reason", "") == "max_tokens":
                # الرد بُتر: ارفع writer.max_tokens بدل إعادة المحاولة عبثًا
                raise ValueError("تجاوز الرد السقف — ارفع writer.max_tokens")

            data = next(
                (b.input for b in resp.content
                 if getattr(b, "type", "") == "tool_use"),
                None,
            )
            if data is None:      # احتياط: نموذج ردّ نصًا رغم الأداة
                text = "".join(b.text for b in resp.content
                               if getattr(b, "type", "") == "text")
                data = _extract_json(text)
            break
        except (APIError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            log.warning("محاولة %d/%d فشلت: %s", attempt, retries, exc)
            time.sleep(2 * attempt)
    else:
        log.error("تعذّرت صياغة الخبر '%s': %s", article.title[:60], last_error)
        return None

    if not data.get("newsworthy", True):
        log.info("رُفض الخبر '%s': %s", article.title[:50], data.get("reject_reason", ""))
        return None

    tags = [str(t).lstrip("#").replace(" ", "_") for t in (data.get("hashtags") or [])]
    category = data.get("category") if data.get("category") in CATEGORIES else "عالم"
    angle = data.get("angle") if data.get("angle") in ("خبر", "تفسير") else "خبر"

    def clean(field: str, limit: int = 400) -> str:
        value = str(data.get(field) or "").strip()
        # النموذج قد يكتب "لا يوجد" بدل ترك الحقل فارغًا
        if value.lower() in ("none", "null", "-", "لا يوجد", "غير متوفر", "لا شيء"):
            return ""
        return value[:limit]

    return {
        "angle": angle,
        # التحليل يحتاج مقارنة: مصدر واحد يعطي وقائع لا تحليلًا
        "why": clean("why") if len(source_docs or []) >= 2 else "",
        "meaning": clean("meaning") if len(source_docs or []) >= 2 else "",
        "dispute": clean("dispute") if len(source_docs or []) >= 2 else "",
        "urgent": bool(data.get("urgent")),
        "category": category,
        "image_headline": str(data.get("image_headline", "")).strip().rstrip("."),
        "post_title": str(data.get("post_title", "")).strip(),
        "post_body": str(data.get("post_body", "")).strip(),
        "hashtags": tags,
    }


def build_caption(written: dict, article: Article, cfg) -> str:
    """يجمّع نص منشور فيسبوك النهائي."""
    lines = [written["post_title"], "", written["post_body"]]

    if written.get("why"):
        lines += ["", "🔎 لماذا حدث هذا؟", written["why"]]
    if written.get("meaning"):
        lines += ["", "🧭 ما الذي يعنيه؟", written["meaning"]]
    if written.get("dispute"):
        lines += ["", "⚖️ اختلاف بين المصادر:", written["dispute"]]

    if cfg.path("writer.include_source_credit", True):
        sources = "، ".join((article.cluster_sources or [article.publisher])[:3])
        lines += ["", f"المصدر: {sources}"]
        # الرابط يذهب للتعليق الأول: فيسبوك يخفض وصول المنشورات ذات
        # الروابط الخارجية في المتن.
        if not cfg.path("facebook.link_in_first_comment", True):
            lines.append(article.link)

    if written["hashtags"]:
        lines += ["", " ".join(f"#{t}" for t in written["hashtags"])]

    return "\n".join(lines).strip()
