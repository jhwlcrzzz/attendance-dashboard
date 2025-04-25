import streamlit as st
import pandas as pd
import os
import time # Keep for potential use elsewhere, but not for the main refresh loop
import matplotlib.pyplot as plt
from streamlit_gsheets import GSheetsConnection
from PIL import Image
# import io # Not explicitly used?
# import numpy as np # Not explicitly used?
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh # <--- IMPORT

# --- Configuration ---
# How often to rerun the Streamlit script (updates UI, checks for points)
APP_REFRESH_INTERVAL_SECONDS = 5 # e.g., rerun every 5 seconds
# How long to cache data from Google Sheets (reduces API calls)
DATA_CACHE_TTL_SECONDS = 4 # e.g., fetch new data only every 30 seconds max
# Lifespan for map points
GATE_POINT_LIFESPAN = 10 # Seconds

# Custom CSS to reduce spacing around title and elements
st.markdown("""     
<style>
    img[data-testid="stLogo"] {
            height: 3.5rem;
}        
    .block-container {
        padding-top: 2.3rem;
        padding-bottom: 0rem;
    }
    h1 {
        margin-top: -10px;
        margin-bottom: 0px;
    }
    div.stTitle {
        margin-bottom: -10px;
    }
    .stHeadingContainer {
        margin-top: 0px;
        margin-bottom: 0px;
    }
    .stSubheader {
        margin-bottom: -25px;
    }
    div[data-testid="stVerticalBlock"] > div:first-child {
        margin-top: 0px;
    }
    div.stElementContainer{
        margin-top: 0px;
        margin-bottom: 0px;    
    }
    
    /* Force main image size reduction */
    .main-img-wrapper img {
        max-width: 70% !important;
        margin-left: auto !important;
        margin-right: auto !important;
        display: block !important;
    }
</style>
""", unsafe_allow_html=True)

# --- Initialization ---
logo_path = os.path.join("sd", f"logo.jpg")
# Use try-except for potentially changing st.logo syntax or if file missing
try:
    if os.path.exists(logo_path):
        st.logo(logo_path) # Removed size="large", seems invalid param
except Exception:
    st.sidebar.warning("Logo image not found or st.logo error.")


# Initialize session state variables
if 'last_point_add_time' not in st.session_state: # Changed from last_refresh for clarity
    st.session_state.last_point_add_time = datetime.min
if 'gate_points' not in st.session_state:
    st.session_state.gate_points = []
# 'last_update_check' is no longer needed for the main refresh loop

# --- Page Config ---
st.set_page_config(page_title="Attendance Dashboard", page_icon=":signal_strength:", layout="wide")

# --- Auto-Refresh Component ---
# Run the autorefresh counter. Counts up indefinitely.
# The interval is in milliseconds, so multiply seconds by 1000.
# The key is optional but helpful if you have multiple autorefresh components.
refresh_count = st_autorefresh(interval=APP_REFRESH_INTERVAL_SECONDS * 1000, limit=None, key="dashboard_refresh")
st.sidebar.write(f"Dashboard Running (Refresh Count: {refresh_count})") # Show counter to verify it's running

# --- Custom CSS (Keep your existing CSS) ---
st.markdown("""
<style>
    /* ... (your existing CSS rules) ... */
     img[data-testid="stLogo"] { height: 3.5rem; }
     .block-container { padding-top: 1rem; padding-bottom: 0rem; }
     h1 { margin-top: -10px; margin-bottom: 10px; }
     .stSubheader { margin-bottom: 5px; margin-top: 10px; }
     .main-img-wrapper img { max-width: 70% !important; max-height: 350px; object-fit: contain; margin-left: auto !important; margin-right: auto !important; display: block !important; }
     /* Remove or fix the map image CSS if it was causing issues */
     /* [data-testid="stImage"] img { max-height: 720px; width: 10px; ... } */
</style>
""", unsafe_allow_html=True)

# --- Title ---
st.title("LORA RFID-BASED UNIVERSITY ATTENDANCE SYSTEM — Dashboard")

