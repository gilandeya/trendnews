"""حذف دوري لما تجاوز نافذة الاحتفاظ (``retention.days``) من ``drafts/`` و
``state/candidates/`` (Issue #956).

تشغيلة متحركة لا دفعة: كل استدعاء يحذف ما تجاوز النافذة وقت تشغيله، لا ما
تراكم منذ آخر مرة — فحجم المحذوف يبقى صغيرًا ومتوقعًا من تشغيلة لأخرى، ولا
حاجة لتتبّع "آخر مرة حُذف فيها" في state/.
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import DRAFTS_DIR, load_config
from .store import CANDIDATES_DIR

log = logging.getLogger("retention")


def _folder_date(folder: Path) -> datetime | None:
    """تاريخ مجلد اليوم (``YYYY-MM-DD``)، أو ``None`` إن لم يطابق الصيغة —
    مجلد كهذا ليس من إنتاج store.draft_dir/candidate_dir فيُتجاهل بأمان بدل
    تخمين عمره."""
    try:
        return datetime.strptime(folder.name, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_iso_utc(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    # بيانات قديمة نادرة قد تكون بلا منطقة زمنية — تُعامَل كأنها UTC بدل أن
    # تُسقِط المقارنة لاحقًا بخطأ offset-naive/aware.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _age_reference(draft: dict, folder_date: datetime) -> datetime:
    """التاريخ الذي يُقاس عليه عمر المسودة، بحسب قاعدة العمر التحريرية:
    المنشورة تُقاس من ``published_at`` (وإلا من تاريخ مجلدها)، وأي حالة أخرى
    غير ``queued`` (المستبعدة قبل الوصول لهذه الدالة) تُقاس من تاريخ مجلدها
    دومًا — pending/failed/rejected لا تاريخ حالة موثوق آخر لها."""
    if draft.get("status") == "published":
        raw = draft.get("published_at")
        if raw:
            parsed = _parse_iso_utc(raw)
            if parsed is not None:
                return parsed
        return folder_date
    return folder_date


def sweep_drafts(draft_dir: Path, cutoff: datetime, dry_run: bool) -> dict:
    stats = {"drafts_removed": 0, "images_removed": 0, "bytes_freed": 0,
             "unreadable": 0, "folders_removed": 0}
    if not draft_dir.exists():
        return stats

    for folder in sorted(p for p in draft_dir.iterdir() if p.is_dir()):
        folder_date = _folder_date(folder)
        if folder_date is None:
            continue

        removed_names: set[str] = set()
        for json_path in sorted(folder.glob("*.json")):
            try:
                draft = json.loads(json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                log.warning("ملف مسودة تالف — تُرك بلا حذف: %s", json_path)
                stats["unreadable"] += 1
                continue

            if draft.get("status") == "queued":
                continue  # لا تُحذف أبدًا مهما كان عمرها

            if _age_reference(draft, folder_date) >= cutoff:
                continue

            # الحذف وحدة واحدة: JSON مع كل ملفاتها المرافقة في نفس المجلد
            # (البطاقة وإصداراتها من next_image_path، الريل...). المعرّفات
            # كلها sha1[:12] بطول ثابت فلا يكون أحدها بادئة لآخر، فالـglob
            # بالمعرّف وحده كافٍ ومضمون العزل بين المسودات.
            draft_id = draft.get("id") or json_path.stem
            for sibling in sorted(folder.glob(f"{draft_id}*")):
                size = sibling.stat().st_size
                if dry_run:
                    print(f"  [تجربة] حذف: {sibling}")
                else:
                    sibling.unlink(missing_ok=True)
                stats["bytes_freed"] += size
                removed_names.add(sibling.name)
                if sibling.suffix == ".json":
                    stats["drafts_removed"] += 1
                else:
                    stats["images_removed"] += 1

        # مجلد يوم صار فارغًا (لا ملفات تبقّت خارج ما حُذف أعلاه) يُحذف —
        # remaining تُحسب حتى في --dry-run فتُعكس نفس النتيجة بلا حذف فعلي،
        # لأن removed_names تُستثنى بصرف النظر عن وجود الملف فعليًا على القرص.
        remaining = [f for f in folder.iterdir() if f.name not in removed_names]
        if not remaining:
            if dry_run:
                print(f"  [تجربة] حذف مجلد فارغ: {folder}")
            else:
                folder.rmdir()
            stats["folders_removed"] += 1

    return stats


def sweep_candidates(candidates_dir: Path, cutoff: datetime, dry_run: bool) -> dict:
    """مرشحو preselect: لا حالة queued لهم ولا published_at — مجلد اليوم
    كاملًا يُحذف أو يبقى بحسب تاريخه وحده."""
    stats = {"candidate_folders_removed": 0, "bytes_freed": 0}
    if not candidates_dir.exists():
        return stats

    for folder in sorted(p for p in candidates_dir.iterdir() if p.is_dir()):
        folder_date = _folder_date(folder)
        if folder_date is None or folder_date >= cutoff:
            continue
        size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
        if dry_run:
            print(f"  [تجربة] حذف مجلد مرشحين: {folder}")
        else:
            shutil.rmtree(folder)
        stats["candidate_folders_removed"] += 1
        stats["bytes_freed"] += size

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="حذف دوري لما تجاوز نافذة الاحتفاظ من drafts/ وstate/candidates/")
    parser.add_argument("--dry-run", action="store_true",
                        help="اطبع ما سيُحذف بلا حذف فعلي")
    args = parser.parse_args(argv)

    cfg = load_config()
    days = int(cfg.path("retention.days", 30))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    draft_stats = sweep_drafts(DRAFTS_DIR, cutoff, args.dry_run)
    cand_stats = sweep_candidates(CANDIDATES_DIR, cutoff, args.dry_run)

    total_kb = (draft_stats["bytes_freed"] + cand_stats["bytes_freed"]) / 1024
    prefix = "🧪 [تجربة] " if args.dry_run else ""
    print(
        f"{prefix}🗑️ الاحتفاظ ({days} يومًا): "
        f"{draft_stats['drafts_removed']} مسودة، "
        f"{draft_stats['images_removed']} صورة/ملف مرفق، "
        f"{draft_stats['folders_removed']} مجلد مسودات فارغ، "
        f"{cand_stats['candidate_folders_removed']} مجلد مرشحين، "
        f"{total_kb:.1f} كيلوبايت مُحرَّرة"
    )
    if draft_stats["unreadable"]:
        print(f"⚠️ {draft_stats['unreadable']} ملف مسودة تالف تُرك بلا حذف")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
