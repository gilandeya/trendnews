"""مسار «هام» — المهمة 3 من 3 (Issue #1221): قراءة اختيارات المرحلة 1 والكتابة بحسب الحكم.

يُستدعى من publish.main حين يحمل Issue الموسوم `approved` وسم `important-selection` (يحلّ محل
التعليق المؤقت للمهمة 2). القراءة بالقارئ الموحَّد stages.read_actions(body, 1) بقاعدة
الأحوط كما للأخبار: go2 ← قضية مرحلة 2، go3 ← بطاقة وقضية مرحلة 3، publish ← بطاقة ونشر
بالفاصل (cmd_burst)، وكلها بعد الكتابة (src/important_write.py). ما بلا تعليم «لم يُختر».
ما بعد الكتابة هو collect_finalize.dispatch_written نفسه الذي تسلكه الأخبار، فلا مسار ثانٍ.

حالة النقطة في state/important/N.json: offered ← selected (عُلِّم) ← written (كُتبت مسودتها،
`draft_id`) أو unselected. فشل الكتابة يترك selected و`write_error` فتُعاد المحاولة بإعادة
وسم approved. القرارات في decisions بأصل `important` وselection_issue كالأخبار.

go1 من المرحلة 2/3: publish.return_to_selection ← reopen_selection أدناه تفتح قضية ترشيح
جديدة للنص نفسه من الملف المحفوظ بلا حكم جديد، والمعادة في أعلاها بشارة «↩️ أعدته من المرحلة N».
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from . import (cards, collect_finalize, decisions, important, important_issue, important_write,
               review, stages, store)

log = logging.getLogger("trendnews.important_finalize")

_OPEN_STATUSES = ("offered", "selected")


def result_for_selection(selection_issue: int) -> dict | None:
    """ملف الحكم الذي تحمل إحدى نقاطه رقم قضية الترشيح هذه (القضية الواحدة من ملف واحد)."""
    if not important.IMPORTANT_DIR.exists():
        return None
    for path in sorted(important.IMPORTANT_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and any(p.get("selection_issue") == selection_issue
                                          for p in data.get("points") or []):
            return data
    return None


def find_point(point_id: str, selection_issue: int | None = None) -> tuple[dict, dict] | None:
    """(الملف، النقطة) بمعرّف النقطة؛ مع selection_issue تُفضَّل نقطة تلك القضية. لصورة المرحلة 1."""
    if not important.IMPORTANT_DIR.exists():
        return None
    fallback = None
    for path in sorted(important.IMPORTANT_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for p in (data.get("points") or []) if isinstance(data, dict) else []:
            if p.get("id") != point_id:
                continue
            if selection_issue is None or p.get("selection_issue") == selection_issue:
                return data, p
            fallback = fallback or (data, p)
    return fallback if selection_issue is None else None


def _pseudo_candidate(point: dict, result: dict, selection_issue: int) -> dict:
    # شكل المرشح الذي يقرؤه decisions: المعرّف والأصل والقضية؛ لا مقال خام لنقطة «هام»
    return {"id": point["id"], "created_at": result.get("created_at", ""),
            "origin": "important", "selection_issue": selection_issue, "article": {}}


def _ids_in(body: str) -> list[str]:
    seen: list[str] = []
    for match in stages.GO_MARKER.finditer(body or ""):
        if match.group(2) not in seen:
            seen.append(match.group(2))
    return seen


def _reuse_returned(point: dict, issue_number: int) -> dict | None:
    """مسودة أعادها المراجع (go1) تعود كما هي — نصها وعناوينها وبطاقتها — بلا نداء كاتب (Issue #1221)."""
    if not point.get("draft_id"):
        return None
    found = store.load_draft(point["draft_id"])
    if not found or found[1].get("status") != "returned":
        return None
    remove = ["returned_from_stage", "returned_at", "review_issue"]
    extra: dict = {}
    if point.get("manual_image"):
        # رابط وضعه المراجع في قضية الترشيح الجديدة: يغلب كل مراحل الصورة فتُبنى البطاقة حوله
        extra["manual_image"] = point["manual_image"]
        remove.append("image")
    draft = store.update_draft(found[0], status="pending", remove=remove,
                               selection_issue=issue_number, **extra)
    for key in ("returned", "returned_from_stage", "returned_at"):
        point.pop(key, None)
    log.info("أُعيد استعمال المسودة المُعادة %s بلا كتابة جديدة", draft["id"])
    return draft


def _title(point: dict) -> str:
    return important_issue.display_title(point)[:60]


def finalize(issue_number: int, body: str, cfg) -> int:
    all_ids = _ids_in(body)
    if not all_ids:
        log.error("Issue #%s: لا علامة go: واحدة في الجسم — ليس قضية ترشيح «هام»", issue_number)
        review.comment(
            issue_number,
            "⚠️ لم يُعثر على أي خيار انتقال (`<!-- go:… -->`) في جسم هذه القضية — لم يُنفَّذ شيء، "
            "ووسم `approved` تُرك كما هو حتى تُصحَّح الحالة يدويًا.")
        return 1
    result = result_for_selection(issue_number)
    if not result:
        review.comment(
            issue_number,
            "⚠️ لا ملف حكم محفوظ لهذه القضية في `state/important` — لم يُنفَّذ شيء، ووسم "
            "`approved` تُرك كما هو.")
        return 1

    actions, conflicts = stages.read_actions(body, 1)
    points = {p["id"]: p for p in result["points"] if p.get("selection_issue") == issue_number}
    ids = [i for i in all_ids if i in points and points[i].get("status") in _OPEN_STATUSES]
    chosen = {i: actions[i] for i in ids if actions.get(i) in ("go2", "go3", "publish")}
    log.info("قضية «هام» #%s: %d نقطة في الجسم، %d معلَّمة، %d بتعارض",
             issue_number, len(all_ids), len(chosen), len(conflicts))

    if conflicts:
        rows = []
        for item in conflicts:
            if item["id"] not in points:
                continue
            marked = " + ".join(stages.action_label(a, 1, cfg) for a in item["marked"])
            rows.append(f"- «{_title(points[item['id']])}»: {marked} ← نُفِّذ: "
                        f"{stages.action_label(item['marked'][0], 1, cfg)}")
        if rows:
            review.comment(
                issue_number,
                "⚠️ عُلِّم أكثر من خيار انتقال على بعض النقاط — نُفِّذ الأحوط (المراجعة الأولية "
                "أوسع من البطاقة، والبطاقة أوسع من النشر المباشر):\n" + "\n".join(rows))

    # غير المعلَّم «لم يُختر» (قرار بشري صريح بلا تعليم) — يُسجَّل في decisions بأصل important
    for pid in ids:
        if pid in chosen:
            points[pid].update(status="selected", action=chosen[pid])
        else:
            points[pid]["status"] = "unselected"
            decisions.record_unselected(_pseudo_candidate(points[pid], result, issue_number))
    important.save(result)

    if not chosen:
        review.comment(issue_number, "⚠️ لم يُعلَّم على أي نقطة. لم تُكتب أي مسودة ولم يُنفق شيء.")
        review.remove_label(issue_number, "approved")
        return 0

    failures: list[tuple[str, str, bool]] = []
    now_drafts: list[dict] = []
    review_drafts: list[dict] = []
    card_drafts: list[dict] = []
    written = 0

    def make(pid: str) -> dict | None:
        point = points[pid]
        draft = _reuse_returned(point, issue_number)
        if draft is None:
            draft, reason, technical = important_write.write_point(point, result, cfg, issue_number)
            if draft is None:
                point["write_error"] = reason
                failures.append((_title(point), reason, technical))
                important.save(result)
                return None
        point.pop("write_error", None)
        point.update(status="written", draft_id=draft["id"],
                     written_at=datetime.now(timezone.utc).isoformat())
        important.save(result)
        return draft

    def with_card(draft: dict, label: str) -> dict | None:
        found = store.load_draft(draft["id"])
        if not found:
            return None
        path, loaded = found
        if cards.ensure(path, loaded, cfg, search_term=loaded.get("image_query_en")) is None:
            log.warning("تعذّر بناء بطاقة المسودة %s %s — تُترك pending بلا صورة", label, draft["id"])
            review.comment(
                issue_number,
                f"⚠️ تعذّر بناء بطاقة **{loaded['arabic']['post_title'][:60]}** {label} — بقيت "
                "المسودة معلَّقة بلا صورة، وستظهر في أقرب Issue مراجعة أولية.")
            return None
        return loaded

    for pid in [i for i in ids if chosen.get(i) == "publish"]:
        draft = make(pid)
        if draft:
            written += 1
            card = with_card(draft, "🚀")
            if card:
                now_drafts.append(card)
    for pid in [i for i in ids if chosen.get(i) == "go2"]:
        draft = make(pid)
        if draft:
            written += 1
            review_drafts.append(draft)
    for pid in [i for i in ids if chosen.get(i) == "go3"]:
        draft = make(pid)
        if draft:
            written += 1
            card = with_card(draft, "🎴")
            if card:
                card_drafts.append(card)

    if failures:
        lines = [f"- «{title}»: {reason}" for title, reason, _ in failures]
        review.comment(issue_number, f"⚠️ تعذّرت كتابة {len(failures)} نقطة:\n" + "\n".join(lines))
    if not written:
        if any(technical for _, _, technical in failures):
            # عطل تقني لا قرار تحرير: approved يبقى ليعيد المراجع تشغيل النشر بلا إعادة تعليم
            return 1
        review.remove_label(issue_number, "approved")
        return 0

    return collect_finalize.dispatch_written(
        issue_number, review_drafts, review.sort_by_score(card_drafts),
        [d["id"] for d in now_drafts], cfg)


def reopen_selection(source_issue: int, cfg) -> int | None:
    """قضية ترشيح «هام» جديدة للنقاط المعادة (go1) من نص `source_issue` نفسه — تُبنى من الملف
    المحفوظ بلا حكم جديد، والمعادة في أعلاها بشارة المرحلة. تعيد رقمها أو None إن لم يبقَ ما يُعرض."""
    result = important.load_saved(source_issue)
    if not result:
        return None
    back = [p for p in result["points"]
            if p.get("returned") and p.get("status") == "offered" and not p.get("selection_issue")]
    if not back:
        return None
    back.sort(key=lambda p: p.get("returned_at") or "")
    view = {**result, "points": back}
    review.ensure_labels()
    created = review.create_issue(important_issue.selection_title(view, cfg),
                                  important_issue.build_selection_body(view, cfg),
                                  labels=[important_issue.LABEL])
    for p in back:
        p["selection_issue"] = created["number"]
    result["selection_issue"] = created["number"]
    important.save(result)
    return created["number"]
