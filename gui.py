import pickle
import pandas as pd
import streamlit as st

st.set_page_config(page_title="FAISS Vector DB Viewer", layout="wide")
st.title("FAISS Vector Store Viewer")

file_path = st.sidebar.selectbox(
    "Select Collection File",
    ["./chroma_data/employees.pkl", "./chroma_data/unknowns.pkl", "./faiss_data/employees.pkl"]
)

try:
    with open(file_path, "rb") as f:
        data = pickle.load(f)

    st.success(f"File Loaded Successfully: {file_path}")

    st.metric("Total Vectors Saved", len(data.get("ids", [])))

    df = pd.DataFrame({
        "Vector ID": data.get("ids", []),
        "Metadata": data.get("metadatas", [])
    })

    st.subheader("Stored Metadata & IDs")
    st.dataframe(df, use_container_width=True)

except Exception as e:
    st.error(f"Error loading file: {e}")