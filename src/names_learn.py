"""تعلّم توحيد رسم الأسماء تلقائيًا من التكرار الفعلي في المسودات (Issue
#1074) -- بلا صيانة يدوية لمعجم names.aliases في config.yaml.

قياس على 331 مسودة أثبت أن الكشف الآلي بقاعدة نصية غير صالح: التشابه
المباشر ينتج أزواجًا متشابهة شكلًا لا معنى («الحرب»~«الحزب»،
«اليمن»~«الأمن»)، والربط بالاسم الأجنبي ينتج تصريفات نحوية («سعودية»~
«سعودي») لا رسمين لاسم واحد، ومرشِّح التصريفات يفوّت الحالة الأصلية
(«نتنياهو»~«نتانياهو» -- مسافة ليفنشتاين حقيقية 1 فقط، لكن مقارنة
حرف-بحرف موضعية تفوّتها لأن إدراج حرف واحد يزيح كل ما بعده). التمييز
حكم لغوي، فيصدر عن نموذج رخيص (screening.model نفسه) لا عن قاعدة.

المسار: src.collect.py يستدعي run(cfg) في نهاية دورة الجمع، مرة كل 24
ساعة على الأكثر (الطابع الزمني في state/names_learned.json نفسه -- لا
تعديل على أي workflow). كل مرشح يمرّ بحواجز عددية وبنيوية رخيصة (بلا
نداء نموذج) قبل أن يُعرض على النموذج، ونداء واحد فقط لكل دفعة مرشحين.
النتيجة تُطبَّق في src/names.py (المعجم المتعلَّم، يُغلَب باليدوي دائمًا).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from anthropic import Anthropic, APIError

from . import names
from .config import STATE_DIR, env
from .writer import record_usage

log = logging.getLogger(__name__)

LEARNED_FILE = names.LEARNED_FILE

# التعلّم لا يعمل مرتين في 24 ساعة -- الطابع الزمني مخزَّن في الملف نفسه
# بدل ملف حالة منفصل، فلا مصدر ثانٍ للحقيقة (نفس مبدأ last_publish_at).
_MIN_RUN_INTERVAL_HOURS = 24

# حواجز الترشيح العددية قبل أي نداء نموذج (كلها لازمة معًا).
_MIN_WORD_LEN = 5
_MIN_HIGH_COUNT = 5
_MIN_LOW_COUNT = 2
_MIN_RATIO = 3.0
_MAX_LEVENSHTEIN = 2

# سقف الرد يُحسَب من عدد الأزواج الفعلي بنمط Issue #1047 -- لا سقف ثابت
# (tokens_per_pair/max_tokens_cap مضبوطان في config.yaml: names.learn).
_MAX_TOKENS_BASE = 300

SYSTEM = """أنت لغوي عربي تفصل بين ثلاث حالات لكل زوج كلمات عربيتين:

- same_name: الكلمتان رسمان مختلفان لاسم علم واحد بعينه (شخص أو مكان أو
  منظمة) -- فرق في النقل الصوتي أو الإملائي فقط، لا فرق في الهوية ولا في
  المعنى (مثال: «نتنياهو»/«نتانياهو»، «ترامب»/«ترمب»).
- inflection: الكلمتان تصريف نحوي أو صرفي لكلمة واحدة (تذكير/تأنيث،
  إفراد/جمع، نسبة) -- ليستا رسمين لاسم علم واحد (مثال: «سعودية»/«سعودي»).
- different: كلمتان مختلفتان تمامًا في المعنى أو الهوية، تشابهتا شكلًا
  فقط (مثال: «الحرب»/«الحزب»، «اليمن»/«الأمن»).

لكل زوج في القائمة أعد حكمًا واحدًا من الثلاثة فقط. كن صارمًا: إن لم تكن
متأكدًا تمامًا أن الكلمتين رسمان لاسم علم واحد بعينه، فالحكم inflection
أو different لا same_name -- القبول الخاطئ هنا يُصحِّح نصًّا سليمًا فيفسده.

