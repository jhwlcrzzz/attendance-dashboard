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
DATA_CACHE_TTL_SECONDS = 30 # e.g., fetch new data only every 30 seconds max
# Lifespan for map points
GATE_POINT_LIFESPAN = 15 # Seconds

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

# --- COLUMN 1: Metrics, Pie Chart, Table ---
with col1:
    st.subheader("Campus Occupancy Status")
    if not filtered_df.empty:
        # Filter for relevant time period if necessary (e.g., today)
        # today_date = pd.to_datetime('today').normalize()
        # relevant_df = filtered_df[filtered_df['Timestamp'] >= today_date]
        # id_counts = relevant_df['Identification No.'].value_counts()
        # If sheet contains only relevant data, use filtered_df directly:
        id_counts = filtered_df['Identification No.'].value_counts()

        # Calculate counts
        people_inside_count = (id_counts % 2 != 0).sum()
        people_outside_count = (id_counts % 2 == 0).sum()
        total_unique_logged = len(id_counts)

        # Display Metrics
        st.metric("People Currently Inside", people_inside_count) # Corrected metric
        st.divider()

        # Pie Chart
        st.write("Inside/Outside Ratio")
        fig, ax = plt.subplots(figsize=(4, 3))
        labels = ['Inside', 'Outside']
        sizes = [people_inside_count, people_outside_count]
        colors = ['#7d171e','#c1ab43'] # Maroon=Inside

        if sum(sizes) > 0:
            ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, colors=colors, pctdistance=0.80, explode=(0.05, 0.05))
            ax.axis('equal')
            centre_circle = plt.Circle((0, 0), 0.60, fc='white')
            fig.gca().add_artist(centre_circle)
        else:
             ax.pie([1], labels=['No Data'], colors=['lightgrey'])
             ax.axis('equal')
        st.pyplot(fig, use_container_width=True)
    else:
        st.info("No attendance data loaded.")
        st.metric("People Currently Inside", 0)

    st.divider()
    st.subheader("Latest Entries")
    st.dataframe(filtered_df.head(5), use_container_width=True, hide_index=True) # Use dataframe

# --- COLUMN 2: Image Gallery ---
with col2:
    st.subheader("Recent Attendees")
    if not filtered_df.empty:
        # Get unique IDs from the most recent entries
        latest_unique_ids = filtered_df["Identification No."].unique()[:4]

        main_img_container = st.container()
        with main_img_container:
            if len(latest_unique_ids) > 0:
                main_id = latest_unique_ids[0]
                # Safely get name
                main_name_series = filtered_df.loc[filtered_df["Identification No."] == main_id, "Name"]
                main_name = main_name_series.iloc[0] if not main_name_series.empty else "Unknown"
                img_path = os.path.join("sd", f"{main_id}.jpg")
                try:
                    if os.path.exists(img_path):
                        # Rely on CSS for sizing, remove explicit width
                        st.markdown('<div class="main-img-wrapper">', unsafe_allow_html=True)
                        st.image(img_path, caption=f"{main_name} (ID: {main_id})")
                        st.markdown('</div>', unsafe_allow_html=True)
                    else:
                        st.warning(f"Image not found for {main_name} (ID: {main_id})")
                except Exception as e:
                    st.error(f"Error displaying image for ID {main_id}: {str(e)}")
            else:
                 st.info("No recent attendees to display.")

        # Smaller images
        if len(latest_unique_ids) > 1:
             st.markdown("---")
             num_small_images = min(3, len(latest_unique_ids) - 1)
             if num_small_images > 0:
                 small_img_row = st.columns(num_small_images)
                 for i in range(num_small_images):
                     with small_img_row[i]:
                         current_id = latest_unique_ids[i + 1]
                         current_name_series = filtered_df.loc[filtered_df["Identification No."] == current_id, "Name"]
                         current_name = current_name_series.iloc[0] if not current_name_series.empty else "Unknown"
                         img_path = os.path.join("sd", f"{current_id}.jpg")
                         try:
                             if os.path.exists(img_path):
                                 st.image(img_path, caption=f"{current_name} (ID: {current_id})", use_container_width=True)
                             else:
                                 st.warning(f"No img: {current_name} ({current_id})")
                         except Exception as e:
                             st.error(f"Error img ID {current_id}: {str(e)}")

# --- COLUMN 3: Gate Location Map ---
with col3:
    st.subheader("Gate Location Map")
    gate_coordinates = { # Make sure these are correct for dhvsu.jpg
        2: (360, 100), 3: (400, 260), 4: (100, 230),
        5: (570, 1060), 6: (560, 1120), 7: (155, 1050),
        8: (150, 975)
    }

    # --- Update Gate Points ---
    if not filtered_df.empty:
        latest_entry = filtered_df.iloc[0]
        latest_timestamp = latest_entry["Timestamp"]
        latest_gate = latest_entry["Gate No."]

        # Simplified logic: Add point if timestamp is newer than last added point's time
        # This assumes timestamps are strictly increasing for new events we care about
        if latest_gate in gate_coordinates and \
           (st.session_state.last_point_add_time is None or \
            latest_timestamp > st.session_state.last_point_add_time):

            st.session_state.gate_points.append({
                "gate": latest_gate,
                "coordinates": gate_coordinates[latest_gate],
                "timestamp": latest_timestamp,
                "created_at": datetime.now() # For lifespan tracking
            })
            st.session_state.last_point_add_time = latest_timestamp # Update last added time
            # Limit points stored
            st.session_state.gate_points = st.session_state.gate_points[-20:]

    # --- Remove Old Points ---
    now_for_points = datetime.now()
    st.session_state.gate_points = [
        point for point in st.session_state.gate_points
        if (now_for_points - point["created_at"]).total_seconds() <= GATE_POINT_LIFESPAN # Use constant
    ]

    # --- Display Map and Points ---
    map_image_path = "dhvsu.jpg"
    if os.path.exists(map_image_path):
        try:
            map_image = Image.open(map_image_path)
            aspect_ratio = map_image.height / map_image.width if map_image.width > 0 else 1.5 # Approximate aspect ratio
            fig_width = 5 # Adjust base width as needed
            fig_height = fig_width * aspect_ratio

            fig, ax = plt.subplots(figsize=(fig_width, fig_height))
            ax.imshow(map_image)

            point_color = '#00FF00' # Bright Green
            for point in st.session_state.gate_points:
                x, y = point["coordinates"]
                gate_num = point["gate"]
                ax.plot(x, y, 'o', color=point_color, markersize=10, alpha=0.8)
                ax.text(x + 15, y + 10, f"Gate {gate_num}", color='black', fontsize=9,
                        bbox=dict(facecolor='white', alpha=0.7, pad=0.2))

            ax.axis('off')
            fig.tight_layout(pad=0) # Reduce padding
            st.pyplot(fig, use_container_width=True)
            st.caption("Campus Map")

        except Exception as e:
            st.error(f"Error displaying map: {str(e)}")
    else:
        st.error(f"Map image not found at '{map_image_path}'")

# --- Sidebar ---
# Manual refresh button still useful
st.sidebar.button("Refresh Data Now", on_click=force_reload, use_container_width=True)
# Display last fetch time using info from load_data return? No, load_data doesn't return time.
# Simplest is to just show when the page last reran via the component.
 st.sidebar.write(f"Data cached for: {DATA_CACHE_TTL_SECONDS}s") # Info

# --- NO LONGER NEEDED: Old auto-refresh logic ---
# The st_autorefresh component handles the reruns now.
