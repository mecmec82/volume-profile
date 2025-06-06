import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# --- Configuration ---
DERIBIT_API_BASE = "https://www.deribit.com/api/v2/public/"

# --- Helper Functions to Fetch Data ---

@st.cache_data(ttl=300) # Cache data for 5 minutes to avoid hitting API too often
def get_deribit_data(currency: str):
    """
    Fetches options summary data and index price from Deribit.
    Returns a DataFrame of options data and the current index price.
    """
    # Define a timeout for the requests in seconds
    request_timeout = 15 # Give it 15 seconds to connect and receive the first byte

    try:
        # Get options book summaries
        summary_url = f"{DERIBIT_API_BASE}get_book_summary_by_currency"
        summary_params = {"currency": currency, "kind": "option"}
        summary_response = requests.get(summary_url, params=summary_params, timeout=request_timeout) # <--- ADDED TIMEOUT
        summary_response.raise_for_status() # Raise an exception for HTTP errors (like 4xx or 5xx)
        option_data = summary_response.json().get("result", [])

        if not option_data:
            st.warning(f"No options data found for {currency}.")
            return pd.DataFrame(), None

        df = pd.DataFrame(option_data)

        # Filter for relevant columns and clean data
        df = df[['instrument_name', 'strike', 'option_type', 'volume_24h', 'mark_price']]
        df['strike'] = pd.to_numeric(df['strike'])
        df['volume_24h'] = pd.to_numeric(df['volume_24h'])

        # Extract expiration date from instrument_name
        df['expiration_date_str'] = df['instrument_name'].apply(lambda x: x.split('-')[1])
        df['expiration_date'] = pd.to_datetime(df['expiration_date_str'], format='%d%b%y')

        # Get current index price
        index_url = f"{DERIBIT_API_BASE}get_index"
        index_params = {"currency": currency}
        index_response = requests.get(index_url, params=index_params, timeout=request_timeout) # <--- ADDED TIMEOUT
        index_response.raise_for_status()
        index_price = index_response.json().get("result", {}).get(f"{currency}_usd")

        return df, index_price

    # Catch specific timeout error
    except requests.exceptions.Timeout:
        st.error(f"Request to Deribit API timed out after {request_timeout} seconds. "
                 f"This could be due to network issues, a slow connection, or Deribit servers being unresponsive.")
        return pd.DataFrame(), None
    # Catch other request-related errors (e.g., HTTP errors, connection refused)
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching data from Deribit: {e}")
        return pd.DataFrame(), None
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        return pd.DataFrame(), None

# --- Rest of your Streamlit Dashboard code remains the same ---
st.set_page_config(layout="wide", page_title="Crypto Options Dashboard")

st.title("📊 Crypto Options Dashboard (via Deribit API)")

st.markdown(
    """
    This dashboard visualizes crypto options data, plotting 24-hour volume by strike price 
    against the current asset index price. Data is sourced from the Deribit public API.
    **Note:** This is aggregated data and not real-time tick data.
    """
)

# --- Sidebar Controls ---
st.sidebar.header("Controls")
selected_currency = st.sidebar.selectbox("Select Crypto:", ["BTC", "ETH"])

with st.spinner(f"Fetching {selected_currency} options data..."):
    options_df, index_price = get_deribit_data(selected_currency)

if options_df.empty:
    st.info("No data available for the selected currency or an error occurred. Please try again later.")
else:
    # Get unique expiration dates
    expiration_dates = sorted(options_df['expiration_date'].unique())
    # Format for display
    expiration_options = {d.strftime('%Y-%m-%d'): d for d in expiration_dates}
    
    selected_expiration_str = st.sidebar.selectbox(
        "Select Expiration Date:",
        options=list(expiration_options.keys()),
        index=0 if expiration_options else None # Default to first option if available
    )
    
    if selected_expiration_str:
        selected_expiration = expiration_options[selected_expiration_str]
        
        # Filter DataFrame by selected expiration
        filtered_df = options_df[options_df['expiration_date'] == selected_expiration].copy()

        if filtered_df.empty:
            st.warning(f"No options data for expiration {selected_expiration_str}. Please select another date.")
        else:
            # --- Plotting ---
            fig = go.Figure()

            # Add Asset Price Line (Primary Y-axis)
            if index_price:
                fig.add_trace(go.Scatter(
                    x=[filtered_df['strike'].min(), filtered_df['strike'].max()],
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
