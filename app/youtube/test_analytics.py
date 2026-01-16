import os
import json
from googleapiclient.discovery import build
# Импортируй свою функцию. ВАЖНО: убедись, что она возвращает (service, credentials)
from app.youtube import authenticate_youtube


def test_stats():
    client_secret_path = os.getenv(
        "YOUTUBE_CLIENT_SECRET",
        r"D:\PyCharm\YouTubeUploader\client_secret.apps.googleusercontent.com.json"
    )

    # 1. Авторизуемся.
    # Если ты поправил функцию, она вернет два объекта:
    youtube_service, credentials = authenticate_youtube(client_secret_path)

    # 2. Строим сервис аналитики, используя полученные credentials
    try:
        analytics = build('youtubeAnalytics', 'v2', credentials=credentials)

        # 3. Просим статистику за последние 30 дней
        # ВАЖНО: даты должны быть строками YYYY-MM-DD
        result = analytics.reports().query(
            ids='channel==MINE',
            startDate='2026-01-01',
            endDate='2026-01-15',
            metrics='views,likes,comments,estimatedMinutesWatched',
            dimensions='day'
        ).execute()

        print("Связь установлена! Полученные данные:")
        print(json.dumps(result, indent=2))  # Красивый вывод JSON

    except Exception as e:
        print(f"Ошибка при работе с Analytics API: {e}")


if __name__ == "__main__":
    test_stats()