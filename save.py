from datetime import datetime, timezone, timedelta
import time
import json
import os

from pyasn1_modules.rfc2459 import ub_organization_name
from googleapiclient.http import MediaFileUpload
from Tools.scripts.stable_abi import itemclass
from googleapiclient.errors import HttpError
import google_auth_oauthlib.flow
import googleapiclient.discovery
from pyasn1.debug import Scope
from zoneinfo import ZoneInfo
import googleapiclient.errors

from template import DESCRIPTION_TEMPLATE, PLAYLISTS
from photo import download_thumbnail_for_beat
from tags_ai import generate_youtube_tags

scopes = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube"
]

GEMINI_API_KEY = ""

MSK = ZoneInfo("Europe/Moscow")


# TODO: Рефакторинг кода что норм, что нет Сделать
#  Вебку где мы будем выбирать видео которое мы будем загружать и вписывать название видео.
#  Рядом будут texbox где будут виден текст который сгенерировал Gemini TAGS и CEO TAGS рядом справа к примеру будет кнопка добавить превью
#  или оно сразу будет добавлятся и будет показана фотка которая будет добавлена. Ниже под тегами будет кнопка задать или нет время для выкладывания видео на ютуб.
#  И всё кнопка выложить Потом когда всё будет стабильно работать просто залить на хост, чтобы оно там работало.
#  Оно будет скачивать видео которое мы вставим вебке и скачивать превью. Когда зальётся на ютуб он удалит чтобы место не занимать


def set_preview(youtube, video_id: str, preview_path: str, retries: int = 10, sleep_s: int = 3):
    last_err = None

    for attempt in range(1, retries + 1):
        try:
            request = youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(preview_path)
            )
            request.execute()
            print(f"Preview uploaded ✅ ({preview_path})")
            return

        except HttpError as e:
            last_err = e
            # Часто бывает 400/403/404 пока видео обрабатывается — пробуем ещё
            print(f"Thumbnail set attempt {attempt}/{retries} failed: {e}")
            time.sleep(sleep_s)

        raise RuntimeError(f"Не удалось загрузить превью после {retries} попыток. Последняя ошибка: {last_err}")


def to_rfc3339_utc(dt_utc: datetime) -> str:
    """RFC3339 строка в UTC: 2026-01-08T00:00:00Z"""
    return dt_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def next_publish_time_msk(hour: int = 3, minute: int = 0) -> str:
    now_local = datetime.now(MSK)
    target_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target_local <= now_local:
        target_local += timedelta(days=1)

    target_utc = target_local.astimezone(timezone.utc)
    return to_rfc3339_utc(target_utc)


def ask_publish_at() -> str | None:
    while True:
        ans = input("Планировать публикацию по времени? (y/n): ").strip().lower()
        if ans in ("y", "yes", "д", "да"):
            break
        if ans in ("n", "no", "н", "нет"):
            return None
        print("Введите y или n.")

        # Режим выбора времени
    while True:
        mode = input("Какое время? 1) ближайшие 03:00 МСК  2) указать дату/время МСК (YYYY-MM-DD HH:MM): ").strip()
        if mode == "1":
            publish_at = next_publish_time_msk(3, 0)
            print("Ок, поставлю publishAt (UTC):", publish_at)
            return publish_at
        if mode == "2":
            raw = input("Введи дату/время по МСК (пример: 2026-01-10 03:00): ").strip()
            try:
                dt_local = datetime.strptime(raw, "%Y-%m-%d %H:%M").replace(tzinfo=MSK)
                # небольшой запас: не ставить публикацию на "прямо сейчас"
                if dt_local <= datetime.now(MSK) + timedelta(minutes=5):
                    print("Время слишком близко/в прошлом. Укажи будущее время (минимум +5 минут).")
                    continue
                publish_at = to_rfc3339_utc(dt_local.astimezone(timezone.utc))
                print("Ок, поставлю publishAt (UTC):", publish_at)
                return publish_at
            except ValueError:
                print("Неверный формат. Нужно YYYY-MM-DD HH:MM (например 2026-01-10 03:00).")
                continue
        print("Выбери 1 или 2.")


