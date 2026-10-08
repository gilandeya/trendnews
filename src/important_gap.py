"""مسار «هام» — البحث المكمِّل لمنشور الخبر الرئيسي (Issue #1293، B2).

يجري عند الكتابة لا عند الحكم، لكل منشور مختار: نداء Haiku واحد يستخرج أسئلة القارئ التي لم تجب عنها
أدلة النقاط الأعضاء، ثم بحث بآلة النقطة نفسها (important._PointSearch: Google ثم Brave web، والذاكرة
كما هي). مصادرنا وحدها (important._is_our_source) وما عداها يُرمى؛ المقتطف من clean_page_text
وselect_excerpt على نص السؤال. السقوف من important.gap: وثائق المنشور وطلبات Brave له، وعدّاد Brave
الشهري القائم يبقى السقف الأعلى. أي عطل هنا يعيد قائمة فارغة ولا يوقف الكتابة.
"""
from __future__ import annotations

import logging

from . import article, evidence, important

log = logging.getLogger("trendnews.important_gap")

GAP_SCHEMA = {
    "name": "report_gap_questions",
    "description": "أسئلة القارئ التي لم تجب عنها الأدلة المعطاة، بعبارتي بحث",
    "input_schema": {
        "type": "object",
        "properties": {"questions": {"type": "array", "items": {
            "type": "object",
            "properties": {"question": {"type": "string"},
                           "query_ar": {"type": "string"},
                           "query_en": {"type": "string"}},
            "required": ["question", "query_ar"]}}},
        "required": ["questions"],
    },
}


def _gcfg(cfg) -> dict:
    return (cfg.get("important", {}) or {}).get("gap", {}) or {}


def _cut(text, words: int) -> str:
    return " ".join(str(text or "").split()[:words])


def _member_block(member: dict, rows: list[dict]) -> str:
    said = member.get("claim") or member.get("text", "")
    ev = " | ".join(f"{r.get('publisher', '')}: {r.get('excerpt', '')[:200]}" for r in rows[:3])
    return f"- [{member.get('verdict', '')}] {said}" + (f" ← {ev}" if ev else "")


def gap_questions(result: dict, item: dict, members: list[dict], cfg) -> list[dict]:
    """[{question, query_ar, query_en}] حتى max_questions، وعبارة كل لغة ≤ query_max_words كلمات
    (الحد يُفرض هنا لا بالثقة بطاعة النموذج: كل عبارة طلب Brave محتمل). فشل النداء ← []."""
    from . import important_write
    g = _gcfg(cfg)
    n_max = int(g.get("max_questions", 4))
    words = int(g.get("query_max_words", 8))
    system = g.get("system", "").format(max_questions=n_max, query_max_words=words)
    if item.get("kind") == "nearest":
        system += "\n" + g.get("nearest_note", "")
    content = (f"الخبر الرئيسي: {result.get('main_story', '')}\nنوع المنشور: {item.get('kind', '')}\n"
               "النقاط الأعضاء:\n" + "\n".join(
                   _member_block(m, important_write.ordered_sources(m, cfg)) for m in members))
    data, err = article._ask_model_with_retry(
        article._client(), g.get("model", "claude-haiku-4-5-20251001"),
        tools=[GAP_SCHEMA], tool_choice={"type": "tool", "name": "report_gap_questions"},
        system=system, messages=[{"role": "user", "content": content}],
        max_tokens=int(g.get("max_tokens", 1200)), cap=int(g.get("max_tokens_cap", 2400)),
        warn_label="أسئلة البحث المكمِّل",
        truncation_message="أسئلة البحث المكمِّل مقطوعة — important.gap.max_tokens غير كافٍ")
    if not data or not isinstance(data.get("questions"), list):
        log.warning("تعذّرت أسئلة البحث المكمِّل: %s", err)
        return []
    out: list[dict] = []
    for q in data["questions"]:
        if not isinstance(q, dict):
            continue
        question = " ".join(str(q.get("question") or "").split())
        ar, en = _cut(q.get("query_ar"), words), _cut(q.get("query_en"), words)
        if question and (ar or en):
            out.append({"question": question, "query_ar": ar, "query_en": en})
    return out[:n_max]


def search_gap(questions: list[dict], cfg) -> list[dict]:
    """[{publisher, link, excerpt, question}] من مصادرنا وحدها، حتى max_docs. _PointSearch جديد لكل منشور
    فعدّاد طلبات Brave (search.brave) له وحده؛ ضربة ذاكرة لا تُحسب طلبًا. بلوغ العدّاد الشهري يمنع
    الطلب داخل brave_web_articles نفسها فيبقى Google وحده."""
    g = _gcfg(cfg)
    icfg = cfg.get("important", {}) or {}
    max_docs, max_brave = int(g.get("max_docs", 8)), int(g.get("max_brave", 4))
    search = important._PointSearch(cfg, "")
    out: list[dict] = []
    seen: set[str] = set()

    def add(docs: list[dict], q: dict) -> None:
        f = {"text": q["question"], "entities": [], "numbers": [], "dates": []}
        for d in docs:
            if len(out) >= max_docs:
                return
            link, _resolved = search.resolve_link(d.get("link") or "")
            name = d.get("name", "")
            if (not link or link in seen or important._is_excluded_domain(link, icfg)
                    or not important._is_our_source(name, link, cfg)):
                continue
            excerpt = important.select_excerpt(important.clean_page_text(d.get("text", ""), icfg), f, icfg)
            if not excerpt.strip():
                continue
            seen.add(link)
            out.append({"publisher": name, "link": link, "excerpt": excerpt, "question": q["question"]})

    for q in questions:
        for phrase in dict.fromkeys(p for p in (q.get("query_ar"), q.get("query_en")) if p):
            if len(out) >= max_docs:
                return out
            _ranked, kept, _dropped = search.run(phrase, q["question"], False, search.days, None)
            add(evidence.readable_only(kept), q)
            if search.brave["requests"] < max_brave and len(out) < max_docs:
                _arts, bdocs, _dropped = search.run_brave(phrase, q["question"], None)
                add(evidence.readable_only(bdocs), q)
    return out


def gather(result: dict, item: dict, members: list[dict], cfg) -> list[dict]:
    """نقطة الدخول: أسئلة ثم بحث. أي عطل ← [] وتحذير؛ الكاتب يكتب بأدلة النقاط وحدها."""
    try:
        questions = gap_questions(result, item, members, cfg)
        return search_gap(questions, cfg) if questions else []
    except Exception:  # noqa: BLE001 — البحث المكمِّل مساعد: لا يُسقط كتابة المنشور
        log.exception("تعذّر البحث المكمِّل لمنشور %s", item.get("kind"))
        return []
