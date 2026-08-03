"""جلب الموضوعات الأكثر بحثًا من Google Trends لاستخدامها كإشارة انتشار.

خلاصات RSS تخبرنا بما *نشرته* غرف الأخبار. Google Trends يخبرنا بما
*يبحث عنه الناس* فعلًا الآن — وهو أقرب مؤشر مجاني لما ينتشر على مواقع
التواصل. ندمج الإشارتين: خبر تغطيه عدة وكالات ويطابق موضوعًا رائجًا
يحصل على أعلى درجة.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import feedparser
import requests

from .rank import tokens
from .sources import HEADERS

log = logging.getLogger(__name__)

# نقطتان: الجديدة أولًا، والقديمة احتياطًا (جوجل غيّر المسار)
ENDPOINTS = (
    "https://trends.google.com/trending/rss?geo={geo}",
    "https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}",
)


def fetch_geo(geo: str, timeout: int = 15) -> list[str]:
    """يعيد عناوين الموضوعات الرائجة في بلد واحد."""
    for template in ENDPOINTS:
        url = template.format(geo=geo)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            if resp.status_code != 200:
                continue
            feed = feedparser.parse(resp.content)
            titles = [e.get("title", "").strip() for e in feed.entries]
            titles = [t for t in titles if t]
            if titles:
                log.info("Trends %s: %d موضوع", geo, len(titles))
                return titles
        except requests.RequestException as exc:
            log.debug("تعذّر جلب Trends لـ %s: %s", geo, exc)
    log.warning("لا موضوعات رائجة من %s", geo)
    return []


def trending_signatures(geos: list[str]) -> list[set[str]]:
    """
    يعيد بصمات الموضوعات الرائجة (مجموعات كلمات) لمطابقتها بعناوين الأخبار.

    نستخدم مجموعات كلمات لا نصوصًا خامًا، لأن الموضوع الرائج قد يكون اسم
    شخص أو مكان يظهر داخل عنوان أطول بصياغة مختلفة.
    """
    signatures: list[set[str]] = []
    seen: set[frozenset] = set()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch_geo, geos))

    for titles in results:
        for title in titles:
            sig = tokens(title)
            if not sig:
                continue
            key = frozenset(sig)
            if key not in seen:
                seen.add(key)
                signatures.append(sig)

    log.info("إجمالي الموضوعات الرائجة الفريدة: %d", len(signatures))
    return signatures


def trend_match(title_tokens: set[str], signatures: list[set[str]]) -> float:
    """
    قوة مطابقة عنوان لأي موضوع رائج، من 0 إلى 1.

    نقيس نسبة كلمات *الموضوع الرائج* الموجودة في العنوان — لا العكس —
    لأن الموضوع قصير (كلمة أو اسم) والعنوان طويل.
    """
    best = 0.0
    for sig in signatures:
        if not sig:
            continue
        overlap = len(sig & title_tokens) / len(sig)
        best = max(best, overlap)
        if best >= 1.0:
            break
    return best
