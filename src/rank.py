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


def score_cluster(group: list[Article], max_age_hours: int,
                  trend: float = 0.0, trend_weight: float = 4.0,
                  vel: dict | None = None, vel_weight: float = 5.0) -> float:
    """
    مؤشر الترند =
        تغطية المصادر (لوغاريتمي)  ×3
      + التنوع الجغرافي            ×2
      + وزن المصدر (الأعلى)        ×1.5
      + الحداثة                    ×2
      + توفّر صورة                 ×0.8
      + مطابقة Google Trends       ×trend_weight
      + سرعة الانتشار              ×vel_weight

    آخر إشارتين هما الأهم: الأولى *الطلب* (ما يبحث عنه الناس)، والثانية
    *التسارع* (كم مصدرًا جديدًا التقط الخبر منذ آخر تشغيلة). خبر ثابت منذ
    يومين يُخصم منه، مهما اتسعت تغطيته.
    ويُخصم نصف نقطة إن كان كل مصادر الخبر إعلامًا رسميًا.
    """
    distinct_sources = len({a.source_name for a in group})
    distinct_regions = len({a.region for a in group})
    newest = max(a.published for a in group)
    top_weight = max(a.weight for a in group)
    has_image = any(a.image_candidates for a in group)
    all_state = all(a.state_media for a in group)

    return (
        3.0 * math.log2(1 + distinct_sources)
        + 2.0 * math.log2(1 + distinct_regions)
        + 1.5 * top_weight
        + 2.0 * freshness(newest, max_age_hours)
        + (0.8 if has_image else 0.0)
        + trend_weight * trend
        + vel_weight * (vel or {}).get("velocity", 0.0)
        - (2.0 if (vel or {}).get("stale") else 0.0)
        - (0.5 if all_state else 0.0)
    )


def pick_representative(group: list[Article]) -> Article:
    """
    يختار أفضل نسخة من الخبر، ويستعير صور بقية النسخ.

    هذا مهم: قد يكون الخبر من Google News (بلا صورة) بينما نسخة BBC من
    الحدث نفسه تحمل صورة حقيقية — فنأخذ نص الأقوى وصورة من يملكها.
    """
    from .sources import is_generic_image

    def key(a: Article):
        return (
            bool(a.image_candidates),               # يملك صورة
            "news.google.com" not in a.link,        # ناشر مباشر
            a.weight,
            a.published,
        )

    best = max(group, key=key)
    best.cluster_sources = sorted({a.publisher or a.source_name for a in group})

    # روابط كل النسخ، الأثقل وزنًا أولًا، بلا روابط جوجل الوسيطة
    seen_links: set[str] = set()
    members: list[dict] = []
    for a in sorted(group, key=lambda x: -x.weight):
        if a.link in seen_links or "news.google.com" in a.link:
            continue
        seen_links.add(a.link)
        members.append({"name": a.publisher or a.source_name, "link": a.link})
    best.cluster_members = members[:6]

    # ادمج مرشحي الصور من كل النسخ، مع الحفاظ على الترتيب وبلا تكرار
    merged: list[str] = list(best.image_candidates)
    for art in sorted(group, key=lambda a: -a.weight):
        for url in art.image_candidates:
            if url not in merged and not is_generic_image(url):
                merged.append(url)
    best.image_candidates = merged[:6]
    best.image_url = merged[0] if merged else None

    # لو غطّى الحدثَ مصدرٌ خفيف ومصدرٌ جاد، فهو خبر خفيف قابل للانتشار
    buckets = {a.bucket for a in group}
    for pref in ("light", "sport"):
        if pref in buckets:
            best.bucket = pref
            break
    return best


def is_blocked(article: Article, keywords: list[str]) -> bool:
    haystack = f"{article.title} {article.summary}".lower()
    return any(kw.lower() in haystack for kw in keywords)


def rank(articles: list[Article], selection: dict,
         trend_signatures: list[set[str]] | None = None,
         trend_weight: float = 4.0,
         velocity_entries: list[dict] | None = None,
         velocity_weight: float = 5.0) -> list[Article]:
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

        trend = 0.0
        if trend_signatures:
            from .trends import trend_match
            trend = max(trend_match(tokens(a.title), trend_signatures) for a in group)

        vel = None
        if velocity_entries is not None:
            from .velocity import observe
            vel = observe(rep.title, len({a.source_name for a in group}),
                          velocity_entries)
            rep.velocity = vel["velocity"]
            rep.age_hours = vel["age_hours"]
            rep.is_stale = vel["stale"]

        rep.trend_score = trend
        rep.state_media = all(a.state_media for a in group)
        rep.score = score_cluster(group, max_age, trend, trend_weight,
                                  vel, velocity_weight)
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
