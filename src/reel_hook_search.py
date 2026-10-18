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
from collections import Counter
from dataclasses import dataclass, field
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
        "properties": {"t": {"type": "integer"}, "kind": {"type": "string", "enum": KINDS}, "relevant": {"type": "boolean"},
                       "desc": {"type": "string", "description": "وصف قصير لما يُرى (اختياري، للقطات الحدث)"},
                       # غير مطلوب عمدًا كي لا تنكسر المزيَّفات القديمة؛ غيابه = 0 (P1b)
                       "impact": {"type": "integer", "minimum": 0, "maximum": 3,
                                  "description": "قوة اللقطة لافتتاح الريل: 3 انفجار/نار/اعتراض/اشتباك، 2 دمار/حشود/آليات، 1 ميداني هادئ، 0 غير ذلك"}},
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

def build_sheet(images: list, first_t: int, cfg, labels: list | None = None) -> Image.Image:
    """صفيحة COLS×ROWS: الخانة k عليها رقم ثانيتها first_t+k بخط واضح بأعلى يسارها؛ الخانة بلا لقطة تبقى سوداء بلا رقم.
    labels: أرقام الثواني الفعلية بدل المتتالية (مسح لقطات الحدث بخطوة 2 ث، Issue #1452)."""
    sheet = Image.new("RGB", (COLS * CELL_W, ROWS * CELL_H), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    font = imaging.load_font(None, 44, "Bold")
    for k, img in enumerate(images[:COLS * ROWS]):
        x, y = (k % COLS) * CELL_W, (k // COLS) * CELL_H
        sheet.paste(img.convert("RGB").resize((CELL_W, CELL_H)), (x, y))
        label = str(labels[k] if labels else first_t + k)
        draw.rectangle([x, y, x + 12 + 26 * len(label) + 10, y + 52], fill=(0, 0, 0))
        draw.text((x + 8, y + 4), label, fill=(255, 255, 255), font=font, stroke_width=1, stroke_fill=(255, 255, 255))
    return sheet


def sheet_jpeg(sheet: Image.Image) -> bytes:
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def call_classify_model(jpeg: bytes, event: str, first_t: int, count: int, cfg, client=None,
                        labels: list | None = None) -> list[dict]:
    hcfg = cfg.path("reel.hook_search")
    where = (f"الثواني المرقّمة في الصفيحة: {', '.join(str(x) for x in labels)}" if labels
             else f"الثواني المرقّمة في الصفيحة من {first_t} إلى {first_t + count - 1}")
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(jpeg).decode("ascii")}},
               {"type": "text", "text": f"الحدث: {event}\n{where}؛ أعد نتيجة لكل ثانية مع desc قصير لما يُرى في اللقطة الميدانية."}]
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

@dataclass
class ScanState:
    """حالة المسح الموحَّد (Issue #1452، R5d2): كل مرشّح يُنزَّل ويُصنَّف مرة واحدة في التركيب ويخدم الهوك واللقطات معًا.
    classified[video][t] = {good, desc, step}: step=1 للهوك (كل ثانية) و>1 لعيّنة اللقطات (تغطي t..t+step-1)."""
    frames: dict = field(default_factory=dict)
    classified: dict = field(default_factory=dict)
    failed: set = field(default_factory=set)
    sheets_used: int = 0
    # صفائح كل فيديو (الهوك والجمل معًا) وثواني ما نزل منه: سقف الفيديو الواحد وتقرير الفحص (Issue #1460، R5d4)
    video_sheets: dict = field(default_factory=dict)
    downloaded: dict = field(default_factory=dict)
    # صفائح تعثّرت لكل فيديو وأول رسالة (Issue #1465، R5d6): العطل للصفيحة لا للفيديو، وبلا حفظ سببه لا يُعرف لماذا خرج صفرًا
    sheet_errors: dict = field(default_factory=dict)
    error_text: dict = field(default_factory=dict)

    def note_sheet_error(self, vid: str, exc: Exception) -> None:
        from . import reel_clips
        self.sheet_errors[vid] = self.sheet_errors.get(vid, 0) + 1
        self.error_text.setdefault(vid, reel_clips.scrub_text(str(exc))[:150])


def _is_good(r: dict) -> bool:
    return r.get("kind") == "event_footage" and r.get("relevant") is True


