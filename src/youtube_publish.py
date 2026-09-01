"""المرحلة الخامسة من مسار يوتيوب (Issue #676): توصيل المسار التحليلي
(youtube_collect → youtube_extract → youtube_cluster → youtube_article) بما
كان قائمًا في المشروع قبله — بطاقة صورة، مسودة في drafts/، Issue مراجعة،
ونشر عبر facebook/publish. لا تعديل على منطق imaging أو store أو review أو
publish هنا — استعمال فقط، وقالب صورة جديد.

**بطاقة العنوان لا تستقبل أبدًا نص المقال ولا أي رابط صورة** (انظر
build_title_card أدناه): الحقول الممرَّرة عنوان + طبقة + كتل + قنوات فقط،
فسطر التقدير وصور الفيديو/القناة/الأشخاص ممنوعة *بنيويًا* لا اجتهادًا —
لا سبيل لتسريبها إلى البطاقة عبر توقيع الدالة نفسه.

**تنبيهات المراجعة تُنزَع من caption قبل أي نشر** (split_warnings) — تبقى في
حقل warnings المنفصل وفي Issue المراجعة فقط، فلا تصل فيسبوك إطلاقًا.

**وسم الاعتماد `youtube-approved` لا `approved`**: publish.yml القائم يشترك
مع أي Issue في المستودع بمجرّد وسمه `approved` (لا فحص عنوان أو وسم آخر)،
وسقفه وتباعده ثابتان (gap_min/gap_max العشوائيان) لا يعرفان
youtube.publish.max_per_run/spacing_minutes الذي يطلبه الـIssue #676 صراحةً.
تشغيله على Issue يحمل `approved` أيضًا كان يعني نشرًا مزدوجًا فعليًا (مرة عبر
publish.yml العام بمنطقه الخاص، ومرة عبر publish_approved هنا) — races حقيقية
على حالة "published" في نفس الملف. وسم مخصّص يفصل المسارين بنيويًا دون لمس
publish.yml (لا صلاحية لتعديل ملفات .github/workflows أصلًا).

**build() ثم open_review() منفصلتان لا دالة واحدة** — نفس تسلسل src/collect.py
+ src/open_review.py بالضبط: الصور تُبنى وتُحفَظ محليًا (build)، ثم يجب أن
تُدفَع إلى المستودع (خطوة git commit/push في الـworkflow) **قبل** فتح Issue
المراجعة (open_review)، وإلا 404 روابط raw.githubusercontent.com فيه (قيد
موثَّق في CLAUDE.md وtests/test_pipeline.py لسير الجمع الأصلي، ينطبق هنا
حرفيًا لنفس السبب). دمجهما في نداء واحد كان يفتح الـ Issue قبل أن تصل الصور
إلى الفرع. open_review() تفلتر على origin == "youtube" تحديدًا (لا
store.pending_drafts() الخام كما في src/open_review.py) حتى لا تلتقط مسودات
المسار العام العادي التي قد تكون معلَّقة في نفس اللحظة (لا تشترك
youtube-articles.yml وcollect.yml مجموعة تزامن واحدة، فتشغيلهما معًا وارد) —
وتُثبِّت review_issue على كل مسودة فور فتح الـ Issue، فتخرج من نافذة الالتقاط
لأي فحص لاحق. نافذة سباق ضيقة تبقى نظريًا بين خطوة build ودفع الصور إن شغّل
أحد سير collect.yml بالتزامن تمامًا؛ لم تُعالَج جذريًا (تحتاج قفلًا عابرًا
للسيرين، خارج نطاق هذه المهمة) — نفس فئة السباق الموثَّقة أصلًا في تعليقات
إعادة محاولة git push بين «الجمع والرادار».

Issue #680 (دورة المراجعة: ترتيب، تأجيل البطاقة، عناوين متعدّدة) غيّر ثلاثة
أشياء في هذه الوحدة تحديدًا -- التحليل (المراحل ١-٣) وبنية المقال (خارج
النطاق) لم يُمسَّا:

(١) **الترتيب بالطبقة وحدها كان يظلم مقالات قوية** -- طبقة (أ/ب/ج) تُحسَب من
**وجود** كتلتين لا من **عدد** المصادر الفعلي، فقضية من ثلاث قنوات في كتلة
واحدة (طبقة ب) كانت تُرتَّب دومًا بعد قضية من قناتين في كتلتين (طبقة أ) رغم
كونها أقوى مادةً. compute_score يحسب درجة مركّبة برمجيًا (عدد القنوات +
مكافأة كتل إضافية + مكافأة نوع الخلاف، القيم في config.yaml:
youtube.review.scoring) وتُخزَّن في كل مسودة (حقل score) ويُرتَّب بها
_review_sort_key تنازليًا، وتُعرَض مكوّناتها نصًّا (score_breakdown_text) في
كل بطاقة مراجعة كي يرى المالك *لماذا* رُتِّب المقال هكذا لا الرقم وحده.

(٢) **البطاقات كانت تُبنى قبل الاختيار** -- سبع بطاقات لسبعة مقالات يُنشر
منها ثلاثة، أربع مهدرة والمستودع يمتلئ بصور لا تُستعمل. build() لم يعد يبني
أي بطاقة إطلاقًا (ولا يستدعي build_title_card)؛ open_review() يفتح الـIssue
**بلا صور** (لا رابط raw ولا blob في build_review_body). البطاقة الوحيدة
تُبنى عند publish_approved() -- بعد الوسم، للمختار فقط -- عبر
ensure_title_card()، بنفس مبدأ publish.ensure_reel() اللاحق تمامًا (يبني
الريل عند الطلب لا عند الجمع): مورد الحوسبة يُصرف على ما اختاره المراجع
فعليًا لا على كل مرشح. لم يحتج هذا أي تعديل على ملفات .github/workflows/ --
الخطوة القائمة "بناء البطاقات والمسودات" في youtube-articles.yml تستدعي
`python -m src.youtube_publish` بلا خيارات، وbuild() نفسها صارت لا تبني
بطاقات؛ وخطوة "نشر المؤشَّر" القائمة في youtube-publish.yml (`--publish`)
هي بالضبط ما يستدعي publish_approved() بعد الوسم، فبناء البطاقة يقع داخلها
بنيويًا بلا نقل أي خطوة يدويًا. (البطاقة نفسها تبقى بلا صورة خبر -- تصميم
Issue #676 المتعمَّد، انظر build_title_card أعلاه؛ لم يُغيَّر هنا، وسبب ذلك
موثَّق في تعليق منفصل على الـPR.)

(٣) **عناوين متعدّدة** -- كل مقال يحمل الآن ثلاثة عناوين مقترحة (يكتبها
src/youtube_article.py: generate_headlines، نداء منفصل عن الكتابة، مذيَّلة
في نصّ المقال ويقرؤها split_headlines هنا) تُعرَض جميعًا في بطاقة المراجعة
بمربعات اختيار (`<!-- hl:id:index -->`)، الأول (سؤال) معلَّم افتراضيًا.
parse_headline_choice تقرأ اختيار المالك من نص الـIssue عند الاعتماد،
وensure_title_card تستعمل العنوان المختار فعليًا في بناء البطاقة والـcaption
معًا (لا البطاقة وحدها) عبر _apply_headline."""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import ImageDraw

