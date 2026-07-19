import os, hmac, hashlib, asyncio, sys, threading
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")

@app.route('/api/crypto-webhook', methods=['POST'])
def crypto_webhook():
    if not CRYPTO_BOT_TOKEN:
        return jsonify({'error': 'Not configured'}), 500
    body = request.get_data(as_text=True)
    sign = request.headers.get('crypto-pay-api-signature', '')
    expected = hmac.new(CRYPTO_BOT_TOKEN.encode(), body.encode(), hashlib.sha256).hexdigest()
    if sign != expected:
        return jsonify({'error': 'Invalid signature'}), 403
    data = request.get_json(silent=True) or {}
    payload = data.get('payload', {})
    if payload.get('status') == 'paid':
        invoice_id = int(payload['invoice_id'])
        try:
            loop = asyncio.new_event_loop()
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from telegram_bot.database import get_invoice, complete_invoice, add_balance
            inv = loop.run_until_complete(get_invoice(invoice_id))
            if inv and inv['status'] == 'active':
                loop.run_until_complete(complete_invoice(invoice_id))
                loop.run_until_complete(add_balance(inv['user_id'], inv['amount_rub']))
                try:
                    from telegram_bot.bot import bot as tg_bot
                    loop.run_until_complete(tg_bot.send_message(
                        inv['user_id'],
                        f"✅ <b>Баланс пополнен!</b>\n\n"
                        f"Сумма: <b>{inv['amount_rub']:.2f}₽</b>\n"
                        f"Текущий баланс: можно проверить в 👤 Профиль"
                    ))
                except:
                    pass
            loop.close()
        except Exception as e:
            print(f"Crypto webhook error: {e}")
    return jsonify({'ok': True})

def run_bot():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from telegram_bot.bot import main as bot_main
    asyncio.run(bot_main(enable_healthcheck=False))

if __name__ == '__main__':
    t = threading.Thread(target=run_bot, daemon=True)
    t.start()
    port = int(os.getenv("PORT", 5000))
    print(f"Бот запущен, вебхук Crypto Bot на порту {port}")
    app.run(host='0.0.0.0', port=port)
