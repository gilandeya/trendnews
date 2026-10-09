"""المصدر الوحيد لنصوص مراحل الاعتماد وخياراتها وعلاماتها وقراءتها (Issue #1180).

بناة المراحل الأربع وقرّاؤها كلها تمرّ من هنا منذ المهمة 4 (Issue #1190:
المرحلة 1 للأخبار والتحليل). النصوص كلها في config.yaml: stages، لا هنا.
"""
from __future__ import annotations

import re

from . import review

# ترتيب ثابت هو نفسه ترتيب العرض وترتيب الأحوط: الأبكر يغلب عند تعليم أكثر
# من مربع لخبر واحد، لأن أضيق ما يُطلب (العودة) أقل ضررًا من نشر لم يُرد.
ACTIONS = ("go1", "go2", "go3", "publish")
# المرحلة التي يعني كل إجراء الذهاب إليها؛ publish = المرحلة 4 (النشر).
_TARGET_STAGE = {"go1": 1, "go2": 2, "go3": 3, "publish": 4}

GO_MARKER = re.compile(r"<!--\s*go:(go1|go2|go3|publish):([0-9a-f]+)\s*-->")
_CHECKED = re.compile(r"\s*[-*]\s*\[([ xX])\]")


def stage_header(stage: int, cfg) -> str:
    name = cfg.path(f"stages.names.{stage}", "")
    return f"### المرحلة {stage} من 4: {name}"


def _option_text(action: str, stage: int, cfg, urgent: bool) -> str:
    if action == "go2":
        # من المرحلة 1 تقدّم، ومن المرحلة 3 عودة — النص يتبع الاتجاه.
        key = "go2_forward" if stage < 2 else "go2_back"
    else:
        key = action
    text = cfg.path(f"stages.options.{key}", "")
    if action == "publish" and urgent:
        text += " " + cfg.path("stages.options.publish_urgent_suffix", "")
    return text


def action_label(action: str, stage: int, cfg) -> str:
    """نص خيار الانتقال كما يراه المراجع (لتنبيه التعارض)."""
    return _option_text(action, stage, cfg, False)


def options_block(stage: int, item_id: str, cfg, has_stage1: bool = True,
                  urgent: bool = False, only: tuple[str, ...] | None = None) -> list[str]:
    """``only`` (Issue #1336): يحصر الخيارات بهذه الإجراءات -- بند الريل في المرحلة 2
    يعرض go1 وحده حتى تُبنى مراحله اللاحقة (R3/R4)."""
    lines = [cfg.path("stages.options_header", "")]
    for action in ACTIONS:
        if only is not None and action not in only:
            continue
        if _TARGET_STAGE[action] == stage:
            continue                      # لا خيار للانتقال إلى المرحلة الحالية
        if action == "go1" and not has_stage1:
            continue                      # مسار بلا مرحلة ترشيح لا يعود إليها
        lines.append(f"- [ ] {_option_text(action, stage, cfg, urgent)}  "
                     f"<!-- go:{action}:{item_id} -->")
    return lines


def image_field(item_id: str, cfg) -> str:
    # علامة imgurl القائمة نفسها كي يبقى review.parse_image_requests يقرؤها.
    return f"{cfg.path('stages.image_field', '')}  <!-- imgurl:{item_id} -->"


# خيار «➕ أضف ريلًا/مقالًا» في المرحلة 2 للتحليل (Issue #1336): علامته addfmt:<صيغة>:<topic_id>
ADDFMT_MARKER = re.compile(r"<!--\s*addfmt:(article|reel):([0-9a-f]+)\s*-->")


def parse_add_formats(body: str) -> list[tuple[str, str]]:
    """[(الصيغة، topic_id)] للخيارات المعلَّمة بالترتيب الذي وردت به."""
    out: list[tuple[str, str]] = []
    for line in (body or "").splitlines():
        match = ADDFMT_MARKER.search(line)
        box = _CHECKED.match(line)
        if match and box and box.group(1).lower() == "x":
            out.append((match.group(1), match.group(2)))
    return out


