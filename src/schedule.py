"""توزيع المنشورات المعتمدة على أوقات الذروة بدل نشرها دفعة واحدة.

المشكلة: اعتماد ثلاث مسودات الساعة الثالثة فجرًا ينشرها كلها فورًا، فتضيع.
الحل: طابور خاص بنا — كل منشور يأخذ أقرب فتحة ذروة شاغرة، وبينه وبين
سابقه فاصل زمني. سير عمل يعمل كل ساعة ينشر ما حان وقته.

لا نستخدم جدولة فيسبوك الأصلية (scheduled_publish_time) لأنها تمنع إضافة
تعليق قبل النشر، وهو ما يكسر ميزة "الرابط في التعليق الأول".
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)


def tz_of(name: str) -> ZoneInfo | timezone:
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 — منطقة زمنية غير معروفة
        log.warning("منطقة زمنية غير معروفة '%s' — سيُستخدم UTC", name)
        return timezone.utc


def upcoming_slots(peak_hours: list[int], tz, start: datetime, days: int = 4):
    """يولّد فتحات الذروة القادمة بالترتيب الزمني."""
    local = start.astimezone(tz)
    hours = sorted(set(int(h) % 24 for h in peak_hours)) or [18]
    for day in range(days):
        base = (local + timedelta(days=day)).replace(
            minute=0, second=0, microsecond=0
        )
        for hour in hours:
            slot = base.replace(hour=hour)
            if slot > local:
                yield slot.astimezone(timezone.utc)


def assign_slots(
    count: int,
    peak_hours: list[int],
    timezone_name: str,
    min_gap_minutes: int = 120,
    taken: list[datetime] | None = None,
    now: datetime | None = None,
    grace_minutes: int = 20,
) -> list[datetime]:
    """
    يعطي `count` مواعيد نشر، بلا ازدحام.

    - أول منشور ينطلق فورًا إذا كنا داخل فتحة ذروة ولا يوجد منشور قريب.
    - الباقي يوزّع على الفتحات القادمة مع احترام الفاصل الأدنى.
    """
    tz = tz_of(timezone_name)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    booked = sorted(t.astimezone(timezone.utc) for t in (taken or []))
    gap = timedelta(minutes=max(min_gap_minutes, 1))

    def is_free(when: datetime) -> bool:
        return all(abs(when - b) >= gap for b in booked)

    chosen: list[datetime] = []

    # هل نحن الآن داخل ساعة ذروة؟ إن كان، انشر أولها فورًا.
    local_hour = now.astimezone(tz).hour
    if local_hour in {int(h) % 24 for h in peak_hours} and is_free(now):
        chosen.append(now)
        booked.append(now)
        booked.sort()

    for slot in upcoming_slots(peak_hours, tz, now):
        if len(chosen) >= count:
            break
        # تجاهل فتحة مضت للتو
        if slot < now - timedelta(minutes=grace_minutes):
            continue
        if is_free(slot):
            chosen.append(slot)
            booked.append(slot)
            booked.sort()

    # لو نفدت الفتحات، أضف مواعيد متباعدة بعد آخر موعد
    while len(chosen) < count:
        last = chosen[-1] if chosen else now
        chosen.append(last + gap)

    return chosen[:count]


def interval_slots(count: int, interval_minutes: int,
                   now: datetime | None = None,
                   taken: list[datetime] | None = None) -> list[datetime]:
    """
    مواعيد متتابعة بفاصل ثابت: الأول فورًا، ثم كل `interval_minutes`.

    يُستخدم في نمط "interval": الخبر الأهم يخرج حالًا، والباقي يتتابع
    بفواصل قصيرة بدل انتظار ساعة ذروة.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    gap = timedelta(minutes=max(interval_minutes, 1))

    # لا نصطدم بما هو محجوز في الطابور أصلًا
    start = now
    for t in sorted(x.astimezone(timezone.utc) for x in (taken or [])):
        if abs(t - start) < gap:
            start = t + gap

    return [start + gap * i for i in range(count)]


def burst_slots(count: int, gap_minutes: float = 5,
                now: datetime | None = None) -> list[datetime]:
    """
    نمط الدفعة: الأول فورًا، ثم فاصل ثابت بين كل منشور والذي يليه.

    يُستخدم حين تريد الأعلى ترندًا أن يخرج في اللحظة التي تعتمده فيها،
    وبقية الدفعة تتوالى خلف بفواصل قصيرة.
    """
    start = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    gap = timedelta(minutes=max(float(gap_minutes), 0.05))
    return [start + gap * i for i in range(max(count, 0))]


def is_due(publish_at: str | datetime, now: datetime | None = None) -> bool:
    when = (
        datetime.fromisoformat(publish_at) if isinstance(publish_at, str) else publish_at
    )
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when <= (now or datetime.now(timezone.utc))


def describe(when: datetime, timezone_name: str) -> str:
    """صياغة موعد بتوقيت المستخدم لعرضه في صفحة المراجعة."""
    local = when.astimezone(tz_of(timezone_name))
    return local.strftime("%Y/%m/%d الساعة %H:%M")
