import os
import json
import datetime
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
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

CATEGORY_KEYWORDS = {
    "fuel": "🏍️ Bike Fuel",
    "petrol": "🏍️ Bike Fuel",
    "grocery": "🛒 Groceries",
    "groceries": "🛒 Groceries",
    "food": "🍱 Food Delivery / Dining Out",
    "dining": "🍱 Food Delivery / Dining Out",
    "emi": "🚗 EMI – Bike Loan",
    "loan": "💳 EMI – Home Loan",
    "subscription": "📺 Subscriptions",
    "insurance": "📑 Insurance",
    "shop": "🎁 Miscellaneous / Shopping",
    "others": "🌟 Others",
}

def detect_category(text: str) -> str:
    text = text.lower()
    for key, category in CATEGORY_KEYWORDS.items():
        if key in text:
            return category
    return "🌟 Others"

# ======================
# Bot Handlers
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! Send me expenses like:\n"
        "`250 groceries dinner`\n\n"
        "If you don’t include a date, I’ll use today.\n"
        "Use /summary for weekly report.\n"
        "Type 'Total' anytime to get lifetime spend."
    )

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()

        # If user asks for total
        if text.lower() == "total":
            return await total(update, context)

        parts = text.split()

        # Try parsing first word as a date (dd-MMM-YYYY)
        try:
            expense_date = datetime.datetime.strptime(parts[0], "%d-%b-%Y").strftime("%d-%b-%Y")
            amount = parts[1]
            notes = " ".join(parts[2:])
        except ValueError:
            # No valid date → assume today
            expense_date = datetime.datetime.now().strftime("%d-%b-%Y")
            amount = parts[0]
            notes = " ".join(parts[1:])

        category = detect_category(notes)
        expense_type = "Fixed" if "EMI" in category or "Loan" in category else "Variable"

        values = [[expense_date, amount, category, expense_type, notes]]
        sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="Transactions!A:E",   # <-- ✅ matches your sheet tab name
            valueInputOption="USER_ENTERED",
            body={"values": values}
        ).execute()

        await update.message.reply_text(f"✅ Added: {amount} under {category} ({expense_type})")

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {str(e)}")

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_summary(update.message.chat_id)

async def total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID, range="Transactions!A:E"
        ).execute()
        rows = result.get("values", [])[1:]

        if not rows:
            await update.message.reply_text("No data yet.")
            return

        total_amt = 0
        for row in rows:
            try:
                total_amt += float(row[1].replace("₹", "").replace(",", ""))
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
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID, range="Transactions!A:E"
        ).execute()
        rows = result.get("values", [])[1:]

        if not rows:
            return

        today = datetime.datetime.now()
        week_ago = today - datetime.timedelta(days=7)

        expenses = []
        for row in rows:
            try:
                date = datetime.datetime.strptime(row[0], "%d-%b-%Y")
                amount = float(row[1].replace("₹", "").replace(",", ""))
                category = row[2]
                expenses.append((date, amount, category))
            except:
                continue

        total = sum(x[1] for x in expenses)
        biggest = max(expenses, key=lambda x: x[1])

        summary_text = f"📊 *Expense Summary (All time)*\n\n"
        summary_text += f"💰 Total: ₹{total:,.0f}\n"
        summary_text += f"🔥 Biggest: {biggest[2]} (₹{biggest[1]:,.0f})\n"

        await app.bot.send_message(chat_id=chat_id, text=summary_text, parse_mode="Markdown")

    except Exception as e:
        await app.bot.send_message(chat_id=chat_id, text=f"⚠️ Error in summary: {str(e)}")

# ======================
# Main
# ======================
def main():
    global app
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_expense))

    # Attach scheduler to PTB loop
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(lambda: asyncio.create_task(send_summary(CHAT_ID)), "cron", hour=21, minute=0)   # daily
    scheduler.add_job(lambda: asyncio.create_task(send_summary(CHAT_ID)), "cron", day_of_week="sun", hour=21, minute=0)  # weekly
    scheduler.add_job(lambda: asyncio.create_task(send_summary(CHAT_ID)), "cron", day=1, hour=21, minute=0)  # monthly
    scheduler.start()

    app.run_polling()

if __name__ == "__main__":
    main()