"""Streamlit dashboard over mart_metrics. Reads the same DuckDB table the
Excel pack is built from, so the dashboard and the workbook can never
disagree with each other.

Run: streamlit run app.py
"""
from __future__ import annotations

import duckdb
import pandas as pd
import streamlit as st

from wagering_mart import config

st.set_page_config(page_title="Wagering Metrics Mart", layout="wide")


@st.cache_data
def load_mart() -> pd.DataFrame:
    con = duckdb.connect(str(config.MART_DB_PATH), read_only=True)
    df = con.execute("SELECT * FROM mart_metrics ORDER BY year_month, state, product").df()
    con.close()
    return df


st.title("Wagering Metrics Mart")
st.caption(
    "Synthetic sportsbook wagering data, generated on this machine. "
    "Handle, hold, structural vs actual hold, parlay mix and revenue per "
    "monthly unique payer, sliced by state and product."
)

df = load_mart()

months = sorted(df["year_month"].unique())
states = sorted(df["state"].unique())
products = sorted(df["product"].unique())

col1, col2, col3 = st.columns(3)
month_sel = col1.multiselect("Month", months, default=months)
state_sel = col2.multiselect("State", states, default=states)
product_sel = col3.multiselect("Product", products, default=products)

f = df[
    df["year_month"].isin(month_sel)
    & df["state"].isin(state_sel)
    & df["product"].isin(product_sel)
]

handle = f["handle"].sum()
payout = f["payout"].sum()
net_revenue = handle - payout
actual_hold = net_revenue / handle if handle else 0.0
structural_hold = (f["handle"] * f["structural_hold"]).sum() / handle if handle else 0.0
parlay_mix = f["parlay_handle"].sum() / handle if handle else 0.0
mup = f.groupby("year_month")["unique_payers"].sum().mean() if len(f) else 0.0

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Handle", f"${handle:,.0f}")
k2.metric("Actual hold", f"{actual_hold:.2%}")
k3.metric("Structural hold", f"{structural_hold:.2%}")
k4.metric("Parlay mix", f"{parlay_mix:.2%}")
k5.metric("Avg monthly unique payers", f"{mup:,.0f}")

st.subheader("Handle and hold by state")
by_state = f.groupby("state", as_index=False).agg(
    handle=("handle", "sum"), payout=("payout", "sum")
)
by_state["actual_hold"] = (by_state["handle"] - by_state["payout"]) / by_state["handle"]
st.bar_chart(by_state.set_index("state")["handle"])
st.dataframe(by_state, use_container_width=True)

st.subheader("Handle by product")
by_product = f.groupby("product", as_index=False)["handle"].sum().sort_values("handle", ascending=False)
st.bar_chart(by_product.set_index("product")["handle"])

st.subheader("Revenue per monthly unique payer, by month")
by_month = f.groupby("year_month", as_index=False).agg(
    net_revenue=("net_revenue", "sum"), unique_payers=("unique_payers", "sum")
)
by_month["revenue_per_mup"] = by_month["net_revenue"] / by_month["unique_payers"]
st.line_chart(by_month.set_index("year_month")["revenue_per_mup"])

st.subheader("Full mart (pivot-ready, same table as the Excel pack)")
st.dataframe(f, use_container_width=True)
