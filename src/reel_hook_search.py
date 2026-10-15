"""بحث آلي عن لقطة فيديو من الحدث نفسه لخلفية الهوك (Issue #1440، R5c2).

التدفق: عبارات بصرية من Haiku ← بحث يوتيوب مقصور على قنوات الأخبار والوكالات ← تنزيل أول ثوانٍ من كل مرشّح ← صفائح 4×3 بالثواني
مرقّمة يصنّفها Haiku بالصور ← أطول سلسلة ثوانٍ كلها لقطات من الحدث نفسه. كل شبكة وملف وفحص عبر Deps كي تُزيَّف، وهذه الوحدة لا تستورد
reel_render (تستورده هي) فلا حلقة استيراد. لا يُرفع منها فشل إلى التركيب: المستدعي يلتقط ويُبقي الهوك بصورة الخبر."""
from __future__ import annotations

import base64
import io
import logging
import os
import re
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw

from . import imaging, llm

log = logging.getLogger(__name__)

COLS, ROWS = 4, 3
CELL_W, CELL_H = 320, 180
KINDS = ["event_footage", "studio", "anchor", "graphic", "text_heavy", "other"]

MAKE_QUERIES_TOOL = {
    "name": "make_queries",
    "description": "عبارات بحث قصيرة تصف المشهد البصري للحدث",
    "input_schema": {"type": "object", "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
                     "required": ["queries"]},
}

CLASSIFY_TOOL = {
    "name": "classify_seconds",
    "description": "تصنيف كل ثانية مرقّمة في الصفيحة",
    "input_schema": {"type": "object", "properties": {"seconds": {"type": "array", "items": {
        "type": "object",
        "properties": {"t": {"type": "integer"}, "kind": {"type": "string", "enum": KINDS}, "relevant": {"type": "boolean"}},
        "required": ["t", "kind", "relevant"]}}}, "required": ["seconds"]},
}


def _client():
    from anthropic import Anthropic

    from .config import env
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def _tool_input(resp, name: str) -> dict:
    if getattr(resp, "stop_reason", "") == "refusal":
        raise RuntimeError("رفض النموذج الطلب")
    for b in getattr(resp, "content", None) or []:
        if getattr(b, "type", "") == "tool_use" and getattr(b, "name", "") == name:
            return getattr(b, "input", None) or {}
    raise ValueError(f"ردّ غير صالح: لا أداة {name}")


# ───────────────────────────── العبارات ─────────────────────────────

def event_text(script: dict, draft: dict) -> str:
    """وصف الحدث للنموذجين: عنوان السيناريو وعنوان المسودة وevent إن وُجد."""
    parts = [script.get("title"), draft.get("title"), draft.get("event") or script.get("event")]
    return " — ".join(str(p) for p in parts if p)


def call_make_queries(script: dict, draft: dict, cfg, client=None) -> list[str]:
    hcfg = cfg.path("reel.hook_search")
    resp = llm.create(client or _client(), cfg=cfg, model=hcfg.get("model", "haiku"), max_tokens=int(hcfg.get("queries_max_tokens", 400)),
                      system=hcfg.get("queries_system", ""), tools=[MAKE_QUERIES_TOOL],
                      tool_choice={"type": "tool", "name": MAKE_QUERIES_TOOL["name"]},
                      messages=[{"role": "user", "content": "الحدث: " + event_text(script, draft)}])
    qs = _tool_input(resp, MAKE_QUERIES_TOOL["name"]).get("queries")
    out = [" ".join(str(q).split()) for q in qs or [] if str(q).strip()]
    if not out:
        raise ValueError("لا عبارات بحث")
    return out[:3]


# ───────────────────────────── البحث ─────────────────────────────

def search_window(topic_date: str, hcfg) -> tuple[str, str]:
    d = date.fromisoformat(str(topic_date)[:10])
    after = d - timedelta(days=int(hcfg.get("days_before", 2)))
    before = d + timedelta(days=int(hcfg.get("days_after", 2)))
    return f"{after.isoformat()}T00:00:00Z", f"{before.isoformat()}T00:00:00Z"


def channel_allowed(channel: str, hcfg) -> bool:
    low = (channel or "").casefold()
    return any(str(n).casefold() in low for n in hcfg.get("channels", []) if str(n).strip())


