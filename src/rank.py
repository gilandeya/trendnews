"""دمج الأخبار المتكررة وترتيبها حسب قوة الترند."""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from datetime import datetime, timezone

from .sources import Article

log = logging.getLogger(__name__)

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for", "with",
    "from", "by", "as", "is", "are", "was", "were", "be", "been", "will", "has",
    "have", "had", "it", "its", "this", "that", "after", "over", "new", "says",
    "said", "amid", "into", "out", "up", "down", "his", "her", "their", "he",
    "she", "they", "we", "you", "not", "but", "than", "then", "more", "most",
}

_WORD_RE = re.compile(r"[A-Za-z\u00C0-\u024F0-9']+")


def tokens(title: str) -> set[str]:
    words = [w.lower() for w in _WORD_RE.findall(title)]
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def similarity(a: set[str], b: set[str]) -> float:
    """معامل جاكارد المرجّح — بسيط وفعّال لعناوين الأخبار."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / min(len(a), len(b))


def cluster(articles: list[Article], threshold: float) -> list[list[Article]]:
    """تجميع جشع: أول خبر يمثّل المجموعة، وما يشبهه يُضاف إليها."""
    clusters: list[list[Article]] = []
    signatures: list[set[str]] = []

    for art in sorted(articles, key=lambda a: (-a.weight, a.published)):
        sig = tokens(art.title)
        placed = False
        for idx, existing in enumerate(signatures):
            if similarity(sig, existing) >= threshold:
                clusters[idx].append(art)
                signatures[idx] = existing | sig
                placed = True
                break
        if not placed:
            clusters.append([art])
            signatures.append(sig)
    return clusters


def freshness(published: datetime, max_age_hours: int) -> float:
    age_h = (datetime.now(timezone.utc) - published).total_seconds() / 3600
    return max(0.0, 1.0 - (age_h / max(max_age_hours, 1)))


def score_cluster(group: list[Article], max_age_hours: int) -> float:
    """
    مؤشر الترند =
        تغطية المصادر (لوغاريتمي)  ×3
      + التنوع الجغرافي            ×2
      + وزن المصدر (الأعلى)        ×1.5
      + الحداثة                    ×2
      + توفّر صورة                 ×0.8
    """
    distinct_sources = len({a.source_name for a in group})
    distinct_regions = len({a.region for a in group})
    newest = max(a.published for a in group)
    top_weight = max(a.weight for a in group)
    has_image = any(a.image_url for a in group)

    return (
        3.0 * math.log2(1 + distinct_sources)
        + 2.0 * math.log2(1 + distinct_regions)
        + 1.5 * top_weight
        + 2.0 * freshness(newest, max_age_hours)
        + (0.8 if has_image else 0.0)
    )


def pick_representative(group: list[Article]) -> Article:
    """يختار أفضل نسخة من الخبر: صورة موجودة، ثم أعلى وزن، ثم الأحدث."""
    best = sorted(
        group,
        key=lambda a: (a.image_url is not None, a.weight, a.published),
        reverse=True,
    )[0]
    best.cluster_sources = sorted({a.publisher or a.source_name for a in group})
    return best


def is_blocked(article: Article, keywords: list[str]) -> bool:
    haystack = f"{article.title} {article.summary}".lower()
    return any(kw.lower() in haystack for kw in keywords)


def rank(articles: list[Article], selection: dict) -> list[Article]:
    threshold = float(selection.get("title_similarity", 0.62))
    max_age = int(selection.get("max_age_hours", 18))
    min_sources = int(selection.get("min_sources_for_trend", 1))
    blocklist = selection.get("blocklist_keywords") or []
    diversity = bool(selection.get("region_diversity", True))
    per_region = int(selection.get("max_per_region", 3))

    groups = cluster(articles, threshold)
    log.info("تم دمج %d خبر في %d موضوع", len(articles), len(groups))

    ranked: list[Article] = []
    for group in groups:
        if len({a.source_name for a in group}) < min_sources:
            continue
        rep = pick_representative(group)
        if is_blocked(rep, blocklist):
            continue
        rep.score = score_cluster(group, max_age)
        ranked.append(rep)

    ranked.sort(key=lambda a: a.score, reverse=True)

    if not diversity:
        return ranked

    # حد أعلى لعدد الأخبار من نفس المنطقة، ثم يُلحق الباقي في نهاية القائمة
    # (لا نحذفه: قد نحتاجه إن رفض النموذج أخبارًا أخرى)
    seen: Counter = Counter()
    primary: list[Article] = []
    overflow: list[Article] = []
    for art in ranked:
        if seen[art.region] >= per_region:
            overflow.append(art)
            continue
        seen[art.region] += 1
        primary.append(art)
    return primary + overflow
