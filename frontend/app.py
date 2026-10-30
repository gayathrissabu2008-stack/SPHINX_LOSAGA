# frontend/app.py  (polished version)
import random
import uuid
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

API = "http://localhost:8000"     # where your FastAPI backend runs
APP_NAME = "LOSAGA"               # change to your product name

st.set_page_config(page_title=f"{APP_NAME} | Payment Protection",
                   page_icon="🛡️", layout="wide")

PAYEES = ["Rahul Kumar", "Priya Sharma", "Amit Verma", "Neha Singh",
          "Karan Mehta", "Sneha Iyer"]

# ======================================================================
# 0. Styling (CSS injected into the page)
# ======================================================================
CSS = """
<style>
#MainMenu, footer {visibility: hidden;}
.block-container {padding-top: 2rem; max-width: 1200px;}
.eyebrow {font-size: .72rem; font-weight: 700; letter-spacing: .14em;
          text-transform: uppercase; color: #2f5da8; margin: 0;}
[data-testid="stMetric"] {background: #fff; border: 1px solid #e3e8ef;
          border-radius: 12px; padding: 16px 18px;}
[data-testid="stSidebar"] {border-right: 1px solid #e3e8ef;}
[data-testid="stSidebarNav"]::before {content: "🛡️ __APP__"; display: block;
          font-weight: 800; font-size: 1.3rem; letter-spacing: .08em;
          padding: 1rem 1rem .5rem;}
</style>
""".replace("__APP__", APP_NAME)
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
# 2. Things remembered between reruns
# ======================================================================
st.session_state.setdefault("history", [])    # the customer's own payments
st.session_state.setdefault("feed", [])       # the bank's live feed
st.session_state.setdefault("outcome", None)  # message shown after a payment


def colour_rows(row):
    """Red background for RISKY rows, green for SAFE."""
    bg = "#ffd9d9" if row["Verdict"] == "RISKY" else "#dcf5e3"
    return [f"background-color: {bg}; color: #111"] * len(row)


def history_table(rows, limit=None):
    shown = rows[:limit] if limit else rows
    df = pd.DataFrame(shown).drop(columns=["id"])      # id is internal only
    st.dataframe(df.style.apply(colour_rows, axis=1), hide_index=True)


def set_status(entry_id, status):
    """Update a payment's status in history (used by the popup buttons)."""
    for h in st.session_state["history"]:
        if h["id"] == entry_id:
            h["Status"] = status


# ======================================================================
# 3. Payment check + warning popup
# ======================================================================
@st.dialog("⚠️ Suspicious payment detected")
def warning_dialog(entry_id, payee, amount, result):
    st.error(f"This payment of ₹{amount:,.2f} to **{payee}** has a "
             f"**{result['risk_score'] * 100:.0f}% risk** of being fraud.")
    st.caption(f"Flagged by: {result['flagged_by']}")
    st.markdown("**Why it looks suspicious:**")
    for reason in result["reasons"]:
        st.markdown(f"- {reason}")

    left, right = st.columns(2)
    if left.button("🛑 Cancel payment", type="primary"):
        set_status(entry_id, "Cancelled by you")
        st.session_state["outcome"] = ("success",
            "🛡️ Payment cancelled. You may have just avoided a scam.")
        st.rerun()                # closes the popup and refreshes the page
    if right.button("Pay anyway"):
        set_status(entry_id, "Sent despite warning")
        st.session_state["outcome"] = ("warning",
            f"⚠️ ₹{amount:,.2f} sent to {payee} despite the warning.")
        st.rerun()


def check_and_pay(payee, payload):
    """Score the payment with the API. SAFE -> sent. RISKY -> warning popup."""
    st.session_state["outcome"] = None
    result = api_post("/score", payload)
    if result is None:
        st.error("Could not reach the fraud API. Is the backend running?")
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
            f"✅ ₹{payload['amount']:,.2f} sent to {payee}. "
            f"Risk {result['risk_score'] * 100:.0f}%, looks safe.")


def load_sample(fraud):
    """Button callback: fetch a real unseen payment from GET /sample."""
    data = api_get("/sample", params={"fraud": "true" if fraud else "false"})
    if data is None:
        st.session_state["sample"] = None
        return
    label = data.pop("actual_label")       # remove the answer key
    st.session_state["sample"] = {"payee": random.choice(PAYEES),
                                  "payload": data, "actual_label": label}
    st.session_state["outcome"] = None


def scenario_scam():
    """Button callback: fill tab 2 with a fake collect-request scam."""
    st.session_state.update({"m_payee": "Rewards Support", "m_amount": 25000.0,
        "m_type": "TRANSFER", "m_balance": 26000.0, "m_usual": 1000.0,
        "m_known": False, "m_collect": True})


def scenario_normal():
    """Button callback: fill tab 2 with an everyday payment."""
    st.session_state.update({"m_payee": "Rahul Kumar", "m_amount": 500.0,
        "m_type": "TRANSFER", "m_balance": 50000.0, "m_usual": 1000.0,
        "m_known": True, "m_collect": False})


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
        with st.container(border=True):                # a "card"
            eyebrow("Payment activity")
            st.subheader("Recent transactions")
            if history:
                history_table(history, limit=8)
            else:
                st.info("No transactions yet. Your payment activity will "
                        "appear here once you start checking payments.")
    with right:
        with st.container(border=True):
            eyebrow("Before you pay")
            st.subheader("Check a payment")
            st.write(f"Not sure whether a payment request is genuine? "
                     f"{APP_NAME} will help assess its risk.")
            if st.button("Start safety check", type="primary"):
                st.switch_page(safety_page)


