"""خريطة متكلمي الحلقة (Issues #1696 S0، S1، S4): وجوه الحلقة كاملة مجمَّعة (YuNet/SFace على المعالج) وأسماؤها من شريط القناة
بقراءة موجَّهة لكل مجموعة وتصويت بالأغلبية، ثم إسناد لحظة من مقطع إلى مجموعة واسمها. تستعملها أداة القياس
tools/speaker_map_probe.py والتركيب (reel_render._map_check). كل العتبات في config.yaml: speaker_map.
القياس أثبتها 7 من 7 على الريل 02b4436a2b66 (2026-10-23) حيث أخطأت حرّاس المقطع الواحد (Q10–Q16)."""
from __future__ import annotations

import time
from pathlib import Path


# ──────────────────────────── دوال خالصة ────────────────────────────


def _cfg(cfg, key: str, default):
    value = cfg.path(f"speaker_map.{key}")
    return default if value is None else value


def cluster_faces(embeddings, cfg) -> list[list[int]]:
    """تجميع البصمات بتشابه جيب التمام ≥ speaker_map.cluster_threshold. يعيد قوائم فهارس البصمات. مرحلتان: مرور متتابع يضم كل بصمة
    إلى أقرب مركز بلغ العتبة وإلا يفتح مجموعة (يبقي الكلفة خطية في عدد الوجوه، وهي بالآلاف)، ثم دمج هرمي لمراكز المجموعات
    (الأقرب فالأقرب بمتوسط موزون بالحجم) حتى لا يبقى زوج بلغ العتبة، فلا يعتمد الناتج على ترتيب الظهور."""
    import numpy as np
    thr = float(_cfg(cfg, "cluster_threshold", 0.363))
    if len(embeddings) == 0:
        return []
    arr = np.asarray(embeddings, dtype=np.float64)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    arr = arr / np.where(norms == 0, 1.0, norms)
    sums: list = []          # مجموع البصمات المطبَّعة لكل مجموعة (المركز = المجموع مطبَّعًا)
    members: list[list[int]] = []

    def unit(v):
        n = float(np.linalg.norm(v))
        return v / n if n else v

    for i, vec in enumerate(arr):
        best, best_sim = None, thr
        for k, s in enumerate(sums):
            sim = float(np.dot(unit(s), vec))
            if sim >= best_sim:
                best, best_sim = k, sim
        if best is None:
            sums.append(vec.copy())
            members.append([i])
        else:
            sums[best] = sums[best] + vec
            members[best].append(i)
    while len(sums) > 1:
        best_pair, best_sim = None, thr
        for a in range(len(sums)):
            for b in range(a + 1, len(sums)):
                sim = float(np.dot(unit(sums[a]), unit(sums[b])))
                if sim >= best_sim:
                    best_pair, best_sim = (a, b), sim
        if best_pair is None:
            break
        a, b = best_pair
        sums[a] = sums[a] + sums[b]
        members[a] = members[a] + members[b]
        del sums[b], members[b]
    return [sorted(m) for m in members]


def chyron_diffs(bands) -> list[float]:
    """فرق كل لقطة عن سابقتها في منطقة الشريط: متوسط |الفرق| ÷ 255 (القيمة 0 للأولى)."""
    import numpy as np
    out = [0.0]
    for prev, cur in zip(bands, bands[1:]):
        a, b = np.asarray(prev, dtype=np.float64).ravel(), np.asarray(cur, dtype=np.float64).ravel()
        out.append(float(np.abs(a - b).mean() / 255.0))
    return out[:len(bands)]


def chyron_changes(bands, cfg) -> list[int]:
    """فهارس اللقطات التي تُقرأ: تغيّر الشريط فوق speaker_map.chyron_change. من كل سلسلة لقطات متتالية متغيّرة (ظهور الشريط
    متحركًا) تُؤخذ آخرها لأنها المستقرة، فيُكشف تغيّر الشريط مرة واحدة لا في كل لقطة منه. دالة خالصة."""
    thr = float(_cfg(cfg, "chyron_change", 0.03))
    changed = [d > thr for d in chyron_diffs(bands)]
    return [i for i, c in enumerate(changed) if c and not (i + 1 < len(changed) and changed[i + 1])]


