from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from dotenv import load_dotenv
import os
import requests
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from email.message import EmailMessage
import base64
import os.path
import time
import smtplib

load_dotenv()
emailCreds={
  "installed": {
    "client_id": os.getenv("MAILCLIENTID"),
    "project_id": os.getenv("PROJECTID"),
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret":os.getenv("MAILSECRET"),
    "redirect_uris": ["http://localhost"]
  }
}
sheetsCreds={
  "type": "service_account",
  "project_id": os.getenv("PROJECTID"),
  "private_key_id": os.getenv("SHEETPRIVATEKEYID"),
  "private_key": os.getenv("SHEETPRIVATEKEY").replace("\\n","\n"),
  "client_email": os.getenv("SHEETMAIL"),
  "client_id": os.getenv("SHEETCLIENTID"),
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": os.getenv("SHEETCERT"),
  "universe_domain": "googleapis.com"
}


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URI")
db = SQLAlchemy(app)
CORS(app)

max_seats = int(os.getenv("MAX_SEATS"))
spreadsheet_id = os.getenv("SPREADSHEET_ID")
base_url = os.getenv("BASE_URL")
token_data = None
prod = False

class PaymentDetails(db.Model):
    id = db.Column(db.Integer, primary_key=True, nullable=False, autoincrement=True)
    name = db.Column(db.String, nullable=False)
    email = db.Column(db.String, nullable=False)
    phone_number = db.Column(db.String, nullable=False)
    transaction_id = db.Column(db.String, nullable=True)
    roll_no = db.Column(db.String, nullable=False)

with app.app_context():
    db.create_all()


def sendMail(to_email,subject,body):
    try:
        
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = "support@amfoss.in" 
        msg["To"] = to_email
        msg.set_content(body)
       
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.starttls()
            smtp.login(os.getenv("EMAIL_ADDRESS"), os.getenv("EMAIL_PASSWORD"))
            smtp.send_message(msg)
        print(f"Mail sent to {to_email}")
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
        
def add_to_DB(name, roll_no, email, phone_number):
    student = PaymentDetails(
        name=name, roll_no=roll_no, email=email, phone_number=phone_number
    )
    db.session.add(student)
    db.session.commit()
    return student.id

def add_to_DB(name, roll_no, email, phone_number):
    student = PaymentDetails(
        name=name, roll_no=roll_no, email=email, phone_number=phone_number
    )
    db.session.add(student)
    db.session.commit()
    return student.id


def add_to_sheet(id, name, roll_no, email, phone_number, transaction_id): # added to sheet only if transaction is completed
    try:
        global spreadsheet_id
        range = "A2:F"
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = ServiceAccountCredentials.from_service_account_info(sheetsCreds, scopes=scopes)
        service = build("sheets", "v4", credentials=creds)
        values = [[id, name, roll_no, email, phone_number, transaction_id]]
        
        body = {"values": values}
        result = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=range,
                valueInputOption="RAW",
                body=body,
            )
            .execute()
        )
        return result
    except Exception as e:
        print(str(e))
        return {'error': str(e)}
def get_access_token():
    global token_data
    if token_data and time.time() < token_data['expires_at'] - 120:
        return token_data['access_token']
    try:
        if not prod:
            url = "https://api-preprod.phonepe.com/apis/pg-sandbox/v1/oauth/token"
        else:
            url = "https://api.phonepe.com/apis/identity-manager/v1/oauth/token"
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        json = {
            'client_id': os.getenv("PHONEPE_CLIENT_ID"),
            'client_secret': os.getenv("PHONEPE_CLIENT_SECRET"),
            'client_version': 1,
            'grant_type': 'client_credentials'
        }
        response = requests.post(url=url, headers=headers, data=json)
        if response.status_code==200:
            data = response.json()
            token_data = data
            return data['access_token']
        elif time.time() < token_data["expires_at"]:
            return token_data['access_token']
        else:
            return False
    except Exception as e:
        return str(e)
    
def confirm_payment(id, transaction_id):
    student = PaymentDetails.query.get(id)
    student.transaction_id = transaction_id
    db.session.commit()
    try:
        add_to_sheet(
            id=student.id, 
            name=student.name,
            roll_no=student.roll_no,
            email=student.email, 
            transaction_id=transaction_id, 
            phone_number=student.phone_number
        )
        sendMail(
            to_email=student.email,
            subject="Workshop Seat Confirmed 🎉",
            body=f"Hi {student.name},\n\nYour seat has been confirmed! ✅\n\nTransaction ID: {transaction_id}\n\nThank you for joining our workshop!"
        )
    except Exception:
        return False
    return True

