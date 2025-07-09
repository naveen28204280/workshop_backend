from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy, or_
from dotenv import load_dotenv
import os
import requests
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URI")
db = SQLAlchemy(app)
CORS(app)

max_seats = int(os.getenv("SEATS"))
spreadsheet_id = os.getenv("SPREADSHEET_ID")
spreadsheet_access_token = os.getenv("SPREADSHEET_ACCESS_TOKEN")
base_url = os.getenv("BASE_URL")

class PaymentDetails(db.Model):
    id = db.Column(db.Integer, primary_key=True, nullable=False, autoincrement=True)
    name = db.Column(db.String, nullable=False)
    email = db.Column(db.String, nullable=False)
    phone_number = db.Column(db.String, nullable=False)
    transaction_id = db.Column(db.Integer, nullable=True)
    roll_no = db.Column(db.String, nullable=False)

with app.app_context():
    db.create_all()

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
        creds = Credentials.from_service_account_file("creds.json", scopes=scopes)
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
        return {'error': str(e)}

def get_access_token():
    pass

def confirm_payment(id, transaction_id):
    student = PaymentDetails.query.get(id=id)
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
        ) # verify it worked
    except Exception as e:
        print(f'adding to sheet failed {e}')
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
        booked = PaymentDetails.query.filter(PaymentDetails.transaction_id is not None).count()
        seats_left = max_seats - booked
        return jsonify({"seat_left": seats_left}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/create_order/", methods=["POST"])
def create_order():
    global max_seats
    booked = PaymentDetails.query.filter(PaymentDetails.transaction_id is not None).count()
    if (max_seats - booked) <= 0:
        return jsonify({'error': "No seats left"}), 409
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
    if prev.transaction_id:
        return jsonify({"error": "You have already paid"}), 409
    if not prev:
        id = add_to_DB(
            name=data["name"], roll_no=data["roll_no"], phone_number=data["phone_number"], email = data['email']
        )
    else:
        id = prev.id
    access_token = get_access_token()
    url = "https://api-preprod.phonepe.com/apis/pg-sandbox/checkout/v2/pay"  # change to https://api.phonepe.com/apis/pg/checkout/v2/pay in prod
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    body = {
        "merchantOrderId": id,
        "amount": 149900,
        "expireAfter": 1200,
        "paymentFlow": {
            "type": "PG_CHECKOUT",
            "message": "Payment message used for collect requests",
            "merchantUrls": {
                "redirectUrl": f"{base_url}/payment-confirmation/",
                "callbackUrl": f"{base_url}/payment-confirmation/",
            },
        },
    }
    try:
        response = requests.post(url, headers=headers, json=body)
        data = response.json
        return jsonify({'redirectUrl': data['redirectUrl']}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/payment-confirmation/", methods=["POST"])
def payment_confirm():
    data = request.json
    if data["payload"]["state"] == "COMPLETED":
        if confirm_payment(
            id = data["payload"]["merchantOrderId"], 
            transaction_id=data["payload"]["paymentDetails"]["transactionId"]
        ):
            return jsonify({'success': 'Booked a seat'}), 200
        else:
            return jsonify({'error': 'payment successful but failed to add to sheets'}), 
    else:
        return jsonify({'error': "payment unsuccessfull"}), 400

if __name__ == "__main__":
    app.run(debug=True)