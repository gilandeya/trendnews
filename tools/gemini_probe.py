"""أداة قياس: هل يسمّي Gemini متحدثي الحلقة ويوقّت كلامهم ويترجمه من رابط يوتيوب مباشرة أصحّ وأرخص من سلسلتنا الحالية
(نص يوتيوب بالبروكسي ← استخراج المقاطع ← شريط الاسم وقائمة الضيوف وخريطة الوجوه وwhisper)؟ قياس فقط: لا يستدعيها شيء في src/،
ولا مسودة ولا قضية ولا render_version.

التشغيل (في الـworkflow، بمفتاح GEMINI_API_KEY ومستودع البيانات الخاص مسحوبًا):
    python tools/gemini_probe.py                      # الفيديوهات الافتراضية في config.yaml: gemini_probe.videos
    python tools/gemini_probe.py --video ID --video ID --model gemini-2.5-flash

ثلاث مقارنات لكل فيديو:
  1) الحقيقة المعروفة (KNOWN في speaker_map_probe، منها خلط البخيتي/الحربي): من يتكلم في تلك الثانية عند Gemini؟
  2) المقاطع المحفوظة (youtube_bites): هل يسمّي Gemini قائل المقطع نفسه الذي سمّاه استخراجنا؟ (الخلاف يُطبع للمراجعة، لا حكم آلي بمن أصاب)
  3) التوقيت: بداية مقطع Gemini مقابل موضع أول كلماته في نص يوتيوب المحفوظ (بدقة سطر النص، نحو 3–5 ث).

المخرجات:
  - youtube-data/gemini_probe/<التاريخ>/<video_id>.json — ردّ Gemini كاملًا والمقارنات بالأسماء (المستودع الخاص وحده: فيه كلام القنوات).
  - state/gemini_probe/<التاريخ>.json — أرقام فقط بلا نص ولا أسماء (هذا المستودع عام).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import gemini  # noqa: E402
from src.gemini import parse_clock  # noqa: E402,F401 — يقرؤها الاختبار من هذه الوحدة

API = gemini.API

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "speakers": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "name_ar": {"type": "STRING"}, "name_original": {"type": "STRING"}, "role": {"type": "STRING"},
            "is_host": {"type": "BOOLEAN"},
            "name_source": {"type": "STRING", "enum": ["chyron", "introduced", "addressed", "unknown"]},
            "appearance": {"type": "STRING"}},
            "required": ["name_ar", "is_host", "name_source"]}},
        "segments": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "start": {"type": "STRING"}, "end": {"type": "STRING"}, "speaker": {"type": "STRING"},
            "first_words": {"type": "STRING"}, "last_words": {"type": "STRING"}, "text_ar": {"type": "STRING"},
            "on_screen": {"type": "STRING"}},
            "required": ["start", "end", "speaker", "first_words", "text_ar"]}},
    },
    "required": ["speakers", "segments"],
}


def build_request(video_id: str, cfg, duration: float | None = None) -> dict:
    """جسم generateContent: الرابط وحده (Google تجلب الفيديو، فلا بروكسي)، ومخطط JSON للرد، والدقة المنخفضة. بلا temperature عمدًا
    (قاعدة المشروع لكل النماذج). الحلقة الأطول من max_minutes تُقصّ بـendOffset فلا يُدفع ثمن ما لا نقيسه."""
    gp = cfg.path("gemini_probe", {}) or {}
    part = {"file_data": {"file_uri": f"https://www.youtube.com/watch?v={video_id}"}}
    cap = float(gp.get("max_minutes") or 0) * 60
    if cap and (duration is None or duration > cap):
        part["video_metadata"] = {"end_offset": f"{int(cap)}s"}
    return {
        "system_instruction": {"parts": [{"text": gp.get("system", "")}]},
        "contents": [{"role": "user", "parts": [part, {"text": "فرّغ هذه الحلقة بحسب التعليمات."}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA,
                             "mediaResolution": gp.get("media_resolution", "MEDIA_RESOLUTION_LOW"),
                             "maxOutputTokens": int(gp.get("max_output_tokens") or 65536)},
    }


def read_response(resp: dict) -> tuple[dict | None, str, dict]:
    return gemini.read_response(resp, "segments")


def cost_usd(usage: dict, cfg) -> float:
    return gemini.cost_usd(usage, cfg.path("gemini_probe.price_per_mtok", {}) or {})


def speaker_record(data: dict, name: str) -> dict:
    for s in data.get("speakers") or []:
        if s.get("name_ar") == name:
            return s
    return {}


def segment_at(segments: list[dict], second: float, duration: float | None = None) -> dict | None:
    for s in segments:
        a, b = parse_clock(s.get("start"), duration), parse_clock(s.get("end"), duration)
        if a is not None and b is not None and a <= second <= b:
            return s
    return None


def best_overlap(segments: list[dict], start: float, end: float, min_share: float,
                 duration: float | None = None) -> dict | None:
    """مقطع Gemini الذي يغطي أكبر جزء من [start, end]، إن بلغت تغطيته min_share من طوله؛ وإلا None (لا مقارنة بمقطع لا يقابله)."""
    best, best_cover = None, 0.0
    length = max(end - start, 1e-6)
    for s in segments:
        a, b = parse_clock(s.get("start"), duration), parse_clock(s.get("end"), duration)
        if a is None or b is None:
            continue
        cover = max(0.0, min(b, end) - max(a, start))
        if cover > best_cover:
            best, best_cover = s, cover
    return best if best_cover / length >= min_share else None


def names_agree(gemini: dict, segment: dict | None, expected: str, cfg) -> bool | None:
    """القاعدة نفسها التي تحكم بها حرّاس الريل (reel_render.speaker_matches): كلمة اسم مشتركة، والاسم الأول وحده لا يكفي."""
    from src import reel_render
    if not segment or not expected:
        return None
    name = segment.get("speaker") or ""
    rec = speaker_record(gemini, name)
    return reel_render.speaker_matches(name, rec.get("name_original", ""), expected, cfg)


def timing_drifts(segments: list[dict], transcript: dict | None, cfg) -> list[float]:
    """فرق بداية مقطع Gemini عن موضع أول كلماته في نص يوتيوب المحفوظ (بالمطابقة نفسها التي توقّت بها نقاطنا). ما لا يُعثر عليه
    حرفيًا يُهمل: نص يوتيوب التركي المحفوظ ترجمة إنجليزية فلا مطابقة له، وهذا بحد ذاته رقم يُقرأ (located من segments)."""
    from src import youtube_extract
    if not transcript:
        return []
    lines = [(int(float(s.get("start") or 0)), s.get("text", "")) for s in transcript.get("segments") or []]
    drifts = []
    duration = transcript.get("duration_seconds")
    for s in segments:
        start = parse_clock(s.get("start"), duration)
        if start is None or not s.get("first_words"):
            continue
        ts, _method = youtube_extract.resolve_timestamp(s["first_words"], lines, "", cfg)
        if ts is not None:
            drifts.append(round(start - ts, 1))
    return drifts


def saved_bites(video_id: str) -> list[dict]:
    from src import youtube_transcripts
    out = []
    for path in sorted(youtube_transcripts.bites_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out += [b for b in (data.get("bites") or []) if isinstance(b, dict) and b.get("video_id") == video_id]
    return out


def compare(video_id: str, gemini: dict, cfg, known, bites: list[dict], transcript: dict | None) -> tuple[dict, dict]:
    """(أرقام عامة، تفاصيل خاصة بالأسماء)."""
    segs = gemini.get("segments") or []
    speakers = gemini.get("speakers") or []
    min_share = float(cfg.path("gemini_probe.overlap_min", 0.5))
    duration = (transcript or {}).get("duration_seconds")
    known_rows = []
    for vid, second, expected in known:
        if vid != video_id:
            continue
        if second == "host":
            host = next((s for s in speakers if s.get("is_host")), {})
            seg = {"speaker": host.get("name_ar", "")} if host else None
        else:
            seg = segment_at(segs, float(second), duration)
        known_rows.append({"second": second, "expected": expected, "gemini": (seg or {}).get("speaker", ""),
                           "agree": names_agree(gemini, seg, expected or "", cfg)})
    bite_rows = []
    for b in bites:
        if not b.get("speaker") or b.get("start") is None or b.get("end") is None:
            continue
        seg = best_overlap(segs, float(b["start"]), float(b["end"]), min_share, duration)
        bite_rows.append({"start": b["start"], "ours": b["speaker"], "gemini": (seg or {}).get("speaker", ""),
                          "agree": names_agree(gemini, seg, b["speaker"], cfg)})
    drifts = timing_drifts(segs, transcript, cfg)
    absd = sorted(abs(d) for d in drifts)
    sources = {}
    for s in speakers:
        sources[s.get("name_source") or "?"] = sources.get(s.get("name_source") or "?", 0) + 1
    numbers = {
        "segments": len(segs), "speakers": len(speakers),
        "named_speakers": sum(1 for s in speakers if (s.get("name_ar") or "").strip() and s.get("name_source") != "unknown"),
        "name_sources": sources,
        "known": {"checked": len(known_rows), "agree": sum(1 for r in known_rows if r["agree"] is True),
                  "disagree": sum(1 for r in known_rows if r["agree"] is False)},
        "bites": {"compared": sum(1 for r in bite_rows if r["agree"] is not None),
                  "agree": sum(1 for r in bite_rows if r["agree"] is True),
                  "disagree": sum(1 for r in bite_rows if r["agree"] is False),
                  "no_segment": sum(1 for r in bite_rows if not r["gemini"])},
        "timing": {"transcript": bool(transcript), "located": len(drifts),
                   "abs_drift_median": round(statistics.median(absd), 1) if absd else None,
                   "abs_drift_p90": absd[int(0.9 * (len(absd) - 1))] if absd else None,
                   "within_3s": sum(1 for d in absd if d <= 3)},
    }
    return numbers, {"known": known_rows, "bites": bite_rows, "drifts": drifts}


def call_gemini(video_id: str, cfg, model: str, key: str, duration: float | None, post=None) -> dict:
    """النداء ورقمه. post يُحقن في الاختبار؛ الحقيقي requests.post برأس x-goog-api-key (لا مفتاح في الرابط فلا يظهر في سجل خطأ)."""
    import requests
    post = post or requests.post
    body = build_request(video_id, cfg, duration)
    t0 = time.monotonic()
    r = post(f"{API}/models/{model}:generateContent", json=body, timeout=900,
             headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    seconds = round(time.monotonic() - t0, 1)
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:300]}", "seconds": seconds}
    data, finish, usage = read_response(r.json())
    return {"data": data, "finish": finish, "usage": usage, "seconds": seconds,
            "error": "" if data is not None else f"لا ناتج مقبول ({finish})"}


def list_models(key: str) -> list[str]:
    import requests
    try:
        r = requests.get(f"{API}/models", headers={"x-goog-api-key": key}, timeout=60)
        return [m.get("name", "") for m in r.json().get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
    except Exception as e:  # noqa: BLE001 — تشخيص فقط
        return [f"تعذّر: {type(e).__name__}"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", action="append", default=[])
    ap.add_argument("--model", default="")
    args = ap.parse_args(argv)

    from src import youtube_transcripts
    from src.config import YOUTUBE_POINTS_DIR, load_config
    from tools.speaker_map_probe import KNOWN

    cfg = load_config()
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        print("⛔ لا GEMINI_API_KEY في البيئة")
        return 1
    model = args.model or cfg.path("gemini_probe.model", "gemini-3.8-flash")
    videos = [v for v in (args.video or cfg.path("gemini_probe.videos", []) or []) if re.match(r"^[A-Za-z0-9_-]{6,20}$", v)]
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d")
    points_dir = Path(os.environ.get("TRENDNEWS_YOUTUBE_POINTS_DIR") or YOUTUBE_POINTS_DIR)
    private_dir = points_dir.parents[1] / "gemini_probe" / stamp
    public_path = ROOT / "state" / "gemini_probe" / f"{stamp}.json"
    private_dir.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"النموذج: {model} · فيديوهات: {len(videos)}")
    rows = []
    for vid in videos:
        transcript = youtube_transcripts.load(vid)
        duration = (transcript or {}).get("duration_seconds")
        res = call_gemini(vid, cfg, model, key, duration)
        row = {"video_id": vid, "channel": (transcript or {}).get("channel", ""), "duration": duration,
               "seconds": res.get("seconds"), "finish": res.get("finish", ""), "error": res.get("error", "")[:300]}
        usage = res.get("usage") or {}
        row["tokens"] = {"prompt": usage.get("promptTokenCount"), "output": usage.get("candidatesTokenCount"),
                         "thoughts": usage.get("thoughtsTokenCount"),
                         "by_modality": {d.get("modality"): d.get("tokenCount") for d in usage.get("promptTokensDetails") or []}}
        row["cost_usd"] = cost_usd(usage, cfg)
        private = {"video_id": vid, "model": model, "usage": usage, "error": res.get("error", ""), "gemini": res.get("data")}
        if res.get("data") is not None:
            numbers, details = compare(vid, res["data"], cfg, KNOWN, saved_bites(vid), transcript)
            row.update(numbers)
            private["compare"] = details
            k, b, t = numbers["known"], numbers["bites"], numbers["timing"]
            print(f"✓ {vid}: {numbers['segments']} مقطعًا، {numbers['named_speakers']}/{numbers['speakers']} متحدثًا مسمّى · "
                  f"معروف {k['agree']}/{k['checked']} · مقاطعنا {b['agree']}/{b['compared']} · "
                  f"انزياح وسيط {t['abs_drift_median']} ث ({t['located']} موقَّعًا) · {res['seconds']} ث · ${row['cost_usd']}")
            for r_ in details["known"]:
                print(f"   معروف {r_['second']}: المتوقَّع {r_['expected']} ← Gemini {r_['gemini'] or '—'} ({r_['agree']})")
        else:
            print(f"✗ {vid}: {row['error']}")
            if "HTTP 404" in row["error"]:
                print("   النماذج المتاحة:", ", ".join(list_models(key)[:40]))
        (private_dir / f"{vid}.json").write_text(json.dumps(private, ensure_ascii=False, indent=1), encoding="utf-8")
        rows.append(row)

    done = [r for r in rows if "segments" in r]
    summary = {"model": model, "videos": len(rows), "ok": len(done),
               "known_agree": sum(r["known"]["agree"] for r in done), "known_checked": sum(r["known"]["checked"] for r in done),
               "bites_agree": sum(r["bites"]["agree"] for r in done), "bites_compared": sum(r["bites"]["compared"] for r in done),
               "cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
               "minutes": round(sum(min(r["duration"] or 0, float(cfg.path("gemini_probe.max_minutes", 45)) * 60) for r in rows) / 60, 1)}
    public_path.write_text(json.dumps({"at": now.isoformat(), "summary": summary, "videos": rows},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
