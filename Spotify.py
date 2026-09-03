"""Independent Spotify playback integration for JARVIS.

Credentials and user-specific playback settings come exclusively from
environment variables. Importing this module never starts authentication;
Spotipy is loaded lazily on the first Spotify command.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import re
import time
from typing import Any, Callable

from App_launch import LaunchResult, launch_application


SPOTIFY_SCOPES = (
    "user-modify-playback-state",
    "user-read-playback-state",
    "user-read-currently-playing",
)


def _environment_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class SpotifyConfig:
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = "http://127.0.0.1:8888/callback"
    preferred_device_name: str = "This Computer"
    playlist_uri: str = ""
    start_track_uri: str = ""
    cache_path: str = ".spotify_cache"
    device_wait_seconds: float = 12.0

    @classmethod
    def from_environment(cls) -> "SpotifyConfig":
        return cls(
            client_id=os.getenv("SPOTIFY_CLIENT_ID", "").strip(),
            client_secret=os.getenv("SPOTIFY_CLIENT_SECRET", "").strip(),
            redirect_uri=os.getenv(
                "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"
            ).strip(),
            preferred_device_name=os.getenv(
                "SPOTIFY_DEVICE_NAME", "This Computer"
            ).strip(),
            playlist_uri=os.getenv("SPOTIFY_PLAYLIST_URI", "").strip(),
            start_track_uri=os.getenv("SPOTIFY_START_TRACK_URI", "").strip(),
            cache_path=os.getenv("SPOTIFY_CACHE_PATH", ".spotify_cache").strip(),
            device_wait_seconds=max(
                0.0, _environment_float("SPOTIFY_DEVICE_WAIT_SECONDS", 12.0)
            ),
        )


@dataclass(frozen=True)
class SpotifyResult:
    success: bool
    action: str
    message: str
    track: str | None = None
    artist: str | None = None
    device_id: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class SpotifyController:
    """Small facade around Spotipy, suitable for direct use by ``jarvis_main``."""

    def __init__(
        self,
        config: SpotifyConfig | None = None,
        *,
        client: Any | None = None,
        app_launcher: Callable[[str], LaunchResult] = launch_application,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config or SpotifyConfig.from_environment()
        self._client = client
        self._app_launcher = app_launcher
        self._sleep = sleep

    def _get_client(self) -> tuple[Any | None, str | None]:
        if self._client is not None:
            return self._client, None
        if not self.config.client_id or not self.config.client_secret:
            return None, (
                "Spotify credentials are not configured. Set SPOTIFY_CLIENT_ID "
                "and SPOTIFY_CLIENT_SECRET."
            )
        try:
            import spotipy
            from spotipy.oauth2 import SpotifyOAuth

            auth_manager = SpotifyOAuth(
                client_id=self.config.client_id,
                client_secret=self.config.client_secret,
                redirect_uri=self.config.redirect_uri,
                scope=" ".join(SPOTIFY_SCOPES),
                cache_path=self.config.cache_path,
                open_browser=True,
            )
            self._client = spotipy.Spotify(auth_manager=auth_manager)
            self._client.current_user()  # Complete auth now so the cache is immediately usable.
            return self._client, None
        except Exception as exc:
            return None, str(exc)

    def _select_device(self, client: Any) -> tuple[str | None, str | None]:
        try:
            devices = (client.devices() or {}).get("devices", [])
        except Exception as exc:
            return None, str(exc)
        preferred = self.config.preferred_device_name.casefold()
        if preferred:
            for device in devices:
                if preferred in str(device.get("name", "")).casefold():
                    return device.get("id"), None
        for device in devices:
            if device.get("is_active"):
                return device.get("id"), None
        if devices:
            return devices[0].get("id"), None
        return None, None

    def _device_for_playback(
        self, client: Any, *, launch_if_missing: bool
    ) -> tuple[str | None, str | None]:
        device_id, error = self._select_device(client)
        if device_id or error or not launch_if_missing:
            return device_id, error

        launch_result = self._app_launcher("spotify")
        if not launch_result.success:
            return None, launch_result.error or launch_result.message

        deadline = time.monotonic() + self.config.device_wait_seconds
        while time.monotonic() < deadline:
            self._sleep(min(1.0, max(0.05, self.config.device_wait_seconds)))
            device_id, error = self._select_device(client)
            if device_id or error:
                return device_id, error
        return None, "Spotify opened, but no playback device became available."

    @staticmethod
    def _track_score(query: str, track: dict[str, Any]) -> tuple[int, int, int]:
        query_words = set(re.findall(r"[a-z0-9]+", query.casefold()))
        name = str(track.get("name", "")).casefold()
        artists = " ".join(
            str(artist.get("name", "")) for artist in track.get("artists", [])
        ).casefold()
        searchable = set(re.findall(r"[a-z0-9]+", f"{name} {artists}"))
        overlap = len(query_words.intersection(searchable))
        exact_name = int(name == query.casefold().strip())
        popularity = int(track.get("popularity") or 0)
        return exact_name, overlap, popularity

    def play_usual(self) -> SpotifyResult:
        if not self.config.playlist_uri:
            return SpotifyResult(
                False,
                "play_usual",
                "Set SPOTIFY_PLAYLIST_URI before using 'play the usual'.",
            )
        client, error = self._get_client()
        if client is None:
            return SpotifyResult(False, "play_usual", "Spotify is not connected.", error=error)
        device_id, error = self._device_for_playback(client, launch_if_missing=True)
        if not device_id:
            return SpotifyResult(
                False, "play_usual", "No Spotify playback device is available.", error=error
            )
        try:
            playback_arguments: dict[str, Any] = {
                "device_id": device_id,
                "context_uri": self.config.playlist_uri,
            }
            if self.config.start_track_uri:
                playback_arguments["offset"] = {"uri": self.config.start_track_uri}
            client.start_playback(**playback_arguments)
            return SpotifyResult(
                True,
                "play_usual",
                "Playing the usual playlist.",
                device_id=device_id,
            )
        except Exception as exc:
            return SpotifyResult(
                False,
                "play_usual",
                "Could not start the usual playlist.",
                device_id=device_id,
                error=str(exc),
            )

    def search_and_play(self, query: str) -> SpotifyResult:
        cleaned_query = " ".join((query or "").strip().split())
        if not cleaned_query:
            return self.control("resume")
        client, error = self._get_client()
        if client is None:
            return SpotifyResult(False, "search_and_play", "Spotify is not connected.", error=error)
        device_id, error = self._device_for_playback(client, launch_if_missing=True)
        if not device_id:
            return SpotifyResult(
                False,
                "search_and_play",
                "No Spotify playback device is available.",
                error=error,
            )
        try:
            response = client.search(q=cleaned_query, limit=8, type="track") or {}
            tracks = response.get("tracks", {}).get("items", [])
            if not tracks:
                return SpotifyResult(
                    False,
                    "search_and_play",
                    f"Could not find '{cleaned_query}' on Spotify.",
                    device_id=device_id,
                )
            best = max(tracks, key=lambda track: self._track_score(cleaned_query, track))
            artists = [str(artist.get("name", "")) for artist in best.get("artists", [])]
            artist = ", ".join(name for name in artists if name) or "Unknown artist"
            track_name = str(best.get("name", cleaned_query))
            client.start_playback(device_id=device_id, uris=[best["uri"]])
            return SpotifyResult(
                True,
                "search_and_play",
                f"Playing {track_name} by {artist}.",
                track=track_name,
                artist=artist,
                device_id=device_id,
            )
        except Exception as exc:
            return SpotifyResult(
                False,
                "search_and_play",
                f"Could not play '{cleaned_query}' on Spotify.",
                device_id=device_id,
                error=str(exc),
            )

    def control(self, action: str) -> SpotifyResult:
        normalized = " ".join((action or "").casefold().strip().split())
        supported = {"pause", "resume", "next", "previous", "shuffle", "volume up", "volume down"}
        if normalized not in supported:
            return SpotifyResult(False, normalized, f"Unsupported Spotify action: {action}.")

        client, error = self._get_client()
        if client is None:
            return SpotifyResult(False, normalized, "Spotify is not connected.", error=error)
        device_id, error = self._device_for_playback(
            client, launch_if_missing=normalized == "resume"
        )
        if not device_id:
            return SpotifyResult(
                False, normalized, "Spotify is not active on a playback device.", error=error
            )

        try:
            if normalized == "pause":
                client.pause_playback(device_id=device_id)
                message = "Paused Spotify."
            elif normalized == "resume":
                client.start_playback(device_id=device_id)
                message = "Resumed Spotify."
            elif normalized == "next":
                client.next_track(device_id=device_id)
                message = "Skipped to the next Spotify track."
            elif normalized == "previous":
                client.previous_track(device_id=device_id)
                message = "Returned to the previous Spotify track."
            elif normalized == "shuffle":
                state = client.current_playback() or {}
                new_state = not bool(state.get("shuffle_state", False))
                client.shuffle(new_state, device_id=device_id)
                message = f"Spotify shuffle is {'on' if new_state else 'off'}."
            else:
                state = client.current_playback() or {}
                current_volume = int((state.get("device") or {}).get("volume_percent", 50))
                delta = 10 if normalized == "volume up" else -10
                new_volume = min(100, max(0, current_volume + delta))
                client.volume(new_volume, device_id=device_id)
                message = f"Spotify volume is {new_volume} percent."
            return SpotifyResult(True, normalized, message, device_id=device_id)
        except Exception as exc:
            return SpotifyResult(
                False,
                normalized,
                "Spotify could not complete that playback command.",
                device_id=device_id,
                error=str(exc),
            )

    def now_playing(self) -> SpotifyResult:
        client, error = self._get_client()
        if client is None:
            return SpotifyResult(False, "now_playing", "Spotify is not connected.", error=error)
        try:
            current = client.current_playback() or {}
            track = current.get("item")
            if not track:
                return SpotifyResult(False, "now_playing", "Nothing is playing on Spotify.")
            name = str(track.get("name", "Unknown track"))
            artists = [str(artist.get("name", "")) for artist in track.get("artists", [])]
            artist = ", ".join(value for value in artists if value) or "Unknown artist"
            state = "Playing" if current.get("is_playing") else "Paused on"
            return SpotifyResult(
                True,
                "now_playing",
                f"{state} {name} by {artist}.",
                track=name,
                artist=artist,
                device_id=(current.get("device") or {}).get("id"),
            )
        except Exception as exc:
            return SpotifyResult(
                False,
                "now_playing",
                "Could not read the current Spotify track.",
                error=str(exc),
            )


_controller: SpotifyController | None = None


def get_controller() -> SpotifyController:
    global _controller
    if _controller is None:
        _controller = SpotifyController()
    return _controller


def play_usual() -> SpotifyResult:
    return get_controller().play_usual()


def search_and_play(query: str) -> SpotifyResult:
    return get_controller().search_and_play(query)


def control(action: str) -> SpotifyResult:
    return get_controller().control(action)


def now_playing() -> SpotifyResult:
    return get_controller().now_playing()


# Compatibility names derived from the old implementation's public functions.
spotify_play_usual = play_usual
spotify_search_and_play = search_and_play
spotify_control = control
spotify_now_playing = now_playing

