"""تحميل الإعدادات من config.yaml ومتغيرات البيئة."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
# tests/test_pipeline.py يضبط هذين المتغيرين قبل استيراد src لتوجيه كل
# كتابة/حذف إلى مجلد مؤقت بدل drafts/ و state/ الحقيقيين في المستودع.
# الإنتاج لا يضبطهما أبدًا فتبقى القيم الافتراضية كما كانت دومًا.
DRAFTS_DIR = Path(os.environ["TRENDNEWS_DRAFTS_DIR"]) if os.environ.get(
    "TRENDNEWS_DRAFTS_DIR") else ROOT / "drafts"
STATE_DIR = Path(os.environ["TRENDNEWS_STATE_DIR"]) if os.environ.get(
    "TRENDNEWS_STATE_DIR") else ROOT / "state"

# نقاط يوتيوب الخام (اقتباسات حرفية من نصوص مترجمة آليًا) ومقالاته المسوَّدة
# لا تُخزَّن في هذا المستودع العام (Issue #724) -- تُقرأ/تُكتب من مستودع خاص
# منفصل (gilandeya/trendnews-data) يُسحَب سحبًا ثانيًا في youtube-collect.yml/
# youtube-articles.yml، وهذان المتغيران يُشيران عندها إلى مجلد ذلك السحب بدل
# state/ المحلي. الإنتاج المحلي/الاختبارات لا يضبطهما فتبقى القيمة
# الافتراضية (state/youtube_points، state/youtube_articles) -- نفس نمط
# DRAFTS_DIR/STATE_DIR أعلاه بالضبط.
YOUTUBE_POINTS_DIR = Path(os.environ["TRENDNEWS_YOUTUBE_POINTS_DIR"]) if os.environ.get(
    "TRENDNEWS_YOUTUBE_POINTS_DIR") else STATE_DIR / "youtube_points"
YOUTUBE_ARTICLES_DIR = Path(os.environ["TRENDNEWS_YOUTUBE_ARTICLES_DIR"]) if os.environ.get(
    "TRENDNEWS_YOUTUBE_ARTICLES_DIR") else STATE_DIR / "youtube_articles"

# الريلز المركَّبة mp4 + gif (Issue #1381): ملفات ثقيلة ومقاطع من مواد محمية بحقوق نشر، فمكانها المستودع الخاص
# في CI (مجلد reels/ في سحب trendnews-data) ولا تدخل هذا المستودع العام أبدًا؛ الافتراضي المحلي مُهمَل في .gitignore.
REELS_DIR = Path(os.environ["TRENDNEWS_REELS_DIR"]) if os.environ.get(
    "TRENDNEWS_REELS_DIR") else STATE_DIR / "reels"

# مقطوعات موسيقى الريل (Issue #1413): ترخيص Pixabay يمنع توزيعها وحدها فلا تدخل هذا المستودع العام أبدًا؛ في CI يشير
# REELS_DIR إلى reels/ في سحب trendnews-data فيصير assets/music بجواره (youtube-data/assets/music) بلا تعديل workflow.
MUSIC_DIR = Path(os.environ["TRENDNEWS_MUSIC_DIR"]) if os.environ.get(
    "TRENDNEWS_MUSIC_DIR") else REELS_DIR.parent / "assets" / "music"


class Config(dict):
    """قاموس إعدادات يدعم الوصول بالنقاط عبر get_path."""

    def path(self, dotted: str, default: Any = None) -> Any:
        node: Any = self
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def load_config(path: str | Path | None = None) -> Config:
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as fh:
        return Config(yaml.safe_load(fh) or {})


def env(name: str, required: bool = False, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(
            f"متغير البيئة {name} غير موجود. أضفه إلى GitHub Secrets أو ملف .env"
        )
    return value


def resolve(relative: str) -> Path:
    """يحوّل مسارًا نسبيًا في الإعدادات إلى مسار مطلق داخل المشروع."""
    p = Path(relative)
    return p if p.is_absolute() else ROOT / p
