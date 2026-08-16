"""محرك بحث وقراءة مستقل عن أي حكم أو تصنيف: يبني استعلامًا من نص/كيانات،
يبحث عبر request.py، ويقرأ أفضل النتائج نصًا كاملًا أو احتياط عنوان+ملخص.

مُستخرَجة من src/verify.py (Issue #348، تعليق الموافقة على التشخيص، البند 1):
هذا الجزء عام بطبيعته — بحث وقراءة نصوص — بلا علاقة بـ classify_fact/
judge_fact وجدول الأحكام اللذين ظلّا في verify.py (ويستوردان من هنا الآن
بدل تعريفها محليًا، فلا تعريف مزدوج). src/article.py (مسار «مقال من
المصادر») يستهلك هذه الوحدة مباشرة بلا أي مرور عبر verify.py.

نُقلت الدوال هنا بلا تعديل سلوكي — التعليقات التاريخية (إشارات لأرقام
Issue سابقة) أُبقيت كما هي لأنها توثّق أسباب قرارات لا تزال سارية.
"""
from __future__ import annotations

import logging
import re

from . import extract
from .rank import STOPWORDS, rank
from .request import DEFAULT_LOCALES, _AR_STOP, _AR_TRANS, norm_tokens, relevant, search_feeds
from .sources import Article, fetch_source, resolve_final_url

log = logging.getLogger("evidence")


# ──────────────────────────── بناء استعلام البحث ────────────────────────────

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
    # "عام"/"عاما"/"لعام": كلمة عمر أو زمن عامة لا كيان مميِّز — دخلت
    # استعلامًا فعليًا في تشخيص Issue #364 (سؤال عن طفل عمره 13 عامًا) وزاحمت
    # الكيانات الحقيقية على سقف max_words لمجرد طولها
    "عام",
)


def _is_query_filler(normalized: str) -> bool:
    return any(stem in normalized for stem in QUERY_FILLER_STEMS)


def _normalize_query_word(raw: str) -> str | None:
    """يطبّع كلمة استعلام واحدة: نفس تحويلات request.norm_tokens (توحيد
    الهمزات والتاء المربوطة، إسقاط "ال" التعريف، استبعاد كلمات الوقف
    العربية/الإنجليزية) **بلا شرط الطول** (len > 2 في norm_tokens).

    ذلك الشرط صيغ أصلًا لفلترة كلمات وقف في المطابقة الرخوة
    (request.relevant)، لا لتقرير أي كلمة **حرفية** تدخل استعلام بحث —
    تشخيص Issue #364 المعتمَد أثبت أنه كان يُسقط بنيويًا كل تاريخ يوم من
    رقمين (كل الأيام 10-31) وكل شهر عربي من حرفين ("آب" تحديدًا) من كل
    استعلام يُبنى عبر build_query/build_query_for_claim — أي كل مستدعييهما
    معًا (article.py وverify.py)، لا مسار بعينه.

    دالة مستقلة بلا لمس norm_tokens نفسها عمدًا: تلك لها مستدعون آخرون
    (request.relevant وrank.cluster عبر bilingual_cluster) يعتمدون على شرط
    الطول لغرضه الأصلي، وتعديله هناك كان سيمسّهم جميعًا بأثر جانبي غير
    مقصود. يعيد الكلمة المطبَّعة، أو None إن كانت كلمة وقف أو فارغة بعدها."""
    word = (raw or "").lower().translate(_AR_TRANS)
    if word.startswith("ال") and len(word) > 4:
        word = word[2:]
    if not word or word in STOPWORDS or word in _AR_STOP:
        return None
    return word


