# bot.py
import asyncio
import random
import sqlite3
import json
import logging
import os
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal, getcontext
from collections import defaultdict

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
    InputFile, BufferedInputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

# Настройка точности
getcontext().prec = 12
load_dotenv()

# ==================== ЛОГИРОВАНИЕ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found!")

# ==================== КОНФИГУРАЦИЯ ====================
class Config:
    # Торговля
    COMMISSION = Decimal('0.005')  # 0.5%
    UPDATE_INTERVAL = 45  # 45 секунд
    MAX_LEVERAGE = 10
    MIN_TRADE = Decimal('0.1')
    MAX_TRADE = Decimal('1000000')
    
    # Стейкинг
    STAKE_PERCENT = Decimal('10')
    STAKE_HOURS = 8
    MIN_STAKE = Decimal('10')
    MAX_STAKE = Decimal('1000000')
    
    # Бонусы
    REFERRAL_BONUS = Decimal('1000')
    DAILY_BONUSES = [100, 200, 400, 700, 1200, 2000, 3500, 5000, 7500, 10000]
    
    # Краш
    CRASH_COOLDOWN = 180
    CRASH_MIN = 30
    CRASH_MAX = 90
    
    # Рост
    GROWTH_MIN = Decimal('1.05')
    GROWTH_MAX = Decimal('1.30')
    PRICE_START = Decimal('100')
    PRICE_MAX = Decimal('9999999')
    
    # Игрок
    START_BALANCE = Decimal('50000')
    
    # VIP
    VIP_LEVELS = {
        0: {'name': 'Новичок', 'bonus': 0, 'color': '⬜'},
        1: {'name': 'Бронза', 'bonus': 2, 'color': '🥉', 'min_deposit': 10000},
        2: {'name': 'Серебро', 'bonus': 5, 'color': '🥈', 'min_deposit': 50000},
        3: {'name': 'Золото', 'bonus': 10, 'color': '🥇', 'min_deposit': 200000},
        4: {'name': 'Платина', 'bonus': 15, 'color': '💎', 'min_deposit': 1000000},
        5: {'name': 'Алмаз', 'bonus': 25, 'color': '👑', 'min_deposit': 5000000}
    }

# Активы
ASSETS = {
    'PEPE': {
        'name': 'PEPE', 'emoji': '🐸', 'color': '🟢',
        'initial': Decimal('100'), 'crash_risk': 5,
        'volatility': Decimal('0.06'), 'growth': Decimal('1.3'),
        'rarity': 'common'
    },
    'DOGE': {
        'name': 'DOGE', 'emoji': '🐕', 'color': '🔵',
        'initial': Decimal('50'), 'crash_risk': 12,
        'volatility': Decimal('0.12'), 'growth': Decimal('1.4'),
        'rarity': 'uncommon'
    },
    'SHIB': {
        'name': 'SHIB', 'emoji': '🔥', 'color': '🔴',
        'initial': Decimal('1'), 'crash_risk': 20,
        'volatility': Decimal('0.20'), 'growth': Decimal('1.5'),
        'rarity': 'rare'
    },
    'FLOKI': {
        'name': 'FLOKI', 'emoji': '⚡', 'color': '🟡',
        'initial': Decimal('10'), 'crash_risk': 15,
        'volatility': Decimal('0.18'), 'growth': Decimal('1.45'),
        'rarity': 'rare'
    },
    'BONK': {
        'name': 'BONK', 'emoji': '🐶', 'color': '🟣',
        'initial': Decimal('0.1'), 'crash_risk': 30,
        'volatility': Decimal('0.30'), 'growth': Decimal('1.6'),
        'rarity': 'epic'
    }
}

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==================== FSM СОСТОЯНИЯ ====================
class TradeFSM(StatesGroup):
    asset = State()
    amount = State()
    confirm = State()
    limit_buy = State()
    limit_sell = State()

class StakeFSM(StatesGroup):
    amount = State()

class CrashFSM(StatesGroup):
    asset = State()
    amount = State()

class P2PFSM(StatesGroup):
    create = State()
    amount = State()
    price = State()

class FarmFSM(StatesGroup):
    select = State()

class TournamentFSM(StatesGroup):
    join = State()

class WithdrawFSM(StatesGroup):
    amount = State()

class TransferFSM(StatesGroup):
    user = State()
    amount = State()

