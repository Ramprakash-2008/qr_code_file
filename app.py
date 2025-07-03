import os
import sqlite3
import qrcode
import uuid
from flask import Flask, render_template, request, redirect, url_for, send_file
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta

load_dotenv()

app = Flask(__name__)
DB_PATH = 'database.db'
OWNER_EMAIL = os.getenv('OWNER_EMAIL')
APP_PASSWORD = os.getenv('APP_PASSWORD')
BASE_URL = os.getenv('BASE_URL')  # e.g. https://yourapp.onrender.com

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
        file_link = request.form['file_link']
        token = str(uuid.uuid4())
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("INSERT INTO requests (token, file_link, status) VALUES (?, ?, ?)",
                         (token, file_link, 'new'))
        qr_url = f"{BASE_URL}/request/{token}"
        img = qrcode.make(qr_url)
        img_path = f"static/qr/{token}.png"
        img.save(img_path)
        return send_file(img_path, as_attachment=True)
    return render_template('generate.html')

@app.route('/request/<token>', methods=['GET', 'POST'])
def request_access(token):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT gmail, status, approved_at FROM requests WHERE token = ?", (token,))
        row = cur.fetchone()

    if row and row[1] == 'approved':
        approved_at = datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S.%f")
        if datetime.now() < approved_at + timedelta(days=1):
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute("SELECT file_link FROM requests WHERE token = ?", (token,))
                file_link = cur.fetchone()[0]
            return redirect(file_link)
    
    if request.method == 'POST':
        gmail = request.form['gmail']
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE requests SET gmail = ?, status = 'pending' WHERE token = ?",
                         (gmail, token))
        approve_url = url_for('process_request', token=token, action='approve', _external=True)
        deny_url = url_for('process_request', token=token, action='deny', _external=True)
        send_email(OWNER_EMAIL, "File Access Request",
                   f"User: {gmail}<br><a href='{approve_url}'>Accept</a> | <a href='{deny_url}'>Deny</a>")
        return render_template('success.html')
    
    return render_template('request_form.html')

@app.route('/process/<action>/<token>')
def process_request(action, token):
    if action == 'approve':
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT gmail FROM requests WHERE token = ?", (token,))
            gmail = cur.fetchone()[0]
            conn.execute("UPDATE requests SET status = ?, approved_at = ? WHERE token = ?",
                         ('approved', datetime.now(), token))
        send_email(gmail, "Access Approved", "Your request has been approved. You can now scan the QR again to access the file.")
    elif action == 'deny':
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT gmail FROM requests WHERE token = ?", (token,))
            gmail = cur.fetchone()[0]
            conn.execute("UPDATE requests SET status = ? WHERE token = ?", ('denied', token))
        send_email(gmail, "Access Denied", "Your request for access was denied.")
    return f"User has been {action}d."

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
