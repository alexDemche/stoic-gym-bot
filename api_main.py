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

@api_router.post("/auth/create_guest")
async def create_guest(req: GuestRequest):
    try:
        b_date = datetime.strptime(req.birthdate, "%Y-%m-%d").date()
        await db.add_user(req.user_id, req.username, b_date)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/auth/sync")
async def sync_with_code(req: SyncRequest):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM sync_codes WHERE code = $1 AND expires_at > (now() AT TIME ZONE 'utc') RETURNING user_id",
            req.code
        )
        if not row:
            raise HTTPException(status_code=401, detail="Код недійсний або застарів")
        
        user_id = row["user_id"]
        user_data = await db.get_full_user_data(user_id)
        academy_count, academy_rank = await db.get_academy_progress(user_id)
        user_data["academy_total"] = academy_count
        user_data["academy_rank"] = academy_rank
        return {"status": "success", "user_id": int(user_id), "user_data": user_data}

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
    current_score, current_level, _ = await db.get_stats(data.user_id)
    new_score = current_score + data.score
    new_level = current_level + 1
    await db.update_game_progress(data.user_id, new_score, new_level)
    await db.decrease_energy(data.user_id)
    await db.log_move(data.user_id, data.level, data.score)
    return {"status": "success", "new_score": new_score, "new_level": new_level}

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
        if not req.messages: return {"reply": "Я не почув твого питання."}
        last_msg = req.messages[-1]["content"]
        await db.add_user(req.user_id, "Мандрівник")
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

app.include_router(api_router)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)