"""One-off diagnostic script for Issue #626 ("اختبار الحجب من Actions").

Answers a single question: does YouTube block transcript-listing calls made
from a GitHub Actions runner IP the way it's known to block generic
cloud-provider ranges? Never fetches transcript text -- only lists which
transcript tracks exist for a video (youtube_transcript_api's list(), never
.fetch()). Prints a report to stdout only: no files written, nothing
committed, nothing saved beyond the run's own log.

Must be triggered manually via workflow_dispatch -- see
.github/workflows/test-actions-block.yml. Not part of any pipeline path.

Usage (locally or from the workflow):
    YOUTUBE_API_KEY=... python tools/test_actions_block.py
"""
from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Reusing measure_channels.py's pure helpers (uploads playlist id, generic
# YouTube Data API GET) instead of duplicating them -- both scripts talk to
# the same API the same way.
from tools.measure_channels import uploads_playlist_id, youtube_api_get  # noqa: E402

CONFIG_PATH = ROOT / "config.yaml"
VIDEOS_PER_CHANNEL = 10  # 4 blocs x 10 = 40 attempts, per the issue's spec
IP_ECHO_URL = "https://api.ipify.org"
# Sequential with a random gap, same shape as measure_channels.py's transcript
# check -- no concurrency, so this looks like ordinary usage, not a scrape burst.
SLEEP_RANGE = (2.0, 5.0)

# Judgment thresholds on the success ratio (issue's spec).
SUCCESS_NO_BLOCK = 0.70
SUCCESS_PARTIAL = 0.30


def pick_probe_channels(channels: list[dict]) -> list[dict]:
    """First channel of each bloc, in the order blocs first appear in the
    input list -- data-driven off config.yaml's channel roster instead of
    hardcoding four handles here, so it tracks the roster if it changes."""
    picked: dict[str, dict] = {}
    for ch in channels:
        picked.setdefault(ch["bloc"], ch)
    return list(picked.values())


def load_probe_channels() -> list[dict]:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return pick_probe_channels(config.get("channels", []))


def echo_egress_ip() -> str:
    """Diagnostic only -- printed so one run's report can be told apart from
    another's. Never used to make any decision in this script."""
    try:
        resp = requests.get(IP_ECHO_URL, timeout=10)
        resp.raise_for_status()
        return resp.text.strip()
    except requests.RequestException as exc:
        return f"تعذّر التحقق ({exc})"


def collect_video_ids(channels: list[dict], api_key: str) -> list[str]:
    video_ids: list[str] = []
    for channel in channels:
        uploads_id = uploads_playlist_id(channel["channel_id"])
        try:
            data = youtube_api_get(
                "playlistItems",
                {"part": "contentDetails", "playlistId": uploads_id, "maxResults": VIDEOS_PER_CHANNEL},
                api_key,
            )
        except requests.RequestException as exc:
            print(f"تعذّر جلب فيديوهات {channel['handle']}: {exc}", file=sys.stderr)
            continue
        video_ids.extend(item["contentDetails"]["videoId"] for item in data.get("items", []))
    return video_ids


def probe_transcripts(video_ids: list[str]) -> dict[str, int]:
    """Sequential, list()-only pass. Never stops on a block -- the point is
    measuring the block *rate* across the whole sample, not just detecting
    that a block happened once (unlike measure_channels.py's check_transcripts,
    which aborts immediately -- this script's whole purpose is different)."""
    from youtube_transcript_api import (
        IpBlocked,
        NoTranscriptFound,
        RequestBlocked,
        TranscriptsDisabled,
        VideoUnavailable,
        YouTubeTranscriptApi,
    )

    ytt_api = YouTubeTranscriptApi()
    counts = {"success": 0, "blocked": 0, "no_transcript": 0, "other": 0}
    for i, video_id in enumerate(video_ids):
        try:
            ytt_api.list(video_id)
        except (IpBlocked, RequestBlocked):
            counts["blocked"] += 1
        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
            # Legitimate, unrelated to blocking -- e.g. captions turned off
            # for that specific video. Must not be confused with a block.
            counts["no_transcript"] += 1
        except Exception:  # noqa: BLE001 -- any other failure must stay visible, never silently dropped
            counts["other"] += 1
        else:
            counts["success"] += 1
        if i < len(video_ids) - 1:
            time.sleep(random.uniform(*SLEEP_RANGE))
    return counts


def success_ratio(counts: dict[str, int]) -> float:
    attempts = sum(counts.values())
    return (counts["success"] / attempts) if attempts else 0.0


def judge(ratio: float) -> str:
    if ratio >= SUCCESS_NO_BLOCK:
        return "لا حجب"
    if ratio >= SUCCESS_PARTIAL:
        return "حجب جزئي"
    return "حجب كامل"


def render_report(ip: str, counts: dict[str, int]) -> str:
    ratio = success_ratio(counts)
    return "\n".join([
        "=== اختبار الحجب من GitHub Actions ===",
        f"عنوان الخروج: {ip}",
        f"المحاولات: {sum(counts.values())}",
        f"نجح: {counts['success']}",
        f"محجوب (IpBlocked/RequestBlocked): {counts['blocked']}",
        f"بلا ترجمة (سبب مشروع): {counts['no_transcript']}",
        f"أخطاء أخرى: {counts['other']}",
        f"نسبة النجاح: {ratio * 100:.0f}%",
        f"الحكم: {judge(ratio)}",
    ])


def main() -> int:
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("YOUTUBE_API_KEY غير موجود في البيئة. صدّره ثم أعد التشغيل:\n"
              "  export YOUTUBE_API_KEY=...", file=sys.stderr)
        return 1

    channels = load_probe_channels()
    ip = echo_egress_ip()
    video_ids = collect_video_ids(channels, api_key)
    counts = probe_transcripts(video_ids)
    print(render_report(ip, counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
