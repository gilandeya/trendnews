"""أداة قياس (Issue #1696، S0): «خريطة متكلمي الحلقة» -- هل تسمّي خريطة واحدة لكل حلقة (وجوه مجمَّعة + أسماء شريط القناة
بالأغلبية) كل وجه تسمية صحيحة، وبأي وقت وكلفة؟ قياس فقط: لا يستدعيها شيء في src/ ولا أثر على أي مسار ولا render_version.

التشغيل (يدويًا، خارج الحزمة):
    python tools/speaker_map_probe.py --video qB_4P0mUCyI --video QFMGl1rCLhU \\
        --points qB_4P0mUCyI:680 --points qB_4P0mUCyI:host
بلا --points تُقاس الطوابع المعروفة (KNOWN) للفيديوهات المطلوبة.

الخطوات: تنزيل الحلقة كاملة بدقة منخفضة (صورة فقط) ← لقطة كل step ثانية ← وجوه (YuNet للكشف وSFace للبصمة، على المعالج، بلا نموذج
لغوي) وتجميعها ← قراءة شريط الاسم عند تغيّره وحده بنداء Haiku مجمَّع ← تصويت بالأغلبية لكل مجموعة ← إسناد كل طابع إلى اسم.
كل العتبات في config.yaml: speaker_map.

التقرير الرقمي وحده يُكتب إلى state/speaker_probe/<التاريخ>.json (مستودع عام: بلا صور ولا لقطات ولا نصوص). معاينة وجوه المجموعات
(--preview) تُكتب إلى youtube-data/speaker_probe/<التاريخ>/ في المستودع الخاص وحده.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# الحقيقة المعروفة من الريل 02b4436a2b66 (#1676): (فيديو، ثانية أو "host") ← الاسم المتوقع؛ None = غير معروف (يُطبع ما وُجد)
KNOWN: list[tuple[str, int | str, str | None]] = [
    ("qB_4P0mUCyI", 680, "علي البخيتي"),
    ("qB_4P0mUCyI", 944, "علي البخيتي"),
    ("qB_4P0mUCyI", 1000, "منيف عماش الحربي"),
    ("qB_4P0mUCyI", "host", "أيمن سرور"),
    ("QFMGl1rCLhU", 723, "مصطفى بكري"),
    ("QFMGl1rCLhU", 1211, "مصطفى بكري"),
    ("nx6MtSAGGLQ", 2446, None),
    ("nx6MtSAGGLQ", "host", "فرداد فرحزاد"),
]


from src.speaker_map import (  # noqa: E402,F401 -- النواة في src/ والأداة تقيس بها
    _cfg,
    cluster_faces,
    chyron_diffs,
    chyron_changes,
    vote_names,
    pick_host,
    pick_read_frames,
    _tokens,
    names_match,
    proxy_url,
    episode_opts,
    download_episode,
    video_duration,
    extract_frames,
    fetch_models,
    FaceEngine,
    chyron_band,
    read_chyrons,
    build_map,
    assign_at,
)

# ──────────────────────────── التشغيل ────────────────────────────


def parse_points(items: list[str]) -> list[tuple[str, int | str]]:
    out = []
    for item in items:
        vid, _, key = item.rpartition(":")
        out.append((vid, "host" if key == "host" else int(key)))
    return out


def run_video(video_id: str, points: list[tuple[str, int | str]], cfg, engine: FaceEngine, proxy, work_root: Path,
              preview_root: Path | None) -> dict:
    report = {"video_id": video_id, "timings": {}, "counters": {"haiku_calls": 0, "haiku_errors": []}}
    work = work_root / video_id
    work.mkdir(parents=True, exist_ok=True)
    try:
        t0 = time.monotonic()
        dl = download_episode(video_id, int(_cfg(cfg, "height", 240)), work, proxy)
        report["timings"]["download"] = round(time.monotonic() - t0, 2)
        report["download"] = {"size_bytes": dl["size_bytes"], "proxy_bytes": dl["proxy_bytes"], "format_id": dl["format_id"]}
        built = build_map(dl["path"], work, cfg, engine, report["timings"], report["counters"],
                          (preview_root / video_id) if preview_root else None)
    except Exception as exc:  # noqa: BLE001 -- فشل فيديو لا يوقف بقية الفيديوهات
        from src import reel_clips
        report["error"] = reel_clips.scrub_text(f"{type(exc).__name__}: {exc}")[:200]
        return report
    report["duration"] = built["duration"]
    report["map"] = built["map"]
    report["host_cluster"] = built["host"]
    report["read_log"] = built.get("read_log", [])   # S1: كان يُبنى ولا يُكتب فلم نعرف لماذا قلّت الأصوات
    t0 = time.monotonic()
    report["assignments"] = []
    for vid, key in points:
        if vid != video_id:
            continue
        if key == "host":
            row = next((r for r in built["map"] if r["is_host"]), None)
            report["assignments"].append({"t": "host", "cluster": built["host"], "name": row["name"] if row else None})
            continue
        try:
            report["assignments"].append(assign_at(dl["path"], work, float(key), built, cfg, engine))
        except Exception as exc:  # noqa: BLE001
            report["assignments"].append({"t": key, "name": None, "error": f"{type(exc).__name__}: {str(exc)[:80]}"})
    report["timings"]["assign"] = round(time.monotonic() - t0, 2)
    return report


def comparison_lines(reports: list[dict]) -> list[str]:
    lines = []
    for r in reports:
        for a in r.get("assignments", []):
            known = [e for v, k, e in KNOWN if v == r["video_id"] and str(k) == str(a["t"] if a["t"] == "host" else int(a["t"]))]
            expected = known[0] if known else None
            got = a.get("name")
            if expected is None:
                lines.append(f"{r['video_id']} @ {a['t']}: غير معروف ← {got or '—'}")
            else:
                ok = names_match(expected, got)
                lines.append(f"{r['video_id']} @ {a['t']}: {expected} ← {got or '—'} {'✅' if ok else '❌'}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--video", action="append", default=[], help="معرّف فيديو يوتيوب (يتكرر)")
    ap.add_argument("--points", action="append", default=[], help="<id>:<ثانية> أو <id>:host (يتكرر)")
    ap.add_argument("--report-dir", default=str(ROOT / "state" / "speaker_probe"))
    ap.add_argument("--out-root", default=str(ROOT / "youtube-data" / "speaker_probe"))
    ap.add_argument("--preview", action="store_true", help="وجه نموذجي لكل مجموعة إلى المستودع الخاص (--out-root)")
    args = ap.parse_args(argv)
    if not args.video:
        ap.error("--video مطلوب")

    from src.config import load_config
    cfg = load_config()
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    points = parse_points(args.points) if args.points else [(v, k) for v, k, _ in KNOWN if v in args.video]
    proxy = proxy_url()
    reports = []
    with tempfile.TemporaryDirectory(prefix="speaker_probe_") as tmp:
        tmp_path = Path(tmp)
        t0 = time.monotonic()
        yunet, sface = fetch_models(cfg, tmp_path)
        engine = FaceEngine(yunet, sface, cfg)
        models_seconds = round(time.monotonic() - t0, 2)
        preview_root = Path(args.out_root) / date if args.preview else None
        for vid in args.video:
            print(f"── {vid}", file=sys.stderr)
            reports.append(run_video(vid, points, cfg, engine, proxy, tmp_path, preview_root))
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"{date}.json").write_text(
        json.dumps({"date": date, "models_seconds": models_seconds, "videos": reports}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    for r in reports:
        if r.get("error"):
            print(f"{r['video_id']}: فشل — {r['error']}")
        else:
            c = r["counters"]
            print(f"{r['video_id']}: {r.get('duration', 0):.0f} ث · لقطات {c.get('frames')} · وجوه {c.get('faces')} · "
                  f"مجموعات {c.get('clusters')} · قراءات شريط {c.get('chyron_reads', 0)} ({c['haiku_calls']} نداء) · {r['timings']}")
    lines = comparison_lines(reports)
    print("\n".join(lines))
    right = sum(1 for ln in lines if ln.endswith("✅"))
    judged = sum(1 for ln in lines if ln.endswith(("✅", "❌")))
    print(f"صحيح {right} من {judged}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
