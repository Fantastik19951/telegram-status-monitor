"""
Скрипт для генерации StringSession.
Запустите локально один раз, затем добавьте SESSION_STRING в переменные Railway.
"""

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = 36223250
API_HASH = "6eda43df31ea7a2108a34a6d28df52f5"


async def main():
    print("Генерация StringSession...")
    print("Введите номер телефона и код подтверждения.\n")
    
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.start()
    
    session_string = client.session.save()
    
    print("\n" + "=" * 60)
    print("✅ SESSION_STRING сгенерирован!")
    print("=" * 60)
    print("\nДобавьте эту строку в переменные Railway:")
    print(f"\nSESSION_STRING={session_string}")
    print("\n" + "=" * 60)
    
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
