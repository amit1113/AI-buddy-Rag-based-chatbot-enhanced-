"""Central settings. Everything tunable lives here so tools stay free of magic numbers."""
import os
from pathlib import Path

from dotenv import load_dotenv

# override=True: the .env file wins over any old key left in Windows environment variables.
load_dotenv(override=True)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
INDEX_DIR = DATA_DIR / "index"

# Accepts either name so your old .env (GOOGLE_API_KEY) keeps working.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-flash-latest")
# Used automatically when CHAT_MODEL stays overloaded after retries.
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-flash-lite-latest")
EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")

# Reliability
REQUEST_TIMEOUT_MS = 60_000   # give up on a single request after 60 s
MAX_RETRIES = 2               # attempts per model for busy/overloaded errors
RETRY_BASE_DELAY = 2.0        # seconds; doubles after each failed attempt

# Conversation memory: number of messages kept (user + assistant each count as one).
MEMORY_MESSAGES = 20

# Retrieval settings (characters, not tokens).
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
TOP_K = 5

# Screen tool
SCREEN_DELAY_SECONDS = float(os.getenv("SCREEN_DELAY_SECONDS", "5"))  # time to switch windows after /screen
SCREEN_MAX_DIMENSION = 1800   # longest side of the image sent to the model, in pixels
SCREEN_JPEG_QUALITY = 85
SAVE_LAST_CAPTURE = True      # keep the last capture on disk so you can see exactly what was sent
SCREEN_SETTLE_SECONDS = 0.3   # overlay hides this long before a capture so the window behind can repaint
LAST_CAPTURE_PATH = DATA_DIR / "last_capture.jpg"
# Windows whose app name or title contains any of these words are never read. Extend it in .env.
SCREEN_BLOCKLIST = [
    word.strip().lower()
    for word in os.getenv(
        "SCREEN_BLOCKLIST", "keepass,1password,bitwarden,lastpass,dashlane,netbanking"
    ).split(",")
    if word.strip()
]

# Overlay app
HOTKEY = os.getenv("HOTKEY", "ctrl+alt+space")  # modifiers (ctrl, alt, shift, win) + one key, joined by +

# Automatic routing of plain messages: "hybrid" (rules first, then an LLM), "rules", "llm", or "off"
# ("off" = plain messages always go to chat; type /doc or /screen yourself).
AUTO_ROUTE = os.getenv("AUTO_ROUTE", "hybrid").strip().lower()
if AUTO_ROUTE not in ("hybrid", "rules", "llm", "off"):
    AUTO_ROUTE = "hybrid"
