"""تحقّق من مقال ملصق: استخراج ادعاءاته والبحث عنها في مصادر مستقلة.

المرحلة الأولى من مسار التحقق: بحث وتقرير فقط — لا صياغة منشور هنا.
المقال الملصق مصدر إلهام لا معلومة: كل حكم في التقرير مبني على ما وجده
البحث في مصدر مستقل عنه، لا على نصه هو ولا على معرفة النموذج السابقة.

    python -m src.verify --issue 132
"""
from __future__ import annotations

import argparse
import logging

from anthropic import Anthropic, APIError

from . import extract, review
from .config import env, load_config
from .rank import rank
from .request import DEFAULT_LOCALES, norm_tokens, relevant, search_feeds
from .sources import Article, fetch_source, resolve_final_url
from .writer import record_usage, usage_summary

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
سيتولى الإجابة."""

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


def _client() -> Anthropic:
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def extract_claims(article_text: str, cfg, retries: int = 3) -> dict | None:
    vcfg = cfg.get("verify", {}) or {}
    model = vcfg.get("model", "claude-sonnet-5")
    client = _client()

    for attempt in range(1, retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=1500,
                tools=[EXTRACT_SCHEMA],
                tool_choice={"type": "tool", "name": "extract_claims"},
                system=EXTRACT_SYSTEM,
                messages=[{"role": "user", "content": article_text}],
            )
            record_usage(resp, model)
            data = next((b.input for b in resp.content
                        if getattr(b, "type", "") == "tool_use"), None)
            if data is not None:
                return data
        except APIError as exc:
            log.warning("محاولة %d/%d فشلت في استخراج البنية: %s", attempt, retries, exc)
    log.error("تعذّر استخراج بنية المقال")
    return None


# ──────────────────────────── البحث عن الأدلة ────────────────────────────


def search(query: str, cfg, days: int) -> list[Article]:
    """يبحث عن استعلام واحد عبر آلية request.py نفسها — بلا تكرار منطقها."""
    vcfg = cfg.get("verify", {}) or {}
    locales = vcfg.get("locales") or DEFAULT_LOCALES

    articles: list[Article] = []
    for feed in search_feeds(query, days, locales):
        articles += fetch_source(feed, max_age_hours=days * 24)
    if not articles:
        return []

    wanted = norm_tokens(query)
    matched = [a for a in articles if relevant(a, wanted, 1)]
    if not matched:
        return []

    selection = {"max_age_hours": days * 24, "region_diversity": False,
                "title_similarity": 0.62}
    return rank(matched, selection, merge_cfg=cfg)


def gather_evidence(articles: list[Article], cfg) -> list[dict]:
    """يقرأ نصوص أعلى النتائج، متبِّعًا روابط Google News الوسيطة أولًا."""
    vcfg = cfg.get("verify", {}) or {}
    limit = int(vcfg.get("read_per_claim", 3))

    members = []
    for a in articles[: limit * 3]:
        link = a.link
        if "news.google.com" in link:
            link = resolve_final_url(link)
        members.append({"name": a.publisher or a.source_name, "link": link})
    return extract.gather(members, limit=limit)


# ──────────────────────────── الحكم على الوقائع ────────────────────────────

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


def _known_only(names: list[str], docs: list[dict]) -> list[str]:
    """يستبعد أي اسم مصدر لم يُعطَ فعليًا — لا مصدر مختلَق يدخل التقرير."""
    known = {d["name"] for d in docs}
    seen: list[str] = []
    for name in names or []:
        if name in known and name not in seen:
            seen.append(name)
    return seen


def judge_fact(claim_text: str, docs: list[dict], cfg, retries: int = 2) -> dict:
    vcfg = cfg.get("verify", {}) or {}
    model = vcfg.get("model", "claude-sonnet-5")
    client = _client()
    prompt = (f"الادّعاء: {claim_text}\n\n"
             f"نصوص المصادر:\n\n{extract.format_for_prompt(docs)}")

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
                return {
                    "supporting": _known_only(data.get("supporting"), docs),
                    "contradicting": _known_only(data.get("contradicting"), docs),
                }
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
تصغه كحقيقة مطلقة من عندك."""

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
             f"نصوص المصادر:\n\n{extract.format_for_prompt(docs)}")

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
    vcfg = cfg.get("verify", {}) or {}
    days = int(vcfg.get("days", 14))
    max_claims = int(vcfg.get("max_claims", 8))
    max_questions = int(vcfg.get("max_questions", 5))
    min_confirm = int(vcfg.get("min_confirm_sources", 2))

    extracted = extract_claims(body, cfg)
    if not extracted:
        return {"ok": False, "reason": "تعذّر استخراج بنية المقال — حاول مجددًا"}

    claims = extracted.get("claims") or []
    facts = [c for c in claims if c.get("kind") == "واقعة"][:max_claims]
    other_claims = [c for c in claims if c.get("kind") != "واقعة"]
    questions = (extracted.get("questions") or [])[:max_questions]

    fact_results = []
    for claim in facts:
        text = claim.get("text", "")
        ranked = search(text, cfg, days)
        docs = gather_evidence(ranked, cfg) if ranked else []
        judged = (judge_fact(text, docs, cfg) if docs
                 else {"supporting": [], "contradicting": []})
        status = classify_fact(judged["supporting"], judged["contradicting"],
                               min_confirm)
        fact_results.append({
            "text": text,
            "status": status,
            "supporting": judged["supporting"],
            "contradicting": judged["contradicting"],
        })

    question_results = []
    for text in questions:
        ranked = search(text, cfg, days)
        docs = gather_evidence(ranked, cfg) if ranked else []
        judged = (judge_question(text, docs, cfg) if docs
                 else {"answered": False, "answer": "", "source": ""})
        question_results.append({
            "text": text,
            "answered": bool(judged.get("answered")),
            "answer": judged.get("answer", ""),
            "source": judged.get("source", ""),
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
        "topic": extracted.get("topic", ""),
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

    lines += ["#### الوقائع", ""]
    if result["facts"]:
        lines += ["| الواقعة | الحكم | المصادر المؤيدة | المصادر المخالفة |",
                  "|---|---|---|---|"]
        for f in result["facts"]:
            lines.append(
                f"| {f['text']} | {f['status']} | "
                f"{'، '.join(f['supporting']) or '—'} | "
                f"{'، '.join(f['contradicting']) or '—'} |"
            )
    else:
        lines.append("لم يستخرج من المقال أي واقعة قابلة للتحقق.")
    lines.append("")

    lines += ["#### الأسئلة المطروحة", ""]
    if result["questions"]:
        for q in result["questions"]:
            if q["answered"]:
                lines.append(f"- **{q['text']}** — {q['answer']} (بحسب {q['source']})")
            else:
                lines.append(f"- **{q['text']}** — لم توجد إجابة في المصادر المستقلة")
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
