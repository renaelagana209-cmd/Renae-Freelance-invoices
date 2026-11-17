import json
import sqlite3
from datetime import date, datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DB_PATH = Path(__file__).parent / "cashier.db"
HOST, PORT = "127.0.0.1", 8001

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price REAL NOT NULL DEFAULT 0,
    stock INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT DEFAULT '',
    customer TEXT DEFAULT '',
    payment_method TEXT DEFAULT 'cash',
    discount REAL DEFAULT 0,
    tax_rate REAL DEFAULT 0,
    subtotal REAL NOT NULL,
    tax REAL NOT NULL,
    total REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sale_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    product_id INTEGER,
    description TEXT NOT NULL,
    qty REAL NOT NULL,
    price REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);
"""

DEFAULT_SETTINGS = {
    "business_name": "My Shop",
    "business_address": "",
    "currency": "$",
    "receipt_footer": "Thank you for your purchase!",
}


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))


def get_settings():
    with db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = dict(DEFAULT_SETTINGS)
    settings.update({r["key"]: r["value"] for r in rows})
    return settings


def money(value, currency):
    return f"{currency}{value:,.2f}"


def sale_row(conn, sale):
    data = dict(sale)
    items = conn.execute("SELECT * FROM sale_items WHERE sale_id = ? ORDER BY id", (sale["id"],)).fetchall()
    data["items"] = [dict(i) for i in items]
    return data


def render_receipt(sale, settings):
    cur = settings["currency"]
    rows = "".join(
        f"<tr><td>{escape(i['description'])}</td><td class='r'>{i['qty']:g}</td>"
        f"<td class='r'>{money(i['price'], cur)}</td><td class='r'>{money(i['qty'] * i['price'], cur)}</td></tr>"
        for i in sale["items"]
    )
    address_html = escape(settings["business_address"]).replace("\n", "<br>")
    when = datetime.fromisoformat(sale["created_at"]).strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(sale['number'])}</title>
<style>
  body {{ font-family: 'Courier New', monospace; color: #111; max-width: 420px; margin: 30px auto; padding: 0 16px; }}
  h1 {{ text-align: center; font-size: 20px; margin-bottom: 4px; }}
  .center {{ text-align: center; font-size: 13px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 13px; }}
  td {{ padding: 3px 2px; }}
  .r {{ text-align: right; }}
  .totals td {{ padding: 2px 2px; }}
  .totals .grand {{ font-weight: bold; font-size: 15px; border-top: 1px dashed #111; }}
  .meta {{ font-size: 12px; margin-top: 14px; }}
  .footer {{ margin-top: 24px; text-align: center; font-size: 13px; }}
  .dash {{ border-top: 1px dashed #111; margin: 12px 0; }}
  .noprint {{ text-align: center; margin-bottom: 20px; }}
  .noprint button {{ padding: 8px 24px; font-size: 14px; cursor: pointer; font-family: system-ui, sans-serif; }}
  @media print {{ .noprint {{ display: none; }} body {{ margin: 0; }} }}
</style>
</head>
<body>
<div class="noprint"><button onclick="window.print()">Print receipt</button></div>
<h1>{escape(settings['business_name'])}</h1>
<div class="center">{address_html}</div>
<div class="meta">
  Receipt: <strong>{escape(sale['number'])}</strong><br>
  Date: {when}<br>
  {f"Customer: {escape(sale['customer'])}<br>" if sale['customer'] else ''}
  Payment: {escape(sale['payment_method'].upper())}
</div>
<div class="dash"></div>
<table>
  {''.join(f"<tr><td>Description</td><td class='r'>Qty</td><td class='r'>Price</td><td class='r'>Total</td></tr>" if False else '')}
  {rows}
</table>
<div class="dash"></div>
<table class="totals">
  <tr><td>Subtotal</td><td class="r">{money(sale['subtotal'], cur)}</td></tr>
  {f"<tr><td>Discount</td><td class='r'>-{money(sale['discount'], cur)}</td></tr>" if sale['discount'] else ''}
  {f"<tr><td>Tax ({sale['tax_rate']:g}%)</td><td class='r'>{money(sale['tax'], cur)}</td></tr>" if sale['tax'] else ''}
  <tr class="grand"><td>TOTAL</td><td class="r">{money(sale['total'], cur)}</td></tr>
</table>
<div class="dash"></div>
<div class="footer">{escape(settings['receipt_footer'])}</div>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, status, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            index = Path(__file__).parent / "static" / "index.html"
            self._send(200, index.read_bytes(), "text/html; charset=utf-8")
            return
        if path.startswith("/receipt/") and path[len("/receipt/"):].isdigit():
            self._receipt_page(int(path[len("/receipt/"):]))
            return
        if path == "/api/dashboard":
            self._dashboard()
            return
        if path == "/api/settings":
            self._send(200, get_settings())
            return
        if path == "/api/products":
            with db() as conn:
                rows = conn.execute("SELECT * FROM products ORDER BY name COLLATE NOCASE").fetchall()
            self._send(200, [dict(r) for r in rows])
            return
        if path == "/api/sales":
            with db() as conn:
                rows = conn.execute("SELECT * FROM sales ORDER BY id DESC LIMIT 100").fetchall()
            self._send(200, [dict(r) for r in rows])
            return
        if path.startswith("/api/sales/") and path[len("/api/sales/"):].isdigit():
            with db() as conn:
                sale = conn.execute("SELECT * FROM sales WHERE id = ?", (int(path.split("/")[-1]),)).fetchone()
                if not sale:
                    self._send(404, {"error": "not found"})
                    return
            self._send(200, sale_row(conn, sale))
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/products":
            data = self._body()
            name = str(data.get("name", "")).strip()
            if not name:
                self._send(400, {"error": "name is required"})
                return
            stock = data.get("stock")
            with db() as conn:
                cur = conn.execute(
                    "INSERT INTO products (name, price, stock, created_at) VALUES (?, ?, ?, ?)",
                    (name, float(data.get("price") or 0), int(stock) if stock not in (None, "") else None,
                     datetime.now().isoformat(timespec="seconds")),
                )
                row = conn.execute("SELECT * FROM products WHERE id = ?", (cur.lastrowid,)).fetchone()
            self._send(201, dict(row))
            return
        if path == "/api/sales":
            self._checkout()
            return
        self._send(404, {"error": "not found"})

    def do_PUT(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "products" and parts[2].isdigit():
            data = self._body()
            allowed = {}
            if "name" in data:
                name = str(data["name"]).strip()
                if not name:
                    self._send(400, {"error": "name cannot be empty"})
                    return
                allowed["name"] = name
            if "price" in data:
                allowed["price"] = float(data["price"] or 0)
            if "stock" in data:
                allowed["stock"] = int(data["stock"]) if data["stock"] not in (None, "") else None
            if not allowed:
                self._send(400, {"error": "no valid fields"})
                return
            sets = ", ".join(f"{k} = ?" for k in allowed)
            with db() as conn:
                cur = conn.execute(f"UPDATE products SET {sets} WHERE id = ?", list(allowed.values()) + [int(parts[2])])
                if cur.rowcount == 0:
                    self._send(404, {"error": "not found"})
                    return
                row = conn.execute("SELECT * FROM products WHERE id = ?", (int(parts[2]),)).fetchone()
            self._send(200, dict(row))
            return
        if urlparse(self.path).path == "/api/settings":
            data = self._body()
            with db() as conn:
                for k, v in data.items():
                    conn.execute(
                        "INSERT INTO settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (str(k), str(v)),
                    )
            self._send(200, get_settings())
            return
        self._send(404, {"error": "not found"})

    def do_DELETE(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "products" and parts[2].isdigit():
            with db() as conn:
                cur = conn.execute("DELETE FROM products WHERE id = ?", (int(parts[2]),))
            if cur.rowcount == 0:
                self._send(404, {"error": "not found"})
                return
            self._send(200, {"ok": True})
            return
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "sales" and parts[2].isdigit():
            sale_id = int(parts[2])
            with db() as conn:
                sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
                if not sale:
                    self._send(404, {"error": "not found"})
                    return
                items = conn.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall()
                for item in items:
                    if item["product_id"] is not None:
                        conn.execute(
                            "UPDATE products SET stock = COALESCE(stock, 0) + ? WHERE id = ? AND stock IS NOT NULL",
                            (item["qty"], item["product_id"]),
                        )
                conn.execute("DELETE FROM sale_items WHERE sale_id = ?", (sale_id,))
                conn.execute("DELETE FROM sales WHERE id = ?", (sale_id,))
            self._send(200, {"ok": True})
            return
        self._send(404, {"error": "not found"})

    def _checkout(self):
        data = self._body()
        items = data.get("items") or []
        items = [i for i in items if str(i.get("description", "")).strip() and float(i.get("qty") or 0) > 0]
        if not items:
            self._send(400, {"error": "cart is empty"})
            return
        discount = max(0.0, float(data.get("discount") or 0))
        tax_rate = max(0.0, float(data.get("tax_rate") or 0))
        with db() as conn:
            for item in items:
                if item.get("product_id") is not None:
                    product = conn.execute(
                        "SELECT * FROM products WHERE id = ?", (item["product_id"],)
                    ).fetchone()
                    if not product:
                        self._send(400, {"error": f"product not found: {item.get('description')}"})
                        return
                    if product["stock"] is not None and float(item["qty"]) > product["stock"]:
                        self._send(400, {"error": f"not enough stock for {product['name']} ({product['stock']} left)"})
                        return
            subtotal = round(sum(float(i["qty"]) * float(i["price"] or 0) for i in items), 2)
            taxable = max(0.0, subtotal - discount)
            tax = round(taxable * tax_rate / 100, 2)
            total = round(taxable + tax, 2)
            cur = conn.execute(
                "INSERT INTO sales (customer, payment_method, discount, tax_rate, subtotal, tax, total, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(data.get("customer", "")),
                    str(data.get("payment_method", "cash")),
                    discount,
                    tax_rate,
                    subtotal,
                    tax,
                    total,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            sale_id = cur.lastrowid
            conn.execute("UPDATE sales SET number = ? WHERE id = ?", (f"RCP-{sale_id:05d}", sale_id))
            for item in items:
                conn.execute(
                    "INSERT INTO sale_items (sale_id, product_id, description, qty, price) VALUES (?, ?, ?, ?, ?)",
                    (sale_id, item.get("product_id"), str(item["description"]), float(item["qty"]), float(item["price"] or 0)),
                )
                if item.get("product_id") is not None:
                    conn.execute(
                        "UPDATE products SET stock = stock - ? WHERE id = ? AND stock IS NOT NULL",
                        (float(item["qty"]), item["product_id"]),
                    )
            sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
        self._send(201, sale_row(conn, sale))

    def _receipt_page(self, sale_id):
        with db() as conn:
            sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
            if not sale:
                self._send(404, {"error": "not found"})
                return
            page = render_receipt(sale_row(conn, sale), get_settings())
        self._send(200, page.encode(), "text/html; charset=utf-8")

    def _dashboard(self):
        today = date.today().isoformat()
        with db() as conn:
            today_sales = conn.execute(
                "SELECT COALESCE(SUM(total), 0) s, COUNT(*) c FROM sales WHERE DATE(created_at) = ?",
                (today,),
            ).fetchone()
            all_sales = conn.execute("SELECT COALESCE(SUM(total), 0) s, COUNT(*) c FROM sales").fetchone()
            low_stock = conn.execute(
                "SELECT * FROM products WHERE stock IS NOT NULL AND stock <= 5 ORDER BY stock"
            ).fetchall()
            recent = conn.execute("SELECT * FROM sales ORDER BY id DESC LIMIT 8").fetchall()
        settings = get_settings()
        self._send(
            200,
            {
                "today": today,
                "currency": settings["currency"],
                "today_revenue": round(today_sales["s"], 2),
                "today_count": today_sales["c"],
                "total_revenue": round(all_sales["s"], 2),
                "total_count": all_sales["c"],
                "low_stock": [dict(r) for r in low_stock],
                "recent": [dict(r) for r in recent],
            },
        )


def main():
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Cashier app running at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
