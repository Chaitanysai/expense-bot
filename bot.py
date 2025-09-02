import os
import json
import datetime
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)
from google.oauth2 import service_account
from googleapiclient.discovery import build
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ======================
# Config
# ======================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
service_account_info = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))
CHAT_ID = int(os.getenv("CHAT_ID", "1133284028"))  # your chat id

creds = service_account.Credentials.from_service_account_info(
    service_account_info,
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)
service = build("sheets", "v4", credentials=creds)
sheet = service.spreadsheets()

# ======================
# Budget Allocations (₹ per month)
# ======================
CATEGORY_BUDGETS = {
    "🚗 EMI – Bike Loan": 6500,
    "🛒 Groceries": 9000,
    "📑 Utilities": 3000,
    "🏍️ Bike Fuel": 2000,
    "💊 Healthcare": 2000,
    "💰 Savings": 12000,
    "📈 Investments": 12000,
    "🍱 Lifestyle": 6000,
    "Others": 2500,  # Changed from Buffer
}

# ======================
# Category Auto-detect
# ======================
CATEGORY_KEYWORDS = {
    "fuel": "🏍️ Bike Fuel",
    "petrol": "🏍️ Bike Fuel",
    "grocery": "🛒 Groceries",
    "groceries": "🛒 Groceries",
    "food": "🍱 Lifestyle",
    "dining": "🍱 Lifestyle",
    "emi": "🚗 EMI – Bike Loan",
    "loan": "🚗 EMI – Bike Loan",
    "bill": "📑 Utilities",
    "electricity": "📑 Utilities",
    "internet": "📑 Utilities",
    "insurance": "💊 Healthcare",
    "medicine": "💊 Healthcare",
    "health": "💊 Healthcare",
    "save": "💰 Savings",
    "invest": "📈 Investments",
    "mutual": "📈 Investments",
    "sip": "📈 Investments",
    "shop": "🍱 Lifestyle",
    "others": "Others", # Changed from Buffer
}


def detect_category(text: str) -> str:
    text = text.lower()
    for key, category in CATEGORY_KEYWORDS.items():
        if key in text:
            return category
    return "Others"  # Changed from Buffer


# ======================
# Bot Handlers
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message with interactive buttons."""
    keyboard = [
        [
            InlineKeyboardButton("📊 Budget Status", callback_data="view_budget"),
            InlineKeyboardButton("📈 Category View", callback_data="view_category"),
        ],
        [
            InlineKeyboardButton("📋 List Recent", callback_data="list_recent"),
            InlineKeyboardButton("❓ Help", callback_data="help"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Hi! I'm your personal finance assistant.", reply_markup=reply_markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends help text."""
    help_text = (
        "Send me expenses like:\n"
        "`250 groceries dinner`\n\n"
        "If you don’t include a date, I’ll use today.\n"
        "Use /summary for weekly report.\n"
        "Type 'Total' anytime to get lifetime spend.\n"
        "Use /list to see logs, /remove <row> to delete.\n"
        "Use the buttons or /budget to see budget usage."
    )
    await update.message.reply_text(help_text)


