"""مواضيع اليوم من عناوين الفيديوهات وأوصافها (خطة «المواضيع من الوصف»، الخطوة 3).

قرار صاحب المشروع (3/11): تُستنتج المواضيع من العنوان والوصف وحدهما قبل جلب أي نص، فلا يمرّ بالبروكسي إلا ما يُختار.
القياس (3/11) أعطى 75–85% من الفيديوهات الطويلة بعنوان ووصف يكفيان، وفهرسًا زمنيًا في 101 من 2545 فقط؛ فالدقائق
تقديرية: مدة الفيديو مقسومة على عدد مواضيعه (قرار صاحب المشروع)، ورصدکده خارج الترشيح (نشرات بلا وصف).

الخطوات: فيديوهات ملف القياس المؤهلة ← نداء Haiku بدفعات يعيد مواضيع كل فيديو ← نداء واحد يجمع المواضيع المتشابهة في
أحداث ← الكود يعدّ لكل حدث الكتل والتوجّهات والدقائق ويرتّب بها ويُبقي ما في كتلتين فأكثر. الحكم اللغوي (ما الحدث؟ هل
موضوعان حدث واحد؟) للنموذج، والعدّ والترتيب للكود.

**المرحلة الحالية معاينة فقط:** تُحفظ النتيجة في المستودع الخاص (عناوين القنوات كلامها) وتُطبع في سجل الجمع، ولا تُفتح
قضية ولا يتغير مسار الترشيح القائم.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import llm

log = logging.getLogger("meta_topics")

TOPICS_TOOL = {
    "name": "report_video_topics",
    "description": "مواضيع كل فيديو كما يفهمها قارئ من عنوانه ووصفه وحدهما.",
    "input_schema": {
        "type": "object",
        "properties": {
            "videos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "n": {"type": "integer"},
                        "political": {"type": "boolean"},
                        "topics": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["n", "political", "topics"],
                },
            },
        },
        "required": ["videos"],
    },
}

CATALOG_TOOL = {
    "name": "list_events",
    "description": "الأحداث المحددة التي تتناولها قناتان مختلفتان فأكثر.",
    "input_schema": {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}, "description": {"type": "string"}},
                    "required": ["title", "description"],
                },
            },
        },
        "required": ["events"],
    },
}

ASSIGN_TOOL = {
    "name": "assign_topics",
    "description": "رقم الحدث الذي يتناوله كل موضوع، أو 0 إن لم يتناول أيًّا منها.",
    "input_schema": {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"n": {"type": "integer"}, "event": {"type": "integer"}},
                    "required": ["n", "event"],
                },
            },
        },
        "required": ["rows"],
    },
}


MERGE_TOOL = {
    "name": "merge_events",
    "description": "مجموعات أرقام الأحداث التي هي زوايا من القصة نفسها؛ كل مجموعة رقمان فأكثر، والحدث الذي لا شريك له لا يُذكر.",
    "input_schema": {
        "type": "object",
        "properties": {
            "groups": {
                "type": "array",
                "items": {"type": "object", "properties": {"events": {"type": "array", "items": {"type": "integer"}}},
                          "required": ["events"]},
            },
        },
        "required": ["groups"],
    },
}


def _mcfg(cfg) -> dict:
    return cfg.path("youtube.meta_topics") or {}


def clean_description(desc: str, repeated: set[str], max_chars: int, drop_chapters: bool = False) -> str:
    """الوصف بلا الروابط والوسوم وبلا السطور التي تتكرر في فيديوهات القناة (قوالب الاشتراك): القياس وجد وصف CNN Türk
    والقناة 14 قالبًا ثابتًا يملأ ألف حرف لا يقول شيئًا عن الحلقة."""
    keep = []
    for line in (desc or "").splitlines():
        s = line.strip()
        if not s or s in repeated or re.search(r"https?://|➤|◄", s) or s.startswith("#"):
            continue
        # الفهرس يُرسل وحده (chapter_lines) فلا يُعدّ من حدّ الوصف ولا يتكرر
        if drop_chapters and _is_chapter_line(s):
            continue
        keep.append(s)
    return " ".join(keep)[:max_chars]


def _is_chapter_line(line: str) -> bool:
    from .youtube_meta_probe import _CHAPTER_RE
    m = _CHAPTER_RE.match(line)
    return bool(m and m.group(2).strip())


def chapter_lines(chapters: list[dict], cfg) -> list[str]:
    """فصول الفهرس الزمني كما تُرسل للنموذج: «12:30 عنوان»، كل عنوان مقصوص إلى `chapter_title_chars` وحتى `max_chapters` فصلًا.

    السبب: قياس 11/11 وجد 450 من 733 فصلًا (61%) لا تصل النموذج لأن الوصف يُقصّ عند 600 حرف والفهرس يأتي بعد فقرة
    التعريف، فيضيع موضوع ذكرته القناة صراحة وقد يكون هو التقاطع الذي يجعل الحدث مشتركًا."""
    m = _mcfg(cfg)
    width = int(m.get("chapter_title_chars", 80))
    out = []
    for c in (chapters or [])[: int(m.get("max_chapters", 30))]:
        t = str(c.get("title") or "").strip()[:width]
        if not t:
            continue
        sec = int(c.get("start") or 0)
        h, rem = divmod(sec, 3600)
        stamp = f"{h}:{rem // 60:02d}:{rem % 60:02d}" if h else f"{rem // 60}:{rem % 60:02d}"
        out.append(f"{stamp} {t}")
    return out


def topics_cap(v: dict, cfg) -> int:
    """سقف مواضيع الفيديو: لفيديو بفهرس موضوع لكل فصل سياسي حتى `max_topics_with_chapters`، وإلا `max_topics_per_video`.
    السبب: 62 فيديو في 11/11 فهرسها أكثر من 5 فصول ونشرة بعشر قضايا كانت لا تُدخل إلا أربعًا."""
    m = _mcfg(cfg)
    base = int(m.get("max_topics_per_video", 4))
    if v.get("chapter_lines"):
        return max(base, int(m.get("max_topics_with_chapters", 10)))
    return base


def eligible_videos(videos: dict, cfg, now: datetime) -> list[dict]:
    """الفيديوهات الطويلة غير المباشرة من القنوات المشمولة ضمن النافذة، بوصف منظّف. القناة المستبعدة من الترشيح
    (`exclude_channels`) وقناة غير نشطة لا تدخل، وأنماط الاستبعاد في القناة تُطبَّق على العنوان كما في الجمع."""
    m = _mcfg(cfg)
    channels = {c.get("name"): c for c in cfg.get("channels", []) if c.get("active", True)}
    excluded = set(m.get("exclude_channels") or [])
    cutoff = now - timedelta(hours=float(m.get("window_hours", 36)))
    by_channel: dict[str, list] = {}
    for vid, v in (videos or {}).items():
        ch = channels.get(v.get("channel"))
        if not ch or v.get("channel") in excluded or v.get("live"):
            continue
        if (v.get("duration_seconds") or 0) < int(m.get("min_seconds", 600)):
            continue
        try:
            when = datetime.fromisoformat(str(v.get("published", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < cutoff:
            continue
        title = v.get("title") or ""
        if any(p.lower() in title.lower() for p in ch.get("exclude_patterns") or []):
            continue
        by_channel.setdefault(v["channel"], []).append({**v, "video_id": vid})
    out = []
    for ch_name, vs in by_channel.items():
        lines = Counter(l.strip() for v in vs for l in set((v.get("description") or "").splitlines()) if l.strip())
        repeated = {l for l, n in lines.items() if n >= int(m.get("repeated_lines", 3))}
        for v in vs:
            v["chapter_lines"] = chapter_lines(v.get("chapters") or [], cfg)
            v["desc_clean"] = clean_description(v.get("description", ""), repeated, int(m.get("max_desc_chars", 600)),
                                                drop_chapters=bool(v["chapter_lines"]))
            v["orientation"] = v.get("orientation") or channels[ch_name].get("orientation")
            out.append(v)
    out.sort(key=lambda v: (v["channel"], v.get("published") or ""))
    return out


def _tool_input(resp, name):
    return next((b.input for b in getattr(resp, "content", []) or []
                 if getattr(b, "type", "") == "tool_use" and getattr(b, "name", name) == name), None)



def _rows(data: dict, key: str) -> list[dict]:
    """قائمة صفوف أداة النموذج بأمان: قد تصل القائمة نصًا JSON (درس #1741) أو مغلَّفة بمفتاحها، وقد يحوي النص بقايا بعده.

    السبب: تشغيل 4/11 بعد دمج الخطوتين انتهى بـ«'str' object has no attribute 'get'» فلم يخرج شيء؛ عنصر غير قاموس يُهمل لا يُسقط النداء."""
    val = (data or {}).get(key)
    if isinstance(val, str):
        txt = val.strip()
        try:
            val = json.JSONDecoder().raw_decode(txt[txt.find("[") if "[" in txt else 0:])[0] if txt else []
        except ValueError:
            val = []
    if isinstance(val, dict):
        val = val.get(key) or []
    return [r for r in val if isinstance(r, dict)] if isinstance(val, list) else []


def _int(x):
    """رقم صف قد يصل نصًا («3»)؛ غيره None."""
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, str) and x.strip().isdigit():
        return int(x.strip())
    return None

def _topics_batch(batch: list[dict], cfg, client, m: dict) -> tuple[dict[int, dict] | None, str | None]:
    """نداء واحد لدفعة ← {رقم: صف}؛ None مع السبب عند العطل أو الرد المقطوع (لا يُقبل منه شيء، درس #1763)."""
    lines = []
    for k, v in enumerate(batch):
        line = (f"[{k}] {v['channel']} ({v.get('language')}) · {round((v.get('duration_seconds') or 0) / 60)} د\n"
                f"العنوان: {v.get('title', '')}\nالوصف: {v.get('desc_clean', '')}")
        if v.get("chapter_lines"):
            line += "\nالفهرس:\n" + "\n".join(v["chapter_lines"])
        lines.append(line)
    system = (m.get("topics_system", "").replace("{max_topics}", str(int(m.get("max_topics_per_video", 4))))
              .replace("{max_chapter_topics}", str(int(m.get("max_topics_with_chapters", 10)))))
    try:
        resp = llm.create(client, cfg=cfg, model=m.get("topics_model", "haiku"),
                          max_tokens=int(m.get("topics_max_tokens", 4000)),
                          system=system, tools=[TOPICS_TOOL],
                          tool_choice={"type": "tool", "name": TOPICS_TOOL["name"]},
                          messages=[{"role": "user", "content": "\n\n".join(lines)}])
    except Exception as exc:  # noqa: BLE001 — دفعة متعطلة لا توقف الباقي
        return None, str(exc)[:120]
    if getattr(resp, "stop_reason", None) == "max_tokens":
        return None, "رد مقطوع"
    data = _tool_input(resp, TOPICS_TOOL["name"]) or {}
    rows = {}
    for row in _rows(data, "videos"):
        n = _int(row.get("n"))
        if isinstance(n, int) and 0 <= n < len(batch) and n not in rows:
            rows[n] = row
    return rows, None


def video_topics(videos: list[dict], cfg, client, info: dict | None = None) -> tuple[dict[str, list[str]], list[str]]:
    """{video_id: [مواضيع]} لكل فيديو سياسي بنداء Haiku لكل دفعة، و`info["verdicts"]` حكم كل فيديو (political/not/missing).

    فيديو لم يرد له صف في رد دفعته يُسأل عنه مرة ثانية في دفعة أصغر (`retry_batch_size`): تشغيل 4/11 أسقط الفيديوهات
    الفارسية الخمسة عشر كلها من دفعة أعادت صفوف جيرانها، فغابت الكتلة الفارسية عن كل حدث. ولا إعادة ثالثة."""
    m = _mcfg(cfg)
    info = info if info is not None else {}
    out: dict[str, list[str]] = {}
    verdicts: dict[str, str] = {}
    errors: list[str] = []

    def apply(batch, rows):
        missing = []
        for k, v in enumerate(batch):
            row = rows.get(k)
            if row is None:
                missing.append(v)
                continue
            topics = [str(t).strip() for t in row.get("topics") or [] if str(t).strip()][:topics_cap(v, cfg)]
            if row.get("political") and topics:
                out[v["video_id"]] = topics
                verdicts[v["video_id"]] = "political"
            else:
                verdicts[v["video_id"]] = "not"
        return missing

    pending: list[dict] = []
    size = int(m.get("batch_size", 20))
    for i in range(0, len(videos), size):
        batch = videos[i:i + size]
        rows, err = _topics_batch(batch, cfg, client, m)
        if rows is None:
            errors.append(f"دفعة {i // size + 1}: {err}")
            pending += batch
            continue
        pending += apply(batch, rows)
    info["retried"] = len(pending)
    rsize = int(m.get("retry_batch_size", 8))
    for i in range(0, len(pending), rsize):
        batch = pending[i:i + rsize]
        rows, err = _topics_batch(batch, cfg, client, m)
        if rows is None:
            errors.append(f"إعادة {i // rsize + 1}: {err}")
            continue
        apply(batch, rows)
    for v in videos:
        verdicts.setdefault(v["video_id"], "missing")
    info["verdicts"] = verdicts
    return out, errors


def _assign_batch(batch: list[tuple[int, dict]], catalog: list[dict], cfg, client, m: dict,
                  depth: int = 0) -> tuple[dict[int, int], list[str]]:
    """{رقم الموضوع العام: رقم الحدث} لدفعة؛ الرد المقطوع يُقسم نصفين (حتى `assign_max_splits`) ولا يُقبل منه شيء (درس #1763)."""
    events = "\n".join(f"{j}. {e['title']} — {e['description']}" for j, e in enumerate(catalog, 1))
    lines = "\n".join(f"[{k}] {it['label']} — {it['channel']}" for k, (_, it) in enumerate(batch))
    try:
        resp = llm.create(client, cfg=cfg, model=m.get("assign_model", "haiku"),
                          max_tokens=int(m.get("assign_max_tokens", 4000)), system=m.get("assign_system", ""),
                          tools=[ASSIGN_TOOL], tool_choice={"type": "tool", "name": ASSIGN_TOOL["name"]},
                          messages=[{"role": "user", "content": f"الأحداث:\n{events}\n\nالمواضيع:\n{lines}"}])
    except Exception as exc:  # noqa: BLE001
        return {}, [str(exc)[:120]]
    if getattr(resp, "stop_reason", None) == "max_tokens":
        if len(batch) > 1 and depth < int(m.get("assign_max_splits", 2)):
            half = len(batch) // 2
            a, ea = _assign_batch(batch[:half], catalog, cfg, client, m, depth + 1)
            b, eb = _assign_batch(batch[half:], catalog, cfg, client, m, depth + 1)
            return {**a, **b}, ea + eb
        return {}, ["رد مقطوع"]
    data = _tool_input(resp, ASSIGN_TOOL["name"]) or {}
    out: dict[int, int] = {}
    for row in _rows(data, "rows"):
        n, ev = _int(row.get("n")), _int(row.get("event"))
        if isinstance(n, int) and 0 <= n < len(batch) and isinstance(ev, int) and 1 <= ev <= len(catalog):
            out[batch[n][0]] = ev - 1
    return out, []


def merge_catalog(catalog: list[dict], cfg, client, info: dict) -> list[dict]:
    """يضمّ الأحداث التي هي زوايا من القصة نفسها إلى أولها بنداء رخيص واحد، قبل الإسناد.

    السبب (4/11): بعد تعليمة «زوايا القصة حدث واحد» ما زال التسمية يُخرج «فوز الديمقراطيين» و«خسارة ترامب» و«التصويت المبكر» بجانب
    «الانتخابات النصفية»، فتمتلئ العشرة الأولى بقصة واحدة. الحكم لغوي فهو للنموذج، والكود يتحقق: أرقام في المدى، لا رقم في مجموعتين،
    والمجموعة رقمان فأكثر. المدموج يبقى بعنوان أولها (الأوسع، لأن التسمية مرتّبة بالانتشار) وتُذكر زواياه في وصفه كي يراها الإسناد.
    العطل أو الرد المقطوع ← القائمة كما هي."""
    m = _mcfg(cfg)
    if not m.get("merge_enabled", True) or len(catalog) < 2:
        return catalog
    # القائمة قبل الدمج تُحفظ للتشخيص: بعده لا يُعرف ما الذي ضُمّ إلا من سطر الدمج
    info["catalog"] = [dict(e) for e in catalog]
    lines = [f"{j + 1}. {e['title']} — {e['description']}" for j, e in enumerate(catalog)]
    try:
        resp = llm.create(client, cfg=cfg, model=m.get("merge_model", "haiku"),
                          max_tokens=int(m.get("merge_max_tokens", 2000)), system=m.get("merge_system", ""),
                          tools=[MERGE_TOOL], tool_choice={"type": "tool", "name": MERGE_TOOL["name"]},
                          messages=[{"role": "user", "content": "\n".join(lines)}])
    except Exception as exc:  # noqa: BLE001 — الدمج تحسين لا شرط
        info["merge_error"] = str(exc)[:150]
        return catalog
    if getattr(resp, "stop_reason", None) == "max_tokens":
        info["merge_error"] = "رد مقطوع"
        return catalog
    data = _tool_input(resp, MERGE_TOOL["name"]) or {}
    used: set[int] = set()
    groups: list[list[int]] = []
    for row in _rows(data, "groups"):
        idx = []
        for x in row.get("events") or []:
            n = _int(x)
            if n is not None and 1 <= n <= len(catalog) and (n - 1) not in used and (n - 1) not in idx:
                idx.append(n - 1)
        if len(idx) >= 2:
            idx.sort()
            used.update(idx)
            groups.append(idx)
    if not groups:
        info["merged"] = []
        return catalog
    head = {g[0]: g for g in groups}
    out = []
    for j, e in enumerate(catalog):
        if j in used and j not in head:
            continue
        if j in head:
            angles = "، ".join(catalog[k]["title"] for k in head[j][1:])
            e = {"title": e["title"], "description": f"{e['description']} · زواياه: {angles}".strip(" ·")}
        out.append(e)
    info["merged"] = [[catalog[k]["title"] for k in g] for g in groups]
    return out


def group_topics(items: list[dict], cfg, client) -> tuple[list[dict], str | None, dict]:
    """خطوتان: نداء قوي واحد يسمّي الأحداث المشتركة (مخرج قصير)، ثم نداءات رخيصة بدفعات تسند كل موضوع إلى حدث منها.

    السبب: نداء واحد يقسم كل المواضيع أعطى في ثلاث تشغيلات للبيانات نفسها تقريبًا (4/11) 3 أحداث ثم 16 ثم حدثًا واحدًا — أكثر من
    400 موضوع بأربع لغات أكبر من أن يُقسَم في رد واحد بثبات. تسمية الأحداث وحدها قصيرة، والإسناد تصنيف لكل موضوع يحتمل الدفعات."""
    m = _mcfg(cfg)
    info: dict = {}
    if not items:
        return [], None, info
    lines = [f"[{k}] {it['label']} — {it['channel']} ({it.get('bloc')})" for k, it in enumerate(items)]
    system = str(m.get("group_system", "")).replace("{max_events}", str(m.get("group_max_events", 30)))
    try:
        resp = llm.create(client, cfg=cfg, model=m.get("group_model", "claude-sonnet-5"),
                          max_tokens=int(m.get("group_max_tokens", 8000)), system=system,
                          tools=[CATALOG_TOOL], tool_choice={"type": "tool", "name": CATALOG_TOOL["name"]},
                          messages=[{"role": "user", "content": "\n".join(lines)}])
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)[:150], info
    info["stop_reason"] = getattr(resp, "stop_reason", None)
    if info["stop_reason"] == "max_tokens":
        return [], "رد مقطوع", info
    data = _tool_input(resp, CATALOG_TOOL["name"]) or {}
    catalog = [{"title": str(e.get("title", "")).strip(), "description": str(e.get("description", "")).strip()}
               for e in _rows(data, "events") if str(e.get("title", "")).strip()]
    catalog = catalog[: int(m.get("group_max_events", 30))]
    info["returned"] = len(catalog)
    if not catalog:
        return [], None, info
    catalog = merge_catalog(catalog, cfg, client, info)
    size = int(m.get("assign_batch_size", 50))
    indexed = list(enumerate(items))
    assigned: dict[int, int] = {}
    errors: list[str] = []
    for i in range(0, len(indexed), size):
        got, errs = _assign_batch(indexed[i:i + size], catalog, cfg, client, m)
        assigned.update(got)
        errors += [f"إسناد {i // size + 1}: {e}" for e in errs]
    info["grouped"] = len(assigned)
    info["assign_errors"] = errors
    events = []
    for j, ev in enumerate(catalog):
        members = sorted(k for k, e in assigned.items() if e == j)
        if members:
            events.append({"title": ev["title"], "members": members})
    return events, ("؛ ".join(errors) if errors else None), info


def score_events(events: list[dict], items: list[dict], cfg, keep_all: bool = False) -> list[dict]:
    """لكل حدث: الكتل المختلفة، والتوجّهات المختلفة (زوج كتلة/توجّه، فقناتان بالتوجّه نفسه صوت واحد)، والدقائق
    التقديرية (مدة الفيديو ÷ عدد مواضيعه)، والفيديوهات. يُبقي ما بلغ `min_blocs` ويرتّب بالكتل ثم التوجّهات ثم الدقائق
    (ترتيب صاحب المشروع)، والفيديو الواحد لا يُعدّ مرتين في الحدث."""
    m = _mcfg(cfg)
    out = []
    for ev in events:
        seen: set[str] = set()
        blocs, orients, channels, minutes, videos = set(), set(), set(), 0.0, []
        for i in ev["members"]:
            it = items[i]
            if it["video_id"] in seen:
                continue
            seen.add(it["video_id"])
            blocs.add(it["bloc"])
            orients.add((it["bloc"], it.get("orientation") or it["channel"]))
            channels.add(it["channel"])
            minutes += it["minutes"]
            videos.append({k: it[k] for k in ("video_id", "channel", "bloc", "orientation", "title", "minutes")})
        out.append({"title": ev["title"], "blocs": sorted(blocs), "orientations": len(orients),
                    "channels": sorted(channels), "minutes": round(minutes), "videos": videos})
    if keep_all:
        return out
    out = [e for e in out if len(e["blocs"]) >= int(m.get("min_blocs", 2))]
    out.sort(key=lambda e: (-len(e["blocs"]), -e["orientations"], -e["minutes"]))
    return out[: int(m.get("max_topics", 10))]


def run(cfg, now: datetime | None = None, client=None, videos: dict | None = None) -> dict:
    """من ملف القياس لليوم إلى أحداث مرتّبة. لا يرفع: العطل في `errors`."""
    now = now or datetime.now(timezone.utc)
    if videos is None:
        from . import youtube_meta_probe
        path = youtube_meta_probe.probe_dir() / f"{now.strftime('%Y-%m-%d')}.json"
        try:
            videos = json.loads(path.read_text(encoding="utf-8")).get("videos") or {}
        except (OSError, ValueError):
            videos = {}
    if client is None:
        from anthropic import Anthropic
        from .config import env
        client = Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    vids = eligible_videos(videos, cfg, now)
    tinfo: dict = {}
    topics, errors = video_topics(vids, cfg, client, tinfo)
    items = []
    for v in vids:
        labels = topics.get(v["video_id"]) or []
        for label in labels:
            items.append({"label": label, "video_id": v["video_id"], "channel": v["channel"], "bloc": v.get("bloc"),
                          "orientation": v.get("orientation"), "title": v.get("title", ""),
                          "minutes": (v.get("duration_seconds") or 0) / 60 / len(labels)})
    events, gerr, ginfo = group_topics(items, cfg, client)
    if gerr:
        errors.append(f"التجميع: {gerr}")
    ranked = score_events(events, items, cfg)
    # للتشخيص في الملف الخاص: كل الأحداث بأعدادها (لا الفائزة وحدها) وكل موضوع بفيديوه، كي يُفهم ما فعله التجميع
    every = [{k: e[k] for k in ("title", "blocs", "orientations", "channels", "minutes")} | {"videos": len(e["videos"])}
             for e in score_events(events, items, cfg, keep_all=True)]
    return {"generated_at": now.isoformat(), "eligible": len(vids), "political": len(topics),
            "topics": len(items), "events": len(events), "grouped": ginfo.get("grouped", 0), "group": ginfo,
            "retried": tinfo.get("retried", 0), "missing": sum(1 for x in tinfo.get("verdicts", {}).values() if x == "missing"),
            "verdicts": tinfo.get("verdicts", {}),
            # للتشخيص: كم فصلًا من فهرس كل فيديو أُرسل إلى النموذج (فيظهر أي ضياع لاحق)
            "chapters_sent": {v["video_id"]: len(v["chapter_lines"]) for v in vids if v.get("chapter_lines")},
            "ranked": ranked, "all_events": every,
            "labels": [{k: it[k] for k in ("label", "video_id", "channel")} for it in items], "errors": errors}


def preview_lines(res: dict, cfg) -> list[str]:
    """سطور السجل: رقم الحدث وعنوانه، ثم «N كتل، M توجهات، X دقيقة (تقديرية)» بصيغة صاحب المشروع."""
    t = _mcfg(cfg).get("texts") or {}
    lines = [t.get("summary", "مواضيع من الوصف: {eligible} فيديو، {political} سياسي، {grouped} من {topics} موضوعًا في {events} حدثًا · أُعيد {retried} وبقي بلا حكم {missing}").format(**res)]
    for k, e in enumerate(res["ranked"], 1):
        lines.append(t.get("line", "{k}- {title}: {blocs} كتل، {orientations} توجهات، {minutes} دقيقة (تقديرية)").format(
            k=k, title=e["title"], blocs=len(e["blocs"]), orientations=e["orientations"], minutes=e["minutes"]))
    # الدمج يُرى في السجل كي يُراجَع: دمج خاطئ لقصتين مختلفتين يُكتشف من هنا لا من غياب حدث
    for g in (res.get("group") or {}).get("merged") or []:
        lines.append(t.get("merged_line", "🔗 دُمج في «{head}»: {rest}").format(head=g[0], rest="، ".join(g[1:])))
    lines += [f"⚠️ {x}" for x in res.get("errors") or []]
    return lines


def preview_safe(cfg) -> None:
    """غلاف الجمع: معاينة فقط، تُحفظ في المستودع الخاص وتُطبع، ولا ترفع أبدًا."""
    if not _mcfg(cfg).get("preview"):
        return
    try:
        res = run(cfg)
        from . import youtube_transcripts
        path = youtube_transcripts.bites_dir() / "meta_topics" / f"{res['generated_at'][:10]}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\n".join(preview_lines(res, cfg)))
    except Exception as exc:  # noqa: BLE001
        # موضع العطل في السطر نفسه: عطل 4/11 لم يذكر أين وقع فلم يُعرف إلا بالتخمين
        tb = exc.__traceback__
        while tb and tb.tb_next:
            tb = tb.tb_next
        where = f" ({tb.tb_frame.f_code.co_name}:{tb.tb_lineno})" if tb else ""
        print(f"مواضيع من الوصف: تعذّر — {str(exc)[:150]}{where}")



