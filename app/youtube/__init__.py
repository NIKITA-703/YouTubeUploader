def authenticate_youtube(*args, **kwargs):
    from .auth import authenticate_youtube as _authenticate_youtube

    return _authenticate_youtube(*args, **kwargs)


def detect_playlists(*args, **kwargs):
    from .playlists import detect_playlists as _detect_playlists

    return _detect_playlists(*args, **kwargs)


def add_video_to_detected_playlists(*args, **kwargs):
    from .playlists import add_video_to_detected_playlists as _add_video_to_detected_playlists

    return _add_video_to_detected_playlists(*args, **kwargs)


def add_video_to_playlist(*args, **kwargs):
    from .playlists import add_video_to_playlist as _add_video_to_playlist

    return _add_video_to_playlist(*args, **kwargs)


__all__ = [
    "authenticate_youtube",
    "detect_playlists",
    "add_video_to_playlist",
    "add_video_to_detected_playlists",
]
