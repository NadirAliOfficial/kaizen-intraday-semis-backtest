import yfinance as yf

df = yf.download(
    ["SMH", "SOXX", "SOXL", "^VIX", "QQQ"],
    start="2022-01-01",
    end="2026-02-01",
    interval="1d",
    group_by="ticker"
)

# Flatten columns
df.columns = [f"{col[1]}_{col[0]}" for col in df.columns]

df.to_csv("market_data.csv")
print("✅ Downloaded: SMH, SOXX, SOXL, VIX, QQQ")
print(f"Rows: {len(df)}")
print(f"Columns: {list(df.columns)}")
print(df.head())
print(df.tail())