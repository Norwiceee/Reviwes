import re
import asyncio
import tempfile
import html

from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from database import get_platforms_with_new_counts, get_new_reviews, get_platform_id
from database import update_review_status, update_review_text, update_review_photo
from database import unauthorize_client
from database import get_client_stats
from googleapiclient.http import MediaFileUpload
from datetime import datetime
from keyboards import (get_pending_keyboard, get_user_menu_keyboard,
                       get_no_new_reviews_keyboard)

router = Router()

class ReviewsStates(StatesGroup):
    WaitingForPlatform = State()
    WaitingForMenuAction = State()
    ApproveSelected = State()
    RejectSelected = State()
    WaitingForReviewNumber = State()
    WaitingForNewReviewText = State()
    WaitingForPlatformAddition = State()
    WaitingForNewReviewTextAddition = State()
    WaitingForPlatformPhotos = State()
    WaitingForReviewNumberForPhotos = State()
    WaitingForPhotosForReview = State()

@router.callback_query(F.data == "go_to_reviews")
async def go_to_reviews_callback(callback: CallbackQuery, state: FSMContext):
    """User clicked 'Переход к отзывам' to view platforms and new reviews."""
    chat_id = callback.message.chat.id
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    await callback.answer()
    # Loading message
    loading = await callback.message.answer("Прогружается список платформ, ожидайте...")
    # Get client_id from state or DB
    data = await state.get_data()
    client_id = data.get("client_id")
    client_number = data.get("client_number")
    if not client_id:
        from database import get_authorized_client_by_chat
        client_rec = await get_authorized_client_by_chat(chat_id)
        if client_rec:
            client_id = client_rec["id"]
            client_number = client_rec["number"]
            await state.update_data(client_id=client_id, client_number=client_number)
    if not client_id:
        await loading.edit_text("Номер клиента не найден. Используйте /start для повторной авторизации.")
        return
    # Retrieve platforms and new review counts from DB
    rows = await get_platforms_with_new_counts(client_id)
    if not rows:
        await loading.edit_text("Не найдены платформы для данного клиента.")
        return
    # Format message with platform list and count of new reviews
    divider = "————————————————————————"
    lines = []
    for row in rows:
        plat_num = row["number"]
        url = row["url"]
        new_count = row["new_count"]
        platform_label = f"ПЛАТФОРМА {plat_num}"
        if url:
            line = f'<a href="{url}"><u>{platform_label}</u></a>   // Количество новых отзывов - {new_count}'
        else:
            line = f'{platform_label}   // Количество новых отзывов - {new_count}'
        lines.append(line)
        lines.append(divider)
    platforms_text = "\n".join(lines)
    await loading.edit_text(platforms_text, parse_mode="HTML", disable_web_page_preview=True)
    # Show keyboard for platform selection
    buttons = []
    for row in rows:
        plat_num = row["number"]
        platform_label = f"Платформа {plat_num}"
        buttons.append(InlineKeyboardButton(text=platform_label, callback_data=f"platform_{plat_num}"))
    # Arrange buttons in 2 columns
    keyboard_buttons = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    keyboard_buttons.append([InlineKeyboardButton(text="В главное меню", callback_data="back_to_main_menu")])
    platform_kb = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    prompt = await callback.message.answer("Выберите платформу для просмотра новых отзывов или введите её номер вручную:", reply_markup=platform_kb)
    # Save prompt message ID in state (for deletion later) and set state
    await state.update_data(platforms_list_id=prompt.message_id)
    await state.set_state(ReviewsStates.WaitingForPlatform)

@router.message(ReviewsStates.WaitingForPlatform)
async def process_platform_input(message: Message, state: FSMContext):
    """Allow user to type a platform number instead of clicking the button."""
    chat_id = message.chat.id
    platform_text = message.text.strip() if message.text else ""
    if not platform_text.isdigit():
        await message.answer("Пожалуйста, введите номер платформы (числом).")
        return
    platform_number = int(platform_text)
    # Simulate the same actions as clicking the platform button
    await show_reviews_for_platform(chat_id, state, platform_number)

