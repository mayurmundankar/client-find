import argparse
import asyncio
import csv
import json
import os
import re
import sys
import httpx

from discovery import (
    search_leads,
    build_niche_queries,
    extract_external_domains_from_url
)
from crawler import crawl_domain
from validator import has_mx_record
from maps_scraper import scrape_maps_no_website

async def process_candidate(client: httpx.AsyncClient, lead: dict, sem: asyncio.Semaphore, check_mx: bool = True) -> dict:
    async with sem:
        meta = await crawl_domain(client, lead["website"])
        mx_status = has_mx_record(lead["website"]) if check_mx else None

        enriched = bool(meta["emails"] or meta["phone_numbers"] or meta["social_profiles"])
        return {
            "company_name": lead["company_name"],
            "website": lead["website"],
            "summary": lead["snippet"],
            "emails": meta["emails"],
            "phone_numbers": meta["phone_numbers"],
            "social_profiles": meta["social_profiles"],
            "has_mx_configured": mx_status,
            "status": "enriched" if enriched else "unresponsive"
        }

def is_url(target: str) -> bool:
    """Check if input string is a URL rather than an industry/niche keyword."""
    target = target.strip()
    if target.startswith(("http://", "https://")):
        return True
    if re.match(r"^[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(/.*)?$", target):
        return True
    return False

def slugify(text: str) -> str:
    """Turn text into a safe filename slug."""
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "_", text)

async def run(
    target: str,
    location: str | None,
    limit: int,
    concurrency: int,
    out_file: str | None,
    out_format: str,
    check_mx: bool,
    filter_aggregators: bool,
    use_maps: bool = False,
    headless: bool = False
):
    target = target.strip()

    # Mode 1: Google Maps Website-less Prospecting Mode
    if use_maps:
        sys.stderr.write(f"[*] Google Maps Mode: Searching for '{target}'" + (f" in '{location}'" if location else "") + f" without a website...\n")
        results = await scrape_maps_no_website(
            niche=target,
            location=location,
            limit=limit,
            headless=headless,
            start_with_duckduckgo=True
        )

    # Mode 2: URL / Directory Crawl Mode
    elif is_url(target):
        sys.stderr.write(f"[*] Target is a web URL. Extracting business links from: {target} (limit={limit})...\n")
        candidates = await extract_external_domains_from_url(url=target, max_results=limit)
        results = await _enrich_candidates(candidates, concurrency, check_mx)

    # Mode 3: Niche / Industry Search Mode
    else:
        queries = build_niche_queries(target, location=location)
        sys.stderr.write(f"[*] Target domain/niche: '{target}'" + (f" in '{location}'" if location else "") + f"\n")
        sys.stderr.write(f"[*] Executing discovery with multi-page pagination (target limit={limit})...\n")
        candidates = await search_leads(query_or_queries=queries, max_results=limit, filter_aggregators=filter_aggregators)
        results = await _enrich_candidates(candidates, concurrency, check_mx)

    if not results:
        sys.stderr.write("[-] No leads found matching criteria.\n")
        empty_data = "[]" if out_format == "json" else ""
        if out_file:
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(empty_data)
        else:
            sys.stdout.write(empty_data + "\n")
        return

    if out_format == "csv":
        output_data = export_csv(results, is_maps=use_maps)
    else:
        output_data = json.dumps(results, indent=2, ensure_ascii=False)

    if out_file:
        with open(out_file, "w", encoding="utf-8", newline="" if out_format == "csv" else None) as f:
            f.write(output_data)
        sys.stderr.write(f"[+] Successfully saved {len(results)} leads to {out_file}\n")
    else:
        sys.stdout.write(output_data + "\n")

async def _enrich_candidates(candidates: list[dict], concurrency: int, check_mx: bool) -> list[dict]:
    sys.stderr.write(f"[+] Discovered {len(candidates)} prospective business domains.\n")
    if not candidates:
        return []

    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=concurrency)
    transport = httpx.AsyncHTTPTransport(retries=1)

    sys.stderr.write(f"[*] Deep scanning businesses with concurrency={concurrency}...\n")
    async with httpx.AsyncClient(limits=limits, transport=transport, timeout=12.0, follow_redirects=True) as client:
        tasks = [process_candidate(client, lead, sem, check_mx=check_mx) for lead in candidates]
        results = await asyncio.gather(*tasks)

    enriched_count = sum(1 for r in results if r["status"] == "enriched")
    sys.stderr.write(f"[+] Scan complete. {enriched_count}/{len(results)} businesses enriched.\n")
    return results

