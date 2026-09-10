import os
import json
import requests
import streamlit as st
import pandas as pd
from google import genai
from google.genai import types

# Page Config
st.set_page_config(page_title="Junkyard Flip Assistant", layout="wide")
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

# --- LOCAL MICHIGAN YARD PRICING TABLES ---
YARD_PRICING = {
    "pontiac": {
        "name": "U-Pull & Save (Pontiac, MI)",
        "prices": {
            "apim": 31.49,
            "blind_spot": 20.99,
            "amp": 12.99,
            "bcm": 31.49,
            "pcm": 31.49,
            "tail_light": 22.99,
            "master_switch": 11.99,
            "hvac_panel": 20.99,
            "cluster": 26.49,
            "abs_module": 31.49,
            "radio_nav": 31.49,
            "default": 20.00
        }
    },
    "sterling_heights": {
        "name": "US Auto Supply (Sterling Heights, MI)",
        "prices": {
            "apim": 25.00,
            "blind_spot": 20.00,
            "amp": 20.00,
            "bcm": 25.00,
            "pcm": 25.00,
            "tail_light": 20.00,
            "master_switch": 10.00,
            "hvac_panel": 15.00,
            "cluster": 25.00,
            "abs_module": 20.00,
            "radio_nav": 35.00,
            "default": 20.00
        }
    }
}

selected_yard = st.sidebar.selectbox(
    "Select Local Yard:",
    options=["pontiac", "sterling_heights"],
    format_func=lambda x: YARD_PRICING[x]["name"]
)

def calculate_local_yard_cost(part_category, yard_key):
    """Calculates exact yard cost including MI 6% sales tax."""
    yard = YARD_PRICING.get(yard_key, YARD_PRICING["pontiac"])
    base_price = yard["prices"].get(part_category, yard["prices"]["default"])
    tax = base_price * 0.06
    return round(base_price + tax, 2)

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
            client = genai.Client(api_key=gemini_api_key)
            
            with st.spinner(f"Analyzing {year} {make} {model} for {YARD_PRICING[selected_yard]['name']}..."):
                prompt = f"""
                You are an expert auto parts liquidator specializing in self-serve junkyard flipping on eBay.
                When given a vehicle ({year} {make} {model} {trim}), identify the top 15 candidate high-value OEM parts.

                Return strictly raw JSON format matching this array schema:
                [
                  {{
                    "part_name": "Part Name",
                    "category_key": "apim", 
                    "est_ebay_price": 120,
                    "difficulty": "Easy (5 mins)",
                    "tools_needed": "10mm socket, trim tool",
                    "notes": "Common failure point; high resale demand."
                  }}
                ]
                Valid category_keys are: 'apim', 'blind_spot', 'amp', 'bcm', 'pcm', 'tail_light', 'master_switch', 'hvac_panel', 'cluster', 'abs_module', 'radio_nav', 'default'.
                """

                # Enforce JSON output mode directly in SDK settings
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )

                raw_text = response.text.strip()
                parts_data = json.loads(raw_text)

                for item in parts_data:
                    cat = item.get("category_key", "default")
                    yard_cost = calculate_local_yard_cost(cat, selected_yard)
                    avg_sold = float(item.get("est_ebay_price", 75))
                    
                    ebay_fee = (avg_sold * 0.1325) + 0.30
                    est_shipping = 12.00
                    net_profit = round(avg_sold - yard_cost - ebay_fee - est_shipping, 2)

                    item["Yard Cost ($)"] = f"${yard_cost:.2f}"
                    item["Avg Sold Price ($)"] = f"${avg_sold:.2f}"
                    item["Est. Net Profit ($)"] = f"${net_profit:.2f}"

                st.subheader(f"Top Pulls for {year} {make} {model}")
                st.caption(f"Yard costs based on exact board rates at **{YARD_PRICING[selected_yard]['name']}** (includes 6% MI Sales Tax).")

                df = pd.DataFrame(parts_data)
                display_cols = ["part_name", "Yard Cost ($)", "Avg Sold Price ($)", "Est. Net Profit ($)", "difficulty", "tools_needed", "notes"]
                st.dataframe(df[display_cols], use_container_width=True)

        except Exception as e:
            st.error(f"An error occurred: {e}")
