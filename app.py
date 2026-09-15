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
    """Queries eBay's Browse API for active market items matching the part query with cleaned keywords."""
    token = get_ebay_token(app_id, cert_id)
    if not token:
        return []
    
    # Trim and simplify query to ensure the API returns valid matches
    clean_query = " ".join(query.split()[:5])
    url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?q={urllib.parse.quote(clean_query)}&limit=3"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            items = response.json().get("itemSummaries", [])
            results = []
            for item in items:
                title = item.get("title")
                price_info = item.get("price", {})
                price = price_info.get("value")
                currency = price_info.get("currency", "USD")
                item_url = item.get("itemWebUrl")
                results.append({"title": title, "price": f"${price} {currency}", "url": item_url})
            return results
    except Exception:
        pass
    return []

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
                    Prefer small-to-medium parts that are cheap to ship, but include larger items (like grilles, tail lights, or mirrors) if they carry exceptionally high profit margins. 
                    IMPORTANT: Provide realistic market resale price estimates (actual transaction averages, not inflated asking prices).
                    Include a brief note specifying if it's best for 'Shipping' or 'Local Pickup Only'.

                    Return strictly raw JSON format matching this array schema:
                    [
                      {
                        "vehicle_name": "2007-2013 GMC Sierra",
                        "part_name": "OEM Front Grille Assembly",
                        "est_ebay_price": 120,
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
                                raw_text = raw_text.split("```")[1]
                                if raw_text.startswith("json"):
                                    raw_text = raw_text[4:]
                                    
                            scanned_data = json.loads(raw_text.strip())

                            st.subheader("Detected Vehicles & Top Part Targets")
                            for item in scanned_data:
                                v_name = item.get("vehicle_name", "Vehicle")
                                p_name = item.get("part_name", "Part")
                                est_price = float(item.get("est_ebay_price", 50))
                                diff = item.get("difficulty", "N/A")
                                tools = item.get("tools_needed", "N/A")
                                notes = item.get("notes", "N/A")

                                query_str = f"{v_name} {p_name}"
                                query_encoded = urllib.parse.quote(query_str)
                                ebay_url = f"https://www.ebay.com/sch/i.html?_nkw={query_encoded}&LH_Sold=1&LH_Complete=1"
                                upull_url = "https://www.u-pullandsave.com/price-list"

                                with st.container(border=True):
                                    st.markdown(f"### 🚗 {v_name}")
                                    c1, c2, c3 = st.columns([3, 2, 2])
                                    with c1:
                                        st.markdown(f"**Part:** {p_name}")
                                        st.markdown(f"*Notes:* {notes}")
                                    with c2:
                                        st.markdown(f"💰 **Est. eBay:** ${est_price:.2f}")
                                        st.markdown(f"🔧 **Tools:** {tools}")
                                        st.markdown(f"⏱️ **Difficulty:** {diff}")
                                    with c3:
                                        st.markdown("**Quick Lookup:**")
                                        st.markdown(f"[🔍 Check U-Pull Price List]({upull_url})")
                                        st.markdown(f"[📦 View eBay Sold Comps]({ebay_url})")
                                    
                                    # Fetch live eBay API results if credentials are provided
                                    if ebay_app_id and ebay_cert_id:
                                        with st.expander("⚡ Live eBay Market Comps"):
                                            live_items = search_ebay_live(query_str, ebay_app_id, ebay_cert_id)
                                            if live_items:
                                                for li in live_items:
                                                    st.markdown(f"- [{li['title']}]({li['url']}) — **{li['price']}**")
                                            else:
                                                st.info("No active live matches found via API.")
                    except Exception as e:
                        st.error(f"Processing Error: {e}")

# --- TAB 2: MANUAL / VIN LOOKUP ---
with tab2:
    st.subheader("Vehicle Lookup")
    vin_input = st.text_input("Paste 17-Digit VIN (Optional)", value="", max_chars=17, key="vin_box")

    decoded_year, decoded_make, decoded_model, decoded_trim = "", "", "", ""
    if len(vin_input.strip()) == 17:
        with st.spinner("Decoding VIN..."):
            decoded_year, decoded_make, decoded_model, decoded_trim = decode_vin(vin_input.strip())
            if decoded_year:
                st.success(f"Decoded: {decoded_year} {decoded_make} {decoded_model} {decoded_trim}")

    with st.form("vehicle_form"):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            year = st.text_input("Year", value=decoded_year if decoded_year else "2016")
        with col2:
            make = st.text_input("Make", value=decoded_make if decoded_make else "FORD")
        with col3:
            model = st.text_input("Model", value=decoded_model if decoded_model else "Fusion")
        with col4:
            trim = st.text_input("Trim / Engine", value=decoded_trim if decoded_trim else "SE")
        
        submit = st.form_submit_button("Find High-Profit Parts")

    if submit:
        if not gemini_api_key:
            st.error("Please enter your Google Gemini API Key in the sidebar.")
        else:
            try:
                with st.spinner(f"Analyzing {year} {make} {model} for high-margin targets..."):
                    prompt = f"""
                    You are an expert auto parts liquidator specializing in self-serve junkyard flipping.
                    When given a vehicle ({year} {make} {model} {trim}), identify 15 top candidate parts balancing ease of shipping with high-value larger items.
                    IMPORTANT: Provide realistic market resale price averages based on actual completed sale values, not inflated asking prices.
                    Include a brief note on whether the item is great for shipping or better for local cash sale.

                    Return strictly raw JSON format matching this array schema:
                    [
                      {{
                        "part_name": "Part Name",
                        "est_ebay_price": 45,
                        "difficulty": "Easy (5 mins)",
                        "tools_needed": "10mm socket, trim tool",
                        "notes": "High demand, great margin. Good for shipping or local sale."
                      }}
                    ]
                    """

                    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={gemini_api_key}"
                    payload = {
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "responseMimeType": "application/json"
                        }
                    }
                    
                    response = call_gemini_with_retry(url, payload)
                    
                    if response is None or response.status_code != 200:
                        err_msg = response.text if response else "No response from server"
                        st.error(f"API Error: {err_msg}")
                    else:
                        res_json = response.json()
                        raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                        
                        if "```" in raw_text:
                            raw_text = raw_text.split("```")[1]
                            if raw_text.startswith("json"):
                                raw_text = raw_text[4:]
                                
                        parts_data = json.loads(raw_text.strip())

                        st.subheader(f"Top High-Margin Parts to Pull for {year} {make} {model}")
                        st.caption("Includes high-value shippable items and profitable larger components.")

                        for i, item in enumerate(parts_data, 1):
                            p_name = item.get("part_name", "Part")
                            est_price = float(item.get("est_ebay_price", 50))
                            diff = item.get("difficulty", "N/A")
                            tools = item.get("tools_needed", "N/A")
                            notes = item.get("notes", "N/A")

                            query_str = f"{year} {make} {model} {p_name}"
                            query_encoded = urllib.parse.quote(query_str)
                            ebay_url = f"https://www.ebay.com/sch/i.html?_nkw={query_encoded}&LH_Sold=1&LH_Complete=1"
                            upull_url = "https://www.u-pullandsave.com/price-list"

                            with st.container(border=True):
                                c1, c2, c3 = st.columns([3, 2, 2])
                                with c1:
                                    st.markdown(f"**{i}. {p_name}**")
                                    st.markdown(f"*Notes:* {notes}")
                                with c2:
                                    st.markdown(f"💰 **Est. eBay:** ${est_price:.2f}")
                                    st.markdown(f"🔧 **Tools:** {tools}")
                                    st.markdown(f"⏱️ **Difficulty:** {diff}")
                                with c3:
                                    st.markdown("**Quick Lookup:**")
                                    st.markdown(f"[🔍 Check U-Pull Price List]({upull_url})")
                                    st.markdown(f"[📦 View eBay Sold Comps]({ebay_url})")
                                
                                # Fetch live eBay API results if credentials are provided
                                if ebay_app_id and ebay_cert_id:
                                    with st.expander("⚡ Live eBay Market Comps"):
                                        live_items = search_ebay_live(query_str, ebay_app_id, ebay_cert_id)
                                        if live_items:
                                            for li in live_items:
                                                st.markdown(f"- [{li['title']}]({li['url']}) — **{li['price']}**")
                                        else:
                                            st.info("No active live matches found via API.")

            except Exception as e:
                st.error(f"API Error: {e}")
