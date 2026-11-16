"""إشعار صاحب المشروع حين ينتظره قرار — وحده (طلبه 16/11).

بريد GitHub يُرسل لكل تعليق وإغلاق وإعادة فتح في قضية هو «مشترك» فيها، والذكر في جسم قضية يشركه فيها؛ فكان ذكره في قضايا
اختيار الأسئلة والسيناريو والمراجعة (#1901) يجرّ بعده بريدًا عن كل تعليق إعلامي يكتبه البوت فيها. الحل: لا ذكر في أي قضية عمل،
وإشعار واحد لكل خطوة تنتظره في قضية «صندوق» ثابتة (وسمها `notifications.inbox.label`) تعليقًا بذكره ورابط القضية؛ هو مشترك في
الصندوق وحده فلا يصله إلا ما فيه.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _icfg(cfg) -> dict:
    return cfg.path("notifications.inbox", {}) or {}


def _mention(cfg) -> str:
    return str(cfg.path("notifications.mention", "") or "").strip()


def _find_inbox(label: str, max_comments: int) -> int | None:
    """أحدث صندوق مفتوح لم يمتلئ. الممتلئ يُنزع وسمه (لا بريد لنزع وسم، والإغلاق يرسل بريدًا) فلا يُختار ثانية."""
    from . import review
    for issue in review.list_open_issues(label):
        if int(issue.get("comments") or 0) < max_comments:
            return int(issue["number"])
        review.remove_label(int(issue["number"]), label)
    return None


def owner(text: str, cfg, issue: int | None = None) -> bool:
    """يكتب «{ذكر} {النص} ← #{القضية}» في الصندوق (يُنشأ أول مرة وأول إشعار في جسمه). لا يرفع: الإشعار لا يُفشل خطوة عمل."""
    icfg = _icfg(cfg)
    mention = _mention(cfg)
    if not icfg.get("enabled", True) or not mention or not text:
        return False
    line = f"{mention} {text}" + (f" ← #{issue}" if issue else "")
    try:
        from . import review
        label = icfg.get("label", "notify-inbox")
        number = _find_inbox(label, int(icfg.get("max_comments", 100)))
        if number is None:
            # الإشعار الأول في جسم الصندوق: بريد الإنشاء يحمله، فلا تعليق يتبعه ببريد ثانٍ
            review.create_issue(icfg.get("title", "🔔 ما ينتظر قرارك"),
                                icfg.get("explainer", "") + "\n\n" + line, labels=[label])
        else:
            review.comment(number, line)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("تعذّر إشعار صاحب المشروع: %s", str(exc)[:150])
        return False


def say(key: str, cfg, issue: int | None = None, **kw) -> bool:
    """`owner` بنص من `notifications.inbox.texts.<key>`؛ مفتاح بلا نص ← لا إشعار."""
    template = (_icfg(cfg).get("texts") or {}).get(key, "")
    if not template:
        return False
    try:
        text = template.format(**kw)
    except (KeyError, IndexError, ValueError):
        text = template
    return owner(text, cfg, issue)
