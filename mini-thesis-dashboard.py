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
@st.cache_data(ttl=FULL_DATA_CACHE_TTL) # Cache definition remains
def fetch_full_attendance_data():
    """Fetches and processes the main attendance data from Sheet1 with debugging."""
    fetch_time = datetime.now()
    st.info(f"[FETCH_DATA] Attempting at {fetch_time.strftime('%H:%M:%S')}...") # DEBUG marker
    processed_df = pd.DataFrame(columns=["Timestamp", "Gate No.", "Identification No.", "Name"]) # Default empty
    try:
        conn_data = st.connection("gsheets", type=GSheetsConnection)
        # --- Ensure worksheet name is correct ---
        worksheet_to_read = "Sheet1" # <--- DOUBLE-CHECK THIS NAME
        st.write(f"[FETCH_DATA] Reading worksheet: '{worksheet_to_read}'") # DEBUG

        # Use short TTL for read during debug? Helps if sheet changes rapidly during test.
        df = conn_data.read(worksheet=worksheet_to_read, ttl=5)

        st.write(f"[FETCH_DATA] Initial read done. Shape: {df.shape}") # DEBUG
        if not df.empty:
             st.write("[FETCH_DATA] First 5 rows read:") # DEBUG
             st.dataframe(df.head()) # DEBUG - Show sample data read

        if df.empty:
             st.warning(f"[FETCH_DATA] Read operation returned an empty DataFrame from '{worksheet_to_read}'.")
             # Return the default empty df and time
             return processed_df, fetch_time

        # --- Column Name Verification ---
        required_cols = ["Timestamp", "Gate No.", "Identification No.", "Name"] # <--- DOUBLE-CHECK THESE HEADERS
        st.write(f"[FETCH_DATA] Expected columns: {required_cols}") # DEBUG
        actual_cols = df.columns.tolist()
        st.write(f"[FETCH_DATA] Actual columns found: {actual_cols}") # DEBUG

        missing_cols = [col for col in required_cols if col not in actual_cols]
        if missing_cols:
             # This is a critical error, data cannot be processed
             st.error(f"[FETCH_DATA] FATAL: Missing required columns in '{worksheet_to_read}': {missing_cols}. Please check Google Sheet header row.")
             return processed_df, fetch_time # Return default empty DF

        # Check for extra columns (optional, but good to know)
        extra_cols = [col for col in actual_cols if col not in required_cols]
        if extra_cols:
            st.write(f"[FETCH_DATA] Note: Found extra columns not used by dashboard: {extra_cols}") # DEBUG
        # --- End Column Verification ---

        filtered_df = df[required_cols].copy()

        # --- Timestamp Conversion ---
        st.write("[FETCH_DATA] Converting Timestamps...") # DEBUG
        initial_rows_ts = len(filtered_df)
        # Ensure the column exists before conversion
        if "Timestamp" in filtered_df.columns:
            filtered_df["Timestamp"] = pd.to_datetime(filtered_df["Timestamp"], errors='coerce')
            filtered_df.dropna(subset=["Timestamp"], inplace=True)
            rows_dropped_ts = initial_rows_ts - len(filtered_df)
            if rows_dropped_ts > 0:
                 st.warning(f"[FETCH_DATA] Dropped {rows_dropped_ts} rows due to invalid Timestamps.")
            st.write("[FETCH_DATA] Timestamp conversion done.") # DEBUG
        else:
            st.error("[FETCH_DATA] Timestamp column not found for conversion!") # Should have been caught above, but safe check
        # --- End Timestamp Conversion ---

        # --- Gate No. Conversion ---
        st.write("[FETCH_DATA] Converting Gate No...") # DEBUG
        if "Gate No." in filtered_df.columns:
             # Handle potential non-numeric values before converting to int
            filtered_df["Gate No."] = pd.to_numeric(filtered_df["Gate No."], errors='coerce').fillna(0).astype(int)
            st.write("[FETCH_DATA] Gate No. conversion done.") # DEBUG
        else:
             st.error("[FETCH_DATA] Gate No. column not found for conversion!")
        # --- End Gate No. Conversion ---

        if "Identification No." in filtered_df.columns:
            filtered_df["Identification No."] = filtered_df["Identification No."].astype(str)
        else:
             st.error("[FETCH_DATA] Identification No. column not found!")


        st.write(f"[FETCH_DATA] Data processing complete. Final DataFrame shape: {filtered_df.shape}") # DEBUG
        if filtered_df.empty and initial_rows_ts > 0:
             # Only warn if it started with rows and ended empty
             st.warning("[FETCH_DATA] Processed DataFrame is empty after cleaning/conversion steps, but started with data.")

        # Sort by Timestamp DESCENDING only if Timestamp column exists and DF not empty
        if "Timestamp" in filtered_df.columns and not filtered_df.empty:
            processed_df = filtered_df.sort_values(by="Timestamp", ascending=False).reset_index(drop=True)
        elif not filtered_df.empty:
             processed_df = filtered_df.reset_index(drop=True) # Keep data if timestamp missing, but don't sort
        # else processed_df remains the default empty one

        st.success("[FETCH_DATA] Function finished.") # Update status

        return processed_df, fetch_time # Return the processed (or empty) DF

    except Exception as e:
        st.error(f"[FETCH_DATA] Error during fetch/process for '{worksheet_to_read}': {e}")
        st.exception(e) # Show full traceback for debugging
        st.info("[FETCH_DATA] Data fetch/process failed.") # Update status
        # Return default empty DataFrame and current time on error
        return processed_df, fetch_time

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
# --- Check for Updates ---
current_time = datetime.now()
st.sidebar.markdown("--- Update Check ---") # Sidebar separator
st.sidebar.write(f"Current Time: {current_time.strftime('%H:%M:%S')}")
st.sidebar.write(f"Last Poll Time: {st.session_state.last_poll_time.strftime('%H:%M:%S')}")
st.sidebar.write(f"Check Interval: {POLLING_INTERVAL_SECONDS}s")

