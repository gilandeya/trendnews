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

أخرج JSON فقط: {"keep": [أرقام العناوين المقبولة]}"""


def _client() -> Anthropic:
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def _parse(text: str) -> list[int]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise
        data = json.loads(text[start : end + 1])
    return [int(i) for i in (data.get("keep") or [])]


def screen(articles: list[Article], cfg, batch_size: int = 30) -> list[Article]:
    """
    يعيد الأخبار الجديرة بالمعالجة فقط.

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

    client = _client()
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
                system=SYSTEM + guidance,
                messages=[{"role": "user", "content":
                           f"افحص هذه العناوين:\n\n{listing}"}],
            )
            record_usage(resp, model)
            text = "".join(b.text for b in resp.content
                           if getattr(b, "type", "") == "text")
            indices = set(_parse(text))
            passed = [a for i, a in enumerate(chunk) if i in indices]
            log.info("الفرز: مرّ %d من %d", len(passed), len(chunk))
            kept.extend(passed)
        except (APIError, json.JSONDecodeError, ValueError) as exc:
            log.warning("فشل الفرز — ستمر الدفعة كاملة: %s", exc)
            kept.extend(chunk)

    log.info("الفرز الأولي: %d من %d خبرًا اجتازوا", len(kept), len(articles))
    return kept
