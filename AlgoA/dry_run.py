import pandas as pd
import numpy as np

# PARAMETERS
ENTRY_1 = 0.0012
ENTRY_2 = 0.0020
ENTRY_3 = 0.0030
INVALID_ZERO = 0.0
HARD_EXIT = 0.002
DAILY_KILL = -0.025

def run_backtest(data):
    state = {
        "mode": "NEUTRAL",
        "position_fraction": 0.0,
        "trading_enabled": True,
        "daily_pnl": 0.0
    }

    results = []

    for ts, row in data.iterrows():
        SMH_RET = row["SMH_RET"]
        SOXX_RET = row["SOXX_RET"]
        QQQ_RET = row["QQQ_RET"]
        VIX = row["VIX"]
        LONG_PERSIST = row["LONG_PERSIST"]
        SHORT_PERSIST = row["SHORT_PERSIST"]

        # Kill switch
        if state["daily_pnl"] <= DAILY_KILL:
            state["trading_enabled"] = False
            state["position_fraction"] = 0.0

        # Detect mode
        if state["trading_enabled"]:
            if SMH_RET > 0 and SOXX_RET > 0:
                state["mode"] = "LONG"
            elif SMH_RET < 0 and SOXX_RET < 0:
                state["mode"] = "SHORT"
            else:
                state["mode"] = "NEUTRAL"

        # Select asset
        if state["mode"] == "LONG":
            asset_ret = max(SMH_RET, SOXX_RET)
        elif state["mode"] == "SHORT":
            asset_ret = min(SMH_RET, SOXX_RET)
        else:
            asset_ret = 0.0

        # Progressive entry
        pf = state["position_fraction"]

        if state["mode"] == "LONG":
            if asset_ret >= ENTRY_1: pf = max(pf, 0.5)
            if asset_ret >= ENTRY_2: pf = max(pf, 0.7)
            if asset_ret >= ENTRY_3: pf = max(pf, 1.0)

        if state["mode"] == "SHORT":
            if asset_ret <= -ENTRY_1: pf = max(pf, 0.5)
            if asset_ret <= -ENTRY_2: pf = max(pf, 0.7)
            if asset_ret <= -ENTRY_3: pf = max(pf, 1.0)

        # Anti churn
        if state["mode"] == "LONG" and 0.003 <= QQQ_RET <= 0.007 and LONG_PERSIST >= 30:
            pf = max(pf, 0.5)

        if state["mode"] == "SHORT" and -0.007 <= QQQ_RET <= -0.003 and SHORT_PERSIST >= 30:
            pf = max(pf, 0.5)

        # Invalidation
        if state["mode"] == "LONG" and asset_ret <= INVALID_ZERO:
            pf *= 0.5
        if state["mode"] == "SHORT" and asset_ret >= INVALID_ZERO:
            pf *= 0.5

        if state["mode"] == "LONG" and asset_ret <= -HARD_EXIT:
            pf = 0.0
        if state["mode"] == "SHORT" and asset_ret >= HARD_EXIT:
            pf = 0.0

        # Leverage
        leverage = 0.0
        if state["mode"] == "LONG":
            base = 4.0 if VIX < 12 else 3.0 if VIX < 15 else 2.0
            leverage = base * pf

        if state["mode"] == "SHORT":
            base = 2.0 if VIX < 20 else 4.0 if VIX < 25 else 5.0
            leverage = base * pf

        state["position_fraction"] = pf

        results.append({
            "timestamp": ts,
            "mode": state["mode"],
            "position_fraction": pf,
            "leverage": leverage
        })

    return pd.DataFrame(results)


if __name__ == "__main__":
    # Dummy intraday data for testing
    idx = pd.date_range("2024-01-02 09:30", periods=78, freq="5min")

    data = pd.DataFrame({
        "SMH_RET": np.random.normal(0, 0.002, len(idx)),
        "SOXX_RET": np.random.normal(0, 0.002, len(idx)),
        "QQQ_RET": np.random.normal(0, 0.0015, len(idx)),
        "VIX": np.random.uniform(12, 22, len(idx)),
        "LONG_PERSIST": np.random.randint(0, 60, len(idx)),
        "SHORT_PERSIST": np.random.randint(0, 60, len(idx)),
    }, index=idx)

    results = run_backtest(data)

    print(results.head())
    print(results.tail())
