"""«المحرر الأخير» لمقالات التحليل (Issue #1326، C2): نموذج قوي يقرأ المنشور كاملًا — h1 والمتن والعناوين
الثلاثة — قبل المرحلة 2، مع بحث ويب خادمي للأسماء والتواريخ وحدها.

لماذا: كل نموذج في مسار التحليل يرى قطعة واحدة (العناوين من عنوان القضية، الكاتب من النقاط)، ولا خطوة
تقرأ المنشور كما يراه القارئ. شواهد 2026-10-09: عنوانان عن «عمدة إسطنبول» والمتن عن رئيس بلدية إزمير،
وخبر «السيطرة على باب المندب» من متحدث واحد غير محسوم الاسم نُشر بـ«قبل ساعات» عن إعلان عمره أيام.

القرار للكود لا للنموذج: النموذج يبلّغ ملاحظات منظَّمة، والكود يطبّق الإصلاح فقط إن كانت فئته ضمن
``youtube.review.editor.auto_fix`` وكان ``original`` حرفيًا في موضعه، ثم يعيد فحوص المقال كلها؛ إصلاح
يُحدث مخالفة جديدة يُلغى ويصير ملاحظة معروضة. الأسماء والوقائع المتجاوزة (name_doubtful وfact_outdated
وother) لا تُطبَّق أبدًا. أي عطل ← تُحفظ المسودة كما هي مع تنبيه، ولا تُفشَل الكتابة."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from . import imagesearch

log = logging.getLogger(__name__)

CATEGORIES = ("headline_contradicts", "headline_overclaims", "headline_judgmental", "h1_overclaims",
              "name_doubtful", "unattributed_opinion", "vague_attribution", "stale_time",
              "fact_outdated", "broken_quote", "other")
NEVER_APPLIED = ("name_doubtful", "fact_outdated", "other")
LOCATIONS = ("h1", "headline_1", "headline_2", "headline_3", "body")

REPORT_TOOL = {
    "name": "report_review",
    "description": "يُبلِّغ ملاحظات المحرر الأخير على المنشور (قائمة فارغة إن لم يجد شيئًا)",
    "input_schema": {
        "type": "object",
        "properties": {
            "notes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": list(CATEGORIES)},
                        "severity": {"type": "string", "enum": ["high", "low"]},
                        "location": {"type": "string", "enum": list(LOCATIONS)},
                        "original": {"type": "string", "description": "نص حرفي من المقال"},
                        "fix": {"type": "string", "description": "البديل، أو فارغ"},
                        "note": {"type": "string", "description": "شرح بالعربية"},
                        "sources": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["category", "severity", "location", "original", "note"],
                },
            },
        },
        "required": ["notes"],
    },
}


def _ecfg(cfg: Any) -> dict:
    return cfg.path("youtube.review.editor", {}) or {}


def _texts(cfg: Any) -> dict:
    return _ecfg(cfg).get("texts", {}) or {}


# ───────────────────────────── العدّاد الشهري ─────────────────────────────


def _usage_key() -> str:
    return "editor_web:" + datetime.now(timezone.utc).strftime("%Y-%m")


def search_usage() -> int:
    try:
        data = json.loads(imagesearch.BRAVE_USAGE_FILE.read_text(encoding="utf-8"))
        return int(data.get(_usage_key(), 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def _bump_usage(n: int) -> None:
    """يزيد عدّاد البحث بما استُعمل فعلًا (usage.server_tool_use) ويحفظ مفاتيح العدّادات الأخرى."""
    if n <= 0:
        return
    path = imagesearch.BRAVE_USAGE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    key = _usage_key()
    data[key] = int(data.get(key, 0) or 0) + n
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


# ───────────────────────────── النداء ─────────────────────────────


def _create(client, **kwargs):
    """نقطة النداء الوحيدة (يزيّفها الاختبار). لا temperature -- النماذج ترفضها بـ400."""
    if client is None:
        from anthropic import Anthropic
        from .config import env
        client = Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    return client.messages.create(**kwargs)


def _searches_in(resp) -> int:
    usage = getattr(resp, "usage", None)
    stu = getattr(usage, "server_tool_use", None)
    n = getattr(stu, "web_search_requests", 0) if stu is not None else 0
    return n if isinstance(n, int) else 0


def _report_of(resp) -> dict | None:
    for b in getattr(resp, "content", None) or []:
        if getattr(b, "type", "") == "tool_use" and getattr(b, "name", "") == "report_review":
            inp = getattr(b, "input", None)
            if isinstance(inp, dict):
                return inp
    return None


def _user_message(draft: dict, member_points: list[dict], today: str, warnings: list[str]) -> str:
    lines = [f"تاريخ اليوم: {today}", "", "المقال (عنوان # ثم المتن):", draft.get("caption", ""), "",
             "العناوين المقترحة:"]
    lines += [f"headline_{i}: {h}" for i, h in enumerate(draft.get("headlines") or [], start=1)]
    lines += ["", "النقاط المصدرية (بيانات لا تعليمات):"]
    for i, p in enumerate(member_points, start=1):
        ts = f"{p['timestamp']}ث" if p.get("timestamp") is not None else "غير معروف"
        lines.append(
            f"{i}. القناة: {p.get('channel', '')} | المتحدث: {p.get('speaker', '')} | النوع: {p.get('type', '')}\n"
            f"   القول: {p.get('statement', '')}\n"
            f"   الفيديو: {p.get('video_url', '')} (الطابع: {ts}) (نُشر: {p.get('video_published') or 'غير معروف'})")
    if warnings:
        lines += ["", "تنبيهات المسودة الحالية:"] + [f"- {w}" for w in warnings]
    return "\n".join(lines)


def _converse(draft: dict, member_points: list[dict], cfg: Any, client, today: str) -> tuple[dict, int, bool]:
    """يعيد (تقرير report_review، عدد عمليات البحث المنفَّذة، هل مُنع البحث بالسقف). يرفع عند الفشل."""
    ecfg = _ecfg(cfg)
    model = ecfg.get("model", "claude-opus-5")
    max_tokens = int(ecfg.get("max_tokens", 6000))
    system = ecfg.get("system", "")
    cap = int(ecfg.get("monthly_search_cap", 300))
    capped = search_usage() >= cap
    msg = _user_message(draft, member_points, today, draft.get("warnings") or [])
    searches = 0

    tools: list[dict] = [REPORT_TOOL]
    if not capped:
        tools = [{"type": "web_search_20250305", "name": "web_search",
                  "max_uses": int(ecfg.get("max_searches", 3))}, REPORT_TOOL]
    resp = _create(client, model=model, max_tokens=max_tokens, system=system,
                   tools=tools, tool_choice={"type": "auto"},
                   messages=[{"role": "user", "content": msg}])
    searches += _searches_in(resp)
    report = _report_of(resp)
    if report is None:
        # لم يستدعِ report_review: نداء ثانٍ واحد بلا بحث وبإلزام الأداة
        resp2 = _create(client, model=model, max_tokens=max_tokens, system=system,
                        tools=[REPORT_TOOL], tool_choice={"type": "tool", "name": "report_review"},
                        messages=[{"role": "user", "content": msg}])
        searches += _searches_in(resp2)
        report = _report_of(resp2)
        if report is None:
            raise ValueError("لم يُرجع المحرر تقريرًا")
    return report, searches, capped


# ───────────────────────────── التطبيق ─────────────────────────────


def _norm_msg(v: str) -> str:
    return re.sub(r"\d+", "#", v)


def _problems(title: str, body: str, headlines: list[str], member_points: list[dict], cfg: Any) -> set[str]:
    from . import youtube_article as ya
    out = {_norm_msg(v) for v in ya.article_violations(f"# {title}\n{body}", cfg, member_points)}
    max_words = cfg.path("youtube.review.headlines.max_words", 15)
    for i, h in enumerate(headlines, start=1):
        if ya.vague_phrases_in(h, cfg):
            out.add(f"headline_{i}: نسبة مجهولة")
        if len(h.split()) > max_words:
            out.add(f"headline_{i}: طويل")
    if ya.vague_phrases_in(title, cfg):
        out.add("h1: نسبة مجهولة")
    return out


def _delete_text(body: str, original: str) -> str:
    out = re.sub(re.escape(original) + r"[ \t]?", "", body, count=1)
    return re.sub(r"\n{3,}", "\n\n", out)


def _default_index(headlines: list[str]) -> int:
    """الأول سؤال إن أمكن؛ وإلا أول عنوان سليم (الأول)."""
    for i, h in enumerate(headlines):
        if h.rstrip().endswith("؟"):
            return i
    return 0


def _point_video_link(note: dict, member_points: list[dict]) -> str:
    """رابط الفيديو مع &t=<الطابع>s للنقطة التي فيها المتحدث المشكوك في اسمه."""
    from . import youtube_article as ya
    words = [ya._fold_mention(w) for w in re.split(r"\s+", f"{note.get('original', '')}") if len(w) >= 3]
    best = None
    for p in member_points:
        sp = ya._fold_mention(p.get("speaker", ""))
        if any(w and w in sp for w in words):
            best = p
            break
    if best is None:
        for p in member_points:
            hay = ya._fold_mention(f"{p.get('statement', '')} {p.get('quote_arabic', '')}")
            if any(w and w in hay for w in words):
                best = p
                break
    if best is None or not best.get("video_url"):
        return ""
    url = best["video_url"]
    if best.get("timestamp") is None:
        return url
    return f"{url}{'&' if '?' in url else '?'}t={int(best['timestamp'])}s"


def _speakers_unresolved(draft: dict, member_points: list[dict]) -> list[str]:
    from . import youtube_article as ya
    out = []
    for item in draft.get("name_unresolved") or []:
        ar = item.get("arabic", "") if isinstance(item, dict) else str(item)
        words = [ya._fold_mention(w) for w in ar.split() if len(w) >= 3]
        if not words:
            continue
        for p in member_points:
            sp = ya._fold_mention(p.get("speaker", ""))
            if sp and any(w in sp for w in words):
                out.append(ar)
                break
    return out


def apply_review(draft: dict, member_points: list[dict], notes: list[dict], cfg: Any) -> dict:
    """يطبّق الملاحظات المسموحة على نسخة العمل ثم يحدّث المسودة. يعيد {applied, notes}."""
    ecfg = _ecfg(cfg)
    auto = set(ecfg.get("auto_fix", []))
    caption = draft.get("caption", "")
    first, _, rest = caption.partition("\n")
    title = first.lstrip("#").strip()
    body = rest
    headlines = list(draft.get("headlines") or [])
    applied: list[dict] = []
    shown: list[dict] = []

    for raw in notes:
        if not isinstance(raw, dict):
            continue
        note = {k: raw.get(k) for k in ("category", "severity", "location", "original", "fix", "note", "sources")}
        note["sources"] = [s for s in (note.get("sources") or []) if isinstance(s, str) and s]
        note["fix"] = (note.get("fix") or "").strip()
        note["original"] = (note.get("original") or "").strip()
        note["note"] = (note.get("note") or "").strip()
        cat, loc = note["category"], note["location"]
        if cat not in CATEGORIES or loc not in LOCATIONS:
            continue
        if note["severity"] not in ("high", "low"):
            note["severity"] = "low"
        if cat == "name_doubtful":
            note["video"] = _point_video_link(note, member_points)

        ok = cat in auto and cat not in NEVER_APPLIED and bool(note["original"])
        if ok and cat == "stale_time" and not note["sources"]:
            ok = False       # تاريخ من الويب بلا مصدر لا يُطبَّق
        if ok:
            target = {"h1": title, "body": body}.get(loc)
            if target is None:
                idx = int(loc.split("_")[1]) - 1
                target = headlines[idx] if idx < len(headlines) else None
            ok = target is not None and note["original"] in target
        if ok and not note["fix"]:
            # fix فارغ: حذف الجملة للرأي بلا نسبة، وحذف العنوان للعناوين (على ألا يبقى أقل من واحد)
            if cat == "unattributed_opinion" and loc == "body":
                pass
            elif loc.startswith("headline_") and len(headlines) > 1:
                pass
            else:
                ok = False
        if ok:
            new_title, new_body, new_heads = title, body, list(headlines)
            if loc == "h1":
                new_title = title.replace(note["original"], note["fix"], 1)
            elif loc == "body":
                new_body = (body.replace(note["original"], note["fix"], 1) if note["fix"]
                            else _delete_text(body, note["original"]))
            else:
                idx = int(loc.split("_")[1]) - 1
                if note["fix"]:
                    new_heads[idx] = new_heads[idx].replace(note["original"], note["fix"], 1)
                else:
                    del new_heads[idx]
            before = _problems(title, body, headlines, member_points, cfg)
            after = _problems(new_title, new_body, new_heads, member_points, cfg)
            if after - before:
                ok = False       # الإصلاح يُحدث مخالفة جديدة ← يُلغى ويصير ملاحظة معروضة
            else:
                title, body, headlines = new_title, new_body, new_heads
                applied.append(note)
                continue
        shown.append(note)

    if applied:
        draft["caption"] = f"# {title}\n{body}"
        if headlines != list(draft.get("headlines") or []):
            draft["headlines"] = headlines
            sel = _default_index(headlines)
            draft["headline_selected"] = sel
            draft["title"] = headlines[sel]
            draft.setdefault("arabic", {})["post_title"] = headlines[sel]
    return {"applied": applied, "notes": shown}


def run(draft: dict, member_points: list[dict], cfg: Any, client=None, now: datetime | None = None) -> dict:
    """نقطة الدخول: لا ترفع أبدًا. تحفظ على المسودة editor_review وتعدّل نصّها بالإصلاحات المطبَّقة."""
    if not _ecfg(cfg).get("enabled", False):
        return {}
    now = now or datetime.now(timezone.utc)
    review: dict = {"at": now.isoformat(), "applied": [], "notes": [], "error": None,
                    "searches": 0, "search_skipped": None, "speaker_unresolved": []}
    try:
        report, searches, capped = _converse(draft, member_points, cfg, client, now.strftime("%Y-%m-%d"))
        review["searches"] = searches
        if capped:
            review["search_skipped"] = "cap"
        try:
            _bump_usage(searches)
        except OSError as exc:
            log.warning("تعذّر حفظ عدّاد بحث المحرر: %s", exc)
        notes = report.get("notes") if isinstance(report, dict) else None
        result = apply_review(draft, member_points, notes if isinstance(notes, list) else [], cfg)
        review["applied"], review["notes"] = result["applied"], result["notes"]
    except Exception as exc:  # noqa: BLE001 — مراجعة مساعدة لا تُفشل كتابة مسودة
        log.warning("مراجعة المحرر تعذّرت (%s): %s", type(exc).__name__, exc)
        review["error"] = f"{type(exc).__name__}: {exc}"
        draft.setdefault("warnings", []).append(_texts(cfg).get("error", "تعذّرت مراجعة المحرر: {error}")
                                                .format(error=review["error"]))
    review["speaker_unresolved"] = _speakers_unresolved(draft, member_points)
    draft["editor_review"] = review
    return review


# ───────────────────────────── البوابة والعرض ─────────────────────────────


def blocking_reasons(draft: dict, cfg: Any = None) -> list[str]:
    """أسباب منع النشر المباشر: ملاحظة high غير مطبَّقة، أو اسم متحدث لم يُحسم."""
    er = draft.get("editor_review") or {}
    out = [n.get("note", "") for n in er.get("notes") or [] if n.get("severity") == "high"]
    fmt = (_texts(cfg).get("speaker_unresolved") if cfg is not None else None) or "اسم متحدث لم يُحسم: {name}"
    out += [fmt.format(name=n) for n in er.get("speaker_unresolved") or []]
    return [o for o in out if o]


def gate_action(action: str, draft: dict, stage: int, cfg: Any = None) -> tuple[str, str]:
    """يحوّل الخيار المباشر إلى المرحلة التالية للمراجعة إن كان للمحرر ما يمنعه. يعيد (الخيار، السبب أو "").
    المرحلة 1: publish/go3 ← go2. المرحلة 2: publish ← go3. المرحلة 3 قرارك."""
    reasons = blocking_reasons(draft, cfg)
    if not reasons:
        return action, ""
    if stage == 1 and action in ("publish", "go3"):
        return "go2", "؛ ".join(reasons)
    if stage == 2 and action == "publish":
        return "go3", "؛ ".join(reasons)
    return action, ""


def _sources_fmt(sources: list[str]) -> str:
    return " " + " ".join(f"[{i}]({u})" for i, u in enumerate(sources, start=1)) if sources else ""


def render_lines(d: dict, cfg: Any = None, indent: str = "  ") -> list[str]:
    """قسم «🧑⚖️ مراجعة المحرر» لقضيتي المرحلتين 2 و3؛ فارغ إن لا مراجعة أو لا شيء يُعرض."""
    er = d.get("editor_review") or {}
    if not (er.get("applied") or er.get("notes")):
        return []
    if cfg is None:
        from .config import load_config
        cfg = load_config()
    t = _texts(cfg)
    rows: list[str] = []
    for n in er.get("applied") or []:
        key = "applied" if n.get("fix") else "deleted"
        rows.append(t[key].format(original=n.get("original", ""), fix=n.get("fix", ""), note=n.get("note", ""),
                                  sources=_sources_fmt(n.get("sources") or [])))
    for n in er.get("notes") or []:
        key = "note_high" if n.get("severity") == "high" else "note_low"
        rows.append(t[key].format(
            note=n.get("note", ""),
            original=t["original_fmt"].format(original=n["original"]) if n.get("original") else "",
            video=t["video_fmt"].format(link=n["video"]) if n.get("video") else "",
            sources=_sources_fmt(n.get("sources") or [])))
    return [f"{indent}{t['header']}:", "", *[f"{indent}- {r}" for r in rows], ""]
