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

import json
import logging
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from .config import STATE_DIR
from .sources import HEADERS

log = logging.getLogger(__name__)

WIKI_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
BRAVE_IMAGES_API = "https://api.search.brave.com/res/v1/images/search"
BRAVE_USAGE_FILE = STATE_DIR / "brave_usage.json"
_no_key_logged = False

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


def find_images(title: str, cfg, limit: int = 6, terms: list[str] | None = None) -> list[str]:
    """
    يعيد روابط صور حرة الترخيص مرشحة للخبر.

    نجرّب كل عبارة بحث لدى كل مزوّد ونجمع النتائج بالترتيب — الأعلام أولًا
    لأنها تعطي أدق الصور.

    `terms` اختياري (تشخيص Issue #373، مراجعة بشرية بعد أول نشر، البند 1):
    keywords() أعلاه تستخرج فقط أحرفًا لاتينية كبيرة (_CAP_RUN/_WORD)،
    مصمَّمة لعناوين RSS الأصلية (title بلغة المصدر، غالبًا لاتينية) —
    عنوان/نص عربي محض يعيد منها قائمة فارغة دومًا فيُسقط find_images إلى
    صفر نتائج قبل أي نداء شبكة، بصرف النظر عن محتواه. مُستدعٍ يملك عبارات
    بحث جاهزة بلغة أخرى (article.py: كيانات entities المستخرَجة من موجز
    عربي) يمرّرها هنا مباشرة فتتجاوز keywords() كليًا؛ None (الافتراضي)
    يُبقي السلوك القديم لكل المستدعين الآخرين (writer.py/collect.py/
    radar.py/verify_draft.py) بلا أي تغيير.
    """
    icfg = cfg.get("image_search", {}) or {}
    if not icfg.get("enabled", True):
        return []

    terms = terms if terms is not None else keywords(title, int(icfg.get("max_terms", 3)))
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


# ───────────────────── بحث صور الويب (Brave) ─────────────────────
# خلافًا لويكيميديا/Openverse أعلاه، نتائج هذا البحث صور أخبار حقيقية بلا
# ترخيص حرّ — لذلك تُعامَل في imaging.build_post_image معاملة صورة الخبر
# (بلا وسم «صورة تعبيرية»، بلا فحص وجه) ويراجعها المراجع قبل الاعتماد
# (review.image_source_line).


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def brave_usage(month: str | None = None) -> int:
    """عدد طلبات Brave هذا الشهر من state/brave_usage.json (0 إن غاب/تلف)."""
    try:
        data = json.loads(BRAVE_USAGE_FILE.read_text(encoding="utf-8"))
        return int(data.get(month or _month_key(), 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def _bump_brave_usage() -> int:
    """يزيد عدّاد الشهر 1 ويحفظه فورًا (قبل الطلب لا بعده): Brave لا تضع سقفًا
    من جهتها فالسقف حماية لبطاقة الدفع، وطلب فاشل يُحتسب أيضًا لأنه قد يُفوتَر.
    الكتابة عبر ملف مؤقت ثم استبدال كي لا يُترك JSON نصف مكتوب عند انقطاع."""
    month = _month_key()
    try:
        data = json.loads(BRAVE_USAGE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data[month] = int(data.get(month, 0) or 0) + 1
    BRAVE_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = BRAVE_USAGE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, BRAVE_USAGE_FILE)
    return data[month]


def _domain_excluded(host: str, excluded: list[str]) -> bool:
    host = (host or "").lower()
    return any(ex.lower() in host for ex in excluded if ex)


def search_web_images(query: str, cfg, state: dict | None = None) -> list[dict]:
    """بحث صور الويب عبر Brave Search API → ``[{"url", "domain"}, ...]``.

    لكل نتيجة (بعد استبعاد نطاقات الوكالات ذات العلامة المائية، وحتى
    ``max_tries`` نتيجة) يُعاد properties.url ثم thumbnail.src مباشرة بعده
    بالنطاق نفسه — يجرّب المستدعي الأصل فإن فشل تحميله جرّب المصغّرة.

    ``state`` (اختياري) يُملأ بـ``skipped`` = "no_key" | "cap" حين تُتخطى
    المرحلة دون أي طلب، كي يصل السبب إلى image_info.web_search_skipped. كل
    فشل شبكة يُسجَّل ويعيد قائمة فارغة — المرحلة اختيارية ولا تُسقط البطاقة."""
    global _no_key_logged
    state = state if state is not None else {}
    wcfg = cfg.path("image.web_search", {}) or {}
    if not wcfg.get("enabled", True) or not (query or "").strip():
        return []

    key = os.environ.get("BRAVE_API_KEY", "").strip()
    if not key:
        state["skipped"] = "no_key"
        if not _no_key_logged:
            log.info("بحث صور الويب متخطّى: لا BRAVE_API_KEY")
            _no_key_logged = True
        return []

    cap = int(wcfg.get("monthly_cap", 800))
    if brave_usage() >= cap:
        state["skipped"] = "cap"
        log.warning("بحث صور الويب متوقف: بلغ السقف الشهري (%d)", cap)
        return []

    _bump_brave_usage()
    try:
        resp = requests.get(
            BRAVE_IMAGES_API,
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            params={"q": query, "safesearch": "strict",
                    "count": int(wcfg.get("count", 10))},
            timeout=15,
        )
        if resp.status_code != 200:
            log.info("Brave: HTTP %s", resp.status_code)
            return []
        results = (resp.json() or {}).get("results") or []
    except (requests.RequestException, ValueError) as exc:
        log.info("Brave: تعذّر البحث: %s", exc)
        return []

    excluded = list(wcfg.get("excluded_domains") or [])
    max_tries = int(wcfg.get("max_tries", 6))
    out: list[dict] = []
    kept = 0
    for res in results:
        if kept >= max_tries:
            break
        page = res.get("url") or ""
        domain = urlparse(page).netloc.lower() or (res.get("source") or "")
        # نطاق الصفحة وحده لا يكفي: موقع إخباري قد يعرض صورة مستضافة عند
        # وكالة بعلامتها المائية، فيُفحص نطاق properties.url أيضًا. المصغّرة
        # تمرّ دائمًا عبر imgs.search.brave.com فلا يكشفها فحص نطاقها، لذا
        # تُستبعد النتيجة كاملة (الأصل والمصغّرة معًا) بمطابقة أيٍّ من النطاقين.
        orig_url = (res.get("properties") or {}).get("url") or ""
        orig_host = urlparse(orig_url).netloc.lower()
        hit = next((h for h in (domain, orig_host)
                    if _domain_excluded(h, excluded)), None)
        if hit:
            log.info("Brave: نتيجة مستبعدة (نطاق تجاري: %s)", hit)
            continue
        kept += 1
        for url in ((res.get("properties") or {}).get("url"),
                    (res.get("thumbnail") or {}).get("src")):
            if url and not any(o["url"] == url for o in out):
                out.append({"url": url, "domain": domain})
    log.info("Brave «%s»: %d رابطًا من %d نتيجة", query[:60], len(out), len(results))
    return out
