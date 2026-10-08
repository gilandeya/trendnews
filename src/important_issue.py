"""مسار «هام» — المهمة 2 من 3 (Issue #1217): من الوسم إلى قضية الترشيح (المرحلة 1).

حكم النقاط (src/important.py، لا يُمَسّ) ← قضية ترشيح بوسم important-selection
بجسم المرحلة 1 المشترك (src/stages.py) ← تعليق على الـIssue الأصلي برابطها وجدول.
لا كتابة ولا قراءة اختيارات هنا: وسم approved على قضية الترشيح تنفّذه المهمة 3،
وإلى حينها يعلّق publish.main تعليقًا مؤقتًا ولا يمسّ القضية.

    python -m src.important --issue N
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests

from . import important, review, stages
from .config import load_config

log = logging.getLogger("trendnews.important_issue")

LABEL = "important-selection"


def _icfg(cfg) -> dict:
    return cfg.get("important", {}) or {}


def _is_http(url) -> bool:
    return isinstance(url, str) and urlparse(url).scheme in ("http", "https") \
        and bool(urlparse(url).netloc)


def _link(publisher: str, link: str) -> str:
    return f"[{publisher}]({link})" if link else publisher


def _first_image(p: dict) -> dict | None:
    for c in p.get("image_candidates") or []:
        if isinstance(c, dict) and _is_http(c.get("url")):
            return c
    return None


def display_title(p: dict) -> str:
    """العنوان المعروض: claim، وفي not_found بأقرب حدث عنوان الحدث نفسه."""
    nearest = p.get("nearest")
    if p.get("verdict") == "not_found" and nearest:
        return nearest["title"]
    return p.get("claim") or p.get("text") or ""


def _context_line(p: dict) -> str | None:
    nearest = p.get("nearest")
    if p.get("verdict") == "not_found" and nearest:
        if nearest.get("title") == p.get("text"):
            return None    # أقرب ما وُجد بنصّ النقطة نفسها (مصدر واحد): لا حاجة لتكرارها
        # العنوان صار عنوان الحدث، فالنقطة الأصلية تُحفظ هنا كي لا تضيع
        return f"  ↳ كما ورد عندك: {p.get('text', '')}"
    said = p.get("circulating_context") or p.get("asserted")
    return f"  ↳ كما ورد عندك: {said}" if said else None


def _evidence_lines(p: dict, result: dict, cfg) -> list[str]:
    icfg = _icfg(cfg)
    verdict = p.get("verdict")
    out: list[str] = []
    if verdict == "confirmed":
        cap = int(icfg.get("selection_support_sources", 3))
        rows = [e for e in p.get("evidence") or [] if e.get("stance") == "supports"]
        if not rows:    # ملفات قديمة: التأييد بتصحيح داخل الهامش بقي conflicts_detail
            rows = [e for e in p.get("evidence") or [] if e.get("stance") != "refutes"]
        # الجهة الأصلية أولًا كي لا يقصّها السقف
        rows.sort(key=lambda e: not important._is_primary_source(e.get("link", ""), icfg))
        for e in rows[:cap]:
            tag = " (جهة البيانات الأصلية)" if important._is_primary_source(
                e.get("link", ""), icfg) else ""
            out.append(f"  - {_link(e.get('publisher', ''), e.get('link', ''))}{tag}")
    elif verdict == "inaccurate":
        c = p.get("correction") or {}
        when = c.get("as_of") or (result.get("created_at") or "")[:10]
        out.append(f"  الخطأ: {c.get('error', '')} ← الصحيح: {c.get('correct', '')} ({when})")
        for s in (c.get("sources") or [])[:2]:
            out.append(f"  - {_link(s.get('publisher', ''), s.get('link', ''))}")
    elif verdict == "false":
        for r in p.get("refuted_by") or []:
            label = f" (حكم: {r['verdict_label']})" if r.get("verdict_label") else ""
            checker = " (جهة تدقيق)" if r.get("fact_checker") else ""
            out.append(f"  - كذّبها: {_link(r.get('publisher', ''), r.get('link', ''))}"
                       f"{label}{checker}")
    elif verdict == "not_found":
        nearest = p.get("nearest")
        if nearest:
            if nearest.get("kind") == "single_source":
                first = (nearest.get("sources") or [{}])[0].get("publisher", "")
                out.append("  " + icfg.get("nearest_single_label",
                                            "🔍 أقرب ما وُجد · مصدر واحد: {publisher}").format(publisher=first))
            else:
                out.append("  " + icfg.get("nearest_intersection_label",
                                            "🔍 أقرب ما وُجد · تقاطع {n} مصادر").format(
                                                n=len(nearest.get("sources") or [])))
                out.append("  لا أثر للنقطة كما وردت. الأقرب:")
            if nearest.get("description"):
                out.append(f"  {nearest['description']}")
            for s in nearest.get("sources") or []:
                out.append(f"  - {_link(s.get('publisher', ''), s.get('link', ''))}")
        elif p.get("note"):
            out.append(f"  لم يكتمل التحقق: {p['note']}")
    return out


def _image_lines(p: dict) -> list[str]:
    img = _first_image(p)
    if not img:
        return ["  🖼️ بلا صورة من المصادر · بحث الويب لاحقًا"]
    url = img["url"]
    return [f"  <img src=\"{url}\" width=\"520\" />", "",
            f"  🖼️ [صورة {img.get('publisher') or 'المصدر'}]({url}) · {urlparse(url).netloc}"]


def build_selection_body(result: dict, cfg=None) -> str:
    """جسم قضية الترشيح: رأس المرحلة 1 ← الشرح ← المصدر، ثم لكل نقطة معروضة (بلا مربع
    فوق بياناتها؛ معرّفها يظهر في علامات go: كتلة الانتقال وحدها): العنوان ← الشارة
    والحكم ← السياق ← الأدلة ← الصورة ← حقل رابط الصورة ← الانتقال. الساقطة في
    <details> بلا مربعات."""
    cfg = cfg if cfg is not None else load_config()
    icfg = _icfg(cfg)
    badges = icfg.get("badges", {}) or {}
    names = icfg.get("verdict_names", {}) or {}
    parts = [stages.stage_header(1, cfg), "",
             cfg.path("stages.explainer_stage1", ""), "",
             f"المصدر: نصّك في #{result['issue']}", "", "---", ""]

    offered = [p for p in result["points"] if p.get("status") != "dropped"]
    dropped = [p for p in result["points"] if p.get("status") == "dropped"]
    # ثلاثة أقسام بهذا الترتيب (#1282): ما ثبت (confirmed وinaccurate) · ما كُذِّب · ما لم يُحسم. الترقيم
    # متصل والعلامات (go: والمعرّفات) لا تتغير فلا يتأثر أي قارئ؛ القسم الفارغ لا يُعرض
    titles = icfg.get("section_titles", {}) or {}
    section_of = {"confirmed": "confirmed", "inaccurate": "confirmed", "false": "false",
                  "not_found": "not_found"}
    offered = sorted(offered, key=lambda p: ("confirmed", "false", "not_found").index(
        section_of.get(p["verdict"], "not_found")))
    current = None
    for k, p in enumerate(offered, start=1):
        v = p["verdict"]
        section = section_of.get(v, "not_found")
        if section != current:
            current = section
            if titles.get(section):
                parts += [f"## {titles[section]}", ""]
        title = display_title(p)
        if p.get("returned"):
            # نقطة أعادها المراجع من المرحلة 2/3 (Issue #1221، go1): الشارة أمام العنوان فيعرف
            # أنه رآها وقرّر الرجوع بها، كما يفعل preselect للأخبار
            title = (cfg.path("stages.returned_badge", "↩️ أعدته من المرحلة {stage}")
                     .format(stage=p.get("returned_from_stage") or 2) + f" · {title}")
        if p.get("write_failed"):
            # نقطة فشلت كتابتها فأُعيد عرضها (#1225): إعادة اختيارها تعيد المحاولة
            n = int(_icfg(cfg).get("write_error_chars", 90))
            reason = (p.get("write_error") or "").strip()
            reason = reason if len(reason) <= n else reason[:n].rstrip() + "…"
            title = (_icfg(cfg).get("write_failed_badge", "⚠️ فشلت الكتابة: {reason}")
                     .format(reason=reason) + f" · {title}")
        parts += [f"**{k}. {title}**", "",
                  f"  🏷️ {badges.get(v, '')} · {p.get('icon', '')} {names.get(v, v)}", ""]
        ctx = _context_line(p)
        if ctx:
            parts += [ctx, ""]
        if p.get("superseded_note"):
            # تجاوز زمني بمصدر واحد (#1225): الحكم باقٍ لكن المراجع يُنبَّه قبل اختيار الانتقال
            parts += [f"  > {p['superseded_note']}", ""]
        ev = _evidence_lines(p, result, cfg)
        if ev:
            parts += [*ev, ""]
        for w in p.get("warnings") or []:
            parts += [f"  > {w}", ""]
        parts += [*_image_lines(p), "",
                  stages.image_field(p["id"], cfg), "",
                  *stages.options_block(1, p["id"], cfg, has_stage1=False), "",
                  "---", ""]

    if dropped:
        parts += [f"<details><summary>نقاط سقطت ({len(dropped)})</summary>", ""]
        for p in dropped:
            line = f"- {p.get('text', '')} — {p.get('dropped_reason', '')}"
            if p.get("note"):
                line += f" ({p['note']})"
            parts.append(line)
        parts += ["", "</details>", ""]

    parts.append("<sub>وسم `approved` = تنفيذ ما عُلِّم عليه لكل نقطة · "
                 "إغلاق الـ Issue بلا تعليم = تجاهل الكل بلا أي إنفاق</sub>")
    return "\n".join(parts)


def selection_title(result: dict, cfg=None) -> str:
    cfg = cfg if cfg is not None else load_config()
    n = int(_icfg(cfg).get("selection_title_chars", 50))
    first = next((p for p in result["points"] if p.get("status") != "dropped"), None)
    topic = display_title(first)[:n] if first else ""
    return f"📌 هام — ترشيح من #{result['issue']}: {topic}"


def _issue_open(number: int) -> bool:
    try:
        resp = requests.get(f"{review.API}/repos/{review._repo()}/issues/{number}",
                            headers=review._headers(), timeout=45)
        resp.raise_for_status()
        return resp.json().get("state") == "open"
    except requests.RequestException as exc:
        log.warning("تعذّر قراءة القضية #%s: %s", number, exc)
        return False


def _cell(text: str, n: int = 70) -> str:
    return " ".join((text or "").split())[:n].replace("|", "\\|")


def build_comment(result: dict, selection_issue: int | None, cfg=None, reused: bool = False) -> str:
    cfg = cfg if cfg is not None else load_config()
    names = _icfg(cfg).get("verdict_names", {}) or {}
    offered = [p for p in result["points"] if p.get("status") != "dropped"]
    dropped = [p for p in result["points"] if p.get("status") == "dropped"]
    lines = []
    if selection_issue:
        lines.append(f"{'♻️ حكم محفوظ لنفس النص — ' if reused else ''}📌 قضية الترشيح: "
                     f"#{selection_issue}")
    else:
        lines.append("📌 لا نقاط للترشيح — لم تُفتح قضية.")
    if offered:
        lines += ["", "| النقطة | الحكم |", "|---|---|"]
        lines += [f"| {_cell(display_title(p))} | {p.get('icon', '')} "
                  f"{names.get(p['verdict'], p['verdict'])} |" for p in offered]
    lines += ["", f"سقط: {len(dropped)}"]
    return "\n".join(lines)


def run(issue: int, cfg=None) -> int:
    cfg = cfg if cfg is not None else load_config()
    body = review.fetch_issue_body(issue)
    if not body.strip():
        print("الـ Issue بلا نص")
        return 0

    saved = important.load_saved(issue)
    # إعادة الاستعمال بتساوي بصمة النص ونسخة القواعد معًا (#1282): رفعُ rules_version يعيد الحكم
    reused = bool(saved and not saved.get("error")
                  and saved.get("body_hash") == important.body_hash(body)
                  and saved.get("rules_version") == important.rules_version(cfg))
    if reused:
        log.info("نص #%s لم يتغيّر — يُعاد استعمال الحكم المحفوظ", issue)
        result = saved
    else:
        result = important.judge(body, issue, cfg)
    if result.get("error"):
        review.comment(issue, f"⚠️ {result['error']}")
        return 0

    sel = result.get("selection_issue")
    offered = [p for p in result["points"] if p.get("status") != "dropped"]
    if offered and not (sel and _issue_open(sel)):
        review.ensure_labels()
        created = review.create_issue(selection_title(result, cfg),
                                      build_selection_body(result, cfg), labels=[LABEL])
        sel = created["number"]
        result["selection_issue"] = sel
        for p in offered:
            p["selection_issue"] = sel
        important.save(result)
    review.comment(issue, build_comment(result, sel if offered else None, cfg, reused))
    return 0
