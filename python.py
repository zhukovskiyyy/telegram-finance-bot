import asyncio
import sqlite3
from datetime import datetime
import matplotlib.pyplot as plt

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile
)
from aiogram.filters import Command

TOKEN = "8739599857:AAEmYy78XR7gt7_P987pdc2C9aJVNPylQcU"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- БАЗА ---
conn = sqlite3.connect("finance.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    category TEXT,
    date TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS shopping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    text TEXT,
    done INTEGER DEFAULT 0
)
""")

conn.commit()

# --- СТАН ---
user_state = {}

def reset(user_id):
    user_state.pop(user_id, None)

# --- КНОПКИ ---
menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💰 Дохід"), KeyboardButton(text="➖ Витрата")],
        [KeyboardButton(text="📊 Баланс"), KeyboardButton(text="📉 Історія")],
        [KeyboardButton(text="📆 За місяць"), KeyboardButton(text="📊 Графік")],
        [KeyboardButton(text="🛒 Покупки")],
        [KeyboardButton(text="🧹 Очистити мої дані")]
    ],
    resize_keyboard=True
)

cancel_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Скасувати")]],
    resize_keyboard=True
)

categories_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🍔 Їжа", callback_data="cat_food")],
    [InlineKeyboardButton(text="👕 Одяг", callback_data="cat_clothes")],
    [InlineKeyboardButton(text="📦 Інше", callback_data="cat_other")]
])

shopping_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Додати покупку")],
        [KeyboardButton(text="📋 Список")],
        [KeyboardButton(text="🗑 Очистити")],
        [KeyboardButton(text="⬅ Назад")]
    ],
    resize_keyboard=True
)

# --- СТАРТ ---
@dp.message(Command("start"))
async def start(message: types.Message):
    reset(message.from_user.id)
    await message.answer("Готовий 👇", reply_markup=menu)

# --- ОЧИСТКА ---
@dp.message(F.text == "🧹 Очистити мої дані")
async def clear_confirm(message: types.Message):
    user_state[message.from_user.id] = "confirm_clear"

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Так, видалити")],
            [KeyboardButton(text="❌ Скасувати")]
        ],
        resize_keyboard=True
    )

    await message.answer(
        "⚠️ Ти впевнений?\nЦе видалить ВСІ твої дані!",
        reply_markup=kb
    )


# --- INPUT (ГОЛОВНИЙ, БЕЗ БАГІВ) ---
@dp.message(lambda m: m.from_user.id in user_state)
async def input_handler(message: types.Message):
    user_id = message.from_user.id
    state = user_state.get(user_id)

    # --- ПІДТВЕРДЖЕННЯ ОЧИСТКИ ---
    if state == "confirm_clear":
        if message.text == "✅ Так, видалити":
            cursor.execute("DELETE FROM transactions WHERE user_id=?", (user_id,))
        cursor.execute("DELETE FROM shopping WHERE user_id=?", (user_id,))
        conn.commit()

        reset(user_id)
        await message.answer("🧹 Дані очищено", reply_markup=menu)

    else:
        reset(user_id)
        await message.answer("Скасовано", reply_markup=menu)

    return

    # --- ДОХІД ---
    if state == "income":
        if not message.text.isdigit():
            await message.answer("Введи число")
            return

        amount = int(message.text)

        cursor.execute(
            "INSERT INTO transactions (user_id, amount, category, date) VALUES (?, ?, ?, ?)",
            (user_id, amount, "Дохід", datetime.now().strftime("%Y-%m-%d"))
        )
        conn.commit()

        reset(user_id)
        await message.answer(f"➕ {amount} грн", reply_markup=menu)
        return

    # --- ВИТРАТА ---
    if state == "expense":
        if not message.text.isdigit():
            await message.answer("Введи число")
            return

        user_state[user_id] = {"amount": int(message.text)}
        await message.answer("Обери категорію:", reply_markup=categories_kb)
        return

    # --- ПОКУПКИ ---
    if state == "shopping":
        cursor.execute(
            "INSERT INTO shopping (user_id, text) VALUES (?, ?)",
            (user_id, message.text)
        )
        conn.commit()

        reset(user_id)
        await message.answer("Додано 🛒", reply_markup=shopping_menu)
        return


# --- КАТЕГОРІЯ ---
@dp.callback_query(F.data.startswith("cat_"))
async def category(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    data = user_state.get(user_id)

    if not isinstance(data, dict):
        return

    category_map = {
        "cat_food": "Їжа",
        "cat_clothes": "Одяг",
        "cat_other": "Інше"
    }

    amount = data["amount"]
    category = category_map[callback.data]

    cursor.execute(
        "INSERT INTO transactions (user_id, amount, category, date) VALUES (?, ?, ?, ?)",
        (user_id, -amount, category, datetime.now().strftime("%Y-%m-%d"))
    )
    conn.commit()

    reset(user_id)
    await callback.message.answer(f"➖ {amount} грн ({category})", reply_markup=menu)
    await callback.answer()

# --- ДОХІД / ВИТРАТА КНОПКИ ---
@dp.message(F.text == "💰 Дохід")
async def income(message: types.Message):
    user_state[message.from_user.id] = "income"
    await message.answer("Введи суму:", reply_markup=cancel_kb)

@dp.message(F.text == "➖ Витрата")
async def expense(message: types.Message):
    user_state[message.from_user.id] = "expense"
    await message.answer("Введи суму:", reply_markup=cancel_kb)

# --- БАЛАНС ---
@dp.message(F.text == "📊 Баланс")
async def balance(message: types.Message):
    reset(message.from_user.id)
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE user_id=?", (message.from_user.id,))
    total = cursor.fetchone()[0] or 0
    await message.answer(f"💰 Залишок: {total} грн")

# --- ІСТОРІЯ ---
@dp.message(F.text == "📉 Історія")
async def history(message: types.Message):
    reset(message.from_user.id)

    cursor.execute("SELECT amount, category FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 10", (message.from_user.id,))
    data = cursor.fetchall()

    if not data:
        await message.answer("Нема операцій")
        return

    text = "📉 Останні операції:\n\n"
    for amount, cat in data:
        sign = "➕" if amount > 0 else "➖"
        text += f"{sign} {abs(amount)} грн ({cat})\n"

    await message.answer(text)

# --- МІСЯЦЬ ---
@dp.message(F.text == "📆 За місяць")
async def month(message: types.Message):
    reset(message.from_user.id)

    now = datetime.now().strftime("%Y-%m")

    cursor.execute("""
        SELECT category, SUM(amount)
        FROM transactions
        WHERE user_id=? AND date LIKE ?
        GROUP BY category
    """, (message.from_user.id, f"{now}%"))

    data = cursor.fetchall()

    if not data:
        await message.answer("Нема даних")
        return

    text = "📆 За місяць:\n\n"
    for cat, amount in data:
        text += f"{cat}: {amount} грн\n"

    await message.answer(text)

# --- ГРАФІК ---
@dp.message(F.text == "📊 Графік")
async def graph(message: types.Message):
    reset(message.from_user.id)

    cursor.execute("""
        SELECT category, SUM(amount)
        FROM transactions
        WHERE user_id=? AND amount < 0
        GROUP BY category
    """, (message.from_user.id,))

    data = cursor.fetchall()

    if not data:
        await message.answer("Нема даних")
        return

    categories = [d[0] for d in data]
    values = [abs(d[1]) for d in data]

    plt.figure()
    plt.bar(categories, values)

    file = f"chart_{message.from_user.id}.png"
    plt.savefig(file)
    plt.close()

    await message.answer_photo(FSInputFile(file))

# --- ПОКУПКИ ---
@dp.message(F.text == "🛒 Покупки")
async def shop(message: types.Message):
    reset(message.from_user.id)
    await message.answer("Меню 👇", reply_markup=shopping_menu)

@dp.message(F.text == "⬅ Назад")
async def back(message: types.Message):
    reset(message.from_user.id)
    await message.answer("Назад 👇", reply_markup=menu)

@dp.message(F.text == "➕ Додати покупку")
async def add_shop(message: types.Message):
    user_state[message.from_user.id] = "shopping"
    await message.answer("Що купити?", reply_markup=cancel_kb)

@dp.message(F.text == "📋 Список")
async def show_list(message: types.Message):
    reset(message.from_user.id)

    cursor.execute("SELECT id, text, done FROM shopping WHERE user_id=?", (message.from_user.id,))
    items = cursor.fetchall()

    if not items:
        await message.answer("Пусто")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'✅' if i[2] else '⬜'} {i[1]}",
            callback_data=f"buy_{i[0]}"
        )] for i in items
    ])

    await message.answer("Список:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("buy_"))
async def toggle(callback: types.CallbackQuery):
    item_id = int(callback.data.split("_")[1])

    cursor.execute("SELECT done FROM shopping WHERE id=? AND user_id=?", (item_id, callback.from_user.id))
    row = cursor.fetchone()

    if not row:
        return

    new_status = 0 if row[0] else 1
    cursor.execute("UPDATE shopping SET done=? WHERE id=? AND user_id=?", (new_status, item_id, callback.from_user.id))
    conn.commit()

    await callback.answer("Ок")

@dp.message(F.text == "🗑 Очистити")
async def clear(message: types.Message):
    cursor.execute("DELETE FROM shopping WHERE user_id=?", (message.from_user.id,))
    conn.commit()
    await message.answer("Очищено")

# --- ЗАПУСК ---
async def main():
    await dp.start_polling(bot)

asyncio.run(main())