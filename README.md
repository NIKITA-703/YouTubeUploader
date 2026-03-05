# YouTubeUploader

Веб-приложение для загрузки YouTube-видео (type beat pipeline) с:
- генерацией тегов (Gemini),
- генерацией/выбором превью,
- автодобавлением в плейлисты,
- сохранением статистики в SQLite,
- Telegram-уведомлениями (отчет о загрузке + напоминания битмарям).

## Стек
- Python 3.11+
- FastAPI + Jinja2 + Uvicorn
- SQLite
- Google YouTube Data API
- Gemini API
- aiogram (Telegram)

## Структура проекта
- `app/web/server.py` — создание FastAPI-приложения, middleware, lifespan.
- `app/web/api.py` — API: fill/upload/preview/tags.
- `app/web/telegram_bot.py` — Telegram-логика напоминаний и callback-кнопок.
- `app/pipeline.py` — основной upload flow.
- `app/content/description.py` — шаблон описания YouTube.
- `app/database.py` — инициализация/работа с БД.
- `app/web/templates/` — HTML-шаблоны.
- `app/web/static/` — фронтенд JS/CSS.
- `tools/create_users.py` — сидирование пользователей в БД.
- `tools/cleanup_media.py` — очистка временных медиа-файлов.
- `tools/sync_stats.py` — синхронизация YouTube-статистики.
- `data/` — OAuth JSON-файлы (`client_secret*.json`, `token*.json`).
- `db/` — SQLite база проекта.

## База данных
Используется `db/youtube_stats.db` (SQLite), основные таблицы:
- `users`
- `videos`
- `known_entities`
- `operation_logs`
- `user_daily_uploads`
- `reminder_manual_stops`

Инициализация таблиц вызывается автоматически на старте сервера (`init_db()`).

## Подготовка окружения
1. Создай venv:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Установи зависимости:

```powershell
pip install -r requiments.txt
```

## Переменные окружения (`.env`)
Минимально важные:
- `GEMINI_API_KEY` — можно несколько через запятую.
- `SESSION_SECRET`
- `DEVMODE` — `True/False` (локальная разработка vs VPS/prod).
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID` — общий чат/тред для отчета о выложенном видео.
- `TELEGRAM_CHAT_THREAD_ID` — id топика (если нужен).
- `TELEGRAM_REMINDER_ENABLED` — включать ли reminder-сервис Telegram при старте FastAPI (`True/False`).
- `TELEGRAM_SITE_CREDENTIALS_JSON` — JSON с логинами/паролями для текста напоминаний битмарям.
- `YOUTUBE_CLIENT_SECRET` — путь к OAuth client secret json.
- `PREVIEW_DIR`
- `WEB_TMP_DIR`

Пример (адаптируй под себя):

```env
GEMINI_API_KEY=key1,key2
SESSION_SECRET=super_secret
DEVMODE=True
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=-100xxxxxxxxxx
TELEGRAM_CHAT_THREAD_ID=11
TELEGRAM_REMINDER_ENABLED=False
TELEGRAM_SITE_CREDENTIALS_JSON={"user":{"login":"...","password":"..."}}
YOUTUBE_CLIENT_SECRET=D:\path\client_secret.json
PREVIEW_DIR=D:\YouTubeUploader\photo
WEB_TMP_DIR=D:\YouTubeUploader\web_tmp
STATIC_DIR=D:\YouTubeUploader\app\web\static
```

## Запуск веб-приложения
Из корня проекта:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.web.server:app --host 0.0.0.0 --port 8000 --reload
```

Открой:
- `http://127.0.0.1:8000/login`

## Запуск только Telegram-бота напоминаний

```powershell
.\.venv\Scripts\python.exe -u -m app.web.telegram_bot
```

> В обычном режиме бот и так поднимается автоматически вместе с FastAPI (`lifespan` в `app/web/server.py`).
> Рекомендуемо:
> - локально: `DEVMODE=True`, `TELEGRAM_REMINDER_ENABLED=False`
> - VPS/production: `DEVMODE=False`, `TELEGRAM_REMINDER_ENABLED=True`

