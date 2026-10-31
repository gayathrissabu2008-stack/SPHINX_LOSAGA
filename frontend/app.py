# frontend/app.py  (v10: login + theme + safety tips + helpline + Scan QR + balance + IST
#                   + payment password + light blue cards)
import base64
import io
import os
import random
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote

import numpy as np
import pandas as pd
import requests
import streamlit as st
from PIL import Image, ImageOps

import auth                      # our login module (frontend/auth.py)

try:                             # main QR decoder (pip install zxing-cpp)
    import zxingcpp
except ImportError:
    zxingcpp = None
try:                             # backup decoder, only used if OpenCV is installed
    import cv2
except ImportError:
    cv2 = None

# ======================================================================
# Settings. Override with environment variables when you deploy.
# ======================================================================
API = os.environ.get("API_URL", "http://localhost:8000")    # where the FastAPI backend runs
DEMO_MODE = os.environ.get("DEMO_MODE", "1") == "1"         # "0" hides everything meant for judges
FEED_SECONDS = int(os.environ.get("FEED_SECONDS", "1"))     # how often the bank feed refreshes
TIP_SECONDS = int(os.environ.get("TIP_SECONDS", "3"))       # how often the safety tip changes
START_BALANCE = 50000.0                                     # balance every new session starts with
MAX_PASSWORD_ATTEMPTS = 3                                   # wrong passwords allowed per payment
LOCK_SECONDS = 60                                           # lock time after too many wrong passwords
APP_NAME = "LOSAGA"

# Indian Standard Time (UTC+5:30). The cloud server's clock is UTC, so we never use it directly.
IST = timezone(timedelta(hours=5, minutes=30), "IST")


def now_ist():
    """Current date and time in India, whatever timezone the server is in."""
    return datetime.now(IST)


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

/* Metric cards: same light blue as the helpline card */
[data-testid="stMetric"] {background: #f4f7fb; border: 1px solid #dfe5f2;
          border-radius: 12px; padding: 16px 18px;}
