"""التحقق من مقاطع الموضوع بالصوت قبل أن تُعرض للاختيار (خطة 15/11، الخطوة «ب»).

لماذا: نافذة Gemini تقديرية، وما لا يطابق مسموعُه نصَّه كان يُكتشف في التركيب بعد أن اختار صاحب المشروع الأسئلة وكُتب السيناريو
ودُفع ثمنه (20 سيناريو فاشلًا من 45، وقضية 1881 أعادت الاختيار كله). هنا يُنزَّل صوت نوافذ المقاطع وحدها (أقسام، أدنى جودة)
ويُفرَّغ ويُطابَق الكلام المحفوظ بالكلمات؛ المطابق يأخذ حدّيه من الصوت وتُحفظ كلماته فلا يفرّغه التركيب ثانية، وغير المطابق
لا يُعرض. يجري في خطوة الأسئلة (reel-render.yml) لأن فيها البروكسي والمفرِّغ؛ خطوة السيناريو (publish.yml) بلا أيٍّ منهما.

لا يرفع أبدًا: عطل التحقق يترك المقاطع كما هي ويبقى حارس التركيب (حذف المقطع وإعادة الاختيار) شبكة أمان.
الكلمات كلام قناة: تُحفظ على المقطع في الملف الخاص وحده.
"""
from __future__ import annotations

import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from . import bite_audio

log = logging.getLogger(__name__)


def _vcfg(cfg: Any) -> dict:
    return cfg.path("youtube.meta_topics.qa.verify") or {}


def enabled(cfg: Any) -> bool:
    return bool(_vcfg(cfg).get("enabled", False))


def default_deps() -> bite_audio.Deps:
    """نقطة الحقن الوحيدة: install_fakes يستبدلها كي لا يحمّل اختبارٌ نموذج التفريغ ولا يلمس الشبكة."""
    return bite_audio.Deps()


def _safe(exc: Exception) -> str:
    """نص العطل بلا أسرار: scrub_text لا تعرف مستخدم البروكسي وكلمة مروره (رابطه يحملهما، درس R8)، والسبب يُحفظ على المقطع."""
    from . import reel_clips
    return f"{type(exc).__name__}: " + re.sub(r"(?<=://)[^/@\s]*@", "", reel_clips.scrub_text(str(exc)))[:120]


def window(b: dict, margin: float) -> tuple[int, int]:
    """نافذة الصوت حول المقطع بثواني الفيديو (أعداد صحيحة). دالة خالصة."""
    w0 = max(0.0, float(b["start"]) - margin)
    w1 = float(b["end"]) + margin
    if b.get("duration_seconds"):
        w1 = min(w1, float(b["duration_seconds"]))
    return int(w0), int(w1 + 0.999)


def priority(questions: list[dict], bites: list[dict], extra: list[dict]) -> list[dict]:
    """ترتيب التحقق حين لا يتسع الوقت للكل: أول إجابة لكل سؤال، ثم مقاطع السياق، ثم ثاني إجابة لكل سؤال وهكذا — فلا ينفد الوقت
    على سؤال واحد ويبقى غيره بلا مقطع محقَّق. كل مقطع مرة. دالة خالصة."""
    out: list[dict] = []
    seen: set[int] = set()

    def push(b: dict) -> None:
        if id(b) not in seen:
            seen.add(id(b))
            out.append(b)
    depth = max((len(q.get("answers") or []) for q in questions), default=0)
    for k in range(depth):
        for q in questions:
            ans = q.get("answers") or []
            if k < len(ans) and 1 <= int(ans[k]["n"]) <= len(bites):
                push(bites[int(ans[k]["n"]) - 1])
        if k == 0:
            for b in extra:
                push(b)
    for b in extra:
        push(b)
    return out


