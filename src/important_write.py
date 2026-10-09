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

import copy
import hashlib
import logging
import re
from datetime import datetime, timezone

from . import (article, headlines as headlines_mod, important, important_gap, names_audit, store,
               verify_draft, writer)
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


def unsourced_in(known: str, written: dict, grounded: list[dict], question: str, cfg) -> list[str]:
    """جمل المتن التي فيها رقم أو تتابع كلمات مضمون غائب عن `known` (نصوص الأدلة المعروفة).
    الكاشف هو article._unsourced_entities نفسه (لا كاشف ثانٍ) على كل جملة منفردة كي يُبلَّغ
    بالجملة لا بالشظية؛ source_texts=None فيبقى شرط الطول وحده (الجملة التي لم تأتِ من أي مصدر
    هي المقصودة، لا المنقولة منه). تنبيه لا رفض: النتيجة تُحفَظ في draft["warnings"] فقط."""
    ucfg = _icfg(cfg).get("unsourced", {}) or {}
    if not ucfg.get("enabled", True):
        return []
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


def unsourced_sentences(point: dict, written: dict, grounded: list[dict], question: str, cfg) -> list[str]:
    """جمل المتن بلا سند في claim النقطة وcorrection ومقتطفات أدلتها (#1233)."""
    c = point.get("correction") or {}
    known = " ".join(filter(None, [
        point.get("claim"), point.get("circulating_context"), c.get("error"), c.get("correct"),
        *[r.get("excerpt", "") for r in ordered_sources(point, cfg)],
        *[r.get("publisher", "") for r in ordered_sources(point, cfg)],
        *[r.get("verdict_label", "") for r in ordered_sources(point, cfg)],
    ]))
    return unsourced_in(known, written, grounded, question, cfg)


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


# ───────────────────────────── منشور الخبر الرئيسي (Issue #1293، B2) ─────────────────────────────

REASON_WORDS = "عدد كلمات المنشور {n} خارج المدى المقبول [{lo}، {hi}]"
REASON_QUOTE = ("اقتباس بين « » ليس في أي مقتطف معطى: «{quote}» — انقله حرفيًا من المقتطف كما هو، "
                "أو اكتبه كلامًا غير مباشر بلا علامتي تنصيص")
REASON_QUOTE_CONVERTED = "اقتباس لم يطابق مصدره حرفيًا فحُوِّل إلى كلام غير مباشر: «{quote}» — راجعه"
REASON_TITLE_QUESTION = "العنوان سؤال لا جملة خبرية"
# منشور الخبر الرئيسي لا يسقط بحارس شكلي (#1304): السبب الباقي بعد الإصلاح الآلي يُحفظ تنبيهًا بهذا القالب
WARN_FAILED_CHECK = "⚠️ لم يجتز الفحص: {reason} — راجعه قبل النشر"
WARN_FAILED_CHECK_PREFIX = "⚠️ لم يجتز الفحص"
WARN_PUBLISHED = "(نُشر: {date})"
WARN_NO_DATE = "(تاريخ غير معروف)"
WARN_OFF_TOPIC = "⚠️ فقرة قد تكون خارج الموضوع: «{start}…»"
WARN_REPEAT = "⚠️ تكرار مع منشور آخر من النص نفسه: «{run}…»"
WARN_NO_REFUTATION = "⚠️ منشور التفنيد لا يذكر الصيغة الصحيحة أو جهة النفي لـ: {points}"
WARN_RELATIVE_TIME = "زمن نسبي في المتن: «{phrase}» — تحقّق من التاريخ"
WARN_NON_ARABIC_PUBLISHER = "اسم مصدر بغير العربية: {name}"
# نوع المنشور ← الحكم الذي تُبنى عليه شارة البطاقة (cards.card_origin): التفنيد بشارته، وغيره «هام»
ARTICLE_VERDICT = {"verified": "confirmed", "nearest": "not_found", "refuted": "false"}
_QUOTE_RE = re.compile(r"«([^»]*)»")


def item_members(result: dict, item: dict) -> list[dict]:
    by_id = {p["id"]: p for p in result["points"]}
    return [by_id[i] for i in item["point_ids"] if i in by_id]


