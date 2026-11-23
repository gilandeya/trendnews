"""كاريكاتير الهوك (طلب صاحب المشروع 23/11): صورة كاريكاتيرية تلخّص ما يقوله المحللون عن سؤال الريل (مثلًا القادة الثلاثة يقتسمون
كعكة خريطة العالم، أو منصة تتويج بترتيب يحكم به التحليل) خلفيةً للهوك تحت سؤاله.

الخطوتان: Claude يكتب فكرة الرسم من مادة الريل نفسها (السؤال وإجابات المحللين ومواقفهم)، فالترتيب أو المفارقة تقولها الإجابات لا
النموذج؛ ثم Gemini يرسمها (`reel.cartoon.model`، مفتاح GEMINI_API_KEY القائم). القرار لصاحب المشروع: تُعرض في قضية مراجعة
السيناريو بمربع غير معلَّم، ولا تدخل الريل إلا إن علّمه. لا يرفع أبدًا: أي عطل ← بلا كاريكاتير وسطر بسببه."""
from __future__ import annotations

import base64
import logging
import os
import re
from pathlib import Path
from typing import Any

from . import llm

log = logging.getLogger(__name__)

CONCEPT_TOOL = {
    "name": "cartoon_concept",
    "description": "فكرة رسم كاريكاتيري واحد يلخّص ما تقوله إجابات المحللين عن سؤال الريل",
    "input_schema": {"type": "object", "properties": {
        "feasible": {"type": "boolean", "description": "false إن لم تحمل الإجابات فكرة يرسمها كاريكاتير بأمانة"},
        "idea_ar": {"type": "string", "description": "الفكرة بالعربية بجملة واحدة للمراجع"},
        "basis_ar": {"type": "string", "description": "أي إجابات (بأرقامها) تقول ما يرسمه الكاريكاتير"},
        "prompt_en": {"type": "string", "description": "وصف الرسم بالإنجليزية لمولّد الصور"}},
        "required": ["feasible", "idea_ar", "basis_ar", "prompt_en"]},
}

OK_RE = re.compile(r"^\s*-\s*\[([ xX])\][^\n]*?<!--\s*cartoonok:([0-9a-f]+)\s*-->", re.MULTILINE)


def ccfg(cfg) -> dict:
    return cfg.path("reel.cartoon") or {}


def enabled(cfg) -> bool:
    return bool(ccfg(cfg).get("enabled", False))


def _create(client, **kwargs):
    """نقطة نداء Claude (يزيّفها الاختبار)."""
    return llm.create(client, **kwargs)


def _generate(body: dict, model: str, key: str, timeout: int):
    """نقطة نداء Gemini (يزيّفها الاختبار): (رمز HTTP، الرد، الثواني)."""
    from . import gemini
    return gemini.generate(body, model, key, timeout=timeout)


def material(script: dict) -> str:
    """مدخل فكرة الرسم: سؤال الريل وسياقه، ولكل سؤال إجاباته بقائليها ومواقفها وترجمتها (ما سيسمعه المشاهد)."""
    scenes = script.get("scenes") or []
    lines = [f"سؤال الريل: {script.get('title', '')}"]
    ctx = " ".join(s.get("text", "") for s in scenes if s.get("kind") == "narration" and s.get("role") == "context")
    if ctx:
        lines.append(f"السياق: {ctx}")
    n = 0
    for s in scenes:
        if s.get("kind") == "narration" and s.get("role") == "question":
            lines.append(f"\n## {s.get('text', '')}")
        elif s.get("kind") in ("clip", "cold_open_clip") and s.get("role") != "context":
            n += 1
            who = s.get("speaker_name") or s.get("channel_display") or "متحدث"
            stance = f" · الموقف: {s['stance']}" if s.get("stance") else ""
            lines.append(f"[{n}] {who} ({s.get('channel_display', '')}){stance}: «{s.get('quote_arabic', '')}»")
    return "\n".join(lines)


def concept(script: dict, cfg, client=None) -> tuple[dict | None, str]:
    """(الفكرة، "") أو (None، السبب). الرد المقطوع لا يُقبل."""
    from .meta_topics import _tool_input
    c = ccfg(cfg)
    resp = _create(client, cfg=cfg, model=c.get("concept_model", "claude-sonnet-5"),
                   max_tokens=int(c.get("max_tokens", 2000)), system=str(c.get("concept_system", "")),
                   tools=[CONCEPT_TOOL], tool_choice={"type": "tool", "name": CONCEPT_TOOL["name"]},
                   messages=[{"role": "user", "content": material(script)}])
    if str(getattr(resp, "stop_reason", "") or "") == "max_tokens":
        return None, "الرد مقطوع"
    got = _tool_input(resp, CONCEPT_TOOL["name"]) or {}
    if not got.get("feasible"):
        return None, str(got.get("idea_ar") or "لا فكرة يرسمها كاريكاتير بأمانة")
    prompt = " ".join(str(got.get("prompt_en") or "").split())
    if not prompt:
        return None, "وصف رسم فارغ"
    return {"idea_ar": " ".join(str(got.get("idea_ar") or "").split()),
            "basis_ar": " ".join(str(got.get("basis_ar") or "").split()), "prompt_en": prompt}, ""


def image_prompt(con: dict, cfg) -> str:
    """وصف الرسم مع قواعد الشكل الثابتة من الإعداد (الأسلوب، والفراغ أعلى الصورة لنص السؤال، وبلا كتابة في الرسم)."""
    return f"{con['prompt_en']}\n\n{ccfg(cfg).get('style', '')}".strip()


