"""مولّد عناوين مشترك (Issue #756) — القالب العام المستخرَج من
youtube_article.generate_headlines: مخطط أداة ``propose_headlines``، حلقة
إعادة المحاولة، والتحقّق العام (ثلاثة عناوين غير فارغة، الأول بصيغة سؤال،
ولا يتجاوز أيّها حدّ الكلمات). فحص الاسم غير الموثَّق
(``youtube_extract.find_unsourced_name`` على ``quotes_original``/
``known_figures``) تحليليّ بحت — يعتمد على أرشيف اقتباسات الفيديو الأصلية
الذي لا نظير له في مسارات الأخبار — فيبقى في غلاف
``youtube_article.generate_headlines`` وحده، لا هنا.

مسار العاجل (``origin == "breaking"``) لا يستدعي هذه الوحدة إطلاقًا —
``radar.build_draft`` لا تولّد عناوين ولا تدفع كلفة نداء لا يستعملها؛ من
يحتاج عناوين لمسودة عاجلة-الشكل (مثل ``request.py``) يولّدها بنفسه ويمرّرها
عبر ``extra`` إلى ``radar.build_draft``."""
from __future__ import annotations

import logging

from anthropic import Anthropic, APIError

from .config import Config, env

log = logging.getLogger(__name__)

HEADLINE_SCHEMA = {
    "name": "propose_headlines",
    "description": "يقترح ثلاثة عناوين عربية بديلة للمنشور -- الأول بصيغة سؤال",
    "input_schema": {
        "type": "object",
        "properties": {
            "headlines": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 3,
                "maxItems": 3,
                "description": "ثلاثة عناوين عربية مستقلة الصياغة، العنصر الأول بصيغة سؤال",
            },
        },
        "required": ["headlines"],
    },
}

# نظام افتراضي عام لمسارات الأخبار/الطلب/التحقق/المقال — youtube_article
# يمرّر نظامه الخاص (نصّه الحرفي القائم، غير مُعدَّل) عبر معامل ``system``
# أدناه بدل هذا الافتراضي، فلا يتغيّر ما يصل النموذج لمسار التحليل إطلاقًا.
DEFAULT_HEADLINE_SYSTEM = """أنت تقترح ثلاثة عناوين عربية بديلة لمنشور، من
المادة المرفقة فقط -- لا معلومة من خارجها.

قواعد صارمة تنطبق على كل عنوان من الثلاثة:
1. لا يتجاوز الحدّ الأقصى للكلمات المذكور في التعليمات.
2. لا يقرّر حكمًا لم تثبته المادة المرفقة -- صياغة استفهامية أو مرجّحة عند
   عدم اليقين، لا جازمة أبعد ممّا تسمح به المادة نفسها.

العنوان الأول **يجب** أن يكون بصيغة سؤال ينتهي بعلامة استفهام (؟) -- هو
الخيار الافتراضي في مراجعة المحرِّر. الثاني والثالث بصيغتين مختلفتين عنه
وعن بعضهما (تقريرية أو ترجيحية)، لا تكرارًا لنفس المعنى بكلمات مختلفة.

أعد الثلاثة عبر الأداة المعرَّفة (propose_headlines) حصرًا، بلا أي نص خارجها."""


def validate_headlines(headlines: list[str], max_words: int) -> tuple[bool, str]:
    """التحقّق العام المشترك بين كل المسارات — ثلاثة عناوين، الأول بصيغة
    سؤال، ولا يتجاوز أيّها حدّ الكلمات. لا فحص اسم غير موثَّق هنا (خاص
    بمسار التحليل، انظر توثيق الوحدة أعلاه)."""
    if not headlines[0].rstrip().endswith("؟"):
        return False, "العنوان الأول ليس بصيغة سؤال (لا ينتهي بـ؟)"
    for i, h in enumerate(headlines, start=1):
        if len(h.split()) > max_words:
            return False, f"العنوان {i} يتجاوز {max_words} كلمة"
    return True, ""


