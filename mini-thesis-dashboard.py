# test_connection.py
import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd

st.set_page_config(layout="wide")
st.title("GSheets Connection Test")
st.write("Attempting to connect using configured 'gsheets' connection...")

try:
    # Ensure secrets are configured via Streamlit Cloud secrets or secrets.toml
    conn = st.connection("gsheets", type=GSheetsConnection)
    st.success("Connection object created successfully.")

    # --- Configuration ---
    worksheet_name = "Metadata"  # Exact name of your metadata sheet
    cell_range_to_read = "A1"   # Cell where the timestamp should be
    # --- End Configuration ---

    st.write(f"Attempting to read range '{cell_range_to_read}' from worksheet '{worksheet_name}'...")

    # Perform the read operation
    # Adding ttl=0 to try and bypass any caching during test
    df = conn.read(worksheet=worksheet_name, range=cell_range_to_read, header=None, ttl=0)

    st.write("Read attempt finished. Resulting DataFrame:")
    st.dataframe(df) # Show the raw DataFrame received

    if df.empty:
        st.error("Read operation returned an EMPTY DataFrame.")
        st.info(f"Please double-check: \n1. Worksheet name ('{worksheet_name}') spelling/case. \n2. Cell '{cell_range_to_read}' actually has data visible in Google Sheets. \n3. Sharing permissions for the service account email. \n4. Secrets configuration. \n5. Google Sheets API is enabled in GCP.")
    elif pd.isna(df.iloc[0, 0]):
         st.warning(f"Read returned data, but the specific cell ({cell_range_to_read}) appears to be NA/empty in the DataFrame.")
         st.write("Value read:", df.iloc[0, 0])
    else:
        st.success("Read operation returned data!")
        st.write("Value read:", df.iloc[0, 0])

except Exception as e:
    st.error("An error occurred during the connection or read process:")
    st.exception(e) # Display the full exception details, often very helpful!
