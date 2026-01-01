import os
import uvicorn
from openai import AsyncOpenAI
from fastapi import FastAPI, HTTPException, Header, Depends, APIRouter # Додали APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from db import Database
from utils import get_stoic_rank

# --- НАЛАШТУВАННЯ ---
ADMIN_TOKEN = os.getenv("ADMIN_SECRET_TOKEN")
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


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
    global_rank = await db.get_user_position(user_id)
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
        "global_rank": global_rank,
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

@api_router.get("/gym/scenario/{user_id}")
async def get_next_gym_scenario(user_id: int):
    energy = await db.check_energy(user_id)
    
    if energy <= 0:
        # Викликаємо твій існуючий метод з db.py
        summary = await db.get_daily_summary(user_id)
        return {
            "error": "no_energy", 
            "message": "Енергія вичерпана",
            "summary": summary # Додаємо об'єкт зі статистикою
        }

    # 2. Отримуємо поточний рівень
    score, level, _ = await db.get_stats(user_id)
    
    # 3. Отримуємо сценарій (в db.py вже є get_scenario_by_level)
    # Якщо рівень > сенаріїв гри, підставляємо випадковий (Endless Mode)
    max_scenarios = await db.pool.fetchval("SELECT COUNT(*) FROM scenarios")
    # 4. Логіка вибору ID сценарію
    is_endless = level > max_scenarios
    if not is_endless:
        target_id = level # Йдемо по порядку 1, 2, 3... 100
    else:
        # Вибираємо випадковий сценарій з тих, що існують
        target_id = random.randint(1, max_scenarios)
    
    scenario = await db.get_scenario_by_level(target_id)
    
    if not scenario:
        return {"error": "not_found", "message": "Сценарій не знайдено."}

    return {
        "scenario": scenario,
        "energy": energy,
        "level": level,
        "is_endless": is_endless,
        "max_levels": max_scenarios
    }

@api_router.post("/gym/answer")
async def submit_gym_answer(data: dict):
    user_id = data.get("user_id")
    option_score = data.get("score") # бали за обраний варіант
    level = data.get("level")
    
    # 1. Отримуємо поточні статки
    current_score, current_level, _ = await db.get_stats(user_id)
    
    # 2. Оновлюємо прогрес (бали + рівень)
    new_score = current_score + option_score
    new_level = current_level + 1
    await db.update_game_progress(user_id, new_score, new_level)
    
    # 3. Списуємо енергію та записуємо в історію
    await db.decrease_energy(user_id)
    await db.log_move(user_id, level, option_score)
    
    return {"status": "success", "new_score": new_score, "new_level": new_level}

# Щоденник
@api_router.post("/journal/save")
async def save_entry(data: dict):
    user_id = data.get("user_id")
    text = data.get("text")
    if not user_id or not text:
        return {"error": "missing_data"}
    
    await db.save_journal_entry(user_id, text)
    return {"status": "success"}

@api_router.get("/journal/history/{user_id}")
async def get_history(user_id: int, limit: int = 5):
    entries = await db.get_journal_entries(user_id, limit)
    # Перетворюємо записи з бази у список словників для JSON
    return [dict(e) for e in entries]

@api_router.delete("/journal/delete/{entry_id}")
async def delete_entry(entry_id: int, user_id: int):
    await db.delete_journal_entry(user_id, entry_id)
    return {"status": "success"}

# ШІ Ментор
@api_router.post("/mentor/chat")
async def mentor_chat(data: dict):
    user_id = data.get("user_id")
    # Отримуємо масив повідомлень з фронтенда: [{"role": "user", "content": "..."}, ...]
    messages = data.get("messages", []) 
    
    system_message = {
        "role": "system", 
        "content": """Ти — Марк Аврелій, римський імператор. Спілкуйся українською. 
        Твій тон: спокійний та емпатичний. Допомагай відділяти те, що ми контролюємо, від того, що ні. 
        Відповідай лаконічно (до 100 слів)."""
    }

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[system_message] + messages, # Додаємо системний промпт до історії
            temperature=0.7,
        )
        return {"reply": response.choices[0].message.content}
    except Exception as e:
        return {"reply": "Мій розум зараз у тумані... Спробуймо пізніше."}

# --- ПІДКЛЮЧАЄМО РОУТЕР ДО APP ---
app.include_router(api_router)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)