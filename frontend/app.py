# frontend/app.py  (v4: login system + indigo theme)
import base64
import os
import random
import uuid
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

import auth                      # our login module (frontend/auth.py)

# ======================================================================
# Settings. Override with environment variables when you deploy.
# ======================================================================
API = os.environ.get("API_URL", "http://localhost:8000")    # where the FastAPI backend runs
DEMO_MODE = os.environ.get("DEMO_MODE", "1") == "1"         # "0" hides everything meant for judges
FEED_SECONDS = int(os.environ.get("FEED_SECONDS", "1"))     # how often the bank feed refreshes
APP_NAME = "LOSAGA"

st.set_page_config(page_title=f"{APP_NAME} | Payment Protection",
                   page_icon=":material/shield:", layout="wide")


@st.cache_resource               # runs once per server start, not on every click
def setup_database():
    auth.init_db()
    if DEMO_MODE:
        auth.seed_demo_users()
    return True


setup_database()

# ======================================================================
# 0. Logo and styling
# ======================================================================
LOGO_MARK_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 72" width="64" height="72">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#7aa2ff"/>
      <stop offset="1" stop-color="#3a1fd1"/>
    </linearGradient>
  </defs>
  <path d="M32 3 L57 12 V34 C57 51 46 62 32 69 C18 62 7 51 7 34 V12 Z" fill="url(#g)"/>
  <path d="M32 3 L57 12 V34 C57 51 46 62 32 69 C18 62 7 51 7 34 V12 Z" fill="none"
        stroke="#ffffff" stroke-opacity=".35" stroke-width="1.5"/>
  <path d="M20 36 L29 45 L45 26" fill="none" stroke="#ffffff" stroke-width="5.5"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""


def logo_mark(width=56):
    """The shield logo as an <img> tag (base64, so no extra files are needed)."""
    b64 = base64.b64encode(LOGO_MARK_SVG.encode("utf-8")).decode("ascii")
    return f'<img src="data:image/svg+xml;base64,{b64}" width="{width}" alt="{APP_NAME} logo">'


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

/* Inter for text and headings (not applied everywhere, so icons keep working) */
h1, h2, h3, h4, [data-testid="stMarkdownContainer"] {font-family: 'Inter', 'Segoe UI', sans-serif;}

/* Leave room for Streamlit's fixed header; hide the toolbar and footer */
.block-container {padding-top: 4.5rem; max-width: 1100px;}
[data-testid="stToolbar"] {visibility: hidden;}
#MainMenu, footer {visibility: hidden;}

h1 {font-size: 1.9rem !important; font-weight: 700 !important;
    letter-spacing: -0.01em; padding: 0.1rem 0 1rem 0 !important;}
h3 {font-size: 1.15rem !important; font-weight: 600 !important;}