def article_grounded(members: list[dict], gap: list[dict], cfg) -> list[dict]:
    """وقائع الكاتب: أدلة كل نقطة عضو كما في write_point، ثم مقتطفات البحث المكمِّل واقعةً لكل مقتطف
    بناشره ورابطه. بلا مقتطف مصدر فعلي لا وقائع مسندة."""
    facts: list[dict] = []
    for p in members:
        facts += build_grounded(p, cfg)[0]
    for g in gap:
        facts.append({"text": g["excerpt"], "sources": [
            {"name": g["publisher"], "link": g["link"], "text": g["excerpt"],
             "published": g.get("published", "")}]})
    # تاريخ نشر كل مصدر لأدلة الأعضاء: من read_docs الحكم بالرابط (#1309)
    dates = {d.get("link"): d.get("published", "") for p in members for d in p.get("read_docs") or []}
    for f in facts:
        for src in f["sources"]:
            src.setdefault("published", dates.get(src.get("link"), ""))
    # الكاتب يرى اسم الناشر بالعربية فينقله إلى المتن كما هو (#1304)؛ المسار القديم (write_point) لا يتغير
    # الكاتب يرى تاريخ نشر كل مقتطف (أو «تاريخ غير معروف») فلا يقدّم قديمًا على أنه جديد (#1309)
    for f in facts:
        f["sources"] = [{**src, "name": publisher_ar(src.get("name", ""), cfg),
                         "text": f"{src.get('text', '')} "
                                 + (WARN_PUBLISHED.format(date=src["published"]) if src.get("published")
                                    else WARN_NO_DATE)} for src in f["sources"]]
    return facts


def article_instructions(result: dict, item: dict, members: list[dict], sibling_texts: list[str], cfg) -> str:
    icfg = _icfg(cfg)
    ai = icfg.get("article_instructions", {}) or {}
    wi = icfg.get("writer_instructions", {}) or {}
    lo, hi = icfg.get("article_words", [180, 450])
    kind = item["kind"]
    points = "؛ ".join(f"«{p.get('claim') or p.get('text', '')}»" for p in members)
    body = ai.get("common", "").format(main_story=result.get("main_story", ""), lo=lo, hi=hi)
    body += "\n" + ai.get(kind, "").format(points=points)
    if kind == "verified":
        for p in members:
            if p.get("support_level") == "single":
                publisher = p.get("support_publisher") or (ordered_sources(p, cfg) or [{}])[0].get("publisher", "")
                body += "\n" + wi.get("confirmed_single", "").format(publisher=publisher)
    if sibling_texts:
        body += "\n" + ai.get("siblings", "{siblings}").format(siblings="\n---\n".join(sibling_texts))
    return f"\n{wi.get('title_note', '')}\n{body}\n{wi.get('quote_note', '')}\n{wi.get('attribution_note', '')}\n"


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text or "", re.UNICODE))


def quote_violations(text: str, sources: list[str], allowed: list[str] | None = None) -> list[str]:
    """اقتباسات « » في النص غير الموجودة حرفيًا في أي من `sources` (مقتطفات المصادر) أو `allowed`.
    الدالة نفسها التي يستعملها verify_draft.check_originality (_quoted_spans + _normalized_words +
    _contains_run) كي لا يحكم فحصان بحكمين مختلفين على اقتباس واحد فلا يصل الكاتب سبب واضح."""
    pool = [verify_draft._normalized_words(t) for t in list(sources) + list(allowed or []) if t]
    bad = []
    for q in verify_draft._quoted_spans(text):
        words = verify_draft._normalized_words(q)
        if not words or not any(verify_draft._contains_run(src, words) for src in pool):
            bad.append(q)
    return bad


def unquote_mismatches(written: dict, sources: list[str], allowed: list[str] | None = None
                       ) -> tuple[dict, list[str]]:
    """ينزع علامتي التنصيص عن كل اقتباس غير مطابق ويبقي نصه (تحويل إلى كلام غير مباشر بدل إسقاط
    المنشور). يعيد (نسخة النص المحوَّلة، الاقتباسات المحوَّلة)."""
    converted: list[str] = []

    def fix(text: str) -> str:
        def sub(m):
            q = m.group(1).strip()
            if q in quote_violations(m.group(0), sources, allowed):
                converted.append(q)
                return m.group(1)
            return m.group(0)
        return verify_draft.QUOTE_RE.sub(sub, text or "")

    out = dict(written)
    for key in ("post_title", "post_body"):
        out[key] = fix(written.get(key, ""))
    return out, list(dict.fromkeys(converted))


