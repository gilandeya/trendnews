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
    تعليق لاحق). _normalize_query_word تُستدعى على كل كلمة منفردة فقط
    لتحديد هل تنجو من تصفية كلمات الوقف، لا لتحويل الكلمة نفسها — وبلا
    شرط طول (خلافًا لـnorm_tokens) كي لا يسقط تاريخ يوم من رقمين أو شهر
    عربي من حرفين (تشخيص Issue #364).

    الأرقام (سنوات، كميات، أيام) أولًا لأنها أدق ما يميّز الادّعاء، ثم أطول
    الكلمات المتبقية بعد استبعاد كلمات الحشو أعلاه — الطول تقريب رخيص
    لعلمية الكلمة (اسم علم أو مكان) بلا استدعاء نموذج إضافي لاستخراج
    كيانات."""
    clean = _TASHKEEL_RE.sub("", text or "")
    seen: set[str] = set()
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


def search(query: str, cfg, days: int, unrestricted: bool = False) -> list[Article]:
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
    من رفض مصدر قديم بعد جلبه فعليًا."""
    vcfg = cfg.get("verify", {}) or {}
    locales = vcfg.get("locales") or DEFAULT_LOCALES
    max_age_hours = REFERENCE_MAX_AGE_HOURS if unrestricted else days * 24

    articles: list[Article] = []
    for feed in search_feeds(query, None if unrestricted else days, locales):
        articles += fetch_source(feed, max_age_hours=max_age_hours)
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
    # keep_google_links=True: نتائج هذا البحث كلها من Google News (بلا
    # استثناء)، فاستبعاد rank.pick_representative الافتراضي لروابط جوجل من
    # cluster_members كان يُفرغها هنا شبه دائمًا قبل أن تصل gather_evidence
    return rank(matched, selection, merge_cfg=None,
               token_fn=norm_tokens if bilingual else None,
               keep_google_links=True)


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


def _candidate_score(weight: float, relevance: int) -> float:
    """درجة مركّبة تجمع وزن الناشر وصلة النص لترتيب مرشّحي القراءة في
    gather_evidence، بدل الفرز التتابعي (-وزن ثم -صلة) الذي أضرّ بالنتيجة
    فعليًا (Issue #132 تعليق لاحق): حين يملأ عدد كافٍ من المرشحين الموثوقين
    بلا أي صلة نافذة قراءة ضيقة، كان الفرز التتابعي يُقصي كليًا مرشّحًا شديد
    الصلة بوزن أقل — بصرف النظر عن مدى ارتفاع صلته. الجمع البسيط يجعل
    الصلة العالية قادرة على تعويض فارق الوزن الأقصى بدل أن يُقصيها كليًا،
    والوزن العالي يبقى قادرًا على تعويض صلة أضعف عند تقاربها."""
    return weight + relevance


def gather_evidence(articles: list[Article], cfg, claim_text: str = "") -> tuple[list[dict], str]:
    """يقرأ نصوص أعلى النتائج، متبِّعًا روابط Google News الوسيطة أولًا
    (عبر sources.resolve_final_url).

    كل عنصر في articles ممثّل مجموعة (دمج عناوين متشابهة لفظيًا عبر
    rank.cluster) — والناشرون المستقلون الآخرون الذين اندمجوا فيه محفوظون
    في cluster_members لا في الممثّل وحده. نوسّع كل ممثّل إلى كل ناشريه
    الفعليين هنا، فيُعَدّ كل ناشر مستقل مصدرًا مستقلًا لا الموضوع/المجموعة
    ككل.

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

    wanted = norm_tokens(claim_text) if claim_text else set()

    vcfg = cfg.get("verify", {}) or {}
    limit = int(vcfg.get("read_per_claim", 3))
    max_members = limit * 4  # هامش فوق سقف extract.gather الداخلي (limit*2)
                              # لأن بعض الروابط قد تفشل قراءتها فعليًا

    # (وزن الناشر، الصلة، الاسم، الرابط) لكل مرشح فردي — الممثّل وكل عضو من
    # cluster_members معًا — قبل أي فرز، ليُرتَّب الجميع بمعيار واحد لا
    # بترتيب articles وحده (انظر التوثيق أعلاه)
    candidates: list[tuple[float, int, str, str]] = []
    for a in articles:
        rel = _relevance(a, wanted) if wanted else 0
        name = a.publisher or a.source_name
        candidates.append((_publisher_weight(name, cfg), rel, name, a.link))
        for m in a.cluster_members:
            mname = m.get("name")
            candidates.append((_publisher_weight(mname, cfg), rel, mname, m.get("link")))

    log.info("مرشحو القراءة قبل الترتيب (وزن، صلة، اسم): %s",
             [(round(w, 2), r, n) for w, r, n, _ in candidates])
    candidates.sort(key=lambda c: -_candidate_score(c[0], c[1]))
    log.info("مرشحو القراءة بعد الترتيب بالدرجة المركّبة (وزن، صلة، اسم): %s",
             [(round(w, 2), r, n) for w, r, n, _ in candidates])

    seen_links: set[str] = set()
    seen_names: set[str] = set()
    members: list[dict] = []

    def _add(name, link):
        if not name or not link or link in seen_links or name in seen_names:
            return
        seen_links.add(link)
        seen_names.add(name)
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

    fulltext = extract.gather(members, limit=limit)
    if fulltext:
        log.info("نصوص مُقروءة فعلًا من نافذة القراءة: %s",
                 [d.get("name") for d in fulltext])
        return [{**d, "from_text": True, "link": link_by_name.get(d["name"], "")}
               for d in fulltext], EVIDENCE_FULL_TEXT

    headline_docs = []
    seen_headline_names: set[str] = set()
    for a in articles:
        name = a.publisher or a.source_name
        if not name or name in seen_headline_names:
            continue
        snippet = f"{a.title}. {a.summary}".strip(" .")
        if snippet:
            headline_docs.append({"name": name, "text": snippet, "from_text": False,
                                  "link": a.link})
            seen_headline_names.add(name)
        if len(headline_docs) >= limit:
            break
    if headline_docs:
        log.info("لا نص كامل مقروء — احتياط العناوين مستعمل من: %s",
                 [d["name"] for d in headline_docs])
        return headline_docs, EVIDENCE_HEADLINES_ONLY
    return [], EVIDENCE_UNREADABLE


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


def _publisher_weight(name: str, cfg) -> float:
    """وزن الناشر: من verify.trusted_boost أولًا (وكالات كبرى)، ثم وزن
    sources في config.yaml، وإلا وزن افتراضي متواضع لناشر غير مُدرَج.
    يبقى تحت مفتاح verify: في config.yaml — مشترك بين verify.py وarticle.py
    وأي مسار آخر يعيد استعمال evidence.py، لا مكرَّر لكل مسار.

    مطابقة اسم trusted_boost وحده حرفيًا (إنجليزي عادة) لا تكفي: نتائج
    البحث العربية تعرض اسم الوكالة بالعربية غالبًا، ولا تحويل بين
    الأبجديتين في norm_tokens — فتُطابَق أيضًا كل مرادف عربي مُدرَج لكل
    وكالة في verify.publisher_aliases."""
    if not name:
        return DEFAULT_PUBLISHER_WEIGHT
    vcfg = cfg.get("verify", {}) or {}
    aliases = vcfg.get("publisher_aliases") or {}
    for trusted in vcfg.get("trusted_boost") or []:
        names_to_try = [trusted, *(aliases.get(trusted) or [])]
        if any(_tokens_match(name, alt) for alt in names_to_try):
            return TRUSTED_PUBLISHER_WEIGHT
    for s in cfg.get("sources", []) or []:
        sname = s.get("name", "")
        if sname and _tokens_match(name, sname):
            return float(s.get("weight", DEFAULT_PUBLISHER_WEIGHT))
    return DEFAULT_PUBLISHER_WEIGHT


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
