"""Single-attempt Nasdaq client. No retries, redirects, proxy override, or spoofed UA."""
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

BASE_URL = "https://api.nasdaq.com/api/quote/{symbol}/option-chain?assetclass=etf&limit=20000&fromdate=all"
HEADERS = {"Accept": "application/json", "User-Agent": "NAVI-OPTIONS-LAB/0.2"}
PILOT_CONFIRMATION = "I_AUTHORIZE_ONE_NASDAQ_SPY_REQUEST"


class LivePilotBlocked(RuntimeError):
    pass


@dataclass
class FetchResult:
    http_status: int | None
    body: bytes | None
    error_type: str | None = None
    error_detail: str | None = None
    request_count: int = 0

    @property
    def classification(self):
        if self.http_status == 403:
            return "HTTP_403_BLOCKED"
        if self.http_status == 429 or (self.http_status is not None and self.http_status >= 400):
            return "HTTP_OTHER_FAILURE"
        if self.http_status == 200:
            return "HTTP_RESPONSE_RECEIVED_UNVALIDATED"
        return "TRANSPORT_FAILURE"


def pilot_preflight(env=None, explicit_confirmation=None):
    env = env if env is not None else os.environ
    blockers = []
    if explicit_confirmation != PILOT_CONFIRMATION:
        blockers.append("EXPLICIT_SINGLE_REQUEST_AUTHORIZATION_MISSING")
    if env.get("NAVI_OPTIONS_ACCESS_PATH_APPROVED") != "YES":
        blockers.append("NASDAQ_ACCESS_PATH_NOT_APPROVED_403_UNRESOLVED")
    if env.get("NAVI_OPTIONS_RUNNER_APPROVED") != "YES":
        blockers.append("EXECUTION_ENVIRONMENT_NOT_APPROVED")
    if env.get("NAVI_OPTIONS_RETENTION_REVIEWED") != "YES":
        blockers.append("DATA_RETENTION_POLICY_NOT_REVIEWED")
    return {"ready": not blockers, "request_budget": 1, "retry_count": 0, "blockers": blockers}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NasdaqClient:
    def __init__(self, timeout=20, opener=None):
        if timeout <= 0 or timeout > 30:
            raise ValueError("TIMEOUT_OUT_OF_BOUNDS")
        self.timeout = timeout
        self.opener = opener or urllib.request.build_opener(NoRedirect)
        self.request_count = 0

    def fetch_spy_once(self, explicit_confirmation=None, env=None):
        preflight = pilot_preflight(env=env, explicit_confirmation=explicit_confirmation)
        if not preflight["ready"]:
            raise LivePilotBlocked("PILOT_PREFLIGHT_BLOCKED:" + ",".join(preflight["blockers"]))
        if self.request_count >= 1:
            raise LivePilotBlocked("REQUEST_BUDGET_EXHAUSTED")
        self.request_count += 1
        url = BASE_URL.format(symbol="SPY")
        request = urllib.request.Request(url, headers=HEADERS, method="GET")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return FetchResult(response.status, response.read(), request_count=self.request_count)
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read(65536)
            except OSError:
                body = None
            return FetchResult(exc.code, body, "HTTP_ERROR", str(exc.reason), self.request_count)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return FetchResult(None, None, type(exc).__name__, str(getattr(exc, "reason", exc)), self.request_count)

