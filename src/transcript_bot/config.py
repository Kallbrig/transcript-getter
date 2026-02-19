import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    bot_token: str
    allowed_user_ids: set[int]
    whisper_model: str
    whisper_compute_type: str
    whisper_language: str | None
    work_dir: Path
    log_level: str


def load_config() -> Config:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    raw_ids = os.environ.get("ALLOWED_USER_IDS", "").strip()
    if not raw_ids:
        raise ValueError(
            "ALLOWED_USER_IDS is required — the bot must be restricted to specific users"
        )
    allowed_user_ids = {int(uid.strip()) for uid in raw_ids.split(",") if uid.strip()}

    whisper_model = os.environ.get("WHISPER_MODEL", "small").strip()

    compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "").strip()
    if not compute_type:
        compute_type = _auto_compute_type()

    whisper_language = os.environ.get("WHISPER_LANGUAGE", "").strip() or None

    work_dir = Path(os.environ.get("WORK_DIR", "/tmp/transcript_bot"))
    work_dir.mkdir(parents=True, exist_ok=True)

    log_level = os.environ.get("LOG_LEVEL", "INFO").strip().upper()

    return Config(
        bot_token=token,
        allowed_user_ids=allowed_user_ids,
        whisper_model=whisper_model,
        whisper_compute_type=compute_type,
        whisper_language=whisper_language,
        work_dir=work_dir,
        log_level=log_level,
    )


def _auto_compute_type() -> str:
    """Detect GPU availability and return the appropriate compute type."""
    try:
        import ctranslate2

        supported = ctranslate2.get_supported_compute_types("cuda")
        if "float16" in supported:
            return "float16"
    except Exception:
        pass
    return "int8"