def build_query(text: str, max_words: int = 5, *, legacy_sort: bool = False) -> str:
    """يبني استعلام بحث قصيرًا (كلمات مفتاحية) من نص ادّعاء أو سؤال قد يكون
    جملة كاملة طويلة: بحث Google News RSS يطابق كل كلمات الاستعلام تقريبًا،
    فجملة من عشرين كلمة لا تُطابق أي نتيجة عمليًا حتى لو كان الحدث موثَّقًا
    في عشرات المصادر (Issue #132 تعليق لاحق: ثماني وقائع شهيرة عادت كلها
    "لا مصدر" لهذا السبب بالذات، لا لغياب التغطية).

    الكلمات المُختارة بإملائها **الأصلي** كما وردت في النص — لا بعد تطبيع
    request.norm_tokens الذي يوحّد الهمزات والتاء المربوطة للمطابقة
    الرخوة (مفيد عند الترشيح، لكنه يفسد نص استعلام حرفي: "اتفاقية" كانت
    تصير "اتفاقيه" في الاستعلام فلا تطابق نص المقالات الفعلي — Issue #132
    تعليق لاحق). _normalize_query_word تُستدعى على كل كلمة منفردة فقط
    لتحديد هل تنجو من تصفية كلمات الوقف، لا لتحويل الكلمة نفسها — وبلا
    شرط طول (خلافًا لـnorm_tokens) كي لا يسقط تاريخ يوم من رقمين أو شهر
    عربي من حرفين (تشخيص Issue #364).

    الافتراضي (Issue #361 تعليق الموافقة الثالث، البند 1) يحفظ **ترتيب
    الورود الأصلي** بلا فصل الأرقام إلى مقدمة الاستعلام: تشخيص معتمَد وجد
    أن الفصل يُبعثر تركيبات طبيعية («11 آب 2026» صارت «11 2026 الخطيب حمزة
    آب» فعليًا في تشغيل حقيقي) — «آب» شهر حرفي لا رقمي فيُصنَّف "كلمة" ثم
    يُدفَع لآخر الاستعلام بالفرز بالطول، فينفصل عن رفيقيه الرقميين رغم
    فصلهما عمدًا لتصدُّر الاستعلام. محركات البحث ترجّح تجاور الكلمات، وهذا
    ما يكتبه إنسان فعلًا.

    legacy_sort=True يستعيد السلوك القديم (الأرقام أولًا، ثم أطول الكلمات
    المتبقية تنازليًا) — محجوز حصرًا لـ verify.py:779 (استعلام سؤال بلا
    entities، من نص خام قد يطول لعشرين كلمة). ذلك مسار متقاعد ينتظر الحذف
    (src/article.py يوثّق الاستبدال)، فأي إصلاح إضافي فيه مهدور — أُبقي
    سلوكه القديم خلف هذا المعامل الصريح بدل تطوير بديل له أو المخاطرة
    بإسقاط رقم/تاريخ يرد متأخرًا في جملة طويلة بلا entities تضمن ظهوره.
    كل مستدعٍ آخر (article.py: كيانات+تاريخ مباشرة، build_query_for_claim
    من entities) نص قصير أو مبني من قائمة entities أصلًا — لا خطر إسقاط."""
    clean = _TASHKEEL_RE.sub("", text or "")
    seen: set[str] = set()

    if legacy_sort:
        numbers: list[str] = []
        words: list[str] = []
        for raw in _QUERY_WORD_RE.findall(clean):
            norm = _normalize_query_word(raw)
            if norm is None or norm in seen or _is_query_filler(norm):
                continue
            seen.add(norm)
            (numbers if _DIGIT_RE.search(raw) else words).append(raw)
        words.sort(key=len, reverse=True)
        picked = (numbers + words)[:max_words]
    else:
        picked = []
        for raw in _QUERY_WORD_RE.findall(clean):
            norm = _normalize_query_word(raw)
            if norm is None or norm in seen or _is_query_filler(norm):
                continue
            seen.add(norm)
            picked.append(raw)
            if len(picked) >= max_words:
                break

    return " ".join(picked) if picked else clean.strip()


def _entities_text(claim: dict) -> str:
    """نص الكيانات الثابتة لادّعاء (أسماء أعلام/أرقام/سنوات/أماكن، منقولة
    حرفيًا من نص المصدر بلا إعادة صياغة)، أو سلسلة فارغة إن غابت entities
    أو خلت من عناصر صالحة. يستعملها كل من build_query_for_claim (بناء
    الاستعلام) وترتيب صلة القراءة في gather_evidence — كلاهما يحتاج نصًا
    ثابتًا عبر تشغيلات متكررة لنفس الادّعاء، لا نص claim["text"] المعاد
    صياغته بحرية في كل استخراج."""
    entities = claim.get("entities") or []
    return " ".join(e for e in entities if isinstance(e, str) and e.strip())


def build_query_for_claim(claim: dict, max_words: int = 5) -> str:
    """يبني استعلام البحث من entities الادّعاء حصرًا حين تتوفر، لا من نص
    الجملة المعاد صياغتها في كل تشغيل (العلاج 2، Issue #132 تعليق لاحق:
    ثلاث إعادات صياغة معقولة رصدها تشخيص سابق لنفس الحقيقة الواحدة أنتجت
    53 مقابل 2 مقابل 3 نتيجة بحث مختلفة جذريًا، لأن build_query كانت تُشتق
    من نص الادّعاء المعاد صياغته نفسه في كل تشغيل رغم ثبات الحقيقة نفسها).

    entities غائبة أو فارغة تُسقط لبناء الاستعلام من نص الادّعاء كاملًا عبر
    build_query — بلا تكرار منطقها."""
    return build_query(_entities_text(claim) or claim.get("text", ""), max_words)


# سقف عمر بديل للوقائع المرجعية (البند 5، تعليق التنفيذ على PR #340):
# search_feeds تُسقط قيد when: تمامًا لهذه الحالة، لكن fetch_source نفسها
# تُصفّي بعد الجلب بـmax_age_hours أيضًا (سطر الاستدعاء أدناه) — بلا رفعه
# هنا أيضًا يبقى مصدر بعمر الواقعة نفسها (كتاب صدر قبل سنوات) مرفوضًا بعد
# جلبه فعليًا رغم إسقاط when: من الاستعلام. 20 سنة تتجاوز عمليًا أي مصدر
# ويب حي دون تعطيل cutoff الآلية نفسها (لا None هنا — fetch_source تطرح
# فرقًا زمنيًا من الآن، فقيمة عددية كبيرة تبقيها بلا تفرّع خاص).
REFERENCE_MAX_AGE_HOURS = 20 * 365 * 24