@router.callback_query(F.data.startswith("platform_"))
async def process_platform_selection(callback: CallbackQuery, state: FSMContext):
    """User selected a platform from the list to view its new reviews."""
    chat_id = callback.message.chat.id
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    await callback.answer()
    # Remove the platform list message if stored
    data = await state.get_data()
    if data.get("platforms_list_id"):
        try:
            await callback.message.bot.delete_message(chat_id, data["platforms_list_id"])
        except:
            pass
    # Parse platform number from callback data
    platform_key = callback.data.replace("platform_", "")
    if not platform_key.isdigit():
        await callback.message.answer("Некорректный выбор платформы.")
        return
    platform_number = int(platform_key)
    await show_reviews_for_platform(chat_id, state, platform_number)

async def show_reviews_for_platform(chat_id: int, state: FSMContext, platform_number: int):
    """Display the list of new reviews for the specified platform."""
    # Show a loading message
    wait_msg = await state.bot.send_message(chat_id, "Прогружается список отзывов, ожидайте...")
    data = await state.get_data()
    client_id = data.get("client_id")
    client_number = data.get("client_number")
    if not client_id or client_number is None:
        await wait_msg.edit_text("Ошибка: не удалось определить вашего клиента.")
        return
    # Get platform_id from DB
    platform_id = await get_platform_id(client_id, platform_number)
    if not platform_id:
        await wait_msg.edit_text("Платформа не найдена.")
        return
    # Fetch new reviews for this platform
    rows = await get_new_reviews(client_id, platform_id)
    current_reviews = []
    for r in rows:
        current_reviews.append({"id": r["id"], "review_text": r["review_text"]})
    # Include any pending inserted reviews not yet saved (with 🆕 marker)
    pending_changes = (await state.get_data()).get("pending_changes", [])
    for change in pending_changes:
        if change.get("action") == "insert":
            # Ensure we don't duplicate if the same text already in current_reviews
            if not any(item.get("pure_text", item["review_text"]) == change.get("review_text") for item in current_reviews):
                display_text = change.get("review_text") + " 🆕"
                current_reviews.append({
                    "id": None,
                    "review_text": display_text,
                    "pure_text": change.get("review_text")
                })
    # Update FSM data for the current platform and reviews
    await state.update_data(platform_number=platform_number, current_reviews=current_reviews)
    # If no new reviews to show
    if not current_reviews:
        await state.clear()  # clear state as no pending actions
        await wait_msg.delete()
        await state.bot.send_message(chat_id, "Новых отзывов пока что нет, но вы можете добавить их самостоятельно", reply_markup=get_no_new_reviews_keyboard())
        return
    # Build the message listing all reviews
    review_lines = []
    for i, rev in enumerate(current_reviews, start=1):
        # Escape HTML in review text
        text_safe = html.escape(rev["review_text"])
        review_lines.append(f"💬 {i}. {text_safe}")
    full_msg = "<b>Список отзывов для редактирования:</b>\n" + "\n".join(review_lines)
    # Delete the loading message
    try:
        await wait_msg.delete()
    except:
        pass
    # Send the review list (split into multiple messages if too long)
    parts = re.findall(r".{1,4000}(?:\s+|$)", full_msg, flags=re.DOTALL)
    for part in parts:
        await state.bot.send_message(chat_id, part, parse_mode="HTML", disable_web_page_preview=True)
    # Show action menu (approve/reject/edit/add)
    kb = await get_pending_keyboard(state)
    await state.bot.send_message(chat_id, "Выберите дальнейшее действие:", reply_markup=kb)
    await state.set_state(ReviewsStates.WaitingForMenuAction)

