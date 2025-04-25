import streamlit as st
import pandas as pd
import os
import time
import matplotlib.pyplot as plt
from streamlit_gsheets import GSheetsConnection
from PIL import Image
import io   
import numpy as np
from datetime import datetime, timedelta

logo_path = os.path.join("sd", f"logo.jpg")
st.logo(logo_path, size="large")

# Initialize session state variables
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = datetime.now()
if 'gate_points' not in st.session_state:
    st.session_state.gate_points = []
if 'last_update_check' not in st.session_state:
    st.session_state.last_update_check = datetime.now() - timedelta(seconds=10)

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

# Modified cache data function with shorter TTL and error handling
@st.cache_data(ttl=3)
def load_data():
    try:
        # Connect to Google Sheets
        conn = st.connection("gsheets", type=GSheetsConnection)
        
        # Force a refresh of the connection
        conn.reset()
        
        # Read data from Google Sheets
        df = conn.read(worksheet="Sheet1")
        
        # Filter required columns (Timestamp, Gate Number, Identification Number)
        filtered_df = df[["Timestamp", "Gate No.", "Identification No.", "Name"]].copy()
        
        # Convert Timestamp to datetime format
        filtered_df["Timestamp"] = pd.to_datetime(filtered_df["Timestamp"])
        
        # Handle NaN values in Gate No. and convert to integer
        filtered_df["Gate No."] = filtered_df["Gate No."].fillna(0).astype(int)
        
        filtered_df = filtered_df.sort_values(by="Timestamp", ascending=False)
        
        return filtered_df
    except Exception as e:
        st.error(f"Error loading data: {str(e)}")
        # Return empty DataFrame if there's an error
        return pd.DataFrame(columns=["Timestamp", "Gate No.", "Identification No.", "Name"])

# Create a function to clear the cache and force reload
def force_reload():
    st.cache_data.clear()

filtered_df = load_data()

# Create three columns for layout
col1, col2, col3 = st.columns([8, 9, 5], gap='large')

# --- COLUMN 1: Pie Chart and Table ---
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

# Add a refresh button and display the last refresh time
st.sidebar.button("Refresh Data", on_click=force_reload)
st.sidebar.write(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")

# Check if it's time to update based on interval
current_time = datetime.now()
if (current_time - st.session_state.last_update_check).total_seconds() >= 2:  # Check every 3 seconds
    st.session_state.last_update_check = current_time
    # Clear cache to force reload
    st.cache_data.clear()
    # Use rerun to refresh the app
    st.rerun()
