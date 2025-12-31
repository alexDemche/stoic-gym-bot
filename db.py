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
                "SELECT score, level, first_name FROM users WHERE user_id = $1", 
                user_id
            )
            if row:
                # Повертаємо score, level та ім'я
                return row['score'], row['level'], row['first_name']
            return 0, 1, "Мандрівник"

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

    # Академія Стоїцизму
    async def create_academy_table(self):
        """Створює таблицю для розгорнутих статей Академії"""
        async with self.pool.acquire() as conn:
            # 1. Створюємо саму таблицю
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS academy_articles (
                    id SERIAL PRIMARY KEY,
                    day INT NOT NULL,
                    month INT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    reflection TEXT,
                    -- Додаємо унікальність безпосередньо при створенні
                    UNIQUE (day, month)
                )
            """
            )

            # 2. Додатковий запит для існуючих таблиць (про всяк випадок)
            # Це гарантує, що якщо таблиця вже була створена раніше без UNIQUE, ми його додамо.
            try:
                await conn.execute(
                    """
                    ALTER TABLE academy_articles
                    ADD CONSTRAINT unique_day_month UNIQUE (day, month);
                """
                )
            except Exception:
                # Якщо констрейнт вже існує, база видасть помилку, ми її ігноруємо
                pass

    async def get_article_by_date(self, day: int, month: int):
        """Отримує статтю на конкретну дату"""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM academy_articles WHERE day = $1 AND month = $2",
                day,
                month,
            )

    # Метод для додавання статті (знадобиться для наповнення)
    async def add_academy_article(self, day, month, title, content, reflection):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO academy_articles (day, month, title, content, reflection)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT DO NOTHING
            """,
                day,
                month,
                title,
                content,
                reflection,
            )

    # --- НОВІ МЕТОДИ ДЛЯ АКАДЕМІЇ ---
    async def create_progress_table(self):
        """Створює таблицю для збереження прогресу навчання"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_academy_progress (
                    user_id BIGINT,
                    article_id INT,
                    read_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, article_id)
                )
            """
            )

    async def mark_article_as_read(self, user_id, article_id):
        """Позначає статтю як прочитану. Повертає True, якщо це вперше."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO user_academy_progress (user_id, article_id)
                VALUES ($1, $2) ON CONFLICT DO NOTHING
            """,
                user_id,
                article_id,
            )
            # "INSERT 0 1" означає, що рядок додався успішно (раніше не читав)
            return result == "INSERT 0 1"

    async def get_academy_progress(self, user_id):
        """Повертає кількість прочитаних статей та шкільний клас"""
        async with self.pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM user_academy_progress WHERE user_id = $1", user_id
            )

            # Система 11 класів
            # Перші класи — швидкий прогрес, далі — складніше
            if count < 1:
                rank = "👶 Дошкільня (Ще не почав)"
            elif count < 5:
                rank = "1️⃣ 1-й Клас (Новачок)"
            elif count < 10:
                rank = "2️⃣ 2-й Клас (Допитливий)"
            elif count < 20:
                rank = "3️⃣ 3-й Клас (Слухач)"
            elif count < 35:
                rank = "4️⃣ 4-й Клас (Молодший учень)"  # Випуск з початкової школи
            elif count < 50:
                rank = "5️⃣ 5-й Клас (Дослідник)"
            elif count < 70:
                rank = "6️⃣ 6-й Клас (Практик)"
            elif count < 100:
                rank = "7️⃣ 7-й Клас (Логік)"
            elif count < 150:
                rank = "8️⃣ 8-й Клас (Аналітик)"
            elif count < 200:
                rank = "9️⃣ 9-й Клас (Гімназист)"  # Неповна середня
            elif count < 300:
                rank = "🔟 10-й Клас (Філософ)"
            elif count < 365:
                rank = "1️⃣1️⃣ 11-й Клас (Випускник)"
            else:
                rank = "🎓 Магістр Стоїцизму (Університет)"  # Якщо пройде весь рік

            return count, rank

    async def is_article_read(self, user_id, article_id):
        """Перевіряє, чи читав користувач цю статтю раніше"""
        async with self.pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT 1 FROM user_academy_progress WHERE user_id = $1 AND article_id = $2",
                user_id, article_id
            )
            return bool(exists)

    async def get_daily_academy_count(self, user_id):
        """Рахує кількість уроків, засвоєних сьогодні"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """
                SELECT COUNT(*) FROM user_academy_progress 
                WHERE user_id = $1 AND read_at::date = CURRENT_DATE
                """,
                user_id
            )

    async def get_article_by_id(self, article_id):
        """Отримує статтю за її унікальним ID"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(  
                "SELECT * FROM academy_articles WHERE id = $1", 
                article_id
            )
            return dict(row) if row else None
        
    async def get_user_library(self, user_id, limit=5, offset=0):
        """Повертає список вивчених статей з пагінацією"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT a.id, a.title, a.day, a.month
                FROM academy_articles a
                JOIN user_academy_progress u ON a.id = u.article_id
                WHERE u.user_id = $1
                ORDER BY u.read_at DESC
                LIMIT $2 OFFSET $3
                """,
                user_id, limit, offset
            )
            return [dict(row) for row in rows]

    async def count_user_library(self, user_id):
        """Рахує загальну кількість вивчених статей"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM user_academy_progress WHERE user_id = $1", 
                user_id
            )
            
    # --- НОВІ ТАБЛИЦІ ДЛЯ ЦИТАТ ТА ГРИ ---
    async def create_content_tables(self):
        async with self.pool.acquire() as conn:
            # Таблиця цитат
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS quotes (
                    id SERIAL PRIMARY KEY,
                    text TEXT NOT NULL,
                    author TEXT,
                    category TEXT
                )
            """)
            # Таблиця сценаріїв Gym
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS scenarios (
                    id SERIAL PRIMARY KEY,
                    text TEXT NOT NULL
                )
            """)
            # Таблиця варіантів відповідей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS scenario_options (
                    id SERIAL PRIMARY KEY,
                    scenario_id INTEGER REFERENCES scenarios(id),
                    option_id TEXT, -- твій "lvl1_opt1"
                    text TEXT NOT NULL,
                    score INTEGER,
                    msg TEXT
                )
            """)

    async def get_random_quote(self):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT text, author, category FROM quotes ORDER BY RANDOM() LIMIT 1")
            return dict(row) if row else None

    async def get_scenario_by_level(self, level: int):
        async with self.pool.acquire() as conn:
            scenario = await conn.fetchrow("SELECT id, text FROM scenarios WHERE id = $1", level)
            if not scenario: return None
            options = await conn.fetch("SELECT option_id, text, score, msg FROM scenario_options WHERE scenario_id = $1", scenario['id'])
            return {
                "text": scenario['text'],
                "options": [dict(opt) for opt in options]
            }