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
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
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
      قبل بلوغ limit — البند 1 (تعليق العطل الثاني على Issue #361): بلا هذا
      السجل، trail لا يملك سببًا لماذا سقط استعلام معيَّن لاحتياط العناوين.
    """
    if not HAS_EXTRACTOR:
        return [], [{"name": m.get("name", "؟"), "link": m.get("link", ""),
                     "reason": "المستخرج trafilatura غير مثبَّت"} for m in members]

    candidates = [m for m in members if m.get("link")][: limit * 2]
    if not candidates:
        return [], []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda m: fetch_text(m["link"]), candidates))

    out: list[dict] = []
    failures: list[dict] = []
    for member, (text, reason) in zip(candidates, results):
        if text:
            out.append({"name": member.get("name", "؟"), "text": text})
        else:
            failures.append({"name": member.get("name", "؟"),
                             "link": member.get("link", ""), "reason": reason})
        if len(out) >= limit:
            break

    log.info("نصوص مُستخرجة: %d من %d محاولة", len(out), len(candidates))
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
