"""
A single hardened HTTP client shared by fetch.py and validate_feeds.py.

Publishers and networks break naive feed fetchers in several distinct ways, and
each needs a *different* answer. Rather than blindly retrying, `get()` reads the
first error and picks only the fallbacks that could plausibly fix it:

  403 / 406 / 451   -> an identity problem. Retry as a feed reader; many
                       publishers block generic clients on /feed/ but explicitly
                       whitelist Feedly.
  cert verify failed-> a *trust* problem, almost always local. requests trusts
                       certifi's bundle, not the OS store, so a TLS-inspecting
                       proxy or antivirus is invisible to it. Retry against the
                       operating system's trust store.
  other SSL errors  -> a *handshake* problem. Retry with a relaxed cipher policy
                       for servers OpenSSL 3 refuses by default.
  429 / 5xx         -> transient. Handled by urllib3 backoff before we ever get
                       here, honouring Retry-After.
  404 / 410 / timeout -> nothing to be done. Fail immediately rather than
                       burning the run's time budget on hopeless retries.

Certificate verification and hostname checking remain enabled on every path.
None of these fallbacks accepts an untrusted certificate.
"""

import ssl
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# `truststore` reads the OS certificate store (Windows CryptoAPI, macOS
# Security.framework, OpenSSL dirs on Linux). It is what pip itself uses.
# Optional: without it we simply lose the system-trust fallback rung.
try:
    import truststore
    HAVE_TRUSTSTORE = True
except ImportError:                                   # pragma: no cover
    HAVE_TRUSTSTORE = False

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

FEEDREADER_UA = ("Feedly/1.0 (+http://www.feedly.com/fetcher.html; "
                 "like FeedFetcher-Google)")

