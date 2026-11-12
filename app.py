
from flask import (
    Flask, render_template, request,
    redirect, url_for, session,
    flash, jsonify
)

from flask_wtf.csrf import CSRFProtect

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from functools import wraps
from decimal import Decimal, InvalidOperation
import sqlite3
import os

from database import get_db


# --------------------------------
# APPLICATION CONFIGURATION
# --------------------------------

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "development-only-change-this-secret"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Enable CSRF protection
csrf = CSRFProtect(app)

# Fictional starting balance: ₹10,000
STARTING_BALANCE = 1000000


# --------------------------------
# LOGIN REQUIRED DECORATOR
# --------------------------------

def login_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:

            return redirect(url_for("login"))

        return func(*args, **kwargs)

    return wrapper


# --------------------------------
# HOME PAGE
# --------------------------------

@app.route("/")
def home():

    if "user_id" in session:

        return redirect(url_for("dashboard"))

    return redirect(url_for("login"))


# --------------------------------
# USER REGISTRATION
# --------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        name = request.form.get("name", "").strip()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get("password", "")

        if not name or len(name) > 100:

            flash("Please enter a valid name.", "error")

            return render_template("register.html")

        if (
            len(email) > 254
            or "@" not in email
            or "." not in email.split("@")[-1]
        ):

            flash("Please enter a valid email.", "error")

            return render_template("register.html")

        if len(password) < 8:

            flash(
                "Password must contain at least 8 characters.",
                "error"
            )

            return render_template("register.html")

        hashed_password = generate_password_hash(password)

        conn = get_db()

        try:

            conn.execute("BEGIN IMMEDIATE")

            cursor = conn.execute("""

                INSERT INTO users (name, email, password)

                VALUES (?, ?, ?)

            """, (name, email, hashed_password))

            user_id = cursor.lastrowid

            # Create wallet automatically

            conn.execute("""

                INSERT INTO accounts (user_id, balance)

                VALUES (?, ?)

            """, (user_id, STARTING_BALANCE))

            conn.commit()

            flash(
                "Account created successfully! Please login.",
                "success"
            )

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:

            conn.rollback()

            flash("Email already registered.", "error")

        finally:

            conn.close()

    return render_template("register.html")


# --------------------------------
# USER LOGIN
# --------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get("password", "")

        conn = get_db()

        user = conn.execute("""

            SELECT * FROM users

            WHERE email = ?

        """, (email,)).fetchone()

        conn.close()

        if user and check_password_hash(
            user["password"], password
        ):

            session.clear()

            session["user_id"] = user["id"]

            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


# --------------------------------
# USER LOGOUT
# --------------------------------

@app.route("/logout", methods=["POST"])
@login_required
def logout():

    session.clear()

    flash("Logged out successfully.", "success")

    return redirect(url_for("login"))


# --------------------------------
# USER DASHBOARD
# --------------------------------

@app.route("/dashboard")
@login_required
def dashboard():

    user_id = session["user_id"]

    conn = get_db()

    user = conn.execute("""

        SELECT users.name, accounts.balance

        FROM users

        JOIN accounts

        ON users.id = accounts.user_id

        WHERE users.id = ?

    """, (user_id,)).fetchone()

    transactions = conn.execute("""

        SELECT

            t.*,

            sender.name AS sender_name,

            receiver.name AS receiver_name

        FROM transactions t

        JOIN users sender

            ON t.sender_id = sender.id

        JOIN users receiver

            ON t.receiver_id = receiver.id

        WHERE t.sender_id = ? OR t.receiver_id = ?

        ORDER BY t.id DESC

        LIMIT 50

    """, (user_id, user_id)).fetchall()

    conn.close()

    if not user:

        session.clear()

        return redirect(url_for("login"))

    return render_template(

        "dashboard.html",

        user=user,

        transactions=transactions

    )


# --------------------------------
# PAYMENT PROCESSING API
# --------------------------------

