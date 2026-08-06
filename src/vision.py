"""تحليل محتوى الصورتين لتقرير أيّهما في الدائرة وأيّهما خلفية.

القاعدة التحريرية: **الموضوع في الدائرة، والمشهد خلفية**. الإنسان أولًا،
ثم الحيوان، ثم الجسم المصنوع. والدائرة صغيرة، فما يُوضع فيها يجب أن
يُقرأ فورًا — وجه أو حيوان أو سيارة، لا مشهد واسع.

سُلَّم القرار:
  ١. الصورتان متشابهتان لونيًا (< 30% فارق) → صورة واحدة
  ٢. الأقل أشخاصًا                          → الدائرة
  ٣. تساوى العدد وأكثر من واحد:
       أحدهما أقرب بأكثر من 50%             → الدائرة
       وإلا                                  → صورة واحدة
  ٤. بلا بشر: صاحبة الحيوان                 → الدائرة
  ٥. ثم صاحبة الجسم المصنوع                 → الدائرة
  ٦. لا شيء مميّز                           → صورة واحدة

البند الأخير مقصود: حين لا يوجد سبب واضح، لا دائرة. دائرة عشوائية تحجب
موضوع الخبر أسوأ من غيابها.
"""
from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

from PIL import Image

from .config import ROOT

log = logging.getLogger(__name__)

# خارج state/ عمدًا: هذا المجلد يُرفع للمستودع، ونموذج بحجم 22 ميغابايت
# يبقى فيه للأبد. تنزيله في كل تشغيلة يكلّف ثانية واحدة ولا شيء غيرها.
MODEL_DIR = ROOT / ".models"
PROTO_URL = ("https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/"
             "master/deploy.prototxt")
WEIGHTS_URL = ("https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/"
               "master/mobilenet_iter_73000.caffemodel")

# أصناف MobileNet-SSD بالترتيب
CLASSES = ["background", "aeroplane", "bicycle", "bird", "boat", "bottle",
           "bus", "car", "cat", "chair", "cow", "diningtable", "dog", "horse",
           "motorbike", "person", "pottedplant", "sheep", "sofa", "train",
           "tvmonitor"]
ANIMALS = {"bird", "cat", "cow", "dog", "horse", "sheep"}
OBJECTS = {"aeroplane", "bicycle", "boat", "bus", "car", "motorbike", "train",
           "bottle", "tvmonitor"}

_net = None


def _load_net():
    """يحمّل النموذج، ويُنزّله مرة واحدة إن لزم."""
    global _net
    if _net is not None:
        return _net
    try:
        import cv2
    except ImportError:
        log.warning("OpenCV غير مثبّت — تحليل المحتوى معطّل")
        return None

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    proto, weights = MODEL_DIR / "ssd.prototxt", MODEL_DIR / "ssd.caffemodel"
    try:
        for path, url in ((proto, PROTO_URL), (weights, WEIGHTS_URL)):
            if not path.exists() or path.stat().st_size < 1000:
                log.info("تنزيل نموذج التعرّف: %s", path.name)
                urllib.request.urlretrieve(url, path)
        _net = cv2.dnn.readNetFromCaffe(str(proto), str(weights))
        return _net
    except Exception as exc:  # noqa: BLE001 — الشبكة أو الملف
        log.warning("تعذّر تحميل نموذج التعرّف: %s", exc)
        return None


def detect(img: Image.Image, min_confidence: float = 0.45) -> list[dict]:
    """
    يكتشف الكائنات في الصورة.

    يعيد [{"label": "person", "area": 0.18}] — المساحة نسبة إلى الصورة.
    """
    net = _load_net()
    if net is None:
        return []
    try:
        import cv2
        import numpy as np

        arr = np.array(img.convert("RGB"))[:, :, ::-1]
        h, w = arr.shape[:2]
        blob = cv2.dnn.blobFromImage(cv2.resize(arr, (300, 300)), 0.007843,
                                     (300, 300), 127.5)
        net.setInput(blob)
        detections = net.forward()
    except Exception as exc:  # noqa: BLE001
        log.debug("فشل التعرّف: %s", exc)
        return []

    found: list[dict] = []
    for i in range(detections.shape[2]):
        confidence = float(detections[0, 0, i, 2])
        if confidence < min_confidence:
            continue
        index = int(detections[0, 0, i, 1])
        if not 0 <= index < len(CLASSES):
            continue
        x1, y1, x2, y2 = detections[0, 0, i, 3:7]
        area = max(0.0, min(1.0, (x2 - x1))) * max(0.0, min(1.0, (y2 - y1)))
        if area <= 0:
            continue
        found.append({"label": CLASSES[index], "area": float(area)})
    return found


