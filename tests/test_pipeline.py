"""اختبار الأنبوب كاملًا بمحاكاة الشبكة و Claude API (بلا أي طلب خارجي).

    python -m tests.test_pipeline
"""
from __future__ import annotations

import atexit
import inspect
import json
import logging
import os
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

from src import collect, evidence, extract, imagesearch, imaging, proxy_config, review, sources, store, trends, writer  # noqa: E402
from src import youtube_article, youtube_cluster, youtube_collect, youtube_extract  # noqa: E402
from src import youtube_publish  # noqa: E402
from src.config import DRAFTS_DIR, STATE_DIR, load_config  # noqa: E402
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


# ──────────────────────────── الاختبارات ────────────────────────────


def test_tokens_and_similarity() -> None:
    a = tokens("Oil prices surge after OPEC+ announces surprise output cut")
    b = tokens("OPEC+ surprise production cut sends oil prices higher")
    c = tokens("Magnitude 6.1 earthquake strikes western Japan")
    check("الكلمات الوظيفية مستبعدة", "the" not in a and "after" not in a)
    check("خبران عن نفس الحدث متشابهان", similarity(a, b) >= 0.5, f"{similarity(a, b):.2f}")
    check("خبران مختلفان غير متشابهين", similarity(a, c) < 0.2, f"{similarity(a, c):.2f}")


def test_fetch_and_filter() -> None:
    cfg = load_config(ROOT / "config.yaml")
    arts = sources.fetch_source({"name": "Fixture", "url": "https://x/rss",
                                 "region": "global", "weight": 1.0}, 18)
    titles = [a.title for a in arts]
    check("استُبعد الخبر القديم", not any("Ancient stale" in t for t in titles))
    check("جُلبت الأخبار الحديثة", len(arts) == 4, f"{len(arts)}")
    check("فُصل اسم الناشر عن العنوان",
          any(a.publisher == "Reuters" and "Reuters" not in a.title for a in arts))
    check("رُقّي مصغّر BBC إلى نسخة كبيرة",
          any(any("/1024/" in u for u in a.image_candidates) for a in arts),
          str([a.image_candidates for a in arts]))
    check("احتُفظ بالرابط الأصلي كبديل",
          any(any("/240/" in u for u in a.image_candidates) for a in arts))
    check("استُخرجت صورة من وسم img",
          any("quake-tokyo" in u for a in arts for u in a.image_candidates))
    check("خبر جوجل بلا صور", not [a for a in arts
          if "news.google.com" in a.link and a.image_candidates])

    ranked = rank(arts, cfg["selection"])
    ranked_titles = [a.title for a in ranked]
    check("حُجب خبر الأبراج (blocklist)",
          not any("horoscope" in t.lower() for t in ranked_titles))
    check("دُمج خبر أوبك من مصدرين",
          any(len(a.cluster_sources) >= 2 for a in ranked),
          str([a.cluster_sources for a in ranked]))
    opec = [a for a in ranked if "opec" in a.title.lower() or "oil" in a.title.lower()]
    check("استعار الخبر صورة من نسخة المجموعة الأخرى",
          bool(opec) and bool(opec[0].image_candidates),
          str(opec[0].image_candidates) if opec else "لا مجموعة")
    check("الترتيب تنازلي حسب المؤشر",
          all(ranked[i].score >= ranked[i + 1].score for i in range(len(ranked) - 1)))


def test_image_filtering() -> None:
    from src.sources import is_generic_image, upgrade_image_url

    up = upgrade_image_url("https://ichef.bbci.co.uk/news/240/cpsprodpb/a.jpg")
    check("ترقية BBC تنتج نسخة أكبر", any("/1024/" in u for u in up), str(up))
    check("الرابط الأصلي يبقى بديلًا", any("/240/" in u for u in up))
    g = upgrade_image_url("https://media.guim.co.uk/abc/140.jpg")
    check("ترقية الغارديان تعمل", any("/1000.jpg" in u for u in g), str(g))
    check("رابط غير معروف يمر كما هو",
          upgrade_image_url("https://x.com/a.jpg") == ["https://x.com/a.jpg"])

    bad = ["https://x.com/logo.png", "https://news.google.com/og.jpg",
           "https://a.com/social-default.jpg", None]
    good = ["https://bbc.co.uk/news/2026/01/quake-tokyo.jpg"]
    check("رفض الشعارات والصور العامة", all(is_generic_image(u) for u in bad))
    check("قبول صور الأخبار الحقيقية", not any(is_generic_image(u) for u in good))


def test_image_report() -> None:
    """تشخيص الصورة في تقرير src.article (مراجعة بشرية بعد أول نشر، البند
    1): «الصورة غائبة ولا سبب في التقرير» — download_image يسجّل الآن سبب
    رفض كل مرشَّح حين يُمرَّر failures، وbuild_post_image يملأ report بعدد
    المرشحين المجرَّبين وسبب فشل كل منهم وحصيلة احتياط find_images."""
    fl: list = []
    result = _REAL_DOWNLOAD_IMAGE("https://x.com/logo.png", failures=fl)
    check("download_image: رابط مشبوه يُرفض ويُسجَّل سببه في failures — بلا شبكة "
          "(looks_bad يرفض قبل أي طلب HTTP)",
          result is None and fl and fl[0]["reason"] == "رابط مشبوه", fl)

    installed_download = imaging.download_image  # نسخة install_fakes — تُعاد كما هي بعد الاختبار

    def fake_download(url, timeout=20, failures=None):
        if url == "https://good.example/fallback.jpg":
            return Image.new("RGB", (800, 600), (10, 10, 10))
        if failures is not None:
            failures.append({"url": url, "reason": "فشل اختباري"})
        return None

    cfg = load_config()
    out_path = _TMP_DATA_DIR / "image_report_test.jpg"

    imaging.download_image = fake_download  # type: ignore
    shot: dict = {}
    imaging.build_post_image(
        headline="عنوان اختبار الصورة", category="عالم", urgent=False,
        image_urls=["https://bad1.example/a.jpg", "https://bad2.example/b.jpg"],
        publisher=["مصدر أول"], bucket="serious",
        fallback_provider=lambda: ["https://good.example/fallback.jpg"],
        cfg=cfg, out_path=out_path, report=shot,
    )
    imaging.download_image = installed_download  # type: ignore

    check("build_post_image: عدد المرشحين المجرَّبين مسجَّل في report",
          shot.get("candidates_tried") == 2, shot)
    check("build_post_image: سبب فشل كل مرشَّح مسجَّل",
          len(shot.get("candidate_failures") or []) == 2 and
          all(f["reason"] == "فشل اختباري" for f in shot["candidate_failures"]), shot)
    check("build_post_image: احتياط find_images استُدعي بعد فشل كل المرشحين",
          shot.get("fallback_tried") is True, shot)
    check("build_post_image: عدد مرشحي الاحتياط مسجَّل",
          shot.get("fallback_candidates") == 1, shot)
    check("build_post_image: نجاح الاحتياط يُسجَّل illustrative=True",
          shot.get("illustrative") is True, shot)

    shot2: dict = {}
    imaging.build_post_image(
        headline="عنوان اختبار آخر", category="عالم", urgent=False,
        image_urls=["https://ok.example/real.jpg"], publisher=["مصدر"],
        bucket="serious", fallback_provider=lambda: [],
        cfg=cfg, out_path=out_path, report=shot2,
    )
    check("build_post_image: صورة مصدر ناجحة ← بلا فشليات مسجَّلة وبلا احتياط",
          shot2.get("used_original") is True and not shot2.get("candidate_failures") and
          shot2.get("fallback_tried") is False, shot2)
    check("build_post_image: chosen_url يحمل الرابط الذي نجح فعليًا (إصلاح عطل عزو "
          "— image_ranked[0] لم تكن دومًا الفائزة)",
          shot2.get("chosen_url") == "https://ok.example/real.jpg", shot2)

    from src import article
    check("article._image_report_lines: صورة ناجحة تُعرض بسطر إيجابي",
          any("مصدر مسند" in ln for ln in article._image_report_lines(shot2)), shot2)
    lines = article._image_report_lines(shot)
    check("article._image_report_lines: صورة تعبيرية بديلة تُذكر صراحة مع عدد المرشحين",
          any("تعبيرية" in ln for ln in lines), lines)
    check("article._image_report_lines: سبب فشل كل مرشَّح يظهر كسطر منفصل",
          sum("فشل اختباري" in ln for ln in lines) == 2, lines)
    check("article._image_report_lines: قاموس فارغ (لم تُبنَ صورة أصلًا) لا يُنتج شيئًا",
          article._image_report_lines({}) == [])

    # ── image_pool_source: تمييز صريح بين مصدر مسند واحتياط استبعاد إعادة
    # النشر (طلب المراجعة، مراجعة بشرية بعد أول نشر، البند 1) ──
    lines_grounded = article._image_report_lines(
        {**shot2, "image_pool_source": "grounded"})
    check("_image_report_lines: pool=grounded يبقي الصياغة الأصلية «مصدر مسند»",
          any("مصدر مسند مباشرة" in ln for ln in lines_grounded), lines_grounded)
    lines_reprint = article._image_report_lines(
        {**shot2, "image_pool_source": "excluded_reprint"})
    check("_image_report_lines: pool=excluded_reprint يوسم الصورة صراحة كغير دليل إسناد",
          any("استُبعد من عدّ الاستقلالية" in ln and "ليس دليل إسناد" in ln
              for ln in lines_reprint), lines_reprint)

    # ── استعلام find_images الفعلي يُطبَع في التقرير عند استدعاء الاحتياط ──
    lines_terms = article._image_report_lines(
        {**shot, "fallback_query_terms": ["زوكربيرغ", "القلعة"]})
    check("_image_report_lines: عبارات استعلام الصورة الاحتياطية تظهر صراحة",
          any("زوكربيرغ" in ln and "القلعة" in ln for ln in lines_terms), lines_terms)
    lines_terms_empty = article._image_report_lines(
        {**shot, "fallback_query_terms": []})
    check("_image_report_lines: عبارات فارغة (لا كيانات) تُذكر صراحة لا سطر ملتبس",
          any("لا كيانات مستخرجة" in ln for ln in lines_terms_empty), lines_terms_empty)

    # ── imagesearch.find_images(terms=...) يتجاوز keywords() (عنوان عربي
    # لا يُنتج شيئًا عبرها أصلًا) — العطل البنيوي المشخَّص (البند 1) ──
    from src import imagesearch
    check("imagesearch.keywords: عنوان عربي محض يعيد قائمة فارغة دومًا (السبب "
          "البنيوي لرجوع find_images بصفر — أحرف لاتينية كبيرة فقط)",
          imagesearch.keywords("استحوذ زوكربيرغ على القلعة القوطية") == [])
    # PROVIDERS تربط أسماء الدوال بمراجعها وقت التعريف — تصحيح imagesearch.
    # search_wikimedia وحدها لا يُغيّر ما تستدعيه find_images فعليًا؛ يجب
    # تصحيح القاموس نفسه
    real_providers = dict(imagesearch.PROVIDERS)
    captured_terms: list = []
    imagesearch.PROVIDERS["wikimedia"] = lambda q, limit=4, timeout=15: (
        captured_terms.append(q) or [])
    imagesearch.PROVIDERS["openverse"] = lambda q, limit=4, timeout=15: []
    imagesearch.find_images("عنوان عربي لن يُستخرج منه شيء", cfg,
                            terms=["زوكربيرغ", "القلعة"])
    imagesearch.PROVIDERS.clear()
    imagesearch.PROVIDERS.update(real_providers)
    check("imagesearch.find_images(terms=...): يتجاوز keywords() ويبحث بالعبارات "
          "المُمرَّرة مباشرة — لا قائمة فارغة رغم عنوان عربي",
          captured_terms == ["زوكربيرغ", "القلعة"], captured_terms)

    # ── article._image_search_terms: عبارات من entities الوقائع المسندة لا
    # من central_text (نص عربي، فلغة imagesearch.keywords() لن تلتقطه) ──
    grounded_terms = [
        {"text": "استحوذ زوكربيرغ على القلعة", "entities": ["زوكربيرغ", "القلعة القوطية"]},
        {"text": "القلعة في أيرلندا", "entities": ["القلعة القوطية", "أيرلندا"]},
    ]
    terms = article._image_search_terms(grounded_terms)
    check("_image_search_terms: يجمع entities من كل الوقائع المسندة، بلا تكرار",
          terms == ["زوكربيرغ", "القلعة القوطية", "أيرلندا"], terms)
    check("_image_search_terms: يُقصّ عند limit",
          article._image_search_terms(grounded_terms, limit=2) ==
          ["زوكربيرغ", "القلعة القوطية"])
    check("_image_search_terms: وقائع بلا entities تعيد قائمة فارغة بلا انهيار",
          article._image_search_terms([{"text": "و"}]) == [])

    # ── _reprint_fallback_images/_pool_image_candidates: وثيقة استُبعدت
    # كإعادة نشر تبقى مرشَّحًا صالحًا للصورة (طلب المراجعة، البند 1) —
    # الاستبعاد يخصّ عدّ السند لا الصور ──
    excluded = [{"name": "الجزيرة نت", "link": "https://aj/1", "shared_words": 82}]
    _now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ranked_pool = [
        Article(title="ت", link="https://aj/1", summary="", source_name="الجزيرة نت",
               region="global", weight=1.0, published=_now,
               publisher="الجزيرة نت", image_candidates=["https://aj/img1.jpg"]),
        Article(title="ت2", link="https://other/2", summary="", source_name="أخرى",
               region="global", weight=1.0, published=_now,
               publisher="أخرى", image_candidates=["https://other/img2.jpg"]),
    ]
    pool = article._reprint_fallback_images(excluded, ranked_pool)
    check("_reprint_fallback_images: يلتقط صور الناشر المستبعَد فقط من ranked "
          "(غير المُصفّاة بالاستبعاد أصلًا) لا كل المرشحين",
          pool == [{"name": "الجزيرة نت", "link": "https://aj/1",
                    "image_candidates": ["https://aj/img1.jpg"]}], pool)
    check("_reprint_fallback_images: بلا excluded_reprints ← قائمة فارغة",
          article._reprint_fallback_images([], ranked_pool) == [])
    pool_imgs = article._pool_image_candidates(pool)
    check("_pool_image_candidates: يحوّل المجمّع إلى (رابط، اسم، رابط المصدر)",
          pool_imgs == [("https://aj/img1.jpg", "الجزيرة نت", "https://aj/1")], pool_imgs)
    pool_dup = pool + [{"name": "ناشر آخر", "link": "https://x/1",
                        "image_candidates": ["https://aj/img1.jpg"]}]
    check("_pool_image_candidates: يزيل تكرار نفس الرابط عبر مصدرين",
          len(article._pool_image_candidates(pool_dup)) == 1)


def test_google_news_link_decode() -> None:
    """فكّ رابط Google News الوسيط بلا شبكة (Issue #132 تعليق لاحق — العطل
    القاتل: extract.py لم يقرأ نص أي مقال قط لأن Google لم يعد يرسل تحويل
    HTTP حقيقي لهذه الروابط). اختبار تكامل ذاتي: نبني رابطًا وهميًا بنفس
    ترميز البروتوبفر الموثَّق (بادئة/طول/رابط/لاحقة) ونتحقق أن الفكّ
    يستعيده — لا اختبار على شكل Google الحقيقي (بلا شبكة لا سبيل للتحقق
    منه هنا)، لكنه يثبت صحة حساب الإزاحات والبادئة/اللاحقة داخليًا."""
    import base64

    from src import sources

    sample_url = "https://example-publisher.test/real-article-slug"
    payload = (sources._GNEWS_ID_PREFIX + chr(len(sample_url)) + sample_url
              + sources._GNEWS_ID_SUFFIX)
    b64 = base64.urlsafe_b64encode(payload.encode("latin1")).decode("ascii").rstrip("=")
    link = f"https://news.google.com/rss/articles/{b64}"

    decoded = sources._decode_google_news_article_id(link)
    check("الفكّ المباشر يستعيد الرابط الأصلي من رابط مُركَّب بنفس الترميز",
          decoded == sample_url, str(decoded))

    check("رابط بلا /articles/ في المسار لا يُفكّ",
          sources._decode_google_news_article_id(
              "https://news.google.com/rss/search?q=x") is None)
    check("base64 غير صالح لا ينهار، يعيد None بهدوء",
          sources._decode_google_news_article_id(
              "https://news.google.com/rss/articles/%%%not-base64%%%") is None)

    # عيّنة اختبارية حقيقية من ثابت RSS_FIXTURE في هذا الملف — base64 مقتطع
    # عمدًا يفكّ فعليًا إلى "https" الخمسة أحرف فقط (بادئة صحيحة، حمولة
    # مبتورة). كانت startswith("http") وحدها تقبل هذا خطأً كرابط حقيقي؛
    # الفحص الصارم (يشترط "://" ونطاقًا فيه نقطة) يرفضه بصمت الآن.
    check("حمولة مقتطعة تفكّ إلى نص يشبه رابطًا لكنه ليس رابطًا لا تُقبَل",
          sources._decode_google_news_article_id(
              "https://news.google.com/rss/articles/CBMiK2h0dHBz") is None)

    # الرابط المُركَّب أعلاه يعمل عبر resolve_final_url كاملة بلا حاجة لأي
    # استدعاء شبكة — الفكّ المباشر يسبق أي HEAD/GET
    resolved = sources.resolve_final_url(link)
    check("resolve_final_url تستعمل الفكّ المباشر أولًا بلا شبكة",
          resolved == sample_url, resolved)


def test_trends() -> None:
    from src.trends import trend_match
    from src.rank import tokens as tk

    sigs = [tk("OPEC oil"), tk("Taylor Swift tour"), tk("earthquake Japan")]

    strong = trend_match(tk("Oil prices surge after OPEC+ announces output cut"), sigs)
    check("عنوان يطابق موضوعًا رائجًا", strong >= 0.9, f"{strong:.2f}")

    none_ = trend_match(tk("Local council approves new parking rules"), sigs)
    check("عنوان غير رائج لا يُطابق", none_ < 0.5, f"{none_:.2f}")

    check("قائمة رائجة فارغة تعطي صفرًا", trend_match(tk("anything here"), []) == 0.0)

    # الترند يرفع الترتيب فعلًا
    from src.rank import rank as _rank
    now = datetime.now(timezone.utc)
    arts = [
        Article(title="Boring council meeting minutes released", link="https://a/1",
                summary="", source_name="A", region="uk", weight=1.0, published=now),
        Article(title="OPEC oil summit ends with surprise decision", link="https://b/2",
                summary="", source_name="B", region="eu", weight=1.0, published=now),
    ]
    sel = {"title_similarity": 0.62, "max_age_hours": 18, "region_diversity": False}
    plain = _rank([a for a in arts], sel)
    boosted = _rank([Article(**{**a.__dict__}) for a in arts], sel, sigs, 4.0)
    check("الترند يقدّم الخبر الرائج",
          boosted[0].title.startswith("OPEC"), boosted[0].title[:40])
    check("الترند يرفع الدرجة",
          max(a.score for a in boosted) > max(a.score for a in plain),
          f"{max(a.score for a in boosted):.1f} مقابل {max(a.score for a in plain):.1f}")


def test_state_media() -> None:
    now = datetime.now(timezone.utc)
    official = Article(title="Ministry announces new policy plan", link="https://s/1",
                       summary="", source_name="TASS", region="russia", weight=0.7,
                       published=now, state_media=True)
    independent = Article(title="Ministry announces new policy plan", link="https://i/2",
                          summary="", source_name="BBC", region="uk", weight=1.2,
                          published=now)
    sel = {"title_similarity": 0.5, "max_age_hours": 18, "region_diversity": False}

    only_state = rank([official], sel)
    check("خبر رسمي منفرد يُوسم", only_state and only_state[0].state_media)

    mixed = rank([official, independent], sel)
    check("خبر بمصدر مستقل لا يُوسم", mixed and not mixed[0].state_media)
    check("الرسمي المنفرد أقل درجة",
          only_state[0].score < mixed[0].score,
          f"{only_state[0].score:.1f} مقابل {mixed[0].score:.1f}")

    body = review.build_issue_body([{
        "id": "abc123", "score": 9.0, "trend_score": 0.0, "state_media": True,
        "image": "drafts/x/a.jpg", "caption": "نص",
        "source": {"link": "https://s/1", "publishers": ["TASS"]},
        "arabic": {"post_title": "عنوان", "urgent": False, "category": "سياسة"},
    }], "u/r", "main")
    check("تحذير الإعلام الرسمي يظهر للمراجع", "إعلام رسمي" in body)


def test_velocity() -> None:
    from src.velocity import observe

    entries: list[dict] = []
    title = "Major earthquake strikes coastal region"

    first = observe(title, 2, entries)
    check("أول مشاهدة تُسجَّل", first["is_new"] and len(entries) == 1)
    check("خبر جديد بمصدرين يأخذ سرعة متواضعة",
          0 < first["velocity"] < 0.5, f"{first['velocity']:.2f}")

    # حاكِ مرور ساعة ونمو من 2 إلى 8 مصادر
    entries[0]["last_seen"] = (datetime.now(timezone.utc)
                               - timedelta(hours=1)).isoformat()
    entries[0]["first_seen"] = entries[0]["last_seen"]
    fast = observe(title, 8, entries)
    check("النمو السريع يعطي سرعة عالية", fast["velocity"] >= 0.9,
          f"{fast['velocity']:.2f}")
    check("لا يُنشئ سجلًا مكررًا", len(entries) == 1)

    # خبر قديم توقّف نموه
    old = datetime.now(timezone.utc) - timedelta(hours=30)
    entries[0]["first_seen"] = old.isoformat()
    entries[0]["last_seen"] = (datetime.now(timezone.utc)
                               - timedelta(hours=3)).isoformat()
    entries[0]["sources"] = 8
    dead = observe(title, 8, entries)
    check("الخبر الميت يُوسم stale", dead["stale"], str(dead))
    check("الخبر الميت سرعته صفر", dead["velocity"] == 0.0)

    # خبر مختلف ينشئ سجلًا جديدًا
    observe("Completely unrelated tech product launch", 3, entries)
    check("خبر مختلف يُسجَّل منفصلًا", len(entries) == 2)


def test_velocity_in_ranking() -> None:
    now = datetime.now(timezone.utc)
    hot = [Article(title="Breaking crisis unfolds in capital city", link=f"https://h/{i}",
                   summary="", source_name=f"S{i}", region=f"r{i}", weight=1.0,
                   published=now) for i in range(6)]
    cold = [Article(title="Slow policy review continues quietly", link=f"https://c/{i}",
                    summary="", source_name=f"T{i}", region=f"q{i}", weight=1.0,
                    published=now) for i in range(6)]

    # الخبر البارد متتبَّع منذ يومين بلا نمو؛ الساخن جديد
    stale_entry = {
        "tokens": sorted(tokens("Slow policy review continues quietly")),
        "sources": 6, "peak": 6,
        "first_seen": (now - timedelta(hours=40)).isoformat(),
        "last_seen": (now - timedelta(hours=2)).isoformat(),
    }
    entries = [stale_entry]
    sel = {"title_similarity": 0.62, "max_age_hours": 30, "region_diversity": False}
    out = rank(hot + cold, sel, velocity_entries=entries, velocity_weight=5.0)

    check("الخبر المنتشر يتقدّم على الراكد",
          out[0].title.startswith("Breaking"), out[0].title[:40])
    stale = [a for a in out if a.title.startswith("Slow")]
    check("الخبر الراكد يُوسم stale", stale and stale[0].is_stale)
    check("الفارق في الدرجة معتبر", out[0].score - stale[0].score > 3,
          f"{out[0].score:.1f} مقابل {stale[0].score:.1f}")


def test_followups() -> None:
    history: list[dict] = []
    store.remember(history, "Death toll rises after factory fire",
                   "https://a/1", "ارتفاع حصيلة حريق المصنع")

    prev = store.find_previous(history, "Factory fire death toll climbs to 30",
                               "https://b/2", 0.55)
    check("يُعثر على المنشور السابق عن الحدث", prev is not None)
    check("عنوان المنشور السابق محفوظ",
          prev and prev.get("posted_title") == "ارتفاع حصيلة حريق المصنع")
    check("خبر مختلف لا يطابق",
          store.find_previous(history, "New space telescope launched",
                              "https://c/3", 0.55) is None)


def test_find_previous_prefers_posted_over_offered() -> None:
    """Issue #331: عرض preselect معلَّق (posted_title فارغ) قد يُسجَّل قبل
    نشر فعلي لاحق لنفس الحدث — أحدهما بنفس الرابط تمامًا. find_previous
    يجب أن يفضّل مدخلة النشر الفعلي على مجرد العرض بصرف النظر عن ترتيب
    الإضافة، وإلا حجب عرض قديم رؤية النشر الحقيقي عن أي بحث لاحق."""
    history: list[dict] = []
    # عُرض كمرشح preselect أولًا (بلا صياغة بعد)
    store.remember(history, "Storm knocks out power across region",
                   "https://p/storm", None)
    # ثم اعتُمد وصِيغ فعليًا — نفس الرابط، مدخلة جديدة بعنوان منشور
    store.remember(history, "Storm knocks out power across region",
                   "https://p/storm", "عاصفة تقطع الكهرباء عن المنطقة")

    prev = store.find_previous(history, "Storm knocks out power across region",
                               "https://p/storm", 0.55)
    check("المطابقة الأحدث (المنشورة) هي التي تُعاد",
          prev and prev.get("posted_title") == "عاصفة تقطع الكهرباء عن المنطقة",
          str(prev))

    # حتى إن أُضيف عرض آخر معلَّق بعد النشر (متابعة عُرضت ولم تُختر بعد)،
    # يبقى النشر الفعلي هو المطابقة المفضَّلة لا العرض الأحدث زمنيًا
    store.remember(history, "Storm knocks out power across region",
                   "https://p/storm-2", None)
    prev2 = store.find_previous(history, "Storm knocks out power across region",
                                "https://p/storm-2", 0.55)
    check("النشر الفعلي يُفضَّل على عرض معلَّق أحدث منه",
          prev2 and prev2.get("posted_title") == "عاصفة تقطع الكهرباء عن المنطقة",
          str(prev2))


def test_bucket_quotas() -> None:
    """الحصص تضمن دفعة مختلطة بدل ما تصادف أن يتصدّر المؤشر."""
    from src.rank import pick_representative

    now = datetime.now(timezone.utc)

    def art(title, bucket, weight=1.0, src="X"):
        return Article(title=title, link=f"https://x/{title[:8]}", summary="",
                       source_name=src, region="r", weight=weight, published=now,
                       bucket=bucket)

    # الخفيف يغلب الجاد في المجموعة الواحدة
    group = [art("Same story here", "serious", src="BBC"),
             art("Same story here", "light", src="People")]
    check("المجموعة المختلطة تُصنَّف خفيفة",
          pick_representative(group).bucket == "light")

    group2 = [art("Other story", "serious", src="BBC"),
              art("Other story", "serious", src="CNN")]
    check("المجموعة الجادة تبقى جادة",
          pick_representative(group2).bucket == "serious")

    # محاكاة اختيار بحصص: 8 جاد ثم 3 خفيف — بلا حصص تُغلق الدفعة على الجاد
    pool = ([art(f"Serious story {i}", "serious") for i in range(8)]
            + [art(f"Light story {i}", "light") for i in range(3)]
            + [art(f"Sport story {i}", "sport") for i in range(2)])

    quotas = {"light": 2, "sport": 1, "serious": 2}
    filled = {k: 0 for k in quotas}
    picked, deferred = [], []
    target = 5
    for phase in (1, 2):
        for a in (pool if phase == 1 else deferred):
            if len(picked) >= target:
                break
            if phase == 1 and (a.bucket not in quotas
                               or filled[a.bucket] >= quotas[a.bucket]):
                deferred.append(a)
                continue
            filled[a.bucket] = filled.get(a.bucket, 0) + 1
            picked.append(a)

    got = {k: sum(1 for a in picked if a.bucket == k) for k in quotas}
    check("الدفعة احترمت الحصص", got == quotas, str(got))
    check("الدفعة مختلطة لا جادة فقط", len({a.bucket for a in picked}) == 3)

    # بلا محتوى خفيف كافٍ، تُملأ الفتحات من المؤجَّل بدل تركها فارغة
    scarce = [art(f"Serious {i}", "serious") for i in range(10)]
    filled2, picked2, deferred2 = {k: 0 for k in quotas}, [], []
    for phase in (1, 2):
        for a in (scarce if phase == 1 else deferred2):
            if len(picked2) >= target:
                break
            if phase == 1 and (a.bucket not in quotas
                               or filled2[a.bucket] >= quotas[a.bucket]):
                deferred2.append(a)
                continue
            filled2[a.bucket] = filled2.get(a.bucket, 0) + 1
            picked2.append(a)
    check("نقص الخفيف لا يترك الدفعة ناقصة", len(picked2) == target,
          f"{len(picked2)} من {target}")


def test_editorial_guardrails() -> None:
    """البرومبت يسمح بالخفيف ويمنع التشهير."""
    from src.writer import CATEGORIES, SYSTEM_PROMPT

    # مشاهير وترفيه أُلغيا عمدًا من CATEGORIES (التزام 8657d52) — البرومبت
    # يمنع أخبار المشاهير صراحة الآن، فلا معنى لاختبار توفر التصنيفين.
    for cat in ("غرائب", "فيروسي", "رياضة"):
        check(f"تصنيف «{cat}» متاح", cat in CATEGORIES)

    check("لا يرفض الخبر لكونه خفيفًا",
          'لا ترفض خبرًا لمجرد أنه "خفيف"' in SYSTEM_PROMPT)
    check("يمنع شائعات الحياة الخاصة", "الشائعات عن الحياة الخاصة" in SYSTEM_PROMPT)
    check("يمنع الإدانة قبل الحكم", "قبل حكم قضائي" in SYSTEM_PROMPT)
    check("يشترط نسبة الاتهام لمصدره", "انسب الاتهام" in SYSTEM_PROMPT)
    check("يمنع الاستهزاء بالأشخاص", "استهزاء" in SYSTEM_PROMPT)
    check("يمنع العناوين المضلِّلة", "لن تصدق" in SYSTEM_PROMPT)


def test_extraction() -> None:
    from src.extract import MIN_CHARS, fetch_text, format_for_prompt, gather

    body = " ".join(["OPEC delegates said the decision followed weeks of talks."] * 12)
    html = f"""<html><body><nav>Home Subscribe Login</nav>
    <article><h1>Oil summit</h1><p>{body}</p></article>
    <footer>Copyright 2026</footer><script>var a=1;</script></body></html>"""
    thin = "<html><body><p>Too short.</p></body></html>"

    class R:
        def __init__(self, text, code=200):
            self.text, self.status_code = text, code

    # ملاحظة: requests وحدة مشتركة بين كل الملفات — نحفظ الأصل ونستعيده
    # في النهاية، وإلا كسرنا اختبار الأنبوب الذي يليه.
    import src.extract as ex
    pages = {"https://a/1": R(html), "https://b/2": R(html),
             "https://c/3": R(thin), "https://d/4": R("", 403),
             "https://e/5": R("", 403), "https://f/6": R("", 403),
             "https://g/7": R("", 403)}
    seen_get_calls: list = []
    original_get = ex.requests.get

    def _fake_get(url, **kw):
        seen_get_calls.append(kw)
        return pages.get(url, R("", 404))

    ex.requests.get = _fake_get
    try:

        text, reason = fetch_text("https://a/1")
        check("النص الأساسي مُستخرج", text and "OPEC delegates" in text)
        check("سبب الفشل فارغ عند النجاح", reason == "")
        # طلب التنفيذ على Issue #373، البند 3: رأس Referer يحاكي وصولًا من
        # Google News — علاج رخيص لحجب France 24/العربية/أورينت نت المتكرر
        check("fetch_text يرسل رأس Referer يحاكي وصولًا من Google News",
              seen_get_calls[-1].get("headers", {}).get("Referer") ==
              "https://news.google.com/", seen_get_calls[-1])
        check("قوائم التنقل مُزالة", text and "Subscribe" not in text)
        check("التذييل والسكربت مُزالان",
              text and "Copyright" not in text and "var a" not in text)
        short_text, short_reason = fetch_text("https://c/3")
        check("النص القصير مرفوض", short_text is None)
        check("سبب رفض النص القصير مذكور صراحة (البند 1، تعليق العطل الثاني)",
              "قصير" in short_reason, short_reason)
        blocked_text, blocked_reason = fetch_text("https://d/4")
        check("الصفحة المحجوبة مرفوضة", blocked_text is None)
        check("سبب رفض الصفحة المحجوبة يذكر رمز HTTP", blocked_reason == "HTTP 403",
              blocked_reason)
        google_text, google_reason = fetch_text("https://news.google.com/rss/articles/X")
        check("رابط جوجل الوسيط يُتجاوز", google_text is None)
        check("سبب تجاوز رابط جوجل الوسيط مذكور صراحة", "جوجل" in google_reason, google_reason)

        members = [{"name": "BBC", "link": "https://a/1"},
                   {"name": "Guardian", "link": "https://b/2"},
                   {"name": "Blocked", "link": "https://d/4"}]
        docs, failures = gather(members, limit=3)
        check("الجلب المتعدد يعيد الناجح فقط", len(docs) == 2, str(len(docs)))
        check("أسماء المصادر محفوظة", {d["name"] for d in docs} == {"BBC", "Guardian"})
        check("فشليات الجلب مُسجَّلة بسببها (البند 1، تعليق العطل الثاني)",
              any(f["name"] == "Blocked" and f["reason"] == "HTTP 403" for f in failures),
              str(failures))

        block = format_for_prompt(docs)
        check("الصياغة تعلّم كل مصدر باسمه",
              "المصدر 1: BBC" in block and "المصدر 2: Guardian" in block)
        check("قائمة فارغة تعطي نصًا فارغًا", format_for_prompt([]) == "")

        # طلب التنفيذ على Issue #373، البند 3: فتحة قراءة فشل جلبها لا تُهدر
        # — أول limit*2 محاولة قد تتصدّرها نطاقات محجوبة (HTTP 403 متكرر)
        # فتُفرَغ الفتحات كلها بلا أي فرصة لمرشح لاحق قابل للجلب فعليًا. هنا
        # limit=1 (batch_size=2) وأربعة مرشحين محجوبين يتصدّرون القائمة قبل
        # مرشح خامس ناجح — يجب أن يُواصَل حتى يُبلَغ عنه
        members_batched = [
            {"name": "Blocked1", "link": "https://d/4"},
            {"name": "Blocked2", "link": "https://e/5"},
            {"name": "Blocked3", "link": "https://f/6"},
            {"name": "Blocked4", "link": "https://g/7"},
            {"name": "Recovers", "link": "https://a/1"},
        ]
        docs_batched, failures_batched = gather(members_batched, limit=1)
        check("لا تُهدر فتحة القراءة عند تصدّر نطاقات محجوبة الدفعة الأولى — "
              "يُواصَل بدفعات تالية حتى مرشح ناجح",
              len(docs_batched) == 1 and docs_batched[0]["name"] == "Recovers",
              (docs_batched, failures_batched))
        check("عدد الفشليات المسجَّلة يطابق كل المحاولات الفاشلة قبل النجاح (4)",
              len(failures_batched) == 4, failures_batched)
    finally:
        ex.requests.get = original_get


def test_analysis_grounding() -> None:
    """القاعدة الحاسمة: الصمت عند غياب المادة، لا الاختراع."""
    from src.writer import (POST_SCHEMA, SYSTEM_PROMPT, USER_TEMPLATE,
                            build_caption)

    fields = POST_SCHEMA["input_schema"]["properties"]

    check("يمنع الاستعانة بالمعرفة السابقة",
          "لا تستعن بمعرفتك السابقة" in SYSTEM_PROMPT)
    check("يأمر بترك الحقل فارغًا عند غياب التفسير",
          "الصمت أفضل من التخمين" in SYSTEM_PROMPT)
    check("يشترط نسبة كل تفسير لقائله", "انسب كل تفسير لقائله" in SYSTEM_PROMPT)
    check("يطلب إظهار الخلاف بين المصادر", "اذكر الخلاف صراحةً" in SYSTEM_PROMPT)
    check("يمنع تكرار المتن في التحليل",
          "لا تكرر شيئًا من post_body" in SYSTEM_PROMPT)
    check("حقل التحليل موجود في المخطط", "analysis" in fields)
    check("حقل التحليل مطلوب في الطلب", "analysis —" in USER_TEMPLATE)
    check("الحقول القديمة أُزيلت",
          not any(f in fields for f in ("why", "meaning", "dispute")))

    cfg = load_config()
    art = Article(title="T", link="https://x/1", summary="", source_name="BBC",
                  region="uk", weight=1.0, published=datetime.now(timezone.utc))
    art.cluster_sources = ["BBC", "Reuters"]

    paragraph = ("تربط رويترز القرار بضعف الطلب الصيني، بينما ترى الغارديان "
                 "أن أثره سيظهر في أسعار الوقود خلال أسابيع.")
    full = build_caption({
        "post_title": "عنوان", "post_body": "متن", "hashtags": ["أخبار"],
        "analysis": paragraph,
    }, art, cfg)
    check("التحليل يظهر في المنشور", paragraph in full)
    check("العنوان الواحد يظهر", "خلف الخبر" in full)
    check("لا أسئلة في المنشور",
          "لماذا حدث" not in full and "ما الذي يعنيه" not in full)
    check("التحليل فقرة واحدة",
          paragraph in full and "\n" not in paragraph)

    empty = build_caption({
        "post_title": "عنوان", "post_body": "متن", "hashtags": ["أخبار"],
        "analysis": "",
    }, art, cfg)
    check("الحقل الفارغ لا يترك عنوانًا معلّقًا", "خلف الخبر" not in empty)
    check("المنشور بلا تحليل يبقى سليمًا", "عنوان" in empty and "متن" in empty)


def test_analysis_cleaning() -> None:
    """تنظيف الفقرة: بلا عناوين، بلا نفي ذاتي، وقصّ عند حدّ الجملة."""
    from src.writer import clean_analysis

    check("النص الفارغ يبقى فارغًا", clean_analysis("") == "")
    check("عبارات النفي البديلة تُفرَّغ", clean_analysis("لا يوجد") == "")

    with_heading = clean_analysis("🔎 لماذا حدث هذا؟\nتربط رويترز القرار بالسوق.")
    check("العنوان يُزال", "لماذا حدث" not in with_heading)
    check("النص يبقى", "تربط رويترز" in with_heading)

    bulleted = clean_analysis("- السبب الأول واضح.\n- والثاني كذلك.")
    check("القائمة تصير فقرة واحدة",
          "\n" not in bulleted and bulleted.startswith("السبب"))

    negating = clean_analysis(
        "تربط رويترز القرار بالسوق. تذكر بي بي سي 700 مبنى وتذكر الغارديان "
        "أكثر من 700، ولا تناقض بين الرقمين. ويتوقع محللون تشديدًا لاحقًا."
    )
    check("الجملة التي تنفي التناقض تُحذف", "لا تناقض" not in negating)
    check("بقية الفقرة تبقى",
          "تربط رويترز" in negating and "يتوقع محللون" in negating)

    long_text = " ".join(f"جملة رقم {i} فيها خمس كلمات." for i in range(1, 21))
    trimmed = clean_analysis(long_text, max_words=20)
    check("القصّ يحترم السقف", len(trimmed.split()) <= 20)
    check("القصّ عند نهاية جملة", trimmed.endswith("."))


def test_cluster_members() -> None:
    from src.rank import pick_representative

    now = datetime.now(timezone.utc)
    group = [
        Article(title="Same event", link="https://news.google.com/rss/x",
                summary="", source_name="GN", region="global", weight=0.6,
                published=now, publisher="Google"),
        Article(title="Same event", link="https://bbc.com/a", summary="",
                source_name="BBC", region="uk", weight=1.2, published=now,
                publisher="BBC"),
        Article(title="Same event", link="https://guardian.com/b", summary="",
                source_name="Guardian", region="uk", weight=1.1, published=now,
                publisher="Guardian"),
    ]
    rep = pick_representative(group)
    links = [m["link"] for m in rep.cluster_members]
    check("روابط كل النسخ مجموعة", len(links) == 2, str(links))
    check("روابط جوجل الوسيطة مستبعدة",
          not any("news.google" in l for l in links))
    check("الأثقل وزنًا أولًا", rep.cluster_members[0]["name"] == "BBC")


def test_useful_bucket() -> None:
    """الصحة والتقنية لهما حصة محمية لا تسحقها السياسة."""
    import yaml
    from collections import Counter

    cfg_raw = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    buckets = Counter(x.get("bucket", "serious") for x in cfg_raw["sources"])
    regions = Counter(x["region"] for x in cfg_raw["sources"])

    check("تصنيف useful موجود في المصادر", buckets["useful"] >= 15, str(buckets))
    # الدفعة الافتراضية صغّرت من 10 إلى 4 (التزام 2f8807b) والحصص معها
    # بنفس النسبة تقريبًا — العتبة هنا مطلقة على حجم الدفعة الحالي.
    check("حصة useful محمية في الدفعة",
          cfg_raw["selection"]["quotas"].get("useful", 0) >= 1,
          str(cfg_raw["selection"]["quotas"]))

    for region, label in [("health", "صحة"), ("tech", "تقنية"),
                          ("money", "أسواق"), ("migration", "هجرة")]:
        check(f"مصادر {label} موجودة", regions[region] >= 2,
              f"{regions[region]}")

    # كل مصادر النافع موسومة فعلًا
    unlabelled = [x["name"] for x in cfg_raw["sources"]
                  if x["region"] in ("health", "tech", "money", "migration", "science")
                  and x.get("bucket") != "useful"]
    check("كل المصادر النافعة موسومة", not unlabelled, str(unlabelled))


def test_health_guardrails() -> None:
    """المحتوى الصحي أخطر ما ينشره حساب إخباري — الضوابط إلزامية."""
    from src.writer import CATEGORIES, SYSTEM_PROMPT

    for cat in ("صحة", "تقنية", "أسواق", "هجرة"):
        check(f"تصنيف «{cat}» متاح", cat in CATEGORIES)

    check("يمنع توجيه القارئ طبيًا", "لا توجّه القارئ إطلاقًا" in SYSTEM_PROMPT)
    check("يفرّق بين الارتباط والسببية",
          "الارتباط ليس سببية" in SYSTEM_PROMPT)
    check("يمنع ذكر الجرعات والبروتوكولات", "لا تذكر جرعة دواء" in SYSTEM_PROMPT)
    check("يمنع الخلط بين البحث المخبري والعلاج",
          "التجربة على الفئران ليس علاجًا" in SYSTEM_PROMPT)
    check("يطلب إحالة القارئ لطبيب", "استشر طبيبًا مختصًا" in SYSTEM_PROMPT)
    check("يرفض العلاج البديل غير المثبت",
          "علاج بديل غير مثبت" in SYSTEM_PROMPT)
    check("يمنع التوصية بشراء أو بيع",
          "لا توصية بشراء أو بيع" in SYSTEM_PROMPT)
    check("يمنع الوعد بقبول طلبات الهجرة", "لا تعد بقبول" in SYSTEM_PROMPT)


def test_dedupe_memory() -> None:
    history: list[dict] = []
    store.remember(history, "Oil prices surge after OPEC+ announces surprise output cut",
                   "https://example.com/oil-opec")
    check("نفس الرابط يُعد مكررًا",
          store.is_duplicate(history, "أي عنوان", "https://example.com/oil-opec", 0.62))
    check("عنوان شديد الشبه يُعد مكررًا",
          store.is_duplicate(history, "OPEC+ surprise output cut sends oil prices surging",
                             "https://other.com/x", 0.62))
    check("خبر مختلف لا يُعد مكررًا",
          not store.is_duplicate(history, "Magnitude 6.1 earthquake strikes Japan",
                                 "https://other.com/y", 0.62))


def test_dedupe_threshold_separation() -> None:
    """Issue #274: عتبة selection.title_similarity (0.62، لتجميع cluster()
    داخل التشغيلة الواحدة) صارمة جدًا لذاكرة التكرار عبر التشغيلات، حيث
    تتفاوت صياغة العنوان أكثر بين ناشر وآخر عبر الزمن. عيّنة حقيقية من
    الإنتاج: ثلاث صياغات لحادثة إطلاق نار في مدرسة تايلاندية خلال أقل من
    ساعتين — الخوارزمية لا ترى أنها الخبر نفسه فتُنتَج لها مسودات منفصلة
    يرفضها المراجع لاحقًا يدويًا كمكررة."""
    t1 = "One killed, four injured in Thailand school shooting, officials say"
    t2 = "Suspect among 7 dead in Thailand school shooting; 15 injured"
    t3 = "Thailand school shooting: seven killed including suspected attacker, police say"

    sim_12 = similarity(tokens(t1), tokens(t2))
    sim_13 = similarity(tokens(t1), tokens(t3))
    sim_23 = similarity(tokens(t2), tokens(t3))
    check("تشابه العنوانين 1-2 يطابق العيّنة المرصودة",
          0.55 <= sim_12 <= 0.59, f"{sim_12:.3f}")
    check("تشابه العنوانين 1-3 يطابق العيّنة المرصودة",
          0.54 <= sim_13 <= 0.58, f"{sim_13:.3f}")
    check("تشابه العنوانين 2-3 يطابق العيّنة المرصودة",
          0.40 <= sim_23 <= 0.44, f"{sim_23:.3f}")

    cfg = load_config(ROOT / "config.yaml")
    old_threshold = float(cfg["selection"]["title_similarity"])
    new_threshold = float(cfg["selection"]["dedupe_title_similarity"])
    check("title_similarity (عتبة cluster) لم تتغير", old_threshold == 0.62,
          f"{old_threshold}")
    check("dedupe_title_similarity أخفض من title_similarity",
          new_threshold < old_threshold, f"{new_threshold} < {old_threshold}")

    history: list[dict] = []
    store.remember(history, t1, "https://example.com/thailand-1")
    check("عتبة 0.62 (القديمة) تفوّت المتابعتين كليًا",
          not store.is_duplicate(history, t2, "https://other.com/x", old_threshold)
          and not store.is_duplicate(history, t3, "https://other.com/y", old_threshold))
    check("عتبة 0.5 (الجديدة) تمسك متابعتين على الأقل",
          sum([store.is_duplicate(history, t2, "https://other.com/x", new_threshold),
               store.is_duplicate(history, t3, "https://other.com/y", new_threshold)]) >= 2)

    # cluster() يستعمل selection.title_similarity من القاموس الممرَّر إليه
    # مباشرة — لا القيمة الجديدة — فسلوكه عبر هذا الاختبار غير متأثر بها
    arts = [
        Article(title=t1, link="https://example.com/thailand-1",
               summary="", source_name="P1", region="asia", weight=1.0,
               published=datetime.now(timezone.utc), bucket="serious"),
        Article(title=t2, link="https://example.com/thailand-2",
               summary="", source_name="P2", region="asia", weight=1.0,
               published=datetime.now(timezone.utc), bucket="serious"),
    ]
    grouped = cluster(arts, old_threshold)
    check("cluster() يبقى بعتبة 0.62 (لا يدمج عنوانين بتشابه 0.571)",
          len(grouped) == 2, f"{len(grouped)} مجموعة")


def test_screen_merge_missing_api_key() -> None:
    """عطل رُصد فعليًا (تعليق لاحق على Issue #274): merge.semantic_merge كان
    يلتقط APIError/JSONDecodeError/ValueError فقط، وscreen.screen كان يبني
    العميل خارج أي try/except أصلًا — فغياب ANTHROPIC_API_KEY (RuntimeError
    من config.env) يُسقط أنبوب الجمع كله بدل أن يتدهور بأمان ويكمل بلا
    فرز/دمج دلالي، كما توثّق نيّة كلتا الدالتين في تذييلهما."""
    from src import merge, screen as screen_mod

    arts = [
        Article(title="خبر أول عن حدث ما", link="https://example.com/a1",
               summary="", source_name="P1", region="global", weight=1.0,
               published=datetime.now(timezone.utc)),
        Article(title="خبر ثانٍ عن حدث مختلف تمامًا", link="https://example.com/a2",
               summary="", source_name="P2", region="global", weight=1.0,
               published=datetime.now(timezone.utc)),
    ]

    def _missing_key():
        raise RuntimeError("متغير البيئة ANTHROPIC_API_KEY غير موجود")

    real_merge_client, real_screen_client = merge._client, screen_mod._client
    merge._client, screen_mod._client = _missing_key, _missing_key
    try:
        merged = merge.semantic_merge(list(arts), {"merge": {"enabled": True}})
        screened = screen_mod.screen(list(arts), {"screening": {"enabled": True}})
    finally:
        merge._client, screen_mod._client = real_merge_client, real_screen_client

    check("غياب مفتاح API لا يُسقط الدمج الدلالي — يعيد القائمة كما هي",
          [a.link for a in merged] == [a.link for a in arts])
    check("غياب مفتاح API لا يُسقط الفرز الأولي — يعيد القائمة كاملة",
          [a.link for a in screened] == [a.link for a in arts])


def test_radar_gate_check_dedupe() -> None:
    """Issue #303: التشخيص أثبت أن score/group_sources لا يميّزان تحديث
    خبر منشور عن خبر جديد فعلًا — بل مرفوضات الرادار كانت أعلى قليلًا في
    المتوسط على كلا المقياسين. كاشف التكرار الدلالي (merge.find_duplicate_event)
    يجب أن يرصد «زلزال يقتل 20» مقابل «ترتفع حصيلة الزلزال إلى 111» كحدث
    واحد، ويمنع النشر التلقائي رغم استيفاء كل العتبات العددية.

    Issue #312: هذا القرار انتقل إلى gate_check ليُحسم *قبل* الصياغة —
    يتحقق هذا الاختبار أيضًا أن gate_check يعيد docs (من extract.gather،
    بلا نموذج) ولا يستدعي write_arabic إطلاقًا مهما كانت نتيجة الفحص."""
    from src import merge, radar
    from src.sources import Article

    published_title = "Earthquake kills 20 in Colombia"
    update_title = "Earthquake death toll rises to 111 in Colombia"
    unrelated_title = "Central bank raises interest rates"

    # كاشف مزيَّف بلا أي شبكة: يجمع عنوانين يشتركان في كلمتي الحدث
    # المميّزتين، ويحاكي بذلك ما يفعله الفحص الدلالي الحقيقي بـ Haiku.
    def fake_group_titles(titles, cfg):
        marker = {"earthquake", "colombia"}
        base = set(titles[0].lower().split())
        group0 = [0]
        for i, t in enumerate(titles[1:], start=1):
            if base & set(t.lower().split()) & marker:
                group0.append(i)
        return [group0] + [[i] for i in range(len(titles)) if i not in group0]

    def _write_should_not_be_called(*a, **kw):
        raise AssertionError("gate_check لا يجوز أن يستدعي الصياغة")

    real_group_titles = merge._group_titles
    real_gather = radar.gather_texts
    real_write = radar.write_arabic
    merge._group_titles = fake_group_titles
    radar.gather_texts = lambda members, limit=2: ([{"name": "Reuters", "text": "..."}], [])
    radar.write_arabic = _write_should_not_be_called
    try:
        ok_dup, matched = merge.find_duplicate_event(update_title, [published_title], {})
        ok_new, matched_none = merge.find_duplicate_event(
            unrelated_title, [published_title], {})
        ok_empty, matched_empty = merge.find_duplicate_event(update_title, [], {})

        check("تحديث حصيلة الضحايا يُكتشف كحدث واحد مع المنشور",
              ok_dup and matched == published_title, str((ok_dup, matched)))
        check("خبر غير مرتبط لا يُعامل كتكرار",
              ok_new and matched_none is None, str((ok_new, matched_none)))
        check("لا عناوين منشورة سابقًا = لا تكرار بلا استدعاء نموذج",
              ok_empty and matched_empty is None)

        # عبر gate_check نفسها: مرشّح يستوفي كل الشروط العددية لكنه تحديث
        # لخبر نُشر خلال نافذة auto_publish_dedupe_days يجب أن يُرفض.
        art = Article(title=update_title, link="https://example.com/quake-update",
                     summary="", source_name="X", region="global", weight=1.0,
                     published=datetime.now(timezone.utc), score=30.0, group_sources=5)
        cfg = {"radar": {
            "auto_publish": True, "auto_publish_daily_limit": 3,
            "auto_publish_min_score": 19.3, "auto_publish_min_sources": 2,
            "auto_publish_dedupe_days": 3,
        }}

        real_recent = store.recent_published_titles
        store.recent_published_titles = lambda days: [published_title]
        try:
            ok, why, docs = radar.gate_check(art, cfg, {"auto_published": []})
        finally:
            store.recent_published_titles = real_recent

        check("تحديث حصيلة الضحايا لا يُنشر تلقائيًا رغم استيفاء العتبات العددية",
              not ok and published_title in why, why)
        check("gate_check يعيد docs المستخرجة رغم الرفض",
              bool(docs) and docs[0]["name"] == "Reuters", str(docs))

        # خبر مستوفٍ حقًا وغير مرتبط بأي عنوان منشور يمرّ كالمعتاد
        art_new = Article(title=unrelated_title, link="https://example.com/rates",
                          summary="", source_name="X", region="global", weight=1.0,
                          published=datetime.now(timezone.utc), score=30.0,
                          group_sources=5)
        store.recent_published_titles = lambda days: [published_title]
        try:
            ok2, why2, docs2 = radar.gate_check(art_new, cfg, {"auto_published": []})
        finally:
            store.recent_published_titles = real_recent
        check("خبر جديد فعلًا يستوفي شروط النشر التلقائي كالمعتاد",
              ok2, why2)
        check("gate_check يعيد docs نفسها لإعادة استخدامها في build_draft بلا استخراج مزدوج",
              bool(docs2) and docs2[0]["name"] == "Reuters", str(docs2))
    finally:
        merge._group_titles = real_group_titles
        radar.gather_texts = real_gather
        radar.write_arabic = real_write


def test_radar_preselect_fallback() -> None:
    """Issue #312: مرشّح عاجل لا يستوفي شروط النشر التلقائي يجب أن يُحفظ
    كمرشح خام في state/candidates (بلا صياغة ولا صورة) بدل أن يُصاغ وتُبنى
    صورته ثم يُرفض غالبًا في المراجعة. يتحقق أيضًا أن store.remember سُجِّل
    للمرشح فورًا — بلاها سيُعاد التقاطه وحفظه كمرشح مكرر كل 15 دقيقة (الرادار
    يعمل بهذا التواتر، خلافًا لـ collect.py الذي يعمل على دفعات متباعدة)."""
    from src.config import Config
    from src import radar
    from src.sources import Article

    art = Article(title="Volcano erupts sending ash miles into the sky",
                 link="https://example.com/volcano-preselect-fallback",
                 summary="", source_name="X", region="global", weight=1.0,
                 published=datetime.now(timezone.utc), score=30.0,
                 velocity=1.0, group_sources=5)

    fake_cfg = Config({
        "radar": {
            "enabled": True, "max_per_run": 1,
            # يفشل عند شرط المؤشر فقط — لا حاجة لتزييف extract/merge
            "auto_publish": True, "auto_publish_min_score": 99.0,
            "auto_publish_min_sources": 2, "auto_publish_daily_limit": 3,
            "preselect_fallback": True,
        },
        "selection": {},
    })

    real_scan, real_load_config = radar.scan, radar.load_config
    radar.scan = lambda cfg: [art]
    radar.load_config = lambda path=None: fake_cfg
    try:
        code = radar.main()
    finally:
        radar.scan, radar.load_config = real_scan, real_load_config

    check("radar.main() ينتهي بنجاح مع مرشح preselect_fallback", code == 0, f"exit={code}")

    saved_candidates = [c for _, c in store.pending_candidates() if c["id"] == art.uid]
    check("المرشح غير المستوفي يُحفظ في state/candidates", len(saved_candidates) == 1,
          str(len(saved_candidates)))
    if saved_candidates:
        check("المرشح المحفوظ بلا صياغة ولا صورة",
              "arabic" not in saved_candidates[0] and "caption" not in saved_candidates[0])

        # Issue #319 البند 2: مرشّح الرادار المرفوض يُبنى بـ preselect.build_
        # candidate نفسها التي يستخدمها collect.py — فيظهر بنفس المربعين
        # («انشر فورًا»/«صغ واعرض») بلا أي تمييز، بلا حاجة لأي كود إضافي
        # في radar.py نفسه.
        from src import preselect
        radar_body = preselect.build_selection_issue_body(saved_candidates)
        check("مرشح الرادار يظهر بمربعي «انشر فورًا» و«صغ واعرض» كمرشح collect تمامًا",
              f"<!-- now:{art.uid} -->" in radar_body
              and f"<!-- review:{art.uid} -->" in radar_body)

    saved_drafts = [d for _, d in store.pending_drafts() if d["id"] == art.uid]
    check("لا مسودة كاملة تُبنى لهذا المرشح", saved_drafts == [], str(saved_drafts))

    history = store.load_history()
    check("store.remember سجّل المرشح فورًا فلا يُعاد التقاطه كل 15 دقيقة",
          store.find_previous(history, art.title, art.link, 0.5) is not None)


def test_collect_end_to_end() -> None:
    """يغطي مساري collect.main(): القديم (preselect.enabled=False) يبني
    مسودات كاملة فورًا، وpreselect (enabled=True) يبني مرشحين خامًا فقط
    بانتظار اختيار بشري. كلا الفرعين يضبط preselect.enabled صراحةً في
    تهيئته بدل أن يرثه من config.yaml — تفعيل preselect.enabled: true
    افتراضيًا هناك (Issue #280) كسر هذا الاختبار سابقًا لأنه افترض ضمنيًا
    أن collect.main() يبني مسودات كاملة دومًا (Issue #301)."""
    real_load_config = collect.load_config

    def _configured(preselect_enabled):
        cfg = load_config()
        cfg["preselect"] = {"enabled": preselect_enabled, "candidates_per_run": 5}
        return cfg

    def _run(cfg, limit=2):
        collect.load_config = lambda path=None: cfg
        sys.argv = ["collect", "--limit", str(limit)]
        try:
            return collect.main()
        finally:
            collect.load_config = real_load_config

    # ── مسار preselect: مفعّل صراحة، يبني مرشحين خامًا لا مسودات ──
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    code_pre = _run(_configured(True))
    check("collect (مسار preselect) انتهى بنجاح", code_pre == 0, f"exit={code_pre}")
    check("preselect لا يبني مسودات كاملة", store.pending_drafts() == [],
          str(store.pending_drafts()))
    check("preselect يبني مرشحين خامًا بانتظار الاختيار",
          len(store.pending_candidates()) > 0, str(len(store.pending_candidates())))

    # ── المسار القديم: معطّل صراحة، يبني مسودات كاملة فورًا (بلا اختيار بشري) ──
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    legacy_cfg = _configured(False)
    code = _run(legacy_cfg)
    check("collect (المسار القديم) انتهى بنجاح", code == 0, f"exit={code}")

    pending = store.pending_drafts()
    check("أُنشئت مسودتان", len(pending) == 2, f"{len(pending)}")

    # لا نُرجع مبكرًا عند فشل الشرط أعلاه (نمط سابق كان يتخطى ١٥ فحصًا
    # بصمت) — draft يبقى قاموسًا فارغًا فتُظهر الفحوص التالية فشلها صراحة
    # بدل أن تختفي من التقرير.
    draft = pending[0][1] if pending else {}
    for field in ("id", "status", "score", "source", "arabic", "caption", "image"):
        check(f"حقل '{field}' موجود في المسودة", field in draft)

    # "drafts/..." مسار نسبي لمستودع جيت لا لمجلد الكتابة الفعلي أثناء
    # الاختبار (DRAFTS_DIR هنا مجلد مؤقت) — نحوّله عبره لا عبر ROOT.
    img = (DRAFTS_DIR / Path(draft["image"]).relative_to("drafts")
           if draft.get("image") else None)
    check("ملف الصورة أُنشئ فعلًا", bool(img and img.exists()), str(img))
    if img and img.exists():
        with Image.open(img) as im:
            check("أبعاد الصورة 1080×1080", im.size == (1080, 1080), str(im.size))
    else:
        check("أبعاد الصورة 1080×1080", False, "لا صورة لقياس أبعادها")

    caption = draft.get("caption", "")
    check("التعليق يحوي هاشتاقات", "#" in caption)
    # المصادر انتقلت إلى تذييل الصورة والتعليق الأول — لا مكان لها في المتن
    check("المتن بلا سطر مصادر", "المصدر:" not in caption)
    check("المصادر محفوظة في المسودة",
          bool((draft.get("source") or {}).get("publishers")))
    check("التعليق ليس فارغًا", len(caption) > 80, f"{len(caption)} حرفًا")
    check("سجل التكرار حُفظ", (STATE_DIR / "history.json").exists())

    # تشغيل ثانٍ بلا مسح الحالة، بنفس الإعداد صراحة: يجب ألا يعيد إنتاج
    # نفس الأخبار
    code2 = _run(legacy_cfg)
    check("التشغيل الثاني انتهى بنجاح", code2 == 0, f"exit={code2}")
    check("التشغيل الثاني لم يكرر نفس الأخبار",
          len(store.pending_drafts()) == 2, f"{len(store.pending_drafts())}")


def test_review_roundtrip() -> None:
    drafts = [d for _, d in store.pending_drafts()]
    # لا نُرجع مبكرًا عند غياب المسودات (نمط سابق كان يتخطى أربعة فحوص
    # بصمت) — الفحوص التالية تعمل بقيم افتراضية آمنة فتُظهر فشلها صراحة
    # بدل أن تختفي من التقرير.
    check("توجد مسودات لبناء الـ Issue", bool(drafts), f"{len(drafts)}")

    body = review.build_issue_body(drafts, "user/trendnews", "main")
    ids = review.all_draft_ids(body)
    check("معرفات المسودات مضمّنة في نص الـ Issue",
          len(ids) == len(drafts), f"{len(ids)} من {len(drafts)}")
    check("الصور معروضة برابط raw", "raw.githubusercontent.com" in body)
    check("مربعات الاختيار فارغة ابتداءً", review.parse_approved(body) == [])

    # محاكاة تعليم المستخدم على المسودة الأولى
    marked = body.replace(f"- [ ] **1.", f"- [x] **1.", 1)
    approved = review.parse_approved(marked)
    expected_first = [drafts[0]["id"]] if drafts else []
    check("قراءة العلامة ✔️ تعمل", approved == expected_first, str(approved))

    marked_all = marked.replace("- [ ] **2.", "- [x] **2.", 1)
    check("اعتماد متعدد يعمل", len(review.parse_approved(marked_all)) == min(2, len(drafts)))


# ═══════════ نقطة التوقف قبل الصياغة (preselect — Issue #280) ═══════════


def test_preselect_no_spend_before_selection() -> None:
    """بناء Issue الاختيار لا يستدعي صياغة Sonnet ولا يبني صورة — فقط
    الترتيب والفرز الرخيصان (Haiku) سبقا هذه النقطة، تمامًا كالدورة
    القديمة قبلها. هذا هو التوفير الذي طلبه Issue #280: الإنفاق يقع بعد
    الاختيار البشري لا قبله."""
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    write_calls: list = []
    real_write = writer.write_arabic

    def _spy_write(*a, **kw):
        write_calls.append(1)
        return real_write(*a, **kw)

    writer.write_arabic = _spy_write
    collect.write_arabic = _spy_write

    image_calls: list = []
    real_build_image = collect.build_post_image

    def _spy_image(*a, **kw):
        image_calls.append(1)
        return real_build_image(*a, **kw)

    collect.build_post_image = _spy_image

    cfg = load_config()
    cfg["preselect"] = {"enabled": True, "candidates_per_run": 5}
    real_load_config = collect.load_config
    collect.load_config = lambda path=None: cfg

    sys.argv = ["collect", "--limit", "5"]
    try:
        code = collect.main()
    finally:
        collect.load_config = real_load_config
        writer.write_arabic = real_write
        collect.write_arabic = real_write
        collect.build_post_image = real_build_image

    check("preselect انتهى بنجاح", code == 0, f"exit={code}")
    check("لا استدعاء لصياغة Sonnet أثناء بناء الاختيار", write_calls == [])
    check("لا بناء صورة أثناء بناء الاختيار", image_calls == [])

    pending = store.pending_candidates()
    check("مرشحون خام محفوظون بانتظار الاختيار", len(pending) > 0, str(len(pending)))
    if pending:
        _, cand = pending[0]
        for field in ("id", "title", "link", "publishers", "bucket", "score", "article"):
            check(f"حقل '{field}' موجود في المرشح", field in cand)
        check("لا حقل صياغة عربية في المرشح الخام", "arabic" not in cand)

    check("لا مسودات جاهزة أُنشئت في مرحلة preselect (بلا صياغة ولا صورة)",
          len(store.pending_drafts()) == 0, f"{len(store.pending_drafts())}")

    history = store.load_history()
    check("run_preselect سجّل مرشحيه في history.json فورًا (Issue #331) "
          "فلا يُعاد التقاطهم كـ«جدد» قبل أن يُبتّ في مصيرهم",
          pending and store.find_previous(
              history, pending[0][1]["title"], pending[0][1]["link"], 0.5) is not None)


def test_preselect_no_duplicate_across_runs() -> None:
    """Issue #331: تشغيلتان متتاليتان لـ collect (preselect.enabled=True)
    بفارق دقائق يجب ألا تُنتجا نفس المرشحين مرتين — قبل الإصلاح كان
    run_preselect لا يستدعي store.remember، فلا يدخل المرشحون ذاكرة
    التكرار إلا إن اختِيروا لاحقًا، فتُعاد تشغيلة قريبة زمنيًا التقاط
    نفس الأخبار من جديد بصفتها "جديدة" في Issue اختيار منفصل."""
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    cfg["preselect"] = {"enabled": True, "candidates_per_run": 5}
    real_load_config = collect.load_config
    collect.load_config = lambda path=None: cfg
    sys.argv = ["collect", "--limit", "5"]
    try:
        code1 = collect.main()
        first_titles = {c["title"] for _, c in store.pending_candidates()}
        code2 = collect.main()
        second_run_titles = {c["title"] for _, c in store.pending_candidates()} - first_titles
    finally:
        collect.load_config = real_load_config

    check("كلتا التشغيلتين انتهتا بنجاح", code1 == 0 and code2 == 0,
          f"{code1}, {code2}")
    check("التشغيلة الأولى أنتجت مرشحين", len(first_titles) > 0, str(len(first_titles)))
    check("التشغيلة الثانية (بعد قليل) لم تُعِد نفس مرشحي الأولى كمرشحين جدد",
          second_run_titles == set(), str(second_run_titles))


def test_preselect_finalize() -> None:
    """الاعتماد على Issue الاختيار يصوغ المختار وحده وينشره مباشرة، وغير
    المختار يُسجَّل في feedback ليتعلّم الفرز الأولي منه لاحقًا."""
    from src import collect_finalize, feedback, preselect
    from src import publish as publish_mod

    now = datetime.now(timezone.utc)
    art_a = Article(title="خبر أول يستحق الاختيار الآن", link="https://pre.example/a",
                    summary="", source_name="P1", region="r1", weight=1.0,
                    published=now, bucket="serious", publisher="P1")
    art_b = Article(title="خبر ثانٍ لن يختاره أحد", link="https://pre.example/b",
                    summary="", source_name="P2", region="r2", weight=1.0,
                    published=now, bucket="light", publisher="P2")

    cand_a = preselect.build_candidate(art_a)
    cand_b = preselect.build_candidate(art_b)
    store.save_candidate(cand_a)
    store.save_candidate(cand_b)

    body = preselect.build_selection_issue_body([cand_a, cand_b])
    marked = tick_marker(body, f"now:{cand_a['id']}")   # «انشر فورًا» للمرشح الأول فقط

    now_selected = preselect.parse_publish_now(marked)
    check("تحليل «انشر فورًا» يلتقط المُعلَّم فقط", now_selected == [cand_a["id"]],
          str(now_selected))
    check("لا أحد عُلِّم على «صغ واعرض»",
          preselect.parse_draft_review(marked) == [])

    captured: dict = {}

    def fake_burst(ids, cfg, issue_number, only_urgent=False, skip_urgent=False,
                   inline_cap_minutes=None):
        captured["ids"] = list(ids)
        captured["issue_number"] = issue_number
        captured["inline_cap_minutes"] = inline_cap_minutes
        return 0

    real_burst = publish_mod.cmd_burst
    publish_mod.cmd_burst = fake_burst

    rejections_before = len(feedback.load())

    try:
        code = collect_finalize.finalize(4242, marked, load_config())
    finally:
        publish_mod.cmd_burst = real_burst

    check("finalize انتهى بنجاح", code == 0, f"exit={code}")
    check("نُشر المختار وحده عبر cmd_burst",
          captured.get("ids") == [cand_a["id"]], str(captured))
    check("رقم الـ Issue مرَّر لـ cmd_burst", captured.get("issue_number") == 4242)
    check("finalize يمرّر inline_cap_minutes=0 كي لا ينام urgent (Issue #315)",
          captured.get("inline_cap_minutes") == 0, str(captured))

    check("صيغت مسودة للمختار", store.load_draft(cand_a["id"]) is not None)
    check("لم تُصَغ مسودة لغير المختار", store.load_draft(cand_b["id"]) is None)

    rejections_after = feedback.load()
    check("عدد سجلات الرفض ازداد بواحد فقط (غير المختار وحده)",
          len(rejections_after) == rejections_before + 1,
          f"{len(rejections_after)} مقابل {rejections_before}")
    check("غير المختار سُجّل في feedback بسبب عام «لم يُختر»",
          any(e["id"] == cand_b["id"] and e["tag"] == "لم يُختر"
              for e in rejections_after),
          str(rejections_after[-3:]))

    updated_a = store.load_candidate(cand_a["id"])
    check("حالة المختار selected", updated_a and updated_a[1]["status"] == "selected")
    updated_b = store.load_candidate(cand_b["id"])
    check("حالة غير المختار unselected",
          updated_b and updated_b[1]["status"] == "unselected")


def test_preselect_empty_selection_no_spend() -> None:
    """لا تعليم على أي مرشح = لا صياغة ولا نشر ولا إنفاق (Issue #280،
    البند 4). حتى وسم `approved` بالخطأ على Issue بلا أي تعليم يجب ألا
    يستدعي الصياغة أو النشر — فقط يعلّم البوت من الرفض الضمني."""
    from src import collect_finalize, feedback, preselect, review
    from src import publish as publish_mod

    # لا شبكة في الاختبارات (راجع تذييل الملف): finalize بلا اختيار يعلّق
    # على الـ Issue ويزيل الوسم — نُحاكي هذين بلا اتصال حقيقي بواجهة GitHub.
    comment_calls, remove_label_calls = [], []
    real_comment = review.comment
    real_remove_label = review.remove_label
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))
    review.remove_label = lambda issue_number, label: remove_label_calls.append(
        (issue_number, label))

    now = datetime.now(timezone.utc)
    art_c = Article(title="خبر ثالث بلا أي تعليم على الإطلاق",
                    link="https://pre.example/c", summary="", source_name="P3",
                    region="r3", weight=1.0, published=now, bucket="useful",
                    publisher="P3")
    cand_c = preselect.build_candidate(art_c)
    store.save_candidate(cand_c)

    body = preselect.build_selection_issue_body([cand_c])   # بلا أي تعليم

    write_calls: list = []
    real_write = collect_finalize.write_arabic

    def _spy_write(*a, **kw):
        write_calls.append(1)
        return real_write(*a, **kw)

    collect_finalize.write_arabic = _spy_write

    burst_calls, now_calls, schedule_calls = [], [], []
    real_burst = publish_mod.cmd_burst
    real_now = publish_mod.cmd_now
    real_schedule = publish_mod.cmd_schedule
    publish_mod.cmd_burst = lambda *a, **kw: burst_calls.append(1)
    publish_mod.cmd_now = lambda *a, **kw: now_calls.append(1)
    publish_mod.cmd_schedule = lambda *a, **kw: schedule_calls.append(1)

    rejections_before = len(feedback.load())

    try:
        code = collect_finalize.finalize(5252, body, load_config())
    finally:
        collect_finalize.write_arabic = real_write
        publish_mod.cmd_burst = real_burst
        publish_mod.cmd_now = real_now
        publish_mod.cmd_schedule = real_schedule
        review.comment = real_comment
        review.remove_label = real_remove_label

    check("finalize بلا تعليم ينتهي بنجاح", code == 0, f"exit={code}")
    check("لا استدعاء صياغة إطلاقًا", write_calls == [])
    check("لا استدعاء نشر من أي نوع",
          not burst_calls and not now_calls and not schedule_calls)
    check("لا مسودة أُنشئت", store.load_draft(cand_c["id"]) is None)
    check("تعليق توضيحي على الـ Issue بلا نشر فعلي (بلا شبكة)",
          len(comment_calls) == 1 and comment_calls[0][0] == 5252)
    check("وسم approved يُزال حتى يصحّح المراجع اختياره",
          remove_label_calls == [(5252, "approved")])

    rejections_after = feedback.load()
    check("المرشح غير المُعلَّم سُجّل كـ«لم يُختر»",
          any(e["id"] == cand_c["id"] and e["tag"] == "لم يُختر"
              for e in rejections_after))
    check("سجل رفض واحد فقط أُضيف", len(rejections_after) == rejections_before + 1)

    updated_c = store.load_candidate(cand_c["id"])
    check("حالة المرشح unselected", updated_c and updated_c[1]["status"] == "unselected")


def test_preselect_drops_stale_candidates() -> None:
    """مرشح معلَّق من تشغيلة preselect سابقة بلا selection_issue (خلل دفع
    state، أو تشغيلة توقفت قبل open_review) لا يجوز أن يتراكم مع الدفعة
    التالية — كان هذا سبب Issue #296 (5 مرشح ثم 10 ثم 22). يجب أن يُسقط
    ويُسجَّل في feedback قبل بناء أي دفعة جديدة."""
    from src import feedback
    from src import preselect as preselect_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    stale_art = Article(title="مرشح معلَّق من تشغيلة preselect سابقة",
                        link="https://pre.example/stale", summary="",
                        source_name="PS", region="rs", weight=1.0,
                        published=now, bucket="serious", publisher="PS")
    stale_cand = preselect_mod.build_candidate(stale_art)
    store.save_candidate(stale_cand)   # selection_issue: None — كأنه من تشغيلة سابقة لم تُربط

    check("المرشح القديم معلَّق فعلًا قبل التشغيلة",
          len(store.pending_candidates()) == 1)

    rejections_before = len(feedback.load())

    cfg = load_config()
    cfg["preselect"] = {"enabled": True, "candidates_per_run": 5}
    real_load_config = collect.load_config
    collect.load_config = lambda path=None: cfg

    sys.argv = ["collect", "--limit", "5"]
    try:
        code = collect.main()
    finally:
        collect.load_config = real_load_config

    check("preselect ينتهي بنجاح رغم وجود مرشح قديم معلَّق", code == 0, f"exit={code}")

    updated_stale = store.load_candidate(stale_cand["id"])
    check("المرشح القديم أُسقط (لم يعد pending)",
          updated_stale is not None and updated_stale[1]["status"] != "pending",
          str(updated_stale[1]["status"] if updated_stale else None))

    rejections_after = feedback.load()
    check("المرشح القديم سُجّل في feedback كـ«لم يُختر»",
          any(e["id"] == stale_cand["id"] and e["tag"] == "لم يُختر"
              for e in rejections_after),
          str(rejections_after[-3:]))
    check("سجل رفض واحد فقط أُضيف للمرشح القديم",
          len(rejections_after) >= rejections_before + 1)

    fresh = store.pending_candidates()
    check("القديم لم يعد ضمن المرشحين المعلَّقين", stale_cand["id"] not in
          {c["id"] for _, c in fresh})
    check("عدد الدفعة الجديدة لا يتجاوز candidates_per_run رغم وجود مرشح قديم مسبقًا",
          len(fresh) <= 5, str(len(fresh)))


# ═══════════ مربعان لكل مرشح: انشر فورًا / صغ واعرض (Issue #319) ═══════════


def test_preselect_two_boxes_now_and_draft_review() -> None:
    """البند 1: «انشر فورًا» يصوغ وينشر مباشرة (سلوك preselect الأصلي)،
    و«صغ واعرض» يصوغ ويحفظ مسودة عادية في Issue مراجعة منفصل بعنوان
    مميّز (البند 3 من طلب الموافقة). تعليم المربعين معًا يُحسم لصالح «صغ
    واعرض» ويُعلَّق تنبيه يذكر عنوان الخبر لا معرّفه (البند 1 من طلب
    الموافقة)."""
    from src import collect_finalize, feedback, preselect, review
    from src import publish as publish_mod

    now = datetime.now(timezone.utc)
    art_now = Article(title="خبر يُنشر فورًا بلا عرض", link="https://pre.example/now",
                      summary="", source_name="PN", region="rn", weight=1.0,
                      published=now, bucket="serious", publisher="PN")
    art_draft = Article(title="خبر يُصاغ ويُعرض قبل النشر",
                        link="https://pre.example/draft", summary="",
                        source_name="PD", region="rd", weight=1.0,
                        published=now, bucket="serious", publisher="PD")
    art_both = Article(title="خبر عُلِّم عليه المربعان معًا بالخطأ",
                       link="https://pre.example/both", summary="",
                       source_name="PB", region="rb", weight=1.0,
                       published=now, bucket="serious", publisher="PB")

    cand_now = preselect.build_candidate(art_now)
    cand_draft = preselect.build_candidate(art_draft)
    cand_both = preselect.build_candidate(art_both)
    for c in (cand_now, cand_draft, cand_both):
        store.save_candidate(c)

    body = preselect.build_selection_issue_body([cand_now, cand_draft, cand_both])
    marked = body
    marked = tick_marker(marked, f"now:{cand_now['id']}")
    marked = tick_marker(marked, f"review:{cand_draft['id']}")
    marked = tick_marker(marked, f"now:{cand_both['id']}")
    marked = tick_marker(marked, f"review:{cand_both['id']}")

    check("«انشر فورًا» يلتقط المرشح الأول والثالث (المزدوج)",
          preselect.parse_publish_now(marked) == [cand_now["id"], cand_both["id"]])
    check("«صغ واعرض» يلتقط المرشح الثاني والثالث (المزدوج)",
          preselect.parse_draft_review(marked)
          == [cand_draft["id"], cand_both["id"]])

    burst_calls: list = []

    def fake_burst(ids, cfg, issue_number, only_urgent=False, skip_urgent=False,
                   inline_cap_minutes=None):
        burst_calls.append(list(ids))
        return 0

    create_issue_calls: list = []

    def fake_create_issue(title, body, labels=None):
        create_issue_calls.append({"title": title, "body": body, "labels": labels})
        return {"number": 9911, "html_url": "https://x/issues/9911"}

    comment_calls: list = []
    ensure_labels_calls: list = []

    real_burst = publish_mod.cmd_burst
    real_create_issue = review.create_issue
    real_comment = review.comment
    real_ensure_labels = review.ensure_labels
    publish_mod.cmd_burst = fake_burst
    review.create_issue = fake_create_issue
    review.comment = lambda issue_number, text: comment_calls.append(
        (issue_number, text))
    review.ensure_labels = lambda: ensure_labels_calls.append(1)

    rejections_before = len(feedback.load())

    real_repo = os.environ.get("GITHUB_REPOSITORY")
    real_ref = os.environ.get("GITHUB_REF_NAME")
    os.environ["GITHUB_REPOSITORY"] = "user/trendnews"
    os.environ["GITHUB_REF_NAME"] = "main"
    try:
        code = collect_finalize.finalize(4343, marked, load_config())
    finally:
        publish_mod.cmd_burst = real_burst
        review.create_issue = real_create_issue
        review.comment = real_comment
        review.ensure_labels = real_ensure_labels
        if real_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo
        if real_ref is None:
            os.environ.pop("GITHUB_REF_NAME", None)
        else:
            os.environ["GITHUB_REF_NAME"] = real_ref

    check("finalize انتهى بنجاح", code == 0, f"exit={code}")
    check("«انشر فورًا» فُوِّض للنشر وحده (لا المزدوج ولا «صغ واعرض»)",
          burst_calls == [[cand_now["id"]]], str(burst_calls))

    check("Issue مراجعة واحد فُتح لكل مسودات «صغ واعرض» في الدفعة",
          len(create_issue_calls) == 1, str(len(create_issue_calls)))
    if create_issue_calls:
        opened = create_issue_calls[0]
        check("عنوان Issue «صغ واعرض» مميّز عن Issue المراجعة العادي",
              opened["title"].startswith("📝 مسودات مطلوبة"), opened["title"])
        check("Issue «صغ واعرض» يحمل وسم pending-review كأي مراجعة عادية",
              opened["labels"] == ["pending-review"], str(opened["labels"]))
        check("جسم Issue «صغ واعرض» يضم مسودتي الثاني والمزدوج",
              f"<!-- draft:{cand_draft['id']} -->" in opened["body"]
              and f"<!-- draft:{cand_both['id']} -->" in opened["body"])
        # البند 4: خانة تبديل الصورة تظهر فعليًا الآن — المسودة تُعرض في
        # Issue مراجعة حقيقي بدل ألا تُعرض أبدًا كما قبل هذا التغيير.
        check("مربع تبديل الصورة يظهر في Issue «صغ واعرض»",
              f"<!-- img:{cand_draft['id']} -->" in opened["body"])
        check("فراغ رابط الصورة يظهر في Issue «صغ واعرض»",
              f"<!-- imgurl:{cand_draft['id']} -->" in opened["body"])

    check("مسودة صيغت للمنشور فورًا", store.load_draft(cand_now["id"]) is not None)
    draft_review_saved = store.load_draft(cand_draft["id"])
    both_review_saved = store.load_draft(cand_both["id"])
    check("مسودة صيغت للمرشح الثاني (صغ واعرض)", draft_review_saved is not None)
    check("مسودة صيغت للمرشح المزدوج (صغ واعرض تغلب)", both_review_saved is not None)
    if draft_review_saved:
        check("review_issue للمسودة الثانية مربوط بالـ Issue المفتوح",
              draft_review_saved[1].get("review_issue") == 9911,
              str(draft_review_saved[1].get("review_issue")))
    if both_review_saved:
        check("review_issue للمسودة المزدوجة مربوط بالـ Issue المفتوح أيضًا",
              both_review_saved[1].get("review_issue") == 9911)
        check("المزدوج لم يُنشر مباشرة (status ليست published/queued)",
              both_review_saved[1].get("status") not in ("published", "queued"))

    conflict_comments = [
        text for _, text in comment_calls
        if "المربعين معًا" in text
    ]
    check("تنبيه التعارض عُلِّق على Issue الاختيار الأصلي",
          len(conflict_comments) == 1, str(comment_calls))
    if conflict_comments:
        check("تنبيه التعارض يذكر عنوان الخبر لا معرّفه فقط",
              art_both.title in conflict_comments[0]
              and cand_both["id"] not in conflict_comments[0],
              conflict_comments[0])

    rejections_after = feedback.load()
    check("لا تسجيل رفض لأي من الثلاثة (كلهم اختيروا بطريقة أو بأخرى)",
          len(rejections_after) == rejections_before)


def test_preselect_draft_review_image_swap_works() -> None:
    """البند 4: مربع تبديل الصورة يعمل فعليًا في مسار «صغ واعرض» —
    setimage.apply_image يعيد بناء البطاقة على المسودة الناتجة كما في
    المسار العادي تمامًا، بلا أي تعديل في review.py أو setimage.py."""
    from src import collect_finalize, preselect, review, setimage
    from src import publish as publish_mod

    now = datetime.now(timezone.utc)
    art = Article(title="خبر يحتاج تبديل صورته بعد الصياغة",
                 link="https://pre.example/imgswap", summary="",
                 source_name="PI", region="ri", weight=1.0,
                 published=now, bucket="serious", publisher="PI")
    cand = preselect.build_candidate(art)
    store.save_candidate(cand)

    body = preselect.build_selection_issue_body([cand])
    marked = tick_marker(body, f"review:{cand['id']}")

    real_burst = publish_mod.cmd_burst
    real_create_issue = review.create_issue
    real_comment = review.comment
    real_ensure_labels = review.ensure_labels
    real_close_issue = review.close_issue
    publish_mod.cmd_burst = lambda *a, **kw: 0
    review.create_issue = lambda title, body, labels=None: {
        "number": 9922, "html_url": "https://x/issues/9922"}
    review.comment = lambda issue_number, text: None
    review.ensure_labels = lambda: None
    close_issue_calls: list = []
    review.close_issue = lambda issue_number: close_issue_calls.append(issue_number)

    real_repo = os.environ.get("GITHUB_REPOSITORY")
    os.environ["GITHUB_REPOSITORY"] = "user/trendnews"
    try:
        code = collect_finalize.finalize(4344, marked, load_config())
    finally:
        publish_mod.cmd_burst = real_burst
        review.create_issue = real_create_issue
        review.comment = real_comment
        review.ensure_labels = real_ensure_labels
        review.close_issue = real_close_issue
        if real_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo

    check("Issue الاختيار الأصلي أُغلق (لا شيء «انشر فورًا» يبقى معلَّقًا)",
          close_issue_calls == [4344], str(close_issue_calls))

    check("finalize (صغ واعرض فقط) انتهى بنجاح", code == 0, f"exit={code}")
    saved = store.load_draft(cand["id"])
    check("مسودة «صغ واعرض» صيغت فعلًا", saved is not None)
    if not saved:
        return
    old_image = saved[1]["image"]

    updated = setimage.apply_image(cand["id"], "https://cdn.example/new-photo.jpg",
                                   load_config())
    check("setimage.apply_image يعيد بطاقة محدَّثة لمسودة «صغ واعرض»",
          updated is not None)
    if updated:
        check("مسار الصورة تغيّر (نسخة جديدة لا استبدال في مكانه)",
              updated["image"] != old_image, str((updated["image"], old_image)))
        check("has_photo أصبحت True بعد الاستبدال اليدوي", updated["has_photo"] is True)
        reloaded = store.load_draft(cand["id"])
        check("التحديث محفوظ فعليًا في المسودة على القرص",
              reloaded is not None and reloaded[1]["image"] == updated["image"])


# ═══════════ ترجمة عناوين المرشحين دفعة واحدة (Issue #319 البند 3) ═══════════


def test_preselect_translate_titles() -> None:
    """استدعاء Haiku واحد للدفعة كلها، تخطّي العربي أصلًا بعتبة من
    config.yaml، تسجيل عدد المُترجَم والمتخطَّى، وفشل صامت لا يوقف
    المسار (تُعرض العناوين الأصلية بلا ترجمة)."""
    from src import preselect

    class _Block:
        def __init__(self, text):
            self.type = "text"
            self.text = text

    class _Resp:
        def __init__(self, content):
            self.content = content

    class _Messages:
        def __init__(self, resp):
            self._resp = resp
            self.calls = 0

        def create(self, **kw):
            self.calls += 1
            self.last_kwargs = kw
            return self._resp

    class _FakeClient:
        def __init__(self, resp):
            self.messages = _Messages(resp)

    cand_en1 = {"id": "t1", "title": "Volcano erupts in Iceland"}
    cand_en2 = {"id": "t2", "title": "Central bank raises interest rates"}
    cand_ar = {"id": "t3", "title": "زلزال يضرب اليابان"}   # عربي أصلًا — يُتخطّى

    resp = _Resp([_Block(
        '{"translations": {"1": "بركان يثور في آيسلندا", '
        '"2": "البنك المركزي يرفع الفائدة"}}')])
    fake_client = _FakeClient(resp)

    cfg = load_config()
    cfg["preselect"] = {
        "translate": {"enabled": True, "model": "claude-haiku-4-5-20251001",
                      "arabic_skip_ratio": 0.4},
    }

    real_client = preselect._client
    preselect._client = lambda: fake_client
    try:
        translations = preselect.translate_titles(
            [cand_en1, cand_en2, cand_ar], cfg)
    finally:
        preselect._client = real_client

    check("استدعاء واحد فقط للدفعة كلها (لا استدعاء لكل عنوان)",
          fake_client.messages.calls == 1, str(fake_client.messages.calls))
    check("العنوان العربي أصلًا لم يُرسَل ضمن الدفعة",
          "زلزال" not in fake_client.messages.last_kwargs["messages"][0]["content"])
    check("العنوانان الإنجليزيان تُرجما", translations == {
        "t1": "بركان يثور في آيسلندا", "t2": "البنك المركزي يرفع الفائدة"})
    check("العنوان العربي أصلًا بلا ترجمة (تُخطّي لا فشل)", "t3" not in translations)

    # عتبة arabic_skip_ratio من config.yaml لا من الكود: عتبة 0.0 تعني "لا
    # عنوان غير عربي كفاية للترجمة" — حتى العنوان الإنجليزي البحت (نسبته
    # العربية 0.0) يُستبعد لأن الفحص شرطه < العتبة لا ≤، فيثبت أن العتبة
    # الفعلية المستخدمة هي قيمة config.yaml لا القيمة الافتراضية 0.4 التي
    # كانت سترسله.
    cfg_zero = load_config()
    cfg_zero["preselect"] = {"translate": {"enabled": True, "arabic_skip_ratio": 0.0}}
    fake_client2 = _FakeClient(_Resp([_Block('{"translations": {}}')]))
    preselect._client = lambda: fake_client2
    try:
        result_zero = preselect.translate_titles([cand_en1], cfg_zero)
    finally:
        preselect._client = real_client
    check("عتبة arabic_skip_ratio=0.0 من config.yaml تمنع حتى الإنجليزي من الترجمة",
          fake_client2.messages.calls == 0 and result_zero == {},
          str((fake_client2.messages.calls, result_zero)))

    # تعطيل الترجمة من config.yaml بلا أي تعديل كود
    cfg_off = load_config()
    cfg_off["preselect"] = {"translate": {"enabled": False}}
    check("enabled: false لا يستدعي أي عميل",
          preselect.translate_titles([cand_en1], cfg_off) == {})

    # فشل الاستدعاء (عطل API) لا يوقف المسار — يعيد {} بصمت
    def _raise(*a, **kw):
        raise RuntimeError("متغير البيئة ANTHROPIC_API_KEY غير موجود")

    preselect._client = _raise
    try:
        result = preselect.translate_titles([cand_en1], cfg)
    finally:
        preselect._client = real_client
    check("فشل الاستدعاء يعيد {} بصمت بلا استثناء يوقف المسار", result == {})


def test_finalize_format_mismatch_no_silent_fail() -> None:
    """جسم Issue بلا أي معرّف <!-- cand:ID --> إطلاقًا (صيغة "مسودات" لا
    "مرشحين" — أحد أعراض Issue #296: وسم pending-selection على Issue من
    نوع آخر) يجب ألا يُعامَل كأن المراجع لم يعلّم شيئًا. يجب تعليق سبب
    واضح وعدم إزالة approved — إزالته كانت ستُخفي العطل صامتًا."""
    from src import collect_finalize, review

    comment_calls, remove_label_calls = [], []
    real_comment = review.comment
    real_remove_label = review.remove_label
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))
    review.remove_label = lambda issue_number, label: remove_label_calls.append(
        (issue_number, label))

    body = "- [x] **1. عنوان مسودة عادية جاهزة للنشر**  <!-- draft:abc123 -->"

    try:
        code = collect_finalize.finalize(6161, body, load_config())
    finally:
        review.comment = real_comment
        review.remove_label = real_remove_label

    check("finalize يعيد رمز فشل عند عدم تطابق الصيغة", code != 0, f"exit={code}")
    check("تعليق بسبب واضح يذكر «صيغة»",
          bool(comment_calls) and comment_calls[0][0] == 6161
          and "صيغة" in comment_calls[0][1], str(comment_calls))
    check("approved لا يُزال عند عدم تطابق الصيغة (لا يُخفى العطل)",
          remove_label_calls == [])


def test_publish_conflicting_labels_no_dispatch() -> None:
    """Issue يحمل pending-selection وpending-review معًا (Issue #296) —
    التفويض القديم كان يفوز لـ pending-selection بلا شرط، فيتجاهل
    pending-review بصمت. الآن يُرفض الحسم التلقائي وتُعلَّق تنبيه صريح."""
    from src import publish
    from src import collect_finalize as cf_mod
    from src import review

    real_fetch = publish.fetch_issue
    publish.fetch_issue = lambda n: {
        "number": n,
        "body": "لا يهم لهذا الاختبار",
        "labels": [{"name": "pending-selection"}, {"name": "pending-review"},
                   {"name": "approved"}],
    }

    comment_calls: list = []
    real_comment = review.comment
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))

    finalize_calls: list = []
    real_finalize = cf_mod.finalize
    cf_mod.finalize = lambda *a, **kw: finalize_calls.append(1) or 0

    sys.argv = ["publish", "--issue", "9001"]
    try:
        code = publish.main()
    finally:
        publish.fetch_issue = real_fetch
        review.comment = real_comment
        cf_mod.finalize = real_finalize

    check("publish يرفض التفويض عند تعارض الوسمين", code != 0, f"exit={code}")
    check("لا استدعاء لـ collect_finalize.finalize", finalize_calls == [])
    check("تعليق تنبيه صريح على الـ Issue بدل الصمت",
          len(comment_calls) == 1 and comment_calls[0][0] == 9001)


def test_writer_classifies_write_errors() -> None:
    """Issue #308 البند 1: تصنيف سبب فشل الصياغة التقني — دالة مستقلة قابلة
    للاختبار بلا شبكة ولا عميل Anthropic حقيقي."""
    from src.writer import classify_write_error

    check("رسالة سقف الإنفاق تُصنَّف بدقة",
          classify_write_error(
              Exception("You have reached your specified API usage limits"))
          == "سقف الإنفاق")
    check("رسالة رصيد منخفض تُصنَّف كسقف إنفاق أيضًا",
          classify_write_error(Exception("Your credit balance is too low"))
          == "سقف الإنفاق")
    check("عطل API عام بلا إشارة لسقف الإنفاق يُصنَّف عامًا",
          classify_write_error(Exception("Internal server error, try again"))
          == "عطل API")


def test_finalize_external_failure_keeps_approved_no_feedback() -> None:
    """Issue #308 البند 1+2: فشل الصياغة لعطل خارجي (سقف إنفاق/API) يجب أن
    يذكر السبب صراحة في التعليق، يُبقي وسم approved (لا يُخفي العطل بإزالته
    وكأنه رفض تحريري)، ولا يُسجَّل المرشح المعتمد في feedback — العطل عارض
    تقني لا قرار بشري، وتسجيله يعلّم الفرز الأولي درسًا خاطئًا."""
    from src import collect_finalize, feedback, preselect, review
    from src.writer import WriteFailure

    now = datetime.now(timezone.utc)
    art_d = Article(title="خبر رابع يصطدم بسقف الإنفاق عند الصياغة",
                    link="https://pre.example/d", summary="", source_name="P4",
                    region="r4", weight=1.0, published=now, bucket="serious",
                    publisher="P4")
    cand_d = preselect.build_candidate(art_d)
    store.save_candidate(cand_d)

    body = preselect.build_selection_issue_body([cand_d])
    marked = tick_marker(body, f"now:{cand_d['id']}")

    comment_calls, remove_label_calls = [], []
    real_comment = review.comment
    real_remove_label = review.remove_label
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))
    review.remove_label = lambda issue_number, label: remove_label_calls.append(
        (issue_number, label))

    real_write = collect_finalize.write_arabic

    def _raise_write_failure(*a, **kw):
        raise WriteFailure("سقف الإنفاق",
                           "You have reached your specified API usage limits")

    collect_finalize.write_arabic = _raise_write_failure

    rejections_before = len(feedback.load())

    try:
        code = collect_finalize.finalize(8001, marked, load_config())
    finally:
        collect_finalize.write_arabic = real_write
        review.comment = real_comment
        review.remove_label = real_remove_label

    check("finalize يعيد رمز فشل عند عطل خارجي", code != 0, f"exit={code}")
    check("approved لا يُزال عند فشل خارجي", remove_label_calls == [])
    check("التعليق يذكر السبب صراحة (سقف الإنفاق)",
          bool(comment_calls) and "سقف الإنفاق" in comment_calls[0][1],
          str(comment_calls))
    check("لا تسجيل جديد في feedback عند فشل خارجي",
          len(feedback.load()) == rejections_before)

    updated_d = store.load_candidate(cand_d["id"])
    check("حالة المرشح لم تتحوّل إلى write_failed عند عطل خارجي",
          updated_d and updated_d[1]["status"] == "pending",
          str(updated_d[1]["status"] if updated_d else None))


def test_finalize_editorial_rejection_removes_approved() -> None:
    """Issue #308 البند 1+2 (تباين ضابط): الرفض التحريري البحت (newsworthy
    =false، يعاد None بلا استثناء) يبقى بالسلوك السابق — يُزال approved
    لأنه قرار بشري منته يحتاج اختيار مرشح آخر، لا عطل يستحق إعادة محاولة."""
    from src import collect_finalize, preselect, review

    now = datetime.now(timezone.utc)
    art_e = Article(title="خبر خامس يرفضه النموذج تحريريًا",
                    link="https://pre.example/e", summary="", source_name="P5",
                    region="r5", weight=1.0, published=now, bucket="light",
                    publisher="P5")
    cand_e = preselect.build_candidate(art_e)
    store.save_candidate(cand_e)

    body = preselect.build_selection_issue_body([cand_e])
    marked = tick_marker(body, f"now:{cand_e['id']}")

    comment_calls, remove_label_calls = [], []
    real_comment = review.comment
    real_remove_label = review.remove_label
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))
    review.remove_label = lambda issue_number, label: remove_label_calls.append(
        (issue_number, label))

    real_write = collect_finalize.write_arabic
    collect_finalize.write_arabic = lambda *a, **kw: None

    try:
        code = collect_finalize.finalize(8002, marked, load_config())
    finally:
        collect_finalize.write_arabic = real_write
        review.comment = real_comment
        review.remove_label = real_remove_label

    check("finalize ينتهي بنجاح عند رفض تحريري بحت", code == 0, f"exit={code}")
    check("approved يُزال عند رفض تحريري (قرار بشري لا عطل)",
          remove_label_calls == [(8002, "approved")])
    check("التعليق لا يذكر سببًا خارجيًا",
          bool(comment_calls) and "سقف الإنفاق" not in comment_calls[0][1]
          and "عطل API" not in comment_calls[0][1], str(comment_calls))

    updated_e = store.load_candidate(cand_e["id"])
    check("حالة المرشح write_failed عند رفض تحريري",
          updated_e and updated_e[1]["status"] == "write_failed",
          str(updated_e[1]["status"] if updated_e else None))


def test_publish_pending_selection_single_dispatch() -> None:
    """Issue #308 البند 3 (الأهم): publish.yml يُشغّل مساري urgent وnormal
    لنفس حدث وسم approved معًا — كلاهما يستدعي publish.main() لنفس Issue
    pending-selection. finalize لا يميّز عاجلًا من عادي داخليًا (ينشر
    الاثنين معًا في تفويضة واحدة)، فتنفيذه مرتين يعني صياغة الخبر ونشره
    مرتين فعليًا لو نجحا معًا. مسار العادي (--skip-urgent) يجب أن يتخطّى
    finalize تمامًا ويترك المسار السريع (بلا --skip-urgent) ينفّذه وحده."""
    from src import publish
    from src import collect_finalize as cf_mod

    real_fetch = publish.fetch_issue
    publish.fetch_issue = lambda n: {
        "number": n,
        "body": "لا يهم لهذا الاختبار",
        "labels": [{"name": "pending-selection"}, {"name": "approved"}],
    }

    finalize_calls: list = []
    real_finalize = cf_mod.finalize
    cf_mod.finalize = lambda *a, **kw: finalize_calls.append(1) or 0

    try:
        # محاكاة تشغيلتي publish.yml لنفس حدث الوسم: العاجل أولًا (بلا
        # skip-urgent)، ثم العادي (needs: urgent) بـ --skip-urgent
        sys.argv = ["publish", "--issue", "7001", "--urgent-only"]
        code_urgent = publish.main()
        sys.argv = ["publish", "--issue", "7001", "--skip-urgent"]
        code_normal = publish.main()
    finally:
        publish.fetch_issue = real_fetch
        cf_mod.finalize = real_finalize

    check("مسار العاجل ينتهي بنجاح", code_urgent == 0, f"exit={code_urgent}")
    check("مسار العادي يتخطّى بنجاح بلا خطأ", code_normal == 0, f"exit={code_normal}")
    check("finalize نُفِّذ مرة واحدة فقط رغم تشغيل المسارين معًا",
          finalize_calls == [1], str(finalize_calls))


def test_arabic_shaping() -> None:
    from PIL import ImageDraw as _D

    cfg = load_config()
    canvas = Image.new("RGB", (10, 10))
    draw = _D.Draw(canvas)
    font = imaging.load_font(cfg.path("image.font_headline"), 60)

    check("محرك التشكيل Raqm متاح", imaging.HAS_RAQM)

    # الحروف الموصولة أضيق بكثير من المنفصلة — إثبات أن الوصل يعمل
    connected = imaging.measure(draw, "ببببب", font)[0]
    separate = sum(imaging.measure(draw, "ب", font)[0] for _ in range(5))
    check("الحروف العربية تتصل", connected < separate * 0.75,
          f"{connected} مقابل {separate}")

    # لا محرف خارج تغطية الخط (وإلا ظهرت مربعات)
    from fontTools.ttLib import TTFont
    cmap = set(TTFont(str(imaging.resolve(cfg.path("image.font_headline"))))
               .getBestCmap())
    sample = "ترامب يصعّد ضد إيران والمفاوضات النووية 2026 %"
    missing = [c for c in sample if ord(c) not in cmap]
    check("لا محارف مفقودة في الخط", not missing, str(missing))

    long_text = "هذا عنوان طويل جدًا يجب أن يُقسّم على عدة أسطر داخل الصورة بشكل صحيح"
    lines = imaging.wrap(draw, long_text, font, 600)
    check("تقسيم الأسطر يعمل", len(lines) >= 2, f"{len(lines)} سطر")
    check("لا كلمة مفقودة بعد التقسيم",
          " ".join(lines).split() == long_text.split())


# ═══════════ اختبارات الجدولة والتعليق الأول والتغذية الراجعة ═══════════


def test_manual_image() -> None:
    """صورة يدوية: أمر التعليق، ومسار جديد، وتلميح في الـ Issue."""
    from src import review, setimage

    cmds = setimage.parse_commands(
        "ممتاز /صورة a1b2c3d4e5f6 https://ex.com/p.jpg شكرًا")
    check("الأمر يُقرأ من وسط التعليق",
          cmds == [("a1b2c3d4e5f6", "https://ex.com/p.jpg")])
    check("الصيغة الإنجليزية مقبولة",
          setimage.parse_commands("/image abc123def456 https://ex.com/x.png")
          == [("abc123def456", "https://ex.com/x.png")])
    check("القوس اللاصق يُقصّ من الرابط",
          setimage.parse_commands("(/صورة abc123def456 https://ex.com/x.png)")
          [0][1].endswith(".png"))
    check("التعليق بلا أمر لا يُنتج شيئًا",
          setimage.parse_commands("صورة جميلة جدًا") == [])

    check("المسار الجديد لا يستبدل القديم",
          setimage.next_image_path("drafts/d/ab.jpg") == "drafts/d/ab-v2.jpg")
    check("النسخ تتتابع",
          setimage.next_image_path("drafts/d/ab-v2.jpg") == "drafts/d/ab-v3.jpg")

    base = {"id": "abc123def456", "score": 9.0, "caption": "متن",
            "image": "drafts/d/abc123def456.jpg", "bucket": "serious",
            "source": {"link": "https://x/1", "publishers": ["BBC"]},
            "arabic": {"post_title": "عنوان", "category": "سياسة"}}

    body = review.build_issue_body([{**base, "has_photo": False}], "u/r")
    check("مربع الاستبدال معروض", "<!-- img:abc123def456 -->" in body)
    check("فراغ الرابط معروض", "<!-- imgurl:abc123def456 -->" in body)
    check("المربع قابل للنقر (خارج <details>)",
          any("- [ ]" in ln and "img:abc123def456" in ln
              for ln in body.splitlines()))
    check("تنبيه غياب الصورة يظهر", "بلا صورة للخبر" in body)
    check("لا تنبيه حين توجد صورة",
          "بلا صورة للخبر" not in
          review.build_issue_body([{**base, "has_photo": True}], "u/r"))

    check("المربع الفارغ لا يُنفَّذ", review.parse_image_requests(body) == [])
    ticked = body.replace("- [ ] 🖼️ استبدل", "- [x] 🖼️ استبدل")
    check("مربع معلَّم بلا رابط يُهمَل",
          review.parse_image_requests(ticked) == [])

    filled = ticked.replace(
        "الرابط:   <!-- imgurl:abc123def456 -->",
        "الرابط: https://cdn.site/p.jpg  <!-- imgurl:abc123def456 -->")
    check("المربع المعلَّم مع الرابط يُنفَّذ",
          review.parse_image_requests(filled)
          == [("abc123def456", "https://cdn.site/p.jpg")])

    # اللصق قبل العلامة أو بعدها — كلاهما يعمل على الهاتف
    after = ticked.replace(
        "الرابط:   <!-- imgurl:abc123def456 -->",
        "الرابط: <!-- imgurl:abc123def456 --> https://cdn.site/p.jpg")
    check("موضع اللصق لا يهم",
          review.parse_image_requests(after)
          == [("abc123def456", "https://cdn.site/p.jpg")])

    cleared = review.clear_image_request(filled, "abc123def456")
    check("المربع يُفرَّغ بعد التنفيذ",
          review.parse_image_requests(cleared) == [])
    check("الفراغ يُنظَّف من الرابط", "cdn.site" not in cleared)
    kept = review.clear_image_request(filled, "abc123def456", keep_url=True)
    check("الرابط يبقى عند الفشل ليصحَّح", "cdn.site" in kept)
    check("لا تكرار عند الفشل", review.parse_image_requests(kept) == [])


def test_request_search() -> None:
    """الطلب اليدوي: كلمات → بحث → مرشحون."""
    from src import request as rq

    feeds = rq.search_feeds("زلزال هرات", 7, rq.DEFAULT_LOCALES)
    check("لكل لغة خلاصة بحث", len(feeds) == len(rq.DEFAULT_LOCALES))
    check("النافذة الزمنية داخل الاستعلام",
          all("when%3A7d" in f["url"] for f in feeds))
    check("الاستعلام مُرمَّز في الرابط",
          all("news.google.com/rss/search" in f["url"] for f in feeds))

    # البند 5 (تعليق التنفيذ على PR #340): days=None يُسقط قيد when: تمامًا
    # — واقعة مرجعية (verify.py) مصدرها المؤيِّد قد يكون بعمر الواقعة نفسها
    feeds_unrestricted = rq.search_feeds("كتاب صدر 2009", None, rq.DEFAULT_LOCALES)
    check("days=None يبني استعلامًا بلا قيد when: إطلاقًا",
          all("when%3A" not in f["url"] for f in feeds_unrestricted),
          [f["url"] for f in feeds_unrestricted])

    # التطبيع العربي: أل التعريف والهمزة والتاء المربوطة لا تفرّق
    check("أل التعريف تُسقط",
          "زلزال" in rq.norm_tokens("الزلزال"))
    check("الهمزة تُطبَّع",
          rq.norm_tokens("إسرائيل") == rq.norm_tokens("اسرائيل"))
    check("حروف الجر تُستبعد", "على" not in rq.norm_tokens("على الحدود"))

    wanted = rq.norm_tokens("زلزال هرات")
    art = Article(title="زلزال قوي يضرب هرات", link="https://x/1", summary="",
                  source_name="s", region="global", weight=1.0,
                  published=datetime.now(timezone.utc))
    off = Article(title="ارتفاع أسعار النفط", link="https://x/2", summary="",
                  source_name="s", region="global", weight=1.0,
                  published=datetime.now(timezone.utc))
    latin = Article(title="Strong earthquake hits Herat", link="https://x/3",
                    summary="", source_name="s", region="global", weight=1.0,
                    published=datetime.now(timezone.utc))
    check("المطابق يمرّ", rq.relevant(art, wanted, 1))
    check("غير المطابق يُستبعد", not rq.relevant(off, wanted, 1))
    check("اختلاف اللغة لا يُسقط النتيجة", rq.relevant(latin, wanted, 1))

    # البحث كاملًا بخلاصة مُصطنعة — بلا شبكة
    cfg = load_config()
    original = rq.fetch_source
    rq.fetch_source = lambda src, max_age_hours: [art, off]
    try:
        found = rq.find("زلزال هرات", cfg, days=7)
    finally:
        rq.fetch_source = original
    titles = [a.title for a in found]
    check("نتيجة الطلب مرشّحة", "زلزال قوي يضرب هرات" in titles)
    check("غير المطابق لا يصل للترتيب", "ارتفاع أسعار النفط" not in titles)

    check("نافذة الطلب أوسع من نافذة الدورة",
          int((load_config().get("request", {}) or {}).get("days", 7)) * 24
          > int((cfg.get("selection", {}) or {}).get("max_age_hours", 18)))


def test_verify() -> None:
    """مسار التحقق: استخراج الادعاءات وتصنيفها، وحكم سلبي واضح بلا مصادر."""
    import json

    from src import verify

    real_search = verify.search  # يُستعاد قبل أي اختبار يحتاج البحث الحقيقي
    real_gather_evidence = verify.gather_evidence  # يُستعاد قبل اختبار التوسيع الحقيقي
    # الأربعة التالية تُستبدل مرارًا أدناه بمحاكاة (claims/judge_fact/
    # judge_question ثابتة، وعميل Anthropic مزيَّف) ولا تُستعمل بشكلها
    # الحقيقي مجددًا داخل test_verify نفسها — لكن تُستعاد صراحةً في نهاية
    # الدالة حتى لا يبقى verify معطوبًا لأي اختبار لاحق في الدفعة يستعملها
    # (نمط ضُبط عليه الاختبار سابقًا مرتين: verify.search على _boom،
    # وverify.gather_evidence على lambda ثابتة — كلاهما مرّ زيفًا).
    real_extract_claims = verify.extract_claims
    real_judge_fact = verify.judge_fact
    real_judge_question = verify.judge_question
    real_client = verify._client

    # التصنيف بكود لا بالنموذج — يجب أن يكون حتميًا وقابلًا للاختبار وحده.
    # وزنان معروفان (BBC/Reuters ≥ near_confirm_min_weight) في كل استدعاء
    # هنا يُبقيان مسار "مؤكَّدة" كما كان قبل البند 4 أدناه — وهو ما يُختبر
    # على حدة بأوزان مجهولة عمدًا
    KNOWN_WEIGHTS = {"BBC": 1.0, "Reuters": 1.0}
    check("تصنيف: مصدران مستقلان فأكثر = مؤكدة",
          verify.classify_fact(["BBC", "Reuters"], [], 2, KNOWN_WEIGHTS) ==
          verify.STATUS_CONFIRMED)
    check("تصنيف: مصدر واحد",
          verify.classify_fact(["BBC"], [], 2) == verify.STATUS_SINGLE)
    check("تصنيف: لا مصدر",
          verify.classify_fact([], [], 2) == verify.STATUS_NONE)
    check("تصنيف: يخالفها مصدر رغم مصدر مؤيد واحد",
          verify.classify_fact(["BBC"], ["Reuters"], 2) == verify.STATUS_CONTRADICTED)
    check("تكرار الاسم نفسه لا يرفع العدد فوق العتبة",
          verify.classify_fact(["BBC", "BBC"], [], 2) == verify.STATUS_SINGLE)

    # البند 2 (تعليق التنفيذ على Issue #339): مصدران كافيان للتأكيد لكن
    # مصدرًا ثالثًا يخالف — كانت تُرجع STATUS_CONFIRMED بصمت بلا أثر
    # للاعتراض؛ الحالة الرابعة الصريحة تحمل الفارق، وverify_draft.attempt
    # يفلتر status == STATUS_CONFIRMED حرفيًا فتُستبعد هذه الحالة تلقائيًا
    check("مصدران كافيان مع مصدر مخالف ثالث ← مؤكَّدة مع اعتراض مصدر، لا "
          "مؤكَّدة بصمت",
          verify.classify_fact(["BBC", "Reuters"], ["أخبار الغد"], 2, KNOWN_WEIGHTS) ==
          verify.STATUS_CONFIRMED_DISPUTED)
    check("مؤكَّدة مع اعتراض مصدر حالة مختلفة عن مؤكَّدة العادية",
          verify.STATUS_CONFIRMED_DISPUTED != verify.STATUS_CONFIRMED)
    check("مصدران كافيان بلا أي اعتراض يبقيان مؤكَّدة عادية (لا تغيير سلوك)",
          verify.classify_fact(["BBC", "Reuters"], [], 2, KNOWN_WEIGHTS) ==
          verify.STATUS_CONFIRMED)

    # العلاج 4 (Issue #132 تعليق لاحق): حالة وسيطة بين "مؤكَّدة" و"مصدر واحد"
    # — مصدر واحد فقط، لكنه "قوي" (وزنه ≥ near_confirm_min_weight) لا يُخفى
    # خلف "مصدر واحد" المبهمة نفسها التي تُستعمل لمصدر مجهول واحد
    check("مصدر واحد قوي (وزن ≥ near_confirm_min_weight) عند حافة العتبة "
          "← شبه مؤكَّدة لا مصدر واحد مبهمة",
          verify.classify_fact(["Bloomberg"], [], 2, {"Bloomberg": 3.0}) ==
          verify.STATUS_NEAR_CONFIRMED)
    check("مصدر واحد دون العتبة (وزن افتراضي لناشر مجهول) يبقى مصدر واحد",
          verify.classify_fact(["موقع مجهول"], [], 2, {"موقع مجهول": 0.6}) ==
          verify.STATUS_SINGLE)
    check("بلا قاموس أوزان أصلًا (توافق خلفي)، المصدر الواحد يبقى مصدر واحد",
          verify.classify_fact(["BBC"], [], 2) == verify.STATUS_SINGLE)
    check("عتبة الوزن الوسيطة قابلة للتحكم عبر near_confirm_min_weight",
          verify.classify_fact(["ناشر متوسط"], [], 2, {"ناشر متوسط": 0.9},
                               near_confirm_min_weight=0.9) ==
          verify.STATUS_NEAR_CONFIRMED)
    check("مصدران فأكثر بمصدر معروف واحد بينهما يتجاوزان الحالة الوسيطة "
          "إلى مؤكَّدة مباشرة",
          verify.classify_fact(["BBC", "Reuters"], [], 2,
                               {"BBC": 3.0, "Reuters": 3.0}) ==
          verify.STATUS_CONFIRMED)

    # البند 4 (تعليق التنفيذ على PR #340): بلوغ العدد وحده لا يكفي —
    # شرط إضافي "مصدر معروف واحد على الأقل" بإعادة استعمال
    # near_confirm_min_weight، لا حد أدنى لمجموع الأوزان (مجموع مصادر
    # مجهولة يعوّض الكمّ عن الجهالة، وهذا بالضبط ما يُمنع هنا)
    check("مصدران فأكثر كلاهما مجهول الوزن ← شبه مؤكَّدة لا مؤكَّدة كاملة "
          "رغم كفاية العدد",
          verify.classify_fact(["موقع أول", "موقع ثانٍ"], [], 2,
                               {"موقع أول": 0.6, "موقع ثانٍ": 0.6}) ==
          verify.STATUS_NEAR_CONFIRMED)
    check("ثلاثة مصادر مجهولة الوزن (مجموع أوزان مرتفع) تبقى دون مؤكَّدة "
          "كاملة — العدد وحده لا يعوّض غياب مصدر معروف",
          verify.classify_fact(["أ", "ب", "جـ"], [], 2,
                               {"أ": 0.6, "ب": 0.6, "جـ": 0.6}) ==
          verify.STATUS_NEAR_CONFIRMED)
    check("مصدر معروف واحد بين عدة مصادر مجهولة يكفي للمؤكَّدة الكاملة",
          verify.classify_fact(["Bloomberg", "موقع مجهول"], [], 2,
                               {"Bloomberg": 3.0, "موقع مجهول": 0.6}) ==
          verify.STATUS_CONFIRMED)
    check("بلا قاموس أوزان أصلًا (توافق خلفي)، عدد كافٍ من المصادر ينزل "
          "لشبه مؤكَّدة لا مؤكَّدة كاملة",
          verify.classify_fact(["موقع أول", "موقع ثانٍ"], [], 2) ==
          verify.STATUS_NEAR_CONFIRMED)
    check("عدد كافٍ بلا مصدر معروف مع اعتراض حقيقي ← يخالفها مصدر، لا "
          "شبه مؤكَّدة ولا مؤكَّدة مع اعتراض",
          verify.classify_fact(["موقع أول", "موقع ثانٍ"], ["Reuters"], 2,
                               {"موقع أول": 0.6, "موقع ثانٍ": 0.6, "Reuters": 1.0}) ==
          verify.STATUS_CONTRADICTED)

    # عتبة العلاج 4 الافتراضية (Issue #132 تعليق لاحق تالٍ): 1.0 لم تكن
    # واقعية — وزن sources في config.yaml يتوزّع فعليًا بين 0.6 و1.3 (0.6
    # لمصدر واحد فقط، "Google News — World"، تطابقًا صدفة مع الوزن الافتراضي
    # DEFAULT_PUBLISHER_WEIGHT — لا يُميَّز عن مجهول، وهذا صحيح دلاليًا: وزنه
    # المضبوط فعلًا لا يفوق مصدر مجهول)؛ بقية القائمة (93 من 94 مصدرًا) تبدأ
    # من 0.7، وكانت عتبة 1.0 تستبعد كل من وزنه 0.7-0.9 فتعامله كمجهول تمامًا.
    # عتبة واقعية مبنية على هذا التوزيع الفعلي: بين DEFAULT_PUBLISHER_WEIGHT
    # (0.6) وأدنى وزن *مميَّز فعليًا عن المجهول* في sources (0.7).
    listed_source_weights = [
        float(s.get("weight", 1.0))
        for s in load_config().get("sources", []) or []]
    min_distinct_source_weight = min(
        w for w in listed_source_weights if w > verify.DEFAULT_PUBLISHER_WEIGHT)
    check("عتبة near_confirm الافتراضية أعلى من وزن الناشر المجهول تمامًا",
          verify.NEAR_CONFIRM_DEFAULT_MIN_WEIGHT > verify.DEFAULT_PUBLISHER_WEIGHT)
    check("عتبة near_confirm الافتراضية أخفض من أدنى وزن ناشر مُدرَج فعليًا "
          "يفوق الوزن الافتراضي — لا تستبعد ناشرًا معروفًا متواضع الوزن كما "
          "فعلت 1.0",
          verify.NEAR_CONFIRM_DEFAULT_MIN_WEIGHT < min_distinct_source_weight,
          f"{verify.NEAR_CONFIRM_DEFAULT_MIN_WEIGHT} >= {min_distinct_source_weight}")
    check("ناشر بأدنى وزن مُدرَج فعليًا يفوق الوزن الافتراضي يُصنَّف شبه مؤكَّد "
          "بالعتبة الافتراضية بلا حاجة لتجاوزها يدويًا (لم يكن ممكنًا عند 1.0)",
          verify.classify_fact(["ناشر متواضع"], [], 2,
                               {"ناشر متواضع": min_distinct_source_weight}) ==
          verify.STATUS_NEAR_CONFIRMED)

    # لا اسم مصدر مختلَق يدخل التقرير — حتى لو ادّعاه ردّ النموذج
    docs = [{"name": "BBC", "text": "x"}, {"name": "Reuters", "text": "y"}]
    check("يُقبل اسم مصدر مُعطى فعلًا", verify._known_only(["BBC"], docs) == ["BBC"])
    check("يُرفض اسم مصدر لم يُعطَ في النصوص",
          verify._known_only(["BBC", "مصدر مختلق"], docs) == ["BBC"])
    check("لا تكرار في القائمة المفلترة",
          verify._known_only(["BBC", "BBC"], docs) == ["BBC"])

    # عطل رُصد فعليًا في السجل (Issue #132 تعليق لاحق): النموذج أيّد واقعة
    # فعلًا لكنه أضاف وصفًا بين قوسين لاسم المصدر —
    # supporting=['جفرا نيوز (نص المقال الكامل)'] بينما docs فيها 'جفرا
    # نيوز' فقط — فالمطابقة الحرفية السابقة حذفت التأييد الحقيقي كله
    # (supporting=[] رغم تأييد صريح). المطابقة الآن متسامحة: تُسقط الوصف
    # بين القوسين وتقارن الكلمات المطبَّعة (request.norm_tokens تتكفّل هي
    # نفسها بالمسافات الزائدة وأل التعريف وفروق الهمزات)، بتطابق جزئي —
    # لكنها تبقى ترفض أسماء لا علاقة لها إطلاقًا.
    docs_jafra = [{"name": "جفرا نيوز", "text": "x"}]
    check("اسم بوصف بين قوسين (عطل Issue #132 الفعلي) يُقبل ويُطابَق بالاسم "
          "الحقيقي لا يُحذف",
          verify._known_only(["جفرا نيوز (نص المقال الكامل)"], docs_jafra) ==
          ["جفرا نيوز"])
    check("_canonical_name يعيد اسم doc الفعلي من docs لا نص النموذج بوصفه",
          verify._canonical_name("BBC News (تقرير مطوّل)",
                                 [{"name": "BBC", "text": "x"}]) == "BBC")
    check("اسم مختلق تمامًا يبقى مرفوضًا رغم التسامح الجديد — الحماية باقية",
          verify._canonical_name("مصدر لا علاقة له بالمرة إطلاقًا",
                                 docs_jafra) is None)
    check("مسافات زائدة وأل التعريف لا تمنع المطابقة",
          verify._canonical_name("  الجفرا   نيوز  ", docs_jafra) == "جفرا نيوز")

    # وزن الناشر لترتيب القراءة وعرضه في التقرير (Issue #132 تعليق لاحق:
    # حكم إيجابي فعلي استند إلى خبرگزاری مهر والخلاصة نت وأهل مصر وVietnam.vn
    # بينما بلومبرغ نفسها ظهرت في نتائج البحث ولم تدخل قائمة المؤيدين)
    _cfg_for_weight = load_config()
    check("_publisher_weight: مصدر في verify.trusted_boost يأخذ الوزن الأقصى",
          verify._publisher_weight("Bloomberg", _cfg_for_weight) ==
          verify.TRUSTED_PUBLISHER_WEIGHT)
    check("_publisher_weight: مصدر في sources (لا يطابق أي اسم في "
          "trusted_boost) يأخذ وزنه المُعرَّف هناك لا الافتراضي ولا الأقصى",
          verify._publisher_weight("Dawn", _cfg_for_weight) == 1.1)
    check("_publisher_weight: ناشر غير مُدرَج في أي من القائمتين (كالمثال "
          "الفعلي 'الخلاصة نت') يأخذ الوزن الافتراضي المتواضع",
          verify._publisher_weight("الخلاصة نت", _cfg_for_weight) ==
          verify.DEFAULT_PUBLISHER_WEIGHT)
    check("الوزن الأقصى أعلى من أي وزن sources الذي أعلى بدوره من الافتراضي",
          verify.TRUSTED_PUBLISHER_WEIGHT > 1.2 > verify.DEFAULT_PUBLISHER_WEIGHT)

    # مرادفات عربية لوكالات trusted_boost (Issue #132 تعليق لاحق: 'الشرق
    # بلومبرغ' لا يطابق 'Bloomberg' حرفيًا — سقطت للوزن الافتراضي رغم كونها
    # بلومبرغ فعليًا؛ حكم إيجابي فعلي فقد بلومبرغ واستند لمصادر ضعيفة بدلًا)
    check("اسم عربي يحوي مرادف وكالة موثوقة (الشرق بلومبرغ ↔ بلومبرغ) يأخذ "
          "وزن الثقة لا الافتراضي",
          verify._publisher_weight("الشرق بلومبرغ", _cfg_for_weight) ==
          verify.TRUSTED_PUBLISHER_WEIGHT)
    check("مقاطع قصيرة جدًا (بي بي سي ← BBC) لا تُسقطها norm_tokens كليًا "
          "بلا مطابقة — احتياط النص الخام يلتقطها",
          verify._publisher_weight("بي بي سي", _cfg_for_weight) ==
          verify.TRUSTED_PUBLISHER_WEIGHT)
    check("مرادف ضمن اسم ناشر أطول (بي بي سي عربي) يُطابَق أيضًا",
          verify._publisher_weight("بي بي سي عربي", _cfg_for_weight) ==
          verify.TRUSTED_PUBLISHER_WEIGHT)

    # ضوابط البرومبت: نفس قاعدة عدم الاستعانة بمعرفة النموذج الخاصة (writer.py)
    check("استخراج البنية لا ينقل جملة حرفية من المقال",
          "لا تنقل جملة من المقال حرفيًا" in verify.EXTRACT_SYSTEM)
    check("الحكم على الوقائع يمنع الاستعانة بمعرفة سابقة",
          "لا تستخدم معرفتك الخاصة" in verify.JUDGE_FACT_SYSTEM)
    # البند 1 (Issue #339): استخراج البنية يفصل مُحدِّدات الإسناد عن جوهر
    # الحدث، وطبقة ثانية في الحكم تشدِّد على أنها تفصيلة تُطابَق لا فارق
    # صياغة — الفصل البنيوي وحده لا يكفي بلا تشديد البرومبت أيضًا (الطلب)
    check("استخراج البنية يفصل مُحدِّدات الإسناد عن ادّعاء الحدث",
          "is_qualifier" in verify.EXTRACT_SYSTEM)
    check("مخطط الاستخراج يفرض حقل is_qualifier",
          "is_qualifier" in verify.EXTRACT_SCHEMA["input_schema"]["properties"]
          ["claims"]["items"]["required"])
    check("الحكم على الوقائع يشدِّد على أن مُحدِّد الإسناد تفصيلة تُطابَق",
          "مُحدِّدات الإسناد" in verify.JUDGE_FACT_SYSTEM)
    # البند 5 (تعليق التنفيذ على PR #340): استخراج البنية يميّز الوقائع
    # المرجعية (لا تتعلق بدورة الأخبار الحالية) عبر حقل is_reference منفصل
    check("استخراج البنية يميّز الوقائع المرجعية عن الأخبار الجارية",
          "is_reference" in verify.EXTRACT_SYSTEM)
    check("مخطط الاستخراج يفرض حقل is_reference",
          "is_reference" in verify.EXTRACT_SCHEMA["input_schema"]["properties"]
          ["claims"]["items"]["required"])
    check("الإجابة عن الأسئلة تشترط النسبة لا الحقيقة المطلقة",
          "انسب الجواب لمن قاله" in verify.JUDGE_QUESTION_SYSTEM)
    check("تصنيفات الادعاء الثلاثة متاحة",
          set(verify.CLAIM_KINDS) == {"واقعة", "رأي", "تنبؤ"})

    # تطبيع شكل رد النموذج (Issue #134: claims وصلت كقائمة نصوص لا قواميس
    # فانهار verify.py:344 بـ AttributeError) — لا يُفترض شكل بلا تحقق
    check("نص مجرد يصير قاموس ادّعاء بحقول افتراضية (entities فارغة، "
          "is_qualifier=False, is_reference=False)",
          verify.normalize_claim("ادّعاء بلا شكل") ==
          {"text": "ادّعاء بلا شكل", "kind": "واقعة", "entities": [],
           "is_qualifier": False, "is_reference": False})
    check("قاموس ناقص حقل kind يُملأ بقيمة افتراضية",
          verify.normalize_claim({"text": "ادّعاء"}) ==
          {"text": "ادّعاء", "kind": "واقعة", "entities": [],
           "is_qualifier": False, "is_reference": False})
    check("قاموس بقيمة kind غير معروفة يُصحَّح لا يُرفَض",
          verify.normalize_claim({"text": "ادّعاء", "kind": "شيء غريب"}) ==
          {"text": "ادّعاء", "kind": "واقعة", "entities": [],
           "is_qualifier": False, "is_reference": False})
    check("عنصر بلا نص قابل للاستخراج (رقم مثلًا) يُستبعد بلا انهيار",
          verify.normalize_claim(42) is None)

    # العلاج 2 (Issue #132 تعليق لاحق): حقل entities الجديد — نص خام يُقبل،
    # عناصر غير نصية أو الحقل كله بشكل غريب يُهمَل بلا انهيار (قائمة فارغة)
    check("entities كقائمة نصوص صالحة تُطبَّع كما هي (بلا فراغات زائدة)",
          verify.normalize_claim(
              {"text": "ادّعاء", "kind": "واقعة",
               "entities": [" بلومبرغ ", "2026", ""]})["entities"] ==
          ["بلومبرغ", "2026"])
    check("entities بشكل غير قائمة (نص مجرد مثلًا) تُهمَل بلا انهيار",
          verify.normalize_claim(
              {"text": "ادّعاء", "kind": "واقعة", "entities": "بلومبرغ"}
          )["entities"] == [])
    check("entities تحوي عناصر غير نصية تُستبعد بلا انهيار",
          verify.normalize_claim(
              {"text": "ادّعاء", "kind": "واقعة", "entities": ["بلومبرغ", 2026, None]}
          )["entities"] == ["بلومبرغ"])

    # البند 1 (Issue #339): حقل is_qualifier — يفصل مُحدِّد الإسناد/اليقين
    # ("رسميًا"...) عن ادّعاء الحدث نفسه (انظر verify_draft._central_fact)
    check("is_qualifier: true صريحة تُقبل كما هي",
          verify.normalize_claim(
              {"text": "الانضمام معلَن رسميًا", "kind": "واقعة",
               "is_qualifier": True})["is_qualifier"] is True)
    check("is_qualifier غائبة تُطبَّع إلى False (توافق خلفي، لا مُحدِّد بلا حقل)",
          verify.normalize_claim({"text": "ادّعاء", "kind": "واقعة"}
                                 )["is_qualifier"] is False)
    check("is_qualifier بشكل غريب (نص لا bool) تُطبَّع إلى False بلا انهيار",
          verify.normalize_claim(
              {"text": "ادّعاء", "kind": "واقعة", "is_qualifier": "true"}
          )["is_qualifier"] is False)

    # البند 5 (تعليق التنفيذ على PR #340): حقل is_reference — واقعة مرجعية
    # (سنة صدور كتاب، تاريخ معاهدة...) تُبحث بلا قيد when: (انظر verify.search)
    check("is_reference: true صريحة تُقبل كما هي",
          verify.normalize_claim(
              {"text": "صدر الكتاب عام 2009", "kind": "واقعة",
               "is_reference": True})["is_reference"] is True)
    check("is_reference غائبة تُطبَّع إلى False (توافق خلفي، لا واقعة "
          "مرجعية بلا حقل)",
          verify.normalize_claim({"text": "ادّعاء", "kind": "واقعة"}
                                 )["is_reference"] is False)
    check("is_reference بشكل غريب (نص لا bool) تُطبَّع إلى False بلا انهيار",
          verify.normalize_claim(
              {"text": "ادّعاء", "kind": "واقعة", "is_reference": "true"}
          )["is_reference"] is False)

    check("normalize_claims على قيمة ليست قائمة أصلًا لا تنهار",
          verify.normalize_claims("ليست قائمة") == [])
    check("normalize_claims على None لا تنهار", verify.normalize_claims(None) == [])
    check("normalize_question يقبل سؤالًا كقاموس أيضًا",
          verify.normalize_question({"question": "لماذا؟"}) == "لماذا؟")
    check("normalize_questions على قيمة ليست قائمة لا تنهار",
          verify.normalize_questions(None) == [])
    check("_known_only على قيمة supporting ليست قائمة لا تنهار",
          verify._known_only("BBC", docs) == [])

    cfg = load_config()

    # استعلام البحث كلمات مفتاحية قصيرة لا الجملة كاملة (Issue #132 تعليق
    # لاحق: ثماني وقائع شهيرة عادت كلها "لا مصدر" لأن الاستعلام كان نص
    # الادّعاء الكامل — جملة طويلة لا تُطابق أي نتيجة في بحث Google News)
    long_claim = ("انخفضت واردات الولايات المتحدة من النفط الخام السعودي "
                  "إلى الصفر طوال شهر يوليو 2026 بأكمله، وفقا لتقرير بلومبرغ")
    # legacy_sort=True: هذه الحزمة تختبر السلوك القديم (أرقام أولًا ثم أطول
    # الكلمات) الذي بقي محجوزًا حصرًا لـ verify.py:779 (سؤال بلا entities —
    # مسار متقاعد ينتظر الحذف، تعليق الموافقة الثالث على Issue #361، البند
    # 1). الافتراضي الجديد يحفظ ترتيب الورود بلا فصل الأرقام — مُختبَر في
    # test_evidence أدناه.
    query = verify.build_query(long_claim, legacy_sort=True)
    check("الاستعلام المولَّد لا يتجاوز 5 كلمات مفتاحية",
          1 <= len(query.split()) <= 5)
    check("الاستعلام المولَّد أقصر بوضوح من الجملة الأصلية",
          len(query) < len(long_claim))
    check("الرقم المميز (السنة) يدخل الاستعلام (legacy_sort)", "2026" in query.split())
    check("سقف الكلمات قابل للتحكم عبر max_words",
          len(verify.build_query(long_claim, max_words=2).split()) <= 2)
    check("نص فارغ لا ينهار بناء الاستعلام", verify.build_query("") == "")

    # عطل ثانٍ رُصد فعليًا في الإنتاج (Issue #132 تعليق لاحق): استعلامات
    # ركيكة مثل 'بلومبرغ لتقرير للتاكد محتواه اليه' — كلمات حشو طويلة
    # تُزاحم أسماء الأعلام، وتطبيع الهمزات يفسد الإملاء الحرفي
    check("اسم العلم (بلومبرغ) يدخل الاستعلام لا كلمات الحشو الأطول (legacy_sort)",
          "بلومبرغ" in query.split())
    check("كلمات الحشو والإسناد لا تدخل الاستعلام رغم طولها (legacy_sort)",
          not any(w in query for w in ("لتقرير", "للتاكد", "وفقا", "بأكمله")))
    check("الهمزة تبقى بإملائها الأصلي في الاستعلام لا مطبَّعة (اتفاقية لا اتفاقيه)",
          "اتفاقيه" not in verify.build_query("اتفاقية البترودولار لعام 1974").split())
    check("كلمة بإملاء صحيح (اتفاقية) تدخل الاستعلام كما وردت",
          "اتفاقية" in verify.build_query("اتفاقية البترودولار لعام 1974").split())

    # العلاج 2 (Issue #132 تعليق لاحق): استعلام البحث يُبنى من entities
    # الادّعاء حصرًا حين تتوفر، لا من نص الجملة المعاد صياغته — تشخيص سابق
    # وجد أن ثلاث صياغات معقولة لنفس الحقيقة (بلا هذا العلاج) أنتجت 53
    # مقابل 2 مقابل 3 نتيجة بحث مختلفة جذريًا، لأن الاستعلام كان يُشتق من
    # الجملة المعاد صياغتها نفسها في كل تشغيل
    same_entities = ["بلومبرغ", "2026", "السعودي"]
    phrasing_a = {"text": "انخفضت واردات الولايات المتحدة من النفط السعودي "
                          "إلى الصفر طوال يوليو 2026 وفقًا لتقرير بلومبرغ",
                 "entities": same_entities}
    phrasing_b = {"text": "توقفت واردات أميركا من النفط السعودي بالكامل في "
                          "2026 كما ذكرت بلومبرغ في تقريرها الأخير",
                 "entities": same_entities}
    phrasing_c = {"text": "صفر واردات نفط سعودي لأميركا سنة 2026، بحسب بلومبرغ",
                 "entities": list(same_entities)}
    queries_from_entities = {verify.build_query_for_claim(c) for c in
                             (phrasing_a, phrasing_b, phrasing_c)}
    check("ثلاث صياغات مختلفة لنفس الواقعة بنفس entities تُنتج استعلامًا واحدًا",
          len(queries_from_entities) == 1, str(queries_from_entities))
    check("الاستعلام المبني من entities لا يتجاوز سقف الكلمات",
          len(next(iter(queries_from_entities)).split()) <= 5)
    check("entities غائبة تمامًا تسقط لبناء الاستعلام من نص الادّعاء كاملًا "
          "كما كان قبل هذا العلاج",
          verify.build_query_for_claim({"text": long_claim}) ==
          verify.build_query(long_claim))
    check("entities فارغة (قائمة فعليًا لكن بلا عناصر) تسقط أيضًا لنص الادّعاء",
          verify.build_query_for_claim({"text": long_claim, "entities": []}) ==
          verify.build_query(long_claim))

    # احتياط العنوان والملخص حين يتعذّر استخراج أي نص كامل (Issue #132
    # تعليق لاحق: extract.py كانت تعيد "0 من N" دائمًا مهما كانت نتائج
    # البحث صحيحة، فيصل الحكم "لا مصدر" رغم دليل واضح في العنوان — 'للمرة
    # الأولى منذ 1985.. أمريكا توقف استيراد النفط السعودي' كان يؤكد الواقعة
    # حرفيًا لكنه ضاع لأن النص الكامل وحده كان مقبولًا كدليل)
    real_extract_gather = extract.gather
    fallback_articles = [
        Article(title="Oil imports halted for first time since 1985",
               link="https://a.example.com/1", summary="US ends Saudi oil imports",
               source_name="Reuters", region="global", weight=1.0,
               published=datetime.now(timezone.utc), publisher="Reuters"),
        Article(title="Second report confirms halt", link="https://b.example.com/2",
               summary="More detail on the halt", source_name="AP", region="global",
               weight=1.0, published=datetime.now(timezone.utc), publisher="AP"),
    ]
    extract.gather = lambda members, limit=2: ([], [])  # كل محاولات استخراج النص الكامل تفشل
    docs, basis = verify.gather_evidence(fallback_articles, cfg)
    check("احتياط العناوين يعمل حين يتعذّر النص الكامل رغم وجود نتائج",
          basis == verify.EVIDENCE_HEADLINES_ONLY)
    check("كل وثيقة احتياط معلَّمة from_text=False",
          bool(docs) and all(d["from_text"] is False for d in docs))
    check("نص الاحتياط يحوي العنوان الفعلي (لا فراغًا)",
          any("1985" in d["text"] for d in docs))

    extract.gather = lambda members, limit=2: (
        [{"name": "Reuters", "text": "نص المقال الكامل الحقيقي المستخرج"}], [])
    docs2, basis2 = verify.gather_evidence(fallback_articles, cfg)
    check("النص الكامل يُفضَّل حين يتوفر لا الاحتياط", basis2 == verify.EVIDENCE_FULL_TEXT)
    check("وثيقة النص الكامل معلَّمة from_text=True",
          bool(docs2) and docs2[0]["from_text"] is True)
    extract.gather = real_extract_gather

    check("لا نتائج بحث أصلًا ← تمييز صريح لا استدعاء extract.gather",
          verify.gather_evidence([], cfg) == ([], verify.EVIDENCE_NO_RESULTS))

    # اختبار مباشر لتحليل رد extract_claims (قبل أي محاكاة تستبدل الدالة
    # نفسها) — يغطي عطل الإصدار الأول: رد مبتور، ورد JSON غير صالح، ورد
    # محاط بأسوار ```json```
    class _Block:
        def __init__(self, type_, text=None, input=None):
            self.type = type_
            self.text = text
            self.input = input

    class _Resp:
        def __init__(self, content, stop_reason="end_turn"):
            self.content = content
            self.stop_reason = stop_reason

    class _FakeMessages:
        def __init__(self, responses):
            self._responses = list(responses)

        def create(self, **kw):
            return self._responses.pop(0)

    class _FakeClient:
        def __init__(self, responses):
            self.messages = _FakeMessages(responses)

    def _with_client(responses):
        verify._client = lambda: _FakeClient(responses)

    # رد مبتور (max_tokens) ← سبب محدد لا "حاول مجددًا"، بلا استثناء غير مُلتقَط
    _with_client([_Resp([_Block("text", text="{\"topic\": \"ناقص")],
                        stop_reason="max_tokens")] * 3)
    data, reason = verify.extract_claims("نص طويل", cfg, retries=3)
    check("رد مبتور: لا بيانات", data is None)
    check("رد مبتور: السبب يذكر تجاوز سقف التوكنات", "مبتور" in reason)

    # رد نصي JSON غير صالح تمامًا ← سبب محدد آخر
    _with_client([_Resp([_Block("text", text="ليس JSON على الإطلاق")])] * 3)
    data, reason = verify.extract_claims("نص", cfg, retries=3)
    check("رد غير صالح: لا بيانات", data is None)
    check("رد غير صالح: السبب يذكر JSON غير صالح", "JSON" in reason)

    # رد نصي صالح لكن محاط بأسوار ```json``` (بلا استدعاء أداة) ← يُقرأ رغم ذلك
    fenced = "```json\n" + json.dumps(
        {"topic": "ت", "claims": [], "questions": []}, ensure_ascii=False
    ) + "\n```"
    _with_client([_Resp([_Block("text", text=fenced)])])
    data, reason = verify.extract_claims("نص", cfg, retries=3)
    check("رد محاط بأسوار json يُحلَّل بنجاح", data is not None and reason is None)
    check("موضوع الرد المحاط بأسوار يصل صحيحًا", data and data.get("topic") == "ت")

    # عطل فعلي رُصد في السجل (Issue #132 تعليق لاحق): النموذج يحشر بنية الرد
    # الكاملة (claims + topic + questions) داخل حقل claims وحده كنص يبدأ
    # بمصفوفة الادّعاءات — أي أن القوس الافتتاحي "{" للكائن الكامل غاب من رد
    # النموذج نفسه. أسماء الحقول في الرد قبل الإصلاح كانت ["claims"] فقط.
    stuffed = (
        '[\n{"text": "ارتفعت أسعار الوقود بنسبة 12٪ الشهر الماضي", '
        '"kind": "واقعة"},\n{"text": "الأسعار ستتضاعف خلال عام", '
        '"kind": "تنبؤ"}\n],\n"topic": "ارتفاع أسعار الوقود",\n'
        '"questions": ["ما مصدر بيانات نسبة الارتفاع؟"]\n}'
    )
    _with_client([_Resp([_Block("tool_use", input={"claims": stuffed})])])
    data, reason = verify.extract_claims("نص", cfg, retries=3)
    check("الرد المحشور في حقل claims وحده يُعالَج بلا فشل", data is not None and reason is None)
    check("الموضوع يُستخرج من داخل النص المحشور",
          data and data.get("topic") == "ارتفاع أسعار الوقود")
    check("الادّعاءان يُستخرجان من داخل النص المحشور",
          data and isinstance(data.get("claims"), list) and len(data["claims"]) == 2)
    check("الأسئلة تُستخرج من داخل النص المحشور",
          data and data.get("questions") == ["ما مصدر بيانات نسبة الارتفاع؟"])

    # الاحتياط العام: قيمة حقل claims وحدها JSON صالح (مصفوفة فقط، بلا حشر
    # بقية الحقول) يجب أن تُقرأ أيضًا لا أن تُرفَض لمجرد كونها نصًا
    check("normalize_claims تقبل نص JSON صالحًا لمصفوفة ادّعاءات",
          verify.normalize_claims('[{"text": "ادّعاء", "kind": "واقعة"}]') ==
          [{"text": "ادّعاء", "kind": "واقعة", "entities": [],
            "is_qualifier": False, "is_reference": False}])
    check("normalize_questions تقبل نص JSON صالحًا لمصفوفة أسئلة",
          verify.normalize_questions('["سؤال؟"]') == ["سؤال؟"])
    check("نص لا يبدأ بـ [ أو { لا يُحاول تحليله كـ JSON",
          verify._coerce_json_string("نص عادي") == "نص عادي")
    check("نص يبدأ بـ [ لكنه JSON غير صالح يُعاد كما وصل بلا انهيار",
          verify._coerce_json_string("[غير صالح") == "[غير صالح")

    # الطريق الكامل: judge_fact الحقيقية (بعميل مزيَّف) تعيد اسمًا مذيَّلًا
    # بوصف بين قوسين تمامًا كالعطل الفعلي في السجل — يجب أن يصل مقبولًا
    # في نتيجتها النهائية لا محذوفًا (Issue #132 تعليق لاحق)
    docs_jafra_full = [{"name": "جفرا نيوز", "text": "نص يؤكد الواقعة",
                        "from_text": True}]
    _with_client([_Resp([_Block("tool_use", input={
        "supporting": ["جفرا نيوز (نص المقال الكامل)"], "contradicting": []})])])
    judged_jafra = verify.judge_fact("ادّعاء", docs_jafra_full, cfg)
    check("جفرا نيوز (نص المقال الكامل) تُقبل عبر judge_fact الكامل لا تُحذف "
          "(العطل الفعلي في السجل)",
          judged_jafra["supporting"] == ["جفرا نيوز"], str(judged_jafra))

    # temperature غير مقبولة من نماذج هذا المشروع (Error code: 400 —
    # "temperature is deprecated for this model", تشخيص Issue #373، الجولة
    # الحادية عشرة) — judge_fact لا يجوز أن تمرّرها إطلاقًا
    class _CapturingMessages:
        def __init__(self, responses, captured):
            self._responses = list(responses)
            self._captured = captured

        def create(self, **kw):
            self._captured.append(kw)
            return self._responses.pop(0)

    class _CapturingClient:
        def __init__(self, responses, captured):
            self.messages = _CapturingMessages(responses, captured)

    captured_kw: list = []
    verify._client = lambda: _CapturingClient(
        [_Resp([_Block("tool_use", input={"supporting": [], "contradicting": []})])],
        captured_kw)
    verify.judge_fact("ادّعاء", docs_jafra_full, cfg)
    check("judge_fact: لا يمرّر temperature (400 من الخادم لو مُرِّرت)",
          bool(captured_kw) and "temperature" not in captured_kw[-1], captured_kw)
    verify._client = real_client

    # فشل نداء تقني (رفض API/انقطاع شبكة) يظهر صراحة في نتيجة judge_fact —
    # لا بصمت خلف نفس {"supporting": [], "contradicting": []} التي يعيدها
    # حكم "لا سند" الشرعي (تشخيص Issue #373، الجولة الحادية عشرة، البند 2)
    from anthropic import APIConnectionError
    import httpx as _httpx

    class _RaisingMessages:
        def create(self, **kw):
            raise APIConnectionError(
                message="انقطاع شبكة اختباري",
                request=_httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    class _RaisingClient:
        def __init__(self):
            self.messages = _RaisingMessages()

    verify._client = lambda: _RaisingClient()
    judged_fail = verify.judge_fact("ادّعاء", docs_jafra_full, cfg, retries=1)
    verify._client = real_client
    check("judge_fact: فشل نداء تقني يعيد supporting/contradicting فارغتين "
          "كحكم سلبي (توافق خلفي)",
          judged_fail["supporting"] == [] and judged_fail["contradicting"] == [],
          judged_fail)
    check("judge_fact: فشل نداء تقني يحمل call_error بنص الاستثناء لا None "
          "(يفرّقه عن حكم 'لا سند' الشرعي)",
          judged_fail.get("call_error") and
          "انقطاع شبكة اختباري" in judged_fail["call_error"],
          judged_fail.get("call_error"))

    # ينعكس صراحة في تقرير Issue التحقّق (لا العمود الداخلي وحده)
    verify.search = lambda query, cfg, days, unrestricted=False: [object()]
    verify.gather_evidence = lambda articles, cfg, claim_text="": (
        docs_jafra_full, verify.EVIDENCE_FULL_TEXT)
    verify.extract_claims = lambda text, cfg, retries=3: ({
        "topic": "اختبار فشل نداء تقني",
        "claims": [{"text": "واقعة تختبر فشل النداء", "kind": "واقعة"}],
        "questions": [],
    }, None)
    verify._client = lambda: _RaisingClient()
    fail_result = verify.verify_article("نص المقال الملصق", cfg)
    verify._client = real_client
    verify.search = real_search
    verify.gather_evidence = real_gather_evidence
    fail_report = verify.build_report(fail_result)
    check("تقرير التحقّق يُظهر فشل النداء التقني صراحة في عمود الأدلة",
          "فشل نداء الحكم تقنيًا" in fail_report and "انقطاع شبكة اختباري" in fail_report,
          fail_report)

    # مقال بلا أي مصدر يؤكد وقائعه ← حكم سلبي واضح لا تقرير مبهم
    verify.extract_claims = lambda text, cfg, retries=3: ({
        "topic": "مقال بلا سند",
        "claims": [{"text": "زعم لا سند له", "kind": "واقعة"},
                   {"text": "رأي كاتب المقال", "kind": "رأي"}],
        "questions": ["سؤال بلا جواب في المصادر؟"],
    }, None)
    verify.search = lambda query, cfg, days, unrestricted=False: []
    result = verify.verify_article("نص المقال الملصق", cfg)

    check("المقال يُعالَج بنجاح", result["ok"])
    check("الواقعة بلا مصدر تُصنَّف كذلك",
          result["facts"][0]["status"] == verify.STATUS_NONE)
    check("الرأي لا يدخل جدول الوقائع", len(result["facts"]) == 1)
    check("لا وقائع مؤكدة ← الحكم لا", result["verdict"] is False)
    check("سبب الحكم صريح لا مبهم",
          "لا واقعة" in result["verdict_reason"]
          or "لا تكفي" in result["verdict_reason"])
    check("السؤال بلا مصادر يُعلَّم بلا إجابة",
          result["questions"][0]["answered"] is False)
    check("لا مخالفات حين لا توجد مصادر أصلًا", result["contradictions"] == [])
    # التمييز الصريح المطلوب (Issue #132 تعليق لاحق): "لا نتائج بحث" غير
    # "قرأتُ ولم أجد تأييدًا" — كلاهما كان يظهر "لا مصدر" نفسها فقط
    check("أساس الأدلة يذكر صراحة عدم وجود نتائج بحث لا حكمًا مبهمًا",
          result["facts"][0]["evidence_basis"] == verify.EVIDENCE_NO_RESULTS)

    report = verify.build_report(result)
    check("التقرير يفرد قسم مخالفة المصادر", "أين خالفت المصادر المقال" in report)
    check("التقرير يحمل حكمًا نهائيًا سلبيًا صريحًا",
          "❌" in report and "**لا**" in report)
    check("التقرير يذكر الموضوع", "مقال بلا سند" in report)

    # مقال بواقعة مؤكدة من مصدرين مستقلين ← حكم إيجابي
    # gather_evidence تعيد (docs, evidence_basis) منذ احتياط العنوان فقط
    # (Issue #132 تعليق لاحق) — لا قائمة docs مجردة كما كانت
    verify.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": "BBC", "text": "t", "from_text": True}], verify.EVIDENCE_FULL_TEXT)
    verify.judge_fact = lambda claim, docs, cfg: {
        "supporting": ["BBC", "Reuters"], "contradicting": []}
    verify.judge_question = lambda q, docs, cfg: {
        "answered": True, "answer": "نعم حدث كذلك", "source": "BBC"}
    verify.search = lambda query, cfg, days, unrestricted=False: [object()]  # غير فارغة لتفعيل القراءة

    result2 = verify.verify_article("نص مقال آخر", cfg)
    check("واقعة مؤكدة بمصدرين ← الحكم نعم", result2["verdict"] is True)
    check("سبب الحكم الإيجابي يذكر العدد المؤكَّد", "مؤكَّدة" in result2["verdict_reason"])
    check("أساس الأدلة نص كامل حين ينجح الاستخراج",
          result2["facts"][0]["evidence_basis"] == verify.EVIDENCE_FULL_TEXT)
    report2 = verify.build_report(result2)
    check("التقرير الإيجابي يحمل ✅", "✅" in report2 and "**نعم**" in report2)
    check("عمود الأدلة يظهر في التقرير", "الأدلة" in report2)
    # وزن كل مصدر مؤيد يظهر في التقرير لا العدد وحده (Issue #132 تعليق لاحق)
    check("عمود المصادر المؤيدة يعرض وزن كل مصدر (BBC وReuters كلاهما في "
          "trusted_boost)", "×" in report2)
    check("supporting_weighted محسوبة فعليًا لكل واقعة لا فارغة",
          bool(result2["facts"][0].get("supporting_weighted")))

    # لقطة (snapshot، Issue #334 نقطة 1 من الموافقة): إضافة "index" و
    # "sources" لكل واقعة (لاستهلاك verify_draft.py) حقل بيانات فقط، يجب
    # ألا يغيّر أي حكم أو حقل من حقول المرحلة الأولى القائمة — كل الحقول
    # القديمة أعلاه (status/verdict/supporting/evidence_basis) فُحصت فعلًا
    # بلا تغيير؛ هنا نثبت أن الحقلين الجديدين إضافيان بحتًا لا يستبدلان شيئًا
    check("الحقول القديمة كلها باقية رغم إضافة index/sources",
          {"text", "status", "supporting", "supporting_weighted",
           "contradicting", "evidence_basis"} <= set(result2["facts"][0].keys()))
    check("index جديد ويطابق ترتيب الاستخراج (واقعة واحدة هنا: 0)",
          result2["facts"][0]["index"] == 0)
    check("sources جديد: مقتطف/رابط لكل مصدر مؤيِّد فعليًا لا اسمًا مجردًا",
          result2["facts"][0]["sources"] and
          all({"name", "link", "text", "image_candidates"} <= set(s.keys())
              for s in result2["facts"][0]["sources"]))
    # فرعية لا تطابق تام: هذا التثبيت يزيّف gather_evidence بمصدر واحد
    # ("BBC") بينما judge_fact مزيَّفة تعيد BBC وReuters معًا — تعمّد لا
    # يمثّل واقعًا حقيقيًا (حيث judge_fact الفعلية عبر _known_only تقتصر
    # على أسماء موجودة في docs أصلًا)، لكنه يثبت أن _fact_sources لا تخترع
    # مصدرًا لا نص موثَّق له
    check("أسماء sources كلها من ضمن supporting، بلا اختراع مصدر بلا نص موثَّق",
          {s["name"] for s in result2["facts"][0]["sources"]} <=
          set(result2["facts"][0]["supporting"]))

    # العلاج 4 (Issue #132 تعليق لاحق) عبر verify_article الكاملة لا وحدة
    # classify_fact فقط: مصدر واحد قوي (Bloomberg، في trusted_boost) يظهر
    # كحالة وسيطة صريحة — التقرير يعكس عدم اليقين بدل إخفائه خلف "مصدر واحد"
    verify.judge_fact = lambda claim, docs, cfg: {
        "supporting": ["Bloomberg"], "contradicting": []}
    result_near = verify.verify_article("نص مقال ثالث", cfg)
    check("مصدر واحد قوي عند حافة العتبة عبر verify_article الكاملة ← "
          "شبه مؤكَّدة لا مصدر واحد مبهمة",
          result_near["facts"][0]["status"] == verify.STATUS_NEAR_CONFIRMED)
    check("الحكم النهائي يبقى لا رغم الحالة الوسيطة (مصدر واحد لا يكفي للنشر)",
          result_near["verdict"] is False)
    check("سبب الحكم يذكر الحالة شبه المؤكَّدة صراحة لا يُخفيها",
          "شبه مؤكَّدة" in result_near["verdict_reason"])
    report_near = verify.build_report(result_near)
    check("التقرير يعرض الحالة الوسيطة في جدول الوقائع",
          verify.STATUS_NEAR_CONFIRMED in report_near)

    # البند 2 (تعليق التنفيذ على Issue #339) عبر verify_article الكاملة —
    # لا وحدة classify_fact فقط: مصدران كافيان للتأكيد، وثالث يخالف — يجب
    # أن تظهر الحالة الرابعة، وألا يتناقض عمود "المصادر المخالفة" مع قسم
    # "أين خالفت المصادر" (البند 3، نفس تعليق التنفيذ)
    verify.judge_fact = lambda claim, docs, cfg: {
        "supporting": ["BBC", "Reuters"], "contradicting": ["أخبار الغد"]}
    result_disputed = verify.verify_article("نص مقال رابع", cfg)
    check("مصدران كافيان مع اعتراض ثالث عبر verify_article الكاملة ← "
          "مؤكَّدة مع اعتراض مصدر",
          result_disputed["facts"][0]["status"] == verify.STATUS_CONFIRMED_DISPUTED)
    check("الواقعة المعترَض عليها لا تُحسب ضمن confirmed لحساب الحكم النهائي "
          "(لا تدخل مسار المسودة لاحقًا)",
          not any(f["status"] == verify.STATUS_CONFIRMED
                  for f in result_disputed["facts"]))
    check("الحكم النهائي لا حين لا واقعة مؤكَّدة (غير معترَض عليها) واحدة",
          result_disputed["verdict"] is False)
    report_disputed = verify.build_report(result_disputed)
    contradicting_col_nonempty = "أخبار الغد" in report_disputed.split(
        "#### ⚠️ أين خالفت المصادر المقال")[0]
    section_says_none = ("لم يظهر أي تناقض" in
                         report_disputed.split("#### ⚠️ أين خالفت المصادر المقال")[1])
    check("عمود المصادر المخالفة مآهول والقسم المخصَّص لا يقول معًا «لم يظهر "
          "أي تناقض» — استحالة تعايش الحالتين",
          not (contradicting_col_nonempty and section_says_none))
    check("«أخبار الغد» تظهر في قسم أين خالفت المصادر أيضًا لا العمود وحده",
          "أخبار الغد" in report_disputed.split(
              "#### ⚠️ أين خالفت المصادر المقال")[1])

    # verify_article يبني استعلام بحث قصيرًا لكل ادّعاء/سؤال قبل استدعاء
    # search، لا يمرّر نص الادّعاء الكامل — سبب عطل "لا مصدر" الجماعي الفعلي
    long_question = ("ما مصدر البيانات التي استند إليها المقال في الحديث عن "
                     "اتفاقية البترودولار لعام 1974 وتأثيرها على الاقتصاد؟")
    verify.extract_claims = lambda text, cfg, retries=3: ({
        "topic": "مقال باستعلامات طويلة",
        "claims": [{"text": long_claim, "kind": "واقعة"}],
        "questions": [long_question],
    }, None)
    seen_queries: list[str] = []

    def _spy_search(query, cfg, days, unrestricted=False):
        seen_queries.append(query)
        return []

    verify.search = _spy_search
    verify.verify_article("نص", cfg)
    check("استعلامات البحث الفعلية قصيرة كلها لا الجملة كاملة",
          len(seen_queries) == 2 and all(len(q.split()) <= 5 for q in seen_queries))
    check("لا استعلام فعلي يساوي نص الادّعاء أو السؤال الكامل",
          long_claim not in seen_queries and long_question not in seen_queries)

    # الإصلاح الأخير (Issue #132 تعليق لاحق): إصلاح الاستعلام وحده لم يكفِ —
    # gather_evidence كانت لا تزال تحسب صلة القراءة من claim["text"] المعاد
    # صياغته، فاستمر التذبذب عمليًا رغم استقرار البحث (تشغيلان متتاليان
    # لنفس المقال أعادا ثلاثة مصادر ثم مصدرًا واحدًا لنفس الواقعة). يجب أن
    # يصل gather_evidence نص entities الثابت لا claim["text"] المتغيّر.
    verify.gather_evidence = real_gather_evidence  # نحتاج السلوك الحقيقي هنا لا التلفيق السابق
    seen_relevance_text: list[str] = []

    def _spy_gather_evidence(articles, cfg, claim_text=""):
        seen_relevance_text.append(claim_text)
        return real_gather_evidence(articles, cfg, claim_text)

    verify.gather_evidence = _spy_gather_evidence
    wiring_entities = ["1985", "السعودي", "بلومبرغ"]
    verify.extract_claims = lambda text, cfg, retries=3: ({
        "topic": "مقال الوزن",
        "claims": [{"text": "توقفت واردات أمريكا من النفط السعودي بالكامل "
                            "لأول مرة منذ 1985", "kind": "واقعة",
                   "entities": wiring_entities}],
        "questions": [],
    }, None)
    verify.search = lambda query, cfg, days, unrestricted=False: [object()]
    verify.verify_article("نص أول", cfg)

    verify.extract_claims = lambda text, cfg, retries=3: ({
        "topic": "مقال الوزن",
        "claims": [{"text": "انخفضت واردات الولايات المتحدة من النفط الخام "
                            "السعودي إلى الصفر، حسب تقرير بلومبرغ في 1985",
                   "kind": "واقعة", "entities": list(wiring_entities)}],
        "questions": [],
    }, None)
    verify.verify_article("نص ثانٍ", cfg)
    verify.gather_evidence = real_gather_evidence

    check("gather_evidence تستقبل نفس نص الصلة (من entities) رغم اختلاف "
          "صياغة claim['text'] كليًا بين تشغيلين لنفس الوقائع",
          len(seen_relevance_text) == 2 and
          seen_relevance_text[0] == seen_relevance_text[1] ==
          " ".join(wiring_entities), str(seen_relevance_text))

    # البند 5 (تعليق التنفيذ على PR #340): _verify_article يمرر
    # unrestricted=True لـsearch() حين is_reference: true على الادّعاء، لا
    # حين تغيب أو تكون false — وقائعة مرجعية وأخرى جارية معًا في مقال واحد
    # تُفرَّقان بلا تسرّب من إحداهما إلى الأخرى
    seen_unrestricted: list[bool] = []

    def _spy_search_unrestricted(query, cfg, days, unrestricted=False):
        seen_unrestricted.append(unrestricted)
        return []

    verify.search = _spy_search_unrestricted
    verify.extract_claims = lambda text, cfg, retries=3: ({
        "topic": "مقال يحوي واقعة مرجعية وأخرى جارية",
        "claims": [
            {"text": "صدر الكتاب المرجعي عام 2009", "kind": "واقعة",
             "is_reference": True},
            {"text": "ارتفعت الأسعار هذا الأسبوع", "kind": "واقعة",
             "is_reference": False},
        ],
        "questions": [],
    }, None)
    verify.verify_article("نص", cfg)
    check("واقعة مرجعية (is_reference: true) ← unrestricted=True لـsearch",
          seen_unrestricted == [True, False], str(seen_unrestricted))

    # لا استخراج ممكن (رد مبتور) ← رسالة خطأ محددة بدل "حاول مجددًا" مبهمة
    verify.extract_claims = lambda text, cfg, retries=3: (
        None, "الرد مبتور — تجاوز سقف التوكنات")
    failed = verify.verify_article("نص", cfg)
    check("فشل الاستخراج يُعاد كخطأ صريح", failed["ok"] is False)
    check("سبب الفشل محدد لا رسالة \"حاول مجددًا\" مبهمة",
          "حاول مجددًا" not in failed["reason"] and "مبتور" in failed["reason"])
    check("تقرير الفشل مقروء لا يحوي حقولًا فارغة",
          "تعذّر التحقق" in verify.build_report(failed))

    # الحالات الثلاث من Issue #134: claims نصوص / claims قواميس / claims
    # غائبة تمامًا عن رد النموذج — لا انهيار في أي منها
    verify.search = lambda query, cfg, days, unrestricted=False: []

    verify.extract_claims = lambda text, cfg, retries=3: (
        {"topic": "مقال بادّعاءات نصية", "claims": ["ادّعاء أول", "ادّعاء ثانٍ"],
         "questions": ["سؤال؟"]}, None)
    out_strings = verify.verify_article("نص", cfg)
    check("claims كقائمة نصوص مجردة لا تنهار (عطل Issue #134 الأصلي)",
          out_strings["ok"] is True)
    check("كل نص مجرد يصير واقعة قابلة للعرض في التقرير",
          len(out_strings["facts"]) == 2 and
          out_strings["facts"][0]["text"] == "ادّعاء أول")

    verify.extract_claims = lambda text, cfg, retries=3: (
        {"topic": "مقال بادّعاءات قواميس",
         "claims": [{"text": "ادّعاء بقاموس", "kind": "واقعة"}],
         "questions": []}, None)
    out_dicts = verify.verify_article("نص", cfg)
    check("claims كقائمة قواميس كاملة تُعالَج طبيعيًا",
          out_dicts["ok"] is True and len(out_dicts["facts"]) == 1)

    # ملاحظة: حقل claims الغائب تمامًا كان يُعامَل سابقًا كنجاح بلا وقائع؛
    # بعد Issue #132 (تعليق لاحق: رد 1858 توكن ضاع بصمت لأن اسم الحقل
    # الفعلي لم يكن claims) أصبح غياب أي اسم بديل معروف فشلًا صريحًا لا
    # تقريرًا فارغًا يبدو مشروعًا — انظر الاختبارات أدناه.
    verify.extract_claims = lambda text, cfg, retries=3: (
        {"topic": "مقال بلا حقل claims إطلاقًا"}, None)
    out_missing = verify.verify_article("نص", cfg)
    check("حقل claims غائب تمامًا تحت كل الأسماء المعروفة ← فشل صريح لا نجاح صامت",
          out_missing["ok"] is False and
          "تعذّرت قراءة بنية الرد" in out_missing["reason"])

    # أسماء حقول بديلة شائعة (Issue #132 تعليق لاحق): facts/statements بدل
    # claims، title/subject بدل topic — يجب أن تُقرأ بنجاح لا أن تُسقَط
    verify.extract_claims = lambda text, cfg, retries=3: (
        {"title": "موضوع بحقل بديل", "facts": ["واقعة بحقل facts"],
         "questions": []}, None)
    out_alias = verify.verify_article("نص", cfg)
    check("حقل facts البديل عن claims يُقرأ بنجاح",
          out_alias["ok"] is True and len(out_alias["facts"]) == 1)
    check("حقل title البديل عن topic يُقرأ بنجاح",
          out_alias["topic"] == "موضوع بحقل بديل")

    verify.extract_claims = lambda text, cfg, retries=3: (
        {"subject": "موضوع آخر",
         "statements": [{"text": "واقعة بحقل statements", "kind": "واقعة"}]},
        None)
    out_alias2 = verify.verify_article("نص", cfg)
    check("حقل statements البديل عن claims يُقرأ بنجاح",
          out_alias2["ok"] is True and len(out_alias2["facts"]) == 1)
    check("حقل subject البديل عن topic يُقرأ بنجاح",
          out_alias2["topic"] == "موضوع آخر")

    # رد بأسماء حقول غير متوقعة تمامًا (لا مطابقة لأي اسم بديل معروف) — يجب
    # ألا يُنتج تقريرًا فارغًا يبدو مشروعًا، بل فشلًا صريحًا يُطلب فيه مراجعة
    # السجل (هذا هو عطل Issue #134 الثالث: رد ضخم 1858 توكن ضاع بصمت)
    verify.extract_claims = lambda text, cfg, retries=3: (
        {"headline_summary": "موضوع لا يُعرف اسم حقله",
         "key_points": ["نقطة أولى", "نقطة ثانية"]}, None)
    out_unknown = verify.verify_article("نص", cfg)
    check("أسماء حقول غير معروفة تمامًا تُنتج فشلًا صريحًا لا تقريرًا فارغًا",
          out_unknown["ok"] is False and
          "تعذّرت قراءة بنية الرد" in out_unknown["reason"])
    report_unknown = verify.build_report(out_unknown)
    check("تقرير الفشل الصريح واضح: \"تعذّر التحقق\" لا جدول وقائع فارغ",
          "تعذّر التحقق" in report_unknown and "الموضوع" not in report_unknown)

    # الانهيار غير مقبول أصلًا: استثناء غير متوقع من أي طبقة أدنى (بحث، حكم،
    # ...) يُلتقط داخل verify_article فيصل تعليق مفهوم لا traceback
    verify.extract_claims = lambda text, cfg, retries=3: (
        {"topic": "مقال", "claims": [{"text": "ادّعاء", "kind": "واقعة"}],
         "questions": []}, None)

    def _boom(query, cfg, days, unrestricted=False):
        raise RuntimeError("عطل غير متوقع لا علاقة له بشكل رد النموذج")

    verify.search = _boom
    crashed = verify.verify_article("نص", cfg)
    check("استثناء غير متوقع من طبقة البحث لا يتسرب من verify_article",
          crashed["ok"] is False)
    check("رسالة الخطأ عند انهيار غير متوقع مفهومة لا traceback خام",
          "خطأ غير متوقع" in crashed["reason"])
    check("تقرير الانهيار غير المتوقع يبقى مقروءًا",
          "تعذّر التحقق" in verify.build_report(crashed))

    # عطل تصميمي رُصد فعليًا في الإنتاج (Issue #132 تعليق لاحق): الدمج
    # الدلالي (merge.semantic_merge) يضمّ نسخ الخبر الواحد من ناشرين مختلفين
    # في ممثّل واحد — صحيح للنشر (لا ننشر الخبر أربع مرات) لكنه يُسقط تعدد
    # المصادر المستقلة الذي هو مقياس التحقق نفسه: 'الدمج الدلالي: ضُمّ 4
    # خبر في 1 مجموعة' ثم 'نصوص مُستخرجة: 1 من 1' رغم ثلاثة عناوين مؤيّدة.
    seen_merge_cfg: list = []
    seen_keep_google_links: list = []
    real_rank = evidence.rank

    def _spy_rank(articles, selection, merge_cfg=None, token_fn=None,
                 keep_google_links=False):
        seen_merge_cfg.append(merge_cfg)
        seen_keep_google_links.append(keep_google_links)
        return real_rank(articles, selection, merge_cfg=merge_cfg, token_fn=token_fn,
                         keep_google_links=keep_google_links)

    one = Article(title="زلزال قوي يضرب هرات", link="https://x/1", summary="",
                  source_name="s", region="global", weight=1.0,
                  published=datetime.now(timezone.utc), publisher="s")
    real_fetch_source = evidence.fetch_source
    evidence.rank = _spy_rank
    evidence.fetch_source = lambda src, max_age_hours: [one]
    verify.search = real_search  # الاختبار السابق تركها على _boom
    try:
        verify.search("زلزال هرات", cfg, 7)
    finally:
        evidence.fetch_source = real_fetch_source
        evidence.rank = real_rank
    check("الدمج الدلالي معطَّل صراحة في بحث التحقق (merge_cfg=None)",
          seen_merge_cfg == [None], str(seen_merge_cfg))
    # keep_google_links=True لازمة لبحث التحقق (Issue #132 تعليق لاحق):
    # نتائجه كلها روابط جوجل، فالاستبعاد الافتراضي في
    # rank.pick_representative كان يُفرغ cluster_members قبل أن تصل
    # gather_evidence أصلًا
    check("verify.search يمرر keep_google_links=True لـ rank",
          seen_keep_google_links == [True], str(seen_keep_google_links))

    # البند 5 (تعليق التنفيذ على PR #340): unrestricted=True يُسقط قيد when:
    # من search_feeds *و* يرفع سقف عمر fetch_source إلى
    # REFERENCE_MAX_AGE_HOURS بدل days*24 — كلاهما معًا، لا أحدهما وحده
    # (إسقاط when: وحده لا يمنع fetch_source من رفض مصدر قديم بعد جلبه)
    seen_days: list = []
    seen_max_age: list = []
    real_search_feeds = evidence.search_feeds

    def _spy_search_feeds(query, days, locales):
        seen_days.append(days)
        return real_search_feeds(query, days, locales)

    evidence.search_feeds = _spy_search_feeds
    evidence.fetch_source = lambda src, max_age_hours: (
        seen_max_age.append(max_age_hours), [one])[1]
    try:
        verify.search("كتاب صدر 2009", cfg, 21, unrestricted=True)
    finally:
        evidence.fetch_source = real_fetch_source
        evidence.search_feeds = real_search_feeds
    check("unrestricted=True يمرر days=None لـ search_feeds (بلا قيد when:)",
          seen_days and all(d is None for d in seen_days), str(seen_days))
    check("unrestricted=True يرفع سقف عمر fetch_source إلى REFERENCE_MAX_AGE_HOURS",
          seen_max_age and all(m == verify.REFERENCE_MAX_AGE_HOURS for m in seen_max_age),
          str(seen_max_age))

    # unrestricted=False (الافتراضي) يبقى سلوكه القديم بلا تغيير
    seen_days.clear()
    seen_max_age.clear()
    evidence.search_feeds = _spy_search_feeds
    evidence.fetch_source = lambda src, max_age_hours: (
        seen_max_age.append(max_age_hours), [one])[1]
    try:
        verify.search("زلزال هرات", cfg, 7)
    finally:
        evidence.fetch_source = real_fetch_source
        evidence.search_feeds = real_search_feeds
    check("unrestricted=False (الافتراضي) يمرر days الفعلي لـ search_feeds",
          seen_days == [7], str(seen_days))
    check("unrestricted=False (الافتراضي) يبقي سقف fetch_source عند days*24",
          seen_max_age and all(m == 7 * 24 for m in seen_max_age), str(seen_max_age))

    # gather_evidence يجب أن يوسّع الممثّل الواحد (بعد تجميع rank.cluster
    # اللفظي، الذي يعمل دومًا داخل rank()) إلى ناشريه الفعليين المحفوظين في
    # cluster_members — لا أن يكتفي برابط/اسم الممثّل وحده. cluster_members
    # هنا يُبنى عبر rank.pick_representative **الحقيقية** من مجموعة روابطها
    # كلها جوجل (كما تصل فعليًا من verify.search، الذي يستعمل بحث Google
    # News حصرًا) — لا تلفيقها يدويًا بروابط ناشرين مباشرة كما كان الاختبار
    # السابق يفعل: ذلك التلفيق كان يُخفي عطلًا فعليًا حقيقيًا رُصد لاحقًا في
    # الإنتاج (Issue #132 تعليق لاحق): 'تم دمج 5 خبر في 1 موضوع' ثم 'نصوص
    # مُستخرجة: 1 من 1' رغم أن هذا الاختبار نفسه كان ينجح، لأن
    # rank.pick_representative الافتراضية تستبعد روابط جوجل الوسيطة من
    # cluster_members قبل أن تصل gather_evidence أصلًا — بصرف النظر عن صحة
    # منطق التوسيع في gather_evidence ذاته.
    from src.rank import pick_representative

    google_group = [
        Article(title="أمريكا توقف استيراد النفط السعودي للمرة الأولى منذ 1985",
               link="https://news.google.com/rss/articles/a", summary="",
               source_name="Bloomberg", region="global", weight=1.5,
               published=datetime.now(timezone.utc), publisher="Bloomberg"),
        Article(title="أمريكا توقف استيراد النفط السعودي للمرة الأولى منذ 1985",
               link="https://news.google.com/rss/articles/b", summary="",
               source_name="Al Jazeera", region="global", weight=1.2,
               published=datetime.now(timezone.utc), publisher="Al Jazeera"),
        Article(title="أمريكا توقف استيراد النفط السعودي للمرة الأولى منذ 1985",
               link="https://news.google.com/rss/articles/c", summary="",
               source_name="Al Arabiya", region="global", weight=1.0,
               published=datetime.now(timezone.utc), publisher="Al Arabiya"),
    ]

    rep_default = pick_representative(list(google_group))
    default_members = list(rep_default.cluster_members)
    check("افتراضيًا (مسار الجمع الأساسي) روابط جوجل مستبعدة من "
          "cluster_members — سلوكه الحالي لم يتغيّر بهذا الإصلاح",
          default_members == [], str(default_members))

    rep = pick_representative(list(google_group), keep_google_links=True)
    check("keep_google_links=True (ما يمرره verify.search) يُبقي روابط جوجل "
          "الثلاثة في cluster_members بدل إفراغها",
          len(rep.cluster_members) == 3, str(rep.cluster_members))

    real_resolve = evidence.resolve_final_url
    resolved_map = {
        "https://news.google.com/rss/articles/a": "https://bloomberg.example.com/self",
        "https://news.google.com/rss/articles/b": "https://aljazeera.example.com/x",
        "https://news.google.com/rss/articles/c": "https://alarabiya.example.com/y",
    }
    # gather_evidence يجب أن تحلّ روابط جوجل الواردة من cluster_members أيضًا
    # لا رابط الممثّل وحده — رابط لم يُحلّ يبقى google.com فيرفضه
    # extract.fetch_text لاحقًا، فأي اسم يُطابَق بلا حلّ هنا خطأ في الاختبار
    evidence.resolve_final_url = lambda link, timeout=12: resolved_map.get(
        link, f"UNRESOLVED::{link}")
    verify.gather_evidence = real_gather_evidence  # اختبار سابق تركها على lambda ثابتة

    received_members: list[dict] = []

    def _fake_gather_multi(members, limit=2):
        received_members.extend(members)
        return [{"name": m["name"], "text": f"نص {m['name']}"} for m in members[:limit]], []

    extract.gather = _fake_gather_multi
    try:
        docs3, basis3 = verify.gather_evidence([rep], cfg)
    finally:
        extract.gather = real_extract_gather
        evidence.resolve_final_url = real_resolve

    check("روابط جوجل الواردة من cluster_members تُحلّ أيضًا (لا رابط "
          "الممثّل وحده) قبل تمريرها لـ extract.gather",
          received_members and
          all(not m["link"].startswith("UNRESOLVED::") for m in received_members),
          str(received_members))

    names3 = {d["name"] for d in docs3}
    check("الممثّل الواحد يتوسّع إلى ناشريه الثلاثة المستقلين لا ناشره وحده",
          names3 == {"Bloomberg", "Al Jazeera", "Al Arabiya"}, str(names3))
    check("أساس الأدلة نص كامل بعد التوسيع", basis3 == verify.EVIDENCE_FULL_TEXT)

    # عدّ المصادر بالناشر لا بالموضوع/المجموعة: ثلاثة ناشرين لواقعة واحدة
    # تُحكم "مؤكَّدة" لا "مصدر واحد" رغم أنهم اندمجوا في مجموعة واحدة
    min_confirm = int((cfg.get("verify", {}) or {}).get("min_confirm_sources", 2))
    # Bloomberg من trusted_boost (البند 4 يشترط مصدرًا معروفًا واحدًا على
    # الأقل بين المؤيِّدين ليصل الحكم لمؤكَّدة كاملة — أوزان حقيقية عبر
    # _publisher_weight لا قاموسًا مصطنعًا)
    weights3 = {n: verify._publisher_weight(n, cfg) for n in names3}
    status3 = verify.classify_fact(list(names3), [], min_confirm, weights3)
    check("واقعة بثلاثة ناشرين مستقلين ← مؤكَّدة لا مصدر واحد",
          status3 == verify.STATUS_CONFIRMED)

    # عطل تصميمي ثانٍ رُصد فعليًا (Issue #132 تعليق لاحق): rank.tokens
    # لاتينية عمدًا (خلاصات الجمع الأساسي إنجليزية)، فعنوانان عربيان
    # مستقلا الصياغة عن الحدث نفسه لا يشتركان في أي توقيع لاتيني ويبقيان
    # مجموعتين منفصلتين رغم تطابق المضمون — الأمثلة هنا من السجل الفعلي
    ar_title_a = ("بلومبرغ: واردات أميركا من النفط السعودي تهبط إلى "
                 "الصفر في يوليو 2026")
    ar_title_b = "لأول مرة منذ 1985.. صادرات النفط السعودي إلى أميركا تهبط للصفر"
    ar_art_a = Article(title=ar_title_a, link="https://a.example/1", summary="",
                       source_name="Bloomberg", region="global", weight=1.0,
                       published=datetime.now(timezone.utc), publisher="Bloomberg")
    ar_art_b = Article(title=ar_title_b, link="https://b.example/2", summary="",
                       source_name="Al Jazeera", region="global", weight=1.0,
                       published=datetime.now(timezone.utc), publisher="Al Jazeera")

    groups_latin = cluster([ar_art_a, ar_art_b], 0.62)
    check("rank.tokens اللاتيني الافتراضي لا يجمع عنوانين عربيين مختلفي الصياغة",
          len(groups_latin) == 2, str(len(groups_latin)))

    vcfg = cfg.get("verify", {}) or {}
    verify_threshold = float(vcfg.get("title_similarity", 0.62))
    groups_bilingual = cluster([ar_art_a, ar_art_b], verify_threshold,
                               token_fn=verify.norm_tokens)
    check("مطبّع request.norm_tokens في rank.cluster يجمع عنوانين عربيين عن الحدث نفسه",
          len(groups_bilingual) == 1, str(len(groups_bilingual)))

    # verify.search يمرر التطبيع ثنائي اللغة والحد المضبوط في config.yaml —
    # لا القيم القديمة الثابتة في الكود (rank.tokens اللاتيني وحد 0.62)
    seen_search_calls: list[dict] = []
    real_rank_for_search = evidence.rank

    def _spy_rank_search(articles, selection, merge_cfg=None, token_fn=None,
                         keep_google_links=False):
        seen_search_calls.append({"token_fn": token_fn,
                                  "title_similarity": selection.get("title_similarity")})
        return real_rank_for_search(articles, selection, merge_cfg=merge_cfg,
                                    token_fn=token_fn,
                                    keep_google_links=keep_google_links)

    evidence.rank = _spy_rank_search
    evidence.fetch_source = lambda src, max_age_hours: [ar_art_a]
    try:
        verify.search("واردات نفط سعودي", cfg, 7)
    finally:
        evidence.fetch_source = real_fetch_source
        evidence.rank = real_rank_for_search
    check("verify.search يمرر request.norm_tokens كمطبّع تجميع",
          seen_search_calls and seen_search_calls[-1]["token_fn"] is verify.norm_tokens)
    check("verify.search يمرر verify.title_similarity من config.yaml لا 0.62 الثابتة",
          seen_search_calls and seen_search_calls[-1]["title_similarity"] == verify_threshold)

    # gather_evidence يرتّب المرشحين بمدى تطابق كلماتهم مع نص الواقعة نفسها،
    # لا بترتيب articles القادم من درجة الترند في search()/rank() — درجة
    # الترند مقياس نشر لا صلة (Issue #132 تعليق لاحق: الموضوع الأكثر تحديدًا
    # كان الأقل ترندًا فخرج من نافذة القراءة الأولى قبل أن يُحاوَل جلبه)
    generic_first = Article(
        title="تغطية عامة لسوق النفط العالمي", link="https://g.example/1",
        summary="أخبار متفرقة عن أسواق الطاقة", source_name="Generic",
        region="global", weight=2.0, published=datetime.now(timezone.utc),
        publisher="Generic")
    specific_second = Article(
        title="توقف واردات النفط السعودي لأمريكا 1985", link="https://s.example/2",
        summary="", source_name="Specific", region="global", weight=0.5,
        published=datetime.now(timezone.utc), publisher="Specific")

    read_order: list[str] = []

    def _fake_gather_order(members, limit=2):
        read_order.extend(m["name"] for m in members)
        return [{"name": m["name"], "text": f"نص {m['name']}"} for m in members[:limit]], []

    extract.gather = _fake_gather_order
    try:
        verify.gather_evidence(
            [generic_first, specific_second], cfg,
            "توقف واردات النفط السعودي لأمريكا منذ عام 1985")
    finally:
        extract.gather = real_extract_gather

    check("المرشح الأكثر تطابقًا مع نص الواقعة يُقرأ أولًا رغم ترتيبه الثاني في articles",
          read_order and read_order[0] == "Specific", str(read_order))

    # الإصلاح الأخير (Issue #132 تعليق لاحق): نفس نتائج البحث بالضبط، بصياغتَي
    # claim["text"] مختلفتين تمامًا لكن بنفس entities — gather_evidence يجب أن
    # تُنتج نفس ترتيب المرشحين ونفس ما يُقرأ فعليًا حين تُستعمل entities (لا
    # text) لحساب الصلة. تشخيص سابق قاس هذا فعليًا: نفس المرشحين رُتِّبوا
    # بشكل مختلف جوهريًا بين صياغتين لنفس الحقيقة قبل هذا الإصلاح.
    wiring_claim_a = {"text": "توقفت واردات أمريكا من النفط السعودي بالكامل "
                              "لأول مرة منذ 1985", "entities": wiring_entities}
    wiring_claim_b = {"text": "انخفضت واردات الولايات المتحدة من النفط الخام "
                              "السعودي إلى الصفر، حسب تقرير بلومبرغ في 1985",
                      "entities": list(wiring_entities)}
    check("نص الصلة المشتق من entities متطابق لصياغتين مختلفتين تمامًا",
          verify._entities_text(wiring_claim_a) ==
          verify._entities_text(wiring_claim_b) == " ".join(wiring_entities))

    read_order_a: list[str] = []
    read_order_b: list[str] = []

    def _fake_gather_capture(target):
        def _inner(members, limit=2):
            target.extend(m["name"] for m in members)
            return [], []
        return _inner

    same_search_results = [generic_first, specific_second]
    extract.gather = _fake_gather_capture(read_order_a)
    try:
        verify.gather_evidence(list(same_search_results), cfg,
                               verify._entities_text(wiring_claim_a))
    finally:
        extract.gather = real_extract_gather

    extract.gather = _fake_gather_capture(read_order_b)
    try:
        verify.gather_evidence(list(same_search_results), cfg,
                               verify._entities_text(wiring_claim_b))
    finally:
        extract.gather = real_extract_gather

    check("نفس نتائج البحث بصياغتَي claim['text'] مختلفتين لكن بنفس entities "
          "تُنتج نفس ترتيب المرشحين ونفس ما يُقرأ",
          read_order_a == read_order_b and read_order_a != [],
          f"{read_order_a} != {read_order_b}")

    # الوزن يفاضل بين ناشرين بصلة متقاربة، لا يُقصي ناشرًا شديد الصلة كليًا
    # (Issue #132 تعليق لاحق ثانٍ: فرز تتابعي سابق -وزن ثم -صلة كان يُقصي
    # مرشّحًا شديد الصلة بوزن أقل كليًا مهما بلغت صلته، فتراجع حكم فعلي من
    # واقعتين مؤكَّدتين إلى واحدة بعد تفعيل ترتيب الوزن — الدرجة المركّبة
    # (وزن + صلة) هي الإصلاح: تُرجِّح الوزن عند تقارب الصلة فقط، لا مطلقًا)
    tied_trusted = Article(
        title="توقف واردات النفط السعودي لأمريكا 1985", link="https://bloomberg.example/3",
        summary="", source_name="Bloomberg", region="global", weight=1.0,
        published=datetime.now(timezone.utc), publisher="Bloomberg")
    tied_unknown = Article(
        title="توقف واردات النفط السعودي لأمريكا 1985", link="https://unknown.example/4",
        summary="", source_name="موقع مجهول", region="global", weight=1.0,
        published=datetime.now(timezone.utc), publisher="موقع مجهول")

    read_order2: list[str] = []

    def _fake_gather_order2(members, limit=2):
        read_order2.extend(m["name"] for m in members)
        return [{"name": m["name"], "text": f"نص {m['name']}"} for m in members[:limit]], []

    extract.gather = _fake_gather_order2
    try:
        # عنوانان متطابقان (صلة متساوية) — لو تجاهلت الدرجة المركّبة الوزن
        # كليًا لتساوى الترتيب بلا معيار حاسم؛ الوزن هو ما يحسم عند التعادل
        verify.gather_evidence(
            [tied_unknown, tied_trusted], cfg,
            "توقف واردات النفط السعودي لأمريكا منذ عام 1985")
    finally:
        extract.gather = real_extract_gather

    check("عند تقارب الصلة، الوزن يُرجّح الناشر الموثوق أولًا رغم ترتيبه "
          "الثاني في articles",
          read_order2 and read_order2[0] == "Bloomberg", str(read_order2))

    # الأهم: مرشّح شديد الصلة بوزن افتراضي منخفض لا يخرج من نافذة القراءة
    # الضيقة رغم خمسة مرشحين موثوقين بلا أي صلة بنص الواقعة (هذا بالضبط ما
    # سبب التراجع الفعلي المُبلَّغ عنه — Issue #132 تعليق لاحق ثانٍ). العنوان
    # يتجنّب عمدًا كلمة "عام" (كانت تشترك صدفة مع "منذ عام 1985" في claim_text
    # فترفع صلة هؤلاء إلى 1 لا صفر — تشخيص Issue #373، تعليق الموافقة الخامس
    # عشر: بعد سقف RELEVANCE_CAP، هذا التشارك العرَضي كان سيقلب الشاهد نفسه —
    # موثوق بصلة عرَضية=1 يهزم مجهولًا شديد الصلة بعد القص، بعكس ما يوثّقه هذا
    # الاختبار أصلًا) فتبقى صلتهم صفرًا فعليًا كما يصف اسم المتغيّر
    trusted_irrelevant = [
        Article(title=f"خبر غير متعلق البتة رقم {i}", link=f"https://trusted{i}.example/1",
               summary="", source_name=name, region="global", weight=1.0,
               published=datetime.now(timezone.utc), publisher=name)
        for i, name in enumerate(["Reuters", "Associated Press", "AFP", "BBC", "Al Jazeera"])
    ]
    relevant_unknown = Article(
        title="توقف واردات النفط السعودي لأمريكا 1985",
        link="https://unknown.example/5", summary="",
        source_name="موقع مجهول شديد الصلة", region="global", weight=1.0,
        published=datetime.now(timezone.utc), publisher="موقع مجهول شديد الصلة")

    read_order3: list[str] = []

    def _fake_gather_order3(members, limit=1):
        read_order3.extend(m["name"] for m in members)
        return [], []

    narrow_cfg = dict(cfg)
    narrow_cfg["verify"] = {**cfg["verify"], "read_per_claim": 1}  # نافذة ضيقة فعليًا

    extract.gather = _fake_gather_order3
    try:
        verify.gather_evidence(
            trusted_irrelevant + [relevant_unknown], narrow_cfg,
            "توقف واردات النفط السعودي لأمريكا منذ عام 1985")
    finally:
        extract.gather = real_extract_gather

    check("مرشّح شديد الصلة منخفض الوزن لا يُقصى من نافذة القراءة رغم خمسة "
          "مرشحين موثوقين بلا صلة — الدرجة المركّبة تمنع إقصاءه كليًا",
          "موقع مجهول شديد الصلة" in read_order3, str(read_order3))

    # استعادة كل ما بقي معطوبًا من محاكاة أعلاه (search/gather_evidence
    # استُعيدتا سابقًا داخل الدالة لأن اختبارات لاحقة هنا احتاجت شكلهما
    # الحقيقي؛ الأربعة التالية لم تُستعمل حقيقيةً بعد استبدالها فبقيت بلا
    # استعادة حتى الآن)
    verify.extract_claims = real_extract_claims
    verify.judge_fact = real_judge_fact
    verify.judge_question = real_judge_question
    verify._client = real_client


def test_verify_draft() -> None:
    """المرحلة الثانية من التحقق (Issue #334): صياغة مسودة من المؤكَّد وحده.
    الاختبارات الثمانية المطلوبة في الـ Issue الأصلي زائد الأربعة الإضافية
    من تعليقات الموافقة — رقّمت بنفس ترقيم التعليقات."""
    from src import verify, verify_draft

    real_client = writer._client
    real_find_images = verify_draft.find_images
    verify_draft.find_images = lambda *a, **kw: []  # لا شبكة إطلاقًا هنا

    # attempt() تشترط الآن صراحةً أن التشغيل يُعلن صلاحية الكتابة (تعليق ما
    # قبل الدمج، نقطة 1) — الاختبارات هنا تُحاكي بيئة verify.yml المحدَّث
    # فتُعلنها، إلا اختبار الغياب نفسه أدناه الذي يزيلها عمدًا
    real_write_enabled = os.environ.get(verify_draft.WRITE_ENABLED_ENV)
    os.environ[verify_draft.WRITE_ENABLED_ENV] = "true"

    class _DBlock:
        def __init__(self, type_, text=None, input=None):
            self.type = type_
            self.text = text
            self.input = input

    class _DResp:
        def __init__(self, content, stop_reason="end_turn", usage=None):
            self.content = content
            self.stop_reason = stop_reason
            self.usage = usage

    class _CapturingMessages:
        def __init__(self, tool_input, calls):
            self._tool_input = tool_input
            self._calls = calls

        def create(self, **kw):
            self._calls.append(kw)
            return _DResp([_DBlock("tool_use", input=self._tool_input)])

    class _CapturingClient:
        def __init__(self, tool_input, calls):
            self.messages = _CapturingMessages(tool_input, calls)

    calls: list[dict] = []

    def install(tool_input):
        calls.clear()
        writer._client = lambda: _CapturingClient(tool_input, calls)

    cfg = load_config()

    SRC_BBC_TEXT = ("أعلنت وزارة الطاقة أن الإنتاج اليومي بلغ خمسة ملايين "
                    "برميل خلال الشهر الماضي وفق بيان رسمي نُشر الثلاثاء "
                    "الماضي في العاصمة")
    SRC_REUTERS_TEXT = ("قالت وكالة رويترز إن الشركة الوطنية أكدت الرقم "
                        "نفسه في مؤتمر صحفي عقد لاحقًا مساء الأربعاء")
    ARTICLE_BODY = ("مقال ملصق يزعم أن الإنتاج انخفض بشكل كبير الشهر "
                    "الماضي بسبب أعطال فنية متكررة في منصات الاستخراج "
                    "الرئيسية بحسب مصادر مقرَّبة من الوزارة")

    central = {
        "text": "بلغ الإنتاج اليومي خمسة ملايين برميل الشهر الماضي",
        "index": 0, "status": verify.STATUS_CONFIRMED,
        "supporting": ["BBC"], "supporting_weighted": [], "contradicting": [],
        "evidence_basis": verify.EVIDENCE_FULL_TEXT,
        "sources": [{"name": "BBC", "link": "https://bbc.example/1",
                    "text": SRC_BBC_TEXT,
                    "image_candidates": ["https://bbc.example/1.jpg"]}],
    }
    second = {
        "text": "أكدت الشركة الوطنية الرقم نفسه في مؤتمر صحفي",
        "index": 1, "status": verify.STATUS_CONFIRMED,
        "supporting": ["Reuters"], "supporting_weighted": [], "contradicting": [],
        "evidence_basis": verify.EVIDENCE_FULL_TEXT,
        "sources": [{"name": "Reuters", "link": "https://reuters.example/1",
                    "text": SRC_REUTERS_TEXT, "image_candidates": []}],
    }
    near = {
        "text": "قد يرتفع الإنتاج مستقبلًا حسب مصدر واحد قوي",
        "index": 2, "status": verify.STATUS_NEAR_CONFIRMED,
        "supporting": ["Bloomberg"], "supporting_weighted": [], "contradicting": [],
        "evidence_basis": verify.EVIDENCE_FULL_TEXT,
        "sources": [{"name": "Bloomberg", "link": "https://bloomberg.example/1",
                    "text": "نص بلومبرغ", "image_candidates": []}],
    }
    single = {
        "text": "زعم موقع مجهول أن الأرباح ارتفعت أربعين بالمئة",
        "index": 3, "status": verify.STATUS_SINGLE,
        "supporting": ["موقع مجهول"], "supporting_weighted": [], "contradicting": [],
        "evidence_basis": verify.EVIDENCE_HEADLINES_ONLY,
        "sources": [{"name": "موقع مجهول", "link": "https://unknown.example/1",
                    "text": "نص موقع مجهول", "image_candidates": []}],
    }

    def _result(facts, topic="موضوع المقال الملصق الفعلي الذي لا يجوز أن يظهر في البرومبت"):
        return {"ok": True, "topic": topic, "facts": facts, "opinions": [],
               "questions": [], "contradictions": [], "verdict": True,
               "verdict_reason": "اختبار"}

    CLEAN_POST = {
        "newsworthy": True, "category": "اقتصاد", "angle": "خبر",
        "image_headline": "إنتاج النفط يرتفع لخمسة ملايين برميل",
        "post_title": "ارتفاع الإنتاج اليومي إلى خمسة ملايين برميل",
        "post_body": "أكدت مصادر مستقلة متعددة أن معدل الضخ اليومي وصل "
                     "لأعلى مستوى منذ أشهر، مدعومًا بتصريحات رسمية متطابقة "
                     "من جهتين منفصلتين خلال الأسبوع نفسه.",
        "hashtags": ["نفط", "طاقة"], "analysis": "",
    }

    # 1) شبه مؤكَّدة ومصدر واحد لا يظهران في المسودة (البرومبت المرسل تحديدًا)
    # 3) مؤكَّد كافٍ ← مسودة مكتوبة بمسار store.py نفسه وبالمخطط نفسه
    install(dict(CLEAN_POST))
    result = _result([central, near, single, second])
    outcome = verify_draft.attempt(result, ARTICLE_BODY, 132, cfg)
    check("1) مسودة أُنتجت من الوقائع المؤكَّدة الكافية", outcome["produced"], outcome["reason"])
    prompt_sent = calls[-1]["messages"][0]["content"] if calls else ""
    check("1) نص الواقعة شبه المؤكَّدة غائب عن البرومبت المرسل",
          near["text"] not in prompt_sent)
    check("1) نص الواقعة بمصدر واحد غائب عن البرومبت المرسل",
          single["text"] not in prompt_sent)
    check("1) نص الواقعة المحورية المؤكَّدة حاضر في البرومبت",
          central["text"] in prompt_sent)
    check("1) نص الواقعة المؤكَّدة الثانية حاضر في البرومبت",
          second["text"] in prompt_sent)

    loaded = store.load_draft(outcome["draft_id"])
    check("3) المسودة محفوظة فعليًا عبر store.load_draft بنفس المعرّف",
          loaded is not None)
    if loaded:
        _, saved = loaded
        check("3) المسودة معلَّمة بحقل المنشأ verify",
              saved.get("origin") == "verify")
        check("3) المسودة تحمل رقم Issue التحقق الأصلي",
              saved.get("verify_issue") == 132)
        check("3) المسودة بحالة pending كأي مسودة عادية",
              saved.get("status") == "pending")
        check("3) رابط المصدر في المسودة رابط مصدر مؤكِّد لا رابط مقال ملصق "
              "(لا رابط له أصلًا)",
              saved.get("source", {}).get("link") in
              ("https://bbc.example/1", "https://reuters.example/1"))
        check("3) نفس مخطط drafts/ (id/arabic/caption/image/source) بلا نقص",
              {"id", "arabic", "caption", "image", "source"} <= set(saved.keys()))
        # نقطة 3 من تعليق ما قبل الدمج: حقل الروابط/الناشرين يُملأ من
        # المصادر المؤكِّدة وحدها؛ رابط المقال الملصق واسم ناشره لا يظهران
        # في المنشور — لا يوجد لهما أصلًا حقل في هذا المسار (لا رابط للمقال
        # الملصق في مدخلات verify.py أساسًا) فالضمان بنيوي لا شرطًا مضافًا
        check("3) publishers في المسودة الناشرَين المؤكِّدَين حصرًا",
              saved.get("source", {}).get("publishers") == ["BBC", "Reuters"],
              saved.get("source", {}).get("publishers"))
        # publish.py يعلّق بالمصدر من draft["source"]["link"]/["publishers"]
        # حصرًا — نفس الحقلين المبنيين هنا من المصادر المؤكِّدة فقط، فتعليق
        # النشر لا يذكر رابط المقال الملصق ولا اسم ناشره بأي حال (لا يوجد
        # لهما حقل أصلًا في هذا المسار)
        from src import publish as publish_mod
        first_comment = publish_mod.first_comment_for(saved, cfg)
        check("3) تعليق النشر الأول يذكر رابط مصدر مؤكِّد والناشرَين المؤكِّدَين حصرًا",
              first_comment == "المصدر: BBC، Reuters\nhttps://bbc.example/1",
              first_comment)

    # 2) مؤكَّد غير كافٍ ← لا مسودة، وسبب امتناع محدد في التقرير
    outcome_insuff = verify_draft.attempt(_result([central]), ARTICLE_BODY, 132, cfg)
    check("2) واقعة مؤكَّدة وحيدة غير كافية ← لا مسودة", not outcome_insuff["produced"])
    check("2) السبب يذكر الحد الأدنى تحديدًا لا رسالة عامة",
          "الحد الأدنى" in outcome_insuff["reason"], outcome_insuff["reason"])
    section2 = verify_draft.build_report_section(outcome_insuff)
    check("2) قسم التقرير يحمل سبب الامتناع المحدد", outcome_insuff["reason"] in section2)

    outcome_central_bad = verify_draft.attempt(
        _result([dict(near, index=0), second]), ARTICLE_BODY, 132, cfg)
    check("2) واقعة محورية غير مؤكَّدة رغم كفاية العدد ← لا مسودة",
          not outcome_central_bad["produced"])
    check("2) السبب يذكر الواقعة المحورية بنصها",
          "المحورية" in outcome_central_bad["reason"] and
          near["text"] in outcome_central_bad["reason"])

    # البند 1 (Issue #339): فصل مُحدِّدات الإسناد في extract_claims يغيّر
    # ترتيب الاستخراج — مُحدِّد مفصول («الانضمام معلَن رسميًا») قد يخرج قبل
    # ادّعاء الحدث نفسه، فلا يجوز أن يصير هو "الواقعة المحورية" لمجرد أنه
    # facts[0]. _central_fact/attempt() يتخطيانه صراحة للحدث الفعلي.
    QUALIFIER_SRC_TEXT = "أكد بيان رسمي مصري تفاصيل الانضمام صراحة لوكالة محلية"
    qualifier_fact = {
        "text": "الانضمام معلَن رسميًا من الجهة المصرية",
        "index": 0, "status": verify.STATUS_SINGLE, "is_qualifier": True,
        "supporting": ["ناشر التأكيد"], "supporting_weighted": [], "contradicting": [],
        "evidence_basis": verify.EVIDENCE_FULL_TEXT,
        "sources": [{"name": "ناشر التأكيد", "link": "https://qualifier.example/1",
                    "text": QUALIFIER_SRC_TEXT, "image_candidates": []}],
    }
    check("_central_fact تتخطى مُحدِّدًا مفصولًا في facts[0] لتعتمد الحدث "
          "الفعلي محوريًا",
          verify_draft._central_fact(
              [qualifier_fact, dict(central, index=1)])["text"] == central["text"])
    check("_central_fact تتراجع لـ facts[0] حين كل الوقائع مُحدِّدات (حافة "
          "نادرة) بدل الانهيار",
          verify_draft._central_fact([qualifier_fact]) is qualifier_fact)

    result_with_qualifier = _result(
        [qualifier_fact, dict(central, index=1), dict(second, index=2)])
    ok_q, reason_q = verify_draft.sufficiency(result_with_qualifier["facts"], cfg)
    check("sufficiency() تتجاوز مُحدِّدًا غير مؤكَّد في facts[0] وتعتمد الحدث "
          "الفعلي محوريًا", ok_q, reason_q)

    outcome_q = verify_draft.attempt(result_with_qualifier, ARTICLE_BODY, 132, cfg)
    check("1b) مُحدِّد إسناد غير مؤكَّد في facts[0] لا يمنع المسودة",
          outcome_q["produced"], outcome_q["reason"])
    check("1b) central_text/central_index المُبلَّغان يشيران للحدث الفعلي "
          "(index 1) لا المُحدِّد المفصول (index 0)",
          outcome_q["central_text"] == central["text"] and
          outcome_q["central_index"] == 1)
    loaded_q = store.load_draft(outcome_q["draft_id"]) if outcome_q["produced"] else None
    if loaded_q:
        _, saved_q = loaded_q
        check("1b) عنوان مصدر المسودة نص الحدث لا نص المُحدِّد المفصول",
              saved_q.get("source", {}).get("title") == central["text"])

    # مُحدِّد الإسناد قد يكون مؤكَّدًا هو أيضًا (بيان رسمي أيّده مصدران
    # مستقلان) — لا يزال يجب ألا يتصدَّر عنوان/مصدر المسودة على الحدث نفسه
    # رغم تصدُّره الترتيب الخام (facts[0]) وconfirmed الخام معًا
    qualifier_confirmed = dict(qualifier_fact, status=verify.STATUS_CONFIRMED,
                               supporting=["ناشر التأكيد", "ناشر ثانٍ"])
    result_q_confirmed = _result(
        [qualifier_confirmed, dict(central, index=1), dict(second, index=2)])
    outcome_qc = verify_draft.attempt(result_q_confirmed, ARTICLE_BODY, 132, cfg)
    check("1c) مُحدِّد إسناد مؤكَّد أيضًا لا يمنع المسودة",
          outcome_qc["produced"], outcome_qc["reason"])
    loaded_qc = store.load_draft(outcome_qc["draft_id"]) if outcome_qc["produced"] else None
    if loaded_qc:
        _, saved_qc = loaded_qc
        check("1c) عنوان مصدر المسودة يبقى نص الحدث حتى لو كان المُحدِّد "
              "مؤكَّدًا هو أيضًا ومتصدرًا facts الخام",
              saved_qc.get("source", {}).get("title") == central["text"])

    # 4) تطابق لفظي مع نص المقال ← المسودة مرفوضة، بلا إعادة محاولة
    copied_from_article = " ".join(ARTICLE_BODY.split()[:9])
    install({**CLEAN_POST, "post_body": f"نص افتتاحي. {copied_from_article} وبقية المتن."})
    outcome4 = verify_draft.attempt(_result([central, second]), ARTICLE_BODY, 132, cfg)
    check("4) تطابق لفظي مع المقال الملصق ← رفض", not outcome4["produced"])
    check("4) سبب الرفض يذكر المقال الملصق تحديدًا",
          "المقال الملصق" in outcome4["reason"], outcome4["reason"])
    check("4) استدعاء واحد فقط — بلا إعادة محاولة بعد رفض التطابق",
          len(calls) == 1)

    # 5) البرومبت المرسل لا يحتوي نص المقال ولا عنوانه
    install(dict(CLEAN_POST))
    verify_draft.attempt(_result([central, second]), ARTICLE_BODY, 132, cfg)
    prompt5 = calls[-1]["messages"][0]["content"]
    check("5) نص المقال الملصق غائب كليًا عن البرومبت", ARTICLE_BODY not in prompt5)
    check("5) عنوان/موضوع المقال (topic) غائب كليًا عن البرومبت",
          "موضوع المقال الملصق الفعلي" not in prompt5)

    # 6) النظام المستعمل هو writer.SYSTEM_PROMPT عينه — تطابق مطلق لا تشابه
    check("6) system المرسل مطابقة حرفية لـ writer.SYSTEM_PROMPT",
          calls[-1]["system"][0]["text"] == writer.SYSTEM_PROMPT)

    # 7) مصادر تخالف نتيجة المقال ← المسودة تتبع المصادر لا المقال
    contradicting_article = ("مقال ملصق يزعم أن الإنتاج انخفض إلى ثلاثة "
                             "ملايين برميل فقط بسبب أعطال متكررة")
    install(dict(CLEAN_POST))  # المسودة (من المصادر) تقول "ارتفع... خمسة ملايين"
    outcome7 = verify_draft.attempt(
        _result([central, second]), contradicting_article, 132, cfg)
    check("7) مسودة تخالف رواية المقال الملصق لفظيًا لكنها تُقبل لأنها من "
          "المصادر المؤكِّدة", outcome7["produced"], outcome7["reason"])
    check("7) رقم/رواية المقال المخالفة غائبة عن البرومبت أصلًا",
          "ثلاثة ملايين" not in calls[-1]["messages"][0]["content"])

    # 8) فشل مصدر أثناء الصياغة (بلا رابط صالح) ← رسالة تحمل السبب، ولا مسودة
    broken_source_fact = {
        "text": "واقعة مؤكَّدة بمصدر بلا رابط صالح",
        "index": 0, "status": verify.STATUS_CONFIRMED,
        "supporting": ["ناشر معطوب"], "supporting_weighted": [], "contradicting": [],
        "evidence_basis": verify.EVIDENCE_FULL_TEXT,
        "sources": [{"name": "ناشر معطوب", "link": "", "text": "نص بلا رابط",
                    "image_candidates": []}],
    }
    outcome8 = verify_draft.attempt(
        _result([broken_source_fact, second]), ARTICLE_BODY, 132, cfg)
    check("8) واقعة مؤكَّدة بلا مصدر برابط صالح ← لا مسودة", not outcome8["produced"])
    check("8) السبب يذكر المرحلة", "مرحلة صياغة المسودة" in outcome8["reason"])
    check("8) السبب يذكر نص الواقعة المتعثرة",
          broken_source_fact["text"] in outcome8["reason"])
    check("8) السبب يذكر اسم المصدر المعطوب", "ناشر معطوب" in outcome8["reason"])

    # 9) مقتطف مصدر منسوخ حرفيًا في المسودة ← رفض
    copied_from_source = " ".join(SRC_BBC_TEXT.split()[:8])
    install({**CLEAN_POST, "post_body": f"مقدمة قصيرة. {copied_from_source} وخاتمة."})
    outcome9 = verify_draft.attempt(_result([central, second]), ARTICLE_BODY, 132, cfg)
    check("9) تطابق لفظي مع مقتطف مصدر مؤكِّد ← رفض", not outcome9["produced"])
    check("9) سبب الرفض يذكر مقتطف مصدر مؤكِّد تحديدًا",
          "مصدر مؤكِّد" in outcome9["reason"], outcome9["reason"])

    # 9b) البند 2 (تعليق التنفيذ على PR #340): التتابع نفسه وارد حرفيًا في
    # مصدرين مستقلين مؤكِّدين (لا مصدر واحد كما في 9 أعلاه) ← ليس نسخًا،
    # فلا يُرفض — الاستثناء العابر للمصادر لا يُضعف العتبة على مصدر واحد
    SHARED_PHRASE = "بلغ الإنتاج اليومي خمسة ملايين برميل خلال الشهر الماضي فقط"
    multi_source_bbc = {**central, "sources": [
        {"name": "BBC", "link": "https://bbc.example/1",
         "text": f"{SHARED_PHRASE} وفق بيان رسمي", "image_candidates": []}]}
    multi_source_reuters = {**second, "sources": [
        {"name": "Reuters", "link": "https://reuters.example/1",
         "text": f"قالت مصادر مطّلعة إن {SHARED_PHRASE} حسب الأرقام الرسمية",
         "image_candidates": []}]}
    install({**CLEAN_POST, "post_body": f"مقدمة قصيرة. {SHARED_PHRASE} وخاتمة."})
    outcome9b = verify_draft.attempt(
        _result([multi_source_bbc, multi_source_reuters]), ARTICLE_BODY, 132, cfg)
    check("9b) تتابع مشترك بين مصدرين مستقلين مؤكِّدين ← لا يُرفض (ليس نسخًا "
          "من أحدهما)", outcome9b["produced"], outcome9b["reason"])

    # 10) اقتباس بين علامتين غير موجود في أي مقتطف مؤكِّد ← رفض
    fabricated_quote = "«تصريح لم يرد حرفيًا في أي مصدر مؤكِّد إطلاقًا هنا»"
    install({**CLEAN_POST, "post_body": f"{CLEAN_POST['post_body']} {fabricated_quote}"})
    outcome10 = verify_draft.attempt(_result([central, second]), ARTICLE_BODY, 132, cfg)
    check("10) اقتباس مختلَق غير موجود في أي مقتطف مؤكِّد ← رفض",
          not outcome10["produced"])
    check("10) سبب الرفض يذكر الاقتباس", "اقتباس" in outcome10["reason"])

    # اقتباس موجود فعليًا حرفيًا في مقتطف مصدر مؤكِّد يُستثنى من الفحص ولا يُرفض
    genuine_quote_words = " ".join(SRC_REUTERS_TEXT.split()[:6])
    install({**CLEAN_POST, "post_body":
            f"{CLEAN_POST['post_body']} «{genuine_quote_words}»"})
    outcome10b = verify_draft.attempt(_result([central, second]), ARTICLE_BODY, 132, cfg)
    check("10) اقتباس منسوب موثَّق فعليًا في مقتطف مصدر مؤكِّد لا يُرفض",
          outcome10b["produced"], outcome10b["reason"])

    # 11) newsworthy: false رغم كفاية المؤكَّد ← امتناع مشروع، والسبب حرفيًا في التقرير
    install({"newsworthy": False, "reject_reason": "خبر مشاهير", "category": "عالم",
            "post_title": "", "post_body": "", "hashtags": []})
    outcome11 = verify_draft.attempt(_result([central, second]), ARTICLE_BODY, 132, cfg)
    check("11) newsworthy=false رغم كفاية المؤكَّد ← لا مسودة", not outcome11["produced"])
    check("11) سبب الرفض التحريري منقول حرفيًا كما أعاده النموذج",
          "خبر مشاهير" in outcome11["reason"], outcome11["reason"])
    section11 = verify_draft.build_report_section(outcome11)
    check("11) سبب الرفض التحريري يظهر في قسم التقرير أيضًا",
          "خبر مشاهير" in section11)

    # حقل المنشأ لا يمنح أي امتياز في المراجعة: parse_approved/parse_rejects
    # يعملان على المعرّف والمربعات فقط بصرف النظر عن وجوده (نقطة 5 من الموافقة)
    origin_draft = {
        "id": "ab01cd23ef45", "score": 1.0, "trend_score": 0.0, "origin": "verify",
        "verify_issue": 132, "image": "drafts/x/a.jpg", "caption": "نص",
        "source": {"link": "https://bbc.example/1", "publishers": ["BBC"]},
        "arabic": {"post_title": "عنوان", "urgent": False, "category": "اقتصاد"},
    }
    origin_body = review.build_issue_body([origin_draft], "u/r", "main")
    origin_body_checked = tick_marker(origin_body, "draft:ab01cd23ef45")
    check("حقل origin لا يمنع اعتماد المسودة عبر parse_approved كالمعتاد",
          review.parse_approved(origin_body_checked) == ["ab01cd23ef45"])
    check("لا رفض بلا تعليم — حقل origin لا يفرض رفضًا افتراضيًا",
          review.parse_rejects(origin_body_checked) == [])

    # 12) فشل نداء النموذج نفسه (شبكة/حصة/استجابة مشوَّهة) أثناء الصياغة —
    # لا مسودة، ورسالة تذكر المرحلة والسبب المحدد لا رسالة عامة (نقطة 4 من
    # تعليق ما قبل الدمج على Issue #334؛ الاختبار 8 غطّى مصدرًا معطوبًا
    # قبل نداء الشبكة — هنا العطل في نداء الشبكة نفسه، عبر writer._call_model
    # المشترك بعد استخراجه)
    class _FailingMessages:
        def create(self, **kw):
            raise ValueError("Connection error: تعذّر الاتصال بخادم Anthropic")

    class _FailingClient:
        def __init__(self):
            self.messages = _FailingMessages()

    real_sleep = writer.time.sleep
    writer.time.sleep = lambda s: None  # بلا إبطاء حقيقي أثناء إعادة المحاولة في الاختبار
    writer._client = lambda: _FailingClient()
    try:
        outcome12 = verify_draft.attempt(_result([central, second]), ARTICLE_BODY, 132, cfg)
    finally:
        writer.time.sleep = real_sleep
    check("12) فشل نداء النموذج نفسه (عطل تقني) أثناء الصياغة ← لا مسودة",
          not outcome12["produced"])
    check("12) السبب يذكر المرحلة تحديدًا", "مرحلة صياغة المسودة" in outcome12["reason"],
          outcome12["reason"])
    check("12) السبب يذكر أنه فشل تقني لا رفض تحريري",
          "فشل تقني" in outcome12["reason"], outcome12["reason"])
    check("12) السبب يحمل تفصيل العطل الفعلي — لا «فشل التحقق» رسالة عامة",
          "تعذّر الاتصال" in outcome12["reason"], outcome12["reason"])

    # 13) صلاحية الكتابة غير معلَنة لهذا التشغيل (نقطة 1 من تعليق ما قبل
    # الدمج) ← امتناع فوري بلا أي نداء نموذج (دفاع في العمق قبل إنفاق أي
    # تكلفة). الملف القديم بلا VERIFY_DRAFT_WRITE_ENABLED كان سيصوغ محتوى
    # مكلفًا يُهمَل صامتًا لأن لا خطوة رفع تحفظه
    install(dict(CLEAN_POST))
    del os.environ[verify_draft.WRITE_ENABLED_ENV]
    try:
        outcome13 = verify_draft.attempt(_result([central, second]), ARTICLE_BODY, 132, cfg)
    finally:
        os.environ[verify_draft.WRITE_ENABLED_ENV] = "true"
    check("13) صلاحية الكتابة غير معلَنة لهذا التشغيل ← لا مسودة",
          not outcome13["produced"])
    check("13) السبب يذكر متغيّر البيئة تحديدًا",
          verify_draft.WRITE_ENABLED_ENV in outcome13["reason"], outcome13["reason"])
    check("13) لا نداء نموذج إطلاقًا — الامتناع يسبق أي تكلفة (دفاع في العمق)",
          calls == [])
    section13 = verify_draft.build_report_section(outcome13)
    check("13) سبب غياب صلاحية الكتابة يظهر في قسم التقرير أيضًا",
          verify_draft.WRITE_ENABLED_ENV in section13)

    writer._client = real_client
    verify_draft.find_images = real_find_images
    if real_write_enabled is None:
        os.environ.pop(verify_draft.WRITE_ENABLED_ENV, None)
    else:
        os.environ[verify_draft.WRITE_ENABLED_ENV] = real_write_enabled


def test_check_originality_signals() -> None:
    """إشارتا إعفاء لفحص الأصالة (تشخيص Issue #373، الجولة العاشرة) —
    بديل مبني على النصوص لا على شهادة النموذج على نفسه (مقترح "مصطلح
    رسمي" مرفوض صراحة: الفحص كله وُجد لأننا لا نثق بمخرَج النموذج). تتابع
    ورد في مصدر واحد فقط يُعفى من الرفض بلا رفع عتبة max_shared_run_words
    إن (أ) تكرر داخل نص ذلك المصدر نفسه ≥ repeat_min_count، أو (ب) ورد في
    وثيقة أخرى مقروءة بهوية ناشر موحَّدة مختلفة — لا نسخة أخرى للناشر نفسه."""
    from src import verify_draft

    cfg = load_config()
    check("config.yaml: verify_draft.repeat_within_source_min_count موجود وقابل للضبط",
          cfg.path("verify_draft.repeat_within_source_min_count") is not None)
    check("config.yaml: article.repeat_within_source_min_count موجود وقابل للضبط",
          cfg.path("article.repeat_within_source_min_count") is not None)

    run = "محكمة الجنايات الرابعة في دمشق برئاسة القاضي"  # 7 كلمات بالضبط
    draft = f"أصدرت {run} حكمًا بالإعدام."

    single_source = [{"name": "مصدر أول", "text": f"القصة: {run}. تفاصيل إضافية هنا."}]
    ok0, reason0, notes0 = verify_draft.check_originality(draft, "", single_source, 7)
    check("خط الأساس: تتابع من مصدر واحد بلا تكرار ولا ورود آخر ← رفض",
          ok0 is False and "تطابق لفظي" in reason0, (ok0, reason0))
    check("خط الأساس: بلا أي إعفاء مُسجَّل", notes0 == [], notes0)

    repeated_text = f"القصة: {run}. وأضاف بيان {run} أن الحكم نهائي."
    source_repeated = [{"name": "مصدر أول", "text": repeated_text}]
    ok_a, reason_a, notes_a = verify_draft.check_originality(
        draft, "", source_repeated, 7, repeat_min_count=2)
    check("إشارة (أ): تكرار التتابع داخل نص المصدر الواحد ≥2 يُعفي من الرفض",
          ok_a is True, reason_a)
    check("إشارة (أ): الإعفاء مُسجَّل صراحة — لا إعفاء صامت",
          bool(notes_a) and "إشارة أ" in notes_a[0], notes_a)

    extra_different = [{"name": "مصدر ثانٍ",
                        "text": f"وذكرت تقارير أخرى أن {run} أصدرت الحكم."}]
    ok_b, reason_b, notes_b = verify_draft.check_originality(
        draft, "", single_source, 7, extra_docs=extra_different)
    check("إشارة (ب): ورود التتابع في وثيقة أخرى مقروءة بهوية ناشر مختلفة يُعفي",
          ok_b is True, reason_b)
    check("إشارة (ب): الإعفاء مُسجَّل صراحة — لا إعفاء صامت",
          bool(notes_b) and "إشارة ب" in notes_b[0], notes_b)

    extra_same_name = [{"name": "مصدر أول", "text": f"نص آخر لنفس الناشر: {run}."}]
    ok_same, reason_same, _ = verify_draft.check_originality(
        draft, "", single_source, 7, extra_docs=extra_same_name)
    check("ضابط التوحيد: وثيقة أخرى بهوية الناشر نفسه (لا مختلفة) لا تُعفي عبر (ب)",
          ok_same is False, (ok_same, reason_same))

    # تكامل توحيد الهوية الفعلي (evidence._canonical_publisher): "الجزيرة
    # نت" و"Al Jazeera" يتشاركان الهوية نفسها — إن مرّرهما المستدعي بعد
    # التوحيد (كما تفعل article.py/verify_draft.py فعليًا)، نسخة الناشر
    # الأخرى بلغة مختلفة لا تُعفي عبر (ب): ليست مصدرًا مستقلًا ثانيًا
    canon_a = evidence._canonical_publisher("الجزيرة نت", cfg)
    canon_b = evidence._canonical_publisher("Al Jazeera", cfg)
    check("توحيد الهوية: الجزيرة نت وAl Jazeera يتشاركان الهوية الموحَّدة نفسها",
          canon_a == canon_b, (canon_a, canon_b))
    single_aljazeera = [{"name": canon_a, "text": f"القصة: {run}. تفاصيل إضافية هنا."}]
    extra_aljazeera_en = [{"name": canon_b, "text": f"story: {run} something."}]
    ok_canon, reason_canon, _ = verify_draft.check_originality(
        draft, "", single_aljazeera, 7, extra_docs=extra_aljazeera_en)
    check("ضابط التوحيد الفعلي: نسخة الجزيرة نت/Al Jazeera بعد التوحيد لا تُعفي "
          "عبر إشارة (ب) — نفس الناشر لا مصدر مستقل ثانٍ",
          ok_canon is False, (ok_canon, reason_canon))

    two_sources = [{"name": "مصدر أول", "text": f"{run} أصدرت الحكم."},
                  {"name": "مصدر ثانٍ", "text": f"وأكدت {run} ذلك."}]
    ok_two, reason_two, notes_two = verify_draft.check_originality(draft, "", two_sources, 7)
    check("الاستثناء الأصلي (مصدران مستقلان فأكثر) لا يزال ساريًا بلا تغيير",
          ok_two is True, reason_two)
    check("الاستثناء الأصلي يبقى صامتًا بلا سطر تبليغ جديد", notes_two == [], notes_two)

    # التبليغ (البند 2 من التنفيذ) يصل تقريري article.build_report
    # وverify_draft.build_report_section الفعليين — لا outcome الداخلي وحده
    from src import article
    fake_outcome_article = article._new_outcome()
    fake_outcome_article.update({"produced": True, "reason": "تجربة",
                                 "draft_id": "abc123", "originality_notes": notes_a})
    report_article = article.build_report(fake_outcome_article)
    check("article.build_report يعرض originality_notes حين تُوجَد",
          "تتابعات أُعفيت من فحص النسخ اللفظي" in report_article and
          notes_a[0] in report_article, report_article)

    fake_outcome_vd = {"produced": True, "reason": "تجربة", "draft_id": "abc123",
                       "central_text": "", "central_index": 0,
                       "originality_notes": notes_b}
    report_vd = verify_draft.build_report_section(fake_outcome_vd)
    check("verify_draft.build_report_section يعرض originality_notes حين تُوجَد",
          "تتابعات أُعفيت من فحص النسخ اللفظي" in report_vd and
          notes_b[0] in report_vd, report_vd)


def test_check_originality_trim() -> None:
    """تقليم حدّي قبل الرفض (تشخيص Issue #373، الجولة الثانية عشرة): نافذة
    سبع كلمات («فرع الأمن السياسي في درعا الذي كان» — شاهد حقيقي) تحمل نواة
    اسم مؤسسة (5 كلمات) لا بديل لصياغتها يمنعها فقط ذيل نحوي («الذي كان»)
    من إشارتَي (أ)/(ب) بطولها الكامل. التقليم يجرّب النواة بعد إسقاط كلمات
    وظيفية فقط (request._AR_STOP الموسَّعة) من الطرفين حتى min_core."""
    from src import verify_draft

    cfg = load_config()
    check("config.yaml: verify_draft.trim_min_core موجود وقابل للضبط",
          cfg.path("verify_draft.trim_min_core") is not None)
    check("config.yaml: article.trim_min_core موجود وقابل للضبط",
          cfg.path("article.trim_min_core") is not None)

    run7 = "فرع الأمن السياسي في درعا الذي كان"  # اسم مؤسسة (5) + ذيل نحوي (2)
    core = "فرع الأمن السياسي في درعا"
    draft = f"{run7} يشرف على الملف الأمني في المحافظة بالكامل."

    # إشارة (أ) مقلَّمة: النافذة الكاملة لا تتكرر، لكن نواتها (بلا الذيل)
    # تتكرر داخل نص المصدر الواحد نفسه ≥ repeat_min_count
    text_a = (f"ذكرت وثيقة رسمية أن {run7} يتبع وزارة الداخلية مباشرة. "
             f"وأضافت أن {core} أنشئ عام 1980 تقريبًا.")
    single_a = [{"name": "مصدر ثالث", "text": text_a}]
    ok_a, reason_a, notes_a = verify_draft.check_originality(draft, "", single_a, 7)
    check("إشارة (أ) مقلَّمة: النافذة الكاملة (بالذيل النحوي) لا تُعفى بطولها، "
          "لكن نواتها تُعفيها بعد تقليم الذيل",
          ok_a is True, reason_a)
    check("إشارة (أ) مقلَّمة: الإعفاء مُسجَّل صراحة ويذكر ما قُلِّم وطول النواة",
          bool(notes_a) and "مقلَّمة" in notes_a[0] and "الذي كان" in notes_a[0]
          and "5 كلمة" in notes_a[0], notes_a)

    # إشارة (ب) مقلَّمة: بلا تكرار داخل نفس المصدر، لكن النواة وحدها (بلا
    # الذيل) وردت في وثيقة أخرى مقروءة بهوية ناشر مختلفة
    text_b = f"{run7} يتبع وزارة الداخلية مباشرة في تنظيم أمني صارم."
    single_b = [{"name": "مصدر رابع", "text": text_b}]
    extra_b = [{"name": "مصدر خامس",
               "text": f"وقالت مصادر أخرى إن {core} أنشئ في ثمانينيات القرن الماضي."}]
    ok_b, reason_b, notes_b = verify_draft.check_originality(
        draft, "", single_b, 7, extra_docs=extra_b)
    check("إشارة (ب) مقلَّمة: النواة المقلَّمة وحدها ورادة في وثيقة أخرى تُعفي "
          "النافذة كاملة رغم أن ذيلها النحوي لم يرد هناك",
          ok_b is True, reason_b)
    check("إشارة (ب) مقلَّمة: الإعفاء مُسجَّل صراحة", bool(notes_b) and "مقلَّمة" in notes_b[0])

    # ضابط: بلا أي تكرار للنواة المقلَّمة في المصدر نفسه ولا في وثيقة أخرى
    # ← الرفض يبقى قائمًا، التقليم لا يُعفي تلقائيًا مجرد وجود ذيل نحوي
    single_reject = [{"name": "مصدر سادس", "text": text_b}]
    ok_none, reason_none, notes_none = verify_draft.check_originality(
        draft, "", single_reject, 7)
    check("ضابط: بلا نواة صالحة (لا تكرار ولا ورود آخر) ← الرفض يبقى قائمًا "
          "رغم وجود ذيل نحوي قابل للتقليم شكليًا",
          ok_none is False, (ok_none, reason_none))

    # ضابط القيد النحوي: كلمة مضمون (لا وظيفية) في الذيل تمنع التقليم كليًا —
    # حتى لو كانت نواة الاسم المؤسساتي وحدها (بلا الذيل) ستُعفى لولا الحرص
    run7_content = "فرع الأمن السياسي في درعا الوطني الجديد"  # ذيل صفتان لا أداتان
    draft_c = f"{run7_content} يشرف على الملف الأمني."
    text_c = (f"ذكرت وثيقة رسمية أن {run7_content} يتبع وزارة الداخلية. "
             f"وأضافت أن {core} أنشئ عام 1980.")
    single_c = [{"name": "مصدر سابع", "text": text_c}]
    ok_c, reason_c, notes_c = verify_draft.check_originality(draft_c, "", single_c, 7)
    check("ضابط القيد النحوي: ذيل من كلمات مضمون (صفات) لا يجوز تقليمه — الرفض "
          "يبقى قائمًا رغم تكرار النواة (بلا الذيل) في نفس المصدر",
          ok_c is False, (ok_c, reason_c))
    check("ضابط القيد النحوي: بلا سطر إعفاء مُسجَّل — لم يُعفَ شيء", notes_c == [], notes_c)


def test_check_originality_context() -> None:
    """تعليق الموافقة الثالث عشر على Issue #373 — ثلاثة بنود على
    check_originality: (1) تجريد بادئة «الـ» في _normalized_words بنفس شرط
    request.norm_tokens، (2) حد أدنى صريح TRIM_MIN_CORE_FLOOR=4 لتقليم
    min_core لا يُنزَل عنه بصرف النظر عمّا يُمرَّر، (3) رسالة الرفض النهائي
    تحمل الجملة الكاملة من مصدرها لا التتابع المقتطَع وحده — «الحكم البشري
    هو المعيار الذي لا يخطئ هنا»."""
    from src import verify_draft

    # (1) تجريد «الـ»: تتابع في مصدر واحد وتتابع مطابق دلاليًا في وثيقة
    # أخرى يختلفان حرفيًا بوجود/غياب «الـ» على كلمة واحدة فقط («الحكومة» في
    # المصدر الوحيد مقابل «حكومة» في الوثيقة الأخرى) — بلا تجريد «الـ» لن
    # يتطابقا فتفشل إشارة (ب)، ومع التجريد يتطابقان فتُعفي
    run_al = "الحكومة السورية في دمشق أصدرت بيانا رسميا"  # 7 كلمات، أولها معرَّف
    draft_al = f"وذكرت مصادر أن {run_al} اليوم."
    single_al = [{"name": "مصدر أول", "text": f"القصة: {run_al}. تفاصيل هنا."}]
    extra_al = [{"name": "مصدر ثانٍ",
                "text": "وأكدت مصادر أخرى أن حكومة السورية في دمشق أصدرت بيانا رسميا اليوم."}]
    ok_al, reason_al, notes_al = verify_draft.check_originality(
        draft_al, "", single_al, 7, extra_docs=extra_al)
    check("تجريد «الـ»: تتابع يختلف حرفيًا عن وثيقة أخرى بوجود/غياب أداة "
          "التعريف على كلمة واحدة فقط يُعفى الآن عبر إشارة (ب) بعد التطبيع",
          ok_al is True, (ok_al, reason_al))
    check("تجريد «الـ»: الإعفاء مُسجَّل صراحة (إشارة ب)",
          bool(notes_al) and "إشارة ب" in notes_al[0], notes_al)

    # (2) حد أدنى صريح للتقليم: نافذة سبع كلمات («فرع الأمن السياسي» + ذيل
    # من 4 كلمات وظيفية نظيفة — لا حروف بها ى/ة/همزة يُترجمها _AR_TRANS
    # فتفشل مطابقتها بصيغتها الخام في request._AR_STOP، وهي مشكلة توثيق
    # منفصلة تمامًا عن هذا التشخيص) واردة حرفيًا مرة واحدة في المصدر، تحمل
    # نواة من 3 كلمات فقط («فرع الأمن السياسي») تتكرر فعليًا مرتين في نص
    # المصدر نفسه — لكن كل نواة بطول 4 فأكثر (مع أول كلمة من الذيل) لا
    # تتكرر إطلاقًا. بمرور min_core=1 (أدنى من الحد الصريح عمدًا)، النتيجة
    # تبقى رفضًا — الحد الأدنى (4) يمنع الوصول لنواة الثلاث كلمات
    # المتكرِّرة، بصرف النظر عمّا طلبه المستدعي
    core3 = "فرع الأمن السياسي"
    tail4 = "التي كان دون كما"  # أربع كلمات نظيفة من request._AR_STOP
    window7 = f"{core3} {tail4}"
    draft_floor = f"وذكرت مصادر أن {window7} اليوم."
    text_floor = (f"ذكر التقرير أن {window7} يتبع الداخلية مباشرة. "
                 f"وأضاف أن {core3} معروف بذلك أيضًا.")
    single_floor = [{"name": "مصدر ثالث", "text": text_floor}]
    ok_floor1, reason_floor1, notes_floor1 = verify_draft.check_originality(
        draft_floor, "", single_floor, 7, repeat_min_count=2, min_core=1)
    check("الحد الأدنى الصريح (4): min_core=1 المطلوب صراحةً لا يُنزل الفحص "
          "دون 4 — نواة الثلاث كلمات المتكرِّرة تبقى خارج المحاولات فيبقى "
          "الرفض قائمًا رغم تكرارها الفعلي",
          ok_floor1 is False, (ok_floor1, reason_floor1))
    ok_floor4, reason_floor4, notes_floor4 = verify_draft.check_originality(
        draft_floor, "", single_floor, 7, repeat_min_count=2, min_core=4)
    check("الحد الأدنى الصريح (4): min_core=4 (على الحد بالضبط) يعطي النتيجة "
          "نفسها تمامًا — الحد الفعلي لا يتغيّر بتمرير قيمة أدنى",
          ok_floor4 is False and reason_floor4 == reason_floor1,
          (ok_floor4, reason_floor4, reason_floor1))

    # (3) الجملة الكاملة ومصدرها عند الرفض النهائي — لا التتابع وحده
    run_ctx = "محكمة الجنايات الرابعة في دمشق برئاسة القاضي"
    draft_ctx = f"وذكرت مصادر أن {run_ctx} أصدرت حكمًا بالإعدام اليوم."
    single_ctx = [{"name": "مصدر رابع", "link": "https://example.com/r4",
                  "text": f"القصة الكاملة: {run_ctx}. تفاصيل إضافية هنا لا صلة لها."}]
    ok_ctx, reason_ctx, notes_ctx = verify_draft.check_originality(
        draft_ctx, "", single_ctx, 7)
    check("الرفض النهائي (مصدر واحد بلا إعفاء) يذكر اسم المصدر كما كان دومًا",
          ok_ctx is False and "مصدر رابع" in reason_ctx, reason_ctx)
    check("الرفض النهائي (تعليق الموافقة الرابع عشر) يرفق رابط المصدر إلى جانب اسمه",
          "https://example.com/r4" in reason_ctx, reason_ctx)
    check("الرفض النهائي يحمل الجملة المقابلة من المصدر — لا التتابع المقتطَع وحده",
          "الجملة المقابلة في المصدر" in reason_ctx and "القصة الكاملة" in reason_ctx
          and "تفاصيل إضافية" not in reason_ctx,  # الجملة التالية لا تُقحَم معها
          reason_ctx)
    check("الرفض النهائي (تعليق الموافقة الرابع عشر) يحمل جملة المسودة نفسها أيضًا",
          "الجملة الكاملة في المسودة" in reason_ctx and "وذكرت مصادر أن" in reason_ctx,
          reason_ctx)

    # مصدر بلا رابط (حقل "link" غائب) — لا يظهر رابط، لا ينهار شيء
    single_no_link = [{"name": "مصدر خامس",
                       "text": f"القصة الكاملة: {run_ctx}. تفاصيل أخرى هنا."}]
    ok_nolink, reason_nolink, _ = verify_draft.check_originality(
        draft_ctx, "", single_no_link, 7)
    check("مصدر بلا حقل link: الرفض يعمل بلا انهيار، بلا رابط في الرسالة",
          ok_nolink is False and "مصدر خامس" in reason_nolink, reason_nolink)

    article_ctx = f"مقدمة عامة. {run_ctx} بحسب ما ذكرته وكالات محلية. خاتمة عامة."
    draft_ctx2 = f"وأفادت التقارير أن {run_ctx} صباح اليوم."
    ok_body, reason_body, notes_body = verify_draft.check_originality(
        draft_ctx2, article_ctx, [], 7)
    check("الرفض النهائي على تطابق مع المقال الملصق يحمل الجملة المقابلة منه أيضًا",
          ok_body is False and "الجملة المقابلة في المقال الملصق" in reason_body
          and "بحسب ما ذكرته وكالات محلية" in reason_body, reason_body)
    check("الرفض النهائي على المقال الملصق يحمل جملة المسودة نفسها أيضًا",
          "الجملة الكاملة في المسودة" in reason_body and "وأفادت التقارير أن" in reason_body,
          reason_body)


def test_check_originality_wa_pronoun_and_min_core_revert() -> None:
    """تعليق الموافقة الرابع عشر على Issue #373: (1) لا خفض لـ min_core —
    القيمة المُهيَّأة في config.yaml أُرجعت إلى 5 بعد أن أثبتت المحاكاة في
    تلك الجولة أن الخفض إلى 4 لا يجدي لصيغ تعريفية («لاعب ريال مدريد
    السابق»)، (2) فجوة «وهو» — الضمائر المنفصلة الملتصقة بواو العطف (وهو/
    وهي/وهم/وهن، وهي/هو/هم/هن منفصلة) أُضيفت إلى request._AR_STOP فتصير
    قابلة للتقليم كذيل نحوي مثل «كان»/«الذي» تمامًا.
    القيمة خُفِّضت من جديد إلى 4 لاحقًا (الحالة الخامسة، «هوي كا يان معروف
    بالصينية باسم شو»/verify_draft._name_link_exempt — انظر
    test_check_originality_name_link) — هذا الاختبار يوثّق تاريخ التغيير لا
    القيمة الحالية، فلا يفحص القيمة العددية بعد الآن."""
    from src import request, verify_draft

    cfg = load_config()
    check("(1) config.yaml: verify_draft.trim_min_core مضبوط (تاريخ: 5 ← 4 ← 5 ← 4)",
          cfg.path("verify_draft.trim_min_core") is not None, cfg.path("verify_draft.trim_min_core"))
    check("(1) config.yaml: article.trim_min_core مضبوط (تاريخ: 5 ← 4 ← 5 ← 4)",
          cfg.path("article.trim_min_core") is not None, cfg.path("article.trim_min_core"))
    check("(1) TRIM_MIN_CORE_FLOOR يبقى 4 بلا تغيير (حارس مستقل عن القيمة المُهيَّأة)",
          verify_draft.TRIM_MIN_CORE_FLOOR == 4, verify_draft.TRIM_MIN_CORE_FLOOR)

    # (2) فجوة «وهو»: الضمائر المطلوبة موجودة في _AR_STOP الآن
    for pronoun in ("هو", "هي", "هم", "هن", "وهو", "وهي", "وهم", "وهن"):
        check(f"(2) request._AR_STOP يضمّ «{pronoun}»", pronoun in request._AR_STOP)

    # تكامل فعلي: نافذة سبع كلمات تنتهي بـ«وهو» — ذيل ضمير معطوف لا صلة له
    # بالنسخ (نظير «الذي كان» في الجولة الثانية عشرة). النواة الست كلمات
    # (بلا الذيل) تتكرر داخل نص المصدر نفسه ≥2 فتُعفى بعد تقليم «وهو»
    # الجملة لا تبدأ بـ«إن»/«أن» قبل النواة عمدًا — تتطبَّع كلتاهما إلى «ان»،
    # وهي ليست ضمن _AR_STOP، فوجودها قبل النواة في كل من المسودة والمصدر
    # كان يُنتج نافذة زائفة مطابقة (بإزاحة كلمة واحدة) قبل النافذة المقصودة،
    # فيُختبَر التقليم على نافذة أخرى غير التي يستهدفها هذا الاختبار
    core6 = "احتفال شعبي كبير في المدينة القديمة"
    run7 = f"{core6} وهو"
    draft = f"{run7} تواصل حتى ساعة متأخرة من الليل، بحسب شهود عيان."
    text = f"جرى {run7} أمس الأول. وأضاف مراسلنا لاحقًا: شهد الآلاف {core6} فعليًا."
    single = [{"name": "مصدر تاسع", "text": text}]
    ok, reason, notes = verify_draft.check_originality(draft, "", single, 7)
    check("فجوة «وهو»: نافذة تنتهي بـ«وهو» تُعفى بعد تقليمه من اليمين "
          "(النواة الست كلمات تتكرر داخل المصدر نفسه)",
          ok is True, reason)
    check("فجوة «وهو»: الإعفاء المقلَّم يذكر «وهو» ضمن ما قُلِّم وطول النواة (6 كلمة)",
          bool(notes) and "وهو" in notes[0] and "6 كلمة" in notes[0], notes)


def test_check_originality_quantity() -> None:
    """نواة رقم/كمية (تشخيص Issue #373، تعليق الموافقة الخامس عشر، البند 2):
    نافذة سبع كلمات («... عدة أطنان من مواد نووية مخزنة» — شاهد حقيقي) تحمل
    نواة كمّية جامدة (6 كلمات، تبدأ عند «عدة») لا بديل لصياغتها يمنعها فقط
    كلمة مضمون ملاصقة (فاعل الجملة، يختلف فعليًا بين مصدرين) من إشارتَي
    (أ)/(ب) بطولها الكامل ومن التقليم الحدّي (_trim_exempt لا يجد كلمة
    وظيفية على أي طرف فيفشل بلا محاولة)."""
    from src import verify_draft

    check("_is_quantity_anchor: رقم مكتوب بالأرقام ارتساء صالح",
          verify_draft._is_quantity_anchor("150"))
    check("_is_quantity_anchor: كلمة كمية من الفئة المغلقة ارتساء صالح",
          verify_draft._is_quantity_anchor("أطنان") and verify_draft._is_quantity_anchor("عدة"))
    check("_is_quantity_anchor: كلمة عادية ليست ارتساءً",
          not verify_draft._is_quantity_anchor("مواد") and
          not verify_draft._is_quantity_anchor("مخزنة"))

    core = "عدة أطنان من مواد نووية مخزنة"  # 6 كلمات، ارتساء عند "عدة"/"أطنان"
    window7 = f"الجهة {core}"  # 7 كلمات — "الجهة" كلمة مضمون (فاعل) لا وظيفية

    # إشارة (أ) كمّية: النافذة الكاملة لا تتكرر (مرة واحدة فقط)، ولا تُقلَّم
    # (بلا كلمة وظيفية على أي طرف — _trim_exempt تفشل بلا محاولة)، لكن
    # النواة الكمّية وحدها تتكرر داخل نص المصدر نفسه ≥ repeat_min_count
    draft_a = f"وأفاد التقرير أن {window7} قرب الحدود الشرقية."
    text_a = (f"وبحسب مصدر عسكري، تملك {window7} في منشآت سرية. "
             f"وأضاف المصدر أن {core} خزِّنت هناك منذ سنوات.")
    single_a = [{"name": "مصدر عاشر", "text": text_a}]
    ok_a, reason_a, notes_a = verify_draft.check_originality(draft_a, "", single_a, 7)
    check("نواة كمّية — إشارة (أ): النافذة الكاملة لا تُعفى بطولها ولا بالتقليم "
          "الحدّي، لكن النواة الكمّية تُعفيها بعد تكرارها داخل المصدر نفسه",
          ok_a is True, reason_a)
    check("نواة كمّية — إشارة (أ): الإعفاء مُسجَّل صراحة ويصف نواة كمّية لا تقليمًا نحويًا",
          bool(notes_a) and "نواة كمّية" in notes_a[0] and "6 كلمة" in notes_a[0], notes_a)

    # إشارة (ب) كمّية: بلا تكرار داخل نفس المصدر (مرة واحدة فقط)، لكن النواة
    # الكمّية وحدها وردت في وثيقة أخرى مقروءة بهوية ناشر مختلفة — بناء
    # مختلف تمامًا (فاعل/ترتيب)، المشترك هو صياغة الكمّية نفسها فقط
    draft_b = f"وذكر التقرير أن {window7} في المنطقة."
    text_b = f"تفيد التقارير بأن {window7} في المنطقة."
    single_b = [{"name": "مصدر حادي عشر", "text": text_b}]
    extra_b = [{"name": "مصدر ثانٍ عشر",
               "text": f"وقالت جهة مطّلعة إن هناك {core} رُصدت هناك بالفعل."}]
    ok_b, reason_b, notes_b = verify_draft.check_originality(
        draft_b, "", single_b, 7, extra_docs=extra_b)
    check("نواة كمّية — إشارة (ب): النواة الكمّية وحدها واردة في وثيقة أخرى "
          "بهوية ناشر مختلفة تُعفي النافذة كاملة رغم اختلاف الفاعل والبناء حولها",
          ok_b is True, reason_b)
    check("نواة كمّية — إشارة (ب): الإعفاء مُسجَّل صراحة",
          bool(notes_b) and "نواة كمّية" in notes_b[0], notes_b)

    # ضابط أول: بلا أي تكرار للنواة الكمّية في المصدر نفسه ولا في وثيقة
    # أخرى ← الرفض يبقى قائمًا رغم وجود رقم/كمية داخل النافذة
    single_reject = [{"name": "مصدر ثالث عشر", "text": text_b}]
    ok_none, reason_none, notes_none = verify_draft.check_originality(
        draft_b, "", single_reject, 7)
    check("نواة كمّية — ضابط أول: بلا نواة صالحة (لا تكرار ولا ورود آخر) ← "
          "الرفض يبقى قائمًا رغم وجود كلمة كمية في النافذة",
          ok_none is False, (ok_none, reason_none))

    # ضابط ثانٍ: جملة تعريفية بلا أي رقم/كلمة كمية (نظير الحالة المرفوضة
    # سابقًا — «روبيرتو كارلوس لاعب ريال مدريد السابق» — تعليق الموافقة
    # الرابع عشر أبقاها مرفوضة عمدًا بلا معيار «تعريف/خبر») لا تُفعِّل
    # _quantity_exempt إطلاقًا — لا تسرّب من هذه الإشارة الجديدة
    definitional = "روبيرتو كارلوس لاعب ريال مدريد السابق فعليا"
    check("نواة كمّية — ضابط ثانٍ: جملة تعريفية بلا رقم/كلمة كمية لا يفعّلها "
          "_quantity_exempt إطلاقًا",
          not any(verify_draft._is_quantity_anchor(w)
                 for w in verify_draft._normalized_words(definitional)))
    draft_def = f"{definitional} أحرز هدفًا تاريخيًا في المباراة."
    text_def = f"{definitional} شارك في المؤتمر الصحفي أمس."
    single_def = [{"name": "مصدر رابع عشر", "text": text_def}]
    ok_def, reason_def, notes_def = verify_draft.check_originality(draft_def, "", single_def, 7)
    check("نواة كمّية — ضابط ثانٍ: الجملة التعريفية (بلا رقم) تبقى مرفوضة كما "
          "كانت — لا تسرّب من الإشارة الجديدة",
          ok_def is False and notes_def == [], (ok_def, reason_def, notes_def))


def test_check_originality_name_link() -> None:
    """نواة ربط تسمية (تشخيص Issue #373، تعليق الموافقة السادس عشر):
    الحالة الخامسة المسجَّلة «هوي كا يان معروف بالصينية باسم شو» — نواة لا
    بديل لها («معروف بالصينية باسم شو») تقع في **منتصف** النافذة (بين اسم
    علم يسبقها وآخر يليها)، فلا تلتقطها `_trim_exempt` (تقليم الأطراف فقط
    بكلمات وظيفية) ولا `_quantity_exempt` (ارتساء عند رقم/كمية فقط) —
    `_name_link_exempt` ترتسي عند فئة مغلقة صغيرة من كلمات ربط التسمية
    («معروف»، «يُعرف»، «الملقب»...)، نظير `_quantity_exempt` حرفيًا. تعميم
    أوسع (أي موضع بلا ارتساء) جُرِّب وأُسقِط: كسر ضابط `test_check_originality_trim`
    (ذيل من كلمات مضمون لا يجوز تقليمه) — الارتساء عند فئة مغلقة يحمي هذا
    الضابط تلقائيًا (لا كلمة ربط تسمية في ذلك الفِكستر)."""
    from src import verify_draft

    check("_is_name_link_anchor: كلمة ربط تسمية من الفئة المغلقة ارتساء صالح",
          verify_draft._is_name_link_anchor("معروف") and
          verify_draft._is_name_link_anchor("يُعرف") and
          verify_draft._is_name_link_anchor("الملقب"))
    check("_is_name_link_anchor: كلمة عادية ليست ارتساءً",
          not verify_draft._is_name_link_anchor("رجل") and
          not verify_draft._is_name_link_anchor("شو"))

    # الشاهد الحرفي المُبلَّغ: النافذة الكاملة سبع كلمات، الارتساء
    # («معروف») عند الكلمة الرابعة (index 3) فلا يتّسع لنواة بطول 5 (سقف
    # الطول الممكن من الارتساء حتى نهاية نافذة سبع كلمات هو 4 فقط) — يحتاج
    # التمكين هنا min_core=4 (حد `TRIM_MIN_CORE_FLOOR` الأدنى الصريح)، لا
    # الافتراضي (5). هذا تمييز صادق: الشكل الحرفي المُبلَّغ (الارتساء قرب
    # نهاية النافذة) يحتاج الحد الأدنى تحديدًا، لا كل شكل مشابه
    window7 = "هوي كا يان معروف بالصينية باسم شو"

    # إشارة (أ): النافذة الكاملة لا تتكرر (مرة واحدة)، ولا تُقلَّم (لا كلمة
    # وظيفية على أي طرف: "هوي"/"شو" ليستا في _AR_STOP) ولا ارتساء كمّي (لا
    # رقم/كلمة كمية في النافذة) — لكن النواة المرتسية عند "معروف" (4 كلمات:
    # "معروف بالصينية باسم شو") تتكرر داخل نص المصدر نفسه ≥ repeat_min_count
    draft_a = f"وذكرت المصادر أن {window7} هو رجل الأعمال الصيني."
    text_a = (f"تقرير عن رجل الأعمال {window7} الذي أسس شركة عملاقة قبل عقود. "
             f"ويؤكد مقربون أن الرجل معروف بالصينية باسم شو منذ صباه.")
    single_a = [{"name": "مصدر خامس عشر", "text": text_a}]
    ok_a, reason_a, notes_a = verify_draft.check_originality(
        draft_a, "", single_a, 7, min_core=4)
    check("نواة ربط تسمية — إشارة (أ): لا تقليم ولا ارتساء كمّي ممكنان، لكن "
          "النواة المرتسية عند كلمة ربط التسمية تتكرر داخل نص المصدر نفسه "
          "تُعفي النافذة كاملة (بحد min_core الأدنى الصريح 4)",
          ok_a is True, reason_a)
    check("نواة ربط تسمية — إشارة (أ): الإعفاء مُسجَّل صراحة ويصف نواة ربط "
          "تسمية لا تقليمًا نحويًا ولا ارتساءً كمّيًا",
          bool(notes_a) and "نواة ربط تسمية" in notes_a[0] and "4 كلمة" in notes_a[0],
          notes_a)
    check("نواة ربط تسمية — إشارة (أ) بـmin_core الافتراضي (5): نفس السيناريو "
          "لا يُعفى — الارتساء قرب نهاية نافذة السبع كلمات يحدّ الطول "
          "الممكن عند 4، دون الافتراضي",
          verify_draft.check_originality(draft_a, "", single_a, 7)[0] is False)

    # إشارة (ب): بلا تكرار داخل نفس المصدر (مرة واحدة)، لكن النواة المرتسية
    # وردت في وثيقة أخرى بهوية ناشر مختلفة
    draft_b = f"وأفاد التقرير أن {window7} يمتلك ثروة ضخمة."
    text_b = f"بحسب مصدر مطّلع، {window7} يمتلك ثروة ضخمة."
    single_b = [{"name": "مصدر سادس عشر", "text": text_b}]
    extra_b = [{"name": "مصدر سابع عشر",
               "text": "ورد في تقرير منفصل تمامًا أن الرجل المعروف بالصينية "
                       "باسم شو حقق ثروته عبر قطاع العقارات."}]
    ok_b, reason_b, notes_b = verify_draft.check_originality(
        draft_b, "", single_b, 7, extra_docs=extra_b, min_core=4)
    check("نواة ربط تسمية — إشارة (ب): النواة المرتسية واردة في وثيقة أخرى "
          "بهوية ناشر مختلفة تُعفي النافذة كاملة",
          ok_b is True, reason_b)
    check("نواة ربط تسمية — إشارة (ب): الإعفاء مُسجَّل صراحة",
          bool(notes_b) and "نواة ربط تسمية" in notes_b[0], notes_b)

    # لكن حين يتسع الارتساء لنواة أطول (كلمة الربط قرب بداية النافذة لا
    # نهايتها)، الإعفاء ينجح حتى بـmin_core الافتراضي (5) بلا حاجة للحد
    # الأدنى الصريح — يثبت أن الآلية تعمل عمومًا، لا فقط عند الحد الأدنى
    window7_early = "الرجل يعرف بالصينية باسم شو الكبير جدا"
    anchor_core = "يعرف بالصينية باسم شو الكبير"  # 5 كلمات، ابتداءً من "يعرف"
    # الذيل يختلف عمدًا بين المسودة والمصدر (لا "في الأوساط" مشتركة) — وإلا
    # تكوّنت نافذة سبع كلمات إضافية تتجاوز العبارة المصمَّمة (تتضمّن كلمات
    # الذيل المشترك) ولا يلتقطها أي إعفاء مصمَّم لها هنا
    draft_c = f"وذكر التقرير أن {window7_early} حسب مصادر مقرَّبة منه تمامًا."
    text_c = (f"يقول خبراء إن {window7_early} وفق ما نقلته صحف محلية عديدة. "
             f"ويضيفون أن الرجل {anchor_core} منذ سنوات طويلة جدًا فعلًا.")
    single_c = [{"name": "مصدر ثامن عشر", "text": text_c}]
    ok_c, reason_c, notes_c = verify_draft.check_originality(draft_c, "", single_c, 7)
    check("نواة ربط تسمية — ارتساء مبكر: بـmin_core الافتراضي (5)، نواة "
          "بطول 5 مرتسية عند كلمة ربط قرب بداية النافذة تُعفي النافذة كاملة "
          "بلا حاجة لحد أدنى صريح",
          ok_c is True, reason_c)

    # ضابط أول: بلا أي نواة صالحة في أي موضع ← الرفض يبقى قائمًا
    single_reject = [{"name": "مصدر تاسع عشر", "text": text_b}]
    ok_none, reason_none, notes_none = verify_draft.check_originality(
        draft_b, "", single_reject, 7, min_core=4)
    check("نواة ربط تسمية — ضابط أول: بلا تكرار ولا ورود آخر لأي نواة ممكنة "
          "← الرفض يبقى قائمًا رغم وجود كلمة ربط تسمية في النافذة",
          ok_none is False, (ok_none, reason_none))

    # ضابط ثانٍ (الأهم — نفس فِكستر test_check_originality_trim، ضابط القيد
    # النحوي): ذيل من كلمات مضمون (صفتان) لا يجوز تقليمه — بلا أي كلمة ربط
    # تسمية في النافذة، فـ_name_link_exempt لا تُفعَّل إطلاقًا ولا تكسر هذا
    # الضابط المتعمَّد رغم أن نواتها (بلا الذيل) تتكرر فعليًا داخل المصدر
    run7_content = "فرع الأمن السياسي في درعا الوطني الجديد"
    core = "فرع الأمن السياسي في درعا"
    draft_content = f"{run7_content} يشرف على الملف الأمني."
    text_content = (f"ذكرت وثيقة رسمية أن {run7_content} يتبع وزارة الداخلية. "
                   f"وأضافت أن {core} أنشئ عام 1980.")
    single_content = [{"name": "مصدر عشرون", "text": text_content}]
    check("نواة ربط تسمية — ضابط ثانٍ: لا كلمة ربط تسمية في النافذة، فلا "
          "تُفعَّل _name_link_exempt إطلاقًا",
          not any(verify_draft._is_name_link_anchor(w)
                 for w in verify_draft._normalized_words(run7_content)))
    ok_content, reason_content, notes_content = verify_draft.check_originality(
        draft_content, "", single_content, 7)
    check("نواة ربط تسمية — ضابط ثانٍ: الرفض يبقى قائمًا (فِكستر "
          "test_check_originality_trim الحمائي) رغم تكرار النواة (بلا "
          "الذيل) داخل نفس المصدر — الارتساء عند فئة مغلقة لا يكسر هذا "
          "الضابط المتعمَّد",
          ok_content is False and notes_content == [], (ok_content, reason_content, notes_content))

    # ضابط ثالث: جملة سردية حقيقية غير منسوخة فعليًا (لا صلة لها بمصدر آخر)
    # تبقى مرفوضة حتى لو حملت صدفة كلمة تشبه ربط التسمية — التطابق الحرفي
    # الفعلي (لا وجود الكلمة وحدها) هو ما يُعفي
    nominal = "استقالة الوزير الفلاني إثر فضيحة مالية كبرى هزت"
    draft_nom = f"وجاء في التقرير {nominal} الحكومة بأكملها."
    text_nom = f"أعلن اليوم {nominal} الحكومة بأكملها فجأة."
    single_nom = [{"name": "مصدر حادٍ وعشرون", "text": text_nom}]
    ok_nom, reason_nom, notes_nom = verify_draft.check_originality(
        draft_nom, "", single_nom, 7)
    check("نواة ربط تسمية — ضابط ثالث: جملة سردية فريدة غير متكررة فعليًا "
          "في أي مصدر آخر تبقى مرفوضة",
          ok_nom is False and notes_nom == [], (ok_nom, reason_nom, notes_nom))


def test_check_originality_offending() -> None:
    """`_check_originality_full` (تشخيص Issue #373، تعليق العطل الحادي
    والعشرون، البند 2) تُعيد قيمة رابعة `offending` — التتابع المخالف
    وجملته الكاملة ونوع تطابقه ومصدره — لمحاولة صياغة ثانية في article.py.
    `check_originality` العامة تبقى غلافًا رقيقًا بتوقيعها الأصلي (3-tuple)
    بلا أي تغيير سلوكي — كل استدعاءاتها القائمة (28 موضعًا في هذا الملف
    وحده، ونداء verify_draft.attempt() الداخلي) تبقى تعمل بلا تعديل."""
    from src import article, verify_draft

    run = "محكمة الجنايات الرابعة في دمشق برئاسة القاضي"  # 7 كلمات
    draft = f"أصدرت {run} حكمًا بالإعدام غيابيًا."
    single_source = [{"name": "مصدر أول", "text": f"القصة: {run}. تفاصيل إضافية هنا.",
                      "link": "https://s1/1"}]

    ok3, reason3, notes3 = verify_draft.check_originality(draft, "", single_source, 7)
    check("check_originality العامة تبقى 3-tuple — لا تغيير في التوقيع العام",
          (ok3, reason3, notes3) is not None and ok3 is False)

    ok4, reason4, notes4, offending = verify_draft._check_originality_full(
        draft, "", single_source, 7)
    check("_check_originality_full تعيد نفس (ok, reason, notes) للغلاف العام",
          (ok4, reason4, notes4) == (ok3, reason3, notes3), (ok4, ok3))
    check("رفض تطابق مع مصدر واحد: offending تحمل match_kind='source' واسم "
          "المصدر ورابطه والتتابع (مُطبَّعًا كما يُبنى منه)",
          offending is not None and offending["match_kind"] == "source" and
          offending["source_name"] == "مصدر أول" and
          offending["source_link"] == "https://s1/1" and
          offending["phrase"] == " ".join(verify_draft._normalized_words(run)),
          offending)
    check("رفض تطابق مع مصدر واحد: offending تحمل جملة المسودة الكاملة",
          draft.rstrip(".") in offending["draft_sentence"] or
          offending["draft_sentence"] in draft, offending)

    brief = f"نُشر أن {run} أصدرت الحكم."
    ok_brief, _, _, offending_brief = verify_draft._check_originality_full(
        draft, brief, [], 7)
    check("رفض تطابق مع الموجز الملصق: offending تحمل match_kind='brief' بلا "
          "اسم/رابط مصدر", ok_brief is False and offending_brief is not None and
          offending_brief["match_kind"] == "brief" and
          "source_name" not in offending_brief, offending_brief)

    ok_quote, reason_quote, _, offending_quote = verify_draft._check_originality_full(
        f'قال المسؤول: "{run} جملة غير موجودة في أي مصدر إطلاقًا".', "", [], 7)
    check("رفض اقتباس مختلَق (لا تتابع نافذة): offending تبقى None — عطل "
          "مضمون لا صياغة يمكن إصلاحها بإعادة الترتيب",
          ok_quote is False and offending_quote is None, (reason_quote, offending_quote))

    two_sources = [{"name": "مصدر أول", "text": f"{run} أصدرت الحكم."},
                  {"name": "مصدر ثانٍ", "text": f"وأكدت {run} ذلك."}]
    ok_pass, _, _, offending_pass = verify_draft._check_originality_full(
        draft, "", two_sources, 7)
    check("نجاح الفحص (مصدران مستقلان): offending تبقى None",
          ok_pass is True and offending_pass is None, offending_pass)

    avoid_note = article._build_avoid_note(offending)
    check("_build_avoid_note: يذكر اسم المصدر والجملة المخالفة صراحة",
          "مصدر أول" in avoid_note and draft.rstrip(".") in avoid_note.replace("«", "").replace("»", ""),
          avoid_note)
    avoid_note_brief = article._build_avoid_note(offending_brief)
    check("_build_avoid_note: حالة الموجز الملصق تذكر «الموجز الملصق» لا اسم مصدر",
          "الموجز الملصق" in avoid_note_brief, avoid_note_brief)


def test_evidence() -> None:
    """اختبارات مستقلة لـsrc/evidence.py — الشبكة التي تثبت سلامة نقل
    البحث والقراءة ومطابقة أسماء المصادر من verify.py (Issue #348، تعليق
    الموافقة على التشخيص، البند 1: verify.py يستورد من evidence.py الآن
    بلا تعريف مزدوج — اختبارات verify.py القديمة تبقى خطًا أخضر إضافيًا
    لأنها تختبر نفس كائنات الدوال المُعاد تصديرها، وهذه اختبارات مباشرة
    عبر اسم evidence. نفسه)."""
    cfg = load_config()

    long_claim = ("انخفضت واردات الولايات المتحدة من النفط الخام السعودي "
                  "إلى الصفر طوال شهر يوليو 2026 بأكمله، وفقا لتقرير بلومبرغ")
    # legacy_sort=True: هذه الحزمة تختبر السلوك القديم (أرقام أولًا ثم أطول
    # الكلمات)، محجوز حصرًا لـ verify.py:779 الآن (تعليق الموافقة الثالث
    # على Issue #361، البند 1). الافتراضي الجديد يُختبَر أدناه مباشرة.
    query = evidence.build_query(long_claim, legacy_sort=True)
    check("evidence.build_query: لا يتجاوز 5 كلمات مفتاحية",
          1 <= len(query.split()) <= 5)
    check("evidence.build_query: الرقم المميز يدخل الاستعلام (legacy_sort)",
          "2026" in query.split())
    check("evidence.build_query: اسم العلم يدخل الاستعلام لا كلمات الحشو الأطول (legacy_sort)",
          "بلومبرغ" in query.split() and
          not any(w in query for w in ("لتقرير", "وفقا", "بأكمله")))
    check("evidence.build_query: نص فارغ لا ينهار", evidence.build_query("") == "")

    # الافتراضي الجديد (البند 1، تعليق الموافقة الثالث): يحفظ ترتيب الورود
    # الأصلي بلا فصل الأرقام إلى المقدمة — عكس legacy_sort أعلاه تمامًا
    ordered_source = "زيد 11 عمرو آب 2026"
    default_ordered = evidence.build_query(ordered_source, 5)
    legacy_ordered = evidence.build_query(ordered_source, 5, legacy_sort=True)
    check("evidence.build_query: الافتراضي يحفظ ترتيب الورود الأصلي حرفيًا "
          "حين تتسع الكلمات كلها ضمن السقف",
          default_ordered == ordered_source, default_ordered)
    check("evidence.build_query: legacy_sort يفصل الأرقام إلى المقدمة فعلًا "
          "— يثبت أن الافتراضي تغيّر لا أنه صدفة بلا فرق",
          legacy_ordered.split()[:2] == ["11", "2026"] and
          legacy_ordered != ordered_source, legacy_ordered)

    # تشخيص التشغيل الحقيقي على Issue #364: شرط الطول (len > 2) في
    # request.norm_tokens كان يُسقط بنيويًا كل تاريخ يوم من رقمين وكل شهر
    # عربي من حرفين ("آب") من كل استعلام — قبل أي منطق فرز أو ترتيب. مثال
    # اصطناعي هنا (لا الحدث الفعلي) لإثبات شكل الاستعلام لا نتيجته
    check("evidence._normalize_query_word: رقم من رقمين (يوم) ينجو بلا شرط طول",
          evidence._normalize_query_word("11") == "11")
    check("evidence._normalize_query_word: اسم شهر عربي من حرفين ينجو بلا شرط طول",
          evidence._normalize_query_word("آب") == "اب")
    check("evidence._normalize_query_word: كلمة وقف عربية تبقى مستبعدة رغم إسقاط شرط الطول",
          evidence._normalize_query_word("من") is None)
    check("evidence._normalize_query_word: نص فارغ لا ينهار", evidence._normalize_query_word("") is None)

    direct_stage_query = evidence.build_query("كيان اختباري 11 آب 2026", 5)
    check("evidence.build_query: استعلام مرحلة مباشرة يحمل اسم الكيان كاملًا "
          "(مثال اصطناعي — تشخيص Issue #364، البند 1)",
          {"كيان", "اختباري"} <= set(direct_stage_query.split()))
    check("evidence.build_query: نفس الاستعلام يحمل مكوّنات التاريخ كاملة "
          "(يوم من رقمين + شهر من حرفين + سنة) لا سنة وحدها",
          {"11", "آب", "2026"} <= set(direct_stage_query.split()))

    check("evidence.build_query: «عامًا» (كلمة عمر/زمن عامة) لا تدخل الاستعلام "
          "كأنها كيان مميِّز — تشخيص Issue #364",
          "عاما" not in evidence.build_query("كان عمره 13 عامًا حين خرج", 5).split() and
          "13" in evidence.build_query("كان عمره 13 عامًا حين خرج", 5).split())

    # وحدات القياس ليست كيانات مستقلة (طلب المراجعة، تشخيص Issue #373،
    # تعليق العطل الثاني والعشرون، البند 2): شاهد فعلي — استعلام تصريح
    # بايراكتار فقد اسم المتحدث لأن "yüzde" (لاحقة قياس تركية) استهلكت
    # خانة من سقف max_words بدل اسم علم
    turkish_query = evidence.build_query("Baykar yüzde 90 Türkiye", 5)
    check("evidence.build_query: «yüzde» التركية (لاحقة قياس) لا تدخل الاستعلام",
          "yüzde" not in turkish_query.split(), turkish_query)
    check("evidence.build_query: الرقم والكيانات المحيطة بـ«yüzde» تدخل رغم استبعادها",
          {"Baykar", "90", "Türkiye"} <= set(turkish_query.split()), turkish_query)
    arabic_percent_query = evidence.build_query("ارتفعت النسبة 90 بالمئة هذا العام", 5)
    check("evidence.build_query: «بالمئة» العربية (لاحقة قياس) لا تدخل الاستعلام",
          "بالمئة" not in arabic_percent_query.split(), arabic_percent_query)
    english_percent_query = evidence.build_query("Baykar localized 90 percent of production", 5)
    check("evidence.build_query: «percent» الإنجليزية (لاحقة قياس) لا تدخل الاستعلام",
          "percent" not in english_percent_query.split(), english_percent_query)

    claim_with_entities = {"text": "أي صياغة أخرى", "entities": ["بلومبرغ", "2026", "السعودي"]}
    check("evidence.build_query_for_claim: يستعمل entities حصرًا حين تتوفر",
          evidence.build_query_for_claim(claim_with_entities) ==
          evidence.build_query(" ".join(claim_with_entities["entities"])))
    check("evidence.build_query_for_claim: entities غائبة تسقط لنص الادّعاء كاملًا",
          evidence.build_query_for_claim({"text": long_claim}) ==
          evidence.build_query(long_claim))

    check("evidence._publisher_weight: مصدر في verify.trusted_boost يأخذ الوزن الأقصى",
          evidence._publisher_weight("Bloomberg", cfg) == evidence.TRUSTED_PUBLISHER_WEIGHT)
    check("evidence._publisher_weight: ناشر غير مُدرَج يأخذ الوزن الافتراضي",
          evidence._publisher_weight("موقع عشوائي غير معروف كليًا هنا", cfg) ==
          evidence.DEFAULT_PUBLISHER_WEIGHT)

    docs = [{"name": "BBC News", "text": "نص", "link": "https://bbc.com/1"}]
    check("evidence._tokens_match: يتسامح مع وصف بين قوسين",
          evidence._tokens_match("BBC News (تقرير مطوّل)", "BBC News"))
    check("evidence._canonical_name: يطابق بتسامح ويعيد الاسم الفعلي من docs",
          evidence._canonical_name("BBC News (تقرير مطوّل)", docs) == "BBC News")
    check("evidence._canonical_name: لا يطابق مصدرًا غير معطى إطلاقًا",
          evidence._canonical_name("مصدر لا علاقة له بالمرة إطلاقًا", docs) is None)
    check("evidence._known_only: يستبعد الأسماء المختلَقة ويُبقي المعروفة فقط",
          evidence._known_only(["BBC News (تقرير)", "مصدر مختلق"], docs) == ["BBC News"])
    check("evidence._known_only: مدخل ليس قائمة لا ينهار", evidence._known_only("BBC", docs) == [])

    check("evidence.gather_evidence: لا نتائج بحث أصلًا",
          evidence.gather_evidence([], cfg) == ([], evidence.EVIDENCE_NO_RESULTS))

    real_extract_gather = extract.gather
    fallback_articles = [
        Article(title="Oil imports halted for first time since 1985",
               link="https://a.example.com/1", summary="US ends Saudi oil imports",
               source_name="Reuters", region="global", weight=1.0,
               published=datetime.now(timezone.utc), publisher="Reuters"),
    ]
    extract.gather = lambda members, limit=2: (
        [], [{"name": "Reuters", "link": "https://a.example.com/1", "reason": "HTTP 403"}])
    docs_h, basis_h = evidence.gather_evidence(fallback_articles, cfg)
    check("evidence.gather_evidence: احتياط العناوين حين يتعذّر النص الكامل",
          basis_h == evidence.EVIDENCE_HEADLINES_ONLY)
    check("evidence.gather_evidence: وثيقة الاحتياط معلَّمة from_text=False",
          bool(docs_h) and docs_h[0]["from_text"] is False)
    check("evidence.gather_evidence: سبب فشل جلب النص الكامل مُرفَق كسمة على docs "
          "(البند 1، تعليق العطل الثاني) — لا صمت حين يُسقَط لاحتياط العناوين",
          getattr(docs_h, "fetch_failures", None) ==
          [{"name": "Reuters", "link": "https://a.example.com/1", "reason": "HTTP 403"}])

    extract.gather = lambda members, limit=2: (
        [{"name": "Reuters", "text": "نص كامل مستخرج فعليًا"}], [])
    docs_f, basis_f = evidence.gather_evidence(fallback_articles, cfg)
    check("evidence.gather_evidence: النص الكامل يُفضَّل حين يتوفر لا الاحتياط",
          basis_f == evidence.EVIDENCE_FULL_TEXT and docs_f[0]["from_text"] is True)
    check("evidence.gather_evidence: لا فشليات حين ينجح الجلب الكامل",
          getattr(docs_f, "fetch_failures", None) == [])
    extract.gather = real_extract_gather

    seen_merge_cfg: list = []
    seen_keep_google: list = []
    real_rank = evidence.rank

    def _spy_rank(articles, selection, merge_cfg=None, token_fn=None,
                 keep_google_links=False):
        seen_merge_cfg.append(merge_cfg)
        seen_keep_google.append(keep_google_links)
        return real_rank(articles, selection, merge_cfg=merge_cfg, token_fn=token_fn,
                         keep_google_links=keep_google_links)

    one = Article(title="زلزال قوي يضرب هرات", link="https://x/1", summary="",
                 source_name="s", region="global", weight=1.0,
                 published=datetime.now(timezone.utc), publisher="s")
    real_fetch_source = evidence.fetch_source
    evidence.rank = _spy_rank
    evidence.fetch_source = lambda src, max_age_hours: [one]
    try:
        search_result = evidence.search("زلزال هرات", cfg, 7)
    finally:
        evidence.fetch_source = real_fetch_source
        evidence.rank = real_rank
    # البند 1 (تعليق العطل الثاني على Issue #361): trail يحتاج عدد النتائج
    # الخام قبل التصفية بالصلة (relevant) وعدد المطابق بعدها — بلا هذين
    # الرقمين لا سبيل لتشخيص لماذا سقط استعلام لمصدر واحد رغم تغطية واسعة
    check("evidence.search: raw_count يساوي عدد النتائج الخام قبل التصفية",
          search_result.raw_count > 0 and
          search_result.raw_count == search_result.matched_count,
          f"raw={search_result.raw_count} matched={search_result.matched_count}")
    check("evidence.search: النتيجة تبقى قائمة عادية بالكامل (توافق خلفي مع verify.py)",
          list(search_result) == search_result and isinstance(search_result, list))
    check("evidence.search: raw_count صفر حين لا نتائج بحث خام أصلًا",
          evidence._search_result([], 0, 0).raw_count == 0)
    check("evidence.search: raw_count يساوي عدد النتائج الخام حتى حين لا مطابقة",
          evidence._search_result([], 3, 0).raw_count == 3 and
          evidence._search_result([], 3, 0).matched_count == 0)
    check("evidence.search: الدمج الدلالي معطَّل صراحة (merge_cfg=None) — تعدد "
          "المصادر المستقلة هو المقياس هنا لا تمثيل الحدث بخبر واحد",
          seen_merge_cfg == [None], str(seen_merge_cfg))
    check("evidence.search: keep_google_links=True دومًا — نتائجه كلها من "
          "Google News فتُحلّ لاحقًا في gather_evidence لا تُستبعد خامًا",
          seen_keep_google == [True], str(seen_keep_google))

    # البند 4 (تعليق الموافقة الثالث على Issue #361): عيّنة عناوين رفضها
    # فلتر الصلة — تشخيص فرضية أن الحدث الصحيح قد لا يذكر كيان الموجز في
    # عنوانه فيُرفض قبل قراءته
    irrelevant = Article(title="مباراة كرة قدم في دوري محلي", link="https://y/1",
                         summary="", source_name="s2", region="global", weight=1.0,
                         published=datetime.now(timezone.utc), publisher="s2")
    evidence.fetch_source = lambda src, max_age_hours: [one, irrelevant]
    try:
        search_result2 = evidence.search("زلزال هرات", cfg, 7)
    finally:
        evidence.fetch_source = real_fetch_source
    check("evidence.search: rejected_titles يحمل عنوان النتيجة المرفوضة بالصلة",
          irrelevant.title in search_result2.rejected_titles and
          all(t == irrelevant.title for t in search_result2.rejected_titles),
          search_result2.rejected_titles)
    check("evidence.search: rejected_titles فارغة حين تُقبَل كل النتائج",
          search_result.rejected_titles == [], search_result.rejected_titles)

    # ── طلب التنفيذ على Issue #373، البند 1: require_relevance=False يُسقط
    # فلتر relevant() كليًا — النتيجة غير المطابقة تدخل matched بدل الرفض ──
    evidence.fetch_source = lambda src, max_age_hours: [one, irrelevant]
    try:
        search_result3 = evidence.search("زلزال هرات", cfg, 7, require_relevance=False)
    finally:
        evidence.fetch_source = real_fetch_source
    check("evidence.search: require_relevance=False يُبقي كل النتائج الخام "
          "بلا تصفية بالصلة — raw==matched حتى مع نتيجة غير مطابقة إطلاقًا "
          "(العدد مضاعَف عن [one, irrelevant]: fetch_source مزيَّفة تُستدعى "
          "مرة لكل لغة محليّة في verify.locales)",
          search_result3.raw_count == search_result3.matched_count > 0,
          (search_result3.raw_count, search_result3.matched_count))
    check("evidence.search: require_relevance=False لا يملأ rejected_titles "
          "— لا شيء رُفض أصلًا",
          search_result3.rejected_titles == [], search_result3.rejected_titles)

    # ── طلب التنفيذ على Issue #373، البند 1: _loose_tokens لا تُسقط تاريخًا
    # قصيرًا (خلافًا لـrequest.norm_tokens) — نفس عطل Issue #364 كان سيُورَث
    # في الفرز لو صار الفرز البوابة الوحيدة على الصلة بعد تعطيل relevant() ──
    check("evidence._loose_tokens: تاريخ يوم من رقمين لا يُسقط",
          "11" in evidence._loose_tokens("حدث وقع في 11 آب 2026"))
    check("evidence._loose_tokens: شهر عربي من حرفين لا يُسقط",
          "اب" in evidence._loose_tokens("حدث وقع في 11 آب 2026"))
    check("evidence._loose_tokens: كلمة وقف عربية تبقى مستبعدة",
          "في" not in evidence._loose_tokens("حدث وقع في 11 آب 2026"))
    date_only_article = Article(
        title="خبر عن كيان آخر تمامًا في 11 آب 2026", link="https://z/1", summary="",
        source_name="s3", region="global", weight=1.0,
        published=datetime.now(timezone.utc), publisher="s3")
    check("evidence._relevance: norm_tokens (الافتراضي) يُفرغ الاستعلام كليًا "
          "حين يقتصر على يوم وشهر قصيرين — لا صلة تُحتسب إطلاقًا (عطل Issue #364)",
          evidence._relevance(date_only_article, evidence.norm_tokens("11 آب")) == 0)
    check("evidence._relevance: token_fn=_loose_tokens تحتفظ باليوم/الشهر "
          "القصيرين فتحتسب الصلة التي أفرغها norm_tokens أعلاه",
          evidence._relevance(date_only_article, evidence._loose_tokens("11 آب"),
                              evidence._loose_tokens) > 0)

    # ── طلب التنفيذ على Issue #373، البند 3+4: استبعاد/خفض ترتيب ناشرين
    # كمرشّحي قراءة تحقّق — قبل أي وزن أو بعده بحسب الحالة ──
    check("evidence._is_excluded_publisher: ناشر في verify.excluded_publishers يُستبعد",
          evidence._is_excluded_publisher("365Scores", cfg))
    check("evidence._is_excluded_publisher: ناشر غير مُدرَج لا يُستبعد",
          not evidence._is_excluded_publisher("BBC News", cfg))
    check("evidence._is_demoted_reader: ناشر في verify.demoted_readers يُخفَّض",
          evidence._is_demoted_reader("France 24", cfg))
    check("evidence._is_demoted_reader: ناشر غير مُدرَج لا يُخفَّض",
          not evidence._is_demoted_reader("BBC News", cfg))
    # Reuters: إضافة لاحقة (تعليق الموافقة السادس على Issue #373) — HTTP 401
    # موثَّق كنمط دائم (جدار اشتراك، لا رأس HTTP يحلّه)، لا 403 كسابقيه، لكن
    # نفس المعالجة: يبقى موثوقًا بوزنه الكامل، يخسر فقط أولوية القراءة.
    # يُختبر بالاسمين (إنجليزي وعربي) كالوكالات الأخرى في trusted_boost —
    # demoted_readers لا يطابق عبر publisher_aliases تلقائيًا كما trusted_boost.
    check("evidence._is_demoted_reader: Reuters (إنجليزي) يُخفَّض بعد إضافته "
          "— HTTP 401 نمط دائم موثَّق (Issue #373)",
          evidence._is_demoted_reader("Reuters", cfg))
    check("evidence._is_demoted_reader: رويترز (عربي) يُخفَّض أيضًا",
          evidence._is_demoted_reader("رويترز", cfg))
    check("evidence._read_priority: ناشر محجوب يُدفَع تحت أي وزن/صلة ممكنين "
          "— لا يُستبعد كليًا، فقط يخسر أولوية الترتيب",
          evidence._read_priority("France 24", cfg) <
          evidence.DEFAULT_PUBLISHER_WEIGHT - evidence.TRUSTED_PUBLISHER_WEIGHT)
    check("evidence._read_priority: ناشر غير محجوب يحتفظ بوزنه كما هو "
          "(_publisher_weight بلا تعديل)",
          evidence._read_priority("BBC News", cfg) ==
          evidence._publisher_weight("BBC News", cfg))
    check("evidence._publisher_weight: ناشر محجوب (demoted_readers) يبقى بوزنه "
          "الحقيقي — الاستشهاد/الترتيب العام لا يتأثران بالحجب",
          evidence._publisher_weight("Al Arabiya", cfg) == evidence.TRUSTED_PUBLISHER_WEIGHT)
    check("evidence._publisher_weight: Reuters المخفَّض يبقى بوزنه الموثوق الكامل "
          "أيضًا — نفس ضمان العربية أعلاه",
          evidence._publisher_weight("Reuters", cfg) == evidence.TRUSTED_PUBLISHER_WEIGHT)

    excluded_article = Article(
        title="365Scores: نتيجة مباراة اليوم", link="https://sport.example/1", summary="",
        source_name="365Scores", region="global", weight=1.0,
        published=datetime.now(timezone.utc), publisher="365Scores")
    real_extract_gather2 = extract.gather
    seen_gather_members: list = []

    def _spy_gather(members, limit=2):
        seen_gather_members.append([m["name"] for m in members])
        return [], []

    extract.gather = _spy_gather
    try:
        docs_ex, basis_ex = evidence.gather_evidence([excluded_article], cfg, "نتيجة مباراة")
    finally:
        extract.gather = real_extract_gather2
    check("evidence.gather_evidence: ناشر مُستبعَد لا يدخل مرشّحي القراءة "
          "الكاملة إطلاقًا — قبل أي وزن (تشخيص Issue #373، البند 4)",
          seen_gather_members == [[]], seen_gather_members)
    check("evidence.gather_evidence: ناشر مُستبعَد لا يظهر في احتياط العناوين "
          "أيضًا — استبعاد كامل من الدليل لا من القراءة الكاملة وحدها",
          basis_ex == evidence.EVIDENCE_UNREADABLE and docs_ex == [], (basis_ex, docs_ex))

    # ── طلب التنفيذ على Issue #373، الجولة الرابعة، البند 1: توحيد هوية
    # الناشر عبر اللغتين قبل اختيار مرشحي القراءة لا بعده — الشاهد الحقيقي:
    # «الجزيرة نت» و«Al Jazeera» عُومِلا ناشرَين مستقلَّين فاستهلكا فتحتي
    # قراءة من الثلاث بدل واحدة ──
    check("evidence._trusted_canonical: نسخة عربية من ناشر trusted_boost تُطابَق "
          "هويته الإنجليزية المرجعية عبر publisher_aliases",
          evidence._trusted_canonical("الجزيرة نت", cfg) == "Al Jazeera")
    check("evidence._trusted_canonical: النسخة الإنجليزية نفسها تُطابَق مباشرة",
          evidence._trusted_canonical("Al Jazeera", cfg) == "Al Jazeera")
    check("evidence._trusted_canonical: ناشر غير مُدرَج في trusted_boost لا يُطابَق",
          evidence._trusted_canonical("موقع عشوائي غير معروف كليًا هنا", cfg) is None)
    check("evidence._canonical_publisher: نسخة عربية وإنجليزية لناشر واحد تشتركان "
          "بالهوية نفسها",
          evidence._canonical_publisher("الجزيرة نت", cfg) ==
          evidence._canonical_publisher("Al Jazeera", cfg) == "Al Jazeera")
    check("evidence._canonical_publisher: ناشر غير مُدرَج يبقى هوية نفسه (الاسم الخام "
          "كما ورد — لا قائمة مرادفات لكل مصدر RSS)",
          evidence._canonical_publisher("موقع عشوائي غير معروف كليًا هنا", cfg) ==
          "موقع عشوائي غير معروف كليًا هنا")

    aj_ar = Article(title="حمزة الخطيب: حكم غيابي بإعدام الأسد", link="https://aj-ar.example/1",
                    summary="", source_name="الجزيرة نت", region="global", weight=1.0,
                    published=datetime.now(timezone.utc), publisher="الجزيرة نت")
    aj_en = Article(title="Assad sentenced in absentia over Hamza al-Khatib case",
                    link="https://aj-en.example/1", summary="", source_name="Al Jazeera",
                    region="global", weight=1.0, published=datetime.now(timezone.utc),
                    publisher="Al Jazeera")
    bbc_real = Article(title="Court sentences Assad in absentia", link="https://bbc.example/1",
                       summary="", source_name="BBC News", region="global", weight=1.0,
                       published=datetime.now(timezone.utc), publisher="BBC News")
    real_extract_gather3 = extract.gather
    seen_gather_members2: list = []

    def _spy_gather2(members, limit=2):
        seen_gather_members2.append([m["name"] for m in members])
        return [], []

    extract.gather = _spy_gather2
    try:
        evidence.gather_evidence([aj_ar, aj_en, bbc_real], cfg, "حمزة الخطيب")
    finally:
        extract.gather = real_extract_gather3
    read_names = seen_gather_members2[0]
    check("evidence.gather_evidence: نسختا الجزيرة (عربية/إنجليزية) تستهلكان فتحة "
          "قراءة واحدة لا فتحتين — مرشح ثالث حقيقي (BBC News) لا يخسر فتحته "
          "(الشاهد الحقيقي في Issue #373: قراءة 'الجزيرة نت، BBC، Al Jazeera' "
          "بدل 'الجزيرة نت، BBC، سكاي نيوز عربية')",
          len(read_names) == 2 and "BBC News" in read_names and
          len({evidence._canonical_publisher(n, cfg) for n in read_names}) == 2,
          read_names)

    aj_ar2 = Article(title="حمزة الخطيب: خبر تجريبي", link="https://aj-ar2.example/1",
                     summary="ملخص عربي", source_name="الجزيرة نت", region="global", weight=1.0,
                     published=datetime.now(timezone.utc), publisher="الجزيرة نت")
    aj_en2 = Article(title="Hamza test story", link="https://aj-en2.example/1",
                     summary="English summary", source_name="Al Jazeera", region="global",
                     weight=1.0, published=datetime.now(timezone.utc), publisher="Al Jazeera")
    extract.gather = lambda members, limit=2: ([], [])
    try:
        docs_hd, basis_hd = evidence.gather_evidence([aj_ar2, aj_en2], cfg)
    finally:
        extract.gather = real_extract_gather3
    check("evidence.gather_evidence: احتياط العناوين يوحّد الناشر أيضًا — لا يعرض "
          "نسختي الجزيرة كمصدرين مستقلين في الاحتياط",
          basis_hd == evidence.EVIDENCE_HEADLINES_ONLY and len(docs_hd) == 1, docs_hd)


def test_article() -> None:
    """مسار «مقال من المصادر» (Issue #348): اختبار لكل قاعدة من القواعد
    السبع الملزمة، واختبار سدّ ثغرة الدائرة (تعليق التنفيذ: واقعة بمصدر
    واحد لا يمكن أن تصبح محورية لأن الترشيح بالسند يسبق اختيار السؤال)،
    وتغطية تعليق الموافقة الثاني على Issue #361 كاملًا: ترتيب سلّم التسمية
    المقلوب (البند 1)، بوابة الاتساق (البند 2)، استخلاص السياق بنداء نموذج
    بدل ترجيح التكرار (البند 3)، سجلّ trail الكامل (البند 4)، بحث فعلي عن
    أسئلة الموجز (البند 5)، عدّ الكفاية مع تمييز الوقائع المرجعية (البند
    6)، وسؤال الصلة بعد تسمية حدث جديد (البند 7)."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_ask_naming_model = article._ask_naming_model
    real_ask_context_model = article._ask_context_model
    real_ask_answer_model = article._ask_answer_model
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_call_draft_model = article._call_draft_model
    real_find_images = article.find_images

    SUPPORT_MAP: dict = {}
    ANSWER_MAP: dict = {}
    seen_question_calls: list = []
    seen_draft_calls: list = []
    seen_search_queries: list = []

    def _fake_search(query, cfg, days, unrestricted=False):
        seen_search_queries.append(query)
        return [object()]  # غير فارغة لتفعيل القراءة فقط — المحتوى لا يهم هنا

    def _fake_gather_evidence(articles, cfg, claim_text=""):
        return ([{"name": "مصدر أول", "text": "نص", "link": "https://s1/1", "from_text": True},
                 {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1", "from_text": True},
                 {"name": "مصدر ثالث", "text": "نص", "link": "https://s3/1", "from_text": True}],
                evidence.EVIDENCE_FULL_TEXT)

    def _fake_support(fact_text, docs, cfg, is_statement=False, is_report=False, publisher=""):
        return SUPPORT_MAP.get(fact_text, [])

    def _fake_answer(question_text, docs, cfg):
        return ANSWER_MAP.get(question_text)

    def _fake_choose_question(grounded, cfg, retries=2):
        seen_question_calls.append([f["text"] for f in grounded])
        return "سؤال اختبار؟", ""

    def _fake_draft_article(grounded, opinions, question, cfg, retries=3, avoid_note=""):
        seen_draft_calls.append({"grounded": [f["text"] for f in grounded],
                                 "opinions": [o["text"] for o in opinions],
                                 "question": question})
        return ({"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
                "image_headline": "عنوان الصورة", "post_title": question,
                "post_body": "متن الاختبار يجيب عن السؤال بوضوح تام كاملة.",
                "hashtags": ["اختبار"]}, "")

    evidence.search = _fake_search
    evidence.gather_evidence = _fake_gather_evidence
    article._support_sources = _fake_support
    article._ask_answer_model = _fake_answer
    article._choose_question = _fake_choose_question
    article._draft_article = _fake_draft_article
    article.find_images = lambda title, cfg, terms=None: []

    # ── القاعدة 1: كل واقعة مسندة — بلا سند كافٍ (مصدران مستقلان فأكثر) تسقط ──
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار القاعدة 1",
        "statements": [
            {"text": "واقعة بمصدر واحد فقط", "kind": "واقعة", "entities": ["ك1"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": "واقعة بمصدرين مستقلين", "kind": "واقعة", "entities": ["ك2"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": "واقعة بثلاثة مصادر", "kind": "واقعة", "entities": ["ك3"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    SUPPORT_MAP.clear()
    SUPPORT_MAP["واقعة بمصدر واحد فقط"] = ["مصدر أول"]
    SUPPORT_MAP["واقعة بمصدرين مستقلين"] = ["مصدر أول", "مصدر ثانٍ"]
    SUPPORT_MAP["واقعة بثلاثة مصادر"] = ["مصدر أول", "مصدر ثانٍ", "مصدر ثالث"]

    out1 = article._write_article("موجز اختبار القاعدة 1", 1, cfg)
    check("1) واقعة بمصدر واحد فقط تسقط ولا تدخل المقال — حتى لو وردت في الموجز",
          any(d["text"] == "واقعة بمصدر واحد فقط" for d in out1["dropped"]))
    check("1) سبب السقوط يذكر السند غير الكافي صراحة (لا فشل صامت)",
          any("سند غير كافٍ" in d["reason"] for d in out1["dropped"]
              if d["text"] == "واقعة بمصدر واحد فقط"))
    check("1) واقعتان مسندتان بمصدرين فأكثر تكفيان لإنتاج المقال",
          out1["produced"] is True, out1["reason"])
    check("1) الواقعة الساقطة غير موجودة ضمن ما مرّ لاختيار السؤال",
          "واقعة بمصدر واحد فقط" not in seen_question_calls[-1])
    # خط الأساس الثابت (تشخيص Issue #373، الجولة الرابعة، البند 3) يحتاج
    # عدد الوقائع المسندة كعدد صريح على outcome — لا استخراجه من نص حر
    check("1) outcome['grounded_count'] يساوي عدد الوقائع التي اجتازت السند فعلًا "
          "(2 من 3: واحدة سقطت لسند غير كافٍ)",
          out1["grounded_count"] == 2, out1["grounded_count"])

    # ── القاعدة 7: بوابة كفاية عددية على الوقائع المُرشَّحة بالسند فقط ──
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار القاعدة 7",
        "statements": [
            {"text": "واقعة يتيمة مسندة", "kind": "واقعة", "entities": ["ك"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": ["سؤال لم يُجب عنه الموجز؟"],
    }, None)
    SUPPORT_MAP.clear()
    SUPPORT_MAP["واقعة يتيمة مسندة"] = ["مصدر أول", "مصدر ثانٍ"]
    ANSWER_MAP.clear()  # السؤال بلا إجابة في ANSWER_MAP عمدًا — بُحث ولم يُجب
    question_calls_before = len(seen_question_calls)
    out7 = article._write_article("موجز اختبار القاعدة 7", 7, cfg)
    check("7) واقعة مسندة واحدة فقط دون الحد الأدنى (min_grounded_facts) ← لا مقال",
          out7["produced"] is False)
    check("7) سبب الامتناع يذكر القاعدة 7 صراحة لا رسالة عامة",
          "القاعدة 7" in out7["reason"])
    check("7) grounded_count يبقى مسجَّلًا (1) رغم امتناع الإنتاج — يُحسَب قبل "
          "بوابة الكفاية لا يُشتق من نجاحها",
          out7["grounded_count"] == 1, out7["grounded_count"])
    check("7) امتناع بلاغ بما بُحث لا مقال ركيك — لا نداء لاختيار السؤال أصلًا "
          "(البوابة العددية تسبق اختياره)",
          len(seen_question_calls) == question_calls_before)
    check("5) سؤال الموجز بُحث عنه فعلًا (لا حصيلة فشل بلا محاولة) ولم يُجب عنه "
          "بسبب محدد يبقى في القسم",
          any(u["text"] == "سؤال لم يُجب عنه الموجز؟" and u["reason"]
              for u in out7["unanswered"]))
    check("4) trail يُمرَّر إلى outcome ويشمل استعلام حلقة الوقائع العادية "
          "واستعلام حلقة الأسئلة معًا، كل عنصر منه بمصادره وحصيلته وعدّاد "
          "النتائج الخام/المطابقة وفشليات الجلب (تعليق العطل الثاني، البند 1)",
          any(t["stage"] == "واقعة" for t in out7["trail"]) and
          any(t["stage"] == "سؤال" for t in out7["trail"]) and
          all({"stage", "query", "basis", "sources", "outcome", "raw_count",
              "matched_count", "fetch_failures"} <= set(t.keys())
              for t in out7["trail"]))
    report7 = article.build_report(out7)
    check("4) التقرير يعرض سجلّ trail الكامل", "سجلّ البحث الكامل" in report7)
    # تشخيص Issue #373 (الجولة الثانية، البند 1): "trail اختفى من التقرير" —
    # التحقق السابق كان يفحص عنوان القسم فقط، لا وجود أسطره فعليًا؛ ثغرة كانت
    # لتترك عطل تصيير حقيقي (كل الأسطر تُفقد رغم ظهور العنوان) بلا رصد. هنا
    # نتحقق أن كل استعلام من trail له سطر فعلي في التقرير المُصيَّر، وأن
    # القسم مفتوح افتراضيًا (<details open>) لا مطويًا — فلا سبيل لأن يبدو
    # "اختفى" لقارئ لم ينقر لفتحه.
    check("4) كل استعلام في trail له سطر فعلي مُصيَّر في التقرير — لا عنوان قسم فارغ",
          all(t["query"] in report7 for t in out7["trail"]), report7)
    check("4) قسم trail مفتوح افتراضيًا (<details open>) لا مطويًا",
          "<details open>" in report7)

    # ── القاعدة 2: الرأي لا يُبحث له سند، ويصل الصياغة منفصلًا عن الوقائع ──
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار القاعدة 2",
        "statements": [
            {"text": "واقعة أولى مسندة", "kind": "واقعة", "entities": ["ك1"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": "واقعة ثانية مسندة", "kind": "واقعة", "entities": ["ك2"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": "أرى أن هذا القرار خاطئ تمامًا برأيي الشخصي", "kind": "رأي",
             "entities": [], "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    SUPPORT_MAP.clear()
    SUPPORT_MAP["واقعة أولى مسندة"] = ["مصدر أول", "مصدر ثانٍ"]
    SUPPORT_MAP["واقعة ثانية مسندة"] = ["مصدر أول", "مصدر ثانٍ"]
    seen_search_queries.clear()
    # include_opinion يُضبط صراحة true هنا — هذا الاختبار يتحقق من فصل الرأي
    # عن الوقائع حين يصل الرأي الصياغة أصلًا، لا من قيمة config.yaml
    # الافتراضية القابلة للتغيير (حالة إعادة إنتاج فعلية: تعطيلها لاحقًا في
    # config.yaml لمراجعة بشرية بعد أول نشر كسر هذا الاختبار بلا أي علاقة
    # بمنطقه — Issue #373، تعليق المراجعة الأخير)
    cfg_opinion_on = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg_opinion_on["article"]["source_extract_enabled"] = False
    cfg_opinion_on["article"]["include_opinion"] = True
    out2 = article._write_article("موجز اختبار القاعدة 2", 2, cfg_opinion_on)
    check("2) الرأي لا يُبحث عنه سند إطلاقًا — لا استعلام بحث يحوي نصه",
          not any("خاطئ" in q for q in seen_search_queries))
    check("2) الرأي يصل مرحلة الصياغة منفصلًا عن الوقائع المسندة لا مندمجًا فيها",
          seen_draft_calls[-1]["opinions"] ==
          ["أرى أن هذا القرار خاطئ تمامًا برأيي الشخصي"])
    check("2) الوقائع المُمرَّرة للصياغة لا تحوي نص الرأي إطلاقًا",
          "أرى أن هذا القرار خاطئ تمامًا برأيي الشخصي" not in seen_draft_calls[-1]["grounded"])
    check("2) برومبت الصياغة يطلب نسبة الرأي بصيغة تحريرية معلنة لا نقلًا حرفيًا",
          "لا تنقلها حرفيًا" in article.DRAFT_SYSTEM_TEMPLATE and
          "{opinion_phrase}" in article.DRAFT_SYSTEM_TEMPLATE)
    check("2) نسبة الرأي بصيغة تحريرية معلنة تُنشر فعليًا — لا عبارة داخلية",
          "بحسب صاحب الطلب" not in article.DRAFT_SYSTEM_TEMPLATE)

    # ── article.include_opinion=false (مراجعة بشرية بعد أول نشر، البند 3):
    # الرأي يُسقط كليًا من المتن بقرار تهيئة — لا لانعدام سند، فيجب أن يُذكر
    # في التقرير مميَّزًا عن "ما سقط من موجزي" ──
    cfg_no_opinion = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg_no_opinion["article"]["source_extract_enabled"] = False
    cfg_no_opinion["article"]["include_opinion"] = False
    out2b = article._write_article("موجز اختبار تعطيل الرأي", 2, cfg_no_opinion)
    check("include_opinion=false: الرأي لا يصل مرحلة الصياغة إطلاقًا",
          seen_draft_calls[-1]["opinions"] == [], seen_draft_calls[-1]["opinions"])
    check("include_opinion=false: outcome['opinion_note'] يذكر الإسقاط بقرار تهيئة "
          "لا انعدام سند",
          "قرار تهيئة" in out2b["opinion_note"], out2b["opinion_note"])
    report2b = article.build_report(out2b)
    check("include_opinion=false: ملاحظة إسقاط الرأي تظهر في التقرير مميَّزة عمّا سقط "
          "لانعدام سند",
          out2b["opinion_note"] in report2b, report2b)

    # مضبوطة صراحة true هنا أيضًا — لا اعتمادًا على قيمة config.yaml
    # الافتراضية (المضبوطة اليوم false لمراجعة بشرية)، فيبقى هذا الاختبار
    # يثبت سلوك الكود عند true بصرف النظر عمّا يُضبط في الملف مستقبلًا
    cfg_with_opinion = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg_with_opinion["article"]["source_extract_enabled"] = False
    cfg_with_opinion["article"]["include_opinion"] = True
    out2c = article._write_article("موجز اختبار الرأي عند include_opinion=true", 2,
                                    cfg_with_opinion)
    check("include_opinion=true صراحة: الرأي يصل الصياغة ولا ملاحظة إسقاط",
          seen_draft_calls[-1]["opinions"] != [] and out2c["opinion_note"] == "",
          (seen_draft_calls[-1]["opinions"], out2c["opinion_note"]))

    # ── القاعدة 3: لا رأي من معرفة النموذج ولا تحليل من عنده — لا صوت ثالث ──
    check("3) برومبت الصياغة يمنع صوتًا ثالثًا يضيفه النموذج بمعزل عن "
          "الوقائع المسندة أو رأي الموجز المنسوب",
          "لا صوت ثالث" in article.DRAFT_SYSTEM_TEMPLATE.format(opinion_phrase="x"))
    check("3) الوقائع المصاغة تُبنى من الوقائع المعطاة حصرًا — لا معرفة سابقة",
          "لا معرفة سابقة" in article.DRAFT_USER_TEMPLATE)
    check("3) برومبت تسمية الحدث يمنع الاستعانة بمعرفة النموذج الخاصة عن الحدث",
          "لا تستعن بمعرفتك الخاصة" in article.NAMING_SYSTEM)
    check("3) برومبت الحكم على السند يمنع الاستعانة بمعرفة النموذج الخاصة",
          "لا تستخدم معرفتك الخاصة" in article.SUPPORT_SYSTEM)
    # تعليق الموافقة الثاني، البند 3: الترجيح بالتكرار الخام (Counter) حُذف
    # كليًا — السياق يُستخلَص بنداء نموذج على نصوص البحث المرجعي فعليًا
    # (اختبار تكامل ذلك ضمن سلّم _name_event أدناه)، مع مرشِّح نافذة رخيص
    # (البديل ج) قبل النداء وبوابة اتساق (_naming_consistent، البند 2) —
    # كلتاهما دالّتان نقيتان تُختبران هنا مباشرة بلا شبكة
    check("3) برومبت استخلاص السياق يمنع الاستعانة بمعرفة النموذج الخاصة عن الكيان",
          "لا من معرفتك الخاصة" in article.CONTEXT_SYSTEM)
    check("3) برومبت الإجابة عن أسئلة الموجز يمنع الاستعانة بمعرفة النموذج الخاصة",
          "لا من معرفتك الخاصة" in article.ANSWER_SYSTEM)
    # تعليق العطل الثاني على Issue #361، البند 3: ANSWER_SCHEMA كانت الوحيدة
    # بين شقيقاتها الثلاث (SUPPORT/NAMING/ANSWER) التي لا تُلزم بحقل المصادر
    # — answered:true بسند فارغ كان يمرّ مخطط الأداة بلا رفض. الآن supporting
    # إلزامي تناظرًا مع SUPPORT_SCHEMA، وANSWER_SYSTEM يشدّد على اسم المصدر
    # كما تفعل SUPPORT_SYSTEM/NAMING_SYSTEM بالضبط
    check("3) ANSWER_SCHEMA تُلزم بحقل supporting الآن — تناظرًا مع SUPPORT_SCHEMA "
          "(كانت الوحيدة بين شقيقاتها الثلاث بلا هذا الإلزام)",
          "supporting" in article.ANSWER_SCHEMA["input_schema"]["required"])
    check("3) SUPPORT_SCHEMA تُلزم بحقل supporting أيضًا (المرجع الذي قِسنا عليه)",
          "supporting" in article.SUPPORT_SCHEMA["input_schema"]["required"])
    check("3) ANSWER_SYSTEM يشدّد على إخراج اسم المصدر كما ورد في وسم المصدر حرفيًا "
          "— بنفس صياغة SUPPORT_SYSTEM/NAMING_SYSTEM لا صياغة أضعف",
          "كما وردت في وسم" in article.ANSWER_SYSTEM or "كما ورد في وسم" in article.ANSWER_SYSTEM)
    # تشخيص Issue #373 (الجولة السادسة): أسئلة «كيف/لماذا» كانت تُرفض في
    # تشغيلات حقيقية بينما نفس النص يُجيب عن سؤال «من/ماذا» موازٍ بلا مشكلة
    # (مثال حقيقي: إجابة "من هو حمزة الخطيب؟" حوت بداية القصة حرفيًا، بينما
    # "كيف بدأت قصته؟" رجع بلا إجابة) — توضيح صريح في البرومبت أن معيار
    # القبول واحد لكل صيغ الأسئلة، لا معيارًا أشدّ للسردي/السببي
    check("ANSWER_SYSTEM يوضّح صراحة أن أسئلة «كيف/لماذا» تُقاس بنفس معيار "
          "«من/ماذا» — لا معيار أشدّ يرفض إجابة موجودة فعليًا لصياغتها السردية",
          "كيف/لماذا" in article.ANSWER_SYSTEM and "نفس معيار" in article.ANSWER_SYSTEM)
    check("3) نافذة الاستخلاص الرخيصة (البديل ج) تقتصر على مطلع النص لا كامله",
          article._narrow_for_context("س" * 900, max_chars=400) == "س" * 400)

    check("2) بوابة الاتساق تقبل تسمية تذكر كيان الواقعة الأصلية في نص التسمية نفسه "
          "(بلا تاريخ في dates — تراجع لفحص الكيانات وحده)",
          article._naming_consistent(
              "حكم إعدام بحق عاطف نجيب في قضية حمزة الخطيب", ["حمزة الخطيب"], [], [], cfg))
    check("2) بوابة الاتساق تقبل تسمية لا تذكر الكيان في نصها لكن وثائقها تذكره",
          article._naming_consistent(
              "حكم إعدام غيابي بحق ثلاثة متهمين", ["حمزة الخطيب"], [],
              [{"name": "م", "text": "شمل الحكم قضية حمزة الخطيب في درعا"}], cfg))
    check("2) بوابة الاتساق ترفض تسمية لا تذكر الكيان لا في نصها ولا في وثائقها "
          "— فشل «لبّاد» في التشخيص المعتمَد بالضبط",
          not article._naming_consistent(
              "تداول فيديو لفتى آخر لا صلة له بالحدث", ["حمزة الخطيب"], [],
              [{"name": "م", "text": "خبر عن تداول فيديو لمراهق آخر لا صلة له"}], cfg))

    # ── بوابة اتساق التاريخ (تعليق التنفيذ على Issue #364، البند 2): الكيان
    # وحده لا يكفي — التشغيل الحقيقي سمّى حدثًا بحديث حقيقي عن الكيان الصحيح
    # لكنه ليس الحدث المقصود بتاريخه. أمثلة اصطناعية هنا لا الحدث الفعلي ──
    check("2) بوابة الاتساق تقبل تسمية يتفق تاريخها (سنة+شهر) رغم فارق يوم "
          "ضمن النافذة (naming_date_window_days)",
          article._naming_consistent(
              "حكم صدر بحق المتهمين في قضية كيان اختباري", ["كيان اختباري"],
              ["11 آب 2026"],
              [{"name": "م", "text": "حكم في قضية كيان اختباري صدر في 12 آب 2026"}], cfg))
    check("2) بوابة الاتساق ترفض تسمية بتاريخ (سنة) مختلف تمامًا رغم اتفاق "
          "الكيان — التاريخ شرط إضافي لا الكيان وحده",
          not article._naming_consistent(
              "حديث سابق يذكر كيان اختباري", ["كيان اختباري"], ["11 آب 2026"],
              [{"name": "م", "text": "في مقابلة أجريت في يونيو 2011 ذُكر كيان اختباري"}],
              cfg))
    check("2) غياب أي تاريخ منظَّم فعليًا في dates (مثلًا مدة لا تاريخ تقويمي) "
          "لا يُقيِّد التسمية بتاريخ — تراجع لفحص الكيانات وحده كما كان",
          article._naming_consistent(
              "خبر عن كيان اختباري", ["كيان اختباري"], ["15 عامًا"],
              [{"name": "م", "text": "تقرير يذكر كيان اختباري"}], cfg))

    # ── تخفيف Issue #373 (الجولة الخامسة، البند 2): تاريخ صريح مطابق يكفي
    # وحده للقبول، حتى بلا أي ذكر للكيان — الشاهد الفعلي: خبر حكم الإعدام
    # بحق الأسد لم يذكر «حمزة الخطيب» في عنوانه/متنه قط، لكن تاريخه يطابق
    # تاريخ الإشارة المبهمة الأصلية. مرآة عكسية لفشل «لبّاد» أعلاه: هناك
    # الكيان غائب و**لا معلومة تاريخ** فيُرفض؛ هنا الكيان غائب لكن **التاريخ
    # يطابق صراحة** فيُقبل — الفارق هو بالضبط ما صُمِّمت من أجله الحالات
    # الثلاث (DATE_NO_INFO/DATE_MATCH/DATE_MISMATCH) بدل bool واحد ==
    check("2) بوابة الاتساق تقبل تسمية لا تذكر الكيان إطلاقًا (لا في نصها ولا "
          "في وثائقها) إن تفق تاريخها صراحةً مع تاريخ الواقعة الأصلية — "
          "التاريخ وحده يكفي حين يكون صريحًا ومطابقًا (تخفيف Issue #373)",
          article._naming_consistent(
              "حكم بإعدام المتهمين الثلاثة غيابيًا", ["كيان اختباري"],
              ["11 آب 2026"],
              [{"name": "م", "text": "المحكمة أصدرت حكمها في 11 آب 2026"}], cfg))
    # وبالمقابل: تعارض تاريخ صريح يبقى رفضًا قاطعًا حتى مع ذكر الكيان
    # الصحيح (فشل جنبلاط أعلاه) — التخفيف لا يعني أن "OR" ساذجة تُنقض حالة
    # الرفض الحاسمة؛ راجع توثيق _naming_consistent لماذا هذا مقصود لا سهو
    check("2) تعارض تاريخ صريح يبقى رفضًا قاطعًا رغم ذكر الكيان — لا OR ساذجة "
          "تُنقض حالة الرفض الحاسمة (فشل جنبلاط، مُعاد تأكيدها هنا صراحة)",
          not article._naming_consistent(
              "حديث سابق يذكر كيان اختباري", ["كيان اختباري"], ["11 آب 2026"],
              [{"name": "م", "text": "في مقابلة أجريت في يونيو 2011 ذُكر كيان اختباري"}],
              cfg))

    # اختبار مباشر لـ_dates_consistent (الحالات الثلاث الصريحة، لا bool)
    check("article._dates_consistent: DATE_NO_INFO حين لا تاريخ منظَّم في dates",
          article._dates_consistent("نص", ["15 عامًا"], [], 2) == article.DATE_NO_INFO)
    check("article._dates_consistent: DATE_MATCH حين يتفق التاريخ",
          article._dates_consistent("حدث في 11 آب 2026", ["11 آب 2026"], [], 2)
          == article.DATE_MATCH)
    check("article._dates_consistent: DATE_MISMATCH حين لا يتفق أي تاريخ في target "
          "(بما فيها غياب أي تاريخ في target كليًا)",
          article._dates_consistent("نص بلا أي تاريخ", ["11 آب 2026"], [], 2)
          == article.DATE_MISMATCH)

    check("article._extract_dates: يوم+شهر+سنة يُستخرجان كتاريخ منظَّم واحد لا سنة مجردة مكرَّرة",
          set(article._extract_dates("صدر الحكم في 12 آب 2026")) ==
          {(2026, 8, 12)})
    check("article._extract_dates: سنة مجردة بلا شهر تُستخرج أيضًا (تراجع)",
          (2026, None, None) in article._extract_dates("في عام 2026 وحده"))

    # ── _merge_named_evidence (تشخيص Issue #373، الجولة السادسة): افصل السند
    # عن الاكتشاف — دورة سند ثانية بعد التسمية، بكيانات الحدث المسمّى لا
    # كيانات الإشارة المبهمة، تُدمَج مع أدلة الاكتشاف. التوحيد بهوية الناشر
    # (evidence._canonical_publisher) كان يعمل داخل دورة بحث واحدة فقط
    # (الجولة الرابعة) — هنا يجب أن يعمل عبر دورتين منفصلتين أيضًا، وإلا
    # عاد عطل «الجزيرة نت»/«Al Jazeera» بين دورة الاكتشاف ودورة السند تحديدًا ──
    merged_docs, merged_supporting = article._merge_named_evidence(
        [{"name": "الجزيرة نت", "link": "https://aj-ar/1", "text": "نص عربي"}],
        ["الجزيرة نت"],
        [{"name": "Al Jazeera", "link": "https://aj-en/1", "text": "نص إنجليزي"},
         {"name": "BBC News", "link": "https://bbc/1", "text": "نص BBC"}],
        ["Al Jazeera", "BBC News"],
        cfg)
    check("_merge_named_evidence: نسخة عربية من دورة الاكتشاف ونسخة إنجليزية من دورة "
          "السند لناشر واحد تُوحَّدان — لا تُحسبان مصدرين مستقلين (نقض شرط «مصدران "
          "مستقلان» لو مرّتا معًا بلا توحيد)",
          len(merged_supporting) == 2 and len(merged_docs) == 2, (merged_docs, merged_supporting))
    check("_merge_named_evidence: الاسم الناجي هو أول من سجَّل الهوية (دورة الاكتشاف "
          "— 'الجزيرة نت') لا اسم دورة السند اللاحقة",
          "الجزيرة نت" in merged_supporting and "Al Jazeera" not in merged_supporting,
          merged_supporting)
    check("_merge_named_evidence: ناشر مستقل حقيقي (BBC News) من دورة السند يبقى "
          "بلا تأثر بالتوحيد",
          "BBC News" in merged_supporting, merged_supporting)

    # ── القاعدة 6: برومبت مستقل — لا يمسّ writer.SYSTEM_PROMPT ولا يستعمل آلياته ──
    check("6) برومبت صياغة المقال مستقل تمامًا عن writer.SYSTEM_PROMPT",
          article.DRAFT_SYSTEM_TEMPLATE != writer.SYSTEM_PROMPT and
          writer.SYSTEM_PROMPT not in article.DRAFT_SYSTEM_TEMPLATE)
    check("6) أداة الصياغة مستقلة عن أداة writer.py (اسم أداة مختلف)",
          article.ARTICLE_POST_SCHEMA["name"] != writer.POST_SCHEMA["name"])
    check("6) نداء الشبكة مستقل عن writer._call_model (الذي يُحمِّل "
          "writer.SYSTEM_PROMPT داخليًا بلا معامل يسمح باستبداله)",
          article._call_draft_model is not writer._call_model)

    # ── article.post_length مستقل عن writer.post_length (مراجعة بشرية بعد
    # أول نشر، البند 2): منتج مختلف يستحق متنًا أطول من منشور الجمع القصير ──
    check("article.post_length مضبوط في config.yaml ومختلف عن writer.post_length "
          "(منتج مستقل، لا وريث قيمة الجمع)",
          cfg.path("article.post_length") and
          cfg.path("article.post_length") != cfg.path("writer.post_length"),
          (cfg.path("article.post_length"), cfg.path("writer.post_length")))
    check("7) برومبت الصياغة يوجّه صراحة لاستيعاب كل الوقائع المسندة بلا اختصار "
          "مفرط",
          "لا تختصرها في جملة واحدة" in
          article.DRAFT_SYSTEM_TEMPLATE.format(opinion_phrase="x"))

    # ── القاعدة 8 (تشخيص Issue #373، الجولة الرابعة عشرة): مزاعم متحدث عن
    # أرقام/قدرات عسكرية-أمنية تُصاغ كمزاعم في صلب الجملة، لا كمعلومة مؤكدة ──
    check("8) برومبت الصياغة يوجّه صراحة لصياغة مزاعم [تصريح لـ...] كمزاعم "
          "قائلها في صلب الجملة، لا كمعلومة مؤكَّدة",
          "[تصريح لـ" in article.DRAFT_SYSTEM_TEMPLATE and
          "وزعم فلان" in article.DRAFT_SYSTEM_TEMPLATE)
    check("_facts_block: واقعة من kind=='تصريح' تُعلَّم بـ'[تصريح لـ<speaker>]' "
          "ظاهرة للنموذج — لا تُصاغ كواقعة عادية",
          article._facts_block([
              {"text": "زعم أنه يملك صواريخ", "kind": "تصريح", "speaker": "فلان"},
          ]) == "- [تصريح لـفلان] زعم أنه يملك صواريخ")
    check("_facts_block: واقعة عادية (kind=='واقعة') بلا وسم — لا تمييز زائف "
          "لواقعة مسندة مباشرة",
          article._facts_block([{"text": "وقعت الواقعة", "kind": "واقعة"}]) ==
          "- وقعت الواقعة")
    check("_facts_block: تصريح بلا speaker مُسجَّل (فراغ/غياب) يُعلَّم بعلامة "
          "استفهام بدل انهيار أو حذف الوسم",
          article._facts_block([{"text": "نص", "kind": "تصريح", "speaker": ""}]) ==
          "- [تصريح لـ؟] نص")

    captured_draft_prompts: list = []

    def _capture_call_draft_model(prompt, system_text, cfg, retries=3):
        captured_draft_prompts.append(prompt)
        return {"post_title": "عنوان اختبار", "post_body": "متن اختبار",
               "hashtags": [], "category": "عالم"}

    article._call_draft_model = _capture_call_draft_model
    cfg_custom_length = load_config()
    cfg_custom_length["article"]["post_length"] = "999 كلمة اختبارية فريدة"
    real_draft_article(
        [{"text": "واقعة اختبار الطول", "sources": []}], [], "سؤال اختبار؟",
        cfg_custom_length)
    check("article.post_length مُستعمَل فعليًا في برومبت الصياغة — لا writer.post_length",
          any("999 كلمة اختبارية فريدة" in p for p in captured_draft_prompts),
          captured_draft_prompts)
    article._call_draft_model = real_call_draft_model

    # ── القاعدة 5 + تسمية الحدث المبهم، مقلوبة الترتيب (تعليق الموافقة
    # الثاني، البنود 1/2/3/4/7): موجز يصف أثر حدث بلا تسميته ──
    naming_search_calls: list = []

    def _naming_search(query, cfg, days, unrestricted=False, require_relevance=True):
        naming_search_calls.append((query, unrestricted, require_relevance))
        return [object()]

    def _naming_gather(articles, cfg, claim_text="", loose_relevance=False):
        if claim_text == "حمزة الخطيب":
            # المرحلة المرجعية (احتياطية، البند 3): سيرة الكيان — سياقها
            # الفعلي "سوريا" مذكور مرارًا، لا حشوًا
            return ([
                {"name": "أرشيف تاريخي", "link": "https://ref/1", "from_text": True,
                 "text": "حمزة الخطيب رمز من انتفاضة سوريا 2011 في درعا سوريا"},
                {"name": "مصدر مرجعي ثانٍ", "link": "https://ref/2", "from_text": True,
                 "text": "قصة حمزة الخطيب في سوريا لا تزال حاضرة اليوم"},
            ], evidence.EVIDENCE_FULL_TEXT)
        if "سوريا" in claim_text:
            # استعلام سياق+تاريخ (المرحلة الاحتياطية الثانية): يجد الحدث
            # الصحيح فعلًا، ووثائقه تذكر «حمزة الخطيب» — تجتاز بوابة الاتساق
            return ([
                {"name": "وكالة الحدث", "link": "https://event/1", "from_text": True,
                 "text": ("صدر حكم إعدام غيابي في 11 آب 2026 بحق بشار الأسد وماهر الأسد "
                         "وعاطف نجيب، وشملت اللائحة قضية حمزة الخطيب في درعا")},
                {"name": "وكالة ثانية", "link": "https://event/2", "from_text": True,
                 "text": ("أكدت مصادر قضائية صدور حكم الإعدام الغيابي بحق الأسد ونجيب "
                         "المتهم أيضًا في ملف حمزة الخطيب")},
            ], evidence.EVIDENCE_FULL_TEXT)
        if "الخطيب" in claim_text:
            # المرحلة المباشرة (البند 1: كيانات+تاريخ، تُجرَّب أولًا) —
            # بلا سياق مكتشَف بعد، الاستعلام العام لا يجد الحدث الصحيح
            return ([], evidence.EVIDENCE_NO_RESULTS)
        return ([{"name": "مصدر أول", "text": "نص", "link": "https://g1/1", "from_text": True},
                 {"name": "مصدر ثانٍ", "text": "نص", "link": "https://g2/1", "from_text": True}],
                evidence.EVIDENCE_FULL_TEXT)

    def _naming_ask_model(vague_text, entities, docs, cfg):
        if any("حكم إعدام" in d["text"] for d in docs):
            return {"text": "صدر حكم إعدام غيابي بحق بشار الأسد وماهر الأسد وعاطف نجيب",
                   "supporting": [d["name"] for d in docs]}
        return None

    def _naming_context(entity, exclude_entities, docs, cfg, max_terms):
        if any("سوريا" in d.get("text", "") for d in docs):
            return ["سوريا"][:max_terms]
        return []

    evidence.search = _naming_search
    evidence.gather_evidence = _naming_gather
    article._ask_naming_model = _naming_ask_model
    article._ask_context_model = _naming_context
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "حدث 11 آب 2026",
        "statements": [
            {"text": "حدث في 11 آب 2026 ما أعاد قصة حمزة الخطيب", "kind": "واقعة",
             "entities": ["حمزة الخطيب", "11 آب 2026"], "is_unnamed_event": True,
             "is_reference": False},
            {"text": "واقعة إضافية مسندة عاديًا", "kind": "واقعة", "entities": ["كس"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    SUPPORT_MAP.clear()
    SUPPORT_MAP["واقعة إضافية مسندة عاديًا"] = ["مصدر أول", "مصدر ثانٍ"]
    ANSWER_MAP.clear()  # سؤال الصلة المُصنَّع (البند 7) بلا إجابة عمدًا — يُبحث ويبقى بلا إجابة

    out_naming = article._write_article(
        "موجز: حدث في 11 آب 2026 ما أعاد قصة حمزة الخطيب.", 348, cfg)

    check("الحدث المبهم يُسمّى بواقعة صريحة جديدة — لا يبقى وصف أثر مبهمًا",
          any(d["sources_say"] ==
              "صدر حكم إعدام غيابي بحق بشار الأسد وماهر الأسد وعاطف نجيب"
              for d in out_naming["diffs"]), out_naming)
    check("الخلاف بين صياغة موجزي والحدث الذي سمّته المصادر يُذكر لي صراحة",
          any(d["brief"] == "حدث في 11 آب 2026 ما أعاد قصة حمزة الخطيب"
              for d in out_naming["diffs"]))
    check("1) السلّم يجرّب كيانات+تاريخ مباشرةً أولًا — بلا بحث مرجعي مسبق",
          naming_search_calls[0][1] is False and "الخطيب" in naming_search_calls[0][0])
    first_unrestricted = next(i for i, c in enumerate(naming_search_calls) if c[1])
    check("1) البحث المرجعي غير المقيَّد لا يقع إلا بعد فشل المرحلة المباشرة "
          "(احتياطي لا رئيسي، تعليق الموافقة الثاني)",
          first_unrestricted > 0 and naming_search_calls[first_unrestricted][0] == "حمزة الخطيب")
    check("3) استعلام لاحق يستعمل السياق المكتشَف (سوريا) بنداء نموذج على "
          "نصوص البحث المرجعي — لا الوصف المبهم الأصلي حرفيًا",
          any("سوريا" in q and not unrestricted
              for q, unrestricted, _rr in naming_search_calls[first_unrestricted + 1:]))
    check("بحث بالوصف المبهم حرفيًا (أعاد قصة) لا يقع إطلاقًا",
          not any("أعاد قصة" in q for q, _u, _rr in naming_search_calls))
    check("المقال يُنتَج فعلًا بعد تسمية الحدث ومروره ببوابة السند",
          out_naming["produced"] is True, out_naming.get("reason"))
    check("4) trail يشمل مراحل التسمية الثلاث (مباشر/مرجعي/سياق) مع حصيلة كل استعلام",
          {"مباشر", "مرجعي", "سياق"} <= {t["stage"] for t in out_naming["trail"]})
    check("7) بعد تسمية الحدث، الصلة بكيان الموجز الأصلي تُصاغ سؤالًا ويُبحث "
          "بدل افتراضها بديهية",
          any(q["text"].startswith("ما الصلة بين") for q in out_naming["unanswered"]))
    # طلب التنفيذ على Issue #373، البند 1: require_relevance=False حصرًا
    # لمرحلتَي «مباشر»/«سياق» — لا «مرجعي» (بحث سيرة الكيان نفسه، فلتر
    # الصلة مفيد فيها كما هو، فتبقى على الافتراضي True). عبر trail لا
    # naming_search_calls الخام: تلك تلتقط أيضًا استعلامات "واقعة"/"سؤال"
    # الأخرى في _write_article (لا تمرّ عبر _try) فلا تصلح للمطابقة المباشرة
    check("1) مراحل «مباشر»/«سياق» في trail مُعلَّمة صراحة بلا تصفية صلة",
          all(t.get("unfiltered_relevance") is True for t in out_naming["trail"]
              if t["stage"] in ("مباشر", "سياق")),
          [t for t in out_naming["trail"] if t["stage"] in ("مباشر", "سياق")])
    check("1) مرحلة «مرجعي» لا تحمل علامة unfiltered_relevance — تبقى على "
          "فلتر الصلة الافتراضي (require_relevance=True) لا يتأثر بعلاج مباشر/سياق",
          all(not t.get("unfiltered_relevance") for t in out_naming["trail"]
              if t["stage"] == "مرجعي"),
          [t for t in out_naming["trail"] if t["stage"] == "مرجعي"])

    # ── تعليق العطل الثاني على Issue #361، البند 1: trail يعرض عدد النتائج
    # الخام/المطابقة (قبل التصفية بالصلة وبعدها) وسبب فشل كل رابط تعذّر جلبه
    # — لا "عناوين فقط" مجرَّدة بلا تفسير كما كشف التشغيل الحقيقي على استعلام
    # 11 آب. اختبار تكامل حقيقي لـ evidence.search/evidence.gather_evidence
    # (لا فاكات مباشرة لهما هنا كبقية هذه الدالة) عبر article._name_event،
    # بمحاكاة سيناريو الفشل الفعلي: نتيجة بحث تُوجَد فعلًا، لكن جلب نصها
    # الكامل يفشل بـ HTTP 403 فيسقط المسار لاحتياط العناوين بمصدر واحد.
    evidence.search = real_search
    evidence.gather_evidence = real_gather_evidence

    trail_article = Article(
        title="حدث اختباري بمصدر واحد في 11 آب 2026", link="https://blocked.example/1",
        summary="", source_name="مصدر محجوب", region="global", weight=1.0,
        published=datetime.now(timezone.utc), publisher="مصدر محجوب")

    real_fetch_source3 = evidence.fetch_source
    real_extract_gather3 = extract.gather
    evidence.fetch_source = lambda src, max_age_hours: [trail_article]
    extract.gather = lambda members, limit=2: (
        [], [{"name": "مصدر محجوب", "link": "https://blocked.example/1", "reason": "HTTP 403"}])
    article._ask_naming_model = lambda vague_text, entities, docs, cfg: (
        {"text": "حدث اختباري تم تسميته", "supporting": [d["name"] for d in docs]}
        if docs else None)
    try:
        _, _, _, name_trail2 = article._name_event(
            {"text": "إشارة اختبارية", "entities": ["كيان اختباري", "11 آب 2026"]}, cfg)
    finally:
        evidence.fetch_source = real_fetch_source3
        extract.gather = real_extract_gather3

    direct_entry = next(t for t in name_trail2 if t["stage"] == "مباشر")
    check("1) trail يعرض raw_count/matched_count حقيقيين من evidence.search "
          "— لا None حين البحث فعلي لا مزيَّف (تشخيص تعليق العطل الثاني)",
          direct_entry["raw_count"] is not None and
          direct_entry["raw_count"] == direct_entry["matched_count"] and
          direct_entry["raw_count"] > 0, direct_entry)
    check("1) trail يعرض سبب فشل جلب النص الكامل لكل رابط (رمز HTTP) حين "
          "يسقط المسار لاحتياط العناوين — لا 'عناوين فقط' مجرَّدة بلا تفسير",
          direct_entry["fetch_failures"] ==
          [{"name": "مصدر محجوب", "link": "https://blocked.example/1", "reason": "HTTP 403"}],
          direct_entry)
    check("1) الأساس فعلًا احتياط العناوين — سيناريو الفشل المشخَّص بالضبط",
          direct_entry["basis"] == evidence.EVIDENCE_HEADLINES_ONLY)
    report_trail = article.build_report({**article._new_outcome(), "trail": name_trail2})
    check("1) التقرير النهائي يعرض عدد النتائج الخام/المطابقة وسبب فشل الجلب فعليًا "
          "لا مجرَّدين من التفاصيل",
          f"{direct_entry['raw_count']} خام" in report_trail and "HTTP 403" in report_trail,
          report_trail)

    # طلب التنفيذ على Issue #373، البند 1: فلتر الصلة قبل البحث مُعطَّل
    # كليًا لمرحلة «مباشر» الآن (raw==matched==2 رغم أن أحد المصدرين لا
    # يشارك أي كلمة مع الاستعلام) — لا مجرَّد عيّنة تشخيصية كما كان سابقًا.
    # استدعاء معزول بمصدرين، أحدهما لا يشارك أي كلمة مع الاستعلام، كي لا
    # يمسّ raw_count==matched_count(=1) المتحقَّق منه أعلاه لسيناريو المصدر
    # الواحد
    irrelevant_naming = Article(
        title="مباراة كرة قدم ودّية بين ناديين محليين", link="https://irrelevant.example/1",
        summary="", source_name="مصدر عام", region="global", weight=1.0,
        published=datetime.now(timezone.utc), publisher="مصدر عام")
    evidence.fetch_source = lambda src, max_age_hours: [trail_article, irrelevant_naming]
    extract.gather = lambda members, limit=2: (
        [], [{"name": "مصدر محجوب", "link": "https://blocked.example/1", "reason": "HTTP 403"}])
    try:
        _, _, _, name_trail3 = article._name_event(
            {"text": "إشارة اختبارية", "entities": ["كيان اختباري", "11 آب 2026"]}, cfg)
    finally:
        evidence.fetch_source = real_fetch_source3
        extract.gather = real_extract_gather3

    direct_entry3 = next(t for t in name_trail3 if t["stage"] == "مباشر")
    check("1) مرحلة «مباشر» لا تصفّي بالصلة قبل البحث — نتيجة لا تشارك أي "
          "كلمة مع الاستعلام تدخل الفرز رغم ذلك (raw==matched رغم وجودها)",
          direct_entry3["raw_count"] == direct_entry3["matched_count"] > 0 and
          "مصدر عام" in direct_entry3["sources"],
          direct_entry3)
    check("1) trail يسجّل صراحة أن الفرز جرى بلا تصفية صلة لمرحلة «مباشر» "
          "(طلب التنفيذ، البند 1: تسجيل عدد المرشحين الذين دخلوا الفرز بلا تصفية)",
          direct_entry3.get("unfiltered_relevance") is True, direct_entry3)
    check("1) لا حقل rejected_titles إطلاقًا — الفلتر الذي كان يرفض نتائج "
          "قبل البحث مُعطَّل هنا لا موثَّق فقط بعيّنة",
          "rejected_titles" not in direct_entry3, direct_entry3)
    report_trail3 = article.build_report({**article._new_outcome(), "trail": name_trail3})
    check("1) التقرير يعرض ملاحظة «بلا تصفية صلة» لمرحلة «مباشر»",
          "بلا تصفية صلة" in report_trail3, report_trail3)

    # ── الدرجة الثالثة في السلّم (البند 2، تشخيص Issue #373): تاريخ + كلمة
    # من topic العام حين تفشل «مباشر» و«سياق» كلتاهما ──
    topic_words_seen: list = []
    real_topic_words = article._topic_words

    def _spy_topic_words(topic, exclude, max_words):
        words = real_topic_words(topic, exclude, max_words)
        topic_words_seen.append((topic, exclude, words))
        return words

    topic_stage_calls: list = []

    def _topic_search(query, cfg, days, unrestricted=False, require_relevance=True):
        topic_stage_calls.append((query, unrestricted, require_relevance))
        return [object()]

    def _topic_gather(articles, cfg, claim_text="", loose_relevance=False):
        if "قضية" in claim_text:  # كلمة من topic + تاريخ (الدرجة الثالثة تحديدًا)
            return ([{"name": "مصدر الموضوع", "link": "https://topic/1", "from_text": True,
                      "text": "حكم صدر بحق كيان بلا سياق في قضية قديمة بتاريخ 11 آب 2026"}],
                    evidence.EVIDENCE_FULL_TEXT)
        return ([], evidence.EVIDENCE_NO_RESULTS)  # مباشر، ثم سياق (بلا سياق مكتشَف)، يفشلان

    def _topic_ask_naming(vague_text, entities, docs, cfg):
        if docs:
            return {"text": "حكم صدر بحق كيان بلا سياق في قضية قديمة",
                   "supporting": [d["name"] for d in docs]}
        return None

    evidence.search = _topic_search
    evidence.gather_evidence = _topic_gather
    article._topic_words = _spy_topic_words
    article._ask_naming_model = _topic_ask_naming
    article._ask_context_model = lambda *a, **k: []  # لا سياق يُستخلَص — تفشل المرحلة الثانية فعليًا

    named_text3, _docs3, _supporting3, trail3 = article._name_event(
        {"text": "حدث ما أعاد قضية قديمة", "entities": ["كيان بلا سياق", "11 آب 2026"]},
        cfg, topic="قضية اختبارية قديمة جدًا")

    article._topic_words = real_topic_words
    check("2) الدرجة الثالثة (موضوع+تاريخ) تُجرَّب حين تفشل مباشر وسياق كلتاهما",
          any(t["stage"] == "موضوع" for t in trail3), trail3)
    check("2) الحدث يُسمّى فعلًا من الدرجة الثالثة حين تنجح وحدها",
          named_text3 == "حكم صدر بحق كيان بلا سياق في قضية قديمة", named_text3)
    check("2) كلمة الموضوع مُشتقّة من topic — لا من نص الواقعة المبهم نفسه "
          "(القاعدة 3: البحث بالوصف المبهم حرفيًا ممنوع بنيويًا)",
          bool(topic_words_seen) and
          not any("أعاد قضية" in q for q, _u, _rr in topic_stage_calls))
    check("2) _topic_words تستبعد كلمات كيانات الواقعة الأصلية (مجرَّبة أصلًا "
          "في المرحلة الأولى) كي لا تكرّر استعلامًا سبق تجربته",
          "كيان" not in article._topic_words("قصة كيان بلا سياق قديمة", ["كيان بلا سياق"], 3))

    evidence.search = _fake_search
    evidence.gather_evidence = _fake_gather_evidence
    article._ask_naming_model = real_ask_naming_model
    article._ask_context_model = real_ask_context_model

    # ── دورة سند ثانية بعد تسمية حدث مبهم، مندمجة مع أدلة الاكتشاف (تشخيص
    # Issue #373، الجولة السادسة — «افصل السند عن الاكتشاف»): استعلام
    # الاكتشاف يبقى ضيقًا بنيويًا حتى بعد نجاح التسمية — شاهد حقيقي: 4
    # نتائج فقط لحدث غطّته عشرات المصادر، معظمها تعذّر جلبها فبقي مصدر
    # واحد دون الحد الأدنى. دورة سند ثانية مستقلة بكيانات الحدث المسمّى
    # نفسه (لا كيانات الإشارة المبهمة) يجب أن تُدمَج نتائجها لتكمل السند
    # لا أن تُهدَر أو تُسقَط الواقعة رغم سند كافٍ فعليًا مجتمعًا ──
    real_name_event = article._name_event

    def _fake_name_event_thin(statement, cfg, topic=""):
        # دورة الاكتشاف وحدها وجدت مصدرًا واحدًا فقط — دون الحد الأدنى
        return ("نص الحدث المسمّى فعلًا",
               [{"name": "مصدر التسمية", "link": "https://naming/1",
                 "text": "نص التسمية", "from_text": True}],
               ["مصدر التسمية"],
               [{"stage": "مباشر", "query": "كيان اختباري 1 يناير 2026",
                 "basis": evidence.EVIDENCE_FULL_TEXT, "sources": ["مصدر التسمية"],
                 "raw_count": 4, "matched_count": 4, "fetch_failures": [],
                 "unfiltered_relevance": True, "outcome": "سُمّي الحدث"}])

    second_round_queries: list = []

    # كائنات Article وهمية بصور — تختبر أن دورة السند الثانية تمرّر ranked
    # الحقيقي لا [] حرفيًا (التشخيص المؤكَّد: الفرع القديم كان يمرّر ranked=[]
    # فتصل كل مصادره image_candidates فارغة دومًا مهما توفّرت صور فعليًا)
    from types import SimpleNamespace
    support_ranked_articles = [
        SimpleNamespace(publisher="مصدر سند أول", source_name="",
                        image_candidates=["https://img.test/1.jpg"]),
        SimpleNamespace(publisher="مصدر سند ثانٍ", source_name="",
                        image_candidates=["https://img.test/2.jpg"]),
    ]

    def _fake_search_second(query, cfg, days, unrestricted=False):
        second_round_queries.append(query)
        return support_ranked_articles

    def _fake_gather_second(articles, cfg, claim_text=""):
        return ([{"name": "مصدر سند أول", "link": "https://support/1", "from_text": True,
                  "text": "نص سند أول"},
                 {"name": "مصدر سند ثانٍ", "link": "https://support/2", "from_text": True,
                  "text": "نص سند ثانٍ"}], evidence.EVIDENCE_FULL_TEXT)

    def _fake_support_second(fact_text, docs, cfg, is_statement=False, is_report=False, publisher=""):
        if fact_text in ("نص الحدث المسمّى فعلًا", "واقعة إضافية عادية"):
            return ["مصدر سند أول", "مصدر سند ثانٍ"]
        return []

    article._name_event = _fake_name_event_thin
    evidence.search = _fake_search_second
    evidence.gather_evidence = _fake_gather_second
    article._support_sources = _fake_support_second
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار دورة السند الثانية",
        "statements": [
            {"text": "إشارة مبهمة لحدث لم يُسمَّ", "kind": "واقعة",
             "entities": ["كيان اختباري", "1 يناير 2026"],
             "is_unnamed_event": True, "is_reference": False},
            {"text": "واقعة إضافية عادية", "kind": "واقعة", "entities": ["كق"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)

    try:
        out_support = article._write_article("موجز اختبار دورة السند الثانية", 3732, cfg)
    finally:
        article._name_event = real_name_event

    check("دورة السند الثانية: مصدر التسمية وحده (1) دون الحد الأدنى، لكن الدمج مع "
          "دورة سند ثانية (مصدران إضافيان) يكفي — الواقعة تدخل المقال لا تسقط",
          not any(d["text"] == "نص الحدث المسمّى فعلًا" for d in out_support["dropped"]),
          out_support["dropped"])
    check("دورة السند الثانية: استعلامها استعلام فعلي منفصل — بُني بعد التسمية "
          "بكيانات الحدث المسمّى، لا حصيلة فشل بلا محاولة (3 نداءات بحث: دورة "
          "السند، الواقعة العادية، وسؤال الصلة البند 7 بعد التسمية)",
          len(second_round_queries) == 3 and all(second_round_queries), second_round_queries)
    check("دورة السند الثانية: trail يحوي مرحلة «سند» منفصلة عن مراحل الاكتشاف، "
          "باستعلامها المسجَّل فعليًا لا فارغًا",
          any(t["stage"] == "سند" and t["query"] == second_round_queries[0]
              for t in out_support["trail"]), out_support["trail"])
    check("دورة السند الثانية: المقال يُنتَج فعلًا بعد الدمج (واقعتان مسندتان تكفيان "
          "min_grounded_facts)",
          out_support["produced"] is True, out_support.get("reason"))
    check("دورة السند الثانية: مصادر الدمج الثلاثة كلها تصل قائمة المصادر النهائية "
          "(مصدر التسمية + مصدرا السند)",
          {"مصدر التسمية", "مصدر سند أول", "مصدر سند ثانٍ"} <=
          {s["name"] for s in out_support["sources"]}, out_support.get("sources"))
    # تشخيص Issue #373 (مراجعة بشرية بعد أول نشر، البند 1): «الصورة غائبة
    # ولا سبب في التقرير» — الفرع القديم كان يمرّر ranked=[] حرفيًا لمصادر
    # فرع الحدث المبهم، فتصل image_candidates فارغة دومًا. صور دورة السند
    # الثانية (support_ranked_articles أعلاه) يجب أن تصل فعليًا الآن.
    check("دورة السند الثانية: صورة من مصادر دورة السند الثانية استُخدمت فعليًا "
          "(لا [] فارغ يُسقط كل الصور بصرف النظر عمّا هو متاح)",
          out_support.get("image_source_name") in ("مصدر سند أول", "مصدر سند ثانٍ"),
          out_support.get("image_source_name"))
    check("دورة السند الثانية: تقرير الصورة يسجّل أنها استُخدمت من مصدر مسند مباشرة",
          out_support.get("image_report", {}).get("used_original") is True,
          out_support.get("image_report"))

    article._support_sources = _fake_support

    # ── سؤال الصلة: افصل السند عن الاكتشاف كذلك (تشخيص Issue #373، الجولة
    # الثانية عشرة، البند 2): أدلة [تسمية]/[سند] المُوحَّدة الهوية أصلًا يجب
    # أن تصل حلقة أسئلة الموجز كإضافة لا بديلًا — إهدارها بالاعتماد على
    # تفاوت نتائج بحث حي جديد وحده هو العطل المُشخَّص. الفاك أدناه مصمَّم
    # عمدًا بحيث لا ينجح أي طرف وحده: أدلة [سند]/[تسمية] وحدها لا تحوي
    # "مصدر صلة جديد"، والبحث الجديد وحده لا يحوي "مصدر تسمية" — فقط الدمج
    # يمرّ فحص _fake_answer_link أدناه، فنجاح الاختبار دليل مباشر على أن
    # الدمج وقع فعليًا لا أنه صودف نجاحه بأي من الطرفين بمفرده.
    def _fake_name_event_link(statement, cfg, topic=""):
        return ("نص الحدث المسمّى",
               [{"name": "مصدر تسمية", "link": "https://naming2/1",
                 "text": "نص التسمية", "from_text": True}],
               ["مصدر تسمية"],
               [{"stage": "مباشر", "query": "س", "basis": evidence.EVIDENCE_FULL_TEXT,
                 "sources": ["مصدر تسمية"], "raw_count": 1, "matched_count": 1,
                 "fetch_failures": [], "unfiltered_relevance": True, "outcome": "سُمّي"}])

    link_call_log: list = []

    def _fake_search_link(query, cfg, days, unrestricted=False):
        link_call_log.append(query)
        return [object()]

    def _fake_gather_link(articles, cfg, claim_text=""):
        if len(link_call_log) == 1:  # دورة السند الثانية (كيانات الحدث المسمّى)
            return ([{"name": "مصدر سند حصري", "link": "https://s2/1", "from_text": True,
                      "text": "نص سند"}], evidence.EVIDENCE_FULL_TEXT)
        return ([{"name": "مصدر صلة جديد", "link": "https://link2/1", "from_text": True,
                  "text": "نص جديد"}], evidence.EVIDENCE_FULL_TEXT)  # بحث سؤال الصلة

    def _fake_support_link(fact_text, docs, cfg, is_statement=False, is_report=False, publisher=""):
        return ["مصدر سند حصري", "مصدر تسمية"] if fact_text == "نص الحدث المسمّى" else []

    captured_answer_docs: list = []

    def _fake_answer_link(question_text, docs, cfg):
        names = [d["name"] for d in docs]
        captured_answer_docs.append(names)
        if "مصدر تسمية" in names and "مصدر صلة جديد" in names:
            return {"text": "إجابة سؤال الصلة", "supporting": ["مصدر تسمية", "مصدر صلة جديد"]}
        return None

    article._name_event = _fake_name_event_link
    evidence.search = _fake_search_link
    evidence.gather_evidence = _fake_gather_link
    article._support_sources = _fake_support_link
    article._ask_answer_model = _fake_answer_link
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار سؤال الصلة",
        "statements": [
            {"text": "إشارة مبهمة لاختبار سؤال الصلة", "kind": "واقعة",
             "entities": ["كيان الطرف الأول", "2 فبراير 2026"],
             "is_unnamed_event": True, "is_reference": False},
        ],
        "questions": [],
    }, None)

    try:
        out_link = article._write_article("موجز اختبار سؤال الصلة", 3733, cfg)
    finally:
        article._name_event = real_name_event

    check("سؤال الصلة: الاستعلام يُبنى من كيانات الطرفين معًا — كيان الإشارة "
          "الأصلية (وحده لا يكفي وحده بلا كيانات الحدث المسمّى)",
          len(link_call_log) >= 2 and "الطرف" in link_call_log[1], link_call_log)
    check("سؤال الصلة: الاستعلام يحمل أيضًا كلمات من نص الحدث المسمّى نفسه — لا "
          "كيانات الإشارة المبهمة الأصلية وحدها",
          any(w in link_call_log[1] for w in ("الحدث", "المسمى", "المسمّى")),
          link_call_log)
    check("سؤال الصلة: نداء الإجابة استُدعي بدمج أدلة [سند]/[تسمية] الموجودة مع "
          "بحث جديد معًا — لا أحدهما وحده (الفاك يفشل لأي منهما منفردًا)",
          any({"مصدر تسمية", "مصدر سند حصري", "مصدر صلة جديد"} <= set(names)
              for names in captured_answer_docs),
          captured_answer_docs)
    check("سؤال الصلة: أُجيب فعلًا بفضل الدمج — لا «سند غير كافٍ» رغم توفّر السند "
          "مجتمعًا من الدورتين",
          any(q["text"].startswith("ما الصلة بين") for q in out_link["answered_questions"]),
          (out_link["answered_questions"], out_link["unanswered"]))
    link_trail_entry = next(t for t in out_link["trail"]
                            if t["stage"] == "سؤال" and t["query"] == link_call_log[1])
    check("سؤال الصلة: trail يسجّل عدد الأدلة المُعاد استعمالها من الدورتين السابقتين "
          "صراحة — لا رقم صامت",
          link_trail_entry.get("reused_evidence_count") == 2, link_trail_entry)

    article._support_sources = _fake_support
    article._ask_answer_model = _fake_answer
    evidence.search = _fake_search
    evidence.gather_evidence = _fake_gather_evidence

    # ── القاعدة 5 (فحص الأصالة): نسخ لفظي من الموجز في المتن ← امتناع ──
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار فحص الأصالة",
        "statements": [
            {"text": "واقعة أولى", "kind": "واقعة", "entities": ["ك1"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": "واقعة ثانية", "kind": "واقعة", "entities": ["ك2"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    SUPPORT_MAP.clear()
    SUPPORT_MAP["واقعة أولى"] = ["مصدر أول", "مصدر ثانٍ"]
    SUPPORT_MAP["واقعة ثانية"] = ["مصدر أول", "مصدر ثانٍ"]

    copied_run = "هذه جملة طويلة منسوخة حرفيًا بالكامل من نص الموجز الأصلي للاختبار فعلًا"

    def _copying_draft(grounded, opinions, question, cfg, retries=3, avoid_note=""):
        return ({"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
                "image_headline": "عنوان", "post_title": question,
                "post_body": copied_run, "hashtags": []}, "")

    article._draft_article = _copying_draft
    brief_with_copy = f"مقدمة الموجز. {copied_run}. خاتمة الموجز."
    out5 = article._write_article(brief_with_copy, 5, cfg)
    check("5) نسخ لفظي طويل من الموجز في المتن ← امتناع بلا نشر (فحص "
          "verify_draft.check_originality المُعاد استعماله كما هو)",
          out5["produced"] is False and "امتناع" in out5["reason"], out5["reason"])
    article._draft_article = _fake_draft_article

    # ── سدّ ثغرة الدائرة: الترشيح بالسند يسبق اختيار السؤال ──
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار سدّ ثغرة الدائرة",
        "statements": [
            {"text": "واقعة ضعيفة السند بمصدر واحد", "kind": "واقعة", "entities": ["كأ"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": "واقعة قوية أولى", "kind": "واقعة", "entities": ["كب"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": "واقعة قوية ثانية", "kind": "واقعة", "entities": ["كج"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    SUPPORT_MAP.clear()
    SUPPORT_MAP["واقعة ضعيفة السند بمصدر واحد"] = ["مصدر أول"]
    SUPPORT_MAP["واقعة قوية أولى"] = ["مصدر أول", "مصدر ثانٍ"]
    SUPPORT_MAP["واقعة قوية ثانية"] = ["مصدر أول", "مصدر ثانٍ"]

    out_gap = article._write_article("موجز اختبار سدّ ثغرة الدائرة", 999, cfg)
    check("سدّ ثغرة الدائرة: واقعة بمصدر واحد لا تصل مرحلة اختيار السؤال إطلاقًا "
          "— الترشيح بالسند يسبق الاختيار، لا العكس",
          "واقعة ضعيفة السند بمصدر واحد" not in seen_question_calls[-1])
    check("سدّ ثغرة الدائرة: الوقائع المُرشَّحة بالسند فقط تصل مرحلة اختيار "
          "السؤال — لا كل ما استُخرج من الموجز",
          set(seen_question_calls[-1]) == {"واقعة قوية أولى", "واقعة قوية ثانية"})
    check("سدّ ثغرة الدائرة: بوابة الكفاية (_sufficiency) تُستدعى على "
          "المُرشَّح بالسند فقط — المحورية مضمونة بالبناء لا بالفحص",
          out_gap["produced"] is True, out_gap.get("reason"))

    # ── البند 5: أسئلة الموجز تُبحث فعليًا (لا حصيلة فشل) — إجابة مسندة تدخل
    # المقال، وسؤال بلا سند كافٍ يبقى بلا إجابة بسبب محدد ──
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار البند 5",
        "statements": [
            {"text": "واقعة إخبارية وحيدة مسندة", "kind": "واقعة", "entities": ["كخ"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [
            {"text": "من هو حمزة الخطيب؟", "entities": ["حمزة الخطيب"], "is_reference": True},
            {"text": "سؤال بلا سند كافٍ؟", "entities": ["كذا"], "is_reference": False},
        ],
    }, None)
    SUPPORT_MAP.clear()
    SUPPORT_MAP["واقعة إخبارية وحيدة مسندة"] = ["مصدر أول", "مصدر ثانٍ"]
    ANSWER_MAP.clear()
    ANSWER_MAP["من هو حمزة الخطيب؟"] = {
        "text": "رمز من انتفاضة سوريا 2011 في درعا",
        "supporting": ["مصدر أول", "مصدر ثانٍ"],
    }
    # "سؤال بلا سند كافٍ؟" غائب عمدًا عن ANSWER_MAP ← _fake_answer يعيد None

    out56 = article._write_article("موجز اختبار البند 5 و6", 56, cfg)
    check("5) سؤال الموجز يُبحث فعليًا ويُجاب من نصوص مسندة — لا حصيلة فشل بلا بحث",
          any(q["text"] == "من هو حمزة الخطيب؟" for q in out56["answered_questions"]))
    check("5) سؤال بُحث عنه فعلًا ولم يُجب يبقى في القسم بسببه المحدد لا حذفًا صامتًا",
          any(u["text"] == "سؤال بلا سند كافٍ؟" and u["reason"] for u in out56["unanswered"]))
    check("6) إجابة سؤال مرجعي مسندة تدخل عدّ الكفاية (min_grounded_facts) فعلًا "
          "— مع واقعة إخبارية غير مرجعية واحدة تكفي بوابة البند 6",
          out56["produced"] is True, out56.get("reason"))

    # ── البند 6: وقائع مسندة كلها مرجعية (خلفية) بلا خبر جديد فعلي ← لا مقال،
    # وسبب الامتناع يفرّق صراحة بين «لا وقائع كافية» و«لا خبر جديد» ──
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار البند 6 — خلفية فقط",
        "statements": [
            {"text": "واقعة ضعيفة السند لن تصمد", "kind": "واقعة", "entities": ["كض"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [
            {"text": "من هو حمزة الخطيب؟", "entities": ["حمزة الخطيب"], "is_reference": True},
            {"text": "ماذا فعلوا به؟", "entities": ["حمزة الخطيب"], "is_reference": True},
        ],
    }, None)
    SUPPORT_MAP.clear()
    SUPPORT_MAP["واقعة ضعيفة السند لن تصمد"] = ["مصدر أول"]  # مصدر واحد فقط ← تسقط
    ANSWER_MAP.clear()
    ANSWER_MAP["من هو حمزة الخطيب؟"] = {
        "text": "رمز من انتفاضة سوريا 2011 في درعا",
        "supporting": ["مصدر أول", "مصدر ثانٍ"],
    }
    ANSWER_MAP["ماذا فعلوا به؟"] = {
        "text": "تعرّض للتعذيب حتى الموت في أحداث 2011",
        "supporting": ["مصدر أول", "مصدر ثانٍ"],
    }

    out_refonly = article._write_article("موجز اختبار البند 6", 57, cfg)
    check("6) وقائع مسندة كلها مرجعية (خلفية موثَّقة سلفًا) بلا خبر جديد فعلي "
          "← لا مقال رغم اجتياز العدّ الرقمي وحده",
          out_refonly["produced"] is False and "لا خبر جديد" in out_refonly["reason"],
          out_refonly.get("reason"))

    # ── البند 3 (تعليق التنفيذ على Issue #364): تفريق «لم يسمِّ النموذج
    # مصدرًا» عن «سمّى مصدرًا لم يُطابَق» عند answered:true مع supporting
    # فارغة بعد evidence._known_only — التشغيل الحقيقي لم يحسم أيهما وقع
    # فعليًا في حالة «من هو حمزة الخطيب؟»، فـ_ask_answer_model يسجّل الفارق
    # صراحة الآن بدل ابتلاعهما في نفس النتيجة "0 من 2" المجردة ──
    class _AnswerBlock:
        def __init__(self, input_):
            self.type = "tool_use"
            self.input = input_

    class _AnswerResp:
        def __init__(self, input_):
            self.content = [_AnswerBlock(input_)]
            self.stop_reason = "end_turn"

    class _AnswerMessages:
        def __init__(self, input_):
            self._input = input_

        def create(self, **kw):
            return _AnswerResp(self._input)

    class _AnswerClient:
        def __init__(self, input_):
            self.messages = _AnswerMessages(input_)

    real_client_fn = article._client
    docs_for_answer = [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"}]

    article._client = lambda: _AnswerClient(
        {"answered": True, "text": "إجابة فعلية", "supporting": []})
    no_name = real_ask_answer_model("سؤال اختبار البند 3؟", docs_for_answer, cfg)
    check("3) answered:true بلا أي اسم مصدر مذكور ← naming_issue = لم يُسمَّ مصدر",
          no_name is not None and no_name["naming_issue"] == "no_source_named")

    article._client = lambda: _AnswerClient(
        {"answered": True, "text": "إجابة فعلية", "supporting": ["مصدر مختلَق لا وجود له"]})
    unmatched = real_ask_answer_model("سؤال اختبار البند 3؟", docs_for_answer, cfg)
    check("3) answered:true بمصدر مسمّى لا يطابق أي doc معطى ← naming_issue = مصدر لم "
          "يُطابَق لا مصدر لم يُسمَّ",
          unmatched is not None and unmatched["naming_issue"] == "unmatched_source")

    article._client = lambda: _AnswerClient(
        {"answered": True, "text": "إجابة فعلية", "supporting": ["مصدر أول"]})
    matched = real_ask_answer_model("سؤال اختبار البند 3؟", docs_for_answer, cfg)
    check("3) answered:true بمصدر مطابق فعليًا ← بلا عطل تسمية (naming_issue = None)",
          matched is not None and matched["naming_issue"] is None and
          matched["supporting"] == ["مصدر أول"])

    # temperature غير مقبولة من نماذج هذا المشروع (Error code: 400 —
    # "temperature is deprecated for this model", تشخيص Issue #373، الجولة
    # الحادية عشرة): جُرِّبت في الجولة العاشرة على الأحكام الثنائية الثلاثة
    # في article.py وكسرت النداء صامتًا (رفض API التقط ضمن except فأعاد
    # نفس شكل "لا نتيجة" الشرعي). لا يجوز أن تعود.
    class _CaptureMessages:
        def __init__(self, input_, captured):
            self._input = input_
            self._captured = captured

        def create(self, **kw):
            self._captured.append(kw)
            return _AnswerResp(self._input)

    class _CaptureClient:
        def __init__(self, input_, captured):
            self.messages = _CaptureMessages(input_, captured)

    temp_calls: list = []
    article._client = lambda: _CaptureClient({"named": False}, temp_calls)
    real_ask_naming_model("نص مبهم", ["ك"], docs_for_answer, cfg)
    article._client = lambda: _CaptureClient({"supporting": []}, temp_calls)
    real_support_sources("واقعة اختبار", docs_for_answer, cfg)
    article._client = lambda: _CaptureClient(
        {"answered": False, "supporting": []}, temp_calls)
    real_ask_answer_model("سؤال اختبار temperature؟", docs_for_answer, cfg)
    check("3) لا temperature في نداءات _ask_naming_model/_support_sources/"
          "_ask_answer_model الثلاثة (400 من الخادم لو مُرِّرت)",
          len(temp_calls) == 3 and all("temperature" not in c for c in temp_calls),
          temp_calls)

    article._client = real_client_fn

    # ── فشل نداء تقني يظهر صراحة لا بصمت (تشخيص Issue #373، الجولة الحادية
    # عشرة، البند 2): فشل نداء (رفض API/انقطاع شبكة) كان يعيد
    # None/[] بالضبط كما يعيدها حكم "لا" شرعي من النموذج، فيظهر في trail
    # والتقرير بنفس عبارة "لم توجد نصوص تجيب عنه" — لا فرق قابل للتشخيص.
    # الآن الفشل التقني يعيد _ModelCallResult/_ModelCallList فارغة (تبقى
    # falsy، فلا تكسر أي فحص `if not result` قائم) لكن تحمل call_error ──
    from anthropic import APIConnectionError
    import httpx as _httpx

    class _RaisingMessages:
        def create(self, **kw):
            raise APIConnectionError(
                message="انقطاع شبكة اختباري",
                request=_httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    class _RaisingClient:
        def __init__(self):
            self.messages = _RaisingMessages()

    article._client = lambda: _RaisingClient()

    fail_naming = real_ask_naming_model("نص مبهم", ["ك"], docs_for_answer, cfg)
    check("فشل نداء _ask_naming_model التقني يبقى falsy كحكم (if not result)",
          not fail_naming, fail_naming)
    check("فشل نداء _ask_naming_model التقني يحمل call_error بنص الاستثناء",
          "انقطاع شبكة اختباري" in (getattr(fail_naming, "call_error", "") or ""),
          getattr(fail_naming, "call_error", None))

    fail_support = real_support_sources("واقعة اختبار", docs_for_answer, cfg)
    check("فشل نداء _support_sources التقني يبقى falsy كحكم (if not result)",
          not fail_support, fail_support)
    check("فشل نداء _support_sources التقني يحمل call_error بنص الاستثناء",
          "انقطاع شبكة اختباري" in (getattr(fail_support, "call_error", "") or ""),
          getattr(fail_support, "call_error", None))

    fail_answer = real_ask_answer_model("سؤال اختبار فشل تقني؟", docs_for_answer, cfg)
    check("فشل نداء _ask_answer_model التقني يبقى falsy كحكم (if not result)",
          not fail_answer, fail_answer)
    check("فشل نداء _ask_answer_model التقني يحمل call_error بنص الاستثناء",
          "انقطاع شبكة اختباري" in (getattr(fail_answer, "call_error", "") or ""),
          getattr(fail_answer, "call_error", None))

    # نداء فاشل بدالة مزيَّفة قديمة الطراز (تعيد None/[] عاديين بلا call_error،
    # كما تفعل fakes الاختبارات الأخرى القائمة) يبقى يعمل بلا انهيار —
    # getattr(..., "call_error", None) على None/[] عادية تعيد None بأمان
    check("getattr(None, call_error) على قيمة فشل تقليدية يعيد None بأمان",
          getattr(None, "call_error", None) is None)
    check("getattr([], call_error) على قيمة فشل تقليدية يعيد None بأمان",
          getattr([], "call_error", None) is None)

    article._client = real_client_fn

    # الفشل التقني ينعكس في trail عبر _name_event._try — لا في outcome حكم
    # "لم يُسمَّ من هذه النتائج" الملتبس بالحكم الشرعي. entities بتاريخ واحد
    # وكيان واحد فقط تجعل مرحلة «مباشر» محاولة وحيدة سهلة التتبع (مرحلتا
    # «سياق»/«موضوع» تُختبران بمعزل أعلاه — ليستا من الأربعة نداءات المعنيَّة)
    evidence.search = lambda query, cfg, days, **kw: [object()]
    evidence.gather_evidence = lambda articles, cfg, claim_text="", **kw: (
        [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"}], evidence.EVIDENCE_FULL_TEXT)
    article._client = lambda: _RaisingClient()
    _, _, _, fail_trail = article._name_event(
        {"text": "إشارة مبهمة", "entities": ["كيان", "2020"]}, cfg)
    article._client = real_client_fn
    evidence.search = _fake_search
    evidence.gather_evidence = _fake_gather_evidence
    direct_trail = [e for e in fail_trail if e["stage"] == "مباشر"]
    check("trail: فشل نداء تسمية تقني يظهر صراحة في outcome مرحلة «مباشر»",
          bool(direct_trail) and all("فشل نداء النموذج تقنيًا" in e["outcome"]
                                     for e in direct_trail),
          [e.get("outcome") for e in direct_trail])
    check("trail: عنصر مرحلة «مباشر» يحمل call_error منفصلًا لا outcome نصيًا وحده",
          bool(direct_trail) and all(e.get("call_error") for e in direct_trail),
          [e.get("call_error") for e in direct_trail])

    # التفريق يصل تقرير الـ Issue فعليًا لا الحقل الداخلي وحده
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار البند 3 — التقرير",
        "statements": [
            {"text": "واقعة إخبارية مسندة للبند 3", "kind": "واقعة", "entities": ["كظ"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [
            {"text": "سؤال بعطل تسمية مصدر؟", "entities": ["كغ"], "is_reference": False},
        ],
    }, None)
    SUPPORT_MAP.clear()
    SUPPORT_MAP["واقعة إخبارية مسندة للبند 3"] = ["مصدر أول", "مصدر ثانٍ"]
    ANSWER_MAP.clear()
    ANSWER_MAP["سؤال بعطل تسمية مصدر؟"] = {
        "text": "إجابة فعلية لكن بلا سند مطابق", "supporting": [],
        "naming_issue": "no_source_named",
    }
    out3 = article._write_article("موجز اختبار البند 3 — التقرير", 3648, cfg)
    reason3 = next((u["reason"] for u in out3["unanswered"]
                   if u["text"] == "سؤال بعطل تسمية مصدر؟"), "")
    check("3) سبب عدم الإجابة في outcome يفرّق «لم يسمِّ النموذج مصدرًا» صراحة "
          "لا «سند غير كافٍ» مجردة",
          "لم يسمِّ" in reason3, reason3)
    report3 = article.build_report(out3)
    check("3) التفريق يظهر في تقرير الـ Issue الفعلي (build_report) لا outcome الداخلي وحده",
          "لم يسمِّ" in report3)

    # ── البند 4 (تعليق التنفيذ على Issue #364): أمثلة مضادة في برومبت
    # استخراج بنية الموجز — سرد انتقالي عام يُستبعد كليًا لا يُصنَّف، وحدث
    # مرجعي مسمّى بفاعل وفعل واضحين رغم قلة التفاصيل لا يُعامَل كإشارة مبهمة ──
    check("4) برومبت استخراج بنية الموجز يستبعد السرد الانتقالي العام من "
          "statements إطلاقًا — لا يُصنَّف واقعة ولا رأيًا",
          "لا تُدرَج ضمن statements إطلاقًا" in article.WRITEUP_EXTRACT_SYSTEM)
    check("4) برومبت استخراج بنية الموجز يميّز حدثًا مرجعيًا مسمّى بفاعل وفعل "
          "واضحين رغم قلة التفاصيل عن إشارة مبهمة",
          "تسمّي الحدث أيضًا رغم قلة التفاصيل" in article.WRITEUP_EXTRACT_SYSTEM)

    # ── طلب التنفيذ على Issue #373، الجولة الرابعة، البند 3: خط أساس ثابت —
    # سطر مُلحَق بملف بالمستودع بعد كل تشغيلة، لا مناقشة تفسيرات بلا دليل ──
    check("article._trail_read_counts: ملخص «مرحلة×عدد مصادر» لكل عنصر trail",
          article._trail_read_counts([
              {"stage": "مباشر", "sources": ["أ", "ب"]},
              {"stage": "سؤال", "sources": []},
          ]) == "مباشر×2، سؤال×0")
    check("article._trail_read_counts: trail فارغة لا تنهار",
          article._trail_read_counts([]) == "بلا استعلامات")

    # ── تشخيص Issue #373، الجولة الثامنة، البند 3: تذبذب حكم النموذج بين
    # نداءين شبه متطابقين على نفس السؤال — يُرصَد لا يُعالَج، عبر عمود جديد
    # في خط الأساس يعرض حكم كل سؤال بعينه لا العدد الكلي وحده ──
    check("article._question_outcomes: يعرض ✅ للأسئلة المُجابة و❌ لغير المُجابة",
          article._question_outcomes({
              "answered_questions": [{"text": "من هو حمزة الخطيب؟", "answer": "..."}],
              "unanswered": [{"text": "كيف بدأت القصة؟", "reason": "..."}],
          }) == "✅ من هو حمزة الخطيب؟؛ ❌ كيف بدأت القصة؟")
    check("article._question_outcomes: بلا أسئلة لا تنهار",
          article._question_outcomes({}) == "بلا أسئلة")

    baseline_path = article.STATE_DIR / "article_baseline_test.md"
    if baseline_path.exists():
        baseline_path.unlink()
    try:
        outcome_ok = {"produced": True, "reason": "صيغ مقال من 2 واقعة مسندة",
                     "grounded_count": 2,
                     "trail": [{"stage": "مباشر", "sources": ["أ", "ب"]}],
                     "answered_questions": [{"text": "من هو حمزة الخطيب؟", "answer": "..."}],
                     "unanswered": [{"text": "كيف بدأت القصة؟", "reason": "..."}]}
        row1 = article.record_baseline(outcome_ok, path=baseline_path)
        check("article.record_baseline: يُلحِق سطر جدول يحوي النتيجة وعدد الوقائع المسندة",
              row1.startswith("|") and "✅" in row1 and "| 2 |" in row1 and
              "مباشر×2" in row1, row1)
        check("article.record_baseline: السطر يحوي حكم كل سؤال بعينه (الجولة الثامنة، البند 3)",
              "✅ من هو حمزة الخطيب؟" in row1 and "❌ كيف بدأت القصة؟" in row1, row1)
        check("article.record_baseline: أول استدعاء يكتب ترويسة الملف (عنوان + جدول)",
              baseline_path.read_text(encoding="utf-8").startswith("# خط أساس ثابت"))
        check("article.record_baseline: الترويسة تحوي عمود «أسئلة الموجز» الجديد",
              "أسئلة الموجز" in baseline_path.read_text(encoding="utf-8"))
        header_len = len(baseline_path.read_text(encoding="utf-8"))

        outcome_fail = {"produced": False, "reason": "بُحث ولم توجد نصوص تجيب عنه بوضوح",
                        "grounded_count": 0, "trail": []}
        row2 = article.record_baseline(outcome_fail, path=baseline_path)
        check("article.record_baseline: الاستدعاء الثاني يُلحِق سطرًا جديدًا بلا إعادة كتابة "
              "الترويسة (سجل تراكمي)",
              "❌" in row2 and "| 0 |" in row2 and
              len(baseline_path.read_text(encoding="utf-8")) > header_len)
        check("article.record_baseline: الملف يحوي السطرين معًا بعد استدعاءين",
              baseline_path.read_text(encoding="utf-8").count("\n|") >= 2)
    finally:
        if baseline_path.exists():
            baseline_path.unlink()

    check("article.BASELINE_LOG_PATH: تحت state/ — تلتزم بها article.yml تلقائيًا "
          "(git add -A drafts state) بلا تعديل سير العمل",
          article.BASELINE_LOG_PATH.parent == article.STATE_DIR)
    check("config.yaml: article.baseline_issue_number موجود كمفتاح تهيئة — رقم "
          "Issue فقط لا نسخة من نص الموجز نفسه (تشخيص Issue #373، الجولة "
          "الخامسة، البند 3: يُقرأ الموجز حيًّا من الـ Issue في main()، لا "
          "من config.yaml)",
          "baseline_issue_number" in (cfg.get("article") or {}))

    article.extract_brief = real_extract_brief
    evidence.search = real_search
    evidence.gather_evidence = real_gather_evidence
    article._support_sources = real_support_sources
    article._ask_naming_model = real_ask_naming_model
    article._ask_context_model = real_ask_context_model
    article._ask_answer_model = real_ask_answer_model
    article._choose_question = real_choose_question
    article._draft_article = real_draft_article
    article._call_draft_model = real_call_draft_model
    article.find_images = real_find_images


def test_article_statement_kind() -> None:
    """تصنيف «تصريح» (تشخيص Issue #373، الجولة الثالثة عشرة، البند 1): نقل
    تصريح لمتحدث واحد في مناسبة واحدة يُستخرج كعنصر واحد بمكوّناته مجتمعة —
    لا يُفكَّك إلى عدة "واقعة" منفصلة يتنافس كل منها وحده على عتبة السند —
    وسنده يُفحَص بمعيار مضمون أدق (STATEMENT_SUPPORT_SYSTEM) لا وقوع مقابلة
    وحدها، بلا أي تخفيف في عتبة min_confirm_sources نفسها. خطر الدمج الزائف
    يُعالَج بالإظهار (merged_statements في التقرير) لا بالمنع."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False

    check("WRITEUP_KINDS يضم «تصريح» تصنيفًا ثالثًا بجانب واقعة/رأي",
          "تصريح" in article.WRITEUP_KINDS)

    # ── normalize_statement: يلتقط speaker/merged_excerpts لعنصر تصريح ──
    stmt = article.normalize_statement({
        "text": "نفى المتحدث الادّعاء وأكّد أنه يدرس الأمر تدريجيًا",
        "kind": "تصريح", "entities": ["المتحدث"], "is_unnamed_event": False,
        "is_reference": False, "speaker": "المتحدث الاختباري",
        "merged_excerpts": ["نفى المتحدث الادّعاء", "قال إنه يدرس الأمر تدريجيًا"],
    })
    check("normalize_statement: يحفظ speaker لعنصر تصريح",
          stmt["speaker"] == "المتحدث الاختباري", stmt)
    check("normalize_statement: يحفظ merged_excerpts حرفيًا كما وردت",
          stmt["merged_excerpts"] == ["نفى المتحدث الادّعاء", "قال إنه يدرس الأمر تدريجيًا"],
          stmt)

    fact = article.normalize_statement({
        "text": "واقعة عادية", "kind": "واقعة", "entities": ["ك"],
        "is_unnamed_event": False, "is_reference": False,
    })
    check("normalize_statement: عنصر واقعة عادي بلا speaker/merged_excerpts يبقى "
          "آمنًا (فارغَين لا كسر)",
          fact["speaker"] == "" and fact["merged_excerpts"] == [], fact)

    # ── _support_sources(is_statement=True) يستعمل STATEMENT_SUPPORT_SYSTEM لا
    # SUPPORT_SYSTEM — بلا تخفيف العتبة، فقط معيار تأييد أدق (مضمون لا مقابلة) ──
    real_client_fn = article._client
    captured: list = []

    class _CaptureBlock:
        type = "text"

    class _CaptureResp:
        content = [_CaptureBlock()]
        stop_reason = "end_turn"

    class _CaptureMessages:
        def create(self, **kw):
            captured.append(kw)
            return _CaptureResp()

    class _CaptureClient:
        def __init__(self):
            self.messages = _CaptureMessages()

    article._client = lambda: _CaptureClient()
    docs = [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"}]
    article._support_sources("واقعة عادية", docs, cfg, is_statement=False)
    article._support_sources("تصريح اختباري", docs, cfg, is_statement=True)
    article._client = real_client_fn

    check("_support_sources(is_statement=False) يستعمل SUPPORT_SYSTEM (سلوك افتراضي بلا تغيير)",
          captured[0]["system"] == article.SUPPORT_SYSTEM)
    check("_support_sources(is_statement=True) يستعمل STATEMENT_SUPPORT_SYSTEM لا SUPPORT_SYSTEM",
          captured[1]["system"] == article.STATEMENT_SUPPORT_SYSTEM and
          captured[1]["system"] != article.SUPPORT_SYSTEM)
    check("STATEMENT_SUPPORT_SYSTEM يشترط مضمون التصريح لا وقوع المقابلة وحدها",
          "مضمون" in article.STATEMENT_SUPPORT_SYSTEM and "مقابلة" in article.STATEMENT_SUPPORT_SYSTEM)

    # ── تكامل كامل عبر _write_article: تصريح يُدمَج كعنصر واحد، يُبلَّغ عنه في
    # التقرير، وسنده يُفحَص جزءًا جزءًا عبر _support_statement_parts (معيار
    # الأغلبية، طلب المراجعة) لا حكمًا شموليًا واحدًا — انظر
    # test_article_statement_majority للتغطية التفصيلية للمعيار نفسه ──
    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_support_parts = article._support_statement_parts

    statement_text = "المتحدث ينفي الادّعاء ويؤكد أنه يدرس الأمر تدريجيًا"
    merged_excerpts = ["نفى المتحدث الادّعاء صراحة", "قال إنه يدرس الأمر تدريجيًا"]
    speaker_name = "المتحدث الاختباري"

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار تصنيف تصريح",
        "statements": [
            {"text": statement_text, "kind": "تصريح", "entities": ["المتحدث"],
             "is_unnamed_event": False, "is_reference": False,
             "speaker": speaker_name, "merged_excerpts": merged_excerpts},
            {"text": "واقعة عادية أخرى في نفس الموجز", "kind": "واقعة",
             "entities": ["ك2"], "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1", "from_text": True},
         {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1", "from_text": True}],
        evidence.EVIDENCE_FULL_TEXT)

    part_calls: list = []
    plain_calls: list = []

    def _fake_support_parts(merged, docs, cfg):
        part_calls.append(list(merged))
        # كلا الجزأين مؤيَّدان بكلا المصدرين — يجتاز كل مصدر عتبة الأغلبية
        # (2 من 2) فيُحسبان مصدرين مستقلين، وكلا الجزأين يدخل نص الصياغة
        return [["مصدر أول", "مصدر ثانٍ"] for _ in merged]

    def _fake_support_plain(fact_text, docs, cfg, is_statement=False, is_report=False,
                            publisher=""):
        plain_calls.append(fact_text)
        # الواقعة العادية تسقط عمدًا (لا سند) — كافٍ لإسقاط outcome["produced"]
        # قبل مرحلتَي السؤال/الصياغة فلا حاجة لمحاكاتهما في هذا الاختبار
        return []

    article._support_statement_parts = _fake_support_parts
    article._support_sources = _fake_support_plain

    out = article._write_article("موجز اختبار تصنيف تصريح", 9001, cfg)

    check("تصريح: التصريح يُحكَم عليه عبر _support_statement_parts جزءًا جزءًا "
          "لا يُهمَل كرأي",
          any(set(c) == set(merged_excerpts) for c in part_calls), part_calls)
    check("تصريح: _support_sources الشمولي القديم لا يُستدعى إطلاقًا للتصريح "
          "— معيار الأغلبية استبدله كليًا لمسار is_statement=True",
          statement_text not in plain_calls, plain_calls)
    check("تصريح: الواقعة العادية المجاورة تبقى تُحكَم عبر _support_sources "
          "الشمولي — لا تسرّب معيار الأغلبية خارج نطاق التصريح",
          "واقعة عادية أخرى في نفس الموجز" in plain_calls, plain_calls)
    check("تصريح: التصريح المسنَد لا يظهر ضمن dropped (لم يُرفض)",
          not any(d["text"] == statement_text for d in out["dropped"]), out["dropped"])
    check("تصريح: grounded_count == 1 — التصريح وحده اجتاز السند (الواقعة "
          "المجاورة سقطت عمدًا في هذا الاختبار)",
          out["grounded_count"] == 1, out["grounded_count"])
    check("تصريح: الواقعة العادية المجاورة سقطت (سند غير كافٍ) — لم تُدمَج زورًا "
          "مع التصريح رغم مجاورتها في نفس الموجز",
          any(d["text"] == "واقعة عادية أخرى في نفس الموجز" for d in out["dropped"]),
          out["dropped"])

    check("تصريح: outcome['merged_statements'] يذكر المتحدث بصرف النظر عن نجاح "
          "الإنتاج الكلي لاحقًا — تبليغ لا مشروط بالنجاح",
          any(m["speaker"] == speaker_name and m["text"] == statement_text
              for m in out["merged_statements"]), out["merged_statements"])
    check("تصريح: outcome['merged_statements'] يحمل جمل الموجز الحرفية المُدمَجة كاملة",
          any(m["merged_excerpts"] == merged_excerpts for m in out["merged_statements"]),
          out["merged_statements"])
    check("تصريح: outcome['merged_statements'][0]['part_support'] يسرد كل جزء "
          "بمصادره المؤيِّدة فعليًا (طلب المراجعة، معيار الأغلبية)",
          any(m["speaker"] == speaker_name and
              [p["excerpt"] for p in m["part_support"]] == merged_excerpts and
              all(p["supporting"] == ["مصدر أول", "مصدر ثانٍ"] for p in m["part_support"])
              for m in out["merged_statements"]), out["merged_statements"])

    report = article.build_report(out)
    check("تصريح: التقرير يعرض قسم «تصريحات دُمجت من عدة جمل» صراحة",
          "تصريحات دُمجت من عدة جمل" in report, report)
    check("تصريح: التقرير يذكر اسم المتحدث والجمل المُدمَجة معًا — لا إعفاء صامت",
          speaker_name in report and all(ex in report for ex in merged_excerpts),
          report)
    check("تصريح: التقرير يعرض كل جزء بمصادره المؤيِّدة (سطر '• «جزء» — مصدر')",
          all(f"«{ex}» — مصدر أول؛ مصدر ثانٍ" in report for ex in merged_excerpts),
          report)
    check("تصريح: نص الدمج هنا يغطي كلا الجملتين فعليًا — لا فجوة دمج مُبلَّغة "
          "(تفريقًا عن شاهد الانكماش في test_article_merged_statement_gaps)",
          "فجوة دمج" not in report, report)
    check("تصريح: trail يسجّل مرحلة «تصريح» (لا «واقعة») للعنصر المصنَّف تصريحًا",
          any(t["stage"] == "تصريح" and t["query"] for t in out["trail"]), out["trail"])

    article.extract_brief = real_extract_brief
    evidence.search = real_search
    evidence.gather_evidence = real_gather_evidence
    article._support_sources = real_support_sources
    article._support_statement_parts = real_support_parts


def test_article_merged_statement_gaps() -> None:
    """فجوة دمج التصريح (تشخيص Issue #373، تعليق العطل الرابع والعشرون،
    شاهد بايكرآر التركي): تصريح دُمج من أربع جمل، لكن نص الواقعة المدموج
    انكمش إلى الجملة الأولى وحدها — الرقم 90% ووصف الشركة سقطا من النص رغم
    ظهورهما في merged_excerpts. فحص بنيوي لاحق (بلا حكم لغوي): أي جملة
    مصدر لا أثر لها في النص المدموج تُبلَّغ، لا تُسقَط صامتة."""
    from src import article

    # ── وحدة _merged_statement_gaps ──
    covered_text = "المتحدث ينفي الادّعاء ويؤكد أنه يدرس الأمر تدريجيًا"
    check("لا فجوة حين تتقاطع كل جملة مصدر مع النص المدموج لفظيًا",
          article._merged_statement_gaps(
              covered_text,
              ["نفى المتحدث الادّعاء صراحة", "قال إنه يدرس الأمر تدريجيًا"],
          ) == [])

    shrunk_text = "قال بايكار إنه حدّد استراتيجيته"
    excerpts = [
        "قال بايكار إنه حدّد استراتيجيته",
        "أضاف أن الشركة تصنّع 90% من طائراتها محليًا",
        "وصف بايكار بأنها رائدة عالميًا في المسيّرات",
        "أكّد استمرار الاستثمار في تركيا",
    ]
    gaps = article._merged_statement_gaps(shrunk_text, excerpts)
    check("فجوة دمج: الجملة الأولى (المصدر الفعلي للنص المدموج) لا تُبلَّغ",
          excerpts[0] not in gaps, gaps)
    check("فجوة دمج: الجملة الثانية (رقم 90% غائب عن النص المدموج) تُبلَّغ",
          excerpts[1] in gaps, gaps)
    check("فجوة دمج: الجملة الثالثة (بلا تقاطع لفظي مع النص المدموج) تُبلَّغ",
          excerpts[2] in gaps, gaps)
    check("فجوة دمج: الجملة الرابعة (بلا تقاطع لفظي مع النص المدموج) تُبلَّغ",
          excerpts[3] in gaps, gaps)

    # ── لا فجوات كاذبة عبر اللغات: جملة مصدر أجنبية (سكريبت لاتيني) مقابل
    # نص عربي مُترجَم لن تشترك ألفاظًا حرفيًا حتى لو نُقل مضمونها كاملًا —
    # مقارنة الكلمات عبر لغتين مختلفتين مضلِّلة فتُسقَط، والرقم (يعبر
    # الترجمة سليمًا) هو الإشارة المعتمدة عبر اللغات ──
    turkish_excerpt_covered = "Baykar'ın SİHA üretiminde yüzde 90'ını yerlileştirdik"
    arabic_text_with_number = "أكّد بايكار أن الشركة تصنّع 90% من مسيّراتها محليًا"
    check("لا فجوة كاذبة: جملة مصدر تركية بلا تقاطع لفظي مع نص عربي مُترجَم، "
          "لكن الرقم المشترك (90) يثبت أن مضمونها انتقل فعليًا",
          article._merged_statement_gaps(
              arabic_text_with_number, [turkish_excerpt_covered]) == [])

    # نظير الشاهد الفعلي بدقة: جملة مصدر تركية تحمل رقمًا (90) غائبًا عن
    # النص العربي المدموج — الأرقام تعبر الترجمة سليمة بصرف النظر عن
    # السكريبت، فهي الإشارة الوحيدة الموثوقة عبر اللغات (تُفحص أولًا، قبل
    # تجاوز فحص الكلمات لاختلاف السكريبت)
    turkish_excerpt_number_gap = "Baykar SİHA üretiminde yüzde 90'ını yerlileştirdi"
    arabic_text_no_number = "قال بايكار إنه حدّد استراتيجية الشركة"
    check("فجوة دمج عبر اللغات: رقم (90) في جملة مصدر تركية غائب عن النص "
          "العربي المدموج — يُبلَّغ رغم اختلاف السكريبت، لأن فحص الأرقام "
          "يسبق تجاوز فحص الكلمات المقيَّد بتطابق الأبجدية",
          turkish_excerpt_number_gap in article._merged_statement_gaps(
              arabic_text_no_number, [turkish_excerpt_number_gap]))

    # جملة تركية بلا رقم وبلا أي كلمة مشتركة — القيد المعروف المسجَّل في
    # CLAUDE.md (تفاوت الترجمة الصوتية للأسماء الأجنبية) يمتد إلى هذا
    # الفحص بالمثل: لا إشارة بنيوية موثوقة تكشف فجوة مضمون هنا بلا حكم
    # لغوي أو مخاطرة فجوات كاذبة، فتمر بلا بلاغ — توثيق للحد لا كسر
    turkish_excerpt_no_signal = "Türkiye'de savunma sanayii dünya lideri konumunda"
    check("قيد معروف: جملة تركية بلا رقم وبلا كلمات مشتركة تمر بلا بلاغ — "
          "فحص الكلمات مقيَّد بتطابق السكريبت لتفادي فجوات كاذبة، فلا إشارة "
          "متبقية تكشفها هنا (توثيق للحد، لا خطأ في التنفيذ)",
          article._merged_statement_gaps(
              arabic_text_with_number, [turkish_excerpt_no_signal]) == [])

    check("جملة فارغة/بيضاء ضمن merged_excerpts لا تُبلَّغ ولا تُكسر الفحص",
          article._merged_statement_gaps(shrunk_text, ["", "   "]) == [])

    # ── تكامل: outcome['merged_statements'] يحمل gaps، والتقرير يعرضها ──
    # gaps تُحسب من f["text"]/merged_excerpts مباشرة عند الاستخراج (قبل أي
    # بحث/حكم سند)، فتظهر بصرف النظر عن آلية الحكم على السند المستعملة —
    # هذا الاختبار يُحاكي _support_statement_parts (معيار الأغلبية) لا
    # _support_sources الشمولي القديم، تناظرًا مع مسار الأنبوب الفعلي
    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_parts = article._support_statement_parts

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False
    speaker_name = "بايكار الاختباري"

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار فجوة دمج التصريح",
        "statements": [
            {"text": shrunk_text, "kind": "تصريح", "entities": ["بايكار"],
             "is_unnamed_event": False, "is_reference": False,
             "speaker": speaker_name, "merged_excerpts": excerpts},
        ],
        "questions": [],
    }, None)
    evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1", "from_text": True},
         {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1", "from_text": True}],
        evidence.EVIDENCE_FULL_TEXT)
    article._support_statement_parts = lambda merged, docs, cfg: (
        [["مصدر أول", "مصدر ثانٍ"] for _ in merged])

    out = article._write_article("موجز اختبار فجوة دمج التصريح", 9002, cfg)

    check("تكامل: outcome['merged_statements'] يحمل gaps للجمل الثلاث الغائبة",
          len(out["merged_statements"]) == 1 and
          set(out["merged_statements"][0]["gaps"]) == set(excerpts[1:]),
          out["merged_statements"])

    report = article.build_report(out)
    check("تكامل: التقرير يعرض تحذير فجوة الدمج صراحة",
          "⚠️ فجوة دمج" in report, report)
    check("تكامل: التقرير يذكر الجمل الثلاث الغائبة تحديدًا داخل التحذير",
          all(ex in report for ex in excerpts[1:]), report)

    article.extract_brief = real_extract_brief
    evidence.search = real_search
    evidence.gather_evidence = real_gather_evidence
    article._support_statement_parts = real_support_parts


def test_article_statement_majority() -> None:
    """معيار الأغلبية لسند "تصريح" مُدمَج (طلب المراجعة، تعليق العطل الرابع
    والعشرون، تشخيص Issue #373): STATEMENT_SUPPORT_SYSTEM القديم يحكم على
    التصريح **ككل** — شاهد فعلي (خمس دعاوى مُدمَجة، مصدران يغطيان الموضوع
    فعليًا): الحكم رجع "ذكره 2 مصدر لكن لم يطابق مضمونه أيٌّ منها"، لأن كل
    مصدر أيّد جزءًا مختلفًا من الخمسة لا التصريح بأكمله، فرفضه الحكم
    الشمولي كليًا. العلاج: حكم جزءًا جزءًا (_support_statement_parts) ثم
    حساب عددي في الكود (_statement_majority، لا تصنيف "جوهري/هامشي" من
    النموذج) — مصدر يُسنِد التصريح ككل إن أيّد N//2+1 من N جزءًا. ما لم
    يُؤيَّد من أي مصدر لا يدخل المتن، حتى لو اجتاز التصريح ككل بأغلبية."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False

    # ── وحدة _statement_majority: خمسة أجزاء، مصدران يغطيان أغلبية مختلفة ──
    parts = ["الجزء الأول", "الجزء الثاني", "الجزء الثالث", "الجزء الرابع",
            "الجزء الخامس"]
    parts_support = [
        ["مصدر أ", "مصدر ب"],  # الجزء الأول
        ["مصدر أ", "مصدر ب"],  # الجزء الثاني
        ["مصدر أ"],             # الجزء الثالث — أيّده مصدر أ وحده
        ["مصدر ب"],             # الجزء الرابع — أيّده مصدر ب وحده
        [],                     # الجزء الخامس — بلا مؤيِّد إطلاقًا
    ]
    supporting, mentioned, included = article._statement_majority(parts, parts_support)
    check("معيار الأغلبية: مصدر أيّد 3 من 5 أجزاء (>= 5//2+1=3) يُحسب مؤيدًا "
          "للتصريح ككل رغم عدم اتفاقه مع الآخر على كل الأجزاء",
          {"مصدر أ", "مصدر ب"} <= supporting, supporting)
    check("معيار الأغلبية: كلا المصدرين يظهران في mentioned",
          mentioned == {"مصدر أ", "مصدر ب"}, mentioned)
    check("معيار الأغلبية: الجزء الخامس بلا مؤيِّد لا يدخل included — لن يدخل "
          "المتن حتى لو اجتاز التصريح ككل بأغلبية أجزاء أخرى (القيد الأهم)",
          parts[4] not in included, included)
    check("معيار الأغلبية: الأجزاء الأربعة الأولى مؤيَّدة بمصدر واحد فأكثر فتدخل included",
          included == parts[:4], included)

    below_majority = [["مصدر ج"], ["مصدر ج"], [], [], []]
    supporting2, mentioned2, _ = article._statement_majority(parts, below_majority)
    check("معيار الأغلبية: مصدر أيّد جزءين فقط من خمسة (دون عتبة 3) لا يُحسب "
          "مؤيدًا للتصريح ككل — لا تصنيف «جوهري/هامشي»، حساب عددي صرف",
          "مصدر ج" not in supporting2, supporting2)
    check("معيار الأغلبية: لكنه يبقى مذكورًا في mentioned رغم عدم بلوغ الأغلبية",
          "مصدر ج" in mentioned2, mentioned2)
    check("معيار الأغلبية: قائمة أجزاء فارغة لا تكسر الحساب",
          article._statement_majority([], []) == (set(), set(), []))

    # ── _support_statement_parts: يرقّم الأجزاء ويستعمل
    # STATEMENT_PART_SUPPORT_SYSTEM لا STATEMENT_SUPPORT_SYSTEM الشمولي ──
    real_client_fn = article._client
    captured: list = []

    class _CaptureBlock:
        type = "text"

    class _CaptureResp:
        content = [_CaptureBlock()]
        stop_reason = "end_turn"

    class _CaptureMessages:
        def create(self, **kw):
            captured.append(kw)
            return _CaptureResp()

    class _CaptureClient:
        def __init__(self):
            self.messages = _CaptureMessages()

    article._client = lambda: _CaptureClient()
    docs = [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"}]
    article._support_statement_parts(["جزء أول", "جزء ثانٍ"], docs, cfg)
    article._client = real_client_fn

    check("_support_statement_parts: يستعمل STATEMENT_PART_SUPPORT_SYSTEM لا "
          "STATEMENT_SUPPORT_SYSTEM الشمولي",
          captured[0]["system"] == article.STATEMENT_PART_SUPPORT_SYSTEM and
          captured[0]["system"] != article.STATEMENT_SUPPORT_SYSTEM)
    check("_support_statement_parts: يستدعي أداة support_statement_parts",
          captured[0]["tools"][0]["name"] == "support_statement_parts" and
          captured[0]["tool_choice"]["name"] == "support_statement_parts")
    check("_support_statement_parts: يرقّم الأجزاء في نص الطلب (1. ... 2. ...)",
          "1. جزء أول" in captured[0]["messages"][0]["content"] and
          "2. جزء ثانٍ" in captured[0]["messages"][0]["content"])
    check("_support_statement_parts: بلا مصادر يعيد قائمة فارغة بلا نداء نموذج",
          article._support_statement_parts(["جزء"], [], cfg) == [] and len(captured) == 1)
    check("_support_statement_parts: بلا أجزاء يعيد قائمة فارغة بلا نداء نموذج",
          article._support_statement_parts([], docs, cfg) == [] and len(captured) == 1)

    # ── فشل نداء تقني: call_error لا حكم "لا مؤيِّد لأي جزء" صامت (نظير
    # الضمان القائم في _support_sources/_ask_naming_model) ──
    from anthropic import APIConnectionError
    import httpx as _httpx

    class _RaisingMessages:
        def create(self, **kw):
            raise APIConnectionError(
                message="انقطاع شبكة اختباري",
                request=_httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    class _RaisingClient:
        def __init__(self):
            self.messages = _RaisingMessages()

    article._client = lambda: _RaisingClient()
    fail_result = article._support_statement_parts(["جزء"], docs, cfg)
    article._client = real_client_fn
    check("_support_statement_parts: فشل النداء التقني يبقى falsy (if not result)",
          not fail_result, fail_result)
    check("_support_statement_parts: فشل النداء التقني يحمل call_error بنص الاستثناء",
          "انقطاع شبكة اختباري" in (getattr(fail_result, "call_error", "") or ""),
          getattr(fail_result, "call_error", None))

    # ── تكامل كامل عبر _write_article: تصريح من خمس دعاوى يجتاز بأغلبية،
    # والجزء غير المؤيَّد لا يدخل نص الصياغة (طلب المراجعة، القيد الأهم) ──
    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_support_parts = article._support_statement_parts
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images

    statement_text = "المتحدث يعلن خمسة أمور دفعة واحدة"
    p1, p2, p3, p4, p5 = ("أعلن الأمر الأول", "أعلن الأمر الثاني",
                         "أعلن الأمر الثالث", "أعلن الأمر الرابع",
                         "أعلن الأمر الخامس")
    excerpts = [p1, p2, p3, p4, p5]
    speaker_name = "متحدث الأغلبية"
    plain_fact_text = "واقعة عادية مسنَدة في نفس الموجز"

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار معيار الأغلبية",
        "statements": [
            {"text": statement_text, "kind": "تصريح", "entities": ["المتحدث"],
             "is_unnamed_event": False, "is_reference": False,
             "speaker": speaker_name, "merged_excerpts": excerpts},
            {"text": plain_fact_text, "kind": "واقعة", "entities": ["ك2"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1", "from_text": True},
         {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1", "from_text": True}],
        evidence.EVIDENCE_FULL_TEXT)

    def _fake_parts(merged, docs, cfg):
        mapping = {p1: ["مصدر أول", "مصدر ثانٍ"], p2: ["مصدر أول", "مصدر ثانٍ"],
                  p3: ["مصدر أول"], p4: ["مصدر ثانٍ"], p5: []}
        return [mapping.get(ex, []) for ex in merged]

    article._support_statement_parts = _fake_parts
    article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
        is_report=False, publisher="": (["مصدر أول", "مصدر ثانٍ"]
                                        if fact_text == plain_fact_text else [])
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار الأغلبية؟", "")

    captured_grounded: list = []

    def _fake_draft_article(grounded, opinions, question, cfg, retries=3, avoid_note=""):
        captured_grounded.append(grounded)
        return ({"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
                "image_headline": "عنوان", "post_title": question,
                "post_body": "متن اختباري.", "hashtags": ["اختبار"]}, "")

    article._draft_article = _fake_draft_article
    article.find_images = lambda title, cfg, terms=None: []

    out = article._write_article("موجز اختبار الأغلبية", 9003, cfg)

    check("تكامل الأغلبية: التصريح اجتاز رغم عدم اتفاق مصدر واحد بمفرده على "
          "كل أجزائه الخمسة — مصدران أيّد كل منهما 3/5 فقط",
          not any(d["text"] == statement_text for d in out["dropped"]), out["dropped"])
    check("تكامل الأغلبية: outcome['grounded_count'] == 2 (التصريح + الواقعة العادية)",
          out["grounded_count"] == 2, out["grounded_count"])
    check("تكامل الأغلبية: outcome['produced'] نجح",
          out["produced"] is True, out["reason"])

    statement_grounded = [g for g in (captured_grounded[0] if captured_grounded else [])
                          if g.get("kind") == "تصريح"]
    check("القيد الأهم: نص التصريح الممرَّر إلى الصياغة يضمّ الأجزاء الأربعة المؤيَّدة فقط",
          bool(statement_grounded) and
          all(p in statement_grounded[0]["text"] for p in (p1, p2, p3, p4)),
          statement_grounded)
    check("القيد الأهم: الجزء الخامس (بلا أي مؤيِّد) غائب عن النص الممرَّر إلى "
          "الصياغة رغم اجتياز التصريح ككل بأغلبية أجزاء أخرى — لا نُنشر دعوى "
          "رفضتها المصادر تحت غطاء أغلبية",
          bool(statement_grounded) and p5 not in statement_grounded[0]["text"],
          statement_grounded)

    check("تكامل الأغلبية: outcome['merged_statements'][0]['part_support'] يسجّل "
          "أي مصدر أيّد كل جزء — الجزء الخامس بقائمة مؤيِّدين فارغة",
          any(m["speaker"] == speaker_name and
              next((p["supporting"] for p in m["part_support"] if p["excerpt"] == p5), None) == []
              for m in out["merged_statements"]), out["merged_statements"])

    report = article.build_report(out)
    check("تكامل الأغلبية: التقرير يعرض الجزء الخامس بعلامة «✗ لا مصدر» — لا "
          "إعفاء صامت لجزء رفضته المصادر",
          f"«{p5}» — ✗ لا مصدر" in report, report)
    check("تكامل الأغلبية: التقرير يعرض الأجزاء المؤيَّدة بأسماء مصادرها",
          f"«{p1}» — مصدر أول؛ مصدر ثانٍ" in report, report)

    # judged_by (طلب المراجعة، تعليق العطل الرابع والعشرون بعد ٢٤: "بعد
    # الدمج، النتيجة لم تتغير ولا أثر لمعيار الأغلبية") — بلاغ بنيوي صريح
    # في trail يذكر أي آلية حكمت على عنصر «تصريح»، فلا يمرّ ارتداد إلى
    # الحكم الشمولي القديم بلا أثر ظاهر في التقرير نفسه
    statement_trail = [t for t in out["trail"] if t["stage"] == "تصريح"]
    plain_trail = [t for t in out["trail"] if t["stage"] == "واقعة"]
    check("تكامل الأغلبية: سطر trail لعنصر «تصريح» يحمل judged_by='أجزاء "
          "(معيار الأغلبية)' — لا 'شمولي'",
          bool(statement_trail) and
          all(t["judged_by"] == "أجزاء (معيار الأغلبية)" for t in statement_trail),
          statement_trail)
    check("تكامل الأغلبية: سطر trail للواقعة العادية المجاورة يحمل "
          "judged_by='شمولي' — لا يتسرّب معيار الأغلبية لغير التصريح",
          bool(plain_trail) and all(t["judged_by"] == "شمولي" for t in plain_trail),
          plain_trail)
    check("تكامل الأغلبية: التقرير يعرض «— حُكم بـ: أجزاء (معيار الأغلبية)» "
          "على سطر [تصريح] صراحة — لا استنتاج ضمني من stage وحده",
          "— حُكم بـ: أجزاء (معيار الأغلبية)" in report, report)
    check("تكامل الأغلبية: التقرير لا يطبع «حُكم بـ» على سطر [واقعة] "
          "(لا فائدة تشخيصية إضافية لمرحلة تكون شمولية دومًا)",
          not any("[واقعة]" in ln and "حُكم بـ" in ln for ln in report.splitlines()),
          report)

    article.extract_brief = real_extract_brief
    evidence.search = real_search
    evidence.gather_evidence = real_gather_evidence
    article._support_sources = real_support_sources
    article._support_statement_parts = real_support_parts
    article._choose_question = real_choose_question
    article._draft_article = real_draft_article
    article.find_images = real_find_images


def test_article_split_statements() -> None:
    """فصل الوقائع المركّبة (تشخيص Issue #373، الجولة الخامسة عشرة، البند
    2): جملة واحدة تحمل أكثر من ادّعاء مستقل (قصف مطار / زيارة وفد تركي)
    توزّع سند مصدر واحد فعلي على محاولات منفصلة إن استُخرجت كواقعة واحدة.
    الفصل يقع في مرحلة الاستخراج (WRITEUP_EXTRACT_SYSTEM) لا بتفكيك برمجي
    لاحق — كل جزء ذرّي يحمل split_from (نص الجملة الأصلية) ويُبلَّغ عنه في
    التقرير (split_statements)، نظير merged_statements لكن بالاتجاه
    المعاكس (تجميع أجزاء لا دمج جمل)."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False

    # ── normalize_statement: يلتقط split_from، وفارغ حين لا فصل ──
    part = article.normalize_statement({
        "text": "قُصف مطار أبو الظهور", "kind": "واقعة",
        "entities": ["مطار أبو الظهور", "18 آب"], "is_unnamed_event": False,
        "is_reference": False,
        "split_from": "قُصف مطار أبو الظهور بالتزامن مع زيارة وفد عسكري تركي "
                      "للموقع للعمل على إعادة تأهيله",
    })
    check("normalize_statement: يحفظ split_from لعنصر واقعة فُصل من جملة مركّبة",
          part["split_from"].startswith("قُصف مطار أبو الظهور بالتزامن"), part)

    plain = article.normalize_statement({
        "text": "واقعة عادية بلا فصل", "kind": "واقعة", "entities": ["ك"],
        "is_unnamed_event": False, "is_reference": False,
    })
    check("normalize_statement: عنصر واقعة عادي بلا split_from يبقى فارغًا (لا كسر)",
          plain["split_from"] == "", plain)

    # ── تكامل كامل عبر _write_article: جزءان من نفس الجملة المركّبة، كلٌّ
    # يحمل الكيان المشترك (مطار أبو الظهور) إلى جانب كيانه المميِّز، وكلٌّ
    # يمرّ بحلقة بحث+سند مستقلة (لا يتنافسان على نفس محاولة السند) ──
    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources

    original_sentence = ("قُصف مطار أبو الظهور بالتزامن مع زيارة وفد عسكري تركي "
                          "للموقع للعمل على إعادة تأهيله")
    part_a = "قُصف مطار أبو الظهور"
    part_b = "زار وفد عسكري تركي مطار أبو الظهور"

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار فصل واقعة مركّبة",
        "statements": [
            {"text": part_a, "kind": "واقعة",
             "entities": ["مطار أبو الظهور", "18 آب"], "is_unnamed_event": False,
             "is_reference": False, "split_from": original_sentence},
            {"text": part_b, "kind": "واقعة",
             "entities": ["مطار أبو الظهور", "18 آب", "وفد عسكري تركي"],
             "is_unnamed_event": False, "is_reference": False,
             "split_from": original_sentence},
        ],
        "questions": [],
    }, None)
    evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1", "from_text": True}],
        evidence.EVIDENCE_FULL_TEXT)

    support_calls: list = []

    def _fake_support_split(fact_text, docs, cfg, is_statement=False, is_report=False, publisher=""):
        support_calls.append(fact_text)
        # كلا الجزأين يفشل عمدًا (سند غير كافٍ) — يكفي لإثبات استدعاءين
        # مستقلَّين بلا حاجة لمحاكاة مرحلتَي السؤال/الصياغة، ويحفظ نمط
        # الاختبار المجاور (test_article_statement_kind) لنفس السبب
        return []

    article._support_sources = _fake_support_split

    out = article._write_article("موجز اختبار فصل واقعة مركّبة", 9002, cfg)

    check("فصل الواقعة: كلا الجزأين مرّ بحلقة السند مستقلًا (استدعاء واحد لكلٍّ لا "
          "استدعاء واحد مشترك)",
          support_calls.count(part_a) == 1 and support_calls.count(part_b) == 1,
          support_calls)
    check("فصل الواقعة: كلا الجزأين سقط لانعدام سند (سقوط أحدهما لا يُسقط الآخر معه)",
          any(d["text"] == part_a for d in out["dropped"]) and
          any(d["text"] == part_b for d in out["dropped"]), out["dropped"])
    check("فصل الواقعة: outcome['split_statements'] يجمع الجزأين تحت الجملة الأصلية "
          "بصرف النظر عن سقوطهما لاحقًا — تبليغ لا مشروط بالنجاح، نظير merged_statements",
          any(sp["original"] == original_sentence and
              sp["parts"] == [part_a, part_b] for sp in out["split_statements"]),
          out["split_statements"])

    report = article.build_report(out)
    check("فصل الواقعة: التقرير يعرض قسم «وقائع فُصِّلت من جملة واحدة»",
          "وقائع فُصِّلت من جملة واحدة" in report, report)
    check("فصل الواقعة: التقرير يذكر الجملة الأصلية وكلا الجزأين معًا",
          original_sentence in report and part_a in report and part_b in report,
          report)

    article.extract_brief = real_extract_brief
    evidence.search = real_search
    evidence.gather_evidence = real_gather_evidence
    article._support_sources = real_support_sources


def test_article_split_event_condition() -> None:
    """شرط ثانٍ لقاعدة الفصل + استبعاد الجمل الوصفية البحتة (تشخيص Issue
    #373، الجولة التاسعة عشرة، شاهد "القلعة": ست تفاصيل وصفية عن مكتب دبلن
    فُكِّكت من جملة واحدة وبُحث لكل منها منفردة فرجعت 0 خام ← 0 مطابق —
    لا يوجد خبر مستقل عن عدد موظفي مكتب أو مساحته). الفصل يقع في مرحلة
    الاستخراج (WRITEUP_EXTRACT_SYSTEM) لا بتفكيك برمجي لاحق، فهذا الاختبار
    يتحقق من نص التوجيه الجديد (الشرط الثاني + قاعدة الاستبعاد) ثم يحاكي
    مخرَج استخراج صحيح تبعًا له (لا فصل ولا استخراج للجملة الوصفية البحتة)
    ليثبت أن العمارة اللاحقة (البحث، السند، الصياغة) تتعامل معه بلا عطل."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False

    # ── نص التوجيه: الشرط الثاني (حدث لا وصف) + قاعدة الاستبعاد + الحماية
    # من الإفراط (تفصيلة ملتصقة بواقعة حدثية في جملتها لا تُنزَع) ──
    check("WRITEUP_EXTRACT_SYSTEM: الشرط الثاني للفصل — كل جزء يصف حدثًا لا وصفًا",
          "وكل جزء ناتج عن الفصل يصف" in article.WRITEUP_EXTRACT_SYSTEM and
          "حدثًا" in article.WRITEUP_EXTRACT_SYSTEM)
    check("WRITEUP_EXTRACT_SYSTEM: قاعدة استبعاد الجملة الوصفية البحتة من statements",
          "جملة وصفية بحتة عن كيان مذكور" in article.WRITEUP_EXTRACT_SYSTEM)
    check("WRITEUP_EXTRACT_SYSTEM: مثال القلعة (1827) موجود في التوجيه",
          "1827" in article.WRITEUP_EXTRACT_SYSTEM and
          "16 ألف قدم مربع" in article.WRITEUP_EXTRACT_SYSTEM)
    check("WRITEUP_EXTRACT_SYSTEM: تحذير صريح من الإفراط في الاستبعاد",
          "لا تُفرط في هذا الاستبعاد" in article.WRITEUP_EXTRACT_SYSTEM)
    check("WRITEUP_EXTRACT_SYSTEM: تفصيلة ملتصقة بواقعة حدثية في جملتها لا تُنزَع "
          "(مثال 440 فدانًا ضمن جملة الاستحواذ نفسها)",
          "440 فدانًا" in article.WRITEUP_EXTRACT_SYSTEM and
          "استحوذ زوكربيرغ على" in article.WRITEUP_EXTRACT_SYSTEM)

    # ── تشديد أولوية entities (طلب المراجعة، مراجعة بشرية بعد أول نشر،
    # البند 3): أعلام/أرقام/تواريخ أولًا، لا كلمات موضوعية عامة — عالج
    # عدم حتمية extract_brief جزئيًا بتضييق مساحة الاختيار الحرة ──
    check("WRITEUP_EXTRACT_SYSTEM: أولوية صريحة للأعلام ثم الأرقام ثم التواريخ",
          "أولوية ثابتة صارمة" in article.WRITEUP_EXTRACT_SYSTEM and
          "أسماء الأعلام" in article.WRITEUP_EXTRACT_SYSTEM)
    check("WRITEUP_EXTRACT_SYSTEM: مثالا المستخدم المضادان («شريان حياة»/«النفط») "
          "موجودان حرفيًا كتحذير من كلمات موضوعية عامة",
          "شريان حياة" in article.WRITEUP_EXTRACT_SYSTEM and
          '"النفط"' in article.WRITEUP_EXTRACT_SYSTEM)

    # ── مثال غير عربي صريح للأولوية نفسها (تشخيص Issue #373، تعليق العطل
    # الرابع والعشرون، شاهد بايكرآر التركي: entities المميِّزة «Baykar»/90/
    # «Türkiye» حلّت محلها كلمة موضوعية «stratejimizi» في جولة لاحقة — فرضية
    # المستخدم أن التوجيه صيغ بأمثلة عربية فقط فقد لا يُفهَم سريانه على أي
    # أبجدية). التوجيه يوضّح الآن صراحة أن القاعدة لا تفترض عربية ──
    check("WRITEUP_EXTRACT_SYSTEM: التوجيه يوضّح صراحة أن أولوية الكيانات لا تفترض "
          "نصًّا عربيًا — بأي أبجدية دومًا أولى من كلمة موضوعية عامة",
          "بصرف النظر عن أبجدية الموجز" in article.WRITEUP_EXTRACT_SYSTEM and
          "لا تفترض عربية" in article.WRITEUP_EXTRACT_SYSTEM)
    check("WRITEUP_EXTRACT_SYSTEM: مثال غير عربي صريح (تركي) — Baykar/90/Türkiye "
          "كيانات صحيحة مقابل stratejimizi ككلمة موضوعية عامة",
          "Baykar" in article.WRITEUP_EXTRACT_SYSTEM and
          "Türkiye" in article.WRITEUP_EXTRACT_SYSTEM and
          "stratejimizi" in article.WRITEUP_EXTRACT_SYSTEM)

    # ── normalize_statement: الشرط الثاني لا يكسر فصلًا مشروعًا لجملة
    # متعددة الأحداث الفعلية (المضادان: حصيلة قتلى، استقالة) — كل جزء منها
    # فعل حدوثي صريح فيبقى split_from محفوظًا كما هو (لا رفض بنيوي جديد) ──
    casualties_sentence = "ارتفع عدد القتلى إلى 40 بعد وفاة ثلاثة مصابين متأثرين بجراحهم"
    part_rise = article.normalize_statement({
        "text": "ارتفع عدد القتلى إلى 40", "kind": "واقعة",
        "entities": ["40 قتيلًا"], "is_unnamed_event": False, "is_reference": False,
        "split_from": casualties_sentence,
    })
    part_death = article.normalize_statement({
        "text": "توفي ثلاثة مصابين متأثرين بجراحهم", "kind": "واقعة",
        "entities": ["ثلاثة مصابين"], "is_unnamed_event": False, "is_reference": False,
        "split_from": casualties_sentence,
    })
    check("مضاد (حصيلة القتلى): جزءان بفعلين حدوثيين (ارتفع/توفي) يبقيان مفصولين "
          "— الشرط الثاني لا يبتلع جملًا خبرية حقيقية متعددة الأحداث",
          part_rise["split_from"] == casualties_sentence and
          part_death["split_from"] == casualties_sentence,
          (part_rise, part_death))

    resignation_sentence = "استقال وزير المالية إثر فضيحة فساد وعُيِّن خلفه فورًا"
    part_resign = article.normalize_statement({
        "text": "استقال وزير المالية إثر فضيحة فساد", "kind": "واقعة",
        "entities": ["وزير المالية"], "is_unnamed_event": False, "is_reference": False,
        "split_from": resignation_sentence,
    })
    part_appoint = article.normalize_statement({
        "text": "عُيِّن خلف لوزير المالية فورًا", "kind": "واقعة",
        "entities": ["وزير المالية"], "is_unnamed_event": False, "is_reference": False,
        "split_from": resignation_sentence,
    })
    check("مضاد (الاستقالة): جزءان بفعلين حدوثيين (استقال/عُيِّن) يبقيان مفصولين",
          part_resign["split_from"] == resignation_sentence and
          part_appoint["split_from"] == resignation_sentence,
          (part_resign, part_appoint))

    # ── تكامل كامل عبر _write_article: يحاكي مخرَج استخراج صحيح لموجز
    # القلعة — واقعة الاستحواذ الحدثية الوحيدة (440 فدانًا ملتصقة بنصها/
    # كياناتها، لا تُنزَع)، وواقعة ثانية مستقلة (لبلوغ min_grounded_facts)،
    # وبلا أي عنصر statements للجملة الوصفية البحتة (1500 موظف/16 ألف قدم/
    # ريالتي لابز في كورك) — لأنها استُبعدت في مرحلة الاستخراج نفسها، لا
    # لأن كودًا لاحقًا صفّاها. الشاهد: لا استعلام بحث يحمل أيًّا من ألفاظها ──
    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images

    acquisition_text = "استحوذ زوكربيرغ على القلعة التي تبلغ مساحتها 440 فدانًا"
    second_text = "أعلنت ميتا نقل مقرها الأوروبي إلى المبنى الجديد"
    forbidden = ["1500 موظف", "16 ألف قدم", "ريالتي لابز", "كورك"]

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار استبعاد الجملة الوصفية البحتة",
        "statements": [
            {"text": acquisition_text, "kind": "واقعة",
             "entities": ["زوكربيرغ", "القلعة", "440 فدانًا"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": second_text, "kind": "واقعة",
             "entities": ["ميتا", "المقر الأوروبي"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)

    search_queries: list = []

    def _fake_search_castle(query, cfg, days, unrestricted=False):
        search_queries.append(query)
        return [object()]

    evidence.search = _fake_search_castle
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1", "from_text": True},
         {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1", "from_text": True}],
        evidence.EVIDENCE_FULL_TEXT)
    article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
        is_report=False, publisher="": ["مصدر أول", "مصدر ثانٍ"]
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار القلعة؟", "")

    captured_grounded: list = []

    def _fake_draft_article_castle(grounded, opinions, question, cfg, retries=3, avoid_note=""):
        captured_grounded.append(grounded)
        return ({"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
                "image_headline": "عنوان الصورة", "post_title": question,
                "post_body": f"{acquisition_text}. {second_text}.",
                "hashtags": ["اختبار"]}, "")

    article._draft_article = _fake_draft_article_castle
    article.find_images = lambda title, cfg, terms=None: []

    out = article._write_article("موجز اختبار القلعة", 9004, cfg)

    check("القلعة: لا استعلام بحث واحد يحمل أيًّا من ألفاظ الجملة الوصفية "
          "البحتة (لأنها لم تُستخرج كعنصر statements إطلاقًا)",
          not any(any(bad in q for bad in forbidden) for q in search_queries),
          search_queries)
    check("القلعة: استعلامان فقط (واحد لكل واقعة حدثية) — لا 6 استعلامات كما في "
          "الشاهد المُبلَّغ (تفكيك الجملة الوصفية إلى ست تفاصيل)",
          len(search_queries) == 2, search_queries)
    check("القلعة: outcome['grounded_count'] يساوي 2 — واقعتان حدثيتان فقط لا ست",
          out["grounded_count"] == 2, out["grounded_count"])
    check("القلعة: نص واقعة الاستحواذ الممرَّر إلى الصياغة يبقي 440 فدانًا ملتصقة "
          "به (تفصيلة داخل جملة حدثية لا تُنزَع، لا مُستبعَدة كالجملة الوصفية البحتة)",
          bool(captured_grounded) and
          any("440 فدانًا" in g["text"] for g in captured_grounded[0]),
          captured_grounded)
    check("القلعة: outcome['produced'] نجح — واقعتان حدثيتان كافيتان (min_grounded_facts) "
          "بلا أي حاجة لتفاصيل وصفية إضافية",
          out["produced"] is True, out["reason"])

    article.extract_brief = real_extract_brief
    evidence.search = real_search
    evidence.gather_evidence = real_gather_evidence
    article._support_sources = real_support_sources
    article._choose_question = real_choose_question
    article._draft_article = real_draft_article
    article.find_images = real_find_images


def test_article_mandatory_query_name() -> None:
    """اسم المتحدث (تصريح)/الناشر (تقرير منقول) يدخل الاستعلام إلزامًا بلا
    مزاحمة من كيانات أخرى (طلب المراجعة، تشخيص Issue #373، تعليق العطل
    الثاني والعشرون، البند 1). الشاهد الفعلي: entities لم تتضمّن اسم
    المتحدث («Selçuk Bayraktar») لأنه يُستخرَج في حقل speaker منفصل، فبُني
    استعلام «Baykar yüzde 90 Türkiye» ورجع صفر نتائج، بينما تشغيلة أخرى
    وجدت 7 نتائج بالاستعلام «Selçuk Bayraktar Baykar 90 Türkiye» (خمس
    كلمات — نفس سقف query_max_words الافتراضي)."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False

    check("_fact_mandatory_query_prefix: عنصر «تصريح» يعيد speaker",
          article._fact_mandatory_query_prefix(
              {"kind": "تصريح", "speaker": "Selçuk Bayraktar"}) == "Selçuk Bayraktar")
    check("_fact_mandatory_query_prefix: عنصر «تقرير منقول» يعيد publisher",
          article._fact_mandatory_query_prefix(
              {"kind": "تقرير منقول", "publisher": "Daily Sabah"}) == "Daily Sabah")
    check("_fact_mandatory_query_prefix: «واقعة» عادية بلا اسم إلزامي",
          article._fact_mandatory_query_prefix({"kind": "واقعة"}) == "")
    check("_fact_mandatory_query_prefix: speaker/publisher غائبان لا ينهاران",
          article._fact_mandatory_query_prefix({"kind": "تصريح"}) == "" and
          article._fact_mandatory_query_prefix({"kind": "تقرير منقول"}) == "")

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار الاسم الإلزامي",
        "statements": [
            {"text": "حدَّدنا استراتيجيتنا لتوطين 90 بالمئة من إنتاج SİHA",
             "kind": "تصريح", "speaker": "Selçuk Bayraktar",
             "entities": ["Baykar", "yüzde 90", "Türkiye"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)

    search_queries: list = []

    def _fake_search_mandatory(query, cfg, days, unrestricted=False):
        search_queries.append(query)
        return [object()]

    evidence.search = _fake_search_mandatory
    evidence.gather_evidence = lambda articles, cfg, claim_text="": ([], evidence.EVIDENCE_NO_RESULTS)
    article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
        is_report=False, publisher="": []

    try:
        article._write_article("موجز اختبار الاسم الإلزامي", 9006, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources

    check("اسم المتحدث الإلزامي: استعلام واحد بُني فعليًا لعنصر «تصريح»",
          len(search_queries) == 1, search_queries)
    built_query = search_queries[0] if search_queries else ""
    check("اسم المتحدث الإلزامي: الاستعلام يطابق تمامًا التشغيلة الناجحة الفعلية "
          "«Selçuk Bayraktar Baykar 90 Türkiye» — الاسم أولًا بلا مزاحمة",
          built_query == "Selçuk Bayraktar Baykar 90 Türkiye", built_query)
    check("اسم المتحدث الإلزامي: «yüzde» (لاحقة قياس) لا تدخل رغم ورودها في entities",
          "yüzde" not in built_query.split(), built_query)

    # عنصر «تقرير منقول»: نفس الضمان لاسم الناشر
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار الاسم الإلزامي — تقرير منقول",
        "statements": [
            {"text": "نشرت المنصة تقريرًا عن الحادثة", "kind": "تقرير منقول",
             "publisher": "Daily Sabah",
             "entities": ["حادثة", "منطقة الحدود"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    search_queries.clear()
    evidence.search = _fake_search_mandatory
    evidence.gather_evidence = lambda articles, cfg, claim_text="": ([], evidence.EVIDENCE_NO_RESULTS)
    article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
        is_report=False, publisher="": []
    try:
        article._write_article("موجز اختبار الاسم الإلزامي — تقرير منقول", 9007, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources

    built_report_query = search_queries[0] if search_queries else ""
    check("اسم الناشر الإلزامي (تقرير منقول): يتصدَّر الاستعلام",
          built_report_query.split()[:2] == ["Daily", "Sabah"], built_report_query)


def test_article_report_kind() -> None:
    """تصنيف رابع «تقرير منقول» (تشخيص Issue #373، الجولة السادسة عشرة):
    نقل موجز لتقرير نشرته منصة واحدة بعينها ليس واقعة تحتاج مصدرين مستقلين
    — الحدث هو النشر نفسه لا شيء وقع في العالم يرصده طرف مستقل ثانٍ (نظير
    365Scores/vietnam.vn لكن بالاتجاه المعاكس: هنا خبر صحيح رُفض ظلمًا
    بعتبة لن تتحقق أبدًا بنيويًا). عتبته المستقلة report_min_confirm=1
    بشرط هوية مزدوج بنيوي (لا حكم نموذج) يمنع الالتفاف بتصنيف خبر عادي
    كـ"تقرير منقول" ليمرّ بمصدر واحد، وقاعدة صياغة إلزامية (القاعدة 9)
    تُفرَض بفحص بنيوي لاحق (_report_attribution_ok) لا بالبرومبت وحده."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False

    check("WRITEUP_KINDS يضم «تقرير منقول» تصنيفًا رابعًا",
          "تقرير منقول" in article.WRITEUP_KINDS)

    # ── normalize_statement: publisher إلزامي دلاليًا — بلا ناشر تعود «واقعة» ──
    with_pub = article.normalize_statement({
        "text": "نشر موقع تجريبي تقريرًا يفيد بكذا", "kind": "تقرير منقول",
        "entities": ["كيان"], "is_unnamed_event": False, "is_reference": False,
        "publisher": "موقع تجريبي",
    })
    check("normalize_statement: عنصر «تقرير منقول» بـpublisher محدَّد يبقى بتصنيفه",
          with_pub["kind"] == "تقرير منقول" and with_pub["publisher"] == "موقع تجريبي",
          with_pub)

    no_pub = article.normalize_statement({
        "text": "نشر موقع تجريبي تقريرًا يفيد بكذا", "kind": "تقرير منقول",
        "entities": ["كيان"], "is_unnamed_event": False, "is_reference": False,
    })
    check("normalize_statement: عنصر «تقرير منقول» بلا publisher يعود «واقعة» — "
          "عتبة report_min_confirm لا معنى لتخفيفها بلا هوية ناشر واضحة",
          no_pub["kind"] == "واقعة" and no_pub["publisher"] == "", no_pub)

    plain = article.normalize_statement({
        "text": "واقعة عادية", "kind": "واقعة", "entities": ["ك"],
        "is_unnamed_event": False, "is_reference": False,
    })
    check("normalize_statement: عنصر واقعة عادي بلا publisher يبقى فارغًا (لا كسر)",
          plain["publisher"] == "", plain)

    # ── _report_identity_kind: شرط هوية بنيوي — لا حكم نموذج ──
    original_doc = {"name": "Militaire.gr", "text": "نص تقرير عن موضوع ما"}
    carrier_doc = {"name": "ناقل عربي", "text": "نقل موقع ميليتير اليوناني عن الموضوع كذا"}
    unrelated_doc = {"name": "ناشر آخر", "text": "خبر عادي لا صلة له بالمنصة"}
    check("_report_identity_kind: الوثيقة من الناشر نفسه (canonical) ← original",
          article._report_identity_kind("Militaire.gr", original_doc, cfg) == "original")
    check("_report_identity_kind: وثيقة تسمّي الناشر صراحة في نصها ← carrier",
          article._report_identity_kind("ميليتير", carrier_doc, cfg) == "carrier")
    check("_report_identity_kind: وثيقة لا تطابق الاسم ولا تذكره ← None",
          article._report_identity_kind("ميليتير", unrelated_doc, cfg) is None)
    check("_report_identity_kind: بلا publisher ← None دومًا (لا سند بنيويًا ممكن)",
          article._report_identity_kind("", original_doc, cfg) is None)

    # ── _support_sources(is_report=True) يصفّي docs بشرط الهوية أولًا (بلا
    # نداء نموذج لوثيقة غير مطابقة)، ثم REPORT_SUPPORT_SYSTEM على الناجيات فقط ──
    real_client_fn = article._client
    captured: list = []

    class _CaptureBlock:
        type = "text"

    class _CaptureResp:
        content = [_CaptureBlock()]
        stop_reason = "end_turn"

    class _CaptureMessages:
        def create(self, **kw):
            captured.append(kw)
            return _CaptureResp()

    class _CaptureClient:
        def __init__(self):
            self.messages = _CaptureMessages()

    article._client = lambda: _CaptureClient()
    article._support_sources("تقرير اختباري", [original_doc, unrelated_doc], cfg,
                             is_report=True, publisher="Militaire.gr")
    article._client = real_client_fn

    check("_support_sources(is_report=True) يستعمل REPORT_SUPPORT_SYSTEM لا SUPPORT_SYSTEM",
          captured[0]["system"] == article.REPORT_SUPPORT_SYSTEM)
    prompt_content = captured[0]["messages"][0]["content"]
    check("_support_sources(is_report=True): الوثيقة المطابقة للهوية فقط تصل البرومبت "
          "— unrelated_doc (لا يطابق الهوية) لا تصل النموذج إطلاقًا",
          original_doc["name"] in prompt_content and unrelated_doc["name"] not in prompt_content,
          prompt_content)

    captured.clear()
    article._client = lambda: _CaptureClient()
    result_none = article._support_sources("تقرير اختباري", [unrelated_doc], cfg,
                                           is_report=True, publisher="Militaire.gr")
    article._client = real_client_fn
    check("_support_sources(is_report=True): بلا وثيقة تطابق الهوية، لا نداء نموذج "
          "إطلاقًا (شرط بنيوي يمنع الالتفاف) — يعود [] فورًا",
          result_none == [] and captured == [], (result_none, captured))

    # ── _report_attribution_ok: القاعدة 9 كفحص بنيوي — لا اعتمادًا على "
    # البرومبت وحده (طلب المراجعة، البند 1) ──
    report_fact = {"kind": "تقرير منقول", "publisher": "ميليتير", "text": "نص التقرير"}
    ok1, why1 = article._report_attribution_ok(
        "وبحسب تقرير نشره موقع ميليتير اليوناني، فإن الأمر كذا.", [report_fact])
    check("_report_attribution_ok: متن ينسب المضمون لاسم الناشر صراحة ← يُقبل",
          ok1 is True and why1 == "", (ok1, why1))
    ok2, why2 = article._report_attribution_ok(
        "الأمر كذا بحسب تقرير نُشر مؤخرًا.", [report_fact])
    check("_report_attribution_ok: متن يقدّم مضمون التقرير بلا نسبة لاسم الناشر ← يُرفض",
          ok2 is False and "القاعدة 9" in why2, (ok2, why2))
    ok3, why3 = article._report_attribution_ok(
        "متن عادي لا يذكر أي تقرير", [{"kind": "واقعة", "text": "واقعة عادية"}])
    check("_report_attribution_ok: بلا عنصر «تقرير منقول» في grounded ← يُقبل دومًا",
          ok3 is True, (ok3, why3))

    # ── تكامل كامل عبر _write_article: عتبة مصدر واحد، شرط الهوية، القسم في
    # التقرير، وضابط _sufficiency الثالث (مقال بكامله تقارير منقولة لا يكفي) ──
    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images

    report_text = "نشر موقع ميليتير اليوناني تقريرًا يفيد بأن الجيش يعزز قدراته"
    publisher_name = "ميليتير"
    carrier_name = "سكاي نيوز عربية"

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار تصنيف تقرير منقول",
        "statements": [
            {"text": report_text, "kind": "تقرير منقول", "entities": ["الجيش"],
             "is_unnamed_event": False, "is_reference": False,
             "publisher": publisher_name},
            {"text": "واقعة عادية مسندة بمصدرين", "kind": "واقعة",
             "entities": ["ك2"], "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": carrier_name,
          "text": f"نقلت {carrier_name} عن موقع ميليتير اليوناني أن الجيش يعزز قدراته",
          "link": "https://c/1", "from_text": True}],
        evidence.EVIDENCE_FULL_TEXT)

    support_calls: list = []

    def _fake_support_report(fact_text, docs, cfg, is_statement=False, is_report=False,
                             publisher=""):
        support_calls.append((fact_text, is_statement, is_report, publisher))
        if fact_text == report_text:
            return [carrier_name]
        if fact_text == "واقعة عادية مسندة بمصدرين":
            return ["مصدر أول", "مصدر ثانٍ"]
        return []

    def _fake_choose_question_report(grounded, cfg, retries=2):
        return "سؤال اختبار تقرير منقول؟", ""

    def _fake_draft_article_ok(grounded, opinions, question, cfg, retries=3, avoid_note=""):
        return ({"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
                "image_headline": "عنوان الصورة", "post_title": question,
                "post_body": ("وبحسب تقرير نشره موقع ميليتير اليوناني، يعزز الجيش "
                             "قدراته. وأكّدت واقعة عادية أخرى مسندة الأمر."),
                "hashtags": ["اختبار"]}, "")

    article._support_sources = _fake_support_report
    article._choose_question = _fake_choose_question_report
    article._draft_article = _fake_draft_article_ok
    article.find_images = lambda title, cfg, terms=None: []

    out = article._write_article("موجز اختبار تصنيف تقرير منقول", 9003, cfg)

    check("تقرير منقول: _support_sources استُدعيت بـis_report=True وpublisher الصحيح "
          "للعنصر «تقرير منقول» تحديدًا",
          any(t == (report_text, False, True, publisher_name) for t in support_calls),
          support_calls)
    check("تقرير منقول: مصدر واحد فقط (report_min_confirm=1) كافٍ لإسناده — لم يسقط",
          not any(d["text"] == report_text for d in out["dropped"]), out["dropped"])
    check("تقرير منقول: trail يسجّل مرحلة «تقرير» (لا «واقعة») للعنصر المصنَّف "
          "تقريرًا منقولًا",
          any(t["stage"] == "تقرير" and t["query"] for t in out["trail"]), out["trail"])
    check("تقرير منقول: outcome['report_statements'] يذكر الناشر والمصدر المسنِد "
          "بتمييز صريح ناقل/أصلي — هنا carrier (لم يُطابِق اسم الوثيقة الناشر "
          "نفسه، بل ذكرته نصًّا)",
          any(r["publisher"] == publisher_name and r["text"] == report_text and
              any(s["name"] == carrier_name and s["kind"] == "carrier"
                  for s in r["sources"])
              for r in out["report_statements"]),
          out["report_statements"])
    check("تقرير منقول: outcome['produced'] نجح — القاعدة 9 اجتازت (المتن ينسب "
          "المضمون لاسم الناشر صراحة)",
          out["produced"] is True, out["reason"])

    report = article.build_report(out)
    check("تقرير منقول: التقرير يعرض قسم «تقارير مُرحَّلة عن ناشر واحد (راجعها)»",
          "تقارير مُرحَّلة عن ناشر واحد" in report, report)
    check("تقرير منقول: التقرير يميّز صراحة بين الوثيقة الأصلية والناقل — «ناقل يسمّي "
          "الناشر» ظاهرة هنا (لا «الوثيقة الأصلية»، اسم الوثيقة يختلف عن الناشر)",
          "ناقل يسمّي الناشر" in report and publisher_name in report, report)

    # ── القاعدة 9 كفحص بنيوي فعلي: متن لا ينسب المضمون يُرفض المقال كاملًا ──
    def _fake_draft_article_bad(grounded, opinions, question, cfg, retries=3, avoid_note=""):
        return ({"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
                "image_headline": "عنوان الصورة", "post_title": question,
                "post_body": ("يعزز الجيش قدراته بحسب تقرير حديث. وأكّدت واقعة عادية "
                             "أخرى مسندة الأمر."),
                "hashtags": ["اختبار"]}, "")

    article._draft_article = _fake_draft_article_bad
    out_bad = article._write_article("موجز اختبار تصنيف تقرير منقول", 9003, cfg)
    check("تقرير منقول: متن يقدّم مضمون التقرير بلا نسبة صريحة لاسم الناشر ← "
          "outcome['produced'] يفشل (فحص بنيوي لاحق، لا اعتمادًا على البرومبت وحده)",
          out_bad["produced"] is False and "القاعدة 9" in out_bad["reason"],
          out_bad["reason"])

    article.extract_brief = real_extract_brief
    evidence.search = real_search
    evidence.gather_evidence = real_gather_evidence
    article._support_sources = real_support_sources
    article._choose_question = real_choose_question
    article._draft_article = real_draft_article
    article.find_images = real_find_images

    # ── ضابط _sufficiency الثالث: مقال بكامله «تقارير منقولة» لا يكفي (نظير
    # شرط الوقائع المرجعية، البند 6) ──
    all_report_grounded = [
        {"kind": "تقرير منقول", "is_reference": False, "text": "تقرير أول"},
        {"kind": "تقرير منقول", "is_reference": False, "text": "تقرير ثانٍ"},
    ]
    ok_suff, reason_suff = article._sufficiency(all_report_grounded, cfg)
    check("_sufficiency: مقال بعدد كافٍ من الوقائع لكن كلها «تقرير منقول» ← يُرفض",
          ok_suff is False and "تقارير منقولة" in reason_suff, reason_suff)

    mixed_grounded = [
        {"kind": "تقرير منقول", "is_reference": False, "text": "تقرير أول"},
        {"kind": "واقعة", "is_reference": False, "text": "واقعة مسندة عادية"},
    ]
    ok_suff2, reason_suff2 = article._sufficiency(mixed_grounded, cfg)
    check("_sufficiency: واقعة واحدة على الأقل ليست «تقرير منقول» ضمن grounded كافية "
          "لاجتياز هذا الضابط",
          ok_suff2 is True, reason_suff2)


def test_article_generic_source_publisher() -> None:
    """ضابط بنيوي على publisher لـ"تقرير منقول" (تشخيص Issue #373، الجولة
    السابعة عشرة): «قنوات تيليغرام إسرائيلية» صُنِّفت ناشرًا فمرّت بعتبة 1
    رغم أنها وصف فئة جماعية مجهولة لا كيانًا إعلاميًا واحدًا. الضابط صنف
    نحوي مغلق صغير (GENERIC_SOURCE_PLURAL_HEADS، نظير _AR_STOP بنيويًا) —
    الرفض على رأس الاسم الجمعي وحده، بصرف النظر عن الوصف اللاحق، فمفرد +
    اسم علم («قناة الجزيرة») يمرّ لأنه ليس جمعًا."""
    from src import article

    check("_publisher_head_word: يستخرج أول كلمة بعد حذف أل التعريف",
          article._publisher_head_word("القنوات الإسرائيلية") == "قنوات")
    check("_publisher_head_word: كلمة واحدة بلا أل التعريف تُعاد كما هي",
          article._publisher_head_word("ميليتير") == "ميليتير")
    check("_publisher_head_word: نص فارغ لا ينهار",
          article._publisher_head_word("") == "")

    generic_examples = [
        "قنوات تيليغرام إسرائيلية", "ناشطون", "حسابات", "مصادر مطلعة",
        "وسائل إعلام",
    ]
    for pub in generic_examples:
        check(f"_is_generic_source_publisher: «{pub}» فئة جماعية مجهولة ← مرفوض",
              article._is_generic_source_publisher(pub) is True, pub)

    named_examples = ["ميليتير", "الجزيرة", "نيويورك تايمز", "قناة الجزيرة",
                      "رويترز"]
    for pub in named_examples:
        check(f"_is_generic_source_publisher: «{pub}» كيان مسمّى واحد ← يمرّ "
              "(مفرد وليس جمعًا، حتى مع سابقة تصنيفية مفردة مثل «قناة»)",
              article._is_generic_source_publisher(pub) is False, pub)

    # ── normalize_statement: الضابط بنيوي — يُطبَّق فعليًا لا توثيقًا فقط ──
    generic_stmt = article.normalize_statement({
        "text": "نشرت قنوات تيليغرام إسرائيلية تقريرًا يفيد بكذا",
        "kind": "تقرير منقول", "entities": ["كيان"],
        "is_unnamed_event": False, "is_reference": False,
        "publisher": "قنوات تيليغرام إسرائيلية",
    })
    check("normalize_statement: publisher بصيغة جمع («قنوات تيليغرام إسرائيلية») "
          "يعود العنصر إلى «واقعة» بعتبتها الكاملة — نظير عنصر بلا publisher تمامًا",
          generic_stmt["kind"] == "واقعة", generic_stmt)

    named_stmt = article.normalize_statement({
        "text": "نشرت قناة الجزيرة تقريرًا يفيد بكذا",
        "kind": "تقرير منقول", "entities": ["كيان"],
        "is_unnamed_event": False, "is_reference": False,
        "publisher": "قناة الجزيرة",
    })
    check("normalize_statement: publisher مفرد + اسم علم («قناة الجزيرة») يبقى "
          "«تقرير منقول» — ليس جمعًا فلا يُرفض",
          named_stmt["kind"] == "تقرير منقول" and
          named_stmt["publisher"] == "قناة الجزيرة", named_stmt)

    # ── القاعدة 10 (طلب المراجعة، البند 2): ادّعاء نية عسكرية/تخطيط هجوم
    # مصدره «تقرير منقول» لا يدخل المتن إطلاقًا مهما كان سنده ──
    template = article.DRAFT_SYSTEM_TEMPLATE.format(opinion_phrase="x")
    check("10) برومبت الصياغة يوجّه صراحة بحذف ادّعاء النية العسكرية/تخطيط الهجوم "
          "المصدره «تقرير منقول» كليًا من المتن — لا نسبة ولا تحفّظ",
          "نية عسكرية" in template and "تخطيطًا لهجوم" in template and
          "لا تدخل المتن إطلاقًا" in template)


def test_article_unsourced_entities() -> None:
    """فحص بنيوي بعدي — بلاغ لا رفض (طلب المراجعة، تشخيص Issue #373، الجولة
    السابعة عشرة، البند 2): البرومبت وحده لا يمنع نقل تفصيلة من نص مصدر
    كامل (نصوص المصادر تصل البرومبت للأسلوب لا للمضمون) لم تمرّ ببوابة
    السند — نمط «هوي كا يان معروف بالصينية باسم شو جيايين» الفعلي. الفحص
    اللاحق (_unsourced_entities) يقارن كيانات المتن (أرقام، وتتابعات كلمات
    مضمون متتالية) بمجمّع الوقائع المسندة والموجز، ويُبلِغ فقط — لا يرفض."""
    from src import article

    # ── (ب) DRAFT_USER_TEMPLATE: التناقض مع القاعدة 1 أُصلح ──
    check("DRAFT_USER_TEMPLATE: لا تبقى صيغة «من هذه الوقائع والنصوص حصرًا» "
          "المتناقضة مع القاعدة 1",
          "من هذه الوقائع والنصوص" not in article.DRAFT_USER_TEMPLATE,
          article.DRAFT_USER_TEMPLATE)
    check("DRAFT_USER_TEMPLATE: نصوص المصادر مُوصوفة صراحة كمادة أسلوبية لا مضمون",
          "للأسلوب" in article.DRAFT_USER_TEMPLATE and
          "لا كمصدر مضمون إضافي" in article.DRAFT_USER_TEMPLATE and
          "{source_texts}" in article.DRAFT_USER_TEMPLATE,
          article.DRAFT_USER_TEMPLATE)
    check("DRAFT_USER_TEMPLATE: التوجيه الجديد يحصر المضمون في facts_block صراحة",
          "الوقائع المسندة أعلاه حصرًا" in article.DRAFT_USER_TEMPLATE,
          article.DRAFT_USER_TEMPLATE)

    # ── (أ) نصوص المصادر تبقى كاملة في البرومبت — لا تضييق إلى مقتطف ──
    grounded_a = [{"text": "و1", "kind": "واقعة", "sources": [
        {"name": "م1", "text": "نص مصدر كامل طويل جدًا " * 20, "link": "https://s/1"}]}]
    real_call_draft = article._call_draft_model
    captured_prompt: list = []
    article._call_draft_model = lambda prompt, system_text, cfg, retries=3: (
        captured_prompt.append(prompt) or
        {"post_title": "س", "post_body": "م", "hashtags": [], "category": "عالم"})
    article._draft_article(grounded_a, [], "سؤال؟", load_config())
    article._call_draft_model = real_call_draft
    check("(أ) نص المصدر الكامل (لا مقتطف مقصوص) يصل البرومبت فعليًا",
          "نص مصدر كامل طويل جدًا" in captured_prompt[0] and
          captured_prompt[0].count("نص مصدر كامل طويل جدًا") >= 20,
          len(captured_prompt[0]))

    # ── (ج) اللبنات: _extract_numbers، _content_words، _word_known ──
    check("_extract_numbers: فواصل الآلاف (لاتينية) تُحذف قبل المطابقة",
          article._extract_numbers("1,234 قتيلًا") == {"1234"})
    check("_extract_numbers: فاصلة عربية (٬) تُعامَل بالمثل",
          article._extract_numbers("1٬234 قتيلًا") == {"1234"})
    check("_extract_numbers: رقمان منفصلان يُستخرَجان معًا",
          article._extract_numbers("قُتل 12 وأُصيب 45") == {"12", "45"})

    words_on = article._content_words("شنّت طائرات غارة على موقع")
    check("_content_words: «على» تُسقَط كوقف رغم ترجمة الهمزة (ى←ي) — عطل مكتشَف "
          "في مطابقة request._AR_STOP الأصلية، أُصلح محليًا هنا (_AR_STOP_NORM)",
          "علي" not in [n for _, n in words_on] and
          not any(raw == "على" for raw, _ in words_on), words_on)
    words_short = article._content_words("شو معروف")
    check("_content_words: كلمة قصيرة (٢ حرفين، «شو») تُسقَط بلا كسر التجاور",
          [raw for raw, _ in words_short] == ["معروف"], words_short)

    known = {"سوريا", "دمشق"}
    check("_word_known: تطابق حرفي بعد التطبيع",
          article._word_known(article._normalize_word("سوريا"), known) is True)
    check("_word_known: اشتقاق الاسم (بادئة مشتركة ≥4 أحرف) يُعامَل معروفًا — "
          "«السوري» صفة مشتقة من «سوريا» المعروفة",
          article._word_known(article._normalize_word("السوري"), known) is True)
    check("_word_known: كلمة غير مرتبطة إطلاقًا تبقى غير معروفة",
          article._word_known(article._normalize_word("اليابان"), known) is False)

    # ── _unsourced_entities: الحالة الفعلية (اسم بلغتين لم يمرّ ببوابة السند) ──
    grounded_name = [{"text": "هوي كا يان أعلن اعتزاله كرة القدم", "kind": "واقعة",
                      "entities": ["هوي كا يان"], "sources": []}]
    body_with_leak = ("أعلن هوي كا يان، المعروف بالصينية باسم جيايين، "
                      "اعتزاله كرة القدم.")
    notes_leak = article._unsourced_entities(
        body_with_leak, grounded_name, "هوي كا يان أعلن اعتزاله", "", [])
    check("_unsourced_entities: تفصيلة من نص مصدر (اسم صيني) لم ترد في الوقائع "
          "المسندة ولا الموجز ← بلاغ يحتوي «جيايين» (source_texts=None: سلوك "
          "الطول القديم بلا تصحيح)",
          any("جيايين" in n for n in notes_leak), notes_leak)

    # ── حصر النطاق (طلب المراجعة، تشخيص Issue #373، تعليق العطل الثاني
    # والعشرون، البند 1): الفحص كان يُغرق بشظايا نحوية لأن _content_words
    # المسطّحة كانت تُسقط كلمات الوقف من القائمة كليًا فتلتصق كلمتان غير
    # متجاورتين أصلًا في النص («قادر على العمل» ← «قادر العمل» بعد إسقاط
    # «على»). _content_word_runs يحفظ التجاور الحقيقي فلا يعود يلتقطهما ──
    runs_gap = article._content_word_runs("قادر على العمل سواء")
    check("_content_word_runs: «على» تقطع التجاور — تتابعان منفصلان "
          "([قادر] و[العمل، سواء]) لا تتابع واحد يضمّ «قادر» و«العمل» معًا",
          len(runs_gap) == 2
          and [w[1] for w in runs_gap[0]] == [article._normalize_word("قادر")]
          and [w[1] for w in runs_gap[1]] == [article._normalize_word("العمل"),
                                              article._normalize_word("سواء")],
          runs_gap)
    runs_true = article._content_word_runs("جيايين لاعب كرة مشهور")
    check("_content_word_runs: تتابع متجاور فعلًا (بلا وقف بينه) يبقى قائمة "
          "فرعية واحدة",
          len(runs_true) == 1 and len(runs_true[0]) == 4, runs_true)

    # ── حصر النطاق: تتابع متجاور فعلًا في المتن لكن لا يرد في أي مصدر مقروء
    # ← لا يُبلَّغ (شظية أسلوبية من إعادة الصياغة، لا تفصيلة منقولة فعلًا) ──
    grounded_style = [{"text": "أعلنت الشركة توسعها التشغيلي", "kind": "واقعة",
                       "entities": [], "sources": []}]
    body_style_leak = "أعلنت الشركة توسعها التشغيلي بمرونة إدارية واضحة."
    notes_no_corrob = article._unsourced_entities(
        body_style_leak, grounded_style, "", "", [],
        source_texts=["نص مصدر لا يذكر أي تفصيلة إضافية هنا إطلاقًا."])
    check("_unsourced_entities: تتابع غير معروف لكن غائب عن كل نص مصدر معطى "
          "(source_texts≠None) ← لا يُبلَّغ (يقصر البلاغ على ما وَرَد فعلًا "
          "في نص مصدر مقروء)",
          notes_no_corrob == [], notes_no_corrob)

    # ── نفس تتابع «شو جيايين» لكن مع تمرير source_texts فعليًا: يبقى مُبلَّغًا
    # عنه فقط لأنه يرد حرفيًا متجاورًا في نص المصدر المعطى — لا لمجرد طوله ──
    notes_leak_corrob = article._unsourced_entities(
        body_with_leak, grounded_name, "هوي كا يان أعلن اعتزاله", "", [],
        source_texts=[body_with_leak])
    check("_unsourced_entities: نفس التفصيلة، لكن الآن بشرط الورود الحرفي في "
          "نص مصدر (source_texts) ← تبقى مُبلَّغًا عنها لأنها ترد فعلًا هناك",
          any("جيايين" in n for n in notes_leak_corrob), notes_leak_corrob)
    notes_leak_no_source = article._unsourced_entities(
        body_with_leak, grounded_name, "هوي كا يان أعلن اعتزاله", "", [],
        source_texts=["نص مصدر مختلف تمامًا بلا أي ذكر لهذا الاسم إطلاقًا."])
    check("_unsourced_entities: نفس التفصيلة، لكن لا يرد التتابع في نص "
          "المصدر المعطى فعليًا ← لا يُبلَّغ عنها رغم طولها",
          not any("جيايين" in n for n in notes_leak_no_source), notes_leak_no_source)

    # ── استثناء صيغة نسبة الرأي الثابتة (attribution_phrase) — بقية الجملة
    # معروفة عبر opinions فلا تتداخل مع الفحص (تعزل أثر attribution_phrase
    # وحده)؛ source_texts=None يُبقي شرط الطول وحده (لا علاقة بالسؤال هنا) ──
    grounded_op: list = []
    opinions_attrib = [{"text": "هذا التطور مهم لمستقبل الملف"}]
    body_with_attribution = "وترى الصفحة أن هذا التطور مهم لمستقبل الملف."
    notes_attrib = article._unsourced_entities(
        body_with_attribution, grounded_op, "", "", opinions_attrib,
        attribution_phrase="وترى الصفحة أن")
    check("_unsourced_entities: صيغة نسبة الرأي الثابتة (opinion_attribution_"
          "phrase) معفاة صراحة عبر attribution_phrase — لا تُبلَّغ رغم أنها "
          "غير واردة في الوقائع/الموجز",
          notes_attrib == [], notes_attrib)
    notes_no_attrib_param = article._unsourced_entities(
        body_with_attribution, grounded_op, "", "", opinions_attrib)
    check("_unsourced_entities: بلا attribution_phrase (سلوك ما قبل هذا "
          "الإصلاح) ← صيغة النسبة نفسها («وترى الصفحة») تُبلَّغ لأنها غير "
          "معروفة — يثبت أن الإعفاء الجديد فعليًا هو من أسقطها أعلاه",
          any("وترى" in n for n in notes_no_attrib_param), notes_no_attrib_param)

    # ── لا إنذار كاذب: إعادة صياغة كاملة بلا مضمون جديد (القاعدة 5 تُلزم بها) ──
    grounded_rephrase = [{"text": "قصفت طائرات حربية موقعا عسكريا قرب المدينة",
                          "kind": "واقعة", "entities": [], "sources": []}]
    body_rephrased = "شنّت طائرات حربية غارة على موقع عسكري قرب المدينة."
    notes_rephrase = article._unsourced_entities(
        body_rephrased, grounded_rephrase, "", "", [])
    check("_unsourced_entities: إعادة صياغة مشروعة (لا مضمون جديد، كلمة واحدة "
          "مختلفة كحد أقصى في كل تتابع) ← بلا بلاغ",
          notes_rephrase == [], notes_rephrase)

    # ── رقم مُختلَق يُبلَّغ فرديًا (بلا حاجة لكلمتين متتاليتين) ──
    grounded_num = [{"text": "قتل 12 شخصا في الحادث", "kind": "واقعة",
                     "entities": [], "sources": []}]
    notes_num = article._unsourced_entities(
        "أسفر الحادث عن مقتل 45 شخصا.", grounded_num, "", "", [])
    check("_unsourced_entities: رقم غير وارد في الوقائع المسندة ولا الموجز ← يُبلَّغ",
          any("45" in n for n in notes_num), notes_num)
    check("_unsourced_entities: رقم وارد فعلًا في الوقائع المسندة ← لا يُبلَّغ عنه",
          not any("12" in n for n in notes_num), notes_num)

    # ── الفئات الثلاث (طلب المراجعة، مراجعة بشرية بعد أول نشر، البند 2):
    # تتابع يحمل كلمة ربط تاريخ (شهر/سنة) يُوسَم "تاريخ" صراحة لا الرسالة
    # العامة، وتتابع بلا كلمة ربط كهذه يبقى "اسم" ──
    check("_is_date_run: تتابع يحوي اسم شهر عربي (شباط) يُصنَّف تاريخًا",
          article._is_date_run([article._normalize_word("شباط"),
                                article._normalize_word("الماضي")]) is True)
    check("_is_date_run: تتابع بلا كلمة ربط تاريخ لا يُصنَّف تاريخًا",
          article._is_date_run([article._normalize_word("جيايين"),
                                article._normalize_word("لاعب")]) is False)
    grounded_date = [{"text": "أعلن ذلك", "kind": "واقعة", "entities": [], "sources": []}]
    notes_date = article._unsourced_entities(
        "وذلك في 15 شباط الماضي وفق ما ورد.", grounded_date, "", "", [])
    check("_unsourced_entities: تتابع تاريخ غير مسنَد يُوسَم «تاريخ» صراحة في نص البلاغ",
          any(n.startswith("تاريخ «") and "شباط" in n for n in notes_date), notes_date)
    notes_name = article._unsourced_entities(
        body_with_leak, grounded_name, "هوي كا يان أعلن اعتزاله", "", [])
    check("_unsourced_entities: تتابع اسم علم (لا تاريخ) يُوسَم «اسم» لا «تاريخ»",
          any(n.startswith("اسم «") for n in notes_name), notes_name)

    # ── اسم الناشر/المتحدث المشروع (القاعدتان 8،9) لا يُبلَّغ عنه — من مجمّع
    # المعروف عبر speaker/publisher لا تخمينًا ──
    grounded_pub = [{"text": "نشر ذلك", "kind": "تقرير منقول", "publisher": "ميليتير",
                     "entities": [], "sources": []}]
    notes_pub = article._unsourced_entities(
        "وبحسب تقرير نشرته منصة ميليتير أن الأمر كذا.", grounded_pub, "", "", [])
    check("_unsourced_entities: اسم الناشر (من حقل publisher البنيوي) معروف — لا يُبلَّغ",
          not any("ميليتير" in n for n in notes_pub), notes_pub)

    # ── min_run قابل للضبط عبر config.yaml ──
    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False
    check("config.yaml: article.unsourced_entity_min_run موجود وقابل للضبط",
          cfg.path("article.unsourced_entity_min_run") is not None)

    # ── تكامل كامل عبر _write_article: بلاغ لا رفض — outcome['produced'] يبقى
    # True رغم وجود تفصيلة غير مسندة، وتظهر في التقرير ──
    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار كيانات غير مسندة",
        "statements": [
            {"text": "هوي كا يان أعلن اعتزاله كرة القدم", "kind": "واقعة",
             "entities": ["هوي كا يان"], "is_unnamed_event": False,
             "is_reference": False},
            {"text": "واقعة ثانية مسندة بمصدرين", "kind": "واقعة",
             "entities": ["ك2"], "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
    # نص المصدر يحمل التفصيلة المسرّبة حرفيًا («المعروف بالصينية باسم
    # جيايين» — 4 كلمات، نفس التتابع الذي سيُبلَّغ عنه) كي تجتاز شرط الورود
    # الحرفي في source_texts (طلب المراجعة، تعليق العطل الثاني والعشرون،
    # البند 1)، لكن بصياغة محيطة مختلفة عن المسودة كي لا يشترك النصان في
    # تتابع ≥7 كلمات فيُرفَض المقال كليًا بفحص الأصالة (اختبار منفصل تمامًا،
    # لا علاقة له بهذا الفحص البعدي — التداخل هنا أثر جانبي لتصميم الاختبار
    # لا عطلًا فعليًا: تسريب أقصر من 7 كلمات، كحالتنا، لا يصطدم بذلك الفحص)
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": "مصدر أول", "link": "https://s1/1", "from_text": True,
          "text": "لاعب كرة القدم الصيني الأشهر، المعروف بالصينية باسم "
                 "جيايين، اعتزل مؤخرًا."},
         {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1", "from_text": True}],
        evidence.EVIDENCE_FULL_TEXT)
    article._support_sources = lambda *a, **k: ["مصدر أول", "مصدر ثانٍ"]
    article._choose_question = lambda grounded, cfg, retries=2: ("لماذا اعتزل؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "رياضة",
         "image_headline": "اعتزال", "post_title": question,
         "post_body": ("أعلن هوي كا يان، المعروف بالصينية باسم جيايين، "
                      "اعتزاله كرة القدم."),
         "hashtags": ["اعتزال"]}, "")
    article.find_images = lambda title, cfg, terms=None: []

    out = article._write_article("موجز اختبار كيانات غير مسندة", 9004, cfg)

    check("تكامل: outcome['unsourced_entities'] يحتوي التفصيلة غير المسندة",
          any("جيايين" in n for n in out["unsourced_entities"]), out["unsourced_entities"])
    check("تكامل: outcome['produced'] يبقى True — بلاغ لا رفض",
          out["produced"] is True, out["reason"])

    report = article.build_report(out)
    check("تكامل: التقرير يعرض قسم «تفاصيل لم تجتز بوابة السند (راجعها)»",
          "تفاصيل لم تجتز بوابة السند" in report and "جيايين" in report, report)

    article.extract_brief = real_extract_brief
    evidence.search = real_search
    evidence.gather_evidence = real_gather_evidence
    article._support_sources = real_support_sources
    article._choose_question = real_choose_question
    article._draft_article = real_draft_article
    article.find_images = real_find_images


def test_evidence_top_candidates() -> None:
    """رصد أعلى 5 مرشّحين بالاسم/الوزن/الصلة/الدرجة المركّبة في trail (تشخيص
    Issue #373، الجولة الثالثة عشرة، البند 2، الخيار (و)): بلا لمس
    _candidate_score نفسها — رصد صرف يحسم لاحقًا برقم فعلي هل تفوّق صلة
    لفظية عالية على فارق وزن ثابت هو ما يمنع مصدرًا موثوقًا من الصعود."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False

    trusted = Article(title="خبر من مصدر موثوق بصياغة تحريرية لا تشارك كلمات الاستعلام",
                      link="https://trusted.example/1", summary="ملخص تحريري",
                      source_name="Al Jazeera", region="global", weight=1.0,
                      published=datetime.now(timezone.utc), publisher="Al Jazeera")
    generic = Article(title="روبيرتو كارلوس الإسلام خبر مطابق لفظيًا حرفيًا للاستعلام",
                      link="https://generic.example/1", summary="ملخص",
                      source_name="موقع مجهول", region="global", weight=1.0,
                      published=datetime.now(timezone.utc), publisher="موقع مجهول")

    real_extract_gather = extract.gather
    extract.gather = lambda members, limit=3: ([], [])  # لا نص كامل — يكفي الفرز قبل القراءة
    docs, basis = evidence.gather_evidence(
        [trusted, generic], cfg, "روبيرتو كارلوس الإسلام")

    top = getattr(docs, "top_candidates", None)
    check("gather_evidence: docs تحمل top_candidates كسمة إضافية (نظير fetch_failures)",
          top is not None, docs)
    check("top_candidates: لا يتجاوز 5 مرشّحين", len(top) <= 5, top)
    check("top_candidates: كل عنصر يحمل اسم/وزن/صلة/درجة مركّبة",
          all({"name", "weight", "relevance", "score"} <= set(c.keys()) for c in top), top)
    # سقف الصلة نُفِّذ لاحقًا (تعليق الموافقة الخامس عشر، البند 1) — الدرجة
    # تساوي وزن + صلة مقصوصة عند RELEVANCE_CAP لا وزن+صلة خامًا كما كانت
    check("top_candidates: الدرجة المركّبة تساوي وزن + صلة مقصوصة عند RELEVANCE_CAP "
          "لكل مرشّح فعليًا",
          all(abs(c["score"] - (c["weight"] + min(c["relevance"], evidence.RELEVANCE_CAP)))
              < 1e-6 for c in top), top)
    names = [c["name"] for c in top]
    check("top_candidates: يضمّ كلا المرشّحين (الموثوق والمجهول) — رصد كامل لا جزئي",
          "Al Jazeera" in names and "موقع مجهول" in names, top)

    # trail في article.py: كل موضع gather_evidence يُمرِّر top_candidates
    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار رصد المرشّحين",
        "statements": [{"text": "واقعة اختبار المرشّحين", "kind": "واقعة",
                        "entities": ["ك"], "is_unnamed_event": False,
                        "is_reference": False}],
        "questions": [],
    }, None)
    evidence.search = lambda query, cfg, days, unrestricted=False: [trusted, generic]
    article._support_sources = (
        lambda fact_text, docs, cfg, is_statement=False, is_report=False, publisher="": [])

    try:
        out = article._write_article("موجز اختبار رصد المرشّحين", 9002, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        extract.gather = real_extract_gather

    fact_trail = [t for t in out["trail"] if t["stage"] == "واقعة"]
    check("trail: عنصر مرحلة «واقعة» يحمل top_candidates فعليًا لا قائمة فارغة دومًا",
          bool(fact_trail) and bool(fact_trail[0].get("top_candidates")), fact_trail)

    report = article.build_report(out)
    check("build_report: يعرض أعلى المرشّحين (اسم/وزن/صلة/درجة) داخل سجلّ trail",
          fact_trail and any(c["name"] in report for c in fact_trail[0]["top_candidates"]),
          report)


def test_evidence_relevance_cap() -> None:
    """RELEVANCE_CAP (تشخيص Issue #373، تعليق الموافقة الخامس عشر، البند 1):
    يحمي فِكستر واحد الشاهدين معًا — لا يجوز أن يُصلَح أحدهما على حساب
    الآخر. الأرقام مأخوذة حرفيًا من التسجيل التشخيصي الحقيقي (top_candidates)
    الذي حسم الفرضية: "تطبيق نبض" (وزن افتراضي 0.6، صلة 4) هزم "برس بي"
    (وزن موثوق 3.0، صلة 1) بدرجة 4.6 مقابل 4.0 — هذا الشاهد يجب أن ينعكس
    بعد الإصلاح. شاهد #132 (مرشّح شديد الصلة بوزن افتراضي، ضد خمسة موثوقين
    بلا أي صلة) يجب أن يبقى صحيحًا كما كان — لا يُضحَّى به لإصلاح الأول."""
    cfg = load_config()

    # الشاهد اليوم: مصدر افتراضي الوزن بصلة معتدلة (4) يجب ألا يهزم موثوقًا
    # بصلة ضعيفة (1) بعد القص — قبل الإصلاح كان 0.6+4=4.6 يهزم 3.0+1=4.0
    check("_candidate_score: مصدر افتراضي الوزن بصلة=4 لا يهزم موثوقًا بصلة=1 "
          "بعد سقف RELEVANCE_CAP (الشاهد الحقيقي: نبض 0.6/4 ضد برس بي 3.0/1)",
          evidence._candidate_score(evidence.DEFAULT_PUBLISHER_WEIGHT, 4) <
          evidence._candidate_score(evidence.TRUSTED_PUBLISHER_WEIGHT, 1))

    # شاهد #132: مصدر افتراضي الوزن بصلة شديدة الارتفاع (تُقصّ لكنها تبقى
    # عالية) يجب أن يبقى قادرًا على هزيمة موثوق بلا أي صلة إطلاقًا — وإلا
    # عاد عطل #132 الأصلي (مرشّح شديد الصلة يُقصى كليًا) من زاوية القص نفسه
    check("_candidate_score: مصدر افتراضي الوزن بصلة شديدة الارتفاع (6) يبقى "
          "يهزم موثوقًا بصلة صفر (شاهد #132: لا إقصاء كليًا لمرشّح شديد الصلة)",
          evidence._candidate_score(evidence.DEFAULT_PUBLISHER_WEIGHT, 6) >
          evidence._candidate_score(evidence.TRUSTED_PUBLISHER_WEIGHT, 0))

    check("RELEVANCE_CAP: يقع داخل النافذة الصالحة المشتقة من الشاهدين معًا (2.4, 3.4]",
          2.4 < evidence.RELEVANCE_CAP <= 3.4, evidence.RELEVANCE_CAP)

    # تكامل كامل عبر gather_evidence بأرقام التسجيل التشخيصي الحرفية —
    # لا حساب صيغة مباشر وحده، بل المسار الفعلي (candidates → فرز → قراءة)
    nabd = Article(title="تطبيق نبض يهزّ الأوساط الرياضية اليوم بمفاجأة",
                  link="https://nabd.example/1", summary="", source_name="تطبيق نبض",
                  region="global", weight=1.0, published=datetime.now(timezone.utc),
                  publisher="تطبيق نبض")
    press_b = Article(title="برس بي ينشر تفاصيل إضافية عن القضية",
                      link="https://pressb.example/1", summary="", source_name="Bloomberg",
                      region="global", weight=1.0, published=datetime.now(timezone.utc),
                      publisher="Bloomberg")

    real_extract_gather = extract.gather
    read_order: list[str] = []

    def _fake_gather(members, limit=1):
        read_order.extend(m["name"] for m in members)
        return [], []

    # claim_text يُبنى بحيث "نبض" يشارك 4 كلمات مطابقة حرفيًا مع عنوان نبض،
    # وBloomberg يشارك كلمة واحدة فقط مع عنوانه هو — يطابق أرقام التشخيص
    # الحقيقي (صلة=4 مقابل صلة=1) بلا حاجة لحساب norm_tokens يدويًا؛ نتحقق
    # من الصلة الفعلية بعد الحساب لضمان الأرقام صحيحة قبل قراءة النتيجة
    claim_text = "تطبيق نبض يهزّ الأوساط الرياضية اليوم بمفاجأة برس بي القضية"
    rel_nabd = evidence._relevance(nabd, evidence.norm_tokens(claim_text))
    rel_press = evidence._relevance(press_b, evidence.norm_tokens(claim_text))
    check("فِكستر الصلة: نبض يشارك أكثر من كلمة واحدة، برس بي أقل — يعكس "
          "شكل الشاهد الحقيقي (نسبيًا، لا الأرقام الحرفية بالضرورة)",
          rel_nabd > rel_press >= 0, (rel_nabd, rel_press))

    narrow_cfg = dict(cfg)
    narrow_cfg["verify"] = {**cfg["verify"], "read_per_claim": 1}
    extract.gather = _fake_gather
    try:
        evidence.gather_evidence([nabd, press_b], narrow_cfg, claim_text)
    finally:
        extract.gather = real_extract_gather

    check("gather_evidence: موثوق (Bloomberg) يُقرأ أولًا رغم صلة لفظية أعلى "
          "لمصدر افتراضي الوزن — بعد سقف RELEVANCE_CAP",
          read_order and read_order[0] == "Bloomberg", read_order)

    # فاصل التعادل التام بالوزن (البند 1، الطلب الثاني): _candidate_sort_key
    # دالّة مستقلة قابلة للاختبار بمعزل عن machinery gather_evidence كاملة —
    # عند تعادل الدرجة المركّبة تمامًا (شائع بعد القص: عدة مرشحين افتراضيي
    # الوزن يبلغون RELEVANCE_CAP معًا) الوزن الأعلى يتصدّر، لا ترتيب الوصول
    default_tied = (evidence.DEFAULT_PUBLISHER_WEIGHT, 10)   # صلة تتجاوز السقف بكثير
    trusted_tied = (evidence.TRUSTED_PUBLISHER_WEIGHT,
                    evidence.RELEVANCE_CAP - evidence.TRUSTED_PUBLISHER_WEIGHT +
                    evidence.DEFAULT_PUBLISHER_WEIGHT)  # يُنتج نفس الدرجة المركّبة تمامًا
    check("فِكستر التعادل: افتراضي بصلة مقصوصة يساوي موثوقًا بصلة مضبوطة تمامًا "
          "(شرط الاختبار قبل فحص الفرز)",
          abs(evidence._candidate_score(*default_tied) -
             evidence._candidate_score(*trusted_tied)) < 1e-9,
          (evidence._candidate_score(*default_tied), evidence._candidate_score(*trusted_tied)))
    tie_candidates = [("موقع مجهول", *default_tied), ("Reuters", *trusted_tied)]
    sorted_tie = sorted(tie_candidates,
                        key=lambda c: evidence._candidate_sort_key(c[1], c[2]))
    check("_candidate_sort_key: عند تعادل الدرجة المركّبة تمامًا، الوزن الأعلى "
          "(Reuters) يتصدّر لا ترتيب الوصول الموروث",
          sorted_tie[0][0] == "Reuters", sorted_tie)


def test_evidence_relevance_display_matches_score() -> None:
    """الرقم المعروض في trail يجب أن يطابق المستعمل في الترتيب (تشخيص Issue
    #373، تعليق العطل العشرون، البند 2): top_candidates كانت تعرض "relevance"
    الخام قبل قصّها عند RELEVANCE_CAP، بينما "score" تُحسب من القيمة
    المقصوصة — فوزن=0.6 صلة=4 كانا يظهران مع درجة=3.6 (لا 4.6 كما يحسب
    القارئ يدويًا)، رغم أن الحساب نفسه صحيح والعرض هو المضلِّل.
    "relevance_used" الجديد هو ما يدخل الجمع فعليًا، ويبقى وزن+relevance_used
    == score دومًا."""
    from src import article

    # ── _capped_relevance: وحدة الحساب المشتركة بين _candidate_score
    # والعرض في top_candidates — قيمة واحدة لا حسابين قد ينفصلان ──
    check("_capped_relevance: صلة دون السقف تمر بلا تغيير", evidence._capped_relevance(2) == 2)
    check("_capped_relevance: صلة تساوي السقف تمامًا تمر بلا تغيير",
          evidence._capped_relevance(int(evidence.RELEVANCE_CAP)) == int(evidence.RELEVANCE_CAP))
    check("_capped_relevance: صلة=4 تُقصّ إلى RELEVANCE_CAP (الشاهد الحقيقي المُبلَّغ)",
          evidence._capped_relevance(4) == int(evidence.RELEVANCE_CAP))

    # ── top_candidates: relevance_used موجود، ووزن + relevance_used == score
    # فعليًا عبر gather_evidence الحقيقية، لمرشّح تتجاوز صلته الخام السقف ──
    generic = Article(title="روبيرتو كارلوس الإسلام خبر رياضي مطابق لفظيًا حرفيًا للاستعلام كاملًا",
                      link="https://generic.example/2", summary="", source_name="موقع مجهول",
                      region="global", weight=1.0, published=datetime.now(timezone.utc),
                      publisher="موقع مجهول")
    cfg = load_config()
    real_extract_gather = extract.gather
    extract.gather = lambda members, limit=3: ([], [])
    try:
        docs, _basis = evidence.gather_evidence([generic], cfg,
                                                 "روبيرتو كارلوس الإسلام خبر رياضي مطابق")
    finally:
        extract.gather = real_extract_gather
    top = getattr(docs, "top_candidates", [])
    check("top_candidates: relevance_used موجود في كل عنصر", top and
          all("relevance_used" in c for c in top), top)
    check("top_candidates: relevance_used == _capped_relevance(relevance) لكل مرشّح",
          all(c["relevance_used"] == evidence._capped_relevance(c["relevance"]) for c in top), top)
    check("top_candidates: وزن + relevance_used == score دومًا — لا فارق راصد كما كان "
          "(الشاهد المُبلَّغ: وزن=0.6 صلة=4 درجة=3.6 كان يبدو مجموعه 4.6 لا 3.6)",
          all(abs(c["weight"] + c["relevance_used"] - c["score"]) < 1e-6 for c in top), top)

    # ── build_report: يعرض relevance_used (لا relevance الخام وحده) مع
    # ذكر الخام بين قوسين فقط حين يختلفان — الشفافية الكاملة بلا تضليل ──
    mismatched = [{"name": "تطبيق نبض", "weight": 0.6, "relevance": 4,
                  "relevance_used": 3, "score": 3.6}]
    matched = [{"name": "برس بي", "weight": 3.0, "relevance": 1,
               "relevance_used": 1, "score": 4.0}]
    out = {"produced": False, "reason": "اختبار", "trail": [
        {"stage": "واقعة", "query": "استعلام اختبار", "basis": evidence.EVIDENCE_FULL_TEXT,
         "sources": ["تطبيق نبض", "برس بي"], "outcome": "اختبار",
         "top_candidates": mismatched + matched},
    ]}
    report = article.build_report(out)
    check("build_report: صلة المرشّح المقصوص تُعرض 3 (المُستعمَلة فعليًا) لا 4 "
          "(الخام) وحدها، مع ذكر الخام بين قوسين للشفافية",
          "صلة=3 (خام 4)" in report and "درجة=3.6" in report, report)
    check("build_report: لا يظهر التركيب المضلِّل القديم (صلة=4 مع درجة=3.6 بلا "
          "أي إشارة أن الصلة قُصَّت)",
          "صلة=4 درجة=" not in report, report)
    check("build_report: مرشّح لا فارق فيه بين الخام والمُستعمَل يُعرض رقمًا واحدًا "
          "بلا قوسين",
          "صلة=1 درجة=4.0" in report and "صلة=1 (خام" not in report, report)


def test_article_duplicate_query_reuse() -> None:
    """ذاكرة استعلامات هذا التشغيل لحلقة الوقائع (تشخيص Issue #373، تعليق
    العطل العشرون، البند 1): شاهد فعلي — ثلاث وقائع تشترك في نفس الكيانات
    (موجز يدور حول شخص واحد) بنت نفس الاستعلام حرفيًا في trail ثلاث مرات،
    كل مرة ببحث وقراءة مستقلَّين رغم تطابق النتائج والمصادر حرفيًا في كل
    مرة. التحقق: evidence.search/gather_evidence يُستدعيان مرة واحدة فقط
    لثلاث وقائع تشترك في الاستعلام نفسه، بينما _support_sources تبقى تُستدعى
    لكل واقعة بنصها بمعزل عن التخزين المؤقَّت — الحكم على السند لا يُشارَك،
    الوثائق المقروءة وحدها تُشارَك."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False

    shared_entities = ["سهيلة الطاهري", "روبرتو كارلوس"]
    fact_texts = [f"واقعة رقم {i} عن سهيلة الطاهري وروبرتو كارلوس" for i in range(1, 4)]

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources

    search_calls: list = []
    gather_calls: list = []
    support_calls: list = []

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار إعادة استعمال الاستعلام",
        "statements": [
            {"text": t, "kind": "واقعة", "entities": shared_entities,
             "is_unnamed_event": False, "is_reference": False}
            for t in fact_texts
        ],
        "questions": [],
    }, None)

    def _fake_search(query, cfg, days, unrestricted=False):
        search_calls.append(query)
        return [object()]

    def _fake_gather(articles, cfg, claim_text=""):
        gather_calls.append(claim_text)
        return ([{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"},
                  {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1"}],
                evidence.EVIDENCE_FULL_TEXT)

    def _fake_support(fact_text, docs, cfg, is_statement=False, is_report=False, publisher=""):
        support_calls.append(fact_text)
        return []  # بلا سند — يكفي لاختبار التخزين المؤقَّت بلا حاجة لتشغيل الصياغة كاملة

    evidence.search = _fake_search
    evidence.gather_evidence = _fake_gather
    article._support_sources = _fake_support

    try:
        out = article._write_article("موجز اختبار إعادة استعمال الاستعلام", 9005, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources

    check("إعادة استعمال الاستعلام: evidence.search استُدعيت مرة واحدة فقط لثلاث "
          "وقائع تشترك في نفس الاستعلام (لا ثلاث مرات كالشاهد المُبلَّغ)",
          len(search_calls) == 1, search_calls)
    check("إعادة استعمال الاستعلام: evidence.gather_evidence استُدعيت مرة واحدة فقط",
          len(gather_calls) == 1, gather_calls)
    check("إعادة استعمال الاستعلام: _support_sources تُستدعى لكل واقعة بنصها الخاص — "
          "الحكم على السند يبقى مستقلًا رغم مشاركة الوثائق",
          support_calls == fact_texts, support_calls)

    fact_trail = [t for t in out["trail"] if t["stage"] == "واقعة"]
    check("trail: ثلاثة أسطر — واحد لكل واقعة — بلا حذف أي سطر رغم إعادة الاستعمال "
          "(الشفافية أهم من اختصار السجل)",
          len(fact_trail) == 3, fact_trail)
    check("trail: الاستعلام نفسه حرفيًا في الأسطر الثلاثة",
          len({t["query"] for t in fact_trail}) == 1, fact_trail)
    check("trail: السطر الأول غير مُعاد (بحث فعلي أول مرة)",
          fact_trail[0].get("reused_query") is False, fact_trail[0])
    check("trail: السطران الثاني والثالث مُعادان من استعلام سابق (reused_query=True)",
          fact_trail[1].get("reused_query") is True and
          fact_trail[2].get("reused_query") is True, fact_trail)
    check("trail: outcome السطرين المُعادين يذكر صراحة أنهما مُعادان — لا حذف السطر، "
          "الشفافية أهم من اختصار السجل",
          "🔁 مُعاد من استعلام سابق" in fact_trail[1]["outcome"] and
          "🔁 مُعاد من استعلام سابق" in fact_trail[2]["outcome"], fact_trail)
    check("trail: السطر الأول لا يحمل علامة إعادة في نص outcome",
          "🔁 مُعاد من استعلام سابق" not in fact_trail[0]["outcome"], fact_trail[0])

    report = article.build_report(out)
    check("build_report: علامة الإعادة تظهر فعليًا في التقرير المُصيَّر",
          "🔁 مُعاد من استعلام سابق" in report, report)


def test_article_longest_shared_run() -> None:
    """_longest_shared_run (طلب المراجعة، أولوية — تشخيص Issue #373، تعليق
    العطل الحادي والعشرون، البند 1): تتابع كلمات متجاور فعلي، لا تشابه
    كيسي/Jaccard — يعيد 0 حين تشترك كل الكلمات لكن بترتيب مختلف، والطول
    الفعلي (لا الحد الأدنى المطلوب فقط) حين يتجاوزه التتابع الفعلي."""
    from src import article

    a = "كلمة1 كلمة2 كلمة3 كلمة4 كلمة5".split()
    b = "كلمة5 كلمة4 كلمة3 كلمة2 كلمة1".split()
    check("_longest_shared_run: كل الكلمات مشتركة بترتيب معكوس ← 0 (لا تشابه كيسي)",
          article._longest_shared_run(a, b, 3) == 0)

    passage = [f"كلمة{i}" for i in range(1, 51)]  # 50 كلمة متجاورة
    a2 = ["مقدمة", "مختلفة"] + passage + ["خاتمة", "أخرى"]
    b2 = ["بداية", "غير", "هذه"] + passage + ["نهاية", "مغايرة", "هنا"]
    check("_longest_shared_run: يعيد الطول الفعلي (50) لا الحد الأدنى المطلوب (30) وحده",
          article._longest_shared_run(a2, b2, 30) == 50,
          article._longest_shared_run(a2, b2, 30))

    part1 = [f"أ{i}" for i in range(1, 16)]   # 15 كلمة مشتركة
    part2a = [f"ب{i}" for i in range(1, 16)]  # 15 كلمة تخص a فقط
    part2b = [f"ج{i}" for i in range(1, 16)]  # 15 كلمة تخص b فقط
    a3, b3 = part1 + part2a, part1 + part2b
    check("_longest_shared_run: تتابع مشترك فعلي (15) دون الحد الأدنى المطلوب (30) ← 0",
          article._longest_shared_run(a3, b3, 30) == 0)
    check("_longest_shared_run: نفس التتابع بحد أدنى مطابق (15) يعيد طوله الفعلي",
          article._longest_shared_run(a3, b3, 15) == 15)


def test_article_reprint_exclusion() -> None:
    """استبعاد إعادات نشر الموجز الملصق قبل حساب استقلالية المصادر (طلب
    المراجعة، أولوية — تشخيص Issue #373، تعليق العطل الحادي والعشرون،
    البند 1): وثيقة قُرئت خلال البحث تشارك الموجز الملصق تتابعًا متجاورًا
    ≥ article.brief_reprint_min_shared_words كلمة تُستبعد كليًا من
    _cached_search — نصٌّ واحد لا يبدو مصدرين. الاستبعاد ظاهر في trail بعدد
    الكلمات المشتركة الفعلي، ورسالة سقوط الواقعة تميّزه صراحة عن الرسالة
    العامة (البند 3: بلا هذا التمييز يبدو عطل بحث لا استبعادًا صحيحًا)."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False
    passage = " ".join(f"كلمة{i}" for i in range(1, 51))  # 50 كلمة متجاورة (≥ 40)
    body = f"مقدمة الموجز. {passage}. خاتمة الموجز الملصق هنا للاختبار الكامل."
    reprint_text = f"نقلاً عن الموجز الأصلي: {passage}. انتهى النقل الحرفي هنا."
    genuine_text = ("نص مستقل تمامًا لا علاقة له بالموجز الملصق إطلاقًا، يتحدث عن "
                    "موضوع آخر بالكامل من مصدر حقيقي منفصل.")

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources

    article.extract_brief = lambda b, cfg, retries=3: ({
        "topic": "اختبار استبعاد إعادة النشر",
        "statements": [
            {"text": "واقعة اختبار الاستبعاد", "kind": "واقعة",
             "entities": ["كيان اختبار"], "is_unnamed_event": False,
             "is_reference": False},
        ],
        "questions": [],
    }, None)
    evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": "ناشر معيد نشر", "text": reprint_text, "link": "https://reprint/1"},
         {"name": "ناشر مستقل", "text": genuine_text, "link": "https://genuine/1"}],
        evidence.EVIDENCE_FULL_TEXT)
    article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
        is_report=False, publisher="": [d["name"] for d in docs]

    try:
        out = article._write_article(body, 9006, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources

    fact_trail = [t for t in out["trail"] if t["stage"] == "واقعة"]
    check("استبعاد إعادة النشر: سطر trail واحد للواقعة الوحيدة", len(fact_trail) == 1, fact_trail)
    excluded = fact_trail[0].get("excluded_reprints") or []
    check("استبعاد إعادة النشر: الوثيقة المعيدة نشر الموجز استُبعدت (لا المصدر المستقل)",
          len(excluded) == 1 and excluded[0]["name"] == "ناشر معيد نشر", excluded)
    check("استبعاد إعادة النشر: عدد الكلمات المشتركة الفعلي ≥ الحد الأدنى (50 ≥ 40)",
          excluded[0]["shared_words"] >= 40, excluded)
    check("استبعاد إعادة النشر: المصدر المستقل بقي ضمن الوثائق المستخدمة فعليًا "
          "— المعيد نشره غاب عنها",
          "ناشر مستقل" in fact_trail[0]["sources"] and
          "ناشر معيد نشر" not in fact_trail[0]["sources"], fact_trail[0])
    check("استبعاد إعادة النشر: outcome نص trail يُعلِم صراحة بعدد الوثائق المستبعدة",
          "🗞️ استُبعدت" in fact_trail[0]["outcome"], fact_trail[0]["outcome"])

    check("استبعاد إعادة النشر: الواقعة سقطت (مصدر مستقل واحد فقط بعد الاستبعاد دون العتبة)",
          len(out["dropped"]) == 1, out["dropped"])
    drop_reason = out["dropped"][0]["reason"]
    check("البند 3: رسالة السقوط تميّز صراحة أن السبب استبعاد إعادات نشر — لا "
          "الرسالة العامة (وإلا يُظَنّ عطل بحث كما ظُنّ مرارًا في هذا الـ Issue)",
          "سند غير كافٍ بعد استبعاد إعادات نشر الموجز" in drop_reason, drop_reason)

    report = article.build_report(out)
    check("build_report: يعرض سطر الاستبعاد باسم الناشر وعدد الكلمات المشتركة",
          "استُبعدت كإعادة نشر حرفية للموجز الملصق" in report and
          "ناشر معيد نشر" in report, report)


def test_article_reprint_image_fallback() -> None:
    """صورة من مصدر استُبعد كإعادة نشر تبقى مرشَّحًا صالحًا للصورة (طلب
    المراجعة، مراجعة بشرية بعد أول نشر، البند 1): الاستبعاد يخصّ عدّ
    السند لا صلاحية الصورة. تكامل كامل عبر _write_article — لا اختبار
    الدوال المساعدة (_reprint_fallback_images/_pool_image_candidates) بمعزل
    عن الأنبوب الفعلي وحدها، فتُثبَت أن الوصل بينها وبين الحلقة الرئيسية
    (reprint_image_pool، اختيار image_ranked، image_pool_source) يعمل."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False
    passage = " ".join(f"كلمة{i}" for i in range(1, 51))  # ≥ 40 كلمة متجاورة
    body = f"مقدمة الموجز. {passage}. خاتمة الموجز الملصق هنا للاختبار الكامل."
    reprint_text = f"نقلاً عن الموجز الأصلي: {passage}. انتهى النقل الحرفي هنا."
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    reprint_article = Article(
        title="ت", link="https://reprint/1", summary="", source_name="ناشر معيد نشر",
        region="global", weight=1.0, published=now, publisher="ناشر معيد نشر",
        image_candidates=["https://aj/img.jpg"])
    indep_a = Article(
        title="ت", link="https://a/1", summary="", source_name="مصدر أ",
        region="global", weight=1.0, published=now, publisher="مصدر أ")
    indep_b = Article(
        title="ت", link="https://b/1", summary="", source_name="مصدر ب",
        region="global", weight=1.0, published=now, publisher="مصدر ب")

    real = {"extract_brief": article.extract_brief, "search": evidence.search,
           "gather_evidence": evidence.gather_evidence,
           "support_sources": article._support_sources,
           "choose_question": article._choose_question,
           "draft_article": article._draft_article,
           "find_images": article.find_images}

    article.extract_brief = lambda b, cfg, retries=3: ({
        "topic": "اختبار احتياط صورة الاستبعاد",
        "statements": [
            {"text": "الحدث الأول وقع بالفعل", "kind": "واقعة",
             "entities": ["كيان أول"], "is_unnamed_event": False, "is_reference": False},
            {"text": "الحدث الثاني وقع بالفعل أيضًا", "kind": "واقعة",
             "entities": ["كيان ثانٍ"], "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    evidence.search = lambda query, cfg, days, unrestricted=False: [
        reprint_article, indep_a, indep_b]
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": "ناشر معيد نشر", "text": reprint_text, "link": "https://reprint/1"},
         {"name": "مصدر أ", "text": "نص مستقل تمامًا عن المصدر أ لا علاقة له بالموجز.",
          "link": "https://a/1"},
         {"name": "مصدر ب", "text": "نص مستقل تمامًا عن المصدر ب لا علاقة له بالموجز.",
          "link": "https://b/1"}],
        evidence.EVIDENCE_FULL_TEXT)
    article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
        is_report=False, publisher="": [d["name"] for d in docs]
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار الاحتياط؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "خبر", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن مُعاد صياغته بالكامل بلا أي تشابه لفظي مع أي مصدر هنا.",
         "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []

    try:
        out = article._write_article(body, 9009, cfg)
    finally:
        article.extract_brief = real["extract_brief"]
        evidence.search = real["search"]
        evidence.gather_evidence = real["gather_evidence"]
        article._support_sources = real["support_sources"]
        article._choose_question = real["choose_question"]
        article._draft_article = real["draft_article"]
        article.find_images = real["find_images"]

    check("احتياط صورة الاستبعاد: المقال يُنتَج فعلًا", out["produced"] is True, out["reason"])
    ir = out["image_report"]
    check("احتياط صورة الاستبعاد: image_pool_source=excluded_reprint (كلا المصدرين "
          "المسندين بلا image_candidates أصلًا — لا بديل إلا مجمّع الاستبعاد)",
          ir.get("image_pool_source") == "excluded_reprint", ir)
    check("احتياط صورة الاستبعاد: outcome['image_source_name'] يعزو الصورة للناشر "
          "المستبعد الصحيح (chosen_url لا image_ranked[0] الافتراضي)",
          out.get("image_source_name") == "ناشر معيد نشر", out)

    report = article.build_report(out)
    check("build_report: يذكر صراحة أن الصورة من مصدر مُستبعد لا دليل إسناد",
          "استُبعد من عدّ الاستقلالية" in report and "ليس دليل إسناد" in report, report)


def test_article_originality_retry() -> None:
    """محاولة صياغة ثانية واحدة عند رفض فحص الأصالة (طلب المراجعة، تشخيص
    Issue #373، تعليق العطل الحادي والعشرون، البند 2): المسودة الأولى قد
    تنسخ تتابعًا حرفيًا من مقتطف مصدر مسنَد — الفحص يعرف الآن الجملة
    المخالفة بعينها (offending) فتُمرَّر توجيهًا صريحًا لمحاولة ثانية.
    نجاح الثانية ينتج المقال، وفشلها امتناع نهائي برسالة مميَّزة."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False
    offending_run = "شهد الخبراء تطورا مفاجئا خطيرا جدا الليلة"
    fixed_docs = [
        {"name": "مصدر رئيسي", "text": f"تقرير: {offending_run} في العاصمة.",
         "link": "https://main/1"},
        {"name": "مصدر ثانٍ", "text": "نص عام يؤيد الوقائع بلا أي عبارة خاصة هنا إطلاقًا.",
         "link": "https://g1/1"},
        {"name": "مصدر ثالث", "text": "نص عام آخر يؤيد الوقائع أيضًا بصياغة مختلفة تمامًا هنا.",
         "link": "https://g2/1"},
    ]

    def _setup(second_body: str):
        real = {"extract_brief": article.extract_brief, "search": evidence.search,
               "gather_evidence": evidence.gather_evidence,
               "support_sources": article._support_sources,
               "choose_question": article._choose_question,
               "draft_article": article._draft_article,
               "find_images": article.find_images}
        article.extract_brief = lambda b, cfg, retries=3: ({
            "topic": "اختبار محاولة الصياغة الثانية",
            "statements": [
                {"text": "الحدث الأول وقع بالفعل", "kind": "واقعة",
                 "entities": ["كيان أول"], "is_unnamed_event": False,
                 "is_reference": False},
                {"text": "الحدث الثاني وقع بالفعل أيضًا", "kind": "واقعة",
                 "entities": ["كيان ثانٍ"], "is_unnamed_event": False,
                 "is_reference": False},
            ],
            "questions": [],
        }, None)
        evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
        evidence.gather_evidence = lambda articles, cfg, claim_text="": (
            list(fixed_docs), evidence.EVIDENCE_FULL_TEXT)
        article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
            is_report=False, publisher="": [d["name"] for d in docs]
        article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار الاستعادة؟", "")

        draft_calls: list = []

        def _fake_draft(grounded, opinions, question, cfg, retries=3, avoid_note=""):
            draft_calls.append(avoid_note)
            body_text = (f"حدث مهم جدًا: {offending_run} كما أكدت المصادر."
                        if len(draft_calls) == 1 else second_body)
            return ({"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
                    "image_headline": "عنوان", "post_title": question,
                    "post_body": body_text, "hashtags": ["اختبار"]}, "")

        article._draft_article = _fake_draft
        article.find_images = lambda title, cfg, terms=None: []
        return real, draft_calls

    def _teardown(real):
        article.extract_brief = real["extract_brief"]
        evidence.search = real["search"]
        evidence.gather_evidence = real["gather_evidence"]
        article._support_sources = real["support_sources"]
        article._choose_question = real["choose_question"]
        article._draft_article = real["draft_article"]
        article.find_images = real["find_images"]

    # ── سيناريو النجاح: المحاولة الثانية بلا أي تشابه لفظي ──
    real1, draft_calls1 = _setup(
        "متن مُعاد صياغته بالكامل بلا أي تشابه لفظي مع أي مصدر مطلقًا هنا.")
    try:
        out_ok = article._write_article("موجز اختبار محاولة الصياغة الثانية", 9007, cfg)
    finally:
        _teardown(real1)

    check("محاولة ثانية ناجحة: استُدعيت _draft_article مرتين فقط",
          len(draft_calls1) == 2, draft_calls1)
    check("محاولة ثانية ناجحة: المحاولة الأولى بلا توجيه تفادٍ (avoid_note فارغ)",
          draft_calls1[0] == "", draft_calls1)
    check("محاولة ثانية ناجحة: المحاولة الثانية مُرِّر إليها توجيه غير فارغ يذكر "
          "الجملة المخالفة بعينها",
          bool(draft_calls1[1]) and offending_run.split()[0] in draft_calls1[1],
          draft_calls1)
    check("محاولة ثانية ناجحة: outcome['originality_retry'] يسجّل المحاولة والنجاح",
          out_ok["originality_retry"]["attempted"] is True and
          out_ok["originality_retry"]["succeeded"] is True, out_ok["originality_retry"])
    check("محاولة ثانية ناجحة: المقال يُنتَج فعلًا بالمسودة الثانية",
          out_ok["produced"] is True, out_ok["reason"])

    report_ok = article.build_report(out_ok)
    check("build_report: يعرض نجاح محاولة الصياغة الثانية صراحة",
          "محاولة صياغة ثانية" in report_ok and "✅ نجحت" in report_ok, report_ok)

    # ── سيناريو الفشل: المحاولة الثانية تكرر نفس النسخ اللفظي ──
    real2, draft_calls2 = _setup(f"حدث آخر أيضًا: {offending_run} كما أكدت المصادر.")
    try:
        out_bad = article._write_article("موجز اختبار محاولة الصياغة الثانية", 9008, cfg)
    finally:
        _teardown(real2)

    check("محاولة ثانية فاشلة: استُدعيت _draft_article مرتين فقط — لا محاولة ثالثة "
          "مهما كانت النتيجة",
          len(draft_calls2) == 2, draft_calls2)
    check("محاولة ثانية فاشلة: outcome['originality_retry'] يسجّل المحاولة بلا نجاح",
          out_bad["originality_retry"]["attempted"] is True and
          out_bad["originality_retry"]["succeeded"] is False, out_bad["originality_retry"])
    check("محاولة ثانية فاشلة: امتناع نهائي — لا أسوأ من رفض بلا محاولة إطلاقًا",
          out_bad["produced"] is False and "امتناع" in out_bad["reason"], out_bad["reason"])
    check("محاولة ثانية فاشلة: رسالة الامتناع تميّز أنها بعد محاولة ثانية فشلت أيضًا",
          "فشلت المحاولة الثانية" in out_bad["reason"], out_bad["reason"])

    report_bad = article.build_report(out_bad)
    check("build_report: يعرض فشل محاولة الصياغة الثانية صراحة",
          "محاولة صياغة ثانية" in report_bad and "❌ فشلت أيضًا" in report_bad, report_bad)


def test_article_jargon_leak() -> None:
    """تسرّب مصطلحات بنية النظام إلى المتن (طلب المراجعة، تشخيص Issue #373،
    تعليق العطل الثالث والعشرون): متن نُشر فعليًا انتهى بـ"بهذا تكون الوقائع
    المسندة قد أجابت..." — النموذج يتحدث عن آليته الداخلية للقارئ. القاعدة 11
    في DRAFT_SYSTEM_TEMPLATE توجيه فقط؛ هذا فحص بنيوي لاحق بنفس آلية إعادة
    المحاولة القائمة أصلًا لفحص الأصالة (avoid_note/محاولة واحدة/امتناع عند
    التكرار)، لا برومبتًا وحده."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False

    # ── وحدة: _system_jargon_hits/_normalize_phrase ──
    check("_system_jargon_hits: يرصد المصطلح رغم اختلاف التشكيل والهمزة",
          "الوقائع المسندة" in article._system_jargon_hits("الوقائعُ المسنَدة قد أجابت"),
          article._system_jargon_hits("الوقائعُ المسنَدة قد أجابت"))
    check("_system_jargon_hits: نص إخباري عادي بلا أي مصطلح ← قائمة فارغة",
          article._system_jargon_hits("أعلنت الوزارة ارتفاع الإنتاج خمسة بالمئة") == [],
          article._system_jargon_hits("أعلنت الوزارة ارتفاع الإنتاج خمسة بالمئة"))
    check("_system_jargon_hits: يرصد أكثر من مصطلح في نفس النص",
          {"بوابة الاتساق", "فحص الأصالة"} <= set(
              article._system_jargon_hits("اجتازت بوابة الاتساق ثم فحص الأصالة بنجاح")),
          article._system_jargon_hits("اجتازت بوابة الاتساق ثم فحص الأصالة بنجاح"))

    # ── القاعدتان 11 و12 في DRAFT_SYSTEM_TEMPLATE ──
    check("القاعدة 11: لا إشارة لآلية الإنتاج/مصطلحات النظام في المتن",
          "مصطلحات بنية المشروع الداخلية" in article.DRAFT_SYSTEM_TEMPLATE,
          article.DRAFT_SYSTEM_TEMPLATE)
    check("القاعدة 12: لا فقرة ختامية تلخيصية — المتن ينتهي بآخر واقعة",
          "لا فقرة ختامية" in article.DRAFT_SYSTEM_TEMPLATE, article.DRAFT_SYSTEM_TEMPLATE)

    # ── تكامل كامل عبر _write_article ──
    fixed_docs = [
        {"name": "مصدر رئيسي", "text": "تقرير إخباري عادي بلا أي عبارة خاصة هنا.",
         "link": "https://main/1"},
        {"name": "مصدر ثانٍ", "text": "نص عام يؤيد الوقائع بصياغة أخرى تمامًا هنا.",
         "link": "https://g1/1"},
    ]

    def _setup(first_body: str, second_body: str = ""):
        real = {"extract_brief": article.extract_brief, "search": evidence.search,
               "gather_evidence": evidence.gather_evidence,
               "support_sources": article._support_sources,
               "choose_question": article._choose_question,
               "draft_article": article._draft_article,
               "find_images": article.find_images}
        article.extract_brief = lambda b, cfg, retries=3: ({
            "topic": "اختبار تسرّب مصطلحات النظام",
            "statements": [
                {"text": "الحدث الأول وقع بالفعل هنا", "kind": "واقعة",
                 "entities": ["كيان أول"], "is_unnamed_event": False,
                 "is_reference": False},
                {"text": "الحدث الثاني وقع بالفعل أيضًا هنا", "kind": "واقعة",
                 "entities": ["كيان ثانٍ"], "is_unnamed_event": False,
                 "is_reference": False},
            ],
            "questions": [],
        }, None)
        evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
        evidence.gather_evidence = lambda articles, cfg, claim_text="": (
            list(fixed_docs), evidence.EVIDENCE_FULL_TEXT)
        article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
            is_report=False, publisher="": [d["name"] for d in docs]
        article._choose_question = lambda grounded, cfg, retries=2: (
            "سؤال اختبار المصطلحات؟", "")

        draft_calls: list = []

        def _fake_draft(grounded, opinions, question, cfg, retries=3, avoid_note=""):
            draft_calls.append(avoid_note)
            body_text = first_body if len(draft_calls) == 1 else second_body
            return ({"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
                    "image_headline": "عنوان", "post_title": question,
                    "post_body": body_text, "hashtags": ["اختبار"]}, "")

        article._draft_article = _fake_draft
        article.find_images = lambda title, cfg, terms=None: []
        return real, draft_calls

    def _teardown(real):
        article.extract_brief = real["extract_brief"]
        evidence.search = real["search"]
        evidence.gather_evidence = real["gather_evidence"]
        article._support_sources = real["support_sources"]
        article._choose_question = real["choose_question"]
        article._draft_article = real["draft_article"]
        article.find_images = real["find_images"]

    # ── سيناريو النجاح: المصطلح يُرصَد أول مرة، المحاولة الثانية نظيفة وتجتاز
    # فحص الأصالة أيضًا (نصّ مُولَّد من الصفر لا امتداد للأول) ──
    real1, draft_calls1 = _setup(
        "بهذا تكون الوقائع المسندة قد أجابت بوضوح عن السؤال المطروح هنا.",
        "متن نظيف تمامًا يجيب عن السؤال بلا أي إشارة لآلية الإنتاج مطلقًا.")
    try:
        out_ok = article._write_article("موجز اختبار تسرّب المصطلحات", 9201, cfg)
    finally:
        _teardown(real1)

    check("تسرّب مصطلحات — نجاح: استُدعيت _draft_article مرتين فقط",
          len(draft_calls1) == 2, draft_calls1)
    check("تسرّب مصطلحات — نجاح: المحاولة الثانية مُرِّر إليها توجيه يذكر المصطلح المرصود",
          bool(draft_calls1[1]) and "الوقائع المسندة" in draft_calls1[1], draft_calls1)
    check("تسرّب مصطلحات — نجاح: outcome['jargon_retry'] يسجّل الرصد والنجاح",
          out_ok["jargon_retry"]["attempted"] is True and
          out_ok["jargon_retry"]["succeeded"] is True and
          "الوقائع المسندة" in out_ok["jargon_retry"]["detected"] and
          out_ok["jargon_retry"]["remaining"] == [], out_ok["jargon_retry"])
    check("تسرّب مصطلحات — نجاح: المقال يُنتَج فعلًا بالمسودة الثانية",
          out_ok["produced"] is True, out_ok["reason"])

    report_ok = article.build_report(out_ok)
    check("build_report: يعرض نجاح محاولة إسقاط مصطلحات النظام صراحة",
          "تسرّب مصطلحات نظام" in report_ok and "✅ زالت" in report_ok, report_ok)

    # ── سيناريو الفشل: المحاولة الثانية تكرر مصطلح نظام (ولو مختلفًا) ──
    real2, draft_calls2 = _setup(
        "بهذا تكون الوقائع المسندة قد أجابت بوضوح عن السؤال المطروح هنا.",
        "خبر آخر: اعتمدت الصياغة على مصادر مستقلة تؤكد الحدث كاملًا هنا فعلًا.")
    try:
        out_bad = article._write_article("موجز اختبار تسرّب المصطلحات", 9202, cfg)
    finally:
        _teardown(real2)

    check("تسرّب مصطلحات — فشل: استُدعيت _draft_article مرتين فقط — لا محاولة ثالثة "
          "مهما كانت النتيجة",
          len(draft_calls2) == 2, draft_calls2)
    check("تسرّب مصطلحات — فشل: outcome['jargon_retry'] يسجّل الفشل مع المصطلحات المتبقية",
          out_bad["jargon_retry"]["attempted"] is True and
          out_bad["jargon_retry"]["succeeded"] is False and
          out_bad["jargon_retry"]["remaining"] == ["المصادر المستقلة"],
          out_bad["jargon_retry"])
    check("تسرّب مصطلحات — فشل: امتناع نهائي برسالة تذكر تسرّب المصطلحات المتبقية",
          out_bad["produced"] is False and
          "مصطلحات من بنية النظام" in out_bad["reason"] and
          "المصادر المستقلة" in out_bad["reason"], out_bad["reason"])

    report_bad = article.build_report(out_bad)
    check("build_report: يعرض فشل محاولة إسقاط مصطلحات النظام صراحة",
          "تسرّب مصطلحات نظام" in report_bad and "❌ تكررت" in report_bad, report_bad)

    # ── سيناريو بلا تسرّب أصلًا: jargon_retry لا يُحاوَل إطلاقًا — بلا كلفة ──
    real3, draft_calls3 = _setup("متن نظيف تمامًا بلا أي مصطلح نظام إطلاقًا هنا.")
    try:
        out_clean = article._write_article("موجز اختبار تسرّب المصطلحات", 9203, cfg)
    finally:
        _teardown(real3)

    check("لا تسرّب أصلًا: استُدعيت _draft_article مرة واحدة فقط — لا كلفة إضافية",
          len(draft_calls3) == 1, draft_calls3)
    check("لا تسرّب أصلًا: outcome['jargon_retry'] لم تُحاوَل إطلاقًا",
          out_clean["jargon_retry"]["attempted"] is False, out_clean["jargon_retry"])
    check("لا تسرّب أصلًا: المقال يُنتَج فعلًا",
          out_clean["produced"] is True, out_clean["reason"])


def test_article_language_note() -> None:
    """توجيه لغوي موحَّد (طلب المراجعة، Issue #373، حالة موجز تركي
    «بايراكتار» — الحالة الثالثة من هذا النمط): entities تُستخرَج حرفيًا
    فتبني استعلامًا بلغة الموجز الأصلية، فتصل وثائق صحيحة (تركية/إنجليزية)
    فعلًا — لكن النص المحكوم عليه (واقعة/تصريح/تقرير/سؤال/تسمية) عربي
    (مترجَم داخل extract_brief)، فكان حكم السند يخفق رغم صحة المضمون لأن
    البرومبت لا يخبر النموذج أن اختلاف اللغة متوقَّع لا خلل. LANGUAGE_NOTE
    مُضافة الآن للأنظمة الخمسة كلها. المطلوب هنا إثبات وصول التوجيه إلى
    البرومبت الفعلي المُرسَل (لا اختبار فهم النموذج) — عميل مزيَّف يكفي،
    ويعيد "تأييد" كأن النموذج تجاوز اختلاف اللغة فعلًا، فيتحقق الاختبار من
    الأمرين معًا: النتيجة، ووصول LANGUAGE_NOTE إلى system الفعلي."""
    from src import article

    cfg = load_config()

    turkish_docs = [{"name": "Daily Sabah",
                     "text": "Bayraktar stratejimizi net şekilde belirledik dedi.",
                     "link": "https://dailysabah/1"}]

    class _Block:
        def __init__(self, input_):
            self.type = "tool_use"
            self.input = input_

    class _Resp:
        def __init__(self, input_):
            self.content = [_Block(input_)]
            self.stop_reason = "end_turn"

    class _CaptureMessages:
        def __init__(self, input_, captured):
            self._input = input_
            self._captured = captured

        def create(self, **kw):
            self._captured.append(kw)
            return _Resp(self._input)

    class _CaptureClient:
        def __init__(self, input_, captured):
            self.messages = _CaptureMessages(input_, captured)

    real_client_fn = article._client
    calls: list = []

    # ── SUPPORT_SYSTEM (واقعة عادية) ──
    article._client = lambda: _CaptureClient({"supporting": ["Daily Sabah"]}, calls)
    out = article._support_sources("بايراكتار: حددنا استراتيجيتنا بوضوح", turkish_docs, cfg)
    check("SUPPORT_SYSTEM: تأييد رغم اختلاف اللغة (وثائق تركية لواقعة عربية)",
          out == ["Daily Sabah"], out)
    check("SUPPORT_SYSTEM: LANGUAGE_NOTE وصل الـsystem الفعلي المُرسَل للنموذج",
          article.LANGUAGE_NOTE in calls[-1]["system"] and
          calls[-1]["system"] == article.SUPPORT_SYSTEM, calls[-1]["system"])

    # ── STATEMENT_SUPPORT_SYSTEM (تصريح) ──
    article._client = lambda: _CaptureClient({"supporting": ["Daily Sabah"]}, calls)
    out = article._support_sources("بايراكتار: حددنا استراتيجيتنا بوضوح", turkish_docs, cfg,
                                   is_statement=True)
    check("STATEMENT_SUPPORT_SYSTEM: تأييد رغم اختلاف اللغة",
          out == ["Daily Sabah"], out)
    check("STATEMENT_SUPPORT_SYSTEM: LANGUAGE_NOTE وصل الـsystem الفعلي",
          article.LANGUAGE_NOTE in calls[-1]["system"] and
          calls[-1]["system"] == article.STATEMENT_SUPPORT_SYSTEM, calls[-1]["system"])

    # ── REPORT_SUPPORT_SYSTEM (تقرير منقول) — الناشر يطابق اسم الوثيقة
    # فيجتاز شرط الهوية البنيوي (_report_identity_kind) قبل نداء النموذج ──
    article._client = lambda: _CaptureClient({"supporting": ["Daily Sabah"]}, calls)
    out = article._support_sources("بايراكتار: حددنا استراتيجيتنا بوضوح", turkish_docs, cfg,
                                   is_report=True, publisher="Daily Sabah")
    check("REPORT_SUPPORT_SYSTEM: تأييد رغم اختلاف اللغة",
          out == ["Daily Sabah"], out)
    check("REPORT_SUPPORT_SYSTEM: LANGUAGE_NOTE وصل الـsystem الفعلي",
          article.LANGUAGE_NOTE in calls[-1]["system"] and
          calls[-1]["system"] == article.REPORT_SUPPORT_SYSTEM, calls[-1]["system"])

    # ── ANSWER_SYSTEM (سؤال) ──
    article._client = lambda: _CaptureClient(
        {"answered": True, "text": "حدَّد بايراكتار الاستراتيجية بوضوح",
         "supporting": ["Daily Sabah"]}, calls)
    out = article._ask_answer_model("ماذا قال بايراكتار عن الاستراتيجية؟", turkish_docs, cfg)
    check("ANSWER_SYSTEM: تأييد رغم اختلاف اللغة", out is not None and
          out["supporting"] == ["Daily Sabah"], out)
    check("ANSWER_SYSTEM: LANGUAGE_NOTE وصل الـsystem الفعلي",
          article.LANGUAGE_NOTE in calls[-1]["system"] and
          calls[-1]["system"] == article.ANSWER_SYSTEM, calls[-1]["system"])

    # ── NAMING_SYSTEM (تسمية حدث مبهم) ──
    article._client = lambda: _CaptureClient(
        {"named": True, "text": "حدَّد بايراكتار الاستراتيجية التركية بوضوح",
         "supporting": ["Daily Sabah"]}, calls)
    out = article._ask_naming_model("إشارة مبهمة عن بايراكتار", ["بايراكتار"], turkish_docs, cfg)
    check("NAMING_SYSTEM: تأييد رغم اختلاف اللغة", out is not None and
          out["supporting"] == ["Daily Sabah"], out)
    check("NAMING_SYSTEM: LANGUAGE_NOTE وصل الـsystem الفعلي",
          article.LANGUAGE_NOTE in calls[-1]["system"] and
          calls[-1]["system"] == article.NAMING_SYSTEM, calls[-1]["system"])

    article._client = real_client_fn

    # ── بوابة الاتساق: القيد اللغوي مسجَّل في CLAUDE.md بلا علاج (تحذير من
    # لمس norm_tokens/_extract_dates المشتركتين) — لكن رسالة الرفض يجب أن
    # تُسمّي السبب اللغوي صراحة حين يكون هو السبب الفعلي، لا رسالة عامة
    # تبدو عطل بحث (طلب المراجعة صراحة) ──
    check("_naming_language_mismatch: كيان عربي + وثائق غير عربية بالكامل + "
          "لا معلومة تاريخ (DATE_NO_INFO) ← تشخيص لغوي",
          article._naming_language_mismatch(
              "Bayraktar stratejimizi belirledik", ["بايراكتار"], ["15 عامًا"],
              [{"name": "Daily Sabah", "text": "Bayraktar stratejimizi belirledik dedi"}],
              cfg))
    check("_naming_language_mismatch: تعارض تاريخ صريح (DATE_MISMATCH) هو السبب "
          "الفعلي ← لا يُنسَب للغة رغم اختلافها فعلًا",
          not article._naming_language_mismatch(
              "Bayraktar 2011 yılında konuştu", ["بايراكتار"], ["11 آب 2026"],
              [{"name": "Daily Sabah", "text": "Bayraktar 2011 yılında konuştu"}],
              cfg))
    check("_naming_language_mismatch: أحد الوثائق عربي ← لا تشخيص لغوي (تطابق حرفي ممكن أصلًا)",
          not article._naming_language_mismatch(
              "خبر عن بايراكتار", ["بايراكتار"], ["15 عامًا"],
              [{"name": "الجزيرة نت", "text": "خبر عن بايراكتار بالعربية"}],
              cfg))
    check("_naming_language_mismatch: كيان بلا حروف عربية أصلًا ← لا تشخيص لغوي "
          "(التطابق الحرفي هنا ممكن بصرف النظر عن لغة الوثائق)",
          not article._naming_language_mismatch(
              "Bayraktar stratejimizi belirledik", ["Bayraktar"], ["15 عامًا"],
              [{"name": "Daily Sabah", "text": "Bayraktar stratejimizi belirledik dedi"}],
              cfg))

    # ── تكامل كامل عبر _name_event._try: رسالة trail الفعلية عند الرفض ──
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    evidence.search = lambda query, cfg, days, **kw: [object()]
    evidence.gather_evidence = lambda articles, cfg, claim_text="", **kw: (
        list(turkish_docs), evidence.EVIDENCE_FULL_TEXT)
    article._client = lambda: _CaptureClient(
        {"named": True, "text": "Bayraktar stratejimizi belirledik dedi",
         "supporting": ["Daily Sabah"]}, [])
    try:
        _, _, _, mismatch_trail = article._name_event(
            {"text": "إشارة مبهمة عن بايراكتار", "entities": ["بايراكتار", "15 عامًا"]}, cfg)
    finally:
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._client = real_client_fn

    direct_entries = [e for e in mismatch_trail if e["stage"] == "مباشر"]
    check("trail: رفض بوابة الاتساق بسبب لغة الوثائق يذكر السبب صراحة — لا الرسالة العامة",
          bool(direct_entries) and
          all("الوثائق بلغة غير عربية" in e["outcome"] for e in direct_entries),
          [e.get("outcome") for e in direct_entries])


def test_article_mentioned_sources() -> None:
    """mentioned (طلب المراجعة، تشخيص Issue #373، حالة بايراكتار الرابعة):
    رسالة السقوط «سند غير كافٍ» كانت واحدة عامة بصرف النظر عن السبب — الآن
    تفرّق «لم يذكر أي مصدر الموضوع إطلاقًا» (عطل بحث محتمل) عن «ذكره N مصدر
    لكن لم يطابق مضمونه» (عطل حكم) عن «طابق مضمونه جزئيًا فقط» — سطر واحد
    يوفّر جولة تشخيص كل مرة بدل رسالة ملتبسة."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False

    check("SUPPORT_SCHEMA يُلزم بحقل mentioned إلى جانب supporting",
          "mentioned" in article.SUPPORT_SCHEMA["input_schema"]["required"],
          article.SUPPORT_SCHEMA["input_schema"]["required"])
    for name, system in (("SUPPORT_SYSTEM", article.SUPPORT_SYSTEM),
                         ("STATEMENT_SUPPORT_SYSTEM", article.STATEMENT_SUPPORT_SYSTEM),
                         ("REPORT_SUPPORT_SYSTEM", article.REPORT_SUPPORT_SYSTEM)):
        check(f"{name}: MENTIONED_NOTE مُدرَج فعليًا في البرومبت",
              article.MENTIONED_NOTE in system)

    docs = [{"name": "Daily Sabah", "text": "نص", "link": "https://s1/1"},
            {"name": "Yeni Şafak", "text": "نص", "link": "https://s2/1"}]

    class _Block:
        def __init__(self, input_):
            self.type = "tool_use"
            self.input = input_

    class _Resp:
        def __init__(self, input_):
            self.content = [_Block(input_)]
            self.stop_reason = "end_turn"

    class _FakeMessages:
        def __init__(self, input_):
            self._input = input_

        def create(self, **kw):
            return _Resp(self._input)

    class _FakeClient:
        def __init__(self, input_):
            self.messages = _FakeMessages(input_)

    real_client_fn = article._client

    article._client = lambda: _FakeClient({"supporting": [], "mentioned": []})
    out = article._support_sources("تصريح اختباري", docs, cfg)
    check("_support_sources: mentioned فارغة حين لا يذكر أي مصدر الموضوع",
          out.mentioned == [], out.mentioned)

    article._client = lambda: _FakeClient({"supporting": [], "mentioned": ["Daily Sabah"]})
    out2 = article._support_sources("تصريح اختباري", docs, cfg)
    check("_support_sources: mentioned تحمل مصدرًا ذكر الموضوع بلا تأييد، supporting تبقى فارغة",
          out2.mentioned == ["Daily Sabah"] and out2 == [], (list(out2), out2.mentioned))

    article._client = lambda: _FakeClient(
        {"supporting": [], "mentioned": ["Daily Sabah", "مصدر مختلَق"]})
    out3 = article._support_sources("تصريح اختباري", docs, cfg)
    check("_support_sources: mentioned تُصفَّى بـ_known_only كما supporting — لا اسم مختلَق",
          out3.mentioned == ["Daily Sabah"], out3.mentioned)

    article._client = real_client_fn

    # ── تكامل كامل عبر _write_article: ثلاث حالات مختلفة في موجز واحد ──
    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_find_images = article.find_images

    evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        list(docs), evidence.EVIDENCE_FULL_TEXT)
    article.find_images = lambda title, cfg, terms=None: []

    def _fake_support(fact_text, docs, cfg, is_statement=False, is_report=False, publisher=""):
        result = article._ModelCallList()
        if fact_text == "لا ذكر إطلاقًا":
            result.mentioned = []
        elif fact_text == "ذُكر ولم يطابق":
            result.mentioned = ["Daily Sabah", "Yeni Şafak"]
        elif fact_text == "ذُكر وطابق جزئيًا":
            result.append("Daily Sabah")
            result.mentioned = ["Daily Sabah", "Yeni Şafak"]
        return result

    article._support_sources = _fake_support
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار mentioned",
        "statements": [
            {"text": "لا ذكر إطلاقًا", "kind": "واقعة", "entities": ["ك1"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": "ذُكر ولم يطابق", "kind": "واقعة", "entities": ["ك2"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": "ذُكر وطابق جزئيًا", "kind": "واقعة", "entities": ["ك3"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)

    try:
        out_full = article._write_article("موجز اختبار mentioned", 9001, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article.find_images = real_find_images

    dropped_by_text = {d["text"]: d["reason"] for d in out_full["dropped"]}
    check("لا ذكر إطلاقًا: رسالة السقوط تفيد أن لا مصدر مقروء ذكر الموضوع إطلاقًا",
          "لم يذكر أي من المصادر المقروءة الموضوع إطلاقًا" in dropped_by_text.get("لا ذكر إطلاقًا", ""),
          dropped_by_text.get("لا ذكر إطلاقًا"))
    check("ذُكر ولم يطابق: رسالة السقوط تذكر عدد من ذكروا الموضوع بلا أي تأييد",
          "ذكره 2 مصدر لكن لم يطابق مضمونه أيٌّ منها" in dropped_by_text.get("ذُكر ولم يطابق", ""),
          dropped_by_text.get("ذُكر ولم يطابق"))
    check("ذُكر وطابق جزئيًا: رسالة السقوط تفرّق بين عدد من ذكر الموضوع وعدد من طابقه فعلًا",
          "ذكره 2 مصدر وطابق مضمونه 1 منها فقط" in dropped_by_text.get("ذُكر وطابق جزئيًا", ""),
          dropped_by_text.get("ذُكر وطابق جزئيًا"))


def test_article_fetch_failure_gap() -> None:
    """نقص سند تقني لا واقعي (تشخيص Issue #583 — تحليل تجميعي على آخر 13
    Issue موسومة `مقال`): فشل جلب (HTTP 403 غالبًا) ظهر في 7 من الـ13، وفي
    أكثر من حالة أسقط تحديدًا مرشّح المصدر الذي كان سيرفع واقعة من (1) إلى
    (2) — سطر تشخيص صريح يفصل هذا عن انفراد مصدر واحد فعليًا بالخبر.
    verify.demoted_readers اكتسب من نفس التحليل ثلاثة نطاقات تكرّر فشل
    جلبها مرتين فأكثر عبر تلك العيّنة تحديدًا (رأي اليوم، نيوز رووم،
    alghad.tv)."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير test_article_mentioned_sources) — هذه الدالة لا تفحص مرحلة
    # استخراج وقائع المصادر، فتُعطَّل صراحة كي لا تستدعي _client() الحقيقي
    cfg["article"]["source_extract_enabled"] = False

    check("verify.demoted_readers يضم النطاقات المرصودة من تشخيص Issue #583",
          evidence._is_demoted_reader("رأي اليوم", cfg)
          and evidence._is_demoted_reader("نيوز رووم", cfg)
          and evidence._is_demoted_reader("alghad.tv", cfg))

    check("_fetch_failure_gap_note: بلا فشل جلب — بلا ملاحظة",
          article._fetch_failure_gap_note({"مصدر أ"}, [], cfg) == "")
    check("_fetch_failure_gap_note: المرشّح الفاشل نفس الناشر المؤيِّد بالفعل "
          "— بلا ملاحظة (تكرار لا سند إضافي حقيقي)",
          article._fetch_failure_gap_note(
              {"مصدر أ"}, [{"name": "مصدر أ", "reason": "HTTP 403"}], cfg) == "")
    check("_fetch_failure_gap_note: المرشّح الفاشل ناشر مختلف — الملاحظة تُضاف",
          article._fetch_failure_gap_note(
              {"مصدر أ"}, [{"name": "مصدر ب", "reason": "HTTP 403"}], cfg)
          == " — سقط مرشّح ثانٍ بفشل جلب — الواقعة كانت ستُسنَد")

    # ── تكامل كامل عبر _write_article: أربع وقائع في موجز واحد ──
    docs = [{"name": "Daily Sabah", "text": "نص", "link": "https://s1/1"},
            {"name": "Yeni Şafak", "text": "نص", "link": "https://s2/1"}]
    fetch_failures_by_claim = {
        "كF1": [{"name": "Yeni Şafak", "link": "https://s2/2", "reason": "HTTP 403"}],
        "كF2": [],
        "كF3": [{"name": "Yeni Şafak", "link": "https://s2/2", "reason": "HTTP 403"}],
        "كF4": [{"name": "Daily Sabah", "link": "https://s1/2", "reason": "HTTP 403"}],
    }

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_find_images = article.find_images

    evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        evidence._evidence_docs(list(docs), fetch_failures_by_claim.get(claim_text, [])),
        evidence.EVIDENCE_FULL_TEXT)
    article.find_images = lambda title, cfg, terms=None: []

    def _fake_support(fact_text, docs, cfg, is_statement=False, is_report=False, publisher=""):
        result = article._ModelCallList()
        if fact_text == "واقعة صفر مصادر":
            result.mentioned = []
        else:
            result.append("Daily Sabah")
            result.mentioned = ["Daily Sabah", "Yeni Şafak"]
        return result

    article._support_sources = _fake_support
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار فجوة فشل الجلب",
        "statements": [
            {"text": "واقعة بمرشّح ثانٍ فاشل", "kind": "واقعة", "entities": ["كF1"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": "واقعة بلا فشل جلب", "kind": "واقعة", "entities": ["كF2"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": "واقعة صفر مصادر", "kind": "واقعة", "entities": ["كF3"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": "واقعة بمرشّح فاشل مكرر", "kind": "واقعة", "entities": ["كF4"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)

    try:
        out = article._write_article("موجز اختبار فجوة فشل الجلب", 9002, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article.find_images = real_find_images

    dropped_by_text = {d["text"]: d["reason"] for d in out["dropped"]}
    check("واقعة 1/2 بمرشّح ثانٍ فشل جلبه (ناشر مختلف) — رسالة السقوط تحمل الملاحظة",
          "سقط مرشّح ثانٍ بفشل جلب — الواقعة كانت ستُسنَد"
          in dropped_by_text.get("واقعة بمرشّح ثانٍ فاشل", ""),
          dropped_by_text.get("واقعة بمرشّح ثانٍ فاشل"))
    check("واقعة 1/2 بلا فشل جلب — لا ملاحظة",
          "سقط مرشّح ثانٍ" not in dropped_by_text.get("واقعة بلا فشل جلب", ""),
          dropped_by_text.get("واقعة بلا فشل جلب"))
    check("واقعة 0/2 رغم فشل جلب مرشّح — لا ملاحظة (فشل مرشّح واحد لا يسدّ فجوة أكبر من واقعة)",
          "سقط مرشّح ثانٍ" not in dropped_by_text.get("واقعة صفر مصادر", ""),
          dropped_by_text.get("واقعة صفر مصادر"))
    check("واقعة 1/2 بمرشّح فشل جلبه هو الناشر المؤيِّد بالفعل — لا ملاحظة (تكرار لا سند إضافي)",
          "سقط مرشّح ثانٍ" not in dropped_by_text.get("واقعة بمرشّح فاشل مكرر", ""),
          dropped_by_text.get("واقعة بمرشّح فاشل مكرر"))


def test_article_source_facts() -> None:
    """وقائع من المصادر (لا الموجز فقط، طلب المراجعة على Issue #373): مرحلة
    جديدة تستخرج من الوثائق المقروءة فعلًا وقائع غائبة عن الموجز، بوسم
    origin: "source" مميَّزًا عن origin: "brief". البند الأخطر في التصميم
    (البند 1) هو الدمج ضد التكرار — فِكستران متعمَّدان (نفس الحدث بصياغتين
    يُدمَج، وحدثان متمايزان يشتركان في الكيانات لا يُدمَجان) يُبنيان أولًا
    ويُختبران بمعزل عن الأنبوب الرئيسي، قبل تكامل كامل عبر _write_article.

    المرحلة تشحن مُعطَّلة افتراضيًا (article.source_extract_enabled=false في
    config.yaml) — نداءا نموذج إضافيان لكل واقعة مستخرَجة (استخراج + دمج)
    يستحقان تشغيلًا حيًّا واحدًا قبل أن يصبحا افتراضيَّين على كل تشغيلة."""
    from src import article

    cfg = load_config()

    class _Block:
        def __init__(self, input_):
            self.type = "tool_use"
            self.input = input_

    class _Resp:
        def __init__(self, input_):
            self.content = [_Block(input_)]
            self.stop_reason = "end_turn"

    class _FakeMessages:
        def __init__(self, input_, captured=None):
            self._input = input_
            self._captured = captured

        def create(self, **kw):
            if self._captured is not None:
                self._captured.append(kw)
            return _Resp(self._input)

    class _FakeClient:
        def __init__(self, input_, captured=None):
            self.messages = _FakeMessages(input_, captured)

    real_client_fn = article._client

    # ── 1) الدمج ضد التكرار (البند 1، الأخطر في هذا التصميم) — فِكستران
    # متعمَّدان قبل أي وصل بالأنبوب الرئيسي ──

    # (أ) نفس الحدث بصياغتين مختلفتين من مسارين — يجب أن يُدمَج لا يُعدّ مرتين
    article._client = lambda: _FakeClient({"duplicate_index": 0})
    dup1 = article._source_fact_duplicate_index(
        "توغّلت قوات الحكومة داخل المدينة الخميس عقب اشتباكات قصيرة",
        ["دخلت القوات الحكومية المدينة يوم الخميس بعد معارك محدودة"], cfg)
    check("١) نفس الحدث بصياغتين مختلفتين ← duplicate=True برقم الواقعة الأصلية",
          dup1 == {"duplicate": True, "index": 0, "call_error": None}, dup1)

    # (ب) حدثان متمايزان يشتركان في الفاعل نفسه — يجب ألا يُدمَجا (المعيار:
    # الفعل/الحدث نفسه لا الكيانات المشتركة وحدها)
    article._client = lambda: _FakeClient({"duplicate_index": -1})
    dup2 = article._source_fact_duplicate_index(
        "التقى الرئيس بوزير الخارجية يوم الجمعة لبحث ملف الطاقة",
        ["زار الرئيس المدينة يوم الخميس"], cfg)
    check("٢) حدث مختلف يشارك الفاعل نفسه مع واقعة سابقة ← duplicate=False، لا يُدمَج",
          dup2 == {"duplicate": False, "index": None, "call_error": None}, dup2)

    dup_empty = article._source_fact_duplicate_index("أي نص", [], cfg)
    check("قائمة وقائع سابقة فارغة ← duplicate=False بلا نداء نموذج (اختصار مبكر)",
          dup_empty == {"duplicate": False, "index": None, "call_error": None})

    from anthropic import APIConnectionError
    import httpx as _httpx

    class _RaisingMessages:
        def create(self, **kw):
            raise APIConnectionError(
                message="انقطاع شبكة اختباري",
                request=_httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    class _RaisingClient:
        def __init__(self):
            self.messages = _RaisingMessages()

    article._client = lambda: _RaisingClient()
    dup_fail = article._source_fact_duplicate_index("نص", ["واقعة سابقة"], cfg)
    check("فشل نداء تقني ← duplicate=False (إسقاط تحوّطي، لا تخمين حكم دمج لم يقع) "
          "مع call_error مضبوط",
          dup_fail["duplicate"] is False and bool(dup_fail["call_error"]), dup_fail)

    article._client = real_client_fn

    # ── 2) العربية إلزامية في SOURCE_EXTRACT_SYSTEM لكل من text وentities
    # معًا (البند 4) ──
    check("SOURCE_EXTRACT_SYSTEM يشترط العربية لكل من text وentities معًا",
          "text وentities كلاهما بالعربية دومًا" in article.SOURCE_EXTRACT_SYSTEM)
    check("SOURCE_EXTRACT_SYSTEM يضمّ LANGUAGE_NOTE",
          article.LANGUAGE_NOTE in article.SOURCE_EXTRACT_SYSTEM)

    captured: list = []
    article._client = lambda: _FakeClient(
        {"facts": [{"text": "واقعة جديدة من مصدر", "entities": ["ك"]}]}, captured)
    out_extract = article._extract_source_facts(
        "موضوع الاختبار", ["واقعة من الموجز أصلًا"],
        [{"name": "مصدر", "text": "نص المصدر", "link": "https://s/1"}], cfg)
    check("_extract_source_facts: يستعمل SOURCE_EXTRACT_SYSTEM فعليًا",
          captured[0]["system"] == article.SOURCE_EXTRACT_SYSTEM)
    check("_extract_source_facts: وقائع الموجز الموجودة أصلًا تصل البرومبت (لا تُكرَّر)",
          "واقعة من الموجز أصلًا" in captured[0]["messages"][0]["content"])
    check("_extract_source_facts: الواقعة الجديدة تُستخرج بنصها وكياناتها",
          out_extract == [{"text": "واقعة جديدة من مصدر", "entities": ["ك"]}], out_extract)

    article._client = lambda: _FakeClient({"facts": []})
    check("_extract_source_facts: قائمة فارغة من النموذج ← [] بلا انهيار",
          article._extract_source_facts("م", [], [{"name": "م", "text": "ن"}], cfg) == [])

    check("_extract_source_facts: بلا وثائق ← [] بلا نداء نموذج",
          article._extract_source_facts("م", [], [], cfg) == [])

    article._client = lambda: _RaisingClient()
    fail_extract = article._extract_source_facts("م", [], [{"name": "م", "text": "ن"}], cfg)
    check("_extract_source_facts: فشل نداء تقني ← قائمة فارغة مع call_error مضبوط",
          fail_extract == [] and bool(getattr(fail_extract, "call_error", None)),
          getattr(fail_extract, "call_error", None))

    article._client = real_client_fn

    # ── 3) سقف حجم البرومبت مرتّب بالوزن ثم الصلة (البند 3) — نظير مرشّحي
    # القراءة، لا فرزًا جديدًا: وثيقة موثوقة قبل مجهولة عند التزاحم ──
    wanted = article.norm_tokens("مطلوبة") | article.norm_tokens("كلمة")
    docs_pool = [
        {"name": "مصدر مجهول لا صلة له", "text": "حشو حشو حشو بلا أي صلة هنا إطلاقًا",
         "link": "https://u1/1"},
        {"name": "Reuters", "text": "خبر", "link": "https://r/1"},  # موثوق بلا صلة
        {"name": "مصدر مجهول ذو صلة", "text": "كلمة مطلوبة كلمة أخرى مطلوبة أيضًا",
         "link": "https://u2/1"},
    ]
    ranked = article._rank_docs_for_source_extract(docs_pool, wanted, cfg, max_docs=2)
    names_ranked = [d["name"] for d in ranked]
    check("_rank_docs_for_source_extract: يقصّ عند max_docs",
          len(ranked) == 2, names_ranked)
    check("_rank_docs_for_source_extract: مصدر موثوق بلا صلة يتصدَّر مصدرًا مجهولًا بلا صلة "
          "أيضًا عند التزاحم على السقف (البند 3: الوزن يفصل)",
          "Reuters" in names_ranked and "مصدر مجهول لا صلة له" not in names_ranked,
          names_ranked)
    check("_rank_docs_for_source_extract: مصدر مجهول لكن ذو صلة عالية يبقى ضمن السقف رغم "
          "وزنه الافتراضي (الصلة تعوّض فارق الوزن)",
          "مصدر مجهول ذو صلة" in names_ranked, names_ranked)

    dedup_docs = [
        {"name": "الجزيرة نت", "text": "نص طويل نسبيًا يحمل تفاصيل أكثر من غيره",
         "link": "https://aj1/1"},
        {"name": "Al Jazeera", "text": "قصير", "link": "https://aj2/1"},
    ]
    ranked_dedup = article._rank_docs_for_source_extract(dedup_docs, set(), cfg, max_docs=5)
    check("_rank_docs_for_source_extract: نسختا ناشر واحد بلغتين تُوحَّدان — مرشَّح واحد لا اثنان",
          len(ranked_dedup) == 1, ranked_dedup)

    # _dedup_docs_by_publisher مستخرَجة من الدالة أعلاه (طلب المراجعة، تعليق
    # العطل الرابع والعشرون، البند 1) — تُستعمَل الآن أيضًا كمجمّع الحكم على
    # السند مباشرة، بلا فرز ولا سقف
    dedup_only = article._dedup_docs_by_publisher(dedup_docs, cfg)
    check("_dedup_docs_by_publisher: توحيد الهوية وحده، بلا فرز/سقف — مرشَّح واحد بالنص الأطول",
          len(dedup_only) == 1 and dedup_only[0]["text"] == "نص طويل نسبيًا يحمل تفاصيل أكثر من غيره",
          dedup_only)
    check("_dedup_docs_by_publisher: وثيقة بلا نص تُستبعد",
          article._dedup_docs_by_publisher(
              [{"name": "م", "text": "", "link": "u"}, {"name": "م٢", "text": "نص", "link": "u2"}],
              cfg) == [{"name": "م٢", "text": "نص", "link": "u2"}])

    # ── 4) التكامل الكامل عبر _write_article: origin، الدمج، القسم، والسطر
    # الملخِّص (البنود 1، 2، 5) — شاهد بايراكتار (Defensehere/Daily Sabah)
    # الذي طلبتَ تشغيله؛ يُبقي الواقعة الأصلية بمصدر واحد فقط (تسقط عمدًا)
    # كي تبقى grounded دون min_grounded_facts فيتوقف _write_article عند
    # بوابة الكفاية مباشرة بعد حساب حصيلة استخراج المصادر — لا حاجة لتزييف
    # الصياغة/الصورة/التخزين، غير مرتبطين بما هذا الاختبار يفحصه ──
    cfg_on = load_config()
    cfg_on["article"] = {**cfg_on["article"], "source_extract_enabled": True}

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_extract_source_facts = article._extract_source_facts
    real_dup_index = article._source_fact_duplicate_index

    brief_fact_text = "أعلنت بايكار أنها تصنّع محليًا 90 بالمئة من مسيّرات بيرقدار"
    duplicate_source_text = "بايكار تصنّع محليًا معظم مكوّنات بيرقدار بحسب الشركة"
    new_source_text = "صدّرت بايكار مسيّرات بيرقدار إلى أكثر من 30 دولة"

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "بايكار وبيرقدار",
        "statements": [
            {"text": brief_fact_text, "kind": "واقعة", "entities": ["بايكار"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": "Defensehere", "text": "نص Defensehere", "link": "https://dh/1"},
         {"name": "Daily Sabah", "text": "نص Daily Sabah", "link": "https://ds/1"}],
        evidence.EVIDENCE_FULL_TEXT)

    def _fake_support(fact_text, docs, cfg, is_statement=False, is_report=False, publisher=""):
        if fact_text == brief_fact_text:
            return ["Defensehere"]  # مصدر واحد فقط — يسقط عمدًا (< min_confirm)
        return ["Defensehere", "Daily Sabah"]

    def _fake_extract_source(topic, brief_texts, docs, cfg):
        return article._ModelCallList([
            {"text": duplicate_source_text, "entities": ["بايكار"]},
            {"text": new_source_text, "entities": ["بايكار", "بيرقدار"]},
        ])

    def _fake_dup(candidate_text, existing_texts, cfg):
        if candidate_text == duplicate_source_text:
            return {"duplicate": True, "index": 0, "call_error": None}
        return {"duplicate": False, "index": None, "call_error": None}

    article._support_sources = _fake_support
    article._extract_source_facts = _fake_extract_source
    article._source_fact_duplicate_index = _fake_dup

    try:
        out = article._write_article("موجز اختبار بايراكتار", 9002, cfg_on)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article._extract_source_facts = real_extract_source_facts
        article._source_fact_duplicate_index = real_dup_index

    check("التكامل: الواقعة الأصلية (مصدر واحد فقط) سقطت كما صُمِّم الاختبار",
          any(d["text"] == brief_fact_text for d in out.get("dropped", [])), out.get("dropped"))
    source_texts = [f["text"] for f in out.get("source_origin_facts", [])]
    check("التكامل: الواقعة المكرَّرة (نفس الحدث بصياغة مختلفة) لم تدخل المقال إطلاقًا",
          duplicate_source_text not in source_texts, source_texts)
    check("التكامل: الواقعة الجديدة الفعلية دخلت المقال بوسم origin=source",
          new_source_text in source_texts, source_texts)
    check("التكامل: ملخّص الاستخراج (البند 5) — 2 استُخرجت، 1 اندمجت، 0 خارج الموضوع، 1 أُضيفت",
          out["source_facts_summary"] == {"extracted": 2, "merged": 1, "off_topic": 0, "added": 1},
          out["source_facts_summary"])

    report = article.build_report(out)
    check("التقرير: قسم «وقائع من المصادر لم ترد في موجزي (راجعها)» ظاهر (البند 2)",
          "وقائع من المصادر لم ترد في موجزي" in report)
    check("التقرير: الواقعة الجديدة ومصادرها المسنِدة تظهر في القسم",
          new_source_text in report and "Defensehere" in report and "Daily Sabah" in report,
          report)
    check("التقرير: الواقعة المندمَجة لا تظهر في قسم «وقائع من المصادر» (اندمجت لا أُضيفت)",
          duplicate_source_text not in report)
    check("التقرير: سطر الملخّص الظاهر (البند 5) يذكر الأعداد الثلاثة صراحة",
          ("استُخرجت 2 واقعة" in report and "اندمجت 1" in report and "أُضيفت 1" in report),
          report)

    # ── 5) تصحيح تصميم (طلب المراجعة، تعليق العطل الرابع والعشرون): وقائع
    # المصادر لا تُبحَث من جديد — سندها المجمّع المقروء نفسه، وفحص صلة
    # بنيوي يستبعد ما لا يشارك كيانات موضوع الموجز قبل أي نداء نموذج ──
    search_calls: list = []

    def _counting_search(query, cfg, days, unrestricted=False):
        search_calls.append(query)
        return [object()]

    dup_calls: list = []

    def _fake_dup_counting(candidate_text, existing_texts, cfg):
        dup_calls.append(candidate_text)
        return {"duplicate": False, "index": None, "call_error": None}

    offtopic_text = "حادث لا صلة له بموضوع الموجز إطلاقًا"

    def _fake_extract_source_offtopic(topic, brief_texts, docs, cfg):
        return article._ModelCallList([
            {"text": offtopic_text, "entities": ["كيان غريب تمامًا لا علاقة له"]},
            {"text": new_source_text, "entities": ["بايكار", "بيرقدار"]},
        ])

    support_docs_seen: list = []

    def _fake_support_recording(fact_text, docs, cfg, is_statement=False, is_report=False,
                                publisher=""):
        support_docs_seen.append((fact_text, [d["name"] for d in docs]))
        if fact_text == brief_fact_text:
            return ["Defensehere"]  # مصدر واحد فقط — يسقط عمدًا (< min_confirm)، كالاختبار
            # الأول: تُبقي grounded دون min_grounded_facts فيتوقف _write_article
            # عند بوابة الكفاية مباشرة بعد حساب حصيلة استخراج المصادر — لا حاجة
            # لتزييف _choose_question/_draft_article، غير مرتبطين بما يفحصه هذا الاختبار
        return ["Defensehere", "Daily Sabah"]

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "بايكار وبيرقدار",
        "statements": [
            {"text": brief_fact_text, "kind": "واقعة", "entities": ["بايكار"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    evidence.search = _counting_search
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": "Defensehere", "text": "نص Defensehere", "link": "https://dh/1"},
         {"name": "Daily Sabah", "text": "نص Daily Sabah", "link": "https://ds/1"}],
        evidence.EVIDENCE_FULL_TEXT)
    article._support_sources = _fake_support_recording
    article._extract_source_facts = _fake_extract_source_offtopic
    article._source_fact_duplicate_index = _fake_dup_counting

    try:
        out2 = article._write_article("موجز اختبار بايراكتار ٢", 9003, cfg_on)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article._extract_source_facts = real_extract_source_facts
        article._source_fact_duplicate_index = real_dup_index

    check("لا بحث جديد لوقائع المصادر: evidence.search استُدعيت مرة واحدة فقط "
          "(للواقعة الوحيدة في الموجز) — لا مرة إضافية لأي من الواقعتين المستخرَجتين",
          len(search_calls) == 1, search_calls)
    check("فحص الصلة البنيوي يمنع نداء الدمج للواقعة خارج الموضوع — دالة الدمج استُدعيت "
          "مرة واحدة فقط (للواقعة الجديدة الفعلية، لا الواقعة خارج الموضوع)",
          dup_calls == [new_source_text], dup_calls)
    off_topic_trail = [t for t in out2["trail"]
                       if t["stage"] == "واقعة (من المصادر)"
                       and "استُبعدت لعدم صلتها" in t.get("outcome", "")]
    check("trail: سطر استبعاد صريح للواقعة خارج الموضوع",
          len(off_topic_trail) == 1 and offtopic_text in off_topic_trail[0]["outcome"],
          off_topic_trail)
    check("source_facts_summary['off_topic'] == 1",
          out2["source_facts_summary"]["off_topic"] == 1, out2["source_facts_summary"])
    check("الواقعة خارج الموضوع لم تدخل المقال إطلاقًا",
          offtopic_text not in [f["text"] for f in out2.get("source_origin_facts", [])])
    check("الواقعة الجديدة الفعلية دخلت المقال رغم عدم إجراء بحث جديد لها — سندها "
          "المجمّع المقروء نفسه",
          new_source_text in [f["text"] for f in out2.get("source_origin_facts", [])],
          out2.get("source_origin_facts"))
    new_fact_support_call = next((c for c in support_docs_seen if c[0] == new_source_text), None)
    check("_support_sources استُدعيت للواقعة الجديدة بوثائق من المجمّع المقروء (Defensehere/"
          "Daily Sabah) لا بوثائق بحث جديد",
          new_fact_support_call is not None
          and set(new_fact_support_call[1]) == {"Defensehere", "Daily Sabah"},
          new_fact_support_call)

    # ── مُعطَّل افتراضيًا في **الكود** حين المفتاح غائب كليًا من التهيئة — لا
    # اعتمادًا على قيمة config.yaml الحالية القابلة للتبديل يدويًا بعد التحقق
    # الحي (نفس فخّ include_opinion سابقًا في هذا الـ Issue: فحص قيمة الملف
    # المتحوِّلة بدل سلوك الكود الثابت). يفحص نص المصدر مباشرة، لا الملف ──
    check("acfg.get('source_extract_enabled', False) — القيمة الافتراضية عند غياب "
          "المفتاح False في نص الكود نفسه، بصرف النظر عمّا يُضبط في config.yaml",
          'acfg.get("source_extract_enabled", False)' in inspect.getsource(article._write_article))


def test_reject_boxes_render() -> None:
    """المربعات خارج <details>: داخلها تظهر نصًا لا يُنقر عليه."""
    from src import review

    draft = {"id": "abcd12", "score": 9.1, "caption": "متن\nسطر",
             "image": "assets/x.jpg", "bucket": "serious",
             "source": {"link": "https://x/1", "publishers": ["BBC", "Reuters"]},
             "arabic": {"post_title": "عنوان", "category": "سياسة"}}
    body = review.build_issue_body([draft], "u/r", "main")

    lines = body.splitlines()
    reject_lines = [ln for ln in lines if "<!-- rj:" in ln]
    check("كل أسباب الرفض معروضة",
          len(reject_lines) == len(review.REJECT_CHOICES))
    check("كل سبب مربع قابل للنقر",
          all("- [ ]" in ln for ln in reject_lines))

    # لا يجوز أن يقع أي مربع رفض داخل كتلة طيّ
    depth, inside = 0, []
    for ln in lines:
        if "<details" in ln:
            depth += 1
        if "<!-- rj:" in ln:
            inside.append(depth)
        if "</details>" in ln:
            depth -= 1
    check("لا مربع رفض داخل <details>", not any(d > 0 for d in inside))

    parsed = review.parse_rejects(
        body.replace("- [ ] مكرر", "- [x] مكرر"))
    check("المربع المعلَّم يُقرأ", ("abcd12", "مكرر") in parsed)


def test_reject_beats_approval() -> None:
    """✔️ مع سبب رفض = لا نشر. الخطأ هنا لا يُستدرك بعد النشر."""
    from src import review

    body = ("- [x] **1. عنوان**  <!-- draft:abcd12 -->\n"
            "- [x] مكرر  <!-- rj:abcd12:مكرر -->\n"
            "- [x] **2. آخر**  <!-- draft:ef3456 -->\n")
    approved = review.parse_approved(body)
    rejected = {did for did, _ in review.parse_rejects(body)}
    check("المرفوض يُستبعد رغم الاعتماد",
          [i for i in approved if i not in rejected] == ["ef3456"])


def test_first_comment() -> None:
    from src.publish import first_comment_for

    cfg = load_config()
    draft = {"source": {"link": "https://bbc.com/a", "publishers": ["BBC", "Reuters"]}}

    text = first_comment_for(draft, cfg)
    check("التعليق الأول يحوي الرابط", text and "https://bbc.com/a" in text)
    check("التعليق الأول يحوي المصادر", text and "BBC" in text)

    cfg2 = load_config()
    cfg2["facebook"]["link_in_first_comment"] = False
    check("تعطيل الميزة يلغي التعليق", first_comment_for(draft, cfg2) is None)

    check("مسودة بلا رابط لا تُنتج تعليقًا",
          first_comment_for({"source": {}}, cfg) is None)

    # المتن يجب ألا يحوي الرابط عند تفعيل الميزة
    art = Article(title="T", link="https://bbc.com/a", summary="", source_name="BBC",
                  region="uk", weight=1.0, published=datetime.now(timezone.utc))
    art.cluster_sources = ["BBC"]
    body = writer.build_caption(
        {"post_title": "عنوان", "post_body": "متن", "hashtags": ["أخبار"]}, art, cfg)
    check("متن المنشور بلا رابط خارجي", "https://bbc.com/a" not in body, body[-60:])
    body2 = writer.build_caption(
        {"post_title": "عنوان", "post_body": "متن", "hashtags": ["أخبار"]}, art, cfg2)
    check("المتن يحوي الرابط عند التعطيل", "https://bbc.com/a" in body2)


def test_burst_inline_cap_zero_defers_without_sleep() -> None:
    """Issue #315: finalize يستدعي cmd_burst داخل مهمة urgent (سقفها 20
    دقيقة)، وأصغر فاصل يحسبه spaced_slots هو 30 دقيقة — أي sleep واحد
    يتجاوز السقف حتمًا. inline_cap_minutes=0 يجب أن يمنع أي sleep تمامًا:
    يُنشر المستحق الآن فقط (wait<=0)، والبقية queued بلا انتظار."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    drafts = []
    for i, score in enumerate([0.9, 0.5, 0.3]):
        d = {
            "id": f"burst{i}", "status": "pending", "score": score,
            "arabic": {"post_title": f"خبر {i}", "urgent": False},
            "image": "drafts/x.jpg", "caption": "متن", "source": {},
        }
        store.save_draft(d)
        drafts.append(d)

    sleep_calls: list = []
    real_sleep = publish_mod.time.sleep
    publish_mod.time.sleep = lambda s: sleep_calls.append(s)

    published_calls: list = []
    real_publish_one = publish_mod.publish_one

    def fake_publish_one(path, draft, cfg):
        published_calls.append(draft["id"])
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['id']}"

    publish_mod.publish_one = fake_publish_one

    try:
        code = publish_mod.cmd_burst(
            [d["id"] for d in drafts], cfg, None, inline_cap_minutes=0)
    finally:
        publish_mod.time.sleep = real_sleep
        publish_mod.publish_one = real_publish_one

    check("cmd_burst بلا انتظار داخلي ينتهي بنجاح", code == 0, f"exit={code}")
    check("لا استدعاء sleep إطلاقًا (لا يتجاوز سقف مهمة urgent)",
          sleep_calls == [], str(sleep_calls))
    check("الأعلى مؤشرًا وحده نُشر فورًا (wait<=0)",
          published_calls == ["burst0"], str(published_calls))

    statuses = {d["id"]: store.load_draft(d["id"])[1]["status"] for d in drafts}
    check("البقية عُلّمت queued لا published",
          statuses["burst0"] == "published"
          and statuses["burst1"] == "queued"
          and statuses["burst2"] == "queued", str(statuses))
    check("موعد نشر مؤجَّل محفوظ للمتبقي (يلتقطه سيّر نشر الطابور)",
          "publish_at" in store.load_draft("burst1")[1])


def test_burst_urgent_still_immediate_with_inline_cap_zero() -> None:
    """العاجل يخرج فورًا مهما كان حجم الدفعة — inline_cap_minutes=0 يمسّ
    البقية العادية فقط، ولا يغيّر منطق العاجل (wait=0 بلا شرط) إطلاقًا."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    urgent = {"id": "urg0", "status": "pending", "score": 0.1,
              "arabic": {"post_title": "عاجل", "urgent": True},
              "image": "drafts/x.jpg", "caption": "متن", "source": {}}
    normal = {"id": "norm0", "status": "pending", "score": 0.9,
              "arabic": {"post_title": "عادي", "urgent": False},
              "image": "drafts/x.jpg", "caption": "متن", "source": {}}
    store.save_draft(urgent)
    store.save_draft(normal)

    real_sleep = publish_mod.time.sleep
    publish_mod.time.sleep = lambda s: (_ for _ in ()).throw(
        AssertionError(f"sleep({s}) استُدعي رغم inline_cap_minutes=0"))

    published_calls: list = []
    real_publish_one = publish_mod.publish_one

    def fake_publish_one(path, draft, cfg):
        published_calls.append(draft["id"])
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['id']}"

    publish_mod.publish_one = fake_publish_one

    try:
        code = publish_mod.cmd_burst(
            ["urg0", "norm0"], load_config(), None, inline_cap_minutes=0)
    finally:
        publish_mod.time.sleep = real_sleep
        publish_mod.publish_one = real_publish_one

    check("cmd_burst مع عاجل ينتهي بنجاح", code == 0, f"exit={code}")
    check("العاجل نُشر فورًا رغم inline_cap_minutes=0",
          "urg0" in published_calls, str(published_calls))
    check("العادي أُجِّل للطابور بلا نشر فوري",
          "norm0" not in published_calls, str(published_calls))


def test_scheduling() -> None:
    from src.schedule import assign_slots, describe, is_due

    tz, peak = "Europe/Istanbul", [12, 18, 21]
    dawn = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)      # 03:00 محليًا
    slots = assign_slots(4, peak, tz, 120, now=dawn)

    check("الاعتماد فجرًا لا يُنشر فورًا", all(s > dawn for s in slots))
    hours = [s.astimezone(__import__("zoneinfo").ZoneInfo(tz)).hour for s in slots]
    check("كل المواعيد في ساعات الذروة", set(hours) <= set(peak), str(hours))
    check("المواعيد مرتبة تصاعديًا",
          all(slots[i] < slots[i + 1] for i in range(len(slots) - 1)))

    gaps = [(slots[i + 1] - slots[i]).total_seconds() / 60 for i in range(len(slots) - 1)]
    check("الفاصل الأدنى محترم", all(g >= 120 for g in gaps), str(gaps))

    evening = datetime(2026, 8, 1, 15, 30, tzinfo=timezone.utc)  # 18:30 محليًا
    quick = assign_slots(2, peak, tz, 120, now=evening)
    check("داخل الذروة يُنشر الأول فورًا", quick[0] == evening)

    taken = [datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)]
    avoid = assign_slots(1, peak, tz, 120, taken=taken, now=evening)
    check("لا تصادم مع موعد محجوز",
          abs((avoid[0] - taken[0]).total_seconds()) >= 7200)

    check("is_due يميّز الماضي", is_due(dawn, dawn + timedelta(hours=1)))
    check("is_due يميّز المستقبل", not is_due(dawn + timedelta(hours=1), dawn))
    check("صياغة الموعد بالتوقيت المحلي", "12:00" in describe(slots[0], tz))


def test_due_publishes_one_at_a_time() -> None:
    """Issue #327 البند 2: لو فاتت queue.yml تشغيلة أو أكثر، تتراكم عدة
    مسودات مستحقة معًا. cmd_due يجب ألا ينشرها كلها في حلقة واحدة بلا
    فاصل — هذا هو النمط الآلي الذي صُمم spaced_slots لتجنّبه أصلًا.
    ينشر الأقدم موعدًا فقط، ويترك الباقي queued للتشغيلة التالية."""
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    ids = ["due_old", "due_mid", "due_new"]
    for i, did in enumerate(ids):
        d = {
            "id": did, "status": "queued",
            "publish_at": (now - timedelta(minutes=90 - i * 10)).isoformat(),
            "arabic": {"post_title": f"خبر {did}", "urgent": False},
            "image": "drafts/x.jpg", "caption": "متن", "source": {},
        }
        store.save_draft(d)

    published_calls: list = []
    real_publish_one = publish_mod.publish_one

    def fake_publish_one(path, draft, cfg):
        published_calls.append(draft["id"])
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['id']}"

    publish_mod.publish_one = fake_publish_one

    comment_calls: list = []
    real_comment = review.comment
    review.comment = lambda issue_number, text: comment_calls.append((issue_number, text))

    try:
        code = publish_mod.cmd_due(load_config())
    finally:
        publish_mod.publish_one = real_publish_one
        review.comment = real_comment

    check("cmd_due ينتهي بنجاح", code == 0, f"exit={code}")
    check("منشور واحد فقط نُشر رغم ثلاثة مستحقة معًا",
          published_calls == ["due_old"], str(published_calls))

    statuses = {did: store.load_draft(did)[1]["status"] for did in ids}
    check("الأقدم وحده published والبقية ما زالت queued بانتظار التشغيلة التالية",
          statuses == {"due_old": "published", "due_mid": "queued",
                       "due_new": "queued"}, str(statuses))


def test_decisions() -> None:
    """Issue #583 — المرحلة الأولى: سجل قرارات تراكمي (state/decisions.json)،
    جمع بلا أي تحليل أو تأثير على الفرز/الترتيب."""
    from src import decisions

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    if decisions.DECISIONS_FILE.exists():
        decisions.DECISIONS_FILE.unlink()

    published_draft = {
        "id": "dec_pub1", "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending", "score": 5.5, "bucket": "serious",
        "trend_score": 0.4, "velocity": 0.2, "has_photo": True, "state_media": False,
        "source": {"region": "eu", "publishers": ["BBC", "Reuters"]},
        "arabic": {"category": "عالم", "angle": "خبر", "urgent": False,
                   "post_body": "نص المنشور هنا"},
    }
    decisions.record_published(published_draft)
    entries = decisions.load()
    check("النشر يُسجَّل بقرار published",
          any(e["id"] == "dec_pub1" and e["decision"] == "published" for e in entries))
    rec = next(e for e in entries if e["id"] == "dec_pub1")
    check("السمات تُستخرج من المسودة بلا حقول جديدة",
          rec["category"] == "عالم" and rec["source_count"] == 2
          and rec["bucket"] == "serious" and rec["origin"] == "collect",
          str(rec))

    before = len(decisions.load())
    decisions.record_published(published_draft)
    check("لا تكرار عند تسجيل نفس المسودة مرتين", len(decisions.load()) == before)

    rejected_draft = dict(published_draft, id="dec_rej1")
    decisions.record_rejected(rejected_draft, "ضعيف")
    rec2 = next(e for e in decisions.load() if e["id"] == "dec_rej1")
    check("الرفض الصريح يُسجَّل بوسمه",
          rec2["decision"] == "rejected_explicit" and rec2["reject_tag"] == "ضعيف",
          str(rec2))

    # الفحص الدوري بلا بيئة Actions: لا شيء يُفحص، بلا عطل
    saved_repo = os.environ.pop("GITHUB_REPOSITORY", None)
    saved_token = os.environ.pop("GITHUB_TOKEN", None)
    check("scan بلا بيئة Actions يعيد صفرًا بأمان", decisions.scan(load_config()) == 0)

    now = datetime.now(timezone.utc)
    old_pending = {
        "id": "dec_old1", "created_at": (now - timedelta(hours=100)).isoformat(),
        "status": "pending", "review_issue": 501, "score": 1.0, "bucket": "serious",
        "source": {}, "arabic": {},
    }
    fresh_pending = {
        "id": "dec_fresh1", "created_at": now.isoformat(),
        "status": "pending", "review_issue": 502, "score": 1.0, "bucket": "serious",
        "source": {}, "arabic": {},
    }
    closed_pending = {
        "id": "dec_closed1", "created_at": now.isoformat(),
        "status": "pending", "review_issue": 503, "score": 1.0, "bucket": "serious",
        "source": {}, "arabic": {},
    }
    for d in (old_pending, fresh_pending, closed_pending):
        store.save_draft(d)

    os.environ["GITHUB_REPOSITORY"] = "u/r"
    os.environ["GITHUB_TOKEN"] = "tok"

    real_fetch_issue = decisions._fetch_issue
    decisions._fetch_issue = lambda n: {"state": "closed" if n == 503 else "open"}

    cfg = load_config()
    cfg["decisions"] = {"ignore_timeout_hours": 48}
    try:
        n = decisions.scan(cfg)
    finally:
        decisions._fetch_issue = real_fetch_issue
        os.environ.pop("GITHUB_REPOSITORY", None)
        os.environ.pop("GITHUB_TOKEN", None)
        if saved_repo is not None:
            os.environ["GITHUB_REPOSITORY"] = saved_repo
        if saved_token is not None:
            os.environ["GITHUB_TOKEN"] = saved_token

    check("scan سجّل قرارين ضمنيين فقط (المهلة + الإغلاق)", n == 2, str(n))
    entries = decisions.load()
    check("مسودة قديمة مفتوحة ← ignored_timeout", any(
        e["id"] == "dec_old1" and e["decision"] == "ignored_timeout" for e in entries))
    check("مسودة حديثة مفتوحة لم تُبتّ بعد — لا تُسجَّل",
          not any(e["id"] == "dec_fresh1" for e in entries))
    check("مسودة Issue أُغلق ← dismissed_closed", any(
        e["id"] == "dec_closed1" and e["decision"] == "dismissed_closed" for e in entries))


def test_insights_analysis() -> None:
    from src.insights import analyse, engagement, recommendations

    check("المشاركة أثقل من الإعجاب",
          engagement({"shares": 1}) > engagement({"reactions": 4}))
    check("التعليق أثقل من الإعجاب",
          engagement({"comments": 1}) > engagement({"reactions": 2}))

    base = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc).isoformat()
    rows = []
    for i in range(6):   # رائجة وقوية
        rows.append({"id": f"t{i}", "title": "رائج", "category": "تقنية", "urgent": False,
                     "trend_score": 0.9, "state_media": False, "publishers": ["BBC"],
                     "published_at": base, "has_photo": True, "reactions": 100,
                     "comments": 10, "shares": 10, "engagement": 180})
    for i in range(6):   # غير رائجة وضعيفة
        rows.append({"id": f"n{i}", "title": "عادي", "category": "ثقافة", "urgent": False,
                     "trend_score": 0.0, "state_media": False, "publishers": ["TASS"],
                     "published_at": base, "has_photo": False, "reactions": 10,
                     "comments": 1, "shares": 0, "engagement": 13})

    a = analyse(rows, "Europe/Istanbul")
    check("التحليل يحسب العدد", a["count"] == 12)
    check("الأفضل أداءً في المقدمة", a["top"][0]["engagement"] == 180)
    check("التصنيف الأقوى أولًا", a["categories"][0][0] == "تقنية")
    check("مقارنة الترند محسوبة", a["trend"][0] > a["trend"][2])

    recs = recommendations(a, load_config())
    joined = " ".join(recs)
    check("يوصي برفع وزن الترند", "ارفع" in joined and "trends.weight" in joined, joined[:120])
    check("يوصي بناءً على الصور", "صورة" in joined or "المصادر" in joined)

    check("لا انهيار مع بيانات فارغة", analyse([], "UTC") == {})


def test_measure_channels() -> None:
    """سكربت الاستطلاع اليدوي (tools/measure_channels.py، Issue #619) لا شبكة
    فعلية له في هذا الاختبار — يُشغَّل يدويًا من جهاز المالك فقط (انظر
    CLAUDE.md). نختبر هنا الدوال الصِرفة فقط: تحليل المدة، التصنيف إلى
    فئات، التجميع الإحصائي، وتوليد نصوص التقرير/config.yaml."""
    mc = measure_channels

    check("13 قناة في قائمة الإدخال", len(mc.CHANNELS) == 13, len(mc.CHANNELS))
    handles = [c["handle"] for c in mc.CHANNELS]
    channel_ids = [c["channel_id"] for c in mc.CHANNELS]
    check("لا تكرار في handle", len(set(handles)) == len(handles))
    check("لا تكرار في channel_id", len(set(channel_ids)) == len(channel_ids))
    check("كل channel_id يبدأ بـ UC",
          all(cid.startswith("UC") for cid in channel_ids),
          [cid for cid in channel_ids if not cid.startswith("UC")])
    check("قناتا Halk TV وSÖZCÜ فقط غير مؤكَّدتين",
          {c["handle"] for c in mc.CHANNELS if c.get("unconfirmed")} ==
          {"@Halktvkanali", "@Sozcutelevizyonu"})

    check("uploads_playlist_id يبدّل الحرف الثاني UC→UU",
          mc.uploads_playlist_id("UCabc123") == "UUabc123")
    try:
        mc.uploads_playlist_id("XXabc123")
        bad_id_raised = False
    except ValueError:
        bad_id_raised = True
    check("uploads_playlist_id يرفض معرّفًا لا يبدأ بـ UC", bad_id_raised)

    check("تحليل PT1H2M10S", mc.parse_iso8601_duration("PT1H2M10S") == 3730)
    check("تحليل PT45S", mc.parse_iso8601_duration("PT45S") == 45)
    check("تحليل PT0S", mc.parse_iso8601_duration("PT0S") == 0)
    check("تنسيق format_mmss", mc.format_mmss(3730) == "62:10")

    check("تصنيف < 5 د", mc.duration_bucket(200) == "< 5 د")
    check("تصنيف 5-15 د على الحد الأدنى", mc.duration_bucket(300) == "5-15 د")
    check("تصنيف > 90 د", mc.duration_bucket(6000) == "> 90 د")

    check("توصية الحد الأدنى تقطع الذيل القصير",
          mc.recommend_min_duration_seconds([60, 120, 180, 240, 600, 900]) == 60)
    check("لا توصية بلا مدد", mc.recommend_min_duration_seconds([]) is None)

    channel = {"handle": "@x", "name": "قناة×"}
    videos = [
        mc.VideoRecord("@x", "قناة×", "v1", "عنوان١", 600, "2024-01-01T00:00:00Z", False,
                        transcript_available=True, transcript_language="ar", transcript_is_manual=True),
        mc.VideoRecord("@x", "قناة×", "v2", "عنوان٢", 1200, "2024-01-03T00:00:00Z", False,
                        transcript_available=True, transcript_language="ar", transcript_is_manual=False),
        mc.VideoRecord("@x", "قناة×", "v3", "عنوان٣", 200, "2024-01-05T00:00:00Z", False,
                        transcript_available=False),
        mc.VideoRecord("@x", "قناة×", "v4", "بث مباشر", 7200, "2024-01-06T00:00:00Z", True),
        mc.VideoRecord("@x", "قناة×", "v5", "خطأ فحص", 300, "2024-01-07T00:00:00Z", False,
                        transcript_error="RequestBlocked"),
    ]
    stats = mc.compute_channel_stats(channel, videos)
    check("حجم العيّنة يشمل كل الفيديوهات", stats["sample_size"] == 5)
    check("عدّ البث المباشر", stats["live_count"] == 1, stats["live_count"])
    check("وسيط المدة يستبعد البث المباشر فقط",
          stats["median_duration"] == 450.0, stats["median_duration"])
    check("عدد المفحوصين يستبعد ما فشل فحصه (v5)", stats["transcript_checked"] == 4)
    check("نسبة توفّر النص من المفحوص فقط (2 من 4)",
          stats["transcript_available_pct"] == 50.0, stats["transcript_available_pct"])
    check("نسبة اليدوي من المتوفر فقط (1 من 2)",
          stats["transcript_manual_pct"] == 50.0, stats["transcript_manual_pct"])
    check("معدّل الرفع اليومي محسوب من مدى تاريخ النشر",
          stats["daily_upload_rate"] is not None and stats["daily_upload_rate"] > 0)

    lang_stats = mc.compute_language_stats(
        [{"handle": "@x", "language": "ar"}], {"@x": videos})
    check("تجميع اللغة يطابق تجميع القناة الوحيدة فيها",
          lang_stats["ar"]["transcript_available_pct"] == stats["transcript_available_pct"])

    table = mc.render_channel_table([stats])
    check("جدول القنوات يذكر اسم القناة", "قناة×" in table)
    lang_table = mc.render_language_table(lang_stats)
    check("جدول اللغات يذكر ar", "| ar |" in lang_table)
    errors = [{"channel": "قناة×", "video_id": "v5", "reason": "RequestBlocked"}]
    err_section = mc.render_errors_section(errors)
    check("قسم الأخطاء يذكر الفيديو والسبب", "v5" in err_section and "RequestBlocked" in err_section)
    recs = mc.render_recommendations([stats], lang_stats)
    check("قسم التوصيات يقترح حدًّا أدنى للقناة", "قناة×" in recs)

    titles_text = mc.render_titles_file(videos)
    check("ملف العناوين سطر لكل فيديو مسبوق بالمدة",
          titles_text.count("\n") == len(videos) and titles_text.startswith("10:00"))

    report = mc.render_survey_report([stats], lang_stats, errors)
    check("التقرير الكامل يحوي الجدولين وقسمي الأخطاء والتوصيات",
          all(s in report for s in ["### جدول القنوات", "### جدول اللغات", "### الأخطاء", "### التوصيات"]))

    # insert_channels_section: إضافة، ثم استبدال في المكان، بلا مسّ لبقية الملف
    base_config = "brand:\n  name: \"\"\n\nsources:\n  - name: \"x\"\n"
    sample_channels = [{
        "handle": "@x", "channel_id": "UCabc", "name": "قناة×",
        "language": "ar", "bloc": "arabic", "bias_note": "ملاحظة",
    }]
    appended = mc.insert_channels_section(base_config, sample_channels)
    check("إضافة قسم channels تُبقي بقية الملف كما هي",
          appended.startswith(base_config.rstrip("\n") + "\n") or base_config in appended)
    check("قسم channels يحوي القناة المضافة", "@x" in appended and "channel_id: UCabc" in appended)
    replaced = mc.insert_channels_section(appended, sample_channels)
    check("إعادة التشغيل على نفس المدخل بلا تغيير (لا تكرار للقسم)",
          replaced == appended and appended.count("channels:") == 1)

    import yaml as _yaml
    parsed = _yaml.safe_load(appended)
    check("channels صالح YAML وله عنصر واحد كما أُدخل",
          parsed.get("channels") == [{
              "handle": "@x", "channel_id": "UCabc", "name": "قناة×",
              "language": "ar", "bloc": "arabic", "bias_note": "ملاحظة",
              "active": True, "min_duration_minutes": 8,
              "programs": [], "exclude_patterns": [],
          }])
    check("قسم sources الأصلي محفوظ حرفيًا", "sources:\n  - name: \"x\"" in appended)


def test_actions_block_script() -> None:
    """سكربت تشخيص الحجب (tools/test_actions_block.py، Issue #626) لا شبكة
    فعلية له هنا — يُشغَّل يدويًا عبر workflow_dispatch فقط. نختبر الدوال
    الصِرفة: اختيار قناة واحدة من كل كتلة، حساب نسبة النجاح، عتبات الحكم،
    وتنسيق التقرير النهائي."""
    tab = test_actions_block

    sample_channels = [
        {"handle": "@a1", "bloc": "arabic"},
        {"handle": "@a2", "bloc": "arabic"},
        {"handle": "@t1", "bloc": "turkish"},
        {"handle": "@f1", "bloc": "persian"},
        {"handle": "@i1", "bloc": "israeli"},
    ]
    picked = tab.pick_probe_channels(sample_channels)
    check("أول قناة من كل كتلة فقط، بترتيب ظهورها",
          [c["handle"] for c in picked] == ["@a1", "@t1", "@f1", "@i1"],
          [c["handle"] for c in picked])

    # config.yaml الفعلي (Issue #626): أربع كتل، وأول قناة في كل واحدة هي
    # بالضبط القنوات الأربع التي سمّاها طلب المراجعة صراحة.
    real_channels = load_config().get("channels", [])
    check("13 قناة مثبَّتة في config.yaml", len(real_channels) == 13, len(real_channels))
    real_picked = tab.pick_probe_channels(real_channels)
    check("قنوات القياس الأربع من config.yaml الفعلي تطابق طلب المراجعة",
          [c["handle"] for c in real_picked] == ["@aljazeera", "@cnnturk", "@IRANINTL", "@C14news"],
          [c["handle"] for c in real_picked])

    check("نسبة النجاح من عدّاد فارغ صفر بلا انهيار",
          tab.success_ratio({"success": 0, "blocked": 0, "no_transcript": 0, "other": 0}) == 0.0)
    check("نسبة النجاح محسوبة من إجمالي المحاولات لا النجاح فقط",
          tab.success_ratio({"success": 30, "blocked": 5, "no_transcript": 4, "other": 1}) == 0.75)

    check("حكم لا حجب عند 70% بالضبط (الحد شامل)", tab.judge(0.70) == "لا حجب")
    check("حكم حجب جزئي دون 70%", tab.judge(0.69) == "حجب جزئي")
    check("حكم حجب جزئي عند 30% بالضبط (الحد شامل)", tab.judge(0.30) == "حجب جزئي")
    check("حكم حجب كامل دون 30%", tab.judge(0.29) == "حجب كامل")

    check("متوسط لكل فيديو من إجمالي البيانات ÷ عدد المحاولات",
          tab.data_usage_lines(40 * 1024 * 1024, 40) == [
              "إجمالي البيانات المنقولة: 40.00 ميجابايت",
              "متوسط لكل فيديو: 1024.0 كيلوبايت",
          ])
    check("لا انهيار على صفر محاولات", tab.data_usage_lines(0, 0)[1].endswith("0.0 كيلوبايت"))

    counts_40 = {"success": 30, "blocked": 5, "no_transcript": 4, "other": 1}
    report = tab.render_report("1.2.3.4", counts_40, None, 4 * 1024 * 1024)
    check("التقرير يذكر عنوان الخروج", "1.2.3.4" in report)
    check("التقرير يذكر إجمالي المحاولات (40)", "المحاولات: 40" in report)
    check("التقرير يميّز الحجب عن اللاترجمة المشروعة",
          "محجوب (IpBlocked/RequestBlocked): 5" in report and "بلا ترجمة (سبب مشروع): 4" in report)
    check("التقرير يذكر نسبة النجاح والحكم", "نسبة النجاح: 75%" in report and "الحكم: لا حجب" in report)
    check("لا نص ترجمة داخل التقرير", "transcript" not in report.lower())
    check("التقرير يذكر حالة البروكسي (غير مفعّل بلا كائن إعداد)",
          "البروكسي: غير مفعّل (اتصال مباشر)" in report)
    check("التقرير يذكر إجمالي البيانات ومتوسطها لكل فيديو",
          "إجمالي البيانات المنقولة: 4.00 ميجابايت" in report and "متوسط لكل فيديو:" in report)

    report_proxied = tab.render_report("1.2.3.4", counts_40, object(), 0)
    check("التقرير يذكر البروكسي مفعّلًا عند وجود كائن إعداد (أيًّا كان نوعه)",
          "البروكسي: مفعّل (Webshare)" in report_proxied)


def test_proxy_config() -> None:
    """وحدة إعداد البروكسي المشتركة (src/proxy_config.py، Issue #629):
    وجود سرّي Webshare في البيئة ⇒ كائن إعداد فعلي، غيابهما ⇒ None (تشغيل
    مباشر بلا بروكسي). لا شبكة هنا -- WebshareProxyConfig لا يتصل بشيء عند
    الإنشاء، هو حاوية بيانات فقط تُستهلَك لاحقًا داخل youtube_transcript_api."""
    saved = {
        proxy_config.USERNAME_VAR: os.environ.pop(proxy_config.USERNAME_VAR, None),
        proxy_config.PASSWORD_VAR: os.environ.pop(proxy_config.PASSWORD_VAR, None),
    }
    try:
        cfg = proxy_config.get_proxy_config()
        check("لا سرّين في البيئة ⇒ None (اتصال مباشر)", cfg is None)
        check("سطر الحالة يطابق غياب البروكسي", proxy_config.proxy_status_line(cfg) == "البروكسي: غير مفعّل (اتصال مباشر)")

        os.environ[proxy_config.USERNAME_VAR] = "user1"
        cfg = proxy_config.get_proxy_config()
        check("اسم مستخدم بلا كلمة مرور لا يزال None (كلاهما مطلوب معًا)", cfg is None)

        os.environ[proxy_config.PASSWORD_VAR] = "pass1"
        cfg = proxy_config.get_proxy_config()
        check("وجود السرّين معًا ⇒ كائن WebshareProxyConfig", cfg is not None)
        check("بيانات الاعتماد تُمرَّر كما هي إلى الكائن",
              cfg.proxy_username == "user1" and cfg.proxy_password == "pass1")
        check("سطر الحالة يطابق تفعيل البروكسي", proxy_config.proxy_status_line(cfg) == "البروكسي: مفعّل (Webshare)")
        check("لا بيانات اعتماد مطبوعة داخل تمثيل الكائن (repr) أو سطر الحالة",
              "user1" not in proxy_config.proxy_status_line(cfg) and
              "pass1" not in proxy_config.proxy_status_line(cfg))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_youtube_collect() -> None:
    """المرحلة الأولى من مسار يوتيوب (src/youtube_collect.py، Issue #631):
    منطق صِرف بلا شبكة فقط -- تطبيق الحرّاس بالترتيب الملزِم، الترتيب
    بالمدة والقصّ، وسجل منع التكرار. لا اختبار هنا لـfetch_playlist_video_ids
    أو fetch_videos_details (يستدعيان requests فعليًا) تماشيًا مع نفس
    الاتفاق المتّبع في test_measure_channels/test_actions_block_script."""
    yc = youtube_collect

    check("uploads_playlist_id يبدّل الحرف الثاني UC→UU",
          yc.uploads_playlist_id("UCabc123") == "UUabc123")
    try:
        yc.uploads_playlist_id("XXabc123")
        bad_id_raised = False
    except ValueError:
        bad_id_raised = True
    check("uploads_playlist_id يرفض معرّفًا لا يبدأ بـ UC", bad_id_raised)

    check("تحليل PT1H2M10S", yc.parse_iso8601_duration("PT1H2M10S") == 3730)
    check("تحليل PT45S", yc.parse_iso8601_duration("PT45S") == 45)

    now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    check("داخل نافذة 30 ساعة", yc.within_lookback(
        (now - timedelta(hours=10)).isoformat(), 30, now))
    check("خارج نافذة 30 ساعة", not yc.within_lookback(
        (now - timedelta(hours=31)).isoformat(), 30, now))
    check("تاريخ فاسد لا يُعدّ ضمن النافذة، بلا انهيار",
          not yc.within_lookback("ليس تاريخًا", 30, now))
    check("تاريخ فارغ لا يُعدّ ضمن النافذة", not yc.within_lookback("", 30, now))

    item = {
        "id": "vid123",
        "snippet": {"title": "تحليل الوضع الاقتصادي", "publishedAt": "2026-08-29T10:00:00Z",
                    "liveBroadcastContent": "none"},
        "contentDetails": {"duration": "PT12M30S"},
    }
    channel = {"name": "قناة×", "bloc": "arabic", "language": "ar", "handle": "@x"}
    video = yc.parse_video_item(item, channel)
    check("تحليل عنصر فيديو: المعرّف والقناة والمدة",
          video.video_id == "vid123" and video.channel == "قناة×" and video.duration_seconds == 750)
    check("رابط الفيديو مبنيّ من المعرّف",
          video.video_url == "https://www.youtube.com/watch?v=vid123")
    check("فيديو غير مباشر (liveBroadcastContent=none)", video.is_live is False)

    live_item = dict(item, snippet={**item["snippet"], "liveBroadcastContent": "live"})
    check("liveBroadcastContent=live يُعدّ بثًا مباشرًا",
          yc.parse_video_item(live_item, channel).is_live is True)
    upcoming_item = dict(item, snippet={**item["snippet"], "liveBroadcastContent": "upcoming"})
    check("liveBroadcastContent=upcoming يُعدّ بثًا مجدولًا",
          yc.parse_video_item(upcoming_item, channel).is_live is True)

    cfg = load_config()
    base_channel = {"name": "قناة×", "bloc": "arabic", "handle": "@x", "exclude_patterns": ["نشرة"]}

    def mk_video(duration_min=10, is_live=False, title="خبر عاجل عن الاقتصاد", vid="v1"):
        return yc.Video(video_id=vid, channel="قناة×", bloc="arabic", language="ar",
                        video_title=title, video_url=f"https://youtube.com/watch?v={vid}",
                        duration_seconds=duration_min * 60, published_at="2026-08-29T10:00:00Z",
                        is_live=is_live)

    ok, reason = yc.passed_guards(mk_video(), base_channel, cfg, {})
    check("فيديو عادي ضمن المدة يجتاز الحرّاس", ok, reason)

    ok, reason = yc.passed_guards(mk_video(is_live=True), base_channel, cfg, {})
    check("بث مباشر يُستبعد حين exclude_live الافتراضي مفعّل",
          not ok and reason == "بث مباشر أو مجدول")

    ok, reason = yc.passed_guards(
        mk_video(is_live=True), {**base_channel, "exclude_live": False}, cfg, {})
    check("تجاوز exclude_live لقناة بعينها يُبقي البث المباشر", ok, reason)

    ok, reason = yc.passed_guards(mk_video(duration_min=200), base_channel, cfg, {})
    check("تجاوز الحد الأقصى للمدة يُستبعد", not ok and "الحد الأقصى" in reason, reason)

    ok, reason = yc.passed_guards(mk_video(duration_min=3), base_channel, cfg, {})
    check("أقل من الحد الأدنى للمدة يُستبعد", not ok and "الحد الأدنى" in reason, reason)

    ok, reason = yc.passed_guards(
        mk_video(duration_min=5), {**base_channel, "min_duration_minutes": 3}, cfg, {})
    check("تجاوز الحد الأدنى لقناة بعينها يسمح بفيديو أقصر من الافتراضي", ok, reason)

    ok, reason = yc.passed_guards(mk_video(title="نشرة الأخبار المسائية"), base_channel, cfg, {})
    check("عنوان يطابق نمط استبعاد القناة يُستبعد",
          not ok and "نشرة" in reason, reason)

    ok, reason = yc.passed_guards(mk_video(vid="seen1"), base_channel, cfg, {"seen1": "2026-08-28"})
    check("فيديو مسجَّل سابقًا في السجل يُستبعد",
          not ok and "السجل" in reason, reason)

    survivors = [mk_video(duration_min=8, vid="a"), mk_video(duration_min=20, vid="b"),
                 mk_video(duration_min=12, vid="c")]
    top2 = yc.select_top(survivors, 2)
    check("الترتيب بالمدة تنازليًا ثم القصّ لأعلى اثنين",
          [v.video_id for v in top2] == ["b", "c"], [v.video_id for v in top2])
    check("القصّ لا يتجاوز عدد المتاح", len(yc.select_top(survivors, 10)) == 3)

    # السجل: تحميل/تسجيل/حفظ مع تقليم حسب الاحتفاظ
    seen_path = yc.SEEN_FILE
    original = seen_path.read_text(encoding="utf-8") if seen_path.exists() else None
    try:
        if seen_path.exists():
            seen_path.unlink()
        check("لا ملف سجل بعد ⇒ قاموس فارغ", yc.load_seen() == {})
        seen = {}
        yc.mark_seen(seen, "old1", "2026-08-01")
        yc.mark_seen(seen, "new1", "2026-08-29")
        yc.save_seen(seen, retention_days=14, now=now)
        reloaded = yc.load_seen()
        check("التقليم يحذف المدخل الأقدم من نافذة الاحتفاظ",
              "old1" not in reloaded and "new1" in reloaded, reloaded)
    finally:
        if original is None:
            seen_path.unlink(missing_ok=True)
        else:
            seen_path.write_text(original, encoding="utf-8")


def test_youtube_extract() -> None:
    """المرحلة الثانية (src/youtube_extract.py، Issue #631)، ثم إصلاح خمسة
    أعطال كشفتها المراجعة اليدوية للتشغيلة الأولى (Issue #635): طوابع زمنية
    مختلَقة، إخراج JSON نصّي هشّ، ترجمة عربية لم تقع، أسماء أعلام مكسورة،
    ونشرات/رياضة نجت من حرّاس المدة. لا شبكة، لا نموذج فعلي، ولا نص ترجمة
    حقيقي يُستعمل في هذا الاختبار."""
    ye = youtube_extract

    good_point = {
        "statement": "أعلن المسؤول عن خطة اقتصادية جديدة",
        "speaker": "وزير المالية",
        "quote_original": "we are launching a new plan",
        "quote_arabic": "نطلق خطة جديدة",
        "anchor_text": "we are launching a new",
        "type": "fact",
        "topic_hint": "اقتصاد وزراء",
    }

    # ── العطل ١: تحليل الطابع الزمني النصّي ──
    check("MM:SS يُحلَّل إلى ثوانٍ", ye.parse_timestamp("01:05") == 65)
    check("HH:MM:SS يُحلَّل إلى ثوانٍ", ye.parse_timestamp("01:02:10") == 3730)
    check("رقم مجرّد (لا صيغة زمن) يُرفَض بـNone", ye.parse_timestamp("570") is None)
    check("نص فارغ يُرفَض بـNone", ye.parse_timestamp("") is None)
    check("مسافات فقط تُرفَض بـNone", ye.parse_timestamp("   ") is None)
    check("قيمة غير نصّية تُرفَض بـNone", ye.parse_timestamp(42) is None)
    check("ثوانٍ خارج 0-59 تُرفَض بـNone", ye.parse_timestamp("01:75") is None)

    # ── Issue #642 العطل ١: الأقواس المربّعة (كما تظهر في النص المصوغ
    # [00:12:34]) تُجرَّد قبل التحليل -- النموذج ينسخها طاعةً حرفية لتعليمة
    # "انسخ كما هو"، وقبل الإصلاح كانت هذه الصيغة السليمة تُرفَض ظلمًا ──
    check("[HH:MM:SS] بقوسين يُحلَّل صحيحًا بعد تجريد القوسين",
          ye.parse_timestamp("[00:12:34]") == 754)
    check("HH:MM:SS بلا قوسين يُحلَّل كما كان", ye.parse_timestamp("00:12:34") == 754)
    check("MM:SS بلا قوسين يُحلَّل صحيحًا", ye.parse_timestamp("12:34") == 754)
    check("[MM:SS] بقوسين يُحلَّل صحيحًا بعد تجريد القوسين",
          ye.parse_timestamp("[12:34]") == 754)
    check("HH:MM:SS بمسافات بادئة ولاحقة يُحلَّل بعد التجريد",
          ye.parse_timestamp("  00:12:34  ") == 754)
    check("نص غير رقمي (abc) يبقى مرفوضًا بعد إصلاح الأقواس",
          ye.parse_timestamp("abc") is None)
    check("قيمة مستحيلة (99:99:99) تبقى مرفوضة", ye.parse_timestamp("99:99:99") is None)

    # ── Issue #644 الإصلاح ١: format_transcript لم تعد تنتج خانة ساعة --
    # صيغة MM:SS بدقائق تتجاوز ٥٩ بلا سقف (فيديو ساعة ونصف مثلًا)، وparse_timestamp
    # تبقى قابلة لهذه الصيغة مباشرةً (لا حاجة لخانة ساعة لتفسير رقم دقائق كبير) ──
    check("دقائق تتجاوز ٥٩ في MM:SS تُحلَّل بلا سقف (Issue #644 الإصلاح ١)",
          ye.parse_timestamp("95:12") == 95 * 60 + 12)
    check("[MM:SS] بدقائق فوق ٥٩ وبقوسين يُحلَّل بعد تجريد القوسين",
          ye.parse_timestamp("[125:00]") == 125 * 60)

    # ── العطل ٣+٤: كاشف الحرف غير العربي ──
    check("نص عربي فصيح بلا شوائب لا يُطابِق شيئًا",
          ye.find_non_arabic_char("أعلن الوزير عن خطة جديدة ٢٠٢٦") is None)
    check("حرف عبري يُكتَشف", ye.find_non_arabic_char("יעקב מרגיס") == "י")
    check("حرف لاتيني مفرد داخل كلمة عربية يُكتَشف (خلط الأعلام، العطل ٤)",
          ye.find_non_arabic_char("ملih غوكجيك") == "i")
    check("حرف فارسي غير عربي (گ) يُكتَشف", ye.find_non_arabic_char("گفتگو") == "گ")
    check("أرقام وعلامات ترقيم عربية لا تُعدّ شائبة",
          ye.find_non_arabic_char("العدد ٢٤، بالمئة %١٠٠!") is None)

    # ── Issue #639 العطل ٢ب: حارس اللغة معكوس المنطق -- يسمح بالعربية
    # والأرقام والترقيم والمسافات فقط، بدل قائمة أبجديات محظورة تفوّت
    # أبجديات لم تُدرَج صراحة (الدليل أ في الـIssue: حرف صيني مرّ من الحارس
    # القديم) ──
    check("حرف صيني يُكتَشف (الدليل أ، Issue #639)",
          ye.find_non_arabic_char("يطالب بمحاسبة الم煽يين") == "煽")
    check("حرف كيريلي يُكتَشف", ye.find_non_arabic_char("بوتين путин") == "п")
    check("حرف يوناني يُكتَشف", ye.find_non_arabic_char("كلمة βeta") == "β")
    check("نص عربي بأرقام وترقيم مختلطة لا يزال يُقبَل بعد عكس المنطق",
          ye.find_non_arabic_char("قال الوزير: «رقم ١٢٣ - نسبة 45%»") is None)

    # ── Issue #642 العطل ٢: حارس اللغة كان يسمح بفئة الترقيم فقط، فيرفض
    # رموزًا رياضية/علمية مشروعة تمامًا بصفتها "حرفًا غير عربي" (شاهد
    # الـIssue: '+' رفضت نقطة صحيحة). المعيار الجديد: نرفض الحروف الأجنبية
    # فقط لا الرموز ──
    check("علامة الجمع + مقبولة الآن ولا تُرفَض بصفتها حرفًا أجنبيًا",
          ye.find_non_arabic_char("زيادة +٢٪ في الناتج") is None)
    for symbol in "+−%$€£°=<>×÷~^*/\\|@#&":
        check(f"رمز رياضي/علمي مقبول في نص عربي: {symbol!r}",
              ye.find_non_arabic_char(f"نسبة {symbol} في التقرير") is None)
    check("الحروف اللاتينية تبقى مرفوضة رغم توسيع الرموز",
          ye.find_non_arabic_char("نمو Growth بنسبة ٥٪") is not None)
    check("الحروف العبرية تبقى مرفوضة رغم توسيع الرموز",
          ye.find_non_arabic_char("שלום عربي") is not None)

    # ── Issue #639 العطل ٢أ: تطبيع الحروف الفارسية/التركية الشائعة قبل
    # فحص اللغة -- تطبيع لا حذف، فالنقطة تُقبَل بعده بدل خسارتها ──
    check("ی الفارسية تُطبَّع إلى ي العربية", ye.normalize_persian_chars("ی") == "ي")
    check("ک الفارسية تُطبَّع إلى ك العربية", ye.normalize_persian_chars("ک") == "ك")
    check("پ الفارسية تُطبَّع إلى ب العربية", ye.normalize_persian_chars("پ") == "ب")
    check("چ الفارسية تُطبَّع إلى تش (حرفان، لا مقابل عربي مفرد)",
          ye.normalize_persian_chars("چ") == "تش")
    check("گ الفارسية تُطبَّع إلى غ العربية", ye.normalize_persian_chars("گ") == "غ")
    check("ژ الفارسية تُطبَّع إلى ج العربية", ye.normalize_persian_chars("ژ") == "ج")
    check("الفاصل غير الظاهر ZWNJ يُحذف",
          ye.normalize_persian_chars("می‌روم") == "ميروم")
    check("مجتبی (فارسي) تُطبَّع إلى مجتبي (عربي خالص، شاهد الـIssue)",
          ye.normalize_persian_chars("مجتبی") == "مجتبي")
    check("پورمحسن (فارسي) تُطبَّع إلى بورمحسن (عربي خالص، شاهد الـIssue)",
          ye.normalize_persian_chars("پورمحسن") == "بورمحسن")
    check("نص عربي فصيح بلا شوائب فارسية لا يتغيّر بالتطبيع",
          ye.normalize_persian_chars("أعلن الوزير خطة جديدة") == "أعلن الوزير خطة جديدة")
    check("النص المطبَّع يجتاز فحص اللغة بعد أن كان سيُرفَض قبل التطبيع",
          ye.find_non_arabic_char(ye.normalize_persian_chars("مجتبی")) is None)

    # ── validate_point: يعيد الآن رباعيًا (صالحة، سبب، فئة، طُبِّعت) ──
    ok, reason, kind, normalized = ye.validate_point(dict(good_point))
    check("نقطة كاملة الحقول صالحة", ok and kind == "", reason)
    check("نقطة عربية خالصة أصلًا: normalized == False", ok and normalized is False, normalized)

    # نقطة تحوي حروفًا فارسية شائعة في statement وspeaker -- كانت سترفض
    # بالكامل قبل الإصلاح، الآن تُطبَّع وتُقبَل (Issue #639 العطل ٢أ)
    persian_point = {**good_point, "statement": "أعلن مجتبی عن خطة جديدة",
                      "speaker": "پورمحسن، مسؤول حكومي"}
    ok, reason, kind, normalized = ye.validate_point(persian_point)
    check("نقطة بحروف فارسية شائعة تُقبَل بعد التطبيع التلقائي",
          ok and kind == "", (reason, persian_point))
    check("normalized == True بعد تطبيع فعلي أنقذ النقطة", normalized is True)
    check("الحقل statement استُبدِل بنسخته المطبَّعة (لا الفارسية الخام)",
          "مجتبی" not in persian_point["statement"] and "مجتبي" in persian_point["statement"],
          persian_point["statement"])

    for missing in ye.REQUIRED_FIELDS:
        broken = {k: v for k, v in good_point.items() if k != missing}
        ok, reason, kind, normalized = ye.validate_point(broken)
        check(f"حقل ناقص ({missing}) يُرفَض", not ok and missing in reason, reason)

    ok, reason, kind, normalized = ye.validate_point({**good_point, "speaker": "   "})
    check("حقل نصّي فارغ (مسافات فقط) يُرفَض", not ok, reason)

    ok, reason, kind, normalized = ye.validate_point({**good_point, "type": "rumor"})
    check("تصنيف خارج fact/opinion/forecast يُرفَض", not ok and "تصنيف" in reason, reason)

    for valid_type in ("fact", "opinion", "forecast"):
        ok, reason, kind, normalized = ye.validate_point({**good_point, "type": valid_type})
        check(f"تصنيف {valid_type} صالح", ok, reason)

    # Issue #644 الإصلاح ٢: validate_point لم تعد تتحقق من طابع زمني أصلًا --
    # anchor_text حقل نصّي عادي كباقي الحقول (فارغ ⇒ رفض بفئة other، كما أي
    # حقل نصّي آخر)، وفئة "timestamp_format" القديمة لم تعد ممكنة الحدوث من
    # هذه الدالة إطلاقًا (لا رقم يُطلَب من النموذج فلا صيغة رقمية ليُخطئ فيها).
    ok, reason, kind, normalized = ye.validate_point({**good_point, "anchor_text": ""})
    check("anchor_text فارغ يُرفَض كأي حقل نصّي إلزامي آخر",
          not ok and kind == "other", reason)

    ok, reason, kind, normalized = ye.validate_point({**good_point, "anchor_text": "   "})
    check("anchor_text بمسافات فقط يُرفَض أيضًا", not ok and kind == "other", reason)

    ok, reason, kind, normalized = ye.validate_point({**good_point, "statement": "יעקב מרגיס מסיים קריירה"})
    check("عبرية في statement تُرفَض بفئة language", not ok and kind == "language", reason)

    ok, reason, kind, normalized = ye.validate_point({**good_point, "speaker": "ملih غوكجيك"})
    check("خلط لاتيني/عربي في speaker يُرفَض بفئة language", not ok and kind == "language", reason)

    ok, reason, kind, normalized = ye.validate_point({**good_point, "quote_arabic": "we launch a plan"})
    check("لاتينية في quote_arabic تُرفَض بفئة language", not ok and kind == "language", reason)

    ok, reason, kind, normalized = ye.validate_point(dict(good_point))
    check("quote_original بلغة أجنبية (لاتينية) مستثنى عمدًا من فحص اللغة", ok, reason)

    check("عنصر ليس كائن JSON يُرفَض بلا انهيار", ye.validate_point("ليس كائنًا")[0] is False)

    prompt = ye.load_prompt()
    check("ملف البرومبت منفصل عن الكود وغير فارغ", len(prompt) > 200)
    check("البرومبت يذكر التصنيفات الثلاثة",
          all(t in prompt for t in ("fact", "opinion", "forecast")))
    check("البرومبت يوضّح صيغة الأختام الزمنية المتوقَّعة في المُدخَل (Issue #644 الإصلاح ١: بلا خانة ساعة)",
          "[12:34]" in prompt and "[00:12:34]" not in prompt)
    check("البرومبت يذكر قاعدة أسماء الأعلام غير المسنودة (Issue #639 العطل ١ بند أ)",
          "quote_original" in prompt and "بايدن" in prompt)
    check("البرومبت يوضّح كتابة الأسماء الفارسية/التركية بحروف عربية خالصة (العطل ٢ج)",
          "مجتبى" in prompt and "بورمحسن" in prompt)

    # ── Issue #644 الإصلاح ٣: تبسيط البرومبت -- تعليمة المرساة الواحدة
    # حرفيًا بدل كل تعليمات نسخ/تقدير الختم القديمة ──
    check("البرومبت يذكر حقل anchor_text في المخرج", "anchor_text" in prompt)
    check("البرومبت لا يذكر حقل timestamp (حُذف من المخطّط، Issue #644 الإصلاح ٢)",
          "`timestamp`" not in prompt)
    check("البرومبت يتضمّن تعليمة المرساة الواحدة حرفيًا",
          ("انسخ في `anchor_text` أول أربع إلى ست كلمات من السطر الذي أخذت\n"
           "منه الاقتباس") in prompt)
    check("البرومبت يشرح معنى علامة الحذف الصريحة في النص المقصوص",
          ye.TRUNCATION_MARKER in prompt)

    # ── Issue #639 العطل ٣: تعريف political_analysis في TOPIC_SYSTEM مشدَّد
    # ليستبعد المقابلات الشخصية صراحة ──
    check("TOPIC_SYSTEM يستبعد المقابلات الشخصية والسير الذاتية من political_analysis",
          "المقابلات الشخصية" in ye.TOPIC_SYSTEM and "المسار المهني" in ye.TOPIC_SYSTEM)
    check("TOPIC_SYSTEM يتضمّن مثالي التصنيف الحرفيين من الـIssue",
          "بداياته وحياته المهنية" in ye.TOPIC_SYSTEM
          and "تداعيات العقوبات على إيران" in ye.TOPIC_SYSTEM)

    # ── Issue #639 العطل ١ بند ب: find_unsourced_name -- تحقّق بأفضل ما
    # يمكن، قائمة مرجعية صغيرة لا استخراج أعلام عام ──
    known_figures = [{"ar": "بايدن", "aliases": ["biden"]},
                      {"ar": "ترامب", "aliases": ["trump"]}]
    check("اسم عربي من القائمة بلا أي alias في quote_original ⇒ يُبلَّغ عنه",
          ye.find_unsourced_name("ربما تحاول إدارة جو بايدن إعادة تشكيل المنطقة",
                                  "Amerika bölgede terör örgütlerinin olmadığı bir yapı istiyor",
                                  known_figures) == "بايدن")
    check("اسم عربي من القائمة وalias مطابق (بغضّ النظر عن حالة الأحرف) في "
          "quote_original ⇒ لا تحذير",
          ye.find_unsourced_name("قال بايدن إن الإدارة الأمريكية ستتحرك",
                                  "President Biden said the administration will act",
                                  known_figures) is None)
    check("لا اسم من القائمة في statement أصلًا ⇒ لا تحذير",
          ye.find_unsourced_name("قالت الحكومة إنها ستتحرك",
                                  "Amerika bölgede terör örgütlerinin olmadığı bir yapı istiyor",
                                  known_figures) is None)
    check("قائمة known_figures فارغة ⇒ لا تحذير أبدًا (لا انهيار)",
          ye.find_unsourced_name("قال بايدن إن الإدارة ستتحرك", "some text", []) is None)

    # ── format_transcript: صياغة النص بأختام ظاهرة قبل كل مقطع (العطل ١) ──
    class _Segment:
        def __init__(self, text, start):
            self.text, self.start = text, start

    # Issue #644 الإصلاح ١: بلا خانة ساعة -- MM:SS فقط، والدقائق تتجاوز ٥٩
    # بلا سقف (٣٦٦١ث ⇐ ٦١ دقيقة، لا "01:01:01" بخانة ساعة منفصلة).
    fetched = [_Segment("مرحبًا", 0), _Segment("بكم", 754), _Segment("جميعًا", 3661)]
    formatted = ye.format_transcript(fetched)
    check("كل مقطع يسبقه ختمه الزمني MM:SS بلا خانة ساعة (Issue #644 الإصلاح ١)",
          formatted == "[00:00] مرحبًا\n[12:34] بكم\n[61:01] جميعًا", formatted)

    # ── parse_transcript_segments وresolve_timestamp: استخراج الطابع بالبحث
    # النصّي عن anchor_text بدل طلب رقم من النموذج (Issue #644 الإصلاح ٢) ──
    sample_transcript = ("[00:00] مرحبًا بكم في النشرة\n"
                          "[00:12] قال الوزير، إننا نطلق خطة اقتصادية جديدة اليوم\n"
                          "[00:20] شكرًا لمتابعتكم")
    segments = ye.parse_transcript_segments(sample_transcript)
    check("parse_transcript_segments تحلّل كل سطر إلى (ثوانٍ، نص)",
          segments == [(0, "مرحبًا بكم في النشرة"),
                       (12, "قال الوزير، إننا نطلق خطة اقتصادية جديدة اليوم"),
                       (20, "شكرًا لمتابعتكم")], segments)

    truncated_transcript = (f"[00:00] مرحبًا\n{ye.TRUNCATION_MARKER}\n[00:20] شكرًا")
    check("أسطر لا تطابق [MM:SS] (كعلامة الحذف) تُهمَل بصمت لا تُحسَب مقطعًا",
          ye.parse_transcript_segments(truncated_transcript) == [(0, "مرحبًا"), (20, "شكرًا")])

    check("resolve_timestamp: تطابق تام (بلا فروق تنسيقية) يعيد ثانية المقطع",
          ye.resolve_timestamp("قال الوزير، إننا نطلق خطة اقتصادية جديدة اليوم",
                                segments) == 12)
    check("resolve_timestamp: تطبيع المسافات المضاعفة والترقيم لا يمنع التطابق",
          ye.resolve_timestamp("قال  الوزير إننا نطلق", segments) == 12)
    check("resolve_timestamp: تجاهل التشكيل لا يمنع التطابق",
          ye.resolve_timestamp("قَالَ الْوَزِيرُ إِنَّنَا نُطْلِقُ", segments) == 12)
    check("resolve_timestamp: مرساة أول ٦ كلمات تطابق مقطعًا آخر بلا لبس",
          ye.resolve_timestamp("مرحبًا بكم في النشرة", segments) == 0)
    check("resolve_timestamp: عند فشل التطابق التام، محاولة ثانية بأول ٣ كلمات فقط",
          ye.resolve_timestamp("قال الوزير إننا نطلق شيئًا لم يُقَل قط", segments) == 12)
    check("resolve_timestamp: فشل نهائي (لا تطابق حتى بأول ٣ كلمات) يعيد None",
          ye.resolve_timestamp("كلام لا علاقة له بأي مقطع هنا إطلاقًا", segments) is None)
    check("resolve_timestamp: نص فارغ يعيد None بلا انهيار",
          ye.resolve_timestamp("", segments) is None)
    check("resolve_timestamp: قيمة غير نصّية تعيد None بلا انهيار",
          ye.resolve_timestamp(None, segments) is None)

    # ── extract_points: إخراج مهيكل (tool_use) لا JSON نصّي (العطل ٢) ──
    class _Block:
        def __init__(self, type_, input_=None, text=None):
            self.type, self.input, self.text = type_, input_, text

    class _Resp:
        def __init__(self, content, stop_reason=None, usage=None):
            self.content = content
            self.stop_reason = stop_reason
            self.usage = usage

    class _Usage:
        def __init__(self, input_tokens, output_tokens):
            self.input_tokens, self.output_tokens = input_tokens, output_tokens

    class _Messages:
        def __init__(self, responses):
            self._responses = list(responses)
            self.calls: list = []

        def create(self, **kw):
            self.calls.append(kw)
            return self._responses.pop(0)

    class _Client:
        def __init__(self, responses):
            self.messages = _Messages(responses)

    extract_cfg = load_config()

    good_raw = {**good_point, "anchor_text": "نص"}
    client = _Client([_Resp([_Block("tool_use", input_={"points": [good_raw]})])])
    valid, rejected, error, truncation_note = ye.extract_points(
        "فيديو تجريبي", "[00:05] نص", "ar", duration_seconds=600,
        cfg=extract_cfg, client=client)
    check("extract_points: نقطة صالحة عبر إخراج مهيكل تُقبَل بلا خطأ عام",
          error is None and len(valid) == 1 and not rejected, (valid, rejected, error))
    check("extract_points: نداء النموذج يستعمل tool_use بمخطط extract_points لا JSON نصّي",
          client.messages.calls[0]["tools"][0]["name"] == "extract_points" and
          client.messages.calls[0]["tool_choice"] == {"type": "tool", "name": "extract_points"})
    check("extract_points: النص المُرسَل للنموذج يحوي الأختام الظاهرة",
          "[00:05]" in client.messages.calls[0]["messages"][0]["content"])
    # Issue #644 الإصلاح ٢: طابع الحل الجذري -- لا رقم من النموذج، بل
    # anchor_text يُبحَث عنه في مقاطع النص فعليًا ويُستخرَج طابعها.
    check("extract_points: anchor_text يُحوَّل إلى طابع محلول من المقطع المطابق",
          valid and valid[0]["timestamp"] == 5, valid)

    # anchor_text بفروق تنسيقية طفيفة (علامة ترقيم لاصقة) لا يزال يُطابَق
    # بعد التطبيع في resolve_timestamp.
    punct_raw = {**good_point, "anchor_text": "نص،"}
    client = _Client([_Resp([_Block("tool_use", input_={"points": [punct_raw]})])])
    valid, rejected, error, truncation_note = ye.extract_points(
        "فيديو تجريبي", "[00:05] نص", "ar", duration_seconds=600,
        cfg=extract_cfg, client=client)
    check("extract_points: anchor_text بترقيم لاصق يُطابَق بعد التطبيع",
          error is None and len(valid) == 1 and not rejected and valid[0]["timestamp"] == 5,
          (valid, rejected, error))

    # العطل ١ بند ج (الحارس الأخير) يبقى للأمان حتى بعد Issue #644 -- طابع
    # محلول فعليًا من مقطع حقيقي في النص لكن يتجاوز مدة الفيديو المُعلَنة
    # (بيانات وصفية غير متّسقة، لا خطأ في resolve_timestamp نفسها) يُرفَض.
    overflow_raw = {**good_point, "anchor_text": "نص طويل هنا"}
    client = _Client([_Resp([_Block("tool_use", input_={"points": [overflow_raw]})])])
    valid, rejected, error, truncation_note = ye.extract_points(
        "فيديو تجريبي", "[20:00] نص طويل هنا فعلا", "ar", duration_seconds=531,
        cfg=extract_cfg, client=client)
    check("طابع محلول يتجاوز مدة الفيديو المُعلَنة يُرفَض ولا يدخل المخرج",
          error is None and valid == [] and len(rejected) == 1, (valid, rejected))
    check("سبب الرفض يُصنَّف timestamp للتغذية في stats",
          rejected and rejected[0]["kind"] == "timestamp", rejected)
    check("رسالة رفض تجاوز المدة تحوي الطابع المحلول ومدة الفيديو",
          rejected and "1200" in rejected[0]["reason"] and "531" in rejected[0]["reason"], rejected)

    # نقطة بلغة غير عربية تُرفَض وتُصنَّف language
    bad_lang_raw = {**good_point, "statement": "יעקב מרגיס", "anchor_text": "نص"}
    client = _Client([_Resp([_Block("tool_use", input_={"points": [bad_lang_raw]})])])
    valid, rejected, error, truncation_note = ye.extract_points(
        "فيديو تجريبي", "نص", "he", duration_seconds=600, cfg=extract_cfg, client=client)
    check("نقطة بحرف غير عربي تُرفَض وتُصنَّف language",
          valid == [] and rejected and rejected[0]["kind"] == "language", rejected)

    # Issue #644 الإصلاح ٢ (و): فشل resolve_timestamp في إيجاد anchor_text
    # (هنا النص المُرسَل بلا أي سطر [MM:SS] فمقاطعه فارغة) يبقي النقطة صالحة
    # بطابع None -- عدّاد points_timestamp_unresolved في run() لا رفض.
    unresolved_raw = {**good_point, "anchor_text": "أي كلام غير موجود في مقطع"}
    client = _Client([_Resp([_Block("tool_use", input_={"points": [unresolved_raw]})])])
    valid, rejected, error, truncation_note = ye.extract_points(
        "فيديو تجريبي", "نص", "ar", duration_seconds=600, cfg=extract_cfg, client=client)
    check("نقطة بمرساة لم تُوجَد تبقى صالحة ولا تُرفَض (Issue #644 الإصلاح ٢)",
          error is None and len(valid) == 1 and not rejected, (valid, rejected, error))
    check("timestamp يبقى None في النقطة الصالحة عند فشل resolve_timestamp",
          valid and valid[0]["timestamp"] is None, valid)

    # ── Issue #639 العطل ٢أ: نقطة بحروف فارسية شائعة كانت سترفض بالكامل
    # قبل الإصلاح -- الآن تُطبَّع تلقائيًا داخل extract_points (عبر
    # validate_point) وتُقبَل، وتحمل علامة _normalized الداخلية للعدّاد
    # points_normalized في run() ──
    persian_raw = {**good_point, "statement": "أعلن مجتبی عن خطة جديدة", "anchor_text": "نص"}
    client = _Client([_Resp([_Block("tool_use", input_={"points": [persian_raw]})])])
    valid, rejected, error, truncation_note = ye.extract_points(
        "فيديو تجريبي", "نص", "fa", duration_seconds=600, cfg=extract_cfg, client=client)
    check("نقطة بحروف فارسية شائعة تُقبَل بعد التطبيع لا تُرفَض",
          error is None and len(valid) == 1 and not rejected, (valid, rejected, error))
    check("النقطة الصالحة تحمل علامة _normalized == True (Issue #639 العطل ٢أ)",
          valid and valid[0].get("_normalized") is True, valid)

    # ── Issue #639 العطل ١ بند ب: اسم علم غير مسنود في quote_original ⇒
    # تحذير عبر raw["_unsourced_name"] لا رفض -- النقطة تبقى صالحة ──
    unsourced_cfg = load_config()
    unsourced_cfg["youtube"]["extract"]["known_figures"] = [
        {"ar": "بايدن", "aliases": ["biden"]}]

    unsourced_raw = {**good_point,
                      "statement": "ربما تحاول إدارة جو بايدن إعادة تشكيل المنطقة",
                      "quote_original": "Amerika bölgede terör örgütlerinin olmadığı bir yapı istiyor",
                      "anchor_text": "نص"}
    client = _Client([_Resp([_Block("tool_use", input_={"points": [unsourced_raw]})])])
    valid, rejected, error, truncation_note = ye.extract_points(
        "فيديو تجريبي", "نص", "tr", duration_seconds=600, cfg=unsourced_cfg, client=client)
    check("نقطة باسم علم غير مسنود تبقى صالحة (تحذير لا رفض تلقائي)",
          error is None and len(valid) == 1 and not rejected, (valid, rejected, error))
    check("النقطة الصالحة تحمل علامة _unsourced_name بالاسم المشكوك فيه",
          valid and valid[0].get("_unsourced_name") == "بايدن", valid)

    sourced_raw = {**good_point, "statement": "قال بايدن إن الإدارة الأمريكية ستتحرك",
                    "quote_original": "President Biden said the administration will act",
                    "anchor_text": "نص"}
    client = _Client([_Resp([_Block("tool_use", input_={"points": [sourced_raw]})])])
    valid, rejected, error, truncation_note = ye.extract_points(
        "فيديو تجريبي", "نص", "en", duration_seconds=600, cfg=unsourced_cfg, client=client)
    check("اسم علم مسنود فعلًا (alias مطابق في quote_original) لا يُثير تحذيرًا",
          valid and valid[0].get("_unsourced_name") is None, valid)

    # إخراج مهيكل غير صالح في المحاولة الأولى ثم صالح في الثانية (إعادة المحاولة)
    good_raw_retry = {**good_point, "anchor_text": "نص"}
    client = _Client([
        _Resp([_Block("text", text="عذرًا لا أستطيع")]),
        _Resp([_Block("tool_use", input_={"points": [good_raw_retry]})]),
    ])
    valid, rejected, error, truncation_note = ye.extract_points(
        "فيديو تجريبي", "نص", "ar", duration_seconds=600, cfg=extract_cfg, client=client)
    check("محاولة ثانية تنجح بعد فشل الأولى في إعادة إخراج مهيكل",
          error is None and len(valid) == 1, (valid, error))
    check("محاولتان فعليتان استُهلكتا (لا أكثر ولا أقل)",
          len(client.messages.calls) == 2)

    # فشل الإخراج المهيكل في كل المحاولات ⇒ خطأ عام مع أول 500 حرف للتشخيص
    long_text = "نص فاشل طويل " * 50
    client = _Client([
        _Resp([_Block("text", text=long_text)]),
        _Resp([_Block("text", text=long_text)]),
    ])
    valid, rejected, error, truncation_note = ye.extract_points(
        "فيديو تجريبي", "نص", "ar", duration_seconds=600, cfg=extract_cfg, client=client)
    check("فشل الإخراج المهيكل في كل المحاولات يُسجَّل كخطأ عام لا انهيار صامت",
          error is not None and valid == [] and rejected == [], error)
    check("رسالة الخطأ تحوي مقتطفًا من المخرج الفاشل للتشخيص (حتى 500 حرف)",
          error is not None and long_text[:80] in error, error)

    # Issue #637 العطل ٢: stop_reason=max_tokens يُسجَّل صراحةً بدل مقتطف نصّي
    # فارغ لا يفسِّر شيئًا -- هذا هو التشخيص الفعلي للفيديوهات الثقيلة التي
    # ردّت بإخراج مهيكل فارغ بعد كل المحاولات.
    client = _Client([
        _Resp([_Block("text", text="")], stop_reason="max_tokens",
              usage=_Usage(input_tokens=15000, output_tokens=2000)),
        _Resp([_Block("text", text="")], stop_reason="max_tokens",
              usage=_Usage(input_tokens=15000, output_tokens=2000)),
    ])
    valid, rejected, error, truncation_note = ye.extract_points(
        "فيديو تحليلي طويل", "نص", "ar", duration_seconds=3600, cfg=extract_cfg, client=client)
    check("انقطاع الإخراج بسبب max_tokens يُسجَّل صراحةً في رسالة الفشل",
          error is not None and "max_tokens" in error, error)
    check("رسالة الفشل تحوي طول النص المُرسَل وعدد الرموز المستهلكة للتشخيص",
          error is not None and "حرفًا" in error and "2000" in error, error)

    # ── _truncate_transcript: قصّ ذكي (نصف أول + نصف أخير) لا من النهاية فقط
    # (Issue #637 العطل ٢) ──
    short_text = "نص قصير لا يتجاوز الحدّ"
    check("نص أقصر من الحدّ لا يُقصّ", ye._truncate_transcript(short_text, 1000) == short_text)

    long_transcript = ("أ" * 100) + ("و" * 100) + ("ي" * 100)
    truncated = ye._truncate_transcript(long_transcript, 120)
    check("النص المقصوص أقصر من الأصلي وضمن حدّ معقول",
          len(truncated) < len(long_transcript), len(truncated))
    check("النصف الأول من النص الأصلي محفوظ في المقصوص",
          truncated.startswith("أ" * 60), truncated[:70])
    check("النصف الأخير من النص الأصلي محفوظ في المقصوص (لا قصّ من الآخر فقط)",
          truncated.endswith("ي" * 60), truncated[-70:])
    # Issue #642 العطل ٣ج: علامة الحذف صريحة الصياغة ("تم حذف جزء من النص")
    # -- ليعرف النموذج أن هناك فجوة حقيقية فلا يستنتج تسلسلًا زمنيًا متصلًا
    # عبرها ولا يختلق ختمًا لمقطع يقع داخلها.
    check("علامة الحذف الصريحة (TRUNCATION_MARKER) موجودة في النص المقصوص",
          ye.TRUNCATION_MARKER in truncated, truncated)
    check("نص علامة الحذف يطابق الصياغة المطلوبة حرفيًا",
          ye.TRUNCATION_MARKER == "[... تم حذف جزء من النص ...]", ye.TRUNCATION_MARKER)

    # extract_points تستعمل max_transcript_chars من config.yaml فعليًا
    truncating_cfg = load_config()
    truncating_cfg["youtube"]["extract"]["max_transcript_chars"] = 50
    long_raw = {**good_point, "anchor_text": "نص"}
    client = _Client([_Resp([_Block("tool_use", input_={"points": [long_raw]})])])
    valid, rejected, error, truncation_note = ye.extract_points(
        "فيديو طويل", "س" * 500, "ar", duration_seconds=600,
        cfg=truncating_cfg, client=client)
    sent_content = client.messages.calls[0]["messages"][0]["content"]
    check("النص الفعلي المُرسَل للنموذج مقصوص حسب max_transcript_chars",
          len(sent_content) < 500, len(sent_content))
    # Issue #642 العطل ٣د: طول النص قبل وبعد القصّ مُعاد صراحةً (لا في log
    # فقط) -- run() يسجّله في failed لمعرفة كم مرة يقع القصّ فعليًا.
    check("extract_points تعيد ملاحظة قصّ تحوي الطول الأصلي والمقصوص",
          truncation_note is not None and "500" in truncation_note and "50" in truncation_note,
          truncation_note)

    short_raw = {**good_point, "anchor_text": "نص"}
    no_truncation_client = _Client([_Resp([_Block("tool_use", input_={"points": [short_raw]})])])
    valid, rejected, error, truncation_note = ye.extract_points(
        "فيديو قصير", "نص قصير", "ar", duration_seconds=600,
        cfg=extract_cfg, client=no_truncation_client)
    check("لا ملاحظة قصّ عندما لا يقع قصّ فعلًا", truncation_note is None, truncation_note)

    # ── fetch_transcript: تراجع أُسّي عند حجب مؤقت أو انقطاع اتصال (العطل ٣) ──
    # اختبار بلا شبكة: fetch_once مزيَّفة ترفع IpBlocked مرتين ثم تنجح --
    # نفحص أن الدالة تعيد النجاح بعد استهلاك محاولتي تراجع بالضبط، بلا
    # انتظار فعلي (نُصلح time.sleep مؤقتًا).
    import requests as _requests
    from youtube_transcript_api import IpBlocked

    real_sleep = ye.time.sleep
    sleep_calls: list = []
    ye.time.sleep = lambda s: sleep_calls.append(s)
    try:
        attempts = {"n": 0}

        def _flaky_fetch_once(video_id, proxy_config, session):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise IpBlocked(video_id)
            return "[00:00:00] نص", "ar"

        text, reason, rate_limited = ye.fetch_transcript(
            "vid1", None, None, backoff_seconds=[15, 45, 90], fetch_once=_flaky_fetch_once)
        check("نجاح بعد إعادتي محاولة بسبب حجب مؤقت (429/IpBlocked)",
              text == "[00:00:00] نص" and reason == "ar" and rate_limited is False,
              (text, reason, rate_limited))
        check("التراجع استعمل الفاصلين الأولين من الجدول بالترتيب",
              sleep_calls == [15, 45], sleep_calls)

        # إرهاق كل محاولات التراجع ⇒ فشل نهائي مع رفع علامة أُرهق التراجع
        sleep_calls.clear()

        def _always_blocked_fetch_once(video_id, proxy_config, session):
            raise IpBlocked(video_id)

        text, reason, rate_limited = ye.fetch_transcript(
            "vid2", None, None, backoff_seconds=[15, 45], fetch_once=_always_blocked_fetch_once)
        check("إرهاق كل محاولات التراجع يُسجَّل فشلًا لا نجاحًا وهميًا",
              text is None and rate_limited is True, (text, reason, rate_limited))
        check("عدد محاولات التراجع المستهلكة يطابق طول الجدول",
              sleep_calls == [15, 45], sleep_calls)

        # انقطاع اتصال (RemoteDisconnected يصل مغلَّفًا بـ ConnectionError) يُعامَل
        # بنفس منطق التراجع
        def _disconnect_once_fetch_once(video_id, proxy_config, session):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise _requests.exceptions.ConnectionError("Remote end closed connection")
            return "[00:00:00] نص", "tr"

        attempts["n"] = 0
        text, reason, rate_limited = ye.fetch_transcript(
            "vid3", None, None, backoff_seconds=[15], fetch_once=_disconnect_once_fetch_once)
        check("انقطاع اتصال يُعامَل بنفس منطق التراجع وينجح بعد إعادة المحاولة",
              text == "[00:00:00] نص" and rate_limited is False, (text, reason, rate_limited))
    finally:
        ye.time.sleep = real_sleep

    # ── _should_retry: قرار صِرف بلا شبكة ولا وقت انتظار فعلي ──
    check("محاولة أولى مع جدول غير فارغ: يجب التراجع بأول فاصل",
          ye._should_retry(0, [15, 45, 90]) == (True, 15))
    check("محاولة أخيرة ضمن الجدول: يجب التراجع بآخر فاصل",
          ye._should_retry(2, [15, 45, 90]) == (True, 90))
    check("تجاوز طول الجدول: لا مزيد من التراجع",
          ye._should_retry(3, [15, 45, 90]) == (False, None))
    check("جدول فارغ: لا تراجع من الأساس", ye._should_retry(0, []) == (False, None))

    # ── classify_topic: حارس الموضوع قبل الاستخلاص (العطل ٥) ──
    client = _Client([_Resp([_Block("tool_use", input_={"category": "news_bulletin"})])])
    category, err = ye.classify_topic("نشرة الأخبار المسائية", "نص", extract_cfg, client)
    check("حارس الموضوع: نشرة تُصنَّف news_bulletin", category == "news_bulletin" and err is None)

    client = _Client([_Resp([_Block("tool_use", input_={"category": "other"})])])
    category, err = ye.classify_topic("مباراة غالاتاسراي", "نص", extract_cfg, client)
    check("حارس الموضوع: رياضة تُصنَّف other", category == "other" and err is None)

    client = _Client([_Resp([_Block("tool_use", input_={"category": "political_analysis"})])])
    category, err = ye.classify_topic("نقاش الساعة", "نص", extract_cfg, client)
    check("حارس الموضوع: تحليل سياسي يُصنَّف political_analysis",
          category == "political_analysis" and err is None)

    from anthropic import APIError
    import httpx as _httpx

    class _FailingMessages:
        def create(self, **kw):
            raise APIError(
                "عطل شبكي مؤقت",
                request=_httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
                body=None)

    class _FailingClient:
        def __init__(self):
            self.messages = _FailingMessages()

    category, err = ye.classify_topic("فيديو ما", "نص", extract_cfg, _FailingClient())
    check("فشل نداء حارس الموضوع لا يُسقِط الفيديو صامتًا -- يُفترَض صالحًا مع تسجيل السبب",
          category == "political_analysis" and err is not None, (category, err))

    # ── config.yaml: أنماط الاستبعاد الفارسية/التركية موسّعة (العطل ٥) ──
    channels_by_name = {c["name"]: c for c in extract_cfg.get("channels", [])}
    fa_patterns = channels_by_name["Iran International"]["exclude_patterns"]
    check("أنماط استبعاد فارسية جديدة مضافة",
          all(p in fa_patterns for p in ("اخبار شامگاهی", "بخش نیمروزی", "به وقت تهران",
                                         "خبر ۲۱", "خبر 21")), fa_patterns)
    tr_patterns = channels_by_name["CNN Türk"]["exclude_patterns"]
    check("أنماط استبعاد تركية جديدة مضافة",
          all(p in tr_patterns for p in ("Ana Haber", "Ana Haber Bülteni", "Maç", "Spor",
                                         "Sinema", "Hayatın İçinden", "Sabah Kahvesi")), tr_patterns)


def test_youtube_cluster() -> None:
    """المرحلة الثالثة (src/youtube_cluster.py، Issue #646): عنقدة نقاط
    youtube_extract.py في قضايا وترتيبها بثلاث طبقات. لا شبكة، لا نموذج
    فعلي -- نداء العنقدة الوحيد مموَّه بفاكة محلية، والطبقة/الترتيب/سقف
    الكتلة منطق صِرف يُختبَر بلا أي استدعاء نموذج."""
    ycl = youtube_cluster

    def mk_point(bloc, channel):
        return {"bloc": bloc, "channel": channel, "statement": "س", "speaker": "ق",
                "topic_hint": "ه", "type": "fact"}

    points = [
        mk_point("arabic", "الجزيرة"),     # 0
        mk_point("arabic", "العربية"),     # 1
        mk_point("turkish", "CNN Türk"),   # 2
        mk_point("arabic", "الجزيرة"),     # 3 -- نفس قناة 0
    ]

    # ── _layer_for: الطبقة تُحسَب من عدد الكتل/القنوات الفعلي، لا من حكم النموذج ──
    check("طبقة أ: كتلتان مختلفتان فأكثر",
          ycl._layer_for({"arabic", "turkish"}, {"الجزيرة"}) == "a")
    check("طبقة ب: كتلة واحدة، قناتان مختلفتان",
          ycl._layer_for({"arabic"}, {"الجزيرة", "العربية"}) == "b")
    check("طبقة ج: كتلة واحدة وقناة واحدة",
          ycl._layer_for({"arabic"}, {"الجزيرة"}) == "c")

    # ── build_topics: الفرز بالطبقة أولًا ثم مؤشّر الخلاف (خلاف > اتفاق > صدى) ──
    issue_a = {"title": "قضية أ (طبقة أ)", "event": "حدث أ", "agreement": "agreement",
               "point_ids": [0, 2]}
    issue_b_dispute = {"title": "قضية ب خلاف", "event": "حدث ب١", "agreement": "dispute",
                        "point_ids": [0, 1]}
    issue_b_echo = {"title": "قضية ب صدى", "event": "حدث ب٢", "agreement": "echo",
                     "point_ids": [0, 1]}
    issue_c = {"title": "قضية ج (طبقة ج)", "event": "حدث ج", "agreement": "agreement",
               "point_ids": [0, 3]}

    topics = ycl.build_topics([issue_c, issue_b_echo, issue_a, issue_b_dispute], points)
    check("العدد الكلي للقضايا محفوظ بعد الفرز", len(topics) == 4, len(topics))
    check("الطبقة أ تتصدّر بصرف النظر عن ترتيب الإدخال",
          topics[0]["title"] == issue_a["title"], [t["title"] for t in topics])
    check("داخل الطبقة ب: الخلاف (cross_source بعد التنقيح) يتقدّم على الصدى (echo)",
          topics[1]["title"] == issue_b_dispute["title"] and
          topics[2]["title"] == issue_b_echo["title"], [t["title"] for t in topics])
    check("الطبقة ج تأتي أخيرًا", topics[3]["title"] == issue_c["title"])
    check("قوائم الكتل/القنوات تُحسَب من نقاط القضية الفعلية لا من النموذج",
          topics[0]["blocs"] == ["arabic", "turkish"] and
          topics[0]["channels"] == sorted({"الجزيرة", "CNN Türk"}),
          topics[0])
    check("build_topics: يحمل حقل event من القضية الخام (Issue #658 العطل ٤)",
          topics[0]["event"] == issue_a["event"], topics[0])

    # ── build_topics/_agreement_type_for: dispute يُنقَّح برمجيًا إلى
    # cross_source/internal حسب قنوات القضية الفعلية (Issue #662 العطل ٤) ──
    check("_agreement_type_for: dispute بقناتين مختلفتين فأكثر ⇐ cross_source",
          ycl._agreement_type_for("dispute", {"الجزيرة", "العربية"}) == "cross_source")
    check("_agreement_type_for: dispute بقناة واحدة ⇐ internal (خلاف بين ضيوف حلقة واحدة)",
          ycl._agreement_type_for("dispute", {"الجزيرة"}) == "internal")
    check("_agreement_type_for: agreement/echo يمرّان بلا تغيير",
          ycl._agreement_type_for("agreement", {"الجزيرة"}) == "agreement" and
          ycl._agreement_type_for("echo", {"الجزيرة", "العربية"}) == "echo")
    check("build_topics: issue_b_dispute (نقطتان من قناتين) خرجت cross_source لا dispute",
          topics[1]["agreement"] == "cross_source", topics[1])
    internal_points = [mk_point("arabic", "الجزيرة"), mk_point("arabic", "الجزيرة")]
    issue_internal = {"title": "خلاف داخل حلقة واحدة", "event": "ح", "agreement": "dispute",
                       "point_ids": [0, 1]}
    internal_topics = ycl.build_topics([issue_internal], internal_points)
    check("build_topics: dispute بقناة واحدة (ضيوف حلقة واحدة) خرجت internal",
          internal_topics[0]["agreement"] == "internal", internal_topics)

    # ── build_topics: ترجيح خفيف للحداثة عند تساوي الطبقة والخلاف (Issue #658 العطل ١ بند د) ──
    today, yesterday = "2098-08-08", "2098-08-06"
    recency_points = [
        {**mk_point("arabic", "قX"), "run_date": yesterday},   # 0
        {**mk_point("arabic", "قY"), "run_date": yesterday},   # 1
        {**mk_point("arabic", "قZ"), "run_date": today},       # 2
        {**mk_point("arabic", "قW"), "run_date": yesterday},   # 3
    ]
    issue_old = {"title": "قضية قديمة", "event": "ح", "agreement": "agreement",
                 "point_ids": [0, 1]}
    issue_fresh = {"title": "قضية حديثة", "event": "ح", "agreement": "agreement",
                   "point_ids": [2, 3]}
    recency_topics = ycl.build_topics([issue_old, issue_fresh], recency_points, today)
    check("build_topics: قضية فيها نقطة من اليوم الحالي تتقدّم عند تساوي الطبقة والخلاف",
          recency_topics[0]["title"] == "قضية حديثة", recency_topics)
    check("build_topics: بلا today_date_str، الترتيب يبقى كما وصل (بلا ترجيح حداثة)",
          ycl.build_topics([issue_old, issue_fresh], recency_points)[0]["title"] == "قضية قديمة")

    # ── apply_bloc_cap: سقف لكل كتلة، مع إبقاء الأعلى ترتيبًا عند التعادل ──
    many_c_topics = [
        {"title": f"قج{i}", "layer": "c", "blocs": ["arabic"], "channels": [f"ق{i}"],
         "agreement": "agreement", "point_ids": [0, 1]}
        for i in range(6)
    ]
    kept, dropped = ycl.apply_bloc_cap(many_c_topics, max_per_bloc=4)
    check("سقف الكتلة يبقي أول 4 قضايا فقط لكتلة واحدة",
          len(kept) == 4 and dropped == 2, (len(kept), dropped))
    check("القضايا المُبقاة هي الأعلى ترتيبًا (أول 4 بترتيب الإدخال)",
          [t["title"] for t in kept] == ["قج0", "قج1", "قج2", "قج3"], kept)

    mixed_bloc_topics = [
        {"title": "أ1", "layer": "a", "blocs": ["arabic", "turkish"], "channels": ["ق1"],
         "agreement": "dispute", "point_ids": [0, 1]},
        {"title": "ب1", "layer": "b", "blocs": ["turkish"], "channels": ["ق2", "ق3"],
         "agreement": "agreement", "point_ids": [0, 1]},
    ]
    kept2, dropped2 = ycl.apply_bloc_cap(mixed_bloc_topics, max_per_bloc=1)
    check("قضية تشترك في كتلة استُنفد سقفها تُستبعَد كاملة ولو شاركت كتلة أخرى غير مستنفَدة",
          len(kept2) == 1 and kept2[0]["title"] == "أ1" and dropped2 == 1, (kept2, dropped2))

    # ── apply_min_points: حدّ أدنى للنقاط، استثناء طبقة (أ) بثلاث لا أربع (Issue #658 العطل ٢) ──
    mp_topics = [
        {"title": "ج بنقطتين", "layer": "c", "point_ids": [0, 1]},
        {"title": "ج بأربع", "layer": "c", "point_ids": [0, 1, 2, 3]},
        {"title": "أ بثلاث", "layer": "a", "point_ids": [0, 1, 2]},
        {"title": "أ بنقطتين", "layer": "a", "point_ids": [0, 1]},
    ]
    kept_mp, dropped_mp = ycl.apply_min_points(mp_topics, min_points=4)
    check("apply_min_points: طبقة ج دون ٤ نقاط تُهمَل، طبقة أ تُقبَل بثلاث نقاط لا أربع",
          [t["title"] for t in kept_mp] == ["ج بأربع", "أ بثلاث"] and dropped_mp == 2,
          (kept_mp, dropped_mp))

    # ── point_key: معرّف مستقر عبر تشغيلات مختلفة (Issue #658 العطل ١ بند ج) ──
    p_a = {"video_id": "v1", "statement": "قول أ"}
    p_b = {"video_id": "v1", "statement": "قول ب"}
    check("point_key: نقطتان مختلفتا statement لهما مفتاحان مختلفان",
          ycl.point_key(p_a) != ycl.point_key(p_b))
    check("point_key: نفس الحقول تعطي نفس المفتاح", ycl.point_key(p_a) == ycl.point_key(dict(p_a)))

    # ── load_points_window: نافذة عدّة أيام، كل نقطة تحمل run_date (Issue #658 العطل ١ بند أ+ب) ──
    ycl.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    day1, day2, day3 = "2098-05-01", "2098-05-02", "2098-05-03"
    (ycl.POINTS_DIR / f"{day1}.json").write_text(
        json.dumps({"points": [mk_point("arabic", "الجزيرة")]}, ensure_ascii=False),
        encoding="utf-8")
    (ycl.POINTS_DIR / f"{day3}.json").write_text(
        json.dumps({"points": [mk_point("turkish", "CNN Türk")]}, ensure_ascii=False),
        encoding="utf-8")
    try:
        window = ycl.load_points_window(day3, 3)
        check("load_points_window: يجمع نقاط الأيام الثلاثة (يوم وسط غائب لا يكسر شيئًا)",
              len(window) == 2, window)
        check("load_points_window: كل نقطة تحمل run_date مصدرها",
              window[0]["run_date"] == day1 and window[1]["run_date"] == day3, window)
        check("load_points_window: نافذة يوم واحد تقرأ اليوم الحالي فقط",
              len(ycl.load_points_window(day3, 1)) == 1)
    finally:
        (ycl.POINTS_DIR / f"{day1}.json").unlink(missing_ok=True)
        (ycl.POINTS_DIR / f"{day2}.json").unlink(missing_ok=True)
        (ycl.POINTS_DIR / f"{day3}.json").unlink(missing_ok=True)

    # ── apply_points_cap: سقف نداء العنقدة، الأحدث حسب run_date ثم ترتيب الظهور (Issue #660 الإصلاح ٢) ──
    cap_points = [
        {**mk_point("arabic", "قA"), "run_date": "2098-08-06", "statement": "قديم-0"},
        {**mk_point("arabic", "قB"), "run_date": "2098-08-06", "statement": "قديم-1"},
        {**mk_point("arabic", "قC"), "run_date": "2098-08-07", "statement": "حديث-0"},
        {**mk_point("arabic", "قD"), "run_date": "2098-08-07", "statement": "حديث-1"},
        {**mk_point("arabic", "قE"), "run_date": "2098-08-08", "statement": "أحدث-0"},
    ]
    check("apply_points_cap: بلا تجاوز السقف، القائمة تعود كما وصلت وبلا إسقاط",
          ycl.apply_points_cap(cap_points, max_points_per_call=10) == (cap_points, 0))
    kept_cap, dropped_cap = ycl.apply_points_cap(cap_points, max_points_per_call=3)
    check("apply_points_cap: يُبقي الأحدث حسب run_date (كتلتا 08+07) ويُسقِط الأقدم (06)",
          {p["statement"] for p in kept_cap} == {"أحدث-0", "حديث-0", "حديث-1"} and
          dropped_cap == 2, (kept_cap, dropped_cap))
    check("apply_points_cap: max_points_per_call<=0 يعني بلا سقف",
          ycl.apply_points_cap(cap_points, max_points_per_call=0) == (cap_points, 0))

    tie_points = [
        {**mk_point("arabic", "قF"), "run_date": "2098-08-06", "statement": "ظهر أولًا"},
        {**mk_point("arabic", "قG"), "run_date": "2098-08-06", "statement": "ظهر ثانيًا"},
        {**mk_point("arabic", "قH"), "run_date": "2098-08-06", "statement": "ظهر ثالثًا"},
    ]
    kept_tie, dropped_tie = ycl.apply_points_cap(tie_points, max_points_per_call=2)
    check("apply_points_cap: عند تساوي run_date، يُبقي الأسبق ظهورًا (ترتيب الظهور)",
          {p["statement"] for p in kept_tie} == {"ظهر أولًا", "ظهر ثانيًا"} and dropped_tie == 1,
          (kept_tie, dropped_tie))

    # ── apply_min_points_date: يُسقِط نقاط ملفات أقدم من الحدّ (Issue #662 العطل ٢ بند أ) ──
    date_points = [
        {**mk_point("arabic", "قI"), "run_date": "2026-08-29", "statement": "قبل الإصلاح"},
        {**mk_point("arabic", "قJ"), "run_date": "2026-08-31", "statement": "يوم الإصلاح"},
        {**mk_point("arabic", "قK"), "run_date": "2026-09-01", "statement": "بعد الإصلاح"},
    ]
    kept_date, dropped_date = ycl.apply_min_points_date(date_points, "2026-08-31")
    check("apply_min_points_date: يُسقِط ملفات أقدم من الحدّ، يُبقي الحدّ نفسه وما بعده",
          {p["statement"] for p in kept_date} == {"يوم الإصلاح", "بعد الإصلاح"} and
          dropped_date == 1, (kept_date, dropped_date))
    check("apply_min_points_date: حدّ فارغ/None يعني بلا فلترة",
          ycl.apply_min_points_date(date_points, None) == (date_points, 0) and
          ycl.apply_min_points_date(date_points, "") == (date_points, 0))

    # ── apply_timestamp_guard: حارس ثانٍ للأمان، طابع يتجاوز مدة الفيديو يُسقَط (Issue #662 العطل ٢ بند ج) ──
    ts_points = [
        {**mk_point("arabic", "قL"), "timestamp": 100, "duration_seconds": 6791,
         "statement": "طابع سليم"},
        {**mk_point("arabic", "قM"), "timestamp": 7800, "duration_seconds": 6791,
         "statement": "طابع يتجاوز المدة"},
        {**mk_point("arabic", "قN"), "timestamp": None, "duration_seconds": 6791,
         "statement": "طابع غير محلول (None)"},
        {**mk_point("arabic", "قO"), "timestamp": 100, "statement": "بلا duration_seconds"},
    ]
    kept_ts, dropped_ts = ycl.apply_timestamp_guard(ts_points)
    check("apply_timestamp_guard: يُسقِط الطابع المتجاوز فقط، يُبقي السليم والفارغ الصادق وناقص البيانات",
          {p["statement"] for p in kept_ts} == {"طابع سليم", "طابع غير محلول (None)",
                                                  "بلا duration_seconds"} and
          dropped_ts == 1, (kept_ts, dropped_ts))

    # ── prepare_window_points: تجميع الخطوات الأربع بترتيب ثابت واحد (Issue #662) --
    # نفس الدالة تُستدعى من youtube_cluster.run() وyoutube_article.run() بنيويًا،
    # فاتساقهما مضمون لا مجرّد اتفاق توثيقي بين الملفين ──
    ycl.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    prep_day_old, prep_day_new = "2026-08-29", "2026-08-31"
    (ycl.POINTS_DIR / f"{prep_day_old}.json").write_text(
        json.dumps({"points": [
            {**mk_point("arabic", "قP"), "statement": "قديم يُستبعَد بالتاريخ",
             "timestamp": 10, "duration_seconds": 100},
        ]}, ensure_ascii=False), encoding="utf-8")
    (ycl.POINTS_DIR / f"{prep_day_new}.json").write_text(
        json.dumps({"points": [
            {**mk_point("arabic", "قQ"), "statement": "سليمة تمر",
             "timestamp": 10, "duration_seconds": 100},
            {**mk_point("arabic", "قR"), "statement": "طابع فاسد يُستبعَد",
             "timestamp": 999, "duration_seconds": 100},
        ]}, ensure_ascii=False), encoding="utf-8")
    prep_cfg = load_config()
    prep_cfg.setdefault("youtube", {}).setdefault("cluster", {})["min_points_date"] = "2026-08-31"
    try:
        prep_points, prep_stats = ycl.prepare_window_points(prep_day_new, prep_cfg)
        check("prepare_window_points: يُبقي النقطة السليمة فقط بعد الفلترتين",
              [p["statement"] for p in prep_points] == ["سليمة تمر"], (prep_points, prep_stats))
        check("prepare_window_points: إحصاءات الإسقاط منفصلة بالسبب",
              prep_stats["points_in"] == 3 and prep_stats["points_dropped_stale_date"] == 1 and
              prep_stats["points_dropped_bad_timestamp"] == 1 and
              prep_stats["points_dropped_over_cap"] == 0, prep_stats)
    finally:
        (ycl.POINTS_DIR / f"{prep_day_old}.json").unlink(missing_ok=True)
        (ycl.POINTS_DIR / f"{prep_day_new}.json").unlink(missing_ok=True)

    # ── load_seen_points/mark_points_seen: سجل الاستهلاك + تقليمه (Issue #658 العطل ١ بند ج) ──
    seen_backup = ycl.SEEN_PATH.read_text(encoding="utf-8") if ycl.SEEN_PATH.exists() else None
    try:
        if ycl.SEEN_PATH.exists():
            ycl.SEEN_PATH.unlink()
        check("load_seen_points: ملف غائب يعيد قاموسًا فارغًا", ycl.load_seen_points() == {})
        ycl.mark_points_seen({"k1", "k2"}, "2098-06-15", retention_days=10)
        seen = ycl.load_seen_points()
        check("mark_points_seen: المفاتيح المُسجَّلة موجودة بتاريخ التسجيل",
              seen.get("k1") == "2098-06-15" and seen.get("k2") == "2098-06-15", seen)
        ycl.mark_points_seen({"k3"}, "2098-07-01", retention_days=10)
        seen2 = ycl.load_seen_points()
        check("mark_points_seen: التقليم يُسقِط مفاتيح أقدم من retention_days من تاريخ التسجيل الجديد",
              "k1" not in seen2 and "k2" not in seen2 and "k3" in seen2, seen2)
    finally:
        if seen_backup is None:
            ycl.SEEN_PATH.unlink(missing_ok=True)
        else:
            ycl.SEEN_PATH.write_text(seen_backup, encoding="utf-8")

    # ── filter_seen_topics: قضية أكثر نقاطها مستهلكة سابقًا تُهمَل (Issue #658 العطل ١ بند ج) ──
    points_fs = [mk_point("arabic", "ق1"), mk_point("arabic", "ق2"), mk_point("turkish", "ق3")]
    points_fs[0]["video_id"], points_fs[0]["statement"] = "v1", "س1"
    points_fs[1]["video_id"], points_fs[1]["statement"] = "v2", "س2"
    points_fs[2]["video_id"], points_fs[2]["statement"] = "v3", "س3"
    seen_keys_fs = {ycl.point_key(points_fs[0])}
    kept_fs, dropped_fs = ycl.filter_seen_topics(
        [{"title": "نصف مستهلَك", "point_ids": [0, 1]}], points_fs, seen_keys_fs)
    check("filter_seen_topics: نصف النقاط مستهلَك بالضبط (ليس أغلبية) تُبقي القضية",
          len(kept_fs) == 1 and dropped_fs == 0, (kept_fs, dropped_fs))
    seen_keys_fs2 = {ycl.point_key(points_fs[0]), ycl.point_key(points_fs[1])}
    kept_fs2, dropped_fs2 = ycl.filter_seen_topics(
        [{"title": "أغلبها مستهلَك", "point_ids": [0, 1]}], points_fs, seen_keys_fs2)
    check("filter_seen_topics: أغلبية حقيقية (2 من 2) تُهمِل القضية",
          len(kept_fs2) == 0 and dropped_fs2 == 1, (kept_fs2, dropped_fs2))

    # ── cluster_points: إخراج مهيكل (tool_use)، تنقية معرّفات خارج النطاق/فاسدة ──
    class _Block:
        def __init__(self, type_, input_=None, text=None):
            self.type, self.input, self.text = type_, input_, text

    class _Usage:
        def __init__(self, input_tokens=100, output_tokens=50):
            self.input_tokens, self.output_tokens = input_tokens, output_tokens

    class _Resp:
        def __init__(self, content, stop_reason=None, usage=None):
            self.content, self.stop_reason, self.usage = content, stop_reason, usage

    class _Messages:
        def __init__(self, responses):
            self._responses = list(responses)
            self.calls: list = []

        def create(self, **kw):
            self.calls.append(kw)
            return self._responses.pop(0)

    class _Client:
        def __init__(self, responses):
            self.messages = _Messages(responses)

    cluster_cfg = load_config()
    two_points = points[:2]
    raw_issues = {
        "issues": [
            {"title": "قضية صالحة", "event": "حدث محدد", "agreement": "dispute",
             "point_ids": [0, 1, 99, -1, "x", True]},
            {"title": "   ", "event": "ح", "agreement": "agreement", "point_ids": [0, 1]},
            {"title": "قضية بنقطة واحدة", "event": "ح", "agreement": "echo", "point_ids": [0]},
            {"title": "قضية بخلاف باطل", "event": "ح", "agreement": "غير معروف",
             "point_ids": [0, 1]},
            {"title": "قضية بلا حقل event", "agreement": "agreement", "point_ids": [0, 1]},
            {"title": "قضية بحدث فارغ", "event": "   ", "agreement": "agreement",
             "point_ids": [0, 1]},
        ],
    }
    client = _Client([_Resp([_Block("tool_use", input_=raw_issues)])])
    issues, error = ycl.cluster_points(two_points, cluster_cfg, client)
    check("cluster_points: القضية الصالحة الوحيدة تعود بلا خطأ عام",
          error is None and len(issues) == 1, (issues, error))
    check("معرّفات خارج النطاق/الفاسدة (99, -1, 'x') تُهمَل، True (=1) تُقبَل كمعرّف صحيح",
          issues[0]["point_ids"] == [0, 1], issues[0] if issues else None)
    check("قضية بعنوان فارغ بعد strip تُهمَل كاملة",
          all(i["title"] != "" for i in issues))
    check("قضية بنقطة واحدة فقط تُهمَل (لا قيمة عنقدية لتقاطع من نقطة)",
          all(len(i["point_ids"]) >= 2 for i in issues))
    check("قضية بمؤشّر خلاف غير صالح تُهمَل",
          all(i["agreement"] in ycl.AGREEMENT_VALUES for i in issues))
    check("قضية بلا حقل event أو بحدث فارغ بعد strip تُهمَل (Issue #658 العطل ٤)",
          all(i["title"] not in ("قضية بلا حقل event", "قضية بحدث فارغ") for i in issues))
    check("cluster_points: القضية الصالحة تحمل event مطابقًا لما أعاده النموذج",
          issues[0]["event"] == "حدث محدد", issues[0] if issues else None)
    check("cluster_points: النداء يستعمل tool_use بمخطط cluster_points",
          client.messages.calls[0]["tools"][0]["name"] == "cluster_points" and
          client.messages.calls[0]["tool_choice"] == {"type": "tool", "name": "cluster_points"})

    check("cluster_points: قائمة نقاط فارغة لا تستدعي النموذج أصلًا",
          ycl.cluster_points([], cluster_cfg, _Client([])) == ([], None))

    # ── فشل نداء الشبكة لا يُسقِط التشغيلة صامتًا ──
    class _FailingMessages:
        def create(self, **kw):
            from anthropic import APIError
            import httpx as _httpx
            raise APIError(
                "عطل شبكي مؤقت",
                request=_httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
                body=None)

    class _FailingClient:
        def __init__(self):
            self.messages = _FailingMessages()

    failed_issues, failed_error = ycl.cluster_points(two_points, cluster_cfg, _FailingClient())
    check("فشل نداء العنقدة يعيد قائمة فارغة وسببًا صريحًا، لا استثناء غير مُلتقَط",
          failed_issues == [] and failed_error is not None, failed_error)

    # ── cluster_points: إعادة محاولة واحدة عند القطع بـmax_tokens، ثم نجاح (Issue #660) ──
    retry_client = _Client([
        _Resp([_Block("text", text="بلوك ناقص لم يكتمل")],
              stop_reason="max_tokens", usage=_Usage(input_tokens=9000, output_tokens=16000)),
        _Resp([_Block("tool_use", input_={"issues": [
            {"title": "قضية بعد إعادة المحاولة", "event": "حدث", "agreement": "agreement",
             "point_ids": [0, 1]},
        ]})]),
    ])
    retry_issues, retry_error = ycl.cluster_points(two_points, cluster_cfg, retry_client)
    check("cluster_points: يعيد المحاولة بعد قطع stop_reason=max_tokens وينجح في الثانية",
          retry_error is None and len(retry_issues) == 1 and
          retry_issues[0]["title"] == "قضية بعد إعادة المحاولة" and
          len(retry_client.messages.calls) == 2, (retry_issues, retry_error))

    # ── cluster_points: استنفاد كل المحاولات يعيد سببًا صريحًا يذكر stop_reason وعدد النقاط ──
    exhaust_client = _Client([
        _Resp([_Block("text", text="ناقص أولًا")], stop_reason="max_tokens"),
        _Resp([_Block("text", text="ناقص ثانيًا")], stop_reason="max_tokens"),
    ])
    exhaust_issues, exhaust_error = ycl.cluster_points(two_points, cluster_cfg, exhaust_client)
    check("cluster_points: استنفاد المحاولات (بلا نجاح) يعيد قائمة فارغة وسببًا صريحًا",
          exhaust_issues == [] and exhaust_error is not None, exhaust_error)
    check("cluster_points: سبب الفشل النهائي يذكر max_tokens وعدد النقاط المدخلة (2)",
          exhaust_error is not None and "max_tokens" in exhaust_error and "2" in exhaust_error,
          exhaust_error)
    check("cluster_points: استنفاد المحاولات يستدعي النموذج max_retries مرة بالضبط",
          len(exhaust_client.messages.calls) == cluster_cfg.path("youtube.cluster.max_retries", 2),
          len(exhaust_client.messages.calls))

    # ── cluster_points: حارس عقلانية (Issue #662 متابعة) -- تشغيلة فعلية أعطت
    # قضية واحدة من ٢٠٩ نقطة بلا أي رسالة خطأ أو stop_reason غير طبيعي. مدخل
    # يتجاوز sanity_min_points (افتراضيًا ٥٠) ينتج عدد قضايا صالحة دون
    # sanity_min_issues (افتراضيًا ٥) يُعَدّ فشل محاولة صريحًا يُعاد بسببه ──
    many_points = [mk_point("arabic", f"ق{i}") for i in range(60)]

    def _sparse_issue(offset):
        return {"title": f"قضية {offset}", "event": f"حدث {offset}", "agreement": "agreement",
                "point_ids": [offset, offset + 1]}

    sanity_retry_client = _Client([
        # محاولة أولى: قضيتان صالحتان فقط من ٦٠ نقطة -- دون الحدّ الأدنى (٥).
        _Resp([_Block("tool_use", input_={"issues": [_sparse_issue(0), _sparse_issue(2)]})],
              stop_reason="end_turn", usage=_Usage(input_tokens=9000, output_tokens=300)),
        # محاولة ثانية: خمس قضايا صالحة -- تجتاز الحارس.
        _Resp([_Block("tool_use", input_={"issues": [
            _sparse_issue(i * 2) for i in range(5)
        ]})], stop_reason="end_turn", usage=_Usage(input_tokens=9000, output_tokens=700)),
    ])
    sanity_issues, sanity_error = ycl.cluster_points(many_points, cluster_cfg, sanity_retry_client)
    check("حارس العقلانية: محاولة بقضايا قليلة جدًا (2 من 60 نقطة) لا تُقبَل، وتُعاد المحاولة",
          sanity_error is None and len(sanity_issues) == 5 and
          len(sanity_retry_client.messages.calls) == 2, (sanity_issues, sanity_error))

    # كل المحاولات هزيلة دلاليًا -- فشل صريح بعد استنفادها، لا نجاح بمخرج ركيك.
    sanity_exhaust_client = _Client([
        _Resp([_Block("tool_use", input_={"issues": [_sparse_issue(0)]})], stop_reason="end_turn"),
        _Resp([_Block("tool_use", input_={"issues": [_sparse_issue(0)]})], stop_reason="end_turn"),
    ])
    sanity_exhaust_issues, sanity_exhaust_error = ycl.cluster_points(
        many_points, cluster_cfg, sanity_exhaust_client)
    check("حارس العقلانية: استنفاد المحاولات كلها هزيلة دلاليًا يعيد فشلًا صريحًا لا نجاحًا هزيلًا",
          sanity_exhaust_issues == [] and sanity_exhaust_error is not None and
          "حارس عقلانية" in sanity_exhaust_error and
          len(sanity_exhaust_client.messages.calls) == 2, sanity_exhaust_error)

    # مدخل صغير (لا يتجاوز sanity_min_points) لا يُفعِّل الحارس ولو كانت
    # القضايا الصالحة قليلة جدًا نسبيًا -- الحارس مخصَّص لمدخل كبير فقط.
    small_sparse_client = _Client([_Resp([_Block("tool_use", input_={
        "issues": [{"title": "قضية وحيدة", "event": "حدث", "agreement": "agreement",
                    "point_ids": [0, 1]}],
    })])])
    small_issues, small_error = ycl.cluster_points(two_points, cluster_cfg, small_sparse_client)
    check("حارس العقلانية: لا يُفعَّل لمدخل دون sanity_min_points حتى لو كانت القضايا قليلة",
          small_error is None and len(small_issues) == 1 and
          len(small_sparse_client.messages.calls) == 1, (small_issues, small_error))

    # ── cluster_points: stop_reason/عدد الرموز يُسجَّلان عند كل محاولة (لا
    # الفشل الظاهر وحده)، وعدد القضايا الخام قبل الترشيح يُسجَّل أيضًا
    # (Issue #662 متابعة) ──
    class _ListHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.messages: list[str] = []

        def emit(self, record):
            self.messages.append(record.getMessage())

    log_handler = _ListHandler()
    prev_level = ycl.log.level
    ycl.log.addHandler(log_handler)
    ycl.log.setLevel(logging.INFO)
    try:
        log_client = _Client([_Resp(
            [_Block("tool_use", input_={"issues": [
                {"title": "قضية", "event": "حدث", "agreement": "agreement", "point_ids": [0, 1]},
            ]})],
            stop_reason="end_turn", usage=_Usage(input_tokens=123, output_tokens=45))])
        ycl.cluster_points(two_points, cluster_cfg, log_client)
        check("cluster_points: stop_reason وعدد الرموز يُسجَّلان عند كل نداء ناجح، لا الفشل وحده",
              any("stop_reason=end_turn" in m and "123" in m and "45" in m
                  for m in log_handler.messages), log_handler.messages)
        check("cluster_points: عدد القضايا الخام قبل أي ترشيح يُسجَّل",
              any("1 قضية خامة قبل أي ترشيح" in m for m in log_handler.messages),
              log_handler.messages)
    finally:
        ycl.log.removeHandler(log_handler)
        ycl.log.setLevel(prev_level)

    # ── merge_duplicate_events: قضيتان لنفس الحدث تُدمَجان، والطبقة تُعاد
    # حسابها برمجيًا بعد الدمج (Issue #662 العطل ١) ──
    merge_a = {"title": "صفقة نفط -- الجزيرة/العربية", "event": "صفقة نفط أمريكية فنزويلية",
               "agreement": "agreement", "point_ids": [0, 1]}
    merge_b = {"title": "صفقة نفط -- CNN Türk", "event": "تفاصيل اتفاق النفط الأمريكي الفنزويلي",
               "agreement": "dispute", "point_ids": [2]}
    merge_unrelated = {"title": "قضية أخرى تمامًا", "event": "حدث منفصل",
                        "agreement": "echo", "point_ids": [0, 3]}
    merge_points = [
        mk_point("arabic", "الجزيرة"), mk_point("arabic", "العربية"),
        mk_point("turkish", "CNN Türk"), mk_point("arabic", "الجزيرة"),
    ]
    merge_raw_response = {"merges": [{"issue_indices": [0, 1]}]}
    merge_client = _Client([_Resp([_Block("tool_use", input_=merge_raw_response)])])
    merged, merge_log, merge_error = ycl.merge_duplicate_events(
        [merge_a, merge_b, merge_unrelated], cluster_cfg, merge_client)
    check("merge_duplicate_events: يعود بلا خطأ، وقضية واحدة أقل بعد الدمج",
          merge_error is None and len(merged) == 2, (merged, merge_error))
    check("merge_duplicate_events: القضية غير المشمولة بالدمج تبقى كما هي",
          any(t["title"] == merge_unrelated["title"] for t in merged), merged)
    merged_topic = next(t for t in merged if t["title"] != merge_unrelated["title"])
    check("merge_duplicate_events: نقاط القضيتين المدموجتين تُضَمّ (اتحاد لا تكرار)",
          merged_topic["point_ids"] == [0, 1, 2], merged_topic)
    check("merge_duplicate_events: مؤشّر الخلاف الخام يُؤخذ من الأعلى رتبة (dispute > agreement)",
          merged_topic["agreement"] == "dispute", merged_topic)
    check("merge_duplicate_events: سجل الدمج يذكر عنواني القضيتين المدموجتين",
          merge_log == [[merge_a["title"], merge_b["title"]]], merge_log)

    # الدمج مُتبَع ببناء القضايا -- الطبقة تُعاد حسابها برمجيًا من point_ids
    # المدموجة تلقائيًا (لا حساب طبقة مكرَّر في merge_duplicate_events نفسها).
    merged_final_topics = ycl.build_topics(merged, merge_points)
    merged_final = next(t for t in merged_final_topics if t["title"] == merge_a["title"])
    check("merge_duplicate_events + build_topics: القضية المدموجة (كتلتان، ٣ قنوات) خرجت طبقة أ",
          merged_final["layer"] == "a" and merged_final["channels"] ==
          sorted({"الجزيرة", "العربية", "CNN Türk"}), merged_final)

    check("merge_duplicate_events: أقل من قضيتين لا يستدعي النموذج أصلًا",
          ycl.merge_duplicate_events([merge_a], cluster_cfg, _Client([])) == ([merge_a], [], None))

    # فشل نداء الدمج لا يُسقِط التشغيلة -- القضايا تبقى بلا دمج (نفس مبدأ check_forbidden)
    no_merge_found, no_merge_log, no_merge_error = ycl.merge_duplicate_events(
        [merge_a, merge_unrelated], cluster_cfg, _FailingClient())
    check("merge_duplicate_events: فشل نداء الشبكة يعيد القضايا بلا دمج، وسببًا صريحًا",
          no_merge_found == [merge_a, merge_unrelated] and no_merge_log == [] and
          no_merge_error is not None, no_merge_error)

    # ── load_points/load_topics: ملف غائب أو تالف لا يُسقِط التشغيلة ──
    check("load_points: تاريخ بلا ملف يعيد قائمة فارغة",
          ycl.load_points("1999-01-01") == [])
    check("load_topics: تاريخ بلا ملف يعيد بنية فارغة متّسقة",
          ycl.load_topics("1999-01-01") == {"run_date": "1999-01-01", "topics": []})

    ycl.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    corrupt_path = ycl.POINTS_DIR / "2099-01-01.json"
    corrupt_path.write_text("{ليس JSON صالحًا", encoding="utf-8")
    try:
        check("load_points: JSON تالف يعيد قائمة فارغة بلا استثناء",
              ycl.load_points("2099-01-01") == [])
    finally:
        corrupt_path.unlink(missing_ok=True)

    # ── run()/save_output: تكامل كامل بفاكة واحدة، ثم قراءة الملف المحفوظ ──
    # point_ids ثلاثة (0، 2، 3) لا اثنان -- min_points_per_topic الافتراضي في
    # config.yaml (٤) يستثني طبقة (أ) بثلاث نقاط لا أربع (Issue #658 العطل ٢).
    run_client = _Client([_Resp([_Block("tool_use", input_={
        "issues": [
            {"title": "قضية تكامل", "event": "حدث تكامل", "agreement": "dispute",
             "point_ids": [0, 2, 3]},
        ],
    })])])
    ycl.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    points_path = ycl.POINTS_DIR / "2099-02-02.json"
    points_path.write_text(json.dumps({"points": points}, ensure_ascii=False), encoding="utf-8")
    try:
        result = ycl.run(cluster_cfg, date_str="2099-02-02", client=run_client)
        check("run(): إحصاءات متّسقة مع مخرج العنقدة",
              result["stats"]["points_in"] == 4 and result["stats"]["topics_out"] == 1 and
              result["stats"]["layer_a"] == 1, result["stats"])
        check("run(): عدّادا سجل الاستهلاك وحدّ النقاط الجديدان صفر عند عدم انطباقهما",
              result["stats"]["topics_seen_skipped"] == 0 and
              result["stats"]["topics_below_min_points"] == 0, result["stats"])
        check("run(): points_dropped_over_cap صفر حين النقاط دون السقف (Issue #660 الإصلاح ٢)",
              result["stats"]["points_dropped_over_cap"] == 0, result["stats"])
        check("run(): عدّادا الإسقاط الجديدان (تاريخ قديم/طابع فاسد) صفر عند عدم انطباقهما (Issue #662)",
              result["stats"]["points_dropped_stale_date"] == 0 and
              result["stats"]["points_dropped_bad_timestamp"] == 0, result["stats"])
        check("run(): topics_merged صفر بلا دمج (قضية واحدة فقط، merge_duplicate_events لا تُستدعى)",
              result["stats"]["topics_merged"] == 0 and result["merged_events"] == [],
              (result["stats"], result["merged_events"]))
        check("run(): dispute بقناتين مختلفتين خرج cross_source في الإحصاءات (Issue #662 العطل ٤)",
              result["stats"]["cross_source"] == 1 and result["topics"][0]["agreement"] ==
              "cross_source", result["stats"])
        saved_path = ycl.save_output(result)
        reloaded = ycl.load_topics("2099-02-02")
        check("save_output/load_topics: تكامل الحفظ والقراءة",
              reloaded["topics"][0]["title"] == "قضية تكامل", reloaded)
    finally:
        points_path.unlink(missing_ok=True)
        (ycl.TOPICS_DIR / "2099-02-02.json").unlink(missing_ok=True)

    # ── run(): max_points_per_call يقصّ النافذة فعليًا قبل نداء العنقدة (Issue #660 الإصلاح ٢) ──
    cap_cfg = load_config()
    cap_cfg.setdefault("youtube", {}).setdefault("cluster", {})["max_points_per_call"] = 2
    capped_run_client = _Client([_Resp([_Block("tool_use", input_={"issues": []})])])
    ycl.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    capped_points_path = ycl.POINTS_DIR / "2099-02-03.json"
    capped_points_path.write_text(json.dumps({"points": points}, ensure_ascii=False),
                                   encoding="utf-8")
    try:
        capped_result = ycl.run(cap_cfg, date_str="2099-02-03", client=capped_run_client)
        check("run(): points_in يبقى حجم النافذة الكاملة قبل القصّ",
              capped_result["stats"]["points_in"] == 4, capped_result["stats"])
        check("run(): points_dropped_over_cap يعكس القصّ الفعلي (4 نقاط، سقف 2)",
              capped_result["stats"]["points_dropped_over_cap"] == 2, capped_result["stats"])
        sent_brief = capped_run_client.messages.calls[0]["messages"][0]["content"]
        check("run(): النداء الفعلي للنموذج يستلم نقاطًا مقصوصة لا النافذة الكاملة",
              len(json.loads(sent_brief)) == 2, sent_brief)
    finally:
        capped_points_path.unlink(missing_ok=True)
        (ycl.TOPICS_DIR / "2099-02-03.json").unlink(missing_ok=True)


def test_youtube_article() -> None:
    """المرحلة الرابعة (src/youtube_article.py، Issue #646): كتابة مقالات
    من أعلى القضايا. لا شبكة، لا نموذج فعلي -- الحارس والكتابة كلاهما
    مموَّهان بفاكة محلية. يغطّي: التحقّق من بنية المقال، حارس المحظورات
    (طبقة ج فقط)، الترقيم بلا فجوات، وبناء index.md."""
    ya = youtube_article
    ycl = youtube_cluster
    article_cfg = load_config()

    def _valid_article(title="عنوان-سؤال تجريبي عن قضية ما؟", filler_words=300,
                        include_likelihood=True, sources_heading="## المصادر", extra_body=""):
        # ٣٠٠ كلمة حشو + جملة الترجيح ⇒ تقع مريحًا داخل نافذة ٢٥٠–٧٥٠ كلمة
        # (youtube.article.min_words/max_words) بلا أي عنوان ## عدا قسم
        # المصادر (النسخة الثالثة، Issue #690). لا سطر **التقدير:** هنا --
        # ممنوع في النسخة الرابعة (Issue #695)؛ عبارة الترجيح مدمجة في جملة
        # نثرية عادية بدل صندوق التقدير الذي زال.
        filler = " ".join(["كلمة"] * filler_words)
        likelihood_sentence = ("وهذا مرجّح بقوة، ولا يسندها إلا مصدر واحد."
                                if include_likelihood else "")
        parts = [filler, likelihood_sentence, extra_body]
        body = "\n\n".join(p for p in parts if p)
        return (f"# {title}\n\n{body}\n\n---\n{sources_heading}\n"
                f"قناة تجريبية -- عنوان الفيديو -- رابط")

    # ── _validate_article_text: بنية إلزامية (Issue #690 -- نثر متّصل بلا أقسام) ──
    ok, reason = ya._validate_article_text(_valid_article(), article_cfg)
    check("مقال نثري مطابق للبنية الجديدة يُقبَل", ok, reason)

    ok, reason = ya._validate_article_text("مقال بلا عنوان رئيسي\n\n## سؤال\nنص", article_cfg)
    check("مقال لا يبدأ بـ# يُرفَض", not ok and "عنوان" in reason, reason)

    # ── Issue #695: عكس تام -- سطر **التقدير:** كان إلزاميًا فصار ممنوعًا ──
    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="**التقدير:** مرجّح بقوة أن يحدث كذا"), article_cfg)
    check("مقال فيه سطر **التقدير:** يُرفَض (ممنوع في النسخة الرابعة)",
          not ok and "صندوق تقدير" in reason and "السطر" in reason, reason)

    ok, reason = ya._validate_article_text(_valid_article(include_likelihood=False), article_cfg)
    check("مقال بلا أي عبارة من سلّم الترجيح في المتن يُرفَض",
          not ok and "سلّم الترجيح" in reason, reason)

    ok, reason = ya._validate_article_text(
        _valid_article(sources_heading="## قسم آخر"), article_cfg)
    check("غياب قسم ## المصادر يُرفَض", not ok and "مصادر" in reason, reason)

    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="## من قال ماذا\nنقاش الأطراف هنا."), article_cfg)
    check("مقال فيه قسم ## غير المصادر يُرفَض (عكس بنية 'النسخة الثانية' القديمة)",
          not ok and "أقسام ##" in reason, reason)

    ok, reason = ya._validate_article_text(_valid_article(filler_words=5), article_cfg)
    check("مقال أقصر من الحدّ الأدنى (250 كلمة) يُرفَض",
          not ok and "قصير جدًا" in reason and "الأدنى 250" in reason, reason)

    ok, reason = ya._validate_article_text(_valid_article(filler_words=800), article_cfg)
    check("مقال أطول من الحدّ الأعلى (750 كلمة) يُرفَض",
          not ok and "طويل جدًا" in reason and "الأعلى 750" in reason, reason)

    # ── فحوص جديدة على "المتن" (بين نهاية العنوان الرئيسي وبداية ## المصادر) ──
    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="النتيجة هنا — كما يبدو — واضحة تمامًا."), article_cfg)
    check("شرطة معترضة (—) في المتن تُرفَض",
          not ok and "شرطة معترضة" in reason and "2" in reason, reason)

    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="نقطة أولى مهمة.\n- بند أول\n- بند ثانٍ"), article_cfg)
    check("قائمة نقطية في المتن تُرفَض", not ok and "سطر قائمة" in reason, reason)

    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="نص عادي و**نصّ غامق زائد**هنا."), article_cfg)
    check("نصّ غامق في المتن يُرفَض",
          not ok and "نصّ غامق" in reason, reason)

    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="فقرة أولى من المتن.\n\n---\n\nفقرة بعد فاصل زائد."),
        article_cfg)
    check("فاصل أفقي (---) داخل المتن (غير الذي يسبق المصادر) يُرفَض",
          not ok and "فاصل أفقي" in reason, reason)

    # ── حارس التكرار القالبي (Issue #690 النقطة ٣) ──
    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="وتجدر الإشارة إلى أن الأمر ما زال قيد المتابعة."),
        article_cfg)
    check("عبارة محظورة (تجدر الإشارة) تُرفَض",
          not ok and "تجدر الإشارة" in reason, reason)

    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="ليس هذا خطأ بل صوابًا. والأمر لا يبدو معقدًا بل بسيطًا."),
        article_cfg)
    check("تركيبا تقابل (ليس..بل / لا..بل) في مقال واحد يُرفَضان (الحدّ 1)",
          not ok and "تركيب التقابل" in reason and "2" in reason, reason)

    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="ليس هذا خطأ بل صوابًا."), article_cfg)
    check("تركيب تقابل واحد داخل الحدّ المسموح يُقبَل", ok, reason)

    # ── Issue #695: نسب مئوية وطوابع زمنية مقوّسة ممنوعة تمامًا في المتن ──
    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="الاحتمال مرجّح (٥٥–٧٥٪) بحسب هذا العرض، وآخر أعلى (٧٥–٩٠٪)."),
        article_cfg)
    check("نسب مئوية في المتن تُرفَض، والرسالة تذكر ما وُجد فعلًا",
          not ok and "نسب مئوية" in reason and "٥٥–٧٥٪" in reason and "٧٥–٩٠٪" in reason, reason)

    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="قال ذلك في اللقاء [٩:٥٣] حين سُئل عن الأمر."), article_cfg)
    check("طابع زمني مقوّس [٩:٥٣] في المتن يُرفَض، والرسالة تذكر الطابع نفسه",
          not ok and "طوابع مقوّسة" in reason and "٩:٥٣" in reason, reason)

    # ── Issue #695: "يفترض أن" حدّ تكرار (٢) لا منع تام ──
    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="بيسنت يفترض أن كذا. وأحمد يفترض أن غير ذلك."), article_cfg)
    check("'يفترض أن' مرتين (ضمن الحدّ الافتراضي 2) تُقبَل", ok, reason)

    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="بيسنت يفترض أن كذا. وأحمد يفترض أن غير ذلك. "
                                   "وثالث يفترض أن شيئًا آخر تمامًا."), article_cfg)
    check("'يفترض أن' ثلاث مرات (يتجاوز الحدّ 2) تُرفَض",
          not ok and "يفترض أن" in reason and "3" in reason, reason)

    # ── Issue #695: عبارات محظورة جديدة (ثقة قالبية + عرض مصادر متقابلة) ──
    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="والحكم هنا بثقة منخفضة لأن المصدر واحد."), article_cfg)
    check("عبارة محظورة جديدة (بثقة منخفضة) تُرفَض", not ok and "بثقة منخفضة" in reason, reason)

    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="وفي النهاية يبقى القارئ أمام روايتين متقابلتين."), article_cfg)
    check("عبارة محظورة جديدة (يبقى القارئ أمام) تُرفَض",
          not ok and "يبقى القارئ أمام" in reason, reason)

    # ── مؤشّر «فاعل الجملة متحدث» (Issue #695 البند ٣) -- تحذير استرشادي لا حارس رفض ──
    speaker_points = [{"speaker": "أحمد بيسنت"}, {"speaker": "خالد أحمد"}]
    high_ratio_narrative = ("أحمد بيسنت يقول كذا. خالد أحمد يرى غير ذلك. "
                             "أحمد بيسنت يضيف رأيًا آخر. الحدث تطوّر بشكل كبير جدًا اليوم.")
    ratio, sentence_count = ya._speaker_subject_ratio(high_ratio_narrative, speaker_points)
    check("_speaker_subject_ratio: يحسب النسبة المتوقعة (3 من 4 جمل تبدأ باسم متحدث)",
          sentence_count == 4 and abs(ratio - 0.75) < 0.01, (ratio, sentence_count))

    low_ratio_narrative = ("الحدث تصاعد بسرعة اليوم. الأزمة اتّسعت لتشمل قطاعات جديدة. "
                            "أحمد بيسنت يعلّق على ذلك. النتائج بدأت تظهر تدريجيًا.")
    ratio_low, count_low = ya._speaker_subject_ratio(low_ratio_narrative, speaker_points)
    check("_speaker_subject_ratio: نسبة منخفضة حين معظم الجمل عن الحدث لا المتحدثين",
          count_low == 4 and abs(ratio_low - 0.25) < 0.01, (ratio_low, count_low))

    check("_speaker_subject_ratio: بلا نقاط مصدرية (بلا أسماء) يعيد صفرًا بلا انهيار",
          ya._speaker_subject_ratio("جملة واحدة هنا فقط.", []) == (0.0, 1))

    warning_high = ya._speaker_subject_warning(high_ratio_narrative, speaker_points, article_cfg)
    check("_speaker_subject_warning: يُبلَّغ تحذيرًا استرشاديًا عند تجاوز الحدّ (لا رفضًا)",
          warning_high is not None and "استرشادي" in warning_high, warning_high)

    warning_low = ya._speaker_subject_warning(low_ratio_narrative, speaker_points, article_cfg)
    check("_speaker_subject_warning: دون الحدّ الاسترشادي لا يُبلَّغ بشيء", warning_low is None,
          warning_low)

    # ── قيم config.yaml (Issue #671) ──
    check("config: youtube.article.max_retries = 3",
          article_cfg.path("youtube.article.max_retries") == 3)
    check("config: youtube.article.max_tokens = 8000",
          article_cfg.path("youtube.article.max_tokens") == 8000)
    check("config: youtube.article.min_words = 250",
          article_cfg.path("youtube.article.min_words") == 250)
    check("config: youtube.article.max_words = 750",
          article_cfg.path("youtube.article.max_words") == 750)
    check("config: youtube.article.likelihood_terms يحوي عبارات السلّم الست",
          set(article_cfg.path("youtube.article.likelihood_terms", [])) ==
          set(ya.DEFAULT_LIKELIHOOD_TERMS))
    check("config: youtube.article.banned_phrases يطابق DEFAULT_BANNED_PHRASES",
          set(article_cfg.path("youtube.article.banned_phrases", [])) ==
          set(ya.DEFAULT_BANNED_PHRASES))
    check("config: youtube.article.max_contrast_constructions = 1",
          article_cfg.path("youtube.article.max_contrast_constructions") == 1)
    check("config: youtube.article.max_assumption_phrases = 2 (Issue #695)",
          article_cfg.path("youtube.article.max_assumption_phrases") == 2)
    check("config: youtube.article.max_speaker_subject_ratio = 0.35 (Issue #695)",
          article_cfg.path("youtube.article.max_speaker_subject_ratio") == 0.35)

    # ── _extract_headline / _slugify ──
    check("_extract_headline: يستخرج العنوان من السطر الأول بلا #",
          ya._extract_headline("# عنوان المقال هنا\n\nبقية النص") == "عنوان المقال هنا")
    check("_extract_headline: نص فارغ يعيد سلسلة فارغة بلا انهيار",
          ya._extract_headline("") == "")
    slug = ya._slugify("عنوان يحوي: علامات؟ ومسافات   متعددة!")
    check("_slugify: لا يحوي مسافات أو علامات ترقيم", " " not in slug and ":" not in slug, slug)
    check("_slugify: عنوان فارغ لا يعيد سلسلة فارغة (اسم ملف صالح دومًا)",
          ya._slugify("   ") != "")

    # ── check_forbidden: حارس المحظورات (طبقة ج فقط) ──
    class _Block:
        def __init__(self, type_, input_=None, text=None):
            self.type, self.input, self.text = type_, input_, text

    class _Usage:
        def __init__(self, input_tokens=100, output_tokens=50):
            self.input_tokens, self.output_tokens = input_tokens, output_tokens

    class _Resp:
        def __init__(self, content, stop_reason=None, usage=None):
            self.content, self.stop_reason, self.usage = content, stop_reason, usage

    class _Messages:
        def __init__(self, responses):
            self._responses = list(responses)
            self.calls: list = []

        def create(self, **kw):
            self.calls.append(kw)
            return self._responses.pop(0)

    class _Client:
        def __init__(self, responses):
            self.messages = _Messages(responses)

    article_cfg = load_config()
    topic_c = {"title": "قضية مصدر واحد", "layer": "c", "blocs": ["arabic"],
              "channels": ["الجزيرة"], "agreement": "agreement", "point_ids": [0]}
    member_points = [{"channel": "الجزيرة", "speaker": "ناطق", "statement": "بيان ما"}]

    blocked_client = _Client([_Resp([_Block("tool_use", input_={
        "blocked": True, "category": "accusation_named", "reason": "اتهام شخص مسمّى بفساد"})])])
    blocked, reason, guard_error, no_reason = ya.check_forbidden(topic_c, member_points,
                                                                  article_cfg, blocked_client)
    check("check_forbidden: اتهام شخص مسمّى بسبب مكتوب يُحظَر فعليًا",
          blocked and guard_error is None and not no_reason, reason)

    allowed_client = _Client([_Resp([_Block("tool_use", input_={
        "blocked": False, "category": "none", "reason": ""})])])
    blocked2, _, _, no_reason2 = ya.check_forbidden(topic_c, member_points, article_cfg,
                                                      allowed_client)
    check("check_forbidden: قضية عادية لا تُحظَر", not blocked2 and not no_reason2)

    # ── حارس صامت لا يُطاع: blocked=true بلا reason مكتوب يُعامَل كقبول (Issue #658 العطل ٣ بند أ) ──
    no_reason_client = _Client([_Resp([_Block("tool_use", input_={
        "blocked": True, "category": "market_moving_numbers", "reason": ""})])])
    blocked_nr, reason_nr, guard_error_nr, no_reason_nr = ya.check_forbidden(
        topic_c, member_points, article_cfg, no_reason_client)
    check("check_forbidden: حظر بسبب فارغ يُقبَل (الحارس الصامت لا يُطاع)",
          not blocked_nr and guard_error_nr is None and no_reason_nr, (reason_nr, no_reason_nr))

    no_reason_whitespace_client = _Client([_Resp([_Block("tool_use", input_={
        "blocked": True, "category": "military_ops", "reason": "   "})])])
    blocked_nr2, _, _, no_reason_nr2 = ya.check_forbidden(
        topic_c, member_points, article_cfg, no_reason_whitespace_client)
    check("check_forbidden: سبب مؤلَّف من مسافات فقط يُعامَل كسبب فارغ",
          not blocked_nr2 and no_reason_nr2)

    class _FailingMessages:
        def create(self, **kw):
            from anthropic import APIError
            import httpx as _httpx
            raise APIError(
                "عطل شبكي مؤقت",
                request=_httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
                body=None)

    class _FailingClient:
        def __init__(self):
            self.messages = _FailingMessages()

    blocked3, _, guard_error3, no_reason3 = ya.check_forbidden(topic_c, member_points,
                                                                article_cfg, _FailingClient())
    check("check_forbidden: فشل نداء الحارس لا يحظر تلقائيًا، ويُسجَّل السبب",
          not blocked3 and guard_error3 is not None and not no_reason3, guard_error3)

    # ── draft_article: محاولة ثانية بعد بنية فاسدة أولى ──
    retry_client = _Client([
        _Resp([_Block("text", text="نص فاسد بلا عنوان رئيسي")]),
        _Resp([_Block("text", text=_valid_article("عنوان بعد إعادة المحاولة"))]),
    ])
    topic_a = {"title": "قضية طبقة أ", "layer": "a", "blocs": ["arabic", "turkish"],
              "channels": ["الجزيرة"], "agreement": "dispute", "point_ids": [0]}
    text, error = ya.draft_article(topic_a, member_points, article_cfg, retry_client)
    check("draft_article: إعادة المحاولة بعد بنية فاسدة أولى تنجح",
          error is None and text is not None and "عنوان بعد إعادة المحاولة" in text, error)

    always_bad_client = _Client([
        _Resp([_Block("text", text="فاسد ١")]),
        _Resp([_Block("text", text="فاسد ٢")]),
        _Resp([_Block("text", text="فاسد ٣")]),
    ])
    text2, error2 = ya.draft_article(topic_a, member_points, article_cfg, always_bad_client)
    check("draft_article: فشل كل المحاولات يعيد سببًا صريحًا لا نصًّا",
          text2 is None and error2 is not None, error2)

    # ── draft_article: stop_reason=max_tokens يُسجَّل صراحةً مع عدد الرموز
    # المستهلكة في سبب الفشل النهائي (Issue #662 تعليق المتابعة) ──
    max_tokens_client = _Client([
        _Resp([_Block("text", text="نص ناقص بسبب القطع")], stop_reason="max_tokens",
              usage=_Usage(input_tokens=1200, output_tokens=8000)),
        _Resp([_Block("text", text="نص ناقص ثانيةً")], stop_reason="max_tokens",
              usage=_Usage(input_tokens=1200, output_tokens=8000)),
        _Resp([_Block("text", text="نص ناقص ثالثةً")], stop_reason="max_tokens",
              usage=_Usage(input_tokens=1200, output_tokens=8000)),
    ])
    text3, error3 = ya.draft_article(topic_a, member_points, article_cfg, max_tokens_client)
    check("draft_article: قطع stop_reason=max_tokens يذكر ذلك صراحةً مع عدد رموز المخرج",
          text3 is None and error3 is not None and "stop_reason=max_tokens" in error3 and
          "8000" in error3, error3)

    # ── draft_article: مؤشّر cross_source/internal يصل النموذج كـ dispute
    # (Issue #662 العطل ٤) -- prompts/youtube_article.md خارج النطاق، ولا
    # يعرف إلا dispute/agreement/echo ──
    for facing_agreement in ("cross_source", "internal"):
        topic_facing = {**topic_a, "agreement": facing_agreement}
        facing_client = _Client([_Resp([_Block("text", text=_valid_article())])])
        ya.draft_article(topic_facing, member_points, article_cfg, facing_client)
        sent = facing_client.messages.calls[0]["messages"][0]["content"]
        check(f"draft_article: مؤشّر {facing_agreement} يُترجَم إلى dispute في نداء النموذج",
              "مؤشّر الخلاف بين المصادر لهذه القضية: dispute" in sent, sent)
    agreement_client = _Client([_Resp([_Block("text", text=_valid_article())])])
    ya.draft_article({**topic_a, "agreement": "agreement"}, member_points, article_cfg,
                      agreement_client)
    check("draft_article: مؤشّر agreement يمرّ بلا تغيير",
          "مؤشّر الخلاف بين المصادر لهذه القضية: agreement" in
          agreement_client.messages.calls[0]["messages"][0]["content"])

    # ── _arabic_point_count_phrase / _collect_warnings / _append_warnings
    # (Issue #662 العطل ٣) ──
    check("_arabic_point_count_phrase: مفرد/مثنى/جمع",
          ya._arabic_point_count_phrase(1) == "نقطة" and
          ya._arabic_point_count_phrase(2) == "نقطتين" and
          ya._arabic_point_count_phrase(5) == "5 نقاط", (
              ya._arabic_point_count_phrase(1), ya._arabic_point_count_phrase(2),
              ya._arabic_point_count_phrase(5)))

    warn_points = [
        {"statement": "بايدن يزور المنطقة", "quote_original": "he visited the region"},
        {"statement": "نص لا يحوي أي اسم علم من القائمة", "quote_original": "..."},
        {"statement": "نتنياهو يتحدث عن الحرب", "quote_original": "he talked about the war"},
        {"statement": "نتنياهو مجددًا في نقطة أخرى", "quote_original": "again, no name here"},
    ]
    collected = ya._collect_warnings(warn_points, article_cfg)
    check("_collect_warnings: تحذير واحد لكل اسم مجمَّع (لا سطر لكل نقطة)", len(collected) == 2,
          collected)
    check("_collect_warnings: نتنياهو ورد في نقطتين، بايدن في نقطة واحدة",
          any("بايدن" in w and "نقطة" in w and "نقطتين" not in w for w in collected) and
          any("نتنياهو" in w and "نقطتين" in w for w in collected), collected)
    check("_collect_warnings: نقاط بلا اسم مشكوك لا تعيد شيئًا",
          ya._collect_warnings([{"statement": "لا شيء هنا", "quote_original": ""}],
                                article_cfg) == [])

    appended = ya._append_warnings("# عنوان\n\nنص المقال\n---\nالمصادر: رابط", collected)
    check("_append_warnings: يضيف القسم بعد المصادر مع الترويسة الصحيحة",
          appended.rstrip().endswith(f"- {collected[-1]}") and ya.WARNINGS_HEADER in appended and
          all(f"- {w}" in appended for w in collected), appended)
    check("_append_warnings: بلا تحذيرات، النص يعود بلا تغيير",
          ya._append_warnings("نص كما هو", []) == "نص كما هو")

    # ── عناوين مقترحة (Issue #680): _validate_headlines / generate_headlines / _append_headlines ──
    hl_points = [{"quote_original": "he commented and biden replied"}]
    good_headlines = ["هل يتصاعد الموقف بعد بيان بايدن؟", "بيان بايدن يفتح الباب لتصعيد جديد",
                       "تصعيد مرجّح بعد رد بايدن على الحدث"]
    ok_hl, reason_hl = ya._validate_headlines(good_headlines, hl_points[0]["quote_original"], [
        {"ar": "بايدن", "aliases": ["biden"]}], 15)
    check("_validate_headlines: ثلاثة عناوين صالحة (سؤال أول + كلمات ضمن الحدّ + اسم موثَّق) تُقبَل",
          ok_hl, reason_hl)

    not_question = ["تصعيد وشيك بعد بيان بايدن", "عنوان ثانٍ", "عنوان ثالث"]
    ok_nq, reason_nq = ya._validate_headlines(not_question, hl_points[0]["quote_original"], [], 15)
    check("_validate_headlines: العنوان الأول بلا علامة استفهام يُرفَض",
          not ok_nq and "سؤال" in reason_nq, reason_nq)

    too_long = ["هل " + " ".join(["كلمة"] * 20) + "؟", "قصير", "قصير أيضًا"]
    ok_long, reason_long = ya._validate_headlines(too_long, "", [], 15)
    check("_validate_headlines: عنوان يتجاوز سقف الكلمات يُرفَض",
          not ok_long and "15 كلمة" in reason_long, reason_long)

    unsourced_headlines = ["هل صرّح ترامب بشيء؟", "عنوان ثانٍ", "عنوان ثالث"]
    ok_uns, reason_uns = ya._validate_headlines(
        unsourced_headlines, hl_points[0]["quote_original"],
        [{"ar": "ترامب", "aliases": ["trump"]}], 15)
    check("_validate_headlines: اسم علم غير موثَّق بالاقتباس الأصلي يُرفَض",
          not ok_uns and "ترامب" in reason_uns, reason_uns)

    hl_topic = {"title": "قضية عناوين تجريبية"}
    hl_member_points = [{"channel": "الجزيرة", "speaker": "ناطق", "statement": "بيان ما",
                         "quote_original": "he commented and biden replied"}]

    hl_success_client = _Client([_Resp([_Block("tool_use", input_={"headlines": good_headlines})])])
    hl_result, hl_error = ya.generate_headlines(hl_topic, hl_member_points, article_cfg,
                                                 hl_success_client)
    check("generate_headlines: محاولة أولى صالحة تُقبَل بلا إعادة",
          hl_error is None and hl_result == good_headlines, (hl_result, hl_error))

    hl_retry_client = _Client([
        _Resp([_Block("tool_use", input_={"headlines": not_question})]),
        _Resp([_Block("tool_use", input_={"headlines": good_headlines})]),
    ])
    hl_result2, hl_error2 = ya.generate_headlines(hl_topic, hl_member_points, article_cfg,
                                                   hl_retry_client)
    check("generate_headlines: إعادة محاولة بعد عنوان أول بلا صيغة سؤال تنجح",
          hl_error2 is None and hl_result2 == good_headlines, (hl_result2, hl_error2))

    hl_bad_client = _Client([
        _Resp([_Block("tool_use", input_={"headlines": not_question})]),
        _Resp([_Block("tool_use", input_={"headlines": not_question})]),
    ])
    hl_result3, hl_error3 = ya.generate_headlines(hl_topic, hl_member_points, article_cfg,
                                                   hl_bad_client)
    check("generate_headlines: فشل كل المحاولات يعيد سببًا صريحًا لا قائمة",
          hl_result3 is None and hl_error3 is not None, hl_error3)

    appended_hl = ya._append_headlines("# عنوان\n\nنص المقال", good_headlines)
    check("_append_headlines: يضيف القسم بترويسة صحيحة وترقيم ١-٣",
          ya.HEADLINES_HEADER in appended_hl and
          all(f"{i}. {h}" in appended_hl for i, h in enumerate(good_headlines, start=1)),
          appended_hl)

    # ── save_articles / build_index: ترقيم بلا فجوات + جدول الفهرس + عمود التنبيهات ──
    saved = ya.save_articles("2099-03-03", [
        {"topic": {"title": "الأولى", "event": "حدث الأولى", "layer": "a",
                   "blocs": ["arabic", "turkish"],
                   "channels": ["الجزيرة"], "agreement": "cross_source"},
         "text": _valid_article("العنوان الأول؟"), "warnings": collected},
        {"topic": {"title": "الثانية", "event": "حدث الثانية", "layer": "c",
                   "blocs": ["arabic"],
                   "channels": ["العربية"], "agreement": "agreement"},
         "text": _valid_article("العنوان الثاني؟")},
    ])
    try:
        check("save_articles: ترقيم متتابع 01، 02",
              [s["filename"][:2] for s in saved] == ["01", "02"], saved)
        check("save_articles: warnings_count يُحسَب من item['warnings']، وصفر بلا حقل warnings",
              saved[0]["warnings_count"] == 2 and saved[1]["warnings_count"] == 0, saved)
        # event القضية يصل حقل المسودة المحفوظة (طلب المراجعة على Issue #680
        # -- مصدر كلمات بحث الصورة التعبيرية لاحقًا في youtube_publish.py)
        check("save_articles: event القضية يُنقَل من topic['event'] حرفيًا",
              saved[0]["event"] == "حدث الأولى" and saved[1]["event"] == "حدث الثانية", saved)
        out_dir = ya.ARTICLES_DIR / "2099-03-03"
        check("save_articles: الملفات مكتوبة فعليًا على القرص",
              all((out_dir / s["filename"]).exists() for s in saved))
        index_text = (out_dir / "index.md").read_text(encoding="utf-8")
        check("build_index: الفهرس يحوي عنواني المقالين",
              "العنوان الأول؟" in index_text and "العنوان الثاني؟" in index_text, index_text)
        check("build_index: الفهرس يحوي عمود الحدث والطبقة والخلاف والتنبيهات",
              "حدث الأولى" in index_text and "| a |" in index_text and
              "cross_source" in index_text and "تنبيهات" in index_text, index_text)
    finally:
        import shutil as _shutil
        _shutil.rmtree(ya.ARTICLES_DIR / "2099-03-03", ignore_errors=True)

    # ── build_index: ثلاثة تنبيهات فأكثر تُعلَّم بوضوح (نص الـIssue) ──
    marked_index = ya.build_index([
        {"number": 1, "filename": "01-x.md", "headline": "ع", "event": "حدث ع",
         "layer": "c", "blocs": ["arabic"],
         "channels": ["ق"], "agreement": "agreement", "warnings_count": 3},
        {"number": 2, "filename": "02-y.md", "headline": "ص", "event": "حدث ص",
         "layer": "c", "blocs": ["arabic"],
         "channels": ["ق"], "agreement": "agreement", "warnings_count": 1},
    ])
    check("build_index: ثلاثة تنبيهات فأكثر تُعلَّم بـ⚠️، وأقل من ثلاثة رقم عادي",
          "⚠️" in marked_index.splitlines()[4] and "⚠️" not in marked_index.splitlines()[5],
          marked_index)

    # ── run(): تكامل كامل -- طبقة أ تتجاوز الحارس، طبقة ج تُحظَر أو تُكتَب أو
    # يُتجاوَز حظرها بلا سبب مكتوب (Issue #658)، وتُسجَّل نقاط المقالات
    # الناجحة في سجل الاستهلاك ──
    points_for_run = [
        {"video_id": "vid0", "bloc": "arabic", "channel": "الجزيرة", "speaker": "ناطق",
         "statement": "قول 0", "quote_arabic": "اقتباس 0", "type": "fact",
         "video_title": "فيديو 0", "video_url": "https://youtube.com/watch?v=0",
         "timestamp": 5},
        {"video_id": "vid1", "bloc": "turkish", "channel": "CNN Türk", "speaker": "متحدث",
         "statement": "قول 1", "quote_arabic": "اقتباس 1", "type": "fact",
         "video_title": "فيديو 1", "video_url": "https://youtube.com/watch?v=1",
         "timestamp": None},
        # نقطة اسم علم مشكوك (Issue #662 العطل ٣) -- statement يذكر "بايدن"
        # بلا نظير له (biden) في quote_original، فتُنقَل تحذيرًا إلى ذيل مقال
        # القضية التي تضمّها.
        {"video_id": "vid2", "bloc": "arabic", "channel": "قناة ثالثة", "speaker": "ناطق آخر",
         "statement": "بايدن يعلّق على القضية", "quote_original": "he commented on the issue",
         "quote_arabic": "اقتباس 2", "type": "fact", "video_title": "فيديو 2",
         "video_url": "https://youtube.com/watch?v=2", "timestamp": 12},
    ]
    topics_for_run = [
        {"title": "طبقة أ تتجاوز الحارس", "event": "حدث أ", "layer": "a",
         "blocs": ["arabic", "turkish"], "channels": ["الجزيرة", "CNN Türk"],
         "agreement": "dispute", "point_ids": [0, 1, 2]},
        {"title": "طبقة ج محظورة", "event": "حدث ج١", "layer": "c", "blocs": ["arabic"],
         "channels": ["الجزيرة"], "agreement": "agreement", "point_ids": [0]},
        {"title": "طبقة ج مسموحة", "event": "حدث ج٢", "layer": "c", "blocs": ["arabic"],
         "channels": ["الجزيرة"], "agreement": "agreement", "point_ids": [0]},
        {"title": "طبقة ج حظر بلا سبب", "event": "حدث ج٣", "layer": "c", "blocs": ["arabic"],
         "channels": ["الجزيرة"], "agreement": "agreement", "point_ids": [1]},
    ]

    # كل مقال ناجح يتبعه نداء عناوين منفصل (generate_headlines، Issue #680) --
    # ثلاثة عناوين عامة بلا أسماء أعلام كي لا تصطدم بحارس _validate_headlines
    # (لا اسم غير موثَّق بالاقتباسات الأصلية لهذه القضايا التجريبية).
    hl_a = ["هل يشتد الخلاف حول هذه القضية؟", "الخلاف حول القضية يتصاعد بحسب المصادر",
            "تصعيد مرجّح في القضية بحسب المتابعين"]
    hl_c2 = ["هل تتضح ملامح القضية قريبًا؟", "القضية تتضح ملامحها تدريجيًا",
             "وضوح مرجّح لملامح القضية قريبًا"]
    hl_c3 = ["هل ينتهي الجدل حول القضية؟", "الجدل حول القضية يقترب من نهايته",
             "نهاية مرجّحة لجدل القضية"]

    run_client = _Client([
        _Resp([_Block("text", text=_valid_article("سؤال عن قضية الطبقة أ؟"))]),
        _Resp([_Block("tool_use", input_={"headlines": hl_a})]),
        _Resp([_Block("tool_use", input_={
            "blocked": True, "category": "military_ops", "reason": "عمليات عسكرية وشيكة"})]),
        _Resp([_Block("tool_use", input_={"blocked": False, "category": "none", "reason": ""})]),
        _Resp([_Block("text", text=_valid_article("سؤال عن قضية الطبقة ج المسموحة؟"))]),
        _Resp([_Block("tool_use", input_={"headlines": hl_c2})]),
        _Resp([_Block("tool_use", input_={
            "blocked": True, "category": "market_moving_numbers", "reason": ""})]),
        _Resp([_Block("text", text=_valid_article("سؤال عن قضية بلا سبب حظر؟"))]),
        _Resp([_Block("tool_use", input_={"headlines": hl_c3})]),
    ])

    ycl.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    ycl.TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    points_path = ycl.POINTS_DIR / "2099-04-04.json"
    topics_path = ycl.TOPICS_DIR / "2099-04-04.json"
    points_path.write_text(json.dumps({"points": points_for_run}, ensure_ascii=False),
                            encoding="utf-8")
    topics_path.write_text(json.dumps({"run_date": "2099-04-04", "topics": topics_for_run},
                                       ensure_ascii=False), encoding="utf-8")
    seen_backup2 = ycl.SEEN_PATH.read_text(encoding="utf-8") if ycl.SEEN_PATH.exists() else None
    try:
        result = ya.run(article_cfg, date_str="2099-04-04", client=run_client)
        stats = result["stats"]
        check("run(): طبقة أ لا تستدعي حارس المحظورات إطلاقًا",
              stats["guard_calls"] == 3, stats)
        check("run(): ثلاثة مقالات تُكتَب (طبقة أ + ج مسموحة + ج بلا سبب حظر مقبولة)، "
              "وقضية واحدة محظورة فعليًا تُستبعَد",
              stats["articles_written"] == 3 and stats["blocked_forbidden"] == 1 and
              stats["skipped"] == 1, stats)
        check("run(): حظر بلا سبب مكتوب يُقبَل ويُعدّ في topics_blocked_no_reason لا blocked_forbidden",
              stats["topics_blocked_no_reason"] == 1, stats)
        check("run(): سبب الاستبعاد مسجَّل صراحة لا صامتًا",
              "محظورة" in result["skipped"][0]["reason"], result["skipped"])
        seen_after = ycl.load_seen_points()
        check("run(): نقاط المقالات المكتوبة فعليًا تُسجَّل في سجل الاستهلاك",
              ycl.point_key(points_for_run[0]) in seen_after and
              ycl.point_key(points_for_run[1]) in seen_after, seen_after)

        # ── التحذيرات تصل فعليًا إلى ذيل المقال وعمود الفهرس (Issue #662 العطل ٣) ──
        layer_a_article = next(a for a in result["articles"] if a["layer"] == "a")
        check("run(): warnings_count محسوب لمقال القضية التي تضمّ نقطة الاسم المشكوك",
              layer_a_article["warnings_count"] == 1, layer_a_article)
        article_path = (ya.ARTICLES_DIR / "2099-04-04" / layer_a_article["filename"])
        article_text = article_path.read_text(encoding="utf-8")
        check("run(): نصّ المقال المحفوظ يحوي قسم التحذيرات واسم العلم المشكوك",
              ya.WARNINGS_HEADER in article_text and "بايدن" in article_text, article_text)
        index_text = (ya.ARTICLES_DIR / "2099-04-04" / "index.md").read_text(encoding="utf-8")
        index_row = next(ln for ln in index_text.splitlines()
                          if layer_a_article["headline"] in ln)
        check("run(): سطر المقال في index.md يحمل قيمة عمود التنبيهات الصحيحة",
              index_row.rstrip().endswith("1 |"), index_row)

        # ── عناوين مقترحة (Issue #680): وصلت فعليًا لكل مقال ناجح، ولا فشل هنا ──
        check("run(): صفر فشل في اقتراح العناوين لكل المقالات الناجحة الثلاثة",
              stats["headline_failures"] == 0, stats)
        check("run(): نصّ المقال المحفوظ يحوي قسم العناوين المقترحة كاملًا",
              ya.HEADLINES_HEADER in article_text and hl_a[0] in article_text and
              hl_a[1] in article_text and hl_a[2] in article_text, article_text)

        # ── مؤشّر «فاعل الجملة متحدث» (Issue #695) -- صفر تحذيرات هنا: نقاط
        # الاختبار تحمل ألقابًا عامة ("ناطق"، "متحدث") لا تظهر في متن المقال
        # المموَّه (حشو "كلمة" فقط)، فلا تطابق صدر أي جملة صدفةً ──
        check("run(): stats.speaker_subject_warnings صفر حين لا جملة تبدأ باسم متحدث",
              stats["speaker_subject_warnings"] == 0, stats)
    finally:
        points_path.unlink(missing_ok=True)
        topics_path.unlink(missing_ok=True)
        import shutil as _shutil
        _shutil.rmtree(ya.ARTICLES_DIR / "2099-04-04", ignore_errors=True)
        if seen_backup2 is None:
            ycl.SEEN_PATH.unlink(missing_ok=True)
        else:
            ycl.SEEN_PATH.write_text(seen_backup2, encoding="utf-8")

    # ── run(): يوكِّد وجود سجل الاستهلاك دومًا ولو بلا مقالات ناجحة (Issue #660 الإصلاح ٣) ──
    # صفر قضايا ⇐ صفر نداءات نموذج ⇐ seen_keys_to_mark فارغة ⇐ mark_points_seen لا
    # تُستدعى أصلًا -- بلا الإصلاح، SEEN_PATH لا يُنشَأ، وخطوة git add عليه في
    # الـworkflow تُسقِط الرفع كاملة (pathspec لم يطابق، exit code 128).
    ycl.TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    empty_topics_path = ycl.TOPICS_DIR / "2099-05-05.json"
    empty_topics_path.write_text(json.dumps({"run_date": "2099-05-05", "topics": []},
                                             ensure_ascii=False), encoding="utf-8")
    seen_backup3 = ycl.SEEN_PATH.read_text(encoding="utf-8") if ycl.SEEN_PATH.exists() else None
    try:
        if ycl.SEEN_PATH.exists():
            ycl.SEEN_PATH.unlink()
        empty_client = _Client([])
        result_empty = ya.run(article_cfg, date_str="2099-05-05", client=empty_client)
        check("run(): صفر قضايا ⇐ صفر مقالات، بلا استدعاء النموذج إطلاقًا",
              result_empty["stats"]["articles_written"] == 0 and
              len(empty_client.messages.calls) == 0, result_empty["stats"])
        check("run(): سجل الاستهلاك يُنشأ فارغًا ({}) حتى بلا استدعاء mark_points_seen "
              "(Issue #660 الإصلاح ٣)",
              ycl.SEEN_PATH.exists() and ycl.SEEN_PATH.read_text(encoding="utf-8") == "{}")
    finally:
        empty_topics_path.unlink(missing_ok=True)
        if seen_backup3 is None:
            ycl.SEEN_PATH.unlink(missing_ok=True)
        else:
            ycl.SEEN_PATH.write_text(seen_backup3, encoding="utf-8")


def test_youtube_publish() -> None:
    """المرحلة الخامسة (src/youtube_publish.py، Issue #676 وIssue #680):
    توصيل المسودة ودورة المراجعة والنشر بما كان قائمًا (imaging/store/
    review/publish) بلا تعديل على منطقها. لا شبكة -- review.create_issue/
    comment/fetch_issue_body/close_issue/remove_label وpublish.publish_one
    كلّها مموَّهة محليًا؛ بناء بطاقة العنوان نفسه محلي بالكامل (Pillow فقط)،
    وimagesearch.find_images/imaging.download_image/imaging.face_score
    مموَّهة أيضًا حيث تُختبَر صورة البطاقة التعبيرية (طلب مراجعة لاحق على
    Issue #680) فلا نداء شبكة حقيقي إطلاقًا في كل هذا الملف.
    يغطّي أيضًا الدرجة المركّبة والترتيب بها، تأجيل بناء البطاقة إلى ما بعد
    الاعتماد (ensure_title_card)، وقراءة اختيار العنوان من ثلاثة (Issue
    #680)."""
    yp = youtube_publish
    cfg = load_config()

    # ── bottom_bar_text: طبقة (ج) تُظهر اسم القناة وحده بلا ذكر كتلة ──
    check("bottom_bar_text: طبقتا أ/ب تعرضان الكتل والقنوات معًا",
          yp.bottom_bar_text("a", ["arabic", "persian"], ["الجزيرة", "Iran International"], cfg)
          == "عربية · فارسية — الجزيرة، Iran International")
    check("bottom_bar_text: طبقة ج تعرض اسم القناة وحده بلا كتلة (نصّ الـIssue)",
          yp.bottom_bar_text("c", ["arabic"], ["الجزيرة"], cfg) == "الجزيرة")
    check("bottom_bar_text: بلا كتل يعرض القنوات وحدها",
          yp.bottom_bar_text("b", [], ["الجزيرة", "العربية"], cfg) == "الجزيرة، العربية")

    # ── split_warnings: قاعدة حاسمة -- caption خالٍ من قسم التنبيهات (Issue #676) ──
    article_with_warnings = (
        "# عنوان تجريبي؟\n\nاستهلال.\n\n**التقدير:** مرجّح أن يحدث كذا\n\n"
        "## من قال ماذا\nنص.\n\n---\n## المصادر\nالجزيرة — عنوان الفيديو — "
        "https://youtube.com/watch?v=abc (٤:١٢)\n\n---\n" + yp.WARNINGS_HEADER +
        "\n- اسم 'فلان' ورد في نقطة بلا نظير له في الاقتباس الأصلي\n"
        "- اسم 'علان' ورد في نقطتين بلا نظير له في الاقتباس الأصلي\n"
    )
    caption, warnings = yp.split_warnings(article_with_warnings)
    check("split_warnings: caption خالٍ تمامًا من رأس قسم التنبيهات",
          yp.WARNINGS_HEADER not in caption, caption)
    check("split_warnings: caption خالٍ من نصّ التنبيهات نفسها",
          "بلا نظير له" not in caption, caption)
    check("split_warnings: caption يحتفظ بمتن المقال كاملًا (العنوان + الأقسام + المصادر)",
          "# عنوان تجريبي؟" in caption and "## المصادر" in caption and
          "youtube.com/watch?v=abc" in caption, caption)
    check("split_warnings: التنبيهان يُستخرجان كاملَين نصًّا لحقل warnings",
          warnings == ["اسم 'فلان' ورد في نقطة بلا نظير له في الاقتباس الأصلي",
                       "اسم 'علان' ورد في نقطتين بلا نظير له في الاقتباس الأصلي"],
          warnings)

    article_no_warnings = "# عنوان بلا تنبيهات؟\n\nنص.\n\n## المصادر\nقناة — عنوان — رابط\n"
    caption2, warnings2 = yp.split_warnings(article_no_warnings)
    check("split_warnings: مقال بلا قسم تنبيهات أصلًا يعود بلا تغيير جوهري ولا استثناء",
          "# عنوان بلا تنبيهات؟" in caption2 and "## المصادر" in caption2, caption2)
    check("split_warnings: بلا تنبيهات ⇒ قائمة فارغة", warnings2 == [], warnings2)

    # ── extract_source_lines ──
    lines = yp.extract_source_lines(caption)
    check("extract_source_lines: يستخرج سطر المصدر الوحيد هنا",
          lines == ["الجزيرة — عنوان الفيديو — https://youtube.com/watch?v=abc (٤:١٢)"],
          lines)
    check("extract_source_lines: قسم غائب يعيد قائمة فارغة بلا استثناء",
          yp.extract_source_lines("# عنوان بلا قسم مصادر\nنص") == [])

    # ── parse_index: جولة كاملة عبر youtube_article.build_index الفعلية (بلا تعديل عليها) ──
    saved_index = [
        {"number": 1, "filename": "01-a.md", "headline": "عنوان أ؟", "event": "حدث أ",
         "layer": "a", "blocs": ["arabic", "turkish"], "channels": ["الجزيرة", "CNN Türk"],
         "agreement": "cross_source", "warnings_count": 2},
        {"number": 2, "filename": "02-b.md", "headline": "عنوان ب؟", "event": "حدث ب",
         "layer": "c", "blocs": ["arabic"], "channels": ["العربية"], "agreement": "agreement",
         "warnings_count": 0},
    ]
    index_md = youtube_article.build_index(saved_index)
    parsed = yp.parse_index(index_md)
    check("parse_index: عدد الصفوف المقروءة يطابق المُدخَل", len(parsed) == 2, parsed)
    check("parse_index: الحقول الأساسية تُقرأ صحيحة للصفّ الأول",
          parsed and parsed[0]["filename"] == "01-a.md" and parsed[0]["layer"] == "a" and
          parsed[0]["blocs"] == ["arabic", "turkish"] and
          parsed[0]["channels"] == ["الجزيرة", "CNN Türk"] and
          parsed[0]["agreement"] == "cross_source", parsed[0] if parsed else None)
    check("parse_index: عمود event الجديد يُقرأ صحيحًا (طلب المراجعة على Issue #680)",
          parsed and parsed[0]["event"] == "حدث أ" and parsed[1]["event"] == "حدث ب", parsed)
    check("parse_index: مؤشّر التنبيهات المُعلَّم (⚠️ **2**) يُقرأ عددًا صحيحًا",
          parsed and parsed[0]["warnings_count"] == 2, parsed)
    check("parse_index: صفّ بصفر تنبيهات يُقرأ 0",
          len(parsed) > 1 and parsed[1]["warnings_count"] == 0, parsed)

    # ── build_title_card: بلا شبكة إطلاقًا (Pillow محلي فقط)، بلا صورة خبر ولا سطر تقدير بنيويًا ──
    tmp_img = STATE_DIR / "_test_youtube_card.jpg"
    tmp_img.parent.mkdir(parents=True, exist_ok=True)
    built = yp.build_title_card("سؤال تجريبي طويل يفحص التفاف النص على البطاقة؟",
                                "a", ["arabic", "persian"],
                                ["الجزيرة", "Iran International"], cfg, tmp_img)
    check("build_title_card: يبني ملف صورة فعليًا", built.exists(), str(built))
    placeholder_top_left = None
    if built.exists():
        with Image.open(built) as im:
            check("build_title_card: أبعاد البطاقة تطابق image.width/height",
                  im.size == (int(cfg.path("image.width", 1080)),
                             int(cfg.path("image.height", 1080))), str(im.size))
            placeholder_top_left = im.convert("RGB").getpixel((10, 10))
    built.unlink(missing_ok=True)

    # ── build_title_card بصورة تعبيرية (طلب المراجعة على Issue #680): نفس
    # الأبعاد، لكن التركيب مختلف فعليًا -- صورة داكنة مموَّهة (أسود صرف) بدل
    # الخلفية المتدرّجة الفاتحة، فأعلى يسار البطاقة يظلم بوضوح مقارنةً
    # بالقالب النصّي أعلاه (نفس الإحداثيات بالضبط) ──
    fake_photo = Image.new("RGB", (1600, 1200), (0, 0, 0))
    tmp_img2 = STATE_DIR / "_test_youtube_card_photo.jpg"
    built2 = yp.build_title_card("سؤال تجريبي طويل يفحص التفاف النص على البطاقة؟",
                                 "a", ["arabic", "persian"],
                                 ["الجزيرة", "Iran International"], cfg, tmp_img2,
                                 photo=fake_photo)
    check("build_title_card (بصورة): يبني ملف صورة فعليًا", built2.exists(), str(built2))
    if built2.exists() and placeholder_top_left is not None:
        with Image.open(built2) as im2:
            check("build_title_card (بصورة): أبعاد البطاقة تطابق image.width/height أيضًا",
                  im2.size == (int(cfg.path("image.width", 1080)),
                               int(cfg.path("image.height", 1080))), str(im2.size))
            photo_top_left = im2.convert("RGB").getpixel((10, 10))
            check("build_title_card (بصورة): التركيب الفعلي يختلف عن القالب النصّي "
                  "(صورة داكنة مموَّهة أعلى اليسار لا خلفية متدرّجة فاتحة)",
                  sum(photo_top_left) < sum(placeholder_top_left), (photo_top_left, placeholder_top_left))
    built2.unlink(missing_ok=True)

    # ── _photo_search_terms: كلمات مفتاحية عربية عبر evidence.build_query،
    # لا imagesearch.keywords() التي تعيد قائمة فارغة لنص عربي محض ──
    terms = yp._photo_search_terms("هل يتجه الملف نحو تصعيد جديد في المنطقة؟",
                                   "اجتماع طارئ لمجلس الأمن بشأن الملف")
    check("_photo_search_terms: يبني عبارتين، event أولًا ثم headline",
          len(terms) == 2 and "اجتماع" in terms[0] and "الملف" in terms[1], terms)
    check("_photo_search_terms: نصّان فارغان يعيدان قائمة فارغة بلا استثناء",
          yp._photo_search_terms("", "") == [], yp._photo_search_terms("", ""))

    # ── _find_photo: بلا شبكة فعلية -- imagesearch.find_images وimaging.
    # download_image وimaging.face_score كلّها مموَّهة محليًا. المرشَّح الأول
    # "فيه وجه" فيُرفض، الثاني نظيف فيُعتمَد (المحظور: لا صورة لأي شخص) ──
    real_find_images = imagesearch.find_images
    real_download_image = imaging.download_image
    real_face_score = imaging.face_score
    download_calls: list = []

    def fake_find_images(title, cfg, limit=6, terms=None):
        return ["https://example.com/face.jpg", "https://example.com/clean.jpg"]

    def fake_download_image(url, *a, **k):
        download_calls.append(url)
        return Image.new("RGB", (800, 600), (10, 20, 30))

    def fake_face_score(img):
        return 0.5

    imagesearch.find_images = fake_find_images  # type: ignore
    imaging.download_image = fake_download_image  # type: ignore
    try:
        # كل المرشّحين "فيهم وجه" ⇒ None، لا يسقط المقال
        imaging.face_score = lambda img: 0.5  # type: ignore
        no_photo = yp._find_photo("عنوان", "حدث", cfg)
        check("_find_photo: كل المرشّحين مرفوضون (وجه ظاهر) ⇒ None لا انهيار",
              no_photo is None, no_photo)

        # المرشَّح الثاني فقط نظيف ⇒ يُعتمَد هو تحديدًا
        download_calls.clear()

        def face_only_first(img):
            return 0.5 if len(download_calls) == 1 else 0.0

        imaging.face_score = face_only_first  # type: ignore
        photo = yp._find_photo("عنوان", "حدث", cfg)
        check("_find_photo: المرشَّح الأول (فيه وجه) يُرفض، والثاني (نظيف) يُعتمَد",
              photo is not None and download_calls ==
              ["https://example.com/face.jpg", "https://example.com/clean.jpg"], download_calls)
    finally:
        imagesearch.find_images = real_find_images  # type: ignore
        imaging.download_image = real_download_image  # type: ignore
        imaging.face_score = real_face_score  # type: ignore

    # terms فارغة (عنوان وevent كلاهما فارغ فعليًا بعد تصفية كلمات الوقف) ⇒
    # لا نداء بحث إطلاقًا
    search_calls: list = []
    imagesearch.find_images = lambda *a, **k: (search_calls.append(1) or [])  # type: ignore
    try:
        empty_terms_photo = yp._find_photo("", "", cfg)
    finally:
        imagesearch.find_images = real_find_images  # type: ignore
    check("_find_photo: عنوان وevent فارغان ⇒ None بلا أي نداء بحث",
          empty_terms_photo is None and search_calls == [], (empty_terms_photo, search_calls))

    # ── الدرجة المركّبة (Issue #680): compute_score / score_breakdown_text ──
    check("compute_score: عدد القنوات + (كتل-1)×2 + مكافأة الخلاف (cross_source=+3)",
          yp.compute_score(["arabic", "turkish"], ["الجزيرة", "CNN Türk"], "cross_source", cfg)
          == 2 + (2 - 1) * 2 + 3, None)
    check("compute_score: كتلة واحدة (بلا مكافأة كتل) واتفاق (بلا مكافأة)",
          yp.compute_score(["arabic"], ["الجزيرة"], "agreement", cfg) == 1)
    check("compute_score: صدى يعاقب بمكافأة سالبة",
          yp.compute_score(["arabic"], ["الجزيرة", "العربية"], "echo", cfg) == 2 + 0 - 2)
    check("score_breakdown_text: يذكر الرقم وعدد القنوات وعدد الكتل ونوع الخلاف معًا",
          "الدرجة 7" in yp.score_breakdown_text(["arabic", "turkish"],
                                                ["الجزيرة", "CNN Türk"], "cross_source", cfg) and
          "قناتان" in yp.score_breakdown_text(["arabic", "turkish"], ["الجزيرة", "CNN Türk"],
                                              "cross_source", cfg) and
          "كتلتان" in yp.score_breakdown_text(["arabic", "turkish"], ["الجزيرة", "CNN Türk"],
                                              "cross_source", cfg),
          yp.score_breakdown_text(["arabic", "turkish"], ["الجزيرة", "CNN Türk"], "cross_source", cfg))

    # ── build_review_body: سطر الصحة + ترتيب بالدرجة المركّبة تنازليًا + التنبيهات والعناوين ظاهرة ──
    drafts = [
        {"id": "c00000000001", "title": "قضية ج اتفاق؟", "tier": "c", "blocs": ["arabic"],
         "channels": ["الجزيرة"], "agreement": "agreement", "warnings": [],
         "caption": "متن قضية ج", "headlines": ["قضية ج اتفاق؟", "بديل ج ١", "بديل ج ٢"],
         "headline_selected": 0, "score": 1},
        {"id": "a00000000002", "title": "قضية أ خلاف قنوات؟", "tier": "a",
         "blocs": ["arabic", "turkish"], "channels": ["الجزيرة", "CNN Türk"],
         "agreement": "cross_source", "warnings": ["تحذير رقم واحد"],
         "caption": "متن قضية أ", "headlines": ["قضية أ خلاف قنوات؟", "بديل أ ١", "بديل أ ٢"],
         "headline_selected": 0, "score": 7},
        {"id": "a00000000003", "title": "قضية أ خلاف داخلي؟", "tier": "a",
         "blocs": ["arabic", "turkish"], "channels": ["الجزيرة"],
         "agreement": "internal", "warnings": [],
         "caption": "متن قضية أ٢", "headlines": ["قضية أ خلاف داخلي؟", "بديل أ٢ ١", "بديل أ٢ ٢"],
         "headline_selected": 0, "score": 4},
        # طبقة (ب) بثلاث قنوات في كتلة واحدة تتفوّق درجةً على طبقة (أ) أضعف
        # مادةً (a00000000003) رغم كونها طبقة أدنى -- هذا بالضبط العطل الذي
        # يعالجه الـIssue #680: الترتيب بالطبقة وحدها كان يضع كل قضايا (أ)
        # قبل كل قضايا (ب) بصرف النظر عن قوة المادة الفعلية.
        {"id": "b00000000004", "title": "قضية ب ثلاث قنوات؟", "tier": "b", "blocs": ["arabic"],
         "channels": ["الجزيرة", "العربية", "سكاي نيوز عربية"], "agreement": "cross_source",
         "warnings": [], "caption": "متن قضية ب", "headlines": ["قضية ب ثلاث قنوات؟", "ب ١", "ب ٢"],
         "headline_selected": 0, "score": 6},
    ]
    drafts.sort(key=yp._review_sort_key)
    order = [d["id"] for d in drafts]
    check("ترتيب البطاقات: بالدرجة المركّبة تنازليًا (7، 6، 4، 1)",
          order == ["a00000000002", "b00000000004", "a00000000003", "c00000000001"], order)
    check("ترتيب البطاقات: طبقة (ب) الأقوى مادةً تسبق طبقة (أ) الأضعف (العطل الأصلي في الـIssue)",
          order.index("b00000000004") < order.index("a00000000003"), order)

    cfg_pub = load_config()
    cfg_pub["youtube"]["publish"] = {"max_per_run": 3, "spacing_minutes": 40}
    body = yp.build_review_body(drafts, "user/trendnews", "main", cfg_pub)
    check("سطر الصحة: العدد الكلي وتوزيع الطبقات وعدّاد خلاف القنوات والتنبيهات",
          "4 مقالات" in body and "أ=2" in body and "ب=1" in body and "ج=1" in body and
          "خلاف قنوات=2" in body and "تنبيهات=1" in body, body[:400])
    check("Issue المراجعة: معرّفات المسودات الأربع كلها مضمّنة",
          set(review.all_draft_ids(body)) ==
          {"c00000000001", "a00000000002", "a00000000003", "b00000000004"})
    check("Issue المراجعة: نصّ التحذير الفعلي ظاهر كاملًا لا عددًا فقط",
          "تحذير رقم واحد" in body, body)
    check("Issue المراجعة: وسم الاعتماد المخصّص (لا `approved` العام) مذكور صراحةً",
          "youtube-approved" in body, body)
    check("Issue المراجعة: بلا صور إطلاقًا (Issue #680 -- البطاقة تُبنى بعد الوسم فقط)",
          "raw.githubusercontent.com" not in body and "<img" not in body, body)
    check("Issue المراجعة: درجة كل بطاقة ومكوّناتها ظاهرة نصًّا",
          "الدرجة 7" in body and "الدرجة 6" in body and "الدرجة 4" in body and
          "الدرجة 1" in body, body)
    check("Issue المراجعة: العناوين الثلاثة لكل مقال ظاهرة بمربعات اختيار، الأول معلَّم افتراضيًا",
          "- [x] 1. قضية أ خلاف قنوات؟  <!-- hl:a00000000002:0 -->" in body and
          "- [ ] 2. بديل أ ١  <!-- hl:a00000000002:1 -->" in body and
          "- [ ] 3. بديل أ ٢  <!-- hl:a00000000002:2 -->" in body, body)
    # ترتيب الظهور في نص الـIssue نفسه يطابق ترتيب drafts بعد الفرز بالدرجة
    pos_a2 = body.index("a00000000002")
    pos_b4 = body.index("b00000000004")
    pos_a3 = body.index("a00000000003")
    pos_c1 = body.index("c00000000001")
    check("ترتيب الظهور الفعلي في نص الـIssue يطابق الدرجة تنازليًا",
          pos_a2 < pos_b4 < pos_a3 < pos_c1, (pos_a2, pos_b4, pos_a3, pos_c1))

    parsed_choice = yp.parse_headline_choice(body)
    check("parse_headline_choice: الافتراضي (الفهرس 0) مقروء لكل مسودة لم يُغيَّر اختيارها",
          all(parsed_choice.get(d["id"]) == 0 for d in drafts), parsed_choice)
    body_choice = body.replace(
        "- [x] 1. قضية أ خلاف قنوات؟  <!-- hl:a00000000002:0 -->",
        "- [ ] 1. قضية أ خلاف قنوات؟  <!-- hl:a00000000002:0 -->",
    ).replace(
        "- [ ] 2. بديل أ ١  <!-- hl:a00000000002:1 -->",
        "- [x] 2. بديل أ ١  <!-- hl:a00000000002:1 -->",
    )
    check("parse_headline_choice: تبديل العلامة إلى بديل آخر يُقرأ فهرسه الصحيح",
          yp.parse_headline_choice(body_choice)["a00000000002"] == 1,
          yp.parse_headline_choice(body_choice))

    # ── build()/open_review(): المسار الكامل من state/youtube_articles/<date>/
    # إلى مسودات محلية (build) ثم Issue مراجعة (open_review) -- مرحلتان
    # منفصلتان عمدًا (انظر توثيق ذلك أعلى الوحدة). لم تعودا مضطرّتين لتفادي
    # 404 صور raw.githubusercontent.com (Issue #680 -- بلا صور هنا إطلاقًا)،
    # لكن يبقى الأصحّ فتح Issue بعد رفع فعلي للمسودات لا قبله ──
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    date_str = "2026-02-02"
    articles_dir = youtube_article.ARTICLES_DIR / date_str
    shutil.rmtree(articles_dir, ignore_errors=True)
    articles_dir.mkdir(parents=True, exist_ok=True)

    article_headlines = ["هل يتجه الملف نحو تصعيد جديد؟", "الملف يتجه نحو تصعيد بحسب المصادر",
                          "تصعيد مرجّح للملف بحسب متابعين"]
    article_text = (
        "# هل يتجه الملف نحو تصعيد جديد؟\n\nاستهلال قصير عن القضية.\n\n"
        "**التقدير:** مرجّح بقوة أن يتصاعد الموقف، بثقة منخفضة لأن المصدر واحد\n\n"
        "## من قال ماذا\nنص القسم.\n\n## الافتراضات الكامنة\nنص القسم.\n\n"
        "## التفسير البديل\nنص القسم.\n\n## ما يعنيه\nنص القسم.\n\n"
        "## ما لا نعرفه\nنص القسم.\n\n---\n## المصادر\n"
        "الجزيرة — عنوان الفيديو — https://youtube.com/watch?v=xyz (١:٠٠)\n\n"
        "---\n" + yp.WARNINGS_HEADER + "\n"
        "- اسم 'فلان' ورد في نقطة بلا نظير له في الاقتباس الأصلي\n"
        "\n---\n" + youtube_article.HEADLINES_HEADER + "\n"
        + "\n".join(f"{i}. {h}" for i, h in enumerate(article_headlines, start=1)) + "\n"
    )
    (articles_dir / "01-test.md").write_text(article_text, encoding="utf-8")
    saved_index_run = [{"number": 1, "filename": "01-test.md",
                        "headline": "هل يتجه الملف نحو تصعيد جديد؟",
                        "event": "اجتماع طارئ بشأن الملف", "layer": "a",
                        "blocs": ["arabic", "turkish"], "channels": ["الجزيرة", "CNN Türk"],
                        "agreement": "cross_source", "warnings_count": 1}]
    (articles_dir / "index.md").write_text(youtube_article.build_index(saved_index_run),
                                           encoding="utf-8")

    build_result = yp.build(cfg, date_str=date_str)
    check("build(): بُنيت مسودة واحدة من المقال الواحد المُدخَل",
          build_result["stats"]["drafts_built"] == 1, build_result["stats"])
    check("build(): لا يفتح Issue مراجعة في هذه المرحلة",
          "issue" not in build_result, build_result)
    check("build(): caption المسودة المحفوظة خالٍ من قسم التنبيهات والعناوين معًا",
          build_result["drafts"] and yp.WARNINGS_HEADER not in build_result["drafts"][0]["caption"]
          and youtube_article.HEADLINES_HEADER not in build_result["drafts"][0]["caption"],
          build_result["drafts"][0]["caption"] if build_result["drafts"] else None)
    check("build(): حقل warnings المنفصل يحمل التحذير كاملًا",
          build_result["drafts"] and build_result["drafts"][0]["warnings"] ==
          ["اسم 'فلان' ورد في نقطة بلا نظير له في الاقتباس الأصلي"],
          build_result["drafts"][0]["warnings"] if build_result["drafts"] else None)
    check("build(): source_urls يحمل رابط الفيديو بطابعه الزمني",
          build_result["drafts"] and
          "youtube.com/watch?v=xyz" in "".join(build_result["drafts"][0]["source_urls"]),
          build_result["drafts"][0]["source_urls"] if build_result["drafts"] else None)
    check("build(): العناوين الثلاثة المُلحَقة بالمقال وصلت كاملة إلى المسودة، والافتراضي هو الأول",
          build_result["drafts"] and build_result["drafts"][0]["headlines"] == article_headlines
          and build_result["drafts"][0]["headline_selected"] == 0,
          build_result["drafts"][0].get("headlines") if build_result["drafts"] else None)
    check("build(): الدرجة محسوبة فعليًا (لا صفر ثابت كسابقًا)",
          build_result["drafts"] and build_result["drafts"][0]["score"] ==
          yp.compute_score(["arabic", "turkish"], ["الجزيرة", "CNN Türk"], "cross_source", cfg),
          build_result["drafts"][0].get("score") if build_result["drafts"] else None)
    check("build(): event القضية وصل المسودة عبر index.md (طلب المراجعة على Issue #680)",
          build_result["drafts"] and
          build_result["drafts"][0]["event"] == "اجتماع طارئ بشأن الملف",
          build_result["drafts"][0].get("event") if build_result["drafts"] else None)

    loaded = store.load_draft(build_result["drafts"][0]["id"]) if build_result["drafts"] else None
    check("build(): المسودة محفوظة فعليًا بحالة pending وبلا review_issue بعد",
          loaded is not None and loaded[1]["status"] == "pending" and
          not loaded[1].get("review_issue"), loaded[1] if loaded else None)
    check("build(): بلا حقل image إطلاقًا -- البطاقة لم تُبنَ بعد (Issue #680)",
          loaded is not None and "image" not in loaded[1], loaded[1] if loaded else None)
    if loaded:
        run_date_dir = DRAFTS_DIR / date_str
        check("build(): لا أي ملف بطاقة على القرص لهذه المسودة بعد",
              not run_date_dir.exists() or not any(run_date_dir.iterdir()), None)

    # build() بلا مقالات لهذا التاريخ (index.md غائب) لا ينهار
    empty_build = yp.build(cfg, date_str="2026-02-03")
    check("build(): تاريخ بلا state/youtube_articles/<date>/index.md يعيد صفر مسودات بلا استثناء",
          empty_build["drafts"] == [], empty_build)

    # open_review() -- بعد "رفع" الصور (محاكاة: لا رفع فعلي في الاختبار، لكن
    # الملفات موجودة محليًا فعلًا وهذا ما يقرؤه open_review())
    created_issues: list = []
    real_create_issue = review.create_issue

    def fake_create_issue(title, body, labels=None):
        created_issues.append({"title": title, "body": body, "labels": labels})
        return {"number": 999, "html_url": "https://example.com/issues/999"}

    review.create_issue = fake_create_issue  # type: ignore
    try:
        review_result = yp.open_review(cfg)
    finally:
        review.create_issue = real_create_issue  # type: ignore

    check("open_review(): فُتح Issue مراجعة واحد بوسم youtube-review",
          len(created_issues) == 1 and created_issues[0]["labels"] == ["youtube-review"],
          created_issues)
    check("open_review(): المسودة اليتيمة الوحيدة أُدرجت في الـIssue",
          len(review_result["drafts"]) == 1, review_result)
    check("open_review(): نص الـIssue المفتوح بلا صور إطلاقًا (Issue #680)",
          "raw.githubusercontent.com" not in created_issues[0]["body"] and
          "<img" not in created_issues[0]["body"], created_issues[0]["body"])
    check("open_review(): العناوين الثلاثة ظاهرة في نص الـIssue المفتوح فعليًا",
          all(h in created_issues[0]["body"] for h in article_headlines),
          created_issues[0]["body"])

    loaded2 = store.load_draft(build_result["drafts"][0]["id"])
    check("open_review(): review_issue ثُبِّت على المسودة فور فتح الـIssue",
          loaded2 is not None and loaded2[1].get("review_issue") == 999,
          loaded2[1] if loaded2 else None)

    # نداء ثانٍ: المسودة مربوطة بـIssue سابق الآن، فلا تُلتقَط ولا يُفتَح Issue جديد
    second_call = yp.open_review(cfg)
    check("open_review(): مسودة مربوطة بـIssue سابق لا تُلتقَط في نداء ثانٍ",
          second_call["issue"] is None and second_call["drafts"] == [], second_call)

    # ── ensure_title_card: البطاقة تُبنى الآن فقط -- بعد الاعتماد، للمختار
    # فقط (Issue #680)، بالعنوان البديل الثاني لا الافتراضي، كي يثبت أن
    # الاختيار الفعلي هو ما يصل البطاقة والـcaption معًا ──
    card_path, card_draft = store.load_draft(build_result["drafts"][0]["id"])
    card_draft["headline_selected"] = 1
    # imagesearch.find_images مموَّهة هنا لتعيد صفر نتائج -- بحث حقيقي بلا
    # شبكة فعلية، يغطّي بالضبط ما طلبته المراجعة: «إن لم يجد البحث صورة
    # مناسبة، ارجع إلى البطاقة النصية الحالية بدل إسقاط المقال» (Issue #680).
    real_find_images_ctc = imagesearch.find_images
    photo_search_calls: list = []

    def fake_find_images_empty(title, cfg, limit=6, terms=None):
        photo_search_calls.append(terms)
        return []

    imagesearch.find_images = fake_find_images_empty  # type: ignore
    try:
        ok_card = yp.ensure_title_card(card_path, card_draft, cfg)
    finally:
        imagesearch.find_images = real_find_images_ctc  # type: ignore
    check("ensure_title_card: يبني البطاقة بنجاح ويعيد True", ok_card, ok_card)
    check("ensure_title_card: بحثت فعليًا عن صورة تعبيرية بكلمات event/headline",
          photo_search_calls and photo_search_calls[0] and
          "اجتماع" in photo_search_calls[0][0], photo_search_calls)
    check("ensure_title_card: يضبط حقل image على مسار drafts/<تاريخ>/<معرّف>.jpg",
          card_draft.get("image") == f"drafts/{date_str}/{card_draft['id']}.jpg",
          card_draft.get("image"))
    built_img = DRAFTS_DIR / date_str / f"{card_draft['id']}.jpg"
    check("ensure_title_card: ملف البطاقة موجود فعليًا على القرص", built_img.exists(),
          str(built_img))
    check("ensure_title_card: العنوان البديل الثاني (لا الافتراضي) يصل arabic.post_title",
          card_draft["arabic"]["post_title"] == article_headlines[1], card_draft["arabic"])
    check("ensure_title_card: العنوان البديل الثاني يصل السطر الأول من caption أيضًا",
          card_draft["caption"].splitlines()[0] == f"# {article_headlines[1]}",
          card_draft["caption"].splitlines()[0])
    persisted = store.load_draft(card_draft["id"])
    check("ensure_title_card: التحديث محفوظ فعليًا على القرص (image + headline_selected)",
          persisted is not None and persisted[1].get("image") == card_draft["image"] and
          persisted[1].get("headline_selected") == 1, persisted[1] if persisted else None)

    # نداء ثانٍ بعد بناء البطاقة فعليًا: يعيد True فورًا بلا إعادة بناء
    # (الملف موجود مسبقًا -- انظر فحص `existing` في ensure_title_card)
    rebuilt_mtime = built_img.stat().st_mtime
    ok_card2 = yp.ensure_title_card(card_path, card_draft, cfg)
    check("ensure_title_card: نداء ثانٍ لا يعيد البناء إن كانت البطاقة موجودة فعلًا",
          ok_card2 and built_img.stat().st_mtime == rebuilt_mtime, None)

    # ── publish_approved: سقف وتباعد (بلا شبكة، بلا time.sleep فعلي) ──
    # معرّفات على شكل hex فعليًا (اصطلاح المشروع، وID_MARKER في review.py لا
    # يطابق إلا [0-9a-f]+) لا "yt0" التي كانت تسقط بصمت من parse_approved.
    def _hex_id(i: int) -> str:
        return f"{i:012x}"

    yp_drafts = []
    for i in range(5):
        d = {
            "id": _hex_id(i), "status": "pending", "origin": "youtube",
            "arabic": {"post_title": f"مقال {i}", "urgent": False},
            "image": "drafts/x.jpg", "caption": "متن", "source": {},
        }
        store.save_draft(d)
        yp_drafts.append(d)

    fake_body = "\n".join(f"- [x] **{i+1}. مقال {i}**  <!-- draft:{_hex_id(i)} -->"
                          for i in range(5))

    sleep_calls: list = []
    real_sleep = yp.time.sleep
    yp.time.sleep = lambda s: sleep_calls.append(s)

    published_ids: list = []
    real_publish_one = yp.publish.publish_one

    def fake_publish_one(path, draft, cfg):
        published_ids.append(draft["id"])
        store.update_draft(path, status="published")
        return True, f"- ✅ {draft['id']}"

    yp.publish.publish_one = fake_publish_one  # type: ignore

    # ensure_title_card مموَّهة هنا -- هذا الاختبار يغطّي منطق السقف/التباعد
    # في publish_approved تحديدًا، لا بناء البطاقة نفسه (مغطّى فعليًا أعلاه
    # في اختبار ensure_title_card المباشر). يسجّل فقط أي المسودات استُدعيت
    # لها، والاختيار الممرَّر إليها (Issue #680).
    card_calls: list = []
    real_ensure_title_card = yp.ensure_title_card

    def fake_ensure_title_card(path, draft, cfg):
        card_calls.append((draft["id"], draft.get("headline_selected", 0)))
        return True

    yp.ensure_title_card = fake_ensure_title_card  # type: ignore

    comments: list = []
    real_comment = review.comment
    real_fetch_body = review.fetch_issue_body
    real_close = review.close_issue
    review.comment = lambda issue_number, text: comments.append(text)  # type: ignore
    review.fetch_issue_body = lambda issue_number: fake_body  # type: ignore
    closed_issues: list = []
    review.close_issue = lambda issue_number: closed_issues.append(issue_number)  # type: ignore

    cfg_cap = load_config()
    cfg_cap["youtube"]["publish"] = {"max_per_run": 3, "spacing_minutes": 40}
    try:
        code = yp.publish_approved(4242, cfg_cap)
    finally:
        yp.time.sleep = real_sleep
        yp.publish.publish_one = real_publish_one
        yp.ensure_title_card = real_ensure_title_card
        review.comment = real_comment
        review.fetch_issue_body = real_fetch_body
        review.close_issue = real_close

    check("publish_approved: ينتهي بنجاح", code == 0, f"exit={code}")
    check("publish_approved: سقف 3 لكل تشغيلة يُحترَم رغم 5 معتمدة",
          published_ids == [_hex_id(0), _hex_id(1), _hex_id(2)], published_ids)
    check("publish_approved: البطاقة تُبنى فقط للثلاثة المنشورة فعليًا لا الخمسة المعتمدة",
          [c[0] for c in card_calls] == [_hex_id(0), _hex_id(1), _hex_id(2)], card_calls)
    check("publish_approved: بلا اختيار عنوان مُعلَّم في نص الـIssue ⇒ الافتراضي (٠) يُمرَّر",
          all(c[1] == 0 for c in card_calls), card_calls)
    check("publish_approved: فاصل ثابت (40 دقيقة) بين كل منشور والتالي فقط "
          "(اثنان بين ثلاثة منشورات، لا بعد الأخير)",
          sleep_calls == [40 * 60, 40 * 60], sleep_calls)
    check("publish_approved: تعليق يذكر عدد المتبقي بانتظار تشغيلة لاحقة",
          comments and "2 مقالًا" in comments[-1], comments)
    check("publish_approved: الـIssue يبقى مفتوحًا (لم يُغلَق) لبقاء معتمَد لم يُنشر",
          closed_issues == [], closed_issues)

    statuses = {d["id"]: store.load_draft(d["id"])[1]["status"] for d in yp_drafts}
    check("publish_approved: الثلاثة الأولى فقط بحالة published",
          statuses[_hex_id(0)] == "published" and statuses[_hex_id(1)] == "published" and
          statuses[_hex_id(2)] == "published" and statuses[_hex_id(3)] == "pending" and
          statuses[_hex_id(4)] == "pending", statuses)

    # سيناريو ثانٍ: سقف يغطي كل المعتمَد ⇒ الـIssue يُغلَق
    for i in range(5, 8):
        d = {
            "id": _hex_id(i), "status": "pending", "origin": "youtube",
            "arabic": {"post_title": f"مقال {i}", "urgent": False},
            "image": "drafts/x.jpg", "caption": "متن", "source": {},
        }
        store.save_draft(d)

    fake_body2 = "\n".join(f"- [x] **{i-4}. مقال {i}**  <!-- draft:{_hex_id(i)} -->"
                           for i in range(5, 8))
    yp.time.sleep = lambda s: sleep_calls.append(s)
    yp.publish.publish_one = fake_publish_one  # type: ignore
    yp.ensure_title_card = fake_ensure_title_card  # type: ignore
    review.comment = lambda issue_number, text: comments.append(text)  # type: ignore
    review.fetch_issue_body = lambda issue_number: fake_body2  # type: ignore
    review.close_issue = lambda issue_number: closed_issues.append(issue_number)  # type: ignore
    try:
        yp.publish_approved(4243, cfg_cap)
    finally:
        yp.time.sleep = real_sleep
        yp.publish.publish_one = real_publish_one
        yp.ensure_title_card = real_ensure_title_card
        review.comment = real_comment
        review.fetch_issue_body = real_fetch_body
        review.close_issue = real_close

    check("publish_approved: سقف يغطي كل المعتمَد (3 من 3) ⇒ الـIssue يُغلَق",
          closed_issues == [4243], closed_issues)

    # ── لا مُعلَّم ⇒ تعليق تنبيه وإزالة الوسم، بلا نشر ──
    removed_labels: list = []
    real_remove_label = review.remove_label
    review.fetch_issue_body = lambda issue_number: "- [ ] **1. مقال** <!-- draft:aaaaaaaaaaaa -->"  # type: ignore
    review.comment = lambda issue_number, text: comments.append(text)  # type: ignore
    review.remove_label = lambda issue_number, label: removed_labels.append(label)  # type: ignore
    try:
        code_none = yp.publish_approved(4244, cfg_cap)
    finally:
        review.fetch_issue_body = real_fetch_body
        review.comment = real_comment
        review.remove_label = real_remove_label

    check("publish_approved: بلا اعتماد ⇒ ينتهي بنجاح بلا نشر", code_none == 0)
    check("publish_approved: وسم youtube-approved يُزال عند عدم وجود اعتماد",
          removed_labels == ["youtube-approved"], removed_labels)

    # ── إعدادات config.yaml (Issue #676) ──
    check("config: youtube.publish.max_per_run = 3",
          cfg.path("youtube.publish.max_per_run") == 3)
    check("config: youtube.publish.spacing_minutes = 40",
          cfg.path("youtube.publish.spacing_minutes") == 40)
    check("config: youtube.image.badge_text موجود",
          bool(cfg.path("youtube.image.badge_text")))
    check("config: youtube.image.bloc_labels يغطي الكتل الأربع",
          set(cfg.path("youtube.image.bloc_labels", {}).keys()) ==
          {"arabic", "turkish", "persian", "israeli"})
    check("config: youtube.image.use_photo مفعَّل افتراضيًا (طلب المراجعة على Issue #680)",
          cfg.path("youtube.image.use_photo") is True)

    # ── إعدادات config.yaml (Issue #680: الدرجة والعناوين) ──
    check("config: youtube.review.scoring.bloc_bonus = 2",
          cfg.path("youtube.review.scoring.bloc_bonus") == 2)
    check("config: youtube.review.scoring.agreement_bonus يغطي القيم الأربع بالترتيب الصحيح",
          cfg.path("youtube.review.scoring.agreement_bonus") ==
          {"cross_source": 3, "internal": 1, "agreement": 0, "echo": -2})
    check("config: youtube.review.headlines.max_words = 15",
          cfg.path("youtube.review.headlines.max_words") == 15)
    check("config: youtube.review.headlines.max_retries موجود",
          bool(cfg.path("youtube.review.headlines.max_retries")))


def test_no_temperature_param() -> None:
    """حارس ثابت يمنع تكرار Issue #373 (الجولة الحادية عشرة): temperature
    تُرفَض بـ400 ("temperature is deprecated for this model") من نماذج هذا
    المشروع — رُصد الفشل صامتًا لأن except APIError كان يبتلع الرفض ويعيد
    نفس شكل "لا نتيجة" الذي يعيده حكم "لا" شرعي من النموذج. لا نداء
    client.messages.create في src/ يجوز أن يمرّرها مجددًا مهما كان الدافع
    (تخفيض تذبذب أو غيره) بلا التحقق أولًا من قبول الخادم الفعلي لها."""
    import re
    offending = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"\btemperature\s*=", code):
                offending.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    check("لا نداء نموذج في src/ يمرّر temperature (ترفضها نماذج المشروع بـ400)",
          not offending, offending)


def main() -> int:
    install_fakes()
    print("\n── ترميز العناوين والتشابه ──")
    test_tokens_and_similarity()
    print("\n── الجلب والترشيح والترتيب ──")
    test_fetch_and_filter()
    print("\n── استخراج نصوص المقالات ──")
    test_extraction()
    print("\n── تأصيل التحليل ──")
    test_analysis_grounding()
    test_analysis_cleaning()
    test_cluster_members()
    print("\n── المحتوى النافع ──")
    test_useful_bucket()
    print("\n── ضوابط المحتوى الصحي ──")
    test_health_guardrails()
    print("\n── حصص التصنيفات ──")
    test_bucket_quotas()
    print("\n── الضوابط التحريرية ──")
    test_editorial_guardrails()
    print("\n── سرعة الانتشار ──")
    test_velocity()
    test_velocity_in_ranking()
    print("\n── المتابعات ──")
    test_followups()
    test_find_previous_prefers_posted_over_offered()
    print("\n── ذاكرة منع التكرار ──")
    test_dedupe_memory()
    test_dedupe_threshold_separation()
    print("\n── تدهور آمن عند غياب مفتاح API ──")
    test_screen_merge_missing_api_key()
    print("\n── كاشف تكرار النشر التلقائي (الرادار) ──")
    test_radar_gate_check_dedupe()
    test_radar_preselect_fallback()
    print("\n── ترشيح الصور ──")
    test_image_filtering()
    test_image_report()
    print("\n── فكّ روابط Google News الوسيطة ──")
    test_google_news_link_decode()
    print("\n── إشارة Google Trends ──")
    test_trends()
    print("\n── وسم الإعلام الرسمي ──")
    test_state_media()
    print("\n── النص العربي والصور ──")
    test_arabic_shaping()
    print("\n── الأنبوب الكامل ──")
    test_collect_end_to_end()
    print("\n── دورة المراجعة ──")
    test_review_roundtrip()
    print("\n── نقطة التوقف قبل الصياغة (preselect) ──")
    test_preselect_no_spend_before_selection()
    test_preselect_no_duplicate_across_runs()
    test_preselect_finalize()
    test_preselect_empty_selection_no_spend()
    test_preselect_drops_stale_candidates()
    print("\n── مربعان لكل مرشح + ترجمة العناوين (Issue #319) ──")
    test_preselect_two_boxes_now_and_draft_review()
    test_preselect_draft_review_image_swap_works()
    test_preselect_translate_titles()
    test_finalize_format_mismatch_no_silent_fail()
    test_publish_conflicting_labels_no_dispatch()
    print("\n── عطل خارجي عند الصياغة مقابل رفض تحريري (preselect) ──")
    test_writer_classifies_write_errors()
    test_finalize_external_failure_keeps_approved_no_feedback()
    test_finalize_editorial_rejection_removes_approved()
    test_publish_pending_selection_single_dispatch()
    print("\n── الرابط في التعليق الأول ──")
    test_manual_image()
    test_request_search()
    print("\n── التحقق من مقال ملصق ──")
    test_verify()
    print("\n── صياغة مسودة من المؤكَّد وحده (التحقق، المرحلة 2) ──")
    test_verify_draft()
    print("\n── فحص الأصالة: إعفاءا تكرار المصدر ووثيقة أخرى مقروءة ──")
    test_check_originality_signals()
    print("\n── فحص الأصالة: تقليم حدّي بقيد نحوي قبل الرفض ──")
    test_check_originality_trim()
    print("\n── فحص الأصالة: تجريد «الـ»، حد التقليم الأدنى، والجملة الكاملة عند الرفض ──")
    test_check_originality_context()
    print("\n── فحص الأصالة: إرجاع min_core إلى 5 + فجوة ضمائر «وهو» ──")
    test_check_originality_wa_pronoun_and_min_core_revert()
    test_check_originality_quantity()
    print("\n── فحص الأصالة: نواة ربط تسمية (تعليق الموافقة السادس عشر) ──")
    test_check_originality_name_link()
    print("\n── فحص الأصالة: القيمة الرابعة offending لمحاولة صياغة ثانية ──")
    test_check_originality_offending()
    print("\n── محرك البحث والقراءة المشترك (evidence.py) ──")
    test_evidence()
    print("\n── مقال من المصادر ──")
    test_article()
    test_article_statement_kind()
    test_article_merged_statement_gaps()
    test_article_statement_majority()
    test_article_split_statements()
    test_article_split_event_condition()
    test_article_mandatory_query_name()
    test_article_report_kind()
    test_article_generic_source_publisher()
    test_article_unsourced_entities()
    test_evidence_top_candidates()
    test_evidence_relevance_cap()
    test_evidence_relevance_display_matches_score()
    test_article_duplicate_query_reuse()
    test_article_longest_shared_run()
    test_article_reprint_exclusion()
    test_article_reprint_image_fallback()
    test_article_originality_retry()
    test_article_jargon_leak()
    test_article_language_note()
    test_article_mentioned_sources()
    test_article_fetch_failure_gap()
    test_article_source_facts()
    test_reject_boxes_render()
    test_reject_beats_approval()
    test_first_comment()
    print("\n── نشر الدفعة بلا انتظار داخل مهمة urgent ──")
    test_burst_inline_cap_zero_defers_without_sleep()
    test_burst_urgent_still_immediate_with_inline_cap_zero()
    print("\n── الجدولة في أوقات الذروة ──")
    test_scheduling()
    test_due_publishes_one_at_a_time()
    print("\n── سجل القرارات التراكمي (Issue #583، المرحلة الأولى) ──")
    test_decisions()
    print("\n── تحليل الأداء ──")
    test_insights_analysis()
    print("\n── حارس temperature (Issue #373) ──")
    test_no_temperature_param()
    print("\n── سكربت قياس قنوات يوتيوب (Issue #619) ──")
    test_measure_channels()
    print("\n── سكربت اختبار الحجب من Actions (Issue #626) ──")
    test_actions_block_script()
    print("\n── إعداد بروكسي Webshare (Issue #629) ──")
    test_proxy_config()
    print("\n── مسار يوتيوب: الجمع (Issue #631) ──")
    test_youtube_collect()
    print("\n── مسار يوتيوب: الاستخلاص (Issue #631) ──")
    test_youtube_extract()
    print("\n── مسار يوتيوب: العنقدة (Issue #646) ──")
    test_youtube_cluster()
    print("\n── مسار يوتيوب: الكتابة (Issue #646) ──")
    test_youtube_article()
    print("\n── مسار يوتيوب: التوصيل (صورة + مسودة + مراجعة + نشر، Issue #676) ──")
    test_youtube_publish()

    print(f"\n{'═' * 50}\nنجح {len(PASSED)} · فشل {len(FAILED)}")
    if FAILED:
        print("الفاشل: " + "، ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
