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

    client_secret = "client_secret_path"
    _, credentials = authenticate_youtube(client_secret)
    analytics = build('youtubeAnalytics', 'v2', credentials=credentials)

    # 2. Получаем список ID видео из нашей базы
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT video_id FROM videos')
    video_ids = [row[0] for row in cursor.fetchall()]
    conn.close()

    # 3. Для каждого видео запрашиваем статистику
    for vid in video_ids:
        try:
            res = analytics.reports().query(
                ids='channel==MINE',
                startDate='2025-09-01', # Начало работы
                endDate='2026-12-31',
                metrics='views,likes',
                filters=f'video=={vid}'
            ).execute()

            if 'rows' in res:
                views = res['rows'][0][0]
                likes = res['rows'][0][1]
                update_video_stats(vid, views, likes)
                print(f"Обновлено видео {vid}: {views} просмотров.")
        except Exception as e:
            print(f"Ошибка синхронизации для {vid}: {e}")


if __name__ == "__main__":
    sync()