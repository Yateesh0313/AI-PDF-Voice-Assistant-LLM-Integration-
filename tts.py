"""
Text-to-Speech using gTTS (Google Text-to-Speech).
Includes error handling and cleanup.
"""
from gtts import gTTS
import uuid
import os
import logging

logger = logging.getLogger(__name__)


def text_to_speech(text: str) -> str:
    """Convert text to speech and return the file path."""
    os.makedirs("static", exist_ok=True)

    # Truncate very long responses to avoid gTTS timeout
    if len(text) > 5000:
        text = text[:5000] + "... (response truncated for audio)"

    filename = f"response_{uuid.uuid4().hex}.mp3"
    output_path = os.path.join("static", filename)

    try:
        tts = gTTS(text=text, lang="en")
        tts.save(output_path)
        logger.info("TTS saved: %s (%d bytes)", output_path, os.path.getsize(output_path))
        return output_path
    except Exception as e:
        logger.error("TTS generation failed: %s", e)
        # Clean up partial file if it exists
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        raise