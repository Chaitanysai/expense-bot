import os
import json
import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ======================
# Config (Railway will inject via env vars)
# ======================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
service_account_info = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))

creds = service_account.Credentials.from_service_account_info(
    service_account_info,
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)
service = build("sheets", "v4", credentials=creds)
sheet = service.spreadsheets()

# ======================
# Category auto-detect (maps free text → your dropdowns)
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
        "Use /summary for weekly report."
    )

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
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

        # Detect category & type
        category = detect_category(notes)
        expense_type = "Fixed" if "EMI" in category or "Loan" in category else "Variable"

        # Push to Google Sheets
        values = [[expense_date, amount, category, expense_type, notes]]
        sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="Sheet1!A:E",
            valueInputOption="USER_ENTERED",
            body={"values": values}
        ).execute()

        await update.message.reply_text(f"✅ Added: {amount} under {category} ({expense_type})")

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {str(e)}")

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID, range="Sheet1!A:E"
        ).execute()
        rows = result.get("values", [])[1:]  # skip headers

        if not rows:
            await update.message.reply_text("No data yet.")
            return

        today = datetime.datetime.now()
        week_ago = today - datetime.timedelta(days=7)

        expenses = []
        for row in rows:
            try:
                date = datetime.datetime.strptime(row[0], "%d-%b-%Y")
                if date >= week_ago:
                    amount = float(row[1].replace("₹", "").replace(",", ""))
                    category = row[2]
                    expenses.append((date, amount, category))
            except:
                continue

        if not expenses:
            await update.message.reply_text("No expenses this week.")
            return

        total = sum(x[1] for x in expenses)
        biggest = max(expenses, key=lambda x: x[1])

        category_totals = {}
        for _, amt, cat in expenses:
            category_totals[cat] = category_totals.get(cat, 0) + amt

        summary_text = f"📊 *Expense Summary*\n{week_ago.strftime('%d %b')} – {today.strftime('%d %b')}\n\n"
        summary_text += f"💰 Total: ₹{total:,.0f}\n"
        summary_text += f"🔥 Biggest: {biggest[2]} (₹{biggest[1]:,.0f})\n\n"
        summary_text += "📌 Categories:\n"
        for cat, amt in category_totals.items():
            summary_text += f"- {cat}: ₹{amt:,.0f}\n"

        await update.message.reply_text(summary_text, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {str(e)}")

# ======================
# Main
# ======================
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_expense))
    app.run_polling()

if __name__ == "__main__":
    main()