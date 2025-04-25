import streamlit as st
import pandas as pd
import os
import time # Keep time for polling interval
import matplotlib.pyplot as plt
from streamlit_gsheets import GSheetsConnection
from PIL import Image
# import io # Not explicitly used?
# import numpy as np # Not explicitly used?
from datetime import datetime, timedelta
import traceback # For detailed error logging

# --- Constants ---
# How often to check the Google Sheet's 'Metadata' sheet for changes
POLLING_INTERVAL_SECONDS = 10
# Lifespan for the blinking dot on the map
GATE_POINT_LIFESPAN = 15 # Seconds
# Cache TTL for the *full data* (used only when a change is detected)
# Can be relatively short now, as it's only hit after a change.
FULL_DATA_CACHE_TTL = 60 # Seconds

MAP_IMAGE_PATH = "dhvsu.jpg"
LOGO_DIR = "sd"
IMAGE_DIR = "sd"

# --- Initialization ---
logo_path = os.path.join(LOGO_DIR, f"logo.jpg")
if os.path.exists(logo_path):
    # Check Streamlit version for st.logo syntax if needed
    try:
        st.logo(logo_path, size="large")

    
    except AttributeError:
        # Fallback for older Streamlit versions if st.logo doesn't exist
        # st.sidebar.image(logo_path) # Example fallback
        pass


# Initialize session state variables
if 'last_known_sheet_update_time' not in st.session_state:
    # Initialize to a very old datetime to ensure first load
    st.session_state.last_known_sheet_update_time = datetime.min
if 'latest_processed_timestamp_for_points' not in st.session_state:
    # Tracks the timestamp of the latest record used for map points
    st.session_state.latest_processed_timestamp_for_points = None
if 'gate_points' not in st.session_state:
    st.session_state.gate_points = []
if 'last_poll_time' not in st.session_state:
    # Tracks when we last checked the Metadata sheet
    st.session_state.last_poll_time = datetime.min
if 'full_data_last_fetch_time' not in st.session_state:
     st.session_state.full_data_last_fetch_time = "Never Fetched"
if 'cached_dataframe' not in st.session_state: # Store the DataFrame in session state
     st.session_state.cached_dataframe = pd.DataFrame(columns=["Timestamp", "Gate No.", "Identification No.", "Name"])

# --- Page Config ---
st.set_page_config(page_title="Attendance Dashboard", page_icon=":signal_strength:", layout="wide")

# --- Custom CSS (Keep your existing CSS) ---
st.markdown("""
<style>
    /* ... (your existing CSS rules) ... */
     .block-container {
         padding-top: 1rem;
         padding-bottom: 0rem;
     }
     h1 {
        margin-top: -10px;
        margin-bottom: 10px;
     }
     .stSubheader {
         margin-bottom: 5px;
         margin-top: 10px;
     }
     .main-img-wrapper img {
         max-width: 70% !important;
         max-height: 350px;
         object-fit: contain;
         margin-left: auto !important;
         margin-right: auto !important;
         display: block !important;
     }
</style>
""", unsafe_allow_html=True)

# --- Data Loading Functions ---

# Function to get ONLY the last update timestamp from the Metadata sheet


