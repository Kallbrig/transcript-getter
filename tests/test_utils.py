import pytest
from transcript_bot.utils import (
    is_instagram_url,
    is_supported_url,
    is_youtube_url,
    format_transcript_file,
)


def test_is_instagram_url_reel():
    assert is_instagram_url("https://www.instagram.com/reel/ABC123def/")
    assert is_instagram_url("https://instagram.com/reel/ABC123def/")


def test_is_instagram_url_post():
    assert is_instagram_url("https://www.instagram.com/p/ABC123def/")
    assert is_instagram_url("https://instagram.com/p/ABC123def/")


def test_is_instagram_url_rejects_non_instagram():
    assert not is_instagram_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert not is_instagram_url("https://twitter.com/video/123")
    assert not is_instagram_url("not a url")


def test_is_supported_url_accepts_youtube():
    assert is_supported_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert is_supported_url("https://youtu.be/dQw4w9WgXcQ")
    assert is_supported_url("https://youtube.com/shorts/dQw4w9WgXcQ")


def test_is_supported_url_accepts_instagram():
    assert is_supported_url("https://www.instagram.com/reel/ABC123def/")
    assert is_supported_url("https://www.instagram.com/p/ABC123def/")


def test_is_supported_url_rejects_other():
    assert not is_supported_url("https://tiktok.com/video/123")
    assert not is_supported_url("hello world")


def test_format_transcript_file_includes_source():
    result = format_transcript_file("My Video", "Some Channel", "text here", source="Instagram")
    assert "Instagram" in result
    assert "My Video" in result
    assert "Some Channel" in result
    assert "text here" in result


def test_format_transcript_file_defaults_to_youtube():
    result = format_transcript_file("My Video", "Some Channel", "text here")
    assert "YouTube" in result
