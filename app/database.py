import sqlite3
from datetime import datetime
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "youtube_stats.db"


def init_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cursor = conn.cursor()
    cursor.execute('''
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                title TEXT,
                hashtags TEXT,
                seo_tags TEXT,
                upload_date DATETIME,
                views INTEGER DEFAULT 0,
                likes INTEGER DEFAULT 0,
                last_updated DATETIME
            )
        ''')
    conn.commit()
    conn.close()
    print("--- DATABASE INITIALIZED ---")


def add_video_to_db(video_id, title, hashtags, seo_tags):
    # Используем str(DB_PATH) и добавляем timeout
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO videos (video_id, title, hashtags, seo_tags, upload_date, last_updated)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (video_id, title, ",".join(hashtags), ",".join(seo_tags),
          datetime.now(), datetime.now()))
    conn.commit()
    conn.close()


def update_video_stats(video_id, views, likes):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE videos 
        SET views = ?, likes = ?, last_updated = ?
        WHERE video_id = ?
    ''', (views, likes, datetime.now(), video_id))
    conn.commit()
    conn.close()


# Функция для получения ТОП-тегов (для обучения ИИ)
def get_best_tags(limit=20):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Выбираем теги из видео, набравших больше всего просмотров
    cursor.execute('SELECT seo_tags FROM videos ORDER BY views DESC LIMIT 10')
    rows = cursor.fetchall()
    conn.close()

    all_tags = []
    for row in rows:
        tags = row[0].split(',')
        all_tags.extend(tags)

    # Возвращаем уникальные теги (оставляем самые популярные)
    return list(set(all_tags))[:limit]