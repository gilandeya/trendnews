"""اختبارات مجال «الجمع والترتيب والفرز والرادار» — تجزّأت من tests/test_pipeline.py (Issue #883): جلب RSS وتنقيته/تجميعه، الترتيب (rank.py)، الفرز الرخيص (screen.py)، استخراج نصوص المقالات (extract.py)، سرعة الانتشار (velocity.py)، Google Trends، الرادار (radar.py)، ترشيح الصور وبناء البطاقة، والأنبوب الكامل من طرف إلى طرف. المساعدات المشتركة (check، الفاكات، install_fakes) في tests/helpers.py."""
from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image, ImageDraw

from tests.helpers import (
    check,
    install_fakes,
    RSS_FIXTURE,
    ROOT,
    _TMP_DATA_DIR,
    _REAL_DOWNLOAD_IMAGE,
    collect,
    extract,
    facebook,
    headlines,
    imagesearch,
    imaging,
    review,
    sources,
    store,
    writer,
    DRAFTS_DIR,
    STATE_DIR,
    load_config,
    cluster,
    rank,
    similarity,
    tokens,
    Article,
)


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
    check("build_post_image: composite يُسجَّل False حين لا تركيب صورتين (مرشَّح واحد ناجح فقط، Issue #752)",
          shot.get("composite") is False, shot)

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
    check("build_post_image: composite يُسجَّل False لصورة مصدر واحدة بلا صورة ثانية للتركيب",
          shot2.get("composite") is False, shot2)

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

def test_card_second_badge_by_origin() -> None:
    """Issue #758: خانة ملصق ثانية واحدة على البطاقة، محكومة بجدول
    config.yaml: cards عبر origin — لا بحكم الكاتب (badge= الصريح يبقى
    ويفوز، ولا يُستعمل هنا). urgent لم يعد يرسم شيئًا بنفسه: حين
    origin == "news" وurgent صحيحة، تُقرأ "breaking" من الجدول بدلًا من
    "news" (خانتها فارغة)؛ لغير "news" ملصق الجدول الخاص بها يفوز دومًا
    بصرف النظر عن urgent."""
    cfg = load_config()
    W = int(cfg.path("image.width", 1080))
    H = int(cfg.path("image.height", 1080))
    margin = int(W * 0.06)
    rule = max(4, W // 240)
    header_h = int(H * 0.160) if (cfg.path("brand.name") or cfg.path("brand.logo")) else 0
    inner_top = int(header_h * 0.14)
    inner_bot = header_h - rule - int(header_h * 0.14)
    handle_in_header = bool(cfg.path("brand.handle") and header_h)
    by = ((inner_top + inner_bot) // 2 if not handle_in_header
          else inner_top + int((inner_bot - inner_top) * 0.34))
    probe_xy = (margin + 10, by)

    breaking_bg = imaging.hex_rgb(cfg.path("cards.breaking.bg"))
    investigation_bg = imaging.hex_rgb(cfg.path("cards.verify.bg"))
    analysis_bg = imaging.hex_rgb(cfg.path("cards.analysis.bg"))
    analysis_fg = imaging.hex_rgb(cfg.path("cards.analysis.fg"))

    def close(pixel, rgb, tol=6):
        return all(abs(a - b) <= tol for a, b in zip(pixel, rgb))

    def probe(origin, urgent=False, out_name="probe.jpg"):
        out_path = _TMP_DATA_DIR / out_name
        imaging.build_post_image(
            headline="سؤال تجريبي لفحص الملصق الثاني؟", category="", urgent=urgent,
            image_urls=None, publisher=["مصدر"], bucket="serious",
            cfg=cfg, out_path=out_path, origin=origin,
        )
        with Image.open(out_path) as im:
            return im.convert("RGB").getpixel(probe_xy)

    analysis_pixel = probe("analysis", out_name="probe_analysis.jpg")
    check("بطاقة analysis تحمل «تحليل» بلونه الأزرق (cards.analysis.bg)",
          close(analysis_pixel, analysis_bg), (analysis_pixel, analysis_bg))
    # نصّ الملصق داكن (fg) لا فاتحًا: يُتحقَّق بأن fg المضبوط في الجدول
    # مختلف فعلًا عن الأبيض المستعمل لبقية الملصقات، لا بقراءة بكسلات النص
    # (رسم عربي مُشكَّل هش لقياس بكسل دقيق).
    check("جدول cards.analysis.fg نصّ داكن كما طُلب (Issue #758)",
          analysis_fg == (0x12, 0x20, 0x3A), analysis_fg)

    for origin in ("verify", "article", "request"):
        pixel = probe(origin, out_name=f"probe_{origin}.jpg")
        check(f"بطاقة {origin} تحمل «تحقيق» بلونه الأخضر (cards.{origin}.bg)",
              close(pixel, investigation_bg), (origin, pixel, investigation_bg))

    breaking_not_urgent = probe("breaking", urgent=False, out_name="probe_breaking.jpg")
    check("بطاقة breaking تحمل «عاجل» بأحمره حتى لو urgent=False",
          close(breaking_not_urgent, breaking_bg), breaking_not_urgent)

    news_not_urgent = probe("news", urgent=False, out_name="probe_news.jpg")
    check("بطاقة news بـurgent=False بلا ملصق ثانٍ (لا أحمر ولا أزرق ولا أخضر)",
          not close(news_not_urgent, breaking_bg) and
          not close(news_not_urgent, analysis_bg) and
          not close(news_not_urgent, investigation_bg), news_not_urgent)

    news_urgent = probe("news", urgent=True, out_name="probe_news_urgent.jpg")
    check("بطاقة news بـurgent=True تحمل «عاجل» (البند الاختياري المنفَّذ: "
          "news + urgent ⇐ breaking من الجدول)",
          close(news_urgent, breaking_bg), news_urgent)

    verify_urgent = probe("verify", urgent=True, out_name="probe_verify_urgent.jpg")
    check("بطاقة verify بـurgent=True تحمل «تحقيق» لا «عاجل» — ملصقها الخاص يفوز دومًا",
          close(verify_urgent, investigation_bg) and not close(verify_urgent, breaking_bg),
          verify_urgent)

    unknown_warnings: list = []
    real_warning = imaging.log.warning
    imaging.log.warning = lambda *a, **kw: unknown_warnings.append((a, kw))  # type: ignore
    try:
        unknown_pixel = probe("مسار-غير-معروف", out_name="probe_unknown.jpg")
    finally:
        imaging.log.warning = real_warning  # type: ignore
    check("origin غير مذكور في الجدول: لا انهيار، وpixel بلا ملصق ثانٍ",
          not close(unknown_pixel, breaking_bg) and not close(unknown_pixel, analysis_bg) and
          not close(unknown_pixel, investigation_bg), unknown_pixel)
    check("origin غير مذكور في الجدول: log.warning واحد بدل التخمين",
          len(unknown_warnings) == 1, unknown_warnings)

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

        # Issue #832 (العطل الثاني): مرشح يفشل جلبه يُستبدَل بالتالي له في
        # القائمة المرتَّبة أصلًا — لا تنتهي الواقعة بعدد أقل مما طُلب طالما
        # بديل متاح ضمن سقف limit*2 محاولة. هنا limit=2 (سقف 4) وBlocked1
        # يفشل قبل BBC، وBlocked2 يفشل قبل Guardian — كلاهما ضمن السقف
        members_substitute = [
            {"name": "Blocked1", "link": "https://d/4"},
            {"name": "BBC2", "link": "https://a/1"},
            {"name": "Blocked2", "link": "https://e/5"},
            {"name": "Guardian2", "link": "https://b/2"},
        ]
        docs_sub, failures_sub = gather(members_substitute, limit=2)
        check("فشل مرشّح يُستبدَل بالتالي له في القائمة — القراءات الناجحة تبلغ "
              "limit رغم فشل بينها (Issue #832)",
              {d["name"] for d in docs_sub} == {"BBC2", "Guardian2"}, docs_sub)
        check("المرشحان الفاشلان كلاهما مسجَّلان في الفشليات",
              {f["name"] for f in failures_sub} == {"Blocked1", "Blocked2"}, failures_sub)

        # سقف المحاولات صارم عند limit*2 — لا مواصلة بلا حدّ عبر members
        # كاملة (خلافًا لسلوك Issue #373 السابق): هنا limit=1 (سقف 2)
        # ومرشّحان محجوبان يتصدّران القائمة قبل مرشح ثالث ناجح — يتوقف عند
        # المحاولة الثانية بلا الوصول إلى الثالث إطلاقًا
        members_capped = [
            {"name": "Blocked1", "link": "https://d/4"},
            {"name": "Blocked2", "link": "https://e/5"},
            {"name": "Recovers", "link": "https://a/1"},
        ]
        docs_capped, failures_capped = gather(members_capped, limit=1)
        check("سقف المحاولات (limit*2=2) يوقف الجلب بما جُمِع — لا يبلغ المرشح "
              "الثالث الناجح رغم توفّره (Issue #832)",
              docs_capped == [], docs_capped)
        check("الفشليات المسجَّلة تقتصر على المرشحَين ضمن السقف فقط — لا Recovers",
              {f["name"] for f in failures_capped} == {"Blocked1", "Blocked2"},
              failures_capped)
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

def test_appeal_factors() -> None:
    """Issue #876: ثلاثة عوامل جذب تحريرية (impact/proximity/intrigue) +
    appeal_note تُقرأ من رد نداء الفرز القائم (بلا نداء نموذج إضافي)،
    تُحمل على Article، وتدخل rank.score_cluster وزنًا × الأعلى في المجموعة
    المدموجة. تغطي: القراءة والقصّ 0-3، الفشل/غياب الحقول ⇒ أصفار بلا
    انهيار، حياد الأوزان الصفرية، أخذ الأعلى لا المتوسط في المجموعة
    المدموجة، تفوّق الأثر على فارق ترند أصغر، وظهور الشارات وappeal_note
    في نصّي Issue الاختيار وIssue المراجعة الأولية."""
    from anthropic import APIError
    import httpx as _httpx

    from src import preselect, screen as screen_mod
    from src.rank import score_cluster

    now = datetime.now(timezone.utc)

    def art(title, link, **kw):
        return Article(title=title, link=link, summary="s", source_name="X",
                       region="r", weight=1.0, published=now, **kw)

    class _Block:
        def __init__(self, text):
            self.type = "text"
            self.text = text

    class _Resp:
        def __init__(self, content):
            self.content = content

    class _Messages:
        def __init__(self, resp_or_raise):
            self._resp_or_raise = resp_or_raise

        def create(self, **kw):
            if isinstance(self._resp_or_raise, Exception):
                raise self._resp_or_raise
            return self._resp_or_raise

    class _FakeClient:
        def __init__(self, resp_or_raise):
            self.messages = _Messages(resp_or_raise)

    real_client = screen_mod._client
    scfg = {"screening": {"enabled": True, "use_feedback": False}}

    # ── 1) قراءة الحقول من رد الفرز + قصّ القيم خارج المدى 0-3 ──
    a0 = art("خبر عن وقود", "https://x/fuel")
    a1 = art("خبر آخر مستبعد", "https://x/excluded")
    resp = _Resp([_Block(json.dumps({"kept": [
        {"i": 0, "impact": 5, "proximity": -1, "intrigue": 2,
         "appeal_note": "سعر الوقود يرتفع مباشرة"},
    ]}))])
    screen_mod._client = lambda: _FakeClient(resp)
    try:
        out = screen_mod.screen([a0, a1], scfg)
    finally:
        screen_mod._client = real_client

    check("الفرز يُبقي فقط ما ورد في kept", [a.link for a in out] == [a0.link],
          [a.link for a in out])
    check("impact يُقصّ من 5 إلى 3", a0.impact == 3, a0.impact)
    check("proximity يُقصّ من -1 إلى 0", a0.proximity == 0, a0.proximity)
    check("intrigue يُحمَل كما ورد ضمن المدى", a0.intrigue == 2, a0.intrigue)
    check("appeal_note يُحمَل على Article", a0.appeal_note == "سعر الوقود يرتفع مباشرة",
          a0.appeal_note)

    # ── 2) عنصر kept بلا حقول (غياب جزئي) ⇒ أصفار بلا انهيار ──
    a2 = art("خبر بلا تقدير كامل", "https://x/partial")
    resp2 = _Resp([_Block(json.dumps({"kept": [{"i": 0}]}))])
    screen_mod._client = lambda: _FakeClient(resp2)
    try:
        out2 = screen_mod.screen([a2], scfg)
    finally:
        screen_mod._client = real_client
    check("غياب حقول التقدير داخل kept لا يُسقط الخبر ويعيد أصفارًا",
          out2 == [a2] and (a2.impact, a2.proximity, a2.intrigue, a2.appeal_note)
          == (0, 0, 0, ""), (a2.impact, a2.proximity, a2.intrigue, a2.appeal_note))

    # ── 3) فشل نداء الفرز (عطل شبكة) ⇒ الدفعة كاملة أصفار بلا انهيار ──
    a3 = art("خبر أثناء عطل الفرز", "https://x/apifail")
    err = APIError("عطل شبكة اختباري",
                   request=_httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
                   body=None)
    screen_mod._client = lambda: _FakeClient(err)
    try:
        out3 = screen_mod.screen([a3], scfg)
    finally:
        screen_mod._client = real_client
    check("فشل نداء الفرز لا يُسقط الخبر ويُبقيه بأصفار",
          out3 == [a3] and (a3.impact, a3.proximity, a3.intrigue) == (0, 0, 0),
          (a3.impact, a3.proximity, a3.intrigue))

    # ── 4) الأوزان صفر ⇒ الدرجة مطابقة تمامًا لما قبل التغيير ──
    art_appealing = art("خبر جذّاب لكن الأوزان صفر", "https://x/neutral",
                        impact=3, proximity=3, intrigue=3)
    score_zero_weights = score_cluster([art_appealing], 24, trend=0.2, trend_weight=4.0)
    score_no_appeal_fields = score_cluster(
        [art("خبر بلا عوامل جذب أصلًا", "https://x/plain")], 24, trend=0.2, trend_weight=4.0)
    check("الأوزان الافتراضية صفر ⇒ حضور عوامل الجذب بلا أوزان لا يغيّر الدرجة",
          abs(score_zero_weights - score_no_appeal_fields) < 1e-9,
          (score_zero_weights, score_no_appeal_fields))

    # ── 5) مجموعة مدموجة: يؤخذ الأعلى لكل عامل على حدة لا المتوسط ──
    group = [
        art("عضو 1", "https://x/g1", impact=1, proximity=0, intrigue=2),
        art("عضو 2", "https://x/g2", impact=3, proximity=1, intrigue=0),
        art("عضو 3", "https://x/g3", impact=2, proximity=3, intrigue=1),
    ]
    with_appeal = score_cluster(group, 24, impact_weight=1.0, proximity_weight=1.0,
                                intrigue_weight=1.0)
    without_appeal = score_cluster(group, 24)
    # الأعلى في كل عامل: impact=3، proximity=3، intrigue=2 ⇒ إضافة 8، لا
    # متوسط (الذي كان سيعطي 2 + 1.33 + 1 ≈ 4.33)
    check("درجة المجموعة المدموجة تأخذ أعلى قيمة لكل عامل لا متوسطها",
          abs((with_appeal - without_appeal) - 8.0) < 1e-9,
          with_appeal - without_appeal)

    # ── 6) خبر بأثر 3 يتقدّم على خبر بمؤشر ترند أعلى بنقطتين ──
    art_impact = art("خبر مؤثر معيشيًا", "https://x/impactful", impact=3)
    art_trending = art("خبر رائج بلا أثر معيشي", "https://x/trendy")
    score_impact = score_cluster([art_impact], 24, trend=0.0, trend_weight=4.0,
                                 impact_weight=1.0, proximity_weight=1.0, intrigue_weight=1.0)
    # مؤشر ترند أعلى بـ 0.5 × وزن 4.0 = فارق نقطتين فقط، أقل من مساهمة
    # impact_weight × impact = 1.0 × 3 = 3
    score_trending = score_cluster([art_trending], 24, trend=0.5, trend_weight=4.0,
                                   impact_weight=1.0, proximity_weight=1.0, intrigue_weight=1.0)
    check("الأثر المعيشي (3) يتقدّم على فارق ترند أصغر (نقطتان)",
          score_impact > score_trending, (score_impact, score_trending))

    # ── 7) الشارات الثلاث وappeal_note تظهران في الواجهتين ──
    draft = {
        "id": "d1", "score": 20.0, "trend_score": 0.1, "velocity": 0.1,
        "bucket": "serious", "is_followup": False, "analysed_sources": [],
        "state_media": False, "impact": 3, "proximity": 2, "intrigue": 1,
        "appeal_note": "يمسّ جيب القارئ مباشرة",
        "arabic": {"urgent": False, "category": "اقتصاد", "post_title": "عنوان",
                   "angle": "خبر"},
        "source": {"publishers": ["Reuters"], "link": "https://x/impactful",
                  "image_candidates": []},
        "caption": "نص المنشور الكامل هنا بلا نقص.",
        "headlines": [], "headline_selected": 0, "reel_spec": None,
    }
    review_body = review.build_issue_body([draft], "user/trendnews", "main")
    check("Issue المراجعة الأولية يعرض شارات عوامل الجذب الثلاث",
          "💰 أثر 3" in review_body and "🫱 قرب 2" in review_body
          and "✨ تشويق 1" in review_body, review_body[:800])
    check("Issue المراجعة الأولية يعرض appeal_note",
          "يمسّ جيب القارئ مباشرة" in review_body, review_body[:800])

    candidate = {
        "id": "c1", "score": 20.0, "trend_score": 0.1, "velocity": 0.1,
        "bucket": "serious", "state_media": False,
        "impact": 3, "proximity": 2, "intrigue": 1,
        "appeal_note": "يمسّ جيب القارئ مباشرة",
        "title": "عنوان المرشح", "link": "https://x/impactful",
        "publishers": ["Reuters"],
    }
    selection_body = preselect.build_selection_issue_body([candidate])
    check("Issue الاختيار يعرض شارات عوامل الجذب الثلاث",
          "💰 أثر 3" in selection_body and "🫱 قرب 2" in selection_body
          and "✨ تشويق 1" in selection_body, selection_body[:800])
    check("Issue الاختيار يعرض appeal_note",
          "يمسّ جيب القارئ مباشرة" in selection_body, selection_body[:800])

def test_appeal_factors_affect_ranking() -> None:
    """Issue #881: عوامل الجذب الثلاثة (Issue #876) كانت تُقدَّر بعد
    rank() داخل screen() بلا أي أثر على الترتيب الفعلي — اختبار #876 فحص
    صيغة score_cluster وحدها فسمح للعطل بالمرور (rank() ← score يُحسب
    والعوامل أصفار، screen() ← العوامل تُقدَّر بعد فوات أوان الترتيب).

    هذا الاختبار يستدعي rank() ثم screen() (بفاكة) ثم
    collect.rescore_after_screen() بنفس التسلسل الذي يستخدمه collect.main()
    فعليًا بعد #881 — لا صيغة معزولة — ويغطي: مرشح بأثر/قرب/تشويق كامل
    يتقدّم فعلًا في القائمة الناتجة؛ الأوزان صفرًا ⇒ نفس ترتيب ما قبل
    التغيير حرفيًا (طريق التراجع)؛ max_per_region يبقى محفوظًا بعد إعادة
    الفرز رغم انقلاب الدرجات؛ ومرشح خارج أفق الفرز يبقى في الذيل بدرجته
    الأصلية بلا تغيير."""
    from src import screen as screen_mod
    from src.rank import rank

    now = datetime.now(timezone.utc)

    def art(title, link, region, weight=1.0):
        return Article(title=title, link=link, summary="s", source_name=title,
                       region=region, weight=weight, published=now)

    class _Block:
        def __init__(self, text):
            self.type = "text"
            self.text = text

    class _Resp:
        def __init__(self, content):
            self.content = content

    def _fake_screen_response(boosted_marker: str, **kw):
        """يمنح كل عنوان يحوي boosted_marker تقديرًا كاملًا (3/3/3)، وصفرًا
        لغيره — محاكاة فرز حقيقي يميّز مرشحًا واحدًا بعينه، لا صيغة ثابتة."""
        listing = kw["messages"][0]["content"]
        kept = []
        for line in listing.splitlines():
            m = re.match(r"(\d+)\. \[.*?\] (.*?) — ", line)
            if not m:
                continue
            i, title = int(m.group(1)), m.group(2)
            boosted = boosted_marker in title
            kept.append({"i": i, "impact": 3 if boosted else 0,
                        "proximity": 3 if boosted else 0,
                        "intrigue": 3 if boosted else 0, "appeal_note": ""})
        return _Resp([_Block(json.dumps({"kept": kept}))])

    class _FakeMessages:
        def __init__(self, marker):
            self._marker = marker

        def create(self, **kw):
            return _fake_screen_response(self._marker, **kw)

    class _FakeClient:
        def __init__(self, marker):
            self.messages = _FakeMessages(marker)

    real_client = screen_mod._client
    scfg = {"screening": {"enabled": True, "use_feedback": False}}

    def fake_screen(candidates, marker):
        screen_mod._client = lambda: _FakeClient(marker)
        try:
            return screen_mod.screen(candidates, scfg)
        finally:
            screen_mod._client = real_client

    # ── 1) مرشح ضعيف الوزن يتقدّم فعليًا في القائمة الناتجة عن الأنبوب ──
    selection = {"region_diversity": True, "max_per_region": 3,
                "appeal": {"impact_weight": 1.0, "proximity_weight": 1.0,
                           "intrigue_weight": 1.0}}
    arts = [
        art("Story Alpha strongest", "https://x/alpha", "r1", weight=3.0),
        art("Story Beta second", "https://x/beta", "r2", weight=2.5),
        art("Story Gamma weakest but impactful", "https://x/gamma", "r3", weight=1.0),
        art("Story Delta filler one", "https://x/delta", "r4", weight=0.8),
        art("Story Echo filler two", "https://x/echo", "r5", weight=0.6),
    ]
    ranked = rank(list(arts), selection)
    before = [a.link for a in ranked]
    check("شاهد بنيوي: gamma ليست في المقدمة قبل الفرز (ضعف وزنها)",
          before.index("https://x/gamma") == 2, before)

    screened = fake_screen(list(ranked), "Gamma")
    final = collect.rescore_after_screen(screened, selection)
    check("مرشح بأثر/قرب/تشويق كامل يتقدّم فعلًا في القائمة الناتجة عن الأنبوب "
          "لا في score_cluster وحدها",
          [a.link for a in final][0] == "https://x/gamma", [a.link for a in final])

    # ── 2) الأوزان صفرًا ⇒ نفس ترتيب ما قبل التغيير حرفيًا (طريق التراجع) ──
    selection_zero = {"region_diversity": True, "max_per_region": 3,
                      "appeal": {"impact_weight": 0.0, "proximity_weight": 0.0,
                                "intrigue_weight": 0.0}}
    arts2 = [
        art("Story Alpha strongest", "https://x/alpha2", "r1", weight=3.0),
        art("Story Beta second", "https://x/beta2", "r2", weight=2.5),
        art("Story Gamma weakest but impactful", "https://x/gamma2", "r3", weight=1.0),
        art("Story Delta filler one", "https://x/delta2", "r4", weight=0.8),
        art("Story Echo filler two", "https://x/echo2", "r5", weight=0.6),
    ]
    ranked2 = rank(list(arts2), selection_zero)
    screened2 = fake_screen(list(ranked2), "Gamma")
    old_pipeline_result = list(screened2)          # السلوك قبل #881: بلا إعادة فرز إطلاقًا
    new_pipeline_result = collect.rescore_after_screen(list(screened2), selection_zero)
    check("الأوزان صفرًا ⇒ القائمة الناتجة مطابقة عنصرًا بعنصر لما قبل التغيير",
          [a.link for a in new_pipeline_result] == [a.link for a in old_pipeline_result],
          ([a.link for a in new_pipeline_result], [a.link for a in old_pipeline_result]))

    # ── 3) max_per_region محفوظ بعد إعادة الفرز رغم انقلاب الدرجات ──
    # مفردات مستقلة تمامًا بين كل عنوانين حتى لا يدمجهما cluster() سهوًا
    # (Jaccard على tokens() يعمل على العنوان اللاتيني وحده، بلا علاقة بـregion)
    r1a = art("Wildfire spreads near capital city", "https://x/r1a", "r1", weight=3.0)
    r1b = art("Central bank raises interest rates today", "https://x/r1b", "r1", weight=2.0)
    r1c = art("Volcano eruption forces evacuation boosted", "https://x/r1c", "r1", weight=1.0)
    r2a = art("Telescope captures distant galaxy image", "https://x/r2a", "r2", weight=0.5)
    selection_div = {"region_diversity": True, "max_per_region": 2,
                     "appeal": {"impact_weight": 1.0, "proximity_weight": 1.0,
                               "intrigue_weight": 1.0}}
    ranked3 = rank([r1a, r1b, r1c, r2a], selection_div)
    check("قبل الفرز: تناوب المناطق يضع r1c (ثالث نفس المنطقة) في overflow",
          [a.link for a in ranked3] == ["https://x/r1a", "https://x/r1b",
                                        "https://x/r2a", "https://x/r1c"],
          [a.link for a in ranked3])

    screened3 = fake_screen(list(ranked3), "boosted")
    final3 = collect.rescore_after_screen(screened3, selection_div)
    check("بعد إعادة الفرز: r1c (الأعلى درجة الآن) يدخل المقدّمة، وr1b (ثالث "
          "نفس المنطقة في الترتيب الجديد) يُنقل إلى overflow — max_per_region محفوظ",
          [a.link for a in final3] == ["https://x/r1c", "https://x/r1a",
                                       "https://x/r2a", "https://x/r1b"],
          [a.link for a in final3])
    from collections import Counter as _Counter
    primary_regions = _Counter(a.region for a in final3[:3])
    check("لا منطقة تتجاوز max_per_region في نتيجة إعادة الفرز",
          primary_regions["r1"] <= 2, dict(primary_regions))

    # ── 4) مرشح خارج أفق الفرز يبقى في الذيل بدرجته الأصلية ──
    head = [art("Storm damages coastal infrastructure heavily", "https://x/head1",
                "r1", weight=3.0),
            art("Election results spark protests nationwide boosted", "https://x/head2",
                "r2", weight=2.5)]
    tail = [art("Harvest season yields record wheat output", "https://x/tail1",
                "r3", weight=1.5),
            art("Bridge construction delayed due funding gap", "https://x/tail2",
                "r4", weight=1.4)]
    ranked4 = rank(head + tail, selection)
    horizon = 2
    tail_scores_before = {a.link: a.score for a in ranked4[horizon:]}
    screened4 = fake_screen(list(ranked4[:horizon]), "boosted")
    final4 = collect.rescore_after_screen(screened4, selection) + ranked4[horizon:]
    check("مرشحو خارج أفق الفرز يبقون في الذيل بلا تغيير في الدرجة",
          all(a.score == tail_scores_before[a.link] for a in final4[horizon:]),
          [(a.link, a.score, tail_scores_before[a.link]) for a in final4[horizon:]])
    check("مرشحو خارج أفق الفرز يبقون بعد المفروزين لا قبلهم",
          {a.link for a in final4[:horizon]} == {a.link for a in ranked4[:horizon]}
          and [a.link for a in final4[horizon:]] == [a.link for a in tail],
          [a.link for a in final4])

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

def test_radar_auto_publish_builds_card() -> None:
    """Issue #852: الاستثناء الإلزامي الوحيد -- مسار radar.auto_publish
    (نشر فوري بلا مراجعة بشرية) لا يمرّ أبدًا بـpublish.main (حيث تُبنى
    البطاقات عند الاعتماد عمومًا)، فيجب أن يبني البطاقة صراحةً بنفسه قبل
    النشر مباشرة عبر cards.ensure -- لا يخرج منشور بلا بطاقة بحال."""
    from src import radar
    from src import publish as publish_mod

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    cfg["radar"] = {
        **(cfg.get("radar") or {}),
        "enabled": True, "auto_publish": True, "auto_publish_daily_limit": 3,
        "auto_publish_min_score": 0.0, "auto_publish_min_sources": 1,
        "preselect_fallback": False, "max_per_run": 1,
    }

    art = Article(title="زلزال عاجل يضرب المنطقة فورًا", link="https://x/auto-radar",
                 summary="", source_name="X", region="global", weight=1.0,
                 published=datetime.now(timezone.utc), score=99.0, group_sources=9,
                 state_media=False, bucket="serious",
                 image_candidates=["https://cdn.example/radar-auto.jpg"])

    real_scan = radar.scan
    real_write = radar.write_arabic
    real_gather = radar.gather_texts
    real_dup = radar.merge.find_duplicate_event
    radar.scan = lambda cfg: [art]
    radar.write_arabic = lambda article, cfg, retries=3, previous_post=None, source_docs=None: {
        "urgent": True, "category": "عالم", "angle": "خبر",
        "image_headline": "عنوان عاجل", "post_title": "عنوان عاجل",
        "post_body": "متن عاجل يكفي طولًا.", "hashtags": []}
    radar.gather_texts = lambda members, limit=2: (
        [{"name": "مصدر", "text": "نص", "link": "https://x/1"}], [])
    radar.merge.find_duplicate_event = lambda title, recent, cfg: (True, None)

    published_paths: list = []
    real_publish_photo = facebook.publish_photo
    real_root = publish_mod.ROOT
    # publish_one يبني مسار الصورة عبر publish.ROOT (لا DRAFTS_DIR)، فيجب
    # توجيهه لمجلد الاختبار المؤقت أيضًا -- وإلا بحث عن الملف في drafts/
    # الحقيقي فسجّل "الصورة مفقودة" رغم بنائها فعليًا في DRAFTS_DIR.
    publish_mod.ROOT = DRAFTS_DIR.parent

    def fake_publish_photo(image_path, caption, api_version, first_comment=None):
        published_paths.append(image_path)
        return {"url": "https://fb.example/r", "id": "1"}

    facebook.publish_photo = fake_publish_photo

    sys.argv = ["radar"]
    try:
        code = radar.main()
    finally:
        radar.scan = real_scan
        radar.write_arabic = real_write
        radar.gather_texts = real_gather
        radar.merge.find_duplicate_event = real_dup
        facebook.publish_photo = real_publish_photo
        publish_mod.ROOT = real_root

    check("radar.main() (نشر تلقائي) ينتهي بنجاح", code == 0, f"exit={code}")
    check("نُشر تلقائيًا فعلًا (نداء واحد لنشر صورة)", len(published_paths) == 1,
          published_paths)
    if published_paths:
        check("البطاقة المنشورة موجودة فعليًا على القرص",
              Path(published_paths[0]).exists(), published_paths[0])

    saved = store.load_draft(art.uid)
    check("مسودة العاجل محفوظة", saved is not None)
    if saved:
        check("البطاقة بُنيت فعلًا قبل النشر (حقل image ظهر -- radar.build_draft "
              "نفسها لم تعد تبنيها)", bool(saved[1].get("image")), saved[1].get("image"))
        check("حالة المسودة published", saved[1].get("status") == "published",
              saved[1].get("status"))

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
    for field in ("id", "status", "score", "source", "arabic", "caption"):
        check(f"حقل '{field}' موجود في المسودة", field in draft)
    check("collect.py يكتب origin=news صراحةً (Issue #749)",
          draft.get("origin") == "news", draft.get("origin"))
    check("collect.py (المسار القديم بلا preselect): يحفظ headlines/headline_selected "
          "(Issue #756)",
          isinstance(draft.get("headlines"), list) and len(draft["headlines"]) == 3
          and draft.get("headline_selected") == 0, draft.get("headlines"))

    # البطاقة لم تُبنَ عند الجمع بعد الآن (Issue #852) -- تُبنى عند
    # الاعتماد فقط عبر cards.ensure. المسودة تحمل مصدر الصورة الخام
    # (source.image_candidates) الذي ستستعمله لاحقًا، لا حقل image.
    check("بلا حقل image عند الجمع (Issue #852)", "image" not in draft, draft.get("image"))
    check("مصدر الصورة الخام محفوظ (source.image_candidates)",
          bool((draft.get("source") or {}).get("image_candidates")),
          (draft.get("source") or {}).get("image_candidates"))

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

def test_writer_usage_summary_cache_ratio() -> None:
    """سطر الكلفة 💵 يسجّل نسبة الإصابة (طلب المراجعة، نقل التخزين المؤقت
    إلى كتلة الوثائق في نداءات الحكم على السند): كم من الإدخال جاء
    مخزَّنًا مؤقتًا — بلا هذا الرقم في التقرير القائم نفسه لا وسيلة لمعرفة
    إن نفع نقل cache_control فعليًا من تشغيلة حقيقية إلى أخرى."""
    saved = dict(writer.USAGE)
    try:
        writer.USAGE.update({"input": 0, "output": 0, "cached": 0, "calls": 0, "cost": 0.0})

        class _Usage:
            def __init__(self, inp, out, cached=0, written=0):
                self.input_tokens = inp
                self.output_tokens = out
                self.cache_read_input_tokens = cached
                self.cache_creation_input_tokens = written

        class _Resp:
            def __init__(self, usage):
                self.usage = usage

        writer.record_usage(_Resp(_Usage(1000, 100)), "claude-sonnet-5")
        writer.record_usage(_Resp(_Usage(50, 20, cached=9000)), "claude-sonnet-5")
        summary = writer.usage_summary()
        total_in = writer.USAGE["input"] + writer.USAGE["cached"]
        expected_pct = round(writer.USAGE["cached"] / total_in * 100)
        check("usage_summary: يسجّل نسبة الإصابة (كم من الإدخال جاء مخزَّنًا) لا "
              "العدد الخام وحده",
              f"إصابة {expected_pct}٪" in summary, summary)
    finally:
        writer.USAGE.clear()
        writer.USAGE.update(saved)
