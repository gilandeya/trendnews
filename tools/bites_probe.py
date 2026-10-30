"""أداة قياس (خطة إعادة البناء V، المرحلة V0): هل يجد استخراج «المقاطع» من النص الكامل مادة ريل أكثر وأتمّ من النقاط الحالية
على الفيديوهات نفسها؟ قياس فقط: لا شيء في المسار الحي يتغير، ولا مسودة ولا قضية.

التشغيل (في الـworkflow، بالبروكسي ومفتاح API ومستودع البيانات الخاص مسحوبًا):
    python tools/bites_probe.py --videos 10 --days 3

المخرجات:
  - youtube-data/bites_probe/<التاريخ>/<video_id>.json — النص والمقاطع والنقاط كاملة (المستودع الخاص وحده، لأن فيها نصوصًا محمية).
  - state/bites_probe/<التاريخ>.json — أرقام فقط بلا أي نص (هذا المستودع عام).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_videos(points_dir: Path, days: int, today: datetime) -> dict[str, dict]:
    """فيديوهات آخر `days` أيام من ملفات النقاط، ولكل فيديو بياناته ونقاطه."""
    oldest = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    videos: dict[str, dict] = {}
    for path in sorted(points_dir.glob("*.json"), reverse=True):
        if path.stem < oldest:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for p in data.get("points", []):
            vid = p.get("video_id")
            if not vid:
                continue
            v = videos.setdefault(vid, {"video_id": vid, "channel": p.get("channel", ""), "language": p.get("language", ""),
                                        "title": p.get("video_title", ""), "description": p.get("video_description", ""),
                                        "duration": p.get("duration_seconds"), "published": p.get("video_published", ""),
                                        "points": []})
            v["points"].append(p)
    return videos


def choose(videos: dict[str, dict], n: int) -> list[dict]:
    """قناة واحدة لكل فيديو أولًا (تنوّع القنوات واللغات أهم من الكثرة)، الأحدث أولًا، ثم يُكمل العدد من الباقي."""
    ordered = sorted(videos.values(), key=lambda v: v.get("published") or "", reverse=True)
    picked, seen = [], set()
    for v in ordered:
        if v["channel"] not in seen:
            picked.append(v)
            seen.add(v["channel"])
    for v in ordered:
        if v not in picked:
            picked.append(v)
    return picked[:n]


def _median(xs):
    return round(statistics.median(xs), 1) if xs else None


def point_numbers(points: list[dict], speaker_wps: float) -> dict:
    """أرقام النقاط الحالية للفيديو نفسه: العدد، والمطوَّع منها، ووسيط كلمات الاقتباس ومدته المقدرة."""
    words = [len((p.get("quote_original") or "").split()) for p in points]
    return {"points": len(points), "with_timestamp": sum(1 for p in points if p.get("timestamp") is not None),
            "opinion_or_forecast": sum(1 for p in points if p.get("type") in ("opinion", "forecast")),
            "quote_words_median": _median(words),
            "quote_seconds_median": _median([w / speaker_wps for w in words])}


def bite_numbers(res: dict) -> dict:
    bites = res.get("bites") or []
    named = [b for b in bites if b["speaker"]]
    debate = {b["speaker"] or f"?{i}" for i, b in enumerate(bites) if b["type"] in ("opinion", "forecast") and not b["is_host"]}
    return {"bites": len(bites), "rejected": len(res.get("rejected") or []),
            "rejected_reasons": [r["reason"] for r in res.get("rejected") or []],
            "seconds_median": _median([b["seconds"] for b in bites]),
            "types": {t: sum(1 for b in bites if b["type"] == t) for t in ("opinion", "forecast", "fact", "report")},
            "named": len(named), "host": sum(1 for b in bites if b["is_host"]),
            "distinct_named_speakers": len({b["speaker"] for b in named}),
            "opinion_speakers": len(debate),
            "error": res.get("error") or "", "stop_reason": res.get("stop_reason") or "",
            "usage": res.get("usage") or {}, "lines": res.get("total_lines"), "truncated": res.get("truncated")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", type=int, default=10)
    ap.add_argument("--days", type=int, default=3)
    args = ap.parse_args(argv)

    import requests

    from src import youtube_bites
    from src.config import YOUTUBE_POINTS_DIR, load_config
    from src.proxy_config import get_proxy_config, proxy_status_line

    cfg = load_config()
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d")
    points_dir = Path(os.environ.get("TRENDNEWS_YOUTUBE_POINTS_DIR") or YOUTUBE_POINTS_DIR)
    private_dir = points_dir.parents[1] / "bites_probe" / stamp
    public_path = ROOT / "state" / "bites_probe" / f"{stamp}.json"
    private_dir.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)

    proxy = get_proxy_config()
    print(proxy_status_line(proxy))
    session = requests.Session()
    backoff = list(cfg.path("youtube.extract.rate_limit_backoff_seconds", [15, 45, 90]))
    sleep_range = tuple(cfg.path("youtube.extract.transcript_sleep_range", [5.0, 12.0]))
    speaker_wps = float(cfg.path("reel.script.speaker_wps", 2.3))

    picked = choose(load_videos(points_dir, args.days, now), args.videos)
    print(f"فيديوهات مختارة: {len(picked)}")
    rows = []
    for n, v in enumerate(picked):
        if n:
            time.sleep(random.uniform(*sleep_range))
        row = {"video_id": v["video_id"], "channel": v["channel"], "language": v["language"],
               "duration": v["duration"], "current": point_numbers(v["points"], speaker_wps)}
        segments, lang, limited = youtube_bites.fetch_segments(v["video_id"], proxy, session, backoff)
        if segments is None:
            row["fetch_error"] = lang[:200]
            rows.append(row)
            print(f"✗ {v['channel']} {v['video_id']}: تعذّر جلب النص — {lang[:120]}")
            if limited:
                break
            continue
        res = youtube_bites.extract(v, segments, lang, cfg)
        row["track_language"] = lang
        row["bites"] = bite_numbers(res)
        rows.append(row)
        (private_dir / f"{v['video_id']}.json").write_text(json.dumps(
            {"video": {k: v[k] for k in ("video_id", "channel", "language", "title", "description", "duration", "published")},
             "track_language": lang, "segments": segments, "result": res, "points": v["points"]},
            ensure_ascii=False, indent=1), encoding="utf-8")
        b = row["bites"]
        print(f"✓ {v['channel']} {v['video_id']}: نقاط {row['current']['points']} (وسيط {row['current']['quote_seconds_median']} ث) ← "
              f"مقاطع {b['bites']} (وسيط {b['seconds_median']} ث، مرفوض {b['rejected']}، متحدثو رأي {b['opinion_speakers']}) {b['error']}")

    done = [r for r in rows if "bites" in r]
    summary = {"videos": len(rows), "fetched": len(done),
               "points_total": sum(r["current"]["points"] for r in done),
               "bites_total": sum(r["bites"]["bites"] for r in done),
               "rejected_total": sum(r["bites"]["rejected"] for r in done),
               "videos_with_2_opinion_speakers": sum(1 for r in done if r["bites"]["opinion_speakers"] >= 2),
               "point_seconds_median": _median([s for r in done if (s := r["current"]["quote_seconds_median"])]),
               "bite_seconds_median": _median([s for r in done if (s := r["bites"]["seconds_median"])]),
               "input_tokens": sum((r["bites"]["usage"].get("input") or 0) for r in done),
               "output_tokens": sum((r["bites"]["usage"].get("output") or 0) for r in done)}
    public_path.write_text(json.dumps({"at": now.isoformat(), "summary": summary, "videos": rows},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
