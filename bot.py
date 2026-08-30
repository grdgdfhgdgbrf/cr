# bot.py
import asyncio
import random
import sqlite3
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Токен бота из .env
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in .env file")

# Конфигурация
COMMISSION = 0.02  # 2%
UPDATE_INTERVAL = 180  # 3 минуты
MAX_LEVERAGE = 3
STAKE_PERCENT = 5
STAKE_HOURS = 24
MIN_STAKE = 100
REFERRAL_BONUS = 200
DAILY_BONUSES = [100, 150, 200, 300, 400, 600, 1000]

# Активы
ASSETS = {
    'PEPE': {'name': 'PEPE', 'emoji': '🐸', 'initial_price': 1.00, 'crash_risk': 10, 'volatility': 0.15},
    'DOGE': {'name': 'DOGE', 'emoji': '🐕', 'initial_price': 0.50, 'crash_risk': 20, 'volatility': 0.20},
    'SHIB': {'name': 'SHIB', 'emoji': '🔥', 'initial_price': 0.001, 'crash_risk': 35, 'volatility': 0.25}
}

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==================== FSM СОСТОЯНИЯ ====================
class BuyState(StatesGroup):
    waiting_for_asset = State()
    waiting_for_amount = State()
    confirm = State()

class SellState(StatesGroup):
    waiting_for_asset = State()
    waiting_for_amount = State()
    confirm = State()

class StakeState(StatesGroup):
    waiting_for_amount = State()

class LeverageState(StatesGroup):
    waiting_for_lever = State()
    confirm = State()

