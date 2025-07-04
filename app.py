import os
import sqlite3
import qrcode
import uuid
from flask import Flask, render_template, request, redirect, url_for, send_file
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE,
                gmail TEXT,
                file_link TEXT,
                status TEXT,
                approved_at DATETIME
            )
        """)
load_dotenv()
app = Flask(__name__)
DB_PATH = 'database.db'
OWNER_EMAIL = os.getenv('OWNER_EMAIL')
APP_PASSWORD = os.getenv('APP_PASSWORD')
BASE_URL = os.getenv('BASE_URL')  # e.g. https://yourapp.onrender.com
init_db()
def send_email(to, subject, html):
    msg = MIMEText(html, "html")
    msg['Subject'] = subject
    msg['From'] = OWNER_EMAIL
    msg['To'] = to

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(OWNER_EMAIL, APP_PASSWORD)
        server.send_message(msg)

@app.route('/generate', methods=['GET', 'POST'])
def generate_qr():
    if request.method == 'POST':
        try:
            file_link = request.form['file_link']
            token = str(uuid.uuid4())
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("INSERT INTO requests (token, file_link, status) VALUES (?, ?, ?)",
                             (token, file_link, 'new'))
            qr_url = f"{BASE_URL}/request/{token}"
            
            # Ensure the QR directory exists
            qr_dir = os.path.join("static", "qr")
            os.makedirs(qr_dir, exist_ok=True)

            img_path = os.path.join(qr_dir, f"{token}.png")
            img = qrcode.make(qr_url)
            img.save(img_path)

            return send_file(img_path, as_attachment=True)

        except Exception as e:
            return f"Internal Server Error: {str(e)}", 500

    return render_template('generate.html')
@app.route('/request/<token>', methods=['GET', 'POST'])
def handle_qr_scan(token):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT file_link, status, gmail FROM requests WHERE token = ?", (token,))
        row = cur.fetchone()

        if not row:
            return "❌ Invalid or expired token."

        file_link, status, approved_gmail = row

        if request.method == 'POST':
            entered_gmail = request.form['gmail'].strip().lower()

            if status == 'approved':
                if entered_gmail == (approved_gmail or '').strip().lower():
                    return redirect(file_link)
                else:
                    return render_template('request_form.html', token=token) 
            elif status in ['new', 'pending']:
                now = datetime.now()
                conn.execute("UPDATE requests SET gmail = ?, status = ?, approved_at = NULL WHERE token = ?",
                             (entered_gmail, 'pending', token))

                approve_url = url_for('process_request', action='approve', token=token, _external=True)
                deny_url = url_for('process_request', action='deny', token=token, _external=True)

                send_email(OWNER_EMAIL, "File Access Request",
                           f"User: {entered_gmail}<br><a href='{approve_url}'>Accept</a> | <a href='{deny_url}'>Deny</a>")

                return render_template('success.html')

            elif status == 'denied':
                return "❌ Your request was denied."

        # If GET method or re-access attempt before approval
        if status == 'approved':
            return render_template('enter_gmail.html', token=token)
        elif status in ['new', 'pending']:
            return render_template('request_form.html', token=token)
        elif status == 'denied':
            return "❌ Your request was denied."

@app.route('/process/<action>/<token>')
def process_request(action, token):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT gmail FROM requests WHERE token = ?", (token,))
        row = cur.fetchone()

        if not row:
            return "❌ Invalid or expired token."

        gmail = row[0]

        if action == 'approve':
            conn.execute("UPDATE requests SET status = ?, approved_at = ? WHERE token = ?",
                         ('approved', datetime.now(), token))
            send_email(gmail, "Access Approved", "✅ Your request has been approved. Scan the QR again to access the file.")
        elif action == 'deny':
            conn.execute("UPDATE requests SET status = ? WHERE token = ?", ('denied', token))
            send_email(gmail, "Access Denied", "❌ Your request was denied.")

    return f"User has been {action}d."

@app.route('/debug/requests')
def debug_requests():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT token, gmail, status FROM requests")
        rows = cur.fetchall()
    return {'requests': rows}

if __name__ == '__main__':
    app.run(debug=True)
