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

seats_left = int(os.getenv("SEATS"))

Cashfree.XClientId = os.getenv("CASHFREE_ID")
Cashfree.XClientSecret = os.getenv("CASHFREE_API_KEY")
Cashfree.XEnvironment = Cashfree.XSandbox
x_api_version = "2023-08-01"

class PaymentDetails(db.Model):
    id = db.Column(db.Integer, primary_key=True, nullable=False, autoincrement=True)
    name = db.Column(db.String, nullable = False)
    email = db.Column(db.String, unique=True, nullable = False)
    transaction_id = db.Column(db.Integer, unique=True, nullable = False)
    roll_no = db.Column(db.String, unique = True, nullable = False)

with app.app_context():
    db.create_all()

def add_to_DB(name, roll_no, email, transaction_id):
    student = PaymentDetails(name = name, roll_no = roll_no, email = email, transaction_id = transaction_id)
    db.add(student)
    db.commit()
    return True

def check_prev(name, roll_no, email):
    transaction = PaymentDetails.query.filter(
        or_(PaymentDetails.name == name, PaymentDetails.roll_no == roll_no, PaymentDetails.email == email)
        ).first()
    if transaction:
        return True
    else:
        return False

def register():
    try:
        global seats_left
        data = request.json
        if not all(data.get(field) for field in ["name", "roll_no", "email", "transaction_id"]):
            return jsonify({"error": "Missing required fields"}), 400
        paid = check_prev(roll_no = data['roll_no'], email = data['email'], name = data['name'])
        if paid:
            return ({'error': 'You have already paid'}), 409
        add_to_DB(name=data['name'], roll_no=data['roll_no'], email=data['email'], transaction_id=data['transaction_id'])
        seats_left -= 1
        return jsonify({'success': 'registered'}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/seats-left/", methods=["GET"])
def no_of_seats_left():
    try:
        global seats_left
        return jsonify({"seat_left": seats_left}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route("/create_order/", methods = ["POST"])
def create_order():
    customerDetails = CustomerDetails(customer_id="123", customer_phone="9999999999")
    createOrderRequest = CreateOrderRequest(order_amount=1, order_currency="INR", customer_details=customerDetails)
    try:
        api_response = Cashfree().PGCreateOrder(x_api_version, createOrderRequest, None, None)
        print(api_response.data)
        return jsonify({}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route(os.getenv("WEBHOOK_PATH"), methods = ["POST"])
def payment_confirm():
    pass # calls register if finished

if __name__ == "__main__":
    app.run(debug=True)