# ==================== БАЗА ДАННЫХ ====================
class Database:
    def __init__(self, db_name='crypto_bot.db'):
        self.db_name = db_name
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_name)

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 1000.0,
                referral_count INTEGER DEFAULT 0,
                last_daily TEXT,
                daily_streak INTEGER DEFAULT 0,
                total_earned REAL DEFAULT 0.0,
                stake_amount REAL DEFAULT 0.0,
                stake_time INTEGER DEFAULT 0,
                leverage_level INTEGER DEFAULT 1,
                last_activity INTEGER
            )
        ''')

        # Таблица портфеля
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                asset TEXT,
                amount REAL,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(user_id, asset)
            )
        ''')

        # Таблица истории цен
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT,
                price REAL,
                timestamp INTEGER
            )
        ''')

        # Таблица транзакций
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                asset TEXT,
                amount REAL,
                price REAL,
                timestamp INTEGER
            )
        ''')

        # Таблица рефералов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                new_user_id INTEGER,
                timestamp INTEGER
            )
        ''')

        # Таблица достижений
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                achievement_id INTEGER,
                timestamp INTEGER,
                UNIQUE(user_id, achievement_id)
            )
        ''')

        # Таблица текущих цен (последние значения)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS current_prices (
                asset TEXT PRIMARY KEY,
                price REAL,
                timestamp INTEGER
            )
        ''')

        # Таблица краш-ставок
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS crash_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                asset TEXT,
                bet_type TEXT,
                amount REAL,
                coefficient REAL,
                status TEXT,
                result REAL,
                timestamp INTEGER
            )
        ''')

        # Инициализация цен для активов
        for asset, data in ASSETS.items():
            cursor.execute('''
                INSERT OR IGNORE INTO current_prices (asset, price, timestamp)
                VALUES (?, ?, ?)
            ''', (asset, data['initial_price'], int(datetime.now().timestamp())))

        conn.commit()
        conn.close()
        logger.info("Database initialized")

    def get_price(self, asset: str) -> float:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT price FROM current_prices WHERE asset = ?', (asset,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else ASSETS[asset]['initial_price']

    def update_price(self, asset: str, price: float):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE current_prices SET price = ?, timestamp = ? WHERE asset = ?
        ''', (price, int(datetime.now().timestamp()), asset))
        cursor.execute('''
            INSERT INTO price_history (asset, price, timestamp) VALUES (?, ?, ?)
        ''', (asset, price, int(datetime.now().timestamp())))
        conn.commit()
        conn.close()

    def get_price_history(self, asset: str, limit: int = 10) -> List[Tuple[float, int]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT price, timestamp FROM price_history 
            WHERE asset = ? 
            ORDER BY timestamp DESC LIMIT ?
        ''', (asset, limit))
        result = cursor.fetchall()
        conn.close()
        return result[::-1]  # Возвращаем в хронологическом порядке

    def get_user(self, user_id: int) -> Dict:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            columns = ['user_id', 'username', 'balance', 'referral_count', 'last_daily', 
                      'daily_streak', 'total_earned', 'stake_amount', 'stake_time', 
                      'leverage_level', 'last_activity']
            return dict(zip(columns, result))
        return None

    def create_user(self, user_id: int, username: str = None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (user_id, username, last_activity)
            VALUES (?, ?, ?)
        ''', (user_id, username, int(datetime.now().timestamp())))
        # Создаём пустой портфель для пользователя
        for asset in ASSETS:
            cursor.execute('''
                INSERT INTO portfolio (user_id, asset, amount)
                VALUES (?, ?, 0.0)
            ''', (user_id, asset))
        conn.commit()
        conn.close()

    def update_balance(self, user_id: int, amount: float):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users SET balance = balance + ? WHERE user_id = ?
        ''', (amount, user_id))
        conn.commit()
        conn.close()

    def set_balance(self, user_id: int, amount: float):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users SET balance = ? WHERE user_id = ?
        ''', (amount, user_id))
        conn.commit()
        conn.close()

    def get_portfolio(self, user_id: int) -> Dict[str, float]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT asset, amount FROM portfolio WHERE user_id = ?', (user_id,))
        result = cursor.fetchall()
        conn.close()
        return {row[0]: row[1] for row in result}

    def update_portfolio(self, user_id: int, asset: str, amount: float):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE portfolio SET amount = amount + ? 
            WHERE user_id = ? AND asset = ?
        ''', (amount, user_id, asset))
        conn.commit()
        conn.close()

    def set_portfolio(self, user_id: int, asset: str, amount: float):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE portfolio SET amount = ? 
            WHERE user_id = ? AND asset = ?
        ''', (amount, user_id, asset))
        conn.commit()
        conn.close()

    def add_transaction(self, user_id: int, trans_type: str, asset: str, amount: float, price: float):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO transactions (user_id, type, asset, amount, price, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, trans_type, asset, amount, price, int(datetime.now().timestamp())))
        conn.commit()
        conn.close()

    def add_referral(self, referrer_id: int, new_user_id: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO referrals (referrer_id, new_user_id, timestamp)
            VALUES (?, ?, ?)
        ''', (referrer_id, new_user_id, int(datetime.now().timestamp())))
        cursor.execute('''
            UPDATE users SET referral_count = referral_count + 1 
            WHERE user_id = ?
        ''', (referrer_id,))
        conn.commit()
        conn.close()

    def get_referral_count(self, user_id: int) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT referral_count FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0

    def get_stake(self, user_id: int) -> Tuple[float, int]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT stake_amount, stake_time FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return result[0], result[1]
        return 0.0, 0

    def update_stake(self, user_id: int, amount: float, stake_time: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users SET stake_amount = ?, stake_time = ? WHERE user_id = ?
        ''', (amount, stake_time, user_id))
        conn.commit()
        conn.close()

    def get_daily_info(self, user_id: int) -> Tuple[str, int]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT last_daily, daily_streak FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return result[0], result[1]
        return None, 0

    def update_daily(self, user_id: int, streak: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute('''
            UPDATE users SET last_daily = ?, daily_streak = ? WHERE user_id = ?
        ''', (today, streak, user_id))
        conn.commit()
        conn.close()

    def get_total_capital(self, user_id: int) -> float:
        balance = self.get_user(user_id)['balance']
        portfolio = self.get_portfolio(user_id)
        total = balance
        for asset, amount in portfolio.items():
            price = self.get_price(asset)
            total += amount * price
        return total

    def get_weekly_growth(self, user_id: int) -> float:
        # Расчёт прироста за неделю (упрощённо)
        # Здесь можно хранить историю капитала, но для простоты используем общий заработок
        user = self.get_user(user_id)
        if user:
            total_earned = user['total_earned']
            balance = user['balance']
            portfolio = self.get_portfolio(user_id)
            portfolio_value = sum(amount * self.get_price(asset) for asset, amount in portfolio.items())
            current_capital = balance + portfolio_value
            if current_capital > 0 and total_earned > 0:
                return ((current_capital - (current_capital - total_earned)) / (current_capital - total_earned)) * 100
        return 0.0

    def get_top_users(self, limit: int = 10) -> List[Tuple[int, str, float]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT ?
        ''', (limit,))
        result = cursor.fetchall()
        conn.close()
        return result

    def get_crash_bets(self, user_id: int, limit: int = 10) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM crash_bets WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?
        ''', (user_id, limit))
        result = cursor.fetchall()
        conn.close()
        if result:
            columns = ['id', 'user_id', 'asset', 'bet_type', 'amount', 'coefficient', 'status', 'result', 'timestamp']
            return [dict(zip(columns, row)) for row in result]
        return []

    def add_crash_bet(self, user_id: int, asset: str, bet_type: str, amount: float, coefficient: float):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO crash_bets (user_id, asset, bet_type, amount, coefficient, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, asset, bet_type, amount, coefficient, 'pending', int(datetime.now().timestamp())))
        bet_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return bet_id

    def update_crash_bet(self, bet_id: int, status: str, result: float):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE crash_bets SET status = ?, result = ? WHERE id = ?
        ''', (status, result, bet_id))
        conn.commit()
        conn.close()

    def get_achievements(self, user_id: int) -> List[int]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT achievement_id FROM achievements WHERE user_id = ?', (user_id,))
        result = cursor.fetchall()
        conn.close()
        return [row[0] for row in result]

    def add_achievement(self, user_id: int, achievement_id: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO achievements (user_id, achievement_id, timestamp)
            VALUES (?, ?, ?)
        ''', (user_id, achievement_id, int(datetime.now().timestamp())))
        conn.commit()
        conn.close()

    def get_all_users(self) -> List[int]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users')
        result = cursor.fetchall()
        conn.close()
        return [row[0] for row in result]

db = Database()

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📈 Торговать", callback_data="trade"),
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile")
    )
    builder.row(
        InlineKeyboardButton(text="🔒 Стейкинг", callback_data="stake"),
        InlineKeyboardButton(text="🏆 Топ", callback_data="top")
    )
    builder.row(
        InlineKeyboardButton(text="📰 Новости", callback_data="news"),
        InlineKeyboardButton(text="👥 Рефералы", callback_data="referral")
    )
    builder.row(
        InlineKeyboardButton(text="🎁 Дейли", callback_data="daily"),
        InlineKeyboardButton(text="💀 Краш-арена", callback_data="crash_arena")
    )
    builder.row(
        InlineKeyboardButton(text="❓ Помощь", callback_data="help")
    )
    return builder.as_markup()

def get_assets_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for asset, data in ASSETS.items():
        price = db.get_price(asset)
        builder.row(
            InlineKeyboardButton(
                text=f"{data['emoji']} {asset} — {price:.4f}",
                callback_data=f"asset_{asset}"
            )
        )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")
    )
    return builder.as_markup()

def get_asset_trade_keyboard(asset: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    price = db.get_price(asset)
    risk = get_crash_risk(asset)
    builder.row(
        InlineKeyboardButton(
            text=f"📊 Текущий курс: {price:.4f}",
            callback_data="refresh_price"
        )
    )
    builder.row(
        InlineKeyboardButton(text="💰 Купить", callback_data=f"buy_{asset}"),
        InlineKeyboardButton(text="💸 Продать", callback_data=f"sell_{asset}")
    )
    builder.row(
        InlineKeyboardButton(text="⚡ Плечо x2", callback_data=f"leverage_{asset}_2"),
        InlineKeyboardButton(text="🔥 Плечо x3", callback_data=f"leverage_{asset}_3")
    )
    builder.row(
        InlineKeyboardButton(
            text=f"📉 Риск краша: {risk}%",
            callback_data="show_risk"
        )
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh_{asset}"),
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_assets")
    )
    return builder.as_markup()

def get_stake_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔒 Застейкать", callback_data="stake_action"),
        InlineKeyboardButton(text="🔓 Забрать стейк", callback_data="unstake_action")
    )
    builder.row(
        InlineKeyboardButton(text="📊 Мой стейк", callback_data="my_stake")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")
    )
    return builder.as_markup()

def get_profile_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Баланс", callback_data="show_balance"),
        InlineKeyboardButton(text="📦 Портфель", callback_data="show_portfolio")
    )
    builder.row(
        InlineKeyboardButton(text="🏅 Достижения", callback_data="show_achievements"),
        InlineKeyboardButton(text="📈 Статистика", callback_data="show_stats")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")
    )
    return builder.as_markup()

def get_top_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🏆 По капиталу", callback_data="top_capital"),
        InlineKeyboardButton(text="📈 По приросту", callback_data="top_growth")
    )
    builder.row(
        InlineKeyboardButton(text="🎯 По сделкам", callback_data="top_trades"),
        InlineKeyboardButton(text="💀 По крашам", callback_data="top_crashes")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")
    )
    return builder.as_markup()

def get_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_yes"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="confirm_no")
    )
    return builder.as_markup()

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")
    )
    return builder.as_markup()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def get_crash_risk(asset: str) -> int:
    """Возвращает текущий риск краша для актива (может меняться динамически)"""
    base_risk = ASSETS[asset]['crash_risk']
    # Добавляем случайную вариацию ±5%
    variation = random.randint(-5, 5)
    risk = max(1, min(80, base_risk + variation))
    return risk

def check_crash(asset: str) -> Tuple[bool, float]:
    """Проверяет, произошёл ли краш, и возвращает результат"""
    risk = get_crash_risk(asset) / 100
    if random.random() < risk:
        # Краш: падение на 50-80%
        crash_percent = random.uniform(0.5, 0.8)
        return True, crash_percent
    return False, 0.0

def calculate_leverage(amount: float, leverage: int, price: float) -> float:
    """Рассчитывает сумму с учётом плеча"""
    return amount * price / leverage

def format_number(num: float) -> str:
    """Форматирует число с разделителями"""
    if num >= 1000:
        return f"{num:,.2f}"
    return f"{num:.4f}"

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Проверяем, существует ли пользователь
    user = db.get_user(user_id)
    if not user:
        db.create_user(user_id, username)
        logger.info(f"New user registered: {user_id}")
        
        # Проверка на реферала
        args = message.text.split()
        if len(args) > 1 and args[1].startswith('ref_'):
            try:
                referrer_id = int(args[1].replace('ref_', ''))
                if referrer_id != user_id:
                    db.add_referral(referrer_id, user_id)
                    db.update_balance(referrer_id, REFERRAL_BONUS)
                    await bot.send_message(
                        referrer_id,
                        f"🎉 Новый игрок по твоей ссылке! Ты получил {REFERRAL_BONUS} JET"
                    )
            except ValueError:
                pass
    
    await message.answer(
        f"🐸 Добро пожаловать в КриптоКаток, {username}!\n\n"
        f"Твой стартовый баланс: 1000 JET\n"
        f"Здесь ты торгуешь мем-токенами, зарабатываешь очки и становишься легендой!\n\n"
        f"Используй кнопки ниже, чтобы начать:",
        reply_markup=get_main_keyboard()
    )
    await state.clear()

@dp.message(Command("menu"))
async def cmd_menu(message: types.Message, state: FSMContext):
    await message.answer(
        "📋 Главное меню:",
        reply_markup=get_main_keyboard()
    )
    await state.clear()

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    await show_profile(message.from_user.id, message)

@dp.message(Command("trade"))
async def cmd_trade(message: types.Message):
    await show_trade_menu(message)

@dp.message(Command("stake"))
async def cmd_stake(message: types.Message):
    await show_stake_menu(message)

@dp.message(Command("top"))
async def cmd_top(message: types.Message):
    await show_top(message)

@dp.message(Command("daily"))
async def cmd_daily(message: types.Message):
    await claim_daily(message.from_user.id, message)

@dp.message(Command("referral"))
async def cmd_referral(message: types.Message):
    await show_referral(message.from_user.id, message)

@dp.message(Command("news"))
async def cmd_news(message: types.Message):
    await show_news(message)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await show_help(message)

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Действие отменено.",
        reply_markup=get_main_keyboard()
    )

# ==================== ОБРАБОТЧИКИ CALLBACK ====================

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "📋 Главное меню:",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_assets")
async def back_to_assets(callback: CallbackQuery):
    await callback.message.edit_text(
        "📈 Выбери актив для торговли:",
        reply_markup=get_assets_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "trade")
async def trade_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "📈 Выбери актив для торговли:",
        reply_markup=get_assets_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("asset_"))
async def asset_trade(callback: CallbackQuery, state: FSMContext):
    asset = callback.data.replace("asset_", "")
    await state.update_data(asset=asset)
    await callback.message.edit_text(
        get_asset_trade_text(asset),
        reply_markup=get_asset_trade_keyboard(asset)
    )
    await callback.answer()

def get_asset_trade_text(asset: str) -> str:
    price = db.get_price(asset)
    history = db.get_price_history(asset, 10)
    risk = get_crash_risk(asset)
    
    # Генерируем график
    graph = ""
    if history:
        values = [h[0] for h in history]
        min_val = min(values)
        max_val = max(values)
        range_val = max_val - min_val if max_val > min_val else 0.001
        
        for val in values[-6:]:  # Показываем последние 6 значений
            if range_val > 0:
                height = int((val - min_val) / range_val * 5) + 1
                bar = "█" * height
                graph += f"{bar} {val:.4f}\n"
    
    return (
        f"{ASSETS[asset]['emoji']} *{asset}*\n\n"
        f"💰 Текущая цена: *{price:.4f}* JET\n"
        f"📊 Риск краша: *{risk}%*\n"
        f"📈 Волатильность: *{ASSETS[asset]['volatility']*100:.0f}%*\n\n"
        f"*График (последние 6 тиков):*\n"
        f"{graph}\n"
        f"Используй кнопки ниже для торговли:"
    )

@dp.callback_query(F.data.startswith("buy_"))
async def buy_callback(callback: CallbackQuery, state: FSMContext):
    asset = callback.data.replace("buy_", "")
    await state.update_data(action="buy", asset=asset)
    await callback.message.edit_text(
        f"💰 Введи количество *{asset}*, которое хочешь купить:\n"
        f"Текущая цена: {db.get_price(asset):.4f} JET\n\n"
        f"*(Отправь число в следующем сообщении или нажми Отмена)*",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(BuyState.waiting_for_amount)
    await callback.answer()

@dp.callback_query(F.data.startswith("sell_"))
async def sell_callback(callback: CallbackQuery, state: FSMContext):
    asset = callback.data.replace("sell_", "")
    portfolio = db.get_portfolio(callback.from_user.id)
    if portfolio.get(asset, 0) <= 0:
        await callback.answer("❌ У тебя нет этого актива!", show_alert=True)
        return
    await state.update_data(action="sell", asset=asset)
    await callback.message.edit_text(
        f"💸 Введи количество *{asset}*, которое хочешь продать:\n"
        f"У тебя есть: {portfolio.get(asset, 0):.4f} {asset}\n"
        f"Текущая цена: {db.get_price(asset):.4f} JET\n\n"
        f"*(Отправь число в следующем сообщении или нажми Отмена)*",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(SellState.waiting_for_amount)
    await callback.answer()

@dp.callback_query(F.data.startswith("leverage_"))
async def leverage_callback(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    asset = parts[1]
    level = int(parts[2])
    
    user = db.get_user(callback.from_user.id)
    db.set_balance(callback.from_user.id, user['balance'])
    # Обновляем уровень плеча
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET leverage_level = ? WHERE user_id = ?', (level, callback.from_user.id))
    conn.commit()
    conn.close()
    
    await callback.answer(f"✅ Плечо x{level} установлено!")
    await callback.message.edit_text(
        get_asset_trade_text(asset),
        reply_markup=get_asset_trade_keyboard(asset)
    )

@dp.callback_query(F.data == "refresh_price")
async def refresh_price(callback: CallbackQuery):
    await callback.answer("🔄 Обновление...")
    # Просто обновляем текст без изменения данных
    await callback.message.edit_text(
        callback.message.text,
        reply_markup=get_asset_trade_keyboard(callback.message.text.split()[1])  # Не идеально, но работает
    )

@dp.callback_query(F.data.startswith("refresh_"))
async def refresh_asset(callback: CallbackQuery):
    asset = callback.data.replace("refresh_", "")
    await callback.message.edit_text(
        get_asset_trade_text(asset),
        reply_markup=get_asset_trade_keyboard(asset)
    )
    await callback.answer("🔄 Обновлено!")

@dp.callback_query(F.data == "show_risk")
async def show_risk(callback: CallbackQuery):
    # Находим актив из текста сообщения
    # Простой способ: парсим текст, но лучше хранить в state
    await callback.answer("📊 Риск обновляется каждые 10 минут", show_alert=True)

@dp.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery):
    await show_profile(callback.from_user.id, callback.message)
    await callback.answer()

@dp.callback_query(F.data == "show_balance")
async def show_balance(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    await callback.message.edit_text(
        f"💰 *Твой баланс:* {format_number(user['balance'])} JET",
        reply_markup=get_profile_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "show_portfolio")
async def show_portfolio(callback: CallbackQuery):
    user_id = callback.from_user.id
    portfolio = db.get_portfolio(user_id)
    text = "📦 *Твой портфель:*\n\n"
    total_value = 0
    
    for asset, amount in portfolio.items():
        if amount > 0:
            price = db.get_price(asset)
            value = amount * price
            total_value += value
            text += f"{ASSETS[asset]['emoji']} *{asset}:* {amount:.4f} (≈ {value:.2f} JET)\n"
    
    text += f"\n💰 *Общая стоимость портфеля:* {total_value:.2f} JET"
    
    if total_value == 0:
        text = "📦 *Твой портфель пуст*\nКупи активы, чтобы начать торговлю!"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_profile_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "show_achievements")
async def show_achievements(callback: CallbackQuery):
    user_id = callback.from_user.id
    achievements = db.get_achievements(user_id)
    
    achievements_list = {
        1: "🏅 *Первая сделка* — Соверши свою первую покупку",
        2: "💀 *Хомяк* — Проиграй 10 сделок подряд",
        3: "🐋 *Кит* — Иметь портфель > 1000 любого актива",
        4: "👑 *Миллионер* — Капитал > 1 000 000 JET",
        5: "📊 *Инвестор* — Иметь все 3 актива одновременно",
        6: "🔒 *Стейкер* — Застейкать 1000+ JET",
        7: "🏆 *Лидер* — Попасть в топ-3 недели"
    }
    
    text = "🏅 *Твои достижения:*\n\n"
    if achievements:
        for ach_id in achievements:
            if ach_id in achievements_list:
                text += f"✅ {achievements_list[ach_id]}\n"
    else:
        text += "❌ Пока нет достижений.\n"
    
    text += "\n*Доступные достижения:*\n"
    for ach_id, ach_text in achievements_list.items():
        if ach_id not in achievements:
            text += f"⬜ {ach_text}\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_profile_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "show_stats")
async def show_stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = db.get_user(user_id)
    capital = db.get_total_capital(user_id)
    growth = db.get_weekly_growth(user_id)
    
    # Считаем количество транзакций
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM transactions WHERE user_id = ?', (user_id,))
    transactions_count = cursor.fetchone()[0]
    conn.close()
    
    text = (
        f"📈 *Твоя статистика:*\n\n"
        f"💰 Баланс: {format_number(user['balance'])} JET\n"
        f"💎 Капитал: {format_number(capital)} JET\n"
        f"📈 Прирост за неделю: {growth:.1f}%\n"
        f"📊 Всего сделок: {transactions_count}\n"
        f"👥 Рефералов: {user['referral_count']}\n"
        f"🏆 Всего заработано: {format_number(user['total_earned'])} JET"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_profile_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "stake")
async def stake_callback(callback: CallbackQuery):
    await show_stake_menu(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "stake_action")
async def stake_action(callback: CallbackQuery, state: FSMContext):
    user = db.get_user(callback.from_user.id)
    if user['stake_amount'] > 0:
        await callback.answer("⚠️ У тебя уже есть активный стейк!", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"🔒 Введи сумму для стейкинга:\n"
        f"Минимальная сумма: {MIN_STAKE} JET\n"
        f"Доходность: {STAKE_PERCENT}% за {STAKE_HOURS} часов\n\n"
        f"*(Отправь число в следующем сообщении или нажми Отмена)*",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(StakeState.waiting_for_amount)
    await callback.answer()

@dp.callback_query(F.data == "unstake_action")
async def unstake_action(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = db.get_user(user_id)
    
    if user['stake_amount'] <= 0:
        await callback.answer("❌ У тебя нет активного стейка!", show_alert=True)
        return
    
    stake_time = user['stake_time']
    current_time = int(datetime.now().timestamp())
    
    if current_time - stake_time < STAKE_HOURS * 3600:
        remaining = STAKE_HOURS * 3600 - (current_time - stake_time)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        await callback.answer(
            f"⏳ Осталось {hours}ч {minutes}мин до разблокировки!",
            show_alert=True
        )
        return
    
    # Разблокировка стейка
    bonus = user['stake_amount'] * (STAKE_PERCENT / 100)
    total = user['stake_amount'] + bonus
    
    db.update_balance(user_id, total)
    db.update_stake(user_id, 0, 0)
    
    await callback.message.edit_text(
        f"🔓 *Стейк разблокирован!*\n\n"
        f"💰 Сумма стейка: {user['stake_amount']:.2f} JET\n"
        f"🎁 Бонус: {bonus:.2f} JET ({STAKE_PERCENT}%)\n"
        f"✅ Итого получено: {total:.2f} JET",
        reply_markup=get_stake_keyboard()
    )
    await callback.answer("✅ Стейк забран!")

@dp.callback_query(F.data == "my_stake")
async def my_stake(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = db.get_user(user_id)
    
    if user['stake_amount'] <= 0:
        text = "🔒 *У тебя нет активного стейка*"
    else:
        stake_time = user['stake_time']
        current_time = int(datetime.now().timestamp())
        elapsed = current_time - stake_time
        total_time = STAKE_HOURS * 3600
        progress = min(100, int(elapsed / total_time * 100))
        
        if elapsed >= total_time:
            status = "✅ *Готов к разблокировке!*"
        else:
            remaining = total_time - elapsed
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            status = f"⏳ Осталось: {hours}ч {minutes}мин"
        
        text = (
            f"🔒 *Твой стейк:*\n\n"
            f"💰 Сумма: {user['stake_amount']:.2f} JET\n"
            f"📊 Прогресс: {progress}%\n"
            f"🔄 Статус: {status}\n"
            f"🎁 Бонус при разблокировке: {user['stake_amount'] * (STAKE_PERCENT / 100):.2f} JET"
        )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_stake_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "top")
async def top_callback(callback: CallbackQuery):
    await show_top(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "top_capital")
async def top_capital(callback: CallbackQuery):
    await show_top_by_capital(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "top_growth")
async def top_growth(callback: CallbackQuery):
    await show_top_by_growth(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "top_trades")
async def top_trades(callback: CallbackQuery):
    await show_top_by_trades(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "top_crashes")
async def top_crashes(callback: CallbackQuery):
    await show_top_by_crashes(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "news")
async def news_callback(callback: CallbackQuery):
    await show_news(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "referral")
async def referral_callback(callback: CallbackQuery):
    await show_referral(callback.from_user.id, callback.message)
    await callback.answer()

@dp.callback_query(F.data == "daily")
async def daily_callback(callback: CallbackQuery):
    await claim_daily(callback.from_user.id, callback.message)
    await callback.answer()

@dp.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery):
    await show_help(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "cancel_action")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Действие отменено.",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

# ==================== ОБРАБОТЧИКИ FSM ====================

@dp.message(BuyState.waiting_for_amount)
async def process_buy_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0!", reply_markup=get_cancel_keyboard())
            return
        
        data = await state.get_data()
        asset = data.get('asset')
        user_id = message.from_user.id
        user = db.get_user(user_id)
        price = db.get_price(asset)
        leverage = user.get('leverage_level', 1)
        
        # Расчёт с учётом плеча
        total_cost = amount * price * (1 + COMMISSION) / leverage
        
        if total_cost > user['balance']:
            await message.answer(
                f"❌ Недостаточно средств!\n"
                f"Нужно: {total_cost:.2f} JET\n"
                f"Баланс: {user['balance']:.2f} JET\n\n"
                f"Попробуй уменьшить количество.",
                reply_markup=get_cancel_keyboard()
            )
            return
        
        # Подтверждение
        await state.update_data(amount=amount, total_cost=total_cost)
        await message.answer(
            f"📊 *Подтверждение покупки:*\n\n"
            f"🪙 Актив: {asset}\n"
            f"📦 Количество: {amount:.4f}\n"
            f"💰 Цена: {price:.4f} JET\n"
            f"⚡ Плечо: x{leverage}\n"
            f"💸 Итого к списанию: {total_cost:.2f} JET\n\n"
            f"Подтверждаешь сделку?",
            reply_markup=get_confirm_keyboard()
        )
        await state.set_state(BuyState.confirm)
        
    except ValueError:
        await message.answer("❌ Введи корректное число!", reply_markup=get_cancel_keyboard())

@dp.message(SellState.waiting_for_amount)
async def process_sell_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0!", reply_markup=get_cancel_keyboard())
            return
        
        data = await state.get_data()
        asset = data.get('asset')
        user_id = message.from_user.id
        portfolio = db.get_portfolio(user_id)
        
        if amount > portfolio.get(asset, 0):
            await message.answer(
                f"❌ У тебя только {portfolio.get(asset, 0):.4f} {asset}!\n"
                f"Попробуй уменьшить количество.",
                reply_markup=get_cancel_keyboard()
            )
            return
        
        price = db.get_price(asset)
        total_revenue = amount * price * (1 - COMMISSION)
        
        # Подтверждение
        await state.update_data(amount=amount, total_revenue=total_revenue)
        await message.answer(
            f"📊 *Подтверждение продажи:*\n\n"
            f"🪙 Актив: {asset}\n"
            f"📦 Количество: {amount:.4f}\n"
            f"💰 Цена: {price:.4f} JET\n"
            f"💸 Итого к получению: {total_revenue:.2f} JET\n\n"
            f"Подтверждаешь сделку?",
            reply_markup=get_confirm_keyboard()
        )
        await state.set_state(SellState.confirm)
        
    except ValueError:
        await message.answer("❌ Введи корректное число!", reply_markup=get_cancel_keyboard())

@dp.message(StakeState.waiting_for_amount)
async def process_stake_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount < MIN_STAKE:
            await message.answer(
                f"❌ Минимальная сумма стейка: {MIN_STAKE} JET!",
                reply_markup=get_cancel_keyboard()
            )
            return
        
        user_id = message.from_user.id
        user = db.get_user(user_id)
        
        if amount > user['balance']:
            await message.answer(
                f"❌ Недостаточно средств!\n"
                f"Нужно: {amount:.2f} JET\n"
                f"Баланс: {user['balance']:.2f} JET",
                reply_markup=get_cancel_keyboard()
            )
            return
        
        # Создаём стейк
        db.update_balance(user_id, -amount)
        db.update_stake(user_id, amount, int(datetime.now().timestamp()))
        
        await state.clear()
        await message.answer(
            f"🔒 *Стейк создан!*\n\n"
            f"💰 Заблокировано: {amount:.2f} JET\n"
            f"⏳ Время: {STAKE_HOURS} часов\n"
            f"🎁 Бонус: {STAKE_PERCENT}% ({amount * STAKE_PERCENT / 100:.2f} JET)\n\n"
            f"Используй /unstake, чтобы забрать после разблокировки.",
            reply_markup=get_stake_keyboard()
        )
        
    except ValueError:
        await message.answer("❌ Введи корректное число!", reply_markup=get_cancel_keyboard())

@dp.callback_query(F.data == "confirm_yes")
async def confirm_yes(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    action = data.get('action')
    asset = data.get('asset')
    amount = data.get('amount')
    
    if action == "buy":
        total_cost = data.get('total_cost')
        price = db.get_price(asset)
        
        # Выполняем покупку
        db.update_balance(user_id, -total_cost)
        db.update_portfolio(user_id, asset, amount)
        db.add_transaction(user_id, 'buy', asset, amount, price)
        
        # Обновляем общий заработок
        user = db.get_user(user_id)
        db.set_balance(user_id, user['balance'])
        
        await callback.message.edit_text(
            f"✅ *Покупка выполнена!*\n\n"
            f"🪙 {asset}: +{amount:.4f}\n"
            f"💰 Цена: {price:.4f} JET\n"
            f"💸 Списано: {total_cost:.2f} JET\n"
            f"📊 Баланс: {db.get_user(user_id)['balance']:.2f} JET",
            reply_markup=get_asset_trade_keyboard(asset)
        )
        
        # Проверка достижений
        await check_achievements(user_id, callback.message)
        
    elif action == "sell":
        total_revenue = data.get('total_revenue')
        price = db.get_price(asset)
        
        # Выполняем продажу
        db.update_balance(user_id, total_revenue)
        db.update_portfolio(user_id, asset, -amount)
        db.add_transaction(user_id, 'sell', asset, amount, price)
        
        await callback.message.edit_text(
            f"✅ *Продажа выполнена!*\n\n"
            f"🪙 {asset}: -{amount:.4f}\n"
            f"💰 Цена: {price:.4f} JET\n"
            f"💸 Получено: {total_revenue:.2f} JET\n"
            f"📊 Баланс: {db.get_user(user_id)['balance']:.2f} JET",
            reply_markup=get_asset_trade_keyboard(asset)
        )
    
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "confirm_no")
async def confirm_no(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Сделка отменена.",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

# ==================== КРАШ-АРЕНА ====================

@dp.callback_query(F.data == "crash_arena")
async def crash_arena(callback: CallbackQuery):
    await callback.message.edit_text(
        "💀 *Краш-арена*\n\n"
        "Ставь на то, упадёт или вырастет цена!\n\n"
        "📈 *Ставка на рост* — коэффициент x1.5\n"
        "📉 *Ставка на падение* — коэффициент x2.5\n"
        "🎰 *Краш-лотерея* — x3 (авто-выбор)\n\n"
        "Выбери актив для ставки:",
        reply_markup=get_assets_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("asset_"))
async def crash_asset_select(callback: CallbackQuery, state: FSMContext):
    asset = callback.data.replace("asset_", "")
    await state.update_data(crash_asset=asset)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📈 Ставка на рост (x1.5)", callback_data=f"crash_bet_{asset}_up"),
        InlineKeyboardButton(text="📉 Ставка на падение (x2.5)", callback_data=f"crash_bet_{asset}_down")
    )
    builder.row(
        InlineKeyboardButton(text="🎰 Краш-лотерея (x3)", callback_data=f"crash_bet_{asset}_auto")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_assets")
    )
    
    await callback.message.edit_text(
        f"💀 *{ASSETS[asset]['emoji']} {asset}*\n\n"
        f"Текущая цена: {db.get_price(asset):.4f} JET\n"
        f"Риск краша: {get_crash_risk(asset)}%\n\n"
        f"Выбери тип ставки:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("crash_bet_"))
async def crash_bet(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    asset = parts[2]
    bet_type = parts[3]
    
    user_id = callback.from_user.id
    user = db.get_user(user_id)
    
    # Запрашиваем сумму ставки
    await state.update_data(crash_asset=asset, crash_bet_type=bet_type)
    await callback.message.edit_text(
        f"💰 Введи сумму ставки для {asset}:\n"
        f"Баланс: {user['balance']:.2f} JET\n"
        f"Тип ставки: {bet_type}\n\n"
        f"*(Отправь число в следующем сообщении или нажми Отмена)*",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state("waiting_crash_bet")
    await callback.answer()

@dp.message(StateFilter("waiting_crash_bet"))
async def process_crash_bet(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0!", reply_markup=get_cancel_keyboard())
            return
        
        user_id = message.from_user.id
        user = db.get_user(user_id)
        
        if amount > user['balance']:
            await message.answer(
                f"❌ Недостаточно средств!\n"
                f"Баланс: {user['balance']:.2f} JET",
                reply_markup=get_cancel_keyboard()
            )
            return
        
        data = await state.get_data()
        asset = data.get('crash_asset')
        bet_type = data.get('crash_bet_type')
        
        # Определяем коэффициенты
        coefficients = {
            'up': 1.5,
            'down': 2.5,
            'auto': 3.0
        }
        coefficient = coefficients.get(bet_type, 1.5)
        
        # Проверяем краш
        is_crash, crash_percent = check_crash(asset)
        
        # Определяем результат
        if bet_type == 'auto':
            # Авто-выбор: случайно победа или поражение
            win = random.random() < 0.5
        elif bet_type == 'up':
            win = not is_crash  # Если нет краша, цена растёт
        else:  # down
            win = is_crash  # Если краш, цена падает
        
        # Расчёт результата
        if win:
            win_amount = amount * coefficient
            db.update_balance(user_id, win_amount - amount)  # Добавляем только прибыль
            result_text = f"✅ *Победа!* +{win_amount:.2f} JET (x{coefficient})"
        else:
            db.update_balance(user_id, -amount)
            result_text = f"❌ *Поражение!* -{amount:.2f} JET"
        
        # Сохраняем ставку
        db.add_crash_bet(user_id, asset, bet_type, amount, coefficient)
        
        # Сообщение о результате
        crash_text = f"💥 Краш: {crash_percent*100:.1f}%" if is_crash else "✅ Без краша"
        
        await state.clear()
        await message.answer(
            f"💀 *Результат ставки*\n\n"
            f"🪙 Актив: {asset}\n"
            f"📊 Тип: {bet_type.upper()}\n"
            f"💰 Сумма: {amount:.2f} JET\n"
            f"📈 Коэффициент: x{coefficient}\n"
            f"{crash_text}\n\n"
            f"{result_text}\n\n"
            f"Новый баланс: {db.get_user(user_id)['balance']:.2f} JET",
            reply_markup=get_main_keyboard()
        )
        
    except ValueError:
        await message.answer("❌ Введи корректное число!", reply_markup=get_cancel_keyboard())

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ПОКАЗА ====================

async def show_profile(user_id: int, message_or_callback):
    user = db.get_user(user_id)
    capital = db.get_total_capital(user_id)
    
    text = (
        f"👤 *Профиль: @{user['username']}*\n\n"
        f"💰 Баланс: {format_number(user['balance'])} JET\n"
        f"💎 Капитал: {format_number(capital)} JET\n"
        f"👥 Рефералов: {user['referral_count']}\n"
        f"🏆 Всего заработано: {format_number(user['total_earned'])} JET\n"
        f"🔒 Стейк: {user['stake_amount']:.2f} JET"
    )
    
    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(text, reply_markup=get_profile_keyboard())
    else:
        await message_or_callback.edit_text(text, reply_markup=get_profile_keyboard())

async def show_trade_menu(message: types.Message):
    await message.answer(
        "📈 Выбери актив для торговли:",
        reply_markup=get_assets_keyboard()
    )

async def show_stake_menu(message: types.Message):
    user = db.get_user(message.from_user.id)
    text = (
        "🔒 *Стейкинг*\n\n"
        f"💰 Баланс: {user['balance']:.2f} JET\n"
        f"🔒 Застейкано: {user['stake_amount']:.2f} JET\n"
        f"📊 Доходность: {STAKE_PERCENT}% за {STAKE_HOURS}ч\n"
        f"📉 Минимальная сумма: {MIN_STAKE} JET\n\n"
        "Заблокируй монеты и получай пассивный доход!"
    )
    await message.answer(text, reply_markup=get_stake_keyboard())

async def show_top(message: types.Message):
    await message.answer(
        "🏆 *Топ игроков*\n\n"
        "Выбери категорию:",
        reply_markup=get_top_keyboard()
    )

async def show_top_by_capital(message: types.Message):
    top = db.get_top_users(10)
    text = "🏆 *Топ по капиталу:*\n\n"
    for i, (user_id, username, balance) in enumerate(top, 1):
        medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
        text += f"{medal} @{username or 'anon'} — {balance:.2f} JET\n"
    
    await message.edit_text(text, reply_markup=get_top_keyboard())

async def show_top_by_growth(message: types.Message):
    # Упрощённая версия - показываем общий заработок
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, total_earned FROM users 
        ORDER BY total_earned DESC LIMIT 10
    ''')
    result = cursor.fetchall()
    conn.close()
    
    text = "📈 *Топ по приросту:*\n\n"
    for i, (user_id, username, earned) in enumerate(result, 1):
        medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
        text += f"{medal} @{username or 'anon'} — +{earned:.2f} JET\n"
    
    await message.edit_text(text, reply_markup=get_top_keyboard())

async def show_top_by_trades(message: types.Message):
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, COUNT(*) as trades 
        FROM transactions t
        JOIN users u ON t.user_id = u.user_id
        GROUP BY user_id
        ORDER BY trades DESC LIMIT 10
    ''')
    result = cursor.fetchall()
    conn.close()
    
    text = "🎯 *Топ по количеству сделок:*\n\n"
    for i, (user_id, username, trades) in enumerate(result, 1):
        medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
        text += f"{medal} @{username or 'anon'} — {trades} сделок\n"
    
    await message.edit_text(text, reply_markup=get_top_keyboard())

async def show_top_by_crashes(message: types.Message):
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, COUNT(*) as bets 
        FROM crash_bets cb
        JOIN users u ON cb.user_id = u.user_id
        WHERE status = 'win'
        GROUP BY user_id
        ORDER BY bets DESC LIMIT 10
    ''')
    result = cursor.fetchall()
    conn.close()
    
    text = "💀 *Топ по краш-прибыли:*\n\n"
    for i, (user_id, username, bets) in enumerate(result, 1):
        medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
        text += f"{medal} @{username or 'anon'} — {bets} выигрышей\n"
    
    await message.edit_text(text, reply_markup=get_top_keyboard())

async def show_news(message: types.Message):
    news_list = [
        "🐳 Крупный кит скупает PEPE! Ожидается рост!",
        "🚀 Слухи о листинге DOGE на крупной бирже!",
        "📉 Инфляция ударила по мемам! Рынок падает!",
        "🤖 Илон Маск твитнул про SHIB! Волатильность!",
        "📊 Аналитики прогнозируют рост PEPE на 30%",
        "🔥 DOGE показывает рекордную волатильность!",
        "💀 SHIB под угрозой краша! Инвесторы паникуют!",
        "🎉 PEPE достиг исторического максимума!",
        "⚠️ Рынок перегрет! Ожидается коррекция!",
        "💪 DOGE продолжает рост! Быки атакуют!"
    ]
    
    news = random.choice(news_list)
    await message.edit_text(
        f"📰 *Новости рынка*\n\n{news}",
        reply_markup=get_main_keyboard()
    )

