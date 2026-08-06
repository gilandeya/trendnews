"""التعلّم من الرفض: أسبابك تُغذّي الفرز فتوفّر مالًا وتحسّن النتائج.

تقرير الأداء يتعلّم مما نُشر. هذه الوحدة تتعلّم مما **رُفض** — وهي إشارة
أثمن، لأنها تقول *لماذا* لا يصلح الخبر لا فقط أنه لم ينجح.

الاستخدام: في صفحة المراجعة، اكتب تعليقًا:

    /reject a1b2c3 محلي
    /reject d4e5f6 آخر: الصورة لا تمثّل الخبر

القاعدة الحاكمة: **يُطبَّق السبب حرفيًا ولا يُعمَّم**. رفض ثلاثة أخبار عن
الصين لسبب عارض لا يعني رفض أخبار الصين — والتعميم بلا إذن يفسد التغطية
من حيث يريد إصلاحها.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from .config import STATE_DIR

log = logging.getLogger(__name__)

REJECTIONS_FILE = STATE_DIR / "rejections.json"

# قائمة قصيرة موحّدة: تسهّل التحليل الإحصائي. وما خرج عنها يُكتب حرًا.
REASONS: dict[str, str] = {
    "محلي": "خبر محلي صرف لا يعني القارئ العربي",
    "قديم": "خبر قديم أو معاد تدويره",
    "ضعيف": "مصدر ضعيف أو غير موثوق",
    "مكرر": "نشرنا الحدث نفسه سابقًا",
    "ركيك": "صياغة عربية ركيكة أو غامضة",
    "صورة": "الصورة لا تمثّل الخبر",
    "تافه": "لا يستحق النشر",
    "حساس": "موضوع حساس لا يناسب الصفحة",
    "منحاز": "انحياز واضح في الرواية",
}

_CMD = re.compile(r"^\s*/reject\s+([0-9a-f]{4,16})\s+(.+?)\s*$",
                  re.MULTILINE | re.IGNORECASE)


def parse_rejections(body: str) -> list[tuple[str, str, str]]:
    """
    يستخرج أوامر الرفض من نص تعليق.

    يعيد [(معرّف المسودة، الوسم، النص الحر)].
    الوسم من القائمة إن طابق أول كلمة، وإلا "آخر" والنص كله حر.
    """
    found: list[tuple[str, str, str]] = []
    for draft_id, rest in _CMD.findall(body):
        rest = rest.strip()
        first = rest.split()[0].strip(":：،,") if rest else ""
        if first in REASONS:
            note = rest[len(first):].strip(" :：،,-")
            found.append((draft_id.lower(), first, note))
        else:
            found.append((draft_id.lower(), "آخر", rest))
    return found


# ──────────────────────────── التخزين ────────────────────────────


def load() -> list[dict]:
    if not REJECTIONS_FILE.exists():
        return []
    try:
        return json.loads(REJECTIONS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("ملف الرفض تالف — سيُعاد إنشاؤه")
        return []


def save(entries: list[dict], keep_days: int = 60) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    fresh = [
        e for e in entries
        if datetime.fromisoformat(e["at"]) >= cutoff
    ]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REJECTIONS_FILE.write_text(
        json.dumps(fresh, ensure_ascii=False, indent=1), encoding="utf-8")


def record(entries: list[dict], draft: dict, tag: str, note: str) -> None:
    entries.append({
        "id": draft.get("id", ""),
        "tag": tag,
        "note": note[:200],
        "title": (draft.get("arabic") or {}).get("post_title", "")[:120],
        "source_title": (draft.get("source") or {}).get("title", "")[:140],
        "publishers": (draft.get("source") or {}).get("publishers", [])[:3],
        "region": (draft.get("source") or {}).get("region", ""),
        "bucket": draft.get("bucket", ""),
        "at": datetime.now(timezone.utc).isoformat(),
    })


# ──────────────────────────── التغذية للفرز ────────────────────────────


def screening_guidance(entries: list[dict], limit: int = 12,
                       days: int = 21) -> str:
    """
    يحوّل أسبابك إلى تعليمات إضافية للفرز الأولي.

    ⚠️ القيد الحاكم: التعليمات تصف *ما رُفض بالضبط* ولا تستنتج قواعد
    أوسع. نمرّر عنوان الخبر المرفوض وسببه، ونأمر النموذج صراحةً بعدم
    التعميم — فرفض ثلاثة أخبار عن بلد لا يعني رفض ذلك البلد.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = [
        e for e in entries
        if datetime.fromisoformat(e["at"]) >= cutoff
    ][-limit:]
    if not recent:
        return ""

    lines = [
        "",
        "📌 أخبار رفضها المحرر سابقًا وأسبابه — استرشد بها في الفرز:",
        "",
    ]
    for e in recent:
        reason = REASONS.get(e["tag"], e["tag"])
        note = f" — {e['note']}" if e.get("note") else ""
        lines.append(f"• «{e['source_title']}» رُفض: {reason}{note}")

    lines += [
        "",
        "⚠️ حدود صارمة لاستخدام هذه القائمة:",
        "• استبعد ما يشبه هذه الأخبار **في سبب الرفض نفسه** فقط.",
        "• لا تعمّم على بلد أو مصدر أو موضوع لمجرد وروده هنا. رفض ثلاثة",
        "  أخبار عن بلد لا يعني رفض أخباره كلها — قد يكون السبب عارضًا.",
        "• إن شككتَ في انطباق السبب، مرّر الخبر. الاستبعاد الخاطئ يفقدنا",
        "  أخبارًا جيدة، ولا سبيل لاكتشافه لاحقًا.",
    ]
    return "\n".join(lines)


def summarise(entries: list[dict], days: int = 7) -> list[str]:
    """أنماط الرفض لعرضها في تقرير الأداء — للاطلاع لا للتطبيق التلقائي."""
    from collections import Counter

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = [e for e in entries
              if datetime.fromisoformat(e["at"]) >= cutoff]
    if not recent:
        return []

    out = [f"**{len(recent)} مسودة مرفوضة خلال {days} أيام**", ""]

    tags = Counter(e["tag"] for e in recent)
    out.append("| السبب | العدد |")
    out.append("|---|---|")
    for tag, count in tags.most_common():
        out.append(f"| {REASONS.get(tag, tag)} | {count} |")

    pubs = Counter(p for e in recent for p in e.get("publishers", []))
    repeat = [(p, c) for p, c in pubs.most_common(5) if c >= 3]
    if repeat:
        out += ["", "مصادر تكرر رفضها (قرارك وحدك بحذفها):"]
        out += [f"- {p}: {c} مرات" for p, c in repeat]

    regions = Counter(e["region"] for e in recent if e.get("region"))
    hot = [(r, c) for r, c in regions.most_common(3) if c >= 3]
    if hot:
        out += ["", "مناطق تكرر رفضها:"]
        out += [f"- {r}: {c} مرات" for r, c in hot]

    out += ["", "<sub>هذه أنماط للاطلاع فقط. البوت لا يحذف مصدرًا ولا يحجب "
            "منطقة تلقائيًا — القرار لك.</sub>"]
    return out
