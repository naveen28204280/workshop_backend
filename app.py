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
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from email.message import EmailMessage
import base64
import os.path
import time

load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URI")
db = SQLAlchemy(app)
CORS(app)

max_seats = int(os.getenv("MAX_SEATS"))
spreadsheet_id = os.getenv("SPREADSHEET_ID")
base_url = os.getenv("BASE_URL")
token_data = None
id = 1

class PaymentDetails(db.Model):
    id = db.Column(db.Integer, primary_key=True, nullable=False)
    name = db.Column(db.String, nullable=False)
    email = db.Column(db.String, nullable=False)
    phone_number = db.Column(db.String, nullable=False)
    transaction_id = db.Column(db.Integer, nullable=True)
    roll_no = db.Column(db.String, nullable=False)

with app.app_context():
    db.create_all()

def sendMail(to_email: str, subject: str, body: str):
    SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    try:
        service = build("gmail", "v1", credentials=creds)
        message = EmailMessage()
        message.set_content(body)
        message["To"] = to_email
        message["From"] = os.getenv("AMFOSS_MAIL")
        message["Subject"] = subject
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {"raw": encoded_message}
        send_message = (
            service.users().messages().send(userId="me", body=create_message).execute()
        )
        print(f"✅ Email sent successfully to {to_email} (ID: {send_message['id']})")
        return send_message["id"]
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return None

def add_to_DB(id, name, roll_no, email, phone_number, transaction_id):
    student = PaymentDetails(
        id = id,
        name = name, 
        roll_no = roll_no, 
        email = email, 
        phone_number = phone_number, 
        transaction_id = transaction_id
    )
    db.session.add(student)
    db.session.commit()
    return student

def add_to_sheet(id, name, roll_no, email, phone_number, transaction_id):  # added to sheet only if transaction is completed
    try:
        global spreadsheet_id
        range = "A2:F"
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = ServiceAccountCredentials.from_service_account_file(
            "creds.json", scopes=scopes
        )
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
    except HttpError as e:
        return {"error": str(e)}

def get_access_token():
    global token_data
    if token_data and time.time() < token_data["expires_at"]:
        return token_data["access_token"]
    try:
        url = "https://api-preprod.phonepe.com/apis/pg-sandbox/v1/oauth/token"  # change to https://api.phonepe.com/apis/identity-manager/v1/oauth/token for prod
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        json = {
            "client_id": os.getenv("PHONEPE_CLIENT_ID"),
            "client_secret": os.getenv("PHONEPE_CLIENT_SECRET"),
            "client_version": 1,
            "grant_type": "client_credentials",
        }
        response = requests.post(url=url, headers=headers, data=json)
        data = response.json()
        token_data = data
        return data["access_token"]
    except Exception as e:
        return str(e)

def confirm_payment(id, name, roll_no, email, phone_number, transaction_id):
    try:
        student = add_to_DB(
            id = id,
            name = name,
            roll_no = roll_no,
            email = email,
            phone_number = phone_number,
            transaction_id = transaction_id
        )
        add_to_sheet(
            id=student.id,
            name=name,
            roll_no=roll_no,
            email=email,
            transaction_id=transaction_id,
            phone_number=phone_number,
        )
        sendMail(
            to_email=student.email,
            subject="Workshop Seat Confirmed 🎉",
            body=f"Hi {student.name},\n\nYour seat has been confirmed! ✅\n\nTransaction ID: {transaction_id}\n\nThank you for joining our workshop!",
        )
    except Exception:
        return False
    return True

def check_prev(name, roll_no, email):
    transaction = PaymentDetails.query.filter(
        or_(
            PaymentDetails.name == name,
            PaymentDetails.roll_no == roll_no,
            PaymentDetails.email == email,
        )
    ).first()
    return transaction

@app.route("/seats-left/", methods=["GET"])
def no_of_seats_left():
    try:
        global max_seats
        booked = PaymentDetails.query.filter(
            PaymentDetails.transaction_id is not None
        ).count()
        seats_left = max_seats - booked
        return jsonify({"seat_left": seats_left}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/create_order/", methods=["POST"])
def create_order():
    global max_seats
    global id
    booked = PaymentDetails.query.filter(
        PaymentDetails.transaction_id is not None
    ).count()
    if (max_seats - booked) <= 0:
        return jsonify({"error": "No seats left"}), 409
    data = request.json
    if not all(
        [
            data.get("name"),
            data.get("roll_no"),
            data.get("email"),
            data.get("phone_number"),
        ]
    ):
        return jsonify({"error": "Missing required fields"}), 400
    prev = check_prev(name=data["name"], roll_no=data["roll_no"], email=data["email"])
    if prev and not prev.transaction_id:
        merchantOrderId = prev.id
    if prev:
        if prev.transaction_id:
            return jsonify({"error": "You have already paid"}), 409
    else:
        merchantOrderId = id
        id+=1
    try:
        access_token = get_access_token()
        url = "https://api-preprod.phonepe.com/apis/pg-sandbox/checkout/v2/pay"  # change to https://api.phonepe.com/apis/pg/checkout/v2/pay in prod
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"O-Bearer {access_token}",
        }
        body = {
            "merchantOrderId": str(merchantOrderId),
            "amount": 149900,
            "expireAfter": 1200,
            "metaInfo": {
                "phone_number": str(data["phone_number"]),
                "name": data['name'],
                "roll_no": data['roll_no'],
                "email": data['email'],
            },
            "paymentFlow": {
                "type": "PG_CHECKOUT",
                "message": "Payment message used for collect requests",
                "merchantUrls": {
                    "redirectUrl": "http://localhost:3000/register/payment",  # Change it to events.amfoss.in/register/payment in prod
                },
            },
        }
        response = requests.post(url, headers=headers, json=body)
        data = response.json()
        return jsonify({"redirectUrl": data["redirectUrl"], "orderId": id}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/payment-confirmation/<int:merchantOrderId>", methods=["GET"])
def payment_confirmation(merchantOrderId):
    access_token = get_access_token()
    url = f"https://api-preprod.phonepe.com/apis/pg-sandbox/checkout/v2/order/{merchantOrderId}/status"  # change to https://api.phonepe.com/apis/pg/checkout/v2/order/{merchantOrderId}/status in prod
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"O-Bearer {access_token}",
    }
    params = {"details": "false", "errorContext": "false"}
    try:
        while True:
            response = requests.get(url, headers=headers, params=params)
            data = response.json()
            if data["state"] == "COMPLETED":
                transaction_id = data["paymentDetails"][0]["transactionId"]
                if confirm_payment(
                    id=int(merchantOrderId), 
                    transaction_id=transaction_id,
                    email= data['metaInfo']['email'],
                    roll_no= data['metaInfo']['roll_no'],
                    phone_number= data['metaInfo']['phone_number'],
                    name = data['metaInfo']['name']
                ):
                    return jsonify(
                        {"success": True, "transactionId": transaction_id}
                    ), 200
                else:
                    return jsonify(
                        {
                            "error": "payment succesfull but failed to add to sheet",
                            "transantionId": transaction_id,
                        }
                    ), 202
            elif data["state"] == "FAILED":
                transaction_id = data["paymentDetails"][0]["transactionId"]
                return jsonify(
                    {
                        "success": False,
                        "state": "FAILED",
                        "transactionId": transaction_id,
                    }
                ), 200
            else:
                time.sleep(1)
    except Exception as e:
        print("Error in payment confirmation:", str(e))
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    app.run(debug=True)