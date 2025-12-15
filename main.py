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
async def back_to_main_menu(callback: types.CallbackQuery):
    """Обробник для кнопки "Назад в меню"."""
    await callback.message.edit_text(
        "👋 **Вітаю в Stoic Trainer!**\n\n"
        "Обери режим для тренування духу:",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )
    await callback.answer() # Скидаємо статус "завантаження" з кнопки

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

# --- ЛОГІКА: STOIC GYM (ГРА) ---

@dp.callback_query(F.data == "mode_gym")
async def start_gym(callback: types.CallbackQuery):
    # Ініціалізуємо гру
    user_db[callback.from_user.id] = {"score": 0, "level": 1}

    # Створюємо кнопки
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Почати тренування", callback_data="game_start")
    builder.button(text="🔙 В меню", callback_data="back_home") # 👈 НОВА КНОПКА

    await callback.message.edit_text(
        "⚔️ **Stoic Gym | Гартування духу**\n\n"
        "Тобі буде запропоновано 40 щоденних ситуацій.\n"
        "Обери стоїчну реакцію, щоб набрати бали мудрості.\n"
        "Наберіть 400 балів, щоб стати Майстром Стоїком!",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()
    
# added handler Додаємо почати тренування 
@dp.callback_query(F.data == "game_start")
async def start_game_from_button(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    # Редагуємо повідомлення, щоб прибрати кнопку "Почати тренування"
    await callback.message.edit_text(
        "⚔️ **Тренування розпочато!**\n\nГотуйся до першої ситуації...",
        parse_mode="Markdown"
    )
    
    # Викликаємо функцію, яка відправить перший рівень
    await asyncio.sleep(1) 
    await send_level(user_id, callback.message)
    
    await callback.answer()

# --- ФУНКЦІЯ ДЛЯ ВІДПРАВКИ РІВНЯ ---
async def send_level(user_id, message_to_edit):
    user_data = user_db[user_id]
    current_level = user_data["level"]
    max_level = len(SCENARIOS)

    # Перевірка на перемогу (якщо рівень став більшим за максимальний)
    if current_level > max_level:
        # Логіка перемоги
        return

    scenario = SCENARIOS.get(current_level)
    scenario_text = f"🛡️ **Рівень {current_level}/{max_level}**\n\n" + scenario['text']

    # Створення клавіатури для поточного рівня
    builder = InlineKeyboardBuilder()
    for option in scenario['options']:
        # Важливо: використовуємо game_<option_id> для фільтрації
        builder.button(
            text=option['text'],
            callback_data=f"game_{option['id']}"
        )

    # --- КНОПКА "НАЗАД" ТУТ ---
    builder.button(text="🔙 В меню", callback_data="back_home") # 👈 ДОДАНО
    
    builder.adjust(1)

    await message_to_edit.edit_text(
        scenario_text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

# Цей хендлер ловить вибір варіантів у грі (усі callback-и, які не є системними)
# Переконайтеся, що back_to_main_menu() знаходиться ВИЩЕ у коді!
@dp.callback_query(lambda c: c.data not in ["back_home", "mode_quotes", "mode_memento", "game_start"])
async def handle_game_choice(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    # 1. Перевірка: чи є юзер в базі 
    if user_id not in user_db:
        await callback.answer("Почни спочатку через /start")
        return

    user_data = user_db[user_id]
    level_id = user_data["level"]
    
    # Якщо ми в процесі гри
    if level_id in SCENARIOS:
        scenario = SCENARIOS[level_id]
        choice_id = callback.data.replace("game_", "") # Прибираємо можливий префікс 'game_'
        
        # Шукаємо, яку опцію обрав юзер
        selected_option = next((opt for opt in scenario["options"] if opt["id"] == choice_id), None)
        
        if selected_option:
            # 2. Оновлюємо статс
            user_data["score"] += selected_option["score"]
            user_data["level"] += 1
            
            # Видаляємо кнопки і пишемо результат
            await callback.message.edit_text(
                f"{scenario['text']}\n\n✅ **Твій вибір:** {selected_option['text']}\n\n💡 *{selected_option['msg']}*",
                parse_mode="Markdown"
            )
            
            # 3. Чекаємо трохи і даємо наступний рівень
            await asyncio.sleep(2)
            
            max_level = len(SCENARIOS)
            
            if user_data["level"] > max_level:
                # ЛОГІКА ПЕРЕМОГИ
                final_score = user_data["score"]
                await callback.message.edit_text(
                    f"🏆 **ПЕРЕМОГА!** Ти завершив усі {max_level} рівнів!\n"
                    f"Твій фінальний рахунок: **{final_score}**\n"
                    f"«Бути стійким — означає керувати собою, а не світом.»",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]])
                )
                del user_db[user_id]
            else:
                await send_level(user_id, callback.message) # Передаємо message_to_edit
    
    await callback.answer()
    
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())