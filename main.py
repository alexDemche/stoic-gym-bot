import asyncio
import logging
import os
import random
from datetime import datetime
from urllib.parse import quote

from aiogram import Bot, Dispatcher, F, types
from aiogram import html
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from academy_service import format_article
from ai_service import get_stoic_advice
# Імпортуємо базу цитат з data.py
from data import HELP_TEXT, SCENARIOS, STOIC_DB
from db import Database
from utils import get_stoic_rank

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

# Глобальна база даних
db = Database()

# --- ІНІЦІАЛІЗАЦІЯ ---
logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

# --- КЛАВІАТУРИ ---
def get_main_menu():
    """Головне меню"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⚔️ Stoic Gym (Гра)", callback_data="mode_gym")
    builder.button(text="📖 Академія (Теорія)", callback_data="mode_academy")
    builder.button(text="🤖 Ментор (AI)", callback_data="mode_ai")
    builder.button(
        text="🧘‍♂️ Lab (Лабараторні)", url="https://t.me/StoicTrainerLab_ua_bot"
    )
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
    score, level, name = await db.get_stats(user_id)
    birth_date = await db.get_birthdate(user_id)
    energy = await db.check_energy(user_id)
    academy_count, academy_rank = await db.get_academy_progress(user_id)
    game_rank = get_stoic_rank(score)

    thresholds = [50, 150, 500, 1000, 2500, 5000]
    next_rank_score = 0
    for t in thresholds:
        if score < t:
            next_rank_score = t
            break

    progress_msg = ""
    if next_rank_score > 0:
        needed = next_rank_score - score
        progress_msg = f" (ще {needed} до підвищення)"
    else:
        progress_msg = " (MAX LEVEL 👑)"

    memento_status = "✅ Активно" if birth_date else "❌ Не налаштовано"

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
        logging.error(f"Помилка при редагуванні профілю: {e}")

    try:
        await callback.answer()
    except TelegramBadRequest:
        logging.info("Запит профілю застарів")


# --- ЛОГІКА: СТАРТ І МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, bot: Bot):
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
    await state.clear()
    try:
        await callback.message.edit_text(
            "👋 **Вітаю в Stoic Trainer!**\n\nОбери режим для тренування духу:",
            reply_markup=get_main_menu(),
            parse_mode="Markdown",
        )
    except Exception:
        pass
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    count = await db.count_users()
    await message.answer(
        f"📊 **Статистика бота:**\n\n👤 Користувачів: **{count}**", parse_mode="Markdown"
    )


@dp.message(Command("sync"))
async def cmd_sync(message: types.Message):
    user_id = message.from_user.id
    code = await generate_sync_code(user_id)
    text = (
        "🔐 **Синхронізація з додатком**\n\n"
        f"Твій тимчасовий код: `{code}`\n\n"
        "⏳ Код діє **10 хвилин**.\n"
        "Введи його в мобільному додатку Stoic Academy, щоб перенести свій прогрес."
    )
    await message.answer(text, parse_mode="Markdown")


# --- ЛОГІКА: Академія ---
async def render_article(callback: types.CallbackQuery, article, user_id):
    is_read = await db.is_article_read(user_id, article["id"])
    daily_count = await db.get_daily_academy_count(user_id)
    full_text = format_article(article)
    limit_info = f"\n\n📊 Сьогодні засвоєно: **{daily_count}/5** уроків."
    final_text = full_text + limit_info
    if len(final_text) > 4000:
        final_text = final_text[:3990] + "...\n\n*(Текст скорочено через ліміти Telegram)*"

    kb = InlineKeyboardBuilder()
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
        await callback.message.edit_text(final_text, reply_markup=kb.as_markup(), parse_mode="Markdown")
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
    try:
        current_date = date(2024, current_month, current_day)
        if direction == "next":
            new_date = current_date + timedelta(days=1)
        else:
            new_date = current_date - timedelta(days=1)
        article = await db.get_article_by_date(new_date.day, new_date.month)
        if article:
            await render_article(callback, article, callback.from_user.id)
        else:
            await callback.answer("Цієї сторінки ще немає в архівах.", show_alert=True)
    except Exception:
        await callback.answer("Помилка навігації.")
    await callback.answer()


@dp.callback_query(F.data == "academy_already_done")
async def handle_already_read(callback: types.CallbackQuery):
    await callback.answer("Ти вже засвоїв цей урок!", show_alert=False)


@dp.callback_query(F.data == "academy_limit_reached")
async def handle_limit_reached_nav(callback: types.CallbackQuery):
    await callback.answer("Ти засвоїв 5 уроків сьогодні! Відпочинь. 🏛️", show_alert=True)


@dp.callback_query(F.data.startswith("academy_read_"))
async def handle_read_article(callback: types.CallbackQuery):
    article_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    daily_count = await db.get_daily_academy_count(user_id)
    if daily_count >= 5:
        await handle_limit_reached_nav(callback)
        return
    is_new = await db.mark_article_as_read(user_id, article_id)
    article = await db.get_article_by_id(article_id)
    if article:
        new_count, rank = await db.get_academy_progress(user_id)
        new_daily = await db.get_daily_academy_count(user_id)
        await render_article(callback, article, user_id)
        if is_new:
            await callback.answer(f"🎉 Урок зараховано!\nВсього: {new_count}\nЗа сьогодні: {new_daily}/5", show_alert=True)
    else:
        await callback.answer("Помилка: статті немає.")


# --- БІБЛІОТЕКА ---
@dp.callback_query(F.data.startswith("library_page_"))
async def show_library_page(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    try:
        page = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        page = 0
    LIMIT = 10
    offset = page * LIMIT
    articles = await db.get_user_library(user_id, limit=LIMIT, offset=offset)
    total_count = await db.count_user_library(user_id)
    import math
    total_pages = math.ceil(total_count / LIMIT) if total_count > 0 else 1

    if not articles:
        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 В Академію", callback_data="mode_academy")
        try:
            await callback.message.edit_text("📚 Тут поки пусто.", reply_markup=kb.as_markup(), parse_mode="Markdown")
        except Exception: pass
        try: await callback.answer()
        except TelegramBadRequest: pass
        return

    text = f"📚 **Бібліотека** (Стор. {page + 1}/{total_pages})\nВсього записів: **{total_count}**\n\n👇 *Натисни, щоб відкрити:*"
    kb = InlineKeyboardBuilder()
    for art in articles:
        title = art["title"][:23] + ".." if len(art["title"]) > 25 else art["title"]
        kb.row(InlineKeyboardButton(text=f"📜 {art['day']:02d}.{art['month']:02d} | {title}", callback_data=f"library_open_{art['id']}"))

    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardButton(text="⬅️ Туди", callback_data=f"library_page_{page - 1}"))
    if total_count > offset + LIMIT: nav_buttons.append(InlineKeyboardButton(text="Сюди ➡️", callback_data=f"library_page_{page + 1}"))
    if nav_buttons: kb.row(*nav_buttons)
    kb.row(InlineKeyboardButton(text="🔙 В Академію", callback_data="mode_academy"))

    try: await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    except Exception: pass
    try: await callback.answer()
    except TelegramBadRequest: pass


@dp.callback_query(F.data.startswith("library_open_"))
async def open_archived_article(callback: types.CallbackQuery):
    try: article_id = int(callback.data.split("_")[2])
    except ValueError: return
    article = await db.get_article_by_id(article_id)
    if article: await render_article(callback, article, callback.from_user.id)
    else: await callback.answer("Статтю не знайдено.")


# --- ОРАКУЛ ---
@dp.callback_query(F.data == "mode_quotes")
async def start_quotes(callback: types.CallbackQuery):
    await send_random_quote(callback)

@dp.callback_query(F.data == "refresh_quote")
async def refresh_quote(callback: types.CallbackQuery):
    await send_random_quote(callback)

async def send_random_quote(callback: types.CallbackQuery):
    quote = random.choice(STOIC_DB)
    text = f"📜 *{quote['category']}*\n\n_{quote['text']}_\n\n— {quote['author']}"
    try: await callback.message.edit_text(text, reply_markup=get_quote_keyboard(), parse_mode="Markdown")
    except Exception: pass
    try: await callback.answer()
    except TelegramBadRequest: pass


# --- MEMENTO MORI ---
def generate_memento_text(birth_date: datetime):
    AVG_LIFESPAN_YEARS = 80
    TOTAL_WEEKS = AVG_LIFESPAN_YEARS * 52
    delta = datetime.now() - birth_date
    weeks_lived = delta.days // 7
    percentage = min((weeks_lived / TOTAL_WEEKS) * 100, 100)
    filled_blocks = int((percentage / 100) * 20)
    progress_bar = "▓" * filled_blocks + "░" * (20 - filled_blocks)
    return (
        f"📅 **Точка відліку:** {birth_date.year} рік\n\n"
        f"⏳ **Середній життєвий шлях:**\n`{progress_bar}` {percentage:.1f}%\n\n"
        f"🔹 Прожито тижнів: **{weeks_lived}**\n"
        f"🔸 Умовний запас: **~{int(TOTAL_WEEKS - weeks_lived)}** тижнів"
    )

@dp.callback_query(F.data == "reset_memento")
async def reset_memento_date(callback: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Скасувати", callback_data="back_home")
    try: await callback.message.edit_text("🔄 Введи нову дату народження (наприклад: `24.08.1991`):", reply_markup=kb.as_markup(), parse_mode="Markdown")
    except Exception: pass
    await state.set_state(MementoMori.waiting_for_birthdate)
    try: await callback.answer()
    except TelegramBadRequest: pass

@dp.callback_query(F.data == "mode_memento")
async def start_memento(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    saved_date = await db.get_birthdate(user_id)
    if saved_date:
        birth_date = datetime(saved_date.year, saved_date.month, saved_date.day)
        text = generate_memento_text(birth_date)
        kb = InlineKeyboardBuilder()
        kb.button(text="🔄 Змінити дату", callback_data="reset_memento")
        kb.button(text="🔙 В меню", callback_data="back_home")
        kb.adjust(1)
        try: await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
        except Exception: pass
    else:
        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 Назад в меню", callback_data="back_home")
        try: await callback.message.edit_text("⏳ **Memento Mori**\n\nВведи дату народження (наприклад: `1995` або `24.08.1995`):", reply_markup=kb.as_markup(), parse_mode="Markdown")
        except Exception: pass
        await state.set_state(MementoMori.waiting_for_birthdate)
    try: await callback.answer()
    except TelegramBadRequest: pass

@dp.message(MementoMori.waiting_for_birthdate)
async def process_birthdate(message: types.Message, state: FSMContext):
    date_text = message.text.strip()
    kb_error = InlineKeyboardBuilder()
    kb_error.button(text="🔙 Скасувати", callback_data="back_home")
    try:
        birth_date = datetime.strptime(date_text, "%d.%m.%Y")
    except ValueError:
        try:
            birth_date = datetime.strptime(date_text, "%Y")
        except ValueError:
            await message.answer("⚠️ Невірний формат. Спробуй ще раз.", reply_markup=kb_error.as_markup())
            return
    if birth_date > datetime.now() or (datetime.now().year - birth_date.year) > 110:
        await message.answer("🐢 Введи реальну дату.", reply_markup=kb_error.as_markup())
        return
    await db.set_birthdate(message.from_user.id, birth_date.date())
    result_text = generate_memento_text(birth_date)
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Змінити дату", callback_data="reset_memento")
    kb.button(text="🔙 В меню", callback_data="back_home")
    kb.adjust(1)
    await message.answer(result_text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    await state.clear()


# --- STOIC GYM ---
@dp.callback_query(F.data == "mode_gym")
async def start_gym(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await db.add_user(user_id, callback.from_user.first_name)
    score, level, _ = await db.get_stats(user_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Продовжити тренування", callback_data="game_start")
    if level > 1 or score > 0: builder.button(text="🔄 Почати заново", callback_data="reset_gym_confirm")
    builder.button(text="🔙 В меню", callback_data="back_home")
    builder.adjust(1)
    await callback.message.edit_text(f"⚔️ **Stoic Gym | Рівень {level}**\n🏆 Рахунок: **{score}**", reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "game_start")
async def start_game_from_button(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await callback.message.edit_text("⚔️ **Тренування розпочато!**", parse_mode="Markdown")
    await asyncio.sleep(1)
    await send_level(user_id, callback.message)
    await callback.answer()

@dp.callback_query(F.data == "mode_top")
async def show_leaderboard(callback: types.CallbackQuery):
    top_users = await db.get_top_users(10)
    text = "🏆 <b>Алея Слави</b>\n\n"
    for i, (uid, name, score) in enumerate(top_users, start=1):
        safe_name = html.quote(name) if name else "Невідомий"
        text += f"{i}. <b>{safe_name}</b> — {score}\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "game_next")
async def go_to_next_level(callback: types.CallbackQuery):
    await send_level(callback.from_user.id, callback.message)
    await callback.answer()

@dp.callback_query(F.data == "journal_write")
async def start_journal(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📝 **Щоденник**\n👇Запиши свій головний урок за сьогодні.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="back_home")]]), parse_mode="Markdown")
    await state.set_state(JournalState.waiting_for_entry)
    await callback.answer()

@dp.message(JournalState.waiting_for_entry)
async def process_journal(message: types.Message, state: FSMContext):
    if len(message.text) < 5:
        await message.answer("Спробуй написати трохи розгорнутіше.")
        return
    await db.save_journal_entry(message.from_user.id, message.text)
    await message.answer("✅ **Запис збережено.**", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]]), parse_mode="Markdown")
    await state.clear()

@dp.callback_query(F.data == "journal_view")
async def view_journal(callback: types.CallbackQuery):
    entries = await db.get_journal_entries(callback.from_user.id)
    text = "📜 **Твої записи:**\n\n" + ("".join([f"🗓 *{e['created_at'].strftime('%d.%m.%y')}*: {e['entry_text']}\n\n" for e in entries]) if entries else "Порожньо.")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="mode_profile")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

async def generate_sync_code(user_id):
    code = "".join([str(random.randint(0, 9)) for _ in range(6)])
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM sync_codes WHERE user_id = $1", user_id)
        await conn.execute("INSERT INTO sync_codes (code, user_id) VALUES ($1, $2)", code, user_id)
    return code

async def clear_expired_codes():
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM sync_codes WHERE expires_at < CURRENT_TIMESTAMP")

async def send_level(user_id, message_to_edit):
    score, current_level, _ = await db.get_stats(user_id)
    energy = await db.check_energy(user_id)
    if energy <= 0:
        await message_to_edit.edit_text("🌙 **Енергія вичерпана.** Відновиться завтра.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]]), parse_mode="Markdown")
        return
    
    max_scenarios = len(SCENARIOS)
    target_id = current_level if current_level <= max_scenarios else random.randint(1, max_scenarios)
    scenario_data = SCENARIOS.get(target_id)
    if not scenario_data:
        await message_to_edit.edit_text("Архів порожній.", reply_markup=get_main_menu())
        return

    await db.decrease_energy(user_id)
    options = scenario_data["options"].copy()
    random.shuffle(options)
    labels = ["A", "B", "C", "D"]
    builder = InlineKeyboardBuilder()
    text_opts = ""
    for i, opt in enumerate(options):
        lbl = labels[i]
        text_opts += f"**{lbl})** {opt['text']}\n\n"
        builder.button(text=f"🔹 {lbl}", callback_data=f"anygame_{target_id}_{opt['id']}")
    builder.button(text="🔙 В меню", callback_data="back_home")
    builder.adjust(2, 2, 1)
    await message_to_edit.edit_text(f"🛡️ **Рівень {current_level}** | ⚡ {energy-1}/5\n\n{scenario_data['text']}\n\n👇 **Твій вибір:**\n\n{text_opts}", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(HELP_TEXT, parse_mode="Markdown")

@dp.callback_query(F.data == "show_help")
async def show_help_callback(callback: types.CallbackQuery):
    await callback.message.edit_text(HELP_TEXT, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]]), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "reset_gym_confirm")
async def confirm_reset(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так", callback_data="reset_gym_final")
    builder.button(text="❌ Ні", callback_data="mode_gym")
    await callback.message.edit_text("⚠️ Скинути прогрес?", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "reset_gym_final")
async def reset_gym(callback: types.CallbackQuery):
    await db.update_game_progress(callback.from_user.id, 0, 1)
    await callback.message.edit_text("✅ Прогрес скинуто!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Почати", callback_data="game_start")], [InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]]))
    await callback.answer()

@dp.callback_query(F.data.startswith("anygame_"))
async def handle_game_choice(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    try:
        parts = callback.data.split("_")
        scenario_id = int(parts[1])
        choice_id = "_".join(parts[2:])
    except: return

    current_score, current_level, _ = await db.get_stats(user_id)
    energy_left = await db.check_energy(user_id)
    scenario = SCENARIOS.get(scenario_id)
    selected_option = next((opt for opt in scenario["options"] if opt["id"] == choice_id), None)

    if selected_option:
        points = selected_option["score"]
        await db.update_game_progress(user_id, current_score + points, current_level + 1)
        await db.log_move(user_id, scenario_id, points)
        
        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 В меню", callback_data="back_home")
        if energy_left > 0: kb.button(text="▶️ Далі", callback_data="game_next")
        else: kb.button(text="📊 Підсумок", callback_data="game_next")
        kb.adjust(2)
        
        msg = f"{scenario['text']}\n\n✅ **Вибір:** {selected_option['text']}\n\n{'🟢' if points>0 else '🔴'} **{points} балів**\n\n💡 *{selected_option['msg']}*"
        if energy_left == 0: msg += "\n\n⚠️ Енергія вичерпана."
        
        try: await callback.message.edit_text(msg, reply_markup=kb.as_markup(), parse_mode="Markdown")
        except: pass
    try: await callback.answer()
    except: pass

async def send_daily_quote(bot: Bot):
    users = await db.get_all_users()
    quote = random.choice(STOIC_DB)
    text = f"☀️ **Мудрість на сьогодні:**\n\n_{quote['text']}_\n\n— {quote['author']}\n\n👉 /start — Пройти тренування"
    for user_id in users:
        try: await bot.send_message(user_id, text, parse_mode="Markdown")
        except: pass
        await asyncio.sleep(0.05)


# --- ШІ МЕНТОР ---
@dp.callback_query(F.data == "mode_ai")
async def start_ai_mentor(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🤖 **Зал Роздумів**\nНапиши своє питання.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Вийти", callback_data="back_home")]]), parse_mode="Markdown")
    await state.set_state(MentorState.chatting)
    await callback.answer()


@dp.message(MentorState.chatting)
async def process_ai_chat(message: types.Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    user_text = message.text

    # 1. ЗАХИСТ ВІД ДОВГИХ ПОВІДОМЛЕНЬ (Token Explosion)
    if len(user_text) > 500:
        await message.reply("📉 Твоє питання занадто довге. Спробуй скоротити думку до суті (до 500 символів).")
        return

    # 2. ПЕРЕВІРКА ЛІМІТІВ (Rate Limiting + Daily Quota)
    status_limit = await db.check_ai_limit(user_id, limit_per_day=50)

    if status_limit == "cooldown":
        await message.reply("⏳ Ти пишеш занадто швидко. Зроби вдих і видих (почекай 5 секунд).")
        return

    if status_limit == "limit_reached":
        await message.reply("⛔ На сьогодні ліміт спілкування з Ментором вичерпано. Чекаємо тебе завтра!")
        return

    # 3. ОБРОБКА ЗАПИТУ
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Зберігаємо повідомлення юзера в історію (важливо для контексту)
    await db.save_mentor_message(user_id, "user", user_text)

    # Отримуємо відповідь
    ai_response = await get_stoic_advice(user_text, user_id) # Передаємо user_id, якщо get_stoic_advice підтримує історію

    # Зберігаємо відповідь
    await db.save_mentor_message(user_id, "assistant", ai_response)

    await message.answer(
        f"🏛 **Марк Аврелій:**\n\n{ai_response}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Завершити", callback_data="back_home")]]),
    )


# --- ЗАПУСК ---
async def main():
    logging.info("🏁 Старт системи...")
    bot = Bot(token=BOT_TOKEN)
    await db.connect()
    await db.create_tables()
    await db.create_academy_table()
    await db.create_progress_table()
    await db.create_lab_tables()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_daily_quote, trigger="cron", hour=7, minute=30, kwargs={"bot": bot})
    scheduler.add_job(clear_expired_codes, "interval", hours=12)
    scheduler.start()

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

# --- ФІДБЕК ---
@dp.callback_query(F.data == "send_feedback")
async def start_feedback(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✉️ Напиши відгук:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Скасувати", callback_data="back_home")]]))
    await state.set_state(FeedbackState.waiting_for_message)
    await callback.answer()

@dp.message(FeedbackState.waiting_for_message)
async def process_feedback(message: types.Message, state: FSMContext, bot: Bot):
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
    try:
        await bot.send_message(ADMIN_ID, f"📨 Відгук від {message.from_user.first_name}:\n{message.text}")
        await message.answer("✅ Відправлено!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="back_home")]]))
    except: await message.answer("Помилка.")
    await state.clear()

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, bot: Bot):
    if message.from_user.id != int(os.getenv("ADMIN_ID", 0)): return
    text = message.text.replace("/broadcast ", "")
    users = await db.get_all_users()
    for uid in users:
        try: await bot.send_message(uid, f"📢 **Оголошення:**\n\n{text}", parse_mode="Markdown")
        except: pass
        await asyncio.sleep(0.05)
    await message.answer("✅ Розсилка завершена!")

if __name__ == "__main__":
    asyncio.run(main())