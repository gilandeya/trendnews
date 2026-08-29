"""المرحلة الأولى من مسار يوتيوب (Issue #631): تحديد الفيديوهات المرشّحة من
القنوات المفعَّلة في config.yaml خلال آخر ``lookback_hours`` ساعة.

لا استخلاص هنا ولا نص ترجمة -- فقط بيانات وصفية عبر YouTube Data API
(playlistItems + videos.list). المرحلة الثانية (src/youtube_extract.py) هي
من تسحب النص الفعلي لكل فيديو ناجٍ من هذه المرحلة.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .config import STATE_DIR, Config, env, load_config

log = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/youtube/v3"
SEEN_FILE = STATE_DIR / "youtube_seen.json"

# نفس تعبير ISO 8601 المستعمل في tools/measure_channels.py -- مكرَّر هنا
# عمدًا لا مستورَد: مسار الإنتاج (src/) لا ينبغي أن يعتمد على سكربت تشخيصي
# يدوي تحت tools/، حتى لو كانت الدالة صِرفة ومطابقة حرفيًا.
_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def parse_iso8601_duration(duration: str) -> int:
    match = _DURATION_RE.match(duration or "")
    if not match:
        raise ValueError(f"تعذّر تحليل صيغة المدة: {duration}")
    parts = {k: int(v) if v else 0 for k, v in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def uploads_playlist_id(channel_id: str) -> str:
    """معرّف قائمة الرفع لأي قناة هو معرّف القناة نفسه مع استبدال الحرف
    الثاني: UC... -> UU... (قاعدة يوتيوب ثابتة)."""
    if len(channel_id) < 2 or channel_id[:2] != "UC":
        raise ValueError(f"channel_id غير متوقَّع الشكل: {channel_id}")
    return "UU" + channel_id[2:]


# ──────────────────────────── سجل التكرار ────────────────────────────
# بنية بسيطة {video_id: "YYYY-MM-DD"} بدل قائمة كما في store.py: البحث هنا
# بمعرّف مباشر لا بتشابه عناوين، فقاموس أسرع وأبسط ولا حاجة لأي منطق تشابه.


def load_seen() -> dict[str, str]:
    if not SEEN_FILE.exists():
        return {}
    try:
        return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("ملف سجل يوتيوب تالف — سيُعاد إنشاؤه")
        return {}


def mark_seen(seen: dict[str, str], video_id: str, date_str: str) -> None:
    seen[video_id] = date_str


def save_seen(seen: dict[str, str], retention_days: int, now: datetime) -> None:
    cutoff = now - timedelta(days=retention_days)
    fresh = {}
    for video_id, date_str in seen.items():
        try:
            when = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if when >= cutoff:
            fresh[video_id] = date_str
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8")


def within_lookback(published_at: str, lookback_hours: float, now: datetime) -> bool:
    if not published_at:
        return False
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return published >= now - timedelta(hours=lookback_hours)


@dataclass
class Video:
    video_id: str
    channel: str
    bloc: str
    language: str
    video_title: str
    video_url: str
    duration_seconds: int
    published_at: str
    is_live: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_video_item(item: dict, channel: dict) -> Video:
    vid = item.get("id", "")
    snippet = item.get("snippet", {}) or {}
    content = item.get("contentDetails", {}) or {}
    # liveBroadcastContent يميّز "live"/"upcoming" عن "none" (بث انتهى وصار
    # VOD عاديًا) -- أدق من مجرّد وجود liveStreamingDetails، الذي يبقى
    # موجودًا حتى بعد انتهاء البث ولا يعني أنه لا يزال مباشرًا الآن.
    is_live = snippet.get("liveBroadcastContent", "none") in ("live", "upcoming")
    return Video(
        video_id=vid,
        channel=channel["name"],
        bloc=channel["bloc"],
        language=channel.get("language", ""),
        video_title=snippet.get("title", ""),
        video_url=f"https://www.youtube.com/watch?v={vid}",
        duration_seconds=parse_iso8601_duration(content.get("duration", "PT0S")),
        published_at=snippet.get("publishedAt", ""),
        is_live=is_live,
    )


def passed_guards(video: Video, channel: dict, cfg: Config, seen: dict) -> tuple[bool, str]:
    """يطبّق الحرّاس بالترتيب الملزِم في الـIssue. يعيد (نجا، سبب الاستبعاد
    إن فشل). كل قيمة قابلة للتجاوز لكل قناة عبر مفتاح بنفس الاسم في
    ``channel``، وإلا ترجع لقيمة config.yaml: youtube العامة."""
    exclude_live = channel.get("exclude_live", cfg.path("youtube.exclude_live", True))
    if exclude_live and video.is_live:
        return False, "بث مباشر أو مجدول"

    max_minutes = channel.get("max_duration_minutes", cfg.path("youtube.max_duration_minutes", 150))
    if video.duration_seconds > max_minutes * 60:
        return False, f"تجاوز الحد الأقصى للمدة ({max_minutes} د)"

    min_minutes = channel.get("min_duration_minutes", cfg.path("youtube.min_duration_minutes", 8))
    if video.duration_seconds < min_minutes * 60:
        return False, f"أقل من الحد الأدنى للمدة ({min_minutes} د)"

    for pattern in channel.get("exclude_patterns", []) or []:
        if pattern and pattern in video.video_title:
            return False, f"يطابق نمط الاستبعاد: {pattern}"

    if video.video_id in seen:
        return False, "مسجَّل سابقًا في السجل"

    return True, ""


def select_top(videos: list[Video], max_per_channel: int) -> list[Video]:
    """ترتيب الناجين بالمدة تنازليًا وأخذ أعلى ``max_per_channel``.

    بديل عن قوائم أسماء البرامج (انظر الـIssue): القياس أظهر فصلًا واضحًا
    بين المقاطع الإخبارية (تحت 5 دقائق) والتحليل (فوق 10) -- وقاعدة كهذه
    تتكيّف وحدها مع برامج جديدة بلا صيانة قوائم."""
    return sorted(videos, key=lambda v: v.duration_seconds, reverse=True)[:max_per_channel]


def fetch_playlist_video_ids(playlist_id: str, api_key: str, lookback_hours: float,
                              now: datetime) -> list[str]:
    """يُرقّم صفحات playlistItems (الأحدث أولًا) حتى يتجاوز عنصر ما نافذة
    lookback_hours -- عندها نتوقف فورًا، فبقية الصفحات أقدم يقينًا."""
    video_ids: list[str] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {
            "part": "contentDetails", "playlistId": playlist_id, "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token
        resp = requests.get(f"{API_BASE}/playlistItems",
                            params={**params, "key": api_key}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        if not items:
            break
        reached_end = False
        for item in items:
            published_at = item.get("contentDetails", {}).get("videoPublishedAt", "")
            if not within_lookback(published_at, lookback_hours, now):
                reached_end = True
                break
            video_ids.append(item["contentDetails"]["videoId"])
        if reached_end:
            break
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return video_ids


def fetch_videos_details(video_ids: list[str], api_key: str) -> list[dict]:
    items: list[dict] = []
    for start in range(0, len(video_ids), 50):
        chunk = video_ids[start:start + 50]
        resp = requests.get(
            f"{API_BASE}/videos",
            params={"part": "contentDetails,snippet,liveStreamingDetails",
                    "id": ",".join(chunk), "key": api_key},
            timeout=20,
        )
        resp.raise_for_status()
        items.extend(resp.json().get("items", []))
    return items


def collect_channel(channel: dict, cfg: Config, api_key: str, seen: dict,
                     now: datetime) -> tuple[list[Video], list[dict], int]:
    """يعيد (الناجون بعد الحرّاس والقصّ، أعطال الجلب، عدد المرشّحين ضمن
    النافذة الزمنية قبل أي حارس)."""
    if not channel.get("active", True):
        return [], [], 0

    lookback_hours = cfg.path("youtube.lookback_hours", 30)
    try:
        playlist_id = uploads_playlist_id(channel["channel_id"])
        video_ids = fetch_playlist_video_ids(playlist_id, api_key, lookback_hours, now)
        items = fetch_videos_details(video_ids, api_key) if video_ids else []
    except (requests.RequestException, ValueError) as exc:
        return [], [{"channel": channel["name"], "video_id": None, "title": None,
                     "reason": f"تعذّر جلب فيديوهات القناة: {exc}"}], 0

    survivors: list[Video] = []
    for item in items:
        try:
            video = parse_video_item(item, channel)
        except ValueError as exc:
            log.warning("تعذّر تحليل مدة فيديو من %s: %s", channel["name"], exc)
            continue
        ok, reason = passed_guards(video, channel, cfg, seen)
        if ok:
            survivors.append(video)

    max_per_channel = channel.get("max_per_channel", cfg.path("youtube.max_per_channel", 3))
    top = select_top(survivors, max_per_channel)
    return top, [], len(items)


def run(cfg: Config | None = None, api_key: str | None = None,
        now: datetime | None = None) -> dict:
    cfg = cfg or load_config()
    api_key = api_key or env("YOUTUBE_API_KEY", required=True)
    now = now or datetime.now(timezone.utc)

    channels = [c for c in cfg.get("channels", []) if c.get("active", True)]
    seen = load_seen()

    all_videos: list[Video] = []
    failed: list[dict] = []
    videos_found = 0

    for channel in channels:
        print(f"جمع: {channel['name']} ({channel['handle']})", file=sys.stderr)
        top, chan_failed, found = collect_channel(channel, cfg, api_key, seen, now)
        videos_found += found
        failed.extend(chan_failed)
        all_videos.extend(top)
        print(f"  → {found} فيديو ضمن النافذة، {len(top)} ناجٍ بعد الحرّاس",
              file=sys.stderr)

    # التسجيل يمنع إعادة معالجة نفس الفيديو في تشغيلة لاحقة. مدوَّن بالتاريخ
    # لا وسمًا فارغًا فقط -- يسمح لاحقًا بتمييز "عولج اليوم" عن "عولج قبل
    # أيام" عند مراجعة السجل يدويًا، وبتقليم المدخلات القديمة (save_seen).
    today = now.strftime("%Y-%m-%d")
    for video in all_videos:
        mark_seen(seen, video.video_id, today)
    save_seen(seen, cfg.path("youtube.seen_retention_days", 14), now)

    return {
        "videos": all_videos,
        "failed": failed,
        "stats": {
            "channels_checked": len(channels),
            "videos_found": videos_found,
            "passed_guards": len(all_videos),
        },
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    result = run()
    stats = result["stats"]
    print(f"القنوات المفحوصة: {stats['channels_checked']}")
    print(f"فيديوهات ضمن النافذة الزمنية: {stats['videos_found']}")
    print(f"ناجية بعد الحرّاس: {stats['passed_guards']}")
    if result["failed"]:
        print(f"تعذّر جلبها: {len(result['failed'])}")
        for entry in result["failed"]:
            print(f"  - {entry['channel']}: {entry['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
