import dns.resolver
import urllib.parse
from functools import lru_cache

# Cache DNS resolver instance
_resolver = None

def get_resolver() -> dns.resolver.Resolver:
    global _resolver
    if _resolver is None:
        _resolver = dns.resolver.Resolver()
        _resolver.timeout = 2.0
        _resolver.lifetime = 6.0
    return _resolver

def get_apex_domain(host: str) -> str:
    """Extract apex domain from host (e.g. sub.example.com -> example.com)."""
    clean_host = host.split("/")[0].split(":")[0].strip().lower()
    parts = clean_host.split(".")

    two_level_tlds = {
        "co.uk", "org.uk", "gov.uk", "ac.uk",
        "com.au", "net.au", "co.in", "net.in",
        "co.nz", "com.br", "co.jp", "com.sg"
    }
    if len(parts) >= 3:
        potential_tld = f"{parts[-2]}.{parts[-1]}"
        if potential_tld in two_level_tlds:
            return ".".join(parts[-3:])
        return ".".join(parts[-2:])
    return clean_host

@lru_cache(maxsize=1024)
def has_mx_record(domain_or_url: str) -> bool:
    """Verify if domain is capable of receiving mail by querying DNS MX records."""
    if not domain_or_url:
        return False

    if "://" in domain_or_url:
        parsed = urllib.parse.urlparse(domain_or_url)
        clean_host = parsed.netloc
    else:
        clean_host = domain_or_url

    apex = get_apex_domain(clean_host)
    resolver = get_resolver()

    try:
        records = resolver.resolve(apex, "MX")
        return len(records) > 0
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.Timeout, Exception):
        return False
