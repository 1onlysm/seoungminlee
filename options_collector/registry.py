from dataclasses import dataclass
@dataclass(frozen=True)
class Symbol:
    symbol: str
    assetclass: str
    category: str
    enabled: bool = True
    expected_root: str = ""
_SYMBOLS = [("SPY","etf","S&P 500 ETF"),("QQQ","etf","Nasdaq 100 ETF"),("SOXX","etf","Semiconductor ETF"),("IWM","etf","Russell 2000 ETF"),("IBIT","etf","Bitcoin ETF"),("NVDA","stocks","Semiconductor"),("AMD","stocks","Semiconductor"),("TSLA","stocks","EV / Technology"),("MSTR","stocks","Bitcoin Treasury"),("PLTR","stocks","AI / Software"),("MU","stocks","Memory Semiconductor"),("CRWV","stocks","AI Cloud"),("COIN","stocks","Crypto Exchange"),("MARA","stocks","Bitcoin Mining")]
REGISTRY = {s: Symbol(s,a,c,True,s) for s,a,c in _SYMBOLS}
assert len(REGISTRY) == 14 and len(REGISTRY) == len(_SYMBOLS)
def get_symbol(symbol: str) -> Symbol:
    try: return REGISTRY[symbol.upper()]
    except KeyError as exc: raise ValueError(f"unregistered symbol: {symbol}") from exc