def export_csv(results: list[dict], is_maps: bool = False) -> str:
    import io
    output = io.StringIO()
    writer = csv.writer(output)

    if is_maps:
        writer.writerow([
            "company_name", "category", "address", "phone_number",
            "rating", "reviews_count", "has_website", "opportunity", "maps_url", "status"
        ])
        for r in results:
            writer.writerow([
                r.get("company_name", ""),
                r.get("category", ""),
                r.get("address", ""),
                r.get("phone_number", ""),
                r.get("rating", ""),
                r.get("reviews_count", ""),
                r.get("has_website", False),
                r.get("opportunity", ""),
                r.get("maps_url", ""),
                r.get("status", "")
            ])
    else:
        writer.writerow([
            "company_name", "website", "summary", "emails",
            "phone_numbers", "whatsapp", "linkedin", "twitter", "instagram", "facebook",
            "has_mx_configured", "status"
        ])
        for r in results:
            socials = r.get("social_profiles", {})
            writer.writerow([
                r.get("company_name", ""),
                r.get("website", ""),
                r.get("summary", ""),
                "; ".join(r.get("emails", [])),
                "; ".join(r.get("phone_numbers", [])),
                socials.get("whatsapp", ""),
                socials.get("linkedin", ""),
                socials.get("twitter", ""),
                socials.get("instagram", ""),
                socials.get("facebook", ""),
                r.get("has_mx_configured", ""),
                r.get("status", "")
            ])
    return output.getvalue()

def interactive_prompt():
    """Prompt user when cli.py is executed without arguments."""
    sys.stderr.write("\n" + "=" * 60 + "\n")
    sys.stderr.write("   Zero-API Client Finder & Lead Pipeline (Interactive)\n")
    sys.stderr.write("=" * 60 + "\n\n")

    try:
        sys.stderr.write("Select Mode:\n")
        sys.stderr.write("  [1] Standard Web Discovery & Deep Crawl (Default)\n")
        sys.stderr.write("  [2] Google Maps (Open Chrome, find businesses with NO website)\n")
        mode_choice = input("[?] Choose mode [1]: ").strip()
        use_maps = (mode_choice == "2")

        domain = input("[?] Enter domain/niche (e.g. Cafe, Clinic, Real Estate): ").strip()
        while not domain:
            domain = input("[!] Field required. Enter domain/niche: ").strip()

        location = None
        if not is_url(domain):
            loc_input = input("[?] Target location/city (e.g. Pune, Berlin, London): ").strip()
            if loc_input:
                location = loc_input

        limit_str = input("[?] Number of leads to find [10]: ").strip()
        limit = int(limit_str) if limit_str.isdigit() else 10

        mode_prefix = "no_website_maps" if use_maps else "leads"
        slug_parts = [domain]
        if location:
            slug_parts.append(location)
        slug_parts.append(mode_prefix)
        default_file = f"{slugify('_'.join(slug_parts))}.json"

        out_file = input(f"[?] Output file path [{default_file}]: ").strip() or default_file

        return domain, location, limit, out_file, use_maps
    except (KeyboardInterrupt, EOFError):
        sys.stderr.write("\n[!] Operation cancelled by user.\n")
        sys.exit(0)

def main():
    parser = argparse.ArgumentParser(
        description="Zero-API Local Client Finder: Discover and enrich business leads by industry domain, URL, or Google Maps.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("target", nargs="?", default=None, help="Domain/niche (e.g. 'Cafe') or directory URL")
    parser.add_argument("-n", "--niche", "--domain", dest="niche", default=None, help="Industry domain/niche (e.g. 'Clinic', 'Real Estate')")
    parser.add_argument("-q", "--query", dest="query", default=None, help="Direct search query")
    parser.add_argument("-loc", "--location", default=None, help="Target geo/city (e.g. 'Pune', 'Berlin', 'Austin')")
    parser.add_argument("-l", "--limit", type=int, default=10, help="Max candidates to extract")
    parser.add_argument("-c", "--concurrency", type=int, default=5, help="Concurrent HTTP requests")
    parser.add_argument("-o", "--output", default=None, help="Output file path (e.g. leads.json). If omitted, auto-generates descriptive file")
    parser.add_argument("--format", choices=["json", "csv"], default=None, help="Output format (json or csv)")
    parser.add_argument("--skip-mx", action="store_true", help="Skip DNS MX record validation")
    parser.add_argument("--include-aggregators", action="store_true", help="Include listicles, directories, and aggregator platforms")
    parser.add_argument("--maps", action="store_true", help="Launch Chrome with DuckDuckGo, search Google Maps, and extract businesses without a website")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (defaults to visible Chrome window)")

    args = parser.parse_args()

    target = args.target or args.niche or args.query
    location = args.location
    limit = args.limit
    out_file = args.output
    use_maps = args.maps

    if not target:
        if sys.stdin.isatty():
            target, location, limit, out_file, use_maps = interactive_prompt()
        else:
            parser.print_help()
            sys.exit(1)

    if not out_file:
        mode_prefix = "no_website_maps" if use_maps else "leads"
        slug_parts = [target]
        if location:
            slug_parts.append(location)
        slug_parts.append(mode_prefix)
        out_file = f"{slugify('_'.join(slug_parts))}.json"

    out_format = args.format
    if not out_format:
        if out_file and out_file.lower().endswith(".csv"):
            out_format = "csv"
        else:
            out_format = "json"

    asyncio.run(run(
        target=target,
        location=location,
        limit=limit,
        concurrency=args.concurrency,
        out_file=out_file,
        out_format=out_format,
        check_mx=not args.skip_mx,
        filter_aggregators=not args.include_aggregators,
        use_maps=use_maps,
        headless=args.headless
    ))

if __name__ == "__main__":
    main()