async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()

        if text.lower() == "total":
            return await total(update, context)

        parts = text.split()

        # Parse date if provided, else use today
        try:
            expense_date = datetime.datetime.strptime(
                parts[0], "%d-%b-%Y"
            ).strftime("%d-%b-%Y")
            amount = float(parts[1])
            notes = " ".join(parts[2:])
        except ValueError:
            expense_date = datetime.datetime.now().strftime("%d-%b-%Y")
            amount = float(parts[0])
            notes = " ".join(parts[1:])

        category = detect_category(notes)
        expense_type = (
            "Fixed" if "EMI" in category or "Loan" in category else "Variable"
        )

        # Get current row count to determine the new row number
        result = (
            sheet.values()
            .get(spreadsheetId=SPREADSHEET_ID, range="Transactions!A:A")
            .execute()
        )
        num_rows = len(result.get("values", []))
        new_row_number = num_rows + 1

        values = [[expense_date, amount, category, expense_type, notes]]
        sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="Transactions!A:E",
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()

        msg = f"✅ Added: ₹{amount:.0f} under {category} ({expense_type})"

        # --- NEW: Add interactive button to change category ---
        keyboard = [
            [
                InlineKeyboardButton(
                    "✏️ Change Category",
                    callback_data=f"edit_category_prompt_{new_row_number}",
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Budget check (can be combined with the message)
        if category in CATEGORY_BUDGETS:
            spent = get_category_total(category)
            budget = CATEGORY_BUDGETS[category]
            percent = (spent / budget) * 100
            if percent >= 100:
                msg += f"\n🔴 ALERT: {category} budget exceeded! (₹{spent:.0f} / ₹{budget})"
            elif percent >= 80:
                msg += f"\n⚠️ Warning: {category} at {percent:.0f}% of budget (₹{spent:.0f} / ₹{budget})"

        await update.message.reply_text(msg, reply_markup=reply_markup)

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {str(e)}")


def get_category_total(category: str) -> float:
    """Fetch total spent for a category from the sheet."""
    result = (
        sheet.values()
        .get(spreadsheetId=SPREADSHEET_ID, range="Transactions!A:E")
        .execute()
    )
    rows = result.get("values", [])[1:]
    total = 0
    for row in rows:
        if len(row) >= 3 and row[2] == category:
            try:
                total += float(str(row[1]).replace("₹", "").replace(",", ""))
            except:
                continue
    return total


# ======================
# Button Callback Handler (NEW)
# ======================
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query
    await query.answer()  # Acknowledge the button press

    data = query.data

    if data.startswith("edit_category_prompt_"):
        row_number = data.split("_")[-1]
        keyboard = []
        # Create a button for each category
        for category_name in CATEGORY_BUDGETS.keys():
            button = InlineKeyboardButton(
                category_name,
                callback_data=f"changecat_{row_number}_{category_name}",
            )
            keyboard.append([button])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text="Which category should it be?", reply_markup=reply_markup
        )

    elif data.startswith("changecat_"):
        _, row_number, new_category = data.split("_", 2)
        range_to_update = f"Transactions!C{row_number}"

        # Update the category in the Google Sheet
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_to_update,
            valueInputOption="USER_ENTERED",
            body={"values": [[new_category]]},
        ).execute()

        await query.edit_message_text(text=f"✅ Category updated to: {new_category}")

    elif data == "view_budget":
        # We can call the existing budget function but need to send the message via the query
        await budget(update, context, query=query)

    elif data == "view_category":
        await category_summary(update, context, query=query)

    elif data == "list_recent":
        await list_entries(update, context, query=query)
    
    elif data == "help":
        help_text = (
            "Send me expenses like:\n"
            "`250 groceries dinner`\n\n"
            "To add a date: `dd-mon-yyyy <amount> <notes>`\n"
            "e.g., `01-Sep-2025 500 petrol`\n\n"
            "Use the buttons or commands to navigate."
        )
        await query.message.reply_text(help_text)


# ======================
# /budget command
# ======================
async def budget(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    try:
        result = (
            sheet.values()
            .get(spreadsheetId=SPREADSHEET_ID, range="Transactions!A:E")
            .execute()
        )
        rows = result.get("values", [])[1:]

        category_totals = {}
        for row in rows:
            if len(row) >= 3:
                category = row[2]
                try:
                    amt = float(str(row[1]).replace("₹", "").replace(",", ""))
                    category_totals[category] = category_totals.get(category, 0) + amt
                except:
                    continue

        msg = "📊 *Category-wise Budget Status:*\n\n"
        total_spent = 0
        total_budget = 0

        for cat, budget_amt in CATEGORY_BUDGETS.items():
            spent = category_totals.get(cat, 0)
            total_spent += spent
            total_budget += budget_amt
            percent = (spent / budget_amt) * 100 if budget_amt > 0 else 0
            status = "✅"
            if percent >= 100:
                status = "🔴"
            elif percent >= 80:
                status = "⚠️"
            msg += f"{status} {cat}: ₹{spent:,.0f} / ₹{budget_amt:,.0f} ({percent:.0f}%)\n"
        
        msg += f"\n*Overall: ₹{total_spent:,.0f} / ₹{total_budget:,.0f}*"

        # Send message via query if it's from a button, else reply normally
        if query:
            await query.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        error_msg = f"⚠️ Error fetching budget: {str(e)}"
        if query:
            await query.message.reply_text(error_msg)
        else:
            await update.message.reply_text(error_msg)


# ======================
# /category command (NEW)
# ======================
async def category_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    try:
        result = (
            sheet.values()
            .get(spreadsheetId=SPREADSHEET_ID, range="Transactions!A:E")
            .execute()
        )
        rows = result.get("values", [])[1:]

        category_totals = {}
        for row in rows:
            if len(row) >= 3:
                category = row[2]
                try:
                    amt = float(str(row[1]).replace("₹", "").replace(",", ""))
                    category_totals[category] = category_totals.get(category, 0) + amt
                except:
                    continue

        msg = "📊 *Category Spending & Remaining Budget:*\n\n"
        
        for cat, budget_amt in CATEGORY_BUDGETS.items():
            spent = category_totals.get(cat, 0)
            remaining = budget_amt - spent
            
            percent = (spent / budget_amt) * 100 if budget_amt > 0 else 0
            status = "✅"
            if percent >= 100:
                status = "🔴"
            elif percent >= 80:
                status = "⚠️"

            msg += f"{status} *{cat}*\n"
            msg += f"  - Spent:     ₹{spent:,.0f}\n"
            msg += f"  - Remaining: ₹{remaining:,.0f}\n\n"

        if query:
            await query.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        error_msg = f"⚠️ Error fetching category summary: {str(e)}"
        if query:
            await query.message.reply_text(error_msg)
        else:
            await update.message.reply_text(error_msg)


# ======================
# /list command
# ======================
async def list_entries(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    try:
        result = (
            sheet.values()
            .get(spreadsheetId=SPREADSHEET_ID, range="Transactions!A:E")
            .execute()
        )
        rows = result.get("values", [])[1:]

        if not rows:
            msg = "No entries found."
            if query: await query.message.reply_text(msg)
            else: await update.message.reply_text(msg)
            return

        msg = "📂 *Last 10 Expenses:*\n\n"
        for i, row in enumerate(reversed(rows[-10:]), start=1):
            row_num = len(rows) - i + 2 # Calculate original row number
            date = row[0] if len(row) > 0 else "-"
            amount = row[1] if len(row) > 1 else "-"
            category = row[2] if len(row) > 2 else "-"
            notes = row[4] if len(row) > 4 else "-"
            msg += f"`Row {row_num}`: {date} | ₹{amount} | {category} | {notes}\n"

        if query:
            await query.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        error_msg = f"⚠️ Error listing entries: {str(e)}"
        if query: await query.message.reply_text(error_msg)
        else: await update.message.reply_text(error_msg)

# ======================
# /remove command
# ======================
async def remove_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("⚠️ Usage: /remove <row_number>")
            return

        row_number = int(context.args[0])
        if row_number <= 1:
            await update.message.reply_text("⚠️ Cannot delete header row.")
            return

        sheet_metadata = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sheets = sheet_metadata.get("sheets", "")
        sheet_id = None
        for s in sheets:
            if s["properties"]["title"] == "Transactions":
                sheet_id = s["properties"]["sheetId"]
                break

        if sheet_id is None:
            await update.message.reply_text("⚠️ Could not find sheet 'Transactions'.")
            return

        requests = [{
            "deleteDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": row_number - 1,
                    "endIndex": row_number
                }
            }
        }]

        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": requests}
        ).execute()

        await update.message.reply_text(f"🗑️ Deleted row {row_number} successfully!")

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {str(e)}")

