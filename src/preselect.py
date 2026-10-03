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
from urllib.parse import urlparse

from anthropic import Anthropic, APIError

from . import stages
from .config import env, load_config
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


def _translate_max_tokens(n_todo: int, tcfg: dict) -> int:
    """يحسب سقف رد translate_titles من عدد العناوين المطلوب ترجمتها (Issue
    #1063): preselect.translate.max_tokens (1500) كان سقفًا ثابتًا لا يتحرك
    مع حجم الدفعة — صار حدًّا أدنى فقط. tokens_per_title/max_tokens_cap
    مفتاحان جديدان تحت preselect.translate."""
    min_tokens = int(tcfg.get("max_tokens", 1500))
    tokens_per_title = int(tcfg.get("tokens_per_title", 60))
    cap = int(tcfg.get("max_tokens_cap", 6000))
    return min(cap, max(min_tokens, tokens_per_title * n_todo + 300))


def translate_titles(candidates: list[dict], cfg) -> dict[str, str]:
    """
    ترجمة عربية مختصرة لعناوين المرشحين — استدعاء Haiku واحد للدفعة كلها
    معًا (لا استدعاء لكل عنوان)، أقل تكلفة ممكنة. تغطي مرشحي collect
    والرادار معًا لأنها تُستدعى مرة واحدة من open_review.py على القائمة
    المدموجة.

    تُستبعد العناوين العربية أصلًا قبل الإرسال (توفير إضافي). أي فشل —
    مفتاح API غائب، عطل شبكة، JSON غير صالح — يُعامَل بصمت: تُعاد {} فتُعرض
    العناوين الأصلية بلا ترجمة ولا يتوقف المسار.

    السقف (Issue #1063) يُحسب من عدد العناوين المطلوب ترجمتها
    (_translate_max_tokens) بدل ثابت preselect.translate.max_tokens وحده.
    القطع (stop_reason == "max_tokens") — كان يقع ضمن except العام فتُعرض
    العناوين بلا ترجمة بتحذير عام — يُكشف الآن صراحةً بسطر ERROR يسمّي عدد
    العناوين والسقف، ثم إعادة محاولة واحدة بسقف مضاعف (مقصوص عند
    max_tokens_cap). ترجمة جزئية (بعض العناوين فقط، بلا قطع) ليست فشلًا —
    السلوك القائم يبقى كما هو حرفيًا: كل عنوان غير مذكور في الرد يُعرض بلا
    ترجمة، بلا إعادة محاولة.

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
    n_todo = len(todo)
    max_tokens = _translate_max_tokens(n_todo, tcfg)
    cap = int(tcfg.get("max_tokens_cap", 6000))

    def _call(tokens: int):
        client = _client()
        resp = client.messages.create(
            model=model,
            max_tokens=tokens,
            system=TRANSLATE_SYSTEM,
            messages=[{"role": "user", "content": f"ترجم هذه العناوين:\n\n{listing}"}],
        )
        record_usage(resp, model)
        return resp

    try:
        resp = _call(max_tokens)
    except (RuntimeError, APIError) as exc:
        log.warning("فشلت ترجمة عناوين المرشحين — ستُعرض بلا ترجمة: %s", exc)
        return {}

    if getattr(resp, "stop_reason", "") == "max_tokens":
        log.error(
            "ترجمة العناوين مقطوعة (stop_reason=max_tokens) لـ%d عنوانًا — "
            "السقف %d غير كافٍ", n_todo, max_tokens)
        retry_tokens = min(cap, max_tokens * 2)
        try:
            resp = _call(retry_tokens)
        except (RuntimeError, APIError) as exc:
            log.warning("فشل نداء إعادة محاولة ترجمة العناوين: %s", exc)
            return {}
        if getattr(resp, "stop_reason", "") == "max_tokens":
            # لا سطر ERROR ثانٍ هنا — الأول أعلاه سمّى القطع سببًا صراحةً
            # بالفعل (نفس مبدأ screen.py/_ask_naming_model: ERROR واحد لكل
            # نداء مرحلة، لا واحد لكل محاولة).
            return {}

    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    try:
        raw = _parse_translations(text)
    except (json.JSONDecodeError, ValueError) as exc:
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


SELIMG_MARKER = re.compile(r"<!--\s*selimg:([0-9a-f]+)\s*-->")


def displayed_image_url(c: dict) -> str | None:
    """الصورة التي تُعرض في قضية الترشيح: رابط المراجع اليدوي إن وُجد (Issue
    #1190) وإلا صورة الناشر نفسها التي يعرضها review في المرحلة 2."""
    if c.get("manual_image"):
        return c["manual_image"]
    art = c.get("article") or {}
    return art.get("image_url") or next(
        (u for u in art.get("image_candidates") or [] if u), None)


def image_display_lines(c: dict) -> list[str]:
    """<img> بعرض 520 كما في المرحلة 2، بعلامة selimg كي يستبدل setimage
    الصورة المعروضة في جسم القضية لاحقًا بلا إعادة بناء الجسم كله."""
    url = displayed_image_url(c)
    if not url:
        return []
    return [f"  <img src=\"{url}\" width=\"520\" />  <!-- selimg:{c['id']} -->", ""]


def image_line(c: dict, cfg=None) -> str:
    """سطر 🖼️ للمراجع فقط (Issue #1174): الصورة المتاحة للمرشح لا ما سينجح
    تحميله. بلا أي علامة HTML ولا مربع كي لا يلتقطه أي قارئ لجسم القضية."""
    # السقف من الإعداد نفسه الذي ينسخ به collect_finalize الروابط، فالعدد
    # المعروض هو عدد ما سيجرّبه cards.ensure فعلًا
    cfg = cfg if cfg is not None else load_config()
    related_max = int(cfg.path("collect.related_links_max", 3))
    art = c.get("article") or {}
    if c.get("manual_image"):
        # رابط المراجع يغلب كل بدائل الصياغة (cards.ensure يعطي manual_image
        # الأولوية المطلقة)، فلا معنى لسرد بدائل لن تُجرَّب
        url = c["manual_image"]
        return (f"  🖼️ [صورتك]({url}) · {urlparse(url).netloc} — "
                "تُستعمل عند الصياغة")
    url = displayed_image_url(c)
    if url:
        domain = urlparse(url).netloc
        return f"  🖼️ [صورة الناشر]({url}) · {domain}"
    own = c.get("link") or art.get("link")
    others: list[str] = []
    for m in art.get("cluster_members") or []:
        link = (m or {}).get("link")
        if not link or link == own or link in others:
            continue
        others.append(link)
        if len(others) >= related_max:
            break
    if others:
        n = len(others)
        if n == 1:
            tried = "صورة ناشر آخر"
        elif n == 2:
            tried = "صور ناشرَين آخرَين"
        else:
            tried = f"صور {n} ناشرين آخرين"
        return f"  🖼️ بلا صورة من الناشر · ستُجرَّب {tried} ثم بحث الويب"
    return "  🖼️ بلا صورة من الناشر ولا بدائل · بحث الويب وحده"


def show_manual_image(body: str, cand: dict, url: str) -> str:
    """يبدّل في جسم قضية ترشيح قائمة الصورة المعروضة لمرشح بصورة المراجع
    (Issue #1190): يحذف <img> الناشر القديم إن وُجد ويضع الجديد قبل سطر 🖼️
    الذي يُستبدل بسطر الصورة اليدوية. العمل داخل مقطع المرشح وحده."""
    cid = cand["id"]
    shown = {**cand, "manual_image": url}
    lines = body.splitlines()
    start = next((i for i, ln in enumerate(lines) if f"<!-- cand:{cid} -->" in ln), None)
    if start is None:
        return body
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == "---"),
               len(lines))
    out = lines[:start + 1]
    seg = lines[start + 1:end]
    i = 0
    while i < len(seg):
        ln = seg[i]
        if f"<!-- selimg:{cid} -->" in ln:
            i += 2 if i + 1 < len(seg) and not seg[i + 1].strip() else 1
            continue
        if ln.lstrip().startswith("🖼️ ") and "<!--" not in ln:
            out += image_display_lines(shown) + [image_line(shown)]
            i += 1
            continue
        out.append(ln)
        i += 1
    return "\n".join(out + lines[end:])


