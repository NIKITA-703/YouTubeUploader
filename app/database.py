import sqlite3
from datetime import datetime
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
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

    cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                display_name TEXT,
                password_hash TEXT,
                email TEXT,
                instagram TEXT,
                telegram TEXT,
                has_beatstars INTEGER DEFAULT 0  -- 1 если нужно поле Beatstars, 0 если нет
            )
        ''')

    cursor.execute('''
            CREATE TABLE IF NOT EXISTS known_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                added_by TEXT
            )
        ''')

    # cursor.execute('SELECT COUNT(*) FROM known_entities')
    # if cursor.fetchone()[0] == 0:
    #     from app.config import KNOWN_ARTISTS  # Берем список из конфига в последний раз
    #     for artist in KNOWN_ARTISTS:
    #         cursor.execute('INSERT OR IGNORE INTO known_entities (name, added_by) VALUES (?, ?)',
    #                        (artist.lower(), "system"))
    #     conn.commit()
    #     print("--- DATABASE SEEDED WITH INITIAL ARTISTS ---")

    conn.commit()
    conn.close()
    print("--- DATABASE INITIALIZED ---")


def add_new_entities_from_title(title: str, username: str):
    """
    Разбирает заголовок и сохраняет новых артистов/альбомы в базу.
    Пример: [FREE] Travis Scott x Metro Boomin TYPE BEAT...
    Результат: ['travis scott', 'metro boomin']
    """
    import re
    title_upper = title.upper()

    # 1. Находим часть между [FREE] (или началом) и TYPE BEAT
    # Регулярка ищет текст после [FREE] до TYPE BEAT
    match = re.search(r'(?:\[FREE\]\s+)?(.*?)\s+TYPE BEAT', title_upper, re.IGNORECASE)

    if match:
        raw_names = match.group(1)  # Например: "Travis Scott x Metro Boomin"
        # Разделяем по ' x ', ' X ', ' , ', ' & '
        names = re.split(r'\s+x\s+|\s+&\s+|,', raw_names, flags=re.IGNORECASE)

        conn = sqlite3.connect(str(DB_PATH))
        for name in names:
            clean_name = name.strip().lower()
            if len(clean_name) > 1:
                # Вставляем, если такого еще нет (благодаря UNIQUE)
                print(f"Add new ARTIST/ALBUM/TYPE")
                conn.execute('INSERT OR IGNORE INTO known_entities (name, added_by) VALUES (?, ?)',
                             (clean_name, username))
        conn.commit()
        conn.close()


def get_all_entities():
    """Собирает список артистов из кода (config.py) и из Базы Данных"""
    from app.config import KNOWN_ARTISTS  # Твои базовые артисты

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM known_entities')
    db_entities = [row[0] for row in cursor.fetchall()]
    conn.close()

    # Объединяем и убираем дубликаты
    return list(set(KNOWN_ARTISTS + db_entities))


def get_user(username: str):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None


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


def get_ai_knowledge_base():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Берем топ-15, чтобы ИИ мог найти совпадения по конкретным артистам
    cursor.execute('''
        SELECT title, seo_tags, views 
        FROM videos 
        WHERE views > 2 
        ORDER BY views DESC LIMIT 15
    ''')
    best_performers = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return best_performers