from __future__ import annotations


# ОДИН УНИВЕРСАЛЬНЫЙ ШАБЛОН
UNIVERSAL_TEMPLATE = """🎧 Buy this beat / Contact me
👉 {purchase_link}

FREE for non profit use
License required for monetization and official releases

🎼 BPM: {bpm}
🎹 Key: {key}

––––––––––––––––––

📩 Contact:

✉️ Mail: {mail}
📸 Instagram: {insta}
💬 Telegram: {tg}

✅ DMs are open

––––––––––––––––––

❗️ IMPORTANT
• Any use of this beat requires a valid license
• Producer credit is required
• Prod. by {display_name}

––––––––––––––––––
{tags}
"""


def build_description(tags: list[str], purchase_link: str, bpm: str, key: str, user: dict) -> str:
    # Определяем ссылку: если Beatstars нет, пишем username.music
    final_link = purchase_link if user.get('has_beatstars') else f"{user.get('display_name')}"

    return UNIVERSAL_TEMPLATE.format(
        purchase_link=final_link,
        bpm=bpm or "",
        key=key or "",
        mail=user.get('email', ''),
        insta=user.get('instagram', ''),
        tg=user.get('telegram', ''),
        display_name=user.get('display_name') or "",
        tags=" ".join(tags)
    )