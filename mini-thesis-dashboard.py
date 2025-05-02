import streamlit as st
import pandas as pd
import os
import time
import matplotlib.pyplot as plt
from streamlit_gsheets import GSheetsConnection
from PIL import Image
# import io    # Not directly used in snippet below
import numpy as np
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh
import gspread # <--- Import gspread
from google.oauth2.service_account import Credentials # <--- For gspread auth

# --- Configuration ---
DATA_CACHE_TTL_SECONDS = 6
APP_REFRESH_INTERVAL_SECONDS = 6
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1k-QHlzi96V0RBRP0lOnRG6S4AIsz-e6N4hKjY1enrW8/edit?gid=0#gid=0"

# Simple check to ensure the placeholder was replaced
if "YOUR_FULL_GOOGLE_SHEET_URL_HERE" in GOOGLE_SHEET_URL or not GOOGLE_SHEET_URL.startswith("https"):
     st.error("Please replace 'YOUR_FULL_GOOGLE_SHEET_URL_HERE' in the code with your actual Google Sheet URL.")
     st.stop() # Stop execution if URL wasn't set

# --- gspread Authentication Function ---
def authenticate_gspread():
    """Authenticates gspread using Streamlit secrets."""
    try:
        creds_dict = st.secrets["connections"]["gsheets"]
        # Define the necessary scopes
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file", # Needed to potentially discover spreadsheets by name/list files
        ]
        # Create credentials object. Ensure secrets keys match JSON key file.
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=scopes
        )
        # Authorize gspread client
        gc = gspread.authorize(creds)
        return gc
    except KeyError:
        st.error("Gspread authentication failed: Ensure 'connections.gsheets' section with service account details exists in Streamlit Secrets.")
        return None
    except Exception as e:
        st.error(f"Gspread authentication error: {e}")
        return None

