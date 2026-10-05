"""المرحلة الخامسة من مسار يوتيوب (Issue #676): توصيل المسار التحليلي
(youtube_collect → youtube_extract → youtube_cluster → youtube_article) بما
كان قائمًا في المشروع قبله — بطاقة صورة، مسودة في drafts/، Issue مراجعة،
ونشر عبر facebook/publish. استعمال فقط لـstore/review/publish، بلا تعديل
على منطقها. بطاقة الصورة (منذ Issue #732) قالب واحد مشترك مع المسار العام
— imaging.build_post_image نفسها، بمعامل badge اختياري — لا قالب مستقل
يفترق تصميمه عن بطاقة الأخبار.

**بطاقة العنوان لا تستقبل أبدًا نص المقال ولا أي رابط صورة أو بيانات
فيديو/قناة/شخص** (انظر ensure_title_card أدناه): الحقول الممرَّرة إلى
imaging.build_post_image عنوان + سطر مصدر مُصاغ برمجيًا (يسمّي القنوات نصًّا
منذ Issue #1106، لكن بلا أي بيانات فيديو/قناة أخرى -- شعار، لقطة، صورة --
انظر image_source_line) + شارة ثابتة + روابط صور تعبيرية (اختيارية، عبر
fallback_urls لا image_urls) فقط، فسطر التقدير ولقطة الفيديو وصورته
المصغّرة وشعار القناة وصورة أي شخص مذكور في المقال ممنوعة *بنيويًا* لا
اجتهادًا — لا سبيل لتسريبها إلى البطاقة عبر توقيع الدالة نفسه، ولا سبيل
لوصول صورة الفيديو/القناة أصلًا لأن مصدر الصورة الوحيد (imagesearch.py،
Wikimedia/Openverse) لا يستقبل أي بيانات فيديو أو قناة إطلاقًا (طلب
المراجعة على Issue #680، انظر `_photo_candidates`).

**تنبيهات المراجعة تُنزَع من caption قبل أي نشر** (split_warnings) — تبقى في
حقل warnings المنفصل وفي Issue المراجعة فقط، فلا تصل فيسبوك إطلاقًا.

**وسم الاعتماد موحَّد `approved` لكل المسارات (Issue #745؛ `youtube-approved`
أُلغي نهائيًا)**: التصميم الأصلي هنا كان وسمًا مخصّصًا (`youtube-approved`)
كي لا يشترك publish.yml القائم (يستجيب لأي Issue موسوم `approved` بصرف
النظر عن عنوانه، بسقف/تباعد ثابتين لا يعرفان
youtube.publish.max_per_run/spacing_minutes) مع هذا المسار. لكن عطلًا فعليًا
وقع (Issue #740): مراجع وسم Issue تحليلي بـ`approved` سهوًا بدل
`youtube-approved` — نصّان متفقٌ عليهما بشريًا، لا حاجزًا برمجيًا، ووسم خاطئ
واحد كفى لتفويت الحاجز كليًا. الحل الدائم لم يكن وسمًا ثانيًا بل توجيه
برمجي: `publish.main` (publish.py) يقرأ حقل `origin` **لكل مسودة معتمَدة على
حدة** عند وسم `approved` عبر `store.origin_of` ويوجّهها إلى
`publish_ids`/`report_batch` هنا إن كانت قيمته المعيارية `"analysis"`
(استيراد مؤجَّل داخل الدالة تفاديًا للدوران—انظر توثيق publish.py). بما أن
هذا التوجيه وحده -- لا اسم الوسم -- هو ما يمنع
النشر المزدوج، لم يعد لوسم مخصّص أي غرض دفاعي: Issue #745 وحّد الوسم إلى
`approved` وحده في كل نصوص المراجعة هنا (build_review_body،
publish_approved)، ووسم فتح المراجعة `youtube-review` يبقى كما هو (وسم عرض
لا اعتماد، لا صلة له بهذا التوحيد).

**build() ثم open_review() منفصلتان لا دالة واحدة** — نفس تسلسل src/collect.py
+ src/open_review.py بالضبط: الصور تُبنى وتُحفَظ محليًا (build)، ثم يجب أن
تُدفَع إلى المستودع (خطوة git commit/push في الـworkflow) **قبل** فتح Issue
المراجعة (open_review)، وإلا 404 روابط raw.githubusercontent.com فيه (قيد
موثَّق في CLAUDE.md وtests/test_pipeline.py لسير الجمع الأصلي، ينطبق هنا
حرفيًا لنفس السبب). دمجهما في نداء واحد كان يفتح الـ Issue قبل أن تصل الصور
إلى الفرع. open_review() تفلتر على store.origin_of(...) == "analysis" تحديدًا
(لا store.pending_drafts() الخام كما في src/open_review.py) حتى لا تلتقط مسودات
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
أي بطاقة إطلاقًا؛ open_review() يفتح الـIssue **بلا صور** (لا رابط raw ولا
blob في build_review_body). البطاقة الوحيدة تُبنى عند publish_approved() --
بعد الوسم، للمختار فقط -- عبر ensure_title_card()، بنفس مبدأ
publish.ensure_reel() اللاحق تمامًا (يبني الريل عند الطلب لا عند الجمع):
مورد الحوسبة يُصرف على ما اختاره المراجع فعليًا لا على كل مرشح. لم يحتج هذا
أي تعديل على ملفات .github/workflows/ -- الخطوة القائمة "بناء البطاقات
والمسودات" في youtube-articles.yml تستدعي `python -m src.youtube_publish`
بلا خيارات، وbuild() نفسها صارت لا تبني بطاقات؛ وخطوة "نشر المؤشَّر" القائمة
في youtube-publish.yml (`--publish`) هي بالضبط ما يستدعي publish_approved()
بعد الوسم، فبناء البطاقة يقع داخلها بنيويًا بلا نقل أي خطوة يدويًا. (البطاقة
كانت تبقى بلا صورة خبر بتصميم Issue #676 المتعمَّد؛ طلب مراجعة لاحق على
Issue #680 أضاف صورة تعبيرية اختيارية عبر imagesearch.py -- انظر
_photo_candidates/ensure_title_card أدناه ولماذا هذا لا يناقض تصميم #676
الأصلي: ذلك التصميم استبعد صور المصادر الأصلية للفيديو تحديدًا
[لقطة/مصغّرة/شعار قناة]، لا كل صورة مطلقًا.)

(٣) **عناوين متعدّدة** -- كل مقال يحمل الآن ثلاثة عناوين مقترحة (يكتبها
src/youtube_article.py: generate_headlines، نداء منفصل عن الكتابة، مذيَّلة
في نصّ المقال ويقرؤها split_headlines هنا) تُعرَض جميعًا في بطاقة المراجعة
بمربعات اختيار (`<!-- hl:id:index -->`)، الأول (سؤال) معلَّم افتراضيًا.
parse_headline_choice تقرأ اختيار المالك من نص الـIssue عند الاعتماد،
وensure_title_card تستعمل العنوان المختار فعليًا في بناء البطاقة والـcaption
معًا (لا البطاقة وحدها) عبر _apply_headline.

Issue #732 وحّد بطاقة هذا المسار مع بطاقة الأخبار بعد أن خرج أول منشور
تحليلي على فيسبوك بلا شعار الصفحة وبلا سطر مصدر وبلا صورة -- ليس عطلًا بل
أثر جانبي مباشر لوجود نسختي رسم منفصلتين (imaging.build_post_image
للأخبار، وbuild_title_card هنا وحدها). لم يعد لهذه الوحدة أي منطق رسم
خاص بها: ensure_title_card يستدعي imaging.build_post_image ذاتها --
نفس الشعار وسطر المصدر والتصميم اللذين تراهما بطاقة الأخبار حرفيًا --
بملصق "تحليل" (Issue #758: يُقرأ الآن من جدول config.yaml: cards عبر
origin="analysis" لا من معامل badge صريح كما كان قبله) هو الفارق البصري
الوحيد المقصود بين المسارين. الشريط السفلي القديم
(بلوكات/قنوات، bottom_bar_text سابقًا) حُذف بالكامل معه؛ أسماء القنوات
تظهر الآن في سطر «المصدر:» القياسي عبر image_source_line -- بصيغة
«تحليل لتغطية X وY» (Issue #1106 يرجع عن قرار سابق كان يخفي الأسماء
ويعرض العدد فقط، «قراءة في تغطية N قناة»: كلمة «تحليل لتغطية» تحلّ العلّة
نفسها التي بُني عليها ذلك القرار -- نسبة المقال زورًا إلى القنوات كمصدر
ناشر -- بديباجة صريحة تقول إن المقال قراءة في تغطيتها لا نقل عنها، فلا
داعي لإخفاء الأسماء بعد اليوم)، والصيغة نفسها قابلة للتعديل من
config.yaml: cards.analysis.source_template/youtube.image.source_line_template
لا مكتوبة في الشيفرة. ولأن بطاقة هذا المسار تُبنى فقط بعد الاعتماد (البند ٢ أعلاه)،
لا عند الجمع، لا يعرف المراجع وقت الموافقة هل ستخرج بصورة تعبيرية أم على
خلفية مصممة إلا لو بحثنا الآن مسبقًا: open_review() يشغّل _photo_candidates
لكل مقال (بحث فقط، لا تحميل بطاقة كاملة) ويضع النتيجة في حقل has_photo
على المسودة قبل فتح الـIssue، فتظهر ⚠️ صريحة في نصّه حين لا مرشَّح متاح --
نفس مبدأ report/has_photo في المسار العام (imaging.build_post_image)، لكن
منقولًا هنا إلى مرحلة أبكر لأن بناء البطاقة نفسه مؤجَّل بنيويًا."""
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

