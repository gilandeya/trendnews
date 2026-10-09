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
    from src import reel_clips
    return " ".join(reel_clips.scrub_text(text).split())[:ERROR_MAX_CHARS]


def download_clip(video_id: str, start: int, end: int, height: int, out_path: Path,
                  proxy: str | None) -> dict:
    """سلّم التنزيل (a/b/c) في src/reel_clips.py؛ يعيد {"bytes", "tier", ...} ويرفع عند فشل الكل."""
    from src import reel_clips
    return reel_clips.download_clip(video_id, start, end, height, out_path, proxy)


def fetch_segments(video_id: str):
    """(المقاطع الزمنية، بايتات النص) عبر youtube_extract.fetch_transcript نفسها."""
    from src import youtube_extract, proxy_config
    text, info, _ = youtube_extract.fetch_transcript(video_id, proxy_config.get_proxy_config())
    if text is None:
        return None, 0, info
    # العنصر الثالث عند النجاح لغة النص المستعمَلة فعلًا (لا لغة القناة المسجَّلة)
    return youtube_extract.parse_transcript_segments(text), len(text.encode("utf-8")), info


# ──────────────────────────── التشغيل ────────────────────────────


def _row(idx: int, p: dict, height: int, start: int, end: int) -> dict:
    return {"index": idx, "channel": p["channel"], "language": p.get("language"),
            "quality": f"{height}p", "window_start": start, "window_end": end,
            "ok": False, "error": None, "size_bytes": 0, "proxy_bytes": 0,
            "tier": None, "failures": [], "format_id": None, "protocol": None}


def run_probe(points: list[dict], seconds: int, out_dir: Path, *,
              downloader=download_clip, transcript_fetcher=fetch_segments,
              proxy: str | None = None, clock=time.monotonic, cfg=None) -> list[dict]:
    from src import reel_clips, youtube_extract
    attempts: list[dict] = []
    transcripts: dict[str, tuple] = {}
    for idx, p in enumerate(points):
        old_start, old_end = clip_window(p["timestamp"], seconds)
        vid = p["video_id"]
        first_use = vid not in transcripts
        if first_use:
            try:
                transcripts[vid] = transcript_fetcher(vid)
            except Exception as exc:  # noqa: BLE001 -- فشل النص لا يوقف القياس
                transcripts[vid] = (None, 0, _scrub(str(exc)))
        segments, text_bytes, tr_info = transcripts[vid]
        # القديمة للمقارنة كما هي، والجديدة هي التي تحدّد النافذة المنزَّلة
        old = check_window(p.get("quote_original"), segments, old_start, old_end)
        loc = (reel_clips.locate_quote(p.get("quote_original"), segments, p["timestamp"], cfg)
               if segments is not None else
               {"start": None, "end": None, "matches": 0, "status": "unavailable"})
        anchor = " ".join((p.get("quote_original") or "").split()[:ANCHOR_WORDS])
        old_found = youtube_extract.resolve_timestamp(anchor, segments) if segments is not None else None
        delta = (loc["start"] - old_found) if loc["start"] is not None and old_found is not None else None
        if loc["start"] is not None and loc["status"] == "found":
            start = max(0, int(loc["start"]) - LEAD_SECONDS)
            end = start + seconds
        else:
            start, end = old_start, old_end
        meta = {"accuracy": old["status"], "offset_seconds": old["offset_seconds"],
                "new_status": loc["status"], "new_level": loc.get("level"), "new_matches": loc["matches"], "start_delta": delta,
                "transcript_language": tr_info if segments is not None else None}
        meta["language_mismatch"] = bool(segments is not None and tr_info and p.get("language")
                                         and tr_info != p.get("language"))
        if loc["status"] in ("missing", "ambiguous"):
            row = _row(idx + 1, p, QUALITIES[0], start, end)
            row.update(meta, error=f"rejected_{loc['status']}", seconds=0)
            attempts.append(row)
            continue
        for q_i, height in enumerate(QUALITIES if idx < COMPARE_FIRST else QUALITIES[:1]):
            out_path = out_dir / f"{idx + 1:02d}_{p.get('language') or 'x'}_{height}p.mp4"
            t0 = clock()
            row = _row(idx + 1, p, height, start, end)
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
                res = downloader(vid, start, end, height, out_path, proxy)
                actual = out_path if out_path.exists() else next(
                    iter(sorted(out_dir.glob(out_path.stem + ".*"))), None)
                row["size_bytes"] = actual.stat().st_size if actual else 0
                row["proxy_bytes"] = int(res.get("bytes", 0))
                row["tier"] = res.get("tier")
                row["failures"] = res.get("failures", [])
                row["format_id"], row["protocol"] = res.get("format_id"), res.get("protocol")
                row["ok"] = row["size_bytes"] > 0
                if not row["ok"]:
                    row["error"] = "لا ملف ناتج"
            except Exception as exc:  # noqa: BLE001 -- سبب كل فشل يُسجَّل والبقية تكمل
                row["error"] = _scrub(str(exc)) or type(exc).__name__
                row["failures"] = getattr(exc, "failures", [])
            row["seconds"] = round(clock() - t0, 2)
            # نص الفيديو يُحسب مرة واحدة: على أول محاولة لذلك الفيديو
            if first_use and q_i == 0:
                row["proxy_bytes"] += text_bytes
            row.update(meta)
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


