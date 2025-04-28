from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_auth_keyboard():
    """Keyboard for authentication prompts (no buttons, just a placeholder)."""
    return InlineKeyboardMarkup(inline_keyboard=[])

def get_cancel_keyboard():
    """Keyboard offering a cancel/return option (empty markup used for fallback responses)."""
    return InlineKeyboardMarkup(inline_keyboard=[])

def get_admin_menu_keyboard():
    """Keyboard for the admin panel main menu."""
    kb = [
        [InlineKeyboardButton(text="Создать клиента", callback_data="admin_create_client")],
        [InlineKeyboardButton(text="Редактировать клиента", callback_data="admin_edit_client")],
        [InlineKeyboardButton(text="Изменить пароль клиента", callback_data="admin_edit_password")],
        [InlineKeyboardButton(text="Просмотреть статистику", callback_data="admin_view_stats")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_user_menu_keyboard():
    """Keyboard for the main menu of an authorized client."""
    kb = [
        [InlineKeyboardButton(text="Переход к отзывам", callback_data="go_to_reviews")],
        [InlineKeyboardButton(text="Добавить фото", callback_data="add_platform_photos")],
        [InlineKeyboardButton(text="Завершить сессию", callback_data="end_session")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_actions_keyboard():
    """Keyboard with actions for review management (approve/reject/edit/add)."""
    kb = [
        [InlineKeyboardButton(text="Согласовать все отзывы", callback_data="approve_all")],
        [InlineKeyboardButton(text="Согласовать выбранные отзывы", callback_data="approve_selected")],
        [InlineKeyboardButton(text="Отклонить все отзывы", callback_data="reject_all")],
        [InlineKeyboardButton(text="Отклонить выбранные отзывы", callback_data="reject_selected")],
        [InlineKeyboardButton(text="Изменить отзывы", callback_data="edit_reviews")],
        [InlineKeyboardButton(text="Добавить отзыв", callback_data="add_review")],
        [InlineKeyboardButton(text="Добавить фотографии к отзыву", callback_data="add_photos")],
        [InlineKeyboardButton(text="Отправить отчет", callback_data="save_changes")],
        [InlineKeyboardButton(text="В главное меню", callback_data="back_to_main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def get_pending_keyboard(state):
    """Keyboard to show when there are pending changes (allowing send or continue editing)."""
    data = await state.get_data()
    if data.get("pending_changes"):
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Отправить отчет", callback_data="save_changes"),
                InlineKeyboardButton(text="Продолжить редактирование", callback_data="continue_editing")
            ]
        ])
    else:
        return get_actions_keyboard()

def get_no_new_reviews_keyboard():
    """Keyboard shown when there are no new reviews, offering to add or go back."""
    kb = [
        [InlineKeyboardButton(text="Добавить новый отзыв", callback_data="add_review")],
        [InlineKeyboardButton(text="Вернуться к выбору платформ", callback_data="return_platform_selection")],
        [InlineKeyboardButton(text="Вернуться в главное меню", callback_data="back_to_main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)