# ───────────── قضية الترشيح (الخطوة 3ب) ─────────────
# تُفتح من youtube-articles (يقرأ المستودع الخاص وله صلاحية فتح القضايا) لا من الجمع (لا صلاحية له)، وتُحفظ نسخة مختصرة
# من المواضيع في المستودع العام (state/meta_topics) لأن الاعتماد يجري في publish.yml الذي لا يدفع المستودع الخاص؛ النسخة
# العامة بلا عناوين الفيديوهات ولا أوصافها (كلام قنوات) — عنوان الحدث بالعربية ومعرّفات الفيديو والقنوات والدقائق وحدها.


MTOPIC_RE = re.compile(r"^\s*-\s*\[([ xX])\][^\n]*?<!--\s*mtopic:([0-9a-f]+)\s*-->", re.MULTILINE)
DATE_RE = re.compile(r"<!--\s*meta-date:(\d{4}-\d{2}-\d{2})\s*-->")


def public_dir() -> Path:
    from .config import STATE_DIR
    return Path(STATE_DIR) / "meta_topics"


def topic_id(date: str, title: str) -> str:
    return hashlib.sha1(f"{date}:{title}".encode("utf-8")).hexdigest()[:12]


def slim(res: dict, date: str) -> dict:
    """النسخة العامة: لكل حدث معرّف ثابت وما يُعرض في القضية، بلا نص من القنوات."""
    topics = []
    for e in res.get("ranked") or []:
        topics.append({"id": topic_id(date, e["title"]), "title": e["title"], "blocs": e["blocs"],
                       "orientations": e["orientations"], "minutes": e["minutes"], "channels": e["channels"],
                       "videos": [{k: v.get(k) for k in ("video_id", "channel", "bloc", "orientation", "minutes")}
                                  for v in e.get("videos") or []]})
    return {"date": date, "generated_at": res.get("generated_at"), "topics": topics}


