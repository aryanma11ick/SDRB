# agents/verifier.py
"""
Verifier agent (pure function).
Verifies extracted fields against Postgres SAP mock data (invoice, PO, GRN).
If PG* env vars aren't present or DB connection fails, returns 'offline' verification (no DB checks).
"""
from dotenv import load_dotenv
load_dotenv()

import os
import psycopg2
from psycopg2.extras import RealDictCursor

DB_CFG = {
    "host": os.getenv("PGHOST","localhost"),
    "port": int(os.getenv("PGPORT",5432)),
    "dbname": os.getenv("PGDATABASE","sdrb_db"),
    "user": os.getenv("PGUSER","sdrb"),
    "password": os.getenv("PGPASSWORD","sdrbpass"),
}

def _connect():
    try:
        return psycopg2.connect(cursor_factory=RealDictCursor, **DB_CFG)
    except Exception as e:
        # DB offline or not configured
        print("[Verifier] DB connect failed, running offline:", e)
        return None

def verify(extraction: dict) -> dict:
    """
    Returns verification dict:
    { invoice_exists, invoice_id, invoice_amount, po_exists, po_id, grn_exists, grn_ids, contradictions }
    """
    invoice = extraction.get("invoice_number")
    po = extraction.get("po_number")
    out = {
        "invoice_exists": False, "invoice_id": None, "invoice_amount": None,
        "po_exists": False, "po_id": None, "grn_exists": False, "grn_ids": [],
        "contradictions": []
    }
    conn = _connect()
    if conn is None:
        # offline mode — just return defaults (no contradictions)
        return out
    try:
        with conn.cursor() as cur:
            if invoice:
                cur.execute("SELECT invoice_id, amount, sap_status FROM invoice WHERE invoice_number = %s", (invoice,))
                r = cur.fetchone()
                if r:
                    out["invoice_exists"] = True
                    out["invoice_id"] = int(r["invoice_id"])
                    out["invoice_amount"] = float(r["amount"]) if r["amount"] is not None else None
                    out["invoice_status"] = r["sap_status"]
            if po:
                cur.execute("SELECT po_id FROM purchase_order WHERE po_number = %s", (po,))
                r = cur.fetchone()
                if r:
                    out["po_exists"] = True
                    out["po_id"] = int(r["po_id"])
                    # check GRNs
                    cur.execute("SELECT grn_id FROM goods_receipt WHERE po_id = %s", (out["po_id"],))
                    rows = cur.fetchall()
                    if rows:
                        out["grn_exists"] = True
                        out["grn_ids"] = [int(x["grn_id"]) for x in rows]
            # contradictions detection
            if extraction.get("claim_type") == "not_received" and out["grn_exists"]:
                out["contradictions"].append("not_received_but_grn_exists")
            if extraction.get("claimed_amount") and out.get("invoice_amount"):
                try:
                    if abs(float(extraction.get("claimed_amount") or 0) - out["invoice_amount"]) > 1.0:
                        out["contradictions"].append("amount_mismatch")
                except Exception:
                    pass
    finally:
        conn.close()
    return out
