# runner.py
"""
Local runner: reads emails_abc_chem.jsonl and runs extractor -> verifier -> scorer for each email.
Saves results to simple local JSON summary and prints a summary table.
"""

import json, os
from src.agents.extractor import extract as extractor_extract
from src.agents.verifier import verify as verifier_verify
from src.agents.scorer import compute_score as scorer_compute

JSONL = os.getenv("EMAILS_JSONL", "data/raw/emails_abc_chem.jsonl")
OUT_SUMMARY = os.getenv("OUT_SUMMARY", "data/out/run_summary.json")

def process_all(jsonl_path=JSONL):
    summaries = []
    with open(jsonl_path, "r", encoding="utf-8") as fh:
        for line in fh:
            email = json.loads(line)
            email_id = email.get("email_id")
            print("\n--- Processing email", email_id, "subject:", email.get("subject"))
            extraction = extractor_extract(email)
            print("  Extraction:", {k: extraction.get(k) for k in ("invoice_number","po_number","claimed_amount","claim_type","confidence")})
            verification = verifier_verify(extraction)
            print("  Verification:", {k: verification.get(k) for k in ("invoice_exists","po_exists","grn_exists","contradictions")})
            score = scorer_compute(extraction, verification, email.get("from") or "")
            print("  Score:", score)
            summaries.append({
                "email_id": email_id,
                "subject": email.get("subject"),
                "extraction": extraction,
                "verification": verification,
                "score": score
            })
    # write summary
    with open(OUT_SUMMARY, "w", encoding="utf-8") as fh:
        json.dump(summaries, fh, indent=2, default=str)
    print("\nDone. Summary written to", OUT_SUMMARY)
    return summaries

if __name__ == "__main__":
    process_all()
