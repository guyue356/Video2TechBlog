import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORAGE_DIR = BASE_DIR / "storage"
VIDEOS_DIR = STORAGE_DIR / "videos"
AUDIO_DIR = STORAGE_DIR / "audio"
OUTPUT_DIR = STORAGE_DIR / "output"
DATABASE_URL = f"sqlite+aiosqlite:///{STORAGE_DIR / 'app.db'}"

for d in [VIDEOS_DIR, AUDIO_DIR, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-v4-pro"
WHISPER_MODEL_SIZE = "large-v3"
def _detect_whisper_device():
    try:
        import ctranslate2
        if "cuda" in ctranslate2.get_supported_compute_types("cuda"):
            return "cuda", "int8_float16"
    except Exception:
        pass
    return "cpu", "int8"

WHISPER_DEVICE, WHISPER_COMPUTE_TYPE = _detect_whisper_device()
print(f"[Whisper] Device: {WHISPER_DEVICE}, Compute: {WHISPER_COMPUTE_TYPE}")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "zh")
MAX_VIDEO_SIZE_MB = 500
AUDIO_SAMPLE_RATE = 16000
