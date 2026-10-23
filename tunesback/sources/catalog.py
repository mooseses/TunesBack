"""Music players and services shown during set-up.

`flow` says how set-up connects one: "library" (find a library file on this
computer or a network drive), "account" (an online profile) or "export" (a
downloaded history file).
"""
from __future__ import annotations

CATALOG = [
    {"id": "itunes", "name": "iTunes / Apple Music", "blurb": "Your library on this computer", "available": True, "flow": "library"},
    {"id": "lastfm", "name": "Last.fm", "blurb": "Every scrobble, with dates", "available": True, "flow": "account"},
    {"id": "listenbrainz", "name": "ListenBrainz", "blurb": "Every listen, with dates", "available": True, "flow": "account"},
    {"id": "spotify", "name": "Spotify", "blurb": "Your downloaded listening history", "available": True, "flow": "export"},
    {"id": "musicbee", "name": "MusicBee", "blurb": "Windows", "available": False},
    {"id": "foobar2000", "name": "foobar2000", "blurb": "With playback statistics", "available": False},
    {"id": "mediamonkey", "name": "MediaMonkey", "blurb": "Windows", "available": False},
    {"id": "rockbox", "name": "Rockbox", "blurb": "On your music player", "available": False},
    {"id": "plexamp", "name": "Plexamp / Plex", "blurb": "Your Plex server", "available": False},
    {"id": "jellyfin", "name": "Jellyfin", "blurb": "Your Jellyfin server", "available": False},
    {"id": "navidrome", "name": "Navidrome", "blurb": "Subsonic-compatible server", "available": False},
    {"id": "strawberry", "name": "Strawberry / Clementine", "blurb": "Linux, Windows, macOS", "available": False},
]
