from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from keyboards import get_auth_keyboard, get_admin_menu_keyboard
from database import get_client_by_number, authorize_client, create_client, update_client_number, update_client_password, get_client_stats

router = Router()

# Define state groups for user authentication and admin actions
class AuthStates(StatesGroup):
    WaitingForClientNumber = State()
    WaitingForPassword = State()

class AdminStates(StatesGroup):
    WaitingForCreateClientNumber = State()
    WaitingForCreateClientPassword = State()
    WaitingForEditClientNumber = State()
    WaitingForNewClientNumber = State()
    WaitingForEditPasswordClient = State()
    WaitingForNewPassword = State()
    WaitingForViewStats = State()

@router.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    """Handle the /start command for both regular users and admin."""
    chat_id = message.chat.id
    # Clear any existing conversation state
    await state.clear()
    # Check if this user is the admin (by Telegram user ID)
    admin_id = str(message.chat.id)
    env_admin_id = str(message.bot.admin_id)
    if admin_id == env_admin_id:
        # Admin user: show admin menu
        await message.answer(
            "<b>Административная панель</b>\nВыберите нужное действие:",
            reply_markup=get_admin_menu_keyboard()
        )
        return
    # Not an admin – proceed as a normal client
    # Check if this user is already authorized
    from database import get_authorized_client_by_chat  # import here to avoid circular
    client_rec = await get_authorized_client_by_chat(chat_id)
    if client_rec:
        client_num = client_rec["number"]
        # Show client information and main menu
        stats = await get_client_stats(client_rec["id"])
        if not stats:
            await message.answer("Таблица клиента не найдена. Обратитесь к администратору.")
            return
        info_text = (
            f"<b>Информация о клиенте</b>\n"
            f"Номер клиента: {client_num}\n"
            f"Количество платформ: {stats['platforms_count']}\n"
            f"Общее количество отзывов: {stats['total_reviews']}\n"
            f"Согласованных отзывов: {stats['approved_reviews']}\n"
            f"Новых отзывов: {stats['new_reviews']}"
        )
        from keyboards import get_user_menu_keyboard
        await message.answer(info_text, reply_markup=get_user_menu_keyboard())
        # Save client_id and client_number in FSM for later use
        await state.update_data(client_id=client_rec["id"], client_number=client_num)
    else:
        # Not authorized yet: prompt for client number
        await message.answer("Введите ваш клиентский номер:", reply_markup=get_auth_keyboard())
        await state.set_state(AuthStates.WaitingForClientNumber)

@router.message(AuthStates.WaitingForClientNumber)
async def process_client_number(message: types.Message, state: FSMContext):
    """Process the client number entered by the user."""
    client_number_text = message.text.strip() if message.text else ""
    if not client_number_text.isdigit():
        await message.answer("Клиент с таким номером не найден. Пожалуйста, попробуйте ещё раз:", reply_markup=get_auth_keyboard())
        return
    client_number = int(client_number_text)
    client_record = await get_client_by_number(client_number)
    if not client_record:
        # Client number not found in DB
        await message.answer("Клиент с таким номером не найден. Пожалуйста, попробуйте ещё раз:", reply_markup=get_auth_keyboard())
        return
    # Store client info (ID and number) in state and ask for password
    client_id = client_record["id"]
    await state.update_data(client_id=client_id, client_number=client_number)
    await message.answer("Введите ваш пароль:", reply_markup=get_auth_keyboard())
    await state.set_state(AuthStates.WaitingForPassword)

@router.message(AuthStates.WaitingForPassword)
async def process_password(message: types.Message, state: FSMContext):
    """Verify the password entered by the user and log them in if correct."""
    data = await state.get_data()
    client_id = data.get("client_id")
    client_number = data.get("client_number")
    password_input = message.text.strip() if message.text else ""
    if not client_id or password_input == "":
        await state.clear()
        await message.answer("Неверный номер клиента или пароль. Попробуйте снова /start.")
        return
    # Fetch client record to verify password
    client_record = await get_client_by_number(int(client_number))
    if client_record and client_record["password"] == password_input:
        # Correct password: authorize client
        await authorize_client(client_record["id"], message.chat.id)
        # Show client info and main menu
        stats = await get_client_stats(client_record["id"])
        if not stats:
            await message.answer("Таблица клиента не найдена. Обратитесь к администратору.")
            return
        info_text = (
            f"<b>Информация о клиенте</b>\n"
            f"Номер клиента: {client_number}\n"
            f"Количество платформ: {stats['platforms_count']}\n"
            f"Общее количество отзывов: {stats['total_reviews']}\n"
            f"Согласованных отзывов: {stats['approved_reviews']}\n"
            f"Новых отзывов: {stats['new_reviews']}"
        )
        from keyboards import get_user_menu_keyboard
        await message.answer(info_text, reply_markup=get_user_menu_keyboard())
        # Save authorization in state
        await state.update_data(client_id=client_record["id"], client_number=client_number)
    else:
        # Wrong password
        await state.clear()
        await message.answer("Неверный номер клиента или пароль. Попробуйте снова /start.")

