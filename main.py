import asyncio
import logging
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- НАЛАШТУВАННЯ ---
load_dotenv() # Завантажуємо змінні з .env файлу
TOKEN = os.getenv("BOT_TOKEN")

# --- КОНТЕНТ (База даних ситуацій) ---
SCENARIOS = {
    1: {
        "text": "🚗 **Ситуація:** Ти стоїш у заторі. Вже спізнюєшся на 20 хвилин. Водій позаду починає сигналити без причини.",
        "options": [
            {"id": "s1_a", "text": "Вийти і пояснити йому, хто він такий 🤬", "score": -10, "msg": "Ти втратив контроль. Гнів — це тимчасове божевілля."},
            {"id": "s1_b", "text": "Нервувати і бити кермо 😰", "score": -5, "msg": "Ти караєш себе за чужу дурість."},
            {"id": "s1_c", "text": "Увімкнути аудіокнигу та ігнорувати 🎧", "score": 10, "msg": "Апонія (відсутність болю). Ти використав час з користю."}
        ]
    },
    2: {
        "text": "🍷 **Ситуація:** Офіціант випадково вилив на тебе вино в дорогому ресторані.",
        "options": [
            {"id": "s2_a", "text": "Влаштувати скандал!", "score": -10, "msg": "Це не поверне чистоту сорочки, але зіпсує вечір усім."},
            {"id": "s2_b", "text": "Спокійно піти замити пляму. Це всього лише одяг.", "score": 10, "msg": "Ти відокремив речі від своєї особистості. Речі ламаються і брудняться."}
        ]
    }
}

# Тимчасова база даних в пам'яті
user_db = {} 

# --- ІНІЦІАЛІЗАЦІЯ ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    # Скидаємо прогрес при старті
    user_db[user_id] = {"score": 0, "level": 1}
    
    await message.answer(
        "🏛 **Stoic Gym: Beta**\n\nТут ми гартуємо характер.\nОбирай дії мудро.", 
        parse_mode="Markdown"
    )
    await send_level(user_id)

async def send_level(user_id):
    user_data = user_db[user_id]
    level_id = user_data["level"]
    
    # Якщо рівні закінчились
    if level_id not in SCENARIOS:
        score = user_data["score"]
        verdict = "Справжній Стоїк 🏛" if score > 0 else "Треба ще тренуватися 👶"
        await bot.send_message(user_id, f"🏁 **Фініш!**\nТвій рахунок: {score}\nВердикт: {verdict}")
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

@dp.callback_query()
async def handle_choice(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_data = user_db.get(user_id)
    
    if not user_data:
        await callback.answer("Напиши /start щоб почати заново.")
        return

    level_id = user_data["level"]
    scenario = SCENARIOS.get(level_id)
    
    # Знаходимо, що обрав юзер
    choice_id = callback.data
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
        
        # Чекаємо трохи і даємо наступне
        await asyncio.sleep(1.5)
        await send_level(user_id)

    await callback.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())