"""
TELEGRAM БОТ ДЛЯ ЧАТА - БОССЫ И РЕЙДЫ
Версия 1.0
Как установить:
1. pip install aiogram sqlite3 apscheduler
2. Заменить TOKEN на свой токен от @BotFather
3. Запустить: python bot.py
4. Добавить бота в чат и дать права администратора (для отправки сообщений)
"""

import asyncio
import sqlite3
import random
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# ========== НАСТРОЙКИ ==========
TOKEN = "8972234129:AAGJp795dnJh8ez2_k1-YgqjQwJ99ENdgv8"  # ЗАМЕНИТЬ НА СВОЙ ТОКЕН!
ADMIN_IDS = [5356400377] # ID администраторов (можно узнать через /id)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self, db_name="boss_bot.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_tables()
    
    def init_tables(self):
        # Таблица игроков
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS players (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                level INTEGER DEFAULT 1,
                exp INTEGER DEFAULT 0,
                exp_to_next INTEGER DEFAULT 100,
                coins INTEGER DEFAULT 50,
                crystals INTEGER DEFAULT 0,
                attack INTEGER DEFAULT 10,
                defense INTEGER DEFAULT 5,
                max_hp INTEGER DEFAULT 100,
                current_hp INTEGER DEFAULT 100,
                total_damage INTEGER DEFAULT 0,
                boss_kills INTEGER DEFAULT 0,
                dungeon_completed INTEGER DEFAULT 0,
                last_attack_time DATETIME,
                last_heal_time DATETIME,
                join_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_banned BOOLEAN DEFAULT FALSE,
                warnings INTEGER DEFAULT 0
            )
        ''')
        
        # Таблица боссов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS bosses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                display_name TEXT,
                max_hp INTEGER,
                current_hp INTEGER,
                reward_coins INTEGER,
                reward_exp INTEGER,
                min_players INTEGER DEFAULT 1,
                phase INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT FALSE,
                spawn_time DATETIME,
                kill_time DATETIME,
                total_kills INTEGER DEFAULT 0,
                abilities TEXT,  -- JSON
                image_url TEXT
            )
        ''')
        
        # Участники битвы с боссом
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS boss_participants (
                boss_id INTEGER,
                user_id INTEGER,
                damage_dealt INTEGER DEFAULT 0,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_alive BOOLEAN DEFAULT TRUE,
                heal_used INTEGER DEFAULT 0,
                PRIMARY KEY (boss_id, user_id),
                FOREIGN KEY (boss_id) REFERENCES bosses(id),
                FOREIGN KEY (user_id) REFERENCES players(user_id)
            )
        ''')
        
        # Таблица предметов магазина
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT,
                category TEXT,  -- weapon, armor, potion, boost
                attack_bonus INTEGER DEFAULT 0,
                defense_bonus INTEGER DEFAULT 0,
                heal_amount INTEGER DEFAULT 0,
                price_coins INTEGER,
                price_crystals INTEGER DEFAULT 0,
                level_required INTEGER DEFAULT 1,
                emoji TEXT,
                is_available BOOLEAN DEFAULT TRUE
            )
        ''')
        
        # Инвентарь игрока
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_id INTEGER,
                quantity INTEGER DEFAULT 1,
                equipped BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (user_id) REFERENCES players(user_id),
                FOREIGN KEY (item_id) REFERENCES shop_items(id)
            )
        ''')
        
        # Данжи
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS dungeons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                difficulty INTEGER,
                level_required INTEGER DEFAULT 1,
                min_players INTEGER DEFAULT 1,
                max_players INTEGER DEFAULT 4,
                enemies TEXT,  -- JSON
                boss_name TEXT,
                reward_coins INTEGER,
                reward_exp INTEGER,
                cooldown_minutes INTEGER DEFAULT 60
            )
        ''')
        
        # Гильдии
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS guilds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                leader_id INTEGER,
                coins INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                total_damage INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (leader_id) REFERENCES players(user_id)
            )
        ''')
        
        # Члены гильдий
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS guild_members (
                guild_id INTEGER,
                user_id INTEGER,
                role TEXT DEFAULT 'member',  -- leader, officer, member
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id),
                FOREIGN KEY (guild_id) REFERENCES guilds(id),
                FOREIGN KEY (user_id) REFERENCES players(user_id)
            )
        ''')
        
        # Логи администраторов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                target_id INTEGER,
                details TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
        self.init_default_data()
    
    def init_default_data(self):
        # Создание стандартных боссов
        default_bosses = [
            {
                "name": "zombie_king",
                "display_name": "🧟 Король Зомби",
                "max_hp": 50000,
                "reward_coins": 100,
                "reward_exp": 50,
                "min_players": 3,
                "abilities": json.dumps({
                    "phase_1": {"hp_range": "70-100", "ability": "Обычные атаки"},
                    "phase_2": {"hp_range": "40-70", "ability": "Вызывает зомби - уменьшает урон игроков на 20%"},
                    "phase_3": {"hp_range": "10-40", "ability": "Регенерация 100 HP в минуту"},
                    "phase_4": {"hp_range": "0-10", "ability": "Ярость - удваивает урон"}
                })
            },
            {
                "name": "dragon",
                "display_name": "🐉 Огненный Дракон",
                "max_hp": 1000000,
                "reward_coins": 500,
                "reward_exp": 200,
                "min_players": 5,
                "abilities": json.dumps({
                    "phase_1": {"hp_range": "70-100", "ability": "Атакует всех игроков (-10 HP)"},
                    "phase_2": {"hp_range": "40-70", "ability": "Огненное дыхание - блокирует 3 игроков на 2 минуты"},
                    "phase_3": {"hp_range": "10-40", "ability": "Поджигает чат - спам сообщений"},
                    "phase_4": {"hp_range": "0-10", "ability": "Апокалипсис - x3 урон"}
                })
            },
            {
                "name": "demon_lord",
                "display_name": "👹 Повелитель Демонов",
                "max_hp": 200000,
                "reward_coins": 250,
                "reward_exp": 100,
                "min_players": 4,
                "abilities": json.dumps({
                    "phase_1": {"hp_range": "70-100", "ability": "Темная магия - 20% шанс промаха"},
                    "phase_2": {"hp_range": "40-70", "ability": "Призыв демонов - нужно убить 3 миньонов"},
                    "phase_3": {"hp_range": "10-40", "ability": "Исцеление - +5% HP раз в 3 минуты"},
                    "phase_4": {"hp_range": "0-10", "ability": "Безумие - атакует всех в 2 раза чаще"}
                })
            },
            {
                "name": "mecha_giant",
                "display_name": "🤖 Меха-Гигант",
                "max_hp": 2000000,
                "reward_coins": 2000,
                "reward_exp": 500,
                "min_players": 10,
                "abilities": json.dumps({
                    "phase_1": {"hp_range": "70-100", "ability": "Лазерный луч - -50 HP случайному игроку"},
                    "phase_2": {"hp_range": "40-70", "ability": "Ракетный удар - все теряют 20% текущего HP"},
                    "phase_3": {"hp_range": "10-40", "ability": "Энергетический щит - урон уменьшен на 50%"},
                    "phase_4": {"hp_range": "0-10", "ability": "Самоуничтожение - нужно нанести 50000 урона за 5 минут"}
                })
            }
        ]
        
        for boss in default_bosses:
            self.cursor.execute('''
                INSERT OR IGNORE INTO bosses 
                (name, display_name, max_hp, current_hp, reward_coins, reward_exp, min_players, abilities)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                boss["name"],
                boss["display_name"],
                boss["max_hp"],
                boss["max_hp"],
                boss["reward_coins"],
                boss["reward_exp"],
                boss["min_players"],
                boss["abilities"]
            ))
        
        # Создание стандартных предметов магазина
        default_items = [
            {"name": "Деревянный меч", "desc": "Обычное оружие новичка", "cat": "weapon", "atk": 5, "price": 50, "emoji": "🗡️"},
            {"name": "Стальной клинок", "desc": "Надежное оружие", "cat": "weapon", "atk": 15, "price": 300, "level": 5, "emoji": "⚔️"},
            {"name": "Огненный меч", "desc": "Горит в руках врага", "cat": "weapon", "atk": 35, "price": 1500, "level": 10, "emoji": "🔥"},
            {"name": "Легендарный клинок", "desc": "Оружие героев", "cat": "weapon", "atk": 75, "price": 10000, "level": 20, "emoji": "⚡"},
            {"name": "Кожаная броня", "desc": "Легкая защита", "cat": "armor", "def": 3, "price": 30, "emoji": "🛡️"},
            {"name": "Кольчуга", "desc": "Крепкая защита", "cat": "armor", "def": 10, "price": 200, "level": 5, "emoji": "🛡️"},
            {"name": "Стальная броня", "desc": "Тяжелая броня", "cat": "armor", "def": 25, "price": 1000, "level": 10, "emoji": "🛡️"},
            {"name": "Малое зелье HP", "desc": "Восстанавливает 30 HP", "cat": "potion", "heal": 30, "price": 40, "emoji": "🧪"},
            {"name": "Большое зелье HP", "desc": "Восстанавливает 80 HP", "cat": "potion", "heal": 80, "price": 150, "emoji": "🧪"},
            {"name": "Эликсир силы", "desc": "+50% урона на 10 минут", "cat": "boost", "atk": 50, "price": 200, "emoji": "💪"},
            {"name": "Щит защиты", "desc": "Уменьшает урон на 50% на 5 минут", "cat": "boost", "def": 50, "price": 250, "emoji": "🛡️"}
        ]
        
        for item in default_items:
            self.cursor.execute('''
                INSERT OR IGNORE INTO shop_items 
                (name, description, category, attack_bonus, defense_bonus, heal_amount, 
                 price_coins, level_required, emoji)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                item["name"],
                item["desc"],
                item["cat"],
                item.get("atk", 0),
                item.get("def", 0),
                item.get("heal", 0),
                item["price"],
                item.get("level", 1),
                item.get("emoji", "📦")
            ))
        
        self.conn.commit()
    
    # ===== МЕТОДЫ ДЛЯ ИГРОКОВ =====
    def get_player(self, user_id: int) -> Optional[tuple]:
        self.cursor.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone()
    
    def register_player(self, user_id: int, username: str = None, first_name: str = None):
        self.cursor.execute('''
            INSERT OR IGNORE INTO players (user_id, username, first_name)
            VALUES (?, ?, ?)
        ''', (user_id, username, first_name))
        self.conn.commit()
    
    def update_player_stats(self, user_id: int, field: str, value):
        self.cursor.execute(
            f"UPDATE players SET {field} = ? WHERE user_id = ?",
            (value, user_id)
        )
        self.conn.commit()
    
    def add_exp(self, user_id: int, amount: int):
        self.cursor.execute("SELECT level, exp, exp_to_next FROM players WHERE user_id = ?", (user_id,))
        level, exp, exp_to_next = self.cursor.fetchone()
        
        exp += amount
        level_up = False
        
        while exp >= exp_to_next:
            exp -= exp_to_next
            level += 1
            exp_to_next = level * 100
            level_up = True
        
        self.cursor.execute('''
            UPDATE players SET level = ?, exp = ?, exp_to_next = ?
            WHERE user_id = ?
        ''', (level, exp, exp_to_next, user_id))
        self.conn.commit()
        
        return level_up, level
    
    def add_coins(self, user_id: int, amount: int):
        self.cursor.execute(
            "UPDATE players SET coins = coins + ? WHERE user_id = ?",
            (amount, user_id)
        )
        self.conn.commit()
    
    # ===== МЕТОДЫ ДЛЯ БОССОВ =====
    def get_active_boss(self) -> Optional[dict]:
        self.cursor.execute('''
            SELECT * FROM bosses WHERE is_active = TRUE AND current_hp > 0
        ''')
        boss = self.cursor.fetchone()
        
        if boss:
            return {
                "id": boss[0],
                "name": boss[1],
                "display_name": boss[2],
                "max_hp": boss[3],
                "current_hp": boss[4],
                "reward_coins": boss[5],
                "reward_exp": boss[6],
                "min_players": boss[7],
                "phase": boss[8],
                "is_active": boss[9],
                "abilities": json.loads(boss[12]) if boss[12] else {},
                "image_url": boss[13]
            }
        return None
    
    def spawn_boss(self, boss_name: str) -> bool:
        # Проверяем, есть ли уже активный босс
        if self.get_active_boss():
            return False
        
        self.cursor.execute('''
            UPDATE bosses SET current_hp = max_hp, is_active = TRUE, 
            spawn_time = CURRENT_TIMESTAMP, phase = 0
            WHERE name = ?
        ''', (boss_name,))
        self.conn.commit()
        return True
    
    def get_boss_participants(self, boss_id: int) -> List[tuple]:
        self.cursor.execute('''
            SELECT user_id, damage_dealt FROM boss_participants 
            WHERE boss_id = ? AND is_alive = TRUE
            ORDER BY damage_dealt DESC
        ''', (boss_id,))
        return self.cursor.fetchall()
    
    def add_boss_participant(self, boss_id: int, user_id: int):
        self.cursor.execute('''
            INSERT OR IGNORE INTO boss_participants (boss_id, user_id)
            VALUES (?, ?)
        ''', (boss_id, user_id))
        self.conn.commit()
    
    def deal_damage_to_boss(self, boss_id: int, user_id: int, damage: int) -> Tuple[bool, int]:
        # Проверяем жив ли босс
        self.cursor.execute("SELECT current_hp FROM bosses WHERE id = ?", (boss_id,))
        current_hp = self.cursor.fetchone()[0]
        
        if current_hp <= 0:
            return False, 0
        
        # Наносим урон
        new_hp = max(0, current_hp - damage)
        self.cursor.execute(
            "UPDATE bosses SET current_hp = ? WHERE id = ?",
            (new_hp, boss_id)
        )
        
        # Обновляем урон игрока
        self.cursor.execute('''
            UPDATE boss_participants SET damage_dealt = damage_dealt + ?
            WHERE boss_id = ? AND user_id = ?
        ''', (damage, boss_id, user_id))
        
        self.conn.commit()
        
        # Проверяем убит ли босс
        if new_hp == 0:
            self.boss_killed(boss_id)
            return True, new_hp
        
        # Проверяем смену фазы
        self.check_boss_phase(boss_id)
        
        return False, new_hp
    
    def check_boss_phase(self, boss_id: int):
        self.cursor.execute("SELECT current_hp, max_hp FROM bosses WHERE id = ?", (boss_id,))
        current_hp, max_hp = self.cursor.fetchone()
        hp_percent = (current_hp / max_hp) * 100
        
        if hp_percent <= 10:
            phase = 4
        elif hp_percent <= 40:
            phase = 3
        elif hp_percent <= 70:
            phase = 2
        else:
            phase = 1
        
        self.cursor.execute(
            "UPDATE bosses SET phase = ? WHERE id = ?",
            (phase, boss_id)
        )
        self.conn.commit()
    
    def boss_killed(self, boss_id: int):
        # Получаем информацию о боссе
        self.cursor.execute("SELECT * FROM bosses WHERE id = ?", (boss_id,))
        boss = self.cursor.fetchone()
        
        # Получаем участников
        participants = self.get_boss_participants(boss_id)
        
        # Обновляем босса
        self.cursor.execute('''
            UPDATE bosses SET is_active = FALSE, kill_time = CURRENT_TIMESTAMP,
            total_kills = total_kills + 1
            WHERE id = ?
        ''', (boss_id,))
        
        # Выдаем награды участникам
        total_damage = sum(p[1] for p in participants)
        
        for user_id, damage in participants:
            # Расчет награды пропорционально урону
            share = damage / total_damage if total_damage > 0 else 0
            coins_reward = int(boss[5] * share)
            exp_reward = int(boss[6] * share)
            
            # Бонус за участие
            if damage > 0:
                coins_reward += 10
                exp_reward += 5
            
            # Минимальная награда
            coins_reward = max(coins_reward, 10)
            exp_reward = max(exp_reward, 5)
            
            self.add_coins(user_id, coins_reward)
            self.add_exp(user_id, exp_reward)
            
            # Обновляем статистику
            self.cursor.execute('''
                UPDATE players SET boss_kills = boss_kills + 1,
                total_damage = total_damage + ?
                WHERE user_id = ?
            ''', (damage, user_id))
        
        self.conn.commit()
        
        # Возвращаем информацию для отправки сообщения
        return {
            "boss_name": boss[2],
            "participants": participants,
            "total_damage": total_damage,
            "top_damage": participants[0] if participants else None
        }
    
    # ===== МЕТОДЫ ДЛЯ МАГАЗИНА =====
    def get_shop_items(self, category: str = None) -> List[tuple]:
        if category:
            self.cursor.execute(
                "SELECT * FROM shop_items WHERE category = ? AND is_available = TRUE",
                (category,)
            )
        else:
            self.cursor.execute(
                "SELECT * FROM shop_items WHERE is_available = TRUE"
            )
        return self.cursor.fetchall()
    
    def buy_item(self, user_id: int, item_id: int) -> Tuple[bool, str]:
        # Проверяем наличие предмета
        self.cursor.execute("SELECT * FROM shop_items WHERE id = ?", (item_id,))
        item = self.cursor.fetchone()
        
        if not item:
            return False, "Предмет не найден!"
        
        # Проверяем уровень
        player = self.get_player(user_id)
        if player[2] < item[8]:  # level < level_required
            return False, f"Требуется уровень {item[8]}!"
        
        # Проверяем баланс
        if player[3] < item[7]:  # coins < price_coins
            return False, f"Недостаточно монет! Нужно: {item[7]}"
        
        # Списываем монеты
        self.add_coins(user_id, -item[7])
        
        # Добавляем в инвентарь
        self.cursor.execute('''
            INSERT INTO inventory (user_id, item_id, quantity)
            VALUES (?, ?, 1)
            ON CONFLICT DO UPDATE SET quantity = quantity + 1
        ''', (user_id, item_id))
        self.conn.commit()
        
        return True, f"Куплено: {item[1]}!"
    
    def get_inventory(self, user_id: int) -> List[tuple]:
        self.cursor.execute('''
            SELECT i.*, s.name, s.category, s.attack_bonus, s.defense_bonus, s.emoji
            FROM inventory i
            JOIN shop_items s ON i.item_id = s.id
            WHERE i.user_id = ?
        ''', (user_id,))
        return self.cursor.fetchall()
    
    def get_equipped_items(self, user_id: int) -> dict:
        self.cursor.execute('''
            SELECT s.category, s.attack_bonus, s.defense_bonus, s.name
            FROM inventory i
            JOIN shop_items s ON i.item_id = s.id
            WHERE i.user_id = ? AND i.equipped = TRUE
        ''', (user_id,))
        
        items = self.cursor.fetchall()
        result = {"weapon": None, "armor": None}
        
        for item in items:
            if item[0] == "weapon":
                result["weapon"] = {"name": item[3], "attack": item[1]}
            elif item[0] == "armor":
                result["armor"] = {"name": item[3], "defense": item[2]}
        
        return result
    
    def equip_item(self, user_id: int, item_id: int) -> Tuple[bool, str]:
        # Проверяем наличие в инвентаре
        self.cursor.execute(
            "SELECT * FROM inventory WHERE user_id = ? AND item_id = ? AND quantity > 0",
            (user_id, item_id)
        )
        if not self.cursor.fetchone():
            return False, "Предмет не найден в инвентаре!"
        
        # Получаем категорию предмета
        self.cursor.execute("SELECT category FROM shop_items WHERE id = ?", (item_id,))
        category = self.cursor.fetchone()[0]
        
        # Снимаем экипировку с других предметов той же категории
        self.cursor.execute('''
            UPDATE inventory SET equipped = FALSE
            WHERE user_id = ? AND item_id IN (
                SELECT id FROM shop_items WHERE category = ?
            )
        ''', (user_id, category))
        
        # Экипируем выбранный предмет
        self.cursor.execute('''
            UPDATE inventory SET equipped = TRUE
            WHERE user_id = ? AND item_id = ?
        ''', (user_id, item_id))
        self.conn.commit()
        
        return True, "Предмет экипирован!"
    
    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====
    def get_all_chat_ids(self) -> List[int]:
        # Получаем все чаты, где есть бот
        self.cursor.execute("SELECT DISTINCT chat_id FROM chat_settings")
        return [row[0] for row in self.cursor.fetchall()]
    
    def add_chat(self, chat_id: int, chat_title: str = None):
        self.cursor.execute('''
            INSERT OR IGNORE INTO chat_settings (chat_id, chat_title)
            VALUES (?, ?)
        ''', (chat_id, chat_title))
        self.conn.commit()