# Uses a very short cache or no cache to ensure frequent checking.
@st.cache_data(ttl=5) # Keep short TTL for frequent checks
def get_sheet_last_update_time():
    """Fetches and parses the timestamp from Metadata!A1 using the range parameter."""
    try:
        conn_meta = st.connection("gsheets", type=GSheetsConnection)
        # --- Use the read method confirmed working in the test script ---
        worksheet_name = "Metadata"
        cell_range_to_read = "A1"
        # Using ttl=0 in read() ensures we bypass streamlit-gsheets internal cache if any,
        # relying solely on the @st.cache_data(ttl=5) decorator above.
        meta_df = conn_meta.read(worksheet=worksheet_name, range=cell_range_to_read, header=None, ttl=0)
        # --- End specific read method ---

        # Check if DataFrame is empty OR if the specific cell value is None/NA
        # meta_df.iloc[0, 0] accesses the first cell (row 0, column 0)
        if meta_df.empty or pd.isna(meta_df.iloc[0, 0]):
             st.warning(f"Metadata sheet '{worksheet_name}' or cell '{cell_range_to_read}' appears empty or NA when read.")
             # Return a very old date so comparison triggers full load on first successful read
             return datetime.min
        else:
            # Attempt to parse the timestamp string
            timestamp_str = str(meta_df.iloc[0, 0])
            try:
                # pd.to_datetime is generally good at auto-detecting many formats,
                # including M/D/YYYY and those with time components from Apps Script new Date().
                parsed_time = pd.to_datetime(timestamp_str, errors='raise') # Use 'raise' to catch errors

                # Check if the parsed result is valid (not NaT)
                if pd.isna(parsed_time):
                    raise ValueError("Parsed timestamp is NaT (Not a Time)")

                # Return the valid parsed datetime object
                return parsed_time

            except ValueError as parse_error:
                 # Log a more persistent warning if parsing fails
                 st.warning(f"Could not parse timestamp '{timestamp_str}' from {worksheet_name}!{cell_range_to_read}. Error: {parse_error}. Change detection may be affected. Using fallback.")
                 # Return datetime.min as a safe fallback to avoid constant reloads due to parse errors
                 return datetime.min
                 
    except Exception as e:
        st.error(f"Error reading Metadata sheet: {e}. Please ensure '{worksheet_name}' sheet exists and check permissions/secrets.")
        # import traceback # Uncomment for detailed debug logs in console
        # traceback.print_exc()
        return datetime.min # Return old date on error



# Function to fetch the FULL data - cached for longer
@st.cache_data(ttl=FULL_DATA_CACHE_TTL)
def fetch_full_attendance_data():
    """Fetches and processes the main attendance data from Metadata."""
    fetch_time = datetime.now()
    st.sidebar.info(f"Fetching full data at {fetch_time.strftime('%H:%M:%S')}...") # Indicate fetch
    time.sleep(0.5) # Brief pause to make the message visible
    try:
        conn_data = st.connection("gsheets", type=GSheetsConnection)
        df = conn_data.read(worksheet="Metadata") # Assumes main data is on Metadata

        if df.empty:
             st.warning("Main data sheet (Metadata) appears empty.")
             return pd.DataFrame(columns=["Timestamp", "Gate No.", "Identification No.", "Name"]), fetch_time

        required_cols = ["Timestamp", "Gate No.", "Identification No.", "Name"]
        if not all(col in df.columns for col in required_cols):
             st.error(f"Missing required columns in Metadata. Need: {required_cols}")
             return pd.DataFrame(columns=required_cols), fetch_time

        filtered_df = df[required_cols].copy()
        # Convert Timestamp, handling potential errors
        filtered_df["Timestamp"] = pd.to_datetime(filtered_df["Timestamp"], errors='coerce')
        initial_rows = len(filtered_df)
        filtered_df.dropna(subset=["Timestamp"], inplace=True)
        if len(filtered_df) < initial_rows:
             st.warning(f"Dropped {initial_rows - len(filtered_df)} rows due to invalid Timestamps.")

        # Handle Gate No. conversion
        filtered_df["Gate No."] = pd.to_numeric(filtered_df["Gate No."], errors='coerce').fillna(0).astype(int)
        filtered_df["Identification No."] = filtered_df["Identification No."].astype(str)

        # Sort by Timestamp DESCENDING
        filtered_df = filtered_df.sort_values(by="Timestamp", ascending=False).reset_index(drop=True)

        st.sidebar.info("Data fetch complete.") # Clear fetch message

        return filtered_df, fetch_time

    except Exception as e:
        st.error(f"Error loading or processing attendance data: {e}")
        # traceback.print_exc() # Uncomment for detailed debug logs in console
        st.sidebar.info("Data fetch failed.") # Update status
        # Return empty DataFrame and current time on error
        return pd.DataFrame(columns=["Timestamp", "Gate No.", "Identification No.", "Name"]), fetch_time

# --- Main App Logic ---
st.title("LORA RFID-BASED UNIVERSITY ATTENDANCE SYSTEM — Dashboard")

