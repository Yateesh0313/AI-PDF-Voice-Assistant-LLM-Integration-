from gtts import gTTS
import uuid
import os

def text_to_speech(text: str) -> str:
    os.makedirs("static", exist_ok=True)

    filename = f"response_{uuid.uuid4().hex}.mp3"
    output_path = os.path.join("static", filename)

    tts = gTTS(text=text, lang="en")
    tts.save(output_path)

    return output_path