import os, json, logging
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# --- Hardcoded Values (your bot + sheet) ---
TOKEN = "8375627088:AAFdnn6KKwqsHYZ2ie73B9-YdMlC3Uu2C-Y"
SPREADSHEET_ID = "1VEliBNt3PnUlp3UEsWRI-HU-b1KEafChsOx1jeR1PHk"

# Load Google Service Account JSON from env variable (Render-safe)
service_account_info = json.loads(os.getenv("SERVICE_ACCOUNT_JSON"))
creds = Credentials.from_service_account_info(
    service_account_info,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
service = build("sheets", "v4", credentials=creds)

# Logging
logging.basicConfig(level=logging.INFO)

fixed_categories = ["EMI", "Rent", "Insurance", "Subscriptions", "Utilities"]

# --- Expense Logging Function ---
async def log_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    try:
        parts = msg.split(" ", 3)
        if len(parts) < 4:
            await update.message.reply_text("❌ Format: 1 Sep 2025 250 Category Notes(optional)")
            return

        date = f"{parts[0]} {parts[1]} {parts[2]}"
        amount = parts[3].split(" ", 1)[0]
        rest = parts[3].split(" ", 1)[1] if " " in parts[3] else ""
        category = rest.split(" ", 1)[0] if rest else ""
        notes = rest.split(" ", 1)[1] if " " in rest else ""

        type_value = "Fixed" if any(f in category for f in fixed_categories) else "Variable"

        values = [[date, amount, category, type_value, notes]]
        body = {"values": values}
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="Transactions!A:E",
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()

        await update.message.reply_text(
            f"✅ Logged: {amount} in {category} ({type_value}) on {date} {f'({notes})' if notes else ''}"
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# --- Main Function ---
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, log_expense))
    app.run_polling()

if __name__ == "__main__":
    main()