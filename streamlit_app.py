import streamlit as st
import pandas as pd
import zipfile
from pathlib import PurePosixPath
from typing import Dict
import altair as alt

st.set_page_config(page_title="AT Utilisation Explorer", layout="wide")
st.title("Assistive Technology Utilisation Explorer")

# ------------------------------------------------------------------
# 1. Upload helper (ZIP/CSV, ignore macOS artefacts)
# ------------------------------------------------------------------
EXPECTED = {
    "a_participant.csv", "b_plan.csv", "c_claim_line.csv",
    "benchmark_history.csv", "supplementary_item_list.csv"
}

@st.cache_data(show_spinner=False)
def load_data(upload) -> Dict[str, pd.DataFrame]:
    if upload is None:
        return {}
    if upload.name.lower().endswith(".csv"):
        return {upload.name.lower(): pd.read_csv(upload)}
    if upload.name.lower().endswith(".zip"):
        dfs, missing = {}, set(EXPECTED)
        with zipfile.ZipFile(upload) as zf:
            for member in zf.namelist():
                if "__macosx" in member.lower():
                    continue
                tail = PurePosixPath(member).name.lower()
                if tail in EXPECTED:
                    with zf.open(member) as f:
                        dfs[tail] = pd.read_csv(f)
                        missing.discard(tail)
        if missing:
            st.warning("Missing file(s): " + ", ".join(sorted(missing)))
        return dfs
    st.error("Unsupported file – upload .zip or .csv")
    return {}

st.sidebar.header("Data upload")
upload = st.sidebar.file_uploader("Upload dataset", type=["zip", "csv"], accept_multiple_files=False)

dfs = load_data(upload)
if len(dfs) < 3:
    st.info("Upload AT_Simulated_Dataset.zip (or individual CSVs) to proceed.")
    st.stop()

participants = dfs.get("a_participant.csv")
plans        = dfs.get("b_plan.csv")
claims       = dfs.get("c_claim_line.csv")

if any(x is None for x in (participants, plans, claims)):
    st.error("Core files still missing – check sidebar warning.")
    st.stop()

# ------------------------------------------------------------------
# 2. Merge minimal fields
# ------------------------------------------------------------------
merged = (
    claims
    .merge(plans[["Plan_ID", "Plan_Start_Date", "Plan_Management_Mode", "Hashed_Participant_ID"]], on="Plan_ID", how="left")
    .merge(participants[["Hashed_Participant_ID", "State", "MMM_Code"]], on="Hashed_Participant_ID", how="left")
)
merged["Service_Date"] = pd.to_datetime(merged["Service_Date"], errors="coerce")
merged["Plan_Start_Date"] = pd.to_datetime(merged["Plan_Start_Date"], errors="coerce")

# ------------------------------------------------------------------
# 3. Sidebar filters
# ------------------------------------------------------------------
st.sidebar.header("Filters")
source_sel = st.sidebar.multiselect("Source system", merged["Source_System"].unique().tolist(), default=list(merged["Source_System"].unique()))
state_sel  = st.sidebar.multiselect("State", merged["State"].dropna().unique().tolist(), default=list(merged["State"].dropna().unique()))
item_sel   = st.sidebar.multiselect("Support item", sorted(merged["Support_Item_Number"].unique()), default=[])
show_breach = st.sidebar.checkbox("Show only price‑limit breaches (> benchmark)")

filt = merged[(merged["Source_System"].isin(source_sel)) & (merged["State"].isin(state_sel))].copy()
if item_sel:
    filt = filt[filt["Support_Item_Number"].isin(item_sel)]
if show_breach:
    filt = filt[filt["Original_Claimed_UnitPrice_AUD"] > filt["Benchmark_UnitPrice_AUD"]]

if filt.empty:
    st.warning("No rows match your filter combination.")
    st.stop()

# ------------------------------------------------------------------
# 4. KPI cards
# ------------------------------------------------------------------
sel_budget  = plans[plans["Plan_ID"].isin(filt["Plan_ID"].unique())]["Capital_AT_Budget_Total_AUD"].sum()
sel_claimed = filt["Original_Claimed_UnitPrice_AUD"].sum()
sel_paid    = filt["Paid_UnitPrice_AUD"].sum()
util_pct = sel_paid / sel_budget * 100 if sel_budget else 0

