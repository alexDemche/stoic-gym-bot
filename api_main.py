import os
import random
from datetime import datetime
from contextlib import asynccontextmanager
from constants import (
    ACADEMY_REWARD,
    LAB_POINTS_PER_MINUTE, 
    LAB_MAX_POINTS_PER_SESSION, 
    LAB_MIN_SECONDS,
    LAB_DAILY_POINTS_LIMIT
)

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyHeader
from openai import AsyncOpenAI
from pydantic import BaseModel

from config import SYSTEM_PROMPT_AI_MSG
from db import Database
from utils import get_stoic_rank

# --- МОДЕЛІ ДАНИХ (ОНОВЛЕНІ: без user_id там, де не треба) ---
class GymAnswer(BaseModel):
    # user_id прибрали!
    score: int
    level: int

class JournalEntry(BaseModel):
    # user_id прибрали!
    text: str

class MentorRequest(BaseModel):
    # user_id прибрали!
    messages: list

class GuestRequest(BaseModel):
    user_id: int # Тут залишаємо, це ID пристрою при реєстрації
    username: str
    birthdate: str

class AcademyReadRequest(BaseModel):
    # user_id прибрали!
    article_id: int
    # score: int

class LabCompleteRequest(BaseModel):
    # user_id прибрали!
    practice_type: str
    duration_seconds: int

class SyncRequest(BaseModel):
    code: str

# --- НАЛАШТУВАННЯ ---
ADMIN_TOKEN = os.getenv("ADMIN_SECRET_TOKEN")
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY") # Крок 1 (API Key)

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

# --- БЕЗПЕКА: 1. API KEY (Захист від ботів) ---
api_key_header = APIKeyHeader(name="X-App-Token", auto_error=False)

async def verify_app_token(token: str = Security(api_key_header)):
    if not APP_SECRET_KEY: return True # Якщо не налаштували, пускаємо (для тесту)
    if token == APP_SECRET_KEY:
        return token
    raise HTTPException(status_code=403, detail="Invalid App Credentials")

# Застосовуємо API Key до всіх роутів
api_router = APIRouter(prefix="/api", dependencies=[Depends(verify_app_token)])

# --- БЕЗПЕКА: 2. USER AUTH (Захист від IDOR) ---
user_auth_header = APIKeyHeader(name="Authorization", auto_error=False)

async def get_current_user(token: str = Security(user_auth_header)):
    """Перевіряє токен користувача і повертає user_id"""
    if not token:
        raise HTTPException(status_code=401, detail="Missing auth token")
    
    # Викликаємо метод, який ти додав у db.py
    user_id = await db.get_user_id_by_token(token)
    
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid auth token")
        
    return user_id

# --- ЕНДПОІНТИ ЗАГАЛЬНІ (Публічні або напів-публічні) ---

@app.get("/")
async def root():
    user_count = await db.count_users()
    return {"status": "online", "total_users": user_count}

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
            # Тут user_id можна показувати (це публічний топ), або приховати
            "username": user["username"] or "Мандрівник",
            "score": user["score"],
            "rank_name": get_stoic_rank(user["score"]),
        } for user in users
    ]

# --- АВТОРИЗАЦІЯ (Тут ми ВИДАЄМО токени) ---

@api_router.post("/auth/create_guest")
async def create_guest(req: GuestRequest):
    try:
        b_date = datetime.strptime(req.birthdate, "%Y-%m-%d").date()
        # db.add_user тепер генерує токен всередині
        await db.add_user(req.user_id, req.username, b_date)
        
        # Нам треба повернути цей токен клієнту!
        # Оскільки add_user не повертає токен, ми дістанемо його окремим запитом 
        # (або можна переписати add_user щоб повертав, але так простіше зараз)
        # В даному випадку ми знаємо user_id (бо це реєстрація по Device ID)
        
        # Тимчасово: дістаємо токен, який щойно створився
        async with db.pool.acquire() as conn:
            token = await conn.fetchval("SELECT auth_token FROM users WHERE user_id = $1", req.user_id)

        return {"status": "success", "token": token}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/auth/sync")
