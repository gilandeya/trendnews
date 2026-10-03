"""مسار «هام» — الحَكَم على النقاط (Issue #1194، المهمة 1 من 3).

كل اختبار هنا يجري على مخرَج الأنبوب كاملًا: نص Issue ← important.judge ←
الملف المحفوظ في state/important، ببحث وجلب ونموذج مزيَّفة (ImportantRig في
tests/helpers.py). حالات الحارس g1–g6 في tests/test_guards_golden.py."""
from __future__ import annotations

import re

from tests.helpers import (check, load_config, ImportantRig, important_doc,
                           important_point, important_stance, brave_result)


def _body(n: int) -> str:
    return f"نص Issue كامل رقم {n} يلصقه صاحب المشروع."


def test_important_pipeline() -> None:
    from src import important, stages

    cfg = load_config()

    # ── (a) أربع نقاط ← الأحكام الأربعة، والملف يحوي حقول البند 3 لكل منها ──
    p_conf = important_point("زيتونة", "افتتحت الحكومة جسر زيتونة الجديد أمس")
    p_inacc = important_point("برتقالة", "قُتل خمسة أشخاص في حادث برتقالة")
    p_false = important_point("ليمونة", "أُعلنت استقالة وزير في حادثة ليمونة")
    p_none = important_point("رمانة", "اندلع حريق ضخم في مخزن رمانة")
    pic = "https://img.example/a.jpg"
    docs = {
        "زيتونة": [important_doc("صحيفة الشرق", "افتتحت الحكومة جسر زيتونة الجديد.",
                                 images=[pic]),
                   important_doc("موقع الغرب", "تقرير مستقل عن افتتاح جسر زيتونة.")],
        "برتقالة": [important_doc("صحيفة الشرق", "أسفر حادث برتقالة عن ثلاثة قتلى."),
                    important_doc("موقع الغرب", "ثلاثة قتلى في حادث برتقالة بحسب مستقل.")],
        "ليمونة": [important_doc("صحيفة الشرق", "تنفي الحكومة استقالة الوزير وتصفها بالكاذبة."),
                   important_doc("موقع الغرب", "مصدر مستقل: خبر استقالة الوزير كاذب تمامًا.")],
        "رمانة": [important_doc("صحيفة الشرق", "حريق صغير في مستودع قريب من رمانة.",
                                images=["https://img.example/n.jpg"]),
                  important_doc("موقع الغرب", "أخمدت فرق الإطفاء حريق المستودع القريب.")],
    }

    def classify(point, names):
        if "جسر زيتونة" in point:
            return {"sources": [important_stance(n, "supports", "جسر زيتونة") for n in names]}
        if "برتقالة" in point:
            return {"sources": [important_stance(
                n, "conflicts_detail", "ثلاثة قتلى", detail="عدد القتلى",
                correct_form="ثلاثة قتلى") for n in names]}
        if "ليمونة" in point:
            return {"sources": [important_stance(names[0], "refutes", "الكاذبة"),
                                important_stance(names[1], "refutes", "كاذب تمامًا")]}
        return {"sources": [important_stance(n, "irrelevant") for n in names],
                "nearest_events": [{"title": "حريق مستودع قرب رمانة",
                                    "description": "حريق أصغر أخمدته فرق الإطفاء",
                                    "sources": list(names)}]}

    with ImportantRig([p_conf, p_inacc, p_false, p_none], docs, classify) as rig:
        important.judge(_body(1), 95001, cfg)
    saved = important.load_saved(95001)
    by_text = {p["text"]: p for p in saved["points"]}
    got = [by_text[p["text"]]["verdict"] for p in (p_conf, p_inacc, p_false, p_none)]
    check("(a) أربع نقاط تنتهي بالأحكام الأربعة",
          got == ["confirmed", "inaccurate", "false", "not_found"], got)
    fields = {"id", "text", "verdict", "evidence", "correction", "refuted_by", "nearest",
              "image_candidates", "dropped_reason"}
    check("(a) كل نقطة تحوي حقول البند 3 كاملة",
          all(fields <= set(p) for p in saved["points"]),
          [fields - set(p) for p in saved["points"]])
    c, i, f_, n = (by_text[p["text"]] for p in (p_conf, p_inacc, p_false, p_none))
    check("(a) الأدلة تحمل الناشر والرابط والتصنيف والمقتطف",
          len(c["evidence"]) == 2 and all(
              {"publisher", "link", "stance", "excerpt"} <= set(e) and e["excerpt"]
              for e in c["evidence"]), c["evidence"])
    check("(a) correction للـinaccurate: الخطأ والصيغة الصحيحة والمصدران",
          i["correction"]["error"] == "عدد القتلى" and i["correction"]["correct"] == "ثلاثة قتلى"
          and len(i["correction"]["sources"]) == 2 and c["correction"] is None, i["correction"])
    check("(a) refuted_by للـfalse (مصدران بمقتطفاتهما) ولا nearest له",
          len(f_["refuted_by"]) == 2 and all(r["excerpt"] for r in f_["refuted_by"])
          and f_["nearest"] is None, f_["refuted_by"])
    check("(a) nearest للـnot_found: عنوان ووصف ومصدران، والنقطة غير مُسقطة",
          n["nearest"]["title"] == "حريق مستودع قرب رمانة" and n["nearest"]["description"]
          and len(n["nearest"]["sources"]) == 2 and n["dropped_reason"] is None, n["nearest"])
    check("(a) image_candidates من صور مصادر الأدلة فقط",
          [x["url"] for x in c["image_candidates"]] == [pic]
          and [x["url"] for x in n["image_candidates"]] == ["https://img.example/n.jpg"],
          (c["image_candidates"], n["image_candidates"]))

    # ── (c) nearest: بحدث موثَّق بمصدرين يُحفظ، وبلا حدث موثَّق تُسقَط النقطة ──
    q_near = important_point("خوخة", "وقع انفجار كبير قرب خوخة")
    q_one = important_point("كمثرى", "غرق قارب كبير قرب كمثرى")
    q_empty = important_point("تينة", "انهار مبنى سكني في تينة")
    docs_c = {
        "خوخة": [important_doc("صحيفة الشرق", "انفجار أصغر قرب مصنع."),
                 important_doc("موقع الغرب", "تحقيق مستقل في انفجار المصنع.")],
        "كمثرى": [important_doc("صحيفة الشرق", "تقرير منفرد عن قارب صيد.")],
        "تينة": [],
    }

    def classify_c(point, names):
        # العنوان يحمل كيان النقطة (آخر كلمة فيها) — شرط الكيان المشترك (#1200)
        ev = [{"title": f"حدث قرب {point.split()[-1]}", "description": "وصف",
               "sources": list(names)}]
        return {"sources": [important_stance(n, "irrelevant") for n in names],
                "nearest_events": ev}

    with ImportantRig([q_near, q_one, q_empty], docs_c, classify_c):
        important.judge(_body(2), 95002, cfg)
    sc = {p["text"]: p for p in important.load_saved(95002)["points"]}
    check("(c) حدث قريب موثَّق بمصدرين ← nearest محفوظ والنقطة باقية",
          sc[q_near["text"]]["nearest"] is not None
          and sc[q_near["text"]]["dropped_reason"] is None, sc[q_near["text"]])
    check("(c) حدث بمصدر واحد لا يُحفظ nearest ← تُسقط بسببها",
          sc[q_one["text"]]["nearest"] is None
          and sc[q_one["text"]]["dropped_reason"] == "لا أثر ولا حدث قريب موثَّق",
          sc[q_one["text"]])
    check("(c) بلا مصدر إطلاقًا ← not_found مُسقطة بالسبب نفسه",
          sc[q_empty["text"]]["verdict"] == "not_found"
          and sc[q_empty["text"]]["dropped_reason"] == "لا أثر ولا حدث قريب موثَّق",
          sc[q_empty["text"]])

    # ── (d) عشر نقاط ← ثمانٍ فقط تُحكم، والقصّ مسجَّل ──
    ten = [important_point(f"نقطةعشر{chr(0x0623 + k)}", f"واقعة عشرية رقم {k} تخص نقطةعشر{chr(0x0623 + k)}")
           for k in range(10)]
    with ImportantRig(ten, {}, lambda p, n: {"sources": []}):
        important.judge(_body(3), 95003, cfg)
    sd = important.load_saved(95003)
    check("(d) عشر نقاط ← ثمانٍ فقط تُحكم",
          len(sd["points"]) == 8
          and [p["text"] for p in sd["points"]] == [p["text"] for p in ten[:8]],
          len(sd["points"]))
    check("(d) القصّ مسجَّل في الملف: المستخرَج والمحكوم والمقصوص",
          sd["truncated"] and sd["truncated"]["extracted"] == 10
          and sd["truncated"]["judged"] == 8
          and [s["text"] for s in sd["truncated"]["skipped"]] == [p["text"] for p in ten[8:]],
          sd["truncated"])
    check("(d) لا قصّ مسجَّل حين تقلّ النقاط عن السقف", saved["truncated"] is None)

    # ── (e) id ثابت لنص النقطة عبر تشغيلتين ويطابق علامات stages.py ──
    with ImportantRig([p_conf, p_inacc, p_false, p_none], docs, classify):
        important.judge(_body(1), 95004, cfg)
    ids1 = {p["text"]: p["id"] for p in important.load_saved(95001)["points"]}
    ids2 = {p["text"]: p["id"] for p in important.load_saved(95004)["points"]}
    check("(e) id ثابت لنص النقطة نفسه عبر تشغيلتين", ids1 == ids2, (ids1, ids2))
    check("(e) id من 12 حرفًا سداسيًا عشريًا مميَّزة لكل نقطة",
          all(re.fullmatch(r"[0-9a-f]{12}", v) for v in ids1.values())
          and len(set(ids1.values())) == 4, ids1)
    marker_ok = all(
        stages.GO_MARKER.search(f"<!-- go:go2:{v} -->")
        and stages.GO_MARKER.search(f"<!-- go:go2:{v} -->").group(2) == v
        for v in ids1.values())
    check("(e) id تقبله علامات stages.GO_MARKER كاملًا", marker_ok)
    check("(e) المسافات الزائدة في النقطة لا تغيّر هويتها",
          important.point_id("أ  ب\nج") == important.point_id("أ ب ج"))

    # ── (f) عدّاد النداءات محفوظ ويطابق النداءات الفعلية المزيَّفة ──
    mc = saved["model_calls"]
    check("(f) المجموع المحفوظ = نداءات النموذج الفعلية المزيَّفة",
          mc["total"] == len(rig.calls) == 5 and sum(mc["by_point"].values()) == 4
          and mc["brief"] == 1, (mc, rig.calls))
    check("(f) النداءات مفصَّلة حسب النموذج: التفكيك Haiku والتصنيف article.model",
          mc["by_model"].get(cfg.path("important.extract_model")) == 1
          and mc["by_model"].get(cfg.path("article.model", "claude-sonnet-5")) == 4,
          mc["by_model"])
    check("(f) نداء تصنيف واحد لكل نقطة وفي كل نقطة حقل model_calls",
          all(p["model_calls"] == 1 for p in saved["points"])
          and set(mc["by_point"]) == set(ids1.values()), mc)
    mc_c = important.load_saved(95002)["model_calls"]
    check("(f) نقطة بلا وثائق لا نداء لها (صفر مصادر ≠ نفي)",
          mc_c["total"] == 3 and mc_c["by_point"][important.point_id(q_empty["text"])] == 0, mc_c)

    # ── نقاط الآراء والأسئلة تُتجاهل، والنقاط المتكررة تُحكم مرة واحدة ──
    opinion = important_point("عنبة", "أرى أن القرار خاطئ بشأن عنبة", kind="رأي")
    with ImportantRig([p_conf, opinion, dict(p_conf)], docs, classify) as rig2:
        important.judge(_body(4), 95005, cfg)
    s5 = important.load_saved(95005)
    check("الآراء تُتجاهل والنص المكرر يُحكم مرة واحدة",
          len(s5["points"]) == 1 and rig2.calls == ["extract_points", "classify_sources"],
          (len(s5["points"]), rig2.calls))

    # ── نفي بلا مقتطف يثبته نص المصدر لا يُحسب (حارس false) ──
    p_fake = important_point("تفاحة", "وقعت حادثة تفاحة في المدينة")
    docs_fake = {"تفاحة": [important_doc("صحيفة الشرق", "نص عن تفاحة."),
                           important_doc("موقع الغرب", "نص آخر مستقل عن تفاحة.")]}
    with ImportantRig([p_fake], docs_fake, lambda p, n: {"sources": [
            important_stance(x, "refutes", "عبارة لا وجود لها في النص") for x in n]}):
        important.judge(_body(5), 95006, cfg)
    check("نفي بمقتطف لا يوجد في نص المصدر ⇒ لا false",
          important.load_saved(95006)["points"][0]["verdict"] != "false")

    # ── جهة تدقيق: «AFP» وحدها وكالة لا مدقِّقة، و«AFP Fact Check» مدقِّقة ──
    icfg = cfg.get("important", {})
    check("«AFP» وحدها ليست جهة تدقيق، و«AFP Fact Check» و«Snopes.com» مدقِّقتان",
          not important._is_fact_checker("AFP", icfg)
          and important._is_fact_checker("AFP Fact Check", icfg)
          and important._is_fact_checker("Snopes.com", icfg))

    # ── أدلة متعارضة (نفي كافٍ وتأييد كافٍ) لا تنتج false ولا confirmed ──
    p_mix = important_point("موزة", "وقعت حادثة موزة في المدينة")
    docs_mix = {"موزة": [important_doc("صحيفة الشرق", "حادثة موزة وقعت فعلًا ونفاها آخرون."),
                         important_doc("موقع الغرب", "مستقل: وقعت حادثة موزة فعلًا."),
                         important_doc("قناة الشمال", "تقرير ثالث: لم تقع حادثة موزة أبدًا."),
                         important_doc("إذاعة الجنوب", "تقرير رابع: حادثة موزة لم تقع أبدًا.")]}

    def classify_mix(point, names):
        return {"sources": [
            important_stance("صحيفة الشرق", "supports", "حادثة موزة وقعت"),
            important_stance("موقع الغرب", "supports", "وقعت حادثة موزة"),
            important_stance("قناة الشمال", "refutes", "لم تقع حادثة موزة"),
            important_stance("إذاعة الجنوب", "refutes", "لم تقع أبدًا")]}

    with ImportantRig([p_mix], docs_mix, classify_mix):
        important.judge(_body(6), 95007, cfg)
    pm = important.load_saved(95007)["points"][0]
    check("نفي كافٍ مع تأييد كافٍ ⇒ not_found بملاحظة «أدلة متعارضة»",
          pm["verdict"] == "not_found" and "أدلة متعارضة" in pm["note"], pm)

    # ── فشل نداء التصنيف تقنيًا ليس «لا أثر»: لا إسقاط ولا حكم ──
    from src import article
    p_err = important_point("خيارة", "وقعت حادثة خيارة في المدينة")
    docs_err = {"خيارة": [important_doc("صحيفة الشرق", "نص عن خيارة.")]}

    def boom(point, names):
        raise article.APIError("فشل مزيَّف", request=None, body=None)

    with ImportantRig([p_err], docs_err, boom):
        important.judge(_body(7), 95008, cfg)
    pe = important.load_saved(95008)["points"][0]
    check("فشل النداء التقني ⇒ not_found بملاحظة الفشل وبلا dropped_reason",
          pe["verdict"] == "not_found" and "فشل نداء التصنيف" in pe["note"]
          and pe["dropped_reason"] is None, pe)

    # ── static: لا temperature في نداء الحكم الجديد ──
    from pathlib import Path
    src_text = (Path(important.__file__)).read_text(encoding="utf-8")
    check("src/important.py لا تمرّر temperature", "temperature" not in src_text)


