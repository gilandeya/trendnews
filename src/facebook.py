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


def publish_photo(image_path: Path, caption: str, api_version: str = "v21.0",
                  first_comment: str | None = None) -> dict:
    """
    ينشر منشور صورة مع تعليق على الصفحة.

    إن مُرِّر first_comment، يُضاف كتعليق أول فور النشر. هذا مقصود:
    فيسبوك يخفض وصول المنشورات التي تحوي روابط خارجية في المتن، فنضع
    رابط المصدر في التعليق بدلًا من ذلك.

    يعيد {"post_id": ..., "url": ..., "comment_id": ...}
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
    result = {
        "post_id": post_id,
        "photo_id": data.get("id"),
        "url": f"https://www.facebook.com/{post_id}" if post_id else None,
    }

    if first_comment and post_id:
        try:
            result["comment_id"] = add_comment(post_id, first_comment, api_version)
        except FacebookError as exc:
            # المنشور نُشر بنجاح — لا نُفشل العملية كلها بسبب التعليق
            log.warning("تعذّر إضافة التعليق الأول: %s", exc)
            result["comment_error"] = str(exc)

    return result


def add_comment(post_id: str, message: str, api_version: str = "v21.0") -> str:
    """يضيف تعليقًا على منشور، ويعيد معرّف التعليق."""
    _, token = _credentials()
    resp = requests.post(
        f"https://graph.facebook.com/{api_version}/{post_id}/comments",
        data={"message": message, "access_token": token},
        timeout=60,
    )
    data = _raise_for_graph(resp)
    log.info("أُضيف التعليق الأول: %s", data.get("id"))
    return data.get("id", "")


def fetch_metrics(post_id: str, api_version: str = "v21.0") -> dict:
    """
    يجلب مقاييس أداء منشور.

    التفاعلات (إعجاب/تعليق/مشاركة) متاحة بصلاحية pages_read_engagement.
    أما الظهور والوصول فيحتاجان read_insights — وإن غابت، نكتفي بالتفاعل
    بدل أن نفشل.
    """
    _, token = _credentials()
    out: dict = {"post_id": post_id}

    resp = requests.get(
        f"https://graph.facebook.com/{api_version}/{post_id}",
        params={
            "fields": "created_time,reactions.summary(true).limit(0),"
                      "comments.summary(true).limit(0),shares",
            "access_token": token,
        },
        timeout=45,
    )
    try:
        data = _raise_for_graph(resp)
    except FacebookError as exc:
        log.warning("تعذّر جلب تفاعل %s: %s", post_id, exc)
        return {**out, "error": str(exc)}

    out["created_time"] = data.get("created_time")
    out["reactions"] = (data.get("reactions") or {}).get("summary", {}).get("total_count", 0)
    out["comments"] = (data.get("comments") or {}).get("summary", {}).get("total_count", 0)
    out["shares"] = (data.get("shares") or {}).get("count", 0)

    insights = requests.get(
        f"https://graph.facebook.com/{api_version}/{post_id}/insights",
        params={
            "metric": "post_impressions,post_impressions_unique,post_engaged_users",
            "access_token": token,
        },
        timeout=45,
    )
    try:
        idata = _raise_for_graph(insights)
        for row in idata.get("data", []):
            values = row.get("values") or [{}]
            out[row["name"]] = values[0].get("value", 0)
    except FacebookError as exc:
        # غالبًا صلاحية read_insights ناقصة — التفاعل وحده يكفي للتحليل
        log.info("مقاييس الوصول غير متاحة (%s)", str(exc)[:80])
        out["insights_unavailable"] = True

    return out


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