from . import imaging, publish, review, store, youtube_article
from .config import DRAFTS_DIR, env, load_config

log = logging.getLogger(__name__)

# نفس القسم الذي يُلحقه youtube_article._append_warnings بذيل المقال —
# مستورَد لا مكرَّر، فتغييره هناك (لو وقع يومًا) لا يكسر هذا الملف بصمت.
WARNINGS_HEADER = youtube_article.WARNINGS_HEADER
SOURCES_HEADING = "## المصادر"

# تُقرأ من كتلة config.yaml (`bloc` القيمة الإنجليزية المخزَّنة في channels)
# — احتياطي فقط إن غاب youtube.image.bloc_labels من الإعداد.
_DEFAULT_BLOC_LABELS = {
    "arabic": "عربية", "turkish": "تركية", "persian": "فارسية", "israeli": "إسرائيلية",
}

_TIER_LABELS = {"a": "أ", "b": "ب", "c": "ج"}
_TIER_RANK = {"a": 0, "b": 1, "c": 2}
# نفس ترتيب src.youtube_cluster._AGREEMENT_RANK (لا نستورده — ثابت صغير لا
# يستحق اعتماد وحدة العنقدة، ونصّ الـIssue يفرض هذا الترتيب صراحةً: خلاف
# القنوات أولًا، فالخلاف الداخلي، فالاتفاق).
_AGREEMENT_RANK = {"cross_source": 0, "internal": 1, "agreement": 2, "echo": 3}
_AGREEMENT_LABELS = {
    "cross_source": "خلاف قنوات", "internal": "خلاف داخلي",
    "agreement": "اتفاق", "echo": "صدى",
}
# نصوص مطوَّلة لسطر مكوّنات الدرجة تحديدًا (score_breakdown_text) -- تختلف
# صياغتها قليلًا عن _AGREEMENT_LABELS المستعملة في السطر الوصفي المختصر
# أعلى كل بطاقة، فهذا سطر تفسيري كامل لا وسم.
_AGREEMENT_SCORE_LABELS = {
    "cross_source": "خلاف بين القنوات", "internal": "خلاف داخلي بين متحدثين",
    "agreement": "اتفاق بين المصادر", "echo": "صدى (نفس الخبر معاد صياغته)",
}
# احتياط فقط إن غاب youtube.review.scoring.agreement_bonus من config.yaml --
# القيم الفعلية المستعملة دومًا تُقرأ من هناك (نصّ الـIssue #680).
_DEFAULT_AGREEMENT_BONUS = {"cross_source": 3, "internal": 1, "agreement": 0, "echo": -2}
_DEFAULT_BLOC_BONUS = 2


# ──────────────────────────── الدرجة المركّبة (Issue #680) ────────────────


