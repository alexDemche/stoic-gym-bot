import psycopg2
import os

# Використовуємо DATABASE_URL, яку надає Railway
DATABASE_URL = os.environ.get('DATABASE_URL')

class Database:
    def __init__(self):
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL environment variable is not set!")
        
        self.conn = self.get_connection()
        self.create_tables()

    def get_connection(self):
        """Встановлює та повертає з'єднання з PostgreSQL"""
        # Параметри з'єднання беруться автоматично з DATABASE_URL
        return psycopg2.connect(DATABASE_URL)

    def create_tables(self):
        """Створює таблицю користувачів, якщо її ще немає"""
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        username TEXT,
                        score INTEGER DEFAULT 0,
                        level INTEGER DEFAULT 1,
                        birthdate DATE
                    )
                """)
            self.conn.commit()

    def user_exists(self, user_id):
        """Перевіряє, чи є користувач у базі"""
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
                return bool(cur.fetchone())

    def add_user(self, user_id, username):
        """Додає нового користувача або оновлює його ім'я"""
        with self.conn:
            with self.conn.cursor() as cur:
                if not self.user_exists(user_id):
                    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s)", (user_id, username))
                else:
                    cur.execute("UPDATE users SET username = %s WHERE user_id = %s", (username, user_id))
            self.conn.commit()

    def get_stats(self, user_id):
        """Повертає статистику (score, level)"""
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute("SELECT score, level FROM users WHERE user_id = %s", (user_id,))
                result = cur.fetchone()
                return result if result else (0, 1)

    def update_game_progress(self, user_id, score, level):
        """Оновлює рахунок та рівень"""
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute("UPDATE users SET score = %s, level = %s WHERE user_id = %s", (score, level, user_id))
            self.conn.commit()

    def set_birthdate(self, user_id, birthdate):
        """Зберігає дату народження"""
        # birthdate тут має бути об'єктом datetime.date
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute("UPDATE users SET birthdate = %s WHERE user_id = %s", (birthdate, user_id))
            self.conn.commit()

    def get_birthdate(self, user_id):
        """Отримує дату народження (повертає об'єкт date або None)"""
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute("SELECT birthdate FROM users WHERE user_id = %s", (user_id,))
                result = cur.fetchone()
                return result[0] if result and result[0] else None

    def get_top_users(self, limit=10):
        """Повертає топ-користувачів"""
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT username, score FROM users ORDER BY score DESC LIMIT %s",
                    (limit,)
                )
                return cur.fetchall()

    def count_users(self):
        """Рахує кількість користувачів"""
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users")
                return cur.fetchone()[0]