from . import cards, names_audit, publish, review, stages, store, youtube_article, youtube_cluster, youtube_extract
from .config import DRAFTS_DIR, env, load_config

log = logging.getLogger(__name__)

# نفس القسم الذي يُلحقه youtube_article._append_warnings بذيل المقال —
# مستورَد لا مكرَّر، فتغييره هناك (لو وقع يومًا) لا يكسر هذا الملف بصمت.
WARNINGS_HEADER = youtube_article.WARNINGS_HEADER

# تُقرأ من كتلة config.yaml (`bloc` القيمة الإنجليزية المخزَّنة في channels)
# — احتياطي فقط إن غاب youtube.image.bloc_labels من الإعداد.
_DEFAULT_BLOC_LABELS = {
    "arabic": "عربية", "turkish": "تركية", "persian": "فارسية", "israeli": "إسرائيلية",
}

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


def _arabic_channel_count_phrase(n: int, genitive: bool = False) -> str:
    """``genitive=True`` لموضع مجرور (مضاف إليه بعد اسم مضاف، كما في
    score_breakdown_text) — المثنى وحده يتغيّر شكله مكتوبًا بين الحالتين
    ("قناتان" مرفوعة مقابل "قناتين" مجرورة/منصوبة)، فبلا هذا التمييز يخرج
    "تغطية قناتان" بتصريف خاطئ (Issue #742). بقية الصيغ (المفرد والجمع) لا
    تتغيّر مكتوبةً بين الحالتين فلا حاجة لتمييزها. ``image_source_line`` لم
    تعد تستعمل هذه الدالة منذ Issue #1106 (السطر يسمّي القنوات الآن بدل
    عدّها) — الاستعمال القائم الوحيد الآن هو score_breakdown_text."""
    if n == 1:
        return "قناة واحدة"
    if n == 2:
        return "قناتين" if genitive else "قناتان"
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


_LATIN_START_RE = re.compile(r"^[A-Za-z]")


def _wa_prefix(name: str) -> str:
    """واو العطف تلتصق بالاسم التالي («والعربية») إلا إذا بدأ بحرف لاتيني
    (Issue #1108): عند حدّ عربي/لاتيني بلا فاصل يشوَّه رسم الواو في محرك
    التشكيل فيصير أقرب لحرف لاتيني منه لواو عربية -- فاصلها بمسافة واحدة
    («و ILTV») يزيل التشوّه فورًا. الحالة العربية البحتة لا تتأثر."""
    return "و " if _LATIN_START_RE.match(name) else "و"


def _join_arabic_names(names: list[str]) -> str:
    """يصل قائمة أسماء بصياغة عربية سليمة (Issue #1106): اسم واحد بلا أي
    وصل، اسمان بـ«و» وحدها («الجزيرة وILTV»)، وثلاثة فأكثر بفواصل بين كل
    اسمين ثم «و» قبل الأخير («الجزيرة، ILTV، والعربية»). لا فرز هنا إطلاقًا
    -- تحافظ على ترتيب المُدخَل كما وصلها (بنفس ترتيب حقل channels في
    المسودة، نصّ الـIssue). واو العطف تُفصل بمسافة عن اسم يبدأ بحرف لاتيني
    (Issue #1108) وتبقى ملتصقة بغير ذلك."""
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} {_wa_prefix(names[1])}{names[1]}"
    return "، ".join(names[:-1]) + f"، {_wa_prefix(names[-1])}{names[-1]}"