def compute_score(blocs: list[str], channels: list[str], agreement: str, cfg=None) -> float:
    """الدرجة = عدد القنوات + (عدد الكتل − ١) × مكافأة الكتلة + مكافأة نوع
    الخلاف (نصّ الـIssue #680) -- تعالج ظلم الترتيب بالطبقة وحدها: الطبقة
    تُحسَب من **وجود** كتلتين لا من **عدد** المصادر، فقضية من ثلاث قنوات في
    كتلة واحدة (طبقة ب) كانت تُرتَّب دومًا بعد قضية من قناتين في كتلتين
    (طبقة أ) بصرف النظر عن قوة موادها الفعلية. القيم قابلة للتعديل بلا كود
    (config.yaml: youtube.review.scoring)."""
    scoring = (cfg.path("youtube.review.scoring", {}) if cfg else {}) or {}
    bloc_bonus = scoring.get("bloc_bonus", _DEFAULT_BLOC_BONUS)
    agreement_bonus = scoring.get("agreement_bonus") or _DEFAULT_AGREEMENT_BONUS
    bonus = agreement_bonus.get(agreement, _DEFAULT_AGREEMENT_BONUS.get(agreement, 0))
    return len(channels) + max(0, len(blocs) - 1) * bloc_bonus + bonus


def _arabic_channel_count_phrase(n: int) -> str:
    if n == 1:
        return "قناة واحدة"
    if n == 2:
        return "قناتان"
    if 3 <= n <= 10:
        return f"{n} قنوات"
    return f"{n} قناة"


def _arabic_bloc_count_phrase(n: int) -> str:
    if n == 1:
        return "كتلة واحدة"
    if n == 2:
        return "كتلتان"
    if 3 <= n <= 10:
        return f"{n} كتل"
    return f"{n} كتلة"


def score_breakdown_text(blocs: list[str], channels: list[str], agreement: str, cfg=None) -> str:
    """"الدرجة ١١ — ٣ قنوات · كتلتان · خلاف بين القنوات" (صياغة الـIssue
    #680 الحرفية) -- يعرض الرقم ومكوّناته معًا كي يرى المالك *لماذا* رُتِّب
    المقال هكذا لا الرقم وحده."""
    score = compute_score(blocs, channels, agreement, cfg)
    agreement_label = _AGREEMENT_SCORE_LABELS.get(agreement, agreement)
    return (f"الدرجة {score:g} — {_arabic_channel_count_phrase(len(channels))} · "
            f"{_arabic_bloc_count_phrase(len(blocs))} · {agreement_label}")


# ──────────────────────────── نصوص بلا شبكة ────────────────────────────


def bloc_label(bloc: str, cfg=None) -> str:
    labels = (cfg.path("youtube.image.bloc_labels", {}) if cfg else {}) or {}
    return labels.get(bloc, _DEFAULT_BLOC_LABELS.get(bloc, bloc))


def bottom_bar_text(tier: str, blocs: list[str], channels: list[str], cfg=None) -> str:
    """"عربية · فارسية — الجزيرة، العربية، Iran International" — لمقال طبقة
    (ج) (مصدر واحد) اسم القناة وحدها بلا ذكر كتلة (نصّ الـIssue #676)."""
    channels_text = "، ".join(channels)
    if tier == "c" or not blocs:
        return channels_text
    blocs_text = " · ".join(bloc_label(b, cfg) for b in blocs)
    return f"{blocs_text} — {channels_text}" if channels_text else blocs_text


def split_warnings(article_text: str) -> tuple[str, list[str]]:
    """يفصل قسم ⚠️ تنبيهات للمراجعة (يُلحقه youtube_article._append_warnings)
    عن متن المقال. **قاعدة حاسمة (نصّ الـIssue #676):** هذا القسم يُنزَع من
    caption قبل النشر ولا يظهر على فيسبوك إطلاقًا — يبقى في حقل warnings
    المنفصل وفي Issue المراجعة فقط. مقال بلا القسم أصلًا (صفر تنبيهات) يعود
    بلا تغيير غير التنظيف السطحي."""
    idx = article_text.find(WARNINGS_HEADER)
    if idx == -1:
        return article_text.strip() + "\n", []

    body = article_text[:idx].rstrip()
    if body.endswith("---"):
        body = body[:-3].rstrip()

    tail = article_text[idx + len(WARNINGS_HEADER):]
    warnings = [line.strip().lstrip("-").strip()
                for line in tail.splitlines() if line.strip().startswith("-")]
    return body + "\n", warnings


_HEADLINE_LINE_RE = re.compile(r"^\d+\.\s*(.+?)\s*$")


def split_headlines(article_text: str) -> tuple[str, list[str]]:
    """يفصل قسم 🏷️ عناوين مقترحة (يُلحقه youtube_article._append_headlines
    في ذيل المقال، بعد قسم التحذيرات إن وُجد -- انظر ترتيب النداءات في
    youtube_article.run()) عن متن المقال. مقال بلا القسم أصلًا (مسار قديم
    من قبل Issue #680، أو اختبار لا يبنيه) يعيد قائمة فارغة بلا استثناء --
    الاستدعاء في build_draft يحتاط بعنوان index.md الأصلي عندها."""
    idx = article_text.find(youtube_article.HEADLINES_HEADER)
    if idx == -1:
        return article_text.strip() + "\n", []

    body = article_text[:idx].rstrip()
    if body.endswith("---"):
        body = body[:-3].rstrip()

    tail = article_text[idx + len(youtube_article.HEADLINES_HEADER):]
    headlines = []
    for line in tail.splitlines():
        m = _HEADLINE_LINE_RE.match(line.strip())
        if m:
            headlines.append(m.group(1))
    return body + "\n", headlines


