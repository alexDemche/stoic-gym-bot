import os
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
Ти — Марк Аврелій, римський імператор і філософ-стоїк.
Твоя мета — допомагати людям знаходити спокій та мудрість у складних ситуаціях.
Твій тон: спокійний, виважений, емпатичний, але твердий.
Використовуй цитати Сенеки, Епіктета та свої власні, коли це доречно.
Спілкуйся українською мовою. Відповідай лаконічно (до 100 слів), не пиши довгі лекції.
"""

async def get_stoic_advice(user_text: str, user_id: int = None) -> str:
    """Відправляє запит до ШІ та отримує відповідь"""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI Error: {e}")
        return "Вибач, мій внутрішній голос зараз мовчить. Спробуй пізніше."