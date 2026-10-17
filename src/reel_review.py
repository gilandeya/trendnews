"""قضية المراجعة النهائية للريل (Issue #1469، R4a): قضية واحدة لكل ريل مركَّب، وسمها reel-review.

العرض والقراءة فقط — النشر الفعلي في R4b. تُفتح عند أول تركيب ناجح وتُحفظ برقمها على المسودة (reel_review_issue)،
وكل إعادة تركيب بعدها تعيد كتابة جسم القضية نفسها بدل فتح قضية جديدة. النصوص كلها في config.yaml: reel.review.
"""
from __future__ import annotations

import logging
from pathlib import Path

from . import review, stages, store

log = logging.getLogger("trendnews.reel_review")


def selected_headline(draft: dict) -> str:
    headlines = draft.get("headlines") or []
    if not headlines:
        return ""
    idx = draft.get("headline_selected", 0)
    return headlines[idx] if isinstance(idx, int) and 0 <= idx < len(headlines) else headlines[0]


def build_body(draft: dict, cfg) -> str:
    t = cfg.path("reel.review")
    base = cfg.path("reel.render.data_link_base")
    script = draft.get("script") or {}
    narrator = cfg.path("reel.texts.narrator_" + str(script.get("narrator", "female")), "")
    # الروابط لا الصور: المستودع خاص فلا تُعرض الصورة في الـIssue
    # العلامة العارية <!-- draft:id --> تجدها review.all_draft_ids كبقية القضايا: بها تعرف cmd_reel_review ريل القضية
    lines = [stages.stage_header(3, cfg), "", t["explainer"], "",
             t["meta"].format(title=script.get("title", ""), seconds=draft.get("duration_seconds", "?"),
                              narrator=narrator) + f" <!-- draft:{draft['id']} -->",
             "", t["video"].format(url=base + draft.get("reel_file", "")),
             t["preview"].format(url=base + draft.get("reel_gif", "")), ""]
    notes = draft.get("render_notes") or []
    if notes:
        lines += [f"**{t['notes_title']}**", ""] + [f"- {n}" if not n.lstrip().startswith(("-", "#")) else n
                                                     for n in notes] + [""]
    lines += review.headline_boxes(draft, t["headlines_intro"])
    post = [selected_headline(draft)]
    if draft.get("render_sources"):
        post += ["", cfg.path("reel.render.texts.clips_from").format(channels=draft["render_sources"])]
    lines += [f"**{t['post_title']}**", "", *post, ""]
    # go2/go1 (Issue #1536، W2b): رجوع خطوة إلى السيناريو أو خطوتين إلى الترشيح؛ go1 لمن له topic_id وحده
    lines += stages.options_block(3, draft["id"], cfg, has_stage1=bool(draft.get("topic_id")),
                                  only=("publish", "go2", "go1"),
                                  labels={"go2": t.get("go2"), "go1": t.get("go1")})
    return "\n".join(lines)


def issue_title(draft: dict, cfg) -> str:
    return cfg.path("reel.review.title").format(title=(draft.get("script") or {}).get("title", ""))


def open_or_update(path: Path, draft: dict, cfg) -> int:
    """يفتح قضية المراجعة أو يعيد كتابة جسم القائمة وتعيد رقمها. يرفع عند العطل والمستدعي يحوّله إلى تحذير."""
    body = build_body(draft, cfg)
    number = draft.get("reel_review_issue")
    if number:
        review.update_issue_body(int(number), body)
        return int(number)
    review.ensure_labels()
    created = review.create_issue(issue_title(draft, cfg), body, labels=[cfg.path("reel.review.label")])
    number = int(created["number"])
    store.update_draft(path, reel_review_issue=number)
    log.info("قضية مراجعة الريل #%s للمسودة %s", number, draft["id"])
    return number