# ========== СОЗДАНИЕ БД ==========
db = Database()

# ========== СОСТОЯНИЯ FSM ==========
class ShopStates(StatesGroup):
    browsing = State()
    buying = State()

class BossStates(StatesGroup):
    spawning = State()
    managing = State()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_player_info(player: tuple) -> str:
    """Форматирует информацию об игроке"""
    equipment = db.get_equipped_items(player[0])
    weapon = equipment.get("weapon", {}).get("name", "Нет")
    armor = equipment.get("armor", {}).get("name", "Нет")
    
    # Бонусы от экипировки
    atk_bonus = equipment.get("weapon", {}).get("attack", 0)
    def_bonus = equipment.get("armor", {}).get("defense", 0)
    
    total_attack = player[6] + atk_bonus
    total_defense = player[7] + def_bonus
    
    return (
        f"👤 @{player[1] or 'Игрок'}\n"
        f"🏆 Уровень: {player[2]}\n"
        f"⚔️ Атака: {total_attack} (+{atk_bonus})\n"
        f"🛡️ Защита: {total_defense} (+{def_bonus})\n"
        f"❤️ HP: {player[9]}/{player[8]}\n"
        f"💰 Монеты: {player[3]}\n"
        f"💎 Кристаллы: {player[4]}\n"
        f"📊 Опыт: {player[1]}/{player[10]}\n"
        f"🗡️ Оружие: {weapon}\n"
        f"🛡️ Броня: {armor}\n"
        f"💀 Убито боссов: {player[12]}\n"
    )

