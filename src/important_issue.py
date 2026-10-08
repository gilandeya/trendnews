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

from . import important, important_write, review, stages
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
    out += _provenance_lines(p, icfg)
    return out


def _provenance_lines(p: dict, icfg) -> list[str]:
    """سطر نسبة التأييد تحت الحكم (#1288) وسطر الوثائق المستبعدة من خارج مصادرنا؛ نصوصها من الإعداد."""
    out: list[str] = []
    level = p.get("support_level")
    labels = icfg.get("support_labels", {}) or {}
    if p.get("verdict") in ("confirmed", "inaccurate") and level in labels:
        if p["verdict"] == "confirmed":
            names = [e.get("publisher", "") for e in p.get("evidence") or [] if e.get("stance") == "supports"]
        else:
            names = [s.get("publisher", "") for s in (p.get("correction") or {}).get("sources") or []]
        publisher = p.get("support_publisher") or (names[0] if names else "")
        out.append("  " + labels[level].format(publisher=publisher,
                                               names="، ".join(dict.fromkeys(n for n in names if n))))
    n = int(p.get("outside_docs") or 0)
    if n > 0 and icfg.get("outside_docs_label"):
        out.append("  " + icfg["outside_docs_label"].format(n=n))
    return out


def _image_lines(p: dict) -> list[str]:
    img = _first_image(p)
    if not img:
        return ["  🖼️ بلا صورة من المصادر · بحث الويب لاحقًا"]
    url = img["url"]
    return [f"  <img src=\"{url}\" width=\"520\" />", "",
            f"  🖼️ [صورة {img.get('publisher') or 'المصدر'}]({url}) · {urlparse(url).netloc}"]


def item_title(item: dict, cfg) -> str:
    return (_icfg(cfg).get("article_titles", {}) or {}).get(item.get("kind"), item.get("kind", ""))


def _member_line(p: dict, cfg) -> str:
    names = list(dict.fromkeys(r["publisher"] for r in important_write.ordered_sources(p, cfg)
                               if r.get("publisher")))
    tail = f" — {'، '.join(names)}" if names else ""
    return f"- {p.get('icon', '')} {p.get('claim') or p.get('text', '')}{tail}"


def build_items_body(result: dict, cfg) -> str:
    """جسم قضية الترشيح بثلاثة منشورات (#1293، B2): سطر الخبر الرئيسي ← لكل عنصر (verified ثم nearest ثم
    refuted): عنوانه ← سطر لكل نقطة عضو ← صورة أول عضو له صورة ← حقل الرابط ← الانتقال بمعرّف العنصر. لا علامة
    go: لنقطة منفردة. ثم «خارج الموضوع الرئيسي» و«نقاط لم تدخل أي منشور» (call_error بسببها)."""
    icfg = _icfg(cfg)
    by_id = {p["id"]: p for p in result["points"]}
    parts = [stages.stage_header(1, cfg), "",
             cfg.path("stages.explainer_stage1", ""), "",
             f"المصدر: نصّك في #{result['issue']}", ""]
    if result.get("main_story"):
        parts += [icfg.get("main_story_label", "📌 الخبر الرئيسي: {main_story}").format(
            main_story=result["main_story"]), ""]
    parts += ["---", ""]
    for item in result.get("article_items") or []:
        if item.get("status") not in (None, "offered", "selected"):
            continue
        members = [by_id[i] for i in item["point_ids"] if i in by_id]
        title = item_title(item, cfg)
        if item.get("returned"):
            title = (cfg.path("stages.returned_badge", "↩️ أعدته من المرحلة {stage}")
                     .format(stage=item.get("returned_from_stage") or 2) + f" · {title}")
        if item.get("write_failed"):
            n = int(icfg.get("write_error_chars", 90))
            reason = (item.get("write_error") or "").strip()
            reason = reason if len(reason) <= n else reason[:n].rstrip() + "…"
            title = icfg.get("write_failed_badge", "⚠️ فشلت الكتابة: {reason}").format(reason=reason) \
                + f" · {title}"
        parts += [f"**{title}**", ""]
        for p in members:
            parts.append(_member_line(p, cfg))
            if p.get("superseded_note"):
                # تنبيه التجاوز الزمني (#1225) يبقى بارزًا تحت نقطته كي لا يضيع في العرض الجديد
                parts.append(f"  > {p['superseded_note']}")
        parts.append("")
        first = next((p for p in members if _first_image(p)), None)
        parts += [*_image_lines(first or {}), "",
                  stages.image_field(item["id"], cfg), "",
                  *stages.options_block(1, item["id"], cfg, has_stage1=False), "",
                  "---", ""]

    covered = {i for ids in (result.get("articles") or {}).values() for i in ids}
    uncovered = [p for p in result["points"] if p["id"] not in covered]
    if uncovered:
        parts += [f"<details><summary>{icfg.get('uncovered_title', 'نقاط لم تدخل أي منشور ({n})').format(n=len(uncovered))}"
                  "</summary>", ""]
        for p in uncovered:
            reason = p.get("call_error") or p.get("dropped_reason") or p.get("note") or ""
            parts.append(f"- {p.get('text', '')}" + (f" — {reason}" if reason else ""))
        parts += ["", "</details>", ""]
    off_topic = result.get("off_topic") or []
    if off_topic:
        parts += [f"<details><summary>{icfg.get('off_topic_title', 'خارج الموضوع الرئيسي ({n})').format(n=len(off_topic))}"
                  "</summary>", ""]
        parts += [f"- {o.get('text', '')}" for o in off_topic]
        parts += ["", "</details>", ""]
    parts.append(f"<sub>{icfg.get('selection_footer_items', 'وسم `approved` = تنفيذ ما عُلِّم عليه لكل منشور')}</sub>")
    return "\n".join(parts)


