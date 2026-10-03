"""مسار «هام» — الحَكَم على النقاط (Issue #1194، المهمة 1 من 3).

كل اختبار هنا يجري على مخرَج الأنبوب كاملًا: نص Issue ← important.judge ←
الملف المحفوظ في state/important، ببحث وجلب ونموذج مزيَّفة (ImportantRig في
tests/helpers.py). حالات الحارس g1–g6 في tests/test_guards_golden.py."""
from __future__ import annotations

import re

from tests.helpers import (check, load_config, ImportantRig, important_doc,
                           important_point, important_stance)


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
          mc["total"] == len(rig.calls) == 4 and sum(mc["by_point"].values()) == 4, (mc, rig.calls))
    check("(f) نداء تصنيف واحد لكل نقطة وفي كل نقطة حقل model_calls",
          all(p["model_calls"] == 1 for p in saved["points"])
          and set(mc["by_point"]) == set(ids1.values()), mc)
    mc_c = important.load_saved(95002)["model_calls"]
    check("(f) نقطة بلا وثائق لا نداء لها (صفر مصادر ≠ نفي)",
          mc_c["total"] == 2 and mc_c["by_point"][important.point_id(q_empty["text"])] == 0, mc_c)

    # ── نقاط الآراء والأسئلة تُتجاهل، والنقاط المتكررة تُحكم مرة واحدة ──
    opinion = important_point("عنبة", "أرى أن القرار خاطئ بشأن عنبة", kind="رأي")
    with ImportantRig([p_conf, opinion, dict(p_conf)], docs, classify) as rig2:
        important.judge(_body(4), 95005, cfg)
    s5 = important.load_saved(95005)
    check("الآراء تُتجاهل والنص المكرر يُحكم مرة واحدة",
          len(s5["points"]) == 1 and len(rig2.calls) == 1, (len(s5["points"]), rig2.calls))

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
