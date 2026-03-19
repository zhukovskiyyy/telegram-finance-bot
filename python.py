import asyncio
import logging
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

import os
TOKEN = os.getenv("8739599857:AAEmYy78XR7gt7_P987pdc2C9aJVNPylQcU")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp  = Dispatcher(storage=MemoryStorage())


# =======================
# DATABASE
# =======================

DB_PATH = "finance.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id  INTEGER NOT NULL,
            type     TEXT NOT NULL,
            amount   REAL NOT NULL,
            category TEXT NOT NULL,
            date     TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS shopping (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            text    TEXT NOT NULL,
            done    INTEGER NOT NULL DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS recurring (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            name       TEXT NOT NULL,
            amount     REAL NOT NULL,
            category   TEXT NOT NULL,
            day        INTEGER NOT NULL,
            active     INTEGER NOT NULL DEFAULT 1,
            last_fired TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS goals (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            name       TEXT NOT NULL,
            target     REAL NOT NULL,
            saved      REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


init_db()


# =======================
# STATES
# =======================

class IncomeState(StatesGroup):
    amount = State()

class ExpenseState(StatesGroup):
    amount   = State()
    category = State()

class ShoppingState(StatesGroup):
    item = State()

class RecurringState(StatesGroup):
    name     = State()
    amount   = State()
    category = State()
    day      = State()

class GoalState(StatesGroup):
    name   = State()
    target = State()

class GoalAddState(StatesGroup):
    amount = State()


# =======================
# KEYBOARDS
# =======================

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💰 Дохід"),      KeyboardButton(text="➖ Витрата")],
        [KeyboardButton(text="📊 Баланс"),     KeyboardButton(text="📜 Історія")],
        [KeyboardButton(text="📈 Статистика"), KeyboardButton(text="🔁 Регулярні")],
        [KeyboardButton(text="🎯 Цілі"),       KeyboardButton(text="🛒 Покупки")],
        [KeyboardButton(text="⚙️ Налаштування")],
    ],
    resize_keyboard=True
)

shopping_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Додати"),            KeyboardButton(text="📋 Список")],
        [KeyboardButton(text="🗑 Видалити виконані"),  KeyboardButton(text="🧹 Очистити список")],
        [KeyboardButton(text="⬅️ Назад")],
    ],
    resize_keyboard=True
)

settings_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🧹 Очистити список покупок")],
        [KeyboardButton(text="💣 Очистити всі дані")],
        [KeyboardButton(text="⬅️ Назад")],
    ],
    resize_keyboard=True
)

recurring_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Новий платіж"),    KeyboardButton(text="📋 Мої платежі")],
        [KeyboardButton(text="▶️ Застосувати зараз")],
        [KeyboardButton(text="⬅️ Назад")],
    ],
    resize_keyboard=True
)

goals_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Нова ціль"), KeyboardButton(text="📋 Мої цілі")],
        [KeyboardButton(text="⬅️ Назад")],
    ],
    resize_keyboard=True
)

CATEGORIES = [
    "🍔 Їжа", "🚗 Транспорт", "🏠 Житло",
    "🎮 Розваги", "💊 Здоров'я", "👕 Одяг", "📦 Інше"
]

STATS_KB = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="📅 Місяць",   callback_data="stats_month"),
    InlineKeyboardButton(text="📆 Рік",      callback_data="stats_year"),
    InlineKeyboardButton(text="🗓 Весь час", callback_data="stats_all"),
]])


def category_kb(prefix: str = "cat") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=cat, callback_data=f"{prefix}_{cat}")]
            for cat in CATEGORIES
        ]
    )


def confirm_kb(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Так",       callback_data=f"confirm_{action}"),
        InlineKeyboardButton(text="❌ Скасувати", callback_data="confirm_cancel"),
    ]])


def shopping_list_kb(items) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=("✅ " if item["done"] else "⬜ ") + item["text"],
                callback_data=f"buy_{item['id']}"
            )]
            for item in items
        ]
    )