def image_source_line(channels: list[str], cfg=None) -> str:
    """سطر «المصدر:» على بطاقة التحليل الموحَّدة (imaging.build_post_image،
    Issue #732، معكوسًا جزئيًا بـIssue #1106) -- **يسمّي القنوات الآن**، بعد
    أن كان القرار السابق هنا يخفي أسماءها ويعرض عددها فقط («قراءة في تغطية
    N قناة»)، خشية أن يُنسَب المقال إليها زورًا كمصدر ناشر. صاحب المشروع
    رجع عن ذلك القرار: القالب الجديد («تحليل لتغطية {channels}») يحلّ نفس
    العلّة بديباجة صريحة -- يقول إن المقال قراءة *في* تغطية تلك القنوات لا
    نقل عنها، فذكر أسمائها لم يعد نسبة زائفة. {channels} تصير أسماء القنوات
    كما هي في draft["channels"] (channels[].name في config.yaml)، موصولة
    بـ_join_arabic_names (بلا فرز، بنفس ترتيب المُدخَل)، داخل قالب نصّي قابل
    للتعديل بلا كود (config.yaml: cards.analysis.source_template أولًا --
    Issue #758 -- ثم youtube.image.source_line_template القائم للتوافق، ثم
    الافتراضي هنا).

    **سقف الطول** (cards.analysis.source_max_chars، افتراضه 48 حرفًا): إن
    تجاوزه السطر الكامل بكل الأسماء، يُقتصَر الذكر على أول اسمين ثم «وقنوات
    أخرى» بدل القائمة الكاملة -- يمنع سطرًا طويلًا يُقصّ على البطاقة أو
    يتداخل مع سطر التاريخ. يُطبَّق فقط حين يوجد أكثر من اسمين (وإلا لا معنى
    لـ«قنوات أخرى» بلا أي قناة متبقّية)."""
    max_chars = (cfg.path("cards.analysis.source_max_chars", 48) if cfg else None) or 48
    template = (
        (cfg.path("cards.analysis.source_template") if cfg else None)
        or (cfg.path("youtube.image.source_line_template") if cfg else None)
        or "تحليل لتغطية {channels}"
    )
    names = list(channels)
    full_line = template.format(channels=_join_arabic_names(names))
    if len(names) > 2 and len(full_line) > max_chars:
        return template.format(
            channels=_join_arabic_names(names[:2] + ["قنوات أخرى"]))
    return full_line


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


def split_image_query(article_text: str) -> tuple[str, str | None]:
    """يفصل قسم 🖼️ كلمات بحث الصورة الإنجليزية (يُلحقه
    youtube_article._append_image_query في ذيل المقال، بعد قسم العناوين إن
    وُجد -- Issue #941) عن متن المقال. يُستدعى على النصّ الخام **قبل**
    split_headlines (لا بعده): القسمان يظهران بالترتيب متن ← تحذيرات ←
    عناوين ← كلمات بحث الصورة، فقصّ هذا القسم أولًا يترك النصّ الباقي مطابقًا
    تمامًا لما كان عليه قبل Issue #941 لبقية دوال split_*. مقال بلا القسم
    أصلًا (فشل نداء العناوين، أو مقال قديم من قبل هذا الـIssue) يعيد None
    بلا استثناء."""
    idx = article_text.find(youtube_article.IMAGE_QUERY_HEADER)
    if idx == -1:
        return article_text.strip() + "\n", None

    body = article_text[:idx].rstrip()
    if body.endswith("---"):
        body = body[:-3].rstrip()

    tail = article_text[idx + len(youtube_article.IMAGE_QUERY_HEADER):].strip()
    return body + "\n", (tail or None)


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


# ── فهرس المقالات (state/youtube_articles/<date>/index.md، من
# youtube_article.build_index) — يُقرأ لا يُعاد بناؤه؛ الجدول جدول أكواد لا
# نثر نموذج، فتحليله بتعبير نمطي ثابت آمن (خلافًا لأي نصّ من إخراج النموذج).

# عمود «الفيديوهات» (Issue #1092) بين القنوات والخلاف -- معرّفات الفيديو
# المصدرية مرتّبة أهميةً (youtube_article._video_ids_by_contribution). لم
# تعد مصدر صورة بطاقة (Issue #1095 ألغى خلفية الفيديو المعتّمة التي
# استعملتها)، لكنها تبقى معلومة مفيدة بذاتها على المسودة (source_videos
# أدناه) -- قد تُستعمل لاحقًا. عمود اختياري القيمة (قد يكون خاليًا لصف قديم
# لا يحمله) لا اختياري الوجود -- (.*?) تطابق سلسلة فارغة بلا كسر بنية الجدول.
_INDEX_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*\[(.*?)\]\((.*?)\)\s*\|\s*(.*?)\s*\|\s*([abc123])\s*\|\s*(.*?)\s*\|"
    r"\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(\S+)\s*\|\s*(.*?)\s*\|\s*$",
    re.MULTILINE,
)


def parse_index(text: str) -> list[dict]:
    rows = []
    for m in _INDEX_ROW_RE.finditer(text):
        (number, headline, filename, event, layer, blocs_s, channels_s, video_ids_s,
         agreement, marker) = m.groups()
        warn_match = re.search(r"(\d+)", marker)
        rows.append({
            "number": int(number), "headline": headline, "filename": filename,
            "event": event, "layer": youtube_cluster.layer_num(layer), "agreement": agreement,
            "blocs": [b.strip() for b in blocs_s.split(",") if b.strip()],
            "channels": [c.strip() for c in channels_s.split(",") if c.strip()],
            "video_ids": [v.strip() for v in video_ids_s.split(",") if v.strip()],
            "warnings_count": int(warn_match.group(1)) if warn_match else 0,
        })
    return rows


# ──────────────────────────── بطاقة العنوان ────────────────────────────


# نُقلت إلى src/youtube_extract.py (Issue #1092) -- src/youtube_article.py
# يحتاج المنطق نفسه (بوابة توفّر صورة قبل نداء الصياغة) ولا يستطيع استيراد
# هذا الملف (youtube_publish.py يستورد youtube_article.py فعليًا، فالعكس
# دورة استيراد)؛ youtube_extract.py قاعدة مشتركة آمنة تستوردها الوحدتان معًا
# بلا دورة. الاسمان المحليان هنا إعادة تصدير فقط (نفس مبدأ
# HEADLINE_BOX_RE/parse_headline_choice أعلاه) كي لا تنكسر استدعاءاتهما أو
# اختباراتهما القائمة (yp._photo_candidates/yp._photo_search_terms).
_photo_search_terms = youtube_extract.photo_search_terms
_photo_candidates = youtube_extract.photo_candidates


# ──────────────────────────── المسودة ────────────────────────────


