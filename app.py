"""
Kindred - Python web app with sign up / sign in and phone verification.
Run: python app.py
"""
import json
import os
import sqlite3
import random
import string
import re
import uuid
import webbrowser
import threading
import time
from datetime import date as date_cls, timedelta
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

DB_PATH = Path(__file__).parent / "kindred.db"
UPLOAD_FOLDER = Path(__file__).parent / "static" / "uploads"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
VERIFICATION_CODES = {}

DAILY_PROMPTS = [
    "What made you smile today?",
    "What's one thing you're grateful for?",
    "What challenged you today?",
    "What's a small win from today?",
    "What did you learn today?",
    "Who inspired you recently?",
    "What are you looking forward to tomorrow?",
    "Describe today in three words.",
    "What would you do differently today?",
    "What's something you want to remember about today?",
    "What made today unique?",
    "Share a random thought you had today.",
    "What song is stuck in your head?",
    "What's your energy level today?",
    "What's one thing you did for yourself today?",
]

BADGE_DEFS = [
    {"id": "first_checkin",  "emoji": "🌟", "name": "First Check-In",    "desc": "Checked in for the first time"},
    {"id": "streak_3",       "emoji": "🔥", "name": "3-Day Streak",       "desc": "Checked in 3 days in a row"},
    {"id": "streak_7",       "emoji": "🏆", "name": "7-Day Streak",       "desc": "Checked in 7 days in a row"},
    {"id": "streak_14",      "emoji": "⚡", "name": "14-Day Streak",      "desc": "Checked in 14 days in a row"},
    {"id": "streak_30",      "emoji": "💎", "name": "30-Day Streak",      "desc": "Checked in 30 days in a row"},
    {"id": "streak_100",     "emoji": "🌈", "name": "100-Day Streak",     "desc": "Checked in 100 days in a row"},
    {"id": "first_friend",   "emoji": "🤝", "name": "First Friend",       "desc": "Made your first friend"},
    {"id": "social_5",       "emoji": "👥", "name": "Social Butterfly",   "desc": "Made 5 friends"},
    {"id": "social_10",      "emoji": "🎊", "name": "Social Star",        "desc": "Made 10 friends"},
    {"id": "first_post",     "emoji": "📝", "name": "First Post",         "desc": "Added your first board post"},
    {"id": "first_reaction", "emoji": "❤️", "name": "First Reaction",     "desc": "Reacted to a friend's post"},
    {"id": "mood_10",        "emoji": "😊", "name": "Mood Tracker",       "desc": "Logged your mood 10 times"},
    {"id": "challenge_1",    "emoji": "🏅", "name": "Challenger",         "desc": "Completed your first weekly challenge"},
    {"id": "group_chat_1",   "emoji": "💬", "name": "Group Chat",         "desc": "Sent your first group message"},
]

WEEKLY_CHALLENGES = [
    {"id": "checkin_7",      "title": "7-Day Warrior",      "desc": "Check in every day this week",            "type": "checkin",        "target": 7, "emoji": "🔥"},
    {"id": "checkin_5",      "title": "5-Day Streak",        "desc": "Check in 5 days this week",               "type": "checkin",        "target": 5, "emoji": "⚡"},
    {"id": "posts_3",        "title": "Board Enthusiast",    "desc": "Post 3 things on your board this week",   "type": "posts",          "target": 3, "emoji": "📝"},
    {"id": "react_5",        "title": "Reaction Master",     "desc": "React to 5 friend posts this week",       "type": "reactions",      "target": 5, "emoji": "❤️"},
    {"id": "friends_check",  "title": "Social Butterfly",    "desc": "Have 3 friends who check in this week",   "type": "friends_checkin","target": 3, "emoji": "👥"},
]