def check_prev(name, roll_no, email):
    transaction = PaymentDetails.query.filter(
        or_(
            PaymentDetails.roll_no == roll_no,
            PaymentDetails.email == email,
        )
    ).first()
    return transaction

@app.route("/seats-left/", methods=["GET"])
def no_of_seats_left():
    try:
        booked = PaymentDetails.query.filter(PaymentDetails.transaction_id is not None).count()
        seats_left = max_seats - booked
        return jsonify({"seat_left": seats_left}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/create_order/", methods=["POST"])
def create_order():
    booked = PaymentDetails.query.filter(PaymentDetails.transaction_id is not None).count()
    if (max_seats - booked) <= 0:
        return jsonify({'error': "No seats left"}),409
    data = request.json
    if not all(
        [
            data.get("name"),
            data.get("roll_no"),
            data.get("email"),
            data.get("phone_number"),
        ]
    ):
        return jsonify({"error": "Missing required fields"}),400
    prev = check_prev(name=data["name"], roll_no=data["roll_no"], email=data["email"])
    if prev and not prev.transaction_id:
        merchantOrderId = prev.id
    if prev:
        if prev.transaction_id:
            return jsonify({"error": "You have already paid"}),409
    else:
        merchantOrderId = add_to_DB(
            name=data["name"], roll_no=data["roll_no"], phone_number=data["phone_number"], email = data['email']
        )
    try:
        access_token = get_access_token()
        if not access_token:
            return jsonify({'error': 'access_token not generated'}), 500
        if not prod:
            url = "https://api-preprod.phonepe.com/apis/pg-sandbox/checkout/v2/pay"
        else:
            url = "https://api.phonepe.com/apis/pg/checkout/v2/pay"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"O-Bearer {access_token}",
        }
        body = {
            "merchantOrderId": str(merchantOrderId),
            "amount": 149900 if prod else 1000,
            "expireAfter": 1200,
            "paymentFlow": {
                "type": "PG_CHECKOUT",
                "message": "Payment message used for collect requests",
                "merchantUrls": {
                    "redirectUrl": "http://localhost:3000/register/payment"
                    if not prod
                    else "https://events.amfoss.in/register/payment"
                },
            },
        }
        response = requests.post(url, headers=headers, json=body)
        if response.status_code==200:
            data = response.json()
            print(merchantOrderId)
            return jsonify({'redirectUrl': data['redirectUrl'], "merchantOrderId": merchantOrderId}), 200
        else:
            return jsonify({'error': 'failed to create order'}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@app.route("/payment-confirmation/<int:merchantOrderId>", methods=["GET"])
def payment_confirmation(merchantOrderId):
    print("Hi")
    access_token = get_access_token()
    if not prod:
        url = f"https://api-preprod.phonepe.com/apis/pg-sandbox/checkout/v2/order/{merchantOrderId}/status"
    else:
        url = f"https://api.phonepe.com/apis/pg/checkout/v2/order/{merchantOrderId}/status"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"O-Bearer {access_token}",
    }
    params = {
        "details": "false",
        "errorContext": "false"
    }
    try:
        while True:
            response = requests.get(url, headers=headers, params=params)
            if response.status_code!=200:
                retry_count=0
                max_retries=10
                if retry_count < max_retries:
                    retry_count += 1
                    time.sleep(1)
                    continue
                return jsonify({"error": "max retries exceeded"}), 500
            data = response.json()
            if data['state'] == "COMPLETED":
                transaction_id = data["paymentDetails"][0]["transactionId"]
                if confirm_payment(
                    id=int(merchantOrderId),
                    transaction_id=transaction_id
                ):
                    return jsonify({"success": True, "transactionId": transaction_id}), 200
                else:
                    return jsonify({'error': "payment succesfull but failed to add to sheet", "transantionId": transaction_id}),202
            elif data['state'] == "FAILED":
                transaction_id = data["paymentDetails"][0]["transactionId"]
                return jsonify({"success": False, "state": "FAILED", "transactionId": transaction_id}), 200
            else:
                time.sleep(1)
    except Exception as e:
        print("Error in payment confirmation:", str(e))
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    app.run(debug=True)