def article_reasons(written: dict, given: list[str], cfg, allowed: list[str] | None = None) -> list[str]:
    """كل أسباب رفض منشور الخبر الرئيسي بترتيب الفحص (الطول خرج منها في #1309 إلى length_reasons تنبيهًا): عبارة المحرر/الرأي
    المحظورة في «هام»، فعل حكم منسوب إلى وسيلة، اقتباس ليس في أي مقتطف معطى (`given` مقتطفات المصادر
    وحدها، و`allowed` ادّعاءات refuted)، عنوان سؤال. تعيد القائمة كلها لا أولها كي يصير كل سبب باقٍ
    تنبيهًا مستقلًا بعد الإصلاح الآلي (#1304)."""
    icfg = _icfg(cfg)
    title, body = written.get("post_title", ""), written.get("post_body", "")
    out: list[str] = []
    acfg = cfg.get("article", {}) or {}
    for phrase in (acfg.get("editor_tag_phrase", "بحسب معلومات المحرر"),
                   acfg.get("opinion_attribution_phrase", "وترى الصفحة أن")):
        if _has_phrase(f"{title} {body}", phrase):
            out.append(REASON_EDITOR_TAG)
            break
    out += outlet_judgment_violations(f"{title}\n{body}", cfg)
    bad = quote_violations(f"{title}\n{body}", given, allowed)
    if bad:
        out.append(REASON_QUOTE.format(quote=bad[0]))
    if title.rstrip().endswith(("؟", "?")) or _is_question(title, cfg):
        out.append(REASON_TITLE_QUESTION)
    return out


def length_reasons(written: dict, cfg) -> list[str]:
    """الطول تنبيه لا رفض (#1309): تحت article_words_warn_below أو فوق أقصى×article_words_tolerance[1].
    لا حدّ أدنى ملزم، فمنشور قصير لأن الوقائع المتصلة قليلة سليم."""
    icfg = _icfg(cfg)
    hi = icfg.get("article_words", [180, 450])[1]
    floor = int(icfg.get("article_words_warn_below", 150))
    ceil = int(hi * icfg.get("article_words_tolerance", [0.85, 1.2])[1])
    n = word_count(written.get("post_body", ""))
    return [REASON_WORDS.format(n=n, lo=floor, hi=ceil)] if (n < floor or n > ceil) else []


def off_topic_warnings(written: dict, pivots: list[str], cfg) -> list[str]:
    """كل فقرة لا تذكر أيًّا من الكيانات المحورية ← تنبيه بأول 12 كلمة منها (#1309). بلا كيانات محورية لا حكم."""
    if not pivots:
        return []
    icfg = cfg.get("important", {}) or {}
    out = []
    for para in re.split(r"\n\s*\n|\n", written.get("post_body", "") or ""):
        if para.strip() and not important_gap.mentions_pivot(para, pivots, icfg):
            out.append(WARN_OFF_TOPIC.format(start=" ".join(para.split()[:12])))
    return out


def repeat_warnings(written: dict, siblings: list[str], run_words: int = 12) -> list[str]:
    """تتابع run_words كلمة فأكثر مشترك مع أحد إخوة المنشور ← تنبيه (#1309)."""
    words = verify_draft._normalized_words(f"{written.get('post_title', '')}\n{written.get('post_body', '')}")
    for sib in siblings:
        sw = verify_draft._normalized_words(sib)
        for i in range(len(words) - run_words + 1):
            if verify_draft._contains_run(sw, words[i:i + run_words]):
                return [WARN_REPEAT.format(run=" ".join(words[i:i + run_words]))]
    return []