async def show_referral(user_id: int, message: types.Message):
    ref_count = db.get_referral_count(user_id)
    link = f"https://t.me/{bot.username}?start=ref_{user_id}"
    
    text = (
        "👥 *Реферальная система*\n\n"
        f"Твоя ссылка:\n`{link}`\n\n"
        f"👥 Приведено друзей: {ref_count}\n"
        f"🎁 Бонус за друга: {REFERRAL_BONUS} JET\n\n"
    )
    
    if ref_count >= 5:
        text += "🔓 *Доступ к сигнальному чату открыт!*\n"
        text += "Ты получаешь подсказки о крашах!"
    else:
        text += f"🔒 Осталось привести {5 - ref_count} друзей для доступа к сигналам!"
    
    await message.edit_text(text, reply_markup=get_main_keyboard())

async def show_help(message: types.Message):
    text = (
        "📖 *Помощь по боту «КриптоКаток»*\n\n"
        "💰 *Основные команды:*\n"
        "/start — Главное меню\n"
        "/trade — Торговая панель\n"
        "/profile — Профиль\n"
        "/stake — Стейкинг\n"
        "/top — Топ игроков\n"
        "/daily — Ежедневный бонус\n"
        "/referral — Рефералы\n"
        "/news — Новости\n"
        "/help — Помощь\n\n"
        "📈 *Как играть:*\n"
        "1. Покупай активы по низкой цене\n"
        "2. Продавай по высокой\n"
        "3. Следи за риском краша\n"
        "4. Используй плечо для увеличения прибыли\n"
        "5. Стейкай монеты для пассивного дохода\n\n"
        "💀 *Краш-механика:*\n"
        "Активы могут резко падать на 50-80%!\n"
        "Риск краша для SHIB выше, но и прибыль больше!"
    )
    
    await message.edit_text(text, reply_markup=get_main_keyboard())

