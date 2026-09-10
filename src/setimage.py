"""صورة يدوية: تعطي رابطًا، فتُعاد بطاقة الخبر ببنائها عليه.

بعض الأخبار تصل بلا صورة صالحة — ناشر لا يضع صورة، أو رابط وسيط لا
يُفتح — فتُبنى البطاقة على خلفية مصممة. هذا المسار يتيح للمراجع أن
يضيف صورة بنفسه ويُعاد بناء البطاقة فورًا بلا إعادة الصياغة.

    # من تعليق على Issue المراجعة
    /صورة a1b2c3d4e5 https://example.com/photo.jpg

    # أو محليًا
    python -m src.setimage --draft a1b2c3d4e5 --url https://example.com/p.jpg
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
from pathlib import Path

from . import cards, review, store
from .config import DRAFTS_DIR, load_config
from .imaging import build_post_image, download_image

log = logging.getLogger("setimage")

# جسر بين خطوتين في سير العمل: البناء يسبق الدفع، وتحديث الـ Issue
# يليه. لو حدّثنا الـ Issue قبل الدفع لأشار إلى ملف غير موجود بعد.
SYNC_FILE = Path(os.environ.get("IMAGE_SYNC_FILE", "/tmp/trendnews_image_sync.json"))

# /صورة المعرّف الرابط — يقبل image بالإنجليزية أيضًا
COMMAND_RE = re.compile(
    r"/(?:صورة|image)\s+([0-9a-f]{6,16})\s+(https?://\S+)", re.IGNORECASE)


def parse_commands(body: str) -> list[tuple[str, str]]:
    """يقرأ أوامر الصورة من نص تعليق. يقبل عدة أوامر في تعليق واحد."""
    out, seen = [], set()
    for draft_id, url in COMMAND_RE.findall(body or ""):
        url = url.rstrip(").,>\u060c")     # لصق الرابط داخل جملة أو قوس
        if draft_id not in seen:
            out.append((draft_id, url))
            seen.add(draft_id)
    return out


# نُقلت فعليًا إلى cards.py (Issue #852) — بلا أي تغيير في سلوكها، معاد
# تصديرها هنا فقط لأن اختبارات هذا الملف القائمة تستدعيها كـ
# setimage.next_image_path.
next_image_path = cards.next_image_path


def _image_related_failure(error: str | None) -> bool:
    """يميّز فشل النشر بسبب الصورة تحديدًا عن أي فشل آخر (Issue #742).

    مسودة ``failed`` تحيا تلقائيًا بعد ``/صورة`` ناجح فقط إن كان ``error``
    أحد النصّين اللذين يسجّلهما ``publish.publish_one``/``open_review``
    لغياب الصورة تحديدًا: حقل ``image`` ضمن "حقول مفقودة: …"، أو "الصورة
    مفقودة". أي نصّ آخر (استثناء فيسبوك، مثلًا) يعني سببًا غير معروف هنا
    فتبقى ``failed`` — السبب لم يزُل بمجرّد تغيير الصورة."""
    if not error:
        return False
    if error == "الصورة مفقودة":
        return True
    if error.startswith("حقول مفقودة:"):
        fields = [f.strip() for f in error.split(":", 1)[1].split(",")]
        return "image" in fields
    return False


def rebuild_card(path: Path, draft: dict, headline: str, cfg) -> str | None:
    """يبني بطاقة جديدة لمسودة قائمة، بنفس مصدر صورتها وبعنوان مُمرَّر.

    مصدر الصورة: ``manual_image`` إن وُجد، وإلا أول عناصر
    ``source.image_candidates``، وإلا ``source.image_url`` — أولوية مصدر
    الصورة الفعلي للمسودة اليوم، لا صورة جديدة. يعيد المسار النسبي الجديد
    (يبدأ بـ "drafts/")، أو ``None`` إن تعذّر (لا مصدر صورة، رابط غير صالح،
    أو فشل التنزيل/البناء) — البطاقة القديمة تبقى قائمة عند الفشل، فلا
    يستدعي هذا الفشل أي تدخّل من الطالب سوى تجاهل القيمة المُعادة.

    ``image_urls`` الممرَّرة لـ``build_post_image``: رابط ``manual_image``
    وحده حين وُجد (رابط وضعه المراجع بعينه، لا مرشَّحًا من عدة)؛ وإلا
    ``source.image_candidates`` كاملة لا ``url`` المفرد وحده (تصحيح من
    #760، Issue #765) — بطاقة مدمجة من صورتين (imaging.build_post_image
    يدمج أول مرشَّحين ناجحين) كانت تنهار صامتة إلى صورة واحدة عند أي
    إعادة بناء (اختيار عنوان غير افتراضي، مثلًا) لأن ``[url]`` (أول عنصر
    فقط) هو ما كان يصل ``build_post_image`` بصرف النظر عن عدد المرشَّحين
    الفعلي.
    """
    # غلاف رفيع فوق cards.ensure (Issue #852): force=True يفرض إعادة بناء
    # بمسار جديد (next_image_path — تفادي كاش camo، انظر توثيق الوحدة)
    # بصرف النظر عن وجود بطاقة سابقة؛ allow_search_fallback=False يحافظ
    # على "لا بديل تلقائي" (الصمت عند الفشل أصدق من إحلال صورة أخرى دون
    # علم الطالب)؛ check_headline_limit=False يستعمل headline كما وصل
    # حرفيًا (لا فحص طول هنا، كالسابق)؛ persist=False لأن هذه الدالة لا
    # تكتب للتخزين قط — المستدعي (apply_image) يكتب حقولًا إضافية في نداء
    # واحد خاص به، ولأن `path` هنا قد لا يشير لملف حقيقي أصلًا (اختبار
    # rebuild_card القائم يستدعيها بمسار وهمي). build_post_image/
    # download_image يُمرَّران صراحة (لا cards._default_*) كي يبقى اختبار
    # rebuild_card القائم الذي يستبدل setimage.build_post_image بجاسوس
    # يعمل بلا أي تعديل — تمرير الاسم المحلي هنا يحترم أي استبدال له.
    return cards.ensure(
        path, draft, cfg, headline=headline,
        force=True, allow_search_fallback=False, check_headline_limit=False,
        persist=False,
        build_post_image=build_post_image, download_image=download_image,
    )


def apply_image(draft_id: str, url: str, cfg) -> dict | None:
    """يعيد بناء بطاقة المسودة على الصورة المعطاة. يعيد المسودة المحدَّثة."""
    found = store.load_draft(draft_id)
    if not found:
        log.warning("لا مسودة بالمعرّف %s", draft_id)
        return None
    path, draft = found

    if not draft.get("image"):
        # مسودة بلا بطاقة بعد — الحالة العامة لكل المسارات منذ Issue #852
        # (كانت مقصورة على مسار التحليل وحده قبلها، Issue #680): البطاقة
        # تُبنى فقط عند الاعتماد (cards.ensure)، فلا معنى لمحاولة "إعادة"
        # بنائها هنا أصلًا (rebuild_card يفترض بطاقة سابقة ليحسب مسارًا
        # "تاليًا" لها — Issue #749). نخزّن الرابط في manual_image وحده
        # بلا أي محاولة بناء؛ أول أولوية في سلسلة مصدر الصورة داخل
        # cards.ensure فتلتقطه تلقائيًا عند الاعتماد.
        revive = (draft.get("status") == "failed"
                  and _image_related_failure(draft.get("error")))
        draft = store.update_draft(
            path, manual_image=url,
            **({"status": "pending", "error": None} if revive else {}),
        )
        if revive:
            log.info("✓ أُحييت المسودة %s من failed إلى pending — سبب الفشل زال", draft_id)
        log.info("✓ رابط يدوي خُزّن لمسودة بلا بطاقة بعد (تُبنى عند الاعتماد): %s", draft_id)
        draft["_old_image"] = None
        return draft

    spec = draft.get("reel_spec") or {}
    ar = draft.get("arabic") or {}
    headline = (spec.get("headline") or ar.get("image_headline")
                or ar.get("post_title") or draft["source"]["title"])
    # manual_image=url يجعل rebuild_card يختار هذا الرابط تحديدًا مصدرًا
    # (أول أولوية في سلسلته) — لا صورة المسودة الحالية إن وُجدت من قبل.
    new_rel = rebuild_card(path, {**draft, "manual_image": url}, headline, cfg)
    if new_rel is None:
        return None

    old_rel = draft["image"]
    # إحياء مسودة failed (Issue #742): السبب المسجَّل في error زال فعلًا
    # فقط إن كان الفشل بسبب الصورة تحديدًا — أي سبب آخر (خطأ فيسبوك مثلًا)
    # يبقى قائمًا رغم تغيير الصورة، فلا تُحيا المسودة تلقائيًا حينها.
    revive = (draft.get("status") == "failed"
              and _image_related_failure(draft.get("error")))
    draft = store.update_draft(
        path,
        image=new_rel,
        has_photo=True,
        manual_image=url,
        image_info={"manual": True, "used_original": True,
                    "illustrative": False, "composite": False, "chosen_url": url},
        source={**draft["source"], "image_url": url, "image_candidates": [url]},
        reel_spec={**spec, "image_candidates": [url]},
        reel=None,          # الريل القديم بُني على الصورة القديمة
        **({"status": "pending", "error": None} if revive else {}),
    )
    if revive:
        log.info("✓ أُحييت المسودة %s من failed إلى pending — سبب الفشل زال", draft_id)
    log.info("✓ أُعيد بناء البطاقة: %s → %s", old_rel, new_rel)
    draft["_old_image"] = old_rel
    return draft


def main() -> int:
    parser = argparse.ArgumentParser(description="إضافة صورة يدوية لمسودة")
    parser.add_argument("--draft", help="معرّف المسودة")
    parser.add_argument("--url", help="رابط الصورة")
    parser.add_argument("--body", default="", help="نص تعليق فيه أوامر /صورة")
    parser.add_argument("--issue", type=int, default=0, help="رقم الـ Issue")
    parser.add_argument("--from-issue", action="store_true",
                        help="اقرأ الطلبات من مربعات الـ Issue وفراغاتها")
    parser.add_argument("--sync", action="store_true",
                        help="تحديث الـ Issue بنتيجة بناء سابق (بعد الدفع)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")

    if args.sync:
        return sync_issue(args.issue)

    pairs = parse_commands(args.body)
    if args.from_issue and args.issue:
        # المربعات هي الواجهة الأساسية؛ أوامر التعليق بديل لمن يفضّلها
        pairs += [p for p in review.parse_image_requests(
            review.fetch_issue_body(args.issue)) if p not in pairs]
    if args.draft and args.url:
        pairs.append((args.draft, args.url))
    if not pairs:
        log.error("لا أمر صورة صالح. الصيغة: /صورة المعرّف رابط_الصورة")
        return 2

    cfg = load_config()
    done: list[dict] = []
    failed: list[str] = []
    for draft_id, url in pairs:
        try:
            updated = apply_image(draft_id, url, cfg)
        except Exception as exc:  # noqa: BLE001 — خطأ واحد لا يُسقط الباقي
            log.error("فشل بناء صورة %s: %s", draft_id, exc)
            updated = None
        if updated:
            # "new" غائب (None) لمسودة بلا بطاقة بعد (Issue #852) — الرابط
            # خُزّن في manual_image بلا بناء، فلا مسار صورة جديد يُستبدَل
            # به في نص الـIssue بعد (لا بطاقة معروضة هناك أصلًا).
            done.append({"id": draft_id,
                         "old": updated["_old_image"],
                         "new": updated.get("image"),
                         "title": updated["arabic"]["post_title"][:60]})
        else:
            failed.append(draft_id)

    SYNC_FILE.write_text(
        json.dumps({"done": done, "failed": failed}, ensure_ascii=False),
        encoding="utf-8")
    return 0 if done else 1


def sync_issue(issue: int) -> int:
    """يُشغَّل بعد رفع الصورة: يبدّل مسارها في الـ Issue ويعلّق بالنتيجة."""
    if not issue or not SYNC_FILE.exists():
        return 0
    data = json.loads(SYNC_FILE.read_text(encoding="utf-8"))
    done, failed = data.get("done", []), data.get("failed", [])

    if done or failed:
        body = review.fetch_issue_body(issue)
        for item in done:
            # "new" غائب لمسودة بلا بطاقة بعد (Issue #852) — لا مسار صورة
            # قديم/جديد يُستبدَل في نص الـIssue أصلًا (لا بطاقة معروضة
            # هناك)، فقط تُفرَغ خانة الطلب.
            if item.get("old") and item.get("new"):
                body = body.replace(item["old"], item["new"])
            body = review.clear_image_request(body, item["id"])
        for draft_id in failed:
            # يبقى الرابط ليصحّحه المراجع بدل أن يعيد لصقه من جديد
            body = review.clear_image_request(body, draft_id, keep_url=True)
        review.update_issue_body(issue, body)

    notes = [(f"🖼️ حُدّثت الصورة: {item['title']}" if item.get("new") else
             f"🖼️ رابط الصورة اليدوي محفوظ لـ«{item['title']}» — ستُبنى البطاقة به عند الاعتماد.")
            for item in done]
    notes += [f"⚠️ تعذّر تحديث `{i}` — تأكد أن الرابط لصورة مباشرة "
              "(ينتهي بـ .jpg أو .png) وأن أبعادها ليست صغيرة." for i in failed]
    if notes:
        review.comment(issue, "\n".join(notes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
