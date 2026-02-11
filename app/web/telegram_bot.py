import os
import asyncio
from aiogram import Bot, types
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Загружаем окружение (нужно для теста)
load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Инициализируем бота с поддержкой HTML по умолчанию
bot = Bot(token=TOKEN, parse_mode=types.ParseMode.HTML)


async def send_upload_report(nickname: str, publish_at_utc: str, video_url: str):
    """
    Отправляет отчет в Telegram.
    """
    try:
        # 1. Форматируем время в МСК
        if publish_at_utc:
            dt_utc = datetime.fromisoformat(publish_at_utc.replace('Z', '+00:00'))
            dt_msk = dt_utc + timedelta(hours=3)
            time_str = dt_msk.strftime("%d.%m %H:%M")
        else:
            dt_now_msk = datetime.now(timedelta(hours=3))
            time_str = dt_now_msk.strftime("%d.%m %H:%M") + " (Сразу)"

        # 2. Формируем КРАСИВЫЙ текст с HTML
        message_text = (
            f"🎬 <b>НОВОЕ ВИДЕО НА КАНАЛЕ</b>\n\n"
            f"👤 <b>Битмарь:</b> <code>{nickname}</code>\n"
            f"📅 <b>Дата публикации:</b> <code>{time_str}</code>\n\n"
            f"🔗 <b>Ссылка:</b> {video_url}\n\n"
            f"<i>С любовью: YouTube Uploader ❤️</i>"
        )

        # 3. Отправляем
        await bot.send_message(CHAT_ID,message_text, message_thread_id=11)
        print(f"--> [TELEGRAM] Отчет успешно отправлен.")

    except Exception as e:
        print(f"--> [TELEGRAM ERROR] Ошибка: {e}")

    finally:
        # Важно закрыть сессию, чтобы Python не ругался при завершении
        session = await bot.get_session()
        await session.close()


# --- ФУНКЦИЯ ДЛЯ ТЕСТА (БЕЗ ЗАГРУЗКИ ВИДЕО) ---
if __name__ == "__main__":
    print("--> Запуск теста Telegram бота...")
    test_nick = "(Test)"
    test_date = "2026-02-12T18:00:00Z"
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    asyncio.run(send_upload_report(test_nick, test_date, test_url))
    print("--> Тест завершен.")