import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
CURRENCY = os.getenv("CURRENCY", "USDT")
DATABASE_PATH = os.getenv("DATABASE_PATH", "database.db")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
SITE_URL = os.getenv("SITE_URL", "https://killstest-site.onrender.com")
# PROXY = os.getenv("PROXY")  # не используется