# ==================== БАЗА ДАННЫХ ====================
class Database:
    def __init__(self, db_name='crypto_bot.db'):
        self.db_name = db_name
        self.init_db()

    def get_conn(self):
        return sqlite3.connect(self.db_name)

    def init_db(self):
        conn = self.get_conn()
        c = conn.cursor()

        # Users
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 50000.0,
                vip_level INTEGER DEFAULT 0,
                referral_count INTEGER DEFAULT 0,
                last_daily TEXT,
                daily_streak INTEGER DEFAULT 0,
                total_earned REAL DEFAULT 0.0,
                stake_amount REAL DEFAULT 0.0,
                stake_time INTEGER DEFAULT 0,
                leverage INTEGER DEFAULT 1,
                last_activity INTEGER,
                total_trades INTEGER DEFAULT 0,
                win_trades INTEGER DEFAULT 0,
                farm_level INTEGER DEFAULT 0,
                farm_exp REAL DEFAULT 0.0,
                farm_last_claim INTEGER DEFAULT 0,
                total_deposit REAL DEFAULT 0.0,
                withdrawable REAL DEFAULT 0.0
            )
        ''')

        # Portfolio
        c.execute('''
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                asset TEXT,
                amount REAL DEFAULT 0.0,
                avg_price REAL DEFAULT 0.0,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(user_id, asset)
            )
        ''')

        # Prices
        c.execute('''
            CREATE TABLE IF NOT EXISTS prices (
                asset TEXT PRIMARY KEY,
                price REAL,
                timestamp INTEGER,
                change_24h REAL DEFAULT 0.0,
                volume REAL DEFAULT 0.0
            )
        ''')

        # Price history
        c.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT,
                price REAL,
                timestamp INTEGER
            )
        ''')

        # Transactions
        c.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                asset TEXT,
                amount REAL,
                price REAL,
                profit REAL DEFAULT 0.0,
                timestamp INTEGER
            )
        ''')

        # Crash bets
        c.execute('''
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

        # Referrals
        c.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                new_user_id INTEGER,
                timestamp INTEGER
            )
        ''')

        # Achievements
        c.execute('''
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                achievement_id INTEGER,
                timestamp INTEGER,
                UNIQUE(user_id, achievement_id)
            )
        ''')

        # P2P offers
        c.execute('''
            CREATE TABLE IF NOT EXISTS p2p_offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                asset TEXT,
                amount REAL,
                price REAL,
                type TEXT,
                status TEXT,
                timestamp INTEGER
            )
        ''')

        # Tournaments
        c.execute('''
            CREATE TABLE IF NOT EXISTS tournaments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                prize REAL,
                start_time INTEGER,
                end_time INTEGER,
                status TEXT,
                participants INTEGER DEFAULT 0
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS tournament_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id INTEGER,
                user_id INTEGER,
                profit REAL DEFAULT 0.0,
                rank INTEGER DEFAULT 0
            )
        ''')

        # Init prices
        for asset, data in ASSETS.items():
            c.execute('''
                INSERT OR IGNORE INTO prices (asset, price, timestamp)
                VALUES (?, ?, ?)
            ''', (asset, float(data['initial']), int(datetime.now().timestamp())))

        conn.commit()
        conn.close()
        logger.info("DB initialized")

    # ========== GETTERS ==========
    def get_price(self, asset: str) -> Decimal:
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT price FROM prices WHERE asset = ?', (asset,))
        r = c.fetchone()
        conn.close()
        return Decimal(str(r[0])) if r else ASSETS[asset]['initial']

    def get_price_history(self, asset: str, limit: int = 30) -> List[Decimal]:
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('''
            SELECT price FROM price_history 
            WHERE asset = ? ORDER BY timestamp DESC LIMIT ?
        ''', (asset, limit))
        r = c.fetchall()
        conn.close()
        return [Decimal(str(x[0])) for x in r[::-1]]

    def get_user(self, user_id: int) -> Optional[Dict]:
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        r = c.fetchone()
        conn.close()
        if r:
            cols = ['user_id', 'username', 'balance', 'vip_level', 'referral_count',
                   'last_daily', 'daily_streak', 'total_earned', 'stake_amount',
                   'stake_time', 'leverage', 'last_activity', 'total_trades',
                   'win_trades', 'farm_level', 'farm_exp', 'farm_last_claim',
                   'total_deposit', 'withdrawable']
            data = dict(zip(cols, r))
            for k in ['balance', 'total_earned', 'stake_amount', 'farm_exp',
                     'total_deposit', 'withdrawable']:
                data[k] = Decimal(str(data[k]))
            return data
        return None

    def get_portfolio(self, user_id: int) -> Dict[str, Dict]:
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT asset, amount, avg_price FROM portfolio WHERE user_id = ?', (user_id,))
        r = c.fetchall()
        conn.close()
        return {x[0]: {'amount': Decimal(str(x[1])), 'avg_price': Decimal(str(x[2]))} for x in r}

    # ========== SETTERS ==========
    def update_price(self, asset: str, price: Decimal):
        conn = self.get_conn()
        c = conn.cursor()
        ts = int(datetime.now().timestamp())
        c.execute('UPDATE prices SET price = ?, timestamp = ? WHERE asset = ?', (float(price), ts, asset))
        c.execute('INSERT INTO price_history (asset, price, timestamp) VALUES (?, ?, ?)', (asset, float(price), ts))
        conn.commit()
        conn.close()

    def update_balance(self, user_id: int, amount: Decimal):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (float(amount), user_id))
        conn.commit()
        conn.close()

    def set_balance(self, user_id: int, amount: Decimal):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('UPDATE users SET balance = ? WHERE user_id = ?', (float(amount), user_id))
        conn.commit()
        conn.close()

    def update_portfolio(self, user_id: int, asset: str, amount: Decimal, avg_price: Optional[Decimal] = None):
        conn = self.get_conn()
        c = conn.cursor()
        if avg_price is not None:
            c.execute('''
                UPDATE portfolio SET amount = ?, avg_price = ? 
                WHERE user_id = ? AND asset = ?
            ''', (float(amount), float(avg_price), user_id, asset))
        else:
            c.execute('''
                UPDATE portfolio SET amount = amount + ? 
                WHERE user_id = ? AND asset = ?
            ''', (float(amount), user_id, asset))
        conn.commit()
        conn.close()

    def create_user(self, user_id: int, username: str = None):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('''
            INSERT INTO users (user_id, username, balance, last_activity)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, float(Config.START_BALANCE), int(datetime.now().timestamp())))
        for asset in ASSETS:
            c.execute('''
                INSERT INTO portfolio (user_id, asset, amount, avg_price)
                VALUES (?, ?, 0.0, 0.0)
            ''', (user_id, asset))
        conn.commit()
        conn.close()

    def add_transaction(self, user_id: int, ttype: str, asset: str, amount: Decimal, price: Decimal, profit: Decimal = Decimal('0')):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('''
            INSERT INTO transactions (user_id, type, asset, amount, price, profit, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, ttype, asset, float(amount), float(price), float(profit), int(datetime.now().timestamp())))
        if ttype == 'sell':
            c.execute('UPDATE users SET total_trades = total_trades + 1 WHERE user_id = ?', (user_id,))
            if profit > 0:
                c.execute('UPDATE users SET win_trades = win_trades + 1, total_earned = total_earned + ? WHERE user_id = ?',
                         (float(profit), user_id))
        conn.commit()
        conn.close()

    def add_referral(self, referrer_id: int, new_user_id: int):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('INSERT INTO referrals (referrer_id, new_user_id, timestamp) VALUES (?, ?, ?)',
                 (referrer_id, new_user_id, int(datetime.now().timestamp())))
        c.execute('UPDATE users SET referral_count = referral_count + 1 WHERE user_id = ?', (referrer_id,))
        conn.commit()
        conn.close()

    def get_referral_count(self, user_id: int) -> int:
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT referral_count FROM users WHERE user_id = ?', (user_id,))
        r = c.fetchone()
        conn.close()
        return r[0] if r else 0

    def add_achievement(self, user_id: int, ach_id: int):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO achievements (user_id, achievement_id, timestamp) VALUES (?, ?, ?)',
                 (user_id, ach_id, int(datetime.now().timestamp())))
        conn.commit()
        conn.close()

    def get_achievements(self, user_id: int) -> List[int]:
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT achievement_id FROM achievements WHERE user_id = ?', (user_id,))
        r = c.fetchall()
        conn.close()
        return [x[0] for x in r]

    def get_all_users(self) -> List[int]:
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT user_id FROM users')
        r = c.fetchall()
        conn.close()
        return [x[0] for x in r]

    def get_total_capital(self, user_id: int) -> Decimal:
        user = self.get_user(user_id)
        portfolio = self.get_portfolio(user_id)
        total = user['balance']
        for asset, data in portfolio.items():
            total += data['amount'] * self.get_price(asset)
        return total

    def get_rank(self, user_id: int) -> int:
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT user_id FROM users ORDER BY balance DESC')
        r = c.fetchall()
        conn.close()
        for i, (uid,) in enumerate(r, 1):
            if uid == user_id:
                return i
        return len(r)

    def get_top(self, limit: int = 10) -> List[Tuple[int, str, Decimal, Decimal]]:
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT user_id, username, balance, total_earned FROM users ORDER BY balance DESC LIMIT ?', (limit,))
        r = c.fetchall()
        conn.close()
        return [(x[0], x[1], Decimal(str(x[2])), Decimal(str(x[3]))) for x in r]

    def update_stake(self, user_id: int, amount: Decimal, stake_time: int):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('UPDATE users SET stake_amount = ?, stake_time = ? WHERE user_id = ?',
                 (float(amount), stake_time, user_id))
        conn.commit()
        conn.close()

    def update_daily(self, user_id: int, streak: int):
        conn = self.get_conn()
        c = conn.cursor()
        today = datetime.now().strftime('%Y-%m-%d')
        c.execute('UPDATE users SET last_daily = ?, daily_streak = ? WHERE user_id = ?',
                 (today, streak, user_id))
        conn.commit()
        conn.close()

    def get_daily(self, user_id: int) -> Tuple[Optional[str], int]:
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT last_daily, daily_streak FROM users WHERE user_id = ?', (user_id,))
        r = c.fetchone()
        conn.close()
        return (r[0], r[1]) if r else (None, 0)

    def get_trade_stats(self, user_id: int) -> Dict:
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT total_trades, win_trades FROM users WHERE user_id = ?', (user_id,))
        r = c.fetchone()
        conn.close()
        return {'total': r[0] if r else 0, 'win': r[1] if r else 0}

    def get_vip_level(self, user_id: int) -> int:
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT vip_level FROM users WHERE user_id = ?', (user_id,))
        r = c.fetchone()
        conn.close()
        return r[0] if r else 0

    def update_vip(self, user_id: int, level: int):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('UPDATE users SET vip_level = ? WHERE user_id = ?', (level, user_id))
        conn.commit()
        conn.close()

    def get_weekly_top(self, limit: int = 10) -> List[Tuple[int, str, Decimal]]:
        conn = self.get_conn()
        c = conn.cursor()
        week_ago = int((datetime.now() - timedelta(days=7)).timestamp())
        c.execute('''
            SELECT u.user_id, u.username, SUM(t.profit) as profit
            FROM transactions t JOIN users u ON t.user_id = u.user_id
            WHERE t.timestamp > ? AND t.type = 'sell'
            GROUP BY t.user_id ORDER BY profit DESC LIMIT ?
        ''', (week_ago, limit))
        r = c.fetchall()
        conn.close()
        return [(x[0], x[1], Decimal(str(x[2]) if x[2] else 0)) for x in r]

    def update_farm(self, user_id: int, level: int, exp: Decimal, last_claim: int):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('''
            UPDATE users SET farm_level = ?, farm_exp = ?, farm_last_claim = ?
            WHERE user_id = ?
        ''', (level, float(exp), last_claim, user_id))
        conn.commit()
        conn.close()

    def get_farm(self, user_id: int) -> Tuple[int, Decimal, int]:
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT farm_level, farm_exp, farm_last_claim FROM users WHERE user_id = ?', (user_id,))
        r = c.fetchone()
        conn.close()
        if r:
            return r[0], Decimal(str(r[1])), r[2]
        return 0, Decimal('0'), 0

    def add_p2p_offer(self, user_id: int, asset: str, amount: Decimal, price: Decimal, otype: str):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('''
            INSERT INTO p2p_offers (user_id, asset, amount, price, type, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, asset, float(amount), float(price), otype, 'active', int(datetime.now().timestamp())))
        offer_id = c.lastrowid
        conn.commit()
        conn.close()
        return offer_id

    def get_p2p_offers(self, asset: str = None, otype: str = None) -> List[Dict]:
        conn = self.get_conn()
        c = conn.cursor()
        query = 'SELECT * FROM p2p_offers WHERE status = "active"'
        params = []
        if asset:
            query += ' AND asset = ?'
            params.append(asset)
        if otype:
            query += ' AND type = ?'
            params.append(otype)
        query += ' ORDER BY timestamp DESC'
        c.execute(query, params)
        r = c.fetchall()
        conn.close()
        cols = ['id', 'user_id', 'asset', 'amount', 'price', 'type', 'status', 'timestamp']
        return [dict(zip(cols, x)) for x in r]

    def update_p2p_status(self, offer_id: int, status: str):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('UPDATE p2p_offers SET status = ? WHERE id = ?', (status, offer_id))
        conn.commit()
        conn.close()

    def create_tournament(self, name: str, prize: Decimal, duration_hours: int):
        conn = self.get_conn()
        c = conn.cursor()
        now = int(datetime.now().timestamp())
        c.execute('''
            INSERT INTO tournaments (name, prize, start_time, end_time, status)
            VALUES (?, ?, ?, ?, ?)
        ''', (name, float(prize), now, now + duration_hours * 3600, 'active'))
        t_id = c.lastrowid
        conn.commit()
        conn.close()
        return t_id

    def join_tournament(self, tournament_id: int, user_id: int):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('''
            INSERT OR IGNORE INTO tournament_participants (tournament_id, user_id)
            VALUES (?, ?)
        ''', (tournament_id, user_id))
        c.execute('UPDATE tournaments SET participants = participants + 1 WHERE id = ?', (tournament_id,))
        conn.commit()
        conn.close()

    def get_tournament_ranking(self, tournament_id: int) -> List[Tuple[int, str, Decimal]]:
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('''
            SELECT u.user_id, u.username, tp.profit
            FROM tournament_participants tp
            JOIN users u ON tp.user_id = u.user_id
            WHERE tp.tournament_id = ?
            ORDER BY tp.profit DESC
        ''', (tournament_id,))
        r = c.fetchall()
        conn.close()
        return [(x[0], x[1], Decimal(str(x[2]))) for x in r]

    def update_tournament_profit(self, tournament_id: int, user_id: int, profit: Decimal):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('''
            UPDATE tournament_participants SET profit = profit + ?
            WHERE tournament_id = ? AND user_id = ?
        ''', (float(profit), tournament_id, user_id))
        conn.commit()
        conn.close()