.eyebrow {font-size: .72rem; font-weight: 700; letter-spacing: .14em;
          text-transform: uppercase; color: #1c0099; margin: 0 0 .2rem 0;}

/* Metric cards */
[data-testid="stMetric"] {background: #fff; border: 1px solid #cdd6f5;
          border-radius: 12px; padding: 16px 18px;}
[data-testid="stMetricLabel"] {color: #4a4a78;}

/* Pill buttons, like the mockup */
.stButton > button, [data-testid="stFormSubmitButton"] > button {
          border-radius: 999px; padding: .5rem 1.6rem; font-weight: 600;}
.stButton > button p, [data-testid="stFormSubmitButton"] > button p {
          text-transform: uppercase; letter-spacing: .06em; font-size: .85rem;}

/* Dark indigo sidebar with white, bold, uppercase menu */
[data-testid="stSidebar"] {background: #190066; border-right: none;}
[data-testid="stSidebar"] * {color: #ffffff;}
.brand-title {font-size: 1.7rem; font-weight: 800; letter-spacing: .08em; margin: .2rem 0 .6rem 0;}
.nav-label {font-size: .78rem; font-weight: 700; letter-spacing: .16em; opacity: .65;
            margin: 1.6rem 0 .2rem 0;}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] {
          text-transform: uppercase; font-weight: 700; letter-spacing: .04em;
          border-radius: 8px;}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"][aria-current="page"] {
          background: rgba(255,255,255,.16);}
[data-testid="stSidebar"] .stButton > button {background: transparent; border: 1.5px solid #ffffff;}
.who {font-weight: 600; margin: 0; line-height: 1.3;}
.who span {font-weight: 400; opacity: .7; font-size: .85rem;}
.status {font-size: .82rem; opacity: .85; margin-top: .6rem;}

/* Login screen */
.login-brand {text-align: center; margin-bottom: 1.5rem;}
.login-title {font-size: 2.3rem; font-weight: 800; letter-spacing: .1em; color: #190066;}
.login-tag {color: #4a4a78; margin-top: .8rem;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def eyebrow(text):
    """Small label above a title, like 'PAYMENT ACTIVITY'."""
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
NEW_PAYEE = "Someone new (enter UPI ID)"
# name -> (payment type for the model, is this payee already known to the customer?)
PAYEES = {
    "Rahul Kumar (saved contact)": ("TRANSFER", True),
    "Priya Sharma (saved contact)": ("TRANSFER", True),
    "Metro Grocery (merchant)": ("PAYMENT", True),
    NEW_PAYEE: ("TRANSFER", False),
}

DEFAULTS = {
    "user": None,                  # who is logged in (None = nobody)
    "history": [],                 # this customer's payments
    "feed": [],                    # the bank's live feed
    "outcome": None,               # message shown after a payment
    "pay_to": "Rahul Kumar (saved contact)",
    "pay_upi": "",
    "pay_amount": 500.0,
    "pay_request": False,
    "acct_balance": 50000.0,       # the customer's account
    "acct_usual": 1000.0,          # their typical payment size
}
for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)


def current_user():
    return st.session_state["user"]


def sign_in(user):
    """Remember the user, load their saved payments, and refresh the page."""
    st.session_state["user"] = user
    st.session_state["history"] = auth.list_payments(user["email"])
    st.session_state["feed"] = []
    st.session_state["outcome"] = None
    st.rerun()


def sign_out():
    """Button callback: forget everything about this session."""
    for key in DEFAULTS:
        st.session_state.pop(key, None)     # DEFAULTS are re-created on the next run


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
    auth.update_status(entry_id, status)               # also save it in the database


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
    entry = {
        "id": uuid.uuid4().hex[:8],
        "When": datetime.now().strftime("%d %b, %H:%M"),
        "Payee": payee,
        "Type": payload["type"],
        "Amount (₹)": round(payload["amount"], 2),
        "Risk %": round(result["risk_score"] * 100),
        "Verdict": result["verdict"],
        "Status": "Awaiting your decision" if risky else "Sent",
        "Flagged by": result["flagged_by"],
    }
    st.session_state["history"].insert(0, entry)             # newest first
    auth.add_payment(current_user()["email"], entry)         # save it for next login

    if risky:
        warning_dialog(entry["id"], payee, payload["amount"], result)
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
def show_login():
    # No sidebar on the login screen
    st.markdown("<style>[data-testid='stSidebar'], "
                "[data-testid='stSidebarCollapsedControl'] {display: none;}</style>",
                unsafe_allow_html=True)

    _, middle, _ = st.columns([1, 1.4, 1])
    with middle:
        st.markdown(
            f'<div class="login-brand">'
            f'<div class="login-title">{APP_NAME}</div>'
            f'<div>{logo_mark(72)}</div>'
            f'<p class="login-tag">Payment protection that checks every payment '
            f'before it leaves your account.</p></div>',
            unsafe_allow_html=True)

        tab_in, tab_up = st.tabs(["Sign in", "Create account"])

        with tab_in:
            with st.form("signin_form"):          # a form lets Enter submit it
                email = st.text_input("Email")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign in", type="primary")
            if submitted:
                user = auth.verify_user(email, password)
                if user:
                    sign_in(user)
                else:
                    st.error("Incorrect email or password.")

        with tab_up:
            with st.form("signup_form"):
                name = st.text_input("Full name")
                new_email = st.text_input("Email", key="signup_email")
                pw1 = st.text_input("Password (6+ characters)", type="password",
                                    key="signup_pw1")
                pw2 = st.text_input("Confirm password", type="password",
                                    key="signup_pw2")
                created = st.form_submit_button("Create account", type="primary")
            if created:
                if pw1 != pw2:
                    st.error("Passwords do not match.")
                else:
                    ok, message = auth.create_user(new_email, name, pw1)
                    if ok:
                        sign_in(auth.verify_user(new_email, pw1))
                    else:
                        st.error(message)

        if DEMO_MODE:
            with st.expander("Demo accounts (for judges)"):
                st.caption("Both accounts use the password: demo123")
                st.markdown("- **Customer:** customer@losaga.demo  \n"
                            "- **Bank officer:** bank@losaga.demo")
                b1, b2 = st.columns(2)
                if b1.button("Customer"):
                    sign_in(auth.verify_user("customer@losaga.demo", "demo123"))
                if b2.button("Bank officer"):
                    sign_in(auth.verify_user("bank@losaga.demo", "demo123"))


def show_home():
    user = current_user()
    eyebrow("Personal payment protection")
    st.title("Your dashboard")
    st.subheader(f"Hello, {user['name'].split()[0]}.")
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

    # Only shown when DEMO_MODE=1. Set DEMO_MODE=0 to hide it for a real launch.
    if DEMO_MODE:
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
            auth.clear_payments(current_user()["email"])
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
@st.fragment(run_every=FEED_SECONDS)    # re-runs ONLY this function every few seconds
def live_feed():
    if st.session_state.get("live", True):
        item = api_get("/next")    # next unseen payment, already scored
        if item is not None:
            p, r = item["payment"], item["result"]
            row = {
                "Time": datetime.now().strftime("%H:%M:%S"),
                "Type": p["type"],
                "Amount (₹)": round(p["amount"], 2),
                "Risk %": round(r["risk_score"] * 100),
                "Verdict": r["verdict"],
                "Why flagged": " • ".join(r["reasons"]),
            }
            if DEMO_MODE:                       # the answer key is a demo-only column
                row["Really fraud? (demo)"] = item["actual_label"]
            st.session_state["feed"].insert(0, row)
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
# 5. Navigation: who sees which pages
# ======================================================================
login_page = st.Page(show_login, title="Sign in", url_path="login", default=True)
home_page = st.Page(show_home, title="Home", icon=":material/home:", default=True)
safety_page = st.Page(show_safety_check, title="Safety Check",
                      icon=":material/shield:", url_path="safety-check")
tx_page = st.Page(show_transactions, title="My Transactions",
                  icon=":material/receipt_long:", url_path="transactions")
insights_page = st.Page(show_insights, title="My Insights",
                        icon=":material/bar_chart:", url_path="insights")
bank_page = st.Page(show_bank_view, title="Bank View",
                    icon=":material/account_balance:", url_path="bank-view",
                    default=True)


def render_sidebar(user, groups):
    """The custom sidebar: brand, menu, who is signed in, log out."""
    sb = st.sidebar
    sb.markdown(f'<div class="brand-title">{APP_NAME}</div>{logo_mark(46)}',
                unsafe_allow_html=True)
    for label, pages in groups:
        sb.markdown(f'<p class="nav-label">{label}</p>', unsafe_allow_html=True)
        for page in pages:
            sb.page_link(page)                      # a link to that page

    role = "Bank officer" if user["role"] == "bank" else "Customer"
    sb.markdown("<br>", unsafe_allow_html=True)
    sb.markdown(f'<p class="who">{user["name"]}<br><span>{role}</span></p>',
                unsafe_allow_html=True)
    sb.button("Log out", on_click=sign_out)

    online = api_get("/health") is not None
    dot = "#4cd98a" if online else "#ff6b6b"
    sb.markdown(f'<p class="status"><span style="color:{dot}">●</span> '
                f'Fraud engine {"online" if online else "offline"}</p>',
                unsafe_allow_html=True)


user = current_user()
if user is None:
    pg = st.navigation([login_page], position="hidden")
else:
    if user["role"] == "bank":
        groups = [("FOR BANKS", [bank_page])]
    else:
        groups = [("MENU", [home_page, safety_page, tx_page, insights_page])]
    pg = st.navigation([p for _, pages in groups for p in pages], position="hidden")
    render_sidebar(user, groups)

pg.run()