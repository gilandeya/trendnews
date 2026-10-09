"""مسار «هام» — الحَكَم على النقاط (Issue #1194، المهمة 1 من 3).

كل اختبار هنا يجري على مخرَج الأنبوب كاملًا: نص Issue ← important.judge ←
الملف المحفوظ في state/important، ببحث وجلب ونموذج مزيَّفة (ImportantRig في
tests/helpers.py). حالات الحارس g1–g6 في tests/test_guards_golden.py."""
from __future__ import annotations

import re

from tests.helpers import (check, load_config, ImportantRig, ImportantWriteRig, important_doc,
                           important_fixture_point, important_good_data, important_marked_body,
                           important_point, important_stance, important_synthetic_point,
                           brave_result, DRAFTS_DIR, store)


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
    # السلوك القديم (حدث بمصدر واحد ← nearest فارغ والنقطة تسقط) أُلغي بالقرار 3 (ج) في #1282:
    # لا تسقط نقطة لها أقرب حدث ولو بمصدر واحد، بل تُعرض بنسبة صريحة إليه
    check("(c) حدث بمصدر واحد ← nearest من نوع single_source والنقطة معروضة لا مُسقطة",
          (sc[q_one["text"]]["nearest"] or {}).get("kind") == "single_source"
          and sc[q_one["text"]]["dropped_reason"] is None
          and sc[q_one["text"]]["status"] == "offered",
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
    # #1282: نداء Sonnet لكل نقطة + نداء إضافي لكل نقطة أُعيد تصنيفها على المخزون المشترك (shared_from)،
    # فالعدد يُحسب من الملف لا يُثبَّت
    expected_sonnet = len(pts) + sum(1 for p in pts if p.get("shared_from"))
    check("(a) نداء تفكيك واحد (Haiku) + نداءات لغة أم، كلها Haiku، والملف "
          "يحمل طلبات Brave وسبب غيابها",
          mc["brief"] >= 1 and mc["brief"] == mc["by_model"].get(cfg.path("important.extract_model"))
          and mc["by_model"].get(cfg.path("article.model")) == expected_sonnet
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
    # 4 = عبارتان عاديتان + عبارتا site: لمدقّقَي العربية (misbar، fatabyyano) — #1205
    check("(d) بمفتاح ← Brave يُستعمل لكل عبارة ولعبارة التدقيق ولمواقع المدقّقين ويُسجَّل في الملف",
          len(rig_d2.brave_calls) == 4 and "brave_web" in pd2["engines"]
          and sd2["brave"]["requests"] == 4 and sd2["brave"]["monthly_usage"] == 4, sd2["brave"])
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
          len(rig_e2.brave_calls) == 4 and data_e2.get(month_img) == cap_img
          and data_e2.get(month_imp) == 4, data_e2)
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
    # الغاية «ليس سوريا»: لا nearest، أو كيانه المشترك تركيا ولا مصدر فيه من وثائق سوريا (#1282)
    # #1288: كان يُبنى من title وexcerpt وهما غير موجودين في read_docs فكان فارغًا دائمًا (فحص يمرّ دائمًا)؛
    # وثيقتا سوريا في هذا الاختبار CNN Arabic وعنب بلدي
    syria_pubs = {"CNN Arabic", "عنب بلدي"}
    n2 = p2["nearest"]
    check("(a) (2) nearest ليس سوريا (لا كيان مشترك مع نقطة عن تركيا)",
          p2["verdict"] == "not_found"
          and (n2 is None or (n2["shared_entity"] == "تركيا"
                              and not ({s["publisher"] for s in n2["sources"]} & syria_pubs))),
          p2["nearest"])
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
            # مقتطف يني شفق يسمّي بايكار صراحة: ادّعاء «أعلنت شركة بايكار…» يشترط (#1229) مؤيِّدًا ينقل عنها
            return {"sources": [important_stance(n, "supports", "أعلنت بايكار إصابة هدف"
                                                 if n == "Yeni Şafak" else "250 كيلومترًا")
                                for n in names]}
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


# ───────────── Issue #1205 (المهمة 1هـ): زمن التصحيح، الجهة الأصلية، بحث المدقّقين ─────────────


def test_important_1205() -> None:
    import inspect
    import json
    from src import article, important, imagesearch

    cfg = load_config()
    icfg = cfg.path("important")
    imagesearch.BRAVE_USAGE_FILE.unlink(missing_ok=True)

    claim_tr = "Türkiye 450 bin asker Suriye gönderdi"
    points = [
        {"claim": P1201["baykar"], "entities": ["بيرقدار"], "numbers": ["250 كيلومتر"],
         "queries": [_q("ar", "بيرقدار أقنجي إصابة 250 كيلومتر")], "factcheck_query": ""},
        {"claim": P1201["pop"], "entities": ["سكان"], "numbers": ["85.7 مليون"],
         "dates": ["نهاية 2025"], "queries": [_q("ar", "عدد سكان تركيا 2025 85.7 مليون")],
         "factcheck_query": ""},
        {"claim": P1201["video"], "framing": "circulating", "circulating_context": CTX_1201,
         "entities": ["تركيا", "سوريا"], "numbers": ["450 ألف"],
         "queries": [_q("ar", "تركيا 450 ألف جندي سوريا"), _q("en", "Turkey 450000 soldiers Syria"),
                     _q("tr", claim_tr)],
         "factcheck_query": "تركيا 450 ألف جندي سوريا تحقق"},
        {"claim": P1201["space"], "entities": ["فضائي"], "dates": ["2026"],
         "queries": [_q("ar", "تركيا شبكة إنترنت فضائي حكومية")], "factcheck_query": ""},
        {"claim": P1201["users"], "entities": ["الإنترنت"], "numbers": ["77.5 مليون"],
         "queries": [_q("ar", "مستخدمو الإنترنت في تركيا 77.5 مليون")], "factcheck_query": ""},
    ]
    teyit_cut = "Teyit: Türkiye'nin Suriye'ye 450 bin asker gönderdiği iddiası yalan"
    brave = {"site:teyit.org": [brave_result(
        "https://teyit.org/analiz/turkiye-450-bin-asker-suriye", teyit_cut,
        "Eski bir video yeni gibi paylaşıldı.", "Teyit")]}
    docs = {
        "بيرقدار": [important_doc("Alsaudi", "بيرقدار أقنجي أصابت هدفًا يبعد أكثر من 250 كيلومترًا.",
                                  link="https://alsaudi.news/international/1109/96875"),
                    important_doc("Yeni Şafak", "أعلنت بايكار إصابة هدف على بعد 250 كيلومترًا بأقنجي.",
                                  link="https://www.yenisafak.com/ar/economy/4131591")],
        "سكان": [important_doc("newturkpost", "بلغ عدد سكان تركيا 86 مليوناً و92 ألفاً و168 نسمة "
                               "في نهاية 2025.", link="https://newturkpost.com/news/118693"),
                 important_doc("TRADING ECONOMICS", "عدد سكان تركيا 86.1 مليون نسمة في 2025.",
                               link="https://ar.tradingeconomics.com/turkey/population"),
                 important_doc("Zaman Arabic", "بلغ التعداد السكاني في تركيا 85 مليون و980 ألف و654 نسمة "
                               "اعتبارا من الأول من أكتوبر.",
                               link="https://www.zamanarabic.com/2025/11/24/population")],
        "450": [important_doc("Al Jazeera", "الفيديو المتداول قديم، ولم تُرسل تركيا 450 ألف جندي إلى سوريا.",
                              link="https://www.aljazeera.net/news/2026/8/23/video")],
        "فضائي": [important_doc("Eutelsat", "خدمات أقمار صناعية في تركيا.", link="https://www.eutelsat.com/turkiye")],
        "الإنترنت": [important_doc("Global Digital Insights",
                                   "Türkiye had 77.5 million internet users at the start of 2026 "
                                   "according to DataReportal Digital 2026.",
                                   link="https://datareportal.com/reports/digital-2026-turkey"),
                     important_doc("Daily Sabah", "Citing Global Digital Insights, 77.5 million Turks use "
                                   "the internet.", link="https://www.dailysabah.com/turkiye/internet-use")],
    }
    forms = {"newturkpost": ("86 مليوناً و92 ألفاً و168 نسمة", "نهاية 2025"),
             "TRADING ECONOMICS": ("86.1 مليون نسمة", "نهاية 2025"),
             "Zaman Arabic": ("85 مليوناً و980 ألفاً و654 نسمة", "1 أكتوبر 2025")}

    def classify(point, names):
        if "بيرقدار" in point:
            # مقتطف يني شفق يسمّي بايكار صراحة: ادّعاء «أعلنت شركة بايكار…» يشترط (#1229) مؤيِّدًا ينقل عنها
            return {"sources": [important_stance(n, "supports", "أعلنت بايكار إصابة هدف"
                                                 if n == "Yeni Şafak" else "250 كيلومترًا")
                                for n in names]}
        if "85.7" in point:
            return {"sources": [important_stance(
                n, "conflicts_detail", forms[n][0], detail="العدد 85.7 غير دقيق",
                correct_form=forms[n][0], as_of=forms[n][1]) for n in names]}
        if "450" in point:
            return {"sources": [important_stance(
                n, "refutes", teyit_cut if n == "Teyit" else "ولم تُرسل تركيا 450 ألف جندي إلى سوريا")
                for n in names]}
        if "فضائي" in point:
            return {"sources": [important_stance(n, "irrelevant", same_event=False) for n in names]}
        return {"sources": [important_stance(n, "supports", "77.5 million internet users")
                            if n == "Global Digital Insights" else important_stance(n, "irrelevant")
                            for n in names]}

    with ImportantRig(points, docs, classify, brave_results=brave, brave_key="k-test") as rig:
        important.judge("\n".join(P1201.values()) + "\n" + CTX_1201, 98005, cfg)
    saved = important.load_saved(98005)
    p1, p2, p3, p4, p5 = saved["points"]

    # (a) الجدول: النقطة ← verdict ← correction/refuted_by
    cor = p2["correction"] or {}
    check("(a) (1) ← confirmed", p1["verdict"] == "confirmed" and not p1["primary_source"], p1["verdict"])
    check("(a) (2) ← inaccurate بـ86,092,168 من newturkpost وTrading Economics لزمن «نهاية 2025»",
          p2["verdict"] == "inaccurate" and cor.get("correct_value") == "86,092,168"
          and cor.get("as_of") == "نهاية 2025"
          and {s["publisher"] for s in cor["sources"]} == {"newturkpost", "TRADING ECONOMICS"},
          p2["correction"])
    zaman = next(d for d in p2["read_docs"] if d["publisher"] == "Zaman Arabic")
    check("(a) (2) صيغة «1 أكتوبر 2025» لزمن آخر: في read_docs وحدها لا في الأدلة ولا التصحيح",
          zaman["as_of"] == "1 أكتوبر 2025"
          and "Zaman Arabic" not in {e["publisher"] for e in p2["evidence"]}, zaman)
    check("(a) (3) ← false برابط teyit.org (مدقّق وحده) مع الجزيرة",
          p3["verdict"] == "false"
          and any("teyit.org" in r["link"] and r["fact_checker"] for r in p3["refuted_by"]),
          (p3["verdict"], p3["refuted_by"]))
    check("(a) (4) ← not_found وسقطت (لا أثر)",
          p4["verdict"] == "not_found" and p4["dropped_reason"] == important.NO_TRACE_REASON,
          (p4["verdict"], p4["dropped_reason"]))
    check("(a) (5) ← confirmed من datareportal.com وحدها بـprimary_source=true",
          p5["verdict"] == "confirmed" and p5["primary_source"] is True
          and any("datareportal.com" in e["link"] for e in p5["evidence"]),
          (p5["verdict"], p5["primary_source"]))
    print("جدول (a):")
    for p in saved["points"]:
        if p["correction"]:
            extra = (p["correction"]["correct_value"], p["correction"]["as_of"],
                     [s["publisher"] for s in p["correction"]["sources"]])
        else:
            extra = [r["link"] for r in p["refuted_by"] or []]
        print("  ", p["text"][:40], "←", p["verdict"], "←", extra)

    # (b) عبارات site: بحسب لغات النقطة، والسقف، وعدّاد «هام»
    sites3 = p3["site_queries"]
    check("(b) نقطة ar+en+tr: 4 عبارات site: (السقف) بترتيب الإعداد، والتركية محفوظة قبل الإنجليزية",
          [q.rsplit("site:", 1)[1] for q in sites3] ==
          ["misbar.com", "fatabyyano.net", "teyit.org", "factcheck.afp.com"]
          and len(sites3) == icfg["factcheck_site_queries"], sites3)
    # #1212: عبارة site: تُبنى في الكود من أرقام النقطة وكياناتها لا من عبارة النموذج (بلا كلمة تدقيق)
    check("(b) عبارة teyit.org مبنيّة في الكود: رقم النقطة وكياناتها بالتركية بلا «teyit»",
          "450 bin Türkiye Suriye site:teyit.org" in sites3, sites3)
    check("(b) نقطة بالعربية وحدها: عبارتا misbar وfatabyyano فقط",
          [q.rsplit("site:", 1)[1] for q in p1["site_queries"]] == ["misbar.com", "fatabyyano.net"],
          p1["site_queries"])
    n_site = sum(len(p["site_queries"]) for p in saved["points"])
    usage = json.loads(imagesearch.BRAVE_USAGE_FILE.read_text()).get(important._usage_key())
    check("(b) كل عبارة site: طلب Brave واحد يحسبه عدّاد «هام»",
          sum(1 for q in rig.brave_calls if "site:" in q) == n_site
          and saved["brave"]["requests"] == len(rig.brave_calls)
          and saved["brave"]["monthly_usage"] == len(rig.brave_calls) == usage,
          (n_site, saved["brave"], len(rig.brave_calls), usage))
    with ImportantRig(points[:1], docs, classify) as rig_nk:
        important.judge("نص", 98006, cfg)
    check("(b) بلا مفتاح لا طلب Brave ولا خطأ",
          rig_nk.brave_calls == [] and important.load_saved(98006)["brave"]["skipped"] == "no_key")

    # (c) الدوال الجديدة وحدها، ومسار «مقال» لم يُمَسّ
    def stat(a, d):
        return important._time_status(a, d, icfg)

    check("(c) زمن الصيغة: نهاية 2025 تطابق «2025» و«نهاية 2025»؛ أكتوبر 2025 وأكتوبر 2026 لا",
          stat("نهاية 2025", ["نهاية 2025"]) == "match" and stat("2025", ["نهاية 2025"]) == "match"
          and stat("1 أكتوبر 2025", ["نهاية 2025"]) == "other"
          and stat("أكتوبر 2026", ["نهاية 2025"]) == "other"
          and stat("", ["نهاية 2025"]) == "absent" and stat("أكتوبر 2026", []) == "free")

    def ph(t):
        return important._numbers_with_half(t, icfg)[0]

    check("(c) الهامش: 86.1 مليون ضمن 86,092,168 ولا ضمن 85.7 مليون",
          important._within_margin(ph("86.1 مليون"), ph("86,092,168"), icfg)
          and not important._within_margin(ph("86.1 مليون"), ph("85.7 مليون"), icfg))
    src = inspect.getsource(article)
    check("(c) article.py لا يعرف as_of ولا الجهات الأصلية (مسار «مقال» لم يُمَسّ)",
          "as_of" not in src and "primary_data" not in src)


# ───────── Issue #1207 (المهمة 1و): ميزانيتا المدقّقين، حكم المدقّق الصريح، هامش _agree ─────────


def test_important_1207() -> None:
    import inspect
    from src import article, important, imagesearch

    cfg = load_config()
    icfg = cfg.path("important")
    imagesearch.BRAVE_USAGE_FILE.unlink(missing_ok=True)

    claim_tr = "Türkiye 450 bin asker Suriye gönderdi"

    def langs(ar: str, tr: str, en: str) -> list[dict]:
        return [_q("ar", ar), _q("tr", tr), _q("en", en)]

    # نقاط (1) و(2) و(5) بثلاث لغات: أربع عبارات site: كما في التجربة الخامسة (مسبار، فتبيّنوا، Teyit، AFP)
    points = [
        {"claim": P1201["baykar"], "entities": ["بيرقدار"], "numbers": ["250 كيلومتر"],
         "queries": langs("بيرقدار أقنجي إصابة 250 كيلومتر", "Bayraktar Akinci 250 kilometre",
                          "Bayraktar Akinci 250 km"), "factcheck_query": ""},
        {"claim": P1201["pop"], "entities": ["سكان"], "numbers": ["85.7 مليون"],
         "dates": ["نهاية 2025"],
         "queries": langs("عدد سكان تركيا 2025 85.7 مليون", "Turkiye nufus 2025 85.7 milyon",
                          "Turkey population 2025 85.7 million"), "factcheck_query": ""},
        {"claim": P1201["video"], "framing": "circulating", "circulating_context": CTX_1201,
         "entities": ["تركيا", "سوريا"], "numbers": ["450 ألف"],
         "queries": [_q("ar", "تركيا 450 ألف جندي سوريا"), _q("en", "Turkey 450000 soldiers Syria"),
                     _q("tr", claim_tr)],
         "factcheck_query": "تركيا 450 ألف جندي سوريا تحقق"},
        {"claim": P1201["space"], "entities": ["فضائي"], "dates": ["2026"],
         "queries": [_q("ar", "تركيا شبكة إنترنت فضائي حكومية")], "factcheck_query": ""},
        {"claim": P1201["users"], "entities": ["الإنترنت"], "numbers": ["77.5 مليون"],
         "queries": langs("مستخدمو الإنترنت في تركيا 77.5 مليون", "Turkiye internet kullanicisi 77.5 milyon",
                          "Turkey internet users 77.5 million"), "factcheck_query": ""},
    ]

    # نتائج المدقّقين الأربع غير ذات الصلة (لا كيان ولا رقم من أي نقطة) — تعود لكل عبارة site:
    junk = {
        "site:misbar.com": [brave_result("https://misbar.com/factcheck/old-flood",
                                         "صورة قديمة لفيضان في مدينة بعيدة", "تدقيق في صورة متداولة", "Misbar")],
        "site:fatabyyano.net": [brave_result("https://fatabyyano.net/old-photo",
                                             "لا صلة لهذه اللقطة بالحدث المتداول", "تدقيق", "Fatabyyano")],
        "site:teyit.org": [brave_result("https://teyit.org/analiz/eski-fotograf",
                                        "Eski bir fotograf yeni gibi paylasildi", "Analiz", "Teyit")],
        "site:factcheck.afp.com": [brave_result("https://factcheck.afp.com/doc.old-photo",
                                                "Old photo shared as new", "Fact check", "AFP Fact Check")],
    }
    junk_links = {r["url"] for rs in junk.values() for r in rs}
    # صفحة Teyit للنقطة (3): عنوانها سؤال، وفيها سطر الحكم «Yanlış»
    q_title = "Türkiye'nin Suriye'ye 450 bin asker gönderdiğini mi gösteriyor?"
    teyit_link = "https://teyit.org/analiz/turkiye-450-bin-asker-suriye"
    verdict_line = "İddia yanlış"
    brave = {**junk, claim_tr: [brave_result(
        teyit_link, q_title, f"Sonuç: Yanlış. {verdict_line}. Video eski bir görüntüye aittir.", "Teyit")]}

    def decoys(tag: str, entity: str, extra: str, n: int = 5) -> list[dict]:
        # مشتتات عادية تطابق النقطة أكثر من المؤيِّدين (كيان + حرفية) — كما ازدحمت المقاعد فعلًا
        return [important_doc(f"Decoy {tag} {i}", f"{entity} {extra} تقرير عام رقم {i}.",
                              link=f"https://decoy-{tag}-{i}.example/a") for i in range(n)]

    docs = {
        "بيرقدار": [
            important_doc("Yeni Şafak", "أعلنت بايكار نجاح الاختبار على بعد 250 كيلومترًا بأقنجي.",
                          link="https://www.yenisafak.com/ar/economy/4131591"),
            important_doc("defensehere", "نجحت المسيّرة في إصابة هدف يبعد 250 كيلومترًا بحسب الشركة.",
                          link="https://defensehere.com/akinci-250"),
            important_doc("SdArabia", "اختبار ناجح لأقنجي بمدى 250 كيلومترًا وفق بيان الشركة.",
                          link="https://sdarabia.com/akinci"),
            important_doc("Alsaudi", "ذكر موقع آخر إصابة هدف على بعد 250 كيلومترًا.",
                          link="https://alsaudi.news/international/1109/96875"),
        ] + decoys("a", "بيرقدار", "250 كيلومتر"),
        "سكان": [
            important_doc("newturkpost", "بلغ عدد سكان تركيا 86 مليوناً و92 ألفاً و168 نسمة في نهاية 2025.",
                          link="https://newturkpost.com/news/118693"),
            important_doc("TRADING ECONOMICS", "عدد سكان تركيا 86.1 مليون نسمة في 2025.",
                          link="https://ar.tradingeconomics.com/turkey/population"),
            important_doc("Zaman Arabic", "بلغ التعداد السكاني في تركيا 85 مليون و980 ألف و654 نسمة "
                          "اعتبارا من الأول من أكتوبر.", link="https://www.zamanarabic.com/2025/11/24/population"),
        ] + decoys("b", "سكان", "85.7 مليون نهاية 2025"),
        "فضائي": [important_doc("Eutelsat", "خدمات أقمار صناعية في تركيا.",
                                link="https://www.eutelsat.com/turkiye")],
        "الإنترنت": [
            important_doc("Global Digital Insights",
                          "Türkiye had 77.5 million internet users at the start of 2026 "
                          "according to DataReportal Digital 2026.",
                          link="https://datareportal.com/reports/digital-2026-turkey"),
            important_doc("Daily Sabah", "Citing Global Digital Insights, 77.5 million Turks use the internet.",
                          link="https://www.dailysabah.com/turkiye/internet-use"),
        ] + decoys("c", "الإنترنت", "77.5 مليون"),
    }
    forms = {"newturkpost": ("86 مليوناً و92 ألفاً و168 نسمة", "نهاية 2025"),
             "TRADING ECONOMICS": ("86.1 مليون نسمة", "نهاية 2025"),
             "Zaman Arabic": ("85 مليوناً و980 ألفاً و654 نسمة", "1 أكتوبر 2025")}
    supporters = {"Yeni Şafak", "defensehere", "SdArabia", "Alsaudi"}

    def classify(point, names):
        if "بيرقدار" in point:
            return {"sources": [important_stance(n, "supports", "أعلنت بايكار إصابة هدف"
                                                 if n == "Yeni Şafak" else "250 كيلومترًا")
                                if n in supporters else important_stance(n, "irrelevant") for n in names]}
        if "85.7" in point:
            return {"sources": [important_stance(
                n, "conflicts_detail", forms[n][0], detail="العدد 85.7 غير دقيق",
                correct_form=forms[n][0], as_of=forms[n][1]) if n in forms
                else important_stance(n, "irrelevant") for n in names]}
        if "450" in point:
            return {"sources": [important_stance(n, "refutes", verdict_line, verdict_label="Yanlış")
                                for n in names]}
        if "فضائي" in point:
            return {"sources": [important_stance(n, "irrelevant", same_event=False) for n in names]}
        return {"sources": [important_stance(n, "supports", "77.5 million internet users")
                            if n == "Global Digital Insights" else important_stance(n, "irrelevant")
                            for n in names]}

    with ImportantRig(points, docs, classify, brave_results=brave, brave_key="k-test") as rig:
        important.judge("\n".join(P1201.values()) + "\n" + CTX_1201, 98007, cfg)
    saved = important.load_saved(98007)
    p1, p2, p3, p4, p5 = saved["points"]

    # (a) الجدول
    cor = p2["correction"] or {}
    check("(a) (1) ← confirmed (يني شفق وdefensehere وSdArabia لم تُزاحَم بالمدقّقين)",
          p1["verdict"] == "confirmed"
          and {e["publisher"] for e in p1["evidence"]} >= {"Yeni Şafak", "defensehere", "SdArabia"},
          (p1["verdict"], [e["publisher"] for e in p1["evidence"]]))
    check("(a) (2) ← inaccurate بـ86,092,168",
          p2["verdict"] == "inaccurate" and cor.get("correct_value") == "86,092,168"
          and {s["publisher"] for s in cor["sources"]} == {"newturkpost", "TRADING ECONOMICS"},
          p2["correction"])
    refuted = p3["refuted_by"] or []
    check("(a) (3) ← false من Teyit وحده (بحكم «Yanlış») ومقتطفه سطر الحكم لا العنوان",
          p3["verdict"] == "false" and len(refuted) == 1 and refuted[0]["excerpt"] == verdict_line
          and refuted[0]["link"] == teyit_link and refuted[0]["fact_checker"]
          and "?" not in refuted[0]["excerpt"], (p3["verdict"], refuted))
    check("(a) (4) ← not_found وسقطت (لا أثر)",
          p4["verdict"] == "not_found" and p4["dropped_reason"] == important.NO_TRACE_REASON,
          (p4["verdict"], p4["dropped_reason"]))
    check("(a) (5) ← confirmed من datareportal.com وحدها (DataReportal لم يُزاحَم)",
          p5["verdict"] == "confirmed" and p5["primary_source"] is True
          and any("datareportal.com" in e["link"] for e in p5["evidence"]),
          (p5["verdict"], p5["primary_source"]))
    print("جدول (a) #1207:")
    for i, p in enumerate(saved["points"], 1):
        extra = ((p["correction"]["correct_value"], [s["publisher"] for s in p["correction"]["sources"]])
                 if p["correction"] else [r["excerpt"] for r in p["refuted_by"] or []]
                 or [e["publisher"] for e in p["evidence"]])
        print("  ", f"({i})", p["text"][:40], "←", p["verdict"], "←", extra)
    print("refuted_by (3):", p3["refuted_by"])

    # (b) نتائج المدقّقين غير ذات الصلة: لا تُجلب ولا تُحسب في أي ميزانية
    check("(b) لا رابط من المدقّقين غير ذوي الصلة أُرسل إلى الجلب",
          not (set(rig.gathered) & junk_links) and teyit_link in rig.gathered, rig.gathered)
    junk_names = {"Misbar", "Fatabyyano", "AFP Fact Check", "Teyit"}
    for i, p in ((1, p1), (2, p2), (5, p5)):
        names = {d["publisher"] for d in p["read_docs"]}
        check(f"(b) النقطة {i}: المدقّقون الأربع (مسبار/فتبيّنوا/Teyit/AFP) خارج read_docs ومسجَّلون مستبعَدين",
              not (names & junk_names) and {s["link"] for s in p["checker_skipped"]} == junk_links,
              (names, p["checker_skipped"]))
    check("(b) النقطة 1: 4 مؤيِّدة محتمَلة + 5 مشتتات = 9 وثائق عادية تُقصّ إلى 8 لا إلى 4",
          p1["docs_before"] == 9 and p1["docs_after"] == 8, (p1["docs_before"], p1["docs_after"]))
    check("(b) النقطة 3: صفحة Teyit ذات الصلة جُلبت وبقيت، وغير ذات الصلة استُبعدت",
          [d["publisher"] for d in p3["read_docs"]] == ["Teyit"] and len(p3["checker_skipped"]) == 4,
          ([d["publisher"] for d in p3["read_docs"]], p3["checker_skipped"]))

    # ميزانيتان منفصلتان: 6 نتائج مدقّقين ذات صلة + 10 وثائق عادية ← 4 + 8
    ent = "عبارةمدقق"
    many_fc = {"site:misbar.com": [brave_result(f"https://misbar.com/factcheck/{i}",
                                                f"تدقيق عن {ent} رقم {i}", "ملخص", f"Misbar {i}")
                                   for i in range(3)],
               "site:fatabyyano.net": [brave_result(f"https://fatabyyano.net/check/{i}",
                                                    f"تحقق من {ent} رقم {i}", "ملخص", f"Fatabyyano {i}")
                                       for i in range(3)]}
    pt = {"claim": f"واقعة {ent} كبيرة", "entities": [ent], "queries": [_q("ar", f"واقعة {ent}")],
          "factcheck_query": ""}
    regular = {ent: [important_doc(f"ناشر {i}", f"نص عن {ent} رقم {i}.", link=f"https://pub-{i}.example/a")
                     for i in range(10)]}
    with ImportantRig([pt], regular, lambda p, n: {"sources": [important_stance(x, "irrelevant") for x in n]},
                      brave_results=many_fc, brave_key="k-test"):
        important.judge("نص", 98008, cfg)
    pb = important.load_saved(98008)["points"][0]
    n_fc = sum(1 for d in pb["read_docs"] if d["engine"] == "brave_web")
    n_reg = sum(1 for d in pb["read_docs"] if d["engine"] == "google_news")
    check("(b) ميزانيتان منفصلتان: max_factcheck_docs (4) للمدقّقين وmax_docs_per_point (8) لغيرهم",
          icfg["max_factcheck_docs"] == 4 and n_fc == 4 and n_reg == 8 and pb["docs_after"] == 12,
          (n_fc, n_reg, pb["docs_after"]))

    # حكم المدقّق الصريح: وحدات
    check("(b) سؤال لا جملة حكم: «؟» أو «?» أو أداة استفهام تركية في الآخر",
          important._is_question(q_title) and important._is_question("İddia gerçek mi")
          and important._is_question("هل أرسلت تركيا جنودها؟") and important._is_question("Is it true?")
          and not important._is_question(verdict_line) and not important._is_question("Bu iddia mı yanlış"))
    check("(b) false_labels/true_labels/misleading_labels مطبَّعة حرفيًا لا جزئيًا",
          important._label_in("Yanlış", icfg, "false_labels") and important._label_in("ملفّق", icfg, "false_labels")
          and not important._label_in("Mostly False", icfg, "false_labels")
          and important._label_in("Yanıltıcı", icfg, "misleading_labels")
          and important._label_in("Doğru", icfg, "true_labels")
          and not important._label_in("", icfg, "false_labels"))

    # (c) مسار «مقال» لم يُمَسّ
    src = inspect.getsource(article)
    check("(c) article.py لا يعرف verdict_label ولا ميزانية المدقّقين (مسار «مقال» لم يُمَسّ)",
          "verdict_label" not in src and "false_labels" not in src and "max_factcheck" not in src)


def test_important_1210() -> None:
    """المهمة 1ز (Issue #1210): حكم المدقّق من ClaimReview في HTML الخام — على الأنبوب كاملًا
    بنقطة #1201 (3) ووثيقة Teyit كما جاءت في التشغيل السادس (page_chars=226)."""
    import inspect
    from src import article, important
    from tests.helpers import claim_review_html

    cfg = load_config()
    teyit_link = ("https://teyit.org/analiz/video-turkiyenin-suriyeye-450-bin-"
                  "asker-gonderdigini-mi-gosteriyor")
    q_title = "Türkiye'nin Suriye'ye 450 bin asker gönderdiğini mi gösteriyor?"
    short_page = (q_title + " Teyit " * 40)[:226]
    claimed = "Türkiye'nin Suriye'ye 450 bin asker gönderdiği"

    def lazy(point, names):
        # النموذج كما في التشغيل السادس: نفي بعنوان سؤالي بلا verdict_label
        return {"sources": [important_stance(n, "refutes", q_title, verdict_label="") for n in names]}

    def run(case: int, doc_extra: dict):
        marker = "تركياكلمة"
        pt = {"claim": f"أرسلت {marker} 450 ألف جندي إلى سوريا", "framing": "circulating",
              "circulating_context": "فيديو انتشر صيف 2026", "entities": [marker],
              "numbers": ["450 ألف"], "queries": [_q("ar", f"{marker} 450 ألف جندي سوريا")]}
        docs = [important_doc("Teyit", short_page, link=teyit_link, **doc_extra)]
        rig = ImportantRig([pt], {marker: docs}, lazy)
        with rig:
            important.judge("نص", 98100 + case, cfg)
        return important.load_saved(98100 + case)["points"][0], rig

    # (a) النقطة (3): false بمقتطف «Yanlış» وclaim_review محفوظ؛ الجلب نفسه سلّم HTML فلا جلب ثانٍ
    p, rig = run(1, {"html": claim_review_html("Yanlış", claimed)})
    refuted = p["refuted_by"] or []
    check("(a) (3) false بمقتطف «Yanlış» لا العنوان السؤالي",
          p["verdict"] == "false" and len(refuted) == 1 and refuted[0]["excerpt"] == "Yanlış"
          and refuted[0]["fact_checker"] and refuted[0]["link"] == teyit_link, (p["verdict"], refuted))
    doc = p["read_docs"][0]
    check("(a) read_docs.claim_review = {claim_reviewed، label، date_published}",
          doc["page_chars"] == 226 and doc["claim_review"] == {
              "claim_reviewed": claimed, "label": "Yanlış", "date_published": "2026-08-14"},
          doc)
    check("(a) HTML الخام وصل من الجلب نفسه: html_sink مُمرَّر ولا جلب إضافي",
          rig.html_sink_seen and all(rig.html_sink_seen) and rig.fetched_html == [], rig.fetched_html)
    print("refuted_by (3) #1210:", refuted)

    # (b) ClaimReview داخل @graph، وكقائمة، وبـname بدل alternateName
    for shape, key in (("graph", "alternateName"), ("list", "alternateName"),
                       ("single", "name"), ("graph", "name")):
        html = claim_review_html("Yanlış", claimed, shape=shape, rating_key=key)
        cr = important.parse_claim_review(html)
        check(f"(b) ClaimReview ({shape}، {key}) يُقرأ",
              cr and cr["label"] == "Yanlış" and cr["claim_reviewed"] == claimed
              and cr["date_published"] == "2026-08-14" and cr["url"] == teyit_link
              and cr["in_raw_html"], cr)
    pg, _ = run(2, {"html": claim_review_html("Yanlış", claimed, shape="graph", rating_key="name")})
    check("(b) داخل @graph وبـname ← false عبر الأنبوب", pg["verdict"] == "false", pg["verdict"])
    esc = ('<script type="application/ld+json">{"@type": "ClaimReview", "claimReviewed": "x", '
           '"reviewRating": {"alternateName": "Yan\\u0131lt\\u0131c\\u0131"}}</script>')
    cr_esc = important.parse_claim_review(esc)
    check("(b) هروب \\uXXXX يُفكّ والحكم يُعدّ موجودًا في الكود الخام",
          cr_esc and cr_esc["label"] == "Yanıltıcı" and cr_esc["in_raw_html"], cr_esc)
    check("(b) كتلة غير ClaimReview تُتجاوز",
          important.parse_claim_review(
              '<script type="application/ld+json">{"@type": "NewsArticle"}</script>') is None)

    # (c) JSON-LD تالف أو غائب ← لا خطأ والسلوك كما قبل (النص المستخرج وحده، لا false)
    for n, shape in ((3, "broken"), (4, "none")):
        pc, _ = run(n, {"html": claim_review_html("Yanlış", claimed, shape=shape)})
        check(f"(c) JSON-LD {shape}: لا خطأ، claim_review فارغ، والحكم لا يكون false",
              pc["verdict"] != "false" and pc["read_docs"][0]["claim_review"] is None,
              (pc["verdict"], pc["read_docs"][0]["claim_review"]))
    check("(c) محلّل بلا HTML أو بنص فارغ ← None",
          important.parse_claim_review("") is None and important.parse_claim_review(None) is None)

    # لم يمرّ الجلب الأول على الصفحة ← جلب واحد إضافي للـHTML؛ ونطاق خارج المدقّقين لا يُجلب
    pl, rig_l = run(5, {"late_html": claim_review_html("Yanlış", claimed)})
    check("(1) بلا HTML من الجلب الأول: جلب إضافي واحد بالرابط نفسه ثم false",
          rig_l.fetched_html == [teyit_link] and pl["verdict"] == "false",
          (rig_l.fetched_html, pl["verdict"]))
    marker = "كلمةغيرمدقق"
    other = {"claim": f"ادّعاء {marker}", "entities": [marker], "queries": [_q("ar", marker)]}
    rig_o = ImportantRig([other], {marker: [important_doc(
        "Haberler", "نص قصير", link="https://haberler.example/a",
        late_html=claim_review_html("Yanlış", claimed))]}, lambda p, n: {
            "sources": [important_stance(x, "irrelevant") for x in n]})
    with rig_o:
        important.judge("نص", 98110, cfg)
    check("(1) نطاق خارج fact_check_domains: لا جلب HTML إضافي ولا claim_review",
          rig_o.fetched_html == []
          and important.load_saved(98110)["points"][0]["read_docs"][0]["claim_review"] is None,
          rig_o.fetched_html)

    # (d) مسار «مقال» لم يُمَسّ
    src = inspect.getsource(article)
    check("(d) article.py لا يعرف ClaimReview (مسار «مقال» لم يُمَسّ)",
          "claim_review" not in src.lower())


def test_important_1212() -> None:
    """المهمة 1ح (Issue #1212): عبارات site: تُبنى في الكود، وذاكرة نتائج البحث بين التشغيلات —
    على الأنبوب كاملًا. نقطة #1201 (3): «أرسلت تركيا 450 ألف جندي إلى سوريا»."""
    import inspect
    import json
    from datetime import datetime, timedelta, timezone
    from src import article, important

    cfg = load_config()
    cache_file = important._search_cache_file

    def irrelevant(p, names):
        return {"sources": [important_stance(x, "irrelevant") for x in names]}

    def supports(p, names):
        return {"sources": [important_stance(x, "supports", "افتتح الرئيس") for x in names]}

    # (a) عبارات site: ثابتة عبر تشغيلتين مهما أعاد النموذج من factcheck_query وعبارات
    def run_a(n: int, factcheck: str, queries: list[dict]):
        pt = {"claim": "أرسلت تركيا 450 ألف جندي إلى سوريا", "framing": "direct",
              "entities": ["سوريا", "جنود"], "numbers": ["450 ألف"],
              "queries": queries, "factcheck_query": factcheck}
        with ImportantRig([pt], {}, irrelevant):
            important.judge("نص", 98200 + n, cfg)
        return important.load_saved(98200 + n)["points"][0]["site_queries"]

    s1 = run_a(1, "Türkiye Suriye'ye 450 bin asker gönderdi teyit",
               [_q("ar", "تركيا 450 ألف جندي سوريا حقيقة"), _q("tr", "Türkiye 450 bin asker Suriye 2026"),
                _q("en", "Turkey 450 thousand soldiers Syria")])
    s2 = run_a(2, "Türkiye 450 bin asker Suriye 2026 teyit yaz",
               [_q("ar", "هل أرسلت تركيا جنودا"), _q("tr", "Türkiye Suriye'ye asker gönderdi mi"),
                _q("en", "Turkey sent troops Syria 2026")])
    teyit = [q for q in s1 if q.endswith("site:teyit.org")]
    check("(a) عبارات site: ثابتة بين تشغيلتين رغم اختلاف ما أعاده النموذج", s1 == s2 and len(s1) == 4, (s1, s2))
    check("(a) عبارة teyit.org «450 bin Suriye asker» حرفيًا بلا «teyit» ولا سنة ولا فعل",
          teyit == ["450 bin Suriye asker site:teyit.org"], teyit)
    check("(a) الإنجليزية والعربية بصيغة لغتهما: 450 thousand / 450 ألف",
          "450 thousand Syria soldiers site:factcheck.afp.com" in s1
          and "450 ألف سوريا جنود site:misbar.com" in s1, s1)
    check("(a) حد site_query_max_words لا يُتجاوز",
          all(len(q.split(" site:")[0].split()) <= cfg["important"]["site_query_max_words"] for q in s1), s1)
    check("(a) نقطة بلا كيانات ولا أرقام: العبارة فارغة (احتياط عبارة النموذج في site_queries)",
          important.site_phrase({"entities": [], "numbers": []}, "tr", cfg["important"]) == "")

    # (b) تشغيلتان بالنص نفسه: الثانية بلا طلب Brave ولا أخبار Google، والأحكام نفسها
    marker = "كلمةذاكرة"
    pt = {"claim": f"افتتح الرئيس جسر {marker}", "entities": [marker],
          "queries": [_q("ar", f"جسر {marker}")]}
    docs = {marker: [important_doc("صحيفة الشرق", f"افتتح الرئيس جسر {marker} أمس."),
                     important_doc("موقع الغرب", f"تقرير مستقل عن افتتاح جسر {marker}.")]}
    brave = {marker: [brave_result("https://b.example/x", f"جسر {marker}", "افتتاح الجسر", "B")]}
    rig = ImportantRig([pt], docs, supports, brave_results=brave, brave_key="k")
    with rig:
        r1 = important.judge("نص", 98210, cfg)
        g1, b1 = len(rig.searches), len(rig.brave_calls)
        usage1 = important.brave_usage()
        r2 = important.judge("نص", 98211, cfg)
        g2, b2 = len(rig.searches), len(rig.brave_calls)
        usage2 = important.brave_usage()
        saved = json.loads(cache_file().read_text(encoding="utf-8"))
    p1, p2 = r1["points"][0], r2["points"][0]
    check("(b) التشغيلة الأولى طلبت فعلًا ولم تضرب الذاكرة",
          g1 > 0 and b1 > 0 and p1["cache_hits"] == 0, (g1, b1, p1["cache_hits"]))
    check("(b) الثانية: صفر طلب Google وصفر طلب Brave، وعدّاد Brave لم يتحرّك",
          g2 == g1 and b2 == b1 and usage2 == usage1 and r2["brave"]["requests"] == 0,
          (g1, g2, b1, b2, usage1, usage2))
    check("(b) الثانية سجّلت cache_hits، والأحكام نفسها",
          p2["cache_hits"] > 0 and p2["verdict"] == p1["verdict"] == "confirmed"
          and [e["publisher"] for e in p2["evidence"]] == [e["publisher"] for e in p1["evidence"]],
          (p2["cache_hits"], p1["verdict"], p2["verdict"]))
    check("(b) الملف يحفظ نتائج بحث لا نصوص صفحات",
          saved["entries"] and all("text" not in d for e in saved["entries"].values() for d in e["results"]),
          list(saved["entries"])[:2])

    # (c) عنصر عمره 8 أيام ← طلب جديد ويُحذف القديم؛ والمنتهي غير المستعمل يُنظَّف أيضًا
    rig2 = ImportantRig([pt], docs, supports, brave_results=brave, brave_key="k")
    with rig2:
        important.judge("نص", 98212, cfg)
        n_g, n_b = len(rig2.searches), len(rig2.brave_calls)
        data = json.loads(cache_file().read_text(encoding="utf-8"))
        old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        stale_key = "brave_web|مفتاح قديم|-"
        for e in data["entries"].values():
            e["at"] = old
        data["entries"][stale_key] = {"at": old, "results": [], "raw_count": 0}
        cache_file().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        r3 = important.judge("نص", 98213, cfg)
        after = json.loads(cache_file().read_text(encoding="utf-8"))["entries"]
    check("(c) عمر 8 أيام ← طلبات Google وBrave جديدة بلا ضربة",
          len(rig2.searches) > n_g and len(rig2.brave_calls) > n_b and r3["points"][0]["cache_hits"] == 0,
          (n_g, len(rig2.searches), n_b, len(rig2.brave_calls)))
    check("(c) القديم حُذف: كل ما في الملف حديث ولا أثر لمفتاح المنتهي",
          after and stale_key not in after and all(e["at"] != old for e in after.values()),
          list(after)[:3])

    # (d) مسار «مقال» لا يعرف الذاكرة
    check("(d) article.py لا يعرف ذاكرة البحث (مسار «مقال» لم يُمَسّ)",
          "search_cache.json" not in inspect.getsource(article))


def test_important_1214() -> None:
    """المهمة 1ط (Issue #1214): نص #1209 بوثائق التشغيل الثامن كما في read_docs —
    (2) تاريخ خاطئ يُصحَّح من BBC/DW/ويكيبيديا رغم as_of 2021، و(3) نفي مدقّقَين صريح
    لا تحجبه ثلاثة conflicts_detail. (b) نص #1201 بوثائق التشغيل السابع في
    test_important_1207 وبلا أي تعديل (لا تراجع)."""
    import inspect
    from src import article, important

    cfg = load_config()
    icfg = cfg.path("important")
    texts = [
        "اكتشاف أبعد مجرة معروفة حتى الآن باسم JADES-GS-z14-0 باستخدام تلسكوب جيمس ويب الفضائي",
        "تم إطلاق تلسكوب جيمس ويب الفضائي بنجاح في 25 ديسمبر 2023",
        "أكدت وكالة ناسا أن الشمس ستشرق من المغرب قريبا بسبب انعكاس مفاجئ في المجال المغناطيسي للأرض",
        "وقعت وكالة الفضاء الأوروبية عقدا حصريا لاستخراج الألماس من الغلاف الجوي لكوكب نبتون بحلول عام 2030",
    ]
    points = [
        {"claim": texts[0], "entities": ["مجرة"], "queries": [_q("ar", "مجرة JADES-GS-z14-0 جيمس ويب")]},
        {"claim": texts[1], "entities": ["إطلاق"], "dates": ["25 ديسمبر 2023"],
         "queries": [_q("ar", "تاريخ إطلاق تلسكوب جيمس ويب")]},
        {"claim": texts[2], "entities": ["الشمس"], "queries": [_q("ar", "ناسا الشمس ستشرق من المغرب")]},
        {"claim": texts[3], "entities": ["نبتون"], "queries": [_q("ar", "الألماس نبتون الفضاء الأوروبية")]},
    ]
    docs = {
        "مجرة": [important_doc(n, f"{n}: اكتُشفت المجرة JADES-GS-z14-0 بتلسكوب جيمس ويب، وهو خبر مستقل {i}.")
                 for i, n in enumerate(("RT Arabic", "Khabaragency", "Sky News Arabia"))],
        "إطلاق": [
            important_doc("BBC", "BBC: أُطلق التلسكوب في 25 ديسمبر 2021 من غويانا الفرنسية.",
                          link="https://www.bbc.com/arabic/science-and-tech-62645267"),
            important_doc("DW", "DW: أُطلق التلسكوب يوم 25 ديسمبر 2021 بصاروخ آريان 5.",
                          link="https://www.dw.com/ar/telescope-launch"),
            important_doc("Wikipedia", "Wikipedia: launched December 25, 2021 from Kourou.",
                          link="https://arz.wikipedia.org/wiki/telescope"),
        ],
        "الشمس": [
            important_doc("Fatabyyano", "وكالة ناسا لعلوم الفضاء تؤكّد اقتراب شروق الشمس من مغربها!..خبر كاذب.",
                          link="https://fatabyyano.net/en/nasa-sun-west/"),
            important_doc("The Last Crescent", "The sun rises in the east. However, this is completely incorrect.",
                          link="https://www.thelastcrescent.com/sunrise-from-the-west"),
            important_doc("Falestinona", "تحذير يتداوله ناشرون عن وكالة الفضاء الأوروبية حول الشمس.",
                          link="https://www.falestinona.com/flst/Art/47785"),
            important_doc("Gerasa News", "فيديو يحذر من شروق الشمس من مغربها نقلًا عن الفضاء الأوروبية.",
                          link="https://www.gerasanews.com/print/254682"),
            important_doc("Hibazoom", "مقال يزعم تحذيرًا من وكالة الفضاء الأوروبية بشأن الشمس.",
                          link="https://www.hibazoom.com/article-79865/"),
        ],
        "نبتون": [important_doc(n, f"{n}: تقرير عن الألماس والكواكب لا يذكر عقدًا.", link=f"https://{n}.example/a")
                  for n in ("RT Arabic 2", "TASS")],
    }
    dates = {"BBC": "25 ديسمبر 2021", "DW": "25 ديسمبر 2021", "Wikipedia": "December 25, 2021"}

    def classify(point, names):
        out = []
        for n in names:
            if "JADES" in point:
                out.append(important_stance(n, "supports", "المجرة JADES-GS-z14-0"))
            elif "ديسمبر 2023" in point:
                out.append(important_stance(n, "conflicts_detail", dates[n], detail="تاريخ الإطلاق",
                                            correct_form=dates[n], as_of="2021", detail_kind="date"))
            elif "ناسا" in point and n == "Fatabyyano":
                out.append(important_stance(n, "refutes", "خبر كاذب", verdict_label="False"))
            elif "ناسا" in point and n == "The Last Crescent":
                out.append(important_stance(n, "refutes", "However, this is completely incorrect.",
                                            verdict_label=""))
            elif "ناسا" in point:
                out.append(important_stance(n, "conflicts_detail", "وكالة الفضاء الأوروبية",
                                            detail="الجهة المصدرة", correct_form="وكالة الفضاء الأوروبية",
                                            detail_kind="name"))
            else:
                out.append(important_stance(n, "irrelevant"))
        return {"sources": out}

    with ImportantRig(points, docs, classify):
        important.judge("\n".join(texts), 98014, cfg)
    saved = important.load_saved(98014)
    p1, p2, p3, p4 = saved["points"]

    cor = p2["correction"] or {}
    check("(a) (1) ← confirmed", p1["verdict"] == "confirmed", p1["verdict"])
    check("(a) (2) ← inaccurate بتصحيح 2021 ومصادر BBC/DW/ويكيبيديا وdetail_kind=date",
          p2["verdict"] == "inaccurate" and "2021" in cor.get("correct", "")
          and cor.get("detail_kind") == "date"
          and {s["publisher"] for s in cor["sources"]} == {"BBC", "DW", "Wikipedia"},
          p2["correction"])
    refuted = p3["refuted_by"] or []
    check("(a) (3) ← false بفتبينوا (fatabyyano.net) ومصدر مستقل ثانٍ رغم ثلاثة conflicts_detail",
          p3["verdict"] == "false" and len(refuted) == 2
          and any("fatabyyano.net" in r["link"] for r in refuted),
          (p3["verdict"], p3["note"], refuted))
    check("(a) (4) ← not_found وسقطت (لا أثر)",
          p4["verdict"] == "not_found" and p4["dropped_reason"] == important.NO_TRACE_REASON,
          (p4["verdict"], p4["dropped_reason"]))
    print("جدول (a) #1214:")
    for i, p in enumerate(saved["points"], 1):
        extra = ((p["correction"]["correct"], [s["publisher"] for s in p["correction"]["sources"]])
                 if p["correction"] else [r["publisher"] for r in p["refuted_by"] or []])
        print("  ", f"({i})", p["text"][:45], "←", p["verdict"], "←", extra)

    # تطبيع التواريخ بقيمتها
    ds = ("25 ديسمبر 2021", "2021-12-25", "December 25, 2021", "٢٥ كانون الأول 2021")
    check("(a) «25 ديسمبر 2021» = «2021-12-25» = «December 25, 2021» = بالأرقام الهندية",
          len({important.parse_date(d, icfg) for d in ds}) == 1
          and important.parse_date(ds[0], icfg) == (2021, 12, 25),
          [important.parse_date(d, icfg) for d in ds])
    check("(a) تاريخان مختلفان (25 ثم 26 ديسمبر) لا يتفقان",
          not important._agree_kind("25 ديسمبر 2021", "26 ديسمبر 2021", "date", icfg))

    # (c) مسار «مقال» لم يُمَسّ
    check("(c) article.py لا يعرف detail_kind (مسار «مقال» لم يُمَسّ)",
          "detail_kind" not in inspect.getsource(article))


def test_important_1217() -> None:
    """المهمة 2 (Issue #1217): من الوسم إلى قضية الترشيح. على مخرَج الأنبوب: important.main
    بنص Issue مزيَّف وGitHub مزيَّف، وملفّا #1209 و#1201 الحقيقيان (نسخة ثابتة في
    tests/fixtures/important) بدل الحكم — judge المزيَّف يعيد الملف نفسه ويكتبه كما يفعل الحقيقي."""
    import copy
    import inspect
    import json
    import sys
    from pathlib import Path
    from src import article, decisions, important, important_issue, publish, review, stages

    cfg = load_config()
    fx = Path(__file__).parent / "fixtures" / "important"
    fixture = {n: json.loads((fx / f"{n}.json").read_text(encoding="utf-8")) for n in (1209, 1201)}
    state = {"judge": [], "created": [], "comments": [], "open": True, "next": 5000,
             "model": 0, "brave": 0, "body": "", "other": []}

    def fake_judge(body, issue, cfg=None):
        state["judge"].append(issue)
        r = copy.deepcopy(fixture[issue])
        r.update(issue=issue, body_hash=important.body_hash(body), selection_issue=None,
                 rules_version=important.rules_version(load_config()))
        important.mark_status(r["points"])
        important.save(r)
        return r

    def fake_client():
        state["model"] += 1
        raise AssertionError("نداء نموذج في مسار إعادة الاستعمال")

    def fake_brave(*a, **kw):
        state["brave"] += 1
        raise AssertionError("نداء Brave في مسار إعادة الاستعمال")

    def fake_create(title, body, labels=None):
        state["next"] += 1
        state["created"].append({"number": state["next"], "title": title, "body": body,
                                 "labels": labels})
        return {"number": state["next"]}

    names = [(important, "judge"), (important, "brave_web_articles"), (article, "_client"),
             (review, "fetch_issue_body"), (review, "create_issue"), (review, "comment"),
             (review, "ensure_labels"), (review, "remove_label"), (review, "close_issue"),
             (important_issue, "_issue_open"), (publish, "fetch_issue")]
    saved_fns = [(m, n, getattr(m, n)) for m, n in names]
    important.judge = fake_judge
    important.brave_web_articles = fake_brave
    article._client = fake_client
    review.fetch_issue_body = lambda n: state["body"]
    review.create_issue = fake_create
    review.comment = lambda n, t: state["comments"].append((n, t))
    review.ensure_labels = lambda: None
    review.remove_label = lambda *a: state["other"].append(("remove_label", a))
    review.close_issue = lambda *a: state["other"].append(("close_issue", a))
    important_issue._issue_open = lambda n: state["open"]
    old_argv = sys.argv
    had_decisions = decisions.DECISIONS_FILE.exists()

    def run_main(issue, body):
        state["body"] = body
        sys.argv = ["important", "--issue", str(issue)]
        return important.main()

    try:
        # (a)(d) أول تشغيل لنص #1209
        code = run_main(1209, "نص الموجز لـ1209")
        iss = state["created"][0]
        body = iss["body"]
        print("──── جسم قضية الترشيح لـ1209 كما بُني ────")
        print(body)
        print("──── عنوانها:", iss["title"])
        pts = fixture[1209]["points"]
        check("(a) إنهاء بنجاح وقضية واحدة بوسم important-selection",
              code == 0 and len(state["created"]) == 1 and iss["labels"] == ["important-selection"],
              (code, iss["labels"]))
        check("(a) العنوان «📌 هام — ترشيح من #1209: …» وموضوعه ≤ 50 حرفًا",
              iss["title"].startswith("📌 هام — ترشيح من #1209: ")
              and len(iss["title"].split(": ", 1)[1]) <= 50, iss["title"])
        order = [body.index(stages.stage_header(1, cfg)),
                 body.index(cfg.path("stages.explainer_stage1")),
                 body.index("المصدر: نصّك في #1209"), body.index("**1. "), body.index("🏷️ "),
                 body.index("https://"), body.index("🖼️ بلا صورة"),
                 body.index(cfg.path("stages.image_field")),
                 body.index(cfg.path("stages.options_header")), body.index("<details>")]
        check("(a) ترتيب الأقسام: رأس ← شرح ← مصدر ← عنوان ← شارة ← أدلة ← صورة ← حقل ← انتقال ← الساقط",
              order == sorted(order), order)
        check("(a) نقطة واحدة معروضة (المؤكَّدة) بشارة «هام» وحكمها وثلاثة مصادر مؤيِّدة بروابطها",
              "**2. " not in body and "🏷️ هام · ✅ مؤكَّدة" in body
              and "[RT Arabic](" in body and "[Khabaragency](" in body
              and "[Sky News Arabia](" in body and "A7walspace" not in body, body[:900])
        check("(a) عنوان المؤكَّدة هو claim", f"**1. {pts[0]['claim']}**" in body)
        tail = body[body.index("<details>"):]
        check("(a) الساقط مطويّ: العدد ثلاثة، نصوصها وأسباب سقوطها وملاحظة «أدلة متعارضة»، بلا مربعات",
              "نقاط سقطت (3)" in tail and all(p["text"] in tail for p in pts[1:])
              and important.NO_TRACE_REASON in tail and "أدلة متعارضة" in tail
              and "[ ]" not in tail and "go:" not in tail, tail[:400])
        lines = body.splitlines()
        title_idx = [i for i, ln in enumerate(lines) if ln.startswith("**")]
        check("(a) لا «- [ ]» قبل عنوان أي نقطة ولا عليه",
              all("[ ]" not in lines[i] and not lines[i - 1].lstrip().startswith(("- [", "* ["))
                  for i in title_idx)
              and not any(ln.lstrip().startswith(("- [", "* [")) for ln in lines[:title_idx[0]]),
              title_idx)
        check("(a) الشارات من config.yaml: important.badges",
              cfg.path("important.badges") == {"confirmed": "هام", "not_found": "هام",
                                               "inaccurate": "تصحيح", "false": "تفنيد"})

        # (b) معرّفات النقاط في علامات go تُقرأ بـread_actions(body, 1)
        pub = cfg.path("stages.options.publish")
        marked = body.replace(f"- [ ] {pub}  <!-- go:publish:{pts[0]['id']}",
                              f"- [x] {pub}  <!-- go:publish:{pts[0]['id']}")
        ids = stages.GO_MARKER.findall(body)
        check("(b) معرّف النقطة في علامات go (go2/go3/publish بلا go1) ويُقرأ بـread_actions(body, 1)",
              {i for _, i in ids} == {pts[0]["id"]} and {a for a, _ in ids} == {"go2", "go3", "publish"}
              and stages.read_actions(marked, 1) == ({pts[0]["id"]: "publish"}, [])
              and stages.read_actions(body, 1) == ({}, []), ids)

        # (d) تعليق على الأصلي: رابط + جدول + عدد الساقط
        n1, c1 = state["comments"][0]
        check("(d) تعليق على #1209 برابط القضية وجدول (النقطة ← الحكم) وعدد الساقط",
              n1 == 1209 and f"#{iss['number']}" in c1 and "| النقطة | الحكم |" in c1
              and "✅ مؤكَّدة" in c1 and "سقط: 3" in c1, c1)
        f = important.load_saved(1209)
        check("(a) حالة كل نقطة في الملف: offered/dropped وselection_issue للمعروضة وحدها + البصمة",
              [p["status"] for p in f["points"]] == ["offered", "dropped", "dropped", "dropped"]
              and f["selection_issue"] == iss["number"]
              and [p["selection_issue"] for p in f["points"]] == [iss["number"], None, None, None]
              and f["body_hash"] == important.body_hash("نص الموجز لـ1209"),
              [(p["status"], p["selection_issue"]) for p in f["points"]])

        # (c) نفس النص: صفر نموذج وBrave، لا قضية جديدة، تعليق برابط القديمة
        code = run_main(1209, "نص الموجز  لـ1209\n")     # فرق مسافات فقط: البصمة تُطبِّعها
        check("(c) نص مطابق ← لا حكم جديد ولا نداء نموذج ولا Brave ولا قضية جديدة",
              code == 0 and state["judge"] == [1209] and state["model"] == 0
              and state["brave"] == 0 and len(state["created"]) == 1,
              (state["judge"], state["model"], state["brave"], len(state["created"])))
        check("(c) والتعليق يحمل رابط القضية القديمة نفسها",
              f"#{iss['number']}" in state["comments"][1][1], state["comments"][1][1])
        state["open"] = False
        run_main(1209, "نص الموجز لـ1209")
        check("(c) قضية ترشيح مغلقة ← قضية جديدة بلا حكم جديد",
              len(state["created"]) == 2 and state["judge"] == [1209], state["judge"])
        state["open"] = True
        run_main(1209, "نص مختلف تمامًا لـ1209")
        check("(c) نص متغيّر ← حكم جديد يستبدل الملف (بصمة جديدة) وقضية ترشيح جديدة",
              state["judge"] == [1209, 1209]
              and important.load_saved(1209)["body_hash"] == important.body_hash("نص مختلف تمامًا لـ1209")
              and len(state["created"]) == 3, state["judge"])

        # (f) أقرب حدث + تصحيح + تفنيد (جسم مركَّب من النقطتين الحقيقيتين وتعديلين مصطنعين)
        near = {"title": "حدث قريب موثَّق من ناسا", "description": "وصف الحدث الأقرب",
                "shared_entity": "ناسا",
                "sources": [{"publisher": "مصدر أ", "link": "https://a.example/1"},
                            {"publisher": "مصدر ب", "link": "https://b.example/2"}]}
        mixed = copy.deepcopy(fixture[1201])
        inacc = next(p for p in mixed["points"] if p["verdict"] == "inaccurate")
        circ = next(p for p in mixed["points"] if p.get("circulating_context"))
        circ.update(nearest=near, dropped_reason=None)
        fals = copy.deepcopy(fixture[1209]["points"][2])
        fals.update(verdict="false", icon="❌", dropped_reason=None, note="",
                    refuted_by=[{"publisher": "Fatabyyano", "link": "https://fatabyyano.net/x",
                                 "excerpt": "خبر كاذب", "verdict_label": "كاذب",
                                 "fact_checker": True},
                                {"publisher": "موقع", "link": "https://m.example/y",
                                 "excerpt": "نفي", "verdict_label": "", "fact_checker": False}])
        mixed["points"].append(fals)
        important.mark_status(mixed["points"])
        text = important_issue.build_selection_body(mixed, cfg)
        print("──── جسم مركَّب (تصحيح + أقرب حدث + تفنيد) ────")
        print(text)
        check("(f) not_found بأقرب حدث يُعرض بعنوان الحدث، و«لا أثر» ومصدراه بروابطهما",
              f". {near['title']}**" in text
              and "لا أثر للنقطة كما وردت. الأقرب:" in text and "[مصدر أ](https://a.example/1)" in text
              and "[مصدر ب](https://b.example/2)" in text and "وصف الحدث الأقرب" in text)
        check("(f) «كما ورد عندك» تحمل النقطة الأصلية في حالة nearest",
              f"↳ كما ورد عندك: {circ['text']}" in text, circ["text"])
        check("(f) شارة «تصحيح» وسطر «الخطأ ← الصحيح (as_of)» ومصدران بروابطهما",
              "🏷️ تصحيح · ✏️ غير دقيقة" in text
              and f"← الصحيح: {inacc['correction']['correct']} ({inacc['correction']['as_of']})" in text
              and all(f"]({s['link']})" in text for s in inacc["correction"]["sources"][:2]))
        check("(f) شارة «تفنيد» وسطرا «كذّبها» بحكم المدقّق و«(جهة تدقيق)»",
              "🏷️ تفنيد · ❌ كاذبة" in text
              and "كذّبها: [Fatabyyano](https://fatabyyano.net/x) (حكم: كاذب) (جهة تدقيق)" in text
              and "كذّبها: [موقع](https://m.example/y)" in text)
        img_pt = copy.deepcopy(mixed)
        img_pt["points"][0]["image_candidates"] = [
            {"url": "ftp://bad", "publisher": "x", "link": ""},
            {"url": "https://img.example/a.jpg", "publisher": "الشرق", "link": "https://s/1"}]
        itext = important_issue.build_selection_body(img_pt, cfg)
        offered = [p for p in img_pt["points"] if p["status"] == "offered"]
        check("(f) الصورة: أول عنصر صالح <img width=\"520\"> وسطر 🖼️ بنطاقه، وإلا «بلا صورة من المصادر»",
              '<img src="https://img.example/a.jpg" width="520" />' in itext
              and "🖼️ [صورة الشرق](https://img.example/a.jpg) · img.example" in itext
              and itext.count("🖼️ بلا صورة من المصادر · بحث الويب لاحقًا") == len(offered) - 1)

        # (e) تنفيذ approved على important-selection انتقل إلى المهمة 3: test_important_1221
    finally:
        for m, n, fn in saved_fns:
            setattr(m, n, fn)
        sys.argv = old_argv
        for n in (1209,):
            important.saved_path(n).unlink(missing_ok=True)

    check("(e) الوسم مسجَّل في ensure_labels",
          "important-selection" in inspect.getsource(review.ensure_labels))


def test_important_1221() -> None:
    """المهمة 3 (Issue #1221): قراءة اختيارات المرحلة 1 والكتابة بحسب الحكم ثم المرحلتان 2 و3. على
    مخرَج الأنبوب: important_finalize.finalize بقضية ترشيح معلَّمة من الملفين الثابتين 1209/1201
    ونقاط مصطنعة لـfalse وnot_found، وكاتب مزيَّف يمرّ عبر article._call_draft_model الحقيقي."""
    import copy
    import inspect
    import sys
    from datetime import datetime, timezone
    from pathlib import Path

    from src import decisions, important, important_finalize, important_write, publish, setimage

    cfg = load_config()
    badges = cfg.path("important.badges")
    number, sel = 97000, 97100
    now = datetime.now(timezone.utc).isoformat()

    conf = important_fixture_point(1209, "confirmed")
    inacc = important_fixture_point(1201, "inaccurate")
    fals = important_synthetic_point("false")
    near = important_synthetic_point("not_found")

    def make_result(n, s, pts):
        pts = copy.deepcopy(pts)
        for pt in pts:
            pt.update(status="offered", selection_issue=s)
        r = {"issue": n, "created_at": now, "topic": "", "error": None, "selection_issue": s,
             "points": pts}
        important.save(r)
        return r

    def respond_for(pts):
        def respond(prompt, system):
            for pt in pts:
                key = ((pt.get("correction") or {}).get("correct") or (pt.get("nearest") or {}).get("title")
                       or pt["claim"])
                if key in prompt:
                    return important_good_data(pt)
            raise AssertionError("نداء كتابة لنقطة مجهولة: " + prompt[:80])
        return respond

    def entries_for(pid):
        return [e for e in decisions.load() if e.get("id") == pid]

    def tick(body, action, item_id):
        text = cfg.path(f"stages.options.{'go2_forward' if action == 'go2' else action}")
        return body.replace(f"- [ ] {text}  <!-- go:{action}:{item_id} -->",
                            f"- [x] {text}  <!-- go:{action}:{item_id} -->")

    real_fetch = publish.fetch_issue
    old_argv = sys.argv

    def run_publish(issue, body, labels, flag="--skip-urgent"):
        publish.fetch_issue = lambda n: {"number": n, "body": body,
                                         "labels": [{"name": x} for x in labels]}
        sys.argv = ["publish", "--issue", str(issue), flag]
        try:
            return publish.main()
        finally:
            publish.fetch_issue = real_fetch
            sys.argv = old_argv

    # ── (a) go2 لمؤكَّدة وgo3 لغير دقيقة، وترك الباقي ──
    pts = [conf, inacc, fals, near]
    result = make_result(number, sel, pts)
    body = important_marked_body(result, {conf["id"]: "go2", inacc["id"]: "go3"}, cfg)
    with ImportantWriteRig(respond_for(pts)) as rig:
        code = important_finalize.finalize(sel, body, cfg)
        saved = {p["id"]: p for p in important.load_saved(number)["points"]}
        drafts = {pid: store.load_draft(saved[pid]["draft_id"])[1] for pid in (conf["id"], inacc["id"])}
        check("(a) إنهاء بنجاح ومسودتان بشارتيهما (هام/تصحيح) وأصل important",
              code == 0 and len(drafts) == 2
              and all(d["origin"] == "important" for d in drafts.values())
              and drafts[conf["id"]]["badge"] == badges["confirmed"] == "هام"
              and drafts[inacc["id"]]["badge"] == badges["inaccurate"] == "تصحيح",
              {k: d.get("badge") for k, d in drafts.items()})
        check("(a) المسودة تحمل point_id وsource_issue وverdict وselection_issue",
              all(d["point_id"] == pid and d["source_issue"] == number and d["selection_issue"] == sel
                  for pid, d in drafts.items())
              and drafts[conf["id"]]["verdict"] == "confirmed"
              and drafts[inacc["id"]]["verdict"] == "inaccurate")
        stage2 = [c for c in rig.created if c["labels"] == ["pending-review"]]
        stage3 = [c for c in rig.created if c["labels"] == ["final-review"]]
        check("(a) قضية مرحلة 2 للأولى وحدها (علامة draft: ومربع go1 للعودة إلى الترشيح)",
              len(stage2) == 1 and f"<!-- draft:{drafts[conf['id']]['id']} -->" in stage2[0]["body"]
              and drafts[inacc["id"]]["id"] not in stage2[0]["body"]
              and f"go:go1:{drafts[conf['id']]['id']}" in stage2[0]["body"])
        inacc_now = store.load_draft(drafts[inacc["id"]]["id"])[1]
        check("(a) بطاقة وقضية مرحلة 3 للثانية (علامة go1 أيضًا) وملف البطاقة موجود",
              len(stage3) == 1 and f"<!-- draft:{inacc_now['id']} -->" in stage3[0]["body"]
              and f"go:go1:{inacc_now['id']}" in stage3[0]["body"]
              and (inacc_now.get("image") or "").startswith("drafts/")
              and (DRAFTS_DIR / Path(inacc_now["image"]).relative_to("drafts")).exists())
        check("(a) المؤكَّدة بلا بطاقة بعد (تُبنى عند الانتقال لا عند الكتابة)",
              "image" not in store.load_draft(drafts[conf["id"]]["id"])[1])
        check("(a) حالات النقاط: written/written/unselected/unselected",
              [saved[p["id"]]["status"] for p in pts] == ["written", "written", "unselected", "unselected"]
              and saved[conf["id"]]["draft_id"] == drafts[conf["id"]]["id"],
              [saved[p["id"]]["status"] for p in pts])
        check("(a) «لم يُختر» للباقي في decisions بأصل important وselection_issue، ولا قيد للمكتوبتين",
              all(len(entries_for(p["id"])) == 1 and entries_for(p["id"])[0]["decision"] == "unselected"
                  and entries_for(p["id"])[0]["origin"] == "important"
                  and entries_for(p["id"])[0]["selection_issue"] == sel
                  and entries_for(p["id"])[0]["reject_tag"] == "لم يُختر" for p in (fals, near))
              and not entries_for(conf["id"]) and not entries_for(inacc["id"]))
        check("(a) قضية الترشيح تُغلق (لا publish) كبقية قضايا المرحلة 1",
              ("close_issue", (sel,)) in rig.other, rig.other)
        check("(a) النموذج article.model (Sonnet) لا Opus في كل نداء كتابة، ونداء واحد لكل نقطة",
              len(rig.calls) == 2 and all(c["model"] == cfg.path("article.model")
                                          and "opus" not in c["model"].lower() for c in rig.calls),
              [c["model"] for c in rig.calls])
        inacc_prompt = next(c["prompt"] for c in rig.calls if "86,092,168" in c["prompt"])
        check("(a) تعليمات inaccurate في الموجّه: correction.correct بنصّه والخطأ الشائع وعنوان خبري",
              "«86,092,168 نسمة»" in inacc_prompt and "خطأً شائعًا" in inacc_prompt
              and "post_title وimage_headline جملتان خبريتان" in inacc_prompt, inacc_prompt[-700:])
        check("(a) مصادر الكاتب أدلة النقطة وحدها (مقتطفا correction.sources في برومبت التصحيح)",
              "TRADING ECONOMICS" in inacc_prompt and "Turkish Minute" in inacc_prompt
              and "RT Arabic" not in inacc_prompt)
        print("──── مسودة inaccurate (بالنموذج المزيَّف) ────")
        print(inacc_now["caption"])

    # ── (b) publish لنقطة false: نشر بالفاصل وسطر المصدر يبدأ بالمدقّق ──
    res_b = make_result(number + 1, sel + 1, [fals])
    body_b = important_marked_body(res_b, {fals["id"]: "publish"}, cfg)
    with ImportantWriteRig(respond_for([fals])) as rig:
        code = important_finalize.finalize(sel + 1, body_b, cfg)
        d_b = store.load_draft(important.load_saved(number + 1)["points"][0]["draft_id"])[1]
        check("(b) publish ← تفويض cmd_burst بالمسودة وحدها (فاصل النشر نفسه الذي للأخبار)",
              code == 0 and rig.published == [("cmd_burst", [d_b["id"]], sel + 1)], rig.published)
        check("(b) البطاقة بُنيت بأصل important_false (شارة تفنيد) وسطر المصدر يبدأ بالمدقّق Fatabyyano",
              rig.builds and rig.builds[-1]["origin"] == "important_false"
              and rig.builds[-1]["publisher"][0] == "Fatabyyano"
              and d_b["source"]["publishers"] == ["Fatabyyano", "موقع النفي"]
              and d_b["badge"] == "تفنيد", (rig.builds, d_b["source"]))
        check("(b) صورة الناشر من image_candidates للنقطة أول سلّم الصورة",
              rig.builds[-1]["image_urls"] == ["https://img.example/a.jpg"], rig.builds[-1])
        prompt_b = rig.calls[0]["prompt"]
        check("(b) تعليمات false: الشائعة مرة واحدة «ادّعاءً متداولًا» وتسمية المدقّق وحكمه",
              "«ادّعاءً متداولًا»" in prompt_b and "«Fatabyyano»" in prompt_b
              and "وحكمه «كاذب»" in prompt_b and "لم تصدر ناسا أي بيان بهذا المعنى" in prompt_b,
              prompt_b[-900:])
        print("──── مسودة false (بالنموذج المزيَّف) ────")
        print(d_b["caption"])

    # ── (c) نص كل حكم يمرّ بفحوص g36–g39 ──
    res_c = make_result(number + 2, sel + 2, pts)
    body_c = important_marked_body(res_c, {p["id"]: "go2" for p in pts}, cfg)
    with ImportantWriteRig(respond_for(pts)) as rig:
        code = important_finalize.finalize(sel + 2, body_c, cfg)
        saved_c = {p["id"]: p for p in important.load_saved(number + 2)["points"]}
        verdicts = {}
        for p in pts:
            d = store.load_draft(saved_c[p["id"]]["draft_id"])[1]
            verdicts[p["verdict"]] = important_write.check_text(p, d["arabic"], cfg)
        check("(c) نص المسودة لكل حكم (confirmed/inaccurate/false/not_found) يمرّ بفحوص g36–g39",
              code == 0 and len(verdicts) == 4 and all(v is None for v in verdicts.values()), verdicts)
        stage2_c = rig.created[0]
        check("(c) قضية المرحلة 2 للأربع، وشارات جدول البطاقات مطابقة لـimportant.badges",
              all(f"<!-- draft:{saved_c[p['id']]['draft_id']} -->" in stage2_c["body"] for p in pts)
              and cfg.path("cards.important.badge") == badges["confirmed"] == badges["not_found"]
              and cfg.path("cards.important_inaccurate.badge") == badges["inaccurate"]
              and cfg.path("cards.important_false.badge") == badges["false"])
        print("──── جسم قضية المرحلة 2 (فيها مسودتا inaccurate وfalse) ────")
        print(stage2_c["body"])

    # ── (d) go1 من المرحلة 2 ثم اختيارها ثانية بلا كتابة ──
    res_d = make_result(number + 3, sel + 3, [conf, inacc])
    body_d = important_marked_body(res_d, {conf["id"]: "go2", inacc["id"]: "go2"}, cfg)
    with ImportantWriteRig(respond_for([conf, inacc])) as rig:
        important_finalize.finalize(sel + 3, body_d, cfg)
        saved_d = {p["id"]: p for p in important.load_saved(number + 3)["points"]}
        d_conf = store.load_draft(saved_d[conf["id"]]["draft_id"])[1]
        stage2_body = tick(rig.created[0]["body"], "go1", d_conf["id"])
        writes = len(rig.calls)
        check("(d) مربع go1 موجود في قضية المرحلة 2 ومُعلَّم", f"[x] {cfg.path('stages.options.go1')}" in stage2_body)
        code_p = run_publish(9201, stage2_body, ["pending-review", "approved"])
        returned = store.load_draft(d_conf["id"])[1]
        reopened = [c for c in rig.created if c["labels"] == ["important-selection"]]
        pt_after = {p["id"]: p for p in important.load_saved(number + 3)["points"]}[conf["id"]]
        check("(d) go1 من المرحلة 2: المسودة returned بنصها (لا كتابة) والنقطة offered/returned",
              code_p == 0 and returned["status"] == "returned" and returned["returned_from_stage"] == 2
              and returned["arabic"] == d_conf["arabic"] and len(rig.calls) == writes
              and pt_after["status"] == "offered" and pt_after["returned"] is True
              and pt_after["draft_id"] == d_conf["id"], (returned["status"], pt_after))
        check("(d) قرار returned في decisions بأصل important وقضية الترشيح التي جاءت منها",
              any(e["decision"] == "returned" and e["origin"] == "important"
                  and e["selection_issue"] == sel + 3 and e["returned_from_stage"] == 2
                  for e in entries_for(d_conf["id"])), entries_for(d_conf["id"]))
        new_body = reopened[0]["body"] if reopened else ""
        new_sel = reopened[0]["number"] if reopened else 0
        check("(d) قضية ترشيح «هام» جديدة للنص نفسه #N فيها النقطة أعلاها بشارة «↩️ أعدته من المرحلة 2»",
              len(reopened) == 1 and f"المصدر: نصّك في #{number + 3}" in new_body
              and "**1. ↩️ أعدته من المرحلة 2 · " in new_body and "**2." not in new_body
              and pt_after["selection_issue"] == new_sel, new_body[:400])
        created_before = len(rig.created)
        code_r = important_finalize.finalize(new_sel, tick(new_body, "go2", conf["id"]), cfg)
        back = store.load_draft(d_conf["id"])[1]
        check("(d) اختيارها ثانية يعيد المسودة نفسها بلا كتابة (عدّاد النداءات 0) وقضية مرحلة 2 جديدة",
              code_r == 0 and len(rig.calls) == writes and back["status"] == "pending"
              and back["arabic"] == d_conf["arabic"] and "returned_from_stage" not in back
              and len(rig.created) == created_before + 1
              and rig.created[-1]["labels"] == ["pending-review"]
              and f"<!-- draft:{d_conf['id']} -->" in rig.created[-1]["body"],
              (code_r, len(rig.calls), writes, back["status"], len(rig.created), created_before,
               rig.created[-1]["labels"]))
    res_d3 = make_result(number + 4, sel + 4, [inacc])
    body_d3 = important_marked_body(res_d3, {inacc["id"]: "go3"}, cfg)
    with ImportantWriteRig(respond_for([inacc])) as rig:
        important_finalize.finalize(sel + 4, body_d3, cfg)
        pid3 = important.load_saved(number + 4)["points"][0]["draft_id"]
        run_publish(9202, tick(rig.created[-1]["body"], "go1", pid3), ["final-review", "approved"])
        reo3 = [c for c in rig.created if c["labels"] == ["important-selection"]]
        d3 = store.load_draft(pid3)[1]
        check("(d) go1 من المرحلة 3: returned_from_stage=3 وقضية ترشيح جديدة بشارة «من المرحلة 3»",
              d3["status"] == "returned" and d3["returned_from_stage"] == 3
              and len(reo3) == 1 and "↩️ أعدته من المرحلة 3 · " in reo3[0]["body"])

    # ── (e) التعليق المؤقت من #1217 لم يعد يُكتب ──
    res_e = make_result(number + 5, sel + 5, [conf])
    body_e = important_marked_body(res_e, {}, cfg)
    with ImportantWriteRig(respond_for([conf])) as rig:
        c_normal = run_publish(sel + 5, body_e, ["important-selection", "approved"], "--skip-urgent")
        quiet = list(rig.comments)
        c_urgent = run_publish(sel + 5, body_e, ["important-selection", "approved"], "--urgent-only")
        temp = "تُنفَّذ بعد اكتمال المهمة 3"
        check("(e) المسار العادي لا يكتب شيئًا والسريع ينفّذ finalize (لا تعليق «بعد اكتمال المهمة 3»)",
              c_normal == 0 and quiet == [] and c_urgent == 0
              and rig.comments and all(temp not in t for _, t in rig.comments)
              and "لم يُعلَّم على أي نقطة" in rig.comments[-1][1]
              and ("remove_label", (sel + 5, "approved")) in rig.other, rig.comments)
    check("(e) نص التعليق المؤقت اختفى من publish.py", "المهمة 3 — لا شيء ضاع" not in inspect.getsource(publish))

    # ── (g) صورة المرحلة 1 لنقطة «هام» تنتقل إلى مسودتها (manual_image) ──
    make_result(number + 6, sel + 6, [near])
    real_dl = setimage.download_image
    setimage.download_image = lambda url, failures=None, **kw: object()
    try:
        got, why = setimage.apply_selection_image(near["id"], "https://img.example/mine.jpg", cfg, sel + 6)
    finally:
        setimage.download_image = real_dl
    body_g = important_marked_body(important.load_saved(number + 6), {near["id"]: "go2"}, cfg)
    with ImportantWriteRig(respond_for([near])) as rig:
        important_finalize.finalize(sel + 6, body_g, cfg)
        d_g = store.load_draft(important.load_saved(number + 6)["points"][0]["draft_id"])[1]
        check("(g) رابط المرحلة 1 يُحفظ على النقطة ثم على المسودة manual_image",
              got and got["kind"] == "important" and why == ""
              and d_g.get("manual_image") == "https://img.example/mine.jpg", (got, why))

    for n in range(number, number + 7):
        important.saved_path(n).unlink(missing_ok=True)


def test_important_1225() -> None:
    """المهمة 3ب (Issue #1225): اقتباس الادّعاء المصحَّح، لا فشل صامت، والادّعاء المتجاوَز زمنيًا.
    على مخرَج الأنبوب: النقطتان الحقيقيتان 4591dfda9524/9c5d1c45c0a3 من fixture 1225."""
    import copy
    import sys
    from datetime import datetime, timezone

    from src import important, important_finalize, important_issue, important_write, publish
    from tests.helpers import tick_marker

    cfg = load_config()
    number, sel = 98000, 98100
    now = datetime.now(timezone.utc).isoformat()
    fx_inacc = important_fixture_point(1225, "inaccurate")
    fx_conf = important_fixture_point(1225, "confirmed")

    def make_result(n, s, pts):
        pts = copy.deepcopy(pts)
        for pt in pts:
            pt.update(status="offered", selection_issue=s)
            pt.pop("write_error", None)   # الأصل الحقيقي فشلت كتابته؛ هنا يبدأ نظيفًا
        r = {"issue": n, "created_at": now, "topic": "", "error": None, "selection_issue": s,
             "points": pts}
        important.save(r)
        return r

    real_fetch = publish.fetch_issue
    old_argv = sys.argv

    def run_publish(issue, body):
        labels = [{"name": "important-selection"}, {"name": "approved"}]
        publish.fetch_issue = lambda n: {"number": n, "body": body, "labels": labels}
        sys.argv = ["publish", "--issue", str(issue), "--urgent-only"]
        try:
            return publish.main()
        finally:
            publish.fetch_issue = real_fetch
            sys.argv = old_argv

    # ── (a) النقطة 4591dfda9524: الكاتب يقتبس الادّعاء الخاطئ بين علامتي تنصيص ← تُقبل (كانت تُرفض) ──
    good = important_good_data(fx_inacc)
    quoted = dict(good, post_body=good["post_body"]
                  + f" وقد انتشر أن «{fx_inacc['claim']}» وهذا غير دقيق.")
    res_a = make_result(number, sel, [fx_inacc])
    body_a = important_marked_body(res_a, {fx_inacc["id"]: "go3"}, cfg)
    with ImportantWriteRig(lambda prompt, system: quoted) as rig:
        code = important_finalize.finalize(sel, body_a, cfg)
        pt = important.load_saved(number)["points"][0]
        check("(a) نقطة 4591dfda9524 بنص يقتبس claim ← written (لا failed ولا selected)",
              fx_inacc["id"] == "4591dfda9524" and code == 0 and pt["status"] == "written"
              and not pt.get("write_error"), (pt["status"], pt.get("write_error")))
        d = store.load_draft(pt["draft_id"])[1]
        stage3 = [c for c in rig.created if c["labels"] == ["final-review"]]
        check("(a) بطاقة «تصحيح» بُنيت وفُتحت قضية مرحلة 3",
              rig.builds and rig.builds[-1]["origin"] == "important_inaccurate"
              and d["badge"] == "تصحيح" and len(stage3) == 1
              and f"<!-- draft:{d['id']} -->" in stage3[0]["body"], (rig.builds, rig.created))
        check("(a) نص الكاتب فيه الادّعاء بين علامتي تنصيص فعلًا",
              f"«{fx_inacc['claim']}»" in d["arabic"]["post_body"])
    check("(a) السماح لـinaccurate وfalse وحدهما: claim وسياق التداول، وغيرهما فارغ",
          important_write.allowed_quotes({"verdict": "false", "claim": "ك", "circulating_context": "س"}) == ["ك", "س"]
          and important_write.allowed_quotes({"verdict": "inaccurate", "claim": "ك"}) == ["ك"]
          and important_write.allowed_quotes({"verdict": "confirmed", "claim": "ك"}) == []
          and important_write.allowed_quotes({"verdict": "not_found", "claim": "ك"}) == [])

    # ── (b) كتابة تفشل مرتين ← failed + تعليق على قضية الترشيح + قضية ترشيح جديدة بشارة «فشلت الكتابة» ──
    bad = dict(good, post_title="عنوان لا يحوي الصيغة", post_body="نص بلا الصيغة المطلوبة.")
    answer = [bad]
    res_b = make_result(number + 1, sel + 1, [fx_inacc])
    body_b = important_marked_body(res_b, {fx_inacc["id"]: "go2"}, cfg)
    with ImportantWriteRig(lambda prompt, system: answer[0]) as rig:
        code = run_publish(sel + 1, body_b)
        pt = important.load_saved(number + 1)["points"][0]
        reopened = [c for c in rig.created if c["labels"] == ["important-selection"]]
        why = "الصيغة الصحيحة غائبة عن العنوان أو أول جملة"
        title = important_issue.display_title(fx_inacc)[:60]
        note = [t for n, t in rig.comments if n == sel + 1]
        check("(b) كتابة فشلت مرتين (نداءان) ← failed وwrite_error في الملف ولا مسودة",
              len(rig.calls) == 2 and pt.get("write_error") == why
              and "draft_id" not in pt, (len(rig.calls), pt.get("status"), pt.get("write_error")))
        check("(b) تعليق على قضية الترشيح نفسها: «⚠️ فشلت كتابة: <الموضوع> — السبب: <write_error>»",
              any(f"⚠️ فشلت كتابة: {title} — السبب: {why}" in t for t in note), note)
        new_sel = reopened[0]["number"] if reopened else 0
        check("(b) قضية ترشيح جديدة فيها النقطة بـ«⚠️ فشلت الكتابة: <سبب>» ولا قضية مرحلة 2/3",
              code == 0 and len(reopened) == 1 and f"⚠️ فشلت الكتابة: {why} · " in reopened[0]["body"]
              and f"go:go2:{fx_inacc['id']}" in reopened[0]["body"]
              and all(c["labels"] == ["important-selection"] for c in rig.created)
              and pt["status"] == "offered" and pt["selection_issue"] == new_sel,
              (code, [c["labels"] for c in rig.created], pt["status"]))
        # إعادة اختيارها تعيد المحاولة: الكاتب الآن يكتب سليمًا فتُقبل
        answer[0] = quoted
        calls = len(rig.calls)
        code_r = important_finalize.finalize(
            new_sel, tick_marker(reopened[0]["body"], f"go:go2:{fx_inacc['id']}"), cfg)
        pt2 = important.load_saved(number + 1)["points"][0]
        check("(b) إعادة اختيارها تعيد المحاولة فتُكتب ويُمسح خطؤها",
              code_r == 0 and len(rig.calls) == calls + 1 and pt2["status"] == "written"
              and not pt2.get("write_error") and not pt2.get("write_failed"),
              (pt2["status"], pt2.get("write_error")))

    # ── (c) الادّعاء المتجاوَز زمنيًا: النقطة 9c5d1c45c0a3 بوثائق read_docs الحقيقية ──
    claim = fx_conf["claim"]
    marker = "كلمةتجاوز"
    by_pub = dict((e["publisher"], e) for e in fx_conf["evidence"])
    real_docs = [d for d in fx_conf["read_docs"] if d["stance"] == "supports"]
    check("(c) fixture النقطة الحقيقية 9c5d1c45c0a3 بوثائقها المؤيِّدة",
          fx_conf["id"] == "9c5d1c45c0a3" and len(real_docs) >= 3)
    docs = [important_doc(d["publisher"], by_pub[d["publisher"]]["excerpt"], link=d["link"])
            for d in real_docs]
    newer = {"fact": "تجاوزتها المجرة MoM-z14 المرصودة", "date": "16 مايو 2025"}
    okaz = important_doc(
        "okaz.com.sa",
        "كانت JADES-GS-z14-0 أبعد مجرة معروفة حتى وقت قريب (قبل اكتشاف MoM-z14 في 16 مايو 2025).",
        link="https://www.okaz.com.sa/variety/na/2233512")
    second = important_doc("مجلة الفضاء", "المجرة MoM-z14 المرصودة في مايو 2025 أبعد من كل ما سبقها.",
                           link="https://space.example/mom-z14")
    pt_in = {"claim": claim, "asserted": "", "entities": [marker], "dates": [], "numbers": [],
             "queries": [{"lang": "ar", "q": f"{marker} {claim}"}], "factcheck_query": "",
             "is_unnamed_event": False}

    def judge(n, extra_docs, sup_names):
        def classify(point, names):
            rows = []
            for name in names:
                if name in sup_names:
                    rows.append(important_stance(name, "related_other", "", same_event=False,
                                                 superseded_by=newer))
                else:
                    rows.append(important_stance(name, "supports", by_pub[name]["excerpt"]))
            return {"sources": rows}
        with ImportantRig([pt_in], {marker: docs + extra_docs}, classify):
            important.judge("نص الـIssue كاملًا", n, cfg)
        return important.load_saved(n)["points"][0]

    two = judge(number + 2, [okaz, second], {"okaz.com.sa", "مجلة الفضاء"})
    cor = two.get("correction") or {}
    check("(c) مع وثيقة ثانية مستقلة تذكر MoM-z14 ← inaccurate بتصحيح الأحدث بتاريخها وdetail_kind=superseded",
          two["verdict"] == "inaccurate" and "MoM-z14" in cor.get("correct", "")
          and "16 مايو 2025" in cor.get("correct", "") and cor.get("detail_kind") == "superseded"
          and set(s["publisher"] for s in cor.get("sources", [])) == {"okaz.com.sa", "مجلة الفضاء"},
          (two["verdict"], cor))
    one = judge(number + 3, [okaz], {"okaz.com.sa"})
    check("(c) بوثيقة okaz وحدها ← confirmed مع note «قد يكون متجاوَزًا» باسم الناشر",
          one["verdict"] == "confirmed" and "⚠️ قد يكون متجاوَزًا" in one["note"]
          and "MoM-z14" in one["note"] and "(okaz.com.sa)" in one["note"]
          and one["superseded_note"] == one["note"], (one["verdict"], one["note"]))
    saved_one = important.load_saved(number + 3)
    saved_one["selection_issue"] = sel + 3
    for p in saved_one["points"]:
        p.update(selection_issue=sel + 3, status="offered",
                 image_candidates=copy.deepcopy(fx_conf["image_candidates"]))
    important.save(saved_one)
    sel_body = important_issue.build_selection_body(saved_one, cfg)
    check("(c) جسم قضية الترشيح يحمل التنبيه سطرًا بارزًا (اقتباس) بعد الشارة",
          f"  > {one['superseded_note']}" in sel_body, sel_body[:600])
    print("──── جسم قضية الترشيح لنقطة 9c5d1c45c0a3 بوثيقة okaz وحدها ────")
    print(sel_body)
    body_c = important_marked_body(saved_one, {one["id"]: "go2"}, cfg)
    with ImportantWriteRig(lambda prompt, system: important_good_data(one)) as rig:
        important_finalize.finalize(sel + 3, body_c, cfg)
        stage2 = [c for c in rig.created if c["labels"] == ["pending-review"]]
        dr = store.load_draft(important.load_saved(number + 3)["points"][0]["draft_id"])[1]
        check("(c) المسودة تحمل superseded_note وقضية المرحلة 2 تعرضه سطرًا بارزًا",
              dr.get("superseded_note") == one["superseded_note"] and len(stage2) == 1
              and f"  > {one['superseded_note']}" in stage2[0]["body"], stage2[:1])
    instr = important_write.instructions(one, cfg)
    check("(c) تعليمات confirmed تُلزم الكاتب بتأريخ صيغة التفضيل بتاريخ الإعلان",
          "بتاريخ الإعلان" in instr and "حتى الآن" in instr, instr)

    for n in range(number, number + 4):
        important.saved_path(n).unlink(missing_ok=True)


def test_important_1229() -> None:
    """المهمة 3ج (Issue #1229): شائعة «ناسا/الشمس من المغرب» حُكم عليها confirmed ونُشرت. على مخرَج
    الأنبوب، بنقاط state/important/1209.json الثلاث كما هي (fixture 1229): (a) حارس التأييد،
    (b)/(c) كتابة التصحيح بلا رفض نسخ ولا اقتباس مختلق."""
    import copy
    from datetime import datetime, timezone

    from src import important, important_finalize, important_write

    cfg = load_config()
    now = datetime.now(timezone.utc).isoformat()
    stale = ("draft_id", "written_at", "write_error", "failed_at", "write_failed", "action")

    # ── (a) النقطة 9185665f38b8 بوثائق read_docs الحقيقية ← false (Issue #1282: كان not_found «أدلة متعارضة») ──
    fx = important_fixture_point(1229, "confirmed")
    check("(a) fixture النقطة الحقيقية 9185665f38b8", fx["id"] == "9185665f38b8", fx["id"])
    by_pub = {e["publisher"]: e for e in fx["evidence"]}
    other_event = {x["publisher"] for x in fx["read_docs"] if x["stance"] == "related_other"}
    marker = "كلمةناسا"
    docs, stances = [], {}
    for d in fx["read_docs"]:
        if d["stance"] == "deduped":
            continue
        ev = by_pub.get(d["publisher"])
        text = (ev["excerpt"] if ev else f"{d['publisher']}: نص لا صلة له بالادّعاء.") + " " + d["publisher"]
        docs.append(important_doc(d["publisher"], text, link=d["link"]))
        if ev and d["stance"] in ("supports", "refutes"):
            stances[d["publisher"]] = (d["stance"], ev["excerpt"])
        elif d["stance"] == "related_other":
            stances[d["publisher"]] = ("supports", "")

    def classify(point, names):
        rows = []
        for n in names:
            kind, excerpt = stances.get(n, ("irrelevant", ""))
            rows.append(important_stance(n, kind, excerpt, same_event=n not in other_event,
                                         verdict_label=""))
        return {"sources": rows}

    pt_in = {"claim": fx["claim"], "entities": [marker],
             "queries": [{"lang": "ar", "q": f"{marker} {fx['claim']}"}]}
    with ImportantRig([pt_in], {marker: docs}, classify, strict_known=True):
        important.judge("نص الـIssue كاملًا", 98290, cfg)
    p = important.load_saved(98290)["points"][0]
    check("(a) 9185665f38b8 بوثائقها الحقيقية ← false لا confirmed (مقتطف المدقّق «خبر كاذب» حكم صريح)",
          p["verdict"] == "false", (p["verdict"], p.get("note")))
    check("(a) وrefuted_by فيه Fatabyyano بمقتطف «كاذب» (الحكم صريح بكلمة من explicit_false_words)",
          any(r["publisher"] == "Fatabyyano" and "كاذب" in r["excerpt"] for r in p.get("refuted_by") or []),
          p.get("refuted_by"))
    check("(a) وليس confirmed ولا not_found (ينقلب فحص «ولا false» القديم)",
          p["verdict"] not in ("confirmed", "not_found"), p["verdict"])
    important.saved_path(98290).unlink(missing_ok=True)

    # ── (b) النقطة 04ae7eae0358: مقالة تصحيح ببطاقة «تصحيح» بلا رفض نسخ ──
    def write(n, point, data, mark="go3"):
        sel = n + 100
        point = {k: v for k, v in copy.deepcopy(point).items() if k not in stale}
        point["selection_issue"] = sel
        result = {"issue": n, "created_at": now, "topic": "", "error": None,
                  "selection_issue": sel, "points": [point]}
        important.save(result)
        body = important_marked_body(result, {point["id"]: mark}, cfg)
        with ImportantWriteRig(lambda prompt, system: data) as rig:
            code = important_finalize.finalize(sel, body, cfg)
            pt = important.load_saved(n)["points"][0]
            draft = store.load_draft(pt["draft_id"])[1] if pt.get("draft_id") else None
        important.saved_path(n).unlink(missing_ok=True)
        return rig, code, pt, draft

    fx_b = important_fixture_point(1229, "inaccurate", 1)
    rig, code, pt, d = write(98291, fx_b, important_good_data(fx_b))
    check("(b) 04ae7eae0358 ← written بمحاولة واحدة دون رفض نسخ",
          fx_b["id"] == "04ae7eae0358" and code == 0 and pt["status"] == "written"
          and len(rig.calls) == 1 and not pt.get("write_error"),
          (pt["status"], pt.get("write_error"), len(rig.calls)))
    check("(b) ببطاقة «تصحيح» (important_inaccurate) ونص التصحيح كما هو في العنوان",
          d is not None and d["badge"] == "تصحيح" and rig.builds
          and rig.builds[-1]["origin"] == "important_inaccurate"
          and fx_b["correction"]["correct"] in d["arabic"]["post_title"],
          (rig.builds, d and d["badge"]))

    # ── (c) النقطة 602ac9017f8e: تُكتب دون اقتباس مختلق ──
    fx_c = important_fixture_point(1229, "inaccurate", 0)
    good = important_good_data(fx_c)
    quoted = dict(good, post_body=good["post_body"] + f" وقد انتشر أن «{fx_c['claim']}» وهذا غير دقيق.")
    rig, code, pt, d = write(98292, fx_c, quoted)
    check("(c) 602ac9017f8e بنص يقتبس claim حرفيًا ← written",
          fx_c["id"] == "602ac9017f8e" and pt["status"] == "written" and not pt.get("write_error"),
          (pt["status"], pt.get("write_error")))
    made_up = dict(good, post_body=good["post_body"] + " وكتب أحدهم «أبعد مجرة هي JADES-GS-z99 بلا شك».")
    rig, code, pt, d = write(98293, fx_c, made_up)
    check("(c) اقتباس مختلق بين علامتي تنصيص ← مرفوض (failed) بعد محاولتين",
          pt["status"] == "failed" and "اقتباس بين علامتي تنصيص" in (pt.get("write_error") or "")
          and len(rig.calls) == 2, (pt["status"], pt.get("write_error"), len(rig.calls)))
    check("(c) تعليمات الكاتب: لا صياغة بين علامتي تنصيص إلا نقلًا حرفيًا من claim أو مقتطف مصدر",
          "لا تضع صياغة بين علامتي تنصيص" in important_write.instructions(fx_c, cfg),
          important_write.instructions(fx_c, cfg))


def test_important_1233() -> None:
    """Issue #1233: عنوان خبري في تصحيح/تفنيد، وتنبيه الجمل بلا مصدر، وتقاعد «مقال» و«طلب». على مخرَج
    الأنبوب بنصَّي الكاتب الحقيقيين من مسودتَي 602ac9017f8e و04ae7eae0358 (fixture 1233)."""
    import copy
    import json
    import logging
    import sys
    from datetime import datetime, timezone
    from pathlib import Path

    from src import important, important_finalize
    from tests.helpers import store

    cfg = load_config()
    now = datetime.now(timezone.utc).isoformat()
    stale = ("draft_id", "written_at", "write_error", "failed_at", "write_failed", "action")
    authors = json.loads((Path(__file__).parent / "fixtures" / "important" / "1233.json")
                         .read_text(encoding="utf-8"))

    def write(n, point, data, mark):
        sel = n + 100
        point = {k: v for k, v in copy.deepcopy(point).items() if k not in stale}
        point["selection_issue"] = sel
        result = {"issue": n, "created_at": now, "topic": "", "error": None,
                  "selection_issue": sel, "points": [point]}
        important.save(result)
        body = important_marked_body(result, {point["id"]: mark}, cfg)
        with ImportantWriteRig(lambda prompt, system: data) as rig:
            important_finalize.finalize(sel, body, cfg)
            pt = important.load_saved(n)["points"][0]
            draft = store.load_draft(pt["draft_id"])[1] if pt.get("draft_id") else None
        important.saved_path(n).unlink(missing_ok=True)
        return rig, pt, draft

    # ── (a) 602ac9017f8e: جملة خبرية أُلحقت بها «؟» ← العنوان الافتراضي بلا «؟» ──
    fx_a = important_fixture_point(1229, "inaccurate", 0)
    real = authors["602ac9017f8e"]
    check("(a) نص الكاتب الحقيقي ينتهي عنوانه بـ«؟» (الشاهد)", real["post_title"].endswith("؟"), real["post_title"])
    rig, pt, d = write(98331, fx_a, real, "go2")
    check("(a) 602ac9017f8e بنصه الحقيقي ← مسودة، والعنوان الافتراضي بلا «؟»",
          fx_a["id"] == "602ac9017f8e" and d is not None
          and not d["arabic"]["post_title"].rstrip().endswith(("؟", "?"))
          and d["arabic"]["post_title"] == real["post_title"].rstrip("؟"),
          (pt["status"], pt.get("write_error"), d and d["arabic"]["post_title"]))
    check("(a) وأول عنوان في headlines بلا «؟» وصورة العنوان كذلك",
          d is not None and not d["headlines"][0].rstrip().endswith(("؟", "?"))
          and not d["arabic"]["image_headline"].rstrip().endswith(("؟", "?")), d and d["headlines"])

    # ── (b) 04ae7eae0358: «تمت في موعدها المحدد» ← تنبيه بالجملة في قضية المرحلة 3 ──
    fx_b = important_fixture_point(1229, "inaccurate", 1)
    real_b = authors["04ae7eae0358"]
    rig, pt, d = write(98332, fx_b, real_b, "go3")
    stage3 = [c for c in rig.created if "المرحلة 3 من 4" in c["body"]]
    check("(b) 04ae7eae0358 بنصه الحقيقي ← مسودة (لا رفض) وفيها warnings بالجملة",
          fx_b["id"] == "04ae7eae0358" and d is not None
          and any("تمت في موعدها المحدد" in w for w in d.get("warnings") or []),
          (pt["status"], pt.get("write_error"), d and d.get("warnings")))
    check("(b) وقسم «⚠️ تنبيهات للمراجعة» في قضية المرحلة 3 بالجملة نفسها",
          len(stage3) == 1 and "⚠️ تنبيهات للمراجعة" in stage3[0]["body"]
          and "تمت في موعدها المحدد" in stage3[0]["body"], [c["body"][:200] for c in rig.created])
    # قيد معروف: جملة التصحيح الصحيحة نفسها تُنبَّه أيضًا لأن «الخامس والعشرين» مكتوبة حروفًا والمصدر
    # يكتبها «25» — الكاشف نصّي (article._unsourced_entities) ولا يحوّل الأرقام المكتوبة؛ تنبيه لا رفض
    check("(b) والتنبيه خارج النص المنشور (caption والمتن) ولا يمنع الكتابة",
          d is not None and "تنبيهات" not in d["caption"] and "تنبيهات" not in d["arabic"]["post_body"]
          and pt["status"] == "written", d and d.get("warnings"))
    print("قسم التنبيهات في قضية المرحلة 3 (b):")
    if stage3:
        body = stage3[0]["body"]
        start = body.index("⚠️ تنبيهات للمراجعة")
        print(body[start - 2:body.index("<img", start) if "<img" in body[start:] else start + 900])

    # ── (c) confirmed: قاعدة «الأول سؤال» كما هي ──
    from src import headlines as headlines_mod
    conf = important_fixture_point(1229, "confirmed")
    conf = {k: v for k, v in conf.items() if k not in stale}
    q_title = {**important_good_data(conf), "post_title": "هل اكتشف العلماء مجرة جديدة؟"}
    rig, pt, d = write(98333, conf, q_title, "go2")
    check("(c) confirmed: عنوان بصيغة سؤال يبقى كما كتبه الكاتب (لا نزع «؟» ولا رفض)",
          d is not None and d["arabic"]["post_title"] == "هل اكتشف العلماء مجرة جديدة؟",
          (pt["status"], pt.get("write_error")))
    check("(c) confirmed وnot_found: headlines بقاعدة السؤال (first_question افتراضي)",
          d is not None and d["headlines"][0].endswith("؟")
          and not __import__("src.important_write", fromlist=["x"]).is_statement_verdict(conf, cfg)
          and not __import__("src.important_write", fromlist=["x"]).is_statement_verdict(
              {"verdict": "not_found"}, cfg), d and d["headlines"])

    # ── (d) تشغيل src.request وsrc.article مباشرة: تحذير التقاعد ثم يكملان كما هما ──
    from src import article, request, review

    class Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.msgs = []

        def emit(self, record):
            self.msgs.append(record.getMessage())

    def run_main(mod, argv, patches):
        grab, saved_argv, undo = Grab(), sys.argv, []
        logging.getLogger().addHandler(grab)
        try:
            sys.argv = ["x", *argv]
            for obj, name, val in patches:
                undo.append((obj, name, getattr(obj, name)))
                setattr(obj, name, val)
            return mod.main(), grab.msgs
        finally:
            sys.argv = saved_argv
            for obj, name, val in reversed(undo):
                setattr(obj, name, val)
            logging.getLogger().removeHandler(grab)

    reached = []
    code, msgs = run_main(request, ["--query", "اختبار", "--dry-run"],
                          [(request, "find", lambda q, c, days=0, stats=None: reached.append(q) or []),
                           (request, "step_summary", lambda t: None)])
    check("(d) python -m src.request: تحذير «مسار متقاعد — استعمل وسم «هام»» ثم يكمل (يبلغ البحث ويعيد 0)",
          code == 0 and reached == ["اختبار"] and "مسار متقاعد — استعمل وسم «هام»" in msgs, (code, reached, msgs))
    commented = []
    code, msgs = run_main(article, ["--issue", "1"],
                          [(review, "fetch_issue_body", lambda n: ""),
                           (review, "comment", lambda n, t: commented.append(n))])
    check("(d) python -m src.article: التحذير نفسه ثم يكمل كما هو (يقرأ الـIssue ويعلّق ويعيد 0)",
          code == 0 and commented == [1] and "مسار متقاعد — استعمل وسم «هام»" in msgs, (code, commented, msgs))


def test_important_1282() -> None:
    """Issue #1282 (حادثة #1278): أنبوب نص #1278 كما حُفظ فعلًا (tests/fixtures/important/1278.json، نسخة
    مطابقة لـstate/important/1278.json): تُبنى وثائق كل نقطة من read_docs ومقتطفات evidence، كما يفعل اختبار
    1229، ويُحكم بالقواعد الجديدة. كيانات النقاط لا يحفظها الملف فهي مفترضة هنا من نص كل نقطة."""
    import json

    from src import important, important_issue

    cfg = load_config()
    from tests.helpers import IMPORTANT_FIXTURES
    fx = json.loads((IMPORTANT_FIXTURES / "1278.json").read_text(encoding="utf-8"))
    entities = {
        "5869367b9c74": ["وزارة الخارجية الأميركية"], "8e645204c867": ["حزب الله", "ترمب"],
        "80943d3f4957": ["حزب الله", "لبنان"], "23c484b9a35a": ["حزب الله", "العقوبات"],
        "ead62e9067e0": ["روسيا", "الغاز"], "90ff3a888844": ["روسيا", "الغاز"],
        "24246e81cd44": ["روسيا", "أوكرانيا"], "bd4e7be00831": ["الحوثي", "روسيا"]}
    check("(1278) fixture: ثماني نقاط بمعرّفاتها الحقيقية",
          [p["id"] for p in fx["points"]] == list(entities), [p["id"] for p in fx["points"]])

    rules: dict[str, dict] = {}     # نص النقطة ← {ناشر: (موقف، مقتطف، same_event)}
    docs_by_marker, rig_points = {}, []
    for i, p in enumerate(fx["points"]):
        marker, ents = f"نقطة1278{i}", entities[p["id"]]
        by_pub = {e["publisher"]: e for e in p["evidence"]}
        docs, stance = [], {}
        for d in p["read_docs"]:
            if d["stance"] == "deduped":
                continue
            ev = by_pub.get(d["publisher"])
            text = ev["excerpt"] if ev else f"{d['publisher']}: تقرير يتناول {ents[-1]} وسياق الخبر."
            if p["id"] == "8e645204c867" and d["publisher"] == "Lebanon 24":
                # عنوان مقال Lebanon 24 الذي قرأته هذه النقطة (كما في وصف الحادثة)
                text += " عنوان المقال: سنواصل خنق مصادر تمويل حزب الله بالعقوبات"
            docs.append(important_doc(d["publisher"], text, link=d["link"]))
            stance[d["publisher"]] = (d["stance"], ev["excerpt"] if ev else "", d["same_event"] is not False)
        rules[p["claim"]] = stance
        docs_by_marker[marker] = docs
        rig_points.append({"claim": p["claim"], "entities": [marker, *ents],
                           "queries": [{"lang": "ar", "q": f"{marker} {p['claim']}"}]})

    lebanon_title = "سنواصل خنق مصادر تمويل حزب الله بالعقوبات"

    def classify(point, names):
        rows = []
        for n in names:
            kind, excerpt, same = rules[point].get(n, ("irrelevant", "", False))
            if point.startswith("الولايات المتحدة ستواصل خنق") and n == "Lebanon 24":
                # النقطة 23c4 تقرأ مقال Lebanon 24 المقروء في نقطة أخرى فتجده يؤيدها
                kind, excerpt, same = "supports", lebanon_title, True
            rows.append(important_stance(n, kind, excerpt, same_event=same, verdict_label=""))
        return {"sources": rows}

    with ImportantRig(rig_points, docs_by_marker, classify, strict_known=True):
        result = important.judge("نص #1278", 98278, cfg)
    by_id = {p["id"]: p for p in result["points"]}

    def kind(pid):
        return (by_id[pid].get("nearest") or {}).get("kind")

    # #1288 (مصادرنا وحدها): كل مؤيِّدي هاتين النقطتين من خارج مصادرنا (إرم نيوز وLebanon 24 وLBCIV7…) فتُستبعد؛
    # القديم confirmed بتنبيه، الجديد ليست confirmed (لا تؤيدها وثيقة من مصادرنا)
    # #1345: LBCIV7 (lbcgroup.tv) صارت من مصادرنا فتثبت 8e645204c867 بها، ويبقى استبعاد إرم نيوز وLebanon 24 (outside_docs).
    # 80943d3f4957 لا تؤيدها LBCIV7 في هذا الشاهد (موقفها غير مؤيِّد) فتبقى ليست confirmed كما كانت
    check("(1278) 8e645204c867 ← confirmed (مؤيِّدها LBCIV7 وسيلة لبنانية من مصادرنا) مع استبعاد الخارجية",
          by_id["8e645204c867"]["verdict"] == "confirmed" and by_id["8e645204c867"]["outside_docs"] > 0,
          (by_id["8e645204c867"]["verdict"], by_id["8e645204c867"].get("outside_docs")))
    check("(1278) 80943d3f4957 ← ليست confirmed (مؤيِّدوها من خارج مصادرنا مستبعدون)",
          by_id["80943d3f4957"]["verdict"] != "confirmed" and by_id["80943d3f4957"]["outside_docs"] > 0,
          (by_id["80943d3f4957"]["verdict"], by_id["80943d3f4957"].get("outside_docs")))
    # القديم not_found بـsingle_source للنقطتين؛ الجديد: 24246e81cd44 ← confirmed بمصدر واحد (BBC؛ Youm7 مستبعدة)،
    # وbd4e7be00831 ← not_found تسقط بلا أثر (ناشروها كلهم خارج مصادرنا)
    p24 = by_id["24246e81cd44"]
    check("(1278) 24246e81cd44 ← confirmed وsupport_level == single (BBC تبقى وYoum7 تُستبعد)",
          p24["verdict"] == "confirmed" and p24["support_level"] == "single"
          and p24["support_publisher"] == "BBC" and p24["outside_docs"] >= 1,
          (p24["verdict"], p24.get("support_level"), p24.get("support_publisher")))
    pbd = by_id["bd4e7be00831"]
    check("(1278) bd4e7be00831 ← not_found تسقط بلا أثر (كل ناشريها خارج مصادرنا)",
          pbd["verdict"] == "not_found" and pbd.get("nearest") is None and bool(pbd["dropped_reason"]),
          (pbd["verdict"], pbd.get("nearest"), pbd["dropped_reason"]))
    for pid in ("ead62e9067e0", "90ff3a888844", "23c484b9a35a"):
        p = by_id[pid]
        check(f"(1278) {pid} لا تسقط إلا بالدرجة (هـ) (لا nearest ولا مصدر)",
              (p["dropped_reason"] is None and p["verdict"] != "not_found" or bool(p.get("nearest")))
              or (p["dropped_reason"] == important.NO_TRACE_REASON and p.get("nearest") is None),
              (p["verdict"], p["dropped_reason"], p.get("nearest")))
    # القديم: تقرأ مقال Lebanon 24 من المخزون المشترك فتصير single_source؛ الجديد: Lebanon 24 خارج مصادرنا
    # فلا تدخل المخزون المشترك ولا pool أصلًا، فتسقط
    p23 = by_id["23c484b9a35a"]
    check("(1278) 23c484b9a35a لا تقرأ Lebanon 24 (خارج مصادرنا) فتسقط",
          p23["verdict"] == "not_found" and "Lebanon 24" not in (p23.get("shared_from") or [])
          and bool(p23["dropped_reason"]), (p23["verdict"], p23.get("shared_from")))
    check("(1278) الملف المحفوظ يحمل rules_version الحالية",
          result["rules_version"] == cfg.path("important.rules_version") == 7, result.get("rules_version"))

    # القديم: build_selection_body · الجديد: build_points_body — بعد #1293 يعرض build_selection_body ثلاثة
    # منشورات (g88)؛ أقسام الأحكام وأسطر النسبة لكل نقطة تخصّ قضية النقاط القديمة التي تبقى تُقرأ وتُكتب
    body = important_issue.build_points_body(result, cfg)
    check("(1278) قضية الترشيح فيها القسمان «✅ ما ثبت» و«🔍 ما لم يُحسم»",
          "## ✅ ما ثبت" in body and "## 🔍 ما لم يُحسم — أقرب ما وُجد" in body
          and body.index("## ✅ ما ثبت") < body.index("## 🔍 ما لم يُحسم — أقرب ما وُجد"), body[:600])
    check("(1278) وسطر «✅ من مصادرنا: BBC (مصدر واحد — يُنسب إليه)» وسطر الاستبعاد «🚫 استُبعدت»",
          "✅ من مصادرنا: BBC (مصدر واحد — يُنسب إليه)" in body and "🚫 استُبعدت" in body
          and "من خارج مصادرنا المسجّلة" not in body, None)
    # تعليمات الكاتب (#1288): 24246e81cd44 صارت confirmed بمصدر واحد ← تُلحَق confirmed_single («بحسب BBC»)؛
    # كانت not_found_single_claim (القديم)
    from src import important_write
    ins24 = important_write.instructions(by_id["24246e81cd44"], cfg)
    check("(1278) تعليمات 24246e81cd44 تنسب إلى BBC وحدها («بحسب BBC»)",
          "بحسب BBC" in ins24 and "أوردها BBC وحده" in ins24, ins24)
    other = {"verdict": "not_found", "claim": "ادّعاء آخر", "text": "ادّعاء آخر",
             "nearest": {"kind": "single_source", "title": "حدث قريب مختلف",
                         "sources": [{"publisher": "الصحيفة", "link": "u", "excerpt": "نص"}]}}
    ins_c = important_write.instructions(other, cfg)
    check("(1278) حالة (ج) بعنوان غير نص النقطة تبقى بتعليمات not_found_single",
          "ممنوع ذكر النقطة الأصلية" in ins_c and "بحسب الصحيفة" in ins_c, ins_c)
    print("نتائج أنبوب #1278 (الحكم · درجة أقرب ما وُجد):")
    for p in result["points"]:
        n = p.get("nearest") or {}
        print(f"  {p['id']} · {p['verdict']} · {n.get('kind') or ('سقطت (هـ)' if p['dropped_reason'] else '-')}"
              f" · shared_from={p.get('shared_from')}")
