import logging
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from .utils import validate_video_id

logger = logging.getLogger(__name__)


class DownloadError(Exception):
    pass


@dataclass
class VideoInfo:
    video_id: str
    title: str
    channel: str
    audio_path: Path
    source: str = "YouTube"


@dataclass
class VideoMetadata:
    video_id: str
    title: str
    channel: str
    source: str = "YouTube"


def fetch_metadata(url: str) -> VideoMetadata:
    """
    Fetch video title and channel without downloading audio.
    Used by the fast (captions) path to get metadata cheaply.
    This is a blocking call — run in executor.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            raw_id = info.get("id")
            if not raw_id:
                raise DownloadError("Video metadata missing 'id' field")
            video_id = validate_video_id(raw_id)
            return VideoMetadata(
                video_id=video_id,
                title=info.get("title", "Unknown Title"),
                channel=info.get("uploader") or info.get("channel", "Unknown Channel"),
                source=info.get("extractor_key", "YouTube"),
            )
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(str(e)) from e
    except Exception as e:
        raise DownloadError(f"Unexpected error fetching metadata: {e}") from e


def download_audio(url: str, work_dir: Path) -> VideoInfo:
    """
    Download audio-only stream and return path + video metadata.
    Uses yt-dlp with FFmpegExtractAudio to produce an m4a file.
    This is a blocking call — run in executor.
    """
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(work_dir / "%(id)s.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "0",
            }
        ],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        raw_id = info.get("id")
        if not raw_id:
            raise DownloadError("Downloaded video missing 'id' field")
        video_id = validate_video_id(raw_id)
        title = info.get("title", "Unknown Title")
        channel = info.get("uploader") or info.get("channel", "Unknown Channel")
        source = info.get("extractor_key", "YouTube")

        # After FFmpegExtractAudio the file is renamed to .m4a
        audio_path = work_dir / f"{video_id}.m4a"
        if not audio_path.exists():
            # Fallback: find any file matching the video ID
            candidates = [
                p for p in work_dir.glob(f"{video_id}.*")
                if p.suffix not in (".txt",)
            ]
            if not candidates:
                raise DownloadError(
                    f"Audio file not found after download for video {video_id}"
                )
            audio_path = candidates[0]

        logger.info("Downloaded audio to %s", audio_path)
        return VideoInfo(
            video_id=video_id,
            title=title,
            channel=channel,
            audio_path=audio_path,
            source=source,
        )

    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(str(e)) from e
    except DownloadError:
        raise
    except Exception as e:
        raise DownloadError(f"Unexpected download error: {e}") from e
