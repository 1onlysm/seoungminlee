"""Frozen target registry for isolated future per-symbol collection."""

SYMBOL_ASSET_CLASSES = {
    "SPY": "etf", "QQQ": "etf", "SOXX": "etf", "NVDA": "stocks",
    "IWM": "etf", "IBIT": "etf", "AMD": "stocks", "TSLA": "stocks",
    "MSTR": "stocks", "PLTR": "stocks", "MU": "stocks", "CRWV": "stocks",
    "COIN": "stocks", "MARA": "stocks",
}


def normalize_symbol(symbol):
    value = str(symbol).strip().upper()
    if value not in SYMBOL_ASSET_CLASSES:
        raise ValueError("UNREGISTERED_SYMBOL")
    return value


def endpoint_for_symbol(symbol):
    symbol = normalize_symbol(symbol)
    return f"https://api.nasdaq.com/api/quote/{symbol}/option-chain?assetclass={SYMBOL_ASSET_CLASSES[symbol]}&limit=20000&fromdate=all"
