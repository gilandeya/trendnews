"""شريط خلفية واحد للريل (خ1، قرار صاحب المشروع 8/11).

كانت كل جملة من جمل الراوي تأخذ خلفيتها وحدها: لقطة حدث إن أُسندت لها، وإلا الصورة المتحركة، فيقفز المشهد بين فيديو وصورة
وبين فيديو وآخر بلا رابط. هنا خطة واحدة على «ساعة الخلفية» (زمن مشاهد الراوي وبطاقات الأسئلة ولوحة الإجابة الواحدة متصلة،
وتتوقف في لوحات الإجابات المتعددة لأن الخلفية مغطاة فيها) تقرّر لكل فترة مصدرها، وتملأ الفترات التي بلا لقطة بإكمال اللقطة
السابقة من سلسلتها نفسها (فيستمر الفيديو بلا قطع) ثم بسلسلة لم تُستعمل، ولا تعود إلى الصورة إلا حين لا يبقى فيديو يصلح.

الدالة plan خالصة (لا ffmpeg ولا شبكة) كي يختبرها الكود بلا تنزيل؛ البناء الفعلي في reel_render._build_bg_track."""
from __future__ import annotations


def _overlaps(a0: float, a1: float, b0: float, b1: float) -> bool:
    return a0 < b1 - 1e-9 and b0 < a1 - 1e-9


def _taken(used: list[dict], vid: str, a: float, b: float, hook: dict | None) -> bool:
    if hook and hook.get("video_id") == vid and hook.get("start") is not None and hook.get("end") is not None \
            and _overlaps(a, b, float(hook["start"]), float(hook["end"])):
        return True
    return any(u["video_id"] == vid and _overlaps(a, b, u["start"], u["end"]) for u in used)


def _chain_of(chains: list[dict], win: dict) -> dict | None:
    """سلسلة النافذة: رقمها المحفوظ (1-based من reel_broll) وإلا أول سلسلة من الفيديو نفسه تحتوي بدايتها."""
    ci = win.get("chain")
    if isinstance(ci, int) and 1 <= ci <= len(chains) and chains[ci - 1].get("video_id") == win.get("video_id"):
        return chains[ci - 1]
    for c in chains:
        if c.get("video_id") == win.get("video_id") and c["start"] - 1e-6 <= win["start"] < c["end"]:
            return c
    return None


def _spare(chains: list[dict], length: float, used: list[dict], hook: dict | None) -> tuple[dict, float] | None:
    """سلسلة فيها نافذة حرة بطول الفترة: ما لم يُستعمل منها أولًا (كي لا يتكرر المشهد نفسه بعد ثوانٍ، كما في reel_broll.fallback)
    ثم relevant ثم الأطول، والنافذة أول فراغ حر فيها (لا وسطها، كي يبقى بعدها ما يُكمل به إن احتاجت الفترة التالية)."""
    def in_use(c: dict) -> bool:
        return any(u["video_id"] == c["video_id"] and _overlaps(c["start"], c["end"], u["start"], u["end"]) for u in used)
    order = sorted(range(len(chains)), key=lambda i: (in_use(chains[i]), not chains[i].get("relevant"),
                                                      -(chains[i]["end"] - chains[i]["start"]), i))
    for i in order:
        c = chains[i]
        if c["end"] - c["start"] < length - 1e-9:
            continue
        # نقاط بداية مرشّحة: أول السلسلة ثم نهاية كل نافذة مستعملة داخلها
        starts = [c["start"]] + sorted(u["end"] for u in used if u["video_id"] == c["video_id"] and c["start"] <= u["end"] < c["end"])
        if hook and hook.get("video_id") == c["video_id"] and hook.get("end") is not None:
            starts.append(float(hook["end"]))
        for s in sorted(set(starts)):
            if s + length <= c["end"] + 1e-9 and s >= c["start"] - 1e-9 and not _taken(used, c["video_id"], s, s + length, hook):
                return c, s
    return None


