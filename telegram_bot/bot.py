import asyncio
import logging
import os
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import database as db
from config import BOT_TOKEN, ADMIN_IDS, WALLET_ADDRESS, CURRENCY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STICKER_ID = "CAACAgIAAxkBAAEBI3tqEE0wy1Kf_YJwOB5OomVOWxsDvAACc4QAAolZUUqfxgrLunneZDsE"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ── Users DB ──

def init_users_db() -> None:
    with sqlite3.connect("bot.db") as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY,
                username   TEXT,
                first_name TEXT,
                joined_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def upsert_user(user_id: int, username: str | None, first_name: str | None) -> None:
    with sqlite3.connect("bot.db") as conn:
        conn.execute("""
            INSERT INTO users (id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name
        """, (user_id, username, first_name))
        conn.commit()


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    upsert_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    ref_code = None
    if message.text and "ref_" in message.text:
        parts = message.text.split("ref_")
        if len(parts) > 1:
            ref_code = parts[1].strip()

    if ref_code:
        await db.apply_ref(ref_code, message.from_user.id, 0)
        await message.answer(
            "🎉 Вас пригласили! Сделайте первый заказ и получите скидку."
        )

    await message.answer(
        "👋 <b>Добро пожаловать в KILLStest!</b>\n\n"
        "Я бот для продажи цифровых товаров.\n"
        "Используй кнопки ниже 👇",
        reply_markup=reply_menu()
    )
    await message.answer(
        "Выберите раздел:",
        reply_markup=main_menu_keyboard()
    )


@dp.callback_query(F.data == "help")
async def cmd_help(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📚 <b>Как это работает:</b>\n\n"
        "1️⃣ Выберите товар в каталоге\n"
        "2️⃣ Оплатите заказ криптовалютой\n"
        "3️⃣ Отправьте хеш транзакции\n"
        "4️⃣ Получите товар автоматически\n\n"
        "💬 По вопросам: @your_support_username",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "👋 <b>Главное меню</b>\n\nВыберите раздел:",
        reply_markup=main_menu_keyboard()
    )
    await callback.answer()


async def show_catalog_by_message(message: types.Message):
    products = await db.get_products(active_only=True)
    if not products:
        await message.answer("😔 <b>Каталог пуст</b>\n\nТовары скоро появятся!",
                             reply_markup=main_menu_keyboard())
        return
    kb = []
    for p in products:
        kb.append([InlineKeyboardButton(text=f"{p['name']} - {p['price']} {CURRENCY}",
                                        callback_data=f"product_{p['id']}")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    await message.answer(
        "🛍 <b>Каталог товаров</b>\n\nВыберите товар:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )


@dp.callback_query(F.data == "catalog")
async def show_catalog(callback: types.CallbackQuery):
    products = await db.get_products(active_only=True)

    if not products:
        await callback.message.edit_text(
            "😔 <b>Каталог пуст</b>\n\nТовары скоро появятся!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
            ])
        )
        await callback.answer()
        return

    keyboard_buttons = []
    for product in products:
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"{product['name']} - {product['price']} {CURRENCY}",
                callback_data=f"product_{product['id']}"
            )
        ])
    keyboard_buttons.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")
    ])

    await callback.message.edit_text(
        "🛍 <b>Каталог товаров</b>\n\nВыберите товар:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("product_"))
async def show_product(callback: types.CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    product = await db.get_product(product_id)

    if not product:
        await callback.answer("Товар не найден!", show_alert=True)
        return

    text = (
        f"📦 <b>{product['name']}</b>\n\n"
        f"{product['description']}\n\n"
        f"💰 <b>Цена:</b> {product['price']} {CURRENCY}\n"
        f"📂 <b>Категория:</b> {product['category']}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Купить", callback_data=f"buy_{product_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="catalog")]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data.startswith("buy_"))
async def buy_product(callback: types.CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    product = await db.get_product(product_id)

    if not product:
        await callback.answer("Товар не найден!", show_alert=True)
        return

    order_id = await db.create_order(
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        product_id=product_id,
        amount=product["price"]
    )

    text = (
        f"💳 <b>Оплата заказа #{order_id}</b>\n\n"
        f"📦 Товар: {product['name']}\n"
        f"💰 Сумма: <b>{product['price']} {CURRENCY}</b>\n\n"
        f"Переведите <b>{product['price']} {CURRENCY}</b> на кошелёк:\n"
        f"<code>{WALLET_ADDRESS}</code>\n\n"
        f"⚠️ После оплаты отправьте хеш транзакции (TX ID)\n"
        f"или скриншот подтверждения."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="catalog")]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


# ── Reply menu ──

def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Каталог", callback_data="catalog")],
        [InlineKeyboardButton(text="📦 Мои покупки", callback_data="my_orders")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")]
    ])


def reply_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛍 Каталог"), KeyboardButton(text="📦 Мои покупки")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🔗 Рефералы")],
            [KeyboardButton(text="ℹ️ Помощь"), KeyboardButton(text="Без кнопки никак")]
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите действие..."
    )


