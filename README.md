# Assistive Technology Utilisation Explorer  📊

*A Streamlit dashboard for exploring NDIA Assistive-Technology (AT) budgets,
claims and benchmark breaches.*

[![Streamlit Cloud](https://static.streamlit.io/badges/streamlit_badge_black.svg)](https://share.streamlit.io/your-org/streamlit-at-explorer)  
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Features

- **Drag-and-drop ZIP upload** – accepts the five-file extract (`A_Participant.csv`, `B_Plan.csv`, …) in a flat folder *or* nested.
- **Interactive filters** – slice by source system (CRM/PACE), state, support-item code, price-limit breaches.
- **KPI cards** – capital budget, total claimed, total paid & utilisation %.
- **Budget attrition waterfall** – Budget → Claimed → Paid.
- **Breach histogram** – distribution of *claimed ÷ benchmark* ratios.
- **Cumulative-payment curve** – % of paid claims vs days since plan start.
- **Support-item league table** – claims, $ paid and average price per item.
- **Raw-data preview** – first 300 rows of the current filter set.

## Quick start (local Python)

```bash
git clone https://github.com/your-org/streamlit-at-explorer.git
cd streamlit-at-explorer
pip install -r requirements.txt
streamlit run streamlit_app.py