def goals_list_kb(goals) -> InlineKeyboardMarkup:
    rows = []
    for g in goals:
        rows.append([InlineKeyboardButton(
            text=f"💰 Поповнити «{g['name'][:22]}»",
            callback_data=f"goal_add_{g['id']}"
        )])
        rows.append([InlineKeyboardButton(
            text=f"🗑 Видалити «{g['name'][:22]}»",
            callback_data=f"goal_del_{g['id']}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def recurring_list_kb(items) -> InlineKeyboardMarkup:
    rows = []
    for r in items:
        status = "✅" if r["active"] else "⏸"
        rows.append([
            InlineKeyboardButton(
                text=f"{status} {r['name']} — {fmt_amount(r['amount'])} ({r['day']}-го)",
                callback_data=f"rec_toggle_{r['id']}"
            ),
            InlineKeyboardButton(text="🗑", callback_data=f"rec_del_{r['id']}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# =======================
# HELPERS
# =======================

def fmt_amount(amount: float) -> str:
    return f"{amount:,.2f}".replace(",", " ")


def progress_bar(current: float, target: float, length: int = 12) -> str:
    pct    = min(current / target, 1.0) if target > 0 else 0
    filled = round(pct * length)
    bar    = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {pct * 100:.1f}%"


def build_stats(user_id: int, period: str) -> str:
    conn = get_conn()
    try:
        now = datetime.now()

        if period == "month":
            date_filter = f"{now.year}-{now.month:02d}-%"
            label       = now.strftime("%B %Y")
        elif period == "year":
            date_filter = f"{now.year}-%"
            label       = str(now.year)
        else:
            date_filter = "%"
            label       = "весь час"

        total_income = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions "
            "WHERE user_id=? AND type='income' AND date LIKE ?",
            (user_id, date_filter)
        ).fetchone()[0]

        total_expense = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions "
            "WHERE user_id=? AND type='expense' AND date LIKE ?",
            (user_id, date_filter)
        ).fetchone()[0]

        cat_rows = conn.execute(
            "SELECT category, SUM(amount) as total "
            "FROM transactions "
            "WHERE user_id=? AND type='expense' AND date LIKE ? "
            "GROUP BY category ORDER BY total DESC",
            (user_id, date_filter)
        ).fetchall()
    finally:
        conn.close()

    if total_income == 0 and total_expense == 0:
        return f"📭 Немає даних за {label}."

    net  = total_income - total_expense
    sign = "+" if net >= 0 else ""

    lines = [
        f"📈 <b>Статистика — {label}</b>\n",
        f"💚 Доходи:  <b>+{fmt_amount(total_income)} грн</b>",
        f"🔴 Витрати: <b>-{fmt_amount(total_expense)} грн</b>",
        f"💳 Баланс:  <b>{sign}{fmt_amount(net)} грн</b>",
    ]

    if cat_rows:
        lines.append("\n🗂 <b>Витрати по категоріях:</b>")
        for r in cat_rows:
            pct     = (r["total"] / total_expense * 100) if total_expense > 0 else 0
            bar_len = round(pct / 10)
            bar     = "▓" * bar_len + "░" * (10 - bar_len)
            lines.append(f"{r['category']}\n  [{bar}] {pct:.1f}%  —  {fmt_amount(r['total'])} грн")

    return "\n".join(lines)


# =======================
# /start
# =======================

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Привіт! Я твій фінансовий бот.\nОбери дію в меню нижче.",
        reply_markup=main_kb
    )


# =======================
# ДОХІД
# =======================

@dp.message(F.text == "💰 Дохід")
async def income_start(message: Message, state: FSMContext):
    await state.set_state(IncomeState.amount)
    await message.answer("Введи суму доходу:")


@dp.message(IncomeState.amount)
async def income_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректне додатнє число. Наприклад: 1500 або 250.50")
        return

    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO transactions (user_id, type, amount, category, date) VALUES (?, ?, ?, ?, ?)",
            (message.from_user.id, "income", amount, "Дохід", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
        last_id = cur.lastrowid
    finally:
        conn.close()

    undo_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ Скасувати", callback_data=f"undo_tx_{last_id}")
    ]])
    await message.answer(
        f"✅ Дохід додано: <b>+{fmt_amount(amount)} грн</b>",
        reply_markup=undo_kb, parse_mode="HTML"
    )
    await message.answer("Головне меню:", reply_markup=main_kb)
    await state.clear()


# =======================
# ВИТРАТА
# =======================

@dp.message(F.text == "➖ Витрата")
async def expense_start(message: Message, state: FSMContext):
    await state.set_state(ExpenseState.amount)
    await message.answer("Введи суму витрати:")


@dp.message(ExpenseState.amount)
async def expense_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректне додатнє число. Наприклад: 200 або 49.99")
        return

    await state.update_data(amount=amount)
    await state.set_state(ExpenseState.category)
    await message.answer("Вибери категорію:", reply_markup=category_kb("cat"))


@dp.callback_query(ExpenseState.category, F.data.startswith("cat_"))
async def expense_category(callback: CallbackQuery, state: FSMContext):
    data   = await state.get_data()
    amount = data.get("amount")

    if amount is None:
        await callback.answer("Щось пішло не так. Почни знову.", show_alert=True)
        await state.clear()
        return

    category = callback.data[4:]

    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO transactions (user_id, type, amount, category, date) VALUES (?, ?, ?, ?, ?)",
            (callback.from_user.id, "expense", amount, category, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
        last_id = cur.lastrowid
    finally:
        conn.close()

    undo_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ Скасувати", callback_data=f"undo_tx_{last_id}")
    ]])

    await callback.message.edit_text(
        f"✅ Витрата: <b>-{fmt_amount(amount)} грн</b>  ({category})",
        parse_mode="HTML"
    )
    await callback.message.answer("Скасувати?", reply_markup=undo_kb)
    await callback.message.answer("Головне меню:", reply_markup=main_kb)
    await state.clear()
    await callback.answer()