def build_draft(row: dict, date_str: str, articles_dir: Path, cfg) -> dict | None:
    """يبني مسودة **بلا بطاقة** (Issue #680) -- البطاقة تُبنى لاحقًا لحظة
    الاعتماد فقط عبر ensure_title_card أدناه، لا هنا. المسودة تحمل الثلاثة
    عناوين المقترحة (headlines، من split_headlines) واختيارًا افتراضيًا
    (headline_selected=0 -- الأول، سؤال) والدرجة المركّبة (score، عبر
    compute_score) لترتيب Issue المراجعة بها. تحمل أيضًا image_query_en إن
    وُجد (Issue #941، split_image_query) -- كلمات البحث الإنجليزية التي
    ينتجها youtube_article.generate_headlines، مصدر الصورة التعبيرية
    الأساسي في _photo_candidates/ensure_title_card أدناه."""
    article_path = articles_dir / row["filename"]
    if not article_path.exists():
        log.warning("ملف مقال مفقود: %s", article_path)
        return None

    raw_text = article_path.read_text(encoding="utf-8")
    # split_image_query أولًا -- ترتيب القسمين الملحقَين في النصّ الخام هو
    # متن ← تحذيرات ← عناوين ← كلمات بحث الصورة (انظر youtube_article.run())،
    # فقصّ الأخير أولًا يترك raw_text مطابقًا لما كان عليه قبل Issue #941.
    raw_text, image_query_en = split_image_query(raw_text)
    body_no_headlines, headlines = split_headlines(raw_text)
    caption, warnings = split_warnings(body_no_headlines)
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
        # القيمة المعيارية (Issue #749) -- المسودات القديمة على القرص تحمل
        # "youtube" (قبل التوحيد)، وstore.origin_of تُرجعها "analysis" عند
        # القراءة بلا حاجة لتعديلها؛ الجديدة تُكتب معيارية مباشرة.
        "origin": "analysis",
        "title": default_title,
        "tier": youtube_cluster.layer_num(row["layer"]),
        "blocs": row["blocs"],
        "channels": row["channels"],
        "agreement": row["agreement"],
        # event القضية (جملة عربية قصيرة تصف الحدث بعينه) -- طلب المراجعة
        # على Issue #680: مصدر الكلمات المفتاحية لبحث صورة تعبيرية في
        # ensure_title_card أدناه، أدقّ من العنوان التحليلي الأعمّ وحده.
        "event": row.get("event", ""),
        # كلمات بحث الصورة الإنجليزية (Issue #941) -- None حين غاب القسم
        # (فشل نداء العناوين، أو مقال قديم): _photo_candidates/ensure_title_card
        # يعودان للبحث بالعربية وحده كما كان، بلا انهيار.
        "image_query_en": image_query_en,
        "warnings": warnings,
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
        # link فارغ صراحة لا مبني من متن المقال -- منذ Issue #941 لم يعد متن
        # المقال يحمل قسم "## المصادر" أصلًا (أي عنوان ## صار مرفوضًا في
        # youtube_article._validate_article_text)، فمحاولة استخراجه كانت
        # تعيد قائمة فارغة في كل تشغيلة على أي حال (Issue #946). فراغ link
        # يجعل publish.first_comment_for يعيد None بحارسه القائم -- سلوك
        # مقصود: منشور تحليل عن تغطية القنوات لا منقول عن مصدر واحد فلا
        # تعليق أول له. publishers يبقى (يقرأه decisions.py/insights.py).
        "source": {"link": "", "publishers": row["channels"]},
        "score": compute_score(row["blocs"], row["channels"], row["agreement"], cfg),
        # معرّفات الفيديوهات المصدرية مرتّبة أهميةً (الأكثر مساهمة بالنقاط
        # أولًا -- youtube_article._video_ids_by_contribution، عبر index.md).
        # لم تعد مصدر صورة بطاقة (Issue #1095 ألغى خلفية الفيديو المعتّمة
        # التي بُنيت لهذا الغرض في Issue #1092) -- تبقى على المسودة معلومة
        # مفيدة بذاتها، قد نحتاجها لاحقًا (قرار صريح من صاحب المشروع). قائمة
        # فارغة لمقال قديم بلا هذا العمود في index.md (row.get بدل row[..])
        # -- لا انهيار.
        "source_videos": row.get("video_ids", []),
    }


def build_draft_from_text(topic: dict, text: str, video_ids: list[str],
                          date_str: str, cfg) -> dict:
    """مثل build_draft أعلاه لكن من نصّ مقال جاهز في الذاكرة مباشرة -- بلا
    ملف .md ولا index.md وسيطين في مستودع البيانات الخاص (Issue #1104،
    بوابة الاختيار قبل الكتابة): الكتابة الفعلية صارت تقع عند اعتماد Issue
    الاختيار، من داخل publish.yml (طلب صريح على الـIssue) -- سير عمل لا
    يفتح تسجيل الدخول إلى gilandeya/trendnews-data إطلاقًا (خلافًا لـ
    youtube-articles.yml)، فلا مكان آمن يُكتب فيه ملف .md وسيط هناك أصلًا،
    ولا خطوة رفع/دفع لذلك المستودع فيه على أي حال. ``topic`` هنا يحمل
    بالفعل ``id`` (يُخصَّص في youtube_cluster.open_selection) بدل الاعتماد
    على رقم صفّ في index.md -- ``draft_id`` يُشتَقّ منه فيبقى ثابتًا حتى لو
    أُعيدت معالجة نفس القضية (سقف youtube.article.max_per_run يؤجّل باقي
    الدفعة لتشغيلة لاحقة، انظر youtube_cluster.finalize_selection). شكل
    المسودة الناتج مطابق لـbuild_draft حرفيًا -- فرق المصدر فقط (نصّ في
    الذاكرة بدل ملف على القرص)."""
    raw_text, image_query_en = split_image_query(text)
    body_no_headlines, headlines = split_headlines(raw_text)
    caption, warnings = split_warnings(body_no_headlines)
    if not headlines:
        headlines = [topic["title"]] * 3
    default_title = headlines[0]

    draft_id = hashlib.sha1(
        f"youtube-selection:{date_str}:{topic['id']}".encode("utf-8")
    ).hexdigest()[:12]

    draft = {
        "id": draft_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "origin": "analysis",
        "title": default_title,
        "tier": youtube_cluster.layer_num(topic["layer"]),
        "blocs": topic["blocs"],
        "channels": topic["channels"],
        "agreement": topic["agreement"],
        "event": topic.get("event", ""),
        "image_query_en": image_query_en,
        "warnings": warnings,
        "caption": caption,
        "run_date": date_str,
        "headlines": headlines,
        "headline_selected": 0,
        "arabic": {"post_title": default_title, "urgent": False, "category": "تحليل"},
        "source": {"link": "", "publishers": topic["channels"]},
        "score": compute_score(topic["blocs"], topic["channels"], topic["agreement"], cfg),
        "source_videos": video_ids,
        # رابطة الموضوع (Issue #1187): بها يعود المقال إلى الترشيح (go1) فيجد
        # موضوعه في ملف تاريخه، وبها يُعاد استعماله حين يُختار الموضوع ثانية
        # بلا كتابة جديدة. المسودات القديمة (build_draft/build_draft_from_text
        # قبل هذا الإصدار) بلا الحقلين فلا تعود ولا يظهر لها go1.
        "topic_id": topic["id"],
        "topic_date": date_str,
    }
    if topic.get("manual_image"):
        # رابط صورة وضعه المراجع في قضية الترشيح (Issue #1190): ينتقل إلى
        # المسودة فيغلب كل مراحل الصورة عند بناء البطاقة (ensure_title_card)
        draft["manual_image"] = topic["manual_image"]
    return draft