def propose_headlines(user_content: str, cfg: Config, cfg_prefix: str, *,
                       system: str | None = None,
                       client: Anthropic | None = None,
                       extra_validate=None) -> tuple[list[str] | None, str | None]:
    """نداء قصير رخيص لاقتراح ثلاثة عناوين بديلة، بمحاولة إعادة عند إخراج
    غير صالح (نفس آلية youtube_article.draft_article). يعيد (ثلاثة عناوين،
    سبب فشل نهائي إن حدث -- None عند النجاح).

    ``cfg_prefix`` يحدّد أين تُقرأ model/max_tokens/max_retries/max_words من
    config.yaml (مثلًا "headlines" للمسارات العامة، "youtube.review.headlines"
    لمسار التحليل -- كتلتان منفصلتان عمدًا، انظر توثيق config.yaml).

    ``extra_validate`` (اختياري): دالّة ``(headlines) -> (صالح, سبب)`` تُفحص
    بعد التحقّق العام (``validate_headlines``) ضمن ميزانية إعادة المحاولة
    نفسها -- لا محاولات إضافية منفصلة. يستعملها ``youtube_article`` لإضافة
    فحص الاسم غير الموثَّق بلا مضاعفة عدد النداءات."""
    model = cfg.path(f"{cfg_prefix}.model", "claude-haiku-4-5-20251001")
    max_tokens = cfg.path(f"{cfg_prefix}.max_tokens", 600)
    max_retries = cfg.path(f"{cfg_prefix}.max_retries", 2)
    max_words = cfg.path(f"{cfg_prefix}.max_words", 15)
    system = system or DEFAULT_HEADLINE_SYSTEM
    client = client or Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))

    last_reason = ""
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                tools=[HEADLINE_SCHEMA],
                tool_choice={"type": "tool", "name": "propose_headlines"},
                system=system,
                messages=[{"role": "user", "content": user_content}],
                # لا تُضِف temperature -- نماذج هذا المشروع ترفضها بـ400.
            )
        except APIError as exc:
            return None, f"فشل نداء العناوين: {exc}"

        data = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
        raw_headlines = data.get("headlines") if isinstance(data, dict) else None
        if (isinstance(raw_headlines, list) and len(raw_headlines) == 3
                and all(isinstance(h, str) and h.strip() for h in raw_headlines)):
            headlines = [h.strip() for h in raw_headlines]
            ok, reason = validate_headlines(headlines, max_words)
            if ok and extra_validate:
                ok, reason = extra_validate(headlines)
            if ok:
                return headlines, None
            last_reason = reason
            log.warning("محاولة %d/%d: عناوين غير صالحة (%s)", attempt, max_retries, reason)
            continue
        last_reason = "لم يُعِد النموذج إخراجًا مهيكلًا بثلاثة عناوين نصّية"

    return None, (f"تعذّر الحصول على عناوين صالحة بعد {max_retries} محاولة/محاولات: {last_reason}")


def headlines_for_post(post_title: str, post_body: str, cfg: Config,
                        client: Anthropic | None = None) -> tuple[list[str] | None, str | None]:
    """يبني مدخل النداء من عنوان ومتن منشور مصوغ فعليًا وينادي
    ``propose_headlines`` بكتلة config.yaml العامة (``headlines`` -- لا
    ``youtube.review.headlines`` الخاصة بمسار التحليل). تستعملها المسارات
    الأربعة (collect_finalize/collect/verify_draft/article) مباشرة بعد نجاح
    الصياغة؛ request.py يستدعيها بنفسه أيضًا (لا radar.build_draft المشتركة
    مع العاجل -- انظر توثيق الوحدة أعلاه)."""
    user_content = f"عنوان المنشور: {post_title}\n\nمتن المنشور:\n{post_body}"
    return propose_headlines(user_content, cfg, "headlines", client=client)