# --- Data Loading Function (Optimized) ---
@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS) # Use configured TTL
def load_data():
    """Fetches and processes data from Google Sheets."""
    st.sidebar.info(f"Fetching data from Google Sheet (Cache TTL: {DATA_CACHE_TTL_SECONDS}s)...")
    start_time = time.time()
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        # conn.reset() # <--- REMOVE THIS - Increases load, usually not needed
        df = conn.read(worksheet="Sheet1") # Ensure sheet name is correct

        if df.empty:
            st.warning("Sheet1 appears empty.")
            return pd.DataFrame(columns=["Timestamp", "Gate No.", "Identification No.", "Name"])

        # --- Column Handling ---
        required_cols = ["Timestamp", "Gate No.", "Identification No.", "Name"]
        actual_cols = df.columns.tolist()
        missing_cols = [col for col in required_cols if col not in actual_cols]
        if missing_cols:
             st.error(f"FATAL: Missing required columns in Sheet1: {missing_cols}.")
             return pd.DataFrame(columns=required_cols) # Return empty on critical error

        filtered_df = df[required_cols].copy()
        # --- End Column Handling ---

        # --- Type Conversions ---
        # Convert Timestamp, drop invalid rows
        initial_rows = len(filtered_df)
        filtered_df["Timestamp"] = pd.to_datetime(filtered_df["Timestamp"], errors='coerce')
        filtered_df.dropna(subset=["Timestamp"], inplace=True)
        if len(filtered_df) < initial_rows:
             st.warning(f"Dropped {initial_rows - len(filtered_df)} rows due to invalid Timestamps.")

        # Convert Gate No.
        filtered_df["Gate No."] = pd.to_numeric(filtered_df["Gate No."], errors='coerce').fillna(0).astype(int)
        # Convert ID to string
        filtered_df["Identification No."] = filtered_df["Identification No."].astype(str)
        # --- End Type Conversions ---

        # Sort by Timestamp DESCENDING
        if not filtered_df.empty:
            filtered_df = filtered_df.sort_values(by="Timestamp", ascending=False).reset_index(drop=True)

        end_time = time.time()
        st.sidebar.info(f"Data fetch successful ({end_time - start_time:.2f}s). DF shape: {filtered_df.shape}")
        return filtered_df

    except Exception as e:
        st.error(f"Error loading data: {e}")
        # import traceback # Uncomment for detailed stack trace in logs
        # traceback.print_exc()
        st.sidebar.error("Data fetch failed.")
        # Return empty DataFrame on error
        return pd.DataFrame(columns=["Timestamp", "Gate No.", "Identification No.", "Name"])

# --- Manual Refresh Function ---
# Still useful for immediate cache clear + fetch
def force_reload():
    st.cache_data.clear()
    st.rerun() # Rerun after clearing cache

# --- Load Data ---
# This now uses the cache correctly. It only runs the full function
# when the cache expires (DATA_CACHE_TTL_SECONDS) or is cleared by force_reload.
filtered_df = load_data()

# --- Layout ---
col1, col2, col3 = st.columns([8, 9, 5], gap='large')

with col1:
    st.subheader("Time-In / Time-Out Status")
    if not filtered_df.empty:
        # Using value_counts for potentially faster calculation if dataset grows
        id_counts = filtered_df['Identification No.'].value_counts()
        time_in_count = (id_counts % 2 != 0).sum() # Count IDs with odd appearances (currently IN)
        time_out_count = (id_counts % 2 == 0).sum() # Count IDs with even appearances (currently OUT)
        # This assumes the latest record determines current status for pie chart %
        # A more robust approach might need tracking pairs of entries per ID per day.

        # Create pie chart
        fig, ax = plt.subplots(figsize=(4, 3)) # Adjust size as needed
        labels = ['Inside', 'Outside']
        sizes = [time_in_count, time_out_count]
        colors = ['#7d171e','#c1ab43'] # Swapped colors: Maroon for Inside, Gold for Outside
        if sum(sizes) > 0: # Avoid division by zero if no data
            ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, colors=colors, pctdistance=0.80, explode=(0.05, 0.05))
        else:
             ax.pie([1], labels=['No Data'], colors=['lightgrey']) # Placeholder if no data
        ax.axis('equal')
        centre_circle = plt.Circle((0, 0), 0.60, fc='white')
        fig.gca().add_artist(centre_circle)
        st.pyplot(fig, use_container_width=True) # Let streamlit manage width

        st.metric("People inside the campus", len(id_counts))

    else:
        st.info("No attendance data loaded.")

    st.subheader("Latest Entries")
    # Use st.dataframe for potentially better display options
    st.table(filtered_df.head(4))

