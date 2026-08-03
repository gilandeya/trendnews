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
MAX_CHARS = 6000         # سقف لكل مصدر لضبط التكلفة


def fetch_text(url: str, timeout: int = 20) -> str | None:
    """يجلب النص الأساسي لمقال واحد، بلا قوائم تنقّل ولا إعلانات."""
    if not HAS_EXTRACTOR or not url:
        return None
    if "news.google.com" in url:      # رابط وسيط لا مقال
        return None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200:
            log.debug("تعذّر جلب %s: %s", url[:60], resp.status_code)
            return None
        text = trafilatura.extract(
            resp.text, include_comments=False, include_tables=False,
            no_fallback=False,
        )
    except (requests.RequestException, Exception) as exc:  # noqa: BLE001
        log.debug("فشل استخراج %s: %s", url[:60], exc)
        return None

    if not text or len(text) < MIN_CHARS:
        return None
    return text[:MAX_CHARS]


def gather(members: list[dict], limit: int = 3, workers: int = 4) -> list[dict]:
    """
    يجلب نصوص عدة نسخ من الخبر نفسه.

    members: [{"name": "BBC", "link": "https://..."}, ...]
    يعيد فقط ما نجح جلبه: [{"name":..., "text":...}]
    """
    if not HAS_EXTRACTOR:
        return []

    candidates = [m for m in members if m.get("link")][: limit * 2]
    if not candidates:
        return []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        texts = list(pool.map(lambda m: fetch_text(m["link"]), candidates))

    out: list[dict] = []
    for member, text in zip(candidates, texts):
        if text:
            out.append({"name": member.get("name", "؟"), "text": text})
        if len(out) >= limit:
            break

    log.info("نصوص مُستخرجة: %d من %d محاولة", len(out), len(candidates))
    return out


def format_for_prompt(docs: list[dict]) -> str:
    """يصوغ النصوص لإدراجها في الطلب، معلّمة باسم كل مصدر."""
    if not docs:
        return ""
    blocks = [
        f"--- المصدر {i}: {d['name']} ---\n{d['text']}"
        for i, d in enumerate(docs, start=1)
    ]
    return "\n\n".join(blocks)
