import asyncio
import re
import sys
import urllib.parse
from playwright.async_api import async_playwright

async def scrape_maps_no_website(
    niche: str,
    location: str | None = None,
    limit: int = 10,
    headless: bool = False,
    start_with_duckduckgo: bool = True
) -> list[dict]:
    """
    Opens Chrome, navigates via DuckDuckGo to Google Maps for nearby businesses,
    and extracts records for businesses that have NO website.
    """
    query_text = f"{niche.strip()} in {location.strip()}" if location and location.strip() else niche.strip()
    maps_direct_url = f"https://www.google.com/maps/search/{urllib.parse.quote_plus(query_text)}"

    no_website_leads: list[dict] = []
    seen_places: set[str] = set()

    sys.stderr.write(f"[*] Launching Chrome browser (headless={headless})...\n")

    async with async_playwright() as p:
        # Prefer system Google Chrome, fallback to bundled chromium
        try:
            browser = await p.chromium.launch(channel="chrome", headless=headless)
        except Exception:
            browser = await p.chromium.launch(headless=headless)

        context = await browser.new_context(
            viewport={"width": 1280, "height": 850},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # Step 1: DuckDuckGo entry point if enabled
        if start_with_duckduckgo:
            sys.stderr.write(f"[*] Opening DuckDuckGo in Chrome to search for: '{query_text} Google Maps'...\n")
            try:
                await page.goto("https://duckduckgo.com/", wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_selector('input[name="q"], #searchbox_input', timeout=5000)
                await page.fill('input[name="q"], #searchbox_input', f"{query_text} Google Maps")
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(2000)
            except Exception:
                pass

        # Step 2: Navigate directly to Google Maps Search for the query
        sys.stderr.write(f"[*] Navigating to Google Maps search for: '{query_text}'...\n")
        try:
            await page.goto(maps_direct_url, wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            sys.stderr.write(f"[-] Maps navigation error: {e}\n")

        # Handle optional Google cookie/consent dialog if present
        try:
            consent_btn = await page.query_selector('button[aria-label*="Accept all" i], form[action*="consent"] button')
            if consent_btn:
                await consent_btn.click()
                await page.wait_for_timeout(1000)
        except Exception:
            pass

        # Wait for the results feed or place links
        try:
            await page.wait_for_selector('div[role="feed"], a[href*="/maps/place/"]', timeout=15000)
        except Exception:
            sys.stderr.write("[-] Could not find Google Maps results container.\n")
            await browser.close()
            return no_website_leads

        sys.stderr.write(f"[*] Searching Google Maps for businesses with NO website (target={limit})...\n")

        scroll_attempts = 0
        max_scroll_attempts = 25

        while len(no_website_leads) < limit and scroll_attempts < max_scroll_attempts:
            scroll_attempts += 1

            cards = await page.query_selector_all('a[href*="/maps/place/"]')
            if not cards:
                break

            for card in cards:
                if len(no_website_leads) >= limit:
                    break

                href = await card.get_attribute("href") or ""
                # Use clean place key from URL or aria label to avoid duplicate clicks
                place_key = href.split("?")[0] if href else ""
                name_attr = await card.get_attribute("aria-label") or ""

                identifier = place_key or name_attr
                if identifier in seen_places:
                    continue
                seen_places.add(identifier)

                # Check if card already displays an outbound website button before clicking
                parent = await card.evaluate_handle("el => el.closest('div.Nv2PK') || el.parentElement")
                has_external_web = False
                if parent:
                    web_el = await parent.query_selector('a[data-value="Website"], a[aria-label*="website" i]')
                    if web_el:
                        has_external_web = True

                # If website button is already present on the card, skip it!
                if has_external_web:
                    continue

                # Click place to inspect details in the pane
                try:
                    await card.click()
                    await page.wait_for_timeout(1200)
                except Exception:
                    continue

                # Check authoritative website button in the side pane
                authority_btn = await page.query_selector('a[data-item-id="authority"], [data-tooltip="Open website"]')
                website_url = None
                if authority_btn:
                    website_url = await authority_btn.get_attribute("href")

                # If a real website is listed in the pane, skip this business
                if website_url:
                    continue

                # Business has NO website! Extract its full contact info:
                # 1. Name
                name = name_attr
                if not name:
                    title_el = await page.query_selector('h1.DUwDvf, div.fontHeadlineSmall')
                    if title_el:
                        name = (await title_el.inner_text()).strip()

                # 2. Phone
                phone = None
                phone_el = await page.query_selector('button[data-item-id*="phone:"]')
                if phone_el:
                    raw_phone = await phone_el.get_attribute("data-item-id") or ""
                    phone = raw_phone.replace("phone:tel:", "").replace("phone:", "").strip()
                if not phone:
                    phone_aria = await page.query_selector('button[aria-label*="Phone:" i]')
                    if phone_aria:
                        phone = (await phone_aria.get_attribute("aria-label") or "").replace("Phone:", "").strip()

                # 3. Address
                address = None
                addr_el = await page.query_selector('button[data-item-id="address"]')
                if addr_el:
                    addr_text = await addr_el.get_attribute("aria-label") or await addr_el.inner_text()
                    address = addr_text.replace("Address:", "").strip()

                # 4. Rating & Reviews
                rating = None
                review_count = None
                rating_el = await page.query_selector('div.F7nice span[aria-hidden="true"], span.ceNzKf')
                if rating_el:
                    rating_raw = (await rating_el.inner_text()).strip()
                    match_rate = re.search(r"(\d+(?:\.\d+)?)", rating_raw)
                    if match_rate:
                        rating = float(match_rate.group(1))

                reviews_el = await page.query_selector('div.F7nice span[aria-label*="reviews" i], button[jsaction*="pane.rating.moreReviews"]')
                if reviews_el:
                    rev_raw = await reviews_el.get_attribute("aria-label") or await reviews_el.inner_text()
                    match_rev = re.search(r"([\d,]+)", rev_raw)
                    if match_rev:
                        review_count = match_rev.group(1).replace(",", "")

                # 5. Category (avoid generic 'Learn more' buttons)
                category = None
                cat_el = await page.query_selector('button.DkEaL, button[jsaction*="pane.rating.category"]')
                if cat_el:
                    cat_text = (await cat_el.inner_text()).strip()
                    if cat_text.lower() not in ["learn more", "overview", "reviews", "about"]:
                        category = cat_text

                lead_record = {
                    "company_name": name or "Local Business",
                    "category": category or niche,
                    "address": address,
                    "phone_number": phone,
                    "rating": rating,
                    "reviews_count": review_count,
                    "has_website": False,
                    "opportunity": "No website listed on Google Maps",
                    "maps_url": href,
                    "status": "enriched" if (phone or address) else "identified"
                }

                no_website_leads.append(lead_record)
                sys.stderr.write(f"  [+] Found website-less business ({len(no_website_leads)}/{limit}): {lead_record['company_name']} | Phone: {phone or 'N/A'}\n")

            # Scroll down the feed container to load more places
            feed_el = await page.query_selector('div[role="feed"]')
            if feed_el:
                await feed_el.evaluate("el => el.scrollBy(0, 1500)")
                await page.wait_for_timeout(1500)
            else:
                break

        await browser.close()

    sys.stderr.write(f"[+] Maps scan complete. Found {len(no_website_leads)} businesses without a website.\n")
    return no_website_leads
