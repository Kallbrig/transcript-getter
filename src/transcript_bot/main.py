import logging
import sys
from pathlib import Path

from .bot import build_application
from .config import load_config
from .transcriber import get_whisper_model


def main() -> None:
    config = load_config()

    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger(__name__)

    logger.info("Starting transcript bot")
    logger.info("Allowed users: %d user(s) configured", len(config.allowed_user_ids))
    logger.debug("Allowed user IDs: %s", config.allowed_user_ids)
    logger.info(
        "Whisper model: %s / compute_type: %s",
        config.whisper_model,
        config.whisper_compute_type,
    )
    logger.info("Work directory: %s", config.work_dir)

    # Sweep orphaned temp files from any previous crashed run
    _cleanup_work_dir(config.work_dir, logger)

    # Pre-load the Whisper model at startup so:
    # 1. The first transcription request is fast
    # 2. Model loading errors surface immediately via logs/journalctl
    logger.info("Pre-loading Whisper model...")
    get_whisper_model(config)

    app = build_application(config)
    logger.info("Bot is running. Listening for updates...")
    app.run_polling(allowed_updates=["message"])


def _cleanup_work_dir(work_dir: Path, logger: logging.Logger) -> None:
    """Remove any leftover audio/transcript files from a prior crashed run."""
    patterns = ("*.m4a", "*.mp3", "*.wav", "*_transcript.txt")
    count = 0
    for pattern in patterns:
        for f in work_dir.glob(pattern):
            try:
                f.unlink()
                count += 1
            except OSError as e:
                logger.warning("Could not remove orphaned file %s: %s", f, e)
    if count:
        logger.info("Cleaned up %d orphaned temp file(s) from work dir", count)


if __name__ == "__main__":
    main()
