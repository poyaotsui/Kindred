"""
Kindred - Python web app with sign up / sign in and phone verification.
Run: python app.py
run: cd /Users/poyaotsui/Desktop/vscode_py/webapp
python app.py
"""
import json
import os
import sqlite3
import re
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
    {"id": "first_checkin", "emoji": "🌟", "name": "First Check-In",    "desc": "Checked in for the first time"},
    {"id": "streak_3",      "emoji": "🔥", "name": "3-Day Streak",      "desc": "Checked in 3 days in a row"},
    {"id": "streak_7",      "emoji": "🏆", "name": "7-Day Streak",      "desc": "Checked in 7 days in a row"},
    {"id": "streak_30",     "emoji": "💎", "name": "30-Day Streak",     "desc": "Checked in 30 days in a row"},
    {"id": "first_friend",  "emoji": "🤝", "name": "First Friend",      "desc": "Made your first friend"},
    {"id": "social_5",      "emoji": "👥", "name": "Social Butterfly",  "desc": "Made 5 friends"},
    {"id": "first_post",    "emoji": "📝", "name": "First Post",        "desc": "Added your first board post"},
    {"id": "first_reaction","emoji": "❤️", "name": "First Reaction",    "desc": "Reacted to a friend's post"},
]


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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for col, defval in [("display_name", "TEXT"), ("bio", "TEXT DEFAULT ''"),
                        ("avatar", "TEXT DEFAULT ''"), ("streak_freezes", "INTEGER DEFAULT 0")]:
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
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
        "SELECT id, email, display_name, bio, avatar, streak_freezes FROM users WHERE email = ?",
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
        }


def _calc_streak(user_id, conn):
    """Calculate current consecutive day streak from DB check-ins."""
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


def _award_badges(user_id, conn):
    """Check milestones and insert any newly earned badges."""
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
    if streak >= 30:
        award("streak_30")

    friend_count = conn.execute(
        "SELECT COUNT(*) FROM friendships WHERE user_id = ? OR friend_id = ?",
        (user_id, user_id)
    ).fetchone()[0]
    if friend_count >= 1:
        award("first_friend")
    if friend_count >= 5:
        award("social_5")

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
        "SELECT id, email, display_name, phone, created_at FROM users ORDER BY created_at DESC"
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
            "phone_masked": _mask_phone(r["phone"]) if r["phone"] else "",
            "created_at": r["created_at"], "friend_status": status, "is_you": False,
        })
    if current_user_row:
        r = current_user_row
        users.insert(0, {
            "id": r["id"], "email": r["email"],
            "display_name": r["display_name"] or r["email"].split("@")[0],
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
            f"SELECT id, email, display_name, avatar FROM users WHERE id IN ({placeholders}) ORDER BY display_name",
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
    # Mark messages as read
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
        "SELECT id, email, display_name, bio, avatar, created_at FROM users WHERE display_name = ? OR email LIKE ?",
        (username, username + "@%")
    ).fetchone()
    if not row:
        conn.close()
        return "User not found", 404
    profile_id = row["id"]
    streak = _calc_streak(profile_id, conn)
    badges_rows = conn.execute(
        "SELECT badge_id FROM user_badges WHERE user_id = ?", (profile_id,)
    ).fetchall()
    earned_badge_ids = {r[0] for r in badges_rows}
    badges = [b for b in BADGE_DEFS if b["id"] in earned_badge_ids]
    today = date_cls.today().isoformat()
    posts = conn.execute(
        "SELECT id, type, content, pos_left, pos_top, width, color FROM board_posts WHERE user_id = ? AND date = ? ORDER BY created_at ASC",
        (profile_id, today)
    ).fetchall()
    posts_data = [dict(p) for p in posts]
    is_own = _current_user_id() == profile_id
    conn.close()
    profile = {
        "id": row["id"],
        "display_name": row["display_name"] or row["email"].split("@")[0],
        "email": row["email"],
        "bio": row["bio"] or "",
        "avatar": row["avatar"] or "",
        "streak": streak,
        "created_at": row["created_at"],
    }
    return render_template("profile.html", user=session.get("user"),
                           profile=profile, badges=badges, posts=posts_data, is_own=is_own)


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
            "badges": top_badges,
            "is_you": uid == current_id,
        })
    entries.sort(key=lambda x: x["streak"], reverse=True)
    conn.close()
    return render_template("leaderboard.html", user=session.get("user"), entries=entries)


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
        return jsonify({"ok": False, "error": "Please use a Gmail account (@gmail.com)"}), 400
    if len(phone) < 10:
        return jsonify({"ok": False, "error": "Please enter a valid phone number"}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "Password must be at least 6 characters"}), 400
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
    session["user"] = {"id": user_id, "email": email, "display_name": display_name, "bio": "", "avatar": ""}
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
        "SELECT id, email, password_hash, display_name, bio, avatar FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    if not row or not check_password(password, row["password_hash"]):
        return jsonify({"ok": False, "error": "Invalid email or password"}), 401
    display_name = row["display_name"] if row["display_name"] else row["email"].split("@")[0]
    session["user"] = {
        "id": row["id"], "email": row["email"], "display_name": display_name,
        "bio": row["bio"] or "", "avatar": row["avatar"] or "",
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
    conn = get_db()
    conn.execute(
        "INSERT INTO check_ins (user_id, date) VALUES (?, ?)", (user_id, today)
    )
    conn.commit()
    streak = _calc_streak(user_id, conn)
    _award_badges(user_id, conn)
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
    conn.close()
    return jsonify({"ok": True, "checked_in_today": count_today > 0,
                    "count_today": count_today, "streak": streak, "freezes": freezes})


@app.route("/api/checkin/history")
def api_checkin_history():
    if not session.get("user"):
        return jsonify({"ok": False, "error": "Sign in required"}), 401
    user_id = _current_user_id()
    conn = get_db()
    rows = conn.execute(
        "SELECT date, COUNT(*) as cnt FROM check_ins WHERE user_id = ? GROUP BY date ORDER BY date DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify({"ok": True, "history": [{"date": r[0], "count": r[1]} for r in rows]})


@app.route("/api/checkin/friends")
def api_checkin_friends():
    """How many friends checked in today."""
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
        "SELECT id, type, content, pos_left, pos_top, width, color FROM board_posts WHERE user_id = ? AND date = ? ORDER BY created_at ASC",
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
            "color": p["color"], "reactions": reactions,
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
    conn = get_db()
    if display_name:
        conn.execute(
            "UPDATE users SET display_name = ?, bio = ? WHERE id = ?",
            (display_name, bio, user_id)
        )
    else:
        conn.execute("UPDATE users SET bio = ? WHERE id = ?", (bio, user_id))
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
