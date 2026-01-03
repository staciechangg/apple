from flask import Flask, render_template, request, redirect, url_for, session, g
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = "change-me-please"  # 用於 session 的密鑰，實務上請改成隨機值

DATABASE = "shop.db"


# ========= 資料庫連線 & 初始化 =========
def get_db():
    """取得目前請求使用的資料庫連線"""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    """每次請求結束時，自動關閉資料庫連線"""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """如果資料庫不存在，建立資料表並加入測試商品"""
    need_init = not os.path.exists(DATABASE)

    db = sqlite3.connect(DATABASE)
    c = db.cursor()

    # 建立資料表（若不存在）
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            stock INTEGER NOT NULL DEFAULT 999
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            total_amount INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price INTEGER NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
        """
    )

    # 如果剛建立資料庫或商品表是空的，就塞一些測試商品
    c.execute("SELECT COUNT(*) FROM products")
    count = c.fetchone()[0]

    if count == 0:
        c.executemany(
            "INSERT INTO products (name, price, stock) VALUES (?, ?, ?)",
            [
                ("蘋果", 30, 100),
                ("香蕉", 20, 200),
                ("草莓", 50, 50),
            ],
        )

    db.commit()
    db.close()





def load_cart_items(db, cart):
    """
    根據 session 裡的 cart（dict: {product_id(str): quantity(int)})
    查出對應商品資料並計算小計與總價
    """
    items = []
    total = 0

    if not cart:
        return items, total

    placeholders = ",".join("?" * len(cart))
    sql = f"SELECT id, name, price FROM products WHERE id IN ({placeholders})"
    rows = db.execute(sql, list(cart.keys())).fetchall()

    for row in rows:
        pid = str(row["id"])
        qty = cart.get(pid, 0)
        subtotal = row["price"] * qty
        total += subtotal
        items.append(
            {
                "id": pid,
                "name": row["name"],
                "price": row["price"],
                "quantity": qty,
                "subtotal": subtotal,
            }
        )

    return items, total


# ========= 1. 商品選擇頁面 =========
@app.route("/")
@app.route("/products")
def product_list():
    db = get_db()
    products = db.execute(
        "SELECT id, name, price FROM products ORDER BY id"
    ).fetchall()
    return render_template("products.html", products=products)


@app.route("/add_to_cart", methods=["POST"])
def add_to_cart():
    """按下「加入購物車」後的處理"""
    product_id = request.form.get("product_id")
    quantity = request.form.get("quantity", type=int)

    if not product_id or not quantity or quantity <= 0:
        return redirect(url_for("product_list"))

    cart = session.get("cart", {})  # {product_id(str): quantity(int)}
    product_id = str(product_id)

    cart[product_id] = cart.get(product_id, 0) + quantity
    session["cart"] = cart

    # 加完直接到購物車頁
    return redirect(url_for("cart_page"))


# ========= 2. 購物車頁面 =========
@app.route("/cart", methods=["GET", "POST"])
def cart_page():
    db = get_db()
    cart = session.get("cart", {})

    if request.method == "POST":
        # 更新購物車（修改數量 / 勾選刪除）
        new_cart = {}
        for pid in list(cart.keys()):
            qty_str = request.form.get(f"qty_{pid}")
            remove = request.form.get(f"remove_{pid}")  # checkbox 有值代表要刪除

            if remove:
                continue  # 不放進 new_cart 就是刪除

            if not qty_str:
                continue

            try:
                qty = int(qty_str)
            except ValueError:
                qty = 0

            if qty > 0:
                new_cart[pid] = qty

        session["cart"] = new_cart
        cart = new_cart

    items, total = load_cart_items(db, cart)
    return render_template("cart.html", items=items, total=total)


# ========= 3. 結帳頁面 =========
@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    db = get_db()
    cart = session.get("cart", {})

    if not cart:
        # 沒東西不能結帳，導回商品頁
        return redirect(url_for("product_list"))

    items, total = load_cart_items(db, cart)

    if request.method == "POST":
        customer_name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()

        if not customer_name or not phone or not address:
            error = "請完整填寫訂購人資訊。"
            return render_template(
                "checkout.html", items=items, total=total, error=error
            )

        cur = db.cursor()
        # 建立訂單主檔
        cur.execute(
            """
            INSERT INTO orders (customer_name, phone, address, total_amount, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                customer_name,
                phone,
                address,
                total,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        order_id = cur.lastrowid

        # 建立訂單明細
        for item in items:
            cur.execute(
                """
                INSERT INTO order_items (order_id, product_id, quantity, unit_price)
                VALUES (?, ?, ?, ?)
                """,
                (order_id, int(item["id"]), item["quantity"], item["price"]),
            )

        db.commit()

        # 清空購物車
        session["cart"] = {}

        return render_template("success.html", order_id=order_id, total=total)

    # GET：顯示結帳畫面
    return render_template("checkout.html", items=items, total=total, error=None)


if __name__ == "__main__":
    # 先初始化資料庫，再啟動 Flask
    init_db()
    app.run(debug=True)
