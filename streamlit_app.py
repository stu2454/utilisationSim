from pathlib import PurePosixPath
from typing import Dict
import zipfile
import re

import pandas as pd
import altair as alt
import streamlit as st

# Page setup
st.set_page_config(page_title="AT Utilisation Explorer", layout="wide")
st.title("Assistive Technology Utilisation Explorer – v5.18")

# ------------------------------------------------------------------
# Expected CSV files (must be defined before load_data)
# ------------------------------------------------------------------
EXPECTED = {
    "a_participant.csv",
    "b_plan.csv",
    "c_claim_line.csv",
    "benchmark_history.csv",
    "supplementary_item_list.csv",
}

@st.cache_data(show_spinner=False)
def _read_lower(buf) -> pd.DataFrame:
    df = pd.read_csv(buf)
    df.columns = [c.lower().strip() for c in df.columns]
    return df

# ------------------------------------------------------------------
# Load data
# ------------------------------------------------------------------
st.sidebar.header('Data upload')
upload = st.sidebar.file_uploader('Upload ZIP or CSV', type=['zip','csv'])

def load_data(upload) -> Dict[str, pd.DataFrame]:
    if not upload:
        return {}
    name = upload.name.lower()
    if name.endswith('.csv'):
        return {name: _read_lower(upload)}
    if name.endswith('.zip'):
        dfs, missing = {}, set(EXPECTED)
        with zipfile.ZipFile(upload) as zf:
            for member in zf.namelist():
                if '__macosx' in member.lower():
                    continue
                tail = PurePosixPath(member).name.lower()
                if tail in EXPECTED:
                    with zf.open(member) as f:
                        dfs[tail] = _read_lower(f)
                        missing.discard(tail)
        if missing:
            st.warning('Missing: ' + ', '.join(sorted(missing)))
        return dfs
    st.error('Upload a .csv or .zip only')
    return {}

dfs = load_data(upload)
if len(dfs) < 3:
    st.info('Please upload the required CSVs or a ZIP containing them.')
    st.stop()

# Assign DataFrames
df_part = dfs['a_participant.csv'].copy()
df_plan = dfs['b_plan.csv'].copy()
df_claim = dfs['c_claim_line.csv'].copy()

# ------------------------------------------------------------------
# Rename maps
# ------------------------------------------------------------------
REN_PART = {
    'hashed_participant_id':'Hashed_Participant_ID',
    'state':'State',
    'mmm_code':'MMM_Code',
    'age_band':'Age_Band',
    'primary_disability':'Primary_Disability',
}
REN_PLAN = {
    'hashed_participant_id':'Hashed_Participant_ID',
    'plan_id':'Plan_ID',
    'plan_start_date':'Plan_Start_Date',
    'capital_at_budget_total_aud':'Capital_AT_Budget_Total_AUD',
    'plan_management_mode':'Plan_Management_Mode',
}
REN_CLAIM = {
    'hashed_participant_id':'Hashed_Participant_ID',
    'plan_id':'Plan_ID',
    'service_date':'Service_Date',
    'support_item_number':'Support_Item_Number',
    'original_claimed_unitprice_aud':'Original_Claimed_UnitPrice_AUD',
    'paid_unitprice_aud':'Paid_UnitPrice_AUD',
    'benchmark_unitprice_aud':'Benchmark_UnitPrice_AUD',
    'claim_id':'Claim_ID',
    'source_system':'Source_System',
}

def rename(df: pd.DataFrame, mapping: Dict[str, str]) -> pd.DataFrame:
    return df.rename(columns={k:v for k,v in mapping.items() if k in df.columns})

# Apply renaming
df_part = rename(df_part, REN_PART)
if 'Hashed_Participant_ID' not in df_part.columns:
    candidates = [c for c in df_part.columns if 'id' in c.lower()]
    df_part['Hashed_Participant_ID'] = df_part[candidates[0]]
df_plan = rename(df_plan, REN_PLAN)
df_claim = rename(df_claim, REN_CLAIM)

# ------------------------------------------------------------------
# Enrichment & merge
# ------------------------------------------------------------------
pattern = re.compile(r'(motor neurone|multiple sclerosis|muscular dystrophy|huntington)', re.I)
df_part['Degenerative_Flag'] = df_part['Primary_Disability'].fillna('').apply(lambda x: bool(pattern.search(x)))

df_claim['Service_Date'] = pd.to_datetime(df_claim['Service_Date'], errors='coerce')
df_plan['Plan_Start_Date'] = pd.to_datetime(df_plan['Plan_Start_Date'], errors='coerce')

