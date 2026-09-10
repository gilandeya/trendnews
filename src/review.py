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
REEL_MARKER = re.compile(r"<!--\s*reel:([0-9a-f]+)\s*-->")
# مربع «اعرض البطاقة قبل النشر» في المراجعة الأولية، ومربع «أعده للمراجعة
# الأولية» في المراجعة النهائية (Issue #858، الجزء الثاني من اثنين).
CARD_MARKER = re.compile(r"<!--\s*card:([0-9a-f]+)\s*-->")
BACK_MARKER = re.compile(r"<!--\s*back:([0-9a-f]+)\s*-->")
CHECKED_LINE = re.compile(r"^\s*[-*]\s*\[([ xX])\]", re.MULTILINE)
# كتلة النص القابلة للتحرير: <!-- cap:المعرّف --> ... <!-- /cap:المعرّف -->
# (Issue #752) — DOTALL كي تمتد المطابقة عبر أسطر الكتلة كاملة، وbackreference
# \1 كي لا تلتقط كتلة معرّف آخر بالخطأ حين يتجاور منشوران في نفس نصّ الـ Issue.
CAP_MARKER = re.compile(
    r"<!--\s*cap:([0-9a-f]+)\s*-->(.*?)<!--\s*/cap:\1\s*-->", re.DOTALL)


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
        "🎴 ✔️ وحده = تُبنى البطاقة ويُنشر فورًا. مع 🎴 = تُبنى البطاقة "
        "وتُعرض عليك في Issue ثانٍ قبل النشر.",
        "",
        "🎬 لكل خبر مربع ثانٍ: علّم عليه لينشر البوت **ريلًا** بدل الصورة. "
        "الريل يُبنى لحظة النشر (يضيف ~30 ثانية) ولا يُبنى لما لا تختاره.",
        "",
        "🚫 **ما لا تعلّمه لن يُنشر** ويُسجَّل مرفوضًا تلقائيًا — وسأسألك عن "
        "السبب في التقرير الأسبوعي.",
        "",
        "✏️ لتعديل نصّ منشور: حرّر هذا الـIssue واكتب داخل كتلة النص مباشرة. "
        "النصّ الذي أراه لحظة الاعتماد هو ما يُنشر. ملاحظة: تعديل النص لا "
        "يغيّر البطاقة — البطاقة تحمل العنوان فقط. لو عدّلت النص وعلّمت "
        "عنوانًا معًا، فالعنوان المعلَّم يستبدل السطر الأول.",
        "",
        "---",
        "",
    ]

    id_to_idx = {dd["id"]: i for i, dd in enumerate(drafts, start=1)}

    for idx, d in enumerate(drafts, start=1):
        img_path = d.get("image")
        ar = d["arabic"]
        badge = "🔴 عاجل" if ar.get("urgent") else f"🏷️ {ar.get('category', '')}"
        if d.get("trend_score", 0) >= 0.5:
            badge += " · 🔥 رائج"
        if d.get("velocity", 0) >= 0.5:
            badge += " · 🚀 ينتشر بسرعة"
        if ar.get("angle") == "تفسير":
            badge += " · 🧭 تفسيري"
        if d.get("is_followup"):
            badge += " · ↩️ متابعة"
        if d.get("bucket") == "light":
            badge += " · 🎭 خفيف"
        if d.get("bucket") == "useful":
            badge += " · 💡 نافع"
        if ar.get("category") == "صحة":
            badge += " · 🏥 راجع الادعاءات الطبية"
        if d.get("analysed_sources"):
            badge += f" · 🔬 محلَّل من {len(d['analysed_sources'])} مصادر"

        parts += [
            f"- [ ] **{idx}. {ar['post_title']}**  <!-- draft:{d['id']} -->",
            "",
            f"  - [ ] 🎴 اعرض البطاقة قبل النشر  <!-- card:{d['id']} -->",
            "",
        ]
        if d.get("sibling_id"):
            # Issue #765، بند 3: مقال ومنشور تحقيق من نفس المدخل يظهران
            # كمسودتين منفصلتين تحملان sibling_id متبادلًا — لا واجهة جديدة،
            # المربعات القائمة تكفي (اعتمد أحدهما أو كليهما أو لا شيء).
            # تصحيح Issue #769: المسودتان قد لا تتجاوران بين مسودات الأخبار،
            # فالسطر يذكر رقم المنشور المقابل صراحة متى وُجد في نفس الـIssue
            # — لا يكفي القول «بديل لنفس المدخل» بلا تحديد أيّهما.
            sib_idx = id_to_idx.get(d["sibling_id"])
            if sib_idx is not None:
                parts += [f"  🔀 بديل للمنشور رقم {sib_idx} — اعتمد أحدهما أو كليهما أو لا شيء.", ""]
            else:
                parts += ["  🔀 بديل لنفس المدخل — اعتمد أحدهما أو كليهما أو لا شيء.", ""]
        parts += [
            f"  {badge} · مؤشر الترند `{d['score']:.1f}` · المصادر: "
            f"{'، '.join(d['source']['publishers'][:3])}",
            "",
            f"  {image_source_line(d)}",
            "",
        ]
        headlines = d.get("headlines") or []
        if headlines:
            # عناوين مقترحة (Issue #756) -- نفس صيغة مسار التحليل
            # (<!-- hl:id:idx -->، الأول معلَّم افتراضيًا)؛ مسودة بقائمة
            # فارغة (فشل النداء، انظر توثيق src/headlines.py) لا تُعرَض لها
            # مربعات إطلاقًا. البطاقة هنا مبنية مسبقًا (خلافًا لمسار
            # التحليل) فتحمل عنوانها القصير الخاص بلا صلة بهذا الاختيار.
            selected = d.get("headline_selected", 0)
            parts.append("  📰 **العنوان:** علّم واحدًا — يستبدل السطر الأول من النص.")
            parts.append("")
            for h_idx, headline in enumerate(headlines):
                mark = "x" if h_idx == selected else " "
                parts.append(f"  - [{mark}] {h_idx + 1}. {headline}  <!-- hl:{d['id']}:{h_idx} -->")
            parts.append("")
            parts.append("  <sub>البطاقة تحمل عنوانها القصير الخاص ولا تتغير باختيارك هنا.</sub>")
            parts.append("")
        parts += [
            *(["  > ⚠️ **مصدره إعلام رسمي/حكومي فقط** — تحقّق من الرواية قبل النشر.",
               ""] if d.get("state_media") else []),
        ]
        # البطاقة (image) لم تُبنَ بعد قبل الاعتماد هو الحال العام الآن
        # (Issue #852) -- تُعرَض بدلًا منها أول مرشَّح صورة خام من
        # source.image_candidates عبر رابط الناشر الخارجي مباشرة، لا
        # raw_url/blob_url (لا شيء رُفع للمستودع بعد).
        if img_path:
            parts += [
                f"  <img src=\"{raw_url(repo, branch, img_path)}\" width=\"520\" />",
                "",
                f"  ↳ [الصورة في المستودع]({blob_url(repo, branch, img_path)}) · "
                f"[الخبر الأصلي]({d['source']['link']})",
                "",
                # صندوق + فراغ: المراجع يفتح تحرير الـ Issue، يلصق الرابط في
                # الفراغ ويعلّم المربع، فيعيد البوت بناء البطاقة. المعرّف
                # مخفي في تعليق HTML لأن المراجع لا يحتاج رؤيته.
                *([f"  🖼️ **بلا صورة للخبر** — البطاقة على خلفية مصممة."]
                  if d.get("has_photo") is False else []),
            ]
        else:
            candidates = (d.get("source") or {}).get("image_candidates") or []
            if candidates:
                parts += [
                    f"  <img src=\"{candidates[0]}\" width=\"520\" />",
                    "",
                    "  <sub>هذه صورة المصدر الخام — البطاقة تُبنى عند الاعتماد.</sub>",
                    "",
                    f"  ↳ [الخبر الأصلي]({d['source']['link']})",
                    "",
                ]
            else:
                parts += [
                    "  🖼️ **المصدر:** بلا صورة من الناشر — ستُستعمل صورة "
                    "تعبيرية حرة عند الاعتماد.",
                    "",
                    f"  ↳ [الخبر الأصلي]({d['source']['link']})",
                    "",
                ]
        parts += [
            f"  - [ ] 🖼️ استبدل الصورة بالرابط أدناه  <!-- img:{d['id']} -->",
            "",
            f"    الرابط:   <!-- imgurl:{d['id']} -->",
            "",
            *([f"  - [ ] 🎬 انشره كريل بدل الصورة  <!-- reel:{d['id']} -->",
               ""] if d.get("reel_spec") or d.get("reel") else []),
            "  <details><summary>📝 نص المنشور الكامل</summary>",
            "",
            f"  <!-- cap:{d['id']} -->",
            "  ```",
            *[f"  {line}" for line in d["caption"].splitlines()],
            "  ```",
            f"  <!-- /cap:{d['id']} -->",
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


def build_final_review_body(drafts: list[dict], repo: str, branch: str = "main") -> str:
    """نص Issue المراجعة النهائية (Issue #858، الجزء الثاني) — يُفتح لمن
    عُلِّم عليه 🎴 في المراجعة الأولية، بعد أن بُنيت بطاقته فعلًا (publish.main
    يبني البطاقة قبل هذا التفرّع، انظر توثيق CLAUDE.md). بلا مربع 🎴 (قرار
    محسوم بالفعل) وبلا مربعات عناوين (العنوان حُفر على البطاقة المبنيّة) —
    فقط اعتماد نهائي، تبديل صورة يدوي (نفس مربعي img/imgurl القائمين في
    build_issue_body، يعمل عبر setimage.py بلا أي تعديل هناك)، وإعادة
    للمراجعة الأولية (↩️، تغلب الاعتماد إن اجتمعا -- نفس مبدأ الرفض يغلب
    الاعتماد قبل #841)."""
    parts = [
        "### 🎴 مراجعة نهائية قبل النشر",
        "",
        "**كيف تعتمد؟** ✔️ ضع علامة على المنشورات التي توافق عليها، ثم أضف "
        "الوسم `approved` إلى هذا الـ Issue. تُنشر البطاقة المبنيّة كما هي "
        "أدناه — بلا إعادة بناء بطاقة ولا اختيار عنوان ولا تعديل نص.",
        "",
        "🚫 **ما لا تعلّمه لن يُنشر** ويُسجَّل مرفوضًا تلقائيًا.",
        "",
        "↩️ لإعادة منشور إلى المراجعة الأولية (لتعديل عنوانه أو نصّه أو "
        "إعادة بناء بطاقته): علّم مربع العودة. يغلب هذا المربع الاعتماد "
        "إن عُلِّم الاثنان معًا على نفس المنشور.",
        "",
        "---",
        "",
    ]

    for idx, d in enumerate(drafts, start=1):
        ar = d["arabic"]
        parts += [
            f"- [ ] **{idx}. {ar['post_title']}**  <!-- draft:{d['id']} -->",
            "",
            f"  {image_source_line(d)}",
            "",
        ]
        img_path = d.get("image")
        if img_path:
            parts += [
                f"  <img src=\"{raw_url(repo, branch, img_path)}\" width=\"520\" />",
                "",
                f"  ↳ [الصورة في المستودع]({blob_url(repo, branch, img_path)}) · "
                f"[الخبر الأصلي]({d['source']['link']})",
                "",
            ]
        parts += [
            f"  - [ ] 🖼️ استبدل الصورة بالرابط أدناه  <!-- img:{d['id']} -->",
            "",
            f"    الرابط:   <!-- imgurl:{d['id']} -->",
            "",
            f"  - [ ] ↩️ أعده للمراجعة الأولية  <!-- back:{d['id']} -->",
            "",
            "  <details><summary>📝 نص المنشور الكامل</summary>",
            "",
            f"  <!-- cap:{d['id']} -->",
            "  ```",
            *[f"  {line}" for line in d["caption"].splitlines()],
            "  ```",
            f"  <!-- /cap:{d['id']} -->",
            "",
            "  </details>",
            "",
            "---",
            "",
        ]

    parts.append("<sub>وسم `approved` = نشر المعلَّم كما هو بلا تعديل · "
                 "إغلاق الـ Issue = تجاهل الكل</sub>")
    return "\n".join(parts)


def parse_reels(body: str) -> set[str]:
    """معرفات المسودات التي اختار المراجع نشرها كريل."""
    chosen: set[str] = set()
    for line in body.splitlines():
        marker = REEL_MARKER.search(line)
        if not marker:
            continue
        checkbox = re.search(r"\[([ xX])\]", line)
        if checkbox and checkbox.group(1).lower() == "x":
            chosen.add(marker.group(1))
    return chosen


def parse_card_requests(body: str) -> set[str]:
    """معرفات المسودات التي طلب المراجع عرض بطاقتها قبل النشر (Issue #858،
    الجزء الثاني) -- نفس أسلوب parse_reels حرفيًا."""
    chosen: set[str] = set()
    for line in body.splitlines():
        marker = CARD_MARKER.search(line)
        if not marker:
            continue
        checkbox = re.search(r"\[([ xX])\]", line)
        if checkbox and checkbox.group(1).lower() == "x":
            chosen.add(marker.group(1))
    return chosen


def parse_back_requests(body: str) -> set[str]:
    """معرفات المسودات التي علّم المراجع «أعده للمراجعة الأولية» عليها في
    Issue المراجعة النهائية (Issue #858) -- نفس أسلوب parse_reels حرفيًا."""
    chosen: set[str] = set()
    for line in body.splitlines():
        marker = BACK_MARKER.search(line)
        if not marker:
            continue
        checkbox = re.search(r"\[([ xX])\]", line)
        if checkbox and checkbox.group(1).lower() == "x":
            chosen.add(marker.group(1))
    return chosen


def parse_approved(body: str) -> list[str]:
    """يستخرج معرفات المسودات التي عُلّم عليها ✔️."""
    approved: list[str] = []
    for line in body.splitlines():
        if REEL_MARKER.search(line):
            continue                      # اختيار الريل لا الاعتماد
        marker = ID_MARKER.search(line)
        if not marker:
            continue
        checkbox = re.match(r"\s*[-*]\s*\[([ xX])\]", line)
        if checkbox and checkbox.group(1).lower() == "x":
            approved.append(marker.group(1))
    return approved


def all_draft_ids(body: str) -> list[str]:
    return ID_MARKER.findall(body)


def parse_captions(body: str) -> dict[str, str]:
    """يقرأ نصوص المنشورات المحرَّرة يدويًا داخل كتل ``<!-- cap:id -->``
    (Issue #752). تسامحها إلزامي — المحرِّر بشر على هاتف، فقد تختفي
    المسافتان البادئتان أو تزيدان أو يتغيّر سطر فارغ: يُقشر حتى مسافتين
    بادئتين من كل سطر فقط (لا أكثر — إزاحة أعمق قد تكون مقصودة في النص
    نفسه)، وتُتجاهل سطور ```‎ فتح/إغلاق الكتلة، ويُعاد الباقي كما هو."""
    out: dict[str, str] = {}
    for draft_id, block in CAP_MARKER.findall(body or ""):
        lines = []
        for raw_line in block.splitlines():
            line = re.sub(r"^ {1,2}", "", raw_line)
            if line.strip() == "```":
                continue
            lines.append(line)
        out[draft_id] = "\n".join(lines).strip("\n")
    return out


def image_source_line(draft: dict) -> str:
    """سطر «المصدر:» في نص Issue المراجعة (Issue #752، تصحيح Issue #756) —
    يصف من أين جاءت صورة البطاقة (لا الناشر نفسه، ذاك سطر منفصل) قبل
    الاعتماد. يقرأ حقل ``image_info`` الذي تكتبه مواضع بناء البطاقة
    الخمسة/setimage.apply_image؛ غيابه وحده لا يكفي للحكم بـ«مسودة سابقة»:
    مسودة التحليل (youtube_publish.build_draft) تُعرَض في Issue مراجعتها
    **قبل** بناء بطاقتها (Issue #680 — البطاقة تُبنى عند الاعتماد فقط) فلا
    تحمل ``image_info`` ولا ``image`` معًا رغم كونها جديدة تمامًا؛ مسودة
    قديمة فعليًا (من قبل حقل image_info) تحمل ``image`` بلا ``image_info``.
    التمييز إذن بحقل ``image``: غيابه مع غياب image_info = بطاقة لم تُبنَ
    بعد، لا مسودة سابقة."""
    info = draft.get("image_info")
    if info is None:
        if not draft.get("image"):
            return "🖼️ **المصدر:** البطاقة لم تُبنَ بعد — تُبنى عند الاعتماد"
        return "🖼️ **المصدر:** غير مسجَّل (مسودة سابقة)"
    if info.get("manual"):
        return "🖼️ **المصدر:** رابط وضعتَه يدويًا — المسؤولية عليك"
    if info.get("illustrative"):
        return ("🖼️ **المصدر:** صورة تعبيرية حرة (ويكيميديا/Openverse) — "
                "ليست من مكان الحدث")
    if info.get("used_original"):
        line = "🖼️ **المصدر:** صورة الناشر — أصلية"
        if info.get("composite"):
            line += " · مدمجة من صورتين"
        return line
    return "🖼️ **المصدر:** بلا صورة — البطاقة على خلفية مصممة"


# مربعات اختيار العنوان: <!-- hl:المعرّف:الفهرس --> (نُقلت من
# youtube_publish.py -- Issue #756: مسار الأخبار يحتاج نفس آلية اختيار
# العنوان التي بناها مسار التحليل، فهذه الوحدة -- لا youtube_publish --
# الموضع المشترك الصحيح. youtube_publish.py يستورد الاسمين هنا على مستوى
# الوحدة كي يبقى ``youtube_publish.parse_headline_choice`` قابلًا للنداء
# كما هو من publish.py بلا تغيير في ذلك النداء.
HEADLINE_BOX_RE = re.compile(
    r"^\s*-\s*\[([ xX])\]\s*.*?<!--\s*hl:([0-9a-f]+):(\d+)\s*-->", re.MULTILINE)


def parse_headline_choice(body: str) -> dict[str, int]:
    """يقرأ اختيار المراجع بين العناوين الثلاثة (Issue #680، عُمِّم لمسارات
    الأخبار/الطلب/التحقق/المقال في Issue #756) من نص Issue المراجعة --
    معرّف المسودة ← فهرس العنوان المعلَّم. مسودة لم تُعلَّم على أيّ عنوان
    فيها (لم تظهر في القاموس المُعاد) تبقى على الافتراضي (٠، الأول) عند
    التطبيق. أكثر من عنوان معلَّم لنفس المسودة (خطأ مراجعة أو تعليم يدوي
    غير دقيق) -- آخر مربع معلَّم في ترتيب ظهور النص يفوز، بلا رفض أو
    تحذير: نفس تسامح parse_approved مع أخطاء التنسيق البسيطة."""
    chosen: dict[str, int] = {}
    for mark, draft_id, idx in HEADLINE_BOX_RE.findall(body or ""):
        if mark.lower() == "x":
            chosen[draft_id] = int(idx)
    return chosen


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


IMG_BOX_RE = re.compile(r"^(\s*)-\s*\[([ xX])\]\s*(.*?)<!--\s*img:([0-9a-f]+)\s*-->",
                        re.MULTILINE)
IMG_URL_RE = re.compile(r"<!--\s*imgurl:([0-9a-f]+)\s*-->")
URL_RE = re.compile(r"https?://\S+")


def parse_image_requests(body: str) -> list[tuple[str, str]]:
    """
    يقرأ طلبات استبدال الصورة: مربع معلَّم + رابط في سطر الفراغ.

    الرابط يُلتقط من أي موضع في سطر الفراغ، لأن اللصق على الهاتف قد يقع
    قبل العلامة أو بعدها. مربع معلَّم بلا رابط يُهمَل — لا يُخمَّن.
    """
    urls: dict[str, str] = {}
    for line in (body or "").splitlines():
        match = IMG_URL_RE.search(line)
        if not match:
            continue
        found = URL_RE.search(IMG_URL_RE.sub(" ", line))
        if found:
            urls[match.group(1)] = found.group(0).rstrip(").,>،")

    out = []
    for _, mark, _, draft_id in IMG_BOX_RE.findall(body or ""):
        if mark.lower() == "x" and draft_id in urls:
            out.append((draft_id, urls[draft_id]))
    return out


def clear_image_request(body: str, draft_id: str, keep_url: bool = False) -> str:
    """يُفرغ المربع بعد تنفيذه: وإلا أعاد كل تحرير لاحق تنفيذ الطلب نفسه."""
    lines = []
    for line in body.splitlines():
        if f"<!-- img:{draft_id} -->" in line:
            line = re.sub(r"-\s*\[[xX]\]", "- [ ]", line, count=1)
        elif f"<!-- imgurl:{draft_id} -->" in line and not keep_url:
            indent = line[:len(line) - len(line.lstrip())]
            line = f"{indent}الرابط:   <!-- imgurl:{draft_id} -->"
        lines.append(line)
    return "\n".join(lines)


def update_issue_body(issue_number: int, body: str) -> None:
    repo = _repo()
    requests.patch(
        f"{API}/repos/{repo}/issues/{issue_number}",
        headers=_headers(),
        json={"body": body},
        timeout=45,
    ).raise_for_status()


def fetch_issue_body(issue_number: int) -> str:
    repo = _repo()
    resp = requests.get(f"{API}/repos/{repo}/issues/{issue_number}",
                        headers=_headers(), timeout=45)
    resp.raise_for_status()
    return resp.json().get("body") or ""


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
        ("pending-selection", "c5def5", "مرشحون بانتظار الاختيار قبل الصياغة"),
        ("final-review", "1d76db", "مراجعة نهائية للبطاقة قبل النشر"),
        ("approved", "0e8a16", "معتمد للنشر"),
        ("rejected", "d73a4a", "مرفوض — سجّل الأسباب"),
        ("published", "5319e7", "تم النشر على فيسبوك"),
    ]
    for name, color, desc in wanted:
        requests.post(
            f"{API}/repos/{repo}/labels",
            headers=_headers(),
            json={"name": name, "color": color, "description": desc},
            timeout=30,
        )