@router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu_callback(callback: CallbackQuery, state: FSMContext):
    """Handle the 'В главное меню' action to return to main menu."""
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    # Show main menu (client info and user menu keyboard)
    data = await state.get_data()
    client_id = data.get("client_id")
    client_number = data.get("client_number")
    if client_id and client_number is not None:
        from database import get_client_stats
        stats = await get_client_stats(client_id)
        if stats:
            info_text = (
                f"<b>Информация о клиенте</b>\n"
                f"Номер клиента: {client_number}\n"
                f"Количество платформ: {stats['platforms_count']}\n"
                f"Общее количество отзывов: {stats['total_reviews']}\n"
                f"Согласованных отзывов: {stats['approved_reviews']}\n"
                f"Новых отзывов: {stats['new_reviews']}"
            )
            await callback.message.answer(info_text, reply_markup=get_user_menu_keyboard())
    # Clear any review-related state
    await state.clear()

@router.callback_query(F.data == "add_review")
async def add_review_callback(callback: CallbackQuery, state: FSMContext):
    """Handle adding a new review via bot."""
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    # If platform already selected earlier in state, use it; else ask for platform number
    data = await state.get_data()
    if data.get("platform_number"):
        await callback.message.answer("Введите текст вашего отзыва:")
        await state.set_state(ReviewsStates.WaitingForNewReviewTextAddition)
    else:
        await callback.message.answer("Введите номер платформы, на которую хотите добавить отзыв:")
        await state.set_state(ReviewsStates.WaitingForPlatformAddition)

@router.message(ReviewsStates.WaitingForPlatformAddition)
async def process_platform_addition(message: Message, state: FSMContext):
    """Process platform number for adding a new review."""
    plat_text = message.text.strip() if message.text else ""
    if not plat_text.isdigit():
        await message.answer("Пожалуйста, введите корректный номер платформы (целое число).")
        return
    platform_number = int(plat_text)
    # Save platform number for addition
    await state.update_data(platform_number=platform_number)
    await message.answer("Введите текст вашего отзыва:")
    await state.set_state(ReviewsStates.WaitingForNewReviewTextAddition)

@router.message(ReviewsStates.WaitingForNewReviewTextAddition)
async def process_new_review_text_addition(message: Message, state: FSMContext):
    """Collect the text for the new review and mark it pending insertion."""
    review_text = message.text.strip() if message.text else ""
    if review_text == "":
        await message.answer("Текст отзыва не может быть пустым. Попробуйте снова.")
        return
    data = await state.get_data()
    platform_number = data.get("platform_number")
    # Prepare a new row representation (similar to sheet) but we'll store as pending change
    # Use current timestamp for date
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Mark as pending insert
    pending_change = {
        "action": "insert",
        "new_review": {
            "platform_number": platform_number,
            "date": now_str,
            "review_text": review_text
        },
        "review_text": review_text,
        "client_action": "добавлен (New)"
    }
    # Add to pending_changes in FSM
    data_pending = await state.get_data()
    changes = data_pending.get("pending_changes", [])
    changes.append(pending_change)
    await state.update_data(pending_changes=changes)
    # Notify user that the review is marked for addition
    kb = await get_pending_keyboard(state)
    await message.answer("Ваш отзыв помечен для добавления.", reply_markup=kb)

@router.callback_query(F.data == "approve_all")
async def approve_all_callback(callback: CallbackQuery, state: FSMContext):
    """Mark all listed new reviews as approved (pending changes)."""
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    data = await state.get_data()
    current_reviews = data.get("current_reviews", [])
    platform_number = data.get("platform_number")
    if not platform_number:
        await callback.message.answer("Не удалось определить платформу.")
        return
    # Add pending changes for each review to mark status approved
    changes = data.get("pending_changes", [])
    for rev in current_reviews:
        if rev.get("id") is not None:
            changes.append({
                "action": "update",
                "review_id": rev["id"],
                "field": "status",
                "value": "🟢",
                "review_text": rev.get("pure_text", rev["review_text"]),
                "client_action": "согласован"
            })
    await state.update_data(pending_changes=changes)
    kb = await get_pending_keyboard(state)
    await callback.message.answer("Все отзывы помечены как согласованные.", reply_markup=kb)