# ───────────── Issue #1198 (المهمة 1ب): التفكيك الخاص والبحث الجامع ─────────────

# نصوص النقاط السبع كما حُفظت في state/important/1197.json (التجربة الحقيقية
# الأولى): الادّعاء وتصحيحه ظهرا نقطتين مستقلتين فصارت سبعًا بدل خمس
BODY_1197 = "\n".join([
    "إعلان تركيا في 2026 عن إطلاق منظومة جديدة لمراقبة المحتوى المضلل على منصات التواصل",
    "انتشار مقطع فيديو زُعم أنه يوثق مظاهرات حديثة في تركيا احتجاجًا على ارتفاع أسعار الغذاء والوقود",
    "تحقق أظهر أن مقطع الفيديو المتداول يعود فعليًا إلى احتجاجات شهدتها إسطنبول في مارس/آذار 2025",
    "تداول صورة لعنصرين من القوات الخاصة التركية زُعم أنها تتضمن اعترافًا بارتكاب مجزرة في عفرين",
    "تبيّن أن الكتابة على الصورة المتداولة عُدّلت وأن الصورة الأصلية تعود إلى عام 2016",
    "تقارير تشير إلى أن تركيا بدأت استخدام طائرات مسيرة جديدة يصل مداها إلى 800 كيلومتر",
    "منشورات متداولة تفيد بأن عدد مستخدمي الإنترنت في تركيا تجاوز 90 مليون مستخدم خلال 2026",
])


