"""مساعدات ومحاكاة مشتركة بين ملفات اختبار الأنبوب الأربعة (tests/test_collect.py، tests/test_review.py، tests/test_article.py، tests/test_youtube.py) بعد تقسيم tests/test_pipeline.py بحسب المجال (Issue #883): فاكات الشبكة/الصور/Claude API (install_fakes)، دالة check() وقائمتا PASSED/FAILED، وضبط بيئة الاختبار (TRENDNEWS_DRAFTS_DIR/STATE_DIR) قبل استيراد أي وحدة من src — يجب أن يبقى هذا الضبط أول ما يُنفَّذ من أي ملف اختبار في الحزمة، لذا يجب أن يكون استيراد tests.helpers هو أول سطر استيراد في كل ملف يستعمله."""
from __future__ import annotations

import atexit
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

from src import collect, evidence, extract, facebook, headlines, imagesearch, imaging, open_review, proxy_config, review, sources, store, trends, writer  # noqa: E402
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


def tick_marker(body: str, marker: str) -> str:
    """يعلّم أول مربع `- [ ]` في السطر الذي يحوي `marker` — يحاكي نقر
    المراجع على مربع بعينه بلا افتراض شكل السطر بالكامل (Issue #319:
    مربعا preselect.py لا يتشاركان سطرًا مع عنوان المرشح كما في السابق)."""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if marker in line:
            lines[i] = line.replace("- [ ]", "- [x]", 1)
            break
    return "\n".join(lines)


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
    def fake_headlines_for_post(post_title, post_body, cfg, client=None):
        return [f"هل {post_title}؟", f"{post_title} — تقرير أول", f"{post_title} — تقرير ثانٍ"], None

    headlines.headlines_for_post = fake_headlines_for_post  # type: ignore