def extract_source_lines(article_body: str) -> list[str]:
    """أسطر قسم ## المصادر (بعد نزع التنبيهات) — "لكل مصدر: اسم القناة —
    عنوان الفيديو — الرابط — الطوابع الزمنية" (prompts/youtube_article.md،
    خارج النطاق). تُستعمَل حرفيًا كما وردت من النموذج، لا تفكيك حقول إضافي —
    البرومبت خارج النطاق فلا ضمان لبنية أدق من أسطر نصّية."""
    idx = article_body.find(SOURCES_HEADING)
    if idx == -1:
        return []
    tail = article_body[idx + len(SOURCES_HEADING):]
    return [line.strip().lstrip("-").strip()
            for line in tail.splitlines() if line.strip()]


# ── فهرس المقالات (state/youtube_articles/<date>/index.md، من
# youtube_article.build_index) — يُقرأ لا يُعاد بناؤه؛ الجدول جدول أكواد لا
# نثر نموذج، فتحليله بتعبير نمطي ثابت آمن (خلافًا لأي نصّ من إخراج النموذج).

_INDEX_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*\[(.*?)\]\((.*?)\)\s*\|\s*([abc])\s*\|\s*(.*?)\s*\|"
    r"\s*(.*?)\s*\|\s*(\S+)\s*\|\s*(.*?)\s*\|\s*$",
    re.MULTILINE,
)


def parse_index(text: str) -> list[dict]:
    rows = []
    for m in _INDEX_ROW_RE.finditer(text):
        number, headline, filename, layer, blocs_s, channels_s, agreement, marker = m.groups()
        warn_match = re.search(r"(\d+)", marker)
        rows.append({
            "number": int(number), "headline": headline, "filename": filename,
            "layer": layer, "agreement": agreement,
            "blocs": [b.strip() for b in blocs_s.split(",") if b.strip()],
            "channels": [c.strip() for c in channels_s.split(",") if c.strip()],
            "warnings_count": int(warn_match.group(1)) if warn_match else 0,
        })
    return rows


# ──────────────────────────── بطاقة العنوان ────────────────────────────


