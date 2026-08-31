"""المرحلة الثالثة من مسار يوتيوب (Issue #646): عنقدة نقاط
src/youtube_extract.py في قضايا، ثم ترتيبها بثلاث طبقات حسب انتشارها عبر
الكتل اللغوية والقنوات.

نداء **واحد** فقط لنموذج متوسط القوة يستقبل كل نقاط اليوم بحقولها المختصرة
(statement, speaker, channel, bloc, topic_hint, type -- نحو ١٥ ألف رمز
للتشغيلة المرجعية) ويطلب تجميعها في قضايا عبر إخراج مهيكل (tool_use) --
لا حكم برمجي على تشابه النصوص نفسها، فتمييز «تناول مستقل بقراءة خاصة» من
«إعادة تدوير نفس الخبر» (الصدى) يحتاج فهمًا دلاليًا لا مطابقة حرفية.

الطبقة (a/b/c) **تُحسَب برمجيًا** من قائمتي الكتل/القنوات الفعليتين لنقاط
كل قضية بعد العنقدة -- لا يُطلَب من النموذج تصنيفها، فهي دالة ميكانيكية
محضة لعدد الكتل/القنوات المشترِكة، ولا فائدة من تكليف النموذج بحساب يمكن
للشيفرة حسابه بدقة تامة.

Issue #658 (بعد أول تشغيلة كاملة أنتجت صفر قضايا طبقة (أ) وصفر خلاف): نافذة
يوم واحد كانت تمنع التقاطع بنيويًا -- قناتان عن نفس الحدث نادرًا ما تنشران
في نفس اليوم بالضبط. أُضيفت نافذة lookback_days (load_points_window)، سجل
قضايا مستهلكة (load_seen_points/mark_points_seen/filter_seen_topics) يمنع
إعادة تدوير نفس القضية أيامًا متتالية، حدّ أدنى لعدد نقاط القضية
(apply_min_points) لمنع مقالات هزيلة من نقطتين، وحقل `event` إلزامي لكل
قضية يمنع خلط حدثين متجاورين يشتركان في اسم أو قطاع بلا كونهما نفس الحدث.

Issue #660 (بعد تشغيلة وسّعت النافذة فعليًا -- ١٧٣ نقطة مدخلة، ٣ أيام
وصلت -- لكن نداء العنقدة نفسه فشل بمخرج فارغ): (١) نفس نمط عطل الاستخلاص
(Issue #637) -- النموذج يبدأ بناء بلوك tool_use ويُقطع قبل إكماله بسبب
max_tokens، ولم تكن هذه المرحلة تفحص stop_reason ولا تعيد المحاولة أصلًا
(أُضيفت بعد معالجة الاستخلاص بمهمة منفصلة). عولج بنفس آلية
youtube_extract.extract_points بالضبط: رفع max_tokens (config)، محاولة
إعادة واحدة، وفحص/تسجيل stop_reason صراحة عند القطع. (٢) النافذة تتراكم مع
تكرار التشغيل (٧٠ ← ١٧٣) وستتجاوز ٢٥٠ خلال أسبوع -- رفع max_tokens وحده لن
يكفي إلى الأبد، فأُضيف سقف max_points_per_call (apply_points_cap) يأخذ
الأحدث حسب run_date ثم ترتيب الظهور ويُسقِط الأقدم عند التجاوز. (٣) خطوة
الرفع في الـworkflow تُسقِط `git add` كاملة حين لا يُكتب
state/youtube_topics_seen.json إطلاقًا (صفر مقالات ⇐ صفر نقاط استُهلكت ⇐
mark_points_seen لم تُستدعَ قط) -- youtube_article.run() الآن يوكِّد وجود
الملف دومًا قبل نهاية التشغيلة، ولو فارغًا.

Issue #662 (تنقية المخرج بعد أول تشغيلة كاملة ناجحة، ٩ مقالات): (١) العنقدة
كانت أدقّ من اللازم أحيانًا -- نفس الحدث ينتج قضيتين منفصلتين لاختلاف
مصدريهما، فيُنشَران معًا محرجًا. أُضيف نداء دمج قصير رخيص منفصل
(merge_duplicate_events) بين العنقدة وحساب الطبقة، يقارن جمل `event` فقط
ويدمج القضايا المتناولة لنفس الحدث بعينه؛ الطبقة تُعاد حسابها برمجيًا بعد
الدمج تلقائيًا (build_topics تُستدعى على القضايا المدموجة). (٢) نافذة
lookback_days كانت تسحب نقاطًا من ملفات أُنتجت قبل إصلاحات جوهرية في
الاستخلاص (المرساة، حارس الموضوع) بلا تمييز عصرها -- أُضيف
youtube.cluster.min_points_date (apply_min_points_date) يُسقِط ملفات أقدم
منه، وحارس ثانٍ (apply_timestamp_guard) يُسقِط أي نقطة طابعها الزمني يتجاوز
مدة فيديوها عند التحميل، بصرف النظر عن مصدرها. الخطوتان مع apply_points_cap
مجمَّعتان الآن في prepare_window_points لضمان اتساق الترتيب بين هذه المرحلة
وsrc/youtube_article.py بنيويًا لا توثيقيًا فقط. (٤) مؤشّر `dispute` كان
يخلط خلافًا حقيقيًا بين قنوات مختلفة بخلاف داخلي بين ضيوف حلقة واحدة --
_agreement_type_for تنقّحه برمجيًا بعد العنقدة إلى cross_source (قنوات
مختلفة) أو internal (قناة واحدة)، من channels القضية الفعلية لا حكم نموذج
إضافي."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anthropic import Anthropic, APIError

from .config import STATE_DIR, Config, env, load_config

log = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "youtube_cluster.md"
POINTS_DIR = STATE_DIR / "youtube_points"
TOPICS_DIR = STATE_DIR / "youtube_topics"
# سجل النقاط التي دخلت مقالًا مكتوبًا سابقًا (Issue #658 العطل ١ بند ج) --
# يمنع إعادة عنقدة/كتابة نفس القضية أيامًا متتالية لمجرّد بقاء نقاطها داخل
# نافذة lookback_days. يُقرأ هنا (مرحلة العنقدة) ويُكتب من src/youtube_article.py
# بعد نجاح الكتابة فعليًا -- لا فائدة من تسجيل قضية عُنقدت لكن فشلت كتابتها
# أو لم تُختَر ضمن أعلى count.
SEEN_PATH = STATE_DIR / "youtube_topics_seen.json"

# قيم حكم النموذج الخام في نداء العنقدة (cluster_points) -- يبقى حكمًا
# دلاليًا صرفًا هنا (هل يوجد خلاف أصلًا؟)، والتنقيح البرمجي أدناه
# (_agreement_type_for) يقع لاحقًا في build_topics.
AGREEMENT_VALUES = ("agreement", "dispute", "echo")
# القيم النهائية في مخرج topics بعد تنقيح `dispute` إلى cross_source/internal
# برمجيًا (Issue #662 العطل ٤) -- انظر _agreement_type_for. `agreement`
# وecho يمرّان كما وردا من النموذج بلا تنقيح.
AGREEMENT_TYPES = ("cross_source", "internal", "agreement", "echo")
# ترتيب مؤشّر الخلاف داخل الطبقة الواحدة: خلاف حقيقي بين قنوات مختلفة
# (cross_source) يتصدّر، يليه خلاف داخلي بين متحدثين في مصدر واحد
# (internal) -- كلاهما أعلى من الاتفاق التام، والصدى (نفس الخبر معاد
# صياغته) ينزل إلى أدنى الترتيب دومًا -- «قيمة هذا المسار في الاختلاف» (نص
# الـIssue الأصلي)، مع تمييز خلاف القنوات عن خلاف الضيوف (Issue #662 العطل ٤).
_AGREEMENT_RANK = {"cross_source": 0, "internal": 1, "agreement": 2, "echo": 3}
# ترتيب القيم الخام (قبل تنقيح dispute) -- يُستعمَل فقط في _merge_issue_group
# لاختيار أعلى مؤشّر خلاف بين قضايا مدموجة، قبل أن يصل الناتج إلى build_topics.
_RAW_AGREEMENT_RANK = {"dispute": 0, "agreement": 1, "echo": 2}
_LAYER_RANK = {"a": 0, "b": 1, "c": 2}

CLUSTER_SCHEMA = {
    "name": "cluster_points",
    "description": "يجمع نقاطًا إخبارية مختصرة في قضايا، ويميّز الصدى (نقل نفس الخبر) عن التقاطع الفعلي",
    "input_schema": {
        "type": "object",
        "properties": {
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string",
                                  "description": "عنوان داخلي عربي قصير للقضية (لا يُنشَر)"},
                        "event": {
                            "type": "string",
                            "description": ("وصف الحدث الواحد بعينه الذي تدور حوله القضية، في "
                                             "جملة عربية قصيرة -- لا موضوع عام (Issue #658 العطل "
                                             "٤: اشتراك نقطتين في اسم شخص أو دولة أو قطاع وحده لا "
                                             "يكفي لضمّهما، فهذا الحقل يجبر تحديد الحدث تحديدًا)"),
                        },
                        "agreement": {"type": "string", "enum": list(AGREEMENT_VALUES)},
                        "point_ids": {"type": "array", "items": {"type": "integer"},
                                      "description": "معرّفات النقاط (id) الداخلة في هذه القضية"},
                    },
                    "required": ["title", "event", "agreement", "point_ids"],
                },
            },
        },
        "required": ["issues"],
    },
}


# ── دمج القضايا المتناولة لنفس الحدث بعينه (Issue #662 العطل ١) ──
#
# العنقدة أعلاه دقيقة أكثر من اللازم أحيانًا: قضيتان تتناولان نفس الحدث
# تُشطَران لأن مصادرهما مختلفة (شاهد الـIssue: "صفقة النفط بين واشنطن
# وكاراكاس" من الجزيرة/العربية/Habertürk مقابل "ما أُعلن فعلًا في اتفاق
# النفط" من CNN Türk وحدها -- نفس الحدث بعينه). نداء قصير رخيص منفصل، بعد
# العنقدة وقبل حساب الطبقة النهائية، يقارن جمل `event` القصيرة فقط (لا نصّ
# القضية كاملًا) ويعيد أزواج القضايا التي تتناول الحدث نفسه تحديدًا -- نفس
# معيار حقل `event` الصارم في CLUSTER_SCHEMA أعلاه (حدث واحد بعينه لا موضوع
# عام مشترك)، لا مجرّد تشابه لفظي بين جملتي event.

MERGE_SYSTEM = """أنت محرِّر تراجع قائمة قضايا إخبارية مُعنقدة مسبقًا، كل
قضية موصوفة بجملة `event` قصيرة تلخّص الحدث الواحد بعينه الذي تدور حوله.