def create_boss_status(boss: dict) -> str:
    """Создает статусную строку босса"""
    if not boss:
        return "❌ Нет активных боссов!"
    
    hp_percent = (boss["current_hp"] / boss["max_hp"]) * 100
    bar_length = 20
    filled = int((hp_percent / 100) * bar_length)
    bar = "█" * filled + "░" * (bar_length - filled)
    
    # Определяем эмоцию для фазы
    phase_emoji = {
        1: "😴",
        2: "😤",
        3: "😡",
        4: "💀"
    }.get(boss["phase"], "😐")
    
    # Получаем участников
    participants = db.get_boss_participants(boss["id"])
    
    text = (
        f"{boss['display_name']}\n"
        f"HP: {boss['current_hp']:,}/{boss['max_hp']:,}\n"
        f"[{bar}] {hp_percent:.1f}%\n"
        f"Фаза: {boss['phase']}/4 {phase_emoji}\n"
        f"👥 Участников: {len(participants)}\n"
        f"💰 Награда: {boss['reward_coins']} монет\n"
    )
    
    # Добавляем информацию о фазе
    if boss.get("abilities"):
        phase_key = f"phase_{boss['phase']}"
        if phase_key in boss["abilities"]:
            text += f"\n⚡ {boss['abilities'][phase_key]['ability']}"
    
    return text

