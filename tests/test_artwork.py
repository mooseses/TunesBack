import urllib.parse

from PIL import Image

from tunesback.art import locations
from tunesback.art.artwork import ThumbnailCache, load_artwork
from tunesback.art.locations import parse_file_uri, resolve_location


def test_parse_keeps_hash_and_question_mark():
    parsed = parse_file_uri("file:///Music/Song%20%231%3F.mp3")
    assert parsed.host is None and parsed.path == "/Music/Song #1?.mp3"


def test_parse_network_locations():
    assert parse_file_uri("file://nas/share/a.mp3") == locations.FileUri("nas", "/share/a.mp3")
    # iTunes for Windows writes UNC paths like this
    assert parse_file_uri("file://localhost//nas/share/a.mp3") == locations.FileUri("nas", "/share/a.mp3")
    assert parse_file_uri("file://localhost/C:/Music/a.mp3") == locations.FileUri(None, "/C:/Music/a.mp3")


def test_parse_rejects_other_schemes():
    assert parse_file_uri("http://example.com/a.mp3") is None
    assert parse_file_uri("") is None


def test_windows_paths(monkeypatch):
    monkeypatch.setattr(locations, "SYSTEM", "Windows")
    assert locations._local_path(parse_file_uri("file://localhost/C:/My%20Music/a.mp3")) == "C:\\My Music\\a.mp3"
    assert next(locations._windows_candidates(parse_file_uri("file://nas/share/x/a.mp3"))) == "\\\\nas\\share\\x\\a.mp3"


def test_resolve_local_file_with_special_characters(tmp_path):
    song = tmp_path / "Album #1" / "Song?.mp3"
    song.parent.mkdir()
    song.write_bytes(b"")
    uri = "file://" + urllib.parse.quote(str(song))
    assert resolve_location(uri) == str(song)
    assert resolve_location(uri.replace("Song", "Missing")) is None


def test_folder_cover_is_used_when_tags_are_unreadable(tmp_path):
    song = tmp_path / "track.m4a"
    song.write_bytes(b"not really audio")
    Image.new("RGB", (300, 300), "red").save(tmp_path / "Cover.jpg")
    uri = "file://" + urllib.parse.quote(str(song))
    image = load_artwork(uri)
    assert image is not None and image.size == (300, 300)
    thumb = ThumbnailCache(size=64).get(uri)
    assert thumb.startswith("data:image/jpeg;base64,")


def test_missing_artwork_is_none(tmp_path):
    song = tmp_path / "track.mp3"
    song.write_bytes(b"")
    assert load_artwork("file://" + str(song)) is None
    assert load_artwork(None) is None


def test_thumbnail_disk_cache(tmp_path):
    song = tmp_path / "music" / "track.m4a"
    song.parent.mkdir()
    song.write_bytes(b"")
    Image.new("RGB", (1200, 1200), "blue").save(song.parent / "cover.jpg")
    uri = "file://" + urllib.parse.quote(str(song))

    first = ThumbnailCache(size=64, cache_dir=tmp_path / "thumbs").get_many([uri, "file:///missing.mp3"])
    assert first[uri].startswith("data:image/jpeg") and first["file:///missing.mp3"] is None
    assert len(list((tmp_path / "thumbs").glob("*.jpg"))) == 1

    (song.parent / "cover.jpg").unlink()  # a fresh cache must now read the stored thumbnail
    assert ThumbnailCache(size=64, cache_dir=tmp_path / "thumbs").get(uri) == first[uri]