def _bloc_names(blocs, cfg) -> str:
    # أسماء الكتل بالعربية في القضية (لا «arabic، israeli»)، من الجدول نفسه الذي تقرؤه قضايا التحليل
    from .youtube_cluster import _bloc_label
    return "، ".join(_bloc_label(b, cfg) for b in blocs)


def _fmt_minutes(m) -> str:
    return str(round(m or 0))


def selection_body(data: dict, cfg) -> str:
    t = _mcfg(cfg).get("texts") or {}
    lines = [t.get("selection_header", "## 🧭 مواضيع اليوم من عناوين الفيديوهات وأوصافها"),
             "", t.get("selection_explainer", ""), "", f"<!-- meta-date:{data['date']} -->", ""]
    for k, e in enumerate(data["topics"], 1):
        lines.append(f"- [ ] **{k}. {e['title']}** <!-- mtopic:{e['id']} -->")
        lines.append("  " + t.get("selection_meta", "{blocs} كتل ({bloc_names})، {orientations} توجهات، {minutes} دقيقة (تقديرية)").format(
            blocs=len(e["blocs"]), bloc_names=_bloc_names(e["blocs"], cfg), orientations=e["orientations"],
            minutes=_fmt_minutes(e["minutes"])))
        vids = " · ".join(f"[{v['channel']} {_fmt_minutes(v['minutes'])} د](https://youtu.be/{v['video_id']})"
                          for v in e["videos"])
        lines.append(f"  <details><summary>{len(e['videos'])} فيديو</summary>\n\n  {vids}\n  </details>")
        lines.append("")
    lines.append(t.get("selection_footer", "وسم `approved` = فتح قضية مستقلة لكل موضوع معلَّم."))
    return "\n".join(lines)


