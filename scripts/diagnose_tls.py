#!/usr/bin/env python3
"""
Identify who is signing the certificates you're being served.

    uv run python scripts/diagnose_tls.py                     # suspects vs control
    uv run python scripts/diagnose_tls.py cbr.com bbc.co.uk   # specific hosts

When a site fails certificate validation against BOTH certifi's bundle and the
operating system's trust store, the chain is being replaced in transit. This
reads the certificate actually presented and prints who issued it. If the issuer
is your antivirus, your router, your ISP or a filtering appliance rather than a
public CA, that is your answer.

For full issuer detail:   uv add cryptography
Without it this still works, using a narrower scan of the raw certificate.

IMPORTANT -- on verification:
This tool deliberately inspects certificates without validating them, because
the entire point is to look at a certificate that failed validation. That is
acceptable here only because it *reads and reports* -- it never returns page
content, and nothing it touches reaches the digest pipeline.

The fetcher never does this, and there is deliberately no --insecure flag.
Beyond the security problem, disabling verification would be silently wrong: an
ISP block page would parse as a valid (empty) feed, so a censored source would
be indistinguishable from a quiet news day.
"""

import argparse
import re
import socket
import ssl
import sys

try:
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding  # noqa: F401
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False

DEFAULT_SUSPECT = ["www.cbr.com", "screenrant.com", "collider.com",
                   "www.rollingstone.com", "www.polygon.com"]
DEFAULT_CONTROL = ["www.bbc.co.uk", "variety.com", "news.google.com"]

PUBLIC_CA_HINTS = (
    "digicert", "let's encrypt", "lets encrypt", "isrg", "sectigo", "comodo",
    "globalsign", "godaddy", "amazon", "google trust", "cloudflare", "entrust",
    "baltimore", "verisign", "thawte", "geotrust", "rapidssl", "certum",
    "buypass", "identrust", "microsoft", "actalis", "ssl.com", "zerossl",
    "starfield", "usertrust", "trustasia", "e-tugra", "quovadis",
)

# Things that show up in the issuer when traffic is being intercepted.
INTERCEPTOR_HINTS = (
    "kaspersky", "eset", "bitdefender", "avast", "avg ", "norton", "mcafee",
    "sophos", "trend micro", "webroot", "malwarebytes", "f-secure", "comodo cis",
    "zscaler", "netskope", "forcepoint", "bluecoat", "blue coat", "fortinet",
    "fortigate", "palo alto", "checkpoint", "check point", "cisco umbrella",
    "sonicwall", "watchguard", "untangle", "pfsense", "squid", "mitmproxy",
    "charles proxy", "fiddler", "burp", "proxy", "filter", "gateway",
    "firewall", "adguard", "pi-hole", "dns", "isp", "jio", "airtel", "vodafone",
    "bsnl", "act fibernet", "hathway", "excitel",
)


GREEN, YELLOW, RED, DIM, BOLD, RESET = (
    "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m")
if not sys.stdout.isatty():
    GREEN = YELLOW = RED = DIM = BOLD = RESET = ""


# ------------------------------------------------------------------ retrieval