def check_bite(b: dict, source: list, deps: bite_audio.Deps, cfg: Any, tmp: Path) -> dict:
    """يفرّغ نافذة المقطع من قسمه المنزَّل ويطابق كلامه المحفوظ. يعيد سجل audio (لا يغيّر المقطع) ولا يرفع.
    النافذة الضيقة أولًا (انزياح Gemini الوسيط نحو ثانية، والتفريغ على المعالج بطول الصوت)، ثم الواسعة مرة لما لم يطابق."""
    from . import reel_clips
    v = _vcfg(cfg)
    rec: dict = {"source": "meta_verify", "orig": [b["start"], b["end"]], "lang": b.get("language") or ""}
    original = str(b.get("text_original") or "")
    if not original:
        return {**rec, "status": "no_text"}
    relaxed = v.get("relaxed_ratio", cfg.path("reel.render.exact.relaxed_ratio"))
    margins = [float(v.get("margin", 8))]
    if float(v.get("wide_margin", 20)) > margins[0]:
        margins.append(float(v.get("wide_margin", 20)))
    diag: dict = {}
    for margin in margins:
        w0, w1 = window(b, margin)
        sec = bite_audio._section_for(source, w0, w1)
        if sec is None:
            return {**rec, "status": "failed", "error": "لا قسم منزَّل يغطي نافذة المقطع"}
        try:
            path = deps.cut(sec[1], w0 - sec[0], w1 - sec[0], tmp)
            words = deps.transcribe(path, b.get("language") or None, cfg) or []
        except Exception as exc:  # noqa: BLE001 -- عطل تفريغ: المقطع يبقى بلا حكم، والتركيب حارسه
            return {**rec, "status": "failed", "error": _safe(exc)}
        words = [(round(float(s) + w0, 2), round(float(e) + w0, 2), str(w)) for s, e, w in words]
        diag = {}
        res = reel_clips.align_quote(original, words, cfg, diag=diag)
        if res is None and relaxed and diag.get("reason") == "low_ratio":
            # كما في التركيب (ريل 13/11): نسبة بين الحد الأرخى والحد تُقبل بتفرّد النافذة
            res = reel_clips.align_quote(original, words, cfg, min_ratio=float(relaxed))
            if res is not None:
                rec["relaxed"] = True
        if res is not None:
            keep = float(v.get("keep_words_margin", 6))
            rec.update(status="ok", ratio=res["ratio"], t0=res["t0"], t1=res["t1"], margin=margin,
                       words=[list(w) for w in words if w[0] >= res["t0"] - keep and w[1] <= res["t1"] + keep])
            return rec
    return {**rec, "status": "no_match", "reason": diag.get("reason", ""), "ratio": round(float(diag.get("best_ratio") or 0), 3)}


def apply(b: dict, rec: dict, cfg: Any) -> None:
    """يكتب السجل على المقطع. المطابق يأخذ حدّيه من أول كلمة وآخرها (يصدق بهما مجموع الثواني ورابط القضية ونافذة التركيب)،
    ما لم تخرج المدة عن حدّ معقول (مطابقة شاذة: يبقى الحدّان والكلمات تكفي التركيب)."""
    b["audio"] = rec
    if rec.get("status") != "ok":
        return
    b["heard"] = True
    lo, hi = (list(_vcfg(cfg).get("span_seconds") or [3, 60]) + [60])[:2]
    if float(lo) <= float(rec["t1"]) - float(rec["t0"]) <= float(hi):
        b["start"], b["end"] = round(float(rec["t0"]), 2), round(float(rec["t1"]), 2)


