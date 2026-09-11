"""مرحلة الاختيار قبل الصياغة (Issue #280): وفّر ثمن الصياغة والصورة على
مرشحين يُرفضون لاحقًا في المراجعة، عبر عرض العناوين الخام فقط للاختيار
البشري قبل إنفاق أي شيء عليها.

بديل لدورة "صُغ ثم راجِع" الحالية لا إضافة إليها (`config.yaml:
preselect.enabled`) — يحلّ محلها حين يُفعَّل. بناء المرشحين هنا لا يستدعي
Sonnet (الصياغة) ولا يبني صورة؛ الترتيب والفرز الأوليان (Haiku) وقعا قبل
هذه النقطة في collect.py وهما شبه مجانيين أصلًا (انظر التشخيص في Issue
#280). الصياغة الفعلية تقع لاحقًا في collect_finalize.py، للمختار فقط.

كل مرشح يحمل ثلاثة مربعات لا واحدًا (Issue #319 ثم #860): 🚀 «انشر فورًا»
(صياغة ثم نشر مباشر — سلوك preselect الأصلي)، 📝 «صغ واعرض عليّ قبل
النشر» (صياغة ثم حفظ كمسودة عادية بانتظار مراجعة أولية كاملة)، و🎴 «صُغ
واعرض البطاقة» (صياغة وبناء بطاقة ثم مراجعة نهائية للبطاقة وحدها مباشرة،
بلا مراجعة أولية — Issue #860). هذا يوحّد أيضًا معاملة مرشحي الرادار
الذين لم يستوفوا شروط النشر التلقائي (`radar.preselect_fallback`) مع
مرشحي collect.py — كلاهما يُبنى بـ`build_candidate` نفسها ويظهر بنفس
المربعات الثلاثة في Issue الاختيار بلا أي تمييز.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, fields
from datetime import datetime, timezone

from anthropic import Anthropic, APIError

from .config import env
from .sources import Article
from .writer import record_usage

log = logging.getLogger(__name__)

CAND_MARKER = re.compile(r"<!--\s*cand:([0-9a-f]+)\s*-->")
# مربعا الاختيار (Issue #319): "now" = انشر فورًا بلا عرض، "review" = صغ
# واعرض عليّ أولًا. اسمان منفصلان عمدًا عن "cand" (يبقى معرّف العنوان
# نفسه) وعن "draft" (اسم مربع الاعتماد في review.py — Issue مختلف).
PUBNOW_MARKER = re.compile(r"<!--\s*now:([0-9a-f]+)\s*-->")
DRAFTFIRST_MARKER = re.compile(r"<!--\s*review:([0-9a-f]+)\s*-->")
# مربع ثالث (Issue #860): 🎴 صُغ واعرض البطاقة — يقفز من الاختيار إلى
# مراجعة نهائية للبطاقة مباشرة، بلا مراجعة أولية. بادئة "sel-card" لا
# "card" عمدًا: review.CARD_MARKER تستعمل "card:" بنفس الشكل لكن في Issue
# المراجعة الأولية (Issue #858) — Issue مختلف تمامًا لا يلتقي بهذا أبدًا،
# لكن بادئة منفصلة تمنع أي قارئ من التقاط علامات الآخر لو تغيّر شيء لاحقًا.
CARDONLY_MARKER = re.compile(r"<!--\s*sel-card:([0-9a-f]+)\s*-->")


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
        "impact": art.impact,
        "proximity": art.proximity,
        "intrigue": art.intrigue,
        "appeal_note": art.appeal_note,
        "bucket": art.bucket,
        "state_media": art.state_media,
        "title": art.title,
        "link": art.link,
        "publishers": art.cluster_sources or [art.publisher],
        "region": art.region,
        "article": article_to_dict(art),
    }


# ──────────────────────────── ترجمة العناوين ────────────────────────────

# نسبة أحرف عربية بين حروف العنوان: فوقها يُعدّ العنوان عربيًا أصلًا فلا
# يُرسَل للترجمة — العتبة نفسها في config.yaml (preselect.translate.
# arabic_skip_ratio) لا هنا، كي تُضبط بلا تعديل كود.
_ARABIC_RE = re.compile(r"[؀-ۿ]")
_ALPHA_RE = re.compile(r"[^\W\d_]", re.UNICODE)

TRANSLATE_SYSTEM = """أنت مترجم أخبار. تصلك عناوين مرقّمة بلغات مختلفة.
ترجم كل عنوان إلى عربية صحفية مختصرة وواضحة (لا تتجاوز طوله الأصلي
تقريبًا) بلا شرح ولا إضافة. أخرج JSON فقط بالشكل:
{"translations": {"1": "الترجمة الأولى", "2": "الترجمة الثانية"}}"""


def _arabic_ratio(title: str) -> float:
    letters = _ALPHA_RE.findall(title)
    if not letters:
        return 0.0
    arabic = len(_ARABIC_RE.findall(title))
    return arabic / len(letters)


def _client() -> Anthropic:
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def _parse_translations(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise
        data = json.loads(text[start : end + 1])
    return data.get("translations") or {}


def translate_titles(candidates: list[dict], cfg) -> dict[str, str]:
    """
    ترجمة عربية مختصرة لعناوين المرشحين — استدعاء Haiku واحد للدفعة كلها
    معًا (لا استدعاء لكل عنوان)، أقل تكلفة ممكنة. تغطي مرشحي collect
    والرادار معًا لأنها تُستدعى مرة واحدة من open_review.py على القائمة
    المدموجة.

    تُستبعد العناوين العربية أصلًا قبل الإرسال (توفير إضافي). أي فشل —
    مفتاح API غائب، عطل شبكة، JSON غير صالح — يُعامَل بصمت: تُعاد {} فتُعرض
    العناوين الأصلية بلا ترجمة ولا يتوقف المسار.

    تعيد {معرّف المرشح: الترجمة} لمن تُرجم فعلًا فقط.
    """
    tcfg = (cfg.get("preselect", {}) or {}).get("translate", {}) or {}
    if not tcfg.get("enabled", True) or not candidates:
        return {}

    threshold = float(tcfg.get("arabic_skip_ratio", 0.4))
    todo = [c for c in candidates if _arabic_ratio(c.get("title", "")) < threshold]
    skipped = len(candidates) - len(todo)
    if not todo:
        log.info("ترجمة العناوين: 0 تُرجم، %d عربي أصلًا تُخُطّي، 0 دفعة",
                 skipped)
        return {}

    model = tcfg.get("model", "claude-haiku-4-5-20251001")
    listing = "\n".join(f"{i}. {c['title']}" for i, c in enumerate(todo, start=1))

    try:
        client = _client()
        resp = client.messages.create(
            model=model,
            max_tokens=int(tcfg.get("max_tokens", 1500)),
            system=TRANSLATE_SYSTEM,
            messages=[{"role": "user", "content": f"ترجم هذه العناوين:\n\n{listing}"}],
        )
        record_usage(resp, model)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        raw = _parse_translations(text)
    except (RuntimeError, APIError, json.JSONDecodeError, ValueError) as exc:
        log.warning("فشلت ترجمة عناوين المرشحين — ستُعرض بلا ترجمة: %s", exc)
        return {}

    out: dict[str, str] = {}
    for i, c in enumerate(todo, start=1):
        translated = raw.get(str(i))
        if translated:
            out[c["id"]] = translated

    log.info("ترجمة العناوين: %d تُرجم، %d عربي أصلًا تُخُطّي، %d بلا نتيجة",
             len(out), skipped, len(todo) - len(out))
    return out


# ──────────────────────────── بناء نص الاختيار ────────────────────────────


def build_selection_issue_body(candidates: list[dict],
                               translations: dict[str, str] | None = None) -> str:
    translations = translations or {}
    parts = [
        "### 🗳️ مرشحون بانتظار الاختيار",
        "",
        "**بلا صياغة ولا صورة بعد** — هذه العناوين الخام كما وردت من "
        "المصادر، قبل أي إنفاق. لكل مرشح ثلاثة مربعات مستقلة — علّم ما "
        "تريده لكل خبر على حدة (يمكن مزج الطرق الثلاث في نفس الدفعة)، ثم "
        "أضف الوسم `approved`:",
        "",
        "🚀 نشر مباشر · 📝 مراجعة أولية (نص وعناوين وتعديل) · 🎴 بطاقة "
        "مباشرة (بلا اختيار عنوان ولا تعديل نص).",
        "",
        "- 🚀 **انشر فورًا** — يُصاغ الخبر وتُبنى صورته وينشر مباشرة بلا "
        "عرض ثانٍ عليك.",
        "- 📝 **صغ واعرض عليّ قبل النشر** — يُصاغ الخبر وتُبنى صورته "
        "وتُحفظ مسودة عادية في Issue مراجعة منفصل تعتمده بنفسك (فيه "
        "مربعات العناوين وكتلة النص القابلة للتحرير).",
        "- 🎴 **صُغ واعرض البطاقة (بلا مراجعة أولية)** — يُصاغ الخبر "
        "وتُبنى بطاقته مباشرة، وتُعرض عليك بطاقة جاهزة في Issue مراجعة "
        "نهائية للاعتماد قبل النشر فقط — بلا اختيار عنوان ولا تعديل نص.",
        "",
        "علّمت أكثر من مربع لخبر واحد بالخطأ؟ الأحوط يغلب: 📝 تغلب 🚀 "
        "و🎴 معًا (المراجعة الأولية أوسع)، و🎴 تغلب 🚀 وحدها — وسيُعلَّق "
        "تنبيه بذلك.",
        "",
        "🚫 **ما لا تعلّمه لن يُصاغ** ويُسجَّل «لم يُختر» — وسأسألك عن "
        "السبب في التقرير الأسبوعي.",
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
        # عوامل الجذب التحريرية الثلاثة (Issue #876) — تظهر دومًا، حتى عند
        # صفر، انظر التوثيق المقابل في review.py:build_issue_body.
        badge += (f" · 💰 أثر {c.get('impact', 0)} · 🫱 قرب {c.get('proximity', 0)}"
                  f" · ✨ تشويق {c.get('intrigue', 0)}")

        parts += [
            f"**{idx}. {c['title']}**  <!-- cand:{c['id']} -->",
            "",
        ]
        translated = translations.get(c["id"])
        if translated:
            parts += [f"  🔤 {translated}", ""]

        parts += [
            f"  {badge} · مؤشر الترند `{c['score']:.1f}` · المصادر: "
            f"{'، '.join(c['publishers'][:3])}",
            "",
            *([f"  <sub>{c['appeal_note']}</sub>", ""] if c.get("appeal_note") else []),
            f"  ↳ [الخبر الأصلي]({c['link']})",
            "",
            f"  - [ ] 🚀 انشر فورًا (صياغة ثم نشر مباشر بلا عرض)  "
            f"<!-- now:{c['id']} -->",
            f"  - [ ] 📝 صغ واعرض عليّ قبل النشر  <!-- review:{c['id']} -->",
            f"  - [ ] 🎴 صُغ واعرض البطاقة (بلا مراجعة أولية)  "
            f"<!-- sel-card:{c['id']} -->",
            "",
            "---",
            "",
        ]

    parts.append("<sub>وسم `approved` = تنفيذ ما عُلِّم عليه لكل مرشح · "
                 "إغلاق الـ Issue بلا تعليم = تجاهل الكل بلا أي إنفاق</sub>")
    return "\n".join(parts)


# ──────────────────────────── قراءة الاختيار ────────────────────────────


def _checked_ids(body: str, marker: re.Pattern) -> list[str]:
    chosen: list[str] = []
    for line in body.splitlines():
        match = marker.search(line)
        if not match:
            continue
        checkbox = re.match(r"\s*[-*]\s*\[([ xX])\]", line)
        if checkbox and checkbox.group(1).lower() == "x":
            chosen.append(match.group(1))
    return chosen


def parse_publish_now(body: str) -> list[str]:
    """يعيد معرفات المرشحين المُعلَّمين على «🚀 انشر فورًا»."""
    return _checked_ids(body, PUBNOW_MARKER)


def parse_draft_review(body: str) -> list[str]:
    """يعيد معرفات المرشحين المُعلَّمين على «📝 صغ واعرض عليّ قبل النشر»."""
    return _checked_ids(body, DRAFTFIRST_MARKER)


def selected_card_ids(body: str) -> list[str]:
    """يعيد معرفات المرشحين المُعلَّمين على «🎴 صُغ واعرض البطاقة» (بلا
    مراجعة أولية) — بنفس أسلوب parse_publish_now/parse_draft_review."""
    return _checked_ids(body, CARDONLY_MARKER)


def all_candidate_ids(body: str) -> list[str]:
    # dict.fromkeys بدل set() للحفاظ على ترتيب الظهور — لا فرق وظيفيًا هنا
    # (كل معرّف يظهر مرة واحدة في سطر العنوان) لكنه أوضح من إعادة SET.
    return list(dict.fromkeys(CAND_MARKER.findall(body)))
