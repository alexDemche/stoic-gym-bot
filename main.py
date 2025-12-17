import asyncio
import logging
import random
import os
from dotenv import load_dotenv
from db import Database
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from urllib.parse import quote

# Імпортуємо базу цитат з data.py
from data import STOIC_DB, SCENARIOS, HELP_TEXT

# --- НАЛАШТУВАННЯ ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- FSM: СТАНИ ---
class MementoMori(StatesGroup):
    waiting_for_birthdate = State()
    
class FeedbackState(StatesGroup):
    waiting_for_message = State()

# Тимчасова база даних користувачів в пам'яті
# user_db = {} 
# db = Database('stoic.db')
db = Database()

# --- ІНІЦІАЛІЗАЦІЯ ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- КЛАВІАТУРИ ---
def get_main_menu():
    """Головне меню"""
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Мій Профіль", callback_data="mode_profile")
    builder.button(text="🧙‍♂️ Оракул (Цитати)", callback_data="mode_quotes")
    builder.button(text="⚔️ Stoic Gym (Гра)", callback_data="mode_gym")
    builder.button(text="⏳ Memento Mori (Час)", callback_data="mode_memento")
    builder.button(text="🏆 Топ Стоїків", callback_data="mode_top")
    
    builder.button(text="✉️ Написати автору", callback_data="send_feedback")
    builder.button(text="📚 Допомога", callback_data="show_help")
    builder.adjust(2, 2, 2, 2) # по 2 кнопки в ряд
    return builder.as_markup()

