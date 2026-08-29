"""إعداد بروكسي Webshare لمكتبة youtube_transcript_api (Issue #629، تكملة #626).

اختبار #626 أثبت رقميًا أن عناوين Actions محجوبة كليًا (٤٠/٤٠ محجوبة) بينما
نفس الكود من عنوان منزلي ينجح ٩٣٪ من المرات — لذا لا بدّ من بروكسي عند
التشغيل من Actions، ولا حاجة له محليًا. الوحدة تخدم الحالتين بسلوك واحد:
وجود السرّين في البيئة يفعّل Webshare، غيابهما يرجع None (اتصال مباشر) بدل
رفع خطأ، حتى يبقى التشغيل المحلي (بلا سرّين) يعمل بلا أي تعديل.
"""
from __future__ import annotations

import os
import sys

from youtube_transcript_api.proxies import ProxyConfig, WebshareProxyConfig

USERNAME_VAR = "WEBSHARE_PROXY_USERNAME"
PASSWORD_VAR = "WEBSHARE_PROXY_PASSWORD"


def get_proxy_config() -> ProxyConfig | None:
    """يقرأ اسم المستخدم وكلمة المرور من البيئة فقط -- لا إعداد بروكسي يدوي
    (عنوان خادم/منفذ)، لأن دعم Webshare المدمج في المكتبة لا يحتاجهما."""
    username = os.environ.get(USERNAME_VAR)
    password = os.environ.get(PASSWORD_VAR)
    if username and password:
        print("البروكسي: مفعّل (Webshare)", file=sys.stderr)
        return WebshareProxyConfig(proxy_username=username, proxy_password=password)
    print(
        f"البروكسي: غير مفعّل (اتصال مباشر) -- {USERNAME_VAR}/{PASSWORD_VAR} غائبان من البيئة",
        file=sys.stderr,
    )
    return None


def proxy_status_line(proxy_config: ProxyConfig | None) -> str:
    status = "مفعّل (Webshare)" if proxy_config is not None else "غير مفعّل (اتصال مباشر)"
    return f"البروكسي: {status}"
