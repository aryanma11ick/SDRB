# src/ai/extractor_agent.py
import json
from pathlib import Path
from src.ai.email_parser_llm import extract_structured

DATA_RAW = Path("data/raw")
EMAILS_JSON = DATA_RAW / "emails.json"
OUT_DIR = Path("data/processed")
OUT_DIR.mkdir(parents=True, exist_ok=True)
EXTRACTED_JSONL = OUT_DIR / "extracted_emails.jsonl"
CACHE_PATH = OUT_DIR / "extraction_cache.json"  # will store raw LLM outputs keyed by email hash

def run_extraction(use_llm_if_missing=True, llm_model="gpt-4o"):
    with EMAILS_JSON.open("r", encoding="utf-8") as f:
        emails = json.load(f)

    with EXTRACTED_JSONL.open("w", encoding="utf-8") as out_f:
        for e in emails:
            subject = e.get("subject","")
            body = e.get("body","")
            structured = extract_structured(subject, body, use_llm_if_missing=use_llm_if_missing, llm_model=llm_model, cache_path=str(CACHE_PATH))
            # attach email id for traceability
            record = {
                "email_id": e.get("email_id"),
                "sender_name": e.get("sender_name"),
                "sender_email": e.get("sender_email"),
                "subject": subject,
                "body": body,
                "extracted": structured
            }
            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print("Wrote", EXTRACTED_JSONL)

if __name__ == "__main__":
    run_extraction()
