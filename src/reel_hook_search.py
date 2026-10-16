"""بحث آلي عن لقطة فيديو من الحدث نفسه لخلفية الهوك (Issue #1440، R5c2؛ Issue #1445، R5c3).

مرحلتان: (١) في السيناريو `pick_hook_candidates`: عبارات من Haiku ← بحث يوتيوب (short ثم medium) ← فلاتر القناة والمدة وحكم العناوين ←
الأكثر مشاهدة أولًا تُحفظ مرشّحات على المسودة وتُعرض في قضية المراجعة؛ (٢) في التركيب `scan_candidates`: تنزيل أول ثوانٍ من كل
مرشّح ← صفائح 4×3 بالثواني مرقّمة يصنّفها Haiku بالصور ← أطول سلسلة ثوانٍ كلها لقطات من الحدث نفسه، وأول مرشّح فيه سلسلة صالحة يُعتمد. كل شبكة وملف وفحص عبر Deps كي تُزيَّف، وهذه الوحدة لا تستورد
reel_render (تستورده هي) فلا حلقة استيراد. لا يُرفع منها فشل إلى التركيب: المستدعي يلتقط ويُبقي الهوك بصورة الخبر."""
from __future__ import annotations

import base64
import html
import io
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

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

JUDGE_TOOL = {
    "name": "judge_titles",
    "description": "حكم على كل عنوان فيديو: عن الحدث نفسه؟ ولقطات منه أم نقاش وتحليل؟",
    "input_schema": {"type": "object", "properties": {"judgments": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "relevant": {"type": "boolean"}, "footage": {"type": "boolean"}},
        "required": ["id", "relevant", "footage"]}}}, "required": ["judgments"]},
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


def call_judge_titles(items: list[dict], event: str, cfg, client=None) -> dict:
    """نداء Haiku واحد على عناوين الباقين وقنواتهم ← {id: {relevant, footage}}؛ عنوان لم يُحكم عليه يُعدّ مرفوضًا."""
    hcfg = cfg.path("reel.hook_search")
    listing = "\n".join(f"{i['video_id']} | {i.get('channel', '')} | {i.get('title', '')}" for i in items)
    resp = llm.create(client or _client(), cfg=cfg, model=hcfg.get("model", "haiku"), max_tokens=int(hcfg.get("judge_max_tokens", 1200)),
                      system=hcfg.get("judge_system", ""), tools=[JUDGE_TOOL],
                      tool_choice={"type": "tool", "name": JUDGE_TOOL["name"]},
                      messages=[{"role": "user", "content": f"الحدث: {event}\nالعناوين (المعرّف | القناة | العنوان):\n{listing}"}])
    rows = _tool_input(resp, JUDGE_TOOL["name"]).get("judgments")
    if not isinstance(rows, list):
        raise ValueError("ردّ غير صالح من حاكم العناوين")
    return {str(r.get("id")): {"relevant": r.get("relevant") is True, "footage": r.get("footage") is True}
            for r in rows if isinstance(r, dict)}


def call_make_queries(script: dict, draft: dict, cfg, client=None, broad: bool = False) -> list[str]:
    """broad: المحاولة الثانية — عبارات أعمّ (الحدث ومكانه دون تفاصيل بصرية) بتعليمتها الخاصة."""
    hcfg = cfg.path("reel.hook_search")
    resp = llm.create(client or _client(), cfg=cfg, model=hcfg.get("model", "haiku"), max_tokens=int(hcfg.get("queries_max_tokens", 400)),
                      system=hcfg.get("queries_system_broad" if broad else "queries_system", ""), tools=[MAKE_QUERIES_TOOL],
                      tool_choice={"type": "tool", "name": MAKE_QUERIES_TOOL["name"]},
                      messages=[{"role": "user", "content": "الحدث: " + event_text(script, draft)}])
    qs = _tool_input(resp, MAKE_QUERIES_TOOL["name"]).get("queries")
    out = [" ".join(str(q).split()) for q in qs or [] if str(q).strip()]
    if not out:
        raise ValueError("لا عبارات بحث")
    return out[:3]


# ───────────────────────────── البحث ─────────────────────────────

