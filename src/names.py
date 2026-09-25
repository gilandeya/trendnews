"""توحيد رسم أسماء الأعلام عبر كل المسارات (Issue #1070)، بطبقتين تُدمجان
معًا هنا فقط: معجم يدوي (config.yaml: names.aliases) ومعجم متعلَّم آليًا
(state/names_learned.json، Issue #1074 — انظر src/names_learn.py لمنطق
التعلّم نفسه). كل مسار (الأخبار وrequest وarticle وyoutube_article) يصوغ
نصه بنموذج مستقل، فقد يخرج اسم العلم نفسه برسمين مختلفين بين مسودتين
متتاليتين (نتنياهو مقابل نتانياهو مثلًا) — فرق يظهر للقارئ مباشرة على
البطاقات. نقطة التطبيق الوحيدة هي store.save_draft/update_draft (لا
تكرار ولا مسار منسي) — لا تطبيع لغوي هنا إطلاقًا (لا همزات، لا تشكيل، لا
ة/ه، لا مسافات)، استبدال نصي مباشر فقط.

**اليدوي يغلب المتعلَّم دائمًا عند التعارض** (تعمُّدًا: تصحيح يدوي صريح لا
يجوز أن ينقضه تخمين آلي)، و``names.blocklist`` يلغي أي مدخل متعلَّم فورًا
حتى لو كان مخزَّنًا في state/names_learned.json — لا يمسّ المعجم اليدوي.
``names.learned_enabled: false`` يوقف طبقة التعلّم كلها بلا مسّ اليدوي.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import STATE_DIR

log = logging.getLogger(__name__)

# الحقول العربية الوحيدة التي يمسّها التوحيد -- لا شيء غيرها، خصوصًا لا
# source ولا link ولا image ولا id ولا publishers (Issue #1070).
_ARABIC_TEXT_FIELDS = ("post_title", "body", "caption")

# ملف الأسماء المتعلَّمة -- src/names_learn.py هو من يكتبه (المصدر الوحيد
# للحقيقة لمنطق التعلّم)، ويستورد هذا الثابت من هنا (names_learn يستورد
# names لاستعمال seen_totals() أصلًا، فلا حلقة استيراد).
LEARNED_FILE = STATE_DIR / "names_learned.json"

# ملف عدّ الأسماء الواردة -- مدخل src/names_learn.py الوحيد (Issue #1074).
SEEN_FILE = STATE_DIR / "names_seen.json"

_DEFAULT_SEEN_KEEP_DAYS = 90

# سوابق عربية شائعة تُجرَّد قبل العدّ (حرف عطف/جر/تعريف ملتصق) -- الأطول
# أولًا كي لا يُجرَّد "و" فقط من "والحرب" ويبقى "الحرب" (طول 4) بدل
# التجريد الصحيح للسابقة المركّبة "وال".
_NAME_PREFIXES = sorted(
    {"وال", "بال", "لل", "ال", "و", "ب", "ل", "ف", "ك"}, key=len, reverse=True)

_ARABIC_WORD_RE = re.compile(r"[ء-ي]+")

# توحيد الهيكل قبل مقارنة ليفنشتاين في names_learn.py (وليس هنا -- هذا
# الثابت يُستعمَل من الوحدتين فيبقى تعريفه هنا مع بقية أدوات الأسماء
# المشتركة؛ التطبيق الفعلي فقط في names_learn._levenshtein).
STRUCTURE_UNIFY_TRANS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"})


def cfg_get(cfg: Any, dotted: str, default: Any = None) -> Any:
    if cfg is None:
        return default
    path = getattr(cfg, "path", None)
    if callable(path):
        return path(dotted, default)
    if isinstance(cfg, dict):
        node: Any = cfg
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node
    return default


def _aliases(cfg: Any) -> dict | None:
    return cfg_get(cfg, "names.aliases")


def blocklist_of(cfg: Any) -> set[str]:
    return set(cfg_get(cfg, "names.blocklist", []) or [])


def _load_learned_entries() -> dict:
    """يقرأ state/names_learned.json دفاعيًا -- ملف تالف أو غائب يعيد {}
    بلا كسر التوحيد؛ لا يكتب شيئًا (الكتابة من اختصاص names_learn.py وحده)."""
    if not LEARNED_FILE.exists():
        return {}
    try:
        data = json.loads(LEARNED_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("ملف الأسماء المتعلَّمة تالف -- سيُتجاهَل هذه المرة")
        return {}
    return data.get("entries") or {}


def _build_alias_map(cfg: Any) -> dict[str, set[str]]:
    """يدمج معجمَي التوحيد إلى {المعتمد: {الرسوم البديلة}} واحد. المتعلَّم
    يُبنى أولًا ثم يُطبَّق اليدوي فوقه فيعيد كتابة أي تعارض -- تطبيقه أخيرًا
    هو ما يضمن غلبته دائمًا بلا حاجة لمنطق أولوية إضافي."""
    variant_to_canonical: dict[str, str] = {}

    if cfg_get(cfg, "names.learned_enabled", True):
        blocklist = blocklist_of(cfg)
        for canonical, info in _load_learned_entries().items():
            if canonical in blocklist:
                continue
            for variant in info.get("variants") or []:
                if variant in blocklist or variant == canonical:
                    continue
                variant_to_canonical[variant] = canonical

    for canonical, variants in (_aliases(cfg) or {}).items():
        for variant in (variants or ()):
            if variant and variant != canonical:
                variant_to_canonical[variant] = canonical

    groups: dict[str, set[str]] = {}
    for variant, canonical in variant_to_canonical.items():
        groups.setdefault(canonical, set()).add(variant)
    return groups


def normalize_names(text: str, cfg: Any) -> str:
    """يستبدل كل رسم بديل لاسم علم بالرسم المعتمد له حسب المعجم المدموج
    (اليدوي + المتعلَّم، اليدوي يغلب). استبدال نصي مباشر (str.replace) --
    غياب المعجمين معًا أو خلوّهما يعيد النص كما هو بلا أي تغيير."""
    if not text:
        return text
    aliases = _build_alias_map(cfg)
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
            placeholder = f"{i}"
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


# ──────────────────────── عدّ الأسماء الواردة (Issue #1074) ────────────────────────
# مدخل التعلّم الوحيد: قبل أي توحيد، حتى لا يغذّي التوحيد نفسه (رسم وُحِّد
# فور كتابته لا يُرى أبدًا برسمه البديل فلا يتراكم له عدّ يستحق التعلّم منه).


def _strip_prefix(word: str) -> str:
    for prefix in _NAME_PREFIXES:
        if word.startswith(prefix) and len(word) > len(prefix):
            return word[len(prefix):]
    return word


def _count_words(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw in _ARABIC_WORD_RE.findall(text or ""):
        word = _strip_prefix(raw)
        if len(word) >= 5:
            counts[word] = counts.get(word, 0) + 1
    return counts


def _extract_draft_counts(draft: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    arabic = draft.get("arabic")
    if isinstance(arabic, dict):
        for key in _ARABIC_TEXT_FIELDS:
            value = arabic.get(key)
            if isinstance(value, str):
                for word, n in _count_words(value).items():
                    counts[word] = counts.get(word, 0) + n
    headlines = draft.get("headlines")
    if isinstance(headlines, list):
        for h in headlines:
            if isinstance(h, str):
                for word, n in _count_words(h).items():
                    counts[word] = counts.get(word, 0) + n
    return counts


def _load_seen() -> dict:
    if not SEEN_FILE.exists():
        return {}
    try:
        return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("ملف عدّ الأسماء تالف -- سيُعاد إنشاؤه")
        return {}


def _prune_seen(data: dict, keep_days: int) -> dict:
    """عدّ شهري بسيط (YYYY-MM) -- المقارنة النصية بين مفاتيح بهذا الشكل
    تطابق الترتيب الزمني الحقيقي بلا حاجة لتحويل تواريخ."""
    cutoff_month = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime("%Y-%m")
    return {month: counts for month, counts in data.items() if month >= cutoff_month}


def record_seen(draft: dict, cfg: Any) -> None:
    """يعدّ الكلمات العربية المرشَّحة لأسماء أعلام (طول ≥ 5 بعد تجريد
    السوابق) في نص المسودة **الخام** (قبل التوحيد) في state/names_seen.json
    -- مدخل src/names_learn.py الوحيد. رخيصة وصامتة: أي خطأ هنا يُلتقط
    ويُسجَّل WARNING ولا يمنع حفظ المسودة أبدًا (حفظ المسودة أهم من العدّ)."""
    try:
        _record_seen(draft, cfg)
    except Exception as exc:  # noqa: BLE001
        log.warning("تعذّر تسجيل عدّ الأسماء: %s", exc)


def _record_seen(draft: dict, cfg: Any) -> None:
    counts = _extract_draft_counts(draft)
    if not counts:
        return
    keep_days = int(cfg_get(cfg, "names.seen_keep_days", _DEFAULT_SEEN_KEEP_DAYS))
    data = _prune_seen(_load_seen(), keep_days)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    month_counts = data.setdefault(month, {})
    for word, n in counts.items():
        month_counts[word] = month_counts.get(word, 0) + n
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def seen_totals() -> dict[str, int]:
    """المجموع التراكمي لكل كلمة عبر الأشهر المحفوظة حاليًا في
    state/names_seen.json (التقليم يقع عند الكتابة في record_seen فقط --
    لا تقليم إضافي هنا). يعيد {} إن لم يُكتب الملف بعد."""
    totals: dict[str, int] = {}
    for month_counts in _load_seen().values():
        for word, n in (month_counts or {}).items():
            totals[word] = totals.get(word, 0) + int(n)
    return totals