def build_selection_body(result: dict, cfg=None) -> str:
    """نتيجة فيها خطة articles (B1 فما بعد) ← ثلاثة منشورات؛ ملف أقدم بلا خطة ← عرض النقاط القديم
    (قضية فُتحت قبل #1293 تُقرأ وتُكتب بمساره أيضًا، انظر important_finalize)."""
    cfg = cfg if cfg is not None else load_config()
    if "articles" in result:
        important.ensure_article_items(result)
        return build_items_body(result, cfg)
    return build_points_body(result, cfg)


def build_points_body(result: dict, cfg=None) -> str:
    """جسم قضية الترشيح القديم: رأس المرحلة 1 ← الشرح ← المصدر، ثم لكل نقطة معروضة (بلا مربع
    فوق بياناتها؛ معرّفها يظهر في علامات go: كتلة الانتقال وحدها): العنوان ← الشارة
    والحكم ← السياق ← الأدلة ← الصورة ← حقل رابط الصورة ← الانتقال. الساقطة في
    <details> بلا مربعات."""
    cfg = cfg if cfg is not None else load_config()
    icfg = _icfg(cfg)
    badges = icfg.get("badges", {}) or {}
    names = icfg.get("verdict_names", {}) or {}
    parts = [stages.stage_header(1, cfg), "",
             cfg.path("stages.explainer_stage1", ""), "",
             f"المصدر: نصّك في #{result['issue']}", ""]
    if result.get("main_story"):
        # الخبر الرئيسي (#1291): عرض فقط؛ ملفات قديمة بلا الحقل لا سطر لها
        parts += [icfg.get("main_story_label", "📌 الخبر الرئيسي: {main_story}").format(
            main_story=result["main_story"]), ""]
    parts += ["---", ""]

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

    off_topic = result.get("off_topic") or []
    if off_topic:
        # نقاط خارج الخبر الرئيسي (#1291): لا حكم لها ولا علامات — قائمة نصوص للعلم
        parts += [f"<details><summary>{icfg.get('off_topic_title', 'خارج الموضوع الرئيسي ({n})').format(n=len(off_topic))}"
                  "</summary>", ""]
        parts += [f"- {o.get('text', '')}" for o in off_topic]
        parts += ["", "</details>", ""]

    parts.append("<sub>وسم `approved` = تنفيذ ما عُلِّم عليه لكل نقطة · "
                 "إغلاق الـ Issue بلا تعليم = تجاهل الكل بلا أي إنفاق</sub>")
    return "\n".join(parts)


def selection_title(result: dict, cfg=None) -> str:
    cfg = cfg if cfg is not None else load_config()
    n = int(_icfg(cfg).get("selection_title_chars", 50))
    if "articles" in result and result.get("main_story"):
        return f"📌 هام — ترشيح من #{result['issue']}: {result['main_story'][:n]}"
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
    items = important.ensure_article_items(result) if "articles" in result else []
    if (items or offered) and not (sel and _issue_open(sel)):
        review.ensure_labels()
        created = review.create_issue(selection_title(result, cfg),
                                      build_selection_body(result, cfg), labels=[LABEL])
        sel = created["number"]
        result["selection_issue"] = sel
        # العناصر وحدها تحمل رقم القضية في العرض الجديد؛ النقاط المنفردة لا قضية لها (#1293)
        for entry in (items if items else offered):
            entry["selection_issue"] = sel
        important.save(result)
    review.comment(issue, build_comment(result, sel if (items or offered) else None, cfg, reused))
    return 0
