import os
import asyncio
import asyncpg
from dotenv import load_dotenv

# Загружаем переменные окружения из файла .env
load_dotenv()

# Параметры подключения из .env для целевой базы данных
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "reviews")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# Параметры для суперпользовательского подключения (используются для создания роли и базы)
# Если у вас суперпользователь отличается, задайте DB_SUPERUSER и DB_SUPERPASSWORD в .env.
DB_SUPERUSER = os.getenv("DB_SUPERUSER", "postgres")
DB_SUPERPASSWORD = os.getenv("DB_SUPERPASSWORD", "")


async def create_role_if_not_exists():
    """
    Подключается к базе "postgres" как суперпользователь и проверяет,
    существует ли роль DB_USER. Если нет – создаёт роль с правом CREATEDB.
    """
    conn = None
    try:
        conn = await asyncpg.connect(
            host=DB_HOST,
            port=int(DB_PORT),
            user=DB_SUPERUSER,
            password=DB_SUPERPASSWORD,
            database="postgres"
        )
        role_exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1;", DB_USER)
        if not role_exists:
            # Экранируем пароль: заменяем одинарные кавычки на две одинарные кавычки
            escaped_password = DB_PASSWORD.replace("'", "''")
            query = f'CREATE ROLE "{DB_USER}" WITH LOGIN PASSWORD \'{escaped_password}\' CREATEDB;'
            await conn.execute(query)
            print(f"Role '{DB_USER}' created successfully.")
        else:
            print(f"Role '{DB_USER}' already exists.")
    except Exception as e:
        print(f"Error creating role '{DB_USER}': {e}")
        print(
            "Убедитесь, что в файле .env заданы корректные суперпользовательские данные (DB_SUPERUSER, DB_SUPERPASSWORD), "
            "а также что на сервере PostgreSQL существует такая роль или установите другой суперпользователь.")
    finally:
        if conn is not None:
            await conn.close()


async def create_database():
    """
    Подключается к базе данных "postgres" с использованием роли DB_USER и проверяет наличие базы DB_NAME.
    Если такой базы нет – создаёт её.
    """
    conn = None
    try:
        conn = await asyncpg.connect(
            host=DB_HOST,
            port=int(DB_PORT),
            user=DB_USER,
            password=DB_PASSWORD,
            database="postgres"
        )
        db_exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1;", DB_NAME)
        if not db_exists:
            await conn.execute(f'CREATE DATABASE "{DB_NAME}";')
            print(f"Database '{DB_NAME}' created successfully.")
        else:
            print(f"Database '{DB_NAME}' already exists.")
    except Exception as e:
        print(f"Error while creating the database: {e}")
    finally:
        if conn is not None:
            await conn.close()


async def main():
    # Сначала создаем нужную роль (если она отсутствует)
    await create_role_if_not_exists()
    # Затем создаем базу данных, если её ещё не существует
    await create_database()

    # Импортируем функции для инициализации таблиц и импорта данных
    from database import init_db, is_clients_empty
    from google_sheets import init_google_services, import_initial_data

    # Инициализируем Google сервисы (Sheets/Drive)
    init_google_services()
    # Инициализируем базу данных: создаются все таблицы, если их еще нет
    await init_db()
    # Если таблица клиентов пуста — считаем, что это первый запуск и импортируем данные из Google Sheets
    if await is_clients_empty():
        await import_initial_data()
        print("Initial data imported from Google Sheets successfully.")
    else:
        print("Database already contains data; no import needed.")


if __name__ == "__main__":
    asyncio.run(main())