@router.callback_query(F.data == "reject_all")
async def reject_all_callback(callback: CallbackQuery, state: FSMContext):
    """Mark all listed new reviews as rejected (pending changes)."""
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    data = await state.get_data()
    current_reviews = data.get("current_reviews", [])
    platform_number = data.get("platform_number")
    if not platform_number:
        await callback.message.answer("Не удалось определить платформу.")
        return
    changes = data.get("pending_changes", [])
    for rev in current_reviews:
        if rev.get("id") is not None:
            changes.append({
                "action": "update",
                "review_id": rev["id"],
                "field": "status",
                "value": "🚫",
                "review_text": rev.get("pure_text", rev["review_text"]),
                "client_action": "отклонен"
            })
    await state.update_data(pending_changes=changes)
    kb = await get_pending_keyboard(state)
    await callback.message.answer("Все отзывы помечены как отклонённые.", reply_markup=kb)

@router.callback_query(F.data == "approve_selected")
async def approve_selected_callback(callback: CallbackQuery, state: FSMContext):
    """Prompt for specific review numbers to approve."""
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    prompt = await callback.message.answer(
        "Введите номера отзывов для согласования через запятую или диапазоны (например, 1,3,5-7):"
    )
    await state.update_data(approve_prompt_id=prompt.message_id)
    await state.set_state(ReviewsStates.ApproveSelected)

@router.message(ReviewsStates.ApproveSelected)
async def process_approve_selected(message: Message, state: FSMContext):
    """Approve specific reviews by their numbers."""
    chat_id = message.chat.id
    data = await state.get_data()
    if data.get("approve_prompt_id"):
        try:
            await message.bot.delete_message(chat_id, data["approve_prompt_id"])
        except:
            pass
    text = message.text or ""
    # Parse input like "1,3,5-7"
    nums = set()
    for part in re.split(r"[,\s]+", text.strip()):
        if '-' in part:
            try:
                start, end = part.split('-')
                for n in range(int(start), int(end)+1):
                    nums.add(n)
            except:
                pass
        elif part.isdigit():
            nums.add(int(part))
    current_reviews = data.get("current_reviews", [])
    changes = data.get("pending_changes", [])
    for n in sorted(nums):
        idx = n - 1
        if 0 <= idx < len(current_reviews):
            rev = current_reviews[idx]
            if rev.get("id") is not None:
                changes.append({
                    "action": "update",
                    "review_id": rev["id"],
                    "field": "status",
                    "value": "🟢",
                    "review_text": rev.get("pure_text", rev["review_text"]),
                    "client_action": "согласован"
                })
    await state.update_data(pending_changes=changes)
    kb = await get_pending_keyboard(state)
    await message.answer("Выбранные отзывы помечены как согласованные.", reply_markup=kb)
    await state.set_state(ReviewsStates.WaitingForMenuAction)

@router.callback_query(F.data == "reject_selected")
async def reject_selected_callback(callback: CallbackQuery, state: FSMContext):
    """Prompt for specific review numbers to reject."""
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    prompt = await callback.message.answer(
        "Введите номера отзывов для отклонения через запятую или диапазоны (например, 1,3,5-7):"
    )
    await state.update_data(reject_prompt_id=prompt.message_id)
    await state.set_state(ReviewsStates.RejectSelected)

@router.message(ReviewsStates.RejectSelected)
async def process_reject_selected(message: Message, state: FSMContext):
    """Reject specific reviews by their numbers."""
    chat_id = message.chat.id
    data = await state.get_data()
    if data.get("reject_prompt_id"):
        try:
            await message.bot.delete_message(chat_id, data["reject_prompt_id"])
        except:
            pass
    text = message.text or ""
    nums = set()
    for part in re.split(r"[,\s]+", text.strip()):
        if '-' in part:
            try:
                start, end = part.split('-')
                for n in range(int(start), int(end)+1):
                    nums.add(n)
            except:
                pass
        elif part.isdigit():
            nums.add(int(part))
    current_reviews = data.get("current_reviews", [])
    changes = data.get("pending_changes", [])
    for n in sorted(nums):
        idx = n - 1
        if 0 <= idx < len(current_reviews):
            rev = current_reviews[idx]
            if rev.get("id") is not None:
                changes.append({
                    "action": "update",
                    "review_id": rev["id"],
                    "field": "status",
                    "value": "🚫",
                    "review_text": rev.get("pure_text", rev["review_text"]),
                    "client_action": "отклонен"
                })
    await state.update_data(pending_changes=changes)
    kb = await get_pending_keyboard(state)
    await message.answer("Выбранные отзывы помечены как отклонённые.", reply_markup=kb)
    await state.set_state(ReviewsStates.WaitingForMenuAction)

