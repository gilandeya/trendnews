"""صيغة الأشهر الموحَّدة «أكتوبر/تشرين الأول» (Issue #1345).

كل مسار يصوغ نصه بنموذج مستقل فيخرج الشهر بثلاث صيغ («تشرين الأول/أكتوبر» و«أكتوبر» وحده و«مارس/آذار»)،
ويظهر الاختلاف للقارئ بين منشورين متجاورين. يُطبَّق هنا مرة واحدة عند الحفظ فقط (store.save_draft/
update_draft) على حقول names نفسها، فلا يحتاج أي كاتب نص إلى استدعائه ولا يستطيع أي مسار تجاوزه.

القواعد (كلها استبدال نصي، لا تطبيع آخر):
- «شامي/ميلادي» (بمسافات حول / أو بدونها) ← «ميلادي/شامي»؛ و«ميلادي/شامي» يبقى.
- اسم شهر منفرد ← «ميلادي/شامي» فقط إن جاوره رقم (يوم قبله أو سنة بعده): «مارس» فعلٌ أيضًا فلا يُمسّ بلا رقم.
- لا يُمسّ شيء داخل « » أو " " أو “ ”: الاقتباس الحرفي يجب أن يطابق مصدره.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from . import names

log = logging.getLogger(__name__)

# حرف عربي قبل الاسم أو بعده يعني أنه جزء من كلمة أخرى («كتاب» ليست «آب»)
_AR = "ء-ي"
_QUOTED_RE = re.compile(r"(«[^»]*»|\"[^\"]*\"|“[^”]*”)")
_DAY_BEFORE_RE = re.compile(r"\d{1,2}\s*$")
_YEAR_AFTER_RE = re.compile(r"^\s*\d{4}")


def _pairs(cfg: Any) -> list[tuple[str, str]]:
    raw = cfg.path("date_style.months") if hasattr(cfg, "path") else None
    out = []
    for p in raw or []:
        if isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(x, str) and x for x in p):
            out.append((p[0], p[1]))
    return out


def _enabled(cfg: Any) -> bool:
    return bool(cfg.path("date_style.enabled")) if hasattr(cfg, "path") else False


def _fix_plain(text: str, pairs: list[tuple[str, str]]) -> str:
    greg_to_lev = {g: l for g, l in pairs}
    lev_to_greg: dict[str, str] = {}
    for g, l in pairs:
        lev_to_greg.setdefault(l, g)       # نيسان ← أول ميلادي مذكور (أبريل)
    valid = set(pairs)
    all_names = sorted(set(greg_to_lev) | set(lev_to_greg), key=len, reverse=True)
    alt = "|".join(re.escape(n) for n in all_names)
    pat = re.compile(rf"(?<![{_AR}])(?P<a>{alt})(?:\s*/\s*(?P<b>{alt}))?(?![{_AR}])")

    def sub(m: re.Match) -> str:
        a, b = m.group("a"), m.group("b")
        if b:
            if (a, b) in valid:
                return m.group(0)            # الترتيب الصحيح أصلًا: يبقى كما كُتب
            if (b, a) in valid:
                return f"{b}/{a}"            # «شامي/ميلادي» ← «ميلادي/شامي»
            return m.group(0)
        before, after = text[:m.start()], text[m.end():]
        if not (_DAY_BEFORE_RE.search(before) or _YEAR_AFTER_RE.search(after)):
            return m.group(0)                # بلا رقم مجاور لا يُمسّ («مارس الضغط»)
        g = a if a in greg_to_lev else lev_to_greg[a]
        l = greg_to_lev.get(g, a)
        return f"{g}/{l}"

    return pat.sub(sub, text)


def normalize_text(text: str, cfg: Any) -> str:
    """يوحّد صيغة الأشهر في نص واحد؛ خارج الاقتباسات وحدها. معطَّلًا أو بلا أزواج ← النص كما هو."""
    if not isinstance(text, str) or not text or not _enabled(cfg):
        return text
    pairs = _pairs(cfg)
    if not pairs:
        return text
    parts = _QUOTED_RE.split(text)
    # الأجزاء ذات الفهرس الفردي هي الاقتباسات (split بمجموعة التقاط)؛ الرقم المجاور يُقرأ داخل الجزء نفسه فقط
    return "".join(p if i % 2 else _fix_plain(p, pairs) for i, p in enumerate(parts))


def normalize_draft(draft: dict, cfg: Any) -> dict:
    """يطبّق normalize_text على حقول names نفسها (arabic.* المعتمدة وcaption وheadlines) في مكانه.
    لا يرفع أبدًا: حفظ المسودة أهمّ من توحيد صيغة شهر."""
    try:
        arabic = draft.get("arabic")
        if isinstance(arabic, dict):
            for key in names._ARABIC_TEXT_FIELDS:
                if isinstance(arabic.get(key), str):
                    arabic[key] = normalize_text(arabic[key], cfg)
        if isinstance(draft.get("caption"), str):
            draft["caption"] = normalize_text(draft["caption"], cfg)
        heads = draft.get("headlines")
        if isinstance(heads, list):
            draft["headlines"] = [normalize_text(h, cfg) if isinstance(h, str) else h for h in heads]
    except Exception as exc:  # noqa: BLE001 — توحيد شكلي لا يوقف حفظ مسودة
        log.warning("تعذّر توحيد صيغة الأشهر: %s", exc)
    return draft
