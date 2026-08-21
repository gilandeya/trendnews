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

from . import review, store
from .config import DRAFTS_DIR, load_config
from .imaging import build_post_image, download_image

log = logging.getLogger("setimage")

# جسر بين خطوتين في سير العمل: البناء يسبق الدفع، وتحديث الـ Issue
# يليه. لو حدّثنا الـ Issue قبل الدفع لأشار إلى ملف غير موجود بعد.
SYNC_FILE = Path(os.environ.get("IMAGE_SYNC_FILE", "/tmp/trendnews_image_sync.json"))

# /صورة المعرّف الرابط — يقبل image بالإنجليزية أيضًا
COMMAND_RE = re.compile(
    r"/(?:صورة|image)\s+([0-9a-f]{6,16}|\d{1,3})\s+(https?://\S+)", re.IGNORECASE)


def parse_commands(body: str, index_map: dict[str, str] | None = None
                   ) -> tuple[list[tuple[str, str]], list[str]]:
    """يقرأ أوامر الصورة من نص تعليق. يقبل عدة أوامر في تعليق واحد.

    رقم ترتيب بسيط («1») يُحوَّل إلى معرّف المسودة عبر index_map — خريطة
    يبنيها المستدعي من نص الـ Issue وقت المعالجة (انظر
    review.draft_index_map). رقم لا يُطابق مسودة في الخريطة يُعاد ضمن
    unresolved بدل أن يُهمَل صمتًا.
    """
    out, seen, unresolved = [], set(), []
    for token, url in COMMAND_RE.findall(body or ""):
        url = url.rstrip(").,>\u060c")     # لصق الرابط داخل جملة أو قوس
        draft_id = token
        if token.isdigit() and len(token) < 6:
            draft_id = (index_map or {}).get(token, "")
            if not draft_id:
                if token not in unresolved:
                    unresolved.append(token)
                continue
        if draft_id not in seen:
            out.append((draft_id, url))
            seen.add(draft_id)
    return out, unresolved


def next_image_path(current: str) -> str:
    """
    مسار جديد لا يستبدل القديم.

    جيت‑هَب يخزّن صور الـ Issues في وسيط تخزين مؤقت (camo)، فالكتابة فوق
    المسار نفسه تُبقي الصورة القديمة معروضة أمام المراجع. اسم جديد يتجاوز
    ذلك، والقديم يبقى شاهدًا على ما جرى.
    """
    p = Path(current)
    stem = p.stem
    match = re.match(r"^(.*)-v(\d+)$", stem)
    if match:
        stem, version = match.group(1), int(match.group(2)) + 1
    else:
        version = 2
    return str(p.with_name(f"{stem}-v{version}{p.suffix}"))