def _review_sort_key(d: dict) -> tuple:
    # الدرجة المركّبة تنازليًا أولًا (نصّ الـIssue #680 -- انظر compute_score
    # ولماذا الطبقة وحدها كانت تظلم مقالات قوية)؛ عند تساوٍ تامّ في الدرجة،
    # الطبقة فنوع الخلاف يبقيان كاسر تعادل ثابتًا كسابقًا (Issue #676) بدل
    # الاعتماد على ترتيب وصول القضايا من youtube_cluster وحده.
    return (-d.get("score", 0), -youtube_cluster.layer_num(d["tier"]), _AGREEMENT_RANK.get(d["agreement"], 9))


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

    # سلّم الصورة (Issue #1123، قُلب ترتيبه): صورة خبر عن الموضوع أولًا (Issue
    # #1095) ثم صورة حرة الترخيص (Issue #680) ثم امتناع الصياغة. صورة الخبر
    # أقرب للحدث دومًا والحرة عامة بطبيعتها. كلاهما دالة كسولة تُنفَّذ داخل
    # imaging.build_post_image (عبر cards.ensure) فقط حين تفشل الدرجة الأعلى --
    # بحث الأخبار وبحث ويكيميديا/Openverse كلاهما شبكة حقيقية، فإنفاق أيٍّ
    # منهما قبل معرفة الحاجة يهدر نداءً (كان بحث الحرة هنا مبكرًا وغير مشروط).
    # الحرة اختيارية ومعطَّلة بأمان (youtube.image.use_photo)، وحارس الوجه
    # (photo_candidates) يبقى عليها وحدها لا على صورة الخبر.
    # image_query_en (Issue #941) يصل هنا أولًا (محاولة عربية+إنجليزية معًا
    # عبر _photo_search_terms).
    image_query_en = draft.get("image_query_en")
    event = draft.get("event", "")
    news_photo_provider = (
        lambda: youtube_extract.news_photo_candidates(headline, event, cfg, image_query_en))
    free_photo_provider = None
    if cfg.path("youtube.image.use_photo", True):
        free_photo_provider = (
            lambda: _photo_candidates(headline, event, cfg, image_query_en))

    # غلاف رفيع فوق cards.ensure (Issue #852): القالب الموحَّد مع بطاقة
    # الأخبار (Issue #732) -- imaging.build_post_image ذاتها عبر cards.ensure،
    # لا نسخة رسم منفصلة هنا. image_urls=None بنيويًا (لا صور فيديو/قناة
    # أصلية إطلاقًا -- انظر توثيق الوحدة أعلاه)؛ المرشّحون التعبيريّون
    # (free_photo_provider أعلاه) يمرّون عبر fallback_provider الكسول. check_headline_limit=False
    # يستعمل العنوان المختار كما هو (لا فحص طول هنا، كالسابق).
    # cards.analysis_card_kwargs() (Issue #1044، سابقًا category="" وurgent=False
    # وbucket="" وorigin="analysis" منثورة هنا نصًّا) -- مصدر وحيد يشاركه
    # setimage.rebuild_card كي لا تنحرف القيمتان عن بعضهما مجددًا؛ bucket=""
    # صراحةً لأن مسودة التحليل لا تحمل حقل bucket إطلاقًا (لا "serious"
    # الافتراضي في cards.ensure).
    # out_dir=run_date لأن مجلد حفظ المسودة الفعلي (store.save_draft) قد
    # يختلف عن run_date في الاختبارات (انظر توثيق cards.ensure).
    #
    # المحاولة الثانية (Issue #941): allow_search_fallback الافتراضي (True)
    # لم يعد مُلغًى صراحة -- إن عاد free_photo_provider فارغًا، سلسلة cards.ensure
    # العامة تجرّب بحثًا مستقلًا بـsearch_term=image_query_en (أو تعود
    # للعنوان العربي إن غاب، فلا فرق سلوكي عمّا كان قبل هذه المهمة حين يغيب
    # الحقل). هذه المحاولة لا تطبّق حارس الوجه في _photo_candidates أعلاه --
    # نفس السلسلة العامة المستعملة في كل مسارات المشروع الأخرى، بلا فحص وجه
    # إضافي هنا (القاعدة القديمة تبقى كما هي في _photo_candidates وحدها).
    #
    # رابط يدوي (Issue #1187): صورة الصقها المراجع في حقل المرحلة 2 قبل بناء
    # البطاقة (setimage.apply_image تحفظها manual_image وتتجنّب البناء). هي
    # اختيار بشري صريح فتغلب كل درجات السلّم كما في الأخبار: تُمرَّر وحدها في
    # image_urls، ولا مزوّد خبر ولا حرّ يُستدعى (cards.ensure يمنع بحث الويب
    # والبديل العام معها). بدونها image_urls=None بنيويًا كما كان.
    manual = draft.get("manual_image")
    if manual:
        news_photo_provider = None
        free_photo_provider = None
    new_rel = cards.ensure(
        path, draft, cfg, headline=headline,
        image_urls=[manual] if manual else None, search_term=image_query_en,
        news_photo_provider=news_photo_provider,
        fallback_provider=free_photo_provider,
        publisher=image_source_line(draft["channels"], cfg),
        out_dir=run_date, check_headline_limit=False,
        **cards.analysis_card_kwargs(),
    )
    if new_rel is None:
        log.warning("تعذّر بناء بطاقة العنوان لـ%r", headline)
        return False

    # تشخيص لاحق (Issue #941/#1095/#1123): أي درجة أثمرت فعلًا -- صورة خبر عن
    # الموضوع، أو صورة حرة (من المزوّد أو من البحث العام الاحتياطي)، أو لا شيء.
    image_info = draft.get("image_info") or {}
    if image_info.get("kind") == "news_photo":
        log.info("📰 صورة خبر عن الموضوع: %r", headline)
    elif image_info.get("illustrative"):
        log.info("🖼️ صورة تعبيرية حرة: %r", headline)
    else:
        log.info("🖼️ بلا صورة — خلفية مصممة: %r", headline)

    new_caption = _apply_headline(draft["caption"], headline)
    new_arabic = {**draft["arabic"], "post_title": headline}
    store.update_draft(path, headline_selected=idx, caption=new_caption, arabic=new_arabic)
    draft["headline_selected"] = idx
    draft["caption"] = new_caption
    draft["arabic"] = new_arabic
    return True


