"""نقطة التحويل الوحيدة لنداءات Haiku (Issue #1416).

كل نموذج رخيص في المشروع يُكتب في config.yaml باسم مختصر «haiku»، وهذه الوحدة وحدها تعرف أي معرّف حقيقي
يقابله (``llm.haiku_model``). هكذا يُترك التراجع إلى الجيل السابق سطرًا واحدًا في الإعداد، لا بحثًا في ملفات
المصدر. نماذج Haiku 5 تحتاج معاملات لا تحتاجها الأجيال السابقة (تعطيل التفكير وخفض الجهد، وسقف أكبر لأن
المُرمِّز يعطي رموزًا أكثر للنص نفسه)، فتُضاف هنا بالشرط على النموذج المحلول لا في كل مستدعٍ.
"""
from __future__ import annotations

import logging
import math

from anthropic import BadRequestError

from .config import load_config

log = logging.getLogger(__name__)

ALIAS = "haiku"
HAIKU5_PREFIX = "claude-haiku-5"
# فوق هذا الحجم يُسعَّر الطلب بالطبقة الأغلى (وثائق Anthropic)
PRICE_TIER_INPUT_TOKENS = 100_000
# كلمات رسالة الـ400 التي تدل على أن سبب الرفض معاملات 5.x نفسها لا غيرها
_PARAM_WORDS = ("thinking", "output_config", "effort")

_DEFAULT = None
# أسباب الرفض التي سُجّل لها ERROR في هذه العملية: سطر واحد لكل عملية لا لكل نداء
_FALLBACK_LOGGED: set[str] = set()
# المعرّفات المحلولة التي رفضها الـAPI لمعاملات 5.x: النداءات التالية تُرسَل بلا المعاملات مباشرة
# بطلب واحد، وإلا دفعنا طلبين (مرفوض ثم معاد) عن كل نداء طوال التشغيل
_PARAMS_REJECTED: set[str] = set()


def _reset_for_tests() -> None:
    _FALLBACK_LOGGED.clear()
    _PARAMS_REJECTED.clear()


def default_cfg():
    """الإعداد الافتراضي يُحمَّل مرة واحدة؛ المستدعون الذين لا يمرّرون cfg (دوال الفرز والدمج…) يقرؤون منه."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = load_config()
    return _DEFAULT


def resolve(model, cfg=None):
    """«haiku» يصير ``llm.haiku_model``؛ أي اسم آخر كما هو."""
    if model == ALIAS:
        return (cfg or default_cfg()).path("llm.haiku_model", "claude-haiku-5-5")
    return model


def _is_haiku5(resolved) -> bool:
    return isinstance(resolved, str) and resolved.startswith(HAIKU5_PREFIX)


def haiku_params(model, cfg=None) -> dict:
    """معاملات Haiku 5 وحدها؛ التفكير مفعّل افتراضيًا في هذا الجيل ويُحسب من max_tokens، ولا حاجة له في
    الفرز والاستخلاص. غير Haiku 5 (4.5 وSonnet وOpus) لا يُمسّ."""
    cfg = cfg or default_cfg()
    resolved = resolve(model, cfg)
    if not _is_haiku5(resolved):
        return {}
    return {"thinking": {"type": cfg.path("llm.haiku_thinking", "disabled")},
            "output_config": {"effort": cfg.path("llm.haiku_effort", "low")}}


def create(client, *, cfg=None, **kwargs):
    """بديل ``client.messages.create`` لكل نداء يمر بنموذج من الأسماء المختصرة أو بمعرّف صريح."""
    cfg = cfg or default_cfg()
    model = resolve(kwargs.get("model"), cfg)
    kwargs["model"] = model
    params = haiku_params(model, cfg)
    if params:
        # المُرمِّز يعطي نحو 30% رموزًا أكثر للنص نفسه، فالسقف القديم كان سيقطع ردودًا كانت تكتمل
        factor = float(cfg.path("llm.haiku_token_factor", 1.3))
        if "max_tokens" in kwargs:
            kwargs["max_tokens"] = math.ceil(kwargs["max_tokens"] * factor)
        if model not in _PARAMS_REJECTED:
            kwargs.update(params)
        else:
            params = {}
    try:
        resp = client.messages.create(**kwargs)
    except BadRequestError as exc:
        text = str(exc).lower()
        if not params or not any(w in text for w in _PARAM_WORDS):
            raise
        _PARAMS_REJECTED.add(model)
        if "params" not in _FALLBACK_LOGGED:
            _FALLBACK_LOGGED.add("params")
            log.error("رفض النموذج %s معاملات thinking/output_config (%s) — إعادة النداء بدونها؛ "
                      "راجع llm.haiku_thinking وllm.haiku_effort", model, exc)
        for k in params:
            kwargs.pop(k, None)
        resp = client.messages.create(**kwargs)
    if getattr(resp, "stop_reason", "") == "refusal":
        # نترك الرد كما هو: لا نص ولا أداة، فتسلك الدالة المستدعية طريق فشلها القائم
        log.warning("رفض النموذج %s الطلب (stop_reason=refusal): %s", model,
                    getattr(resp, "stop_details", None) or "بلا تفصيل")
    usage = getattr(resp, "usage", None)
    if (getattr(usage, "input_tokens", 0) or 0) > PRICE_TIER_INPUT_TOKENS:
        log.warning("طلب %s تجاوز %d رمز إدخال — يُسعَّر بالطبقة الأغلى", model, PRICE_TIER_INPUT_TOKENS)
    return resp
