import asyncio
import logging
import os
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import database as db
from config import BOT_TOKEN, ADMIN_IDS, CURRENCY, CRYPTO_BOT_TOKEN, SITE_URL, CHANNEL_USERNAME, CHANNEL_ID, OWNER_USERNAME, DONATE_LINK
import cryptopay

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STICKER_ID = "CAACAgIAAxkBAAEBI3tqEE0wy1Kf_YJwOB5OomVOWxsDvAACc4QAAolZUUqfxgrLunneZDsE"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ── States ──

AWAITING_DEPOSIT_AMOUNT = set()
AWAITING_TRANSFER_TARGET = set()
AWAITING_TRANSFER_AMOUNT = {}
AWAITING_MAILING_TEXT = set()


def reply_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛍 Каталог"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="ℹ️ О магазине")]
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Меню..."
    )


# ── Subscription check ──

async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ("member", "creator", "administrator")
    except:
        return True  # если бот не админ — пропускаем всех


# ── Start ──

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await db.upsert_user(
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

    if not await is_subscribed(message.from_user.id):
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="✅ Я подписался")]],
            resize_keyboard=True
        )
        await message.answer(
            f"🔒 <b>Доступ ограничен</b>\n\n"
            f"Чтобы пользоваться ботом, подпишись на канал:\n"
            f"{CHANNEL_USERNAME}\n\n"
            f"После подписки нажми кнопку ниже 👇",
            reply_markup=kb
        )
        return

    await message.answer(
        "👋 <b>Добро пожаловать в KILLStest!</b>\n\n"
        "Используй кнопки ниже 👇",
        reply_markup=reply_menu()
    )


@dp.message(F.text == "✅ Я подписался")
async def check_sub_after_button(message: types.Message):
    if await is_subscribed(message.from_user.id):
        await message.answer(
            "✅ <b>Подписка подтверждена!</b>\n\n"
            "Добро пожаловать 👇",
            reply_markup=reply_menu()
        )
    else:
        await message.answer(
            f"❌ Ты ещё не подписан на {CHANNEL_USERNAME}.\n"
            f"Подпишись и нажми кнопку снова."
        )


# ── Каталог ──

# ── Subscription guard ──

async def require_sub(message: types.Message) -> bool:
    if await is_subscribed(message.from_user.id):
        return True
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ Я подписался")]],
        resize_keyboard=True
    )
    await message.answer(
        f"🔒 <b>Доступ ограничен</b>\n\n"
        f"Подпишись на канал {CHANNEL_USERNAME}",
        reply_markup=kb
    )
    return False


# ── О магазине ──

@dp.message(F.text == "ℹ️ О магазине")
async def reply_about(message: types.Message):
    if not await require_sub(message): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Наш канал", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
        [InlineKeyboardButton(text="☕️ Кинуть на чай", callback_data="donate")],
        [InlineKeyboardButton(text="👤 Владелец", url=f"https://t.me/{OWNER_USERNAME.lstrip('@')}")]
    ])
    await message.answer(
        "ℹ️ <b>О магазине KILLStest</b>\n\n"
        "Цифровые товары с быстрой доставкой.\n"
        f"Владелец: {OWNER_USERNAME}",
        reply_markup=kb
    )


AWAITING_DONATE_AMOUNT = set()

@dp.callback_query(F.data == "donate")
async def callback_donate(callback: types.CallbackQuery):
    if not await require_sub(callback.message): return
    await callback.message.answer(
        "☕️ <b>Поддержать магазин</b>\n\n"
        "Введите сумму в рублях (₽), которую хотите отправить.\n"
        "Это добровольный донат владельцу.\n\n"
        "Например: <code>100</code>"
    )
    AWAITING_DONATE_AMOUNT.add(callback.from_user.id)
    await callback.answer()


@dp.message(F.text == "🛍 Каталог")
async def reply_catalog(message: types.Message):
    if not await require_sub(message): return
    products = await db.get_products(active_only=True)
    if not products:
        await message.answer("😔 <b>Каталог пуст</b>\n\nТовары скоро появятся!")
        return
    text = "🛍 <b>Каталог товаров</b>\n\n"
    for p in products:
        text += f"<b>{p['id']}.</b> {p['name']} — {p['price']} {CURRENCY}\n"
    text += "\nОтправьте <b>номер товара</b>, чтобы купить."
    await message.answer(text)


# ── Профиль ──