@dp.message(F.text == "🛍 Каталог")
async def reply_catalog(message: types.Message):
    await show_catalog_by_message(message)


@dp.message(F.text == "📦 Мои покупки")
async def reply_my_orders(message: types.Message):
    orders = await db.get_user_orders(message.from_user.id)
    if not orders:
        await message.answer("📦 <b>Ваши покупки</b>\n\nУ вас пока нет заказов.")
        return
    text = "📦 <b>Ваши покупки:</b>\n\n"
    for order in orders[:10]:
        emoji = "✅" if order["status"] == "completed" else "⏳"
        text += f"{emoji} #{order['id']} - {order['product_name']} ({order['amount']} {CURRENCY})\n"
    await message.answer(text)


@dp.message(F.text == "🔗 Рефералы")
async def reply_ref(message: types.Message):
    ref = await db.get_or_create_ref(message.from_user.id)
    bot_username = (await bot.me()).username
    await message.answer(
        f"🔗 <b>Реферальная программа</b>\n\n"
        f"Приглашай друзей и получай 5% от их покупок!\n\n"
        f"Твоя ссылка:\n"
        f"<code>https://t.me/{bot_username}?start=ref_{ref['ref_code']}</code>\n\n"
        f"💵 Заработано: {ref['earned']} {CURRENCY}"
    )


@dp.message(F.text == "ℹ️ Помощь")
async def reply_help(message: types.Message):
    await message.answer(
        "📚 <b>Как это работает:</b>\n\n"
        "1️⃣ Выберите товар в каталоге\n"
        "2️⃣ Оплатите криптовалютой USDT TRC20\n"
        "3️⃣ Отправьте хеш транзакции\n"
        "4️⃣ Получите товар\n\n"
        "💬 Поддержка: @accounts22"
    )


@dp.message(F.text == "👤 Профиль")
async def reply_profile(message: types.Message):
    orders = await db.get_user_orders(message.from_user.id)
    completed = len([o for o in orders if o["status"] == "completed"])
    total = len(orders)
    ref = await db.get_or_create_ref(message.from_user.id)
    bot_username = (await bot.me()).username
    await message.answer(
        f"👤 <b>Профиль</b>\n\n"
        f"ID: <code>{message.from_user.id}</code>\n"
        f"Username: @{message.from_user.username or 'не указан'}\n"
        f"Заказов: {total} | Выполнено: {completed}\n\n"
        f"🔗 <b>Реферальная ссылка:</b>\n"
        f"<code>https://t.me/{bot_username}?start=ref_{ref['ref_code']}</code>\n"
        f"💵 Заработано с рефералов: {ref['earned']} {CURRENCY}"
    )


@dp.message(Command("ref"))
async def cmd_ref(message: types.Message):
    ref = await db.get_or_create_ref(message.from_user.id)
    bot_username = (await bot.me()).username
    await message.answer(
        f"🔗 <b>Твоя реферальная ссылка:</b>\n\n"
        f"<code>https://t.me/{bot_username}?start=ref_{ref['ref_code']}</code>\n\n"
        f"👥 Приглашай друзей — получай 5% от их покупок!\n"
        f"💵 Заработано: {ref['earned']} {CURRENCY}"
    )


