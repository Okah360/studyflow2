from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
import calendar
from datetime import datetime, timedelta
from dotenv import load_dotenv
import json

load_dotenv()

# Import API integrations
from api_integrations import (
    send_task_reminder, get_weather_for_date, send_discord_notification,
    get_ai_task_suggestions, generate_task_from_description, check_api_status
)


# This app uses a small SQLite database file named study.db
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("STUDY_DB_PATH", os.path.join(BASE_DIR, "study.db"))

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates"))

# secret key for sessions - change to a secure random value for production
app.config['SECRET_KEY'] = os.environ.get('STUDY_PLANNER_SECRET') or 'dev-secret-change-me'

# Create or open the database and make sure the table exists.
def init_db():
    # Ensure the database file exists and required tables are present.
    need_create = not os.path.exists(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    # Create tasks table if missing
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            due_date TEXT,
            duration TEXT,
            notes TEXT,
            complete INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Create users table if missing
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # ensure new columns exist (priority, time_spent)
    cur = conn.cursor()
    # helper to check column
    def has_column(table, column):
        cur.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        return column in cols

    if not has_column('tasks', 'priority'):
        cur.execute("ALTER TABLE tasks ADD COLUMN priority TEXT DEFAULT 'medium'")
    if not has_column('tasks', 'time_spent'):
        cur.execute("ALTER TABLE tasks ADD COLUMN time_spent INTEGER DEFAULT 0")
    if not has_column('tasks', 'tags'):
        cur.execute("ALTER TABLE tasks ADD COLUMN tags TEXT DEFAULT ''")
    
    # add name and theme columns to users table
    if not has_column('users', 'name'):
        cur.execute("ALTER TABLE users ADD COLUMN name TEXT DEFAULT ''")
    if not has_column('users', 'theme'):
        cur.execute("ALTER TABLE users ADD COLUMN theme TEXT DEFAULT 'dark'")
    
    # Add API integration columns to users table
    if not has_column('users', 'google_token'):
        cur.execute("ALTER TABLE users ADD COLUMN google_token TEXT DEFAULT ''")
    if not has_column('users', 'email'):
        cur.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")
    if not has_column('users', 'discord_webhook'):
        cur.execute("ALTER TABLE users ADD COLUMN discord_webhook TEXT DEFAULT ''")
    if not has_column('users', 'latitude'):
        cur.execute("ALTER TABLE users ADD COLUMN latitude REAL DEFAULT 40.7128")
    if not has_column('users', 'longitude'):
        cur.execute("ALTER TABLE users ADD COLUMN longitude REAL DEFAULT -74.0060")
    if not has_column('users', 'enable_email_notifications'):
        cur.execute("ALTER TABLE users ADD COLUMN enable_email_notifications INTEGER DEFAULT 1")
    if not has_column('users', 'enable_discord_notifications'):
        cur.execute("ALTER TABLE users ADD COLUMN enable_discord_notifications INTEGER DEFAULT 0")
    if not has_column('users', 'enable_weather_display'):
        cur.execute("ALTER TABLE users ADD COLUMN enable_weather_display INTEGER DEFAULT 1")

    conn.commit()
    conn.close()

# Initialize the database before the server starts.
# (Flask 3 removed `before_first_request`, so call init_db() at startup.)

# Open SQLite connection and use dictionary-like rows.
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Load all tasks from the database.
def load_tasks():
    conn = get_connection()
    tasks = conn.execute("SELECT * FROM tasks ORDER BY due_date, id").fetchall()
    conn.close()
    return tasks

@app.route("/", methods=["GET"])
def index():
    if not session.get('user_id'):
        flash('Please sign in to view your tasks.', 'warning')
        return redirect(url_for('login'))

    q = request.args.get('q', '').strip()
    tag = request.args.get('tag', '').strip()
    filt = request.args.get('filter', '')
    sort = request.args.get('sort', 'due_date')

    today = datetime.now().date()
    sql = 'SELECT * FROM tasks WHERE 1=1'
    params = []

    if q:
        sql += ' AND name LIKE ?'
        params.append(f'%{q}%')

    if tag:
        sql += ' AND (tags LIKE ? OR tags = ?)' 
        params.extend([f'%{tag}%', tag])

    if filt == 'today':
        sql += ' AND due_date = ?'
        params.append(today.isoformat())
    elif filt == 'week':
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        sql += ' AND due_date BETWEEN ? AND ?'
        params.extend([week_start.isoformat(), week_end.isoformat()])
    elif filt == 'completed':
        sql += ' AND complete = 1'

    order_clause = 'due_date IS NULL, due_date, id'
    if sort == 'priority':
        order_clause = "CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, due_date IS NULL, due_date, id"

    conn = get_connection()
    tasks = conn.execute(sql + f' ORDER BY {order_clause}', params).fetchall()
    total = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
    completed = conn.execute('SELECT COUNT(*) FROM tasks WHERE complete = 1').fetchone()[0]
    conn.close()

    progress = int((completed / total) * 100) if total else 0
    return render_template(
        'index.html',
        tasks=tasks,
        total=total,
        completed=completed,
        progress=progress,
        q=q,
        tag=tag,
        filt=filt,
        sort=sort,
        today_iso=today.isoformat(),
    )


@app.route('/dashboard')
def dashboard():
    if not session.get('user_id'):
        flash('Please sign in to view the dashboard.', 'warning')
        return redirect(url_for('login'))

    conn = get_connection()
    total = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
    completed = conn.execute('SELECT COUNT(*) FROM tasks WHERE complete = 1').fetchone()[0]
    pending = total - completed

    today = datetime.now().date()
    next_week = today + timedelta(days=6)
    upcoming = conn.execute('SELECT * FROM tasks WHERE due_date BETWEEN ? AND ? ORDER BY due_date', (today.isoformat(), next_week.isoformat())).fetchall()

    # counts for next 7 days (used by the small bar chart)
    counts = []
    for i in range(7):
        day = today + timedelta(days=i)
        c = conn.execute('SELECT COUNT(*) FROM tasks WHERE due_date = ?', (day.isoformat(),)).fetchone()[0]
        counts.append((day.isoformat(), c))

    # build a month calendar for the current month
    year = today.year
    month = today.month
    month_name = calendar.month_name[month]
    month_matrix = calendar.monthcalendar(year, month)  # list of weeks, 0 means day outside month

    # build counts per day of month
    day_counts = {}
    rows = conn.execute('SELECT due_date, COUNT(*) as cnt FROM tasks WHERE due_date LIKE ? GROUP BY due_date', (f"{year}-{month:02d}-%",)).fetchall()
    for r in rows:
        try:
            d = r['due_date']
            day = int(d.split('-')[-1])
            day_counts[day] = r['cnt']
        except Exception:
            continue

    conn.close()
    progress = int((completed/total)*100) if total else 0
    return render_template('dashboard.html', total=total, completed=completed, pending=pending, upcoming=upcoming, counts=counts, progress=progress, month_matrix=month_matrix, month_name=month_name, year=year, day_counts=day_counts)

@app.route('/addnew')
def add_new_redirect():
    if not session.get('user_id'):
        flash('Please sign in to add tasks.', 'warning')
        return redirect(url_for('login'))
    return redirect(url_for('index') + '#add-task')

@app.route("/add", methods=["POST"])
def add_task():
    # require login
    if not session.get("user_id"):
        flash("Please sign in to add tasks.", "warning")
        return redirect(url_for("login"))

    name = request.form.get("name", "").strip()
    due_date = request.form.get("due_date", "").strip()
    duration_value = request.form.get("duration_value", "").strip()
    duration_unit = request.form.get("duration_unit", "minutes").strip()
    notes = request.form.get("notes", "").strip()
    priority = request.form.get('priority', 'medium')

    duration = ""
    if duration_value.isdigit() and int(duration_value) > 0:
        amount = int(duration_value)
        unit = duration_unit.rstrip('s') if amount == 1 else duration_unit
        duration = f"{amount} {unit}"
    tags = request.form.get('tags', '').strip()

    if name:
        conn = get_connection()
        conn.execute(
            "INSERT INTO tasks (name, due_date, duration, notes, priority, time_spent, tags) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (name, due_date, duration, notes, priority, tags),
        )
        conn.commit()
        conn.close()

    return redirect("/")

@app.route("/toggle/<int:task_id>")
def toggle_complete(task_id):
    # require login
    if not session.get("user_id"):
        flash("Please sign in.", "warning")
        return redirect(url_for("login"))

    conn = get_connection()
    task = conn.execute("SELECT complete FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is not None:
        new_value = 0 if task["complete"] else 1
        conn.execute("UPDATE tasks SET complete = ? WHERE id = ?", (new_value, task_id))
        conn.commit()
    conn.close()
    return redirect("/")

@app.route("/delete/<int:task_id>")
def delete_task(task_id):
    # require login
    if not session.get("user_id"):
        flash("Please sign in.", "warning")
        return redirect(url_for("login"))

    conn = get_connection()
    # fetch the task to allow undo
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task:
        # store minimal info in session for undo
        session['last_deleted'] = {k: task[k] for k in task.keys()}
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
    conn.close()
    flash('Task deleted — you can undo.', 'info')
    return redirect(url_for('index'))


@app.route('/undo_delete')
def undo_delete():
    last = session.pop('last_deleted', None)
    if not last:
        flash('Nothing to undo.', 'warning')
        return redirect(url_for('index'))
    conn = get_connection()
    conn.execute('INSERT INTO tasks (name,due_date,duration,notes,complete,created_at,priority,time_spent,tags) VALUES (?,?,?,?,?,?,?,?,?)',
                 (last.get('name'), last.get('due_date'), last.get('duration'), last.get('notes'), last.get('complete',0), last.get('created_at'), last.get('priority','medium'), last.get('time_spent',0), last.get('tags','')))
    conn.commit()
    conn.close()
    flash('Undo successful — task restored.', 'success')
    return redirect(url_for('index'))


@app.route('/export')
def export_tasks():
    # export tasks as CSV
    import io, csv
    conn = get_connection()
    rows = conn.execute('SELECT * FROM tasks ORDER BY id').fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id','name','due_date','duration','notes','complete','created_at','priority','time_spent','tags'])
    for r in rows:
        writer.writerow([r['id'], r['name'], r['due_date'], r['duration'], r['notes'], r['complete'], r['created_at'], r.get('priority','medium'), r.get('time_spent',0), r.get('tags','')])
    output.seek(0)
    return (output.getvalue(), 200, {
        'Content-Type': 'text/csv',
        'Content-Disposition': 'attachment; filename="tasks.csv"'
    })


@app.route('/import', methods=['GET','POST'])
def import_tasks():
    if request.method == 'POST':
        f = request.files.get('file')
        if not f:
            flash('No file uploaded.', 'error')
            return redirect(url_for('import_tasks'))
        import csv, io
        data = io.StringIO(f.stream.read().decode('utf-8'))
        reader = csv.DictReader(data)
        conn = get_connection()
        for row in reader:
            conn.execute('INSERT INTO tasks (name,due_date,duration,notes,complete,created_at,priority,time_spent,tags) VALUES (?,?,?,?,?,?,?,?,?)',
                         (row.get('name'), row.get('due_date'), row.get('duration'), row.get('notes'), int(row.get('complete') or 0), row.get('created_at') or None, row.get('priority') or 'medium', int(row.get('time_spent') or 0), row.get('tags') or ''))
        conn.commit()
        conn.close()
        flash('Imported tasks.', 'success')
        return redirect(url_for('index'))

    return render_template('import.html')


@app.route('/log_time/<int:task_id>', methods=['POST'])
def log_time(task_id):
    # expects JSON {seconds: n}
    data = request.get_json() or {}
    seconds = int(data.get('seconds',0))
    conn = get_connection()
    conn.execute('UPDATE tasks SET time_spent = COALESCE(time_spent,0) + ? WHERE id = ?', (seconds, task_id))
    conn.commit()
    conn.close()
    return ('',204)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash('Username and password are required.', 'error')
            return redirect(url_for('register'))

        conn = get_connection()
        existing = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if existing:
            conn.close()
            flash('Username already taken.', 'error')
            return redirect(url_for('register'))

        pw_hash = generate_password_hash(password)
        conn.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, pw_hash))
        conn.commit()
        conn.close()
        flash('Account created — please sign in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('Signed in successfully.', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'error')
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been signed out.', 'info')
    return redirect(url_for('index'))


@app.route('/account', methods=['GET','POST'])
def account():
    if not session.get('user_id'):
        flash('Please sign in to access account settings.', 'warning')
        return redirect(url_for('login'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        theme = request.form.get('theme', 'dark')
        
        conn = get_connection()
        user = conn.execute('SELECT username FROM users WHERE id = ?', (session.get('user_id'),)).fetchone()
        
        # Check if new username is taken (only if username changed)
        if username and username != user['username']:
            existing = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
            if existing:
                conn.close()
                flash('Username already taken.', 'error')
                return redirect(url_for('account'))
        
        # Update the user
        updates = []
        params = []
        if name:
            updates.append('name = ?')
            params.append(name)
        if username and username != user['username']:
            updates.append('username = ?')
            params.append(username)
            session['username'] = username  # Update session
        if password:
            pw_hash = generate_password_hash(password)
            updates.append('password_hash = ?')
            params.append(pw_hash)
        
        # Always update theme
        updates.append('theme = ?')
        params.append(theme)
        
        if updates:
            params.append(session.get('user_id'))
            sql = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
            conn.execute(sql, params)
            conn.commit()
        
        conn.close()
        flash('Account updated successfully.', 'success')
        return redirect(url_for('account'))
    
    # Get user info
    conn = get_connection()
    user = conn.execute('SELECT name, username, theme FROM users WHERE id = ?', (session.get('user_id'),)).fetchone()
    conn.close()
    
    return render_template('account.html', user_name=user['name'] if user else '', user_theme=user['theme'] if user else 'dark')

@app.route('/planner')
def planner():
    if not session.get('user_id'):
        flash('Please sign in to view the planner.', 'warning')
        return redirect(url_for('login'))

    today = datetime.now().date()
    week_start_param = request.args.get('week_start')

    if week_start_param:
        try:
            week_start = datetime.strptime(week_start_param, '%Y-%m-%d').date()
        except ValueError:
            week_start = today - timedelta(days=today.weekday())
    else:
        week_start = today - timedelta(days=today.weekday())

    conn = get_connection()
    tasks = conn.execute('SELECT * FROM tasks ORDER BY due_date, priority DESC, name').fetchall()
    conn.close()

    week_days = []
    day_tasks = {}

    for i in range(7):
        day = week_start + timedelta(days=i)
        day_iso = day.isoformat()
        day_name = day.strftime('%A')
        day_num = day.strftime('%d')

        week_days.append({
            'date': day_iso,
            'name': day_name,
            'num': day_num,
            'is_today': day == today
        })

        day_task_list = [t for t in tasks if t['due_date'] == day_iso]
        day_tasks[day_iso] = day_task_list

    unscheduled = [t for t in tasks if not t['due_date']]
    prev_week = week_start - timedelta(days=7)
    next_week = week_start + timedelta(days=7)

    return render_template(
        'planner.html',
        week_days=week_days,
        day_tasks=day_tasks,
        unscheduled=unscheduled,
        week_start=week_start,
        today=today,
        prev_week=prev_week,
        next_week=next_week,
    )


# ============================================================================
# API INTEGRATION ROUTES
# ============================================================================

@app.route('/api/weather/<task_id>')
def get_task_weather(task_id):
    """Get weather for a specific task's due date"""
    if not session.get('user_id'):
        return jsonify({"error": "Not authenticated"}), 401
    
    conn = get_connection()
    task = conn.execute('SELECT due_date FROM tasks WHERE id = ?', (task_id,)).fetchone()
    user = conn.execute('SELECT latitude, longitude, enable_weather_display FROM users WHERE id = ?', (session.get('user_id'),)).fetchone()
    conn.close()
    
    if not user or not user['enable_weather_display']:
        return jsonify({"error": "Weather display disabled"}), 403
    
    if not task or not task['due_date']:
        return jsonify({"error": "Task has no due date"}), 400
    
    weather = get_weather_for_date(task['due_date'], user['latitude'], user['longitude'])
    return jsonify(weather)


@app.route('/api/send-reminder/<task_id>', methods=['POST'])
def send_reminder(task_id):
    """Send email reminder for a task"""
    if not session.get('user_id'):
        return jsonify({"error": "Not authenticated"}), 401
    
    conn = get_connection()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    user = conn.execute('SELECT email, enable_email_notifications FROM users WHERE id = ?', (session.get('user_id'),)).fetchone()
    conn.close()
    
    if not user or not user['email'] or not user['enable_email_notifications']:
        return jsonify({"error": "Email notifications not configured"}), 403
    
    if not task:
        return jsonify({"error": "Task not found"}), 404
    
    result = send_task_reminder(user['email'], dict(task))
    return jsonify(result)


@app.route('/api/ai-suggestion', methods=['POST'])
def ai_suggestion():
    """Get AI-powered task suggestion"""
    if not session.get('user_id'):
        return jsonify({"error": "Not authenticated"}), 401
    
    query = request.json.get('query', '').strip()
    if not query:
        return jsonify({"error": "Query is required"}), 400
    
    conn = get_connection()
    tasks = conn.execute('SELECT * FROM tasks WHERE id IS NOT NULL LIMIT 10').fetchall()
    conn.close()
    
    result = get_ai_task_suggestions([dict(t) for t in tasks], query)
    return jsonify(result)


@app.route('/api/parse-task', methods=['POST'])
def parse_task_ai():
    """Use AI to parse task description"""
    if not session.get('user_id'):
        return jsonify({"error": "Not authenticated"}), 401
    
    description = request.json.get('description', '').strip()
    if not description:
        return jsonify({"error": "Description is required"}), 400
    
    result = generate_task_from_description(description)
    return jsonify(result)


@app.route('/api/status')
def api_status():
    """Check which APIs are configured"""
    status = check_api_status()
    return jsonify(status)


@app.route('/api/discord-notification/<task_id>', methods=['POST'])
def discord_notification(task_id):
    """Send Discord notification for task"""
    if not session.get('user_id'):
        return jsonify({"error": "Not authenticated"}), 401
    
    action = request.json.get('action', 'created')
    
    conn = get_connection()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    user = conn.execute('SELECT enable_discord_notifications FROM users WHERE id = ?', (session.get('user_id'),)).fetchone()
    conn.close()
    
    if not user or not user['enable_discord_notifications']:
        return jsonify({"error": "Discord notifications not enabled"}), 403
    
    if not task:
        return jsonify({"error": "Task not found"}), 404
    
    result = send_discord_notification(dict(task), action)
    return jsonify(result)


@app.route('/settings/api', methods=['GET', 'POST'])
def api_settings():
    """Manage API integration settings"""
    if not session.get('user_id'):
        flash('Please sign in to access API settings.', 'warning')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        discord_webhook = request.form.get('discord_webhook', '').strip()
        latitude = request.form.get('latitude', '40.7128')
        longitude = request.form.get('longitude', '-74.0060')
        enable_email = request.form.get('enable_email_notifications') == 'on'
        enable_discord = request.form.get('enable_discord_notifications') == 'on'
        enable_weather = request.form.get('enable_weather_display') == 'on'
        
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except:
            flash('Invalid latitude/longitude.', 'error')
            return redirect(url_for('api_settings'))
        
        conn = get_connection()
        conn.execute('''UPDATE users SET email = ?, discord_webhook = ?, latitude = ?, longitude = ?,
                       enable_email_notifications = ?, enable_discord_notifications = ?, enable_weather_display = ?
                       WHERE id = ?''',
                    (email, discord_webhook, latitude, longitude, 
                     1 if enable_email else 0, 1 if enable_discord else 0, 1 if enable_weather else 0,
                     session.get('user_id')))
        conn.commit()
        conn.close()
        
        flash('API settings updated successfully.', 'success')
        return redirect(url_for('api_settings'))
    
    # Get user API settings
    conn = get_connection()
    user = conn.execute('SELECT email, discord_webhook, latitude, longitude, enable_email_notifications, enable_discord_notifications, enable_weather_display FROM users WHERE id = ?', (session.get('user_id'),)).fetchone()
    status = check_api_status()
    conn.close()
    
    return render_template('api_settings.html', 
                          user_email=user['email'] if user else '',
                          user_discord=user['discord_webhook'] if user else '',
                          user_latitude=user['latitude'] if user else '40.7128',
                          user_longitude=user['longitude'] if user else '-74.0060',
                          enable_email=user['enable_email_notifications'] if user else 1,
                          enable_discord=user['enable_discord_notifications'] if user else 0,
                          enable_weather=user['enable_weather_display'] if user else 1,
                          api_status=status)

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
