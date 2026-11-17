# Freelance Invoicing

A self-contained invoicing app for freelancers. No dependencies — Python 3 standard library only.

## Run

```bash
python3 app.py
```

Then open http://127.0.0.1:8000 in your browser. Data is stored in `freelance.db` (SQLite), created automatically next to `app.py`.

## Features

- **Dashboard** — outstanding balance, paid this month, paid all time, overdue count, recent invoices
- **Clients** — name, email, address
- **Invoices** — auto-numbered (INV-0001…), line items with qty and unit price, tax rate, notes, live totals
- **Statuses** — draft → sent → paid, with automatic overdue flagging past the due date
- **Printable invoices** — open `/invoice/<id>` and use "Print / Save as PDF" for a clean, client-ready document
- **Settings** — business name, email, address, currency symbol, default tax rate

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/dashboard` | Totals and recent invoices |
| GET/POST | `/api/clients` | List / create clients |
| PUT/DELETE | `/api/clients/{id}` | Update / delete a client |
| GET/POST | `/api/invoices` | List / create invoice (with `items` array) |
| GET | `/api/invoices/{id}` | Invoice detail incl. items |
| PUT | `/api/invoices/{id}` | Update fields and/or replace items |
| PUT | `/api/invoices/{id}/status` | Set `draft`, `sent`, or `paid` |
| DELETE | `/api/invoices/{id}` | Delete invoice and its items |
| GET/PUT | `/api/settings` | Business details and defaults |
| GET | `/invoice/{id}` | Printable invoice page |
