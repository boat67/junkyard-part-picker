import os
import json
import time
import base64
import urllib.parse
import requests
import streamlit as st
import pandas as pd
from PIL import Image
from streamlit_paste_button import paste_image_button

# Page Config
st.set_page_config(page_title="Junkyard Part Picker AI", layout="wide")
st.title("🚗 Junkyard Part Picker AI")
st.write("Upload or paste a yard arrival photo or enter a vehicle/VIN to identify high-profit parts with live eBay market data.")

# --- AUTOMATIC API KEY LOGIC ---
secret_key = st.secrets.get("GEMINI_API_KEY", "")
secret_ebay_app = st.secrets.get("EBAY_APP_ID", "")
secret_ebay_cert = st.secrets.get("EBAY_CERT_ID", "")

st.sidebar.header("Settings")
if secret_key:
    gemini_api_key = secret_key
    st.sidebar.success("✅ Gemini API Key loaded automatically!")
else:
    gemini_api_key = st.sidebar.text_input("Google Gemini API Key", type="password")

st.sidebar.markdown("---")
st.sidebar.header("eBay API Credentials")
if secret_ebay_app and secret_ebay_cert:
    ebay_app_id = secret_ebay_app
    ebay_cert_id = secret_ebay_cert
    st.sidebar.success("✅ eBay Keys loaded automatically!")
else:
    ebay_app_id = st.sidebar.text_input("eBay App ID (Client ID)", type="password")
    ebay_cert_id = st.sidebar.text_input("eBay Cert ID (Client Secret)", type="password")

# --- ROBUST GEMINI API CALLER WITH AUTO-RETRIES ---
def call_gemini_with_retry(url, payload, max_retries=3):
    """Automatically retries the request if Gemini's servers throw a 503 high demand error."""
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=payload, timeout=45)
            if response.status_code == 200:
                return response
            elif response.status_code == 503 and attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            else:
                return response
        except requests.exceptions.Timeout:
            if attempt == max_retries - 1:
                raise
            time.sleep(2)
    return None

# --- EBAY API CLIENT FUNCTIONS ---
@st.cache_data(ttl=7200)
def get_ebay_token(app_id, cert_id):
    """Generates an OAuth client credentials token from eBay."""
    url = "https://api.ebay.com/identity/v1/oauth2/token"
    credentials = f"{app_id}:{cert_id}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope"
    }
    try:
        response = requests.post(url, headers=headers, data=data, timeout=10)
        if response.status_code == 200:
            return response.json().get("access_token")
    except Exception:
        pass
    return None

def search_ebay_live(query, app_id, cert_id):
    """Queries eBay's Browse API with cleaned keywords and basic error handling."""
    token = get_ebay_token(app_id, cert_id)
    if not token:
        return [{"title": "API Auth Failed (Check Keys)", "price": "$0.00", "url": "#"}]
    
    # Simplify query to just core terms to ensure API matches items
    words = query.split()
    clean_query = " ".join(words[:4]) if len(words) > 4 else query
    
    url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?q={urllib.parse.quote(clean_query)}&limit=3"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            items = data.get("itemSummaries", [])
            if not items:
                fallback_url = f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote(query)}"
                return [{"title": "No direct API matches. Click to search manually.", "price": "", "url": fallback_url}]
            
            results = []
            for item in items:
                title = item.get("title")
                price_info = item.get("price", {})
                price = price_info.get("value", "0.00")
                currency = price_info.get("currency", "USD")
                item_url = item.get("itemWebUrl", "#")
                results.append({"title": title, "price": f"${price} {currency}", "url": item_url})
            return results
        else:
            return [{"title": f"API Error Code: {response.status_code}", "price": "", "url": "#"}]
    except Exception as e:
        return [{"title": f"Connection Error: {str(e)}", "price": "", "url": "#"}]