def get_quote_keyboard():
    """Меню для цитат"""
    buttons = [
        [InlineKeyboardButton(text="🔄 Інша цитата", callback_data="refresh_quote")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ЛОГІКА ПРОФІЛЮ ТА РАНГІВ ---

def get_stoic_rank(score):
    """Визначає звання на основі балів"""
    if score < 50:
        return "👶 Початківець"
    elif score < 150:
        return "📚 Учень"
    elif score < 300:
        return "🛡️ Практик"
    elif score < 500:
        return "🦉 Філософ"
    else:
        return "👑 Стоїчний Мудрець"

@dp.callback_query(F.data == "mode_profile")
async def show_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    # 1. Отримуємо дані з бази
    score, level = await db.get_stats(user_id)
    birth_date = await db.get_birthdate(user_id)
    
    # 2. Визначаємо ранг
    rank = get_stoic_rank(score)
    
    # 3. Формуємо текст
    # Вираховуємо прогрес до наступного рангу (для краси)
    next_rank_score = 500
    if score < 50: next_rank_score = 50
    elif score < 150: next_rank_score = 150
    elif score < 300: next_rank_score = 300
    elif score < 500: next_rank_score = 500
    
    progress_bar = ""
    if score < 500:
        needed = next_rank_score - score
        progress_bar = f"\n📈 До підвищення: ще **{needed}** балів"
    else:
        progress_bar = "\n🌟 Ти досяг вершини мудрості!"

    # Перевірка Memento
    memento_status = "✅ Встановлено" if birth_date else "❌ Не налаштовано"

    text = (
        f"👤 **Особиста справа Стоїка**\n\n"
        f"🏷️ Ім'я: **{callback.from_user.first_name}**\n"
        f"🏅 Звання: **{rank}**\n"
        f"💎 Бали мудрості: **{score}**\n"
        f"{progress_bar}\n\n"
        f"⚔️ Рівень в Gym: **{level}**\n"
        f"⏳ Memento Mori: **{memento_status}**"
    )

    # --- ФОРМУВАННЯ ПОСИЛАННЯ ДЛЯ ШЕРІНГУ ---
    bot_username = "StoicTrainer_ua_bot" # ⚠️ Заміни на юзернейм свого бота без @
    share_text = f"🏛 Я досяг звання «{rank}» ({score} балів) у Stoic Trainer!\nЧи зможеш ти мене перевершити?"
    
    # Кодуємо текст для URL
    share_url = f"https://t.me/share/url?url={f'https://t.me/{bot_username}'}&text={quote(share_text)}"

    # Додаємо кнопку URL
    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Похвалитися друзям", url=share_url)
    builder.button(text="🔙 В меню", callback_data="back_home")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

# --- ЛОГІКА: СТАРТ І МЕНЮ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Передаємо ID та Ім'я (first_name)
    user_name = message.from_user.first_name if message.from_user.first_name else "друже"
    await db.add_user(message.from_user.id, user_name)
    
    await message.answer(
        f"👋 **Вітаю, {user_name}!**\n\n"
        "🏛️ **Stoic Trainer** — це твій кишеньковий гід до стародавньої філософії **Стоїцизму**.\n"
        "Цей шлях допоможе тобі знайти **внутрішній спокій** та **стійкість** серед хаосу життя.\n"
        "Обери режим для тренування духу:",
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
    
# --- АДМІН-КОМАНДА ---
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    # Тут можна додати перевірку на твій ID, щоб цю команду міг викликати тільки ти
    # Наприклад: if message.from_user.id != ТВІЙ_ID: return
    
    count = await db.count_users()
    await message.answer(f"📊 **Статистика бота:**\n\n👤 Користувачів: **{count}**", parse_mode="Markdown")

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

def generate_memento_text(birth_date: datetime):
    """Генерує текст таймера життя на основі дати."""
    AVG_LIFESPAN_YEARS = 80
    WEEKS_IN_YEAR = 52
    TOTAL_WEEKS = AVG_LIFESPAN_YEARS * WEEKS_IN_YEAR
    
    delta = datetime.now() - birth_date
    weeks_lived = delta.days // 7
    
    percentage = (weeks_lived / TOTAL_WEEKS) * 100
    if percentage > 100: percentage = 100
        
    total_blocks = 20
    filled_blocks = int((percentage / 100) * total_blocks)
    empty_blocks = total_blocks - filled_blocks
    progress_bar = "▓" * filled_blocks + "░" * empty_blocks
    
    return (
        f"📅 **Точка відліку:** {birth_date.year} рік\n\n"
        f"⏳ **Твій життєвий шлях (80 років):**\n"
        f"`{progress_bar}` {percentage:.1f}%\n\n"
        f"🔹 Прожито тижнів: **{weeks_lived}**\n"
        f"🔸 Залишилось тижнів: **{int(TOTAL_WEEKS - weeks_lived)}**\n\n"
        f"💡 *«Життя довге, якщо знаєш, як його прожити.» — Сенека*"
    )
    
@dp.callback_query(F.data == "reset_memento")
async def reset_memento_date(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🔄 **Зміна дати**\n\n"
        "Введи нову дату народження (або рік):",
        parse_mode="Markdown"
    )
    await state.set_state(MementoMori.waiting_for_birthdate)
    await callback.answer()

#  Моменто морі логіка
@dp.callback_query(F.data == "mode_memento")
async def start_memento(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    # Отримуємо дату з бази (asyncpg повертає об'єкт datetime.date або None)
    saved_date = await db.get_birthdate(user_id)
    
    if saved_date:
        # ВАЖЛИВО: saved_date — це вже об'єкт date.
        birth_date = datetime(saved_date.year, saved_date.month, saved_date.day)
        
        text = generate_memento_text(birth_date)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Змінити дату", callback_data="reset_memento")],
            [InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]
        ])
        
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        # Якщо дати немає, просимо ввести
        await callback.message.edit_text(
            "⏳ **Memento Mori**\n\n"
            "Щоб побачити свій таймер, введи дату народження.\n"
            "Можна повну: `24.08.1995`\n"
            "Або просто рік: `1995`",
            parse_mode="Markdown"
        )
        await state.set_state(MementoMori.waiting_for_birthdate)
    
    await callback.answer()

@dp.message(MementoMori.waiting_for_birthdate)
async def process_birthdate(message: types.Message, state: FSMContext):
    date_text = message.text.strip()
    birth_date = None
    
    # Спроба 1: Повна дата
    try:
        birth_date = datetime.strptime(date_text, "%d.%m.%Y")
    except ValueError:
        # Спроба 2: Тільки рік
        try:
            birth_date = datetime.strptime(date_text, "%Y")
        except ValueError:
            await message.answer("⚠️ Не розумію формат.\nНапиши просто рік (наприклад: `1998`) або дату (`24.08.1998`).")
            return 

    # --- ЗБЕРЕЖЕННЯ В БАЗУ ---
    # Зберігаємо у форматі РРРР-ММ-ДД (стандарт для баз даних)
    # Передаємо об'єкт date(), драйвер сам перетворить його у формат SQL
    await db.set_birthdate(message.from_user.id, birth_date.date())

    # Генеруємо текст через нашу нову функцію
    result_text = generate_memento_text(birth_date)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Змінити дату", callback_data="reset_memento")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]
    ])
    
    await message.answer(result_text, reply_markup=kb, parse_mode="Markdown")
    await state.clear()

