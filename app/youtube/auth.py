import os
from pathlib import Path
from contextlib import contextmanager

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


@contextmanager
def _without_http_proxies():
    proxy_keys = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ]
    saved = {key: os.environ.get(key) for key in proxy_keys}
    try:
        for key in proxy_keys:
            os.environ.pop(key, None)
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def authenticate_youtube(
    client_secret_path: str,
    scopes: list[str] = SCOPES,
    *,
    token_path: str | Path | None = None,
):
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

    client_secret = Path(client_secret_path)
    if not client_secret.exists():
        fallback = client_secret.parent / "json" / client_secret.name
        if fallback.exists():
            client_secret = fallback

    creds = None
    # По умолчанию сохраняем токен рядом с client_secret, но путь можно переопределить.
    token_path = Path(token_path).resolve() if token_path else (client_secret.parent / "token.json").resolve()
    token_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Пытаемся загрузить уже существующий токен
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), scopes)
            print(f"--> Загружен существующий токен из {token_path}")
        except Exception as e:
            print(f"--> Не удалось прочитать токен {token_path}: {e}. Будет выполнен новый OAuth вход.")
            creds = None

    # 2. Если токена нет или он протух
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("--> Токен истек, обновляем его автоматически...")
            try:
                with _without_http_proxies():
                    creds.refresh(Request())
            except Exception as e:
                print(f"--> Не удалось обновить токен: {e}. Требуется повторный вход.")
                creds = None

        # 3. Если автоматическое обновление не сработало — запускаем вход через браузер
        if not creds:
            print("--> Запуск ручной авторизации через браузер...")
            with _without_http_proxies():
                flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                    str(client_secret), scopes)

                print("AUTH FILE:", __file__)
                print("AUTH PORT:", 8080)

                creds = flow.run_local_server(port=8080)

        # 4. Сохраняем свежий токен в файл для будущего использования
        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())
            print(f"--> Новый токен сохранен в {token_path}")

    # Строим сервис YouTube v3
    with _without_http_proxies():
        youtube = googleapiclient.discovery.build(
            "youtube", "v3", credentials=creds)

    return youtube, creds
