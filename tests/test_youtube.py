"""اختبارات مسار يوتيوب الكامل — تجزّأت من tests/test_pipeline.py (Issue #883): سكربتا القياس والتشخيص اليدويين (tools/)، إعداد بروكسي Webshare (proxy_config.py)، ومراحل المسار الخمس: الجمع (youtube_collect.py)، الاستخلاص (youtube_extract.py)، مسارات مستودع البيانات الخاص، العنقدة (youtube_cluster.py)، الكتابة (youtube_article.py)، والتوصيل (youtube_publish.py). المساعدات المشتركة (check، الفاكات، install_fakes) في tests/helpers.py."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from PIL import Image

from tests.helpers import (
    check,
    badge_probe_xy,
    reset_last_publish,
    auto_restore_last_publish,
    install_fakes,
    evidence,
    extract,
    facebook,
    headlines,
    imagesearch,
    imaging,
    open_review,
    proxy_config,
    review,
    sources,
    store,
    youtube_article,
    youtube_cluster,
    youtube_collect,
    youtube_extract,
    youtube_publish,
    DRAFTS_DIR,
    STATE_DIR,
    YOUTUBE_ARTICLES_DIR,
    YOUTUBE_POINTS_DIR,
    load_config,
    cluster,
    measure_channels,
    test_actions_block,
)
from src import publish as publish_mod


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

def test_youtube_data_repo_paths() -> None:
    """Issue #724: state/youtube_points/ وstate/youtube_articles/ لم يعودا في
    هذا المستودع -- انتقلا إلى مستودع خاص منفصل (gilandeya/trendnews-data)
    لأنهما يحويان اقتباسات حرفية من مواد محمية بحقوق نشر. config.
    YOUTUBE_POINTS_DIR/YOUTUBE_ARTICLES_DIR (src/config.py، نفس نمط
    STATE_DIR/DRAFTS_DIR القائم -- يقرآن TRENDNEWS_YOUTUBE_POINTS_DIR/
    TRENDNEWS_YOUTUBE_ARTICLES_DIR إن ضُبطا، وإلا يسقطان افتراضيًا تحت
    STATE_DIR المحلي كالسابق) هما مصدر الحقيقة الوحيد لهذين المسارين الآن؛
    هذا الاختبار يتحقّق أن الوحدات الثلاث المستهلكة تشير فعليًا لنفس القيمة
    من config لا لنسخة محلية منفصلة قد تنجرف عنها بصمت (لو أُعيد تعريف
    POINTS_DIR/ARTICLES_DIR محليًا في أحدها بالخطأ بدل استيرادها)."""
    check("YOUTUBE_POINTS_DIR افتراضيًا تحت STATE_DIR (بلا TRENDNEWS_YOUTUBE_POINTS_DIR في بيئة الاختبار)",
          YOUTUBE_POINTS_DIR == STATE_DIR / "youtube_points", YOUTUBE_POINTS_DIR)
    check("YOUTUBE_ARTICLES_DIR افتراضيًا تحت STATE_DIR (بلا TRENDNEWS_YOUTUBE_ARTICLES_DIR في بيئة الاختبار)",
          YOUTUBE_ARTICLES_DIR == STATE_DIR / "youtube_articles", YOUTUBE_ARTICLES_DIR)
    check("youtube_extract.POINTS_DIR مصدره config.YOUTUBE_POINTS_DIR",
          youtube_extract.POINTS_DIR == YOUTUBE_POINTS_DIR)
    check("youtube_cluster.POINTS_DIR مصدره config.YOUTUBE_POINTS_DIR",
          youtube_cluster.POINTS_DIR == YOUTUBE_POINTS_DIR)
    check("youtube_article.ARTICLES_DIR مصدره config.YOUTUBE_ARTICLES_DIR",
          youtube_article.ARTICLES_DIR == YOUTUBE_ARTICLES_DIR)
    # youtube_topics/ وسجلّا التكرار يبقون محليين (Issue #724 بند ٢) -- لا
    # اقتباسات فيهم (فُحص محتواهم فعليًا قبل هذا القرار)، فلا حاجة لهجرتهم.
    check("youtube_cluster.TOPICS_DIR يبقى تحت STATE_DIR المحلي (لا اقتباسات فيه)",
          youtube_cluster.TOPICS_DIR == STATE_DIR / "youtube_topics")
    check("youtube_cluster.SEEN_PATH (سجل قضايا مستهلكة) يبقى تحت STATE_DIR المحلي",
          youtube_cluster.SEEN_PATH == STATE_DIR / "youtube_topics_seen.json")

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
          ycl._layer_for({"arabic", "turkish"}, {"الجزيرة"}) == 2)
    check("طبقة ب: كتلة واحدة، قناتان مختلفتان",
          ycl._layer_for({"arabic"}, {"الجزيرة", "العربية"}) == 1)
    check("طبقة ج: كتلة واحدة وقناة واحدة",
          ycl._layer_for({"arabic"}, {"الجزيرة"}) == 1)

    # ── Issue #1121: الطبقة رقم = عدد الكتل المتقاطعة ──
    check("طبقة ٣: ثلاث كتل",
          ycl._layer_for({"arabic", "turkish", "persian"}, {"ق1"}) == 3)
    check("layer_num: الحرف القديم مرادف للرقم (أ⇒2، ب⇒1، ج⇒1) والرقم يمرّ",
          [ycl.layer_num(x) for x in ("a", "b", "c", 3, "2")] == [2, 1, 1, 3, 2])
    order_points = [mk_point("arabic", "ق1"), mk_point("turkish", "ق2"),
                    mk_point("persian", "ق3"), mk_point("arabic", "ق4")]
    order_issues = [{"title": t, "event": "ح", "agreement": "agreement", "point_ids": ids}
                    for t, ids in (("واحدة", [0, 3]), ("ثلاث", [0, 1, 2]), ("اثنتان", [0, 1]))]
    ordered = ycl.build_topics(order_issues, order_points)
    check("الترتيب: ثلاث كتل ثم كتلتان ثم كتلة",
          [t["title"] for t in ordered] == ["ثلاث", "اثنتان", "واحدة"] and
          [t["layer"] for t in ordered] == [3, 2, 1], ordered)
    thr = ycl.apply_min_points([
        {"title": "ث", "layer": 3, "point_ids": [0, 1, 2]},
        {"title": "ن", "layer": 2, "point_ids": [0, 1, 2]},
        {"title": "و", "layer": 1, "point_ids": [0, 1, 2]},
        {"title": "قديم", "layer": "a", "point_ids": [0, 1, 2]},
    ], min_points=4)[0]
    check("العتبة المخفّفة تنطبق على الطبقة 2 و3 (والحرف القديم أ) لا 1",
          [t["title"] for t in thr] == ["ث", "ن", "قديم"], thr)
    sel = ycl.build_selection_body("2099-01-01", [
        {"id": "a1", "title": "ق", "event": "", "layer": 2, "blocs": ["arabic", "persian"],
         "channels": ["ق1"], "agreement": "agreement", "point_ids": [0]}], order_points)
    check("Issue الاختيار يذكر عدد الكتل وأسماءها",
          "تقاطع 2 كتل: عربية، فارسية" in sel, sel)
    old_sel = ycl.build_selection_body("2099-01-01", [
        {"id": "a2", "title": "ق", "event": "", "layer": "a", "blocs": ["arabic", "turkish"],
         "channels": ["ق1"], "agreement": "agreement", "point_ids": [0]}], order_points)
    check("ملف قضايا قديم بحرف يُقرأ بلا انهيار", "تقاطع 2 كتل" in old_sel, old_sel)
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "prompts", "youtube_article.md"), encoding="utf-8") as fh:
        prompt_text = fh.read()
    check("البرومبت: قصّ النداء من الطرفين فقط",
          "الحذف من الطرفين فقط" in prompt_text and "إذا سمحتَ أستاذ" in prompt_text)
    check("البرومبت: لا جملة موضوعها المصادر",
          "لا تكتب جملة موضوعها المصادر" in prompt_text and "المصادر لا تتفق" in prompt_text)

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
    # الطبقات ب وج القديمتان صارتا معًا طبقة 1 (كتلة واحدة): يفرز بينهما مؤشّر الخلاف
    check("داخل الطبقة 1: الخلاف (cross_source) ثم الاتفاق ثم الصدى (echo)",
          [t["title"] for t in topics[1:]] ==
          [issue_b_dispute["title"], issue_c["title"], issue_b_echo["title"]],
          [t["title"] for t in topics])
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

    # ── apply_min_channels: حدّ أدنى للقنوات، مستقل عن عدد النقاط (Issue #944) ──
    mc_topics = [
        {"title": "قناة واحدة (ج)", "layer": "c", "blocs": ["arabic"], "channels": ["ق1"],
         "point_ids": [0, 1, 2, 3]},
        {"title": "قناتان بكتلة واحدة (ب)", "layer": "b", "blocs": ["arabic"],
         "channels": ["ق1", "ق2"], "point_ids": [0, 1, 2, 3]},
        {"title": "قناتان بكتلتين (أ)", "layer": "a", "blocs": ["arabic", "turkish"],
         "channels": ["ق1", "ق2"], "point_ids": [0, 1, 2]},
    ]
    kept_mc, dropped_mc = ycl.apply_min_channels(mc_topics, min_channels=2)
    check("apply_min_channels: موضوع بقناة واحدة يسقط",
          "قناة واحدة (ج)" not in [t["title"] for t in kept_mc], kept_mc)
    check("apply_min_channels: موضوع بقناتين في كتلة واحدة (طبقة ب) يمرّ",
          "قناتان بكتلة واحدة (ب)" in [t["title"] for t in kept_mc], kept_mc)
    check("apply_min_channels: موضوع بقناتين من كتلتين (طبقة أ) يمرّ",
          "قناتان بكتلتين (أ)" in [t["title"] for t in kept_mc], kept_mc)
    check("apply_min_channels: يُسقِط قضية واحدة فقط، يُبقي الأخريين",
          len(kept_mc) == 2 and dropped_mc == 1, (kept_mc, dropped_mc))
    check("apply_min_channels: min_channels<=1 يعطّل الشرط ويعيد السلوك السابق حرفيًا",
          ycl.apply_min_channels(mc_topics, min_channels=1) == (mc_topics, 0) and
          ycl.apply_min_channels(mc_topics, min_channels=0) == (mc_topics, 0))

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
          merged_final["layer"] == 2 and merged_final["channels"] ==
          sorted({"الجزيرة", "العربية", "CNN Türk"}), merged_final)

    check("merge_duplicate_events: أقل من قضيتين لا يستدعي النموذج أصلًا",
          ycl.merge_duplicate_events([merge_a], cluster_cfg, _Client([])) == ([merge_a], [], None))

    # فشل نداء الدمج لا يُسقِط التشغيلة -- القضايا تبقى بلا دمج (نفس مبدأ check_forbidden)
    no_merge_found, no_merge_log, no_merge_error = ycl.merge_duplicate_events(
        [merge_a, merge_unrelated], cluster_cfg, _FailingClient())
    check("merge_duplicate_events: فشل نداء الشبكة يعيد القضايا بلا دمج، وسببًا صريحًا",
          no_merge_found == [merge_a, merge_unrelated] and no_merge_log == [] and
          no_merge_error is not None, no_merge_error)

    # ── merge_duplicate_events: فحص stop_reason صراحةً بنفس أسلوب cluster_points
    # أعلاه بالضبط (Issue #1063) -- كانت لا تفحصه إطلاقًا رغم امتلاكها إعادة
    # محاولة قائمة (merge_max_retries)، فالقطع كان يُعامَل كأي إخراج غير
    # مهيكل عادي بلا تمييز، بلا رفع السقف في المحاولة التالية ──

    # 1) قطع مرة ثم نجاح إعادة المحاولة: النتيجة (الدمج) تصل فعلًا، والنداء
    # الثاني بسقف مضاعف عن الأول.
    merge_truncate_client = _Client([
        _Resp([_Block("text", text="بلوك ناقص لم يكتمل")], stop_reason="max_tokens",
              usage=_Usage(input_tokens=500, output_tokens=2000)),
        _Resp([_Block("tool_use", input_={"merges": [{"issue_indices": [0, 1]}]})],
              stop_reason="end_turn"),
    ])
    merged_t, merge_log_t, merge_error_t = ycl.merge_duplicate_events(
        [merge_a, merge_b, merge_unrelated], cluster_cfg, merge_truncate_client)
    check("merge_duplicate_events: قطع مرة ثم نجاح ⇒ الدمج يقع فعليًا بلا خطأ",
          merge_error_t is None and len(merged_t) == 2, (merged_t, merge_error_t))
    check("merge_duplicate_events: قطع مرة ثم نجاح ⇒ نداءان فقط، والثاني بسقف مضاعف عن الأول",
          len(merge_truncate_client.messages.calls) == 2 and
          merge_truncate_client.messages.calls[1]["max_tokens"] ==
          merge_truncate_client.messages.calls[0]["max_tokens"] * 2,
          [c["max_tokens"] for c in merge_truncate_client.messages.calls])

    # 2) قطع مستمر (كلتا المحاولتين، max_retries=2 افتراضيًا): لا دمج —
    # القضايا كما هي (التدهور الآمن المنصوص عليه)، وسبب الفشل النهائي يسمّي
    # max_tokens صراحةً في رسالة الفشل (لا "لم يُعِد إخراجًا مهيكلًا صالحًا"
    # العامة وحدها).
    merge_giveup_client = _Client([
        _Resp([_Block("text", text="")], stop_reason="max_tokens"),
        _Resp([_Block("text", text="")], stop_reason="max_tokens"),
    ])
    merged_g, merge_log_g, merge_error_g = ycl.merge_duplicate_events(
        [merge_a, merge_unrelated], cluster_cfg, merge_giveup_client)
    check("merge_duplicate_events: قطع مستمر ⇒ لا دمج — القضايا كما هي (التدهور الآمن)",
          merged_g == [merge_a, merge_unrelated] and merge_log_g == [], merged_g)
    check("merge_duplicate_events: قطع مستمر ⇒ سبب الفشل النهائي يسمّي max_tokens صراحةً",
          merge_error_g is not None and "max_tokens" in merge_error_g, merge_error_g)
    check("merge_duplicate_events: قطع مستمر ⇒ نداءان بالضبط (max_retries)، والثاني بسقف "
          "مضاعف عن الأول",
          len(merge_giveup_client.messages.calls) == 2 and
          merge_giveup_client.messages.calls[1]["max_tokens"] ==
          merge_giveup_client.messages.calls[0]["max_tokens"] * 2,
          [c["max_tokens"] for c in merge_giveup_client.messages.calls])

    # 3) السقف المضاعف يُقصّ عند merge_max_tokens_cap -- سقف ابتدائي وcap
    # قريبان منه كي يظهر أثر القصّ فعليًا في النداء الثاني.
    from src.config import Config as _CfgClass
    capped_cfg = _CfgClass({"youtube": {"cluster": {
        "merge_model": "claude-haiku-4-5-20251001",
        "merge_max_tokens": 3000, "merge_max_retries": 2,
        "merge_max_tokens_cap": 4000,
    }}})
    merge_cap_client = _Client([
        _Resp([_Block("text", text="")], stop_reason="max_tokens"),
        _Resp([_Block("tool_use", input_={"merges": []})], stop_reason="end_turn"),
    ])
    ycl.merge_duplicate_events([merge_a, merge_unrelated], capped_cfg, merge_cap_client)
    check("merge_duplicate_events: السقف المضاعف يُقصّ عند merge_max_tokens_cap "
          "(3000×2=6000 يُقصّ إلى 4000)",
          merge_cap_client.messages.calls[0]["max_tokens"] == 3000 and
          merge_cap_client.messages.calls[1]["max_tokens"] == 4000,
          [c["max_tokens"] for c in merge_cap_client.messages.calls])

    # ── load_points/load_topics: ملف غائب أو تالف لا يُسقِط التشغيلة ──
    check("load_points: تاريخ بلا ملف يعيد قائمة فارغة",
          ycl.load_points("1999-01-01") == [])
    check("load_topics: تاريخ بلا ملف يعيد بنية فارغة متّسقة",
          ycl.load_topics("1999-01-01") ==
          {"run_date": "1999-01-01", "topics": [], "all_topics": []})

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
              result["stats"]["layers"].get("2") == 1, result["stats"])
        check("run(): عدّادا سجل الاستهلاك وحدّ النقاط الجديدان صفر عند عدم انطباقهما",
              result["stats"]["topics_seen_skipped"] == 0 and
              result["stats"]["topics_below_min_points"] == 0, result["stats"])
        check("run(): عدّاد حدّ القنوات الجديد (Issue #944) صفر أيضًا -- القضية بها قناتان",
              result["stats"]["topics_below_min_channels"] == 0, result["stats"])
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
        # ── Issue #735 بند أ: total_points/fresh_points/dropped_reason تُوسَم
        # قبل أي فلترة، وall_topics يحفظ كل قضية بصرف النظر عن مصيرها ──
        check("run(): القضية الناجية تحمل total_points/fresh_points صحيحين وdropped_reason فارغًا",
              result["topics"][0]["total_points"] == 3 and
              result["topics"][0]["fresh_points"] == 3 and
              result["topics"][0]["dropped_reason"] is None, result["topics"][0])
        check("run(): all_topics يحوي كل القضايا (هنا واحدة، بلا إسقاط)",
              len(result["all_topics"]) == 1 and result["all_topics"] == result["topics"],
              result["all_topics"])
        saved_path = ycl.save_output(result)
        reloaded = ycl.load_topics("2099-02-02")
        check("save_output/load_topics: تكامل الحفظ والقراءة",
              reloaded["topics"][0]["title"] == "قضية تكامل", reloaded)
        check("save_output/load_topics: all_topics محفوظ ومُستَرجَع أيضًا",
              reloaded["all_topics"][0]["dropped_reason"] is None, reloaded)
    finally:
        points_path.unlink(missing_ok=True)
        (ycl.TOPICS_DIR / "2099-02-02.json").unlink(missing_ok=True)

    # ── run(): min_points_per_topic وmin_channels_per_topic يُحسَبان
    # مستقلَّين في الإحصاء (Issue #944) -- قضية بأربع نقاط من قناة واحدة
    # تسقط بحدّ القنوات لا النقاط، وقضية بقناتين لكن نقطتين فقط تسقط بحدّ
    # النقاط لا القنوات، فكل عدّاد يُحصي سقوطه هو فقط. ──
    indep_points = [
        {**mk_point("arabic", "ق1"), "statement": "٩٤٤-أ0"},
        {**mk_point("arabic", "ق1"), "statement": "٩٤٤-أ1"},
        {**mk_point("arabic", "ق1"), "statement": "٩٤٤-أ2"},
        {**mk_point("arabic", "ق1"), "statement": "٩٤٤-أ3"},
        {**mk_point("arabic", "ق2"), "statement": "٩٤٤-ب0"},
        {**mk_point("arabic", "ق3"), "statement": "٩٤٤-ب1"},
    ]
    indep_client = _Client([
        _Resp([_Block("tool_use", input_={
            "issues": [
                {"title": "أربع نقاط بقناة واحدة", "event": "حدث ١", "agreement": "agreement",
                 "point_ids": [0, 1, 2, 3]},
                {"title": "نقطتان بقناتين", "event": "حدث ٢", "agreement": "agreement",
                 "point_ids": [4, 5]},
            ],
        })]),
        # نداء merge_duplicate_events يُستدعى تلقائيًا (٢ قضية فأكثر) -- حدثان
        # منفصلان تمامًا فلا دمج.
        _Resp([_Block("tool_use", input_={"merges": []})]),
    ])
    ycl.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    indep_points_path = ycl.POINTS_DIR / "2099-02-05.json"
    indep_points_path.write_text(json.dumps({"points": indep_points}, ensure_ascii=False),
                                  encoding="utf-8")
    try:
        indep_result = ycl.run(cluster_cfg, date_str="2099-02-05", client=indep_client)
        check("run(): القضيتان تسقطان معًا، وكل واحدة بسبب مختلف",
              indep_result["topics"] == [], indep_result["topics"])
        check("run(): topics_below_min_channels يُحصي قضية القناة الواحدة فقط",
              indep_result["stats"]["topics_below_min_channels"] == 1, indep_result["stats"])
        check("run(): topics_below_min_points يُحصي قضية النقطتين فقط، مستقلًّا عن حدّ القنوات",
              indep_result["stats"]["topics_below_min_points"] == 1, indep_result["stats"])
        dropped_reasons = {t["title"]: t["dropped_reason"] for t in indep_result["all_topics"]}
        check("run(): dropped_reason يوضّح أيّ الشرطين أسقط كل قضية على حدة",
              dropped_reasons.get("أربع نقاط بقناة واحدة") == "below_min_channels" and
              dropped_reasons.get("نقطتان بقناتين") == "below_min_points",
              dropped_reasons)
    finally:
        indep_points_path.unlink(missing_ok=True)
        (ycl.TOPICS_DIR / "2099-02-05.json").unlink(missing_ok=True)

    # ── run(): قضية كل نقاطها مستهلَكة سلفًا تُسقَط بسبب 'seen'، وتبقى
    # مسجَّلة في all_topics بدل أن تضيع بلا أثر (Issue #735 بند أ -- هذا
    # بالضبط ما كان مفقودًا في قياس أيام 08-31/09-01/09-02) ──
    seen_run_points = [mk_point("arabic", "ق1"), mk_point("arabic", "ق1"),
                        mk_point("arabic", "ق1")]
    for i, p in enumerate(seen_run_points):
        p["video_id"], p["statement"] = f"vseen{i}", f"سseen{i}"
    seen_run_client = _Client([_Resp([_Block("tool_use", input_={
        "issues": [
            {"title": "قضية مستهلكة بالكامل", "event": "حدث مستهلك", "agreement": "agreement",
             "point_ids": [0, 1, 2]},
        ],
    })])])
    ycl.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    seen_run_points_path = ycl.POINTS_DIR / "2099-03-01.json"
    seen_run_points_path.write_text(json.dumps({"points": seen_run_points}, ensure_ascii=False),
                                     encoding="utf-8")
    seen_backup2 = ycl.SEEN_PATH.read_text(encoding="utf-8") if ycl.SEEN_PATH.exists() else None
    try:
        all_seen_keys = {ycl.point_key(p) for p in seen_run_points}
        ycl.SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        ycl.SEEN_PATH.write_text(json.dumps({k: "2099-02-28" for k in all_seen_keys},
                                             ensure_ascii=False), encoding="utf-8")
        seen_result = ycl.run(load_config(), date_str="2099-03-01", client=seen_run_client)
        check("run(): قضية كل نقاطها مستهلَكة سلفًا تُسقَط بسبب 'seen' فتغيب عن topics",
              seen_result["topics"] == [], seen_result["topics"])
        check("run(): لكنها تبقى في all_topics بـdropped_reason='seen' وfresh_points=0",
              len(seen_result["all_topics"]) == 1 and
              seen_result["all_topics"][0]["dropped_reason"] == "seen" and
              seen_result["all_topics"][0]["total_points"] == 3 and
              seen_result["all_topics"][0]["fresh_points"] == 0,
              seen_result["all_topics"])
    finally:
        seen_run_points_path.unlink(missing_ok=True)
        (ycl.TOPICS_DIR / "2099-03-01.json").unlink(missing_ok=True)
        if seen_backup2 is None:
            ycl.SEEN_PATH.unlink(missing_ok=True)
        else:
            ycl.SEEN_PATH.write_text(seen_backup2, encoding="utf-8")

    # ── _mark_dropped: وحدة تسجيل منفصلة -- تسم فقط ما خرج من before ولم
    # يصل after، بمقارنة مرجعية (id) لا قيمية (Issue #735 بند أ) ──
    mk_before = [{"title": "a"}, {"title": "b"}, {"title": "c"}]
    mk_after = [mk_before[0], mk_before[2]]
    ycl._mark_dropped(mk_before, mk_after, "below_min_points")
    check("_mark_dropped: القضية المُسقَطة (b) وحدها تحمل dropped_reason",
          mk_before[1].get("dropped_reason") == "below_min_points" and
          "dropped_reason" not in mk_before[0] and "dropped_reason" not in mk_before[2],
          mk_before)

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

    # ── بوابة الاختيار قبل الكتابة (Issue #1104): open_selection/
    # finalize_selection -- على مخرَج المسار (Issue مفتوح، ملف القضايا
    # المحدَّث) لا على تفاصيل داخلية. لا نداء نموذج في أيّ من الدالتين --
    # كل المعلومات المعروضة من بنية القضية المحفوظة نفسها. ──
    from src import decisions
    cfg = load_config()
    sel_topics = [
        {"title": f"قضية {i}", "event": f"حدث {i}", "layer": "a",
         "blocs": ["arabic", "turkish"], "channels": ["الجزيرة", "CNN Türk"],
         "agreement": "cross_source", "point_ids": [0, 1]}
        for i in range(1, 5)
    ]
    sel_points = [
        {"video_id": "s0", "bloc": "arabic", "channel": "الجزيرة", "speaker": "متحدث أول",
         "statement": "قول تجريبي أول", "quote_arabic": "اقتباس", "type": "fact",
         "video_title": "فيديو", "video_url": "https://youtube.com/watch?v=s0", "timestamp": 1},
        {"video_id": "s1", "bloc": "turkish", "channel": "CNN Türk", "speaker": "متحدث ثانٍ",
         "statement": "قول تجريبي ثانٍ", "quote_arabic": "اقتباس ٢", "type": "fact",
         "video_title": "فيديو ٢", "video_url": "https://youtube.com/watch?v=s1", "timestamp": 2},
    ]
    ycl.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    ycl.TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    sel_points_path = ycl.POINTS_DIR / "2099-08-01.json"
    sel_topics_path = ycl.TOPICS_DIR / "2099-08-01.json"
    sel_points_path.write_text(json.dumps({"points": sel_points}, ensure_ascii=False),
                               encoding="utf-8")
    sel_topics_path.write_text(
        json.dumps({"run_date": "2099-08-01", "topics": sel_topics}, ensure_ascii=False),
        encoding="utf-8")

    sel_created_issues: list = []
    real_create_issue_sel = review.create_issue
    real_ensure_labels_sel = review.ensure_labels
    real_repo_sel = os.environ.get("GITHUB_REPOSITORY")

    def _fake_create_issue_sel(title, body, labels=None):
        sel_created_issues.append({"title": title, "body": body, "labels": labels})
        return {"number": 4242, "html_url": "https://example.com/issues/4242"}

    review.create_issue = _fake_create_issue_sel  # type: ignore
    review.ensure_labels = lambda: None  # type: ignore
    os.environ["GITHUB_REPOSITORY"] = "user/trendnews"
    seen_backup_sel = ycl.SEEN_PATH.read_text(encoding="utf-8") if ycl.SEEN_PATH.exists() else None
    decisions_backup = decisions.load()
    decisions_file_backup = (decisions.DECISIONS_FILE.read_text(encoding="utf-8")
                             if decisions.DECISIONS_FILE.exists() else None)
    try:
        sel_result = ycl.open_selection(cfg, date_str="2099-08-01")
        check("open_selection(): يفتح Issue واحدًا بوسم youtube-selection",
              len(sel_created_issues) == 1 and sel_created_issues[0]["labels"] == ["youtube-selection"],
              sel_created_issues)
        check("open_selection(): أربعة معرّفات <!-- topic:ID --> فريدة في الجسم",
              len(ycl.SELECTION_TOPIC_RE.findall(sel_created_issues[0]["body"])) == 4 and
              len(set(ycl.SELECTION_TOPIC_RE.findall(sel_created_issues[0]["body"]))) == 4,
              sel_created_issues[0]["body"])
        check("open_selection(): علامة تاريخ الاختيار مضمَّنة في الجسم",
              "<!-- selection-date:2099-08-01 -->" in sel_created_issues[0]["body"])
        check("open_selection(): نقطة عيّنة باسم متحدث ظاهرة في الجسم (بلا نداء نموذج)",
              "متحدث أول" in sel_created_issues[0]["body"], sel_created_issues[0]["body"])
        check("open_selection(): أربع قضايا أُعيدت وكل واحدة حملت id/selection_issue",
              len(sel_result["topics"]) == 4 and
              all(t.get("id") and t.get("selection_issue") == 4242 for t in sel_result["topics"]),
              sel_result["topics"])

        # نداء ثانٍ لنفس التاريخ: القضايا عُلِّمت بالفعل (selection_status)
        # فلا تُعرَض ثانيةً ولا يُفتَح Issue جديد.
        sel_result_again = ycl.open_selection(cfg, date_str="2099-08-01")
        check("open_selection(): تشغيلة ثانية لنفس التاريخ لا تفتح Issue مكرَّرًا",
              sel_result_again["issue"] is None and sel_result_again["topics"] == [],
              sel_result_again)

        # اعتماد باختيار قضيتين من أربع (١ و٣) فقط -- محاكاة تعليم المراجع
        # لمربعي هذين المعرّفين في نصّ الـIssue الفعلي.
        chosen_ids = [sel_result["topics"][0]["id"], sel_result["topics"][2]["id"]]
        approve_body = sel_created_issues[0]["body"]
        for cid in chosen_ids:
            approve_body = re.sub(
                r"- \[ \](.*?)<!-- topic:" + cid + r" -->",
                lambda m: f"- [x]{m.group(1)}<!-- topic:{cid} -->",
                approve_body)

        fin_result = ycl.finalize_selection(4242, approve_body, cfg)
        check("finalize_selection(): تاريخ الاختيار استُخرج صحيحًا من الجسم",
              fin_result["date_str"] == "2099-08-01", fin_result)
        check("finalize_selection(): قضيتان معلَّمتان للكتابة، وقضيتان لم تُختارا",
              len(fin_result["to_write"]) == 2 and fin_result["unselected_now"] == 2,
              fin_result)
        written_titles = {t["title"] for t in fin_result["to_write"]}
        check("finalize_selection(): القضيتان المكتوبتان هما المعلَّمتان فعليًا (١ و٣)",
              written_titles == {"قضية 1", "قضية 3"}, written_titles)

        persisted = json.loads(sel_topics_path.read_text(encoding="utf-8"))
        persisted_status = {t["title"]: t.get("selection_status") for t in persisted["topics"]}
        check("finalize_selection(): الحالة المحفوظة على القرص صحيحة لكل قضية (selected/unselected)",
              persisted_status == {"قضية 1": "selected", "قضية 2": "unselected",
                                   "قضية 3": "selected", "قضية 4": "unselected"},
              persisted_status)
        check("finalize_selection(): غير المعلَّم سُجِّل «لم يُختر» في decisions.json",
              len(decisions.load()) - len(decisions_backup) == 2 and
              all(e["decision"] == "unselected" and e["reject_tag"] == "لم يُختر"
                  for e in decisions.load()[len(decisions_backup):]),
              decisions.load()[len(decisions_backup):])
        check("finalize_selection(): نقاط غير المختار عُلِّمت مستهلكة (mark_points_seen)",
              ycl.point_key(sel_points[0]) in ycl.load_seen_points(), ycl.load_seen_points())

        # إعادة اعتماد نفس الـIssue بلا تغيير (تكرار الوسم) -- لا يُعاد حسم
        # ما حُسِم بالفعل، ونفس دفعة الكتابة تعود كما هي (بلا مضاعفة).
        fin_result_again = ycl.finalize_selection(4242, approve_body, cfg)
        check("finalize_selection(): إعادة الاعتماد لا تُسجِّل «لم يُختر» مرّة ثانية",
              fin_result_again["unselected_now"] == 0, fin_result_again)
        check("finalize_selection(): إعادة الاعتماد تعيد نفس دفعة الكتابة (القضيتان أنفسهما)",
              {t["title"] for t in fin_result_again["to_write"]} == {"قضية 1", "قضية 3"},
              fin_result_again)
    finally:
        review.create_issue = real_create_issue_sel  # type: ignore
        review.ensure_labels = real_ensure_labels_sel  # type: ignore
        if real_repo_sel is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo_sel
        sel_points_path.unlink(missing_ok=True)
        sel_topics_path.unlink(missing_ok=True)
        if seen_backup_sel is None:
            ycl.SEEN_PATH.unlink(missing_ok=True)
        else:
            ycl.SEEN_PATH.write_text(seen_backup_sel, encoding="utf-8")
        if decisions_file_backup is None:
            decisions.DECISIONS_FILE.unlink(missing_ok=True)
        else:
            decisions.DECISIONS_FILE.write_text(decisions_file_backup, encoding="utf-8")

def test_youtube_article() -> None:
    """المرحلة الرابعة (src/youtube_article.py، Issue #646): كتابة مقالات
    من أعلى القضايا. لا شبكة، لا نموذج فعلي -- الحارس والكتابة كلاهما
    مموَّهان بفاكة محلية. يغطّي: التحقّق من بنية المقال، حارس المحظورات
    (طبقة ج فقط)، الترقيم بلا فجوات، وبناء index.md."""
    ya = youtube_article
    ycl = youtube_cluster
    article_cfg = load_config()

    def _valid_article(title="عنوان-سؤال تجريبي عن قضية ما؟", filler_words=300,
                        include_likelihood=True, extra_body=""):
        # ٣٠٠ كلمة حشو + جملة الترجيح ⇒ تقع مريحًا داخل نافذة ٢٥٠–٧٥٠ كلمة
        # (youtube.article.min_words/max_words) بلا أي عنوان ## إطلاقًا (Issue
        # #941 -- حتى ## المصادر صار ممنوعًا، لا فقط ما زاد عنه). لا سطر
        # **التقدير:** هنا -- ممنوع في النسخة الرابعة (Issue #695)؛ عبارة
        # الترجيح مدمجة في جملة نثرية عادية بدل صندوق التقدير الذي زال.
        filler = " ".join(["كلمة"] * filler_words)
        likelihood_sentence = ("وهذا مرجّح بقوة، ولا يسندها إلا مصدر واحد."
                                if include_likelihood else "")
        parts = [filler, likelihood_sentence, extra_body]
        body = "\n\n".join(p for p in parts if p)
        return f"# {title}\n\n{body}\n"

    # ── _validate_article_text: بنية إلزامية (Issue #690 -- نثر متّصل بلا أقسام،
    # Issue #941 -- حتى ## المصادر صار ممنوعًا لا مطلوبًا) ──
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

    # ── Issue #941: القاعدة معكوسة تمامًا -- ## المصادر كان إلزاميًا (Issue
    # #690) وصار ممنوعًا، وأي قسم ## آخر كان "زائدًا" فيُرفَض ويبقى مرفوضًا
    # الآن لنفس السبب العام (صفر أقسام مسموح) ──
    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="## المصادر\nقناة تجريبية -- رابط"), article_cfg)
    check("(#941) مقال فيه ## المصادر يُرفَض الآن (عكس قاعدة Issue #690)",
          not ok and "##" in reason and "المصادر" in reason, reason)

    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="## من قال ماذا\nنقاش الأطراف هنا."), article_cfg)
    check("مقال فيه أي قسم ## آخر يُرفَض أيضًا (صفر أقسام مسموح إطلاقًا)",
          not ok and "##" in reason, reason)

    ok, reason = ya._validate_article_text(_valid_article(filler_words=5), article_cfg)
    check("مقال أقصر من الحدّ الأدنى (250 كلمة) يُرفَض",
          not ok and "قصير جدًا" in reason and "الأدنى 250" in reason, reason)

    ok, reason = ya._validate_article_text(_valid_article(filler_words=800), article_cfg)
    check("مقال أطول من الحدّ الأعلى (750 كلمة) يُرفَض",
          not ok and "طويل جدًا" in reason and "الأعلى 750" in reason, reason)

    # ── فحوص "المتن" (كل ما بعد العنوان الرئيسي حتى نهاية النص، Issue #941) ──
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
    check("فاصل أفقي (---) في المتن يُرفَض (ممنوع كليًا الآن، Issue #941 -- لا استثناء "
          "لفاصل يسبق مصادر بعد زوال قسمها)",
          not ok and "فاصل أفقي" in reason, reason)

    # Issue #941: كان الفاصل الأفقي الواحد الذي يسبق ## المصادر مباشرة
    # مستثنًى (Issue #695) -- زوال القسم معه يعني رفض حتى فاصل زائد وحيد في
    # آخر المتن، لا فقط ما تجاوز فاصلًا واحدًا مسموحًا كسابقًا.
    ok, reason = ya._validate_article_text(
        _valid_article(extra_body="فقرة أخيرة من المتن.") + "\n---\n", article_cfg)
    check("(#941) فاصل أفقي وحيد في آخر المتن يُرفَض أيضًا (لا استثناء له بعد اليوم)",
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

    # ── نظام تعليمات draft_article يُلزم بالوقائع الصلبة، بالاقتباس الحرفي
    # من quote_arabic وحده، وبتعريف المتحدث باسمه وصفته (Issue #1102) --
    # قياس على 20 مقال تحليل حقيقي أظهر 16 منها بلا رقم واحد و16 بلا اقتباس
    # حرفي واحد، ومتحدثين بلا هوية ("محلل" مجرّدة 11 مرة). هذا اختبار على
    # نصّ التعليمات نفسه (منطق الشيفرة لم يتغيّر) -- لا يُثبت جودة الناتج،
    # فذلك يحكم عليه صاحب المشروع بعينه على مقالات حقيقية لاحقًا ──
    article_prompt_text = ya.load_article_prompt()
    check("برومبت المقال (#1102): ينقل الأرقام/التواريخ/النسب/أسماء الأماكن كما وردت حرفيًا",
          "كل رقم أو تاريخ أو نسبة أو اسم مكان ورد في النقاط ينتقل إلى المقال كما هو"
          in article_prompt_text, article_prompt_text)
    check("برومبت المقال (#1102): يمنع منعًا قاطعًا اختراع رقم أو تاريخ لم يرد في النقاط",
          "يُمنع منعًا قاطعًا اختراع رقم أو تاريخ أو نسبة لم يرد حرفيًا في النقاط"
          in article_prompt_text, article_prompt_text)
    check("برومبت المقال (#1102): يشترط اقتباسًا حرفيًا واحدًا على الأقل من quote_arabic فقط",
          "اقتباسًا حرفيًا واحدًا على الأقل من نص quote_arabic" in article_prompt_text and
          "لا يجوز اقتباس أي نص غير quote_arabic" in article_prompt_text, article_prompt_text)
    check("برومبت المقال (#1102): سقف ثلاثة اقتباسات، وبلا اقتباس إن لم يصلح أيّ منها",
          "سقفك ثلاثة اقتباسات" in article_prompt_text and
          "فاكتب المقال بلا اقتباس إطلاقًا -- لا تختلق واحدًا" in article_prompt_text,
          article_prompt_text)
    check("برومبت المقال (#1102): يمنع الألقاب المجرّدة (محلل/متحدث/مقدّم البرنامج/الضيف) بلا تعريف",
          "يُمنع استعمال «محلل» أو «متحدث» أو «مقدّم البرنامج» أو «الضيف» مجرّدة"
          in article_prompt_text, article_prompt_text)
    check("برومبت المقال (#1102): لقب عام بلا اسم عَلَم يُنسَب صراحةً إلى القناة",
          "فانسب القول صراحةً إلى القناة نفسها" in article_prompt_text, article_prompt_text)
    check("برومبت المقال (#1102): يمنع نسبة رأي إلى «مصادر»/«مراقبين» مبهمة",
          "لا تنسب رأيًا إلى «مصادر» أو «مراقبين»" in article_prompt_text, article_prompt_text)
    check("برومبت المقال (#1102): يمنع افتتاح الخاتمة بصيغة قالبية ثابتة",
          "يُمنع افتتاح الخاتمة بعبارة «في المحصلة» أو «بجمع هذه الخيوط» أو «من حيث الترجيح»"
          in article_prompt_text, article_prompt_text)

    # ── draft_article: الوقائع الصلبة (رقم)، اسم المتحدث، والاقتباس الحرفي
    # الواردة في النقاط تصل فعلًا نصّ الطلب المُرسَل إلى النموذج (Issue #1102
    # -- المادة موجودة أصلًا في _points_block، هذا تثبيت لا يزال يمرّ بعد
    # تعديل نظام التعليمات وحده بلا مسّ أيّ منطق) ──
    rich_points = [{
        "channel": "الجزيرة", "bloc": "arabic", "speaker": "أحمد فلان (محلل سياسي)",
        "type": "رأي", "statement": "الأزمة تفاقمت خلال ستين عامًا من التوتر",
        "quote_arabic": "لم نشهد توترًا بهذا الحجم منذ ستين عامًا",
        "video_title": "فيديو تجريبي", "video_url": "https://example.com/v", "timestamp": 12,
    }]
    rich_client = _Client([_Resp([_Block("text", text=_valid_article())])])
    ya.draft_article(topic_a, rich_points, article_cfg, rich_client)
    sent_content = rich_client.messages.calls[0]["messages"][0]["content"]
    check("draft_article: الرقم/التاريخ الوارد في النقطة يصل نصّ الطلب",
          "ستين عامًا" in sent_content, sent_content)
    check("draft_article: اسم المتحدث الوارد في speaker يصل نصّ الطلب",
          "أحمد فلان (محلل سياسي)" in sent_content, sent_content)
    check("draft_article: الاقتباس الحرفي (quote_arabic) يصل نصّ الطلب",
          "لم نشهد توترًا بهذا الحجم منذ ستين عامًا" in sent_content, sent_content)

    # ── draft_article: نقطة بلا quote_arabic صالح (مفتاح غائب كليًا) لا
    # تكسر شيئًا -- المقال يُصاغ كما اليوم (Issue #1102 قيد التثبيت) ──
    no_quote_points = [{"channel": "الجزيرة", "speaker": "ناطق باسم الحكومة",
                        "statement": "بيان رسمي بلا اقتباس مسجَّل"}]
    no_quote_client = _Client([_Resp([_Block("text", text=_valid_article())])])
    no_quote_text, no_quote_error = ya.draft_article(topic_a, no_quote_points, article_cfg,
                                                       no_quote_client)
    check("draft_article: نقطة بلا مفتاح quote_arabic لا تكسر شيئًا (يُصاغ المقال كالمعتاد)",
          no_quote_error is None and no_quote_text is not None, no_quote_error)

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

    hl_success_client = _Client([_Resp([_Block("tool_use", input_={
        "headlines": good_headlines, "image_query_en": "Strait of Hormuz tanker"})])])
    hl_result, hl_error, hl_image_query = ya.generate_headlines(
        hl_topic, hl_member_points, article_cfg, hl_success_client)
    check("generate_headlines: محاولة أولى صالحة تُقبَل بلا إعادة",
          hl_error is None and hl_result == good_headlines, (hl_result, hl_error))
    check("generate_headlines: image_query_en (Issue #941) يصل عبر نفس النداء بلا نداء إضافي",
          hl_image_query == "Strait of Hormuz tanker", hl_image_query)

    hl_retry_client = _Client([
        _Resp([_Block("tool_use", input_={"headlines": not_question})]),
        _Resp([_Block("tool_use", input_={"headlines": good_headlines})]),
    ])
    hl_result2, hl_error2, hl_image_query2 = ya.generate_headlines(
        hl_topic, hl_member_points, article_cfg, hl_retry_client)
    check("generate_headlines: إعادة محاولة بعد عنوان أول بلا صيغة سؤال تنجح",
          hl_error2 is None and hl_result2 == good_headlines, (hl_result2, hl_error2))
    check("generate_headlines: غياب image_query_en من ردّ النموذج يعيد None بلا انهيار",
          hl_image_query2 is None, hl_image_query2)

    hl_bad_client = _Client([
        _Resp([_Block("tool_use", input_={"headlines": not_question})]),
        _Resp([_Block("tool_use", input_={"headlines": not_question})]),
    ])
    hl_result3, hl_error3, hl_image_query3 = ya.generate_headlines(
        hl_topic, hl_member_points, article_cfg, hl_bad_client)
    check("generate_headlines: فشل كل المحاولات يعيد سببًا صريحًا لا قائمة",
          hl_result3 is None and hl_error3 is not None, hl_error3)
    check("generate_headlines: فشل كل المحاولات يعيد image_query_en=None أيضًا",
          hl_image_query3 is None, hl_image_query3)

    appended_hl = ya._append_headlines("# عنوان\n\nنص المقال", good_headlines)
    check("_append_headlines: يضيف القسم بترويسة صحيحة وترقيم ١-٣",
          ya.HEADLINES_HEADER in appended_hl and
          all(f"{i}. {h}" in appended_hl for i, h in enumerate(good_headlines, start=1)),
          appended_hl)

    # ── _append_image_query (Issue #941): كلمات بحث الصورة الإنجليزية ──
    appended_iq = ya._append_image_query("# عنوان\n\nنص المقال", "Strait of Hormuz tanker")
    check("_append_image_query: يضيف القسم بترويسة صحيحة عند توفّر قيمة فعلية",
          ya.IMAGE_QUERY_HEADER in appended_iq and "Strait of Hormuz tanker" in appended_iq,
          appended_iq)
    check("_append_image_query: غياب القيمة (None) لا يغيّر النص إطلاقًا",
          ya._append_image_query("نص كما هو", None) == "نص كما هو")
    check("_append_image_query: سلسلة فارغة تُعامَل معاملة None (بلا قسم فارغ دومًا)",
          ya._append_image_query("نص كما هو", "") == "نص كما هو")

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
    # بوابة توفّر صورة قبل نداء الصياغة (Issue #1092، الدرجة الثانية استُبدلت
    # في Issue #1095) -- تستدعيها run() الآن لكل قضية عبر
    # youtube_extract.photo_candidates (بحث حر حقيقي، فيمرّ عبر
    # imagesearch.find_images/sources.requests.get غير المموَّهين هنا لهذا
    # الغرض) قبل youtube_extract.news_photo_available (بحث عبر
    # request.search_feeds/sources.fetch_source، وsources.requests.get/
    # image_from_page وimaging.download_image المموَّهة عالميًا في
    # install_fakes -- الفاكة العامة تعيد خلاصة RSS ثابتة وصورة og:image
    # صالحة دومًا، فصورة الخبر تنجح لكل قضية بلا استثناء). لا صورة حرة هنا
    # (find_images مموَّهة فارغة) كي لا يصل نداء بحث حقيقي عبر الفاكة العامة
    # غير المُعِدَّة لصيغة رد ويكيميديا.
    real_find_images_run = imagesearch.find_images
    imagesearch.find_images = lambda *a, **k: []  # type: ignore
    try:
        # Issue #1104: run() لم تعد تقرأ topics[:count] تلقائيًا من ملف
        # العنقدة -- topics_override يمرّرها صراحةً (بوابة الاختيار قبل
        # الكتابة تُختبَر بذاتها أدناه في هذا الملف). topics_path لا يزال
        # يُكتَب أعلاه لأن run() يستهلك نفس ملف النقاط (points_path) عبر
        # prepare_window_points -- لا علاقة لذلك بقراءة topics نفسها.
        result = ya.run(article_cfg, date_str="2099-04-04", client=run_client,
                        topics_override=topics_for_run)
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
        imagesearch.find_images = real_find_images_run  # type: ignore
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

    # ── run(): بلا topics_override لا تكتب شيئًا إطلاقًا حتى لو حمل ملف
    # العنقدة قضايا فعلية (Issue #1104، بوابة الاختيار قبل الكتابة) -- هذا
    # بالضبط ما يجعل خطوة "الكتابة" في youtube-articles.yml (python -m
    # src.youtube_article، بلا خيارات) بلا عمل فعليًا بعد اليوم: صفر نداء
    # نموذج، صفر مقال، بصرف النظر عمّا تحمله state/youtube_topics/<date>.json ──
    ycl.TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    no_override_topics_path = ycl.TOPICS_DIR / "2099-07-07.json"
    no_override_topics_path.write_text(
        json.dumps({"run_date": "2099-07-07", "topics": topics_for_run}, ensure_ascii=False),
        encoding="utf-8")
    seen_backup_noverride = ycl.SEEN_PATH.read_text(encoding="utf-8") if ycl.SEEN_PATH.exists() else None
    try:
        no_override_client = _Client([])
        result_no_override = ya.run(article_cfg, date_str="2099-07-07", client=no_override_client)
        check("run(): بلا topics_override ⇐ صفر مقالات رغم وجود قضايا في ملف العنقدة",
              result_no_override["stats"]["articles_written"] == 0 and
              result_no_override["stats"]["topics_considered"] == 0, result_no_override["stats"])
        check("run(): بلا topics_override ⇐ صفر نداء نموذج إطلاقًا (لا حارس، لا كتابة، لا عناوين)",
              len(no_override_client.messages.calls) == 0, no_override_client.messages.calls)
    finally:
        no_override_topics_path.unlink(missing_ok=True)
        shutil.rmtree(ya.ARTICLES_DIR / "2099-07-07", ignore_errors=True)
        if seen_backup_noverride is None:
            ycl.SEEN_PATH.unlink(missing_ok=True)
        else:
            ycl.SEEN_PATH.write_text(seen_backup_noverride, encoding="utf-8")

@auto_restore_last_publish
def test_youtube_publish() -> None:
    """المرحلة الخامسة (src/youtube_publish.py، Issue #676 وIssue #680
    وIssue #732): توصيل المسودة ودورة المراجعة والنشر بما كان قائمًا
    (imaging/store/review/publish) بلا تعديل على منطقها إلا حيث وحَّد
    Issue #732 بطاقة هذا المسار مع بطاقة الأخبار (imaging.build_post_image
    ذاتها بمعامل badge). لا شبكة -- review.create_issue/comment/
    fetch_issue_body/close_issue/remove_label وpublish.publish_one كلّها
    مموَّهة محليًا؛ بناء بطاقة العنوان نفسه محلي بالكامل (Pillow فقط)،
    وimagesearch.find_images/imaging.download_image/imaging.face_score
    مموَّهة أيضًا حيث تُختبَر صورة البطاقة التعبيرية (طلب مراجعة لاحق على
    Issue #680) فلا نداء شبكة حقيقي إطلاقًا في كل هذا الملف.
    يغطّي أيضًا الدرجة المركّبة والترتيب بها، تأجيل بناء البطاقة إلى ما بعد
    الاعتماد (ensure_title_card)، وقراءة اختيار العنوان من ثلاثة (Issue
    #680)."""
    yp = youtube_publish
    cfg = load_config()

    # ── image_source_line (Issue #732، معكوسًا جزئيًا بـIssue #1106): يسمّي
    # القنوات الآن بدل عدّها -- «تحليل لتغطية» تحلّ علّة القرار القديم
    # (النسبة الزائفة) بديباجة صريحة بدل إخفاء الأسماء ──
    check("image_source_line: قناتان، الثانية لاتينية -- الواو تُفصل بمسافة (Issue #1108)",
          yp.image_source_line(["الجزيرة", "ILTV"], cfg) == "تحليل لتغطية الجزيرة و ILTV",
          yp.image_source_line(["الجزيرة", "ILTV"], cfg))
    check("image_source_line: قناة واحدة -- اسمها وحده بلا «و»",
          yp.image_source_line(["الجزيرة"], cfg) == "تحليل لتغطية الجزيرة",
          yp.image_source_line(["الجزيرة"], cfg))
    check("image_source_line: ثلاث قنوات، الأخيرة لاتينية -- فواصل ثم «و» بمسافة قبل الأخيرة",
          yp.image_source_line(["الجزيرة", "العربية", "ILTV"], cfg)
          == "تحليل لتغطية الجزيرة، العربية، و ILTV",
          yp.image_source_line(["الجزيرة", "العربية", "ILTV"], cfg))
    # سقف الطول (cards.analysis.source_max_chars، افتراضه 48): أسماء طويلة
    # تتجاوزه ⇐ أول اسمين ثم «وقنوات أخرى» بدل القائمة الكاملة.
    long_channels = ["قناة تلفزيونية طويلة الاسم جدًا", "قناة أخرى طويلة الاسم أيضًا",
                      "قناة ثالثة طويلة الاسم كذلك"]
    long_line = yp.image_source_line(long_channels, cfg)
    check("image_source_line: أسماء طويلة تتجاوز السقف ⇐ أول اسمين ثم «وقنوات أخرى»",
          long_line == "تحليل لتغطية " + yp._join_arabic_names(long_channels[:2] + ["قنوات أخرى"]),
          long_line)
    check("image_source_line: سطر التجاوز لا يحوي اسم القناة الثالثة",
          long_channels[2] not in long_line, long_line)
    check("image_source_line: سطر لا يتجاوز السقف يبقى كاملًا بلا اقتطاع",
          yp.image_source_line(["الجزيرة", "ILTV"], cfg) == "تحليل لتغطية الجزيرة و ILTV")

    # Issue #758: cards.analysis.source_template صار له الأولوية على
    # youtube.image.source_line_template -- يُحذَف هنا كي يختبر هذا القالب
    # الأقدم وحده مستوى الأولوية الثاني (المفتاح القديم القائم للتوافق).
    cfg_custom_line = load_config()
    del cfg_custom_line["cards"]["analysis"]["source_template"]
    cfg_custom_line["youtube"]["image"]["source_line_template"] = "بعيون {channels}"
    check("image_source_line: بلا cards.analysis.source_template، يُقرأ القالب من "
          "youtube.image.source_line_template (المستوى الثاني، Issue #758)",
          yp.image_source_line(["الجزيرة", "العربية"], cfg_custom_line) == "بعيون الجزيرة والعربية",
          yp.image_source_line(["الجزيرة", "العربية"], cfg_custom_line))

    cfg_cards_priority = load_config()
    cfg_cards_priority["cards"]["analysis"]["source_template"] = "نظرة على {channels}"
    cfg_cards_priority["youtube"]["image"]["source_line_template"] = "بعيون {channels}"
    check("image_source_line: cards.analysis.source_template يفوز على "
          "youtube.image.source_line_template حين يتوفّر كلاهما (Issue #758)",
          yp.image_source_line(["الجزيرة", "العربية"], cfg_cards_priority) == "نظرة على الجزيرة والعربية",
          yp.image_source_line(["الجزيرة", "العربية"], cfg_cards_priority))

    # سقف طول قابل للتعديل بلا كود (Issue #1106): تعديله في config.yaml
    # يغيّر عتبة الاقتطاع فعليًا لا رقمًا مزروعًا في الشيفرة -- سطر ٣ قنوات
    # قصيرة الأسماء لا يتجاوز الافتراضي (48) لكنه يتجاوز سقفًا مخفَّضًا يدويًا.
    cfg_small_cap = load_config()
    cfg_small_cap["cards"]["analysis"]["source_max_chars"] = 10
    small_cap_line = yp.image_source_line(["الجزيرة", "العربية", "ILTV"], cfg_small_cap)
    check("image_source_line: cards.analysis.source_max_chars قابل للتعديل من config.yaml",
          small_cap_line == "تحليل لتغطية " + yp._join_arabic_names(["الجزيرة", "العربية", "قنوات أخرى"]),
          small_cap_line)

    check("_arabic_channel_count_phrase: مرفوعة افتراضيًا («قناتان»)",
          yp._arabic_channel_count_phrase(2) == "قناتان")
    check("_arabic_channel_count_phrase: مجرورة صراحة («قناتين»)",
          yp._arabic_channel_count_phrase(2, genitive=True) == "قناتين")

    # ── _join_arabic_names: الوصل العربي وحده، بلا فرز (Issue #1106) ──
    check("_join_arabic_names: قائمة فارغة تعيد نصًّا فارغًا",
          yp._join_arabic_names([]) == "")
    check("_join_arabic_names: اسم واحد بلا وصل",
          yp._join_arabic_names(["أ"]) == "أ")
    check("_join_arabic_names: اسمان بـ«و» وحدها",
          yp._join_arabic_names(["أ", "ب"]) == "أ وب")
    check("_join_arabic_names: ثلاثة فأكثر بفواصل ثم «و» قبل الأخير",
          yp._join_arabic_names(["أ", "ب", "ج"]) == "أ، ب، وج")
    check("_join_arabic_names: يحافظ على ترتيب المُدخَل بلا فرز جديد",
          yp._join_arabic_names(["ب", "أ"]) == "ب وأ")

    # ── واو العطف الملتصقة باسم لاتيني تُرسم مشوَّهة (Issue #1108): تُفصل
    # بمسافة عند حدّ عربي/لاتيني بلا فاصل، وتبقى ملتصقة حين يكون الاسم
    # التالي عربيًّا كما كانت دومًا ──
    check("_join_arabic_names: اسم لاتيني تالٍ -- الواو تُفصل بمسافة",
          yp._join_arabic_names(["الجزيرة", "ILTV"]) == "الجزيرة و ILTV",
          yp._join_arabic_names(["الجزيرة", "ILTV"]))
    check("_join_arabic_names: اسم عربي تالٍ -- الواو ملتصقة كما اليوم",
          yp._join_arabic_names(["الجزيرة", "العربية"]) == "الجزيرة والعربية",
          yp._join_arabic_names(["الجزيرة", "العربية"]))
    check("_join_arabic_names: ثلاثة أسماء، الأخير لاتيني -- فواصل ثم «و» بمسافة",
          yp._join_arabic_names(["الجزيرة", "العربية", "ILTV"]) == "الجزيرة، العربية، و ILTV",
          yp._join_arabic_names(["الجزيرة", "العربية", "ILTV"]))
    check("_join_arabic_names: اسم لاتيني أول ثم عربي تالٍ -- الواو ملتصقة (الاسم التالي عربي)",
          yp._join_arabic_names(["ILTV", "الجزيرة"]) == "ILTV والجزيرة",
          yp._join_arabic_names(["ILTV", "الجزيرة"]))

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

    # ── split_image_query (Issue #941): يُقصّ قبل split_headlines -- الترتيب
    # الفعلي في نصّ المقال متن ← تحذيرات ← عناوين ← كلمات بحث الصورة ──
    article_with_image_query = (
        "# عنوان تجريبي؟\n\nمتن.\n\n---\n" + youtube_article.HEADLINES_HEADER + "\n"
        "1. عنوان تجريبي؟\n2. بديل ١\n3. بديل ٢\n"
        "\n---\n" + youtube_article.IMAGE_QUERY_HEADER + "\nStrait of Hormuz tanker\n"
    )
    stripped, image_query = yp.split_image_query(article_with_image_query)
    check("split_image_query: يستخرج كلمات البحث الإنجليزية كاملة",
          image_query == "Strait of Hormuz tanker", image_query)
    check("split_image_query: النصّ المتبقّي خالٍ من قسم كلمات البحث لكنه يحتفظ بالعناوين",
          youtube_article.IMAGE_QUERY_HEADER not in stripped and
          youtube_article.HEADLINES_HEADER in stripped, stripped)
    check("split_image_query: بعد القصّ، split_headlines يعمل عليه كما لو لم يكن القسم موجودًا",
          yp.split_headlines(stripped)[1] == ["عنوان تجريبي؟", "بديل ١", "بديل ٢"],
          yp.split_headlines(stripped))

    stripped_none, image_query_none = yp.split_image_query("# عنوان بلا قسم\nنص")
    check("split_image_query: قسم غائب يعيد None بلا استثناء، والنصّ بلا تغيير جوهري",
          image_query_none is None and "# عنوان بلا قسم" in stripped_none, stripped_none)

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
          parsed and parsed[0]["filename"] == "01-a.md" and parsed[0]["layer"] == 2 and
          parsed[0]["blocs"] == ["arabic", "turkish"] and
          parsed[0]["channels"] == ["الجزيرة", "CNN Türk"] and
          parsed[0]["agreement"] == "cross_source", parsed[0] if parsed else None)
    check("parse_index: عمود event الجديد يُقرأ صحيحًا (طلب المراجعة على Issue #680)",
          parsed and parsed[0]["event"] == "حدث أ" and parsed[1]["event"] == "حدث ب", parsed)
    check("parse_index: مؤشّر التنبيهات المُعلَّم (⚠️ **2**) يُقرأ عددًا صحيحًا",
          parsed and parsed[0]["warnings_count"] == 2, parsed)
    check("parse_index: صفّ بصفر تنبيهات يُقرأ 0",
          len(parsed) > 1 and parsed[1]["warnings_count"] == 0, parsed)

    # ── imaging.build_post_image بمعامل badge (Issue #732): بطاقة التحليل
    # لا نسخة رسم منفصلة -- بادج «تحليل» وحده هو الفارق البصري عن بطاقة
    # الأخبار. badge=None (الافتراضي) يجب ألا يغيّر شيئًا -- هذا بالضبط ما
    # يضمنه معيار القبول "بطاقة أخبار قبل التعديل وبعده متطابقتان" ──
    card_cfg = load_config()
    W = int(card_cfg.path("image.width", 1080))
    H = int(card_cfg.path("image.height", 1350))
    # الشارة في صف منطقة العنوان (Issue #1160)
    probe_pt = badge_probe_xy(card_cfg, ["تحليل"], 0,
                              "سؤال تجريبي طويل يفحص التفاف النص على البطاقة؟")

    no_badge_path = STATE_DIR / "_test_card_no_badge.jpg"
    imaging.build_post_image(
        headline="سؤال تجريبي طويل يفحص التفاف النص على البطاقة؟",
        category="", urgent=False, image_urls=None,
        publisher=yp.image_source_line(["الجزيرة", "Iran International"], card_cfg),
        cfg=card_cfg, out_path=no_badge_path,
    )
    check("build_post_image: يبني ملف صورة فعليًا (بلا badge)", no_badge_path.exists())
    with Image.open(no_badge_path) as im_no_badge:
        check("build_post_image: أبعاد البطاقة تطابق image.width/height",
              im_no_badge.size == (W, int(card_cfg.path("image.height", 1350))), str(im_no_badge.size))
        no_badge_pixel = im_no_badge.convert("RGB").getpixel(probe_pt)
    no_badge_path.unlink(missing_ok=True)

    badge_path = STATE_DIR / "_test_card_badge.jpg"
    imaging.build_post_image(
        headline="سؤال تجريبي طويل يفحص التفاف النص على البطاقة؟",
        category="", urgent=False, image_urls=None,
        publisher=yp.image_source_line(["الجزيرة", "Iran International"], card_cfg),
        cfg=card_cfg, out_path=badge_path, badge="تحليل",
    )
    check("build_post_image: يبني ملف صورة فعليًا (مع badge)", badge_path.exists())
    with Image.open(badge_path) as im_badge:
        badge_pixel = im_badge.convert("RGB").getpixel(probe_pt)
    badge_path.unlink(missing_ok=True)

    accent = imaging.hex_rgb(card_cfg.path("brand.accent_color", "#F0B429"))
    # مقارنة بسماحية صغيرة لا تطابق حرفي -- ضغط JPEG (quality=90) يزيح كل
    # قناة لونية ببضع درجات حتى فوق تعبئة مصمتة.
    close_to_accent = all(abs(a - b) <= 6 for a, b in zip(badge_pixel, accent))
    check("build_post_image: badge يرسم ملصقًا فعليًا (لون accent في موضعه)",
          close_to_accent, (badge_pixel, accent))
    check("build_post_image: بلا badge، الموضع نفسه يبقى بلا ملصق (لون مختلف عن accent)",
          not all(abs(a - b) <= 6 for a, b in zip(no_badge_pixel, accent)), no_badge_pixel)

    # ── _photo_search_terms: كلمات مفتاحية عربية عبر evidence.build_query،
    # لا imagesearch.keywords() التي تعيد قائمة فارغة لنص عربي محض ──
    terms = yp._photo_search_terms("هل يتجه الملف نحو تصعيد جديد في المنطقة؟",
                                   "اجتماع طارئ لمجلس الأمن بشأن الملف")
    check("_photo_search_terms: يبني عبارتين، event أولًا ثم headline",
          len(terms) == 2 and "اجتماع" in terms[0] and "الملف" in terms[1], terms)
    check("_photo_search_terms: نصّان فارغان يعيدان قائمة فارغة بلا استثناء",
          yp._photo_search_terms("", "") == [], yp._photo_search_terms("", ""))

    # ── image_query_en (Issue #941): يتصدّر القائمة حين يتوفّر -- السبب
    # الجذري لبطاقات بلا صورة كان بحثًا عربيًا محضًا في ويكيميديا/Openverse ──
    terms_en = yp._photo_search_terms(
        "هل يتجه الملف نحو تصعيد جديد في المنطقة؟",
        "اجتماع طارئ لمجلس الأمن بشأن الملف", "Strait of Hormuz tanker")
    check("_photo_search_terms: image_query_en يتصدّر القائمة حين يتوفّر",
          terms_en[0] == "Strait of Hormuz tanker" and len(terms_en) == 3, terms_en)
    check("_photo_search_terms: غياب image_query_en (None) لا يضيف شيئًا -- سلوك سابق كما هو",
          yp._photo_search_terms("عنوان", "حدث", None) == yp._photo_search_terms("عنوان", "حدث"))

    # ── _photo_candidates: بلا شبكة فعلية -- imagesearch.find_images
    # وimaging.download_image وimaging.face_score كلّها مموَّهة محليًا.
    # تعيد روابط لا صورًا محمَّلة (Issue #732 -- تُمرَّر لاحقًا إلى
    # imaging.build_post_image عبر fallback_urls). المرشَّح الأول "فيه وجه"
    # فيُستبعَد، الثاني نظيف فيبقى (المحظور: لا صورة لأي شخص) ──
    real_find_images = imagesearch.find_images
    real_download_image = imaging.download_image
    real_face_score = imaging.face_score
    download_calls: list = []

    def fake_find_images(title, cfg, limit=6, terms=None):
        return ["https://example.com/face.jpg", "https://example.com/clean.jpg"]

    def fake_download_image(url, *a, **k):
        download_calls.append(url)
        return Image.new("RGB", (800, 600), (10, 20, 30))

    imagesearch.find_images = fake_find_images  # type: ignore
    imaging.download_image = fake_download_image  # type: ignore
    try:
        # كل المرشّحين "فيهم وجه" ⇒ قائمة فارغة، لا يسقط المقال
        imaging.face_score = lambda img: 0.5  # type: ignore
        no_photo = yp._photo_candidates("عنوان", "حدث", cfg)
        check("_photo_candidates: كل المرشّحين مرفوضون (وجه ظاهر) ⇒ قائمة فارغة لا انهيار",
              no_photo == [], no_photo)

        # المرشَّح الثاني فقط نظيف ⇒ يبقى هو تحديدًا في القائمة المعادة
        download_calls.clear()

        def face_only_first(img):
            return 0.5 if len(download_calls) == 1 else 0.0

        imaging.face_score = face_only_first  # type: ignore
        photos = yp._photo_candidates("عنوان", "حدث", cfg)
        check("_photo_candidates: المرشَّح الأول (فيه وجه) يُستبعَد، والثاني (نظيف) يبقى وحده",
              photos == ["https://example.com/clean.jpg"] and download_calls ==
              ["https://example.com/face.jpg", "https://example.com/clean.jpg"], (photos, download_calls))
    finally:
        imagesearch.find_images = real_find_images  # type: ignore
        imaging.download_image = real_download_image  # type: ignore
        imaging.face_score = real_face_score  # type: ignore

    # terms فارغة (عنوان وevent كلاهما فارغ فعليًا بعد تصفية كلمات الوقف) ⇒
    # لا نداء بحث إطلاقًا
    search_calls: list = []
    imagesearch.find_images = lambda *a, **k: (search_calls.append(1) or [])  # type: ignore
    try:
        empty_terms_photos = yp._photo_candidates("", "", cfg)
    finally:
        imagesearch.find_images = real_find_images  # type: ignore
    check("_photo_candidates: عنوان وevent فارغان ⇒ قائمة فارغة بلا أي نداء بحث",
          empty_terms_photos == [] and search_calls == [], (empty_terms_photos, search_calls))

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
         "headline_selected": 0, "score": 1, "has_photo": True},
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
         # has_photo=False (طلب مراجعة على Issue #732): معاينة _photo_candidates
         # في open_review لم تجد مرشَّحًا لهذه القضية -- ⚠️ يجب أن تظهر في الـIssue
         "headline_selected": 0, "score": 6, "has_photo": False},
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
    # ── تنبيه غياب الصورة التعبيرية (Issue #732، "أخبر المراجع حين تخرج
    # البطاقة بلا صورة") -- has_photo=False يظهر ⚠️ صريحة، True لا يظهر شيئًا ──
    check("Issue المراجعة: تنبيه بلا صورة تعبيرية يظهر للمقال الذي has_photo=False",
          "بلا صورة تعبيرية متاحة حاليًا" in body, body)
    b4_start = body.index("قضية ب ثلاث قنوات؟")
    b4_end = body.index("---", b4_start)
    check("Issue المراجعة: تنبيه غياب الصورة يقع فعليًا داخل قسم القضية (ب) لا في مكان آخر",
          "بلا صورة تعبيرية" in body[b4_start:b4_end], body[b4_start:b4_end])
    c1_start = body.index("قضية ج اتفاق؟")
    c1_end = body.index("---", c1_start)
    check("Issue المراجعة: has_photo=True لا يُظهر تنبيه غياب صورة لتلك القضية",
          "بلا صورة تعبيرية" not in body[c1_start:c1_end], body[c1_start:c1_end])
    check("سطر الصحة: العدد الكلي وتوزيع الطبقات وعدّاد خلاف القنوات والتنبيهات",
          "4 مقالات" in body and "الكتل المتقاطعة: 2=2 1=2" in body and
          "خلاف قنوات=2" in body and "تنبيهات=1" in body, body[:400])
    check("Issue المراجعة: معرّفات المسودات الأربع كلها مضمّنة",
          set(review.all_draft_ids(body)) ==
          {"c00000000001", "a00000000002", "a00000000003", "b00000000004"})
    check("Issue المراجعة: نصّ التحذير الفعلي ظاهر كاملًا لا عددًا فقط",
          "تحذير رقم واحد" in body, body)
    check("Issue المراجعة: وسم الاعتماد الموحَّد `approved` مذكور صراحةً (Issue #745)",
          "`approved`" in body, body)
    check("Issue المراجعة: لا ذكر لوسم youtube-approved الملغى (Issue #745)",
          "youtube-approved" not in body, body)
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
        "## ما لا نعرفه\nنص القسم.\n\n"
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
    # source_urls حُذف نهائيًا (Issue #946) -- كان يُستخرَج من قسم "##
    # المصادر" الذي لم يعد متن المقال يحمله أصلًا منذ Issue #941 (أي عنوان
    # ## صار مرفوضًا في youtube_article._validate_article_text)، فكان
    # يعيد قائمة فارغة في كل تشغيلة. source.link يبقى فارغًا صراحة بدل
    # ذلك، وfirst_comment_for يعيد None له بحارسه القائم -- سلوك مقصود
    # (منشور تحليل عن تغطية القنوات لا منقول عن مصدر واحد).
    check("build(): بلا حقل source_urls إطلاقًا بعد حذفه",
          build_result["drafts"] and "source_urls" not in build_result["drafts"][0],
          build_result["drafts"][0].keys() if build_result["drafts"] else None)
    check("build(): source.link فارغ صراحة (لا انهيار ولا استخراج ميت)",
          build_result["drafts"] and build_result["drafts"][0]["source"]["link"] == "",
          build_result["drafts"][0].get("source") if build_result["drafts"] else None)
    check("build(): first_comment_for تعيد None لمسودة تحليل بلا رابط مصدر",
          build_result["drafts"] and
          publish_mod.first_comment_for(build_result["drafts"][0], cfg) is None,
          build_result["drafts"][0].get("source") if build_result["drafts"] else None)
    check("build(): العناوين الثلاثة المُلحَقة بالمقال وصلت كاملة إلى المسودة، والافتراضي هو الأول",
          build_result["drafts"] and build_result["drafts"][0]["headlines"] == article_headlines
          and build_result["drafts"][0]["headline_selected"] == 0,
          build_result["drafts"][0].get("headlines") if build_result["drafts"] else None)
    check("build(): الدرجة محسوبة فعليًا (لا صفر ثابت كسابقًا)",
          build_result["drafts"] and build_result["drafts"][0]["score"] ==
          yp.compute_score(["arabic", "turkish"], ["الجزيرة", "CNN Türk"], "cross_source", cfg),
          build_result["drafts"][0].get("score") if build_result["drafts"] else None)
    check("build(): بلا قسم كلمات بحث صورة في المقال ⇒ image_query_en=None على المسودة "
          "(Issue #941، مقال بلا هذا القسم لا انهيار)",
          build_result["drafts"] and build_result["drafts"][0].get("image_query_en") is None,
          build_result["drafts"][0].get("image_query_en") if build_result["drafts"] else None)
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

    # ── build(): image_query_en (Issue #941) يصل المسودة فعليًا حين يحمله
    # ملف المقال -- مقال/تاريخ منفصلان كي لا يتشابكا مع الشاهد أعلاه (الذي
    # يختبر عمدًا الحال بلا هذا القسم) ──
    iq_date_str = "2026-02-04"
    iq_articles_dir = youtube_article.ARTICLES_DIR / iq_date_str
    shutil.rmtree(iq_articles_dir, ignore_errors=True)
    iq_articles_dir.mkdir(parents=True, exist_ok=True)
    iq_article_text = (
        "# هل تتصاعد أزمة مضيق هرمز؟\n\nمتن تجريبي كافٍ.\n\n---\n"
        + youtube_article.HEADLINES_HEADER + "\n1. هل تتصاعد أزمة مضيق هرمز؟\n"
        "2. بديل ١\n3. بديل ٢\n"
        "\n---\n" + youtube_article.IMAGE_QUERY_HEADER + "\nStrait of Hormuz tanker\n"
    )
    (iq_articles_dir / "01-iq.md").write_text(iq_article_text, encoding="utf-8")
    (iq_articles_dir / "index.md").write_text(youtube_article.build_index([
        {"number": 1, "filename": "01-iq.md", "headline": "هل تتصاعد أزمة مضيق هرمز؟",
         "event": "توتر في مضيق هرمز", "layer": "a", "blocs": ["arabic"],
         "channels": ["الجزيرة"], "agreement": "agreement", "warnings_count": 0}]),
        encoding="utf-8")
    iq_build_result = yp.build(cfg, date_str=iq_date_str)
    check("build(): image_query_en وصل المسودة فعليًا من قسم المقال المذيَّل (Issue #941)",
          iq_build_result["drafts"] and
          iq_build_result["drafts"][0].get("image_query_en") == "Strait of Hormuz tanker",
          iq_build_result["drafts"][0].get("image_query_en") if iq_build_result["drafts"] else None)
    check("build(): caption خالٍ من قسم كلمات بحث الصورة (نُزع قبل حفظ المسودة)",
          iq_build_result["drafts"] and
          youtube_article.IMAGE_QUERY_HEADER not in iq_build_result["drafts"][0]["caption"],
          iq_build_result["drafts"][0]["caption"] if iq_build_result["drafts"] else None)
    shutil.rmtree(iq_articles_dir, ignore_errors=True)
    # يُحذَف من drafts/ فورًا -- وإلا يلتقطه open_review() لاحقًا كمسودة يتيمة
    # ثانية، فيكسر شاهد "المسودة اليتيمة الوحيدة" أدناه الذي يفترض مسودة
    # واحدة فقط بانتظار مراجعة عند تلك اللحظة.
    if iq_build_result["drafts"]:
        iq_loaded = store.load_draft(iq_build_result["drafts"][0]["id"])
        if iq_loaded:
            iq_loaded[0].unlink(missing_ok=True)

    # open_review() -- بعد "رفع" الصور (محاكاة: لا رفع فعلي في الاختبار، لكن
    # الملفات موجودة محليًا فعلًا وهذا ما يقرؤه open_review())
    created_issues: list = []
    real_create_issue = review.create_issue

    def fake_create_issue(title, body, labels=None):
        created_issues.append({"title": title, "body": body, "labels": labels})
        return {"number": 999, "html_url": "https://example.com/issues/999"}

    # imagesearch.find_images مموَّهة هنا لتعيد رابطًا نظيفًا واحدًا -- open_review()
    # يبحث الآن مسبقًا عن معاينة صورة تعبيرية لكل مقال قبل فتح الـIssue (Issue
    # #732)؛ imaging.download_image/face_score تبقيان على تمويه install_fakes()
    # القائم (تنجح دومًا، ولا وجه يُكتشَف -- لا cv2 في بيئة الاختبار).
    real_find_images_review = imagesearch.find_images
    imagesearch.find_images = lambda title, cfg, limit=6, terms=None: (
        ["https://example.com/analysis-photo.jpg"])  # type: ignore
    review.create_issue = fake_create_issue  # type: ignore
    try:
        review_result = yp.open_review(cfg)
    finally:
        review.create_issue = real_create_issue  # type: ignore
        imagesearch.find_images = real_find_images_review  # type: ignore

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
    check("open_review(): معاينة صورة تعبيرية وُجدت ⇒ has_photo=True على المسودة المُعادة",
          review_result["drafts"][0].get("has_photo") is True, review_result["drafts"][0])
    check("open_review(): معاينة صورة موجودة ⇒ لا تنبيه غياب صورة في نص الـIssue",
          "بلا صورة تعبيرية" not in created_issues[0]["body"], created_issues[0]["body"])

    loaded2 = store.load_draft(build_result["drafts"][0]["id"])
    check("open_review(): review_issue ثُبِّت على المسودة فور فتح الـIssue",
          loaded2 is not None and loaded2[1].get("review_issue") == 999,
          loaded2[1] if loaded2 else None)
    check("open_review(): has_photo محفوظ فعليًا على القرص لا في الذاكرة وحدها",
          loaded2 is not None and loaded2[1].get("has_photo") is True,
          loaded2[1] if loaded2 else None)

    # نداء ثانٍ: المسودة مربوطة بـIssue سابق الآن، فلا تُلتقَط ولا يُفتَح Issue جديد
    second_call = yp.open_review(cfg)
    check("open_review(): مسودة مربوطة بـIssue سابق لا تُلتقَط في نداء ثانٍ",
          second_call["issue"] is None and second_call["drafts"] == [], second_call)

    # ── ensure_title_card: البطاقة تُبنى الآن فقط -- بعد الاعتماد، للمختار
    # فقط (Issue #680)، بالعنوان البديل الثاني لا الافتراضي، كي يثبت أن
    # الاختيار الفعلي هو ما يصل البطاقة والـcaption معًا ──
    from src import cards

    card_path, card_draft = store.load_draft(build_result["drafts"][0]["id"])
    card_draft["headline_selected"] = 1
    # imagesearch.find_images مموَّهة هنا لتعيد صفر نتائج -- بحث حقيقي بلا
    # شبكة فعلية، يغطّي بالضبط ما طلبته المراجعة: «إن لم يجد البحث صورة
    # مناسبة، ارجع إلى البطاقة النصية الحالية بدل إسقاط المقال» (Issue #680).
    # cards.find_images (Issue #941، مرجع مختلف عن imagesearch.find_images
    # داخل cards.py -- import مباشر) تُموَّه أيضًا هنا: منذ حذف
    # allow_search_fallback=False من نداء cards.ensure في ensure_title_card،
    # قائمة fallback_urls الفارغة تُطلق محاولة ثانية عبرها فعليًا، وبلا هذا
    # التمويه كانت لتصل شبكة حقيقية.
    real_find_images_ctc = imagesearch.find_images
    real_cards_find_images = cards.find_images
    photo_search_calls: list = []
    fallback_search_calls: list = []

    def fake_find_images_empty(title, cfg, limit=6, terms=None):
        photo_search_calls.append(terms)
        return []

    def fake_cards_find_images_empty(term, cfg):
        fallback_search_calls.append(term)
        return []

    # Issue #1123: صورة الخبر صارت تسبق الحرة، وفاكات install_fakes تنجحها
    # دومًا -- تُعطَّل هنا كي تبقى هذه الفحوص على سلسلة الحرة (الدرجة الثالثة)
    # كما صُمِّمت؛ ترتيب الدرجات نفسه يُفحص في test_youtube_image_news_photo.
    real_npc_ctc = youtube_extract.news_photo_candidates
    youtube_extract.news_photo_candidates = lambda *a, **k: []  # type: ignore
    imagesearch.find_images = fake_find_images_empty  # type: ignore
    cards.find_images = fake_cards_find_images_empty  # type: ignore
    try:
        ok_card = yp.ensure_title_card(card_path, card_draft, cfg)
    finally:
        imagesearch.find_images = real_find_images_ctc  # type: ignore
        cards.find_images = real_cards_find_images  # type: ignore
        youtube_extract.news_photo_candidates = real_npc_ctc  # type: ignore
    check("ensure_title_card: يبني البطاقة بنجاح ويعيد True", ok_card, ok_card)
    check("ensure_title_card: بحثت فعليًا عن صورة تعبيرية بكلمات event/headline",
          photo_search_calls and photo_search_calls[0] and
          "اجتماع" in photo_search_calls[0][0], photo_search_calls)
    check("ensure_title_card: المحاولة الأولى فارغة ⇒ محاولة ثانية عامة عبر cards.ensure "
          "(Issue #941، allow_search_fallback لم يعد مُلغًى) بالعنوان العربي المختار "
          "إذ لا image_query_en على هذه المسودة",
          fallback_search_calls == [article_headlines[1]], fallback_search_calls)
    check("ensure_title_card: بحث فارغ ⇒ has_photo=False (خلفية مصممة، لا انهيار)",
          card_draft.get("has_photo") is False, card_draft.get("has_photo"))
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
    check("ensure_title_card: has_photo النهائي (الحقيقي بعد البناء) محفوظ أيضًا",
          persisted is not None and persisted[1].get("has_photo") is False,
          persisted[1] if persisted else None)
    check("ensure_title_card: image_info محفوظ فعليًا (Issue #752) — يطابق has_photo، manual=False",
          persisted is not None and persisted[1].get("image_info", {}).get("used_original") is False
          and persisted[1]["image_info"].get("manual") is False,
          persisted[1].get("image_info") if persisted else None)

    # نداء ثانٍ بعد بناء البطاقة فعليًا: يعيد True فورًا بلا إعادة بناء
    # (الملف موجود مسبقًا -- انظر فحص `existing` في ensure_title_card)
    rebuilt_mtime = built_img.stat().st_mtime
    ok_card2 = yp.ensure_title_card(card_path, card_draft, cfg)
    check("ensure_title_card: نداء ثانٍ لا يعيد البناء إن كانت البطاقة موجودة فعلًا",
          ok_card2 and built_img.stat().st_mtime == rebuilt_mtime, None)

    # ── ensure_title_card: image_query_en (Issue #941) يصل كلا المحاولتين
    # -- الأولى (_photo_candidates، عربية+إنجليزية معًا) والثانية (العامة
    # عبر cards.ensure، search_term=) -- مسودة جديدة مستقلّة كي لا تصطدم
    # بفحص "بطاقة موجودة مسبقًا" أعلاه ──
    query_draft_id = "eq00000000aa"
    query_draft = {
        "id": query_draft_id, "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending", "origin": "analysis",
        "title": "سؤال تجريبي عن قضية إنجليزية؟", "tier": "a", "blocs": ["arabic"],
        "channels": ["الجزيرة"], "agreement": "agreement", "event": "حدث تجريبي",
        "image_query_en": "Strait of Hormuz tanker",
        "warnings": [], "source_urls": [], "run_date": date_str,
        "caption": "# سؤال تجريبي عن قضية إنجليزية؟\n\nمتن تجريبي.",
        "headlines": ["سؤال تجريبي عن قضية إنجليزية؟"], "headline_selected": 0,
        "arabic": {"post_title": "سؤال تجريبي عن قضية إنجليزية؟", "urgent": False,
                   "category": "تحليل"},
        "source": {"link": "", "publishers": ["الجزيرة"]},
        "score": 1.0,
    }
    store.save_draft(query_draft)
    query_path, _ = store.load_draft(query_draft_id)

    photo_calls_en: list = []
    fallback_calls_en: list = []
    imagesearch.find_images = (  # type: ignore
        lambda title, cfg, limit=6, terms=None: (photo_calls_en.append(terms) or []))
    cards.find_images = (  # type: ignore
        lambda term, cfg: (fallback_calls_en.append(term) or []))
    youtube_extract.news_photo_candidates = lambda *a, **k: []  # type: ignore
    try:
        ok_query = yp.ensure_title_card(query_path, query_draft, cfg)
    finally:
        imagesearch.find_images = real_find_images_ctc  # type: ignore
        cards.find_images = real_cards_find_images  # type: ignore
        youtube_extract.news_photo_candidates = real_npc_ctc  # type: ignore

    check("ensure_title_card: image_query_en يصل المحاولة الأولى (_photo_candidates) "
          "أول عبارات البحث", photo_calls_en and photo_calls_en[0] and
          photo_calls_en[0][0] == "Strait of Hormuz tanker", photo_calls_en)
    check("ensure_title_card: image_query_en نفسه يصل المحاولة الثانية العامة "
          "(cards.ensure عبر search_term=) حين تعود الأولى فارغة",
          fallback_calls_en == ["Strait of Hormuz tanker"], fallback_calls_en)
    check("ensure_title_card: تبني البطاقة بنجاح رغم فراغ كل عمليات البحث (خلفية مصممة)",
          ok_query, ok_query)

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

    # مسودتان بقيتا pending بلا review_issue (_hex_id(3)/_hex_id(4)، السيناريو
    # الأول) وبلا حقل title أصلًا (بنية مبسَّطة لاختبار سقف/تباعد
    # publish_approved وحده -- لا شكل مسودة حقيقي) -- تُحذَف هنا فورًا كي لا
    # يلتقطها youtube_publish.open_review() لاحقًا في هذا الملف (Issue #1104:
    # publish.cmd_youtube_selection يستدعيها فعليًا بعد الكتابة) فتنهار على
    # d["title"] المفقود.
    for i in range(8):
        found_leftover = store.load_draft(_hex_id(i))
        if found_leftover:
            found_leftover[0].unlink(missing_ok=True)

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
    check("publish_approved: وسم approved الموحَّد يُزال عند عدم وجود اعتماد (Issue #745)",
          removed_labels == ["approved"], removed_labels)

    # ── نشر فعلي (publish.publish_one، لا مموَّهة) لمسودة تحليل بلا
    # source.link -- ينجح بلا تعليق أول (Issue #946: source.link فارغ صراحة
    # بعد حذف extract_source_lines الميتة، وfirst_comment_for يعيد None
    # لغيابه بحارسها القائم بلا أي تعديل عليها) ──
    real_publish_photo = facebook.publish_photo
    real_publish_root = publish_mod.ROOT
    photo_calls: list = []

    def fake_publish_photo(image_path, caption, api_version, first_comment=None):
        photo_calls.append(first_comment)
        return {"url": "https://fb.example/analysis", "id": "1"}

    live_draft = {
        "id": "live00000001", "status": "pending", "origin": "analysis",
        "caption": "متن مقال تحليلي.",
        "arabic": {"post_title": "عنوان تحليلي", "urgent": False, "category": "تحليل"},
        "source": {"link": "", "publishers": ["الجزيرة", "CNN Türk"]},
        "image": f"drafts/{date_str}/live00000001.jpg",
    }
    live_path = store.save_draft(live_draft)
    # publish_one يقرأ ROOT / draft["image"] حرفيًا (خلافًا لـensure_title_card
    # الذي يقرأ من DRAFTS_DIR) -- توجيه ROOT إلى DRAFTS_DIR.parent هنا (نفس
    # ما تفعله test_publish_builds_cards_at_approval في test_review.py) كي لا
    # يكتب هذا الاختبار صورة تجريبية داخل drafts/ الفعلي بالمستودع.
    publish_mod.ROOT = DRAFTS_DIR.parent
    img_path = DRAFTS_DIR / date_str / "live00000001.jpg"
    img_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 40), (5, 5, 5)).save(img_path, "JPEG")

    facebook.publish_photo = fake_publish_photo  # type: ignore
    reset_last_publish()
    try:
        ok, line = publish_mod.publish_one(live_path, live_draft, cfg)
    finally:
        facebook.publish_photo = real_publish_photo
        publish_mod.ROOT = real_publish_root

    check("publish_one: نشر مسودة تحليل بلا source.link ينجح", ok, line)
    check("publish_one: بلا تعليق أول -- first_comment الممرَّر لـpublish_photo هو None",
          photo_calls == [None], photo_calls)
    check("publish_one: حالة المسودة published بعد النشر الفعلي",
          store.load_draft(live_draft["id"])[1]["status"] == "published",
          store.load_draft(live_draft["id"])[1].get("status"))

    # ── إعدادات config.yaml (Issue #676) ──
    check("config: youtube.publish.max_per_run = 3",
          cfg.path("youtube.publish.max_per_run") == 3)
    check("config: youtube.publish.spacing_minutes = 40",
          cfg.path("youtube.publish.spacing_minutes") == 40)
    check("config: youtube.image.bloc_labels يغطي الكتل الأربع",
          set(cfg.path("youtube.image.bloc_labels", {}).keys()) ==
          {"arabic", "turkish", "persian", "israeli"})
    check("config: youtube.image.use_photo مفعَّل افتراضيًا (طلب المراجعة على Issue #680)",
          cfg.path("youtube.image.use_photo") is True)
    check("config: youtube.image.source_line_template موجود ويحوي {channels} (Issue #732)",
          "{channels}" in (cfg.path("youtube.image.source_line_template") or ""))
    check("config: cards.analysis.source_max_chars = 48 (Issue #1106)",
          cfg.path("cards.analysis.source_max_chars") == 48)

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

    # ── Issue #1104: publish.cmd_youtube_selection -- الكتابة الفعلية عند
    # اعتماد Issue اختيار المواضيع. يغطّي: سقف youtube.article.max_per_run،
    # بوابة الصورة مطبَّقة على المعلَّم وحده (موضوع معلَّم بلا صورة لا
    # يُكتَب ويُسجَّل سبب التخطّي)، عدم الكتابة مزدوجًا عند تكرار وسم
    # approved، وإكمال الباقي بعد إعادة الوسم. ──
    class _Block2:
        def __init__(self, type_, input_=None, text=None):
            self.type, self.input, self.text = type_, input_, text

    class _Resp2:
        def __init__(self, content, stop_reason="end_turn", usage=None):
            self.content, self.stop_reason, self.usage = content, stop_reason, usage

    class _Messages2:
        def __init__(self, responses):
            self._responses = list(responses)
            self.calls: list = []

        def create(self, **kw):
            self.calls.append(kw)
            return self._responses.pop(0)

    class _Client2:
        def __init__(self, responses):
            self.messages = _Messages2(responses)

    sel2_topics = [
        {"title": "موضوع بصورة أول", "event": "حدث ١", "layer": "a",
         "blocs": ["arabic", "turkish"], "channels": ["الجزيرة", "CNN Türk"],
         "agreement": "cross_source", "point_ids": [0, 1]},
        {"title": "موضوع بلا صورة متاحة", "event": "حدث ٢", "layer": "a",
         "blocs": ["arabic", "turkish"], "channels": ["الجزيرة", "CNN Türk"],
         "agreement": "cross_source", "point_ids": [0, 1]},
        {"title": "موضوع بصورة ثانٍ فوق السقف", "event": "حدث ٣", "layer": "a",
         "blocs": ["arabic", "turkish"], "channels": ["الجزيرة", "CNN Türk"],
         "agreement": "cross_source", "point_ids": [0, 1]},
        {"title": "موضوع لم يُختر", "event": "حدث ٤", "layer": "a",
         "blocs": ["arabic", "turkish"], "channels": ["الجزيرة", "CNN Türk"],
         "agreement": "cross_source", "point_ids": [0, 1]},
    ]
    sel2_points = [
        {"video_id": "sw0", "bloc": "arabic", "channel": "الجزيرة", "speaker": "متحدث",
         "statement": "قول", "quote_arabic": "اقتباس", "type": "fact",
         "video_title": "فيديو", "video_url": "https://youtube.com/watch?v=sw0",
         "timestamp": 1},
        {"video_id": "sw1", "bloc": "turkish", "channel": "CNN Türk", "speaker": "متحدث٢",
         "statement": "قول٢", "quote_arabic": "اقتباس٢", "type": "fact",
         "video_title": "فيديو٢", "video_url": "https://youtube.com/watch?v=sw1",
         "timestamp": 2},
    ]
    ycl2 = youtube_cluster
    ycl2.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    ycl2.TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    sel2_points_path = ycl2.POINTS_DIR / "2099-09-01.json"
    sel2_topics_path = ycl2.TOPICS_DIR / "2099-09-01.json"
    sel2_points_path.write_text(json.dumps({"points": sel2_points}, ensure_ascii=False),
                                encoding="utf-8")
    sel2_topics_path.write_text(
        json.dumps({"run_date": "2099-09-01", "topics": sel2_topics}, ensure_ascii=False),
        encoding="utf-8")

    sel2_cfg = load_config()
    sel2_cfg.setdefault("youtube", {}).setdefault("article", {})["max_per_run"] = 2

    sel2_issues: dict = {}
    issue_counter = {"n": 6000}

    def _fake_create_issue2(title, body, labels=None):
        issue_counter["n"] += 1
        num = issue_counter["n"]
        sel2_issues[num] = {"title": title, "body": body, "labels": labels}
        return {"number": num, "html_url": f"https://example.com/issues/{num}"}

    comments2: list = []
    removed_labels2: list = []
    closed_issues2: list = []

    real_create_issue2 = review.create_issue
    real_ensure_labels2 = review.ensure_labels
    real_comment2 = review.comment
    real_remove_label2 = review.remove_label
    real_close_issue2 = review.close_issue
    real_repo2 = os.environ.get("GITHUB_REPOSITORY")
    real_photo_candidates2 = youtube_extract.photo_candidates
    real_news_photo_available2 = youtube_extract.news_photo_available
    real_find_images2 = imagesearch.find_images

    review.create_issue = _fake_create_issue2  # type: ignore
    review.ensure_labels = lambda: None  # type: ignore
    review.comment = lambda issue_number, text: comments2.append((issue_number, text))  # type: ignore
    review.remove_label = lambda issue_number, label: removed_labels2.append((issue_number, label))  # type: ignore
    review.close_issue = lambda issue_number: closed_issues2.append(issue_number)  # type: ignore
    os.environ["GITHUB_REPOSITORY"] = "user/trendnews"
    youtube_extract.photo_candidates = lambda *a, **k: (
        [] if "بلا صورة" in a[0] else ["https://example.com/photo.jpg"])  # type: ignore
    youtube_extract.news_photo_available = lambda *a, **k: False  # type: ignore
    imagesearch.find_images = lambda *a, **k: []  # type: ignore

    seen_backup_sel2 = ycl2.SEEN_PATH.read_text(encoding="utf-8") if ycl2.SEEN_PATH.exists() else None
    try:
        sel2_result = ycl2.open_selection(sel2_cfg, date_str="2099-09-01")
        sel_issue_num = sel2_result["issue"]["number"]
        selection_body = sel2_issues[sel_issue_num]["body"]

        # علّم الثلاثة الأولى (بصورة أول، بلا صورة، بصورة ثانٍ فوق السقف)
        # ولا تعلّم الرابع (لم يُختر).
        chosen2 = [sel2_result["topics"][0]["id"], sel2_result["topics"][1]["id"],
                  sel2_result["topics"][2]["id"]]
        approve_body2 = selection_body
        for cid in chosen2:
            approve_body2 = re.sub(
                r"- \[ \](.*?)<!-- topic:" + cid + r" -->",
                lambda m, cid=cid: f"- [x]{m.group(1)}<!-- topic:{cid} -->",
                approve_body2)

        # الدفعة الأولى (سقف ٢): الأول ناجح (نداءا نموذج: مقال + عناوين)،
        # الثاني تتخطّاه بوابة الصورة *قبل* أي نداء نموذج، الثالث فوق السقف
        # فلا يُحاوَل بعد -- عميل بردّين فقط يكفي ويُثبت عدم إهدارهما.
        w1_article = ("# هل يقع هذا التطوّر فعلًا؟\n\n" + "كلمة " * 260 +
                     "\n\nمرجّح أن يقع هذا التطوّر فعلًا.")
        batch1_client = _Client2([
            _Resp2([_Block2("text", text=w1_article)]),
            _Resp2([_Block2("tool_use", input_={"headlines": [
                "هل يقع هذا التطوّر؟", "بديل ١", "بديل ٢"]})]),
        ])

        result1 = publish_mod.cmd_youtube_selection(sel_issue_num, approve_body2, sel2_cfg,
                                                     client=batch1_client)
        check("cmd_youtube_selection(): الدفعة الأولى تُعيد 0 (نجاح)", result1 == 0, result1)
        check("cmd_youtube_selection(): نداءا نموذج فقط في الدفعة الأولى (مقال+عناوين للأول وحده)",
              len(batch1_client.messages.calls) == 2, batch1_client.messages.calls)

        report1 = comments2[-1][1]
        check("cmd_youtube_selection(): تقرير الدفعة الأولى يذكر الموضوع الناجح "
              "(بعنوانه المكتوب فعليًا) والمتخطّى لغياب الصورة والباقي فوق السقف "
              "وعدد غير المختار",
              "هل يقع هذا التطوّر؟" in report1 and "لا صورة متاحة" in report1 and
              "موضوع بصورة ثانٍ فوق السقف" in report1 and "🚫" in report1,
              report1)
        check("cmd_youtube_selection(): سقف الدفعة تجاوَزه موضوع واحد ⇒ وسم approved أُزيل "
              "والـIssue لم يُغلَق",
              removed_labels2 == [(sel_issue_num, "approved")] and
              closed_issues2 == [], (removed_labels2, closed_issues2))

        persisted2 = json.loads(sel2_topics_path.read_text(encoding="utf-8"))
        status_by_title = {t["title"]: t.get("selection_status") for t in persisted2["topics"]}
        check("cmd_youtube_selection(): حالة كل موضوع بعد الدفعة الأولى صحيحة على القرص",
              status_by_title == {
                  "موضوع بصورة أول": "attempted", "موضوع بلا صورة متاحة": "attempted",
                  "موضوع بصورة ثانٍ فوق السقف": "selected", "موضوع لم يُختر": "unselected"},
              status_by_title)

        # مسودة الموضوع الناجح كُتبت فعليًا في drafts/ بمعرّف ثابت (مشتقّ من
        # id الموضوع)، origin="analysis"، وبلا حقل image (Issue #680 -- تُبنى
        # لاحقًا عند الاعتماد لا هنا.
        import hashlib as _hashlib_sel
        written_topic_id = sel2_result["topics"][0]["id"]
        written_draft_id = _hashlib_sel.sha1(
            f"youtube-selection:2099-09-01:{written_topic_id}".encode("utf-8")).hexdigest()[:12]
        found_draft = store.load_draft(written_draft_id)
        check("cmd_youtube_selection(): مسودة الموضوع الناجح كُتبت فعليًا في drafts/",
              found_draft is not None, written_draft_id)
        if found_draft:
            check("cmd_youtube_selection(): المسودة المكتوبة origin=analysis وبلا حقل image",
                  store.origin_of(found_draft[1]) == "analysis" and "image" not in found_draft[1],
                  found_draft[1])

        # إعادة اعتماد نفس الـIssue (تكرار وسم approved لمتابعة الباقي فوق
        # السقف، Issue #961/#1008): الأول/الثاني صارا attempted فلن يُعاد
        # النظر فيهما أو كتابتهما مجددًا -- عميل هذه الدفعة يحمل ردّين فقط
        # (مقال+عناوين)، فاستهلاكهما بالضبط يثبت أن الثالث وحده كُتب لا هو
        # وأحد سابقيه معًا (لو أُعيد الأول/الثاني لاستُنفد العميل بردّين
        # إضافيين مفقودين وانهار الاختبار).
        w3_article = ("# هل يستمر هذا التطوّر الثاني؟\n\n" + "كلمة " * 260 +
                     "\n\nمرجّح أن يستمر هذا التطوّر الثاني.")
        batch2_client = _Client2([
            _Resp2([_Block2("text", text=w3_article)]),
            _Resp2([_Block2("tool_use", input_={"headlines": [
                "هل يستمر هذا التطوّر الثاني؟", "بديل ١", "بديل ٢"]})]),
        ])
        result2 = publish_mod.cmd_youtube_selection(sel_issue_num, approve_body2, sel2_cfg,
                                                     client=batch2_client)
        check("cmd_youtube_selection(): إعادة الوسم تكمل الباقي فوق السقف (نداءا نموذج للثالث)",
              len(batch2_client.messages.calls) == 2, batch2_client.messages.calls)
        check("cmd_youtube_selection(): لا شيء يبقى بعد إكمال الدفعة ⇒ الـIssue أُغلق",
              sel_issue_num in closed_issues2, closed_issues2)

        # مسار --urgent-only لا يفعل شيئًا بهذا الـIssue (نصّ الـIssue #1104
        # الصريح: يعمل في مسار normal فقط) -- عبر publish.main فعليًا، بنفس
        # حارس failed-review (المسار السريع لا يعالج الإحياء) المطابق شكلًا.
        import sys as _sys
        selection_calls: list = []
        real_cmd_selection = publish_mod.cmd_youtube_selection
        real_fetch_issue = publish_mod.fetch_issue
        real_argv = _sys.argv
        publish_mod.cmd_youtube_selection = (  # type: ignore
            lambda *a, **k: selection_calls.append((a, k)) or 0)
        publish_mod.fetch_issue = lambda issue_number: {  # type: ignore
            "body": approve_body2, "labels": [{"name": "youtube-selection"}]}
        try:
            _sys.argv = ["publish.py", "--issue", str(sel_issue_num), "--urgent-only"]
            publish_mod.main()
            check("main(): --urgent-only لا يستدعي cmd_youtube_selection إطلاقًا لهذا الوسم",
                  selection_calls == [], selection_calls)

            _sys.argv = ["publish.py", "--issue", str(sel_issue_num), "--skip-urgent"]
            publish_mod.main()
            check("main(): --skip-urgent (المسار العادي) يستدعي cmd_youtube_selection فعليًا",
                  len(selection_calls) == 1, selection_calls)
        finally:
            publish_mod.cmd_youtube_selection = real_cmd_selection  # type: ignore
            publish_mod.fetch_issue = real_fetch_issue  # type: ignore
            _sys.argv = real_argv
    finally:
        review.create_issue = real_create_issue2  # type: ignore
        review.ensure_labels = real_ensure_labels2  # type: ignore
        review.comment = real_comment2  # type: ignore
        review.remove_label = real_remove_label2  # type: ignore
        review.close_issue = real_close_issue2  # type: ignore
        youtube_extract.photo_candidates = real_photo_candidates2  # type: ignore
        youtube_extract.news_photo_available = real_news_photo_available2  # type: ignore
        imagesearch.find_images = real_find_images2  # type: ignore
        if real_repo2 is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = real_repo2
        sel2_points_path.unlink(missing_ok=True)
        sel2_topics_path.unlink(missing_ok=True)
        if seen_backup_sel2 is None:
            ycl2.SEEN_PATH.unlink(missing_ok=True)
        else:
            ycl2.SEEN_PATH.write_text(seen_backup_sel2, encoding="utf-8")


def _news_photo_draft(draft_id: str, run_date: str = "2026-03-01") -> dict:
    """مسودة تحليل صالحة الحقول (بلا حقل image -- Issue #680) لاختبارات
    صورة الخبر عن الموضوع أدناه، بنفس بنية youtube_publish.build_draft
    الفعلية."""
    return {
        "id": draft_id, "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending", "origin": "analysis",
        "title": "سؤال بطاقة اختبار صورة الخبر؟", "tier": "a", "blocs": ["arabic"],
        "channels": ["الجزيرة"], "agreement": "agreement",
        "event": "حدث اختبار صورة الخبر", "image_query_en": None,
        "warnings": [], "caption": "# سؤال بطاقة اختبار صورة الخبر؟\n\nمتن تجريبي.",
        "run_date": run_date, "headlines": ["سؤال بطاقة اختبار صورة الخبر؟"],
        "headline_selected": 0,
        "arabic": {"post_title": "سؤال بطاقة اختبار صورة الخبر؟", "urgent": False,
                   "category": "تحليل"},
        "source": {"link": "", "publishers": ["الجزيرة"]}, "score": 1.0,
        "source_videos": [],
    }


def test_youtube_image_news_photo() -> None:
    """مقال تحليلي بلا صورة حرة الترخيص -- صورة خبر صحفي عن الموضوع نفسه
    بدل خلفية الفيديو الملغاة (Issue #1095، تراجع محسوم عن Issue #1092:
    محاولتان لرسم خلفية معتّمة فشلتا بصريًا، وصورة الفيديو ليست صورة الحدث
    بل صورة قناة تتحدث عنه). الدرجات الآن (قُلب ترتيبها في Issue #1123): صورة
    خبر عن الموضوع (تُرسم صورةً رئيسية عادية تمامًا، بلا فحص وجه) ← صورة حرة
    بلا وجه ← امتناع تام عن الصياغة.

    imagesearch.find_images/cards.find_images (بحث حر) وimaging.download_image/
    face_score (تحميل/فحص وجه) كلّها مموَّهة محليًا داخل كل سيناريو على حدة
    -- نفس أسلوب test_youtube_publish أعلاه. سيناريو ٢ (والتحقّق من بوابة
    run() فيه) لا يمويه شبكة محليًا لصورة الخبر نفسها: يعتمد الفاكات العامة
    (install_fakes -- خلاصة RSS ثابتة + og:image صالح + تحميل ناجح دومًا)
    بما أن صورة الخبر الآن بحث RSS حقيقي البنية (request.search_feeds/
    sources.enrich_image) لا مجرّد رابط مصغّرة ثابت -- لا نداء شبكة حقيقي
    إطلاقًا مع ذلك."""
    from src import cards, setimage
    yp = youtube_publish
    cfg = load_config()

    real_find_images = imagesearch.find_images
    real_cards_find_images = cards.find_images
    real_download_image = imaging.download_image
    real_face_score = imaging.face_score

    def _restore() -> None:
        imagesearch.find_images = real_find_images  # type: ignore
        cards.find_images = real_cards_find_images  # type: ignore
        imaging.download_image = real_download_image  # type: ignore
        imaging.face_score = real_face_score  # type: ignore

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── ١) المزوّدان متاحان (Issue #1123، الترتيب مقلوب): تُستعمل صورة الخبر،
    # ومزوّد الصور الحرة لا يُستدعى إطلاقًا (عدّ نداءات imagesearch.find_images
    # وcards.find_images معًا -- الكسل في الاتجاه الثاني) ──
    d1 = _news_photo_draft("np0000000001")
    store.save_draft(d1)
    path1, d1 = store.load_draft(d1["id"])
    free_calls_1: list = []
    try:
        imagesearch.find_images = lambda *a, **k: (free_calls_1.append(1) or ["https://example.com/free.jpg"])  # type: ignore
        cards.find_images = lambda *a, **k: (free_calls_1.append(2) or ["https://example.com/free.jpg"])  # type: ignore
        imaging.download_image = lambda *a, **k: Image.new("RGB", (800, 600), (10, 90, 200))  # type: ignore
        imaging.face_score = lambda img: 0.0  # type: ignore
        ok1 = yp.ensure_title_card(path1, d1, cfg)
    finally:
        _restore()
    check("١) المزوّدان متاحان: البطاقة تُبنى بنجاح", ok1, ok1)
    check("١) المزوّدان متاحان: تُستعمل صورة الخبر (kind == 'news_photo')",
          d1.get("image_info", {}).get("kind") == "news_photo", d1.get("image_info"))
    check("١) المزوّدان متاحان: ليست صورة حرة (illustrative=False، used_original=False)",
          d1.get("image_info", {}).get("illustrative") is False
          and d1.get("image_info", {}).get("used_original") is False, d1.get("image_info"))
    check("١) المزوّدان متاحان: مزوّد الصور الحرة لا يُستدعى إطلاقًا (صفر نداء)",
          free_calls_1 == [], free_calls_1)

    # ── ٢) لا صورة حرة، وخبر بصورة صالحة: البطاقة تُبنى بصورة رئيسية عادية،
    # وimage_info يميّزها صراحةً، والمقال يُصاغ فعليًا (بوابة run() لا تمتنع).
    # الفاكات العامة تكفي لإنجاح الدرجة الثانية -- لا تمويه شبكة محلي هنا،
    # فقط تعطيل الدرجة الأولى (find_images) ──
    d2 = _news_photo_draft("np0000000002")
    store.save_draft(d2)
    path2, d2 = store.load_draft(d2["id"])
    try:
        imagesearch.find_images = lambda *a, **k: []  # type: ignore
        cards.find_images = lambda *a, **k: []  # type: ignore
        ok2 = yp.ensure_title_card(path2, d2, cfg)
    finally:
        _restore()
    check("٢) لا صورة حرة + خبر بصورة صالحة: البطاقة تُبنى بنجاح", ok2, ok2)
    check("٢) لا صورة حرة + خبر بصورة صالحة: image_info.kind == 'news_photo'",
          d2.get("image_info", {}).get("kind") == "news_photo", d2.get("image_info"))
    check("٢) لا صورة حرة + خبر بصورة صالحة: ناشر صورة الخبر مسجَّل",
          bool(d2.get("image_info", {}).get("news_photo_publisher")), d2.get("image_info"))
    check("٢) لا صورة حرة + خبر بصورة صالحة: used_original يبقى False "
          "(ليست صورة الناشر الأصلية للمقال)",
          d2.get("image_info", {}).get("used_original") is False, d2.get("image_info"))
    check("٢) لا صورة حرة + خبر بصورة صالحة: has_photo=False (نفس المعيار القائم)",
          d2.get("has_photo") is False, d2.get("has_photo"))

    # نفس السيناريو، لكن من زاوية بوابة youtube_article.run() قبل الصياغة --
    # المقال *يُصاغ* فعليًا (لا امتناع) لأن has_news_photo=True يكفي البوابة.
    # جولة run() كاملة حقيقية (لا محاكاة جزئية) -- عدّ نداءات النموذج يثبت
    # أن draft_article/generate_headlines استُدعيا فعلًا لا أن البوابة أسقطتهما.
    topic_news_photo = {"title": "قضية بلا صورة حرة لكن بخبر بصورة صالحة",
                        "event": "حدث تجريبي", "layer": "a",
                        "blocs": ["arabic", "turkish"],
                        "channels": ["الجزيرة", "CNN Türk"], "agreement": "agreement",
                        "point_ids": [0, 1]}
    points_news_photo = [
        {"video_id": "vidnp1", "bloc": "arabic", "channel": "الجزيرة", "speaker": "ناطق",
         "statement": "قول تجريبي", "quote_arabic": "اقتباس", "type": "fact",
         "video_title": "فيديو", "video_url": "https://youtube.com/watch?v=vidnp1",
         "timestamp": 3},
        {"video_id": "vidnp1", "bloc": "turkish", "channel": "CNN Türk", "speaker": "متحدث",
         "statement": "قول تجريبي ٢", "quote_arabic": "اقتباس ٢", "type": "fact",
         "video_title": "فيديو ٢", "video_url": "https://youtube.com/watch?v=vidnp1",
         "timestamp": 4},
    ]

    class _NPResp:
        def __init__(self, text: str = "", input_: dict | None = None) -> None:
            class _Blk:
                pass
            blk = _Blk()
            if input_ is not None:
                blk.type = "tool_use"  # type: ignore[attr-defined]
                blk.input = input_  # type: ignore[attr-defined]
            else:
                blk.type = "text"  # type: ignore[attr-defined]
                blk.text = text  # type: ignore[attr-defined]
            self.content = [blk]
            self.stop_reason = "end_turn"
            self.usage = None

    class _NPMessages:
        def __init__(self, responses: list) -> None:
            self._responses = list(responses)
            self.calls: list = []

        def create(self, **kw):
            self.calls.append(kw)
            return self._responses.pop(0)

    class _NPClient:
        def __init__(self, responses: list) -> None:
            self.messages = _NPMessages(responses)

    article_text_np = (
        "# هل يقع هذا التطور فعلًا؟\n\n" + "كلمة " * 260
        + "\n\nمرجّح أن يقع هذا التطور فعلًا."
    )
    np_run_client = _NPClient([
        _NPResp(text=article_text_np),
        _NPResp(input_={"headlines": ["هل يقع هذا التطور؟", "بديل ١", "بديل ٢"]}),
    ])

    ycl2 = youtube_cluster
    ycl2.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    ycl2.TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    points_path2 = ycl2.POINTS_DIR / "2099-06-02.json"
    topics_path2 = ycl2.TOPICS_DIR / "2099-06-02.json"
    points_path2.write_text(json.dumps({"points": points_news_photo}, ensure_ascii=False),
                            encoding="utf-8")
    topics_path2.write_text(json.dumps({"run_date": "2099-06-02", "topics": [topic_news_photo]},
                                       ensure_ascii=False), encoding="utf-8")
    seen_backup_r2 = ycl2.SEEN_PATH.read_text(encoding="utf-8") if ycl2.SEEN_PATH.exists() else None
    try:
        imagesearch.find_images = lambda *a, **k: []  # type: ignore
        # Issue #1104: topics_override صراحة (انظر تعليق مشابه أعلى الملف)
        result2 = youtube_article.run(cfg, date_str="2099-06-02", client=np_run_client,
                                      topics_override=[topic_news_photo])
    finally:
        _restore()
        points_path2.unlink(missing_ok=True)
        topics_path2.unlink(missing_ok=True)
        shutil.rmtree(youtube_article.ARTICLES_DIR / "2099-06-02", ignore_errors=True)
        if seen_backup_r2 is None:
            ycl2.SEEN_PATH.unlink(missing_ok=True)
        else:
            ycl2.SEEN_PATH.write_text(seen_backup_r2, encoding="utf-8")

    stats2 = result2["stats"]
    check("٢) بوابة run(): المقال يُصاغ فعليًا (لا امتناع) -- مقال واحد كُتب، صفر تخطٍّ لغياب صورة",
          stats2["articles_written"] == 1 and stats2["no_image_skipped"] == 0, stats2)
    check("٢) بوابة run(): نداء الصياغة فعلًا استُدعي (لا تخطٍّ صامت) -- نداءا نموذج على الأقل",
          len(np_run_client.messages.calls) >= 1, np_run_client.messages.calls)

    # ── ٣) أول خبر بلا صورة صالحة والثاني بصورة: تُستعمل الثانية فعليًا ──
    d3 = _news_photo_draft("np0000000003")
    store.save_draft(d3)
    path3, d3 = store.load_draft(d3["id"])
    good_image = Image.new("RGB", (800, 600), (200, 20, 20))

    def _dl_second_only(url, *a, **k):
        return None if "bad-news" in url else good_image

    real_news_photo_candidates_3 = youtube_extract.news_photo_candidates
    try:
        imagesearch.find_images = lambda *a, **k: []  # type: ignore
        cards.find_images = lambda *a, **k: []  # type: ignore
        youtube_extract.news_photo_candidates = lambda *a, **k: [  # type: ignore
            {"url": "https://example.com/bad-news.jpg", "publisher": "ناشر أول"},
            {"url": "https://example.com/good-news.jpg", "publisher": "ناشر ثانٍ"},
        ]
        imaging.download_image = _dl_second_only  # type: ignore
        ok3 = yp.ensure_title_card(path3, d3, cfg)
    finally:
        _restore()
        youtube_extract.news_photo_candidates = real_news_photo_candidates_3  # type: ignore
    check("٣) أول خبر بلا صورة صالحة: البطاقة تُبنى بنجاح مع ذلك", ok3, ok3)
    check("٣) أول خبر بلا صورة صالحة: الرابط المُعتمَد فعليًا من الخبر الثاني (good-news) لا الأول",
          "good-news" in (d3.get("image_info", {}).get("chosen_url") or ""),
          d3.get("image_info", {}).get("chosen_url"))
    check("٣) أول خبر بلا صورة صالحة: ناشر الصورة المسجَّل من الخبر الثاني فعليًا",
          d3.get("image_info", {}).get("news_photo_publisher") == "ناشر ثانٍ",
          d3.get("image_info"))
    check("٣) أول خبر بلا صورة صالحة: kind لا يزال news_photo",
          d3.get("image_info", {}).get("kind") == "news_photo", d3.get("image_info"))

    # ── ٤) لا صورة حرة ولا أي خبر بصورة صالحة: لا نداء صياغة إطلاقًا،
    # والتخطّي يُسجَّل بسببه، وسطر الملخّص يظهر كما هو اليوم ──
    topic_none = {"title": "قضية بلا أي صورة", "event": "حدث بلا صورة", "layer": "a",
                 "blocs": ["arabic", "turkish"], "channels": ["الجزيرة", "CNN Türk"],
                 "agreement": "agreement", "point_ids": [0, 1]}
    points_none = [
        {"video_id": "vidnone1", "bloc": "arabic", "channel": "الجزيرة", "speaker": "ناطق",
         "statement": "قول بلا صورة", "quote_arabic": "اقتباس", "type": "fact",
         "video_title": "فيديو", "video_url": "https://youtube.com/watch?v=vidnone1",
         "timestamp": 1},
        {"video_id": "vidnone2", "bloc": "turkish", "channel": "CNN Türk", "speaker": "متحدث",
         "statement": "قول بلا صورة ٢", "quote_arabic": "اقتباس ٢", "type": "fact",
         "video_title": "فيديو ٢", "video_url": "https://youtube.com/watch?v=vidnone2",
         "timestamp": 2},
    ]

    class _NoCallClient:
        class _Messages:
            def __init__(self) -> None:
                self.calls: list = []

            def create(self, **kw):
                self.calls.append(kw)
                raise AssertionError("لا يجوز نداء الصياغة -- بوابة الصورة كانت يجب أن تمتنع")

        def __init__(self) -> None:
            self.messages = self._Messages()

    ycl4 = youtube_cluster
    ycl4.POINTS_DIR.mkdir(parents=True, exist_ok=True)
    ycl4.TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    points_path4 = ycl4.POINTS_DIR / "2099-06-06.json"
    topics_path4 = ycl4.TOPICS_DIR / "2099-06-06.json"
    points_path4.write_text(json.dumps({"points": points_none}, ensure_ascii=False),
                            encoding="utf-8")
    topics_path4.write_text(json.dumps({"run_date": "2099-06-06", "topics": [topic_none]},
                                       ensure_ascii=False), encoding="utf-8")
    seen_backup4 = ycl4.SEEN_PATH.read_text(encoding="utf-8") if ycl4.SEEN_PATH.exists() else None
    no_call_client = _NoCallClient()
    real_news_photo_available_4 = youtube_extract.news_photo_available
    try:
        imagesearch.find_images = lambda *a, **k: []  # type: ignore
        youtube_extract.news_photo_available = lambda *a, **k: False  # type: ignore
        # Issue #1104: topics_override صراحة (انظر تعليق مشابه أعلى الملف)
        result4 = youtube_article.run(cfg, date_str="2099-06-06", client=no_call_client,
                                      topics_override=[topic_none])
    finally:
        _restore()
        youtube_extract.news_photo_available = real_news_photo_available_4  # type: ignore
        points_path4.unlink(missing_ok=True)
        topics_path4.unlink(missing_ok=True)
        shutil.rmtree(youtube_article.ARTICLES_DIR / "2099-06-06", ignore_errors=True)
        if seen_backup4 is None:
            ycl4.SEEN_PATH.unlink(missing_ok=True)
        else:
            ycl4.SEEN_PATH.write_text(seen_backup4, encoding="utf-8")

    stats4 = result4["stats"]
    check("٤) لا صورة حرة ولا خبر صالح: صفر نداءات نموذج (لا صياغة، لا عناوين، لا حارس محظورات)",
          len(no_call_client.messages.calls) == 0, no_call_client.messages.calls)
    check("٤) لا صورة حرة ولا خبر صالح: صفر مقالات كُتبت",
          stats4["articles_written"] == 0, stats4)
    check("٤) لا صورة حرة ولا خبر صالح: stats.no_image_skipped == 1، لا draft_failures",
          stats4["no_image_skipped"] == 1 and stats4["draft_failures"] == 0, stats4)
    check("٤) لا صورة حرة ولا خبر صالح: سبب التخطّي مسجَّل صراحةً («لا صورة متاحة»)",
          result4["skipped"] and "لا صورة متاحة" in result4["skipped"][0]["reason"],
          result4["skipped"])
    # سطر ملخّص التشغيلة (main()) -- نفس الشرط والصياغة الحرفيَّين المستعملين
    # هناك، مُغذَّيين بإحصاء run() الحقيقي أعلاه لا رقم مصطنع.
    import contextlib
    import io as _io
    summary_buf = _io.StringIO()
    with contextlib.redirect_stdout(summary_buf):
        if stats4["no_image_skipped"]:
            print(f"⏭️ تُخطّي {stats4['no_image_skipped']} موضوعًا: لا صورة متاحة")
    check("٤) سطر الملخّص: «⏭️ تُخطّي N موضوعًا: لا صورة متاحة» يظهر فعليًا",
          "⏭️ تُخطّي 1 موضوعًا: لا صورة متاحة" in summary_buf.getvalue(),
          summary_buf.getvalue())

    # ── ٥) فشل شبكة في البحث: انتقال هادئ بلا انهيار، وسجل تشخيصي واحد على
    # الأقل -- يختبر youtube_extract.news_photo_candidates مباشرة (لا عبر
    # ensure_title_card) لعزل معالجة الفشل الجديدة عن بقية السلسلة. headline/
    # event فارغان كي تبقى عبارة البحث الوحيدة image_query_en، فيقع الفشل
    # مرّة واحدة بالضبط (نداء sources.fetch_source واحد) لا مرّات متكرّرة ──
    class _ListHandler5(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.messages: list[str] = []

        def emit(self, record) -> None:
            self.messages.append(record.getMessage())

    def _boom(*a, **k):
        raise RuntimeError("تعطّل الشبكة (محاكاة)")

    log_handler5 = _ListHandler5()
    prev_level5 = youtube_extract.log.level
    youtube_extract.log.addHandler(log_handler5)
    youtube_extract.log.setLevel(logging.INFO)
    real_fetch_source_5 = sources.fetch_source
    try:
        sources.fetch_source = _boom  # type: ignore
        result5 = youtube_extract.news_photo_candidates(
            "", "", cfg, image_query_en="مصطلح اختباري")
    finally:
        sources.fetch_source = real_fetch_source_5  # type: ignore
        youtube_extract.log.removeHandler(log_handler5)
        youtube_extract.log.setLevel(prev_level5)
    check("٥) فشل شبكة في البحث: لا انهيار -- تعيد قائمة فارغة",
          result5 == [], result5)
    check("٥) فشل شبكة في البحث: سجل تشخيصي واحد على الأقل يوثّق الفشل بدل الصمت",
          len(log_handler5.messages) >= 1, log_handler5.messages)

    # ── ٦) تبديل الصورة يدويًا عبر /صورة على مسودة بصورة خبر يعمل ولا ينهار ──
    # setimage.py يستورد download_image بـ``from .imaging import download_image``
    # (اسم محلي مربوط وقت أول استيراد للوحدة، لا مرجعًا لـimaging.download_image
    # الحالي) -- تمويهي المحلي أعلاه لا يبلغه إطلاقًا؛ الفاكة العامة
    # (install_fakes، مربوطة فعليًا منذ أول "from src import setimage" في
    # الحزمة) هي ما يُستعمَل هنا بالضبط، بنفس نمط
    # test_setimage_revives_failed_draft_only_when_image_was_the_cause القائم
    # (بلا أي تمويه محلي فيه أيضًا).
    manual_url = "https://example.com/manual-swap.jpg"
    updated6 = setimage.apply_image(d2["id"], manual_url, cfg)
    check("٦) /صورة على مسودة بصورة خبر: لا انهيار، تعيد مسودة محدَّثة",
          updated6 is not None, updated6)
    check("٦) /صورة على مسودة بصورة خبر: الصورة الجديدة يدوية فعليًا (manual=True)",
          bool(updated6) and updated6.get("image_info", {}).get("manual") is True,
          updated6.get("image_info") if updated6 else None)
    check("٦) /صورة على مسودة بصورة خبر: kind لم يعد news_photo بعد الاستبدال اليدوي",
          bool(updated6) and updated6.get("image_info", {}).get("kind") != "news_photo",
          updated6.get("image_info") if updated6 else None)

    # (Issue #1160: الخطّان الذهبيان استُبدلا بتدرّجين ناعمين، فعتبة القفزة
    # خُفِّضت من 45 إلى 12 كي يبقى الشريط السفلي مكتشَفًا — حدّ حادّ وحيد الآن —
    # ويُضاف مقارنة العمود كله صفًّا صفًّا لتغطية التدرّجين.)
    # ── ٧) فحص التخطيط: بطاقة الدرجة الثانية مطابقة تمامًا لبطاقة مسار
    # الأخبار في مواضع الترويسة/شريط الصورة/شريط العنوان/التذييل -- الحدود
    # تُكتشَف من ألوان البطاقتين الفعليَّين المبنيَّين هنا بالبكسل، لا من
    # أرقام محسوبة يدويًا من صيغ config.yaml (نفس الاحتياط الذي طلبه صاحب
    # المشروع: فحصان سابقان مرّا ببطاقة معطوبة فعليًا لأنهما اعتمدا فحص
    # بكسلات مفردة بدل هيكل البطاقة كاملة) ──
    def _col_colors(img) -> list[tuple[int, int, int]]:
        px = img.load()
        x = 4  # قريب من الحافة اليسرى -- خارج منطقة الشعار/الملصقات/النص
        return [px[x, y] for y in range(img.height)]

    def _band_boundaries(colors, threshold: int = 12) -> list[int]:
        bounds = []
        prev = colors[0]
        for y in range(1, len(colors)):
            cur = colors[y]
            if sum(abs(a - b) for a, b in zip(cur, prev)) > threshold:
                bounds.append(y)
            prev = cur
        return bounds

    shared_headline = "عنوان مشترك لفحص تطابق تخطيط بطاقتَي الأخبار والتحليل"
    photo_fixture = Image.new("RGB", (900, 600), (20, 220, 20))
    news_card_path = DRAFTS_DIR / "layout_check_news.jpg"
    analysis_card_path = DRAFTS_DIR / "layout_check_analysis.jpg"
    news_report: dict = {}
    analysis_report: dict = {}
    try:
        imaging.download_image = lambda *a, **k: photo_fixture.copy()  # type: ignore
        imaging.build_post_image(
            headline=shared_headline, category="", urgent=False,
            image_urls=["https://example.com/news-main.jpg"], publisher=["ناشر تجريبي"],
            cfg=cfg, out_path=news_card_path, bucket="", report=news_report, origin="news")
        imaging.build_post_image(
            headline=shared_headline, category="", urgent=False,
            image_urls=None, fallback_urls=[], publisher=[], cfg=cfg,
            out_path=analysis_card_path, bucket="", report=analysis_report, origin="analysis",
            news_photo_provider=lambda: [{"url": "https://example.com/analysis-photo.jpg",
                                          "publisher": "ناشر الصورة"}])
    finally:
        _restore()

    with Image.open(news_card_path) as im_news:
        news_col = _col_colors(im_news.convert("RGB"))
        news_bounds = _band_boundaries(news_col)
    with Image.open(analysis_card_path) as im_analysis:
        analysis_col = _col_colors(im_analysis.convert("RGB"))
        analysis_bounds = _band_boundaries(analysis_col)
    col_drift = max(sum(abs(a - b) for a, b in zip(p, q))
                    for p, q in zip(news_col, analysis_col))
    news_card_path.unlink(missing_ok=True)
    analysis_card_path.unlink(missing_ok=True)

    check("٧) فحص التخطيط: بطاقة الدرجة الثانية تحمل kind == 'news_photo' فعليًا",
          analysis_report.get("kind") == "news_photo", analysis_report)
    check("٧) فحص التخطيط: حدود الشرائط (ترويسة/صورة/عنوان/تذييل) متطابقة "
          "تمامًا بين بطاقة أخبار عادية وبطاقة الدرجة الثانية، مكتشَفة من "
          "الصور الفعلية المبنيّة لا من أرقام مكتوبة يدويًا",
          news_bounds == analysis_bounds and len(news_bounds) >= 1 and col_drift <= 30,
          (news_bounds, analysis_bounds, col_drift))

    shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)


def test_image_ladder_order() -> None:
    """سلّم الصورة على imaging.build_post_image نفسها والبطاقة المبنيّة فعليًا
    (Issue #1123): الناشر ← صورة خبر عن الموضوع ← حرة ← بلا صورة. الكسل في
    الاتجاهين يُقاس بعدّ نداءات المزوّدَين، لا بمطالعة الكود."""
    from PIL import Image as _Img
    cfg = load_config()
    real_dl = imaging.download_image
    real_face = imaging.face_score
    real_draw_text = imaging.draw_text
    out = DRAFTS_DIR / "ladder_check.jpg"
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    news_img = _Img.new("RGB", (900, 600), (20, 220, 20))
    FACE_URL = "https://example.com/free-face.jpg"

    def run(*, image_urls=None, news=True, free=True, origin="analysis",
            news_url="https://example.com/news.jpg", free_url="https://example.com/free.jpg"):
        calls = {"news": 0, "free": 0}
        drawn: list[str] = []

        def news_provider():
            calls["news"] += 1
            return [{"url": news_url, "publisher": "ناشر الخبر"}] if news else []

        def free_provider():
            calls["free"] += 1
            return [free_url] if free else []

        report: dict = {}
        imaging.download_image = lambda *a, **k: news_img.copy()  # type: ignore
        imaging.draw_text = (  # type: ignore
            lambda d, xy, text, *a, **k: (drawn.append(text), real_draw_text(d, xy, text, *a, **k))[1])
        try:
            kw = dict(news_photo_provider=news_provider) if origin == "analysis" else {}
            imaging.build_post_image(
                headline="عنوان اختبار السلّم", category="", urgent=False,
                image_urls=image_urls, publisher=["الجزيرة"], cfg=cfg, out_path=out,
                fallback_provider=free_provider, bucket="", report=report,
                origin=origin, **kw)
        finally:
            imaging.download_image = real_dl  # type: ignore
            imaging.draw_text = real_draw_text  # type: ignore
        return calls, report, drawn

    # ١) تحليل، المزوّدان متاحان: صورة الخبر، والحرة صفر نداء
    calls, rep, drawn = run()
    check("سلّم الصورة: المزوّدان متاحان ⇒ صورة الخبر", rep.get("kind") == "news_photo", rep)
    check("سلّم الصورة: المزوّدان متاحان ⇒ مزوّد الحرة لا يُستدعى (عدّ النداءات)",
          calls == {"news": 1, "free": 0}, calls)
    check("سلّم الصورة: صورة الخبر بلا وسم «صورة تعبيرية»",
          "صورة تعبيرية" not in drawn and rep.get("illustrative") is False, (drawn, rep))
    # Issue #1158: لا «صورة: …» على البطاقة؛ ناشر الصورة يبقى في التقرير
    check("سلّم الصورة: سطر المصدر لا يذكر ناشر صورة الخبر (داخلي في report فقط)",
          not any("صورة:" in t for t in drawn)
          and rep.get("news_photo_publisher") == "ناشر الخبر", (drawn, rep))

    # ٢) تحليل، لا صورة خبر: الحرة بوسم «صورة تعبيرية»
    calls, rep, drawn = run(news=False)
    check("سلّم الصورة: لا صورة خبر ⇒ تُستعمل الحرة", rep.get("illustrative") is True
          and rep.get("kind") is None, rep)
    check("سلّم الصورة: لا صورة خبر ⇒ المزوّدان استُدعيا مرة واحدة كلٌّ",
          calls == {"news": 1, "free": 1}, calls)
    check("سلّم الصورة: الحرة تحمل وسم «صورة تعبيرية»", "صورة تعبيرية" in drawn, drawn)

    # ٣) تحليل، لا الاثنتان: بلا صورة (بوابة المنع تعمل على has_photo/used_original)
    calls, rep, drawn = run(news=False, free=False)
    check("سلّم الصورة: لا الاثنتان ⇒ بلا صورة (used_original=False، illustrative=False، kind=None)",
          rep.get("used_original") is False and rep.get("illustrative") is False
          and rep.get("kind") is None, rep)
    check("سلّم الصورة: لا الاثنتان ⇒ لا وسم تعبيرية", "صورة تعبيرية" not in drawn, drawn)
    # بوابة المنع نفسها (youtube_article) لم تتغيّر: news_photo_available=False
    # وصورة حرة غائبة ⇒ لا صياغة -- مغطّاة في test_youtube_image_news_photo ٤.

    # ٤) أخبار بصورة ناشر: لا يُستدعى أي مزوّد، والبطاقة كما اليوم
    calls, rep, drawn = run(image_urls=["https://example.com/publisher.jpg"], origin="news")
    check("سلّم الصورة (تثبيت): أخبار بصورة ناشر ⇒ لا مزوّد يُستدعى",
          calls == {"news": 0, "free": 0}, calls)
    check("سلّم الصورة (تثبيت): صورة الناشر أصلية بلا وسم تعبيرية",
          rep.get("used_original") is True and rep.get("illustrative") is False
          and "صورة تعبيرية" not in drawn, (rep, drawn))
    # وصورة ناشر مع مزوّد أخبار مُمرَّر: لا يُستدعى أيّ منهما
    calls, rep, _ = run(image_urls=["https://example.com/publisher.jpg"])
    check("سلّم الصورة: نجاح صورة الناشر ⇒ لا مزوّد أخبار ولا حرة",
          calls == {"news": 0, "free": 0}, calls)
    # أخبار بلا صورة ناشر: الحرة مباشرةً كما كان
    calls, rep, drawn = run(origin="news")
    check("سلّم الصورة (تثبيت): أخبار بلا صورة ناشر ⇒ الحرة بوسم تعبيرية، بلا خبر",
          calls == {"news": 0, "free": 1} and rep.get("illustrative") is True
          and "صورة تعبيرية" in drawn, (calls, rep, drawn))

    # ٥) وجه: صورة الخبر لا تُفحَص، والحرة ذات الوجه تُرفض (فحص photo_candidates)
    imaging.face_score = lambda img: 0.9  # type: ignore
    try:
        calls, rep, _ = run()
        check("سلّم الصورة: صورة خبر فيها وجه تُستعمل (لا فحص وجوه عليها)",
              rep.get("kind") == "news_photo", rep)
        from src import imagesearch as _is
        real_find = _is.find_images
        real_dl2 = imaging.download_image
        _is.find_images = lambda *a, **k: [FACE_URL]  # type: ignore
        imaging.download_image = lambda *a, **k: news_img.copy()  # type: ignore
        try:
            faces = youtube_extract.photo_candidates("عنوان", "حدث", cfg)
        finally:
            _is.find_images = real_find  # type: ignore
            imaging.download_image = real_dl2  # type: ignore
        check("سلّم الصورة: صورة حرة فيها وجه تُرفض كما اليوم (photo_candidates فارغة)",
              faces == [], faces)
    finally:
        imaging.face_score = real_face  # type: ignore

    # ٦) فحص بصري مكتوب: بطاقة تحليل بصورة خبر مصطنعة نظيفة تُحفظ للفحص العيني
    visual = Path(tempfile.gettempdir()) / "ladder_visual_check.jpg"
    imaging.download_image = lambda *a, **k: news_img.copy()  # type: ignore
    try:
        imaging.build_post_image(
            headline="هل تتغير معادلة الطاقة بعد الاتفاق الجديد؟", category="", urgent=False,
            image_urls=None, publisher=["تحليل لتغطية الجزيرة وTRT"], cfg=cfg,
            out_path=visual, bucket="", origin="analysis",
            news_photo_provider=lambda: [{"url": "https://example.com/n.jpg",
                                          "publisher": "ناشر الخبر"}])
    finally:
        imaging.download_image = real_dl  # type: ignore
    check("سلّم الصورة: بطاقة الفحص البصري بُنيت فعليًا", visual.exists(), str(visual))
    out.unlink(missing_ok=True)
