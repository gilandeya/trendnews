"""نداء Gemini المشترك: رابط يوتيوب يُعطى للنموذج فتجلب Google الفيديو بنفسها (لا بروكسي ولا نص يوتيوب ولا تنزيل).

مستعمل في خطوة أسئلة الموضوع (`gemini_bites`) وفي أداة القياس (`tools/gemini_probe.py`). قياس 6/11 على سبع حلقات: 29 من 31 مقطعًا
بقائله نفسه، وانزياح وسيط ثانية أو أقل، و0.57$ لـ89 دقيقة؛ ولهذا صار مصدر المقاطع حين نفد رصيد البروكسي.
"""

from __future__ import annotations

import json
import time

API = "https://generativelanguage.googleapis.com/v1beta"


def parse_clock(value, duration: float | None = None) -> float | None:
    """«H:MM:SS» أو «MM:SS» أو «SS» (وكسور الثانية) ← ثوانٍ؛ غير ذلك None. Gemini يكتب الزمن نصًا فلا يُوثق بشكل واحد: في أول قياس
    (6/11) كتب بعد الدقيقة 9 «1:10:25» يريد 10:25 في حلقة طولها 17 دقيقة، فزمن بثلاثة أجزاء يتجاوز مدة الحلقة يُقرأ بلا ساعته."""
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value or "").strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if not nums or len(nums) > 3 or any(n < 0 for n in nums):
        return None
    total = 0.0
    for n in nums:
        total = total * 60 + n
    if duration and len(nums) == 3 and total > duration and nums[1] * 60 + nums[2] <= duration:
        return nums[1] * 60 + nums[2]
    return total


def video_part(video_id: str, max_minutes: float = 0, duration: float | None = None) -> dict:
    """جزء الفيديو في الطلب. الحلقة الأطول من max_minutes تُقصّ بـend_offset فلا يُدفع ثمن ما لا يُقرأ."""
    part = {"file_data": {"file_uri": f"https://www.youtube.com/watch?v={video_id}"}}
    cap = float(max_minutes or 0) * 60
    if cap and (duration is None or duration > cap):
        part["video_metadata"] = {"end_offset": f"{int(cap)}s"}
    return part


def read_response(resp: dict, key: str = "segments") -> tuple[dict | None, str, dict]:
    """(الناتج أو None، سبب التوقف، الاستهلاك). الرد المقطوع (MAX_TOKENS) لا يُقبل منه شيء: JSON ناقص يعطي مقاطع ناقصة بلا تنبيه."""
    cands = resp.get("candidates") or []
    finish = (cands[0].get("finishReason") if cands else "") or ""
    usage = resp.get("usageMetadata") or {}
    if not cands or finish == "MAX_TOKENS":
        return None, finish or "no_candidates", usage
    text = "".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts") or [] if not p.get("thought"))
    try:
        data = json.loads(text)
    except ValueError:
        return None, f"{finish}:invalid_json", usage
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        return None, f"{finish}:bad_shape", usage
    return data, finish, usage


def cost_usd(usage: dict, price: dict) -> float:
    """الكلفة التقديرية: الصوت بسعره والباقي (صور الفيديو والنص) بسعر الإدخال، والتفكير يُحسب مخرجًا كما تحسبه Google."""
    price = price or {}
    audio = sum(d.get("tokenCount", 0) for d in usage.get("promptTokensDetails") or [] if d.get("modality") == "AUDIO")
    prompt = usage.get("promptTokenCount", 0) or 0
    out = (usage.get("candidatesTokenCount", 0) or 0) + (usage.get("thoughtsTokenCount", 0) or 0)
    total = ((prompt - audio) * price.get("input", 0) + audio * price.get("audio", 0) + out * price.get("output", 0)) / 1e6
    return round(total, 4)


def generate(body: dict, model: str, key: str, post=None, timeout: int = 900) -> tuple[int, dict | str, float]:
    """(رمز HTTP، الرد JSON أو أول 300 حرف من نصه، الثواني). المفتاح في رأس x-goog-api-key لا في الرابط فلا يظهر في سجل خطأ.
    post يُحقن في الاختبار؛ الحقيقي requests.post."""
    import requests
    post = post or requests.post
    t0 = time.monotonic()
    r = post(f"{API}/models/{model}:generateContent", json=body, timeout=timeout,
             headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    seconds = round(time.monotonic() - t0, 1)
    if r.status_code != 200:
        return r.status_code, (r.text or "")[:300], seconds
    return 200, r.json(), seconds
