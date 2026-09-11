"""فحص أولي رخيص: يستبعد الأخبار غير الصالحة قبل أي قراءة مكلفة.

المشكلة التي يحلها: البوت كان يقرأ ثلاثة مقالات كاملة (نحو 4500 توكن)
ثم يسأل النموذج "هل يستحق النشر؟" فيأتي الجواب "لا" في أغلب الحالات —
بعد أن دُفع الثمن كاملًا.

الحل: استدعاء واحد رخيص بنموذج Haiku يفحص عشرات العناوين **دفعة واحدة**
من العنوان والملخص فقط. الناجون وحدهم يمرّون للقراءة والتحليل.

التكلفة: نحو 0.003 دولار لفحص 25 خبرًا — مقابل 0.35 دولار لو مرّت كلها.
"""
from __future__ import annotations

import json
import logging
import re

from anthropic import Anthropic, APIError

from .config import env
from .sources import Article
from .writer import record_usage

log = logging.getLogger(__name__)

SYSTEM = """أنت محرر فرز في غرفة أخبار عربية شعبية. مهمتك سريعة: تحديد أي
العناوين تستحق أن يقرأها محرر بالتفصيل، وأيها يُستبعد فورًا.

اقبل: الغرائب والاكتشافات المدهشة والرياضة والصحة والتقنية والأحداث
الكبرى، وكل ما يثير فضول قارئ عربي عام أو يدفعه للمشاركة.

استبعد فورًا:
• 🚫 أخبار المشاهير: كل خبر محوره فنان أو مغنٍّ أو ممثل أو مؤثر أو
  عارض بوصفه مشهورًا — زواج، طلاق، حمل، أعياد ميلاد، إطلالات، تصريحات
  عن النفس، حفلات وألبومات وأفلام. استبعدها كلها بلا استثناء.
  (يُقبل فقط إن كان الشخص طرفًا في حدث عام: قضية قانونية ذات أثر،
   قرار حكومي، كارثة — أي أن الخبر عن الحدث لا عن الشخص.)
• محلي صرف لا يعني أحدًا خارج بلده (حوادث فردية، بلديات، محاكم محلية،
  تعيينات إدارية، أخبار مدارس وطرق وأسواق محلية)
• إعلانات وترويج مُقنّع ومراجعات منتجات
• عناوين ناقصة أو مبتورة أو غير مفهومة
• جداول مباريات وملخصات نتائج روتينية بلا حدث
• رأي ومقالات افتتاحية وتحليلات كاتب
• محتوى يخص جمهورًا غربيًا فقط (سياسة داخلية أمريكية تفصيلية، ضرائب
  محلية، انتخابات بلدية أجنبية)

كن صارمًا: المرور مكلف، والاستبعاد مجاني. إن ترددت، استبعد.

لكل عنوان يمرّ، قدّر ثلاثة عوامل جذب منفصلة — كل واحد عدد صحيح من 0 إلى 3،
لا تدمجها في رقم واحد ولا توازن بينها ولا تعطِ رقمًا وسطًا. قدّر كلًّا على
حدة: خبرٌ عالي القرب الهوياتي قد يكون صفرًا في الأثر المعيشي، والعكس:

- impact — أثر مباشر على معيشة القارئ العربي: سعر سلعة أو وقود أو دواء،
  تأشيرة أو سفر أو هجرة، وظيفة أو تحويلات، صحة عامة، طقس مدمّر، عملة
  بلده. 0 = لا أثر يُذكر · 3 = يغيّر يومه أو جيبه فعلًا.
- proximity — قرب هوياتي وعاطفي: العالم العربي والإسلامي، فلسطين، جاليات
  عربية في المهجر، حروب وأزمات تمسّه بالنسب أو الدين أو التاريخ.
  0 = بعيد تمامًا · 3 = يمسّه مباشرة.
- intrigue — قوة التشويق: هل يوقف الإصبع عن التمرير؟ مفاجأة أو غرابة
  موثَّقة أو سؤال يفتح فضولًا، بالدهشة لا بالإثارة. 0 = خبر روتيني ·
  3 = يستوقف القارئ حتمًا. الاستبعادات أعلاه (المشاهير، الإثارة الرخيصة)
  تُطبَّق أولًا وتبقى كما هي — هذا الحقل لا ينقضها.
- appeal_note — سطر واحد يشرح أعلى الثلاثة عندك.

أخرج JSON فقط بهذا الشكل، لكل عنوان مقبول عنصر واحد في kept:
{"kept": [{"i": رقم العنوان, "impact": 0-3, "proximity": 0-3,
"intrigue": 0-3, "appeal_note": "سطر قصير"}]}"""