db = Database()

# ==================== КЛАВИАТУРЫ ====================
def main_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📈 Торговля", callback_data="trade"),
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile")
    )
    builder.row(
        InlineKeyboardButton(text="🔒 Стейкинг", callback_data="stake"),
        InlineKeyboardButton(text="🏆 Топ", callback_data="top")
    )
    builder.row(
        InlineKeyboardButton(text="💀 Краш-арена", callback_data="crash"),
        InlineKeyboardButton(text="🌾 Ферма", callback_data="farm")
    )
    builder.row(
        InlineKeyboardButton(text="🔄 P2P-биржа", callback_data="p2p"),
        InlineKeyboardButton(text="🏅 Турниры", callback_data="tournaments")
    )
    builder.row(
        InlineKeyboardButton(text="🎁 Дейли", callback_data="daily"),
        InlineKeyboardButton(text="👥 Рефералы", callback_data="referral")
    )
    builder.row(
        InlineKeyboardButton(text="📰 Новости", callback_data="news"),
        InlineKeyboardButton(text="❓ Помощь", callback_data="help")
    )
    return builder.as_markup()

def assets_kb(back: str = "back_main") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for asset, data in ASSETS.items():
        price = db.get_price(asset)
        change = get_change(asset)
        arrow = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
        builder.row(
            InlineKeyboardButton(
                text=f"{data['emoji']} {asset} {data['color']} {price:.2f} {arrow}",
                callback_data=f"asset_{asset}"
            )
        )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back))
    return builder.as_markup()

def trade_kb(asset: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    price = db.get_price(asset)
    builder.row(
        InlineKeyboardButton(text=f"📊 {price:.2f}", callback_data="refresh"),
        InlineKeyboardButton(text=f"💀 Риск {get_crash_risk(asset)}%", callback_data="show_risk")
    )
    builder.row(
        InlineKeyboardButton(text="💰 Купить", callback_data=f"buy_{asset}"),
        InlineKeyboardButton(text="💸 Продать", callback_data=f"sell_{asset}")
    )
    builder.row(
        InlineKeyboardButton(text="x2", callback_data=f"lev_{asset}_2"),
        InlineKeyboardButton(text="x5", callback_data=f"lev_{asset}_5"),
        InlineKeyboardButton(text="x10", callback_data=f"lev_{asset}_10")
    )
    builder.row(
        InlineKeyboardButton(text="📈 Лимит-ордер", callback_data=f"limit_buy_{asset}"),
        InlineKeyboardButton(text="📉 Лимит-продажа", callback_data=f"limit_sell_{asset}")
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh_{asset}"),
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_assets")
    )
    return builder.as_markup()

def profile_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💰 Баланс", callback_data="p_balance"),
        InlineKeyboardButton(text="📦 Портфель", callback_data="p_portfolio")
    )
    builder.row(
        InlineKeyboardButton(text="🏅 Достижения", callback_data="p_achievements"),
        InlineKeyboardButton(text="📈 Статистика", callback_data="p_stats")
    )
    builder.row(
        InlineKeyboardButton(text="💎 VIP-статус", callback_data="p_vip"),
        InlineKeyboardButton(text="📊 Капитал", callback_data="p_capital")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")
    )
    return builder.as_markup()

def stake_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔒 Застейкать", callback_data="stake_do"),
        InlineKeyboardButton(text="🔓 Забрать", callback_data="unstake")
    )
    builder.row(
        InlineKeyboardButton(text="📊 Мой стейк", callback_data="my_stake")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")
    )
    return builder.as_markup()

def top_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🏆 По капиталу", callback_data="top_capital"),
        InlineKeyboardButton(text="📈 По прибыли", callback_data="top_profit")
    )
    builder.row(
        InlineKeyboardButton(text="🎯 По сделкам", callback_data="top_trades"),
        InlineKeyboardButton(text="💀 По крашам", callback_data="top_crashes")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")
    )
    return builder.as_markup()

def confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да", callback_data="confirm_yes"),
        InlineKeyboardButton(text="❌ Нет", callback_data="confirm_no")
    )
    return builder.as_markup()

def cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    return builder.as_markup()

def crash_kb(asset: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📈 Рост x1.5", callback_data=f"cr_up_{asset}"),
        InlineKeyboardButton(text="📉 Падение x2.5", callback_data=f"cr_down_{asset}")
    )
    builder.row(
        InlineKeyboardButton(text="🎰 Лотерея x4", callback_data=f"cr_auto_{asset}")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_assets")
    )
    return builder.as_markup()

def farm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🌾 Собрать урожай", callback_data="farm_claim"),
        InlineKeyboardButton(text="📊 Ферма", callback_data="farm_info")
    )
    builder.row(
        InlineKeyboardButton(text="⬆️ Улучшить", callback_data="farm_upgrade")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")
    )
    return builder.as_markup()

def p2p_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📈 Купить", callback_data="p2p_buy"),
        InlineKeyboardButton(text="📉 Продать", callback_data="p2p_sell")
    )
    builder.row(
        InlineKeyboardButton(text="📋 Мои ордера", callback_data="p2p_my"),
        InlineKeyboardButton(text="📊 Все ордера", callback_data="p2p_all")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")
    )
    return builder.as_markup()

def tournament_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🏅 Текущий турнир", callback_data="tournament_current"),
        InlineKeyboardButton(text="📊 Рейтинг", callback_data="tournament_rank")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")
    )
    return builder.as_markup()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ====================
def get_change(asset: str) -> float:
    history = db.get_price_history(asset, 2)
    if len(history) >= 2:
        old, new = history[0], history[-1]
        if old > 0:
            return float((new - old) / old * 100)
    return 0.0

def get_crash_risk(asset: str) -> int:
    base = ASSETS[asset]['crash_risk']
    price = db.get_price(asset)
    initial = ASSETS[asset]['initial']
    ratio = float(price / initial)
    bonus = 0
    if ratio > 10: bonus = 20
    elif ratio > 5: bonus = 12
    elif ratio > 3: bonus = 6
    return min(70, max(3, base + bonus + random.randint(-3, 3)))

def check_crash(asset: str) -> Tuple[bool, Decimal]:
    risk = get_crash_risk(asset)
    if random.randint(1, 100) <= risk:
        pct = Decimal(str(random.randint(Config.CRASH_MIN, Config.CRASH_MAX))) / Decimal('100')
        return True, pct
    return False, Decimal('0')

