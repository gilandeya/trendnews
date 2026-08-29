"""Manual, one-off survey script for Issue #619 ("قياس القنوات").

Measures 13 YouTube channels — sample size, upload cadence, duration spread,
and transcript availability — before deciding whether to build the "YouTube
analysis" pipeline. Produces a report only: no pipeline, no publishing, no
transcript text saved anywhere.

Must be run manually from the owner's home IP, never from GitHub Actions —
YouTube blocks cloud-provider IP ranges (including Actions runners) with
IpBlocked/RequestBlocked when listing transcripts. The YouTube Data API calls
are unaffected by that block and would work from anywhere with a key; only
the transcript-listing step needs a residential IP.

Usage:
    YOUTUBE_API_KEY=... python tools/measure_channels.py
"""
from __future__ import annotations

import random
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

API_BASE = "https://www.googleapis.com/youtube/v3"
SAMPLE_SIZE = 50
# Required by the issue: sequential, randomized 2-5s gap between transcript
# list() calls — no concurrency, to stay under whatever informal rate limit
# keeps this from tripping YouTube's bot detection.
TRANSCRIPT_SLEEP_RANGE = (2.0, 5.0)

REPORT_PATH = ROOT / "reports" / "channel_survey.md"
TITLES_DIR = ROOT / "reports" / "titles"
CONFIG_PATH = ROOT / "config.yaml"

DURATION_BUCKETS = [
    ("< 5 د", 0, 300),
    ("5-15 د", 300, 900),
    ("15-30 د", 900, 1800),
    ("30-90 د", 1800, 5400),
    ("> 90 د", 5400, None),
]

# The 13 channels from the issue body. Identifiers are already confirmed —
# only #6/#7 (Halk TV, SÖZCÜ) carry "unconfirmed": True per the issue's own
# caveat, so verify_unconfirmed_handles() re-checks just those two.
CHANNELS: list[dict[str, Any]] = [
    {"name": "الجزيرة", "handle": "@aljazeera", "channel_id": "UCfiwzLy-8yKzIbsmZTzxDgw",
     "language": "ar", "bloc": "arabic", "bias_note": "قطرية التمويل"},
    {"name": "العربية", "handle": "@alarabiya", "channel_id": "UCahpxixMCwoANAftn6IxkTg",
     "language": "ar", "bloc": "arabic", "bias_note": "سعودية التمويل، مقرّها دبي"},
    {"name": "فرانس 24 عربي", "handle": "@france24_ar", "channel_id": "UCdTyuXgmJkG_O8_75eqej-w",
     "language": "ar", "bloc": "arabic", "bias_note": "فرنسية عامة"},
    {"name": "CNN Türk", "handle": "@cnnturk", "channel_id": "UCV6zcRug6Hqp1UX_FdyUeBg",
     "language": "tr", "bloc": "turkish", "bias_note": "تيار سائد"},
    {"name": "Habertürk", "handle": "@haberturktv", "channel_id": "UCn6dNfiRE_Xunu7iMyvD7AA",
     "language": "tr", "bloc": "turkish", "bias_note": "تيار سائد"},
    {"name": "Halk TV", "handle": "@Halktvkanali", "channel_id": "UCf_ResXZzE-o18zACUEmyvQ",
     "language": "tr", "bloc": "turkish", "bias_note": "معارض", "unconfirmed": True},
    {"name": "SÖZCÜ", "handle": "@Sozcutelevizyonu", "channel_id": "UCOulx_rep5O4i9y6AyDqVvw",
     "language": "tr", "bloc": "turkish", "bias_note": "معارض علماني", "unconfirmed": True},
    {"name": "Iran International", "handle": "@IRANINTL", "channel_id": "UCat6bC0Wrqq9Bcq7EkH_yQw",
     "language": "fa", "bloc": "persian", "bias_note": "معارضة إيرانية"},
    {"name": "رصدکده", "handle": "@Rasadkadeh", "channel_id": "UCAwjnLdBvZPVuCJU_8RHg_w",
     "language": "fa", "bloc": "persian", "bias_note": "من داخل إيران"},
    {"name": "ערוץ 14", "handle": "@C14news", "channel_id": "UCKEImtWikw9usC1pl_9m1nQ",
     "language": "he", "bloc": "israeli", "bias_note": "يمين"},
    {"name": "ILTV", "handle": "@IsraelEnglishNews", "channel_id": "UCuxgEyMeaks7HS5gAw6Tt7w",
     "language": "en", "bloc": "israeli", "bias_note": "مناصرة موجّهة للخارج"},
    {"name": "All Israel News", "handle": "@allisraelnewscom", "channel_id": "UCu6O9MhKi6m7pgJcchrkxjA",
     "language": "en", "bloc": "israeli", "bias_note": "يمين ديني"},
    {"name": "Haaretz", "handle": "@haaretzcom", "channel_id": "UCJboXXfoy9Ik4MKU9cpA-Uw",
     "language": "en", "bloc": "israeli", "bias_note": "يسار ليبرالي"},
]


