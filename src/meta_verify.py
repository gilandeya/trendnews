"""التحقق من مقاطع الموضوع بالصوت قبل أن تُعرض للاختيار (خطة 15/11، الخطوة «ب»).

لماذا: نافذة Gemini تقديرية، وما لا يطابق مسموعُه نصَّه كان يُكتشف في التركيب بعد أن اختار صاحب المشروع الأسئلة وكُتب السيناريو
ودُفع ثمنه (20 سيناريو فاشلًا من 45، وقضية 1881 أعادت الاختيار كله). هنا يُنزَّل صوت نوافذ المقاطع وحدها (أقسام، أدنى جودة)
ويُفرَّغ ويُطابَق الكلام المحفوظ بالكلمات؛ المطابق يأخذ حدّيه من الصوت وتُحفظ كلماته فلا يفرّغه التركيب ثانية، وغير المطابق
لا يُعرض. يجري في خطوة الأسئلة (reel-render.yml) لأن فيها البروكسي والمفرِّغ؛ خطوة السيناريو (publish.yml) بلا أيٍّ منهما.

لا يرفع أبدًا: عطل التحقق يترك المقاطع كما هي ويبقى حارس التركيب (حذف المقطع وإعادة الاختيار) شبكة أمان.
الكلمات كلام قناة: تُحفظ على المقطع في الملف الخاص وحده.

المهلة لا تُتجاوز (قضية 1904): تنزيل صوت فيديو واحد أخذ 27 دقيقة ونصفًا (المهلة ثمانٍ) فتأخرت قضية الأسئلة 38 دقيقة ولم يُفحص
مقطع واحد، والموضوع التالي قُطع عند مهلة التشغيلة. كانت المهلة تُفحص بين الفيديوهات فقط، وتنزيل yt-dlp داخل العملية لا يُقطع. الآن
تنزيل كل فيديو في عملية فرعية (`--fetch`) تُقتل هي وffmpeg عند المهلة، وعدة فيديوهات معًا، والتفريغ يجري أثناء التنزيل بترتيب
الأولوية؛ والطريق الأول طريق التركيب المجرَّب (`download: clip`) لأن الصوت وحده فشل أو تأخر في كل تشغيل حقيقي.
"""
from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import sys
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
    original = str(b.get("text_original") or "")
    # لغة الكلام لا لغة القناة (القضية 1991): مقطع «zh» من CCTV كلامه فارسي، وإجبار المفرِّغ على الصينية يترجم ولا يسمع
    lang = (reel_clips.speech_language(original, b.get("language")) if cfg.path("reel.render.exact.language_from_text", True)
            else b.get("language")) or None
    rec: dict = {"source": "meta_verify", "orig": [b["start"], b["end"]], "lang": lang or ""}
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
            words = deps.transcribe(path, lang, cfg) or []
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


class _Local:
    """تنزيل محقون (الاختبار) يجري في العملية نفسها فورًا، بواجهة العملية الفرعية نفسها."""

    def __init__(self, fn, vid: str, ranges: list, out: Path):
        self._sections: list = []
        self._error = ""
        try:
            self._sections = list(fn(vid, out, ranges))
        except Exception as exc:  # noqa: BLE001 -- عطل تنزيل فيديو: مقاطعه بلا حكم
            self._error = _safe(exc)

    @classmethod
    def failed(cls, exc: Exception) -> "_Local":
        """تنزيل لم يبدأ أصلًا (تعذّر تشغيل عمليته): فيديوه وحده بلا حكم."""
        self = cls(lambda *a: [], "", [], Path("."))
        self._error = _safe(exc)
        return self

    def done(self) -> bool:
        return True

    def sections(self) -> list:
        return self._sections

    def error(self) -> str:
        return self._error

    def bytes(self) -> int:
        return sum(Path(f).stat().st_size for _, _, f in self._sections if Path(f).exists())

    def kill(self) -> None:
        return None


