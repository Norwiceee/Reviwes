# utils.py
"""Utility functions for the Telegram bot.

Включает вспомогательные функции:
- загрузка и сохранение данных клиентов из файла JSON,
- поиск клиентов по номеру,
- экранирование HTML в тексте,
- разбиение длинных сообщений,
- проверка URL,
- отслеживание отправленных сообщений и их очистка."""
import json
import html
import re
from urllib.parse import urlparse
from aiogram.fsm.context import FSMContext
import config

def load_clients() -> dict:
    """Загрузить словарь клиентов из файла clients.json (если файл отсутствует, вернуть пустой словарь)."""
    try:
        with open("clients.json", "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}

def save_clients(clients_data: dict) -> None:
    """Сохранить текущий словарь клиентов в файл clients.json."""
    with open("clients.json", "w", encoding="utf-8") as file:
        json.dump(clients_data, file, indent=4, ensure_ascii=False)

# Глобальный словарь клиентов, загружается при импорте модуля
clients = load_clients()

def find_client_key(client_number: str):
    """Найти идентификатор клиента (ключ словаря) по номеру клиента. Если не найдено, вернуть None."""
    pattern = re.compile(r"КЛИЕНТ\s+(\d+)", re.IGNORECASE)
    for key in clients.keys():
        m = pattern.search(key)
        if m and m.group(1) == str(client_number):
            return key
    return None

def escape_html_text(text: str) -> str:
    """Экранировать текст для безопасного отображения в HTML-сообщениях."""
    return html.escape(text)

def split_message(text: str, max_length: int = 4000) -> list:
    """Разбить длинное сообщение на список частей не длиннее max_length, не разрывая слова."""
    return [part for part in re.findall(r".{1,%d}(?:\s+|$)" % max_length, text)]

def is_valid_url(url: str) -> bool:
    """Проверить, является ли строка корректным URL (http/https)."""
    try:
        result = urlparse(url)
        return all([result.scheme in ["http", "https"], result.netloc])
    except Exception:
        return False

async def send_and_track(chat_id: int, text: str, state: FSMContext, **kwargs):
    """Отправить сообщение и сохранить его message_id в состоянии FSM для последующей очистки."""
    if not text or not text.strip():
        return None
    msg = await config.bot.send_message(chat_id, text, **kwargs)
    data = await state.get_data()
    tracked = data.get("tracked_messages", [])
    tracked.append(msg.message_id)
    await state.update_data(tracked_messages=tracked)
    return msg

async def clear_all_messages(chat_id: int, state: FSMContext):
    """Удалить все сохранённые ботом сообщения в данном чате, кроме текущего выбранного отзыва (если такой есть)."""
    data = await state.get_data()
    selected_review_msg_id = data.get("selected_review_msg_id")
    print(f"DEBUG: Сообщение с отзывом (ID: {selected_review_msg_id}) должно остаться.")
    # Ключи данных состояния, содержащие id сообщений для удаления
    keys_to_clear = [
        "tracked_messages",
        "client_info_id",
        "prompt_id",
        "platforms_list_id",
        "approve_prompt_id",
        "reject_prompt_id",
        "edit_prompt_id",
        "waiting_id",
        "init_photos_msg",
        "review_number_prompt"
    ]
    for key in keys_to_clear:
        value = data.get(key)
        if value:
            if isinstance(value, list):
                for mid in value:
                    if mid != selected_review_msg_id:
                        try:
                            print(f"DEBUG: Удаляю сообщение ID {mid}")
                            await config.bot.delete_message(chat_id, mid)
                        except Exception:
                            pass
                    else:
                        print(f"DEBUG: Оставляю сообщение ID {mid}")
            elif isinstance(value, int):
                if value != selected_review_msg_id:
                    try:
                        print(f"DEBUG: Удаляю сообщение ID {value}")
                        await config.bot.delete_message(chat_id, value)
                    except Exception:
                        pass
                else:
                    print(f"DEBUG: Оставляю сообщение ID {value}")
    # Обновить состояние, удалив очищенные ключи
    new_data = {k: v for k, v in data.items() if k not in keys_to_clear}
    if selected_review_msg_id:
        new_data["selected_review_msg_id"] = selected_review_msg_id
    await state.set_data(new_data)

async def add_pending_change(state: FSMContext, change: dict):
    """Добавить отложенное изменение (непосредственно не сохранённое в таблице) в состояние FSM."""
    data = await state.get_data()
    pending = data.get("pending_changes", [])
    pending.append(change)
    await state.update_data(pending_changes=pending)

