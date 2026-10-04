"""أداة قياس جدوى (Issue #1236): هل تُنزَّل مقاطع قصيرة من يوتيوب من GitHub Actions
عبر بروكسي Webshare، وبأي كلفة بايتات ودقة زمنية؟ قياس فقط -- لا ريل ولا نشر ولا
أثر على أي مسار قائم.

التشغيل:
    python tools/reel_clip_probe.py --clips 6 --seconds 12

المقاطع تُحفظ في youtube-data/reel_probe/<التاريخ>/ (مستودع البيانات الخاص المسحوب
في الـworkflow) لا في المستودع العام أبدًا؛ التقرير الرقمي وحده يُكتب إلى
state/reel_probe/<التاريخ>.json بلا اقتباسات ولا نصوص فيديو لأن هذا المستودع عام.

ما لا يُحتسب في «البايتات المنقولة عبر البروكسي» (التقدير أدنى من الحقيقة):
طلبات yt-dlp الوصفية (صفحة المشغّل، player/JS، قوائم الصيغ والـmanifest)، وكلفة
TLS/CONNECT وترويسات HTTP، وإعادات المحاولة الداخلية، وطلبات المكتبة لسحب النص
غير جسم النص نفسه. المحتسب: بايتات أجزاء الوسائط (progress hooks) + طول نص
الفيديو المسحوب بالـUTF-8 مرة واحدة لكل فيديو.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ترتيب تفضيل اللغات: كل لغة متاحة مرة قبل أي تكرار
LANGUAGE_ORDER = ["ar", "tr", "fa", "he", "en"]
# أول نقطتين تُنزَّلان بالجودتين للمقارنة، البقية بالأولى فقط
QUALITIES = [720, 480]
COMPARE_FIRST = 2
LEAD_SECONDS = 1  # بداية المقطع قبل لحظة النقطة بثانية
ANCHOR_WORDS = 5  # مرساة المطابقة: أول كلمات quote_original
ERROR_MAX_CHARS = 200
MONTH_DAYS = 30
CLIPS_PER_QUALITY_PER_DAY = 2


# ──────────────────────────── اختيار النقاط ────────────────────────────


def load_points(points_dir: Path, days: int, today: datetime) -> list[dict]:
    """نقاط ملفات <تاريخ>.json لآخر `days` أيام (بتاريخ اسم الملف)."""
    oldest = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    points: list[dict] = []
    if not points_dir.exists():
        return points
    for path in sorted(points_dir.glob("*.json")):
        if path.stem < oldest:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        points.extend(p for p in data.get("points", []) if isinstance(p, dict))
    return points


def _lang_rank(lang: str | None) -> int:
    return LANGUAGE_ORDER.index(lang) if lang in LANGUAGE_ORDER else len(LANGUAGE_ORDER)


def select_points(points: list[dict], clips: int) -> list[dict]:
    """نقاط بـtimestamp محلول فقط (0 صالح)، من قنوات مختلفة، وكل لغة مرة قبل
    تكرارها. تكرار القناة ممنوع إلا إن نفدت القنوات -- لا يحدث هنا عمدًا:
    الهدف قياس تنوع فعلي لا عدد."""
    usable = [p for p in points
              if isinstance(p.get("timestamp"), int) and not isinstance(p["timestamp"], bool)
              and p.get("video_id") and p.get("channel")]
    by_lang: dict[str, list[dict]] = {}
    for p in usable:
        by_lang.setdefault(p.get("language") or "?", []).append(p)
    langs = sorted(by_lang, key=_lang_rank)
    chosen: list[dict] = []
    used_channels: set[str] = set()
    while len(chosen) < clips:
        progressed = False
        for lang in langs:
            if len(chosen) >= clips:
                break
            queue = by_lang[lang]
            while queue:
                cand = queue.pop(0)
                if cand["channel"] in used_channels:
                    continue
                used_channels.add(cand["channel"])
                chosen.append(cand)
                progressed = True
                break
        if not progressed:
            break
    return chosen


def clip_window(timestamp: int, seconds: int) -> tuple[int, int]:
    start = max(0, int(timestamp) - LEAD_SECONDS)
    return start, start + seconds


# ──────────────────────────── حارس الدقة ────────────────────────────


def check_window(quote: str | None, segments: list[tuple[int, str]] | None,
                 start: int, end: int) -> dict:
    """يحدّد أين يقع quote_original زمنيًا في نص الفيديو نسبةً لنافذة المقطع.
    status: inside | outside | missing (غائب من النص) | unavailable (تعذّر السحب).
    الأعداد وحدها تُعاد -- لا نص."""
    if segments is None:
        return {"status": "unavailable", "offset_seconds": None}
    from src import youtube_extract
    anchor = " ".join((quote or "").split()[:ANCHOR_WORDS])
    found = youtube_extract.resolve_timestamp(anchor, segments)
    if found is None:
        return {"status": "missing", "offset_seconds": None}
    if start <= found <= end:
        return {"status": "inside", "offset_seconds": 0}
    off = start - found if found < start else found - end
    return {"status": "outside", "offset_seconds": off}


# ──────────────────────────── التنزيل ────────────────────────────


def proxy_url() -> str | None:
    """البروكسي نفسه الذي يستعمله youtube_extract (src/proxy_config.py)."""
    from src import proxy_config
    cfg = proxy_config.get_proxy_config()
    return cfg.url if cfg is not None else None


def _scrub(text: str) -> str:
    for var in ("WEBSHARE_PROXY_USERNAME", "WEBSHARE_PROXY_PASSWORD"):
        secret = os.environ.get(var)
        if secret:
            text = text.replace(secret, "***")
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    return " ".join(text.split())[:ERROR_MAX_CHARS]


def download_clip(video_id: str, start: int, end: int, height: int, out_path: Path,
                  proxy: str | None) -> dict:
    """ينزّل النافذة وحدها بـyt-dlp. يعيد {"bytes": مقدّر المنقول}، ويرفع عند الفشل."""
    import yt_dlp
    from yt_dlp.utils import download_range_func

    seen: dict[str, int] = {}

    def hook(d: dict) -> None:
        name = d.get("filename") or d.get("tmpfilename") or "?"
        got = d.get("downloaded_bytes")
        if isinstance(got, int):
            seen[name] = max(seen.get(name, 0), got)

    opts = {
        "format": f"bv*[height<={height}]+ba/b[height<={height}]",
        "merge_output_format": "mp4",
        "download_ranges": download_range_func(None, [(start, end)]),
        "force_keyframes_at_cuts": True,
        "outtmpl": str(out_path.with_suffix("")) + ".%(ext)s",
        "progress_hooks": [hook],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "overwrites": True,
    }
    if proxy:
        opts["proxy"] = proxy
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    return {"bytes": sum(seen.values())}


def fetch_segments(video_id: str):
    """(المقاطع الزمنية، بايتات النص) عبر youtube_extract.fetch_transcript نفسها."""
    from src import youtube_extract, proxy_config
    text, info, _ = youtube_extract.fetch_transcript(video_id, proxy_config.get_proxy_config())
    if text is None:
        return None, 0, info
    return youtube_extract.parse_transcript_segments(text), len(text.encode("utf-8")), None


# ──────────────────────────── التشغيل ────────────────────────────


def run_probe(points: list[dict], seconds: int, out_dir: Path, *,
              downloader=download_clip, transcript_fetcher=fetch_segments,
              proxy: str | None = None, clock=time.monotonic) -> list[dict]:
    attempts: list[dict] = []
    transcripts: dict[str, tuple] = {}
    for idx, p in enumerate(points):
        start, end = clip_window(p["timestamp"], seconds)
        vid = p["video_id"]
        first_use = vid not in transcripts
        if first_use:
            try:
                transcripts[vid] = transcript_fetcher(vid)
            except Exception as exc:  # noqa: BLE001 -- فشل النص لا يوقف القياس
                transcripts[vid] = (None, 0, _scrub(str(exc)))
        segments, text_bytes, _err = transcripts[vid]
        accuracy = check_window(p.get("quote_original"), segments, start, end)
        for q_i, height in enumerate(QUALITIES if idx < COMPARE_FIRST else QUALITIES[:1]):
            out_path = out_dir / f"{idx + 1:02d}_{p.get('language') or 'x'}_{height}p.mp4"
            t0 = clock()
            row = {"index": idx + 1, "channel": p["channel"], "language": p.get("language"),
                   "quality": f"{height}p", "window_start": start, "window_end": end,
                   "ok": False, "error": None, "size_bytes": 0, "proxy_bytes": 0}
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
                res = downloader(vid, start, end, height, out_path, proxy)
                actual = out_path if out_path.exists() else next(
                    iter(sorted(out_dir.glob(out_path.stem + ".*"))), None)
                row["size_bytes"] = actual.stat().st_size if actual else 0
                row["proxy_bytes"] = int(res.get("bytes", 0))
                row["ok"] = row["size_bytes"] > 0
                if not row["ok"]:
                    row["error"] = "لا ملف ناتج"
            except Exception as exc:  # noqa: BLE001 -- سبب كل فشل يُسجَّل والبقية تكمل
                row["error"] = _scrub(str(exc)) or type(exc).__name__
            row["seconds"] = round(clock() - t0, 2)
            # نص الفيديو يُحسب مرة واحدة: على أول محاولة لذلك الفيديو
            if first_use and q_i == 0:
                row["proxy_bytes"] += text_bytes
            row["accuracy"] = accuracy["status"]
            row["offset_seconds"] = accuracy["offset_seconds"]
            attempts.append(row)
    return attempts


def summarize(attempts: list[dict]) -> dict:
    ok = [a for a in attempts if a["ok"]]

    def avg(rows, key):
        return round(sum(r[key] for r in rows) / len(rows), 2) if rows else 0

    per_quality = {}
    for q in sorted({a["quality"] for a in ok}):
        rows = [a for a in ok if a["quality"] == q]
        per_quality[q] = avg(rows, "proxy_bytes")
    judged = [a for a in attempts if a["accuracy"] in ("inside", "outside", "missing")]
    exact = [a for a in judged if a["accuracy"] == "inside"]
    daily = CLIPS_PER_QUALITY_PER_DAY * sum(per_quality.get(f"{h}p", 0) for h in QUALITIES)
    return {
        "attempts": len(attempts), "succeeded": len(ok), "failed": len(attempts) - len(ok),
        "avg_size_bytes": avg(ok, "size_bytes"), "avg_seconds": avg(ok, "seconds"),
        "total_proxy_bytes": sum(a["proxy_bytes"] for a in attempts),
        "avg_proxy_bytes_by_quality": per_quality,
        "exact_window_ratio": round(len(exact) / len(judged), 2) if judged else None,
        "monthly_proxy_bytes_estimate": int(daily * MONTH_DAYS),
    }


def _mb(n: float) -> str:
    return f"{n / (1024 * 1024):.2f}"


def render_table(attempts: list[dict], s: dict) -> str:
    lines = ["| # | القناة | اللغة | الجودة | النتيجة | الزمن ث | الحجم MB | المنقول MB | النافذة |",
             "|---|---|---|---|---|---|---|---|---|"]
    for a in attempts:
        acc = a["accuracy"]
        if acc == "outside":
            acc = f"خارج ({a['offset_seconds']}ث)"
        result = "نجاح" if a["ok"] else f"فشل: {a['error']}"
        lines.append(f"| {a['index']} | {a['channel']} | {a['language']} | {a['quality']} | "
                     f"{result} | {a['seconds']} | {_mb(a['size_bytes'])} | "
                     f"{_mb(a['proxy_bytes'])} | {acc} |")
    ratio = "—" if s["exact_window_ratio"] is None else f"{s['exact_window_ratio']:.0%}"
    lines += ["",
              f"**المجموع:** نجاح {s['succeeded']} · فشل {s['failed']} من {s['attempts']} — "
              f"متوسط الحجم {_mb(s['avg_size_bytes'])} MB، متوسط الزمن {s['avg_seconds']} ث، "
              f"مجموع المنقول {_mb(s['total_proxy_bytes'])} MB، النوافذ الدقيقة {ratio}",
              "",
              f"**تقدير شهري** (ريل يوميًا بمقطعين من كل جودة، {MONTH_DAYS} يومًا): "
              f"{_mb(s['monthly_proxy_bytes_estimate'])} MB",
              "",
              "_المنقول تقدير أدنى: لا يشمل طلبات yt-dlp الوصفية ولا ترويسات TLS/HTTP ولا "
              "إعادات المحاولة، ويشمل أجزاء الوسائط ونص الفيديو مرة لكل فيديو._"]
    return "\n".join(lines)


def build_report(date: str, args, attempts: list[dict], s: dict) -> dict:
    """أرقام وأسباب فشل مختصرة فقط -- لا quote ولا anchor ولا نص فيديو."""
    return {"date": date, "clips": args.clips, "seconds": args.seconds,
            "attempts": attempts, "summary": s}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--clips", type=int, default=6)
    ap.add_argument("--seconds", type=int, default=12)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--out-root", default=str(ROOT / "youtube-data" / "reel_probe"))
    ap.add_argument("--report-dir", default=str(ROOT / "state" / "reel_probe"))
    args = ap.parse_args(argv)

    from src.config import YOUTUBE_POINTS_DIR
    now = datetime.now(timezone.utc)
    date = now.strftime("%Y-%m-%d")
    points = select_points(load_points(Path(YOUTUBE_POINTS_DIR), args.days, now), args.clips)
    print(f"نقاط مختارة: {len(points)}", file=sys.stderr)

    attempts = run_probe(points, args.seconds, Path(args.out_root) / date, proxy=proxy_url())
    s = summarize(attempts)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"{date}.json").write_text(
        json.dumps(build_report(date, args, attempts, s), ensure_ascii=False, indent=2),
        encoding="utf-8")
    table = render_table(attempts, s)
    print(table)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(table + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