@router.callback_query(F.data == "edit_reviews")
async def edit_reviews_callback(callback: CallbackQuery, state: FSMContext):
    """Prompt the user to enter the review number they want to edit."""
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    prompt = await callback.message.answer("Введите номер отзыва, который вы хотите отредактировать:")
    await state.update_data(edit_prompt_id=prompt.message_id)
    await state.set_state(ReviewsStates.WaitingForReviewNumber)

@router.message(ReviewsStates.WaitingForReviewNumber)
async def process_review_number(message: Message, state: FSMContext):
    """Process the review number to edit and prompt for new text."""
    data = await state.get_data()
    chat_id = message.chat.id
    # Remove the edit prompt message if it exists
    if data.get("edit_prompt_id"):
        try:
            await message.bot.delete_message(chat_id, data["edit_prompt_id"])
        except:
            pass
    if not message.text or not message.text.strip().isdigit():
        await message.answer("Пожалуйста, введите корректный номер отзыва (целое число).")
        return
    review_number = int(message.text.strip())
    current_reviews = data.get("current_reviews", [])
    if review_number < 1 or review_number > len(current_reviews):
        await message.answer(f"Отзыв №{review_number} не существует или уже согласован/удалён.")
        return
    # Store index and prompt for new text
    await state.update_data(edit_review_index=review_number - 1)
    await message.answer("Введите новый текст отзыва:")
    await state.set_state(ReviewsStates.WaitingForNewReviewText)

@router.message(ReviewsStates.WaitingForNewReviewText)
async def process_new_review_text(message: Message, state: FSMContext):
    """Receive the new text for the selected review and mark for update."""
    data = await state.get_data()
    idx = data.get("edit_review_index")
    new_text = message.text.strip() if message.text else ""
    if idx is None or new_text == "":
        await message.answer("Ошибка при редактировании. Попробуйте снова.")
        await state.clear()
        return
    current_reviews = data.get("current_reviews", [])
    if not (0 <= idx < len(current_reviews)):
        await message.answer("Отзыв для редактирования не найден.")
        await state.clear()
        return
    rev = current_reviews[idx]
    # Add pending change to update review text
    changes = data.get("pending_changes", [])
    if rev.get("id") is not None:
        changes.append({
            "action": "update",
            "review_id": rev["id"],
            "field": "text",
            "value": new_text,
            "review_text": new_text,
            "client_action": "обновлён"
        })
    await state.update_data(pending_changes=changes)
    kb = await get_pending_keyboard(state)
    await message.answer("Отзыв изменён и помечен для обновления.", reply_markup=kb)
    await state.set_state(ReviewsStates.WaitingForMenuAction)

@router.callback_query(F.data == "add_photos")
async def add_photos_callback(callback: CallbackQuery, state: FSMContext):
    """Initiate adding photos to a selected review."""
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    prompt = await callback.message.answer("Введите номер отзыва, к которому хотите добавить фотографии:")
    await state.update_data(review_number_prompt=prompt.message_id)
    await state.set_state(ReviewsStates.WaitingForReviewNumberForPhotos)