def build_selection_issue_body(candidates: list[dict],
                               translations: dict[str, str] | None = None,
                               cfg=None) -> str:
    """نص قضية المرحلة 1 للأخبار (Issue #1190، المهمة 4 من توحيد المراحل):
    الرأس والشرح وكتلة الانتقال من stages، ولا مربع فوق بيانات أي مرشح ولا على
    سطر عنوانه. ترتيب المرشح: العنوان (علامة cand: وحدها) ← الترجمة ← الشارات
    والمصادر ← الصورة معروضة إن وُجدت ← سطر 🖼️ ← الخبر الأصلي ← حقل رابط
    الصورة ← خيارات الانتقال."""
    cfg = cfg if cfg is not None else load_config()
    translations = translations or {}
    parts = [
        stages.stage_header(1, cfg),
        "",
        cfg.path("stages.explainer_stage1", ""),
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

        title_line = c["title"]
        if c.get("returned"):
            # مرشح أعاده المراجع من المرحلة 2/3 (Issue #1184): الشارة أمام
            # العنوان فيعرف أنه رآه وقرر الرجوع به، لا أنه خبر جديد.
            from_stage = c.get("returned_from_stage") or 2
            badge_text = cfg.path(
                "stages.returned_badge", "↩️ أعدته من المرحلة {stage}"
            ).format(stage=from_stage)
            title_line = f"{badge_text} · {title_line}"
        parts += [
            f"**{idx}. {title_line}**  <!-- cand:{c['id']} -->",
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
            *image_display_lines(c),
            image_line(c, cfg),
            "",
            f"  ↳ [الخبر الأصلي]({c['link']})",
            "",
            stages.image_field(c["id"], cfg),
            "",
            *stages.options_block(1, c["id"], cfg, has_stage1=False),
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
