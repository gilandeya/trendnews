"""اختبار الأنبوب كاملًا بمحاكاة الشبكة و Claude API (بلا أي طلب خارجي).

    python -m tests.test_pipeline
"""
from __future__ import annotations

import atexit
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

from src import collect, evidence, extract, imaging, review, sources, store, trends, writer  # noqa: E402
from src.config import DRAFTS_DIR, STATE_DIR, load_config  # noqa: E402
from src.rank import cluster, rank, similarity, tokens  # noqa: E402
from src.sources import Article  # noqa: E402

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
        lambda url, timeout=20: Image.open("/tmp/_fixture_photo.jpg").convert("RGB")
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
             "https://c/3": R(thin), "https://d/4": R("", 403)}
    original_get = ex.requests.get
    ex.requests.get = lambda url, **kw: pages.get(url, R("", 404))
    try:

        text = fetch_text("https://a/1")
        check("النص الأساسي مُستخرج", text and "OPEC delegates" in text)
        check("قوائم التنقل مُزالة", text and "Subscribe" not in text)
        check("التذييل والسكربت مُزالان",
              text and "Copyright" not in text and "var a" not in text)
        check("النص القصير مرفوض", fetch_text("https://c/3") is None)
        check("الصفحة المحجوبة مرفوضة", fetch_text("https://d/4") is None)
        check("رابط جوجل الوسيط يُتجاوز",
              fetch_text("https://news.google.com/rss/articles/X") is None)

        members = [{"name": "BBC", "link": "https://a/1"},
                   {"name": "Guardian", "link": "https://b/2"},
                   {"name": "Blocked", "link": "https://d/4"}]
        docs = gather(members, limit=3)
        check("الجلب المتعدد يعيد الناجح فقط", len(docs) == 2, str(len(docs)))
        check("أسماء المصادر محفوظة", {d["name"] for d in docs} == {"BBC", "Guardian"})

        block = format_for_prompt(docs)
        check("الصياغة تعلّم كل مصدر باسمه",
              "المصدر 1: BBC" in block and "المصدر 2: Guardian" in block)
        check("قائمة فارغة تعطي نصًا فارغًا", format_for_prompt([]) == "")
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
    radar.gather_texts = lambda members, limit=2: [{"name": "Reuters", "text": "..."}]
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
    query = verify.build_query(long_claim)
    check("الاستعلام المولَّد لا يتجاوز 5 كلمات مفتاحية",
          1 <= len(query.split()) <= 5)
    check("الاستعلام المولَّد أقصر بوضوح من الجملة الأصلية",
          len(query) < len(long_claim))
    check("الرقم المميز (السنة) يدخل الاستعلام", "2026" in query.split())
    check("سقف الكلمات قابل للتحكم عبر max_words",
          len(verify.build_query(long_claim, max_words=2).split()) <= 2)
    check("نص فارغ لا ينهار بناء الاستعلام", verify.build_query("") == "")

    # عطل ثانٍ رُصد فعليًا في الإنتاج (Issue #132 تعليق لاحق): استعلامات
    # ركيكة مثل 'بلومبرغ لتقرير للتاكد محتواه اليه' — كلمات حشو طويلة
    # تُزاحم أسماء الأعلام، وتطبيع الهمزات يفسد الإملاء الحرفي
    check("اسم العلم (بلومبرغ) يدخل الاستعلام لا كلمات الحشو الأطول",
          "بلومبرغ" in query.split())
    check("كلمات الحشو والإسناد لا تدخل الاستعلام رغم طولها",
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
    extract.gather = lambda members, limit=2: []  # كل محاولات استخراج النص الكامل تفشل
    docs, basis = verify.gather_evidence(fallback_articles, cfg)
    check("احتياط العناوين يعمل حين يتعذّر النص الكامل رغم وجود نتائج",
          basis == verify.EVIDENCE_HEADLINES_ONLY)
    check("كل وثيقة احتياط معلَّمة from_text=False",
          bool(docs) and all(d["from_text"] is False for d in docs))
    check("نص الاحتياط يحوي العنوان الفعلي (لا فراغًا)",
          any("1985" in d["text"] for d in docs))

    extract.gather = lambda members, limit=2: [
        {"name": "Reuters", "text": "نص المقال الكامل الحقيقي المستخرج"}]
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
        return [{"name": m["name"], "text": f"نص {m['name']}"} for m in members[:limit]]

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
        return [{"name": m["name"], "text": f"نص {m['name']}"} for m in members[:limit]]

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
            return []
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
        return [{"name": m["name"], "text": f"نص {m['name']}"} for m in members[:limit]]

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
    # سبب التراجع الفعلي المُبلَّغ عنه — Issue #132 تعليق لاحق ثانٍ)
    trusted_irrelevant = [
        Article(title=f"خبر عام غير متعلق رقم {i}", link=f"https://trusted{i}.example/1",
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
        return []

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
    query = evidence.build_query(long_claim)
    check("evidence.build_query: لا يتجاوز 5 كلمات مفتاحية",
          1 <= len(query.split()) <= 5)
    check("evidence.build_query: الرقم المميز يدخل الاستعلام", "2026" in query.split())
    check("evidence.build_query: اسم العلم يدخل الاستعلام لا كلمات الحشو الأطول",
          "بلومبرغ" in query.split() and
          not any(w in query for w in ("لتقرير", "وفقا", "بأكمله")))
    check("evidence.build_query: نص فارغ لا ينهار", evidence.build_query("") == "")

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
    extract.gather = lambda members, limit=2: []  # كل محاولات النص الكامل تفشل
    docs_h, basis_h = evidence.gather_evidence(fallback_articles, cfg)
    check("evidence.gather_evidence: احتياط العناوين حين يتعذّر النص الكامل",
          basis_h == evidence.EVIDENCE_HEADLINES_ONLY)
    check("evidence.gather_evidence: وثيقة الاحتياط معلَّمة from_text=False",
          bool(docs_h) and docs_h[0]["from_text"] is False)

    extract.gather = lambda members, limit=2: [
        {"name": "Reuters", "text": "نص كامل مستخرج فعليًا"}]
    docs_f, basis_f = evidence.gather_evidence(fallback_articles, cfg)
    check("evidence.gather_evidence: النص الكامل يُفضَّل حين يتوفر لا الاحتياط",
          basis_f == evidence.EVIDENCE_FULL_TEXT and docs_f[0]["from_text"] is True)
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
        evidence.search("زلزال هرات", cfg, 7)
    finally:
        evidence.fetch_source = real_fetch_source
        evidence.rank = real_rank
    check("evidence.search: الدمج الدلالي معطَّل صراحة (merge_cfg=None) — تعدد "
          "المصادر المستقلة هو المقياس هنا لا تمثيل الحدث بخبر واحد",
          seen_merge_cfg == [None], str(seen_merge_cfg))
    check("evidence.search: keep_google_links=True دومًا — نتائجه كلها من "
          "Google News فتُحلّ لاحقًا في gather_evidence لا تُستبعد خامًا",
          seen_keep_google == [True], str(seen_keep_google))


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

    def _fake_support(fact_text, docs, cfg):
        return SUPPORT_MAP.get(fact_text, [])

    def _fake_answer(question_text, docs, cfg):
        return ANSWER_MAP.get(question_text)

    def _fake_choose_question(grounded, cfg, retries=2):
        seen_question_calls.append([f["text"] for f in grounded])
        return "سؤال اختبار؟", ""

    def _fake_draft_article(grounded, opinions, question, cfg, retries=3):
        seen_draft_calls.append({"grounded": [f["text"] for f in grounded],
                                 "opinions": [o["text"] for o in opinions],
                                 "question": question})
        return ({"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
                "image_headline": "عنوان الصورة", "post_title": question,
                "post_body": "متن الاختبار يجيب عن السؤال بالوقائع المسندة كاملة.",
                "hashtags": ["اختبار"]}, "")

    evidence.search = _fake_search
    evidence.gather_evidence = _fake_gather_evidence
    article._support_sources = _fake_support
    article._ask_answer_model = _fake_answer
    article._choose_question = _fake_choose_question
    article._draft_article = _fake_draft_article
    article.find_images = lambda title, cfg: []

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
    check("7) امتناع بلاغ بما بُحث لا مقال ركيك — لا نداء لاختيار السؤال أصلًا "
          "(البوابة العددية تسبق اختياره)",
          len(seen_question_calls) == question_calls_before)
    check("5) سؤال الموجز بُحث عنه فعلًا (لا حصيلة فشل بلا محاولة) ولم يُجب عنه "
          "بسبب محدد يبقى في القسم",
          any(u["text"] == "سؤال لم يُجب عنه الموجز؟" and u["reason"]
              for u in out7["unanswered"]))
    check("4) trail يُمرَّر إلى outcome ويشمل استعلام حلقة الوقائع العادية "
          "واستعلام حلقة الأسئلة معًا، كل عنصر منه بمصادره وحصيلته",
          any(t["stage"] == "واقعة" for t in out7["trail"]) and
          any(t["stage"] == "سؤال" for t in out7["trail"]) and
          all({"stage", "query", "basis", "sources", "outcome"} <= set(t.keys())
              for t in out7["trail"]))
    report7 = article.build_report(out7)
    check("4) التقرير يعرض سجلّ trail الكامل", "سجلّ البحث الكامل" in report7)

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
    out2 = article._write_article("موجز اختبار القاعدة 2", 2, cfg)
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
    check("3) نافذة الاستخلاص الرخيصة (البديل ج) تقتصر على مطلع النص لا كامله",
          article._narrow_for_context("س" * 900, max_chars=400) == "س" * 400)

    check("2) بوابة الاتساق تقبل تسمية تذكر كيان الواقعة الأصلية في نص التسمية نفسه",
          article._naming_consistent(
              "حكم إعدام بحق عاطف نجيب في قضية حمزة الخطيب", ["حمزة الخطيب"], []))
    check("2) بوابة الاتساق تقبل تسمية لا تذكر الكيان في نصها لكن وثائقها تذكره",
          article._naming_consistent(
              "حكم إعدام غيابي بحق ثلاثة متهمين", ["حمزة الخطيب"],
              [{"name": "م", "text": "شمل الحكم قضية حمزة الخطيب في درعا"}]))
    check("2) بوابة الاتساق ترفض تسمية لا تذكر الكيان لا في نصها ولا في وثائقها "
          "— فشل «لبّاد» في التشخيص المعتمَد بالضبط",
          not article._naming_consistent(
              "تداول فيديو لفتى آخر لا صلة له بالحدث", ["حمزة الخطيب"],
              [{"name": "م", "text": "خبر عن تداول فيديو لمراهق آخر لا صلة له"}]))

    # ── القاعدة 6: برومبت مستقل — لا يمسّ writer.SYSTEM_PROMPT ولا يستعمل آلياته ──
    check("6) برومبت صياغة المقال مستقل تمامًا عن writer.SYSTEM_PROMPT",
          article.DRAFT_SYSTEM_TEMPLATE != writer.SYSTEM_PROMPT and
          writer.SYSTEM_PROMPT not in article.DRAFT_SYSTEM_TEMPLATE)
    check("6) أداة الصياغة مستقلة عن أداة writer.py (اسم أداة مختلف)",
          article.ARTICLE_POST_SCHEMA["name"] != writer.POST_SCHEMA["name"])
    check("6) نداء الشبكة مستقل عن writer._call_model (الذي يُحمِّل "
          "writer.SYSTEM_PROMPT داخليًا بلا معامل يسمح باستبداله)",
          article._call_draft_model is not writer._call_model)

    # ── القاعدة 5 + تسمية الحدث المبهم، مقلوبة الترتيب (تعليق الموافقة
    # الثاني، البنود 1/2/3/4/7): موجز يصف أثر حدث بلا تسميته ──
    naming_search_calls: list = []

    def _naming_search(query, cfg, days, unrestricted=False):
        naming_search_calls.append((query, unrestricted))
        return [object()]

    def _naming_gather(articles, cfg, claim_text=""):
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
                 "text": ("صدر حكم إعدام غيابي بحق بشار الأسد وماهر الأسد وعاطف نجيب، "
                         "وشملت اللائحة قضية حمزة الخطيب في درعا")},
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
              for q, unrestricted in naming_search_calls[first_unrestricted + 1:]))
    check("بحث بالوصف المبهم حرفيًا (أعاد قصة) لا يقع إطلاقًا",
          not any("أعاد قصة" in q for q, _ in naming_search_calls))
    check("المقال يُنتَج فعلًا بعد تسمية الحدث ومروره ببوابة السند",
          out_naming["produced"] is True, out_naming.get("reason"))
    check("4) trail يشمل مراحل التسمية الثلاث (مباشر/مرجعي/سياق) مع حصيلة كل استعلام",
          {"مباشر", "مرجعي", "سياق"} <= {t["stage"] for t in out_naming["trail"]})
    check("7) بعد تسمية الحدث، الصلة بكيان الموجز الأصلي تُصاغ سؤالًا ويُبحث "
          "بدل افتراضها بديهية",
          any(q["text"].startswith("ما الصلة بين") for q in out_naming["unanswered"]))

    evidence.search = _fake_search
    evidence.gather_evidence = _fake_gather_evidence
    article._ask_naming_model = real_ask_naming_model
    article._ask_context_model = real_ask_context_model

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

    def _copying_draft(grounded, opinions, question, cfg, retries=3):
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
    print("\n── محرك البحث والقراءة المشترك (evidence.py) ──")
    test_evidence()
    print("\n── مقال من المصادر ──")
    test_article()
    test_reject_boxes_render()
    test_reject_beats_approval()
    test_first_comment()
    print("\n── نشر الدفعة بلا انتظار داخل مهمة urgent ──")
    test_burst_inline_cap_zero_defers_without_sleep()
    test_burst_urgent_still_immediate_with_inline_cap_zero()
    print("\n── الجدولة في أوقات الذروة ──")
    test_scheduling()
    test_due_publishes_one_at_a_time()
    print("\n── تحليل الأداء ──")
    test_insights_analysis()

    print(f"\n{'═' * 50}\nنجح {len(PASSED)} · فشل {len(FAILED)}")
    if FAILED:
        print("الفاشل: " + "، ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
