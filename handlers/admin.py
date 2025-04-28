
# handlers/admin.py
"""Обработчики для команд и колбэков панели администратора.

Позволяют администратору создавать новых клиентов, изменять номер/пароль клиента и просматривать статистику клиентов."""
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from config import ADMIN_ID
from utils import clients, save_clients, find_client_key, clear_all_messages, send_and_track
from keyboards import get_auth_keyboard, get_admin_menu_keyboard
from database import get_client_stats

admin_router = Router()

class AdminStates(StatesGroup):
    """Состояния, используемые в сценариях панели администратора."""
    WaitingForCreateClientNumber = State()
    WaitingForCreateClientPassword = State()
    WaitingForEditClientNumber = State()
    WaitingForEditAction = State()
    WaitingForNewClientNumber = State()
    WaitingForNewClientPassword = State()
    WaitingForViewStats = State()

@admin_router.message(Command("admin"))
async def admin_command(message: Message, state: FSMContext):
    """Точка входа в панель администратора через команду /admin."""
    chat_id = message.chat.id
    await clear_all_messages(chat_id, state)
    if str(chat_id) != ADMIN_ID:
        await send_and_track(chat_id, "У вас нет доступа в административную панель.", state)
        return
    await send_and_track(chat_id,
                         "<b>Административная панель</b>\nВыберите нужное действие:",
                         state,
                         reply_markup=get_admin_menu_keyboard())

@admin_router.callback_query(F.data == "admin_create_client")
async def admin_create_client(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик нажатия кнопки 'Создать клиента' в админ-меню."""
    chat_id = callback.message.chat.id
    await clear_all_messages(chat_id, state)
    if str(chat_id) != ADMIN_ID:
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer()
    await send_and_track(chat_id, "Введите номер нового клиента:", state, reply_markup=get_auth_keyboard())
    await state.set_state(AdminStates.WaitingForCreateClientNumber)

@admin_router.message(AdminStates.WaitingForCreateClientNumber)
async def process_create_client_number(message: Message, state: FSMContext):
    """Обработать ввод номера клиента для создания нового клиента."""
    chat_id = message.chat.id
    await clear_all_messages(chat_id, state)
    if not message.text or not message.text.strip().isdigit():
        await send_and_track(chat_id, "Введите корректный номер (целое число).", state,
                              reply_markup=get_auth_keyboard())
        return
    num = message.text.strip()
    if find_client_key(num):
        await send_and_track(chat_id, "Клиент с таким номером уже существует.", state,
                              reply_markup=get_auth_keyboard())
        await state.clear()
        return
    # Временно сохраняем новый номер и переходим к запросу пароля
    await state.update_data(new_client_number=num)
    await send_and_track(chat_id, "Введите пароль для нового клиента:", state, reply_markup=get_auth_keyboard())
    await state.set_state(AdminStates.WaitingForCreateClientPassword)

@admin_router.message(AdminStates.WaitingForCreateClientPassword)
async def process_create_client_password(message: Message, state: FSMContext):
    """Завершить создание нового клиента, сохранив введённый пароль."""
    chat_id = message.chat.id
    await clear_all_messages(chat_id, state)
    password = message.text.strip()
    data = await state.get_data()
    num = data.get("new_client_number")
    if not num:
        await send_and_track(chat_id, "Ошибка. Повторите создание клиента.", state,
                              reply_markup=get_auth_keyboard())
        await state.clear()
        return
    key = f"КЛИЕНТ {num}(new)"
    clients[key] = {"password": password, "authorized": False, "telegram_id": None}
    save_clients(clients)
    await send_and_track(chat_id, f"Клиент {key} успешно создан.", state,
                          reply_markup=get_admin_menu_keyboard())
    await state.clear()

@admin_router.callback_query(F.data == "admin_edit_client")
async def admin_edit_client(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик нажатия 'Редактировать клиента' в админ-меню."""
    chat_id = callback.message.chat.id
    await clear_all_messages(chat_id, state)
    if str(chat_id) != ADMIN_ID:
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer()
    await send_and_track(chat_id, "Введите номер клиента для редактирования:", state,
                          reply_markup=get_auth_keyboard())
    await state.set_state(AdminStates.WaitingForEditClientNumber)

@admin_router.message(AdminStates.WaitingForEditClientNumber)
async def process_edit_client_number(message: Message, state: FSMContext):
    """Обработать ввод номера клиента для редактирования (смена номера или пароля)."""
    chat_id = message.chat.id
    await clear_all_messages(chat_id, state)
    if not message.text or not message.text.strip().isdigit():
        await send_and_track(chat_id, "Введите корректный номер (целое число).", state,
                              reply_markup=get_auth_keyboard())
        return
    num = message.text.strip()
    key = find_client_key(num)
    if not key:
        await send_and_track(chat_id, "Клиент с таким номером не найден.", state,
                              reply_markup=get_auth_keyboard())
        await state.clear()
        return
    # Сохраняем ключ (идентификатор) клиента для редактирования и предлагаем выбор действия
    await state.update_data(edit_client_key=key)
    options_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сменить номер клиента", callback_data="admin_edit_number")],
        [InlineKeyboardButton(text="Сменить пароль клиента", callback_data="admin_edit_password")],
        [InlineKeyboardButton(text="В главное меню", callback_data="back_to_main_menu")]
    ])
    await send_and_track(chat_id, "Выберите действие:", state, reply_markup=options_keyboard)
    await state.set_state(AdminStates.WaitingForEditAction)