PROFILE_THEMES = {
    "blue":   {"primary": "#4a90e2", "gradient": "135deg, #1a1a2e 0%, #16213e 100%"},
    "purple": {"primary": "#8b5cf6", "gradient": "135deg, #1e1b3a 0%, #2d1b69 100%"},
    "green":  {"primary": "#10b981", "gradient": "135deg, #1a2e1a 0%, #0f2d20 100%"},
    "pink":   {"primary": "#ec4899", "gradient": "135deg, #2e1a2e 0%, #3d0d3d 100%"},
    "orange": {"primary": "#f59e0b", "gradient": "135deg, #2e1a00 0%, #3d2200 100%"},
    "red":    {"primary": "#ef4444", "gradient": "135deg, #2e0000 0%, #3d0000 100%"},
}


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            bio TEXT DEFAULT '',
            avatar TEXT DEFAULT '',
            streak_freezes INTEGER DEFAULT 0,
            theme_color TEXT DEFAULT 'blue',
            status_msg TEXT DEFAULT '',
            board_privacy TEXT DEFAULT 'friends',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for col, defval in [
        ("display_name",  "TEXT"),
        ("bio",           "TEXT DEFAULT ''"),
        ("avatar",        "TEXT DEFAULT ''"),
        ("streak_freezes","INTEGER DEFAULT 0"),
        ("theme_color",   "TEXT DEFAULT 'blue'"),
        ("status_msg",    "TEXT DEFAULT ''"),
        ("board_privacy", "TEXT DEFAULT 'friends'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {defval}")
        except sqlite3.OperationalError:
            pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS friend_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_user_id, to_user_id),
            FOREIGN KEY (from_user_id) REFERENCES users(id),
            FOREIGN KEY (to_user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS friendships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            friend_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, friend_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (friend_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS check_ins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            mood TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    try:
        conn.execute("ALTER TABLE check_ins ADD COLUMN mood TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS board_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            content TEXT NOT NULL,
            pos_left REAL DEFAULT 20,
            pos_top REAL DEFAULT 60,
            width REAL DEFAULT 200,
            color TEXT DEFAULT 'default',
            pinned INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    try:
        conn.execute("ALTER TABLE board_posts ADD COLUMN pinned INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            emoji TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(post_id, user_id, emoji),
            FOREIGN KEY (post_id) REFERENCES board_posts(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            read_at TIMESTAMP,
            FOREIGN KEY (from_user_id) REFERENCES users(id),
            FOREIGN KEY (to_user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_badges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            badge_id TEXT NOT NULL,
            earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, badge_id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            from_user_id INTEGER,
            type TEXT NOT NULL,
            message TEXT NOT NULL,
            read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS group_chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS group_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(group_id, user_id),
            FOREIGN KEY (group_id) REFERENCES group_chats(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS group_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            from_user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (group_id) REFERENCES group_chats(id),
            FOREIGN KEY (from_user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS custom_prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            prompt TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def is_gmail(email: str) -> bool:
    email = (email or "").strip().lower()
    return bool(email and email.endswith("@gmail.com") and "@" in email and "." in email.split("@")[1])


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10 and digits.startswith(("2", "3", "4", "5", "6", "7", "8", "9")):
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return "+" + digits if digits else ""


def generate_code() -> str:
    return "".join(random.choices(string.digits, k=6))


def send_sms_via_twilio(to: str, body: str) -> bool:
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_num = os.environ.get("TWILIO_PHONE_NUMBER")
    if not all([sid, token, from_num]):
        print(f"[DEMO] SMS to {to}: {body}")
        return True
    try:
        from twilio.rest import Client
        client = Client(sid, token)
        client.messages.create(to=to, from_=from_num, body=body)
        return True
    except Exception as e:
        print(f"Twilio error: {e}")
        return False


def hash_password(password: str) -> str:
    from werkzeug.security import generate_password_hash
    return generate_password_hash(password, method="pbkdf2:sha256")


def check_password(password: str, password_hash: str) -> bool:
    from werkzeug.security import check_password_hash
    return check_password_hash(password_hash, password)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _mask_phone(phone: str) -> str:
    if len(phone) < 4:
        return "***"
    return phone[:2] + "***" + phone[-4:]


def _current_user_id():
    u = session.get("user")
    if not u:
        return None
    uid = u.get("id")
    if uid is not None:
        return uid
    email = u.get("email")
    if not email:
        return None
    conn = get_db()
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    if row:
        session.setdefault("user", {})["id"] = row["id"]
        return row["id"]
    return None


def _refresh_session_user():
    u = session.get("user")
    if not u or not u.get("email"):
        return
    conn = get_db()
    row = conn.execute(
        "SELECT id, email, display_name, bio, avatar, streak_freezes, theme_color, status_msg, board_privacy FROM users WHERE email = ?",
        (u["email"],)
    ).fetchone()
    conn.close()
    if row:
        session["user"] = {
            "id": row["id"],
            "email": row["email"],
            "display_name": row["display_name"] or row["email"].split("@")[0],
            "bio": row["bio"] or "",
            "avatar": row["avatar"] or "",
            "streak_freezes": row["streak_freezes"] or 0,
            "theme_color": row["theme_color"] or "blue",
            "status_msg": row["status_msg"] or "",
            "board_privacy": row["board_privacy"] or "friends",
        }


def _calc_streak(user_id, conn):
    rows = conn.execute(
        "SELECT DISTINCT date FROM check_ins WHERE user_id = ? ORDER BY date DESC",
        (user_id,)
    ).fetchall()
    if not rows:
        return 0
    dates = [r[0] for r in rows]
    today = date_cls.today().isoformat()
    yesterday = (date_cls.today() - timedelta(days=1)).isoformat()
    if dates[0] not in (today, yesterday):
        return 0
    streak = 0
    expected = date_cls.fromisoformat(dates[0])
    for d in dates:
        if date_cls.fromisoformat(d) == expected:
            streak += 1
            expected -= timedelta(days=1)
        else:
            break
    return streak


def _calc_longest_streak(user_id, conn):
    rows = conn.execute(
        "SELECT DISTINCT date FROM check_ins WHERE user_id = ? ORDER BY date ASC",
        (user_id,)
    ).fetchall()
    if not rows:
        return 0
    dates = [date_cls.fromisoformat(r[0]) for r in rows]
    max_streak = 1
    cur_streak = 1
    for i in range(1, len(dates)):
        if dates[i] - dates[i - 1] == timedelta(days=1):
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 1
    return max_streak


def _award_badges(user_id, conn):
    earned = {r[0] for r in conn.execute(
        "SELECT badge_id FROM user_badges WHERE user_id = ?", (user_id,)
    ).fetchall()}

    def award(badge_id):
        if badge_id not in earned:
            conn.execute(
                "INSERT OR IGNORE INTO user_badges (user_id, badge_id) VALUES (?, ?)",
                (user_id, badge_id)
            )
            earned.add(badge_id)

    checkin_count = conn.execute(
        "SELECT COUNT(DISTINCT date) FROM check_ins WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    if checkin_count >= 1:
        award("first_checkin")

    streak = _calc_streak(user_id, conn)
    if streak >= 3:
        award("streak_3")
    if streak >= 7:
        award("streak_7")
        conn.execute(
            "UPDATE users SET streak_freezes = streak_freezes + 1 WHERE id = ?", (user_id,)
        )
    if streak >= 14:
        award("streak_14")
    if streak >= 30:
        award("streak_30")
    if streak >= 100:
        award("streak_100")

    friend_count = conn.execute(
        "SELECT COUNT(*) FROM friendships WHERE user_id = ? OR friend_id = ?",
        (user_id, user_id)
    ).fetchone()[0]
    if friend_count >= 1:
        award("first_friend")
    if friend_count >= 5:
        award("social_5")
    if friend_count >= 10:
        award("social_10")

    post_count = conn.execute(
        "SELECT COUNT(*) FROM board_posts WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    if post_count >= 1:
        award("first_post")

    reaction_count = conn.execute(
        "SELECT COUNT(*) FROM reactions WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    if reaction_count >= 1:
        award("first_reaction")

    mood_count = conn.execute(
        "SELECT COUNT(*) FROM check_ins WHERE user_id = ? AND mood != ''", (user_id,)
    ).fetchone()[0]
    if mood_count >= 10:
        award("mood_10")

    group_msg_count = conn.execute(
        "SELECT COUNT(*) FROM group_messages WHERE from_user_id = ?", (user_id,)
    ).fetchone()[0]
    if group_msg_count >= 1:
        award("group_chat_1")

    conn.commit()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if session.get("user"):
        _refresh_session_user()
    today = date_cls.today().isoformat()
    day_of_year = date_cls.today().timetuple().tm_yday
    daily_prompt = DAILY_PROMPTS[day_of_year % len(DAILY_PROMPTS)]
    return render_template("index.html", user=session.get("user"),
                           daily_prompt=daily_prompt, today=today)


@app.route("/signup", methods=["GET"])
def signup_page():
    return render_template("signup.html")


@app.route("/signin", methods=["GET"])
def signin_page():
    return render_template("signin.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("index"))


@app.route("/users")
def users_page():
    if not session.get("user"):
        return redirect(url_for("signin_page"))
    _refresh_session_user()
    current_id = _current_user_id()
    conn = get_db()
    rows = conn.execute(
        "SELECT id, email, display_name, avatar, phone, created_at FROM users ORDER BY created_at DESC"
    ).fetchall()
    friends = set()
    pending_sent = set()
    pending_received = set()
    if current_id:
        friends_rows = conn.execute(
            "SELECT friend_id FROM friendships WHERE user_id = ? UNION SELECT user_id FROM friendships WHERE friend_id = ?",
            (current_id, current_id),
        ).fetchall()
        friends = {r[0] for r in friends_rows}
        sent = conn.execute(
            "SELECT to_user_id FROM friend_requests WHERE from_user_id = ? AND status = 'pending'",
            (current_id,),
        ).fetchall()
        pending_sent = {r[0] for r in sent}
        received = conn.execute(
            "SELECT from_user_id FROM friend_requests WHERE to_user_id = ? AND status = 'pending'",
            (current_id,),
        ).fetchall()
        pending_received = {r[0] for r in received}
    users = []
    current_user_row = None
    for r in rows:
        uid = r["id"]
        if uid == current_id:
            current_user_row = r
            continue
        status = "friend" if uid in friends else (
            "pending_sent" if uid in pending_sent else (
                "pending_received" if uid in pending_received else "none"))
        users.append({
            "id": uid, "email": r["email"],
            "display_name": r["display_name"] or r["email"].split("@")[0],
            "avatar": r["avatar"] or "",
            "phone_masked": _mask_phone(r["phone"]) if r["phone"] else "",
            "created_at": r["created_at"], "friend_status": status, "is_you": False,
        })
    if current_user_row:
        r = current_user_row
        users.insert(0, {
            "id": r["id"], "email": r["email"],
            "display_name": r["display_name"] or r["email"].split("@")[0],
            "avatar": r["avatar"] or "",
            "phone_masked": _mask_phone(r["phone"]) if r["phone"] else "",
            "created_at": r["created_at"], "friend_status": "you", "is_you": True,
        })
    conn.close()
    return render_template("users.html", user=session.get("user"), users=users)


@app.route("/friends")
def friends_page():
    if not session.get("user"):
        return redirect(url_for("signin_page"))
    _refresh_session_user()
    current_id = _current_user_id()
    conn = get_db()
    friend_ids = conn.execute(
        "SELECT friend_id FROM friendships WHERE user_id = ? UNION SELECT user_id FROM friendships WHERE friend_id = ?",
        (current_id, current_id),
    ).fetchall()
    friend_ids = [r[0] for r in friend_ids]
    friends = []
    if friend_ids:
        placeholders = ",".join("?" * len(friend_ids))
        rows = conn.execute(
            f"SELECT id, email, display_name, avatar, status_msg FROM users WHERE id IN ({placeholders}) ORDER BY display_name",
            friend_ids,
        ).fetchall()
        today = date_cls.today().isoformat()
        for r in rows:
            streak = _calc_streak(r["id"], conn)
            checked_in_today = conn.execute(
                "SELECT 1 FROM check_ins WHERE user_id = ? AND date = ?",
                (r["id"], today)
            ).fetchone() is not None
            unread = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE from_user_id = ? AND to_user_id = ? AND read_at IS NULL",
                (r["id"], current_id)
            ).fetchone()[0]
            friends.append({
                "id": r["id"],
                "email": r["email"],
                "display_name": r["display_name"] or r["email"].split("@")[0],
                "avatar": r["avatar"] or "",
                "status_msg": r["status_msg"] or "",
                "streak": streak,
                "checked_in_today": checked_in_today,
                "unread": unread,
            })
    conn.close()
    return render_template("friends.html", user=session.get("user"), friends=friends)


@app.route("/chat/<int:friend_id>")
def chat_page(friend_id):
    if not session.get("user"):
        return redirect(url_for("signin_page"))
    _refresh_session_user()
    current_id = _current_user_id()
    conn = get_db()
    friend = conn.execute(
        "SELECT id, email, display_name, avatar FROM users WHERE id = ?", (friend_id,)
    ).fetchone()
    if not friend:
        conn.close()
        return redirect(url_for("friends_page"))
    conn.execute(
        "UPDATE messages SET read_at = CURRENT_TIMESTAMP WHERE from_user_id = ? AND to_user_id = ? AND read_at IS NULL",
        (friend_id, current_id)
    )
    msgs = conn.execute(
        """SELECT m.id, m.from_user_id, m.content, m.created_at,
                  u.display_name, u.email
           FROM messages m JOIN users u ON u.id = m.from_user_id
           WHERE (m.from_user_id = ? AND m.to_user_id = ?)
              OR (m.from_user_id = ? AND m.to_user_id = ?)
           ORDER BY m.created_at ASC""",
        (current_id, friend_id, friend_id, current_id)
    ).fetchall()
    conn.commit()
    conn.close()
    messages = [
        {
            "id": m["id"],
            "from_me": m["from_user_id"] == current_id,
            "content": m["content"],
            "created_at": m["created_at"],
            "sender_name": m["display_name"] or m["email"].split("@")[0],
        }
        for m in msgs
    ]
    friend_data = {
        "id": friend["id"],
        "display_name": friend["display_name"] or friend["email"].split("@")[0],
        "avatar": friend["avatar"] or "",
    }
    return render_template("chat.html", user=session.get("user"),
                           friend=friend_data, messages=messages)


@app.route("/profile/<username>")
def profile_page(username):
    conn = get_db()
    row = conn.execute(
        "SELECT id, email, display_name, bio, avatar, created_at, theme_color, status_msg, board_privacy FROM users WHERE display_name = ? OR email LIKE ?",
        (username, username + "@%")
    ).fetchone()
    if not row:
        conn.close()
        return "User not found", 404
    profile_id = row["id"]
    streak = _calc_streak(profile_id, conn)
    longest_streak = _calc_longest_streak(profile_id, conn)
    total_checkins = conn.execute(
        "SELECT COUNT(DISTINCT date) FROM check_ins WHERE user_id = ?", (profile_id,)
    ).fetchone()[0]
    badges_rows = conn.execute(
        "SELECT badge_id FROM user_badges WHERE user_id = ?", (profile_id,)
    ).fetchall()
    earned_badge_ids = {r[0] for r in badges_rows}
    badges = [b for b in BADGE_DEFS if b["id"] in earned_badge_ids]
    today = date_cls.today().isoformat()

    current_uid = _current_user_id()
    is_own = current_uid == profile_id
    is_friend = False
    if current_uid and not is_own:
        is_friend = conn.execute(
            "SELECT 1 FROM friendships WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)",
            (current_uid, profile_id, profile_id, current_uid)
        ).fetchone() is not None

    board_privacy = row["board_privacy"] or "friends"
    can_see_board = is_own or board_privacy == "public" or (board_privacy == "friends" and is_friend)

    posts = []
    if can_see_board:
        posts = conn.execute(
            "SELECT id, type, content, pos_left, pos_top, width, color FROM board_posts WHERE user_id = ? AND date = ? ORDER BY created_at ASC",
            (profile_id, today)
        ).fetchall()
        posts = [dict(p) for p in posts]

    pinned_posts = conn.execute(
        "SELECT id, type, content, pos_left, pos_top, width, color, date FROM board_posts WHERE user_id = ? AND pinned = 1 ORDER BY created_at DESC",
        (profile_id,)
    ).fetchall()
    pinned_data = [dict(p) for p in pinned_posts]

    conn.close()
    profile = {
        "id": row["id"],
        "display_name": row["display_name"] or row["email"].split("@")[0],
        "email": row["email"],
        "bio": row["bio"] or "",
        "avatar": row["avatar"] or "",
        "streak": streak,
        "longest_streak": longest_streak,
        "total_checkins": total_checkins,
        "created_at": row["created_at"],
        "theme_color": row["theme_color"] or "blue",
        "status_msg": row["status_msg"] or "",
        "board_privacy": board_privacy,
    }
    theme = PROFILE_THEMES.get(profile["theme_color"], PROFILE_THEMES["blue"])
    return render_template("profile.html", user=session.get("user"),
                           profile=profile, badges=badges, posts=posts,
                           pinned_posts=pinned_data, is_own=is_own,
                           can_see_board=can_see_board, theme=theme,
                           all_themes=PROFILE_THEMES)


@app.route("/leaderboard")
def leaderboard_page():
    if not session.get("user"):
        return redirect(url_for("signin_page"))
    _refresh_session_user()
    current_id = _current_user_id()
    conn = get_db()
    friend_ids = conn.execute(
        "SELECT friend_id FROM friendships WHERE user_id = ? UNION SELECT user_id FROM friendships WHERE friend_id = ?",
        (current_id, current_id),
    ).fetchall()
    friend_ids = [r[0] for r in friend_ids]
    all_ids = [current_id] + friend_ids
    entries = []
    for uid in all_ids:
        row = conn.execute(
            "SELECT id, email, display_name, avatar FROM users WHERE id = ?", (uid,)
        ).fetchone()
        if not row:
            continue
        streak = _calc_streak(uid, conn)
        longest_streak = _calc_longest_streak(uid, conn)
        total_checkins = conn.execute(
            "SELECT COUNT(DISTINCT date) FROM check_ins WHERE user_id = ?", (uid,)
        ).fetchone()[0]
        badges_rows = conn.execute(
            "SELECT badge_id FROM user_badges WHERE user_id = ?", (uid,)
        ).fetchall()
        badge_ids = {r[0] for r in badges_rows}
        top_badges = [b for b in BADGE_DEFS if b["id"] in badge_ids][:3]
        entries.append({
            "id": uid,
            "display_name": row["display_name"] or row["email"].split("@")[0],
            "avatar": row["avatar"] or "",
            "streak": streak,
            "longest_streak": longest_streak,
            "total_checkins": total_checkins,
            "badges": top_badges,
            "is_you": uid == current_id,
        })
    entries.sort(key=lambda x: x["streak"], reverse=True)
    conn.close()
    return render_template("leaderboard.html", user=session.get("user"), entries=entries)


@app.route("/groups")
def groups_page():
    if not session.get("user"):
        return redirect(url_for("signin_page"))
    _refresh_session_user()
    current_id = _current_user_id()
    conn = get_db()
    groups = conn.execute(
        """SELECT gc.id, gc.name, gc.created_at,
                  (SELECT COUNT(*) FROM group_members WHERE group_id = gc.id) as member_count,
                  (SELECT COUNT(*) FROM group_messages WHERE group_id = gc.id) as message_count,
                  (SELECT gm2.content FROM group_messages gm2 WHERE gm2.group_id = gc.id ORDER BY gm2.created_at DESC LIMIT 1) as last_message
           FROM group_chats gc
           JOIN group_members gm ON gm.group_id = gc.id
           WHERE gm.user_id = ?
           ORDER BY gc.created_at DESC""",
        (current_id,)
    ).fetchall()
    groups_data = [dict(g) for g in groups]
    # Get friends for "create group" modal
    friend_ids = conn.execute(
        "SELECT friend_id FROM friendships WHERE user_id = ? UNION SELECT user_id FROM friendships WHERE friend_id = ?",
        (current_id, current_id),
    ).fetchall()
    friend_ids = [r[0] for r in friend_ids]
    friends = []
    if friend_ids:
        placeholders = ",".join("?" * len(friend_ids))
        rows = conn.execute(
            f"SELECT id, display_name, email, avatar FROM users WHERE id IN ({placeholders})",
            friend_ids
        ).fetchall()
        friends = [{"id": r["id"], "display_name": r["display_name"] or r["email"].split("@")[0], "avatar": r["avatar"] or ""} for r in rows]
    conn.close()
    return render_template("groups.html", user=session.get("user"), groups=groups_data, friends=friends)


@app.route("/groups/<int:group_id>")
def group_chat_page(group_id):
    if not session.get("user"):
        return redirect(url_for("signin_page"))
    _refresh_session_user()
    current_id = _current_user_id()
    conn = get_db()
    is_member = conn.execute(
        "SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, current_id)
    ).fetchone()
    if not is_member:
        conn.close()
        return redirect(url_for("groups_page"))
    group = conn.execute("SELECT id, name, created_by FROM group_chats WHERE id = ?", (group_id,)).fetchone()
    if not group:
        conn.close()
        return redirect(url_for("groups_page"))
    msgs = conn.execute(
        """SELECT gm.id, gm.from_user_id, gm.content, gm.created_at,
                  u.display_name, u.email, u.avatar
           FROM group_messages gm JOIN users u ON u.id = gm.from_user_id
           WHERE gm.group_id = ?
           ORDER BY gm.created_at ASC LIMIT 200""",
        (group_id,)
    ).fetchall()
    members = conn.execute(
        """SELECT u.id, u.display_name, u.email, u.avatar
           FROM group_members gm JOIN users u ON u.id = gm.user_id
           WHERE gm.group_id = ?""",
        (group_id,)
    ).fetchall()
    # Friends not yet in group (for adding members)
    member_ids = {m["id"] for m in members}
    friend_ids = conn.execute(
        "SELECT friend_id FROM friendships WHERE user_id = ? UNION SELECT user_id FROM friendships WHERE friend_id = ?",
        (current_id, current_id),
    ).fetchall()
    friend_ids = [r[0] for r in friend_ids if r[0] not in member_ids]
    addable_friends = []
    if friend_ids:
        placeholders = ",".join("?" * len(friend_ids))
        rows = conn.execute(
            f"SELECT id, display_name, email FROM users WHERE id IN ({placeholders})",
            friend_ids
        ).fetchall()
        addable_friends = [{"id": r["id"], "display_name": r["display_name"] or r["email"].split("@")[0]} for r in rows]
    conn.close()
    messages = [
        {
            "id": m["id"],
            "from_me": m["from_user_id"] == current_id,
            "from_user_id": m["from_user_id"],
            "content": m["content"],
            "created_at": m["created_at"],
            "sender_name": m["display_name"] or m["email"].split("@")[0],
            "avatar": m["avatar"] or "",
        }
        for m in msgs
    ]
    members_data = [
        {
            "id": mb["id"],
            "display_name": mb["display_name"] or mb["email"].split("@")[0],
            "avatar": mb["avatar"] or "",
        }
        for mb in members
    ]
    group_data = {"id": group["id"], "name": group["name"], "created_by": group["created_by"]}
    return render_template("group_chat.html", user=session.get("user"),
                           group=group_data, messages=messages,
                           members=members_data, addable_friends=addable_friends,
                           current_id=current_id)


# ---------------------------------------------------------------------------
# Auth APIs
# ---------------------------------------------------------------------------

@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    phone = normalize_phone(data.get("phone") or "")
    password = data.get("password") or ""
    if not is_gmail(email):
        return jsonify({"ok": False, "error": "Please use a Gmail account"}), 400
    if len(phone) < 10:
        return jsonify({"ok": False, "error": "Invalid phone number"}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "Password must be at least 6 characters"}), 400
    display_name = email.split("@")[0]
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (email, phone, password_hash, display_name) VALUES (?, ?, ?, ?)",
            (email, phone, hash_password(password), display_name),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        user_id = row["id"] if row else None
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"ok": False, "error": "An account with this email or phone already exists"}), 400
    conn.close()
    session["user"] = {"id": user_id, "email": email, "display_name": display_name, "bio": "", "avatar": "",
                       "theme_color": "blue", "status_msg": "", "board_privacy": "friends"}
    return jsonify({"ok": True, "redirect": url_for("index")})


@app.route("/api/send-verification", methods=["POST"])
def send_verification():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    phone = normalize_phone(data.get("phone") or "")
    if not is_gmail(email):
        return jsonify({"ok": False, "error": "Please use a Gmail account (@gmail.com)"}), 400
    if len(phone) < 10:
        return jsonify({"ok": False, "error": "Please enter a valid phone number"}), 400
    conn = get_db()
    existing = conn.execute("SELECT 1 FROM users WHERE email = ? OR phone = ?", (email, phone)).fetchone()
    conn.close()
    if existing:
        return jsonify({"ok": False, "error": "An account with this email or phone already exists"}), 400
    code = generate_code()
    VERIFICATION_CODES[phone] = {"code": code, "email": email}
    msg = f"Your Kindred verification code is: {code}"
    if send_sms_via_twilio(phone, msg):
        return jsonify({"ok": True, "message": "Verification code sent"})
    return jsonify({"ok": False, "error": "Failed to send SMS"}), 500


@app.route("/api/verify-and-signup", methods=["POST"])
def verify_and_signup():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    phone = normalize_phone(data.get("phone") or "")
    password = data.get("password") or ""
    code = (data.get("code") or "").strip()
    if not is_gmail(email):
        return jsonify({"ok": False, "error": "Please use a Gmail account"}), 400
    if len(phone) < 10:
        return jsonify({"ok": False, "error": "Invalid phone number"}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "Password must be at least 6 characters"}), 400
    if len(code) != 6 or not code.isdigit():
        return jsonify({"ok": False, "error": "Please enter the 6-digit verification code"}), 400
    stored = VERIFICATION_CODES.get(phone)
    if not stored or stored.get("email") != email:
        return jsonify({"ok": False, "error": "Please request a new verification code"}), 400
    if stored.get("code") != code:
        return jsonify({"ok": False, "error": "Invalid verification code"}), 400
    del VERIFICATION_CODES[phone]
    display_name = email.split("@")[0] if email else ""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (email, phone, password_hash, display_name) VALUES (?, ?, ?, ?)",
            (email, phone, hash_password(password), display_name),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        user_id = row["id"] if row else None
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"ok": False, "error": "An account with this email or phone already exists"}), 400
    conn.close()
    session["user"] = {"id": user_id, "email": email, "display_name": display_name, "bio": "", "avatar": "",
                       "theme_color": "blue", "status_msg": "", "board_privacy": "friends"}
    return jsonify({"ok": True, "redirect": url_for("index")})


@app.route("/api/signin", methods=["POST"])
def signin():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"ok": False, "error": "Email and password are required"}), 400
    conn = get_db()
    row = conn.execute(
        "SELECT id, email, password_hash, display_name, bio, avatar, theme_color, status_msg, board_privacy FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    if not row or not check_password(password, row["password_hash"]):
        return jsonify({"ok": False, "error": "Invalid email or password"}), 401
    display_name = row["display_name"] if row["display_name"] else row["email"].split("@")[0]
    session["user"] = {
        "id": row["id"], "email": row["email"], "display_name": display_name,
        "bio": row["bio"] or "", "avatar": row["avatar"] or "",
        "theme_color": row["theme_color"] or "blue",
        "status_msg": row["status_msg"] or "",
        "board_privacy": row["board_privacy"] or "friends",
    }
    return jsonify({"ok": True, "redirect": url_for("index")})


# ---------------------------------------------------------------------------
# Friend APIs
# ---------------------------------------------------------------------------

@app.route("/api/friend-request", methods=["POST"])
def api_send_friend_request():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    data = request.get_json() or {}
    to_user_id = data.get("to_user_id")
    if not to_user_id:
        return jsonify({"ok": False, "error": "User required"}), 400
    try:
        to_user_id = int(to_user_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid user"}), 400
    from_user_id = _current_user_id()
    if from_user_id == to_user_id:
        return jsonify({"ok": False, "error": "Cannot add yourself"}), 400
    conn = get_db()
    existing = conn.execute(
        "SELECT 1 FROM friendships WHERE (user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?)",
        (from_user_id, to_user_id, to_user_id, from_user_id),
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({"ok": False, "error": "Already friends"}), 400
    req = conn.execute(
        "SELECT id, status, from_user_id FROM friend_requests WHERE (from_user_id = ? AND to_user_id = ?) OR (from_user_id = ? AND to_user_id = ?)",
        (from_user_id, to_user_id, to_user_id, from_user_id),
    ).fetchone()
    if req and req["status"] == "pending":
        conn.close()
        return jsonify({"ok": False, "error": "Request already sent" if req["from_user_id"] == from_user_id else "They already sent you a request"}), 400
    conn.execute(
        "INSERT OR IGNORE INTO friend_requests (from_user_id, to_user_id, status) VALUES (?, ?, 'pending')",
        (from_user_id, to_user_id),
    )
    # Send notification
    from_name = session["user"].get("display_name") or session["user"].get("email", "").split("@")[0]
    conn.execute(
        "INSERT INTO notifications (user_id, from_user_id, type, message) VALUES (?, ?, 'friend_request', ?)",
        (to_user_id, from_user_id, f"{from_name} sent you a friend request!")
    )
    conn.commit()
    _award_badges(from_user_id, conn)
    conn.close()
    return jsonify({"ok": True, "status": "pending_sent"})


@app.route("/api/friend-request/accept", methods=["POST"])
def api_accept_friend_request():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    data = request.get_json() or {}
    from_user_id = data.get("from_user_id")
    if not from_user_id:
        return jsonify({"ok": False, "error": "User required"}), 400
    try:
        from_user_id = int(from_user_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid user"}), 400
    to_user_id = _current_user_id()
    conn = get_db()
    req = conn.execute(
        "SELECT id FROM friend_requests WHERE from_user_id = ? AND to_user_id = ? AND status = 'pending'",
        (from_user_id, to_user_id),
    ).fetchone()
    if not req:
        conn.close()
        return jsonify({"ok": False, "error": "Request not found"}), 404
    conn.execute("UPDATE friend_requests SET status = 'accepted' WHERE id = ?", (req["id"],))
    conn.execute("INSERT OR IGNORE INTO friendships (user_id, friend_id) VALUES (?, ?)", (to_user_id, from_user_id))
    conn.execute("INSERT OR IGNORE INTO friendships (user_id, friend_id) VALUES (?, ?)", (from_user_id, to_user_id))
    to_name = session["user"].get("display_name") or session["user"].get("email", "").split("@")[0]
    conn.execute(
        "INSERT INTO notifications (user_id, from_user_id, type, message) VALUES (?, ?, 'friend_accepted', ?)",
        (from_user_id, to_user_id, f"{to_name} accepted your friend request!")
    )
    conn.commit()
    _award_badges(to_user_id, conn)
    _award_badges(from_user_id, conn)
    conn.close()
    return jsonify({"ok": True, "status": "friend"})


@app.route("/api/friend-request/decline", methods=["POST"])
def api_decline_friend_request():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    data = request.get_json() or {}
    from_user_id = data.get("from_user_id")
    if not from_user_id:
        return jsonify({"ok": False, "error": "User required"}), 400
    try:
        from_user_id = int(from_user_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid user"}), 400
    to_user_id = _current_user_id()
    conn = get_db()
    req = conn.execute(
        "SELECT id FROM friend_requests WHERE from_user_id = ? AND to_user_id = ? AND status = 'pending'",
        (from_user_id, to_user_id),
    ).fetchone()
    if not req:
        conn.close()
        return jsonify({"ok": False, "error": "Request not found"}), 404
    conn.execute("UPDATE friend_requests SET status = 'declined' WHERE id = ?", (req["id"],))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Check-in API
# ---------------------------------------------------------------------------

@app.route("/api/checkin", methods=["POST"])
def api_checkin():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    today = date_cls.today().isoformat()
    data = request.get_json() or {}
    mood = (data.get("mood") or "").strip()[:10]
    conn = get_db()
    conn.execute(
        "INSERT INTO check_ins (user_id, date, mood) VALUES (?, ?, ?)", (user_id, today, mood)
    )
    conn.commit()
    streak = _calc_streak(user_id, conn)
    _award_badges(user_id, conn)
    # Notify friends of check-in
    from_name = session["user"].get("display_name") or session["user"].get("email", "").split("@")[0]
    friend_ids = conn.execute(
        "SELECT friend_id FROM friendships WHERE user_id = ? UNION SELECT user_id FROM friendships WHERE friend_id = ?",
        (user_id, user_id),
    ).fetchall()
    for fid in friend_ids:
        conn.execute(
            "INSERT INTO notifications (user_id, from_user_id, type, message) VALUES (?, ?, 'friend_checkin', ?)",
            (fid[0], user_id, f"{from_name} just checked in! {mood if mood else ''}")
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "streak": streak, "date": today})


@app.route("/api/checkin/status")
def api_checkin_status():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    today = date_cls.today().isoformat()
    conn = get_db()
    count_today = conn.execute(
        "SELECT COUNT(*) FROM check_ins WHERE user_id = ? AND date = ?", (user_id, today)
    ).fetchone()[0]
    streak = _calc_streak(user_id, conn)
    freeze_row = conn.execute(
        "SELECT streak_freezes FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    freezes = freeze_row[0] if freeze_row else 0
    # Get mood for today if checked in
    mood_row = conn.execute(
        "SELECT mood FROM check_ins WHERE user_id = ? AND date = ? ORDER BY created_at DESC LIMIT 1",
        (user_id, today)
    ).fetchone()
    today_mood = mood_row["mood"] if mood_row else ""
    conn.close()
    return jsonify({"ok": True, "checked_in_today": count_today > 0,
                    "count_today": count_today, "streak": streak, "freezes": freezes,
                    "today_mood": today_mood})


@app.route("/api/checkin/history")
def api_checkin_history():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    conn = get_db()
    rows = conn.execute(
        "SELECT date, COUNT(*) as cnt, MAX(mood) as mood FROM check_ins WHERE user_id = ? GROUP BY date ORDER BY date DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify({"ok": True, "history": [{"date": r[0], "count": r[1], "mood": r[2] or ""} for r in rows]})


@app.route("/api/checkin/friends")
def api_checkin_friends():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    today = date_cls.today().isoformat()
    conn = get_db()
    friend_ids = conn.execute(
        "SELECT friend_id FROM friendships WHERE user_id = ? UNION SELECT user_id FROM friendships WHERE friend_id = ?",
        (user_id, user_id),
    ).fetchall()
    friend_ids = [r[0] for r in friend_ids]
    names = []
    if friend_ids:
        placeholders = ",".join("?" * len(friend_ids))
        rows = conn.execute(
            f"""SELECT u.display_name, u.email FROM check_ins c
                JOIN users u ON u.id = c.user_id
                WHERE c.user_id IN ({placeholders}) AND c.date = ?
                GROUP BY c.user_id""",
            friend_ids + [today]
        ).fetchall()
        names = [r["display_name"] or r["email"].split("@")[0] for r in rows]
    conn.close()
    return jsonify({"ok": True, "count": len(names), "names": names})


@app.route("/api/streak-freeze/use", methods=["POST"])
def api_use_streak_freeze():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    conn = get_db()
    row = conn.execute("SELECT streak_freezes FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or row[0] < 1:
        conn.close()
        return jsonify({"ok": False, "error": "No streak freezes available"}), 400
    yesterday = (date_cls.today() - timedelta(days=1)).isoformat()
    already = conn.execute(
        "SELECT 1 FROM check_ins WHERE user_id = ? AND date = ?", (user_id, yesterday)
    ).fetchone()
    if already:
        conn.close()
        return jsonify({"ok": False, "error": "You already checked in yesterday"}), 400
    conn.execute("INSERT INTO check_ins (user_id, date) VALUES (?, ?)", (user_id, yesterday))
    conn.execute("UPDATE users SET streak_freezes = streak_freezes - 1 WHERE id = ?", (user_id,))
    conn.commit()
    streak = _calc_streak(user_id, conn)
    conn.close()
    _refresh_session_user()
    return jsonify({"ok": True, "streak": streak})


# ---------------------------------------------------------------------------
# Weekly Recap API
# ---------------------------------------------------------------------------

@app.route("/api/weekly-recap")
def api_weekly_recap():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    conn = get_db()
    today = date_cls.today()
    week_start = (today - timedelta(days=6)).isoformat()
    my_checkins = conn.execute(
        "SELECT date, mood FROM check_ins WHERE user_id = ? AND date >= ? GROUP BY date ORDER BY date",
        (user_id, week_start)
    ).fetchall()
    friend_ids = conn.execute(
        "SELECT friend_id FROM friendships WHERE user_id = ? UNION SELECT user_id FROM friendships WHERE friend_id = ?",
        (user_id, user_id),
    ).fetchall()
    friend_ids = [r[0] for r in friend_ids]
    friends_activity = []
    for fid in friend_ids:
        row = conn.execute("SELECT display_name, email, avatar, streak_freezes FROM users WHERE id = ?", (fid,)).fetchone()
        if not row:
            continue
        checkin_count = conn.execute(
            "SELECT COUNT(DISTINCT date) FROM check_ins WHERE user_id = ? AND date >= ?",
            (fid, week_start)
        ).fetchone()[0]
        streak = _calc_streak(fid, conn)
        friends_activity.append({
            "id": fid,
            "display_name": row["display_name"] or row["email"].split("@")[0],
            "avatar": row["avatar"] or "",
            "checkins_this_week": checkin_count,
            "streak": streak,
        })
    conn.close()
    return jsonify({
        "ok": True,
        "week_start": week_start,
        "week_end": today.isoformat(),
        "my_checkins": [{"date": r["date"], "mood": r["mood"] or ""} for r in my_checkins],
        "friends_activity": sorted(friends_activity, key=lambda x: x["checkins_this_week"], reverse=True),
    })


# ---------------------------------------------------------------------------
# Challenges API
# ---------------------------------------------------------------------------

@app.route("/api/challenges")
def api_challenges():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    today = date_cls.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    conn = get_db()
    results = []
    for ch in WEEKLY_CHALLENGES:
        progress = 0
        if ch["type"] == "checkin":
            progress = conn.execute(
                "SELECT COUNT(DISTINCT date) FROM check_ins WHERE user_id = ? AND date >= ?",
                (user_id, week_start)
            ).fetchone()[0]
        elif ch["type"] == "posts":
            progress = conn.execute(
                "SELECT COUNT(*) FROM board_posts WHERE user_id = ? AND date >= ?",
                (user_id, week_start)
            ).fetchone()[0]
        elif ch["type"] == "reactions":
            progress = conn.execute(
                "SELECT COUNT(*) FROM reactions WHERE user_id = ? AND created_at >= ?",
                (user_id, week_start + " 00:00:00")
            ).fetchone()[0]
        elif ch["type"] == "friends_checkin":
            fids = conn.execute(
                "SELECT friend_id FROM friendships WHERE user_id = ? UNION SELECT user_id FROM friendships WHERE friend_id = ?",
                (user_id, user_id),
            ).fetchall()
            fids = [r[0] for r in fids]
            if fids:
                placeholders = ",".join("?" * len(fids))
                progress = conn.execute(
                    f"SELECT COUNT(DISTINCT user_id) FROM check_ins WHERE user_id IN ({placeholders}) AND date >= ?",
                    fids + [week_start]
                ).fetchone()[0]
        completed = progress >= ch["target"]
        if completed:
            # Award challenge badge
            earned = conn.execute("SELECT 1 FROM user_badges WHERE user_id = ? AND badge_id = 'challenge_1'", (user_id,)).fetchone()
            if not earned:
                conn.execute("INSERT OR IGNORE INTO user_badges (user_id, badge_id) VALUES (?, 'challenge_1')", (user_id,))
                conn.commit()
        results.append({**ch, "progress": min(progress, ch["target"]), "completed": completed, "week_start": week_start})
    conn.close()
    return jsonify({"ok": True, "challenges": results})


# ---------------------------------------------------------------------------
# Notifications API
# ---------------------------------------------------------------------------

@app.route("/api/notifications")
def api_notifications():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    conn = get_db()
    rows = conn.execute(
        """SELECT n.id, n.type, n.message, n.read, n.created_at,
                  u.display_name, u.avatar, n.from_user_id
           FROM notifications n LEFT JOIN users u ON u.id = n.from_user_id
           WHERE n.user_id = ? ORDER BY n.created_at DESC LIMIT 50""",
        (user_id,)
    ).fetchall()
    unread_count = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read = 0", (user_id,)
    ).fetchone()[0]
    conn.close()
    return jsonify({"ok": True, "notifications": [dict(r) for r in rows], "unread_count": unread_count})


@app.route("/api/notifications/read", methods=["POST"])
def api_notifications_read():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    conn = get_db()
    conn.execute("UPDATE notifications SET read = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Nudge API
# ---------------------------------------------------------------------------

@app.route("/api/nudge", methods=["POST"])
def api_nudge():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    data = request.get_json() or {}
    to_user_id = data.get("to_user_id")
    if not to_user_id:
        return jsonify({"ok": False, "error": "User required"}), 400
    try:
        to_user_id = int(to_user_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid user"}), 400
    from_user_id = _current_user_id()
    from_name = session["user"].get("display_name") or session["user"].get("email", "").split("@")[0]
    conn = get_db()
    is_friend = conn.execute(
        "SELECT 1 FROM friendships WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)",
        (from_user_id, to_user_id, to_user_id, from_user_id)
    ).fetchone()
    if not is_friend:
        conn.close()
        return jsonify({"ok": False, "error": "Not friends"}), 400
    conn.execute(
        "INSERT INTO notifications (user_id, from_user_id, type, message) VALUES (?, ?, 'nudge', ?)",
        (to_user_id, from_user_id, f"{from_name} nudged you to check in! 👋")
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Shared Streak API
# ---------------------------------------------------------------------------

@app.route("/api/friends/<int:friend_id>/shared-streak")
def api_shared_streak(friend_id):
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    conn = get_db()
    my_dates = set(r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM check_ins WHERE user_id = ?", (user_id,)
    ).fetchall())
    friend_dates = set(r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM check_ins WHERE user_id = ?", (friend_id,)
    ).fetchall())
    conn.close()
    shared = sorted(my_dates & friend_dates, reverse=True)
    if not shared:
        return jsonify({"ok": True, "streak": 0})
    today = date_cls.today().isoformat()
    yesterday = (date_cls.today() - timedelta(days=1)).isoformat()
    if shared[0] not in (today, yesterday):
        return jsonify({"ok": True, "streak": 0})
    streak = 0
    expected = date_cls.fromisoformat(shared[0])
    for d in shared:
        if date_cls.fromisoformat(d) == expected:
            streak += 1
            expected -= timedelta(days=1)
        else:
            break
    return jsonify({"ok": True, "streak": streak})


# ---------------------------------------------------------------------------
# Board API
# ---------------------------------------------------------------------------

@app.route("/api/board", methods=["GET"])
def api_board_get():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = request.args.get("user_id", type=int) or _current_user_id()
    date_str = request.args.get("date", date_cls.today().isoformat())
    conn = get_db()
    posts = conn.execute(
        "SELECT id, type, content, pos_left, pos_top, width, color, pinned FROM board_posts WHERE user_id = ? AND date = ? ORDER BY created_at ASC",
        (user_id, date_str)
    ).fetchall()
    result = []
    for p in posts:
        reaction_rows = conn.execute(
            "SELECT emoji, COUNT(*) as cnt, MAX(CASE WHEN user_id = ? THEN 1 ELSE 0 END) as mine FROM reactions WHERE post_id = ? GROUP BY emoji",
            (_current_user_id(), p["id"])
        ).fetchall()
        reactions = [{"emoji": r["emoji"], "count": r["cnt"], "mine": bool(r["mine"])} for r in reaction_rows]
        result.append({
            "id": p["id"], "type": p["type"], "content": p["content"],
            "left": p["pos_left"], "top": p["pos_top"], "width": p["width"],
            "color": p["color"], "pinned": bool(p["pinned"]), "reactions": reactions,
        })
    conn.close()
    return jsonify({"ok": True, "posts": result})


@app.route("/api/board", methods=["POST"])
def api_board_post():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    data = request.get_json() or {}
    user_id = _current_user_id()
    post_type = data.get("type", "text")
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"ok": False, "error": "Content required"}), 400
    date_str = data.get("date", date_cls.today().isoformat())
    pos_left = data.get("left", 20)
    pos_top = data.get("top", 60)
    width = data.get("width", 200)
    color = data.get("color", "default")
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO board_posts (user_id, date, type, content, pos_left, pos_top, width, color) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, date_str, post_type, content, pos_left, pos_top, width, color)
    )
    new_id = cur.lastrowid
    conn.commit()
    _award_badges(user_id, conn)
    conn.close()
    return jsonify({"ok": True, "id": new_id})


@app.route("/api/board/upload-image", methods=["POST"])
def api_board_upload_image():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename or not allowed_file(f.filename):
        return jsonify({"ok": False, "error": "Invalid file type"}), 400
    user_id = _current_user_id()
    ext = f.filename.rsplit(".", 1)[1].lower()
    filename = secure_filename(f"board_{user_id}_{uuid.uuid4().hex[:8]}.{ext}")
    f.save(UPLOAD_FOLDER / filename)
    return jsonify({"ok": True, "url": f"/uploads/{filename}"})


@app.route("/api/board/<int:post_id>", methods=["PATCH"])
def api_board_patch(post_id):
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    data = request.get_json() or {}
    user_id = _current_user_id()
    conn = get_db()
    post = conn.execute("SELECT user_id FROM board_posts WHERE id = ?", (post_id,)).fetchone()
    if not post or post["user_id"] != user_id:
        conn.close()
        return jsonify({"ok": False, "error": "Not found"}), 404
    fields = []
    values = []
    if "left" in data:
        fields.append("pos_left = ?"); values.append(data["left"])
    if "top" in data:
        fields.append("pos_top = ?"); values.append(data["top"])
    if "width" in data:
        fields.append("width = ?"); values.append(data["width"])
    if "color" in data:
        fields.append("color = ?"); values.append(data["color"])
    if fields:
        values.append(post_id)
        conn.execute(f"UPDATE board_posts SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/board/<int:post_id>", methods=["DELETE"])
def api_board_delete(post_id):
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    conn = get_db()
    post = conn.execute("SELECT user_id FROM board_posts WHERE id = ?", (post_id,)).fetchone()
    if not post or post["user_id"] != user_id:
        conn.close()
        return jsonify({"ok": False, "error": "Not found"}), 404
    conn.execute("DELETE FROM reactions WHERE post_id = ?", (post_id,))
    conn.execute("DELETE FROM board_posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/board/<int:post_id>/pin", methods=["POST"])
def api_board_pin(post_id):
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    conn = get_db()
    post = conn.execute("SELECT user_id, pinned FROM board_posts WHERE id = ?", (post_id,)).fetchone()
    if not post or post["user_id"] != user_id:
        conn.close()
        return jsonify({"ok": False, "error": "Not found"}), 404
    new_pinned = 0 if post["pinned"] else 1
    conn.execute("UPDATE board_posts SET pinned = ? WHERE id = ?", (new_pinned, post_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "pinned": bool(new_pinned)})


@app.route("/api/board/<int:post_id>/react", methods=["POST"])
def api_board_react(post_id):
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    data = request.get_json() or {}
    emoji = (data.get("emoji") or "").strip()
    if not emoji:
        return jsonify({"ok": False, "error": "Emoji required"}), 400
    user_id = _current_user_id()
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM reactions WHERE post_id = ? AND user_id = ? AND emoji = ?",
        (post_id, user_id, emoji)
    ).fetchone()
    if existing:
        conn.execute("DELETE FROM reactions WHERE id = ?", (existing["id"],))
        added = False
    else:
        conn.execute(
            "INSERT INTO reactions (post_id, user_id, emoji) VALUES (?, ?, ?)",
            (post_id, user_id, emoji)
        )
        added = True
        _award_badges(user_id, conn)
    conn.commit()
    count = conn.execute(
        "SELECT COUNT(*) FROM reactions WHERE post_id = ? AND emoji = ?", (post_id, emoji)
    ).fetchone()[0]
    conn.close()
    return jsonify({"ok": True, "added": added, "count": count})


# ---------------------------------------------------------------------------
# Activity Feed API
# ---------------------------------------------------------------------------

@app.route("/api/feed")
def api_feed():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    today = date_cls.today().isoformat()
    conn = get_db()
    friend_ids = conn.execute(
        "SELECT friend_id FROM friendships WHERE user_id = ? UNION SELECT user_id FROM friendships WHERE friend_id = ?",
        (user_id, user_id),
    ).fetchall()
    friend_ids = [r[0] for r in friend_ids]
    if not friend_ids:
        conn.close()
        return jsonify({"ok": True, "posts": []})
    placeholders = ",".join("?" * len(friend_ids))
    rows = conn.execute(
        f"""SELECT bp.id, bp.user_id, bp.type, bp.content, bp.color, bp.created_at,
                   u.display_name, u.email, u.avatar
            FROM board_posts bp JOIN users u ON u.id = bp.user_id
            WHERE bp.user_id IN ({placeholders}) AND bp.date = ?
            ORDER BY bp.created_at DESC LIMIT 50""",
        friend_ids + [today]
    ).fetchall()
    result = []
    for r in rows:
        reaction_rows = conn.execute(
            "SELECT emoji, COUNT(*) as cnt, MAX(CASE WHEN user_id = ? THEN 1 ELSE 0 END) as mine FROM reactions WHERE post_id = ? GROUP BY emoji",
            (user_id, r["id"])
        ).fetchall()
        reactions = [{"emoji": rx["emoji"], "count": rx["cnt"], "mine": bool(rx["mine"])} for rx in reaction_rows]
        result.append({
            "id": r["id"],
            "user_id": r["user_id"],
            "type": r["type"],
            "content": r["content"],
            "color": r["color"],
            "created_at": r["created_at"],
            "display_name": r["display_name"] or r["email"].split("@")[0],
            "avatar": r["avatar"] or "",
            "reactions": reactions,
        })
    conn.close()
    return jsonify({"ok": True, "posts": result})


# ---------------------------------------------------------------------------
# Messages API
# ---------------------------------------------------------------------------

@app.route("/api/messages", methods=["POST"])
def api_send_message():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    data = request.get_json() or {}
    to_user_id = data.get("to_user_id")
    content = (data.get("content") or "").strip()
    if not to_user_id or not content:
        return jsonify({"ok": False, "error": "Recipient and content required"}), 400
    from_user_id = _current_user_id()
    conn = get_db()
    conn.execute(
        "INSERT INTO messages (from_user_id, to_user_id, content) VALUES (?, ?, ?)",
        (from_user_id, int(to_user_id), content)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/messages/unread")
def api_messages_unread():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE to_user_id = ? AND read_at IS NULL", (user_id,)
    ).fetchone()[0]
    conn.close()
    return jsonify({"ok": True, "count": count})


# ---------------------------------------------------------------------------
# Groups API
# ---------------------------------------------------------------------------

@app.route("/api/groups", methods=["GET"])
def api_groups_list():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    conn = get_db()
    groups = conn.execute(
        """SELECT gc.id, gc.name, gc.created_at
           FROM group_chats gc
           JOIN group_members gm ON gm.group_id = gc.id
           WHERE gm.user_id = ?
           ORDER BY gc.created_at DESC""",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify({"ok": True, "groups": [dict(g) for g in groups]})


@app.route("/api/groups", methods=["POST"])
def api_groups_create():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()[:100]
    member_ids = data.get("member_ids") or []
    if not name:
        return jsonify({"ok": False, "error": "Group name required"}), 400
    user_id = _current_user_id()
    conn = get_db()
    cur = conn.execute("INSERT INTO group_chats (name, created_by) VALUES (?, ?)", (name, user_id))
    group_id = cur.lastrowid
    conn.execute("INSERT OR IGNORE INTO group_members (group_id, user_id) VALUES (?, ?)", (group_id, user_id))
    for mid in member_ids:
        try:
            mid = int(mid)
            is_friend = conn.execute(
                "SELECT 1 FROM friendships WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)",
                (user_id, mid, mid, user_id)
            ).fetchone()
            if is_friend:
                conn.execute("INSERT OR IGNORE INTO group_members (group_id, user_id) VALUES (?, ?)", (group_id, mid))
        except (TypeError, ValueError):
            pass
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "group_id": group_id})


@app.route("/api/groups/<int:group_id>/members", methods=["POST"])
def api_groups_add_member(group_id):
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    data = request.get_json() or {}
    new_user_id = data.get("user_id")
    if not new_user_id:
        return jsonify({"ok": False, "error": "User required"}), 400
    try:
        new_user_id = int(new_user_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid user"}), 400
    current_id = _current_user_id()
    conn = get_db()
    is_member = conn.execute(
        "SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, current_id)
    ).fetchone()
    if not is_member:
        conn.close()
        return jsonify({"ok": False, "error": "Not a member"}), 403
    conn.execute("INSERT OR IGNORE INTO group_members (group_id, user_id) VALUES (?, ?)", (group_id, new_user_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/groups/<int:group_id>/messages", methods=["GET"])
def api_group_messages_get(group_id):
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    conn = get_db()
    is_member = conn.execute(
        "SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, user_id)
    ).fetchone()
    if not is_member:
        conn.close()
        return jsonify({"ok": False, "error": "Not a member"}), 403
    msgs = conn.execute(
        """SELECT gm.id, gm.from_user_id, gm.content, gm.created_at,
                  u.display_name, u.email
           FROM group_messages gm JOIN users u ON u.id = gm.from_user_id
           WHERE gm.group_id = ?
           ORDER BY gm.created_at ASC LIMIT 200""",
        (group_id,)
    ).fetchall()
    conn.close()
    return jsonify({"ok": True, "messages": [
        {
            "id": m["id"],
            "from_user_id": m["from_user_id"],
            "from_me": m["from_user_id"] == user_id,
            "content": m["content"],
            "created_at": m["created_at"],
            "sender_name": m["display_name"] or m["email"].split("@")[0],
        }
        for m in msgs
    ]})


@app.route("/api/groups/<int:group_id>/messages", methods=["POST"])
def api_group_messages_post(group_id):
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    data = request.get_json() or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"ok": False, "error": "Content required"}), 400
    user_id = _current_user_id()
    conn = get_db()
    is_member = conn.execute(
        "SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, user_id)
    ).fetchone()
    if not is_member:
        conn.close()
        return jsonify({"ok": False, "error": "Not a member"}), 403
    conn.execute(
        "INSERT INTO group_messages (group_id, from_user_id, content) VALUES (?, ?, ?)",
        (group_id, user_id, content)
    )
    _award_badges(user_id, conn)
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Custom Prompts API
# ---------------------------------------------------------------------------

@app.route("/api/custom-prompts", methods=["GET"])
def api_custom_prompts_get():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    conn = get_db()
    rows = conn.execute(
        "SELECT id, prompt FROM custom_prompts WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify({"ok": True, "prompts": [{"id": r["id"], "prompt": r["prompt"]} for r in rows]})


@app.route("/api/custom-prompts", methods=["POST"])
def api_custom_prompts_post():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    data = request.get_json() or {}
    prompt = (data.get("prompt") or "").strip()[:200]
    if not prompt:
        return jsonify({"ok": False, "error": "Prompt required"}), 400
    user_id = _current_user_id()
    conn = get_db()
    conn.execute("INSERT INTO custom_prompts (user_id, prompt) VALUES (?, ?)", (user_id, prompt))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/custom-prompts/<int:prompt_id>", methods=["DELETE"])
def api_custom_prompts_delete(prompt_id):
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    conn = get_db()
    conn.execute("DELETE FROM custom_prompts WHERE id = ? AND user_id = ?", (prompt_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Search API
# ---------------------------------------------------------------------------

@app.route("/api/search/users")
def api_search_users():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    q = (request.args.get("q") or "").strip()[:50]
    if not q:
        return jsonify({"ok": True, "users": []})
    current_id = _current_user_id()
    conn = get_db()
    rows = conn.execute(
        "SELECT id, display_name, email, avatar FROM users WHERE display_name LIKE ? AND id != ? LIMIT 20",
        (f"%{q}%", current_id)
    ).fetchall()
    friends = set()
    pending_sent = set()
    if rows:
        friend_rows = conn.execute(
            "SELECT friend_id FROM friendships WHERE user_id = ? UNION SELECT user_id FROM friendships WHERE friend_id = ?",
            (current_id, current_id),
        ).fetchall()
        friends = {r[0] for r in friend_rows}
        sent = conn.execute(
            "SELECT to_user_id FROM friend_requests WHERE from_user_id = ? AND status = 'pending'",
            (current_id,),
        ).fetchall()
        pending_sent = {r[0] for r in sent}
    conn.close()
    return jsonify({"ok": True, "users": [
        {
            "id": r["id"],
            "display_name": r["display_name"] or r["email"].split("@")[0],
            "avatar": r["avatar"] or "",
            "friend_status": "friend" if r["id"] in friends else ("pending_sent" if r["id"] in pending_sent else "none"),
        }
        for r in rows
    ]})


# ---------------------------------------------------------------------------
# Profile API
# ---------------------------------------------------------------------------

@app.route("/api/profile/update", methods=["POST"])
def api_profile_update():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    data = request.get_json() or {}
    user_id = _current_user_id()
    display_name = (data.get("display_name") or "").strip()[:50]
    bio = (data.get("bio") or "").strip()[:300]
    status_msg = (data.get("status_msg") or "").strip()[:100]
    theme_color = (data.get("theme_color") or "blue").strip()[:20]
    board_privacy = (data.get("board_privacy") or "friends").strip()
    if theme_color not in PROFILE_THEMES:
        theme_color = "blue"
    if board_privacy not in ("public", "friends"):
        board_privacy = "friends"
    conn = get_db()
    if display_name:
        conn.execute(
            "UPDATE users SET display_name = ?, bio = ?, status_msg = ?, theme_color = ?, board_privacy = ? WHERE id = ?",
            (display_name, bio, status_msg, theme_color, board_privacy, user_id)
        )
    else:
        conn.execute(
            "UPDATE users SET bio = ?, status_msg = ?, theme_color = ?, board_privacy = ? WHERE id = ?",
            (bio, status_msg, theme_color, board_privacy, user_id)
        )
    conn.commit()
    conn.close()
    _refresh_session_user()
    return jsonify({"ok": True})


@app.route("/api/avatar/upload", methods=["POST"])
def api_avatar_upload():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename or not allowed_file(f.filename):
        return jsonify({"ok": False, "error": "Invalid file type"}), 400
    user_id = _current_user_id()
    ext = f.filename.rsplit(".", 1)[1].lower()
    filename = secure_filename(f"avatar_{user_id}.{ext}")
    f.save(UPLOAD_FOLDER / filename)
    conn = get_db()
    conn.execute("UPDATE users SET avatar = ? WHERE id = ?", (filename, user_id))
    conn.commit()
    conn.close()
    _refresh_session_user()
    return jsonify({"ok": True, "filename": filename})


# ---------------------------------------------------------------------------
# Badges & Leaderboard API
# ---------------------------------------------------------------------------

@app.route("/api/badges")
def api_badges():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    conn = get_db()
    rows = conn.execute(
        "SELECT badge_id, earned_at FROM user_badges WHERE user_id = ? ORDER BY earned_at ASC",
        (user_id,)
    ).fetchall()
    conn.close()
    earned = {r[0]: r[1] for r in rows}
    result = []
    for b in BADGE_DEFS:
        result.append({**b, "earned": b["id"] in earned,
                       "earned_at": earned.get(b["id"], "")})
    return jsonify({"ok": True, "badges": result})


# ---------------------------------------------------------------------------
# Tenor GIF search
# ---------------------------------------------------------------------------

@app.route("/api/tenor-search")
def tenor_search():
    q = request.args.get("q", "").strip()[:50]
    if not q:
        return jsonify({"results": []})
    key = os.environ.get("TENOR_API_KEY")
    if not key:
        return jsonify({"results": [], "error": "TENOR_API_KEY not set"})
    try:
        import urllib.request
        import urllib.parse
        url = "https://api.tenor.com/v2/search?key=%s&q=%s&limit=20" % (key, urllib.parse.quote(q))
        req = urllib.request.Request(url, headers={"User-Agent": "Kindred/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return jsonify({"results": [], "error": str(e)})
    results = []
    for g in data.get("results", []):
        media = (g.get("media_formats") or {})
        gif_url = media.get("gif", {}).get("url") or media.get("tinygif", {}).get("url")
        if gif_url:
            results.append({"url": gif_url, "id": g.get("id")})
    return jsonify({"results": results})


# ---------------------------------------------------------------------------
# Static uploads
# ---------------------------------------------------------------------------

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


init_db()


def open_browser():
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:5001")


if __name__ == "__main__":
    if os.environ.get("FLASK_ENV") != "production":
        threading.Thread(target=open_browser, daemon=True).start()
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