def _q(lang: str, text: str) -> dict:
    return {"lang": lang, "q": text}


def regression_1197(issue: int = 96001) -> dict:
    """تشغيل الأنبوب على نص #1197 بمصادر مزيَّفة تحاكي الحقيقة الموثَّقة في الـIssue
    ← الملف المحفوظ كما هو. دالة مستقلة كي يُطبع ناتجها نفسه عند الحاجة."""
    from src import important

    cfg = load_config()
    points = [
        {"claim": "تركيا أعلنت في 2026 إطلاق منظومة جديدة لمراقبة المحتوى المضلل على منصات التواصل",
         "asserted": "", "entities": ["تركيا"], "dates": ["2026"], "numbers": [],
         "queries": [_q("ar", "تركيا تطلق منظومة جديدة لمراقبة المحتوى المضلل"),
                     _q("en", "Turkey new system monitoring disinformation social media"),
                     _q("tr", "Türkiye dezenformasyon izleme sistemi sosyal medya")],
         "factcheck_query": "تركيا منظومة مراقبة المحتوى المضلل تحقق"},
        # بلا أسماء: لا تسقط قبل البحث، وما ذكره النص عنها (تحقق ← مارس 2025) في asserted
        {"claim": "فيديو متداول زُعم أنه يوثق مظاهرات حديثة احتجاجًا على ارتفاع أسعار الغذاء والوقود",
         "asserted": "تحقق أظهر أن المقطع يعود إلى احتجاجات إسطنبول في مارس 2025",
         "entities": [], "dates": ["مارس 2025"], "numbers": [],
         "queries": [_q("ar", "فيديو مظاهرات حديثة احتجاجا على ارتفاع الأسعار تركيا"),
                     _q("tr", "protesto videosu eski görüntü zam gıda akaryakıt")],
         "factcheck_query": "فيديو مظاهرات تركيا أسعار الغذاء تحقق"},
        {"claim": "صورة لعنصرين من القوات الخاصة التركية يُزعم أنها تتضمن اعترافًا بمجزرة في عفرين",
         "asserted": "الكتابة على الصورة عُدّلت وأصلها يعود إلى 2016",
         "entities": ["القوات الخاصة التركية", "عفرين"], "dates": ["2016"], "numbers": [],
         "queries": [_q("ar", "صورة القوات الخاصة التركية اعتراف مجزرة عفرين"),
                     _q("en", "Turkish special forces photo Afrin massacre confession")],
         "factcheck_query": "صورة القوات الخاصة التركية مجزرة عفرين تحقق"},
        {"claim": "تركيا بدأت استخدام طائرات مسيرة جديدة يصل مداها إلى 800 كيلومتر",
         "asserted": "", "entities": ["تركيا"], "dates": [], "numbers": ["800 كيلومتر"],
         "queries": [_q("ar", "تركيا طائرات مسيرة جديدة مدى 800 كيلومتر"),
                     _q("en", "Turkey new drones 800 km range")],
         "factcheck_query": "تركيا طائرات مسيرة 800 كيلومتر تحقق"},
        {"claim": "عدد مستخدمي الإنترنت في تركيا تجاوز 90 مليون مستخدم خلال 2026",
         "asserted": "", "entities": ["تركيا"], "dates": ["2026"], "numbers": ["90 مليون"],
         "queries": [_q("ar", "عدد مستخدمي الإنترنت في تركيا 2026 مليون"),
                     _q("en", "Turkey internet users 2026 million DataReportal")],
         "factcheck_query": "عدد مستخدمي الإنترنت في تركيا تحقق"},
    ]
    refute_txt = "الصورة معدّلة، والكتابة عليها مفبركة، وأصلها يعود إلى عام 2016"
    docs = {
        "منظومة": [important_doc("وكالة الأناضول", "رئاسة الاتصالات التركية تطلق حملات ضد الحسابات المضللة."),
                   important_doc("صحيفة صباح", "حملات رئاسة الاتصالات ضد حسابات التواصل المضللة.")],
        "مظاهرات": [important_doc("مسبار", "فيديو الاحتجاجات قديم يعود إلى عام 2013.",
                                  link="https://misbar.com/factcheck/2026/video-2013"),
                    important_doc("موقع عربي ٢١", "تدقيق مستقل لفيديو احتجاجات قديم من 2013.")],
        "عفرين": [important_doc("مسبار", refute_txt,
                                link="https://misbar.com/factcheck/2026/02/19/afrin-photo")],
        "مسيرة": [important_doc("صحيفة ديلي صباح", "اختبار صاروخ Çakır من Baykar بسرعة 800 كم/ساعة."),
                  important_doc("موقع خبر تك", "Baykar تختبر صاروخ Çakır بسرعة 800 كيلومتر في الساعة.")],
        "الإنترنت": [important_doc("DataReportal", "بلغ عدد مستخدمي الإنترنت في تركيا 77.5 مليون مستخدم."),
                     important_doc("موقع الأرقام", "تقرير Digital 2026: 77.5 مليون مستخدم للإنترنت في تركيا.")],
    }

    def classify(point, names):
        if "عفرين" in point:
            return {"sources": [important_stance(n, "refutes", "الصورة معدّلة") for n in names]}
        if "الإنترنت" in point:
            return {"sources": [important_stance(
                n, "conflicts_detail", "77.5 مليون", detail="العدد 90 مليونًا لا 77.5",
                correct_form="77.5 مليون مستخدم") for n in names]}
        return {"sources": [important_stance(n, "irrelevant") for n in names],
                "nearest_events": [{"title": "أقرب حدث موثَّق في تركيا", "description": "وصف من النصوص",
                                    "sources": list(names[:2])}]}

    with ImportantRig(points, docs, classify):
        important.judge(BODY_1197, issue, cfg)
    return important.load_saved(issue)