# --- Archive and Clear Function ---
def archive_and_clear():
    """Copies Sheet1 data to a date-named sheet, then clears Sheet1."""
    today_str = datetime.now().strftime("%b-%d-%Y") # Format: MonthAbbr-Day-Year (e.g., May-02-2025)
    new_sheet_name = f"Attendance_{today_str}"
    source_sheet_name = "Sheet1"

    st.sidebar.info(f"Starting archive process for {today_str}...")

    # 1. Authenticate gspread
    gc = authenticate_gspread()
    if not gc:
        st.sidebar.error("Aborting archive: Authentication failed.")
        return # Stop if authentication fails

    try:
        # 2. Open the spreadsheet
        st.sidebar.info(f"Opening spreadsheet...")
        # Use the URL or ID stored earlier
        spreadsheet = gc.open_by_url(GOOGLE_SHEET_URL) # Or gc.open_by_key(SPREADSHEET_ID)

        # 3. Check if archive sheet already exists
        existing_sheets = [sheet.title for sheet in spreadsheet.worksheets()]
        if new_sheet_name in existing_sheets:
            st.sidebar.warning(f"Sheet '{new_sheet_name}' already exists. Skipping archive.")
            # Optionally, you could add logic here to overwrite or append if desired
            return # Stop if sheet exists

        # 4. Read data from Sheet1 (using gspread for a fresh read)
        st.sidebar.info(f"Reading data from '{source_sheet_name}'...")
        try:
            source_sheet = spreadsheet.worksheet(source_sheet_name)
            data_to_archive = source_sheet.get_all_values() # Get list of lists (includes header)
            if not data_to_archive: # Check if sheet is empty (only header or truly empty)
                 st.sidebar.warning(f"'{source_sheet_name}' is empty or contains no data to archive.")
                 return # Nothing to archive
        except gspread.WorksheetNotFound:
            st.sidebar.error(f"Source sheet '{source_sheet_name}' not found. Aborting.")
            return

        # 5. Create the new sheet
        st.sidebar.info(f"Creating new sheet '{new_sheet_name}'...")
        # Get dimensions from the data read
        num_rows = len(data_to_archive)
        num_cols = len(data_to_archive[0]) if num_rows > 0 else 1 # Handle empty header case
        archive_sheet = spreadsheet.add_worksheet(title=new_sheet_name, rows=str(num_rows + 5), cols=str(num_cols + 2)) # Add some buffer rows/cols

        # 6. Write data to the new sheet
        st.sidebar.info(f"Writing data to '{new_sheet_name}'...")
        # 'A1' notation is commonly used for the top-left cell
        archive_sheet.update('A1', data_to_archive, value_input_option='USER_ENTERED') # Write data

        # 7. Clear Sheet1 using clear() and rewrite header
        st.sidebar.info(f"Clearing data from '{source_sheet_name}' (keeping header)...")
        try:
            # Ensure we have the source_sheet object
            source_sheet = spreadsheet.worksheet(source_sheet_name)

            # Get header values from the first row BEFORE clearing
            header_values = source_sheet.row_values(1)
            st.sidebar.info("Retrieved header row values.")

            if header_values: # Proceed only if header was actually retrieved
                 # Clear the entire sheet (removes all values and formatting)
                 source_sheet.clear()
                 st.sidebar.info(f"Cleared all content and formatting from '{source_sheet_name}'.")

                 # Rewrite the header row back into the first row (A1 notation range is automatic for single list)
                 source_sheet.update('A1', [header_values], value_input_option='USER_ENTERED')
                 st.sidebar.info(f"Rewrote header into '{source_sheet_name}'.")

                 # Optional: Re-apply basic formatting like bold to the header if desired
                 # Note: This might also depend on gspread version/utils availability
                 try:
                      last_header_col = gspread.utils.rowcol_to_a1(1, len(header_values))[:-1] # Get letter like 'D' from 'D1'
                      source_sheet.format(f'A1:{last_header_col}1', {'textFormat': {'bold': True}})
                      st.sidebar.info("Re-applied bold format to header.")
                 except AttributeError:
                     st.sidebar.warning("Could not auto-bold header: function potentially missing in gspread.utils.")
                 except Exception as fmt_e:
                     st.sidebar.warning(f"Could not auto-bold header: {fmt_e}")

            else:
                 st.sidebar.warning(f"Could not retrieve header from '{source_sheet_name}'. Sheet not cleared to prevent header loss.")
                 # Optional: Decide if you should proceed with other steps like cache clearing
                 # For safety, let's prevent further action if header couldn't be saved
                 return # Stop the archive process here

        except gspread.WorksheetNotFound:
            st.sidebar.error(f"Source sheet '{source_sheet_name}' not found during clearing step.")
            raise # Re-raise to be caught by the outer try/except block
        except Exception as clear_error:
             st.sidebar.error(f"Error during clearing/header rewrite of '{source_sheet_name}': {clear_error}")
             raise # Re-raise

        # ... (Step 8: Clear Streamlit cache, Step 9: Reset state - these run only if clear succeeds) ...

        # 8. Clear Streamlit cache to reflect the change
        st.sidebar.info("Clearing Streamlit cache...")
        st.cache_data.clear()

        # 9. Reset relevant session state
        if 'inside_ids' in st.session_state:
             del st.session_state['inside_ids']
        if 'gate_points' in st.session_state: # Also clear map points? Optional.
             st.session_state.gate_points = []

        st.sidebar.success(f"Archive complete! Data saved to '{new_sheet_name}' and '{source_sheet_name}' cleared.")
        # No st.rerun() needed here, Streamlit handles it after callback

    except gspread.exceptions.APIError as api_e:
         st.sidebar.error(f"Google API Error during archive: {api_e}")
    except Exception as e:
        st.sidebar.error(f"An unexpected error occurred during archive: {e}")
        import traceback
        st.sidebar.text(traceback.format_exc())




logo_path = os.path.join("sd", f"logo.jpg")
st.logo(logo_path, size="large")

# Initialize session state variables
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = datetime.now()
if 'gate_points' not in st.session_state:
    st.session_state.gate_points = []



