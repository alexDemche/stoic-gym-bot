import os
import uvicorn
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from db import Database

from utils import get_stoic_rank

# Отримуємо токен із замінних оточення
ADMIN_TOKEN = os.getenv("ADMIN_SECRET_TOKEN")

# Функція перевірки (Dependency)
async def verify_admin(x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Ви не маєте прав для цієї дії")
    return x_admin_token

app = FastAPI(title="Stoic Trainer API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # У продакшені краще вказати конкретні домени
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
db = Database()

# Модель даних для додавання статті
class AcademyArticle(BaseModel):
    day: int
    month: int
    title: str
    content: str
    reflection: str = ""

@app.on_event("startup")
async def startup():
    await db.connect()
    # Створюємо таблиці, якщо вони ще не існують
    await db.create_tables()
    await db.create_academy_table()
    await db.create_progress_table()

@app.get("/")
async def root():
    user_count = await db.count_users()
    return {
        "status": "online",
        "service": "Stoic Trainer API",
        "total_users": user_count
    }

# МАРШРУТ ДЛЯ ЗАВАНТАЖЕННЯ СТАТЕЙ
@app.post("/articles/add")
async def add_article(article: AcademyArticle, token: str = Depends(verify_admin)):
    try:
        await db.add_academy_article(
            article.day, article.month, 
            article.title, article.content, article.reflection
        )
        return {"message": "Статтю додано успішно"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats/{user_id}")
async def get_user_stats(user_id: int):
    # Отримуємо дані з бази
    score, level = await db.get_stats(user_id)
    energy = await db.check_energy(user_id) 
    
    # Вираховуємо ранг на основі балів
    rank_name = get_stoic_rank(score)
    
    return {
        "user_id": user_id, 
        "score": score, 
        "level": level,
        "energy": energy,
        "rank": rank_name  # Тепер повертається динамічний ранг
    }
    
@app.get("/api/quotes/random")
async def get_random_quote():
    quote = await db.get_random_quote()
    if not quote:
        # Якщо в БД ще порожньо, віддаємо дефолтну, щоб додаток не впав
        return {"text": "Живи зараз.", "author": "Сенека", "category": "Час"}
    return quote

@app.get("/api/gym/level/{level_num}")
async def get_gym_level(level_num: int):
    scenario = await db.get_scenario_by_level(level_num)
    if not scenario:
        raise HTTPException(status_code=404, detail="Рівень не знайдено")
    return scenario

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)