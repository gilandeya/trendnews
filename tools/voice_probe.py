"""قياس صوت الراوي في ElevenLabs (طلب صاحب المشروع 20/11): يقرأ سطور reel.tts.sample_lines بعدة صيغ ويحفظ كل صيغة ملف mp3
يُستمع إليه، قبل أن يُعتمد في الإنتاج أي تغيير. قياس فقط: لا شيء في src/ يستدعيه، ولا مسودة ولا ريل.

الصيغ (كلها بالأنبوب نفسه الذي يمرّ به صوت الريل: تشكيل ← جمل ← وقف ← أسماء أجنبية برسمها ← نداء لكل جملة ← وصل بصمت):
  01_current        الصوت والإعداد الحاليان كما في الإنتاج (كل جملة وحدها، والتسريع بـatempo بعد التوليد).
  02_context        + نص الجملة السابقة واللاحقة في الطلب (previous_text/next_text) فتتصل النبرة.
  03_native_speed   + السرعة والإعدادات داخل ElevenLabs (voice_settings) بلا atempo.
  04_no_tashkeel    مثل 03 بنص بلا تشكيل: هل التشكيل الكامل يفيد هذا النموذج أم يربكه؟
  05_whole          الفقرة كلها في طلب واحد بإعدادات 03: مرجع لأكثر قراءة اتصالًا يعطيها النموذج.
  voice_<الاسم>_*   صيغتا 03 و04 بكل صوت يُمرَّر في --voices.
  model_<الاسم>     صيغة 03 بكل نموذج يُمرَّر في --models.

python tools/voice_probe.py [--voices id1,id2] [--models eleven_v3] [--gender female] [--out voice_probe_out]
يحتاج ELEVENLABS_API_KEY وANTHROPIC_API_KEY (للتشكيل). الملفات وتقرير report.json في --out، وجدول في ملخص التشغيلة.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import reel, tts  # noqa: E402
from src.config import load_config  # noqa: E402

VOICE_API = "https://api.elevenlabs.io/v1/voices/"


def voice_info(voice_id: str, key: str, get=None) -> dict:
    """اسم الصوت ووسومه (اللهجة واللغة والجنس) من ElevenLabs، ليُعرف ما في الإعداد فعلًا. العطل ← المعرّف وحده."""
    get = get or tts._el_get
    try:
        data = get(VOICE_API + voice_id, {"xi-api-key": key}, tts.TIMEOUT) or {}
    except Exception as exc:  # noqa: BLE001 -- اسم الصوت للعرض وحده
        return {"id": voice_id, "name": voice_id, "error": str(exc).replace(key, "***")[:150]}
    labels = data.get("labels") or {}
    return {"id": voice_id, "name": data.get("name") or voice_id,
            "labels": {k: labels.get(k) for k in ("accent", "language", "gender", "age", "use_case", "descriptive") if labels.get(k)}}


def slug(text: str) -> str:
    keep = "".join(c if c.isalnum() else "_" for c in (text or "").strip())
    return "_".join(p for p in keep.split("_") if p)[:30] or "voice"


def prepare(cfg, diacritize=None) -> dict:
    """النص كما يُعدّه التركيب: التشكيل والأعلام مرة واحدة لكل الصيغ (فلا تختلف الصيغ في التشكيل نفسه)."""
    lines = [str(x) for x in (cfg.path("reel.tts.sample_lines") or []) if str(x).strip()]
    text = " ".join(lines)
    diacritize = diacritize or (lambda t: tts.diacritize_full(t, cfg))
    shown, warn, nouns = diacritize(text)
    # الأداة تقيس ElevenLabs وحده، فوقف الأعلام بقاعدته (ريل 5d767581bd5e)
    shown = tts.apply_proper_nouns(shown, nouns, every_word=tts.foreign_every_word(cfg, "elevenlabs"),
                                   person_bare=bool(cfg.path("reel.tts.foreign_waqf.person_bare")))
    marked = tts.split_sentences(shown)
    return {"text": text, "warn": warn, "nouns": nouns, "marked": marked,
            "plain": [tts.strip_tashkeel(s) for s in marked]}


def spoken_lines(sentences: list[str], nouns: list, cfg) -> list[str]:
    """نص النطق كما يرسله التركيب (tts.spoken_line): الوقف ثم أسماء الأشخاص الأجنبية برسمها ثم الأرقام بالكلمات."""
    return [tts.spoken_line(s, nouns, cfg, latin=bool(cfg.path("reel.tts.latin_names.enabled")))[0] for s in sentences]


def variants(cfg, prep: dict, voices: list[dict], models: list[str], gender: str) -> list[dict]:
    """خطة الصيغ: لكل صيغة الصوت والنموذج والجمل والسياق والإعدادات والتسريع بعد التوليد."""
    e = tts._el_cfg(cfg)
    vp = cfg.path("reel.tts.voice_probe") or {}
    current = (e.get("voices") or {}).get(gender) or next(iter((e.get("voices") or {}).values()), "")
    model = e.get("model", "eleven_multilingual_v2")
    tempo = float(cfg.path("reel.tts.speed", 1) or 1)
    native = dict(vp.get("settings") or {})
    marked = spoken_lines(prep["marked"], prep["nouns"], cfg)
    plain = spoken_lines(prep["plain"], prep["nouns"], cfg)
    plan = [
        {"name": "01_current", "voice": current, "model": model, "lines": marked, "context": False, "settings": None, "tempo": tempo},
        {"name": "02_context", "voice": current, "model": model, "lines": marked, "context": True, "settings": None, "tempo": tempo},
        {"name": "03_native_speed", "voice": current, "model": model, "lines": marked, "context": True, "settings": native, "tempo": 1.0},
        {"name": "04_no_tashkeel", "voice": current, "model": model, "lines": plain, "context": True, "settings": native, "tempo": 1.0},
        {"name": "05_whole", "voice": current, "model": model, "lines": [" ".join(marked)], "context": False, "settings": native,
         "tempo": 1.0},
    ]
    for v in voices:
        tag = slug(v.get("name") or v["id"])
        plan.append({"name": f"voice_{tag}_tashkeel", "voice": v["id"], "model": model, "lines": marked, "context": True,
                     "settings": native, "tempo": 1.0})
        plan.append({"name": f"voice_{tag}_plain", "voice": v["id"], "model": model, "lines": plain, "context": True,
                     "settings": native, "tempo": 1.0})
    for m in models:
        plan.append({"name": f"model_{slug(m)}", "voice": current, "model": m, "lines": marked, "context": True,
                     "settings": native, "tempo": 1.0})
    return plan


def requests_for(v: dict) -> list[dict]:
    """جسم الطلب الإضافي لكل جملة (يدمجه tts.el_synthesize فوق إعداد الإنتاج)."""
    out = []
    lines = v["lines"]
    for k, line in enumerate(lines):
        extra = {"model_id": v["model"]}
        if v.get("settings"):
            extra["voice_settings"] = dict(v["settings"])
        if v.get("context"):
            extra["previous_text"] = " ".join(lines[:k])[-600:]
            extra["next_text"] = " ".join(lines[k + 1:])[:600]
        out.append({"text": line, "extra": extra})
    return out


def _ffmpeg(args: list[str]) -> None:
    exe = reel.ffmpeg_path() or "ffmpeg"
    subprocess.run([exe, "-y", "-loglevel", "error", *args], check=True)


def render(v: dict, cfg, key: str, out_dir: Path, post=None, run=None) -> dict:
    """يولّد صيغة واحدة: نداء لكل جملة، ثم atempo (إن طُلب) وصمت الجمل كما في التركيب، ثم ملف mp3 واحد."""
    run = run or _ffmpeg
    silence = float(cfg.path("reel.tts.sentence_silence", 0.35))
    row = {"name": v["name"], "voice": v["voice"], "model": v["model"], "chars": 0, "requests": 0}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        wavs = []
        for k, req in enumerate(requests_for(v)):
            res = tts.el_synthesize(req["text"], v["voice"], cfg, key, post=post, extra=req["extra"])
            row["requests"] += 1
            if not res.get("ok"):
                row["error"] = str(res.get("error") or "?")[:200]
                return row
            row["chars"] += int(res.get("chars") or 0)
            mp3 = tmp / f"{k}.mp3"
            mp3.write_bytes(res["audio"])
            wav = tmp / f"{k}.wav"
            tempo = f"atempo={v['tempo']:g}," if abs(float(v.get("tempo") or 1) - 1) > 1e-6 else ""
            run(["-i", str(mp3), "-af", f"{tempo}aresample=44100,apad=pad_dur={silence}", str(wav)])
            wavs.append(wav)
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{w}'\n" for w in wavs), encoding="utf-8")
        target = out_dir / f"{v['name']}.mp3"
        run(["-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "libmp3lame", "-b:a", "192k", str(target)])
        row["file"] = target.name
    return row


def summary_lines(report: dict) -> list[str]:
    lines = ["## 🎙️ قياس صوت الراوي", "",
             "نزّل الملفات من **Artifacts** أسفل صفحة التشغيلة (voice-probe)، واستمع إليها بالترتيب.", ""]
    for v in report["voices"]:
        tag = "، ".join(f"{k}: {val}" for k, val in (v.get("labels") or {}).items())
        lines.append(f"- الصوت `{v['id']}` = **{v['name']}**" + (f" ({tag})" if tag else "") + (f" ⚠️ {v['error']}" if v.get("error") else ""))
    lines += ["", "| الملف | الصوت | النموذج | الحروف | ملاحظة |", "|---|---|---|---|---|"]
    for r in report["variants"]:
        lines.append(f"| {r.get('file') or r['name']} | {r['voice']} | {r['model']} | {r['chars']} | {r.get('error', '')} |")
    lines += ["", f"مجموع الحروف: {report['chars']}" + (f" · ⚠️ التشكيل: {report['warn']}" if report.get("warn") else "")]
    return lines


def run_probe(cfg, key: str, voices_arg: list[str], models: list[str], gender: str, out_dir: Path,
              post=None, get=None, run=None, diacritize=None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    prep = prepare(cfg, diacritize=diacritize)
    e = tts._el_cfg(cfg)
    current_ids = list(dict.fromkeys((e.get("voices") or {}).values()))
    extra = [voice_info(v, key, get=get) for v in voices_arg if v and v not in current_ids]
    report = {"date": dt.date.today().isoformat(), "warn": prep["warn"], "sentences": len(prep["marked"]),
              "voices": [voice_info(v, key, get=get) for v in current_ids] + extra, "variants": []}
    for v in variants(cfg, prep, extra, models, gender):
        report["variants"].append(render(v, cfg, key, out_dir, post=post, run=run))
    report["chars"] = sum(r["chars"] for r in report["variants"])
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "text.txt").write_text("\n".join(prep["marked"]) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="قياس صوت الراوي في ElevenLabs")
    ap.add_argument("--voices", default="", help="معرّفات أصوات أخرى للتجربة، مفصولة بفواصل")
    ap.add_argument("--models", default="", help="نماذج أخرى للتجربة، مفصولة بفواصل (مثل eleven_v3)")
    ap.add_argument("--gender", default="female", help="جنس الصوت الحالي الذي تُجرَّب عليه الصيغ")
    ap.add_argument("--out", default="voice_probe_out")
    args = ap.parse_args(argv)
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        print("لا مفتاح ELEVENLABS_API_KEY")
        return 1
    cfg = load_config()
    split = lambda s: [x.strip() for x in (s or "").split(",") if x.strip()]  # noqa: E731
    report = run_probe(cfg, key, split(args.voices), split(args.models), args.gender, Path(args.out))
    lines = summary_lines(report)
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return 0 if any(r.get("file") for r in report["variants"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