@dp.message(F.text == "👤 Профиль")
async def reply_profile(message: types.Message):
    if not await require_sub(message): return
    import traceback
    try:
        user = await db.get_user(message.from_user.id)
        orders = await db.get_user_orders(message.from_user.id) or []
        ref = await db.get_or_create_ref(message.from_user.id)
        text = (
            f"👤 <b>Мой профиль</b>\n\n"
            f"🪪 ID: <code>{user['id']}</code>\n"
            f"💰 Баланс: <b>{float(user['balance']):.2f}₽</b>\n"
            f"🛒 Покупок: {len(orders)}\n"
            f"💵 Потрачено: <b>{float(user['total_spent']):.2f}₽</b>\n"
            f"🔗 Рефералов: {float(ref['earned']):.2f}₽\n"
            f"🗓 Рега: {user['registered_at']}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Пополнить", callback_data="deposit"),
             InlineKeyboardButton(text="📦 Мои покупки", callback_data="my_orders")],
            [InlineKeyboardButton(text="🔗 Рефералка", callback_data="referral"),
             InlineKeyboardButton(text="💸 Передать", callback_data="transfer")],
            BK
        ])
        await message.answer(text, reply_markup=kb)
    except Exception as e:
        tb = traceback.format_exc()
        await message.answer(f"❌ {e}\n\n<pre>{tb[-500:]}</pre>")


# ── Пополнить ──

@dp.message(F.text == "💰 Пополнить")
async def reply_deposit(message: types.Message):
    if not await require_sub(message): return
    await prompt_deposit(message)


@dp.callback_query(F.data == "deposit")
async def callback_deposit(callback: types.CallbackQuery):
    if not await require_sub(callback.message): return
    await prompt_deposit(callback.message)
    await callback.answer()


async def prompt_deposit(msg: types.Message):
    await msg.answer(
        "💰 <b>Пополнение баланса</b>\n\n"
        "Введите сумму в рублях (₽), которую хотите внести.\n"
        "Оплата через Crypto Bot (USDT по курсу).\n\n"
        "Например: <code>500</code>"
    )
    AWAITING_DEPOSIT_AMOUNT.add(msg.from_user.id)


