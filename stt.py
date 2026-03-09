"""
Speech-to-Text using Groq Whisper API (cloud-based).
Falls back to a simple error if the API is unreachable.
"""
import os
import subprocess
import tempfile
import logging
import httpx

from config import LLM_API_KEY, LLM_BASE_URL

logger = logging.getLogger(__name__)

# Groq Whisper API endpoint
_GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


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
            logger.warning("ffmpeg produced no output for %s.", input_path)
    except FileNotFoundError:
        logger.error("ffmpeg not found! Voice recognition needs ffmpeg.")
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out converting %s", input_path)
    return input_path


def speech_to_text(audio_path: str) -> str:
    """Transcribe audio to text using Groq's Whisper API."""
    # Convert to WAV for better compatibility
    wav_path = _convert_to_wav(audio_path)

    try:
        logger.info("Transcribing %s with Groq Whisper API", wav_path)

        with open(wav_path, "rb") as audio_file:
            response = httpx.post(
                _GROQ_WHISPER_URL,
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                },
                files={
                    "file": (os.path.basename(wav_path), audio_file, "audio/wav"),
                },
                data={
                    "model": "whisper-large-v3",
                    "language": "en",
                    "response_format": "json",
                },
                timeout=30.0,
            )

        if response.status_code == 200:
            result = response.json()
            text = result.get("text", "").strip()
            logger.info("Transcription result: %s", text)
            return text
        else:
            logger.error("Groq Whisper API error %d: %s", response.status_code, response.text)
            return ""

    except Exception as e:
        logger.error("Whisper transcription failed: %s", str(e))
        return ""
    finally:
        # Clean up WAV if we created one
        if wav_path != audio_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass