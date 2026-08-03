"""جمع الأخبار من خلاصات RSS واستخراج روابط الصور."""
from __future__ import annotations

import hashlib
import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

import feedparser
import requests

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "en,ar;q=0.8"}


@dataclass
class Article:
    title: str
    link: str
    summary: str
    source_name: str
    region: str
    weight: float
    published: datetime
    image_url: str | None = None
    publisher: str = ""
    # يُملأ لاحقًا في مرحلة الترتيب
    cluster_sources: list[str] = field(default_factory=list)
    cluster_members: list[dict] = field(default_factory=list)  # {name, link} لكل نسخة
    image_candidates: list[str] = field(default_factory=list)
    bucket: str = "serious"          # light | sport | serious — لحصص الدفعة
    state_media: bool = False        # إعلام رسمي/حكومي — يُنبَّه عليه للمراجع
    trend_score: float = 0.0         # مطابقة Google Trends (0 إلى 1)
    velocity: float = 0.0            # سرعة الانتشار (0 إلى 1)
    age_hours: float = 0.0           # منذ متى نتتبّع هذا الخبر
    is_stale: bool = False           # توقّف نموه
    score: float = 0.0

    @property
    def uid(self) -> str:
        return hashlib.sha1(self.link.encode("utf-8")).hexdigest()[:12]


# ──────────────────────────── تنظيف النصوص ────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def strip_publisher(title: str) -> tuple[str, str]:
    """Google News يضيف ' - Publisher' في نهاية العنوان. نفصله."""
    parts = re.split(r"\s+[-–—]\s+", title)
    if len(parts) > 1 and len(parts[-1]) < 40:
        return " - ".join(parts[:-1]).strip(), parts[-1].strip()
    return title.strip(), ""


# ──────────────────────────── استخراج الصور ────────────────────────────


def images_from_entry(entry) -> list[str]:
    """كل روابط الصور داخل عنصر RSS، مرتبة من الأكبر إلى الأصغر."""
    sized: list[tuple[int, str]] = []

    for key in ("media_content", "media_thumbnail"):
        for item in entry.get(key) or []:
            url = item.get("url")
            if not url:
                continue
            try:
                width = int(item.get("width") or 0)
            except (TypeError, ValueError):
                width = 0
            sized.append((width, url))

    for enc in entry.get("enclosures") or []:
        if str(enc.get("type", "")).startswith("image") and enc.get("href"):
            sized.append((0, enc["href"]))

    blobs = [entry.get("summary")]
    if entry.get("content"):
        blobs.append(entry["content"][0].get("value"))
    for blob in blobs:
        if blob:
            for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', blob):
                sized.append((0, m.group(1)))

    sized.sort(key=lambda t: -t[0])
    out: list[str] = []
    for _, url in sized:
        for variant in upgrade_image_url(url):
            if variant not in out and not is_generic_image(variant):
                out.append(variant)
    return out


_OG_PATTERNS = [
    re.compile(r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', re.I),
    re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)', re.I),
]


def resolve_final_url(url: str, timeout: int = 12) -> str:
    """روابط Google News وسيطة — نتبع التحويلات للوصول للناشر الأصلي."""
    try:
        r = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=timeout)
        if r.url and "news.google.com" not in r.url:
            return r.url
        r = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=timeout,
                         stream=True)
        return r.url or url
    except requests.RequestException:
        return url