def _entry(r: dict, step: int) -> dict:
    """مدخل الثانية المصنَّفة: good معيار الهوك (ميدانية وrelevant للحدث)، وfootage معيار لقطات الجمل (ميدانية بوصف، relevant أم لا)
    لأن الجملة تطلب مشهدًا بعينه لا الحدث المجرّد، والحَكَم بين السلسلة والجملة هو الإسناد والمدقّق (Issue #1460)."""
    desc = str(r.get("desc") or "").strip()
    try:
        impact = max(0, min(3, int(r.get("impact") or 0)))
    except (TypeError, ValueError):
        impact = 0
    return {"good": _is_good(r), "desc": desc, "step": step, "kind": str(r.get("kind") or ""), "impact": impact,
            "relevant": r.get("relevant") is True, "footage": r.get("kind") == "event_footage" and bool(desc)}


def _load_frames(c: dict, hcfg, cfg, deps, tmp: Path, state: ScanState, seconds: int) -> list:
    """تنزيل المرشّح ولقطاته مرة واحدة لكل فيديو في التركيب كله."""
    vid = c["video_id"]
    if vid not in state.frames:
        path = tmp / f"hook_scan_{vid}.mp4"
        # عطل التنزيل عابر عادة (الفيديو نفسه نزل في تركيبين سابقين): يُعاد التنزيل والاستخراج معًا قبل عدّ الفيديو فاشلًا (Issue #1467)
        attempts = max(int(cfg.path("reel.broll.scan_download_attempts", 3)), 1)
        wait = float(cfg.path("reel.render.retry_wait_seconds", 20))
        sleep = getattr(deps, "sleep", None)
        for n in range(1, attempts + 1):
            try:
                deps.scan_download(vid, seconds, int(hcfg.get("scan_height", 240)), path)
                state.frames[vid] = deps.scan_frames(path, seconds, cfg)
                break
            except Exception as exc:  # noqa: BLE001 -- نحفظ سبب آخر عطل ليظهر في broll_scan
                from . import reel_clips
                state.error_text[vid] = reel_clips.scrub_text(str(exc))[:150]
                if n >= attempts:
                    raise
                log.warning("تعثّر تنزيل فحص %s (محاولة %s من %s): %s", vid, n, attempts, str(exc)[:150])
                if sleep is not None:
                    sleep(wait)
        state.downloaded[vid] = len(state.frames[vid])
    return state.frames[vid]


def scan_candidates(draft: dict, script: dict, cands: list[dict], cfg, deps, tmp: Path, state: ScanState | None = None,
                    want_broll: bool = False) -> dict:
    """يفحص المرشّحين بترتيبهم ويعتمد أول من فيه سلسلة لقطات صالحة. يعيد {hook_video?, errors}؛ عطل مرشّح واحد
    (تنزيل أو تصنيف) يتخطاه إلى التالي ويُعدّ في errors.
    state/want_broll (Issue #1452): تنزيل المرشّح بمدى مسح اللقطات وحفظ لقطاته وتصنيفه في state ليستعملها scan_broll؛
    اختيار الهوك نفسه لا يتغير (أول scan_seconds ثانية وميزانية max_sheets الخاصة به)."""
    hcfg = cfg.path("reel.hook_search")
    state = state if state is not None else ScanState()
    event = event_text(script, draft)
    out: dict = {"errors": 0}
    sheets_left = int(hcfg.get("max_sheets", 12))
    hook_secs = int(hcfg.get("scan_seconds", 180))
    dl_secs = max(hook_secs, int(cfg.path("reel.broll.scan_seconds", 600))) if want_broll else hook_secs
    for c in cands:
        if sheets_left <= 0:
            break
        vid = c["video_id"]
        try:
            frames = _load_frames(c, hcfg, cfg, deps, tmp, state, dl_secs)
            if want_broll:
                frames = frames[:hook_secs]
            good: set[int] = set()
            known = state.classified.setdefault(vid, {})
            per = COLS * ROWS
            tried = bad = 0
            for first in range(0, len(frames), per):
                if sheets_left <= 0:
                    break
                chunk = frames[first:first + per]
                sheets_left -= 1
                state.sheets_used += 1
                state.video_sheets[vid] = state.video_sheets.get(vid, 0) + 1
                tried += 1
                try:
                    jpeg = sheet_jpeg(build_sheet(chunk, first, cfg))
                    results = deps.classify_sheet(jpeg, event, first, len(chunk), cfg)
                    got = {t for t in good_seconds(results) if first <= t < first + len(chunk)}
                    parsed: dict[int, dict] = {}
                    for r in results:
                        try:
                            t = int(r["t"])
                        except (TypeError, ValueError, KeyError):
                            continue
                        if first <= t < first + len(chunk):
                            parsed[t] = _entry(r, 1)
                except Exception as exc:  # noqa: BLE001 -- صفيحة متعثرة تُتخطّى وما صُنّف حولها يبقى (Issue #1465)
                    log.warning("تعثّرت صفيحة %s من %s: %s", first, vid, str(exc)[:150])
                    state.note_sheet_error(vid, exc)
                    bad += 1
                    continue
                good |= got
                known.update(parsed)
            if tried and bad == tried:
                raise RuntimeError(f"فشلت كل الصفائح: {state.error_text.get(vid, '')}")
        except Exception as exc:  # noqa: BLE001 -- مرشّح معطوب لا يُسقط البقية
            log.warning("تعذّر فحص مرشّح الهوك %s: %s", c.get("video_id"), str(exc)[:150])
            out["errors"] += 1
            state.failed.add(vid)
            continue
        win = pick_hook_window({t: e for t, e in known.items() if e.get("step") == 1}, cfg)
        if win:
            title = re.sub(r"[\[\]]", "", clean_title(c.get("title", ""))).strip()
            reason = cfg.path("reel.render.texts.hook_reason").format(seconds=int(cfg.path("reel.render.hook.strong_seconds", 3)),
                                                                      impact=win["impact"])
            out["hook_video"] = {"video_id": c["video_id"], "start": win["start"], "end": win["end"], "channel": c.get("channel", ""),
                                 "title": title, "source": "auto", "views": int(c.get("views") or 0),
                                 "impact": win["impact"], "pre_ok": win["pre_ok"], "strong_start": win["start"], "reason": reason}
            break  # الأعلى مشاهدة أولًا: لا مقارنة بين المرشّحين
    return out