# =======================
# UNDO
# =======================

@dp.callback_query(F.data.startswith("undo_tx_"))
async def undo_transaction(callback: CallbackQuery):
    tx_id = int(callback.data.split("_")[2])
    uid   = callback.from_user.id

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM transactions WHERE id=? AND user_id=?", (tx_id, uid)
        ).fetchone()

        if not row:
            await callback.answer("❌ Транзакцію вже видалено.", show_alert=True)
            return

        conn.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
        conn.commit()
    finally:
        conn.close()

    sign = "+" if row["type"] == "income" else "-"
    await callback.message.edit_text(
        f"↩️ Скасовано: {sign}{fmt_amount(row['amount'])} грн  ({row['category']})"
    )
    await callback.answer("Транзакцію видалено ✅")


# =======================
# БАЛАНС
# =======================

@dp.message(F.text == "📊 Баланс")
async def balance(message: Message):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT type, SUM(amount) FROM transactions WHERE user_id=? GROUP BY type",
            (message.from_user.id,)
        ).fetchall()
    finally:
        conn.close()

    income  = next((r[1] for r in rows if r[0] == "income"),  0.0)
    expense = next((r[1] for r in rows if r[0] == "expense"), 0.0)
    net     = income - expense
    sign    = "+" if net >= 0 else ""

    await message.answer(
        f"📊 <b>Баланс</b>\n\n"
        f"💚 Доходи:  <b>+{fmt_amount(income)} грн</b>\n"
        f"🔴 Витрати: <b>-{fmt_amount(expense)} грн</b>\n"
        f"──────────────\n"
        f"💳 Разом:   <b>{sign}{fmt_amount(net)} грн</b>",
        parse_mode="HTML"
    )


# =======================
# ІСТОРІЯ
# =======================

@dp.message(F.text == "📜 Історія")
async def history(message: Message):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT type, amount, category, date FROM transactions "
            "WHERE user_id=? ORDER BY id DESC LIMIT 15",
            (message.from_user.id,)
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        await message.answer("📭 Немає жодних записів.")
        return

    lines = []
    for r in rows:
        icon = "💚" if r["type"] == "income" else "🔴"
        sign = "+" if r["type"] == "income" else "-"
        d    = r["date"][:10]
        lines.append(f"{icon} {sign}{fmt_amount(r['amount'])} грн  |  {r['category']}  |  {d}")

    await message.answer(
        "📜 <b>Остання історія (до 15 записів)</b>\n\n" + "\n".join(lines),
        parse_mode="HTML"
    )


