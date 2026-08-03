"""فحص كل مصادر الأخبار وخلاصات الترند وتقرير أيها يعمل.

    python -m src.check_sources

مفيد بعد إضافة مصادر جديدة: روابط RSS تتغير وتُغلق، وهذه الأداة تخبرك
أيها يعمل، وكم خبرًا يعطي، وكم منها يحمل صورة حقيقية.
"""
from __future__ import annotations

import logging
import os
from collections import Counter

from .config import load_config
from .sources import fetch_source
from .trends import fetch_geo

log = logging.getLogger("check")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    cfg = load_config()
    max_age = int(cfg.path("selection.max_age_hours", 18))

    rows: list[tuple[str, str, int, int, str]] = []
    working = broken = 0

    print("\nفحص المصادر...\n")
    for src in cfg.get("sources", []):
        try:
            arts = fetch_source(src, max_age)
        except Exception as exc:  # noqa: BLE001
            rows.append((src["name"], src.get("region", "-"), 0, 0, f"خطأ: {exc}"[:60]))
            broken += 1
            continue

        with_img = sum(1 for a in arts if a.image_candidates)
        if not arts:
            status = "لا أخبار حديثة أو الرابط معطّل"
            broken += 1
        else:
            status = "يعمل"
            working += 1
        rows.append((src["name"], src.get("region", "-"), len(arts), with_img, status))
        print(f"  {'✅' if arts else '❌'} {src['name']:32} {len(arts):3} خبر، "
              f"{with_img:3} بصورة")

    print(f"\nالنتيجة: {working} يعمل · {broken} معطّل\n")

    by_region: Counter = Counter()
    for name, region, n, _, _ in rows:
        if n:
            by_region[region] += n
    print("التغطية الجغرافية:")
    for region, n in by_region.most_common():
        print(f"  {region:10} {n:4} خبر")

    tcfg = cfg.get("trends", {}) or {}
    if tcfg.get("enabled", True):
        print("\nفحص Google Trends...\n")
        ok = 0
        for geo in tcfg.get("geos") or []:
            titles = fetch_geo(geo)
            print(f"  {'✅' if titles else '❌'} {geo}: {len(titles)} موضوع")
            ok += bool(titles)
        print(f"\n  {ok} من {len(tcfg.get('geos') or [])} بلد يعمل")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = ["### 🔎 فحص المصادر", "",
                 "| المصدر | المنطقة | أخبار | بصورة | الحالة |",
                 "|---|---|---|---|---|"]
        lines += [f"| {n} | {r} | {c} | {i} | {s} |" for n, r, c, i, s in rows]
        lines += ["", f"**{working} يعمل · {broken} معطّل**"]
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