@dataclass
class HookDeps:
    """كل ما يلمس الشبكة في مرحلة السيناريو؛ الحقل الفارغ يُملأ بالحقيقي في `resolved` والاختبارات تحقن مزيَّفات.
    yt_search(عبارة، بعد، قبل، العدد، المدة) ← [{video_id, channel, title, published}]؛ yt_details(معرّفات) ← {id: {duration, views}}؛
    make_queries(سيناريو، مسودة، cfg، broad) ← عبارات؛ judge_titles(عناصر، الحدث، cfg) ← {id: {relevant, footage}}."""
    yt_search: Callable[..., list] | None = None
    yt_details: Callable[[list], dict] | None = None
    make_queries: Callable[..., list] | None = None
    judge_titles: Callable[..., dict] | None = None

    def resolved(self) -> "HookDeps":
        return HookDeps(
            yt_search=self.yt_search or real_yt_search,
            yt_details=self.yt_details or real_yt_details,
            make_queries=self.make_queries or (
                lambda script, draft, cfg, broad=False: call_make_queries(script, draft, cfg, broad=broad)),
            judge_titles=self.judge_titles or (lambda items, event, cfg: call_judge_titles(items, event, cfg)))


def search_window(topic_date: str, days_before: int, days_after: int) -> tuple[str, str]:
    d = date.fromisoformat(str(topic_date)[:10])
    return (f"{(d - timedelta(days=days_before)).isoformat()}T00:00:00Z",
            f"{(d + timedelta(days=days_after)).isoformat()}T00:00:00Z")


def clean_title(title) -> str:
    """عنوان يوتيوب يصل من الواجهة مرمَّزًا بـHTML («&amp;» «&#39;»): يُفك قبل أن يُحفظ أو يُعرض (Issue #1447)."""
    return html.unescape(str(title or ""))


def channel_allowed(channel: str, hcfg) -> bool:
    low = (channel or "").casefold()
    return any(str(n).casefold() in low for n in hcfg.get("channels", []) if str(n).strip())


def _attempt(draft: dict, script: dict, topic_date: str, cfg, deps: HookDeps, broad: bool, budget: list) -> tuple[list[dict], dict]:
    """محاولة بحث واحدة ← (مرشّحون مرتّبون بالمشاهدات، تشخيصها). budget[0] = ما بقي من طلبات search.list للمحاولتين معًا."""
    hcfg = cfg.path("reel.hook_search")
    # المحاولة الثانية أوسع نافذةً لأن الحدث قد يُغطّى قبله أو بعده بأيام أكثر مما قدّرنا
    days = ((int(hcfg.get("retry_days_before", 4)), int(hcfg.get("retry_days_after", 3))) if broad
            else (int(hcfg.get("days_before", 2)), int(hcfg.get("days_after", 2))))
    after, before = search_window(topic_date, *days)
    queries = deps.make_queries(script, draft, cfg, broad)
    diag: dict = {"broad": broad, "window": [after, before], "queries": [], "duration_ok": 0, "judged_ok": 0,
                  "rejected_channels": []}
    seen: dict[str, dict] = {}
    rejected: list[str] = []
    for q in queries:
        raw = ok = 0
        for duration in hcfg.get("durations", ["short", "medium"]):
            if budget[0] <= 0:
                break
            budget[0] -= 1
            for r in deps.yt_search(q, after, before, int(hcfg.get("search_results", 15)), duration) or []:
                raw += 1
                if channel_allowed(r.get("channel", ""), hcfg):
                    ok += 1
                    if r.get("video_id") and r["video_id"] not in seen:
                        seen[r["video_id"]] = r
                else:
                    name = str(r.get("channel", "")).strip()
                    if name and name not in rejected:
                        rejected.append(name)
        diag["queries"].append({"query": q, "raw": raw, "channel_ok": ok})
    diag["rejected_channels"] = rejected[:8]
    if not seen:
        return [], diag
    details = deps.yt_details(list(seen)) or {}
    limit = float(hcfg.get("max_video_seconds", 1200))
    short = []
    for vid, r in seen.items():
        info = details.get(vid) or {}
        if info.get("duration") is not None and float(info["duration"]) <= limit:
            short.append({"video_id": vid, "title": clean_title(r.get("title", "")), "channel": r.get("channel", ""),
                          "views": int(info.get("views") or 0), "duration": int(info["duration"]),
                          "published": r.get("published", "")})
    diag["duration_ok"] = len(short)
    if not short:
        return [], diag
    verdicts = deps.judge_titles([{"video_id": c["video_id"], "title": c["title"], "channel": c["channel"]} for c in short],
                                 event_text(script, draft), cfg) or {}
    judged = [c for c in short if (verdicts.get(c["video_id"]) or {}).get("relevant") is True
              and (verdicts.get(c["video_id"]) or {}).get("footage") is True]
    diag["judged_ok"] = len(judged)
    judged.sort(key=lambda c: c["views"], reverse=True)
    return judged[:int(hcfg.get("max_candidates", 4))], diag