def create_shop_keyboard(items: List[tuple]) -> InlineKeyboardMarkup:
    """Создает клавиатуру магазина"""
    keyboard = []
    
    # Группируем по категориям
    categories = {}
    for item in items:
        cat = item[3]  # category
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(item)
    
    for cat, cat_items in categories.items():
        keyboard.append([InlineKeyboardButton(
            text=f"📁 {cat.upper()} ({len(cat_items)})",
            callback_data=f"shop_cat_{cat}"
        )])
        
        for item in cat_items[:3]:  # Показываем первые 3
            emoji = item[9] or "📦"
            keyboard.append([InlineKeyboardButton(
                text=f"{emoji} {item[1]} - {item[7]}💰",
                callback_data=f"shop_buy_{item[0]}"
            )])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ========== ОБРАБОТЧИКИ КОМАНД ==========

# Общая команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    db.register_player(user.id, user.username, user.first_name)
    
    # Добавляем чат в БД
    if message.chat.type in ["group", "supergroup"]:
        db.add_chat(message.chat.id, message.chat.title)
    
    welcome_text = (
        "🎮 **Добро пожаловать в Boss Raid RPG!**\n\n"
        "Здесь ты можешь сражаться с эпическими боссами вместе с друзьями!\n\n"
        "📋 **Основные команды:**\n"
        "/profile - твой профиль\n"
        "/boss - статус текущего босса\n"
        "/attack - атаковать босса\n"
        "/heal - восстановить HP\n"
        "/shop - магазин\n"
        "/inventory - инвентарь\n"
        "/top - топ игроков\n"
        "/help - помощь\n\n"
        "⚔️ Сражайся, прокачивайся и становись легендой!"
    )
    
    await message.answer(welcome_text, parse_mode="Markdown")