def refutation_warnings(kind: str, members: list[dict], written: dict, cfg) -> list[str]:
    """منشور التفنيد يفنّد فعلًا (#1309): لكل عضو inaccurate يرد correction.correct، ولكل false اسم أول
    refuted_by بالعربية (أو أصله) في المتن؛ وإلا تنبيه بنقاط الأعضاء الناقصة."""
    if kind != "refuted":
        return []
    text = f"{written.get('post_title', '')} {written.get('post_body', '')}"
    missing = []
    for p in members:
        if p.get("verdict") == "inaccurate":
            ok = _contains(text, (p.get("correction") or {}).get("correct", ""))
        elif p.get("verdict") == "false":
            who = ((p.get("refuted_by") or [{}])[0]).get("publisher", "")
            ok = bool(who) and (_contains(text, publisher_ar(who, cfg)) or _contains(text, who))
        else:
            continue
        if not ok:
            missing.append(p.get("claim") or p.get("text", ""))
    return [WARN_NO_REFUTATION.format(points="؛ ".join(missing))] if missing else []


def check_article(written: dict, given: list[str], cfg, allowed: list[str] | None = None) -> str | None:
    """أول سبب رفض (article_reasons) أو None — يقرؤه حلقة المحاولات: السبب الأول يكفي لتوجيه الكاتب."""
    reasons = article_reasons(written, given, cfg, allowed)
    return reasons[0] if reasons else None


# ───────────── أسماء المصادر بالعربية والزمن النسبي (Issue #1304) ─────────────


def _publisher_map(cfg) -> dict[str, str]:
    """الاسم اللاتيني ← العربي: name_ar من sources/channels أولًا ثم important.publisher_ar (الأولى تغلب)."""
    out = {str(k): str(v) for k, v in (_icfg(cfg).get("publisher_ar") or {}).items() if k and v}
    for entry in list(cfg.get("sources", []) or []) + list(cfg.get("channels", []) or []):
        if isinstance(entry, dict) and entry.get("name") and entry.get("name_ar"):
            out[str(entry["name"])] = str(entry["name_ar"])
    return out


def publisher_ar(name: str, cfg) -> str:
    """اسم الناشر بالعربية للكاتب والمتن؛ بلا مقابل يعاد الاسم كما هو (فيُنبَّه عليه إن لاتينيًا)."""
    return _publisher_map(cfg).get(name) or next(
        (v for k, v in _publisher_map(cfg).items() if k.casefold() == (name or "").casefold()), name)


_LATIN_RE = re.compile(r"[A-Za-z]")
_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")


def arabize_publishers(written: dict, names: list[str], cfg) -> tuple[dict, list[str]]:
    """يستبدل في post_title وpost_body وimage_headline كل اسم لاتيني له مقابل عربي (الأطول أولًا كي لا يُقصّ
    «U.S. Department of State (.gov)» إلى «… (.gov)»). يعيد (النسخة، تنبيهات اسم لاتيني بلا مقابل ورد في
    المتن من `names` ناشري المنشور)."""
    mapping = _publisher_map(cfg)
    out = dict(written)
    for key in ("post_title", "post_body", "image_headline"):
        text = out.get(key) or ""
        for latin in sorted(mapping, key=len, reverse=True):
            if _LATIN_RE.search(latin):
                # حسّاس للحالة (#1316): «time» الإنجليزية داخل المتن و«aa» لا تُستبدل باسم ناشر
                text = re.sub(rf"(?<![\w]){re.escape(latin)}(?![\w])", mapping[latin], text)
        out[key] = text
    shown = f"{out.get('post_title', '')}\n{out.get('post_body', '')}".casefold()
    warns = []
    for n in dict.fromkeys(names):
        if n and _LATIN_RE.search(n) and not _ARABIC_RE.search(n) and publisher_ar(n, cfg) == n \
                and n.casefold() in shown:
            warns.append(WARN_NON_ARABIC_PUBLISHER.format(name=n))
    return out, warns


# ───────────── النقل الحرفي المنسوب يصير اقتباسًا (Issue #1316) ─────────────

_TOKEN_RE = re.compile(r"[\w'\u0640\u064B-\u065F\u0670]+", re.UNICODE)
_SENT_SPLIT_RE = re.compile(r"((?<=[.!؟?])\s+|\n+)")
_LEAD_PARTICLES = {"ان", "بان"}   # بعد التطبيع (إن/أن/بأن): أداة ربط لا من كلام المصدر المنقول