def vote_names(reads, faces_per_frame, cfg, host=None) -> dict:
    """تصويت الأغلبية: كل قراءة تسمّي شخصًا (name_kind == person) تعطي صوتها للمجموعة الأكبر وجهًا في لقطتها
    (faces_per_frame[frame] = [(مجموعة، مساحة)]). قراءة name_is_speaker == "no" اسمها للمقدّم لا للمتكلم الظاهر: لا تُعطى لأي ضيف،
    وتُعطى للمجموعة host إن عُرفت؛ و"unsure" تُهمل. الاسم المعتمد لمجموعة هو الأكثر أصواتًا بشرط ≥ speaker_map.min_votes وتفوّقه
    على الثاني تفوّقًا صريحًا (التعادل لا يسمّي). يعيد {مجموعة: {name, votes: {اسم: عدد}}} للمجموعات التي نالت صوتًا. دالة خالصة."""
    min_votes = int(_cfg(cfg, "min_votes", 2))
    tally: dict = {}
    for r in reads:
        name = str(r.get("name") or "").strip()
        if not name or r.get("name_kind", "person") != "person":
            continue
        flag = r.get("name_is_speaker", "yes")
        if flag == "no":
            target = host
        elif flag == "yes" and r.get("cluster") is not None:
            # قراءة موجَّهة (S1): اللقطة اختيرت لأن وجه هذه المجموعة وحده فيها أو غالب عليها، فالاسم لها لا لأكبر وجه
            target = r["cluster"]
        elif flag == "yes":
            frame = r.get("frame")
            faces = faces_per_frame[frame] if isinstance(frame, int) and 0 <= frame < len(faces_per_frame) else []
            target = max(faces, key=lambda f: f[1])[0] if faces else None
        else:
            target = None
        if target is None:
            continue
        votes = tally.setdefault(target, {})
        votes[name] = votes.get(name, 0) + 1
    out = {}
    for cid, votes in tally.items():
        ranked = sorted(votes.items(), key=lambda kv: -kv[1])
        top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0
        out[cid] = {"name": top[0] if top[1] >= min_votes and top[1] > second else None, "votes": dict(votes)}
    # الاسم الواحد لوجه واحد (S1): القياس الأول سمّى المقدّم والحربي معًا «منيف عماش الحربي» (2 مقابل 7 أصوات)؛
    # يبقى الاسم للمجموعة الأكثر أصواتًا له، وتعادلها لا يسمّي أيًّا منها
    by_name: dict = {}
    for cid, row in out.items():
        if row["name"]:
            by_name.setdefault(row["name"], []).append(cid)
    for name, cids in by_name.items():
        if len(cids) < 2:
            continue
        best = max(out[c]["votes"][name] for c in cids)
        winners = [c for c in cids if out[c]["votes"][name] == best]
        for c in cids:
            if len(winners) > 1 or c != winners[0]:
                out[c]["name"] = None
    return out


def pick_host(clusters, duration, cfg):
    """المقدّم = المجموعة الأكثر ظهورًا بين من يمتد ظهورها (أول ظهور إلى آخره) على ≥ speaker_map.host_span من مدة الحلقة؛
    بلا ممتدة ← None. clusters = [{id, count, first, last}]. دالة خالصة."""
    span = float(_cfg(cfg, "host_span", 0.6))
    if not clusters or not duration:
        return None
    wide = [c for c in clusters if (c["last"] - c["first"]) / float(duration) >= span]
    return max(wide, key=lambda c: c["count"])["id"] if wide else None


