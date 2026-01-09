from .auth import authenticate_youtube
from .playlists import detect_playlists, add_video_to_detected_playlists, add_video_to_playlist

__all__ = [
    "authenticate_youtube",
    "detect_playlists",
    "add_video_to_playlist",
    "add_video_to_detected_playlists",
]