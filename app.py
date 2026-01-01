import streamlit as st
import pandas as pd
import yfinance as yf
import altair as alt
from datetime import datetime, timedelta



st.set_page_config(page_title="My Portfolio Tracker", layout="wide")
st.title("My Trading 212 Portfolio Tracker")
st.write("""
Upload your Trading 212 CSV file to see:
- Projected annual & monthly dividend income
- Dividend growth rates
- Currency-adjusted portfolio visuals
- Projected DRIP growth
""")

# Sidebar
# Upload CVSs, combine and remove duplicates
dataframes = []
combined_df = pd.DataFrame()
uploaded_files = st.sidebar.file_uploader(
    "Upload your Trading 212 CSV", type="csv", accept_multiple_files=True
)

if uploaded_files:
    dataframes = [pd.read_csv(file) for file in uploaded_files]
    combined_df = pd.concat(dataframes, ignore_index=True)

    before = combined_df.shape[0]
    combined_df = combined_df.drop_duplicates(ignore_index=True)
    after = combined_df.shape[0]
    st.success("CSV files combined successfully!")

    st.write("Below is the combined data from all uploaded CSV files. You can review your tickers, shares, and transactions.")
    st.dataframe(combined_df)
    
    csv = combined_df.to_csv(index=False).encode('utf-8')
    st.sidebar.download_button(
        label="Download Combined CSV",
        data=csv,
        file_name="combined_file.csv",
        mime="text/csv"
    )

base_currency = st.sidebar.selectbox("Portfolio Base Currency", ["USD", "GBP", "EUR"], index=0)

# DRIP slider
st.sidebar.subheader("DRIP Simulation")
drip_years = st.sidebar.slider("Years to simulate", 1, 30, 5)
drip_enabled = st.sidebar.checkbox("Enable DRIP", value=True)

# FX rate
@st.cache_data(show_spinner=False)
def get_fx_rate(from_ccy, to_ccy):
    if from_ccy == to_ccy:
        return 1.0
    ticker = f"{from_ccy}{to_ccy}=X"
    fx = yf.Ticker(ticker)
    hist = fx.history(period="5d")
    if hist.empty:
        return 1.0
    return hist["Close"].iloc[-1]

# Dividend historical info
@st.cache_data(show_spinner=False)
def get_dividend_history(ticker):
    try:
        stock = yf.Ticker(ticker)
        dividends = stock.dividends
        if dividends.empty:
            return pd.Series(dtype=float)
        dividends.index = dividends.index.tz_localize(None)
        return dividends
    except Exception:
        return pd.Series(dtype=float)

# Dividend CAGR
def calculate_dividend_cagr(dividends, years=5):
    if dividends.empty:
        return 0.0
    annual = dividends.resample("Y").sum()
    annual = annual[annual > 0]
    if len(annual) < 2:
        return 0.0
    start = annual.iloc[-min(years, len(annual))]
    end = annual.iloc[-1]
    n = len(annual) - 1
    if start <= 0 or n <= 0:
        return 0.0
    return (end / start) ** (1 / n) - 1

# DRIP Simulation
def simulate_drip(shares, annual_dividend, price, years):
    shares_over_time = [shares]
    yearly_income = []
    for _ in range(years):
        income = shares * annual_dividend
        yearly_income.append(income)
        # reinvest
        new_shares = income / price
        shares += new_shares
        shares_over_time.append(shares)
    return shares_over_time, yearly_income


