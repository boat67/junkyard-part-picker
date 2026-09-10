import os
import re
import json
import requests
import streamlit as st
import google.generativeai as genai

# ------------------------------------------------------------------------------
# 1. SETUP & CONFIGURATION
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="YardFlip - Junkyard Part Evaluator",
    page_icon="🚗",
    layout="wide"
)

# API Keys (Set via Streamlit Secrets or Environment Variables)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EBAY_APP_ID = os.getenv("EBAY_APP_ID")  # Production AppID for eBay Finding API

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ------------------------------------------------------------------------------
# 2. LOCAL MICHIGAN YARD PRICING TABLES (Pontiac & Sterling Heights)
# ------------------------------------------------------------------------------
YARD_PRICING = {
    "pontiac": {
        "name": "U-Pull & Save (Pontiac, MI)",
        "env_fee": 3.00,  # Gate / Environmental fee estimate
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
        "env_fee": 3.00,
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

def calculate_local_yard_cost(part_category, yard_key):
    """Calculates exact yard cost including MI 6% sales tax."""
    yard = YARD_PRICING.get(yard_key, YARD_PRICING["pontiac"])
    base_price = yard["prices"].get(part_category, yard["prices"]["default"])
    
    # Apply 6% Michigan Sales Tax
    tax = base_price * 0.06
    total_cost = round(base_price + tax, 2)
    return total_cost, base_price

# ------------------------------------------------------------------------------
# 3. REAL-TIME EBAY MARKET DATA FETCHING
# ------------------------------------------------------------------------------
def fetch_ebay_sold_data(query_term):
    """
    Fetches real completed/sold listings from eBay Finding API.
    Fallback: returns calculated estimate if API key is not active.
    """
    if not EBAY_APP_ID:
        # Fallback simulation if no active eBay production token present
        return None

    endpoint = "https://svcs.ebay.com/services/search/FindingService/v1"
    headers = {
        "X-EBAY-SOA-OPERATION-NAME": "findCompletedItems",
        "X-EBAY-SOA-SECURITY-APPNAME": EBAY_APP_ID,
        "X-EBAY-SOA-RESPONSE-DATA-FORMAT": "JSON",
    }
    params = {
        "keywords": query_term,
        "itemFilter(0).name": "SoldItemsOnly",
        "itemFilter(0).value": "true",
        "itemFilter(1).name": "Condition",
        "itemFilter(1).value": "3000",  # Used Condition
        "paginationInput.entriesPerPage": "15"
    }

    try:
        res = requests.get(endpoint, headers=headers, params=params, timeout=5)
        data = res.json()
        items = data.get("findCompletedItemsResponse", [{}])[0].get("searchResult", [{}])[0].get("item", [])
        
        prices = []
        for item in items:
            price = float(item["sellingStatus"][0]["currentPrice"][0]["__value__"])
            prices.append(price)

        if prices:
            # Strip outliers (highest/lowest 10%)
            prices.sort()
            trimmed = prices[1:-1] if len(prices) > 3 else prices
            avg_price = sum(trimmed) / len(trimmed)
            return round(avg_price, 2)
    except Exception as e:
        st.sidebar.warning(f"eBay Live API Notice: Using market estimate ({e})")
    
    return None

# ------------------------------------------------------------------------------
# 4. GEMINI PART IDENTIFICATION ENGINE
# ------------------------------------------------------------------------------
def evaluate_vehicle_parts(year, make, model, trim, yard_key):
    """Uses Gemini to identify high-value flip targets and cross-reference with yard prices."""
    model_engine = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    You are an expert junkyard auto parts reseller on eBay.
    Analyze the following vehicle: {year} {make} {model} {trim}.
    
    List top 8 high-demand, high-profit electronic or fast-pull components on this specific vehicle.
    For each part, provide a structured JSON list containing:
    1. part_name: Common name of the part.
    2. category_key: One of ['apim', 'blind_spot', 'amp', 'bcm', 'pcm', 'tail_light', 'master_switch', 'hvac_panel', 'cluster', 'abs_module', 'radio_nav']
    3. est_avg_sold: Estimated eBay average sold price in USD ($).
    4. difficulty: Pull difficulty e.g. "Easy (5 mins)", "Moderate (15 mins)".
    5. tools_needed: Tools required e.g. "10mm socket, trim tool".
    6. notes: Location in car and key failure modes/reasons for demand.

    Return ONLY a valid JSON array of objects. No markdown formatting outside of ```json ``` block.
    """
    
    response = model_engine.generate_content(prompt)
    
    try:
        cleaned_text = re.sub(r'```json\s*|\s*```', '', response.text).strip()
        parts_data = json.loads(cleaned_text)
    except Exception as e:
        st.error(f"Error parsing Gemini response: {e}")
        return []

    # Process and enrich with local yard prices and eBay fees
    results = []
    for part in parts_data:
        category = part.get("category_key", "default")
        yard_cost, base_yard_price = calculate_local_yard_cost(category, yard_key)
        
        # Check live eBay price if available, otherwise use Gemini estimate
        live_ebay = fetch_ebay_sold_data(f"{year} {make} {model} {part['part_name']}")
        avg_sold = live_ebay if live_ebay else part.get("est_avg_sold", 100.0)
        
        # Standard eBay Profit Formula:
        # Net Profit = Avg Sold - Yard Cost - eBay Fee (13.25% + $0.30) - Est Shipping ($12.00)
        ebay_fee = (avg_sold * 0.1325) + 0.30
        est_shipping = 12.00
        net_profit = round(avg_sold - yard_cost - ebay_fee - est_shipping, 2)

        results.append({
            "part_name": part.get("part_name"),
            "yard_cost": yard_cost,
            "avg_sold": avg_sold,
            "net_profit": net_profit,
            "difficulty": part.get("difficulty"),
            "tools_needed": part.get("tools_needed"),
            "notes": part.get("notes")
        })

    return results

# ------------------------------------------------------------------------------
# 5. STREAMLIT FRONTEND USER INTERFACE
# ------------------------------------------------------------------------------
st.title("🚗 Junkyard Flip Calculator")
st.caption("Configured for Southeast Michigan Self-Serve Yards")

st.sidebar.header("Yard & Vehicle Options")

selected_yard = st.sidebar.selectbox(
    "Select Local Yard:",
    options=["pontiac", "sterling_heights"],
    format_func=lambda x: YARD_PRICING[x]["name"]
)

col1, col2, col3, col4 = st.columns(4)

with col1:
    year = st.text_input("Year", value="2015")
with col2:
    make = st.text_input("Make", value="Ford")
with col3:
    model = st.text_input("Model", value="Explorer")
with col4:
    trim = st.text_input("Trim (Optional)", value="Limited")

if st.button("Evaluate Vehicle Parts", type="primary"):
    with st.spinner(f"Analyzing {year} {make} {model} against {YARD_PRICING[selected_yard]['name']} pricing..."):
        results = evaluate_vehicle_parts(year, make, model, trim, selected_yard)
        
        if results:
            st.subheader(f"Recommended Pulls for {year} {make} {model}")
            st.caption(f"Yard Costs based on exact rates at **{YARD_PRICING[selected_yard]['name']}** (Includes 6% MI Sales Tax).")

            # Format data for display
            display_table = []
            for item in results:
                display_table.append({
                    "Part Name": item["part_name"],
                    "Yard Cost ($)": f"${item['yard_cost']:.2f}",
                    "Avg Sold Price ($)": f"${item['avg_sold']:.2f}",
                    "Net Profit ($)": f"${item['net_profit']:.2f}",
                    "Difficulty": item["difficulty"],
                    "Tools Needed": item["tools_needed"],
                    "Notes": item["notes"]
                })

            st.dataframe(display_table, use_container_width=True)