def render_table(attempts: list[dict], s: dict, tts_rows: list[dict] | None = None,
                 rate_line: str | None = None) -> str:
    lines = ["| # | القناة | اللغة | الجودة | النتيجة | الدرجة | الزمن ث | الحجم MB | المنقول MB "
             "| النافذة (قديم) | الحالة الجديدة | المطابقة | الفارق ث | لغة النص |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in attempts:
        acc = a["accuracy"]
        if acc == "outside":
            acc = f"خارج ({a['offset_seconds']}ث)"
        result = "نجاح" if a["ok"] else f"فشل: {a['error']}"
        delta = "—" if a.get("start_delta") is None else a["start_delta"]
        tr_lang = a.get("transcript_language") or "—"
        if a.get("language_mismatch"):
            tr_lang += f" (≠{a['language']})"
        lines.append(f"| {a['index']} | {a['channel']} | {a['language']} | {a['quality']} | "
                     f"{result} | {a.get('tier') or '—'} | {a['seconds']} | {_mb(a['size_bytes'])} | "
                     f"{_mb(a['proxy_bytes'])} | {acc} | {a.get('new_status', '—')} | {a.get('new_level') or '—'} | {delta} | {tr_lang} |")
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
    if tts_rows:
        lines += ["", "| الصوت | الجنس | الحروف | المدة ث | كلمة/ث | الكلفة $ | الحالة |",
                  "|---|---|---|---|---|---|---|"]
        for t in tts_rows:
            lines.append(f"| {t['voice']} | {t['gender']} | {t.get('chars', '—')} | "
                         f"{t.get('seconds', '—')} | {t.get('wps', '—')} | {t.get('cost_usd', '—')} | "
                         f"{t.get('skipped') or t.get('error') or 'ok'} |")
    if rate_line:
        lines += ["", rate_line]
    return "\n".join(lines)


def build_report(date: str, args, attempts: list[dict], s: dict,
                 tts_rows: list[dict] | None = None, rate_line: str | None = None) -> dict:
    """أرقام وأسباب فشل مختصرة فقط -- لا quote ولا anchor ولا نص فيديو."""
    return {"date": date, "clips": args.clips, "seconds": args.seconds,
            "attempts": attempts, "summary": s, "tts": tts_rows or [], "tts_rate_line": rate_line}


# ──────────────────────────── عينات الصوت ────────────────────────────


def sample_lines(drafts_dir: Path, cfg) -> list[str]:
    """سطور الراوي والسؤال من أحدث مسودة ريل script_status="ready"، وإلا reel.tts.sample_lines."""
    best = None
    for path in Path(drafts_dir).glob("*/*.json"):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("format") == "reel" and d.get("script_status") == "ready":
            stamp = str(d.get("created_at") or path.parent.name)
            if best is None or stamp > best[0]:
                best = (stamp, d)
    if best:
        scenes = (best[1].get("script") or {}).get("scenes") or []
        lines = [sc.get("text") for sc in scenes if sc.get("kind") in ("narration", "question") and sc.get("text")]
        if lines:
            return lines
    return list(cfg.path("reel.tts.sample_lines") or [])


def audio_duration(path: Path) -> float | None:
    import subprocess
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                              "default=nw=1:nk=1", str(path)], capture_output=True, text=True, timeout=30)
        return float(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def run_tts(lines: list[str], out_dir: Path, cfg, *, synth=None,
            duration=audio_duration) -> tuple[list[dict], str | None]:
    from src import tts
    synth = synth or tts.synthesize
    text = " ".join(lines)
    words = len(text.split())
    rows: list[dict] = []
    for gender, voice in tts.all_voices(cfg):
        row = {"voice": voice, "gender": gender}
        res = synth(text, voice, cfg)
        if not res.get("ok"):
            row.update(skipped=res.get("skipped"), error=res.get("error"))
            rows.append(row)
            continue
        target = out_dir / "tts" / f"{voice}.mp3"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(res["audio"])
        secs = duration(target)
        row.update(chars=len(text), seconds=None if secs is None else round(secs, 2),
                   wps=round(words / secs, 2) if secs else None,
                   cost_usd=round(tts.estimate_cost(len(text), voice, cfg), 4))
        rows.append(row)
    wps = [r["wps"] for r in rows if r.get("wps")]
    current = cfg.path("reel.script.speech_rate_wps")
    line = None
    if wps:
        line = (f"متوسط سرعة الأصوات {sum(wps) / len(wps):.2f} كلمة/ث مقابل "
                f"reel.script.speech_rate_wps الحالية {current} (لم تُغيَّر)")
    return rows, line


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

    from src.config import DRAFTS_DIR, load_config
    cfg = load_config()
    attempts = run_probe(points, args.seconds, Path(args.out_root) / date, proxy=proxy_url(), cfg=cfg)
    s = summarize(attempts)
    tts_rows, rate_line = run_tts(sample_lines(Path(DRAFTS_DIR), cfg), Path(args.out_root) / date, cfg)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"{date}.json").write_text(
        json.dumps(build_report(date, args, attempts, s, tts_rows, rate_line),
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    table = render_table(attempts, s, tts_rows, rate_line)
    print(table)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(table + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
