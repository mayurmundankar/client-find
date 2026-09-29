# Zero-API Client Finder & Lead Enrichment CLI

A lightweight, high-performance, asynchronous CLI pipeline to discover and enrich business leads directly from open web HTML interfaces without paid third-party APIs or API keys.

---

## Architecture Overview

```text
               +----------------------------------+
               |     CLI Input (Query, Target)    |
               +-----------------+----------------+
                                 |
                                 v
               +----------------------------------+
               |  Discovery: Search Engine HTML   |
               | (DuckDuckGo Lite / HTML Gateway) |
               +-----------------+----------------+
                                 |  [Discovered Domains]
                                 v
               +----------------------------------+
               | Async Deep Crawler (httpx + bs4) |
               | Root, /contact, /about, /team    |
               +-----------------+----------------+
                                 |
                                 v
               +----------------------------------+
               |   Sanitization & MX Validation   |
               | (dnspython, Regex, De-obfuscate) |
               +-----------------+----------------+
                                 |
                                 v
               +----------------------------------+
               |      JSON / CSV File Output      |
               +----------------------------------+
```

---

## Directory Structure

```text
client-find/
├── .venv/               # Python virtual environment
├── cli.py               # Asynchronous orchestrator & CLI entrypoint
├── crawler.py           # Deep extraction crawler for contacts & socials
├── discovery.py         # Search engine scraper (DuckDuckGo HTML)
├── validator.py         # DNS MX record resolver
├── requirements.txt     # Python dependencies
└── README.md            # Documentation
```

---

## Setup & Installation

1. **Activate Virtual Environment** (already created):
   - Windows PowerShell:
     ```powershell
     .\.venv\Scripts\Activate.ps1
     ```
   - Windows CMD:
     ```cmd
     .\.venv\Scripts\activate.bat
     ```
   - Linux / macOS:
     ```bash
     source .venv/bin/activate
     ```

2. **Install Dependencies** (already installed in `.venv`):
   ```bash
   pip install -r requirements.txt
   ```

---

## Usage Examples

### 1. Domain / Industry Mode (Recommended)
Simply pass the industry/domain (e.g. `real estate`, `dentists`, `coffee roasters`):
```bash
# Pass industry directly
python cli.py "real estate"

# Pass industry + location
python cli.py "real estate" --location "Pune" --limit 10

# Pass industry + export to specific file
python cli.py "law firms" -loc "Berlin" -o law_firms.json
```

### 2. Interactive Guided Mode
Simply run the script with no arguments, and follow the interactive prompts:
```bash
python cli.py
```
```text
==========================================================
   Zero-API Client Finder & Lead Pipeline (Interactive)
==========================================================
[?] Enter domain/niche (e.g. real estate, law firm) or URL: real estate
[?] Target location/city (optional, press Enter to skip): London
[?] Number of leads to find [10]: 15
[?] Output file path [real_estate_london_leads.json]:
```

### 3. Directory / Portal URL Crawl Mode
If you provide a direct website or directory URL, the tool will crawl that page, find all outbound company website links, and enrich each business:
```bash
python cli.py https://example-directory.com/members -l 20 -o directory_leads.json
```

### 4. Google Maps Website-less Prospecting Mode (New Feature!)
Opens Chrome (visibly or headless), searches DuckDuckGo & Google Maps for nearby businesses, filters for businesses that **do NOT have a website**, and saves their direct phone numbers, addresses, ratings, and Maps links to JSON:
```bash
# Visible Chrome browser (default)
python cli.py "Cafe" --location "Pune" --limit 10 --maps

# Background headless mode
python cli.py "Clinic" --location "Pune" --limit 10 --maps --headless

# Dental clinics without websites saved to specific file
python cli.py "Dentist" -loc "Berlin" -l 15 --maps -o dentists_no_website.json
```

### 5. Advanced Search Query Mode
For full manual control over boolean search operators:
```bash
python cli.py -q '"packaging design" "London" "contact" -blog' -l 10 -c 5 -o packaging.json
```

---

## Output Data Schema

```json
[
  {
    "company_name": "Sample Artisan Roasters",
    "website": "https://sampleartisanroasters.in",
    "summary": "Specialty coffee roastery sourcing ethically grown single-origin Arabica beans.",
    "emails": [
      "orders@sampleartisanroasters.in",
      "wholesale@sampleartisanroasters.in"
    ],
    "phone_numbers": [
      "+91 98201 12345"
    ],
    "social_profiles": {
      "instagram": "https://instagram.com/sampleartisanroasters",
      "linkedin": "https://linkedin.com/company/sample-artisan-roasters"
    },
    "has_mx_configured": true,
    "status": "enriched"
  }
]
```