# --- COLUMN 2: Image Gallery ---
with col2:
    st.subheader("Recent Attendees")
    
    # Get unique IDs from latest records (up to 4)
    latest_ids = filtered_df["Identification No."].unique()[:4]
    
    # Container for the main (latest) image
    main_img_container = st.container()
    
    # Display the main image (most recent) with direct size control
    with main_img_container:
        if len(latest_ids) > 0:
            try:
                img_path = os.path.join("sd", f"{latest_ids[0]}.jpg")
                if os.path.exists(img_path):
                    # Wrap the image in a div with our custom CSS class
                    st.markdown('<div class="main-img-wrapper">', unsafe_allow_html=True)
                    st.image(img_path, caption=f"ID: {latest_ids[0]}", width=269)  # Explicitly set width
                    st.markdown('</div>', unsafe_allow_html=True)
                else:
                    st.write("Corrupted Data")
                    st.caption(f"ID: {latest_ids[0]}")
            except Exception as e:
                st.write("Corrupted Data")
                st.caption(f"ID: {latest_ids[0]}")
    
    # Container for the three smaller images
    small_img_row = st.columns(3)
    
    # Display up to 3 smaller images
    for i in range(min(3, len(latest_ids)-1)):
        with small_img_row[i]:
            try:
                img_path = os.path.join("sd", f"{latest_ids[i+1]}.jpg")
                if os.path.exists(img_path):
                    st.image(img_path, caption=f"ID: {latest_ids[i+1]}", use_container_width=True)
                else:
                    st.write("Corrupted Data")
                    st.caption(f"ID: {latest_ids[i+1]}")
            except Exception as e:
                st.write("Corrupted Data")
                st.caption(f"ID: {latest_ids[i+1]}")

# --- COLUMN 3: Image with plotted points ---
with col3:
    st.subheader("Gate Location Map")
    
    # Check for new gate entries
    if not filtered_df.empty:
        latest_timestamp = filtered_df.iloc[0]["Timestamp"]
        latest_gate = filtered_df.iloc[0]["Gate No."]
        
        # Dictionary to map gate numbers to coordinates (x, y)
        # Adjust these coordinates based on your image
        gate_coordinates = {
            2: (360, 100),
            3: (400, 260),
            4: (100, 230),
            5: (570, 1060),
            6: (560, 1120),
            7: (155, 1050),
            8: (150, 975)
        }
        
        # Add new point if it's a new entry
        current_time = datetime.now()
        if (latest_timestamp > st.session_state.last_refresh - timedelta(seconds=10)) and latest_gate in gate_coordinates:
            st.session_state.gate_points.append({
                "gate": latest_gate,
                "coordinates": gate_coordinates[latest_gate],
                "created_at": current_time
            })
            st.session_state.last_refresh = current_time

    # Remove points older than 1 second
    st.session_state.gate_points = [
        point for point in st.session_state.gate_points 
        if (datetime.now() - point["created_at"]).total_seconds() <= 1
    ]
    
    # Load the vertical image
    try:
        # Try to load the image
        if os.path.exists("dhvsu.jpg"):
            map_container = st.container()
            st.caption("Source: Google Maps")
            with map_container:
                # Create fixed-height container for the map
                map_height = 720  # Adjust this value to control the height
                
                map_image = Image.open("dhvsu.jpg")
                
                # Create a figure with controlled height
                fig, ax = plt.subplots(figsize=(4, 8))
                ax.imshow(map_image)
                
                # Plot all active points with bright violet color and larger size
                violet_color = '#00FF00'  # Bright violet color (Indigo)
                for point in st.session_state.gate_points:
                    x, y = point["coordinates"]
                    gate_num = point["gate"]
                    # Much larger marker size (20 instead of 10)
                    ax.plot(x, y, 'o', color=violet_color, markersize=8, alpha=.9)
                    # Bold text with larger font
                    ax.text(x+12, y+50, f"Gate{gate_num}", color='#000000', fontsize=8, bbox=dict(facecolor='#ffffff', alpha=0.69))
                
                ax.axis('off')  # Hide axes
                
                # Use a custom CSS hack to control the height
                st.markdown(f"""
                <style>
                    [data-testid="stImage"] img {{
                        max-height: {map_height}px;
                        width: 10px;
                        margin: auto;
                        display: block;
                    }}
                </style>
                """, unsafe_allow_html=True)
                
                st.pyplot(fig)
        else:
            st.error("Map image not found. Please upload 'dhvsu.jpg'")
            st.write("Corrupted Data")
            
    except Exception as e:
        st.error(f"Error displaying map: {str(e)}")
        st.write("Corrupted Data")

# --- Sidebar ---
# Manual refresh button still useful
st.sidebar.button("Refresh Data Now", on_click=force_reload, use_container_width=True)
# Display last fetch time using info from load_data return? No, load_data doesn't return time.
# Simplest is to just show when the page last reran via the component.
st.sidebar.write(f"Data cached for: {DATA_CACHE_TTL_SECONDS}s") # Info

# --- NO LONGER NEEDED: Old auto-refresh logic ---
# The st_autorefresh component handles the reruns now.
