import os
import random
from datetime import datetime
from contextlib import asynccontextmanager

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel

from config import SYSTEM_PROMPT_AI_MSG
from db import Database
from utils import get_stoic_rank

# --- МОДЕЛІ ДАНИХ ---
class GymAnswer(BaseModel):
    user_id: int
    score: int
    level: int

class JournalEntry(BaseModel):
    user_id: int
    text: str

class MentorRequest(BaseModel):
    user_id: int
    messages: list

class GuestRequest(BaseModel):
    user_id: int
    username: str
    birthdate: str

class AcademyReadRequest(BaseModel):
    user_id: int
    article_id: int

class LabComplete(BaseModel):
    user_id: int
    practice_type: str
    score: int

class SyncRequest(BaseModel):
    code: str
    guest_id: int
    device_id: str
    
class DeviceAuthRequest(BaseModel): # Краще використовувати модель замість dict
    device_id: str
    username: str = "Мандрівник"
    birthdate: str = "1995-01-01"

# --- НАЛАШТУВАННЯ ---
ADMIN_TOKEN = os.getenv("ADMIN_SECRET_TOKEN")
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
db = Database()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await db.create_tables()
    await db.create_academy_table()
    await db.create_progress_table()
    await db.create_lab_tables()
    yield

app = FastAPI(title="Stoic Trainer API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

api_router = APIRouter(prefix="/api")

# --- ЕНДПОІНТИ ЗАГАЛЬНІ ---

@app.get("/")
async def root():
    user_count = await db.count_users()
    return {"status": "online", "total_users": user_count}

@api_router.get("/stats/{user_id}")
async def get_user_stats(user_id: int):
    score, level, name = await db.get_stats(user_id)
    global_rank = await db.get_user_position(user_id)
    energy = await db.check_energy(user_id)
    birthdate = await db.get_birthdate(user_id)
    rank_name = get_stoic_rank(score)
    
    thresholds = [50, 150, 500, 1000, 2500, 5000]
    next_rank_score = next((t for t in thresholds if score < t), 0)

    return {
        "user_id": user_id,
        "name": name,
        "score": score,
        "level": level,
        "energy": energy,
        "birthdate": birthdate,
        "rank": rank_name,
        "global_rank": global_rank,
        "next_rank_score": next_rank_score,
    }

@api_router.get("/quotes/random")
async def get_random_quote():
    quote = await db.get_random_quote()
    if not quote:
        return {"text": "Живи зараз.", "author": "Сенека", "category": "Час"}
    return quote

@api_router.get("/leaderboard")
async def get_leaderboard(limit: int = 20):
    users = await db.get_top_users(limit)
    return [
        {
            "user_id": user["user_id"],
            "username": user["username"] or "Мандрівник",
            "score": user["score"],
            "rank_name": get_stoic_rank(user["score"]),
        } for user in users
    ]

# --- АВТОРИЗАЦІЯ ТА СИНХРОНІЗАЦІЯ ---

@api_router.post("/auth/device")
async def device_auth(req: DeviceAuthRequest):
    device_id = req.device_id
    username = req.username
    birthdate_str = req.birthdate

    if not device_id:
        raise HTTPException(status_code=400, detail="Device ID обов'язковий")

    async with db.pool.acquire() as conn:
        # 1. Шукаємо юзера за device_id
        user = await conn.fetchrow("SELECT * FROM users WHERE device_id = $1", device_id)
        
        if user:
            # Юзер уже був у нас — повертаємо його дані
            # Це і є "фікс" фрізів та логаутів
            full_data = await db.get_full_user_data(user["user_id"])
            return {
                "status": "exists",
                "user_id": int(user["user_id"]),
                "user_data": full_data
            }
        
        # 2. Якщо пристрою немає — створюємо нового гостя
        try:
            guest_id = random.randint(900000000, 999999999)
            b_date = datetime.strptime(birthdate_str, "%Y-%m-%d").date()
            
            # Створюємо юзера
            await db.add_user(guest_id, username, b_date)
            # Прив'язуємо пристрій
            await conn.execute("UPDATE users SET device_id = $1 WHERE user_id = $2", device_id, guest_id)
            
            return {
                "status": "success",
                "user_id": guest_id,
                "user_data": {
                    "username": username,
                    "birthdate": birthdate_str,
                    "score": 0,
                    "level": 1
                }
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/auth/sync")
async def sync_with_code(req: SyncRequest):
    # req.code, req.guest_id, req.device_id
    
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            # 1. Перевірка коду синхронізації
            row = await conn.fetchrow(
                "DELETE FROM sync_codes WHERE code = $1 AND expires_at > (now() AT TIME ZONE 'utc') RETURNING user_id",
                req.code
            )
            if not row:
                raise HTTPException(status_code=401, detail="Код недійсний")
            
            tg_id = row["user_id"]
            gst_id = req.guest_id

            # 2. Отримуємо ВСІ дані гостя перед видаленням
            guest = await conn.fetchrow(
                "SELECT username, birthdate, score, level FROM users WHERE user_id = $1", 
                gst_id
            )

            if guest:
                # 3. ОНОВЛЮЄМО основний ТГ-профіль даними з телефона
                # Ми беремо ім'я (username) та дату народження з телефона,
                # а бали (score) додаємо до існуючих.
                await conn.execute("""
                    UPDATE users 
                    SET username = $1, 
                        birthdate = $2, 
                        score = score + $3, 
                        level = GREATEST(level, $4),
                        device_id = $5,
                        user_type = 'synced'
                    WHERE user_id = $6
                """, 
                guest["username"], guest["birthdate"], guest["score"], guest["level"], req.device_id, tg_id)

                # 4. Переносимо прогрес Академії та Журнал
                await conn.execute("""
                    INSERT INTO user_academy_progress (user_id, article_id, read_at)
                    SELECT $1, article_id, read_at FROM user_academy_progress WHERE user_id = $2
                    ON CONFLICT (user_id, article_id) DO NOTHING
                """, tg_id, gst_id)
                
                await conn.execute("UPDATE journal SET user_id = $1 WHERE user_id = $2", tg_id, gst_id)
                await conn.execute("UPDATE game_history SET user_id = $1 WHERE user_id = $2", tg_id, gst_id)

                # 5. Видаляємо тепер уже порожній гостьовий профіль
                await conn.execute("DELETE FROM users WHERE user_id = $1", gst_id)
            else:
                # Якщо раптом гостя не знайшли, просто прив'язуємо пристрій до ТГ
                await conn.execute("UPDATE users SET device_id = $1 WHERE user_id = $2", req.device_id, tg_id)

            # 6. Повертаємо чистий, об'єднаний профіль
            user_data = await db.get_full_user_data(tg_id)
            return {"status": "success", "user_id": int(tg_id), "user_data": user_data}

# --- STOIC GYM ---

@api_router.get("/gym/scenario/{user_id}")
async def get_next_gym_scenario(user_id: int):
    energy = await db.check_energy(user_id)
    if energy <= 0:
        summary = await db.get_daily_summary(user_id)
        return {"error": "no_energy", "message": "Енергія вичерпана", "summary": summary}
    
    score, level, _ = await db.get_stats(user_id)
    max_scenarios = await db.pool.fetchval("SELECT COUNT(*) FROM scenarios")
    target_id = level if level <= max_scenarios else random.randint(1, max_scenarios)
    scenario = await db.get_scenario_by_level(target_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Сценарій не знайдено")
    return {"scenario": scenario, "energy": energy, "level": level, "is_endless": level > max_scenarios}

@api_router.post("/gym/answer")
async def submit_gym_answer(data: GymAnswer):
    # 1. Отримуємо актуальний стан користувача безпосередньо з БД
    current_score, db_level, _ = await db.get_stats(data.user_id)
    
    # 2. ВАЛІДАЦІЯ: Перевіряємо, чи рівень, який прислав клієнт, збігається з рівнем у БД
    # Якщо юзер намагається вдруге прислати відповідь на той самий рівень (data.level == db_level - 1)
    # або старий рівень (data.level < db_level), ми відхиляємо запит.
    if data.level != db_level:
        raise HTTPException(
            status_code=400, 
            detail="Цей рівень вже пройдено або дані застаріли. Не хитруй, стоїку!"
        )
    
    # 3. Перевірка енергії (додатковий захист, щоб не піти в мінус)
    energy = await db.check_energy(data.user_id)
    if energy <= 0:
        raise HTTPException(status_code=403, detail="Енергія вичерпана")

    # 4. Розрахунок нових значень
    new_score = current_score + data.score
    new_level = db_level + 1 # Переходимо на наступний рівень
    
    # 5. Атомарне оновлення бази
    await db.update_game_progress(data.user_id, new_score, new_level)
    await db.decrease_energy(data.user_id)
    await db.log_move(data.user_id, data.level, data.score)
    
    return {
        "status": "success", 
        "new_score": new_score, 
        "new_level": new_level,
        "energy_left": energy - 1
    }

# --- АКАДЕМІЯ ---

@api_router.get("/academy/status/{user_id}")
async def get_academy_status(user_id: int):
    count, rank = await db.get_academy_progress(user_id)
    daily_count = await db.get_daily_academy_count(user_id)
    return {"total_learned": count, "rank": rank, "daily_count": daily_count, "can_learn_more": daily_count < 5}

@api_router.get("/academy/articles")
async def get_articles(limit: int = 50, offset: int = 0):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, day, month, title FROM academy_articles ORDER BY month, day LIMIT $1 OFFSET $2", limit, offset)
        return [dict(row) for row in rows]

@api_router.get("/academy/articles/{article_id}")
async def get_article_detail(article_id: int):
    article = await db.get_article_by_id(article_id)
    if not article: raise HTTPException(status_code=404, detail="Статтю не знайдено")
    return article

@api_router.get("/academy/library/{user_id}")
async def get_library(user_id: int):
    return await db.get_user_library(user_id, limit=100)

@api_router.get("/academy/check/{user_id}/{article_id}")
async def check_article(user_id: int, article_id: int):
    is_read = await db.is_article_read(user_id, article_id)
    return {"is_read": is_read}

@api_router.post("/academy/complete")
async def complete_lesson(req: AcademyReadRequest):
    daily_count = await db.get_daily_academy_count(req.user_id)
    if daily_count >= 5: return {"success": False, "error": "limit_reached"}
    is_new = await db.mark_article_as_read(req.user_id, req.article_id)
    return {"success": True, "is_new": is_new}

# --- ЩОДЕННИК ---

@api_router.get("/journal/history/{user_id}")
async def get_journal_history(user_id: int, limit: int = 10):
    entries = await db.get_journal_entries(user_id, limit)
    return [dict(e) for e in entries]

@api_router.post("/journal/save")
async def save_journal_entry(req: JournalEntry):
    await db.save_journal_entry(req.user_id, req.text)
    return {"status": "success"}

@api_router.delete("/journal/delete/{entry_id}")
async def delete_journal_entry(entry_id: int, user_id: int):
    await db.delete_journal_entry(user_id, entry_id)
    return {"status": "success"}

# --- ШІ МЕНТОР ---

@api_router.get("/mentor/history/{user_id}")
async def get_mentor_history(user_id: int):
    entries = await db.get_mentor_history(user_id)
    return [dict(e) for e in entries]

@api_router.post("/mentor/chat")
async def mentor_chat(req: MentorRequest):
    try:
        if not req.messages: 
            return {"reply": "Я не почув твого питання."}
        
        last_msg = req.messages[-1]["content"]
        
        # ❌ ВИДАЛЯЄМО ЦЕЙ РЯДОК:
        # await db.add_user(req.user_id, "Мандрівник") 
        
        # Просто зберігаємо повідомлення. 
        # Якщо юзера немає в базі, db.save_mentor_message сам це виправить (через try/except)
        await db.save_mentor_message(req.user_id, "user", last_msg)
        
        response = await client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[{"role": "system", "content": SYSTEM_PROMPT_AI_MSG}] + req.messages, 
            temperature=0.7
        )
        reply = response.choices[0].message.content
        await db.save_mentor_message(req.user_id, "assistant", reply)
        
        return {"reply": reply}
    except Exception as e:
        return {"reply": "Мій розум зараз у тумані..."}

# --- ЛАБОРАТОРІЯ ---

@api_router.post("/lab/complete")
async def complete_lab_practice(req: LabComplete):
    new_score = await db.save_lab_practice(req.user_id, req.practice_type, req.score)
    return {"status": "success", "added_score": req.score, "total_score": new_score}

# --- Повне видалення користувача ---
@app.delete("/api/user/{user_id}")
async def delete_account(user_id: int):
    success = await db.delete_user_data(user_id)
    if success:
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="User not found")

app.include_router(api_router)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)