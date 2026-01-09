from __future__ import annotations

from app.config import PLAYLISTS


def detect_playlists(title: str) -> list[str]:
    """
        По названию видео определяет, в какие плейлисты добавлять.
        Ищем ключи из PLAYLISTS как подстроку в title (lowercase).

        Возвращает список playlistId (может быть пустым).
        """
    title_lower = title.lower()
    result = []

    for artist, playlist_id in PLAYLISTS.items():
        if artist in title_lower:
            result.append(playlist_id)

    return result


def add_video_to_playlist(youtube, video_id: str, playlist_id: str):
    """
        Добавляет видео в конкретный плейлист.
    """
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


def add_video_to_detected_playlists(youtube, video_id: str, beat_name: str) -> list[str]:
    """
    Удобная обёртка: сама находит плейлисты по beat_name и добавляет video_id.
    Возвращает список playlistId, куда добавили.
    """
    playlist_ids = detect_playlists(beat_name)

    if playlist_ids:
        for pid in playlist_ids:
            add_video_to_playlist(youtube, video_id, pid)
        print("Video added to playlist(s)")
    else:
        print("No matching playlists found")

    return playlist_ids