def read_image(resp: dict) -> tuple[bytes | None, str, dict]:
    """(بايتات الصورة، سبب التوقف، الاستهلاك). أجزاء التفكير (thought) تُهمل؛ بلا صورة ← None."""
    cands = (resp or {}).get("candidates") or []
    finish = (cands[0].get("finishReason") if cands else "") or "no_candidates"
    usage = (resp or {}).get("usageMetadata") or {}
    for p in ((cands[0].get("content") or {}).get("parts") or []) if cands else []:
        data = p.get("inlineData") or p.get("inline_data")
        if data and not p.get("thought") and data.get("data"):
            try:
                return base64.b64decode(data["data"]), finish, usage
            except ValueError:
                return None, "bad_base64", usage
    return None, finish, usage


def plan(draft: dict, cfg: Any, client=None) -> dict | None:
    """يكتب الفكرة ويرسمها ويحفظها PNG بجوار المسودة (drafts/<اليوم>/<id>-cartoon.png، يودِعه publish.yml مع drafts فيُعرض في القضية)، ويحفظ draft["hook_cartoon"] = {status: ready|none, idea_ar, basis_ar,
    prompt_en, path, model, cost_usd, error}. لا يرفع أبدًا."""
    if not enabled(cfg) or not draft.get("script"):
        return None
    c = ccfg(cfg)
    rec: dict = {"status": "none"}
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        rec["error"] = "no_key"
        draft["hook_cartoon"] = rec
        return rec
    try:
        con, why = concept(draft["script"], cfg, client)
        if not con:
            rec["error"] = why
            draft["hook_cartoon"] = rec
            return rec
        rec.update(con)
        model = str(c.get("model", "gemini-3.1-flash-image"))
        body = {"contents": [{"parts": [{"text": image_prompt(con, cfg)}]}],
                "generationConfig": {"responseModalities": ["IMAGE"],
                                     "imageConfig": {"aspectRatio": str(c.get("aspect", "9:16"))}}}
        code, resp, _ = _generate(body, model, key, int(c.get("timeout", 180)))
        if code != 200 or not isinstance(resp, dict):
            rec["error"] = f"HTTP {code}: {str(resp)[:150]}"
        else:
            img, finish, usage = read_image(resp)
            from . import costs
            usd = round(int(usage.get("candidatesTokenCount") or 0) * float(c.get("usd_per_mtok_output", 30)) / 1e6
                        + float(c.get("usd_per_image", 0)), 4)
            rec["cost_usd"] = usd
            costs.add("gemini", usd)
            if not img:
                rec["error"] = f"بلا صورة: {finish}"
            else:
                from . import store
                out_dir = store.draft_dir()
                out_dir.mkdir(parents=True, exist_ok=True)
                path = out_dir / f"{draft['id']}-cartoon.png"
                from io import BytesIO

                from PIL import Image
                Image.open(BytesIO(img)).convert("RGB").save(path, "PNG")
                # المسار بصيغة حقل image نفسها (drafts/…) لأن raw_url وقارئ التركيب يحلّانه هكذا
                rec.update(status="ready", path=f"drafts/{out_dir.name}/{path.name}", model=model)
    except Exception as exc:  # noqa: BLE001 -- الكاريكاتير إضافة: السيناريو صالح بدونه
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
        log.warning("تعذّر رسم كاريكاتير الهوك: %s", str(exc)[:150])
    draft["hook_cartoon"] = rec
    return rec


def local_path(rec: dict) -> Path | None:
    """ملف الكاريكاتير على القرص من مساره المحفوظ؛ None إن غاب."""
    from .config import DRAFTS_DIR
    rel = (rec or {}).get("path")
    if not rel:
        return None
    path = DRAFTS_DIR / Path(rel).relative_to("drafts")
    return path if path.exists() else None


def usable(draft: dict, cfg) -> Path | None:
    """الكاريكاتير يدخل الريل إن كان جاهزًا وعلّمه المراجع وملفه موجود."""
    rec = draft.get("hook_cartoon")
    if not enabled(cfg) or not isinstance(rec, dict) or rec.get("status") != "ready" or not rec.get("approved"):
        return None
    return local_path(rec)


def cover_frame(path: Path, w: int, h: int):
    """الصورة بمقاس الشاشة: تُكبَّر لتغطيه ثم يُقصّ وسطها، فلا شريط أسود إن أعاد المولّد نسبة قريبة لا 9:16 تمامًا."""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    scale = max(w / img.width, h / img.height)
    img = img.resize((max(w, round(img.width * scale)), max(h, round(img.height * scale))), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def parse_ok(body: str) -> set[str]:
    return {did for mark, did in OK_RE.findall(body or "") if mark.lower() == "x"}


def review_lines(d: dict, cfg, image_url: str = "") -> list[str]:
    """سطور الكاريكاتير في قضية السيناريو: الفكرة وأساسها والصورة ومربع غير معلَّم، أو سبب غيابه."""
    rec = d.get("hook_cartoon")
    if not isinstance(rec, dict) or not enabled(cfg):
        return []
    t = ccfg(cfg).get("texts") or {}
    if rec.get("status") != "ready":
        return [f"  {t.get('none', '🎨 لا كاريكاتير للهوك')}: {rec.get('error', '')}", ""]
    out = [f"  {t.get('header', '🎨 كاريكاتير مقترح للهوك')}: {rec.get('idea_ar', '')}",
           f"  <sub>{t.get('basis', 'الأساس')}: {rec.get('basis_ar', '')}</sub>", ""]
    if image_url:
        out += [f'  <img src="{image_url}" width="270">', ""]
    out += [f"  - [ ] {t.get('approve', 'استعمله خلفيةً للهوك')} <!-- cartoonok:{d['id']} -->", ""]
    return out
