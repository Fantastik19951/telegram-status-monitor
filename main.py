"""
Telegram Userbot + Bot для мониторинга статуса активности контакта.
Единый запускной файл для Railway.
"""

import os
import asyncio
import json
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
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

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

from config import TARGET_USER_ID, CHECK_INTERVAL

load_dotenv()

API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")

HISTORY_FILE = Path("activity_history.json")
ITEMS_PER_PAGE = 5

previous_status_type = None
previous_last_online = None

# Статус бота для /heartbeat
bot_status = {
    "started_at": datetime.now(),
    "last_check": None,
    "total_checks": 0,
    "total_alerts": 0,
    "last_error": None,
    "last_reconnect": None,
    "flood_waits": 0,
    "reconnects": 0,
    "is_connected": False
}

bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()


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
        "contact": TARGET_USER_ID
    }
    if last_online:
        entry["last_online"] = last_online.strftime("%d.%m.%Y %H:%M:%S")
    
    history.append(entry)
    if len(history) > 500:
        history = history[-500:]
    save_history(history)


def get_today_stats():
    """Возвращает статистику за сегодня."""
    history = load_history()
    today = datetime.now().strftime("%d.%m.%Y")
    
    today_entries = [e for e in history if e["timestamp"].startswith(today)]
    
    online_count = sum(1 for e in today_entries if e["status_type"] == "online")
    offline_count = sum(1 for e in today_entries if e["status_type"] == "offline")
    total = len(today_entries)
    
    return {
        "date": today,
        "total": total,
        "online": online_count,
        "offline": offline_count,
        "entries": today_entries
    }


