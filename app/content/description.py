from __future__ import annotations


def _normalize_key_for_youtube(key: str) -> str:
    k = (key or "").strip()
    if not k:
        return ""
    return k.replace("#", " sharp ")


def build_description(tags: list[str], purchase_link: str, bpm: str, key: str, user: dict) -> str:
    """
    Универсальный сборщик описания.
    Автоматически скрывает пустые поля и адаптирует ссылки под юзера.
    """

    # 1. Логика главной ссылки:
    # Если есть Beatstars — берем ссылку из формы.
    # Если нет берем Instagram. Если нет инсты берем username.
    if user.get('has_beatstars'):
        final_link = purchase_link
    else:
        final_link = user.get('instagram') or user.get('username') or ""

    # 2. Динамическая сборка блока контактов
    contact_parts = []

    # Проверяем Email
    email = user.get('email')
    if email and email.upper() != "NONE":
        contact_parts.append(f"✉️ Mail: {email}")

    # Проверяем Instagram
    insta = user.get('instagram')
    if insta and insta.upper() != "NONE":
        contact_parts.append(f"📸 Instagram: {insta}")

    # Проверяем Telegram
    tg = user.get('telegram')
    if tg and tg.upper() != "NONE":
        contact_parts.append(f"💬 Telegram: {tg}")

    # Склеиваем контакты через перенос строки
    contact_block = "\n".join(contact_parts)

    key_for_description = _normalize_key_for_youtube(key)

    # 3. Финальный шаблон
    # Мы используем f-строку для гибкости
    description = f"""🎧 Buy this beat / Contact me
👉 {final_link}

FREE for non profit use
License required for monetization and official releases

🎼 BPM: {bpm or '???'}
🎹 Key: {key_for_description or '???'}

––––––––––––––––––

📩 Contact:

{contact_block}

✅ DMs are open

––––––––––––––––––

❗️ IMPORTANT
• Any use of this beat requires a valid license
• Producer credit is required
• Prod. by {user.get('display_name') or ""}

––––––––––––––––––
{" ".join(tags)}
"""

    return description.strip()