class SearchResult(list):
    """قائمة نتائج بحث عادية (ما تعيده search())، مع عدّاد النتائج الخام
    والمطابقة قبل الفرز/الدمج كسمتين إضافيتين — البند 1 (تعليق العطل
    الثاني على Issue #361): trail في article.py يحتاج عدد النتائج قبل
    التصفية بالصلة وبعدها ليُشخَّص لماذا سقط استعلام معيَّن لمصدر واحد رغم
    تغطية واسعة، لا "عناوين فقط" مجرَّدة بلا رقم. مستهلكون آخرون (verify.py)
    يتعاملون معها كقائمة عادية بلا أي تغيير في العقد — list.__eq__ يقارن
    بالعناصر لا بنوع الصنف، فكل مقارنة/تكرار/فهرسة قائمة بها تسلك كسابقتها
    تمامًا.

    rejected_titles: عيّنة (5 كحد أقصى) من عناوين النتائج الخام التي رفضها
    فلتر الصلة (relevant) — البند 4 (تعليق الموافقة الثالث على Issue #361):
    الحدث المطلوب قد لا يذكر كيان الموجز في عنوانه (خبر عن محكمة قد يذكر
    الكيان في سطر فرعي فقط)، فقد نرفض الخبر الصحيح قبل قراءته. لا تُعالَج
    هذه الفرضية الآن — العيّنة هنا للتشخيص فقط، تُعرَض حصرًا في مرحلة
    التسمية المباشرة (article.py) لا كل استعلام."""
    raw_count: int
    matched_count: int
    rejected_titles: list


def _search_result(items, raw_count: int, matched_count: int,
                   rejected_titles: list | None = None) -> SearchResult:
    out = SearchResult(items)
    out.raw_count = raw_count
    out.matched_count = matched_count
    out.rejected_titles = rejected_titles or []
    return out


def search(query: str, cfg, days: int, unrestricted: bool = False,
          require_relevance: bool = True) -> list[Article]:
    """يبحث عن استعلام واحد عبر آلية request.py نفسها — بلا تكرار منطقها.

    الدمج الدلالي (merge_cfg) معطَّل هنا عمدًا: هو مصمَّم لمسار النشر حيث
    الهدف تمثيل الحدث بخبر واحد لا تكراره — وهذا بالضبط ما يفسد التحقق،
    حيث تعدد المصادر المستقلة هو المقياس نفسه (Issue #132 تعليق لاحق: ثلاثة
    عناوين من ناشرين مختلفين اندمجت في مجموعة واحدة فصار الحكم "مصدر واحد"
    رغم ثلاثة). تجميع العناوين المتشابهة لفظيًا عبر rank.cluster يبقى يعمل
    (لا مفر منه داخل rank())، لكنه يحفظ كل ناشر أصلي في cluster_members/
    cluster_sources على الممثّل — وهذا ما تعتمد عليه gather_evidence.

    التجميع اللفظي نفسه يستعمل هنا مطبّع request.norm_tokens (عربي+إنجليزي)
    بدل rank.tokens الافتراضي (لاتيني فقط) عبر verify.bilingual_cluster في
    config.yaml (يبقى تحت مفتاح verify: — مشترك بين verify.py وarticle.py،
    لا مكرَّر)، وبحد تشابه verify.title_similarity الأخفض من الافتراضي.

    unrestricted=True (واقعة مرجعية) يُسقط قيد when: من الاستعلام
    (search_feeds) ويرفع سقف عمر النتائج المقبولة إلى REFERENCE_MAX_AGE_HOURS
    بدل days*24 — كلاهما ضروري معًا، فإسقاط when: وحده لا يمنع fetch_source
    من رفض مصدر قديم بعد جلبه فعليًا.

    require_relevance=False (تشخيص Issue #373، البند 1: عيّنة حقيقية —
    الخبر الصحيح عن حكم إعدام بحق الأسد رُفض هنا لأن عنوانه لم يذكر «حمزة
    الخطيب» الوارد في الاستعلام، بينما نجا موقع نتائج رياضية بمطابقة لفظية
    عابرة) يُسقط فلتر relevant() هنا كليًا: كل نتيجة خام تدخل الفرز/الترتيب
    بلا استبعاد مسبق بمطابقة كلمة واحدة في العنوان/الملخص. الحدث المطلوب قد
    لا يحمل اسم الكيان الذي قاد إليه إطلاقًا — التاريخ هو الرابط، لا الاسم،
    فمطابقة كلمة واحدة في العنوان معيار خاطئ لهذه المرحلة تحديدًا. الاستدعاء
    المسؤول (article._try، مرحلتا «مباشر»/«سياق» فقط) يمرّر
    loose_relevance=True لـgather_evidence أيضًا، فبوابة الاتساق
    (_naming_consistent/_dates_consistent) — لا هذا الفلتر — تصير الحارس
    الوحيد على دقة التسمية؛ الكلفة محدودة (مجموعة مرشحي الفرز تتسع، لا عدد
    القراءات الفعلية المحدود بـread_per_claim). مستدعون آخرون (request.py،
    verify.py عبر هذه الدالة) لا شبكة أمان مكافئة لديهم فيبقون على الافتراضي
    True."""
    vcfg = cfg.get("verify", {}) or {}
    locales = vcfg.get("locales") or DEFAULT_LOCALES
    max_age_hours = REFERENCE_MAX_AGE_HOURS if unrestricted else days * 24

    articles: list[Article] = []
    for feed in search_feeds(query, None if unrestricted else days, locales):
        articles += fetch_source(feed, max_age_hours=max_age_hours)
    log.info("بحث %r → %d نتيجة خام؛ أول 3: %s", query, len(articles),
             "؛ ".join(a.title[:80] for a in articles[:3]) or "—")
    if not articles:
        return _search_result([], 0, 0)

    if not require_relevance:
        matched: list[Article] = list(articles)
        rejected_titles: list[str] = []
    else:
        wanted = norm_tokens(query)
        matched = []
        # عيّنة عناوين مرفوضة بالصلة (5 كحد أقصى) — البند 4، انظر توثيق
        # SearchResult.rejected_titles أعلاه
        rejected_titles = []
        for a in articles:
            if relevant(a, wanted, 1):
                matched.append(a)
            elif len(rejected_titles) < 5:
                rejected_titles.append(a.title)
    log.info("بحث %r → %d مطابق من %d خام", query, len(matched), len(articles))
    if not matched:
        return _search_result([], len(articles), 0, rejected_titles)

    selection = {"max_age_hours": days * 24, "region_diversity": False,
                "title_similarity": float(vcfg.get("title_similarity", 0.62))}
    bilingual = bool(vcfg.get("bilingual_cluster", True))
    # keep_google_links=True: نتائج هذا البحث كلها من Google News (بلا
    # استثناء)، فاستبعاد rank.pick_representative الافتراضي لروابط جوجل من
    # cluster_members كان يُفرغها هنا شبه دائمًا قبل أن تصل gather_evidence
    ranked = rank(matched, selection, merge_cfg=None,
                 token_fn=norm_tokens if bilingual else None,
                 keep_google_links=True)
    return _search_result(ranked, len(articles), len(matched), rejected_titles)


