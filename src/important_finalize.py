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

from . import (cards, collect_finalize, decisions, editor, important, important_editor, important_issue,
               important_write, review, stages, store)

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
        if isinstance(data, dict) and any(
                p.get("selection_issue") == selection_issue
                for p in (data.get("points") or []) + (data.get("article_items") or [])):
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
        # العناصر (#1293) بعد النقاط: معرّف المنشور يحمل صورة المرحلة 1 كما تحملها النقطة
        entries = ((data.get("points") or []) + (data.get("article_items") or [])) \
            if isinstance(data, dict) else []
        for p in entries:
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


def _title(point: dict, cfg=None) -> str:
    if point.get("kind") in important.ARTICLE_KINDS and "point_ids" in point:
        return important_issue.item_title(point, cfg if cfg is not None else {})[:60]
    return important_issue.display_title(point)[:60]


def _sibling_texts(result: dict, item: dict) -> list[str]:
    """نصوص المنشورات الأخرى للنص نفسه التي كُتبت مسودتها (في هذه التشغيلة أو قبلها): عنوانها ومتنها،
    كي لا يكرّر المنشور الجديد وقائعها (#1293)."""
    out = []
    for other in result.get("article_items") or []:
        if other.get("id") == item.get("id") or not other.get("draft_id"):
            continue
        found = store.load_draft(other["draft_id"])
        if found:
            ar = found[1].get("arabic") or {}
            out.append(f"{ar.get('post_title', '')}\n{ar.get('post_body', '')}".strip())
    return out


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
    # قضية بعلامات منشورات (#1293) تُقرأ عناصرها؛ قضية فُتحت قبله علاماتها معرّفات نقاط فتُقرأ بالمسار القديم
    items = {i["id"]: i for i in result.get("article_items") or []
             if i.get("selection_issue") == issue_number}
    item_mode = any(i in items for i in all_ids)
    points = items if item_mode else {
        p["id"]: p for p in result["points"] if p.get("selection_issue") == issue_number}
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
            rows.append(f"- «{_title(points[item['id']], cfg)}»: {marked} ← نُفِّذ: "
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
    reused: set[str] = set()

    def make(pid: str) -> dict | None:
        point = points[pid]
        draft = _reuse_returned(point, issue_number)
        if draft is not None:
            reused.add(pid)
        if draft is None:
            if item_mode:
                draft, reason, technical = important_write.write_article(
                    result, point, cfg, _sibling_texts(result, point), issue_number)
            else:
                draft, reason, technical = important_write.write_point(point, result, cfg, issue_number)
            if draft is None:
                point["write_error"] = reason
                if not technical:
                    # رفض تحريري بعد إعادة المحاولة: failed ظاهرة لا «selected» صامتة (#1225)؛
                    # العطل التقني يبقى selected ليُعاد بإعادة وسم approved كما كان
                    point.update(status="failed", failed_at=datetime.now(timezone.utc).isoformat())
                failures.append((_title(point, cfg), reason, technical))
                important.save(result)
                return None
        for key in ("write_error", "write_failed", "failed_at"):
            point.pop(key, None)
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

    # ترتيب الكتابة: النقاط بمجموعات الانتقال (نشر ثم مراجعة ثم بطاقة) كما كان؛ والمنشورات بنوعها
    # (verified ثم nearest ثم refuted) كي يرى كل منشور نصوص ما كُتب قبله (#1293)
    if item_mode:
        order = sorted((i for i in ids if i in chosen),
                       key=lambda i: important.ARTICLE_KINDS.index(points[i]["kind"]))
    else:
        order = [i for act in ("publish", "go2", "go3") for i in ids if chosen.get(i) == act]
    # الكتابة كلها أولًا (ليرى المحرر كل الإخوة)، ثم المحرر الأخير لكل مسودة جديدة بترتيب الكتابة، ثم التوزيع (#1331)
    made: list[tuple[str, dict]] = []
    for pid in order:
        draft = make(pid)
        if draft:
            made.append((pid, draft))
    if item_mode:
        made = [(pid, draft if pid in reused else important_editor.review(draft, result, points[pid], cfg))
                for pid, draft in made]
    for pid, draft in made:
        written += 1
        gated, _why = editor.gate_action(chosen[pid], draft, 1, cfg)
        if chosen[pid] in ("publish", "go3") and (gated != chosen[pid] or any(
                str(w).startswith(important_write.WARN_FAILED_CHECK_PREFIX) for w in draft.get("warnings") or [])):
            # منشور لم يجتز فحصًا أو وجد فيه المحرر ما يمنعه لا يُنشر ولا تُبنى بطاقته قبل عين بشرية (#1304، #1331)
            chosen[pid] = "go2"
            review.comment(issue_number, f"📝 حُوِّل {_title(points[pid], cfg)} إلى المراجعة لأن فيه تنبيهات فحص")
        if chosen[pid] == "go2":
            review_drafts.append(draft)
        else:
            label = "🚀" if chosen[pid] == "publish" else "🎴"
            card = with_card(draft, label)
            if card:
                (now_drafts if chosen[pid] == "publish" else card_drafts).append(card)

    if failures:
        # كل فشل يُبلَّغ على قضية الترشيح نفسها بسببه (#1225): لا فشل صامت
        review.comment(issue_number, "\n".join(
            f"⚠️ فشلت كتابة: {title} — السبب: {reason}" for title, reason, _ in failures))
    if not written:
        if any(technical for _, _, technical in failures):
            # عطل تقني لا قرار تحرير: approved يبقى ليعيد المراجع تشغيل النشر بلا إعادة تعليم
            return 1
        review.remove_label(issue_number, "approved")
        return 0

    return collect_finalize.dispatch_written(
        issue_number, review_drafts, review.sort_by_score(card_drafts),
        [d["id"] for d in now_drafts], cfg)


def run(issue_number: int, body: str, cfg) -> int:
    """نقطة دخول publish.main: finalize ثم إعادة عرض ما فشلت كتابته في قضية ترشيح جديدة.
    الفصل مقصود: finalize وحدها لا تفتح قضية (كتابة مرفوضة بلا مسودة ولا قضية)، وفتحها
    خطوة تتبعها من الملف المحفوظ كما يفعل go1."""
    code = finalize(issue_number, body, cfg)
    try:
        reopen_failed(issue_number, cfg)
    except Exception:  # noqa: BLE001 — إعادة العرض مساعدة: لا تُسقط رمز خروج الكتابة نفسها
        log.exception("تعذّرت إعادة عرض النقاط الفاشلة لقضية «هام» #%s", issue_number)
    return code


def reopen_failed(selection_issue: int, cfg) -> int | None:
    """النقاط failed من قضية الترشيح هذه تعود offered بلا قضية ومعها `write_failed` فتفتح
    reopen_selection قضية جديدة لها بشارة «⚠️ فشلت الكتابة» (آلية go1 نفسها، #1225)."""
    result = result_for_selection(selection_issue)
    if not result:
        return None
    failed = [p for p in (result.get("article_items") or []) + result["points"]
              if p.get("selection_issue") == selection_issue and p.get("status") == "failed"]
    if not failed:
        return None
    for p in failed:
        p.update(status="offered", selection_issue=None, write_failed=True)
    important.save(result)
    return reopen_selection(result["issue"], cfg)


def reopen_selection(source_issue: int, cfg) -> int | None:
    """قضية ترشيح «هام» جديدة للنقاط المعادة (go1) أو الفاشلة كتابتها من نص `source_issue`
    نفسه — تُبنى من الملف المحفوظ بلا حكم جديد، والمعادة في أعلاها بشارة المرحلة.
    تعيد رقمها أو None إن لم يبقَ ما يُعرض."""
    result = important.load_saved(source_issue)
    if not result:
        return None
    pool = result["article_items"] if result.get("article_items") else result["points"]
    back = [p for p in pool
            if (p.get("returned") or p.get("write_failed"))
            and p.get("status") == "offered" and not p.get("selection_issue")]
    if not back:
        return None
    back.sort(key=lambda p: p.get("returned_at") or p.get("failed_at") or "")
    view = {**result, "article_items": back} if result.get("article_items") else {**result, "points": back}
    review.ensure_labels()
    created = review.create_issue(important_issue.selection_title(view, cfg),
                                  important_issue.build_selection_body(view, cfg),
                                  labels=[important_issue.LABEL])
    for p in back:
        p["selection_issue"] = created["number"]
    result["selection_issue"] = created["number"]
    important.save(result)
    return created["number"]