def get_history_page(page: int = 0):
    """Возвращает страницу истории."""
    history = load_history()
    history.reverse()
    
    total_pages = max(1, (len(history) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_items = history[start:end]
    
    return {
        "items": page_items,
        "page": page,
        "total_pages": total_pages,
        "total_items": len(history)
    }


def format_history_message(data: dict) -> str:
    """Форматирует сообщение с историей."""
    if not data["items"]:
        return "📭 История пуста"
    
    lines = [f"📋 <b>История активности</b> (стр. {data['page'] + 1}/{data['total_pages']})\n"]
    
    for entry in data["items"]:
        status_emoji = "🟢" if entry["status_type"] == "online" else "⚪"
        line = f"{status_emoji} <code>{entry['timestamp']}</code>"
        if entry.get("last_online"):
            line += f"\n   └ Был(а): {entry['last_online']}"
        lines.append(line)
    
    lines.append(f"\n📊 Всего записей: {data['total_items']}")
    return "\n".join(lines)


def format_stats_message(stats: dict) -> str:
    """Форматирует сообщение со статистикой."""
    lines = [
        f"📊 <b>Статистика за {stats['date']}</b>\n",
        f"🔢 Всего активностей: <b>{stats['total']}</b>",
        f"🟢 Онлайн: <b>{stats['online']}</b>",
        f"⚪ Офлайн (с временем): <b>{stats['offline']}</b>",
    ]
    
    if stats["entries"]:
        lines.append("\n📝 <b>Последние 5:</b>")
        for entry in stats["entries"][-5:]:
            status_emoji = "🟢" if entry["status_type"] == "online" else "⚪"
            lines.append(f"{status_emoji} {entry['timestamp']}")
    
    return "\n".join(lines)


def get_pagination_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Создает клавиатуру пагинации."""
    buttons = []
    
    if page > 0:
        buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"history_{page - 1}"))
    
    buttons.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"history_{page + 1}"))
    
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


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


def print_log(message, is_alert=False):
    """Выводит лог в консоль."""
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    if is_alert:
        print(f"\n{'='*60}\n🚨 [{timestamp}] {message}\n{'='*60}\n")
    else:
        print(f"[{timestamp}] {message}")


async def send_bot_notification(message: str, is_alert: bool = False):
    """Отправляет уведомление через Telegram бота."""
    global bot_status
    if not bot or not CHAT_ID:
        return
    
    try:
        await bot.send_message(chat_id=int(CHAT_ID), text=message, parse_mode=ParseMode.HTML)
        if is_alert:
            bot_status["total_alerts"] += 1
    except Exception as e:
        print_log(f"⚠️ Ошибка отправки в бота: {e}")


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start."""
    global CHAT_ID
    CHAT_ID = str(message.chat.id)
    
    with open(".env", "r") as f:
        env_content = f.read()
    
    if "CHAT_ID=" not in env_content:
        with open(".env", "a") as f:
            f.write(f"\nCHAT_ID={CHAT_ID}")
    
    await message.answer(
        f"👋 <b>Мониторинг активности</b>\n\n"
        f"✅ Chat ID сохранен: <code>{CHAT_ID}</code>\n\n"
        f"Команды:\n"
        f"/history — История активности\n"
        f"/stats — Статистика за сегодня\n"
        f"/heartbeat — Состояние бота\n\n"
        f"🔔 Уведомления приходят автоматически",
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    """Обработчик команды /history."""
    data = get_history_page(0)
    text = format_history_message(data)
    keyboard = get_pagination_keyboard(data["page"], data["total_pages"]) if data["total_pages"] > 1 else None
    
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """Обработчик команды /stats."""
    stats = get_today_stats()
    text = format_stats_message(stats)
    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("heartbeat"))
async def cmd_heartbeat(message: types.Message):
    """Обработчик команды /heartbeat — проверка состояния бота."""
    uptime = datetime.now() - bot_status["started_at"]
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    
    status_emoji = "🟢" if bot_status["is_connected"] else "🔴"
    
    text = (
        f"💓 <b>Heartbeat — Состояние бота</b>\n\n"
        f"{status_emoji} Статус: <b>{'Работает' if bot_status['is_connected'] else 'Отключен'}</b>\n"
        f"⏱ Аптайм: <b>{hours}ч {minutes}м {seconds}с</b>\n"
        f"📊 Проверок: <b>{bot_status['total_checks']}</b>\n"
        f"🔔 Алертов: <b>{bot_status['total_alerts']}</b>\n"
        f"⚠️ FloodWait: <b>{bot_status['flood_waits']}</b>\n"
        f"🔄 Реконнектов: <b>{bot_status['reconnects']}</b>\n"
    )
    
    if bot_status["last_check"]:
        text += f"\n🕐 Последняя проверка: <code>{bot_status['last_check'].strftime('%H:%M:%S')}</code>"
    
    if bot_status["last_error"]:
        text += f"\n\n❌ <b>Последняя ошибка:</b>\n<code>{bot_status['last_error'][:200]}</code>"
    
    if bot_status["last_reconnect"]:
        text += f"\n\n🔄 Последний реконнект: <code>{bot_status['last_reconnect'].strftime('%d.%m %H:%M:%S')}</code>"
    
    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.callback_query(lambda c: c.data.startswith("history_"))
async def callback_history_page(callback: types.CallbackQuery):
    """Обработчик пагинации истории."""
    page = int(callback.data.split("_")[1])
    data = get_history_page(page)
    text = format_history_message(data)
    keyboard = get_pagination_keyboard(data["page"], data["total_pages"])
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "noop")
async def callback_noop(callback: types.CallbackQuery):
    """Пустой обработчик для кнопки страницы."""
    await callback.answer()


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
                    f"🚨 <b>ID:{TARGET_USER_ID}</b> ОТКРЫЛ(А) СТАТУС!\n\n"
                    f"Предыдущий: Недавно\n"
                    f"Текущий: {status_text}"
                )
                print_log(f"ID:{TARGET_USER_ID} ОТКРЫЛ(А) СТАТУС! {status_text}", is_alert=True)
                add_to_history(current_status_type, status_text, current_last_online)
                
            elif current_status_type == "online" and previous_status_type != "online":
                alert_message = f"🟢 <b>ID:{TARGET_USER_ID}</b> СЕЙЧАС В СЕТИ!"
                print_log(f"ID:{TARGET_USER_ID} СЕЙЧАС В СЕТИ!", is_alert=True)
                add_to_history(current_status_type, status_text)
                
            elif (current_status_type == "offline" and 
                  current_last_online and 
                  current_last_online != previous_last_online):
                alert_message = (
                    f"⚪ <b>ID:{TARGET_USER_ID}</b> ОТКРЫЛ(А) СТАТУС!\n\n"
                    f"Был(а): {current_last_online.strftime('%d.%m.%Y %H:%M:%S')}"
                )
                print_log(f"ID:{TARGET_USER_ID} ОТКРЫЛ(А) СТАТУС! Был(а): {current_last_online}", is_alert=True)
                add_to_history(current_status_type, status_text, current_last_online)
            else:
                print_log(f"Статус ID:{TARGET_USER_ID}: {status_text}")
            
            if alert_message:
                await send_bot_notification(alert_message, is_alert=True)
        else:
            print_log(f"Начальный статус ID:{TARGET_USER_ID}: {status_text}")
        
        previous_status_type = current_status_type
        previous_last_online = current_last_online
        
    except FloodWaitError:
        raise  # передаем в monitoring_loop для обработки
    except (ConnectionError, OSError):
        raise  # передаем в monitoring_loop для реконнекта
    except Exception as e:
        if "disconnected" in str(e).lower() or "connection" in str(e).lower():
            raise  # передаем в monitoring_loop
        print_log(f"❌ Ошибка при проверке статуса: {e}")