def test_important_search_and_extract() -> None:
    import json
    import os
    from src import article, important, imagesearch

    cfg = load_config()

    # ── (a) انحدار #1197: خمس نقاط لا سبع، والأحكام الصحيحة بدل صفر من خمسة ──
    saved = regression_1197()
    pts = saved["points"]
    p1, p2, p3, p4, p5 = (pts[i] for i in range(5))
    check("(a) خمس نقاط لا سبع (الادّعاء وتصحيحه نقطة واحدة)",
          len(pts) == 5 and len(BODY_1197.splitlines()) == 7, len(pts))
    check("(a) (3) ← false برابط misbar.com",
          p3["verdict"] == "false" and any("misbar.com" in r["link"] for r in p3["refuted_by"]),
          (p3["verdict"], p3["refuted_by"]))
    check("(a) (5) ← inaccurate بتصحيح 77.5 مليون",
          p5["verdict"] == "inaccurate" and "77.5" in p5["correction"]["correct"]
          and len(p5["correction"]["sources"]) == 2, p5["correction"])
    check("(a) (1) و(4) ← not_found مع nearest وبلا إسقاط",
          all(p["verdict"] == "not_found" and p["nearest"] and p["dropped_reason"] is None
              for p in (p1, p4)), [(p["verdict"], p["nearest"]) for p in (p1, p4)])
    # النقطة 2 بلا كيانات: لا كيان مشترك ممكن ← nearest null (#1200) فتسقط بسببها
    check("(a) (2) بلا كيانات ← not_found بلا nearest",
          p2["verdict"] == "not_found" and p2["nearest"] is None, p2["nearest"])
    check("(a) asserted محفوظ للعرض (النقطة 2 بلا أسماء ولم تسقط) وclaim حاضر",
          "مارس 2025" in p2["asserted"] and all(p["claim"] == p["text"] for p in pts), p2["asserted"])
    check("(a) النقطة 3 (تاريخ 2016) بُحثت بنافذة أوسع ثم بلا قيد",
          p3["windows"][:2] == ["wide", "unrestricted"], p3["windows"])
    fields = {"claim", "asserted", "queries", "engines", "docs_before", "docs_after"}
    check("(a) الحقول الجديدة لكل نقطة (البند 5)", all(fields <= set(p) for p in pts),
          [fields - set(p) for p in pts])
    mc = saved["model_calls"]
    # #1203: نقطة كيانها «تركيا» بلا عبارة تركية من الاستخراج تُطلب لها عبارتها بنداء
    # Haiku ثانٍ قصير (نقطتان هنا) — فنداء التفكيك واحد، وكل نداءات «brief» من Haiku
    check("(a) نداء تفكيك واحد (Haiku) + نداءات لغة أم، كلها Haiku، والملف "
          "يحمل طلبات Brave وسبب غيابها",
          mc["brief"] >= 1 and mc["brief"] == mc["by_model"].get(cfg.path("important.extract_model"))
          and mc["by_model"].get(cfg.path("article.model")) == len(pts)
          and saved["brave"]["skipped"] == "no_key", (mc, saved.get("brave")))

    # ── (b) نقطة بلا أسماء ← تُبحث بعباراتها ولا تسقط قبل البحث ──
    nm = {"claim": "مقطع متداول عن فيضان في مدينة ساحلية", "asserted": "", "entities": [],
          "dates": [], "numbers": [],
          "queries": [_q("ar", "مقطع فيضان مدينة ساحلية عبارةسحابة"), _q("en", "coastal flood video")],
          "factcheck_query": ""}
    docs_b = {"عبارةسحابة": [important_doc("صحيفة الشرق", "فيضان المدينة الساحلية حدث فعلًا."),
                             important_doc("موقع الغرب", "تقرير مستقل عن فيضان المدينة الساحلية.")]}

    def supports(point, names):
        return {"sources": [important_stance(x, "supports", "فيضان") for x in names]}

    with ImportantRig([nm], docs_b, supports) as rig_b:
        important.judge("نص Issue رقم 10", 96002, cfg)
    pb = important.load_saved(96002)["points"][0]
    check("(b) نقطة بلا كيانات تُبحث بعباراتها وتُحكم (لا إسقاط قبل البحث)",
          pb["verdict"] == "confirmed" and nm["queries"][0]["q"] in rig_b.queries
          and pb["dropped_reason"] is None and "تعذّر تسمية" not in pb["note"], pb)
    # بلا كيانات وبلا عبارات أيضًا: تُبحث بنصها مباشرة
    bare = {"claim": "انهيار جسر عبارةنخلة الجديد", "entities": []}
    docs_b2 = {"عبارةنخلة": [important_doc("صحيفة الشرق", "انهار جسر عبارةنخلة."),
                             important_doc("موقع الغرب", "مستقل: انهيار جسر عبارةنخلة.")]}
    with ImportantRig([bare], docs_b2, lambda p, n: {"sources": [
            important_stance(x, "supports", "انهار جسر") for x in n]}) as rig_b2:
        important.judge("نص Issue رقم 11", 96003, cfg)
    check("(b) بلا كيانات وبلا عبارات ← بحث بنص الادّعاء نفسه ولا إسقاط",
          important.load_saved(96003)["points"][0]["verdict"] == "confirmed"
          and any("عبارةنخلة" in q for q in rig_b2.queries), rig_b2.queries)
    # فشل تسمية حدث مبهم لا يُسقط نقطة لها عبارات بحث
    vague = dict(nm, is_unnamed_event=True)
    real_name = article._name_event
    article._name_event = lambda f, cfg_, topic="": (None, [], [], [])  # type: ignore
    try:
        with ImportantRig([vague], docs_b, supports):
            important.judge("نص Issue رقم 12", 96004, cfg)
    finally:
        article._name_event = real_name  # type: ignore
    pv = important.load_saved(96004)["points"][0]
    check("(b) فشل _name_event لا يُسقط نقطة لها عبارات (ملاحظة فقط)",
          pv["verdict"] == "confirmed" and "تعذّرت تسمية الحدث" in pv["note"], pv)

    # ── (c) نافذة أوسع ثم بلا قيد ──
    old = {"claim": "صورة قديمة تعود إلى عام 2016 عن عبارةزيتون", "entities": ["عبارةزيتون"],
           "dates": ["2016"], "numbers": [],
           "queries": [_q("ar", "صورة قديمة عبارةزيتون")], "factcheck_query": ""}
    wide = cfg.path("important.wide_days")
    days = cfg.path("important.days")
    docs_c = {"عبارةزيتون": [important_doc("صحيفة الشرق", "نص عن الصورة.")]}
    with ImportantRig([old], docs_c, lambda p, n: {"sources": []},
                      unrestricted_only=["عبارةزيتون"]) as rig_c:
        important.judge("نص Issue رقم 13", 96005, cfg)
    steps = [(d, u) for _q_, d, u in rig_c.searches]
    check("(c) تاريخ 2016 ← نافذة wide_days ثم بلا قيد، ولا نافذة days أصلًا",
          steps[0] == (wide, False) and steps[1][1] is True and all(d != days for d, _ in steps),
          steps)
    plain = {"claim": "حادثة حديثة عبارةتينة", "entities": ["عبارةتينة"], "dates": [], "numbers": [],
             "queries": [_q("ar", "حادثة حديثة عبارةتينة")], "factcheck_query": ""}
    with ImportantRig([plain], {"عبارةتينة": [important_doc("صحيفة الشرق", "نص.")]},
                      lambda p, n: {"sources": []}, unrestricted_only=["عبارةتينة"]) as rig_c2:
        important.judge("نص Issue رقم 14", 96006, cfg)
    steps2 = [(d, u) for _q_, d, u in rig_c2.searches]
    check("(c) صفر نتائج بالنافذة العادية ← wide_days ← بلا قيد بالترتيب",
          steps2 == [(days, False), (wide, False), (wide, True)], steps2)

    # ── (d) Brave: بلا مفتاح ← Google وحدها وسجل في الملف؛ ومعه ← يُستعمل ويُعدّ ──
    pt_d = {"claim": "واقعة عبارةرمان للبحث", "entities": ["عبارةرمان"], "dates": [], "numbers": [],
            "queries": [_q("ar", "واقعة عبارةرمان")], "factcheck_query": "عبارةرمان تحقق"}
    docs_d = {"عبارةرمان": [important_doc("صحيفة الشرق", "نص عن عبارةرمان.")]}

    def cls_d(point, names):
        return {"sources": [important_stance(x, "irrelevant") for x in names]}

    usage = imagesearch.BRAVE_USAGE_FILE
    usage.unlink(missing_ok=True)
    with ImportantRig([pt_d], docs_d, cls_d) as rig_d:
        important.judge("نص Issue رقم 15", 96007, cfg)
    sd = important.load_saved(96007)
    check("(d) بلا مفتاح ← Google وحدها، لا طلب Brave، والملف يسجّل السبب بلا خطأ",
          rig_d.brave_calls == [] and sd["points"][0]["engines"] == ["google_news"]
          and sd["brave"]["skipped"] == "no_key" and sd["brave"]["requests"] == 0
          and sd["error"] is None, (sd["brave"], sd["points"][0]["engines"]))
    brave = {"عبارةرمان": [
        brave_result("https://www.example-news.com/a", "خبر عبارةرمان", "وصف", "موقع الأخبار"),
        brave_result("https://www.facebook.com/p/9", "منشور عبارةرمان", "نفي", "فيسبوك")]}
    with ImportantRig([pt_d], docs_d, cls_d, brave_results=brave, brave_key="k-test") as rig_d2:
        important.judge("نص Issue رقم 16", 96008, cfg)
    sd2 = important.load_saved(96008)
    pd2 = sd2["points"][0]
    check("(d) بمفتاح ← Brave يُستعمل لكل عبارة ولعبارة التدقيق ويُسجَّل في الملف",
          len(rig_d2.brave_calls) == 2 and "brave_web" in pd2["engines"]
          and sd2["brave"]["requests"] == 2 and sd2["brave"]["monthly_usage"] == 2, sd2["brave"])
    check("(d) نتيجة Brave من facebook.com تُستبعد قبل جمع الأدلة",
          pd2["docs_after"] == 2 and pd2["sources_read"] == 2, (pd2["docs_before"], pd2["docs_after"]))

    # ── (e) عدّادا Brave مستقلان: صور البطاقات وبحث «هام» ──
    month_img, month_imp = imagesearch._month_key(), important._usage_key()
    cap_imp = cfg.path("important.brave_monthly_cap")
    cap_img = cfg.path("image.web_search.monthly_cap")

    def run_images() -> int:
        # بحث صور البطاقات الحقيقي (imagesearch.search_web_images) عبر requests.get مزيَّف
        import requests as _r
        inner, hits = _r.get, []

        def fake_get(url, **kw):
            if "images/search" in url:
                hits.append(url)

                class R:
                    status_code = 200

                    def json(self_):
                        return {"results": []}
                return R()
            return inner(url, **kw)
        _r.get = fake_get
        os.environ["BRAVE_API_KEY"] = "k-test"
        try:
            imagesearch.search_web_images("استعلام صورة", cfg, {})
        finally:
            _r.get = inner
            os.environ.pop("BRAVE_API_KEY", None)
        return len(hits)

    usage.write_text(json.dumps({month_imp: cap_imp}))
    images_called = run_images()
    with ImportantRig([pt_d], docs_d, cls_d, brave_results=brave, brave_key="k-test") as rig_e1:
        important.judge("نص Issue رقم 17", 96009, cfg)
    s_e1 = important.load_saved(96009)
    check("(e) بلوغ سقف «هام» لا يوقف بحث صور البطاقات، و«هام» يتخطّى بسبب السقف",
          images_called == 1 and rig_e1.brave_calls == [] and s_e1["brave"]["skipped"] == "cap",
          (images_called, s_e1["brave"]))
    data_e = json.loads(usage.read_text())
    check("(e) مفتاحا العدّاد منفصلان في الملف نفسه ولا يمحو أحدهما الآخر",
          data_e.get(month_imp) == cap_imp and data_e.get(month_img) == 1, data_e)
    usage.write_text(json.dumps({month_img: cap_img}))
    with ImportantRig([pt_d], docs_d, cls_d, brave_results=brave, brave_key="k-test") as rig_e2:
        important.judge("نص Issue رقم 18", 96010, cfg)
    data_e2 = json.loads(usage.read_text())
    check("(e) بلوغ سقف الصور لا يوقف بحث «هام» ولا يمسّ عدّاد الصور",
          len(rig_e2.brave_calls) == 2 and data_e2.get(month_img) == cap_img
          and data_e2.get(month_imp) == 2, data_e2)
    usage.unlink(missing_ok=True)

    # ── (f) الجمع لا يتوقف عند أول عبارة، والسقف 8 وثائق يُحترم ──
    marks = ("عبارةأ", "عبارةب", "عبارةج", "عبارةد")
    many = {"claim": "واقعة كبيرة متعددة المصادر", "entities": ["عبارةأ"], "dates": [],
            "numbers": [], "factcheck_query": "",
            # لغتان بعبارتين لكل منهما: حد queries_per_lang (2) يُفرض في الكود
            "queries": [_q(lang, f"واقعة {m}") for lang, m in zip(("ar", "ar", "en", "en"), marks)]}
    docs_f = {m: [important_doc(f"ناشر {m} {i}", f"نص {m} {i}.",
                                link=f"https://pub-{m}-{i}.example/a") for i in range(3)]
              for m in marks}
    seen_names: list[list[str]] = []

    def cls_f(point, names):
        seen_names.append(list(names))
        return {"sources": [important_stance(n, "irrelevant") for n in names]}

    with ImportantRig([many], docs_f, cls_f) as rig_f:
        important.judge("نص Issue رقم 19", 96011, cfg)
    pf = important.load_saved(96011)["points"][0]
    check("(f) الجمع يتجاوز أول عبارة (أكثر من عبارة وأكثر من 3 وثائق)",
          len(set(rig_f.queries)) >= 3 and pf["docs_before"] > 3, (rig_f.queries, pf["docs_before"]))
    check("(f) سقف max_docs_per_point (8) محترم في التصنيف والملف",
          cfg.path("important.max_docs_per_point") == 8 and pf["docs_after"] == 8
          and pf["sources_read"] <= 8 and len(seen_names[0]) <= 8,
          (pf["docs_after"], pf["sources_read"], len(seen_names[0])))

    # ── جهة التدقيق بالنطاق، والنطاقات المستبعدة، وحد العبارات ──
    icfg = cfg.get("important", {})
    check("نطاق مدقّق يكفي، وreuters.com وحدها لا، ومسار /fact-check/ فيها نعم",
          important._is_fact_checker("x", icfg, "https://misbar.com/a")
          and not important._is_fact_checker("Reuters", icfg, "https://www.reuters.com/world/a")
          and important._is_fact_checker("Reuters", icfg, "https://www.reuters.com/fact-check/a")
          and not important._is_fact_checker("x", icfg, "https://notmisbar.com/a")
          and important._is_fact_checker("مسبار", icfg))
    check("النطاقات المستبعدة تشمل النطاقات الفرعية ولا تطابق نطاقًا يشبهها",
          important._is_excluded_domain("https://m.facebook.com/a", icfg)
          and important._is_excluded_domain("https://t.me/x", icfg)
          and not important._is_excluded_domain("https://box.com/x", icfg)
          and not important._is_excluded_domain("https://bbc.com/x", icfg))
    check("حد عبارات البحث لكل لغة يُفرض في الكود",
          len(important._queries_per_lang(
              [_q("ar", "أ"), _q("ar", "ب"), _q("ar", "ج"), _q("en", "d")], 2)) == 3)


