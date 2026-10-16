"""خطة لقطات الحدث خلف جمل الراوي (Issue #1452، R5d2 — الجزء أ: السيناريو).

ما يُرى خلف كل جملة قرار تحريري فمكانه السيناريو؛ التركيب (الجزء ب) يجد الثواني الفعلية ويتحقق بالعين.
هنا نداء Haiku واحد يصف لكل جملة ما يجب أن يُرى (visual) أو يتركه فارغًا للجملة المجرّدة، وعطله لا يُسقط سيناريو صالحًا."""
from __future__ import annotations

import logging
from typing import Any

from . import llm, tts

log = logging.getLogger("trendnews")

PLAN_TOOL = {
    "name": "plan_broll",
    "description": "يُبلِّغ لكل جملة من جمل الراوي وصفًا قصيرًا لما يجب أن يُرى خلفها، أو فارغًا إن كانت مجرّدة",
    "input_schema": {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {
            "type": "object",
            "properties": {"scene": {"type": "integer"}, "sentence": {"type": "integer"},
                           "visual": {"type": "string", "description": "وصف قصير لما يُرى أو فارغ"}},
            "required": ["scene", "sentence", "visual"]}}},
        "required": ["items"],
    },
}


def _create(client, **kwargs):
    """نقطة النداء الوحيدة (يزيّفها الاختبار). النداء عبر llm.create فلا temperature."""
    if client is None:
        from anthropic import Anthropic
        from .config import env
        client = Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    return llm.create(client, **kwargs)


def narration_sentences(script: dict) -> list[dict]:
    """جمل الراوي بترتيبها بالقسمة نفسها التي يستعملها التركيب (tts.split_sentences)."""
    out = []
    for i, sc in enumerate(script.get("scenes") or []):
        if sc.get("kind") != "narration":
            continue
        for k, s in enumerate(tts.split_sentences(sc.get("text", ""))):
            out.append({"scene": i, "sentence": k, "text": s})
    return out


def plan(script: dict, title: str, cfg: Any, client=None) -> list[dict]:
    """[{scene, sentence, text, visual}] لكل جملة؛ visual فارغ ← الصورة المتحركة. يرفع عند العطل (يلتقطه write_plan)."""
    sents = narration_sentences(script)
    if not sents:
        return []
    bcfg = cfg.path("reel.broll", {}) or {}
    listing = "\n".join(f"[{s['scene']}.{s['sentence']}] {s['text']}" for s in sents)
    resp = _create(client, cfg=cfg, model=bcfg.get("model", "haiku"), max_tokens=int(bcfg.get("plan_max_tokens", 1500)),
                   system=bcfg.get("plan_system", ""), tools=[PLAN_TOOL],
                   tool_choice={"type": "tool", "name": PLAN_TOOL["name"]},
                   messages=[{"role": "user", "content": f"عنوان الحدث: {title}\n\nجمل الراوي:\n{listing}"}])
    data = None
    for b in getattr(resp, "content", None) or []:
        if getattr(b, "type", "") == "tool_use" and getattr(b, "name", "") == PLAN_TOOL["name"]:
            data = getattr(b, "input", None)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("لا خطة لقطات في الرد")
    by_key = {(int(i.get("scene", -1)), int(i.get("sentence", -1))): str(i.get("visual") or "").strip()
              for i in data["items"] if isinstance(i, dict)}
    # المفتاح من الكود لا من النموذج: جملة لم يصفها يعيدها فارغة فتأخذ الصورة
    return [{**s, "visual": by_key.get((s["scene"], s["sentence"]), "")} for s in sents]


def write_plan(draft: dict, cfg: Any, client=None) -> None:
    """يحفظ broll_plan على المسودة؛ العطل ← [] وbroll_plan_error ولا يُسقط السيناريو."""
    draft.pop("broll_plan_error", None)
    if not cfg.path("reel.broll.enabled", False):
        return
    try:
        draft["broll_plan"] = plan(draft.get("script") or {}, str(draft.get("title", "")), cfg, client)
    except Exception as exc:  # noqa: BLE001
        log.warning("تعذّرت خطة لقطات الريل: %s", str(exc)[:100])
        draft["broll_plan"] = []
        draft["broll_plan_error"] = str(exc)[:200]