# ... (Initialize session state - remove last_update_check if using st_autorefresh) ...
# Keep inside_ids if you implemented that logic
if 'inside_ids' not in st.session_state:
    st.session_state.inside_ids = {}




# Page configuration
st.set_page_config(page_title="Attendace Dashboard", page_icon=":signal_strength:", layout="wide")

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

# More compact title and divider
st.title("LORA RFID-BASED UNIVERSITY ATTENDANCE SYSTEM — Dashboard")
#st.divider()


# --- Auto-Refresh (Use st autorefresh if possible for Cloud) ---
# If using st autorefresh:
refresh_count = st_autorefresh(interval=APP_REFRESH_INTERVAL_SECONDS * 1000, limit=None, key="dashboard_refresh")
#st.sidebar.write(f"Dashboard Auto-Refreshing (Count: {refresh_count})")


# Modified cache data function with shorter TTL and error handling
# --- Data Loading Function (Optimized) ---
@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS) # Make sure DATA_CACHE_TTL_SECONDS is defined (e.g., 10)
def load_data():
    # This log appears ONLY when the function *actually* executes (cache miss)
    #st.sidebar.warning(f"!!! RUNNING load_data() - CACHE MISS at {datetime.now().strftime('%H:%M:%S')} !!!")
    processed_df = pd.DataFrame(columns=["Timestamp", "Gate No.", "Identification No.", "Name"])
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        # conn.reset() # REMOVED - Avoid this

        worksheet_to_read = "Sheet1" # Ensure correct name
        #st.sidebar.info(f"[load_data] Reading '{worksheet_to_read}' via conn.read(ttl=5)...")

        # Explicitly set short TTL for the gsheets connection read itself
        df = conn.read(worksheet=worksheet_to_read, ttl=5)

        #st.sidebar.info(f"[load_data] Raw data read shape: {df.shape}") # Log raw shape
        # Optional: Show head of raw data read - uncomment carefully if needed
        # if not df.empty: st.sidebar.dataframe(df.head(2))

        if df.empty:
            st.sidebar.warning(f"[load_data] Read returned empty DataFrame from '{worksheet_to_read}'.")
            return processed_df # Return default empty

        # --- Column Handling & Type Conversion ---
        required_cols = ["Timestamp", "Gate No.", "Identification No.", "Name"] # Ensure exact match
        #st.sidebar.info(f"[load_data] Expected cols: {required_cols}")
        actual_cols = df.columns.tolist()
        #st.sidebar.info(f"[load_data] Actual cols: {actual_cols}")

        missing_cols = [col for col in required_cols if col not in actual_cols]
        if missing_cols:
             #st.sidebar.error(f"[load_data] FATAL: Missing required columns: {missing_cols}.")
             return processed_df

        filtered_df = df[required_cols].copy()
        initial_rows = len(filtered_df)

        # Convert Timestamp (Keep this as is)
        if "Timestamp" in filtered_df.columns:
            filtered_df["Timestamp"] = pd.to_datetime(filtered_df["Timestamp"], errors='coerce')
            filtered_df.dropna(subset=["Timestamp"], inplace=True)
            # ... (optional logging) ...
        else:
            st.sidebar.error("[load_data] Timestamp column missing!")
        
        # Convert Gate No. (Keep this as is)
        if "Gate No." in filtered_df.columns:
            filtered_df["Gate No."] = pd.to_numeric(filtered_df["Gate No."], errors='coerce').fillna(0).astype(int)
        else:
            st.sidebar.error("[load_data] Gate No. column missing!")
        
        # --- CORRECT Identification No. Handling ---
        if "Identification No." in filtered_df.columns:
            # 1. Convert to string FIRST to handle mixed types directly
            id_series_str = filtered_df["Identification No."].astype(str)

            # 2. Optional: Remove leading/trailing whitespace
            id_series_stripped = id_series_str.str.strip()

            # 3. *** ADDED STEP: Remove trailing ".0" if it exists ***
            # This handles cases where purely numeric IDs were read as floats
            # and converted to strings like "##########.0".
            # The regex '\.0$' matches a literal dot '.', then a '0', only at the end ('$') of the string.
            id_series_cleaned = id_series_stripped.str.replace(r'\.0$', '', regex=True)

            # 4. Assign the cleaned series back
            filtered_df["Identification No."] = id_series_cleaned

            # 5. Optional: Log if any are now empty
            if (filtered_df["Identification No."] == "").any():
                 st.sidebar.warning("[load_data] Found empty strings in Identification No. after processing.")
            # st.sidebar.info("[load_data] Identification No. processed AS STRING and cleaned.") # Confirmation log
        else:
             st.sidebar.error("[load_data] Identification No. column is missing!")
        # --- End CORRECT Identification No. Handling ---

        #if filtered_df.empty and initial_rows > 0:
             #st.sidebar.warning("[load_data] Processed DataFrame empty after cleaning.")

        if "Timestamp" in filtered_df.columns and not filtered_df.empty:
            processed_df = filtered_df.sort_values(by="Timestamp", ascending=False).reset_index(drop=True)
        elif not filtered_df.empty:
             processed_df = filtered_df.reset_index(drop=True)

        #st.sidebar.success(f"[load_data] OK. Processed shape: {processed_df.shape}")
        return processed_df

    except Exception as e:
        #st.sidebar.error(f"!!! ERROR in load_data: {e}") # Log specific error
        import traceback
        # Print full error traceback to sidebar for debugging
        st.sidebar.text(traceback.format_exc())
        return processed_df # Return default empty on error



