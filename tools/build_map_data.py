"""يبني بيانات خرائط الريل (assets/maps/) من Natural Earth (ملك عام): حدود الدول بمقياس 1:50m مبسَّطة، ومدن بأسمائها العربية.

يُشغَّل يدويًا مرة حين تُحدَّث المصادر؛ الريل لا يحتاج شبكة وقت التركيب لأن الملفين الناتجين في المستودع.
الاستعمال: python tools/build_map_data.py [مجلد فيه الملفات منزَّلة سلفًا]
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
COUNTRIES = "ne_50m_admin_0_countries.geojson"
PLACES = "ne_10m_populated_places.geojson"
OUT = Path(__file__).resolve().parents[1] / "assets" / "maps"
# تبسيط الحدود (درجات): 0.02 ≈ 2 كم، أدق من بكسل في أوسع لقطة (دولة كاملة) وأخفّ بكثير من الأصل
TOLERANCE = 0.02
# مدن العالم كثيرة؛ يكفي ما له اسم عربي وسكانه فوق هذا الحد، وعواصم الدول كلها مهما صغرت
MIN_POP = 20000


def _load(src: Path | None, name: str) -> dict:
    if src and (src / name).exists():
        return json.loads((src / name).read_text(encoding="utf-8"))
    with urllib.request.urlopen(BASE + name, timeout=120) as r:  # noqa: S310 -- رابط ثابت لملك عام
        return json.loads(r.read().decode("utf-8"))


def _dp(points: list, tol: float) -> list:
    """دوغلاس-بوكر تكراريًا (بلا عودية تتجاوز حدّ بايثون في الحلقات الطويلة)."""
    if len(points) < 4:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = points[a], points[b]
        dx, dy = x2 - x1, y2 - y1
        norm = (dx * dx + dy * dy) ** 0.5 or 1e-12
        best, idx = 0.0, -1
        for i in range(a + 1, b):
            x0, y0 = points[i]
            d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norm
            if d > best:
                best, idx = d, i
        if best > tol and idx > 0:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def _rings(geom: dict) -> list:
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    out = []
    for poly in polys:
        pts = [(round(x, 3), round(y, 3)) for x, y in poly[0]]   # الحلقة الخارجية وحدها: البحيرات لا تُرسم
        # الحلقة مغلقة (أولها آخرها) فلا خط مرجعي لدوغلاس-بوكر؛ تُقسم عند أبعد نقطة عن أولها وتُبسَّط كل نصف وحده
        far = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
        ring = _dp(pts[:far + 1], TOLERANCE)[:-1] + _dp(pts[far:], TOLERANCE)
        if len(ring) >= 4:
            out.append([[x, y] for x, y in ring])
    return out


def build(src: Path | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    countries = {}
    for f in _load(src, COUNTRIES)["features"]:
        p = f["properties"]
        code = p["ADM0_A3"]
        rings = _rings(f["geometry"])
        if not rings:   # جزر صغيرة يمحوها التبسيط: لا شكل يُرسم لها بهذا المقياس
            continue
        xs = [x for r in rings for x, _ in r]
        ys = [y for r in rings for _, y in r]
        countries[code] = {"ar": p.get("NAME_AR") or "", "en": p.get("NAME") or "", "label": [p["LABEL_X"], p["LABEL_Y"]],
                           "bbox": [min(xs), min(ys), max(xs), max(ys)], "rings": rings}
    places = []
    for f in _load(src, PLACES)["features"]:
        p = f["properties"]
        ar = (p.get("NAME_AR") or "").strip()
        if not ar or ((p.get("POP_MAX") or 0) < MIN_POP and not p.get("ADM0CAP")):
            continue
        places.append({"ar": ar, "en": p.get("NAME") or "", "lon": round(p["LONGITUDE"], 4), "lat": round(p["LATITUDE"], 4),
                       "country": p.get("ADM0_A3") or "", "pop": int(p.get("POP_MAX") or 0), "capital": bool(p.get("ADM0CAP"))})
    places.sort(key=lambda x: -x["pop"])
    (OUT / "countries.json").write_text(json.dumps(countries, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (OUT / "places.json").write_text(json.dumps(places, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(countries)} دولة، {len(places)} مدينة ← {OUT}")


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
