# backend/main.py  (FINAL: ML model + safety rules)
from pathlib import Path
from typing import Literal, Optional          # NEW: Optional
import json
import random

import pandas as pd
import shap
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from xgboost import XGBClassifier

# Folder this file lives in, so file paths work wherever you start the server
BASE = Path(__file__).parent

# ---------- 1. Load everything ONCE, when the server starts ----------
model = XGBClassifier()
model.load_model(str(BASE / "model" / "xgb_model.json"))

with open(BASE / "model" / "feature_columns.json") as f:
    FEATURE_COLUMNS = json.load(f)       # exact column order the model expects

with open(BASE / "model" / "config.json") as f:
    CONFIG = json.load(f)
THRESHOLD = CONFIG["threshold"]          # score at/above this = RISKY
REASONS = CONFIG["reasons"]              # feature name -> plain-English sentence

explainer = shap.TreeExplainer(model)    # SHAP: explains individual scores
stream_df = pd.read_csv(BASE / "test_stream.csv")   # unseen rows for the demo

# ---------- 2. Create the app and allow the frontend to call it ----------
app = FastAPI(title="UPI Fraud Shield API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # anyone; fine for a hackathon
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 3. What a payment request looks like ----------
class Payment(BaseModel):
    amount: float
    type: Literal["TRANSFER", "CASH_OUT", "PAYMENT", "CASH_IN", "DEBIT"]
    oldbalanceOrg: float      # sender's balance before
    newbalanceOrig: float     # sender's balance after
    oldbalanceDest: float     # receiver's balance before
    newbalanceDest: float     # receiver's balance after
    hour: int                 # 0-23
    # --- NEW: optional context that a payments app knows about its customer ---
    # None = "not provided", and then the safety rules are skipped
    # (so the PaySim sample flow still uses the ML model only).
    payee_known: Optional[bool] = None         # paid this person before / saved contact?
    is_collect_request: Optional[bool] = None  # approving a "request money" message?
    usual_amount: Optional[float] = None       # the customer's typical payment size

# ---------- 4. Turn a payment into the exact row the model was trained on ----------
def build_features(p: Payment) -> pd.DataFrame:
    row = {col: 0.0 for col in FEATURE_COLUMNS}      # every column starts at 0
    row["amount"] = p.amount
    row["oldbalanceOrg"] = p.oldbalanceOrg
    row["newbalanceOrig"] = p.newbalanceOrig
    row["oldbalanceDest"] = p.oldbalanceDest
    row["newbalanceDest"] = p.newbalanceDest
    row["hour"] = p.hour
    # same formulas as the notebook
    row["errorOrig"] = p.oldbalanceOrg - p.amount - p.newbalanceOrig
    row["errorDest"] = p.oldbalanceDest + p.amount - p.newbalanceDest
    # one-hot type: set only the matching type_ column to 1
    type_col = f"type_{p.type}"
    if type_col in row:
        row[type_col] = 1.0
    # columns=FEATURE_COLUMNS forces the correct order
    return pd.DataFrame([row], columns=FEATURE_COLUMNS)

# ---------- NEW: hand-written safety rules ----------
def apply_rules(p: Payment):
    """Returns (rule_score 0-1, list of plain-English reasons)."""
    if p.payee_known is None:          # no customer context given -> skip the rules
        return 0.0, []

    score, reasons = 0.0, []

    # Classic UPI scam: a stranger sends a "collect" request and you approve it
    if p.is_collect_request and not p.payee_known:
        score += 0.60
        reasons.append("An unknown person is requesting money from you. "
                       "You never need to approve a request to receive money")
    if not p.payee_known and p.amount >= 10_000:
        score += 0.30
        reasons.append("Large payment to someone you have never paid before")
    if p.oldbalanceOrg > 0 and p.amount >= 0.9 * p.oldbalanceOrg:
        score += 0.30
        reasons.append("This payment would use up almost your entire balance")
    if p.usual_amount and p.amount >= 5 * p.usual_amount:
        score += 0.30
        reasons.append(f"Amount is {p.amount / p.usual_amount:.0f}x your usual payment")
    if 0 <= p.hour <= 5 and p.amount >= 10_000:
        score += 0.20
        reasons.append("Large payment made late at night")

    return min(score, 0.99), reasons

# ---------- 5. Endpoints ----------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/score")
def score(payment: Payment):
    X = build_features(payment)
    model_score = float(model.predict_proba(X)[0, 1])    # NEW: brain 1, the ML model
    rule_score, rule_reasons = apply_rules(payment)       # NEW: brain 2, the rules
    risk = max(model_score, rule_score)                   # trust whichever is more worried
    verdict = "RISKY" if risk >= THRESHOLD else "SAFE"

    reasons = []
    if verdict == "RISKY":
        reasons += rule_reasons
        if model_score >= THRESHOLD:     # SHAP reasons only when the ML model raised the alarm
            contribs = pd.Series(explainer.shap_values(X)[0], index=FEATURE_COLUMNS)
            top = contribs[contribs > 0].sort_values(ascending=False).head(3)
            reasons += [REASONS.get(name, name) for name in top.index]

    model_flag = model_score >= THRESHOLD
    rule_flag = rule_score >= THRESHOLD
    flagged_by = ("model + rules" if model_flag and rule_flag else
                  "ML model" if model_flag else
                  "safety rules" if rule_flag else "none")

    return {
        "risk_score": round(risk, 4),
        "verdict": verdict,
        "reasons": reasons,
        "flagged_by": flagged_by,           # NEW: which brain raised the alarm
        "model_score": round(model_score, 4),
        "rule_score": round(rule_score, 4),
    }

@app.get("/sample")
def sample(fraud: bool = False):
    """Return one real, unseen transaction. ?fraud=true gives a known fraud one."""
    pool = stream_df[stream_df["isFraud"] == (1 if fraud else 0)]
    row = pool.sample(1).iloc[0]
    # the CSV stores type as one-hot columns; turn back into a single word
    tx_type = next((c.replace("type_", "") for c in stream_df.columns
                    if c.startswith("type_") and bool(row[c])), "PAYMENT")
    return {
        "amount": float(row["amount"]),
        "type": tx_type,
        "oldbalanceOrg": float(row["oldbalanceOrg"]),
        "newbalanceOrig": float(row["newbalanceOrig"]),
        "oldbalanceDest": float(row["oldbalanceDest"]),
        "newbalanceDest": float(row["newbalanceDest"]),
        "hour": int(row["hour"]),
        "actual_label": "FRAUD" if row["isFraud"] == 1 else "LEGIT",  # demo only
    }

# ---------- 6. Live feed + dashboard numbers ----------
# Running totals (reset when the server restarts, or by POST /reset)
stats = {"scanned": 0, "flagged": 0, "amount_flagged": 0.0}

@app.get("/next")
def next_transaction():
    """Pick a random unseen payment, score it, return everything in one go."""
    fraud = random.random() < 0.15       # ~15% of demo payments are scams

    tx = sample(fraud=fraud)             # reuse the /sample function above
    label = tx.pop("actual_label")       # remove the answer key before scoring
    result = score(Payment(**tx))        # reuse /score (no context fields -> rules skipped)

    stats["scanned"] += 1
    if result["verdict"] == "RISKY":
        stats["flagged"] += 1
        stats["amount_flagged"] += tx["amount"]

    return {"payment": tx, "result": result, "actual_label": label}

@app.get("/stats")
def get_stats():
    return stats

@app.post("/reset")
def reset_stats():
    """Zero the counters, handy right before you demo to the judges."""
    stats.update({"scanned": 0, "flagged": 0, "amount_flagged": 0.0})
    return stats