# --- Manual Refresh Function ---
def force_reload():
    # Clear specific caches if possible, otherwise clear all
    st.cache_data.clear() # Clears all @st.cache_data
    st.sidebar.info("Cache cleared.") # Optional: Feedback

    # Clear session state related to counts if needed
    if 'inside_ids' in st.session_state:
        st.sidebar.info("Resetting 'inside' status.") # Optional: Feedback
        del st.session_state['inside_ids'] # Reset count state on manual refresh


filtered_df = load_data()

# Create three columns for layout
col1, col2, col3 = st.columns([8, 9, 5], gap='large')

# --- COLUMN 1: Pie Chart and Table ---
with col1:
    st.subheader("Time-In / Time-Out Status")
    if not filtered_df.empty:
        # --- IMPORTANT CAVEAT ---
        # This calculation assumes 'filtered_df' contains ONLY the entries
        # relevant for determining current in/out status (e.g., all entries
        # from today, or since the campus opened). If it contains old data,
        # the odd/even count might be incorrect for "currently inside".
        # You might need to filter filtered_df by date before calculating id_counts
        # if your Google Sheet accumulates data over multiple days.
        # Example (uncomment and adapt if needed):
        # today_date = pd.to_datetime('today', utc=True).normalize() # Get today's date UTC
        # # Assuming 'Timestamp' column is timezone-aware UTC or convert it
        # # filtered_df['Timestamp'] = filtered_df['Timestamp'].dt.tz_convert('UTC') # Example conversion
        # relevant_df = filtered_df[filtered_df['Timestamp'] >= today_date]
        # id_counts = relevant_df['Identification No.'].value_counts()

        # If sheet only contains relevant data, use filtered_df directly:
        id_counts = filtered_df['Identification No.'].value_counts()

        # Correctly calculates IDs with an odd number of entries (presumed inside)
        time_in_count = (id_counts % 2 != 0).sum()
        # Correctly calculates IDs with an even number of entries (presumed outside)
        time_out_count = (id_counts % 2 == 0).sum()

        # --- Create Pie Chart ---
        fig, ax = plt.subplots(figsize=(4, 3)) # Adjust size as needed
        labels = ['Inside', 'Outside']
        sizes = [time_in_count, time_out_count] # Use correct counts
        colors = ['#7d171e','#c1ab43'] # Maroon for Inside, Gold for Outside
        if sum(sizes) > 0: # Avoid division by zero if no data
            ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, colors=colors, pctdistance=0.80, explode=(0.05, 0.05))
        else:
             ax.pie([1], labels=['No Data'], colors=['lightgrey']) # Placeholder if no data
        ax.axis('equal')
        centre_circle = plt.Circle((0, 0), 0.60, fc='white')
        fig.gca().add_artist(centre_circle)
        st.pyplot(fig, use_container_width=True) # Let streamlit manage width

        # --- CORRECTED METRIC ---
       # --- Custom CSS Injection ---
        st.markdown("""
        <style>
        /* Target the main container of each metric */
        div[data-testid="stMetric"] {
            background-color: #FFFFFF;
            border: 1px solid #CCCCCC;
            padding: 10px 15px; /* Adjusted padding */
            border-radius: 5px;
            color: #000000; /* Default text color inside */
        }
        
        /* Target the label text specifically */
        div[data-testid="stMetricLabel"] {
            color: #333333 !important; /* Dark grey label */
            font-size: 0.95em; /* Slightly smaller label */
        }
        
        /* Target the value text specifically */
        div[data-testid="stMetricValue"] {
            color: #000000 !important; /* Black value */
            font-size: 4.5em !important; /* <<< Added this line - Adjust size (e.g., 2em, 24px) as needed */
        }
        
        /* Make sure text elements inherit the black color if not specified */
        /* This might not be strictly necessary if the above works, but can help */
        div[data-testid="stMetric"] p {
            color: #000000 !important;
        }
        
        /* Target the value text's inner container if direct targeting isn't enough */
        /* Usually the above selector is sufficient, but uncomment/use this if needed: */
        /*
        div[data-testid="stMetricValue"] > div,
        div[data-testid="stMetricValue"] > p {
            font-size: 4.5em !important; /* Ensure inner element gets size */
        /* } */
        
        </style>
        """, unsafe_allow_html=True)
        # --- End Custom CSS ---
        
        # ... (Rest of your script, including where st.metric is called) ...
        
        #Example of where your metrics might be called (inside col1)
        metric_col1, metric_col2 = st.columns(2)
        with metric_col1:
            st.metric("People inside the campus", time_in_count)
        with metric_col2:
            st.metric("Total Unique Persons Today (Approx)", len(id_counts))

    else:
        st.info("No attendance data loaded.")
        # Display 0 when no data is loaded
        st.metric("People inside the campus", 0)


    st.subheader("Latest Entries")
    # Display table (using st.table or st.dataframe)
    # st.dataframe(filtered_df.head(5), use_container_width=True, hide_index=True) # Consider dataframe
    st.table(filtered_df.head(4)) # Keep st.table if preferred


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
                    ax.text(x+12, y+55, f"Gate{gate_num}", color='#000000', fontsize=10, bbox=dict(facecolor='#ffffff', alpha=0.69))
                
                ax.axis('off')  # Hide axes
                
                
                # Add fake points for testing - REMOVE IN PRODUCTION
                # This will help you see if the points are being displayed correctly
#                for gate_num, coords in gate_coordinates.items():
#                    x, y = coords
#                    ax.plot(x, y, 'o', color=violet_color, markersize=8, alpha=.9)
#                    ax.text(x+12, y+50, f"Gate{gate_num}", color='#000000', fontsize=8, bbox=dict(facecolor='#ffffff', alpha=0.69))

                
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
st.sidebar.subheader("Daily Operations")
archive_button = st.sidebar.button(
    "Archive Today's Attendance",
    on_click=archive_and_clear,
    help=f"Copies today's data from Sheet1 to a new sheet named 'Attendance_{datetime.now().strftime('%b-%d-%Y')}' and clears Sheet1 (keeps header)."
)
st.sidebar.divider()
st.sidebar.button("Refresh Data Now", on_click=force_reload, use_container_width=True)




