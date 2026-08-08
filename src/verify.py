"""تحقّق من مقال ملصق: استخراج ادعاءاته والبحث عنها في مصادر مستقلة.

المرحلة الأولى من مسار التحقق: بحث وتقرير فقط — لا صياغة منشور هنا.
المقال الملصق مصدر إلهام لا معلومة: كل حكم في التقرير مبني على ما وجده
البحث في مصدر مستقل عنه، لا على نصه هو ولا على معرفة النموذج السابقة.

    python -m src.verify --issue 132
"""
from __future__ import annotations

import argparse
import json
import logging
import re

from anthropic import Anthropic, APIError

from . import extract, review
from .config import env, load_config
from .rank import rank
from .request import DEFAULT_LOCALES, norm_tokens, relevant, search_feeds
from .sources import Article, fetch_source, resolve_final_url
from .writer import _extract_json, record_usage, usage_summary

log = logging.getLogger("verify")

CLAIM_KINDS = ["واقعة", "رأي", "تنبؤ"]

STATUS_CONFIRMED = "مؤكدة"
STATUS_SINGLE = "مصدر واحد"
STATUS_NONE = "لا مصدر"
STATUS_CONTRADICTED = "يخالفها مصدر"


# ──────────────────────────── استخراج بنية المقال ────────────────────────────

EXTRACT_SYSTEM = """أنت محلل تحقق (fact-checker) يقرأ مقالًا ملصَقًا لاستخراج
بنيته فقط — لا تحكم على صحته الآن، فذلك يأتي بعد بحث لاحق في مصادر مستقلة.

استخرج:
1. topic: جملة واحدة تلخّص موضوع المقال كما فهمته أنت، لا كما كتبه المقال.
2. claims: كل ادّعاء محدد يحمل معلومة، مصنّفًا:
   - "واقعة": حدث أو رقم أو تصريح يمكن التحقق من وقوعه في مصدر مستقل
   - "رأي": تحليل أو تفسير أو موقف لا واقعة قائمة بذاتها
   - "تنبؤ": توقع لما سيحدث مستقبلًا
3. questions: أسئلة يثيرها المقال ولا يجيب عنها هو نفسه — فجوات في الرواية
   تستحق بحثًا مستقلًا، لا أسئلة بلاغية.

لا تنقل جملة من المقال حرفيًا: أعد صياغة كل ادّعاء وسؤال بإيجاز يكفي لبناء
استعلام بحث منه. لا تُجب عن الأسئلة من معرفتك — استخرجها فقط، فالبحث
سيتولى الإجابة.

كل عنصر في claims يجب أن يكون كائنًا {"text": ..., "kind": ...} — لا نصًا
مجردًا أبدًا، حتى لو بدا ذلك مختصرًا. مثال دقيق على الشكل المطلوب:
{
  "topic": "ارتفاع أسعار الوقود وتأثيره على النقل",
  "claims": [
    {"text": "ارتفعت أسعار الوقود بنسبة 12٪ الشهر الماضي", "kind": "واقعة"},
    {"text": "الارتفاع نتيجة سياسات حكومية غير مدروسة", "kind": "رأي"},
    {"text": "الأسعار ستتضاعف خلال عام", "kind": "تنبؤ"}
  ],
  "questions": ["ما مصدر البيانات التي استند إليها المقال في نسبة الارتفاع؟"]
}
لا تُعِد claims أو questions كقائمة نصوص مجردة أو بشكل مختلف عن هذا أبدًا."""

EXTRACT_SCHEMA = {
    "name": "extract_claims",
    "description": "يستخرج بنية مقال: موضوعه ووقائعه وأسئلته المفتوحة",
    "input_schema": {
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "kind": {"type": "string", "enum": CLAIM_KINDS},
                    },
                    "required": ["text", "kind"],
                },
            },
            "questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["topic", "claims", "questions"],
    },
}


