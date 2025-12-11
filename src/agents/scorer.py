# agents/scorer.py
"""
Scorer agent (pure function).
Input: extraction dict, verification dict, sender string
Output: dict { suspicious_score (0..1), action, reasons }
"""

def compute_score(extraction: dict, verification: dict, sender: str) -> dict:
    # base suspiciousness inversely proportional to LLM confidence
    confidence = float(extraction.get("confidence", 0.5) or 0.5)
    base = 1.0 - confidence

    reasons = []
    # contradictions bump
    if verification.get("contradictions"):
        base += 0.35
        reasons.extend(verification.get("contradictions", []))
    # invoice referenced but missing in SAP
    if extraction.get("invoice_number") and not verification.get("invoice_exists"):
        base += 0.30
        reasons.append("invoice_missing_in_sap")
    # sender domain check
    if sender and (not sender.lower().endswith("@abcchem.com")):
        base += 0.15
        reasons.append("non_standard_sender")
    # clamp
    score = max(0.0, min(1.0, base))
    # map to action thresholds (tune later)
    if score >= 0.75:
        action = "HOLD_PAYMENT"
    elif score >= 0.35:
        action = "REQUEST_DOCS"
    else:
        action = "AUTO_APPROVE"
    return {"suspicious_score": round(score,3), "action": action, "reasons": reasons}