def _publisher_forms(publisher: str, cfg) -> list[str]:
    """صيغ الناشر المطبَّعة للبحث عن ذكره في الجملة: اسمه وعربيه، وما يطابقه من outlet_aliases."""
    names = [publisher, publisher_ar(publisher, cfg)]
    folded = [important._fold(n) for n in names if n]
    for alias in _icfg(cfg).get("outlet_aliases") or []:
        fa = important._fold(alias)
        if fa and any(fa in f or f in fa for f in folded if f):
            names.append(alias)
    # صيغ الذكر من الإعداد (#1331): «بيان وزارة الخارجية» لا يحوي اسم الناشر المسجَّل «وزارة الخارجية الأميركية»
    for key, mentions in (_icfg(cfg).get("publisher_mentions") or {}).items():
        fk = important._fold(key)
        if fk and any(fk == f or fk in f or f in fk for f in folded if f):
            names += list(mentions or [])
    forms = [" ".join(important._WORD_RE.findall(important._fold(n))) for n in names if n]
    return [f for f in dict.fromkeys(forms) if f]


def _longest_common_run(a: list[str], b: list[str]) -> tuple[int, int]:
    """(بداية التتابع في a، طوله) لأطول تتابع متجاور مشترك."""
    best, best_i = 0, 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best, best_i = cur[j], i - cur[j]
        prev = cur
    return best_i, best


def quote_attributed_copies(written: dict, sources: list[tuple[str, str]], cfg) -> tuple[dict, list[str]]:
    """نقل حرفي (تتابع ≥ article_max_shared_run_words كلمة مع مقتطف) داخل جملة تذكر ناشر ذلك المقتطف يُحاط
    بـ« » فيصير اقتباسًا منسوبًا صحيحًا بدل نسخ يُنبَّه عليه (#1316: «قالت الخارجية إن …» نُقلت من بيان
    state.gov حرفيًا). النقل غير المنسوب يبقى للأصالة؛ وتعذّر ربط الكلمات المطبَّعة بكلمات الجملة أو كون
    المقطع داخل « » أصلًا ← لا تحويل. يعيد (نسخة النص، بدايات المقاطع المحوَّلة) ولا يمسّ العنوان."""
    body = written.get("post_body") or ""
    threshold = int(_icfg(cfg).get("article_max_shared_run_words", 12))
    prepared = [(verify_draft._normalized_words(text), _publisher_forms(pub, cfg)) for pub, text in sources if text]
    parts = _SENT_SPLIT_RE.split(body)
    converted: list[str] = []
    for k in range(0, len(parts), 2):
        sentence = parts[k]
        tokens = list(_TOKEN_RE.finditer(sentence))
        norm = [verify_draft._normalized_words(m.group(0)) for m in tokens]
        keep = [(m, n[0]) for m, n in zip(tokens, norm) if len(n) == 1]
        if len(keep) != len(verify_draft._normalized_words(sentence)) or len(keep) < threshold:
            continue   # الربط واحدًا بواحد متعذّر
        words = [w for _m, w in keep]
        best = None   # (طول، بداية)
        for src_words, forms in prepared:
            if not forms or not important._mentions(sentence, forms):
                continue
            i, n = _longest_common_run(words, src_words)
            if n >= threshold and (best is None or n > best[0]):
                best = (n, i)
        if best is None:
            continue
        n, i = best
        while n > 0 and words[i] in _LEAD_PARTICLES:
            i, n = i + 1, n - 1
        if n < 1:
            continue
        start, end = keep[i][0].start(), keep[i + n - 1][0].end()
        # حدّ البداية (#1331): لا يُحاط إلا مقطع سبقه مباشرة أداة ربط أو فعل قول أو نقطتان؛ مقطع يبدأ من منتصف
        # الجملة بعد حرف جر («في 31 تشرين الأول…») يصير اقتباسًا مبتورًا
        lead = {verify_draft._normalized_words(w)[0] for w in _icfg(cfg).get("quote_lead_words") or []
                if verify_draft._normalized_words(w)}
        if not ((i > 0 and words[i - 1] in lead) or sentence[:start].rstrip().endswith(":")):
            continue
        if any(m.start() < end and start < m.end() for m in verify_draft.QUOTE_RE.finditer(sentence)):
            continue   # داخل « » أصلًا
        converted.append(" ".join(sentence[start:end].split()[:12]))
        parts[k] = f"{sentence[:start]}«{sentence[start:end]}»{sentence[end:]}"
    if not converted:
        return written, []
    out = dict(written)
    out["post_body"] = "".join(parts)
    return out, converted


