import sqlite3

class Database:
    def __init__(self, db_file):
        self.connection = sqlite3.connect(db_file)
        self.cursor = self.connection.cursor()
        self.create_tables()

    def create_tables(self):
        """Створює таблицю користувачів, якщо її ще немає"""
        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    score INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    birthdate TEXT
                )
            """)

    def user_exists(self, user_id):
        """Перевіряє, чи є користувач у базі"""
        with self.connection:
            result = self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchall()
            return bool(len(result))

    def add_user(self, user_id):
        """Додає нового користувача"""
        if not self.user_exists(user_id):
            with self.connection:
                self.cursor.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))

    def get_stats(self, user_id):
        """Повертає статистику (score, level)"""
        with self.connection:
            result = self.cursor.execute("SELECT score, level FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not result:
                return 0, 1 # Дефолтні значення
            return result[0], result[1]

    def update_game_progress(self, user_id, score, level):
        """Оновлює рахунок та рівень"""
        with self.connection:
            self.cursor.execute("UPDATE users SET score = ?, level = ? WHERE user_id = ?", (score, level, user_id))

    def set_birthdate(self, user_id, birthdate):
        """Зберігає дату народження"""
        with self.connection:
            self.cursor.execute("UPDATE users SET birthdate = ? WHERE user_id = ?", (birthdate, user_id))

    def get_birthdate(self, user_id):
        """Отримує дату народження"""
        with self.connection:
            result = self.cursor.execute("SELECT birthdate FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return result[0] if result else None