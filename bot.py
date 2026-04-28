import os
import sqlite3
import logging
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("alpha-referral-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "alphagaminghubBot").replace("@", "")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@alphagaminghub")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/alphagaminghub")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_FILE = "alpha_referral.db"

REWARD_TEXT = """
🎯 রিওয়ার্ড সিস্টেম:

✅ ৩ জন = ১০ টাকা
✅ ১০ জন = ৫০ টাকা
✅ ২০ জন = ১২০ টাকা

⚠️ একই user একবারই count হবে।
⚠️ Fake account / duplicate join count হবে না।
⚠️ Reward পেতে অবশ্যই Channel join verify করতে হবে।
"""


def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            referrer_id INTEGER,
            verified INTEGER DEFAULT 0,
            joined_at TEXT
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referred_user_id INTEGER PRIMARY KEY,
            referrer_id INTEGER,
            verified INTEGER DEFAULT 0,
            created_at TEXT
        )
        """)
        conn.commit()


def get_ref_count(user_id: int) -> int:
    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM referrals WHERE referrer_id=? AND verified=1",
            (user_id,)
        ).fetchone()
        return row["c"]


def get_invite_link(user_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    referrer_id = None
    if args and args[0].startswith("ref_"):
        try:
            referrer_id = int(args[0].replace("ref_", ""))
            if referrer_id == user.id:
                referrer_id = None
        except Exception:
            referrer_id = None

    with db() as conn:
        existing = conn.execute(
            "SELECT user_id, referrer_id, verified FROM users WHERE user_id=?",
            (user.id,)
        ).fetchone()

        if not existing:
            conn.execute("""
            INSERT INTO users (user_id, first_name, username, referrer_id, verified, joined_at)
            VALUES (?, ?, ?, ?, 0, ?)
            """, (
                user.id,
                user.first_name or "",
                user.username or "",
                referrer_id,
                datetime.now(timezone.utc).isoformat()
            ))

            if referrer_id:
                conn.execute("""
                INSERT OR IGNORE INTO referrals
                (referred_user_id, referrer_id, verified, created_at)
                VALUES (?, ?, 0, ?)
                """, (
                    user.id,
                    referrer_id,
                    datetime.now(timezone.utc).isoformat()
                ))

            conn.commit()

    invite_link = get_invite_link(user.id)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Channel Join করুন", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ আমি Join করেছি", callback_data="verify_join")],
        [InlineKeyboardButton("🔗 আমার Invite Link", callback_data="my_link")],
        [InlineKeyboardButton("📊 আমার Referral", callback_data="my_ref")]
    ])

    text = f"""
🎮 স্বাগতম {user.first_name}!

Alpha Gaming Hub-এ আপনাকে স্বাগতম 🔥

💰 Invite করে reward জেতার সুযোগ!

আপনার personal invite link:
{invite_link}

এই link বন্ধুদের দিন। তারা BOT START করে Channel join verify করলে আপনার count বাড়বে।

{REWARD_TEXT}