async def monitoring_loop(client, contact_id: int):
    """Цикл мониторинга статуса с автопереподключением (24/7)."""
    global bot_status
    reconnect_delay = 5
    max_reconnect_delay = 300  # макс 5 минут между попытками
    
    while True:
        try:
            if not client.is_connected():
                bot_status["is_connected"] = False
                print_log("🔄 Переподключение к Telegram...")
                await client.connect()
                if not await client.is_user_authorized():
                    error_msg = "Сессия недействительна"
                    print_log(f"❌ {error_msg}. Ожидание 60 сек и повтор...")
                    bot_status["last_error"] = error_msg
                    await send_bot_notification(f"❌ <b>Ошибка:</b> {error_msg}. Повтор через 60 сек...")
                    await asyncio.sleep(60)
                    continue
                print_log("✅ Переподключение успешно!")
                bot_status["is_connected"] = True
                bot_status["reconnects"] += 1
                bot_status["last_reconnect"] = datetime.now()
                await send_bot_notification("✅ <b>Переподключение успешно!</b> Мониторинг продолжается.")
                reconnect_delay = 5
            
            bot_status["is_connected"] = True
            await check_status(client, contact_id)
            bot_status["total_checks"] += 1
            bot_status["last_check"] = datetime.now()
            reconnect_delay = 5
            
        except FloodWaitError as e:
            bot_status["flood_waits"] += 1
            print_log(f"⚠️ Flood wait: ждем {e.seconds} секунд...")
            await send_bot_notification(f"⚠️ <b>FloodWait:</b> ждем {e.seconds} секунд...")
            await asyncio.sleep(e.seconds)
            continue
            
        except (ConnectionError, OSError) as e:
            bot_status["is_connected"] = False
            bot_status["last_error"] = str(e)
            print_log(f"⚠️ Потеря соединения: {e}. Повтор через {reconnect_delay} сек...")
            await send_bot_notification(f"⚠️ <b>Потеря соединения.</b> Повтор через {reconnect_delay} сек...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
            continue
            
        except Exception as e:
            error_msg = str(e)
            if "disconnected" in error_msg.lower() or "connection" in error_msg.lower():
                bot_status["is_connected"] = False
                bot_status["last_error"] = error_msg
                print_log(f"⚠️ Отключение: {e}. Повтор через {reconnect_delay} сек...")
                await send_bot_notification(f"⚠️ <b>Отключение.</b> Повтор через {reconnect_delay} сек...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
                continue
            else:
                bot_status["last_error"] = error_msg
                print_log(f"❌ Неожиданная ошибка: {e}. Продолжаем...")
        
        await asyncio.sleep(CHECK_INTERVAL)


async def main():
    """Главная функция."""
    global CHAT_ID
    
    print("\n" + "=" * 60)
    print("🔍 МОНИТОРИНГ СТАТУСА АКТИВНОСТИ TELEGRAM")
    print("=" * 60)
    
    if not API_ID or API_ID == 0 or not API_HASH:
        print("\n❌ ОШИБКА: Заполните API_ID и API_HASH в .env файле!")
        return
    
    if not BOT_TOKEN:
        print("\n❌ ОШИБКА: Заполните BOT_TOKEN в .env файле!")
        return
    
    if SESSION_STRING:
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    else:
        client = TelegramClient("status_monitor_session", API_ID, API_HASH)
    await client.start()
    print_log("✅ Userbot авторизован")
    
    print_log(f"🎯 Целевой пользователь ID: {TARGET_USER_ID}")
    
    try:
        user = await client.get_entity(TARGET_USER_ID)
        print_log(f"✅ Пользователь найден: {user.first_name} {user.last_name or ''} (ID: {user.id})")
    except Exception as e:
        print_log(f"❌ Пользователь с ID {TARGET_USER_ID} не найден: {e}")
        await client.disconnect()
        return
    
    print_log(f"⏱️ Интервал проверки: {CHECK_INTERVAL} сек")
    
    if CHAT_ID:
        print_log(f"🤖 Chat ID: {CHAT_ID}")
    else:
        print_log("⚠️ CHAT_ID не найден. Отправьте /start боту для сохранения.")
    
    print("\n" + "-" * 60 + "\n")
    
    monitoring_task = asyncio.create_task(monitoring_loop(client, TARGET_USER_ID))
    
    print_log("🤖 Запуск бота...")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print_log(f"❌ Ошибка бота: {e}")
    finally:
        monitoring_task.cancel()
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