BASE_HEADERS = {
    "Accept": ("application/rss+xml, application/atom+xml, application/xml;q=0.9, "
               "text/xml;q=0.9, text/html;q=0.8, */*;q=0.5"),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

# connect=0 is deliberate and important. urllib3 treats a TLS failure as a
# connection error and would otherwise retry it three times with backoff -- so a
# certificate that will never verify costs ~40s per feed instead of ~1s. Status
# retries stay on, because 429 and 503 genuinely are worth waiting out.
RETRY = Retry(
    total=3,
    connect=0,
    read=1,
    status=3,
    backoff_factor=1.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET", "HEAD"),
    respect_retry_after_header=True,
)


class LegacyTLSAdapter(HTTPAdapter):
    """Permits older cipher suites and legacy renegotiation.

    Widens which handshakes we will complete. Certificate verification stays on.
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        try:
            ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        except ssl.SSLError:                          # pragma: no cover
            pass
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


class SystemTrustAdapter(HTTPAdapter):
    """Verifies against the OS trust store rather than certifi's bundle.

    This is what rescues machines behind TLS-inspecting antivirus or a corporate
    proxy: the interceptor's root CA is installed in the OS store, so the OS
    trusts it, but certifi has never heard of it.
    """

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        return super().init_poolmanager(*args, **kwargs)


def _session(adapter_cls=HTTPAdapter):
    s = requests.Session()
    s.mount("https://", adapter_cls(max_retries=RETRY))
    s.mount("http://", HTTPAdapter(max_retries=RETRY))
    return s


# Each trust backend words the same failure differently. OpenSSL (certifi) says
# "unable to get local issuer certificate"; Windows CryptoAPI, which is what
# truststore consults, says "terminated in a root certificate which is not
# trusted". Both mean: the chain is fine, we just do not trust who signed it.
_CERT_ERROR_MARKERS = (
    "CERTIFICATE_VERIFY_FAILED",
    "certificate verify failed",
    "unable to get local issuer",
    "terminated in a root certificate which is not trusted",   # Windows
    "self signed certificate",
    "self-signed certificate",
    "unable to get issuer certificate",
)


def is_cert_error(exc):
    """True when the failure is about *trust*, not about ciphers or transport."""
    text = str(exc)
    return any(m in text for m in _CERT_ERROR_MARKERS)


class FeedClient:
    """Reusable across threads: requests.Session is thread-safe for plain GETs."""

    def __init__(self, timeout=25):
        self.timeout = timeout
        self.plain = _session()
        self.legacy = _session(LegacyTLSAdapter)
        self.system = _session(SystemTrustAdapter) if HAVE_TRUSTSTORE else None

    def _try(self, session, url, ua):
        headers = dict(BASE_HEADERS, **{"User-Agent": ua})
        r = session.get(url, timeout=self.timeout, headers=headers)
        r.raise_for_status()
        return r

    def _plan(self, exc):
        """Which fallbacks could actually fix this error? Empty means give up."""
        if isinstance(exc, requests.exceptions.SSLError):
            if is_cert_error(exc):
                # A different User-Agent or cipher list cannot make an untrusted
                # chain trusted. Only a different trust store can.
                if self.system is None:
                    return []
                # One attempt only. The User-Agent is sent *after* the handshake
                # completes, so it cannot possibly influence a TLS failure --
                # varying it here would just add latency to a hopeless case.
                return [(self.system, BROWSER_UA, "system-trust-store")]
            return [(self.legacy, BROWSER_UA, "legacy-tls")]

        if isinstance(exc, requests.exceptions.HTTPError):
            code = exc.response.status_code if exc.response is not None else 0
            if code in (403, 406, 451):
                plan = [(self.plain, FEEDREADER_UA, "feedreader"),
                        (self.legacy, BROWSER_UA, "legacy-tls")]
                if self.system is not None:
                    plan.append((self.system, BROWSER_UA, "system-trust-store"))
                return plan
            return []                                  # 404, 410, 401 -- hopeless

        return []                                      # timeouts, DNS, etc.

    def get(self, url):
        """Return (response, strategy_used). Raises the last error if all fail."""
        try:
            return self._try(self.plain, url, BROWSER_UA), "browser"
        except requests.exceptions.RequestException as first:
            plan = self._plan(first)
            if not plan:
                raise
            last = first
            for session, ua, label in plan:
                try:
                    return self._try(session, url, ua), label
                except requests.exceptions.RequestException as exc:
                    last = exc
            raise last


def describe_error(exc):
    """A short, readable one-liner for logs and the failed_feeds list."""
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, requests.exceptions.SSLError):
        if is_cert_error(exc):
            return "SSL: untrusted certificate (run --diagnose)"
        return "SSL: handshake failed"
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "connect timeout"
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return "read timeout"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "connection failed"
    return f"{type(exc).__name__}: {str(exc)[:80]}"


# A filtering appliance that is *blocking* rather than merely inspecting serves
# its own block page, usually with HTTP 200 and an HTML body. If its root CA is
# ever trusted, that page arrives looking like a perfectly successful fetch.
# feedparser would find zero entries and the source would look like a quiet news
# day rather than a censored one, so it is worth naming explicitly.
_BLOCK_MARKERS = (
    b"fortiguard", b"fortigate", b"web page blocked", b"url blocked",
    b"access denied", b"blocked by", b"content filter", b"web filter",
    b"zscaler", b"websense", b"forcepoint", b"bluecoat", b"blue coat",
    b"sonicwall", b"barracuda", b"policy violation", b"this site is blocked",
    b"blocked category", b"restricted by your network",
)


def looks_like_block_page(body, content_type=""):
    """True when a 200 response is a filter's block page, not a feed."""
    if not body:
        return False
    head = body[:4096].lower()
    # A real feed declares itself early, whatever else is in the body.
    if b"<rss" in head or b"<feed" in head or b"<?xml" in head or b"<rdf" in head:
        return False
    if "html" not in (content_type or "").lower() and b"<html" not in head:
        return False
    return any(m in head for m in _BLOCK_MARKERS)


def trust_store_status():
    """One line for the validator header, so the cause is obvious up front."""
    if HAVE_TRUSTSTORE:
        return "system trust store available (truststore installed)"
    return ("system trust store UNAVAILABLE -- run:  uv add truststore\n"
            "  Without it, certificate errors caused by antivirus or a "
            "corporate proxy cannot be worked around.")