def pick_hook_window(entries: dict, cfg) -> dict | None:
    """نافذة الهوك (P1b): أقوى strong_seconds ثانية متتالية صالحة لا وسط أطول سلسلة، لأن هذه الثواني تُعرض نظيفة أولًا.
    entries = {الثانية: مدخل _entry} لمرشّح واحد. الدرجة = مجموع impact (غيابه 0)؛ المرشّحة ما بلغ الأعلى − impact_slack، ويُقدَّم
    فيها ما بدايته ≥ pre_seconds (قبله لقطات تكفي لخلفية الختام) ثم الأعلى ثم الأسبق. بلا سلسلة ≥ min_seconds ← None."""
    hcfg = cfg.path("reel.hook_search")
    min_s = int(hcfg.get("min_seconds", 3))
    size = max(int(cfg.path("reel.render.hook.strong_seconds", 3)), 1)
    cap = int(cfg.path("reel.render.hook.max_seconds", 7))
    slack, pre = int(hcfg.get("impact_slack", 1)), int(hcfg.get("pre_seconds", 10))
    good = sorted(t for t, e in entries.items() if e.get("good"))
    wins: list[tuple[int, int, int]] = []  # (بداية، درجة، نهاية السلسلة + 1)
    i = 0
    while i < len(good):
        j = i
        while j + 1 < len(good) and good[j + 1] == good[j] + 1:
            j += 1
        a, b = good[i], good[j]
        n = b - a + 1
        if n >= min_s:
            w = min(size, n)
            for s in range(a, b - w + 2):
                wins.append((s, sum(int(entries[t].get("impact") or 0) for t in range(s, s + w)), b + 1))
        i = j + 1
    if not wins:
        return None
    best = max(w[1] for w in wins)
    s, score, run_end = min((w for w in wins if w[1] >= best - slack), key=lambda w: (w[0] < pre, -w[1], w[0]))
    return {"start": s, "end": min(run_end, s + cap), "impact": score, "pre_ok": s >= pre}


def _chains_of(c: dict, known: dict, hook: dict | None, min_s: int) -> list[dict]:
    """سلاسل الثواني الصالحة المتتالية للمرشّح [{video_id,start,end,desc,channel}] بعد استبعاد نافذة الهوك وما دون min_s ثوانٍ."""
    secs: dict[int, tuple[str, bool]] = {}
    for t, r in known.items():
        if not r.get("footage"):
            continue
        for u in range(t, t + max(int(r.get("step", 1)), 1)):
            # ثانية صنِّفت بمفردها (الهوك) غير ميدانية لا تُرثها عيّنة أوسع
            if u != t and (u in known and not known[u].get("footage")):
                continue
            secs.setdefault(u, (r.get("desc", ""), bool(r.get("relevant"))))
    if hook and hook.get("video_id") == c["video_id"]:
        for u in range(int(hook.get("start", 0)), int(hook.get("end", 0))):
            secs.pop(u, None)
    out: list[dict] = []
    run: list[int] = []

    def flush():
        if len(run) >= min_s:
            # حتى 3 أوصاف مختلفة بترتيبها الزمني: سلسلة 68 ث بوصف أول ثانية وحده تبدو للإسناد مشهدًا واحدًا (Issue #1462)
            descs = list(dict.fromkeys(secs[u][0] for u in run if secs[u][0]))[:3]
            out.append({"video_id": c["video_id"], "start": run[0], "end": run[-1] + 1,
                        "desc": " · ".join(descs) if descs else clean_title(c.get("title", "")),
                        "channel": c.get("channel", ""), "relevant": all(secs[u][1] for u in run)})
    for u in sorted(secs):
        if run and u != run[-1] + 1:
            flush()
            run = []
        run.append(u)
    if run:
        flush()
    return out


