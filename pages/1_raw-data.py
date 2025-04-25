import streamlit as st
from streamlit_gsheets import GSheetsConnection
import os

st.set_page_config(page_title="Raw Data", page_icon=":signal_strength:", layout="wide")
logo_path = os.path.join("sd", f"logo.jpg")
st.logo(logo_path, size="large")
st.markdown("""     
<style>
    img[data-testid="stLogo"] {
            height: 3rem;
}      
</style>
""", unsafe_allow_html=True)

conn = st.connection("gsheets", type=GSheetsConnection)
df = conn.read(worksheet="Sheet1")

st.dataframe(df)
