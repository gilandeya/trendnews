"""خرائط السياق خلف جمل الراوي في الريل (المرحلة 4 من تصميم الريل، الصيغة الثانية).

جملة سياق تذكر أماكن ← خريطة تقترب من تلك الأماكن، وتلوّن الدول المذكورة، وترسم سهمًا لكل حركة تذكرها الجملة
(«زحف الحوثيون من صعدة إلى صنعاء» ← سهم صعدة → صنعاء). القاعدة الحاكمة: كل ما يُرسم مذكور في نص الجملة نفسها.
النموذج يسمّي الأماكن والحركة فقط (خطة اللقطات، reel_broll)، والإحداثيات من معجم ثابت في المستودع (Natural Earth،
ملك عام: assets/maps، يبنيه tools/build_map_data.py)؛ مكان لا يوجد في المعجم أو لا يرد في الجملة ← لا خريطة لتلك الجملة.
"""
from __future__ import annotations

import json
import logging
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from . import imaging

log = logging.getLogger("trendnews")

MAPS_DIR = Path(__file__).resolve().parents[1] / "assets" / "maps"

_TASHKEEL = re.compile("[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
# حرف كلمة: \w يشمل الحروف العربية ويستثني «،» و«؛» (النطاق العربي كله كان يعدّ الفاصلة العربية حرفًا فلا تُرى «فرنسا،»)
_LETTER = r"\w"
# السوابق الملتصقة بالاسم في الجملة («وصنعاء»، «بالحديدة»، «للحديدة»)، الأطول أولًا
_PREFIXES = ("وبال", "وال", "بال", "فال", "كال", "لل", "ال", "و", "ب", "ل", "ف", "ك")


def norm(text: str) -> str:
    """طيّ للمطابقة وحدها: بلا تشكيل ولا تطويل، والألفات ألفًا، وى ياءً، وة هاءً، والمسافات واحدة."""
    t = _TASHKEEL.sub("", str(text or ""))
    t = re.sub("[أإآٱ]", "ا", t).replace("ى", "ي").replace("ة", "ه")
    return " ".join(t.split())


def compact(text: str) -> str:
    """الاسم المطبَّع بلا مسافات: مفتاح المعجم، فلا يمنع اختلاف الفصل («أبو ظبي»/«أبوظبي»، «عبد الله»/«عبدالله») المطابقة."""
    return norm(text).replace(" ", "")


def _bare(name: str) -> str:
    """الاسم بلا «ال» في أوله: «الحديدة» تُكتب «للحديدة» بعد اللام فيسقط ألفها."""
    return name[2:] if name.startswith("ال") and len(name) > 3 else name


def mentioned(name: str, sentence: str) -> bool:
    """يرد الاسم في الجملة كلمةً (أو كلمات) كاملة، بسابقة ملتصقة واحدة أو بلا سابقة."""
    n, s = norm(name), norm(sentence)
    if not n:
        return False
    forms = {n, _bare(n)}
    # المسافة داخل الاسم اختيارية في الاتجاهين: «أبوظبي» في الجملة و«أبو ظبي» في المعجم (ريل مفاوضات أبوظبي 12/11 بلا خريطة)
    alt = "|".join(r"\s?".join(re.escape(ch) for ch in compact(f)) for f in sorted(forms, key=len, reverse=True))
    pre = "|".join(_PREFIXES)
    return re.search(rf"(?<!{_LETTER})(?:{pre})?(?:{alt})(?!{_LETTER})", s) is not None


# ───────────────────────────── المعجم ─────────────────────────────


@lru_cache(maxsize=4)
def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def countries(cfg) -> dict:
    """الدول بعد الدمج المضبوط في الإعداد (merge: {الرمز: الرمز الذي يُضمّ إليه})."""
    raw = _load(str(MAPS_DIR / "countries.json"))
    merge = dict(cfg.path("reel.maps.merge", {}) or {})
    out: dict = {}
    for code, c in raw.items():
        if code in merge:
            continue
        out[code] = {**c, "rings": list(c["rings"])}
    for src, dst in merge.items():
        if src in raw and dst in out:
            out[dst]["rings"] += raw[src]["rings"]
            b, o = out[dst]["bbox"], raw[src]["bbox"]
            out[dst]["bbox"] = [min(b[0], o[0]), min(b[1], o[1]), max(b[2], o[2]), max(b[3], o[3])]
    return out


class Gazetteer:
    """فهرس الأسماء العربية المطبَّعة: المدن من Natural Earth وما يضيفه الإعداد (extra_places)، والدول بأسمائها وأسماء الإعداد البديلة."""

    def __init__(self, cfg):
        self.cfg = cfg
        mcfg = cfg.path("reel.maps", {}) or {}
        self.countries = countries(cfg)
        self.places: dict[str, list[dict]] = {}
        rows = list(_load(str(MAPS_DIR / "places.json")))
        rows += [{**p, "pop": int(p.get("pop", 0)), "extra": True} for p in mcfg.get("extra_places") or []]
        for p in rows:
            names = {p["ar"], *(p.get("aliases") or [])}
            # «مدينة الكويت»، «مدينة بروكسل»: الاسم بلا «مدينة» هو ما تكتبه الجملة
            names |= {n[len("مدينة "):] for n in names if n.startswith("مدينة ")}
            for n in names:
                self.places.setdefault(compact(n), []).append(p)
        self.country_names: dict[str, str] = {}
        aliases = mcfg.get("country_aliases") or {}
        for code, c in self.countries.items():
            for n in [c.get("ar"), *(aliases.get(code) or [])]:
                if n:
                    self.country_names.setdefault(compact(n), code)

    def _strip(self, name: str, index: dict) -> list[str]:
        """الاسم كما هو ثم بلا سابقة ملتصقة، ما دام الباقي في الفهرس (النموذج قد ينقل «وصنعاء» كما وردت)."""
        n = compact(name)
        out = [n]
        for p in _PREFIXES:
            if n.startswith(p) and len(n) > len(p) + 1:
                rest = n[len(p):]
                out += [rest, "ال" + rest] if p in ("لل",) else [rest]
        return [x for x in out if x in index]

    def country(self, name: str) -> str | None:
        hits = self._strip(name, self.country_names)
        return self.country_names[hits[0]] if hits else None

    def place(self, name: str, near: set[str] | None = None) -> tuple[dict | None, str]:
        """(المكان، السبب). اسم لمدن في دول مختلفة: يُختار ما في دولة مذكورة (near)، وإلا الأكبر إن فاق التالي بـambiguity_ratio
        مرة، وإلا لا شيء («طرابلس» في ليبيا ولبنان)."""
        hits = self._strip(name, self.places)
        if not hits:
            return None, "unknown"
        cands = sorted(self.places[hits[0]], key=lambda p: -int(p.get("pop", 0)))
        by_country: dict[str, dict] = {}
        for p in cands:
            by_country.setdefault(p.get("country", ""), p)
        if len(by_country) == 1:
            return cands[0], ""
        if near:
            inside = [p for c, p in by_country.items() if c in near]
            if len(inside) == 1:
                return inside[0], ""
        top = list(by_country.values())
        ratio = float(self.cfg.path("reel.maps.ambiguity_ratio", 5))
        if int(top[0].get("pop", 0)) >= ratio * max(int(top[1].get("pop", 0)), 1):
            return top[0], ""
        return None, "ambiguous"


_CACHE: dict = {}


def gazetteer(cfg) -> Gazetteer:
    """معجم واحد لكل كائن إعداد: بناؤه يقرأ آلاف المدن، والتركيب يطلبه لكل جملة."""
    hit = _CACHE.get(id(cfg))
    if hit is None or hit[0] is not cfg:
        hit = (cfg, Gazetteer(cfg))
        _CACHE[id(cfg)] = hit
    return hit[1]


# ───────────────────────────── التحقق من خطة الجملة ─────────────────────────────


def resolve(spec: Any, sentence: str, cfg) -> tuple[dict | None, str]:
    """يتحقق من خريطة جملة اقترحها النموذج ({places, countries, arrows}) ويحلّها إلى إحداثيات. يعيد (الخريطة، "") أو (None، السبب).
    كل اسم لا يرد في الجملة نفسها أو لا يعرفه المعجم يُسقط وحده ويُسجَّل في skipped، وكل سهم سقط أحد طرفيه يسقط معه؛ الخريطة
    تُرفض كلها فقط إن لم يبق شيء يُرسم أو تجاوزت السقوف. (اسم واحد خاطئ كان يُسقط الخريطة كلها: «مصر» لجملة تقول «الرئيس المصري»
    كانت تمحو بريطانيا والسعودية المذكورتين فعلًا.)"""
    if not isinstance(spec, dict):
        return None, "none"
    mcfg = cfg.path("reel.maps", {}) or {}
    g = gazetteer(cfg)
    names = [str(x).strip() for x in spec.get("places") or [] if str(x).strip()]
    cnames = [str(x).strip() for x in spec.get("countries") or [] if str(x).strip()]
    arrows = [a for a in spec.get("arrows") or [] if isinstance(a, dict)]
    for a in arrows:
        for k in ("from", "to"):
            v = str(a.get(k) or "").strip()
            if v and norm(v) not in {norm(n) for n in names}:
                names.append(v)     # طرف سهم لم يُذكر في الأماكن: يُضاف إليها ويُتحقق منه مثلها
    if not names and not cnames:
        return None, "none"
    if len(names) > int(mcfg.get("max_places", 4)) or len(cnames) > int(mcfg.get("max_countries", 3)) \
            or len(arrows) > int(mcfg.get("max_arrows", 2)):
        return None, "too_many"
    skipped: list[str] = []
    out_c: list[str] = []
    for n in cnames:
        if not mentioned(n, sentence):
            skipped.append(f"not_in_sentence:{n}")
            continue
        code = g.country(n)
        if code is None:
            skipped.append(f"unknown:{n}")
        elif code not in out_c:
            out_c.append(code)
    # دول الجملة كلها (لا ما سمّاه النموذج وحده) تحسم المدينة المتعددة: «طرابلس اللبنانية» أو «طرابلس» مع «لبنان»
    near = set(out_c) | {code for w, code in g.country_names.items() if mentioned(w, sentence)}
    out_p: list[dict] = []
    for n in names:
        if not mentioned(n, sentence):
            skipped.append(f"not_in_sentence:{n}")
            continue
        p, why = g.place(n, near)
        if p is None:
            # اسم دولة في قائمة الأماكن (النموذج خلط): يُعامل دولةً
            code = g.country(n)
            if code is None:
                skipped.append(f"{why}:{n}")
            elif code not in out_c:
                out_c.append(code)
            continue
        if all(q["key"] != norm(n) for q in out_p):
            out_p.append({"key": norm(n), "ar": n, "lon": float(p["lon"]), "lat": float(p["lat"]), "country": p.get("country", "")})
    keys = {q["key"]: q for q in out_p}
    out_a = []
    for a in arrows:
        f, t = keys.get(norm(str(a.get("from") or ""))), keys.get(norm(str(a.get("to") or "")))
        if f is None or t is None or f is t:
            skipped.append("bad_arrow")
            continue
        out_a.append({"from": f["key"], "to": t["key"]})
    if len(out_c) > int(mcfg.get("max_countries", 3)):
        return None, "too_many"
    if not out_p and not out_c:
        return None, skipped[0] if skipped else "none"
    return {"places": out_p, "countries": out_c, "arrows": out_a, "skipped": skipped}, ""


def detect(sentence: str, cfg) -> dict | None:
    """أماكن الجملة من المعجم في الكود، احتياطًا لخطة لم تقترح خريطة (ريل مفاوضات أبوظبي 12/11: جملة السياق تسمّي أبوظبي والخطة
    بلا خريطة). القاعدة نفسها: لا يُرسم إلا ما في نص الجملة وفي المعجم، وresolve يتحقق بعده كما يتحقق من اقتراح النموذج. المدن
    كلمات قد تكون عادية («العين»، «جدة»)، فلا تُقبل منها إلا العاصمة أو ما بلغ سكانه auto_detect.min_pop أو ما أضافه الإعداد
    (extra_places)؛ الدول بأسمائها لا بصفاتها («روسيا» لا «روسية»). الأطول أولًا ولا تداخل («أبو ظبي» لا «ظبي»)."""
    acfg = cfg.path("reel.maps.auto_detect", {}) or {}
    g = gazetteer(cfg)
    orig = re.sub(r"[^\w\s]", " ", str(sentence or "")).split()
    words = [norm(w) for w in orig]
    min_pop = int(acfg.get("min_pop", 1000000))
    places: list[str] = []
    cnames: list[str] = []
    used: set[int] = set()
    for size in (3, 2, 1):
        for i in range(len(words) - size + 1):
            if used & set(range(i, i + size)):
                continue
            text = " ".join(words[i:i + size])
            hits_c = g._strip(text, g.country_names)
            hits_p = g._strip(text, g.places)
            # الاسم المعروض: رسم المعجم («أبو ظبي») إن ورد في الجملة، وإلا كلمات الجملة نفسها كما كُتبت
            seen = " ".join(orig[i:i + size])
            if hits_c:
                canon = g.countries.get(g.country_names[hits_c[0]], {}).get("ar") or ""
                cnames.append(canon if canon and mentioned(canon, sentence) else seen)
            elif hits_p and any(p.get("capital") or p.get("extra") or int(p.get("pop", 0)) >= min_pop
                                for p in g.places[hits_p[0]]):
                canon = g.places[hits_p[0]][0].get("ar") or ""
                places.append(canon if canon and mentioned(canon, sentence) else seen)
            else:
                continue
            used |= set(range(i, i + size))
    if not places and not cnames:
        return None
    return {"places": places[:int(cfg.path("reel.maps.max_places", 4))],
            "countries": cnames[:int(cfg.path("reel.maps.max_countries", 3))], "auto": True}


def spec_for(entry: dict, sentence: str, role: str | None, cfg) -> Any:
    """خريطة جملة الخطة: ما اقترحه النموذج، وإلا ما يجده detect في جمل أدوار auto_detect.roles (السياق وحده افتراضيًا: الأسئلة لها
    بطاقتها، وجملة الراوي الأخرى قد تذكر دولة عابرة)."""
    if isinstance(entry, dict) and entry.get("map"):
        return entry["map"]
    acfg = cfg.path("reel.maps.auto_detect", {}) or {}
    if not acfg.get("enabled") or role not in (acfg.get("roles") or ["context"]):
        return None
    return detect(sentence, cfg)


def reason_text(code: str, cfg) -> str:
    """سبب رفض خريطة جملة بالعربية للمراجع؛ «not_in_sentence:صنعاء» ← نص السبب مع الاسم."""
    kind, _, name = str(code).partition(":")
    text = (cfg.path("reel.maps.reasons", {}) or {}).get(kind, kind)
    return f"{text}: {name}" if name else text


def summary(resolved: dict, cfg) -> str:
    """سطر عرض للمراجع: «صعدة ← صنعاء · اليمن»."""
    g = gazetteer(cfg)
    keys = {p["key"]: p["ar"] for p in resolved.get("places") or []}
    parts = [f"{keys[a['from']]} ← {keys[a['to']]}" for a in resolved.get("arrows") or []]
    in_arrows = {k for a in resolved.get("arrows") or [] for k in (a["from"], a["to"])}
    parts += [p["ar"] for p in resolved.get("places") or [] if p["key"] not in in_arrows]
    parts += [g.countries[c].get("ar", c) for c in resolved.get("countries") or [] if c in g.countries]
    return " · ".join(parts)


# ───────────────────────────── الإسقاط والكاميرا ─────────────────────────────


def merc(lon: float, lat: float) -> tuple[float, float]:
    lat = max(min(lat, 84.0), -84.0)
    return math.radians(lon), math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def camera(resolved: dict, cfg) -> dict:
    """مركز اللقطة النهائية (بوحدات مركاتور) ومقياسها (بكسل لكل وحدة) بحيث تقع الأماكن والدول داخل منطقة التركيز
    (focus) فوق نص الراوي. مدى الأماكن لا يقلّ عن min_span_deg (مدينة واحدة لا تُكبَّر إلى حيّ) ولا يزيد على max_span_deg."""
    mcfg = cfg.path("reel.maps")
    g = gazetteer(cfg)
    pts = [merc(p["lon"], p["lat"]) for p in resolved.get("places") or []]
    if pts:
        # الدول الملوَّنة مع الأماكن: نقطة تسمية كل دولة تدخل اللقطة كي يُقرأ اسمها («مضيق هرمز» وحده يُكبَّر حتى تختفي إيران والإمارات)
        for code in resolved.get("countries") or []:
            c = g.countries[code]
            lx, ly = merc(*c["label"])
            if abs(lx - pts[0][0]) < math.radians(float(mcfg["max_span_deg"])) / 2:
                pts.append((lx, ly))
    else:
        for code in resolved.get("countries") or []:
            b = main_box(g.countries[code], float(mcfg["max_span_deg"]))
            pts += [merc(b[0], b[1]), merc(b[2], b[3])]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    # مكان واحد بلا دولة ملوَّنة: مدى أوسع يُظهر ما حوله (الرياض وحدها بمدى 2.5° صحراء بلا معلم)
    lone = len(resolved.get("places") or []) == 1 and not resolved.get("countries")
    lo = math.radians(float(mcfg["single_span_deg"] if lone else mcfg["min_span_deg"]))
    hi = math.radians(float(mcfg["max_span_deg"]))
    pad = 1 + float(mcfg["pad"])
    w = min(max((max(xs) - min(xs)) * pad, lo), hi)
    h = min(max((max(ys) - min(ys)) * pad, lo), hi)
    f = mcfg["focus"]
    fw, fh = float(f["x1"]) - float(f["x0"]), float(f["y1"]) - float(f["y0"])
    return {"cx": cx, "cy": cy, "s": min(fw / w, fh / h),
            "fx": (float(f["x0"]) + float(f["x1"])) / 2, "fy": (float(f["y0"]) + float(f["y1"])) / 2}


def main_box(c: dict, max_span: float) -> list[float]:
    """إطار الدولة الذي يُعرض: حلقاتها القريبة من نقطة تسميتها وحدها. حدود فرنسا تشمل غويانا وجزرًا في المحيطات، وحدود
    الولايات المتحدة ألاسكا، فإطارها الكامل يعرض نصف العالم أو يُستبدل بنقطة فتُكبَّر الدولة حتى تملأ الشاشة."""
    lx, ly = c["label"]
    near = [r for r in c["rings"] if any(abs(x - lx) <= max_span / 2 and abs(y - ly) <= max_span / 2 for x, y in r)]
    rings = near or c["rings"]
    xs = [x for r in rings for x, _ in r]
    ys = [y for r in rings for _, y in r]
    b = [min(xs), min(ys), max(xs), max(ys)]
    if b[2] - b[0] > max_span:
        # ما زالت أعرض من السقف (روسيا): مربع حول نقطة التسمية بعرض السقف
        b = [lx - max_span / 2, max(ly - max_span / 4, -80), lx + max_span / 2, min(ly + max_span / 4, 80)]
    return b


def ease(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def timeline(n_places: int, n_arrows: int, seconds: float, cfg) -> dict:
    """أزمنة الحركة داخل مدة الجملة (دالة خالصة): الاقتراب، وظهور تلوين الدول، وظهور كل مكان، وامتداد كل سهم.
    السهم ينتهي قبل نهاية الجملة بـtail_seconds دائمًا، ولو قصرت الجملة فقصر زمنه."""
    m = cfg.path("reel.maps")
    zoom = min(float(m["zoom_seconds"]), max(seconds * 0.5, 0.3))
    marks = [float(m["marker_start"]) + k * float(m["marker_gap"]) for k in range(n_places)]
    start = float(m["arrow_start"])
    room = max(seconds - float(m["tail_seconds"]) - start, 0.3)
    each = min(float(m["arrow_seconds"]), room / max(n_arrows, 1))
    arrows = [(start + j * each, start + (j + 1) * each) for j in range(n_arrows)]
    settle = max([zoom, (marks[-1] + float(m["pop_seconds"])) if marks else 0.0, arrows[-1][1] if arrows else 0.0,
                  float(m["highlight_start"]) + float(m["highlight_seconds"])])
    return {"zoom": zoom, "marks": marks, "arrows": arrows, "settle": min(settle, seconds)}


# ───────────────────────────── الرسم ─────────────────────────────


def _hex(cfg, key: str) -> tuple[int, int, int]:
    return imaging.hex_rgb(cfg.path(f"reel.maps.colors.{key}"))


def _project(x: float, y: float, cam: dict, zoom: float) -> tuple[float, float]:
    """نقطة مركاتور ← بكسل الشاشة عند تكبير zoom (أكبر من 1 = أبعد)؛ التكبير حول مركز منطقة التركيز فتبقى الأماكن مكانها."""
    s = cam["s"] / zoom
    return cam["fx"] + (x - cam["cx"]) * s, cam["fy"] - (y - cam["cy"]) * s


def base_layers(resolved: dict, cam: dict, cfg) -> tuple[Image.Image, Image.Image]:
    """(الخريطة، الخريطة وعليها تلوين الدول المذكورة) بمقاس الشاشة × zoom_from، مرسومتين بضعف الدقة ثم مصغَّرتين (حواف ناعمة).
    كل إطار بعدها قصّ وتصغير منهما، فلا تُرسم حدود العالم إلا مرة واحدة للجملة."""
    r, m = cfg.path("reel.render"), cfg.path("reel.maps")
    z0 = float(m["zoom_from"])
    W, H = int(r["width"]), int(r["height"])
    ss = 2
    BW, BH = int(W * z0), int(H * z0)
    big = (BW * ss, BH * ss)
    sea, land, border, hl = _hex(cfg, "sea"), _hex(cfg, "land"), _hex(cfg, "border"), _hex(cfg, "highlight")
    g = gazetteer(cfg)

    def to_base(lon, lat):
        x, y = merc(lon, lat)
        # إحداثي الأساس: بكسل الشاشة عند z0 مضروبًا في z0 (الشاشة نافذة منه) ثم في ss
        X, Y = _project(x, y, cam, 1.0)
        return ((cam["fx"] * z0 + (X - cam["fx"])) * ss, (cam["fy"] * z0 + (Y - cam["fy"])) * ss)

    # حدود الرؤية بالدرجات تقريبًا لتخطّي الدول البعيدة (رسم العالم كله لكل جملة هدر)
    span_x = (BW / 2) / cam["s"]
    lon_lo, lon_hi = math.degrees(cam["cx"] - span_x * 1.2), math.degrees(cam["cx"] + span_x * 1.2)
    img = Image.new("RGB", big, sea)
    hi = Image.new("RGBA", big, (0, 0, 0, 0))
    d, dh = ImageDraw.Draw(img), ImageDraw.Draw(hi)
    alpha = int(255 * float(m["colors"].get("highlight_alpha", 0.45)))
    bw = max(1, int(float(m.get("border_width", 1.5)) * ss))
    for code, c in g.countries.items():
        b = c["bbox"]
        if b[2] < lon_lo or b[0] > lon_hi:
            continue
        for ring in c["rings"]:
            pts = [to_base(x, y) for x, y in ring]
            d.polygon(pts, fill=land)
            d.line(pts + [pts[0]], fill=border, width=bw)
            if code in (resolved.get("countries") or []):
                dh.polygon(pts, fill=hl + (alpha,))
                dh.line(pts + [pts[0]], fill=hl + (255,), width=bw * 2)
    base = img.resize((BW, BH), Image.LANCZOS)
    lit = Image.alpha_composite(img.convert("RGBA"), hi).convert("RGB").resize((BW, BH), Image.LANCZOS)
    return base, lit


def text_shade(cfg) -> Image.Image:
    """تدرّج كحلي من أسفل منطقة الأماكن إلى ما تحتها: نص الراوي يُقرأ فوق الخريطة دون تظليل الأماكن نفسها."""
    r, s = cfg.path("reel.render"), cfg.path("reel.maps.text_shade")
    W, H = int(r["width"]), int(r["height"])
    navy = imaging.hex_rgb(cfg.path("brand.primary_color"))
    y0, y1, a = int(s["from_y"]), int(s["to_y"]), float(s["alpha"])
    col = Image.new("L", (1, H), 0)
    for y in range(H):
        col.putpixel((0, y), int(255 * a * ease((y - y0) / max(y1 - y0, 1))))
    layer = Image.new("RGBA", (W, H), navy + (0,))
    layer.putalpha(col.resize((W, H)))
    return layer


def _label_font(cfg, text: str, size: int):
    from .reel_render import face
    path, weight = face(cfg, text, "display")
    return imaging.load_font(path, size, weight)


def _label(d: ImageDraw.ImageDraw, xy, text: str, font, fill, stroke, anchor: str = "mb") -> None:
    d.text(xy, imaging._prepare(text), font=font, fill=fill, anchor=anchor, stroke_width=max(2, font.size // 12),
           stroke_fill=stroke, **imaging._kwargs())


def _arrow_path(a: tuple, b: tuple, m) -> list[tuple[float, float]]:
    """مسار السهم المرسوم: يقف قبل علامة الوجهة وبعد علامة المنطلق كي يُرى رأسه ولا يختفي تحت الدائرتين."""
    clear = float(m["marker_radius"]) * 2.2
    return [q for q in _arrow_points(a, b, float(m["arrow_bend"]))
            if math.hypot(q[0] - b[0], q[1] - b[1]) > clear and math.hypot(q[0] - a[0], q[1] - a[1]) > clear * 0.6]


def _arrow_points(a: tuple, b: tuple, bend: float, n: int = 48) -> list[tuple[float, float]]:
    """منحنى تربيعي من a إلى b ينحني جانبًا بنسبة bend من طوله: السهم المستقيم يبدو خطًّا على الخريطة لا حركة."""
    (x0, y0), (x1, y1) = a, b
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    cx, cy = mx - dy * bend, my + dx * bend
    return [((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1)
            for t in (k / n for k in range(n + 1))]


def frame(resolved: dict, cam: dict, layers: tuple, shade: Image.Image, t: float, tl: dict, cfg) -> Image.Image:
    """إطار الخريطة عند الثانية t من الجملة."""
    r, m = cfg.path("reel.render"), cfg.path("reel.maps")
    W, H = int(r["width"]), int(r["height"])
    z0 = float(m["zoom_from"])
    z = z0 - (z0 - 1.0) * ease(t / tl["zoom"])
    base, lit = layers
    box = (cam["fx"] * z0 - cam["fx"] * z, cam["fy"] * z0 - cam["fy"] * z,
           cam["fx"] * z0 + (W - cam["fx"]) * z, cam["fy"] * z0 + (H - cam["fy"]) * z)
    k = ease((t - float(m["highlight_start"])) / float(m["highlight_seconds"])) if resolved.get("countries") else 0.0
    src = Image.blend(base, lit, k) if 0 < k < 1 else (lit if k >= 1 else base)
    img = src.resize((W, H), Image.BILINEAR, box=box).convert("RGBA")
    img = Image.alpha_composite(img, shade)
    d = ImageDraw.Draw(img)
    gold, white, navy = _hex(cfg, "highlight"), _hex(cfg, "text"), imaging.hex_rgb(cfg.path("brand.primary_color"))
    pos = {p["key"]: _project(*merc(p["lon"], p["lat"]), cam, z) for p in resolved.get("places") or []}
    # الدول الملوَّنة تُسمّى عند نقطة تسميتها حين تظهر في الإطار
    taken: list[tuple] = []     # صناديق الأسماء المرسومة: اسم يقع فوق آخر يُنقل إلى موضع بديل أو لا يُرسم
    rad = float(m["marker_radius"])
    lf = _label_font(cfg, "مكان", int(m["label_size"]))
    labels = {}
    # العلامات نفسها محجوزة قبل الأسماء: اسم مكان فوق علامة مكان آخر يخفيها
    marks = {key: (x - rad * 1.4, y - rad * 1.4, x + rad * 1.4, y + rad * 1.4) for key, (x, y) in pos.items()}
    # مسار كل سهم محجوز كاملًا (لا ما امتد منه حتى الآن) كي لا يقفز الاسم حين يصل السهم إليه، ولا يغطي الاسمُ رأس السهم
    aw = float(m["arrow_width"])
    for a in resolved.get("arrows") or []:
        for qx, qy in _arrow_path(pos[a["from"]], pos[a["to"]], m)[::3]:
            taken.append((qx - aw, qy - aw, qx + aw, qy + aw))
    small = _label_font(cfg, "مكان", int(int(m["label_size"]) * float(m.get("label_shrink", 0.8))))
    for key, (x, y) in pos.items():
        name = next(p["ar"] for p in resolved["places"] if p["key"] == key)
        # لا موضع بالحجم الكامل ← بحجم أصغر قبل التخلّي عن الاسم (أماكن متقاربة كجنوب لبنان وبعلبك)
        others = taken + [b for k2, b in marks.items() if k2 != key]
        spot = None
        for font in (lf, small):
            hit = _place_label(d, name, font, x, y, rad * 1.2, others, W)
            if hit is not None:
                taken.append(hit[2])
                spot = (hit[0], hit[1], font)
                break
        labels[key] = spot
    if k > 0:
        g = gazetteer(cfg)
        cf = _label_font(cfg, "دولة", int(m["country_label_size"]))
        for code in resolved.get("countries") or []:
            c = g.countries.get(code)
            if not c:
                continue
            x, y = _project(*merc(*c["label"]), cam, z)
            bb = d.textbbox((x, y), imaging._prepare(c.get("ar", "")), font=cf, anchor="mm", **imaging._kwargs())
            if any(_hit(bb, o) for o in taken) or any(math.hypot(x - px, y - py) < rad * 4 for px, py in pos.values()):
                continue
            taken.append(bb)
            if 0 < x < W and float(m["focus"]["y0"]) - 40 < y < float(m["text_shade"]["to_y"]):
                lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                _label(ImageDraw.Draw(lay), (x, y), c.get("ar", ""), cf, gold + (255,), navy + (255,), "mm")
                lay.putalpha(lay.getchannel("A").point(lambda v: int(v * k)))
                img = Image.alpha_composite(img, lay)
        d = ImageDraw.Draw(img)
    # الأسهم تحت العلامات
    width = int(m["arrow_width"])
    for (start, end), a in zip(tl["arrows"], resolved.get("arrows") or []):
        p = ease((t - start) / max(end - start, 1e-6))
        if p <= 0:
            continue
        pts = _arrow_path(pos[a["from"]], pos[a["to"]], m)
        if len(pts) < 2:
            continue
        cut = max(2, int(round(p * (len(pts) - 1))) + 1)
        line = pts[:cut]
        d.line(line, fill=navy + (255,), width=width + 8, joint="curve")
        d.line(line, fill=gold + (255,), width=width, joint="curve")
        (xa, ya), (xb, yb) = line[-2], line[-1]
        ang = math.atan2(yb - ya, xb - xa)
        hl = width * 2.6
        head = [(xb + math.cos(ang) * hl * 0.6, yb + math.sin(ang) * hl * 0.6),
                (xb + math.cos(ang + 2.5) * hl, yb + math.sin(ang + 2.5) * hl),
                (xb + math.cos(ang - 2.5) * hl, yb + math.sin(ang - 2.5) * hl)]
        d.polygon(head, fill=gold + (255,), outline=navy + (255,))
    # العلامات والأسماء
    for (key, (x, y)), t0 in zip(pos.items(), tl["marks"]):
        q = (t - t0) / float(m["pop_seconds"])
        if q <= 0:
            continue
        # انبثاق يتجاوز حجمه قليلًا ثم يستقر (ease-out-back)
        q = min(q, 1.0)
        c1 = 1.70158
        s = 1 + (c1 + 1) * (q - 1) ** 3 + c1 * (q - 1) ** 2
        rr = max(rad * s, 1.0)
        d.ellipse([x - rr - 5, y - rr - 5, x + rr + 5, y + rr + 5], fill=navy + (255,))
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=gold + (255,), outline=white + (255,), width=3)
        name = next(p["ar"] for p in resolved["places"] if p["key"] == key)
        spot = labels.get(key)
        if spot is not None:
            _label(d, spot[0], name, spot[2], white + (255,), navy + (255,), spot[1])
    return img.convert("RGB")


def _hit(a: tuple, b: tuple) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _place_label(d, name: str, font, x: float, y: float, gap: float, taken: list, width: int):
    """(موضع اسم المكان، مرساته، صندوقه): فوق علامته، وإلا تحتها، وإلا جانبيها أو قطريها؛ أول موضع لا يقع على ما في taken
    (أسماء سابقة وعلامات أخرى) ولا يخرج من الشاشة. لا موضع ← None (العلامة وحدها)؛ «بعلبك» فوق «جنوب لبنان» كان يمحو الاسمين معًا."""
    d2 = gap * 0.75
    for xy, anchor in (((x, y - gap), "mb"), ((x, y + gap), "mt"), ((x + gap, y), "lm"), ((x - gap, y), "rm"),
                       ((x + d2, y - d2), "lb"), ((x - d2, y - d2), "rb"), ((x + d2, y + d2), "lt"), ((x - d2, y + d2), "rt")):
        bb = d.textbbox(xy, imaging._prepare(name), font=font, anchor=anchor, **imaging._kwargs())
        pad = font.size // 6
        bb = (bb[0] - pad, bb[1] - pad, bb[2] + pad, bb[3] + pad)
        if bb[0] < 0 or bb[2] > width or any(_hit(bb, o) for o in taken):
            continue
        return xy, anchor, bb
    return None


def render(resolved: dict, seconds: float, cfg, tmp: Path, tag: str) -> list[tuple[Path, float]]:
    """إطارات الجملة [(png، مدة)]: إطار لكل 1/fps حتى تستقر الحركة، ثم آخر إطار ثابتًا لبقية المدة (لا هدر في رسم إطارات متطابقة)."""
    m = cfg.path("reel.maps")
    fps = float(m["fps"])
    cam = camera(resolved, cfg)
    tl = timeline(len(resolved.get("places") or []), len(resolved.get("arrows") or []), seconds, cfg)
    layers = base_layers(resolved, cam, cfg)
    shade = text_shade(cfg)
    n = max(1, int(math.ceil(tl["settle"] * fps)))
    out: list[tuple[Path, float]] = []
    step = 1.0 / fps
    for k in range(n + 1):
        t = min(k * step, tl["settle"])
        p = tmp / f"map_{tag}_{k:04d}.png"
        frame(resolved, cam, layers, shade, t, tl, cfg).save(p, compress_level=1)
        out.append((p, step))
    used = step * n
    out[-1] = (out[-1][0], max(seconds - used, step))
    return out
