import os
import re
import asyncio
import html
from datetime import datetime  # Добавлено для работы с датой
from google.oauth2.service_account import Credentials
import gspread
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from tenacity import retry, stop_after_attempt, wait_exponential

# Импортируем необходимые функции и переменную pool из database.py
from database import pool, create_platform, update_review_status, update_review_text

# Globals for Google API clients
credentials = None
gspread_client = None
drive_service = None
sheets_cache = {}  # Cache for opened Google Spreadsheet objects by ID

# Spreadsheet ID environment variables (expected as SPREADSHEET_ID_1, 2, 3, ...)
spreadsheet_ids = []
def init_google_services():
    """Initialize Google Sheets and Drive services using service account credentials."""
    global credentials, gspread_client, drive_service, spreadsheet_ids
    # Gather spreadsheet IDs from environment (e.g., SPREADSHEET_ID_1, _2, _3)
    idx = 1
    while True:
        key = f"SPREADSHEET_ID_{idx}"
        val = os.getenv(key)
        if not val:
            break
        spreadsheet_ids.append(val)
        idx += 1
    # Ensure we have at least one spreadsheet ID
    if not spreadsheet_ids:
        raise ValueError("No Google Spreadsheet IDs provided in environment variables.")
    # Google API scopes
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    # Load service account credentials from file
    credentials = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    # Initialize gspread client and Google Drive service
    gspread_client = gspread.authorize(credentials)
    drive_service = build("drive", "v3", credentials=credentials)

@retry(stop=stop_after_attempt(5), wait=wait_exponential(min=4, max=10))
def connect_to_sheet(sheet_id: str):
    """Open a Google Spreadsheet by ID, with retries on failure."""
    if sheet_id in sheets_cache:
        return sheets_cache[sheet_id]
    # Authorize and open spreadsheet
    sheet_obj = gspread_client.open_by_key(sheet_id)
    sheets_cache[sheet_id] = sheet_obj
    return sheet_obj

def get_client_spreadsheet(client_number: int):
    """Determine which Google Spreadsheet file contains the given client number."""
    # Map ranges: 1-99 -> first spreadsheet, 100-199 -> second, 200-299 -> third
    if 1 <= client_number <= 99:
        idx = 0
    elif 100 <= client_number <= 199:
        idx = 1
    elif 200 <= client_number <= 299:
        idx = 2
    else:
        return None
    if idx < len(spreadsheet_ids):
        return connect_to_sheet(spreadsheet_ids[idx])
    return None

def find_client_sheet(client_number: int):
    """Find the worksheet for a specific client by their number."""
    ss = get_client_spreadsheet(client_number)
    if not ss:
        return None
    title_str = f"Клиент {client_number}"
    try:
        # Try to open worksheet by exact title
        return ss.worksheet(title_str)
    except gspread.exceptions.WorksheetNotFound:
        # Fallback: find by iterating (case-insensitive match)
        for ws in ss.worksheets():
            if ws.title.strip().lower() == title_str.lower():
                return ws
    return None

def get_platforms_from_sheet(worksheet):
    """Extract platform links from the top of a client's worksheet."""
    platforms = {}
    all_rows = worksheet.get_all_values()
    count = 1
    # Check first 10 rows and first 6 columns for URLs
    for r in range(min(10, len(all_rows))):
        row = all_rows[r]
        for c in range(6):
            if c < len(row):
                cell = row[c].strip()
                # If cell contains a valid URL, assign it to "ПЛАТФОРМА {count}"
                if cell and (cell.startswith("http://") or cell.startswith("https://")):
                    platforms[f"ПЛАТФОРМА {count}"] = cell
                    count += 1
    return platforms

def get_platform_reviews_from_sheet(worksheet):
    """Read all review entries from the worksheet, grouped by platform."""
    reviews = {}
    rows = worksheet.get_all_values()
    current_platform = None
    for row in rows:
        if row and row[0].strip().upper().startswith("ПЛАТФОРМА"):
            current_platform = row[0].strip().upper()
            reviews[current_platform] = []
        elif current_platform:
            # Only consider rows that have a review text (at least 5 columns and 5th column not empty)
            if len(row) > 4 and row[4].strip():
                reviews[current_platform].append(row)
    return reviews