# ──────────────────────────── Issue المراجعة ────────────────────────────


# نُقلت إلى review.py (Issue #756) -- مسار الأخبار يحتاج نفس آلية اختيار
# العنوان، فهذه الوحدة استوردتها لتبقى `youtube_publish.parse_headline_choice`
# قابلة للنداء كما هي من publish.py بلا تغيير في ذلك النداء.
HEADLINE_BOX_RE = review.HEADLINE_BOX_RE
parse_headline_choice = review.parse_headline_choice


def build_review_body(drafts: list[dict], repo: str, branch: str, cfg=None) -> str:
    """نص قضية المرحلة 2 للتحليل (Issue #1187، المهمة 3 من توحيد المراحل) —
    الشكل نفسه الذي ثبّته #1182 لقضية الأخبار (review.build_issue_body): رأس
    stages.stage_header وشرح stages.explainer، ولا مربع فوق بيانات أي مقال.
    ترتيب المقال: العنوان (علامة draft: وحدها) ← الشارات والقنوات والدرجة
    والتنبيهات ← الصورة إن وُجدت مع سطر مصدرها الداخلي ← نص المقال
    (<details>) ← اختيار العنوان (hl:) ← حقل رابط الصورة ← كتلة الانتقال.
    الانتقال كله بعلامات go: (stages.options_block)؛ go1 لمن يحمل topic_id
    وحده (review.has_stage1). الدوال المشتركة (caption_details/headline_boxes/
    image_source_line/raw_url) من review.py؛ يبقى هنا ما يخصّ التحليل وحده
    (الدرجة المركّبة، القنوات والكتل، تنبيهات المراجعة، معاينة توفّر الصورة)."""
    if cfg is None:
        cfg = load_config()
    tier_counts: dict[int, int] = {}
    cross_source_count = 0
    warnings_total = 0
    for d in drafts:
        n = youtube_cluster.layer_num(d["tier"])
        tier_counts[n] = tier_counts.get(n, 0) + 1
        if d["agreement"] == "cross_source":
            cross_source_count += 1
        warnings_total += len(d.get("warnings") or [])

    tiers_text = " ".join(f"{n}={c}" for n, c in sorted(tier_counts.items(), reverse=True)) or "—"
    health = (f"{len(drafts)} مقالات · الكتل المتقاطعة: {tiers_text} · خلاف قنوات={cross_source_count} · "
              f"تنبيهات={warnings_total}")

    max_per_run = cfg.path("youtube.publish.max_per_run", 3)
    spacing = cfg.path("youtube.publish.spacing_minutes", 40)

    parts = [
        stages.stage_header(2, cfg),
        "",
        cfg.path("stages.explainer", ""),
        "",
        f"**{health}**",
        "",
        # سقف النشر وتباعده خاصّان بالتحليل (publish_ids) فيبقيان هنا لا في
        # الشرح الموحَّد.
        f"سيُنشر البوت حتى {max_per_run} مقالات مؤشَّرة لكل تشغيلة، بفاصل "
        f"{spacing:g} دقيقة بين كل منشور والتالي؛ الباقي ينتظر تشغيلة يدوية "
        "لاحقة بنفس الوسم.",
        "",
        "✏️ لتعديل نصّ منشور: حرّر هذا الـIssue واكتب داخل كتلة النص مباشرة. "
        "النصّ الذي أراه لحظة الاعتماد هو ما يُنشر. ملاحظة: تعديل النص لا "
        "يغيّر البطاقة — البطاقة تحمل العنوان فقط.",
        "",
        "---",
        "",
    ]

    for idx, d in enumerate(drafts, start=1):
        meta_line = (
            f"  تقاطع {youtube_cluster.layer_num(d['tier'])} كتل · "
            f"{' · '.join(bloc_label(b, cfg) for b in d['blocs']) or '—'} · "
            f"{'، '.join(d['channels'])} · "
            f"{_AGREEMENT_LABELS.get(d['agreement'], d['agreement'])}"
        )
        # درجة الأهمية ومكوّناتها (Issue #680) -- لماذا رُتِّب هذا المقال هكذا،
        # لا الرقم وحده.
        score_line = "  " + score_breakdown_text(d["blocs"], d["channels"], d["agreement"], cfg)
        # العنوان بلا مربع؛ علامة draft: تبقى عليه وحدها كي يجد
        # review.all_draft_ids معرّفات القضية.
        parts += [
            f"**{idx}. {d['title']}**  <!-- draft:{d['id']} -->",
            "",
            meta_line,
            "",
            score_line,
            "",
        ]
        if d.get("warnings"):
            # هذا بالضبط ما يجعل المراجعة حقيقية (Issue #676) — عدد التنبيهات
            # ونصّها كاملًا، لا مجرّد إشارة صامتة.
            parts.append(f"  ⚠️ **{len(d['warnings'])} تنبيه/تنبيهات للمراجعة:**")
            parts.append("")
            parts += [f"  - {w}" for w in d["warnings"]]
            parts.append("")
        # أسماء صُحّحت آليًا بدليل بحث (Issue #1252)
        fixes = names_audit.corrections_lines(d)
        if fixes:
            parts += [*[f"  {line}" for line in fixes], ""]
        # سطر مصدر الصورة يظهر دومًا: قبل البناء يقول إن البطاقة لم تُبنَ (أو
        # إن رابطًا يدويًا محفوظًا سيُستعمل)، وبعده مصدر الصورة الفعلي.
        parts += [f"  {review.image_source_line(d)}", ""]
        img_path = d.get("image")
        if img_path:
            parts += [
                f"  <img src=\"{review.raw_url(repo, branch, img_path)}\" width=\"520\" />",
                "",
                f"  ↳ [الصورة في المستودع]({review.blob_url(repo, branch, img_path)})",
                "",
            ]
        if d.get("has_photo") is False:
            # نفس مبدأ تحذير "بلا صورة" في review.build_issue_body للمسار
            # العام (Issue #732) -- لكن منقولًا هنا إلى ما قبل الاعتماد، لأن
            # بطاقة هذا المسار لا تُبنى فعليًا إلا بعده (Issue #680)؛ open_review
            # يبحث الآن مسبقًا (_photo_candidates) ليعرف المراجع الحال قبل أن
            # يوسم لا بعده حين يفوت أوان إضافة صورة. الرسالة تتفرّع (Issue
            # #1095): مقال بلغ هذه المرحلة أصلًا لضمان توفّر إحدى الدرجتين
            # (البوابة في youtube_article.run() تمتنع عن الصياغة دون ذلك) --
            # فمعاينة has_news_photo=True هنا تعني صورة خبر عن الموضوع
            # ستُستعمَل، لا خلفية مصممة عادية.
            if d.get("has_news_photo"):
                parts.append("  🖼️ **بلا صورة تعبيرية حرة** — ستُستعمَل صورة "
                             "خبر عن الموضوع نفسه بدلًا منها.")
            else:
                parts.append("  🖼️ **بلا صورة تعبيرية متاحة حاليًا** — ستُبنى البطاقة "
                             "على خلفية مصممة.")
            parts.append("")
        parts += review.caption_details(d, "📝 نص المقال كاملًا")
        # عناوين بديلة (Issue #680) -- الأول (سؤال) معلَّم افتراضيًا؛ المالك
        # يبدّل العلامة إلى بديل آخر. لا صورة هنا إطلاقًا قبل الاعتماد؛
        # البطاقة تُبنى لاحقًا للمختار فقط.
        parts += review.headline_boxes(
            d, "🏷️ **العناوين المقترحة** (علّم المختار، الأول افتراضي):")
        parts += [
            stages.image_field(d["id"], cfg),
            "",
            *stages.options_block(2, d["id"], cfg, has_stage1=review.has_stage1(d)),
            "",
            "---",
            "",
        ]

    parts.append(
        "<sub>وسم `approved` = تنفيذ المعلَّم (بسقف وتباعد للنشر) · "
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
    (store.origin_of(...) == "analysis") التي لم تُربَط بـIssue مراجعة بعد —
    لا الفحص الخام الذي يستعمله src/open_review.py للمسار العام (انظر توثيق
    الوحدة أعلاه)."""
    return [(p, d) for p, d in store.pending_drafts()
            if store.origin_of(d) == "analysis" and not d.get("review_issue")]


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
    by_id_path = {d["id"]: path for path, d in fresh}

    # معاينة توفّر صورة تعبيرية *قبل* فتح الـIssue (طلب المراجعة على Issue
    # #732: "أخبر المراجع حين تخرج البطاقة بلا صورة") -- بحث فقط عبر
    # _photo_candidates، لا بناء بطاقة كاملة، فيبقى مبدأ Issue #680 (حوسبة
    # البطاقة نفسها تُصرف على المختار فقط بعد الاعتماد) بلا مساس. النتيجة
    # معاينة لا وعد: ensure_title_card يعيد البحث فعليًا عند الاعتماد وقد
    # يختلف قليلًا إن اختار المراجع عنوانًا بديلًا (photo_search_terms يستعمل
    # العنوان الافتراضي هنا).
    if cfg.path("youtube.image.use_photo", True):
        for d in drafts:
            has_photo = bool(_photo_candidates(d["title"], d.get("event", ""), cfg,
                                               d.get("image_query_en")))
            d["has_photo"] = has_photo
            # معاينة الدرجة الثانية (Issue #1095) -- لا فائدة من فحصها إن
            # كانت الأولى متاحة فعلًا (لن تُستعمَل حينها إطلاقًا)؛ نفس مبدأ
            # "معاينة لا وعد" أعلاه، وبلا فحص وجه (انظر توثيق
            # youtube_extract.news_photo_available).
            has_news_photo = (not has_photo and bool(
                youtube_extract.news_photo_available(d["title"], d.get("event", ""), cfg,
                                                      d.get("image_query_en"))))
            d["has_news_photo"] = has_news_photo
            store.update_draft(by_id_path[d["id"]], has_photo=has_photo,
                               has_news_photo=has_news_photo)
    else:
        for d in drafts:
            d["has_photo"] = False
            d["has_news_photo"] = bool(
                youtube_extract.news_photo_available(d["title"], d.get("event", ""), cfg,
                                                      d.get("image_query_en")))

    drafts.sort(key=_review_sort_key)

    repo = env("GITHUB_REPOSITORY") or ""
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    body = build_review_body(drafts, repo, branch, cfg)
    issue = review.create_issue(
        title=f"📰 مراجعة مقالات تحليلية {now:%Y-%m-%d %H:%M} UTC — {len(drafts)} مقال",
        body=body, labels=["youtube-review"],
    )

    for d in drafts:
        store.update_draft(by_id_path[d["id"]], review_issue=issue["number"])

    return {"issue": issue, "drafts": drafts}


# ──────────────────────────── النشر (بسقف وتباعد) ────────────────────────


def publish_ids(ids: list[str], headline_choices: dict[str, int], cfg,
                body: str = "", issue_number: int | None = None,
                go3_ids: set[str] | None = None,
                ) -> tuple[list[str], int, int, list[str]]:
    """ينشر دفعة معرّفات مسودات يوتيوب معتمَدة، بسقف youtube.publish.max_per_run
    لكل تشغيلة وتباعد youtube.publish.spacing_minutes بين كل منشور **ناجح
    فعليًا** والتالي (نصّ الإصدار #676 النقطة ٤ + إصلاح Issue #740) — لا سقف
    ولا تباعد ثابتين كهذين في publish.cmd_burst القائمة، فهذا تنسيق جديد
    يستدعي publish.publish_one (بلا تعديل عليها) بدل استدعاء cmd_burst/cmd_now
    مباشرة. مستخرجة من publish_approved كي يستعملها أيضًا publish.main عبر
    التوجيه بالأصل (Issue #740) — منطق واحد مشترك لا نسخة ثالثة مكرَّرة.

    **الفاصل بعد نشر ناجح فقط:** مسودة غير موجودة، منشورة مسبقًا، أو فشل
    نشرها الفعلي (مثلًا صورة/حقل مفقود يسجّله publish_one كـfailed) تمرّ
    فورًا إلى التالية بلا انتظار — عطل حقيقي وقع (Issue #740): مسودات فشلت
    فورًا كانت تُهدر فاصل التشغيلة الثابت كاملًا كأنها نشرت بنجاح.

    **خيار go3 (Issue #1187، كان مربع 🎴 في #1000):** المعرّفات المطلوب عرض
    بطاقتها قبل النشر تأتي ``go3_ids`` من المستدعي (publish.main قرأها
    بـstages.read_actions)؛ إن لم تُمرَّر قُرئت من ``body`` بالقارئ الموحَّد
    نفسه (علامات go: أو الترجمة القديمة لقضية مفتوحة قبل التحديث).

    **مربع 🎴 (Issue #1000):** ``body``/``issue_number`` اختياريان (افتراضيًا
    فارغ/None) لأن ``publish.cmd_revival`` يستدعي هذه الدالة بجسم Issue
    إحياء الفشل لا جسم مراجعة تحليل حقيقي (لا مربعات 🎴 فيه إطلاقًا — انظر
    ``review.build_revival_body``)، فلا فرق سلوكي حين يغيبان. معرّف عُلِّم
    عليه 🎴 في ``body`` (نفس ``review.CARD_MARKER``) يُستبعد من دفعة
    النشر/سقف ``max_per_run`` كليًا -- لا يستهلك محاولة نشر فعلية في هذه
    التشغيلة -- تُبنى بطاقته عبر ``ensure_title_card`` كالمعتاد ثم يُجمَّع مع
    بقية معرّفات 🎴 في Issue مراجعة نهائية واحد بوسم ``final-review`` عبر
    ``publish.open_final_review`` (نفس ``review.build_final_review_body``
    المستعمل في مسار الأخبار -- لا باني نصّ ثالث). معرّف بلا مسودة أو منشور
    مسبقًا يُسجَّل سطرًا ويُتخطّى، بنفس حارس النشر المزدوج أدناه."""
    max_per_run = int(cfg.path("youtube.publish.max_per_run", 3))
    spacing_minutes = float(cfg.path("youtube.publish.spacing_minutes", 40))

    lines: list[str] = []
    if go3_ids is None:
        go3_ids = {i for i, a in stages.read_actions(body, 2)[0].items() if a == "go3"}
    card_requests = go3_ids & set(ids)
    if card_requests:
        built_ids: list[str] = []
        for draft_id in ids:
            if draft_id not in card_requests:
                continue
            found = store.load_draft(draft_id)
            if not found:
                lines.append(f"- ❌ `{draft_id}` — المسودة غير موجودة")
                continue
            path, draft = found
            if draft.get("status") == "published":
                lines.append(f"- ↩️ {draft['arabic']['post_title'][:50]} — منشور مسبقًا")
                continue
            if draft_id in headline_choices:
                draft["headline_selected"] = headline_choices[draft_id]
            ensure_title_card(path, draft, cfg)
            built_ids.append(draft_id)
        if built_ids:
            if issue_number is not None:
                publish.open_final_review(issue_number, built_ids, cfg)
                lines.append(f"- 🎴 {len(built_ids)} مقال بانتظار مراجعة نهائية للبطاقة قبل النشر")
            else:
                lines.append(f"- ⚠️ {len(built_ids)} مقال طلب 🎴 لكن لا رقم Issue متاح "
                             "لفتح المراجعة النهائية")
        ids = [i for i in ids if i not in card_requests]

    batch = ids[:max_per_run]
    remaining = ids[max_per_run:]

    published = 0
    wait_before_next = False
    for draft_id in batch:
        if wait_before_next:
            log.info("انتظار %.0f دقيقة قبل المنشور التالي…", spacing_minutes)
            time.sleep(spacing_minutes * 60)
            wait_before_next = False

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
        lines.append(line)
        if ok:
            published += 1
            wait_before_next = True

    return lines, published, len(batch), remaining


def report_batch(issue_number: int, lines: list[str], published: int, attempted: int,
                 remaining: list[str], cfg) -> None:
    """يعلّق تقرير الدفعة على Issue المراجعة ويغلقه عند اكتمال المعتمَد كله
    -- مستخرجة من publish_approved لتُستعمل أيضًا من publish.main (Issue
    #740)."""
    max_per_run = int(cfg.path("youtube.publish.max_per_run", 3))
    header = f"### 🚀 نُشر {published} من {attempted} (سقف {max_per_run} لكل تشغيلة)"
    if remaining:
        header += (f"\n<sub>{len(remaining)} مقالًا معتمدًا ينتظر تشغيلة لاحقة "
                   "بنفس الوسم.</sub>")
    text = header + "\n" + "\n".join(lines)
    review.comment(issue_number, text)
    if published and not remaining:
        review.close_issue(issue_number)


def publish_approved(issue_number: int, cfg) -> int:
    """ينشر ما عُلِّم عليه في Issue مراجعة يوتيوب (وسم approved، موحَّد مع
    المسار العام منذ Issue #745).
    التنسيق الفعلي (سقف/تباعد/بناء البطاقة) في publish_ids أعلاه.

    القراءة بـstages.read_actions(body, 2) (Issue #1187): publish = الاعتماد
    وحده، go3 = الاعتماد + البطاقة، go1 = العودة إلى الترشيح (من المسار العادي
    نفسه، publish.return_to_selection)؛ وقضية قديمة بمربعات draft:/card: تُقرأ
    بالترجمة القديمة نفسها."""
    body = review.fetch_issue_body(issue_number)
    actions, conflicts = stages.read_actions(body, 2)
    all_ids = review.all_draft_ids(body)
    ids = [i for i in all_ids if actions.get(i) in ("publish", "go3")]
    go3_ids = {i for i in ids if actions[i] == "go3"}
    go1_ids = [i for i in all_ids if actions.get(i) == "go1"]
    publish.report_conflicts(issue_number, conflicts, 2, cfg)
    if go1_ids:
        returned = publish.return_to_selection(go1_ids, 2)
        if returned:
            review.comment(issue_number, "### ↩️ عودة إلى الترشيح\n" + "\n".join(returned))
    if not ids:
        if go1_ids:
            review.close_issue(issue_number)
            return 0
        review.comment(issue_number,
                       "⚠️ لم يُعلَّم على أي مقال. علّم خيار انتقال تحت المقال ثم أعد وسم `approved`.")
        review.remove_label(issue_number, "approved")
        return 0

    # اختيار العنوان (Issue #680) -- يُقرأ هنا مرّة واحدة قبل الحلقة، لا
    # لكل مسودة على حدة، فمصدره نفس نصّ الـIssue الذي جُلب لتوّه أعلاه.
    headline_choices = parse_headline_choice(body)

    lines, published, attempted, remaining = publish_ids(
        ids, headline_choices, cfg, body=body, issue_number=issue_number,
        go3_ids=go3_ids)
    report_batch(issue_number, lines, published, attempted, remaining, cfg)
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