# --- FREE NHTSA VIN DECODER ENGINE ---
def decode_vin(vin):
    """Decodes a 17-digit VIN using the free public NHTSA API."""
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json().get("Results", [])[0]
            year = data.get("ModelYear", "")
            make = data.get("Make", "")
            model = data.get("Model", "")
            trim = data.get("Trim", "") or data.get("DisplacementL", "")
            if trim and "L" in str(trim) and not str(trim).endswith("L"):
                trim = f"{trim}L"
            
            if year and make and model:
                return year, make, model, trim
    except Exception:
        pass
    return None, None, None, None

# --- TAB LAYOUT FOR INPUT MODES ---
tab1, tab2 = st.tabs(["📸 Scan Facebook Yard Photo", "🔤 Manual Vehicle / VIN Lookup"])

# --- TAB 1: FACEBOOK PHOTO SCANNER ---
with tab1:
    st.subheader("Analyze New Arrival Yard Post")
    st.write("Take a screenshot of the Facebook yard post, copy it to your clipboard (`PrtScn` or `Win+Shift+S`), click the button below, and press `Ctrl+V`!")
    
    paste_result = paste_image_button(
        label="📋 Click here & Press Ctrl+V to Paste Image",
        background_color="#FF4B4B",
        hover_background_color="#FF2B2B",
        key="clipboard_paste_btn"
    )
    
    st.markdown("---")
    st.markdown("*Or upload a file the traditional way:*")
    uploaded_file = st.file_uploader("Upload Yard Photo Grid (PNG, JPG)", type=["jpg", "jpeg", "png"], key="yard_uploader")
    
    image = None
    if paste_result.image_data is not None:
        image = paste_result.image_data
        st.success("✅ Image pasted successfully from clipboard!")
    elif uploaded_file is not None:
        image = Image.open(uploaded_file)
        
    if image is not None:
        st.image(image, caption="Active Yard Post Image", use_container_width=True)
        
        if st.button("Scan Vehicles & Find High-Profit Parts"):
            if not gemini_api_key:
                st.error("Please enter your Google Gemini API Key in the sidebar.")
            else:
                with st.spinner("Analyzing vehicles and identifying high-margin parts..."):
                    import io
                    buffered = io.BytesIO()
                    if image.mode in ("RGBA", "P"):
                        image = image.convert("RGB")
                    image.save(buffered, format="JPEG")
                    img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

                    prompt = """
                    You are an expert auto parts liquidator. Look at this yard arrival photo containing multiple vehicles. 
                    Identify each distinct vehicle visible. For each vehicle, list its top 5 highest-margin parts to flip.
                    Prefer small-to-medium parts that are cheap to ship, but include larger items if they carry exceptionally high profit margins. 
                    IMPORTANT: Provide realistic market resale price estimates based on typical completed sale values (e.g., switches usually sell for $25-$40, modules for $40-$70).
                    Include a brief note specifying if it's best for 'Shipping' or 'Local Pickup Only'.

                    Return strictly raw JSON format matching this array schema:
                    [
                      {
                        "vehicle_name": "2007-2013 GMC Sierra",
                        "part_name": "OEM Front Grille Assembly",
                        "est_ebay_price": 90,
                        "difficulty": "Easy (5 mins)",
                        "tools_needed": "10mm socket, clips tool",
                        "notes": "Large item, highly sought after. Best for Local Pickup or careful box shipping."
                      }
                    ]
                    """

                    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={gemini_api_key}"
                    payload = {
                        "contents": [{
                            "parts": [
                                {"text": prompt},
                                {"inline_data": {"mime_type": "image/jpeg", "data": img_base64}}
                            ]
                        }],
                        "generationConfig": {
                            "responseMimeType": "application/json"
                        }
                    }
                    
                    try:
                        response = call_gemini_with_retry(url, payload)
                        if response is None or response.status_code != 200:
                            err_msg = response.text if response else "No response from server"
                            st.error(f"API Error: {err_msg}")
                        else:
                            res_json = response.json()
                            raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                            
                            if "```" in raw_text:
                                parts_split = raw_text.split("
