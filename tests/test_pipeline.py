"""اختبار الأنبوب كاملًا بمحاكاة الشبكة و Claude API (بلا أي طلب خارجي).

    python -m tests.test_pipeline
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import collect, extract, imaging, review, sources, store, trends, writer  # noqa: E402
from src.config import DRAFTS_DIR, STATE_DIR, load_config  # noqa: E402
from src.rank import cluster, rank, similarity, tokens  # noqa: E402
from src.sources import Article  # noqa: E402

PASSED, FAILED = [], []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    mark = "✅" if condition else "❌"
    print(f"{mark} {name}" + (f"  → {detail}" if detail and not condition else ""))


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

    for cat in ("مشاهير", "غرائب", "فيروسي", "ترفيه", "رياضة"):
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
    check("حصة useful محمية في الدفعة",
          cfg_raw["selection"]["quotas"].get("useful", 0) >= 2,
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


def test_collect_end_to_end() -> None:
    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    sys.argv = ["collect", "--limit", "2"]
    code = collect.main()
    check("collect انتهى بنجاح", code == 0, f"exit={code}")

    pending = store.pending_drafts()
    check("أُنشئت مسودتان", len(pending) == 2, f"{len(pending)}")
    if not pending:
        return

    _, draft = pending[0]
    for field in ("id", "status", "score", "source", "arabic", "caption", "image"):
        check(f"حقل '{field}' موجود في المسودة", field in draft)

    img = ROOT / draft["image"]
    check("ملف الصورة أُنشئ فعلًا", img.exists(), str(img))
    if img.exists():
        with Image.open(img) as im:
            check("أبعاد الصورة 1080×1080", im.size == (1080, 1080), str(im.size))

    caption = draft["caption"]
    check("التعليق يحوي هاشتاقات", "#" in caption)
    # المصادر انتقلت إلى تذييل الصورة والتعليق الأول — لا مكان لها في المتن
    check("المتن بلا سطر مصادر", "المصدر:" not in caption)
    check("المصادر محفوظة في المسودة",
          bool((draft.get("source") or {}).get("publishers")))
    check("التعليق ليس فارغًا", len(caption) > 80, f"{len(caption)} حرفًا")
    check("سجل التكرار حُفظ", (STATE_DIR / "history.json").exists())

    # تشغيل ثانٍ: يجب ألا يعيد إنتاج نفس الأخبار
    sys.argv = ["collect", "--limit", "2"]
    collect.main()
    check("التشغيل الثاني لم يكرر نفس الأخبار",
          len(store.pending_drafts()) == 2, f"{len(store.pending_drafts())}")


def test_review_roundtrip() -> None:
    drafts = [d for _, d in store.pending_drafts()]
    if not drafts:
        check("توجد مسودات لبناء الـ Issue", False)
        return

    body = review.build_issue_body(drafts, "user/trendnews", "main")
    ids = review.all_draft_ids(body)
    check("معرفات المسودات مضمّنة في نص الـ Issue",
          len(ids) == len(drafts), f"{len(ids)} من {len(drafts)}")
    check("الصور معروضة برابط raw", "raw.githubusercontent.com" in body)
    check("مربعات الاختيار فارغة ابتداءً", review.parse_approved(body) == [])

    # محاكاة تعليم المستخدم على المسودة الأولى
    marked = body.replace(f"- [ ] **1.", f"- [x] **1.", 1)
    approved = review.parse_approved(marked)
    check("قراءة العلامة ✔️ تعمل", approved == [drafts[0]["id"]], str(approved))

    marked_all = marked.replace("- [ ] **2.", "- [x] **2.", 1)
    check("اعتماد متعدد يعمل", len(review.parse_approved(marked_all)) == min(2, len(drafts)))


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

    # التصنيف بكود لا بالنموذج — يجب أن يكون حتميًا وقابلًا للاختبار وحده
    check("تصنيف: مصدران مستقلان فأكثر = مؤكدة",
          verify.classify_fact(["BBC", "Reuters"], [], 2) == verify.STATUS_CONFIRMED)
    check("تصنيف: مصدر واحد",
          verify.classify_fact(["BBC"], [], 2) == verify.STATUS_SINGLE)
    check("تصنيف: لا مصدر",
          verify.classify_fact([], [], 2) == verify.STATUS_NONE)
    check("تصنيف: يخالفها مصدر رغم مصدر مؤيد واحد",
          verify.classify_fact(["BBC"], ["Reuters"], 2) == verify.STATUS_CONTRADICTED)
    check("تكرار الاسم نفسه لا يرفع العدد فوق العتبة",
          verify.classify_fact(["BBC", "BBC"], [], 2) == verify.STATUS_SINGLE)

    # لا اسم مصدر مختلَق يدخل التقرير — حتى لو ادّعاه ردّ النموذج
    docs = [{"name": "BBC", "text": "x"}, {"name": "Reuters", "text": "y"}]
    check("يُقبل اسم مصدر مُعطى فعلًا", verify._known_only(["BBC"], docs) == ["BBC"])
    check("يُرفض اسم مصدر لم يُعطَ في النصوص",
          verify._known_only(["BBC", "مصدر مختلق"], docs) == ["BBC"])
    check("لا تكرار في القائمة المفلترة",
          verify._known_only(["BBC", "BBC"], docs) == ["BBC"])

    # ضوابط البرومبت: نفس قاعدة عدم الاستعانة بمعرفة النموذج الخاصة (writer.py)
    check("استخراج البنية لا ينقل جملة حرفية من المقال",
          "لا تنقل جملة من المقال حرفيًا" in verify.EXTRACT_SYSTEM)
    check("الحكم على الوقائع يمنع الاستعانة بمعرفة سابقة",
          "لا تستخدم معرفتك الخاصة" in verify.JUDGE_FACT_SYSTEM)
    check("الإجابة عن الأسئلة تشترط النسبة لا الحقيقة المطلقة",
          "انسب الجواب لمن قاله" in verify.JUDGE_QUESTION_SYSTEM)
    check("تصنيفات الادعاء الثلاثة متاحة",
          set(verify.CLAIM_KINDS) == {"واقعة", "رأي", "تنبؤ"})

    # تطبيع شكل رد النموذج (Issue #134: claims وصلت كقائمة نصوص لا قواميس
    # فانهار verify.py:344 بـ AttributeError) — لا يُفترض شكل بلا تحقق
    check("نص مجرد يصير قاموس ادّعاء بحقلين افتراضيين",
          verify.normalize_claim("ادّعاء بلا شكل") ==
          {"text": "ادّعاء بلا شكل", "kind": "واقعة"})
    check("قاموس ناقص حقل kind يُملأ بقيمة افتراضية",
          verify.normalize_claim({"text": "ادّعاء"}) ==
          {"text": "ادّعاء", "kind": "واقعة"})
    check("قاموس بقيمة kind غير معروفة يُصحَّح لا يُرفَض",
          verify.normalize_claim({"text": "ادّعاء", "kind": "شيء غريب"}) ==
          {"text": "ادّعاء", "kind": "واقعة"})
    check("عنصر بلا نص قابل للاستخراج (رقم مثلًا) يُستبعد بلا انهيار",
          verify.normalize_claim(42) is None)
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
          [{"text": "ادّعاء", "kind": "واقعة"}])
    check("normalize_questions تقبل نص JSON صالحًا لمصفوفة أسئلة",
          verify.normalize_questions('["سؤال؟"]') == ["سؤال؟"])
    check("نص لا يبدأ بـ [ أو { لا يُحاول تحليله كـ JSON",
          verify._coerce_json_string("نص عادي") == "نص عادي")
    check("نص يبدأ بـ [ لكنه JSON غير صالح يُعاد كما وصل بلا انهيار",
          verify._coerce_json_string("[غير صالح") == "[غير صالح")

    # مقال بلا أي مصدر يؤكد وقائعه ← حكم سلبي واضح لا تقرير مبهم
    verify.extract_claims = lambda text, cfg, retries=3: ({
        "topic": "مقال بلا سند",
        "claims": [{"text": "زعم لا سند له", "kind": "واقعة"},
                   {"text": "رأي كاتب المقال", "kind": "رأي"}],
        "questions": ["سؤال بلا جواب في المصادر؟"],
    }, None)
    verify.search = lambda query, cfg, days: []
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
    verify.gather_evidence = lambda articles, cfg: (
        [{"name": "BBC", "text": "t", "from_text": True}], verify.EVIDENCE_FULL_TEXT)
    verify.judge_fact = lambda claim, docs, cfg: {
        "supporting": ["BBC", "Reuters"], "contradicting": []}
    verify.judge_question = lambda q, docs, cfg: {
        "answered": True, "answer": "نعم حدث كذلك", "source": "BBC"}
    verify.search = lambda query, cfg, days: [object()]  # غير فارغة لتفعيل القراءة

    result2 = verify.verify_article("نص مقال آخر", cfg)
    check("واقعة مؤكدة بمصدرين ← الحكم نعم", result2["verdict"] is True)
    check("سبب الحكم الإيجابي يذكر العدد المؤكَّد", "مؤكَّدة" in result2["verdict_reason"])
    check("أساس الأدلة نص كامل حين ينجح الاستخراج",
          result2["facts"][0]["evidence_basis"] == verify.EVIDENCE_FULL_TEXT)
    report2 = verify.build_report(result2)
    check("التقرير الإيجابي يحمل ✅", "✅" in report2 and "**نعم**" in report2)
    check("عمود الأدلة يظهر في التقرير", "الأدلة" in report2)

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

    def _spy_search(query, cfg, days):
        seen_queries.append(query)
        return []

    verify.search = _spy_search
    verify.verify_article("نص", cfg)
    check("استعلامات البحث الفعلية قصيرة كلها لا الجملة كاملة",
          len(seen_queries) == 2 and all(len(q.split()) <= 5 for q in seen_queries))
    check("لا استعلام فعلي يساوي نص الادّعاء أو السؤال الكامل",
          long_claim not in seen_queries and long_question not in seen_queries)

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
    verify.search = lambda query, cfg, days: []

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

    def _boom(query, cfg, days):
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
    real_rank = verify.rank

    def _spy_rank(articles, selection, merge_cfg=None):
        seen_merge_cfg.append(merge_cfg)
        return real_rank(articles, selection, merge_cfg=merge_cfg)

    one = Article(title="زلزال قوي يضرب هرات", link="https://x/1", summary="",
                  source_name="s", region="global", weight=1.0,
                  published=datetime.now(timezone.utc), publisher="s")
    real_fetch_source = verify.fetch_source
    verify.rank = _spy_rank
    verify.fetch_source = lambda src, max_age_hours: [one]
    verify.search = real_search  # الاختبار السابق تركها على _boom
    try:
        verify.search("زلزال هرات", cfg, 7)
    finally:
        verify.fetch_source = real_fetch_source
        verify.rank = real_rank
    check("الدمج الدلالي معطَّل صراحة في بحث التحقق (merge_cfg=None)",
          seen_merge_cfg == [None], str(seen_merge_cfg))

    # gather_evidence يجب أن يوسّع الممثّل الواحد (بعد تجميع rank.cluster
    # اللفظي، الذي يعمل دومًا داخل rank()) إلى ناشريه الفعليين المحفوظين في
    # cluster_members — لا أن يكتفي برابط/اسم الممثّل وحده
    rep = Article(
        title="أمريكا توقف استيراد النفط السعودي للمرة الأولى منذ 1985",
        link="https://news.google.com/rss/articles/xyz", summary="",
        source_name="Bloomberg", region="global", weight=1.5,
        published=datetime.now(timezone.utc), publisher="Bloomberg")
    rep.cluster_members = [
        {"name": "Bloomberg", "link": "https://bloomberg.example.com/a"},
        {"name": "Al Jazeera", "link": "https://aljazeera.example.com/b"},
        {"name": "Al Arabiya", "link": "https://alarabiya.example.com/c"},
    ]

    real_resolve = verify.resolve_final_url
    verify.resolve_final_url = lambda link, timeout=12: "https://bloomberg.example.com/self"
    verify.gather_evidence = real_gather_evidence  # اختبار سابق تركها على lambda ثابتة

    def _fake_gather_multi(members, limit=2):
        return [{"name": m["name"], "text": f"نص {m['name']}"} for m in members[:limit]]

    extract.gather = _fake_gather_multi
    try:
        docs3, basis3 = verify.gather_evidence([rep], cfg)
    finally:
        extract.gather = real_extract_gather
        verify.resolve_final_url = real_resolve

    names3 = {d["name"] for d in docs3}
    check("الممثّل الواحد يتوسّع إلى ناشريه الثلاثة المستقلين لا ناشره وحده",
          names3 == {"Bloomberg", "Al Jazeera", "Al Arabiya"}, str(names3))
    check("أساس الأدلة نص كامل بعد التوسيع", basis3 == verify.EVIDENCE_FULL_TEXT)

    # عدّ المصادر بالناشر لا بالموضوع/المجموعة: ثلاثة ناشرين لواقعة واحدة
    # تُحكم "مؤكَّدة" لا "مصدر واحد" رغم أنهم اندمجوا في مجموعة واحدة
    min_confirm = int((cfg.get("verify", {}) or {}).get("min_confirm_sources", 2))
    status3 = verify.classify_fact(list(names3), [], min_confirm)
    check("واقعة بثلاثة ناشرين مستقلين ← مؤكَّدة لا مصدر واحد",
          status3 == verify.STATUS_CONFIRMED)


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
    print("\n── ذاكرة منع التكرار ──")
    test_dedupe_memory()
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
    print("\n── الرابط في التعليق الأول ──")
    test_manual_image()
    test_request_search()
    print("\n── التحقق من مقال ملصق ──")
    test_verify()
    test_reject_boxes_render()
    test_reject_beats_approval()
    test_first_comment()
    print("\n── الجدولة في أوقات الذروة ──")
    test_scheduling()
    print("\n── تحليل الأداء ──")
    test_insights_analysis()

    print(f"\n{'═' * 50}\nنجح {len(PASSED)} · فشل {len(FAILED)}")
    if FAILED:
        print("الفاشل: " + "، ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
