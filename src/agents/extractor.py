# agents/extractor.py
"""
Extractor agent (pure function).
Input: email dict with keys: email_id, from, to, subject, date, body, linked_invoice, linked_po, label
Output: dict with extracted fields (invoice_number, po_number, claimed_amount, currency, claim_type, claim_text, confidence)
- By default uses a regex fallback. If OPENAI_API_KEY env var is set it will try to call OpenAI ChatCompletion.
"""

import os
import re
import json

# Optional: import openai only if key present
try:
    import openai
except Exception:
    openai = None

INV_RE = re.compile(r'\bINV[-\s]?\d{3,}\b', re.I)
PO_RE = re.compile(r'\bPO[-\s]?\d{4,}\b', re.I)
AMT_RE = re.compile(r'INR\s?([\d,]+(?:\.\d{1,2})?)', re.I)

LLM_PROMPT = """
You are an extractor that MUST output JSON only following this schema:
{ "invoice_number": null or "INV-0001", "po_number": null or "PO-2024-0001",
  "claimed_amount": null or number, "currency": "INR" or null,
  "claim_type": one of [short_delivery, tax_mismatch, not_received, duplicate_invoice, other],
  "claim_text": short sentence, "confidence": number 0-1 }

Return JSON only. Now extract from the email below:

\"\"\"<<EMAIL_BODY>>\"\"\"
"""

def _regex_extract(body: str):
    inv = INV_RE.search(body)
    po = PO_RE.search(body)
    amt = AMT_RE.search(body)
    invoice = inv.group(0).replace(" ", "") if inv else None
    po_number = po.group(0).replace(" ", "") if po else None
    claimed_amount = float(amt.group(1).replace(",","")) if amt else None
    lower = body.lower()
    if "short" in lower:
        claim_type = "short_delivery"
    elif "tax" in lower:
        claim_type = "tax_mismatch"
    elif "not received" in lower or "never received" in lower:
        claim_type = "not_received"
    elif "duplicate" in lower:
        claim_type = "duplicate_invoice"
    else:
        claim_type = "other"
    return {
        "invoice_number": invoice,
        "po_number": po_number,
        "claimed_amount": claimed_amount,
        "currency": "INR" if claimed_amount else None,
        "claim_type": claim_type,
        "claim_text": body.strip().replace("\n"," ")[:300],
        "confidence": 0.6
    }

def _call_openai(body: str):
    key = os.getenv("OPENAI_API_KEY")
    if not key or openai is None:
        return None
    openai.api_key = key
    # replace the safe token (no braces!) with the email body
    prompt = LLM_PROMPT.replace("<<EMAIL_BODY>>", body)
    try:
        resp = openai.ChatCompletion.create(
            model=os.getenv("OPENAI_MODEL","gpt-4o-mini"),
            messages=[{"role":"user","content":prompt}],
            temperature=0.0,
            max_tokens=300
        )
        text = resp["choices"][0]["message"]["content"].strip()
        parsed = json.loads(text)
        parsed["confidence"] = float(parsed.get("confidence", 0.5))
        return parsed
    except Exception as e:
        print("[Extractor] OpenAI call/parse failed:", e)
        return None

def extract(email_obj: dict) -> dict:
    """
    Main extractor function to call from runner.
    Tries LLM first (if key present), otherwise regex fallback.
    """
    body = email_obj.get("body","") or ""
    llm_result = _call_openai(body)
    if llm_result:
        # normalize keys to expected format
        return {
            "invoice_number": llm_result.get("invoice_number"),
            "po_number": llm_result.get("po_number"),
            "claimed_amount": llm_result.get("claimed_amount"),
            "currency": llm_result.get("currency"),
            "claim_type": llm_result.get("claim_type"),
            "claim_text": llm_result.get("claim_text"),
            "confidence": float(llm_result.get("confidence", 0.5)),
            "llm_raw": llm_result
        }
    # fallback
    r = _regex_extract(body)
    r["llm_raw"] = None
    return r