def calc_price(asset: str) -> Tuple[Decimal, bool, Decimal]:
    current = db.get_price(asset)
    data = ASSETS[asset]
    
    # Рост
    growth = Decimal(str(random.uniform(float(Config.GROWTH_MIN), float(Config.GROWTH_MAX))))
    growth *= data['growth']
    
    # Шум
    noise = Decimal(str(random.uniform(0.97, 1.03)))
    new_price = current * growth * noise
    
    # Краш
    is_crash, crash_pct = check_crash(asset)
    if is_crash:
        new_price = current * (Decimal('1') - crash_pct)
        return new_price, True, crash_pct
    
    return new_price, False, Decimal('0')

def fmt(n: Decimal) -> str:
    if n >= Decimal('1000000'):
        return f"{n/1000000:.2f}M"
    if n >= Decimal('1000'):
        return f"{n:,.2f}"
    return f"{n:.4f}"

def get_vip_info(level: int) -> Dict:
    return Config.VIP_LEVELS.get(level, Config.VIP_LEVELS[0])

# ==================== КОМАНДЫ ====================
@dp.message(Command("start"))
async def start_cmd(msg: types.Message, state: FSMContext):
    uid = msg.from_user.id
    uname = msg.from_user.username or "anon"
    
    user = db.get_user(uid)
    if not user:
        db.create_user(uid, uname)
        logger.info(f"New user: {uid}")
        
        # Рефералка
        args = msg.text.split()
        if len(args) > 1 and args[1].startswith('ref_'):
            try:
                ref_id = int(args[1].replace('ref_', ''))
                if ref_id != uid:
                    db.add_referral(ref_id, uid)
                    db.update_balance(ref_id, Config.REFERRAL_BONUS)
                    await bot.send_message(ref_id,
                        f"🎉 Новый игрок @{uname} по твоей ссылке!\n"
                        f"+{Config.REFERRAL_BONUS:.0f} JET"
                    )
            except:
                pass
    
    await msg.answer(
        f"🚀 *КриптоКаток v3.0*\n\n"
        f"👤 @{uname}\n"
        f"💰 Стартовый капитал: {Config.START_BALANCE:.0f} JET\n\n"
        f"📈 *Цены растут каждую минуту!*\n"
        f"💀 Краши, стейкинг, P2P, турниры и ферма!\n\n"
        f"⬇️ Выбирай действие:",
        reply_markup=main_kb()
    )
    await state.clear()

@dp.message(Command("menu"))
async def menu_cmd(msg: types.Message, state: FSMContext):
    await msg.answer("📋 Главное меню:", reply_markup=main_kb())
    await state.clear()

@dp.callback_query(F.data == "back_main")
async def back_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("📋 Главное меню:", reply_markup=main_kb())
    await cb.answer()

@dp.callback_query(F.data == "back_assets")
async def back_assets(cb: CallbackQuery):
    await cb.message.edit_text(
        "📈 Выбери актив:",
        reply_markup=assets_kb("back_main")
    )
    await cb.answer()

# ==================== ТОРГОВЛЯ ====================
@dp.callback_query(F.data == "trade")
async def trade_cb(cb: CallbackQuery):
    await cb.message.edit_text(
        "📈 *Выбери актив для торговли:*\n\n"
        "🟢 Зелёный — рост\n"
        "🔴 Красный — падение\n"
        "⚪ Стабильно",
        reply_markup=assets_kb("back_main")
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("asset_"))
async def asset_cb(cb: CallbackQuery, state: FSMContext):
    asset = cb.data.replace("asset_", "")
    await state.update_data(asset=asset)
    await cb.message.edit_text(
        get_asset_text(asset),
        reply_markup=trade_kb(asset)
    )
    await cb.answer()

def get_asset_text(asset: str) -> str:
    price = db.get_price(asset)
    change = get_change(asset)
    risk = get_crash_risk(asset)
    history = db.get_price_history(asset, 10)
    
    graph = ""
    if history:
        mn, mx = min(history), max(history)
        rg = mx - mn if mx > mn else Decimal('0.001')
        for val in history[-8:]:
            h = int((val - mn) / rg * 5) + 1
            graph += "█" * h + f" {val:.2f}\n"
    
    arrow = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
    
    return (
        f"{ASSETS[asset]['emoji']} *{asset}* {ASSETS[asset]['color']}\n\n"
        f"💰 Цена: *{price:.2f}* JET\n"
        f"📊 Изм.: *{arrow} {abs(change):.1f}%*\n"
        f"💀 Риск: *{risk}%*\n"
        f"📈 Волатильность: *{ASSETS[asset]['volatility']*100:.0f}%*\n\n"
        f"*График:*\n{graph}\n"
        f"Используй кнопки:"
    )

@dp.callback_query(F.data.startswith("lev_"))
async def lev_cb(cb: CallbackQuery):
    parts = cb.data.split("_")
    asset, level = parts[1], int(parts[2])
    conn = db.get_conn()
    c = conn.cursor()
    c.execute('UPDATE users SET leverage = ? WHERE user_id = ?', (level, cb.from_user.id))
    conn.commit()
    conn.close()
    await cb.answer(f"⚡ Плечо x{level} установлено!", show_alert=True)
    await cb.message.edit_text(
        get_asset_text(asset),
        reply_markup=trade_kb(asset)
    )

@dp.callback_query(F.data.startswith("buy_"))
async def buy_cb(cb: CallbackQuery, state: FSMContext):
    asset = cb.data.replace("buy_", "")
    await state.update_data(action="buy", asset=asset)
    user = db.get_user(cb.from_user.id)
    await cb.message.edit_text(
        f"💰 *Покупка {asset}*\n\n"
        f"Цена: {db.get_price(asset):.2f} JET\n"
        f"Баланс: {user['balance']:.2f} JET\n"
        f"Плечо: x{user['leverage']}\n\n"
        f"Введи количество:",
        reply_markup=cancel_kb()
    )
    await state.set_state(TradeFSM.amount)
    await cb.answer()

@dp.callback_query(F.data.startswith("sell_"))
async def sell_cb(cb: CallbackQuery, state: FSMContext):
    asset = cb.data.replace("sell_", "")
    portfolio = db.get_portfolio(cb.from_user.id)
    if portfolio.get(asset, {}).get('amount', Decimal('0')) <= 0:
        await cb.answer("❌ У тебя нет этого актива!", show_alert=True)
        return
    await state.update_data(action="sell", asset=asset)
    await cb.message.edit_text(
        f"💸 *Продажа {asset}*\n\n"
        f"У тебя: {portfolio[asset]['amount']:.4f}\n"
        f"Цена: {db.get_price(asset):.2f} JET\n\n"
        f"Введи количество:",
        reply_markup=cancel_kb()
    )
    await state.set_state(TradeFSM.amount)
    await cb.answer()

@dp.message(TradeFSM.amount)
async def trade_amount(msg: types.Message, state: FSMContext):
    try:
        amount = Decimal(msg.text)
        if amount <= 0:
            await msg.answer("❌ > 0!", reply_markup=cancel_kb())
            return
        
        data = await state.get_data()
        action, asset = data['action'], data['asset']
        uid = msg.from_user.id
        user = db.get_user(uid)
        price = db.get_price(asset)
        lev = user['leverage']
        
        if action == "buy":
            total = amount * price * (1 + Config.COMMISSION) / Decimal(lev)
            if total > user['balance']:
                await msg.answer(f"❌ Нужно {total:.2f}, есть {user['balance']:.2f}", reply_markup=cancel_kb())
                return
            await state.update_data(amount=amount, total=total)
            await msg.answer(
                f"📊 *Подтверждение покупки*\n\n"
                f"{asset}: {amount:.4f}\n"
                f"Цена: {price:.2f}\n"
                f"Плечо: x{lev}\n"
                f"Итого: {total:.2f}\n\n"
                f"Подтверждаешь?",
                reply_markup=confirm_kb()
            )
        else:
            portfolio = db.get_portfolio(uid)
            if amount > portfolio.get(asset, {}).get('amount', Decimal('0')):
                await msg.answer(f"❌ У тебя только {portfolio[asset]['amount']:.4f}", reply_markup=cancel_kb())
                return
            total = amount * price * (1 - Config.COMMISSION)
            await state.update_data(amount=amount, total=total)
            await msg.answer(
                f"📊 *Подтверждение продажи*\n\n"
                f"{asset}: {amount:.4f}\n"
                f"Цена: {price:.2f}\n"
                f"Итого: {total:.2f}\n\n"
                f"Подтверждаешь?",
                reply_markup=confirm_kb()
            )
        await state.set_state(TradeFSM.confirm)
        
    except:
        await msg.answer("❌ Введи число!", reply_markup=cancel_kb())

