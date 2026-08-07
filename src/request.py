"""طلب يدوي: كلمات مفتاحية → بحث → مسودة خبر.

الدورة العادية تلتقط ما يتصدّر الخلاصات. هذا المسار عكسه: أنت تحدد
الموضوع، والبوت يبحث عنه ويصوغ خبرًا منه إن وجد ما يستحق.

    python -m src.request --query "زلزال هرات"
    python -m src.request --query "إضراب موانئ" --days 14 --limit 2
    python -m src.request --query "معرض دبي" --dry-run   # بحث بلا صياغة

البحث عبر خلاصة بحث Google News: بلا مفتاح وبلا تكلفة، وتغطي آلاف
الناشرين بالعربية والإنجليزية معًا. التكلفة الوحيدة هي استدعاء النموذج
عند وجود نتيجة تستحق الصياغة.
"""
from __future__ import annotations

import argparse
import logging
import re
import urllib.parse
from datetime import datetime, timezone

from . import radar, store
from .collect import step_summary
from .config import load_config
from .rank import STOPWORDS, rank
from .sources import fetch_source
from .writer import usage_summary

log = logging.getLogger("request")

SEARCH_URL = ("https://news.google.com/rss/search"
              "?q={q}&hl={hl}&gl={gl}&ceid={ceid}")

DEFAULT_LOCALES = [
    {"hl": "ar", "gl": "EG", "ceid": "EG:ar"},
    {"hl": "en-US", "gl": "US", "ceid": "US:en"},
]

# مطابِق الكلمات: `rank.tokens` لاتيني فقط لأن الخلاصات إنجليزية، أما
# الطلب فيكتبه صاحب الصفحة بالعربية غالبًا — فيحتاج تطبيعًا عربيًا.
_AR_RANGE = re.compile(r"[\u0600-\u06FF]")
_AR_MARKS = re.compile(r"[\u064B-\u0652\u0640\u0670]")
_WORD_RE = re.compile(r"[\w']+", re.UNICODE)
_AR_TRANS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
                           "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
_AR_STOP = {"من", "عن", "على", "الى", "إلى", "في", "مع", "بعد", "قبل",
            "هذا", "هذه", "التي", "الذي", "بين", "عند", "كل", "لكن"}


def has_arabic(text: str) -> bool:
    return bool(_AR_RANGE.search(text or ""))


def norm_tokens(text: str) -> set[str]:
    """كلمات مطبَّعة: الهمزات والتاء المربوطة وأل التعريف لا تفرّق."""
    text = _AR_MARKS.sub("", text or "")
    out: set[str] = set()
    for raw in _WORD_RE.findall(text.lower()):
        word = raw.translate(_AR_TRANS)
        if word.startswith("ال") and len(word) > 4:
            word = word[2:]
        if len(word) > 2 and word not in STOPWORDS and word not in _AR_STOP:
            out.add(word)
    return out


def search_feeds(query: str, days: int, locales: list[dict]) -> list[dict]:
    """يبني مصادر بحث مؤقتة — بصيغة المصادر العادية ليمرّ عبر المسار نفسه."""
    # when:Nd يقصر النتائج على النافذة الزمنية عند جوجل نفسه، فلا نجلب
    # أرشيفًا كاملًا لنرميه بعد الجلب.
    q = urllib.parse.quote(f"{query} when:{days}d")
    feeds = []
    for loc in locales:
        feeds.append({
            "name": f"بحث · {loc.get('hl', '')}",
            "url": SEARCH_URL.format(q=q, hl=loc.get("hl", "en-US"),
                                     gl=loc.get("gl", "US"),
                                     ceid=loc.get("ceid", "US:en")),
            "region": "global",
            "weight": 1.0,
            "bucket": "serious",
        })
    return feeds


def relevant(art, wanted: set[str], min_matches: int) -> bool:
    """
    يستبعد ما لا يمتّ للطلب بصلة.

    بحث جوجل يوسّع الاستعلام ويعيد نتائج مجاورة للموضوع، فقد يأتي خبر
    عن بلد ورد اسمه عرضًا. نطلب حضورًا صريحًا لكلمات الطلب في العنوان
    أو الملخص — الطلب صريح، فلا معنى لتخمين نية صاحبه.

    لكن حين تختلف لغة الطلب عن لغة النتيجة، لا سبيل للمطابقة الحرفية:
    «هرات» لا تطابق Herat. هنا نثق ببحث جوجل بدل أن نرمي كل نتيجة
    أجنبية — وإلا صارت لغة البحث الثانية بلا فائدة.
    """
    if not wanted:
        return True
    text = f"{art.title} {art.summary}"
    found = norm_tokens(text)
    q_ar = {t for t in wanted if has_arabic(t)}
    q_latin = wanted - q_ar

    if has_arabic(text) and q_ar:
        return len(q_ar & found) >= min_matches
    if not has_arabic(text) and q_latin:
        return len(q_latin & found) >= min_matches
    return True