مهمتك: حدّد أي زوج من القضايا يتناول **نفس الحدث بعينه** -- لا موضوعًا
عامًا مشتركًا (اسم شخص أو دولة أو قطاع وحده لا يكفي)، بل نفس الواقعة
تحديدًا ولو رواها كل طرف من زاوية أو بتفصيل مختلف. مثال: "صفقة نفط أمريكية-
فنزويلية أُعلنت" و"تفاصيل ما أُعلن فعلًا في اتفاق النفط الأمريكي
الفنزويلي" -- نفس الحدث، زاويتان مختلفتان. أما "صفقة نفط أمريكية-فنزويلية"
و"شروط إيرانية لفتح مضيق هرمز" فحدثان منفصلان تمامًا رغم اشتراكهما في ذكر
النفط والولايات المتحدة.

عبر الأداة المُعرَّفة (merge_duplicate_events) حصرًا، أعد قائمة `merges`:
كل عنصر `issue_indices` يحوي فهرسَي (`index`) القضيتين اللتين تتناولان
الحدث نفسه بعينه. عند الشك، لا تدمج -- قضيتان منفصلتان خطأ أهون من قضية
واحدة مضطربة. القضايا التي لا تشارك حدثًا مع أي قضية أخرى لا تظهر في
`merges` إطلاقًا."""

MERGE_SCHEMA = {
    "name": "merge_duplicate_events",
    "description": "يحدّد أزواج القضايا التي تتناول الحدث نفسه بعينه من قائمة أحداثها المختصرة",
    "input_schema": {
        "type": "object",
        "properties": {
            "merges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "issue_indices": {
                            "type": "array", "items": {"type": "integer"},
                            "description": "فهرسا (index) القضيتين اللتين تتناولان الحدث نفسه بعينه",
                        },
                    },
                    "required": ["issue_indices"],
                },
            },
        },
        "required": ["merges"],
    },
}


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def load_points(date_str: str) -> list[dict]:
    """يقرأ نقاط تشغيلة يوم بعينه من مخرج youtube_extract.py. ملف غير
    موجود (لم تُشغَّل المرحلة الثانية بعد لهذا التاريخ) يعيد قائمة فارغة لا
    استثناء -- عنقدة صفر نقاط قرار سليم لا عطل."""
    path = POINTS_DIR / f"{date_str}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("ملف نقاط يوتيوب تالف: %s", path)
        return []
    return data.get("points", [])


def _date_range(date_str: str, lookback_days: int) -> list[str]:
    """أقدم إلى أحدث -- ترتيب لا يؤثّر في نتيجة العنقدة (النموذج يستلم كل
    النقاط دفعة واحدة بلا اعتبار لترتيب وصولها)، لكنه يبقي ملف نقاط اليوم
    الحالي دومًا آخر عنصر، وهو ما تعتمد عليه بعض الاختبارات للقراءة."""
    base = datetime.strptime(date_str, "%Y-%m-%d")
    days = max(1, lookback_days)
    return [(base - timedelta(days=offset)).strftime("%Y-%m-%d")
            for offset in range(days - 1, -1, -1)]


def load_points_window(date_str: str, lookback_days: int) -> list[dict]:
    """يقرأ نقاط كل الأيام ضمن نافذة lookback_days المنتهية بـdate_str (Issue
    #658 العطل ١ بند أ) -- لا ملف اليوم وحده. التقاطع عبر الكتل نادر أن يقع
    في نفس اليوم بالضبط (الجزيرة تحلّل موضوعًا اليوم، وهابرتورك تتناوله
    غدًا)، فنافذة يوم واحد كانت تضمن صفر قضايا طبقة (أ) بنيويًا بصرف النظر عن
    المحتوى الفعلي.

    كل نقطة تحمل `run_date` (بند ب) لتمييز مصدرها -- يُستهلَك في build_topics
    للترجيح الخفيف نحو الحداثة، وفي point_key لسجل الاستهلاك أدناه. ملفات
    أيام غائبة (لم تُشغَّل المرحلة الثانية بعدها، أو تشغيلة أولى بلا تاريخ
    سابق) تُهمَل بصمت -- نفس مبدأ load_points، لا استثناء لمجرّد نقص تاريخي."""
    combined: list[dict] = []
    for day in _date_range(date_str, lookback_days):
        for point in load_points(day):
            point = dict(point)
            point["run_date"] = day
            combined.append(point)
    return combined


def apply_points_cap(points: list[dict], max_points_per_call: int) -> tuple[list[dict], int]:
    """يقصّ نافذة نقاط (بعد load_points_window) إلى max_points_per_call عند
    التجاوز (Issue #660 الإصلاح ٢) -- تُبقي الأحدث حسب run_date ثم ترتيب
    الظهور الأصلي عند تساوي run_date (فرز مستقر بـreverse=True يحافظ على
    استقرار المتساوي، لا يعكسه)، وتُسقِط الأقدم. max_points_per_call<=0
    يعني بلا سقف (يعيد points كما وصلت) -- قيمة تحوّطية لو غاب مفتاح config
    أو ضُبط صفرًا خطأً، لا حالة تُستعمَل فعليًا.

    **يجب استدعاؤها بنفس max_points_per_call من كل من youtube_cluster.run()
    وyoutube_article.run()** فوق نفس load_points_window(date_str,
    lookback_days) -- نفس مبدأ اتساق lookback_days الموثَّق أعلاه: point_ids
    كل قضية فهارس ضمن هذه القائمة تحديدًا، فلو قُصّت بسقف مختلف في إحدى
    المرحلتين لاختلفت الفهارس عن الأخرى فارتبطت قضية بنقاط خاطئة تمامًا.

    يعيد (النقاط المُبقاة بترتيبها الأصلي، عدد النقاط المُسقَطة)."""
    if max_points_per_call <= 0 or len(points) <= max_points_per_call:
        return points, 0
    order = sorted(range(len(points)), key=lambda i: points[i].get("run_date", ""), reverse=True)
    kept_indices = set(order[:max_points_per_call])
    kept = [p for i, p in enumerate(points) if i in kept_indices]
    dropped_points = [points[i] for i in order[max_points_per_call:]]
    dropped_dates = sorted({p.get("run_date", "") for p in dropped_points})
    date_note = dropped_dates[0] if len(dropped_dates) == 1 else f"{dropped_dates[0]}..{dropped_dates[-1]}"
    log.warning("قُصّت النقاط الداخلة: %d → %d (أُسقطت %d نقطة من %s)",
                len(points), len(kept), len(dropped_points), date_note)
    return kept, len(dropped_points)


def apply_min_points_date(points: list[dict], min_points_date: str | None) -> tuple[list[dict], int]:
    """يُسقِط نقاط ملفات أقدم من youtube.cluster.min_points_date (Issue #662
    العطل ٢ بند أ) -- نافذة lookback_days تجمع نقاط عدّة أيام بلا تمييز عصر
    الاستخلاص الذي أنتجها، فإصلاح جوهري في الاستخلاص (مرساة، حارس موضوع...)
    يترك خلفه أيامًا من مادة أُنتجت بمنطق قديم تظل تُسحَب كأنها صالحة طالما
    بقيت ضمن النافذة. المقارنة نصّية (YYYY-MM-DD قابلة للمقارنة معجميًا
    بصورة صحيحة). min_points_date فارغ/None يعني بلا حدّ -- تحوّطية لغياب
    المفتاح من config.yaml، لا حالة تُستعمَل فعليًا."""
    if not min_points_date:
        return points, 0
    kept = [p for p in points if p.get("run_date", "") >= min_points_date]
    return kept, len(points) - len(kept)


def apply_timestamp_guard(points: list[dict]) -> tuple[list[dict], int]:
    """حارس ثانٍ للأمان (Issue #662 العطل ٢ بند ج): أي نقطة طابعها الزمني
    يتجاوز duration_seconds فيديوها تُسقَط عند تحميل النافذة. الطوابع صارت
    مستحيلة الخطأ بنيويًا بعد إصلاح المرساة (resolve_timestamp في
    src/youtube_extract.py تحسبها من مقطع ينتمي فعلًا للفيديو)، لكن هذا
    يمسك ما تسرّب من ملفات أقدم من الإصلاح ولم يلتقطه min_points_date (لو
    ضُبط الحدّ التاريخي خطأً أو غاب). نقطة بلا timestamp (None -- المرساة
    لم تُوجَد) أو بلا duration_seconds تمرّ بلا مقارنة، لا رفض لغياب بيانات
    لا علاقة له بصحة الطابع."""
    kept: list[dict] = []
    dropped = 0
    for p in points:
        ts = p.get("timestamp")
        duration = p.get("duration_seconds")
        if ts is not None and isinstance(duration, (int, float)) and ts > duration:
            dropped += 1
            continue
        kept.append(p)
    return kept, dropped


def prepare_window_points(date_str: str, cfg: Config) -> tuple[list[dict], dict]:
    """يبني نافذة النقاط النهائية بترتيب ثابت واحد (Issue #662): تحميل
    النافذة (load_points_window) ← إسقاط ملفات أقدم من min_points_date ←
    إسقاط طابع يتجاوز مدة الفيديو ← قصّ سقف النداء (apply_points_cap).
    **يجب استدعاؤها بنفس cfg من كل من youtube_cluster.run() وyoutube_article.run()**
    -- نفس مبدأ اتساق apply_points_cap الموثَّق أعلاه بالضبط: point_ids كل
    قضية فهارس ضمن هذه القائمة تحديدًا، فاختلاف أي خطوة فلترة بين المرحلتين
    يربط قضية بنقاط خاطئة تمامًا. تجميع الخطوات هنا في دالة واحدة يضمن
    الاتساق بنيويًا لا بمجرّد اتفاق توثيقي بين الملفين.

    يعيد (النقاط الجاهزة لنداء العنقدة/الكتابة، قاموس إحصاءات الإسقاط في كل
    خطوة)."""
    lookback_days = cfg.path("youtube.cluster.lookback_days", 3)
    min_points_date = cfg.path("youtube.cluster.min_points_date")
    max_points_per_call = cfg.path("youtube.cluster.max_points_per_call", 150)

    window_points = load_points_window(date_str, lookback_days)
    points, dropped_stale_date = apply_min_points_date(window_points, min_points_date)
    points, dropped_bad_timestamp = apply_timestamp_guard(points)
    points, dropped_over_cap = apply_points_cap(points, max_points_per_call)

    return points, {
        "points_in": len(window_points),
        "points_dropped_stale_date": dropped_stale_date,
        "points_dropped_bad_timestamp": dropped_bad_timestamp,
        "points_dropped_over_cap": dropped_over_cap,
    }


def point_key(point: dict) -> str:
    """معرّف مستقر لنقطة عبر تشغيلات مختلفة (خلافًا لمعرّفها الرقمي `id`
    الذي هو مجرّد فهرس ضمن نافذة تشغيلة بعينها، يتغيّر شكله يوميًا). فيديو +
    نصّ القول يكفيان عمليًا -- لا حاجة لمعرّف صريح لم يكن موجودًا أصلًا في
    مخرج src/youtube_extract.py، وتضارب مصادفة (نفس الفيديو ونفس نصّ الملخّص
    حرفيًا لقولين مختلفين) غير وارد عمليًا."""
    return f"{point.get('video_id', '')}::{point.get('statement', '')}"


def load_topics(date_str: str) -> dict:
    """يقرأ مخرج هذه المرحلة نفسها (state/youtube_topics/YYYY-MM-DD.json)
    -- يستهلكها src/youtube_article.py. ملف غير موجود يعيد بنية فارغة
    متّسقة الشكل مع run()، لا استثناء."""
    path = TOPICS_DIR / f"{date_str}.json"
    if not path.exists():
        return {"run_date": date_str, "topics": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("ملف قضايا يوتيوب تالف: %s", path)
        return {"run_date": date_str, "topics": []}


def load_seen_points() -> dict[str, str]:
    """يقرأ سجل النقاط المستهلكة (معرّف ← تاريخ آخر تسجيل). ملف غائب أو تالف
    يعيد قاموسًا فارغًا لا استثناء -- نفس مبدأ load_points/load_topics، سجل
    استهلاك فارغ يعني ببساطة "لا شيء اسْتُهلِك بعد"، لا عطلًا."""
    if not SEEN_PATH.exists():
        return {}
    try:
        data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("سجل القضايا المستهلكة تالف: %s", SEEN_PATH)
        return {}
    return data if isinstance(data, dict) else {}


def mark_points_seen(keys: set[str], run_date: str, retention_days: int = 14) -> None:
    """يُستدعى من src/youtube_article.py بعد نجاح كتابة مقال فعليًا. يقلّم
    السجل بنفس أفق youtube.seen_retention_days (افتراضيًا ١٤ يومًا، أوسع
    بفارق واسع من youtube.cluster.lookback_days) -- نقطة خرجت من كل نوافذ
    lookback المحتملة لا فائدة من إبقائها في السجل، فينمو الملف بلا حدّ
    لولا هذا التقليم."""
    seen = load_seen_points()
    for key in keys:
        seen[key] = run_date
    cutoff = (datetime.strptime(run_date, "%Y-%m-%d")
              - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(seen, ensure_ascii=False, indent=2, sort_keys=True),
                          encoding="utf-8")


def filter_seen_topics(topics: list[dict], points: list[dict],
                        seen_keys: set[str]) -> tuple[list[dict], int]:
    """يُهمِل قضية أكثر نقاطها (أغلبية صارمة، لا مجرّد نقطة واحدة مستهلكة من
    عدّة) دخلت مقالًا مكتوبًا سابقًا (Issue #658 العطل ١ بند ج) -- بلا هذا
    قد يُعاد كتابة نفس القضية أيامًا متتالية طالما بقيت نقاطها ضمن نافذة
    lookback_days. يعيد (القضايا الناجية، عدد المُهمَل)."""
    kept: list[dict] = []
    dropped = 0
    for topic in topics:
        member_points = [points[pid] for pid in topic["point_ids"] if 0 <= pid < len(points)]
        if not member_points:
            kept.append(topic)
            continue
        seen_count = sum(1 for p in member_points if point_key(p) in seen_keys)
        if seen_count > len(member_points) / 2:
            dropped += 1
            continue
        kept.append(topic)
    return kept, dropped


def apply_min_points(topics: list[dict], min_points: int) -> tuple[list[dict], int]:
    """قضية دون min_points_per_topic (افتراضيًا ٤) لا تدخل مخرج العنقدة
    (Issue #658 العطل ٢) -- مقالات أقل وأغنى خير من مقالات أكثر وأفقر، ونصّ
    الـIssue الحرفي: مقال من نقطتين خرج معترفًا بفقره بدل امتناعه عن الكتابة.
    استثناء طبقة (أ) بثلاث نقاط بدل أربع (بند ج) -- قيمة قضية عبر كتلتين في
    التقاطع نفسه لا في كمّ نقاطها. يعيد (القضايا الناجية، عدد المُهمَل)."""
    kept: list[dict] = []
    dropped = 0
    for topic in topics:
        threshold = 3 if topic["layer"] == "a" else min_points
        if len(topic["point_ids"]) < threshold:
            dropped += 1
            continue
        kept.append(topic)
    return kept, dropped


def _brief_points(points: list[dict]) -> list[dict]:
    """الحقول المختصرة فقط تُرسَل للنموذج -- لا الاقتباسات ولا الروابط ولا
    الطوابع. تلك تُستهلَك لاحقًا في الكتابة (src/youtube_article.py) بعد أن
    تُحدَّد القضايا، ولا فائدة عنقدية من إرسالها هنا فتُضخِّم النداء بلا
    داعٍ (نحو ١٥ ألف رمز للتشغيلة المرجعية بالحقول المختصرة وحدها)."""
    return [
        {"id": i, "statement": p.get("statement", ""), "speaker": p.get("speaker", ""),
         "channel": p.get("channel", ""), "bloc": p.get("bloc", ""),
         "topic_hint": p.get("topic_hint", ""), "type": p.get("type", "")}
        for i, p in enumerate(points)
    ]


def cluster_points(points: list[dict], cfg: Config, client: Anthropic | None = None
                    ) -> tuple[list[dict], str | None]:
    """نداء للنموذج (محاولة واحدة + إعادة محاولة واحدة عند غياب إخراج مهيكل
    صالح -- Issue #660، نفس آلية youtube_extract.extract_points بالضبط).
    يعيد (قضايا خامة صالحة الشكل -- title/agreement/point_ids بمعرّفات ضمن
    نطاق points فقط، سبب فشل النداء العام إن حدث -- None عند النجاح ولو بلا
    قضايا)."""
    if not points:
        return [], None

    model = cfg.path("youtube.cluster.model", "claude-sonnet-5")
    max_tokens = cfg.path("youtube.cluster.max_tokens", 4000)
    max_retries = cfg.path("youtube.cluster.max_retries", 2)
    client = client or Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))

    brief = _brief_points(points)

    raw_issues: list | None = None
    last_snippet = ""
    last_resp = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                tools=[CLUSTER_SCHEMA],
                tool_choice={"type": "tool", "name": "cluster_points"},
                system=load_prompt(),
                messages=[{"role": "user", "content": json.dumps(brief, ensure_ascii=False)}],
                # لا تُضِف temperature -- نماذج هذا المشروع ترفضها بـ400.
            )
        except APIError as exc:
            return [], f"فشل نداء العنقدة: {exc}"

        last_resp = resp
        data = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
        candidate = data.get("issues") if isinstance(data, dict) else None
        if isinstance(candidate, list):
            raw_issues = candidate
            break

        text_snippet = "".join(b.text for b in resp.content
                                if getattr(b, "type", "") == "text")[:500]
        stop_reason = getattr(resp, "stop_reason", None)
        if stop_reason == "max_tokens":
            # صيغة الـIssue الحرفية -- بلا هذا نعود إلى التخمين في المرة القادمة.
            usage = getattr(resp, "usage", None)
            output_tokens = getattr(usage, "output_tokens", "؟") if usage is not None else "؟"
            log.warning("قُطع إخراج العنقدة (stop_reason: max_tokens) — %d نقطة مدخلة، "
                        "%s رمز مستهلك", len(points), output_tokens)
            last_snippet = f"[stop_reason=max_tokens] {text_snippet}"
        else:
            log.warning("محاولة %d/%d: لم يُعِد نداء العنقدة إخراجًا مهيكلًا صالحًا "
                        "(stop_reason=%s، %d نقطة مدخلة)", attempt, max_retries,
                        stop_reason, len(points))
            last_snippet = text_snippet

    if raw_issues is None:
        usage_note = ""
        usage = getattr(last_resp, "usage", None)
        if usage is not None:
            usage_note = (f"، رموز مستهلكة: مدخل {getattr(usage, 'input_tokens', '؟')}"
                          f"/مخرج {getattr(usage, 'output_tokens', '؟')}")
        return [], (f"لم يُعِد النموذج إخراجًا مهيكلًا صالحًا بعد {max_retries} محاولة/محاولات "
                    f"({len(points)} نقطة مدخلة{usage_note}): {last_snippet!r}")

    max_id = len(points) - 1
    issues: list[dict] = []
    for raw in raw_issues:
        if not isinstance(raw, dict):
            continue
        title = raw.get("title")
        event = raw.get("event")
        agreement = raw.get("agreement")
        point_ids = raw.get("point_ids")
        if not isinstance(title, str) or not title.strip():
            continue
        # حقل event إلزامي (Issue #658 العطل ٤) -- غيابه أو فراغه يعني أن
        # النموذج لم يحدّد حدثًا بعينه، وهذا بالضبط ما يمنع خلط موضوعين
        # متجاورين (شاهد الـIssue: صفقة النفط الفنزويلية مقابل هرمز).
        if not isinstance(event, str) or not event.strip():
            continue
        if agreement not in AGREEMENT_VALUES:
            continue
        if not isinstance(point_ids, list):
            continue
        # معرّفات خارج نطاق النقاط المُرسَلة (اختلاق أو خطأ عدّ من النموذج)
        # تُهمَل بصمت -- لا ترفض القضية كلها، بقية المعرّفات الصحيحة تبقى.
        valid_ids = sorted({pid for pid in point_ids
                             if isinstance(pid, int) and not isinstance(pid, bool)
                             and 0 <= pid <= max_id})
        if len(valid_ids) < 2:
            # قضية بنقطة واحدة أو أقل ليست تقاطعًا -- لا قيمة عنقدية لها
            # (البرومبت يطلب هذا صراحة، هذا تحقّق برمجي مساند لا يثق بطاعة
            # النموذج وحدها).
            continue
        issues.append({"title": title.strip(), "event": event.strip(), "agreement": agreement,
                        "point_ids": valid_ids})
    return issues, None


def _merge_issue_group(issues: list[dict], group: set[int]) -> dict:
    """يدمج مجموعة قضايا (فهارس ضمن issues) تتناول نفس الحدث في قضية واحدة
    (Issue #662 العطل ١ بند ب): نقاط كل القضايا تُضَمّ (اتحاد لا تكرار --
    قضية قد تشارك نقطة مع أخرى نظريًا)، والعنوان/الحدث يُؤخذان من أول قضية
    بترتيب ظهورها الأصلي (تشخيصي فقط، لا يُنشَر). مؤشّر الخلاف الخام يُؤخذ
    من الأعلى رتبة بين القضايا المدموجة (dispute يتقدّم على agreement على
    echo، بنفس _AGREEMENT_RANK الخام قبل تنقيح cross_source/internal) --
    قضية دُمجت من خلاف حقيقي وأخرى اتفاق تبقى خلافًا، فذلك ما ورد في أحد
    مصدريها فعليًا. الطبقة **لا** تُحسَب هنا -- build_topics يحسبها لاحقًا
    من point_ids المدموجة، فالتعادل مضمون برمجيًا لا بإعادة حساب مكرَّرة."""
    ordered = sorted(group)
    primary = issues[ordered[0]]
    combined_point_ids = sorted({pid for i in ordered for pid in issues[i]["point_ids"]})
    best_agreement = min((issues[i]["agreement"] for i in ordered),
                          key=lambda a: _RAW_AGREEMENT_RANK.get(a, 99))
    return {"title": primary["title"], "event": primary["event"], "agreement": best_agreement,
            "point_ids": combined_point_ids}


def merge_duplicate_events(issues: list[dict], cfg: Config, client: Anthropic | None = None
                            ) -> tuple[list[dict], list[list[str]], str | None]:
    """نداء قصير رخيص (Issue #662 العطل ١) يقارن جمل `event` فقط لكل قضية
    ويعيد أزواج القضايا المتناولة لنفس الحدث بعينه، فتُدمَج قبل حساب الطبقة
    النهائية -- عنقدة النقاط في cluster_points أدقّ من اللازم أحيانًا:
    مصدران مختلفان لنفس الحدث ينتجان قضيتين منفصلتين لمجرّد اختلاف نقاطهما
    المصدرية (شاهد الـIssue: قضيتا صفقة النفط الفنزويلية من مصدرين مختلفين).

    يعيد (القضايا بعد الدمج، سجل أزواج العناوين المدموجة لكل تجميعة، سبب
    فشل النداء إن حدث). فشل النداء أو أقل من قضيتين لا يمنعان التشغيلة --
    نفس مبدأ check_forbidden/classify_topic: عطل شبكي عابر ليس دليل عدم
    تكرار، والقضايا تبقى كما عنقدتها cluster_points بلا دمج بدل إسقاطها."""
    if len(issues) < 2:
        return issues, [], None

    model = cfg.path("youtube.cluster.merge_model",
                      cfg.path("youtube.extract.model", "claude-haiku-4-5-20251001"))
    max_tokens = cfg.path("youtube.cluster.merge_max_tokens", 2000)
    max_retries = cfg.path("youtube.cluster.merge_max_retries", 2)
    client = client or Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))

    brief = [{"index": i, "event": issue["event"]} for i, issue in enumerate(issues)]

    raw_merges: list | None = None
    last_snippet = ""
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                tools=[MERGE_SCHEMA],
                tool_choice={"type": "tool", "name": "merge_duplicate_events"},
                system=MERGE_SYSTEM,
                messages=[{"role": "user", "content": json.dumps(brief, ensure_ascii=False)}],
                # لا تُضِف temperature -- نماذج هذا المشروع ترفضها بـ400.
            )
        except APIError as exc:
            log.warning("فشل نداء دمج الأحداث المتكرّرة -- بلا دمج هذه التشغيلة: %s", exc)
            return issues, [], f"فشل نداء الدمج: {exc}"

        data = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
        candidate = data.get("merges") if isinstance(data, dict) else None
        if isinstance(candidate, list):
            raw_merges = candidate
            break
        text_snippet = "".join(b.text for b in resp.content
                                if getattr(b, "type", "") == "text")[:500]
        log.warning("محاولة %d/%d: لم يُعِد نداء الدمج إخراجًا مهيكلًا صالحًا (%d قضية مدخلة)",
                    attempt, max_retries, len(issues))
        last_snippet = text_snippet

    if raw_merges is None:
        return issues, [], (f"لم يُعِد نداء الدمج إخراجًا مهيكلًا صالحًا بعد {max_retries} "
                             f"محاولة/محاولات: {last_snippet!r}")

    # اتحاد-بحث (union-find) بسيط -- يدعم تجميعات متسلسلة (أ-ب نفس الحدث،
    # ب-ج نفس الحدث ⇐ أ وب وج قضية واحدة) بلا افتراض أن كل زوج مستقل.
    parent = list(range(len(issues)))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def _union(i: int, j: int) -> None:
        ri, rj = _find(i), _find(j)
        if ri != rj:
            parent[rj] = ri

    for raw in raw_merges:
        if not isinstance(raw, dict):
            continue
        pair = raw.get("issue_indices")
        if not isinstance(pair, list):
            continue
        valid = [i for i in pair if isinstance(i, int) and not isinstance(i, bool)
                 and 0 <= i < len(issues)]
        for i in valid[1:]:
            _union(valid[0], i)

    groups: dict[int, set[int]] = {}
    for i in range(len(issues)):
        groups.setdefault(_find(i), set()).add(i)

    merged_issues: list[dict] = []
    merge_log: list[list[str]] = []
    for group in groups.values():
        if len(group) < 2:
            merged_issues.append(issues[next(iter(group))])
            continue
        merged_issues.append(_merge_issue_group(issues, group))
        merge_log.append([issues[i]["title"] for i in sorted(group)])

    return merged_issues, merge_log, None


def _layer_for(blocs: set[str], channels: set[str]) -> str:
    if len(blocs) >= 2:
        return "a"
    if len(channels) >= 2:
        return "b"
    return "c"


def _agreement_type_for(raw_agreement: str, channels: set[str]) -> str:
    """`dispute` من حكم النموذج (cluster_points) يُنقَّح برمجيًا إلى
    cross_source/internal (Issue #662 العطل ٤) -- خلاف حقيقي بين قنوات
    مختلفة يختلف صحفيًا عن خلاف بين ضيوف داخل حلقة قناة واحدة، وخلطهما بوسم
    `dispute` واحد يفقد المؤشّر معناه (شاهد الـIssue: قضية هرمز خلاف داخلي
    بين ثلاثة باحثين على الجزيرة وُسِمت كخلاف بنفس وزن قضية بها ثلاث قنوات
    فعليًا مختلفة). المعيار ميكانيكي محض من channels الفعلية للقضية بعد
    العنقدة/الدمج -- لا حكم نموذج إضافي: قنوات مختلفة فأكثر ⇐ cross_source،
    وإلا (قناة واحدة، خلاف بين متحدثيها) ⇐ internal. `agreement` وecho
    يمرّان بلا تغيير -- الحكم الدلالي (هل يوجد خلاف أصلًا؟) يبقى للنموذج."""
    if raw_agreement != "dispute":
        return raw_agreement
    return "cross_source" if len(channels) >= 2 else "internal"


def build_topics(issues: list[dict], points: list[dict],
                  today_date_str: str | None = None) -> list[dict]:
    """يحوّل قضايا العنقدة الخامة إلى بنية المخرج النهائية: يحسب الطبقة
    وقوائم الكتل/القنوات من نقاط كل قضية فعليًا (لا من حكم النموذج)، ثم
    يفرز بمفتاح مركّب (الطبقة أولًا، مؤشّر الخلاف ثانيًا، ترجيح الحداثة
    ثالثًا وأخيرًا -- Issue #658 العطل ١ بند د: قضية فيها نقطة من
    today_date_str تتقدّم على قضية كل نقاطها أقدم، عند تساوي الطبقة
    والخلاف فقط، لا فوقهما -- «ترجيح خفيف» بنص الـIssue)."""
    topics = []
    for issue in issues:
        member_points = [points[pid] for pid in issue["point_ids"]]
        blocs = sorted({p.get("bloc", "") for p in member_points if p.get("bloc")})
        channels = sorted({p.get("channel", "") for p in member_points if p.get("channel")})
        layer = _layer_for(set(blocs), set(channels))
        agreement = _agreement_type_for(issue["agreement"], set(channels))
        has_today = (today_date_str is not None and
                     any(p.get("run_date") == today_date_str for p in member_points))
        topics.append({
            "title": issue["title"],
            "event": issue["event"],
            "layer": layer,
            "blocs": blocs,
            "channels": channels,
            "agreement": agreement,
            "point_ids": issue["point_ids"],
            "_has_today": has_today,
        })

    topics.sort(key=lambda t: (_LAYER_RANK[t["layer"]], _AGREEMENT_RANK[t["agreement"]],
                                0 if t["_has_today"] else 1))
    for t in topics:
        del t["_has_today"]
    return topics


def apply_bloc_cap(topics: list[dict], max_per_bloc: int) -> tuple[list[dict], int]:
    """يبقي القضايا مرتّبة كما وصلت (فرز build_topics سابق لهذه الخطوة) --
    فرز مستقر (stable) يبقي ترتيب الطبقة/الخلاف الأصلي بين القضايا التي
    تُقبَل معًا -- ويستبعد أي قضية تجعل عدد قضايا كتلة ما يتجاوز
    max_per_bloc، حتى لا تحتلّ كتلة واحدة القائمة. نفس منطق select_top في
    youtube_collect.py: أخذ الأعلى ترتيبًا أولًا لمورد محدود. يعيد
    (القضايا الناجية، عدد القضايا المستبعدة)."""
    counts: dict[str, int] = {}
    kept: list[dict] = []
    dropped = 0
    for topic in topics:
        blocs = topic["blocs"] or ["_unknown"]
        if any(counts.get(b, 0) >= max_per_bloc for b in blocs):
            dropped += 1
            continue
        for b in blocs:
            counts[b] = counts.get(b, 0) + 1
        kept.append(topic)
    return kept, dropped


def run(cfg: Config | None = None, date_str: str | None = None,
        client: Anthropic | None = None, now: datetime | None = None) -> dict:
    cfg = cfg or load_config()
    now = now or datetime.now(timezone.utc)
    date_str = date_str or now.strftime("%Y-%m-%d")

    min_points_per_topic = cfg.path("youtube.cluster.min_points_per_topic", 4)
    max_per_bloc = cfg.path("youtube.cluster.max_per_bloc", 4)

    points, window_stats = prepare_window_points(date_str, cfg)

    raw_issues, error = cluster_points(points, cfg, client)
    merged_issues, merge_log, merge_error = merge_duplicate_events(raw_issues, cfg, client)
    if merge_error:
        log.warning("تعذّر دمج الأحداث المتكرّرة، بلا دمج هذه التشغيلة: %s", merge_error)
    topics = build_topics(merged_issues, points, date_str)

    seen_keys = set(load_seen_points().keys())
    topics, dropped_by_seen = filter_seen_topics(topics, points, seen_keys)
    topics, dropped_by_min_points = apply_min_points(topics, min_points_per_topic)
    topics, dropped_by_cap = apply_bloc_cap(topics, max_per_bloc)

    layer_counts = {"a": 0, "b": 0, "c": 0}
    agreement_counts = {"agreement": 0, "cross_source": 0, "internal": 0, "echo": 0}
    for t in topics:
        layer_counts[t["layer"]] += 1
        agreement_counts[t["agreement"]] += 1

    return {
        "run_date": date_str,
        "stats": {
            "points_in": window_stats["points_in"],
            "points_dropped_stale_date": window_stats["points_dropped_stale_date"],
            "points_dropped_bad_timestamp": window_stats["points_dropped_bad_timestamp"],
            "points_dropped_over_cap": window_stats["points_dropped_over_cap"],
            "issues_clustered": len(raw_issues),
            "topics_merged": len(merge_log),
            "topics_out": len(topics),
            "dropped_by_bloc_cap": dropped_by_cap,
            "topics_seen_skipped": dropped_by_seen,
            "topics_below_min_points": dropped_by_min_points,
            "layer_a": layer_counts["a"], "layer_b": layer_counts["b"],
            "layer_c": layer_counts["c"],
            "agreement": agreement_counts["agreement"],
            "cross_source": agreement_counts["cross_source"],
            "internal": agreement_counts["internal"],
            "echo": agreement_counts["echo"],
        },
        "error": error,
        "merged_events": merge_log,
        "topics": topics,
    }


def save_output(result: dict) -> Path:
    TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    path = TOPICS_DIR / f"{result['run_date']}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    result = run()
    path = save_output(result)
    stats = result["stats"]
    print(f"ملف القضايا: {path}")
    print(f"نقاط مدخلة: {stats['points_in']} (أُسقطت بتاريخ قديم: "
          f"{stats['points_dropped_stale_date']} · بطابع فاسد: "
          f"{stats['points_dropped_bad_timestamp']} · بسقف النداء: "
          f"{stats['points_dropped_over_cap']}) · قضايا مُعنقدة: {stats['issues_clustered']} "
          f"(دُمج منها: {stats['topics_merged']}) "
          f"· قضايا في المخرج: {stats['topics_out']} "
          f"(مستبعدة بسقف الكتلة: {stats['dropped_by_bloc_cap']} "
          f"· مستهلكة سابقًا: {stats['topics_seen_skipped']} "
          f"· دون حدّ النقاط: {stats['topics_below_min_points']})")
    print(f"الطبقات: أ={stats['layer_a']} ب={stats['layer_b']} ج={stats['layer_c']}")
    print(f"مؤشّر الخلاف: اتفاق={stats['agreement']} خلاف قنوات={stats['cross_source']} "
          f"خلاف داخلي={stats['internal']} صدى={stats['echo']}")
    if result["merged_events"]:
        for pair in result["merged_events"]:
            print(f"  دُمجت: {' + '.join(pair)}")
    if result["error"]:
        print(f"خطأ: {result['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