EVIDENCE_NO_RESULTS = "لا نتائج بحث"
EVIDENCE_HEADLINES_ONLY = "عناوين فقط"
EVIDENCE_FULL_TEXT = "نص كامل"
EVIDENCE_UNREADABLE = "غير قابل للقراءة"


def _loose_tokens(text: str) -> set[str]:
    """مطبِّع صلة بلا شرط الطول (خلافًا لـrequest.norm_tokens) — يستعمل
    نفس تطبيع _normalize_query_word لكل كلمة (توحيد الهمزات/التاء المربوطة
    وإسقاط كلمات الوقف، بلا شرط len > 2). تشخيص Issue #373 (البند 1) وجد
    أن _relevance كانت سترث عطل Issue #364 (إسقاط تاريخ يوم من رقمين وشهر
    عربي من حرفين) لو صارت البوابة الوحيدة على مرحلتَي «مباشر»/«سياق» بعد
    تعطيل فلتر relevant() فيهما (search(require_relevance=False)) — تلك
    التواريخ هي بالضبط ما يربط المرشح الصحيح بالواقعة حين لا يُذكر اسم
    الكيان في العنوان. تُستعمل حصرًا حين يُطلَب loose_relevance=True في
    gather_evidence، لا كتغيير افتراضي لمسارات أخرى (verify.py) بلا شبكة
    أمان مكافئة (بوابة الاتساق)."""
    clean = _TASHKEEL_RE.sub("", text or "")
    out: set[str] = set()
    for raw in _QUERY_WORD_RE.findall(clean):
        norm = _normalize_query_word(raw)
        if norm:
            out.add(norm)
    return out


def _relevance(article: Article, wanted: set[str], token_fn=norm_tokens) -> int:
    """عدد كلمات نص الواقعة/السؤال التي يشاركها عنوان المرشّح وملخصه —
    مقياس صلة مباشر، لا درجة ترند (rank.score) قد لا تمتّ للتفصيلة
    المطلوب التحقق منها بصلة. token_fn قابل للاستبدال بـ_loose_tokens (انظر
    توثيقها) حين يكون الفرز هو البوابة الوحيدة على الصلة، فلا يُسقط تاريخًا
    قصيرًا كان سيقرر الحكم."""
    if not wanted:
        return 0
    haystack = token_fn(f"{article.title} {article.summary}")
    return len(wanted & haystack)


def _candidate_score(weight: float, relevance: int) -> float:
    """درجة مركّبة تجمع وزن الناشر وصلة النص لترتيب مرشّحي القراءة في
    gather_evidence، بدل الفرز التتابعي (-وزن ثم -صلة) الذي أضرّ بالنتيجة
    فعليًا (Issue #132 تعليق لاحق): حين يملأ عدد كافٍ من المرشحين الموثوقين
    بلا أي صلة نافذة قراءة ضيقة، كان الفرز التتابعي يُقصي كليًا مرشّحًا شديد
    الصلة بوزن أقل — بصرف النظر عن مدى ارتفاع صلته. الجمع البسيط يجعل
    الصلة العالية قادرة على تعويض فارق الوزن الأقصى بدل أن يُقصيها كليًا،
    والوزن العالي يبقى قادرًا على تعويض صلة أضعف عند تقاربها."""
    return weight + relevance


