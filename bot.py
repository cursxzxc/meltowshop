
import logging
import os
import asyncio
import urllib.parse
import sqlite3

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, FSInputFile

from config import BOT_TOKEN, CRYPTO_BOT_TOKEN, CRYPTO_BOT_API_URL, CRYPTO_BOT_CURRENCY, SESSION_DIR, SELL_DIR, INVALID_DIR, SCRIPTS_DIR, DATABASE_FILE, ADMIN_IDS, SESSION_PRICE, API_ID, API_HASH
from utils import is_session_valid, move_file, get_available_sessions, get_script_price, get_script_description, get_script_image, get_script_file, create_db_connection, create_users_table, add_user_to_db, get_all_user_ids_from_db, update_script_price

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Инициализация бота и диспетчера ---
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot=bot, storage=storage)

# --- Подключение к базе данных и создание таблицы ---
conn = create_db_connection()
if conn:
    create_users_table(conn)
    conn.close()

# --- Состояния ---
class BuyItem(StatesGroup):
    choosing_item = State()
    waiting_for_payment = State()
    item_file = None  # Для хранения пути к файлу(скрипту) или имени сессии
    item_type = None  # для хранения типа item (session или script)
    invoice_id = None

class AdminPanel(StatesGroup):
    waiting_for_broadcast_text = State()
    waiting_for_admin_id = State()
    choosing_price_type = State() # Добавлено состояние для выбора типа цены
    waiting_for_session_price = State() # Добавлено состояние для ввода цены сессии
    confirm_session_price = State() # Добавлено состояние для подтверждения цены сессии
    choosing_script_folder = State() # Добавлено состояние для выбора папки скрипта
    waiting_for_script_price = State() # Добавлено состояние для ввода цены скрипта
    confirm_script_price = State() # Добавлено состояние для подтверждения цены скрипта
    current_script_folder = None #  Для хранения имени папки скрипта

# --- Проверка на админа ---
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# --- Создание инвойса Crypto Bot ---
async def create_crypto_bot_invoice(amount: float, description: str) -> str:
    try:
        url = f"{CRYPTO_BOT_API_URL}createInvoice"
        params = {
            "asset": CRYPTO_BOT_CURRENCY,
            "amount": amount,
            "description": description,
            "expires_in": 3600
        }
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=params) as response:
                response.raise_for_status()
                data = await response.json()
                if data["ok"]:
                    return data["result"]["pay_url"]
                else:
                    logger.error(f"Ошибка при создании инвойса: {data}")
                    return None
    except aiohttp.ClientResponseError as e:
        logger.error(f"Ошибка при создании инвойса: {e}")
        return None
    except Exception as e:
        logger.exception(f"Ошибка при работе с Crypto Bot API: {e}")
        return None

# --- Проверка оплаты Crypto Bot ---
async def check_crypto_bot_payment(invoice_id: str) -> bool:
    try:
        url = f"{CRYPTO_BOT_API_URL}getInvoices"
        params = {
            "invoice_ids": invoice_id
        }
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as response:
                response.raise_for_status()
                data = await response.json()
                if data["ok"]:
                    invoices = data["result"]["items"]
                    if invoices:
                        invoice = invoices[0]
                        return invoice["status"] == "paid"
                    else:
                        logger.warning(f"Инвойс с ID {invoice_id} не найден.")
                        return False
                else:
                    logger.error(f"Ошибка при проверке инвойса: {data}")
                    return False
    except aiohttp.ClientResponseError as e:
        logger.error(f"Ошибка запроса к Crypto Bot API: {e}")
        return False
    except Exception as e:
        logger.exception(f"Ошибка при проверке платежа через Crypto Bot API")
        return False

# --- Проверка и отправка товара ---
async def check_payment_and_send_item(user_id: int, item_file: str, item_type: str, invoice_id: str, bot: Bot, state: FSMContext):
    try:
        max_attempts = 10
        delay = 10
        attempts = 0

        while attempts < max_attempts:
            attempts += 1
            logger.info(f"Попытка {attempts}/{max_attempts}: Проверка оплаты инвойса {invoice_id}...")
            payment_status = await check_crypto_bot_payment(invoice_id)

            if payment_status:
                logger.info(f"Оплата инвойса {invoice_id} подтверждена.")

                if item_type == "session":
                    move_file(item_file, SESSION_DIR, SELL_DIR)  # Перемещаем сессию в папку проданных
                    try:
                        document = FSInputFile(os.path.join(SELL_DIR, item_file))
                        await bot.send_message(user_id, "Спасибо за покупку! Сессия отправлена вам:", parse_mode=ParseMode.HTML)
                        await bot.send_document(user_id, document=document)
                    except Exception as e:
                        logger.exception(f"Не удалось отправить сессию пользователю {user_id}: {e}")
                elif item_type == "script":
                    try:
                        script_path = item_file
                        script_file = get_script_file(script_path)

                        if script_file:
                            document = FSInputFile(script_file)
                            await bot.send_message(user_id, "Спасибо за покупку! Архив со скриптом отправлен вам:", parse_mode=ParseMode.HTML)
                            await bot.send_document(user_id, document=document)  # Отправляем архив
                        else:
                            await bot.send_message(user_id, "К сожалению, архив скрипта не найден.", parse_mode=ParseMode.HTML)
                    except Exception as e:
                        logger.exception(f"Не удалось отправить архив скрипта пользователю {user_id}: {e}")
                else:
                    await bot.send_message(user_id, "Ошибка: Неизвестный тип товара.", parse_mode=ParseMode.HTML)

                await state.clear()
                return

            else:
                logger.info(f"Оплата инвойса {invoice_id} еще не подтверждена. Пауза {delay} секунд...")
                await asyncio.sleep(delay)

        logger.warning(f"Время ожидания оплаты инвойса {invoice_id} истекло.")
        await bot.send_message(user_id, "Время оплаты истекло, или оплата не была подтверждена. Попробуйте еще раз.", parse_mode=ParseMode.HTML)

        await state.clear()
    except Exception as e:
        logger.exception(f"Ошибка в check_payment_and_send_item: {e}")

# --- Обработчики ---
@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        add_user_to_db(user_id)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Купить", callback_data="buy")],
            [InlineKeyboardButton(text="О боте", callback_data="about")]  # Кнопка "О боте"
        ])
        await message.reply("Добро пожаловать в магазин!", reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"Ошибка в start: {e}")

@dp.callback_query(lambda c: c.data == "about")
async def about(callback_query: CallbackQuery):
    try:
        await bot.answer_callback_query(callback_query.id)
        about_text = ("Это бот для покупки сессий Telethon и скриптов.\n"
                      "Чтобы купить, нажмите кнопку 'Купить'.")
        await bot.send_message(callback_query.from_user.id, about_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"Ошибка в about: {e}")

@dp.callback_query(lambda c: c.data == "buy")
async def buy(callback_query: CallbackQuery, state: FSMContext):
    try:
        await bot.answer_callback_query(callback_query.id)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Сессию", callback_data="buy_session")],
            [InlineKeyboardButton(text="Скрипт", callback_data="buy_script")]
        ])
        await bot.send_message(callback_query.from_user.id, "Что вы хотите купить?", reply_markup=keyboard, parse_mode=ParseMode.HTML)
        await state.set_state(BuyItem.choosing_item)
    except Exception as e:
        logger.exception(f"Ошибка в buy: {e}")

@dp.callback_query(lambda c: c.data == "buy_session", BuyItem.choosing_item)
async def choose_session(callback_query: CallbackQuery, state: FSMContext):
    try:
        await bot.answer_callback_query(callback_query.id)
        available_sessions = await get_available_sessions(SESSION_DIR)
        if not available_sessions:
            await bot.send_message(callback_query.from_user.id, "Нет доступных сессий для продажи.", parse_mode=ParseMode.HTML)
            await state.clear()
            return

        keyboard_buttons = []
        for session_file in available_sessions:
            keyboard_buttons.append([InlineKeyboardButton(text=session_file, callback_data=f"session_{session_file}")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

        await bot.send_message(callback_query.from_user.id, "Выберите сессию для покупки:", reply_markup=keyboard, parse_mode=ParseMode.HTML)
        await state.update_data(item_type="session")  # запоминаем тип товара
    except Exception as e:
        logger.exception(f"Ошибка в choose_session: {e}")

@dp.callback_query(lambda c: c.data.startswith("session_"), BuyItem.choosing_item)
async def process_session_choice(callback_query: CallbackQuery, state: FSMContext):
    try:
        await bot.answer_callback_query(callback_query.id)
        session_file = callback_query.data.split("_")[1]  # извлекаем имя файла сессии
        # Проверяем сессию на работоспособность
        if not await is_session_valid(session_file):
            await bot.send_message(callback_query.from_user.id, "К сожалению, выбранная сессия неработоспособна. Пожалуйста, выберите другую.", parse_mode=ParseMode.HTML)
            move_file(session_file, SESSION_DIR, INVALID_DIR)
            return

        invoice_url = await create_crypto_bot_invoice(SESSION_PRICE, f"Покупка сессии {session_file}")

        if invoice_url:
            try:  # Пытаемся получить invoice_id с помощью urllib.parse
                parsed_url = urllib.parse.urlparse(invoice_url)
                invoice_id = urllib.parse.parse_qs(parsed_url.query)['start'][0]  # Извлекаем значение параметра 'start'
            except Exception as e:
                logger.exception(f"Не удалось извлечь invoice_id из URL: {invoice_url}")
                await callback_query.message.reply("Произошла ошибка при обработке счета. Попробуйте позже.", parse_mode=ParseMode.HTML)
                return

            pay_button = InlineKeyboardButton(text="Оплатить", url=invoice_url)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[pay_button]])

            await bot.send_message(callback_query.from_user.id, f"Для покупки сессии {session_file}, оплатите {SESSION_PRICE} {CRYPTO_BOT_CURRENCY}:\n{invoice_url}", reply_markup=keyboard, parse_mode=ParseMode.HTML)

            await state.set_state(BuyItem.waiting_for_payment)
            await state.update_data(item_file=session_file, item_type="session", invoice_id=invoice_id)  # запоминаем имя файла, тип и ID инвойса

            asyncio.create_task(check_payment_and_send_item(callback_query.from_user.id, session_file, "session", invoice_id, bot, state))  # запускаем проверку оплаты
        else:
            await bot.send_message(callback_query.from_user.id, "Произошла ошибка при создании счета. Попробуйте позже.", parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.exception(f"Ошибка в process_session_choice: {e}")

@dp.callback_query(lambda c: c.data == "buy_script", BuyItem.choosing_item)
async def choose_script(callback_query: CallbackQuery, state: FSMContext):
    try:
        await bot.answer_callback_query(callback_query.id)
        script_folders = [f.path for f in os.scandir(SCRIPTS_DIR) if f.is_dir()]

        if not script_folders:
            await bot.send_message(callback_query.from_user.id, "Нет доступных скриптов для продажи.", parse_mode=ParseMode.HTML)
            await state.clear()
            return

        keyboard_buttons = []  # Создаем пустой список для кнопок

        for script_path in script_folders:
            script_name = os.path.basename(script_path)
            keyboard_buttons.append([InlineKeyboardButton(text=script_name, callback_data=f"script_{script_name}")])  # Добавляем кнопку в список

        keyboard_buttons.append([InlineKeyboardButton(text="Назад", callback_data="buy")])  # Добавляем кнопку "Назад"

        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)  # Передаем список списков кнопок

        await bot.send_message(callback_query.from_user.id, "Выберите скрипт для покупки:", reply_markup=keyboard, parse_mode=ParseMode.HTML)
        await state.update_data(item_type="script")
    except Exception as e:
        logger.exception(f"Ошибка в choose_script: {e}")

@dp.callback_query(lambda c: c.data.startswith("script_"), BuyItem.choosing_item)
async def process_script_choice(callback_query: CallbackQuery, state: FSMContext):
    try:
        await bot.answer_callback_query(callback_query.id)
        script_name = callback_query.data.split("_")[1]
        script_path = os.path.join(SCRIPTS_DIR, script_name)

        price = get_script_price(script_path)
        description = get_script_description(script_path)
        image_path = get_script_image(script_path)

        if price is None:
            await bot.send_message(callback_query.from_user.id, "К сожалению, цена скрипта не определена.", parse_mode=ParseMode.HTML)
            return

        if description:
            await bot.send_message(callback_query.from_user.id, f"Описание: {description}", parse_mode=ParseMode.HTML)

        if image_path:
            try:
                photo = FSInputFile(image_path)  # Используем FSInputFile
                await bot.send_photo(callback_query.from_user.id, photo=photo)
            except Exception as e:
                logger.exception(f"Не удалось отправить фото скрипта: {e}")

        invoice_url = await create_crypto_bot_invoice(price, f"Покупка скрипта {script_name}")

        if invoice_url:
            try:  # Пытаемся получить invoice_id с помощью urllib.parse
                parsed_url = urllib.parse.urlparse(invoice_url)
                invoice_id = urllib.parse.parse_qs(parsed_url.query)['start'][0]  # Извлекаем значение параметра 'start'
            except Exception as e:
                logger.exception(f"Не удалось извлечь invoice_id из URL: {invoice_url}")
                await callback_query.message.reply("Произошла ошибка при обработке счета. Попробуйте позже.", parse_mode=ParseMode.HTML)
                return

            pay_button = InlineKeyboardButton(text="Оплатить", url=invoice_url)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[pay_button]])

            await bot.send_message(callback_query.from_user.id, f"Для покупки скрипта {script_name}, оплатите {price} {CRYPTO_BOT_CURRENCY}:\n{invoice_url}", reply_markup=keyboard, parse_mode=ParseMode.HTML)

            await state.set_state(BuyItem.waiting_for_payment)
            await state.update_data(item_file=script_path, item_type="script", invoice_id=invoice_id)

            asyncio.create_task(check_payment_and_send_item(callback_query.from_user.id, script_path, "script", invoice_id, bot, state))
        else:
            await bot.send_message(callback_query.from_user.id, "Произошла ошибка при создании счета. Попробуйте позже.", parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.exception(f"Ошибка в process_script_choice: {e}")

# --- Admin Panel ---
@dp.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        if not is_admin(user_id):
            await message.reply("У вас нет прав для доступа к админ-панели.", parse_mode=ParseMode.HTML)
            return

        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Рассылка")],
                [KeyboardButton(text="Добавить админа")],
                [KeyboardButton(text="Изменить цену")] # Добавлена кнопка "Изменить цену"
            ],
            resize_keyboard=True
        )
        await message.reply("Добро пожаловать в админ-панель!", reply_markup=keyboard, parse_mode=ParseMode.HTML)
        await state.clear()  # Сбрасываем состояние
    except Exception as e:
        logger.exception(f"Ошибка в admin_panel: {e}")

