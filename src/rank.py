"""دمج الأخبار المتكررة وترتيبها حسب قوة الترند."""
from __future__ import annotations

import logging
import math
import re
import unicodedata
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


# كلمات تبدأ بها الجُمل فتُكتب بحرف كبير وتبدو أسماء أعلام
_NOT_ENTITY = {
    "the", "this", "that", "these", "those", "after", "before", "why", "how",
    "what", "when", "where", "who", "new", "top", "breaking", "watch", "video",
    "update", "exclusive", "live", "report", "opinion", "analysis", "first",
    "last", "more", "most", "police", "government", "president", "minister",
}
_ENT_WORD = re.compile(r"[^\W\d_]+|\d[\d.,]*", re.UNICODE)


def _fold(word: str) -> str:
    """يجرّد الحرف من علاماته: Iran / İran / Irán → iran."""
    stripped = unicodedata.normalize("NFKD", word)
    return "".join(c for c in stripped if not unicodedata.combining(c)).lower()


def entities(title: str) -> set[str]:
    """
    أسماء الأعلام والأرقام في العنوان.

    هذه وحدها تعبر اللغات: «Trump» و«Iran» و«2026» تُكتب متشابهة في
    الإنجليزية والفرنسية والألمانية والإسبانية والتركية، بينما الأفعال
    والحروف تختلف كليًا. مقارنة الكلمات العادية تفشل عبر اللغات، فيبقى
    كل خبر وحيدًا ولا يُقاس انتشاره.
    """
    found: set[str] = set()
    # نقسّم على الفاصلة العليا: التركية تلحق اللواحق هكذا (İran'a)
    for chunk in re.split(r"['’]", title):
        words = _ENT_WORD.findall(chunk)
        for index, word in enumerate(words):
            if word[:1].isdigit():
                if len(word) >= 2:            # الأرقام إشارة قوية
                    found.add(_fold(word))
                continue
            if len(word) < 3 or not word[:1].isupper():
                continue
            folded = _fold(word)
            # كلمة واحدة أول الجملة قد تكون شائعة لا اسم عَلَم
            if index == 0 and folded in _NOT_ENTITY:
                continue
            if folded in _NOT_ENTITY:
                continue
            found.add(folded)
    return found