def find_candidates(queries: list[str], topic_date: str, cfg, deps) -> list[dict]:
    """نتائج كل العبارات بترتيب الظهور، مقبولها قناة من القائمة ومدته ≤ max_video_seconds، بلا مكرر، أول max_candidates."""
    hcfg = cfg.path("reel.hook_search")
    after, before = search_window(topic_date, hcfg)
    seen: dict[str, dict] = {}
    for q in queries:
        for r in deps.yt_search(q, after, before, int(hcfg.get("search_results", 15))) or []:
            vid = r.get("video_id")
            if vid and vid not in seen and channel_allowed(r.get("channel", ""), hcfg):
                seen[vid] = r
    if not seen:
        return []
    durations = deps.yt_durations(list(seen)) or {}
    limit = float(hcfg.get("max_video_seconds", 600))
    ok = [r for vid, r in seen.items() if durations.get(vid) is not None and float(durations[vid]) <= limit]
    return ok[:int(hcfg.get("max_candidates", 4))]


# ───────────────────────────── الصفيحة والتصنيف ─────────────────────────────

def build_sheet(images: list, first_t: int, cfg) -> Image.Image:
    """صفيحة COLS×ROWS: الخانة k عليها رقم ثانيتها first_t+k بخط واضح بأعلى يسارها؛ الخانة بلا لقطة تبقى سوداء بلا رقم."""
    sheet = Image.new("RGB", (COLS * CELL_W, ROWS * CELL_H), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    font = imaging.load_font(None, 44, "Bold")
    for k, img in enumerate(images[:COLS * ROWS]):
        x, y = (k % COLS) * CELL_W, (k // COLS) * CELL_H
        sheet.paste(img.convert("RGB").resize((CELL_W, CELL_H)), (x, y))
        label = str(first_t + k)
        draw.rectangle([x, y, x + 12 + 26 * len(label) + 10, y + 52], fill=(0, 0, 0))
        draw.text((x + 8, y + 4), label, fill=(255, 255, 255), font=font, stroke_width=1, stroke_fill=(255, 255, 255))
    return sheet


def sheet_jpeg(sheet: Image.Image) -> bytes:
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def call_classify_model(jpeg: bytes, event: str, first_t: int, count: int, cfg, client=None) -> list[dict]:
    hcfg = cfg.path("reel.hook_search")
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(jpeg).decode("ascii")}},
               {"type": "text", "text": f"الحدث: {event}\nالثواني المرقّمة في الصفيحة من {first_t} إلى {first_t + count - 1}؛ "
                                        f"أعد نتيجة لكل ثانية."}]
    resp = llm.create(client or _client(), cfg=cfg, model=hcfg.get("model", "haiku"), max_tokens=int(hcfg.get("classify_max_tokens", 900)),
                      system=hcfg.get("classify_system", ""), tools=[CLASSIFY_TOOL],
                      tool_choice={"type": "tool", "name": CLASSIFY_TOOL["name"]},
                      messages=[{"role": "user", "content": content}])
    secs = _tool_input(resp, CLASSIFY_TOOL["name"]).get("seconds")
    if not isinstance(secs, list) or not all(isinstance(s, dict) for s in secs):
        raise ValueError("ردّ غير صالح من مصنِّف الثواني")
    return secs


def good_seconds(results: list[dict]) -> set[int]:
    out = set()
    for r in results:
        try:
            if r.get("kind") == "event_footage" and r.get("relevant") is True:
                out.add(int(r["t"]))
        except (TypeError, ValueError, KeyError):
            continue
    return out


def best_run(good: set[int]) -> tuple[int, int] | None:
    """أطول سلسلة ثوانٍ متتالية (بداية، طول)؛ عند التساوي الأسبق زمنًا."""
    best = None
    for t in sorted(good):
        if t - 1 in good:
            continue
        n = 0
        while t + n in good:
            n += 1
        if best is None or n > best[1]:
            best = (t, n)
    return best


def window(run: tuple[int, int], max_seconds: int) -> tuple[int, int]:
    """النافذة المقصوصة من وسط السلسلة إلى max_seconds."""
    start, n = run
    if n > max_seconds:
        start += (n - max_seconds) // 2
        n = max_seconds
    return start, start + n


# ───────────────────────────── التدفق ─────────────────────────────