# Check if polling interval met
interval_met = (current_time - st.session_state.last_poll_time).total_seconds() >= POLLING_INTERVAL_SECONDS
st.sidebar.write(f"Polling Interval Met?: {interval_met}") # DEBUG

if interval_met:
    st.sidebar.write("--> Polling...") # DEBUG Indent
    st.session_state.last_poll_time = current_time # Update poll time

    actual_sheet_update_time = get_sheet_last_update_time()
    st.sidebar.write(f"--> Sheet Update Time (Read): {actual_sheet_update_time}") # DEBUG

    # Ensure we have a valid datetime object in session state for comparison
    last_known = st.session_state.last_known_sheet_update_time
    if not isinstance(last_known, datetime):
        st.sidebar.warning(f"--> Last known update time was invalid type ({type(last_known)}), resetting to min.") # DEBUG
        last_known = datetime.min
        st.session_state.last_known_sheet_update_time = last_known # Fix state

    st.sidebar.write(f"--> Last Known Update (State): {last_known}") # DEBUG

    # Perform comparison carefully
    needs_update = False # Default
    if isinstance(actual_sheet_update_time, datetime): # Check if read was successful
        try:
            needs_update = actual_sheet_update_time > last_known
        except TypeError:
             st.sidebar.error("--> Error comparing timestamps. Check types.") # DEBUG
             needs_update = True # Force update on comparison error?
    else:
        st.sidebar.error("--> Failed to get valid sheet update time for comparison.") # DEBUG

    st.sidebar.write(f"--> Needs Fetch? (Comparison): {needs_update}") # DEBUG

    if needs_update:
        st.sidebar.info("--> Change detected or initial load. Fetching full data...") # DEBUG
        # Clear cache before fetching (important)
        st.cache_data.clear()
        st.sidebar.write("--> Cache cleared.") # DEBUG

        # Call the data fetching function (which now has its own debug prints)
        new_df, fetch_time = fetch_full_attendance_data()

        # Update session state
        st.session_state.cached_dataframe = new_df
        st.session_state.last_known_sheet_update_time = actual_sheet_update_time
        st.session_state.full_data_last_fetch_time = fetch_time.strftime('%Y-%m-%d %H:%M:%S')
        st.session_state.latest_processed_timestamp_for_points = None # Reset point processor

        st.sidebar.success(f"--> Data fetch complete. Stored DF shape: {st.session_state.cached_dataframe.shape}") # DEBUG
        st.sidebar.write("--> Triggering immediate rerun.") # DEBUG
        st.rerun() # Rerun immediately to display the new data
    else:
        st.sidebar.write("--> No change detected in sheet timestamp. No fetch triggered.") # DEBUG
# else: # Optional debug for when interval NOT met
#    st.sidebar.write("Polling interval not yet met.")



# --- Assign data for display ---
# Always assign from session state AFTER the update check block
filtered_df = st.session_state.cached_dataframe
st.sidebar.markdown("--- Display ---")
st.sidebar.write(f"DataFrame for display shape: {filtered_df.shape}") # DEBUG outside condition
# --- End Check for Updates ---

# (Rest of your dashboard code using filtered_df...)

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
