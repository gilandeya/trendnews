"""مساعدات ومحاكاة مشتركة بين ملفات اختبار الأنبوب الأربعة (tests/test_collect.py، tests/test_review.py، tests/test_article.py، tests/test_youtube.py) بعد تقسيم tests/test_pipeline.py بحسب المجال (Issue #883): فاكات الشبكة/الصور/Claude API (install_fakes)، دالة check() وقائمتا PASSED/FAILED، وضبط بيئة الاختبار (TRENDNEWS_DRAFTS_DIR/STATE_DIR) قبل استيراد أي وحدة من src — يجب أن يبقى هذا الضبط أول ما يُنفَّذ من أي ملف اختبار في الحزمة، لذا يجب أن يكون استيراد tests.helpers هو أول سطر استيراد في كل ملف يستعمله."""
from __future__ import annotations

import atexit
import functools
import inspect
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# مجلد مؤقت يعزل الاختبارات عن drafts/ و state/ الحقيقيين في المستودع —
# بلا هذا كان test_collect_end_to_end يمحو مسودات وسجلّ تكرار حقيقيين في
# كل تشغيل (اضطرت جولات سابقة لاستعادتها يدويًا بـ git checkout بعدها).
# يجب ضبط المتغيرين قبل أي استيراد من src لأن الوحدات تقرأ DRAFTS_DIR/
# STATE_DIR عند التحميل لا عند الاستدعاء.
_TMP_DATA_DIR = Path(tempfile.mkdtemp(prefix="trendnews_test_"))
os.environ["TRENDNEWS_DRAFTS_DIR"] = str(_TMP_DATA_DIR / "drafts")
os.environ["TRENDNEWS_STATE_DIR"] = str(_TMP_DATA_DIR / "state")
atexit.register(shutil.rmtree, _TMP_DATA_DIR, ignore_errors=True)

from src import collect, evidence, extract, facebook, headlines, imagesearch, imaging, names, names_learn, open_review, proxy_config, review, sources, store, trends, writer  # noqa: E402
from src import youtube_article, youtube_cluster, youtube_collect, youtube_extract  # noqa: E402
from src import youtube_publish  # noqa: E402
from src.config import (  # noqa: E402
    DRAFTS_DIR, STATE_DIR, YOUTUBE_ARTICLES_DIR, YOUTUBE_POINTS_DIR, load_config,
)
from src.rank import cluster, rank, similarity, tokens  # noqa: E402
from src.sources import Article  # noqa: E402
from tools import measure_channels, test_actions_block  # noqa: E402

# نسخة imaging.download_image الحقيقية، مُلتقَطة قبل أن يستبدلها install_fakes()
# بلا شرط — منطق رفض الروابط المشبوهة (looks_bad) لا يحتاج شبكة، ويستحق
# اختبارًا على الدالة الفعلية لا الفاكة العامة (test_image_report)
_REAL_DOWNLOAD_IMAGE = imaging.download_image

PASSED, FAILED = [], []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    mark = "✅" if condition else "❌"
    print(f"{mark} {name}" + (f"  → {detail}" if detail and not condition else ""))


# علامات مربعات قضية ترشيح الأخبار القديمة ← خيار الانتقال الموحَّد المقابل
# (Issue #1190): اختبارات كثيرة سابقة تعلّم «now:/review:/sel-card:» بالاسم؛
# على قضية بالشكل الجديد (لا مربعات قديمة فيها) يُترجَم الطلب إلى علامة go:
# المقابلة فتعلّم الاختبارات النقر نفسه بلا إعادة كتابة كل موضع.
_LEGACY_SELECTION_BOX = {"now": "publish", "review": "go2", "sel-card": "go3"}
_LEGACY_SELECTION_RE = re.compile(r"(now|review|sel-card):([0-9a-f]+)")


def tick_marker(body: str, marker: str) -> str:
    """يعلّم أول مربع `- [ ]` في السطر الذي يحوي `marker` — يحاكي نقر
    المراجع على مربع بعينه بلا افتراض شكل السطر بالكامل (Issue #319:
    مربعا preselect.py لا يتشاركان سطرًا مع عنوان المرشح كما في السابق)."""
    legacy = _LEGACY_SELECTION_RE.search(marker)
    if legacy and f"<!-- {legacy.group(1)}:{legacy.group(2)} -->" not in body:
        translated = f"go:{_LEGACY_SELECTION_BOX[legacy.group(1)]}:{legacy.group(2)}"
        if translated in body:
            marker = translated
    topic = re.search(r"topic:([0-9a-f]+)", marker)
    if topic and f"go:go2:{topic.group(1)}" in body:
        # قضية ترشيح تحليل بالشكل الجديد: «معلَّم» = go2 (الكتابة ثم المرحلة 2)
        marker = f"go:go2:{topic.group(1)}"
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if marker in line:
            lines[i] = line.replace("- [ ]", "- [x]", 1)
            break
    return "\n".join(lines)


def legacy_selection_body(cands: list[dict]) -> str:
    """قضية ترشيح أخبار بالشكل القديم (قبل Issue #1190): نص ثابت منسوخ من
    الباني القديم حرفيًا، لا يمرّ ببناة src — كي يثبت اختبار أن قضية فُتحت
    قبل التحديث تُقرأ كما كانت. ثلاثة مربعات لكل مرشح."""
    parts = [
        "### 🗳️ مرشحون بانتظار الاختيار", "",
        "**بلا صياغة ولا صورة بعد** — هذه العناوين الخام كما وردت من المصادر.", "",
        "🚀 نشر مباشر · 📝 مراجعة أولية (نص وعناوين وتعديل) · 🎴 بطاقة مباشرة.", "",
        "---", "",
    ]
    for idx, c in enumerate(cands, start=1):
        parts += [
            f"**{idx}. {c['title']}**  <!-- cand:{c['id']} -->", "",
            f"  🏷️ {c.get('bucket', '')} · مؤشر الترند `{c['score']:.1f}`", "",
            f"  ↳ [الخبر الأصلي]({c['link']})", "",
            f"  - [ ] 🚀 انشر فورًا (صياغة ثم نشر مباشر بلا عرض)  <!-- now:{c['id']} -->",
            f"  - [ ] 📝 صغ واعرض عليّ قبل النشر  <!-- review:{c['id']} -->",
            f"  - [ ] 🎴 صُغ واعرض البطاقة (بلا مراجعة أولية)  <!-- sel-card:{c['id']} -->",
            "", "---", "",
        ]
    parts.append("<sub>وسم `approved` = تنفيذ ما عُلِّم عليه لكل مرشح</sub>")
    return "\n".join(parts)


