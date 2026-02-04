import pandas as pd

df = pd.read_csv("AlgoB/market_data_3y.csv", header=[0,1], index_col=0)
print("Data loaded from AlgoB/market_data_3y.csv")
def get_data():
    return df       

if __name__ == "__main__":
    print(df.head())