def parse_actions(body: str) -> tuple[dict[str, str], list[dict]]:
    """يعيد ({item_id: action}, تعارضات). التعارض: {"id", "marked"} حين عُلِّم
    أكثر من مربع لخبر واحد؛ يغلب الأبكر في ACTIONS."""
    marked: dict[str, set[str]] = {}
    for line in (body or "").splitlines():
        match = GO_MARKER.search(line)
        if not match:
            continue
        box = _CHECKED.match(line)
        if box and box.group(1).lower() == "x":
            marked.setdefault(match.group(2), set()).add(match.group(1))
    result: dict[str, str] = {}
    conflicts: list[dict] = []
    for item_id, actions in marked.items():
        ordered = [a for a in ACTIONS if a in actions]
        result[item_id] = ordered[0]
        if len(ordered) > 1:
            conflicts.append({"id": item_id, "marked": ordered})
    return result, conflicts


def read_actions(body: str, stage: int) -> tuple[dict[str, str], list[dict]]:
    """القارئ الموحَّد لقضايا المرحلتين 2 و3: علامات go: إن وُجدت وإلا الترجمة
    القديمة. التمييز بوجود علامة واحدة على الأقل لا بالمرحلة، لأن قضية مفتوحة
    قبل التحديث لا تحمل أيًّا منها، وقضية جديدة تحمله دائمًا (options_block)؛
    فلا يلتبس الأمر ولا تُقرأ قضية واحدة بالطريقتين معًا."""
    if GO_MARKER.search(body or ""):
        return parse_actions(body)
    conflicts = _legacy_conflicts_stage1(body or "") if stage == 1 else []
    return legacy_actions(body or "", stage), conflicts


def _legacy_conflicts_stage1(body: str) -> list[dict]:
    """تعارض مربعات قضية ترشيح أخبار قديمة (🚀/📝/🎴): الترجمة القديمة تحسمه
    بالأحوط صامتةً، وكان collect_finalize يعلّق بتنبيه خاص — فيبقى التنبيه
    لتلك القضايا بإعادة حساب المجموعات نفسها هنا بالقرّاء القائمين."""
    from . import preselect
    marked: dict[str, set[str]] = {}
    for ids, action in ((preselect.parse_publish_now(body), "publish"),
                        (preselect.selected_card_ids(body), "go3"),
                        (preselect.parse_draft_review(body), "go2")):
        for i in ids:
            marked.setdefault(i, set()).add(action)
    return [{"id": i, "marked": [a for a in ACTIONS if a in actions]}
            for i, actions in marked.items() if len(actions) > 1]


def legacy_actions(body: str, stage: int) -> dict[str, str]:
    """نفس الترجمة من العلامات القديمة، بإعادة استعمال القرّاء القائمين كما
    هم (لا قارئ ثانٍ) كي يبقى سلوك Issues المفتوحة قبل التحديث حرفيًا."""
    out: dict[str, str] = {}
    if stage == 1:
        from . import preselect, youtube_cluster
        # الأحوط القائم: 📝 تغلب الكل، 🎴 تغلب 🚀 — يُطبَّق بالكتابة المتأخرة.
        for ids, action in ((preselect.parse_publish_now(body), "publish"),
                            (preselect.selected_card_ids(body), "go3"),
                            (preselect.parse_draft_review(body), "go2")):
            for i in ids:
                out[i] = action
        for i in youtube_cluster._checked_topic_ids(body):
            out[i] = "go2"                # مسار التحليل: «معلَّم» = مراجعة أولية
    elif stage == 2:
        cards = review.parse_card_requests(body)
        for i in review.parse_approved(body):
            out[i] = "go3" if i in cards else "publish"   # 🎴 وحده بلا ✔️ لا شيء
    elif stage == 3:
        back = review.parse_back_requests(body)
        for i in review.parse_approved(body):
            if i not in back:
                out[i] = "publish"
        for i in back:
            out[i] = "go2"                # ↩️ يغلب ✔️
    return out