async def claim_daily(user_id: int, message: types.Message):
    last_daily, streak = db.get_daily_info(user_id)
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Проверка на пропуск
    if last_daily:
        last_date = datetime.strptime(last_daily, '%Y-%m-%d')
        diff = (datetime.now() - last_date).days
        if diff > 1:
            streak = 0
        elif diff == 0:
            await message.edit_text(
                "🎁 *Ежедневный бонус*\n\n"
                "❌ Ты уже получил бонус сегодня!\n"
                f"Завтра будет: {DAILY_BONUSES[min(streak, 6)]} JET",
                reply_markup=get_main_keyboard()
            )
            return
    
    # Начисляем бонус
    if streak >= len(DAILY_BONUSES):
        streak = len(DAILY_BONUSES) - 1
    
    bonus = DAILY_BONUSES[streak]
    db.update_balance(user_id, bonus)
    db.update_daily(user_id, streak + 1)
    
    await message.edit_text(
        f"🎁 *Ежедневный бонус получен!*\n\n"
        f"💰 +{bonus} JET\n"
        f"📅 День {streak + 1} из 7\n"
        f"📊 Новый баланс: {db.get_user(user_id)['balance']:.2f} JET\n\n"
        f"Завтра будет: {DAILY_BONUSES[min(streak + 1, 6)]} JET",
        reply_markup=get_main_keyboard()
    )

