import asyncio
import random
import re
import urllib.parse
import httpx
from bs4 import BeautifulSoup

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
]

def get_random_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
    }

# Substring matches on domain/hostname (catches subdomains like yellowpages.webindia123.com)
IGNORED_HOST_KEYWORDS = {
    "yellowpages", "directory", "listing", "listings", "tripadvisor",
    "zomato", "swiggy", "practo", "lybrate", "holidify", "wanderlog",
    "magicpin", "eazydiner", "dineout", "justdial", "sulekha",
    "webindia123", "threebestrated", "whatshot", "restaurant-guru",
    "venuelook", "stanzaliving", "secretattractions", "mypunepulse",
    "awifiplace", "laptopfriendlycafe", "coffeegearguides", "jetlygo",
    "newplacealert", "clinicspots", "vaidyahub", "hindfiri",
    "wikipedia", "youtube", "facebook", "instagram", "linkedin",
    "twitter", "x.com", "reddit", "yelp", "pinterest", "tiktok",
    "clutch", "goodfirms", "upwork", "fiverr", "glassdoor", "indeed",
    "trustpilot", "crunchbase", "zoominfo", "g2.com", "capterra",
    "magicbricks", "99acres", "housing.com", "nobroker", "squareyards",
    "realestateindia", "zillow", "realtor.com", "redfin", "trulia",
    "rightmove", "zoopla", "proptiger", "makaan", "mapquest"
}

AGGREGATOR_TITLE_PATTERNS = re.compile(
    r"\b(top|best)\s+\d+\b|"
    r"\b\d+\s+(best|top|must[- ]visit|secret|cozy|coziest|favorite|popular|greatest|famous|open|leading)\b|"
    r"\b(list\s+of|directory\s+of|curated\s+by|where\s+to\s+find|where\s+to\s+eat|guide\s+to|complete\s+guide|things\s+to\s+do|rankings\s*\|)\b",
    re.I
)

AGGREGATOR_SNIPPET_PATTERNS = re.compile(
    r"\b(curated\s+by\s+the\s+community|filter\s+by\s+origin|roasteries\s+deliver\s+to|here\s+is\s+the\s+list\s+of|find\s+address,\s+phone\s+number|complete\s+guide)\b",
    re.I
)

def clean_url(raw_url: str) -> str | None:
    """Extract clean domain URL from DuckDuckGo redirect paths."""
    if not raw_url:
        return None

    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url

    if "/l/?" in raw_url:
        parsed = urllib.parse.urlparse(raw_url)
        params = urllib.parse.parse_qs(parsed.query)
        target = params.get("uddg", [None])[0]
        if target:
            raw_url = urllib.parse.unquote(target)

    parsed_domain = urllib.parse.urlparse(raw_url)
    if not parsed_domain.netloc:
        return None

    base_host = parsed_domain.netloc.lower().split(":")[0]

    # Filter out by substring matching (e.g. yellowpages.webindia123.com, zomato.com)
    for kw in IGNORED_HOST_KEYWORDS:
        if kw in base_host:
            return None

    scheme = parsed_domain.scheme or "https"
    return f"{scheme}://{parsed_domain.netloc}"

def is_likely_aggregator(title: str, snippet: str, domain: str) -> bool:
    """Detect if candidate is a listicle, directory, or aggregator blog."""
    if AGGREGATOR_TITLE_PATTERNS.search(title):
        return True
    if AGGREGATOR_SNIPPET_PATTERNS.search(snippet):
        return True
    domain_lower = domain.lower()
    for kw in ["directory", "curated", "wanderlog", "yellowpages", "listings", "alert"]:
        if kw in domain_lower:
            return True
    return False

def build_niche_queries(niche: str, location: str | None = None) -> list[str]:
    """Generate adaptive natural search queries with semantic variations for any business domain."""
    niche_clean = niche.strip().strip("'\"")
    loc = location.strip() if location and location.strip() else ""

    # If user provided a raw custom query with boolean syntax, use directly
    if any(op in niche_clean for op in ["-", "OR", "site:", "AND"]):
        return [f"{niche_clean} {loc}".strip()]

    # Generate domain-appropriate semantic variants
    lower_niche = niche_clean.lower()
    variations = []

    if loc:
        variations.append(f"{niche_clean} {loc}")
        if "cafe" in lower_niche or "coffee" in lower_niche:
            variations.extend([
                f"coffee shop {loc}",
                f"specialty coffee cafe {loc}",
                f"bakery cafe {loc}",
                f"{niche_clean} {loc} menu",
            ])
        elif "clinic" in lower_niche or "doctor" in lower_niche or "hospital" in lower_niche:
            variations.extend([
                f"multispeciality clinic {loc}",
                f"healthcare clinic {loc}",
                f"dental clinic {loc}",
                f"{niche_clean} {loc} appointment",
            ])
        elif "estate" in lower_niche or "realtor" in lower_niche:
            variations.extend([
                f"real estate developers {loc}",
                f"property consultants {loc}",
                f"builders in {loc}",
            ])
        else:
            variations.extend([
                f"{niche_clean} in {loc}",
                f"{niche_clean} services {loc}",
                f"{niche_clean} {loc} contact",
            ])
    else:
        variations.extend([
            f"{niche_clean} official website",
            f"{niche_clean} companies",
            f"{niche_clean}",
        ])

    return variations

