import os
import json
import streamlit as st
import pandas as pd
from openai import OpenAI

# Page Config
st.set_page_config(page_title="Junkyard Flip Assistant", layout="wide")
st.title("🚗 Junkyard Part Picker AI")
st.write("Enter a vehicle to see the top high-profit, easy-to-pull parts for eBay flipping.")

# Sidebar for API Configuration
st.sidebar.header("Settings")
openai_api_key = st.sidebar.text_input("OpenAI API Key", type="password")

# --- MOCK EBAY DATA ENGINE ---
# This function simulates eBay API pricing while your Developer Account is pending approval.
# Once approved, you will replace this function with live calls to eBay's Browse API.
def get_mock_ebay_pricing(part_name, year, make, model):
    """Simulates real-time eBay sold prices and demand statistics."""
    return {
        "avg_sold_price": 75.00,
        "sell_through_rate": "High (85%)",
        "active_listings": 12,
        "sold_last_90_days": 45
    }

# --- MAIN LOGIC ---
with st.form("vehicle_form"):
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        year = st.text_input("Year", value="2005")
    with col2:
        make = st.text_input("Make", value="Acura")
    with col3:
        model = st.text_input("Model", value="TL")
    with col4:
        trim = st.text_input("Trim / Engine (Optional)", value="3.2L Base")
    
    submit = st.form_submit_button("Find High-Value Parts")

if submit:
    if not openai_api_key:
        st.error("Please enter your OpenAI API Key in the sidebar to run the analysis.")
    else:
        try:
            client = OpenAI(api_key=openai_api_key)
            
            with st.spinner("Analyzing platform architecture and identifying high-margin parts..."):
                system_prompt = """
                You are an expert auto parts liquidator specializing in self-serve junkyard flipping on eBay.
                When given a vehicle (Year, Make, Model, Trim), identify the top 10 candidate high-value OEM parts.

                Prioritize:
                1. High Profit Density: Lightweight/small relative to sell price (low shipping).
                2. Known High-Failure / High-Demand Parts: Modules (ECM, TCM, BCM), Climate Control Knobs, OEM Amps, Window Switches, Tail Lights, Cup Holders, Overhead Consoles, Instrument Clusters.
                3. Ease of Removal: Hand tool removal vs. heavy teardown.

                Return strictly raw JSON format (no markdown code blocks, no ```json formatting) matching this array schema:
                [
                  {
                    "part_name": "Part Name",
                    "est_yard_cost": 15,
                    "est_ebay_price": 120,
                    "est_net_profit": 85,
                    "difficulty": "Easy (5 mins)",
                    "tools_needed": "10mm socket, trim tool",
                    "notes": "Common failure point; high resale demand."
                  }
                ]
                """

                user_prompt = f"Identify top 10 eBay parts to pull for: {year} {make} {model} {trim}"

                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.2
                )

                # Parse JSON output
                raw_text = response.choices[0].message.content.strip()
                # Clean up formatting if model adds code fences
                if raw_text.startswith("```"):
                    raw_text = raw_text.split("```")[1]
                    if raw_text.startswith("json"):
                        raw_text = raw_text[4:]
                
                parts_data = json.loads(raw_text.strip())

                # Enrich each part with the (mocked) eBay market data
                for item in parts_data:
                    ebay_stats = get_mock_ebay_pricing(item["part_name"], year, make, model)
                    item["Market Demand"] = ebay_stats["sell_through_rate"]
                    item["Avg Sold Price ($)"] = f"${item['est_ebay_price']}"
                    item["Yard Cost ($)"] = f"${item['est_yard_cost']}"
                    item["Net Profit ($)"] = f"${item['est_net_profit']}"

                st.subheader(f"Top 10 Parts to Pull: {year} {make} {model}")
                
                # Convert to DataFrame for a clean visual table
                df = pd.DataFrame(parts_data)
                
                # Display clean table
                display_cols = ["part_name", "Yard Cost ($)", "Avg Sold Price ($)", "Net Profit ($)", "difficulty", "tools_needed", "notes"]
                st.dataframe(df[display_cols], use_container_width=True)

        except Exception as e:
            st.error(f"An error occurred: {e}")
