import os
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from db import Database

from utils import get_stoic_rank

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
async def add_article(article: AcademyArticle):
    try:
        await db.add_academy_article(
            article.day, 
            article.month, 
            article.title, 
            article.content, 
            article.reflection
        )
        return {"message": f"Стаття '{article.title}' успішно додана на {article.day}.{article.month}"}
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)