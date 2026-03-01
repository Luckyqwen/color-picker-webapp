import os
import asyncpg
from datetime import datetime
from typing import Optional, List, Dict, Any

DATABASE_URL = os.getenv("DATABASE_URL")
# Если DATABASE_URL не задана, можно использовать fallback для локального тестирования
if not DATABASE_URL:
    # Пример для локального PostgreSQL (измените под свои параметры)
    DATABASE_URL = "postgresql://postgres:password@localhost:5432/colorpicker"

# Глобальный пул соединений
_pool: Optional[asyncpg.Pool] = None

async def init_db():
    """Инициализация пула соединений и создание таблиц, если их нет."""
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL)
    async with _pool.acquire() as conn:
        # Таблица пользователей
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        # Таблица заказов
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                photo_file_id TEXT,
                wood_type TEXT,
                application_method TEXT,
                gloss INTEGER,
                volume FLOAT,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')

async def add_user(user_id: int, username: Optional[str], first_name: Optional[str]):
    """Добавить пользователя, если его нет."""
    async with _pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO users (user_id, username, first_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO NOTHING
        ''', user_id, username, first_name)

async def save_order(user_id: int, photo_id: Optional[str], wood: Optional[str],
                     method: Optional[str], gloss: Optional[int], volume: float) -> int:
    """Сохранить заказ, вернуть его ID."""
    async with _pool.acquire() as conn:
        order_id = await conn.fetchval('''
            INSERT INTO orders (user_id, photo_file_id, wood_type, application_method, gloss, volume)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        ''', user_id, photo_id, wood, method, gloss, volume)
        return order_id

async def get_new_orders() -> List[Dict[str, Any]]:
    """Получить все новые заказы."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT id, user_id, photo_file_id, wood_type, application_method,
                   gloss, volume, status, created_at
            FROM orders
            WHERE status = 'new'
            ORDER BY created_at DESC
        ''')
        # Преобразуем в список словарей
        return [dict(row) for row in rows]

async def update_order_status(order_id: int, status: str):
    """Обновить статус заказа."""
    async with _pool.acquire() as conn:
        await conn.execute('''
            UPDATE orders SET status = $1 WHERE id = $2
        ''', status, order_id)