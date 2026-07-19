import os
import sqlite3
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, session
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder='.')
app.secret_key = os.getenv("FLASK_SECRET", os.urandom(24).hex())

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
DATABASE_PATH = os.getenv("DATABASE_PATH", "telegram_bot/database.db")


def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            file_id TEXT,
            category TEXT DEFAULT 'general',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            product_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            tx_hash TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
        CREATE TABLE IF NOT EXISTS promo_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            discount_percent INTEGER NOT NULL,
            max_uses INTEGER DEFAULT -1,
            used_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        );
    """)
    conn.commit()
    conn.close()


init_db()


def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


# ── Static ──

@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')


@app.route('/admin')
def serve_admin():
    return send_from_directory('.', 'admin.html')


@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)


# ── Public API ──

@app.route('/api/config', methods=['GET'])
def api_config():
    return jsonify({
        'wallet': os.getenv("WALLET_ADDRESS", ""),
        'currency': os.getenv("CURRENCY", "USDT")
    })

@app.route('/api/products', methods=['GET'])
def api_products():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, description, price, category FROM products WHERE is_active = 1 ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/product/<int:product_id>', methods=['GET'])
def api_product(product_id):
    conn = get_db()
    row = conn.execute(
        "SELECT id, name, description, price, category FROM products WHERE id = ? AND is_active = 1",
        (product_id,)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(dict(row))


# ── Admin Auth ──

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json(silent=True) or {}
    if data.get('password') == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        session.permanent = True
        return jsonify({'success': True})
    return jsonify({'error': 'Неверный пароль'}), 401


@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('admin_logged_in', None)
    return jsonify({'success': True})


@app.route('/api/admin/check', methods=['GET'])
def admin_check():
    if session.get('admin_logged_in'):
        return jsonify({'logged_in': True})
    return jsonify({'logged_in': False}), 401


# ── Admin Stats ──

@app.route('/api/admin/stats', methods=['GET'])
@login_required
def admin_stats():
    conn = get_db()
    stats = {
        'products': conn.execute("SELECT COUNT(*) FROM products WHERE is_active = 1").fetchone()[0],
        'total_orders': conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        'pending_orders': conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'pending'").fetchone()[0],
        'completed_orders': conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'completed'").fetchone()[0],
        'total_revenue': conn.execute("SELECT COALESCE(SUM(amount), 0) FROM orders WHERE status = 'completed'").fetchone()[0],
        'unique_buyers': conn.execute("SELECT COUNT(DISTINCT user_id) FROM orders").fetchone()[0],
    }
    conn.close()
    return jsonify(stats)


# ── Admin Orders ──

@app.route('/api/admin/orders', methods=['GET'])
@login_required
def admin_orders():
    conn = get_db()
    rows = conn.execute("""
        SELECT o.*, p.name as product_name
        FROM orders o
        JOIN products p ON o.product_id = p.id
        ORDER BY o.created_at DESC
        LIMIT 100
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/admin/orders/<int:order_id>/status', methods=['PUT'])
@login_required
def admin_update_order_status(order_id):
    data = request.get_json(silent=True) or {}
    status = data.get('status')
    if status not in ('pending', 'awaiting_confirmation', 'completed', 'rejected'):
        return jsonify({'error': 'Invalid status'}), 400
    conn = get_db()
    conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ── Send message (for mailing) ──

@app.route('/api/send-message', methods=['POST'])
def send_message():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    text = data.get('text', '')
    if not user_id or not text:
        return jsonify({'error': 'Missing params'}), 400
    try:
        from telegram_bot.bot import bot as tg_bot
        import asyncio
        new_loop = asyncio.new_event_loop()
        new_loop.run_until_complete(tg_bot.send_message(user_id, text, parse_mode='HTML'))
        new_loop.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Admin Mailing ──

@app.route('/api/admin/users', methods=['GET'])
@login_required
def admin_users():
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT user_id, username FROM orders UNION SELECT id as user_id, username FROM users"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/admin/stats/referrals', methods=['GET'])
@login_required
def admin_ref_stats():
    conn = get_db()
    total_refs = conn.execute("SELECT COUNT(*) FROM referrals").fetchone()[0]
    total_used = conn.execute("SELECT COUNT(*) FROM referrals_used").fetchone()[0]
    conn.close()
    return jsonify({'total_refs': total_refs, 'total_used': total_used})


# ── Admin Products CRUD ──

@app.route('/api/admin/products', methods=['GET'])
@login_required
def admin_get_products():
    conn = get_db()
    rows = conn.execute("SELECT * FROM products ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/admin/products', methods=['POST'])
@login_required
def admin_add_product():
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Название обязательно'}), 400
    try:
        price = float(data.get('price', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Некорректная цена'}), 400

    conn = get_db()
    conn.execute(
        "INSERT INTO products (name, description, price, category) VALUES (?, ?, ?, ?)",
        (name, data.get('description', ''), price, data.get('category', 'general'))
    )
    conn.commit()
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return jsonify({'success': True, 'id': new_id}), 201


@app.route('/api/admin/products/<int:product_id>', methods=['PUT'])
@login_required
def admin_update_product(product_id):
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Название обязательно'}), 400

    conn = get_db()
    conn.execute(
        """UPDATE products
           SET name = ?, description = ?, price = ?, category = ?, is_active = ?
           WHERE id = ?""",
        (name, data.get('description', ''), data.get('price', 0),
         data.get('category', 'general'), data.get('is_active', 1), product_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/admin/products/<int:product_id>', methods=['DELETE'])
@login_required
def admin_delete_product(product_id):
    conn = get_db()
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ── Run ──

def run_bot():
    """Запускает Telegram бота в фоновом потоке (общая БД)."""
    import asyncio
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from telegram_bot.bot import main as bot_main
    asyncio.run(bot_main(enable_healthcheck=False))


if __name__ == '__main__':
    import threading
    t = threading.Thread(target=run_bot, daemon=True)
    t.start()

    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    print(f"Сервер запущен на http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=debug)
