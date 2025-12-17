import os
from datetime import datetime

import asyncpg
from dotenv import load_dotenv

load_dotenv()


class Database:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        self.pool = None

    async def connect(self):
        if not self.pool:
            try:
                self.pool = await asyncpg.create_pool(self.db_url)
                print("✅ Connected to Database")
            except Exception as e:
                print(f"❌ Database connection failed: {e}")

    async def create_tables(self):
        """Створює таблиці користувачів, журналу та історії"""
        async with self.pool.acquire() as conn:
            # 1. Таблиця користувачів
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    score INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    birthdate DATE,
                    energy INTEGER DEFAULT 5,
                    last_active_date DATE DEFAULT CURRENT_DATE
                )
            """
            )

            # 2. Таблиця журналу (щоденник)
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS journal (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    entry_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # 3. Таблиця історії ігор (для щоденного звіту)
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS game_history (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    level_num INTEGER,
                    points_earned INTEGER,
                    played_at DATE DEFAULT CURRENT_DATE
                )
            """
            )

            # МІГРАЦІЇ: Додаємо колонки для старих користувачів (якщо їх немає)
            try:
                await conn.execute(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS energy INTEGER DEFAULT 5"
                )
                await conn.execute(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active_date DATE DEFAULT CURRENT_DATE"
                )
            except Exception as e:
                print(f"Migration log: {e}")

    async def add_user(self, user_id, username):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (user_id, username)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET username = $2
            """,
                user_id,
                username,
            )

    async def get_stats(self, user_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT score, level FROM users WHERE user_id = $1", user_id
            )
            if row:
                return row["score"], row["level"]
            return 0, 1

    async def update_game_progress(self, user_id, score, level):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET score = $1, level = $2 WHERE user_id = $3",
                score,
                level,
                user_id,
            )

    async def get_top_users(self, limit=10):
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT username, score FROM users ORDER BY score DESC LIMIT $1", limit
            )

    async def count_users(self):
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM users")

    async def set_birthdate(self, user_id, birth_date):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET birthdate = $1 WHERE user_id = $2",
                birth_date,
                user_id,
            )

    async def get_birthdate(self, user_id):
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT birthdate FROM users WHERE user_id = $1", user_id
            )

    async def get_all_users(self):
        """Повертає список всіх user_id для розсилки"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT user_id FROM users")
            return [row["user_id"] for row in rows]

    # --- ЕНЕРГІЯ ---

    async def check_energy(self, user_id):
        """
        Перевіряє енергію.
        Якщо настав новий день - відновлює до 5.
        Повертає поточну енергію.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT energy, last_active_date FROM users WHERE user_id = $1", user_id
            )

            if not row:
                return 0

            current_energy = row["energy"]
            # Конвертуємо в date, бо база може повернути datetime
            last_date = row["last_active_date"]
            today = datetime.now().date()

            # Якщо останній раз грали не сьогодні — відновлюємо енергію
            if last_date < today:
                current_energy = 5
                await conn.execute(
                    "UPDATE users SET energy = 5, last_active_date = $1 WHERE user_id = $2",
                    today,
                    user_id,
                )

            return current_energy

    async def decrease_energy(self, user_id):
        """Зменшує енергію на 1"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET energy = energy - 1 WHERE user_id = $1", user_id
            )

    async def add_energy(self, user_id, amount=1):
        """Додає енергію (але не більше ліміту 5)"""
        async with self.pool.acquire() as conn:
            current = await conn.fetchval(
                "SELECT energy FROM users WHERE user_id = $1", user_id
            )
            if current is not None and current < 5:
                await conn.execute(
                    "UPDATE users SET energy = energy + $1 WHERE user_id = $2",
                    amount,
                    user_id,
                )
                return True
            return False

    # --- ЩОДЕННИК (JOURNAL) ---

    async def save_journal_entry(self, user_id, text):
        """Зберігає запис у щоденник"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO journal (user_id, entry_text) VALUES ($1, $2)",
                user_id,
                text,
            )

    async def get_journal_entries(self, user_id, limit=5):
        """Отримує останні записи щоденника"""
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT entry_text, created_at FROM journal WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
                user_id,
                limit,
            )

    # --- ІСТОРІЯ ІГОР (GAME HISTORY) ---

    async def log_move(self, user_id, level, points):
        """Записує результат ходу в історію"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO game_history (user_id, level_num, points_earned) VALUES ($1, $2, $3)",
                user_id,
                level,
                points,
            )

    async def get_daily_summary(self, user_id):
        """Повертає статистику за сьогодні"""
        async with self.pool.acquire() as conn:
            # Беремо всі записи за сьогоднішню дату
            rows = await conn.fetch(
                """
                SELECT points_earned FROM game_history
                WHERE user_id = $1 AND played_at = CURRENT_DATE
            """,
                user_id,
            )

            if not rows:
                return None

            total_moves = len(rows)
            total_points = sum(r["points_earned"] for r in rows)
            # Рахуємо помилки (де бали < 0)
            mistakes = sum(1 for r in rows if r["points_earned"] < 0)
            # Рахуємо ідеальні рішення (де бали > 0)
            wisdoms = sum(1 for r in rows if r["points_earned"] > 0)

            return {
                "moves": total_moves,
                "points": total_points,
                "mistakes": mistakes,
                "wisdoms": wisdoms,
            }