def _as_text(value) -> str:
    """يستخرج نصًا من قيمة قد تكون نصًا أو قاموسًا بحقل نصي — بلا افتراض شكل.
    قائمة أسماء الحقول موسّعة (Issue #132 تعليق لاحق) لتقبل أسماء بديلة
    شائعة يستعملها النموذج أحيانًا رغم مخطط الأداة."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "claim", "question", "content", "statement",
                    "fact", "description", "title"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return ""


# أسماء حقول بديلة شائعة يقبلها كل حقل رئيسي في رد الاستخراج (Issue #132
# تعليق لاحق: رد بـ 1858 توكن إخراج ضاع بصمت لأن حقل claims وصل باسم آخر —
# فالتزام النموذج بأسماء مخطط الأداة ليس مضمونًا حتى مع tool_choice إجباري)
TOPIC_ALT_KEYS = ("topic", "title", "subject", "headline", "main_topic")
CLAIMS_ALT_KEYS = ("claims", "facts", "statements", "assertions")
QUESTIONS_ALT_KEYS = ("questions", "open_questions", "unanswered_questions")


def _first_present(data: dict, keys: tuple[str, ...]):
    """يعيد أول قيمة موجودة تحت أي من الأسماء البديلة لحقل، أو None إن غاب
    الحقل تمامًا تحت كل الأسماء المعروفة."""
    for key in keys:
        if key in data:
            return data[key]
    return None


def _coerce_json_string(value):
    """قيمة قد تصل نصًا مكتوبًا بصيغة JSON بدل الكائن/القائمة الفعليين —
    النموذج أحيانًا يُعيد ترميز جزء من البنية كسلسلة نصية بدل توزيعه على
    حقول الأداة (Issue #132 تعليق لاحق). نحاول تحليلها كـ JSON قبل رفضها
    كليًا؛ فشل التحليل يعيد القيمة كما وصلت بلا تغيير."""
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in "[{":
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _recover_stuffed_json(extracted: dict) -> dict:
    """احتياط لعطل رُصد فعليًا (Issue #132 تعليق لاحق): النموذج حشر بنية
    الرد الكاملة (topic + claims + questions) داخل حقل claims وحده، كنص
    يبدأ بمصفوفة الادّعاءات ثم يتبعها بقية الحقول — أي أن الحرف `{`
    الافتتاحي للكائن الكامل غاب من رد النموذج نفسه، لا من تحليلنا له.
    نحاول إعادة بناء الكائن الكامل من ذلك النص بإضافة اسم الحقل والقوس
    الناقصين قبل رفضه؛ الحقول الأخرى غير المتأثرة (لو وُجدت) تُستبدل بما
    يحمله الحقل المحشور، فهو الأحدث وربما الأكمل."""
    for key, value in extracted.items():
        if not isinstance(value, str):
            continue
        text = value.strip()
        if text[:1] not in "[{":
            continue
        candidates = [text]
        if text[:1] == "[":
            candidates.append(f'{{"{key}": {text}')
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and len(parsed) > 1:
                log.warning(
                    "تعافيت من بنية محشورة في حقل %r وحده — الحقول بعد "
                    "إعادة البناء: %s", key, sorted(parsed.keys()))
                return parsed
    return extracted


def normalize_claim(item) -> dict | None:
    """يطبّع عنصر ادّعاء واحدًا من رد النموذج، الذي قد يخالف مخطط الأداة
    (Issue #134: النموذج أعاد claims كقائمة نصوص لا كقائمة قواميس):
    نص مجرد يصير {"text": النص, "kind": "واقعة"}؛ قاموس بحقل kind غائب أو
    غير معروف يُملأ بالقيمة نفسها. عنصر بلا نص قابل للاستخراج يُستبعد."""
    text = _as_text(item)
    if not text:
        return None
    kind = item.get("kind") if isinstance(item, dict) else None
    if kind not in CLAIM_KINDS:
        kind = "واقعة"
    return {"text": text, "kind": kind}


def normalize_claims(raw) -> list[dict]:
    raw = _coerce_json_string(raw)
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        norm = normalize_claim(item)
        if norm:
            out.append(norm)
    return out


def normalize_question(item) -> str | None:
    """سؤال قد يصل نصًا مجردًا (الشكل المطلوب) أو قاموسًا — كلاهما مقبول."""
    text = _as_text(item)
    return text or None


def normalize_questions(raw) -> list[str]:
    raw = _coerce_json_string(raw)
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        norm = normalize_question(item)
        if norm:
            out.append(norm)
    return out


def _client() -> Anthropic:
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def _response_preview(resp) -> str:
    """يبني معاينة نصية من رد النموذج للتسجيل عند الفشل — لا للنشر."""
    parts = []
    for block in resp.content:
        kind = getattr(block, "type", "")
        if kind == "text":
            parts.append(block.text)
        elif kind == "tool_use":
            parts.append(json.dumps(block.input, ensure_ascii=False))
    return "".join(parts)


def extract_claims(article_text: str, cfg, retries: int = 3) -> tuple[dict | None, str | None]:
    """يستخرج بنية المقال. يرجع (data, None) عند النجاح، أو (None, سبب محدد)
    عند الفشل — السبب يصل لتقرير الـ Issue بدل "حاول مجددًا" المبهمة، بينما
    تفاصيل الرد الكاملة (أول 500 حرف) تُسجَّل في السجل فقط لا في التعليق."""
    vcfg = cfg.get("verify", {}) or {}
    model = vcfg.get("model", "claude-sonnet-5")
    max_tokens = int(vcfg.get("extract_max_tokens", 4000))
    client = _client()

    reason = "تعذّر الاتصال بالنموذج"
    for attempt in range(1, retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                tools=[EXTRACT_SCHEMA],
                tool_choice={"type": "tool", "name": "extract_claims"},
                system=EXTRACT_SYSTEM,
                messages=[{"role": "user", "content": article_text}],
            )
            record_usage(resp, model)
        except APIError as exc:
            log.warning("محاولة %d/%d فشلت في استخراج البنية: %s", attempt, retries, exc)
            reason = "تعذّر الاتصال بالنموذج"
            continue

        if getattr(resp, "stop_reason", "") == "max_tokens":
            # الرد بُتر قبل اكتمال JSON — رفع verify.extract_max_tokens هو
            # الحل، لا إعادة محاولة عبثية (writer.py يتبع النمط نفسه)
            log.error("محاولة %d/%d: استخراج البنية مبتور (max_tokens) — "
                     "أول 500 حرف من الرد: %r",
                     attempt, retries, _response_preview(resp)[:500])
            reason = "الرد مبتور — تجاوز سقف التوكنات"
            continue

        data = next((b.input for b in resp.content
                    if getattr(b, "type", "") == "tool_use"), None)
        if isinstance(data, dict):
            # نسجّل الرد الخام الكامل عند كل نجاح لا الفشل فقط (Issue #132
            # تعليق لاحق: استدعاء ناجح 1858 توكن أنتج تقريرًا فارغًا، ولم يكن
            # هناك سجل يُظهر أسماء الحقول الفعلية التي أعادها النموذج)
            log.info("نجح استخراج البنية — الرد الخام الكامل: %s",
                     json.dumps(data, ensure_ascii=False))
            data = _recover_stuffed_json(data)
            return data, None

        # احتياط: نموذج ردّ نصًا (ربما محاطًا بأسوار ```json```) رغم الأداة
        text = "".join(b.text for b in resp.content
                       if getattr(b, "type", "") == "text")
        try:
            data = _extract_json(text) if text.strip() else None
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            log.info("نجح استخراج البنية (رد نصي) — الرد الخام الكامل: %s",
                     json.dumps(data, ensure_ascii=False))
            data = _recover_stuffed_json(data)
            return data, None

        log.error("محاولة %d/%d: رد استخراج البنية لم يكن JSON صالحًا — "
                 "أول 500 حرف من الرد: %r",
                 attempt, retries, _response_preview(resp)[:500])
        reason = "الرد لم يكن JSON صالحًا"

    log.error("تعذّر استخراج بنية المقال بعد %d محاولات: %s", retries, reason)
    return None, reason


# ──────────────────────────── البحث عن الأدلة ────────────────────────────

_DIGIT_RE = re.compile(r"\d")
_TASHKEEL_RE = re.compile(r"[ً-ْـٰ]")  # مطابق لـ request._AR_MARKS
_QUERY_WORD_RE = re.compile(r"[\w']+", re.UNICODE)

# جذور كلمات حشو وأفعال إسناد تكرّرت في استعلامات ركيكة فعليًا رُصدت في
# السجل (Issue #132 تعليق لاحق): 'بلومبرغ لتقرير للتاكد محتواه اليه' —
# اختيار "أطول الكلمات" وحده يأتي بهذه بدل أسماء الأعلام. مطابقة جزئية
# (substring) على الجذر بعد تطبيع request.norm_tokens تلتقط اشتقاقاتها
# (لتقرير/بالتقرير/تقريرها...) دون قائمة صيغ منتهية.
QUERY_FILLER_STEMS = (
    "تقرير", "تاكد", "محتوا", "اليه", "وفق", "حسب", "كمل", "خلال",
    "افاد", "ذكر", "اشار", "صرح", "اعلن", "كشف",
)


def _is_query_filler(normalized: str) -> bool:
    return any(stem in normalized for stem in QUERY_FILLER_STEMS)


def build_query(text: str, max_words: int = 5) -> str:
    """يبني استعلام بحث قصيرًا (كلمات مفتاحية) من نص ادّعاء أو سؤال قد يكون
    جملة كاملة طويلة: بحث Google News RSS يطابق كل كلمات الاستعلام تقريبًا،
    فجملة من عشرين كلمة لا تُطابق أي نتيجة عمليًا حتى لو كان الحدث موثَّقًا
    في عشرات المصادر (Issue #132 تعليق لاحق: ثماني وقائع شهيرة عادت كلها
    "لا مصدر" لهذا السبب بالذات، لا لغياب التغطية).

    الكلمات المُختارة بإملائها **الأصلي** كما وردت في النص — لا بعد تطبيع
    request.norm_tokens الذي يوحّد الهمزات والتاء المربوطة للمطابقة
    الرخوة (مفيد عند الترشيح، لكنه يفسد نص استعلام حرفي: "اتفاقية" كانت
    تصير "اتفاقيه" في الاستعلام فلا تطابق نص المقالات الفعلي — Issue #132
    تعليق لاحق). norm_tokens تُستدعى على كل كلمة منفردة فقط لتحديد هل تنجو
    من تصفية كلمات الوقف/الطول، لا لتحويل الكلمة نفسها.

    الأرقام (سنوات، كميات) أولًا لأنها أدق ما يميّز الادّعاء، ثم أطول
    الكلمات المتبقية بعد استبعاد كلمات الحشو أعلاه — الطول تقريب رخيص
    لعلمية الكلمة (اسم علم أو مكان) بلا استدعاء نموذج إضافي لاستخراج
    كيانات."""
    clean = _TASHKEEL_RE.sub("", text or "")
    seen: set[str] = set()
    numbers: list[str] = []
    words: list[str] = []
    for raw in _QUERY_WORD_RE.findall(clean):
        normalized = norm_tokens(raw)
        if not normalized:
            continue
        norm = next(iter(normalized))
        if norm in seen or _is_query_filler(norm):
            continue
        seen.add(norm)
        (numbers if _DIGIT_RE.search(raw) else words).append(raw)
    words.sort(key=len, reverse=True)
    picked = (numbers + words)[:max_words]
    return " ".join(picked) if picked else clean.strip()


def search(query: str, cfg, days: int) -> list[Article]:
    """يبحث عن استعلام واحد عبر آلية request.py نفسها — بلا تكرار منطقها.

    الدمج الدلالي (merge_cfg) معطَّل هنا عمدًا: هو مصمَّم لمسار النشر حيث
    الهدف تمثيل الحدث بخبر واحد لا تكراره — وهذا بالضبط ما يفسد التحقق،
    حيث تعدد المصادر المستقلة هو المقياس نفسه (Issue #132 تعليق لاحق: ثلاثة
    عناوين من ناشرين مختلفين اندمجت في مجموعة واحدة فصار الحكم "مصدر واحد"
    رغم ثلاثة). تجميع العناوين المتشابهة لفظيًا عبر rank.cluster يبقى يعمل
    (لا مفر منه داخل rank())، لكنه يحفظ كل ناشر أصلي في cluster_members/
    cluster_sources على الممثّل — وهذا ما تعتمد عليه gather_evidence.

    التجميع اللفظي نفسه يستعمل هنا مطبّع request.norm_tokens (عربي+إنجليزي)
    بدل rank.tokens الافتراضي (لاتيني فقط، عمدًا كذلك لمسار الجمع الأساسي
    الذي لا يتأثر — verify.py لا يمسّه) عبر verify.bilingual_cluster في
    config.yaml، وبحد تشابه verify.title_similarity الأخفض من الافتراضي
    (Issue #132 تعليق لاحق: صياغتان عربيتان مستقلتان لحدث واحد لا تتجاوزان
    عمليًا 0.5 تشابهًا حتى بعد التطبيع، فحد selection.title_similarity
    الافتراضي 0.62 — مضبوط لنسخ وكالة شبه متطابقة — يبقيهما مجموعتين
    منفصلتين رغم تطابق المضمون)."""
    vcfg = cfg.get("verify", {}) or {}
    locales = vcfg.get("locales") or DEFAULT_LOCALES

    articles: list[Article] = []
    for feed in search_feeds(query, days, locales):
        articles += fetch_source(feed, max_age_hours=days * 24)
    log.info("بحث %r → %d نتيجة خام؛ أول 3: %s", query, len(articles),
             "؛ ".join(a.title[:80] for a in articles[:3]) or "—")
    if not articles:
        return []

    wanted = norm_tokens(query)
    matched = [a for a in articles if relevant(a, wanted, 1)]
    log.info("بحث %r → %d مطابق من %d خام", query, len(matched), len(articles))
    if not matched:
        return []

    selection = {"max_age_hours": days * 24, "region_diversity": False,
                "title_similarity": float(vcfg.get("title_similarity", 0.62))}
    bilingual = bool(vcfg.get("bilingual_cluster", True))
    return rank(matched, selection, merge_cfg=None,
               token_fn=norm_tokens if bilingual else None)


EVIDENCE_NO_RESULTS = "لا نتائج بحث"
EVIDENCE_HEADLINES_ONLY = "عناوين فقط"
EVIDENCE_FULL_TEXT = "نص كامل"
EVIDENCE_UNREADABLE = "غير قابل للقراءة"


def _relevance(article: Article, wanted: set[str]) -> int:
    """عدد كلمات نص الواقعة/السؤال التي يشاركها عنوان المرشّح وملخصه —
    مقياس صلة مباشر، لا درجة ترند (rank.score) قد لا تمتّ للتفصيلة
    المطلوب التحقق منها بصلة."""
    if not wanted:
        return 0
    haystack = norm_tokens(f"{article.title} {article.summary}")
    return len(wanted & haystack)


def gather_evidence(articles: list[Article], cfg, claim_text: str = "") -> tuple[list[dict], str]:
    """يقرأ نصوص أعلى النتائج، متبِّعًا روابط Google News الوسيطة أولًا
    (عبر sources.resolve_final_url المُصلَحة — Issue #132 تعليق لاحق: كانت
    تفشل دائمًا لأن Google لم يعد يرسل تحويل HTTP حقيقي لهذه الروابط).

    كل عنصر في articles ممثّل مجموعة (دمج عناوين متشابهة لفظيًا عبر
    rank.cluster، يعمل دومًا داخل rank()) — والناشرون المستقلون الآخرون
    الذين اندمجوا فيه محفوظون في cluster_members لا في الممثّل وحده.
    الاكتفاء بلينك/ناشر الممثّل فقط كان يفقد تعدد المصادر بصمت رغم أن
    البحث وجدها فعليًا (Issue #132 تعليق لاحق: 'الدمج الدلالي: ضُمّ 4 خبر
    في 1 مجموعة' ثم 'نصوص مُستخرجة: 1 من 1' رغم ثلاثة عناوين مؤيّدة من
    ناشرين مختلفين) — لذا نوسّع كل ممثّل إلى كل ناشريه الفعليين هنا، فيُعَدّ
    كل ناشر مستقل مصدرًا مستقلًا لا الموضوع/المجموعة ككل.

    articles تُرتَّب حسب claim_text (إن أُعطي) بمدى تطابق كلمات كل ممثّل
    مع نص الواقعة/السؤال نفسه — لا بترتيبها الوارد من search()/rank()
    (درجة ترند، مقياس نشر لا صلة). سقف extract.gather الداخلي (limit*2
    محاولة) يقصّ القائمة قبل القراءة، فترتيب المرشحين يقرر أي نص يُقرأ
    أصلًا لا الحكم عليه فقط (Issue #132 تعليق لاحق: الموضوع الأكثر تحديدًا
    — يذكر الرقم/التاريخ المطلوبين حرفيًا — كان الأقل ترندًا فخرج من نافذة
    القراءة قبل أن يُحاوَل جلبه، فقُرئت نصوص عامة لا تؤيد التفصيلة بدلًا
    من النص الذي كان سيؤيّدها فعلًا).

    حين يتعذّر استخراج أي نص كامل رغم وجود نتائج مطابقة، نسقط للعنوان
    والملخص كدليل أضعف بدل حكم "لا مصدر" رغم وجود مطابقة صريحة في العنوان
    (Issue #132 تعليق لاحق: 'للمرة الأولى منذ 1985.. أمريكا توقف استيراد
    النفط السعودي' كان يؤكد الواقعة حرفيًا، لكن تعذّر استخراج النص أسقطه).

    يعيد (docs, evidence_basis) — evidence_basis إحدى أربع حالات صريحة
    تُعرض في التقرير (Issue #132 تعليق لاحق: "لا نتائج بحث" و"وجدتُ نتائج
    ولم أستطع قراءتها" و"قرأتُ ولم أجد تأييدًا" كانت الثلاث تظهر "لا مصدر"
    نفسها في التقرير، وهذا مضلل)."""
    if not articles:
        return [], EVIDENCE_NO_RESULTS

    if claim_text:
        wanted = norm_tokens(claim_text)
        articles = sorted(articles, key=lambda a: -_relevance(a, wanted))

    vcfg = cfg.get("verify", {}) or {}
    limit = int(vcfg.get("read_per_claim", 3))
    max_members = limit * 4  # هامش فوق سقف extract.gather الداخلي (limit*2)
                              # لأن بعض الروابط قد تفشل قراءتها فعليًا

    seen_links: set[str] = set()
    seen_names: set[str] = set()
    members: list[dict] = []

    def _add(name, link):
        if not name or not link or link in seen_links or name in seen_names:
            return
        seen_links.add(link)
        seen_names.add(name)
        members.append({"name": name, "link": link})

    for a in articles:
        link = a.link
        if "news.google.com" in link:
            link = resolve_final_url(link)
        _add(a.publisher or a.source_name, link)
        for m in a.cluster_members:
            _add(m.get("name"), m.get("link"))
        if len(members) >= max_members:
            break

    fulltext = extract.gather(members, limit=limit)
    if fulltext:
        return [{**d, "from_text": True} for d in fulltext], EVIDENCE_FULL_TEXT

    headline_docs = []
    seen_headline_names: set[str] = set()
    for a in articles:
        name = a.publisher or a.source_name
        if not name or name in seen_headline_names:
            continue
        snippet = f"{a.title}. {a.summary}".strip(" .")
        if snippet:
            headline_docs.append({"name": name, "text": snippet, "from_text": False})
            seen_headline_names.add(name)
        if len(headline_docs) >= limit:
            break
    if headline_docs:
        return headline_docs, EVIDENCE_HEADLINES_ONLY
    return [], EVIDENCE_UNREADABLE


# ──────────────────────────── الحكم على الوقائع ────────────────────────────

def _format_evidence(docs: list[dict]) -> str:
    """يصوغ نصوص الأدلة لإدراجها في طلب الحكم، معلَّمة باسم كل مصدر
    وأساس دليله (نص كامل أو عنوان وملخص فقط عند تعذّر استخراج النص —
    Issue #132 تعليق لاحق). يختلف عن extract.format_for_prompt بإضافة
    وسم الأساس هذا، فلا يُعاد استعمالها كما هي."""
    if not docs:
        return ""
    blocks = []
    for i, d in enumerate(docs, start=1):
        basis = "نص المقال الكامل" if d.get("from_text", True) else \
            "عنوان الخبر وملخصه فقط — لا نص المقال الكامل"
        blocks.append(f"--- المصدر {i}: {d['name']} ({basis}) ---\n{d['text']}")
    return "\n\n".join(blocks)


JUDGE_FACT_SYSTEM = """أنت تقارن ادّعاءً بنصوص مصادر مستقلة عن الحدث نفسه.
لكل نص مصدر معطى حدّد: هل يؤيد الادّعاء صراحة، أم يخالفه صراحة، أم لا علاقة
له به.

قواعد صارمة:
- احكم من النصوص المعطاة فقط. لا تستخدم معرفتك الخاصة عن الموضوع.
- التأييد يعني أن النص يذكر المعلومة نفسها أو ما يقاربها بوضوح، لا مجرد
  ذكر الموضوع العام دون التفصيلة المدّعاة.
- المخالفة تعني تناقضًا حقيقيًا (رقم مختلف بوضوح، نفي صريح) لا فارقًا شكليًا
  في الصياغة أو الوحدة أو رقمًا محدَّثًا مقابل رقم قديم.
- مصدر لم يذكر الادّعاء إطلاقًا لا يُحسب مؤيدًا ولا مخالفًا.
- مصدر معلَّم "عنوان وملخص فقط" نصه قصير وقد يبسّط أو يبالغ — لا تعتبره
  تأييدًا لتفصيلة دقيقة (رقم، تاريخ...) لم يذكرها العنوان صراحة بنفس الدقة.
- أخرج فقط أسماء المصادر المعطاة لك حرفيًا، بلا اختراع أسماء جديدة."""

JUDGE_FACT_SCHEMA = {
    "name": "judge_claim",
    "description": "يحدد أي المصادر المعطاة يؤيد الادّعاء أو يخالفه",
    "input_schema": {
        "type": "object",
        "properties": {
            "supporting": {"type": "array", "items": {"type": "string"}},
            "contradicting": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["supporting", "contradicting"],
    },
}


def _known_only(names, docs: list[dict]) -> list[str]:
    """يستبعد أي اسم مصدر لم يُعطَ فعليًا — لا مصدر مختلَق يدخل التقرير.
    لا يفترض أن names قائمة أصلًا؛ رد النموذج قد يخالف مخطط الأداة."""
    if not isinstance(names, list):
        return []
    known = {d["name"] for d in docs}
    seen: list[str] = []
    for name in names:
        if isinstance(name, str) and name in known and name not in seen:
            seen.append(name)
    return seen


def judge_fact(claim_text: str, docs: list[dict], cfg, retries: int = 2) -> dict:
    vcfg = cfg.get("verify", {}) or {}
    model = vcfg.get("model", "claude-sonnet-5")
    client = _client()
    prompt = (f"الادّعاء: {claim_text}\n\n"
             f"نصوص المصادر:\n\n{_format_evidence(docs)}")

    for attempt in range(1, retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=500,
                tools=[JUDGE_FACT_SCHEMA],
                tool_choice={"type": "tool", "name": "judge_claim"},
                system=JUDGE_FACT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            record_usage(resp, model)
            data = next((b.input for b in resp.content
                        if getattr(b, "type", "") == "tool_use"), None)
            if data is not None:
                supporting = _known_only(data.get("supporting"), docs)
                contradicting = _known_only(data.get("contradicting"), docs)
                # تسجيل دائم لا عند الفشل فقط (Issue #132 تعليق لاحق: طُلب
                # توفره حتى لو لم يكن هو سبب عطل بعينه، لتشخيص أي تذبذب
                # مستقبلي — رد النموذج الحرفي، وأسماء docs المعطاة له، وما
                # بقي بعد استبعاد الأسماء المختلَقة — من السجل مباشرة بلا
                # تخمين في الجولة القادمة)
                log.info(
                    "حكم واقعة %r — رد النموذج الحرفي: supporting=%s "
                    "contradicting=%s؛ أسماء المصادر المعطاة: %s؛ بعد "
                    "_known_only: supporting=%s contradicting=%s",
                    claim_text[:80], data.get("supporting"), data.get("contradicting"),
                    sorted(d["name"] for d in docs), supporting, contradicting)
                return {"supporting": supporting, "contradicting": contradicting}
        except APIError as exc:
            log.warning("محاولة %d/%d فشلت في الحكم على واقعة: %s", attempt, retries, exc)
    return {"supporting": [], "contradicting": []}


def classify_fact(supporting: list[str], contradicting: list[str],
                  min_confirm: int) -> str:
    """
    التصنيف بكود لا بالنموذج: النموذج يحدد من أيّد ومن خالف فقط، والعدّ
    يحدّد الحكم — فلا يقع الحكم النهائي رهن صياغة النموذج له في كل استدعاء.
    """
    if len(set(supporting)) >= min_confirm:
        return STATUS_CONFIRMED
    if contradicting:
        return STATUS_CONTRADICTED
    if supporting:
        return STATUS_SINGLE
    return STATUS_NONE


# ──────────────────────────── الحكم على الأسئلة ────────────────────────────

JUDGE_QUESTION_SYSTEM = """أنت تبحث في نصوص مصادر مستقلة عن جواب لسؤال أثاره
مقال آخر. أجب فقط إن وجدت الجواب صراحة في النصوص المعطاة، ولا تستخدم معرفتك
الخاصة عن الموضوع مهما بدت لك صحيحة. انسب الجواب لمن قاله في المصدر — لا
تصغه كحقيقة مطلقة من عندك. مصدر معلَّم "عنوان وملخص فقط" نصه قصير — لا تبنِ
عليه جوابًا تفصيليًا لم يذكره صراحة بنفس الدقة."""

JUDGE_QUESTION_SCHEMA = {
    "name": "answer_question",
    "description": "يجيب عن سؤال من نصوص مصادر معطاة فقط، أو يقر بغياب الجواب",
    "input_schema": {
        "type": "object",
        "properties": {
            "answered": {"type": "boolean"},
            "answer": {"type": "string"},
            "source": {"type": "string"},
        },
        "required": ["answered"],
    },
}


def judge_question(question: str, docs: list[dict], cfg, retries: int = 2) -> dict:
    vcfg = cfg.get("verify", {}) or {}
    model = vcfg.get("model", "claude-sonnet-5")
    client = _client()
    prompt = (f"السؤال: {question}\n\n"
             f"نصوص المصادر:\n\n{_format_evidence(docs)}")

    for attempt in range(1, retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=400,
                tools=[JUDGE_QUESTION_SCHEMA],
                tool_choice={"type": "tool", "name": "answer_question"},
                system=JUDGE_QUESTION_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            record_usage(resp, model)
            data = next((b.input for b in resp.content
                        if getattr(b, "type", "") == "tool_use"), None)
            if data is not None:
                source = str(data.get("source") or "")
                return {
                    "answered": bool(data.get("answered")) and source in
                               {d["name"] for d in docs},
                    "answer": str(data.get("answer") or ""),
                    "source": source,
                }
        except APIError as exc:
            log.warning("محاولة %d/%d فشلت في الإجابة عن سؤال: %s", attempt, retries, exc)
    return {"answered": False, "answer": "", "source": ""}


# ──────────────────────────── التنسيق الكامل ────────────────────────────


def verify_article(body: str, cfg) -> dict:
    """يلتقط أي انهيار غير متوقع (رد نموذج بشكل لم يُتوقَّع رغم التطبيع، خطأ
    شبكة لم يُلتقط في طبقة أدنى...) فلا يصل traceback إلى تعليق الـ Issue —
    المستخدم لا يقرأ سجلات Actions."""
    try:
        return _verify_article(body, cfg)
    except Exception:
        log.exception("انهيار غير متوقع أثناء التحقق من المقال")
        return {"ok": False,
                "reason": "حدث خطأ غير متوقع أثناء التحقق — راجع سجلات Actions للتفاصيل"}


def _verify_article(body: str, cfg) -> dict:
    vcfg = cfg.get("verify", {}) or {}
    days = int(vcfg.get("days", 14))
    max_claims = int(vcfg.get("max_claims", 8))
    max_questions = int(vcfg.get("max_questions", 5))
    min_confirm = int(vcfg.get("min_confirm_sources", 2))
    query_max_words = int(vcfg.get("query_max_words", 5))

    extracted, extract_error = extract_claims(body, cfg)
    if not extracted:
        return {"ok": False, "reason": extract_error or "تعذّر استخراج بنية المقال"}

    raw_topic = _first_present(extracted, TOPIC_ALT_KEYS)
    raw_claims = _first_present(extracted, CLAIMS_ALT_KEYS)
    raw_questions = _first_present(extracted, QUESTIONS_ALT_KEYS)

    claims = normalize_claims(raw_claims)
    if not claims:
        # الاستدعاء نجح ورد النموذج غير فارغ (Issue #132 تعليق لاحق: 1858
        # توكن إخراج)، لكن التطبيع لم يجد ادّعاءً واحدًا صالحًا — سواء لغياب
        # حقل claims/facts/statements تمامًا تحت كل الأسماء المعروفة، أو
        # لعناصر بشكل غريب لا نص فيه. هذا تطبيع أسقط كل شيء، لا نجاحًا
        # صامتًا: تقرير فارغ يبدو مشروعًا أسوأ من فشل صريح يُطلب فيه إعادة
        # المحاولة أو مراجعة السجل.
        log.error("تعذّر تفسير بنية رد الاستخراج رغم نجاح الاستدعاء — "
                 "أسماء الحقول في الرد: %s؛ الرد الكامل: %s",
                 sorted(extracted.keys()),
                 json.dumps(extracted, ensure_ascii=False))
        return {"ok": False, "reason": "تعذّرت قراءة بنية الرد"}

    facts = [c for c in claims if c["kind"] == "واقعة"][:max_claims]
    other_claims = [c for c in claims if c["kind"] != "واقعة"]
    questions = normalize_questions(raw_questions)[:max_questions]

    fact_results = []
    for claim in facts:
        text = claim.get("text", "")
        ranked = search(build_query(text, query_max_words), cfg, days)
        docs, evidence_basis = gather_evidence(ranked, cfg, text)
        judged = (judge_fact(text, docs, cfg) if docs
                 else {"supporting": [], "contradicting": []})
        status = classify_fact(judged["supporting"], judged["contradicting"],
                               min_confirm)
        fact_results.append({
            "text": text,
            "status": status,
            "supporting": judged["supporting"],
            "contradicting": judged["contradicting"],
            "evidence_basis": evidence_basis,
        })

    question_results = []
    for text in questions:
        ranked = search(build_query(text, query_max_words), cfg, days)
        docs, evidence_basis = gather_evidence(ranked, cfg, text)
        judged = (judge_question(text, docs, cfg) if docs
                 else {"answered": False, "answer": "", "source": ""})
        question_results.append({
            "text": text,
            "answered": bool(judged.get("answered")),
            "answer": judged.get("answer", ""),
            "source": judged.get("source", ""),
            "evidence_basis": evidence_basis,
        })

    contradictions = [f for f in fact_results if f["status"] == STATUS_CONTRADICTED]
    confirmed = [f for f in fact_results if f["status"] == STATUS_CONFIRMED]

    if not fact_results:
        verdict, verdict_reason = False, "لم يُستخرج من المقال أي واقعة قابلة للتحقق"
    elif confirmed:
        verdict = True
        verdict_reason = (f"{len(confirmed)} واقعة مؤكَّدة بمصدرين مستقلين فأكثر "
                          f"من أصل {len(fact_results)}")
    else:
        verdict = False
        verdict_reason = ("لا واقعة واحدة مؤكَّدة بمصدرين مستقلين — المصادر "
                          "المستقلة لا تكفي لخبر قائم بذاته")

    return {
        "ok": True,
        "topic": _as_text(raw_topic) or "(لم يُستخرج موضوع محدد)",
        "facts": fact_results,
        "opinions": other_claims,
        "questions": question_results,
        "contradictions": contradictions,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
    }


def build_report(result: dict) -> str:
    if not result.get("ok"):
        return f"### 🔎 تعذّر التحقق\n\n{result.get('reason', '')}"

    lines = ["### 🔎 تقرير التحقق", "", f"**الموضوع:** {result['topic']}", ""]

    # عمود "الأدلة" يميّز صراحة بين لا نتائج بحث / نتائج بلا نص مقروء
    # (عناوين فقط) / نص مقروء — الثلاثة كانت تظهر "لا مصدر" نفسها فتبدو
    # متطابقة رغم اختلاف السبب جذريًا (Issue #132 تعليق لاحق).
    lines += ["#### الوقائع", ""]
    if result["facts"]:
        lines += ["| الواقعة | الحكم | الأدلة | المصادر المؤيدة | المصادر المخالفة |",
                  "|---|---|---|---|---|"]
        for f in result["facts"]:
            lines.append(
                f"| {f['text']} | {f['status']} | {f.get('evidence_basis', '—')} | "
                f"{'، '.join(f['supporting']) or '—'} | "
                f"{'، '.join(f['contradicting']) or '—'} |"
            )
    else:
        lines.append("لم يستخرج من المقال أي واقعة قابلة للتحقق.")
    lines.append("")

    lines += ["#### الأسئلة المطروحة", ""]
    if result["questions"]:
        for q in result["questions"]:
            basis = q.get("evidence_basis", "")
            basis_note = f" ({basis})" if basis and basis != EVIDENCE_FULL_TEXT else ""
            if q["answered"]:
                lines.append(f"- **{q['text']}** — {q['answer']} "
                             f"(بحسب {q['source']}){basis_note}")
            else:
                lines.append(f"- **{q['text']}** — لم توجد إجابة في المصادر "
                             f"المستقلة{basis_note}")
    else:
        lines.append("لم يثر المقال أسئلة مفتوحة تستحق بحثًا مستقلًا.")
    lines.append("")

    lines += ["#### ⚠️ أين خالفت المصادر المقال", ""]
    if result["contradictions"]:
        for f in result["contradictions"]:
            lines.append(f"- **{f['text']}** — تخالفه: {'، '.join(f['contradicting'])}")
    else:
        lines.append("لم يظهر أي تناقض بين المقال والمصادر المستقلة.")
    lines.append("")

    verdict_icon = "✅" if result["verdict"] else "❌"
    verdict_word = "نعم" if result["verdict"] else "لا"
    lines += ["#### الحكم النهائي", "",
             f"{verdict_icon} **{verdict_word}** — {result['verdict_reason']}"]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="تحقق من مقال ملصق في Issue")
    parser.add_argument("--issue", type=int, required=True, help="رقم الـ Issue")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")

    cfg = load_config()
    body = review.fetch_issue_body(args.issue)
    if not body.strip():
        review.comment(args.issue,
                       "### 🔎 لا نص\nالـ Issue لا يحوي نص مقال للتحقق منه.")
        return 0

    result = verify_article(body, cfg)
    report = build_report(result)
    review.comment(args.issue, f"{report}\n\n<sub>💵 {usage_summary()}</sub>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
