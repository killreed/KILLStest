import aiosqlite
from config import DATABASE_PATH


async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL,
                file_id TEXT,
                category TEXT DEFAULT 'general',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
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
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                discount_percent INTEGER NOT NULL,
                max_uses INTEGER DEFAULT -1,
                used_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ref_code TEXT UNIQUE NOT NULL,
                earned REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals_used (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ref_code TEXT NOT NULL,
                used_by INTEGER NOT NULL,
                order_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance REAL DEFAULT 0,
                total_spent REAL DEFAULT 0,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS crypto_invoices (
                invoice_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                amount_rub REAL NOT NULL,
                amount_usdt REAL NOT NULL,
                status TEXT DEFAULT 'active'
            )
        """)

        await db.commit()


async def get_products(active_only=True):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM products"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY created_at DESC"
        async with db.execute(query) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def get_product(product_id):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM products WHERE id = ?", (product_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def add_product(name, description, price, file_id=None, category="general"):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO products (name, description, price, file_id, category) VALUES (?, ?, ?, ?, ?)",
            (name, description, price, file_id, category)
        )
        await db.commit()
        return cursor.lastrowid


async def update_product(product_id, **kwargs):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        fields = []
        values = []
        for key, value in kwargs.items():
            fields.append(f"{key} = ?")
            values.append(value)
        values.append(product_id)
        await db.execute(
            f"UPDATE products SET {', '.join(fields)} WHERE id = ?",
            values
        )
        await db.commit()


async def delete_product(product_id):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM products WHERE id = ?", (product_id,))
        await db.commit()


async def create_order(user_id, username, product_id, amount):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO orders (user_id, username, product_id, amount) VALUES (?, ?, ?, ?)",
            (user_id, username, product_id, amount)
        )
        await db.commit()
        return cursor.lastrowid


async def update_order_status(order_id, status, tx_hash=None):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        if tx_hash:
            await db.execute(
                "UPDATE orders SET status = ?, tx_hash = ? WHERE id = ?",
                (status, tx_hash, order_id)
            )
        else:
            await db.execute(
                "UPDATE orders SET status = ? WHERE id = ?",
                (status, order_id)
            )
        await db.commit()


async def get_order(order_id):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT o.*, p.name as product_name, p.file_id
               FROM orders o JOIN products p ON o.product_id = p.id
               WHERE o.id = ?""",
            (order_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_user_orders(user_id):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT o.*, p.name as product_name
               FROM orders o JOIN products p ON o.product_id = p.id
               WHERE o.user_id = ? ORDER BY o.created_at DESC""",
            (user_id,)
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def get_all_orders(status=None):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = """SELECT o.*, p.name as product_name, p.file_id
                   FROM orders o JOIN products p ON o.product_id = p.id"""
        params = []
        if status:
            query += " WHERE o.status = ?"
            params.append(status)
        query += " ORDER BY o.created_at DESC"
        async with db.execute(query, params) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def add_promo_code(code, discount_percent, max_uses=-1):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO promo_codes (code, discount_percent, max_uses) VALUES (?, ?, ?)",
                (code.upper(), discount_percent, max_uses)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


# ── Referral ──

async def get_or_create_ref(user_id):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM referrals WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
        import secrets, string
        code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        await db.execute("INSERT OR IGNORE INTO referrals (user_id, ref_code) VALUES (?, ?)", (user_id, code))
        await db.commit()
        async with db.execute("SELECT * FROM referrals WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
            return {"id": 0, "user_id": user_id, "ref_code": code, "earned": 0}


async def apply_ref(code, used_by, order_id):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT * FROM referrals WHERE ref_code = ?", (code,)) as cur:
            ref = await cur.fetchone()
            if not ref:
                return False
        await db.execute(
            "INSERT INTO referrals_used (ref_code, used_by, order_id) VALUES (?, ?, ?)",
            (code, used_by, order_id)
        )
        await db.commit()
        return True


async def get_all_users():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id as user_id, username FROM users") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def check_promo_code(code):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM promo_codes WHERE code = ? AND is_active = 1",
            (code.upper(),)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                row = dict(row)
                if row["max_uses"] == -1 or row["used_count"] < row["max_uses"]:
                    return row
            return None


async def use_promo_code(code):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE promo_codes SET used_count = used_count + 1 WHERE code = ?",
            (code.upper(),)
        )
        await db.commit()


# ── Crypto Invoices ──

async def save_invoice(invoice_id, user_id, amount_rub, amount_usdt):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO crypto_invoices (invoice_id, user_id, amount_rub, amount_usdt) VALUES (?, ?, ?, ?)",
            (invoice_id, user_id, amount_rub, amount_usdt)
        )
        await db.commit()


async def get_invoice(invoice_id):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM crypto_invoices WHERE invoice_id = ?", (invoice_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def complete_invoice(invoice_id):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE crypto_invoices SET status = 'paid' WHERE invoice_id = ?", (invoice_id,))
        await db.commit()


# ── Balance ──

async def upsert_user(user_id, username=None, first_name=None):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO users (id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                username = COALESCE(?, username),
                first_name = COALESCE(?, first_name)
        """, (user_id, username, first_name, username, first_name))
        await db.commit()


async def get_user(user_id):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
        await db.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (user_id,))
        await db.commit()
        async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cur:
            return dict(await cur.fetchone())


async def add_balance(user_id, amount):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
        await db.commit()


async def deduct_balance(user_id, amount):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE users SET balance = balance - ?, total_spent = total_spent + ? WHERE id = ?",
                         (amount, amount, user_id))
        await db.commit()


async def transfer_balance(from_id, to_id, amount):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, from_id))
        await db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, to_id))
        await db.commit()


async def find_user_by_username(username):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE username = ?", (username.lstrip("@"),)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_all_db_users():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users ORDER BY registered_at DESC") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_stats():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        stats = {}

        async with db.execute("SELECT COUNT(*) FROM products WHERE is_active = 1") as cursor:
            stats["products"] = (await cursor.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM orders") as cursor:
            stats["total_orders"] = (await cursor.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM orders WHERE status = 'pending'") as cursor:
            stats["pending_orders"] = (await cursor.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM orders WHERE status = 'completed'") as cursor:
            stats["completed_orders"] = (await cursor.fetchone())[0]

        async with db.execute("SELECT COALESCE(SUM(amount), 0) FROM orders WHERE status = 'completed'") as cursor:
            stats["total_revenue"] = (await cursor.fetchone())[0]

        async with db.execute("SELECT COUNT(DISTINCT user_id) FROM orders") as cursor:
            stats["unique_buyers"] = (await cursor.fetchone())[0]

        return stats