[data-testid="stMetricLabel"] {color: #4a4a78;}

/* Every bordered box with a key starting "card_" gets the light blue look */
[class*="st-key-card_"] {background: #f4f7fb !important; border-color: #dfe5f2 !important;
          border-radius: 16px !important;}
/* Keep input boxes white inside light blue cards so they stay visible */
[class*="st-key-card_"] [data-baseweb="input"],
[class*="st-key-card_"] [data-baseweb="base-input"],
[class*="st-key-card_"] [data-baseweb="select"] > div,
[class*="st-key-card_"] [data-testid="stFileUploaderDropzone"] {background: #ffffff !important;}

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

/* Safety tip card (yellow, compact, top right) and scam helpline card (light blue) */
.tip-card {background: #fbefd6; border-radius: 14px; padding: .9rem 1.2rem;
           min-height: 6rem; margin: 0 0 1.2rem 0;}
.help-card {background: #f4f7fb; border: 1px solid #dfe5f2; border-radius: 16px;
            padding: 1.4rem 1.7rem; margin: 1rem 0 0 0;}
.card-label {font-size: .78rem; font-weight: 700; letter-spacing: .16em;
             text-transform: uppercase; color: #16284f; margin: 0 0 .7rem 0;}
.card-text {font-size: 1.05rem; line-height: 1.6; color: #1a1a40; margin: 0;}
.card-text a {color: #190066; font-weight: 600; text-decoration: underline;}
.tip-card .card-label {font-size: .7rem; margin-bottom: .35rem;}
.tip-card .card-text {font-size: .92rem; line-height: 1.45;}
.tip-text {animation: tipFade .5s ease-in;}
@keyframes tipFade {from {opacity: 0;} to {opacity: 1;}}
@media (prefers-reduced-motion: reduce) {.tip-text {animation: none;}}

/* Scan QR button: right edge of the home page header, light blue like the cards */
.st-key-home_scan {align-items: flex-end;}
.st-key-home_scan .stButton > button {background: #f4f7fb; border: 1px solid #dfe5f2;}
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

# Tips shown one at a time in the Safety Tip card (change every TIP_SECONDS)
SAFETY_TIPS = [
    "You never need your UPI PIN to receive money. Only to send it.",
    "Never share your UPI PIN or OTP with anyone, not even someone claiming to be from your bank.",
    "Scanning a QR code is for paying money, never for receiving it.",
    "Your bank will never ask you to install screen-sharing apps like AnyDesk or TeamViewer.",
    "Always check the payee's name on screen before you enter your UPI PIN.",
    "A prize, refund or cashback that asks you to pay first is a scam.",
    "Don't approve a payment request you weren't expecting. Decline it.",
    "Install payment apps only from the official Play Store or App Store.",
]

DEFAULTS = {
    "user": None,                  # who is logged in (None = nobody)
    "history": [],                 # this customer's payments
    "feed": [],                    # the bank's live feed
    "outcome": None,               # message shown after a payment
    "pay_to": "Rahul Kumar (saved contact)",
    "pay_upi": "",
    "pay_amount": 500.0,
    "pay_request": False,
    "balance": START_BALANCE,      # the customer's account (resets on reload / log out)
    "acct_usual": 1000.0,          # their typical payment size
    "tip_index": 0,                # which safety tip is showing
    "scan_prefill": None,          # QR result waiting to fill the payment form
    "scanned": None,               # last QR used on the payment form (shows the name)
    "pending_payment": None,       # payment waiting for the password
    "verified_payment": None,      # payment whose password was correct, ready to send
    "pw_attempts": 0,              # wrong passwords so far
    "pw_locked_until": 0.0,        # time.time() until which payments are locked
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


def deduct_balance(amount):
    """Take a sent payment out of the customer's balance (never below zero)."""
    st.session_state["balance"] = max(0.0, st.session_state["balance"] - amount)


def lock_seconds_left():
    """How many seconds payments stay locked after too many wrong passwords (0 = not locked)."""
    return max(0, int(round(st.session_state["pw_locked_until"] - time.time())))


# ======================================================================
# 2b. Safety tip and scam helpline cards
# ======================================================================
@st.fragment(run_every=TIP_SECONDS)     # re-runs ONLY this card every few seconds
def safety_tip_card():
    """Shows one tip, then moves to the next one on the following refresh."""
    i = st.session_state["tip_index"] % len(SAFETY_TIPS)
    st.markdown(
        f'<div class="tip-card">'
        f'<p class="card-label">Safety tip</p>'
        f'<p class="card-text tip-text">{SAFETY_TIPS[i]}</p>'
        f'</div>',
        unsafe_allow_html=True)
    st.session_state["tip_index"] = i + 1


def scam_help_card():
    """Static card with the national cyber crime helpline."""
    st.markdown(
        '<div class="help-card">'
        '<p class="card-label">Lost money to a scam?</p>'
        '<p class="card-text">Call <b>1930</b> (National Cyber Crime Helpline) or report at '
        '<a href="https://cybercrime.gov.in" target="_blank" rel="noopener">cybercrime.gov.in</a>.'
        '</p></div>',
        unsafe_allow_html=True)


# ======================================================================
# 2c. QR scanning: reads UPI QRs from Google Pay, PhonePe, Paytm, BHIM and BharatQR
# ======================================================================
VPA_RE = re.compile(r"[A-Za-z0-9._\-]{2,256}@[A-Za-z][A-Za-z0-9.\-]{1,64}")   # name@bank


def _image_variants(img):
    """A few cleaned-up versions of the photo. If one fails to decode, the next may work."""
    img = ImageOps.exif_transpose(img).convert("RGB")     # fix sideways phone photos
    gray = ImageOps.grayscale(img)
    variants = [img, gray, ImageOps.autocontrast(gray)]
    w, h = gray.size
    if max(w, h) > 1600:                                   # very large photo: shrink it
        scale = 1600 / max(w, h)
        variants.append(gray.resize((int(w * scale), int(h * scale))))
    if max(w, h) < 600:                                    # tiny screenshot: enlarge it
        variants.append(gray.resize((w * 3, h * 3), Image.NEAREST))
    variants.append(gray.point(lambda p: 255 if p > 128 else 0))   # pure black and white
    return variants


@st.cache_data(show_spinner=False)      # same image twice -> no need to decode again
def decode_qr(image_bytes):
    """Returns the text stored inside the QR code, or None if no QR was found."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception:
        return None
    for variant in _image_variants(img):
        pixels = np.array(variant)
        if zxingcpp is not None:
            for result in zxingcpp.read_barcodes(pixels):
                if result.text:
                    return result.text
        if cv2 is not None:
            text, _, _ = cv2.QRCodeDetector().detectAndDecode(pixels)
            if text:
                return text
    return None


def _tlv(data):
    """Splits a BharatQR string into {tag: value}. Each field is 2-digit tag + 2-digit length + value."""
    fields, i = {}, 0
    while i + 4 <= len(data):
        tag, length = data[i:i + 2], data[i + 2:i + 4]
        if not length.isdigit():
            break
        n = int(length)
        fields[tag] = data[i + 4:i + 4 + n]
        i += 4 + n
    return fields


def _parse_bharat_qr(text):
    """Shop QRs (BharatQR / EMV format) keep the UPI ID inside tags 02-51 and the name in tag 59."""
    top = _tlv(text)
    params = {}
    for tag, value in top.items():
        if tag.isdigit() and 2 <= int(tag) <= 51:
            for sub_value in _tlv(value).values():
                if "@" in sub_value and "pa" not in params:
                    params["pa"] = sub_value
    if "59" in top:
        params["pn"] = top["59"]
    if "54" in top:
        params["am"] = top["54"]
    return params


def parse_upi_qr(text):
    """Turns the QR text into {vpa, name, amount, note, raw}, whatever app made it."""
    text = (text or "").strip().replace("&amp;", "&")
    if text.startswith("000201"):                          # BharatQR shop code
        params = _parse_bharat_qr(text)
    else:                                                  # upi://pay?..., UPI://PAY/?..., web links
        query = text.split("?", 1)[1] if "?" in text else ""
        params = {k.lower(): v[0] for k, v in parse_qs(query).items()}   # decodes %20 and +

    vpa = params.get("pa", "").strip()
    if not vpa:                                            # last resort: find name@bank anywhere
        match = VPA_RE.search(unquote(text))
        vpa = match.group(0) if match else ""

    try:
        amount = float(params.get("am") or 0)
    except ValueError:
        amount = 0.0

    return {"vpa": vpa.lower(), "name": params.get("pn", "").strip(),
            "amount": amount, "note": params.get("tn", "").strip(), "raw": text}


# ======================================================================
# 3. Payment password, fraud check and warning popup
# ======================================================================
@st.dialog("Confirm payment")
def password_dialog():
    """Asks for the account password before a payment is sent (like a UPI PIN)."""
    pending = st.session_state.get("pending_payment")
    if not pending:
        return
    payload = pending["payload"]
    st.markdown(f"Paying **₹{payload['amount']:,.2f}** to **{pending['payee']}**")
    st.caption(f"Enter your {APP_NAME} account password to authorise this payment.")

    with st.form("pay_password_form", clear_on_submit=True):   # clears the box after each try
        password = st.text_input("Password", type="password")
        confirmed = st.form_submit_button("Confirm and pay", type="primary")

    if st.button("Cancel", key="pay_password_cancel"):
        st.session_state["pending_payment"] = None
        st.session_state["outcome"] = ("warning", "Payment cancelled. Nothing was sent.")
        st.rerun()

    if confirmed:
        if auth.verify_user(current_user()["email"], password):
            # correct: hand the payment to the page, which sends it after this popup closes
            st.session_state["pw_attempts"] = 0
            st.session_state["verified_payment"] = pending
            st.session_state["pending_payment"] = None
            st.rerun()

        st.session_state["pw_attempts"] += 1
        left = MAX_PASSWORD_ATTEMPTS - st.session_state["pw_attempts"]
        if left <= 0:
            # too many wrong tries: lock payments for a minute and close the popup
            st.session_state["pw_attempts"] = 0
            st.session_state["pw_locked_until"] = time.time() + LOCK_SECONDS
            st.session_state["pending_payment"] = None
            st.session_state["outcome"] = ("error",
                f"{MAX_PASSWORD_ATTEMPTS} wrong password attempts. Payments are locked. "
                f"Please wait {LOCK_SECONDS // 60} minute and try again.")
            st.rerun()
        st.error(f"Wrong password. {left} attempt{'s' if left != 1 else ''} left.")


@st.dialog("Suspicious payment detected")
def warning_dialog(entry_id, payee, amount, result, uses_balance=True):
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
        if uses_balance:
            deduct_balance(amount)            # the money actually left the account
        st.session_state["outcome"] = ("warning",
            f"₹{amount:,.2f} was sent to {payee} despite the warning.")
        st.rerun()


def check_and_pay(payee, payload, uses_balance=True):
    """Score the payment with the API. SAFE -> sent. RISKY -> warning popup.
    uses_balance=False for dataset demo payments, which aren't the customer's money."""
    st.session_state["outcome"] = None
    result = api_post("/score", payload)
    if result is None:
        st.error("Could not reach the fraud engine. Is the backend running?")
        return

    risky = result["verdict"] == "RISKY"
    entry = {
        "id": uuid.uuid4().hex[:8],
        "When": now_ist().strftime("%d %b, %H:%M"),        # Indian time, not server time
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
        warning_dialog(entry["id"], payee, payload["amount"], result, uses_balance)
    else:
        if uses_balance:
            deduct_balance(payload["amount"])
        st.session_state["outcome"] = ("success",
            f"₹{payload['amount']:,.2f} sent to {payee}. "
            f"Risk {result['risk_score'] * 100:.0f}%, looks safe. "
            f"Balance left: ₹{st.session_state['balance']:,.2f}")


def run_dataset_payment(fraud):
    """Demo control: score a real unseen payment from the dataset (ML model only)."""
    data = api_get("/sample", params={"fraud": "true" if fraud else "false"})
    if data is None:
        st.error("Could not reach the fraud engine.")
        return
    data.pop("actual_label")               # remove the answer key
    check_and_pay(random.choice(["Rahul Kumar", "Priya Sharma", "Amit Verma"]), data,
                  uses_balance=False)


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

    # Top row: greeting on the left; Scan QR button + rotating safety tip on the right
    head_left, head_right = st.columns([3, 2], gap="large", vertical_alignment="center")
    with head_left:
        eyebrow("Personal payment protection")
        st.title("Your dashboard")
        st.subheader(f"Hello, {user['name'].split()[0]}.")
        st.write("Here's an overview of your payment activity.")
    with head_right:
        with st.container(key="home_scan"):
            if st.button("Scan QR", icon=":material/qr_code_scanner:", key="home_scan_btn"):
                st.switch_page(scan_page)
        safety_tip_card()

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
        with st.container(border=True, key="card_activity"):
            eyebrow("Payment activity")
            st.subheader("Recent transactions")
            if history:
                history_table(history, limit=8)
            else:
                st.info("No transactions yet. Your payment activity will "
                        "appear here once you start making payments.")
    with right:
        with st.container(border=True, key="card_check_payment"):
            eyebrow("Before you pay")
            st.subheader("Check a payment")
            st.write(f"Not sure whether a payment request is genuine? "
                     f"{APP_NAME} checks the risk before the money leaves your account.")
            if st.button("Make a payment", type="primary"):
                st.switch_page(safety_page)
        scam_help_card()          # helpline card, right under the Check a payment box


def show_scan_qr():
    eyebrow("Scan to pay")
    st.title("Scan a QR code")
    st.write("Works with QR codes from Google Pay, PhonePe, Paytm, BHIM and shop BharatQR codes.")

    scan_col, result_col = st.columns([3, 2], gap="large")
    with scan_col:
        with st.container(border=True, key="card_scan"):
            tab_cam, tab_up = st.tabs(["Use camera", "Upload QR image"])
            with tab_cam:
                photo = st.camera_input("Hold the QR code in front of the camera",
                                        key="qr_camera")
            with tab_up:
                upload = st.file_uploader("Screenshot or photo of a QR code",
                                          type=["png", "jpg", "jpeg", "webp"],
                                          key="qr_upload")

    source = photo or upload
    with result_col:
        if source is None:
            with st.container(border=True, key="card_scan_empty"):
                st.info("Take a photo or upload an image of the QR code to see who it pays.")
            return

        text = decode_qr(source.getvalue())
        if text is None:
            st.error("No QR code found in this image. Fill the frame with the QR, "
                     "avoid glare, and try again.")
            return

        info = parse_upi_qr(text)
        if not info["vpa"]:
            st.error("This QR code isn't a UPI payment code.")
            with st.expander("What the QR contains"):
                st.code(info["raw"])
            return

        with st.container(border=True, key="card_scan_result"):
            eyebrow("Scanned payee")
            st.subheader(info["name"] or "Name not included in this QR")
            st.markdown(f"UPI ID: `{info['vpa']}`")
            if info["amount"]:
                st.markdown(f"Amount requested: **₹{info['amount']:,.2f}**")
            if info["note"]:
                st.caption(f"Note: {info['note']}")
            st.caption(f"{APP_NAME} checks this payment for fraud before it's sent.")
            if st.button("Pay this person", type="primary", key="qr_pay"):
                st.session_state["scan_prefill"] = info
                st.switch_page(safety_page)


def show_safety_check():
    eyebrow("Before you pay")
    st.title("Make a payment")

    # Coming from Scan QR? Fill the form with the scanned payee before the widgets are drawn.
    prefill = st.session_state.get("scan_prefill")
    if prefill:
        st.session_state.update({"pay_to": NEW_PAYEE, "pay_upi": prefill["vpa"],
                                 "pay_request": False, "scanned": prefill})
        if prefill["amount"] >= 1:
            st.session_state["pay_amount"] = prefill["amount"]
        st.session_state["scan_prefill"] = None

    # Password was correct in the popup? Send the payment now (fraud check + warning as usual).
    verified = st.session_state.get("verified_payment")
    if verified:
        st.session_state["verified_payment"] = None
        check_and_pay(verified["payee"], verified["payload"])

    balance = st.session_state["balance"]
    usual = st.session_state["acct_usual"]

    form_col, info_col = st.columns([3, 2], gap="large")

    with form_col:
        with st.container(border=True, key="card_payment_form"):
            choice = st.selectbox("Pay to", list(PAYEES), key="pay_to")
            tx_type, payee_known = PAYEES[choice]

            if choice == NEW_PAYEE:
                payee_name = st.text_input("UPI ID", placeholder="name@bank",
                                           key="pay_upi").strip()
                scanned = st.session_state.get("scanned")
                if scanned and scanned["name"] and scanned["vpa"] == payee_name.lower():
                    st.caption(f"Scanned QR belongs to: {scanned['name']}")
                    payee_name = f"{scanned['name']} ({payee_name})"
            else:
                payee_name = choice.split(" (")[0]      # "Rahul Kumar"

            amount = st.number_input("Amount (₹)", min_value=1.0, step=100.0,
                                     key="pay_amount")
            is_request = st.checkbox(
                "I'm paying because someone sent me a payment request",
                key="pay_request")

            if st.button("Pay now", type="primary"):
                wait = lock_seconds_left()
                if wait:
                    st.error(f"Too many wrong password attempts. Try again in {wait} seconds.")
                elif choice == NEW_PAYEE and not payee_name:
                    st.error("Enter the UPI ID to continue.")
                elif amount > balance:
                    st.error("Insufficient balance.")
                else:
                    st.session_state["outcome"] = None
                    st.session_state["pending_payment"] = {
                        "payee": payee_name,
                        "payload": {
                            "amount": amount,
                            "type": tx_type,
                            "oldbalanceOrg": balance,
                            "newbalanceOrig": balance - amount,
                            "oldbalanceDest": 0.0,
                            # merchants keep no balance in the dataset; people do
                            "newbalanceDest": 0.0 if tx_type == "PAYMENT" else amount,
                            "hour": now_ist().hour,     # Indian hour of day for the model
                            # context the safety rules use (a real app knows these itself)
                            "payee_known": payee_known,
                            "is_collect_request": is_request,
                            "usual_amount": usual,
                        },
                    }
                    password_dialog()                   # ask for the password first

        outcome = st.session_state.get("outcome")
        if outcome:
            kind, text = outcome
            show = {"success": st.success, "warning": st.warning, "error": st.error}
            show.get(kind, st.info)(text)

    with info_col:
        with st.container(border=True, key="card_account"):
            eyebrow("From account")
            # read it fresh, so a payment made just above shows up immediately
            st.metric("Available balance", f"₹{st.session_state['balance']:,.2f}")
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
            a1.number_input("Set balance to (₹)", min_value=0.0, step=1000.0,
                            value=START_BALANCE, key="demo_balance")
            if a1.button("Update balance"):
                st.session_state["balance"] = st.session_state["demo_balance"]
                st.rerun()
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
        with st.container(border=True, key="card_insight_split"):
            st.subheader("Safe vs flagged")
            st.bar_chart(pd.Series({"Safe": safe, "Flagged": len(history) - safe}))
    with right:
        with st.container(border=True, key="card_insight_risk"):
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
                "Time": now_ist().strftime("%H:%M:%S"),   # Indian time
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

    with st.container(border=True, key="card_live_feed"):
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
scan_page = st.Page(show_scan_qr, title="Scan QR",
                    icon=":material/qr_code_scanner:", url_path="scan-qr")
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
        groups = [("MENU", [home_page, scan_page, safety_page, tx_page, insights_page])]
    pg = st.navigation([p for _, pages in groups for p in pages], position="hidden")
    render_sidebar(user, groups)

pg.run()