@dp.message(F.text.regexp(r'^\d+([.,]\d+)?$'))
async def handle_numeric(message: types.Message):
    if not await require_sub(message): return
    uid = message.from_user.id

    if uid in AWAITING_ADMIN_MAILING:
        await handle_mailing(message)
        return
    if uid in AWAITING_ADMIN_NEW_CAT or uid in AWAITING_ADMIN_NEW_PROD:
        return

    if uid in AWAITING_DONATE_AMOUNT:
        AWAITING_DONATE_AMOUNT.discard(uid)
        amount_rub = float(message.text.replace(",", "."))
        if amount_rub < 10:
            await message.answer("❌ Минимальный донат — 10₽")
            return
        await message.answer("⏳ Получаю курс USDT...")
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": "tether", "vs_currencies": "rub"}
                )
                price_data = r.json()
                usdt_rate = price_data.get("tether", {}).get("rub", 90)
        except:
            usdt_rate = 90
        amount_usdt = round(amount_rub / usdt_rate, 2)
        try:
            inv = await cryptopay.create_invoice("USDT", amount_usdt, f"Донат KILLStest {amount_rub}₽")
            if inv and inv.get("ok"):
                await message.answer(
                    f"☕️ <b>Спасибо за поддержку!</b>\n\n"
                    f"Сумма: <b>{amount_rub:.2f}₽</b>\n"
                    f"К оплате: <b>{amount_usdt} USDT</b>\n\n"
                    f"Ссылка для оплаты:\n"
                    f"{inv['result']['pay_url']}"
                )
            else:
                err = inv.get("error") if inv else "Нет ответа от Crypto Bot"
                await message.answer(f"❌ Crypto Bot: {err}")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
        return

    if uid in AWAITING_DEPOSIT_AMOUNT:
        AWAITING_DEPOSIT_AMOUNT.discard(uid)
        amount_rub = float(message.text.replace(",", "."))
        if amount_rub < 10:
            await message.answer("❌ Минимальная сумма пополнения — 10₽")
            return
        await message.answer("⏳ Получаю курс USDT...")
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": "tether", "vs_currencies": "rub"}
                )
                price_data = r.json()
                usdt_rate = price_data.get("tether", {}).get("rub", 90)
        except:
            usdt_rate = 90
        amount_usdt = round(amount_rub / usdt_rate, 2)
        try:
            inv = await cryptopay.create_invoice("USDT", amount_usdt, f"Пополнение баланса KILLStest на {amount_rub}₽")
            if inv and inv.get("ok"):
                result = inv["result"]
                pay_url = result["pay_url"]
                invoice_id = result["invoice_id"]
                await db.save_invoice(invoice_id, uid, amount_rub, amount_usdt)
                await message.answer(
                    f"💰 <b>Счёт на оплату</b>\n\n"
                    f"Сумма: <b>{amount_rub:.2f}₽</b>\n"
                    f"Курс USDT: <b>{usdt_rate}₽</b>\n"
                    f"К оплате: <b>{amount_usdt} USDT</b>\n\n"
                    f"Оплати по ссылке ниже:\n"
                    f"{pay_url}\n\n"
                    f"✅ После оплаты баланс пополнится автоматически"
                )
            else:
                err = inv.get("error") if inv else "Нет ответа от Crypto Bot"
                await message.answer(f"❌ Crypto Bot: {err}")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
        return

    if uid in AWAITING_TRANSFER_TARGET:
        AWAITING_TRANSFER_TARGET.discard(uid)
        target = message.text.strip()
        user = None
        if target.startswith("@"):
            user = await db.find_user_by_username(target[1:])
        else:
            try:
                user = await db.get_user(int(target))
            except ValueError:
                pass
        if not user or user["id"] == uid:
            await message.answer("❌ Пользователь не найден или это вы сами.")
            return
        AWAITING_TRANSFER_AMOUNT[uid] = user["id"]
        await message.answer(f"✅ Получатель: <b>@{user['username'] or user['id']}</b>\n\nВведите сумму в рублях:")
        return

    if uid in AWAITING_TRANSFER_AMOUNT:
        to_id = AWAITING_TRANSFER_AMOUNT.pop(uid)
        amount = float(message.text.replace(",", "."))
        sender = await db.get_user(uid)
        if sender["balance"] < amount:
            await message.answer(f"❌ Недостаточно средств. Баланс: {sender['balance']:.2f}₽")
            return
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0")
            return
        await db.transfer_balance(uid, to_id, amount)
        await message.answer(f"✅ Переведено <b>{amount:.2f}₽</b> пользователю @{to_id}")
        return

    # Product selection (integer only)
    if message.text.isdigit():
        product_id = int(message.text)
        product = await db.get_product(product_id)
        if not product:
            await message.answer("❌ Товар с таким номером не найден.")
            return
        user = await db.get_user(uid)
        price = product["price"]
        if user["balance"] < price:
            await message.answer(
                f"❌ Недостаточно средств.\n"
                f"Баланс: <b>{user['balance']:.2f}₽</b>\n"
                f"Цена: <b>{price}₽</b>\n\n"
                f"Пополни баланс через 💰 Пополнить"
            )
            return
        await db.deduct_balance(uid, price)
        order_id = await db.create_order(
            user_id=uid,
            username=message.from_user.username,
            product_id=product_id,
            amount=price
        )
        await db.update_order_status(order_id, "completed")
        text = f"✅ <b>Покупка совершена!</b>\n\n📦 Товар: {product['name']}\n💰 Цена: {price}₽\n🆔 Заказ: #{order_id}\n\n"
        if product.get("description"):
            text += f"📄 <b>Товар:</b>\n<code>{product['description']}</code>"
        await message.answer(text)
        if product.get("file_id"):
            try:
                await message.answer_document(product["file_id"])
            except:
                pass


# ── Мои покупки ──

@dp.message(F.text == "📦 Мои покупки")
async def reply_my_orders(message: types.Message):
    if not await require_sub(message): return
    await show_my_orders(message)


@dp.callback_query(F.data == "my_orders")
async def callback_my_orders(callback: types.CallbackQuery):
    if not await require_sub(callback.message): return
    await show_my_orders(callback.message)
    await callback.answer()


async def show_my_orders(msg: types.Message):
    orders = await db.get_user_orders(msg.from_user.id)
    if not orders:
        await msg.answer("📦 <b>Ваши покупки</b>\n\nУ вас пока нет заказов.")
        return
    text = "📦 <b>Ваши покупки:</b>\n\n"
    for order in orders[:10]:
        emoji = "✅" if order["status"] == "completed" else "⏳"
        text += f"{emoji} #{order['id']} — {order['product_name']} ({order['amount']}₽)\n"
    await msg.answer(text)


# ── Рефералка ──

@dp.message(F.text == "🔗 Рефералка")
async def reply_ref(message: types.Message):
    if not await require_sub(message): return
    await show_ref(message)