def get_platform_insertion_index(worksheet, platform_key: str):
    """Determine the row index at which to insert a new entry under a given platform section."""
    all_rows = worksheet.get_all_values()
    start_index = None
    for i, row in enumerate(all_rows, start=1):
        if row and row[0].strip().upper() == platform_key:
            start_index = i
            break
    if start_index is None:
        # Platform label not found, insert at end
        return len(all_rows) + 1
    insert_index = start_index + 1
    for j in range(start_index + 1, len(all_rows) + 1):
        if j <= len(all_rows):
            cell_value = worksheet.cell(j, 1).value
        else:
            cell_value = None
        if cell_value and cell_value.strip().upper().startswith("ПЛАТФОРМА") and cell_value.strip().upper() != platform_key:
            insert_index = j
            break
        else:
            insert_index = j + 1
    return insert_index

async def import_initial_data():
    """Import clients, platforms, and reviews from Google Sheets into the database on first run."""
    from database import create_client, create_platform, create_review  # import here to avoid circular dependency
    for sheet_id in spreadsheet_ids:
        sheet_obj = connect_to_sheet(sheet_id)
        for worksheet in sheet_obj.worksheets():
            title = worksheet.title.strip()
            # We consider worksheets titled like "Клиент X" as client sheets
            match = re.match(r"Клиент\s+(\d+)", title, re.IGNORECASE)
            if not match:
                continue
            client_number = int(match.group(1))
            # Create client with a placeholder password if not exists in DB
            client_record = await create_client(client_number, "")  # password set empty (to be updated by admin)
            client_id = client_record  # create_client returns new client_id
            # Import platforms
            platforms = get_platforms_from_sheet(worksheet)
            platform_id_map = {}
            for plat_key, url in platforms.items():
                # Extract platform number from key "ПЛАТФОРМА X"
                m = re.search(r"(\d+)", plat_key)
                if not m:
                    continue
                plat_num = int(m.group(1))
                platform_id = await create_platform(client_id, plat_num, url)
                platform_id_map[plat_num] = platform_id
            # Import reviews for each platform section
            reviews_by_platform = get_platform_reviews_from_sheet(worksheet)
            for plat_key, rows in reviews_by_platform.items():
                m = re.search(r"ПЛАТФОРМА\s+(\d+)", plat_key, re.IGNORECASE)
                if not m:
                    continue
                plat_num = int(m.group(1))
                platform_id = platform_id_map.get(plat_num)
                if platform_id is None:
                    # If platform link was not in top section, create platform without URL
                    platform_id = await create_platform(client_id, plat_num, None)
                    platform_id_map[plat_num] = platform_id
                for row in rows:
                    # row format: [ (maybe empty colA), date, manager_comment, status, review_text, photo_link, ... ]
                    date_str = row[1].strip() if len(row) > 1 else ""
                    manager_comment = row[2].strip() if len(row) > 2 else ""
                    status_cell = row[3].strip() if len(row) > 3 else ""
                    review_text = row[4].strip() if len(row) > 4 else ""
                    photo_link = row[5].strip() if len(row) > 5 else ""
                    # Determine status value
                    if manager_comment != "" and status_cell == "":
                        # Manager responded but status not set, treat as approved
                        status = "approved"
                    elif status_cell in ("🟢", "Согласован"):
                        status = "approved"
                    elif status_cell in ("🚫", "Отклонен"):
                        status = "rejected"
                    elif status_cell == "⚠️":
                        status = "pending"
                    else:
                        status = "new"
                    # Insert review into database
                    await create_review(client_id, platform_id, review_text, date_str, manager_comment, status, photo_link or None)
    print("Initial data import from Google Sheets completed.")