merged = (
    df_claim
    .merge(df_plan, on='Plan_ID', how='left')
    .merge(
        df_part[['Hashed_Participant_ID','State','MMM_Code','Age_Band','Degenerative_Flag']],
        on='Hashed_Participant_ID', how='left'
    )
)

# ------------------------------------------------------------------
# Filters
# ------------------------------------------------------------------
sb = st.sidebar; sb.header('Filters')
f_source = sb.multiselect('Source', merged['Source_System'].dropna().unique(), default=merged['Source_System'].unique())
f_state = sb.multiselect('State', merged['State'].dropna().unique(), default=merged['State'].unique())
f_mmm = sb.multiselect('MMM region', merged['MMM_Code'].dropna().unique(), default=merged['MMM_Code'].unique())
f_age = sb.multiselect('Age band', merged['Age_Band'].dropna().unique(), default=merged['Age_Band'].unique())
f_mode = sb.multiselect('Plan mode', merged['Plan_Management_Mode'].dropna().unique(), default=merged['Plan_Management_Mode'].unique())
f_items = sb.multiselect('Support item number', merged['Support_Item_Number'].dropna().unique(), default=merged['Support_Item_Number'].unique())
if sb.checkbox('Degenerative only'):
    merged = merged[merged['Degenerative_Flag']]
if sb.checkbox('Breaches only'):
    merged = merged[merged['Original_Claimed_UnitPrice_AUD'] > merged['Benchmark_UnitPrice_AUD']]
filtered = merged[
    merged['Source_System'].isin(f_source) &
    merged['State'].isin(f_state) &
    merged['MMM_Code'].isin(f_mmm) &
    merged['Age_Band'].isin(f_age) &
    merged['Plan_Management_Mode'].isin(f_mode) &
    merged['Support_Item_Number'].isin(f_items)
]
if filtered.empty:
    st.warning('No data matches filters')
    st.stop()

# ------------------------------------------------------------------
# Plan draw-down
# ------------------------------------------------------------------
plan_base = df_plan.merge(
    df_part[['Hashed_Participant_ID','State','MMM_Code','Age_Band']], on='Hashed_Participant_ID', how='left'
)
paid_sum = filtered.groupby('Plan_ID')['Paid_UnitPrice_AUD'].sum().reset_index(name='Paid')
plan_draw = plan_base.merge(paid_sum, on='Plan_ID', how='left').fillna({'Paid':0})
plan_draw['DrawPct'] = plan_draw['Paid'] / plan_draw['Capital_AT_Budget_Total_AUD']
draw_filt = plan_draw[plan_draw['Plan_ID'].isin(filtered['Plan_ID'].unique())]

# ------------------------------------------------------------------
# KPI cards
# ------------------------------------------------------------------
cap_total = draw_filt['Capital_AT_Budget_Total_AUD'].sum()
paid_total = draw_filt['Paid'].sum()
util_pct = paid_total / cap_total * 100 if cap_total else 0
zero_count = (draw_filt['DrawPct'] == 0).sum()
partial_count = (draw_filt['DrawPct'] < 1).sum()
cols = st.columns(5)
cols[0].metric(
    'Capital budget',
    f'{cap_total:,.0f} AUD',
    help="Total approved capital AT budget across the selected plans."
)
cols[1].metric(
    'Paid',
    f'{paid_total:,.0f} AUD',
    help="Total amount actually paid for AT items in those plans."
)
cols[2].metric(
    'Util %',
    f'{util_pct:.1f}%',
    help="Share of the approved budget that’s been paid (Paid ÷ Budget)."
)
cols[3].metric(
    '0% draw',
    zero_count,
    help="Number of plans where no AT budget was drawn down – i.e. zero paid claims."
)
cols[4].metric(
    '<100% draw',
    partial_count,
    help="Number of plans where some, but not all, of the AT budget was utilised."
)
# ------------------------------------------------------------------
# Utilisation by State
# ------------------------------------------------------------------
st.subheader('Utilisation by State')
st.altair_chart(
    alt.Chart(draw_filt.groupby('State', as_index=False)
                 .agg(Paid=('Paid','sum'), Budget=('Capital_AT_Budget_Total_AUD','sum'))
                 .assign(Util=lambda df: df['Paid']/df['Budget']*100)
        )
    .mark_bar()
    .encode(
        x='State:N',
        y='Util:Q', tooltip=['Paid','Budget', alt.Tooltip('Util', format='.1f')]
    ),
    use_container_width=True
)

