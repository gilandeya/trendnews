"""جمع الأخبار من خلاصات RSS واستخراج روابط الصور."""
from __future__ import annotations

import hashlib
import html
import logging
import re
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


def image_from_entry(entry) -> str | None:
    """يبحث عن صورة داخل عنصر RSS نفسه (الأسرع والأقل تكلفة)."""
    for key in ("media_content", "media_thumbnail"):
        items = entry.get(key) or []
        best, best_w = None, -1
        for item in items:
            url = item.get("url")
            if not url:
                continue
            try:
                width = int(item.get("width") or 0)
            except (TypeError, ValueError):
                width = 0
            if width > best_w:
                best, best_w = url, width
        if best:
            return best

    for enc in entry.get("enclosures") or []:
        if str(enc.get("type", "")).startswith("image") and enc.get("href"):
            return enc["href"]

    for blob in (entry.get("summary"), entry.get("content", [{}])[0].get("value")
                 if entry.get("content") else None):
        if not blob:
            continue
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', blob)
        if m:
            return m.group(1)
    return None


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


def enrich_image(article: Article) -> Article:
    """يضمن وجود صورة للمقال قدر الإمكان (RSS ← og:image)."""
    if article.image_url:
        return article
    final = resolve_final_url(article.link)
    if final != article.link:
        article.link = final
    article.image_url = image_from_page(article.link)
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
                image_url=image_from_entry(entry),
                publisher=publisher or src["name"],
            )
        )
    log.info("  → %d خبر صالح", len(out))
    return out


def fetch_all(sources: Iterable[dict], max_age_hours: int) -> list[Article]:
    articles: list[Article] = []
    for src in sources:
        articles.extend(fetch_source(src, max_age_hours))
    log.info("الإجمالي المجموع: %d خبر", len(articles))
    return articles
