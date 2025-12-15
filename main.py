import asyncio
import logging
import random
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from datetime import datetime
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# Імпортуємо базу цитат з data.py
from data import STOIC_DB, SCENARIOS

# --- НАЛАШТУВАННЯ ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- FSM: СТАНИ ---
class MementoMori(StatesGroup):
    waiting_for_birthdate = State()

# Тимчасова база даних користувачів в пам'яті
user_db = {} 

# --- ІНІЦІАЛІЗАЦІЯ ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- КЛАВІАТУРИ ---

def get_main_menu():
    """Головне меню"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🧙‍♂️ Оракул (Цитати)", callback_data="mode_quotes")
    builder.button(text="⚔️ Stoic Gym (Гра)", callback_data="mode_gym")
    builder.button(text="⏳ Memento Mori (Час)", callback_data="mode_memento") # 👈 НОВА КНОПКА
    builder.adjust(1)
    return builder.as_markup()

def get_quote_keyboard():
    """Меню для цитат"""
    buttons = [
        [InlineKeyboardButton(text="🔄 Інша цитата", callback_data="refresh_quote")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ЛОГІКА: СТАРТ І МЕНЮ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 **Вітаю, мандрівнику.**\n\nЯ допоможу тобі знайти спокій та мудрість.\nОбери свій шлях:",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "back_home")
async def back_home(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "👋 **Головне меню.**\n\nОбери свій шлях:",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

# --- ЛОГІКА: ОРАКУЛ (ЦИТАТИ) ---

@dp.callback_query(F.data == "mode_quotes")
async def start_quotes(callback: types.CallbackQuery):
    await send_random_quote(callback)

@dp.callback_query(F.data == "refresh_quote")
async def refresh_quote(callback: types.CallbackQuery):
    await send_random_quote(callback)

async def send_random_quote(callback: types.CallbackQuery):
    quote = random.choice(STOIC_DB)
    text = f"📜 *{quote['category']}*\n\n_{quote['text']}_\n\n— {quote['author']}"
    
    # try/except на випадок, якщо випаде та сама цитата (Telegram не любить редагувати текст на той самий)
    try:
        await callback.message.edit_text(text, reply_markup=get_quote_keyboard(), parse_mode="Markdown")
    except Exception:
        await callback.answer("Це та сама цитата. Спробуй ще!")

# --- ЛОГІКА: STOIC GYM (ГРА) ---

@dp.callback_query(F.data == "mode_gym")
async def start_gym(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    # Скидаємо прогрес
    user_db[user_id] = {"score": 0, "level": 1}
    
    await callback.message.edit_text(
        "🏛 **Stoic Gym**\n\nТут ми гартуємо характер.\nОбирай дії мудро.",
        parse_mode="Markdown"
    )
    # Коротка пауза для ефекту
    await asyncio.sleep(1)
    await send_level(user_id)

async def send_level(user_id):
    user_data = user_db[user_id]
    level_id = user_data["level"]
    
    # Якщо рівні закінчились
    if level_id not in SCENARIOS:
        score = user_data["score"]
        verdict = "Справжній Стоїк 🏛" if score > 15 else "Учень початківець 👶"
        
        # Кнопка повернення в меню
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]])
        
        await bot.send_message(user_id, f"🏁 **Фініш!**\nТвій рахунок: {score}\nВердикт: {verdict}", reply_markup=kb)
        return

    scenario = SCENARIOS[level_id]
    
    # Створення кнопок
    builder = InlineKeyboardBuilder()
    for opt in scenario["options"]:
        builder.button(text=opt["text"], callback_data=opt["id"])
    builder.adjust(1)
    
    await bot.send_message(
        user_id, 
        f"⚔️ **Рівень {level_id}**\n\n{scenario['text']}", 
        reply_markup=builder.as_markup(), 
        parse_mode="Markdown"
    )

# Цей хендлер ловить вибір варіантів у грі (усі інші callback-и)
@dp.callback_query()
async def handle_game_choice(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    # Перевірка: чи є юзер в базі і чи не натиснув він щось ліве
    if user_id not in user_db:
        await callback.answer("Почни спочатку через /start")
        return

    user_data = user_db[user_id]
    level_id = user_data["level"]
    
    # Якщо ми в процесі гри
    if level_id in SCENARIOS:
        scenario = SCENARIOS[level_id]
        choice_id = callback.data
        
        # Шукаємо, яку опцію обрав юзер
        selected_option = next((opt for opt in scenario["options"] if opt["id"] == choice_id), None)
        
        if selected_option:
            # Оновлюємо статс
            user_data["score"] += selected_option["score"]
            user_data["level"] += 1
            
            # Видаляємо кнопки і пишемо результат
            await callback.message.edit_text(
                f"{scenario['text']}\n\n✅ **Твій вибір:** {selected_option['text']}\n\n💡 *{selected_option['msg']}*",
                parse_mode="Markdown"
            )
            
            # Чекаємо трохи і даємо наступний рівень
            await asyncio.sleep(2)
            await send_level(user_id)
    
    await callback.answer()
    
# --- ЛОГІКА: MEMENTO MORI (ТАЙМЕР ЖИТТЯ) ---

@dp.callback_query(F.data == "mode_memento")
async def start_memento(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "⏳ **Memento Mori**\n\n"
        "Щоб побачити свій таймер, введи дату народження.\n"
        "Можна повну: `24.08.1995`\n"
        "Або просто рік: `1995`", # 👈 Додали опцію
        parse_mode="Markdown"
    )
    # Переводимо бота в режим очікування
    await state.set_state(MementoMori.waiting_for_birthdate)

@dp.message(MementoMori.waiting_for_birthdate)
async def process_birthdate(message: types.Message, state: FSMContext):
    date_text = message.text.strip()
    birth_date = None
    
    # --- СПРОБА 1: Повна дата ---
    try:
        birth_date = datetime.strptime(date_text, "%d.%m.%Y")
    except ValueError:
        # --- СПРОБА 2: Тільки рік ---
        try:
            # Якщо ввели тільки рік, ставимо 1 січня цього року
            birth_date = datetime.strptime(date_text, "%Y")
        except ValueError:
            # Якщо ні те, ні інше не підійшло
            await message.answer("⚠️ Не розумію формат.\nНапиши просто рік (наприклад: `1998`) або дату (`24.08.1998`).")
            return # Зупиняємо функцію, не виходимо зі стану, чекаємо нове повідомлення

    # --- МАТЕМАТИКА ЖИТТЯ (Той самий код) ---
    AVG_LIFESPAN_YEARS = 80
    WEEKS_IN_YEAR = 52
    TOTAL_WEEKS = AVG_LIFESPAN_YEARS * WEEKS_IN_YEAR
    
    delta = datetime.now() - birth_date
    weeks_lived = delta.days // 7
    
    percentage = (weeks_lived / TOTAL_WEEKS) * 100
    
    if percentage > 100:
        percentage = 100
        
    total_blocks = 20
    filled_blocks = int((percentage / 100) * total_blocks)
    empty_blocks = total_blocks - filled_blocks
    
    progress_bar = "▓" * filled_blocks + "░" * empty_blocks
    
    result_text = (
        f"📅 **Точка відліку:** {birth_date.year} рік\n\n" # Показуємо тільки рік для краси
        f"⏳ **Твій життєвий шлях (80 років):**\n"
        f"`{progress_bar}` {percentage:.1f}%\n\n"
        f"🔹 Прожито тижнів: **{weeks_lived}**\n"
        f"🔸 Залишилось тижнів: **{int(TOTAL_WEEKS - weeks_lived)}**\n\n"
        f"💡 *«Життя довге, якщо знаєш, як його прожити.» — Сенека*"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]])
    
    await message.answer(result_text, reply_markup=kb, parse_mode="Markdown")
    
    # Виходимо зі стану очікування
    await state.clear()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())