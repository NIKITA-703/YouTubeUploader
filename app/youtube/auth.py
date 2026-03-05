import os
from pathlib import Path

import google_auth_oauthlib.flow
import googleapiclient.discovery
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly",    # Просмотр данных канала
    "https://www.googleapis.com/auth/yt-analytics.readonly",  #  Статистика
]


def _env_flag(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def authenticate_youtube(client_secret_path: str, scopes: list[str] = SCOPES):
    """
    Авторизация YouTube с поддержкой сохранения токена в файл.
    Если token.json существует, использует его. Если нет — открывает браузер.
    """

    # Отключаем проверку HTTPS только для локальной разработки.
    dev_mode = _env_flag("DEVMODE", default=_env_flag("DEV_MODE", default=False))
    if dev_mode:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    else:
        os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)

    creds = None
    # Путь к файлу с токеном будет в той же папке, что и client_secret
    token_path = Path(client_secret_path).parent / "token.json"

    # 1. Пытаемся загрузить уже существующий токен
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        print(f"--> Загружен существующий токен из {token_path}")

    # 2. Если токена нет или он протух
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("--> Токен истек, обновляем его автоматически...")
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"--> Не удалось обновить токен: {e}. Требуется повторный вход.")
                creds = None

        # 3. Если автоматическое обновление не сработало — запускаем вход через браузер
        if not creds:
            print("--> Запуск ручной авторизации через браузер...")
            flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                client_secret_path, scopes)

            print("AUTH FILE:", __file__)
            print("AUTH PORT:", 8080)

            creds = flow.run_local_server(port=8080)

        # 4. Сохраняем свежий токен в файл для будущего использования
        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())
            print(f"--> Новый токен сохранен в {token_path}")

    # Строим сервис YouTube v3
    youtube = googleapiclient.discovery.build(
        "youtube", "v3", credentials=creds)

    return youtube, creds
