"""النشر على صفحة فيسبوك عبر Graph API."""
from __future__ import annotations

import logging
from pathlib import Path

import requests

from .config import env

log = logging.getLogger(__name__)


class FacebookError(RuntimeError):
    pass


def _credentials() -> tuple[str, str]:
    return (
        env("FB_PAGE_ID", required=True),          # type: ignore[return-value]
        env("FB_PAGE_ACCESS_TOKEN", required=True),  # type: ignore[return-value]
    )


def _raise_for_graph(resp: requests.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        raise FacebookError(f"رد غير متوقع من فيسبوك ({resp.status_code}): {resp.text[:300]}")
    if "error" in data:
        err = data["error"]
        raise FacebookError(
            f"خطأ فيسبوك [{err.get('code')}/{err.get('error_subcode')}]: "
            f"{err.get('message')}"
        )
    if resp.status_code >= 400:
        raise FacebookError(f"فشل الطلب ({resp.status_code}): {resp.text[:300]}")
    return data


def publish_photo(image_path: Path, caption: str, api_version: str = "v21.0") -> dict:
    """
    ينشر منشور صورة مع تعليق على الصفحة.
    يعيد {"post_id": ..., "url": ...}
    """
    page_id, token = _credentials()
    url = f"https://graph.facebook.com/{api_version}/{page_id}/photos"

    with open(image_path, "rb") as fh:
        resp = requests.post(
            url,
            data={"message": caption, "published": "true", "access_token": token},
            files={"source": (image_path.name, fh, "image/jpeg")},
            timeout=120,
        )
    data = _raise_for_graph(resp)

    post_id = data.get("post_id") or data.get("id")
    log.info("تم النشر: %s", post_id)
    return {
        "post_id": post_id,
        "photo_id": data.get("id"),
        "url": f"https://www.facebook.com/{post_id}" if post_id else None,
    }


def publish_link(link: str, caption: str, api_version: str = "v21.0") -> dict:
    """بديل: منشور نصي برابط (يستخدم صورة المعاينة من الموقع)."""
    page_id, token = _credentials()
    url = f"https://graph.facebook.com/{api_version}/{page_id}/feed"
    resp = requests.post(
        url, data={"message": caption, "link": link, "access_token": token}, timeout=60
    )
    data = _raise_for_graph(resp)
    post_id = data.get("id")
    return {"post_id": post_id, "url": f"https://www.facebook.com/{post_id}"}


def verify_token(api_version: str = "v21.0") -> dict:
    """فحص سريع للصلاحيات — استخدمه قبل أول تشغيل حقيقي."""
    page_id, token = _credentials()
    resp = requests.get(
        f"https://graph.facebook.com/{api_version}/{page_id}",
        params={"fields": "id,name,fan_count", "access_token": token},
        timeout=30,
    )
    return _raise_for_graph(resp)
