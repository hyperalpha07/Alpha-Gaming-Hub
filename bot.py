import os
import sqlite3
import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("alpha-referral-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
VIP_CHAT_ID = int(os.getenv("VIP_CHAT_ID", "0"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_FILE = "referrals.db"

REWARD_TEXT = """
🎯 Reward System:

3 জন Active Join = 10 টাকা
10 জন Active Join = 50 টাকা
20 জন Active Join = 120 টাকা

⚠️ Fake account, duplicate join, leave করে আবার join করলে count হবে না।
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
            username TEXT,
            first_name TEXT,
            invite_link TEXT UNIQUE,
            created_at TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            joined_user_id INTEGER PRIMARY KEY,
            referrer_id INTEGER,
            joined_at TEXT,
            active INTEGER DEFAULT 1
        )
        """)
        conn.commit()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    with db() as conn:
        row = conn.execute(
            "SELECT invite_link FROM users WHERE user_id=?",
            (user.id,)
        ).fetchone()

    if row:
        link = row["invite_link"]
    else:
        invite = await context.bot.create_chat_invite_link(
            chat_id=VIP_CHAT_ID,
            name=f"ref_{user.id}",
            creates_join_request=False
        )
        link = invite.invite_link

        with db() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO users
            (user_id, username, first_name, invite_link, created_at)
            VALUES (?, ?, ?, ?, ?)
            """, (
                user.id,
                user.username or "",
                user.first_name or "",
                link,
                datetime.now(timezone.utc).isoformat()
            ))
            conn.commit()

    msg = f"""
🔥 Alpha Gaming VIP-এ স্বাগতম

💰 Invite করে reward জিতুন।

আপনার personal invite link:
{link}

বন্ধুদের এই link পাঠান। তারা join করলে আপনার count বাড়বে।

{REWARD_TEXT}

আপনার count দেখতে:
/myref
"""
    await update.message.reply_text(msg)


async def myref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM referrals WHERE referrer_id=? AND active=1",
            (user.id,)
        ).fetchone()["c"]

    await update.message.reply_text(
        f"📊 আপনার Active Referral: {count} জন\n\n{REWARD_TEXT}"
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        rows = conn.execute("""
        SELECT u.first_name, u.username, COUNT(r.joined_user_id) AS total
        FROM referrals r
        JOIN users u ON u.user_id = r.referrer_id
        WHERE r.active=1
        GROUP BY r.referrer_id
        ORDER BY total DESC
        LIMIT 10
        """).fetchall()

    if not rows:
        await update.message.reply_text("এখনো কোনো referral নেই।")
        return

    text = "🏆 Top Referrers:\n\n"
    for i, r in enumerate(rows, 1):
        name = r["first_name"] or r["username"] or "User"
        text += f"{i}. {name} — {r['total']} জন\n"

    await update.message.reply_text(text)


async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    old = cm.old_chat_member.status
    new = cm.new_chat_member.status
    joined_user = cm.new_chat_member.user

    if old in ("left", "kicked") and new in ("member", "administrator"):
        invite_link = cm.invite_link.invite_link if cm.invite_link else None
        if not invite_link:
            return

        with db() as conn:
            ref = conn.execute(
                "SELECT user_id FROM users WHERE invite_link=?",
                (invite_link,)
            ).fetchone()

            if not ref:
                return

            referrer_id = ref["user_id"]

            if joined_user.id == referrer_id:
                return

            conn.execute("""
            INSERT OR IGNORE INTO referrals
            (joined_user_id, referrer_id, joined_at, active)
            VALUES (?, ?, ?, 1)
            """, (
                joined_user.id,
                referrer_id,
                datetime.now(timezone.utc).isoformat()
            ))
            conn.commit()

            count = conn.execute(
                "SELECT COUNT(*) AS c FROM referrals WHERE referrer_id=? AND active=1",
                (referrer_id,)
            ).fetchone()["c"]

        try:
            await context.bot.send_message(
                chat_id=referrer_id,
                text=f"✅ নতুন ১ জন আপনার link দিয়ে join করেছে!\n\n📊 মোট Active Referral: {count} জন"
            )
        except Exception:
            pass

        if ADMIN_ID:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"✅ New Referral\nUser: {joined_user.full_name}\nReferrer ID: {referrer_id}\nTotal: {count}"
            )

    if old in ("member", "administrator") and new in ("left", "kicked"):
        with db() as conn:
            conn.execute(
                "UPDATE referrals SET active=0 WHERE joined_user_id=?",
                (joined_user.id,)
            )
            conn.commit()


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    with db() as conn:
        total_users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        total_refs = conn.execute(
            "SELECT COUNT(*) AS c FROM referrals WHERE active=1"
        ).fetchone()["c"]

    await update.message.reply_text(
        f"📊 Admin Stats\n\nBot Users: {total_users}\nActive Referrals: {total_refs}"
    )


def main():
    if not BOT_TOKEN or not VIP_CHAT_ID:
        raise RuntimeError("BOT_TOKEN and VIP_CHAT_ID env variables required")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myref", myref))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.CHAT_MEMBER))

    log.info("Alpha referral bot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
