"""
Speech-to-Text using Groq Whisper API (cloud-based).
Falls back to a simple error if the API is unreachable.
Includes retry logic for transient failures.
"""
import os
import subprocess
import logging
import httpx

from config import LLM_API_KEY

logger = logging.getLogger(__name__)

# Groq Whisper API endpoint
_GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Max retries for transient failures
_MAX_RETRIES = 2


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
            logger.warning("ffmpeg produced no output for %s. stderr: %s",
                           input_path, result.stderr.decode(errors="replace")[:200])
    except FileNotFoundError:
        logger.error("ffmpeg not found! Voice recognition needs ffmpeg.")
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out converting %s", input_path)
    return input_path


def speech_to_text(audio_path: str) -> str:
    """Transcribe audio to text using Groq's Whisper API with retry."""
    # Convert to WAV for better compatibility
    wav_path = _convert_to_wav(audio_path)

    last_error = None
    try:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                logger.info("Transcribing %s with Groq Whisper API (attempt %d)", wav_path, attempt)

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
                    logger.info("Transcription result: %s", text[:100])
                    return text
                elif response.status_code == 429:
                    # Rate limited — wait and retry
                    logger.warning("Groq Whisper rate limited (attempt %d)", attempt)
                    import time
                    time.sleep(2 * attempt)
                    continue
                else:
                    logger.error("Groq Whisper API error %d: %s", response.status_code, response.text[:200])
                    last_error = f"API error {response.status_code}"

            except httpx.TimeoutException:
                logger.warning("Whisper API timeout (attempt %d)", attempt)
                last_error = "timeout"
            except Exception as e:
                logger.error("Whisper transcription failed (attempt %d): %s", attempt, str(e))
                last_error = str(e)

        logger.error("All Whisper transcription attempts failed: %s", last_error)
        return ""
    finally:
        # Clean up the WAV file if we created one
        if wav_path != audio_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass