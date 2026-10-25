import asyncio
import logging
import sqlite3
import os
import json
import secrets
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

BOT_TOKEN = "8652645802:AAGzn4Ubjhx3TozhM4_rklmu-opk5f9V0p4"
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

BASE_ALPHABET = list("АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
DIGITS = list("0123456789")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "cipher_bot.db")

class BotStates(StatesGroup):
    waiting_for_cipher_name = State()
    waiting_for_setup = State()
    waiting_for_single_setup = State()
    waiting_for_encrypt = State()
    waiting_for_decrypt = State()
    waiting_for_import_code = State()

def get_main_menu_keyboard(active_name="Не выбран"):
    builder = ReplyKeyboardBuilder()
    builder.button(text="🔒 Зашифровать текст")
    builder.button(text="🔓 Расшифровать текст")
    builder.button(text="📋 Посмотреть текущий шифр")
    builder.button(text="⚙️ Управление шифрами")
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)

def get_cipher_management_inline(ciphers_list, active_name):
    builder = InlineKeyboardBuilder()
    active_name = active_name or "Не выбран"
    for name in ciphers_list:
        status = "🟢 " if name == active_name else "⚪ "
        builder.button(text=f"{status}{name}", callback_data=f"select_cipher:{name}")
        builder.button(text="✏️", callback_data=f"edit_menu:{name}")
        builder.button(text="❌", callback_data=f"delete_cipher:{name}")
    builder.button(text="➕ Создать новый", callback_data="create_new_cipher")
    builder.button(text="📥 Импортировать одноразовый код", callback_data="import_cipher_start")
    layout = []
    for _ in ciphers_list: layout.append(3)
    layout.append(1)
    layout.append(1)
    builder.adjust(*layout)
    return builder.as_markup()

def get_edit_choice_inline(cipher_name, use_spaces=0, use_digits=0):
    builder = InlineKeyboardBuilder()
    space_status = "🟢 Вкл" if use_spaces else "⚪ Выкл"
    digit_status = "🟢 Вкл" if use_digits else "⚪ Выкл"
    builder.button(text="🔄 Перенастроить полностью", callback_data=f"setup_all:{cipher_name}")
    builder.button(text="✏️ Изменить один символ", callback_data=f"setup_one:{cipher_name}")
    builder.button(text=f"🌌 Пробелы: {space_status}", callback_data=f"toggle_spaces:{cipher_name}")
    builder.button(text=f"🔢 Цифры: {digit_status}", callback_data=f"toggle_digits:{cipher_name}")
    builder.button(text="📤 Получить ОДНОРАЗОВЫЙ код", callback_data=f"export_cipher:{cipher_name}")
    builder.button(text="⬅️ Назад", callback_data="back_to_management")
    builder.adjust(1)
    return builder.as_markup()

def get_alphabet_inline(cipher_name, alphabet_list):
    builder = InlineKeyboardBuilder()
    for char in alphabet_list:
        display_char = "Пробел" if char == " " else char
        builder.button(text=display_char, callback_data=f"edit_letter:{cipher_name}:{char}")
    builder.button(text="⬅️ Назад", callback_data=f"edit_menu:{cipher_name}")
    builder.adjust(6)
    return builder.as_markup()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cipher (
            user_id INTEGER, cipher_name TEXT, source_char TEXT, target_char TEXT,
            PRIMARY KEY (user_id, cipher_name, source_char)
        )""")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_cipher (
            user_id INTEGER PRIMARY KEY, cipher_name TEXT
        )""")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shared_ciphers (
            token TEXT PRIMARY KEY, cipher_name TEXT, mapping_json TEXT
        )""")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cipher_settings (
            user_id INTEGER, cipher_name TEXT, use_spaces INTEGER DEFAULT 0, use_digits INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, cipher_name)
        )""")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_groups (
            user_id INTEGER PRIMARY KEY, group_id INTEGER
        )""")
    conn.commit()
    conn.close()

def get_cipher_settings(user_id: int, cipher_name: str) -> tuple:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT use_spaces, use_digits FROM cipher_settings WHERE user_id = ? AND cipher_name = ?", (user_id, cipher_name))
    row = cursor.fetchone()
    conn.close()
    return row if row else (0, 0)

def save_cipher_settings(user_id: int, cipher_name: str, use_spaces: int, use_digits: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO cipher_settings (user_id, cipher_name, use_spaces, use_digits) VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, cipher_name) DO UPDATE SET use_spaces=excluded.use_spaces, use_digits=excluded.use_digits
    """, (user_id, cipher_name, use_spaces, use_digits))
    conn.commit()
    conn.close()

def link_user_group(user_id: int, group_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO user_groups (user_id, group_id) VALUES (?, ?)", (user_id, group_id))
    conn.commit()
    conn.close()

def get_user_linked_group(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT group_id FROM user_groups WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def get_cipher_alphabet(user_id: int, cipher_name: str) -> list:
    use_spaces, use_digits = get_cipher_settings(user_id, cipher_name)
    full_list = list(BASE_ALPHABET)
    if use_spaces: full_list.append(" ")
    if use_digits: full_list.extend(DIGITS)
    return full_list

def create_share_token(cipher_name: str, mapping_dict: dict, settings_tuple: tuple) -> str:
    token = "SHARE-" + secrets.token_hex(8).upper()
    payload = {"name": cipher_name, "mapping": mapping_dict, "settings": settings_tuple}
    mapping_json = json.dumps(payload, ensure_ascii=False)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO shared_ciphers (token, cipher_name, mapping_json) VALUES (?, ?, ?)", (token, cipher_name, mapping_json))
    conn.commit()
    conn.close()
    return token

def consume_share_token(token: str) -> tuple:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT cipher_name, mapping_json FROM shared_ciphers WHERE token = ?", (token,))
    row = cursor.fetchone()
    if row:
        cursor.execute("DELETE FROM shared_ciphers WHERE token = ?", (token,))
        conn.commit()
    conn.close()
    if row:
        data = json.loads(row[1])
        return data.get("name"), data.get("mapping"), data.get("settings")
    return None, None, None

def get_user_ciphers_list(user_id: int) -> list:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT cipher_name FROM cipher WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_active_cipher_name(user_id: int) -> str:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT cipher_name FROM active_cipher WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def set_active_cipher(user_id: int, cipher_name: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO active_cipher (user_id, cipher_name) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET cipher_name = excluded.cipher_name
    """, (user_id, cipher_name))
    conn.commit()
    conn.close()

def is_target_char_used(user_id: int, cipher_name: str, target: str, current_source: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 1 FROM cipher 
        WHERE user_id = ? AND cipher_name = ? AND target_char = ? AND source_char != ?
    """, (user_id, cipher_name, target, current_source))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def save_char_mapping(user_id: int, cipher_name: str, source: str, target: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO cipher (user_id, cipher_name, source_char, target_char) VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, cipher_name, source_char) DO UPDATE SET target_char = excluded.target_char
    """, (user_id, cipher_name, source, target))
    conn.commit()
    conn.close()

def get_user_cipher(user_id: int, cipher_name: str) -> dict:
    if not cipher_name: return {}
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT source_char, target_char FROM cipher WHERE user_id = ? AND cipher_name = ?", (user_id, cipher_name))
    rows = cursor.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

def clear_entire_cipher(user_id: int, cipher_name: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cipher WHERE user_id = ? AND cipher_name = ?", (user_id, cipher_name))
    conn.commit()
    conn.close()

def delete_cipher_profile(user_id: int, cipher_name: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cipher WHERE user_id = ? AND cipher_name = ?", (user_id, cipher_name))
    cursor.execute("DELETE FROM active_cipher WHERE user_id = ? AND cipher_name = ?", (user_id, cipher_name))
    cursor.execute("DELETE FROM cipher_settings WHERE user_id = ? AND cipher_name = ?", (user_id, cipher_name))
    conn.commit()
    conn.close()

# === ХЕНДЛЕРЫ МЕНЮ, ОБМЕНА И ШИФРОВАНИЯ ===

@dp.message(Command("start", "menu"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    active = get_active_cipher_name(message.from_user.id) or "Не выбран"
    await message.answer(f"Привет! Я бот-шифровальщик.\n🔥 Сейчас выбран шифр: **{active}**\nВыбери действие на панели ниже:", reply_markup=get_main_menu_keyboard(active), parse_mode="Markdown")

@dp.message(F.text == "📋 Посмотреть текущий шифр")
async def view_cipher(message: types.Message):
    active_name = get_active_cipher_name(message.from_user.id)
    user_cipher = get_user_cipher(message.from_user.id, active_name)
    if not user_cipher:
        await message.answer("⚠️ У тебя нет активного шифра! Зайди в '⚙️ Управление шифрами'.")
        return
    alphabet = get_cipher_alphabet(message.from_user.id, active_name)
    lines = [f"**{'Пробел' if c == ' ' else c}** ➡️ `{user_cipher[c]}`" for c in alphabet if c in user_cipher]
    await message.answer(f"📋 **Текущий шифр ({active_name}):**\n\n" + "\n".join(lines), parse_mode="Markdown")

@dp.message(F.text == "⚙️ Управление шифрами")
async def cipher_management_menu(message: types.Message, state: FSMContext):
    await state.clear()
    ciphers = get_user_ciphers_list(message.from_user.id)
    active = get_active_cipher_name(message.from_user.id)
    await message.answer("⚙️ **Управление профилями шифров**\n\n🟢 — Активный\n✏️ — Редактировать\n❌ — Удалить", reply_markup=get_cipher_management_inline(ciphers, active), parse_mode="Markdown")

@dp.callback_query(F.data == "back_to_management")
async def back_to_management_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    ciphers = get_user_ciphers_list(callback.from_user.id)
    active = get_active_cipher_name(callback.from_user.id)
    await callback.message.edit_text("⚙️ **Управление профилями шифров**", reply_markup=get_cipher_management_inline(ciphers, active), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("select_cipher:"))
async def select_cipher_callback(callback: types.CallbackQuery):
    name = callback.data.split(":")[1]
    set_active_cipher(callback.from_user.id, name)
    ciphers = get_user_ciphers_list(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=get_cipher_management_inline(ciphers, name))
    await callback.message.answer(f"🟢 Шифр **{name}** успешно выбран основным!", parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_cipher:"))
async def delete_cipher_callback(callback: types.CallbackQuery):
    name = callback.data.split(":")[1]
    delete_cipher_profile(callback.from_user.id, name)
    ciphers = get_user_ciphers_list(callback.from_user.id)
    active = get_active_cipher_name(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=get_cipher_management_inline(ciphers, active))
    await callback.message.answer(f"❌ Шифр **{name}** полностью удален.", parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_menu:"))
async def edit_menu_callback(callback: types.CallbackQuery):
    name = callback.data.split(":")[1]
    sp, dg = get_cipher_settings(callback.from_user.id, name)
    await callback.message.edit_text(f"Редактирование шифра: **{name}**\nЧто именно ты хочешь сделать?", reply_markup=get_edit_choice_inline(name, sp, dg), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("toggle_spaces:"))
async def toggle_spaces_callback(callback: types.CallbackQuery):
    name = callback.data.split(":")[1]
    sp, dg = get_cipher_settings(callback.from_user.id, name)
    new_sp = 0 if sp else 1
    save_cipher_settings(callback.from_user.id, name, new_sp, dg)
    await callback.message.edit_reply_markup(reply_markup=get_edit_choice_inline(name, new_sp, dg))
    await callback.answer()

@dp.callback_query(F.data.startswith("toggle_digits:"))
async def toggle_digits_callback(callback: types.CallbackQuery):
    name = callback.data.split(":")[1]
    sp, dg = get_cipher_settings(callback.from_user.id, name)
    new_dg = 0 if dg else 1
    save_cipher_settings(callback.from_user.id, name, sp, new_dg)
    await callback.message.edit_reply_markup(reply_markup=get_edit_choice_inline(name, sp, new_dg))
    await callback.answer()

@dp.callback_query(F.data == "create_new_cipher")
async def create_new_cipher_callback(callback: types.CallbackQuery, state: FSMContext):
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer("✏️ Введи **название** для нового шифра:", parse_mode="Markdown")
    await state.set_state(BotStates.waiting_for_cipher_name)
    await callback.answer()

@dp.callback_query(F.data.startswith("export_cipher:"))
async def export_cipher_callback(callback: types.CallbackQuery):
    name = callback.data.split(":")[1]
    cipher_dict = get_user_cipher(callback.from_user.id, name)
    if not cipher_dict:
        await callback.message.answer("⚠️ Этот шифр пустой, им нельзя поделиться.")
        await callback.answer()
        return
    settings = get_cipher_settings(callback.from_user.id, name)
    one_time_token = create_share_token(name, cipher_dict, settings)
    await callback.message.answer(f"📤 **ОДНОРАЗОВЫЙ код для импорта шифра '{name}':**\n\n`{one_time_token}`\n\nСкопируй этот код кликом.", parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "import_cipher_start")
async def import_cipher_start_callback(callback: types.CallbackQuery, state: FSMContext):
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer("📥 Отправь мне **одноразовый код**, полученный от друга:")
    await state.set_state(BotStates.waiting_for_import_code)
    await callback.answer()

@dp.message(BotStates.waiting_for_import_code)
async def process_imported_code(message: types.Message, state: FSMContext):
    if message.text in ["🔒 Зашифровать текст", "🔓 Расшифровать текст", "📋 Посмотреть текущий шифр", "⚙️ Управление шифрами"]:
        await state.clear()
        if message.text == "⚙️ Управление шифрами": await cipher_management_menu(message, state)
        return
    token = message.text.strip()
    name, mapping, settings = consume_share_token(token)
    if not name or not mapping:
        await message.answer("❌ Код неверный, устарел или уже был кем-то использован! Попробуй ввести другой код:")
        return
    if name in get_user_ciphers_list(message.from_user.id): name = f"{name}_импорт"
    for src, target in mapping.items(): save_char_mapping(message.from_user.id, name, src, target)
    if settings: save_cipher_settings(message.from_user.id, name, settings[0], settings[1])
    set_active_cipher(message.from_user.id, name)
    await state.clear()
    await message.answer(f"🎉 Шифр **{name}** успешно импортирован!", reply_markup=get_main_menu_keyboard(name), parse_mode="Markdown")

@dp.message(Command("reg"))
async def cmd_register_group(message: types.Message):
    if message.chat.type in ["group", "supergroup"]:
        link_user_group(message.from_user.id, message.chat.id)
        await message.reply("🔗 **Эта группа успешно привязана к твоему профилю!**\nТеперь ты можешь шифровать тексты в ЛС бота, и они будут отправляться сразу сюда.", parse_mode="Markdown")
    else:
        await message.answer("⚠️ Эту команду нужно писать внутри группового чата, который ты хочешь привязать.")

# === ХЕНДЛЕРЫ НАСТРОЙКИ, ЛС-ШИФРОВАНИЯ И ЗАПУСК БОТА ===

@dp.message(F.text == "🔒 Зашифровать текст")
async def start_encrypt_mode(message: types.Message, state: FSMContext):
    active = get_active_cipher_name(message.from_user.id)
    if not active or not get_user_cipher(message.from_user.id, active):
        await message.answer("⚠️ Сначала создай шифр в '⚙️ Управление шифрами'")
        return
    linked_group = get_user_linked_group(message.from_user.id)
    if linked_group:
        await message.answer(f"🛸 **Режим отправки в группу активирован.**\nВведи текст ниже, бот зашифрует его и отправит СРАЗУ в твою привязанную группу!")
    else:
        await message.answer(f"В режиме шифра '**{active}**'. Отправь мне текст:")
    await state.set_state(BotStates.waiting_for_encrypt)

@dp.message(BotStates.waiting_for_encrypt)
async def process_encryption(message: types.Message, state: FSMContext):
    if message.text in ["🔒 Зашифровать текст", "🔓 Расшифровать текст", "📋 Посмотреть текущий шифр", "⚙️ Управление шифрами"]:
        await state.clear()
        if message.text == "🔒 Зашифровать текст": await start_encrypt_mode(message, state)
        elif message.text == "🔓 Расшифровать текст": await start_decrypt_mode(message, state)
        elif message.text == "⚙️ Управление шифрами": await cipher_management_menu(message, state)
        elif message.text == "📋 Посмотреть текущий шифр": await view_cipher(message)
        return
    active = get_active_cipher_name(message.from_user.id)
    cipher = get_user_cipher(message.from_user.id, active)
    res = [cipher[c].lower() if c in cipher else (cipher[c.upper()].lower() if c.upper() in cipher else c) for c in message.text]
    final_crypt = "".join(res)
    linked_group = get_user_linked_group(message.from_user.id)
    if linked_group:
        try:
            await bot.send_message(chat_id=linked_group, text=f"🔒 **Шифр от {message.from_user.first_name}:**\n`{final_crypt}`", parse_mode="Markdown")
            await message.answer("🚀 **Успешно зашифровано и отправлено в группу чата!**")
        except Exception:
            await message.answer("❌ Ошибка отправки. Убедись, что бот добавлен в твою группу как Администратор.")
    else:
        await message.answer(f"🔒 **[{active}] Результат:**\n\n`{final_crypt}`", parse_mode="Markdown")
    await message.answer("Выбери следующее действие:", reply_markup=get_main_menu_keyboard(active))
    await state.clear()

@dp.message(F.text == "🔓 Расшифровать текст")
async def start_decrypt_mode(message: types.Message, state: FSMContext):
    active = get_active_cipher_name(message.from_user.id)
    if not active or not get_user_cipher(message.from_user.id, active):
        await message.answer("⚠️ Сначала создай шифр в '⚙️ Управление шифрами'")
        return
    await message.answer(f"В режиме расшифровки по шифру '**{active}**'. Отправь текст:")
    await state.set_state(BotStates.waiting_for_decrypt)

@dp.message(BotStates.waiting_for_decrypt)
async def process_decryption(message: types.Message, state: FSMContext):
    if message.text in ["🔒 Зашифровать текст", "🔓 Расшифровать текст", "📋 Посмотреть текущий шифр", "⚙️ Управление шифрами"]:
        await state.clear()
        if message.text == "🔒 Зашифровать текст": await start_encrypt_mode(message, state)
        elif message.text == "🔓 Расшифровать текст": await start_decrypt_mode(message, state)
        elif message.text == "⚙️ Управление шифрами": await cipher_management_menu(message, state)
        elif message.text == "📋 Посмотреть текущий шифр": await view_cipher(message)
        return
    active = get_active_cipher_name(message.from_user.id)
    rev = {v: k for k, v in get_user_cipher(message.from_user.id, active).items()}
    res = [rev[c].lower() if c in rev else (rev[c.upper()].lower() if c.upper() in rev else c) for c in message.text]
    await message.answer(f"🔓 **[{active}] Результат:**\n\n`{''.join(res)}`", parse_mode="Markdown")
    await message.answer("Выбери следующее действие:", reply_markup=get_main_menu_keyboard(active))
    await state.clear()

@dp.message(BotStates.waiting_for_cipher_name)
async def process_cipher_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if not name or len(name) > 20 or ":" in name:
        await message.answer("❌ Название должно быть не длиннее 20 символов и не содержать ':'. Попробуй снова:")
        return
    if name in get_user_ciphers_list(message.from_user.id):
        await message.answer("❌ Шифр с таким названием уже существует!")
        return
    save_cipher_settings(message.from_user.id, name, 0, 0)
    alphabet = get_cipher_alphabet(message.from_user.id, name)
    await state.update_data(cipher_name=name, current_index=0, active_alphabet=alphabet)
    first_char = alphabet[0]
    display_first = "Пробел" if first_char == " " else first_char
    await message.answer(f"Создаем шифр '{name}'.\nПридумай символ для буквы: **{display_first}**", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(BotStates.waiting_for_setup)

@dp.callback_query(F.data.startswith("setup_all:"))
async def setup_all_callback(callback: types.CallbackQuery, state: FSMContext):
    name = callback.data.split(":")[1]
    clear_entire_cipher(callback.from_user.id, name)
    alphabet = get_cipher_alphabet(callback.from_user.id, name)
    await state.update_data(cipher_name=name, current_index=0, active_alphabet=alphabet)
    try: await callback.message.delete()
    except Exception: pass
    src = alphabet[0]
    display_src = "Пробел" if src == " " else src
    await callback.message.answer(f"Шифр '{name}' сброшен.\nПридумай символ для: **{display_src}**", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(BotStates.waiting_for_setup)
    await callback.answer()

@dp.message(BotStates.waiting_for_setup)
async def process_setup_input(message: types.Message, state: FSMContext):
    if message.text in ["🔒 Зашифровать текст", "🔓 Расшифровать текст", "📋 Посмотреть текущий шифр", "⚙️ Управление шифрами"]:
        await state.clear()
        if message.text == "🔒 Зашифровать текст": await start_encrypt_mode(message, state)
        elif message.text == "🔓 Расшифровать текст": await start_decrypt_mode(message, state)
        elif message.text == "⚙️ Управление шифрами": await cipher_management_menu(message, state)
        elif message.text == "📋 Посмотреть текущий шифр": await view_cipher(message)
        return
    data = await state.get_data()
    idx, name, alphabet = data["current_index"], data["cipher_name"], data["active_alphabet"]
    src, val = alphabet[idx], message.text.strip()
    if len(val) != 1:
        display_src = "Пробел" if src == " " else src
        await message.answer(f"❌ Нужен ровно 1 символ. Попробуй еще раз для: **{display_src}**")
        return
    if is_target_char_used(message.from_user.id, name, val, src):
        await message.answer(f"❌ Символ '{val}' занят! Выбери другой:")
        return
    save_char_mapping(message.from_user.id, name, src, val)
    if idx + 1 < len(alphabet):
        await state.update_data(current_index=idx + 1)
        next_char = alphabet[idx + 1]
        display_next = "Пробел" if next_char == " " else next_char
        await message.answer(f"Принято! Теперь символ для: **{display_next}**")
    else:
        set_active_cipher(message.from_user.id, name)
        await state.clear()
        await message.answer(f"🎉 Шифр '{name}' настроен и активирован!", reply_markup=get_main_menu_keyboard(name))

@dp.callback_query(F.data.startswith("setup_one:"))
async def setup_one_callback(callback: types.CallbackQuery):
    name = callback.data.split(":")[1]
    alphabet = get_cipher_alphabet(callback.from_user.id, name)
    await callback.message.edit_text("Выбери символ для изменения:", reply_markup=get_alphabet_inline(name, alphabet))
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_letter:"))
async def edit_single_letter(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data.split(":")
    name, letter = data[1], data[2]
    await state.update_data(single_cipher_name=name, single_source_char=letter)
    try: await callback.message.delete()
    except Exception: pass
    display_letter = "Пробел" if letter == " " else letter
    await callback.message.answer(f"Введи новый символ для [**{display_letter}**] в шифре '{name}':", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(BotStates.waiting_for_single_setup)
    await callback.answer()

@dp.message(BotStates.waiting_for_single_setup)
async def process_single_setup(message: types.Message, state: FSMContext):
    data = await state.get_data()
    name, src, val = data["single_cipher_name"], data["single_source_char"], message.text.strip()
    if len(val) != 1:
        display_src = "Пробел" if src == " " else src
        await message.answer(f"❌ Нужен 1 символ. Попробуй снова для: **{display_src}**")
        return
    if is_target_char_used(message.from_user.id, name, val, src):
        await message.answer(f"❌ Символ '{val}' занят! Выбери другой:")
        return
    save_char_mapping(message.from_user.id, name, src, val)
    await state.clear()
    display_src = "Пробел" if src == " " else src
    await message.answer(f"✅ Для '{display_src}' установлен символ '{val}'!", reply_markup=get_main_menu_keyboard(name))

async def main():
    init_db()
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())