@dp.message(Command("mailing"))
async def cmd_mailing(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer(
        "📨 <b>Рассылка</b>\n\n"
        "Отправь сообщение, которое хочешь разослать всем пользователям.\n"
        "Поддерживается HTML-разметка."
    )
    dp.message.register(handle_mailing, F.text)


async def handle_mailing(message: types.Message):
    users = await db.get_all_users()
    sent = 0
    failed = 0
    await message.answer(f"📨 Начинаю рассылку {len(users)} пользователям...")
    for u in users:
        try:
            await bot.send_message(u["user_id"], message.text, parse_mode=ParseMode.HTML)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    await message.answer(f"✅ Рассылка завершена!\nОтправлено: {sent}\nОшибок: {failed}")


@dp.message(F.text == "Без кнопки никак")
async def btn_no_choice(message: types.Message) -> None:
    await message.answer_sticker(STICKER_ID)


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    stats = await db.get_stats()
    text = (
        f"📊 <b>Статистика магазина</b>\n\n"
        f"📦 Товаров: {stats['products']}\n"
        f"🛒 Заказов всего: {stats['total_orders']}\n"
        f"⏳ Ожидают: {stats['pending_orders']}\n"
        f"✅ Выполнено: {stats['completed_orders']}\n"
        f"💰 Выручка: {stats['total_revenue']} {CURRENCY}\n"
        f"👥 Покупателей: {stats['unique_buyers']}"
    )
    await message.answer(text)


# ── Admin confirm/reject ──

@dp.callback_query(F.data.startswith("confirm_"))
async def confirm_payment(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split("_")[1])
    await db.update_order_status(order_id, "completed")
    order = await db.get_order(order_id)
    await callback.message.edit_text(
        callback.message.text + "\n\n✅ <b>Оплата подтверждена!</b>"
    )
    await callback.answer("✅ Заказ подтверждён", show_alert=True)
    if order:
        try:
            await bot.send_message(
                order["user_id"],
                f"✅ <b>Оплата подтверждена!</b>\n\n"
                f"Заказ #{order_id} — {order['product_name']}\n"
                f"Спасибо за покупку!"
            )
        except:
            pass


@dp.callback_query(F.data.startswith("reject_"))
async def reject_payment(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split("_")[1])
    await db.update_order_status(order_id, "rejected")
    order = await db.get_order(order_id)
    await callback.message.edit_text(
        callback.message.text + "\n\n❌ <b>Платёж отклонён</b>"
    )
    await callback.answer("❌ Заказ отклонён", show_alert=True)
    if order:
        try:
            await bot.send_message(
                order["user_id"],
                f"❌ <b>Платёж отклонён</b>\n\n"
                f"Заказ #{order_id} — {order['product_name']}\n"
                f"Свяжитесь с поддержкой: @accounts22"
            )
        except:
            pass


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_message(message: types.Message):
    if message.reply_to_message and "Оплата заказа" in (message.reply_to_message.text or ""):
        tx_hash = message.text.strip()

        orders = await db.get_all_orders(status="pending")
        user_orders = [o for o in orders if o["user_id"] == message.from_user.id]

        if user_orders:
            latest_order = user_orders[0]
            await db.update_order_status(latest_order["id"], "awaiting_confirmation", tx_hash)

            await message.answer(
                "✅ <b>Хеш транзакции получен!</b>\n\n"
                f"Номер заказа: #{latest_order['id']}\n"
                f"TX: <code>{tx_hash}</code>\n\n"
                "Ожидайте подтверждения оплаты администратором."
            )

            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"🔔 <b>Новый платёж!</b>\n\n"
                        f"Заказ: #{latest_order['id']}\n"
                        f"Покупатель: @{message.from_user.username or message.from_user.id}\n"
                        f"Сумма: {latest_order['amount']} {CURRENCY}\n"
                        f"TX: <code>{tx_hash}</code>",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [
                                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_{latest_order['id']}"),
                                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{latest_order['id']}")
                            ]
                        ])
                    )
                except:
                    pass


@dp.callback_query(F.data.startswith("my_orders"))
async def my_orders(callback: types.CallbackQuery):
    orders = await db.get_user_orders(callback.from_user.id)

    if not orders:
        await callback.message.edit_text(
            "📦 <b>Ваши покупки</b>\n\nУ вас пока нет заказов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛍 В каталог", callback_data="catalog")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
            ])
        )
        await callback.answer()
        return

    text = "📦 <b>Ваши покупки:</b>\n\n"
    for order in orders[:10]:
        status_emoji = "✅" if order["status"] == "completed" else "⏳"
        text += f"{status_emoji} #{order['id']} - {order['product_name']} ({order['amount']} {CURRENCY})\n"

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
    )
    await callback.answer()


async def main(enable_healthcheck=True):
    if not BOT_TOKEN:
        raise ValueError("Переменная BOT_TOKEN не найдена в .env")

    await db.init_db()
    init_users_db()
    logger.info("Бот запущен!")

    if enable_healthcheck:
        port = int(os.getenv("PORT", 10000))
        from aiohttp import web
        async def healthcheck(request):
            return web.Response(text="ok")
        web_app = web.Application()
        web_app.router.add_get("/", healthcheck)
        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        asyncio.create_task(site.start())

    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
