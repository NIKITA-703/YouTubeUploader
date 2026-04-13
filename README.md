# YouTubeUploader

Веб-приложение для YouTube pipeline под type beat workflow:
- генерация тегов через Gemini,
- генерация/выбор превью,
- upload видео на YouTube,
- автодобавление в плейлисты,
- сборка монтажных видео из аудио + YouTube source clips,
- отложенная генерация и автозагрузка shorts,
- Telegram-отчёты и напоминания битмарям,
- сохранение статистики и логов в SQLite.

## Что умеет проект
- `Upload`:
  - генерирует метаданные,
  - позволяет выбрать превью из галереи или загрузить своё,
  - загружает видео на YouTube,
  - ставит расписание публикации,
  - отправляет Telegram-отчёт,
  - сохраняет данные о видео в БД.
- `Create Video`:
  - принимает бит (`.mp3`) и 1-4 YouTube URL,
  - скачивает source video,
  - режет клипы по аудиособытиям,
  - собирает main montage по шаблону,
  - умеет отдельно собирать shorts.
- `Delayed Shorts Pipeline`:
  - после успешного upload main video ждёт заданную задержку,
  - собирает shorts отдельно от main video,
  - планирует shorts на следующий день относительно даты публикации main video,
  - переиспользует превью main video,
  - удаляет временные файлы после завершения pipeline.

## Стек
- Python 3.11+
- FastAPI + Jinja2 + Uvicorn
- SQLite
- Google YouTube Data API
- Gemini API
- aiogram
- ffmpeg / ffprobe
- yt-dlp
- librosa

## Основные пути проекта
- `app/web/server.py` — создание FastAPI-приложения, middleware, lifespan.
- `app/web/pages.py` — страницы `/`, `/create-video`, `/admin/logs`.
- `app/web/api.py` — web API: fill/upload/preview/montage/logs/calendar.
- `app/pipeline.py` — основной YouTube upload flow.
- `app/montage/service.py` — логика скачивания source clips, анализа аудио, main montage и shorts.
- `app/montage/models.py` — модели монтажа.
- `app/montage/title_parser.py` — разбор title для интро/shorts.
- `app/web/telegram_bot.py` — Telegram-напоминания и callback-кнопки.
- `app/web/templates/` — HTML-шаблоны.
- `app/web/static/` — JS/CSS.
- `tools/create_users.py` — сидирование пользователей.
- `tools/cleanup_media.py` — очистка старых медиа.
- `tools/sync_stats.py` — синхронизация YouTube-статистики.
- `data/json/` — OAuth-файлы (`client_secret*.json`, `token.json`).
- `data/montage/` — монтажные ассеты (`Frame.mp4`, `Sub.mp4`, `ShortsFrame.mp4`, voice tags, fonts).
- `db/` — SQLite база проекта.

## База данных
Используется `db/youtube_stats.db` (SQLite).

Основные таблицы:
- `users`
- `videos`
- `known_entities`
- `operation_logs`
- `user_daily_uploads`
- `reminder_manual_stops`

Инициализация вызывается автоматически на старте (`init_db()`).

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

3. Для montage/shorts установи системные зависимости:

Windows:
- установить `ffmpeg` и добавить в `PATH`
- убедиться, что доступны `ffmpeg -version` и `ffprobe -version`

Ubuntu:

```bash
sudo apt update
sudo apt install -y ffmpeg
```

4. Для `yt-dlp` на YouTube иногда нужен JS runtime:

```bash
sudo apt install -y nodejs npm
```

## Запуск веб-приложения

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.web.server:app --host 0.0.0.0 --port 8000 --reload
```

Открой:
- `http://127.0.0.1:8000/login`

## Запуск только Telegram-бота

```powershell
.\.venv\Scripts\python.exe -u -m app.web.telegram_bot
```

Обычно отдельный запуск не нужен: бот поднимается вместе с FastAPI.

## Основные режимы

### Upload
- пользователь загружает готовое видео,
- либо использует уже собранный main montage,
- выбирает превью,
- отправляет видео на YouTube.

### Create Video
- доступен по `/create-video`,
- можно отключить через `CREATE_VIDEO_ENABLED=0`,
- принимает:
  - аудио-файл,
  - title,
  - 1-4 YouTube ссылки.

### Main + Delayed Shorts
Нормальный боевой сценарий:
- `CREATE VIDEO` собирает только main video,
- пользователь нажимает `UPLOAD`,
- после успешного upload и задержки запускается shorts pipeline,
- shorts ставятся в расписание на следующий день от даты main video.

Для этого нужен режим:

```env
MONTAGE_BUILD_MODE=video
SHORTS_AFTER_MAIN_UPLOAD_ENABLED=1
```

## Монтаж: как это работает