أخرج JSON فقط بهذا الشكل:
{"verdicts": [{"i": رقم الزوج, "verdict": "same_name|inflection|different"}]}"""


def _client() -> Anthropic:
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def load_learned() -> dict:
    """يقرأ state/names_learned.json دفاعيًا؛ ملف غائب أو تالف يعيد بنية
    فارغة صالحة بلا كسر لا هنا ولا في names.py (المستهلك الآخر لهذا
    الملف، عبر مسار مستقل names._load_learned_entries)."""
    if not LEARNED_FILE.exists():
        return {"entries": {}, "rejected_pairs": [], "last_run": None}
    try:
        data = json.loads(LEARNED_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("ملف الأسماء المتعلَّمة تالف -- سيُعاد إنشاؤه")
        return {"entries": {}, "rejected_pairs": [], "last_run": None}
    data.setdefault("entries", {})
    data.setdefault("rejected_pairs", [])
    data.setdefault("last_run", None)
    return data


def save_learned(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LEARNED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _due(data: dict) -> bool:
    last_run = data.get("last_run")
    if not last_run:
        return True
    try:
        last = datetime.fromisoformat(last_run)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - last >= timedelta(hours=_MIN_RUN_INTERVAL_HOURS)


def _levenshtein(a: str, b: str) -> int:
    """مسافة ليفنشتاين حقيقية (حذف/إدراج/استبدال) -- لا مقارنة حرف-بحرف
    موضعية. المقارنة الموضعية تفوّت إدراجًا واحدًا في منتصف الكلمة (مثل
    الألف الزائدة في «نتانياهو» مقارنة بـ«نتنياهو»)، لأنها تُزيح كل ما
    بعدها موضعيًا فتُحسَب أخطاء كثيرة بدل خطأ واحد فعلي."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


def _unify_structure(word: str) -> str:
    return word.translate(names.STRUCTURE_UNIFY_TRANS)


def _pair_key(a: str, b: str) -> str:
    lo, hi = sorted((a, b))
    return f"{lo}␟{hi}"


def _judged_pairs(learned: dict) -> set[str]:
    """أزواج حُكم عليها سلفًا -- لا تُرشَّح ثانية (لا للنموذج مجددًا ولا
    لإعادة الترشيح): كل زوج مرفوض مسجَّل صراحة، وكل زوج ضمن متغيّرات مدخل
    متعلَّم واحد (حُكم عليه ضمنًا حين انضمّ إلى ذلك المدخل)."""
    judged: set[str] = set(learned.get("rejected_pairs") or [])
    for canonical, info in (learned.get("entries") or {}).items():
        words = [canonical, *(info.get("variants") or [])]
        for i in range(len(words)):
            for j in range(i + 1, len(words)):
                judged.add(_pair_key(words[i], words[j]))
    return judged


def find_candidates(seen_totals: dict[str, int], learned: dict,
                     blocklist: set[str]) -> list[tuple[str, str, int, int]]:
    """يرشِّح أزواج الكلمات قبل أي نداء نموذج -- كل الشروط لازمة معًا.
    يعيد (الرسم الأكثر ورودًا، الرسم الأقل ورودًا، عدده، عدد الآخر) لكل
    زوج ناجٍ، مرتّبة لضمان ترتيب ثابت بين تشغيلة وأخرى."""
    words = sorted(w for w, n in seen_totals.items()
                    if len(w) >= _MIN_WORD_LEN and n >= _MIN_LOW_COUNT)
    judged = _judged_pairs(learned)

    candidates: list[tuple[str, str, int, int]] = []
    seen_pairs: set[str] = set()
    for i, w1 in enumerate(words):
        n1 = seen_totals[w1]
        for w2 in words[i + 1:]:
            n2 = seen_totals[w2]
            hi_word, lo_word = (w1, w2) if n1 >= n2 else (w2, w1)
            hi_n, lo_n = (n1, n2) if n1 >= n2 else (n2, n1)
            if hi_n < _MIN_HIGH_COUNT or lo_n < _MIN_LOW_COUNT:
                continue
            if hi_n < _MIN_RATIO * lo_n:
                continue
            if w1 in blocklist or w2 in blocklist:
                continue
            key = _pair_key(w1, w2)
            if key in judged or key in seen_pairs:
                continue
            if _levenshtein(_unify_structure(w1), _unify_structure(w2)) > _MAX_LEVENSHTEIN:
                continue
            seen_pairs.add(key)
            candidates.append((hi_word, lo_word, hi_n, lo_n))
    return candidates


def _max_tokens_for(n: int, lcfg: dict) -> int:
    tokens_per_pair = int(lcfg.get("tokens_per_pair", 40))
    cap = int(lcfg.get("max_tokens_cap", 3000))
    return min(cap, tokens_per_pair * max(n, 1) + _MAX_TOKENS_BASE)


def _parse_verdicts(text: str) -> dict[int, str]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise
        data = json.loads(text[start:end + 1])
    out: dict[int, str] = {}
    for item in (data.get("verdicts") or []):
        out[int(item["i"])] = str(item.get("verdict") or "")
    return out


def _ask_batch(client, model: str, batch: list[tuple[str, str, int, int]],
                lcfg: dict) -> tuple[dict[str, str] | None, bool]:
    """نداء واحد لدفعة من الأزواج. يعيد (الأحكام بمفتاح الزوج أو None عند
    فشل التحليل، هل قُطع الرد stop_reason == "max_tokens")."""
    listing = "\n".join(
        f'{i}. "{a}" مقابل "{b}"' for i, (a, b, _, _) in enumerate(batch))
    max_tokens = _max_tokens_for(len(batch), lcfg)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM,
        messages=[{"role": "user", "content": f"احكم على هذه الأزواج:\n\n{listing}"}],
    )
    record_usage(resp, model)
    truncated = getattr(resp, "stop_reason", "") == "max_tokens"
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    try:
        parsed = _parse_verdicts(text)
    except (json.JSONDecodeError, ValueError, KeyError, TypeError, IndexError):
        return None, truncated

    out: dict[str, str] = {}
    for i, (a, b, _, _) in enumerate(batch):
        verdict = parsed.get(i)
        if verdict in ("same_name", "inflection", "different"):
            out[_pair_key(a, b)] = verdict
    return out, truncated