def fetch_der(host, port=443, timeout=12):
    """Return (leaf_der, chain_ders, error). Verification off -- see docstring."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                leaf = tls.getpeercert(binary_form=True)
                chain = []
                # Python 3.13+ exposes the full chain even when unverified.
                getter = getattr(tls, "get_unverified_chain", None)
                if getter is not None:
                    try:
                        for cert in getter() or ():
                            try:
                                chain.append(cert.public_bytes(ssl.ENCODING_DER))
                            except (AttributeError, TypeError, ValueError):
                                pass
                    except Exception:                        # noqa: BLE001
                        pass
                return leaf, chain, None
    except Exception as exc:                                 # noqa: BLE001
        return None, [], f"{type(exc).__name__}: {str(exc)[:90]}"


# -------------------------------------------------------------------- parsing

def _name_bits(name):
    out = {}
    for attr in name:
        out[attr.oid._name] = attr.value
    return out


def parse_with_crypto(der):
    cert = x509.load_der_x509_certificate(der)
    iss = _name_bits(cert.issuer)
    sub = _name_bits(cert.subject)
    return {
        "issuer_org": iss.get("organizationName") or "",
        "issuer_cn": iss.get("commonName") or "",
        "subject_cn": sub.get("commonName") or "",
        "size": len(der),
    }


PRINTABLE = re.compile(rb"[\x20-\x7e]{4,}")


def parse_by_scan(der):
    """Fallback when `cryptography` is absent.

    DER stores names as length-prefixed printable strings, so scanning for
    printable runs recovers the organisation names even without a real parser.
    Good enough to tell a public CA from an antivirus root.
    """
    strings = [s.decode("ascii", "ignore") for s in PRINTABLE.findall(der)]
    blob = " | ".join(strings).lower()
    hit = next((h for h in INTERCEPTOR_HINTS if h in blob), "")
    pub = next((h for h in PUBLIC_CA_HINTS if h in blob), "")
    return {
        "issuer_org": "",
        "issuer_cn": "",
        "subject_cn": "",
        "size": len(der),
        "scan_public": pub,
        "scan_interceptor": hit,
        "strings": strings[:14],
    }


def classify(info):
    """'public' | 'intercept' | 'unknown'"""
    blob = f"{info.get('issuer_org','')} {info.get('issuer_cn','')}".lower()
    if blob.strip():
        if any(h in blob for h in INTERCEPTOR_HINTS):
            return "intercept"
        if any(h in blob for h in PUBLIC_CA_HINTS):
            return "public"
        return "unknown"
    if info.get("scan_interceptor"):
        return "intercept"
    if info.get("scan_public"):
        return "public"
    return "unknown"


# ------------------------------------------------------------------ reporting

def report(host):
    leaf, chain, err = fetch_der(host)
    if err:
        print(f"  {RED}{'??':<4}{RESET} {host:<26} {DIM}{err}{RESET}")
        return None
    info = parse_with_crypto(leaf) if HAVE_CRYPTO else parse_by_scan(leaf)
    verdict = classify(info)
    mark = {"public": f"{GREEN}ok  {RESET}",
            "intercept": f"{RED}MITM{RESET}",
            "unknown": f"{YELLOW}?   {RESET}"}[verdict]

    if HAVE_CRYPTO:
        who = info["issuer_org"] or info["issuer_cn"] or "(no issuer name)"
        extra = f" {DIM}({info['issuer_cn']}){RESET}" if (
            info["issuer_cn"] and info["issuer_cn"] != info["issuer_org"]) else ""
        print(f"  {mark} {host:<26} {DIM}{info['size']:>5}B{RESET}  "
              f"issued by {BOLD}{who}{RESET}{extra}")
    else:
        found = info["scan_interceptor"] or info["scan_public"] or "nothing recognised"
        print(f"  {mark} {host:<26} {DIM}{info['size']:>5}B{RESET}  scan: {found}")
        if verdict == "unknown":
            print(f"       {DIM}{' | '.join(info['strings'][:7])[:96]}{RESET}")

    # the chain root is the most direct evidence, when we can see it
    if HAVE_CRYPTO and len(chain) > 1:
        try:
            root = parse_with_crypto(chain[-1])
            print(f"       {DIM}chain root: "
                  f"{root['issuer_org'] or root['issuer_cn']}{RESET}")
        except Exception:                                     # noqa: BLE001
            pass
    return verdict


def main():
    ap = argparse.ArgumentParser(description="Identify TLS interception.")
    ap.add_argument("hosts", nargs="*")
    args = ap.parse_args()

    if not HAVE_CRYPTO:
        print(f"{YELLOW}`cryptography` not installed -- using a narrower scan.{RESET}")
        print(f"{DIM}For exact issuer names:  uv add cryptography{RESET}\n")

    if args.hosts:
        print(f"\n{BOLD}Certificates presented{RESET}\n")
        results = [report(h) for h in args.hosts]
        suspect, control = results, []
    else:
        print(f"\n{BOLD}Hosts that failed validation{RESET}\n")
        suspect = [report(h) for h in DEFAULT_SUSPECT]
        print(f"\n{BOLD}Hosts that validated fine (control group){RESET}\n")
        control = [report(h) for h in DEFAULT_CONTROL]

    print()
    bad = [r for r in suspect if r == "intercept"]
    ctrl_ok = [r for r in control if r == "public"]

    if bad:
        print(f"{RED}Confirmed: TLS interception.{RESET}")
        print("The failing hosts are served certificates from a non-public issuer.")
        print("Look at the issuer name above -- that is what is intercepting you.")
    elif control and ctrl_ok and all(r == "unknown" for r in suspect if r):
        print(f"{YELLOW}Strong indication of interception.{RESET}")
        print("The failing hosts present certificates from an issuer that is not a")
        print("recognised public CA, while the control hosts present normal ones.")
        print(f"{DIM}Install `cryptography` for the issuer's actual name.{RESET}")
    else:
        print(f"{DIM}Inconclusive from issuer names alone -- compare the sizes above.{RESET}")
        print(f"{DIM}Certificates of near-identical size across unrelated sites{RESET}")
        print(f"{DIM}indicate one issuer generating them from a single template.{RESET}")

    print()
    print(f"{BOLD}What to do{RESET}")
    print("  1. Nothing, for the digest's sake. GitHub-hosted runners sit on")
    print("     GitHub's own network, not behind this appliance. Confirm with:")
    print("     Actions -> Validate feeds -> Run workflow")
    print("  2. Locally, it depends what is intercepting you:")
    print(f"     {DIM}Antivirus (Kaspersky, ESET, Bitdefender, Avast){RESET}")
    print("       Turn off HTTPS/SSL scanning in its settings. Yours to change.")
    print(f"     {DIM}A network appliance (FortiGate, Zscaler, Palo Alto, Cisco){RESET}")
    print("       This is a managed device on the network you are connected to --")
    print("       office, campus, or a building-wide connection. You most likely")
    print("       cannot change it, and probably should not try. Options:")
    print("         · use a different network for local testing")
    print("         · ask whoever administers it to allow the category")
    print("         · just rely on CI, which is unaffected")
    print()
    print(f"  {YELLOW}Importing the appliance root CA is not a real fix.{RESET} It stops the")
    print("  certificate error, but if the appliance is *blocking* rather than")
    print("  merely inspecting, you then receive its block page over a trusted")
    print("  connection. The fetcher detects and rejects those, so the feed still")
    print("  fails -- just later and less obviously.")
    print(f"\n{DIM}Inspection only. Nothing fetched here is used by the digest.{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