@router.message(ReviewsStates.WaitingForReviewNumberForPhotos)
async def process_review_number_for_photos(message: Message, state: FSMContext):
    """Handle the review number selection for photo attachment."""
    data = await state.get_data()
    chat_id = message.chat.id
    if data.get("review_number_prompt"):
        try:
            await message.bot.delete_message(chat_id, data["review_number_prompt"])
        except:
            pass
    if not message.text or not message.text.strip().isdigit():
        await message.answer("Пожалуйста, введите корректный номер отзыва (целое число).")
        return
    review_number = int(message.text.strip())
    current_reviews = data.get("current_reviews", [])
    if review_number < 1 or review_number > len(current_reviews):
        await message.answer(f"Отзыв №{review_number} не найден или уже обработан.")
        return
    await state.update_data(review_index=review_number - 1, photo_ids=[])
    # Prompt user to send photos
    done_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Готово", callback_data="done_adding_review_photos")],
        [InlineKeyboardButton(text="Отмена", callback_data="continue_editing")]
    ])
    await message.answer(
        "Пришлите все фото для отзыва (по одной или группой). Когда закончите, нажмите «Готово».",
        reply_markup=done_kb
    )
    await state.set_state(ReviewsStates.WaitingForPhotosForReview)

@router.message(ReviewsStates.WaitingForPhotosForReview, F.photo)
async def accumulate_review_photos(message: Message, state: FSMContext):
    """Collect photos sent for attaching to a review."""
    data = await state.get_data()
    photo_ids = data.get("photo_ids", [])
    # Take the highest resolution photo
    file_id = message.photo[-1].file_id
    photo_ids.append(file_id)
    await state.update_data(photo_ids=photo_ids)
    # Notify user that photo is received (schedule a message after 1 sec)
    scheduled_task = data.get("scheduled_review_photo_notification")
    if scheduled_task:
        scheduled_task.cancel()
    async def send_notification():
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            return
        done_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="done_adding_review_photos")],
            [InlineKeyboardButton(text="Отмена", callback_data="continue_editing")]
        ])
        sent_msg = await message.answer(
            "Фото получено. Если хотите добавить ещё фото — присылайте. Когда закончите, нажмите «Готово».",
            reply_markup=done_kb
        )
        await state.update_data(last_review_done_msg_id=sent_msg.message_id)
        data2 = await state.get_data()
        data2.pop("scheduled_review_photo_notification", None)
        await state.set_data(data2)
    task = asyncio.create_task(send_notification())
    await state.update_data(scheduled_review_photo_notification=task)

@router.message(ReviewsStates.WaitingForPhotosForReview, F.document)
async def accumulate_review_photos_document(message: Message, state: FSMContext):
    """Handle image files sent as documents for attaching to a review."""
    doc = message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await message.answer("Ошибка: загруженный файл не является изображением. Пожалуйста, отправьте изображение.")
        return
    data = await state.get_data()
    photo_ids = data.get("photo_ids", [])
    photo_ids.append(doc.file_id)
    await state.update_data(photo_ids=photo_ids)
    # Use the same notification logic as for photo
    scheduled_task = data.get("scheduled_review_photo_notification")
    if scheduled_task:
        scheduled_task.cancel()
    async def send_notification():
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            return
        done_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="done_adding_review_photos")],
            [InlineKeyboardButton(text="Отмена", callback_data="continue_editing")]
        ])
        sent_msg = await message.answer(
            "Фото получено. Если хотите добавить ещё фото — присылайте. Когда закончите, нажмите «Готово».",
            reply_markup=done_kb
        )
        await state.update_data(last_review_done_msg_id=sent_msg.message_id)
        data2 = await state.get_data()
        data2.pop("scheduled_review_photo_notification", None)
        await state.set_data(data2)
    task = asyncio.create_task(send_notification())
    await state.update_data(scheduled_review_photo_notification=task)