def image_from_page(url: str, timeout: int = 12) -> str | None:
    """يسحب og:image من صفحة الخبر."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code != 200:
            return None
        head = r.text[:400_000]
    except requests.RequestException as exc:
        log.debug("فشل جلب الصفحة %s: %s", url, exc)
        return None

    for pattern in _OG_PATTERNS:
        m = pattern.search(head)
        if m:
            img = html.unescape(m.group(1)).strip()
            if img.startswith("//"):
                img = "https:" + img
            if img.startswith("http"):
                return img
    return None


GENERIC_IMAGE_HINTS = (
    "logo", "placeholder", "default", "avatar", "icon", "sprite", "blank",
    "gstatic.com", "news.google.com", "/favicon", "share-image", "og-default",
    "social-default", "fallback",
)


def is_generic_image(url: str | None) -> bool:
    """يرفض الشعارات والصور الافتراضية التي لا علاقة لها بالخبر."""
    if not url:
        return True
    low = url.lower()
    return any(hint in low for hint in GENERIC_IMAGE_HINTS)


# ترقية روابط الصور: أغلب الخلاصات تعطي مصغّرات صغيرة، وشبكات التوزيع
# تسمح بطلب النسخة الكبيرة بتغيير رقم العرض في المسار.
_CDN_UPGRADES: list[tuple[re.Pattern, list[str]]] = [
    # BBC: ichef.bbci.co.uk/news/240/cpsprodpb/...
    (re.compile(r"(ichef\.bbci\.co\.uk/(?:news|ace/(?:standard|ws))/)(\d{2,4})(/)"),
     ["1024", "800"]),
    # The Guardian: media.guim.co.uk/.../140.jpg
    (re.compile(r"(media\.guim\.co\.uk/.+/)(\d{2,4})(\.\w+)$"), ["1000", "620"]),
    # Sky News: e3.365dm.com/.../768x432/...
    (re.compile(r"(365dm\.com/.+/)(\d{3,4})x(\d{3,4})(/)"), ["1096"]),
]


def upgrade_image_url(url: str) -> list[str]:
    """يعيد [النسخة الكبيرة إن أمكن, الرابط الأصلي] لتُجرّب بالترتيب."""
    variants: list[str] = []
    for pattern, widths in _CDN_UPGRADES:
        m = pattern.search(url)
        if not m:
            continue
        for width in widths:
            if len(m.groups()) == 4:  # نمط العرضxالارتفاع
                ratio = int(m.group(3)) / max(int(m.group(2)), 1)
                repl = f"{m.group(1)}{width}x{int(int(width) * ratio)}{m.group(4)}"
            else:
                repl = f"{m.group(1)}{width}{m.group(3)}"
            variants.append(url[: m.start()] + repl + url[m.end():])
        break
    variants.append(url)
    return variants


def enrich_image(article: Article) -> Article:
    """
    يبني قائمة مرشحي الصور *المتعلقة بالخبر*.

    روابط Google News وسيطة ومشفّرة، ومتابعتها كثيرًا ما تنتهي بصفحة عامة
    صورتها شعار جوجل. لذلك نرفض أي صورة تبدو عامة — الخلفية البديلة المصممة
    أفضل من صورة لا علاقة لها بالمحتوى.
    """
    if article.image_candidates:
        article.image_url = article.image_candidates[0]
        return article

    final = resolve_final_url(article.link)
    if "news.google.com" in final:
        log.info("تعذّر الوصول للناشر الأصلي: %s", article.title[:50])
        return article

    article.link = final
    candidate = image_from_page(final)
    if is_generic_image(candidate):
        log.info("لا صورة صالحة لـ: %s", article.title[:50])
        return article

    article.image_candidates = upgrade_image_url(candidate)  # type: ignore[arg-type]
    article.image_url = article.image_candidates[0]
    return article


# ──────────────────────────── الجلب ────────────────────────────


def parse_published(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        tm = entry.get(key)
        if tm:
            return datetime(*tm[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def fetch_source(src: dict, max_age_hours: int) -> list[Article]:
    log.info("جلب: %s", src["name"])
    try:
        resp = requests.get(src["url"], headers=HEADERS, timeout=20)
        feed = feedparser.parse(resp.content)
    except requests.RequestException as exc:
        log.warning("تعذّر جلب %s: %s", src["name"], exc)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    out: list[Article] = []

    for entry in feed.entries:
        title_raw = clean_text(entry.get("title"))
        link = entry.get("link")
        if not title_raw or not link:
            continue
        published = parse_published(entry)
        if published < cutoff:
            continue
        title, publisher = strip_publisher(title_raw)
        out.append(
            Article(
                title=title,
                link=link,
                summary=clean_text(entry.get("summary"))[:1200],
                source_name=src["name"],
                region=src.get("region", "global"),
                weight=float(src.get("weight", 1.0)),
                published=published,
                image_candidates=images_from_entry(entry),
                publisher=publisher or src["name"],
                bucket=str(src.get("bucket", "serious")),
                state_media=bool(src.get("state_media")),
            )
        )
    log.info("  → %d خبر صالح", len(out))
    return out


def fetch_all(sources: Iterable[dict], max_age_hours: int,
              workers: int = 12) -> list[Article]:
    """
    يجلب كل الخلاصات بالتوازي.

    الجلب المتسلسل لستين مصدرًا يستغرق دقيقتين؛ بالتوازي يهبط إلى عشر ثوانٍ.
    كل خلاصة معزولة: فشل واحدة لا يوقف الباقي.
    """
    sources = list(sources)
    articles: list[Article] = []
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(fetch_source, src, max_age_hours): src for src in sources
        }
        for future in as_completed(futures):
            src = futures[future]
            try:
                got = future.result()
            except Exception as exc:  # noqa: BLE001 — لا نُسقط الدفعة لمصدر واحد
                log.warning("تعذّر جلب %s: %s", src["name"], exc)
                failed.append(src["name"])
                continue
            if not got:
                failed.append(src["name"])
            articles.extend(got)

    log.info("الإجمالي المجموع: %d خبر من %d مصدر",
             len(articles), len(sources) - len(failed))
    if failed:
        log.warning("مصادر بلا نتائج (%d): %s", len(failed), "، ".join(failed[:10]))
    return articles
