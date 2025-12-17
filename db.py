import asyncpg
import os
from datetime import datetime

# Використовуємо DATABASE_URL, яку надає Railway
DATABASE_URL = os.environ.get('DATABASE_URL')

class Database:
    def __init__(self):
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL environment variable is not set!")
        self.pool = None

    async def connect(self):
        """Створює пул з'єднань"""
        self.pool = await asyncpg.create_pool(DATABASE_URL)

    async def create_tables(self):
        """Створює таблицю користувачів та оновлює структуру"""
        async with self.pool.acquire() as conn:
            # 1. Створення таблиці (якщо немає)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    score INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    birthdate DATE,
                    energy INTEGER DEFAULT 5,
                    last_active_date DATE DEFAULT CURRENT_DATE
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS journal (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    entry_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 2. МІГРАЦІЯ: Додаємо колонки для старих користувачів (якщо їх немає)
            # Це безпечний код: якщо колонка є, він нічого не зламає
            try:
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS energy INTEGER DEFAULT 5")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active_date DATE DEFAULT CURRENT_DATE")
            except Exception as e:
                print(f"Migration log: {e}")

    async def user_exists(self, user_id):
        """Перевіряє, чи є користувач у базі"""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1 FROM users WHERE user_id = $1", user_id)
            return bool(result)

    async def add_user(self, user_id, username):
        """Додає нового користувача або оновлює його ім'я"""
        # Увага: тут ми не викликаємо user_exists, щоб уникнути конфлікту
        # Використовуємо синтаксис SQL: ON CONFLICT
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username) VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET username = $2
            """, user_id, username)

    async def get_stats(self, user_id):
        """Повертає статистику (score, level)"""
        async with self.pool.acquire() as conn:
            result = await conn.fetchrow("SELECT score, level FROM users WHERE user_id = $1", user_id)
            return result if result else (0, 1)

    async def update_game_progress(self, user_id, score, level):
        """Оновлює рахунок та рівень"""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET score = $1, level = $2 WHERE user_id = $3", score, level, user_id)

    async def set_birthdate(self, user_id, birthdate):
        """Зберігає дату народження"""
        async with self.pool.acquire() as conn:
            # birthdate має бути об'єктом datetime.date
            await conn.execute("UPDATE users SET birthdate = $1 WHERE user_id = $2", birthdate, user_id)

    async def get_birthdate(self, user_id):
        """Отримує дату народження"""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("SELECT birthdate FROM users WHERE user_id = $1", user_id)
            return result # поверне datetime.date або None

    async def get_top_users(self, limit=10):
        """Повертає топ-користувачів"""
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT username, score FROM users ORDER BY score DESC LIMIT $1",
                limit
            )

    async def count_users(self):
        """Рахує кількість користувачів"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM users")
        
    async def get_all_users(self):
        """Повертає список всіх user_id"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT user_id FROM users")
            return [row['user_id'] for row in rows]
        
    async def check_energy(self, user_id):
        """
        Перевіряє енергію. 
        Якщо настав новий день - відновлює до 5.
        Повертає поточну енергію.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT energy, last_active_date FROM users WHERE user_id = $1", user_id)
            
            if not row:
                return 0
            
            current_energy = row['energy']
            last_date = row['last_active_date']
            today = datetime.now().date() # Потрібен import datetime зверху файлу db.py!
            
            # Якщо останній раз грали не сьогодні — відновлюємо енергію
            if last_date < today:
                current_energy = 5
                await conn.execute("UPDATE users SET energy = 5, last_active_date = $1 WHERE user_id = $2", today, user_id)
            
            return current_energy

    async def decrease_energy(self, user_id):
        """Зменшує енергію на 1"""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET energy = energy - 1 WHERE user_id = $1", user_id)
            
    async def save_journal_entry(self, user_id, text):
    """Зберігає запис у щоденник"""
    async with self.pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO journal (user_id, entry_text) VALUES ($1, $2)",
            user_id, text
        )

    async def get_journal_entries(self, user_id, limit=5):
        """Отримує останні записи щоденника"""
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT entry_text, created_at FROM journal WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
                user_id, limit
            )