# Admin command handlers:

@router.callback_query(F.data == "admin_create_client")
async def admin_create_client_callback(callback: types.CallbackQuery, state: FSMContext):
    """Admin chose to create a new client account."""
    await callback.answer()
    # Prompt for new client number
    await callback.message.edit_text("Введите новый номер клиента:", reply_markup=get_auth_keyboard())
    await state.set_state(AdminStates.WaitingForCreateClientNumber)

@router.message(AdminStates.WaitingForCreateClientNumber)
async def process_create_client_number(message: types.Message, state: FSMContext):
    """Process the client number for new client creation."""
    num_text = message.text.strip() if message.text else ""
    if not num_text.isdigit():
        await message.answer("Пожалуйста, введите корректный номер клиента (целое число).", reply_markup=get_auth_keyboard())
        return
    new_num = int(num_text)
    # Check if client already exists
    record = await get_client_by_number(new_num)
    if record:
        await message.answer("Клиент с таким номером уже существует.", reply_markup=get_auth_keyboard())
        await state.clear()
        return
    # Store the new client number and prompt for password
    await state.update_data(new_client_number=new_num)
    await message.answer("Введите пароль для нового клиента:", reply_markup=get_auth_keyboard())
    await state.set_state(AdminStates.WaitingForCreateClientPassword)

@router.message(AdminStates.WaitingForCreateClientPassword)
async def process_create_client_password(message: types.Message, state: FSMContext):
    """Create the new client with the provided password."""
    data = await state.get_data()
    new_num = data.get("new_client_number")
    password = message.text.strip() if message.text else ""
    if new_num is None or password == "":
        await message.answer("Ошибка при создании клиента. Попробуйте заново.", reply_markup=get_auth_keyboard())
        await state.clear()
        return
    # Create client in DB
    await create_client(new_num, password)
    await message.answer(f"Клиент {new_num} успешно создан.", reply_markup=get_admin_menu_keyboard())
    await state.clear()

@router.callback_query(F.data == "admin_edit_client")
async def admin_edit_client_callback(callback: types.CallbackQuery, state: FSMContext):
    """Admin chose to edit an existing client's number."""
    await callback.answer()
    await callback.message.edit_text("Введите текущий номер клиента для редактирования:", reply_markup=get_auth_keyboard())
    await state.set_state(AdminStates.WaitingForEditClientNumber)

@router.message(AdminStates.WaitingForEditClientNumber)
async def process_edit_client_number(message: types.Message, state: FSMContext):
    """Process the client number whose record needs to be edited."""
    num_text = message.text.strip() if message.text else ""
    if not num_text.isdigit():
        await message.answer("Введите корректный номер (целое число).", reply_markup=get_auth_keyboard())
        return
    old_num = int(num_text)
    client_record = await get_client_by_number(old_num)
    if not client_record:
        await message.answer("Клиент с таким номером не найден.", reply_markup=get_auth_keyboard())
        await state.clear()
        return
    # Store the client ID to edit
    await state.update_data(edit_client_id=client_record["id"], edit_client_number=old_num)
    # Prompt for new number
    await message.answer("Введите новый номер клиента:", reply_markup=get_auth_keyboard())
    await state.set_state(AdminStates.WaitingForNewClientNumber)

