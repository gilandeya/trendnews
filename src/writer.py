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

CATEGORIES = ["عالم", "سياسة", "اقتصاد", "تقنية", "علوم", "صحة", "رياضة", "ثقافة"]

SYSTEM_PROMPT = """أنت محرر أخبار عربي محترف يعمل في غرفة أخبار رقمية.
مهمتك: تحويل خبر بلغة أجنبية إلى منشور فيسبوك عربي جاهز للنشر.

قواعد صارمة:
1. لا تخترع أي معلومة، رقم، اسم، أو تصريح غير موجود في النص المصدر. إن كانت المعلومة ناقصة فاصمت عنها.
2. لا تنسخ جُملًا حرفية من المصدر — أعد الصياغة بالكامل بأسلوبك.
3. اكتب بعربية فصيحة واضحة، بلا ترجمة حرفية ركيكة وبلا عبارات إنشائية.
4. اكتب أسماء الأعلام والدول بالرسم العربي المعتمد إعلاميًا.
5. تجنّب الإثارة والتهويل وعلامات التعجب المتعددة، ولا تُبدِ رأيًا أو انحيازًا سياسيًا.
6. إذا كان الخبر تافهًا أو ترويجيًا أو غير قابل للتحقق، اضبط newsworthy على false.

أخرج JSON فقط بلا أي نص أو علامات markdown حوله."""

USER_TEMPLATE = """الخبر المصدر:

العنوان: {title}
الملخص: {summary}
الناشر/الناشرون: {publishers}
الرابط: {link}

المطلوب — كائن JSON بهذه الحقول بالضبط:

{{
  "newsworthy": true أو false,
  "reject_reason": "سبب الرفض إن كان newsworthy=false، وإلا نص فارغ",
  "urgent": true إذا كان الخبر عاجلًا/كسر أخبار، وإلا false,
  "category": واحدة من {categories},
  "image_headline": "عنوان مكثّف يُكتب على الصورة، بحد أقصى {max_chars} حرفًا، بلا نقطة في النهاية",
  "post_title": "عنوان المنشور، جملة واحدة جاذبة ودقيقة",
  "post_body": "متن المنشور، {post_length}، يجيب عن ماذا ومتى وأين ولماذا يهم القارئ العربي",
  "hashtags": ["قائمة", "من", "{hashtags_count}", "هاشتاقات"]
}}

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


def _client() -> Anthropic:
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def write_arabic(article: Article, cfg, retries: int = 3) -> dict | None:
    """يعيد قاموس المنشور العربي، أو None إذا رُفض الخبر أو فشل التوليد."""
    w = cfg.get("writer", {})
    prompt = USER_TEMPLATE.format(
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
                max_tokens=1500,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(
                block.text for block in resp.content if getattr(block, "type", "") == "text"
            )
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

    return {
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

    if cfg.path("writer.include_source_credit", True):
        sources = "، ".join((article.cluster_sources or [article.publisher])[:3])
        lines += ["", f"المصدر: {sources}", article.link]

    if written["hashtags"]:
        lines += ["", " ".join(f"#{t}" for t in written["hashtags"])]

    return "\n".join(lines).strip()
