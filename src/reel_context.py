"""إعادة بناء السياق في التركيب حين يسقط أحد مقاطعه (ريل 1647a40f7337، 28/11).

الحادثة: سقط مقطع سائق الشاحنة الأول في التركيب (لم يطابق مسموعه كلامه المكتوب) فبقي تمهيده «سائق شاحنة إيراني يقارن ما دفعه
العام الماضي بما يدفعه اليوم» يُقرأ بلا مقطع بعده، ثم «ويشكو سائق شاحنة إيراني آخر…» يمهّد لمقطع لا «أول» قبله. السياق كُتب
متصلًا حول مقاطعه (beats)، فحذف مقطع وحده يكسر الكلام. هنا يُعاد كتابة كلام السياق كله على المقاطع الباقية وحدها قبل توليد أي
صوت، بنداء واحد على ما كتبه الكاتب نفسه (لا وقائع جديدة)، ويبقى ترتيب المقاطع وفهارس المشاهد كما هي: النص الجديد يُكتب في أول
مشهد راوٍ من كل فراغ بين مقطعين باقيين، وما زاد من مشاهد الراوي يُحذف (يعود فهرسه في dead)، فلا يتغير مفتاح clips ولا
render_crops. الفشل لا يُسقط التركيب: يبقى السياق كما كان بسطر ⚠️.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

REBUILD_TOOL = {
    "name": "rebuild_context",
    "description": "كلام السياق بعد إعادة بنائه: جزء لكل فراغ بترتيبه.",
    "input_schema": {
        "type": "object",
        "properties": {
            "parts": {"type": "array", "items": {"type": "string"},
                      "description": "نص كل فراغ بترتيبه؛ الفراغ المعلَّم «يُترك فارغًا» نصه \"\"."},
        },
        "required": ["parts"],
    },
}


def _rcfg(cfg) -> dict:
    return cfg.path("reel.render.context_rebuild") or {}


def _words(text: str) -> list[str]:
    return " ".join(str(text or "").split()).split()


def context_layout(script: dict, clips: dict) -> dict | None:
    """تخطيط قسم السياق (دالة خالصة): مشاهده من بعد بطاقة العنوان إلى أول مشهد ليس سياقًا. يعيد None إن لم يسقط منه مقطع، وإلا
    {scenes, kept, lost, gaps}: kept فهارس المقاطع الباقية بترتيبها، lost الساقطة، gaps لكل فراغ (قبل أول باقٍ، بين كل باقيين، بعد
    آخر باقٍ) فهارس مشاهد الراوي فيه. فراغ بلا مشهد راوٍ لا يأخذ كلامًا (لا مشهد يُضاف كي لا تتغير الفهارس)."""
    scenes = script.get("scenes") or []
    sect: list[int] = []
    started = False
    for i, sc in enumerate(scenes):
        if sc.get("role") == "context" and sc.get("kind") in ("narration", "clip"):
            sect.append(i)
            started = True
        elif started:
            break
    clip_idx = [i for i in sect if scenes[i].get("kind") == "clip"]
    lost = [i for i in clip_idx if i not in clips]
    if not lost:
        return None
    kept = [i for i in clip_idx if i in clips]
    gaps: list[list[int]] = [[] for _ in range(len(kept) + 1)]
    g = 0
    for i in sect:
        if scenes[i].get("kind") == "clip":
            if i in clips:
                g += 1
            continue
        gaps[g].append(i)
    return {"scenes": sect, "kept": kept, "lost": lost, "gaps": gaps}


def _speaker(sc: dict) -> str:
    return " ".join(str(sc.get("speaker_name") or "").split()) if sc.get("speaker_verified") else ""


def _clip_line(sc: dict) -> str:
    who = _speaker(sc) or "متحدث غير مسمّى"
    role = f" — {sc['speaker_role']}" if sc.get("speaker_role") and _speaker(sc) else ""
    return f"{who}{role} ({sc.get('channel_display', '')}): «{sc.get('quote_arabic', '')}»"


def _next_question(script: dict, after: int) -> str:
    for sc in (script.get("scenes") or [])[after + 1:]:
        if sc.get("kind") == "narration" and sc.get("role") == "question":
            return str(sc.get("text") or "")
    return ""


def message(script: dict, lay: dict) -> str:
    scenes = script["scenes"]
    lines = [f"سؤال الريل: {script.get('title', '')}", "", "السياق كما كُتب (بترتيبه):"]
    for i in lay["scenes"]:
        sc = scenes[i]
        if sc.get("kind") == "narration":
            lines.append(f"- راوٍ: {sc.get('text', '')}")
        elif i in lay["lost"]:
            lines.append(f"- مقطع سقط ولن يُعرض: {_clip_line(sc)}")
        else:
            lines.append(f"- مقطع {lay['kept'].index(i) + 1}: {_clip_line(sc)}")
    lines += ["", f"المقاطع الباقية: {len(lay['kept'])}. اكتب {len(lay['gaps'])} أجزاء بترتيبها:"]
    for g, slots in enumerate(lay["gaps"]):
        where = ("قبل المقطع 1" if g == 0 and lay["kept"] else f"بين المقطع {g} والمقطع {g + 1}"
                 if g < len(lay["kept"]) else ("بعد المقطع الأخير" if lay["kept"] else "السياق كله"))
        lines.append(f"{g + 1}) {where}" + ("" if slots else " — يُترك فارغًا (لا مكان له)"))
    q = _next_question(script, lay["scenes"][-1])
    if q:
        lines += ["", f"أول سؤال بعد السياق (آخر جزء يمهّد له): {q}"]
    return "\n".join(lines)


def problems(parts: list, lay: dict, script: dict, cfg) -> list[str]:
    """ما يرفضه الكود من الرد (دالة خالصة): عدد الأجزاء، وفراغ بلا مكان كُتب له كلام، وسياق صار فارغًا، وتمهيد مقطع مسمّى لا يسمّي
    قائله (قاعدة meta_script.speaker_problems نفسها)."""
    from . import reel_figures
    out: list[str] = []
    if len(parts) != len(lay["gaps"]):
        return [f"عدد الأجزاء {len(parts)} والمطلوب {len(lay['gaps'])}"]
    for g, (text, slots) in enumerate(zip(parts, lay["gaps"])):
        if _words(text) and not slots:
            out.append(f"الجزء {g + 1} لا مكان له ويجب أن يُترك فارغًا")
    if not any(_words(p) for p, s in zip(parts, lay["gaps"]) if s):
        out.append("السياق صار فارغًا")
    for k, i in enumerate(lay["kept"]):
        name = _speaker(script["scenes"][i])
        text = " ".join(_words(parts[k]))
        if name and text and not reel_figures.name_in_sentence(name, text, cfg):
            out.append(f"تمهيد المقطع {k + 1} لا يسمّي قائله «{name}»")
    return out


def _ask(client, cfg, system: str, messages: list[dict]):
    from . import llm
    r = _rcfg(cfg)
    resp = llm.create(client, model=r.get("model", "claude-sonnet-5"), max_tokens=int(r.get("max_tokens", 2000)),
                      system=system, tools=[REBUILD_TOOL], tool_choice={"type": "tool", "name": REBUILD_TOOL["name"]},
                      messages=messages, cfg=cfg)
    if getattr(resp, "stop_reason", "") == "max_tokens":
        return None, "رد مقطوع"
    block = next((b for b in getattr(resp, "content", []) or []
                  if getattr(b, "type", "") == "tool_use" and getattr(b, "name", "") == REBUILD_TOOL["name"]), None)
    if block is None:
        return None, "لم يُرجع النموذج السياق"
    from . import reel_script
    return block, [str(p or "") for p in reel_script._listish((block.input or {}).get("parts"))]


def rebuild(script: dict, clips: dict, cfg, notes: list, meta: dict | None = None, client=None) -> set[int]:
    """يعيد بناء كلام السياق على المقاطع الباقية إن سقط منه مقطع. يغيّر نصوص مشاهد الراوي في script (نسخة الذاكرة؛ السيناريو
    المحفوظ لا يُمسّ، فإعادة التركيب تبدأ من السيناريو المعتمد) ويعيد فهارس مشاهد الراوي التي فرغت. لا يرفع أبدًا."""
    r = _rcfg(cfg)
    if not r.get("enabled", False):
        return set()
    lay = context_layout(script, clips)
    if lay is None:
        return set()
    t = cfg.path("reel.render.texts") or {}
    scenes = script["scenes"]
    lost_names = "، ".join(dict.fromkeys(scenes[i].get("channel_display", "") for i in lay["lost"]))
    try:
        from . import llm
        system = llm.with_notes(str(r.get("system", "")), cfg)
        messages: list[dict] = [{"role": "user", "content": message(script, lay)}]
        parts: list[str] = []
        reasons: list[str] = ["لا رد"]
        for _ in range(2):
            block, got = _ask(client, cfg, system, messages)
            if block is None:
                reasons = [got]
                break
            parts = got
            reasons = problems(parts, lay, script, cfg)
            if not reasons:
                break
            # إعادة واحدة في المحادثة نفسها بالسبب (نهج Q8)
            messages += [{"role": "assistant", "content": [{"type": "tool_use", "id": block.id, "name": block.name,
                                                            "input": block.input}]},
                         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                                       "content": "صحّح: " + "؛ ".join(reasons)}]}]
        if reasons:
            notes.append(t.get("comment_context_rebuild_failed", "⚠️ سقط مقطع سياق ({channels}) ولم يُعَد بناء السياق: {reason}")
                         .format(channels=lost_names, reason="؛ ".join(reasons)[:200]))
            if meta is not None:
                meta["context_rebuild"] = {"lost": [scenes[i].get("point_id", "") for i in lay["lost"]], "error": reasons[:3]}
            return set()
    except Exception as exc:  # noqa: BLE001 -- تحسين لا يُسقط التركيب
        log.warning("تعذّرت إعادة بناء السياق: %s", str(exc)[:150])
        notes.append(t.get("comment_context_rebuild_failed", "⚠️ سقط مقطع سياق ({channels}) ولم يُعَد بناء السياق: {reason}")
                     .format(channels=lost_names, reason=type(exc).__name__))
        return set()
    dead: set[int] = set()
    texts: list[str] = []
    for text, slots in zip(parts, lay["gaps"]):
        text = " ".join(_words(text))
        if not slots:
            continue
        if text:
            scenes[slots[0]]["text"] = text
            texts.append(text)
            dead.update(slots[1:])
        else:
            dead.update(slots)
    notes.append(t.get("comment_context_rebuilt", "🔁 أُعيد بناء السياق بعد سقوط مقطع ({channels}): {text}")
                 .format(channels=lost_names, text=" ◂ ".join(texts)))
    if meta is not None:
        meta["context_rebuild"] = {"lost": [scenes[i].get("point_id", "") for i in lay["lost"]], "texts": texts,
                                   "dead": sorted(dead)}
    return dead
