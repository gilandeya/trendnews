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
        ev = [{"title": "حدث", "description": "وصف", "sources": list(names)}]
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
                "nearest_events": [{"title": "أقرب حدث موثَّق", "description": "وصف من النصوص",
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
    check("(a) (1) و(2) و(4) ← not_found مع nearest وبلا إسقاط",
          all(p["verdict"] == "not_found" and p["nearest"] and p["dropped_reason"] is None
              for p in (p1, p2, p4)), [(p["verdict"], p["nearest"]) for p in (p1, p2, p4)])
    check("(a) asserted محفوظ للعرض (النقطة 2 بلا أسماء ولم تسقط) وclaim حاضر",
          "مارس 2025" in p2["asserted"] and all(p["claim"] == p["text"] for p in pts), p2["asserted"])
    check("(a) النقطة 3 (تاريخ 2016) بُحثت بنافذة أوسع ثم بلا قيد",
          p3["windows"][:2] == ["wide", "unrestricted"], p3["windows"])
    fields = {"claim", "asserted", "queries", "engines", "docs_before", "docs_after"}
    check("(a) الحقول الجديدة لكل نقطة (البند 5)", all(fields <= set(p) for p in pts),
          [fields - set(p) for p in pts])
    mc = saved["model_calls"]
    check("(a) نداء تفكيك واحد (Haiku)، والملف يحمل طلبات Brave وسبب غيابها",
          mc["brief"] == 1 and mc["by_model"].get(cfg.path("important.extract_model")) == 1
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
