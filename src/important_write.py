"""مسار «هام» — المهمة 3 من 3 (Issue #1221): الكتابة بحسب الحكم.

نقطة حُكم عليها (state/important/N.json) ← مسودة `origin: "important"` بآلة مسار «مقال»
نفسها: article._draft_article (برومبتها وقواعدها ونموذجها article.model) بلا أي تعديل عليها.
مصادر الكاتب أدلة النقطة وحدها (evidence وcorrection.sources وrefuted_by وnearest.sources)،
والتعليمات الخاصة بكل حكم (config.yaml: important.writer_instructions) تُلحَق ببرومبته.

ما يمسّ ما يُنشر يُفحص **في الكود بعد الكتابة** (check_text) لا في الموجّه وحده — الموجّه
توجيه والفحص ضمان: عنوان تفنيد يكرّر الشائعة، مقال أقرب حدث يذكر النقطة الأصلية، تصحيح لا
يقول الصيغة الصحيحة بنصّها، تفنيد لا يسمّي المدقّق. الرفض يعيد الكتابة مرة واحدة بذكر العلّة
(important.write_attempts) ثم يُرفض كتابةً فاشلة بسببها.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone

from . import article, headlines as headlines_mod, important, names_audit, store, verify_draft, writer
from .request import norm_tokens
from .sources import Article

log = logging.getLogger("trendnews.important_write")

DRAFT_ORIGIN = "important"

# أسباب الرفض — نصوصها تُعرض للمراجع في تعليق القضية فتبقى ثابتة
REASON_RUMOR_TITLE = "عنوان التفنيد يكرّر الادّعاء"
REASON_RUMOR_FIRST = "أول جملة في التفنيد تكرّر الادّعاء"
REASON_NO_CHECKER = "المقال لا يسمّي المدقّق"
REASON_NO_LABEL = "المقال لا يذكر حكم المدقّق"
REASON_ORIGINAL = "المقال يذكر النقطة الأصلية"
REASON_NO_CORRECT = "الصيغة الصحيحة غائبة عن العنوان أو أول جملة"
REASON_ORIGINALITY = "نسخ لفظي من مقتطفات المصادر"
REASON_QUESTION_TITLE = "العنوان سؤال لا جملة خبرية (تصحيح/تفنيد)"
REASON_EDITOR_TAG = "المقال ينسب إلى «موجز المحرر» أو رأيه ولا موجز في «هام»"
NO_FACTS_REASON = "لا وقائع مسندة من أدلة النقطة — لا كتابة من نص المستخدم في «هام»"
TECHNICAL_PREFIX = "مرحلة الصياغة — فشل تقني"


def _icfg(cfg) -> dict:
    return cfg.get("important", {}) or {}


def _norm(text: str) -> str:
    """نص مطبَّع للمطابقة وحدها (important._fold: تشكيل، همزات، ياء/ألف مقصورة) مفصول بمسافات
    بلا ترقيم — مطابقة الجملة الحرفية لا تتعثر بعلامة أو حركة."""
    return " ".join(important._WORD_RE.findall(important._fold(text)))


def _contains(haystack: str, needle: str) -> bool:
    n = _norm(needle)
    return bool(n) and f" {n} " in f" {_norm(haystack)} "


def _has_phrase(text: str, phrase: str) -> bool:
    """عبارة ثابتة في النص مع تسامح بحرف عطف ملتصق بأول كلمة («وبحسب معلومات المحرر»)؛ _contains
    وحدها تفوّت هذا الشكل لأن المطابقة بحدود الكلمات."""
    want = _norm(phrase).split()
    words = _norm(text).split()
    for i in range(len(words) - len(want) + 1):
        head = words[i]
        if (head == want[0] or (head[:1] in ("و", "ف") and head[1:] == want[0])) \
                and words[i + 1:i + len(want)] == want[1:]:
            return True
    return False


def first_sentence(body: str) -> str:
    parts = re.split(r"(?<=[.!؟?۔])\s+|\n+", (body or "").strip(), maxsplit=1)
    return parts[0] if parts else ""


# ───────────────────────────── مصادر الكاتب ─────────────────────────────


def ordered_sources(point: dict, cfg) -> list[dict]:
    """أدلة النقطة وحدها بترتيب العرض: [{publisher, link, excerpt, fact_checker}]. في false
    يأتي المدقّق أولًا (سطر المصدر على البطاقة يبدأ به)، وفي confirmed الجهة الأصلية أولًا."""
    icfg = _icfg(cfg)
    verdict = point.get("verdict")
    rows: list[dict] = []
    if verdict == "confirmed":
        ev = [e for e in point.get("evidence") or [] if e.get("stance") == "supports"]
        if not ev:   # ملفات قديمة: التأييد بتصحيح داخل الهامش بقي conflicts_detail
            ev = [e for e in point.get("evidence") or [] if e.get("stance") != "refutes"]
        ev.sort(key=lambda e: not important._is_primary_source(e.get("link", ""), icfg))
        rows = [{"publisher": e.get("publisher", ""), "link": e.get("link", ""),
                 "excerpt": e.get("excerpt", "")} for e in ev]
    elif verdict == "inaccurate":
        rows = [{"publisher": s.get("publisher", ""), "link": s.get("link", ""),
                 "excerpt": s.get("excerpt", "")}
                for s in (point.get("correction") or {}).get("sources") or []]
    elif verdict == "false":
        refs = sorted(point.get("refuted_by") or [], key=lambda r: not r.get("fact_checker"))
        rows = [{"publisher": r.get("publisher", ""), "link": r.get("link", ""),
                 "excerpt": r.get("excerpt", ""), "fact_checker": bool(r.get("fact_checker")),
                 "verdict_label": r.get("verdict_label", "")} for r in refs]
    elif verdict == "not_found":
        rows = [{"publisher": s.get("publisher", ""), "link": s.get("link", ""),
                 "excerpt": s.get("excerpt", "")}
                for s in (point.get("nearest") or {}).get("sources") or []]
    seen: set[str] = set()
    out = []
    for r in rows:
        key = r["publisher"] or r["link"]
        if key and key not in seen:
            seen.add(key)
            out.append(r)
    return out[:int(icfg.get("write_max_sources", 4))]


def _fact_sources(rows: list[dict]) -> list[dict]:
    # حكم المدقّق يدخل نص المصدر كي لا يُعدّ اقتباسه بين علامتي تنصيص «غير موجود في مقتطف»
    # عند فحص الأصالة (verify_draft.check_originality) وهو مطلوب تسميته في المتن
    return [{"name": r["publisher"], "link": r["link"],
             "text": r.get("excerpt", "") + (f" — حكم المدقّق: {r['verdict_label']}"
                                              if r.get("verdict_label") else "")} for r in rows]


def build_grounded(point: dict, cfg) -> tuple[list[dict], str]:
    """(الوقائع بشكل article._draft_article، «السؤال-العنوان»). الوقائع بلا درجة (أ) لأن
    الحَكَم وثّقها بمصادر مستقلة؛ والسؤال يحمل الواقعة المراد تقريرها لا سؤالًا حقيقيًا
    (title_note يلغي صيغة السؤال)."""
    verdict = point.get("verdict")
    rows = ordered_sources(point, cfg)
    sources = _fact_sources(rows)
    if verdict == "inaccurate":
        c = point.get("correction") or {}
        facts = [{"text": c.get("error") or c.get("correct", ""), "sources": sources},
                 {"text": f"الصيغة الصحيحة بنصّها: {c.get('correct', '')}", "sources": sources}]
        return facts, c.get("correct", "")
    if verdict == "false":
        facts = []
        for r in rows:
            who = f"{r['publisher']}" + (f" (حكمها: {r['verdict_label']})" if r.get("verdict_label") else "")
            facts.append({"text": f"{who}: {r.get('excerpt', '')}",
                          "sources": _fact_sources([r])})
        return facts, point.get("claim") or point.get("text", "")
    if verdict == "not_found":
        n = point.get("nearest") or {}
        facts = [{"text": n.get("title", ""), "sources": sources},
                 {"text": n.get("description", ""), "sources": sources}]
        return [f for f in facts if f["text"]], n.get("title", "")
    return [{"text": point.get("claim") or point.get("text", ""), "sources": sources}], \
        point.get("claim") or point.get("text", "")


def allowed_quotes(point: dict) -> list[str]:
    """نصوص يجوز اقتباسها حرفيًا بين علامتي تنصيص فوق مقتطفات المصادر (Issue #1225): في
    inaccurate وfalse وحدهما — الادّعاء المصحَّح أو المفنَّد يُقتبس ليُرَدّ عليه — claim النقطة
    وسياق تداولها. أي نص آخر من جسم الـIssue يبقى ممنوعًا، وغيرهما من الأحكام لا يُسمح لهما.
    وفي inaccurate يُضاف نص correction.correct (Issue #1229): هو الصيغة الصحيحة كما في المصدر
    فاقتباسه حرفيًا مشروع بطبيعته."""
    if point.get("verdict") not in ("inaccurate", "false"):
        return []
    texts = [point.get("claim"), point.get("circulating_context")]
    if point.get("verdict") == "inaccurate":
        texts.append((point.get("correction") or {}).get("correct"))
    return [t for t in texts if t]


def exempt_texts(point: dict) -> list[str]:
    """نصوص تُستثنى من فحص التتابع اللفظي (max_shared_run_words) لأنها المعلومة المطلوبة نفسها
    كما في المصدر (Issue #1229): الصيغة الصحيحة في inaccurate، وحكم المدقّق في false. ما حولها
    يُفحص كالمعتاد، ونسخ أي تتابع آخر من المقتطف يبقى مرفوضًا."""
    if point.get("verdict") == "inaccurate":
        return [t for t in [(point.get("correction") or {}).get("correct")] if t]
    if point.get("verdict") == "false":
        return [r["verdict_label"] for r in point.get("refuted_by") or [] if r.get("verdict_label")]
    return []


def checker_of(point: dict) -> dict | None:
    """المدقّق المسمّى في تفنيد: أول جهة تدقيق، وإلا أول نافٍ (حارس false قبل أن يصل هنا
    ضمن لنقطة false نافيَين مستقلَّين على الأقل)."""
    rows = ordered_sources(point, {})
    return rows[0] if rows else None


def instructions(point: dict, cfg) -> str:
    wi = _icfg(cfg).get("writer_instructions", {}) or {}
    verdict = point.get("verdict")
    template = wi.get(verdict, "")
    if verdict == "inaccurate":
        c = point.get("correction") or {}
        body = template.format(correct=c.get("correct", ""), wrong=point.get("claim") or point.get("text", ""))
    elif verdict == "false":
        who = checker_of(point) or {}
        label = who.get("verdict_label", "")
        clause = wi.get("label_clause", "").format(label=label) if label else ""
        body = template.format(rumor=point.get("claim") or point.get("text", ""),
                               checker=who.get("publisher", ""), label_clause=clause)
    elif verdict == "not_found":
        near = point.get("nearest") or {}
        if near.get("kind") == "single_source":
            # مصدر واحد (#1282): تعليمات خاصة تنسب كل شيء إليه ولا تكتبه حقيقة ثابتة
            # عنوانه نصّ النقطة نفسها ← مفتاح لا يمنع ذكرها (الشرط نفسه في check_text)
            same = near.get("title") in (point.get("claim"), point.get("text"))
            template = wi.get("not_found_single_claim" if same else "not_found_single", template)
            publisher = ((near.get("sources") or [{}])[0]).get("publisher", "")
            body = template.format(nearest_title=near.get("title", ""), publisher=publisher)
        else:
            body = template.format(nearest_title=near.get("title", ""))
    else:
        body = template
    if verdict in ("confirmed", "inaccurate") and point.get("support_level") == "single":
        # مصدر واحد من مصادرنا (#1288): تُنسب المعلومة إليه صراحة ولا تُكتب حقيقة ثابتة
        publisher = point.get("support_publisher") or (ordered_sources(point, cfg) or [{}])[0].get("publisher", "")
        body += "\n" + wi.get("confirmed_single", "").format(publisher=publisher)
    return (f"\n{wi.get('title_note', '')}\n{body}\n{wi.get('quote_note', '')}\n"
            f"{wi.get('attribution_note', '')}\n")


# ───────────────────────────── عنوان خبري (Issue #1233) ─────────────────────────────


def is_statement_verdict(point: dict, cfg) -> bool:
    """تصحيح وتفنيد: عنوانهما الافتراضي جملة خبرية لا سؤال (important.statement_headline_verdicts)."""
    return point.get("verdict") in (_icfg(cfg).get("statement_headline_verdicts") or [])


def _is_question(text: str, cfg) -> bool:
    """سؤال حقيقي: يبدأ بأداة استفهام من الإعداد. «؟» وحدها في آخر جملة خبرية لا تجعلها سؤالًا —
    هذا ما حدث في 602ac9017f8e (جملة خبرية أُلحقت بها «؟»)."""
    words = _norm(text).split()
    return bool(words) and words[0] in {_norm(w) for w in _icfg(cfg).get("question_starts") or []}


def _strip_question_mark(text: str) -> str:
    return re.sub(r"[؟?]+\s*$", "", text.strip()).rstrip()


def normalize_statement_title(written: dict, cfg) -> dict:
    """ينزع «؟» الملحقة بآخر post_title/image_headline حين تكون الجملة خبرية؛ السؤال الحقيقي يُترك
    ليرفضه check_text فتُعاد الكتابة (لا نغيّر معنى جملة استفهامية بنزع علامتها)."""
    for key in ("post_title", "image_headline"):
        value = written.get(key, "")
        if value.rstrip().endswith(("؟", "?")) and not _is_question(value, cfg):
            written[key] = _strip_question_mark(value)
    return written


# ───────────────────────────── تنبيه الجمل بلا مصدر (Issue #1233) ─────────────────────────────


def unsourced_sentences(point: dict, written: dict, grounded: list[dict], question: str, cfg) -> list[str]:
    """جمل المتن التي فيها رقم أو تتابع كلمات مضمون غائب عن مقتطفات أدلة النقطة وclaim وcorrection.
    الكاشف هو article._unsourced_entities نفسه (لا كاشف ثانٍ) على كل جملة منفردة كي يُبلَّغ
    بالجملة لا بالشظية؛ source_texts=None فيبقى شرط الطول وحده (الجملة التي لم تأتِ من أي مصدر
    هي المقصودة، لا المنقولة منه). تنبيه لا رفض: النتيجة تُحفَظ في draft["warnings"] فقط."""
    ucfg = _icfg(cfg).get("unsourced", {}) or {}
    if not ucfg.get("enabled", True):
        return []
    c = point.get("correction") or {}
    known = " ".join(filter(None, [
        point.get("claim"), point.get("circulating_context"), c.get("error"), c.get("correct"),
        *[r.get("excerpt", "") for r in ordered_sources(point, cfg)],
        *[r.get("publisher", "") for r in ordered_sources(point, cfg)],
        *[r.get("verdict_label", "") for r in ordered_sources(point, cfg)],
    ]))
    neutral = " ".join(ucfg.get("neutral_words") or [])
    out: list[str] = []
    for sentence in re.split(r"(?<=[.!؟?۔])\s+|\n+", written.get("post_body", "")):
        sentence = sentence.strip()
        if not sentence:
            continue
        if article._unsourced_entities(sentence, grounded, known, question, [], None,
                                       int(ucfg.get("min_run", 2)), attribution_phrase=neutral):
            out.append(sentence)
    return out


# ───────────────────────────── الفحص بعد الكتابة ─────────────────────────────


def _outlet_names(cfg) -> list[list[str]]:
    """أسماء الوسائل كسلاسل كلمات مطبَّعة: sources (name وname_ar) + important.outlet_aliases."""
    raw = [str(s.get(k) or "") for s in cfg.get("sources", []) or [] for k in ("name", "name_ar")]
    raw += [str(a) for a in _icfg(cfg).get("outlet_aliases") or []]
    out = []
    for n in raw:
        toks = _norm(n).split()
        if toks and toks not in out:
            out.append(toks)
    return out


def outlet_judgment_violations(text: str, cfg) -> list[str]:
    """الوسيلة الإعلامية ناقلة لا حَكَم (Issue #1291): جملة فيها فعل حكم (important.judgment_verbs)
    ضمن judgment_window كلمات من اسم وسيلة، قبله أو بعده، مخالفة. أفعال النقل (أفادت/ذكرت/بحسب…)
    ليست في القائمة فمسموحة. حرف العطف الملتصق («وتعدّ»، «وDW») يُتسامح فيه."""
    icfg = _icfg(cfg)
    window = int(icfg.get("judgment_window", 3))
    verbs = {t for v in icfg.get("judgment_verbs") or [] for t in _norm(v).split()}
    outlets = _outlet_names(cfg)
    if not verbs or not outlets:
        return []

    def strip_w(tok: str) -> list[str]:
        return [tok, tok[1:]] if tok[:1] in ("و", "ف") and len(tok) > 1 else [tok]

    out: list[str] = []
    for sentence in re.split(r"(?<=[.!؟?۔])\s+|\n+", text or ""):
        toks = _norm(sentence).split()
        v_at = [i for i, t in enumerate(toks) if any(c in verbs for c in strip_w(t))]
        if not v_at:
            continue
        spans = []
        for name in outlets:
            n = len(name)
            for i in range(len(toks) - n + 1):
                head = strip_w(toks[i])
                if any([h] + toks[i + 1:i + n] == name for h in head):
                    spans.append((i, i + n - 1))
        if any((vi - end - 1 <= window and vi > end) or (start - vi - 1 <= window and start > vi)
               for vi in v_at for start, end in spans):
            out.append(icfg.get("outlet_judgment_violation",
                                "حكم منسوب إلى وسيلة إعلام ({sentence}): انسبه إلى قائله بالاسم أو احذفه"
                                ).format(sentence=sentence.strip()))
    return out


def check_text(point: dict, written: dict, cfg) -> str | None:
    """يعيد سبب الرفض أو None. مطابقة مطبَّعة (_norm) في الكود — الموجّه وحده لا يكفي."""
    verdict = point.get("verdict")
    title = written.get("post_title", "")
    body = written.get("post_body", "")
    first = first_sentence(body)
    icfg = _icfg(cfg)

    # لا درجة ج ولا نسبة رأي في «هام» (#1229): لا موجز محرر هنا، فورود العبارتين يعني أن الكاتب
    # كتب من نص المستخدم لا من أدلة النقطة — يُرفض أيًّا كان الحكم
    acfg = cfg.get("article", {}) or {}
    for phrase in (acfg.get("editor_tag_phrase", "بحسب معلومات المحرر"),
                   acfg.get("opinion_attribution_phrase", "وترى الصفحة أن")):
        if _has_phrase(f"{title} {body}", phrase):
            return REASON_EDITOR_TAG

    if is_statement_verdict(point, cfg) and (
            title.rstrip().endswith(("؟", "?")) or _is_question(title, cfg)
            or first.rstrip().endswith(("؟", "?")) or _is_question(first, cfg)):
        return REASON_QUESTION_TITLE

    if verdict == "false":
        for claim in {point.get("claim", ""), point.get("text", "")} - {""}:
            if _contains(title, claim):
                return REASON_RUMOR_TITLE
            if _contains(first, claim):
                return REASON_RUMOR_FIRST
        who = checker_of(point) or {}
        name_tokens = norm_tokens(who.get("publisher", ""))
        if not name_tokens or not name_tokens <= norm_tokens(f"{title} {body}"):
            return REASON_NO_CHECKER
        label = who.get("verdict_label", "")
        if label and not _contains(f"{title} {body}", label):
            return REASON_NO_LABEL
    elif verdict == "inaccurate":
        correct = (point.get("correction") or {}).get("correct", "")
        if not (_contains(title, correct) and _contains(first, correct)):
            return REASON_NO_CORRECT
    elif verdict == "not_found":
        near = point.get("nearest") or {}
        same = near.get("kind") == "single_source" and near.get("title") in (point.get("claim"), point.get("text"))
        if _mentions_original(point, f"{title}\n{body}", icfg, claim_allowed=same):
            return REASON_ORIGINAL
    violations = outlet_judgment_violations(f"{title}\n{body}", cfg)
    if violations:
        return violations[0]
    return None


def _mentions_original(point: dict, text: str, icfg, claim_allowed: bool = False) -> bool:
    """هل يذكر النص النقطة الأصلية؟ جملتها حرفيًا، أو جملة واحدة تحوي نسبة كبيرة من كلماتها،
    أو عبارة تعلن غياب الأثر (important.not_found_forbidden)."""
    overlap = float(icfg.get("original_mention_overlap", 0.8))
    # أقرب ما وُجد بمصدر واحد وعنوانه نصّ النقطة نفسها (#1282، الدرجة أ): النقطة هي الموضوع المنسوب إلى
    # المصدر، فذكرها مشروع؛ تبقى عبارات غياب الأثر ممنوعة
    for original in ({point.get("claim", ""), point.get("text", "")} - {""}) if not claim_allowed else ():
        if _contains(text, original):
            return True
        words = {w for w in _norm(original).split() if len(w) >= 3}
        if len(words) < 4:
            continue
        for sentence in re.split(r"(?<=[.!؟?۔])\s+|\n+", text):
            if len(words & set(_norm(sentence).split())) / len(words) >= overlap:
                return True
    folded = _norm(text)
    return any(_contains(folded, phrase) for phrase in icfg.get("not_found_forbidden") or [])


# ───────────────────────────── الكتابة ─────────────────────────────


def _draft_id(point: dict, source_issue: int) -> str:
    """معرّف المسودة = معرّف النقطة (12 سداسيًا عشريًا يقبله stages.GO_MARKER)؛ فإن وُجدت مسودة
    بالمعرّف نفسه (النص نفسه لصق ثانية فخرجت نقطة بالمعرّف نفسه) اشتُقّ معرّف جديد بدل
    الكتابة فوقها — مسودة منشورة أو مرفوضة لا تُمحى."""
    pid = point["id"]
    if not store.load_draft(pid):
        return pid
    seed = f"important:{pid}:{source_issue}:{datetime.now(timezone.utc).isoformat()}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def write_point(point: dict, result: dict, cfg, selection_issue: int | None = None
                ) -> tuple[dict | None, str, bool]:
    """يكتب نقطة معتمدة ويحفظ مسودتها. يعيد (المسودة، سبب الفشل، هل الفشل تقني).
    تقني = عطل API لا يعكس رأيًا في النص (يبقى approved ليُعاد بلا إعادة تعليم)؛ غيره رفض
    تحريري بعد استنفاد المحاولات."""
    acfg = cfg.get("article", {}) or {}
    grounded, question = build_grounded(point, cfg)
    # بلا مقتطف مصدر فعلي لا وقائع مسندة: الكاتب حينها يكتب من نص الـIssue بدرجة ج («بحسب معلومات
    # المحرر») وهذا ما نُشر في #1229 — فشل كتابة صريح بدل مقال، بلا نداء نموذج
    if not article._source_docs(grounded):
        return None, NO_FACTS_REASON, False

    attempts = max(1, int(_icfg(cfg).get("write_attempts", 2)))
    # الوقاية قبل الكتابة (Issue #1252): الأسماء المعتمدة التي يرد أصلها في الأدلة تُلحَق بتعليمات الكتابة
    name_note = names_audit.names_note(
        [d["text"] for d in article._source_docs(grounded)] + [point.get("claim") or ""], cfg)
    base_note = instructions(point, cfg) + (f"\n{name_note}\n" if name_note else "")
    note = base_note
    wi = _icfg(cfg).get("writer_instructions", {}) or {}
    system_note = wi.get("no_editor_note", "").format(
        editor_tag=acfg.get("editor_tag_phrase", "بحسب معلومات المحرر"),
        opinion_phrase=acfg.get("opinion_attribution_phrase", "وترى الصفحة أن"))
    written, reason = None, ""
    for attempt in range(attempts):
        got, err = article._draft_article(grounded, [], question, cfg, avoid_note=note,
                                           system_note=system_note)
        if got is None:
            return None, err, err.startswith(TECHNICAL_PREFIX)
        if is_statement_verdict(point, cfg):
            normalize_statement_title(got, cfg)
        reason = check_text(point, got, cfg) or ""
        if not reason:
            ok, why, _notes = verify_draft.check_originality(
                got["post_body"], "", article._source_docs(grounded),
                int(acfg.get("max_shared_run_words", 7)),
                allowed_quotes=allowed_quotes(point), exempt_texts=exempt_texts(point))
            reason = "" if ok else f"{REASON_ORIGINALITY}: {why}"
        if not reason:
            written = got
            break
        log.warning("نقطة %s رُفضت بعد الكتابة (محاولة %d/%d): %s",
                    point["id"], attempt + 1, attempts, reason)
        note = base_note + "\n" + wi.get("retry_note", "{reason}").format(reason=reason) + "\n"
    if written is None:
        return None, reason, False

    draft = build_draft(point, result, written, cfg, selection_issue)
    # تنبيهات الحكم (مؤيِّدون من خارج مصادرنا، #1282) أولًا ثم الجمل بلا مصدر
    warns = list(point.get("warnings") or []) + unsourced_sentences(point, written, grounded, question, cfg)
    if warns:
        draft["warnings"] = warns   # للمراجعة فقط: لا تدخل caption ولا تمنع النشر
    # تدقيق أسماء الأشخاص بدليل بحث (Issue #1252): نصوص الأدلة وحدها مصدرًا، وتنبيهه يُلحَق بما قبله
    names_audit.run(draft, [d["text"] for d in article._source_docs(grounded)] + [point.get("claim") or ""],
                    cfg)
    store.save_draft(draft)
    return draft, "", False


def build_draft(point: dict, result: dict, written: dict, cfg, selection_issue: int | None) -> dict:
    icfg = _icfg(cfg)
    rows = ordered_sources(point, cfg)
    publishers = [r["publisher"] for r in rows if r["publisher"]]
    primary_link = rows[0]["link"] if rows else ""
    title = point.get("claim") or point.get("text", "")
    if point.get("verdict") == "not_found" and point.get("nearest"):
        title = point["nearest"]["title"]

    if is_statement_verdict(point, cfg):
        # قاعدة «الأول سؤال» المشتركة لا تسري على التصحيح والتفنيد (Issue #1233)
        headlines, hl_error = headlines_mod.headlines_for_post(
            written["post_title"], written["post_body"], cfg, first_question=False,
            system=icfg.get("headline_system") or None)
    else:
        headlines, hl_error = headlines_mod.headlines_for_post(
            written["post_title"], written["post_body"], cfg)
    if hl_error:
        log.warning("فشلت اقتراحات العناوين لنقطة %s: %s", point["id"], hl_error)
        headlines = []

    image_urls = [c["url"] for c in point.get("image_candidates") or []
                  if isinstance(c, dict) and str(c.get("url", "")).startswith(("http://", "https://"))]
    related_max = int(cfg.path("collect.related_links_max", 3))
    related = [r for r in rows[1:] if r["link"]][:related_max]

    art = Article(
        title=title, link=primary_link, summary=title,
        source_name=publishers[0] if publishers else "", region="global",
        weight=1.0, published=datetime.now(timezone.utc),
        publisher=publishers[0] if publishers else "", cluster_sources=publishers,
    )
    draft = {
        "id": _draft_id(point, result["issue"]),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "review_issue": None,
        "origin": DRAFT_ORIGIN,
        "point_id": point["id"],
        "source_issue": result["issue"],
        "selection_issue": selection_issue,
        "verdict": point["verdict"],
        "badge": (icfg.get("badges", {}) or {}).get(point["verdict"], ""),
        "score": 0.0,
        "bucket": "serious",
        "analysed_sources": publishers,
        "trend_score": 0.0,
        "velocity": 0.0,
        "age_hours": 0.0,
        "is_followup": False,
        "state_media": False,
        "source": {
            "title": title,
            "link": primary_link,
            "publisher": publishers[0] if publishers else "",
            "publishers": publishers,
            "region": "global",
            "image_url": image_urls[0] if image_urls else None,
            "image_candidates": image_urls,
            **({"related_links": [r["link"] for r in related],
                "related_publishers": [r["publisher"] for r in related]} if related else {}),
        },
        "arabic": written,
        "caption": writer.build_caption(written, art, cfg),
        "headlines": headlines,
        "headline_selected": 0,
        "image_query_en": written.get("image_query_en"),
        # بلا حقل image عمدًا: البطاقة تُبنى عند الانتقال (cards.ensure) لا هنا (Issue #852)
        "reel": None,
        "reel_spec": {
            "headline": written["image_headline"] or written["post_title"],
            "category": written["category"],
            "urgent": False,
            "image_candidates": image_urls,
        },
    }
    if point.get("superseded_note"):
        draft["superseded_note"] = point["superseded_note"]   # يظهر بارزًا في قضية المرحلة 2
    if point.get("manual_image"):
        draft["manual_image"] = point["manual_image"]   # صورة المراجع من المرحلة 1 تغلب كالعادة
    return draft
