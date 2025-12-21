import asyncio
import csv

from dotenv import load_dotenv

from db import Database

load_dotenv()


async def upload_articles(csv_file_path):
    db = Database()
    try:
        await db.connect()
        await db.create_academy_table()

        count = 0
        with open(csv_file_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Використовуємо ON CONFLICT для оновлення тексту, якщо дата вже є
                async with db.pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO academy_articles (day, month, title, content, reflection)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (day, month)
                        DO UPDATE SET title = $3, content = $4, reflection = $5
                        """,
                        int(row["day"]),
                        int(row["month"]),
                        row["title"],
                        row["content"],
                        row["reflection"],
                    )
                count += 1

        print(f"✅ Успішно синхронізовано {count} статей.")
    except Exception as e:
        print(f"❌ Помилка: {e}")
    finally:
        if db.pool:
            await db.pool.close()


if __name__ == "__main__":
    asyncio.run(upload_articles("academy.csv"))
