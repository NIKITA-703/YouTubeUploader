import os
import google_auth_oauthlib.flow
import googleapiclient.discovery


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube"
]


def authenticate_youtube(client_secret_path: str, scopes: list[str] = SCOPES):
    """
       Локальная OAuth-авторизация через браузер.
       Для хоста позже сделаем refresh_token-авторизацию.
   """

    # Disable OAuthlib's HTTPS verification when running locally.
    # *DO NOT* leave this option enabled in production.
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        client_secret_path, scopes)

    credentials = flow.run_local_server()

    youtube = googleapiclient.discovery.build(
        "youtube", "v3", credentials=credentials)

    return youtube