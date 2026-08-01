"""واجهة المراجعة: إنشاء Issue على GitHub يعرض المسودات وصورها لاعتمادها."""
from __future__ import annotations

import logging
import os
import re

import requests

from .config import env

log = logging.getLogger(__name__)

API = "https://api.github.com"
ID_MARKER = re.compile(r"<!--\s*draft:([0-9a-f]+)\s*-->")
CHECKED_LINE = re.compile(r"^\s*[-*]\s*\[([ xX])\]", re.MULTILINE)


def _repo() -> str:
    return env("GITHUB_REPOSITORY", required=True)  # type: ignore[return-value]


def _headers() -> dict:
    token = env("GITHUB_TOKEN", required=True)
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def raw_url(repo: str, branch: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def blob_url(repo: str, branch: str, path: str) -> str:
    return f"https://github.com/{repo}/blob/{branch}/{path}"


# ──────────────────────────── بناء نص المراجعة ────────────────────────────


def build_issue_body(drafts: list[dict], repo: str, branch: str = "main") -> str:
    run_id = os.environ.get("GITHUB_RUN_ID")
    parts = [
        "### 📋 مسودات بانتظار المراجعة",
        "",
        "**كيف تعتمد؟** ✔️ ضع علامة على المنشورات التي توافق عليها، ثم أضف "
        "الوسم `approved` إلى هذا الـ Issue. سيتولى البوت نشر المحدد فقط.",
        "",
        "لتعديل نص أي منشور: افتح ملف `.json` الخاص به وعدّل حقل `caption` ثم احفظ.",
        "",
        "---",
        "",
    ]

    for idx, d in enumerate(drafts, start=1):
        img_path = d["image"]
        ar = d["arabic"]
        badge = "🔴 عاجل" if ar.get("urgent") else f"🏷️ {ar.get('category', '')}"

        parts += [
            f"- [ ] **{idx}. {ar['post_title']}**  <!-- draft:{d['id']} -->",
            "",
            f"  {badge} · مؤشر الترند `{d['score']:.1f}` · المصادر: "
            f"{'، '.join(d['source']['publishers'][:3])}",
            "",
            f"  <img src=\"{raw_url(repo, branch, img_path)}\" width=\"520\" />",
            "",
            f"  ↳ [الصورة في المستودع]({blob_url(repo, branch, img_path)}) · "
            f"[الخبر الأصلي]({d['source']['link']})",
            "",
            "  <details><summary>📝 نص المنشور الكامل</summary>",
            "",
            "  ```",
            *[f"  {line}" for line in d["caption"].splitlines()],
            "  ```",
            "",
            "  </details>",
            "",
            "---",
            "",
        ]

    if run_id:
        parts += [
            f"> إن لم تظهر الصور أعلاه (مستودع خاص)، نزّلها من "
            f"[مخرجات التشغيل](https://github.com/{repo}/actions/runs/{run_id}).",
            "",
        ]
    parts.append("<sub>وسم `approved` = نشر المحدد · إغلاق الـ Issue = تجاهل الكل</sub>")
    return "\n".join(parts)


def parse_approved(body: str) -> list[str]:
    """يستخرج معرفات المسودات التي عُلّم عليها ✔️."""
    approved: list[str] = []
    for line in body.splitlines():
        marker = ID_MARKER.search(line)
        if not marker:
            continue
        checkbox = re.match(r"\s*[-*]\s*\[([ xX])\]", line)
        if checkbox and checkbox.group(1).lower() == "x":
            approved.append(marker.group(1))
    return approved


def all_draft_ids(body: str) -> list[str]:
    return ID_MARKER.findall(body)


# ──────────────────────────── عمليات GitHub ────────────────────────────


def create_issue(title: str, body: str, labels: list[str] | None = None) -> dict:
    repo = _repo()
    resp = requests.post(
        f"{API}/repos/{repo}/issues",
        headers=_headers(),
        json={"title": title, "body": body, "labels": labels or []},
        timeout=45,
    )
    resp.raise_for_status()
    data = resp.json()
    log.info("تم إنشاء Issue #%s للمراجعة", data["number"])
    return data


def comment(issue_number: int, text: str) -> None:
    repo = _repo()
    requests.post(
        f"{API}/repos/{repo}/issues/{issue_number}/comments",
        headers=_headers(),
        json={"body": text},
        timeout=45,
    ).raise_for_status()


def close_issue(issue_number: int) -> None:
    repo = _repo()
    requests.patch(
        f"{API}/repos/{repo}/issues/{issue_number}",
        headers=_headers(),
        json={"state": "closed", "state_reason": "completed"},
        timeout=45,
    ).raise_for_status()


def remove_label(issue_number: int, label: str) -> None:
    repo = _repo()
    requests.delete(
        f"{API}/repos/{repo}/issues/{issue_number}/labels/{label}",
        headers=_headers(),
        timeout=45,
    )


def ensure_labels() -> None:
    """ينشئ الوسوم المطلوبة إن لم تكن موجودة."""
    repo = _repo()
    wanted = [
        ("pending-review", "fbca04", "مسودات بانتظار المراجعة"),
        ("approved", "0e8a16", "معتمد للنشر"),
        ("published", "5319e7", "تم النشر على فيسبوك"),
    ]
    for name, color, desc in wanted:
        requests.post(
            f"{API}/repos/{repo}/labels",
            headers=_headers(),
            json={"name": name, "color": color, "description": desc},
            timeout=30,
        )