def plan(slots: list[dict], chains: list[dict], hook: dict | None, cfg=None, prev: dict | None = None,
         taken: list[dict] | None = None) -> list[dict]:
    """slots: [{t0, t1, win}] بترتيب الساعة، win نافذة لقطة أُسندت للفترة ({video_id, start, end, chain, ...}) أو None.
    يعيد قطعًا متتالية تغطي الساعة: {t0, t1, src: "footage", video_id, start, channel, desc, how, joined, win?} أو
    {t0, t1, src: "photo"}. how: assigned (اللقطة المسندة) · continue (إكمال السابقة من سلسلتها) · spare (سلسلة لم تُستعمل).
    joined: القطعة تكمل سابقتها من الفيديو نفسه بلا فاصل، فتُلصق بها بلا مزج (المزج بين مصدرين مختلفين وحدهما).
    prev/taken (خ2): قطعة سابقة يُكمَل منها، ونوافذ عُرضت قبلُ فلا تُعاد (خلفية الختام بعد الشريط)."""
    gap = 0.5
    if cfg is not None:
        try:
            gap = float(cfg.path("reel.render.bg_track.join_gap", gap))
        except (TypeError, ValueError):
            pass
    # النوافذ المسندة كلها محجوزة من البداية: إكمال قطعة سابقة لا يأخذ ثواني جملة لاحقة أُسندت لها
    used: list[dict] = [{"video_id": s["win"]["video_id"], "start": float(s["win"]["start"]), "end": float(s["win"]["end"])}
                        for s in slots if isinstance(s.get("win"), dict) and s["win"].get("video_id")]
    used += [{"video_id": u["video_id"], "start": float(u["start"]), "end": float(u["end"])} for u in taken or []]
    pieces: list[dict] = []
    for s in slots:
        t0, t1 = float(s["t0"]), float(s["t1"])
        length = t1 - t0
        if length <= 1e-6:
            continue
        w = s.get("win") if isinstance(s.get("win"), dict) and s["win"].get("video_id") else None
        piece: dict | None = None
        if w is not None:
            start = float(w["start"])
            joined = bool(prev and prev["src"] == "footage" and prev["video_id"] == w["video_id"]
                          and abs(start - prev["src_end"]) <= gap)
            piece = {"t0": t0, "t1": t1, "src": "footage", "video_id": w["video_id"], "start": start,
                     "channel": w.get("channel", ""), "desc": w.get("desc", ""), "how": "assigned", "joined": joined, "win": w}
            # الفترة قد تطول عن النافذة (آخر جملة في المشهد تمتد إلى بداية المشهد التالي): الثواني الزائدة تُحجز أيضًا
            used.append({"video_id": w["video_id"], "start": start, "end": start + length})
        elif prev is not None and prev["src"] == "footage":
            c = prev.get("chain")
            a = prev["src_end"]
            if c is not None and a + length <= c["end"] + 1e-9 and not _taken(used, prev["video_id"], a, a + length, hook):
                piece = {"t0": t0, "t1": t1, "src": "footage", "video_id": prev["video_id"], "start": a,
                         "channel": prev.get("channel", ""), "desc": prev.get("desc", ""), "how": "continue", "joined": True}
                used.append({"video_id": prev["video_id"], "start": a, "end": a + length})
        if piece is None and w is None:
            sp = _spare(chains, length, used, hook)
            if sp is not None:
                c, a = sp
                piece = {"t0": t0, "t1": t1, "src": "footage", "video_id": c["video_id"], "start": a,
                         "channel": c.get("channel", ""), "desc": c.get("desc", ""), "how": "spare",
                         "joined": bool(prev and prev["src"] == "footage" and prev["video_id"] == c["video_id"]
                                        and abs(a - prev["src_end"]) <= gap)}
                used.append({"video_id": c["video_id"], "start": a, "end": a + length})
        if piece is None:
            piece = {"t0": t0, "t1": t1, "src": "photo"}
        else:
            piece["src_end"] = piece["start"] + length
            piece["chain"] = _chain_of(chains, w) if piece["how"] == "assigned" else (
                prev.get("chain") if piece["how"] == "continue" else _chain_of(chains, piece))
        pieces.append(piece)
        prev = piece
    # صورتان متتاليتان قطعة واحدة: الصورة متحركة بحركة واحدة على الساعة فلا فاصل بينهما
    merged: list[dict] = []
    for p in pieces:
        if merged and p["src"] == "photo" and merged[-1]["src"] == "photo":
            merged[-1]["t1"] = p["t1"]
        else:
            merged.append(p)
    return merged


def runs(pieces: list[dict]) -> list[list[dict]]:
    """القطع مجموعات متصلة: قطعة joined تنضم إلى ما قبلها (فيديو واحد بلا فاصل)، وكل مجموعة تُمزج بالتالية."""
    out: list[list[dict]] = []
    for p in pieces:
        if out and p.get("joined") and out[-1][-1]["src"] == "footage":
            out[-1].append(p)
        else:
            out.append([p])
    return out


def summary(pieces: list[dict]) -> dict:
    """أرقام الشريط للتعليق والحفظ: ثواني الفيديو والصورة وعدد المصادر والانتقالات."""
    video = sum(p["t1"] - p["t0"] for p in pieces if p["src"] == "footage")
    photo = sum(p["t1"] - p["t0"] for p in pieces if p["src"] == "photo")
    by_how: dict[str, float] = {}
    for p in pieces:
        if p["src"] == "footage":
            by_how[p["how"]] = by_how.get(p["how"], 0.0) + p["t1"] - p["t0"]
    return {"video": round(video, 1), "photo": round(photo, 1), "runs": len(runs(pieces)),
            "how": {k: round(v, 1) for k, v in by_how.items()}}


def saved(pieces: list[dict]) -> list[dict]:
    """صيغة الحفظ على المسودة (بلا مسارات ملفات ولا كائنات سلاسل)."""
    keep = ("t0", "t1", "src", "video_id", "start", "channel", "how", "joined")
    return [{k: (round(p[k], 2) if isinstance(p.get(k), float) else p[k]) for k in keep if k in p} for p in pieces]


def shown(pieces: list[dict]) -> list[dict]:
    """نوافذ الفيديو التي عرضها الشريط ({video_id, start, end})."""
    return [{"video_id": p["video_id"], "start": p["start"], "end": p["start"] + (p["t1"] - p["t0"])}
            for p in pieces if p["src"] == "footage"]


def closing_piece(pieces: list[dict], chains: list[dict], hook: dict | None, length: float, cfg=None) -> dict | None:
    """خلفية الختام بعد الشريط (خ2): تُكمل آخر قطعة فيه إن كانت فيديو (فالختام يبدأ من حيث توقفت الخلفية قبل اللوحة الأخيرة)، وإلا
    سلسلة لم تُعرض؛ بلا ذلك ← None (التجميد القديم). القطعة المعادة {src: footage, video_id, start, how, ...} بطول length."""
    if not pieces or length <= 0:
        return None
    last = pieces[-1]
    prev = last if last["src"] == "footage" else None
    out = plan([{"t0": 0.0, "t1": float(length), "win": None}], chains, hook, cfg, prev=prev, taken=shown(pieces))
    return out[0] if out and out[0]["src"] == "footage" else None
