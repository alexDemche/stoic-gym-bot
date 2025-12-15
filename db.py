import sqlite3

class Database:
    def __init__(self, db_file):
        self.connection = sqlite3.connect(db_file)
        self.cursor = self.connection.cursor()
        self.create_tables()

    def create_tables(self):
        with self.connection:
            # Створюємо таблицю (якщо її немає)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    score INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    birthdate TEXT
                )
            """)
            
            # ХАК: Перевіряємо, чи є колонка username (для тих, хто вже створив базу раніше)
            try:
                self.connection.execute("SELECT username FROM users LIMIT 1")
            except sqlite3.OperationalError:
                # Якщо колонки немає - додаємо її
                self.connection.execute("ALTER TABLE users ADD COLUMN username TEXT")

    def user_exists(self, user_id):
        with self.connection:
            result = self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchall()
            return bool(len(result))

    def add_user(self, user_id, username):
        """Додає користувача або оновлює його ім'я, якщо він вже є"""
        if not self.user_exists(user_id):
            with self.connection:
                self.cursor.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        else:
            # Якщо юзер вже є, оновимо його ім'я (раптом він його змінив в ТГ)
            with self.connection:
                self.cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))

    def get_stats(self, user_id):
        with self.connection:
            result = self.cursor.execute("SELECT score, level FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not result:
                return 0, 1
            return result[0], result[1]

    def update_game_progress(self, user_id, score, level):
        with self.connection:
            self.cursor.execute("UPDATE users SET score = ?, level = ? WHERE user_id = ?", (score, level, user_id))

    def set_birthdate(self, user_id, birthdate):
        with self.connection:
            self.cursor.execute("UPDATE users SET birthdate = ? WHERE user_id = ?", (birthdate, user_id))

    def get_birthdate(self, user_id):
        with self.connection:
            result = self.cursor.execute("SELECT birthdate FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return result[0] if result else None

    # --- НОВА ФУНКЦІЯ: ТОП ГРАВЦІВ ---
    def get_top_users(self, limit=10):
        with self.connection:
            return self.cursor.execute(
                "SELECT username, score FROM users ORDER BY score DESC LIMIT ?", 
                (limit,)
            ).fetchall()