@router.callback_query(F.data == "done_adding_review_photos")
async def finish_adding_review_photos(callback: CallbackQuery, state: FSMContext):
    """Finalize adding photos to a review: upload to Drive and mark pending update."""
    await callback.answer()
    data = await state.get_data()
    chat_id = callback.message.chat.id
    # Clear intermediate messages
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    # If no photos were sent
    photo_ids = data.get("photo_ids", [])
    if not photo_ids:
        await callback.message.answer("Вы не отправили ни одной фотографии.")
        # Return to menu without clearing pending changes
        await state.set_state(ReviewsStates.WaitingForMenuAction)
        return
    init_msg = await callback.message.answer("Фотографии инициализируются, ожидайте...")
    current_reviews = data.get("current_reviews", [])
    review_index = data.get("review_index")
    if review_index is None or review_index < 0 or review_index >= len(current_reviews):
        await init_msg.edit_text("Неверный номер отзыва или отзыв уже не доступен.")
        return
    rev = current_reviews[review_index]
    review_id = None
    if rev.get("id") is not None:
        review_id = rev["id"]
    else:
        await init_msg.edit_text("Ошибка: отзыв для добавления фото не найден.")
        return
    # Check if a Drive folder already exists for this review (by checking existing photo_link in DB)
    from database import pool
    folder_id = None
    folder_link = None
    async with pool.acquire() as conn:
        result = await conn.fetchrow("SELECT photo_link FROM reviews WHERE id=$1;", review_id)
        if result:
            existing_link = result["photo_link"]
            if existing_link and "drive.google.com" in existing_link:
                # Extract folder ID from link
                parts = existing_link.split("/")
                folder_id = parts[-1] if parts else None
                folder_link = existing_link
    # Initialize Google Drive service
    from google_sheets import drive_service
    if not folder_id:
        # Create a new folder on Google Drive for this review
        folder_metadata = {
            "name": f"review_{review_index+1}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [callback.bot['drive_folder_id']]
        }
        try:
            folder = drive_service.files().create(body=folder_metadata, fields="id").execute()
            folder_id = folder.get("id")
            drive_service.permissions().create(fileId=folder_id, body={"role": "reader", "type": "anyone"}).execute()
            folder_link = f"https://drive.google.com/drive/folders/{folder_id}"
        except Exception as e:
            await init_msg.edit_text(f"Ошибка при создании папки на Google Диске: {str(e)}")
            return
    # Upload each photo to the Drive folder
    error_messages = []
    for idx, file_id in enumerate(photo_ids, start=1):
        try:
            file_info = await callback.message.bot.get_file(file_id)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
                tmp_name = tmp_file.name
                await callback.message.bot.download_file(file_info.file_path, tmp_name)
            file_name = f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            file_metadata = {"name": file_name, "mimeType": "image/jpeg", "parents": [folder_id]}
            media = MediaFileUpload(tmp_name, mimetype="image/jpeg")
            drive_service.files().create(body=file_metadata, media_body=media, fields="id").execute()
            # Remove temp file
            import os as _os
            if _os.path.exists(tmp_name):
                _os.remove(tmp_name)
        except Exception as e:
            error_messages.append(
                f"Ошибка при загрузке фото №{idx} (ID: {file_id}). Техническая информация: {str(e)}"
            )
    # Add pending change to mark the review as approved with photo link
    changes = data.get("pending_changes", [])
    changes.append({
        "action": "update_multiple",
        "review_id": review_id,
        "updates": { "status": "🟢", "photo_link": folder_link },
        "review_text": rev.get("pure_text", rev["review_text"]),
        "client_action": "Фото добавлено"
    })
    await state.update_data(pending_changes=changes, photo_ids=[])
    # Delete init message
    try:
        await init_msg.delete()
    except:
        pass
    # Notify result
    if error_messages:
        full_error = "\n\n".join(error_messages)
        await callback.message.answer(f"Не все фотографии были успешно загружены:\n{full_error}")
    else:
        await callback.message.answer("Фотографии успешно добавлены к отзыву.")
    # Show pending actions keyboard (now user can send report to save)
    kb = await get_pending_keyboard(state)
    await callback.message.answer("Что дальше?", reply_markup=kb)
    await state.set_state(ReviewsStates.WaitingForMenuAction)

