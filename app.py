import os
import json
import urllib.parse
import requests
import streamlit as st
import pandas as pd

# Page Config
st.set_page_config(page_title="Junkyard Part Picker AI", layout="wide")
st.title("🚗 Junkyard Part Picker AI")
st.write("Enter a vehicle or paste a VIN to see high-profit, easy-to-pull parts for eBay flipping.")

# --- AUTOMATIC API KEY LOGIC ---
secret_key = st.secrets.get("GEMINI_API_KEY", "")

st.sidebar.header("Settings")
if secret_key:
    gemini_api_key = secret_key
    st.sidebar.success("✅ Gemini API Key loaded automatically!")
else:
    gemini_api_key = st.sidebar.text_input("Google Gemini API Key", type="password")

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

# --- UI INPUT FORM ---
st.subheader("Vehicle Lookup")
vin_input = st.text_input("Paste 17-Digit VIN (Optional)", value="", max_chars=17, help="Paste a VIN to auto-fill vehicle details.")

decoded_year, decoded_make, decoded_model, decoded_trim = "", "", "", ""
if len(vin_input.strip()) == 17:
    with st.spinner("Decoding VIN..."):
        decoded_year, decoded_make, decoded_model, decoded_trim = decode_vin(vin_input.strip())
        if decoded_year:
            st.success(f"Decoded: {decoded_year} {decoded_make} {decoded_model} {decoded_trim}")
        else:
            st.warning("Could not decode VIN. Please check the digits or fill out manually.")

with st.form("vehicle_form"):
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        year = st.text_input("Year", value=decoded_year if decoded_year else "2005")
    with col2:
        make = st.text_input("Make", value=decoded_make if decoded_make else "Acura")
    with col3:
        model = st.text_input("Model", value=decoded_model if decoded_model else "TL")
    with col4:
        trim = st.text_input("Trim / Engine (Optional)", value=decoded_trim if decoded_trim else "3.2L Base")
    
    submit = st.form_submit_button("Find High-Value Parts")

if submit:
    if not gemini_api_key:
        st.error("Please enter your Google Gemini API Key in the sidebar or set up Streamlit Secrets to run the analysis.")
    else:
        try:
            with st.spinner(f"Analyzing {year} {make} {model} for top eBay parts..."):
                prompt = f"""
                You are an expert auto parts liquidator specializing in self-serve junkyard flipping on eBay.
                When given a vehicle ({year} {make} {model} {trim}), identify 20 top candidate high-value OEM parts.

                Return strictly raw JSON format matching this array schema:
                [
                  {{
                    "part_name": "Part Name",
                    "est_ebay_price": 120,
                    "difficulty": "Easy (5 mins)",
                    "tools_needed": "10mm socket, trim tool",
                    "notes": "Common failure point; high resale demand."
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
                
                response = requests.post(url, json=payload, timeout=30)
                
                if response.status_code != 200:
                    st.error(f"API Error ({response.status_code}): {response.text}")
                else:
                    res_json = response.json()
                    raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                    
                    if "```" in raw_text:
                        raw_text = raw_text.split("```")[1]
                        if raw_text.startswith("json"):
                            raw_text = raw_text[4:]
                            
                    parts_data = json.loads(raw_text.strip())

                    st.subheader(f"Top 20 Parts to Pull for {year} {make} {model}")
                    st.caption("Click the quick links below each part to instantly check local yard pricing or eBay sold comps without retyping.")

                    for i, item in enumerate(parts_data, 1):
                        p_name = item.get("part_name", "Part")
                        est_price = float(item.get("est_ebay_price", 75))
                        diff = item.get("difficulty", "N/A")
                        tools = item.get("tools_needed", "N/A")
                        notes = item.get("notes", "N/A")

                        # Generate pre-filled search URLs
                        query_encoded = urllib.parse.quote(f"{year} {make} {model} {p_name}")
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

        except Exception as e:
            st.error(f"API Error: {e}")
