"""المرحلة الرابعة من مسار يوتيوب (Issue #646): كتابة مقالات عربية من أعلى
قضايا src/youtube_cluster.py، للقراءة فقط -- لا مسودات في drafts/، لا Issue
مراجعة، لا صور، لا نشر (خارج نطاق هذه المهمة صراحةً).

يأخذ أعلى ``youtube.article.count`` قضية (افتراضيًا ١٠) ويكتب لكل واحدة
مقالًا بنموذج أقوى من نموذج العنقدة -- مقال مقسَّم إلى أسئلة فرعية، بنسبة
صريحة لكل متحدث لا لقناته، وبلا أي معلومة من خارج النقاط المرفقة (انظر
prompts/youtube_article.md للقواعد التحريرية كاملة).

خرج المقال **نصّ عادي** (Markdown) لا إخراج مهيكل -- خلافًا لمرحلة العنقدة:
البنية هنا نثرية (عنوان + فقرات + رؤوس فرعية) لا بيانات مصنَّفة في حقول،
فلا فائدة من إجبارها في مخطّط tool_use؛ التحقّق من مطابقة البنية يقع بعد
الاستلام (_validate_article_text) لا أثناء الطلب.

قائمة المحظورات (skipped بسببها) تُطبَّق فقط على قضايا الطبقة (ج) -- مصدر
واحد -- عبر نداء حرّاس رخيص منفصل قبل إنفاق نداء الكتابة الأقوى، بنفس مبدأ
حارس الموضوع في src/youtube_extract.py: حكم دلالي رخيص قبل تكلفة كبيرة."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic, APIError

from . import youtube_cluster
from .config import STATE_DIR, Config, env, load_config

log = logging.getLogger(__name__)

ARTICLE_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "youtube_article.md"
ARTICLES_DIR = STATE_DIR / "youtube_articles"

# قائمة المحظورات (نص الـIssue) -- لا يُكتب مقال بمصدر واحد (طبقة ج) عن أيّ
# من هذه الأبواب مهما كانت النسبة صريحة؛ تحتاج طبقة (أ) أو (ب) بدلًا منها.
FORBIDDEN_CATEGORIES = (
    "accusation_named",           # اتهام شخص أو جهة مسمّاة بجريمة أو فساد أو خيانة
    "health_medical",             # ادعاءات صحية أو دوائية أو علاجية
    "military_ops",               # حركات جيوش أو عمليات وشيكة أو مواقع منشآت
    "sectarian_generalization",   # ما يمسّ طائفة أو قومية أو دينًا بتعميم
    "market_moving_numbers",      # أرقام مالية محددة قابلة لتحريك سوق
    "minors",                     # ما يخصّ قاصرين
)

GUARD_SCHEMA = {
    "name": "check_forbidden_topic",
    "description": ("يفحص إن كانت قضية أحادية المصدر (طبقة ج) تقع ضمن قائمة "
                     "المحظورات التي تمنع الكتابة عنها بمصدر واحد"),
    "input_schema": {
        "type": "object",
        "properties": {
            "blocked": {"type": "boolean"},
            "category": {"type": "string", "enum": list(FORBIDDEN_CATEGORIES) + ["none"]},
            "reason": {"type": "string", "description": "شرح عربي قصير للسبب"},
        },
        "required": ["blocked", "category", "reason"],
    },
}

GUARD_SYSTEM = """أنت حارس محظورات لقضايا أحادية المصدر (تناولتها قناة واحدة
فقط بلا تأكيد مستقل). القضايا التالية لا يجوز كتابة مقال عنها بمصدر واحد
مهما كانت النسبة صريحة لقائلها:

- accusation_named: اتهام شخص أو جهة مسمّاة بجريمة أو فساد أو خيانة.
- health_medical: ادعاءات صحية أو دوائية أو علاجية.
- military_ops: حركات جيوش أو عمليات عسكرية وشيكة أو مواقع منشآت.
- sectarian_generalization: ما يمسّ طائفة أو قومية أو دينًا بتعميم.
- market_moving_numbers: أرقامًا مالية محدَّدة قابلة لتحريك سوق.
- minors: ما يخصّ قاصرين.

