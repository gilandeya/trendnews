"""صورة الشخص خلف الجملة التي تسمّيه (طلب صاحب المشروع 22/11): القاعدة العامة «كل جملة راوٍ تُظهر ما تسمّيه» — المكان خريطة
(reel_map) والشخص صورته. جملة «الرئيس الأمريكي دونالد ترمب تحدث عن الملف الأبرز» كانت تُعرض على خلفية الحدث العامة.

الحكم من النموذج (خطة اللقطات تسمّي الشخص في حقل person) أو من الكود (متحدث موثَّق في الريل نفسه مذكور في الجملة)، والتحقق في
الكود: الاسم وارد في الجملة كما ستُقرأ. المصدر بالترتيب: لقطة من الحدث نفسه (مقطع في الريل قائله هذا الشخص) ← أحدث صورة من الويب
(Brave، تحت سقفه الشهري) ← ويكيميديا. الصورة تُقبل بوجه واحد بارز (لا صورة جماعية لا يُعرف فيها من المقصود) وتُعرض بتقريب بطيء
نحو الوجه. الدوال هنا خالصة عدا web_urls؛ التنزيل والرسم في reel_render."""
from __future__ import annotations

import datetime as _dt
import logging
import re
from typing import Any

from . import reel_map

log = logging.getLogger("trendnews")

_WORD = re.compile(r"[\w؀-ۿ]+")
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"]


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(reel_map.norm(text)) if w]


def _strip(w: str) -> str:
    """الكلمة بلا سابقة ملتصقة واحدة ولا «ال»: «وترمب» و«لترمب» و«الترمب» = «ترمب»."""
    for p in ("وال", "بال", "فال", "كال", "لل", "ال", "و", "ب", "ل", "ف", "ك"):
        if w.startswith(p) and len(w) - len(p) >= 3:
            return w[len(p):]
    return w


def name_in_sentence(name: str, sentence: str, cfg) -> bool:
    """هل يرد اسم الشخص في الجملة؟ كلمة من اسمه (min_word أحرف فأكثر، ليست من كلمات الصفة) ترد فيها حرفًا أو برسم قريب
    («ترمب»/«ترامب»: النقل العربي للاسم الأجنبي يختلف بين النماذج). صفة وحدها («الرئيس») لا تكفي."""
    from . import reel_clips
    fcfg = cfg.path("reel.figures") or {}
    skip = {reel_map.norm(w) for w in fcfg.get("title_words") or []}
    min_len = int(fcfg.get("min_word", 3))
    sim = float(fcfg.get("name_similarity", 0.75))
    words = [_strip(w) for w in _tokens(name) if reel_map.norm(w) not in skip]
    words = [w for w in words if len(w) >= min_len]
    if not words:
        return False
    sent = {_strip(w) for w in _tokens(sentence)}
    return any(any(reel_clips.word_close(w, s, sim, 4) for s in sent) for w in words)


def person_of(entry: dict | None) -> dict | None:
    """حقل person من خطة اللقطات بعد تنظيفه: {name_ar, name_en} أو None."""
    from . import llm
    p = llm.tool_json((entry or {}).get("person"), dict) if entry else None
    if not isinstance(p, dict):
        return None
    ar = " ".join(str(p.get("name_ar") or "").split())
    en = " ".join(str(p.get("name_en") or "").split())
    return {"name_ar": ar, "name_en": en} if ar else None


def reel_people(script: dict) -> list[dict]:
    """متحدثو الريل الموثَّقون بأسمائهم ومشاهدهم: الكود يجد من ذكرته جملة راوٍ منهم ولو لم تسمّه الخطة (خطة كُتبت قبل الحقل)."""
    out: dict[str, dict] = {}
    for i, sc in enumerate(script.get("scenes") or []):
        name = " ".join(str(sc.get("speaker_name") or "").split())
        if not name or not sc.get("speaker_verified") or sc.get("is_host"):
            continue
        p = out.setdefault(reel_map.norm(name), {"name_ar": name, "name_en": str(sc.get("speaker_name_latin")
                                                                                 or sc.get("speaker_original") or ""),
                                                  "scenes": []})
        p["scenes"].append(i)
    return list(out.values())


def sentence_person(entry: dict | None, sentence: str, people: list[dict], cfg) -> tuple[dict | None, str]:
    """(الشخص، مصدر الحكم plan|auto) لجملة، أو (None، سبب). اسم الخطة يُقبل إن ورد في الجملة؛ وإلا أول متحدث موثَّق في الريل
    يرد اسمه فيها. اسم الخطة الذي لا يرد ← «not_in_sentence» (النموذج لا يُضيف شخصًا لم تذكره الجملة)."""
    p = person_of(entry)
    why = ""
    if p:
        if name_in_sentence(p["name_ar"], sentence, cfg):
            for q in people:
                if name_in_sentence(q["name_ar"], p["name_ar"], cfg):
                    p = {**p, "scenes": q["scenes"], "name_en": p["name_en"] or q["name_en"]}
                    break
            return p, "plan"
        why = "not_in_sentence"
    if (cfg.path("reel.figures.auto_detect", True)):
        for q in people:
            if name_in_sentence(q["name_ar"], sentence, cfg):
                return dict(q), "auto"
    return None, why


