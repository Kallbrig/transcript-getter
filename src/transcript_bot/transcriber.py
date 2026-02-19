import logging
from pathlib import Path

from faster_whisper import WhisperModel

from .config import Config

logger = logging.getLogger(__name__)

_model_cache: WhisperModel | None = None


def get_whisper_model(config: Config) -> WhisperModel:
    """
    Return the cached WhisperModel, loading it on first call.
    Model loading can take 15-60 seconds depending on size; always cache it.
    Call this at startup (in main.py) to surface errors early.
    """
    global _model_cache
    if _model_cache is None:
        logger.info(
            "Loading Whisper model '%s' with compute_type='%s'",
            config.whisper_model,
            config.whisper_compute_type,
        )
        _model_cache = WhisperModel(
            config.whisper_model,
            device="auto",
            compute_type=config.whisper_compute_type,
            cpu_threads=0,   # 0 = use all available CPU cores
            num_workers=1,
        )
        logger.info("Whisper model loaded successfully")
    return _model_cache


def transcribe_audio(audio_path: Path, model: WhisperModel, config: Config) -> str:
    """
    Transcribe an audio file using faster-whisper.
    Returns the full transcript as a plain text string.

    IMPORTANT: model.transcribe() returns a lazy generator. The actual inference
    runs during iteration. This entire function must be called via run_in_executor —
    never return the generator across the executor boundary.
    """
    logger.info("Starting transcription of %s", audio_path)

    segments, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        language=config.whisper_language,
        condition_on_previous_text=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )

    logger.info(
        "Detected language '%s' (probability %.2f)",
        info.language,
        info.language_probability,
    )

    # Iterate the generator here, in the executor thread, not in the async coroutine.
    lines = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            lines.append(text)

    transcript = "\n".join(lines)
    logger.info("Transcription complete: %d segments", len(lines))
    return transcript