def _load_public(date: str) -> dict | None:
    try:
        return json.loads((public_dir() / f"{date}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save_public(data: dict) -> None:
    path = public_dir() / f"{data['date']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def open_selection(cfg, date: str) -> dict | None:
    """من ملف اليوم الخاص إلى قضية ترشيح `meta-selection`. لا ترفع: مطفأ أو بلا مواضيع أو قضية مفتوحة لليوم ← None."""
    m = _mcfg(cfg)
    if not m.get("enabled"):
        return None
    try:
        from . import review, youtube_transcripts
        existing = _load_public(date)
        if existing and existing.get("selection_issue"):
            return None
        path = youtube_transcripts.bites_dir() / "meta_topics" / f"{date}.json"
        res = json.loads(path.read_text(encoding="utf-8"))
        data = slim(res, date)
        if not data["topics"]:
            return None
        t = m.get("texts") or {}
        issue = review.create_issue(t.get("selection_title", "🧭 مواضيع اليوم — {date}").format(date=date),
                                    selection_body(data, cfg), labels=[m.get("selection_label", "meta-selection")])
        data["selection_issue"] = issue["number"]
        _save_public(data)
        return issue
    except Exception as exc:  # noqa: BLE001 — الترشيح القديم يبقى، فعطل هذا لا يوقف العنقدة
        log.warning("مواضيع من الوصف: تعذّر فتح قضية الترشيح — %s", str(exc)[:150])
        return None


def topic_body(topic: dict, data: dict, cfg) -> str:
    t = _mcfg(cfg).get("texts") or {}
    lines = [f"## 🎬 {topic['title']}", "", f"<!-- mtopic-issue:{topic['id']} -->", f"<!-- meta-date:{data['date']} -->", "",
             t.get("selection_meta", "").format(blocs=len(topic["blocs"]), bloc_names=_bloc_names(topic["blocs"], cfg),
                                                 orientations=topic["orientations"], minutes=_fmt_minutes(topic["minutes"])),
             ""]
    for v in topic["videos"]:
        lines.append(f"- [{v['channel']}](https://youtu.be/{v['video_id']}) · {v.get('orientation') or ''} · "
                     f"{_fmt_minutes(v['minutes'])} د")
    lines += ["", t.get("topic_pending", "⏳ تُجلب نصوص هذه الفيديوهات وتُستخرج الأسئلة والإجابات في الخطوة التالية.")]
    return "\n".join(lines)


def finalize(issue_number: int, body: str, cfg) -> int:
    """اعتماد قضية الترشيح: قضية مستقلة لكل موضوع معلَّم (مرة واحدة لكل موضوع)، وتعليق بروابطها، ثم إغلاق القضية."""
    from . import review
    m = _mcfg(cfg)
    t = m.get("texts") or {}
    date_m = DATE_RE.search(body or "")
    data = _load_public(date_m.group(1)) if date_m else None
    if not data:
        review.comment(issue_number, t.get("finalize_missing", "⚠️ لم أجد ملف مواضيع هذه القضية."))
        return 1
    marked = [tid for mark, tid in MTOPIC_RE.findall(body) if mark.lower() == "x"]
    by_id = {e["id"]: e for e in data["topics"]}
    lines = []
    opened = False
    for tid in marked:
        topic = by_id.get(tid)
        if not topic:
            continue
        if not topic.get("topic_issue"):
            issue = review.create_issue(t.get("topic_title", "🎬 {title}").format(title=topic["title"]),
                                        topic_body(topic, data, cfg), labels=[m.get("topic_label", "meta-topic")])
            topic["topic_issue"] = issue["number"]
            # وقت طلب الاستخراج: به يميّز meta_script.qa_in_flight «لم تُحفظ النتيجة بعد» من «لم يُطلب أو ضاع الطلب»
            topic["qa_requested_at"] = datetime.now(timezone.utc).isoformat()
            opened = True
        lines.append(f"- {topic['title']} ← #{topic['topic_issue']}")
    _save_public(data)
    review.comment(issue_number, "\n".join([t.get("finalize_header", "فُتحت قضية لكل موضوع:")] + lines) if lines
                   else t.get("finalize_none", "لم يُعلَّم موضوع — لا شيء يُفتح."))
    review.close_issue(issue_number)
    if opened and (m.get("qa") or {}).get("enabled"):
        request_qa_run(issue_number, cfg)
    return 0


def request_qa_run(issue_number: int, cfg) -> None:
    """الأسئلة تُستخرج في تشغيلة تركيب الريل (فيها البروكسي والمستودع الخاص). بوجود ملف الإطلاق (W5) يُطلق بعد إيداع
    النسخة العامة التي فيها رقم قضية الموضوع، وإلا يُطلق الآن؛ العطل تعليق لا استثناء."""
    import os

    from . import publish, review
    path = os.environ.get(publish.RENDER_DISPATCH_ENV)
    if path:
        data = publish._read_dispatch_file(path)
        data.update(meta_issue=issue_number)
        Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return
    publish.dispatch_qa(issue_number, cfg)