class FatalBlockedError(RuntimeError):
    """Raised when YouTube returns IpBlocked/RequestBlocked — stop, don't retry."""


@dataclass
class VideoRecord:
    channel_handle: str
    channel_name: str
    video_id: str
    title: str
    duration_seconds: int
    published_at: str
    is_live: bool
    transcript_available: bool | None = None
    transcript_language: str | None = None
    transcript_is_manual: bool | None = None
    transcript_error: str | None = None


# ─────────────────────────── pure helpers ───────────────────────────

def uploads_playlist_id(channel_id: str) -> str:
    """A channel's uploads playlist id is its channel id with the second
    letter swapped: UC... -> UU... (a fixed YouTube convention)."""
    if len(channel_id) < 2 or channel_id[:2] != "UC":
        raise ValueError(f"channel_id غير متوقَّع الشكل: {channel_id}")
    return "UU" + channel_id[2:]


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


def format_mmss(seconds: float) -> str:
    minutes, secs = divmod(max(0, int(round(seconds))), 60)
    return f"{minutes:02d}:{secs:02d}"


def duration_bucket(seconds: int) -> str:
    for label, lo, hi in DURATION_BUCKETS:
        if seconds >= lo and (hi is None or seconds < hi):
            return label
    return DURATION_BUCKETS[-1][0]