# =======================
# СТАТИСТИКА
# =======================

@dp.message(F.text == "📈 Статистика")
async def stats_menu(message: Message):
    await message.answer("Обери період:", reply_markup=STATS_KB)


@dp.callback_query(F.data.startswith("stats_"))
async def stats_period(callback: CallbackQuery):
    period = callback.data.split("_")[1]
    text   = build_stats(callback.from_user.id, period)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=STATS_KB)
    await callback.answer()


# =======================
# РЕГУЛЯРНІ ПЛАТЕЖІ
# =======================

@dp.message(F.text == "🔁 Регулярні")
async def recurring_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🔁 Регулярні платежі", reply_markup=recurring_kb)


@dp.message(F.text == "➕ Новий платіж")
async def recurring_new(message: Message, state: FSMContext):
    await state.set_state(RecurringState.name)
    await message.answer("Введи назву (наприклад: Netflix, Оренда):")


@dp.message(RecurringState.name)
async def recurring_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(RecurringState.amount)
    await message.answer("Введи суму:")


@dp.message(RecurringState.amount)
async def recurring_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректне число.")
        return

    await state.update_data(amount=amount)
    await state.set_state(RecurringState.category)
    await message.answer("Вибери категорію:", reply_markup=category_kb("rcat"))


@dp.callback_query(RecurringState.category, F.data.startswith("rcat_"))
async def recurring_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data[5:]
    await state.update_data(category=category)
    await state.set_state(RecurringState.day)
    await callback.message.edit_text(f"Категорія: {category}\n\nВведи день місяця (1–28):")
    await callback.answer()


@dp.message(RecurringState.day)
async def recurring_day(message: Message, state: FSMContext):
    try:
        day = int(message.text.strip())
        if not (1 <= day <= 28):
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число від 1 до 28.")
        return

    data = await state.get_data()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO recurring (user_id, name, amount, category, day) VALUES (?, ?, ?, ?, ?)",
            (message.from_user.id, data["name"], data["amount"], data["category"], day)
        )
        conn.commit()
    finally:
        conn.close()

    await message.answer(
        f"✅ Регулярний платіж додано!\n"
        f"<b>{data['name']}</b> — {fmt_amount(data['amount'])} грн\n"
        f"Категорія: {data['category']}\n"
        f"Щомісяця {day}-го числа",
        parse_mode="HTML",
        reply_markup=recurring_kb
    )
    await state.clear()


@dp.message(F.text == "📋 Мої платежі")
async def recurring_list(message: Message):
    conn = get_conn()
    try:
        items = conn.execute(
            "SELECT * FROM recurring WHERE user_id=? ORDER BY day",
            (message.from_user.id,)
        ).fetchall()
    finally:
        conn.close()

    if not items:
        await message.answer("📭 Немає регулярних платежів.")
        return

    await message.answer(
        "🔁 <b>Регулярні платежі</b>\n"
        "Натисни рядок — увімк/вимк, 🗑 — видалити:",
        reply_markup=recurring_list_kb(items),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("rec_toggle_"))
async def recurring_toggle(callback: CallbackQuery):
    rec_id = int(callback.data.split("_")[2])
    conn   = get_conn()
    try:
        conn.execute(
            "UPDATE recurring SET active = NOT active WHERE id=? AND user_id=?",
            (rec_id, callback.from_user.id)
        )
        conn.commit()
        items = conn.execute(
            "SELECT * FROM recurring WHERE user_id=? ORDER BY day",
            (callback.from_user.id,)
        ).fetchall()
    finally:
        conn.close()

    await callback.message.edit_reply_markup(reply_markup=recurring_list_kb(items))
    await callback.answer("Оновлено ✅")