def pick_face(boxes: list, size: tuple[int, int], cfg) -> tuple | None:
    """الوجه البارز (x, y, w, h) أو None (دالة خالصة): أكبر وجه ارتفاعه ≥ face.min_height من الصورة، والثاني (إن وُجد) أصغر منه
    بنسبة face.dominance على الأقل؛ صورة جماعية بوجوه متقاربة لا يُعرف فيها المقصود ← None."""
    fcfg = cfg.path("reel.figures.face") or {}
    faces = sorted((tuple(int(v) for v in b[:4]) for b in boxes or []), key=lambda b: -b[3])
    if not faces or faces[0][3] < float(fcfg.get("min_height", 0.1)) * size[1]:
        return None
    if len(faces) > 1 and faces[1][3] * float(fcfg.get("dominance", 1.6)) > faces[0][3]:
        return None
    return faces[0]


def portrait_box(size: tuple[int, int], face: tuple, cfg) -> tuple[int, int, int, int] | None:
    """مستطيل 9:16 داخل الصورة حول الوجه (دالة خالصة): أعلى ما تسعه الصورة، والوجه أفقيًا في وسطه ورأسيًا عند face_y منه.
    أقصر من min_crop_height ← None (تكبيرها إلى ارتفاع الشاشة يطمسها)."""
    fcfg = cfg.path("reel.figures") or {}
    W, H = size
    h = min(H, int(W * 16 / 9))
    w = int(h * 9 / 16)
    if h < int(fcfg.get("min_crop_height", 360)):
        return None
    cx, cy = face[0] + face[2] / 2, face[1] + face[3] / 2
    x = int(min(max(cx - w / 2, 0), W - w))
    y = int(min(max(cy - h * float(fcfg.get("face_y", 0.38)), 0), H - h))
    return x, y, x + w, y + h


def zoom_filter(fx: float, fy: float, seconds: float, cfg) -> str:
    """مرشّح ffmpeg لتقريب بطيء نحو الوجه على صورة بمقاس الشاشة (دالة خالصة): المقياس 1 ← zoom_to خطيًا على مدة الجملة، والقصّ
    يُبقي نقطة الوجه (fx, fy بكسلًا) في موضعها فيكبر الوجه ولا ينزاح. scale بـeval=frame يُقيّم كل إطار (كشعار الافتتاح)."""
    r = cfg.path("reel.render")
    W, H = int(r["width"]), int(r["height"])
    zt = float(cfg.path("reel.figures.zoom_to", 1.12))
    T = max(float(seconds), 0.1)
    z = f"(1+{zt - 1:.4f}*min(t/{T:.3f},1))"
    return (f"scale=w='trunc({W}*{z}/2)*2':h='trunc({H}*{z}/2)*2':eval=frame,"
            f"crop={W}:{H}:x='(iw-{W})*{fx / W:.4f}':y='(ih-{H})*{fy / H:.4f}'")


def web_query(person: dict, cfg, today: _dt.date | None = None) -> str:
    """عبارة البحث عن أحدث صورة: الاسم بحروفه اللاتينية (نتائج الصور بها أكثر) ثم الشهر والسنة."""
    today = today or _dt.date.today()
    name = person.get("name_en") or person.get("name_ar") or ""
    tpl = str(cfg.path("reel.figures.web.query", "{name} {month} {year}"))
    return " ".join(tpl.format(name=name, month=_MONTHS[today.month - 1], year=today.year).split())


def web_urls(person: dict, cfg) -> list[tuple[str, str]]:
    """[(رابط، المصدر web|wikimedia)] بالترتيب (الشبكة). Brave أولًا بعدّاده وسقفه الشهريين القائمين، ثم ويكيميديا بالاسم.
    كل عطل يعيد ما وُجد قبله ولا يرفع."""
    from . import imagesearch
    out: list[tuple[str, str]] = []
    sources = cfg.path("reel.figures.sources") or ["event", "web", "wikimedia"]
    try:
        if "web" in sources:
            out += [(r["url"], "web") for r in imagesearch.search_web_images(web_query(person, cfg), cfg)]
        if "wikimedia" in sources:
            q = person.get("name_en") or person.get("name_ar") or ""
            out += [(u, "wikimedia") for u in imagesearch.search_wikimedia(q, limit=int(cfg.path("reel.figures.wiki_limit", 4)))]
    except Exception as exc:  # noqa: BLE001 -- الصورة تحسين: الجملة تبقى بخلفيتها
        log.warning("تعذّر البحث عن صورة %s: %s", person.get("name_ar"), str(exc)[:120])
    return out


def mention_index(name: str, text: str, cfg) -> int | None:
    """رقم أول كلمة من text (بتقسيم المسافات، كما تُوقَّت كلمات الراوي) يرد فيها اسم الشخص بقاعدة name_in_sentence، أو None. لتوقيت
    دخول رسم الشخص عند نطق اسمه لا عند أول الجملة (قضية 2020). دالة خالصة."""
    if not name:
        return None
    for j, word in enumerate(str(text or "").split()):
        if name_in_sentence(name, word, cfg):
            return j
    return None