@router.message(AdminStates.WaitingForNewClientNumber)
async def process_new_client_number(message: types.Message, state: FSMContext):
    """Process the new client number for an existing client."""
    num_text = message.text.strip() if message.text else ""
    if not num_text.isdigit():
        await message.answer("Пожалуйста, введите корректный номер (целое число).", reply_markup=get_auth_keyboard())
        return
    new_num = int(num_text)
    data = await state.get_data()
    old_client_id = data.get("edit_client_id")
    old_number = data.get("edit_client_number")
    if old_client_id is None:
        await message.answer("Ошибка. Повторите операцию.", reply_markup=get_auth_keyboard())
        await state.clear()
        return
    # Check if new number is not already taken by another client
    existing = await get_client_by_number(new_num)
    if existing:
        await message.answer("Клиент с новым номером уже существует.", reply_markup=get_auth_keyboard())
        await state.clear()
        return
    # Update the client's number in DB
    await update_client_number(old_client_id, new_num)
    await message.answer(f"Номер клиента изменён с {old_number} на {new_num}.", reply_markup=get_admin_menu_keyboard())
    await state.clear()

@router.callback_query(F.data == "admin_edit_password")
async def admin_edit_password_callback(callback: types.CallbackQuery, state: FSMContext):
    """Admin chose to change a client's password."""
    await callback.answer()
    await callback.message.edit_text("Введите номер клиента для изменения пароля:", reply_markup=get_auth_keyboard())
    await state.set_state(AdminStates.WaitingForEditPasswordClient)

@router.message(AdminStates.WaitingForEditPasswordClient)
async def process_edit_password_client(message: types.Message, state: FSMContext):
    """Process the client number for which to change password."""
    num_text = message.text.strip() if message.text else ""
    if not num_text.isdigit():
        await message.answer("Введите корректный номер клиента.", reply_markup=get_auth_keyboard())
        return
    client_num = int(num_text)
    client_record = await get_client_by_number(client_num)
    if not client_record:
        await message.answer("Клиент с таким номером не найден.", reply_markup=get_auth_keyboard())
        await state.clear()
        return
    # Store client ID to change password
    await state.update_data(password_client_id=client_record["id"], password_client_number=client_num)
    await message.answer("Введите новый пароль для клиента:", reply_markup=get_auth_keyboard())
    await state.set_state(AdminStates.WaitingForNewPassword)

@router.message(AdminStates.WaitingForNewPassword)
async def process_new_password(message: types.Message, state: FSMContext):
    """Update the client's password in the database."""
    data = await state.get_data()
    client_id = data.get("password_client_id")
    client_num = data.get("password_client_number")
    new_password = message.text.strip() if message.text else ""
    if client_id is None or new_password == "":
        await message.answer("Ошибка. Повторите операцию.", reply_markup=get_auth_keyboard())
        await state.clear()
        return
    await update_client_password(client_id, new_password)
    await message.answer(f"Пароль для клиента {client_num} успешно изменён.", reply_markup=get_admin_menu_keyboard())
    await state.clear()

@router.callback_query(F.data == "admin_view_stats")
async def admin_view_stats_callback(callback: types.CallbackQuery, state: FSMContext):
    """Admin chose to view a client's statistics."""
    await callback.answer()
    await callback.message.edit_text("Введите номер клиента для просмотра статистики:", reply_markup=get_auth_keyboard())
    await state.set_state(AdminStates.WaitingForViewStats)

@router.message(AdminStates.WaitingForViewStats)
async def process_view_stats(message: types.Message, state: FSMContext):
    """Retrieve and display the stats for the requested client."""
    num_text = message.text.strip() if message.text else ""
    if not num_text.isdigit():
        await message.answer("Введите корректный номер (целое число).", reply_markup=get_auth_keyboard())
        return
    client_num = int(num_text)
    client_record = await get_client_by_number(client_num)
    if not client_record:
        await message.answer("Клиент с таким номером не найден.", reply_markup=get_auth_keyboard())
        await state.clear()
        return
    stats = await get_client_stats(client_record["id"])
    if not stats:
        await message.answer("Таблица клиента не найдена. Обратитесь к администратору.")
        await state.clear()
        return
    stat_text = (
        f"<b>Статистика клиента {client_num}</b>\n"
        f"Общее количество отзывов: {stats['total_reviews']}\n"
        f"Согласованных отзывов: {stats['approved_reviews']}\n"
        f"Новых отзывов: {stats['new_reviews']}"
    )
    await message.answer(stat_text, reply_markup=get_admin_menu_keyboard())
    await state.clear()