👇 আগে Channel join করুন, তারপর Verify চাপুন।
"""

    await update.message.reply_text(text, reply_markup=keyboard)

    if referrer_id and ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"👤 New user started by referral\nUser: {user.first_name}\nUser ID: {user.id}\nReferrer ID: {referrer_id}"
            )
        except Exception:
            pass


async def verify_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user

    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL_USERNAME,
            user_id=user.id
        )

        if member.status not in ["member", "administrator", "creator"]:
            await query.message.reply_text(
                "❌ আপনি এখনো Channel join করেননি।\n\nআগে Channel join করুন, তারপর আবার Verify চাপুন।"
            )
            return

    except Exception as e:
        log.warning(f"Verify failed: {e}")
        await query.message.reply_text(
            "⚠️ Verify করতে সমস্যা হচ্ছে।\n\nBot-কে Channel-এর Admin করা আছে কি না check করুন।"
        )
        return

    with db() as conn:
        user_row = conn.execute(
            "SELECT verified, referrer_id FROM users WHERE user_id=?",
            (user.id,)
        ).fetchone()

        if not user_row:
            await query.message.reply_text("প্রথমে /start দিন।")
            return

        if user_row["verified"] == 1:
            await query.message.reply_text("✅ আপনি already verified.")
            return

        conn.execute("UPDATE users SET verified=1 WHERE user_id=?", (user.id,))

        referrer_id = user_row["referrer_id"]
        if referrer_id:
            conn.execute("""
            UPDATE referrals
            SET verified=1
            WHERE referred_user_id=? AND referrer_id=?
            """, (user.id, referrer_id))

        conn.commit()

    await query.message.reply_text(
        "✅ Verification successful!\n\nএখন আপনার নিজের invite link share করে reward জিতুন।"
    )

    if referrer_id:
        count = get_ref_count(referrer_id)

        try:
            await context.bot.send_message(
                chat_id=referrer_id,
                text=f"✅ আপনার link দিয়ে নতুন ১ জন verified হয়েছে!\n\n📊 মোট Verified Referral: {count} জন"
            )
        except Exception:
            pass

        if ADMIN_ID:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"✅ Verified Referral\nUser: {user.first_name}\nReferrer ID: {referrer_id}\nTotal: {count}"
            )


async def my_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    link = get_invite_link(user.id)

    await query.message.reply_text(
        f"🔗 আপনার personal invite link:\n\n{link}\n\nবন্ধুদের এই link পাঠান।"
    )


async def my_ref_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    count = get_ref_count(user.id)

    await query.message.reply_text(
        f"📊 আপনার Verified Referral: {count} জন\n\n{REWARD_TEXT}"
    )


async def myref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    count = get_ref_count(user.id)
    await update.message.reply_text(
        f"📊 আপনার Verified Referral: {count} জন\n\n{REWARD_TEXT}"
    )


async def link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    invite_link = get_invite_link(user.id)

    await update.message.reply_text(
        f"🔗 আপনার personal invite link:\n\n{invite_link}\n\nবন্ধুদের এই link পাঠান।"
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        rows = conn.execute("""
        SELECT u.first_name, u.username, COUNT(r.referred_user_id) AS total
        FROM referrals r
        JOIN users u ON u.user_id = r.referrer_id
        WHERE r.verified=1
        GROUP BY r.referrer_id
        ORDER BY total DESC
        LIMIT 10
        """).fetchall()

    if not rows:
        await update.message.reply_text("এখনো কোনো verified referral নেই।")
        return

    text = "🏆 Top Referrers:\n\n"
    for i, r in enumerate(rows, 1):
        name = r["first_name"] or r["username"] or "User"
        text += f"{i}. {name} — {r['total']} জন\n"

    await update.message.reply_text(text)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    with db() as conn:
        total_users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        verified_users = conn.execute("SELECT COUNT(*) AS c FROM users WHERE verified=1").fetchone()["c"]
        total_refs = conn.execute("SELECT COUNT(*) AS c FROM referrals WHERE verified=1").fetchone()["c"]

    await update.message.reply_text(
        f"📊 Admin Stats\n\n"
        f"👤 Total Bot Users: {total_users}\n"
        f"✅ Verified Channel Users: {verified_users}\n"
        f"🔗 Verified Referrals: {total_refs}"
    )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    message = " ".join(context.args)
    if not message:
        await update.message.reply_text("ব্যবহার করুন:\n/broadcast আপনার মেসেজ")
        return

    sent = 0
    failed = 0

    with db() as conn:
        rows = conn.execute("SELECT user_id FROM users").fetchall()

    for r in rows:
        try:
            await context.bot.send_message(chat_id=r["user_id"], text=message)
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(f"✅ Broadcast done\nSent: {sent}\nFailed: {failed}")


async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data

    if data == "verify_join":
        await verify_join_callback(update, context)
    elif data == "my_link":
        await my_link_callback(update, context)
    elif data == "my_ref":
        await my_ref_callback(update, context)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myref", myref))
    app.add_handler(CommandHandler("link", link))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CallbackQueryHandler(button_router))

    log.info("Alpha Gaming Hub bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
