from __future__ import annotations

from datetime import datetime, timedelta, timezone


MSK = timezone(timedelta(hours=3))


def to_rfc3339_utc(dt_utc: datetime) -> str:
    """
    RFC3339 строка в UTC: 2026-01-08T00:00:00Z
    dt_utc должен быть timezone-aware в UTC.
    """
    dt_utc = dt_utc.astimezone(timezone.utc)
    return dt_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def next_publish_time_msk(hour: int = 3, minute: int = 0) -> str:
    """
    Возвращает publishAt в UTC (RFC3339), ближайшее время hour:minute по МСК.
    """
    now_local = datetime.now(MSK)
    target_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target_local <= now_local:
        target_local += timedelta(days=1)

    target_utc = target_local.astimezone(timezone.utc)
    return to_rfc3339_utc(target_utc)


def ask_publish_at() -> str | None:
    """
    CLI-вопросы. Для вебки потом сделаем другой интерфейс, но эта функция пока ок.
    Возвращает publishAt в UTC (RFC3339) или None.
    """
    while True:
        ans = input("Планировать публикацию по времени? (y/n): ").strip().lower()
        if ans in ("y", "yes", "д", "да"):
            break
        if ans in ("n", "no", "н", "нет"):
            return None
        print("Введите y или n.")

    while True:
        mode = input(
            "Какое время? 1) ближайшие 03:00 МСК  2) указать дату/время МСК (YYYY-MM-DD HH:MM): "
        ).strip()

        if mode == "1":
            publish_at = next_publish_time_msk(3, 0)
            print("Ок, поставлю publishAt (UTC):", publish_at)
            return publish_at

        if mode == "2":
            raw = input("Введи дату/время по МСК (пример: 2026-01-10 03:00): ").strip()
            try:
                dt_local = datetime.strptime(raw, "%Y-%m-%d %H:%M").replace(tzinfo=MSK)

                # небольшой запас: не ставить публикацию на "прямо сейчас"
                if dt_local <= datetime.now(MSK) + timedelta(minutes=5):
                    print("Время слишком близко/в прошлом. Укажи будущее время (минимум +5 минут).")
                    continue

                publish_at = to_rfc3339_utc(dt_local.astimezone(timezone.utc))
                print("Ок, поставлю publishAt (UTC):", publish_at)
                return publish_at

            except ValueError:
                print("Неверный формат. Нужно YYYY-MM-DD HH:MM (например 2026-01-10 03:00).")
                continue

        print("Выбери 1 или 2.")