def search_hook(draft: dict, script: dict, topic_date: str, cfg, deps, tmp: Path) -> dict:
    """يعيد {queries, candidates, picked, hook_video?, errors}؛ يرفع فقط عند عطل العبارات أو البحث نفسه. عطل مرشّح واحد
    (تنزيل أو تصنيف) يتخطاه إلى التالي ويُعدّ في errors."""
    hcfg = cfg.path("reel.hook_search")
    event = event_text(script, draft)
    queries = deps.make_queries(script, draft, cfg)
    cands = find_candidates(queries, topic_date, cfg, deps)
    out = {"queries": queries, "candidates": [{"video_id": c["video_id"], "channel": c.get("channel", "")} for c in cands],
           "picked": None, "errors": 0}
    sheets_left = int(hcfg.get("max_sheets", 12))
    min_s, cap = int(hcfg.get("min_seconds", 3)), int(cfg.path("reel.render.hook.max_seconds", 7))
    best = None
    for c in cands:
        if sheets_left <= 0:
            break
        try:
            path = tmp / f"hook_scan_{c['video_id']}.mp4"
            deps.scan_download(c["video_id"], int(hcfg.get("scan_seconds", 180)), int(hcfg.get("scan_height", 240)), path)
            frames = deps.scan_frames(path, int(hcfg.get("scan_seconds", 180)), cfg)
            good: set[int] = set()
            per = COLS * ROWS
            for first in range(0, len(frames), per):
                if sheets_left <= 0:
                    break
                chunk = frames[first:first + per]
                sheets_left -= 1
                jpeg = sheet_jpeg(build_sheet(chunk, first, cfg))
                good |= {t for t in good_seconds(deps.classify_sheet(jpeg, event, first, len(chunk), cfg))
                         if first <= t < first + len(chunk)}
        except Exception as exc:  # noqa: BLE001 -- مرشّح معطوب لا يُسقط البقية
            log.warning("تعذّر فحص مرشّح الهوك %s: %s", c.get("video_id"), str(exc)[:150])
            out["errors"] += 1
            continue
        run = best_run(good)
        if run and run[1] >= min_s and (best is None or run[1] > best[1][1]):
            best = (c, run)
            if run[1] >= cap:
                break
    if best:
        c, run = best
        start, end = window(run, cap)
        title = re.sub(r"[\[\]]", "", str(c.get("title", ""))).strip()
        reason = f"{run[1]} ث متتالية من لقطات الحدث"
        out["hook_video"] = {"video_id": c["video_id"], "start": start, "end": end, "channel": c.get("channel", ""),
                             "title": title, "source": "auto", "reason": reason}
        out["picked"] = {"video_id": c["video_id"], "channel": c.get("channel", ""), "start": start, "end": end}
    return out


# ───────────────────────────── التنفيذات الحقيقية لـDeps ─────────────────────────────

def _api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY غائب")
    return key


def real_yt_search(query: str, after: str, before: str, max_results: int) -> list[dict]:
    import requests
    r = requests.get("https://www.googleapis.com/youtube/v3/search", timeout=30, params={
        "part": "snippet", "type": "video", "q": query, "maxResults": max_results, "publishedAfter": after,
        "publishedBefore": before, "key": _api_key()})
    r.raise_for_status()
    return [{"video_id": (i.get("id") or {}).get("videoId"), "channel": (i.get("snippet") or {}).get("channelTitle", ""),
             "title": (i.get("snippet") or {}).get("title", "")} for i in r.json().get("items", [])]


def _iso_seconds(text: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text or "")
    if not m:
        raise ValueError(f"مدة غير مفهومة: {text}")
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def real_yt_durations(ids: list[str]) -> dict[str, int]:
    import requests
    out: dict[str, int] = {}
    for i in range(0, len(ids), 50):
        r = requests.get("https://www.googleapis.com/youtube/v3/videos", timeout=30, params={
            "part": "contentDetails", "id": ",".join(ids[i:i + 50]), "key": _api_key()})
        r.raise_for_status()
        for item in r.json().get("items", []):
            try:
                out[item["id"]] = _iso_seconds(item["contentDetails"]["duration"])
            except (KeyError, ValueError):
                continue
    return out


def real_scan_download(video_id: str, seconds: int, height: int, out_path) -> dict:
    from . import proxy_config, reel_clips
    pc = proxy_config.get_proxy_config()
    return reel_clips.download_clip(video_id, 0, seconds, height, out_path, pc.url if pc else None)


def real_scan_frames(path, seconds: int, cfg) -> list:
    """لقطة كل ثانية بمجلد مؤقت بجوار الملف."""
    import subprocess
    folder = Path(path).parent / (Path(path).stem + "_frames")
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vf", f"fps=1,scale={CELL_W}:{CELL_H}",
                    "-frames:v", str(seconds), str(folder / "%04d.jpg")], capture_output=True, timeout=300, check=True)
    return [Image.open(p).convert("RGB") for p in sorted(folder.glob("*.jpg"))]