# --- Check for Updates ---
# Periodically check the sheet's last modification time
current_time = datetime.now()
if (current_time - st.session_state.last_poll_time).total_seconds() >= POLLING_INTERVAL_SECONDS:
    st.session_state.last_poll_time = current_time # Update poll time regardless of outcome

    # Get the timestamp stored in the Metadata sheet
    actual_sheet_update_time = get_sheet_last_update_time()

    # Compare with the last known update time
    if actual_sheet_update_time > st.session_state.last_known_sheet_update_time:
        st.success(f"Change detected in Google Sheet at {actual_sheet_update_time.strftime('%H:%M:%S')}. Reloading data.")
        # Clear the cache for the *full data fetching function* specifically
        # Note: st.cache_data doesn't have a simple way to clear *one* function's cache.
        # Clearing all cache associated with @st.cache_data:
        st.cache_data.clear()

        # Fetch the updated full data
        new_df, fetch_time = fetch_full_attendance_data()

        # Update session state
        st.session_state.cached_dataframe = new_df # Store the latest data
        st.session_state.last_known_sheet_update_time = actual_sheet_update_time
        st.session_state.full_data_last_fetch_time = fetch_time.strftime('%Y-%m-%d %H:%M:%S')
        # Reset the point processor timestamp to ensure new points are added
        st.session_state.latest_processed_timestamp_for_points = None
        # Rerun immediately to display the new data
        st.rerun()
    # else:
        # Optional: Indicate that no change was detected
        # st.sidebar.write(f"Checked at {current_time.strftime('%H:%M:%S')}: No change detected.")

# Use the DataFrame stored in session state for the dashboard display
filtered_df = st.session_state.cached_dataframe

# --- Layout Columns ---
col1, col2, col3 = st.columns([8, 9, 5], gap='large')

# --- Column 1: Metrics, Pie Chart, and Table ---
with col1:
    st.subheader("Campus Occupancy Status") # Changed subheader
    if not filtered_df.empty:
        # --- IMPORTANT CAVEAT ---
        # For the "Currently Inside" count to be accurate for *today*,
        # ensure 'filtered_df' only contains relevant entries (e.g., entries from today).
        # If your sheet contains historical data, you might need to filter `filtered_df` by date first:
        # Example: today_date = pd.to_datetime('today').normalize() # Get today's date
        # Example: relevant_df = filtered_df[filtered_df['Timestamp'] >= today_date]
        # Example: id_counts = relevant_df['Identification No.'].value_counts()
        # If your sheet *only* has today's data or relevant logs, you can use filtered_df directly.

        # Calculate counts based on the relevant data
        id_counts = filtered_df['Identification No.'].value_counts() # Use relevant_df if filtered by date

        # Calculate number of people presumed inside (odd number of logs)
        people_inside_count = (id_counts % 2 != 0).sum()

        # Calculate number of people presumed outside (even number of logs for those who entered today)
        # Note: This counts people who entered *and* left today/within the data scope.
        people_outside_count = (id_counts % 2 == 0).sum()

        # Total unique individuals logged within the data scope
        total_unique_logged = len(id_counts)

        # --- Display Metrics ---
        st.metric("People Currently Inside Campus", people_inside_count)
        # You could add other metrics if useful
        # st.metric("People Logged Out (Today)", people_outside_count)
        # st.metric("Total Unique Individuals Logged (Today)", total_unique_logged)
        st.divider() # Add a visual separator

        # --- Create Pie Chart (Optional but still useful visual) ---
        st.write("Inside/Outside Ratio") # Add a small title for the chart
        fig, ax = plt.subplots(figsize=(4, 3)) # Adjust size as needed
        labels = ['Inside', 'Outside']
        # Use the calculated counts for the pie chart
        sizes = [people_inside_count, people_outside_count]
        colors = ['#7d171e','#c1ab43'] # Maroon = Inside, Gold = Outside

        if sum(sizes) > 0:
            ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, colors=colors, pctdistance=0.80, explode=(0.05, 0.05))
            ax.axis('equal')
            centre_circle = plt.Circle((0, 0), 0.60, fc='white')
            fig.gca().add_artist(centre_circle)
        else:
             # Placeholder if no data
             ax.pie([1], labels=['No Data'], colors=['lightgrey'])
             ax.axis('equal')

        st.pyplot(fig, use_container_width=True)

    else:
        st.info("No attendance data available.")
        st.metric("People Currently Inside Campus", 0) # Show 0 if no data

    st.subheader("Latest Entries")
    st.dataframe(filtered_df.head(4))

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