@admin_router.callback_query(F.data == "admin_edit_number")
async def admin_edit_number(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора смены номера клиента."""
    chat_id = callback.message.chat.id
    await clear_all_messages(chat_id, state)
    if str(chat_id) != ADMIN_ID:
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer()
    await send_and_track(chat_id, "Введите новый номер клиента:", state, reply_markup=get_auth_keyboard())
    await state.set_state(AdminStates.WaitingForNewClientNumber)

@admin_router.message(AdminStates.WaitingForNewClientNumber)
async def process_new_client_number(message: Message, state: FSMContext):
    """Обработать ввод нового номера клиента при редактировании."""
    chat_id = message.chat.id
    await clear_all_messages(chat_id, state)
    if not message.text or not message.text.strip().isdigit():
        await send_and_track(chat_id, "Введите корректный номер (целое число).", state,
                              reply_markup=get_auth_keyboard())
        return
    new_num = message.text.strip()
    data = await state.get_data()
    old_key = data.get("edit_client_key")
    if not old_key:
        await send_and_track(chat_id, "Ошибка. Повторите операцию.", state,
                              reply_markup=get_auth_keyboard())
        await state.clear()
        return
    if find_client_key(new_num):
        await send_and_track(chat_id, "Клиент с новым номером уже существует.", state,
                              reply_markup=get_auth_keyboard())
        await state.clear()
        return
    new_key = f"КЛИЕНТ {new_num}(new)"
    # Переименовываем ключ клиента в словаре (смена номера)
    clients[new_key] = clients.pop(old_key)
    save_clients(clients)
    await send_and_track(chat_id, f"Номер клиента изменён с {old_key} на {new_key}.", state,
                          reply_markup=get_admin_menu_keyboard())
    await state.clear()

@admin_router.callback_query(F.data == "admin_edit_password")
async def admin_edit_password(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора смены пароля клиента."""
    chat_id = callback.message.chat.id
    await clear_all_messages(chat_id, state)
    if str(chat_id) != ADMIN_ID:
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer()
    await send_and_track(chat_id, "Введите новый пароль для клиента:", state, reply_markup=get_auth_keyboard())
    await state.set_state(AdminStates.WaitingForNewClientPassword)

@admin_router.message(AdminStates.WaitingForNewClientPassword)
async def process_new_client_password(message: Message, state: FSMContext):
    """Обработать ввод нового пароля и сохранить его для выбранного клиента."""
    chat_id = message.chat.id
    await clear_all_messages(chat_id, state)
    password = message.text.strip()
    data = await state.get_data()
    key = data.get("edit_client_key")
    if not key:
        await send_and_track(chat_id, "Ошибка. Повторите операцию.", state,
                              reply_markup=get_auth_keyboard())
        await state.clear()
        return
    clients[key]["password"] = password
    save_clients(clients)
    await send_and_track(chat_id, f"Пароль для клиента {key} успешно изменён.", state,
                          reply_markup=get_admin_menu_keyboard())
    await state.clear()

@admin_router.callback_query(F.data == "admin_view_stats")
async def admin_view_stats(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик нажатия 'Просмотреть статистику' в админ-меню."""
    chat_id = callback.message.chat.id
    await clear_all_messages(chat_id, state)
    if str(chat_id) != ADMIN_ID:
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer()
    await send_and_track(chat_id, "Введите номер клиента для просмотра статистики:", state,
                          reply_markup=get_auth_keyboard())
    await state.set_state(AdminStates.WaitingForViewStats)

@admin_router.message(AdminStates.WaitingForViewStats)
async def process_view_stats(message: Message, state: FSMContext):
    """Обработать ввод номера клиента и вывести его статистику."""
    chat_id = message.chat.id
    await clear_all_messages(chat_id, state)
    if not message.text or not message.text.strip().isdigit():
        await send_and_track(chat_id, "Введите корректный номер (целое число).", state,
                              reply_markup=get_auth_keyboard())
        return
    num = message.text.strip()
    key = find_client_key(num)
    if not key:
        await send_and_track(chat_id, "Клиент с таким номером не найден.", state,
                              reply_markup=get_auth_keyboard())
        await state.clear()
        return
    stats = get_client_stats(key)
    if not stats:
        await send_and_track(chat_id, "Статистика не найдена. Обратитесь к администратору.", state,
                              reply_markup=get_auth_keyboard())
        await state.clear()
        return
    stat_text = (
        f"<b>Статистика клиента {key}</b>\n"
        f"Общее количество отзывов: {stats['total_reviews']}\n"
        f"Согласованных отзывов: {stats['approved_reviews']}\n"
        f"Новых отзывов: {stats['new_reviews']}"
    )
    await send_and_track(chat_id, stat_text, state, reply_markup=get_admin_menu_keyboard())
    await state.clear()