@dp.message(lambda message: message.text == "Рассылка")
async def broadcast_command(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        if not is_admin(user_id):
            await message.reply("У вас нет прав для выполнения этой команды.", parse_mode=ParseMode.HTML)
            return

        await message.reply("Введите текст для рассылки:", reply_markup=types.ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        await state.set_state(AdminPanel.waiting_for_broadcast_text)
    except Exception as e:
        logger.exception(f"Ошибка в broadcast_command: {e}")

@dp.message(AdminPanel.waiting_for_broadcast_text)
async def process_broadcast_text(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        if not is_admin(user_id):
            await message.reply("У вас нет прав для выполнения этой команды.", parse_mode=ParseMode.HTML)
            return

        broadcast_text = message.text
        user_ids = get_all_user_ids_from_db()

        success_count = 0
        fail_count = 0
        for user_id in user_ids:
            try:
                await bot.send_message(user_id, broadcast_text, parse_mode=ParseMode.HTML)
                success_count += 1
                await asyncio.sleep(0.1)  # Ограничение скорости отправки
            except Exception as e:
                logger.exception(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
                fail_count += 1

        await message.reply(f"Рассылка завершена. Успешно отправлено: {success_count}, не удалось: {fail_count}.", parse_mode=ParseMode.HTML)
        await state.clear()  # Сбрасываем состояние
    except Exception as e:
        logger.exception(f"Ошибка в process_broadcast_text: {e}")

@dp.message(lambda message: message.text == "Добавить админа")
async def add_admin_command(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        if not is_admin(user_id):
            await message.reply("У вас нет прав для выполнения этой команды.", parse_mode=ParseMode.HTML)
            return

        await message.reply("Введите ID нового админа:", reply_markup=types.ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        await state.set_state(AdminPanel.waiting_for_admin_id)
    except Exception as e:
        logger.exception(f"Ошибка в add_admin_command: {e}")

@dp.message(AdminPanel.waiting_for_admin_id)
async def process_admin_id(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        if not is_admin(user_id):
            await message.reply("У вас нет прав для выполнения этой команды.", parse_mode=ParseMode.HTML)
            return

        try:
            new_admin_id = int(message.text)
        except ValueError:
            await message.reply("Некорректный ID пользователя. Введите число.", parse_mode=ParseMode.HTML)
            return

        if new_admin_id in ADMIN_IDS:
            await message.reply("Этот пользователь уже является админом.", parse_mode=ParseMode.HTML)
            return
        try:
            ADMIN_IDS.append(new_admin_id)
        except NameError:
            await message.reply("Похоже, ADMIN_IDS не определен как список. Проверьте config.py", parse_mode=ParseMode.HTML)
            return
        # Не нужно ничего записывать в файл, ADMIN_IDS хранится в памяти

        await message.reply(f"Пользователь с ID {new_admin_id} добавлен в список админов.", parse_mode=ParseMode.HTML)
        await state.clear()  # Сбрасываем состояние
    except Exception as e:
        logger.exception(f"Ошибка в process_admin_id: {e}")

@dp.message(lambda message: message.text == "Изменить цену")
async def choose_price_type(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        if not is_admin(user_id):
            await message.reply("У вас нет прав для выполнения этой команды.", parse_mode=ParseMode.HTML)
            return

        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Сессий")],
                [KeyboardButton(text="Скрипты")]
            ],
            resize_keyboard=True
        )
        await message.reply("Выберите тип товара для изменения цены:", reply_markup=keyboard, parse_mode=ParseMode.HTML)
        await state.set_state(AdminPanel.choosing_price_type)
    except Exception as e:
        logger.exception(f"Ошибка в choose_price_type: {e}")

@dp.message(lambda message: message.text == "Сессий", AdminPanel.choosing_price_type)
async def set_session_price(message: Message, state: FSMContext):
    try:
        await message.reply("Введите цену для всех сессий:", reply_markup=types.ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        await state.set_state(AdminPanel.waiting_for_session_price)
    except Exception as e:
        logger.exception(f"Ошибка в set_session_price: {e}")

@dp.message(AdminPanel.waiting_for_session_price)
async def process_session_price(message: Message, state: FSMContext):
    try:
        new_price = message.text
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Да")],
                [KeyboardButton(text="Нет")]
            ],
            resize_keyboard=True
        )
        await state.update_data(new_session_price=new_price)
        await message.reply(f"Вы уверены, что хотите изменить цену сессий на {new_price}?", reply_markup=keyboard, parse_mode=ParseMode.HTML)
        await state.set_state(AdminPanel.confirm_session_price)
    except Exception as e:
        logger.exception(f"Ошибка в process_session_price: {e}")

@dp.message(lambda message: message.text == "Да", AdminPanel.confirm_session_price)
async def confirm_session_price(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        new_price = data.get('new_session_price')
        if new_price is None:
            await message.reply("Произошла ошибка. Попробуйте еще раз.", parse_mode=ParseMode.HTML)
            await state.clear()
            return

        try:
            with open(".env", "r") as f:
                lines = f.readlines()
            # Поиск строки с SESSION_PRICE и замена
            for i, line in enumerate(lines):
                if line.startswith("SESSION_PRICE="):
                    lines[i] = f"SESSION_PRICE={new_price}\n"
                    break
            else:
                logger.warning("Строка SESSION_PRICE не найдена в .env.")
            with open(".env", "w") as f:
                f.writelines(lines)

            # Обновляем значение SESSION_PRICE в config.py
            global SESSION_PRICE
            SESSION_PRICE = float(new_price)

            await message.reply("Цена сессий успешно изменена.", reply_markup=types.ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
            await state.clear()
        except Exception as e:
            logger.exception(f"Ошибка при записи в файл .env: {e}")
            await message.reply("Произошла ошибка при изменении цены.", parse_mode=ParseMode.HTML)
            await state.clear()
    except Exception as e:
        logger.exception(f"Ошибка в confirm_session_price: {e}")

@dp.message(lambda message: message.text == "Нет", AdminPanel.confirm_session_price)
async def cancel_session_price(message: Message, state: FSMContext):
    try:
        # Восстанавливаем цену сессий из config.py
        try:
            with open(".env", "r") as f:
                lines = f.readlines()
            # Поиск строки с SESSION_PRICE и замена
            for i, line in enumerate(lines):
                if line.startswith("SESSION_PRICE="):
                    lines[i] = f"SESSION_PRICE={SESSION_PRICE}\n"
                    break
            else:
                logger.warning("Строка SESSION_PRICE не найдена в .env.")
            with open(".env", "w") as f:
                f.writelines(lines)
        except Exception as e:
            logger.exception(f"Ошибка при записи в файл .env: {e}")
            await message.reply("Произошла ошибка при отмене изменения цены.", parse_mode=ParseMode.HTML)
            await state.clear()
            return

        await message.reply("Изменение цены сессий отменено. Цена возвращена к исходной.", reply_markup=types.ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        await state.clear()
    except Exception as e:
        logger.exception(f"Ошибка в cancel_session_price: {e}")

@dp.message(lambda message: message.text == "Скрипты", AdminPanel.choosing_price_type)
async def choose_script_folder(message: Message, state: FSMContext):
    try:
        script_folders = [f.name for f in os.scandir(SCRIPTS_DIR) if f.is_dir()]

        if not script_folders:
            await message.reply("Нет доступных папок со скриптами.", parse_mode=ParseMode.HTML)
            await state.clear()
            return

        keyboard_buttons = []
        for folder_name in script_folders:
            keyboard_buttons.append([KeyboardButton(text=folder_name)])

        keyboard = ReplyKeyboardMarkup(keyboard=keyboard_buttons, resize_keyboard=True)

        await message.reply("Выберите папку скрипта:", reply_markup=keyboard, parse_mode=ParseMode.HTML)
        await state.set_state(AdminPanel.choosing_script_folder)
    except Exception as e:
        logger.exception(f"Ошибка в choose_script_folder: {e}")

@dp.message(AdminPanel.choosing_script_folder)
async def set_script_price(message: Message, state: FSMContext):
    try:
        script_folder = message.text
        script_path = os.path.join(SCRIPTS_DIR, script_folder)
        if not os.path.isdir(script_path):
            await message.reply("Выбрана некорректная папка.", parse_mode=ParseMode.HTML)
            return

        await state.update_data(current_script_folder=script_folder)
        await message.reply(f"Введите цену для скрипта в папке {script_folder}:", reply_markup=types.ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
        await state.set_state(AdminPanel.waiting_for_script_price)
    except Exception as e:
        logger.exception(f"Ошибка в set_script_price: {e}")

@dp.message(AdminPanel.waiting_for_script_price)
async def process_script_price(message: Message, state: FSMContext):
    try:
        new_price = message.text
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Да")],
                [KeyboardButton(text="Нет")]
            ],
            resize_keyboard=True
        )
        await state.update_data(new_script_price=new_price)
        await message.reply(f"Вы уверены, что хотите изменить цену скрипта на {new_price}?", reply_markup=keyboard, parse_mode=ParseMode.HTML)
        await state.set_state(AdminPanel.confirm_script_price)
    except Exception as e:
        logger.exception(f"Ошибка в process_script_price: {e}")

@dp.message(lambda message: message.text == "Да", AdminPanel.confirm_script_price)
async def confirm_script_price(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        new_price = data.get('new_script_price')
        script_folder = data.get('current_script_folder')

        if new_price is None or script_folder is None:
            await message.reply("Произошла ошибка. Попробуйте еще раз.", parse_mode=ParseMode.HTML)
            await state.clear()
            return

        try:
            script_path = os.path.join(SCRIPTS_DIR, script_folder)
            with open(os.path.join(script_path, "price.txt"), "w") as f:
                f.write(str(new_price))

            await message.reply("Цена скрипта успешно изменена.", reply_markup=types.ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
            await state.clear()

        except Exception as e:
            logger.exception(f"Ошибка при записи в файл price.txt: {e}")
            await message.reply("Произошла ошибка при изменении цены скрипта. Убедитесь, что папка и файл price.txt существуют.", parse_mode=ParseMode.HTML) # Более конкретное сообщение об ошибке
            await state.clear()

    except Exception as e:
        logger.exception(f"Ошибка в confirm_script_price: {e}")
        await message.reply("Произошла общая ошибка. Попробуйте еще раз.", parse_mode=ParseMode.HTML)
        await state.clear()

async def main():
    # Создаем необходимые папки
    os.makedirs(SESSION_DIR, exist_ok=True)
    os.makedirs(SELL_DIR, exist_ok=True)
    os.makedirs(INVALID_DIR, exist_ok=True)
    os.makedirs(SCRIPTS_DIR, exist_ok=True)

    # Подключаемся к базе данных (если нужно)
    conn = create_db_connection()
    if conn:
        create_users_table(conn)
        conn.close()

    # Запускаем бота
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.exception(f"Ошибка при запуске бота: {e}")

if __name__ == "__main__":
    asyncio.run(main())