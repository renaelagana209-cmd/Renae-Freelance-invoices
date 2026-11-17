import json
import sqlite3
from datetime import date, datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DB_PATH = Path(__file__).parent / "freelance.db"
HOST, PORT = "127.0.0.1", 8000

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT DEFAULT '',
    address TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT DEFAULT '',
    client_id INTEGER NOT NULL REFERENCES clients(id),
    issue_date TEXT NOT NULL,
    due_date TEXT DEFAULT '',
    tax_rate REAL DEFAULT 0,
    status TEXT DEFAULT 'draft',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    qty REAL DEFAULT 1,
    price REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);
"""

DEFAULT_SETTINGS = {
    "business_name": "My Business",
    "business_email": "",
    "business_address": "",
    "currency": "$",
    "tax_rate": "0",
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


def invoice_totals(conn, invoice_id):
    row = conn.execute(
        "SELECT COALESCE(SUM(qty * price), 0) s FROM invoice_items WHERE invoice_id = ?",
        (invoice_id,),
    ).fetchone()
    inv = conn.execute("SELECT tax_rate FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    subtotal = row["s"] if row else 0
    tax_rate = inv["tax_rate"] if inv else 0
    tax = round(subtotal * tax_rate / 100, 2)
    return {"subtotal": round(subtotal, 2), "tax": tax, "total": round(subtotal + tax, 2)}


def invoice_row(conn, inv):
    client = conn.execute("SELECT name, email FROM clients WHERE id = ?", (inv["client_id"],)).fetchone()
    data = dict(inv)
    data["client_name"] = client["name"] if client else "?"
    data.update(invoice_totals(conn, inv["id"]))
    return data


def money(value, currency):
    return f"{currency}{value:,.2f}"


def render_invoice_page(inv, items, client, settings):
    cur = settings["currency"]
    rows = "".join(
        f"<tr><td>{escape(i['description'])}</td><td class='r'>{i['qty']:g}</td>"
        f"<td class='r'>{money(i['price'], cur)}</td><td class='r'>{money(i['qty'] * i['price'], cur)}</td></tr>"
        for i in items
    )
    address_html = escape(settings["business_address"]).replace("\n", "<br>")
    client_address = escape(client["address"]).replace("\n", "<br>") if client else ""
    status = inv["status"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(inv['number'])}</title>
<style>
  body {{ font-family: Georgia, 'Times New Roman', serif; color: #111; max-width: 800px; margin: 40px auto; padding: 0 20px; }}
  .top {{ display: flex; justify-content: space-between; align-items: flex-start; }}
  h1 {{ margin: 0; font-size: 28px; letter-spacing: 2px; }}
  .meta, .addresses {{ font-size: 14px; line-height: 1.6; }}
  .meta td {{ padding: 2px 8px; }}
  .meta td:first-child {{ color: #666; text-align: right; }}
  table.items {{ width: 100%; border-collapse: collapse; margin-top: 30px; font-size: 14px; }}
  th, td {{ border-bottom: 1px solid #ddd; padding: 8px 6px; text-align: left; }}
  th {{ border-bottom: 2px solid #111; }}
  .r {{ text-align: right; }}
  .totals {{ margin-top: 16px; margin-left: auto; width: 260px; font-size: 14px; }}
  .totals td {{ padding: 4px 8px; }}
  .totals .grand {{ font-weight: bold; font-size: 16px; border-top: 2px solid #111; }}
  .badge {{ display: inline-block; padding: 2px 10px; border: 1px solid #111; border-radius: 99px; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }}
  .notes {{ margin-top: 30px; font-size: 13px; color: #444; white-space: pre-wrap; }}
  .noprint {{ text-align: center; margin-bottom: 30px; }}
  .noprint button {{ padding: 8px 24px; font-size: 14px; cursor: pointer; }}
  @media print {{ .noprint {{ display: none; }} body {{ margin: 0; }} }}
</style>
</head>
<body>
<div class="noprint"><button onclick="window.print()">Print / Save as PDF</button></div>
<div class="top">
  <div>
    <h1>INVOICE</h1>
    <div class="meta">
      <table>
        <tr><td>Number</td><td><strong>{escape(inv['number'])}</strong></td></tr>
        <tr><td>Issued</td><td>{escape(inv['issue_date'])}</td></tr>
        <tr><td>Due</td><td>{escape(inv['due_date'] or '-')}</td></tr>
        <tr><td>Status</td><td><span class="badge">{escape(status)}</span></td></tr>
      </table>
    </div>
  </div>
  <div class="addresses">
    <strong>{escape(settings['business_name'])}</strong><br>
    {address_html}
    {('<br>' + escape(settings['business_email'])) if settings['business_email'] else ''}
  </div>
</div>
<div class="addresses" style="margin-top:30px">
  <strong>Billed to:</strong><br>
  {escape(client['name']) if client else ''}<br>
  {client_address}
</div>
<table class="items">
  <thead><tr><th>Description</th><th class="r">Qty</th><th class="r">Unit price</th><th class="r">Amount</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
<table class="totals">
  <tr><td>Subtotal</td><td class="r">{money(inv['subtotal'], cur)}</td></tr>
  <tr><td>Tax ({inv['tax_rate']:g}%)</td><td class="r">{money(inv['tax'], cur)}</td></tr>
  <tr class="grand"><td>Total</td><td class="r">{money(inv['total'], cur)}</td></tr>
</table>
{f'<div class="notes">{escape(inv["notes"])}</div>' if inv['notes'] else ''}
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
        if path.startswith("/invoice/") and path[len("/invoice/"):].isdigit():
            self._invoice_page(int(path[len("/invoice/"):]))
            return
        if path == "/api/dashboard":
            self._dashboard()
            return
        if path == "/api/settings":
            self._send(200, get_settings())
            return
        if path == "/api/clients":
            with db() as conn:
                rows = conn.execute("SELECT * FROM clients ORDER BY name COLLATE NOCASE").fetchall()
            self._send(200, [dict(r) for r in rows])
            return
        if path == "/api/invoices":
            with db() as conn:
                rows = conn.execute(
                    "SELECT * FROM invoices ORDER BY id DESC"
                ).fetchall()
                self._send(200, [invoice_row(conn, r) for r in rows])
            return
        if path.startswith("/api/invoices/") and path[len("/api/invoices/"):].isdigit():
            with db() as conn:
                inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (int(path.split("/")[-1]),)).fetchone()
                if not inv:
                    self._send(404, {"error": "not found"})
                    return
                items = conn.execute(
                    "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY id", (inv["id"],)
                ).fetchall()
                client = conn.execute("SELECT * FROM clients WHERE id = ?", (inv["client_id"],)).fetchone()
            data = invoice_row(conn, inv)
            data["items"] = [dict(i) for i in items]
            data["client"] = dict(client) if client else None
            self._send(200, data)
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/clients":
            data = self._body()
            name = str(data.get("name", "")).strip()
            if not name:
                self._send(400, {"error": "name is required"})
                return
            with db() as conn:
                cur = conn.execute(
                    "INSERT INTO clients (name, email, address, created_at) VALUES (?, ?, ?, ?)",
                    (name, str(data.get("email", "")), str(data.get("address", "")), datetime.now().isoformat(timespec="seconds")),
                )
                row = conn.execute("SELECT * FROM clients WHERE id = ?", (cur.lastrowid,)).fetchone()
            self._send(201, dict(row))
            return
        if path == "/api/invoices":
            self._create_invoice()
            return
        self._send(404, {"error": "not found"})

    def do_PUT(self):
        path = urlparse(self.path).path
        if path == "/api/settings":
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
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "clients" and parts[2].isdigit():
            data = self._body()
            allowed = {k: data[k] for k in ("name", "email", "address") if k in data}
            if not allowed:
                self._send(400, {"error": "no valid fields"})
                return
            sets = ", ".join(f"{k} = ?" for k in allowed)
            with db() as conn:
                cur = conn.execute(f"UPDATE clients SET {sets} WHERE id = ?", list(allowed.values()) + [int(parts[2])])
                if cur.rowcount == 0:
                    self._send(404, {"error": "not found"})
                    return
                row = conn.execute("SELECT * FROM clients WHERE id = ?", (int(parts[2]),)).fetchone()
            self._send(200, dict(row))
            return
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "invoices" and parts[2].isdigit():
            if parts[3] == "status":
                self._set_status(int(parts[2]))
                return
            if parts[3] == "items":
                self._add_item(int(parts[2]))
                return
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "invoices" and parts[2].isdigit():
            self._update_invoice(int(parts[2]))
            return
        self._send(404, {"error": "not found"})

    def do_DELETE(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] in ("clients", "invoices") and parts[2].isdigit():
            table = parts[1]
            item_id = int(parts[2])
            with db() as conn:
                if table == "invoices":
                    conn.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (item_id,))
                cur = conn.execute(f"DELETE FROM {table} WHERE id = ?", (item_id,))
            if cur.rowcount == 0:
                self._send(404, {"error": "not found"})
                return
            self._send(200, {"ok": True})
            return
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "invoices" and parts[2].isdigit() and parts[3].isdigit():
            with db() as conn:
                cur = conn.execute(
                    "DELETE FROM invoice_items WHERE id = ? AND invoice_id = ?",
                    (int(parts[3]), int(parts[2])),
                )
            if cur.rowcount == 0:
                self._send(404, {"error": "not found"})
                return
            self._send(200, {"ok": True})
            return
        self._send(404, {"error": "not found"})

    def _create_invoice(self):
        data = self._body()
        client_id = data.get("client_id")
        if not client_id:
            self._send(400, {"error": "client_id is required"})
            return
        items = data.get("items") or []
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO invoices (client_id, issue_date, due_date, tax_rate, status, notes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    client_id,
                    str(data.get("issue_date") or date.today().isoformat()),
                    str(data.get("due_date", "")),
                    float(data.get("tax_rate") or 0),
                    "draft",
                    str(data.get("notes", "")),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            invoice_id = cur.lastrowid
            conn.execute("UPDATE invoices SET number = ? WHERE id = ?", (f"INV-{invoice_id:04d}", invoice_id))
            for item in items:
                conn.execute(
                    "INSERT INTO invoice_items (invoice_id, description, qty, price) VALUES (?, ?, ?, ?)",
                    (invoice_id, str(item.get("description", "")), float(item.get("qty") or 0), float(item.get("price") or 0)),
                )
            inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        self._send(201, invoice_row(conn, inv))

    def _update_invoice(self, invoice_id):
        data = self._body()
        with db() as conn:
            inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            if not inv:
                self._send(404, {"error": "not found"})
                return
            fields = {k: data[k] for k in ("client_id", "issue_date", "due_date", "tax_rate", "notes") if k in data}
            if "tax_rate" in fields:
                fields["tax_rate"] = float(fields["tax_rate"] or 0)
            if fields:
                sets = ", ".join(f"{k} = ?" for k in fields)
                conn.execute(f"UPDATE invoices SET {sets} WHERE id = ?", list(fields.values()) + [invoice_id])
            if "items" in data:
                conn.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (invoice_id,))
                for item in data["items"]:
                    if str(item.get("description", "")).strip():
                        conn.execute(
                            "INSERT INTO invoice_items (invoice_id, description, qty, price) VALUES (?, ?, ?, ?)",
                            (invoice_id, str(item.get("description", "")), float(item.get("qty") or 0), float(item.get("price") or 0)),
                        )
            inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        self._send(200, invoice_row(conn, inv))

    def _set_status(self, invoice_id):
        data = self._body()
        status = data.get("status")
        if status not in ("draft", "sent", "paid"):
            self._send(400, {"error": "invalid status"})
            return
        with db() as conn:
            cur = conn.execute("UPDATE invoices SET status = ? WHERE id = ?", (status, invoice_id))
            if cur.rowcount == 0:
                self._send(404, {"error": "not found"})
                return
            inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        self._send(200, invoice_row(conn, inv))

    def _invoice_page(self, invoice_id):
        with db() as conn:
            inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            if not inv:
                self._send(404, {"error": "not found"})
                return
            items = conn.execute(
                "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY id", (invoice_id,)
            ).fetchall()
            client = conn.execute("SELECT * FROM clients WHERE id = ?", (inv["client_id"],)).fetchone()
        data = invoice_row(conn, inv)
        page = render_invoice_page(data, [dict(i) for i in items], dict(client) if client else None, get_settings())
        self._send(200, page.encode(), "text/html; charset=utf-8")

    def _dashboard(self):
        today = date.today().isoformat()
        month = today[:7]
        with db() as conn:
            invoices = conn.execute("SELECT * FROM invoices").fetchall()
            clients = conn.execute("SELECT COUNT(*) c FROM clients").fetchone()["c"]
        outstanding = paid = paid_month = 0.0
        overdue = 0
        for inv in invoices:
            totals = invoice_totals(conn, inv["id"])
            if inv["status"] == "paid":
                paid += totals["total"]
                if inv["issue_date"][:7] == month:
                    paid_month += totals["total"]
            else:
                outstanding += totals["total"]
                if inv["due_date"] and inv["due_date"] < today:
                    overdue += 1
        recent = [invoice_row(conn, r) for r in conn.execute("SELECT * FROM invoices ORDER BY id DESC LIMIT 5").fetchall()]
        settings = get_settings()
        self._send(
            200,
            {
                "today": today,
                "currency": settings["currency"],
                "outstanding": round(outstanding, 2),
                "paid_total": round(paid, 2),
                "paid_this_month": round(paid_month, 2),
                "overdue": overdue,
                "clients": clients,
                "invoices": len(invoices),
                "recent": recent,
            },
        )


def main():
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Freelance Invoicing running at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