@dp.callback_query(F.data.startswith("rec_del_"))
async def recurring_delete(callback: CallbackQuery):
    rec_id = int(callback.data.split("_")[2])
    conn   = get_conn()
    try:
        conn.execute(
            "DELETE FROM recurring WHERE id=? AND user_id=?",
            (rec_id, callback.from_user.id)
        )
        conn.commit()
        items = conn.execute(
            "SELECT * FROM recurring WHERE user_id=? ORDER BY day",
            (callback.from_user.id,)
        ).fetchall()
    finally:
        conn.close()

    if items:
        await callback.message.edit_reply_markup(reply_markup=recurring_list_kb(items))
    else:
        await callback.message.edit_text("📭 Немає регулярних платежів.")

    await callback.answer("Видалено 🗑")


@dp.message(F.text == "▶️ Застосувати зараз")
async def recurring_apply_now(message: Message):
    uid     = message.from_user.id
    now     = datetime.now()
    yearmon = now.strftime("%Y-%m")

    conn = get_conn()
    try:
        items = conn.execute(
            "SELECT * FROM recurring WHERE user_id=? AND active=1",
            (uid,)
        ).fetchall()

        applied = []
        for r in items:
            if r["last_fired"] == yearmon:
                continue
            conn.execute(
                "INSERT INTO transactions (user_id, type, amount, category, date) VALUES (?, ?, ?, ?, ?)",
                (uid, "expense", r["amount"], r["category"], now.strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.execute(
                "UPDATE recurring SET last_fired=? WHERE id=?", (yearmon, r["id"])
            )
            applied.append(r)

        conn.commit()
    finally:
        conn.close()

    if not applied:
        await message.answer("ℹ️ Всі активні платежі вже застосовано цього місяця.")
        return

    lines = "\n".join(
        f"  • {r['name']} — -{fmt_amount(r['amount'])} грн ({r['category']})"
        for r in applied
    )
    await message.answer(f"✅ Застосовано {len(applied)} платежів:\n{lines}")


# =======================
# ЦІЛІ НАКОПИЧЕНЬ
# =======================

@dp.message(F.text == "🎯 Цілі")
async def goals_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🎯 Цілі накопичень", reply_markup=goals_kb)


@dp.message(F.text == "➕ Нова ціль")
async def goal_new(message: Message, state: FSMContext):
    await state.set_state(GoalState.name)
    await message.answer("Введи назву цілі (наприклад: Відпустка, Ноутбук, Машина):")


@dp.message(GoalState.name)
async def goal_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(GoalState.target)
    await message.answer("Введи цільову суму (грн):")


@dp.message(GoalState.target)
async def goal_target(message: Message, state: FSMContext):
    try:
        target = float(message.text.replace(",", "."))
        if target <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректне число.")
        return

    data = await state.get_data()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO goals (user_id, name, target, saved, created_at) VALUES (?, ?, ?, 0, ?)",
            (message.from_user.id, data["name"], target, datetime.now().strftime("%Y-%m-%d"))
        )
        conn.commit()
    finally:
        conn.close()

    await message.answer(
        f"🎯 Ціль створено!\n\n"
        f"<b>{data['name']}</b>\n"
        f"  {progress_bar(0, target)}\n"
        f"  0 / {fmt_amount(target)} грн",
        parse_mode="HTML",
        reply_markup=goals_kb
    )
    await state.clear()


@dp.message(F.text == "📋 Мої цілі")
async def goals_list(message: Message):
    conn = get_conn()
    try:
        goals = conn.execute(
            "SELECT * FROM goals WHERE user_id=? ORDER BY id",
            (message.from_user.id,)
        ).fetchall()
    finally:
        conn.close()

    if not goals:
        await message.answer("📭 Немає жодної цілі. Натисни «➕ Нова ціль»!")
        return

    lines = []
    for g in goals:
        bar  = progress_bar(g["saved"], g["target"])
        left = max(g["target"] - g["saved"], 0)
        if g["saved"] >= g["target"]:
            status = "  🎉 <b>Виконано!</b>"
        else:
            status = f"  ще {fmt_amount(left)} грн"

        lines.append(
            f"🎯 <b>{g['name']}</b>\n"
            f"  {bar}\n"
            f"  {fmt_amount(g['saved'])} / {fmt_amount(g['target'])} грн\n"
            f"{status}"
        )

    await message.answer(
        "🎯 <b>Мої цілі</b>\n\n" + "\n\n".join(lines),
        reply_markup=goals_list_kb(goals),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("goal_add_"))
async def goal_add_start(callback: CallbackQuery, state: FSMContext):
    goal_id = int(callback.data.split("_")[2])
    await state.set_state(GoalAddState.amount)
    await state.update_data(goal_id=goal_id)
    await callback.message.answer("Введи суму поповнення:")
    await callback.answer()


@dp.message(GoalAddState.amount)
async def goal_add_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректне число.")
        return

    data    = await state.get_data()
    goal_id = data["goal_id"]
    uid     = message.from_user.id

    conn = get_conn()
    try:
        goal = conn.execute(
            "SELECT * FROM goals WHERE id=? AND user_id=?", (goal_id, uid)
        ).fetchone()

        if not goal:
            await message.answer("❌ Ціль не знайдена.")
            await state.clear()
            return

        new_saved = goal["saved"] + amount
        conn.execute("UPDATE goals SET saved=? WHERE id=?", (new_saved, goal_id))
        conn.commit()
    finally:
        conn.close()

    bar  = progress_bar(new_saved, goal["target"])
    left = max(goal["target"] - new_saved, 0)

    if new_saved >= goal["target"]:
        extra = "\n\n🎉 <b>Ціль досягнута! Вітаю!</b>"
    else:
        extra = f"\n  ще {fmt_amount(left)} грн до цілі"

    await message.answer(
        f"✅ Поповнення: <b>+{fmt_amount(amount)} грн</b>\n\n"
        f"🎯 <b>{goal['name']}</b>\n"
        f"  {bar}\n"
        f"  {fmt_amount(new_saved)} / {fmt_amount(goal['target'])} грн{extra}",
        parse_mode="HTML",
        reply_markup=goals_kb
    )
    await state.clear()


@dp.callback_query(F.data.startswith("goal_del_"))
async def goal_delete(callback: CallbackQuery):
    goal_id = int(callback.data.split("_")[2])
    uid     = callback.from_user.id

    conn = get_conn()
    try:
        conn.execute("DELETE FROM goals WHERE id=? AND user_id=?", (goal_id, uid))
        conn.commit()
        goals = conn.execute(
            "SELECT * FROM goals WHERE user_id=? ORDER BY id", (uid,)
        ).fetchall()
    finally:
        conn.close()

    if goals:
        await callback.message.edit_reply_markup(reply_markup=goals_list_kb(goals))
    else:
        await callback.message.edit_text("📭 Немає жодної цілі. Натисни «➕ Нова ціль»!")

    await callback.answer("Ціль видалено 🗑")


# =======================
# ПОКУПКИ
# =======================

@dp.message(F.text == "🛒 Покупки")
async def shopping_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🛒 Меню покупок", reply_markup=shopping_kb)


@dp.message(F.text == "➕ Додати")
async def add_item_start(message: Message, state: FSMContext):
    await state.set_state(ShoppingState.item)
    await message.answer("Введіть назву товару:")


@dp.message(ShoppingState.item)
async def save_item(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer("❌ Назва не може бути порожньою.")
        return

    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO shopping (user_id, text) VALUES (?, ?)",
            (message.from_user.id, text)
        )
        conn.commit()
    finally:
        conn.close()

    await message.answer(f"✅ «{text}» додано до списку.", reply_markup=shopping_kb)
    await state.clear()


@dp.message(F.text == "📋 Список")
async def show_list(message: Message):
    conn = get_conn()
    try:
        items = conn.execute(
            "SELECT id, text, done FROM shopping WHERE user_id=? ORDER BY id",
            (message.from_user.id,)
        ).fetchall()
    finally:
        conn.close()

    if not items:
        await message.answer("🛒 Список покупок пустий.")
        return

    await message.answer(
        "🛒 <b>Список покупок</b>\nНатисни на товар, щоб позначити виконання:",
        reply_markup=shopping_list_kb(items),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("buy_"))
async def toggle_item(callback: CallbackQuery):
    item_id = int(callback.data.split("_")[1])
    conn    = get_conn()
    try:
        conn.execute("UPDATE shopping SET done = NOT done WHERE id=?", (item_id,))
        conn.commit()
        items = conn.execute(
            "SELECT id, text, done FROM shopping WHERE user_id=? ORDER BY id",
            (callback.from_user.id,)
        ).fetchall()
    finally:
        conn.close()

    await callback.message.edit_reply_markup(reply_markup=shopping_list_kb(items))
    await callback.answer("Оновлено ✅")


@dp.message(F.text == "🗑 Видалити виконані")
async def delete_done_items(message: Message):
    conn = get_conn()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM shopping WHERE user_id=? AND done=1",
            (message.from_user.id,)
        ).fetchone()[0]

        if count == 0:
            await message.answer("ℹ️ Немає виконаних товарів.")
            return

        conn.execute("DELETE FROM shopping WHERE user_id=? AND done=1", (message.from_user.id,))
        conn.commit()
    finally:
        conn.close()

    await message.answer(f"🗑 Видалено {count} виконаних товарів.")