def relative_time_warnings(written: dict, cfg) -> list[str]:
    """تنبيه لكل عبارة زمن نسبي (important.relative_time_words) وردت في العنوان أو المتن: «الشهر الماضي»
    المنقولة من مصدر تُقرأ بتاريخ النشر لا بتاريخ المراجع."""
    text = f"{written.get('post_title', '')} {written.get('post_body', '')}"
    return [WARN_RELATIVE_TIME.format(phrase=w) for w in _icfg(cfg).get("relative_time_words") or []
            if _contains(text, w)]


def _article_cfg(cfg):
    """نسخة من cfg بطول المنشور المطلوب في article.post_length (يقرؤه article._draft_article)."""
    hi = _icfg(cfg).get("article_words", [180, 450])[1]
    out = copy.copy(cfg)
    out["article"] = {**(cfg.get("article", {}) or {}), "post_length": f"حتى {hi} كلمة"}
    return out


def _salvage(last: dict, sources_text: list[str], allowed: list[str], originality, cfg
             ) -> tuple[dict, list[str], list[str]]:
    """بعد آخر محاولة مرفوضة: إصلاح آلي على آخر نص ثم إعادة الفحص عليه (#1304). العنوان السؤال يُستبدل بأول
    عنوان خبري من headlines_for_post (وإلا يبقى مع تنبيه)، والاقتباس غير المطابق يُنزع تنصيصه (#1298)،
    وكل سبب باقٍ (طول، نسبة حكم، أصالة…) تنبيه «لم يجتز الفحص» لا فشل. يعيد (النص، الاقتباسات المحوَّلة،
    التنبيهات)."""
    fixed = dict(last)
    if _is_question_title(fixed.get("post_title", ""), cfg):
        heads, err = headlines_mod.headlines_for_post(
            fixed["post_title"], fixed.get("post_body", ""), cfg, first_question=False,
            system=_icfg(cfg).get("headline_system") or None)
        first = next((h for h in heads or [] if h and not _is_question_title(h, cfg)), None) if not err else None
        if first:
            fixed["post_title"] = first
            if _is_question_title(fixed.get("image_headline", ""), cfg):
                fixed["image_headline"] = first
    fixed, converted = unquote_mismatches(fixed, sources_text, allowed)
    reasons = article_reasons(fixed, sources_text, cfg, allowed)
    why = originality(fixed)
    if why:
        reasons.append(why)
    warns = [WARN_FAILED_CHECK.format(reason=r) for r in reasons]
    log.warning("منشور حُفظ بتنبيهات فحص بدل الفشل: %s", " | ".join(reasons) or "—")
    return fixed, converted, warns


def _is_question_title(title: str, cfg) -> bool:
    return title.rstrip().endswith(("؟", "?")) or _is_question(title, cfg)