async def sync_with_google():
    """Continuous synchronization: add new reviews, update status changes, and export new bot entries to Google Sheets every minute."""
    from database import (get_platforms_with_new_counts, get_new_reviews, get_client_by_number,
                          get_authorized_client_by_chat, get_unsynced_photo_packs,
                          mark_photo_pack_synced, create_review)  # avoid circular imports at top
    # Structures to track notification state
    last_count_per_platform = {}   # {(client_id, platform_id): last_new_count}
    pending_notifications = {}    # {(client_id, platform_id): {"timestamp": time, "diff": diff}}
    while True:
        # Sync every 60 seconds
        await asyncio.sleep(60)
        # Synchronize data for each client in Google Sheets
        for sheet_id in spreadsheet_ids:
            sheet_obj = None
            try:
                sheet_obj = connect_to_sheet(sheet_id)
            except Exception:
                continue  # if sheet not accessible, skip this iteration
            for worksheet in sheet_obj.worksheets():
                title = worksheet.title.strip()
                match = re.match(r"Клиент\s+(\d+)", title, re.IGNORECASE)
                if not match:
                    continue
                client_number = int(match.group(1))
                # Check if client exists in DB
                client_row = await get_client_by_number(client_number)
                if not client_row:
                    continue
                client_id = client_row["id"]
                # Fetch platform data from sheet and DB
                sheet_platforms = get_platforms_from_sheet(worksheet)
                reviews_by_platform = get_platform_reviews_from_sheet(worksheet)
                # Ensure all platforms from sheet exist in DB
                platform_ids = {}
                for plat_key, url in sheet_platforms.items():
                    m = re.search(r"(\d+)", plat_key)
                    if not m:
                        continue
                    plat_num = int(m.group(1))
                    # Find or create platform in DB
                    async with pool.acquire() as conn:
                        platform_id = await conn.fetchval(
                            "SELECT id FROM platforms WHERE client_id=$1 AND number=$2;",
                            client_id, plat_num
                        )
                        if not platform_id:
                            platform_id = await conn.fetchval(
                                "INSERT INTO platforms(client_id, number, url) VALUES($1, $2, $3) RETURNING id;",
                                client_id, plat_num, url
                            )
                    platform_ids[plat_num] = platform_id
                # Now synchronize reviews:
                # Build sets for sheet and DB reviews for comparison
                sheet_review_set = set()
                sheet_reviews_data = {}  # map (plat_num, text, date) -> (status, manager_comment, photo_link)
                for plat_key, rows in reviews_by_platform.items():
                    m = re.search(r"ПЛАТФОРМА\s+(\d+)", plat_key, re.IGNORECASE)
                    if not m:
                        continue
                    plat_num = int(m.group(1))
                    platform_id = platform_ids.get(plat_num)
                    if platform_id is None:
                        # Create platform if missing
                        platform_id = await create_platform(client_id, plat_num, None)
                        platform_ids[plat_num] = platform_id
                    for row in rows:
                        date_str = row[1].strip() if len(row) > 1 else ""
                        manager_comment = row[2].strip() if len(row) > 2 else ""
                        status_cell = row[3].strip() if len(row) > 3 else ""
                        review_text = row[4].strip() if len(row) > 4 else ""
                        photo_link = row[5].strip() if len(row) > 5 else ""
                        # Determine sheet status in terms of DB values
                        if manager_comment != "" and status_cell == "":
                            sheet_status = "approved"
                        elif status_cell in ("🟢", "Согласован"):
                            sheet_status = "approved"
                        elif status_cell in ("🚫", "Отклонен"):
                            sheet_status = "rejected"
                        elif status_cell == "⚠️":
                            sheet_status = "pending"
                        else:
                            sheet_status = "new"
                        # Only consider actual review entries with text
                        if review_text:
                            key = (plat_num, review_text, date_str)
                            sheet_review_set.add(key)
                            sheet_reviews_data[key] = (sheet_status, manager_comment, photo_link)
                # Fetch all reviews from DB for this client
                async with pool.acquire() as conn:
                    db_rows = await conn.fetch("""
                        SELECT p.number as plat_num, r.review_text, r.review_date, r.manager_comment, r.status, r.photo_link
                        FROM reviews r 
                        JOIN platforms p ON r.platform_id = p.id
                        WHERE r.client_id=$1;
                    """, client_id)
                db_review_set = set()
                db_reviews_data = {}
                for r in db_rows:
                    plat_num = r["plat_num"]
                    text = r["review_text"]
                    date_str = r["review_date"] or ""
                    status = r["status"]
                    m_comment = r["manager_comment"] or ""
                    photo_link = r["photo_link"] or ""
                    key = (plat_num, text, date_str)
                    db_review_set.add(key)
                    db_reviews_data[key] = (status, m_comment, photo_link)
                # Find new reviews in sheet (to add to DB)
                new_sheet_reviews = sheet_review_set - db_review_set
                for key in new_sheet_reviews:
                    plat_num, text, date_str = key
                    sheet_status, m_comment, photo_link = sheet_reviews_data.get(key, ("new", "", ""))
                    platform_id = platform_ids.get(plat_num)
                    # Insert into DB
                    await create_review(client_id, platform_id, text, date_str, m_comment, sheet_status, photo_link or None)
                # Find reviews added via bot that need exporting to sheet
                new_bot_reviews = db_review_set - sheet_review_set
                for key in new_bot_reviews:
                    plat_num, text, date_str = key
                    status, m_comment, photo_link = db_reviews_data.get(key, (None, "", ""))
                    # Only export those that are pending or new in DB (i.e., likely added via bot)
                    if status in ("pending", "new"):
                        platform_id = platform_ids.get(plat_num)
                        platform_label = f"ПЛАТФОРМА {plat_num}".upper()
                        # Determine insertion row index in sheet for this platform section
                        insert_idx = get_platform_insertion_index(worksheet, platform_label)
                        # Compose row values
                        # If added via bot, mark as "Внесено клиентом" with ⚠️ status
                        new_row = [
                            "Внесено клиентом",
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "",
                            "⚠️",
                            text,
                            photo_link or ""
                        ]
                        try:
                            worksheet.insert_row(new_row, index=insert_idx)
                        except Exception as e:
                            print(f"Error exporting review to sheet for client {client_number}: {e}")
                        # (We keep status in DB as pending; admin can handle it later)
                # Reflect status changes from sheet to DB
                for key in sheet_review_set.intersection(db_review_set):
                    sheet_status, sheet_m_comment, sheet_photo = sheet_reviews_data.get(key, (None, "", ""))
                    db_status, db_m_comment, db_photo = db_reviews_data.get(key, (None, "", ""))
                    if not sheet_status or not db_status:
                        continue
                    # If status on sheet is now approved or rejected, update DB if it was new/pending
                    if sheet_status in ("approved", "rejected") and db_status in ("new", "pending"):
                        # Find the review ID in DB
                        plat_num, text, date_str = key
                        platform_id = platform_ids.get(plat_num)
                        async with pool.acquire() as conn:
                            review_id = await conn.fetchval("""
                                SELECT r.id FROM reviews r 
                                JOIN platforms p ON r.platform_id=p.id
                                WHERE r.client_id=$1 AND p.number=$2 AND r.review_text=$3 AND COALESCE(r.review_date, '')=$4;
                            """, client_id, plat_num, text, date_str)
                        if review_id:
                            new_status_val = "approved" if sheet_status == "approved" else "rejected"
                            await update_review_status(review_id, new_status_val)
                            # If manager comment exists and we had none, update that too (optional, for record)
                            if sheet_m_comment and not db_m_comment:
                                async with pool.acquire() as conn:
                                    await conn.execute(
                                        "UPDATE reviews SET manager_comment=$1 WHERE id=$2;",
                                        sheet_m_comment, review_id
                                    )
                    # If a manager comment is present on sheet and DB status still 'new', mark as approved
                    if sheet_status == "approved" and db_status == "new":
                        plat_num, text, date_str = key
                        platform_id = platform_ids.get(plat_num)
                        async with pool.acquire() as conn:
                            review_id = await conn.fetchval("""
                                SELECT r.id FROM reviews r 
                                JOIN platforms p ON r.platform_id=p.id
                                WHERE r.client_id=$1 AND p.number=$2 AND r.review_text=$3 AND COALESCE(r.review_date, '')=$4;
                            """, client_id, plat_num, text, date_str)
                        if review_id:
                            await update_review_status(review_id, "approved")
                # Handle any unsynced photo packs for this client
                packs = await get_unsynced_photo_packs(client_id)
                for pack in packs:
                    pack_id = pack["id"]
                    platform_id = pack["platform_id"]
                    folder_link = pack["folder_link"]
                    # Determine platform number from platform_id
                    plat_num = None
                    for num, pid in platform_ids.items():
                        if pid == platform_id:
                            plat_num = num
                            break
                    if plat_num is None:
                        # Fetch platform number from DB if not in map
                        async with pool.acquire() as conn:
                            plat_num = await conn.fetchval(
                                "SELECT number FROM platforms WHERE id=$1;", platform_id
                            )
                    platform_label = f"ПЛАТФОРМА {plat_num}".upper() if plat_num is not None else None
                    if platform_label:
                        insert_idx = get_platform_insertion_index(worksheet, platform_label)
                    else:
                        insert_idx = len(worksheet.get_all_values()) + 1
                    pack_row = [
                        "Добавленный ПАК с фото клиентом для всей платформы",
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "", "", "", folder_link
                    ]
                    try:
                        worksheet.insert_row(pack_row, index=insert_idx)
                        await mark_photo_pack_synced(pack_id)
                    except Exception as e:
                        print(f"Error syncing photo pack for client {client_number}: {e}")
        # After syncing data, handle notification checks for authorized clients
        async with pool.acquire() as conn:
            auth_clients = await conn.fetch("SELECT id, number, telegram_id FROM clients WHERE authorized=True;")
        for client in auth_clients:
            client_id = client["id"]
            chat_id = client["telegram_id"]
            # Get current count of new reviews per platform from DB
            new_counts = {}
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT platform_id, COUNT(*) AS cnt 
                    FROM reviews WHERE client_id=$1 AND status='new'
                    GROUP BY platform_id;
                """, client_id)
            for r in rows:
                new_counts[r["platform_id"]] = r["cnt"]
            # For each platform of this client
            for platform_id, new_count in new_counts.items():
                key = (client_id, platform_id)
                last_count = last_count_per_platform.get(key, 0)
                diff = new_count - last_count
                if diff > 0:
                    pending = pending_notifications.get(key)
                    current_time = asyncio.get_event_loop().time()
                    if not pending:
                        pending_notifications[key] = {"timestamp": current_time, "diff": diff}
                    else:
                        # Update diff if more new reviews
                        pending["diff"] = diff
                        # If 10 minutes have passed since first detection, send notification
                        if current_time - pending["timestamp"] >= 600:
                            updated_diff = diff
                            if updated_diff > 0:
                                # Determine platform number or name for message
                                plat_num = None
                                async with pool.acquire() as conn:
                                    plat_num = await conn.fetchval(
                                        "SELECT number FROM platforms WHERE id=$1;", platform_id
                                    )
                                platform_label = f"ПЛАТФОРМА {plat_num}" if plat_num else "платформе"
                                # Send notification to client
                                try:
                                    from main import bot  # import bot for sending
                                    await bot.send_message(
                                        chat_id,
                                        f"На {platform_label} появилось {updated_diff} новых отзывов.",
                                        disable_web_page_preview=True,
                                        reply_markup=None
                                    )
                                except Exception as e:
                                    print(f"Failed to send notification to client {client_id}: {e}")
                                # Clear pending and update last count
                                pending_notifications.pop(key, None)
                                last_count_per_platform[key] = new_count
                else:
                    # No new reviews or negative diff => clear pending if any
                    if (client_id, platform_id) in pending_notifications:
                        pending_notifications.pop(key, None)
                    last_count_per_platform[key] = new_count
