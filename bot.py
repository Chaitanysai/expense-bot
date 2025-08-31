import os
import json
import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ======================
# Config
# ======================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
service_account_info = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))

# Your personal chat ID
OWNER_CHAT_ID = 1133284028  

creds = service_account.Credentials.from_service_account_info(
    service_account_info,
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)
service = build("sheets", "v4", credentials=creds)
sheet = service.spreadsheets()

# ======================
# Category auto-detect
# ======================
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
        "Use /total for lifetime spending.\n"
        "Use /id to get your chat ID."
    )

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()

        # Special shortcut
        if text.lower() == "total":
            await total(update, context)
            return

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
            range="Transactions!A:E",
            valueInputOption="USER_ENTERED",
            body={"values": values}
        ).execute()

        await update.message.reply_text(f"✅ Added: {amount} under {category} ({expense_type})")

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {str(e)}")

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await generate_summary(days=7)
    await update.message.reply_text(text, parse_mode="Markdown")

async def total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await generate_total()
    await update.message.reply_text(text)

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    await update.message.reply_text(f"🆔 Your Chat ID is: `{chat_id}`", parse_mode="Markdown")

# ======================
# Helpers to generate reports
# ======================
async def generate_summary(days=7):
    try:
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID, range="Transactions!A:E"
        ).execute()
        rows = result.get("values", [])[1:]

        if not rows:
            return "No data yet."

        today = datetime.datetime.now()
        since = today - datetime.timedelta(days=days)

        expenses = []
        for row in rows:
            try:
                date = datetime.datetime.strptime(row[0], "%d-%b-%Y")
                if date >= since:
                    amount = float(row[1].replace("₹", "").replace(",", ""))
                    category = row[2]
                    expenses.append((date, amount, category))
            except:
                continue

        if not expenses:
            return f"No expenses in last {days} days."

        total_amt = sum(x[1] for x in expenses)
        biggest = max(expenses, key=lambda x: x[1])

        category_totals = {}
        for _, amt, cat in expenses:
            category_totals[cat] = category_totals.get(cat, 0) + amt

        summary_text = f"📊 *Expense Summary ({days} days)*\n{since.strftime('%d %b')} – {today.strftime('%d %b')}\n\n"
        summary_text += f"💰 Total: ₹{total_amt:,.0f}\n"
        summary_text += f"🔥 Biggest: {biggest[2]} (₹{biggest[1]:,.0f})\n\n"
        summary_text += "📌 Categories:\n"
        for cat, amt in category_totals.items():
            summary_text += f"- {cat}: ₹{amt:,.0f}\n"

        return summary_text

    except Exception as e:
        return f"⚠️ Error: {str(e)}"

async def generate_total():
    try:
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID, range="Transactions!A:E"
        ).execute()
        rows = result.get("values", [])[1:]

        if not rows:
            return "No expenses recorded yet."

        total_amt = 0
        for row in rows:
            try:
                total_amt += float(row[1].replace("₹", "").replace(",", ""))
            except:
                continue

        return f"💰 Total spent till now: ₹{total_amt:,.0f}"

    except Exception as e:
        return f"⚠️ Error: {str(e)}"

# ======================
# Scheduler jobs (auto push)
# ======================
async def send_daily_summary(app: Application):
    text = await generate_summary(days=1)
    await app.bot.send_message(chat_id=OWNER_CHAT_ID, text="📅 *Daily Report*\n\n" + text, parse_mode="Markdown")

async def send_weekly_summary(app: Application):
    text = await generate_summary(days=7)
    await app.bot.send_message(chat_id=OWNER_CHAT_ID, text="📅 *Weekly Report*\n\n" + text, parse_mode="Markdown")

async def send_monthly_summary(app: Application):
    text = await generate_summary(days=30)
    await app.bot.send_message(chat_id=OWNER_CHAT_ID, text="📅 *Monthly Report*\n\n" + text, parse_mode="Markdown")

# ======================
# Main
# ======================
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Manual commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("total", total))
    app.add_handler(CommandHandler("id", get_id))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_expense))

    # Scheduler setup
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(send_daily_summary, "cron", hour=21, minute=0, args=[app])   # 9PM IST daily
    scheduler.add_job(send_weekly_summary, "cron", day_of_week="sun", hour=21, minute=0, args=[app])  # Sunday
    scheduler.add_job(send_monthly_summary, "cron", day=1, hour=21, minute=0, args=[app])  # 1st of month
    scheduler.start()

    app.run_polling()

if __name__ == "__main__":
    main()