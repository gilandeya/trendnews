"""سجل تراكمي لقرارات المراجعة — المرحلة الأولى فقط (Issue #583): جمع بلا
أي تحليل أو تنبؤ أو تأثير على الفرز/الترتيب.

المراجع اليوم لا يستعمل شارة الرفض إطلاقًا (`/reject`)، فتجاهله الفعلي —
الأصوب لفهم أذواقه — لا يترك أثرًا مسجَّلاً. هذه الوحدة تستنتج إشارتين
إضافيتين من سلوك موجود أصلًا بلا أي تسجيل جديد وقت الجمع:

  • ``dismissed_closed`` — إشارة **صريحة**: أُغلق Issue المراجعة ومسودة ما
    فيه بقيت بلا اعتماد (``review.build_issue_body`` يقول صراحة "إغلاق
    الـ Issue = تجاهل الكل"، فقط لم يكن يُقرأ كبيانات حتى الآن).
  • ``ignored_timeout`` — إشارة **ضمنية**: بقي الـ Issue مفتوحًا أكثر من
    ``decisions.ignore_timeout_hours`` ساعة بلا أي بتّ — تخمين، لا فعل
    مقصود، ولذا ⚠️ لا يُعامَل بوزن إشارة ``dismissed_closed`` الصريحة في
    أي تقرير لاحق.

مع ``published`` (يُسجَّل لحظة النشر الفعلي)، ``rejected_explicit`` (لحظة
تسجيل رفض صريح عبر `/reject`)، ``rejected_unchecked`` و``unselected``
(Issue #954، أضيفتا معًا): الأولى حين تُعرض مسودة على المراجع في مراجعة
أولية أو نهائية فلا يُعلَّمها ثم يُوسَم الـIssue بـ approved — رفض ضمني
بنفس المعنى الذي يقوم عليه ``dismissed_closed`` أدناه، لكن الحدث المحفِّز
هنا اعتماد الـIssue نفسه لا إغلاقه؛ والثانية حين يُعرض مرشح في Issue اختيار
(gate A) فلا يُختار — قيمة منفصلة عمدًا لأن الرفض هنا سابق للصياغة لا لاحق
لها، وسماته (`_features_candidate`) مأخوذة من شكل المرشح لا شكل المسودة.
ستة قيم تغطي كل مصير ممكن لمسودة أو مرشح بلا حاجة لبناء جديد — كل حقل
تلتقطه ``_features``/``_features_candidate`` موجود أصلًا في ملف المسودة أو
المرشح.

⚠️ قيد على أي عمل لاحق في هذا الاتجاه (مسجَّل أيضًا في CLAUDE.md): أي
انتقال مستقبلي من "عرض" (تقرير) إلى "تأثير" (فرز/ترتيب) يجب أن يكون خفض
أولوية لا حجبًا كليًا — نفس فلسفة ``verify.demoted_readers``. عيّنة صغيرة
تثبّت انحيازًا لا تكشف نمطًا؛ نظام يرشّح ما يتوقع أن المراجع سينشره قد
يضيّق تغطيته بدل تحسينها.

    python -m src.decisions --count     # عدد القرارات المتراكمة حتى الآن
    python -m src.decisions --scan      # تشغيل الفحص يدويًا بلا انتظار collect
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone

import requests

from . import store
from .config import STATE_DIR, env, load_config

# الحرف القديم مرادف للرقم عند القراءة فقط (Issue #1121) -- decisions لا تستورد
# youtube_cluster لأن الأخيرة تستوردها (دورة)
_LEGACY_LAYER = {"a": 2, "b": 1, "c": 1}


def _layer_num(layer):
    if isinstance(layer, int):
        return layer
    if isinstance(layer, str) and layer.strip().isdigit():
        return int(layer.strip())
    return _LEGACY_LAYER.get(str(layer).strip().lower(), "")

log = logging.getLogger("decisions")

DECISIONS_FILE = STATE_DIR / "decisions.json"
API = "https://api.github.com"


# ──────────────────────────── التخزين ────────────────────────────


def load() -> list[dict]:
    if not DECISIONS_FILE.exists():
        return []
    try:
        return json.loads(DECISIONS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("ملف القرارات تالف — سيُعاد إنشاؤه")
        return []


def save(entries: list[dict]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    DECISIONS_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")


def _created_hour(created_at: str) -> int | None:
    try:
        return datetime.fromisoformat(created_at).hour
    except (ValueError, TypeError):
        return None


def _features(draft: dict) -> dict:
    """السمات المتاحة أصلًا في ملف المسودة — بلا أي حقل جديد يُكتب وقت
    الجمع (Issue #583). ``source_count`` من ``publishers`` (كل من التقط
    الخبر) لا ``analysed_sources`` (من حُلِّل نصّه فقط) — الأول موجود دومًا،
    والثاني قد يكون فارغًا حتى لمسودة كاملة."""
    ar = draft.get("arabic") or {}
    src = draft.get("source") or {}
    body = ar.get("post_body") or draft.get("caption") or ""
    return {
        # القيمة المعيارية عبر store.origin_of (Issue #749) — تعامل مسودة
        # بلا حقل، أو بـ"collect" (ما كان يُكتب هنا افتراضيًا قبل التوحيد)،
        # كليهما بوصفها "news"، وتُحوّل "youtube" القديمة إلى "analysis".
        "origin": store.origin_of(draft),
        "category": ar.get("category", ""),
        "angle": ar.get("angle", ""),
        "urgent": bool(ar.get("urgent")),
        "bucket": draft.get("bucket", ""),
        "region": src.get("region", ""),
        "score": round(float(draft.get("score", 0) or 0), 2),
        "trend_score": round(float(draft.get("trend_score", 0) or 0), 2),
        "velocity": round(float(draft.get("velocity", 0) or 0), 2),
        "source_count": len(src.get("publishers") or []),
        "body_len": len(body),
        "has_photo": bool(draft.get("has_photo", True)),
        "state_media": bool(draft.get("state_media", False)),
        "created_hour": _created_hour(draft.get("created_at", "")),
    }


def _features_candidate(cand: dict) -> dict:
    """سمات مرشح preselect (Issue #954) — شكل مختلف عن شكل المسودة الذي
    تلتقطه ``_features``: لا ``arabic`` ولا ``source``، فالمرشح لم يُصَغ
    بعد. ``category``/``angle`` تحريريان بحتًا فيبقيان فارغين قبل الصياغة،
    وbody_len صفر للسبب نفسه؛ ``has_photo`` من ``article.image_url`` (صورة
    المصدر الخام، لا بطاقة مبنيَّة — المرشح لا يملك واحدة)."""
    article = cand.get("article") or {}
    return {
        "origin": store.origin_of(cand),
        "category": "",
        "angle": "",
        "urgent": False,
        "bucket": cand.get("bucket", ""),
        "region": cand.get("region", ""),
        "score": round(float(cand.get("score", 0) or 0), 2),
        "trend_score": round(float(cand.get("trend_score", 0) or 0), 2),
        "velocity": round(float(cand.get("velocity", 0) or 0), 2),
        "source_count": len(cand.get("publishers") or []),
        "body_len": 0,
        "has_photo": bool(article.get("image_url")),
        "state_media": bool(cand.get("state_media", False)),
        "created_hour": _created_hour(cand.get("created_at", "")),
    }


# قرارات لا تحجب تسجيل أي قرار لاحق للمعرّف نفسه: كلاهما لحظة وسيطة لا مصير.
_NON_BLOCKING = ("unselected", "returned")


def _append(entries: list[dict], item: dict, decision: str,
            reject_tag: str | None = None,
            features: dict | None = None,
            selection_issue: int | None = None) -> None:
    entry = {
        "id": item.get("id", ""),
        "created_at": item.get("created_at", ""),
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "reject_tag": reject_tag,
        **(features if features is not None else _features(item)),
    }
    # قيود المرشحين وحدها تحمل الحقل: ظهور المرشح في Issue اختيار قرارٌ
    # مستقل، والمعرّف وحده لا يميّز ظهورين للخبر نفسه
    if selection_issue is not None:
        entry["selection_issue"] = selection_issue
    entries.append(entry)
    log.info("قرار مسجَّل: %s ← %s", item.get("id", ""), decision)


def record_published(draft: dict) -> None:
    entries = load()
    # يمنعه «published» سابق فقط: «unselected» سابق للمعرّف نفسه (ظهور
    # سابق في Issue اختيار لم يُختر فيه) لا يعني أن النشر الفعلي لاحقًا لا
    # يُسجَّل — هما قراران مختلفان في لحظتين مختلفتين
    if any(e.get("id") == draft.get("id") and e.get("decision") == "published"
           for e in entries):
        return
    # («returned» لا يمنع أصلًا: الشرط أعلاه يقرأ «published» وحدها.)
    _append(entries, draft, "published")
    save(entries)


def _blocks_rejection(entries: list[dict], draft: dict) -> bool:
    """هل يمنع قيدٌ سابق للمعرّف نفسه تسجيل رفض المسودة؟ «unselected» السابق
    لا يمنع (Issue #1153، بند مؤجَّل من #1135): هو قرار لحظة الاختيار قبل
    الصياغة، أما رفض المسودة بعد صياغتها فقرار آخر في لحظة أخرى — نفس مبدأ
    record_published. «returned» كذلك (Issue #1184): عودة الخبر إلى الترشيح
    ليست مصيرًا نهائيًا له، فرفضه لاحقًا بعد تقدّمه ثانية قرار جديد. أي قيد
    آخر للمعرّف يبقى مانعًا كما كان، حتى لا يُعدّ الرفض مرتين."""
    return any(e.get("id") == draft.get("id")
               and e.get("decision") not in _NON_BLOCKING
               for e in entries)


def record_rejected(draft: dict, tag: str) -> None:
    """الرفض الصريح عبر `/reject` — نادر عمليًا (المراجع لا يستعمله اليوم)
    لكنه يُسجَّل للاكتمال: يُميَّز عن ``dismissed_closed``/``ignored_timeout``
    بأنه فعل مقصود موثَّق بسبب، لا استنتاج. ويُميَّز عن ``rejected_unchecked``
    بأن سببه الحقيقي مكتوب يدويًا (`/reject <id> <سبب>`)، لا افتراضيًا
    بمجرَّد عدم التعليم."""
    entries = load()
    if _blocks_rejection(entries, draft):
        return
    _append(entries, draft, "rejected_explicit", reject_tag=tag)
    save(entries)


def record_rejected_unchecked(draft: dict) -> None:
    """رفض ضمني (Issue #954): عُرضت المسودة على المراجع في مراجعة أولية أو
    نهائية فلم يُعلِّمها، ثم وُسم الـIssue بـ approved — قرار منه بعدم
    الاعتماد، بنفس المعنى الذي بُني عليه ``dismissed_closed``، لكن الحدث
    المحفِّز هنا اعتماد الـIssue نفسه لا إغلاقه. منع التكرار ضروري هنا تحديدًا:
    publish.yml يُشغّل مساري urgent وnormal لنفس حدث approved، وكلاهما قد
    يصل هذا الفرع لنفس المسودة."""
    entries = load()
    if _blocks_rejection(entries, draft):
        return
    _append(entries, draft, "rejected_unchecked", reject_tag="لم يُعتمد")
    save(entries)


def _features_topic(topic: dict) -> dict:
    """سمات موضوع تحليل غير مختار (Issue #1104، بوابة اختيار مسار
    التحليل) — شكل ثالث مختلف عن ``_features``/``_features_candidate``: لا
    ``arabic`` ولا ``source`` ولا ``article``، فالموضوع مُعنقَد فقط ولم
    يُصَغ بعد. السمات التحريرية المتاحة فعلًا قبل الكتابة هي بالضبط ما ذكره
    نصّ الـIssue: الكتل، القنوات، عدد النقاط، ومؤشر الاتفاق/الخلاف — لا
    ``score``/``trend_score``/``velocity`` (مفاهيم مسار الأخبار، لا معنى
    لها هنا)."""
    return {
        "origin": "analysis",
        "category": "", "angle": "", "urgent": False,
        "bucket": "", "region": "",
        "score": 0.0, "trend_score": 0.0, "velocity": 0.0,
        "source_count": len(topic.get("channels") or []),
        "body_len": 0, "has_photo": False, "state_media": False,
        "created_hour": _created_hour(topic.get("created_at", "")),
        "layer": _layer_num(topic.get("layer", "")),
        "bloc_count": len(topic.get("blocs") or []),
        "channel_count": len(topic.get("channels") or []),
        "point_count": len(topic.get("point_ids") or []),
        "agreement": topic.get("agreement", ""),
    }


def record_unselected_topic(topic: dict) -> None:
    """رفض قبل الكتابة (Issue #1104) — نظير ``record_unselected`` أعلاه لكن
    لمسار التحليل: موضوع عُرض في Issue اختيار مواضيع التحليل
    (``youtube_cluster.open_selection``) فلم يُختَر ضمن دفعته. قيمة
    ``decision`` نفسها (``"unselected"``) بنصّ الـIssue الحرفي — «نفس قيمة
    unselected المستعملة في بوابة اختيار الأخبار» — لتبقى قابلة للقياس معًا
    في أي تقرير لاحق، مع سمات مختلفة (``_features_topic``) تناسب شكل
    الموضوع لا شكل مرشح الأخبار."""
    entries = load()
    if any(e.get("id") == topic.get("id") for e in entries):
        return
    _append(entries, topic, "unselected", reject_tag="لم يُختر",
            features=_features_topic(topic))
    save(entries)


def record_returned(draft: dict, from_stage: int,
                    selection_issue: int | None = None) -> None:
    """عودة خبر من المرحلة 2 أو 3 إلى الترشيح (Issue #1184). قرار جديد في كل
    عودة (لا منع تكرار): الخبر قد يعود مرتين وكل عودة حدث مستقل. لا يحجب أي
    تسجيل لاحق للمعرّف (انظر _NON_BLOCKING). ``selection_issue`` = قضية
    الترشيح التي جاء منها (يغيب إن لم يمر بترشيح)."""
    entries = load()
    _append(entries, draft, "returned", selection_issue=selection_issue)
    entries[-1]["returned_from_stage"] = from_stage
    save(entries)


def _candidate_known(entries: list[dict], cand: dict) -> bool:
    """منع تكرار قيد مرشح على الزوج (id، selection_issue) لا على id وحده —
    الخبر نفسه يُعرض في أكثر من Issue اختيار بالمعرّف نفسه وكل ظهور قرار
    مستقل. استثناء متحفِّظ عمدًا: أي قيد للمعرّف بلا حقل selection_issue
    (قديم، سابق لهذا الحقل) يحجب الاستكمال في كل Issue — لا سبيل لمعرفة أي
    Issue يخصّه فتفاديًا للعدّ المزدوج نقبل خسارة حالات قليلة."""
    cid = cand.get("id")
    issue = cand.get("selection_issue")
    for e in entries:
        if e.get("id") != cid or e.get("decision") == "returned":
            continue
        if "selection_issue" not in e or e.get("selection_issue") == issue:
            return True
    return False


def record_unselected(cand: dict) -> None:
    """رفض قبل الصياغة (Issue #954): مرشح preselect عُرض في Issue اختيار
    (gate A) فلم يُختر ضمن دفعته. قيمة decision منفصلة عمدًا عن
    ``rejected_unchecked``: هذا رُفض قبل إنفاق تكلفة الصياغة لا بعدها،
    وسماته (`_features_candidate`) مأخوذة من شكل المرشح لا شكل المسودة —
    لا ``arabic`` ولا ``source`` في مرشح لم يُصَغ بعد."""
    entries = load()
    if _candidate_known(entries, cand):
        return
    _append(entries, cand, "unselected", reject_tag="لم يُختر",
            features=_features_candidate(cand),
            selection_issue=cand.get("selection_issue"))
    save(entries)


# ──────────────────────────── الفحص الدوري (الإشارتان الضمنيتان) ────────


def _fetch_issue(issue_number: int) -> dict:
    repo = env("GITHUB_REPOSITORY", required=True)
    token = env("GITHUB_TOKEN", required=True)
    resp = requests.get(
        f"{API}/repos/{repo}/issues/{issue_number}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"},
        timeout=45,
    )
    resp.raise_for_status()
    return resp.json()


def _too_old(draft: dict, since: datetime | None) -> bool:
    """Issue #954: بلا ``decisions.scan_since`` مضبوطًا، لا تخطّي إطلاقًا
    (السلوك القديم كما هو). حين يُضبط، تُتخطى مسودة أقدم من ``since``
    وأيضًا مسودة created_at فيها غير قابل للقراءة — لا سبيل لمعرفة عمرها
    الحقيقي فتُعامَل بحذر بوصفها من الدفعة القديمة، لا بتخمين تاريخ لها."""
    if since is None:
        return False
    try:
        created = datetime.fromisoformat(draft["created_at"])
    except (KeyError, ValueError, TypeError):
        return True
    return created < since


def _has_approved(issue: dict) -> bool:
    return any((lb.get("name") if isinstance(lb, dict) else lb) == "approved"
               for lb in issue.get("labels") or [])


def scan(cfg) -> int:
    """يفحص المسودات المعلَّقة المرتبطة بـ Issue مراجعة **والمرشحين المعلَّقين**
    المرتبطين بـ Issue اختيار، ويسجّل قرارًا ضمنيًا لكل ما بُتَّ فيه فعلًا.
    يُشغَّل كل تشغيلة جمع (حتى بلا مسودة جديدة) — الإغلاق أو انقضاء المهلة قد
    يقعان بين تشغيلة وأخرى بلا أي حدث آخر يستدعي الفحص. يعيد عدد القرارات
    الجديدة.

    المرشحون كانوا خارج الفحص فبقي منهم 255 بلا قرار مسجَّل: Issue اختيار
    أُغلق أو ترك بلا رد لا يمرّ بـ finalize أصلًا. طلب API واحد لكل Issue
    (مسودات ومرشحين معًا) لا لكل عنصر."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo or not os.environ.get("GITHUB_TOKEN"):
        return 0  # بيئة محلية بلا Actions — لا شيء يُفحص

    scan_since_raw = cfg.path("decisions.scan_since", None)
    scan_since = datetime.fromisoformat(scan_since_raw) if scan_since_raw else None
    entries = load()
    # «returned» لا يجعل المعرّف «معروفًا»: المسودة التي تقدّمت ثانية بعد
    # عودتها تحتاج فحص الإغلاق/المهلة كأي مسودة (Issue #1184)
    known = {e["id"] for e in entries if e.get("decision") != "returned"}

    drafts = [(p, d) for p, d in store.pending_drafts()
              if d.get("review_issue") and not _too_old(d, scan_since)
              and d.get("id") not in known]
    cands = [(p, c) for p, c in store.pending_candidates()
             if c.get("selection_issue") and not _too_old(c, scan_since)
             and not _candidate_known(entries, c)]
    if not drafts and not cands:
        return 0

    timeout_hours = float(cfg.path("decisions.ignore_timeout_hours", 48))
    now = datetime.now(timezone.utc)

    # (نوع، مسار، عنصر) — مفتاح المجموعة رقم الـIssue فيُجلب مرة واحدة
    by_issue: dict[int, list[tuple[str, object, dict]]] = {}
    for path, draft in drafts:
        by_issue.setdefault(draft["review_issue"], []).append(("draft", path, draft))
    for path, cand in cands:
        by_issue.setdefault(cand["selection_issue"], []).append(("cand", path, cand))

    recorded = 0
    for issue_number, items in by_issue.items():
        try:
            issue = _fetch_issue(issue_number)
        except requests.RequestException as exc:
            log.warning("تعذّر جلب Issue #%s للفحص: %s", issue_number, exc)
            continue

        closed = issue.get("state") == "closed"
        approved = _has_approved(issue)
        for kind, path, item in items:
            decision = None
            if closed:
                # مرشح في Issue اختيار مغلق مع approved = لم يُعلَّم عند
                # الاعتماد (رفض ضمني قبل الصياغة)؛ بلا approved = أُغلق
                # الـIssue كله بلا بتّ
                decision = ("unselected" if kind == "cand" and approved
                            else "dismissed_closed")
            else:
                try:
                    created = datetime.fromisoformat(item["created_at"])
                except (KeyError, ValueError, TypeError):
                    continue
                if (now - created).total_seconds() >= timeout_hours * 3600:
                    decision = "ignored_timeout"
            if decision is None:
                continue
            if kind == "draft":
                _append(entries, item, decision)
            else:
                _append(entries, item, decision,
                        reject_tag="لم يُختر" if decision == "unselected" else None,
                        features=_features_candidate(item),
                        selection_issue=issue_number)
                # تحديث ملف المرشح نفسه كي لا يُعاد فحصه في الدورة التالية
                store.update_candidate(path, status=decision)
            recorded += 1

    if recorded:
        save(entries)
        log.info("قرارات ضمنية مسجَّلة هذه الدورة: %d", recorded)
    return recorded


# ──────────────────────────── الأمر ────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="سجل القرارات التراكمي — المرحلة الأولى: جمع بلا تحليل")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--count", action="store_true",
                       help="عدد القرارات المتراكمة حتى الآن")
    group.add_argument("--scan", action="store_true",
                       help="فحص المسودات المعلَّقة يدويًا الآن")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
                        datefmt="%H:%M:%S")

    if args.scan:
        n = scan(load_config(args.config))
        print(f"سُجّل {n} قرارًا ضمنيًا جديدًا.")
        return 0

    entries = load()
    print(f"إجمالي القرارات المسجَّلة: {len(entries)}")
    for decision, count in Counter(e["decision"] for e in entries).most_common():
        print(f"  {decision}: {count}")
    remaining = max(0, 30 - len(entries))
    if remaining:
        print(f"(يلزم {remaining} إضافيًا قبل مراجعة N=48 على أدلة)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