def topic_hook(chains: list[dict], cands: list[dict], cfg, deps=None, script: dict | None = None,
               draft: dict | None = None) -> tuple[dict | None, list[dict], list]:
    """هوك احتياطي من لقطات الموضوع (Issue #1462، R5d5؛ بالمعنى لا بالطول منذ Issue #1465، R5d6): الأطول كان ضبابًا لا معنى له تحت
    العنوان، فيُسأل deps.assign_broll بمدخل واحد {n: 0, dur: hook.max_seconds, text: عنوان السيناريو, visual: وصف الحدث} على السلاسل
    بطول ≥ hook.min_seconds. أُسندت سلسلة ← الهوك منها بنافذة من وسطها لا تتجاوز hook.max_seconds وsource = "auto_topic"؛ لم تُسند
    ← لا هوك احتياطي. يعيد (hook_video أو None، السلاسل بعد إزالة نافذته، الردّ الخام للحفظ)."""
    min_h = float(cfg.path("reel.render.hook.min_seconds", 3.5))
    cap = int(cfg.path("reel.render.hook.max_seconds", 7))
    long_ones = [c for c in chains if c["end"] - c["start"] >= min_h]
    if not long_ones or deps is None or getattr(deps, "assign_broll", None) is None:
        return None, list(chains), []
    script, draft = script or {}, draft or {}
    item = {"n": 0, "dur": cap, "text": str(script.get("title") or draft.get("title") or ""), "visual": event_text(script, draft)}
    try:
        raw = deps.assign_broll([item], long_ones, cfg) or []
    except Exception as exc:  # noqa: BLE001 -- الهوك الاحتياطي تحسين: يبقى الهوك بصورة الخبر
        log.warning("تعذّر إسناد الهوك الاحتياطي: %s", str(exc)[:150])
        return None, list(chains), []
    pick = None
    for r in raw:
        try:
            if int(r["n"]) == 0 and 1 <= int(r["chain"]) <= len(long_ones):
                pick = long_ones[int(r["chain"]) - 1]
                break
        except (TypeError, ValueError, KeyError):
            continue
    if pick is None:
        return None, list(chains), raw
    best = pick
    start, end = window((int(best["start"]), int(best["end"]) - int(best["start"])), cap)
    meta = next((c for c in cands if c.get("video_id") == best["video_id"]), {})
    title = re.sub(r"[\[\]]", "", clean_title(meta.get("title", ""))).strip()
    hook = {"video_id": best["video_id"], "start": start, "end": end, "channel": best.get("channel") or meta.get("channel", ""),
            "title": title, "source": "auto_topic", "views": int(meta.get("views") or 0),
            "reason": "لقطات ميدانية عن الموضوع بلا لقطة للحدث نفسه"}
    min_s = int(cfg.path("reel.broll.min_seconds", 3))
    rest: list[dict] = []
    for c in chains:
        if c["video_id"] != best["video_id"] or c["end"] <= start or c["start"] >= end:
            rest.append(c)
            continue
        for a, b in ((c["start"], start), (end, c["end"])):
            if b - a >= min_s:
                rest.append({**c, "start": a, "end": b})
    return hook, rest, raw


