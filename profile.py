import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# --- Configuration ---
OKX_API_BASE = "https://www.okx.com/api/v5/"

# --- Helper Functions to Fetch Data ---

@st.cache_data(ttl=300) # Cache data for 5 minutes
def get_okx_data(currency: str):
    """
    Fetches options instrument data (including volume) and index price from OKX.
    Returns a DataFrame of options data and the current index price.
    """
    request_timeout = 15 # Seconds

    try:
        underlying_asset = f"{currency}-USD"

        # --- CORRECTED OPTIONS ENDPOINT: Use market/instruments for comprehensive data ---
        options_url = f"{OKX_API_BASE}market/instruments"
        options_params = {"instType": "OPTION", "uly": underlying_asset} # uly is underlying asset
        options_response = requests.get(options_url, params=options_params, timeout=request_timeout)
        options_response.raise_for_status() # Raise an exception for HTTP errors (like 4xx or 5xx)
        instrument_data = options_response.json().get("data", [])

        if not instrument_data:
            st.warning(f"No options data found for {currency} from OKX. Check the currency or API status.")
            return pd.DataFrame(), None

        df = pd.DataFrame(instrument_data)

        # OKX market/instruments specific parsing
        # instId example: BTC-USD-240329-70000-C
        # stk: Strike price (string)
        # optType: Option type ('C' for Call, 'P' for Put)
        # vol24h: 24h volume (string)
        # expTime: Expiration timestamp in milliseconds (string)

        df['instrument_name'] = df['instId']
        df['strike'] = pd.to_numeric(df['stk'], errors='coerce')
        df['option_type'] = df['optType'].apply(lambda x: 'call' if x == 'C' else 'put')
        df['volume_24h'] = pd.to_numeric(df['vol24h'], errors='coerce').fillna(0)
        
        # Convert expTime (milliseconds timestamp) to datetime
        df['expiration_date'] = pd.to_datetime(df['expTime'], unit='ms')

        # Filter for relevant columns and drop rows with invalid strike (if coerce failed)
        df = df[['instrument_name', 'strike', 'option_type', 'volume_24h', 'expiration_date']].dropna(subset=['strike'])
        
        # Get current index price (this endpoint was already correct)
        index_url = f"{OKX_API_BASE}market/index-tickers"
        index_params = {"instId": underlying_asset}
        index_response = requests.get(index_url, params=index_params, timeout=request_timeout)
        index_response.raise_for_status()
        index_price_data = index_response.json().get("data", [])
        
        index_price = None
        if index_price_data:
            index_price = float(index_price_data[0].get("idxPx"))

        return df, index_price

    except requests.exceptions.Timeout:
        st.error(f"Request to OKX API timed out after {request_timeout} seconds. "
                 f"This could be due to network issues, a slow connection, or OKX servers being unresponsive. Please try again.")
        return pd.DataFrame(), None
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching data from OKX: {e}. Please check the API status or your network.")
        return pd.DataFrame(), None
    except Exception as e:
        st.error(f"An unexpected error occurred during data processing: {e}. Please check the data format.")
        return pd.DataFrame(), None

# --- Streamlit Dashboard ---
st.set_page_config(layout="wide", page_title="Crypto Options Dashboard")

st.title("📊 Crypto Options Dashboard (via OKX API)")

st.markdown(
    """
    This dashboard visualizes crypto options data, plotting 24-hour volume by strike price 
    against the current asset index price. Data is sourced from the **OKX public API**.
    **Note:** This is aggregated data (24h volume in contracts) and not real-time tick data.
    """
)

# --- Sidebar Controls ---
st.sidebar.header("Controls")
selected_currency = st.sidebar.selectbox("Select Crypto:", ["BTC", "ETH"])

with st.spinner(f"Fetching {selected_currency} options data..."):
    options_df, index_price = get_okx_data(selected_currency)

if options_df.empty:
    st.info("No data available for the selected currency or an error occurred. Please try again later.")
