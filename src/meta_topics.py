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

import json
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

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

GROUP_TOOL = {
    "name": "group_topics",
    "description": "تجميع المواضيع التي تتناول الحدث نفسه.",
    "input_schema": {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "members": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": ["title", "members"],
                },
            },
        },
        "required": ["events"],
    },
}


def _mcfg(cfg) -> dict:
    return cfg.path("youtube.meta_topics") or {}


def clean_description(desc: str, repeated: set[str], max_chars: int) -> str:
    """الوصف بلا الروابط والوسوم وبلا السطور التي تتكرر في فيديوهات القناة (قوالب الاشتراك): القياس وجد وصف CNN Türk
    والقناة 14 قالبًا ثابتًا يملأ ألف حرف لا يقول شيئًا عن الحلقة."""
    keep = []
    for line in (desc or "").splitlines():
        s = line.strip()
        if not s or s in repeated or re.search(r"https?://|➤|◄", s) or s.startswith("#"):
            continue
        keep.append(s)
    return " ".join(keep)[:max_chars]


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
            v["desc_clean"] = clean_description(v.get("description", ""), repeated, int(m.get("max_desc_chars", 600)))
            v["orientation"] = v.get("orientation") or channels[ch_name].get("orientation")
            out.append(v)
    out.sort(key=lambda v: (v["channel"], v.get("published") or ""))
    return out


def _tool_input(resp, name):
    return next((b.input for b in getattr(resp, "content", []) or []
                 if getattr(b, "type", "") == "tool_use" and getattr(b, "name", name) == name), None)


def _topics_batch(batch: list[dict], cfg, client, m: dict) -> tuple[dict[int, dict] | None, str | None]:
    """نداء واحد لدفعة ← {رقم: صف}؛ None مع السبب عند العطل أو الرد المقطوع (لا يُقبل منه شيء، درس #1763)."""
    lines = [f"[{k}] {v['channel']} ({v.get('language')}) · {round((v.get('duration_seconds') or 0) / 60)} د\n"
             f"العنوان: {v.get('title', '')}\nالوصف: {v.get('desc_clean', '')}" for k, v in enumerate(batch)]
    try:
        resp = llm.create(client, cfg=cfg, model=m.get("topics_model", "haiku"),
                          max_tokens=int(m.get("topics_max_tokens", 4000)),
                          system=m.get("topics_system", ""), tools=[TOPICS_TOOL],
                          tool_choice={"type": "tool", "name": TOPICS_TOOL["name"]},
                          messages=[{"role": "user", "content": "\n\n".join(lines)}])
    except Exception as exc:  # noqa: BLE001 — دفعة متعطلة لا توقف الباقي
        return None, str(exc)[:120]
    if getattr(resp, "stop_reason", None) == "max_tokens":
        return None, "رد مقطوع"
    data = _tool_input(resp, TOPICS_TOOL["name"]) or {}
    rows = {}
    for row in data.get("videos") or []:
        n = row.get("n")
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
    max_topics = int(m.get("max_topics_per_video", 4))

    def apply(batch, rows):
        missing = []
        for k, v in enumerate(batch):
            row = rows.get(k)
            if row is None:
                missing.append(v)
                continue
            topics = [str(t).strip() for t in row.get("topics") or [] if str(t).strip()][:max_topics]
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


def group_topics(items: list[dict], cfg, client) -> tuple[list[dict], str | None, dict]:
    """نداء واحد يجمع المواضيع (عبر الفيديوهات واللغات) في أحداث. يقبل الكود العضو المعروف مرة واحدة فقط.

    لا يُطلب تقسيم كل المواضيع: أول تشغيل حقيقي (4/11) أعطى 436 موضوعًا فأعاد النموذج 3 أحداث فقط حين طُلب منه أن يجعل
    كل موضوع منفرد حدثًا وحده (مخرج بمئات الأحداث يتركه). الترشيح لا يحتاج إلا الأحداث المشتركة بين قناتين فأكثر، فهي وحدها
    المطلوبة بسقف `group_max_events`، والكود يعدّ ما بقي بلا حدث للتشخيص."""
    m = _mcfg(cfg)
    info: dict = {}
    if not items:
        return [], None, info
    lines = [f"[{k}] {it['label']} — {it['channel']} ({it.get('bloc')})" for k, it in enumerate(items)]
    system = str(m.get("group_system", "")).replace("{max_events}", str(m.get("group_max_events", 30)))
    try:
        resp = llm.create(client, cfg=cfg, model=m.get("group_model", "claude-sonnet-5"),
                          max_tokens=int(m.get("group_max_tokens", 8000)), system=system,
                          tools=[GROUP_TOOL], tool_choice={"type": "tool", "name": GROUP_TOOL["name"]},
                          messages=[{"role": "user", "content": "\n".join(lines)}])
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)[:150], info
    info["stop_reason"] = getattr(resp, "stop_reason", None)
    if info["stop_reason"] == "max_tokens":
        return [], "رد مقطوع", info
    data = _tool_input(resp, GROUP_TOOL["name"]) or {}
    used: set[int] = set()
    events = []
    for ev in data.get("events") or []:
        members = [i for i in ev.get("members") or [] if isinstance(i, int) and 0 <= i < len(items) and i not in used]
        used.update(members)
        if members and str(ev.get("title", "")).strip():
            events.append({"title": str(ev["title"]).strip(), "members": members})
    info["returned"] = len(data.get("events") or [])
    info["grouped"] = len(used)
    return events, None, info


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
            "ranked": ranked, "all_events": every,
            "labels": [{k: it[k] for k in ("label", "video_id", "channel")} for it in items], "errors": errors}


def preview_lines(res: dict, cfg) -> list[str]:
    """سطور السجل: رقم الحدث وعنوانه، ثم «N كتل، M توجهات، X دقيقة (تقديرية)» بصيغة صاحب المشروع."""
    t = _mcfg(cfg).get("texts") or {}
    lines = [t.get("summary", "مواضيع من الوصف: {eligible} فيديو، {political} سياسي، {grouped} من {topics} موضوعًا في {events} حدثًا · أُعيد {retried} وبقي بلا حكم {missing}").format(**res)]
    for k, e in enumerate(res["ranked"], 1):
        lines.append(t.get("line", "{k}- {title}: {blocs} كتل، {orientations} توجهات، {minutes} دقيقة (تقديرية)").format(
            k=k, title=e["title"], blocs=len(e["blocs"]), orientations=e["orientations"], minutes=e["minutes"]))
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
        print(f"مواضيع من الوصف: تعذّر — {str(exc)[:150]}")