تستلم ملخّص نقاط قضية واحدة. اضبط blocked=true وcategory بالفئة المطابقة
إن انطبقت واحدة منها على مضمون القضية، وإلا blocked=false وcategory="none".
الحكم على المضمون لا على درجة يقين الصياغة -- اتهام "مزعوم" يبقى اتهامًا."""


def load_article_prompt() -> str:
    return ARTICLE_PROMPT_PATH.read_text(encoding="utf-8")


def _topic_summary(topic: dict, member_points: list[dict]) -> str:
    lines = [f"القضية: {topic['title']}"]
    for p in member_points:
        lines.append(f"- ({p.get('speaker', '')} عبر {p.get('channel', '')}): "
                     f"{p.get('statement', '')}")
    return "\n".join(lines)


def check_forbidden(topic: dict, member_points: list[dict], cfg: Config,
                     client: Anthropic | None = None) -> tuple[bool, str, str | None]:
    """يعيد (محظورة، السبب، سبب فشل النداء إن حدث -- None عند النجاح).
    فشل النداء لا يحظر القضية تلقائيًا -- نفس مبدأ classify_topic في
    src/youtube_extract.py: عطل شبكي عابر ليس دليل حظر، وإسقاط القضية
    صامتًا لهذا السبب يناقض مبدأ المشروع في عدم الفشل الصامت."""
    model = cfg.path("youtube.article.guard_model",
                      cfg.path("youtube.extract.model", "claude-haiku-4-5-20251001"))
    client = client or Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=200,
            tools=[GUARD_SCHEMA],
            tool_choice={"type": "tool", "name": "check_forbidden_topic"},
            system=GUARD_SYSTEM,
            messages=[{"role": "user", "content": _topic_summary(topic, member_points)}],
            # لا تُضِف temperature -- نماذج هذا المشروع ترفضها بـ400.
        )
    except APIError as exc:
        return False, "", f"فشل نداء حارس المحظورات: {exc}"

    data = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
    if not isinstance(data, dict):
        return False, "", None
    category = data.get("category")
    blocked = bool(data.get("blocked")) and category in FORBIDDEN_CATEGORIES
    return blocked, str(data.get("reason", "")), None


def _points_block(member_points: list[dict]) -> str:
    lines = []
    for i, p in enumerate(member_points, start=1):
        ts = f"{p['timestamp']}ث" if p.get("timestamp") is not None else "غير معروف"
        lines.append(
            f"{i}. القناة: {p.get('channel', '')} ({p.get('bloc', '')}) | "
            f"المتحدث: {p.get('speaker', '')} | النوع: {p.get('type', '')}\n"
            f"   القول: {p.get('statement', '')}\n"
            f"   الاقتباس العربي: {p.get('quote_arabic', '')}\n"
            f"   الفيديو: {p.get('video_title', '')} — {p.get('video_url', '')} "
            f"(الطابع: {ts})"
        )
    return "\n".join(lines)


_HEADING_RE = re.compile(r"^##\s+\S", re.MULTILINE)


def _validate_article_text(text: str) -> tuple[bool, str]:
    if not text.strip().startswith("#"):
        return False, "لا يبدأ بعنوان رئيسي (# )"
    if len(_HEADING_RE.findall(text)) < 3:
        return False, "أقل من ثلاثة أسئلة فرعية (## )"
    if "المصادر" not in text:
        return False, "لا قسم مصادر"
    word_count = len(text.split())
    if word_count < 150:
        return False, f"قصير جدًا ({word_count} كلمة)"
    return True, ""


def draft_article(topic: dict, member_points: list[dict], cfg: Config,
                   client: Anthropic | None = None) -> tuple[str | None, str | None]:
    """نداء نموذج أقوى، إخراج نصّ عادي (لا tool_use) -- انظر توثيق أعلى
    الملف. يعيد (نصّ المقال، سبب الفشل بعد استنفاد المحاولات -- None عند
    النجاح)."""
    model = cfg.path("youtube.article.model", "claude-opus-5")
    max_tokens = cfg.path("youtube.article.max_tokens", 3000)
    max_retries = cfg.path("youtube.article.max_retries", 2)
    client = client or Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))

    user_content = (
        f"مؤشّر الخلاف بين المصادر لهذه القضية: {topic['agreement']}\n\n"
        f"النقاط المصدرية (المصدر الوحيد المسموح استعماله -- لا معلومة من "
        f"خارجها):\n{_points_block(member_points)}"
    )

    last_reason = ""
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=load_article_prompt(),
                messages=[{"role": "user", "content": user_content}],
                # لا تُضِف temperature -- نماذج هذا المشروع ترفضها بـ400.
            )
        except APIError as exc:
            return None, f"فشل نداء الكتابة: {exc}"

        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        ok, reason = _validate_article_text(text)
        if ok:
            return text, None
        last_reason = reason
        log.warning("محاولة %d/%d: مقال %r غير مطابق للبنية المطلوبة (%s)",
                    attempt, max_retries, topic["title"][:40], reason)

    return None, f"تعذّر الحصول على مقال مطابق للبنية بعد {max_retries} محاولة/محاولات: {last_reason}"


def _extract_headline(article_text: str) -> str:
    first_line = article_text.strip().splitlines()[0] if article_text.strip() else ""
    return first_line.lstrip("#").strip()


_SLUG_STRIP_RE = re.compile(r"[^\w]+", re.UNICODE)


def _slugify(title: str, max_len: int = 60) -> str:
    slug = _SLUG_STRIP_RE.sub("-", title).strip("-")
    return slug[:max_len] or "قضية"


def build_index(saved: list[dict]) -> str:
    lines = ["# فهرس مقالات يوتيوب", "",
             "| # | العنوان | الطبقة | الكتل | القنوات | الخلاف |",
             "|---|---|---|---|---|---|"]
    for item in saved:
        lines.append(
            f"| {item['number']} | [{item['headline']}]({item['filename']}) | "
            f"{item['layer']} | {', '.join(item['blocs'])} | "
            f"{', '.join(item['channels'])} | {item['agreement']} |")
    return "\n".join(lines) + "\n"


def save_articles(date_str: str, articles: list[dict]) -> list[dict]:
    """يكتب ملفات المقالات المرقَّمة + index.md. الترقيم متتابع بلا فجوات
    (أول مقال ناجح 01، الثاني 02...) بصرف النظر عن رتبة قضيته الأصلية --
    قضية تخطّاها الحظر أو فشلت كتابتها لا تترك فجوة رقمية في القائمة التي
    يقرؤها المالك أولًا."""
    out_dir = ARTICLES_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict] = []
    for i, item in enumerate(articles, start=1):
        topic = item["topic"]
        headline = _extract_headline(item["text"]) or topic["title"]
        slug = _slugify(headline)
        filename = f"{i:02d}-{slug}.md"
        (out_dir / filename).write_text(item["text"], encoding="utf-8")
        saved.append({
            "number": i, "filename": filename, "headline": headline,
            "layer": topic["layer"], "blocs": topic["blocs"],
            "channels": topic["channels"], "agreement": topic["agreement"],
        })
    (out_dir / "index.md").write_text(build_index(saved), encoding="utf-8")
    return saved


def run(cfg: Config | None = None, date_str: str | None = None,
        client: Anthropic | None = None, now: datetime | None = None) -> dict:
    cfg = cfg or load_config()
    now = now or datetime.now(timezone.utc)
    date_str = date_str or now.strftime("%Y-%m-%d")

    topics_result = youtube_cluster.load_topics(date_str)
    topics = topics_result.get("topics", [])
    points = youtube_cluster.load_points(date_str)
    count = cfg.path("youtube.article.count", 10)

    to_draft: list[dict] = []
    skipped: list[dict] = []
    guard_calls = 0
    blocked_count = 0
    draft_failures = 0

    for topic in topics[:count]:
        member_points = [points[pid] for pid in topic["point_ids"] if 0 <= pid < len(points)]
        if not member_points:
            skipped.append({"title": topic["title"], "layer": topic["layer"],
                            "reason": "لا نقاط صالحة لهذه القضية (نقاط/قضايا من تشغيلات مختلفة؟)"})
            continue

        if topic["layer"] == "c":
            guard_calls += 1
            blocked, reason, guard_error = check_forbidden(topic, member_points, cfg, client)
            if guard_error:
                log.warning("فشل حارس المحظورات لـ%r: %s", topic["title"], guard_error)
            if blocked:
                blocked_count += 1
                skipped.append({"title": topic["title"], "layer": topic["layer"],
                                "reason": f"محظورة (طبقة ج، مصدر واحد): {reason}"})
                continue

        text, error = draft_article(topic, member_points, cfg, client)
        if error:
            draft_failures += 1
            skipped.append({"title": topic["title"], "layer": topic["layer"], "reason": error})
            log.warning("فشلت كتابة مقال لـ%r: %s", topic["title"], error)
            continue

        to_draft.append({"topic": topic, "text": text})

    saved = save_articles(date_str, to_draft)

    return {
        "run_date": date_str,
        "stats": {
            "topics_considered": min(len(topics), count),
            "articles_written": len(saved),
            "skipped": len(skipped),
            "guard_calls": guard_calls,
            "blocked_forbidden": blocked_count,
            "draft_failures": draft_failures,
        },
        "skipped": skipped,
        "articles": saved,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    result = run()
    stats = result["stats"]
    out_dir = ARTICLES_DIR / result["run_date"]
    print(f"مجلد المقالات: {out_dir}")
    print(f"قضايا فُحصت: {stats['topics_considered']} · مقالات كُتبت: {stats['articles_written']} "
          f"· تخطّي: {stats['skipped']}")
    print(f"نداءات حارس المحظورات: {stats['guard_calls']} · محظورة: {stats['blocked_forbidden']} "
          f"· فشل كتابة: {stats['draft_failures']}")
    if result["skipped"]:
        for entry in result["skipped"]:
            print(f"  - {entry['title']} ({entry['layer']}): {entry['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