@dp.callback_query(F.data == "referral")
async def callback_ref(callback: types.CallbackQuery):
    if not await require_sub(callback.message): return
    await show_ref(callback.message)
    await callback.answer()


async def show_ref(msg: types.Message):
    ref = await db.get_or_create_ref(msg.from_user.id)
    bot_username = (await bot.me()).username
    await msg.answer(
        f"🔗 <b>Реферальная программа</b>\n\n"
        f"Приглашай друзей и получай 5% от их покупок!\n\n"
        f"Твоя ссылка:\n"
        f"<code>https://t.me/{bot_username}?start=ref_{ref['ref_code']}</code>\n\n"
        f"💵 Заработано: {ref['earned']:.2f}₽"
    )


# ── Передать ──

@dp.message(F.text == "💸 Передать")
async def reply_transfer(message: types.Message):
    if not await require_sub(message): return
    await prompt_transfer(message)


@dp.callback_query(F.data == "transfer")
async def callback_transfer(callback: types.CallbackQuery):
    if not await require_sub(callback.message): return
    await prompt_transfer(callback.message)
    await callback.answer()


async def prompt_transfer(msg: types.Message):
    await msg.answer(
        "💸 <b>Перевод средств</b>\n\n"
        "Введите <b>@username</b> или <b>ID</b> пользователя, "
        "которому хотите перевести деньги:"
    )
    AWAITING_TRANSFER_TARGET.add(msg.from_user.id)


# ── Handle @username for transfer target ──

@dp.message(F.text.regexp(r'^@\w+$'))
async def handle_at_mention(message: types.Message):
    if not await require_sub(message): return
    if message.from_user.id not in AWAITING_TRANSFER_TARGET:
        return
    AWAITING_TRANSFER_TARGET.discard(message.from_user.id)
    user = await db.find_user_by_username(message.text[1:])
    if not user or user["id"] == message.from_user.id:
        await message.answer("❌ Пользователь не найден или это вы сами.")
        return
    AWAITING_TRANSFER_AMOUNT[message.from_user.id] = user["id"]
    await message.answer(f"✅ Получатель: <b>@{user['username'] or user['id']}</b>\n\nВведите сумму в рублях:")


# ── Help (скрытая) ──

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "📚 <b>Как это работает:</b>\n\n"
        "1️⃣ Пополни баланс через 💰 Пополнить\n"
        "2️⃣ Выбери товар в каталоге\n"
        "3️⃣ Купи с баланса\n"
        "4️⃣ Получи товар\n\n"
        "💬 Поддержка: @accounts22"
    )


# ── Ref / Mailing / Admin ──

@dp.message(Command("ref"))
async def cmd_ref(message: types.Message):
    ref = await db.get_or_create_ref(message.from_user.id)
    bot_username = (await bot.me()).username
    await message.answer(
        f"🔗 <b>Твоя реферальная ссылка:</b>\n\n"
        f"<code>https://t.me/{bot_username}?start=ref_{ref['ref_code']}</code>\n\n"
        f"👥 Приглашай друзей — получай 5% от их покупок!\n"
        f"💵 Заработано: {ref['earned']:.2f}₽"
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
    if message.from_user.id not in AWAITING_ADMIN_MAILING:
        return False
    AWAITING_ADMIN_MAILING.discard(message.from_user.id)
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
    return True


AWAITING_ADMIN_BALANCE = {}
AWAITING_ADMIN_SETTING = {}
AWAITING_ADMIN_NEW_CAT = set()
AWAITING_ADMIN_NEW_PROD = set()
AWAITING_ADMIN_MAILING = set()


ADMIN_MENU_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
     InlineKeyboardButton(text="📦 Товары", callback_data="admin_products")],
    [InlineKeyboardButton(text="📂 Категории", callback_data="admin_cats"),
     InlineKeyboardButton(text="📨 Рассылка", callback_data="admin_mailing")],
    [InlineKeyboardButton(text="💳 Выдать баланс", callback_data="admin_balance"),
     InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings")],
    [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
])

ADMIN_BACK = [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]


@dp.message(F.text == "админ")
async def text_admin(message: types.Message):
    await cmd_admin(message)


async def admin_main_menu(callback_or_msg):
    text = "🔧 <b>Админ-панель</b>\n\nВыберите действие:"
    if hasattr(callback_or_msg, "edit_text"):
        await callback_or_msg.edit_text(text, reply_markup=ADMIN_MENU_KB, parse_mode=ParseMode.HTML)
    else:
        await callback_or_msg.answer(text, reply_markup=ADMIN_MENU_KB, parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "back_main")
