"""تجميع الأخبار عبر اللغات — دلاليًا لا لفظيًا.

المشكلة: مقارنة كلمات العناوين تنجح داخل اللغة الواحدة وتفشل عبر اللغات.
«OPEC cuts output» و«L'OPEP réduit sa production» لا يشتركان في حرف، فيبقى
كل خبر وحيدًا: مؤشر التغطية يصبح بلا معنى، والسرعة لا تُقاس، والتحليل
متعدد المصادر لا يجد مصدرين.

وأسماء الأعلام وحدها لا تكفي: «ترامب + إيران» يظهران في عشرات الأخبار
المختلفة، فالمطابقة عليهما تدمج ما لا ينبغي دمجه.

الحل: استدعاء واحد رخيص بـ Haiku يجمّع المتصدّرين حسب *الحدث*. لا يُطبّق
على كل الأخبار (1800 خبر) بل على من قد يُنشر فعلًا — فالدقة مطلوبة حيث
تُتخذ القرارات، لا في ذيل القائمة.
"""
from __future__ import annotations

import json
import logging
import re

from anthropic import Anthropic, APIError

from .config import env
from .sources import Article

log = logging.getLogger(__name__)

SYSTEM = """أنت محرر يجمّع عناوين الأخبار حسب الحدث الذي تتناوله.

العناوين بلغات مختلفة (إنجليزية، فرنسية، ألمانية، إسبانية، تركية،
برتغالية، عربية…). اجمع كل العناوين التي تصف **الحدث نفسه** في مجموعة
واحدة، مهما اختلفت لغتها أو صياغتها.

قواعد صارمة:
• الحدث نفسه = نفس الواقعة في نفس الزمان والمكان. تغطية مختلفة لحدث
  واحد تُجمع، ولو اختلفت الزاوية أو التفاصيل المذكورة.
• حدثان مختلفان لنفس الأشخاص **لا يُجمعان**: "ترامب يهدد إيران" و"ترامب
  يوقّع اتفاقًا تجاريًا مع إيران" حدثان منفصلان رغم تطابق الأسماء.
• التطور اللاحق لحدث يُجمع معه: "زلزال يضرب طوكيو" و"ارتفاع حصيلة زلزال
  طوكيو" حدث واحد.
• العنوان الذي لا يشارك غيره يبقى في مجموعة وحده.

أخرج JSON فقط: {"groups": [[0,3,7],[1],[2,5],...]}
كل قائمة داخلية أرقام العناوين التي تصف حدثًا واحدًا. كل رقم مرة واحدة."""


def _client() -> Anthropic:
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def _parse(text: str) -> list[list[int]]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise
        data = json.loads(text[start : end + 1])
    return [[int(i) for i in g] for g in (data.get("groups") or [])]


def _group_titles(titles: list[str], cfg) -> list[list[int]] | None:
    """يجمّع فهارس العناوين حسب الحدث الذي تصفه؛ يعيد None عند أي فشل."""
    mcfg = cfg.get("merge", {}) or {}
    model = mcfg.get("model", "claude-haiku-4-5-20251001")
    listing = "\n".join(f"{i}. {t}" for i, t in enumerate(titles))

    try:
        resp = _client().messages.create(
            model=model,
            max_tokens=1500,
            system=SYSTEM,
            messages=[{"role": "user", "content": f"العناوين:\n\n{listing}"}],
        )
        from .writer import record_usage
        record_usage(resp, model)
        text = "".join(b.text for b in resp.content
                       if getattr(b, "type", "") == "text")
        return _parse(text)
    except (APIError, RuntimeError, json.JSONDecodeError, ValueError) as exc:
        # RuntimeError تصدر من _client() نفسه إن غاب ANTHROPIC_API_KEY —
        # يجب أن تتدهور كبقية أعطال النموذج، لا أن تُسقط الجمع كله.
        log.warning("فشل تجميع العناوين دلاليًا: %s", exc)
        return None


def semantic_merge(articles: list[Article], cfg, limit: int = 60) -> list[Article]:
    """
    يدمج المتصدّرين حسب الحدث، ويعيد القائمة بعد الدمج.

    الممثل المُختار من كل مجموعة يرث مصادر بقية أعضائها وصورهم وروابطهم —
    فيرتفع مؤشر تغطيته وتُقاس سرعته بحق.

    عند أي فشل نُعيد القائمة كما هي: الدمج تحسين لا شرط.
    """
    mcfg = cfg.get("merge", {}) or {}
    if not mcfg.get("enabled", True) or len(articles) < 2:
        return articles

    head, tail = articles[:limit], articles[limit:]
    groups = _group_titles([a.title for a in head], cfg)
    if groups is None:
        return articles

    seen: set[int] = set()
    merged: list[Article] = []
    joined = 0

    for group in groups:
        members = [head[i] for i in group if 0 <= i < len(head) and i not in seen]
        seen.update(i for i in group if 0 <= i < len(head))
        if not members:
            continue
        rep = members[0]
        if len(members) > 1:
            joined += len(members) - 1
            rep = _absorb(rep, members[1:])
        merged.append(rep)

    merged += [a for i, a in enumerate(head) if i not in seen]
    if joined:
        log.info("الدمج الدلالي: ضُمّ %d خبر في %d مجموعة",
                 joined, sum(1 for g in groups if len(g) > 1))
    return merged + tail


def _absorb(rep: Article, others: list[Article]) -> Article:
    """يضم مصادر الآخرين وصورهم وروابطهم إلى الممثل."""
    names = set(rep.cluster_sources or [rep.publisher])
    members = list(rep.cluster_members)
    images = list(rep.image_candidates)
    links = {m.get("link") for m in members}

    for other in others:
        names.update(other.cluster_sources or [other.publisher])
        for member in other.cluster_members:
            if member.get("link") not in links:
                links.add(member.get("link"))
                members.append(member)
        for url in other.image_candidates:
            if url not in images:
                images.append(url)

    rep.cluster_sources = sorted(names)
    rep.cluster_members = members[:6]
    rep.image_candidates = images[:6]
    rep.group_sources = len(names)
    if not rep.image_url and images:
        rep.image_url = images[0]
    return rep


def find_duplicate_event(candidate_title: str, recent_titles: list[str],
                         cfg) -> tuple[bool, str | None]:
    """
    هل يغطي العنوان المرشّح حدثًا سبق نشره ضمن ``recent_titles``؟

    يُستعمل في مسار النشر التلقائي تحديدًا: تحديث حصيلة ضحايا أو تفاصيل
    إضافية لخبر نُشر فعلًا لا يستحق منشورًا مستقلًا بلا مراجعة بشرية —
    نفس منطق تجميع الحدث الواحد عبر صياغات مختلفة في `semantic_merge`،
    مطبَّقًا هنا على عنوان واحد مقابل ما نُشر مؤخرًا بدل مجموعة متصدّرين.

    يعيد (نجح_الفحص, العنوان المطابق أو None). عند فشل الاستدعاء نعيد
    ``(False, None)`` — خلافًا لـ`semantic_merge`/`screen` اللذين يتدهوران
    بأمان لأن فشلهما يعني مرور المزيد للمراجعة البشرية فقط، فشل هذا الفحص
    يقع على حافة النشر بلا مراجعة، فيُعامل كعدم تأكيد لا كسماح.
    """
    if not recent_titles:
        return True, None

    titles = [candidate_title] + list(recent_titles)
    groups = _group_titles(titles, cfg)
    if groups is None:
        return False, None

    matched = [i for g in groups if 0 in g for i in g if i != 0]
    if not matched:
        return True, None
    return True, titles[min(matched)]
