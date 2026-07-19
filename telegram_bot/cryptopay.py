import httpx
from config import CRYPTO_BOT_TOKEN, SITE_URL

BASE = "https://pay.crypt.bot/api"


async def _post(method, data=None):
    if not CRYPTO_BOT_TOKEN:
        return None
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{BASE}/{method}",
            json=data or {},
            headers={"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
        )
        return r.json()


async def get_me():
    return await _post("getMe")


async def create_invoice(asset, amount, description=""):
    return await _post("createInvoice", {
        "asset": asset,
        "amount": str(amount),
        "description": description
    })


async def set_webhook(url):
    return await _post("setWebhook", {"url": url})


async def get_invoices(offset=0, count=100):
    return await _post("getInvoices", {"offset": offset, "count": count})
