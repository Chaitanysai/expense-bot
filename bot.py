import logging
from telegram.ext import Updater, MessageHandler, Filters
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# --- Telegram Bot Token (from BotFather) ---
TOKEN = "8375627088:AAFdnn6KKwqsHYZ2ie73B9-YdMlC3Uu2C-Y"

# --- Google Sheets Setup ---
SPREADSHEET_ID = "1VEliBNt3PnUlp3UEsWRI-HU-b1KEafChsOx1jeR1PHk"
RANGE = "Transactions!A:E"  # Sheet name + range

# --- Authenticate with Google Sheets ---
creds = Credentials.from_service_account_file(
    "service_account.json",
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
service = build("sheets", "v4", credentials=creds)

# --- Logging for debugging ---
logging.basicConfig(level=logging.INFO)

# --- Categories that are considered FIXED ---
fixed_categories = [
    "EMI", "Rent", "Insurance", "Subscriptions", "Utilities"
]

# --- Expense Logging Function ---
def log_expense(update, context):
    msg = update.message.text.strip()
    try:
        # Expected format: "1 Sep 2025 250 Groceries Dinner at KFC"
        parts = msg.split(" ", 3)
        if len(parts) < 4:
            update.message.reply_text("❌ Format: 1 Sep 2025 250 Category Notes(optional)")
            return

        # Parse input
        date = f"{parts[0]} {parts[1]} {parts[2]}"  # e.g. "1 Sep 2025"
        amount = parts[3].split(" ", 1)[0]          # first number after date
        rest = parts[3].split(" ", 1)[1] if " " in parts[3] else ""
        category = rest.split(" ", 1)[0] if rest else ""
        notes = rest.split(" ", 1)[1] if " " in rest else ""

        # Determine Type (Fixed / Variable)
        type_value = "Fixed" if any(f in category for f in fixed_categories) else "Variable"

        # Append row to Google Sheet
        values = [[date, amount, category, type_value, notes]]
        body = {"values": values}
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE,
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()

        # Confirmation message back to Telegram
        update.message.reply_text(
            f"✅ Logged: {amount} in {category} ({type_value}) on {date} {f'({notes})' if notes else ''}"
        )

    except Exception as e:
        update.message.reply_text(f"❌ Error: {e}")

# --- Main Bot Function ---
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, log_expense))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