# --- ЛОГІКА: STOIC GYM (ГРА) ---

@dp.callback_query(F.data == "mode_gym")
async def start_gym(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    # Оновлюємо ім'я при вході в гру
    await db.add_user(user_id, callback.from_user.first_name)
    
    # Отримуємо поточний прогрес
    score, level = await db.get_stats(user_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Продовжити тренування", callback_data="game_start")
    
    if level > 1 or score > 0: # Показуємо кнопку, тільки якщо є прогрес
        builder.button(text="🔄 Почати заново", callback_data="reset_gym_confirm")
        
    builder.button(text="🔙 В меню", callback_data="back_home")

    builder.adjust(1)
    await callback.message.edit_text(
        f"⚔️ **Stoic Gym | Рівень {level}**\n\n"
        f"🏆 Твій рахунок: **{score}**\n"
        "Продовжуй свій шлях до мудрості.",
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
    
# added leaderboard callback
@dp.callback_query(F.data == "mode_top")
async def show_leaderboard(callback: types.CallbackQuery):
    top_users = await db.get_top_users(10)

    text = "🏆 **Алея Слави Стоїків**\n\n"

    if not top_users:
        text += "Поки що ніхто не набрав балів. Будь першим!"
    else:
        for i, (name, score) in enumerate(top_users, start=1):
            # Медальки для перших трьох
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🔹"
            
            # визначення рангу
            rank_emoji = get_stoic_rank(score).split()[0] # Беремо тільки смайлик (👶, 🦉 тощо)
            
            # Якщо ім'я немає в базі (старі юзери), пишемо "Невідомий Стоїк"
            safe_name = name if name else "Невідомий Стоїк"
            
            # Формат: 🥇 1. Ім'я (🦉) — 350 балів
            text += f"{medal} {i}. **{safe_name}** ({rank_emoji}) — {score}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()
    
# --- НОВИЙ ХЕНДЛЕР: ПЕРЕХІД ДО НАСТУПНОГО РІВНЯ ---
@dp.callback_query(F.data == "game_next")
async def go_to_next_level(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    # Викликаємо функцію, яка відобразить наступний рівень
    # send_level сам бере поточний рівень з бази даних
    await send_level(user_id, callback.message)
    
    await callback.answer()

# --- ФУНКЦІЯ ДЛЯ ВІДПРАВКИ РІВНЯ ---
async def send_level(user_id, message_to_edit):
    # Отримуємо дані з БД
    score, current_level = await db.get_stats(user_id)
    max_level = len(SCENARIOS)

    # Перевірка на перемогу (якщо рівень став більшим за максимальний)
    if current_level > max_level:
        # Логіка перемоги
        return

    scenario = SCENARIOS.get(current_level)
    # 1. КОПІЮВАННЯ ТА ПЕРЕМІШУВАННЯ
    options = scenario['options'].copy()
    random.shuffle(options)
    
    scenario_text = f"🛡️ **Рівень {current_level}/{max_level}**\n\n" + scenario['text']
    
    # Створення клавіатури для поточного рівня
    builder = InlineKeyboardBuilder()
    for option in options:
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
    
# Додаємо команду /help
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    # Використовуємо змінну з data.py
    await message.answer(HELP_TEXT, parse_mode="Markdown")
   
# хендлер, який буде ловити callback_data="show_help" 
@dp.callback_query(F.data == "show_help")
async def show_help_callback(callback: types.CallbackQuery):
    # Використовуємо змінну з data.py
    await callback.message.edit_text(
        HELP_TEXT, 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]]), 
        parse_mode="Markdown"
    )
    await callback.answer()

# додаємо функці. скинути прогрес
@dp.callback_query(F.data == "reset_gym_confirm")
async def confirm_reset(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так, скинути все", callback_data="reset_gym_final")
    builder.button(text="❌ Ні, повернутися", callback_data="mode_gym")
    
    await callback.message.edit_text(
        "⚠️ **Увага!** Ти впевнений, що хочеш скинути свій прогрес?\n"
        "Твій рахунок і рівень будуть обнулені.",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "reset_gym_final")
async def reset_gym(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    # Скидаємо в базі: score=0, level=1
    await db.update_game_progress(user_id, 0, 1) 
    
    await callback.message.edit_text(
        "✅ **Прогрес скинуто!**\n\n"
        "Твій шлях стоїка починається знову. Натисни 'Почати тренування'.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Почати тренування", callback_data="game_start")],
            [InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()

# Цей хендлер ловить вибір варіантів у грі (усі callback-и, які не є системними)
# Переконайтеся, що back_to_main_menu() знаходиться ВИЩЕ у коді!
@dp.callback_query(lambda c: c.data and c.data.startswith('game_') and c.data not in ["game_next"]) # Додаємо фільтр "game_next"
async def handle_game_choice(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    current_score, current_level = await db.get_stats(user_id)
    
    if current_level in SCENARIOS:
        scenario = SCENARIOS[current_level]
        choice_id = callback.data.replace("game_", "")
        
        selected_option = next((opt for opt in scenario["options"] if opt["id"] == choice_id), None)
        
        if selected_option:
            points_change = selected_option["score"]
            new_score = current_score + points_change
            new_level = current_level + 1
            
            # --- Оновлення бази даних відбувається тут ---
            await db.update_game_progress(user_id, new_score, new_level)
            
            # Визначаємо фідбек
            if points_change > 0:
                score_feedback = f"🟢 **+{points_change} балів мудрості**"
            elif points_change < 0:
                score_feedback = f"🔴 **{points_change} балів (Не стоїчно)**"
            else:
                score_feedback = f"⚪ **0 балів**"

            # 1. СТВОРЕННЯ КЛАВІАТУРИ ДЛЯ ПРОДОВЖЕННЯ
            kb = InlineKeyboardBuilder()
            
            max_level = len(SCENARIOS)
            
            if new_level > max_level:
                # 2. ЛОГІКА ПЕРЕМОГИ
                final_score = new_score
                
                await callback.message.edit_text(
                    f"🏆 **ПЕРЕМОГА!** Ти завершив усі {max_level} рівнів!\n"
                    f"Твій фінальний рахунок: **{final_score}**\n"
                    f"«Невдача — це ціна навчання, успіх — це результат практики.»",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]])
                )
            else:
                # 3. КНОПКИ "ПРОДОВЖИТИ" / "В МЕНЮ"
                kb.button(text="🔙 В меню", callback_data="back_home")
                kb.button(text="▶️ Продовжити", callback_data="game_next")
                kb.adjust(2)
                
                await callback.message.edit_text(
                    f"{scenario['text']}\n\n✅ **Твій вибір:** {selected_option['text']}\n\n"
                    f"{score_feedback}\n\n"
                    f"💡 *{selected_option['msg']}*",
                    reply_markup=kb.as_markup(),
                    parse_mode="Markdown"
                )
            
            # Видаляємо стару паузу
            # await asyncio.sleep(4) 
            # await send_level(user_id, callback.message) # Це тепер робить game_next
    
    await callback.answer()
    
# --- Розсилка повідомлень юзерам ---
async def send_daily_quote():
    """Розсилає випадкову цитату всім користувачам"""
    users = await db.get_all_users()
    
    if not users:
        return

    # Вибираємо випадкову цитату
    quote = random.choice(STOIC_DB)
    text = f"☀️ **Мудрість на сьогодні:**\n\n_{quote['text']}_\n\n— {quote['author']}\n\n👉 /start — Пройти тренування"

    count = 0
    for user_id in users:
        try:
            await bot.send_message(user_id, text, parse_mode="Markdown")
            count += 1
            # Робимо маленьку паузу, щоб Telegram не заблокував за спам (ліміти)
            await asyncio.sleep(0.05) 
        except Exception as e:
            # Користувач міг заблокувати бота
            logging.error(f"Не вдалося надіслати повідомлення користувачу {user_id}: {e}")
            
    logging.info(f"✅ Розсилка завершена. Отримали: {count} користувачів.")

    
async def main():
    # ... (ініціалізація бота, диспетчера, роутера)
    
    # 1. ПІДКЛЮЧЕННЯ ДО БАЗИ ДАНИХ АСИНХРОННО
    await db.connect()
    await db.create_tables() # Створюємо таблиці після підключення
    
    # --- ПЛАНУВАЛЬНИК (SCHEDULER) ---
    scheduler = AsyncIOScheduler()
    
    # Додаємо задачу: запускати send_daily_quote щодня о 9:00 ранку
    # timezone="Europe/Kyiv" бажано вказати, якщо сервер в іншому часовому поясі,
    # але поки можна залишити за замовчуванням (UTC). 
    # Якщо Railway в UTC, то 9:00 UTC = 11:00 або 12:00 за Києвом.
    # Давай поставимо 7:00 UTC (це 9:00 або 10:00 за Києвом)
    scheduler.add_job(send_daily_quote, trigger='cron', hour=7, minute=30)
    
    scheduler.start()
    
    # 2. ЗАПУСК БОТА
    await dp.start_polling(bot)
    
# --- АДМІН-КОМАНДА: РОЗСИЛКА ---
# Використання: /broadcast Текст повідомлення
@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    ADMIN_ID = 7597463225
    if message.from_user.id != ADMIN_ID: return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Помилка. Використання: `/broadcast Ваш текст`")
        return

    broadcast_text = f"📢 **Оголошення:**\n\n{parts[1]}"
    
    users = await db.get_all_users()
    count = 0
    
    await message.answer(f"⏳ Починаю розсилку на {len(users)} користувачів...")
    
    for user_id in users:
        try:
            await bot.send_message(user_id, broadcast_text, parse_mode="Markdown")
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass # Ігноруємо помилки (наприклад, юзер заблокував бота)
            
    await message.answer(f"✅ Розсилка завершена! Успішно: {count}")

# --- ЛОГІКА ЗВОРОТНОГО ЗВ'ЯЗКУ ---

@dp.callback_query(F.data == "send_feedback")
async def start_feedback(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "✉️ **Зв'язок з розробником**\n\n"
        "Напиши своє повідомлення (відгук, ідею або знайдену помилку) і я передам його автору.\n\n"
        "👇 *Чекаю на твій текст:*",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="back_home")]]),
        parse_mode="Markdown"
    )
    await state.set_state(FeedbackState.waiting_for_message)
    await callback.answer()

@dp.message(FeedbackState.waiting_for_message)
async def process_feedback(message: types.Message, state: FSMContext):
    user_text = message.text
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    # ID адміна
    ADMIN_ID = 7597463225 
    
    # 1. Відправляємо повідомлення (адміну)
    try:
        admin_text = (
            f"📨 **Новий відгук!**\n"
            f"👤 Від: {user_name} (`{user_id}`)\n\n"
            f"💬 Текст:\n{user_text}"
        )
        await bot.send_message(ADMIN_ID, admin_text, parse_mode="Markdown")
        
        # 2. Відповідаємо користувачу
        await message.answer(
            "✅ **Повідомлення відправлено!**\nДякую за твій внесок у розвиток проекту.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]]),
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer("⚠️ Сталася помилка при відправці. Спробуй пізніше.")
        logging.error(f"Feedback error: {e}")
        
    await state.clear()

if __name__ == "__main__":
    # db = Database() # Цей рядок прибрати!
    # потрібно ініціалізувати db = Database() як глобальну змінну, а потім викликати main()
    asyncio.run(main())