#------------------------------------------------------------------
# Utilisation by MMM region
#------------------------------------------------------------------
st.subheader('Utilisation by MMM region')
st.altair_chart(
    alt.Chart(draw_filt.groupby('MMM_Code', as_index=False)
                 .agg(Paid=('Paid','sum'), Budget=('Capital_AT_Budget_Total_AUD','sum'))
                 .assign(Util=lambda df: df['Paid']/df['Budget']*100)
        )
    .mark_bar()
    .encode(
        x='MMM_Code:N',
        y='Util:Q', tooltip=['Paid','Budget', alt.Tooltip('Util', format='.1f')]
    ),
    use_container_width=True
)

# ------------------------------------------------------------------
# Draw-down histogram
#------------------------------------------------------------------
st.subheader('Plan draw-down distribution')
st.altair_chart(
    alt.Chart(draw_filt)
        .mark_area(opacity=0.7, interpolate='step')
        .encode(
            alt.X('DrawPct:Q', bin=alt.Bin(maxbins=40), title='Draw-down %'),
            alt.Y('count()', title='Plans')
        ),
    use_container_width=True
)

#------------------------------------------------------------------
# Waterfall diagnostics & chart
#------------------------------------------------------------------
st.subheader('Waterfall diagnostics')
utilisation_rate = paid_total / cap_total if cap_total else 0
st.write(f"Total Budget: {cap_total:,.2f} AUD")
st.write(f"Total Paid:   {paid_total:,.2f} AUD")
st.write(f"Utilisation Rate (Paid/Budget): {utilisation_rate:.1%}")

#------------------------------------------------------------------
# Budget attrition waterfall
#------------------------------------------------------------------
st.subheader('Budget attrition waterfall')
hf_chart = (
    alt.Chart(pd.DataFrame({'Step': ['Budget','Claimed','Paid'], 'AUD': [cap_total, filtered['Original_Claimed_UnitPrice_AUD'].sum(), filtered['Paid_UnitPrice_AUD'].sum()]}))
        .mark_bar(color='orange', size=40)
        .encode(
            alt.X('Step:O', title='Stage'),
            alt.Y('AUD:Q', title='Amount (AUD)', axis=alt.Axis(format=',')),
            tooltip=[alt.Tooltip('AUD:Q', format=',')]
        )
)
st.altair_chart(hf_chart, use_container_width=True)

#------------------------------------------------------------------
# Breach histogram
#------------------------------------------------------------------
st.subheader('Breach ratio distribution')
rf = filtered[filtered['Benchmark_UnitPrice_AUD']>0].copy()
rf['Ratio'] = rf['Original_Claimed_UnitPrice_AUD'] / rf['Benchmark_UnitPrice_AUD']
st.altair_chart(
    alt.Chart(rf)
        .mark_area(opacity=0.7, interpolate='step')
        .encode(
            alt.X('Ratio:Q', bin=alt.Bin(maxbins=40)),
            alt.Y('count()', title='Claims')
        ),
    use_container_width=True
)

#------------------------------------------------------------------
# Cumulative paid-claim curve
#------------------------------------------------------------------
st.subheader('Cumulative paid-claim share vs days since start')
o = (
    filtered.assign(Day=lambda df: (df['Service_Date'] - df['Plan_Start_Date']).dt.days)
           .query('Day>=0')
)
st.altair_chart(
    alt.Chart(
        o.groupby('Day', as_index=False)
         .agg(Count=('Claim_ID','count'))
         .assign(Cum=lambda df: df['Count'].cumsum(), Pct=lambda df: df['Cum']/df['Count'].sum()*100)
    )
    .mark_line()
    .encode(
        x='Day:Q',
        y='Pct:Q',
        tooltip=['Day', alt.Tooltip('Pct', format='.1f')]
    ),
    use_container_width=True
)

#------------------------------------------------------------------
# Support-item league
#------------------------------------------------------------------
st.subheader('Top support items')
st.dataframe(
    filtered.groupby('Support_Item_Number', as_index=False)
            .agg(Claims=('Claim_ID','count'), Paid=('Paid_UnitPrice_AUD','sum'), Avg_Price=('Original_Claimed_UnitPrice_AUD','mean'))
            .sort_values('Paid', ascending=False)
            .head(50),
    use_container_width=True
)

#------------------------------------------------------------------
# Raw data preview
#------------------------------------------------------------------
with st.expander('Raw claim rows (first 300)'):
    st.dataframe(filtered.head(300), use_container_width=True)

# Footer
st.markdown('---\n*v5.18 – EXPECTED defined and full cleanup*')
