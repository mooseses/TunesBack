"""Music players shown during set-up. Only iTunes / Apple Music is supported so far."""
from __future__ import annotations

CATALOG = [
    {"id": "itunes", "name": "iTunes / Apple Music", "blurb": "Library exports and the iTunes library file", "available": True},
    {"id": "musicbee", "name": "MusicBee", "blurb": "Windows", "available": False},
    {"id": "foobar2000", "name": "foobar2000", "blurb": "With playback statistics", "available": False},
    {"id": "mediamonkey", "name": "MediaMonkey", "blurb": "Windows", "available": False},
    {"id": "rockbox", "name": "Rockbox", "blurb": "On your music player", "available": False},
    {"id": "plexamp", "name": "Plexamp / Plex", "blurb": "Your Plex server", "available": False},
    {"id": "jellyfin", "name": "Jellyfin", "blurb": "Your Jellyfin server", "available": False},
    {"id": "navidrome", "name": "Navidrome", "blurb": "Subsonic-compatible server", "available": False},
    {"id": "strawberry", "name": "Strawberry / Clementine", "blurb": "Linux, Windows, macOS", "available": False},
]