@router.callback_query(F.data == "continue_editing")
async def continue_editing_callback(callback: CallbackQuery, state: FSMContext):
    """Continue editing (dismiss the send report prompt without saving yet)."""
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    # Simply return to waiting for menu action state (pending changes remain)
    await state.set_state(ReviewsStates.WaitingForMenuAction)

@router.callback_query(F.data == "save_changes")
async def save_changes_callback(callback: CallbackQuery, state: FSMContext):
    """Finalize all pending changes: apply to database and show summary."""
    await callback.answer()
    chat_id = callback.message.chat.id
    # Clear any menus
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    data = await state.get_data()
    pending = data.get("pending_changes", [])
    if not pending:
        await callback.message.answer("Нет внесенных изменений.")
        await state.clear()
        return
    # Apply each pending change to the database
    changes_lines = []
    for change in pending:
        action = change.get("action")
        if action == "insert":
            # Insert new review to DB (status pending)
            new_review = change.get("new_review", {})
            plat_num = new_review.get("platform_number")
            text = new_review.get("review_text", "")
            date_str = new_review.get("date", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            # Determine platform_id
            client_id = data.get("client_id")
            platform_id = await get_platform_id(client_id, plat_num)
            if platform_id:
                from database import create_review
                await create_review(client_id, platform_id, text, date_str, "", "pending", None)
            changes_lines.append(f"🆕 {text} - добавлен (New)")
        elif action == "update":
            # Update a single field (status or text)
            review_id = change.get("review_id")
            val = change.get("value")
            if review_id:
                if val in ["🟢", "🚫"]:
                    # Update status in DB
                    new_status = "approved" if val == "🟢" else "rejected"
                    await update_review_status(review_id, new_status)
                    marker = "🟢" if val == "🟢" else "🔴"
                    changes_lines.append(f"{marker} {change.get('review_text', '')} - {change.get('client_action', '')}")
                else:
                    # Update review text
                    await update_review_text(review_id, val)
                    changes_lines.append(f"✏️ {change.get('review_text', '')} - обновлён")
        elif action == "update_multiple":
            # Update status and photo_link for a review (photo added)
            review_id = change.get("review_id")
            updates = change.get("updates", {})
            if review_id:
                # Set status approved and photo_link
                link = updates.get("photo_link")
                await update_review_photo(review_id, link or "")
                changes_lines.append(f"📷 {change.get('review_text', '')} - Фото добавлено")
    # Clear pending changes from state
    await state.update_data(pending_changes=[])
    # Show summary of changes
    if changes_lines:
        summary = "Измененные отзывы:\n" + "\n".join(changes_lines)
    else:
        summary = "Нет внесенных изменений."
    await callback.message.answer(summary, parse_mode="HTML")
    await callback.message.answer("Изменения сохранены. Возвращение в главное меню...")
    # Return to main menu
    from handlers.auth import start_command  # call start to show menu
    await start_command(types.Message(chat=types.Chat(id=chat_id, type='private'), text="/start"), state)

@router.message(Command("stats"))
async def stats_command(message: types.Message, state: FSMContext):
    """Allow user to view their statistics with /stats command."""
    data = await state.get_data()
    client_id = data.get("client_id")
    client_number = data.get("client_number")
    if not client_id:
        from database import get_authorized_client_by_chat
        client_rec = await get_authorized_client_by_chat(message.chat.id)
        if client_rec:
            client_id = client_rec["id"]
            client_number = client_rec["number"]
            await state.update_data(client_id=client_id, client_number=client_number)
    if not client_id:
        await message.answer("Вы не авторизованы. Используйте /start для начала работы.")
        return
    stats = await get_client_stats(client_id)
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
    await message.answer(info_text, reply_markup=get_user_menu_keyboard())

@router.message(Command("exit"))
async def exit_command(message: types.Message, state: FSMContext):
    """Handle the /exit command to log out the user."""
    chat_id = message.chat.id
    data = await state.get_data()
    client_id = data.get("client_id")
    if client_id:
        await unauthorize_client(client_id)
    await state.clear()
    await message.answer("Сессия завершена. Используйте /start для новой авторизации.")
