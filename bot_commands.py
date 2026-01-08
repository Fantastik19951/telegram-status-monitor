"""
Telegram бот для просмотра истории активности.
Команды: /start, /history, /stats
"""

import os
import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
HISTORY_FILE = Path("activity_history.json")
ITEMS_PER_PAGE = 5


def load_history():
    """Загружает историю активности из файла."""
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


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


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start."""
    await message.answer(
        "👋 <b>Мониторинг активности</b>\n\n"
        "Команды:\n"
        "/history — История активности\n"
        "/stats — Статистика за сегодня\n\n"
        "🔔 Уведомления приходят автоматически",
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


async def main():
    """Запуск бота."""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не найден в .env!")
        return
    
    print("🤖 Бот запущен. Команды: /start, /history, /stats")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