# ───────────── Issue #1200 (المهمة 1ج): same_event وnearest بكيان ومقتطفات وread_docs ─────────────

def _sections(content: str) -> dict[str, str]:
    """نص الوثائق كما وصل نداء التصنيف ← {اسم المصدر: ما أُرسل منه}."""
    parts = re.split(r"--- المصدر: (.*?) ---\n", content)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def regression_1197_second(issue: int = 97001) -> dict:
    """النص نفسه #1197 بالمصادر التي ظهرت فعلًا في التشغيل الحقيقي الثاني: قانون
    القاصرين (UrduPoint وTRT) للنقطة 1، وCNN عن سوريا للنقطة 2، ومسبار برابط
    news.google.com للنقطة 3، وA News وTRT للنقطة 4، وصفحة DataReportal طويلة للنقطة 5."""
    from src import important, sources

    cfg = load_config()
    points = [
        {"claim": "تركيا أعلنت في 2026 إطلاق منظومة جديدة لمراقبة المحتوى المضلل على منصات التواصل",
         "entities": ["تركيا"], "dates": ["2026"], "numbers": [],
         "queries": [_q("ar", "تركيا تطلق منظومة جديدة لمراقبة المحتوى المضلل")],
         "factcheck_query": ""},
        {"claim": "فيديو متداول زُعم أنه يوثق مظاهرات حديثة في تركيا احتجاجًا على ارتفاع أسعار الغذاء والوقود",
         "entities": ["تركيا"], "dates": [], "numbers": [],
         "queries": [_q("ar", "فيديو مظاهرات حديثة في تركيا ارتفاع أسعار الغذاء والوقود")],
         "factcheck_query": ""},
        {"claim": "صورة لعنصرين من القوات الخاصة التركية يُزعم أنها تتضمن اعترافًا بمجزرة في عفرين",
         "entities": ["القوات الخاصة التركية", "عفرين"], "dates": ["2016"], "numbers": [],
         "queries": [_q("ar", "صورة القوات الخاصة التركية اعتراف مجزرة عفرين")],
         "factcheck_query": ""},
        {"claim": "تركيا بدأت استخدام طائرات مسيرة جديدة يصل مداها إلى 800 كيلومتر",
         "entities": ["تركيا"], "dates": [], "numbers": ["800 كيلومتر"],
         "queries": [_q("ar", "تركيا طائرات مسيرة جديدة مدى 800 كيلومتر")],
         "factcheck_query": ""},
        {"claim": "عدد مستخدمي الإنترنت في تركيا تجاوز 90 مليون مستخدم خلال 2026",
         "entities": ["تركيا"], "dates": ["2026"], "numbers": ["90 مليون"],
         "queries": [_q("ar", "عدد مستخدمي الإنترنت في تركيا 2026 مليون")],
         "factcheck_query": ""},
    ]
    minors = ("أقرّت تركيا قانونًا يقيّد استخدام القاصرين دون 15 عامًا لمنصات التواصل "
              "الاجتماعي مع آليات تحقق من الهوية.")
    syria = "اندلعت احتجاجات في محافظات سورية بعد قرار الحكومة رفع أسعار المحروقات."
    refute_txt = "الصورة معدّلة، والكتابة عليها مفبركة، وأصلها يعود إلى عام 2016"
    google_link = "https://news.google.com/rss/articles/CBMiygNBVV95cUxQRVpJLXh"
    # صفحة DataReportal: 25 فقرة؛ كثير منها يذكر Türkiye بلا الرقم، والرقم في فقرة متأخرة
    filler = []
    for i in range(24):
        if i % 2 == 0:
            filler.append(f"Digital 2026 overview, section {i}: global social media trends and "
                          f"ad spending across regions, with Türkiye mentioned in the context "
                          f"of platform use and time spent online per day, part {i}.")
        else:
            filler.append(f"Section {i}: worldwide mobile connections, e-commerce adoption and "
                          f"streaming habits, a long general discussion of digital behaviour.")
    filler.insert(21, "Türkiye had 77.5 million internet users at the start of 2026, "
                      "according to the DataReportal Digital 2026 analysis.")
    datareportal = "\n\n".join(filler)
    docs = {
        "منظومة": [important_doc("UrduPoint", minors, link="https://www.urdupoint.com/arabic/story/1.html"),
                   important_doc("TRT Arabi", minors + " وفق التقارير.",
                                 link="https://www.trtarabi.com/article/1")],
        "مظاهرات": [important_doc("CNN Arabic", syria, link="https://arabic.cnn.com/a/fuel"),
                    important_doc("عنب بلدي", syria + " مستقل.", link="https://enabbaladi.net/x")],
        "عفرين": [important_doc("موقع مسبار", refute_txt, link=google_link)],
        "مسيرة": [important_doc("A News", "K2 has a range of more than 2,000 kilometers (1,240 miles).",
                                link="https://www.anews.com.tr/k2"),
                  important_doc("TRT World", "The K2 drone range exceeds 2,000 kilometers, Baykar said.",
                                link="https://www.trtworld.com/k2")],
        "الإنترنت": [important_doc("DataReportal", datareportal,
                                   link="https://datareportal.com/reports/digital-2026-turkiye"),
                     important_doc("موقع الأرقام", "تقرير Digital 2026: 77.5 مليون مستخدم للإنترنت في تركيا.",
                                   link="https://raqam.example/t"),
                     important_doc("موقع الرياضة", "نتائج مباريات الدوري المحلي هذا الأسبوع.",
                                   link="https://sport.example/s")],
    }

    def classify(point, names):
        sec = _sections(rig.last_content)
        if "منظومة" in point:
            return {"sources": [important_stance(n, "conflicts_detail", "قانونًا يقيّد", detail="قانون آخر",
                                                 correct_form="قانون القاصرين", same_event=False)
                                for n in names],
                    "nearest_events": [{"title": "قانون تركي لحماية القاصرين على المنصات — تركيا",
                                        "description": "قانون يقيّد استخدام من هم دون 15 عامًا",
                                        "sources": list(names)}]}
        if "مظاهرات" in point:
            return {"sources": [important_stance(n, "supports", "احتجاجات", same_event=False)
                                for n in names],
                    "nearest_events": [{"title": "احتجاجات في سوريا على رفع أسعار المحروقات",
                                        "description": syria, "sources": list(names)}]}
        if "عفرين" in point:
            return {"sources": [important_stance(n, "refutes", "الصورة معدّلة") for n in names]}
        if "مسيرة" in point:
            return {"sources": [important_stance(
                n, "conflicts_detail", "more than 2,000 kilometers", detail="مدى K2",
                correct_form="range of more than 2,000 kilometers") for n in names]}
        return {"sources": [
            important_stance(n, "conflicts_detail", "77.5 million", detail="العدد 90 مليونًا لا 77.5",
                             correct_form="77.5 مليون مستخدم")
            if "77.5" in sec.get(n, "") else important_stance(n, "irrelevant", same_event=False)
            for n in names]}

    real = sources.resolve_final_url
    sources.resolve_final_url = lambda url, timeout=12: (
        "https://misbar.com/factcheck/2026/02/19/afrin-photo" if url == google_link else url)
    try:
        with ImportantRig(points, docs, classify) as rig:
            important.judge(BODY_1197, issue, cfg)
    finally:
        sources.resolve_final_url = real
    saved = important.load_saved(issue)
    saved["_contents"] = list(rig.contents)
    return saved


