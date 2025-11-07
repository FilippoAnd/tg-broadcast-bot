import os
import asyncio
import textwrap
from datetime import datetime

import aiosqlite
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ──────────────────────────────────────────────────────
# CONFIG
# Preferisce ENV; se non ci sono, usa fallback hard-coded.
BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    "8449085013:AAE6x7EeJkNm9WpC_xWa8ihqmq8fdxtQ3lc"  # <-- puoi rimuoverlo in prod
)

# ADMIN_IDS può essere "123,456" da ENV oppure fallback set singolo
if os.getenv("ADMIN_IDS"):
    ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS").split(",") if x.strip().isdigit()}
else:
    ADMIN_IDS = {1672972729}

COOLDOWN = float(os.getenv("COOLDOWN", "1.2"))  # secondi fra i messaggi broadcast
FOOTER   = os.getenv("FOOTER", "⚠️ For educational purposes only. This is not financial advice.")
# FORZA il path ignorando qualunque ENV per sbloccare il deploy
DB_PATH  = "/tmp/subs.db"   # /tmp esiste sempre ed è scrivibile su Railway

# ──────────────────────────────────────────────────────

def fmt(msg: str) -> str:
    clean = textwrap.dedent(msg).strip()
    return f"{clean}\n\n{FOOTER}" if FOOTER else clean

async def init_db():
    # crea la cartella se il path è tipo /data/subs.db o ./data/subs.db
    db_dir = os.path.dirname(DB_PATH) or "."
    os.makedirs(db_dir, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS subscribers(
            chat_id   INTEGER PRIMARY KEY,
            username  TEXT,
            created_at TEXT
        )""")
        # compatibilità se la tabella esiste senza colonna username
        try:
            await db.execute("ALTER TABLE subscribers ADD COLUMN username TEXT;")
        except Exception:
            pass
        await db.commit()

async def add_sub(chat_id: int, username: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO subscribers (chat_id, username, created_at) VALUES (?, ?, ?)",
            (chat_id, username, datetime.utcnow().isoformat())
        )
        await db.commit()

async def remove_sub(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subscribers WHERE chat_id=?", (chat_id,))
        await db.commit()

async def get_subs() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT chat_id FROM subscribers")
        rows = await cur.fetchall()
        return [r[0] for r in rows]

# ──────────────── COMMANDS ────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "Available commands:\n"
        "/subscribe – subscribe to alerts\n"
        "/unsubscribe – unsubscribe from alerts\n"
        "/status – check your subscription status\n"
        "/about – info and disclaimer"
    )

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "All alerts are manually created by the admin and sent automatically.\n"
        "For educational purposes only. This is not financial advice."
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_sub(update.effective_chat.id, update.effective_user.username)
    await update.message.reply_text("✅ Subscription activated: you'll receive future alerts.")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await remove_sub(update.effective_chat.id)
    await update.message.reply_text("❎ Subscription canceled.")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subs = await get_subs()
    msg = "🔔 You are subscribed." if update.effective_chat.id in subs else "🔕 You are not subscribed."
    await update.message.reply_text(msg)

async def adminlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("Admins only.")
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute("SELECT chat_id, username, created_at FROM subscribers")).fetchall()
    if not rows:
        return await update.message.reply_text("No subscribers yet.")
    lines = [f"{(u or '(no username)'):>15} — {cid} — {ts}" for cid, u, ts in rows]
    await update.message.reply_text(f"Total subscribers: {len(rows)}\n\n" + "\n".join(lines))

async def post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("This command is for admins only.")
    text = update.message.text.partition(" ")[2].strip()
    if not text and update.message.reply_to_message:
        text = update.message.reply_to_message.text
    if not text:
        return await update.message.reply_text("Usage: /post <text> or reply to a message with /post.")

    msg  = fmt(text)
    subs = await get_subs()
    ok = 0
    for cid in subs:
        try:
            await context.bot.send_message(cid, msg, parse_mode=ParseMode.MARKDOWN)
            ok += 1
            await asyncio.sleep(COOLDOWN)
        except Exception:
            # ignora errori singoli e continua
            await asyncio.sleep(0.3)
    await update.message.reply_text(f"🟢 Message sent to {ok} subscribers.")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Unknown command. Use /start to see available commands.")

# ──────────────── BOOTSTRAP ────────────────

async def run():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing. Set it as env var on your host.")
    await init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("about", about))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("adminlist", adminlist, filters=filters.User(user_id=list(ADMIN_IDS))))
    app.add_handler(CommandHandler("post", post, filters=filters.User(user_id=list(ADMIN_IDS))))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("✅ Bot started. Listening...")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    # compat Windows, se mai esegui locale
    import sys
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run())
