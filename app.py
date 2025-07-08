from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy, or_
from dotenv import load_dotenv
import os
from cashfree_pg.models.create_order_request import CreateOrderRequest
from cashfree_pg.api_client import Cashfree
from cashfree_pg.models.customer_details import CustomerDetails
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

Cashfree.XClientId = os.getenv("CASHFREE_ID")
Cashfree.XClientSecret = os.getenv("CASHFREE_API_KEY")
Cashfree.XEnvironment = Cashfree.XSandbox
x_api_version = "2023-08-01"

class PaymentDetails(db.Model):
    id = db.Column(db.Integer, primary_key=True, nullable=False, autoincrement=True)
    name = db.Column(db.String, nullable=False)
    email = db.Column(db.String, unique=True, nullable=False)
    phone_number = db.Column(db.String, unique=True, nullable=False)
    transaction_id = db.Column(db.Integer, nullable=True)
    roll_no = db.Column(db.String, unique=True, nullable=False)

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

def confirm_payment(id, transaction_id):
    student = PaymentDetails.query.get(id=id)
    student.transaction_id = transaction_id
    db.session.commit()
    add_to_sheet(
        id=student.id, 
        name=student.name,
        roll_no=student.roll_no,
        email=student.email, 
        transaction_id=transaction_id, 
        phone_number=student.phone_number
    ) # verify it worked
    return True

def check_prev(name, roll_no, email):
    transaction = PaymentDetails.query.filter(
        or_(
            PaymentDetails.name == name,
            PaymentDetails.roll_no == roll_no,
            PaymentDetails.email == email,
        )
    ).first()
    if transaction:
        return True
    else:
        return False

@app.route("/seats-left/", methods=["GET"])
def no_of_seats_left():
    try:
        global max_seats
        booked = PaymentDetails.query.filter(PaymentDetails.transaction_id is not None).count()
        seats_left = max_seats - booked
        return jsonify({"seat_left": seats_left}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/create_order/", methods=["POST"]) # check add_to_sheet if it throws an error also check to make sure seats are left
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
    if prev:
        return jsonify({"error": "These details already exist"}), 409
    id = add_to_DB(
        name=data["name"], roll_no=data["roll_no"], phone_number=data["phone_number"], email = data['email']
    )
    customerDetails = CustomerDetails(
        customer_id=id, customer_phone=data["phone_number"]
    )
    createOrderRequest = CreateOrderRequest(
        order_amount=1499.00, order_currency="INR", customer_details=customerDetails, notify_url = f"{base_url}/payment-confirmation/"
    )
    try:
        api_response = Cashfree().PGCreateOrder(
            x_api_version, createOrderRequest, None, None
        )
        return jsonify(
            {
                "order_id": api_response.data["order_id"],
                "payment_session_id": api_response.data["payment_session_id"],
            }
        ), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/payment-confirmation/", methods=["POST"])
def payment_confirm():
    data = request.json
    if data['payment']['payment_status']=="SUCCESS":
        confirm_payment(
            id = data["customer_details"]["customer_id"], 
            transaction_id=data["payment"]["bank_reference"]
        )
        return jsonify({'success': 'Booked a seat'}), 200
    else:
        return jsonify({'error': "payment unsuccessfull"}), 400

if __name__ == "__main__":
    app.run(debug=True)