class EvidenceDocs(list):
    """قائمة وثائق عادية (ما تعيده gather_evidence كعنصر أول)، مع سجلّ فشل
    جلب النص الكامل كسمة إضافية — البند 1 (تعليق العطل الثاني على Issue
    #361): trail يحتاج سبب فشل كل رابط تعذّر جلبه (رمز HTTP أو نوع العطل)
    حين يُسقَط المسار إلى احتياط العناوين. مستهلكون آخرون (verify.py)
    يتعاملون معها كقائمة عادية بلا أي تغيير في العقد الحالي (docs, basis)."""
    fetch_failures: list


def _evidence_docs(items, fetch_failures: list) -> EvidenceDocs:
    out = EvidenceDocs(items)
    out.fetch_failures = fetch_failures
    return out


def gather_evidence(articles: list[Article], cfg, claim_text: str = "",
                    loose_relevance: bool = False) -> tuple[list[dict], str]:
    """يقرأ نصوص أعلى النتائج، متبِّعًا روابط Google News الوسيطة أولًا
    (عبر sources.resolve_final_url).

    loose_relevance=True (تشخيص Issue #373، البند 1) يستعمل _loose_tokens
    بدل norm_tokens لحساب الصلة (wanted وحاصل عنوان/ملخص كل مرشح معًا) —
    بلا شرط الطول الذي يُسقط تاريخًا قصيرًا (يوم من رقمين، شهر عربي من
    حرفين) كان سيميّز المرشح الصحيح حين لا يذكر عنوانه اسم الكيان. يُستعمل
    من article._try (مرحلتا «مباشر»/«سياق» فقط) مقترنًا بـ
    search(require_relevance=False) — الفرز هنا يصير البوابة الوحيدة على
    الصلة فلا يجوز أن يرث عطل الطول نفسه.

    كل عنصر في articles ممثّل مجموعة (دمج عناوين متشابهة لفظيًا عبر
    rank.cluster) — والناشرون المستقلون الآخرون الذين اندمجوا فيه محفوظون
    في cluster_members لا في الممثّل وحده. نوسّع كل ممثّل إلى كل ناشريه
    الفعليين هنا، فيُعَدّ كل ناشر مستقل مصدرًا مستقلًا لا الموضوع/المجموعة
    ككل — لكن هذا التوسيع يعمل على أسماء ناشرين خامة كما وردت في نتيجة
    البحث، وقد يكرّر الناشر نفسه باسمين مختلفين (نسخته العربية والإنجليزية
    من نتيجتَي بحث مختلفتين، مثال حقيقي: "الجزيرة نت" و"Al Jazeera" —
    تشخيص Issue #373، الجولة الرابعة، البند 1). لذا يُوحَّد مرشحو القراءة
    بهوية الناشر (_canonical_publisher) **قبل** اختيارهم لا بعده — فناشر
    واحد بلغتين يستهلك فتحة قراءة واحدة من read_per_claim لا فتحتين،
    ويُعَدّ مصدرًا مستقلًا واحدًا لا اثنين حين يُحسب سند الواقعة لاحقًا في
    article.py (unique = set(supporting) يرث هذا التوحيد تلقائيًا لأن كل
    ما تراه set() أصلًا هو الأسماء الخامة الناجية من هذا التوحيد وحدها).

    articles تُرتَّب حسب claim_text (إن أُعطي) بمدى تطابق كلمات كل ممثّل
    مع نص الواقعة/السؤال نفسه — لا بترتيبها الوارد من search()/rank()
    (درجة ترند، مقياس نشر لا صلة). سقف extract.gather الداخلي (limit*2
    محاولة) يقصّ القائمة قبل القراءة، فترتيب المرشحين يقرر أي نص يُقرأ
    أصلًا لا الحكم عليه فقط.

    حين يتعذّر استخراج أي نص كامل رغم وجود نتائج مطابقة، نسقط للعنوان
    والملخص كدليل أضعف بدل حكم "لا مصدر" رغم وجود مطابقة صريحة في العنوان.

    ترتيب القراءة بدرجة مركّبة (_candidate_score: وزن الناشر + الصلة)، لا
    بفرز تتابعي (-وزن ثم -صلة). الوزن يُحسب لكل مرشح على حدة — الممثّل وكل
    عضو من cluster_members — لا للممثّل وحده، فناشر موثوق مدفون داخل مجموعة
    لا يخرج من نافذة القراءة بسبب ترتيب مجموعته.

    يعيد (docs, evidence_basis) — evidence_basis إحدى أربع حالات صريحة
    تُعرض في التقرير ("لا نتائج بحث" و"وجدتُ نتائج ولم أستطع قراءتها"
    و"قرأتُ ولم أجد تأييدًا" كانت الثلاث تظهر "لا مصدر" نفسها، وهذا مضلل)."""
    if not articles:
        return [], EVIDENCE_NO_RESULTS

    token_fn = _loose_tokens if loose_relevance else norm_tokens
    wanted = token_fn(claim_text) if claim_text else set()

    vcfg = cfg.get("verify", {}) or {}
    limit = int(vcfg.get("read_per_claim", 3))
    max_members = limit * 4  # هامش فوق سقف extract.gather الداخلي (limit*2)
                              # لأن بعض الروابط قد تفشل قراءتها فعليًا

    # (أولوية القراءة، الصلة، الاسم، الرابط) لكل مرشح فردي — الممثّل وكل
    # عضو من cluster_members معًا — قبل أي فرز، ليُرتَّب الجميع بمعيار واحد
    # لا بترتيب articles وحده (انظر التوثيق أعلاه). ناشرون غير إخباريين
    # (verify.excluded_publishers، تشخيص Issue #373 البند 4) يُستبعَدون
    # كليًا هنا — قبل أي وزن — لا يدخلون الفرز إطلاقًا مهما ارتفعت صلتهم
    # اللفظية.
    candidates: list[tuple[float, int, str, str]] = []
    for a in articles:
        rel = _relevance(a, wanted, token_fn) if wanted else 0
        name = a.publisher or a.source_name
        if not _is_excluded_publisher(name, cfg):
            candidates.append((_read_priority(name, cfg), rel, name, a.link))
        for m in a.cluster_members:
            mname = m.get("name")
            if not _is_excluded_publisher(mname, cfg):
                candidates.append((_read_priority(mname, cfg), rel, mname, m.get("link")))

    log.info("مرشحو القراءة قبل الترتيب (أولوية القراءة، صلة، اسم): %s",
             [(round(w, 2), r, n) for w, r, n, _ in candidates])
    candidates.sort(key=lambda c: -_candidate_score(c[0], c[1]))
    log.info("مرشحو القراءة بعد الترتيب بالدرجة المركّبة (أولوية القراءة، صلة، اسم): %s",
             [(round(w, 2), r, n) for w, r, n, _ in candidates])

    seen_links: set[str] = set()
    seen_publishers: set[str] = set()
    members: list[dict] = []

    def _add(name, link):
        if not name or not link or link in seen_links:
            return
        # التوحيد قبل اختيار مرشحي القراءة لا بعده (تشخيص Issue #373، الجولة
        # الرابعة، البند 1): بلا هذا، نسختا ناشر واحد بلغتين (مثال حقيقي:
        # "الجزيرة نت" و"Al Jazeera") تُعَدّان مرشحَين مستقلَّين فتستهلكان
        # فتحتي قراءة من الثلاث بدل واحدة — مرشح ثالث مختلف فعليًا يخسر
        # فتحته له رغم صلته أو وزنه.
        canonical = _canonical_publisher(name, cfg)
        if canonical in seen_publishers:
            return
        seen_links.add(link)
        seen_publishers.add(canonical)
        members.append({"name": name, "link": link})

    for _weight, _rel, name, link in candidates:
        # rank.pick_representative تُبقي روابط جوجل الوسيطة هنا (نمرر
        # keep_google_links=True في search()) لأن نتائج بحث التحقق كلها
        # من Google News أصلًا — فتُحلّ هنا بالضبط، لا تُضاف خامًا
        if link and "news.google.com" in link:
            link = resolve_final_url(link)
        _add(name, link)
        if len(members) >= max_members:
            break

    # اسم → رابط لكل مرشح جرى ضمّه فعليًا — يُستهلك أدناه لإرفاق رابط كل
    # مصدر بمقتطفه (verify_draft.py وarticle.py يحتاجان الرابط ليستشهدا
    # بالمصدر عند النشر، لا اسمه وحده)
    link_by_name = {m["name"]: m["link"] for m in members}

    fulltext, fetch_failures = extract.gather(members, limit=limit)
    if fulltext:
        log.info("نصوص مُقروءة فعلًا من نافذة القراءة: %s",
                 [d.get("name") for d in fulltext])
        docs = [{**d, "from_text": True, "link": link_by_name.get(d["name"], "")}
               for d in fulltext]
        return _evidence_docs(docs, fetch_failures), EVIDENCE_FULL_TEXT

    headline_docs = []
    seen_headline_publishers: set[str] = set()
    for a in articles:
        name = a.publisher or a.source_name
        if not name or _is_excluded_publisher(name, cfg):
            continue
        # نفس توحيد الناشر أعلاه (البند 1) — احتياط العناوين يستهلك limit
        # نفسها، فيخسر نفس مشكلة الفتحات المهدورة بلا هذا التوحيد
        canonical = _canonical_publisher(name, cfg)
        if canonical in seen_headline_publishers:
            continue
        snippet = f"{a.title}. {a.summary}".strip(" .")
        if snippet:
            headline_docs.append({"name": name, "text": snippet, "from_text": False,
                                  "link": a.link})
            seen_headline_publishers.add(canonical)
        if len(headline_docs) >= limit:
            break
    if headline_docs:
        log.info("لا نص كامل مقروء — احتياط العناوين مستعمل من: %s",
                 [d["name"] for d in headline_docs])
        return _evidence_docs(headline_docs, fetch_failures), EVIDENCE_HEADLINES_ONLY
    return _evidence_docs([], fetch_failures), EVIDENCE_UNREADABLE


