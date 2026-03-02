import logging
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

_YOUTUBE_PATTERN = re.compile(
    r"(https?://)?(www\.)?"
    r"(youtube\.com/watch\?|youtu\.be/|youtube\.com/shorts/|youtube\.com/live/)"
    r"[a-zA-Z0-9_?=&-]+"
)

_INSTAGRAM_PATTERN = re.compile(
    r"(https?://)?(www\.)?instagram\.com/(reel|p)/[a-zA-Z0-9_-]+"
)

_VIDEO_ID_PATTERN = re.compile(r"[a-zA-Z0-9_-]{11}")


def is_youtube_url(text: str) -> bool:
    return bool(_YOUTUBE_PATTERN.search(text))


def is_instagram_url(text: str) -> bool:
    return bool(_INSTAGRAM_PATTERN.search(text))


def is_supported_url(text: str) -> bool:
    return is_youtube_url(text) or is_instagram_url(text)


def extract_video_id(url: str) -> str:
    """Extract the 11-character YouTube video ID from any valid YouTube URL."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # youtu.be/VIDEO_ID
    if hostname == "youtu.be":
        video_id = parsed.path.lstrip("/").split("/")[0].split("?")[0]
        if len(video_id) == 11:
            return video_id

    if "youtube.com" in hostname:
        # youtube.com/watch?v=VIDEO_ID
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return qs["v"][0]

        # youtube.com/shorts/VIDEO_ID or youtube.com/live/VIDEO_ID
        parts = parsed.path.split("/")
        for marker in ("shorts", "live"):
            if marker in parts:
                idx = parts.index(marker)
                if idx + 1 < len(parts):
                    return parts[idx + 1]

    raise ValueError(f"Cannot extract video ID from URL: {url}")


def format_transcript_file(title: str, channel: str, transcript: str, source: str = "YouTube") -> str:
    """Format the transcript file content with a header."""
    return f"# {title}\n{channel} ({source})\n\n{transcript}\n"


def write_transcript(
    title: str, channel: str, transcript: str, video_id: str, work_dir: Path,
    source: str = "YouTube",
) -> Path:
    content = format_transcript_file(title, channel, transcript, source=source)
    path = work_dir / f"{video_id}_transcript.txt"
    path.write_text(content, encoding="utf-8")
    logger.debug("Transcript written to %s", path)
    return path


def cleanup_files(*paths: Path | None) -> None:
    for path in paths:
        if path is not None and path.exists():
            try:
                path.unlink()
                logger.debug("Deleted temp file: %s", path)
            except OSError as e:
                logger.warning("Failed to delete %s: %s", path, e)


def safe_filename(title: str) -> str:
    """Sanitize a video title for use as a filename."""
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title)
    sanitized = sanitized.strip(". ")
    return sanitized[:80] or "transcript"
