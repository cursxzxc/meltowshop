import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH")
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
SESSION_PRICE = float(os.getenv("SESSION_PRICE", 0.5))

CRYPTO_BOT_API_URL = os.getenv("CRYPTO_BOT_API_URL", "https://pay.crypt.bot/api/")
CRYPTO_BOT_CURRENCY = os.getenv("CRYPTO_BOT_CURRENCY", "USDT")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_DIR = os.path.join(BASE_DIR, "sessions")
SELL_DIR = os.path.join(BASE_DIR, "sell")
INVALID_DIR = os.path.join(BASE_DIR, "invalid")
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
DATABASE_FILE = os.path.join(BASE_DIR, "users.db")

ADMIN_IDS = []
if ADMIN_IDS_STR:
    try:
        for admin_id in ADMIN_IDS_STR.split(","):
            cleaned_admin_id = admin_id.strip()
            if cleaned_admin_id:
                ADMIN_IDS.append(int(cleaned_admin_id))
    except ValueError as e:
        print(f"Error converting to int: {e}")
        ADMIN_IDS = [] # Reset to empty list on error


print(f"ADMIN_IDS: {ADMIN_IDS}")
