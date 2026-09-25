"""توحيد رسم أسماء الأعلام عبر كل المسارات (Issue #1070).

كل مسار (الأخبار وrequest وarticle وyoutube_article) يصوغ نصه بنموذج
مستقل، فقد يخرج اسم العلم نفسه برسمين مختلفين بين مسودتين متتاليتين
(نتنياهو مقابل نتانياهو مثلًا) — فرق يظهر للقارئ مباشرة على البطاقات.
نقطة التطبيق الوحيدة هي store.save_draft/update_draft (لا تكرار ولا مسار
منسي)، والمعجم في config.yaml: names.aliases وحده مصدر الحقيقة — لا
تطبيع لغوي هنا إطلاقًا (لا همزات، لا تشكيل، لا ة/ه، لا مسافات)، استبدال
نصي مباشر فقط.
"""
from __future__ import annotations

from typing import Any

# الحقول العربية الوحيدة التي يمسّها التوحيد -- لا شيء غيرها، خصوصًا لا
# source ولا link ولا image ولا id ولا publishers (Issue #1070).
_ARABIC_TEXT_FIELDS = ("post_title", "body", "caption")


def _aliases(cfg: Any) -> dict | None:
    if cfg is None:
        return None
    path = getattr(cfg, "path", None)
    if callable(path):
        return path("names.aliases")
    if isinstance(cfg, dict):
        return (cfg.get("names") or {}).get("aliases")
    return None


def normalize_names(text: str, cfg: Any) -> str:
    """يستبدل كل رسم بديل لاسم علم بالرسم المعتمد له حسب names.aliases في
    config.yaml. استبدال نصي مباشر (str.replace) -- غياب القسم أو خلوّه
    يعيد النص كما هو بلا أي تغيير."""
    if not text:
        return text
    aliases = _aliases(cfg)
    if not aliases:
        return text
    for canonical, variants in aliases.items():
        ordered = sorted(
            {v for v in (variants or ()) if v and v != canonical}, key=len, reverse=True)
        if not ordered:
            continue
        # الأطول أولًا داخل المدخل نفسه: رسم أقصر قد يكون محتوًى في رسم
        # أطول من المدخل نفسه، فاستبداله أولًا يفسد مطابقة الأطول جزئيًا.
        # الاستبدال يمرّ بمرحلتين عبر رمز وسيط بدل الكتابة المباشرة للرسم
        # المعتمد: الرسم المعتمد نفسه قد يحتوي رسمًا أقصر كمّدخل جزئي منه
        # (مثال: "القاهرة" المعتمد يحتوي حرفيًا الرسم البديل الأقصر
        # "قاهرة") -- كتابته فورًا تُعرِّضه لاستبدال ثانٍ مشوِّه حين يصل
        # الدور لاحقًا إلى ذلك الرسم الأقصر في المدخل نفسه.
        placeholders: list[str] = []
        for i, variant in enumerate(ordered):
            if variant not in text:
                continue
            placeholder = f"{i}"
            text = text.replace(variant, placeholder)
            placeholders.append(placeholder)
        for placeholder in placeholders:
            text = text.replace(placeholder, canonical)
    return text


def normalize_draft(draft: dict, cfg: Any) -> dict:
    """يطبّق normalize_names على حقول النص العربي المشمولة فقط في المسودة
    (arabic.post_title/body/caption، caption، headlines) بلا لمس أي حقل
    آخر. يُعدَّل draft في مكانه (نفس كائن draft["arabic"] الذي يحمله بعض
    الكاتبين -- collect.py مثلًا -- كي يرى المتن ذاته النص الموحَّد أيضًا)
    ويُعاد للتيسير."""
    arabic = draft.get("arabic")
    if isinstance(arabic, dict):
        for key in _ARABIC_TEXT_FIELDS:
            value = arabic.get(key)
            if isinstance(value, str):
                arabic[key] = normalize_names(value, cfg)

    caption = draft.get("caption")
    if isinstance(caption, str):
        draft["caption"] = normalize_names(caption, cfg)

    headlines = draft.get("headlines")
    if isinstance(headlines, list):
        draft["headlines"] = [
            normalize_names(h, cfg) if isinstance(h, str) else h for h in headlines
        ]

    return draft
