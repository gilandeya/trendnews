"""دفتر كلفة التشغيلة: كل نداء Claude وGemini والصوت وبحث الويب وبايتات البروكسي يُجمع هنا، فتُعرف كلفة كل ريل بمراحله.

السبب: لا يعرف صاحب المشروع ثمن الريل الواحد؛ الكلفة متفرقة بين وحدات كثيرة (Opus للسيناريو وحكم الإجابات، Haiku للفحوص والشريط،
Gemini للمقاطع والقائلين، Google للصوت، والبروكسي لتنزيل المقاطع). الدفتر عالمي للعملية كـwriter.USAGE، والمرحلة تأخذ لقطة قبلها
وتحفظ الفرق (`stage`)؛ نقطة تغذية Claude الوحيدة writer.record_usage (ومنه llm.create)، وهي لا تحسب الرد نفسه مرتين.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from typing import Any

LEDGER: dict = {"claude": {}, "gemini": 0.0, "tts": 0.0, "web_search": 0, "proxy_bytes": 0}
_SEEN_IDS: set[int] = set()


def reset() -> None:
    LEDGER.clear()
    LEDGER.update({"claude": {}, "gemini": 0.0, "tts": 0.0, "web_search": 0, "proxy_bytes": 0})


def first_time(resp) -> bool:
    """True أول مرة يُرى فيها الرد: llm.create يسجّله، ووحدات قديمة تعيد record_usage على الرد نفسه بعده فلا يُحسب مرتين.
    المقارنة بـ«is True» لا بالصدق: MagicMock يعيد كائنًا صادقًا لأي سمة."""
    if getattr(resp, "_cost_recorded", None) is True:
        return False
    try:
        resp._cost_recorded = True
        return True
    except Exception:  # noqa: BLE001 — كائن لا يقبل سمة جديدة: هويته بديلًا
        if id(resp) in _SEEN_IDS:
            return False
        _SEEN_IDS.add(id(resp))
        return True


def add_claude(model: str, usd: float) -> None:
    c = LEDGER["claude"]
    c[model] = c.get(model, 0.0) + float(usd)


def add(kind: str, amount) -> None:
    """gemini/tts بالدولار، web_search بالعدد، proxy_bytes بالبايت. لا يرفع: الدفتر إخبار لا شرط لأي خطوة."""
    try:
        LEDGER[kind] = LEDGER.get(kind, 0) + (amount or 0)
    except Exception:  # noqa: BLE001
        pass


def snapshot() -> dict:
    return copy.deepcopy(LEDGER)


def delta(before: dict, after: dict | None = None) -> dict:
    """الفرق بين لقطتين بشكل الدفتر نفسه، بلا الصفري."""
    after = after if after is not None else LEDGER
    out: dict = {}
    claude = {m: round(v - before.get("claude", {}).get(m, 0.0), 5) for m, v in after.get("claude", {}).items()}
    claude = {m: v for m, v in claude.items() if v > 0}
    if claude:
        out["claude"] = claude
    for k in ("gemini", "tts", "web_search", "proxy_bytes"):
        v = (after.get(k) or 0) - (before.get(k) or 0)
        if v:
            out[k] = round(v, 5) if isinstance(v, float) else v
    return out


def merge(*parts: dict | None) -> dict:
    """يجمع عدة فروق (مراحل أو محاولات) في واحد."""
    out: dict = {}
    for p in parts:
        if not isinstance(p, dict):
            continue
        for m, v in (p.get("claude") or {}).items():
            out.setdefault("claude", {})[m] = round(out.get("claude", {}).get(m, 0.0) + float(v), 5)
        for k in ("gemini", "tts", "web_search", "proxy_bytes"):
            if p.get(k):
                out[k] = (out.get(k) or 0) + p[k]
    return out


def _family(model: str) -> str:
    m = (model or "").lower()
    for name in ("opus", "sonnet", "haiku"):
        if name in m:
            return name.capitalize()
    return model or "Claude"


def usd(d: dict | None, cfg: Any) -> float:
    """مجموع الدولار: Claude وGemini والصوت، وبحث الويب بسعره، والبروكسي بسعره إن عُرف (وإلا لا يدخل المجموع)."""
    d = d or {}
    total = sum(float(v) for v in (d.get("claude") or {}).values()) + float(d.get("gemini") or 0) + float(d.get("tts") or 0)
    total += (d.get("web_search") or 0) * float(cfg.path("costs.web_search_usd_per_1000", 0) or 0) / 1000
    per_gb = cfg.path("costs.proxy_usd_per_gb")
    if per_gb:
        total += (d.get("proxy_bytes") or 0) / 1e9 * float(per_gb)
    return total


def parts_text(d: dict | None, cfg: Any) -> str:
    """«Opus 0.52$ · Haiku 0.03$ · Gemini 0.11$ · صوت 0.02$ · بحث 3 · بروكسي 46 MB» — بنود الفرق بالترتيب الأغلى أولًا لعائلات Claude."""
    d = d or {}
    fam: dict[str, float] = {}
    for m, v in (d.get("claude") or {}).items():
        fam[_family(m)] = fam.get(_family(m), 0.0) + float(v)
    t = cfg.path("costs.texts", {}) or {}
    items = [f"{name} {v:.2f}$" for name, v in sorted(fam.items(), key=lambda kv: -kv[1])]
    if d.get("gemini"):
        items.append(f"Gemini {float(d['gemini']):.2f}$")
    if d.get("tts"):
        items.append(f"{t.get('tts', 'صوت')} {float(d['tts']):.2f}$")
    if d.get("web_search"):
        items.append(f"{t.get('web_search', 'بحث ويب')} {int(d['web_search'])}")
    if d.get("proxy_bytes"):
        items.append(f"{t.get('proxy', 'بروكسي')} {d['proxy_bytes'] / 1e6:.0f} MB")
    return " · ".join(items)


def draft_stages(draft: dict) -> dict:
    """مراحل كلفة مسودة ريل: qa (مقاطع موضوع العناوين وأسئلته) · script · render (مجموع كل محاولات التركيب)."""
    out = {}
    if isinstance(draft.get("cost_qa"), dict):
        out["qa"] = draft["cost_qa"]
    if isinstance(draft.get("cost_script"), dict):
        out["script"] = draft["cost_script"]
    renders = [r for r in draft.get("cost_renders") or [] if isinstance(r, dict)]
    if renders:
        out["render"] = merge(*renders)
    return out


def draft_total(draft: dict, cfg: Any) -> float | None:
    stages = draft_stages(draft)
    return usd(merge(*stages.values()), cfg) if stages else None


def reel_line(draft: dict, cfg: Any) -> str:
    """سطر الكلفة الواحد لتعليق التركيب وجسم قضية المراجعة؛ فارغ إن لم تُسجَّل كلفة."""
    stages = draft_stages(draft)
    if not stages:
        return ""
    t = cfg.path("costs.texts", {}) or {}
    names = t.get("stages", {}) or {}
    renders = len([r for r in draft.get("cost_renders") or [] if isinstance(r, dict)])
    by_stage = []
    for k in ("qa", "script", "render"):
        if k in stages:
            label = names.get(k, k)
            if k == "render" and renders > 1:
                label += " " + t.get("attempts", "({n} محاولات)").format(n=renders)
            by_stage.append(f"{label} {usd(stages[k], cfg):.2f}$")
    total = merge(*stages.values())
    tpl = t.get("line", "💵 كلفة الريل: {total}$ — {stages} ({parts})")
    line = tpl.format(total=f"{usd(total, cfg):.2f}", stages=" · ".join(by_stage), parts=parts_text(total, cfg))
    if total.get("proxy_bytes") and not cfg.path("costs.proxy_usd_per_gb"):
        line += t.get("proxy_unpriced", "")
    return line


@contextmanager
def stage(out: dict, key: str):
    """يحفظ في out[key] فرق الدفتر خلال الكتلة، نجحت أو رفعت. الفارغ لا يُكتب."""
    before = snapshot()
    try:
        yield
    finally:
        d = delta(before)
        if d:
            out[key] = d