# --- Column 3: Gate Location Map ---
with col3:
    st.subheader("Gate Activity Map")
    gate_coordinates = {
        2: (360, 100), 3: (400, 260), 4: (100, 230),
        5: (570, 1060), 6: (560, 1120), 7: (155, 1050),
        8: (150, 975)
    }

    # --- Update Gate Points (using data from session state) ---
    if not filtered_df.empty:
        latest_entry = filtered_df.iloc[0]
        latest_timestamp = latest_entry["Timestamp"]
        latest_gate = latest_entry["Gate No."]

        # Check if this entry's timestamp is newer than the last one processed *for points*
        if latest_gate in gate_coordinates and \
           (st.session_state.latest_processed_timestamp_for_points is None or \
            latest_timestamp > st.session_state.latest_processed_timestamp_for_points):

            st.session_state.gate_points.append({
                "gate": latest_gate,
                "coordinates": gate_coordinates[latest_gate],
                "timestamp": latest_timestamp, # Store actual event time
                "created_at": datetime.now() # For lifespan tracking
            })
            st.session_state.latest_processed_timestamp_for_points = latest_timestamp
            # Optional: Limit the total number of points stored
            st.session_state.gate_points = st.session_state.gate_points[-20:] # Keep last 20 points

    # --- Remove Old Points ---
    now_for_points = datetime.now()
    st.session_state.gate_points = [
        point for point in st.session_state.gate_points
        if (now_for_points - point["created_at"]).total_seconds() <= GATE_POINT_LIFESPAN
    ]

    # --- Display Map and Points ---
    if os.path.exists(MAP_IMAGE_PATH):
        try:
            map_image = Image.open(MAP_IMAGE_PATH)
            aspect_ratio = map_image.height / map_image.width if map_image.width > 0 else 1
            fig_width = 5
            fig_height = fig_width * aspect_ratio
            fig, ax = plt.subplots(figsize=(fig_width, fig_height))
            ax.imshow(map_image)

            point_color = '#00FF00' # Bright Green
            for point in st.session_state.gate_points:
                x, y = point["coordinates"]
                gate_num = point["gate"]
                ax.plot(x, y, 'o', color='#00FF00', markersize=16, alpha=.9)
                ax.text(x+12, y+50, f"Gate{gate_num}", color='#000000', fontsize=23, 
                        bbox=dict(facecolor='#ffffff', alpha=0.69))

            ax.axis('off')
            fig.tight_layout(pad=0)
            st.pyplot(fig, use_container_width=True)
            st.caption("DHVSU Campus Map") # Adjust source if needed

        except Exception as e:
            st.error(f"Error displaying map: {str(e)}")
            # traceback.print_exc() # Uncomment for detailed debug logs
    else:
        st.error(f"Map image not found at '{MAP_IMAGE_PATH}'")


# --- Sidebar ---
# Manual Refresh Button (still useful for troubleshooting or forcing a check)
if st.sidebar.button("Check for Updates Now", use_container_width=True):
    st.cache_data.clear() # Clear cache on manual check
    st.session_state.last_known_sheet_update_time = datetime.min # Force re-check
    st.rerun()

st.sidebar.write(f"Sheet Last Update: {st.session_state.last_known_sheet_update_time.strftime('%Y-%m-%d %H:%M:%S') if isinstance(st.session_state.last_known_sheet_update_time, datetime) else 'Unknown'}")
st.sidebar.write(f"Data Last Fetched: {st.session_state.full_data_last_fetch_time}")
st.sidebar.write(f"Last Checked: {st.session_state.last_poll_time.strftime('%H:%M:%S')}")


# --- Auto-Polling Trigger ---
# This ensures the check runs periodically without user interaction
# This replaces the simple auto-refresh st.rerun() loop at the end.
# We trigger the check within the main logic block based on POLLING_INTERVAL_SECONDS
# We need a mechanism to force Streamlit to rerun periodically to *enable* the check.
# Use st.empty() and time.sleep() in a loop at the very end for background polling trigger.

# Placeholder at the end of the script to trigger reruns for polling
# Note: time.sleep() blocks execution, so the polling interval effectively becomes
# POLLING_INTERVAL_SECONDS + script execution time. Adjust interval if needed.
placeholder = st.empty()
with placeholder:
    time.sleep(POLLING_INTERVAL_SECONDS) # Wait for the polling interval
    st.rerun() # Trigger a rerun to perform the check at the top
