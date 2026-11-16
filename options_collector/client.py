import json, urllib.error, urllib.request
from dataclasses import dataclass
from .registry import get_symbol
BASE = "https://api.nasdaq.com/api/quote/{symbol}/option-chain?assetclass={assetclass}&limit=20000&fromdate=all"
HEADERS = {"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36","Accept":"application/json","Referer":"https://www.nasdaq.com/"}
@dataclass
class FetchResult:
    symbol: str; http_status: int|None; api_rcode: int|None; body: bytes|None; error_type: str|None=None; error_detail: str|None=None
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None
class NasdaqClient:
    """One-shot client: no retries, no redirects; keeps urllib's default proxy handling."""
    def __init__(self, timeout=30): self.timeout=timeout; self.opener=urllib.request.build_opener(NoRedirect)
    def fetch_once(self,symbol):
        item=get_symbol(symbol); req=urllib.request.Request(BASE.format(symbol=item.symbol,assetclass=item.assetclass),headers=HEADERS)
        try:
            with self.opener.open(req,timeout=self.timeout) as response: body,status=response.read(),response.status
        except urllib.error.HTTPError as exc:
            body=exc.read(); return FetchResult(item.symbol,exc.code,_rcode(body),body,"HTTP_ERROR")
        except urllib.error.URLError as exc:
            reason=exc.reason; return FetchResult(item.symbol,None,None,None,type(reason).__name__,str(reason))
        except TimeoutError as exc: return FetchResult(item.symbol,None,None,None,"TimeoutError",str(exc))
        return FetchResult(item.symbol,status,_rcode(body),body)
def _rcode(body):
    try:
        rc=json.loads(body.decode("utf-8")).get("status",{}).get("rCode"); return int(rc) if rc is not None else None
    except (UnicodeDecodeError,json.JSONDecodeError,AttributeError,TypeError,ValueError): return None