def build_niche_query(niche: str, location: str | None = None) -> str:
    """Backward compatibility helper returning the primary query."""
    return build_niche_queries(niche, location)[0]

async def extract_external_domains_from_url(url: str, max_results: int = 20) -> list[dict]:
    """Crawl a specific directory or portal page to extract outbound business websites."""
    discovered: list[dict] = []
    seen_domains: set[str] = set()

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed_source = urllib.parse.urlparse(url)
    source_host = parsed_source.netloc.lower()

    async with httpx.AsyncClient(headers=get_random_headers(), follow_redirects=True, timeout=12.0) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return discovered

            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                full_url = urllib.parse.urljoin(url, href)
                parsed = urllib.parse.urlparse(full_url)

                if not parsed.scheme.startswith("http") or not parsed.netloc:
                    continue

                dest_host = parsed.netloc.lower().split(":")[0]
                if dest_host == source_host or dest_host.endswith("." + source_host):
                    continue

                if any(kw in dest_host for kw in IGNORED_HOST_KEYWORDS):
                    continue

                clean_site = f"{parsed.scheme}://{parsed.netloc}"
                if clean_site in seen_domains:
                    continue

                seen_domains.add(clean_site)
                title = a.get_text(strip=True) or parsed.netloc
                discovered.append({
                    "company_name": title,
                    "website": clean_site,
                    "snippet": f"Discovered on {source_host}",
                })

                if len(discovered) >= max_results:
                    break
        except Exception:
            pass

    return discovered

async def search_leads(
    query_or_queries: str | list[str],
    max_results: int = 20,
    filter_aggregators: bool = True
) -> list[dict]:
    """Scrape DuckDuckGo HTML endpoint with automatic multi-page pagination, rate-limit backoff, and query expansion."""
    url = "https://html.duckduckgo.com/html/"
    discovered: list[dict] = []
    seen_domains: set[str] = set()

    if isinstance(query_or_queries, str):
        queries = [query_or_queries]
    else:
        queries = list(query_or_queries)

    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
        for q in queries:
            if len(discovered) >= max_results:
                break

            form_data = {"q": q}

            # Paginate through DuckDuckGo HTML pages (up to 6 pages per query variation)
            for page in range(6):
                if len(discovered) >= max_results:
                    break

                try:
                    headers = get_random_headers()
                    response = await client.post(url, data=form_data, headers=headers)

                    # If rate limited (202 anomaly challenge), back off with jitter and rotate headers
                    if response.status_code == 202:
                        await asyncio.sleep(random.uniform(1.8, 3.2))
                        headers = get_random_headers()
                        response = await client.post(url, data=form_data, headers=headers)

                    if response.status_code != 200:
                        break

                    soup = BeautifulSoup(response.text, "lxml")
                    results = soup.select(".result")

                    if not results:
                        break

                    for item in results:
                        title_node = item.select_one(".result__title .result__a")
                        snippet_node = item.select_one(".result__snippet")

                        if not title_node or not title_node.get("href"):
                            continue

                        raw_href = title_node["href"]
                        clean_site = clean_url(raw_href)

                        if not clean_site or clean_site in seen_domains:
                            continue

                        company_title = title_node.get_text(strip=True)
                        snippet_text = snippet_node.get_text(strip=True) if snippet_node else ""

                        if filter_aggregators and is_likely_aggregator(company_title, snippet_text, clean_site):
                            continue

                        seen_domains.add(clean_site)
                        discovered.append({
                            "company_name": company_title,
                            "website": clean_site,
                            "snippet": snippet_text,
                        })

                        if len(discovered) >= max_results:
                            break

                    # Locate "Next" pagination form inputs
                    next_inputs = None
                    for form in soup.find_all("form"):
                        inputs = {i.get("name"): i.get("value", "") for i in form.find_all("input") if i.get("name")}
                        if "s" in inputs and ("dc" in inputs or "vqd" in inputs):
                            next_inputs = inputs
                            break

                    if not next_inputs or next_inputs.get("s") == form_data.get("s"):
                        break

                    form_data = next_inputs
                    # Inject friendly delay between pagination sweeps
                    await asyncio.sleep(random.uniform(0.6, 1.2))

                except Exception:
                    break

    return discovered