async def sync_with_code(req: SyncRequest):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            DELETE FROM sync_codes 
            WHERE code = $1 AND expires_at > (now() AT TIME ZONE 'utc') 
            RETURNING user_id
            """,
            req.code
        )
        
        if not row:
            raise HTTPException(status_code=401, detail="Код недійсний")
        
        user_id = row["user_id"]
        
        # Тепер беремо повні дані, ВКЛЮЧАЮЧИ ТОКЕН
        user_data = await db.get_full_user_data(user_id)
        
        # Важливо: get_full_user_data має повертати auth_token. 
        # Якщо ні - дістанемо його:
        token = await conn.fetchval("SELECT auth_token FROM users WHERE user_id = $1", user_id)
        
        academy_count, academy_rank = await db.get_academy_progress(user_id)
        user_data["academy_total"] = academy_count
        user_data["academy_rank"] = academy_rank
        
        return {
            "status": "success", 
            "user_id": int(user_id), 
            "token": token, # <--- ПОВЕРТАЄМО ТОКЕН
            "user_data": user_data
        }

# --- ЗАХИЩЕНІ ЕНДПОІНТИ (Вимагають Token) ---
# Увага: скрізь user_id береться з get_current_user

@api_router.get("/stats") # Прибрав {user_id}
async def get_user_stats(user_id: int = Depends(get_current_user)):
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

# --- STOIC GYM ---

@api_router.get("/gym/scenario")
async def get_next_gym_scenario(user_id: int = Depends(get_current_user)):
    energy = await db.check_energy(user_id)
    if energy <= 0:
        summary = await db.get_daily_summary(user_id)
        return {"error": "no_energy", "message": "Енергія вичерпана", "summary": summary}
    
    score, level, _ = await db.get_stats(user_id)
    max_scenarios = await db.get_scenarios_count()
    target_id = level if level <= max_scenarios else random.randint(1, max_scenarios)
    scenario = await db.get_scenario_by_level(target_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Сценарій не знайдено")
    return {"scenario": scenario, "energy": energy, "level": level, "is_endless": level > max_scenarios}

@api_router.post("/gym/answer")
async def submit_gym_answer(
    data: GymAnswer, 
    user_id: int = Depends(get_current_user)
):
    current_score, db_level, _ = await db.get_stats(user_id)
    
    if data.level != db_level:
        raise HTTPException(status_code=400, detail="Дані застаріли")
    
    energy = await db.check_energy(user_id)
    if energy <= 0:
        raise HTTPException(status_code=403, detail="Енергія вичерпана")

    new_score = current_score + data.score
    new_level = db_level + 1
    
    await db.update_game_progress(user_id, new_score, new_level)
    await db.decrease_energy(user_id)
    await db.log_move(user_id, data.level, data.score)
    
    return {
        "status": "success", 
        "new_score": new_score, 
        "new_level": new_level,
        "energy_left": energy - 1
    }

# --- АКАДЕМІЯ ---

@api_router.get("/academy/status") # Прибрав {user_id}
async def get_academy_status(user_id: int = Depends(get_current_user)):
    count, rank = await db.get_academy_progress(user_id)
    daily_count = await db.get_daily_academy_count(user_id)
    return {"total_learned": count, "rank": rank, "daily_count": daily_count, "can_learn_more": daily_count < 5}

@api_router.get("/academy/articles")
async def get_articles(limit: int = 50, offset: int = 0, user_id: int = Depends(get_current_user)):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, day, month, title FROM academy_articles ORDER BY month, day LIMIT $1 OFFSET $2", limit, offset)
        return [dict(row) for row in rows]

@api_router.get("/academy/articles/{article_id}")
async def get_article_detail(article_id: int, user_id: int = Depends(get_current_user)):
    article = await db.get_article_by_id(article_id)
    if not article: raise HTTPException(status_code=404, detail="Статтю не знайдено")
    return article

@api_router.get("/academy/library") # Прибрав {user_id}
async def get_library(user_id: int = Depends(get_current_user)):
    return await db.get_user_library(user_id, limit=100)

@api_router.get("/academy/check/{article_id}") # Прибрав {user_id} з URL
async def check_article(article_id: int, user_id: int = Depends(get_current_user)):
    is_read = await db.is_article_read(user_id, article_id)
    return {"is_read": is_read}

# --- api_main.py ---

# 1. Оновлюємо модель (прибираємо score)
class AcademyReadRequest(BaseModel):
    article_id: int
    # score: int  <-- ВИДАЛЯЄМО ЦЕ ПОЛЕ. Фронт не повинен ним керувати.

# 2. Оновлюємо ендпоінт
@api_router.post("/academy/complete")
async def complete_lesson(
    req: AcademyReadRequest, 
    user_id: int = Depends(get_current_user)
):
    
    daily_count = await db.get_daily_academy_count(user_id)
    if daily_count >= 5: 
        return {"success": False, "error": "limit_reached"}
    
    # Передаємо наше фіксоване значення винагороди
    is_new, new_total_score = await db.mark_article_as_read(user_id, req.article_id, score=ACADEMY_REWARD)

    return {
        "success": True, 
        "is_new": is_new, 
        "new_score": new_total_score, # Віддаємо новий загальний рахунок
        "reward": ACADEMY_REWARD if is_new else 0 # Повідомляємо, скільки нарахували
    }

# --- ЩОДЕННИК ---

@api_router.get("/journal/history") # Прибрав {user_id}
async def get_journal_history(limit: int = 10, user_id: int = Depends(get_current_user)):
    entries = await db.get_journal_entries(user_id, limit)
    return [dict(e) for e in entries]

@api_router.post("/journal/save")
async def save_journal_entry(
    req: JournalEntry, 
    user_id: int = Depends(get_current_user)
):
    await db.save_journal_entry(user_id, req.text)
    return {"status": "success"}

@api_router.delete("/journal/delete/{entry_id}")
async def delete_journal_entry(entry_id: int, user_id: int = Depends(get_current_user)):
    # Функція в DB вже перевіряє user_id (DELETE ... AND user_id = $2)
    # Тому юзер не зможе видалити чужий запис
    await db.delete_journal_entry(user_id, entry_id)
    return {"status": "success"}

# --- ШІ МЕНТОР ---

@api_router.get("/mentor/history")
async def get_mentor_history(user_id: int = Depends(get_current_user)):
    entries = await db.get_mentor_history(user_id)
    return [dict(e) for e in entries]

@api_router.post("/mentor/chat")
async def mentor_chat(
    req: MentorRequest, 
    user_id: int = Depends(get_current_user)
):
    # 1. ЗАХИСТ ВІД ДОВГИХ ТЕКСТІВ (Економія токенів)
    # Беремо тільки останні 5 повідомлень (щоб пам'ятав контекст, але не всю історію)
    # І обрізаємо кожне повідомлення до 500 символів
    safe_messages = []
    if req.messages:
        for msg in req.messages[-5:]: 
            content = str(msg.get("content", ""))
            if len(content) > 500:
                content = content[:500] + "..." # Обрізаємо
            safe_messages.append({"role": msg["role"], "content": content})
    
    if not safe_messages:
         return {"reply": "Ти мовчиш..."}

    # 2. ЗАХИСТ ВІД СПАМУ (Rate Limiting)
    # Цей метод ми додали в db.py
    # limit_per_day=50 означає ~1.5$ в місяць макс. на юзера (дуже грубо)
    status_limit = await db.check_ai_limit(user_id, limit_per_day=50)
    
    if status_limit == "cooldown":
        # 429 Too Many Requests
        raise HTTPException(status_code=429, detail="Не поспішай. Дай мені 5 секунд на роздуми.")
    
    if status_limit == "limit_reached":
        raise HTTPException(status_code=429, detail="На сьогодні ліміт мудрості вичерпано. Приходь завтра.")

    # 3. ВИКОНАННЯ ЗАПИТУ
    try:
        # Зберігаємо останнє питання юзера
        last_msg = safe_messages[-1]["content"]
        await db.save_mentor_message(user_id, "user", last_msg)
        
        response = await client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[{"role": "system", "content": SYSTEM_PROMPT_AI_MSG}] + safe_messages, 
            temperature=0.7,
            max_tokens=350 # <-- ОБМЕЖЕННЯ ВІДПОВІДІ (щоб AI не писав занадто багато)
        )
        reply = response.choices[0].message.content
        await db.save_mentor_message(user_id, "assistant", reply)
        
        return {"reply": reply}
    except Exception as e:
        print(f"Error AI: {e}")
        # Якщо помилка, повертаємо щось філософське, щоб не лякати юзера кодами
        return {"reply": "Мій зв'язок із Логосом зараз перервано..."}

# --- ЛАБОРАТОРІЯ ---

@api_router.post("/lab/complete")
async def complete_lab_practice(
    req: LabCompleteRequest, 
    user_id: int = Depends(get_current_user)
):
    # 1. Відсіюємо випадкові кліки (надто короткі)
    if req.duration_seconds < LAB_MIN_SECONDS:
        return {"success": False, "error": "too_short", "message": "Практика занадто коротка"}

    # 2. Рахуємо чесні бали за час
    minutes = req.duration_seconds // 60
    calculated_score = minutes * LAB_POINTS_PER_MINUTE
    
    # Бонус: якщо менше хвилини, але більше 30 сек — даємо 1 бал заохочення
    if calculated_score < 1 and req.duration_seconds >= LAB_MIN_SECONDS:
        calculated_score = 1

    # 3. Обрізаємо аномально довгі сесії (макс 10 балів за раз)
    session_score = min(calculated_score, LAB_MAX_POINTS_PER_SESSION)

    # --- 🛑 ЗАХИСТ ВІД СПАМУ (Денний ліміт) ---
    today_score = await db.get_today_lab_points(user_id)
    
    if today_score >= LAB_DAILY_POINTS_LIMIT:
        # Ліміт вичерпано.
        # Можна повернути помилку, або записати практику з 0 балів (щоб зберегти статистику в історії, але не дати балів)
        session_score = 0
        # return {"success": False, "message": "Денний ліміт балів вичерпано!"} <--- Або так, якщо хочеш помилку

    # Коригування "хвоста": Якщо ліміт 50, вже є 48, а заробив 5 -> даємо тільки 2.
    elif today_score + session_score > LAB_DAILY_POINTS_LIMIT:
        session_score = LAB_DAILY_POINTS_LIMIT - today_score

    # 4. Зберігаємо (тільки якщо є що зберігати або треба записати факт історії)
    if session_score > 0:
        new_total_score = await db.save_lab_practice(user_id, req.practice_type, session_score)
    else:
        # Якщо балів 0, просто отримуємо поточний рахунок, щоб не поламати фронт
        # (можна викликати легкий SELECT або взяти з кешу, тут приклад через SELECT)
        data = await db.pool.fetchrow("SELECT score FROM users WHERE user_id = $1", user_id)
        new_total_score = data['score']

    return {
        "success": True, 
        "added_score": session_score, 
        "total_score": new_total_score
    }


# --- ВИДАЛЕННЯ АКАУНТА ---
@app.delete("/api/user/{target_user_id}")
async def delete_account(
    target_user_id: int, 
    # Ми дізнаємось, хто робить запит, через його токен
    requester_id: int = Depends(get_current_user)
):
    # Перевірка: чи намагається юзер видалити сам себе?
    if requester_id != target_user_id:
        # Якщо ID в токені не співпадає з ID, який хочуть видалити
        raise HTTPException(status_code=403, detail="Ви не можете видалити чужий акаунт")

    # Якщо перевірка пройшла успішно - видаляємо
    success = await db.delete_user_data(target_user_id)
    
    if success:
        return {"status": "deleted"}
        
    raise HTTPException(status_code=404, detail="User not found")

app.include_router(api_router)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)