# =======================
# НАЛАШТУВАННЯ
# =======================

@dp.message(F.text == "⚙️ Налаштування")
async def settings_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("⚙️ Налаштування", reply_markup=settings_kb)


@dp.message(F.text.in_({"🧹 Очистити список покупок", "🧹 Очистити список"}))
async def clear_shopping_confirm(message: Message):
    await message.answer(
        "⚠️ Видалити весь список покупок?",
        reply_markup=confirm_kb("shopping")
    )


@dp.message(F.text == "💣 Очистити всі дані")
async def clear_all_confirm(message: Message):
    await message.answer(
        "⚠️ <b>УВАГА!</b> Видалити <b>ВСІ дані</b>?\n"
        "(транзакції, покупки, цілі, регулярні платежі)",
        reply_markup=confirm_kb("all"),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("confirm_"))
async def handle_confirm(callback: CallbackQuery):
    action = callback.data[8:]
    uid    = callback.from_user.id

    if action == "cancel":
        await callback.message.edit_text("❌ Дію скасовано.")
        await callback.answer()
        return

    conn = get_conn()
    try:
        if action == "shopping":
            conn.execute("DELETE FROM shopping WHERE user_id=?", (uid,))
            conn.commit()
            await callback.message.edit_text("🧹 Список покупок очищено.")
        elif action == "all":
            for table in ("transactions", "shopping", "recurring", "goals"):
                conn.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
            conn.commit()
            await callback.message.edit_text("💣 Всі дані видалено.")
    finally:
        conn.close()

    await callback.answer()