def show_safety_check():
    eyebrow("Before you pay")
    st.title("Safety check")
    tab_demo, tab_manual = st.tabs(["🎲 Demo payment (real sample)",
                                    "✍️ My own payment"])

    # ---- Tab 1: a real payment from the model's unseen test data ----
    with tab_demo:
        st.write("Load a real payment the model has never seen, then press Pay.")
        b1, b2 = st.columns(2)
        b1.button("🎲 Load sample payment", on_click=load_sample, args=(False,))
        b2.button("🚨 Load sample scam", on_click=load_sample, args=(True,))

        sample = st.session_state.get("sample")
        if sample:
            p = sample["payload"]
            with st.container(border=True):
                st.markdown(f"**To:** {sample['payee']}  \n"
                            f"**Amount:** ₹{p['amount']:,.2f}  \n"
                            f"**Type:** {p['type']}")
                with st.expander("Account details (filled in by the bank system)"):
                    st.json(p)
                    st.caption(f"Answer key (demo only): really {sample['actual_label']}")
                if st.button("💸 Pay now", key="pay_demo", type="primary"):
                    check_and_pay(sample["payee"], p)

    # ---- Tab 2: your own payment, ML model + safety rules ----
    with tab_manual:
        # defaults, set once (widgets below read them through their keys)
        for key, default in {"m_payee": "Rahul Kumar", "m_amount": 500.0,
                             "m_type": "TRANSFER", "m_balance": 50000.0,
                             "m_usual": 1000.0, "m_known": True,
                             "m_collect": False}.items():
            st.session_state.setdefault(key, default)

        st.write("Type a payment, or try a ready-made scenario:")
        s1, s2 = st.columns(2)
        s1.button("✅ Everyday payment", on_click=scenario_normal)
        s2.button("🚨 Fake collect-request scam", on_click=scenario_scam)

        payee = st.text_input("Pay to", key="m_payee")
        c1, c2 = st.columns(2)
        amount = c1.number_input("Amount (₹)", min_value=1.0, step=100.0, key="m_amount")
        tx_type = c2.selectbox("Payment type", ["TRANSFER", "PAYMENT"], key="m_type")
        balance = c1.number_input("Your account balance (₹)", min_value=0.0,
                                  step=1000.0, key="m_balance")
        usual = c2.number_input("Your usual payment size (₹)", min_value=1.0,
                                step=100.0, key="m_usual")
        known = st.checkbox("I've paid this person before (saved contact)", key="m_known")
        collect = st.checkbox("This is a 'request money' (collect) approval", key="m_collect")

        if st.button("💸 Pay now", key="pay_manual", type="primary"):
            if amount > balance:
                st.error("Insufficient balance.")
            else:
                check_and_pay(payee, {
                    "amount": amount,
                    "type": tx_type,
                    "oldbalanceOrg": balance,
                    "newbalanceOrig": balance - amount,
                    "oldbalanceDest": 0.0,
                    "newbalanceDest": 0.0 if tx_type == "PAYMENT" else amount,
                    "hour": datetime.now().hour,
                    # context the safety rules use (a real app knows these itself)
                    "payee_known": known,
                    "is_collect_request": collect,
                    "usual_amount": usual,
                })

    outcome = st.session_state.get("outcome")
    if outcome:
        kind, text = outcome
        st.divider()
        (st.success if kind == "success" else st.warning)(text)


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
        st.info("No transactions yet. Run a safety check first.")


def show_insights():
    eyebrow("Your payment safety")
    st.title("Understanding your activity")
    st.write(f"{APP_NAME} uses transaction patterns and risk indicators to help "
             f"you spot potentially suspicious payments.")
    history = st.session_state["history"]
    if not history:
        st.info("Insights appear after you check a few payments.")
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
        item = api_get("/next")    # GET /next: next unseen payment, already scored
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
        st.error(f"🚨 **Latest alert** ({a['Time']}): ₹{a['Amount (₹)']:,.0f} "
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
    st.caption("Every payment is scored in real time. Red = flagged as risky.")
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
home_page = st.Page(show_home, title="Home", icon="🏠", default=True)
safety_page = st.Page(show_safety_check, title="Safety Check", icon="🛡️")
tx_page = st.Page(show_transactions, title="My Transactions", icon="📜")
insights_page = st.Page(show_insights, title="My Insights", icon="📊")
bank_page = st.Page(show_bank_view, title="Bank View", icon="🏦")

pg = st.navigation({"MENU": [home_page, safety_page, tx_page, insights_page],
                    "FOR BANKS": [bank_page]})

if api_get("/health") is None:
    st.sidebar.error("Backend not reachable.\n\nStart it with:\n`uvicorn main:app --reload`")
else:
    st.sidebar.success("Backend connected")

pg.run()