# Команда /help
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = (
        "📖 **Справка по командам**\n\n"
        "**Игровые команды:**\n"
        "/profile - показать профиль\n"
        "/boss - статус босса\n"
        "/attack - атаковать босса\n"
        "/heal - восстановить HP (кулдаун 5 мин)\n"
        "/shop - открыть магазин\n"
        "/inventory - инвентарь\n"
        "/equip [id] - экипировать предмет\n"
        "/top - топ игроков\n"
        "/stats - статистика чата\n\n"
        "**Для групп:**\n"
        "/join - присоединиться к битве с боссом\n"
        "/leave - покинуть битву\n\n"
        "**Данжи (в разработке):**\n"
        "/dungeon - войти в данж\n\n"
        "**Админ-команды:**\n"
        "/admin - админ-панель"
    )
    await message.answer(help_text, parse_mode="Markdown")

# Команда /id - узнать свой ID
@dp.message(Command("id"))
async def cmd_id(message: types.Message):
    await message.answer(f"🆔 Твой ID: `{message.from_user.id}`", parse_mode="Markdown")

# ========== ОСНОВНЫЕ ИГРОВЫЕ КОМАНДЫ ==========

# Команда /profile
@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    user_id = message.from_user.id
    player = db.get_player(user_id)
    
    if not player:
        await message.answer("❌ Ты не зарегистрирован! Напиши /start")
        return
    
    await message.answer(
        get_player_info(player),
        parse_mode="Markdown"
    )

