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
