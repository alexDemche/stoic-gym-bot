import asyncio
import os
import asyncpg
from openai import AsyncOpenAI
from dotenv import load_dotenv

# Завантажуємо змінні з .env (DATABASE_URL та OPENAI_API_KEY)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def translate_text(text: str, is_content: bool = False) -> str:
    """Переклад через ШІ з інструкцією для довгих текстів"""
    if not text:
        return ""
    
    # Для контенту статей використовуємо трохи вищий temperature для природності мови
    temp = 0.4 if is_content else 0.2
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": "You are a professional translator specializing in philosophy and Stoicism. "
                               "Translate from Ukrainian to English. Preserve all emojis, Markdown formatting, "
                               "and keep the wisdom-sharing tone. Don't add comments, just return the translation."
                },
                {"role": "user", "content": text}
            ],
            temperature=temp
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Error translating: {e}")
        return None

async def process_academy_translations():
    conn = await asyncpg.connect(DATABASE_URL)
    print("✅ Connected to database. Starting Academy translation...")

    # Шукаємо статті, де англійський контент ще порожній
    rows = await conn.fetch("""
        SELECT id, title, content, reflection 
        FROM academy_articles 
        WHERE content_en IS NULL OR content_en = ''
    """)
    
    print(f"Found {len(rows)} articles to translate.")

    for row in rows:
        print(f"--- Translating Article ID {row['id']}: {row['title'][:30]}... ---")
        
        # 1. Перекладаємо заголовок
        t_en = await translate_text(row['title'])
        # 2. Перекладаємо довгий контент
        c_en = await translate_text(row['content'], is_content=True)
        # 3. Перекладаємо рефлексію (практику)
        r_en = await translate_text(row['reflection'])

        if t_en and c_en:
            await conn.execute("""
                UPDATE academy_articles 
                SET title_en = $1, content_en = $2, reflection_en = $3 
                WHERE id = $4
            """, t_en, c_en, r_en, row['id'])
            print(f"✅ Saved translation for ID {row['id']}")
            
            # Невелика пауза, щоб не перевищити ліміти API при довгих текстах
            await asyncio.sleep(1) 
        else:
            print(f"⚠️ Skipping ID {row['id']} due to error.")

    await conn.close()
    print("\n🎉 Academy translation completed!")

if __name__ == "__main__":
    asyncio.run(process_academy_translations())