### Main video
- берётся бит,
- скачиваются YouTube source clips,
- по аудио ищутся bass/beat events,
- на их основе режутся shot segments,
- собирается итоговый montage,
- применяются:
  - `Frame.mp4`,
  - `Sub.mp4`,
  - voice tag,
  - intro text.

### Shorts
- shorts не режутся из готового main video,
- они собираются отдельно из тех же source clips,
- у shorts отдельный пайплайн,
- по умолчанию:
  - без `Sub.mp4`,
  - без voice tag,
  - с отдельным `ShortsFrame.mp4`, если он есть.

### Preview логика
- если пользователь выбрал превью в UI, именно оно уходит в main upload,
- автопоиск превью включается только если пользователь ничего не выбрал,
- shorts используют превью main video, сохранённое после успешного upload.

## Переменные окружения

### Обязательные
- `GEMINI_API_KEY` — один или несколько ключей через запятую.
- `SESSION_SECRET`
- `DEV_MODE`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_REMINDER_ENABLED`
- `TELEGRAM_SITE_CREDENTIALS_JSON`
- `YOUTUBE_CLIENT_SECRET`
- `PREVIEW_DIR`
- `WEB_TMP_DIR`
- `STATIC_DIR`

### YouTube / OAuth
- `YOUTUBE_CLIENT_SECRET` — путь к `client_secret*.json`.

Рекомендуемая структура:
- Windows: `data\json\client_secret.apps.googleusercontent.com.json`
- Linux: `/var/www/YouTubeUploader/data/json/client_secret.apps.googleusercontent.com.json`

### Proxy
- `GEMINI_PROXY` — прокси только для Gemini-запросов.
- `YTDLP_PROXY` — прокси только для `yt-dlp`.

`YTDLP_PROXY` не используется для YouTube upload/auth. Это сделано специально, чтобы не ломать OAuth/upload.

### Create Video / Montage
- `CREATE_VIDEO_ENABLED=1` — показывать вкладку `Create Video`.
- `MONTAGE_ASSETS_DIR` — папка с монтажными ассетами.
- `MONTAGE_SHORTS_DIR` — папка для готовых shorts.
- `MONTAGE_FONT_FILE` — явный путь к шрифту.
- `MONTAGE_QUALITY` — профиль качества монтажа.
- `MONTAGE_BUILD_MODE` — `video`, `shorts`, `all`.
- `MONTAGE_SEGMENT_TIMEOUT_SECONDS` — timeout на рендер одного shot segment.
- `MONTAGE_COOKIES_FROM_BROWSER` — cookies source для `yt-dlp`.
- `MONTAGE_COOKIES_FILE` — путь к cookies-файлу для `yt-dlp`.
- `MONTAGE_JS_RUNTIME` — JS runtime для `yt-dlp`, например `node`.

### Delayed Shorts
- `SHORTS_AFTER_MAIN_UPLOAD_ENABLED=1`
- `SHORTS_POST_UPLOAD_DELAY_SECONDS=300`
- `SHORTS_SCHEDULE_TIMES=12:00,15:00,18:00,22:00`

Важно:
- shorts планируются не "на завтра от текущего дня",
- а на следующий день от даты публикации main video.

Если main video запланирован на `2026-04-05`, shorts уйдут на `2026-04-06`.

### Cleanup
- `CLEANUP_OLDER_THAN_HOURS`
- `CLEANUP_DRY_RUN`
- `MAX_PREVIEW_FILES`

## Профили качества монтажа

`MONTAGE_QUALITY` поддерживает:
- `high`
- `medium`
- `low`
- `normal` как alias для `medium`

Что меняется:
- формат скачивания source video,
- resolution/fps для shorts,
- preset/crf для segment/final encode,
- аудио bitrate.

Рекомендуемо:
- локально на сильной машине: `high`
- VPS с ограниченными ресурсами: `medium` или `low`

## Пример `.env` для локальной разработки

```env
GEMINI_API_KEY=key1,key2
SESSION_SECRET=super_secret
DEV_MODE=True
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=-100xxxxxxxxxx
TELEGRAM_REMINDER_ENABLED=False
TELEGRAM_SITE_CREDENTIALS_JSON={"user":{"login":"...","password":"..."}}
YOUTUBE_CLIENT_SECRET=D:\YouTubeUploader\data\json\client_secret.apps.googleusercontent.com.json
PREVIEW_DIR=D:\YouTubeUploader\photo
WEB_TMP_DIR=D:\YouTubeUploader\web_tmp
STATIC_DIR=D:\YouTubeUploader\app\web\static
MONTAGE_ASSETS_DIR=D:\YouTubeUploader\data\montage
MONTAGE_SHORTS_DIR=D:\YouTubeUploader\web_tmp\shorts
MONTAGE_FONT_FILE=D:\YouTubeUploader\data\montage\fonts\SITKAVF.TTF
MONTAGE_QUALITY=high
MONTAGE_BUILD_MODE=video
SHORTS_AFTER_MAIN_UPLOAD_ENABLED=1
SHORTS_POST_UPLOAD_DELAY_SECONDS=180
SHORTS_SCHEDULE_TIMES=12:00,15:00,18:00,22:00
YTDLP_PROXY=http://user:pass@host:port
```

## Пример `.env` для VPS

```env
DEV_MODE=False
TELEGRAM_REMINDER_ENABLED=True
YOUTUBE_CLIENT_SECRET=/var/www/YouTubeUploader/data/json/client_secret.apps.googleusercontent.com.json
PREVIEW_DIR=/var/www/YouTubeUploader/photo
WEB_TMP_DIR=/var/www/YouTubeUploader/web_tmp
STATIC_DIR=/var/www/YouTubeUploader/app/web/static
MONTAGE_ASSETS_DIR=/var/www/YouTubeUploader/data/montage
MONTAGE_SHORTS_DIR=/var/www/YouTubeUploader/web_tmp/shorts
MONTAGE_FONT_FILE=/var/www/YouTubeUploader/data/montage/fonts/SITKAVF.TTF
MONTAGE_QUALITY=medium
MONTAGE_BUILD_MODE=video
SHORTS_AFTER_MAIN_UPLOAD_ENABLED=1
SHORTS_POST_UPLOAD_DELAY_SECONDS=300
SHORTS_SCHEDULE_TIMES=12:00,15:00,18:00,22:00
```

## Telegram reminders
Актуальная логика в `app/web/telegram_bot.py`:
- время считается по МСК,
- напоминания битмарю идут в ЛС,
- если за день уже есть upload, напоминания не отправляются,
- до дедлайна есть преднапоминание,
- после дедлайна напоминания идут каждые 30 минут,
- у Kellmi есть callback на ручную остановку напоминаний на текущий день,
- отчёт о факте upload отправляется в общий чат.

Актуальная карта `WEEKDAY_DUTY`:
- Понедельник — Kellmi
- Вторник — whallythekidd
- Среда — plak1!
- Четверг — LVBUBA
- Пятница — spacech1ld
- Суббота — sunly
- Воскресенье — nootropics

## Полезные утилиты

Сидирование пользователей:

```powershell
.\.venv\Scripts\python.exe tools/create_users.py
```

Очистка медиа:

```powershell
.\.venv\Scripts\python.exe tools/cleanup_media.py
```

Синхронизация статистики:

```powershell
.\.venv\Scripts\python.exe tools/sync_stats.py
```

## Логи и диагностика

Логи сервиса на VPS:

```bash
journalctl -u uploader -f -o cat
```

Полезные маркеры:
- `--> [TELEGRAM] Reminder service started`
- `--> [UPLOAD PREVIEW] ...`
- `--> [YTDLP] Using YTDLP_PROXY for YouTube downloads`
- `--> [MONTAGE ASSETS] Using asset dir: ...`
- `--> [SHORTS] waiting ...`

## Troubleshooting

### `ffmpeg and ffprobe must be available in PATH`
- установить `ffmpeg`,
- проверить `ffmpeg -version` и `ffprobe -version`.

### `Sign in to confirm you’re not a bot` от `yt-dlp`
- использовать `YTDLP_PROXY`,
- при необходимости добавить cookies:
  - `MONTAGE_COOKIES_FROM_BROWSER`
  - или `MONTAGE_COOKIES_FILE`,
- при необходимости поставить `nodejs`.

### `NetworkError when attempting to fetch resource` / `504`
- чаще всего это не баг логики, а слабый VPS под `ffmpeg`,
- main montage сам по себе тяжёлый,
- использовать `MONTAGE_QUALITY=medium` или `low`,
- увеличить ресурсы сервера.

### Рекомендуемые ресурсы для VPS
Минимально рабочая конфигурация для main montage:
- `2 vCPU`
- `4 GB RAM`
- `20-30 GB SSD`

Комфортнее:
- `4 vCPU`
- `4-8 GB RAM`
- `30+ GB SSD`

### `Terminated by other getupdates request`
- запущено несколько экземпляров Telegram-бота,
- оставь только один.

### `Selected preview file not found on server`
- пользователь выбрал превью из галереи,
- но файла уже нет в `PREVIEW_DIR`,
- нужно выбрать превью заново.

## Безопасность
В проекте есть чувствительные данные:
- токены,
- client secrets,
- Telegram credentials,
- пароли.

Рекомендуется:
- хранить секреты только в `.env`,
- не коммитить `token.json`, `client_secret*.json`, пароли и cookies,
- использовать отдельные production secrets,
- не хранить тяжёлые монтажные ассеты в git без необходимости.
