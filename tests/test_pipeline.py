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

from src import collect, imaging, review, sources, store, writer  # noqa: E402
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
  <link>https://example.com/oil-opec</link>
  <description>&lt;p&gt;Crude jumped more than 6% on Tuesday.&lt;/p&gt;</description>
  <pubDate>{recent}</pubDate>
  <media:content url="https://example.com/oil.jpg" width="1200"/>
</item>
<item>
  <title>OPEC+ surprise production cut sends oil prices higher - BBC</title>
  <link>https://example.com/opec-bbc</link>
  <description>Markets reacted sharply.</description>
  <pubDate>{recent}</pubDate>
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
  <description>&lt;img src="https://example.com/quake.jpg"/&gt; No tsunami warning issued.</description>
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
            "urgent": True, "category": "اقتصاد",
            "image_headline": "أوبك بلس تفاجئ الأسواق بخفض الإنتاج وأسعار النفط ترتفع 6%",
            "post_title": "أوبك بلس تخفض الإنتاج والنفط يرتفع 6%",
            "post_body": "أعلنت مجموعة أوبك بلس خفضًا مفاجئًا في إنتاج النفط، ما دفع "
                         "أسعار الخام إلى الارتفاع بأكثر من ستة في المئة. يهم القرار "
                         "الأسواق العربية المرتبطة بأسعار الطاقة.",
            "hashtags": ["أوبك", "النفط", "الاقتصاد_العالمي", "أسعار_الطاقة"],
        },
        "quake": {
            "urgent": False, "category": "عالم",
            "image_headline": "زلزال بقوة 6.1 درجة يضرب غرب اليابان دون تحذير من تسونامي",
            "post_title": "زلزال بقوة 6.1 درجة يضرب غرب اليابان",
            "post_body": "ضرب زلزال بقوة 6.1 درجة غرب اليابان، ولم تصدر السلطات تحذيرًا "
                         "من أمواج تسونامي. لم ترد أنباء عن إصابات حتى الآن.",
            "hashtags": ["اليابان", "زلزال", "أخبار_عاجلة", "آسيا"],
        },
    }

    def fake_write(article, cfg, retries=3):
        key = "oil" if "oil" in article.link or "opec" in article.link else "quake"
        return dict(canned[key])

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
    check("استُخرجت صورة media:content",
          any(a.image_url == "https://example.com/oil.jpg" for a in arts))
    check("استُخرجت صورة من وسم img",
          any(a.image_url == "https://example.com/quake.jpg" for a in arts))

    ranked = rank(arts, cfg["selection"])
    ranked_titles = [a.title for a in ranked]
    check("حُجب خبر الأبراج (blocklist)",
          not any("horoscope" in t.lower() for t in ranked_titles))
    check("دُمج خبر أوبك من مصدرين",
          any(len(a.cluster_sources) >= 2 for a in ranked),
          str([a.cluster_sources for a in ranked]))
    check("الترتيب تنازلي حسب المؤشر",
          all(ranked[i].score >= ranked[i + 1].score for i in range(len(ranked) - 1)))


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
            check("أبعاد الصورة 1200×630", im.size == (1200, 630), str(im.size))

    caption = draft["caption"]
    check("التعليق يحوي هاشتاقات", "#" in caption)
    check("التعليق يحوي المصدر", "المصدر:" in caption)
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
    shaped = imaging.shape("مرحبا بالعالم")
    check("تشكيل الحروف يغيّر النص", shaped != "مرحبا بالعالم")
    check("طول النص المُشكّل معقول", 8 <= len(shaped) <= 20, str(len(shaped)))

    from PIL import ImageDraw as _D
    canvas = Image.new("RGB", (10, 10))
    draw = _D.Draw(canvas)
    font = imaging.load_font(load_config()["image"]["font_bold"], 40)
    long_text = "هذا عنوان طويل جدًا يجب أن يُقسّم على عدة أسطر داخل الصورة بشكل صحيح"
    lines = imaging.wrap_arabic(draw, long_text, font, 600)
    check("تقسيم الأسطر يعمل", len(lines) >= 2, f"{len(lines)} سطر")
    check("لا كلمة مفقودة بعد التقسيم",
          " ".join(lines).split() == long_text.split())


def main() -> int:
    install_fakes()
    print("\n── ترميز العناوين والتشابه ──")
    test_tokens_and_similarity()
    print("\n── الجلب والترشيح والترتيب ──")
    test_fetch_and_filter()
    print("\n── ذاكرة منع التكرار ──")
    test_dedupe_memory()
    print("\n── النص العربي والصور ──")
    test_arabic_shaping()
    print("\n── الأنبوب الكامل ──")
    test_collect_end_to_end()
    print("\n── دورة المراجعة ──")
    test_review_roundtrip()

    print(f"\n{'═' * 50}\nنجح {len(PASSED)} · فشل {len(FAILED)}")
    if FAILED:
        print("الفاشل: " + "، ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
