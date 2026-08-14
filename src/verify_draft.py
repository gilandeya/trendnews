"""صياغة مسودة خبر من الوقائع المؤكَّدة وحدها — المرحلة الثانية من مسار
التحقق (Issue #334)، تُستدعى من verify.py بعد بناء تقرير المرحلة الأولى.

معزولة عمدًا في وحدة مستقلة عن verify.py: الضمان البنيوي للقاعدة الملزمة
الأولى («المقال مصدر إلهام لا معلومة») هو أن دالّة الصياغة هنا لا تقبل نص
مقال في توقيعها أصلًا — لا مراجعة يدوية تضمن ذلك، بل الاستيراد نفسه. لو
عاشت هذه الدالة داخل verify.py حيث `body: str` (نص المقال) في نطاق كل
دالّة تقريبًا، أي تعديل مستقبِل سهل الخطأ بتمرير `body` إليها بالغلط.

تسلسل القرار في attempt():
  0) _write_access_reason() — هل يعلن هذا التشغيل صلاحية كتابة أصلًا؟
     (تعليق ما قبل الدمج على Issue #334، نقطة 1 — انظر تذييل الدالة)
  1) sufficiency() — هل يكفي المؤكَّد لخبر قائم بذاته؟ (القاعدة 7)
  2) _validate_sources() — لكل واقعة مؤكَّدة مصدر بنص ورابط صالحين فعلًا؟
  3) _draft_from_facts() — الصياغة، من الوقائع ومقتطفات مصادرها حصرًا
  4) check_originality() — فحص بعدي: لا نسخ حرفي من المقال ولا من المصادر
كل بند يمتنع برسالة سبب محددة — لا فشل صامت، ولا رجوع لمحتوى غير مؤكَّد.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
from datetime import datetime, timezone

from . import extract, imaging, review, store, writer
from . import verify
from .config import DRAFTS_DIR
from .imagesearch import find_images
from .request import _AR_TRANS
from .sources import Article

log = logging.getLogger("verify_draft")

DRAFT_ORIGIN = "verify"
WRITE_ENABLED_ENV = "VERIFY_DRAFT_WRITE_ENABLED"


# ──────────────────────── صلاحية الكتابة (دفاع في العمق) ────────────────────


def _write_access_reason() -> str:
    """يمنع إنفاق أي تكلفة نموذج أو بناء صورة قبل التأكد أن هذا التشغيل
    يستطيع فعليًا حفظ ما يُنتَج. لا اعتماد على افتراض أن
    `.github/workflows/verify.yml` يحمل تعديل contents:write + خطوات
    الرفع: العدد المذكور دُمج تاريخيًا من دونه فعلًا (GitHub App لا يملك
    صلاحية تعديل ملفات workflow — تعليق ما قبل الدمج على Issue #334، نقطة
    1)، وحينها ينفّذ verify.py القديم `src.verify` بلا أي خطوة رفع أو فتح
    Issue مراجعة: attempt() كانت ستصوغ محتوى مكلفًا (نداء نموذج + بحث/بناء
    صورة) ثم store.save_draft() يكتبه محليًا في نسخة العامل المؤقتة فقط —
    يُهمَل صامتًا حين ينتهي التشغيل، بينما يقرأ البشر في التقرير "✅ صيغت
    مسودة... ستظهر في أقرب Issue مراجعة" التي لن تُفتح أبدًا. فحص فاعل هنا
    يمنع هذا التناقض الصامت تحديدًا.

    التصريح مقصود لا فحص صلاحية حي عبر GitHub API: خطوة "تنفيذ التحقق" في
    verify.yml تُعلن `VERIFY_DRAFT_WRITE_ENABLED=true` صراحةً إلى جانب
    `permissions.contents: write` — إن غاب المتغيّر فالملف المطبَّق فعليًا
    ليس الملف المعتمد. لا يلغي هذا حاجة خطوة "رفع مسودة المؤكَّد" في
    الـ workflow لفحصها الخاص (git push يفشل بخطأ صريح إن كانت الصلاحية
    الفعلية غائبة رغم إعلان المتغيّر خطأً) — هذا دفاع أول أرخص وأبكر، لا
    بديل عنه."""
    if os.environ.get(WRITE_ENABLED_ENV) != "true":
        return (
            "صلاحية الكتابة غير معلَنة لهذا التشغيل "
            f"(متغيّر البيئة {WRITE_ENABLED_ENV} غائب أو ليس \"true\") — "
            "تأكد أن .github/workflows/verify.yml يحمل التعديل الذي يضبط "
            "permissions.contents: write ويُعلن هذا المتغيّر في خطوة "
            "«تنفيذ التحقق» (راجع تعليق ما قبل الدمج على Issue #334)؛ بلا "
            "هذا التعديل تُصاغ المسودة ثم تُهمَل صامتًا لأن لا خطوة تحفظها"
        )
    return ""


# ──────────────────────────── الكفاية (القاعدة 7) ────────────────────────────


def _central_fact(facts: list[dict]) -> dict:
    """الواقعة المحورية: أول ادّعاء **ليس** مُحدِّد إسناد/يقين منفصل
    (is_qualifier) — لا facts[0] الخام (البند 1، Issue #339). فصل مُحدِّدات
    الإسناد في extract_claims (رسميًا/تأكيدًا/بحسب بيان رسمي...) يغيّر
    ترتيب الاستخراج: مُحدِّد كـ"الانضمام معلَن رسميًا" قد يخرج قبل ادّعاء
    الحدث نفسه في claims، فاعتماد الموضع الخام وحده كان سيجعل مُحدِّدًا
    مفصولًا هو "الواقعة المحورية" خطأً — بالضبط العطل الذي طلب فصل
    المُحدِّدات حله أصلًا. تراجع لـ facts[0] فقط حين تكون كل الوقائع
    المستخرجة مُحدِّدات (حافة نادرة لا يُفترض وقوعها عمليًا) بدل الانهيار
    على قائمة غير فارغة."""
    for f in facts:
        if not f.get("is_qualifier"):
            return f
    return facts[0]


def sufficiency(facts: list[dict], cfg) -> tuple[bool, str]:
    """معيار الكفاية: دالّة نقية بلا نموذج (تعليق الموافقة على Issue #334،
    نقطة 2). الواقعة المحورية = أول ادّعاء ليس مُحدِّد إسناد مفصول عن حدثه
    (_central_fact، Issue #339 — لا facts[0] الخام كما كان، فذلك أعاد
    مُحدِّدًا مفصولًا مثل "الواقعة المحورية" خطأً حين يخرج قبل ادّعاء
    الحدث نفسه). شرط منفصل عن العدّ: عدد كافٍ من التفاصيل الهامشية
    المؤكَّدة لا يعوّض واقعة محورية غير مؤكَّدة."""
    vd_cfg = cfg.get("verify_draft", {}) or {}
    min_confirmed_facts = int(vd_cfg.get("min_confirmed_facts", 2))

    if not facts:
        return False, "لا وقائع مستخرجة من المقال"

    central = _central_fact(facts)
    if central["status"] != verify.STATUS_CONFIRMED:
        return False, (f"الواقعة المحورية (index {central.get('index', 0)}) "
                       f"«{central['text']}» غير مؤكَّدة (حكمها: {central['status']})")

    confirmed = [f for f in facts if f["status"] == verify.STATUS_CONFIRMED]
    if len(confirmed) < min_confirmed_facts:
        return False, (f"عدد الوقائع المؤكَّدة ({len(confirmed)}) دون الحد الأدنى "
                       f"({min_confirmed_facts}) رغم أن الواقعة المحورية مؤكَّدة")

    return True, (f"{len(confirmed)} واقعة مؤكَّدة، منها الواقعة المحورية "
                  f"«{central['text']}»")


def _validate_sources(confirmed: list[dict]) -> str:
    """يمنع صياغة مسودة من واقعة مؤكَّدة بلا مصدر بنص ورابط صالحين فعليًا —
    القسم «لا فشل صامت»: رسالة الامتناع تذكر المرحلة ومعرّف الواقعة ورابط
    كل مصدر مسجَّل لها والسبب، لا «فشل التحقق» رسالة عامة. يعيد نص السبب،
    أو فارغًا إن كانت كل واقعة مؤكَّدة تملك مصدرًا صالحًا واحدًا على الأقل."""
    for f in confirmed:
        usable = [s for s in f.get("sources", []) if s.get("text") and s.get("link")]
        if usable:
            continue
        bad = f.get("sources") or []
        bad_desc = "، ".join(
            f"{s.get('name', '؟')} ({s.get('link') or 'بلا رابط'})" for s in bad
        ) or "لا مصادر مسجَّلة إطلاقًا"
        return (f"مرحلة صياغة المسودة — الواقعة (index {f.get('index', '؟')}) "
               f"«{f['text']}»: لا مصدر مؤيِّد بنص ورابط صالحين للاستشهاد "
               f"({bad_desc})")
    return ""


# ──────────────────────────── فحص التطابق البعدي (القاعدة 1) ────────────────

QUOTE_RE = re.compile(r'[«"“]([^»"”]{4,})[»"”]')
_WORD_RE = re.compile(r"[\w']+", re.UNICODE)


def _normalized_words(text: str) -> list[str]:
    """تتابع كلمات مطبَّع يحفظ الترتيب — الترتيب جوهر فحص النسخ هنا، فلا
    نحوّله لمجموعة كما تفعل request.norm_tokens، ولا نحذف كلمات الوقف (حذفها
    يكسر التجاور فيُفرغ مفهوم «التتابع» من معناه). التطبيع (تشكيل/تطويل +
    توحيد الهمزات والتاء المربوطة) نفسه المستعمل في verify.py وrequest.py —
    الدلالة نفسها يجب أن تُطابَق بصرف النظر عن مصدرها."""
    text = verify._TASHKEEL_RE.sub("", text or "")
    return [w.translate(_AR_TRANS) for w in _WORD_RE.findall(text.lower())]


def _contains_run(haystack: list[str], needle: list[str]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    n = len(needle)
    return any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


def _shared_run(candidate_words: list[str], reference_words: list[str],
                n: int) -> tuple[str, ...] | None:
    if n <= 0 or len(candidate_words) < n or len(reference_words) < n:
        return None
    ref_ngrams = {tuple(reference_words[i:i + n])
                 for i in range(len(reference_words) - n + 1)}
    for i in range(len(candidate_words) - n + 1):
        window = tuple(candidate_words[i:i + n])
        if window in ref_ngrams:
            return window
    return None


def _quoted_spans(text: str) -> list[str]:
    return [m.group(1).strip() for m in QUOTE_RE.finditer(text or "")]


def check_originality(draft_text: str, article_body: str, source_texts: list[str],
                      max_shared_run_words: int) -> tuple[bool, str]:
    """يتحقق أن نص المسودة لا يحمل نسخًا حرفيًا من المقال الملصق ولا من
    مقتطفات المصادر المؤكِّدة (تعليق الموافقة على Issue #334، نقطة 3):
    القاعدة 1 تمنع نقل جملة من المقال، والمقتطفات تدخل البرومبت هنا كنصوص
    كاملة (خطر نسخ أعلى من ملخصات RSS القصيرة التي يتلقاها writer.py عادة)
    فالنسخ من مصدر مؤكِّد يُفحص بالصرامة نفسها.

    اقتباس بين علامتي تنصيص يُستثنى من الفحص بشرط وجوده حرفيًا (بعد
    التطبيع) في أحد مقتطفات المصادر المؤكِّدة — اقتباس منسوب مشروع. اقتباس
    غير موجود في أي مقتطف يُرفض مباشرة بوصفه نسخًا من المقال الملصق، بلا
    حاجة لفحص التتابع عليه. الرفض هنا نهائي بلا إعادة محاولة: مدخلات
    الصياغة (الوقائع والمقتطفات) لا تتغيّر بين محاولتين، فتكرار التطابق
    مرجَّح لا مستبعَد."""
    quotes = _quoted_spans(draft_text)
    normalized_sources = [_normalized_words(s) for s in source_texts]
    cleaned = draft_text
    for q in quotes:
        q_words = _normalized_words(q)
        if not q_words or not any(_contains_run(src_words, q_words)
                                  for src_words in normalized_sources):
            return False, (f"اقتباس بين علامتي تنصيص غير موجود حرفيًا في أي "
                           f"مقتطف مصدر مؤكِّد — يُفترض نسخه من المقال الملصق: "
                           f"«{q[:80]}»")
        cleaned = cleaned.replace(q, " ")

    candidate_words = _normalized_words(cleaned)
    checks = [("المقال الملصق", article_body)]
    checks += [(f"مقتطف مصدر مؤكِّد ({i + 1})", s) for i, s in enumerate(source_texts)]
    for label, reference in checks:
        shared = _shared_run(candidate_words, _normalized_words(reference),
                             max_shared_run_words)
        if shared:
            return False, (f"تطابق لفظي مع {label}: {max_shared_run_words} كلمة "
                           f"متتالية مشتركة — «{' '.join(shared)}»")
    return True, ""


# ──────────────────────────── الصياغة من الوقائع ────────────────────────────

# لا نستدعي writer.write_arabic هنا رغم استيراد writer.py كاملة: توقيعها
# يتمحور حول Article (عنوان/رابط/ناشر المقال المصدر يدخل برومبتها مباشرة)
# — وهذا بالضبط ما تمنعه القاعدة الملزمة الأولى بنيويًا هنا. الفرق إذن في
# *بناء البرومبت* لا في آلية نداء الشبكة نفسها؛ نداء الشبكة (الطلب، إعادة
# المحاولة، تصنيف العطل، استخراج JSON) مستخرج فعليًا إلى writer._call_model
# ويُستعمل من المسارين معًا (لا نسختين تتباعدان — تعليق ما قبل الدمج على
# Issue #334، نقطة 2)، وتنظيف الحقول النهائية إلى writer._post_from_data
# للسبب نفسه. النظام المستعمل writer.SYSTEM_PROMPT كما هو (القاعدة 5) —
# لا نسخة معدّلة ولا غلاف يعيد صياغة قواعد التحرير.
DRAFT_USER_TEMPLATE = """وقائع مؤكَّدة بمصدرين مستقلين فأكثر — لا مصدر واحد ولا
أي حالة أضعف. ابنِ منها منشورًا مستقلًا بلا أي رجوع لمصدر آخر غير المذكور
أدناه:

{facts_block}

نصوص المصادر المستقلة التي أيّدت هذه الوقائع تحديدًا:

{source_texts}
املأ حقول أداة publish_post من هذه الوقائع والنصوص وحدها — لا معرفة سابقة
ولا مصدر ثالث. القواعد التحريرية كما هي دومًا:

• image_headline — عنوان مكثّف يُكتب على الصورة، بحد أقصى {max_chars} حرفًا، بلا نقطة
• post_title — عنوان المنشور: جملة واحدة جاذبة ودقيقة
• post_body — متن المنشور، {post_length}
• hashtags — {hashtags_count} هاشتاقات عربية، بلا رمز # وبـ _ بدل المسافة
• category — التصنيف الأنسب
• analysis — فقرة «خلف الخبر»: نص واحد متصل بحد أقصى {analysis_max_words} كلمة
  إن حملت نصوص المصادر تحليلًا فعليًا يتجاوز الوقائع أعلاه، وإلا اتركه فارغًا.

نبرة الكتابة المطلوبة: {tone}"""


def _source_docs(confirmed: list[dict]) -> list[dict]:
    """مقتطفات المصادر المؤيِّدة للوقائع المؤكَّدة، بلا تكرار اسم واحد — هذا
    ما يصل البرومبت، لا نص المقال الملصق ولا ملخصات RSS القصيرة."""
    seen: set[str] = set()
    out = []
    for f in confirmed:
        for s in f.get("sources", []):
            if s["name"] in seen or not s.get("text"):
                continue
            seen.add(s["name"])
            out.append({"name": s["name"], "text": s["text"]})
    return out


def _draft_from_facts(confirmed: list[dict], cfg,
                      retries: int = 3) -> tuple[dict | None, str]:
    """يستدعي النموذج للصياغة من الوقائع المؤكَّدة ومقتطفات مصادرها حصرًا.
    الضمان البنيوي للقاعدة 1: توقيعها لا يقبل نص مقال أو عنوانه أو زاويته
    في أي معامل — لا مدخل هنا غير `confirmed` (نصوص وقائع + مقتطفات مصادر
    مؤكِّدة فقط) و`cfg`."""
    w = cfg.get("writer", {})
    docs = _source_docs(confirmed)
    facts_block = "\n".join(f"- {f['text']}" for f in confirmed)
    max_words = int(w.get("analysis_max_words", 120))
    prompt = DRAFT_USER_TEMPLATE.format(
        facts_block=facts_block,
        source_texts=extract.format_for_prompt(docs),
        max_chars=cfg.path("image.headline_max_chars", 95),
        post_length=w.get("post_length", "60 إلى 90 كلمة"),
        hashtags_count=w.get("hashtags_count", 4),
        analysis_max_words=max_words,
        tone=w.get("tone", "خبري رصين، عربي فصيح مبسّط، بلا مبالغة أو إثارة"),
    )

    try:
        data = writer._call_model(prompt, cfg, retries)
    except writer.WriteFailure as exc:
        log.warning("فشل تقني في صياغة مسودة التحقق (%s): %s", exc.reason, exc.detail)
        return None, f"مرحلة صياغة المسودة — فشل تقني ({exc.reason}): {exc.detail}"

    if not data.get("newsworthy", True):
        # امتناع مشروع لا التفاف عليه ولا إعادة صياغة (تعليق الموافقة على
        # Issue #334): السبب يُنقل حرفيًا كما أعاده النموذج، لا يُعمَّم
        reject_reason = str(data.get("reject_reason") or "").strip() or "بلا سبب محدد من النموذج"
        return None, f"مرحلة صياغة المسودة — رفض تحريري (newsworthy=false): {reject_reason}"

    written = writer._post_from_data(data, max_words, len(docs) >= 2)
    return written, ""


# ──────────────────────────── بناء المسودة والصورة ──────────────────────────


def _image_candidates(confirmed: list[dict]) -> list[tuple[str, str, str]]:
    """(رابط الصورة، اسم المصدر، رابط المصدر) لكل صورة مرشحة من مصادر
    مؤيِّدة مؤكَّدة فقط — لا صورة المقال الملصق (لا رابط له أصلًا: verify.py
    يستقبل نصًا خامًا بلا رابط مقال) ولا أي مصدر غير مؤكَّد."""
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for f in confirmed:
        for s in f.get("sources", []):
            for url in s.get("image_candidates") or []:
                if url in seen:
                    continue
                seen.add(url)
                out.append((url, s["name"], s.get("link", "")))
    return out


def _synthetic_article(confirmed: list[dict], primary_link: str,
                       publishers: list[str]) -> Article:
    """لا نص مقال ولا عنوانه الفعلي في أي حقل هنا (القاعدة 2): العنوان نص
    الواقعة المحورية المؤكَّدة، وهو أصلًا إعادة صياغة عن المصادر لا نقل
    حرفي عن المقال (EXTRACT_SYSTEM يمنع ذلك). الرابط رابط مصدر مؤكِّد لا
    رابط المقال الملصق — لا رابط له أصلًا."""
    central = confirmed[0]
    return Article(
        title=central["text"],
        link=primary_link,
        summary="؛ ".join(f["text"] for f in confirmed[1:]),
        source_name=publishers[0] if publishers else "",
        region="global",
        weight=1.0,
        published=datetime.now(timezone.utc),
        publisher=publishers[0] if publishers else "",
        cluster_sources=publishers,
    )


def attempt(result: dict, article_body: str, issue_number: int, cfg) -> dict:
    """يحاول بناء مسودة من المؤكَّد وحده بعد تقرير المرحلة الأولى. يعيد
    قاموس outcome بحقل `produced` ورسالة `reason` محددة دومًا (نجاحًا أو
    امتناعًا) — لا فشل صامت، ولا رجوع لمحتوى غير مؤكَّد كخطة بديلة."""
    facts = result.get("facts") or []
    central = _central_fact(facts) if facts else None
    outcome: dict = {
        "produced": False, "reason": "",
        "central_text": central["text"] if central else "",
        "central_index": central.get("index", 0) if central else 0,
        "confirmed_count": 0, "draft_id": None,
        "image_source_name": None, "image_source_link": None,
    }

    write_access_error = _write_access_reason()
    if write_access_error:
        outcome["reason"] = write_access_error
        return outcome

    ok, reason = sufficiency(facts, cfg)
    if not ok:
        outcome["reason"] = reason
        return outcome

    confirmed = [f for f in facts if f["status"] == verify.STATUS_CONFIRMED]
    # الواقعة المحورية (الحدث نفسه لا مُحدِّد إسناد مفصول عنه) يجب أن تتصدر
    # confirmed: _synthetic_article وimage/central_fact_text أدناه يعتمدان
    # confirmed[0] كعنوان/استعلام صورة الحدث — موضعها الخام في facts قد لا
    # يكون صفرًا بعد فصل المُحدِّدات (Issue #339)، فبلا هذا الترتيب يعود
    # نفس العطل من زاوية أخرى: عنوان المسودة يصير نص مُحدِّد لا نص الحدث
    if central is not None and any(f is central for f in confirmed):
        confirmed = [central] + [f for f in confirmed if f is not central]
    outcome["confirmed_count"] = len(confirmed)

    source_error = _validate_sources(confirmed)
    if source_error:
        outcome["reason"] = source_error
        return outcome

    vd_cfg = cfg.get("verify_draft", {}) or {}
    max_shared_run_words = int(vd_cfg.get("max_shared_run_words", 7))

    written, write_reason = _draft_from_facts(confirmed, cfg)
    if written is None:
        outcome["reason"] = write_reason
        return outcome

    source_texts = [s["text"] for f in confirmed for s in f.get("sources", [])
                    if s.get("text")]
    draft_text = "\n".join(filter(None, [
        written["image_headline"], written["post_title"],
        written["post_body"], written.get("analysis", ""),
    ]))
    ok_orig, orig_reason = check_originality(
        draft_text, article_body, source_texts, max_shared_run_words)
    if not ok_orig:
        outcome["reason"] = f"مرحلة صياغة المسودة — امتناع: {orig_reason}"
        return outcome

    publishers: list[str] = []
    for f in confirmed:
        for s in f.get("sources", []):
            if s["name"] not in publishers:
                publishers.append(s["name"])
    primary_link = next(
        (s.get("link") for f in confirmed for s in f.get("sources", [])
         if s.get("link")), "")

    art = _synthetic_article(confirmed, primary_link, publishers)
    draft_id = hashlib.sha1(
        f"verify:{issue_number}:{confirmed[0]['text']}".encode("utf-8")
    ).hexdigest()[:12]

    image_ranked = _image_candidates(confirmed)
    image_urls = [u for u, _, _ in image_ranked]
    central_fact_text = confirmed[0]["text"]

    image_name = f"{datetime.now(timezone.utc):%Y-%m-%d}/{draft_id}.jpg"
    image_rel = f"drafts/{image_name}"
    shot: dict = {}
    try:
        imaging.build_post_image(
            headline=written["image_headline"] or written["post_title"],
            category=written["category"],
            urgent=written["urgent"],
            image_urls=image_urls,
            publisher=publishers,
            bucket="serious",
            # كسول: لا يُستدعى إلا إن فشلت كل صور المصادر المؤكِّدة فعليًا —
            # موضوع البحث الوقائع المؤكَّدة لا زاوية المقال أو عنوانه
            fallback_provider=lambda: find_images(central_fact_text, cfg),
            cfg=cfg,
            out_path=DRAFTS_DIR / image_name,
            report=shot,
        )
    except Exception as exc:  # noqa: BLE001 — امتناع صريح مُسجَّل لا انهيار صامت
        outcome["reason"] = f"مرحلة بناء صورة المسودة — فشل: {exc}"
        return outcome

    draft = {
        "id": draft_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "review_issue": None,
        "origin": DRAFT_ORIGIN,
        "verify_issue": issue_number,
        "score": 0.0,
        "bucket": "serious",
        "analysed_sources": [d["name"] for d in _source_docs(confirmed)],
        "trend_score": 0.0,
        "velocity": 0.0,
        "age_hours": 0.0,
        "is_followup": False,
        "state_media": False,
        "has_photo": bool(shot.get("used_original")),
        "source": {
            "title": central_fact_text,
            "link": primary_link,
            "publisher": publishers[0] if publishers else "",
            "publishers": publishers,
            "region": "global",
            "image_url": image_urls[0] if image_urls else None,
            "image_candidates": image_urls,
        },
        "arabic": written,
        "caption": writer.build_caption(written, art, cfg),
        "image": image_rel,
        "reel": None,
        "reel_spec": {
            "headline": written["image_headline"] or written["post_title"],
            "category": written["category"],
            "urgent": written["urgent"],
            "image_candidates": image_urls,
        },
    }
    store.save_draft(draft)

    if shot.get("used_original") and image_ranked:
        outcome["image_source_name"] = image_ranked[0][1]
        outcome["image_source_link"] = image_ranked[0][2]

    outcome.update({
        "produced": True,
        "reason": f"صيغت مسودة من {len(confirmed)} واقعة مؤكَّدة",
        "draft_id": draft_id,
    })
    return outcome


def build_report_section(outcome: dict) -> str:
    lines = ["#### 📝 مسودة من المؤكَّد", ""]
    if outcome["produced"]:
        lines.append(f"✅ {outcome['reason']} (المعرّف `{outcome['draft_id']}`) — "
                     "ستظهر في أقرب Issue مراجعة يفتحه البوت بعد رفع المسودة.")
        if outcome.get("image_source_link"):
            name = outcome.get("image_source_name") or "مصدر مؤكِّد"
            lines.append(f"🖼️ مصدر الصورة: [{name}]({outcome['image_source_link']})")
    else:
        lines.append(f"❌ لم تُصَغ مسودة — {outcome['reason']}")
    if outcome.get("central_text"):
        lines += ["", f"<sub>الواقعة المحورية (index {outcome['central_index']}): "
                      f"«{outcome['central_text']}»</sub>"]
    return "\n".join(lines)


# ──────────────────────────── ربط المسودة بتعليق Issue التحقق ───────────────


def main() -> int:
    """يربط مسودة أُنتجت أثناء التحقق بـ Issue مراجعتها بعد فتحه. خطوة
    منفصلة عن `python -m src.verify` لأن فتح Issue المراجعة يجب أن يقع بعد
    رفع الصور إلى المستودع (القيد الموثَّق في CLAUDE.md)، وهذا يقع في خطوة
    لاحقة من verify.yml بعد أن تنتهي src.verify من عملها.

        python -m src.verify_draft --link --issue 132 --draft-id abcdef123456
    """
    parser = argparse.ArgumentParser(description="ربط مسودة تحقق بـ Issue مراجعتها")
    parser.add_argument("--link", action="store_true", required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--draft-id", required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")

    loaded = store.load_draft(args.draft_id)
    if not loaded:
        log.error("تعذّر العثور على مسودة %s بعد الرفع — لا رابط سيُضاف "
                 "لتعليق Issue #%d", args.draft_id, args.issue)
        review.comment(args.issue,
                       f"⚠️ تعذّر العثور على مسودة `{args.draft_id}` بعد رفعها "
                       "للمستودع — راجع سجلات Actions.")
        return 1

    _, draft = loaded
    review_issue = draft.get("review_issue")
    if not review_issue:
        log.error("مسودة %s محفوظة بلا review_issue بعد open_review.main()",
                 args.draft_id)
        return 1

    review.comment(args.issue, f"➡️ راجع المسودة في Issue #{review_issue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