def verify(targets: list[dict], cfg: Any, deps: bite_audio.Deps | None = None) -> dict:
    """يتحقق من المقاطع بترتيبها حتى max_bites أو budget_seconds ويكتب على كل مقطع فُحص سجله. يعيد أرقامًا وحدها
    (تُحفظ في ملف الحالة العام): {checked, ok, no_match, failed, no_text, left, audio_seconds, skipped}. لا يرفع."""
    from . import costs
    stats: dict = {"checked": 0, "ok": 0, "no_match": 0, "failed": 0, "no_text": 0, "left": 0, "audio_seconds": 0, "skipped": ""}
    try:
        v = _vcfg(cfg)
        deps = deps or default_deps()
        section_dl = deps.download_sections or (lambda vid, out, ranges: download_sections(vid, out, ranges, cfg, stats))
        deps = bite_audio.Deps(cut=deps.cut or bite_audio._real_cut, transcribe=deps.transcribe or bite_audio._real_transcribe,
                               selfcheck=deps.selfcheck or bite_audio._real_selfcheck)
        ok, why = deps.selfcheck(cfg)
        if not ok:
            stats["skipped"] = (why or "فشل الفحص الذاتي للمفرِّغ")[:120]
            stats["left"] = len(targets)
            return stats
        todo = [b for b in targets if (b.get("audio") or {}).get("status") not in ("ok", "open", "no_match")]
        todo = todo[:int(v.get("max_bites", 30))]
        stats["left"] = len(targets) - len(todo)
        budget = float(v.get("budget_seconds", 480))
        began = time.monotonic()
        wide = max(float(v.get("margin", 8)), float(v.get("wide_margin", 20)))
        by_video: dict[str, list[dict]] = {}
        for b in todo:
            by_video.setdefault(str(b.get("video_id")), []).append(b)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            for vid, group in by_video.items():
                if time.monotonic() - began > budget:
                    stats["left"] += len(group)
                    continue
                ranges = bite_audio.merge_windows([window(b, wide) for b in group], float(v.get("section_merge_gap", 20)))
                try:
                    source = section_dl(vid, tmp, ranges)
                    stats["audio_seconds"] += sum(b1 - a1 for a1, b1 in ranges)
                    costs.add("proxy_bytes", sum(Path(f).stat().st_size for _, _, f in source if Path(f).exists()))
                except Exception as exc:  # noqa: BLE001 -- عطل تنزيل فيديو: مقاطعه بلا حكم
                    err = _safe(exc)
                    for b in group:
                        apply(b, {"source": "meta_verify", "status": "failed", "error": err}, cfg)
                        stats["checked"] += 1
                        stats["failed"] += 1
                    continue
                for b in group:
                    if time.monotonic() - began > budget:
                        stats["left"] += 1
                        continue
                    rec = check_bite(b, source, deps, cfg, tmp)
                    apply(b, rec, cfg)
                    stats["checked"] += 1
                    stats[rec["status"]] = stats.get(rec["status"], 0) + 1
                for _, _, f in source:
                    Path(f).unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 -- التحقق تحسين لا شرط: عطله لا يُسقط أسئلة الموضوع
        log.warning("التحقق من مقاطع الموضوع: %s", exc)
        stats["skipped"] = f"{type(exc).__name__}: {str(exc)[:100]}"
    return stats


def download_sections(vid: str, out: Path, ranges: list, cfg: Any, stats: dict | None = None) -> list:
    """أقسام الصوت بالطريق الرخيص (صوت وحده)، وإن تعطّل فبطريق التركيب المجرَّب (reel_clips.download_clip: صورة بأدنى دقة وصوت،
    بدرجاته الثلاث) لكل قسم. السبب (ريل 1890): أول تشغيل حقيقي فشل تنزيل الصوت وحده لكل الفيديوهات («ffmpeg exited with code 251»)
    فلم يُفحص مقطع، وسقط في التركيب ما كان الفحص سيُسقطه قبل اختيارك. يُحفظ أول سبب وعدد ما نزل بالاحتياط (أرقام وحدها)."""
    from . import reel_clips, speaker_map
    try:
        return bite_audio._real_download(vid, out, cfg, ranges)
    except Exception as exc:  # noqa: BLE001 -- الاحتياط أدناه؛ ما لم ينجح يرفع
        v = _vcfg(cfg)
        if stats is not None and not stats.get("download_error"):
            stats["download_error"] = _safe(exc)
        if not v.get("fallback_video", True):
            raise
        got = []
        for a, b in ranges:
            path = out / f"vsec_{vid}_{int(a)}.mp4"
            reel_clips.download_clip(vid, int(a), int(b), int(v.get("fallback_height", 144)), path, speaker_map.proxy_url())
            hit = path if path.exists() else next(iter(sorted(out.glob(path.stem + ".*"))), None)
            if hit is not None:
                got.append((a, b, hit))
        if not got:
            raise
        if stats is not None:
            stats["fallback"] = stats.get("fallback", 0) + len(got)
        return got


def unheard(b: dict) -> bool:
    """مقطع فُحص صوته فلم يطابق كلامه المحفوظ."""
    return (b.get("audio") or {}).get("status") == "no_match"