# ==================== ДОСТИЖЕНИЯ ====================

async def check_achievements(user_id: int, message: types.Message):
    user = db.get_user(user_id)
    portfolio = db.get_portfolio(user_id)
    capital = db.get_total_capital(user_id)
    achievements = db.get_achievements(user_id)
    
    new_achievements = []
    
    # 1. Первая сделка
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM transactions WHERE user_id = ?', (user_id,))
    trades = cursor.fetchone()[0]
    conn.close()
    
    if trades >= 1 and 1 not in achievements:
        new_achievements.append(1)
        db.add_achievement(user_id, 1)
    
    # 2. Хомяк (10 проигрышей подряд)
    # Упрощённо: проверяем последние 10 транзакций
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT type FROM transactions 
        WHERE user_id = ? 
        ORDER BY timestamp DESC LIMIT 10
    ''', (user_id,))
    last_trades = cursor.fetchall()
    conn.close()
    
    if len(last_trades) >= 10 and all(t[0] == 'sell' for t in last_trades) and 2 not in achievements:
        new_achievements.append(2)
        db.add_achievement(user_id, 2)
    
    # 3. Кит (портфель > 1000 любого актива)
    for asset, amount in portfolio.items():
        if amount > 1000 and 3 not in achievements:
            new_achievements.append(3)
            db.add_achievement(user_id, 3)
            break
    
    # 4. Миллионер
    if capital > 1000000 and 4 not in achievements:
        new_achievements.append(4)
        db.add_achievement(user_id, 4)
    
    # 5. Инвестор (все 3 актива)
    has_all = all(amount > 0 for amount in portfolio.values())
    if has_all and 5 not in achievements:
        new_achievements.append(5)
        db.add_achievement(user_id, 5)
    
    # 6. Стейкер
    if user['stake_amount'] >= 1000 and 6 not in achievements:
        new_achievements.append(6)
        db.add_achievement(user_id, 6)
    
    # 7. Лидер (проверим топ-3)
    top = db.get_top_users(3)
    if any(t[0] == user_id for t in top) and 7 not in achievements:
        new_achievements.append(7)
        db.add_achievement(user_id, 7)
    
    # Уведомляем о новых достижениях
    achievements_names = {
        1: "🏅 Первая сделка",
        2: "💀 Хомяк",
        3: "🐋 Кит",
        4: "👑 Миллионер",
        5: "📊 Инвестор",
        6: "🔒 Стейкер",
        7: "🏆 Лидер"
    }
    
    if new_achievements:
        for ach_id in new_achievements:
            await message.answer(
                f"🎉 *Новое достижение!*\n\n{achievements_names.get(ach_id, '')}",
                reply_markup=get_main_keyboard()
            )

# ==================== ФОНОВЫЕ ПРОЦЕССЫ ====================

async def update_prices():
    """Фоновый процесс обновления цен"""
    while True:
        try:
            for asset in ASSETS:
                current_price = db.get_price(asset)
                volatility = ASSETS[asset]['volatility']
                
                # Случайное изменение
                change = random.uniform(1 - volatility, 1 + volatility)
                new_price = current_price * change
                
                # Проверка на краш
                is_crash, crash_percent = check_crash(asset)
                if is_crash:
                    new_price = current_price * (1 - crash_percent)
                    logger.info(f"💥 CRASH on {asset}! -{crash_percent*100:.1f}%")
                    
                    # Уведомление о краше (всем пользователям)
                    users = db.get_all_users()
                    for user_id in users:
                        try:
                            await bot.send_message(
                                user_id,
                                f"💥 *КРАШ!*\n\n"
                                f"{ASSETS[asset]['emoji']} *{asset}* упал на {crash_percent*100:.1f}%!\n"
                                f"Новая цена: {new_price:.4f} JET",
                                reply_markup=get_main_keyboard()
                            )
                        except:
                            pass
                
                # Защита от бесконечного роста
                if new_price > 10.0 or new_price < 0.001:
                    new_price = ASSETS[asset]['initial_price']
                
                db.update_price(asset, new_price)
                logger.info(f"📊 Price updated: {asset} = {new_price:.4f}")
            
            await asyncio.sleep(UPDATE_INTERVAL)
            
        except Exception as e:
            logger.error(f"Error in update_prices: {e}")
            await asyncio.sleep(60)

async def check_stakes():
    """Проверка просроченных стейков"""
    while True:
        try:
            conn = db.get_connection()
            cursor = conn.cursor()
            current_time = int(datetime.now().timestamp())
            
            cursor.execute('''
                SELECT user_id, stake_amount FROM users 
                WHERE stake_amount > 0 AND stake_time + ? <= ?
            ''', (STAKE_HOURS * 3600, current_time))
            
            ready_stakes = cursor.fetchall()
            conn.close()
            
            for user_id, amount in ready_stakes:
                bonus = amount * (STAKE_PERCENT / 100)
                total = amount + bonus
                
                db.update_balance(user_id, total)
                db.update_stake(user_id, 0, 0)
                
                await bot.send_message(
                    user_id,
                    f"🔓 *Стейк автоматически разблокирован!*\n\n"
                    f"💰 Сумма: {amount:.2f} JET\n"
                    f"🎁 Бонус: {bonus:.2f} JET\n"
                    f"✅ Всего: {total:.2f} JET",
                    reply_markup=get_main_keyboard()
                )
                logger.info(f"Stake unlocked for user {user_id}")
            
            await asyncio.sleep(60)
            
        except Exception as e:
            logger.error(f"Error in check_stakes: {e}")
            await asyncio.sleep(60)

async def reset_daily():
    """Сброс ежедневных бонусов в 00:00"""
    while True:
        try:
            now = datetime.now()
            # Ждём до полуночи
            next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            await asyncio.sleep((next_midnight - now).total_seconds())
            
            conn = db.get_connection()
            cursor = conn.cursor()
            yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            
            cursor.execute('''
                UPDATE users SET daily_streak = 0 
                WHERE last_daily != ? OR last_daily IS NULL
            ''', (yesterday,))
            conn.commit()
            conn.close()
            
            logger.info("Daily streaks reset")
            
        except Exception as e:
            logger.error(f"Error in reset_daily: {e}")
            await asyncio.sleep(60)

# ==================== ЗАПУСК БОТА ====================

async def main():
    # Запускаем фоновые задачи
    asyncio.create_task(update_prices())
    asyncio.create_task(check_stakes())
    asyncio.create_task(reset_daily())
    
    # Запускаем бота
    logger.info("🚀 Bot started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