# Main
if not combined_df.empty:
    ticker_col = next(c for c in ["Ticker", "Stock Ticker", "Instrument"] if c in combined_df.columns)
    qty_col = next(c for c in ["No. of shares", "Shares", "Shares Owned"] if c in combined_df.columns)
    action_col = next((c for c in ["Action", "Type", "Transaction Type"] if c in combined_df.columns), None)

    if action_col:
        def signed_shares(row):
            action = str(row[action_col]).strip().lower()
            if "buy" in action:
                return row[qty_col]
            elif "sell" in action:
                return -row[qty_col]
            else:
                return 0

        combined_df["Signed Shares"] = combined_df.apply(signed_shares, axis=1)
        share_col = "Signed Shares"
    else:
        st.warning("No Sell Action column detected.")
        share_col = qty_col

    df = (
        combined_df.groupby(ticker_col, as_index=False)[share_col]
        .sum()
        .rename(columns={ticker_col: "Ticker", share_col: "Shares"})
    )

    positive_df = df[df["Shares"] > 0]
    if positive_df.empty:
        st.info("No holdings detected.")
    else:
        df = positive_df
        st.success(f"Processed {len(df)} tickers with positive holdings.")

    # Portfolio Share Distribution 
    st.subheader("Portfolio Share Distribution")
    df["Share %"] = (df["Shares"] / df["Shares"].sum()) * 100
    st.dataframe(df[["Ticker", "Shares", "Share %"]].style.format({"Shares": "{:.2f}", "Share %": "{:.2f}%"}))

    # Pie chart visualisation
    share_pie = alt.Chart(df).mark_arc().encode(
        theta="Share %:Q",
        color="Ticker:N",
        tooltip=["Ticker", "Shares", "Share %"]
    ).properties(
        title="Portfolio Share Distribution"
    )

    st.altair_chart(share_pie, use_container_width=True)

    # Bar chart visualisation
    share_bar = alt.Chart(df).mark_bar().encode(
        x="Ticker:N",
        y="Share %:Q",
        color="Ticker:N",
        tooltip=["Ticker", "Shares", "Share %"]
    ).properties(
        title="Portfolio Share Distribution"
    )

    st.altair_chart(share_bar, use_container_width=True)

    if df.empty:
        st.info("No holdings after processing buy/sell actions.")
    else:
        df["Annual Dividend / Share"] = 0.0
        df["Annual Income"] = 0.0
        df["Dividend CAGR %"] = 0.0
        df["Shares After DRIP"] = 0.0
        df["Income After DRIP"] = 0.0

        monthly_income = {}
        calendar_rows = []

        with st.spinner("Fetching dividend data..."):
            for i, row in df.iterrows():
                dividends = get_dividend_history(row["Ticker"])
                if dividends.empty:
                    continue

                last_12m = dividends[dividends.index >= datetime.today() - timedelta(days=365)]
                annual_div = last_12m.sum()
                cagr = calculate_dividend_cagr(dividends)

                # Monthly calendar
                for date, value in last_12m.items():
                    future_date = date + pd.DateOffset(years=1)
                    calendar_rows.append({
                        "Ticker": row["Ticker"],
                        "Month": future_date.strftime("%Y-%m"),
                        "Dividend": value * row["Shares"]
                    })
                    month = date.strftime("%b")
                    monthly_income[month] = monthly_income.get(month, 0) + value * row["Shares"]

                df.at[i, "Annual Dividend / Share"] = annual_div
                df.at[i, "Annual Income"] = annual_div * row["Shares"]
                df.at[i, "Dividend CAGR %"] = cagr * 100

                # DRIP simulation
                if drip_enabled:
                    try:
                        price = yf.Ticker(row["Ticker"]).history(period="5d")["Close"].iloc[-1]
                    except Exception:
                        price = 0
                    if price > 0:
                        shares_path, income_path = simulate_drip(row["Shares"], annual_div, price, drip_years)
                        df.at[i, "Shares After DRIP"] = shares_path[-1]
                        df.at[i, "Income After DRIP"] = income_path[-1]

        calendar_df = pd.DataFrame(calendar_rows).groupby(["Month", "Ticker"], as_index=False)["Dividend"].sum().sort_values("Month")

        # Currency conversion
        fx_rate = get_fx_rate("USD", base_currency)
        df["Annual Income"] *= fx_rate
        df["Income After DRIP"] *= fx_rate
        monthly_df = pd.DataFrame(list(monthly_income.items()), columns=["Month", "Income"]).assign(Income=lambda x: x["Income"] * fx_rate)
        month_order = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        monthly_df["Month"] = pd.Categorical(monthly_df["Month"], categories=month_order, ordered=True)
        monthly_df = monthly_df.sort_values("Month")

        # Display
        st.subheader("Dividend Portfolio Overview")
        st.dataframe(df.style.format({
            "Annual Dividend / Share": "{:.2f}",
            "Annual Income": "{:,.2f}",
            "Dividend CAGR %": "{:.2f}%",
            "Shares After DRIP": "{:.2f}",
            "Income After DRIP": "{:,.2f}"
        }))

        st.metric("Total Projected Annual Dividend", f"{base_currency} {df['Annual Income'].sum():,.2f}")

        st.subheader("Dividend Calendar – Next 12 Months")
        calendar_pivot = calendar_df.pivot(index="Month", columns="Ticker", values="Dividend").fillna(0)
        
        st.dataframe(calendar_pivot.style.format("{:,.2f}"))
        calendar_chart = alt.Chart(calendar_df).mark_bar().encode(
            x="Month:N",
            y="Dividend:Q",
            color="Ticker:N",
            tooltip=["Ticker", "Dividend"]
        ).properties(title="Projected Dividend Distribution per month")
        st.altair_chart(calendar_chart, use_container_width=True)

        # Charts
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Annual Dividend by Holding")
            bar = alt.Chart(df).mark_bar().encode(
                x="Ticker:N",
                y="Annual Income:Q",
                tooltip=["Ticker", "Annual Income"]
            )
            st.altair_chart(bar, use_container_width=True)

        with col2:
            st.subheader("Dividend Income Distribution")
            pie = alt.Chart(df).mark_arc().encode(
                theta="Annual Income:Q",
                color="Ticker:N",
                tooltip=["Ticker", "Annual Income"]
            )
            st.altair_chart(pie, use_container_width=True)

        st.subheader("Monthly Dividend Income Projection")
        st.dataframe(monthly_df.style.format({"Income": "{:,.2f}"}))
        monthly_chart = alt.Chart(monthly_df).mark_bar().encode(
            x="Month:N",
            y="Income:Q",
            tooltip=["Month", "Income"]
        ).properties(title="Projected Monthly Income")
        st.altair_chart(monthly_chart, use_container_width=True)

        # DRIP Growth Projection for all stocks      
        if drip_enabled:
            st.subheader("Overall DRIP Growth Projection")
            drip_chart = alt.Chart(
                pd.DataFrame({"Year": range(drip_years + 1), "Shares": shares_path})
            ).mark_line(point=True).encode(
                x="Year:Q",
                y="Shares:Q",
                tooltip=["Year", "Shares"]
            )
            st.altair_chart(drip_chart, use_container_width=True)

        # DRIP Simulation per Ticker
        if drip_enabled and not df.empty:
            st.subheader("DRIP Simulation per Stock")

            tickers = df["Ticker"].tolist()
            selected_ticker = st.selectbox("Select a stock to simulate DRIP:", tickers)

            drip_data = []

            row = df[df["Ticker"] == selected_ticker].iloc[0]
            shares = row["Shares"]
            annual_div = row["Annual Dividend / Share"]

            try:
                price = yf.Ticker(selected_ticker).history(period="5d")["Close"].iloc[-1]
            except Exception:
                price = 0

        if price > 0:
            shares_path, income_path = simulate_drip(shares, annual_div, price, drip_years)

            for year, s in enumerate(shares_path):
                drip_data.append({
                    "Ticker": selected_ticker,
                    "Year": year,
                    "Shares": s,
                    "Income": s * annual_div
                })

            drip_df = pd.DataFrame(drip_data)

            # Chart: Shares growth
            drip_chart_shares = alt.Chart(drip_df).mark_line(point=True).encode(
                x="Year:Q",
                y="Shares:Q",
                tooltip=["Ticker", "Year", "Shares"]
            ).properties(title=f"DRIP Growth – {selected_ticker} Shares")

            st.altair_chart(drip_chart_shares, use_container_width=True)

            # Chart: Projected dividend income
            drip_chart_income = alt.Chart(drip_df).mark_line(point=True).encode(
                x="Year:Q",
                y="Income:Q",
                tooltip=["Ticker", "Year", "Income"]
            ).properties(title=f"DRIP Projected Dividend Income – {selected_ticker}")

            st.altair_chart(drip_chart_income, use_container_width=True)
        else:
                st.warning(f"Could not fetch price data for {selected_ticker}.")
else:
    st.write("No data available. Upload your Trading 212 CSV to begin.")

