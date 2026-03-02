# Instagram Video Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the Telegram transcript bot to accept Instagram Reels and Posts in addition to YouTube URLs, using yt-dlp (already a dependency) for download and Whisper for transcription.

**Architecture:** Add Instagram URL detection to `utils.py` alongside the existing YouTube detection. Add a `source` field to `VideoInfo`/`VideoMetadata` in `downloader.py`, populated from yt-dlp's `extractor_key`. Update `bot.py` routing to accept any supported URL and fall back to the slow (Whisper) pipeline for Instagram, including when `/fast` is used.

**Tech Stack:** yt-dlp (already handles Instagram natively), python-telegram-bot, faster-whisper. No new dependencies.

---

### Task 1: Add Instagram URL detection and source-aware transcript header to `utils.py`

**Files:**
- Modify: `src/transcript_bot/utils.py`
- Create: `tests/test_utils.py`

**Step 1: Create the test file**

```python
# tests/test_utils.py
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
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/chaseallbright/Development/transcript-getter
python -m pytest tests/test_utils.py -v
```

Expected: multiple failures — `is_instagram_url`, `is_supported_url` not found; `format_transcript_file` signature mismatch.

**Step 3: Implement the changes in `utils.py`**

Replace the top of `src/transcript_bot/utils.py` (lines 1–18) with:

```python
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
```

Then update `format_transcript_file` (currently line 49) to accept a `source` param:

```python
def format_transcript_file(title: str, channel: str, transcript: str, source: str = "YouTube") -> str:
    """Format the transcript file content with a header."""
    return f"# {title}\n{channel} ({source})\n\n{transcript}\n"
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_utils.py -v
```

Expected: all 8 tests PASS.

---

### Task 2: Add `source` field to `VideoInfo` and `VideoMetadata` in `downloader.py`

**Files:**
- Modify: `src/transcript_bot/downloader.py`

No new tests needed here — yt-dlp integration is not unit-testable without network access. The `source` field is populated from yt-dlp's `extractor_key` which returns `"Youtube"` or `"Instagram"` etc.

**Step 1: Add `source` to both dataclasses**

In `downloader.py`, update the dataclasses (lines 14–27):

```python
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
```

**Step 2: Populate `source` in `fetch_metadata`**

In `fetch_metadata`, update the return statement (around line 43):

```python
return VideoMetadata(
    video_id=info.get("id", "unknown"),
    title=info.get("title", "Unknown Title"),
    channel=info.get("uploader") or info.get("channel", "Unknown Channel"),
    source=info.get("extractor_key", "YouTube"),
)
```

**Step 3: Populate `source` in `download_audio`**

In `download_audio`, after extracting `channel` (around line 81), add:

```python
source = info.get("extractor_key", "YouTube")
```

Then update the return statement:

```python
return VideoInfo(
    video_id=video_id,
    title=title,
    channel=channel,
    audio_path=audio_path,
    source=source,
)
```

---

### Task 3: Update `bot.py` routing for Instagram support

**Files:**
- Modify: `src/transcript_bot/bot.py`

**Step 1: Update imports**

Replace line 20:
```python
from .utils import cleanup_files, extract_video_id, is_youtube_url, safe_filename, write_transcript
```
with:
```python
from .utils import cleanup_files, extract_video_id, is_youtube_url, is_supported_url, safe_filename, write_transcript
```

**Step 2: Update `handle_url_message` — URL check and user message**

In `handle_url_message` (around lines 54–58), replace:

```python
    if not is_youtube_url(text):
        await update.message.reply_text(
            "Send a YouTube URL to get a transcript, or use /fast <url> for quick captions."
        )
        return
```

with:

```python
    if not is_supported_url(text):
        await update.message.reply_text(
            "Send a YouTube or Instagram video URL to get a transcript.\n"
            "For YouTube, you can also use /fast <url> to fetch captions instantly."
        )
        return
```

**Step 3: Update `_run_slow_pipeline` to pass `source` to `write_transcript`**

In `_run_slow_pipeline`, update the `write_transcript` call (around line 116):

```python
        transcript_path = write_transcript(
            title=video_info.title,
            channel=video_info.channel,
            transcript=transcript_text,
            video_id=video_info.video_id,
            work_dir=config.work_dir,
            source=video_info.source,
        )
```

**Step 4: Update `handle_fast_command` to fall back to slow pipeline for Instagram**

Replace the body of `handle_fast_command` (lines 76–89):

```python
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /fast <youtube_url>")
        return

    url = args[0].strip()

    if not is_supported_url(url):
        await update.message.reply_text("That doesn't look like a supported URL (YouTube or Instagram).")
        return

    if not is_youtube_url(url):
        # Instagram has no caption API — fall back to Whisper
        ack = await update.message.reply_text(
            "Instagram detected. Downloading and transcribing with Whisper..."
        )
        asyncio.get_event_loop().create_task(
            _run_slow_pipeline(update, context, config, url, ack.message_id)
        )
        return

    ack = await update.message.reply_text("Fetching captions...")
    asyncio.get_event_loop().create_task(
        _run_fast_pipeline(update, context, config, url, ack.message_id)
    )
```

**Step 5: Update `_run_fast_pipeline` to pass `source` to `write_transcript`**

In `_run_fast_pipeline`, update the `write_transcript` call (around line 162):

```python
        transcript_path = write_transcript(
            title=metadata.title,
            channel=metadata.channel,
            transcript=transcript_text,
            video_id=video_id,
            work_dir=config.work_dir,
            source=metadata.source,
        )
```

---

### Task 4: Update `write_transcript` in `utils.py` to accept and forward `source`

**Files:**
- Modify: `src/transcript_bot/utils.py`

The `write_transcript` function currently doesn't accept `source`. Update it:

```python
def write_transcript(
    title: str, channel: str, transcript: str, video_id: str, work_dir: Path,
    source: str = "YouTube",
) -> Path:
    content = format_transcript_file(title, channel, transcript, source=source)
    path = work_dir / f"{video_id}_transcript.txt"
    path.write_text(content, encoding="utf-8")
    logger.debug("Transcript written to %s", path)
    return path
```

**Step 1: Apply the change, then run all tests**

```bash
python -m pytest tests/ -v
```

Expected: all tests PASS.

**Step 2: Manual smoke test**

Send an Instagram Reel URL to the bot. Confirm:
- Bot responds with "Downloading and transcribing with Whisper..."
- Bot sends back a `.txt` file
- File header reads: `# [Title]\n[Channel] (Instagram)\n\n[transcript]`

Send a YouTube URL to confirm nothing regressed:
- Header reads: `# [Title]\n[Channel] (Youtube)\n\n[transcript]`

---

### Done

No new dependencies. No changes to `transcriber.py`, `captions.py`, or `config.py`.