else:
    # Get unique expiration dates
    # Ensure to get unique dates after conversion to datetime for consistent grouping
    expiration_dates = sorted(options_df['expiration_date'].dt.normalize().unique()) # Normalize to remove time component
    
    # Filter out past expiration dates for cleaner display
    current_date_floor = pd.Timestamp.now().floor('D')
    expiration_dates = [d for d in expiration_dates if d >= current_date_floor]

    if not expiration_dates:
        st.warning(f"No future expiration dates available for {selected_currency}.")
        st.stop() # Stop execution if no valid dates

    # Format for display
    expiration_options = {d.strftime('%Y-%m-%d'): d for d in expiration_dates}
    
    selected_expiration_str = st.sidebar.selectbox(
        "Select Expiration Date:",
        options=list(expiration_options.keys()),
        index=0 # Default to the first available future expiration
    )
    
    if selected_expiration_str:
        selected_expiration = expiration_options[selected_expiration_str]
        
        # Filter DataFrame by selected expiration (compare normalized dates)
        filtered_df = options_df[options_df['expiration_date'].dt.normalize() == selected_expiration].copy()

        if filtered_df.empty:
            st.warning(f"No options data for expiration {selected_expiration_str}. Please select another date.")
        else:
            # --- Plotting ---
            fig = go.Figure()

            # Add Asset Price Line (Primary Y-axis)
            if index_price:
                # Ensure strikes are within a reasonable range for the line
                # Handle cases where filtered_df might have no strikes (e.g., if all volume is 0)
                if not filtered_df.empty:
                    min_strike = filtered_df['strike'].min()
                    max_strike = filtered_df['strike'].max()
                else: # Fallback if no options in filtered_df, maybe use a default range
                    min_strike = index_price * 0.8
                    max_strike = index_price * 1.2

                fig.add_trace(go.Scatter(
                    x=[min_strike, max_strike],
                    y=[index_price, index_price],
                    mode='lines',
                    name=f'{selected_currency} Index Price',
                    line=dict(color='orange', dash='dash'),
                    yaxis='y1',
                    hoverinfo='name+y'
                ))
                st.sidebar.markdown(f"**Current {selected_currency} Index Price:** `{index_price:,.2f} USD`")
            else:
                st.sidebar.warning(f"Could not retrieve current {selected_currency} index price.")

            # Add Call Volume Bars (Secondary Y-axis)
            calls_df = filtered_df[filtered_df['option_type'] == 'call'].sort_values('strike')
            if not calls_df.empty:
                fig.add_trace(go.Bar(
                    x=calls_df['strike'],
                    y=calls_df['volume_24h'],
                    name='Call Volume (24h)',
                    marker_color='rgba(0, 150, 250, 0.6)', # Light blue
                    yaxis='y2',
                    hovertemplate='Strike: %{x}<br>Call Vol: %{y}<extra></extra>'
                ))

            # Add Put Volume Bars (Secondary Y-axis)
            puts_df = filtered_df[filtered_df['option_type'] == 'put'].sort_values('strike')
            if not puts_df.empty:
                fig.add_trace(go.Bar(
                    x=puts_df['strike'],
                    y=puts_df['volume_24h'],
                    name='Put Volume (24h)',
                    marker_color='rgba(255, 100, 100, 0.6)', # Light red
                    yaxis='y2',
                    hovertemplate='Strike: %{x}<br>Put Vol: %{y}<extra></extra>'
                ))

            # Update layout for dual Y-axes
            fig.update_layout(
                title=f'{selected_currency} Options Volume by Strike for {selected_expiration_str}',
                xaxis_title='Strike Price',
                yaxis=dict(
                    title=f'{selected_currency} Price (USD)',
                    titlefont=dict(color='orange'),
                    tickfont=dict(color='orange'),
                    side='left'
                ),
                yaxis2=dict(
                    title='24h Volume (Contracts)',
                    titlefont=dict(color='grey'),
                    tickfont=dict(color='grey'),
                    overlaying='y', # Crucial for secondary axis
                    side='right'
                ),
                legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.7)'),
                hovermode='x unified', # Shows all traces on hover for a given x-value
                height=600,
                template="plotly_dark" # Or "plotly_white" for a lighter theme
            )

            st.plotly_chart(fig, use_container_width=True)

            # Optional: Display raw data
            if st.checkbox("Show raw data"):
                st.subheader("Raw Data (Filtered)")
                st.dataframe(filtered_df)
    else:
        st.info("No expiration dates available for the selected currency.")
