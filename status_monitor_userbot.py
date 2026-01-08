"""
Telegram Userbot для мониторинга статуса активности контакта.
Использует Telethon для совместимости с Python 3.14.
"""

import os
import asyncio
import json
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import (
    UserStatusOnline,
    UserStatusOffline,
    UserStatusRecently,
    UserStatusLastWeek,
    UserStatusLastMonth,
    UserStatusEmpty
)
from telethon.errors import FloodWaitError
from telethon.tl.functions.contacts import GetContactsRequest
import aiohttp

from config import TARGET_CONTACT, CHECK_INTERVAL

load_dotenv()

API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

HISTORY_FILE = Path("activity_history.json")

previous_status_type = None
previous_last_online = None
my_chat_id = None


def load_history():
    """Загружает историю активности из файла."""
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(history):
    """Сохраняет историю активности в файл."""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def add_to_history(status_type: str, status_text: str, last_online=None):
    """Добавляет запись в историю (кроме 'недавно')."""
    if status_type == "recently":
        return
    
    history = load_history()
    entry = {
        "timestamp": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "status_type": status_type,
        "status_text": status_text,
        "contact": TARGET_CONTACT
    }
    if last_online:
        entry["last_online"] = last_online.strftime("%d.%m.%Y %H:%M:%S")
    
    history.append(entry)
    if len(history) > 100:
        history = history[-100:]
    save_history(history)


def get_status_type(status):
    """Возвращает тип статуса."""
    if isinstance(status, UserStatusOnline):
        return "online"
    elif isinstance(status, UserStatusOffline):
        return "offline"
    elif isinstance(status, UserStatusRecently):
        return "recently"
    elif isinstance(status, UserStatusLastWeek):
        return "last_week"
    elif isinstance(status, UserStatusLastMonth):
        return "last_month"
    else:
        return "unknown"


def format_status(status):
    """Форматирует статус пользователя в читаемый вид."""
    if isinstance(status, UserStatusOnline):
        return "🟢 В СЕТИ"
    elif isinstance(status, UserStatusOffline):
        if status.was_online:
            return f"⚪ Был(а) {status.was_online.strftime('%d.%m.%Y %H:%M:%S')}"
        return "⚪ Офлайн"
    elif isinstance(status, UserStatusRecently):
        return "🔵 Недавно"
    elif isinstance(status, UserStatusLastWeek):
        return "🔵 На этой неделе"
    elif isinstance(status, UserStatusLastMonth):
        return "🔵 В этом месяце"
    elif isinstance(status, UserStatusEmpty):
        return "⚫ Давно"
    else:
        return "❓ Неизвестно"


def print_notification(message, is_alert=False):
    """Выводит уведомление в терминал."""
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    if is_alert:
        print("\n" + "=" * 60)
        print(f"🚨 ВНИМАНИЕ! [{timestamp}]")
        print(f"   {message}")
        print("=" * 60 + "\n")
    else:
        print(f"[{timestamp}] {message}")


async def send_bot_notification(message: str):
    """Отправляет уведомление через Telegram бота."""
    global my_chat_id
    
    if not BOT_TOKEN or not my_chat_id:
        return
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": my_chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    print_notification(f"⚠️ Ошибка отправки в бота: {resp.status}")
    except Exception as e:
        print_notification(f"⚠️ Ошибка отправки в бота: {e}")


async def get_bot_chat_id():
    """Получает chat_id из последних обновлений бота."""
    global my_chat_id
    
    if not BOT_TOKEN:
        return None
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("result"):
                        my_chat_id = data["result"][-1]["message"]["chat"]["id"]
                        return my_chat_id
    except Exception as e:
        print_notification(f"⚠️ Не удалось получить chat_id: {e}")
    
    return None


async def find_contact_by_name(client, name: str):
    """Ищет контакт по имени в записной книге."""
    result = await client(GetContactsRequest(hash=0))
    for user in result.users:
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        if name.lower() in full_name.lower():
            return user
    return None