# ──────────────────────────── مطابقة أسماء المصادر ────────────────────────────

_PAREN_RE = re.compile(r"[\(（][^\)）]*[\)）]?")


def _clean_raw(s: str) -> str:
    """نص خام مبسّط للمطابقة الاحتياطية في _tokens_match: بلا وصف بين
    قوسين ولا تشكيل ولا مسافات زائدة، بحالة أحرف موحَّدة."""
    s = _PAREN_RE.sub("", s or "")
    s = _TASHKEEL_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _tokens_match(a: str, b: str) -> bool:
    """يقارن اسمين بتسامح: يُسقط أي وصف بين قوسين، ويقارن كلماتهما عبر
    request.norm_tokens بتطابق جزئي — كلمات أحد الاسمين واردة كاملة داخل
    الآخر، لا تطابق حرفي صارم. يستعملها _canonical_name (مطابقة اسم أعاده
    النموذج بأحد docs) و_publisher_weight (مطابقة ناشر بقائمة
    sources/trusted_boost/publisher_aliases) معًا.

    norm_tokens تُسقط أي كلمة من حرفين فأقل — يُفرغ هذا مجموعة الاسم كاملة
    لمختصرات منقحرة كـ"بي بي سي" (BBC). حين تُفرِغ norm_tokens أحد الجانبين
    أو كليهما، نسقط لمطابقة نص خام مبسّط بتطابق جزئي (substring) بدل
    الرفض المباشر."""
    ta = norm_tokens(_PAREN_RE.sub("", a or ""))
    tb = norm_tokens(_PAREN_RE.sub("", b or ""))
    if ta and tb:
        return ta <= tb or tb <= ta
    ra, rb = _clean_raw(a), _clean_raw(b)
    return bool(ra) and bool(rb) and (ra in rb or rb in ra)


