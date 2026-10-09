"""مقاطع الريل: تحديد موضع الاقتباس في نص الفيديو، وتنزيل نافذته بسلّم درجات (Issue #1347، R3a).

قياس فقط في R3a؛ يعيد R3b استعمال الوحدة. لا يمسّ `youtube_extract.resolve_timestamp`:
تلك تعيد أول سطر يطابق وتبحث داخل سطر واحد، وهذه تجمع كل المواضع وتبحث عبر حد السطر.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from collections import deque
from pathlib import Path

log = logging.getLogger("trendnews.reel_clips")

TAIL_LINES = 30
WIDE_PAD_SECONDS = 5
LINE_MAX_CHARS = 300
SECRET_VARS = ("WEBSHARE_PROXY_USERNAME", "WEBSHARE_PROXY_PASSWORD", "GOOGLE_TTS_API_KEY")
# الدرجة (ج) تحتاج ffmpeg محليًا؛ المهلة تمنع تعليق التشغيل
LOCAL_CUT_TIMEOUT = 120


def scrub_text(text: str) -> str:
    """يخفي الأسرار ورموز الألوان؛ يحافظ على تعدد الأسطر (ذيل الخطأ يُقرأ سطرًا سطرًا)."""
    for var in SECRET_VARS:
        secret = os.environ.get(var)
        if secret:
            text = text.replace(secret, "***")
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


# ──────────────────────────── تحديد موضع الاقتباس ────────────────────────────


def _speech_rate(cfg) -> float:
    rate = cfg.path("reel.script.speech_rate_wps") if cfg is not None else None
    return float(rate) if rate else 2.3


def locate_quote(quote, segments, near, cfg=None) -> dict:
    """{start, end, matches, status, level}: found | ambiguous | missing.

    أسطر يوتيوب قصيرة (2–4 ثوانٍ) والاقتباس يمتد عدّة أسطر، فيُبنى نص واحد موصول من كل الأسطر
    المطبَّعة بـ`_normalize_for_anchor` نفسها مع خريطة موضع ← سطر، ويُبحث بالتدرّج: الاقتباس كاملًا
    ثم أول 8 كلمات (كل المواضع، الأقرب إلى near) ثم 5 ثم 3 (موضع واحد فقط وإلا ambiguous)،
    لأن الكلمات القليلة تتكرر فتُنسب إلى لحظة خاطئة بلا إنذار."""
    from bisect import bisect_right
    from src import youtube_extract
    norm = youtube_extract._normalize_for_anchor
    empty = {"start": None, "end": None, "matches": 0, "status": "missing", "level": None}
    if not isinstance(quote, str) or not segments:
        return empty
    target = norm(quote)
    words = target.split()
    if not words:
        return empty
    lines = [norm(text) for _, text in segments]
    starts, parts, pos = [], [], 0
    for ln in lines:
        starts.append(pos)
        parts.append(ln)
        pos += len(ln) + 1
    joined = " ".join(parts)
    rate = _speech_rate(cfg)

    def positions(needle_words: list[str]) -> list[int]:
        needle = " ".join(needle_words)
        found, idx = [], joined.find(needle)
        while idx != -1:
            before_ok = idx == 0 or joined[idx - 1] == " "
            after = idx + len(needle)
            if before_ok and (after == len(joined) or joined[after] == " "):
                found.append(idx)
            idx = joined.find(needle, idx + 1)
        return found

    def line_of(offset: int) -> int:
        return max(bisect_right(starts, offset) - 1, 0)

    def build(hits: list[int], level: str, status: str) -> dict:
        if near is not None:
            hits = sorted(hits, key=lambda h: abs(segments[line_of(h)][0] - near))
        first = line_of(hits[0])
        if level == "full":
            end = float(segments[line_of(hits[0] + len(target) - 1)][0])
        else:
            end = round(segments[first][0] + len(words) / rate, 1)
        return {"start": segments[first][0], "end": end, "matches": len(hits),
                "status": status, "level": level}

    hits = positions(words)
    if hits:
        return build(hits, "full", "found")
    for n, level, multi_ok in ((8, "8", True), (5, "5", False), (3, "3", False)):
        if len(words) <= n:
            continue
        hits = positions(words[:n])
        if not hits:
            continue
        if multi_ok or len(hits) == 1:
            return build(hits, level, "found")
        return build(hits, level, "ambiguous")
    return empty


# ──────────────────────────── سلّم التنزيل ────────────────────────────


class TailCapture:
    """logger لـyt-dlp يحتفظ بآخر أسطر المخرجات، ويحمل الصيغة المختارة للتقرير."""

    def __init__(self) -> None:
        self.lines: deque[str] = deque(maxlen=TAIL_LINES)
        self.format_id: str | None = None
        self.protocol: str | None = None

    def write(self, msg) -> None:
        for ln in str(msg).splitlines():
            if ln.strip():
                self.lines.append(ln)

    debug = info = warning = error = write

    def note_format(self, info: dict | None) -> None:
        if isinstance(info, dict):
            self.format_id = str(info.get("format_id") or "") or self.format_id
            self.protocol = str(info.get("protocol") or "") or self.protocol

    def tail(self) -> list[str]:
        return [scrub_text(ln)[:LINE_MAX_CHARS] for ln in self.lines]


class ClipDownloadError(RuntimeError):
    def __init__(self, message: str, failures: list[dict]):
        super().__init__(message)
        self.failures = failures


def _ydl_opts(out_path: Path, height: int, ranges, force_keyframes: bool, proxy, capture, hook) -> dict:
    opts = {
        "format": f"bv*[height<={height}]+ba/b[height<={height}]",
        "merge_output_format": "mp4",
        "download_ranges": ranges,
        "outtmpl": str(out_path.with_suffix("")) + ".%(ext)s",
        "progress_hooks": [hook],
        "logger": capture,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "overwrites": True,
    }
    if force_keyframes:
        opts["force_keyframes_at_cuts"] = True
    if proxy:
        opts["proxy"] = proxy
    return opts


def _run_tier(tier, video_id, start, end, height, out_path, proxy, capture) -> dict:
    """ينفّذ درجة واحدة فعليًا بـyt-dlp. (أ) الطريقة الحالية · (ب) 480p · (ج) نافذة أوسع ثم قص محلي."""
    import yt_dlp
    from yt_dlp.utils import download_range_func

    seen: dict[str, int] = {}

    def hook(d: dict) -> None:
        name = d.get("filename") or d.get("tmpfilename") or "?"
        got = d.get("downloaded_bytes")
        if isinstance(got, int):
            seen[name] = max(seen.get(name, 0), got)
        capture.note_format(d.get("info_dict"))

    url = f"https://www.youtube.com/watch?v={video_id}"
    if tier in ("a", "b"):
        h = height if tier == "a" else 480
        opts = _ydl_opts(out_path, h, download_range_func(None, [(start, end)]), True, proxy, capture, hook)
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        return {"bytes": sum(seen.values()), "format_id": capture.format_id, "protocol": capture.protocol}

    wide_start = max(0, start - WIDE_PAD_SECONDS)
    wide_end = end + WIDE_PAD_SECONDS
    wide = out_path.with_name(out_path.stem + "_wide.mp4")
    opts = _ydl_opts(wide, 480, download_range_func(None, [(wide_start, wide_end)]), False, proxy, capture, hook)
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    wide_actual = wide if wide.exists() else next(iter(sorted(wide.parent.glob(wide.stem + ".*"))), None)
    if wide_actual is None:
        raise RuntimeError("لا ملف للنافذة الأوسع")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start - wide_start), "-t", str(end - start),
           "-i", str(wide_actual), "-c:v", "libx264", "-c:a", "aac", str(out_path.with_suffix(".mp4"))]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=LOCAL_CUT_TIMEOUT)
    capture.write(proc.stderr or "")
    wide_actual.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg local cut exited with code {proc.returncode}")
    return {"bytes": sum(seen.values()), "format_id": capture.format_id, "protocol": capture.protocol}


def download_clip(video_id: str, start: int, end: int, height: int, out_path: Path,
                  proxy: str | None, *, runner=_run_tier) -> dict:
    """يجرّب الدرجات a ثم b ثم c حتى تنجح واحدة ويسجّل رقمها في `tier`. عند فشل كل الدرجات
    يرفع ClipDownloadError بـ`failures` (لكل درجة: error_tail وformat_id وprotocol)."""
    failures: list[dict] = []
    for tier in ("a", "b", "c"):
        capture = TailCapture()
        try:
            res = runner(tier, video_id, start, end, height, out_path, proxy, capture) or {}
        except Exception as exc:  # noqa: BLE001 -- فشل الدرجة ينقل إلى التالية
            capture.write(str(exc))
            failures.append({"tier": tier, "error_tail": capture.tail(),
                             "format_id": capture.format_id, "protocol": capture.protocol})
            continue
        return {"bytes": int(res.get("bytes", 0)), "tier": tier, "failures": failures,
                "format_id": res.get("format_id") or capture.format_id,
                "protocol": res.get("protocol") or capture.protocol}
    last = failures[-1]["error_tail"][-1:] or ["?"]
    raise ClipDownloadError(scrub_text(f"فشلت كل الدرجات: {last[0]}")[:200], failures)