async def check_status(client, user_id: int):
    """Проверяет статус пользователя."""
    global previous_status_type, previous_last_online
    
    try:
        user = await client.get_entity(user_id)
        current_status = user.status
        current_status_type = get_status_type(current_status)
        
        current_last_online = None
        if isinstance(current_status, UserStatusOffline) and current_status.was_online:
            current_last_online = current_status.was_online
        
        status_text = format_status(current_status)
        
        if previous_status_type is not None:
            alert_message = None
            
            if previous_status_type == "recently" and current_status_type != "recently":
                alert_message = (
                    f"🚨 <b>{TARGET_CONTACT}</b> ОТКРЫЛ(А) СТАТУС!\n\n"
                    f"Предыдущий: Недавно\n"
                    f"Текущий: {status_text}"
                )
                print_notification(
                    f"'{TARGET_CONTACT}' ОТКРЫЛ(А) СТАТУС АКТИВНОСТИ!\n"
                    f"   Предыдущий статус: Недавно\n"
                    f"   Текущий статус: {status_text}",
                    is_alert=True
                )
                add_to_history(current_status_type, status_text, current_last_online)
                
            elif current_status_type == "online" and previous_status_type != "online":
                alert_message = f"🟢 <b>{TARGET_CONTACT}</b> СЕЙЧАС В СЕТИ!"
                print_notification(f"'{TARGET_CONTACT}' СЕЙЧАС В СЕТИ!", is_alert=True)
                add_to_history(current_status_type, status_text)
                
            elif (current_status_type == "offline" and 
                  current_last_online and 
                  current_last_online != previous_last_online):
                alert_message = (
                    f"⚪ <b>{TARGET_CONTACT}</b> ОТКРЫЛ(А) СТАТУС!\n\n"
                    f"Был(а): {current_last_online.strftime('%d.%m.%Y %H:%M:%S')}"
                )
                print_notification(
                    f"'{TARGET_CONTACT}' ОТКРЫЛ(А) СТАТУС!\n"
                    f"   Время последнего визита: {current_last_online.strftime('%d.%m.%Y %H:%M:%S')}",
                    is_alert=True
                )
                add_to_history(current_status_type, status_text, current_last_online)
            else:
                print_notification(f"Статус '{TARGET_CONTACT}': {status_text}")
            
            if alert_message:
                await send_bot_notification(alert_message)
        else:
            print_notification(f"Начальный статус '{TARGET_CONTACT}': {status_text}")
        
        previous_status_type = current_status_type
        previous_last_online = current_last_online
        return True
        
    except FloodWaitError as e:
        print_notification(f"⚠️ Flood wait: ждем {e.seconds} секунд, затем перезапуск...")
        await asyncio.sleep(e.seconds)
        return True
    except Exception as e:
        print_notification(f"❌ Ошибка при проверке статуса: {e}")
        return True


async def main():
    """Главная функция."""
    global my_chat_id
    
    print("\n" + "=" * 60)
    print("🔍 МОНИТОРИНГ СТАТУСА АКТИВНОСТИ TELEGRAM")
    print("=" * 60)
    
    if not API_ID or API_ID == 0 or not API_HASH:
        print("\n❌ ОШИБКА: Заполните API_ID и API_HASH в .env файле!")
        return
    
    if BOT_TOKEN:
        print_notification("🤖 Получаем chat_id бота...")
        print_notification("   Отправьте любое сообщение боту, затем перезапустите скрипт")
        await get_bot_chat_id()
        if my_chat_id:
            print_notification(f"✅ Chat ID получен: {my_chat_id}")
        else:
            print_notification("⚠️ Chat ID не найден. Отправьте сообщение боту и перезапустите.")
    
    client = TelegramClient("status_monitor_session", API_ID, API_HASH)
    
    await client.start()
    print_notification("✅ Авторизация успешна")
    
    print_notification(f"🔎 Поиск контакта '{TARGET_CONTACT}'...")
    contact = await find_contact_by_name(client, TARGET_CONTACT)
    
    if not contact:
        print_notification(f"❌ Контакт '{TARGET_CONTACT}' не найден в записной книге!")
        await client.disconnect()
        return
    
    print_notification(f"✅ Контакт найден: {contact.first_name} {contact.last_name or ''} (ID: {contact.id})")
    print_notification(f"⏱️ Интервал проверки: {CHECK_INTERVAL} сек")
    print("\n" + "-" * 60 + "\n")
    
    try:
        while True:
            await check_status(client, contact.id)
            await asyncio.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        print_notification("🛑 Остановлено пользователем")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
