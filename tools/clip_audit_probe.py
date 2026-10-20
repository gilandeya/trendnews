"""قياس يدوي لنداء فحص المقاطع الحقيقي (Issue #1642، Q1): `python tools/clip_audit_probe.py` (يحتاج ANTHROPIC_API_KEY).

يشغّل reel_script.audit_clips على tests/fixtures/reel/1642/mismatch.json (28 مقطعًا استبعدها الحارس النصي القديم؛ expect هو الاسم
الآخر الصحيح أو «» لمقطع سليم) ويطبع الحكم مقابل المتوقع ثم «صحيح N من 28». خارج الحزمة ولا يكتب شيئًا."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import reel_script  # noqa: E402
from src.config import load_config  # noqa: E402


def main() -> int:
    cfg = load_config()
    items = json.loads((ROOT / "tests/fixtures/reel/1642/mismatch.json").read_text(encoding="utf-8"))
    clips = [{"point_id": f"p{i:02d}", "channel_display": "", "speaker_text": it["speaker"], "statement": it["statement"],
              "quote_original": "", "language": "", "quote_arabic": ""} for i, it in enumerate(items)]
    rows = {r["point_id"]: r for r in reel_script.audit_clips(clips, cfg)}
    right = 0
    for c, it in zip(clips, items):
        r = rows.get(c["point_id"])
        said = r["speaker_said_it"] if r else "—"
        other = r["other_name"] if r else ""
        # المتوقع: لمقطع سليم أي حكم غير no (unsure حياد لا استبعاد)، ولمقطع باسم آخر no مع ذكر الاسم
        ok = (said != "no") if not it["expect"] else (said == "no" and it["expect"] in other)
        right += ok
        print(f"{'✔' if ok else '✘'} {said:6} | آخر={other!r:20} | متوقع={it['expect']!r:12} | {it['statement'][:50]}")
    print(f"صحيح {right} من {len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