async def callback_back_main(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "👋 <b>Главное меню</b>\n\nИспользуй кнопки ниже 👇",
        reply_markup=reply_menu()
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_back")
async def callback_admin_back(callback: types.CallbackQuery):
    await admin_main_menu(callback)
    await callback.answer()


BK = [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    await admin_main_menu(message)


@dp.callback_query(F.data == "admin_stats")
async def admin_cb_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔", show_alert=True)
    stats = await db.get_stats()
    users = await db.get_all_db_users()
    total_bal = sum(u["balance"] for u in users)
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"📦 Товаров: {stats['products']}\n"
        f"🛒 Заказов всего: {stats['total_orders']}\n"
        f"⏳ Ожидают: {stats['pending_orders']}\n"
        f"✅ Выполнено: {stats['completed_orders']}\n"
        f"💰 Выручка: {stats['total_revenue']:.2f}₽\n"
        f"👥 Покупателей: {stats['unique_buyers']}\n"
        f"👤 Пользователей: {len(users)}\n"
        f"💵 Балансов всего: {total_bal:.2f}₽"
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[ADMIN_BACK]))
    await callback.answer()


@dp.callback_query(F.data == "admin_products")
async def admin_cb_products(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔", show_alert=True)
    products = await db.get_products(active_only=False)
    kb = []
    for p in products:
        status = "✅" if p["is_active"] else "❌"
        kb.append([InlineKeyboardButton(text=f"{status} #{p['id']} {p['name']} ({p['price']}₽)", callback_data=f"admin_delprod_{p['id']}")])
    kb.append([InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin_addprod")])
    kb.append(ADMIN_BACK)
    await callback.message.edit_text("📦 <b>Управление товарами</b>\n\nНажми на товар чтобы удалить:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_delprod_"))
async def admin_cb_delprod(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔", show_alert=True)
    pid = int(callback.data.split("_")[2])
    await db.delete_product(pid)
    await callback.answer("🗑 Удалено", show_alert=True)
    await admin_cb_products(callback)


@dp.callback_query(F.data == "admin_addprod")
async def admin_cb_addprod(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔", show_alert=True)
    await callback.message.edit_text(
        "➕ <b>Добавить товар</b>\n\nНапиши в одну строку:\n"
        "<code>Название | Цена | Категория</code>\n\n"
        "Например:\n<code>Название товара | 500 | games</code>"
    )
    AWAITING_ADMIN_NEW_PROD.add(callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data == "admin_cats")
async def admin_cb_cats(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔", show_alert=True)
    conn = sqlite3.connect(db.DATABASE_PATH)
    rows = conn.execute("SELECT DISTINCT category FROM products ORDER BY category").fetchall()
    conn.close()
    kb = []
    for r in rows:
        name = r[0]
        kb.append([InlineKeyboardButton(text=f"✕ {name}", callback_data=f"admin_delcat_{name}")])
    kb.append([InlineKeyboardButton(text="➕ Добавить категорию", callback_data="admin_addcat")])
    kb.append(ADMIN_BACK)
    await callback.message.edit_text("📂 <b>Управление категориями</b>\n\nНажми на категорию чтобы удалить:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_delcat_"))
async def admin_cb_delcat(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔", show_alert=True)
    name = callback.data[len("admin_delcat_"):]
    conn = sqlite3.connect(db.DATABASE_PATH)
    conn.execute("UPDATE products SET category = 'general' WHERE category = ?", (name,))
    conn.commit()
    conn.close()
    await callback.answer(f"🗑 Категория {name} удалена", show_alert=True)
    await admin_cb_cats(callback)


@dp.callback_query(F.data == "admin_addcat")
async def admin_cb_addcat(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔", show_alert=True)
    await callback.message.edit_text("➕ <b>Добавить категорию</b>\n\nНапиши название категории:")
    AWAITING_ADMIN_NEW_CAT.add(callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data == "admin_mailing")
async def admin_cb_mailing(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔", show_alert=True)
    await callback.message.edit_text(
        "📨 <b>Рассылка</b>\n\nОтправь следующее сообщение — оно уйдёт всем пользователям.\nПоддерживается HTML.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[ADMIN_BACK])
    )
    AWAITING_ADMIN_MAILING.add(callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data == "admin_balance")
async def admin_cb_balance(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔", show_alert=True)
    await callback.message.edit_text(
        "💳 <b>Выдать баланс</b>\n\nНапиши:\n<code>ID СУММА</code>\nНапример: <code>123456789 500</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[ADMIN_BACK])
    )
    AWAITING_ADMIN_BALANCE[callback.from_user.id] = True
    await callback.answer()


@dp.callback_query(F.data == "admin_settings")
async def admin_cb_settings(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔", show_alert=True)
    await callback.message.edit_text(
        "⚙️ <b>Настройки</b>\n\nНапиши:\n<code>CHANNEL_USERNAME=@channel</code>\n<code>WALLET_ADDRESS=T...</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[ADMIN_BACK])
    )
    AWAITING_ADMIN_SETTING[callback.from_user.id] = True
    await callback.answer()


# ── Admin: добавить категорию ──

@dp.message(F.text & ~F.text.contains("|") & ~F.text.startswith("/") & F.text.len() <= 30)
async def admin_new_cat_input(message: types.Message):
    if message.from_user.id not in ADMIN_IDS or message.from_user.id not in AWAITING_ADMIN_NEW_CAT:
        return
    AWAITING_ADMIN_NEW_CAT.discard(message.from_user.id)
    name = message.text.strip()
    if not name:
        return
    conn = sqlite3.connect(db.DATABASE_PATH)
    conn.execute("INSERT OR IGNORE INTO products (name, description, price, category) VALUES (?, '', 0, ?)",
                 (f"_cat_placeholder_{name}", name))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Категория «{name}» добавлена!")


# ── Admin: добавить товар ──

@dp.message(F.text.contains("|"))
async def admin_new_prod_input(message: types.Message):
    if message.from_user.id not in ADMIN_IDS or message.from_user.id not in AWAITING_ADMIN_NEW_PROD:
        return
    AWAITING_ADMIN_NEW_PROD.discard(message.from_user.id)
    parts = [p.strip() for p in message.text.split("|")]
    if len(parts) < 2:
        await message.answer("❌ Формат: Название | Цена | Категория")
        return
    name = parts[0]
    try:
        price = float(parts[1].replace(",", "."))
    except:
        await message.answer("❌ Цена должна быть числом")
        return
    category = parts[2] if len(parts) > 2 else "general"
    await db.add_product(name, "", price, category=category)
    await message.answer(f"✅ Товар «{name}» добавлен за {price}₽ в категорию {category}")


# ── Admin: выдать баланс ──

@dp.message(F.text.regexp(r'^\d+\s+\d+([.,]\d+)?$'))
async def admin_balance_input(message: types.Message):
    if message.from_user.id not in ADMIN_IDS or message.from_user.id not in AWAITING_ADMIN_BALANCE:
        return
    AWAITING_ADMIN_BALANCE.pop(message.from_user.id, None)
    parts = message.text.split()
    uid = int(parts[0])
    amount = float(parts[1].replace(",", "."))
    conn = sqlite3.connect(db.DATABASE_PATH)
    conn.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (uid,))
    conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, uid))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Выдано {amount:.2f}₽ пользователю {uid}")


# ── Admin: настройки ──

@dp.message(F.text.regexp(r'^(CHANNEL_USERNAME|WALLET_ADDRESS)=.+'))
async def admin_settings_input(message: types.Message):
    if message.from_user.id not in ADMIN_IDS or message.from_user.id not in AWAITING_ADMIN_SETTING:
        return
    AWAITING_ADMIN_SETTING.pop(message.from_user.id, None)
    key, value = message.text.split("=", 1)
    os.environ[key] = value
    await message.answer(f"✅ {key} обновлён на {value}")


# ── Обработчик остальных сообщений ──

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_fallback(message: types.Message):
    if await handle_mailing(message): return
    if not await require_sub(message): return
    await message.answer(
        "❗ Неизвестная команда.\nИспользуй кнопки ниже 👇",
        reply_markup=reply_menu()
    )


# ── Main ──

async def main(enable_healthcheck=True):
    if not BOT_TOKEN:
        raise ValueError("Переменная BOT_TOKEN не найдена в .env")

    await db.init_db()
    logger.info("Бот запущен!")

    if CRYPTO_BOT_TOKEN:
        try:
            webhook_url = f"{SITE_URL}/api/crypto-webhook"
            res = await cryptopay.set_webhook(webhook_url)
            logger.info(f"Crypto Bot webhook set: {res}")
        except Exception as e:
            logger.warning(f"Failed to set Crypto Bot webhook: {e}")

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
