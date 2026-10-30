# backend/main.py  (FINAL)
from pathlib import Path
from typing import Literal
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

# CORS: lets a React page on another port (e.g. :5173) call this API on :8000
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

# ---------- 5. Endpoints ----------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/score")
def score(payment: Payment):
    X = build_features(payment)
    risk = float(model.predict_proba(X)[0, 1])        # fraud probability, 0 to 1
    verdict = "RISKY" if risk >= THRESHOLD else "SAFE"

    reasons = []
    if verdict == "RISKY":
        # SHAP: how much each feature pushed this score; keep the top 3 toward fraud
        contribs = pd.Series(explainer.shap_values(X)[0], index=FEATURE_COLUMNS)
        top = contribs[contribs > 0].sort_values(ascending=False).head(3)
        reasons = [REASONS.get(name, name) for name in top.index]

    return {"risk_score": round(risk, 4), "verdict": verdict, "reasons": reasons}

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
    result = score(Payment(**tx))        # reuse the /score function above

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