def build_title_card(headline: str, tier: str, blocs: list[str], channels: list[str],
                      cfg, out_path: Path) -> Path:
    """قالب جديد بعنصرين فقط (نصّ الـIssue #676): عنوان بخطّ كبير في الوسط،
    وشريط سفلي يحمل الكتل والقنوات — وعلامة بصرية ثابتة (badge) تميّز هذا
    المسار عن تقارير الصفحة العادية. تُستعمَل أدوات imaging.py الأساسية
    (load_font/draw_text/fit_text/placeholder/badge_left) بلا لمس
    build_post_image نفسها — «محرّكها» (القصّ والتعتيم والتشكيل العربي) غير
    مطروق هنا أصلًا لأن لا صورة خبر تدخل هذا القالب إطلاقًا."""
    W = int(cfg.path("image.width", 1080))
    H = int(cfg.path("image.height", 1080))
    primary = imaging.hex_rgb(cfg.path("brand.primary_color", "#12203A"))
    accent = imaging.hex_rgb(cfg.path("brand.accent_color", "#F0B429"))
    f_head = cfg.path("image.font_headline")
    head_weight = cfg.path("image.font_headline_weight") or None
    f_body = cfg.path("image.font_body") or f_head
    body_weight = cfg.path("image.font_body_weight") or None
    badge_text = cfg.path("youtube.image.badge_text", "تحليل")

    canvas = imaging.placeholder(W, H, primary, accent)
    draw = ImageDraw.Draw(canvas)
    margin = int(W * 0.08)
    rule = max(4, W // 240)

    # الشريط السفلي أولًا لمعرفة المساحة المتبقية للعنوان — نفس ترتيب
    # build_post_image (قياس شريط العنوان قبل الصورة).
    bar_text = bottom_bar_text(tier, blocs, channels, cfg)
    bar_font, bar_lines, bar_line_h = imaging.fit_text(
        draw, bar_text, f_body, max_width=W - margin * 2, max_lines=2,
        start=int(W * 0.032), minimum=int(W * 0.020), weight=body_weight,
    )
    bar_pad = int(H * 0.035)
    bar_h = len(bar_lines) * bar_line_h + bar_pad * 2

    head_font, head_lines, line_h = imaging.fit_text(
        draw, headline, f_head, max_width=W - margin * 2, max_lines=6,
        start=int(W * 0.090), minimum=int(W * 0.045), weight=head_weight,
    )

    # العنوان يتوسّط المساحة فوق الشريط رأسيًا
    avail_h = H - bar_h
    y = (avail_h - len(head_lines) * line_h) // 2 + line_h // 2
    for line in head_lines:
        imaging.draw_text(draw, (W // 2, y), line, head_font, (255, 255, 255), anchor="mm")
        y += line_h

    # الشريط السفلي
    bar_top = H - bar_h
    draw.rectangle([0, bar_top, W, H], fill=imaging.mix(primary, (0, 0, 0), 0.28))
    draw.rectangle([0, bar_top, W, bar_top + rule], fill=accent)
    by = bar_top + bar_pad + bar_line_h // 2
    for line in bar_lines:
        imaging.draw_text(draw, (W // 2, by), line, bar_font,
                          (225, 228, 235), anchor="mm")
        by += bar_line_h

    # العلامة البصرية الثابتة (نصّ الـIssue #676: تميّز هذا المسار عن تقرير
    # الصفحة العادي) — أعلى يسار البطاقة، ثابتة المكان في كل بطاقة.
    badge_font = imaging.load_font(f_body, int(W * 0.028), body_weight)
    imaging.badge_left(draw, margin, int(H * 0.07), badge_text, badge_font, accent, primary)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=90, optimize=True, subsampling=0)
    return out_path


# ──────────────────────────── المسودة ────────────────────────────


def build_draft(row: dict, date_str: str, articles_dir: Path, cfg) -> dict | None:
    """يبني مسودة **بلا بطاقة** (Issue #680) -- البطاقة تُبنى لاحقًا لحظة
    الاعتماد فقط عبر ensure_title_card أدناه، لا هنا. المسودة تحمل الثلاثة
    عناوين المقترحة (headlines، من split_headlines) واختيارًا افتراضيًا
    (headline_selected=0 -- الأول، سؤال) والدرجة المركّبة (score، عبر
    compute_score) لترتيب Issue المراجعة بها."""
    article_path = articles_dir / row["filename"]
    if not article_path.exists():
        log.warning("ملف مقال مفقود: %s", article_path)
        return None

    raw_text = article_path.read_text(encoding="utf-8")
    body_no_headlines, headlines = split_headlines(raw_text)
    caption, warnings = split_warnings(body_no_headlines)
    source_lines = extract_source_lines(caption)
    # مقال بلا قسم عناوين أصلًا (مسار قديم قبل Issue #680) -- عنوان index.md
    # الأصلي مكرَّرًا ثلاثًا، بنفس احتياط youtube_article.run() عند فشل النداء.
    if not headlines:
        headlines = [row["headline"]] * 3
    default_title = headlines[0]

    draft_id = hashlib.sha1(
        f"youtube:{date_str}:{row['filename']}".encode("utf-8")
    ).hexdigest()[:12]

    return {
        "id": draft_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "origin": "youtube",
        "title": default_title,
        "tier": row["layer"],
        "blocs": row["blocs"],
        "channels": row["channels"],
        "agreement": row["agreement"],
        "warnings": warnings,
        "source_urls": source_lines,
        "caption": caption,
        # تاريخ التشغيلة -- يحدّد مسار البطاقة عند بنائها لاحقًا في
        # ensure_title_card (drafts/<run_date>/<id>.jpg، نفس اصطلاح
        # store.draft_dir)، فلا حاجة لتخمينه من created_at وقت النشر.
        "run_date": date_str,
        "headlines": headlines,
        "headline_selected": 0,
        # حقول بصيغة الأنبوب القائم (arabic.post_title/urgent، source.link/
        # publishers) — يقرأها publish.publish_one/first_comment_for بلا أي
        # تعديل عليهما (نصّ الـIssue: استعمال publish القائم فقط). **بلا
        # حقل image** حتى الاعتماد -- ensure_title_card يضيفه.
        "arabic": {"post_title": default_title, "urgent": False, "category": "تحليل"},
        "source": {"link": "\n".join(source_lines), "publishers": row["channels"]},
        "score": compute_score(row["blocs"], row["channels"], row["agreement"], cfg),
    }


def _review_sort_key(d: dict) -> tuple:
    # الدرجة المركّبة تنازليًا أولًا (نصّ الـIssue #680 -- انظر compute_score
    # ولماذا الطبقة وحدها كانت تظلم مقالات قوية)؛ عند تساوٍ تامّ في الدرجة،
    # الطبقة فنوع الخلاف يبقيان كاسر تعادل ثابتًا كسابقًا (Issue #676) بدل
    # الاعتماد على ترتيب وصول القضايا من youtube_cluster وحده.
    return (-d.get("score", 0), _TIER_RANK.get(d["tier"], 9), _AGREEMENT_RANK.get(d["agreement"], 9))


def _apply_headline(caption: str, headline: str) -> str:
    """يستبدل سطر العنوان الرئيسي الأول (# ...) في caption بالعنوان
    المختار فعليًا -- كي يبقى نصّ المنشور المنشور متّسقًا مع عنوان البطاقة
    المُختار، لا العنوان الافتراضي وحده (Issue #680)."""
    lines = caption.splitlines()
    if lines and lines[0].lstrip().startswith("#"):
        lines[0] = f"# {headline}"
    tail = "\n".join(lines)
    return tail + ("\n" if caption.endswith("\n") else "")


def ensure_title_card(path: Path, draft: dict, cfg) -> bool:
    """يبني بطاقة العنوان عند الحاجة فقط -- بعد الاعتماد، للمختار فقط
    (Issue #680)، بنفس مبدأ publish.ensure_reel تمامًا: الريل يُبنى لحظة
    النشر لا لحظة الجمع، فلا تُهدر حوسبة على ما لن يُنشر. يعيد True عند
    توفّر بطاقة صالحة (مبنيّة الآن أو موجودة مسبقًا من محاولة نشر سابقة)،
    False عند فشل البناء -- publish.publish_one يتعامل مع صورة مفقودة
    أصلًا (حالة failed صريحة)، فلا حاجة لتكرار ذلك المنطق هنا."""
    existing = draft.get("image")
    if existing:
        existing_path = DRAFTS_DIR / Path(existing).relative_to("drafts")
        if existing_path.exists():
            return True

    headlines = draft.get("headlines") or [draft["arabic"]["post_title"]]
    idx = draft.get("headline_selected", 0)
    if not isinstance(idx, int) or not (0 <= idx < len(headlines)):
        idx = 0
    headline = headlines[idx]
    run_date = draft.get("run_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    image_name = f"{run_date}/{draft['id']}.jpg"

    try:
        build_title_card(headline, draft["tier"], draft["blocs"], draft["channels"],
                          cfg, DRAFTS_DIR / image_name)
    except Exception as exc:  # noqa: BLE001 — امتناع صريح مُسجَّل لا انهيار صامت
        log.warning("تعذّر بناء بطاقة العنوان لـ%r: %s", headline, exc)
        return False

    new_caption = _apply_headline(draft["caption"], headline)
    new_arabic = {**draft["arabic"], "post_title": headline}
    store.update_draft(path, image=f"drafts/{image_name}", headline_selected=idx,
                        caption=new_caption, arabic=new_arabic)
    draft["image"] = f"drafts/{image_name}"
    draft["headline_selected"] = idx
    draft["caption"] = new_caption
    draft["arabic"] = new_arabic
    return True


# ──────────────────────────── Issue المراجعة ────────────────────────────


HEADLINE_BOX_RE = re.compile(
    r"^\s*-\s*\[([ xX])\]\s*.*?<!--\s*hl:([0-9a-f]+):(\d+)\s*-->", re.MULTILINE)


def parse_headline_choice(body: str) -> dict[str, int]:
    """يقرأ اختيار المالك بين العناوين الثلاثة (Issue #680) من نص Issue
    المراجعة -- معرّف المسودة ← فهرس العنوان المعلَّم. مسودة لم تُعلَّم على
    أيّ عنوان فيها (لم تظهر في القاموس المُعاد) تبقى على الافتراضي (٠، سؤال)
    في ensure_title_card. أكثر من عنوان معلَّم لنفس المسودة (خطأ مراجعة أو
    تعليم يدوي غير دقيق) -- آخر مربع معلَّم في ترتيب ظهور النص يفوز، بلا
    رفض أو تحذير: نفس تسامح parse_approved مع أخطاء التنسيق البسيطة."""
    chosen: dict[str, int] = {}
    for mark, draft_id, idx in HEADLINE_BOX_RE.findall(body or ""):
        if mark.lower() == "x":
            chosen[draft_id] = int(idx)
    return chosen


def build_review_body(drafts: list[dict], repo: str, branch: str, cfg=None) -> str:
    tier_counts = {"a": 0, "b": 0, "c": 0}
    cross_source_count = 0
    warnings_total = 0
    for d in drafts:
        tier_counts[d["tier"]] = tier_counts.get(d["tier"], 0) + 1
        if d["agreement"] == "cross_source":
            cross_source_count += 1
        warnings_total += len(d.get("warnings") or [])

    health = (f"{len(drafts)} مقالات · أ={tier_counts['a']} ب={tier_counts['b']} "
              f"ج={tier_counts['c']} · خلاف قنوات={cross_source_count} · "
              f"تنبيهات={warnings_total}")

    max_per_run = cfg.path("youtube.publish.max_per_run", 3) if cfg else 3
    spacing = cfg.path("youtube.publish.spacing_minutes", 40) if cfg else 40

    parts = [
        "### 📰 مراجعة مقالات تحليلية من القنوات",
        "",
        f"**{health}**",
        "",
        "**كيف تعتمد؟** ✔️ ضع علامة على المقالات التي توافق عليها، ثم أضف "
        "الوسم `youtube-approved` (لا `approved`) إلى هذا الـ Issue — وسم "
        "مخصّص لهذا المسار كي لا يتداخل مع سيّر النشر العام الذي يستجيب لأي "
        f"وسم `approved` على أي Issue. سيُنشر البوت حتى {max_per_run} مقالات "
        f"مؤشَّرة لكل تشغيلة، بفاصل {spacing:g} دقيقة بين كل منشور والتالي؛ "
        "الباقي ينتظر تشغيلة يدوية لاحقة بنفس الوسم.",
        "",
        "إغلاق الـ Issue بلا وسم = تجاهل الكل.",
        "",
        "---",
        "",
    ]

    for idx, d in enumerate(drafts, start=1):
        meta_line = (
            f"  الطبقة {_TIER_LABELS.get(d['tier'], d['tier'])} · "
            f"{' · '.join(bloc_label(b, cfg) for b in d['blocs']) or '—'} · "
            f"{'، '.join(d['channels'])} · "
            f"{_AGREEMENT_LABELS.get(d['agreement'], d['agreement'])}"
        )
        # درجة الأهمية ومكوّناتها (نصّ الـIssue #680) -- لماذا رُتِّب هذا
        # المقال هكذا، لا الرقم وحده.
        score_line = "  " + score_breakdown_text(d["blocs"], d["channels"], d["agreement"], cfg)
        parts += [
            f"- [ ] **{idx}. {d['title']}**  <!-- draft:{d['id']} -->",
            "",
            meta_line,
            "",
            score_line,
            "",
        ]
        if d.get("warnings"):
            # هذا بالضبط ما يجعل المراجعة حقيقية (نصّ الـIssue #676) — عدد
            # التنبيهات ونصّها كاملًا، لا مجرّد إشارة صامتة.
            parts.append(f"  ⚠️ **{len(d['warnings'])} تنبيه/تنبيهات للمراجعة:**")
            parts.append("")
            parts += [f"  - {w}" for w in d["warnings"]]
            parts.append("")
        headlines = d.get("headlines") or []
        if headlines:
            # عناوين بديلة (Issue #680) -- الأول (سؤال) معلَّم افتراضيًا؛
            # المالك يبدّل العلامة إلى بديل آخر، أو يترك الافتراضي كما هو.
            # لا صورة هنا إطلاقًا (Issue المراجعة يُفتح بلا صور — انظر توثيق
            # الوحدة أعلاه)؛ البطاقة تُبنى لاحقًا للمختار فقط بعد الوسم.
            selected = d.get("headline_selected", 0)
            parts.append("  🏷️ **العناوين المقترحة** (علّم المختار، الأول افتراضي):")
            parts.append("")
            for h_idx, headline in enumerate(headlines):
                mark = "x" if h_idx == selected else " "
                parts.append(f"  - [{mark}] {h_idx + 1}. {headline}  <!-- hl:{d['id']}:{h_idx} -->")
            parts.append("")
        parts += [
            "  <details><summary>📝 نص المقال كاملًا</summary>",
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

    parts.append(
        "<sub>وسم `youtube-approved` = نشر المؤشَّر (بسقف وتباعد) · "
        "إغلاق الـ Issue = تجاهل الكل</sub>"
    )
    return "\n".join(parts)


# ──────────────────────────── التشغيل (بناء + مراجعة) ────────────────────


def build(cfg=None, date_str: str | None = None, now: datetime | None = None) -> dict:
    """المرحلة الأولى فقط: مسودة **بلا بطاقة** لكل مقال، محفوظة محليًا
    (Issue #680 -- البطاقة تأجّلت إلى ensure_title_card عند الاعتماد، انظر
    توثيق الوحدة أعلاه). **لا تفتح Issue مراجعة** — انظر open_review() أدناه
    ولماذا يجب أن تُفصلا."""
    cfg = cfg or load_config()
    now = now or datetime.now(timezone.utc)
    date_str = date_str or now.strftime("%Y-%m-%d")

    articles_dir = youtube_article.ARTICLES_DIR / date_str
    index_path = articles_dir / "index.md"
    empty = {"run_date": date_str, "drafts": [],
             "stats": {"articles_in": 0, "drafts_built": 0, "article_missing": 0}}
    if not index_path.exists():
        return empty

    rows = parse_index(index_path.read_text(encoding="utf-8"))
    if not rows:
        return empty

    drafts: list[dict] = []
    missing = 0
    for row in rows:
        # فشل build_draft الوحيد الممكن الآن غياب ملف المقال نفسه -- لا بناء
        # بطاقة هنا إطلاقًا (Issue #680)، فلا فشل بطاقة يُسقِط مسودة بعد الآن.
        draft = build_draft(row, date_str, articles_dir, cfg)
        if draft is None:
            missing += 1
            continue
        store.save_draft(draft)
        drafts.append(draft)

    stats = {"articles_in": len(rows), "drafts_built": len(drafts),
              "article_missing": missing}
    return {"run_date": date_str, "drafts": drafts, "stats": stats}


def pending_youtube_drafts() -> list[tuple[Path, dict]]:
    """مثل store.pending_drafts() لكن مقصورة على مسودات هذا المسار
    (origin == "youtube") التي لم تُربَط بـIssue مراجعة بعد — لا الفحص الخام
    الذي يستعمله src/open_review.py للمسار العام (انظر توثيق الوحدة أعلاه)."""
    return [(p, d) for p, d in store.pending_drafts()
            if d.get("origin") == "youtube" and not d.get("review_issue")]


def open_review(cfg=None, now: datetime | None = None) -> dict:
    """المرحلة الثانية: تُشغَّل بعد رفع المسودات إلى المستودع (خطوة git
    commit/push منفصلة في الـworkflow، بين build() وهذه). لم يعد هذا الفصل
    مضطرًا لتفادي 404 صور raw.githubusercontent.com (Issue #680 -- لا صور في
    الـ Issue أصلًا الآن، انظر توثيق الوحدة أعلاه)، لكنه يبقى الأصحّ: مسودات
    محفوظة على القرص فقط دون دفع فعلي لا قيمة لفتح Issue يشير إليها قبل أن
    تصمد التشغيلة."""
    cfg = cfg or load_config()
    now = now or datetime.now(timezone.utc)

    fresh = pending_youtube_drafts()
    if not fresh:
        return {"issue": None, "drafts": []}

    drafts = [d for _, d in fresh]
    drafts.sort(key=_review_sort_key)

    repo = env("GITHUB_REPOSITORY") or ""
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    body = build_review_body(drafts, repo, branch, cfg)
    issue = review.create_issue(
        title=f"📰 مراجعة مقالات تحليلية {now:%Y-%m-%d %H:%M} UTC — {len(drafts)} مقال",
        body=body, labels=["youtube-review"],
    )

    by_id = {d["id"]: path for path, d in fresh}
    for d in drafts:
        store.update_draft(by_id[d["id"]], review_issue=issue["number"])

    return {"issue": issue, "drafts": drafts}


# ──────────────────────────── النشر (بسقف وتباعد) ────────────────────────


def publish_approved(issue_number: int, cfg) -> int:
    """ينشر ما عُلِّم عليه في Issue مراجعة يوتيوب، بسقف youtube.publish.
    max_per_run لكل تشغيلة وتباعد youtube.publish.spacing_minutes بين كل
    منشور والتالي (نصّ الـIssue #676، النقطة ٤) — لا سقف ولا تباعد ثابتين
    كهذين في publish.cmd_burst القائمة (فاصلها عشوائي 30-60 دقيقة وبلا سقف
    عدد)، فهذا تنسيق جديد يستدعي publish.publish_one (بلا تعديل عليها) بدل
    استدعاء cmd_burst/cmd_now مباشرة."""
    body = review.fetch_issue_body(issue_number)
    ids = review.parse_approved(body)
    if not ids:
        review.comment(issue_number,
                       "⚠️ لم يُعلَّم على أي مقال. أضف ✔️ ثم أعد وسم `youtube-approved`.")
        review.remove_label(issue_number, "youtube-approved")
        return 0

    # اختيار العنوان (Issue #680) -- يُقرأ هنا مرّة واحدة قبل الحلقة، لا
    # لكل مسودة على حدة، فمصدره نفس نصّ الـIssue الذي جُلب لتوّه أعلاه.
    headline_choices = parse_headline_choice(body)

    max_per_run = int(cfg.path("youtube.publish.max_per_run", 3))
    spacing_minutes = float(cfg.path("youtube.publish.spacing_minutes", 40))
    batch = ids[:max_per_run]
    remaining = ids[max_per_run:]

    lines: list[str] = []
    published = 0
    for i, draft_id in enumerate(batch):
        found = store.load_draft(draft_id)
        if not found:
            lines.append(f"- ❌ `{draft_id}` — المسودة غير موجودة")
            continue
        path, draft = found
        if draft.get("status") == "published":
            lines.append(f"- ↩️ {draft['arabic']['post_title'][:50]} — منشور مسبقًا")
            continue
        # البطاقة تُبنى الآن -- بعد الوسم، للمختار فقط (Issue #680) -- بدل
        # كل مقال مكتوب. فشل البناء لا يُوقِف النشر هنا: publish_one يكتشف
        # غياب ملف الصورة بنفسه ويسجّل "failed" صراحةً (نفس مسار صورة مفقودة
        # في الأنبوب العام).
        if draft_id in headline_choices:
            draft["headline_selected"] = headline_choices[draft_id]
        ensure_title_card(path, draft, cfg)
        ok, line = publish.publish_one(path, draft, cfg)
        published += int(ok)
        lines.append(line)
        if i < len(batch) - 1:
            log.info("انتظار %.0f دقيقة قبل المنشور التالي…", spacing_minutes)
            time.sleep(spacing_minutes * 60)

    header = f"### 🚀 نُشر {published} من {len(batch)} (سقف {max_per_run} لكل تشغيلة)"
    if remaining:
        header += (f"\n<sub>{len(remaining)} مقالًا معتمدًا ينتظر تشغيلة لاحقة "
                   "بنفس الوسم.</sub>")
    text = header + "\n" + "\n".join(lines)
    review.comment(issue_number, text)
    if published and not remaining:
        review.close_issue(issue_number)
    return 0


# ──────────────────────────── CLI ────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="توصيل مسار يوتيوب: بطاقة + مسودة، أو فتح Issue مراجعة، أو نشر المؤشَّر")
    parser.add_argument("--date", help="تاريخ التشغيلة YYYY-MM-DD (افتراضيًا اليوم، مع البناء)")
    parser.add_argument("--open-review", action="store_true",
                        help="افتح Issue مراجعة لما بُني وبقي بانتظار الرفع (بلا صور -- "
                             "Issue #680)")
    parser.add_argument("--issue", type=int, help="رقم Issue مراجعة (مع --publish)")
    parser.add_argument("--publish", action="store_true",
                        help="نشر المؤشَّر في --issue بسقف وتباعد بدل بناء مسودات جديدة")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    cfg = load_config()

    if args.publish:
        if not args.issue:
            parser.error("--publish يحتاج --issue")
        return publish_approved(args.issue, cfg)

    if args.open_review:
        result = open_review(cfg)
        if result["issue"]:
            print(f"Issue المراجعة: #{result['issue']['number']} "
                  f"({len(result['drafts'])} مقال)")
        else:
            print("لا مسودات جديدة بانتظار مراجعة")
        return 0

    result = build(cfg, args.date)
    stats = result["stats"]
    print(f"مقالات مُدخَلة: {stats['articles_in']} · مسودات بُنيت (بلا بطاقة -- Issue #680): "
          f"{stats['drafts_built']} (ملف مقال مفقود: {stats['article_missing']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
