"""
Speech-to-Text using OpenAI Whisper.
Converts browser audio (webm/opus) → WAV for best accuracy.
"""
import os
import subprocess
import tempfile
import logging

# ── Ensure ffmpeg is on PATH (winget installs to a non-PATH location) ──
_FFMPEG_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Microsoft", "WinGet", "Packages",
    "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe",
    "ffmpeg-8.0.1-full_build", "bin",
)
if os.path.isdir(_FFMPEG_DIR) and _FFMPEG_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")

import whisper
from config import WHISPER_MODEL

logger = logging.getLogger(__name__)

# Load model once at import time
model = whisper.load_model(WHISPER_MODEL)


def _convert_to_wav(input_path: str) -> str:
    """Convert any audio file to 16 kHz mono WAV using ffmpeg."""
    wav_path = input_path.rsplit(".", 1)[0] + ".wav"
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", input_path,
                "-ar", "16000",
                "-ac", "1",
                "-c:a", "pcm_s16le",
                wav_path,
            ],
            capture_output=True,
            timeout=30,
        )
        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 0:
            logger.info("Audio converted to WAV: %s → %s", input_path, wav_path)
            return wav_path
        else:
            logger.warning("ffmpeg produced no output for %s. stderr: %s", input_path, result.stderr.decode(errors='replace'))
    except FileNotFoundError:
        logger.error("ffmpeg not found! Voice recognition needs ffmpeg. Install with: winget install Gyan.FFmpeg")
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out converting %s", input_path)
    return input_path


def speech_to_text(audio_path: str) -> str:
    """Transcribe audio to text with format conversion for accuracy."""
    # Convert to WAV for much better Whisper accuracy
    wav_path = _convert_to_wav(audio_path)

    try:
        logger.info("Transcribing %s with Whisper (model=%s)", wav_path, WHISPER_MODEL)
        result = model.transcribe(
            wav_path,
            fp16=False,
            language="en",
            initial_prompt="This is a clear English question about documents or general knowledge.",
        )
        text = result["text"].strip()
        logger.info("Transcription result: %s", text)
        return text
    finally:
        # Clean up WAV if we created one
        if wav_path != audio_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass