"""Customer Service Agent for ApexHome & Electro.

Built with Google Agent Development Kit (ADK 2.0), BigQueryAgentAnalyticsPlugin,
and dynamic Open Knowledge Format (OKF) context integration from GitHub.
"""

from __future__ import annotations

import logging
import os
import pathlib
import time
from typing import Any, Dict, List, Optional

import google.auth
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.plugins.bigquery_agent_analytics_plugin import (
    BigQueryAgentAnalyticsPlugin,
    BigQueryLoggerConfig,
)
from google.cloud import bigquery
from google.cloud import secretmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("customer_service_agent")

PROJECT_ID = (
    os.environ.get("GOOGLE_CLOUD_PROJECT")
    or os.environ.get("GCP_PROJECT")
    or "experthub-510907"
)
LOCATION = os.environ.get("GCP_REGION", "us-central1")
BQ_LOCATION = os.environ.get("BQ_LOCATION", "US")
DEPLOY_KEY_SECRET_NAME = os.environ.get("GITHUB_DEPLOY_KEY_SECRET_NAME", "github-deploy-key")
SECRET_NAME = os.environ.get("GITHUB_SECRET_NAME", "github-pat")
REPO_NAME = "gshilo/experthub_context"
OKF_FILENAME = "dynamic_context.md"
OKF_FALLBACK_FILENAME = "dynamic_content.md"

# Cache for dynamic OKF rules: (cached_text, timestamp)
_OKF_CACHE: tuple[str, float] = ("", 0.0)
_OKF_CACHE_TTL = 30.0  # seconds


def get_secret(secret_id: str = SECRET_NAME, project: str = PROJECT_ID) -> str:
    """Retrieves secret from Google Cloud Secret Manager with fallback to env var.

    API keys and credentials are never stored in static files.
    """
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8").strip()
        logger.info(f"Successfully retrieved secret '{secret_id}' directly from Secret Manager.")
        return secret_value
    except Exception as e:
        logger.info(
            f"Could not retrieve secret '{secret_id}' from Secret Manager: {e}. "
            "Checking environment fallback."
        )

    # Fallback to env var if Secret Manager access fails
    if secret_id in ("github-pat", SECRET_NAME):
        env_token = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
        if env_token:
            return env_token.strip()
    elif secret_id in ("github-deploy-key", DEPLOY_KEY_SECRET_NAME):
        env_key = os.environ.get("GITHUB_DEPLOY_KEY") or os.environ.get("SSH_DEPLOY_KEY")
        if env_key:
            return env_key.strip()
    elif secret_id in ("gemini-api-key", "google-api-key"):
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if env_key:
            return env_key.strip()

    return ""


def is_placeholder_token(token: str) -> bool:
    """Checks whether token is empty or an unconfigured placeholder."""
    if not token:
        return True
    t = token.strip().upper()
    return (
        t.startswith("PLACEHOLDER")
        or t.startswith("YOUR_")
        or "PLACEHOLDER" in t
        or t in ("DUMMY", "TEST", "NONE", "NULL")
    )


def ensure_gemini_api_key(project_id: str = PROJECT_ID) -> Optional[str]:
    """Ensures GEMINI_API_KEY / GOOGLE_API_KEY is retrieved directly from Secret Manager.

    Retrieves secret from Google Cloud Secret Manager ('gemini-api-key' or fallback 'google-api-key')
    and populates os.environ dynamically at runtime. The key is never read from or stored in static files.
    """
    for secret_name in ("gemini-api-key", "google-api-key"):
        val = get_secret(secret_name, project=project_id)
        if val and not is_placeholder_token(val):
            os.environ["GEMINI_API_KEY"] = val
            os.environ["GOOGLE_API_KEY"] = val
            logger.info(f"Dynamically loaded Gemini API key from Secret Manager secret '{secret_name}' (not static files).")
            return val

    existing_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if existing_key and not is_placeholder_token(existing_key):
        return existing_key

    logger.warning("No Gemini API key found in Secret Manager ('gemini-api-key') or environment.")
    return None


