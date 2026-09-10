"""بناء بطاقة المنشور من حقول المسودة المخزَّنة وحدها — نقطة مشتركة واحدة
لكل مسارات النشر (Issue #852، الجزء الأول من اثنين).

قبل هذه الوحدة كانت البطاقة تُبنى لحظة الجمع، قبل أن يُختار عنوانها فعليًا
— فالعنوان الذي يتعلّمه المراجع (headlines/headline_selected، Issue #756)
لا يظهر على البطاقة إلا بإعادة بناء استثنائية (#760). مسار التحليل
(youtube_publish.ensure_title_card) طبّق مبدأ «ابنِ عند الاعتماد لا عند
الجمع» منذ Issue #680؛ هذه الوحدة تعمّمه لبقية المسارات بدل تكراره خمس
مرات، فتوقف collect.py/collect_finalize.py/radar.py/verify_draft.py/
article.py عن بناء البطاقة وتترك ensure() تبنيها لاحقًا (عادة عند
الاعتماد في publish.main، انظر توثيق CLAUDE.md).

ensure() هي الاستعمال المعتاد: تبني بطاقة أول مرة من الحقول المخزَّنة
(manual_image ← source.image_candidates ← source.image_url ← بحث
imagesearch.find_images احتياطًا)، أو تعيد المسار الحالي بلا أي بناء إن
كانت البطاقة موجودة فعلًا على القرص — نفس سلوك youtube_publish.
ensure_title_card السابق حرفيًا (فحص «موجودة مسبقًا» قبل أي عمل).

setimage.rebuild_card وyoutube_publish.ensure_title_card غلافان رفيعان
فوق هذه الدالة (لا نسختان مكرَّرتان) عبر معاملات إضافية غير موثَّقة في
توقيع ensure() العام (force/allow_search_fallback/check_headline_limit/
persist/build_post_image/download_image) — كل معامل منها موجود لسبب
سلوكي محدَّد يحافظ على تطابق الوظيفتين حرفيًا مع ما كانتا عليه قبل هذه
المهمة (كل سبب موثَّق عند استعماله في الوحدتين). الأهم: اختبار
setimage.rebuild_card القائم (tests/test_pipeline.py) يستبدل
``setimage.build_post_image`` بجاسوس (spy) ليفحص وسيط ``image_urls``
الفعلي — استيراد ensure() لاسم ``imaging.build_post_image`` مباشرة كان
سيُفلت من ذلك الاستبدال (الاسمان منفصلان في بايثون بعد ``from .imaging
import build_post_image``)، فتمرير الاسم المحلي القابل للاستبدال صراحةً
من setimage.py (معامل ``build_post_image``) هو ما يُبقي ذلك الاختبار
يعمل بلا أي تعديل عليه — نفس المبدأ لـ``download_image``.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from . import store
from .config import DRAFTS_DIR
from .imaging import build_post_image as _default_build_post_image
from .imaging import download_image as _default_download_image
from .imagesearch import find_images

log = logging.getLogger("cards")

_VERSION_RE = re.compile(r"^(.*)-v(\d+)$")
_UNSET = object()


def next_image_path(current: str) -> str:
    """مسار جديد لا يستبدل القديم — نُقلت من setimage.py إلى هنا (Issue
    #852)؛ setimage.next_image_path يُعيد تصديرها بلا أي تغيير في سلوكها.

    جيت‑هَب يخزّن صور الـIssues في وسيط تخزين مؤقت (camo)، فالكتابة فوق
    المسار نفسه تُبقي الصورة القديمة معروضة أمام المراجع. اسم جديد يتجاوز
    ذلك، والقديم يبقى شاهدًا على ما جرى."""
    p = Path(current)
    stem = p.stem
    match = _VERSION_RE.match(stem)
    if match:
        stem, version = match.group(1), int(match.group(2)) + 1
    else:
        version = 2
    return str(p.with_name(f"{stem}-v{version}{p.suffix}"))


def _resolve_headline(draft: dict, cfg, headline: str | None) -> tuple[str, str | None]:
    """العنوان: الممرَّر إن وُجد وكان ضمن حدّ image.headline_max_chars
    (المقرَّر في #760)، وإلا arabic.image_headline — عنوان ممرَّر يتجاوز
    الحدّ لا يُستعمل على البطاقة، ويُعاد سبب ذلك لتسجيله لا للفشل به."""
    ar = draft.get("arabic") or {}
    max_chars = int(cfg.path("image.headline_max_chars", 95))
    reason = None
    chosen = headline
    if chosen and len(chosen) > max_chars:
        reason = (f"العنوان الممرَّر ({len(chosen)} حرفًا) يتجاوز حدّ البطاقة "
                  f"({max_chars}) — استُعمل arabic.image_headline بدلًا منه")
        chosen = None
    if not chosen:
        chosen = (ar.get("image_headline") or ar.get("post_title")
                 or (draft.get("source") or {}).get("title", ""))
    return chosen, reason


def _resolve_image_urls(draft: dict) -> tuple[list[str], str | None]:
    """سلسلة مصدر الصورة: manual_image ← source.image_candidates ← أول
    عنصر منها ← source.image_url. يعيد (روابط build_post_image، رابط
    manual المفرد إن وُجد — يُستعمل لفحص مسبق ولوسم image_info.manual)."""
    src = draft.get("source") or {}
    manual = draft.get("manual_image")
    if manual:
        return [manual], manual
    candidates = list(src.get("image_candidates") or [])
    if candidates:
        return candidates, None
    if src.get("image_url"):
        return [src["image_url"]], None
    return [], None


def ensure(path: Path, draft: dict, cfg, headline: str | None = None, *,
           force: bool = False,
           image_urls=_UNSET,
           fallback_urls: list[str] | None = None,
           allow_search_fallback: bool = True,
           search_term: str | None = None,
           publisher=_UNSET,
           category: str | None = None,
           urgent: bool | None = None,
           bucket: str | None = None,
           origin: str | None = None,
           out_dir: str | None = None,
           check_headline_limit: bool = True,
           persist: bool = True,
           build_post_image=None,
           download_image=None) -> str | None:
    """يبني بطاقة المسودة من حقولها المخزَّنة، أو يعيد مسارها الحالي بلا
    بناء إن كانت موجودة فعلًا على القرص (``force=False``). يعيد المسار
    النسبي الجديد (يبدأ بـ"drafts/")، أو ``None`` عند الفشل (لا مصدر
    صورة، رابط غير صالح، أو تعذّر البناء) — البطاقة السابقة (إن وُجدت)
    تبقى قائمة عند الفشل.

    ``persist=True`` (الافتراضي، لكل مستدعٍ جديد): يحفظ image/has_photo/
    image_info على القرص عبر ``store.update_draft`` ويحدّث ``draft`` في
    الذاكرة أيضًا، فيتمكن المستدعي من استعمال المسودة فورًا بلا إعادة
    تحميلها. ``persist=False`` (setimage.rebuild_card وحدها): لا كتابة
    هنا إطلاقًا — المستدعي القديم يكتب حقولًا إضافية (manual_image،
    revive...) في نداء ``update_draft`` واحد خاص به، ولأن ``path`` في ذلك
    المسار قد لا يشير إلى ملف حقيقي على القرص أصلًا (اختبار
    ``rebuild_card`` يستدعيها بمسار وهمي، إذ الدالة لا تلمس التخزين قط).

    ``out_dir``: اسم مجلد التاريخ الذي تُكتب فيه البطاقة الجديدة
    (``drafts/<out_dir>/<id>.jpg``) حين لا توجد بطاقة سابقة ولا force.
    الافتراض (``None``) يشتقّه من مجلد ``path`` نفسه (حيث المسودة محفوظة
    فعليًا) — الصحيح لكل مستدعٍ جديد. ``youtube_publish.ensure_title_card``
    وحدها تمرّره صراحةً (حقل ``run_date`` المخزَّن في المسودة): مجلد الحفظ
    الفعلي (``store.save_draft`` يستعمل تاريخ الحفظ الحقيقي وقت النداء، لا
    ``run_date`` المُمرَّر لـ``build()``) يطابق ``run_date`` دومًا في
    التشغيل الحقيقي، لكن اختبارها يُمرِّر ``run_date`` مصطنعًا فيتباعدان —
    وسلوكها يجب أن يبقى مطابقًا لما كان قبل هذه المهمة حرفيًا."""
    build_fn = build_post_image or _default_build_post_image
    dl_fn = download_image or _default_download_image

    existing = draft.get("image")
    if existing and not force:
        existing_path = DRAFTS_DIR / Path(existing).relative_to("drafts")
        if existing_path.exists():
            return existing

    src = draft.get("source") or {}
    manual = draft.get("manual_image")

    if image_urls is _UNSET:
        urls, manual_url = _resolve_image_urls(draft)
    else:
        urls = list(image_urls or [])
        manual_url = manual if manual and urls[:1] == [manual] else None

    first_url = urls[0] if urls else None
    if force:
        if not first_url and not fallback_urls:
            log.warning("لا مصدر صورة لإعادة بناء بطاقة %s", draft.get("id", path))
            return None
        if first_url and dl_fn(first_url) is None:
            log.warning("رابط غير صالح كصورة: %s", str(first_url)[:90])
            return None

    if check_headline_limit:
        chosen_headline, reason = _resolve_headline(draft, cfg, headline)
    else:
        ar = draft.get("arabic") or {}
        chosen_headline = headline or ar.get("image_headline") or ar.get("post_title", "")
        reason = None
    if reason:
        log.info("بطاقة %s: %s", draft.get("id", path), reason)

    spec = draft.get("reel_spec") or {}
    ar = draft.get("arabic") or {}

    if existing and force:
        out_rel = next_image_path(existing)
    else:
        rel_dir = out_dir or path.parent.relative_to(DRAFTS_DIR).as_posix()
        out_rel = f"drafts/{rel_dir}/{draft['id']}.jpg"
    out_path = DRAFTS_DIR / Path(out_rel).relative_to("drafts")

    fb_provider = None
    if allow_search_fallback and not urls and not fallback_urls:
        term = search_term or src.get("title") or chosen_headline
        fb_provider = lambda t=term: find_images(t, cfg)

    resolved_publisher = (publisher if publisher is not _UNSET
                          else (src.get("publishers") or [src.get("publisher", "")]))

    shot: dict = {}
    try:
        build_fn(
            headline=chosen_headline,
            category=(category if category is not None
                     else (spec.get("category") or ar.get("category", ""))),
            urgent=(urgent if urgent is not None
                   else bool(spec.get("urgent") or ar.get("urgent"))),
            image_urls=urls or None,
            fallback_urls=fallback_urls,
            publisher=resolved_publisher,
            bucket=bucket if bucket is not None else draft.get("bucket", "serious"),
            origin=origin if origin is not None else store.origin_of(draft),
            fallback_provider=fb_provider,
            cfg=cfg,
            out_path=out_path,
            report=shot,
        )
    except Exception as exc:  # noqa: BLE001 — امتناع صريح مُسجَّل لا انهيار صامت
        log.warning("تعذّر بناء بطاقة %s: %s", draft.get("id", path), exc)
        return None

    if persist:
        image_info = {
            "used_original": bool(shot.get("used_original")),
            "illustrative": bool(shot.get("illustrative")),
            "composite": bool(shot.get("composite")),
            "chosen_url": shot.get("chosen_url"),
            "candidates_tried": shot.get("candidates_tried"),
            "manual": bool(manual_url),
        }
        store.update_draft(path, image=out_rel, has_photo=image_info["used_original"],
                           image_info=image_info)
        draft["image"] = out_rel
        draft["has_photo"] = image_info["used_original"]
        draft["image_info"] = image_info

    return out_rel
