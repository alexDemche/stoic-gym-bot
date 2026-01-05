import os
import random
from datetime import datetime
from contextlib import asynccontextmanager

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from config import SYSTEM_PROMPT_AI_MSG
from db import Database
from utils import get_stoic_rank

# --- МОДЕЛІ ДАНИХ (Pydantic) ---
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

# --- НАЛАШТУВАННЯ ---
ADMIN_TOKEN = os.getenv("ADMIN_SECRET_TOKEN")
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
db = Database()

# Сучасний спосіб керування життєвим циклом (замість on_event)
@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await db.create_tables()
    await db.create_academy_table()
    await db.create_progress_table()
    yield
    # Тут можна закрити підключення, якщо треба: await db.disconnect()

app = FastAPI(title="Stoic Trainer API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Статика
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

api_router = APIRouter(prefix="/api")

# --- АДМІН ВАЛІДАЦІЯ ---
async def verify_admin(x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Невірний токен адміна")
    return x_admin_token

# --- ЕНДПОІНТИ ---

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

@api_router.get("/gym/scenario/{user_id}")
async def get_next_gym_scenario(user_id: int):
    energy = await db.check_energy(user_id)
    if energy <= 0:
        summary = await db.get_daily_summary(user_id)
        return {"error": "no_energy", "message": "Енергія вичерпана", "summary": summary}

    score, level, _ = await db.get_stats(user_id)
    max_scenarios = await db.pool.fetchval("SELECT COUNT(*) FROM scenarios")
    
    # Endless mode logic
    target_id = level if level <= max_scenarios else random.randint(1, max_scenarios)
    scenario = await db.get_scenario_by_level(target_id)

    if not scenario:
        raise HTTPException(status_code=404, detail="Сценарій не знайдено")

    return {
        "scenario": scenario,
        "energy": energy,
        "level": level,
        "is_endless": level > max_scenarios,
        "max_levels": max_scenarios,
    }

@api_router.post("/gym/answer")
async def submit_gym_answer(data: GymAnswer):
    current_score, current_level, _ = await db.get_stats(data.user_id)
    
    new_score = current_score + data.score
    new_level = current_level + 1
    
    await db.update_game_progress(data.user_id, new_score, new_level)
    await db.decrease_energy(data.user_id)
    await db.log_move(data.user_id, data.level, data.score)

    return {"status": "success", "new_score": new_score, "new_level": new_level}

@api_router.post("/mentor/chat")
async def mentor_chat(req: MentorRequest):
    try:
        if not req.messages:
            return {"reply": "Я не почув твого питання, мій друже."}

        last_user_msg = req.messages[-1]["content"]
        await db.add_user(req.user_id, "Мандрівник") # Fallback
        await db.save_mentor_message(req.user_id, "user", last_user_msg)

        response = await client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[{"role": "system", "content": SYSTEM_PROMPT_AI_MSG}] + req.messages, 
            temperature=0.7
        )
        reply = response.choices[0].message.content
        await db.save_mentor_message(req.user_id, "assistant", reply)

        return {"reply": reply}
    except Exception as e:
        print(f"AI Error: {e}")
        return {"reply": "Мій розум зараз у тумані... Спробуй пізніше."}

@api_router.post("/auth/create_guest")
async def create_guest(req: GuestRequest):
    try:
        b_date = datetime.strptime(req.birthdate, "%Y-%m-%d").date()
        await db.add_user(req.user_id, req.username, b_date)
        return {"status": "success"}
    except ValueError:
        raise HTTPException(status_code=400, detail="Невірний формат дати. Використовуйте РРРР-ММ-ДД")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/lab/complete")
async def complete_lab_practice(req: LabComplete):
    new_score = await db.save_lab_practice(req.user_id, req.practice_type, req.score)
    return {
        "status": "success",
        "practice_type": req.practice_type,
        "added_score": req.score,
        "total_score": new_score,
    }

# Підключаємо роутер
app.include_router(api_router)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)