def pick_hook_candidates(draft: dict, cfg, deps: HookDeps | None = None) -> None:
    """يحفظ على المسودة hook_candidates وhook_search (Issue #1445). بلا YOUTUBE_API_KEY ← skipped بلا أي نداء. محاولة ثانية واحدة
    بعبارات أعمّ ونافذة أوسع حين لا مرشّح، ولا ثالثة. أي عطل يُسجَّل في hook_search["error"] ولا يُرفع: السيناريو الصالح لا يسقط."""
    if not os.environ.get("YOUTUBE_API_KEY", "").strip():
        draft.pop("hook_candidates", None)
        draft["hook_search"] = {"skipped": "no_key"}
        return
    hcfg = cfg.path("reel.hook_search")
    deps = (deps or HookDeps()).resolved()
    script = draft.get("script") or {}
    topic_date = draft.get("topic_date") or str(draft.get("date") or "")[:10] or date.today().isoformat()
    budget = [int(hcfg.get("max_search_calls", 12))]
    attempts: list[dict] = []
    cands: list[dict] = []
    search: dict = {"attempts": attempts}
    try:
        for broad in (False, True):
            cands, diag = _attempt(draft, script, topic_date, cfg, deps, broad, budget)
            attempts.append(diag)
            if cands:
                break
    except Exception as exc:  # noqa: BLE001 -- لقطة الهوك تحسين: لا تُسقط سيناريو صالحًا
        from . import reel_clips
        search["error"] = reel_clips.scrub_text(str(exc))[:150]
        log.warning("تعذّر البحث عن مرشّحي لقطة الهوك: %s", search["error"])
        cands = []
    search["picked"] = [c["video_id"] for c in cands]
    draft["hook_candidates"] = cands
    draft["hook_search"] = search


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


# ───────────────────────────── الفحص البصري (التركيب) ─────────────────────────────

def scan_candidates(draft: dict, script: dict, cands: list[dict], cfg, deps, tmp: Path) -> dict:
    """يفحص المرشّحين بترتيبهم ويعتمد أول من فيه سلسلة لقطات صالحة. يعيد {hook_video?, errors}؛ عطل مرشّح واحد
    (تنزيل أو تصنيف) يتخطاه إلى التالي ويُعدّ في errors."""
    hcfg = cfg.path("reel.hook_search")
    event = event_text(script, draft)
    out: dict = {"errors": 0}
    sheets_left = int(hcfg.get("max_sheets", 12))
    min_s, cap = int(hcfg.get("min_seconds", 3)), int(cfg.path("reel.render.hook.max_seconds", 7))
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
        if run and run[1] >= min_s:
            start, end = window(run, cap)
            title = re.sub(r"[\[\]]", "", clean_title(c.get("title", ""))).strip()
            out["hook_video"] = {"video_id": c["video_id"], "start": start, "end": end, "channel": c.get("channel", ""),
                                 "title": title, "source": "auto", "views": int(c.get("views") or 0),
                                 "reason": f"{run[1]} ث متتالية من لقطات الحدث"}
            break  # الأعلى مشاهدة أولًا: لا مقارنة بين المرشّحين
    return out


# ───────────────────────────── التنفيذات الحقيقية لـDeps ─────────────────────────────

def _api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY غائب")
    return key


def real_yt_search(query: str, after: str, before: str, max_results: int, duration: str | None = None) -> list[dict]:
    import requests
    params = {"part": "snippet", "type": "video", "q": query, "maxResults": max_results, "publishedAfter": after,
              "publishedBefore": before, "key": _api_key()}
    if duration:
        params["videoDuration"] = duration
    r = requests.get("https://www.googleapis.com/youtube/v3/search", timeout=30, params=params)
    r.raise_for_status()
    return [{"video_id": (i.get("id") or {}).get("videoId"), "channel": (i.get("snippet") or {}).get("channelTitle", ""),
             "title": clean_title((i.get("snippet") or {}).get("title", "")), "published": (i.get("snippet") or {}).get("publishedAt", "")}
            for i in r.json().get("items", [])]


def _iso_seconds(text: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text or "")
    if not m:
        raise ValueError(f"مدة غير مفهومة: {text}")
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def real_yt_details(ids: list[str]) -> dict[str, dict]:
    """videos.list بـpart=contentDetails,statistics ← {id: {duration, views}}."""
    import requests
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 50):
        r = requests.get("https://www.googleapis.com/youtube/v3/videos", timeout=30, params={
            "part": "contentDetails,statistics", "id": ",".join(ids[i:i + 50]), "key": _api_key()})
        r.raise_for_status()
        for item in r.json().get("items", []):
            try:
                out[item["id"]] = {"duration": _iso_seconds(item["contentDetails"]["duration"]),
                                   "views": int((item.get("statistics") or {}).get("viewCount") or 0)}
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
