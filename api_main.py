import os
import uvicorn
from fastapi import FastAPI, HTTPException, Header, Depends, APIRouter # Додали APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from db import Database
from utils import get_stoic_rank

# --- НАЛАШТУВАННЯ ---
ADMIN_TOKEN = os.getenv("ADMIN_SECRET_TOKEN")

async def verify_admin(x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Ви не маєте прав для цієї дії")
    return x_admin_token

app = FastAPI(title="Stoic Trainer API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = Database()

# --- СТВОРЮЄМО РОУТЕР З ПРЕФІКСОМ /api ---
api_router = APIRouter(prefix="/api")

class AcademyArticle(BaseModel):
    day: int
    month: int
    title: str
    content: str
    reflection: str = ""
    
# Модель для запиту на прочитання
class AcademyReadRequest(BaseModel):
    user_id: int
    article_id: int

@app.on_event("startup")
async def startup():
    await db.connect()
    await db.create_tables()
    await db.create_academy_table()
    await db.create_progress_table()

# Залишаємо root поза /api для перевірки статусу (healthcheck)
@app.get("/")
async def root():
    user_count = await db.count_users()
    return {"status": "online", "total_users": user_count}

# --- ДОДАЄМО ЕНДПОІНТИ В РОУТЕР ---

@api_router.get("/stats/{user_id}")
async def get_user_stats(user_id: int):
    # 1. Отримуємо 3 значення (score, level, name)
    score, level, name = await db.get_stats(user_id) 
    energy = await db.check_energy(user_id)
    birthdate = await db.get_birthdate(user_id)
    rank_name = get_stoic_rank(score)
    
    thresholds = [50, 150, 500, 1000, 2500, 5000]
    # За замовчуванням 0, якщо поріг не знайдено (максимальний рівень)
    next_rank_score = 0 

    # 2.
    for t in thresholds:
        if score < t:
            next_rank_score = t
            break
    
    return {
        "user_id": user_id, 
        "name": name,
        "score": score, 
        "level": level,
        "energy": energy,
        "birthdate": birthdate,
        "rank": rank_name,
        "next_rank_score": next_rank_score
    }

@api_router.get("/quotes/random")
async def get_random_quote():
    quote = await db.get_random_quote()
    if not quote:
        return {"text": "Живи зараз.", "author": "Сенека", "category": "Час"}
    return quote

@api_router.get("/gym/level/{level_num}")
async def get_gym_level(level_num: int):
    scenario = await db.get_scenario_by_level(level_num)
    if not scenario:
        raise HTTPException(status_code=404, detail="Рівень не знайдено")
    return scenario

@api_router.post("/articles/add")
async def add_article(article: AcademyArticle, token: str = Depends(verify_admin)):
    try:
        await db.add_academy_article(
            article.day, article.month, 
            article.title, article.content, article.reflection
        )
        return {"message": "Статтю додано успішно"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@api_router.get("/academy/articles/{article_id}")
async def get_article_detail(article_id: int):
    article = await db.get_article_by_id(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Статтю не знайдено")
    return article

# 1. Отримати всі статті та статус прогресу користувача
@api_router.get("/academy/status/{user_id}")
async def get_academy_status(user_id: int):
    count, rank = await db.get_academy_progress(user_id)
    daily_count = await db.get_daily_academy_count(user_id)
    return {
        "total_learned": count,
        "rank": rank,
        "daily_count": daily_count,
        "can_learn_more": daily_count < 5
    }

# 2. Список усіх статей (для головного списку)
@api_router.get("/academy/articles")
async def get_articles(limit: int = 50, offset: int = 0):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, day, month, title FROM academy_articles ORDER BY month, day LIMIT $1 OFFSET $2",
            limit, offset
        )
        return [dict(row) for row in rows]

# 3. Список вивчених статей (Бібліотека)
@api_router.get("/academy/library/{user_id}")
async def get_user_library(user_id: int):
    # Використовуємо твій метод з db.py
    articles = await db.get_user_library(user_id, limit=100)
    return articles

# 4. Перевірка конкретної статті (вивчена чи ні)
@api_router.get("/academy/check/{user_id}/{article_id}")
async def check_article(user_id: int, article_id: int):
    is_read = await db.is_article_read(user_id, article_id)
    return {"is_read": is_read}

# 5. Зарахувати урок
@api_router.post("/academy/complete")
async def complete_lesson(req: AcademyReadRequest):
    daily_count = await db.get_daily_academy_count(req.user_id)
    if daily_count >= 5:
        return {"success": False, "error": "limit_reached"}
    
    # mark_article_as_read вже повертає True, якщо це новий запис
    is_new = await db.mark_article_as_read(req.user_id, req.article_id)
    return {"success": True, "is_new": is_new}

@api_router.get("/leaderboard")
async def get_leaderboard(limit: int = 20):
    # Отримуємо топ користувачів через існуючий метод у db.py
    # Припускаємо, що він повертає список словників: [{'username': '...', 'score': ...}, ...]
    users = await db.get_top_users(limit)
    
    # Додаємо кожному користувачу його текстове звання
    leaderboard = []
    for user in users:
        leaderboard.append({
            "username": user['username'],
            "score": user['score'],
            "rank_name": get_stoic_rank(user['score'])
        })
    return leaderboard

# --- ПІДКЛЮЧАЄМО РОУТЕР ДО APP ---
app.include_router(api_router)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)