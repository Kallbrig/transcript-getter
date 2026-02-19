import logging

from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)

logger = logging.getLogger(__name__)


class CaptionError(Exception):
    pass


def fetch_captions(video_id: str, languages: list[str] | None = None) -> str:
    """
    Fetch auto-generated or manual captions via youtube-transcript-api.
    Returns the full transcript as a plain text string.
    This is a blocking HTTP call — run in executor.
    """
    if languages is None:
        languages = ["en"]

    try:
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id, languages=languages)

        lines = []
        for snippet in transcript:
            # Support both attribute access (newer API) and dict access (older API)
            text = getattr(snippet, "text", None) or snippet.get("text", "")
            text = text.strip()
            if text:
                lines.append(text)

        result = "\n".join(lines)
        logger.info("Fetched %d caption segments for %s", len(lines), video_id)
        return result

    except TranscriptsDisabled:
        raise CaptionError("Captions are disabled for this video.")
    except NoTranscriptFound:
        raise CaptionError(
            f"No captions found in {languages}. "
            "Try the slow mode (send the URL without /fast) to transcribe with Whisper."
        )
    except CaptionError:
        raise
    except Exception as e:
        raise CaptionError(f"Failed to fetch captions: {e}") from e
