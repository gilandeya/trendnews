"""مرحلة الاختيار قبل الصياغة (Issue #280): وفّر ثمن الصياغة والصورة على
مرشحين يُرفضون لاحقًا في المراجعة، عبر عرض العناوين الخام فقط للاختيار
البشري قبل إنفاق أي شيء عليها.

بديل لدورة "صُغ ثم راجِع" الحالية لا إضافة إليها (`config.yaml:
preselect.enabled`) — يحلّ محلها حين يُفعَّل. بناء المرشحين هنا لا يستدعي
Sonnet (الصياغة) ولا يبني صورة؛ الترتيب والفرز الأوليان (Haiku) وقعا قبل
هذه النقطة في collect.py وهما شبه مجانيين أصلًا (انظر التشخيص في Issue
#280). الصياغة الفعلية تقع لاحقًا في collect_finalize.py، للمختار فقط.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, fields
from datetime import datetime, timezone

from . import review
from .sources import Article

log = logging.getLogger(__name__)

CAND_MARKER = re.compile(r"<!--\s*cand:([0-9a-f]+)\s*-->")
CREJECT_MARKER = re.compile(r"<!--\s*crj:([0-9a-f]+):([^\s>]+)\s*-->")


# ──────────────────────────── تسلسل Article ────────────────────────────


def article_to_dict(art: Article) -> dict:
    """يحوّل Article إلى قاموس قابل لتخزين JSON — يحفظ كل ما يلزم لإعادة
    بنائه لاحقًا عند الصياغة (cluster_members وimage_candidates تحديدًا)."""
    data = asdict(art)
    data["published"] = art.published.isoformat()
    return data


def article_from_dict(data: dict) -> Article:
    """يعكس article_to_dict — يُستدعى في collect_finalize بعد الاختيار."""
    valid = {f.name for f in fields(Article)}
    clean = {k: v for k, v in data.items() if k in valid}
    clean["published"] = datetime.fromisoformat(clean["published"])
    return Article(**clean)


# ──────────────────────────── بناء المرشح ────────────────────────────


def build_candidate(art: Article) -> dict:
    return {
        "id": art.uid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",          # pending → selected/unselected/write_failed
        "selection_issue": None,
        "score": round(art.score, 2),
        "trend_score": round(art.trend_score, 2),
        "velocity": round(art.velocity, 2),
        "bucket": art.bucket,
        "state_media": art.state_media,
        "title": art.title,
        "link": art.link,
        "publishers": art.cluster_sources or [art.publisher],
        "region": art.region,
        "article": article_to_dict(art),
    }


# ──────────────────────────── بناء نص الاختيار ────────────────────────────


def build_selection_issue_body(candidates: list[dict]) -> str:
    parts = [
        "### 🗳️ مرشحون بانتظار الاختيار",
        "",
        "**بلا صياغة ولا صورة بعد** — هذه العناوين الخام كما وردت من "
        "المصادر، قبل أي إنفاق. علّم ما تريد صياغته ونشره (بعضها أو "
        "كلها أو لا شيء)، ثم أضف الوسم `approved`. سيصوغ البوت المختار "
        "فقط وينشره مباشرة بلا مراجعة ثانية ولا Issue آخر.",
        "",
        "🚫 لم يعجبك مرشح؟ اتركه بلا تعليم، أو علّم سببًا من القائمة "
        "تحته إن أردت تحديد السبب — يتعلّم الفرز الأولي منه.",
        "",
        "---",
        "",
    ]

    for idx, c in enumerate(candidates, start=1):
        badge = f"🏷️ {c.get('bucket', '')}"
        if c.get("trend_score", 0) >= 0.5:
            badge += " · 🔥 رائج"
        if c.get("velocity", 0) >= 0.5:
            badge += " · 🚀 ينتشر بسرعة"
        if c.get("state_media"):
            badge += " · ⚠️ إعلام رسمي/حكومي"

        parts += [
            f"- [ ] **{idx}. {c['title']}**  <!-- cand:{c['id']} -->",
            "",
            f"  {badge} · مؤشر الترند `{c['score']:.1f}` · المصادر: "
            f"{'، '.join(c['publishers'][:3])}",
            "",
            f"  ↳ [الخبر الأصلي]({c['link']})",
            "",
            "  🚫 **لاستبعاده صراحة، علّم سببًا:**",
            "",
            *[f"  - [ ] {label}  <!-- crj:{c['id']}:{tag} -->"
              for tag, label in review.REJECT_CHOICES],
            "",
            "---",
            "",
        ]

    parts.append("<sub>وسم `approved` = صياغة المُعلَّم ونشره فورًا · "
                 "إغلاق الـ Issue بلا تعليم = تجاهل الكل بلا أي إنفاق</sub>")
    return "\n".join(parts)


# ──────────────────────────── قراءة الاختيار ────────────────────────────


def parse_selected(body: str) -> list[str]:
    """يعيد معرفات المرشحين المُعلَّم عليهم ✔️ (لا وسم رفض عليها)."""
    chosen: list[str] = []
    for line in body.splitlines():
        if CREJECT_MARKER.search(line):
            continue
        marker = CAND_MARKER.search(line)
        if not marker:
            continue
        checkbox = re.match(r"\s*[-*]\s*\[([ xX])\]", line)
        if checkbox and checkbox.group(1).lower() == "x":
            chosen.append(marker.group(1))
    return chosen


def parse_candidate_rejects(body: str) -> list[tuple[str, str]]:
    """يعيد [(معرّف المرشح، الوسم)] لمن عُلّم عليه سبب استبعاد صراحة."""
    chosen: list[tuple[str, str]] = []
    for line in body.splitlines():
        marker = CREJECT_MARKER.search(line)
        if not marker:
            continue
        checkbox = re.search(r"\[([ xX])\]", line)
        if checkbox and checkbox.group(1).lower() == "x":
            chosen.append((marker.group(1), marker.group(2)))
    return chosen


def all_candidate_ids(body: str) -> list[str]:
    return CAND_MARKER.findall(body)