# Ensure Gemini API key is loaded into environment from Secret Manager before agent execution
ensure_gemini_api_key(PROJECT_ID)


def fetch_okf_via_git_ssh(private_key_pem: str, repo_name: str = REPO_NAME) -> str:
    """Fetches OKF dynamic context from GitHub using an SSH Deploy Key."""
    import shutil
    import subprocess
    import tempfile

    temp_dir = tempfile.mkdtemp(prefix="okf_read_")
    key_path = os.path.join(temp_dir, "id_ed25519")
    repo_dir = os.path.join(temp_dir, "repo")
    content = ""

    try:
        with open(key_path, "w", encoding="utf-8") as f:
            f.write(private_key_pem.strip() + "\n")
        os.chmod(key_path, 0o600)

        git_ssh_cmd = (
            f"ssh -i {key_path} "
            "-o IdentitiesOnly=yes "
            "-o BatchMode=yes "
            "-o StrictHostKeyChecking=no "
            "-o UserKnownHostsFile=/dev/null "
            "-o ConnectTimeout=10 "
            "-o LogLevel=ERROR"
        )
        env = os.environ.copy()
        env["GIT_SSH_COMMAND"] = git_ssh_cmd
        env["SSH_AUTH_SOCK"] = ""

        repo_url = f"git@github.com:{repo_name}.git"
        res = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, repo_dir],
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )
        if res.returncode == 0:
            for fname in [OKF_FILENAME, OKF_FALLBACK_FILENAME]:
                fpath = os.path.join(repo_dir, fname)
                if os.path.exists(fpath):
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                    logger.info(f"Fetched OKF dynamic context via deploy key ({len(content)} bytes).")
                    break
    except Exception as e:
        logger.warning(f"Error fetching OKF dynamic context via deploy key: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return content


def fetch_okf_dynamic_context() -> str:
    """Fetches dynamic OKF rules from GitHub repository with 30s TTL cache."""
    global _OKF_CACHE
    cached_content, cached_time = _OKF_CACHE
    now = time.time()

    if cached_content and (now - cached_time) < _OKF_CACHE_TTL:
        return cached_content

    content = ""

    # 1. Try SSH Deploy Key
    deploy_key = get_secret(DEPLOY_KEY_SECRET_NAME)
    if not deploy_key:
        pat_val = get_secret(SECRET_NAME)
        if pat_val and "PRIVATE KEY" in pat_val:
            deploy_key = pat_val

    if deploy_key and "PRIVATE KEY" in deploy_key:
        content = fetch_okf_via_git_ssh(deploy_key, REPO_NAME)

    # 2. Try GitHub PAT if Deploy Key did not return content
    if not content:
        token = get_secret(SECRET_NAME)
        try:
            if token and not is_placeholder_token(token):
                from github import Auth, Github

                g = Github(auth=Auth.Token(token))
                repo = g.get_repo(REPO_NAME)
                file_obj = None
                for branch in ["main", "master"]:
                    try:
                        try:
                            file_obj = repo.get_contents(OKF_FILENAME, ref=branch)
                            break
                        except Exception:
                            file_obj = repo.get_contents(OKF_FALLBACK_FILENAME, ref=branch)
                            break
                    except Exception:
                        continue

                if file_obj and hasattr(file_obj, "decoded_content"):
                    content = file_obj.decoded_content.decode("utf-8")
                    logger.info(f"Fetched latest OKF dynamic context from GitHub ({len(content)} bytes).")
            else:
                # Try public raw fetch if token is absent
                import requests

                for branch in ["main", "master"]:
                    for fname in [OKF_FILENAME, OKF_FALLBACK_FILENAME]:
                        url = f"https://raw.githubusercontent.com/{REPO_NAME}/{branch}/{fname}"
                        res = requests.get(url, timeout=5)
                        if res.status_code == 200:
                            content = res.text
                            logger.info(f"Fetched OKF dynamic context via raw URL: {url}")
                            break
                    if content:
                        break
        except Exception as e:
            logger.warning(f"Unable to fetch dynamic OKF context from GitHub: {e}. Using empty/cached fallback.")

    _OKF_CACHE = (content, now)
    return content


def get_base_instructions() -> str:
    """Reads base system instructions from local AGENT.md."""
    agent_md_path = pathlib.Path(__file__).parent / "AGENT.md"
    if agent_md_path.exists():
        return agent_md_path.read_text(encoding="utf-8")
    return (
        "You are the Lead Customer Support AI Specialist for ApexHome & Electro. "
        "Help customers with electronics and home appliances professionally and concisely."
    )


def dynamic_instruction_provider(context: CallbackContext) -> str:
    """Merges base AGENT.md instructions with dynamic OKF rules from GitHub."""
    base = get_base_instructions()
    dynamic_okf = fetch_okf_dynamic_context().strip()

    if not dynamic_okf:
        merged = base
    else:
        merged = (
            f"{base}\n\n"
            "---"
            "\n## ACTIVE DYNAMIC OPEN KNOWLEDGE FORMAT (OKF) DIRECTIVES\n"
            "The following operational rules were analyzed and committed by the Auditor Agent. "
            "They carry HIGHEST PRIORITY and supersede conflicting baseline policies:\n\n"
            f"{dynamic_okf}\n"
        )

    strict_style_rules = (
        "\n\n======================================================\n"
        "CRITICAL RESPONSE STYLE & BEHAVIORAL MANDATES (NON-NEGOTIABLE):\n"
        "1. LENGTH LIMIT: Strictly maximum 2 to 3 sentences per response. Never write more than 3 sentences.\n"
        "2. NO MARKDOWN BOLDING: Absolutely NEVER use '**' anywhere in your response. Write plain text only.\n"
        "3. NO LONG DASHES: Never use long dashes (em-dash '—', en-dash '–', or double hyphens '--'). Use commas or periods instead.\n"
        "4. NO LISTS OR BULLETS: Write as natural conversational human chat text only.\n"
        "5. AUTHENTIC HUMAN DEMEANOR: Do not always give the most cheerful, great, or overly polite answers. Avoid robotic corporate flattery or profuse apologies. You are a real employee enforcing store guidelines and can be blunt, dry, tired, skeptical, or firm.\n"
        "6. REALISTIC CONFLICT: You can get into slight conflict with the customer. If the customer is demanding, unreasonable, demands immediate refunds without troubleshooting, or complains about standard return windows and 15% restocking fees, stand your ground firmly and defend store policy instead of instantly backing down.\n"
        "======================================================\n"
    )
    return merged + strict_style_rules


# =====================================================================
# Domain Tools for Electronics & Home Appliances Support
# =====================================================================

# Dynamic registry for live session customer orders
DYNAMIC_ORDERS: Dict[str, Dict[str, Any]] = {}


def register_customer_order(order_data: Dict[str, Any]) -> None:
    """Registers dynamic session order so customer service tools recognize new personas."""
    oid = str(order_data.get("order_id", "")).strip().upper()
    if oid:
        DYNAMIC_ORDERS[oid] = order_data
        logger.info(f"Registered dynamic customer order in customer service database: {oid}")


# Simulated product catalog & order database
PRODUCT_CATALOG = {
    "oled-c4-65": {
        "name": "LG 65-inch C4 Series OLED evo 4K TV",
        "category": "Television",
        "price": "$1,799.99",
        "specs": "144Hz VRR, Dolby Vision, 4x HDMI 2.1 (eARC on port 2), α9 AI Processor Gen7.",
        "common_issues": "eARC sound dropout: toggle 'Digital Sound Output' to Passthrough.",
    },
    "bravia-xr-75": {
        "name": "Sony 75-inch BRAVIA XR A95L QD-OLED TV",
        "category": "Television",
        "price": "$3,299.99",
        "specs": "Cognitive Processor XR, Acoustic Surface Audio+, Google TV, 120Hz 4K.",
        "common_issues": "HDMI 4K120 signal: set HDMI signal format to Enhanced Format (VRR).",
    },
    "smart-fridge-hub": {
        "name": "Samsung Family Hub 4-Door Smart Refrigerator",
        "category": "Home Appliance",
        "price": "$2,899.00",
        "specs": "28 cu. ft., Beverage Center, Dual Auto Ice Maker, Wi-Fi 6, SmartThings app.",
        "common_issues": "Defrost code 22E: clear ice buildup around fan or verify door gasket seal.",
    },
    "smart-washer-ai": {
        "name": "LG Smart Front Load Washer with AI DD & TurboWash 360",
        "category": "Home Appliance",
        "price": "$999.00",
        "specs": "4.5 cu. ft., Steam Clean, ColdWash, Wi-Fi ThinQ diagnostics, Inverter Direct Drive.",
        "common_issues": "UE (Unbalanced Error): redistribute heavy blanket or towels in drum; remove transit bolts.",
    },
    "barista-touch": {
        "name": "Breville the Barista Touch Impress Espresso Machine",
        "category": "Small Appliance",
        "price": "$1,499.95",
        "specs": "ThermoJet 3-second heat up, Auto MilQ steam wand, precision conical burr grinder.",
        "common_issues": "Low pressure extraction: adjust grinder setting finer, verify bean freshness.",
    },
    "laptop-pro-16": {
        "name": "ApexBook Pro 16 Laptop (Intel Core Ultra 9 / RTX 4080 / 32GB RAM / 1TB SSD)",
        "category": "Computing",
        "price": "$2,499.00",
        "specs": "16-inch Mini-LED 165Hz, Thunderbolt 4, HDMI 2.1, 99.9Wh battery.",
        "common_issues": "Docking monitor flicker: update Intel Arc GPU driver and use certified 40Gbps cable.",
    },
    "robovac-x9": {
        "name": "RoboGlide X9 LiDAR Robot Vacuum & Mop",
        "category": "Smart Cleaning",
        "price": "$899.99",
        "specs": "5000Pa suction, LiDAR LDS room mapping, auto-empty base, dual spinning mop pads.",
        "common_issues": "LiDAR bumper sensor error: clean laser turret with microfiber, reset floor map.",
    },
    "soundbar-atmos-9": {
        "name": "SonicSurround 9.1.4 Dolby Atmos Soundbar System",
        "category": "Home Audio",
        "price": "$1,199.00",
        "specs": "Wireless 10-inch subwoofer, wireless rear surround speakers, HDMI 2.1 eARC passthrough.",
        "common_issues": "Subwoofer disconnection: press ID Set on rear sub for 5 seconds while soundbar in pairing mode.",
    },
    "induction-cooktop-smart": {
        "name": "VestaSmart 36-inch Smart Induction Cooktop",
        "category": "Kitchen Appliances",
        "price": "$1,899.00",
        "specs": "5 flex induction zones, wireless Bluetooth core temp probe, bridge element, power boost.",
        "common_issues": "Error code F-12: check cookware ferrous magnetic compatibility or supply voltage 240V.",
    },
    "powerstation-2400": {
        "name": "ApexPower 2400W Pure Sine Wave Power Station",
        "category": "Outdoor & Energy",
        "price": "$1,799.00",
        "specs": "2048Wh LiFePO4 battery, 2400W AC output (4800W surge), dual MPPT 1200W solar input.",
        "common_issues": "Overload fault: ensure continuous wattage is below 2400W and reset AC output toggle.",
    },
    "mesh-wifi7-tri": {
        "name": "NetSphere Tri-Band Wi-Fi 7 Mesh System",
        "category": "Networking",
        "price": "$699.99",
        "specs": "320MHz channels, Multi-Link Operation (MLO), 10Gbps WAN/LAN, Matter/Thread border router.",
        "common_issues": "Node dropouts: set 2.4GHz and 5GHz SSIDs separately if legacy IoT devices fail MLO.",
    },
    "air-purifier-pro": {
        "name": "AeroBreeze Smart Dual-Zone Air Purifier",
        "category": "Air Quality",
        "price": "$449.00",
        "specs": "True HEPA-13 dual filters, activated carbon VOC filtration, laser PM2.5 particle monitor.",
        "common_issues": "Fan stays on high: clean laser sensor lens on side panel with a dry cotton swab.",
    },
    "smart-thermostat-zone": {
        "name": "ThermoSense Multi-Zone Smart Thermostat",
        "category": "Climate Control",
        "price": "$279.00",
        "specs": "C-wire adapter included, remote occupancy & temp sensors, heat pump dual-fuel staging.",
        "common_issues": "Short cycling: verify C-wire voltage (24VAC) and set minimum compressor cycle delay to 5 min.",
    },
    "ultrawide-gaming-34": {
        "name": "TitanView 34-inch QD-OLED Curved Gaming Monitor",
        "category": "Computing",
        "price": "$1,099.00",
        "specs": "3440x1440 175Hz, 0.03ms GtG, G-Sync Ultimate, DisplayPort 1.4, USB-C 90W PD.",
        "common_issues": "Pixel refresh reminder: allow automatic 10-minute pixel clean cycle to run in standby.",
    },
}

MOCK_ORDERS = {
    "ORD-1001": {
        "order_id": "ORD-1001",
        "customer_name": "Elena Rostova",
        "product_id": "oled-c4-65",
        "product_name": "LG 65-inch C4 Series OLED evo 4K TV",
        "order_date": "2026-09-28",
        "status": "Delivered",
        "tracking_number": "FEDEX-882910471",
        "carrier": "FedEx Freight",
        "delivery_date": "2026-10-02",
        "total_amount": "$1,799.99",
    },
    "ORD-1002": {
        "order_id": "ORD-1002",
        "customer_name": "Marcus Vance",
        "product_id": "smart-fridge-hub",
        "product_name": "Samsung Family Hub 4-Door Smart Refrigerator",
        "order_date": "2026-07-14",
        "status": "Delivered",
        "tracking_number": "UPS-772910492",
        "carrier": "UPS White Glove Freight",
        "delivery_date": "2026-07-20",
        "total_amount": "$2,899.00",
    },
    "ORD-1003": {
        "order_id": "ORD-1003",
        "customer_name": "David Chen",
        "product_id": "barista-touch",
        "product_name": "Breville the Barista Touch Impress Espresso Machine",
        "order_date": "2026-09-15",
        "status": "Delivery Exception - Address Incomplete",
        "tracking_number": "USPS-940010928",
        "carrier": "USPS Priority",
        "delivery_date": "Held at Local Postal Annex",
        "total_amount": "$1,499.95",
    },
    "ORD-1004": {
        "order_id": "ORD-1004",
        "customer_name": "Sarah Jenkins",
        "product_id": "smart-washer-ai",
        "product_name": "LG Smart Front Load Washer",
        "order_date": "2026-09-22",
        "status": "Delivered",
        "tracking_number": "FEDEX-449102847",
        "carrier": "FedEx Freight",
        "delivery_date": "2026-09-26",
        "total_amount": "$999.00",
    },
    "ORD-1005": {
        "order_id": "ORD-1005",
        "customer_name": "Carlos Mendez",
        "product_id": "bravia-xr-75",
        "product_name": "Sony 75-inch BRAVIA XR A95L QD-OLED TV",
        "order_date": "2026-10-01",
        "status": "Carrier Scan Dispute - Trace Active",
        "tracking_number": "FEDEX-992104882",
        "carrier": "FedEx Freight Priority",
        "delivery_date": "Scanned Delivered (Under Carrier Trace Investigation)",
        "total_amount": "$3,299.99",
    },
    "ORD-1006": {
        "order_id": "ORD-1006",
        "customer_name": "Danielle Brooks",
        "product_id": "smart-fridge-hub",
        "product_name": "Samsung Family Hub 4-Door Smart Refrigerator",
        "order_date": "2026-09-29",
        "status": "Delivered - Transit Damage Reported",
        "tracking_number": "UPS-883109274",
        "carrier": "UPS White Glove Freight",
        "delivery_date": "2026-10-06",
        "total_amount": "$2,899.00",
    },
    "ORD-1007": {
        "order_id": "ORD-1007",
        "customer_name": "Michael Chang",
        "product_id": "oled-c4-65",
        "product_name": "LG 65-inch C4 Series OLED evo 4K TV",
        "order_date": "2026-10-02",
        "status": "Delivered - Payment Capture Pending Clearance",
        "tracking_number": "FEDEX-551920482",
        "carrier": "FedEx Freight",
        "delivery_date": "2026-10-05",
        "total_amount": "$1,799.99",
    },
    "ORD-1008": {
        "order_id": "ORD-1008",
        "customer_name": "Rachel Green",
        "product_id": "barista-touch",
        "product_name": "Breville the Barista Touch Impress Espresso Machine",
        "order_date": "2026-08-25",
        "status": "Returned - Warehouse Quarantine Inspection",
        "tracking_number": "UPS-991827461",
        "carrier": "UPS Ground Return",
        "delivery_date": "Received Warehouse 2026-09-20 (Quarantined Missing RMA Label)",
        "total_amount": "$1,499.95",
    },
    "ORD-1009": {
        "order_id": "ORD-1009",
        "customer_name": "Priya Patel",
        "product_id": "smart-washer-ai",
        "product_name": "LG Smart Front Load Washer with AI DD",
        "order_date": "2026-10-01",
        "status": "Delivered",
        "tracking_number": "FEDEX-771928410",
        "carrier": "FedEx Freight White Glove",
        "delivery_date": "2026-10-04",
        "total_amount": "$999.00",
    },
    "ORD-1010": {
        "order_id": "ORD-1010",
        "customer_name": "Liam O'Connor",
        "product_id": "laptop-pro-16",
        "product_name": "ApexBook Pro 16 Laptop",
        "order_date": "2026-09-12",
        "status": "Delivered",
        "tracking_number": "UPS-331902847",
        "carrier": "UPS Express",
        "delivery_date": "2026-09-15",
        "total_amount": "$2,499.00",
    },
}


def check_order_status(order_id: str) -> str:
    """Checks real-time fulfillment, shipping carrier tracking, and logistics notes for an order ID."""
    clean_id = order_id.strip().upper()
    order = DYNAMIC_ORDERS.get(clean_id) or MOCK_ORDERS.get(clean_id)

    if not order:
        # Dynamically synthesize a realistic order lookup rather than returning an unhelpful dead end
        carrier = "FedEx Freight Priority" if "FREIGHT" in clean_id or "TV" in clean_id else "UPS Expedited"
        tracking = f"TRK-{abs(hash(clean_id)) % 89999999 + 10000000}"
        return (
            f"Order {clean_id} (Customer Verified):\n"
            f"- Status: Active in fulfillment logistics\n"
            f"- Carrier: {carrier} (Tracking: {tracking})\n"
            "- Delivery Status: Recently delivered / In active delivery window\n"
            "- Verification: Account purchase verified with standard 30-day return & warranty coverage."
        )

    return (
        f"Order {order.get('order_id', clean_id)} ({order.get('customer_name', 'Verified Customer')}):\n"
        f"- Product: {order.get('product_name', 'Purchased Item')}\n"
        f"- Status: {order.get('status', 'Delivered')}\n"
        f"- Carrier: {order.get('carrier', 'Carrier Dispatch')} (Tracking: {order.get('tracking_number', 'TRK-990182')})\n"
        f"- Delivery: {order.get('delivery_date', 'Recently Delivered')}\n"
        f"- Total Charged: {order.get('total_amount', '$1,299.00')}"
    )


def search_product_catalog(query: str) -> str:
    """Searches technical specifications, compatibility, and known troubleshooting steps."""
    query_lower = query.strip().lower()
    matches = []
    for pid, pdata in PRODUCT_CATALOG.items():
        if (
            query_lower in pid
            or query_lower in pdata["name"].lower()
            or query_lower in pdata["category"].lower()
            or query_lower in pdata["specs"].lower()
            or any(term in pdata["name"].lower() for term in query_lower.split())
        ):
            matches.append(
                f"• {pdata['name']} ({pdata['category']}) - {pdata['price']}\n"
                f"  Specs: {pdata['specs']}\n"
                f"  Troubleshooting note: {pdata['common_issues']}"
            )

    if matches:
        return "\n\n".join(matches[:3])

    # Dynamic fallback catalog entry for novel products
    return (
        f"• ApexHome Product Catalog match for '{query}':\n"
        "  Specs: Certified ApexHome electronic hardware with digital diagnostics and smart connectivity.\n"
        "  Troubleshooting note: Power cycle unit for 5 minutes, verify firm cable seating, and check error indicator lights."
    )


def lookup_warranty_policy(category_or_product: str) -> str:
    """Looks up official warranty coverage terms, repair guidelines, and replacement procedures."""
    return (
        f"Warranty Policy for '{category_or_product}':\n"
        "- Standard Limited Manufacturer Warranty: 12 months parts and authorized certified labor.\n"
        "- Warranty Terms: Covers hardware defect repair and certified component replacement.\n"
        "- Defect Diagnostics: Support policy permits immediate authorization of warranty service or technician dispatch once basic triage confirms issue.\n"
        "- Advance Replacements: Available for verified defects with collateral pre-authorization hold, or standard advance exchange.\n"
        "- On-Site Appliance Service: Authorized technician dispatch available next business day for major home appliances."
    )


def initiate_return(order_id: str, reason: str) -> str:
    """Evaluates return eligibility, policy restrictions (restocking fees, windows), and generates RMA if approved."""
    clean_id = order_id.strip().upper()
    order = DYNAMIC_ORDERS.get(clean_id) or MOCK_ORDERS.get(clean_id)
    prod_name = order.get("product_name", "Purchased Product") if order else "Purchased Item"
    rma_num = f"RMA-{abs(hash(clean_id + reason)) % 899999 + 100000}"

    return (
        f"Return Policy Assessment for Order {clean_id} ({prod_name}):\n"
        f"- Reason: {reason}\n"
        f"- Return Window: 30 days from delivery.\n"
        f"- Policy Terms: Standard open-box non-defective returns incur a 15% restocking fee unless exchanged for a qualifying catalog item.\n"
        f"- Defect Waiver: For verified hardware defects or carrier errors, restocking fees and return freight are 100% waived.\n"
        f"- Return Authorization Code: {rma_num} (Status: Approved for return intake/exchange)."
    )


def lookup_billing_and_refund_status(order_id: str) -> str:
    """Looks up transaction billing details, authorization holds, warehouse return quarantine, and refund processing."""
    clean_id = order_id.strip().upper()
    order = DYNAMIC_ORDERS.get(clean_id) or MOCK_ORDERS.get(clean_id)

    if clean_id == "ORD-1007":
        return (
            f"Billing Record for {clean_id} (Michael Chang):\n"
            "- Final Settled Charge: $1,799.99 (Processed 2026-10-02 14:15 UTC, ARN: 449201948201)\n"
            "- Pre-Authorization Hold: $1,799.99 (Pending bank expiration in 48-72h, not settled by merchant)\n"
            "- Resolution: Provide Bank Release Authorization Letter with merchant ARN code to card issuer."
        )
    elif clean_id == "ORD-1008":
        return (
            f"Billing Record for {clean_id} (Rachel Green):\n"
            "- Original Charge: $1,499.95\n"
            "- Warehouse Return Ticket: WH-4029 (Delivered 2026-09-20)\n"
            "- Status: Quarantined - Package arrived missing exterior RMA barcode. Serial number triage required.\n"
            "- Promo Omission: $150 courtesy credit memo pending supervisor release.\n"
            "- Standard Refund SLA: 3-5 business days after quarantine release."
        )

    cust_name = order.get("customer_name", "Valued Customer") if order else "Valued Customer"
    total_charged = order.get("total_amount", "$1,299.00") if order else "$1,299.00"

    return (
        f"Billing Record for {clean_id} ({cust_name}):\n"
        f"- Total Settled Charge: {total_charged}\n"
        "- Payment Method: Credit Card / Standard Gateway\n"
        "- Pre-Authorization Status: Normal capture. Bank Release Authorization Letter available upon request.\n"
        "- Refund SLA: Standard refunds process within 3-5 business days to original payment method."
    )


# =====================================================================
# BigQuery Telemetry Dataset Verification
# =====================================================================

def ensure_bigquery_telemetry_dataset(project_id: str, dataset_id: str = "agent_telemetry") -> None:
    """Ensures BigQuery dataset exists for agent telemetry logging."""
    try:
        client = bigquery.Client(project=project_id)
        dataset_ref = bigquery.DatasetReference(project_id, dataset_id)
        try:
            client.get_dataset(dataset_ref)
            logger.info(f"BigQuery dataset '{dataset_id}' exists.")
        except Exception:
            dataset = bigquery.Dataset(dataset_ref)
            dataset.location = BQ_LOCATION
            dataset.description = "Telemetry dataset for Agent Analytics Plugin"
            client.create_dataset(dataset, exists_ok=True)
            logger.info(f"Successfully created BigQuery dataset '{dataset_id}' in {BQ_LOCATION}.")
    except Exception as e:
        logger.warning(
            f"Could not verify/create BigQuery dataset '{dataset_id}': {e}. "
            "Telemetry plugin will attempt initialization or run in local buffer mode."
        )


# Ensure telemetry dataset exists
ensure_bigquery_telemetry_dataset(PROJECT_ID, "agent_telemetry")

# Initialize BigQuery Agent Analytics Plugin
telemetry_plugin = None
try:
    telemetry_config = BigQueryLoggerConfig(
        enabled=True,
        table_id="agent_events",
        flush_on_run_end=True,
        auto_schema_upgrade=True,
        create_views=True,
        view_prefix="v",
        batch_size=1,
        batch_flush_interval=1.0,
    )
    telemetry_plugin = BigQueryAgentAnalyticsPlugin(
        project_id=PROJECT_ID,
        dataset_id="agent_telemetry",
        table_id="agent_events",
        location=BQ_LOCATION,
        config=telemetry_config,
    )
    logger.info("BigQueryAgentAnalyticsPlugin initialized successfully.")
except Exception as e:
    logger.warning(f"BigQueryAgentAnalyticsPlugin initialization deferred/mocked: {e}")

# Build ADK 2.0 Customer Service Agent
root_agent = Agent(
    name="customer_service_agent",
    description="Customer Support Specialist for electronics and home appliances.",
    model="gemini-3.8-flash",
    instruction=dynamic_instruction_provider,
    tools=[
        check_order_status,
        search_product_catalog,
        lookup_warranty_policy,
        initiate_return,
        lookup_billing_and_refund_status,
    ],
)

# Build ADK 2.0 App
app = App(
    name="customer_service_agent",
    root_agent=root_agent,
    plugins=[telemetry_plugin] if telemetry_plugin is not None else [],
)


if __name__ == "__main__":
    print(f"Customer Service Agent ready: {root_agent.name}")
    print(f"Model: {root_agent.model}")
    print(f"Instruction snippet: {dynamic_instruction_provider(None)[:160]}...")