## VPS: чувствительные и режимные значения
Перед запуском на VPS проверь минимум:
- `DEVMODE=False`
- `TELEGRAM_REMINDER_ENABLED=True`
- `SESSION_SECRET` — уникальный длинный секрет
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_SITE_CREDENTIALS_JSON`
- `GEMINI_API_KEY`
- `YOUTUBE_CLIENT_SECRET` (Linux path)
- `CLEANUP_DRY_RUN=0` (для реальной очистки; `1` только для теста)

Примечание:
- `https_only` для сессионной cookie в `server.py` включается автоматически, когда `DEVMODE=False`.
- `OAUTHLIB_INSECURE_TRANSPORT` в `app/youtube/auth.py` включается только в `DEVMODE=True`.

## Тестовый режим Telegram-бота
Быстрый тест отправки через 10 секунд:

```powershell
$env:TELEGRAM_TEST_MODE="1"
.\.venv\Scripts\python.exe -u -m app.web.telegram_bot
```

Вернуть обычный режим:

```powershell
Remove-Item Env:TELEGRAM_TEST_MODE
```

## Логика напоминаний (Telegram)
Актуальная логика в `app/web/telegram_bot.py`:
- Время считается по МСК.
- Напоминания битмарю идут в ЛС по `chat_id` из `WEEKDAY_DUTY`.
- Если за текущий день уже есть upload в БД (`user_daily_uploads`) — напоминания не отправляются.
- Для старых записей есть fallback-проверка по `videos`.
- Преддедлайн: одно напоминание в `20:30`.
- После дедлайна (`21:00`) — каждые 30 минут до `00:00`.
- Кнопка у битмаря: `✅ Принял, увидел`.
- У Kellmi: `❌ прекратить напоминать` (останавливает напоминания на текущий день для выбранного битмаря, флаг хранится в БД).
- Отчет о факте загрузки видео (`send_upload_report`) идет в общий чат/тред.

Дополнительно:
- При `/start` бот пишет в серверный лог `username`, `name`, `id` (удобно для сбора `tg_user_id`).
- Проверка загрузки на день идет по:
  - `user_daily_uploads` (основной источник),
  - `videos` как fallback для legacy-записей.
- Для scheduled-видео день фиксируется по дате публикации (МСК), а не по времени нажатия Upload в вебке.

## Telegram: расписание напоминаний
Актуальная карта хранится в `WEEKDAY_DUTY` в `app/web/telegram_bot.py`:
- Понедельник — Kellmi
- Вторник — whallythekidd
- Среда — plak1!
- Четверг — LVBUBA
- Пятница — spacech1ld
- Суббота — sunly
- Воскресенье — nootropics

## Telegram: проверка работы
- Логи сервиса:

```bash
journalctl -u uploader -f -o cat
```

- Полезные маркеры в логах:
  - `--> [TELEGRAM] Reminder service started`
  - `--> [TELEGRAM REMINDER CHECK] ...`
  - `--> [TELEGRAM REMINDER SENT] ...`
  - `--> [TELEGRAM REMINDER SKIP] ...`
  - `--> [TELEGRAM START] username=@... id=...`

## Валидации в UI/API
- `BPM`: только цифры, диапазон `0..250`.
- `KEY`: выбор из dropdown.
- В описании YouTube символ `#` в KEY заменяется на `sharp`.

## Полезные утилиты
- Сидирование пользователей:

```powershell
.\.venv\Scripts\python.exe tools/create_users.py
```

- Очистка медиа:

```powershell
.\.venv\Scripts\python.exe tools/cleanup_media.py
```

- Синхронизация статистики:

```powershell
.\.venv\Scripts\python.exe tools/sync_stats.py
```

## Troubleshooting
- `Terminated by other getupdates request`:
  - Запущено несколько экземпляров бота одновременно. Оставь только один.

- `BPM: ???` в описании:
  - Проверь, что BPM введён числом и проходит валидацию (`0..250`).

- Telegram не пишет в ЛС:
  - У пользователя должен быть корректный `chat_id`/`tg_user_id` в `WEEKDAY_DUTY`.
  - Пользователь должен хотя бы раз написать боту `/start`.

## Безопасность
В проекте есть чувствительные данные (токены, client secrets, пароли). Рекомендуется:
- использовать `.env` и секрет-хранилище,