def _canonical_name(candidate, docs: list[dict]) -> str | None:
    """يطابق اسم مصدر أعاده النموذج مع أحد أسماء docs المعطاة فعليًا،
    بتسامح. يعيد اسم doc **الفعلي** (لا نص النموذج) ليبقى التقرير والعدّ
    نظيفين، أو None إن لم يطابق أي اسم معروف حتى بهذا التسامح."""
    if not isinstance(candidate, str):
        return None
    for d in docs:
        if _tokens_match(candidate, d["name"]):
            return d["name"]
    return None


DEFAULT_PUBLISHER_WEIGHT = 0.6
TRUSTED_PUBLISHER_WEIGHT = 3.0


def _trusted_canonical(name: str, cfg) -> str | None:
    """اسم trusted_boost المرجعي (إنجليزي) إن طابقه name بتسامح (مباشرة أو
    عبر verify.publisher_aliases)، وإلا None.

    مطابقة اسم trusted_boost وحده حرفيًا (إنجليزي عادة) لا تكفي: نتائج
    البحث العربية تعرض اسم الوكالة بالعربية غالبًا، ولا تحويل بين
    الأبجديتين في norm_tokens — فتُطابَق أيضًا كل مرادف عربي مُدرَج لكل
    وكالة في verify.publisher_aliases. مُستخرَجة من _publisher_weight
    (تشخيص Issue #373، الجولة الرابعة، البند 1) ليستعملها _canonical_publisher
    أيضًا بلا تكرار حلقة المطابقة نفسها."""
    if not name:
        return None
    vcfg = cfg.get("verify", {}) or {}
    aliases = vcfg.get("publisher_aliases") or {}
    for trusted in vcfg.get("trusted_boost") or []:
        names_to_try = [trusted, *(aliases.get(trusted) or [])]
        if any(_tokens_match(name, alt) for alt in names_to_try):
            return trusted
    return None


def _publisher_weight(name: str, cfg) -> float:
    """وزن الناشر: من verify.trusted_boost أولًا (وكالات كبرى)، ثم وزن
    sources في config.yaml، وإلا وزن افتراضي متواضع لناشر غير مُدرَج.
    يبقى تحت مفتاح verify: في config.yaml — مشترك بين verify.py وarticle.py
    وأي مسار آخر يعيد استعمال evidence.py، لا مكرَّر لكل مسار."""
    if not name:
        return DEFAULT_PUBLISHER_WEIGHT
    if _trusted_canonical(name, cfg) is not None:
        return TRUSTED_PUBLISHER_WEIGHT
    for s in cfg.get("sources", []) or []:
        sname = s.get("name", "")
        if sname and _tokens_match(name, sname):
            return float(s.get("weight", DEFAULT_PUBLISHER_WEIGHT))
    return DEFAULT_PUBLISHER_WEIGHT


