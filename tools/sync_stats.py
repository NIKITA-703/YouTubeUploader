import os
import sqlite3
from app.youtube.auth import authenticate_youtube
from googleapiclient.discovery import build
from app.database import update_video_stats, DB_PATH


def sync():
    # 1. Авторизация

    client_secret_path = os.getenv(
        "YOUTUBE_CLIENT_SECRET",
        r"client_secret.apps.googleusercontent.com.json",
    )

    if not os.path.exists(client_secret_path):
        print(f"!!! ОШИБКА: Файл секретов не найден по пути: {client_secret_path}")
        return

        # 2. Авторизация (получаем credentials для аналитики)
    try:
        # Важно: authenticate_youtube теперь возвращает (service, credentials)
        _, credentials = authenticate_youtube(client_secret_path)
        analytics = build('youtubeAnalytics', 'v2', credentials=credentials)
    except Exception as e:
        print(f"!!! ОШИБКА АВТОРИЗАЦИИ: {e}")
        return

        # 3. Получаем список ID видео из нашей SQLite
    try:
        # SQLite в Windows требует строку, а не объект Path
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute('SELECT video_id, title FROM videos')
        video_data = cursor.fetchall()  # Список кортежей [(id, title), ...]
        conn.close()
    except Exception as e:
        print(f"!!! ОШИБКА ЧТЕНИЯ БД: {e}")
        return

    if not video_data:
        print("--- База данных пуста. Нечего синхронизировать.")
        return

    print(f"--- Найдено видео в базе: {len(video_data)}")

    # 4. Для каждого видео запрашиваем статистику
    for vid, title in video_data:
        try:
            # Запрашиваем данные за всё время работы (от сентября 2025 до конца 2026)
            res = analytics.reports().query(
                ids='channel==MINE',
                startDate='2025-09-01',
                endDate='2026-12-31',
                metrics='views,likes',
                filters=f'video=={vid}'
            ).execute()

            # Если YouTube вернул данные (строки)
            if 'rows' in res and res['rows']:
                views = int(res['rows'][0][0])
                likes = int(res['rows'][0][1])

                # Обновляем SQLite
                update_video_stats(vid, views, likes)
                print(f"[OK] {vid} ('{title[:20]}...'): {views} views, {likes} likes.")
            else:
                print(f"[SKIP] {vid}: Данных в YouTube Analytics пока нет (обработка занимает 2-3 дня).")

        except Exception as e:
            print(f"[ERROR] Не удалось обновить {vid}: {e}")

    print("--> [FINISH] Синхронизация завершена.")


if __name__ == "__main__":
    sync()