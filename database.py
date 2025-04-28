import os
import asyncpg
from datetime import datetime

# Global connection pool
pool: asyncpg.Pool = None

async def init_db():
    """Initialize the database connection pool and ensure tables exist."""
    global pool
    # Read database configuration from environment
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "")
    db_user = os.getenv("DB_USER", "")
    db_password = os.getenv("DB_PASSWORD", "")
    # Create connection pool
    pool = await asyncpg.create_pool(
        host=db_host,
        port=int(db_port),
        user=db_user,
        password=db_password,
        database=db_name
    )
    # Create tables if they do not exist
    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id SERIAL PRIMARY KEY,
            number INTEGER UNIQUE NOT NULL,
            password TEXT NOT NULL,
            authorized BOOLEAN DEFAULT FALSE,
            telegram_id BIGINT
        );
        CREATE TABLE IF NOT EXISTS platforms (
            id SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            number INTEGER NOT NULL,
            url TEXT,
            UNIQUE(client_id, number)
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            platform_id INTEGER NOT NULL REFERENCES platforms(id) ON DELETE CASCADE,
            review_text TEXT NOT NULL,
            review_date TEXT,
            manager_comment TEXT,
            status TEXT NOT NULL,
            photo_link TEXT
        );
        CREATE TABLE IF NOT EXISTS photo_packs (
            id SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            platform_id INTEGER NOT NULL REFERENCES platforms(id) ON DELETE CASCADE,
            folder_link TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            synced BOOLEAN NOT NULL DEFAULT FALSE
        );
        """)

async def is_clients_empty() -> bool:
    """Check if the clients table is empty (no clients imported yet)."""
    async with pool.acquire() as conn:
        result = await conn.fetchval("SELECT COUNT(*) FROM clients;")
        return result == 0

async def create_client(number: int, password: str) -> int:
    """Create a new client with the given number and password. Returns client ID."""
    async with pool.acquire() as conn:
        # Insert client (authorized False by default)
        client_id = await conn.fetchval(
            "INSERT INTO clients(number, password) VALUES($1, $2) RETURNING id;",
            number, password
        )
        return client_id

async def update_client_number(client_id: int, new_number: int):
    """Update the client number (identifier) for a given client."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE clients SET number=$1 WHERE id=$2;",
            new_number, client_id
        )

async def update_client_password(client_id: int, new_password: str):
    """Update the password for a given client."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE clients SET password=$1 WHERE id=$2;",
            new_password, client_id
        )

async def get_client_by_number(number: int):
    """Fetch a client record by client number."""
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT id, password, authorized, telegram_id FROM clients WHERE number=$1;",
            number
        )

async def authorize_client(client_id: int, chat_id: int):
    """Set a client as authorized and store their Telegram chat ID."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE clients SET authorized=True, telegram_id=$1 WHERE id=$2;",
            chat_id, client_id
        )

async def unauthorize_client(client_id: int):
    """Mark a client as unauthorized (logout)."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE clients SET authorized=False, telegram_id=NULL WHERE id=$1;",
            client_id
        )

async def get_authorized_client_by_chat(chat_id: int):
    """Get the client (id, number) that is authorized for this Telegram chat, if any."""
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT id, number FROM clients WHERE telegram_id=$1 AND authorized=True;",
            chat_id
        )

async def get_client_stats(client_id: int) -> dict:
    """Compute statistics for a client: number of platforms, total reviews, approved and new reviews."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT 
                (SELECT COUNT(*) FROM platforms WHERE client_id=$1) AS platforms_count,
                (SELECT COUNT(*) FROM reviews WHERE client_id=$1) AS total_reviews,
                (SELECT COUNT(*) FROM reviews WHERE client_id=$1 AND status='approved') AS approved_reviews,
                (SELECT COUNT(*) FROM reviews WHERE client_id=$1 AND status='new') AS new_reviews;
        """, client_id)
        if row:
            return {
                "platforms_count": row["platforms_count"],
                "total_reviews": row["total_reviews"],
                "approved_reviews": row["approved_reviews"],
                "new_reviews": row["new_reviews"]
            }
        return None

async def create_platform(client_id: int, platform_number: int, url: str) -> int:
    """Create a platform record for a client. Returns platform ID."""
    async with pool.acquire() as conn:
        platform_id = await conn.fetchval(
            "INSERT INTO platforms(client_id, number, url) VALUES($1, $2, $3) RETURNING id;",
            client_id, platform_number, url
        )
        return platform_id

async def get_platform_id(client_id: int, platform_number: int):
    """Fetch the platform id for a given client and platform number."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT id FROM platforms WHERE client_id=$1 AND number=$2;",
            client_id, platform_number
        )

async def create_review(client_id: int, platform_id: int, text: str, date: str, manager_comment: str, status: str, photo_link: str = None):
    """Create a new review record in the database."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO reviews(client_id, platform_id, review_text, review_date, manager_comment, status, photo_link) "
            "VALUES($1, $2, $3, $4, $5, $6, $7);",
            client_id, platform_id, text, date, manager_comment, status, photo_link
        )

async def update_review_status(review_id: int, new_status: str):
    """Update the status of a review."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE reviews SET status=$1 WHERE id=$2;",
            new_status, review_id
        )

async def update_review_text(review_id: int, new_text: str):
    """Update the text of a review."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE reviews SET review_text=$1 WHERE id=$2;",
            new_text, review_id
        )

async def update_review_photo(review_id: int, folder_link: str):
    """Update a review to mark it approved and set its photo link."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE reviews SET status='approved', photo_link=$1 WHERE id=$2;",
            folder_link, review_id
        )

async def get_new_reviews(client_id: int, platform_id: int):
    """Get all 'new' status reviews for a given client and platform."""
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, review_text FROM reviews WHERE client_id=$1 AND platform_id=$2 AND status='new';",
            client_id, platform_id
        )

async def get_platforms_with_new_counts(client_id: int):
    """Get all platforms for a client along with the count of new reviews on each."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.number, p.url, COALESCE(r.new_count, 0) AS new_count
            FROM platforms p
            LEFT JOIN (
                SELECT platform_id, COUNT(*) AS new_count
                FROM reviews
                WHERE client_id=$1 AND status='new'
                GROUP BY platform_id
            ) r ON p.id = r.platform_id
            WHERE p.client_id=$1
            ORDER BY p.number;
        """, client_id)
        return rows

async def create_photo_pack(client_id: int, platform_id: int, folder_link: str):
    """Record a photo pack upload (Google Drive folder link) for a platform."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO photo_packs(client_id, platform_id, folder_link) VALUES($1, $2, $3);",
            client_id, platform_id, folder_link
        )

async def get_unsynced_photo_packs(client_id: int):
    """Get all unsynced photo pack records for a client."""
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, platform_id, folder_link FROM photo_packs WHERE client_id=$1 AND synced=False;",
            client_id
        )

async def mark_photo_pack_synced(pack_id: int):
    """Mark a photo pack record as synced to Google Sheets."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE photo_packs SET synced=True WHERE id=$1;",
            pack_id
        )
