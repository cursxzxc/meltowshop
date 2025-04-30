import sqlite3
import logging
import os
from config import DATABASE_FILE, SCRIPTS_DIR

logger = logging.getLogger(__name__)

def create_db_connection():
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        return conn
    except sqlite3.Error as e:
        logger.error(f"Ошибка подключения к базе данных: {e}")
        return None

def create_users_table(conn):
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY
            )
        """)
        conn.commit()
        logger.info("Таблица users успешно создана (или уже существовала).")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при создании таблицы: {e}")

def add_user_to_db(user_id):
    conn = create_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,)) # Исправлено: user_id вместо id
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Ошибка при добавлении пользователя в базу данных: {e}")
        finally:
            conn.close()

def get_all_user_ids_from_db():
    conn = create_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            user_ids = [row[0] for row in cursor.fetchall()]
            return user_ids
        except sqlite3.Error as e:
            logger.error(f"Ошибка при получении user_id из базы данных: {e}")
            return []
        finally:
            conn.close()

def get_script_price(script_path):
    try:
        with open(os.path.join(script_path, "price.txt"), "r") as f:
            price = float(f.read().strip())
            return price
    except FileNotFoundError:
        logger.warning(f"Файл price.txt не найден в {script_path}")
        return None
    except ValueError:
        logger.error(f"Некорректный формат цены в price.txt в {script_path}")
        return None

def get_script_description(script_path):
    try:
        with open(os.path.join(script_path, "description.txt"), "r", encoding="utf-8") as f:
            description = f.read().strip()
            return description
    except FileNotFoundError:
        logger.warning(f"Файл description.txt не найден в {script_path}")
        return None

def get_script_image(script_path):
    image_path = os.path.join(script_path, "image.jpg")
    if os.path.exists(image_path):
        return image_path
    else:
        logger.info(f"Файл image.jpg не найден в {script_path}")
        return None

def get_script_file(script_path):
    archive_path = os.path.join(script_path, "script.zip")  # Предполагаем, что архив называется script.zip
    if os.path.exists(archive_path):
        return archive_path
    else:
        logger.warning(f"Архив script.zip не найден в {script_path}")
        return None

async def is_session_valid(session_file):
    """
    Проверяет, является ли сессия Telethon рабочей.
    """
    # Здесь должна быть логика проверки сессии. Например, попытка подключения.
    # Поскольку это зависит от вашей реализации, здесь просто заглушка.
    return True  # Возвращаем True для примера, замените на реальную проверку

def move_file(file_name, source_dir, dest_dir):
    """
    Перемещает файл из одной директории в другую.
    """
    source_path = os.path.join(source_dir, file_name)
    dest_path = os.path.join(dest_dir, file_name)
    try:
        os.rename(source_path, dest_path)
        logger.info(f"Файл {file_name} перемещен из {source_dir} в {dest_dir}")
    except FileNotFoundError:
        logger.error(f"Файл {file_name} не найден в {source_dir}")
    except OSError as e:
        logger.error(f"Ошибка при перемещении файла {file_name}: {e}")

async def get_available_sessions(session_dir):
    """
    Получает список доступных файлов сессий в указанной директории.
    """
    try:
        return [f for f in os.listdir(session_dir) if f.endswith(".session")]
    except FileNotFoundError:
        logger.error(f"Директория {session_dir} не найдена.")
        return []

# Функции для изменения цены и т.д. в файлах

def update_script_price(script_folder, new_price):
    """Обновляет цену скрипта в файле price.txt."""
    script_path = os.path.join(SCRIPTS_DIR, script_folder)
    price_file_path = os.path.join(script_path, "price.txt")

    try:
        with open(price_file_path, "w") as f:
            f.write(str(new_price))
        logger.info(f"Цена скрипта в {script_path} обновлена до {new_price}")
    except FileNotFoundError:
        logger.error(f"Файл price.txt не найден в {script_path}")
    except Exception as e:
        logger.error(f"Ошибка при записи в файл price.txt: {e}")