def test_important_same_event_and_excerpts() -> None:
    from src import important, sources

    cfg = load_config()
    saved = regression_1197_second()
    p1, p2, p3, p4, p5 = saved["points"]

    # (a) انحدار #1197 الثاني
    check("(a) (1) ← not_found لا inaccurate (قانون القاصرين حدث آخر)",
          p1["verdict"] == "not_found" and p1["correction"] is None, (p1["verdict"], p1["correction"]))
    n1 = p1["nearest"]
    rel = {d["publisher"] for d in p1["read_docs"] if d["stance"] == "related_other"}
    check("(a) (1) nearest، إن وُجد، يشارك كيانًا ومصدراه related_other",
          n1 is None or (n1["shared_entity"] and {s["publisher"] for s in n1["sources"]} <= rel), n1)
    check("(a) (2) nearest ليس سوريا (لا كيان مشترك مع نقطة عن تركيا)",
          p2["verdict"] == "not_found" and p2["nearest"] is None, p2["nearest"])
    check("(a) (3) ← false بمدقّق وبرابط misbar.com المحلول",
          p3["verdict"] == "false" and p3["refuted_by"][0]["link"].startswith("https://misbar.com/")
          and p3["refuted_by"][0]["fact_checker"], p3["refuted_by"])
    check("(a) (4) ← inaccurate بـK2 (2000 كم)",
          p4["verdict"] == "inaccurate" and "2,000" in p4["correction"]["correct"], p4["correction"])
    check("(a) (5) ← inaccurate بتصحيح 77.5 مليون من الفقرة المتأخرة",
          p5["verdict"] == "inaccurate" and "77.5" in p5["correction"]["correct"]
          and len(p5["correction"]["sources"]) == 2, (p5["verdict"], p5["correction"]))

    # اختيار المقتطف: الفقرة المتأخرة وصلت التصنيف والصفحة أطول من المقتطف
    dr = next(d for d in p5["read_docs"] if d["publisher"] == "DataReportal")
    budget = cfg.path("important.tokens_per_source") * cfg.path("important.chars_per_token")
    check("(a) فقرة 77.5 المتأخرة (من أكثر من 20 فقرة) اختيرت ضمن الميزانية",
          dr["page_chars"] > budget >= dr["excerpt_chars"] > 0
          and any("77.5 million" in c for c in saved["_contents"]), (dr, budget))
    check("(a) tokens_per_source الافتراضي 600", cfg.path("important.tokens_per_source") == 600)

    # (b) read_docs بكل الوثائق ومنها irrelevant
    keys = {"publisher", "link", "engine", "page_chars", "excerpt_chars", "same_event", "stance"}
    check("(b) read_docs لكل نقطة بالحقول المطلوبة وبعدد الوثائق المقروءة",
          all(keys <= set(d) for p in saved["points"] for d in p["read_docs"])
          and all(len(p["read_docs"]) == p["docs_after"] for p in saved["points"]),
          [(len(p["read_docs"]), p["docs_after"]) for p in saved["points"]])
    check("(b) read_docs فيها irrelevant والمحرّك مسجَّل",
          any(d["stance"] == "irrelevant" for d in p5["read_docs"])
          and all(d["engine"] == "google_news" for d in p5["read_docs"]), p5["read_docs"])

    # (c) رابط Google محلول، ومسبار يُعرف بالنطاق المحلول
    d3 = p3["read_docs"][0]
    check("(c) رابط news.google.com يُحفظ محلولًا مع الأصلي",
          d3["link"].startswith("https://misbar.com/") and d3["resolved"] is True
          and d3["orig_link"].startswith("https://news.google.com/"), d3)
    marker = "كلمةهام1200"
    pt = important_point(marker, f"وقعت حادثة {marker} في المدينة")
    gl = "https://news.google.com/rss/articles/XYZ"
    real = sources.resolve_final_url
    sources.resolve_final_url = lambda url, timeout=12: "https://www.misbar.com/factcheck/q"
    try:
        with ImportantRig([pt], {marker: [important_doc(
                "ناشر مجهول الاسم", "تنفي المصادر وقوع الحادثة وتؤكد أنها لم تحدث إطلاقًا.",
                link=gl)]}, lambda p, n: {"sources": [
                    important_stance(x, "refutes", "لم تحدث إطلاقًا") for x in n]}):
            important.judge("نص", 97002, cfg)
        pc = important.load_saved(97002)["points"][0]
        sources.resolve_final_url = lambda url, timeout=12: url
        with ImportantRig([pt], {marker: [important_doc("ناشر مجهول الاسم", "نص.", link=gl)]},
                          lambda p, n: {"sources": [important_stance(x, "irrelevant") for x in n]}):
            important.judge("نص", 97003, cfg)
        pu = important.load_saved(97003)["points"][0]
    finally:
        sources.resolve_final_url = real
    check("(c) مدقّق معروف بالنطاق المحلول وحده (الاسم مجهول) ⇒ false",
          pc["verdict"] == "false", (pc["verdict"], pc["note"]))
    check("(c) تعذّر الحل ← الرابط الأصلي وresolved=false",
          pu["read_docs"][0]["link"] == gl and pu["read_docs"][0]["resolved"] is False,
          pu["read_docs"])


# ───────────── Issue #1203 (المهمة 1د): سقف الصفحة، اتفاق الأرقام، الادّعاء المتداول ─────────────