def _judge(client, model: str, candidates: list[tuple[str, str, int, int]],
           lcfg: dict) -> tuple[dict[str, str], bool]:
    """نداء واحد على الدفعة كلها، وإعادة محاولة واحدة فقط بتقسيم الدفعة
    نصفين عند القطع (نفس نمط screen.py، Issue #1047) -- لا محاولات أخرى
    بعدها. يعيد (الأحكام بمفتاح الزوج، هل بقي أي زوج بلا حكم)."""
    try:
        verdicts, truncated = _ask_batch(client, model, candidates, lcfg)
    except APIError as exc:
        log.error("فشل نداء تعلّم الأسماء (عطل شبكة): %s", exc)
        return {}, True

    if verdicts is not None and not truncated:
        return verdicts, False

    if not truncated:
        log.error("فشل نداء تعلّم الأسماء -- تعذّر تحليل الرد")
        return {}, True

    log.error(
        "تعلّم الأسماء مقطوع (stop_reason=max_tokens) لدفعة من %d -- إعادة "
        "محاولة واحدة بتقسيم الدفعة", len(candidates))
    half = max(1, len(candidates) // 2)
    halves = ([candidates[:half], candidates[half:]] if len(candidates) > 1
              else [candidates])
    merged: dict[str, str] = {}
    any_unresolved = False
    for sub in halves:
        if not sub:
            continue
        try:
            sub_verdicts, sub_truncated = _ask_batch(client, model, sub, lcfg)
        except APIError:
            sub_verdicts, sub_truncated = None, False
        if sub_verdicts is not None and not sub_truncated:
            merged.update(sub_verdicts)
        else:
            any_unresolved = True
    return merged, any_unresolved


def _merge_pair(entries: dict, hi_word: str, lo_word: str, hi_n: int, lo_n: int,
                 now_iso: str) -> None:
    """يدمج زوجًا محكومًا عليه بـsame_name في entries. إن كان أحد الرسمين
    عضوًا في مدخل قائم (معتمَدًا أو متغيّرًا) يُدمَج الرسم الآخر فيه بدل
    مدخل جديد منفصل -- المعتمد يُعاد حسابه من الأكثر ورودًا بين كل رسوم
    المدخل مجتمعة (لا يبقى ثابتًا بالضرورة عبر عمليات دمج متتالية)."""
    target_canonical = None
    for canonical, info in entries.items():
        words = {canonical, *(info.get("variants") or [])}
        if hi_word in words or lo_word in words:
            target_canonical = canonical
            break

    if target_canonical is None:
        entries[hi_word] = {
            "variants": [lo_word],
            "counts": {hi_word: hi_n, lo_word: lo_n},
            "learned_at": now_iso,
            "verdict": "same_name",
        }
        return

    entry = entries.pop(target_canonical)
    words = {target_canonical, *(entry.get("variants") or []), hi_word, lo_word}
    counts = dict(entry.get("counts") or {})
    counts[hi_word] = hi_n
    counts[lo_word] = lo_n
    new_canonical = max(words, key=lambda w: counts.get(w, 0))
    variants = sorted(w for w in words if w != new_canonical)
    entries[new_canonical] = {
        "variants": variants,
        "counts": counts,
        "learned_at": now_iso,
        "verdict": "same_name",
    }


def run(cfg: Any) -> None:
    """نقطة الدخول الوحيدة -- تُستدعى من src.collect.py في نهاية دورة
    الجمع. لا تُلقي استثناءً في المسار العادي (فشل نداء النموذج/الشبكة
    يُعامَل داخليًا)؛ المستدعي يُحيطها بـtry/except إضافيًا احتياطًا فقط،
    بنفس نمط decisions.scan."""
    if not names.cfg_get(cfg, "names.learned_enabled", True):
        return

    data = load_learned()
    if not _due(data):
        return

    now = datetime.now(timezone.utc)
    data["last_run"] = now.isoformat()

    blocklist = names.blocklist_of(cfg)
    candidates = find_candidates(names.seen_totals(), data, blocklist)
    if not candidates:
        save_learned(data)
        return

    model = names.cfg_get(cfg, "screening.model", "claude-haiku-4-5-20251001")
    lcfg = names.cfg_get(cfg, "names.learn", {}) or {}
    try:
        client = _client()
    except RuntimeError as exc:
        log.error("تعذّر تعلّم الأسماء -- غياب مفتاح API: %s", exc)
        save_learned(data)
        return

    # _judge نفسها تُسجِّل سطر ERROR واحدًا عند أي فشل (عطل شبكة/تحليل/قطع)
    # -- لا تكرار هنا. زوج بقي بلا حكم (unresolved) يبقى مرشَّحًا ببساطة
    # للدورة القادمة عبر حلقة التطبيق أدناه (verdict is None ⇒ تخطٍّ بلا
    # ترحيل إلى rejected_pairs).
    verdicts, _unresolved = _judge(client, model, candidates, lcfg)

    entries = data.setdefault("entries", {})
    rejected_pairs = set(data.get("rejected_pairs") or [])
    now_iso = now.isoformat()

    for hi_word, lo_word, hi_n, lo_n in candidates:
        verdict = verdicts.get(_pair_key(hi_word, lo_word))
        if verdict is None:
            continue  # لم يُحكم عليه (فشل جزئي) -- يبقى مرشَّحًا للدورة القادمة
        if verdict != "same_name":
            rejected_pairs.add(_pair_key(hi_word, lo_word))
            continue
        _merge_pair(entries, hi_word, lo_word, hi_n, lo_n, now_iso)
        log.info("تعلّم توحيد رسم: %s ← %s (%d مقابل %d)", lo_word, hi_word, hi_n, lo_n)

    data["rejected_pairs"] = sorted(rejected_pairs)
    save_learned(data)
