"""كاريكاتير الهوك (طلب صاحب المشروع 23/11): رسم كاريكاتيري يلخّص ما يقوله المحللون عن سؤال الريل (مثلًا القادة الثلاثة يقتسمون
كعكة خريطة العالم، أو منصة تتويج بترتيب يحكم به التحليل) يظهر في الهوك تحت سؤاله.

قطع لا لوحة (قرار صاحب المشروع 25/11، قضية 2007): الرسم بخلفيته غطّى الشاشة كلها فغابت خلفية الهوك المعتادة (لقطة الحدث). صار الرسم
2–5 قطع بلا خلفية (السفينة، ليبيا بمن عليها، البحر…) تدخل مع دخول السؤال من خارج الشاشة وتتجمّع في مواضعها فوق الخلفية المعتادة.
كل قطعة تُرسم وحدها على لون مفتاح مسطّح (key_color) ويُزال اللون في الكود بالمتصل بحافة الصورة وحده، فلا يُمحى لون مشابه داخل الرسم.

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
    "description": "فكرة رسم كاريكاتيري واحد يلخّص ما تقوله إجابات المحللين عن سؤال الريل، مقسومًا قطعًا بلا خلفية",
    "input_schema": {"type": "object", "properties": {
        "feasible": {"type": "boolean", "description": "false إن لم تحمل الإجابات فكرة يرسمها كاريكاتير بأمانة"},
        "idea_ar": {"type": "string", "description": "الفكرة بالعربية بجملة واحدة للمراجع"},
        "basis_ar": {"type": "string", "description": "أي إجابات (بأرقامها) تقول ما يرسمه الكاريكاتير"},
        "prompt_en": {"type": "string", "description": "وصف المشهد كاملًا بالإنجليزية (أسلوب مشترك للقطع)"},
        "pieces": {"type": "array", "description": "قطع الرسم بلا خلفية، كل قطعة شيء واحد أو مجموعة متماسكة", "items": {
            "type": "object", "properties": {
                "name_ar": {"type": "string"},
                "prompt_en": {"type": "string", "description": "وصف القطعة وحدها بالإنجليزية: الشيء وألوانه وزاويته، بلا أرضية ولا سماء"},
                "x": {"type": "number", "description": "مركز القطعة أفقيًا في منطقة الرسم: 0 يسار، 1 يمين"},
                "y": {"type": "number", "description": "مركزها رأسيًا في منطقة الرسم: 0 أعلى، 1 أسفل"},
                "width": {"type": "number", "description": "عرضها نسبةً من عرض منطقة الرسم (0.15–0.9)"},
                "enter": {"type": "string", "enum": ["left", "right", "top", "bottom"],
                          "description": "من أين تدخل الشاشة"}},
            "required": ["name_ar", "prompt_en", "x", "y", "width", "enter"]}}},
        "required": ["feasible", "idea_ar", "basis_ar", "prompt_en", "pieces"]},
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
    pieces = clean_pieces(llm.tool_json(got.get("pieces"), list) or [], cfg)
    lo, hi = int(c.get("min_pieces", 2)), int(c.get("max_pieces", 5))
    if len(pieces) < lo:
        return None, f"قطع الرسم أقل من {lo}"
    return {"idea_ar": " ".join(str(got.get("idea_ar") or "").split()),
            "basis_ar": " ".join(str(got.get("basis_ar") or "").split()), "prompt_en": prompt, "pieces": pieces[:hi]}, ""


def _num(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def clean_pieces(raw: list, cfg) -> list[dict]:
    """قطع الفكرة بعد التحقق (دالة خالصة): وصف غير فارغ، ومواضع داخل [0، 1]، وعرض بين min/max_width، واتجاه دخول معروف
    (وإلا من الأسفل)."""
    c = ccfg(cfg)
    lo_w, hi_w = float(c.get("min_width", 0.15)), float(c.get("max_width", 0.9))
    out = []
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        prompt = " ".join(str(p.get("prompt_en") or "").split())
        if not prompt:
            continue
        enter = str(p.get("enter") or "bottom")
        out.append({"name_ar": " ".join(str(p.get("name_ar") or "").split()), "prompt_en": prompt,
                    "x": min(max(_num(p.get("x"), 0.5), 0.0), 1.0), "y": min(max(_num(p.get("y"), 0.5), 0.0), 1.0),
                    "width": min(max(_num(p.get("width"), 0.4), lo_w), hi_w),
                    "enter": enter if enter in ("left", "right", "top", "bottom") else "bottom"})
    return out


def area_px(cfg, w: int, h: int) -> tuple[int, int, int, int]:
    """منطقة القطع بالبكسل (يسار، أعلى، يمين، أسفل) من reel.cartoon.area بنسب الشاشة: تحت عنوان السؤال وفوق نص منشور فيسبوك."""
    a = ccfg(cfg).get("area") or {}
    return (round(float(a.get("left", 0.04)) * w), round(float(a.get("top", 0.5)) * h),
            round(float(a.get("right", 0.96)) * w), round(float(a.get("bottom", 0.92)) * h))


def place(size: tuple[int, int], spec: dict, cfg, w: int, h: int) -> tuple[int, int, int, int]:
    """موضع القطعة النهائي (x، y، عرض، ارتفاع) بالبكسل (دالة خالصة): عرضها width من عرض المنطقة بنسبتها، تُصغَّر إن تجاوز ارتفاعها
    المنطقة، ومركزها (x، y) في المنطقة ثم تُحصر كلها داخلها."""
    al, at, ar, ab = area_px(cfg, w, h)
    aw, ah = max(ar - al, 1), max(ab - at, 1)
    sw, sh = max(int(size[0]), 1), max(int(size[1]), 1)
    pw = max(float(spec.get("width", 0.4)) * aw, 2.0)
    ph = pw * sh / sw
    if ph > ah:
        pw, ph = pw * ah / ph, float(ah)
    pw, ph = max(int(round(pw)), 2), max(int(round(ph)), 2)
    cx = al + float(spec.get("x", 0.5)) * aw
    cy = at + float(spec.get("y", 0.5)) * ah
    x = int(round(min(max(cx - pw / 2, al), ar - pw)))
    y = int(round(min(max(cy - ph / 2, at), ab - ph)))
    return x, y, pw, ph


def start_pos(enter: str, box: tuple[int, int, int, int], w: int, h: int) -> tuple[int, int]:
    """موضع القطعة قبل دخولها: خارج الشاشة تمامًا من جهة enter وعلى خط موضعها النهائي (دالة خالصة)."""
    x, y, pw, ph = box
    return {"left": (-pw, y), "right": (w, y), "top": (x, -ph)}.get(enter, (x, h))


def cutout(img, cfg):
    """القطعة بلا خلفية (RGBA مقصوصة إلى حدودها) أو None. لون المفتاح (key_color) يُزال حيث يتصل بحافة الصورة وحدها، فلون مشابه
    داخل الرسم (علم أو بحر) لا يُمحى؛ ثم تنعيم الحافة وإزالة أثر اللون عنها. تغطية خارج [min_cover، max_cover] ← None (المولّد لم
    يرسم على اللون المسطّح أو لم يرسم شيئًا)."""
    import cv2
    import numpy as np
    from PIL import Image
    c = ccfg(cfg)
    rgb = np.asarray(img.convert("RGB")).astype(np.int32)
    from . import imaging
    key = np.array(imaging.hex_rgb(str(c.get("key_color", "#FF00FF"))), np.int32)
    near = (np.sqrt(((rgb - key) ** 2).sum(axis=2)) <= float(c.get("key_tolerance", 110))).astype(np.uint8)
    n, labels = cv2.connectedComponents(near, connectivity=4)
    edge = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    bg = np.isin(labels, list(edge)) & (near > 0)
    alpha = np.where(bg, 0.0, 1.0).astype(np.float32)
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
    cover = float((alpha > 0.5).mean())
    if not float(c.get("min_cover", 0.03)) <= cover <= float(c.get("max_cover", 0.95)):
        return None
    out = rgb.astype(np.float32)
    # أثر اللون على الحافة: حيث الشفافية جزئية تُخفَّض كل قناة يبرزها لون المفتاح إلى أعلى القنوات الأخرى، فلا تبقى هالة بلونه
    soft = (alpha > 0) & (alpha < 1)
    strong = [k for k in range(3) if key[k] >= 200]
    weak = [k for k in range(3) if key[k] < 200]
    if strong and weak:
        cap = np.max(out[..., weak], axis=2)
        for k in strong:
            out[..., k] = np.where(soft, np.minimum(out[..., k], cap), out[..., k])
    rgba = np.dstack([np.clip(out, 0, 255), alpha * 255]).astype(np.uint8)
    ys, xs = np.where(alpha > 0.02)
    pad = int(c.get("trim_pad", 4))
    y0, y1 = max(int(ys.min()) - pad, 0), min(int(ys.max()) + pad + 1, rgba.shape[0])
    x0, x1 = max(int(xs.min()) - pad, 0), min(int(xs.max()) + pad + 1, rgba.shape[1])
    return Image.fromarray(rgba[y0:y1, x0:x1], "RGBA")


def image_prompt(piece: dict, con: dict, cfg) -> str:
    """وصف القطعة وحدها مع المشهد كله (ليتّسق أسلوب القطع) وقواعد الشكل الثابتة (قطعة واحدة على لون مفتاح مسطّح، بلا كتابة)."""
    c = ccfg(cfg)
    return (f"{piece['prompt_en']}\n\nThis is one cut-out element of a larger cartoon scene: {con['prompt_en']}\n"
            f"Draw ONLY this element.\n\n{c.get('style', '')}\n{c.get('piece_style', '')}").strip()


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


def _draw_piece(piece: dict, con: dict, cfg, key: str) -> tuple[Any, float, str]:
    """(القطعة RGBA أو None، الكلفة، سبب الفشل): نداء Gemini واحد للقطعة ثم إزالة اللون."""
    from io import BytesIO

    from PIL import Image
    c = ccfg(cfg)
    model = str(c.get("model", "gemini-3.1-flash-image"))
    body = {"contents": [{"parts": [{"text": image_prompt(piece, con, cfg)}]}],
            "generationConfig": {"responseModalities": ["IMAGE"],
                                 "imageConfig": {"aspectRatio": str(c.get("piece_aspect", "1:1"))}}}
    code, resp, _ = _generate(body, model, key, int(c.get("timeout", 180)))
    if code != 200 or not isinstance(resp, dict):
        return None, 0.0, f"HTTP {code}: {str(resp)[:150]}"
    img, finish, usage = read_image(resp)
    usd = round(int(usage.get("candidatesTokenCount") or 0) * float(c.get("usd_per_mtok_output", 30)) / 1e6
                + float(c.get("usd_per_image", 0)), 4)
    if not img:
        return None, usd, f"بلا صورة: {finish}"
    cut = cutout(Image.open(BytesIO(img)), cfg)
    if cut is None:
        return None, usd, "لم تُفصل القطعة عن خلفيتها"
    return cut, usd, ""


def preview(pieces: list[dict], cfg, w: int, h: int):
    """صورة المراجعة: القطع في مواضعها النهائية فوق لون العلامة (الخلفية الفعلية في الريل لقطة الهوك المعتادة)."""
    from PIL import Image

    from . import imaging
    base = Image.new("RGBA", (w, h), (*imaging.hex_rgb(str(cfg.path("brand.primary_color") or "#12203A")), 255))
    for p in pieces:
        img = Image.open(p["file"]).convert("RGBA")
        x, y, pw, ph = place(img.size, p, cfg, w, h)
        base.alpha_composite(img.resize((pw, ph), Image.LANCZOS), (x, y))
    return base.convert("RGB")


def plan(draft: dict, cfg: Any, client=None) -> dict | None:
    """يكتب الفكرة بقطعها ويرسم كل قطعة وحدها ويحفظها PNG شفافة بجوار المسودة (drafts/<اليوم>/<id>-cartoon-<k>.png) ومعاينتها
    (…-cartoon.png، في path) فيودِعها publish.yml مع drafts وتُعرض في القضية. draft["hook_cartoon"] = {status: ready|none, idea_ar,
    basis_ar, prompt_en, pieces: [{name_ar, x, y, width, enter, path}], path, model, cost_usd, error}. أقل من min_pieces قطعة ناجحة
    ← none بسببه. لا يرفع أبدًا."""
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
        rec.update({k: v for k, v in con.items() if k != "pieces"})
        from . import costs, store
        out_dir = store.draft_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        done, failed, usd = [], [], 0.0
        for k, piece in enumerate(con["pieces"]):
            img, cost, err = _draw_piece(piece, con, cfg, key)
            usd += cost
            if img is None:
                failed.append(f"{piece.get('name_ar') or k + 1}: {err}")
                continue
            path = out_dir / f"{draft['id']}-cartoon-{k}.png"
            img.save(path, "PNG")
            done.append({**piece, "path": f"drafts/{out_dir.name}/{path.name}", "file": path})
        usd = round(usd, 4)
        rec["cost_usd"] = usd
        costs.add("gemini", usd)
        if failed:
            rec["failed"] = failed
        if len(done) < int(c.get("min_pieces", 2)):
            rec["error"] = "؛ ".join(failed) or "لا قطعة"
        else:
            w, h = int(cfg.path("reel.render.width")), int(cfg.path("reel.render.height"))
            prev = out_dir / f"{draft['id']}-cartoon.png"
            preview(done, cfg, w, h).save(prev, "PNG")
            # المسار بصيغة حقل image نفسها (drafts/…) لأن raw_url وقارئ التركيب يحلّانه هكذا
            rec.update(status="ready", path=f"drafts/{out_dir.name}/{prev.name}", model=str(c.get("model", "")),
                       pieces=[{k: v for k, v in p.items() if k != "file"} for p in done])
    except Exception as exc:  # noqa: BLE001 -- الكاريكاتير إضافة: السيناريو صالح بدونه
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
        log.warning("تعذّر رسم كاريكاتير الهوك: %s", str(exc)[:150])
    draft["hook_cartoon"] = rec
    return rec


def local_path(rec_or_path) -> Path | None:
    """ملف على القرص من مساره المحفوظ (drafts/…) أو من سجلّ فيه path؛ None إن غاب."""
    from .config import DRAFTS_DIR
    rel = rec_or_path.get("path") if isinstance(rec_or_path, dict) else rec_or_path
    if not rel:
        return None
    path = DRAFTS_DIR / Path(rel).relative_to("drafts")
    return path if path.exists() else None


def usable(draft: dict, cfg) -> list[dict] | None:
    """قطع الكاريكاتير التي تدخل الريل [{…الموضع والاتجاه، file}] إن كان جاهزًا وعلّمه المراجع وبقي من ملفاتها min_pieces؛ وإلا None.
    كاريكاتير قديم بلوحة واحدة (قبل 25/11، بلا pieces) لا يدخل: كان يغطي خلفية الهوك كلها."""
    rec = draft.get("hook_cartoon")
    if not enabled(cfg) or not isinstance(rec, dict) or rec.get("status") != "ready" or not rec.get("approved"):
        return None
    out = []
    for p in rec.get("pieces") or []:
        f = local_path(p.get("path")) if isinstance(p, dict) else None
        if f is not None:
            out.append({**p, "file": f})
    return out if len(out) >= int(ccfg(cfg).get("min_pieces", 2)) else None


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
           f"  <sub>{t.get('basis', 'الأساس')}: {rec.get('basis_ar', '')}</sub>"]
    names = [p.get("name_ar") for p in rec.get("pieces") or [] if isinstance(p, dict) and p.get("name_ar")]
    if names:
        out.append(f"  <sub>{t.get('pieces', 'القطع')}: {' · '.join(names)}</sub>")
    out.append("")
    if image_url:
        out += [f'  <img src="{image_url}" width="270">', ""]
    out += [f"  - [ ] {t.get('approve', 'استعمله خلفيةً للهوك')} <!-- cartoonok:{d['id']} -->", ""]
    return out
