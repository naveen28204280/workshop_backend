from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy, or_
from dotenv import load_dotenv
import os
from cashfree_pg.models.create_order_request import CreateOrderRequest
from cashfree_pg.api_client import Cashfree
from cashfree_pg.models.customer_details import CustomerDetails

load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URI")
db = SQLAlchemy(app)
CORS(app)

max_seats = int(os.getenv("SEATS"))

Cashfree.XClientId = os.getenv("CASHFREE_ID")
Cashfree.XClientSecret = os.getenv("CASHFREE_API_KEY")
Cashfree.XEnvironment = Cashfree.XSandbox
x_api_version = "2023-08-01"

class PaymentDetails(db.Model):
    id = db.Column(db.Integer, primary_key=True, nullable=False, autoincrement=True)
    name = db.Column(db.String, nullable=False)
    email = db.Column(db.String, unique=True, nullable=False)
    phone_number = db.Column(db.Integer, unique=True, nullable=False)
    transaction_id = db.Column(db.Integer, unique=True, nullable=True)
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

def confirm_payment(id, transaction_id):
    student = PaymentDetails.query.get(id=id)
    student.transaction_id = transaction_id
    student.paid = True
    db.session.commit()
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
        booked = PaymentDetails.query.filter(paid=True).count()
        seats_left = max_seats - booked
        return jsonify({"seat_left": seats_left}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/create_order/", methods=["POST"])
def create_order():
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
    check_prev(name=data["name"], roll_no=data["roll_no"], email=data["email"])
    if check_prev:
        return jsonify({"error": "This details already exist"}), 409
    id = add_to_DB(
        name=data["name"], roll_no=data["roll_no"], phone_number=data["phone_number"], email = data['email']
    )
    customerDetails = CustomerDetails(
        customer_id=id, customer_phone=data["phone_number"]
    )
    createOrderRequest = CreateOrderRequest(
        order_amount=1800, order_currency="INR", customer_details=customerDetails
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
    pass  # calls register if finished

if __name__ == "__main__":
    app.run(debug=True)