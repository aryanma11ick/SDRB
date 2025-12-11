# src/ai/email_parser_llm.py
import os
import re
import json
import hashlib
from typing import Optional, Dict, Any
import openai
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
DEFAULT_MODEL = "gpt-4o"  # or change to your available model

# --- Regex patterns (deterministic fallback) ---
INVOICE_RE = re.compile(r"\bINV[-\s]?\d{3,7}\b", re.IGNORECASE)
PO_RE = re.compile(r"\b45\d{5,6}\b|\bPO[-\s]?\d{3,7}\b", re.IGNORECASE)
AMOUNT_RE = re.compile(r"₹\s?([0-9]{1,3}(?:[,0-9]{3})*(?:\.\d{1,2})?)|([0-9]{1,3}(?:[,0-9]{3})+(?:\.\d{1,2})?)")

def _ensure_api_key():
    key = os.environ.get(OPENAI_API_KEY_ENV)
    if not key:
        raise RuntimeError(f"Please set {OPENAI_API_KEY_ENV} in environment")
    openai.api_key = key

def call_llm_system_user(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL, temperature: float = 0.0, max_tokens: int = 400) -> str:
    _ensure_api_key()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    resp = openai.ChatCompletion.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens
    )
    return resp.choices[0].message["content"]

# --- Deterministic extraction helpers ---
def extract_invoice_regex(text: str) -> Optional[str]:
    m = INVOICE_RE.search(text)
    if not m:
        return None
    return m.group(0).upper().replace(" ", "-")

def extract_po_regex(text: str) -> Optional[str]:
    m = PO_RE.search(text)
    if not m:
        return None
    v = m.group(0)
    v = v.replace("PO", "").replace("-", "").strip()
    # normalize to start with 45 if missing
    if not v.startswith("45"):
        v = "45" + v
    return v

def extract_amounts_regex(text: str):
    vals = []
    for m in AMOUNT_RE.finditer(text):
        s = (m.group(1) or m.group(2) or "").replace(",", "")
        try:
            vals.append(float(s))
        except:
            continue
    return vals

# --- LLM prompt templates ---
SYSTEM_PROMPT = (
    "You are a strict JSON extractor. Given an email subject and body, return only valid JSON "
    "with keys: invoice_number (or null), po_number (or null), invoice_amount (number or null), "
    "po_amount (number or null), supplier_name (string or null), issue_summary (short string). "
    "Amounts should be numbers (no currency symbols). Invoice format: INV-1234. PO format: 45xxxxx."
)

USER_PROMPT_TEMPLATE = (
    "Email SUBJECT:\n{subject}\n\nEmail BODY:\n{body}\n\n"
    "Return the JSON only."
)

# --- Cache utils ---
def _make_key(subject: str, body: str) -> str:
    h = hashlib.sha256((subject + "\n" + body).encode("utf-8")).hexdigest()
    return h

def load_cache(path: Path) -> Dict[str, Any]:
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(path: Path, data: Dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- Public API ---
def extract_structured(subject: str, body: str, use_llm_if_missing: bool = True, llm_model: str = DEFAULT_MODEL, cache_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns a dict:
      {
        "invoice_number": str|None,
        "po_number": str|None,
        "invoice_amount": float|None,
        "po_amount": float|None,
        "supplier_name": str|None,
        "issue_summary": str
      }
    Uses regex first; if essential keys are missing and use_llm_if_missing==True -> calls LLM.
    Caches LLM outputs if cache_path provided.
    """
    text = (subject or "") + "\n" + (body or "")
    # 1) Regex pass
    invoice = extract_invoice_regex(text)
    po = extract_po_regex(text)
    amounts = extract_amounts_regex(text)
    invoice_amount = amounts[0] if amounts else None
    po_amount = amounts[1] if len(amounts) > 1 else None

    result = {
        "invoice_number": invoice,
        "po_number": po,
        "invoice_amount": invoice_amount,
        "po_amount": po_amount,
        "supplier_name": None,
        "issue_summary": ""
    }

    # if regex found sufficient info, return quickly
    if invoice and po:
        result["issue_summary"] = f"Extracted invoice {invoice} and PO {po} via regex"
        return result

    # otherwise, consider LLM
    if not use_llm_if_missing:
        result["issue_summary"] = "Incomplete via regex; LLM disabled"
        return result

    # caching
    cache = {}
    cache_file = Path(cache_path) if cache_path else None
    if cache_file:
        cache = load_cache(cache_file)

    key = _make_key(subject, body)
    if key in cache:
        llm_out = cache[key]
    else:
        user_prompt = USER_PROMPT_TEMPLATE.format(subject=subject, body=body)
        raw = call_llm_system_user(SYSTEM_PROMPT, user_prompt, model=llm_model, temperature=0.0, max_tokens=400)
        # sanitize and parse JSON
        s = raw.strip()
        if s.startswith("```"):
            # strip code fences
            lines = s.splitlines()
            # find first line with { and last line with }
            try:
                start = next(i for i,l in enumerate(lines) if "{" in l)
                end = len(lines) - list(reversed(lines)).index(next(l for l in reversed(lines) if "}" in l)) - 1
                s = "\n".join(lines[start:end+1])
            except Exception:
                s = s.strip("`")
        # find JSON inside
        m = re.search(r"(\{.*\})", s, re.S)
        if not m:
            raise RuntimeError(f"LLM did not return JSON. Raw:\n{s[:1000]}")
        json_text = m.group(1)
        try:
            llm_out = json.loads(json_text)
        except Exception as e:
            raise RuntimeError(f"Failed to parse JSON from LLM output. Err: {e}\nJSON text:\n{json_text[:1000]}")

        # cache
        if cache_file:
            cache[key] = llm_out
            save_cache(cache_file, cache)

    # merge llm_out into result (prefer regex when present)
    for k in ("invoice_number","po_number","invoice_amount","po_amount","supplier_name","issue_summary"):
        if result.get(k) in (None, "") and llm_out.get(k) is not None:
            result[k] = llm_out.get(k)

    # ensure numeric amounts converted
    for k in ("invoice_amount","po_amount"):
        v = result.get(k)
        try:
            if isinstance(v, str):
                result[k] = float(v.replace(",",""))
            elif v is None:
                result[k] = None
            else:
                result[k] = float(v)
        except Exception:
            result[k] = None

    if not result["issue_summary"]:
        result["issue_summary"] = "Merged regex + LLM extraction"

    # add metadata
    result["_meta"] = {"extracted_at": datetime.utcnow().isoformat(), "used_llm": key not in cache if cache_file else True}
    return result
