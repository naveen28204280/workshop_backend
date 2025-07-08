from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy, or_
from dotenv import load_dotenv
import os
import random
import shutil
import google.auth
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build

load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URI")
db = SQLAlchemy(app)
CORS(app)

max_seats = int(os.getenv("SEATS"))
spreadsheet_id = os.getenv("SPREADSHEET_ID")
spreadsheet_access_token = os.getenv("SPREADSHEET_ACCESS_TOKEN")

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
        creds, _ = google.auth.default()
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
        return jsonify({'error': e})

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

@app.route("/create-order/", methods=["POST"]) # check add_to_sheet if it throws an error also check to make sure seats are left
def create_order():
    os.makedirs('qr_codes', exist_ok=True)
    files = [
        f for f in os.listdir('qr_codes') if f.lower().endswith((".png", ".jpg", ".jpeg"))
    ]
    if not files:
        return None
    return os.path.join('qr_codes', random.choice(files))

@app.route("/payment-confirmation/", methods=["POST"])
def payment_confirm():
    if "image" not in request.files or "name" not in request.form:
        return {"error": "Missing required fields"}, 400
    image = request.files["image"]
    name = request.form["name"]
    if image.filename == "":
        return {"error": "No file selected"}, 400
    os.makedirs("payment_confirmation", exist_ok=True)
    _, ext = os.path.splitext(image.filename)
    new_filename = f"{name}{ext}"
    destination_path = os.path.join("payment_confirmation", new_filename)
    image.save(destination_path)
    return {"stored_path": destination_path}, 200

if __name__ == "__main__":
    app.run(debug=True)