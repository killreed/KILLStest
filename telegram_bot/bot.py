import asyncio
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
import database as db
from config import BOT_TOKEN, ADMIN_IDS, WALLET_ADDRESS, CURRENCY, PROXY


session = AiohttpSession(proxy=PROXY) if PROXY else None
bot = Bot(token=BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Каталог", callback_data="catalog")],
        [InlineKeyboardButton(text="📦 Мои покупки", callback_data="my_orders")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")]
    ])

    await message.answer(
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Я бот для продажи цифровых товаров.\n"
        "Выберите раздел в меню ниже:",
        reply_markup=keyboard
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
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Каталог", callback_data="catalog")],
        [InlineKeyboardButton(text="📦 Мои покупки", callback_data="my_orders")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")]
    ])

    await callback.message.edit_text(
        "👋 <b>Главное меню</b>\n\nВыберите раздел:",
        reply_markup=keyboard
    )
    await callback.answer()


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


async def main():
    await db.init_db()
    print("Бот запущен!")

    port = int(os.getenv("PORT", 10000))

    async def healthcheck():
        handler = await asyncio.start_server(
            lambda r, w: None, host="0.0.0.0", port=port
        )
        async with handler:
            await handler.serve_forever()

    asyncio.create_task(healthcheck())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