def pick_read_frames(faces_per_frame, cfg) -> list[tuple[int, int]]:
    """لقطات قراءة الشريط الموجَّهة (S1): لكل مجموعة ظهر وجهها ≥ speaker_map.min_cluster_faces مرة، حتى reads_per_cluster لقطة
    موزّعة على زمن ظهورها، يكون وجهها فيها وحده، وإلا غالبًا (≥ dominant_share من مساحة الوجوه). القياس الأول قرأ الأشرطة عند تغيّرها
    وأعطى الاسم لأكبر وجه، فلم يصل اسم البخيتي ولا بكري إلى وجهيهما لأن تغيّرات الشريط في الشاشة المقسومة والتقارير لا عند ظهور الضيف
    وحده. الأكثر ظهورًا أولًا، والسقف max_chyron_reads للحلقة كلها. يعيد [(لقطة، مجموعة)] مرتبة بالزمن. دالة خالصة."""
    min_faces = int(_cfg(cfg, "min_cluster_faces", 20))
    per = int(_cfg(cfg, "reads_per_cluster", 4))
    share = float(_cfg(cfg, "dominant_share", 0.6))
    cap = int(_cfg(cfg, "max_chyron_reads", 40))
    counts: dict = {}
    solo: dict = {}
    dominant: dict = {}
    for i, faces in enumerate(faces_per_frame):
        total = sum(a for _, a in faces) or 0
        for cid, area in faces:
            counts[cid] = counts.get(cid, 0) + 1
        if len(faces) == 1:
            solo.setdefault(faces[0][0], []).append(i)
        elif faces and total:
            cid, area = max(faces, key=lambda f: f[1])
            if area / total >= share:
                dominant.setdefault(cid, []).append(i)

    def spread(frames: list[int], k: int) -> list[int]:
        if len(frames) <= k:
            return list(frames)
        return [frames[round(j * (len(frames) - 1) / (k - 1))] for j in range(k)] if k > 1 else [frames[len(frames) // 2]]

    out: list[tuple[int, int]] = []
    for cid in sorted(counts, key=lambda c: -counts[c]):
        if counts[cid] < min_faces:
            continue
        pool = solo.get(cid) or dominant.get(cid) or []
        out.extend((f, cid) for f in spread(pool, per))
    return sorted(out[:cap])


# ──────────────────────────── مقارنة الأسماء ────────────────────────────


def _tokens(name: str) -> set[str]:
    from src import youtube_extract
    return {t for t in youtube_extract._normalize_for_anchor(str(name or "")).split() if len(t) >= 3}


def names_match(expected: str | None, got: str | None) -> bool:
    """يطابق إن اشترك الاسمان في كلمتين (أو في كلمة إن كان أحدهما كلمة واحدة)، بعد الطيّ الإملائي."""
    a, b = _tokens(expected or ""), _tokens(got or "")
    if not a or not b:
        return False
    need = 1 if min(len(a), len(b)) < 2 else 2
    return len(a & b) >= need


# ──────────────────────────── التنزيل واللقطات ────────────────────────────


def proxy_url() -> str | None:
    from src import proxy_config
    cfg = proxy_config.get_proxy_config()
    return cfg.url if cfg is not None else None


def episode_opts(out: Path, height: int, proxy, capture, hook) -> dict:
    """خيارات yt-dlp لتنزيل الحلقة كاملة صورةً فقط، مبنية على reel_clips._ydl_opts نفسها. download_ranges يُحذف لا يُضبط على None:
    yt-dlp يستدعي القيمة إن وُجد المفتاح، فـNone يرفع «'NoneType' object is not callable» (أول تشغيلة حقيقية لـS0 فشلت به)."""
    from src import reel_clips
    opts = reel_clips._ydl_opts(out, height, None, False, proxy, capture, hook)
    opts.pop("download_ranges", None)
    opts["format"] = f"bv*[height<={height}]/b[height<={height}]/worst"
    opts.pop("merge_output_format", None)
    return opts


def download_episode(video_id: str, height: int, out_dir: Path, proxy: str | None, retries: int = 2,
                     wait: float = 20.0) -> dict:
    """الحلقة كاملة صورةً فقط (الصوت لا يلزم الوجوه) بآلة التنزيل القائمة (yt-dlp عبر البروكسي، reel_clips._ydl_opts)."""
    import yt_dlp

    from src import reel_clips
    last: Exception | None = None
    for attempt in range(retries + 1):
        capture, seen = reel_clips.TailCapture(), {}

        def hook(d, seen=seen, capture=capture):
            got = d.get("downloaded_bytes")
            if isinstance(got, int):
                seen[d.get("filename") or "?"] = max(seen.get(d.get("filename") or "?", 0), got)
            capture.note_format(d.get("info_dict"))

        out = out_dir / f"{video_id}.mp4"
        opts = episode_opts(out, height, proxy, capture, hook)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
            files = sorted(out_dir.glob(f"{video_id}.*"))
            if not files:
                raise RuntimeError("لا ملف ناتج")
            return {"path": files[0], "size_bytes": files[0].stat().st_size, "proxy_bytes": sum(seen.values()),
                    "format_id": capture.format_id}
        except Exception as exc:  # noqa: BLE001 -- يُعاد ثم يرفع آخر سبب
            last = exc
            time.sleep(wait)
    raise RuntimeError(reel_clips.scrub_text(str(last))[:200])


def video_duration(path: Path) -> float | None:
    from src import reel_render
    return reel_render.probe_duration(path)


def extract_frames(video: Path, out_dir: Path, step: float, height: int, start: float = 0.0, length: float | None = None) -> list[Path]:
    """لقطة كل step ثانية JPEG بارتفاع height (ffmpeg)؛ المسار i يقابل الثانية start + i × step."""
    import subprocess
    out_dir.mkdir(parents=True, exist_ok=True)
    from src import reel
    # نسخة pip المضمّنة أولًا: تثبيت ffmpeg بـapt علّق القياس 28 دقيقة (2026-10-23) والقياس لا يحتاج ffprobe
    cmd = [reel.ffmpeg_path() or "ffmpeg", "-y", "-v", "error"]
    if start:
        cmd += ["-ss", f"{start:.2f}"]
    if length:
        cmd += ["-t", f"{length:.2f}"]
    cmd += ["-i", str(video), "-vf", f"fps=1/{step},scale=-2:{height}", "-q:v", "2", str(out_dir / "f%05d.jpg")]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg: " + " ".join((proc.stderr or "").split())[-200:])
    return sorted(out_dir.glob("f*.jpg"))


# ──────────────────────────── الوجوه ────────────────────────────


def fetch_models(cfg, model_dir: Path) -> tuple[Path, Path]:
    """نموذجا ONNX من opencv_zoo إلى مجلد مؤقت (لا يُودَعان في المستودع). المرجع والنطاق في config."""
    import urllib.request
    mcfg = _cfg(cfg, "models", {})
    ref = mcfg.get("ref", "main")
    paths = []
    for key in ("yunet", "sface"):
        rel = mcfg[key]
        target = model_dir / Path(rel).name
        if not target.exists():
            urllib.request.urlretrieve(f"https://github.com/opencv/opencv_zoo/raw/{ref}/{rel}", target)  # noqa: S310
        paths.append(target)
    return paths[0], paths[1]


class FaceEngine:
    """كشف YuNet وبصمة SFace على المعالج (OpenCV)؛ لا نموذج لغوي."""

    def __init__(self, yunet: Path, sface: Path, cfg):
        import cv2
        self.cv2 = cv2
        self.score = float(_cfg(cfg, "score_threshold", 0.8))
        self.min_face = float(_cfg(cfg, "min_face", 0.10))
        self.det = cv2.FaceDetectorYN.create(str(yunet), "", (320, 320), self.score)
        self.rec = cv2.FaceRecognizerSF.create(str(sface), "")

    def faces(self, img, with_embedding: bool = True) -> list[dict]:
        """وجوه اللقطة الأكبر من min_face من ارتفاعها: [{box: (x,y,w,h), area, embedding?}]."""
        h, w = img.shape[:2]
        self.det.setInputSize((w, h))
        _, rows = self.det.detect(img)
        out = []
        for row in (rows if rows is not None else []):
            x, y, fw, fh = (float(v) for v in row[:4])
            if fh < self.min_face * h:
                continue
            item = {"box": (x, y, fw, fh), "area": fw * fh}
            if with_embedding:
                aligned = self.rec.alignCrop(img, row)
                item["embedding"] = self.rec.feature(aligned).ravel().tolist()
            out.append(item)
        return out


def chyron_band(img, cfg):
    """منطقة الشريط الأسفل مصغَّرة رمادية 64×8 (متجه مسطَّح) لحساب التغيّر."""
    import cv2
    lo, hi = (float(v) for v in _cfg(cfg, "chyron_band", [0.70, 0.95]))
    h = img.shape[0]
    crop = img[int(h * lo):int(h * hi), :]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (64, 8), interpolation=cv2.INTER_AREA).ravel()


def read_chyrons(frames_idx: list, images: list, cfg, counters: dict) -> list[dict]:
    """قراءة الشريط للقطات المختارة بنداء Haiku مجمَّع في صفائح، بأداة read_lower_third القائمة نفسها (reel_render.call_chyron_model).
    اللقطة تُكبَّر إلى read_width عرضًا قبل الإرسال (التنزيل منخفض الدقة). فشل صفيحة يُسجَّل ويُتخطّى."""
    import cv2

    from src import reel_render
    sheet = max(1, int(_cfg(cfg, "chyron_sheet", 4)))
    width = int(_cfg(cfg, "read_width", 960))
    from anthropic import Anthropic

    from src.config import env
    client = Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    reads: list[dict] = []
    pairs = [p if isinstance(p, tuple) else (p, None) for p in frames_idx]   # (لقطة، مجموعة) للقراءة الموجَّهة
    for s in range(0, len(pairs), sheet):
        part = pairs[s:s + sheet]
        jpegs = []
        for i, _ in part:
            img = images[i]
            scale = width / img.shape[1]
            big = cv2.resize(img, (width, int(img.shape[0] * scale)), interpolation=cv2.INTER_CUBIC)
            jpegs.append(cv2.imencode(".jpg", big, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes())
        counters["haiku_calls"] += 1
        try:
            results = reel_render.call_chyron_model(jpegs, cfg, client)
        except Exception as exc:  # noqa: BLE001 -- صفيحة متعثرة لا تُسقط الباقي
            counters["haiku_errors"].append(f"{type(exc).__name__}: {str(exc)[:80]}")
            continue
        for (i, cid), res in zip(part, results):
            if not res.get("has_caption"):
                continue
            name = res.get("name_arabic") or res.get("name_original") or ""
            reads.append({"frame": i, "cluster": cid, "name": name, "name_kind": res.get("name_kind", "person"),
                          "name_is_speaker": res.get("name_is_speaker", "unsure")})
    counters["chyron_reads"] = len(frames_idx)
    return reads


# ──────────────────────────── بناء الخريطة والإسناد ────────────────────────────


def build_map(video: Path, work: Path, cfg, engine: FaceEngine, timings: dict, counters: dict,
              preview_dir: Path | None = None) -> dict:
    import cv2
    import numpy as np
    step = float(_cfg(cfg, "step", 2))
    height = int(_cfg(cfg, "height", 240))
    duration = video_duration(video) or 0.0

    t0 = time.monotonic()
    paths = extract_frames(video, work / "frames", step, height)
    timings["frames"] = round(time.monotonic() - t0, 2)
    counters["frames"] = len(paths)

    t0 = time.monotonic()
    images = [cv2.imread(str(p)) for p in paths]
    flat: list[tuple[int, dict]] = []
    per_frame_faces = []
    for i, img in enumerate(images):
        faces = engine.faces(img) if img is not None else []
        per_frame_faces.append(faces)
        flat.extend((i, f) for f in faces)
    timings["faces"] = round(time.monotonic() - t0, 2)
    counters["faces"] = len(flat)

    t0 = time.monotonic()
    groups = cluster_faces([f["embedding"] for _, f in flat], cfg)
    timings["cluster"] = round(time.monotonic() - t0, 2)
    counters["clusters"] = len(groups)
    owner = {}
    for cid, members in enumerate(groups):
        for m in members:
            owner[m] = cid
    faces_per_frame: list[list[tuple[int, float]]] = [[] for _ in images]
    summary = {cid: {"id": cid, "count": 0, "first": None, "last": None} for cid in range(len(groups))}
    for k, (i, f) in enumerate(flat):
        cid = owner[k]
        faces_per_frame[i].append((cid, f["area"]))
        row = summary[cid]
        row["count"] += 1
        sec = i * step
        row["first"] = sec if row["first"] is None else min(row["first"], sec)
        row["last"] = sec if row["last"] is None else max(row["last"], sec)
    centroids = {}
    for cid, members in enumerate(groups):
        v = np.mean([flat[m][1]["embedding"] for m in members], axis=0)
        centroids[cid] = v / (np.linalg.norm(v) or 1.0)
    clusters = list(summary.values())
    host = pick_host(clusters, duration, cfg)

    t0 = time.monotonic()
    bands = [chyron_band(im, cfg) if im is not None else np.zeros(512) for im in images]
    changes = chyron_changes(bands, cfg)
    counters["chyron_changes"] = len(changes)
    targets = pick_read_frames(faces_per_frame, cfg)   # S1: التغيّر يُعدّ للتشخيص وحده، والقراءة موجَّهة لكل مجموعة
    counters["read_targets"] = len(targets)
    reads = read_chyrons(targets, images, cfg, counters) if targets else []
    counters["reads_with_name"] = sum(1 for r in reads if r.get("name"))
    timings["chyron"] = round(time.monotonic() - t0, 2)

    votes = vote_names(reads, faces_per_frame, cfg, host=host)
    if preview_dir is not None:
        preview_dir.mkdir(parents=True, exist_ok=True)
        for cid, members in enumerate(groups):
            i, f = flat[members[0]]
            x, y, w, h = (int(v) for v in f["box"])
            crop = images[i][max(0, y):y + h, max(0, x):x + w]
            if crop.size:
                cv2.imwrite(str(preview_dir / f"cluster_{cid}.jpg"), crop)
    rows = []
    for c in clusters:
        v = votes.get(c["id"], {"name": None, "votes": {}})
        rows.append({**c, "name": v["name"], "votes": v["votes"], "is_host": c["id"] == host})
    return {"duration": duration, "map": rows, "host": host, "centroids": centroids, "reads": len(reads),
            # تفصيل القراءات للتشخيص (S1): أي لقطة قُرئت لأي مجموعة وماذا قال النموذج — بلا صور
            "read_log": [{"sec": r["frame"] * step, "cluster": r.get("cluster"), "name": r.get("name"),
                          "kind": r.get("name_kind"), "speaker": r.get("name_is_speaker")} for r in reads]}


def assign_at(video: Path, work: Path, t: float, built: dict, cfg, engine: FaceEngine, length: float | None = None) -> dict:
    """اسم المتكلم عند الثانية t: لقطات [t, t+window] بمعدل assign_fps، الوجه المتكلم بـreel_render.speaker_track إن حُسم وإلا
    الأكبر، ثم مجموعته بأقرب مركز (جيب التمام ≥ العتبة) ثم اسمها من الخريطة."""
    import cv2
    import numpy as np

    from src import reel_render
    window = float(length if length is not None else _cfg(cfg, "assign_window", 6))
    fps = float(_cfg(cfg, "assign_fps", 4))
    thr = float(_cfg(cfg, "cluster_threshold", 0.363))
    paths = extract_frames(video, work / f"assign_{int(t)}", 1.0 / fps, int(_cfg(cfg, "height", 240)), start=t, length=window)
    imgs = [cv2.imread(str(p)) for p in paths]
    per = [engine.faces(im) if im is not None else [] for im in imgs]
    if not any(per):
        return {"t": t, "cluster": None, "name": None, "reason": "no_face"}
    gray = [cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) for im in imgs]
    track = reel_render.speaker_track(gray, [[f["box"] for f in fs] for fs in per], cfg)
    center = track.get("center")
    picks = []
    for fs in per:
        if not fs:
            continue
        if track.get("source") == "speaker" and center is not None:
            picks.append(min(fs, key=lambda f: abs(f["box"][0] + f["box"][2] / 2 - center)))
        else:
            picks.append(max(fs, key=lambda f: f["area"]))
    votes: dict = {}
    for f in picks:
        e = np.asarray(f["embedding"])
        e = e / (np.linalg.norm(e) or 1.0)
        # الخريطة المحفوظة في المسودة (JSON) مفاتيحها نصوص ومراكزها قوائم: تُوحَّد هنا فيعمل الإسناد على المبنية والمحفوظة معًا
        sims = {int(cid): float(np.dot(e, np.asarray(c, dtype=float))) for cid, c in built["centroids"].items()}
        if sims:
            cid, sim = max(sims.items(), key=lambda kv: kv[1])
            if sim >= thr:
                votes[cid] = votes.get(cid, 0) + 1
    if not votes:
        return {"t": t, "cluster": None, "name": None, "reason": "no_cluster", "source": track.get("source")}
    cid = max(votes, key=votes.get)
    row = next((r for r in built["map"] if int(r["id"]) == cid), {})
    return {"t": t, "cluster": cid, "name": row.get("name"), "is_host": row.get("is_host"),
            "source": track.get("source"), "votes": votes, "share": round(votes[cid] / max(len(picks), 1), 2)}


def to_saved(built: dict) -> dict:
    """ما يُحفظ على المسودة (render_speaker_map): الخريطة والمقدّم ومراكز كل المجموعات — فيُعاد التركيب بلا تنزيل الحلقة. المراكز كلها لا
    المسمّاة وحدها: وجه ضيف بلا اسم يجب أن يجد مجموعته هو، ولو حُذفت لربما أُسند إلى أقرب مجموعة مسمّاة. بلا صور ولا قراءات."""
    keep = {r["id"] for r in built["map"]}
    return {"map": [{k: r.get(k) for k in ("id", "count", "first", "last", "name", "is_host")} for r in built["map"]],
            "host": built.get("host"), "duration": built.get("duration"),
            "centroids": {str(cid): [round(float(x), 4) for x in v] for cid, v in built["centroids"].items() if cid in keep}}


def host_name(built: dict) -> str | None:
    row = next((r for r in built.get("map") or [] if r.get("is_host")), None)
    return (row or {}).get("name")