def legacy_youtube_selection_body(date_str: str, topics: list[dict]) -> str:
    """قضية ترشيح تحليل بالشكل القديم (قبل Issue #1190): مربع واحد على سطر
    عنوان كل موضوع، نص ثابت منسوخ من الباني القديم."""
    parts = [
        f"<!-- selection-date:{date_str} -->", "### 🗳️ اختيار مواضيع التحليل", "",
        "علّم ما تريد كتابته. ما لا تعلّمه لا يُكتب ولا يُقترح ثانيةً.", "",
        "---", "",
    ]
    for idx, t in enumerate(topics, start=1):
        parts += [f"- [ ] **{idx}. {t['title']}**  <!-- topic:{t['id']} -->", "",
                  f"  {t.get('event', '')}", "", "---", ""]
    parts.append("<sub>وسم `approved` = كتابة المعلَّم فقط</sub>")
    return "\n".join(parts)


_REAL_LAST_PUBLISH_AT = store.last_publish_at


def reset_last_publish() -> None:
    """تجعل ``store.last_publish_at`` يتجاهل أي مسودة published موجودة فعلًا
    في drafts/ حتى لحظة هذا الاستدعاء (Issue #1015: لا ملف حالة يُصفَّر —
    المصدر الوحيد الآن ``published_at`` في drafts/ نفسها). استبدال مؤقت
    بعتبة زمنية (``floor``) لا استبدال بقيمة ثابتة: مسودة نُشرت قبل هذا
    الاستدعاء (تسرّبت من سيناريو سابق *داخل نفس دالة الاختبار* لا تُمحى
    بين سيناريو وآخر عمدًا، أو من دالة اختبار أخرى تتشارك DRAFTS_DIR
    المؤقتة معها) لا تُحسَب؛ لكن نشرًا فعليًا جديدًا يقع *بعد* هذا الاستدعاء
    (ضمن الدفعة الحالية نفسها، عبر publish_one الحقيقية) يظل يُحسَب بقيمته
    الحقيقية، فتستمر بوابة الفاصل تعمل بين عناصر دفعة واحدة كما يُفترض بها
    — استبدال بقيمة ثابتة (``None`` دومًا) كان يعطّل هذا التتابع بالكامل.
    يُستدعى في بداية أي اختبار ينشر عبر publish_one الحقيقية أو عبر
    cmd_burst/cmd_revival/cmd_due/cmd_now الحقيقية ولا يفحص توقيت البوابة
    نفسه بدقة. اختبارات البوابة الدقيقة تستدعي ``restore_last_publish()``
    بدل هذه، ثم تتحكّم بآخر منشور عبر مسودة published حقيقية بتاريخ
    ``published_at`` محدد (``stub_last_publish``)."""
    floor = datetime.now(timezone.utc)

    def _patched() -> datetime | None:
        real = _REAL_LAST_PUBLISH_AT()
        if real is None or real <= floor:
            return None
        return real

    store.last_publish_at = _patched


def restore_last_publish() -> None:
    """يستعيد ``store.last_publish_at`` الحقيقية (الحساب من drafts/) بعد
    اختبار استدعى ``reset_last_publish()`` — تستدعيها اختبارات البوابة قبل
    أن تتحكّم بآخر منشور فعلي عبر ``stub_last_publish``."""
    store.last_publish_at = _REAL_LAST_PUBLISH_AT


def auto_restore_last_publish(fn):
    """مُزيِّن لأي دالة اختبار تستدعي ``reset_last_publish()`` — يضمن
    استعادة ``store.last_publish_at`` الحقيقية بعد انتهاء الدالة دومًا،
    نجاحًا أو استثناءً (Issue #1044). قبل هذا كانت ``reset_last_publish()``
    تستبدل ``store.last_publish_at`` ولا تُعاد أبدًا ما لم يستدعِ الاختبار
    نفسه ``restore_last_publish()`` صراحةً (3 اختبارات فقط من أصل 56 كانت
    تفعل ذلك، وبعضها كان يستدعيها دفاعيًا في *بداية* الاختبار تحسّبًا
    لتسرّب استبدال اختبار سابق — أثر جانبي لنفس الخلل) — فيبقى الاستبدال
    ساريًا على كل اختبار لاحق في نفس التشغيلة. استدعاء ``restore_last_publish()``
    غير مكلف وآمن حتى لو لم يكن ``reset_last_publish()`` استُدعيت أصلًا."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        finally:
            restore_last_publish()
    return wrapper


_LAST_PUBLISH_STUB_ID = "_last_publish_stub"


def stub_last_publish(when: datetime) -> Path:
    """يثبّت آخر نشر فعلي في drafts/ عند ``when`` بمسودة published واحدة
    تُعاد كتابتها بمعرّف ثابت (لا نُسخ جديدة تتراكم) — Issue #1015:
    ``store.last_publish_at`` الحقيقية تحسب أحدث ``published_at`` بين كل
    مسودات ``status == "published"``، فلو تراكمت أكثر من مسودة مثبَّتة
    لفاز الأحدث تاريخًا بينها، لا التي استدعيت أخيرًا. تفترض أن
    ``restore_last_publish()`` استُدعيت أولًا (أو لم يُستدعَ
    ``reset_last_publish()`` إطلاقًا في هذا الاختبار)."""
    draft = {
        "id": _LAST_PUBLISH_STUB_ID,
        "status": "published",
        "published_at": when.isoformat(),
    }
    return store.save_draft(draft)


# ──────────────────────────── تجهيزات ────────────────────────────

RSS_FIXTURE = """<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel><title>Fixture</title>
<item>
  <title>Oil prices surge after OPEC+ announces surprise output cut - Reuters</title>
  <link>https://news.google.com/rss/articles/CBMiK2h0dHBz</link>
  <description>&lt;p&gt;Crude jumped more than 6% on Tuesday.&lt;/p&gt;</description>
  <pubDate>{recent}</pubDate>
</item>
<item>
  <title>OPEC+ surprise production cut sends oil prices higher - BBC</title>
  <link>https://www.bbc.com/news/opec-cut</link>
  <description>Markets reacted sharply.</description>
  <pubDate>{recent}</pubDate>
  <media:thumbnail url="https://ichef.bbci.co.uk/news/240/cpsprodpb/oil.jpg" width="240"/>
</item>
<item>
  <title>Ancient stale story nobody wants</title>
  <link>https://example.com/old</link>
  <description>Old news.</description>
  <pubDate>{old}</pubDate>
</item>
<item>
  <title>Daily horoscope for Tuesday - Astro Times</title>
  <link>https://example.com/horoscope</link>
  <description>Your horoscope today.</description>
  <pubDate>{recent}</pubDate>
</item>
<item>
  <title>Magnitude 6.1 earthquake strikes western Japan - NHK</title>
  <link>https://example.com/japan-quake</link>
  <description>&lt;img src="https://example.com/quake-tokyo.jpg"/&gt; No tsunami warning issued.</description>
  <pubDate>{recent}</pubDate>