@app.route("/api/transfer", methods=["POST"])
@login_required
def transfer():

    data = request.get_json(silent=True)

    if not isinstance(data, dict):

        return jsonify({
            "error": "Invalid request data."
        }), 400

    receiver_email = data.get(
        "receiver_email", ""
    )

    if not isinstance(receiver_email, str):

        return jsonify({
            "error": "Invalid receiver email."
        }), 400

    receiver_email = receiver_email.strip().lower()

    raw_amount = data.get("amount")

    key = request.headers.get(
        "Idempotency-Key", ""
    ).strip()

    if not receiver_email or not key or len(key) > 128:

        return jsonify({
            "error": "Missing or invalid payment details."
        }), 400

    if len(key) < 8:

        return jsonify({
            "error": "Invalid idempotency key."
        }), 400

    # Validate amount without floating-point calculations

    if isinstance(raw_amount, bool) or raw_amount is None:

        return jsonify({
            "error": "Invalid payment amount."
        }), 400

    try:

        amount_decimal = Decimal(str(raw_amount))

        if not amount_decimal.is_finite():

            raise InvalidOperation

        if amount_decimal <= 0:

            raise InvalidOperation

        if amount_decimal != amount_decimal.quantize(
            Decimal("0.01")
        ):

            raise InvalidOperation

        amount = int(amount_decimal * 100)

    except (InvalidOperation, ValueError, TypeError):

        return jsonify({
            "error": "Enter a valid amount with at most 2 decimal places."
        }), 400

    sender_id = session["user_id"]

    conn = get_db()

    try:

        # Lock the database before processing payment

        conn.execute("BEGIN IMMEDIATE")

        # Find receiver

        receiver = conn.execute("""

            SELECT id FROM users

            WHERE email = ?

        """, (receiver_email,)).fetchone()

        if not receiver:

            conn.rollback()

            return jsonify({
                "error": "Receiver account not found."
            }), 404

        receiver_id = receiver["id"]

        if sender_id == receiver_id:

            conn.rollback()

            return jsonify({
                "error": "You cannot transfer money to yourself."
            }), 400

        # Check duplicate payment request

        existing = conn.execute("""

            SELECT * FROM transactions

            WHERE idempotency_key = ?

        """, (key,)).fetchone()

        if existing:

            if (
                existing["sender_id"] != sender_id
                or existing["receiver_id"] != receiver_id
                or existing["amount"] != amount
            ):

                conn.rollback()

                return jsonify({
                    "error": "Idempotency key reused with different payment details."
                }), 409

            conn.commit()

            return jsonify({

                "message": "Payment already processed.",

                "transaction_id": existing["id"],

                "status": existing["status"]

            }), 200

        # Check sender balance

        sender = conn.execute("""

            SELECT balance FROM accounts

            WHERE user_id = ?

        """, (sender_id,)).fetchone()

        if not sender or sender["balance"] < amount:

            conn.rollback()

            return jsonify({
                "error": "Insufficient wallet balance."
            }), 400

        # Debit sender only if sufficient balance remains

        debit = conn.execute("""

            UPDATE accounts

            SET balance = balance - ?

            WHERE user_id = ?

            AND balance >= ?

        """, (amount, sender_id, amount))

        if debit.rowcount != 1:

            conn.rollback()

            return jsonify({
                "error": "Payment could not be completed."
            }), 400

        # Credit receiver

        credit = conn.execute("""

            UPDATE accounts

            SET balance = balance + ?

            WHERE user_id = ?

        """, (amount, receiver_id))

        if credit.rowcount != 1:

            conn.rollback()

            return jsonify({
                "error": "Receiver wallet not found."
            }), 400

        # Save transaction record

        cursor = conn.execute("""

            INSERT INTO transactions (

                sender_id,

                receiver_id,

                amount,

                status,

                idempotency_key

            )

            VALUES (?, ?, ?, ?, ?)

        """, (

            sender_id,

            receiver_id,

            amount,

            "SUCCESS",

            key

        ))

        transaction_id = cursor.lastrowid

        # Commit all operations together

        conn.commit()

        return jsonify({

            "message": "Payment successful!",

            "transaction_id": transaction_id,

            "status": "SUCCESS"

        }), 200

    except sqlite3.Error:

        conn.rollback()

        app.logger.exception("Payment database error")

        return jsonify({

            "error": "Payment processing failed. Please try again."

        }), 500

    finally:

        conn.close()


# --------------------------------
# RUN APPLICATION
# --------------------------------

if __name__ == "__main__":

    app.run(debug=True)