def build_description(beat_name: str, tags: list[str]) -> str:
    return DESCRIPTION_TEMPLATE.format(
        beat_name=beat_name,
        purchase_link="https://bsta.rs/FLGeJb",
        tags=" ".join(tags)
    )


def detect_playlists(title: str) -> list[str]:
    title_lower = title.lower()
    result = []

    for artist, playlist_id in PLAYLISTS.items():
        if artist in title_lower:
            result.append(playlist_id)

    return result


def authenticate_youtube():
    # Disable OAuthlib's HTTPS verification when running locally.
    # *DO NOT* leave this option enabled in production.
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    client_secret = r"D:\PyCharm\YouTubeUploader\client_secret_2_146476972144-mojtb9a99bgj2i3clkg778405f4j7mh7.apps.googleusercontent.com.json"

    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        client_secret, scopes)

    credentials = flow.run_local_server()

    youtube = googleapiclient.discovery.build(
        "youtube", "v3", credentials=credentials)

    return youtube


# "categoryId": "10"


def upload_video(youtube):
    beat_name = "[42 42] !!DELETE!! Travis Scott x Future x UTOPIA Type Beat [42 42]"

    beat_name = beat_name[:100]

    try:
        # 1) Генерим теги через Gemini
        ai = generate_youtube_tags(beat_name, api_key=GEMINI_API_KEY)
        ai_hashtags = ai["hashtags"]  # ['#TravisScottTypeBeat', ...]
        ai_seo_tags = ai["seo_tags"]  # ['Travis Scott type beat', ...]
        # artists = ai["artists"]
    except Exception as e:
        print("Gemini tags failed, using fallback:", e)
        ai_hashtags = ["#TypeBeat", "#TrapTypeBeat"]
        ai_seo_tags = ["Type Beat", "Trap Type Beat", "Rap Beat"]

    # 2) Собираем описание через твой template (хэштеги идут в DESCRIPTION_TEMPLATE)
    description = build_description(beat_name, ai_hashtags)

    # tags = [
    #     "#TravisScottTypeBeat",
    #     "#MetroBoominTypeBeat",
    #     "#DarkTrap",
    #     "#TypeBeat"
    # ]

    # description = build_description(beat_name, tags)

    publish_at = ask_publish_at()

    status_block = {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": False
    }
    if publish_at:
        status_block["publishAt"] = publish_at

    request_body = {
        "snippet": {
            "title": beat_name,
            "description": description,
            "tags": ai_seo_tags,
            "categoryId": "10"
        },
        "status": status_block
    }

    media_file = r"D:\PyCharm\YouTubeUploader\beat.mp4"

    print(json.dumps(request_body, ensure_ascii=False, indent=2))

    request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=MediaFileUpload(media_file, chunksize=-1, resumable=True)
    )

    response = None

    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload {int(status.progress() * 100)}%")

    preview_file = r"D:\PyCharm\YouTubeUploader\travis.jpg"

    video_id = response["id"]
    print(f"Video uploaded with ID: {video_id}")

    # Превью
    preview_path = download_thumbnail_for_beat(beat_name)
    set_preview(youtube, video_id, str(preview_path))

    # Добавление плейлист

    playlist_id = detect_playlists(beat_name)

    if playlist_id:
        for playlist_id in playlist_id:
            add_video_to_playlist(youtube, video_id, playlist_id)
        print("Video added to playlist")
    else:
        print("No matching playlists found")


def add_video_to_playlist(youtube, video_id: str, playlist_id: str):
    request = youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": video_id
                }
            }
        }
    )
    request.execute()


if __name__ == '__main__':
    youtube = authenticate_youtube()
    upload_video(youtube)
