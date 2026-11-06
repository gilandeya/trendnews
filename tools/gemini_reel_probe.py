"""قياس: هل يسمّي Gemini قائل كل مقطع في ريل مُركَّب كما سمّاه تركيبنا (الشريط وقائمة الضيوف وخريطة الوجوه وحرّاس Q10–Q16)؟

السبب (قرار صاحب المشروع 6/11): «الاعتماد على البروكسي وسلسلتنا، إلا إذا سبّب ذلك خطأً أو خللًا في الجودة ولو قليلًا، فعندها يعمل
Gemini». فلا يُستبدل حارس قبل أن نعرف بأرقام على ريلات حقيقية أين يختلف الطرفان. قياس فقط: لا شيء في src/ يستدعيه، ولا مسودة
تُكتب ولا قضية.

لكل ريل: مقاطع السيناريو بنوافذها الفعلية (ضبط الكلمات `render_crops[i].exact` إن وُجد وإلا حدّا المشهد) ومصيرها في التركيب (بقي باسم،
صُحّح قائله `render_relabel`، أو حُذف `render_dropped` وسببه). لكل فيديو نداء Gemini واحد من أول الحلقة (حيث يُعرَّف الضيوف) إلى ما بعد آخر
نافذة بقليل، يسأل عن قائل كل نافذة. المقارنة بالأسماء (`reel_render.speaker_matches`) تصنّف كل مقطع:
  agree · disagree (بقي عندنا باسم وGemini يسمّي غيره) · dropped_ok · dropped_maybe_wrong (حذفناه وGemini يقول إن قائله هو قائل
  السيناريو) · gemini_named (عرضناه باسم القناة وحده وGemini يسمّيه) · unknown (لا اسم عند Gemini).
الخلاف لا يُحكم فيه آليًا بمن أصاب: يُطبع للمراجعة البشرية.

المخرجات: youtube-data/gemini_probe/<التاريخ>/reel_<id>.json (الخاص: الأسماء والردود) و state/gemini_probe/<التاريخ>-reels.json (أرقام فقط).
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "speakers": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "name_ar": {"type": "STRING"}, "name_original": {"type": "STRING"}, "role": {"type": "STRING"},
            "is_host": {"type": "BOOLEAN"},
            "name_source": {"type": "STRING", "enum": ["chyron", "introduced", "addressed", "unknown"]}},
            "required": ["name_ar", "is_host", "name_source"]}},
        "windows": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "id": {"type": "STRING"}, "speaker": {"type": "STRING"}, "one_speaker": {"type": "BOOLEAN"},
            "evidence": {"type": "STRING"}},
            "required": ["id", "speaker", "one_speaker"]}},
    },
    "required": ["speakers", "windows"],
}


def video_id_of(url: str) -> str:
    try:
        u = urlparse(url or "")
        if "youtu.be" in u.netloc:
            return u.path.strip("/")
        return (parse_qs(u.query).get("v") or [""])[0]
    except ValueError:
        return ""


def reel_clips(draft: dict) -> list[dict]:
    """مقاطع الريل بنوافذها ومصيرها في التركيب. دالة خالصة."""
    dropped = {d.get("point_id"): d.get("reason", "") for d in draft.get("render_dropped") or [] if isinstance(d, dict)}
    relabel = {r.get("point_id"): r for r in draft.get("render_relabel") or [] if isinstance(r, dict)}
    crops = draft.get("render_crops") or {}
    out = []
    for i, s in enumerate((draft.get("script") or {}).get("scenes") or []):
        if s.get("kind") not in ("clip", "cold_open_clip") or not s.get("point_id"):
            continue
        vid = video_id_of(s.get("video_url", ""))
        if not vid:
            continue
        exact = ((crops.get(str(i)) if isinstance(crops, dict) else None) or {}).get("exact") or {}
        t0 = exact.get("t0") if exact.get("source") == "words" else None
        t1 = exact.get("t1") if exact.get("source") == "words" else None
        pid = s["point_id"]
        name = (relabel.get(pid) or {}).get("to") or s.get("speaker_name") or ""
        out.append({"id": pid, "scene": i, "video_id": vid, "channel": s.get("channel_display", ""),
                    "start": float(t0 if t0 is not None else s.get("start") or 0),
                    "end": float(t1 if t1 is not None else s.get("end") or 0),
                    "scripted": s.get("speaker_name", ""), "ours": "" if pid in dropped else name,
                    "dropped": pid in dropped, "drop_reason": dropped.get(pid, ""),
                    "relabeled": pid in relabel})
    return out


def _clock(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def build_request(video_id: str, clips: list[dict], cfg) -> dict:
    """بلا temperature. النداء من أول الحلقة لأن الضيوف يُعرَّفون فيه غالبًا، وينتهي بعد آخر نافذة بـtail_seconds فلا يُدفع ثمن ما بعدها."""
    from src import gemini
    g = cfg.path("gemini_probe.reels", {}) or {}
    end = max(c["end"] for c in clips) + float(g.get("tail_seconds", 60))
    part = gemini.video_part(video_id)
    part["video_metadata"] = {"end_offset": f"{int(end)}s"}
    lines = ["النوافذ (من بداية الفيديو، MM:SS):"]
    lines += [f"- {c['id']}: {_clock(c['start'])} – {_clock(c['end'])}" for c in clips]
    return {"system_instruction": {"parts": [{"text": g.get("system", "")}]},
            "contents": [{"role": "user", "parts": [part, {"text": "\n".join(lines)}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA,
                                 "mediaResolution": cfg.path("gemini_probe.media_resolution", "MEDIA_RESOLUTION_LOW"),
                                 "maxOutputTokens": int(cfg.path("gemini_probe.max_output_tokens", 65536))}}


def classify(clip: dict, gem: dict | None, speakers: dict, cfg) -> str:
    """تصنيف مقطع واحد. دالة خالصة. gem = نافذته في رد Gemini؛ speakers = name_ar ← سجل المتحدث."""
    from src.reel_render import speaker_matches
    name = " ".join(str((gem or {}).get("speaker") or "").split())
    rec = speakers.get(name) or {}
    if not name or rec.get("name_source") in (None, "unknown"):
        return "unknown"
    vs = clip["scripted"] if clip["dropped"] else clip["ours"]
    if not vs:
        # عرضناه باسم القناة وحده وGemini يعرف اسمه من الشريط أو التعريف: اسم فاتنا (يُراجَع بيد إنسان قبل أن يُعدّ مكسبًا)
        return "gemini_named" if not clip["dropped"] else "unknown"
    same = speaker_matches(name, rec.get("name_original", ""), vs, cfg)
    if same is None:
        return "unknown"
    if clip["dropped"]:
        return "dropped_maybe_wrong" if same else "dropped_ok"
    return "agree" if same else "disagree"


def compare(clips: list[dict], data: dict, cfg) -> list[dict]:
    speakers = {" ".join(str(s.get("name_ar") or "").split()): s for s in data.get("speakers") or [] if isinstance(s, dict)}
    wins = {str(w.get("id")): w for w in data.get("windows") or [] if isinstance(w, dict)}
    rows = []
    for c in clips:
        gem = wins.get(c["id"])
        rows.append({**c, "gemini": (gem or {}).get("speaker", ""), "gemini_one_speaker": (gem or {}).get("one_speaker"),
                     "gemini_evidence": (gem or {}).get("evidence", ""),
                     "gemini_source": (speakers.get(" ".join(str((gem or {}).get("speaker") or "").split())) or {}).get("name_source", ""),
                     "verdict": classify(c, gem, speakers, cfg)})
    return rows


VERDICTS = ("agree", "disagree", "dropped_ok", "dropped_maybe_wrong", "gemini_named", "unknown")


def run(cfg, key: str, private_dir, public_path, draft_ids: list[str], post=None, now_iso: str = "") -> dict:
    """يشغّل القياس على المسودات ويكتب الملفين. post يُحقن في الاختبار."""
    from src import gemini, store
    g = cfg.path("gemini_probe.reels", {}) or {}
    model = g.get("model") or cfg.path("gemini_probe.model", "gemini-3.8-flash")
    price = cfg.path("gemini_probe.price_per_mtok", {}) or {}
    summary = {v: 0 for v in VERDICTS}
    summary.update(reels=0, clips=0, cost_usd=0.0, errors=0)
    reels = []
    for did in draft_ids:
        if not re.match(r"^[0-9a-f]{12}$", did or ""):
            continue
        paths = sorted(store.DRAFTS_DIR.glob(f"*/{did}.json"))
        if not paths:
            print(f"✗ {did}: لا مسودة")
            continue
        draft = json.loads(paths[0].read_text(encoding="utf-8"))
        clips = reel_clips(draft)
        by_video: dict[str, list[dict]] = {}
        for c in clips:
            by_video.setdefault(c["video_id"], []).append(c)
        rows, private_calls, cost = [], [], 0.0
        for vid, vclips in by_video.items():
            code, resp, seconds = gemini.generate(build_request(vid, vclips, cfg), model, key, post=post)
            if code != 200:
                summary["errors"] += 1
                private_calls.append({"video_id": vid, "error": f"HTTP {code}: {resp}"[:300]})
                rows += [{**c, "verdict": "unknown", "gemini": "", "error": f"HTTP {code}"} for c in vclips]
                continue
            data, finish, usage = gemini.read_response(resp, "windows")
            c_ = gemini.cost_usd(usage, price)
            cost += c_
            private_calls.append({"video_id": vid, "finish": finish, "usage": usage, "seconds": seconds, "gemini": data})
            if data is None:
                summary["errors"] += 1
                rows += [{**c, "verdict": "unknown", "gemini": "", "error": finish} for c in vclips]
                continue
            rows += compare(vclips, data, cfg)
        counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in VERDICTS}
        for v in VERDICTS:
            summary[v] += counts[v]
        summary["reels"] += 1
        summary["clips"] += len(rows)
        summary["cost_usd"] = round(summary["cost_usd"] + cost, 4)
        reels.append({"draft": did, "clips": len(rows), "videos": len(by_video), "cost_usd": round(cost, 4), **counts})
        private_dir.mkdir(parents=True, exist_ok=True)
        (private_dir / f"reel_{did}.json").write_text(
            json.dumps({"draft": did, "model": model, "rows": rows, "calls": private_calls}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"✓ ريل {did}: {len(rows)} مقطعًا من {len(by_video)} فيديو · " +
              " · ".join(f"{v} {counts[v]}" for v in VERDICTS) + f" · ${round(cost, 4)}")
        for r in rows:
            if r["verdict"] in ("disagree", "dropped_maybe_wrong", "gemini_named"):
                print(f"   ⚠️ {r['verdict']} {r['channel']} {_clock(r['start'])}: نحن «{r['ours'] or r['scripted']}»"
                      f"{' (حُذف)' if r['dropped'] else ''} ← Gemini «{r['gemini']}» ({r['gemini_source']})")
    public_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.write_text(json.dumps({"at": now_iso, "model": model, "summary": summary, "reels": reels},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return summary
