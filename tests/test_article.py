"""اختبارات مجال «المقال والتحقق» — تجزّأت من tests/test_pipeline.py (Issue #883): التحقق من مقال ملصق (verify.py)، صياغة مسودة من المؤكَّد وحده (verify_draft.py)، فحص الأصالة (check_originality)، محرك البحث والقراءة المشترك (evidence.py)، ومقال من المصادر (article.py) بمراحله (استخلاص الموجز، تسمية الحدث، التأصيل، درجات الوثوق، ومنشور «تحقيق»). المساعدات المشتركة (check، الفاكات، install_fakes) في tests/helpers.py."""
from __future__ import annotations

import inspect
import json
import os
import shutil
from datetime import datetime, timedelta, timezone

from tests.helpers import (
    check,
    tick_marker,
    evidence,
    extract,
    headlines,
    review,
    sources,
    store,
    writer,
    DRAFTS_DIR,
    load_config,
    cluster,
    rank,
    Article,
)


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
    # verify_draft لم تعد تستورد find_images ولا تبني بطاقة إطلاقًا
    # (Issue #852) -- البطاقة تُبنى عند الاعتماد فقط، لا هنا.

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
        # بلا "image" (Issue #852) -- البطاقة تُبنى عند الاعتماد لا هنا.
        check("3) نفس مخطط drafts/ (id/arabic/caption/source) بلا نقص",
              {"id", "arabic", "caption", "source"} <= set(saved.keys()))
        check("3) بلا حقل image عند الصياغة (Issue #852)", "image" not in saved)
        check("3) verify_draft.py يحفظ headlines/headline_selected (Issue #756)",
              isinstance(saved.get("headlines"), list) and len(saved["headlines"]) == 3
              and saved.get("headline_selected") == 0, saved.get("headlines"))
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

    # حقل المنشأ لا يمنح أي امتياز في المراجعة: parse_approved يعمل على
    # المعرّف والمربعات فقط بصرف النظر عن وجوده (نقطة 5 من الموافقة)
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

