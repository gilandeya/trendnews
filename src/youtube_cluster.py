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
قضية يمنع خلط حدثين متجاورين يشتركان في اسم أو قطاع بلا كونهما نفس الحدث."""
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

AGREEMENT_VALUES = ("agreement", "dispute", "echo")
# ترتيب مؤشّر الخلاف داخل الطبقة الواحدة: خلاف حقيقي بين المصادر يرفع
# الترتيب، الاتفاق التام يخفضه، والصدى (نفس الخبر معاد صياغته) ينزل إلى
# أدنى الترتيب دومًا -- «قيمة هذا المسار في الاختلاف» (نص الـIssue).
_AGREEMENT_RANK = {"dispute": 0, "agreement": 1, "echo": 2}
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
    """نداء واحد للنموذج. يعيد (قضايا خامة صالحة الشكل -- title/agreement/
    point_ids بمعرّفات ضمن نطاق points فقط، سبب فشل النداء العام إن حدث --
    None عند النجاح ولو بلا قضايا)."""
    if not points:
        return [], None

    model = cfg.path("youtube.cluster.model", "claude-sonnet-5")
    max_tokens = cfg.path("youtube.cluster.max_tokens", 4000)
    client = client or Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))

    brief = _brief_points(points)
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

    data = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
    raw_issues = data.get("issues") if isinstance(data, dict) else None
    if not isinstance(raw_issues, list):
        return [], "لم يُعِد النموذج إخراجًا مهيكلًا صالحًا (لا قائمة issues)"

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


def _layer_for(blocs: set[str], channels: set[str]) -> str:
    if len(blocs) >= 2:
        return "a"
    if len(channels) >= 2:
        return "b"
    return "c"


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
        has_today = (today_date_str is not None and
                     any(p.get("run_date") == today_date_str for p in member_points))
        topics.append({
            "title": issue["title"],
            "event": issue["event"],
            "layer": layer,
            "blocs": blocs,
            "channels": channels,
            "agreement": issue["agreement"],
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

    lookback_days = cfg.path("youtube.cluster.lookback_days", 3)
    min_points_per_topic = cfg.path("youtube.cluster.min_points_per_topic", 4)
    max_per_bloc = cfg.path("youtube.cluster.max_per_bloc", 4)

    points = load_points_window(date_str, lookback_days)

    raw_issues, error = cluster_points(points, cfg, client)
    topics = build_topics(raw_issues, points, date_str)

    seen_keys = set(load_seen_points().keys())
    topics, dropped_by_seen = filter_seen_topics(topics, points, seen_keys)
    topics, dropped_by_min_points = apply_min_points(topics, min_points_per_topic)
    topics, dropped_by_cap = apply_bloc_cap(topics, max_per_bloc)

    layer_counts = {"a": 0, "b": 0, "c": 0}
    agreement_counts = {"agreement": 0, "dispute": 0, "echo": 0}
    for t in topics:
        layer_counts[t["layer"]] += 1
        agreement_counts[t["agreement"]] += 1

    return {
        "run_date": date_str,
        "stats": {
            "points_in": len(points),
            "issues_clustered": len(raw_issues),
            "topics_out": len(topics),
            "dropped_by_bloc_cap": dropped_by_cap,
            "topics_seen_skipped": dropped_by_seen,
            "topics_below_min_points": dropped_by_min_points,
            "layer_a": layer_counts["a"], "layer_b": layer_counts["b"],
            "layer_c": layer_counts["c"],
            "agreement": agreement_counts["agreement"], "dispute": agreement_counts["dispute"],
            "echo": agreement_counts["echo"],
        },
        "error": error,
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
    print(f"نقاط مدخلة: {stats['points_in']} · قضايا مُعنقدة: {stats['issues_clustered']} "
          f"· قضايا في المخرج: {stats['topics_out']} "
          f"(مستبعدة بسقف الكتلة: {stats['dropped_by_bloc_cap']} "
          f"· مستهلكة سابقًا: {stats['topics_seen_skipped']} "
          f"· دون حدّ النقاط: {stats['topics_below_min_points']})")
    print(f"الطبقات: أ={stats['layer_a']} ب={stats['layer_b']} ج={stats['layer_c']}")
    print(f"مؤشّر الخلاف: اتفاق={stats['agreement']} خلاف={stats['dispute']} صدى={stats['echo']}")
    if result["error"]:
        print(f"خطأ: {result['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