k1, k2, k3 = st.columns(3)
k1.metric("Capital Budget (AUD)", f"{sel_budget:,.0f}")
k2.metric("Total Claimed (AUD)", f"{sel_claimed:,.0f}")
k3.metric("Paid (AUD)", f"{sel_paid:,.0f}  ({util_pct:.1f}%)")

# ------------------------------------------------------------------
# 5. Utilisation waterfall
# ------------------------------------------------------------------
wf_df = pd.DataFrame({"Step": ["Budget", "Claimed", "Paid"], "AUD": [sel_budget, sel_claimed, sel_paid]})
st.subheader("Budget attrition waterfall")
st.altair_chart(
    alt.Chart(wf_df).mark_bar(size=40).encode(
        x=alt.X("Step", sort=["Budget", "Claimed", "Paid"], title=""),
        y=alt.Y("AUD:Q", title="AUD ($)", axis=alt.Axis(format=",.0f")),
        tooltip=["AUD:Q"]
    ).properties(height=250), use_container_width=True)

# ------------------------------------------------------------------
# 6. Paid‑by‑system & breach histogram
# ------------------------------------------------------------------
left, right = st.columns(2)
with left:
    st.subheader("Paid by source system")
    st.altair_chart(
        alt.Chart(filt.groupby("Source_System", as_index=False)["Paid_UnitPrice_AUD"].sum()).mark_bar().encode(
            x="Source_System:N", y="Paid_UnitPrice_AUD:Q", tooltip=["Paid_UnitPrice_AUD"]
        ), use_container_width=True)
with right:
    st.subheader("Breach distribution (claimed ÷ benchmark)")
    ratio_df = filt[filt["Benchmark_UnitPrice_AUD"] > 0].copy()
    ratio_df["Ratio"] = ratio_df["Original_Claimed_UnitPrice_AUD"] / ratio_df["Benchmark_UnitPrice_AUD"]
    st.altair_chart(
        alt.Chart(ratio_df).mark_area(opacity=0.7, interpolate="step").encode(
            alt.X("Ratio:Q", bin=alt.Bin(maxbins=40)), alt.Y("count()"), tooltip=["count()"]
        ), use_container_width=True)

# ------------------------------------------------------------------
# 7. Cumulative % of paid claims vs days since plan start
# ------------------------------------------------------------------
st.subheader("Cumulative paid‑claim share by days since plan start")

offset_df = filt.copy()
offset_df["Day_Offset"] = (offset_df["Service_Date"] - offset_df["Plan_Start_Date"]).dt.days
offset_df = offset_df[offset_df["Day_Offset"].notna() & (offset_df["Day_Offset"] >= 0)]

if offset_df.empty:
    st.info("No dated claims available for the cumulative chart.")
else:
    daily = offset_df.groupby("Day_Offset", as_index=False)["Claim_ID"].count().rename(columns={"Claim_ID": "Daily_Count"})
    daily["Cumulative"] = daily["Daily_Count"].cumsum()
    total = daily["Daily_Count"].sum()
    daily["Pct"] = daily["Cumulative"] / total * 100
    st.altair_chart(
        alt.Chart(daily).mark_line().encode(
            x=alt.X("Day_Offset:Q", title="Days since plan start"),
            y=alt.Y("Pct:Q", title="Cumulative % of paid claims", axis=alt.Axis(format=".0f")),
            tooltip=["Day_Offset", alt.Tooltip("Pct", format=".1f")]
        ), use_container_width=True)

# ------------------------------------------------------------------
# 8. Support‑item league table
# ------------------------------------------------------------------
st.subheader("Support‑item summary (current filter)")
item_summary = (
    filt.groupby("Support_Item_Number")
        .agg(Claims=("Claim_ID", "count"),
             Paid_AUD=("Paid_UnitPrice_AUD", "sum"),
             Avg_Price=("Original_Claimed_UnitPrice_AUD", "mean"))
        .sort_values("Paid_AUD", ascending=False)
)
st.dataframe(item_summary.head(50), use_container_width=True)

# ------------------------------------------------------------------
# 9. Raw claim rows (sample)
# ------------------------------------------------------------------
with st.expander("Show raw claim rows (first 300)"):
    st.dataframe(filt.head(300), use_container_width=True)

st.markdown(
    "---\n"
    "*Prototype v4 – KPI cards, waterfall, breach histogram, cumulative curve & league table*"
)

