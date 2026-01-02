import asyncio
import logging
import os
import random
from datetime import datetime
from urllib.parse import quote

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.session.aiohttp import AiohttpSession # Для таймаутів
from aiogram.exceptions import TelegramBadRequest        # Для обробки помилок
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from utils import get_stoic_rank

from academy_service import format_article
from ai_service import get_stoic_advice
# Імпортуємо базу цитат з data.py
from data import HELP_TEXT, SCENARIOS, STOIC_DB
from db import Database

# --- НАЛАШТУВАННЯ ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")


# --- FSM: СТАНИ ---
class MementoMori(StatesGroup):
    waiting_for_birthdate = State()


class FeedbackState(StatesGroup):
    waiting_for_message = State()


class JournalState(StatesGroup):
    waiting_for_entry = State()


class MentorState(StatesGroup):
    chatting = State()  # Стан активного діалогу з ШІ


# Тимчасова база даних користувачів в пам'яті
# user_db = {}
# db = Database('stoic.db')
db = Database()

# --- ІНІЦІАЛІЗАЦІЯ ---
logging.basicConfig(level=logging.INFO)
# Додаємо сесію з таймаутом у 60 секунд
# session = AiohttpSession(timeout=60)
# bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()


# --- КЛАВІАТУРИ ---
def get_main_menu():
    """Головне меню"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⚔️ Stoic Gym (Гра)", callback_data="mode_gym")

    builder.button(text="📖 Академія (Теорія)", callback_data="mode_academy")
    
    builder.button(text="🤖 Ментор (AI)", callback_data="mode_ai")
    builder.button(text="🧘‍♂️ Lab (Лабараторні)", url="https://t.me/StoicTrainerLab_ua_bot")

    builder.button(text="🧙‍♂️ Оракул (Цитати)", callback_data="mode_quotes")
    builder.button(text="⏳ Memento Mori (Час)", callback_data="mode_memento")

    builder.button(text="👤 Мій Профіль", callback_data="mode_profile")
    builder.button(text="🏆 Топ Стоїків", callback_data="mode_top")
    
    builder.button(text="📚 Допомога", callback_data="show_help")
    builder.button(text="✉️ Написати автору", callback_data="send_feedback")

    builder.adjust(1, 1, 2, 2, 2, 2)
    return builder.as_markup()


def get_quote_keyboard():
    """Меню для цитат"""
    buttons = [
        [InlineKeyboardButton(text="🔄 Інша цитата", callback_data="refresh_quote")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- ЛОГІКА ПРОФІЛЮ ТА РАНГІВ ---


@dp.callback_query(F.data == "mode_profile")
async def show_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    # 1. Отримуємо дані гри (Gym)
    score, level, name = await db.get_stats(user_id)
    birth_date = await db.get_birthdate(user_id)
    energy = await db.check_energy(user_id)

    # 2. Отримуємо дані навчання (Академія)
    # academy_count - кількість статей, academy_rank - назва класу
    academy_count, academy_rank = await db.get_academy_progress(user_id)

    # 3. Визначаємо ігрове звання (Gym)
    game_rank = get_stoic_rank(score)

    # 4. Прогрес-бар до наступного ігрового звання (ОНОВЛЕНО)
    # Створюємо словник порогів, щоб не писати купу if/else
    thresholds = [50, 150, 500, 1000, 2500, 5000]
    next_rank_score = 0

    # Шукаємо найближчу мету
    for t in thresholds:
        if score < t:
            next_rank_score = t
            break

    progress_msg = ""
    if next_rank_score > 0:
        needed = next_rank_score - score
        progress_msg = f" (ще {needed} до підвищення)"
    else:
        # Якщо більше 5000
        progress_msg = " (MAX LEVEL 👑)"

    memento_status = "✅ Активно" if birth_date else "❌ Не налаштовано"

    # 5. Формуємо красивий текст
    text = (
        f"👤 **Особиста справа Стоїка**\n"
        f"🏷️ Ім'я: **{name}**\n\n"
        f"⚔️ **STOIC GYM (Практика)**\n"
        f"🏅 Звання: **{game_rank}**\n"
        f"💎 Бали мудрості: **{score}**{progress_msg}\n"
        f"🏔️ Пройдено рівнів: **{level - 1}**\n"
        f"⚡ Енергія: **{energy}/5**\n\n"
        f"🎓 **АКАДЕМІЯ (Теорія)**\n"
        f"🏫 Клас: **{academy_rank}**\n"
        f"📚 Пройдено уроків: **{academy_count}**\n\n"
        f"⏳ Memento Mori: **{memento_status}**"
    )

    # --- ФОРМУВАННЯ КНОПОК ---
    bot_username = "StoicTrainer_ua_bot"
    share_text = (
        f"🏛 Мій прогрес у Stoic Trainer:\n"
        f"⚔️ Практика: {game_rank} ({score} балів)\n"
        f"🎓 Теорія: {academy_rank}\n"
        f"Спробуй і ти!"
    )
    share_url = f"https://t.me/share/url?url={f'https://t.me/{bot_username}'}&text={quote(share_text)}"

    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Записати думку", callback_data="journal_write")
    builder.button(text="📜 Мої роздуми", callback_data="journal_view")
    builder.button(text="📢 Похвалитися", url=share_url)
    builder.button(text="🔙 В меню", callback_data="back_home")
    builder.adjust(1)

    try:
        await callback.message.edit_text(
            text, reply_markup=builder.as_markup(), parse_mode="Markdown"
        )
    except Exception as e:
        # Якщо текст не змінився або повідомлення видалене - просто ігноруємо помилку
        logging.error(f"Помилка при редагуванні профілю: {e}")

    # Спроба відповісти на кнопку (найважливіше місце для "query is too old")
    try:
        await callback.answer()
    except TelegramBadRequest:
        # Якщо запит застарів (бот спав) - просто пишемо в лог і не "падаємо"
        logging.info("Запит профілю застарів, ігноруємо.")

# --- ЛОГІКА: СТАРТ І МЕНЮ ---


@dp.message(Command("start"))
async def cmd_start(message: types.Message, bot: Bot):
    # Передаємо ID та Ім'я (first_name)
    user_name = (
        message.from_user.first_name if message.from_user.first_name else "друже"
    )
    await db.add_user(message.from_user.id, user_name)

    await message.answer(
        f"👋 **Вітаю, {user_name}!**\n\n"
        "🏛️ **Stoic Trainer** — це твій кишеньковий гід до стародавньої філософії **Стоїцизму**.\n"
        "Цей шлях допоможе тобі знайти **внутрішній спокій** та **стійкість** серед хаосу життя.\n"
        "Обери режим для тренування духу:",
        reply_markup=get_main_menu(),
        parse_mode="Markdown",
    )


@dp.callback_query(F.data == "back_home")
async def back_to_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()  # <-- ВАЖЛИВО: Виходимо з будь-якого режиму (ШІ, гра, фідбек)
    """Обробник для кнопки "Назад в меню"."""
    try:
        await callback.message.edit_text(
            "👋 **Вітаю в Stoic Trainer!**\n\nОбери режим для тренування духу:",
            reply_markup=get_main_menu(),
            parse_mode="Markdown",
        )
    except Exception:
        pass # Якщо повідомлення вже таке саме, ігноруємо

    # ЗАХИЩЕНИЙ ВАРІАНТ ВІДПОВІДІ НА КНОПКУ:
    try:
        await callback.answer()
    except TelegramBadRequest:
        # Якщо бот лагав 5 хвилин, просто ігноруємо цей старий запит
        logging.info("Старий запит ігноровано")

# --- АДМІН-КОМАНДА ---
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    # Тут можна додати перевірку на твій ID, щоб цю команду міг викликати тільки ти
    # Наприклад: if message.from_user.id != ТВІЙ_ID: return

    count = await db.count_users()
    await message.answer(
        f"📊 **Статистика бота:**\n\n👤 Користувачів: **{count}**", parse_mode="Markdown"
    )


# --- ЛОГІКА: Академія Стоїцизму (Теорія) ---

async def render_article(callback: types.CallbackQuery, article, user_id):
    """Універсальна функція відображення статті з контролем лімітів та довжини тексту"""
    is_read = await db.is_article_read(user_id, article['id'])
    # count, rank = await db.get_academy_progress(user_id) # Можна розкоментувати, якщо треба в тексті
    daily_count = await db.get_daily_academy_count(user_id)
    
    # Отримуємо основний текст
    full_text = format_article(article)
    limit_info = f"\n\n📊 Сьогодні засвоєно: **{daily_count}/5** уроків."
    
    # Виправляємо помилку MESSAGE_TOO_LONG
    final_text = full_text + limit_info
    if len(final_text) > 4000:
        final_text = final_text[:3990] + "...\n\n*(Текст скорочено через ліміти Telegram)*"

    kb = InlineKeyboardBuilder()
    
    # --- ЛОГІКА КНОПКИ "НАСТУПНИЙ" ---
    # Якщо ліміт вичерпано і стаття ще не читана, кнопка веде на відпочинок
    if daily_count >= 5 and not is_read:
        next_callback = "academy_limit_reached"
        next_text = "➡️ (Відпочинок)"
    else:
        next_callback = f"academy_nav_next_{article['day']}_{article['month']}"
        next_text = "➡️ Наступний"

    if is_read:
        kb.button(text="🌟 Вже вивчено", callback_data="academy_already_done")
    else:
        kb.button(text="Зарахувати урок (+1 бал)", callback_data=f"academy_read_{article['id']}")
        
    kb.button(text="⬅️ Минулий", callback_data=f"academy_nav_prev_{article['day']}_{article['month']}")
    kb.button(text=next_text, callback_data=next_callback)
    
    kb.button(text="🔙 В меню", callback_data="back_home")
    kb.button(text="📚 Бібліотека", callback_data="library_page_0")
    kb.adjust(1, 2, 2)
    
    try:
        await callback.message.edit_text(
            final_text, 
            reply_markup=kb.as_markup(), 
            parse_mode="Markdown"
        )
    except Exception:
        pass

@dp.callback_query(F.data == "mode_academy")
async def show_academy_article(callback: types.CallbackQuery):
    now = datetime.now()
    article = await db.get_article_by_date(now.day, now.month)
    if article:
        await render_article(callback, article, callback.from_user.id)
    else:
        await callback.answer("Сьогоднішня сторінка Академії ще пуста.", show_alert=True)
    await callback.answer()

@dp.callback_query(F.data.startswith("academy_nav_"))
async def navigate_academy(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    direction = parts[2]
    current_day = int(parts[3])
    current_month = int(parts[4])

    from datetime import date, timedelta
    # Використовуємо 2024 рік для коректної роботи календаря
    try:
        current_date = date(2024, current_month, current_day)
        if direction == "next":
            new_date = current_date + timedelta(days=1)
        else:
            new_date = current_date - timedelta(days=1)
        
        new_day, new_month = new_date.day, new_date.month
        article = await db.get_article_by_date(new_day, new_month)

        if article:
            await render_article(callback, article, callback.from_user.id)
        else:
            await callback.answer("Цієї сторінки ще немає в архівах.", show_alert=True)
    except Exception as e:
        logging.error(f"Navigation error: {e}")
        await callback.answer("Помилка навігації.")
    await callback.answer()

@dp.callback_query(F.data == "academy_already_done")
async def handle_already_read(callback: types.CallbackQuery):
    await callback.answer("Ти вже засвоїв цей урок! Мудрість назавжди з тобою. 🤝", show_alert=False)

@dp.callback_query(F.data == "academy_limit_reached")
async def handle_limit_reached_nav(callback: types.CallbackQuery):
    # Скорочений текст (максимум 200 символів для alert)
    text = (
        "Ти засвоїв 5 уроків сьогодні! ✨\n\n"
        "Стоїки кажуть: знання мають «прорости» всередині нас, а для цього потрібен спокій.\n\n"
        "Відпочинь, і завтра продовжимо! 🏛️"
    )
    await callback.answer(text, show_alert=True)

@dp.callback_query(F.data.startswith("academy_read_"))
async def handle_read_article(callback: types.CallbackQuery):
    article_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    daily_count = await db.get_daily_academy_count(user_id)
    if daily_count >= 5:
        # Використовуємо той самий лояльний текст
        await handle_limit_reached_nav(callback)
        return

    is_new = await db.mark_article_as_read(user_id, article_id)
    article = await db.get_article_by_id(article_id)
    
    if article:
        # Отримуємо оновлені дані після запису
        new_count, rank = await db.get_academy_progress(user_id)
        new_daily = await db.get_daily_academy_count(user_id)
        
        await render_article(callback, article, user_id)
        
        if is_new:
            # ДЕТАЛЬНИЙ АЛЕРТ ІЗ ЗАГАЛЬНОЮ КІЛЬКІСТЮ
            await callback.answer(
                f"🎉 Урок зараховано!\n\n"
                f"📚 Всього вивчено: {new_count}\n"
                f"📊 За сьогодні: {new_daily}/5\n"
                f"🎓 Твій клас: {rank}", 
                show_alert=True
            )
    else:
        await callback.answer("Архів: статті немає.")
        
# --- ЛОГІКА: БІБЛІОТЕКА (АРХІВ) ---

# --- ОНОВЛЕНИЙ ХЕНДЛЕР БІБЛІОТЕКИ ---

@dp.callback_query(F.data.startswith("library_page_"))
async def show_library_page(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    try:
        page = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        page = 0

    LIMIT = 10
    offset = page * LIMIT
    
    # Дістаємо дані з бази
    articles = await db.get_user_library(user_id, limit=LIMIT, offset=offset)
    total_count = await db.count_user_library(user_id)
    
    import math
    total_pages = math.ceil(total_count / LIMIT)
    if total_pages == 0: total_pages = 1

    if not articles:
        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 В Академію", callback_data="mode_academy")
        
        # Спроба відредагувати текст (якщо бот "прокинувся" після лагу)
        try:
            await callback.message.edit_text(
                "📚 **Моя Бібліотека**\n\nТут поки що пусто. Вивчи свій перший урок!", 
                reply_markup=kb.as_markup(),
                parse_mode="Markdown"
            )
        except Exception:
            pass

        # Відповідаємо на кнопку (захищено)
        try:
            await callback.answer()
        except TelegramBadRequest:
            logging.info("Запит порожньої бібліотеки застарів")
        return

    text = (
        f"📚 **Бібліотека** (Стор. {page + 1}/{total_pages})\n"
        f"Всього записів: **{total_count}**\n\n"
        f"👇 *Натисни, щоб відкрити:*",
    )
    
    kb = InlineKeyboardBuilder()
    
    for art in articles:
        title = art['title']
        if len(title) > 25: 
            title = title[:23] + ".."
            
        btn_text = f"📜 {art['day']:02d}.{art['month']:02d} | {title}"
        kb.row(InlineKeyboardButton(text=btn_text, callback_data=f"library_open_{art['id']}"))

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Туди", callback_data=f"library_page_{page - 1}"))
    if total_count > offset + LIMIT:
        nav_buttons.append(InlineKeyboardButton(text="Сюди ➡️", callback_data=f"library_page_{page + 1}"))
    
    if nav_buttons:
        kb.row(*nav_buttons)
    
    kb.row(InlineKeyboardButton(text="🔙 В Академію", callback_data="mode_academy"))

    final_text = text[0] if isinstance(text, tuple) else text

    # --- ВЗАЄМОДІЯ З TELEGRAM (ЗАХИЩЕНА) ---

    # 1. Редагуємо список сторінок
    try:
        await callback.message.edit_text(
            final_text, 
            reply_markup=kb.as_markup(), 
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Помилка оновлення сторінки бібліотеки: {e}")

    # 2. Відповідаємо на клік кнопки
    try:
        await callback.answer()
    except TelegramBadRequest:
        # Це саме те місце, де виникала помилка "query is too old"
        logging.info("Запит сторінки бібліотеки застарів, ігноруємо.")

@dp.callback_query(F.data.startswith("library_open_"))
async def open_archived_article(callback: types.CallbackQuery):
    try:
        article_id = int(callback.data.split("_")[2])
    except ValueError:
        await callback.answer("Помилка відкриття.")
        return

    # Дістаємо статтю і рендеримо її
    article = await db.get_article_by_id(article_id)
    if article:
        # Відкриваємо статтю як зазвичай
        await render_article(callback, article, callback.from_user.id)
    else:
        await callback.answer("Статтю не знайдено.")

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

    # 1. Спроба оновити текст цитати
    try:
        await callback.message.edit_text(
            text, reply_markup=get_quote_keyboard(), parse_mode="Markdown"
        )
    except Exception as e:
        # Найчастіша помилка тут — "Message is not modified", 
        # якщо рандом вибрав ту саму цитату, що вже на екрані.
        logging.info(f"Помилка оновлення цитати: {e}")
        
        # Можна вивести маленьке сповіщення юзеру, якщо хочеш
        try:
            await callback.answer("Випала та сама цитата. Спробуй ще раз! 🔄")
            return
        except Exception:
            pass

    # 2. Спроба підтвердити клік (захист від застарілих запитів)
    try:
        await callback.answer()
    except TelegramBadRequest:
        logging.info("Запит цитати застарів.")


# --- ЛОГІКА: MEMENTO MORI (ТАЙМЕР ЖИТТЯ) ---

def generate_memento_text(birth_date: datetime):
    """Генерує текст таймера життя на основі дати."""
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

    return (
        f"📅 **Точка відліку:** {birth_date.year} рік\n\n"
        f"⏳ **Середній життєвий шлях (статистика):**\n"
        f"`{progress_bar}` {percentage:.1f}%\n\n"
        f"🔹 Прожито тижнів: **{weeks_lived}**\n"
        f"🔸 Умовний запас: **~{int(TOTAL_WEEKS - weeks_lived)}** тижнів\n\n"
        f"✨ *«Не те щоб ми маємо мало часу, а те, що ми багато його втрачаємо.» — Сенека*\n\n"
        f"☝️ _Пам'ятай: цей графік — лише модель. Справжня цінність життя вимірюється не тижнями, а глибиною твоїх вчинків._"
    )


@dp.callback_query(F.data == "reset_memento")
async def reset_memento_date(callback: types.CallbackQuery, state: FSMContext):
    # Додаємо кнопку скасування, щоб не застрягти
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Скасувати", callback_data="back_home")
    
    # Додано try/except для безпечного редагування тексту
    try:
        await callback.message.edit_text(
            "🔄 **Зміна дати**\n\n" 
            "Введи нову дату народження (наприклад: `24.08.1991`) або просто рік:",
            reply_markup=kb.as_markup(),
            parse_mode="Markdown",
        )
    except Exception:
        pass

    await state.set_state(MementoMori.waiting_for_birthdate)

    # Додано захист для відповіді на кнопку
    try:
        await callback.answer()
    except TelegramBadRequest:
        logging.info("Запит зміни дати Memento Mori застарів")


@dp.callback_query(F.data == "mode_memento")
async def start_memento(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id

    # Отримуємо дату з бази
    saved_date = await db.get_birthdate(user_id)

    if saved_date:
        # --- ВАРІАНТ 1: ДАТА Є ---
        birth_date = datetime(saved_date.year, saved_date.month, saved_date.day)
        text = generate_memento_text(birth_date)

        kb = InlineKeyboardBuilder()
        kb.button(text="🔄 Змінити дату", callback_data="reset_memento")
        kb.button(text="🔙 В меню", callback_data="back_home")
        kb.adjust(1) # Кнопки одна під одною

        # Додано try/except для редагування тексту
        try:
            await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
        except Exception:
            pass
    else:
        # --- ВАРІАНТ 2: ДАТИ НЕМАЄ (ПЕРШИЙ ВХІД) ---
        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 Назад в меню", callback_data="back_home")
        
        # Додано try/except для редагування тексту
        try:
            await callback.message.edit_text(
                "⏳ **Memento Mori**\n\n"
                "Щоб візуалізувати твій час, мені потрібно знати дату народження.\n\n"
                "👇 Напиши її у чат:\n"
                "• Повну: `24.08.1995`\n"
                "• Або рік: `1995`",
                reply_markup=kb.as_markup(),
                parse_mode="Markdown",
            )
        except Exception:
            pass
        await state.set_state(MementoMori.waiting_for_birthdate)

    # Додано захист для відповіді на кнопку
    try:
        await callback.answer()
    except TelegramBadRequest:
        logging.info("Запит Memento Mori застарів")

@dp.message(MementoMori.waiting_for_birthdate)
async def process_birthdate(message: types.Message, state: FSMContext):
    date_text = message.text.strip()
    birth_date = None
    
    # Кнопка "Скасувати" на випадок помилки
    kb_error = InlineKeyboardBuilder()
    kb_error.button(text="🔙 Скасувати", callback_data="back_home")

    # Спроба 1: Повна дата
    try:
        birth_date = datetime.strptime(date_text, "%d.%m.%Y")
    except ValueError:
        # Спроба 2: Тільки рік
        try:
            birth_date = datetime.strptime(date_text, "%Y")
        except ValueError:
            await message.answer(
                "⚠️ **Невірний формат.**\n"
                "Спробуй ще раз: `24.08.1998` або просто `1998`.",
                reply_markup=kb_error.as_markup(),
                parse_mode="Markdown"
            )
            return

    # --- ДОДАТКОВІ ПЕРЕВІРКИ ---
    # 1. Перевірка на майбутнє
    if birth_date > datetime.now():
        await message.answer(
            "🔮 Ти з майбутнього? Введи дату народження з минулого.",
            reply_markup=kb_error.as_markup()
        )
        return
    
    # 2. Перевірка на реалістичність (наприклад, > 110 років)
    if (datetime.now().year - birth_date.year) > 110:
        await message.answer(
            "🐢 Ого, ти бачив динозаврів? Давай введемо реальну дату.",
            reply_markup=kb_error.as_markup()
        )
        return

    # --- ЗБЕРЕЖЕННЯ В БАЗУ ---
    await db.set_birthdate(message.from_user.id, birth_date.date())

    # Генеруємо результат
    result_text = generate_memento_text(birth_date)

    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Змінити дату", callback_data="reset_memento")
    kb.button(text="🔙 В меню", callback_data="back_home")
    kb.adjust(1)

    await message.answer(result_text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    await state.clear()


# --- ЛОГІКА: STOIC GYM (ГРА) ---


@dp.callback_query(F.data == "mode_gym")
async def start_gym(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    # Оновлюємо ім'я при вході в гру
    await db.add_user(user_id, callback.from_user.first_name)

    # Отримуємо поточний прогрес
    score, level, _ = await db.get_stats(user_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Продовжити тренування", callback_data="game_start")

    if level > 1 or score > 0:  # Показуємо кнопку, тільки якщо є прогрес
        builder.button(text="🔄 Почати заново", callback_data="reset_gym_confirm")

    builder.button(text="🔙 В меню", callback_data="back_home")

    builder.adjust(1)
    await callback.message.edit_text(
        f"⚔️ **Stoic Gym | Рівень {level}**\n\n"
        f"🏆 Твій рахунок: **{score}**\n"
        "Продовжуй свій шлях до мудрості.",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer()


# added handler Додаємо почати тренування
@dp.callback_query(F.data == "game_start")
async def start_game_from_button(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    # Редагуємо повідомлення, щоб прибрати кнопку "Почати тренування"
    await callback.message.edit_text(
        "⚔️ **Тренування розпочато!**\n\nГотуйся до першої ситуації...",
        parse_mode="Markdown",
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
        for i, (uid, name, score) in enumerate(top_users, start=1):
            # Медальки для перших трьох
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🔹"

            # визначення рангу
            rank_emoji = get_stoic_rank(score).split()[
                0
            ]  # Беремо тільки смайлик (👶, 🦉 тощо)

            # Якщо ім'я немає в базі (старі юзери), пишемо "Невідомий Стоїк"
            safe_name = name if name else "Невідомий Стоїк"

            # Формат: 🥇 1. Ім'я (🦉) — 350 балів
            text += f"{medal} {i}. **{safe_name}** ({rank_emoji}) — {score}\n"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]
        ]
    )

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


# --- ХЕНДЛЕР: запис до журналу ---
@dp.callback_query(F.data == "journal_write")
async def start_journal(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📝 **Щоденник Стоїка**\n\n"
        "Марк Аврелій писав: «Наші думки визначають якість нашого життя».\n\n"
        "👇Запиши свій головний урок за сьогодні або те, за що ти вдячний. "
        "Це допоможе закріпити мудрість на практиці.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Скасувати", callback_data="back_home")]
            ]
        ),
        parse_mode="Markdown",
    )
    await state.set_state(JournalState.waiting_for_entry)
    await callback.answer()


@dp.message(JournalState.waiting_for_entry)
async def process_journal(message: types.Message, state: FSMContext):
    user_text = message.text
    if len(user_text) < 5:
        await message.answer(
            "Спробуй написати трохи розгорнутіше. Це для твоєї ж користі."
        )
        return

    await db.save_journal_entry(message.from_user.id, user_text)

    await message.answer(
        "✅ **Запис збережено.**\n\n"
        "Ти приділив час рефлексії — це і є шлях справжнього стоїка. Повертайся завтра за новими викликами!",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]
            ]
        ),
        parse_mode="Markdown",
    )
    await state.clear()


# --- ХЕНДЛЕР: подививтись журнал ---
@dp.callback_query(F.data == "journal_view")
async def view_journal(callback: types.CallbackQuery):
    entries = await db.get_journal_entries(callback.from_user.id)

    if not entries:
        text = "Твій щоденник поки що порожній. Час зробити перший запис!"
    else:
        text = "📜 **Твої останні роздуми:**\n\n"
        for entry in entries:
            date_str = entry["created_at"].strftime("%d.%m.%y")
            text += f"🗓 *{date_str}*: {entry['entry_text']}\n\n"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="mode_profile")]
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


# --- ФУНКЦІЯ ДЛЯ ВІДПРАВКИ РІВНЯ ---
async def send_level(user_id, message_to_edit):
    # 1. ПЕРЕВІРКА ЕНЕРГІЇ
    energy = await db.check_energy(user_id)

    if energy <= 0:
        # --- ФОРМУВАННЯ ЩОДЕННОГО ЗВІТУ ---
        summary = await db.get_daily_summary(user_id)

        feedback_text = ""
        stats_text = ""

        if summary:
            if summary["mistakes"] == 0:
                feedback_text = (
                    "🌟 **Бездоганний день!** Твій розум був гострим, як меч."
                )
            elif summary["mistakes"] > summary["wisdoms"]:
                feedback_text = (
                    "🌪 **День випробувань.** Сьогодні емоції часто брали гору."
                )
            else:
                feedback_text = "⚖️ **Гідний результат.** Ти діяв зважено."

            stats_text = (
                f"\n\n📊 **Підсумок сесії:**\n"
                f"✅ Мудрих рішень: **{summary['wisdoms']}**\n"
                f"❌ Емоційних зривів: **{summary['mistakes']}**\n"
                f"💎 Зароблено балів: **{summary['points']}**"
            )
        else:
            feedback_text = "Ти добре попрацював сьогодні."

        kb = InlineKeyboardBuilder()
        kb.button(text="📝 Запис у щоденник", callback_data="journal_write")
        kb.button(text="🔙 В меню", callback_data="back_home")
        kb.adjust(1)

        await message_to_edit.edit_text(
            f"🌙 **Енергія вичерпана**\n\n"
            f"{feedback_text}"
            f"{stats_text}\n\n"
            "🧘‍♂️ **Стоїцизм вимагає пауз для осмислення.**\n"
            "Обдумай отримані уроки і повертайся завтра з новими силами.\n\n"
            "✍️ **Порада:** Щоб не втратити важливі думки, запиши їх зараз у **Щоденник**.\n\n"
            "⚡ Енергія відновиться зранку.",
            reply_markup=kb.as_markup(),
            parse_mode="Markdown",
        )
        return

    # 2. ОТРИМАННЯ СТАТИСТИКИ
    score, current_level, _ = await db.get_stats(user_id)
    max_scenarios = len(SCENARIOS)  # Зараз 60, потім буде 100

    # 3. ЛОГІКА ВИБОРУ СЦЕНАРІЮ (Endless Mode)
    scenario_data = None
    header_text = ""

    if current_level <= max_scenarios:
        # --- ЗВИЧАЙНИЙ РЕЖИМ (1-100) ---
        scenario_data = SCENARIOS.get(current_level)
        header_text = f"🛡️ **Рівень {current_level}/{max_scenarios}**"
    else:
        # --- НЕСКІНЧЕННИЙ РЕЖИМ (101+) ---
        # Вибираємо випадковий ID від 1 до max_scenarios
        random_id = random.randint(1, max_scenarios)
        scenario_data = SCENARIOS.get(random_id)
        header_text = f"♾️ **Шлях Мудреця | Рівень {current_level}**"

    # 4. СПИСАННЯ ЕНЕРГІЇ
    await db.decrease_energy(user_id)
    new_energy = energy - 1

    # Копіюємо і перемішуємо варіанти
    options = scenario_data["options"].copy()
    random.shuffle(options)

    # ЛОГІКА A/B/C/D
    labels = ["A", "B", "C", "D"]
    options_text_block = ""
    builder = InlineKeyboardBuilder()

    for i, option in enumerate(options):
        label = labels[i] if i < len(labels) else f"{i + 1}"
        options_text_block += f"**{label})** {option['text']}\n\n"
        builder.button(text=f"🔹 {label}", callback_data=f"game_{option['id']}")

    builder.button(text="🔙 В меню", callback_data="back_home")
    builder.adjust(2, 2, 1)

    full_text = (
        f"{header_text} | ⚡ {new_energy}/5\n\n"
        f"{scenario_data['text']}\n\n"
        f"👇 **Твій вибір:**\n\n"
        f"{options_text_block}"
    )

    await message_to_edit.edit_text(
        full_text, reply_markup=builder.as_markup(), parse_mode="Markdown"
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
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]
            ]
        ),
        parse_mode="Markdown",
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
        parse_mode="Markdown",
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
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="▶️ Почати тренування", callback_data="game_start"
                    )
                ],
                [InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")],
            ]
        ),
        parse_mode="Markdown",
    )
    await callback.answer()


# Цей хендлер ловить вибір варіантів у грі (усі callback-и, які не є системними)
# Переконайтеся, що back_to_main_menu() знаходиться ВИЩЕ у коді!
@dp.callback_query(
    lambda c: c.data and c.data.startswith("game_") and c.data not in ["game_next"]
)
async def handle_game_choice(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    current_score, current_level, _ = await db.get_stats(user_id)

    if current_level in SCENARIOS:
        scenario = SCENARIOS[current_level]
        choice_id = callback.data.replace("game_", "")

        selected_option = next(
            (opt for opt in scenario["options"] if opt["id"] == choice_id), None
        )

        if selected_option:
            points_change = selected_option["score"]
            new_score = current_score + points_change
            new_level = current_level + 1

            # 1. Оновлюємо базу даних (це критично важливо, робимо без try/except для Telegram)
            await db.update_game_progress(user_id, new_score, new_level)
            await db.log_move(user_id, current_level, points_change)

            # Визначаємо фідбек
            if points_change > 0:
                score_feedback = f"🟢 **+{points_change} балів мудрості**"
            elif points_change < 0:
                score_feedback = f"🔴 **{points_change} балів (Не стоїчно)**"
            else:
                score_feedback = "⚪ **0 балів**"

            kb = InlineKeyboardBuilder()
            max_level = len(SCENARIOS)

            # Формуємо текст та кнопки
            if new_level > max_level:
                msg_text = (
                    f"🏆 **ПЕРЕМОГА!** Ти завершив усі {max_level} рівнів!\n"
                    f"Твій фінальний рахунок: **{new_score}**\n"
                    f"«Невдача — це ціна навчання, успіх — це результат практики.»"
                )
                kb.button(text="🔙 В меню", callback_data="back_home")
            else:
                msg_text = (
                    f"{scenario['text']}\n\n✅ **Твій вибір:** {selected_option['text']}\n\n"
                    f"{score_feedback}\n\n"
                    f"💡 *{selected_option['msg']}*"
                )
                kb.button(text="🔙 В меню", callback_data="back_home")
                kb.button(text="▶️ Продовжити", callback_data="game_next")
                kb.adjust(2)

            # --- ТУТ ЗАХИЩЕНА ВЗАЄМОДІЯ З TELEGRAM ---

            # 2. Спроба оновити екран результату
            try:
                await callback.message.edit_text(
                    msg_text,
                    reply_markup=kb.as_markup(),
                    parse_mode="Markdown"
                )
            except Exception as e:
                # Наприклад, якщо користувач натиснув двічі дуже швидко
                logging.error(f"Game edit error: {e}")

    # 3. Відповідаємо на клік (захист від "query is too old")
    try:
        await callback.answer()
    except TelegramBadRequest:
        logging.info("Ігноруємо застарілий вибір у грі.")


# --- Розсилка повідомлень юзерам ---
async def send_daily_quote(bot: Bot):
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
            logging.error(
                f"Не вдалося надіслати повідомлення користувачу {user_id}: {e}"
            )

    logging.info(f"✅ Розсилка завершена. Отримали: {count} користувачів.")


# --- ЛОГІКА ШІ МЕНТОРА ---
@dp.callback_query(F.data == "mode_ai")
async def start_ai_mentor(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🤖 **Зал Роздумів**\n\n"
        "Я — цифрова тінь Марка Аврелія. Я тут, щоб вислухати твої тривоги.\n\n"
        "👇 Напиши мені, що тебе турбує, або запитай поради. \n"
        "_(Наприклад: 'Як перестати злитися на колег?' або 'Я втратив мотивацію')_",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 Вийти з діалогу", callback_data="back_home"
                    )
                ]
            ]
        ),
        parse_mode="Markdown",
    )
    await state.set_state(MentorState.chatting)
    await callback.answer()


@dp.message(MentorState.chatting)
async def process_ai_chat(message: types.Message, state: FSMContext, bot: Bot):
    user_text = message.text

    # Показуємо, що бот "друкує" (це важливо для UX, бо ШІ думає 2-3 сек)
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    # Отримуємо відповідь від ШІ
    ai_response = await get_stoic_advice(user_text)

    await message.answer(
        f"🏛 **Марк Аврелій:**\n\n{ai_response}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 Завершити розмову", callback_data="back_home"
                    )
                ]
            ]
        ),
    )
    # Ми НЕ скидаємо стан, щоб юзер міг писати далі (діалог триває)


async def main():
    logging.info("🏁 Старт системи...")
    bot = Bot(token=BOT_TOKEN)
    # 1. ПІДКЛЮЧЕННЯ ДО БАЗИ ДАНИХ
    await db.connect()
    await db.create_tables()
    await db.create_academy_table()
    await db.create_progress_table()

    # 2. ПЛАНУВАЛЬНИК (SCHEDULER)
    scheduler = AsyncIOScheduler()
    # 07:30 UTC = 09:30 за Києвом
    scheduler.add_job(send_daily_quote, trigger="cron", hour=7, minute=30, kwargs={"bot": bot})
    scheduler.start()

    # 3. ЗАПУСК БОТА (Видаляємо зайві коментарі, просто запускаємо)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


# --- АДМІН-КОМАНДА: РОЗСИЛКА ---
# Використання: /broadcast Текст повідомлення
@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, bot: Bot):
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
    if message.from_user.id != ADMIN_ID:
        return

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
            pass  # Ігноруємо помилки (наприклад, юзер заблокував бота)

    await message.answer(f"✅ Розсилка завершена! Успішно: {count}")


# --- ЛОГІКА ЗВОРОТНОГО ЗВ'ЯЗКУ ---


@dp.callback_query(F.data == "send_feedback")
async def start_feedback(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "✉️ **Зв'язок з розробником**\n\n"
        "Напиши своє повідомлення (відгук, ідею або знайдену помилку) і я передам його автору.\n\n"
        "👇 *Чекаю на твій текст:*",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Скасувати", callback_data="back_home")]
            ]
        ),
        parse_mode="Markdown",
    )
    await state.set_state(FeedbackState.waiting_for_message)
    await callback.answer()


@dp.message(FeedbackState.waiting_for_message)
async def process_feedback(message: types.Message, state: FSMContext, bot: Bot):
    user_text = message.text
    user_id = message.from_user.id
    user_name = message.from_user.first_name

    # ID адміна
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

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
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]
                ]
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        await message.answer("⚠️ Сталася помилка при відправці. Спробуй пізніше.")
        logging.error(f"Feedback error: {e}")

    await state.clear()


if __name__ == "__main__":
    # db = Database() # Цей рядок прибрати!
    # потрібно ініціалізувати db = Database() як глобальну змінну, а потім викликати main()
    asyncio.run(main())