def _canonical_publisher(name: str, cfg) -> str:
    """هوية الناشر الموحَّدة عبر اللغتين، لغرض العدّ/إزالة التكرار (لا
    الاستشهاد — الاسم الخام كما ورد يبقى ما يُعرَض) — تشخيص Issue #373،
    الجولة الرابعة، البند 1: «الجزيرة نت» (نتيجة بحث عربية) و«Al Jazeera»
    (نتيجة بحث إنجليزية) كانا يُعامَلان ناشرَين مستقلَّين رغم كونهما
    الناشر نفسه — فاستهلكا فتحتي قراءة من read_per_claim الثلاث بدل واحدة
    (مرشح ثالث فعليًا مختلف خسر فتحته)، والأخطر أن عدّ "مصادر مستقلة" في
    article.py (unique = set(supporting)) كان يحسبهما اثنين، ما يمكن أن
    ينقض شرط "مصدران مستقلان" الجوهري في المشروع كله لو أيّد الاثنان واقعة
    واحدة بلا مصدر ثالث حقيقي.

    تُطابِق trusted_boost/publisher_aliases بنفس منطق _publisher_weight (لا
    قائمة ثانية مُدارة يدويًا) فتُعيد الاسم الإنجليزي المرجعي بدل اسم
    النتيجة الخام حين يطابق أحدهما. بلا مطابقة، الاسم الخام نفسه هو الهوية
    — لا كل مصدر RSS في sources: يملك مرادفًا ثنائي اللغة مُدرَجًا، ولا حاجة
    لذلك خارج وكالات trusted_boost الكبرى التي تتكرر مشكلتها فعليًا (تظهر
    بالعربية والإنجليزية معًا في نتائج بحث مختلفة لنفس الاستعلام)."""
    return _trusted_canonical(name, cfg) or name


def _is_excluded_publisher(name: str, cfg) -> bool:
    """ناشرون غير إخباريين (رياضة/تسوق/ترفيه...) يُستبعدون كليًا كمرشّحي
    قراءة تحقّق — قبل أي وزن (تشخيص Issue #373، البند 4): مطابقة لفظية
    عابرة من موقع بلا سلطة تحقق صحفي (365Scores نجا فعليًا بهذه الطريقة في
    عيّنة حقيقية) ليست دليلًا مهما ارتفعت. المشكلة نوع المصدر لا موثوقيته
    أو صلته، فالاستبعاد لا يمرّ عبر _publisher_weight (الذي يُقيّم درجة
    الثقة لا نوعها) بل يمنع دخول candidates إطلاقًا."""
    if not name:
        return False
    vcfg = cfg.get("verify", {}) or {}
    return any(_tokens_match(name, excluded)
              for excluded in vcfg.get("excluded_publishers") or [])


def _is_demoted_reader(name: str, cfg) -> bool:
    """ناشرون يحجبون جلب نصهم الكامل بحجب شبه دائم (HTTP 403 متكرر عبر كل
    استعلام تقريبًا — تشخيص Issue #373، البند 3، لا عارض شبكي عابر). يبقون
    مصدر إشارة صالحًا للعنوان/الملخص والترتيب العام (_publisher_weight لا
    يتأثر، فلا يفقدون وزنهم كمصدر معروف/موثوق)، لكنهم يخسرون أولوية فتحات
    القراءة النادرة (read_per_claim) عبر _read_priority أدناه — محاولة جلب
    شبه مضمونة الفشل لا ينبغي أن تستهلك فتحة كان مرشح آخر سيملأها فعليًا."""
    if not name:
        return False
    vcfg = cfg.get("verify", {}) or {}
    return any(_tokens_match(name, demoted)
              for demoted in vcfg.get("demoted_readers") or [])


# يتجاوز أي فارق ممكن بين وزن الناشر (0.6-3.0) وصلة _relevance معًا — يضمن
# أن مرشحًا محجوبًا لا يسبق أي مرشح غير محجوب في ترتيب فتحات القراءة، بصرف
# النظر عن وزنه أو صلته اللفظية، بلا استبعاده كليًا (يبقى يُقرأ إن نفد كل
# مرشح آخر)
READ_DEMOTION_PENALTY = 10.0


def _read_priority(name: str, cfg) -> float:
    """أولوية ترتيب فتحات القراءة تحديدًا في gather_evidence — لا وزن
    الاستشهاد/الترتيب العام (_publisher_weight يبقى بلا تعديل لكل استهلاك
    آخر: تقارير verify.py، الوزن المعروض في التقرير...). ناشر محجوب
    (_is_demoted_reader) يُدفَع لآخر ترتيب القراءة، لا يُستبعد منه."""
    weight = _publisher_weight(name, cfg)
    if _is_demoted_reader(name, cfg):
        return weight - READ_DEMOTION_PENALTY
    return weight


def _known_only(names, docs: list[dict]) -> list[str]:
    """يستبعد أي اسم مصدر لا يطابق ما أُعطي فعليًا حتى بتسامح (انظر
    _canonical_name) — لا مصدر مختلَق يدخل التقرير. لا يفترض أن names
    قائمة أصلًا؛ رد النموذج قد يخالف مخطط الأداة."""
    if not isinstance(names, list):
        return []
    seen: list[str] = []
    for name in names:
        canonical = _canonical_name(name, docs)
        if canonical is None:
            log.warning("اسم مصدر مرفوض: %r لا يطابق أي مصدر معطى فعليًا "
                       "حتى بتسامح (المصادر المعطاة: %s)",
                       name, sorted(d["name"] for d in docs))
            continue
        if canonical not in seen:
            seen.append(canonical)
    return seen