def similarity(a: set[str], b: set[str]) -> float:
    """معامل جاكارد المرجّح — بسيط وفعّال لعناوين الأخبار."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / min(len(a), len(b))


def cluster(articles: list[Article], threshold: float,
            token_fn=tokens) -> list[list[Article]]:
    """تجميع جشع: أول خبر يمثّل المجموعة، وما يشبهه يُضاف إليها.

    token_fn يبني توقيع العنوان — الافتراضي `tokens` (لاتيني فقط عمدًا:
    خلاصات الجمع الأساسي إنجليزية، ولا داعي لتطبيع عربي هناك). مسار
    التحقق (verify.py) يمرّر `request.norm_tokens` بدلًا منه عبر
    rank(token_fn=...)، لأن عنوانين عربيين مستقلي الصياغة عن الحدث نفسه
    لا يشتركان في أي توقيع لاتيني فيبقيان مجموعتين منفصلتين رغم تطابق
    المضمون (Issue #132 تعليق لاحق)."""
    clusters: list[list[Article]] = []
    signatures: list[set[str]] = []

    for art in sorted(articles, key=lambda a: (-a.weight, a.published)):
        sig = token_fn(art.title)
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


def pick_representative(group: list[Article],
                        keep_google_links: bool = False) -> Article:
    """
    يختار أفضل نسخة من الخبر، ويستعير صور بقية النسخ.

    هذا مهم: قد يكون الخبر من Google News (بلا صورة) بينما نسخة BBC من
    الحدث نفسه تحمل صورة حقيقية — فنأخذ نص الأقوى وصورة من يملكها.

    keep_google_links: مسار الجمع الأساسي يستبعد روابط جوجل الوسيطة من
    cluster_members افتراضيًا لأن extract.fetch_text ترفضها مباشرة بلا حل.
    مسار التحقق (verify.py) يمرّر True: نتائجه **كلها** من بحث Google News
    (لا خلاصات ناشرين مباشرة)، فالاستبعاد الافتراضي كان يُفرغ cluster_members
    من كل الأعضاء تقريبًا قبل أن تصل gather_evidence أصلًا — التي تحلّ هذه
    الروابط بنفسها عبر sources.resolve_final_url (Issue #132 تعليق لاحق:
    'تم دمج 5 خبر في 1 موضوع' ثم 'نصوص مُستخرجة: 1 من 1' رغم توسيع
    cluster_members، لأنها كانت تصل شبه فارغة من هنا أصلًا)."""
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

    # روابط كل النسخ، الأثقل وزنًا أولًا؛ روابط جوجل الوسيطة تُستبعد إلا
    # حين keep_google_links=True (انظر التوثيق أعلاه)
    seen_links: set[str] = set()
    members: list[dict] = []
    for a in sorted(group, key=lambda x: -x.weight):
        if a.link in seen_links:
            continue
        if not keep_google_links and "news.google.com" in a.link:
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
         velocity_weight: float = 5.0,
         merge_cfg=None,
         token_fn=None,
         keep_google_links: bool = False) -> list[Article]:
    threshold = float(selection.get("title_similarity", 0.62))
    max_age = int(selection.get("max_age_hours", 18))
    min_sources = int(selection.get("min_sources_for_trend", 1))
    blocklist = selection.get("blocklist_keywords") or []
    diversity = bool(selection.get("region_diversity", True))
    per_region = int(selection.get("max_per_region", 3))

    groups = cluster(articles, threshold, token_fn=token_fn or tokens)
    log.info("تم دمج %d خبر في %d موضوع", len(articles), len(groups))

    ranked: list[Article] = []
    for group in groups:
        if len({a.source_name for a in group}) < min_sources:
            continue
        rep = pick_representative(group, keep_google_links=keep_google_links)
        if is_blocked(rep, blocklist):
            continue

        trend = 0.0
        if trend_signatures:
            from .trends import trend_match
            trend = max(trend_match(tokens(a.title), trend_signatures) for a in group)

        rep.trend_score = trend
        rep.state_media = all(a.state_media for a in group)
        rep.score = score_cluster(group, max_age, trend, trend_weight)
        rep.group_sources = len({a.source_name for a in group})
        ranked.append(rep)

    # ── الدمج الدلالي قبل السرعة ──
    # لا معنى لقياس سرعة خبر مشتّت على خمس لغات: كل نسخة تبدو خبرًا
    # وحيدًا. نجمّعه أولًا فترتفع تغطيته وتُقاس سرعته بحق.
    if merge_cfg is not None:
        from .merge import semantic_merge
        ranked.sort(key=lambda a: a.score, reverse=True)
        before = len(ranked)
        ranked = semantic_merge(ranked, merge_cfg,
                                int((merge_cfg.get("merge", {}) or {})
                                    .get("top", 60)))
        if len(ranked) < before:
            # أعِد حساب الدرجات: تغيّرت أعداد المصادر بعد الدمج
            for art in ranked:
                art.score = score_cluster(
                    [art], max_age, art.trend_score, trend_weight)
                art.score += 3.0 * math.log2(1 + max(art.group_sources - 1, 0))

    # ── السرعة: للمتصدّرين فقط ──
    # تتبّع 1700 خبر في كل تشغيلة يضخّم ملف الحالة ويبطّئ البحث خطيًا
    # (2200 سجل = 4 ثوانٍ، و12000 سجل = 24 ثانية). والأخبار التي لن
    # تقترب من الترشيح لا تحتاج قياس سرعة أصلًا.
    if velocity_entries is not None:
        from .velocity import observe

        track = int(selection.get("velocity_track_top", 250))
        ranked.sort(key=lambda a: a.score, reverse=True)
        for art in ranked[:track]:
            vel = observe(art.title, art.group_sources, velocity_entries)
            art.velocity = vel["velocity"]
            art.age_hours = vel["age_hours"]
            art.is_stale = vel["stale"]
            art.score += (velocity_weight * vel["velocity"]
                          - (2.0 if vel["stale"] else 0.0))
        log.info("قيست سرعة %d خبر من %d", min(track, len(ranked)), len(ranked))

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