def find(query: str, cfg, days: int = 0, dry_run: bool = False) -> list:
    rcfg = cfg.get("request", {}) or {}
    days = days or int(rcfg.get("days", 7))
    locales = rcfg.get("locales") or DEFAULT_LOCALES

    articles = []
    for feed in search_feeds(query, days, locales):
        articles += fetch_source(feed, max_age_hours=days * 24)
    log.info("نتائج البحث الخام: %d", len(articles))
    if not articles:
        return []

    wanted = norm_tokens(query)
    matched = [a for a in articles
               if relevant(a, wanted, int(rcfg.get("min_matches", 1)))]
    log.info("مطابق لكلمات الطلب: %d من %d", len(matched), len(articles))
    if not matched:
        return []

    # نافذة الترتيب توسَّع لتشمل نافذة الطلب: الافتراضي 18 ساعة يسقط
    # كل نتيجة أقدم من يوم، وأغلب الطلبات عن أحداث ليست وليدة الساعة.
    selection = dict(cfg.get("selection", {}) or {})
    selection["max_age_hours"] = days * 24
    selection["region_diversity"] = False   # الطلب موضوع واحد لا دفعة متنوعة

    ranked = rank(matched, selection, merge_cfg=cfg)
    log.info("بعد الدمج والترتيب: %d", len(ranked))
    for a in ranked[:5]:
        log.info("  • [%.1f · %d مصدر] %s", a.score,
                 a.group_sources, a.title[:70])
    return ranked


def main() -> int:
    parser = argparse.ArgumentParser(description="طلب خبر بكلمات مفتاحية")
    parser.add_argument("--query", required=True, help="الكلمات المفتاحية")
    parser.add_argument("--days", type=int, default=0, help="نافذة البحث بالأيام")
    parser.add_argument("--limit", type=int, default=1, help="عدد المسودات")
    parser.add_argument("--dry-run", action="store_true",
                        help="بحث وعرض النتائج بلا صياغة (مجاني)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")

    query = args.query.strip()
    if not query:
        log.error("الطلب فارغ")
        return 2

    cfg = load_config()
    log.info("الطلب: «%s»", query)
    found = find(query, cfg, days=args.days)

    if not found:
        log.warning("لا نتائج تطابق «%s»", query)
        step_summary(
            f"### 🔍 لا نتائج\nالطلب: «{query}» — لم يعثر البحث على خبر "
            "يطابق هذه الكلمات في النافذة الزمنية المحددة. جرّب كلمات "
            "أعم أو وسّع `--days`."
        )
        return 0

    if args.dry_run:
        lines = [f"### 🔍 نتائج «{query}» (بحث فقط)", ""]
        lines += [f"- `{a.score:.1f}` [{a.title[:80]}]({a.link})"
                  for a in found[:10]]
        step_summary("\n".join(lines))
        return 0

    selection = cfg.get("selection", {}) or {}
    dupe_threshold = float(selection.get("title_similarity", 0.62))
    history = store.load_history()
    made: list[dict] = []
    for art in found:
        if len(made) >= max(1, args.limit):
            break
        # لا نعيد صياغة ما نُشر: الطلب لا يُلغي ذاكرة النشر
        if store.is_duplicate(history, art.title, art.link, dupe_threshold):
            log.info("سبق نشره: %s", art.title[:60])
            continue

        draft = radar.build_draft(art, cfg, urgent=False,
                                  extra={"from_request": query})
        if not draft:
            continue
        store.save_draft(draft)
        store.remember(history, art.title, art.link,
                       draft["arabic"]["post_title"],
                       region=art.region, score=art.score, bucket=art.bucket)
        made.append(draft)
        log.info("✓ مسودة جاهزة: %s", draft["arabic"]["post_title"][:60])

    store.save_history(history, int(selection.get("dedupe_days", 5)))

    if not made:
        step_summary(
            f"### ⚠️ لا مسودة\nوُجدت {len(found)} نتيجة لـ «{query}» لكن "
            "لم تنجُ أي منها من الفرز التحريري (مكررة أو بلا نص كافٍ)."
        )
        return 0

    lines = [f"### ✅ {len(made)} مسودة من طلبك", "",
             f"الطلب: «{query}»", ""]
    lines += [f"- `{d['score']:.1f}` {d['arabic']['post_title']}" for d in made]
    lines += ["", f"<sub>💵 {usage_summary()}</sub>"]
    step_summary("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