# =======================
# НАЗАД
# =======================

@dp.message(F.text == "⬅️ Назад")
async def go_back(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Головне меню", reply_markup=main_kb)


# =======================
# FALLBACK
# =======================

@dp.message()
async def fallback(message: Message, state: FSMContext):
    if await state.get_state() is None:
        await message.answer(
            "❓ Не розумію цю команду. Скористайся меню нижче.",
            reply_markup=main_kb
        )


# =======================
# RECURRING SCHEDULER
# =======================

async def recurring_scheduler():
    """Перевіряє регулярні платежі кожні 6 годин."""
    while True:
        await asyncio.sleep(6 * 3600)
        now     = datetime.now()
        today   = now.day
        yearmon = now.strftime("%Y-%m")

        conn = get_conn()
        try:
            items = conn.execute(
                "SELECT * FROM recurring WHERE active=1 "
                "AND (last_fired IS NULL OR last_fired != ?)",
                (yearmon,)
            ).fetchall()

            for r in items:
                if r["day"] != today:
                    continue

                conn.execute(
                    "INSERT INTO transactions (user_id, type, amount, category, date) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (r["user_id"], "expense", r["amount"], r["category"],
                     now.strftime("%Y-%m-%d %H:%M:%S"))
                )
                conn.execute(
                    "UPDATE recurring SET last_fired=? WHERE id=?", (yearmon, r["id"])
                )

                try:
                    await bot.send_message(
                        r["user_id"],
                        f"🔁 Регулярний платіж: <b>{r['name']}</b>\n"
                        f"-{fmt_amount(r['amount'])} грн ({r['category']})",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

            conn.commit()
        finally:
            conn.close()


# =======================
# RUN
# =======================

async def main():
    asyncio.create_task(recurring_scheduler())
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