# ──────────────────────────── الوصف ────────────────────────────


def describe(img: Image.Image) -> dict:
    """ملخّص محتوى الصورة: عدد الأشخاص، وقرب أكبرهم، ووجود حيوان أو جسم."""
    objects = detect(img)
    people = [o for o in objects if o["label"] == "person"]
    animals = [o for o in objects if o["label"] in ANIMALS]
    things = [o for o in objects if o["label"] in OBJECTS]

    return {
        "people": len(people),
        "closest": max((p["area"] for p in people), default=0.0),
        "animal": max((a["area"] for a in animals), default=0.0),
        "object": max((t["area"] for t in things), default=0.0),
        "labels": sorted({o["label"] for o in objects}),
    }


def palette_distance(a: Image.Image, b: Image.Image, bins: int = 4) -> float:
    """
    فارق لوني بين صورتين، من 0 (متطابقتان) إلى 1 (مختلفتان تمامًا).

    نبني مدرّجًا لونيًا مبسّطًا لكل صورة ونقارنهما. صورتان بألوان متقاربة
    تبدوان مكرّرتين في الكارت ولو اختلف محتواهما.
    """
    def histogram(img: Image.Image) -> list[float]:
        small = img.convert("RGB").resize((48, 48), Image.LANCZOS)
        counts = [0] * (bins ** 3)
        step = 256 // bins
        for r, g, bl in small.getdata():
            counts[(r // step) * bins * bins + (g // step) * bins
                   + (bl // step)] += 1
        total = sum(counts) or 1
        return [c / total for c in counts]

    ha, hb = histogram(a), histogram(b)
    return sum(abs(x - y) for x, y in zip(ha, hb)) / 2


# ──────────────────────────── القرار ────────────────────────────


def choose_layout(main: Image.Image, second: Image.Image, cfg) -> dict:
    """
    يقرر: هل نستخدم صورتين؟ وأيّهما في الدائرة؟

    يعيد {"composite": bool, "swap": bool, "reason": str}
      swap=True يعني أن الصورة الثانية تصلح خلفيةً والأولى للدائرة.
    """
    icfg = cfg.get("image", {}) or {}
    min_palette = float(icfg.get("inset_min_palette", 0.30))
    closer_ratio = float(icfg.get("inset_closer_ratio", 1.5))

    distance = palette_distance(main, second)
    if distance < min_palette:
        return {"composite": False, "swap": False,
                "reason": f"ألوان متقاربة ({distance:.2f} < {min_palette})"}

    a, b = describe(main), describe(second)
    log.info("محتوى الصور: خلفية=%s · مرشحة=%s", a["labels"] or "—",
             b["labels"] or "—")

    # ── البشر أولًا ──
    if a["people"] or b["people"]:
        if a["people"] != b["people"]:
            # الأقل أشخاصًا للدائرة: الوجه المفرد يُقرأ، والحشد لا
            swap = a["people"] < b["people"]
            fewer = min(a["people"], b["people"])
            if fewer == 0:
                # إحداهما بلا بشر: البشر للدائرة
                swap = b["people"] == 0
            return {"composite": True, "swap": swap,
                    "reason": f"أشخاص {a['people']} مقابل {b['people']}"}

        if a["people"] > 1:
            near_a, near_b = a["closest"], b["closest"]
            hi, lo = max(near_a, near_b), min(near_a, near_b)
            if lo > 0 and hi / lo >= closer_ratio:
                return {"composite": True, "swap": near_a > near_b,
                        "reason": f"الأقرب للكاميرا ({hi:.2f} مقابل {lo:.2f})"}
            return {"composite": False, "swap": False,
                    "reason": "عدد متساوٍ وقرب متقارب"}

        # شخص واحد في كلٍّ: الأقرب للدائرة
        if a["closest"] != b["closest"]:
            return {"composite": True, "swap": a["closest"] > b["closest"],
                    "reason": f"قرب {a['closest']:.2f} مقابل {b['closest']:.2f}"}

    # ── الحيوان ثم الجسم المصنوع ──
    for key, name in (("animal", "حيوان"), ("object", "جسم")):
        if a[key] or b[key]:
            if a[key] and b[key]:
                return {"composite": True, "swap": a[key] > b[key],
                        "reason": f"{name} في كليهما — الأكبر للدائرة"}
            return {"composite": True, "swap": bool(a[key]),
                    "reason": f"{name} في إحداهما"}

    return {"composite": False, "swap": False,
            "reason": "لا موضوع مميّز في أيٍّ منهما"}