</item>
</channel></rss>
"""


def rfc822(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


class FakeResponse:
    def __init__(self, content: bytes, status: int = 200, url: str = "https://example.com"):
        self.content = content
        self.text = content.decode("utf-8", "ignore")
        self.status_code = status
        self.url = url


def install_fakes() -> None:
    now = datetime.now(timezone.utc)
    body = RSS_FIXTURE.format(
        recent=rfc822(now - timedelta(hours=2)),
        old=rfc822(now - timedelta(days=4)),
    ).encode("utf-8")

    sources.requests.get = lambda url, **kw: FakeResponse(body, url=url)  # type: ignore
    sources.requests.head = lambda url, **kw: FakeResponse(b"", url=url)  # type: ignore
    sources.image_from_page = lambda url, timeout=12: "https://example.com/og.jpg"  # type: ignore

    # صورة "ناشر" اصطناعية بدل التحميل الحقيقي
    fake = Image.new("RGB", (1400, 800), (34, 52, 92))
    ImageDraw.Draw(fake).ellipse([500, 100, 900, 500], fill=(226, 194, 150))
    fake.save("/tmp/_fixture_photo.jpg")
    imaging.download_image = (  # type: ignore
        lambda url, timeout=20, failures=None: Image.open("/tmp/_fixture_photo.jpg").convert("RGB")
    )

    canned = {
        "oil": {
            "urgent": True, "category": "اقتصاد", "angle": "خبر",
            "image_headline": "أوبك بلس تفاجئ الأسواق بخفض الإنتاج وأسعار النفط ترتفع 6%",
            "post_title": "أوبك بلس تخفض الإنتاج والنفط يرتفع 6%",
            "post_body": "أعلنت مجموعة أوبك بلس خفضًا مفاجئًا في إنتاج النفط، ما دفع "
                         "أسعار الخام إلى الارتفاع بأكثر من ستة في المئة. يهم القرار "
                         "الأسواق العربية المرتبطة بأسعار الطاقة.",
            "hashtags": ["أوبك", "النفط", "الاقتصاد_العالمي", "أسعار_الطاقة"],
        },
        "quake": {
            "urgent": False, "category": "عالم", "angle": "خبر",
            "image_headline": "زلزال بقوة 6.1 درجة يضرب غرب اليابان دون تحذير من تسونامي",
            "post_title": "زلزال بقوة 6.1 درجة يضرب غرب اليابان",
            "post_body": "ضرب زلزال بقوة 6.1 درجة غرب اليابان، ولم تصدر السلطات تحذيرًا "
                         "من أمواج تسونامي. لم ترد أنباء عن إصابات حتى الآن.",
            "hashtags": ["اليابان", "زلزال", "أخبار_عاجلة", "آسيا"],
        },
    }

    def fake_write(article, cfg, retries=3, previous_post=None, source_docs=None):
        key = "oil" if "oil" in article.link or "opec" in article.link else "quake"
        out = dict(canned[key])
        out["angle"] = "تفسير" if (article.age_hours or 0) > 8 else "خبر"
        # التحليل يظهر فقط حين تُمرَّر نصوص فعلية
        out["analysis"] = ("تربط رويترز القرار بضغوط السوق، وتضيف الغارديان "
                           "أنه قد ينعكس على الأسعار محليًا.") if source_docs else ""
        if previous_post:
            out["post_title"] = "تحديث: " + out["post_title"]
        return out

    writer.write_arabic = fake_write  # type: ignore
    collect.write_arabic = fake_write  # type: ignore

    # عناوين مقترحة (Issue #756) -- fake عام واحد على src.headlines نفسها،
    # يكفي كل المسارات الأربعة (collect_finalize/collect/verify_draft/article)
    # لأنها كلها تنادي headlines_mod.headlines_for_post عبر ``from . import
    # headlines as headlines_mod`` (استيراد وحدة لا نسخة اسم) -- تعديل
    # الدالة على الوحدة المشتركة يظهر فورًا لكل من يستدعيها بلا تصحيح كل
    # وحدة على حدة. اختبارات فشل النداء المخصَّصة تُصحّح هذا الفاكة محليًا
    # (حفظ/استعادة) داخل دالتها فقط.
    def fake_headlines_for_post(post_title, post_body, cfg, client=None, first_question=True, system=None):
        if not first_question:   # Issue #1233: تصحيح/تفنيد «هام» — الأول خبري
            return [f"{post_title} — تقرير أول", f"{post_title} — تقرير ثانٍ", f"{post_title} — تقرير ثالث"], None
        return [f"هل {post_title}؟", f"{post_title} — تقرير أول", f"{post_title} — تقرير ثانٍ"], None

    headlines.headlines_for_post = fake_headlines_for_post  # type: ignore

    # تدقيق أسماء الأشخاص (Issue #1252): نداء الكشف الحقيقي يحتاج Anthropic، فيُستبدل هنا بكاشف لا
    # يرى شيئًا لكل الاختبارات؛ اختبارات التدقيق نفسها تضع كاشفها عبر NamesAuditRig
    from src import names_audit
    names_audit._detect = lambda texts, arabic, cfg: []  # type: ignore
    # المحرر الأخير (Issue #1326): افتراضيًا تقرير بلا ملاحظات، بلا شبكة
    from src import editor, youtube_editor
    editor._create = lambda client, **kw: editor_response([])  # type: ignore
    youtube_editor._create = lambda client, **kw: editor_response([])  # type: ignore


def card_plan(cfg, headline: str, badge_texts: list[str]) -> dict:
    """هندسة البطاقة نفسها التي يرسم بها src/imaging.py (Issue #1161):
    imaging.plan_card_layout على سطح رسم وهمي، فلا نسخة ثانية للصيغة."""
    W = int(cfg.path("image.width", 1080))
    H = int(cfg.path("image.height", 1350))
    return imaging.plan_card_layout(
        ImageDraw.Draw(Image.new("RGB", (W, H))), headline, badge_texts, cfg)


def badge_probe_xy(cfg, texts: list[str], index: int, headline: str) -> tuple[int, int]:
    """بكسل داخل الشارة رقم index من مجموعة الشارات (Issue #1161): المجموعة
    محاذاة لليمين فوق أول سطر من العنوان، فموضعها العمودي يتبع العنوان —
    لذا يلزم `headline` المرسوم على البطاقة. `texts` بترتيب اليمين ← اليسار
    (عاجل، التصنيف، شارة الأصل)، و`index` 0 = الأقصى يمينًا."""
    box = card_plan(cfg, headline, texts)["badges"][index]
    return box["x0"] + 10, (box["y0"] + box["y1"]) // 2


# ───────────── عدّة مسار «هام» (Issue #1194): بحث وجلب ونموذج مزيَّفة ─────────────


class ImportantRig:
    """يثبّت مزيَّفات الأنبوب كاملًا لـ src/important.py (نداء التفكيك
    extract_points، evidence.search/gather_evidence، Brave web، article._client)
    ويسجّل كل نداء نموذج فعلي في ``calls`` — مصدر الحقيقة الوحيد لاختبار
    عدّاد النداءات المحفوظ في الملف (لا يُحسب العدّاد من الجهتين بالمنطق نفسه).

    points: نقاط يعيدها نداء التفكيك المزيَّف. الشكل القديم (text/kind/
    entities…) يُحوَّل إلى شكل رد الأداة (الآراء تُهمَل كما يفعل النموذج
    الحقيقي، وعبارة البحث هي نص النقطة)؛ ومن فيه مفتاح ``claim`` يُمرَّر
    كما هو بشكل رد الأداة (انظر important.EXTRACT_SCHEMA).

    brave_results / brave_key: كلمة مميِّزة ← نتائج Brave web الخام؛ بلا
    brave_key لا مفتاح في البيئة (الافتراضي). searches تسجّل (استعلام،
    أيام، بلا_قيد) لكل بحث Google؛ unrestricted_only: كلمات لا تُعاد وثائقها
    إلا من بحث بلا قيد زمني (يحاكي حدثًا قديمًا).
    docs_by_marker: كلمة مميِّزة ← وثائق تُعاد حين يحويها نص الاستعلام (كل
    نقطة تحمل كلمة فريدة في كياناتها فتُبنى الاستعلامات بها أولًا).
    classify(point_text, doc_names) ← مدخلات أداة classify_sources.
    """

    def __init__(self, points, docs_by_marker, classify, brave_results=None,
                 brave_key=None, unrestricted_only=(), native=None, strict_known=False,
                 main_story=None, gap=None, gap_main_story_en=""):
        self.points = points
        # أسئلة البحث المكمِّل التي يعيدها نداء report_gap_questions المزيَّف (#1293)
        self.gap = gap or []
        self.gap_main_story_en = gap_main_story_en   # ترجمة الخبر الرئيسي التي يعيدها النداء (#1304)
        self.gap_requests: list[str] = []
        # الخبر الرئيسي الذي يعيده التفكيك المزيَّف (#1291)؛ None = الحقل غائب كما قبل
        self.main_story = main_story
        # Issue #1229: شرط «مؤيِّد معروف» لـconfirmed. افتراضه مُعطَّل في المزيَّف (كل ناشر معروف) كي
        # تبقى الاختبارات القائمة — ناشروها «صحيفة الشرق»/«موقع الغرب» الوهميون — على دلالتها الأصلية؛
        # وحالات #1229 تمرّر strict_known=True فتجري على الحارس الحقيقي بلا أي تزييف
        self.strict_known = strict_known
        self.docs_by_marker = docs_by_marker
        self.classify = classify
        self.brave_results = brave_results or {}
        self.brave_key = brave_key
        self.unrestricted_only = set(unrestricted_only)
        # رمز لغة ← عبارات يعيدها نداء native_queries الثاني (Issue #1203)؛ الافتراضي لا شيء
        self.native = native or {}
        self.native_requests: list[str] = []
        self.max_chars_seen: list = []
        self.html_sink_seen: list = []
        self.html_pages: list[str] = []
        # الجلب الإضافي لـHTML الخام (extract.fetch_html): لا شبكة أبدًا في الاختبار؛ late_html صفحات
        # لم يرها الجلب الأول فتُخدم هنا، وfetched_html يسجّل كل رابط طُلب (#1210)
        self.late_html: dict[str, str] = {}
        self.fetched_html: list[str] = []
        # روابط كل ما أُرسل فعلًا إلى الجلب (#1207): ما استُبعد قبل الجلب لا يظهر هنا
        self.gathered: list[str] = []
        self.systems: list[str] = []
        self.calls: list[str] = []
        self.queries: list[str] = []
        self.searches: list[tuple] = []
        self.doc_registry: dict = {}
        self.brave_calls: list[str] = []
        # نص الوثائق كما وصل نداء التصنيف فعلًا (Issue #1200: اختبار اختيار الفقرات)
        self.last_content = ""
        self.contents: list[str] = []
        self._saved: dict = {}

    def __enter__(self):
        from src import article, extract, important
        rig = self
        # ذاكرة نتائج البحث (#1212) تعيش بين التشغيلات؛ كل rig يبدأ بذاكرة فارغة كي لا تتسرّب
        # نتائج اختبار إلى آخر. اختبار الذاكرة نفسه يُجري تشغيلتين داخل rig واحد.
        important._search_cache_file().unlink(missing_ok=True)
        self._real_known = getattr(important, "_is_known_source", None)
        if self._real_known is not None and not self.strict_known:
            important._is_known_source = lambda *a, **k: True

        class _Ranked(list):
            raw_count = 0

        class _Art:
            def __init__(self, doc):
                self.doc = doc
                self.publisher = doc["name"]
                self.source_name = doc["name"]
                self.image_candidates = list(doc.get("images", []))
                # عنوان ومقتطف بحث ورابط اختيارية (#1207): الترشيح قبل الجلب يقرأ العنوان
                # والمقتطف؛ وثيقة بلا حقليهما لا يُحكم عليها فتمرّ كما كانت
                self.title = doc.get("title", "")
                self.summary = doc.get("summary", "")
                self.link = doc.get("link", "")
                rig.doc_registry[(self.publisher, self.title, self.link)] = doc

        def fake_search(query, cfg, days, unrestricted=False, require_relevance=True):
            rig.queries.append(query)
            rig.searches.append((query, days, unrestricted))
            out = _Ranked()
            for marker, docs in rig.docs_by_marker.items():
                if marker in query and (unrestricted or marker not in rig.unrestricted_only):
                    out.extend(_Art(d) for d in docs)
            out.raw_count = len(out)
            return out

        def fake_gather(articles, cfg, claim_text="", loose_relevance=False, max_chars=None,
                        html_sink=None):
            rig.max_chars_seen.append(max_chars)
            rig.html_sink_seen.append(html_sink is not None)
            rig.gathered += [getattr(a, "link", "") or (a.doc.get("link", "") if hasattr(a, "doc") else "")
                             for a in articles]
            # مقالات Brave حقيقية الشكل (Article) بلا .doc: وثيقتها من حقولها
            # نتيجة أُعيد بناؤها من ذاكرة البحث (#1212) بلا .doc: وثيقتها من سجلّ المزيَّف نفسه
            docs = [a.doc if hasattr(a, "doc") else
                    rig.doc_registry.get((a.publisher, a.title, a.link)) or
                    {"name": a.publisher or a.source_name, "link": a.link,
                     "text": f"{a.title}. {a.summary}", "from_text": True}
                    for a in articles]
            out = []
            for d in docs:
                if "late_html" in d:
                    rig.late_html[d.get("link", "")] = d["late_html"]
                    d = {k: v for k, v in d.items() if k != "late_html"}
                # «html» حقل اختبار فقط: يحاكي HTML الخام الذي رآه الجلب نفسه (#1210)؛ يصل
                # المستقبِل عبر html_sink كما في extract.fetch_text الحقيقية ولا يبقى في الوثيقة
                if "html" in d:
                    rig.html_pages.append(d.get("link", ""))
                    if html_sink is not None:
                        html_sink(d.get("link", ""), d["html"])
                    d = {k: v for k, v in d.items() if k != "html"}
                out.append(d)
            return out, "full"

        class _Block:
            type = "tool_use"

            def __init__(self, input_):
                self.input = input_

        class _Resp:
            usage = None
            stop_reason = "tool_use"

            def __init__(self, input_):
                self.content = [_Block(input_)]

        class _Msgs:
            def create(self, **kw):
                rig.calls.append(kw["tool_choice"]["name"])
                content = kw["messages"][0]["content"]
                if kw["tool_choice"]["name"] == "extract_points":
                    return _Resp(rig._extract_input())
                if kw["tool_choice"]["name"] == "report_gap_questions":
                    rig.gap_requests.append(kw["messages"][0]["content"])
                    return _Resp({"questions": list(rig.gap), "main_story_en": rig.gap_main_story_en})
                if kw["tool_choice"]["name"] == "native_queries":
                    m = re.search(r"\(([a-z]{2})\)", kw["system"])
                    lang = m.group(1) if m else ""
                    rig.native_requests.append(lang)
                    return _Resp({"queries": list(rig.native.get(lang, []))})
                rig.systems.append(kw.get("system", ""))
                rig.last_content = content[0]["text"]
                rig.contents.append(content[0]["text"])
                names = re.findall(r"--- المصدر: (.*?) ---", content[0]["text"])
                point = content[1]["text"].split(":", 1)[1].strip()
                return _Resp(rig.classify(point, names))

        class _Client:
            messages = _Msgs()

        import os
        import requests as _requests

        class _Http:
            status_code = 200

            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

        real_get = _requests.get

        def fake_fetch_html(url, timeout=20):
            rig.fetched_html.append(url)
            return rig.late_html.get(url)

        def fake_get(url, **kw):
            if "search.brave.com/res/v1/web/search" not in url:
                return real_get(url, **kw)
            query = kw["params"]["q"]
            rig.brave_calls.append(query)
            results = [r for marker, rs in rig.brave_results.items()
                       if marker in query for r in rs]
            return _Http({"web": {"results": results}})

        self._saved = {
            "_client": article._client, "search": evidence.search,
            "gather": evidence.gather_evidence, "get": real_get,
            "env": os.environ.get("BRAVE_API_KEY"), "fetch_html": extract.fetch_html,
        }
        extract.fetch_html = fake_fetch_html
        article._client = lambda: _Client()
        evidence.search = fake_search
        evidence.gather_evidence = fake_gather
        _requests.get = fake_get
        os.environ.pop("BRAVE_API_KEY", None)
        if self.brave_key:
            os.environ["BRAVE_API_KEY"] = self.brave_key
        return self

    def _extract_input(self) -> dict:
        out = []
        for p in self.points:
            if "claim" in p:
                out.append(p)
            elif p.get("kind", "واقعة") in ("واقعة", "تصريح", "تقرير منقول"):
                out.append({
                    "claim": p["text"], "asserted": p.get("asserted", ""),
                    "entities": p.get("entities", []), "dates": p.get("dates", []),
                    "numbers": p.get("numbers", []),
                    "queries": p.get("queries") or [{"lang": "ar", "q": p["text"]}],
                    "factcheck_query": p.get("factcheck_query", ""),
                    "is_unnamed_event": bool(p.get("is_unnamed_event"))})
        extra = {"main_story": self.main_story} if self.main_story is not None else {}
        return {"topic": "موضوع اختبار", **extra, "points": out}

    def __exit__(self, *exc):
        import os
        import requests as _requests
        from src import article, extract, important
        important._search_cache_file().unlink(missing_ok=True)
        if self._real_known is not None:
            important._is_known_source = self._real_known
        article._client = self._saved["_client"]
        evidence.search = self._saved["search"]
        evidence.gather_evidence = self._saved["gather"]
        extract.fetch_html = self._saved["fetch_html"]
        _requests.get = self._saved["get"]
        if self._saved["env"] is None:
            os.environ.pop("BRAVE_API_KEY", None)
        else:
            os.environ["BRAVE_API_KEY"] = self._saved["env"]
        return False


def important_point(marker: str, text: str, **extra) -> dict:
    """نقطة واقعة بكلمة مميِّزة أولى في الكيانات (تُبنى بها الاستعلامات)."""
    return {"text": text, "kind": "واقعة", "entities": [marker], "is_unnamed_event": False,
            "is_reference": False, "speaker": "", "merged_excerpts": [],
            "split_from": "", "publisher": "", "query_latin": "", **extra}


def fresh_date(days: int = 3) -> str:
    """تاريخ نشر «حديث» محسوب وقت التشغيل (اليوم − days) لا ثابتًا، كي لا تنكسر الاختبارات بعد 14 يومًا (#1345)."""
    return (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()


def freshen_nearest(result: dict, days: int = 3) -> dict:
    """يعطي وثائق أعضاء كل عنصر nearest في نتيجة محمَّلة (من fixture حقيقي) تاريخ نشر حديثًا عند التحميل بلا لمس الملف:
    منشور «الأقرب» لا يُكتب من مصادر قديمة وحدها (#1345). تعيد النتيجة نفسها."""
    d = fresh_date(days)
    by_id = {p["id"]: p for p in result.get("points") or []}
    for item in result.get("article_items") or []:
        if item.get("kind") != "nearest":
            continue
        for pid in item.get("point_ids") or []:
            for doc in (by_id.get(pid) or {}).get("read_docs") or []:
                doc["published"] = d
    return result


def important_doc(name: str, text: str, **extra) -> dict:
    return {"name": name, "text": text, "link": f"https://{name.replace(' ', '-')}.example/a",
            "from_text": True, **extra}


def important_stance(source: str, stance: str, excerpt: str = "", **kw) -> dict:
    # same_event (Issue #1200): افتراضه True كي تبقى حالات g1–g9 والاختبارات القائمة
    # كما هي؛ الحالات الجديدة تمرّر same_event=False صراحةً
    # verdict_label (Issue #1207): حكم المدقّق كما يرد في صفحته. الافتراضي لنفي صريح «False»
    # كي تبقى حالات g1–g20 (مدقّق واحد ينفي) كما هي دون تعديل؛ الحالات الجديدة تمرّر
    # القيمة صراحةً (حتى الفارغة) فلا يُستعمل الافتراضي
    default_label = "False" if stance == "refutes" else ""
    return {"source": source, "stance": stance, "excerpt": excerpt,
            "same_event": kw.get("same_event", True),
            "detail": kw.get("detail", ""), "correct_form": kw.get("correct_form", ""),
            "as_of": kw.get("as_of", ""),
            # detail_kind (Issue #1214): غيابه يبقي السلوك القديم (يُعامَل رقمًا) كي تمرّ g1–g30
            **({"detail_kind": kw["detail_kind"]} if "detail_kind" in kw else {}),
            # superseded_by (Issue #1225): {fact, date} الحقيقة الأحدث التي تجاوزت ما في النقطة
            **({"superseded_by": kw["superseded_by"]} if "superseded_by" in kw else {}),
            "verdict_label": kw.get("verdict_label", default_label)}


def brave_result(url: str, title: str, description: str, name: str = "") -> dict:
    """نتيجة خام بشكل Brave web/search (web.results[])."""
    return {"url": url, "title": title, "description": description,
            "profile": {"name": name} if name else {}}


def claim_review_html(label: str = "Yanlış", claim_reviewed: str = "", shape: str = "single",
                      rating_key: str = "alternateName", date_published: str = "2026-08-14",
                      url: str = "https://teyit.org/analiz/video-turkiyenin-suriyeye-450-bin-asker-gonderdigini-mi-gosteriyor",
                      body: str = "") -> str:
    """HTML خام لصفحة مدقّق فيه JSON-LD من نوع ClaimReview بالبنية الحقيقية (Issue #1210):
    @context schema.org وreviewRating.alternateName (أو name عبر rating_key). shape:
    single (كتلة وحدها) · graph (داخل @graph مع كتل أخرى) · list (قائمة كتل) ·
    broken (JSON تالف) · none (بلا JSON-LD). نص الصفحة المرئي ``body`` لا يحمل الحكم —
    هذا ما يجعل المستخرَج منها عنوانًا فقط."""
    import json as _json
    review = {"@type": "ClaimReview", "url": url, "datePublished": date_published,
              "claimReviewed": claim_reviewed,
              "author": {"@type": "Organization", "name": "Teyit"},
              "reviewRating": {"@type": "Rating", "ratingValue": "1", "bestRating": "5",
                               "worstRating": "1", rating_key: label}}
    org = {"@type": "Organization", "name": "Teyit", "url": "https://teyit.org"}
    if shape == "graph":
        block = {"@context": "https://schema.org", "@graph": [org, review]}
    elif shape == "list":
        block = [{"@context": "https://schema.org", **org},
                 {"@context": "https://schema.org", **review}]
    else:
        block = {"@context": "https://schema.org", **review}
    if shape == "broken":
        script = ('<script type="application/ld+json">'
                  '{"@context": "https://schema.org", "@type": "ClaimReview", </script>')
    elif shape == "none":
        script = ""
    else:
        script = f'<script type="application/ld+json">{_json.dumps(block, ensure_ascii=False)}</script>'
    return (f"<html><head><title>teyit</title>{script}</head>"
            f"<body><h1>{body}</h1></body></html>")


# ───────────── كتابة مسار «هام» (Issue #1221، المهمة 3 من 3) ─────────────

IMPORTANT_FIXTURES = ROOT / "tests" / "fixtures" / "important"
_IMG = [{"url": "https://img.example/a.jpg", "publisher": "الشرق", "link": "https://s.example/1"}]


def important_fixture_point(issue: int, verdict: str, index: int = 0, **over) -> dict:
    """نقطة حقيقية من ملف حكم ثابت (1209/1201) بحالة «معروضة»، مع صورة ناشر
    مصطنعة كي لا يمسّ بناء البطاقة الشبكة. index: ترتيبها بين نقاط الحكم نفسه."""
    import copy
    data = json.loads((IMPORTANT_FIXTURES / f"{issue}.json").read_text(encoding="utf-8"))
    point = copy.deepcopy([p for p in data["points"] if p["verdict"] == verdict][index])
    point.update(status="offered", dropped_reason=None, image_candidates=copy.deepcopy(_IMG), **over)
    return point


def important_synthetic_point(verdict: str, **over) -> dict:
    """نقطة مصطنعة لحكمَي false وnot_found (لا نقطة حقيقية لهما في الملفات الثابتة)."""
    from src import important
    if verdict == "false":
        text = "أعلنت ناسا أن الشمس ستشرق من الغرب غدًا بسبب انقلاب مغناطيسي"
        point = {"verdict": "false", "icon": "❌", "evidence": [], "correction": None,
                 "nearest": None, "primary_source": False,
                 "refuted_by": [
                     {"publisher": "Fatabyyano", "link": "https://fatabyyano.net/x",
                      "excerpt": "لم تصدر ناسا أي بيان بهذا المعنى والصور المتداولة مفبركة",
                      "verdict_label": "كاذب", "fact_checker": True},
                     {"publisher": "موقع النفي", "link": "https://m.example/y",
                      "excerpt": "لا يوجد أي انقلاب مغناطيسي وشيك بحسب الوكالة",
                      "verdict_label": "", "fact_checker": False}]}
    else:
        text = "أعلنت وكالة الفضاء عن اكتشاف حياة على القمر أمس"
        point = {"verdict": "not_found", "icon": "🔍", "evidence": [], "correction": None,
                 "refuted_by": None, "primary_source": False,
                 "nearest": {"title": "رصد جليد مائي في فوهة قطبية على القمر",
                             "description": "أظهرت بيانات مسبار مدار القمر وجود جليد مائي دائم الظل في فوهة قطبية.",
                             "shared_entity": "القمر",
                             "sources": [{"publisher": "مصدر أ", "link": "https://a.example/1",
                                          "excerpt": "رصد المسبار جليدًا مائيًا في فوهة قطبية دائمة الظل"},
                                         {"publisher": "مصدر ب", "link": "https://b.example/2",
                                          "excerpt": "تؤكد البيانات وجود جليد مائي في قطب القمر"}]}}
    point.update(id=important.point_id(text), text=text, claim=text, framing="direct",
                 circulating_context="", asserted="", note="", status="offered",
                 dropped_reason=None, image_candidates=[dict(c) for c in _IMG])
    point.update(over)
    return point


def important_good_data(point: dict) -> dict:
    """رد كاتب مزيَّف يستوفي توجيهات الحكم كلها (فحوص g36–g39 تمرّره)."""
    verdict = point["verdict"]
    base = {"category": "عالم", "hashtags": ["هام"], "image_query_en": "space telescope galaxy"}
    if verdict == "inaccurate":
        c = point["correction"]
        return {**base, "post_title": f"الصحيح: {c['correct']}",
                "image_headline": f"الصحيح: {c['correct']}",
                "post_body": (f"تشير أحدث البيانات إلى أن العدد هو {c['correct']} وفق المصدرين. "
                              "أما الرقم المتداول فخطأ شائع لا يطابق التقديرات الرسمية.")}
    if verdict == "false":
        r = point["refuted_by"][0]
        return {**base, "post_title": "لا صحة لشروق الشمس من الغرب والمدقّقون يحسمون",
                "image_headline": "لا صحة لشروق الشمس من الغرب",
                "post_body": (f"لا أساس لهذا الكلام عند الوكالة، فالشمس تشرق من الشرق كما هو معلوم. "
                              f"وصنّفت {r['publisher']} الأمر بحكم «{r['verdict_label']}». "
                              "ويبقى ما جرى تداوله ادّعاءً متداولًا لا سند له.")}
    if verdict == "not_found":
        n = point["nearest"]
        return {**base, "post_title": n["title"], "image_headline": n["title"],
                "post_body": f"{n['description']} وتؤكد المصادر المستقلة هذه النتائج بالبيانات المنشورة."}
    return {**base, "post_title": "مجرة جديدة تكسر الأرقام القياسية في الكون",
            "image_headline": "أبعد مجرة معروفة",
            "post_body": "اكتشف علماء الفلك أبعد مجرة معروفة باستخدام تلسكوب جيمس ويب الفضائي."}


def important_marked_body(result: dict, marks: dict, cfg=None) -> str:
    """جسم قضية الترشيح **القديمة** (علامات go: لكل نقطة، قبل #1293) مع تعليم خيار الانتقال لكل نقطة
    ({id: go2|go3|publish}) — محاكاة نقر المراجع. بعد #1293 يبني build_selection_body ثلاثة منشورات
    لأي نتيجة فيها articles، فهذا المساعد يستعمل build_points_body ليبقى مسار الكتابة لكل نقطة
    (القضايا المفتوحة قبل التحديث) مغطًّى بالاختبارات نفسها؛ منشورات الخبر الرئيسي في
    important_items_marked_body أدناه."""
    from src import important_issue
    body = important_issue.build_points_body(result, cfg or load_config())
    for pid, action in marks.items():
        body = tick_marker(body, f"go:{action}:{pid}")
    return body


def important_b2_result(issue: int = 88000, main_story: str = "تطوّرات الخبر الرئيسي في الاختبار") -> dict:
    """نتيجة حكم بخطة منشورات {verified: 2، nearest: 2، refuted: 1} (#1293): نقطتان مؤكَّدتان من الملفين
    الثابتين، ونقطتا not_found إحداهما بلا nearest وساقطة، ونقطة false. محفوظة في state/important."""
    from src import important
    conf1 = important_fixture_point(1209, "confirmed", 0)
    conf2 = important_fixture_point(1201, "confirmed", 0)
    nf1 = important_synthetic_point("not_found")
    text2 = "قيل إن قوات دخلت مدينة المخا صباح اليوم"
    nf2 = important_synthetic_point("not_found", id=important.point_id(text2), text=text2, claim=text2,
                                    nearest=None, status="dropped", dropped_reason=important.NO_TRACE_REASON)
    fl = important_synthetic_point("false")
    points = [conf1, conf2, nf1, nf2, fl]
    result = {"issue": issue, "body_hash": "x", "rules_version": 4, "selection_issue": None,
              "created_at": "2026-10-08T00:00:00+00:00", "topic": "t", "error": None,
              "main_story": main_story, "off_topic": [], "articles": important.plan_articles(points),
              "points": points}
    important.ensure_article_items(result)
    important.save(result)
    return result


def important_items_marked_body(result: dict, marks: dict, cfg=None) -> str:
    """جسم قضية الترشيح الجديد (ثلاثة منشورات) مع تعليم خيار الانتقال لكل عنصر ({معرّف_العنصر: go2|go3|publish})."""
    from src import important_issue
    body = important_issue.build_selection_body(result, cfg or load_config())
    for iid, action in marks.items():
        body = tick_marker(body, f"go:{action}:{iid}")
    return body


class ImportantWriteRig:
    """مزيَّفات كتابة مسار «هام» ومراحله: عميل Anthropic يلتقط نداء الكاتب فعلًا (النموذج
    والنظام والبرومبت) فيمرّ article._call_draft_model الحقيقي، وGitHub (قضايا/تعليقات)،
    ونشر cmd_burst/cmd_now/cmd_schedule، وتجسّس على بناء البطاقة (الناشرون وشارة الأصل).
    respond(prompt, system) ← قاموس حقول أداة write_article."""

    def __init__(self, respond, gap_sources=None):
        self.respond = respond
        # مقتطفات البحث المكمِّل المزيَّفة (#1293): بها يُستبدل important_gap.gather كله؛ None = البحث الحقيقي
        # (يلزم حينها ImportantRig متداخل). gap_calls تسجّل (النوع، أعضاء المنشور) لكل منشور.
        self.gap_sources = gap_sources
        self.gap_calls: list[tuple] = []
        self.calls: list[dict] = []
        self.created: list[dict] = []
        self.comments: list[tuple] = []
        self.other: list[tuple] = []
        self.builds: list[dict] = []
        self.published: list[tuple] = []
        self.next = 7000
        self._saved: list[tuple] = []

    def _swap(self, mod, name, new):
        self._saved.append((mod, name, getattr(mod, name)))
        setattr(mod, name, new)

    def __enter__(self):
        import types
        from src import article, cards, publish
        rig = self

        class _Messages:
            def create(self, **kw):
                system = kw["system"][0]["text"] if isinstance(kw.get("system"), list) else kw.get("system")
                prompt = kw["messages"][0]["content"]
                rig.calls.append({"model": kw.get("model"), "system": system, "prompt": prompt})
                data = rig.respond(prompt, system)
                return types.SimpleNamespace(
                    stop_reason="end_turn",
                    content=[types.SimpleNamespace(type="tool_use", input=data)],
                    usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))

        self._swap(article, "_client", lambda: types.SimpleNamespace(messages=_Messages()))
        if self.gap_sources is not None:
            from src import important_gap

            def fake_gather(result, item, members, cfg):
                rig.gap_calls.append((item["kind"], [m["id"] for m in members]))
                return [dict(g) for g in rig.gap_sources]

            self._swap(important_gap, "gather", fake_gather)

        def fake_create(title, body, labels=None):
            rig.next += 1
            rig.created.append({"number": rig.next, "title": title, "body": body, "labels": labels})
            return {"number": rig.next, "html_url": f"https://example/issues/{rig.next}"}

        self._swap(review, "create_issue", fake_create)
        self._swap(review, "comment", lambda n, t: rig.comments.append((n, t)))
        self._swap(review, "ensure_labels", lambda: None)
        self._swap(review, "remove_label", lambda *a: rig.other.append(("remove_label", a)))
        self._swap(review, "close_issue", lambda *a: rig.other.append(("close_issue", a)))
        for name in ("cmd_burst", "cmd_now", "cmd_schedule"):
            self._swap(publish, name,
                       lambda ids, cfg, issue=None, _n=name, **kw: rig.published.append((_n, list(ids), issue)) or 0)

        real_build = cards._default_build_post_image

        def spy_build(**kw):
            rig.builds.append({k: kw.get(k) for k in ("headline", "publisher", "origin", "category", "image_urls")})
            return real_build(**kw)

        self._swap(cards, "_default_build_post_image", spy_build)
        os.environ.setdefault("GITHUB_REPOSITORY", "owner/repo")
        return self

    def __exit__(self, *exc):
        for mod, name, old in reversed(self._saved):
            setattr(mod, name, old)
        return False


# ───────── عدّة تدقيق أسماء الأشخاص (Issue #1252): كشف وبحث مزيَّفان ─────────


class NamesAuditRig:
    """تعزل src/names_audit عن الشبكة: `_detect` (نداء Haiku) يعيد قائمة مُعدَّة، و`_brave_http`
    (طلب Brave وحده) يردّ بنتائج حسب نص الاستعلام — فمنطق العدّاد والسقف والذاكرة والاستقلال
    يجري على الكود الحقيقي. تمحو ملفات الحالة عند الدخول فلا يتسرّب شيء بين الاختبارات.
    `web`: {جزء من الاستعلام: [{url, title, description}, …]}؛ ما لا يطابق يردّ [].
    `detections`: ما يعيده الكشف (قائمة قواميس، أو دالة (texts, arabic) ← قائمة)."""

    def __init__(self, detections=None, web=None, key: str | None = "test-key"):
        self.detections = detections if detections is not None else []
        self.web = web or {}
        self.key = key
        self.detect_calls: list = []
        self.http_calls: list[str] = []

    def __enter__(self):
        from src import names_audit
        self.mod = names_audit
        self._saved = {"_detect": names_audit._detect, "_brave_http": names_audit._brave_http,
                       "env": os.environ.get("BRAVE_API_KEY")}
        for f in (names_audit.VERIFIED_FILE, names_audit.CACHE_FILE):
            f.unlink(missing_ok=True)
        imagesearch.BRAVE_USAGE_FILE.unlink(missing_ok=True)

        def detect(texts, arabic, cfg):
            self.detect_calls.append((list(texts), arabic))
            d = self.detections
            return [dict(x) for x in (d(texts, arabic) if callable(d) else d)]

        def http(query, key, count):
            self.http_calls.append(query)
            for part, results in self.web.items():
                if part in query:
                    return results
            return []

        names_audit._detect = detect
        names_audit._brave_http = http
        if self.key is None:
            os.environ.pop("BRAVE_API_KEY", None)
        else:
            os.environ["BRAVE_API_KEY"] = self.key
        return self

    def __exit__(self, *exc):
        self.mod._detect = self._saved["_detect"]
        self.mod._brave_http = self._saved["_brave_http"]
        if self._saved["env"] is None:
            os.environ.pop("BRAVE_API_KEY", None)
        else:
            os.environ["BRAVE_API_KEY"] = self._saved["env"]
        return False


def names_audit_draft(text_name: str = "فريدة المسلمي") -> dict:
    """مسودة أخبار بشكل 4e1ba01e960a الحقيقي (الاسم الخاطئ في التحليل والتعليق) — حقول النص الخمسة."""
    analysis = (f"يرى {text_name}، الباحث في معهد تشاتام هاوس، أن الحوثيين حققوا هدفهم العسكري "
                "المتمثل في عزل تعز عن عدن.")
    title = "الحوثيون يسيطرون على منطقة الصافية ويقطعون شريان تعز الحيوي مع عدن"
    body = "سيطر مقاتلو جماعة الحوثي على منطقة الصافية في محافظة تعز وقطعوا الطريق الرئيسي."
    return {
        "id": "4e1ba01e960a", "status": "pending", "origin": "news", "score": 24.8,
        "bucket": "serious", "state_media": False,
        "source": {"title": "Houthis cut vital supply road to Yemen’s Taiz",
                   "link": "https://www.freemalaysiatoday.com/x", "publisher": "Free Malaysia Today",
                   "publishers": ["Free Malaysia Today", "Malay Mail"]},
        "arabic": {"post_title": title, "post_body": body, "analysis": analysis,
                   "image_headline": "الحوثيون يقطعون طريق تعز-عدن", "category": "عالم",
                   "urgent": False, "hashtags": ["اليمن"]},
        "caption": f"{title}\n\n{body}\n\nخلف الخبر\n{analysis}",
        "headlines": [f"{text_name} يشرح خطة الحوثيين"], "headline_selected": 0,
    }


NAMES_AUDIT_SOURCE = [
    "Analysts say the Houthis achieved their military aim. Farea al-Muslimi, a research fellow at "
    "Chatham House, said cutting the road isolates Taiz from Aden even without taking the city."]


def names_audit_hit(url: str, name: str) -> dict:
    return {"url": url, "title": f"{name} — تحليل", "description": f"قال {name} إن الحوثيين قطعوا الطريق"}


def names_audit_doubt(arabic: str = "فريدة المسلمي", latin: str = "Farea al-Muslimi",
                      candidates=("فارع المسلمي", "فريعة المسلمي")) -> dict:
    return {"arabic": arabic, "latin": latin, "gender": "male", "verdict": "doubtful",
            "reason": "تعارض جنس: اسم مؤنث مع «الباحث»", "candidates": list(candidates),
            "context": "تشاتام هاوس"}


# ── المحرر الأخير (Issue #1326) ──
class _NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def editor_response(notes, searches: int = 0, report: bool = True):
    """رد مزيَّف لنداء المحرر: server_tool_use ثم report_review (أو بدونها)."""
    content = []
    if searches:
        content.append(_NS(type="server_tool_use", name="web_search", input={"query": "q"}))
    if report:
        content.append(_NS(type="tool_use", name="report_review", input={"notes": notes}))
    else:
        content.append(_NS(type="text", text="لا تقرير"))
    return _NS(content=content, stop_reason="end_turn",
               usage=_NS(input_tokens=1, output_tokens=1,
                         server_tool_use=_NS(web_search_requests=searches)))