class _Child:
    """تنزيل أقسام فيديو واحد في عملية فرعية لها مجموعة عملياتها: تُقتل هي وffmpeg الذي يشغّله yt-dlp معًا عند المهلة (قتل العملية
    وحدها يترك ffmpeg ينزّل عبر البروكسي حتى آخر التشغيلة). تكتب نتيجتها بعد كل قسم، فالقتل يُبقي ما اكتمل."""

    def __init__(self, vid: str, ranges: list, out: Path, argv: list | None = None):
        self.result = Path(out) / f"fetch_{vid}.json"
        # «=» لأن معرّف يوتيوب قد يبدأ بشرطة فيقرؤه argparse خيارًا
        argv = argv or [sys.executable, "-m", "src.meta_verify", f"--fetch={vid}", f"--out={out}",
                        f"--ranges={json.dumps([list(r) for r in ranges])}", f"--result={self.result}"]
        self.proc = subprocess.Popen(argv, cwd=str(Path(__file__).resolve().parent.parent), start_new_session=True)
        self.killed = False

    def done(self) -> bool:
        return self.proc.poll() is not None

    def _read(self) -> dict:
        try:
            got = json.loads(self.result.read_text(encoding="utf-8"))
            return got if isinstance(got, dict) else {}
        except (OSError, ValueError):
            return {}

    def sections(self) -> list:
        return [(a, b, Path(f)) for a, b, f in self._read().get("sections") or []]

    def error(self) -> str:
        err = str(self._read().get("error") or "")
        if not err and not self.killed and self.done() and self.proc.returncode:
            err = f"انتهى التنزيل برمز {self.proc.returncode}"
        return err

    def bytes(self) -> int:
        return int(self._read().get("bytes") or 0)

    def kill(self) -> None:
        if self.done():
            return
        self.killed = True
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except OSError:
            self.proc.kill()
        try:
            self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass


def video_limit(videos: int, cfg: Any) -> float:
    """مهلة الفيديو الواحد. الحدّ موجود ليُفرغ خانةً لفيديو ينتظر، فحين لا ينتظر أحد (الفيديوهات ≤ الخانات) المهلة كلها له.
    قضية 1916: كل مقاطع الموضوع في فيديوين، فقُتل كلاهما عند 150 ث ولم يُفحص صوت مقطع واحد ونصف المهلة لم يُستعمل. دالة خالصة."""
    v = _vcfg(cfg)
    parallel = max(1, int(v.get("parallel", 3)))
    waves = max(1, -(-max(1, videos) // parallel))
    return max(float(v.get("video_seconds", 150)), float(v.get("budget_seconds", 300)) / waves)


def verify(targets: list[dict], cfg: Any, deps: bite_audio.Deps | None = None, launch=None,
           clock=time.monotonic, sleep=time.sleep) -> dict:
    """يتحقق من المقاطع بترتيبها حتى max_bites أو budget_seconds ويكتب على كل مقطع فُحص سجله. يعيد أرقامًا وحدها
    (تُحفظ في ملف الحالة العام): {checked, ok, no_match, failed, no_text, left, audio_seconds, skipped, seconds, cut_off}. لا يرفع.

    المهلة حدّ فعلي: حتى `parallel` تنزيلًا معًا (launch(vid, ranges, out) ← كائن له done/sections/error/bytes/kill)، وكل مقطع
    يُفرَّغ حين ينزل قسمه دون انتظار بقية الفيديوهات، وعند المهلة يُقتل ما لم ينتهِ ويبقى ما لم يُفحص معروضًا بلا 🎧."""
    from . import costs
    stats: dict = {"checked": 0, "ok": 0, "no_match": 0, "failed": 0, "no_text": 0, "left": 0, "audio_seconds": 0, "skipped": ""}
    began = clock()
    try:
        v = _vcfg(cfg)
        deps = deps or default_deps()
        if launch is None:
            injected = deps.download_sections
            launch = (lambda vid, ranges, out: _Local(injected, vid, ranges, out)) if injected else _Child
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
        began = clock()        # المهلة لما بعد الفحص الذاتي (تحميل نموذج التفريغ أول مرة ليس من وقت الموضوع)
        deadline = began + float(v.get("budget_seconds", 300))
        wide = max(float(v.get("margin", 8)), float(v.get("wide_margin", 20)))
        by_video: dict[str, list[dict]] = {}
        for b in todo:
            by_video.setdefault(str(b.get("video_id")), []).append(b)
        ranges = {vid: bite_audio.merge_windows([window(b, wide) for b in group], float(v.get("section_merge_gap", 20)))
                  for vid, group in by_video.items()}
        queue = list(by_video)             # الفيديوهات بترتيب أول مقطع لها في الأولوية
        parallel = max(1, int(v.get("parallel", 3)))
        poll = float(v.get("poll_seconds", 1))
        # فيديو واحد لا يحجز خانته أكثر من هذا: ثلاثة تنزيلات عالقة كانت ستأكل المهلة كلها وتمنع بقية الفيديوهات
        per_video = video_limit(len(by_video), cfg)
        running: dict[str, Any] = {}
        finished: dict[str, Any] = {}
        started: dict[str, float] = {}
        cut: set[str] = set()
        pending = list(todo)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            try:
                while pending and clock() <= deadline:
                    while queue and len(running) < parallel:
                        vid = queue.pop(0)
                        started[vid] = clock()
                        try:
                            running[vid] = launch(vid, ranges[vid], tmp)
                        except Exception as exc:  # noqa: BLE001 -- تعذّر تشغيل تنزيل فيديو لا يوقف فحص غيره
                            finished[vid] = _Local.failed(exc)
                    for vid in list(running):
                        h = running[vid]
                        if not h.done():
                            if clock() - started[vid] <= per_video:
                                continue
                            h.kill()
                            cut.add(vid)
                        finished[vid] = running.pop(vid)
                    acted = False
                    for b in pending:
                        vid = str(b.get("video_id"))
                        h = running.get(vid) or finished.get(vid)
                        if h is None:
                            continue           # لم يبدأ تنزيل فيديوه بعد
                        source = h.sections()
                        if bite_audio._section_for(source, *window(b, wide)) is not None:
                            rec = check_bite(b, source, deps, cfg, tmp)
                        elif vid in finished:
                            rec = {"source": "meta_verify", "status": "failed",
                                   "error": ("تجاوز تنزيل قسمه مهلته" if vid in cut else h.error())
                                   or "لا قسم منزَّل يغطي نافذة المقطع"}
                        else:
                            continue           # قسمه ما زال ينزل
                        apply(b, rec, cfg)
                        stats["checked"] += 1
                        stats[rec["status"]] = stats.get(rec["status"], 0) + 1
                        pending.remove(b)
                        acted = True
                        break                  # مقطع واحد ثم تُراجَع التنزيلات: التفريغ ثوانٍ وقد انتهى غيره
                    if not acted:
                        sleep(poll)
            finally:
                # ما لم ينتهِ عند المهلة يُقتل (ومعه ffmpeg): لا تنزيل يبقى خلف الخطوة يستهلك البروكسي
                for h in running.values():
                    h.kill()
                handles = list(running.values()) + list(finished.values())
                stats["cut_off"] = len(running) + len(cut)
                stats["audio_seconds"] = int(sum(b1 - a1 for h in handles for a1, b1, _ in h.sections()))
                costs.add("proxy_bytes", sum(h.bytes() for h in handles))
                err = next((h.error() for h in handles if h.error()), "")
                if err:
                    stats["download_error"] = err[:160]
            stats["left"] += len(pending)
            if pending and not stats["checked"]:
                # لا مقطع فُحص: يُقال في القضية بدل الصمت (قضية 1904 عُرضت بلا 🎧 وبلا سطر يفسّره)
                stats["skipped"] = str(cfg.path("youtube.meta_topics.qa.texts.verify_timeout", "") or "انتهت مهلة الفحص قبل أي مقطع")
    except Exception as exc:  # noqa: BLE001 -- التحقق تحسين لا شرط: عطله لا يُسقط أسئلة الموضوع
        log.warning("التحقق من مقاطع الموضوع: %s", exc)
        stats["skipped"] = f"{type(exc).__name__}: {str(exc)[:100]}"
    stats["seconds"] = int(round(clock() - began))
    log.info("فحص صوت المقاطع: %s", {k: val for k, val in stats.items() if val})
    return stats


def download_sections(vid: str, out: Path, ranges: list, cfg: Any, stats: dict | None = None, progress=None) -> list:
    """أقسام نوافذ فيديو واحد [(بداية، نهاية، ملف)]. `download: clip` (الافتراضي) طريق التركيب المجرَّب لكل قسم
    (reel_clips.download_clip: صورة بأدنى دقة وصوت، بدرجاته الثلاث)؛ `audio` الصوت وحده أولًا ثم ذاك احتياطًا (`fallback_video`).

    لماذا لم يعد الصوت وحده الطريق الأول: ريل 1890 فشل تنزيله لكل الفيديوهات («ffmpeg exited with code 251») بعد ثماني دقائق،
    وقضية 1904 نجح لفيديو واحد بعد 27 دقيقة ونصف؛ والطريق نفسه ينزّل مقطع التركيب في نحو دقيقة. قسم تعطّل لا يُسقط بقية أقسام
    الفيديو، ولا يرفع إلا إن لم ينزل قسم. progress(a, b, file) بعد كل قسم؛ stats: download_error (أول سبب بلا أسرار) وbytes وfallback."""
    from . import reel_clips, speaker_map
    v = _vcfg(cfg)
    stats = stats if stats is not None else {}
    fallback = False
    if str(v.get("download", "clip")) == "audio":
        try:
            got = bite_audio._real_download(vid, out, cfg, ranges)
            for a, b, f in got:
                stats["bytes"] = stats.get("bytes", 0) + (Path(f).stat().st_size if Path(f).exists() else 0)
                if progress:
                    progress(a, b, f)
            return got
        except Exception as exc:  # noqa: BLE001 -- الاحتياط أدناه؛ ما لم ينجح يرفع
            if not stats.get("download_error"):
                stats["download_error"] = _safe(exc)
            if not v.get("fallback_video", True):
                raise
            fallback = True
    got, first = [], None
    for a, b in ranges:
        path = out / f"vsec_{vid}_{int(a)}.mp4"
        try:
            res = reel_clips.download_clip(vid, int(a), int(b), int(v.get("clip_height", 144)), path, speaker_map.proxy_url()) or {}
        except Exception as exc:  # noqa: BLE001 -- قسم واحد: مقاطعه بلا حكم والبقية تمضي
            first = first or exc
            if not stats.get("download_error"):
                stats["download_error"] = _safe(exc)
            continue
        hit = path if path.exists() else next(iter(sorted(out.glob(path.stem + ".*"))), None)
        if hit is None:
            continue
        got.append((a, b, hit))
        stats["bytes"] = stats.get("bytes", 0) + int(res.get("bytes") or 0)
        if progress:
            progress(a, b, hit)
    if not got:
        raise first or RuntimeError("لم يُنتج التنزيل ملفًا")
    if fallback:
        stats["fallback"] = stats.get("fallback", 0) + len(got)
    return got


def _fetch_main(args) -> int:
    """العملية الفرعية: تنزّل أقسام فيديو واحد وتكتب {sections, bytes, error} بعد كل قسم (كتابة ذرّية: الأب يقرأ أثناء التنزيل)."""
    from .config import load_config
    cfg = load_config()
    result = Path(args.result)
    state: dict = {"sections": [], "bytes": 0, "error": ""}
    stats: dict = {}

    def flush() -> None:
        state["bytes"], state["error"] = int(stats.get("bytes", 0)), str(stats.get("download_error", ""))
        part = result.with_suffix(".part")
        part.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(part, result)

    def progress(a, b, path) -> None:
        state["sections"].append([a, b, str(path)])
        flush()
    try:
        download_sections(args.fetch, Path(args.out), [tuple(r) for r in json.loads(args.ranges)], cfg, stats, progress)
    except Exception as exc:  # noqa: BLE001 -- السبب في ملف النتيجة؛ رمز الخروج لا يحمل معنى
        stats.setdefault("download_error", _safe(exc))
    flush()
    return 0


def unheard(b: dict) -> bool:
    """مقطع فُحص صوته فلم يطابق كلامه المحفوظ."""
    return (b.get("audio") or {}).get("status") == "no_match"


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="تنزيل أقسام فيديو واحد لفحص صوت المقاطع (عملية فرعية لـverify)")
    ap.add_argument("--fetch", required=True, help="معرّف الفيديو")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ranges", required=True, help="JSON: [[بداية، نهاية]، …]")
    ap.add_argument("--result", required=True)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    return _fetch_main(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