# نصوص نقاط #1201 كما في state/important/1201.json
P1201 = {
    "baykar": "أعلنت شركة بايكار أن الطائرة المسيّرة الهجومية بيرقدار أقنجي تمكنت خلال اختبار إطلاق من "
              "إصابة هدف يبعد أكثر من 250 كيلومترًا باستخدام صاروخ بالستي فرط صوتي",
    "pop": "بلغ عدد سكان تركيا في نهاية عام 2025 نحو 85.7 مليون نسمة",
    "video": "أرسلت تركيا 450 ألف جندي إلى سوريا",
    "space": "أعلنت تركيا خلال عام 2026 تشغيل أول شبكة إنترنت فضائي حكومية تركية بالكامل تغطي جميع أنحاء البلاد",
    "users": "عدد مستخدمي الإنترنت في تركيا بلغ نحو 77.5 مليون مستخدم، أي ما يقارب 88% من السكان",
}
CTX_1201 = "انتشر على مواقع التواصل الاجتماعي خلال صيف 2026 مقطع فيديو قيل إنه يُظهر إرسال تركيا 450 ألف جندي إلى سوريا"


def regression_1201(issue: int = 98001):
    """نقاط #1201 الخمس بالوثائق التي ظهرت فعلًا في read_docs، وصفحة DataReportal
    كاملة يقع فيها 77.5 بعد الحرف 2500."""
    from src import important

    cfg = load_config()
    points = [
        {"claim": P1201["baykar"], "entities": ["بيرقدار"], "numbers": ["250 كيلومتر"],
         "queries": [_q("ar", "بيرقدار أقنجي إصابة 250 كيلومتر")], "factcheck_query": ""},
        {"claim": P1201["pop"], "entities": ["سكان"], "numbers": ["85.7 مليون"], "dates": ["2025"],
         "queries": [_q("ar", "عدد سكان تركيا 2025 85.7 مليون")], "factcheck_query": ""},
        {"claim": P1201["video"], "framing": "circulating", "circulating_context": CTX_1201,
         "asserted": "كذّبت Teyit الادّعاء", "entities": ["تركيا", "سوريا"], "numbers": ["450 ألف"],
         "queries": [_q("ar", "تركيا 450 ألف جندي سوريا"), _q("en", "Turkey 450000 soldiers Syria")],
         "factcheck_query": ""},
        {"claim": P1201["space"], "entities": ["فضائي"], "dates": ["2026"],
         "queries": [_q("ar", "تركيا شبكة إنترنت فضائي حكومية")], "factcheck_query": ""},
        {"claim": P1201["users"], "entities": ["الإنترنت"], "numbers": ["77.5 مليون"],
         "queries": [_q("ar", "مستخدمو الإنترنت في تركيا 77.5 مليون")], "factcheck_query": ""},
    ]
    fill = []
    for i in range(30):
        fill.append(f"Digital 2026 section {i}: global social media trends, ad spending and time spent "
                    f"online across regions, a long general discussion with Türkiye mentioned in passing, "
                    f"part {i} of the report with plenty of filler text to push the figure deep.")
    fill.insert(28, "Türkiye had 77.5 million internet users at the start of 2026 (88 percent of the "
                    "population), according to DataReportal Digital 2026.")
    datareportal = "\n\n".join(fill)
    assert datareportal.index("77.5 million") > 2500
    docs = {
        "بيرقدار": [important_doc("Alsaudi", "بيرقدار أقنجي أصابت هدفًا يبعد أكثر من 250 كيلومترًا.",
                                  link="https://alsaudi.news/international/1109/96875"),
                    important_doc("Yeni Şafak", "أعلنت بايكار إصابة هدف على بعد 250 كيلومترًا بأقنجي.",
                                  link="https://www.yenisafak.com/ar/economy/4131591"),
                    important_doc("News-pravda", "أصابت بيرقدار أقنجي هدفًا يبعد 250 كيلومترًا.",
                                  link="https://syria.news-pravda.com/syria/2026/09/11/323210.html")],
        "سكان": [important_doc("newturkpost", "بلغ عدد سكان تركيا 86 مليوناً و92 ألفاً و168 نسمة "
                               "في نهاية 2025.", link="https://newturkpost.com/news/118693"),
                 important_doc("TRADING ECONOMICS", "عدد سكان تركيا 86.1 مليون نسمة في 2025.",
                               link="https://ar.tradingeconomics.com/turkey/population")],
        "450": [important_doc("Al Jazeera", "الفيديو المتداول قديم، ولم تُرسل تركيا 450 ألف جندي إلى سوريا.",
                              link="https://www.aljazeera.net/news/2026/8/23/video"),
                important_doc("CNN", "مقطع قديم يُتداول زورًا؛ لم تُرسل تركيا 450 ألف جندي إلى سوريا.",
                              link="https://arabic.cnn.com/middle-east/article/2026/08/22/old-video")],
        "فضائي": [important_doc("Daily Sabah", "نفت تركيا مزاعم عن شبكة إنترنت فضائي.",
                                link="https://www.dailysabah.com/business/tech/x"),
                  important_doc("Eutelsat", "خدمات أقمار صناعية في تركيا.", link="https://www.eutelsat.com/turkiye")],
        "الإنترنت": [important_doc("Global Digital Insights", datareportal,
                                   link="https://datareportal.com/reports/digital-2026-turkey"),
                     important_doc("موقع الأرقام", "تقرير Digital 2026: 77.5 مليون مستخدم للإنترنت في تركيا.",
                                   link="https://raqam.example/t")],
    }
    forms = {"newturkpost": "86 مليوناً و92 ألفاً و168 نسمة", "TRADING ECONOMICS": "86.1 مليون نسمة"}
    refute_cut = {"Al Jazeera": "ولم تُرسل تركيا 450 ألف جندي إلى سوريا",
                  "CNN": "لم تُرسل تركيا 450 ألف جندي إلى سوريا"}

    def classify(point, names):
        sec = _sections(rig.last_content)
        if "بيرقدار" in point:
            return {"sources": [important_stance(n, "supports", "250 كيلومترًا") for n in names]}
        if "85.7" in point:
            return {"sources": [important_stance(n, "conflicts_detail", forms[n], detail="العدد 85.7 غير دقيق",
                                                 correct_form=forms[n]) for n in names]}
        if "450" in point:
            return {"sources": [important_stance(n, "refutes", refute_cut[n]) for n in names]}
        if "فضائي" in point:
            return {"sources": [important_stance(n, "irrelevant", same_event=False) for n in names]}
        return {"sources": [important_stance(n, "supports", "77.5 million") if "77.5" in sec.get(n, "")
                            else important_stance(n, "irrelevant") for n in names]}

    with ImportantRig(points, docs, classify, native={"tr": ["Türkiye 450 bin asker Suriye video"]}) as rig:
        important.judge("\n".join(P1201.values()) + "\n" + CTX_1201, issue, cfg)
    saved = important.load_saved(issue)
    saved["_rig"] = rig
    return saved