def _client() -> Anthropic:
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def _clip03(value) -> int:
    """يقصّ تقدير النموذج إلى المدى 0-3 — تحقّق برمجي لا ثقة بالطاعة،
    فالنموذج قد يُخرج 5 أو -1 رغم التوجيه (Issue #876)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(3, n))


def _parse(text: str) -> dict[int, dict]:
    """يعيد {رقم العنوان: {impact, proximity, intrigue, appeal_note}} لكل
    عنصر في kept — حقل مفقود لعنصر بعينه يُعامَل كصفر بلا انهيار (Issue #876)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise
        data = json.loads(text[start : end + 1])

    out: dict[int, dict] = {}
    for item in (data.get("kept") or []):
        i = int(item["i"])
        out[i] = {
            "impact": _clip03(item.get("impact", 0)),
            "proximity": _clip03(item.get("proximity", 0)),
            "intrigue": _clip03(item.get("intrigue", 0)),
            "appeal_note": str(item.get("appeal_note") or ""),
        }
    return out


def screen(articles: list[Article], cfg, batch_size: int = 30,
          recent_titles: list[str] | None = None) -> list[Article]:
    """
    يعيد الأخبار الجديرة بالمعالجة فقط.

    ``recent_titles`` اختياري ويُمرَّر من مسار النشر التلقائي في الرادار
    وحده (عناوين آخر أيام منشورة) — يضيف سؤال «هل هذا تحديث لخبر سابق؟»
    لأن التكرار هناك يخرج للجمهور بلا مراجعة بشرية. الفحص العادي في
    `collect.py` لا يمرّره فيبقى بلا تغيير، حفاظًا على تكلفته.

    عند أي فشل نُعيد القائمة كاملة — الفشل يجب أن يكلّف مالًا، لا أخبارًا.
    """
    scfg = cfg.get("screening", {}) or {}
    if not scfg.get("enabled", True) or not articles:
        return articles

    model = scfg.get("model", "claude-haiku-4-5-20251001")

    # إرشاد من أسباب رفضك السابقة — يستبعد ما يشبهها قبل الصياغة المكلفة
    guidance = ""
    if scfg.get("use_feedback", True):
        from .feedback import load as load_rejections, screening_guidance
        guidance = screening_guidance(
            load_rejections(), int(scfg.get("feedback_examples", 12)))
        if guidance:
            log.info("الفرز يسترشد بأسباب رفض سابقة")

    dedupe_note = ""
    if recent_titles:
        listing_recent = "\n".join(f"- {t}" for t in recent_titles[:60])
        dedupe_note = (
            "\n\nاستبعد أيضًا أي عنوان هو تحديث أو تكملة لخبر **نُشر بالفعل**"
            " ضمن هذه القائمة (تطوّر الحدث نفسه، رقم ضحايا جديد، تفاصيل"
            " إضافية) — التكرار هنا يخرج للجمهور بلا مراجعة بشرية:\n"
            f"{listing_recent}"
        )

    try:
        client = _client()
    except RuntimeError as exc:
        # غياب ANTHROPIC_API_KEY يجب أن يُعامل كفشل عادي في الفرز — يمرّ كل
        # شيء بلا فرز، لا أن يُسقط أنبوب الجمع كله.
        log.warning("فشل الفرز — ستمر كل الأخبار: %s", exc)
        return articles

    kept: list[Article] = []

    for start in range(0, len(articles), batch_size):
        chunk = articles[start : start + batch_size]
        listing = "\n".join(
            f"{i}. [{a.bucket}] {a.title} — {a.summary[:150]}"
            for i, a in enumerate(chunk)
        )
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=500,
                system=SYSTEM + guidance + dedupe_note,
                messages=[{"role": "user", "content":
                           f"افحص هذه العناوين:\n\n{listing}"}],
            )
            record_usage(resp, model)
            text = "".join(b.text for b in resp.content
                           if getattr(b, "type", "") == "text")
            appeal = _parse(text)
            passed = []
            for i, a in enumerate(chunk):
                scores = appeal.get(i)
                if scores is None:
                    continue
                a.impact = scores["impact"]
                a.proximity = scores["proximity"]
                a.intrigue = scores["intrigue"]
                a.appeal_note = scores["appeal_note"]
                passed.append(a)
            log.info("الفرز: مرّ %d من %d", len(passed), len(chunk))
            kept.extend(passed)
        except (APIError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            log.warning("فشل الفرز — ستمر الدفعة كاملة: %s", exc)
            kept.extend(chunk)

    log.info("الفرز الأولي: %d من %d خبرًا اجتازوا", len(kept), len(articles))
    return kept