# Команда /boss
@dp.message(Command("boss"))
async def cmd_boss(message: types.Message):
    boss = db.get_active_boss()
    
    if not boss:
        await message.answer("❌ Нет активных боссов! Ожидайте появления.")
        return
    
    # Получаем участников
    participants = db.get_boss_participants(boss["id"])
    
    # Проверяем, участвует ли игрок
    user_id = message.from_user.id
    is_participant = any(p[0] == user_id for p in participants)
    
    # Создаем клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚔️ Атаковать!" if is_participant else "👋 Присоединиться",
            callback_data="boss_attack" if is_participant else "boss_join"
        )],
        [InlineKeyboardButton(text="📊 Топ дамагеров", callback_data="boss_top")]
    ])
    
    await message.answer(
        create_boss_status(boss),
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# Команда /attack
@dp.message(Command("attack"))
async def cmd_attack(message: types.Message):
    user_id = message.from_user.id
    player = db.get_player(user_id)
    
    if not player:
        await message.answer("❌ Зарегистрируйся через /start")
        return
    
    # Проверяем активного босса
    boss = db.get_active_boss()
    if not boss:
        await message.answer("❌ Нет активных боссов!")
        return
    
    # Проверяем участие
    db.cursor.execute(
        "SELECT * FROM boss_participants WHERE boss_id = ? AND user_id = ?",
        (boss["id"], user_id)
    )
    if not db.cursor.fetchone():
        await message.answer("❌ Ты не участвуешь в битве! Напиши /join")
        return
    
    # Проверяем кулдаун (30 секунд)
    if player[13]:
        last_attack = datetime.fromisoformat(player[13])
        cooldown = 30  # секунд
        if (datetime.now() - last_attack).seconds < cooldown:
            remaining = cooldown - (datetime.now() - last_attack).seconds
            await message.answer(
                f"⏳ Подожди {remaining} секунд перед следующей атакой!"
            )
            return
    
    # Проверяем HP
    if player[9] <= 0:
        await message.answer("💀 Ты мертв! Используй /heal чтобы воскреснуть (кулдаун 10 мин)")
        return
    
    # Расчет урона
    equipment = db.get_equipped_items(user_id)
    weapon_bonus = equipment.get("weapon", {}).get("attack", 0)
    total_attack = player[6] + weapon_bonus
    
    # Случайный разброс урона
    damage = random.randint(int(total_attack * 0.7), int(total_attack * 1.3))
    
    # Шанс критического удара (10%)
    is_critical = random.random() < 0.1
    if is_critical:
        damage = int(damage * 2)
        crit_text = "💥 **КРИТИЧЕСКИЙ УДАР!**"
    else:
        crit_text = ""
    
    # Наносим урон
    killed, new_hp = db.deal_damage_to_boss(boss["id"], user_id, damage)
    
    # Обновляем время атаки
    db.update_player_stats(user_id, "last_attack_time", datetime.now().isoformat())
    
    # Ответное действие босса (наносит урон игроку)
    boss_damage = random.randint(5, 15)
    if random.random() < 0.3:  # 30% шанс что босс атакует
        new_hp = max(0, player[9] - boss_damage)
        db.update_player_stats(user_id, "current_hp", new_hp)
        
        # Проверяем смерть игрока
        if new_hp == 0:
            db.cursor.execute("SELECT username FROM players WHERE user_id = ?", (user_id,))
            username = db.cursor.fetchone()[0] or "Игрок"
            
            # Отправляем сообщение в чат
            await message.reply(
                f"💀 {username} пал в бою! Босс нанес {boss_damage} урона.\n"
                f"Используй /heal чтобы вернуться в строй!"
            )
        
        boss_attack_text = f"\n💢 Босс атакует тебя! -{boss_damage} HP"
    else:
        boss_attack_text = ""
    
    # Формируем ответ
    response = (
        f"⚔️ **Ты атакуешь босса!**\n"
        f"{crit_text}\n"
        f"Нанесено урона: **{damage}**\n"
        f"Осталось HP босса: **{new_hp:,}**\n"
        f"{boss_attack_text}"
    )
    
    await message.answer(response, parse_mode="Markdown")
    
    # Если босс убит - отправляем сообщение в чат
    if killed:
        result = db.boss_killed(boss["id"])
        
        # Формируем сообщение о победе
        top_player = result["participants"][0] if result["participants"] else None
        top_text = ""
        if top_player:
            db.cursor.execute("SELECT username FROM players WHERE user_id = ?", (top_player[0],))
            username = db.cursor.fetchone()[0] or "Игрок"
            top_text = f"🏆 Топ дамагер: @{username} - {top_player[1]:,} урона!"
        
        await message.answer(
            f"🎉 **БОСС ПОВЕРЖЕН!** 🎉\n\n"
            f"{boss['display_name']} уничтожен!\n"
            f"Всего участников: {len(result['participants'])}\n"
            f"Общий урон: {result['total_damage']:,}\n"
            f"{top_text}\n\n"
            f"💰 Все участники получили награды!"
        )

# Команда /heal - восстановление HP
@dp.message(Command("heal"))
async def cmd_heal(message: types.Message):
    user_id = message.from_user.id
    player = db.get_player(user_id)
    
    if not player:
        await message.answer("❌ Зарегистрируйся через /start")
        return
    
    # Проверяем кулдаун (5 минут)
    if player[14]:
        last_heal = datetime.fromisoformat(player[14])
        cooldown = 300  # 5 минут
        if (datetime.now() - last_heal).seconds < cooldown:
            remaining = cooldown - (datetime.now() - last_heal).seconds
            minutes = remaining // 60
            seconds = remaining % 60
            await message.answer(
                f"⏳ Восстановление доступно через {minutes}м {seconds}с"
            )
            return
    
    # Восстанавливаем HP
    heal_amount = random.randint(20, 50)
    new_hp = min(player[8], player[9] + heal_amount)
    db.update_player_stats(user_id, "current_hp", new_hp)
    db.update_player_stats(user_id, "last_heal_time", datetime.now().isoformat())
    
    await message.answer(
        f"❤️ Ты восстановил {heal_amount} HP!\n"
        f"Текущее HP: {new_hp}/{player[8]}"
    )

# Команда /join - присоединиться к битве
@dp.message(Command("join"))
async def cmd_join(message: types.Message):
    user_id = message.from_user.id
    player = db.get_player(user_id)
    
    if not player:
        await message.answer("❌ Зарегистрируйся через /start")
        return
    
    boss = db.get_active_boss()
    if not boss:
        await message.answer("❌ Нет активных боссов!")
        return
    
    # Проверяем, не участвует ли уже
    db.cursor.execute(
        "SELECT * FROM boss_participants WHERE boss_id = ? AND user_id = ?",
        (boss["id"], user_id)
    )
    if db.cursor.fetchone():
        await message.answer("👋 Ты уже участвуешь в битве!")
        return
    
    # Проверяем минимальное количество участников
    participants = db.get_boss_participants(boss["id"])
    if len(participants) >= 10:  # Максимум 10 участников
        await message.answer("❌ Слишком много участников! Максимум 10.")
        return
    
    # Добавляем участника
    db.add_boss_participant(boss["id"], user_id)
    
    await message.answer(
        f"👋 @{message.from_user.username or 'Игрок'} присоединился к битве!\n"
        f"Всего участников: {len(participants) + 1}"
    )

# Команда /leave - покинуть битву
@dp.message(Command("leave"))
async def cmd_leave(message: types.Message):
    user_id = message.from_user.id
    boss = db.get_active_boss()
    
    if not boss:
        await message.answer("❌ Нет активных боссов!")
        return
    
    db.cursor.execute(
        "DELETE FROM boss_participants WHERE boss_id = ? AND user_id = ?",
        (boss["id"], user_id)
    )
    db.conn.commit()
    
    await message.answer("👋 Ты покинул битву!")

# Команда /top
@dp.message(Command("top"))
async def cmd_top(message: types.Message):
    db.cursor.execute('''
        SELECT user_id, username, level, total_damage, boss_kills, coins
        FROM players
        ORDER BY level DESC, total_damage DESC
        LIMIT 10
    ''')
    top_players = db.cursor.fetchall()
    
    if not top_players:
        await message.answer("📊 Нет данных")
        return
    
    text = "🏆 **ТОП ИГРОКОВ**\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, player in enumerate(top_players):
        medal = medals[i] if i < 3 else f"{i+1}."
        username = f"@{player[1]}" if player[1] else f"Игрок {player[0]}"
        text += (
            f"{medal} {username}\n"
            f"   Уровень: {player[2]} | Урон: {player[3]:,} | Боссов: {player[4]} | Монет: {player[5]}\n\n"
        )
    
    await message.answer(text, parse_mode="Markdown")

# ========== МАГАЗИН ==========

# Команда /shop
@dp.message(Command("shop"))
async def cmd_shop(message: types.Message):
    items = db.get_shop_items()
    
    if not items:
        await message.answer("🛒 Магазин пуст!")
        return
    
    keyboard = create_shop_keyboard(items)
    
    await message.answer(
        "🛒 **Магазин**\n\n"
        "Выбери категорию или предмет для покупки:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# Команда /inventory
@dp.message(Command("inventory"))
async def cmd_inventory(message: types.Message):
    user_id = message.from_user.id
    inventory = db.get_inventory(user_id)
    
    if not inventory:
        await message.answer("📦 У тебя пустой инвентарь!")
        return
    
    text = "📦 **Твой инвентарь**\n\n"
    for item in inventory:
        name = item[6]  # shop_items.name
        emoji = item[10] or "📦"
        category = item[7]
        quantity = item[3]
        equipped = "✅" if item[4] else "❌"
        
        # Показываем бонусы
        bonuses = []
        if item[8] > 0:  # attack_bonus
            bonuses.append(f"⚔️+{item[8]}")
        if item[9] > 0:  # defense_bonus
            bonuses.append(f"🛡️+{item[9]}")
        bonus_text = " | ".join(bonuses) if bonuses else "Нет бонусов"
        
        text += f"{emoji} **{name}** (x{quantity}) {equipped}\n"
        text += f"   {category} | {bonus_text}\n\n"
    
    await message.answer(text, parse_mode="Markdown")

# Команда /equip
@dp.message(Command("equip"))
async def cmd_equip(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "⚠️ Укажи ID предмета\n"
            "Пример: `/equip 1`",
            parse_mode="Markdown"
        )
        return
    
    try:
        item_id = int(args[1])
    except ValueError:
        await message.answer("❌ Некорректный ID!")
        return
    
    user_id = message.from_user.id
    success, msg = db.equip_item(user_id, item_id)
    
    await message.answer(msg)

# Обработка callback-запросов магазина
@dp.callback_query(lambda c: c.data.startswith("shop_"))
async def process_shop_callback(callback: types.CallbackQuery):
    data = callback.data.split("_")
    action = data[1]
    
    if action == "cat":
        category = data[2]
        items = db.get_shop_items(category)
        
        if not items:
            await callback.answer("В этой категории нет товаров", show_alert=True)
            return
        
        text = f"📁 **{category.upper()}**\n\n"
        for item in items:
            emoji = item[9] or "📦"
            text += f"{emoji} **{item[1]}** - {item[7]}💰\n"
            text += f"   {item[2]}\n"
            if item[8] > 0:  # level_required
                text += f"   🔒 Требуется уровень: {item[8]}\n"
            text += "\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="shop_back")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    
    elif action == "buy":
        item_id = int(data[2])
        user_id = callback.from_user.id
        
        success, msg = db.buy_item(user_id, item_id)
        await callback.answer(msg, show_alert=not success)
        
        if success:
            await callback.message.edit_text(
                f"✅ {msg}\n\n"
                f"Используй /inventory чтобы посмотреть инвентарь",
                parse_mode="Markdown"
            )
    
    elif action == "back":
        items = db.get_shop_items()
        keyboard = create_shop_keyboard(items)
        
        await callback.message.edit_text(
            "🛒 **Магазин**\n\nВыбери категорию или предмет для покупки:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    await callback.answer()

# ========== BOSS КОМАНДЫ (админские) ==========

@dp.message(Command("spawn_boss"))
async def cmd_spawn_boss(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Только для администраторов!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "⚠️ Укажи имя босса\n"
            "Доступные: zombie_king, dragon, demon_lord, mecha_giant"
        )
        return
    
    boss_name = args[1]
    
    # Проверяем, существует ли босс
    db.cursor.execute("SELECT name FROM bosses WHERE name = ?", (boss_name,))
    if not db.cursor.fetchone():
        await message.answer(f"❌ Босс '{boss_name}' не найден!")
        return
    
    if db.spawn_boss(boss_name):
        # Получаем информацию о боссе
        boss = db.get_active_boss()
        await message.answer(
            f"✅ Босс {boss['display_name']} появился!\n"
            f"HP: {boss['max_hp']:,}\n"
            f"Награда: {boss['reward_coins']} монет\n"
            f"Присоединяйся: /join"
        )
    else:
        await message.answer("❌ Босс уже активен! Напиши /boss")

@dp.message(Command("kill_boss"))
async def cmd_kill_boss(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Только для администраторов!")
        return
    
    boss = db.get_active_boss()
    if not boss:
        await message.answer("❌ Нет активных боссов!")
        return
    
    # Убиваем босса
    db.cursor.execute(
        "UPDATE bosses SET current_hp = 0, is_active = FALSE WHERE id = ?",
        (boss["id"],)
    )
    db.conn.commit()
    
    result = db.boss_killed(boss["id"])
    
    await message.answer(
        f"💀 Босс {boss['display_name']} был принудительно убит!"
    )

@dp.message(Command("boss_list"))
async def cmd_boss_list(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Только для администраторов!")
        return
    
    db.cursor.execute("SELECT name, display_name, max_hp, is_active FROM bosses")
    bosses = db.cursor.fetchall()
    
    text = "📋 **Список боссов**\n\n"
    for boss in bosses:
        status = "🟢 Активен" if boss[3] else "🔴 Неактивен"
        text += f"• {boss[1]}\n"
        text += f"  ID: {boss[0]} | HP: {boss[2]:,} | {status}\n\n"
    
    await message.answer(text, parse_mode="Markdown")

# ========== ОБРАБОТКА INLINE КНОПОК ДЛЯ БОССОВ ==========

@dp.callback_query(lambda c: c.data.startswith("boss_"))
async def process_boss_callback(callback: types.CallbackQuery):
    action = callback.data.split("_")[1]
    
    if action == "join":
        user_id = callback.from_user.id
        player = db.get_player(user_id)
        
        if not player:
            await callback.answer("❌ Зарегистрируйся через /start", show_alert=True)
            return
        
        boss = db.get_active_boss()
        if not boss:
            await callback.answer("❌ Нет активных боссов!", show_alert=True)
            return
        
        # Проверяем, не участвует ли уже
        db.cursor.execute(
            "SELECT * FROM boss_participants WHERE boss_id = ? AND user_id = ?",
            (boss["id"], user_id)
        )
        if db.cursor.fetchone():
            await callback.answer("👋 Ты уже участвуешь!", show_alert=True)
            return
        
        db.add_boss_participant(boss["id"], user_id)
        await callback.answer("✅ Ты присоединился к битве!", show_alert=True)
        
        # Обновляем сообщение
        participants = db.get_boss_participants(boss["id"])
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Атаковать!", callback_data="boss_attack")],
            [InlineKeyboardButton(text="📊 Топ дамагеров", callback_data="boss_top")]
        ])
        
        await callback.message.edit_text(
            create_boss_status(boss),
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    elif action == "attack":
        # Эмулируем команду /attack
        await callback.answer("⚔️ Используй команду /attack в чате!", show_alert=True)
    
    elif action == "top":
        boss = db.get_active_boss()
        if not boss:
            await callback.answer("❌ Нет активных боссов!", show_alert=True)
            return
        
        participants = db.get_boss_participants(boss["id"])
        
        if not participants:
            await callback.answer("📊 Пока нет участников!", show_alert=True)
            return
        
        text = "📊 **Топ дамагеров**\n\n"
        medals = ["🥇", "🥈", "🥉"]
        
        for i, (user_id, damage) in enumerate(participants[:10]):
            db.cursor.execute(
                "SELECT username FROM players WHERE user_id = ?",
                (user_id,)
            )
            username = db.cursor.fetchone()[0] or f"Игрок {user_id}"
            medal = medals[i] if i < 3 else f"{i+1}."
            text += f"{medal} @{username} - {damage:,} урона\n"
        
        await callback.message.answer(text, parse_mode="Markdown")
        await callback.answer()

# ========== ОБРАБОТЧИК ВСТУПЛЕНИЯ В ГРУППУ ==========

@dp.message(lambda m: m.new_chat_members is not None)
async def on_new_chat_member(message: types.Message):
    for member in message.new_chat_members:
        if member.id == bot.id:
            # Бот добавлен в группу
            chat_id = message.chat.id
            chat_title = message.chat.title
            
            db.add_chat(chat_id, chat_title)
            
            await message.answer(
                f"👋 Привет! Я Boss Raid Bot!\n\n"
                f"📌 Чат: {chat_title}\n"
                f"🎮 Используй /start чтобы начать игру\n"
                f"👑 Администраторы могут использовать /spawn_boss [имя]"
            )

# ========== ФОНОВЫЕ ЗАДАЧИ ==========

async def check_boss_regeneration():
    """Проверяет и восстанавливает HP босса"""
    boss = db.get_active_boss()
    if not boss:
        return
    
    # Восстанавливаем 0.5% HP каждые 5 минут
    regen_amount = int(boss["max_hp"] * 0.005)
    new_hp = min(boss["max_hp"], boss["current_hp"] + regen_amount)
    
    db.cursor.execute(
        "UPDATE bosses SET current_hp = ? WHERE id = ?",
        (new_hp, boss["id"])
    )
    db.conn.commit()
    
    # Если босс восстановился до 100% - уведомляем
    if new_hp == boss["max_hp"]:
        # Отправляем уведомление во все чаты
        for chat_id in db.get_all_chat_ids():
            try:
                await bot.send_message(
                    chat_id,
                    f"🔄 {boss['display_name']} полностью восстановил здоровье!"
                )
            except:
                pass

async def schedule_boss_spawn():
    """Автоматический спавн боссов по расписанию"""
    # Получаем список боссов
    db.cursor.execute("SELECT name, display_name FROM bosses")
    bosses = db.cursor.fetchall()
    
    for boss_name, display_name in bosses:
        # Проверяем, не активен ли уже босс
        if db.get_active_boss():
            continue
        
        # Спавним босса
        db.spawn_boss(boss_name)
        
        # Отправляем уведомление
        for chat_id in db.get_all_chat_ids():
            try:
                boss = db.get_active_boss()
                await bot.send_message(
                    chat_id,
                    f"⚔️ **{display_name} появился!**\n\n"
                    f"HP: {boss['max_hp']:,}\n"
                    f"💰 Награда: {boss['reward_coins']} монет\n"
                    f"Присоединяйся: /join",
                    parse_mode="Markdown"
                )
            except:
                pass
        
        # Спавним только одного босса
        break

async def boss_timeout():
    """Если босс не убит за 12 часов - исчезает"""
    boss = db.get_active_boss()
    if not boss:
        return
    
    # Проверяем время спавна
    db.cursor.execute(
        "SELECT spawn_time FROM bosses WHERE id = ?",
        (boss["id"],)
    )
    spawn_time = datetime.fromisoformat(db.cursor.fetchone()[0])
    
    if (datetime.now() - spawn_time).seconds > 43200:  # 12 часов
        # Босс исчезает
        db.cursor.execute(
            "UPDATE bosses SET is_active = FALSE WHERE id = ?",
            (boss["id"],)
        )
        db.conn.commit()
        
        for chat_id in db.get_all_chat_ids():
            try:
                await bot.send_message(
                    chat_id,
                    f"💨 {boss['display_name']} исчез! Слишком долго никто не атаковал."
                )
            except:
                pass

# ========== ГЛАВНАЯ ФУНКЦИЯ ==========

async def main():
    # Настройка расписания
    # Спавн боссов каждый день в 12:00 и 20:00
    scheduler.add_job(
        schedule_boss_spawn,
        CronTrigger(hour="12,20", minute="0"),
        id="boss_spawn"
    )
    
    # Регенерация босса каждые 5 минут
    scheduler.add_job(
        check_boss_regeneration,
        "interval",
        minutes=5,
        id="boss_regen"
    )
    
    # Проверка таймаута босса каждые 30 минут
    scheduler.add_job(
        boss_timeout,
        "interval",
        minutes=30,
        id="boss_timeout"
    )
    
    scheduler.start()
    
    logger.info("🤖 Бот запущен!")
    logger.info("Расписание:")
    logger.info("- Спавн боссов: 12:00 и 20:00")
    logger.info("- Регенерация босса: каждые 5 минут")
    logger.info("- Таймаут босса: каждые 30 минут")
    
    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
