# frontend/app.py  (v3: cleaner, more like a real product)
import random
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

API = "http://localhost:8000"     # where your FastAPI backend runs
APP_NAME = "LOSAGA"               # change to your product name

st.set_page_config(page_title=f"{APP_NAME} | Payment Protection",
                   page_icon=":material/shield:", layout="wide")

# ======================================================================
# 0. Logo and styling
# ======================================================================
# The app writes this logo file once. To use your own (e.g. a Figma export),
# just replace frontend/assets/logo.svg. Delete it to regenerate this one.
LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 190 44" width="190" height="44">
  <path d="M22 3 L39 9 V22 C39 31 32 38 22 41 C12 38 5 31 5 22 V9 Z" fill="#16284f"/>
  <path d="M16 14 V28 H28" fill="none" stroke="#ffffff" stroke-width="3.6"
        stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="28" cy="14" r="2.6" fill="#4cc2a8"/>
  <text x="50" y="29" font-family="Inter, 'Segoe UI', Arial, sans-serif" font-size="21"
        font-weight="800" letter-spacing="3.2" fill="#16284f">__APP__</text>
</svg>"""
LOGO = Path(__file__).parent / "assets" / "logo.svg"
if not LOGO.exists():
    LOGO.parent.mkdir(exist_ok=True)
    LOGO.write_text(LOGO_SVG.replace("__APP__", APP_NAME), encoding="utf-8")
st.logo(str(LOGO), size="large")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* Inter for text and headings (not applied everywhere, so icons keep working) */
h1, h2, h3, h4, [data-testid="stMarkdownContainer"] {font-family: 'Inter', 'Segoe UI', sans-serif;}

/* Fixes the clipped top: leave room for Streamlit's fixed header */
.block-container {padding-top: 4.5rem; max-width: 1100px;}
[data-testid="stToolbar"] {visibility: hidden;}

h1 {font-size: 1.9rem !important; font-weight: 700 !important;
    letter-spacing: -0.01em; padding: 0.1rem 0 1rem 0 !important;}
h3 {font-size: 1.15rem !important; font-weight: 600 !important;}

.eyebrow {font-size: .72rem; font-weight: 700; letter-spacing: .14em;
          text-transform: uppercase; color: #2f5da8; margin: 0 0 .2rem 0;}
.status {font-size: .82rem; color: #5b6b85; margin-top: .5rem;}

[data-testid="stMetric"] {background: #fff; border: 1px solid #e3e8ef;
          border-radius: 12px; padding: 16px 18px;}
[data-testid="stMetricLabel"] {color: #5b6b85;}
[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 12px;}
[data-testid="stSidebar"] {border-right: 1px solid #e3e8ef;}
.stButton > button {border-radius: 8px; font-weight: 600;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def eyebrow(text):
    """Small blue label above a title, like 'PAYMENT ACTIVITY'."""
    st.markdown(f'<p class="eyebrow">{text}</p>', unsafe_allow_html=True)


# ======================================================================
# 1. Helpers that talk to the backend
# ======================================================================
def api_get(path, params=None):
    try:
        r = requests.get(f"{API}{path}", params=params, timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None               # backend down -> the screen shows a message


def api_post(path, payload=None):
    try:
        r = requests.post(f"{API}{path}", json=payload, timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


# ======================================================================
# 2. Who you can pay, and the things remembered between reruns
# ======================================================================
NEW_PAYEE = "Someone new (enter UPI ID)"
# name -> (payment type for the model, is this payee already known to the customer?)
PAYEES = {
    "Rahul Kumar (saved contact)": ("TRANSFER", True),
    "Priya Sharma (saved contact)": ("TRANSFER", True),
    "Metro Grocery (merchant)": ("PAYMENT", True),
    NEW_PAYEE: ("TRANSFER", False),
}

DEFAULTS = {
    "history": [],                 # the customer's own payments
    "feed": [],                    # the bank's live feed
    "outcome": None,               # message shown after a payment
    "pay_to": "Rahul Kumar (saved contact)",
    "pay_upi": "",
    "pay_amount": 500.0,
    "pay_request": False,
    "acct_balance": 50000.0,       # the customer's account (set in Demo controls)
    "acct_usual": 1000.0,          # their typical payment size
}
for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)


def colour_rows(row):
    """Light red background for RISKY rows, light green for SAFE."""
    bg = "#ffd9d9" if row["Verdict"] == "RISKY" else "#dcf5e3"
    return [f"background-color: {bg}; color: #111"] * len(row)


def history_table(rows, limit=None):
    shown = rows[:limit] if limit else rows
    df = pd.DataFrame(shown).drop(columns=["id"])      # id is internal only
    st.dataframe(df.style.apply(colour_rows, axis=1), hide_index=True)


def set_status(entry_id, status):
    for h in st.session_state["history"]:
        if h["id"] == entry_id:
            h["Status"] = status


# ======================================================================
# 3. Payment check and warning popup
# ======================================================================
@st.dialog("Suspicious payment detected")
def warning_dialog(entry_id, payee, amount, result):
    st.error(f"This payment of ₹{amount:,.2f} to {payee} has a "
             f"{result['risk_score'] * 100:.0f}% risk of being fraud.")
    st.caption(f"Flagged by: {result['flagged_by']}")
    st.markdown("**Why it looks suspicious**")
    for reason in result["reasons"]:
        st.markdown(f"- {reason}")

    left, right = st.columns(2)
    if left.button("Cancel payment", type="primary"):
        set_status(entry_id, "Cancelled by you")
        st.session_state["outcome"] = ("success",
            "Payment cancelled. You may have just avoided a scam.")
        st.rerun()                # closes the popup and refreshes the page
    if right.button("Pay anyway"):
        set_status(entry_id, "Sent despite warning")
        st.session_state["outcome"] = ("warning",
            f"₹{amount:,.2f} was sent to {payee} despite the warning.")
        st.rerun()


def check_and_pay(payee, payload):
    """Score the payment with the API. SAFE -> sent. RISKY -> warning popup."""
    st.session_state["outcome"] = None
    result = api_post("/score", payload)
    if result is None:
        st.error("Could not reach the fraud engine. Is the backend running?")
        return

    risky = result["verdict"] == "RISKY"
    entry_id = uuid.uuid4().hex[:8]
    st.session_state["history"].insert(0, {            # newest first
        "id": entry_id,
        "Time": datetime.now().strftime("%H:%M:%S"),
        "Payee": payee,
        "Type": payload["type"],
        "Amount (₹)": round(payload["amount"], 2),
        "Risk %": round(result["risk_score"] * 100),
        "Verdict": result["verdict"],
        "Status": "Awaiting your decision" if risky else "Sent",
        "Flagged by": result["flagged_by"],
    })

    if risky:
        warning_dialog(entry_id, payee, payload["amount"], result)
    else:
        st.session_state["outcome"] = ("success",
            f"₹{payload['amount']:,.2f} sent to {payee}. "
            f"Risk {result['risk_score'] * 100:.0f}%, looks safe.")


def run_dataset_payment(fraud):
    """Demo control: score a real unseen payment from the dataset (ML model only)."""
    data = api_get("/sample", params={"fraud": "true" if fraud else "false"})
    if data is None:
        st.error("Could not reach the fraud engine.")
        return
    data.pop("actual_label")               # remove the answer key
    check_and_pay(random.choice(["Rahul Kumar", "Priya Sharma", "Amit Verma"]), data)


def scenario_normal():
    """Callback: fill the form with an everyday payment."""
    st.session_state.update({"pay_to": "Rahul Kumar (saved contact)",
                             "pay_upi": "", "pay_amount": 500.0, "pay_request": False})


def scenario_scam():
    """Callback: fill the form with a fake collect-request scam."""
    st.session_state.update({"pay_to": NEW_PAYEE, "pay_upi": "rewards.helpdesk@upi",
                             "pay_amount": 25000.0, "pay_request": True})


# ======================================================================
# 4. Pages
# ======================================================================
def show_home():
    eyebrow("Personal payment protection")
    st.title("Your dashboard")
    st.write("Here's an overview of your payment activity.")

    history = st.session_state["history"]
    total = len(history)
    recent_total = sum(h["Amount (₹)"] for h in history[:10])
    safe = sum(1 for h in history if h["Verdict"] == "SAFE")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total transactions", total)
    c2.metric("Recent payments total", f"₹{recent_total:,.2f}")
    c3.metric("Safe transactions", safe)
    c4.metric("Flagged transactions", total - safe)

    left, right = st.columns([2, 1])
    with left:
        with st.container(border=True):
            eyebrow("Payment activity")
            st.subheader("Recent transactions")
            if history:
                history_table(history, limit=8)
            else:
                st.info("No transactions yet. Your payment activity will "
                        "appear here once you start making payments.")
    with right:
        with st.container(border=True):
            eyebrow("Before you pay")
            st.subheader("Check a payment")
            st.write(f"Not sure whether a payment request is genuine? "
                     f"{APP_NAME} checks the risk before the money leaves your account.")
            if st.button("Make a payment", type="primary"):
                st.switch_page(safety_page)


def show_safety_check():
    eyebrow("Before you pay")
    st.title("Make a payment")

    balance = st.session_state["acct_balance"]
    usual = st.session_state["acct_usual"]

    form_col, info_col = st.columns([3, 2], gap="large")

    with form_col:
        with st.container(border=True):
            choice = st.selectbox("Pay to", list(PAYEES), key="pay_to")
            tx_type, payee_known = PAYEES[choice]

            if choice == NEW_PAYEE:
                payee_name = st.text_input("UPI ID", placeholder="name@bank",
                                           key="pay_upi").strip()
            else:
                payee_name = choice.split(" (")[0]      # "Rahul Kumar"

            amount = st.number_input("Amount (₹)", min_value=1.0, step=100.0,
                                     key="pay_amount")
            is_request = st.checkbox(
                "I'm paying because someone sent me a payment request",
                key="pay_request")

            if st.button("Pay now", type="primary"):
                if choice == NEW_PAYEE and not payee_name:
                    st.error("Enter the UPI ID to continue.")
                elif amount > balance:
                    st.error("Insufficient balance.")
                else:
                    check_and_pay(payee_name, {
                        "amount": amount,
                        "type": tx_type,
                        "oldbalanceOrg": balance,
                        "newbalanceOrig": balance - amount,
                        "oldbalanceDest": 0.0,
                        # merchants keep no balance in the dataset; people do
                        "newbalanceDest": 0.0 if tx_type == "PAYMENT" else amount,
                        "hour": datetime.now().hour,    # the system fills in the time
                        # context the safety rules use (a real app knows these itself)
                        "payee_known": payee_known,
                        "is_collect_request": is_request,
                        "usual_amount": usual,
                    })

        outcome = st.session_state.get("outcome")
        if outcome:
            kind, text = outcome
            (st.success if kind == "success" else st.warning)(text)

    with info_col:
        with st.container(border=True):
            eyebrow("From account")
            st.metric("Available balance", f"₹{balance:,.2f}")
            st.caption("Savings account ending 4821. Every payment is checked "
                       "for fraud before it is sent.")

    with st.expander("Demo controls (for judges)"):
        st.caption("Shortcuts for the live demo. A real customer would not see this.")
        d1, d2, d3 = st.columns(3)
        d1.button("Fill: everyday payment", on_click=scenario_normal)
        d2.button("Fill: fake collect-request scam", on_click=scenario_scam)
        if d3.button("Run a real dataset scam"):
            run_dataset_payment(fraud=True)
        a1, a2 = st.columns(2)
        a1.number_input("Account balance (₹)", min_value=0.0, step=1000.0,
                        key="acct_balance")
        a2.number_input("Usual payment size (₹)", min_value=1.0, step=100.0,
                        key="acct_usual")


def show_transactions():
    eyebrow("Payment activity")
    st.title("My transactions")
    history = st.session_state["history"]
    if history:
        history_table(history)
        if st.button("Clear history"):
            st.session_state["history"] = []
            st.rerun()
    else:
        st.info("No transactions yet. Make a payment to see it here.")


def show_insights():
    eyebrow("Your payment safety")
    st.title("Understanding your activity")
    st.write(f"{APP_NAME} looks at transaction patterns and risk indicators to "
             f"help you spot potentially suspicious payments.")
    history = st.session_state["history"]
    if not history:
        st.info("Insights appear after you make a few payments.")
        return
    safe = sum(1 for h in history if h["Verdict"] == "SAFE")
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Safe vs flagged")
            st.bar_chart(pd.Series({"Safe": safe, "Flagged": len(history) - safe}))
    with right:
        with st.container(border=True):
            st.subheader("Risk % over time")
            st.line_chart(pd.Series([h["Risk %"] for h in reversed(history)]))


# ---- Bank View: the live feed (the "stream simulator") ----
@st.fragment(run_every=1)          # re-runs ONLY this function every second
def live_feed():
    if st.session_state.get("live", True):
        item = api_get("/next")    # next unseen payment, already scored
        if item is not None:
            p, r = item["payment"], item["result"]
            st.session_state["feed"].insert(0, {
                "Time": datetime.now().strftime("%H:%M:%S"),
                "Type": p["type"],
                "Amount (₹)": round(p["amount"], 2),
                "Risk %": round(r["risk_score"] * 100),
                "Verdict": r["verdict"],
                "Why flagged": " • ".join(r["reasons"]),
                "Really fraud? (demo)": item["actual_label"],
            })
            del st.session_state["feed"][30:]       # keep the last 30 rows

    stats = api_get("/stats")
    if stats:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Payments scanned", stats["scanned"])
        m2.metric("Flagged as risky", stats["flagged"])
        m3.metric("Amount flagged", f"₹{stats['amount_flagged']:,.0f}")
        rate = stats["flagged"] / stats["scanned"] * 100 if stats["scanned"] else 0
        m4.metric("Flag rate", f"{rate:.1f}%")
    else:
        st.error("Backend not reachable.")

    feed = st.session_state["feed"]
    flagged = [row for row in feed if row["Verdict"] == "RISKY"]
    if flagged:
        a = flagged[0]
        st.error(f"**Latest alert** ({a['Time']}): ₹{a['Amount (₹)']:,.0f} "
                 f"{a['Type']}, risk {a['Risk %']}%\n\n{a['Why flagged']}")

    with st.container(border=True):
        eyebrow("Live payments")
        if feed:
            st.dataframe(pd.DataFrame(feed).style.apply(colour_rows, axis=1),
                         hide_index=True)
        else:
            st.info("Waiting for payments...")


def show_bank_view():
    eyebrow("Fraud operations")
    st.title("Bank fraud dashboard")
    st.caption("Every payment is scored in real time. Red rows were flagged as risky.")
    c1, c2 = st.columns(2)
    c1.toggle("Live feed", value=True, key="live")
    if c2.button("Reset counters"):
        api_post("/reset")
        st.session_state["feed"] = []
        st.rerun()
    live_feed()


# ======================================================================
# 5. Navigation (the sidebar menu)
# ======================================================================
home_page = st.Page(show_home, title="Home", icon=":material/home:",
                    default=True)
safety_page = st.Page(show_safety_check, title="Safety Check",
                      icon=":material/shield:", url_path="safety-check")
tx_page = st.Page(show_transactions, title="My Transactions",
                  icon=":material/receipt_long:", url_path="transactions")
insights_page = st.Page(show_insights, title="My Insights",
                        icon=":material/bar_chart:", url_path="insights")
bank_page = st.Page(show_bank_view, title="Bank View",
                    icon=":material/account_balance:", url_path="bank-view")

pg = st.navigation({"MENU": [home_page, safety_page, tx_page, insights_page],
                    "FOR BANKS": [bank_page]})

online = api_get("/health") is not None
dot = "#1a9d5c" if online else "#d93636"
st.sidebar.markdown(
    f'<p class="status"><span style="color:{dot}">●</span> '
    f'Fraud engine {"online" if online else "offline"}</p>',
    unsafe_allow_html=True)
if not online:
    st.sidebar.caption("Start it with: uvicorn main:app --reload")

pg.run()