def scan_report(state: ScanState, cands: list[dict], chains: list[dict], bcfg) -> dict:
    """ما رآه الفحص لكل مرشّح (يُحفظ draft["broll_scan"]): بلا هذا لا يُعرف لماذا خرج المسح صفرًا (Issue #1460)."""
    videos: dict = {}
    for c in cands:
        vid = c["video_id"]
        known = state.classified.get(vid) or {}
        if vid not in state.downloaded and vid not in state.failed and not known:
            continue
        kinds: Counter = Counter()
        rel = other = 0
        for r in known.values():
            w = max(int(r.get("step", 1)), 1)
            kinds[r.get("kind") or "unknown"] += w
            if r.get("kind") == "event_footage":
                if r.get("relevant"):
                    rel += w
                else:
                    other += w
        mine = [x for x in chains if x["video_id"] == vid]
        videos[vid] = {"downloaded": state.downloaded.get(vid, 0), "classified": sum(kinds.values()),
                       "sheets": state.video_sheets.get(vid, 0), "kinds": dict(kinds), "footage_relevant": rel,
                       "footage_other": other, "chains": len(mine),
                       "longest": max((x["end"] - x["start"] for x in mine), default=0),
                       **({"sheet_errors": state.sheet_errors[vid]} if state.sheet_errors.get(vid) else {}),
                       **({"error_text": state.error_text[vid]}
                          if state.error_text.get(vid) and (state.sheet_errors.get(vid) or vid in state.failed) else {}),
                       **({"error": True} if vid in state.failed else {})}
    return {"videos": videos, "sheets_used": state.sheets_used}


def scan_broll(draft: dict, script: dict, cands: list[dict], cfg, deps, tmp: Path, state: ScanState,
               hook: dict | None = None) -> dict:
    """مسح اللقطات (Issue #1452، R5d2): كل مرشّح بمداه الكامل broll.scan_seconds وخطوة broll.step، ضمن ميزانية broll.max_sheets
    صفيحة لكل التركيب (ما صرفه الهوك محسوب). لا يُنزَّل مرشّح نزل أو فشل سابقًا. يعيد {chains, errors}؛ السلاسل تستبعد نافذة الهوك."""
    bcfg = cfg.path("reel.broll")
    hcfg = cfg.path("reel.hook_search")
    event = event_text(script, draft)
    scan_s, step = int(bcfg.get("scan_seconds", 600)), max(int(bcfg.get("step", 2)), 1)
    min_s = int(bcfg.get("min_seconds", 3))
    budget = int(bcfg.get("max_sheets", 30)) - state.sheets_used
    video_cap = int(bcfg.get("max_sheets_per_video", 15))
    per = COLS * ROWS
    chains: list[dict] = []
    errors = 0
    for c in cands:
        vid = c["video_id"]
        if vid in state.failed:
            continue
        known = state.classified.setdefault(vid, {})
        room = min(budget, video_cap - state.video_sheets.get(vid, 0))
        if room <= 0 and not known:
            continue
        try:
            if room > 0:
                frames = _load_frames(c, hcfg, cfg, deps, tmp, state, scan_s)
                labels = [t for t in range(0, min(len(frames), scan_s), step) if t not in known]
                tried = bad = 0
                for i in range(0, len(labels), per):
                    if room <= 0:
                        break
                    chunk = labels[i:i + per]
                    room -= 1
                    budget -= 1
                    state.sheets_used += 1
                    state.video_sheets[vid] = state.video_sheets.get(vid, 0) + 1
                    tried += 1
                    try:
                        jpeg = sheet_jpeg(build_sheet([frames[t] for t in chunk], chunk[0], cfg, labels=chunk))
                        results = deps.classify_sheet(jpeg, event, chunk[0], len(chunk), cfg, labels=chunk)
                        by_t = {}
                        for r in results or []:
                            try:
                                by_t[int(r["t"])] = r
                            except (TypeError, ValueError, KeyError):
                                continue
                    except Exception as exc:  # noqa: BLE001 -- صفيحة متعثرة تُتخطّى وما صُنّف حولها يبقى (Issue #1465)
                        log.warning("تعثّرت صفيحة %s من %s: %s", chunk[0], vid, str(exc)[:150])
                        state.note_sheet_error(vid, exc)
                        bad += 1
                        continue
                    for t in chunk:
                        if t in by_t:
                            known[t] = _entry(by_t[t], step)
                if tried and bad == tried:
                    raise RuntimeError(f"فشلت كل الصفائح: {state.error_text.get(vid, '')}")
        except Exception as exc:  # noqa: BLE001 -- مرشّح معطوب لا يُسقط البقية
            log.warning("تعذّر مسح لقطات المرشّح %s: %s", vid, str(exc)[:150])
            errors += 1
            state.failed.add(vid)
            state.frames.pop(vid, None)
            continue
        state.frames.pop(vid, None)    # الذاكرة: لقطات المرشّح لا تُحتاج بعد تصنيفه
        chains.extend(_chains_of(c, known, hook, min_s))
    return {"chains": chains, "errors": errors, "scan": scan_report(state, cands, chains, bcfg)}


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
