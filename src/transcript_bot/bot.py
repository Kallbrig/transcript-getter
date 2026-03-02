import asyncio
import logging
from functools import partial
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .captions import CaptionError, fetch_captions
from .config import Config
from .downloader import DownloadError, VideoInfo, download_audio, fetch_metadata
from .transcriber import get_whisper_model, transcribe_audio
from .utils import cleanup_files, extract_video_id, is_youtube_url, is_supported_url, safe_filename, write_transcript

logger = logging.getLogger(__name__)


def build_application(config: Config) -> Application:
    app = ApplicationBuilder().token(config.bot_token).build()

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            partial(handle_url_message, config=config),
        )
    )
    app.add_handler(
        CommandHandler("fast", partial(handle_fast_command, config=config))
    )
    app.add_error_handler(error_handler)
    return app


def _is_allowed(update: Update, config: Config) -> bool:
    return update.effective_user.id in config.allowed_user_ids


async def handle_url_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: Config,
) -> None:
    if not _is_allowed(update, config):
        return  # silent rejection

    text = update.message.text.strip()
    if not is_supported_url(text):
        await update.message.reply_text(
            "Send a YouTube or Instagram video URL to get a transcript.\n"
            "For YouTube, you can also use /fast <url> to fetch captions instantly."
        )
        return

    ack = await update.message.reply_text(
        "Downloading and transcribing with Whisper. This may take a few minutes for long videos..."
    )
    asyncio.get_event_loop().create_task(
        _run_slow_pipeline(update, context, config, text, ack.message_id)
    )


async def handle_fast_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: Config,
) -> None:
    if not _is_allowed(update, config):
        return

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


async def _run_slow_pipeline(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: Config,
    url: str,
    ack_message_id: int,
) -> None:
    chat_id = update.effective_chat.id
    audio_path: Path | None = None
    transcript_path: Path | None = None

    try:
        loop = asyncio.get_event_loop()

        video_info: VideoInfo = await loop.run_in_executor(
            None, download_audio, url, config.work_dir
        )
        audio_path = video_info.audio_path

        model = get_whisper_model(config)
        transcript_text: str = await loop.run_in_executor(
            None, transcribe_audio, audio_path, model, config
        )

        transcript_path = write_transcript(
            title=video_info.title,
            channel=video_info.channel,
            transcript=transcript_text,
            video_id=video_info.video_id,
            work_dir=config.work_dir,
            source=video_info.source,
        )

        filename = f"{safe_filename(video_info.title)}.txt"
        with open(transcript_path, "rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=filename,
                caption=url,
            )

    except DownloadError as e:
        logger.error("Download failed for %s: %s", url, e)
        await context.bot.send_message(chat_id, f"Download failed: {e}")
    except Exception as e:
        logger.exception("Slow pipeline error for %s", url)
        await context.bot.send_message(chat_id, f"Error: {e}")
    finally:
        cleanup_files(audio_path, transcript_path)


async def _run_fast_pipeline(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: Config,
    url: str,
    ack_message_id: int,
) -> None:
    chat_id = update.effective_chat.id
    transcript_path: Path | None = None

    try:
        loop = asyncio.get_event_loop()
        video_id = extract_video_id(url)

        metadata = await loop.run_in_executor(None, fetch_metadata, url)
        transcript_text: str = await loop.run_in_executor(
            None, fetch_captions, video_id
        )

        transcript_path = write_transcript(
            title=metadata.title,
            channel=metadata.channel,
            transcript=transcript_text,
            video_id=video_id,
            work_dir=config.work_dir,
            source=metadata.source,
        )

        filename = f"{safe_filename(metadata.title)}.txt"
        with open(transcript_path, "rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=filename,
                caption=url,
            )

    except CaptionError as e:
        logger.warning("Caption fetch failed for %s: %s", url, e)
        await context.bot.send_message(chat_id, f"Caption error: {e}")
    except DownloadError as e:
        logger.error("Metadata fetch failed for %s: %s", url, e)
        await context.bot.send_message(chat_id, f"Failed to fetch video info: {e}")
    except Exception as e:
        logger.exception("Fast pipeline error for %s", url)
        await context.bot.send_message(chat_id, f"Error: {e}")
    finally:
        cleanup_files(transcript_path)


async def error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    logger.error("Unhandled exception", exc_info=context.error)