def test_important_1203() -> None:
    import inspect
    import types
    from datetime import datetime, timezone
    from decimal import Decimal
    from src import article, evidence, extract, important
    from src.sources import Article

    cfg = load_config()
    icfg = cfg.path("important")

    # (a) الأنبوب على نقاط #1201 الخمس
    saved = regression_1201()
    rig = saved["_rig"]
    p1, p2, p3, p4, p5 = saved["points"]
    check("(a) (1) ← confirmed بمصدرين ولا يُحسب news-pravda",
          p1["verdict"] == "confirmed" and {e["publisher"] for e in p1["evidence"]} == {"Alsaudi", "Yeni Şafak"}
          and all("news-pravda" not in d["link"] for d in p1["read_docs"]), (p1["verdict"], p1["evidence"]))
    check("(a) (2) ← inaccurate والصحيح 86,092,168 (أدقّ الصيغتين)",
          p2["verdict"] == "inaccurate" and p2["correction"]["correct_value"] == "86,092,168"
          and "168" in p2["correction"]["correct"], p2["correction"])
    check("(a) (3) ← false بمصدري CNN والجزيرة والمضمون هو الادّعاء",
          p3["verdict"] == "false" and {r["publisher"] for r in p3["refuted_by"]} == {"Al Jazeera", "CNN"}
          and p3["framing"] == "circulating" and p3["claim"] == P1201["video"], (p3["verdict"], p3["refuted_by"]))
    check("(a) (4) ← not_found وسقطت (لا أثر)",
          p4["verdict"] == "not_found" and p4["dropped_reason"] == important.NO_TRACE_REASON,
          (p4["verdict"], p4["dropped_reason"]))
    dr = next(d for d in p5["read_docs"] if d["publisher"] == "Global Digital Insights")
    check("(a) (5) ← confirmed من فقرة بعد الحرف 2500 (الصفحة كاملة والمقتطف يحوي الرقم)",
          p5["verdict"] == "confirmed" and dr["page_chars"] > 2500
          and any("77.5 million" in c for c in rig.contents), (p5["verdict"], dr))
    check("(a) كل جلب لمسار «هام» بسقف page_max_chars (20000)",
          icfg["page_max_chars"] == 20000 and rig.max_chars_seen and set(rig.max_chars_seen) == {20000},
          set(rig.max_chars_seen))

    # (b) غير «هام» ما زال يقصّ عند 2500: extract بلا المعامل، وevidence لا تمرّره بلا قيمة
    html = " ".join(["كلمة"] * 6000)

    class _Resp:
        status_code = 200
        text = html

    real = (getattr(extract, "trafilatura", None), extract.HAS_EXTRACTOR,
            extract.requests.get, evidence.extract.gather)
    extract.trafilatura = types.SimpleNamespace(extract=lambda h, **kw: h)
    extract.HAS_EXTRACTOR = True
    extract.requests.get = lambda url, **kw: _Resp()
    try:
        default_txt, _ = extract.fetch_text("https://x.example/a")
        long_txt, _ = extract.fetch_text("https://x.example/a", max_chars=20000)
        got_default, _ = extract.gather([{"name": "A", "link": "https://x.example/a"}], limit=1)
        got_long, _ = extract.gather([{"name": "A", "link": "https://x.example/a"}], limit=1,
                                     max_chars=20000)
        seen_kw: list[dict] = []
        evidence.extract.gather = lambda members, limit=2, **kw: (seen_kw.append(kw) or ([], []))
        arts = [Article(title="t", link="https://a.example/1", summary="s", source_name="Reuters",
                        region="global", weight=1.0, published=datetime.now(timezone.utc),
                        publisher="Reuters")]
        evidence.gather_evidence(arts, cfg)
        evidence.gather_evidence(arts, cfg, max_chars=20000)
    finally:
        if real[0] is not None:
            extract.trafilatura = real[0]
        extract.HAS_EXTRACTOR, extract.requests.get, evidence.extract.gather = real[1:]
    check("(b) fetch_text/gather بلا المعامل يقصّان عند MAX_CHARS (2500)",
          extract.MAX_CHARS == 2500 and len(default_txt) == 2500 and len(got_default[0]["text"]) == 2500,
          (len(default_txt), len(got_default[0]["text"])))
    check("(b) المعامل الاختياري يرفع السقف لنداء «هام» وحده",
          len(html) > 20000 and len(long_txt) == 20000 and len(got_long[0]["text"]) == 20000,
          len(long_txt))
    check("(b) evidence.gather_evidence لا يمرّر max_chars بلا قيمة ويمرّره بها",
          seen_kw == [{}, {"max_chars": 20000}], seen_kw)

    # (c) محلّل الأرقام
    def vals(t):
        return [v for v, _y in important.parse_numbers(t, icfg)]

    check("(c) «86 مليوناً و92 ألفاً و168» = 86092168 (والسنة تبقى رقمًا منفصلًا)",
          vals("86 مليوناً و92 ألفاً و168 نسمة") == [Decimal(86092168)]
          and vals("86 مليوناً و92 ألفاً و168 نهاية 2025") == [Decimal(86092168), Decimal(2025)],
          vals("86 مليوناً و92 ألفاً و168 نهاية 2025"))
    check("(c) كسور مع مقياس: مليون/million/milyon/مليار/billion/ألف/bin",
          vals("86.1 مليون") == vals("86.1 million") == vals("86,1 milyon") == [Decimal(86100000)]
          and vals("1.5 مليار") == vals("1.5 billion") == [Decimal(1500000000)]
          and vals("450 ألف") == vals("450 bin") == vals("450 thousand") == [Decimal(450000)],
          [vals("86.1 مليون"), vals("1.5 مليار"), vals("450 ألف")])
    check("(c) فواصل الآلاف بالفاصلة والنقاط: 86,092,168 و1.234.567",
          vals("86,092,168") == [Decimal(86092168)] and vals("1.234.567") == [Decimal(1234567)],
          (vals("86,092,168"), vals("1.234.567")))
    check("(c) الأرقام الهندية: ٨٦ مليون و٨٦ مليوناً و٩٢ ألفاً و١٦٨ و٧٧٫٥ مليون",
          vals("٨٦ مليون") == [Decimal(86000000)] and vals("٨٦ مليوناً و٩٢ ألفاً و١٦٨") == [Decimal(86092168)]
          and vals("٧٧٫٥ مليون") == [Decimal(77500000)], vals("٧٧٫٥ مليون"))
    ag = important._agree
    check("(c) اتفاق «86.1 مليون» و«86 مليوناً و92 ألفاً و168» ضمن 0.5% وعدم اتفاق 86 و90 مليونًا",
          ag("86.1 مليون", "86 مليوناً و92 ألفاً و168 نسمة", icfg)
          and not ag("86 مليون", "90 مليون", icfg) and ag("٨٦ مليون", "86 million", icfg),
          icfg["number_tolerance"])
    check("(c) بلا أرقام تبقى القاعدة القديمة (تقاطع كلمات)، وفارغة لا تتفق",
          ag("قانون القاصرين", "قانون حماية القاصرين", icfg) and not ag("", "قانون", icfg)
          and not ag("ثلاثة قتلى", "عشرة جرحى", icfg))
    check("(c) رقم في الصيغتين بقيمتين مختلفتين لا يتفقان رغم تقاطع الكلمات",
          not ag("3 قتلى في الحادثة", "5 قتلى في الحادثة", icfg))

    # (d) نقطة circulating: السياق محفوظ، claim المضمون، عبارة تركية حاضرة
    check("(d) circulating_context محفوظ للعرض وclaim هو المضمون لا واقعة التداول",
          p3["circulating_context"] == CTX_1201 and "انتشر" not in p3["claim"]
          and p1["framing"] == "direct" and p1["circulating_context"] == "",
          (p3["circulating_context"], p3["claim"]))
    check("(d) سياق التداول لا يصل نداء التصنيف ونداء النقطة المتداولة يحمل ملاحظة المضمون",
          all("صيف 2026" not in c for c in rig.contents)
          and sum(1 for s in rig.systems if "مضمون متداول" in s) == 1,
          sum(1 for s in rig.systems if "مضمون متداول" in s))
    check("(d) عبارة تركية لنقطة تركيا حاضرة في queries (نداء Haiku ثانٍ لأن الاستخراج لم يعدها)",
          "Türkiye 450 bin asker Suriye video" in p3["queries"] and "tr" in rig.native_requests,
          (p3["queries"], rig.native_requests))
    marker = "كلمة1203"
    tr_point = {"claim": f"أرسلت تركيا {marker} جندي", "entities": ["Turkey"],
                "queries": [_q("ar", f"تركيا {marker}"), _q("tr", f"Türkiye {marker} asker")]}
    with ImportantRig([tr_point], {marker: []}, lambda p, n: {"sources": []}) as rig2:
        important.judge("نص", 98002, cfg)
    pt2 = important.load_saved(98002)["points"][0]
    check("(d) عبارة تركية من الاستخراج نفسه ← لا نداء لغة أم ثانٍ وتبقى في queries",
          rig2.native_requests == [] and f"Türkiye {marker} asker" in pt2["queries"],
          (rig2.native_requests, pt2["queries"]))
    with ImportantRig([{"claim": f"وقعت حادثة {marker}", "entities": ["سويسرا"]}], {marker: []},
                      lambda p, n: {"sources": []}) as rig3:
        important.judge("نص", 98003, cfg)
    check("(d) كيان لبلد بلا لغة في entity_languages ← لا نداء ثانٍ", rig3.native_requests == [],
          rig3.native_requests)
    check("(d) github.com ونطاقات news-pravda.com الفرعية مستبعدة",
          all(important._is_excluded_domain(u, icfg) for u in (
              "https://github.com/gilandeya/trendnews/issues/1198",
              "https://syria.news-pravda.com/a", "https://news-pravda.com/b"))
          and not important._is_excluded_domain("https://notgithub.com/x", icfg))

    # (e) مسار «مقال» لم يُمَسّ: article.py بلا أي ذكر للمعامل الجديد
    check("(e) article.py لا يمرّر max_chars لجلب الأدلة (يبقى سقف 2500 لمسار «مقال» والأخبار)",
          "gather_evidence(" in inspect.getsource(article)
          and not re.search(r"gather_evidence\([^)]*max_chars", inspect.getsource(article)))
