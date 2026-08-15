"""جلب النص الكامل لخبر واحد من عدة ناشرين، لتغذية التحليل.

لماذا عدة مصادر؟ لأن قراءة مصدر واحد تعطي روايته وحدها. قراءة ثلاثة
تكشف ما تتفق عليه المصادر (حقيقة راسخة) وما تنفرد به (رواية طرف) —
وهذا وحده تحليل لا يملكه أي مصدر منفرد.

قاعدة صارمة: إن تعذّر الجلب، نُعيد قائمة فارغة. النموذج حينها لن يحلل،
وهذا مقصود — التحليل بلا مادة اختراع.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import requests

from .sources import HEADERS

log = logging.getLogger(__name__)

try:
    import trafilatura
    HAS_EXTRACTOR = True
except ImportError:  # pragma: no cover
    HAS_EXTRACTOR = False
    log.warning("trafilatura غير مثبّتة — التحليل متعدد المصادر معطّل")

MIN_CHARS = 400          # أقل من ذلك = صفحة اشتراك أو حظر لا مقال
MAX_CHARS = 2500         # سقف لكل مصدر — الفقرات الأولى تحمل الجوهر


def fetch_text(url: str, timeout: int = 20) -> tuple[str | None, str]:
    """يجلب النص الأساسي لمقال واحد، بلا قوائم تنقّل ولا إعلانات.

    يعيد (النص، "") عند النجاح، أو (None, سبب الفشل) عند الفشل — البند 1
    (تعليق العطل الثاني على Issue #361): سجلّ trail في article.py يحتاج
    سبب فشل كل رابط تعذّر جلبه (رمز HTTP أو نوع العطل) لا صمتًا واحدًا
    يظهر "عناوين فقط" مجرَّدة بلا تفصيل يشرح لماذا."""
    if not HAS_EXTRACTOR:
        return None, "المستخرج trafilatura غير مثبَّت"
    if not url:
        return None, "بلا رابط"
    if "news.google.com" in url:      # رابط وسيط لا مقال
        return None, "رابط جوجل الوسيط لم يُحلّ إلى رابط مقال فعلي"
    try:
        # Referer يحاكي وصولًا من Google News (تشخيص Issue #373، البند 3):
        # France 24 والعربية وأورينت نت تحجب الطلب المباشر بـHTTP 403 شبه
        # دائم — بعض الناشرين يسمحون بحركة إحالة من جوجل تحديدًا حتى مع حجب
        # الزحف المباشر بلا هذا الرأس. علاج رخيص (رأس واحد إضافي) يستحق
        # التجربة قبل أي شيء أثقل — لا يحل حجب النطاق الشبكي نفسه إن وُجد.
        resp = requests.get(
            url, headers={**HEADERS, "Referer": "https://news.google.com/"},
            timeout=timeout)
    except requests.Timeout:
        return None, "انتهت مهلة الاتصال"
    except requests.RequestException as exc:
        return None, f"عطل شبكة ({type(exc).__name__})"
    if resp.status_code != 200:
        log.debug("تعذّر جلب %s: %s", url[:60], resp.status_code)
        return None, f"HTTP {resp.status_code}"
    try:
        text = trafilatura.extract(
            resp.text, include_comments=False, include_tables=False,
            no_fallback=False,
        )
    except Exception as exc:  # noqa: BLE001 — استخراج trafilatura قد يطرح أي شيء
        log.debug("فشل استخراج %s: %s", url[:60], exc)
        return None, f"عطل استخراج ({type(exc).__name__})"

    if not text:
        return None, "لم يُستخرَج نص (بنية صفحة غير مدعومة أو محتوى غير نصي)"
    if len(text) < MIN_CHARS:
        return None, f"نص قصير جدًا ({len(text)} حرف) — صفحة اشتراك/حظر محتملة"
    return text[:MAX_CHARS], ""


def gather(members: list[dict], limit: int = 2,
          workers: int = 4) -> tuple[list[dict], list[dict]]:
    """
    يجلب نصوص عدة نسخ من الخبر نفسه.

    members: [{"name": "BBC", "link": "https://..."}, ...]
    يعيد (نجاحات، فشليات):
    - نجاحات: [{"name":..., "text":...}] — كما كانت.
    - فشليات: [{"name":..., "link":..., "reason":...}] لكل رابط تعذّر جلبه
      — البند 1 (تعليق العطل الثاني على Issue #361): بلا هذا السجل، trail
      لا يملك سببًا لماذا سقط استعلام معيَّن لاحتياط العناوين.

    يحاول أول limit*2 مرشح دفعة واحدة (يكفي عادة، ويوفّر زمن الجلب حين
    تنجح الدفعة الأولى)، ثم يواصل بدفعات تالية من members حتى يبلغ limit
    نجاحًا أو تنفد المرشحات — لا يقف عند أول limit*2 محاولة مهما فشلت
    (تشخيص Issue #373، البند 3: ناشرون محجوبون بحجب شبه دائم (HTTP 403)
    قد يتصدّرون الدفعة الأولى فتُهدر فتحات القراءة كلها بلا أي فرصة لمرشح
    لاحق قابل للجلب فعليًا — members أصلًا محدودة العدد (gather_evidence
    تمرّر max_members=limit*4 كسقف)، فمواصلة المحاولة بلا توقف مبكر مأمونة
    التكلفة).
    """
    if not HAS_EXTRACTOR:
        return [], [{"name": m.get("name", "؟"), "link": m.get("link", ""),
                     "reason": "المستخرج trafilatura غير مثبَّت"} for m in members]

    candidates = [m for m in members if m.get("link")]
    if not candidates:
        return [], []

    out: list[dict] = []
    failures: list[dict] = []
    batch_size = limit * 2
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(candidates), batch_size):
            if len(out) >= limit:
                break
            batch = candidates[start:start + batch_size]
            results = pool.map(lambda m: fetch_text(m["link"]), batch)
            for member, (text, reason) in zip(batch, results):
                if text:
                    out.append({"name": member.get("name", "؟"), "text": text})
                else:
                    failures.append({"name": member.get("name", "؟"),
                                     "link": member.get("link", ""), "reason": reason})
                if len(out) >= limit:
                    break

    log.info("نصوص مُستخرجة: %d من %d محاولة", len(out), len(out) + len(failures))
    return out, failures


def format_for_prompt(docs: list[dict]) -> str:
    """يصوغ النصوص لإدراجها في الطلب، معلّمة باسم كل مصدر."""
    if not docs:
        return ""
    blocks = [
        f"--- المصدر {i}: {d['name']} ---\n{d['text']}"
        for i, d in enumerate(docs, start=1)
    ]
    return "\n\n".join(blocks)
