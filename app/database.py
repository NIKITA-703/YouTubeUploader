import sqlite3
from datetime import datetime, date, timezone, timedelta
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

    cursor.execute('''
            CREATE TABLE IF NOT EXISTS operation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at DATETIME,
                level TEXT,
                event TEXT,
                username TEXT,
                status TEXT,
                details TEXT
            )
        ''')

    cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_daily_uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day_msk TEXT NOT NULL,
                username TEXT NOT NULL,
                video_id TEXT,
                created_at DATETIME,
                UNIQUE(day_msk, username)
            )
        ''')

    cursor.execute('''
            CREATE TABLE IF NOT EXISTS reminder_manual_stops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day_msk TEXT NOT NULL,
                username TEXT NOT NULL,
                stopped_by_user_id TEXT,
                created_at DATETIME,
                UNIQUE(day_msk, username)
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
    ''', (
        video_id,
        title,
        ",".join(hashtags),
        ",".join(seo_tags),
        datetime.now(),
        datetime.now(),
    ))
    conn.commit()
    conn.close()


def has_any_upload_on_day(day_msk: date) -> bool:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        '''
        SELECT 1
        FROM videos
        WHERE date(upload_date) = ?
        LIMIT 1
        ''',
        (day_msk.isoformat(),),
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None


def mark_user_upload_on_day(username: str, video_id: str | None = None, day_msk: date | None = None):
    if not username:
        return
    if day_msk is None:
        msk = timezone(timedelta(hours=3))
        day_msk = datetime.now(timezone.utc).astimezone(msk).date()

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT INTO user_daily_uploads (day_msk, username, video_id, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(day_msk, username) DO UPDATE SET
            video_id = excluded.video_id,
            created_at = excluded.created_at
        ''',
        (day_msk.isoformat(), username, video_id, datetime.now()),
    )
    conn.commit()
    conn.close()


def has_user_upload_on_day(username: str, day_msk: date) -> bool:
    if not username:
        return False
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        '''
        SELECT 1
        FROM user_daily_uploads
        WHERE day_msk = ? AND username = ?
        LIMIT 1
        ''',
        (day_msk.isoformat(), username),
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None


def has_legacy_video_upload_on_day(producer_username: str, day_msk: date) -> bool:
    """
    Fallback for old records before user_daily_uploads existed.
    Uses title pattern: (prod. <username> ...)
    """
    if not producer_username:
        return False
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        '''
        SELECT 1
        FROM videos
        WHERE date(upload_date) = ?
          AND lower(title) LIKE ?
        LIMIT 1
        ''',
        (day_msk.isoformat(), f"%prod. {producer_username.lower()}%"),
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None


def mark_manual_stop_on_day(day_msk: date, username: str, stopped_by_user_id: str | None = None):
    if not username:
        return
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT INTO reminder_manual_stops (day_msk, username, stopped_by_user_id, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(day_msk, username) DO UPDATE SET
            stopped_by_user_id = excluded.stopped_by_user_id,
            created_at = excluded.created_at
        ''',
        (day_msk.isoformat(), username, stopped_by_user_id, datetime.now()),
    )
    conn.commit()
    conn.close()


def is_manual_stop_on_day(day_msk: date, username: str) -> bool:
    if not username:
        return False
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        '''
        SELECT 1
        FROM reminder_manual_stops
        WHERE day_msk = ? AND username = ?
        LIMIT 1
        ''',
        (day_msk.isoformat(), username),
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None


def get_last_upload_at_on_day(day_msk: date):
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        '''
        SELECT upload_date
        FROM videos
        WHERE date(upload_date) = ?
        ORDER BY upload_date DESC
        LIMIT 1
        ''',
        (day_msk.isoformat(),),
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


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


def add_operation_log(
    event: str,
    level: str = "INFO",
    username: str | None = None,
    status: str | None = None,
    details: str | None = None,
):
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT INTO operation_logs (created_at, level, event, username, status, details)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        (datetime.now(), level, event, username, status, details),
    )
    conn.commit()
    conn.close()


def get_recent_operation_logs(limit: int = 50):
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        '''
        SELECT created_at, level, event, username, status, details
        FROM operation_logs
        ORDER BY id DESC
        LIMIT ?
        ''',
        (limit,),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows
