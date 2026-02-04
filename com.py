"""
Strategy Comparison: PIÑON_FIJO vs EMA 25/125 Crossover
"""

print("=" * 80)
print("STRATEGY COMPARISON")
print("=" * 80)

# Strategy A: PIÑON_FIJO_DYNAMIC (Always Long)
print("\n📊 STRATEGY A: PIÑON_FIJO_DYNAMIC (Always Long)")
print("-" * 80)
print("Period: 2023-02-03 to 2026-02-03 (752 days)")
print("\nPerformance:")
print("  Total Return:        1,092.32%")
print("  Final Equity:        $1,192,321")
print("  Sharpe Ratio:        1.35")
print("  Profit Factor:       1.59")
print("  Max Drawdown:        $12,958 (1.3%)")

print("\nTrade Stats:")
print("  Total Trades:        461")
print("  Win Rate:            44.4%")
print("  Avg Win:             $78,992")
print("  Avg Loss:            -$39,780")
print("  Stop Loss Hit Rate:  98.8%")
print("  Short Hedge Rate:    19.8%")

# Strategy B: EMA 25/125 Crossover
print("\n📈 STRATEGY B: EMA 25/125 CROSSOVER (Bull Market Only)")
print("-" * 80)
print("Period: 2023-08-04 to 2026-02-03 (627 days)")
print("\nPerformance:")
print("  Total Return:        474.82%")
print("  Final Equity:        $574,819")
print("  Sharpe Ratio:        1.27")
print("  Profit Factor:       1.64")
print("  Max Drawdown:        $31,246 (5.4%)")

print("\nTrade Stats:")
print("  Total Trades:        377")
print("  Win Rate:            43.1%")
print("  Avg Win:             $41,753")
print("  Avg Loss:            -$19,268")
print("  Stop Loss Hit Rate:  97.0%")
print("  Bear Exit Rate:      1.5%")
print("  Short Hedge Rate:    19.6%")

print("\nMarket Exposure:")
print("  Bull Market Days:    565 (90.1%)")
print("  Bear Market Days:    62 (9.9%)")

# Comparison
print("\n" + "=" * 80)
print("KEY DIFFERENCES")
print("=" * 80)

print("\n✅ STRATEGY A ADVANTAGES:")
print("  • 2.3x higher return (1,092% vs 475%)")
print("  • Better Sharpe (1.35 vs 1.27)")
print("  • Much smaller max drawdown ($12,958 vs $31,246)")
print("  • Larger average wins ($78,992 vs $41,753)")
print("  • Always in the market (no missed bull runs)")

print("\n✅ STRATEGY B ADVANTAGES:")
print("  • Higher profit factor (1.64 vs 1.59)")
print("  • Smaller average loss (-$19,268 vs -$39,780)")
print("  • Avoids bear markets (90% bull exposure)")
print("  • Lower position sizes = less extreme losses")

print("\n⚠️  KEY OBSERVATIONS:")
print("  • Both strategies have ~44% win rates but profit due to asymmetric wins")
print("  • Both strategies hit stop loss ~97-98% of the time")
print("  • Strategy A's higher leverage (always 3-3.5x) drives higher returns")
print("  • Strategy B missed 125 days for EMA warmup + bear market periods")
print("  • During the test period, staying invested was better (strong bull)")

print("\n🎯 VERDICT:")
print("  • Strategy A dominates in strong bull markets (like 2023-2026)")
print("  • Strategy B would likely outperform in volatile/choppy markets")
print("  • Strategy B's EMA filter avoided only 62 bear days (9.9%)")
print("  • The market was mostly bullish, favoring always-long approach")

print("\n💡 RECOMMENDATION:")
print("  • Use Strategy A in confirmed bull markets")
print("  • Use Strategy B when macro uncertainty is high")
print("  • Consider a hybrid: Start with B, switch to A on strong EMA signal")

print("\n" + "=" * 80)