@dp.callback_query(F.data == "confirm_yes")
async def confirm_yes(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    action, asset, amount, total = data['action'], data['asset'], data['amount'], data['total']
    uid = cb.from_user.id
    
    if action == "buy":
        price = db.get_price(asset)
        db.update_balance(uid, -total)
        db.update_portfolio(uid, asset, amount)
        db.add_transaction(uid, 'buy', asset, amount, price)
        await cb.message.edit_text(
            f"✅ *Куплено!*\n\n{asset}: +{amount:.4f}\nЦена: {price:.2f}\nСписано: {total:.2f}",
            reply_markup=trade_kb(asset)
        )
    else:
        price = db.get_price(asset)
        portfolio = db.get_portfolio(uid)
        avg = portfolio[asset]['avg_price']
        profit = amount * (price - avg)
        db.update_balance(uid, total)
        db.update_portfolio(uid, asset, -amount)
        db.add_transaction(uid, 'sell', asset, amount, price, profit)
        await cb.message.edit_text(
            f"✅ *Продано!*\n\n{asset}: -{amount:.4f}\nЦена: {price:.2f}\nПолучено: {total:.2f}\n"
            f"Прибыль: {'+' if profit > 0 else ''}{profit:.2f}",
            reply_markup=trade_kb(asset)
        )
        # Tournaments
        await update_tournaments(uid, profit)
    
    await check_achievements(uid, cb.message)
    await state.clear()
    await cb.answer()

@dp.callback_query(F.data == "confirm_no")
async def confirm_no(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("❌ Отменено", reply_markup=main_kb())
    await cb.answer()

@dp.callback_query(F.data == "cancel")
async def cancel_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("❌ Отменено", reply_markup=main_kb())
    await cb.answer()

# ==================== ЛИМИТ-ОРДЕРА ====================
@dp.callback_query(F.data.startswith("limit_buy_"))
async def limit_buy(cb: CallbackQuery, state: FSMContext):
    asset = cb.data.replace("limit_buy_", "")
    await state.update_data(action="limit_buy", asset=asset)
    await cb.message.edit_text(
        f"📈 *Лимит-ордер на покупку {asset}*\n\n"
        f"Введи цену, по которой хочешь купить:",
        reply_markup=cancel_kb()
    )
    await state.set_state(TradeFSM.limit_buy)
    await cb.answer()

@dp.callback_query(F.data.startswith("limit_sell_"))
async def limit_sell(cb: CallbackQuery, state: FSMContext):
    asset = cb.data.replace("limit_sell_", "")
    await state.update_data(action="limit_sell", asset=asset)
    await cb.message.edit_text(
        f"📉 *Лимит-ордер на продажу {asset}*\n\n"
        f"Введи цену, по которой хочешь продать:",
        reply_markup=cancel_kb()
    )
    await state.set_state(TradeFSM.limit_sell)
    await cb.answer()

# ==================== ПРОФИЛЬ ====================
@dp.callback_query(F.data == "profile")
async def profile_cb(cb: CallbackQuery):
    await show_profile(cb.from_user.id, cb.message)
    await cb.answer()

async def show_profile(uid: int, msg: types.Message):
    user = db.get_user(uid)
    capital = db.get_total_capital(uid)
    rank = db.get_rank(uid)
    vip = get_vip_info(user['vip_level'])
    
    text = (
        f"👤 *Профиль* @{user['username'] or 'anon'}\n\n"
        f"💰 Баланс: {fmt(user['balance'])} JET\n"
        f"💎 Капитал: {fmt(capital)} JET\n"
        f"🏆 Рейтинг: #{rank}\n"
        f"{vip['color']} VIP: {vip['name']} (+{vip['bonus']}% бонус)\n"
        f"👥 Рефералов: {user['referral_count']}\n"
        f"🔒 Стейк: {user['stake_amount']:.2f} JET\n"
        f"🌾 Ферма: Lv.{user['farm_level']}\n"
        f"📊 Сделок: {user['total_trades']} (вин {user['win_trades']})"
    )
    await msg.edit_text(text, reply_markup=profile_kb())

@dp.callback_query(F.data == "p_balance")
async def p_balance(cb: CallbackQuery):
    user = db.get_user(cb.from_user.id)
    await cb.message.edit_text(
        f"💰 *Баланс:* {fmt(user['balance'])} JET\n"
        f"💸 Доступно к выводу: {fmt(user['withdrawable'])} JET",
        reply_markup=profile_kb()
    )
    await cb.answer()

@dp.callback_query(F.data == "p_portfolio")
async def p_portfolio(cb: CallbackQuery):
    uid = cb.from_user.id
    portfolio = db.get_portfolio(uid)
    text = "📦 *Портфель:*\n\n"
    total = Decimal('0')
    for asset, data in portfolio.items():
        if data['amount'] > 0:
            price = db.get_price(asset)
            value = data['amount'] * price
            total += value
            profit = (price - data['avg_price']) / data['avg_price'] * 100 if data['avg_price'] > 0 else 0
            emoji = "🟢" if profit > 0 else "🔴" if profit < 0 else "⚪"
            text += f"{ASSETS[asset]['emoji']} *{asset}:* {data['amount']:.4f} ({value:.2f} JET) {emoji} {profit:.1f}%\n"
    if total == 0:
        text = "📦 *Портфель пуст*"
    else:
        text += f"\n💰 *Итого:* {fmt(total)} JET"
    await cb.message.edit_text(text, reply_markup=profile_kb())
    await cb.answer()

@dp.callback_query(F.data == "p_achievements")
async def p_achievements(cb: CallbackQuery):
    uid = cb.from_user.id
    has = db.get_achievements(uid)
    all_ach = {
        1: "🏅 Первая сделка",
        2: "💀 Хомяк (10 проигрышей)",
        3: "🐋 Кит (1000+ актива)",
        4: "👑 Миллиардер (1B JET)",
        5: "📊 Инвестор (все активы)",
        6: "🔒 Стейкер (10k+ стейк)",
        7: "🏆 Лидер (топ-3)",
        8: "🔥 Трейдер (100 сделок)",
        9: "⚡ Спринтер (10 сделок за час)",
        10: "💎 Алмазный VIP",
        11: "🌾 Фермер (Lv.10)",
        12: "👑 Король краша (50 побед)"
    }
    text = "🏅 *Достижения:*\n\n"
    if has:
        for aid in has:
            if aid in all_ach:
                text += f"✅ {all_ach[aid]}\n"
    else:
        text += "❌ Пока нет\n"
    text += "\n*Остальные:*\n"
    for aid, name in all_ach.items():
        if aid not in has:
            text += f"⬜ {name}\n"
    await cb.message.edit_text(text, reply_markup=profile_kb())
    await cb.answer()

@dp.callback_query(F.data == "p_stats")
async def p_stats(cb: CallbackQuery):
    uid = cb.from_user.id
    user = db.get_user(uid)
    stats = db.get_trade_stats(uid)
    wr = (stats['win'] / stats['total'] * 100) if stats['total'] > 0 else 0
    text = (
        f"📈 *Статистика*\n\n"
        f"📊 Сделок: {stats['total']}\n"
        f"🏆 Побед: {stats['win']} ({wr:.1f}%)\n"
        f"💰 Заработано: {fmt(user['total_earned'])} JET\n"
        f"👥 Рефералов: {user['referral_count']}\n"
        f"⚡ Активность: {user['last_activity']}"
    )
    await cb.message.edit_text(text, reply_markup=profile_kb())
    await cb.answer()

@dp.callback_query(F.data == "p_vip")
async def p_vip(cb: CallbackQuery):
    uid = cb.from_user.id
    user = db.get_user(uid)
    level = user['vip_level']
    vip = get_vip_info(level)
    next_vip = get_vip_info(level + 1) if level < 5 else None
    
    text = f"💎 *VIP-статус*\n\n"
    text += f"Твой уровень: {vip['color']} {vip['name']}\n"
    text += f"Бонус к прибыли: +{vip['bonus']}%\n"
    text += f"Депозит: {fmt(user['total_deposit'])} JET\n\n"
    
    if next_vip:
        need = next_vip['min_deposit'] - user['total_deposit']
        text += f"До {next_vip['name']}: {fmt(need)} JET"
    else:
        text += "👑 Максимальный уровень!"
    
    await cb.message.edit_text(text, reply_markup=profile_kb())
    await cb.answer()

@dp.callback_query(F.data == "p_capital")
async def p_capital(cb: CallbackQuery):
    uid = cb.from_user.id
    capital = db.get_total_capital(uid)
    rank = db.get_rank(uid)
    await cb.message.edit_text(
        f"💎 *Капитал:* {fmt(capital)} JET\n"
        f"🏆 Рейтинг: #{rank}\n"
        f"📊 Топ-1: {fmt(db.get_top(1)[0][2]) if db.get_top(1) else '—'}",
        reply_markup=profile_kb()
    )
    await cb.answer()

# ==================== СТЕЙКИНГ ====================
@dp.callback_query(F.data == "stake")
async def stake_cb(cb: CallbackQuery):
    await show_stake(cb.from_user.id, cb.message)
    await cb.answer()

async def show_stake(uid: int, msg: types.Message):
    user = db.get_user(uid)
    text = (
        f"🔒 *Стейкинг*\n\n"
        f"💰 Баланс: {user['balance']:.2f} JET\n"
        f"🔒 Застейкано: {user['stake_amount']:.2f} JET\n"
        f"📊 Доходность: {Config.STAKE_PERCENT}% за {Config.STAKE_HOURS}ч\n"
        f"📉 Мин: {Config.MIN_STAKE:.0f} JET"
    )
    await msg.edit_text(text, reply_markup=stake_kb())

@dp.callback_query(F.data == "stake_do")
async def stake_do(cb: CallbackQuery, state: FSMContext):
    user = db.get_user(cb.from_user.id)
    if user['stake_amount'] > 0:
        await cb.answer("⚠️ Уже есть стейк!", show_alert=True)
        return
    await cb.message.edit_text(
        f"Введи сумму стейка (мин {Config.MIN_STAKE:.0f}):",
        reply_markup=cancel_kb()
    )
    await state.set_state(StakeFSM.amount)
    await cb.answer()

@dp.message(StakeFSM.amount)
async def stake_amount(msg: types.Message, state: FSMContext):
    try:
        amount = Decimal(msg.text)
        if amount < Config.MIN_STAKE:
            await msg.answer(f"❌ Мин {Config.MIN_STAKE:.0f}!", reply_markup=cancel_kb())
            return
        uid = msg.from_user.id
        user = db.get_user(uid)
        if amount > user['balance']:
            await msg.answer(f"❌ Недостаточно!", reply_markup=cancel_kb())
            return
        db.update_balance(uid, -amount)
        db.update_stake(uid, amount, int(datetime.now().timestamp()))
        await state.clear()
        await msg.answer(
            f"🔒 *Стейк создан!*\n\n{amount:.2f} JET на {Config.STAKE_HOURS}ч\nБонус: {amount * Config.STAKE_PERCENT / 100:.2f} JET",
            reply_markup=stake_kb()
        )
    except:
        await msg.answer("❌ Введи число!", reply_markup=cancel_kb())

@dp.callback_query(F.data == "unstake")
async def unstake_cb(cb: CallbackQuery):
    uid = cb.from_user.id
    user = db.get_user(uid)
    if user['stake_amount'] <= 0:
        await cb.answer("❌ Нет стейка!", show_alert=True)
        return
    elapsed = int(datetime.now().timestamp()) - user['stake_time']
    if elapsed < Config.STAKE_HOURS * 3600:
        rem = Config.STAKE_HOURS * 3600 - elapsed
        h, m = rem // 3600, (rem % 3600) // 60
        await cb.answer(f"⏳ Осталось {h}ч {m}мин", show_alert=True)
        return
    bonus = user['stake_amount'] * (Config.STAKE_PERCENT / 100)
    total = user['stake_amount'] + bonus
    db.update_balance(uid, total)
    db.update_stake(uid, Decimal('0'), 0)
    await cb.message.edit_text(
        f"🔓 *Стейк разблокирован!*\n\n+{total:.2f} JET\nБонус: {bonus:.2f}",
        reply_markup=stake_kb()
    )
    await cb.answer()

@dp.callback_query(F.data == "my_stake")
async def my_stake(cb: CallbackQuery):
    uid = cb.from_user.id
    user = db.get_user(uid)
    if user['stake_amount'] <= 0:
        text = "🔒 Нет стейка"
    else:
        elapsed = int(datetime.now().timestamp()) - user['stake_time']
        total_time = Config.STAKE_HOURS * 3600
        progress = min(100, int(elapsed / total_time * 100))
        if elapsed >= total_time:
            status = "✅ Готов к разблокировке"
        else:
            rem = total_time - elapsed
            h, m = rem // 3600, (rem % 3600) // 60
            status = f"⏳ {h}ч {m}мин"
        text = f"🔒 *Стейк*\n\nСумма: {user['stake_amount']:.2f}\nПрогресс: {progress}%\nСтатус: {status}"
    await cb.message.edit_text(text, reply_markup=stake_kb())
    await cb.answer()

# ==================== ТОП ====================
@dp.callback_query(F.data == "top")
async def top_cb(cb: CallbackQuery):
    await cb.message.edit_text("🏆 *Топы*", reply_markup=top_kb())
    await cb.answer()

@dp.callback_query(F.data == "top_capital")
async def top_capital(cb: CallbackQuery):
    top = db.get_top(10)
    text = "🏆 *Топ по капиталу:*\n\n"
    for i, (uid, uname, bal, _) in enumerate(top, 1):
        m = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
        text += f"{m} @{uname or 'anon'} — {fmt(bal)} JET\n"
    await cb.message.edit_text(text, reply_markup=top_kb())
    await cb.answer()

@dp.callback_query(F.data == "top_profit")
async def top_profit(cb: CallbackQuery):
    top = db.get_weekly_top(10)
    text = "📈 *Топ по прибыли (неделя):*\n\n"
    for i, (uid, uname, profit) in enumerate(top, 1):
        m = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
        text += f"{m} @{uname or 'anon'} — +{fmt(profit)} JET\n"
    await cb.message.edit_text(text, reply_markup=top_kb())
    await cb.answer()

@dp.callback_query(F.data == "top_trades")
async def top_trades(cb: CallbackQuery):
    conn = db.get_conn()
    c = conn.cursor()
    c.execute('SELECT user_id, username, total_trades, win_trades FROM users ORDER BY total_trades DESC LIMIT 10')
    r = c.fetchall()
    conn.close()
    text = "🎯 *Топ по сделкам:*\n\n"
    for i, (uid, uname, total, win) in enumerate(r, 1):
        m = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
        wr = (win / total * 100) if total > 0 else 0
        text += f"{m} @{uname or 'anon'} — {total} ({wr:.0f}%)\n"
    await cb.message.edit_text(text, reply_markup=top_kb())
    await cb.answer()

@dp.callback_query(F.data == "top_crashes")
async def top_crashes(cb: CallbackQuery):
    conn = db.get_conn()
    c = conn.cursor()
    c.execute('''
        SELECT u.user_id, u.username, COUNT(*) as wins
        FROM crash_bets cb JOIN users u ON cb.user_id = u.user_id
        WHERE cb.status = 'win'
        GROUP BY cb.user_id ORDER BY wins DESC LIMIT 10
    ''')
    r = c.fetchall()
    conn.close()
    text = "💀 *Топ по крашам:*\n\n"
    for i, (uid, uname, wins) in enumerate(r, 1):
        m = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
        text += f"{m} @{uname or 'anon'} — {wins} побед\n"
    await cb.message.edit_text(text, reply_markup=top_kb())
    await cb.answer()

# ==================== КРАШ-АРЕНА ====================
@dp.callback_query(F.data == "crash")
async def crash_cb(cb: CallbackQuery):
    await cb.message.edit_text(
        "💀 *Краш-арена*\n\n"
        "Ставь на рост или падение!\n"
        "📈 Рост x1.5\n"
        "📉 Падение x2.5\n"
        "🎰 Лотерея x4\n\n"
        "Выбери актив:",
        reply_markup=assets_kb("back_main")
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("cr_up_"))
async def cr_up(cb: CallbackQuery, state: FSMContext):
    asset = cb.data.replace("cr_up_", "")
    await state.update_data(cr_asset=asset, cr_type="up")
    await ask_crash(cb, state)

@dp.callback_query(F.data.startswith("cr_down_"))
async def cr_down(cb: CallbackQuery, state: FSMContext):
    asset = cb.data.replace("cr_down_", "")
    await state.update_data(cr_asset=asset, cr_type="down")
    await ask_crash(cb, state)

@dp.callback_query(F.data.startswith("cr_auto_"))
async def cr_auto(cb: CallbackQuery, state: FSMContext):
    asset = cb.data.replace("cr_auto_", "")
    await state.update_data(cr_asset=asset, cr_type="auto")
    await ask_crash(cb, state)

async def ask_crash(cb: CallbackQuery, state: FSMContext):
    user = db.get_user(cb.from_user.id)
    await cb.message.edit_text(
        f"💀 *Ставка*\n\nБаланс: {user['balance']:.2f}\n\nВведи сумму:",
        reply_markup=cancel_kb()
    )
    await state.set_state(CrashFSM.amount)
    await cb.answer()

@dp.message(CrashFSM.amount)
async def crash_amount(msg: types.Message, state: FSMContext):
    try:
        amount = Decimal(msg.text)
        if amount <= 0:
            await msg.answer("❌ > 0!", reply_markup=cancel_kb())
            return
        uid = msg.from_user.id
        user = db.get_user(uid)
        if amount > user['balance']:
            await msg.answer(f"❌ Недостаточно!", reply_markup=cancel_kb())
            return
        
        data = await state.get_data()
        asset = data['cr_asset']
        bet_type = data['cr_type']
        coef = {"up": Decimal('1.5'), "down": Decimal('2.5'), "auto": Decimal('4')}[bet_type]
        
        is_crash, crash_pct = check_crash(asset)
        
        if bet_type == "auto":
            win = random.random() < 0.5
        elif bet_type == "up":
            win = not is_crash
        else:
            win = is_crash
        
        if win:
            win_amt = amount * coef
            db.update_balance(uid, win_amt - amount)
            result = f"✅ *Победа!* +{win_amt:.2f} JET"
            status = "win"
        else:
            db.update_balance(uid, -amount)
            result = f"❌ *Поражение!* -{amount:.2f} JET"
            status = "lose"
        
        db.add_crash_bet(uid, asset, bet_type, amount, coef, status)
        
        await state.clear()
        await msg.answer(
            f"💀 *Результат*\n\n{asset} | {bet_type.upper()} x{coef}\n"
            f"{'💥 Краш!' if is_crash else '✅ Без краша'}\n\n"
            f"{result}\n\nБаланс: {db.get_user(uid)['balance']:.2f}",
            reply_markup=main_kb()
        )
    except:
        await msg.answer("❌ Введи число!", reply_markup=cancel_kb())

# ==================== ДЕЙЛИ ====================
@dp.callback_query(F.data == "daily")
async def daily_cb(cb: CallbackQuery):
    uid = cb.from_user.id
    last, streak = db.get_daily(uid)
    today = datetime.now().strftime('%Y-%m-%d')
    
    if last:
        last_date = datetime.strptime(last, '%Y-%m-%d')
        diff = (datetime.now() - last_date).days
        if diff > 1:
            streak = 0
        elif diff == 0:
            bonus = Config.DAILY_BONUSES[min(streak, len(Config.DAILY_BONUSES)-1)]
            await cb.message.edit_text(
                f"🎁 *Уже получено!*\nЗавтра: {bonus} JET",
                reply_markup=main_kb()
            )
            await cb.answer()
            return
    
    if streak >= len(Config.DAILY_BONUSES):
        streak = len(Config.DAILY_BONUSES) - 1
    
    bonus = Config.DAILY_BONUSES[streak]
    db.update_balance(uid, Decimal(str(bonus)))
    db.update_daily(uid, streak + 1)
    
    await cb.message.edit_text(
        f"🎁 *Дейли бонус!*\n\n+{bonus} JET\nДень {streak+1}/{len(Config.DAILY_BONUSES)}\n"
        f"Баланс: {db.get_user(uid)['balance']:.2f}",
        reply_markup=main_kb()
    )
    await cb.answer()

# ==================== РЕФЕРАЛЫ ====================
@dp.callback_query(F.data == "referral")
async def referral_cb(cb: CallbackQuery):
    uid = cb.from_user.id
    count = db.get_referral_count(uid)
    link = f"https://t.me/{bot.username}?start=ref_{uid}"
    text = (
        f"👥 *Рефералы*\n\n"
        f"🔗 `{link}`\n\n"
        f"👥 Приведено: {count}\n"
        f"🎁 Бонус: {Config.REFERRAL_BONUS:.0f} JET\n"
    )
    if count >= 5:
        text += "🔓 *Доступ к сигналам открыт!*"
    else:
        text += f"🔒 Осталось {5-count} друзей"
    await cb.message.edit_text(text, reply_markup=main_kb())
    await cb.answer()

# ==================== НОВОСТИ ====================
@dp.callback_query(F.data == "news")
async def news_cb(cb: CallbackQuery):
    news = [
        "🐳 Крупный кит купил PEPE на 5M JET!",
        "🚀 DOGE готов к листингу!",
        "🔥 SHIB бьёт рекорды волатильности!",
        "💀 Аналитики ждут крах PEPE!",
        "📈 Рынок растёт 3-й день подряд!",
        "🎉 PEPE достиг ATH!",
        "⚠️ Инвесторы фиксируют прибыль",
        "💪 DOGE ралли продолжается!",
        "🤖 Илон Маск твитнул про FLOKI!",
        "📊 Объём торгов вырос на 500%!"
    ]
    await cb.message.edit_text(
        f"📰 *Новости*\n\n{random.choice(news)}",
        reply_markup=main_kb()
    )
    await cb.answer()

# ==================== ПОМОЩЬ ====================
@dp.callback_query(F.data == "help")
async def help_cb(cb: CallbackQuery):
    text = (
        "📖 *Помощь*\n\n"
        "💰 *Торговля* — покупай/продавай активы\n"
        "⚡ *Плечо* x2/x5/x10 — умножает прибыль\n"
        "💀 *Краш* — актив может упасть на 30-90%\n"
        "🔒 *Стейкинг* — 10% за 8ч\n"
        "🌾 *Ферма* — пассивный доход\n"
        "🔄 *P2P* — торгуй с другими игроками\n"
        "🏅 *Турниры* — соревнуйся за призы\n"
        "🎁 *Дейли* — бонус каждый день\n"
        "👥 *Рефералы* — приводи друзей"
    )
    await cb.message.edit_text(text, reply_markup=main_kb())
    await cb.answer()

# ==================== ТУРНИРЫ ====================
@dp.callback_query(F.data == "tournaments")
async def tournaments_cb(cb: CallbackQuery):
    await cb.message.edit_text(
        "🏅 *Турниры*\n\n"
        "Соревнуйся с другими игроками!\n"
        "Побеждает тот, кто заработает больше всех за время турнира.",
        reply_markup=tournament_kb()
    )
    await cb.answer()

@dp.callback_query(F.data == "tournament_current")
async def tournament_current(cb: CallbackQuery):
    conn = db.get_conn()
    c = conn.cursor()
    now = int(datetime.now().timestamp())
    c.execute('SELECT * FROM tournaments WHERE status = "active" AND end_time > ? ORDER BY start_time DESC LIMIT 1', (now,))
    r = c.fetchone()
    conn.close()
    if r:
        text = f"🏅 *{r[1]}*\n\nПриз: {fmt(Decimal(str(r[2])))} JET\nУчастников: {r[6]}\n"
        remaining = r[4] - now
        h, m = remaining // 3600, (remaining % 3600) // 60
        text += f"⏳ Осталось: {h}ч {m}мин"
    else:
        text = "🏅 *Нет активных турниров*"
    await cb.message.edit_text(text, reply_markup=tournament_kb())
    await cb.answer()

@dp.callback_query(F.data == "tournament_rank")
async def tournament_rank(cb: CallbackQuery):
    conn = db.get_conn()
    c = conn.cursor()
    now = int(datetime.now().timestamp())
    c.execute('SELECT id FROM tournaments WHERE status = "active" AND end_time > ? ORDER BY start_time DESC LIMIT 1', (now,))
    r = c.fetchone()
    if r:
        ranking = db.get_tournament_ranking(r[0])
        text = "📊 *Рейтинг турнира:*\n\n"
        for i, (uid, uname, profit) in enumerate(ranking[:10], 1):
            m = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
            text += f"{m} @{uname or 'anon'} — +{fmt(profit)} JET\n"
    else:
        text = "📊 *Нет активных турниров*"
    conn.close()
    await cb.message.edit_text(text, reply_markup=tournament_kb())
    await cb.answer()

async def update_tournaments(uid: int, profit: Decimal):
    conn = db.get_conn()
    c = conn.cursor()
    now = int(datetime.now().timestamp())
    c.execute('SELECT id FROM tournaments WHERE status = "active" AND end_time > ?', (now,))
    ts = c.fetchall()
    for (tid,) in ts:
        db.update_tournament_profit(tid, uid, profit)
    conn.close()

# ==================== ФЕРМА ====================
@dp.callback_query(F.data == "farm")
async def farm_cb(cb: CallbackQuery):
    await show_farm(cb.from_user.id, cb.message)
    await cb.answer()

async def show_farm(uid: int, msg: types.Message):
    level, exp, last = db.get_farm(uid)
    exp_needed = level * 100 + 50
    income = Decimal('1') * (Decimal('1.1') ** level)
    
    # Пассивный доход
    now = int(datetime.now().timestamp())
    if last > 0:
        elapsed = (now - last) // 3600
        available = income * Decimal(elapsed) if elapsed > 0 else Decimal('0')
    else:
        available = Decimal('0')
    
    text = (
        f"🌾 *Ферма*\n\n"
        f"Уровень: {level}\n"
        f"Опыт: {exp:.0f}/{exp_needed}\n"
        f"Доход: {income:.2f} JET/час\n"
        f"Доступно к сбору: {available:.2f} JET"
    )
    await msg.edit_text(text, reply_markup=farm_kb())

@dp.callback_query(F.data == "farm_claim")
async def farm_claim(cb: CallbackQuery):
    uid = cb.from_user.id
    level, exp, last = db.get_farm(uid)
    income = Decimal('1') * (Decimal('1.1') ** level)
    now = int(datetime.now().timestamp())
    if last > 0:
        elapsed = (now - last) // 3600
        if elapsed > 0:
            amount = income * Decimal(elapsed)
            db.update_balance(uid, amount)
            db.update_farm(uid, level, exp, now)
            await cb.message.edit_text(
                f"🌾 *Урожай собран!*\n\n+{amount:.2f} JET",
                reply_markup=farm_kb()
            )
            await cb.answer()
            return
    await cb.answer("🌾 Ещё ничего не выросло!", show_alert=True)

@dp.callback_query(F.data == "farm_upgrade")
async def farm_upgrade(cb: CallbackQuery):
    uid = cb.from_user.id
    level, exp, last = db.get_farm(uid)
    exp_needed = level * 100 + 50
    if exp >= exp_needed:
        db.update_farm(uid, level + 1, Decimal('0'), last)
        await cb.message.edit_text(
            f"⬆️ *Ферма улучшена!*\n\nУровень {level} → {level+1}",
            reply_markup=farm_kb()
        )
        await cb.answer()
    else:
        await cb.answer(f"❌ Нужно {exp_needed - exp:.0f} опыта!", show_alert=True)

@dp.callback_query(F.data == "farm_info")
async def farm_info(cb: CallbackQuery):
    await show_farm(cb.from_user.id, cb.message)
    await cb.answer()

# ==================== P2P ====================
@dp.callback_query(F.data == "p2p")
async def p2p_cb(cb: CallbackQuery):
    await cb.message.edit_text(
        "🔄 *P2P-биржа*\n\n"
        "Торгуй напрямую с другими игроками!",
        reply_markup=p2p_kb()
    )
    await cb.answer()

@dp.callback_query(F.data == "p2p_all")
async def p2p_all(cb: CallbackQuery):
    offers = db.get_p2p_offers()
    text = "📊 *Все ордера:*\n\n"
    if offers:
        for o in offers[:10]:
            emoji = "📈" if o['type'] == 'buy' else "📉"
            text += f"{emoji} {o['asset']} {o['amount']:.2f} @ {o['price']:.2f} — @{db.get_user(o['user_id'])['username']}\n"
    else:
        text += "❌ Нет активных ордеров"
    await cb.message.edit_text(text, reply_markup=p2p_kb())
    await cb.answer()

# ==================== ДОСТИЖЕНИЯ ====================
async def check_achievements(uid: int, msg: types.Message):
    user = db.get_user(uid)
    portfolio = db.get_portfolio(uid)
    capital = db.get_total_capital(uid)
    has = db.get_achievements(uid)
    stats = db.get_trade_stats(uid)
    new = []
    
    if stats['total'] >= 1 and 1 not in has: new.append(1)
    if stats['total'] >= 10 and stats['win'] == 0 and 2 not in has: new.append(2)
    for asset, data in portfolio.items():
        if data['amount'] > 1000 and 3 not in has:
            new.append(3); break
    if capital > 1000000000 and 4 not in has: new.append(4)
    if all(data['amount'] > 0 for data in portfolio.values()) and 5 not in has: new.append(5)
    if user['stake_amount'] >= 10000 and 6 not in has: new.append(6)
    if db.get_rank(uid) <= 3 and 7 not in has: new.append(7)
    if stats['total'] >= 100 and 8 not in has: new.append(8)
    if user['vip_level'] >= 5 and 10 not in has: new.append(10)
    if user['farm_level'] >= 10 and 11 not in has: new.append(11)
    
    names = {
        1: "🏅 Первая сделка",
        2: "💀 Хомяк",
        3: "🐋 Кит",
        4: "👑 Миллиардер",
        5: "📊 Инвестор",
        6: "🔒 Стейкер",
        7: "🏆 Лидер",
        8: "🔥 Трейдер",
        10: "💎 Алмазный VIP",
        11: "🌾 Фермер"
    }
    
    for aid in new:
        db.add_achievement(uid, aid)
        await msg.answer(f"🎉 *Новое достижение!*\n\n{names.get(aid, '')}")

# ==================== ФОНОВЫЕ ПРОЦЕССЫ ====================
async def update_prices():
    while True:
        try:
            for asset in ASSETS:
                new_price, is_crash, crash_pct = calc_price(asset)
                if new_price > Config.PRICE_MAX:
                    new_price = Config.PRICE_MAX
                if new_price < Decimal('0.001'):
                    new_price = Decimal('0.001')
                
                db.update_price(asset, new_price)
                
                if is_crash:
                    logger.info(f"💥 CRASH {asset}: -{crash_pct*100:.1f}%")
                    users = db.get_all_users()
                    for uid in users:
                        try:
                            await bot.send_message(
                                uid,
                                f"💥 *КРАШ!*\n\n{ASSETS[asset]['emoji']} {asset}\n"
                                f"Падение: {crash_pct*100:.1f}%\n"
                                f"Новая цена: {new_price:.2f} JET",
                                reply_markup=main_kb()
                            )
                        except:
                            pass
                    await asyncio.sleep(3)
                
                await asyncio.sleep(0.5)
            await asyncio.sleep(Config.UPDATE_INTERVAL)
        except Exception as e:
            logger.error(f"Price update: {e}")
            await asyncio.sleep(60)

async def check_stakes():
    while True:
        try:
            conn = db.get_conn()
            c = conn.cursor()
            now = int(datetime.now().timestamp())
            c.execute('''
                SELECT user_id, stake_amount FROM users
                WHERE stake_amount > 0 AND stake_time + ? <= ?
            ''', (Config.STAKE_HOURS * 3600, now))
            r = c.fetchall()
            conn.close()
            for uid, amt in r:
                amt = Decimal(str(amt))
                bonus = amt * (Config.STAKE_PERCENT / 100)
                total = amt + bonus
                db.update_balance(uid, total)
                db.update_stake(uid, Decimal('0'), 0)
                await bot.send_message(
                    uid,
                    f"🔓 *Стейк разблокирован!*\n\n+{total:.2f} JET\nБонус: {bonus:.2f}",
                    reply_markup=main_kb()
                )
                logger.info(f"Stake unlocked: {uid}")
            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Stake check: {e}")
            await asyncio.sleep(60)

async def update_vip():
    while True:
        try:
            conn = db.get_conn()
            c = conn.cursor()
            c.execute('SELECT user_id, total_deposit FROM users')
            r = c.fetchall()
            conn.close()
            for uid, dep in r:
                dep = Decimal(str(dep))
                level = 0
                for lvl, info in Config.VIP_LEVELS.items():
                    if dep >= info['min_deposit']:
                        level = lvl
                db.update_vip(uid, level)
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"VIP update: {e}")
            await asyncio.sleep(3600)

async def farm_passive():
    while True:
        try:
            conn = db.get_conn()
            c = conn.cursor()
            now = int(datetime.now().timestamp())
            c.execute('SELECT user_id, farm_level, farm_exp, farm_last_claim FROM users WHERE farm_level > 0')
            r = c.fetchall()
            conn.close()
            for uid, level, exp, last in r:
                if last == 0:
                    continue
                elapsed = (now - last) // 3600
                if elapsed > 0:
                    income = Decimal('1') * (Decimal('1.1') ** level)
                    exp_gain = income * Decimal(elapsed) / Decimal('10')
                    new_exp = Decimal(str(exp)) + exp_gain
                    db.update_farm(uid, level, new_exp, now)
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"Farm passive: {e}")
            await asyncio.sleep(3600)

# ==================== ЗАПУСК ====================
async def main():
    asyncio.create_task(update_prices())
    asyncio.create_task(check_stakes())
    asyncio.create_task(update_vip())
    asyncio.create_task(farm_passive())
    
    logger.info("🚀 Bot started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