def write_article(result: dict, item: dict, cfg, sibling_texts: list[str] | None = None,
                  selection_issue: int | None = None) -> tuple[dict | None, str, bool]:
    """يكتب منشور الخبر الرئيسي لعنصر مختار ويحفظ مسودته: بحث مكمِّل ← نداء كاتب واحد بنموذج
    article.model ← فحص في الكود (رفض ثم إعادة كتابة مرة واحدة بذكر العلّة ثم فشل بسببها). يعيد
    (المسودة، سبب الفشل، هل الفشل تقني) كـwrite_point."""
    sibling_texts = list(sibling_texts or [])
    members = item_members(result, item)
    gap = important_gap.gather(result, item, members, cfg)
    item["gap_sources"] = gap   # أثر للتشخيص ولو فشلت الكتابة
    grounded = article_grounded(members, gap, cfg)
    docs = article._source_docs(grounded)
    if not docs:
        return None, NO_FACTS_REASON, False
    kind = item["kind"]
    sources_text = [d["text"] for d in docs]
    # نص النقطة العضو معروف للجمل غير المسندة إلا في nearest: نقاطها لم تثبت، فجملة تقرّرها تُنبَّه
    claims = [] if kind == "nearest" else [p.get("claim") or "" for p in members]
    texts = sources_text + claims
    # الادّعاء يُقتبس ليُردّ عليه في refuted وحدها؛ لا نص نقطة عضو في verified ولا nearest
    allowed = [t for p in members for t in allowed_quotes(p)] if kind == "refuted" else []
    all_allowed = [t for p in members for t in allowed_quotes(p)]
    exempt = [t for p in members for t in exempt_texts(p)]
    question = result.get("main_story", "")
    attempts = max(1, int(_icfg(cfg).get("article_write_attempts", 3)))
    acfg = cfg.get("article", {}) or {}
    # مقال من 300–450 كلمة يستند إلى بيان رسمي منسوب يتشارك معه تتابعًا أطول من عتبة المنشور القصير (#1304)
    shared_run = int(_icfg(cfg).get("article_max_shared_run_words", acfg.get("max_shared_run_words", 7)))
    wi = _icfg(cfg).get("writer_instructions", {}) or {}
    name_note = names_audit.names_note(texts, cfg)
    base_note = (article_instructions(result, item, members, sibling_texts, cfg)
                 + (f"\n{name_note}\n" if name_note else ""))
    note = base_note
    system_note = wi.get("no_editor_note", "").format(
        editor_tag=acfg.get("editor_tag_phrase", "بحسب معلومات المحرر"),
        opinion_phrase=acfg.get("opinion_attribution_phrase", "وترى الصفحة أن"))
    wcfg = _article_cfg(cfg)
    written, reason, converted = None, "", []
    last = None
    attributed: list[str] = []

    def originality(w: dict) -> str:
        ok, why, _notes = verify_draft.check_originality(
            w["post_body"], "", docs, shared_run,
            allowed_quotes=all_allowed if kind == "refuted" else [], exempt_texts=exempt)
        return "" if ok else f"{REASON_ORIGINALITY}: {why}"

    for attempt in range(attempts):
        got, err = article._draft_article(grounded, [], question, wcfg, avoid_note=note,
                                           system_note=system_note)
        if got is None:
            return None, err, err.startswith(TECHNICAL_PREFIX)
        normalize_statement_title(got, cfg)
        # نقل حرفي منسوب ← اقتباس، قبل الفحوص كلها (#1316)؛ ما لم يُنسب يبقى لفحص الأصالة
        got, attributed = quote_attributed_copies(
            got, [(s_.get("name", ""), s_.get("text", "")) for f in grounded for s_ in f["sources"]], cfg)
        last = got
        reason = check_article(got, sources_text, cfg, allowed) or ""
        if not reason:
            reason = originality(got)
        if not reason:
            written = got
            break
        log.warning("منشور %s رُفض بعد الكتابة (محاولة %d/%d): %s", kind, attempt + 1, attempts, reason)
        note = base_note + "\n" + wi.get("retry_note", "{reason}").format(reason=reason) + "\n"
    check_warns: list[str] = []
    if written is None and last is not None:
        # لا يسقط منشور إلا بلا وقائع أو بعطل تقني (#1304): إصلاح آلي للعنوان والاقتباس، وما بقي تنبيه للمراجع
        written, converted, check_warns = _salvage(last, sources_text, allowed, originality, cfg)
        reason = ""
    item.pop("last_attempt", None)

    publishers = [s_.get("name", "") for f in grounded for s_ in f["sources"]]
    written, latin_warns = arabize_publishers(written, publishers + [g["publisher"] for g in gap], cfg)
    draft = build_article_draft(result, item, members, gap, written, cfg, selection_issue)
    known = " ".join(texts + [g["publisher"] for g in gap] + publishers)
    warns = [w for p in members for w in p.get("warnings") or []]
    warns += unsourced_in(known, written, grounded, question, cfg)
    warns += [REASON_QUOTE_CONVERTED.format(quote=q) for q in converted]
    warns += [_icfg(cfg).get("quote_converted_warning", "").format(start=q) for q in attributed]
    warns += check_warns + latin_warns + relative_time_warnings(written, cfg)
    warns += [WARN_FAILED_CHECK.format(reason=r) for r in length_reasons(written, cfg)]
    warns += off_topic_warnings(written, item.get("pivot_entities") or [], cfg)
    warns += repeat_warnings(written, sibling_texts)
    warns += refutation_warnings(kind, members, written, cfg)
    if warns:
        draft["warnings"] = list(dict.fromkeys(warns))   # للمراجعة فقط: لا تدخل caption ولا تمنع النشر
    names_audit.run(draft, texts, cfg)
    store.save_draft(draft)
    return draft, "", False


