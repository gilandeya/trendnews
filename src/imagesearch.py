"""البحث عن صورة بديلة حرة الترخيص حين لا يوفّر الناشر صورة.

⚠️ لماذا لا نبحث في جوجل صور؟ لأن نتائجه محمية بحقوق النشر. وكالات
الصور ترصد الاستخدام غير المرخّص، ولفيسبوك نظام آلي (Rights Manager)
قد يحجب المنشور أو يقيّد الصفحة. مصدر واحد مخالف يكفي.

لذلك نبحث في مكتبتين مجانيتين بالكامل:
  • ويكيميديا كومنز — ممتاز للأعلام والمدن والمعالم والمؤسسات
  • Openverse — يجمع صورًا برخص المشاع الإبداعي من عشرات المصادر

وأي صورة من هنا تُوسم على الكارت بعبارة "صورة تعبيرية"، لأنها ليست من
مكان الحدث — وإخفاء ذلك عن القارئ تضليل.
"""
from __future__ import annotations

import logging
import re

import requests

from .sources import HEADERS

log = logging.getLogger(__name__)

WIKI_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"

# كلمات لا تصلح للبحث البصري
STOP = {
    "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for", "with",
    "from", "by", "as", "is", "are", "was", "were", "be", "been", "will", "has",
    "have", "had", "it", "its", "this", "that", "after", "over", "new", "says",
    "said", "amid", "into", "out", "up", "down", "his", "her", "their", "they",
    "we", "you", "not", "but", "than", "then", "more", "most", "first", "last",
    "report", "reports", "reveals", "announces", "could", "would", "may",
    "find", "finds", "found", "make", "makes", "take", "takes", "gets",
    "acquits", "warns", "urges", "calls", "plans", "sets", "adds", "shows",
    "total", "full", "major", "top", "best", "worst", "how", "why", "what",
}

# كلمات شائعة تبدأ بها الجُمل فتُكتب بحرف كبير وتبدو أسماء أعلام
SENTENCE_STARTERS = {
    "court", "total", "study", "report", "police", "officials", "scientists",
    "researchers", "experts", "video", "watch", "breaking", "exclusive",
    "update", "opinion", "analysis", "here", "these", "there", "after",
    "before", "during", "why", "how", "what", "when", "where", "who",
}

_CAP_RUN = re.compile(r"\b([A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,}){0,2})\b")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")


def keywords(title: str, limit: int = 3) -> list[str]:
    """
    يستخرج عبارات بحث من العنوان الأصلي.

    الأولوية للأعلام (الكلمات المبدوءة بحرف كبير) لأنها تعطي صورًا محددة
    — اسم مدينة أو شخص أو مؤسسة — بدل صور عامة لا تعني شيئًا.
    """
    phrases: list[str] = []
    for match in _CAP_RUN.finditer(title):
        phrase = match.group(1).strip()
        low = phrase.lower()
        # كلمة واحدة أول الجملة قد تكون شائعة لا اسم عَلَم
        if (match.start() == 0 and " " not in phrase
                and low in SENTENCE_STARTERS):
            continue
        if low in STOP or phrase in phrases:
            continue
        phrases.append(phrase)

    if len(phrases) < limit:
        plain = [w for w in _WORD.findall(title.lower())
                 if w not in STOP and len(w) > 3]
        for word in plain:
            if word not in [p.lower() for p in phrases]:
                phrases.append(word)
            if len(phrases) >= limit:
                break

    return phrases[:limit]


# ──────────────────────────── المزوّدون ────────────────────────────


def search_wikimedia(query: str, limit: int = 4, timeout: int = 15) -> list[str]:
    """ويكيميديا كومنز — كل محتواه حر الاستخدام."""
    try:
        resp = requests.get(
            WIKI_API,
            params={
                "action": "query", "format": "json",
                "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
                "gsrnamespace": "6", "gsrlimit": str(limit),
                "prop": "imageinfo", "iiprop": "url|size",
                "iiurlwidth": "1200",
            },
            headers=HEADERS, timeout=timeout,
        )
        pages = (resp.json().get("query") or {}).get("pages") or {}
    except (requests.RequestException, ValueError) as exc:
        log.debug("فشل بحث ويكيميديا: %s", exc)
        return []

    out: list[tuple[int, str]] = []
    for page in pages.values():
        for info in page.get("imageinfo") or []:
            url = info.get("thumburl") or info.get("url")
            width = int(info.get("width") or 0)
            if url and width >= 600:
                out.append((width, url))
    out.sort(key=lambda t: -t[0])
    return [u for _, u in out]


def search_openverse(query: str, limit: int = 4, timeout: int = 15) -> list[str]:
    """Openverse — صور برخص المشاع الإبداعي تسمح بالاستخدام التجاري."""
    try:
        resp = requests.get(
            OPENVERSE_API,
            params={
                "q": query, "page_size": str(limit),
                "license_type": "commercial",   # يسمح بالاستخدام التجاري
                "mature": "false",
                "aspect_ratio": "wide",
            },
            headers={**HEADERS, "Accept": "application/json"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return []
        results = resp.json().get("results") or []
    except (requests.RequestException, ValueError) as exc:
        log.debug("فشل بحث Openverse: %s", exc)
        return []

    return [r["url"] for r in results if r.get("url")]


PROVIDERS = {
    "wikimedia": search_wikimedia,
    "openverse": search_openverse,
}


def find_images(title: str, cfg, limit: int = 6) -> list[str]:
    """
    يعيد روابط صور حرة الترخيص مرشحة للخبر.

    نجرّب كل عبارة بحث لدى كل مزوّد ونجمع النتائج بالترتيب — الأعلام أولًا
    لأنها تعطي أدق الصور.
    """
    icfg = cfg.get("image_search", {}) or {}
    if not icfg.get("enabled", True):
        return []

    terms = keywords(title, int(icfg.get("max_terms", 3)))
    if not terms:
        return []

    providers = icfg.get("providers") or ["wikimedia", "openverse"]
    found: list[str] = []

    for term in terms:
        for name in providers:
            fn = PROVIDERS.get(name)
            if not fn:
                continue
            for url in fn(term):
                if url not in found:
                    found.append(url)
            if len(found) >= limit:
                log.info("صور بديلة لـ «%s»: %d نتيجة", term, len(found))
                return found[:limit]

    log.info("صور بديلة: %d نتيجة من %s", len(found), "، ".join(terms))
    return found[:limit]