def test_check_originality_grounded() -> None:
    """الإعفاء الرابع (Issue #865، شاهد تشغيلة مضيق هرمز): المقال يُبنى
    إلزامًا على وقائع مسندة أُعطيت للكاتب حرفيًا في مدخل الصياغة
    (`article._facts_block`) — فتتابع من هذه الوقائع نفسها (لا صياغة
    اختيارية، مثل منصب رسمي باسم صاحبه) لا يجوز أن يُرفض بوصفه نسخًا عن
    المصدر الذي استُخرجت منه. `grounded_texts` معامل اختياري جديد في
    `_check_originality_full` وحدها — `check_originality` العامة (3-tuple)
    تبقى بلا تغيير سلوكي حين لا يُمرَّر."""
    from src import verify_draft

    # الشاهد الحرفي المُبلَّغ بالضبط: سبع كلمات، منصب رسمي باسم صاحبه، لا
    # صياغة بديلة له
    run = "أعلن أمين المجلس الأعلى للأمن القومي الإيراني"
    draft = f"{run} تصريحات مهمة اليوم بشأن مضيق هرمز."
    single_source = [{"name": "وكالة إيرانية",
                      "text": f"وذكرت وكالة الأنباء أن {run} في تصريح رسمي اليوم.",
                      "link": "https://ir-agency/1"}]
    grounded_texts = [
        f"{run} محسن رضائي أن إيران ستقيم منطقة محظورة في مضيق هرمز.",
    ]

    ok_g, reason_g, notes_g, offending_g = verify_draft._check_originality_full(
        draft, "", single_source, 7, grounded_texts=grounded_texts)
    check("تتابع مخالف وارد بالكامل في واقعة مسندة مُمرَّرة ⇒ يُعفى والمقال يمرّ "
          "(شاهد مضيق هرمز الحرفي)",
          ok_g is True and offending_g is None, (ok_g, reason_g))
    check("الإعفاء الرابع مُسجَّل صراحة في notes — لا إسقاط صامت",
          bool(notes_g) and "واقعة مسندة" in notes_g[0] and "الإعفاء الرابع" in notes_g[0],
          notes_g)

    # نفس التتابع تمامًا بلا تمرير grounded_texts ⇒ يُرفض كما اليوم (لا
    # تكرار داخل نفس المصدر، ولا وثيقة أخرى، ولا نواة تقليم/كمية/ربط تسمية)
    ok_no_g, reason_no_g, notes_no_g = verify_draft.check_originality(
        draft, "", single_source, 7)
    check("نفس التتابع بلا تمرير grounded_texts ⇒ يُرفض كما اليوم — بلا تغيير "
          "سلوكي في المعامل الاختياري الغائب",
          ok_no_g is False and notes_no_g == [], (ok_no_g, reason_no_g))

    # تتابع من وثيقة مصدر غير وارد في أي واقعة مسندة يبقى رفضًا رغم تمرير
    # grounded_texts (مقيَّد بالوقائع المسندة فعلًا — لا إعفاء عام لكل نص مصدر)
    unrelated_grounded = ["نص واقعة مسندة أخرى لا صلة له بالتتابع المرفوض إطلاقًا."]
    ok_unrelated, reason_unrelated, notes_unrelated, _off = verify_draft._check_originality_full(
        draft, "", single_source, 7, grounded_texts=unrelated_grounded)
    check("تتابع من وثيقة مصدر غير وارد في أي واقعة مسندة ⇒ يُرفض رغم تمرير "
          "grounded_texts (الإعفاء مقيَّد بالوقائع المسندة نفسها لا كل نص)",
          ok_unrelated is False and notes_unrelated == [], (ok_unrelated, reason_unrelated))

    # ضابط: الإعفاء لا يمسّ فرع تطابق المقال الملصق (article_body) — تتابع
    # وارد في الموجز الملصق يبقى مرفوضًا حتى مع grounded_texts تحمله، لأن
    # هذا الفرع فحص مختلف كليًا (القاعدة 1: لا نقل حرفي عن المقال الملصق)
    ok_brief, reason_brief, _notes_brief, offending_brief = verify_draft._check_originality_full(
        draft, f"نُشر أن {run} في وكالات الأنباء.", [], 7, grounded_texts=grounded_texts)
    check("الإعفاء الرابع لا يمسّ فرع تطابق المقال الملصق — يبقى رفضًا كما كان",
          ok_brief is False and offending_brief is not None and
          offending_brief["match_kind"] == "brief", (ok_brief, reason_brief))

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

    # ── مقتطف بدل إسقاط كلي لمرشّح فشل جلبه رغم نجاح غيره (Issue #895) ──
    # الشاهد: Bloomberg/Reuters/Investing.com/The Arab Weekly ٤٠٣/٤٠١ متكرر
    # — العلاج القديم (demoted_readers) يؤخّرها في ترتيب القراءة فقط، ولا
    # يمنع إسقاطها كليًا حين يفشل جلبها فعليًا رغم الأولوية. الآن: تُحفَظ
    # كمقتطف (عنوان+ملخص) بعلامة snippet_only صريحة بدل الاختفاء التام.
    mixed_articles = [
        Article(title="Bloomberg report on the story", link="https://bloomberg.example/1",
               summary="Bloomberg's own summary of the event", source_name="Bloomberg",
               region="global", weight=1.0, published=datetime.now(timezone.utc),
               publisher="Bloomberg"),
        Article(title="AP confirms the story", link="https://ap.example/1",
               summary="AP full account", source_name="AP", region="global", weight=1.0,
               published=datetime.now(timezone.utc), publisher="AP"),
    ]
    real_extract_gather2 = extract.gather
    extract.gather = lambda members, limit=2: (
        [{"name": "AP", "text": "نص AP الكامل المقروء فعليًا"}],
        [{"name": "Bloomberg", "link": "https://bloomberg.example/1", "reason": "HTTP 403"}])
    docs_mix, basis_mix = evidence.gather_evidence(mixed_articles, cfg)
    extract.gather = real_extract_gather2
    by_name_mix = {d["name"]: d for d in docs_mix}
    check("evidence.gather_evidence: مرشّح فشل جلبه رغم نجاح غيره لا يُسقَط "
          "كليًا — يبقى في docs كمقتطف",
          "Bloomberg" in by_name_mix, docs_mix)
    check("evidence.gather_evidence: المقتطف مُعلَّم snippet_only=True صراحة",
          by_name_mix.get("Bloomberg", {}).get("snippet_only") is True, by_name_mix)
    check("evidence.gather_evidence: المقتطف from_text=False (لا نص كامل فعليًا)",
          by_name_mix.get("Bloomberg", {}).get("from_text") is False, by_name_mix)
    check("evidence.gather_evidence: نص المقتطف مبني من عنوان/ملخص المقالة الفعليَّين",
          "Bloomberg report on the story" in by_name_mix.get("Bloomberg", {}).get("text", ""),
          by_name_mix)
    check("evidence.gather_evidence: المرشّح الناجح يبقى نصًّا كاملًا snippet_only=False",
          by_name_mix.get("AP", {}).get("from_text") is True and
          by_name_mix.get("AP", {}).get("snippet_only") is False, by_name_mix)
    check("evidence.gather_evidence: الأساس يبقى «نص كامل» طالما نجح مرشّح واحد فأكثر",
          basis_mix == evidence.EVIDENCE_FULL_TEXT)
    check("evidence.gather_evidence: fetch_failures التشخيصية تبقى محفوظة كالمعتاد",
          getattr(docs_mix, "fetch_failures", None) ==
          [{"name": "Bloomberg", "link": "https://bloomberg.example/1", "reason": "HTTP 403"}])

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

    # ── القاعدة 1: كل واقعة مسندة — بلا أي سند (Issue #835: مصدر واحد لم
    # يعد يُسقِط — درجة ب، انظر اختبار الدرجات الثلاث المخصَّص) تسقط ──
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار القاعدة 1",
        "statements": [
            {"text": "واقعة بلا أي مصدر", "kind": "واقعة", "entities": ["ك1"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": "واقعة بمصدرين مستقلين", "kind": "واقعة", "entities": ["ك2"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": "واقعة بثلاثة مصادر", "kind": "واقعة", "entities": ["ك3"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    SUPPORT_MAP.clear()
    SUPPORT_MAP["واقعة بلا أي مصدر"] = []
    SUPPORT_MAP["واقعة بمصدرين مستقلين"] = ["مصدر أول", "مصدر ثانٍ"]
    SUPPORT_MAP["واقعة بثلاثة مصادر"] = ["مصدر أول", "مصدر ثانٍ", "مصدر ثالث"]

    out1 = article._write_article("موجز اختبار القاعدة 1", 1, cfg)
    check("1) واقعة بلا أي مصدر تسقط ولا تدخل المقال — حتى لو وردت في الموجز",
          any(d["text"] == "واقعة بلا أي مصدر" for d in out1["dropped"]))
    check("1) سبب السقوط يذكر السند غير الكافي صراحة (لا فشل صامت)",
          any("سند غير كافٍ" in d["reason"] for d in out1["dropped"]
              if d["text"] == "واقعة بلا أي مصدر"))
    check("1) واقعتان مسندتان بمصدرين فأكثر تكفيان لإنتاج المقال",
          out1["produced"] is True, out1["reason"])
    check("1) الواقعة الساقطة غير موجودة ضمن ما مرّ لاختيار السؤال",
          "واقعة بلا أي مصدر" not in seen_question_calls[-1])
    # خط الأساس الثابت (تشخيص Issue #373، الجولة الرابعة، البند 3) يحتاج
    # عدد الوقائع المسندة كعدد صريح على outcome — لا استخراجه من نص حر
    check("1) outcome['grounded_count'] يساوي عدد الوقائع التي اجتازت السند فعلًا "
          "(2 من 3: واحدة سقطت لانعدام سند)",
          out1["grounded_count"] == 2, out1["grounded_count"])

    # ── القاعدة 7 (أُلغيت، Issue #814 جزء 1): واقعة مسندة واحدة فقط لم تعد
    # تمتنع عن المقال -- الشرط الوحيد الباقي عددي محض (لا واقعة واحدة مسندة
    # إطلاقًا)، ومصدران مستقلان لواقعة واحدة كافيان الآن لإنتاج مقال ──
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار إلغاء القاعدة 7",
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
    out7 = article._write_article("موجز اختبار إلغاء القاعدة 7", 7, cfg)
    check("7) واقعة مسندة واحدة فقط تكفي الآن لإنتاج مقال — القاعدة 7 (الحدّ "
          "الأدنى العددي) أُلغيت",
          out7["produced"] is True, out7["reason"])
    check("7) سبب الإنتاج لا يذكر «القاعدة 7» — البوابة العددية القديمة زالت",
          "القاعدة 7" not in out7["reason"], out7["reason"])
    check("7) grounded_count يساوي 1 -- واقعة واحدة مسندة بمصدرين مستقلين",
          out7["grounded_count"] == 1, out7["grounded_count"])
    check("7) واقعة مسندة واحدة كافية لاختيار سؤال منها -- نداء اختيار السؤال "
          "وقع فعلًا (لا امتناع قبله)",
          len(seen_question_calls) == question_calls_before + 1)
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
          "لا صوت ثالث" in article.DRAFT_SYSTEM_TEMPLATE.format(
              opinion_phrase="x", editor_tag_phrase="y"))
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
          article.DRAFT_SYSTEM_TEMPLATE.format(opinion_phrase="x", editor_tag_phrase="y"))

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
    # البطاقة لم تعد تُبنى عند الصياغة (Issue #852) -- لا "used_original"
    # بعد الآن، فالإشارة الصحيحة هنا أن مرشَّحين فعليين وصلا التقرير (لا
    # [] فارغ يُسقط كل الصور بصرف النظر عمّا هو متاح، جوهر هذا الاختبار).
    check("دورة السند الثانية: تقرير الصورة يسجّل مرشَّحين فعليين من الدمج",
          out_support.get("image_report", {}).get("total_candidates", 0) >= 2,
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
    check("6) إجابة سؤال مرجعي مسندة تدخل grounded فعلًا مع واقعة إخبارية غير "
          "مرجعية واحدة — كلتاهما تكفي (بوابة البند 6 القديمة لم تعد تُشترَط)",
          out56["produced"] is True, out56.get("reason"))

    # ── البند 6 (بوابة «كل الوقائع مرجعية» أُلغيت، Issue #814 جزء 1): وقائع
    # مسندة كلها مرجعية (خلفية) لم تعد تمنع المقال — واقعة مسندة واحدة على
    # الأقل (مرجعية أو لا) كافية الآن ──
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
    check("6) وقائع مسندة كلها مرجعية (خلفية موثَّقة سلفًا) لم تعد تمنع المقال "
          "— القاعدة 7 القديمة (شرط واقعة غير مرجعية) أُلغيت",
          out_refonly["produced"] is True, out_refonly.get("reason"))

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

    # ── normalize_statement/query_latin: تجريد الرقم برمجيًا (Issue #832،
    # العطل الأول) — البرومبت وحده لا يكفي، النموذج قد يُدرج الرقم موضع
    # التحقق رغم التعليمات ──
    check("_sanitize_query_latin: رمز يحوي رقمًا (لا سنة) يُجرَّد ويبقى الحقل "
          "صالحًا (كلمتان فأكثر متبقيتان)",
          article._sanitize_query_latin("Vestel debt 105 billion lira") ==
          "Vestel debt billion lira")
    check("_sanitize_query_latin: سنة من أربع خانات (2025) تبقى بلا تجريد",
          article._sanitize_query_latin("Vestel results Q1 2025") ==
          "Vestel results 2025")
    check("_sanitize_query_latin: التجريد يُفرغ الحقل إلى أقل من كلمتين ⇒ "
          "يُهمَل كليًا (فارغ)",
          article._sanitize_query_latin("Vestel 105") == "")
    check("_sanitize_query_latin: نص بلا أرقام يمر بلا تغيير",
          article._sanitize_query_latin("Vestel debt burden lira") ==
          "Vestel debt burden lira")

    num_stmt = article.normalize_statement({
        "text": "تجاوزت ديون فيستل 105 مليارات ليرة", "kind": "واقعة",
        "entities": ["فيستل", "105 مليارات ليرة"], "is_unnamed_event": False,
        "is_reference": False, "query_latin": "Vestel debt 105 billion lira",
    })
    check("normalize_statement: query_latin المُستلَم يُجرَّد من الرقم قبل التخزين",
          num_stmt["query_latin"] == "Vestel debt billion lira", num_stmt)

    empty_stmt = article.normalize_statement({
        "text": "تجاوزت ديون فيستل 105 مليارات ليرة", "kind": "واقعة",
        "entities": ["فيستل"], "is_unnamed_event": False, "is_reference": False,
        "query_latin": "Vestel 105",
    })
    check("normalize_statement: query_latin يصير كلمة واحدة بعد التجريد ⇒ "
          "يُخزَّن فارغًا (كأنه غاب أصلًا)",
          empty_stmt["query_latin"] == "", empty_stmt)

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
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images

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
        # الواقعة العادية تسقط عمدًا (لا سند) — لا تؤثر على إنتاج المقال بعد
        # إلغاء القاعدة 7 (Issue #814 جزء 1): التصريح المسنَد وحده يكفي الآن،
        # فمرحلتا السؤال/الصياغة تقعان فعلًا وتُزيَّفان أدناه
        return []

    article._support_statement_parts = _fake_support_parts
    article._support_sources = _fake_support_plain
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار تصريح؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": f"{statement_text}.", "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []

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
    check("تصريح: واقعة مسندة واحدة (التصريح) تكفي لإنتاج المقال — القاعدة 7 "
          "القديمة (حدّ أدنى عددي) أُلغيت",
          out["produced"] is True, out["reason"])
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
    article._choose_question = real_choose_question
    article._draft_article = real_draft_article
    article.find_images = real_find_images

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
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images

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
    # القاعدة 7 أُلغيت (Issue #814 جزء 1): التصريح المسنَد وحده يكفي الآن
    # لإتمام المسار كاملًا -- تُزيَّف مرحلتا الصياغة والصورة فقط لإتمام
    # التشغيلة بلا نداء شبكة/نموذج حقيقي، بلا صلة بما يفحصه هذا الاختبار
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار فجوة دمج؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": f"{shrunk_text}.", "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []

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
    article._choose_question = real_choose_question
    article._draft_article = real_draft_article
    article.find_images = real_find_images

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
    # الأجزاء المرقَّمة نص متغيّر — في الكتلة الثانية بلا تخزين، لا الأولى
    # (طلب المراجعة: كتلة الوثائق الثابتة وحدها تحمل cache_control)
    variable_block_text = captured[0]["messages"][0]["content"][1]["text"]
    check("_support_statement_parts: يرقّم الأجزاء في نص الطلب (1. ... 2. ...)",
          "1. جزء أول" in variable_block_text and
          "2. جزء ثانٍ" in variable_block_text)
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
    _majority_loaded = store.load_draft(out["draft_id"]) if out.get("draft_id") else None
    check("article.py يحفظ headlines/headline_selected (Issue #756)",
          _majority_loaded is not None
          and isinstance(_majority_loaded[1].get("headlines"), list)
          and len(_majority_loaded[1]["headlines"]) == 3
          and _majority_loaded[1].get("headline_selected") == 0,
          _majority_loaded[1].get("headlines") if _majority_loaded else None)

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
        # الاختبار المجاور (test_article_statement_kind) لنفس السبب. سند
        # غير كافٍ دومًا يُصعِّد السُلَّم عبر محاولتيه الاثنتين (Issue #808،
        # البند 3) — استدعاءان لكل جزء إذن، لا واحد كسابقًا
        return []

    article._support_sources = _fake_support_split
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images
    # الضمان (Issue #835، البند 2): كلا الجزأين يسقط بلا سند فعليًا، فتنشط
    # آلية الضمان (fallback_to_brief) وتُصاغ مسودة من الموجز نفسه — بلا صلة
    # بما يفحصه هذا الاختبار (سلوك الفصل/السند المستقل لكل جزء)؛ تُزيَّف
    # مراحل الصياغة/الصورة فقط لإتمام التشغيلة بلا نداء شبكة حقيقي
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار؟", "")
    article._draft_article = (
        lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
            {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
             "image_headline": "عنوان", "post_title": question,
             "post_body": "متن اختبار فصل الواقعة بحسب معلومات المحرر.",
             "hashtags": ["اختبار"]}, ""))
    article.find_images = lambda title, cfg, terms=None: []

    try:
        out = article._write_article("موجز اختبار فصل واقعة مركّبة", 9002, cfg)
    finally:
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images

    check("فصل الواقعة: كلا الجزأين مرّ بحلقة السند مستقلًا (استدعاءا محاولتَي "
          "السُلَّم لكلٍّ منفصلان — لا استدعاءات متداخلة بين الجزأين)",
          support_calls.count(part_a) == 2 and support_calls.count(part_b) == 2 and
          len(support_calls) == 4,
          support_calls)
    # كلا الجزأين سقط لانعدام سند فعليًا (سقوط أحدهما لا يُسقط الآخر معه) —
    # لكن Issue #835 (الضمان، البند 2) يعيدهما درجة ج بدل أن يُبقيا في
    # dropped: المقال صيغ منهما مباشرة (fallback_to_brief)، فلا يظهران في
    # "ما سقط من موجزي" (مُزالان من dropped عمدًا — البند 3) بل في fact_grades
    check("فصل الواقعة: كلا الجزأين لم يجتز السند فعليًا فانتقل درجة ج — الضمان "
          "صاغ المقال منهما (fallback_to_brief)",
          out["fallback_to_brief"] is True, out)
    fact_texts = [g["text"] for g in out.get("fact_grades", [])]
    check("فصل الواقعة: كلا الجزأين دخل المقال درجة ج (لا dropped) بعد سقوط سنده",
          part_a in fact_texts and part_b in fact_texts and
          all(g["grade"] == "C" for g in out["fact_grades"]
              if g["text"] in (part_a, part_b)),
          out["fact_grades"])
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
    # كياناتها، لا تُنزَع)، وواقعة ثانية مستقلة (تثبت أن الفصل يتعامل مع
    # واقعتين مستقلتين بلا عطل — لا لبلوغ أي حدّ أدنى عددي، القاعدة 7
    # القديمة أُلغيت، Issue #814 جزء 1)، وبلا أي عنصر statements للجملة
    # الوصفية البحتة (1500 موظف/16 ألف قدم/ريالتي لابز في كورك) — لأنها
    # استُبعدت في مرحلة الاستخراج نفسها، لا لأن كودًا لاحقًا صفّاها. الشاهد:
    # لا استعلام بحث يحمل أيًّا من ألفاظها ──
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
    check("القلعة: outcome['produced'] نجح — واقعتان حدثيتان مسندتان بلا أي حاجة "
          "لتفاصيل وصفية إضافية (لا حدّ أدنى عددي بعد إلغاء القاعدة 7)",
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
    real_support_parts = article._support_statement_parts
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images

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
    # وثائق غير فارغة إلزامًا هنا (خلافًا لبقية هذا الاختبار): سُلَّم البحث
    # يُصعِّد عند انعدام السند (Issue #808) لا يتوقف عند أول نتيجة خام
    # وحدها — docs فارغة كانت تمنع _support_statement_parts من النداء
    # إطلاقًا فيُصعَّد السُلَّم دومًا رغم عدم وجود ما يمنع النجاح فعليًا،
    # فيكسر افتراض "استعلام واحد فقط" الذي يفحصه هذا الاختبار تحديدًا
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"},
         {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1"}],
        evidence.EVIDENCE_FULL_TEXT)
    article._support_statement_parts = lambda merged, docs, cfg: (
        [["مصدر أول", "مصدر ثانٍ"] for _ in merged])
    # القاعدة 7 أُلغيت (Issue #814 جزء 1): التصريح المسنَد وحده يكفي الآن
    # لإتمام المسار كاملًا -- تُزيَّف مرحلتا الصياغة والصورة فقط لإتمام
    # التشغيلة بلا نداء شبكة/نموذج حقيقي، بلا صلة بما يفحصه هذا الاختبار
    # (عدد/محتوى استعلام البحث، محسوب أعلاه في مرحلة السند لا بعدها)
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار الاسم؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختبار الاسم الإلزامي.", "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []

    try:
        article._write_article("موجز اختبار الاسم الإلزامي", 9006, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article._support_statement_parts = real_support_parts
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images

    check("اسم المتحدث الإلزامي: استعلام واحد بُني فعليًا لعنصر «تصريح» — "
          "السند كافٍ من المحاولة الأولى فلا يُصعَّد السُلَّم",
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
    # بلا سند إطلاقًا هنا (docs فارغة عمدًا) — الضمان (Issue #835، البند 2)
    # يصوغ مسودة من الموجز نفسه (fallback_to_brief)؛ لا صلة بما يفحصه هذا
    # الجزء (بناء الاستعلام قبل أي حكم على السند) — تُزيَّف مراحل
    # الصياغة/الصورة فقط لإتمام التشغيلة بلا نداء شبكة حقيقي
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار الناشر؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختبار الاسم الإلزامي بحسب تقرير نشرته Daily Sabah.",
         "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []
    try:
        article._write_article("موجز اختبار الاسم الإلزامي — تقرير منقول", 9007, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images

    built_report_query = search_queries[0] if search_queries else ""
    check("اسم الناشر الإلزامي (تقرير منقول): يتصدَّر الاستعلام",
          built_report_query.split()[:2] == ["Daily", "Sabah"], built_report_query)

def test_article_search_ladder() -> None:
    """سُلَّم ثلاث محاولات بحث لكل واقعة عادية (Issue #803، مُعدَّل بـIssue
    #808). الشاهد الأصلي (#803): موجز عن شركة «فيستل» التركية أنتج استعلامات
    كيانات-رقمية-بحتة («فيستل 48»، «فيستل 105 مليارات ليرة») فقدت كل كلمة
    معنى من نص الواقعة، فرجعت ست وقائع من سبع صفر نتائج بلا أي محاولة ثانية.
    الشاهد الثاني (#808): محاولة ثالثة باسم الكيان اللاتيني المجرَّد
    («Vestel» وحده) رجعت 117 نتيجة حقيقية غير فارغة — لكن عن بيع حصة في
    شركة «توغ»، لا صلة لها بموجز الديون — فأوقفت السُلَّم عند أول نتيجة خام
    دون فحص سندها إطلاقًا. العلاج: (أ) query_latin عبارة بحث جاهزة من ٣-٦
    كلمات بدل اسم الكيان المجرَّد، (ب) رفض أي محاولة أقل من كلمتين بنيويًا،
    (ج) التصعيد للمحاولة التالية عند انعدام السند لا عند صفر النتائج وحده."""
    from src import article

    cfg = load_config()
    cfg["article"]["source_extract_enabled"] = False

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images

    evidence.gather_evidence = lambda articles, cfg, claim_text="": ([], evidence.EVIDENCE_NO_RESULTS)
    article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
        is_report=False, publisher="": []
    # القاعدة 7 أُلغيت (Issue #814 جزء 1): سيناريوهَي ٢ و٤ أدناه يُسنَدان
    # فعليًا (مصدران مستقلان)، فيكفي ذلك الآن لإتمام المسار كاملًا -- تُزيَّف
    # مرحلتا الصياغة والصورة هنا لإتمام أي تشغيلة تصل هذه المرحلة بلا نداء
    # شبكة/نموذج حقيقي، بلا صلة بما يفحصه هذا الاختبار (بناء استعلامات السُلَّم)
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار سُلَّم البحث؟", "")
    # العبارة الثابتة (Issue #835، البند 2) مضمَّنة هنا: بعض سيناريوهات هذا
    # الاختبار موجز بواقعة وحيدة تسقط سندها كليًا فينشط الضمان
    # (fallback_to_brief) — بلا العبارة يفشل فرض النسبة فتُسقَط الواقعة مرة
    # ثانية عبر آلية مختلفة (attribution_retry)، فيصبح المقال بلا مادة رغم
    # أن هذا الاختبار لا يفحص شيئًا من هذا القبيل أصلًا
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختبار سُلَّم البحث بحسب معلومات المحرر.", "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []

    def _brief(statements: list) -> None:
        article.extract_brief = lambda body, cfg, retries=3: ({
            "topic": "اختبار سُلَّم البحث", "statements": statements, "questions": [],
        }, None)

    def _stmt(text: str, entities: list, query_latin: str = "") -> dict:
        return {"text": text, "kind": "واقعة", "entities": entities,
                "is_unnamed_event": False, "is_reference": False,
                "query_latin": query_latin}

    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        # ── ١) query_text يحوي كلمات الواقعة حتى مع وجود كيانات، والاسم
        # الإلزامي (هنا speaker لعنصر «تصريح») يبقى أول الاستعلام ──
        _brief([{"text": "حقّقت الشركة إنجازًا صناعيًا كبيرًا", "kind": "تصريح",
                 "speaker": "Selçuk Bayraktar", "entities": ["Baykar", "90"],
                 "is_unnamed_event": False, "is_reference": False}])
        search_queries: list = []
        evidence.search = lambda query, cfg, days, unrestricted=False: (
            search_queries.append(query) or [object()])
        article._write_article("موجز اختبار ١", 9101, cfg)
        built = search_queries[0] if search_queries else ""
        check("سُلَّم البحث ١) الاسم الإلزامي يبقى أول الاستعلام رغم إضافة نص الواقعة",
              built.split()[:2] == ["Selçuk", "Bayraktar"], built)
        # build_query يُسقِط التشكيل (_TASHKEEL_RE) قبل بناء الاستعلام، فالشدّة
        # تسقط من «حقّقت» — المطابقة هنا على الإملاء بلا تشكيل كالمُتوقَّع فعليًا
        check("سُلَّم البحث ١) كلمة معنى من نص الواقعة («حققت») تدخل الاستعلام "
              "رغم وجود كيانات — لا تُهمَل كليًا كما في العطل الأصلي",
              "حققت" in built.split(), built)

        # ── ٢) محاولة أولى برجوع نتائج خام غير فارغة لكن سند غير كافٍ لا توقف
        # السُلَّم (البند 3، Issue #808 — شاهد «Vestel» وحدها رجعت 117 نتيجة
        # حقيقية عن موضوع آخر): محاولة ثانية بسند كافٍ فعليًا توقفه ──
        _brief([_stmt("تجاوزت ديون فيستل 105 مليارات ليرة",
                      ["فيستل", "105 مليارات ليرة"])])
        search_queries = []
        attempt_docs = [
            [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"}],
            [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"},
             {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1"}],
        ]

        def _fake_search_2(query, cfg, days, unrestricted=False):
            search_queries.append(query)
            return [object()]  # نتائج خام غير فارغة في كل محاولة — لا صفر نتائج هنا إطلاقًا

        def _fake_gather_2(articles, cfg, claim_text=""):
            idx = min(len(search_queries) - 1, len(attempt_docs) - 1)
            return list(attempt_docs[idx]), evidence.EVIDENCE_FULL_TEXT

        evidence.search = _fake_search_2
        evidence.gather_evidence = _fake_gather_2
        article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
            is_report=False, publisher="": [d["name"] for d in docs]
        outcome = article._write_article("موجز اختبار ٢", 9102, cfg)
        evidence.gather_evidence = lambda articles, cfg, claim_text="": (
            [], evidence.EVIDENCE_NO_RESULTS)
        article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
            is_report=False, publisher="": []
        check("سُلَّم البحث ٢) محاولتان بالضبط: الأولى مصدر واحد (دون العتبة) رغم "
              "نتائج خام غير فارغة، الثانية مصدران (يكفي) فتوقف السُلَّم",
              len(search_queries) == 2, search_queries)
        last_trail = outcome["trail"][-1]
        check("سُلَّم البحث ٢) trail يسجّل رقم المحاولة الناجحة (٢) — سندًا لا نتائج خامًا",
              last_trail.get("search_attempt") == 2, last_trail)
        check("سُلَّم البحث ٢) الواقعة اجتازت (لم تسقط) — السند اكتمل بالمحاولة الثانية",
              not any(d["text"] == "تجاوزت ديون فيستل 105 مليارات ليرة"
                     for d in outcome["dropped"]), outcome["dropped"])

        # ── ٣) المحاولة الثالثة لا تنطلق بلا query_latin — حتى لو صفرت
        # المحاولتان الأوليان معًا ──
        search_queries = []

        def _fake_all_zero(query, cfg, days, unrestricted=False):
            search_queries.append(query)
            return []

        evidence.search = _fake_all_zero
        outcome = article._write_article("موجز اختبار ٣", 9103, cfg)
        check("سُلَّم البحث ٣) صفر query_latin ⇒ محاولتان فقط رغم صفر نتائج بكليهما",
              len(search_queries) == 2, search_queries)

        # ── ٤) query_latin من أربع كلمات (لا اسم الكيان مجرَّدًا) يُستعمل كما
        # هو حرفيًا كمحاولة ثالثة، وينجح فعلًا بسند كافٍ ──
        _brief([_stmt("تجاوزت ديون فيستل 105 مليارات ليرة",
                      ["فيستل", "105 مليارات ليرة"],
                      query_latin="Vestel debt burden lira")])
        search_queries = []

        def _fake_search_4(query, cfg, days, unrestricted=False):
            search_queries.append(query)
            return [] if len(search_queries) < 3 else [object()]

        def _fake_gather_4(articles, cfg, claim_text=""):
            if len(search_queries) < 3:
                return [], evidence.EVIDENCE_NO_RESULTS
            return ([{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"},
                     {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1"}],
                    evidence.EVIDENCE_FULL_TEXT)

        evidence.search = _fake_search_4
        evidence.gather_evidence = _fake_gather_4
        article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
            is_report=False, publisher="": [d["name"] for d in docs]
        outcome = article._write_article("موجز اختبار ٤", 9104, cfg)
        evidence.gather_evidence = lambda articles, cfg, claim_text="": (
            [], evidence.EVIDENCE_NO_RESULTS)
        article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
            is_report=False, publisher="": []
        check("سُلَّم البحث ٤) query_latin موجود ⇒ محاولة ثالثة فعلية عند صفر الأوليين",
              len(search_queries) == 3, search_queries)
        check("سُلَّم البحث ٤) المحاولة الثالثة عبارة query_latin الأربع-كلمات كما "
              "هي حرفيًا — لا اسم الكيان مجرَّدًا",
              search_queries[2] == "Vestel debt burden lira", search_queries)
        last_trail = outcome["trail"][-1]
        check("سُلَّم البحث ٤) trail يسجّل رقم المحاولة الناجحة (٣)",
              last_trail.get("search_attempt") == 3, last_trail)

        # ── ٥) وقائع «فيستل» السبع (من السجل المرفق في الـIssue): استعلامات
        # المحاولة الثانية تحوي «مبيعات»/«ديون»/«خسائر» لا الأرقام وحدها ──
        vestel_facts = [
            _stmt("تراجعت مبيعات فيستل بنسبة 48%", ["فيستل", "48"]),
            _stmt("تجاوزت ديون فيستل 105 مليارات ليرة",
                  ["فيستل", "105 مليارات ليرة"]),
            _stmt("سجّلت فيستل خسائر بلغت 9.7 مليار ليرة",
                  ["فيستل", "9.7 مليار ليرة"]),
            _stmt("يعمل في فيستل نحو 20 ألف شخص", ["فيستل", "20 ألف شخص"]),
            _stmt("انخفضت حصة فيستل السوقية إلى 12%", ["فيستل", "12"]),
            _stmt("أغلقت فيستل 3 مصانع في تركيا", ["فيستل", "3 مصانع"]),
            _stmt("هبط سهم فيستل 15% في البورصة", ["فيستل", "15"]),
        ]
        _brief(vestel_facts)
        search_queries = []

        def _fake_alternating(query, cfg, days, unrestricted=False):
            # يحاكي التشغيلة الحقيقية: المحاولة المركَّبة (فردية الترتيب هنا)
            # تعود صفرًا دومًا، ونص الواقعة وحده (زوجية الترتيب) ينجح دومًا —
            # بصرف النظر عن محتوى الاستعلام. _support_sources تبقى المُعادة
            # [] بلا شرط (المُعاد ضبطها أعلاه) فلا سند يكتمل أبدًا هنا — يفحص
            # هذا السيناريو عرض بناء الاستعلامات عبر السُلَّم لا نجاح السند
            search_queries.append(query)
            return [] if len(search_queries) % 2 == 1 else [object()]

        evidence.search = _fake_alternating
        article._write_article("موجز اختبار وقائع فيستل السبع", 9105, cfg)
        check("وقائع فيستل السبع) سبع وقائع × محاولتان بالضبط = 14 نداء بحث",
              len(search_queries) == 14, len(search_queries))
        check("وقائع فيستل السبع) استعلام واقعة المبيعات الناجح يحوي «مبيعات»",
              "مبيعات" in search_queries[1].split(), search_queries[1])
        check("وقائع فيستل السبع) استعلام واقعة الديون الناجح يحوي «ديون»",
              "ديون" in search_queries[3].split(), search_queries[3])
        check("وقائع فيستل السبع) استعلام واقعة الخسائر الناجح يحوي «خسائر»",
              "خسائر" in search_queries[5].split(), search_queries[5])

        # ── ٦) query_latin يصير كلمة واحدة بعد تجريد الرقم برمجيًا («Vestel
        # 105» ⇦ «Vestel» ⇦ Issue #832: normalize_statements تُهمِل الحقل
        # كليًا حين يبقى أقل من كلمتين بعد التجريد، فيصل السُلَّم فارغًا —
        # يُعامَل كما لو غاب أصلًا (نظير السيناريو ٣ أعلاه)، لا محاولة ثالثة
        # ولا سطر تخطٍّ في trail (خلافًا لسلوك ما قبل #832 حين كان النص الخام
        # يصل السُلَّم كما هو فيُخطَّى هناك بدل أن يُهمَل قبل الوصول إليه) ──
        _brief([_stmt("تجاوزت ديون فيستل 105 مليارات ليرة",
                      ["فيستل", "105 مليارات ليرة"], query_latin="Vestel 105")])
        search_queries = []
        evidence.search = _fake_all_zero
        outcome = article._write_article("موجز اختبار ٦", 9106, cfg)
        check("سُلَّم البحث ٦) query_latin يصير كلمة واحدة بعد تجريد الرقم ⇒ "
              "يُهمَل قبل السُلَّم — محاولتان فقط أُرسلتا فعليًا للبحث",
              len(search_queries) == 2, search_queries)
        skip_entries = [t for t in outcome["trail"]
                       if "أقل من كلمتين" in (t.get("outcome") or "")]
        check("سُلَّم البحث ٦) لا سطر تخطٍّ في trail — الحقل أُهمِل قبل وصوله "
              "السُلَّم لا تُخُطِّي داخله (خلافًا لكلمة واحدة خام قبل #832)",
              len(skip_entries) == 0, skip_entries)
        # الواقعة الوحيدة في هذا الموجز لم تجد أي سند (آخر محاولة فعلية
        # الثانية) — لا خطأ ناتج عن query_latin المُهمَل؛ Issue #835 (الضمان)
        # يعني أنها لم تعد تبقى في dropped بل تنتقل درجة ج (fallback_to_brief)
        # إذ لا واقعة أخرى في هذا الموجز تُبقي grounded غير فارغة
        check("سُلَّم البحث ٦) الواقعة لم تجد سندًا من آخر محاولة فعلية (الثانية) فانتقلت "
              "درجة ج (الضمان) — لا خطأ ناتج عن query_latin المُهمَل",
              outcome["fallback_to_brief"] is True and
              any(g["text"] == "تجاوزت ديون فيستل 105 مليارات ليرة" and g["grade"] == "C"
                  for g in outcome["fact_grades"]),
              outcome["fact_grades"])

        # ── ٧) المصادر ذكرت الموضوع (fact_mentioned غير فارغة) ولم يطابق
        # مضمونها الواقعة — لا توقف صفر نتائج بل عدم إجماع؛ استعلام آخر لن
        # يغيّر حكمًا على مضمون وُجد بالفعل، فالسُلَّم يتوقف عند أول محاولة
        # بلا تصعيد لمحاولة تالية (طلب المراجعة، البند 2: في سجل فيستل
        # واقعتان من هذا النوع كلّفتا كل منهما دورة بحث/قراءة/حكم كاملة
        # إضافية بلا عائد قبل هذا الإصلاح) ──
        _brief([_stmt("تجاوزت ديون فيستل 105 مليارات ليرة",
                      ["فيستل", "105 مليارات ليرة"])])
        search_queries = []

        def _fake_search_7(query, cfg, days, unrestricted=False):
            search_queries.append(query)
            return [object()]

        def _fake_gather_7(articles, cfg, claim_text=""):
            return ([{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"}],
                    evidence.EVIDENCE_FULL_TEXT)

        def _fake_support_mentioned_only(fact_text, docs, cfg, is_statement=False,
                                         is_report=False, publisher=""):
            result = article._ModelCallList([])
            result.mentioned = ["مصدر أول"]
            return result

        evidence.search = _fake_search_7
        evidence.gather_evidence = _fake_gather_7
        article._support_sources = _fake_support_mentioned_only
        outcome = article._write_article("موجز اختبار ٧", 9107, cfg)
        evidence.gather_evidence = lambda articles, cfg, claim_text="": (
            [], evidence.EVIDENCE_NO_RESULTS)
        article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
            is_report=False, publisher="": []
        check("سُلَّم البحث ٧) مصدر ذكر الموضوع ولم يسنده ⇒ محاولة واحدة فقط "
              "(لا تصعيد لمحاولة ثانية رغم توفّرها)",
              len(search_queries) == 1, search_queries)
        last_trail = outcome["trail"][-1]
        check("سُلَّم البحث ٧) trail يسجّل توقّف السُلَّم عند المحاولة الأولى "
              "رغم توفّر محاولتين",
              last_trail.get("search_attempt") == 1 and
              last_trail.get("search_attempts_tried") == 2, last_trail)
        # trail (لا dropped بعد الضمان — Issue #835: الواقعة الوحيدة هنا
        # انتقلت درجة ج بدل السقوط) يحمل نفس التمييز الدقيق: "ذكره... ولم
        # يطابق مضمونه" لا "لم يُذكر إطلاقًا" — outcome_text لا drop_reason
        # هو من يحمله الآن لواقعة لم تعد تسقط
        check("سُلَّم البحث ٧) trail يذكر أن المصدر ذكر الموضوع ولم يطابق مضمونه "
              "— لا «لم يُذكر إطلاقًا»",
              "ذكره" in last_trail.get("outcome", "") and
              "لم يطابق مضمونه" in last_trail.get("outcome", ""), last_trail)
        check("سُلَّم البحث ٧) الواقعة انتقلت درجة ج (الضمان) لا سقطت",
              outcome["fallback_to_brief"] is True and
              any(g["text"] == "تجاوزت ديون فيستل 105 مليارات ليرة" and g["grade"] == "C"
                  for g in outcome["fact_grades"]),
              outcome["fact_grades"])
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images

def test_article_read_failure_substitution() -> None:
    """العطل الثاني (Issue #832): مرشح قراءة يفشل جلبه لا يُنهي الواقعة
    بمصدر ناقص — evidence.gather_evidence الحقيقية (لا مزيَّفة) عبر
    extract.gather الحقيقي أيضًا (نزيّف extract.fetch_text وحدها، أدنى نقطة
    ممكنة) يجب أن تستبدل المرشح الفاشل بالتالي له في القائمة المرتَّبة أصلًا
    فتبلغ عتبة السند رغم الفشل. الشاهد المُثبَّت من الـIssue: واقعة «يعمل في
    فيستل نحو 20 ألف شخص» — مرشّحان يفشل جلبهما (نصّ قصير جدًا/حجب) بين
    أربعة مرشّحين مرتَّبين، والاثنان الباقيان يكفيان (min_confirm_sources=2)
    فتُسنَد الواقعة بدل أن تسقط."""
    from src import article

    cfg = load_config()
    cfg["article"]["source_extract_enabled"] = False

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_support_sources = article._support_sources
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images
    real_fetch_text = extract.fetch_text

    now = datetime.now(timezone.utc)
    # ترتيب الوصول نفسه هو ترتيب مرشّحي القراءة هنا (صلة صفرية للجميع —
    # لا كلمة من العناوين تشارك relevance_text، فوزنهم الافتراضي المتساوي
    # 0.6 يبقي التعادل، ويحسمه فرز مستقر بترتيب الوصول — انظر
    # evidence._candidate_sort_key)
    candidates = [
        Article(title="تقرير عام عن قطاع الإلكترونيات", link="https://bikeeurope.example/1",
               summary="", source_name="Bike Europe", region="global", weight=1.0,
               published=now, publisher="Bike Europe"),
        Article(title="تحليل صناعي عام آخر", link="https://defensearabia.example/1",
               summary="", source_name="defensearabia.com", region="global", weight=1.0,
               published=now, publisher="defensearabia.com"),
        Article(title="مقال ثالث عام", link="https://third.example/1",
               summary="", source_name="المصدر الثالث", region="global", weight=1.0,
               published=now, publisher="المصدر الثالث"),
        Article(title="مقال رابع عام", link="https://fourth.example/1",
               summary="", source_name="المصدر الرابع", region="global", weight=1.0,
               published=now, publisher="المصدر الرابع"),
    ]

    def _fake_fetch_text(url, timeout=20):
        if url == "https://bikeeurope.example/1":
            return None, "نص قصير جدًا (224 حرف) — صفحة اشتراك/حظر محتملة"
        if url == "https://defensearabia.example/1":
            return None, "HTTP 403"
        return "نص مقروء فعليًا. " * 40, ""

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار استبدال مرشح فاشل",
        "statements": [{"text": "يعمل في فيستل نحو 20 ألف شخص", "kind": "واقعة",
                        "entities": ["فيستل", "20 ألف شخص"], "is_unnamed_event": False,
                        "is_reference": False, "query_latin": ""}],
        "questions": [],
    }, None)
    evidence.search = lambda query, cfg, days, unrestricted=False: list(candidates)
    # snippet_only (Issue #895) مُستبعَدة هنا كما تفعل _support_sources
    # الحقيقية فعليًا (عبر _format_docs) — الفاكة تُحاكي هذا الاستبعاد
    # صراحة، وإلا لظهر مرشّحا القراءة الفاشلان (اللذان صارا الآن مقتطفَين
    # في docs بدل إسقاط كلي) كمصدرين "مؤيِّدين" زورًا
    article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
        is_report=False, publisher="": [d["name"] for d in docs if not d.get("snippet_only")]
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار الاستبدال؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختبار الاستبدال.", "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []
    extract.fetch_text = _fake_fetch_text

    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        outcome = article._write_article("موجز اختبار استبدال مرشح فاشل", 9108, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        article._support_sources = real_support_sources
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images
        extract.fetch_text = real_fetch_text

    check("استبدال مرشح فاشل) الواقعة أُسنِدت (لم تسقط) رغم فشل مرشَّحين من "
          "أربعة — الاثنان الباقيان يكفيان min_confirm_sources",
          not any(d["text"] == "يعمل في فيستل نحو 20 ألف شخص"
                 for d in outcome["dropped"]), outcome["dropped"])
    fact_trail = [t for t in outcome["trail"] if t["stage"] == "واقعة"]
    check("استبدال مرشح فاشل) trail يسجّل اسمَي المرشّحين الفاشلين وسبب فشل كل منهما",
          bool(fact_trail) and
          {f["name"] for f in fact_trail[0].get("fetch_failures", [])} ==
          {"Bike Europe", "defensearabia.com"}, fact_trail)
    # منذ Issue #895، المرشّحان الفاشلان لا يختفيان كليًا من docs (مقتطف
    # عنوان+ملخص بدل إسقاط كلي) — trail["sources"] يعرض الأربعة معًا الآن،
    # لكن outcome["sources"] (المصادر المسنِدة فعليًا فقط، من unique/supporting)
    # يبقى يحمل البديلين الناجحين حصرًا لا الفاشلَين المتحوَّلين لمقتطف
    check("استبدال مرشح فاشل) trail[sources] يعرض الأربعة معًا (البديلان "
          "الناجحان + مقتطفا المرشَّحين الفاشلَين، Issue #895)",
          bool(fact_trail) and
          set(fact_trail[0].get("sources", [])) ==
          {"المصدر الثالث", "المصدر الرابع", "Bike Europe", "defensearabia.com"},
          fact_trail)
    check("استبدال مرشح فاشل) المصادر المسندة فعليًا هي البديلان الناجحان لا "
          "الفاشلَين (مقتطفاهما لا يدخلان السند، Issue #895)",
          {s["name"] for s in outcome["sources"]} == {"المصدر الثالث", "المصدر الرابع"},
          outcome["sources"])

def test_article_wide_days() -> None:
    """توسيع نافذة البحث مرة واحدة عند صفر نتائج خام (Issue #820، الجزء
    الثالث من ثلاثة — نُفِّذ قبل الثاني عمدًا). الشاهد: موجز ديون «فيستل» —
    أرقام الربع الأول تُنشر بعد شهور من تاريخ لصق الموجز، فwhen:21d كان
    يُسقطها قبل أن تصل صفحة نتائج واحدة رغم استعلامات سليمة تمامًا. العلاج:
    محاولة واحدة إضافية بـarticle.wide_days بدل days حين تعود المحاولة
    النصّية بصفر نتائج بحث خام (raw_count==0) — بُعد داخل المحاولة لا
    محاولة رابعة، ولا حين توجد نتائج غير مسندة (Issue #810 يبقى كما هو)،
    ولا لواقعة مرجعية (is_reference)، ولا لبحث الأسئلة إطلاقًا."""
    from src import article

    cfg = load_config()
    cfg["article"]["source_extract_enabled"] = False
    cfg["article"]["wide_days"] = 540

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images

    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار التوسيع؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختبار توسيع النافذة.", "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []

    def _brief(statements: list, questions: list | None = None) -> None:
        article.extract_brief = lambda body, cfg, retries=3: ({
            "topic": "اختبار توسيع النافذة", "statements": statements,
            "questions": questions or [],
        }, None)

    def _stmt(text: str, entities: list, is_reference: bool = False) -> dict:
        return {"text": text, "kind": "واقعة", "entities": entities,
                "is_unnamed_event": False, "is_reference": is_reference, "query_latin": ""}

    old_date = datetime(2023, 5, 10, tzinfo=timezone.utc)
    wide_docs = [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"},
                {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1"}]
    wide_articles = [
        Article(title="ت١", link="https://s1/1", summary="", source_name="مصدر أول",
               region="global", weight=1.0, published=old_date, publisher="مصدر أول"),
        Article(title="ت٢", link="https://s2/1", summary="", source_name="مصدر ثانٍ",
               region="global", weight=1.0, published=old_date + timedelta(days=3),
               publisher="مصدر ثانٍ"),
    ]

    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        # ── ١) صفر نتائج خام بالنافذة العادية ⇒ توسيع مرة واحدة بـwide_days
        # بنفس الاستعلام حرفيًا، ينجح فيسند الواقعة، ويُسجَّل التوسيع في
        # trail وقسم «مسندة بمصادر أقدم» في outcome/التقرير ──
        _brief([_stmt("تجاوزت ديون فيستل 105 مليارات ليرة",
                      ["فيستل", "105 مليارات ليرة"])])
        calls: list = []

        def _fake_search_1(query, cfg, days, unrestricted=False):
            calls.append((query, days))
            if days == 540:
                return evidence._search_result(list(wide_articles), 2, 2)
            return evidence._search_result([], 0, 0)

        def _fake_gather_1(articles, cfg, claim_text=""):
            if articles:
                return list(wide_docs), evidence.EVIDENCE_FULL_TEXT
            return [], evidence.EVIDENCE_NO_RESULTS

        evidence.search = _fake_search_1
        evidence.gather_evidence = _fake_gather_1
        article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
            is_report=False, publisher="": [d["name"] for d in docs]
        outcome = article._write_article("موجز اختبار توسيع ١", 9201, cfg)
        evidence.gather_evidence = lambda articles, cfg, claim_text="": (
            [], evidence.EVIDENCE_NO_RESULTS)
        article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
            is_report=False, publisher="": []

        check("توسيع ١) محاولة واحدة بالضبط بالنافذة العادية (21) قبل التوسيع",
              sum(1 for q, d in calls if d == 21) == 1, calls)
        check("توسيع ١) محاولة واحدة إضافية بالضبط بـwide_days (540)",
              sum(1 for q, d in calls if d == 540) == 1, calls)
        check("توسيع ١) الاستعلام الموسَّع مطابق حرفيًا للاستعلام العادي",
              calls[0][0] == calls[1][0], calls)
        check("توسيع ١) الواقعة اجتازت (لم تسقط) بعد التوسيع",
              not any(d["text"] == "تجاوزت ديون فيستل 105 مليارات ليرة"
                     for d in outcome["dropped"]), outcome["dropped"])
        last_trail = outcome["trail"][-1]
        check("توسيع ١) trail يُعلِّم المحاولة widened=True",
              last_trail.get("widened") is True, last_trail)
        check("توسيع ١) outcome السردي يذكر نافذة موسّعة 540 يومًا",
              "⏳ نافذة موسّعة 540 يومًا" in (last_trail.get("outcome") or ""), last_trail)
        check("توسيع ١) قسم الوقائع الأقدم من النافذة المعتادة يحوي الواقعة",
              len(outcome["older_window_facts"]) == 1 and
              outcome["older_window_facts"][0]["text"] == "تجاوزت ديون فيستل 105 مليارات ليرة",
              outcome["older_window_facts"])
        check("توسيع ١) أقدم تاريخ مصدر هو تاريخ «مصدر أول» الأقدم لا «مصدر ثانٍ»",
              outcome["older_window_facts"][0]["oldest_date"] == old_date.strftime("%Y-%m-%d"),
              outcome["older_window_facts"])
        report = article.build_report(outcome)
        check("توسيع ١) التقرير يحوي قسم «مسندة بمصادر أقدم من النافذة المعتادة»",
              "مسندة بمصادر أقدم من النافذة المعتادة — راجع تواريخها" in report, report)

        # ── ٢) نتائج خام غير صفرية لكن سند غير كافٍ لا تُطلِق التوسيع أبدًا
        # (Issue #810: البحث أصاب والمصادر لا تؤيد، لا عطل بحث) ──
        _brief([_stmt("تجاوزت ديون فيستل 105 مليارات ليرة",
                      ["فيستل", "105 مليارات ليرة"])])
        calls = []

        def _fake_search_2(query, cfg, days, unrestricted=False):
            calls.append((query, days))
            return evidence._search_result([object()], 3, 3)

        def _fake_gather_2(articles, cfg, claim_text=""):
            return [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"}], \
                evidence.EVIDENCE_FULL_TEXT

        evidence.search = _fake_search_2
        evidence.gather_evidence = _fake_gather_2
        article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
            is_report=False, publisher="": []  # سند غير كافٍ دومًا
        outcome2 = article._write_article("موجز اختبار توسيع ٢", 9202, cfg)
        evidence.gather_evidence = lambda articles, cfg, claim_text="": (
            [], evidence.EVIDENCE_NO_RESULTS)
        article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
            is_report=False, publisher="": []

        check("توسيع ٢) نتائج خام غير صفرية مع سند غير كافٍ ⇒ لا نداء بwide_days إطلاقًا",
              all(d != 540 for q, d in calls), calls)
        check("توسيع ٢) محاولتان نصّيتان عاديتان فقط (بلا أي توسيع)",
              len(calls) == 2, calls)
        check("توسيع ٢) بلا وقائع في قسم النافذة الموسّعة",
              outcome2["older_window_facts"] == [], outcome2["older_window_facts"])

        # ── ٣) صفر نتائج بالنافذة العادية، وصفر أيضًا بالموسّعة ⇒ توسيع واحد
        # فقط لكل محاولة نصّية، ثم انتقال للمحاولة التالية (لا محاولة رابعة) ──
        _brief([_stmt("تجاوزت ديون فيستل 105 مليارات ليرة",
                      ["فيستل", "105 مليارات ليرة"])])
        calls = []

        def _fake_search_3(query, cfg, days, unrestricted=False):
            calls.append((query, days))
            return evidence._search_result([], 0, 0)

        evidence.search = _fake_search_3
        outcome3 = article._write_article("موجز اختبار توسيع ٣", 9203, cfg)
        check("توسيع ٣) محاولتان نصّيتان × (عادية+موسّعة) = 4 نداءات بحث بالضبط",
              len(calls) == 4, calls)
        check("توسيع ٣) توسيع واحد فقط لكل محاولة نصّية (لا تكرار)",
              sum(1 for q, d in calls if d == 540) == 2, calls)
        check("توسيع ٣) بلا وقائع بنافذة موسّعة (لم يُسنَد شيء فعليًا)",
              outcome3["older_window_facts"] == [], outcome3["older_window_facts"])

        # ── ٤) واقعة مرجعية (is_reference) لا تُوسَّع أبدًا رغم صفر نتائج —
        # unrestricted يُسقط قيد days أصلًا في evidence.search، فتوسيعها ثانية
        # بلا معنى ──
        _brief([_stmt("خلفية مرجعية عن فيستل", ["فيستل"], is_reference=True)])
        calls = []

        def _fake_search_4(query, cfg, days, unrestricted=False):
            calls.append((query, days))
            return evidence._search_result([], 0, 0)

        evidence.search = _fake_search_4
        article._write_article("موجز اختبار توسيع ٤", 9204, cfg)
        check("توسيع ٤) واقعة مرجعية لا تُوسَّع أبدًا رغم صفر نتائج خام",
              all(d != 540 for q, d in calls), calls)
        check("توسيع ٤) محاولتان نصّيتان فقط (بلا أي توسيع) لواقعة مرجعية",
              len(calls) == 2, calls)

        # ── ٥) بحث السؤال ([سؤال] في trail) لا يُوسَّع أبدًا حتى مع صفر
        # نتائج خام — السؤال يسأل عن تحليل راهن، وتوسيعه يجلب تحليلًا قديمًا
        # يُقدَّم كأنه اليوم ──
        _brief([_stmt("تجاوزت ديون فيستل 105 مليارات ليرة",
                      ["فيستل", "105 مليارات ليرة"])],
              questions=[{"text": "ما مستقبل فيستل؟", "entities": ["فيستل"],
                         "is_reference": False}])
        calls = []

        def _fake_search_5(query, cfg, days, unrestricted=False):
            calls.append((query, days))
            # الواقعة (النداء الأول) تُسنَد فورًا بنتائج خام غير صفرية —
            # عزلًا لسلوك بحث السؤال (التالي) عن سُلَّم الواقعة نفسه
            if len(calls) == 1:
                return evidence._search_result([object()], 5, 5)
            return evidence._search_result([], 0, 0)

        def _fake_gather_5(articles, cfg, claim_text=""):
            if articles:
                return ([{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"},
                        {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1"}],
                       evidence.EVIDENCE_FULL_TEXT)
            return [], evidence.EVIDENCE_NO_RESULTS

        evidence.search = _fake_search_5
        evidence.gather_evidence = _fake_gather_5
        article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
            is_report=False, publisher="": [d["name"] for d in docs]
        article._write_article("موجز اختبار توسيع ٥", 9205, cfg)
        evidence.gather_evidence = lambda articles, cfg, claim_text="": (
            [], evidence.EVIDENCE_NO_RESULTS)
        article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
            is_report=False, publisher="": []

        check("توسيع ٥) نداء واحد فقط لبحث السؤال، بالنافذة العادية (21) لا الموسّعة",
              len(calls) == 2 and calls[1][1] == 21, calls)
        check("توسيع ٥) بلا أي نداء بـwide_days لبحث السؤال رغم صفر نتائجه الخام",
              all(d != 540 for q, d in calls), calls)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images

def test_article_support_call_caching() -> None:
    """تخزين كتلة الوثائق مؤقتًا في نداءات الحكم على السند (طلب المراجعة):
    تشغيلة حقيقية سجّلت ٩٤٪ من كلفة تشغيلة المقال إدخالًا، منه ١٪ فقط
    مخزَّن مؤقتًا — لأن نصوص المصادر كانت تُرسَل مدموجة بنص الواقعة
    المتغيّر في رسالة واحدة، فأي اختلاف في نص الواقعة (متوقَّع دومًا بين
    وقائع مختلفة) يُبطل الإصابة لكل الرسالة رغم ثبات الوثائق نفسها.
    العلاج: رسالة المستخدم كتلتان — كتلة أولى ثابتة الترتيب لنصوص الوثائق
    عليها cache_control، وكتلة ثانية بلا تخزين للنص المتغيّر. هذا الاختبار
    يثبّت الشكل (كتلتان، cache_control على الأولى فقط)، ثبات الكتلة الأولى
    حرفيًا بين نداءين لنفس مجموعة الوثائق رغم اختلاف النص المتغيّر، وأن
    مخرَج _support_sources/_support_statement_parts لم يتغيّر لنفس المدخلات
    (نفس القيم التي تثبّتها test_article_report_kind/test_article_statement_majority
    القائمان بشكلٍ مباشر لهذه الدالتين)."""
    from src import article

    cfg = load_config()

    class _CaptureBlock:
        type = "text"

    class _CaptureResp:
        content = [_CaptureBlock()]
        stop_reason = "end_turn"

    class _CaptureMessages:
        def __init__(self, captured):
            self._captured = captured

        def create(self, **kw):
            self._captured.append(kw)
            return _CaptureResp()

    class _CaptureClient:
        def __init__(self, captured):
            self.messages = _CaptureMessages(captured)

    real_client_fn = article._client
    docs = [{"name": "مصدر أول", "text": "نص أول", "link": "https://s1/1"},
           {"name": "مصدر ثانٍ", "text": "نص ثانٍ", "link": "https://s2/1"}]

    # ── _support_sources: رسالتان بفارق نص الواقعة وحده، بنفس مجموعة الوثائق ──
    captured: list = []
    article._client = lambda: _CaptureClient(captured)
    article._support_sources("واقعة اختبار أولى", docs, cfg)
    article._support_sources("واقعة اختبار ثانية", docs, cfg)
    article._client = real_client_fn

    content1 = captured[0]["messages"][0]["content"]
    content2 = captured[1]["messages"][0]["content"]
    check("_support_sources: محتوى رسالة المستخدم صار قائمة كتلتين لا نصًّا واحدًا",
          isinstance(content1, list) and len(content1) == 2, content1)
    check("_support_sources: الكتلة الأولى (الوثائق) وحدها تحمل cache_control",
          content1[0].get("cache_control") == {"type": "ephemeral"} and
          "cache_control" not in content1[1], content1)
    check("_support_sources: الكتلة الأولى تحمل نصوص الوثائق بترتيب ورودها",
          content1[0]["text"].index("مصدر أول") < content1[0]["text"].index("مصدر ثانٍ"),
          content1[0]["text"])
    check("_support_sources: الكتلة الثانية تحمل نص الواقعة المتغيّر فقط",
          content1[1]["text"] == "الواقعة: واقعة اختبار أولى", content1[1])
    check("_support_sources: كتلة الوثائق حرفيًا مطابقة بين نداءين لنفس مجموعة "
          "الوثائق رغم اختلاف نص الواقعة — شرط إصابة الذاكرة المؤقتة",
          content1[0] == content2[0], (content1[0], content2[0]))
    check("_support_sources: نص الواقعة المتغيّر خارج الكتلة المخزَّنة ويختلف فعليًا "
          "بين النداءين",
          content2[1]["text"] == "الواقعة: واقعة اختبار ثانية" and
          content1[1] != content2[1], (content1[1], content2[1]))

    # ── مخرَج _support_sources لم يتغيّر لنفس المدخلات (تثبيت حالة من
    # test_article_report_kind: مصدر واحد مطابق ← نفس اسمه في المخرَج) ──
    captured_out: list = []
    article._client = lambda: _CaptureClient(captured_out)

    class _SupportBlock:
        type = "tool_use"
        input = {"supporting": ["مصدر أول"], "mentioned": ["مصدر أول"]}

    class _SupportResp:
        content = [_SupportBlock()]
        stop_reason = "end_turn"

    class _SupportMessages:
        def create(self, **kw):
            return _SupportResp()

    class _SupportClient:
        def __init__(self):
            self.messages = _SupportMessages()

    article._client = lambda: _SupportClient()
    out = article._support_sources("واقعة اختبار", docs, cfg)
    article._client = real_client_fn
    check("_support_sources: المخرَج لم يتغيّر لنفس المدخلات (أسماء المصادر "
          "المؤيِّدة الفعلية من رد النموذج، بصرف النظر عن شكل الرسالة المُرسَلة)",
          list(out) == ["مصدر أول"], out)

    # ── _support_statement_parts: نفس البنية (كتلتان، الوثائق أولًا ومخزَّنة) ──
    captured_parts: list = []
    article._client = lambda: _CaptureClient(captured_parts)
    article._support_statement_parts(["جزء أول", "جزء ثانٍ"], docs, cfg)
    article._client = real_client_fn

    parts_content = captured_parts[0]["messages"][0]["content"]
    check("_support_statement_parts: محتوى الرسالة كتلتان أيضًا",
          isinstance(parts_content, list) and len(parts_content) == 2, parts_content)
    check("_support_statement_parts: الكتلة الأولى (الوثائق) وحدها تحمل "
          "cache_control، ونصها مطابق حرفيًا لكتلة _support_sources لنفس "
          "الوثائق (نفس _format_docs، نفس الترتيب)",
          parts_content[0].get("cache_control") == {"type": "ephemeral"} and
          "cache_control" not in parts_content[1] and
          parts_content[0] == content1[0], parts_content)
    check("_support_statement_parts: الكتلة الثانية تحمل أجزاء التصريح المرقَّمة "
          "فقط، لا نصوص الوثائق",
          parts_content[1]["text"] == "أجزاء التصريح:\n1. جزء أول\n2. جزء ثانٍ",
          parts_content[1])

def test_article_source_fact_duplicate_index_on_topic() -> None:
    """وحدة _source_fact_duplicate_index بعد Issue #824: on_topic/on_topic_reason
    حقلان جديدان في نفس نداء التكرار (لا نداء إضافي). يغطي: حكم النموذج
    الناجح، حقل on_topic غائب/مشوَّه يفشل مفتوحًا (True)، فشل نداء تقني
    يفشل مفتوحًا لكليهما (duplicate=False و on_topic=True معًا)، و
    existing_texts فارغة لا تستدعي النموذج إطلاقًا (لا تكلفة على أول واقعة
    حين لا شيء لمقارنتها بعد)."""
    from src import article

    class _Block:
        def __init__(self, input_):
            self.type = "tool_use"
            self.input = input_

    class _Resp:
        def __init__(self, input_):
            self.content = [_Block(input_)]
            self.usage = None

    class _Messages:
        def __init__(self, input_, calls):
            self._input = input_
            self._calls = calls

        def create(self, **kw):
            self._calls.append(kw)
            return _Resp(self._input)

    class _Client:
        def __init__(self, input_, calls):
            self.messages = _Messages(input_, calls)

    cfg = load_config()
    real_client_fn = article._client

    calls: list = []
    article._client = lambda: _Client(
        {"duplicate_index": -1, "on_topic": True, "on_topic_reason": "نفس الموضوع"}, calls)
    result = article._source_fact_duplicate_index(
        "واقعة جديدة", ["واقعة سابقة"], cfg, topic="موضوع الموجز")
    article._client = real_client_fn
    check("_source_fact_duplicate_index: حكم on_topic=True ناجح يُقرأ من الرد",
          result == {"duplicate": False, "index": None, "call_error": None,
                    "on_topic": True, "on_topic_reason": "نفس الموضوع"}, result)
    check("_source_fact_duplicate_index: نداء واحد فقط (لا نداء إضافي لحكم الموضوع)",
          len(calls) == 1, calls)
    check("_source_fact_duplicate_index: البرومبت يحمل موضوع الموجز صراحة",
          "موضوع الموجز" in calls[0]["messages"][0]["content"], calls[0])

    article._client = lambda: _Client(
        {"duplicate_index": 0, "on_topic": False, "on_topic_reason": "موضوع آخر"}, [])
    dup_offtopic = article._source_fact_duplicate_index(
        "واقعة مكرَّرة", ["واقعة سابقة"], cfg, topic="موضوع الموجز")
    article._client = real_client_fn
    check("_source_fact_duplicate_index: duplicate=True و on_topic=False معًا يُقرآن معًا "
          "من نفس الرد",
          dup_offtopic == {"duplicate": True, "index": 0, "call_error": None,
                           "on_topic": False, "on_topic_reason": "موضوع آخر"}, dup_offtopic)

    # حقل on_topic غائب من رد النموذج (تشوّه/عطل تسمية) — يفشل مفتوحًا
    # (True)، لا يُعامَل حجبًا (Issue #824، "عند فشل النداء أو غياب الحقل:
    # اسمح بالدخول ولا تحجب")
    article._client = lambda: _Client({"duplicate_index": -1}, [])
    missing_field = article._source_fact_duplicate_index(
        "واقعة جديدة", ["واقعة سابقة"], cfg, topic="موضوع الموجز")
    article._client = real_client_fn
    check("_source_fact_duplicate_index: غياب حقل on_topic من الرد يفشل مفتوحًا (True)",
          missing_field["on_topic"] is True and missing_field["on_topic_reason"] == "",
          missing_field)

    # فشل نداء تقني (Issue #824): duplicate=False و on_topic=True معًا —
    # لا تُحجب الواقعة لا لعطل تكرار ولا لعطل موضوع، وتخضع لحكم السند
    # الفعلي بدلًا من ذلك (انظر test_article_source_fact_topic_guard)
    from anthropic import APIError
    import httpx as _httpx

    class _RaisingMessages:
        def create(self, **kw):
            raise APIError(
                "عطل شبكة اختباري",
                request=_httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
                body=None)

    class _RaisingClient:
        def __init__(self):
            self.messages = _RaisingMessages()

    article._client = lambda: _RaisingClient()
    failed = article._source_fact_duplicate_index(
        "واقعة جديدة", ["واقعة سابقة"], cfg, topic="موضوع الموجز")
    article._client = real_client_fn
    check("_source_fact_duplicate_index: فشل نداء تقني لا ينهار، ويعيد duplicate=False "
          "و on_topic=True معًا (فتح لا حجب)",
          failed["duplicate"] is False and failed["call_error"] and
          failed["on_topic"] is True, failed)

    # existing_texts فارغة: لا نداء إطلاقًا (لا شيء لمقارنة التكرار به)،
    # ويفشل on_topic مفتوحًا بنفس السياسة
    no_call: list = []
    article._client = lambda: _Client({"duplicate_index": -1, "on_topic": True}, no_call)
    empty_existing = article._source_fact_duplicate_index(
        "واقعة جديدة", [], cfg, topic="موضوع الموجز")
    article._client = real_client_fn
    check("_source_fact_duplicate_index: existing_texts فارغة ← لا نداء نموذج إطلاقًا",
          no_call == [], no_call)
    check("_source_fact_duplicate_index: existing_texts فارغة ← on_topic=True افتراضيًا",
          empty_existing["on_topic"] is True, empty_existing)

def test_article_source_fact_topic_guard() -> None:
    """حارس الموضوع لوقائع المصادر (Issue #808 البند 4، ثم Issue #824).
    الشاهد الأول (#808): موجز عن ديون شركة «فيستل» استخرج من مصادر البحث
    واقعة «باعت فيستل حصتها في توغ» — نفس الكيان (فيستل) لكن موضوع مختلف
    كليًا. عولج حينها بتقاطع كلمة معنى حرفي (norm_tokens) بعد تقاطع الكيانات
    — لكن العربية تصرّف (جمع/مفرد، همزات)، فشاهد ثانٍ حقيقي (#824) بيّن أن
    نفس هذا التقاطع الحرفي يحجب وقائع مسندة صميمة («ديون» لا تقاطع «الدين»،
    «خسائر» لا تقاطع «خسارة») — أربع من ثماني وقائع موجز حقيقي سقطت هكذا.
    العلاج: التقاطع الحرفي أُلغي كليًا، واستُبدل بحكم نموذج (on_topic) داخل
    نفس نداء _source_fact_duplicate_index — entity_ok (تقاطع الكيانات فقط)
    يبقى مرشِّحًا رخيصًا أوليًا كما هو."""
    from src import article

    cfg = load_config()
    cfg["article"]["source_extract_enabled"] = True

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images
    real_extract_source_facts = article._extract_source_facts
    real_client_fn = article._client

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "ديون فيستل التركية وخسائرها",
        "statements": [
            {"text": "تجاوزت ديون فيستل 105 مليارات ليرة", "kind": "واقعة",
             "entities": ["فيستل"], "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1", "from_text": True},
         {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1", "from_text": True}],
        evidence.EVIDENCE_FULL_TEXT)
    article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
        is_report=False, publisher="": [d["name"] for d in docs]
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار الحارس؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "اقتصاد",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختباري بلا أي تشابه لفظي مع مصدر.",
         "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []

    # الشاهد الفعلي المرفق في Issue #824: أربع وقائع مسندة صميم موضوع
    # الموجز (الديون والخسائر) سقطت سابقًا بتقاطع كلمات حرفي — يجب أن تدخل
    debt_total = {"text": "إجمالي دين فيستل بلغ 147.59 مليار ليرة", "entities": ["فيستل"]}
    quarterly_loss = {"text": "سجّلت فيستل أكبر خسارة فصلية في تاريخها",
                      "entities": ["فيستل"]}
    obligations = {"text": "التزامات فيستل باتت أربعة أضعاف رأس مالها",
                   "entities": ["فيستل"]}
    sales_decline = {"text": "تراجع إنتاج فيستل 35% وتراجعت مبيعاتها 16%",
                     "entities": ["فيستل"]}
    on_topic_facts = [debt_total, quarterly_loss, obligations, sales_decline]

    # نفس الكيان («فيستل») لكن موضوع مختلف كليًا — يجب أن تُحجب
    tug_fact = {"text": "باعت فيستل حصتها في شركة توغ للدفاع", "entities": ["فيستل", "توغ"]}
    fridge_fact = {"text": "فازت ثلاجة من فيستل بجائزة أفضل تصميم صناعي",
                   "entities": ["فيستل"]}
    kuwait_fact = {"text": "أطلقت فيستل تشكيلة منتجاتها الجديدة في السوق الكويتي",
                  "entities": ["فيستل"]}
    off_topic_facts = [tug_fact, fridge_fact, kuwait_fact]

    # بلا أي تقاطع كيانات إطلاقًا — الفحص العام (off_topic) لا حارس الكيان
    unrelated_fact = {"text": "افتتح مطعم جديد في اسطنبول", "entities": ["اسطنبول"]}

    article._extract_source_facts = lambda topic, brief_texts, docs, cfg: (
        on_topic_facts + off_topic_facts + [unrelated_fact])

    off_topic_texts = {f["text"] for f in off_topic_facts}

    class _GuardBlock:
        def __init__(self, input_):
            self.type = "tool_use"
            self.input = input_

    class _GuardResp:
        def __init__(self, input_):
            self.content = [_GuardBlock(input_)]
            self.usage = None

    class _GuardMessages:
        def __init__(self, calls):
            self._calls = calls

        def create(self, **kw):
            self._calls.append(kw)
            prompt = kw["messages"][0]["content"]
            on_topic = not any(t in prompt for t in off_topic_texts)
            reason = "" if on_topic else "نفس الكيان بموضوع مختلف"
            return _GuardResp({"duplicate_index": -1, "on_topic": on_topic,
                              "on_topic_reason": reason})

    class _GuardClient:
        def __init__(self, calls):
            self.messages = _GuardMessages(calls)

    guard_calls: list = []
    article._client = lambda: _GuardClient(guard_calls)

    try:
        out = article._write_article("موجز اختبار حارس الموضوع", 9110, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images
        article._extract_source_facts = real_extract_source_facts
        article._client = real_client_fn

    source_texts = [g["text"] for g in out.get("source_origin_facts", [])]
    check("حارس الموضوع: الوقائع الأربع الصميمة (الدين، الخسارة الفصلية، الالتزامات، "
          "تراجع المبيعات) دخلت المقال رغم عدم تطابقها الحرفي مع «ديون»/«خسائر»",
          all(f["text"] in source_texts for f in on_topic_facts), source_texts)
    check("حارس الموضوع: وقائع «توغ»/الثلاجة/إطلاق الكويت (نفس الكيان، موضوع مختلف) "
          "لم تدخل المقال",
          not any(f["text"] in source_texts for f in off_topic_facts), source_texts)
    check("حارس الموضوع: الوقائع الثلاث المحجوبة ظهرت في same_entity_off_topic_facts",
          {f["text"] for f in out["same_entity_off_topic_facts"]} == off_topic_texts,
          out["same_entity_off_topic_facts"])
    check("حارس الموضوع: source_facts_summary يعكس same_entity_off_topic بـ٣ لا off_topic "
          "العام",
          out["source_facts_summary"]["same_entity_off_topic"] == 3, out["source_facts_summary"])
    check("حارس الموضوع: واقعة بلا أي تقاطع كيانات سقطت بالفحص العام off_topic "
          "لا same_entity_off_topic",
          out["source_facts_summary"]["off_topic"] == 1, out["source_facts_summary"])
    check("حارس الموضوع: نداء نموذج واحد بالضبط لكل واقعة اجتازت entity_ok (٧ وقائع: "
          "٤ صميمة + ٣ نفس الكيان) — لا نداء إضافي منفصل لحكم الموضوع",
          len(guard_calls) == 7, len(guard_calls))

    report = article.build_report(out)
    check("حارس الموضوع: التقرير يعرض قسم «وقائع عن نفس الكيان بموضوع مختلف — "
          "لم تدخل المقال» صراحة، وسبب الحكم (on_topic_reason) لكل واقعة محجوبة",
          "وقائع عن نفس الكيان بموضوع مختلف" in report and
          "توغ" in report and "نفس الكيان بموضوع مختلف" in report.split(
              "وقائع عن نفس الكيان بموضوع مختلف")[1], report)

def test_article_source_fact_topic_guard_call_failure_admits() -> None:
    """فشل نداء _source_fact_duplicate_index التقني لا يحجب الواقعة ولا
    ينهار (Issue #824، آخر بند من اختبارات الـIssue) — الواقعة تمرّ إلى حكم
    السند الفعلي (min_confirm) بدل أن تُسقَط احتياطًا على عطل تقني عابر."""
    from src import article

    cfg = load_config()
    cfg["article"]["source_extract_enabled"] = True

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images
    real_extract_source_facts = article._extract_source_facts
    real_client_fn = article._client

    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "ديون فيستل التركية",
        "statements": [
            {"text": "تجاوزت ديون فيستل 105 مليارات ليرة", "kind": "واقعة",
             "entities": ["فيستل"], "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1", "from_text": True},
         {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1", "from_text": True}],
        evidence.EVIDENCE_FULL_TEXT)
    article._support_sources = lambda fact_text, docs, cfg, is_statement=False, \
        is_report=False, publisher="": [d["name"] for d in docs]
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار الحارس؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "اقتصاد",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختباري بلا أي تشابه لفظي مع مصدر.",
         "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []

    failing_fact = {"text": "تجاوزت التزامات فيستل حاجز 200 مليار ليرة إضافية",
                    "entities": ["فيستل"]}
    article._extract_source_facts = lambda topic, brief_texts, docs, cfg: [failing_fact]

    from anthropic import APIError
    import httpx as _httpx

    class _RaisingMessages:
        def create(self, **kw):
            raise APIError(
                "عطل شبكة اختباري",
                request=_httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
                body=None)

    class _RaisingClient:
        def __init__(self):
            self.messages = _RaisingMessages()

    article._client = lambda: _RaisingClient()

    try:
        out = article._write_article("موجز اختبار عطل الحارس", 9111, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images
        article._extract_source_facts = real_extract_source_facts
        article._client = real_client_fn

    check("حارس الموضوع: فشل نداء تقني لا ينهار التشغيلة كاملة",
          isinstance(out, dict), type(out))
    check("حارس الموضوع: فشل نداء تقني لم يُحجب الواقعة بحارس الموضوع "
          "(لم تظهر في same_entity_off_topic_facts)",
          not any(f["text"] == failing_fact["text"]
                 for f in out.get("same_entity_off_topic_facts", [])),
          out.get("same_entity_off_topic_facts"))
    check("حارس الموضوع: فشل نداء تقني سمح للواقعة بالوصول لحكم السند فدخلت المقال "
          "فعلًا (min_confirm محقَّق بمصدرين وهميين)",
          any(g["text"] == failing_fact["text"]
             for g in out.get("source_origin_facts", [])),
          out.get("source_origin_facts"))

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
    # الرسالة صارت كتلتين (طلب المراجعة، تخزين الوثائق مؤقتًا) — نصوص
    # الوثائق في الكتلة الأولى تحديدًا، لا في محتوى الرسالة كنص واحد
    docs_block_text = captured[0]["messages"][0]["content"][0]["text"]
    check("_support_sources(is_report=True): الوثيقة المطابقة للهوية فقط تصل البرومبت "
          "— unrelated_doc (لا يطابق الهوية) لا تصل النموذج إطلاقًا",
          original_doc["name"] in docs_block_text and unrelated_doc["name"] not in docs_block_text,
          docs_block_text)

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

    # ── ضابط _sufficiency الثالث (أُلغي، Issue #814 جزء 1): مقال بكامله
    # «تقارير منقولة» لم يعد يُمنَع — واقعة مسندة واحدة (بأي تصنيف) كافية ──
    all_report_grounded = [
        {"kind": "تقرير منقول", "is_reference": False, "text": "تقرير أول"},
        {"kind": "تقرير منقول", "is_reference": False, "text": "تقرير ثانٍ"},
    ]
    ok_suff, reason_suff = article._sufficiency(all_report_grounded, cfg)
    check("_sufficiency: مقال كله «تقرير منقول» لم يعد يُرفض — الضابط الثالث القديم أُلغي",
          ok_suff is True, reason_suff)

    mixed_grounded = [
        {"kind": "تقرير منقول", "is_reference": False, "text": "تقرير أول"},
        {"kind": "واقعة", "is_reference": False, "text": "واقعة مسندة عادية"},
    ]
    ok_suff2, reason_suff2 = article._sufficiency(mixed_grounded, cfg)
    check("_sufficiency: مزيج تقرير منقول وواقعة عادية يجتاز أيضًا (واقعة مسندة "
          "واحدة على الأقل موجودة أصلًا)",
          ok_suff2 is True, reason_suff2)

    empty_grounded: list = []
    ok_suff3, reason_suff3 = article._sufficiency(empty_grounded, cfg)
    check("_sufficiency: صفر وقائع مسندة ← الشرط الوحيد الباقي يرفض (لا مادة للمقال)",
          ok_suff3 is False, reason_suff3)

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
    template = article.DRAFT_SYSTEM_TEMPLATE.format(opinion_phrase="x", editor_tag_phrase="y")
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
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images
    # بلا سند إطلاقًا هنا (الشاهد يفحص top_candidates لا نجاح المقال) —
    # الضمان (Issue #835، البند 2) يصوغ مسودة من الموجز نفسه؛ تُزيَّف
    # مراحل الصياغة/الصورة فقط لإتمام التشغيلة بلا نداء شبكة حقيقي
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار المرشّحين؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختبار رصد المرشّحين بحسب معلومات المحرر.",
         "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []

    try:
        out = article._write_article("موجز اختبار رصد المرشّحين", 9002, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        extract.gather = real_extract_gather
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images

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
    مرة. التحقق: evidence.search/gather_evidence لا تُستدعيان لكل نص استعلام
    فعلي إلا مرة واحدة مهما تكرر عبر الوقائع الثلاث، بينما _support_sources
    تبقى تُستدعى لكل واقعة (ولكل محاولة سُلَّم — Issue #808، البند 3: سند
    غير كافٍ يُصعِّد للمحاولة التالية) بمعزل عن التخزين المؤقَّت — الحكم على
    السند لا يُشارَك، الوثائق المقروءة وحدها تُشارَك."""
    from src import article

    cfg = load_config()
    # اختبار هشّ إن اعتمد على قيمة config.yaml الافتراضية القابلة للتبديل
    # (نظير include_opinion، Issue #373) — يُضبط صراحة false هنا لأن هذه
    # الدالة لا تفحص مرحلة استخراج وقائع المصادر
    cfg["article"]["source_extract_enabled"] = False

    shared_entities = ["سهيلة الطاهري", "روبرتو كارلوس"]
    # الرقم المميِّز ({i}) يقع عمدًا بعد سقف query_max_words=5 الافتراضي في
    # نصّ المحاولة الثانية (النص وحده بلا بادئة الكيانات) — فيبني build_query
    # نفس الاستعلام الحرفي لهذه المحاولة عبر الوقائع الثلاث معًا (تحقَّق
    # ببرمجية فعلية، لا افتراضًا)، مختلفًا عن استعلام المحاولة الأولى
    # (المركَّبة بالكيانات) لكنه مستقر بذاته عبر الوقائع أيضًا — فسند غير
    # كافٍ دومًا (Issue #808، البند 3) يُصعِّد كل واقعة لمحاولتها الثانية،
    # لكن هذا لا يعني استعلامًا جديدًا فعليًا لكل واقعة: search_cache يمنع
    # القراءة المكرَّرة لنفس النص حتى عبر محاولات/وقائع مختلفة
    fact_texts = [f"زار الوفد المدينة صباحًا اليوم بخصوص واقعة رقم {i}"
                 for i in range(1, 4)]

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
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images
    # بلا سند إطلاقًا لأي واقعة (الشاهد يفحص التخزين المؤقَّت لا نجاح
    # المقال) — الضمان (Issue #835، البند 2) يصوغ مسودة من الموجز نفسه؛
    # تُزيَّف مراحل الصياغة/الصورة فقط لإتمام التشغيلة بلا نداء شبكة حقيقي
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار الإعادة؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختبار إعادة الاستعلام بحسب معلومات المحرر.",
         "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []

    try:
        out = article._write_article("موجز اختبار إعادة استعمال الاستعلام", 9005, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images

    check("إعادة استعمال الاستعلام: evidence.search استُدعيت مرتين فقط (نصّا "
          "المحاولتين المختلفان) لثلاث وقائع تشترك فيهما كليهما — لا ست مرات",
          len(search_calls) == 2, search_calls)
    check("إعادة استعمال الاستعلام: evidence.gather_evidence استُدعيت مرتين فقط "
          "بالمثل",
          len(gather_calls) == 2, gather_calls)
    check("إعادة استعمال الاستعلام: _support_sources تُستدعى لكل واقعة بنصها "
          "الخاص، مرتين لكل واحدة (محاولتا السُلَّم كلتاهما — Issue #808) — "
          "الحكم على السند يبقى مستقلًا رغم مشاركة الوثائق",
          support_calls == [t for t in fact_texts for _ in range(2)], support_calls)

    fact_trail = [t for t in out["trail"] if t["stage"] == "واقعة"]
    check("trail: ثلاثة أسطر — واحد لكل واقعة — بلا حذف أي سطر رغم إعادة الاستعمال "
          "(الشفافية أهم من اختصار السجل)",
          len(fact_trail) == 3, fact_trail)
    check("trail: استعلام المحاولة الثانية (الأخيرة) نفسه حرفيًا في الأسطر الثلاثة",
          len({t["query"] for t in fact_trail}) == 1, fact_trail)
    check("trail: كل الأسطر الثلاثة سجّلت المحاولة الثانية (تصعيد بسبب سند "
          "غير كافٍ في الأولى دومًا)",
          all(t.get("search_attempt") == 2 for t in fact_trail), fact_trail)
    check("trail: السطر الأول غير مُعاد (أول استعمال فعلي لاستعلام المحاولة "
          "الثانية هذا تحديدًا)",
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
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images
    # مصدر مستقل واحد فقط يبقى بعد الاستبعاد (Issue #835): درجة ب لا سقوط —
    # يدخل المقال منسوبًا لاسم المصدر الباقي. تُزيَّف مراحل الصياغة/الصورة
    # فقط لإتمام التشغيلة، والمتن يذكر اسم المصدر إجابةً لمتطلب النسبة
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار الاستبعاد؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختبار الاستبعاد بحسب ناشر مستقل.", "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []

    try:
        out = article._write_article(body, 9006, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images

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

    # مصدر مستقل واحد فقط بعد الاستبعاد لم يعد يُسقِط الواقعة (Issue #835):
    # درجة ب — تدخل المقال منسوبة لاسم ذلك المصدر الباقي وحده، لا dropped
    check("استبعاد إعادة النشر: الواقعة لم تسقط — مصدر مستقل واحد بعد الاستبعاد "
          "يكفي درجة ب (Issue #835)",
          out["dropped"] == [], out["dropped"])
    check("استبعاد إعادة النشر: الواقعة دخلت المقال درجة ب منسوبة لاسم المصدر الباقي "
          "وحده (لا المُستبعَد)",
          any(g["grade"] == "B" and g.get("attribution_name") == "ناشر مستقل"
              for g in out["fact_grades"]),
          out["fact_grades"])

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
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    # "ذُكر وطابق جزئيًا" تطابق مصدرًا مستقلًا واحدًا (Issue #835): درجة ب —
    # لا تسقط، فالمسار يبلغ الصياغة فعليًا هذه المرة (خلافًا لسابق هذا
    # الاختبار حيث كانت الوقائع الثلاث تسقط كلها) — تُزيَّف الصياغة فقط
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار mentioned؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختبار mentioned بحسب Daily Sabah.", "hashtags": ["اختبار"]}, "")

    try:
        out_full = article._write_article("موجز اختبار mentioned", 9001, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article.find_images = real_find_images
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article

    dropped_by_text = {d["text"]: d["reason"] for d in out_full["dropped"]}
    check("لا ذكر إطلاقًا: رسالة السقوط تفيد أن لا مصدر مقروء ذكر الموضوع إطلاقًا",
          "لم يذكر أي من المصادر المقروءة الموضوع إطلاقًا" in dropped_by_text.get("لا ذكر إطلاقًا", ""),
          dropped_by_text.get("لا ذكر إطلاقًا"))
    check("ذُكر ولم يطابق: رسالة السقوط تذكر عدد من ذكروا الموضوع بلا أي تأييد",
          "ذكره 2 مصدر لكن لم يطابق مضمونه أيٌّ منها" in dropped_by_text.get("ذُكر ولم يطابق", ""),
          dropped_by_text.get("ذُكر ولم يطابق"))
    # "ذُكر وطابق جزئيًا" طابقها مصدر مستقل واحد (Daily Sabah) — لم تعد تسقط
    # (Issue #835): درجة ب، تدخل المقال منسوبة لا في dropped
    check("ذُكر وطابق جزئيًا: لم تسقط — مصدر مستقل واحد يكفي درجة ب",
          "ذُكر وطابق جزئيًا" not in dropped_by_text, dropped_by_text)
    check("ذُكر وطابق جزئيًا: دخلت المقال درجة ب منسوبة لـDaily Sabah",
          any(g["text"] == "ذُكر وطابق جزئيًا" and g["grade"] == "B" and
              g.get("attribution_name") == "Daily Sabah"
              for g in out_full["fact_grades"]),
          out_full["fact_grades"])

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
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    # ثلاث من الوقائع الأربع تُطابَق بمصدر مستقل واحد (Daily Sabah) — درجة ب
    # (Issue #835): لم تعد تسقط، فالملاحظة التقنية (Issue #583) صارت تظهر
    # على سطر trail نفسه (المعلومة تبقى مفيدة رغم أن الواقعة لم تعد تسقط —
    # قد تستحق درجة أ حقًّا لو لم يفشل الجلب) لا في رسالة سقوط لم تعد تقع
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار الفجوة؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختبار فجوة الجلب بحسب Daily Sabah.", "hashtags": ["اختبار"]}, "")

    try:
        out = article._write_article("موجز اختبار فجوة فشل الجلب", 9002, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article.find_images = real_find_images
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article

    dropped_by_text = {d["text"]: d["reason"] for d in out["dropped"]}
    fact_trail = [t for t in out["trail"] if t["stage"] == "واقعة"]
    check("أربعة أسطر trail — واحد لكل واقعة", len(fact_trail) == 4, fact_trail)
    gap_note = "سقط مرشّح ثانٍ بفشل جلب — الواقعة كانت ستُسنَد"
    check("واقعة 1/2 بمرشّح ثانٍ فشل جلبه (ناشر مختلف) — درجة ب، والملاحظة التقنية "
          "تظهر على سطر trail رغم أنها لم تعد تسقط (Issue #835)",
          gap_note in fact_trail[0]["outcome"], fact_trail[0])
    check("واقعة 1/2 بلا فشل جلب — درجة ب بلا ملاحظة",
          gap_note not in fact_trail[1]["outcome"], fact_trail[1])
    check("واقعة 0/2 رغم فشل جلب مرشّح — تسقط فعليًا (لا وقائع أخرى تدخل حوض الضمان "
          "بما يكفي لتغييرها) ولا ملاحظة (فشل مرشّح واحد لا يسدّ فجوة أكبر من واقعة)",
          "واقعة صفر مصادر" in dropped_by_text and
          gap_note not in dropped_by_text.get("واقعة صفر مصادر", ""),
          dropped_by_text.get("واقعة صفر مصادر"))
    check("واقعة 1/2 بمرشّح فشل جلبه هو الناشر المؤيِّد بالفعل — درجة ب بلا ملاحظة "
          "(تكرار لا سند إضافي)",
          gap_note not in fact_trail[3]["outcome"], fact_trail[3])
    check("الوقائع الثلاث (درجة ب) لم تسقط — دخلت المقال منسوبة لـDaily Sabah",
          all(text not in dropped_by_text for text in
              ("واقعة بمرشّح ثانٍ فاشل", "واقعة بلا فشل جلب", "واقعة بمرشّح فاشل مكرر")),
          dropped_by_text)

def test_article_snippet_only_sources() -> None:
    """مقتطف بدل إسقاط كلي عند فشل الجلب (Issue #895): مرشّح فشل جلب نصّه
    الكامل فعليًا (٤٠٣/٤٠١/صفحة اشتراك) رغم نجاح قراءة مرشّح آخر لا يُسقَط
    كليًا من evidence.gather_evidence بعد الآن — يبقى في docs كمقتطف
    (عنوان+ملخص) مُعلَّم snippet_only=True صراحة (انظر الإضافة على test_evidence
    لاختبار evidence.gather_evidence مباشرة).

    القاعدة الحاسمة المختبرة هنا على مستوى article.py: المقتطف يُثبت أن
    المصدر ذكر الموضوع فقط — يُحتسب في «ذكره N مصدر» — ولا يُحتسب إطلاقًا
    في «طابق مضمونه» ولا في عدّ المصادر المستقلة المؤيِّدة، فلا يدخل فحص
    الأصالة ولا extra_docs، وأي واقعة سندها الوحيد مقتطفات لا تدخل المقال
    ولا بالدرجة ب."""
    from src import article, verify_draft

    cfg = load_config()
    cfg["article"]["source_extract_enabled"] = False

    real_doc = {"name": "Daily Sabah", "text": "نص كامل مقروء فعليًا من Daily Sabah",
               "link": "https://s1/1", "from_text": True, "snippet_only": False}
    snippet_doc_ys = {"name": "Yeni Şafak", "text": "عنوان Yeni Şafak. ملخص Yeni Şafak",
                      "link": "https://s2/1", "from_text": False, "snippet_only": True}
    snippet_doc_ds = {"name": "Daily Sabah", "text": "عنوان Daily Sabah. ملخص Daily Sabah",
                      "link": "https://s1/2", "from_text": False, "snippet_only": True}
    docs_by_claim = {
        "كB1": [real_doc, snippet_doc_ys],
        "كC1": [snippet_doc_ds, snippet_doc_ys],
    }

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images
    real_check_orig = verify_draft._check_originality_full

    captured_extra_docs: list[list[dict]] = []

    def _fake_check_orig(*args, **kwargs):
        captured_extra_docs.append(list(kwargs.get("extra_docs") or []))
        return real_check_orig(*args, **kwargs)

    def _fake_support(fact_text, docs, cfg, is_statement=False, is_report=False, publisher=""):
        # يحاكي عقد _support_sources الحقيقي بعد Issue #895: snippet_only
        # لا تدخل الحكم على المضمون إطلاقًا (نظير استبعادها من _format_docs
        # الحقيقية) — mentioned تبقى فارغة هنا عمدًا لأن article.py نفسه
        # يضيف أسماء snippet_only إلى fact_mentioned يدويًا من docs الأصلية
        # لا من نتيجة _support_sources (انظر التعديل في _check_fact)
        return article._ModelCallList(d["name"] for d in docs if not d.get("snippet_only"))

    evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
    evidence.gather_evidence = lambda articles, cfg, claim_text="": (
        list(docs_by_claim.get(claim_text, [])), evidence.EVIDENCE_FULL_TEXT)
    article._support_sources = _fake_support
    article.find_images = lambda title, cfg, terms=None: []
    verify_draft._check_originality_full = _fake_check_orig
    article.extract_brief = lambda body, cfg, retries=3: ({
        "topic": "اختبار مقتطف فقط",
        "statements": [
            {"text": "واقعة بمصدر مقروء ومقتطف", "kind": "واقعة", "entities": ["كB1"],
             "is_unnamed_event": False, "is_reference": False},
            {"text": "واقعة سندها مقتطفان فقط", "kind": "واقعة", "entities": ["كC1"],
             "is_unnamed_event": False, "is_reference": False},
        ],
        "questions": [],
    }, None)
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار المقتطف؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختبار المقتطف بحسب Daily Sabah.", "hashtags": ["اختبار"]}, "")

    try:
        out = article._write_article("موجز اختبار مقتطف فقط", 9004, cfg)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article.find_images = real_find_images
        verify_draft._check_originality_full = real_check_orig
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article

    dropped_by_text = {d["text"]: d["reason"] for d in out["dropped"]}
    check("واقعة بمصدر مقروء ومقتطف: لم تسقط",
          "واقعة بمصدر مقروء ومقتطف" not in dropped_by_text, dropped_by_text)
    check("واقعة بمصدر مقروء ومقتطف: دخلت المقال درجة ب منسوبة إلى Daily Sabah "
          "وحده — المقتطف (Yeni Şafak) لم يرفعها إلى درجة أ",
          any(g["text"] == "واقعة بمصدر مقروء ومقتطف" and g["grade"] == "B" and
              g.get("attribution_name") == "Daily Sabah" for g in out["fact_grades"]),
          out["fact_grades"])
    check("واقعة سندها مقتطفان فقط: تسقط فعليًا — لا تدخل المقال ولا بالدرجة ب "
          "رغم أن مصدرين ذكرا الموضوع",
          "واقعة سندها مقتطفان فقط" in dropped_by_text, dropped_by_text)
    check("واقعة سندها مقتطفان فقط: لا تدخل fact_grades بأي درجة من الدرجات الثلاث",
          not any(g["text"] == "واقعة سندها مقتطفان فقط" for g in out["fact_grades"]),
          out["fact_grades"])
    check("واقعة سندها مقتطفان فقط: رسالة السقوط تُحصي المصدرين في «ذكره N مصدر» "
          "(يُحتسبان في الذكر لا في السند)",
          "ذكره 2 مصدر" in dropped_by_text.get("واقعة سندها مقتطفان فقط", ""),
          dropped_by_text)

    check("check_originality: extra_docs يستبعد كل وثيقة snippet_only كليًا "
          "(اسمًا ونصًّا) — لا يدخلها فحص الأصالة",
          all(d["name"] != "Yeni Şafak" for ed in captured_extra_docs for d in ed) and
          all("Yeni Şafak" not in (d.get("text") or "")
              for ed in captured_extra_docs for d in ed) and
          all("عنوان Daily Sabah" not in (d.get("text") or "")
              for ed in captured_extra_docs for d in ed),
          captured_extra_docs)
    check("check_originality: extra_docs يحوي النص الكامل الحقيقي المقروء "
          "(Daily Sabah) لا مقتطفه",
          any(d["name"] == "Daily Sabah" and
              d["text"] == "نص كامل مقروء فعليًا من Daily Sabah"
              for ed in captured_extra_docs for d in ed),
          captured_extra_docs)

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
    # duplicate_index فقط في رد النموذج، بلا on_topic/on_topic_reason — هذا
    # الاختبار يفحص حكم التكرار حصرًا؛ حكم الموضوع (Issue #824) له اختباره
    # الخاص في test_article_source_fact_duplicate_index_on_topic. غياب
    # الحقلين يفشل مفتوحًا (on_topic=True) بتصميم الدالة، لا يكسر هنا
    article._client = lambda: _FakeClient({"duplicate_index": 0})
    dup1 = article._source_fact_duplicate_index(
        "توغّلت قوات الحكومة داخل المدينة الخميس عقب اشتباكات قصيرة",
        ["دخلت القوات الحكومية المدينة يوم الخميس بعد معارك محدودة"], cfg)
    check("١) نفس الحدث بصياغتين مختلفتين ← duplicate=True برقم الواقعة الأصلية",
          dup1 == {"duplicate": True, "index": 0, "call_error": None,
                  "on_topic": True, "on_topic_reason": ""}, dup1)

    # (ب) حدثان متمايزان يشتركان في الفاعل نفسه — يجب ألا يُدمَجا (المعيار:
    # الفعل/الحدث نفسه لا الكيانات المشتركة وحدها)
    article._client = lambda: _FakeClient({"duplicate_index": -1})
    dup2 = article._source_fact_duplicate_index(
        "التقى الرئيس بوزير الخارجية يوم الجمعة لبحث ملف الطاقة",
        ["زار الرئيس المدينة يوم الخميس"], cfg)
    check("٢) حدث مختلف يشارك الفاعل نفسه مع واقعة سابقة ← duplicate=False، لا يُدمَج",
          dup2 == {"duplicate": False, "index": None, "call_error": None,
                  "on_topic": True, "on_topic_reason": ""}, dup2)

    dup_empty = article._source_fact_duplicate_index("أي نص", [], cfg)
    check("قائمة وقائع سابقة فارغة ← duplicate=False بلا نداء نموذج (اختصار مبكر)",
          dup_empty == {"duplicate": False, "index": None, "call_error": None,
                       "on_topic": True, "on_topic_reason": ""})

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
    # عمدًا، بحصيلة نهائية غير متعلّقة بها (واقعة مصدر واحدة فقط تدخل
    # grounded). القاعدة 7 (الحدّ الأدنى العددي) أُلغيت (Issue #814 جزء 1)
    # فواقعة واحدة كافية الآن لإتمام المسار كاملًا -- الصياغة/الصورة مزيَّفتان
    # أدناه فقط لإتمام التشغيلة بلا نداء شبكة حقيقي، غير مرتبطتين بما هذا
    # الاختبار يفحصه فعليًا (حصيلة استخراج المصادر أعلاه) ──
    cfg_on = load_config()
    cfg_on["article"] = {**cfg_on["article"], "source_extract_enabled": True}

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_extract_source_facts = article._extract_source_facts
    real_dup_index = article._source_fact_duplicate_index
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images

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
            # صفر مصادر لا مصدر واحد (Issue #835: مصدر واحد صار درجة ب —
            # يدخل المقال منسوبًا لا يسقط) — يسقط عمدًا لعزل ما يفحصه هذا
            # الاختبار فعليًا (استخراج وقائع المصادر) عن آلية الدرجات
            return []
        return ["Defensehere", "Daily Sabah"]

    def _fake_extract_source(topic, brief_texts, docs, cfg):
        return article._ModelCallList([
            {"text": duplicate_source_text, "entities": ["بايكار"]},
            {"text": new_source_text, "entities": ["بايكار", "بيرقدار"]},
        ])

    def _fake_dup(candidate_text, existing_texts, cfg, topic=""):
        if candidate_text == duplicate_source_text:
            return {"duplicate": True, "index": 0, "call_error": None,
                    "on_topic": True, "on_topic_reason": ""}
        return {"duplicate": False, "index": None, "call_error": None,
                "on_topic": True, "on_topic_reason": ""}

    article._support_sources = _fake_support
    article._extract_source_facts = _fake_extract_source
    article._source_fact_duplicate_index = _fake_dup
    # القاعدة 7 أُلغيت (Issue #814 جزء 1): واقعة مصدر واحدة (new_source_text)
    # كافية الآن لإتمام المسار كاملًا -- تُزيَّف مرحلتا الصياغة والصورة فقط
    # كي تكتمل التشغيلة بلا نداء شبكة/نموذج حقيقي، بلا صلة بما يُفحَص هنا
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار بايراكتار؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختبار بايراكتار يجيب عن السؤال بوضوح.",
         "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []

    try:
        out = article._write_article("موجز اختبار بايراكتار", 9002, cfg_on)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article._extract_source_facts = real_extract_source_facts
        article._source_fact_duplicate_index = real_dup_index
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images

    check("التكامل: الواقعة الأصلية (بلا أي مصدر) سقطت كما صُمِّم الاختبار",
          any(d["text"] == brief_fact_text for d in out.get("dropped", [])), out.get("dropped"))
    source_texts = [f["text"] for f in out.get("source_origin_facts", [])]
    check("التكامل: الواقعة المكرَّرة (نفس الحدث بصياغة مختلفة) لم تدخل المقال إطلاقًا",
          duplicate_source_text not in source_texts, source_texts)
    check("التكامل: الواقعة الجديدة الفعلية دخلت المقال بوسم origin=source",
          new_source_text in source_texts, source_texts)
    check("التكامل: ملخّص الاستخراج (البند 5) — 2 استُخرجت، 1 اندمجت، 0 خارج الموضوع، 1 أُضيفت",
          out["source_facts_summary"] == {"extracted": 2, "merged": 1, "off_topic": 0,
                                          "same_entity_off_topic": 0, "added": 1},
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

    def _fake_dup_counting(candidate_text, existing_texts, cfg, topic=""):
        dup_calls.append(candidate_text)
        return {"duplicate": False, "index": None, "call_error": None,
                "on_topic": True, "on_topic_reason": ""}

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
            # صفر مصادر لا مصدر واحد (Issue #835)، كالاختبار الأول — يسقط
            # عمدًا لعزل ما يفحصه هذا الاختبار عن آلية الدرجات. واقعة المصدر
            # الجديدة وحدها تكفي الآن لإتمام المسار (القاعدة 7 أُلغيت) —
            # _choose_question/_draft_article/find_images مزيَّفة أدناه فقط
            # لإتمام التشغيلة، غير مرتبطة بما يفحصه هذا الاختبار فعليًا
            return []
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
    article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار بايراكتار ٢؟", "")
    article._draft_article = lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
        {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
         "image_headline": "عنوان", "post_title": question,
         "post_body": "متن اختبار بايراكتار ٢ يجيب عن السؤال بوضوح.",
         "hashtags": ["اختبار"]}, "")
    article.find_images = lambda title, cfg, terms=None: []

    try:
        out2 = article._write_article("موجز اختبار بايراكتار ٢", 9003, cfg_on)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article._extract_source_facts = real_extract_source_facts
        article._source_fact_duplicate_index = real_dup_index
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images

    check("لا بحث جديد لوقائع المصادر: evidence.search استُدعيت مرة واحدة فقط "
          "لواقعة الموجز الوحيدة — سند مصدر واحد غير كافٍ يُصعِّد محاولتها الثانية "
          "(Issue #808، البند 3) لكن محاولتيها تبنيان الاستعلام الحرفي نفسه هنا "
          "(كيان بايكار المفرد يتكرر داخل نص الواقعة نفسه) فتُخزَّن الثانية مؤقَّتًا "
          "— لا مرة إضافية على أي حال لأي من الواقعتين المستخرَجتين من المصادر",
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

def test_article_draft_investigation() -> None:
    """منشور «تحقيق» من outcome._write_article نفسه (Issue #765): يُصاغ من
    report_statements المؤكَّدة/dropped/diffs/sources/question حصرًا --
    القيد البنيوي الملزم (نظير رأس verify_draft.py) هو التوقيع نفسه: لا
    يقبل body إطلاقًا، لا مراجعة يدوية تضمن ذلك. نجاح المقال أو فشله
    (outcome['produced']) لا يمنع محاولة صياغة التحقيق (Issue #814 جزء 1) --
    الشرط الوحيد المانع هو dropped/diffs فارغان معًا (لا شيء يستحق تحقيقًا)."""
    from src import article

    sig_params = inspect.signature(article.draft_investigation).parameters
    check("draft_investigation: التوقيع لا يقبل body إطلاقًا -- ضمان بنيوي "
          "نظير verify_draft._draft_from_facts",
          "body" not in sig_params, list(sig_params))

    cfg = load_config()

    def _base_outcome(**overrides) -> dict:
        out = article._new_outcome()
        out.update({
            "produced": True, "reason": "صيغ مقال اختباري", "draft_id": "art00000001",
            "question": "هل وقع الحدث فعلًا؟",
            "sources": [{"name": "مصدر أول", "link": "https://s1/1"},
                       {"name": "مصدر ثانٍ", "link": "https://s2/1"}],
            "report_statements": [
                {"publisher": "منصة تقارير", "text": "نشرت منصة تقارير أن كذا وقع",
                 "sources": [{"name": "ناقل مستقل", "link": "https://c/1", "kind": "carrier"}]},
            ],
            "dropped": [
                {"text": "ادّعى الموجز أن شخصًا مجهولًا فعل كذا",
                 "reason": "سند غير كافٍ (0 من 2 مصادر مستقلة مطلوبة)"},
            ],
            "diffs": [
                {"brief": "الموجز قال إن الحدث وقع في المكان أ",
                 "sources_say": "المصادر المستقلة تقول إنه وقع في المكان ب"},
            ],
        })
        out.update(overrides)
        return out

    real_draft_text = article._draft_investigation_text
    real_unsourced = article._unsourced_entities
    real_find_images = article.find_images
    # يُعزَل فحص _unsourced_entities هنا عمدًا (يعيد [] دومًا): هذا الاختبار
    # يغطي إعادة المحاولة على الكلمة النافية الممنوعة تحديدًا (القاعدة 1)
    # بمعزل عن حساسية مطابقة الكيانات النصية (القاعدة 2، مغطاة سلوكيًا عبر
    # _investigation_known_facts نفسها بلا حاجة لصياغة فعلية من نموذج).
    article._unsourced_entities = lambda *a, **k: []
    article.find_images = lambda topic, cfg, terms=None: []

    try:
        # ── dropped وdiffs فارغان معًا: لا شيء يستحق تحقيقًا -- None بلا أي
        # نداء صياغة إطلاقًا ──
        calls_none: list = []

        def _record_none(*a, **k):
            calls_none.append(1)
            return None, ""

        article._draft_investigation_text = _record_none
        out_empty = _base_outcome(dropped=[], diffs=[])
        result_empty = article.draft_investigation(out_empty, cfg)
        check("draft_investigation: dropped وdiffs فارغان معًا ← None بلا أي نداء صياغة",
              result_empty is None and not calls_none, (result_empty, calls_none))

        # ── فشل المقال (produced=False) لا يمنع محاولة صياغة تحقيق (Issue
        # #814 جزء 1) — dropped/diffs غير فارغين هنا (افتراضيًا في
        # _base_outcome)، فالتحقيق يُحاول ويُنتَج فعلًا بصرف النظر عن نجاح
        # المقال أو فشله ──
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        calls_failed: list = []

        def _record_failed(*a, **k):
            calls_failed.append(1)
            return ({"angle": "تحقيق", "analysis": "", "urgent": False, "category": "عالم",
                    "image_headline": "عنوان تحقيق", "post_title": "عنوان تحقيق",
                    "post_body": "لم نجد مصدرًا مستقلًا يؤكد بعض ما ورد في الموجز.",
                    "hashtags": ["تحقيق"]}, "")

        article._draft_investigation_text = _record_failed
        out_failed = _base_outcome(produced=False, draft_id=None)
        result_failed = article.draft_investigation(out_failed, cfg)
        check("draft_investigation: فشل المقال (produced=False) لا يمنع محاولة صياغة "
              "تحقيق فعلية — dropped/diffs غير فارغين هنا",
              len(calls_failed) >= 1 and result_failed is not None,
              (result_failed, calls_failed))
        check("draft_investigation: عند produced=False بلا draft_id (لا مقال محفوظ)، "
              "sibling_id يبقى None بلا محاولة ربط تكسر شيئًا",
              result_failed is not None and result_failed.get("sibling_id") is None,
              result_failed)

        # ── مخرَج فيه كلمة نافية ممنوعة (القاعدة 1) يُرفض ويُعاد المحاولة؛
        # نجاح المحاولة الثانية يُنتج مسودة فعلية ──
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        article_draft = {
            "id": "art00000001", "status": "pending", "origin": "article",
            "bucket": "serious",
            "image": "drafts/2026-01-01/art00000001.jpg",
            "arabic": {"post_title": "عنوان المقال", "category": "عالم"},
            "caption": "متن المقال", "source": {"publishers": ["مصدر أول"]},
        }
        store.save_draft(article_draft)

        forbidden_calls: list = []

        def _forbidden_then_ok(report_statements, dropped, diffs, sources, question, cfg,
                               retries=3, avoid_note=""):
            forbidden_calls.append(avoid_note)
            body = ("هذا الادّعاء كاذب ومفبرك بالكامل." if len(forbidden_calls) == 1
                    else "لم نجد مصدرًا مستقلًا يؤكد هذا الادّعاء.")
            return ({"angle": "تحقيق", "analysis": "", "urgent": False, "category": "عالم",
                    "image_headline": "عنوان تحقيق", "post_title": "عنوان تحقيق",
                    "post_body": body, "hashtags": ["تحقيق"]}, "")

        article._draft_investigation_text = _forbidden_then_ok
        out_ok = _base_outcome()
        result_ok = article.draft_investigation(out_ok, cfg)

        check("draft_investigation: كلمة نافية ممنوعة (كاذب/مفبرك) في المحاولة الأولى "
              "تُرفض وتُعاد المحاولة مرة واحدة",
              len(forbidden_calls) == 2, forbidden_calls)
        check("draft_investigation: المحاولة الأولى بلا توجيه تفادٍ (avoid_note فارغ)",
              forbidden_calls[0] == "", forbidden_calls)
        check("draft_investigation: توجيه المحاولة الثانية غير فارغ",
              bool(forbidden_calls[1]), forbidden_calls)
        check("draft_investigation: المحاولة الثانية (بلا كلمة نافية) تُنتج مسودة فعلية",
              result_ok is not None, result_ok)

        if result_ok is not None:
            check("draft_investigation: المسودة الناتجة تحمل sibling_id بمعرّف المقال",
                  result_ok["sibling_id"] == "art00000001", result_ok.get("sibling_id"))
            reloaded_article = store.load_draft("art00000001")[1]
            check("draft_investigation: مسودة المقال حُدِّثت بـsibling_id بمعرّف "
                  "منشور التحقيق -- sibling_id متبادل بين المسودتين",
                  reloaded_article.get("sibling_id") == result_ok["id"],
                  (reloaded_article.get("sibling_id"), result_ok["id"]))
            check("draft_investigation: origin يبقى \"article\" كما اليوم (يصير "
                  "investigation في شريحة لاحقة، لا الآن)",
                  result_ok["origin"] == "article", result_ok["origin"])
            check("draft_investigation: is_investigation=True (علامة داخلية للنشر، "
                  "بند 3)",
                  result_ok.get("is_investigation") is True, result_ok.get("is_investigation"))
            check("draft_investigation: status=pending -- لا نشر تلقائي بحال",
                  result_ok["status"] == "pending", result_ok["status"])

            report = article.build_report(out_ok, result_ok)
            check("build_report: يذكر معرّف مسودة المقال",
                  "art00000001" in report, report)
            check("build_report: يذكر معرّف منشور التحقيق أيضًا -- سطر لكل مسودة",
                  result_ok["id"] in report, report)

        # ── فشل نهائي (كلمة نافية في المحاولتين معًا) لا يُسقط مسودة المقال
        # المحفوظة سلفًا -- والعكس أيضًا (فشل المقال أعلاه لا صلة له بهذا) ──
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        store.save_draft(article_draft)

        def _always_forbidden(report_statements, dropped, diffs, sources, question, cfg,
                              retries=3, avoid_note=""):
            return ({"angle": "تحقيق", "analysis": "", "urgent": False, "category": "عالم",
                    "image_headline": "عنوان", "post_title": "عنوان تحقيق",
                    "post_body": "هذا الادّعاء كاذب.", "hashtags": []}, "")

        article._draft_investigation_text = _always_forbidden
        out_bad = _base_outcome()
        result_bad = article.draft_investigation(out_bad, cfg)

        check("draft_investigation: فشل الفحص البنيوي في المحاولتين معًا ← امتناع نهائي "
              "(None)",
              result_bad is None, result_bad)
        reloaded_article_2 = store.load_draft("art00000001")[1]
        check("draft_investigation: فشل صياغة التحقيق لا يُسقط مسودة المقال المحفوظة "
              "سلفًا -- تبقى pending كما هي",
              reloaded_article_2 is not None and reloaded_article_2.get("status") == "pending",
              reloaded_article_2)
    finally:
        article._draft_investigation_text = real_draft_text
        article._unsourced_entities = real_unsourced
        article.find_images = real_find_images

def test_article_no_min_facts_gate() -> None:
    """Issue #814 (جزء 1 من 3) ثم Issue #835 (البند 2): مسار المقال لا يمتنع
    لقلة الوقائع أو لانعدام سندها بعد الآن — القاعدة 7 وضابطاها أُلغيت من
    _sufficiency، ومنشور التحقيق يُنتَج بصرف النظر عن نجاح المقال. Issue
    #835 ذهب أبعد: حتى صفر وقائع مسندة لم تعد تعني "لا مقال" — يُصاغ من
    وقائع الموجز نفسها (درجة ج، fallback_to_brief). الامتناع الوحيد الباقي
    هنا هو غياب مادة من الأصل (موجز لا يحمل ولا واقعة واحدة قابلة للتحقق،
    رأي فقط) — لا "أدلة غير كافية". تكامل كامل عبر _write_article +
    draft_investigation يثبت سيناريوهَين: بلا أي واقعة إطلاقًا (منشور تحقيق
    وحده بلا انهيار)، وواقعة مسندة واحدة (منشوران مترابطان بـsibling_id)."""
    from src import article

    cfg = load_config()
    cfg["article"]["source_extract_enabled"] = False

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images
    real_draft_investigation_text = article._draft_investigation_text
    real_unsourced_entities = article._unsourced_entities

    def _fake_search(query, cfg, days, unrestricted=False):
        return [object()]

    def _fake_gather_evidence(articles, cfg, claim_text=""):
        return ([{"name": "مصدر أول", "text": "نص", "link": "https://s1/1", "from_text": True},
                 {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1", "from_text": True}],
                evidence.EVIDENCE_FULL_TEXT)

    evidence.search = _fake_search
    evidence.gather_evidence = _fake_gather_evidence
    article._unsourced_entities = lambda *a, **k: []
    article.find_images = lambda title, cfg, terms=None: []
    article._draft_investigation_text = (
        lambda report_statements, dropped, diffs, sources, question, cfg,
        retries=3, avoid_note="": (
            {"angle": "تحقيق", "analysis": "", "urgent": False, "category": "عالم",
             "image_headline": "عنوان تحقيق", "post_title": "عنوان تحقيق",
             "post_body": "لم نجد مصدرًا مستقلًا يؤكد بعض ما ورد في الموجز.",
             "hashtags": ["تحقيق"]}, ""))

    try:
        # ── سيناريو 1: موجز بلا أي واقعة قابلة للتحقق (رأي فقط) ← لا مادة
        # للمقال إطلاقًا (غياب مادة من الأصل، لا "أدلة غير كافية" — Issue
        # #835 ألغى حتى امتناع صفر السند: انظر سيناريو 3 أدناه) — منشور
        # تحقيق وحده بلا انهيار، لا رسالة فشل (reason يذكرها نتيجة صحيحة) ──
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

        article.extract_brief = lambda body, cfg, retries=3: ({
            "topic": "اختبار بلا وقائع",
            "statements": [
                {"text": "رأي بلا أي واقعة قابلة للتحقق", "kind": "رأي", "entities": [],
                 "is_unnamed_event": False, "is_reference": False},
            ],
            "questions": [],
        }, None)
        article._support_sources = (
            lambda fact_text, docs, cfg, is_statement=False, is_report=False, publisher="":
            ["مصدر أول"])  # لن تُستدعى إطلاقًا — لا وقائع تدخل حلقة السند

        outcome_zero = article._write_article("موجز بلا وقائع", 8141, cfg)
        check("بلا وقائع إطلاقًا: outcome['produced'] هو False -- غياب مادة من الأصل",
              outcome_zero["produced"] is False, outcome_zero["reason"])
        check("بلا وقائع إطلاقًا: outcome['grounded_count'] == 0",
              outcome_zero["grounded_count"] == 0, outcome_zero["grounded_count"])
        check("بلا وقائع إطلاقًا: dropped فارغة (لا واقعة حتى لتسقط)",
              outcome_zero["dropped"] == [], outcome_zero["dropped"])
        check("بلا وقائع إطلاقًا: fallback_to_brief == False (لا حوض ضمان — لا واقعة أصلًا)",
              outcome_zero["fallback_to_brief"] is False, outcome_zero)

        # لا dropped ولا diffs هنا (لا واقعة أصلًا لتسقط) — منشور التحقيق
        # يمتنع بالمثل (لا شيء يُحقَّق فيه)، لا انهيار: امتناع مزدوج صحيح،
        # لا "مقال امتنع لكن التحقيق نجح" كما في Issue #814 (تلك الحالة
        # تطلّبت وقائع سقطت فعليًا؛ هنا لا واقعة سقطت لتبدأ التحقيق منها)
        investigation_zero = article.draft_investigation(outcome_zero, cfg)
        check("بلا وقائع إطلاقًا: draft_investigation تمتنع أيضًا (لا dropped ولا diffs)",
              investigation_zero is None, investigation_zero)

        report_zero = article.build_report(outcome_zero, investigation_zero)
        check("بلا وقائع إطلاقًا: التقرير يذكر الامتناع بلا أي إشارة لمنشور تحقيق",
              "❌" in report_zero and "🔎" not in report_zero, report_zero)

        # ── سيناريو 2: واقعة واحدة مسندة ← منشوران (مقال وتحقيق) مترابطان ──
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

        article.extract_brief = lambda body, cfg, retries=3: ({
            "topic": "اختبار واقعة واحدة مسندة",
            "statements": [
                {"text": "واقعة مسندة وحيدة", "kind": "واقعة", "entities": ["ك1"],
                 "is_unnamed_event": False, "is_reference": False},
                {"text": "واقعة أخرى بمصدر واحد فقط تسقط", "kind": "واقعة", "entities": ["ك2"],
                 "is_unnamed_event": False, "is_reference": False},
            ],
            "questions": [],
        }, None)

        def _fake_support_one(fact_text, docs, cfg, is_statement=False, is_report=False,
                              publisher=""):
            if fact_text == "واقعة مسندة وحيدة":
                return ["مصدر أول", "مصدر ثانٍ"]
            # صفر مصادر لا مصدر واحد (Issue #835): مصدر واحد صار درجة ب —
            # يدخل المقال منسوبًا لا يسقط (انظر اختبار درجات الإسناد
            # المخصَّص) — هذا السيناريو يفحص فقط أن واقعة واحدة مسندة تكفي
            # لإتمام المسار (القاعدة 7)، فيبقى صفر المصادر هو الإسقاط
            # الحاسم غير الملتبس بأي آلية أخرى
            return []

        article._support_sources = _fake_support_one
        article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار؟", "")
        article._draft_article = (
            lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
                {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
                 "image_headline": "عنوان الصورة", "post_title": question,
                 "post_body": "متن الاختبار يجيب عن السؤال بوضوح تام كاملة.",
                 "hashtags": ["اختبار"]}, ""))

        outcome_one = article._write_article("موجز واقعة واحدة", 8142, cfg)
        check("واقعة واحدة مسندة: outcome['produced'] هو True -- القاعدة 7 القديمة أُلغيت",
              outcome_one["produced"] is True, outcome_one["reason"])
        check("واقعة واحدة مسندة: outcome['grounded_count'] == 1",
              outcome_one["grounded_count"] == 1, outcome_one["grounded_count"])

        investigation_one = article.draft_investigation(outcome_one, cfg)
        check("واقعة واحدة مسندة: draft_investigation تُنتج منشورًا ثانيًا أيضًا -- "
              "منشوران من تشغيلة واحدة",
              investigation_one is not None, investigation_one)
        if investigation_one is not None:
            check("واقعة واحدة مسندة: منشورا المقال والتحقيق مرتبطان بـsibling_id متبادل",
                  investigation_one["sibling_id"] == outcome_one["draft_id"], investigation_one)
            reloaded_article_one = store.load_draft(outcome_one["draft_id"])[1]
            check("واقعة واحدة مسندة: مسودة المقال حُدِّثت بـsibling_id معرّف التحقيق",
                  reloaded_article_one.get("sibling_id") == investigation_one["id"],
                  reloaded_article_one)
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images
        article._draft_investigation_text = real_draft_investigation_text
        article._unsourced_entities = real_unsourced_entities

def test_article_grading_tiers() -> None:
    """الدرجات الثلاث للإسناد (Issue #835): min_confirm_sources لم يعد
    بوابة قبول ثنائية — مصدر مستقل واحد (درجة ب) يدخل المقال منسوبًا لاسمه
    في المتن، لا يسقط؛ صفر مصادر (درجة ج) لا يدخل المقال إلا حين تخلو
    الدرجتان أ/ب معًا في التشغيلة كلها، فعندها يُصاغ المقال من الموجز نفسه
    موسومًا "بحسب معلومات المحرر" (الضمان، البند 2). النسبة تُفرض برمجيًا
    لا بالبرومبت وحده (_grade_attribution_ok): واقعة درجة ب/ج لا يظهر
    اسم/وسم نسبتها في المتن ⇐ إعادة نداء واحدة بتوجيه صريح ⇐ فشلت أيضًا ⇐
    تُسقَط هي وحدها لا المقال (البند 1). مسودة الدرجة ج لا تُنشر تلقائيًا
    بحال — status="pending" دومًا، نفس مسار المراجعة العادي (البند 2)."""
    from src import article

    cfg = load_config()
    cfg["article"]["source_extract_enabled"] = False

    real_extract_brief = article.extract_brief
    real_search = evidence.search
    real_gather_evidence = evidence.gather_evidence
    real_support_sources = article._support_sources
    real_choose_question = article._choose_question
    real_draft_article = article._draft_article
    real_find_images = article.find_images
    real_extract_source_facts = article._extract_source_facts
    real_dup_index = article._source_fact_duplicate_index

    def _install_common():
        evidence.search = lambda query, cfg, days, unrestricted=False: [object()]
        article._choose_question = lambda grounded, cfg, retries=2: ("سؤال اختبار الدرجات؟", "")
        article.find_images = lambda title, cfg, terms=None: []

    try:
        # ── 1) واقعة واحدة بمصدر مستقل واحد ⇒ مقال منسوب من أول محاولة ──
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        _install_common()
        evidence.gather_evidence = lambda articles, cfg, claim_text="": (
            [{"name": "Türkiye Today", "text": "نص", "link": "https://tt/1"}],
            evidence.EVIDENCE_FULL_TEXT)
        article._support_sources = (
            lambda fact_text, docs, cfg, is_statement=False, is_report=False, publisher="":
            ["Türkiye Today"])
        article.extract_brief = lambda body, cfg, retries=3: ({
            "topic": "اختبار درجة ب",
            "statements": [
                {"text": "واقعة بمصدر واحد", "kind": "واقعة", "entities": ["ك"],
                 "is_unnamed_event": False, "is_reference": False},
            ],
            "questions": [],
        }, None)
        article._draft_article = (
            lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
                {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
                 "image_headline": "عنوان", "post_title": question,
                 "post_body": "متن الاختبار بحسب Türkiye Today عن الواقعة.",
                 "hashtags": ["اختبار"]}, ""))

        out_b = article._write_article("موجز درجة ب", 20001, cfg)
        check("1) واقعة بمصدر واحد ⇒ مقال (لا تسقط)",
              out_b["produced"] is True, out_b["reason"])
        check("1) outcome['dropped'] فارغة", out_b["dropped"] == [], out_b["dropped"])
        check("1) fact_grades يسجّل الدرجة ب واسم المصدر",
              out_b["fact_grades"] == [{"text": "واقعة بمصدر واحد", "grade": "B",
                                       "attribution_name": "Türkiye Today"}],
              out_b["fact_grades"])
        check("1) attribution_retry لم تُحاوَل (نجحت المحاولة الأولى)",
              out_b["attribution_retry"]["attempted"] is False, out_b["attribution_retry"])
        check("1) fallback_to_brief == False (سند حقيقي فعليًا لا موجز محرر)",
              out_b["fallback_to_brief"] is False, out_b)
        report_b = article.build_report(out_b)
        check("1) التقرير يعرض «منسوبة إلى مصدر واحد: Türkiye Today»",
              "منسوبة إلى مصدر واحد: Türkiye Today" in report_b, report_b)

        # ── 2) غياب اسم المصدر في المتن مرتين ⇒ تُسقَط تلك الواقعة وحدها
        # لا المقال — واقعة أخرى درجة أ تبقى وتُصاغ المقال منها ──
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        _install_common()
        evidence.gather_evidence = lambda articles, cfg, claim_text="": (
            [{"name": "Daily Sabah", "text": "نص", "link": "https://ds/1"},
             {"name": "Yeni Şafak", "text": "نص", "link": "https://ys/1"}],
            evidence.EVIDENCE_FULL_TEXT)
        SUPPORT2 = {
            "واقعة درجة أ": ["Daily Sabah", "Yeni Şafak"],
            "واقعة بلا اسم في المتن": ["Daily Sabah"],
        }
        article._support_sources = (
            lambda fact_text, docs, cfg, is_statement=False, is_report=False, publisher="":
            SUPPORT2.get(fact_text, []))
        article.extract_brief = lambda body, cfg, retries=3: ({
            "topic": "اختبار إسقاط فردي",
            "statements": [
                {"text": "واقعة درجة أ", "kind": "واقعة", "entities": ["ك1"],
                 "is_unnamed_event": False, "is_reference": False},
                {"text": "واقعة بلا اسم في المتن", "kind": "واقعة", "entities": ["ك2"],
                 "is_unnamed_event": False, "is_reference": False},
            ],
            "questions": [],
        }, None)
        draft_calls: list = []

        def _draft_always_missing(grounded, opinions, question, cfg, retries=3, avoid_note=""):
            draft_calls.append(avoid_note)
            body = "متن اختبار الإسقاط الفردي يذكر واقعة درجة أ فقط."
            return ({"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
                    "image_headline": "عنوان", "post_title": question,
                    "post_body": body, "hashtags": ["اختبار"]}, "")

        article._draft_article = _draft_always_missing
        out_drop = article._write_article("موجز إسقاط فردي", 20002, cfg)
        check("2) المقال صيغ رغم فشل نسبة إحدى الوقائع مرتين",
              out_drop["produced"] is True, out_drop["reason"])
        check("2) إعادة النداء حاولت فعلًا",
              out_drop["attribution_retry"]["attempted"] is True, out_drop["attribution_retry"])
        check("2) المحاولة الثانية لم تنجح (المتن الثابت لا يذكر اسم المصدر)",
              out_drop["attribution_retry"]["succeeded"] is False, out_drop["attribution_retry"])
        check("2) الواقعة غير المنسوبة أُسقطت وحدها — لا المقال كله",
              "واقعة بلا اسم في المتن" in out_drop["attribution_retry"]["dropped_facts"],
              out_drop["attribution_retry"])
        check("2) الواقعة الأخرى (درجة أ) بقيت في المقال",
              any(g["text"] == "واقعة درجة أ" for g in out_drop["fact_grades"]),
              out_drop["fact_grades"])
        check("2) الواقعة المُسقَطة غابت عن fact_grades النهائية",
              all(g["text"] != "واقعة بلا اسم في المتن" for g in out_drop["fact_grades"]),
              out_drop["fact_grades"])
        check("2) إعادة النداء استُدعيت بتوجيه صريح يذكر اسم المصدر المطلوب",
              len(draft_calls) >= 2 and "Daily Sabah" in draft_calls[1], draft_calls)

        # ── 3) صفر وقائع مسندة كليًا ⇒ الضمان يصوغ مقالًا من الموجز نفسه
        # موسومًا «بحسب معلومات المحرر»، ولا يُنشر تلقائيًا (status يبقى
        # "pending" — نفس مسار المراجعة العادي، لا طريق نشر مباشر) ──
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        _install_common()
        evidence.gather_evidence = lambda articles, cfg, claim_text="": (
            [{"name": "مصدر", "text": "نص", "link": "https://s/1"}],
            evidence.EVIDENCE_FULL_TEXT)
        article._support_sources = (
            lambda fact_text, docs, cfg, is_statement=False, is_report=False, publisher="": [])
        article.extract_brief = lambda body, cfg, retries=3: ({
            "topic": "اختبار الضمان",
            "statements": [
                {"text": "واقعة بلا أي سند مستقل", "kind": "واقعة", "entities": ["ك"],
                 "is_unnamed_event": False, "is_reference": False},
            ],
            "questions": [],
        }, None)
        article._draft_article = (
            lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
                {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
                 "image_headline": "عنوان", "post_title": question,
                 "post_body": "متن اختبار الضمان بحسب معلومات المحرر عن الواقعة.",
                 "hashtags": ["اختبار"]}, ""))

        out_fb = article._write_article("موجز الضمان", 20003, cfg)
        check("3) صفر وقائع مسندة لا يمنع المقال — يُصاغ من الموجز نفسه",
              out_fb["produced"] is True, out_fb["reason"])
        check("3) fallback_to_brief == True", out_fb["fallback_to_brief"] is True, out_fb)
        check("3) الواقعة دخلت المقال درجة ج",
              out_fb["fact_grades"] == [{"text": "واقعة بلا أي سند مستقل",
                                        "grade": "C", "attribution_name": ""}],
              out_fb["fact_grades"])
        check("3) dropped فارغة (الواقعة صارت مضمون المقال نفسه لا ادّعاءً ساقطًا)",
              out_fb["dropped"] == [], out_fb["dropped"])
        report_fb = article.build_report(out_fb)
        check("3) التقرير يبدأ بتحذير بارز أن المقال كله بلا سند مستقل",
              "⚠️ هذا المقال مبنيّ كاملًا على موجزك ولم يُؤكَّد أيٌّ منه بمصدر مستقل" in report_fb,
              report_fb)
        check("3) التقرير يعرض «من موجز المحرر — بلا سند مستقل»",
              "من موجز المحرر — بلا سند مستقل" in report_fb, report_fb)
        loaded = store.load_draft(out_fb["draft_id"])
        check("3) المسودة محفوظة بحالة pending — لا طريق نشر مباشر لمقال بلا سند",
              loaded is not None and loaded[1]["status"] == "pending",
              loaded[1].get("status") if loaded else None)

        # ── 4) مزيج الدرجات الثلاث في تشغيلة واحدة — كل واقعة بصيغتها ──
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        _install_common()
        docs_by_key = {
            "واقعة أ": [{"name": "مصدر أول", "text": "نص", "link": "https://s1/1"},
                       {"name": "مصدر ثانٍ", "text": "نص", "link": "https://s2/1"}],
            "واقعة ب": [{"name": "المصدر المنفرد", "text": "نص", "link": "https://s3/1"}],
        }

        def _gather_mixed(articles, cfg, claim_text=""):
            for key, docs in docs_by_key.items():
                if key in claim_text:
                    return (docs, evidence.EVIDENCE_FULL_TEXT)
            return ([], evidence.EVIDENCE_NO_RESULTS)

        evidence.gather_evidence = _gather_mixed
        SUPPORT_MIX = {"واقعة أ": ["مصدر أول", "مصدر ثانٍ"], "واقعة ب": ["المصدر المنفرد"],
                       "واقعة ج": []}
        article._support_sources = (
            lambda fact_text, docs, cfg, is_statement=False, is_report=False, publisher="":
            SUPPORT_MIX.get(fact_text, []))
        article.extract_brief = lambda body, cfg, retries=3: ({
            "topic": "اختبار مزيج الدرجات",
            "statements": [
                {"text": "واقعة أ", "kind": "واقعة", "entities": ["واقعة أ"],
                 "is_unnamed_event": False, "is_reference": False},
                {"text": "واقعة ب", "kind": "واقعة", "entities": ["واقعة ب"],
                 "is_unnamed_event": False, "is_reference": False},
                {"text": "واقعة ج", "kind": "واقعة", "entities": ["واقعة ج"],
                 "is_unnamed_event": False, "is_reference": False},
            ],
            "questions": [],
        }, None)
        article._draft_article = (
            lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
                {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
                 "image_headline": "عنوان", "post_title": question,
                 "post_body": "متن اختبار المزيج بحسب المصدر المنفرد.",
                 "hashtags": ["اختبار"]}, ""))

        out_mix = article._write_article("موجز مزيج الدرجات", 20004, cfg)
        grades_by_text = {g["text"]: g["grade"] for g in out_mix["fact_grades"]}
        check("4) واقعة أ (مصدران) درجة أ", grades_by_text.get("واقعة أ") == "A", grades_by_text)
        check("4) واقعة ب (مصدر واحد) درجة ب", grades_by_text.get("واقعة ب") == "B", grades_by_text)
        check("4) واقعة ج (بلا سند) سقطت — الدرجتان أ/ب غير فارغتين فلا ضمان",
              "واقعة ج" not in grades_by_text and
              any(d["text"] == "واقعة ج" for d in out_mix["dropped"]),
              (grades_by_text, out_mix["dropped"]))
        check("4) fallback_to_brief == False (وقائع أ/ب موجودتان فعلًا)",
              out_mix["fallback_to_brief"] is False, out_mix)

        # ── 5) شاهد التشغيلة (Issue #835): ثلاث عشرة واقعة مصدرية كلها
        # بمصدر مستقل واحد فقط («سند غير كافٍ من المجمّع (1/2)» في السجل
        # الأصلي المُبلَّغ) — يُصاغ مقال منها منسوبةً، لا امتناع ──
        shutil.rmtree(DRAFTS_DIR, ignore_errors=True)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        _install_common()
        cfg_src = load_config()
        cfg_src["article"]["source_extract_enabled"] = True
        evidence.gather_evidence = lambda articles, cfg, claim_text="": (
            [{"name": "مصدر التشغيلة", "text": "نص", "link": "https://run/1"}],
            evidence.EVIDENCE_FULL_TEXT)
        thirteen = [{"text": f"واقعة مصدر {i}", "entities": [f"ك{i}"]} for i in range(1, 14)]
        article._extract_source_facts = lambda topic, brief_texts, docs, cfg: thirteen
        article._source_fact_duplicate_index = (
            lambda candidate_text, existing_texts, cfg, topic="": {
                "duplicate": False, "index": None, "call_error": None,
                "on_topic": True, "on_topic_reason": ""})

        def _support_dispatch(fact_text, docs, cfg, is_statement=False, is_report=False,
                              publisher=""):
            if fact_text.startswith("واقعة مصدر"):
                return ["مصدر التشغيلة"]  # مصدر مستقل واحد فقط — شاهد التشغيلة بعينه
            return ["مصدر أول", "مصدر ثانٍ"]  # الواقعة الأولية تُغذّي القراءة فقط، درجة أ واضحة

        article._support_sources = _support_dispatch
        article.extract_brief = lambda body, cfg, retries=3: ({
            "topic": "شاهد التشغيلة",
            "statements": [
                {"text": "واقعة أولية لتغذية القراءة", "kind": "واقعة", "entities": [],
                 "is_unnamed_event": False, "is_reference": False},
            ],
            "questions": [],
        }, None)
        article._draft_article = (
            lambda grounded, opinions, question, cfg, retries=3, avoid_note="": (
                {"angle": "تفسير", "analysis": "", "urgent": False, "category": "عالم",
                 "image_headline": "عنوان", "post_title": question,
                 "post_body": "متن شاهد التشغيلة بحسب مصدر التشغيلة عن كل الوقائع.",
                 "hashtags": ["اختبار"]}, ""))

        out_run = article._write_article("موجز شاهد التشغيلة", 20005, cfg_src)
        source_grades = [g for g in out_run["fact_grades"] if g["text"].startswith("واقعة مصدر")]
        check("5) مقال صيغ من الوقائع الثلاث عشرة — لا امتناع",
              out_run["produced"] is True, out_run["reason"])
        check("5) الوقائع الثلاث عشرة كلها دخلت درجة ب منسوبة لمصدر التشغيلة",
              len(source_grades) == 13 and
              all(g["grade"] == "B" and g["attribution_name"] == "مصدر التشغيلة"
                  for g in source_grades),
              source_grades)
        check("5) dropped فارغة (لا واقعة سقطت فعليًا — كلها درجة ب)",
              out_run["dropped"] == [], out_run["dropped"])
    finally:
        article.extract_brief = real_extract_brief
        evidence.search = real_search
        evidence.gather_evidence = real_gather_evidence
        article._support_sources = real_support_sources
        article._choose_question = real_choose_question
        article._draft_article = real_draft_article
        article.find_images = real_find_images
        article._extract_source_facts = real_extract_source_facts
        article._source_fact_duplicate_index = real_dup_index