def recommend_min_duration_seconds(durations: list[int]) -> int | None:
    """Heuristic cutoff that trims the short tail while keeping the longer
    videos: the 20th percentile, rounded down to a whole minute (never below
    one minute). Not a statistical claim — a starting point for
    min_duration_minutes, to be refined by hand from the report."""
    if not durations:
        return None
    ordered = sorted(durations)
    idx = max(0, int(len(ordered) * 0.2) - 1)
    pct20 = ordered[idx]
    return max(60, (pct20 // 60) * 60)


def _fmt_num(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _parse_dt(value: str):
    from datetime import datetime
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────── aggregation ───────────────────────────

def compute_channel_stats(channel: dict, videos: list[VideoRecord]) -> dict:
    checked = [v for v in videos if v.transcript_error is None]
    available = [v for v in checked if v.transcript_available]
    manual = [v for v in available if v.transcript_is_manual]
    non_live = [v for v in videos if not v.is_live]
    durations = [v.duration_seconds for v in non_live]

    published = sorted(v.published_at for v in videos if v.published_at)
    daily_rate = None
    if len(published) >= 2:
        span_days = (_parse_dt(published[-1]) - _parse_dt(published[0])).total_seconds() / 86400
        if span_days > 0:
            daily_rate = len(videos) / span_days

    buckets = {label: 0 for label, _, _ in DURATION_BUCKETS}
    for d in durations:
        buckets[duration_bucket(d)] += 1

    return {
        "channel": channel,
        "sample_size": len(videos),
        "daily_upload_rate": daily_rate,
        "median_duration": statistics.median(durations) if durations else None,
        "duration_buckets": buckets,
        "durations": durations,
        "live_count": len(videos) - len(non_live),
        "transcript_checked": len(checked),
        "transcript_available_pct": (len(available) / len(checked) * 100) if checked else None,
        "transcript_manual_pct": (len(manual) / len(available) * 100) if available else None,
    }


def compute_language_stats(channels: list[dict], videos_by_channel: dict[str, list[VideoRecord]]) -> dict[str, dict]:
    by_lang: dict[str, list[VideoRecord]] = {}
    for channel in channels:
        by_lang.setdefault(channel["language"], []).extend(videos_by_channel.get(channel["handle"], []))

    result = {}
    for lang, videos in by_lang.items():
        checked = [v for v in videos if v.transcript_error is None]
        available = [v for v in checked if v.transcript_available]
        manual = [v for v in available if v.transcript_is_manual]
        result[lang] = {
            "video_count": len(videos),
            "transcript_available_pct": (len(available) / len(checked) * 100) if checked else None,
            "transcript_manual_pct": (len(manual) / len(available) * 100) if available else None,
            "transcript_auto_pct": ((len(available) - len(manual)) / len(available) * 100) if available else None,
        }
    return result


# ─────────────────────────── report rendering ───────────────────────────

CHANNEL_TABLE_HEADER = (
    "| المعرّف | الاسم | عدد العيّنة | معدّل الرفع اليومي | وسيط المدة "
    "| < 5 د | 5-15 | 15-30 | 30-90 | > 90 | بث مباشر | توفّر النص | يدوي % |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|---|---|"
)


def render_channel_table(stats_list: list[dict]) -> str:
    rows = [CHANNEL_TABLE_HEADER]
    for stats in stats_list:
        ch = stats["channel"]
        b = stats["duration_buckets"]
        median = format_mmss(stats["median_duration"]) if stats["median_duration"] is not None else "—"
        rows.append(
            f"| {ch['handle']} | {ch['name']} | {stats['sample_size']} | "
            f"{_fmt_num(stats['daily_upload_rate'])} | {median} | "
            f"{b['< 5 د']} | {b['5-15 د']} | {b['15-30 د']} | {b['30-90 د']} | {b['> 90 د']} | "
            f"{stats['live_count']} | {_fmt_pct(stats['transcript_available_pct'])} | "
            f"{_fmt_pct(stats['transcript_manual_pct'])} |"
        )
    return "\n".join(rows)


LANGUAGE_TABLE_HEADER = (
    "| اللغة | عدد الفيديوهات | توفّر النص | يدوي | تلقائي |\n"
    "|---|---|---|---|---|"
)


def render_language_table(language_stats: dict[str, dict]) -> str:
    rows = [LANGUAGE_TABLE_HEADER]
    for lang in ["ar", "tr", "fa", "he", "en"]:
        stats = language_stats.get(lang)
        if stats is None:
            continue
        rows.append(
            f"| {lang} | {stats['video_count']} | {_fmt_pct(stats['transcript_available_pct'])} | "
            f"{_fmt_pct(stats['transcript_manual_pct'])} | {_fmt_pct(stats['transcript_auto_pct'])} |"
        )
    return "\n".join(rows)


def render_errors_section(errors: list[dict]) -> str:
    lines = ["### الأخطاء", ""]
    if not errors:
        lines.append("لا أخطاء مسجَّلة.")
        return "\n".join(lines)
    for err in errors:
        video_part = f" (فيديو {err['video_id']})" if err.get("video_id") else ""
        lines.append(f"- **{err['channel']}**{video_part}: {err['reason']}")
    return "\n".join(lines)


def render_recommendations(stats_list: list[dict], language_stats: dict[str, dict]) -> str:
    lines = ["### التوصيات", "", "**حدّ أدنى مقترح للمدة (يقطع الذيل القصير):**", ""]
    for stats in stats_list:
        ch = stats["channel"]
        rec = recommend_min_duration_seconds(stats["durations"])
        lines.append(f"- {ch['name']} ({ch['handle']}): {format_mmss(rec) if rec is not None else '—'}")
    lines.append("")
    lines.append("**لغات نسبة توفّر النص فيها دون 50٪:**")
    low = [
        lang for lang, s in language_stats.items()
        if s["transcript_available_pct"] is not None and s["transcript_available_pct"] < 50
    ]
    if low:
        for lang in low:
            lines.append(f"- {lang}: {_fmt_pct(language_stats[lang]['transcript_available_pct'])}")
    else:
        lines.append("- لا توجد لغة دون 50٪ في هذه العيّنة.")
    return "\n".join(lines)


def render_survey_report(stats_list: list[dict], language_stats: dict[str, dict], errors: list[dict]) -> str:
    return "\n".join([
        "# تقرير استطلاع قنوات يوتيوب (Issue #619)",
        "",
        "تقرير قياس فقط — لا أنبوب ولا نشر. انظر CLAUDE.md لسياق المهمة.",
        "",
        "### جدول القنوات",
        "",
        render_channel_table(stats_list),
        "",
        "### جدول اللغات",
        "",
        render_language_table(language_stats),
        "",
        render_errors_section(errors),
        "",
        render_recommendations(stats_list, language_stats),
        "",
    ])


def render_titles_file(videos: list[VideoRecord]) -> str:
    return "\n".join(f"{format_mmss(v.duration_seconds)}  {v.title}" for v in videos) + "\n"


# ─────────────────────────── config.yaml channels section ───────────────────────────

CHANNELS_HEADER_COMMENT = (
    "# ── قنوات يوتيوب (قياس أولي — Issue #619) ─────────────────\n"
    "# نتاج tools/measure_channels.py، سكربت يدوي بحت (انظر CLAUDE.md) —\n"
    "# لا يُشغَّل من Actions. programs وexclude_patterns فارغتان عمدًا،\n"
    "# تُملآن يدويًا من reports/titles/<handle>.txt. min_duration_minutes\n"
    "# قيمة مؤقتة تُصقَل من توصيات reports/channel_survey.md.\n"
)


def render_channels_yaml(channels: list[dict]) -> str:
    data = [
        {
            "handle": ch["handle"],
            "channel_id": ch["channel_id"],
            "name": ch["name"],
            "language": ch["language"],
            "bloc": ch["bloc"],
            "bias_note": ch["bias_note"],
            "active": True,
            "min_duration_minutes": 8,
            "programs": [],
            "exclude_patterns": [],
        }
        for ch in channels
    ]
    dumped = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    indented = "\n".join(("  " + line if line else line) for line in dumped.splitlines())
    return "channels:\n" + indented + "\n"


def insert_channels_section(config_text: str, channels: list[dict]) -> str:
    """Replace an existing top-level `channels:` section (plus the blank-line
    separator and header comment this script writes right above it) in
    place, or append a new one at the end. Never touches any other section
    of the file. Idempotent: re-running on its own output changes nothing."""
    block = "\n" + CHANNELS_HEADER_COMMENT + render_channels_yaml(channels)
    lines = config_text.splitlines(keepends=True)

    start = None
    for i, line in enumerate(lines):
        if line.strip() == "channels:":
            start = i
            break

    if start is None:
        prefix = config_text if config_text.endswith("\n") else config_text + "\n"
        return prefix + block

    header_start = start
    while header_start > 0 and lines[header_start - 1].startswith("#"):
        header_start -= 1
    if header_start > 0 and lines[header_start - 1] == "\n":
        header_start -= 1

    end = len(lines)
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if line.strip() and not line[0].isspace():
            end = j
            break

    return "".join(lines[:header_start]) + block + "".join(lines[end:])


# ─────────────────────────── network ───────────────────────────

def youtube_api_get(endpoint: str, params: dict, api_key: str) -> dict:
    resp = requests.get(f"{API_BASE}/{endpoint}", params={**params, "key": api_key}, timeout=20)
    resp.raise_for_status()
    return resp.json()


def verify_unconfirmed_handles(channels: list[dict], api_key: str, errors: list[dict]) -> None:
    for channel in channels:
        if not channel.get("unconfirmed"):
            continue
        try:
            data = youtube_api_get("channels", {"part": "id", "forHandle": channel["handle"]}, api_key)
        except requests.RequestException as exc:
            errors.append({"channel": channel["name"], "video_id": None,
                            "reason": f"تعذّر التحقق من المعرّف عبر forHandle: {exc}"})
            continue
        items = data.get("items", [])
        found_id = items[0]["id"] if items else None
        if found_id != channel["channel_id"]:
            errors.append({
                "channel": channel["name"], "video_id": None,
                "reason": f"معرّف forHandle لا يطابق القائمة: متوقَّع {channel['channel_id']}، والفعلي {found_id}",
            })


def fetch_channel_sample(channel: dict, api_key: str, errors: list[dict]) -> tuple[list[str], dict[str, dict]]:
    uploads_id = uploads_playlist_id(channel["channel_id"])
    try:
        data = youtube_api_get(
            "playlistItems",
            {"part": "contentDetails", "playlistId": uploads_id, "maxResults": SAMPLE_SIZE},
            api_key,
        )
    except requests.RequestException as exc:
        errors.append({"channel": channel["name"], "video_id": None, "reason": f"فشل playlistItems.list: {exc}"})
        return [], {}

    video_ids = [item["contentDetails"]["videoId"] for item in data.get("items", [])]
    if not video_ids:
        errors.append({"channel": channel["name"], "video_id": None, "reason": "لا فيديوهات في قائمة الرفع"})
        return [], {}

    meta_by_id: dict[str, dict] = {}
    for batch_start in range(0, len(video_ids), 50):
        batch = video_ids[batch_start:batch_start + 50]
        try:
            vdata = youtube_api_get(
                "videos", {"part": "contentDetails,snippet,liveStreamingDetails", "id": ",".join(batch)}, api_key
            )
        except requests.RequestException as exc:
            for vid in batch:
                errors.append({"channel": channel["name"], "video_id": vid, "reason": f"فشل videos.list: {exc}"})
            continue
        for item in vdata.get("items", []):
            meta_by_id[item["id"]] = item

    return video_ids, meta_by_id


def build_video_records(channel: dict, video_ids: list[str], meta_by_id: dict[str, dict],
                         errors: list[dict]) -> list[VideoRecord]:
    records = []
    for vid in video_ids:
        item = meta_by_id.get(vid)
        if item is None:
            errors.append({"channel": channel["name"], "video_id": vid,
                            "reason": "لا بيانات وصفية (videos.list لم يُعِد هذا المعرّف)"})
            continue
        snippet = item.get("snippet", {})
        content = item.get("contentDetails", {})
        is_live = "liveStreamingDetails" in item or snippet.get("liveBroadcastContent") == "live"
        try:
            duration = parse_iso8601_duration(content.get("duration", "PT0S"))
        except ValueError as exc:
            errors.append({"channel": channel["name"], "video_id": vid, "reason": str(exc)})
            continue
        records.append(VideoRecord(
            channel_handle=channel["handle"],
            channel_name=channel["name"],
            video_id=vid,
            title=snippet.get("title", ""),
            duration_seconds=duration,
            published_at=snippet.get("publishedAt", ""),
            is_live=is_live,
        ))
    return records


def _pick_best_transcript(transcript_list) -> Any:
    manual, generated = None, None
    for t in transcript_list:
        if not t.is_generated and manual is None:
            manual = t
        elif t.is_generated and generated is None:
            generated = t
    return manual or generated


def check_transcripts(videos: list[VideoRecord], errors: list[dict]) -> None:
    """Sequential, list-only transcript availability check — never fetches
    transcript text, per the issue's "no transcript text is ever saved"
    constraint. Aborts the whole run (no retry loop) on IpBlocked/RequestBlocked.

    Uses proxy_config.get_proxy_config() -- a no-op (None) when run from the
    owner's home IP as this script's docstring requires, since the Webshare
    secrets are only ever set in the Actions environment (Issue #629)."""
    from youtube_transcript_api import IpBlocked, RequestBlocked, YouTubeTranscriptApi

    from src.proxy_config import get_proxy_config

    ytt_api = YouTubeTranscriptApi(proxy_config=get_proxy_config())
    for v in videos:
        try:
            transcript_list = ytt_api.list(v.video_id)
        except (IpBlocked, RequestBlocked) as exc:
            v.transcript_error = str(exc)
            errors.append({"channel": v.channel_name, "video_id": v.video_id, "reason": f"حُجب الطلب: {exc}"})
            raise FatalBlockedError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — any failure must be visible, never silent
            v.transcript_error = str(exc)
            errors.append({"channel": v.channel_name, "video_id": v.video_id, "reason": str(exc)})
        else:
            best = _pick_best_transcript(transcript_list)
            if best is None:
                v.transcript_available = False
            else:
                v.transcript_available = True
                v.transcript_language = best.language_code
                v.transcript_is_manual = not best.is_generated
        time.sleep(random.uniform(*TRANSCRIPT_SLEEP_RANGE))


# ─────────────────────────── output ───────────────────────────

def write_report(stats_list: list[dict], language_stats: dict[str, dict], errors: list[dict]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_survey_report(stats_list, language_stats, errors), encoding="utf-8")


def write_title_files(channels: list[dict], videos_by_channel: dict[str, list[VideoRecord]]) -> None:
    TITLES_DIR.mkdir(parents=True, exist_ok=True)
    for channel in channels:
        videos = videos_by_channel.get(channel["handle"], [])
        handle_name = channel["handle"].lstrip("@")
        (TITLES_DIR / f"{handle_name}.txt").write_text(render_titles_file(videos), encoding="utf-8")


def write_config_channels(channels: list[dict]) -> None:
    text = CONFIG_PATH.read_text(encoding="utf-8")
    CONFIG_PATH.write_text(insert_channels_section(text, channels), encoding="utf-8")


# ─────────────────────────── main ───────────────────────────

def main() -> int:
    import os

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("YOUTUBE_API_KEY غير موجود في البيئة. صدّره ثم أعد التشغيل:\n"
              "  export YOUTUBE_API_KEY=...", file=sys.stderr)
        return 1

    channels = CHANNELS
    errors: list[dict] = []
    videos_by_channel: dict[str, list[VideoRecord]] = {}
    stats_list: list[dict] = []
    blocked = False

    verify_unconfirmed_handles(channels, api_key, errors)

    for i, channel in enumerate(channels, 1):
        video_ids, meta_by_id = fetch_channel_sample(channel, api_key, errors)
        videos = build_video_records(channel, video_ids, meta_by_id, errors)

        try:
            check_transcripts(videos, errors)
        except FatalBlockedError:
            videos_by_channel[channel["handle"]] = videos
            stats_list.append(compute_channel_stats(channel, videos))
            blocked = True
            break

        videos_by_channel[channel["handle"]] = videos
        stats_list.append(compute_channel_stats(channel, videos))

        with_transcript = sum(1 for v in videos if v.transcript_available)
        print(f"[{i}/{len(channels)}] {channel['name']} — {len(videos)} فيديو — {with_transcript} بنص")

    language_stats = compute_language_stats(channels, videos_by_channel)

    write_report(stats_list, language_stats, errors)
    write_title_files(channels, videos_by_channel)
    write_config_channels(channels)

    if blocked:
        print("توقّف بسبب حجب من يوتيوب — التقرير جزئي. راجع قسم الأخطاء.", file=sys.stderr)
        return 1

    print(f"تم. راجع {REPORT_PATH}, {TITLES_DIR}, و{CONFIG_PATH}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