def build_article_draft(result: dict, item: dict, members: list[dict], gap: list[dict], written: dict,
                        cfg, selection_issue: int | None) -> dict:
    icfg = _icfg(cfg)
    kind = item["kind"]
    verdict = ARTICLE_VERDICT[kind]
    rows: list[dict] = []
    for p in members:
        rows += ordered_sources(p, cfg)
    rows += [{"publisher": g["publisher"], "link": g["link"], "excerpt": g["excerpt"]} for g in gap]
    uniq: dict[str, dict] = {}
    for r in rows:
        uniq.setdefault(r["publisher"] or r["link"], r)
    rows = list(uniq.values())
    publishers = [r["publisher"] for r in rows if r["publisher"]]
    primary_link = rows[0]["link"] if rows else ""
    title = result.get("main_story") or written["post_title"]

    headlines, hl_error = headlines_mod.headlines_for_post(
        written["post_title"], written["post_body"], cfg, first_question=False,
        system=icfg.get("headline_system") or None)
    if hl_error:
        log.warning("فشلت اقتراحات العناوين لمنشور %s: %s", kind, hl_error)
        headlines = []
    # العنوان الافتراضي دائمًا أول عنوان خبري من القائمة المعروضة نفسها (#1309: عنوان الكاتب كان سؤالًا بلا «؟»
    # في المنشورات الثلاثة)؛ لا مولّد/لا خبري ← يبقى عنوان الكاتب
    first = next((h for h in headlines if h and not _is_question_title(h, cfg)), None)
    if first:
        written["post_title"] = first

    image_urls: list[str] = []
    for p in sorted(members, key=lambda p: not p.get("image_candidates")):
        image_urls += [c["url"] for c in p.get("image_candidates") or []
                       if isinstance(c, dict) and str(c.get("url", "")).startswith(("http://", "https://"))]
    image_urls = list(dict.fromkeys(image_urls))
    related_max = int(cfg.path("collect.related_links_max", 3))
    related = [r for r in rows[1:] if r["link"]][:related_max]
    art = Article(title=title, link=primary_link, summary=title,
                  source_name=publishers[0] if publishers else "", region="global",
                  weight=1.0, published=datetime.now(timezone.utc),
                  publisher=publishers[0] if publishers else "", cluster_sources=publishers)
    draft = {
        "id": _draft_id(item, result["issue"]),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "review_issue": None,
        "origin": DRAFT_ORIGIN,
        # point_id = معرّف العنصر: publish.return_to_selection يجده في article_items (go1)
        "point_id": item["id"],
        "point_ids": list(item["point_ids"]),
        "article_kind": kind,
        "main_story": result.get("main_story", ""),
        "gap_sources": gap,
        "source_issue": result["issue"],
        "selection_issue": selection_issue,
        "verdict": verdict,
        "badge": (icfg.get("badges", {}) or {}).get(verdict, ""),
        "score": 0.0, "bucket": "serious",
        "analysed_sources": publishers,
        "trend_score": 0.0, "velocity": 0.0, "age_hours": 0.0,
        "is_followup": False, "state_media": False,
        "source": {
            "title": title, "link": primary_link,
            "publisher": publishers[0] if publishers else "", "publishers": publishers,
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
        "reel": None,
        "reel_spec": {"headline": written["image_headline"] or written["post_title"],
                      "category": written["category"], "urgent": False,
                      "image_candidates": image_urls},
    }
    if item.get("manual_image"):
        draft["manual_image"] = item["manual_image"]
    return draft
