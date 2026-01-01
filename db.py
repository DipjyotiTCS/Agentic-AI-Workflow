import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional
import json
import uuid
from datetime import datetime

DB_PATH = Path("runtime.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            sku TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            purpose TEXT NOT NULL,
            price_usd REAL NOT NULL,
            is_active INTEGER NOT NULL,
            keywords TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sales_requests (
            ticket_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            customer_hint TEXT,
            email_subject TEXT,
            email_body TEXT NOT NULL,
            attachments_json TEXT NOT NULL,
            classification_json TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS support_requests (
            ticket_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            customer_hint TEXT,
            email_subject TEXT,
            email_body TEXT NOT NULL,
            attachments_json TEXT NOT NULL,
            intent TEXT NOT NULL,
            confidence REAL NOT NULL,
            classification_json TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def seed_dummy_products_if_empty() -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM products")
    c = cur.fetchone()["c"]
    if c > 0:
        conn.close()
        return

    products = [
        {
            "sku": "PROD-CRM-001",
            "name": "NimbusCRM Starter",
            "category": "CRM",
            "purpose": "Small teams CRM with email tracking and pipelines",
            "price_usd": 49.0,
            "is_active": 1,
            "keywords": "crm pipeline leads email tracking small team starter",
        },
        {
            "sku": "PROD-CRM-010",
            "name": "NimbusCRM Pro",
            "category": "CRM",
            "purpose": "Advanced CRM with automation, analytics, and role-based access",
            "price_usd": 149.0,
            "is_active": 1,
            "keywords": "crm automation analytics rbac enterprise pro",
        },
        {
            "sku": "PROD-SUP-100",
            "name": "HelioSupport Desk",
            "category": "Support",
            "purpose": "Ticketing + SLA + knowledge base for support teams",
            "price_usd": 99.0,
            "is_active": 1,
            "keywords": "support ticketing sla knowledge base helpdesk",
        },
        {
            "sku": "PROD-BI-200",
            "name": "AuroraBI",
            "category": "Analytics",
            "purpose": "Self-serve dashboards and KPI tracking for leadership",
            "price_usd": 199.0,
            "is_active": 1,
            "keywords": "bi dashboards kpi analytics reporting leadership",
        },
        {
            "sku": "PROD-OLD-777",
            "name": "LegacyBundle X (Deprecated)",
            "category": "Bundle",
            "purpose": "Deprecated legacy bundle (not available)",
            "price_usd": 79.0,
            "is_active": 0,
            "keywords": "legacy deprecated bundle old",
        },
    ]

    cur.executemany(
        """
        INSERT INTO products (sku, name, category, purpose, price_usd, is_active, keywords)
        VALUES (:sku, :name, :category, :purpose, :price_usd, :is_active, :keywords)
        """,
        products,
    )

    conn.commit()
    conn.close()


def create_sales_ticket(
    email_subject: str,
    email_body: str,
    attachments: List[Dict[str, Any]],
    classification: Dict[str, Any],
    customer_hint: Optional[str] = None,
) -> str:
    conn = get_conn()
    cur = conn.cursor()
    ticket_id = f"SR-{uuid.uuid4().hex[:10].upper()}"
    cur.execute(
        """
        INSERT INTO sales_requests (ticket_id, created_at, customer_hint, email_subject, email_body, attachments_json, classification_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticket_id,
            datetime.utcnow().isoformat(),
            customer_hint,
            email_subject,
            email_body,
            json.dumps(attachments, ensure_ascii=False),
            json.dumps(classification, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()
    return ticket_id


def create_support_ticket(
    email_subject: str,
    email_body: str,
    attachments: List[Dict[str, Any]],
    intent: str,
    confidence: float,
    classification: Dict[str, Any],
    customer_hint: Optional[str] = None,
) -> str:
    conn = get_conn()
    cur = conn.cursor()
    ticket_id = f"SUP-{uuid.uuid4().hex[:10].upper()}"
    cur.execute(
        """
        INSERT INTO support_requests (
            ticket_id, created_at, customer_hint, email_subject, email_body, attachments_json,
            intent, confidence, classification_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticket_id,
            datetime.utcnow().isoformat(),
            customer_hint,
            email_subject,
            email_body,
            json.dumps(attachments, ensure_ascii=False),
            intent,
            float(confidence),
            json.dumps(classification, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()
    return ticket_id


def get_ticket(ticket_id: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()

    if ticket_id.startswith("SR-"):
        cur.execute("SELECT * FROM sales_requests WHERE ticket_id=?", (ticket_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    if ticket_id.startswith("SUP-"):
        cur.execute("SELECT * FROM support_requests WHERE ticket_id=?", (ticket_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    cur.execute("SELECT * FROM sales_requests WHERE ticket_id=?", (ticket_id,))
    row = cur.fetchone()
    if row:
        conn.close()
        return dict(row)

    cur.execute("SELECT * FROM support_requests WHERE ticket_id=?", (ticket_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def search_products_by_exact_mention(mentions: List[str]) -> List[Dict[str, Any]]:
    if not mentions:
        return []
    conn = get_conn()
    cur = conn.cursor()

    results: List[Dict[str, Any]] = []
    for m in mentions:
        like = f"%{m.strip()}%"
        cur.execute(
            """
            SELECT * FROM products
            WHERE (sku LIKE ? OR name LIKE ?)
            LIMIT 10
            """,
            (like, like),
        )
        for row in cur.fetchall():
            results.append(dict(row))

    conn.close()
    uniq = {r["sku"]: r for r in results}
    return list(uniq.values())


def search_products_by_need_keywords(keywords: List[str], limit: int = 10) -> List[Dict[str, Any]]:
    if not keywords:
        return []
    conn = get_conn()
    cur = conn.cursor()

    where = " OR ".join(["keywords LIKE ?"] * len(keywords))
    params = [f"%{k.strip()}%" for k in keywords]

    cur.execute(
        f"""
        SELECT * FROM products
        WHERE ({where})
        LIMIT ?
        """,
        (*params, limit),
    )

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_active_products() -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE is_active=1 ORDER BY price_usd ASC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