def apply_image(draft_id: str, url: str, cfg) -> dict | None:
    """يعيد بناء بطاقة المسودة على الصورة المعطاة. يعيد المسودة المحدَّثة."""
    found = store.load_draft(draft_id)
    if not found:
        log.warning("لا مسودة بالمعرّف %s", draft_id)
        return None
    path, draft = found

    # نتحقق قبل البناء: الرابط قد يكون صفحة لا صورة، أو صورة صغيرة
    # لا تصلح خلفية. الفشل هنا أرخص من بطاقة مشوّهة.
    if download_image(url) is None:
        log.warning("رابط غير صالح كصورة: %s", url[:90])
        return None

    spec = draft.get("reel_spec") or {}
    ar = draft.get("arabic") or {}
    headline = (spec.get("headline") or ar.get("image_headline")
                or ar.get("post_title") or draft["source"]["title"])
    new_rel = next_image_path(draft["image"])
    # new_rel نص لعنوان الصورة داخل المستودع (يبدأ بـ "drafts/" دومًا —
    # يلزم لبناء raw_url في review.py) لا مسار كتابة فعلي؛ الكتابة نفسها
    # يجب أن تمرّ عبر DRAFTS_DIR لا ROOT مباشرة، وإلا تجاوزت عزل الاختبارات
    # (TRENDNEWS_DRAFTS_DIR) وكتبت داخل drafts/ الحقيقي في المستودع.
    out_path = DRAFTS_DIR / Path(new_rel).relative_to("drafts")

    build_post_image(
        headline=headline,
        category=spec.get("category") or ar.get("category", ""),
        urgent=bool(spec.get("urgent") or ar.get("urgent")),
        image_urls=[url],
        publisher=draft["source"].get("publishers") or [draft["source"].get("publisher", "")],
        bucket=draft.get("bucket", "serious"),
        cfg=cfg,
        out_path=out_path,
        # لا بديل تلقائي: طلب المراجع صورة بعينها، فالصمت عند فشلها
        # أصدق من إحلال صورة أخرى محلها دون علمه.
        fallback_provider=None,
    )

    old_rel = draft["image"]
    draft = store.update_draft(
        path,
        image=new_rel,
        has_photo=True,
        manual_image=url,
        source={**draft["source"], "image_url": url, "image_candidates": [url]},
        reel_spec={**spec, "image_candidates": [url]},
        reel=None,          # الريل القديم بُني على الصورة القديمة
    )
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

    # الخريطة تُبنى من نص الـ Issue الآن تحديدًا، لا من ترتيب مخزَّن سابقًا:
    # رقم الترتيب يتغيّر إن أُضيفت مسودة جديدة أو حُذفت بين تشغيلتين.
    issue_body = review.fetch_issue_body(args.issue) if args.issue else ""
    index_map = review.draft_index_map(issue_body) if issue_body else {}

    pairs, unresolved_refs = parse_commands(args.body, index_map)

    missing_links: list[dict] = []
    if args.from_issue and args.issue:
        # المربعات هي الواجهة الأساسية؛ أوامر التعليق بديل لمن يفضّلها
        resolved, missing_ids = review.parse_image_requests(issue_body)
        pairs += [p for p in resolved if p not in pairs]
        for draft_id in missing_ids:
            found = store.load_draft(draft_id)
            title = found[1]["arabic"]["post_title"][:60] if found else draft_id
            missing_links.append({"id": draft_id, "title": title})

    if args.draft and args.url:
        pairs.append((args.draft, args.url))
    if not pairs and not unresolved_refs and not missing_links:
        log.error("لا أمر صورة صالح. الصيغة: /صورة رقم_الترتيب_أو_المعرّف رابط_الصورة")
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
            done.append({"id": draft_id,
                         "old": updated["_old_image"],
                         "new": updated["image"],
                         "title": updated["arabic"]["post_title"][:60]})
        else:
            failed.append(draft_id)

    SYNC_FILE.write_text(
        json.dumps({"done": done, "failed": failed,
                    "missing_links": missing_links,
                    "unresolved_refs": unresolved_refs}, ensure_ascii=False),
        encoding="utf-8")
    return 0 if done else 1


def sync_issue(issue: int) -> int:
    """يُشغَّل بعد رفع الصورة: يبدّل مسارها في الـ Issue ويعلّق بالنتيجة."""
    if not issue or not SYNC_FILE.exists():
        return 0
    data = json.loads(SYNC_FILE.read_text(encoding="utf-8"))
    done, failed = data.get("done", []), data.get("failed", [])
    missing_links = data.get("missing_links", [])
    unresolved_refs = data.get("unresolved_refs", [])

    if done or failed:
        body = review.fetch_issue_body(issue)
        for item in done:
            body = body.replace(item["old"], item["new"])
            body = review.clear_image_request(body, item["id"])
        for draft_id in failed:
            # يبقى الرابط ليصحّحه المراجع بدل أن يعيد لصقه من جديد
            body = review.clear_image_request(body, draft_id, keep_url=True)
        review.update_issue_body(issue, body)

    notes = [f"🖼️ حُدّثت الصورة: {item['title']}" for item in done]
    notes += [f"⚠️ تعذّر تحديث `{i}` — تأكد أن الرابط لصورة مباشرة "
              "(ينتهي بـ .jpg أو .png) وأن أبعادها ليست صغيرة." for i in failed]
    # فشل صامت سابق: مربع مُعلَّم بلا رابط كان يُهمَل بلا أي تنبيه.
    notes += [f"⚠️ المربع مُعلَّم لـ«{item['title']}» لكن سطر «الرابط:» "
              "فارغ — أضف الرابط فيه ثم احفظ." for item in missing_links]
    notes += [f"⚠️ لا مسودة بالرقم `{ref}` — رقم الترتيب قد يكون تغيّر، "
              "تحقّق من الرقم الظاهر الآن في القائمة أو استعمل المعرّف الكامل."
              for ref in unresolved_refs]
    if notes:
        review.comment(issue, "\n".join(notes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
