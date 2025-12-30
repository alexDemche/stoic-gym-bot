import os
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from db import Database

app = FastAPI(title="Stoic Trainer API")
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
    score, level = await db.get_stats(user_id)
    return {
        "user_id": user_id, 
        "score": score, 
        "level": level,
        "rank": "Practical Stoic" # Тут можна додати логіку рангів
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)