# ======================
# /summary and total
# ======================
async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_summary(update.message.chat_id)


async def total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        result = (
            sheet.values()
            .get(spreadsheetId=SPREADSHEET_ID, range="Transactions!A:E")
            .execute()
        )
        rows = result.get("values", [])[1:]

        if not rows:
            await update.message.reply_text("No data yet.")
            return

        total_amt = 0
        for row in rows:
            try:
                total_amt += float(str(row[1]).replace("₹", "").replace(",", ""))
            except:
                continue

        await update.message.reply_text(f"💰 *Total spent so far:* ₹{total_amt:,.0f}", parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {str(e)}")


# ======================
# Automated Summary Sender
# ======================
async def send_summary(chat_id: int):
    try:
        result = (
            sheet.values()
            .get(spreadsheetId=SPREADSHEET_ID, range="Transactions!A:E")
            .execute()
        )
        rows = result.get("values", [])[1:]

        if not rows:
            return

        # Simplified summary for all time
        expenses = []
        for row in rows:
            try:
                date = datetime.datetime.strptime(row[0], "%d-%b-%Y")
                amount = float(str(row[1]).replace("₹", "").replace(",", ""))
                category = row[2]
                expenses.append((date, amount, category))
            except:
                continue
        
        if not expenses: return

        total = sum(x[1] for x in expenses)
        biggest = max(expenses, key=lambda x: x[1])

        summary_text = f"📊 *Expense Summary (All time)*\n\n"
        summary_text += f"💰 Total: ₹{total:,.0f}\n"
        summary_text += f"🔥 Biggest: {biggest[2]} (₹{biggest[1]:,.0f})\n"

        await app.bot.send_message(
            chat_id=chat_id, text=summary_text, parse_mode="Markdown"
        )

    except Exception as e:
        await app.bot.send_message(
            chat_id=chat_id, text=f"⚠️ Error in summary: {str(e)}"
        )


# ======================
# Setup Scheduler AFTER app starts
# ======================
async def setup_scheduler(app: Application):
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(
        lambda: asyncio.create_task(send_summary(CHAT_ID)), "cron", hour=21, minute=0
    )  # daily
    scheduler.add_job(
        lambda: asyncio.create_task(send_summary(CHAT_ID)),
        "cron",
        day_of_week="sun",
        hour=21,
        minute=0,
    )  # weekly
    scheduler.add_job(
        lambda: asyncio.create_task(send_summary(CHAT_ID)), "cron", day=1, hour=21, minute=0
    )  # monthly
    scheduler.start()


# ======================
# Main
# ======================
def main():
    global app
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(setup_scheduler)
        .build()
    )

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("total", total))
    app.add_handler(CommandHandler("list", list_entries))
    app.add_handler(CommandHandler("remove", remove_entry))
    app.add_handler(CommandHandler("budget", budget))
    app.add_handler(CommandHandler("category", category_summary))
    
    # --- NEW: Handler for all button clicks ---
    app.add_handler(CallbackQueryHandler(button_callback_handler))

    # Message handler for adding expenses
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_expense))

    app.run_polling()


if __name__ == "__main__":
    main()