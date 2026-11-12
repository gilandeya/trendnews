"""قضية السيناريو لمواضيع العناوين (الخطوة 5): اعتماد قضية الموضوع `meta-topic` يكتب سيناريو الريل مما علّمه صاحب المشروع.

لماذا لا يختار النموذج الإجابات هنا: صاحب المشروع اختارها بيده في قضية الموضوع (العنوان والأسئلة وإجاباتها)، فالكود يبني
المشاهد منها مباشرة، ويكتب نداء واحد ما لم يُكتب بعد: السياق (وقائع لا وصف للنقاش) وسؤال الختام. بقية الأنبوب هي أنبوب
الريل القائم بلا نسخة ثانية (فحص قائلي المقاطع وتدقيق الأسماء والمحرر الأخير وخلفية الراوي ومرشّحو الهوك وخطة اللقطات)
عبر `reel_script.write_for_draft(builder=)`. الناتج مسودة ريل تحليل تُعرض في قضية مرحلة 2 (`youtube-review`) خاصة بها،
فتعمل فيها كتلة النص القابلة للتعديل (السياق سطر منها) واعتماد السيناريو والتركيب كما هي، ويضاف إليها اختيار لقطة الهوك
من ثلاثة مرشّحين أولهم معلَّم.

يعمل في publish.yml (المسار العادي): فيه المستودع الخاص (ملف الأسئلة والمقاطع بترجمتها) ومفتاحا Anthropic ويوتيوب. لا بروكسي
مطلوب: النصوص جُلبت في الخطوة 4، والتنزيل في التركيب.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

TOPIC_ISSUE_RE = re.compile(r"<!--\s*mtopic-issue:([0-9a-f]+)\s*-->")

CONTEXT_TOOL = {
    "name": "write_reel_frame",
    "description": "سياق الريل وسؤال ختامه.",
    "input_schema": {
        "type": "object",
        "properties": {
            "context": {"type": "array", "items": {"type": "string"},
                        "description": "جمل السياق: وقائع الحدث التي يحتاجها المشاهد ليفهم الأسئلة، بلا وصف للنقاش"},
            "closing_question": {"type": "string", "description": "سؤال الختام للمشاهد، بلا «برأيك» وبلا واو عطف في أوله"},
        },
        "required": ["context", "closing_question"],
    },
}


def _scfg(cfg) -> dict:
    return cfg.path("youtube.meta_topics.script") or {}


def _texts(cfg) -> dict:
    return _scfg(cfg).get("texts") or {}


# ───────────── من علامات القضية إلى المادة ─────────────

def selected_material(marks: dict, priv: dict) -> tuple[list[dict], list[dict]]:
    """(الأسئلة المعلَّمة بإجاباتها المعلَّمة بترتيب القضية، المقاطع المعلَّمة). سؤال معلَّم بلا إجابة معلَّمة يُترك، ومقطع لا يتكرر
    بين الأسئلة (الأول يغلب) لأن التركيب يعرض المقطع مرة واحدة."""
    by_id = {b["bite_id"]: b for b in priv.get("bites") or [] if b.get("bite_id")}
    questions, bites, used = [], [], set()
    for qi in marks.get("questions") or []:
        if not 1 <= qi <= len(priv.get("questions") or []):
            continue
        ids = [bid for bid in (marks.get("answers") or {}).get(qi, []) if bid in by_id and bid not in used]
        if not ids:
            continue
        used.update(ids)
        questions.append({"text": priv["questions"][qi - 1]["text"], "bite_ids": ids})
        bites += [by_id[bid] for bid in ids]
    return questions, bites


def bites_points(bites: list[dict], date: str) -> list[dict]:
    """المقاطع بشكل النقطة الذي يقرؤه أنبوب الريل، مع ما لا يحمله ملف الأسئلة: رابط الفيديو وعنوانه ووصفه وتاريخه (من ملف
    القياس) لأن identify_speakers يوثّق المتحدث من عنوان الفيديو ووصفه."""
    from . import meta_qa, youtube_bites
    rich = []
    for b in bites:
        meta = meta_qa.video_meta(b["video_id"], date)
        rich.append(dict(b, video_url=f"https://www.youtube.com/watch?v={b['video_id']}",
                         video_title=meta.get("title", ""), video_description=meta.get("description", ""),
                         video_published=meta.get("published") or ""))
    points = youtube_bites.bites_as_points(rich)
    for p, b in zip(points, rich):
        p["orientation"] = b.get("orientation") or ""
    return points


def draft_points(draft: dict) -> list[dict]:
    """نقاط ريل موضوع العناوين للتركيب: مقاطعه في ملف الأسئلة الخاص لا في نافذة نقاط youtube_topics (قضية 1850: حُذفت
    المقاطع الثلاثة كلها «غير موجودة في نافذة النقاط»). كل مقاطع الملف لا المعلَّم وحده، لأن السيناريو المعتمد يُعدَّل
    وقد يحمل مقطعًا آخر من الموضوع؛ ومعرّف النقطة (point_key) من الفيديو والملخّص فيطابق ما كتبه finalize."""
    from . import meta_qa
    tid = draft.get("meta_topic_id") or ""
    if not tid:
        return []
    priv = json.loads(meta_qa.private_path(tid).read_text(encoding="utf-8"))
    bites = [b for b in priv.get("bites") or [] if b.get("bite_id") and b.get("video_id")]
    return bites_points(bites, draft.get("topic_date") or draft.get("run_date") or "")


# ───────────── السياق والختام (نداء واحد) ─────────────

def _create(client, **kwargs):
    # publish.py يستدعي finalize بلا عميل، فيُبنى هنا عند الحاجة (حادثة #1808 في 6/11: AttributeError على None أسقط خطوة
    # النشر كلها). الاختبار كان يزيّف _create نفسها فلم يرَ ذلك
    from . import llm
    if client is None:
        from anthropic import Anthropic

        from .config import env
        client = Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    return llm.create(client, **kwargs)


def frame_message(title: str, topic: dict, questions: list[dict], by_bite: dict, facts: list[str]) -> str:
    lines = [f"الموضوع: {topic.get('title', '')}", f"السؤال الرئيس (عنوان الريل): {title}", "", "الأسئلة وإجاباتها:"]
    for k, q in enumerate(questions, 1):
        lines.append(f"{k}. {q['text']}")
        for bid in q["bite_ids"]:
            b = by_bite.get(bid) or {}
            lines.append(f"   - {b.get('speaker') or b.get('speaker_original') or 'متحدث'} ({b.get('channel', '')}): "
                         f"{b.get('summary_ar', '')} — «{b.get('text_ar', '')}»")
    if facts:
        lines += ["", "وقائع من المقاطع:", *[f"- {f}" for f in facts]]
    return "\n".join(lines)


def frame_problems(data: dict, cfg) -> list[str]:
    """ما يرفض الكود من نداء السياق: سياق فارغ أو أطول من الحد، وختام فارغ أو يبدأ بـ«برأيك» (التركيب يضيفها هو)."""
    from . import reel_script
    out = []
    ctx = " ".join(str(x) for x in reel_script._listish(data.get("context")) or ([data.get("context")] if isinstance(
        data.get("context"), str) else []))
    n, limit = len(ctx.split()), int(cfg.path("reel.script.v2.context_max_words", 25))
    if not n:
        out.append("السياق فارغ")
    elif n > limit:
        out.append(f"السياق أطول من {limit} كلمة ({n})")
    closing = " ".join(str(data.get("closing_question") or "").split())
    if not closing:
        out.append("سؤال الختام فارغ")
    elif closing.startswith("برأيك"):
        out.append("سؤال الختام يبدأ بـ«برأيك» والتركيب يضيفها")
    return out


def write_frame(title: str, topic: dict, questions: list[dict], by_bite: dict, facts: list[str], cfg, client=None,
                info: dict | None = None) -> tuple[dict | None, str]:
    """(بيانات السياق والختام، السبب). الرد المقطوع لا يُقبل، والمخالفة تُعاد مرة واحدة في المحادثة نفسها بسببها."""
    s = _scfg(cfg)
    limit = int(cfg.path("reel.script.v2.context_max_words", 25))
    system = str(s.get("system", "")).replace("{context_max_words}", str(limit))
    messages: list[dict] = [{"role": "user", "content": frame_message(title, topic, questions, by_bite, facts)}]
    reasons: list[str] = []
    for attempt in (1, 2):
        resp = _create(client, model=s.get("model", "claude-opus-5"), max_tokens=int(s.get("max_tokens", 1500)),
                       system=system, tools=[CONTEXT_TOOL], tool_choice={"type": "tool", "name": CONTEXT_TOOL["name"]},
                       messages=messages)
        if getattr(resp, "stop_reason", "") == "max_tokens":
            return None, "رد السياق مقطوع عند حد الطول"
        block = next((b for b in getattr(resp, "content", []) or []
                      if getattr(b, "type", "") == "tool_use" and getattr(b, "name", "") == CONTEXT_TOOL["name"]), None)
        if block is None:
            return None, "لم يُرجع النموذج السياق"
        data = dict(block.input or {})
        reasons = frame_problems(data, cfg)
        if info is not None and reasons:
            info.setdefault("attempts", []).append({"attempt": attempt, "reasons": reasons})
        if not reasons:
            return data, ""
        messages += [{"role": "assistant", "content": [{"type": "tool_use", "id": block.id, "name": block.name,
                                                         "input": block.input}]},
                     {"role": "user", "content": [{"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                                   "content": "؛ ".join(reasons) + " — صحّحه دون تغيير ما سواه."}]}]
    return None, "؛ ".join(reasons)


def make_builder(title: str, titles: list[str], topic: dict, questions: list[dict], by_bite: dict, pid_of: dict,
                 facts: list[str], cfg, client=None):
    """الباني الذي يمرّره finalize إلى write_for_draft: يبني المشاهد من المعلَّم بعد فحص قائلي المقاطع (مقطع استبعده الفحص
    يسقط من سؤاله، وسؤال بلا إجابة باقية يُترك)، والعناوين الثلاثة من قضية الموضوع بترتيبها والمختار أولًا."""
    from . import reel_script

    def build(valid: list[dict], narrator: str, info: dict) -> tuple[dict | None, str]:
        valid_ids = {c["point_id"] for c in valid}
        qs = []
        for q in questions:
            ans = [{"point_id": pid_of[bid], "stance": "", "angle": ""} for bid in q["bite_ids"]
                   if pid_of.get(bid) in valid_ids]
            if ans:
                qs.append({"role": "", "text": q["text"], "answers": ans})
            else:
                info.setdefault("warnings", []).append(
                    _texts(cfg).get("question_dropped", "🔧 تُرك سؤال لم تبق له إجابة بعد فحص المقاطع: {q}").format(q=q["text"]))
        if not qs:
            return None, _texts(cfg).get("no_answers_left", "لم تبق إجابة معلَّمة بعد فحص قائلي المقاطع")
        data, reason = write_frame(title, topic, questions, by_bite, facts, cfg, client, info)
        if data is None:
            return None, reason
        script = reel_script._build_v2({"main_question": title, "context": data.get("context"), "questions": qs,
                                        "closing_question": data.get("closing_question")}, valid, narrator, topic, cfg)
        info["headlines"] = [title] + [t for t in titles if t != title]
        return script, ""

    return build


# ───────────── الاعتماد ─────────────

def build_draft(topic: dict, data: dict, title: str, hook_options: int = 3) -> dict:
    """مسودة ريل تحليل لموضوع العناوين. بلا topic_id عمدًا: ذلك الحقل يربط بمواضيع youtube_topics (العودة إلى الترشيح وخيارا
    «➕ أضف»)، وموضوع العناوين لا يعيش هناك؛ رابطه meta_topic_id."""
    from .important import point_id
    return {
        "id": point_id(f"{topic['id']}:metareel"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending", "origin": "analysis", "format": "reel", "script_status": "awaiting_script",
        "title": topic["title"], "event": topic["title"], "tier": len(topic.get("blocs") or []),
        "blocs": topic.get("blocs") or [], "channels": topic.get("channels") or [], "agreement": "", "score": 0,
        "warnings": [], "run_date": data["date"], "topic_date": data["date"],
        "arabic": {"post_title": title, "urgent": False, "category": "تحليل"},
        "source": {"link": "", "publishers": topic.get("channels") or []}, "source_videos": [],
        "meta_topic_id": topic["id"], "meta_issue": topic.get("topic_issue"),
        # عدد مرشّحي الهوك المعروضين مربعات في قضية السيناريو (youtube_publish._reel_hook_lines)
        "hook_pick": max(1, int(hook_options)),
        # ما صُرف على مقاطع الموضوع وأسئلته (meta_qa) يدخل كلفة هذا الريل (costs.reel_line)
        **({"cost_qa": (topic.get("qa") or {})["cost"]} if isinstance((topic.get("qa") or {}).get("cost"), dict) else {}),
    }


def qa_in_flight(topic: dict, cfg, now: datetime) -> bool:
    """طلب استخراج (فتح قضية الموضوع أو إعادة طلبه) أحدث من `qa.pending_grace_minutes`: نتيجته لم تُحفظ بعد ولم يمضِ ما يكفي
    للحكم بضياعها. بعد المهلة (تشغيلة أُلغيت أو تعطّلت) يُعاد الطلب كما كان."""
    grace = float(cfg.path("youtube.meta_topics.qa.pending_grace_minutes", 0) or 0)
    if grace <= 0:
        return False
    stamp = (topic.get("qa") or {}).get("requeued_at") or topic.get("qa_requested_at")
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (now - when).total_seconds() < grace * 60


def requeue_qa(issue_number: int, topic: dict, data: dict, cfg, now: datetime | None = None) -> bool:
    """إعادة وسم approved على قضية موضوع لم تجهز أسئلته (رصيد البروكسي منتهٍ أو فشل الاستخراج) تطلب الاستخراج من جديد.
    السبب: تشغيلة التركيب لا تجري إلا بإطلاق، فموضوع ينتظر البروكسي لا يُعاد «تلقائيًا» ما لم يطلبه أحد. الطلب الإنساني يصفّر
    المحاولات وعلامة تعليق الانتظار. موضوع أقدم من `qa.days` لا يُعاد (أخباره قديمة ولا يعالجه pending_topics). يعيد True إن طُلب."""
    from . import meta_topics, review
    qa = topic.get("qa") or {}
    if qa.get("status") not in ("waiting_proxy", "failed", None):
        return False
    t = _texts(cfg)
    now = now or datetime.now(timezone.utc)
    if qa.get("status") is None and qa_in_flight(topic, cfg, now):
        # طُلب الاستخراج قبل قليل ولم تصل نتيجته المستودعَ بعد (قضية 1847: الأسئلة كُتبت في القضية ✅ والتشغيلة ما زالت تركّب
        # ريلات قبل أن تحفظها، فطلبت إعادة الوسم استخراجًا ثالثًا محا تعليم صاحب المشروع). لا طلب ثانٍ: finalize تعلّق no_qa
        return False
    days = int(cfg.path("youtube.meta_topics.qa.days", 3))
    try:
        age = (now.date() - datetime.strptime(data["date"], "%Y-%m-%d").date()).days
    except (KeyError, ValueError):
        age = 0
    if age >= days:
        review.comment(issue_number, t.get("qa_expired", "").format(days=days))
        review.remove_label(issue_number, "approved")
        return True
    topic["qa"] = {**qa, "attempts": 0, "notified_proxy": False, "requeued_at": now.isoformat()}
    meta_topics._save_public(data)
    review.comment(issue_number, t.get("qa_requeued", ""))
    review.remove_label(issue_number, "approved")
    meta_topics.request_qa_run(issue_number, cfg)
    return True


def finalize(issue_number: int, body: str, cfg, client=None) -> int:
    """اعتماد قضية الموضوع: سيناريو من المعلَّم ← مسودة ← قضية سيناريو، ثم تعليق برابطها وإغلاق قضية الموضوع. لا علامة ← تعليق
    وتبقى القضية مفتوحة (تُزال approved) ليعلّم صاحب المشروع ويعيد الوسم."""
    from . import meta_qa, meta_topics, review, store, reel_script, youtube_publish
    t = _texts(cfg)
    m_tid, m_date = TOPIC_ISSUE_RE.search(body or ""), meta_topics.DATE_RE.search(body or "")
    data = meta_topics._load_public(m_date.group(1)) if m_date else None
    topic = next((x for x in (data or {}).get("topics") or [] if m_tid and x.get("id") == m_tid.group(1)), None)
    if topic is None:
        review.comment(issue_number, t.get("missing", "⚠️ لم أجد ملف هذا الموضوع."))
        return 1
    if topic.get("script_issue"):
        # المساران لحدث وسم واحد، أو إعادة وسم بعد فتح قضية السيناريو: لا سيناريو ثانٍ
        return 0
    try:
        priv = json.loads(meta_qa.private_path(topic["id"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        if requeue_qa(issue_number, topic, data, cfg):
            return 0
        review.comment(issue_number, t.get("no_qa", "⚠️ لا أسئلة جاهزة لهذا الموضوع بعد — انتظر تعليق ✅ ثم أعد الوسم."))
        review.remove_label(issue_number, "approved")
        return 1
    marks = meta_qa.read_marks(body)
    questions, bites = selected_material(marks, priv)
    if not questions:
        review.comment(issue_number, t.get("nothing_marked", "⚠️ لم يُعلَّم سؤال بإجابة — علّم ثم أعد وسم `approved`."))
        review.remove_label(issue_number, "approved")
        return 0
    titles = list(priv.get("titles") or []) or [topic["title"]]
    title = titles[marks["title"]] if 0 <= marks["title"] < len(titles) else titles[0]
    points = bites_points(bites, data["date"])
    pid_of = {b["bite_id"]: reel_script.point_key_id(p) for b, p in zip(bites, points)}
    by_bite = {b["bite_id"]: b for b in bites}
    facts = [b.get("summary_ar", "") for b in priv.get("bites") or [] if b.get("type") == "fact" and b.get("summary_ar")]
    facts = facts[: int(cfg.path("reel.script.v2.facts_max", 6))]
    draft = build_draft(topic, data, title, int(_scfg(cfg).get("hook_options", 3)))
    builder = make_builder(title, titles, topic, questions, by_bite, pid_of, facts, cfg, client)
    result = reel_script.write_for_draft(draft, topic, points, "", [], cfg, client, builder=builder)
    if result.get("status") != "ready":
        # فشل لا يُحفظ مسودةً: مسودة ريل معلّقة بلا قضية يجمعها open_review في قضية مجمّعة. السبب ومحاولات الكتابة في التعليق،
        # والقضية تبقى مفتوحة بلا approved فيعيد صاحب المشروع الوسم (أو يغيّر اختياره) فيُكتب من جديد
        tries = "؛ ".join(f"{a.get('attempt')}) {'، '.join(a.get('reasons') or [])}" for a in draft.get("script_attempts") or [])
        review.comment(issue_number, t.get("failed", "⚠️ تعذّر السيناريو: {reason}").format(reason=result.get("reason", ""))
                       + (f"\n{t.get('attempts_label', 'محاولات الكتابة:')} {tries}" if tries else ""))
        review.remove_label(issue_number, "approved")
        return 1
    path = store.save_draft(draft)
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    issue = review.create_issue(t.get("issue_title", "🎬 سيناريو: {title}").format(title=title),
                                youtube_publish.build_review_body([draft], repo, branch, cfg), labels=["youtube-review"])
    store.update_draft(path, review_issue=issue["number"], stage2_issue=issue["number"])
    topic.update(script_issue=issue["number"], script_draft=draft["id"])
    meta_topics._save_public(data)
    review.comment(issue_number, t.get("done", "🎬 كُتب السيناريو ← #{n}").format(n=issue["number"]))
    review.close_issue(issue_number)
    return 0
