import re
import urllib.parse
import httpx
from bs4 import BeautifulSoup

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
# Word boundary/non-digit boundary to avoid truncating larger license/registration numbers like 14-digit FSSAI
PHONE_REGEX = re.compile(r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}(?!\d)")

SOCIAL_PATTERNS = {
    "linkedin": re.compile(r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[^/\"'\s]+", re.I),
    "twitter": re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/[^/\"'\s]+", re.I),
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/[^/\"'\s]+", re.I),
    "facebook": re.compile(r"https?://(?:www\.)?facebook\.com/[^/\"'\s]+", re.I),
    "youtube": re.compile(r"https?://(?:www\.)?youtube\.com/(?:c/|channel/|user/|@)[^/\"'\s]+", re.I),
    "github": re.compile(r"https?://(?:www\.)?github\.com/[^/\"'\s]+", re.I),
    "whatsapp": re.compile(r"https?://(?:wa\.me|api\.whatsapp\.com/send\?(?:[^\"'\s]*&)?phone=)[^\"'\s]+", re.I),
}

ASSET_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot", ".ico"
)

IGNORED_EMAIL_TERMS = {
    "sentry", "u0026", "webpack", "wixpress", "bootstrap",
    "example.com", "domain.com", "email.com", "yourdomain.com",
    "schema.org", "noreply", "no-reply"
}

FALLBACK_CONTACT_PATHS = [
    "/contact", "/contact-us", "/about", "/about-us", "/team",
    "/pages/contact-us", "/pages/contact", "/policies/contact-information"
]

CONTACT_KEYWORDS = ("contact", "about", "team", "reach", "policy", "policies", "connect", "touch")

CRAWL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def deobfuscate_text(text: str) -> str:
    """Pre-process text to resolve basic email obfuscation like [at] and [dot]."""
    text = re.sub(r"\[at\]|\(at\)|\[@\]", "@", text, flags=re.IGNORECASE)
    text = re.sub(r"\[dot\]|\(dot\)", ".", text, flags=re.IGNORECASE)
    return text

def clean_social_url(url: str) -> str:
    """Clean tracking params, dashboard routes, and trailing slashes from social profile URLs."""
    url = url.split("?")[0].rstrip("/")
    for bad_suffix in ["/admin/dashboard", "/admin", "/edit", "/dashboard"]:
        if url.endswith(bad_suffix):
            url = url[:-len(bad_suffix)]
    return url

def sanitize_emails(raw_matches: list[str]) -> list[str]:
    valid = set()
    for email in raw_matches:
        lowered = email.lower().strip()
        lowered = lowered.rstrip(".,;:'\"!?)]}")

        if any(lowered.endswith(ext) for ext in ASSET_EXTENSIONS):
            continue
        if any(term in lowered for term in IGNORED_EMAIL_TERMS):
            continue
        if "@" not in lowered:
            continue
        parts = lowered.split("@")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            continue

        domain_part = parts[1]
        # Ignore npm package versions like gsap@3.12.5 or splide@4.1.3
        if re.match(r"^\d+\.\d+(\.\d+)?$", domain_part):
            continue
        if "." not in domain_part:
            continue

        valid.add(lowered)
    return sorted(valid)

def sanitize_phones(raw_matches: list[str]) -> list[str]:
    valid = set()
    for phone in raw_matches:
        phone_clean = phone.strip().rstrip(".,;:")
        # Check balanced parentheses
        if phone_clean.count("(") != phone_clean.count(")"):
            phone_clean = phone_clean.replace("(", "").replace(")", "").strip()

        digits = re.sub(r"\D", "", phone_clean)

        # Standard valid phones: 10-13 digits (with country code)
        if 10 <= len(digits) <= 13:
            # Reject Unix millisecond timestamps starting with 16, 17, 18, 19
            if len(digits) == 13 and digits.startswith(("16", "17", "18", "19", "20")):
                continue
            # Reject 14-digit FSSAI or license numbers
            if len(digits) >= 14:
                continue
            # Avoid single repeated digit or dummy sequences
            if len(set(digits)) <= 2 or digits == "1234567890":
                continue
            valid.add(phone_clean)
    return sorted(valid)

def discover_internal_contact_paths(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Dynamically discover contact/about links from homepage navigation."""
    base_netloc = urllib.parse.urlparse(base_url).netloc.lower()
    discovered_paths = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full_url = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(full_url)

        if parsed.netloc.lower() == base_netloc:
            path = parsed.path
            path_lower = path.lower()
            if any(kw in path_lower for kw in CONTACT_KEYWORDS):
                if path and path not in seen and not any(path_lower.endswith(ext) for ext in ASSET_EXTENSIONS):
                    seen.add(path)
                    discovered_paths.append(path)

    return discovered_paths

async def crawl_domain(client: httpx.AsyncClient, base_url: str) -> dict:
    emails = set()
    phones = set()
    socials: dict[str, str] = {}

    # Step 1: Fetch homepage first
    homepage_soup = None
    try:
        resp = await client.get(base_url, headers=CRAWL_HEADERS, follow_redirects=True, timeout=8.0)
        if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", "").lower():
            homepage_soup = BeautifulSoup(resp.text, "lxml")
            _extract_from_page(homepage_soup, resp.text, emails, phones, socials)
    except Exception:
        pass

    # Step 2: Dynamically discover contact paths from homepage + fallback paths
    contact_paths = []
    if homepage_soup:
        contact_paths.extend(discover_internal_contact_paths(homepage_soup, base_url))

    for fb in FALLBACK_CONTACT_PATHS:
        if fb not in contact_paths:
            contact_paths.append(fb)

    # Limit to top 4 contact subpaths to balance thoroughness and crawl speed
    target_paths = contact_paths[:4]

    # Step 3: Crawl discovered subpaths
    for path in target_paths:
        target_endpoint = urllib.parse.urljoin(base_url, path)
        try:
            resp = await client.get(target_endpoint, headers=CRAWL_HEADERS, follow_redirects=True, timeout=8.0)
            if resp.status_code != 200 or "text/html" not in resp.headers.get("content-type", "").lower():
                continue

            text = resp.text
            if not text or len(text) < 100:
                continue

            soup = BeautifulSoup(text, "lxml")
            _extract_from_page(soup, text, emails, phones, socials)
        except Exception:
            continue

    return {
        "emails": sanitize_emails(list(emails)),
        "phone_numbers": sanitize_phones(list(phones)),
        "social_profiles": socials,
    }

def _extract_from_page(soup: BeautifulSoup, raw_html: str, emails: set, phones: set, socials: dict):
    """Extract contact emails, phone numbers, and social links from a single page."""
    # 1. Extract mailto: links
    for mailto in soup.select('a[href^="mailto:"]'):
        href = mailto.get("href", "")
        raw_mail = href.replace("mailto:", "").split("?")[0].strip()
        if raw_mail:
            emails.add(raw_mail)

    # 2. Extract tel: links
    for tel in soup.select('a[href^="tel:"]'):
        href = tel.get("href", "")
        raw_phone = href.replace("tel:", "").split("?")[0].strip()
        if raw_phone:
            phones.add(urllib.parse.unquote(raw_phone))

    # 3. Detect social channels from page hrefs
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("http"):
            continue
        for platform, pattern in SOCIAL_PATTERNS.items():
            if platform not in socials and pattern.match(href):
                if any(share in href.lower() for share in ["/share", "/intent", "sharer.php"]):
                    continue
                socials[platform] = clean_social_url(href)

    # 4. Decompose scripts/styles and extract from visible text
    for tag in soup(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()

    visible_text = soup.get_text(separator=" ")
    clean_text = deobfuscate_text(visible_text)

    for email in EMAIL_REGEX.findall(clean_text):
        emails.add(email)

    for phone in PHONE_REGEX.findall(clean_text):
        phones.add(phone)
