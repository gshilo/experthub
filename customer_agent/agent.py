"""Customer Simulator Agent for electronics and home appliances support.

Built with Google Agent Development Kit (ADK 2.0), powered by Gemini 3.8 Flash (gemini-3.8-flash).
Generates live, highly varied customer personas, issues, and multi-turn human dialogues
on every conversation trigger, with realistic human pacing and automated post-conversation
feedback persistence to AlloyDB (cluster 'apex', database 'postgres', table 'customer_ratings').
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import random
import re
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import google.auth
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.models import Gemini
from google.cloud.alloydb.connector import Connector, IPTypes
from google import genai
from google.genai import types

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("customer_agent")


def _resolve_project_id() -> str:
    env_proj = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
    if env_proj and env_proj.strip():
        return env_proj.strip()
    try:
        _, default_proj = google.auth.default()
        if default_proj:
            return default_proj.strip()
    except Exception:
        pass
    return "experthub-510907"


PROJECT_ID = _resolve_project_id()
VERTEX_LOCATION = os.environ.get("VERTEX_AI_LOCATION", "global")
ALLOYDB_REGION = os.environ.get("ALLOYDB_REGION") or os.environ.get("GCP_REGION") or "us-central1"
ALLOYDB_CLUSTER = os.environ.get("ALLOYDB_CLUSTER", "apex")
ALLOYDB_INSTANCE = os.environ.get("ALLOYDB_INSTANCE", "apex")
ALLOYDB_DATABASE = os.environ.get("ALLOYDB_DATABASE", "postgres")
ALLOYDB_USER = os.environ.get("ALLOYDB_USER", "postgres")
ALLOYDB_PASSWORD = os.environ.get("ALLOYDB_PASSWORD", "apex1234")
TABLE_ID = "customer_ratings"
MODEL_NAME = "gemini-3.8-flash"

_GENAI_CLIENT: Optional[genai.Client] = None
_ALLOYDB_IAM_CONNECTOR: Optional[Connector] = None
_ALLOYDB_PWD_CONNECTOR: Optional[Connector] = None
_ALLOYDB_IAM_AUTH_FAILED: bool = False
_ALLOYDB_TABLE_VERIFIED: bool = False


def configure_vertex_ai_adc(project_id: str = PROJECT_ID, location: str = VERTEX_LOCATION) -> None:
    """Configures environment for Google GenAI SDK and ADK to use Vertex AI with ADC without API keys."""
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
    os.environ["GOOGLE_CLOUD_LOCATION"] = location
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("GOOGLE_API_KEY", None)


def _get_genai_client() -> genai.Client:
    """Returns a cached google.genai.Client instance configured for Vertex AI via ADC."""
    global _GENAI_CLIENT
    configure_vertex_ai_adc(PROJECT_ID, VERTEX_LOCATION)
    if _GENAI_CLIENT is None:
        _GENAI_CLIENT = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location=VERTEX_LOCATION,
        )
    return _GENAI_CLIENT


# Ensure Vertex AI ADC is configured before agent execution
configure_vertex_ai_adc(PROJECT_ID, VERTEX_LOCATION)


def _get_alloydb_connector(enable_iam_auth: bool = True) -> Connector:
    """Returns a cached AlloyDB Python Connector instance for IAM or password auth."""
    global _ALLOYDB_IAM_CONNECTOR, _ALLOYDB_PWD_CONNECTOR
    if enable_iam_auth:
        if _ALLOYDB_IAM_CONNECTOR is None:
            _ALLOYDB_IAM_CONNECTOR = Connector(refresh_strategy="lazy", enable_iam_auth=True)
        return _ALLOYDB_IAM_CONNECTOR
    if _ALLOYDB_PWD_CONNECTOR is None:
        _ALLOYDB_PWD_CONNECTOR = Connector(refresh_strategy="lazy", enable_iam_auth=False)
    return _ALLOYDB_PWD_CONNECTOR


def _get_alloydb_iam_user() -> str:
    """Resolves the AlloyDB IAM database username from the active service account."""
    explicit_user = os.environ.get("ALLOYDB_IAM_USER")
    if explicit_user and explicit_user.strip():
        user_val = explicit_user.strip()
        if user_val.endswith(".gserviceaccount.com"):
            return user_val[: -len(".gserviceaccount.com")]
        return user_val

    email = ""
    try:
        credentials, _ = google.auth.default()
        email = getattr(credentials, "service_account_email", "") or ""
    except Exception:
        pass

    if not email or email == "default":
        try:
            req = urllib.request.Request(
                "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email",
                headers={"Metadata-Flavor": "Google"},
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                email = resp.read().decode("utf-8").strip()
        except Exception:
            pass

    if email and email.endswith(".gserviceaccount.com"):
        return email[: -len(".gserviceaccount.com")]
    if email and "@" in email:
        return email
    return ""


def _connect_alloydb(
    db_name: str = ALLOYDB_DATABASE,
    project_id: str = PROJECT_ID,
):
    """Creates a pg8000 DB-API connection to AlloyDB via Public IP (mTLS) with IAM + built-in user fallback."""
    resolved_project = project_id or _resolve_project_id()
    instance_uri = (
        f"projects/{resolved_project}/locations/{ALLOYDB_REGION}/"
        f"clusters/{ALLOYDB_CLUSTER}/instances/{ALLOYDB_INSTANCE}"
    )
    # PUBLIC works from Cloud Run and Vertex AI Agent Engine without VPC egress or PSC DNS,
    # while the AlloyDB Connector still enforces mTLS and roles/alloydb.client IAM checks.
    ip_type_str = os.environ.get("ALLOYDB_IP_TYPE", "PUBLIC").upper()
    ip_type = getattr(IPTypes, ip_type_str, IPTypes.PUBLIC)
    auth_mode = os.environ.get("ALLOYDB_AUTH_MODE", "AUTO").strip().upper()

    global _ALLOYDB_IAM_AUTH_FAILED
    iam_user = _get_alloydb_iam_user()
    if auth_mode == "IAM" or (auth_mode == "AUTO" and iam_user and not _ALLOYDB_IAM_AUTH_FAILED):
        try:
            connector = _get_alloydb_connector(enable_iam_auth=True)
            return connector.connect(
                instance_uri,
                "pg8000",
                user=iam_user,
                db=db_name,
                enable_iam_auth=True,
                ip_type=ip_type,
            )
        except Exception as iam_err:
            if auth_mode == "IAM":
                raise
            _ALLOYDB_IAM_AUTH_FAILED = True
            logger.info(
                f"AlloyDB IAM auth as '{iam_user}' did not succeed ({iam_err}); "
                f"falling back to built-in AlloyDB user '{ALLOYDB_USER}'."
            )

    connector = _get_alloydb_connector(enable_iam_auth=False)
    return connector.connect(
        instance_uri,
        "pg8000",
        user=ALLOYDB_USER,
        password=ALLOYDB_PASSWORD,
        db=db_name,
        enable_iam_auth=False,
        ip_type=ip_type,
    )


def ensure_alloydb_ratings_table(project_id: str = PROJECT_ID) -> None:
    """Verifies or creates AlloyDB database and table 'customer_ratings' with expected schema."""
    global _ALLOYDB_TABLE_VERIFIED
    try:
        try:
            conn = _connect_alloydb(db_name=ALLOYDB_DATABASE, project_id=project_id)
        except Exception as db_err:
            err_str = str(db_err)
            if "3D000" in err_str or f'database "{ALLOYDB_DATABASE}" does not exist' in err_str.lower():
                logger.info(f"AlloyDB database '{ALLOYDB_DATABASE}' does not exist yet; creating it via 'postgres'...")
                admin_conn = _connect_alloydb(db_name="postgres", project_id=project_id)
                try:
                    admin_conn.autocommit = True
                    cur = admin_conn.cursor()
                    cur.execute(f'CREATE DATABASE "{ALLOYDB_DATABASE}"')
                    cur.close()
                    logger.info(f"Created AlloyDB database '{ALLOYDB_DATABASE}' in cluster '{ALLOYDB_CLUSTER}'.")
                finally:
                    admin_conn.close()
                conn = _connect_alloydb(db_name=ALLOYDB_DATABASE, project_id=project_id)
            else:
                raise

        try:
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE_ID} (
                    customer_id BIGINT NOT NULL,
                    customer_name TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    timestamp TIMESTAMPTZ
                )
                """
            )
            try:
                cur.execute("GRANT ALL PRIVILEGES ON SCHEMA public TO PUBLIC")
                cur.execute(f"GRANT ALL PRIVILEGES ON TABLE {TABLE_ID} TO PUBLIC")
            except Exception as grant_err:
                logger.info(f"Skipped GRANT on '{TABLE_ID}' (caller is not table owner): {grant_err}")
            cur.execute("SELECT has_table_privilege(current_user, %s, 'INSERT')", (TABLE_ID,))
            can_insert = bool(cur.fetchone()[0])
            cur.close()
            if not can_insert:
                raise PermissionError(
                    f"Connected AlloyDB user lacks INSERT privilege on '{TABLE_ID}' in database '{ALLOYDB_DATABASE}'."
                )
            _ALLOYDB_TABLE_VERIFIED = True
            logger.info(
                f"AlloyDB table '{ALLOYDB_CLUSTER}/{ALLOYDB_DATABASE}.{TABLE_ID}' verified."
            )
        finally:
            conn.close()
    except Exception as e:
        logger.error(
            f"Could not verify/create AlloyDB table '{ALLOYDB_CLUSTER}/{ALLOYDB_DATABASE}.{TABLE_ID}': {e}. "
            "Will retry on rating write."
        )


# Backward-compatible alias
ensure_bigquery_ratings_table = ensure_alloydb_ratings_table


def write_customer_rating_to_alloydb(
    customer_id: int,
    customer_name: str,
    rating: int,
    description: str,
    timestamp: Optional[str] = None,
    project_id: str = PROJECT_ID,
) -> bool:
    """Inserts a customer evaluation row with timestamp into AlloyDB table customer_ratings."""
    global _ALLOYDB_TABLE_VERIFIED
    safe_rating = max(1, min(5, int(rating)))
    if timestamp:
        try:
            now_dt = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except Exception:
            now_dt = datetime.datetime.now(datetime.timezone.utc)
    else:
        now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_ts = now_dt.isoformat()

    row = {
        "customer_id": int(customer_id),
        "customer_name": str(customer_name),
        "rating": safe_rating,
        "description": str(description),
        "timestamp": now_ts,
    }

    try:
        if not _ALLOYDB_TABLE_VERIFIED:
            ensure_alloydb_ratings_table(project_id)

        conn = _connect_alloydb(db_name=ALLOYDB_DATABASE, project_id=project_id)
        try:
            cur = conn.cursor()
            cur.execute(
                f"""
                INSERT INTO {TABLE_ID} (customer_id, customer_name, rating, description, timestamp)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    int(customer_id),
                    str(customer_name),
                    safe_rating,
                    str(description),
                    now_dt,
                ),
            )
            conn.commit()
            cur.close()
            logger.info(
                f"Persisted rating ({safe_rating}/5) for {customer_name} at {now_ts} "
                f"to AlloyDB {ALLOYDB_CLUSTER}/{ALLOYDB_DATABASE}.{TABLE_ID}."
            )
            return True
        finally:
            conn.close()
    except Exception as e:
        logger.exception(
            f"Could not write rating to AlloyDB '{ALLOYDB_CLUSTER}/{ALLOYDB_DATABASE}.{TABLE_ID}': {e}. "
            f"Data: {row}"
        )
        return False


# Backward-compatible alias for legacy callers
write_customer_rating_to_bigquery = write_customer_rating_to_alloydb


# =====================================================================
# Seed Dimensions & Diversification Controls for Live Generation
# =====================================================================

CATEGORY_SEEDS = [
    "Hardware Malfunction & Diagnostics",
    "Delivery Delay, Carrier Trace & False Delivery Scan",
    "Payment, Duplicate Pre-Auth Hold & Ledger Dispute",
    "Return Policy & Restocking Fee Dispute",
    "Technical Setup, Handshake & Compatibility",
    "Warranty Service SLA & Repair Center Turnaround",
    "Damaged Freight, Crushed Carton & Exterior Dents",
    "Missing Critical Cables & Subassembly Parts",
    "Smart Connectivity, Wi-Fi 7 & Matter/Thread Pairing",
    "Installation Failure & Contractor Workmanship",
    "Noise, Acoustic Whine & Motor Vibration",
    "Overheating, Thermal Throttling & Fan Sensor Trip",
    "Power Delivery, Solar Input & Battery Management",
    "Water Leakage, Drain Pump Blockage & Seal Breakdown",
    "Price Protection Guarantee & Promotional Code Omission",
    "Display Artifacts, VRR Frame Sync & Dead Pixels",
    "Open-Box Unit With Previous Owner Account Locked",
    "Gift Recipient Warranty Transfer & Receipt Lookup",
    "App Sensor Calibration & False Environmental Alarms",
    "Firmware Brick & Bootloop After Automatic OTA Update",
]

PRODUCT_DOMAIN_SEEDS = [
    "Smart French Door Refrigerator with dual auto icemaker and Family Hub touchscreen",
    "Flagship 65-inch / 77-inch 4K OLED / QD-OLED TV with 144Hz VRR and eARC",
    "Smart Front-Load Direct Drive Inverter Washer & Heat Pump Dryer stack",
    "Bean-to-Cup Touchscreen Espresso & Cappuccino Machine with dual thermocoils",
    "High-Performance 16-inch Laptop Workstation with Thunderbolt 4 dock",
    "Robotic Vacuum & Mop with LiDAR room mapping and auto-emptying base station",
    "Dolby Atmos 9.1.4 Soundbar System with wireless subwoofer and rear satellite speakers",
    "Smart Induction Cooktop with flex zones and precision wireless temperature probe",
    "Multi-Camera 4K Wireless Home Security Hub with solar panels and local NVR",
    "Smart Multi-Zone Thermostat with remote room sensors and heat pump staging",
    "Cordless Wet-Dry Vacuum Floor Scrubber with dual-tank water extraction",
    "Portable 2400W Pure Sine Wave Power Station with MPPT solar input",
    "Built-in Smart Convection Microwave & Speed Oven combo",
    "Ultra-Quiet 39dBA Smart Dishwasher with auto-release door and leak sensor",
    "Under-Counter Dual-Zone Wine Refrigerator with vibration dampening",
    "Tri-Band Wi-Fi 7 Mesh System with 10Gbps WAN and Matter/Thread border router",
    "34-inch Curved QD-OLED Ultrawide Gaming Monitor with 175Hz and G-Sync Ultimate",
    "Smart Dual-Filter HEPA-13 Air Purifier with laser particle sensor",
    "Smart Biometric Deadbolt with Matter integration and auto-lock sensor",
    "Smart Electric Pressure Cooker & Multi-Cooker with automated steam release valve",
    "Active Noise-Canceling Wireless Studio Headphones with lossless spatial audio",
    "High-End Direct-Drive Turntable with carbon-fiber tonearm and USB-C output",
]

PERSONALITY_SEEDS = [
    "hurried corporate professional on a tight schedule with zero tolerance for generic scripted pleasantries",
    "anxious new homeowner dealing with active water pooling or spoiling refrigerated groceries",
    "detail-oriented software/electronics engineer who has already probed connections, voltages, and analyzed logs",
    "elderly polite customer who gets anxious and confused by modern mobile app companion setups and Bluetooth permissions",
    "frugal bargain hunter outraged by surprise 15% restocking fees or return shipping deductions",
    "skeptical consumer who caught a false carrier delivery scan on their doorbell camera with video proof",
    "analytical audiophile or competitive gamer frustrated by HDMI 2.1 eARC audio drops or VRR frame tearing",
    "blunt and assertive customer who gives short replies and demands direct replacements or supervisor escalations",
    "courteous and patient customer seeking thorough explanation and mutual accommodation",
    "stressed home chef hosting a major family holiday dinner tonight with a malfunctioning kitchen range",
    "remote worker whose workstation dock is offline during high-stakes client meetings",
    "customer who received this high-end appliance as a wedding gift and lacks the original purchaser invoice",
    "exhausted customer who already waited two weeks for a subcontractor technician who never showed up",
    "witty and sarcastic customer making dry remarks about appliances being overly complicated",
    "budget-conscious buyer who saved up for 6 months to buy this flagship item and is devastated by a defect",
]

PATIENCE_SEEDS = ["Low", "Moderate", "High"]
TECH_LITERACY_SEEDS = ["Non-technical", "Average", "Tech-savvy"]

FALLBACK_NAMES = [
    "Aria Montgomery", "Devon Vance", "Camila Rodriguez", "Julian Sterling",
    "Fatima Al-Mansoor", "Tariq Washington", "Siddharth Rao", "Chloe Dupont",
    "Keiko Tanaka", "Henrik Lindqvist", "Mei-Ling Zhou", "Nia Campbell",
    "Dominic Morales", "Svetlana Voronova", "Kofi Mensah", "Ananya Sharma",
    "Mateo Silva", "Ingrid Bergman", "Kenji Sato", "Amara Okafor",
    "Elias Lindstrom", "Zara Haddad", "Lucas Beaumont", "Priya Nair",
]

FALLBACK_PRODUCTS = [
    "ApexCool PureFlow 4-Door Smart Refrigerator",
    "LuminaView 65-inch Quantum OLED 4K Display",
    "HydroClean Pro Inverter Front Load Washer",
    "BaristaCraft Touch Impress Espresso Station",
    "TitanBook Ultra 16 Workstation Laptop",
    "RoboGlide X9 LiDAR Robot Vacuum & Mop",
    "AeroBreeze Smart Dual-Zone Air Purifier",
    "SonicSurround 9.1.4 Dolby Atmos Soundbar System",
    "ApexPower 2400W Pure Sine Power Station",
    "VestaSmart Induction Cooktop with Precision Probe",
    "NetSphere Tri-Band Wi-Fi 7 Mesh Router",
    "ThermoSense Multi-Zone Smart Thermostat",
]


def _procedural_fallback_persona(category_hint: str = "") -> Dict[str, Any]:
    """Generates a randomized fallback persona across a diverse combinatoric pool."""
    name = random.choice(FALLBACK_NAMES)
    product = random.choice(FALLBACK_PRODUCTS)
    category = category_hint or random.choice(CATEGORY_SEEDS)
    patience = random.choice(PATIENCE_SEEDS)
    tech = random.choice(TECH_LITERACY_SEEDS)
    order_num = f"ORD-{random.randint(1011, 9999)}"
    customer_id = random.randint(100000, 999999)

    complaints_pool = [
        (
            f"The touch display on my {product} stopped responding and is flashing error code E-41 after a software update.",
            f"Hi, my {product} froze up completely and displays error code E-41. It won't reset. Can you help me fix this or send a technician?",
            "Hardware Malfunction",
            3,
            "Agent helped reboot the unit, but having a brand new appliance fault out within two weeks was frustrating.",
        ),
        (
            f"Carrier tracking for my {product} says delivered to porch yesterday under {order_num}, but my building security confirmed no delivery truck arrived.",
            f"Carrier tracking says my {product} was delivered yesterday under {order_num}, but nothing was received and security footage is empty. Where is my shipment?",
            "Delivery & Logistics",
            2,
            "Terrible shipping carrier handoff. Support finally opened a trace investigation, but communication was slow.",
        ),
        (
            f"I returned my {product} in pristine condition and was charged an unexpected $180 open-box restocking fee deduction on my refund for {order_num}.",
            f"I received my refund for {order_num} and you deducted a $180 restocking fee! The item was only unboxed for 20 minutes. I expect a 100% full refund.",
            "Return & Refund Dispute",
            3,
            "Agent waived the fee after substantial pushback, but company return terms are needlessly punishing.",
        ),
        (
            f"My credit card shows two duplicate charges of $1,699.00 for order {order_num}. It is tying up my credit line.",
            f"I have two identical charges for order {order_num} on my banking app! Reverse the duplicate authorization immediately.",
            "Payment & Billing",
            2,
            "Double hold tied up my credit card limit. Support explained it was a pre-auth hold, but couldn't expedite the bank release.",
        ),
        (
            f"My {product} disconnects from Wi-Fi whenever the 5GHz band switches channels, causing remote monitoring to drop completely.",
            f"Hello, my {product} keeps dropping its network connection every few hours under order {order_num}. Is this a known firmware defect?",
            "Smart Connectivity",
            4,
            "Specialist gave me specific DHCP IP reservation instructions that stabilized the connection.",
        ),
        (
            f"The freight crew dropped the shipping crate for my {product} onto my porch, leaving a deep crease across the brushed metal casing.",
            f"Order {order_num} arrived today with heavy carton damage and a deep dent right on the front casing of my {product}. I need a replacement panel.",
            "Damaged Freight",
            3,
            "Replaced the dented exterior panel under warranty, though freight delivery handling was reckless.",
        ),
        (
            f"My {product} is emitting an unbearable high-pitched coil whine whenever it draws more than 50% power load.",
            f"Hi, I recently received my {product} under {order_num} and it emits an intolerable electronic screech during operation. I need an exchange.",
            "Hardware Malfunction",
            3,
            "Advance hardware replacement was processed after diagnostic audio verification.",
        ),
        (
            f"The delivery for order {order_num} arrived without the essential proprietary power supply brick and mounting hardware.",
            f"I unpacked order {order_num} for my {product} and the proprietary power adapter was missing from the sealed box! How can I use it?",
            "Missing Subassembly",
            4,
            "Customer service overnighted the missing accessories free of charge.",
        ),
        (
            f"The {product} dropped in price by $220 on your website just 4 days after my purchase under {order_num}. I am requesting a price match credit.",
            f"I purchased my {product} under order {order_num} last week and it is currently discounted by $220. Can you please process a price adjustment refund?",
            "Price Protection",
            5,
            "Representative promptly credited the price difference back to my original payment card.",
        ),
        (
            f"My {product} tripped my kitchen 20A circuit breaker twice this morning and now refuses to turn on at all.",
            f"Emergency help needed: my {product} under order {order_num} tripped the house breaker and now has a blank display with a faint electrical smell.",
            "Hardware Malfunction",
            2,
            "Safety triage was thorough and certified technician dispatch was arranged, but an electrical trip is alarming.",
        ),
    ]

    issue_text, opening_text, cat, exp_rating, rating_fb = random.choice(complaints_pool)

    return {
        "customer_id": customer_id,
        "customer_name": name,
        "category": cat,
        "scenario_key": f"dyn_{int(time.time())}_{random.randint(100, 999)}",
        "patience": patience,
        "personality": random.choice(PERSONALITY_SEEDS),
        "tech_literacy": tech,
        "product": product,
        "issue": issue_text,
        "order_id": order_num,
        "opening": opening_text,
        "expected_rating": exp_rating,
        "rating_feedback": rating_fb,
        "created_at": time.time(),
        "turns_count": 0,
    }


def generate_customer_persona(
    category_hint: str = "",
    model_name: str = MODEL_NAME,
) -> Dict[str, Any]:
    """Generates a novel, highly varied customer persona live using Gemini 3.8 Flash.

    Generates distinct mixtures of issue type, product type, customer personality,
    patience, and technical literacy on every conversation trigger, avoiding rigid repetition.
    """
    configure_vertex_ai_adc(PROJECT_ID, VERTEX_LOCATION)

    cat_seed = category_hint or random.choice(CATEGORY_SEEDS)
    prod_seed = random.choice(PRODUCT_DOMAIN_SEEDS)
    pers_seed = random.choice(PERSONALITY_SEEDS)
    patience_seed = random.choice(PATIENCE_SEEDS)
    tech_seed = random.choice(TECH_LITERACY_SEEDS)
    customer_id = random.randint(100000, 999999)
    order_num = f"ORD-{random.randint(1020, 9990)}"

    prompt = f"""You are generating an authentic, highly unique simulated customer persona for an e-commerce support session at ApexHome & Electro (consumer electronics and smart home appliances).
Create a novel customer persona with a distinct mixture of problem type, product, personality, and patience level.
Make this customer feel like an authentic human with genuine circumstances, conversational voice, and emotions.

Design seeds for this session:
- Focus Category: {cat_seed}
- Product Category Seed: {prod_seed}
- Customer Personality Seed: {pers_seed}
- Target Patience Level: {patience_seed}
- Technical Background: {tech_seed}
- Assigned Order ID: {order_num}

Instructions:
- Be highly creative, specific, and realistic. Invent concrete real-world details (e.g. realistic symptoms, error messages, environmental setups, real-life consequences like spoiled groceries, lost productivity, or an upcoming event).
- Give the customer an authentic, distinct human voice in their opening message (not generic or robotic).
- AVOID reusing common stock situations; explore fresh angles and unexpected real-world dilemmas.

Return a valid JSON object with EXACTLY the following keys:
- "customer_name": Realistic human full name (diverse cultures and backgrounds)
- "category": Problem category (e.g. Hardware Malfunction, Delivery & Logistics, Payment & Billing, Return & Refund Dispute, Technical Setup & Compatibility, Warranty Service, Damaged Freight, Smart Connectivity)
- "scenario_key": Short descriptive slug in snake_case (e.g. "induction_coil_buzz", "solar_station_mppt_trip", "mesh_node_channel_drop")
- "patience": One of ["Low", "Moderate", "High"]
- "personality": Vivid 1-2 sentence description of communication style, attitude, and personal situation
- "tech_literacy": One of ["Non-technical", "Average", "Tech-savvy"]
- "product": Specific brand and model name of the electronic item or appliance
- "issue": Detailed 1-2 sentence description of the specific problem or dispute
- "order_id": The order ID "{order_num}"
- "opening": Authentic first chat message sent by customer to initiate support
- "expected_rating": Integer between 1 and 5 (realistic satisfaction score reflecting their friction, patience, and issue)
- "rating_feedback": 1-2 sentence realistic post-resolution customer review explaining why they gave that score
"""

    try:
        client = _get_genai_client()
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=1.05,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )

        raw_text = response.text.strip()
        data = json.loads(raw_text)

        # Sanitize and complement keys
        persona = {
            "customer_id": customer_id,
            "customer_name": str(data.get("customer_name") or random.choice(FALLBACK_NAMES)),
            "category": str(data.get("category") or cat_seed),
            "scenario_key": str(data.get("scenario_key") or f"dyn_{int(time.time())}"),
            "patience": str(data.get("patience") or patience_seed),
            "personality": str(data.get("personality") or pers_seed),
            "tech_literacy": str(data.get("tech_literacy") or tech_seed),
            "product": str(data.get("product") or random.choice(FALLBACK_PRODUCTS)),
            "issue": str(data.get("issue") or "Device is failing under regular use."),
            "order_id": str(data.get("order_id") or order_num),
            "opening": str(data.get("opening") or "Hello, I am contacting support regarding an issue with my recent purchase."),
            "expected_rating": max(1, min(5, int(data.get("expected_rating", 3)))),
            "rating_feedback": str(data.get("rating_feedback") or "Support resolved the inquiry."),
            "created_at": time.time(),
            "turns_count": 0,
        }
        logger.info(
            f"Generated live customer persona: {persona['customer_name']} "
            f"({persona['category']} | {persona['product']} | Patience: {persona['patience']})"
        )
        return persona

    except Exception as e:
        logger.warning(f"Live persona generation fallback to procedural generator: {e}")
        return _procedural_fallback_persona(cat_seed)


def generate_customer_turn(
    history: List[Dict[str, str]],
    persona: Dict[str, Any],
    last_service_message: str,
    model_name: str = MODEL_NAME,
) -> str:
    """Generates the next simulated customer dialogue turn live using Gemini 3.8 Flash.

    Reflects the persona's authentic voice, emotional arc, patience, pushback, and circumstances.
    """
    configure_vertex_ai_adc(PROJECT_ID, VERTEX_LOCATION)

    cust_name = persona.get("customer_name", "Customer")
    product = persona.get("product", "purchased product")
    issue = persona.get("issue", "product malfunction")
    patience = persona.get("patience", "Moderate")
    tech_literacy = persona.get("tech_literacy", "Average")
    personality = persona.get("personality", "authentic customer")

    # Format transcript history
    formatted_history = []
    for turn in history[-8:]:  # Keep recent context
        role = "Customer" if turn.get("role") == "customer" else "Apex Support"
        formatted_history.append(f"{role}: {turn.get('content', '')}")
    history_block = "\n".join(formatted_history)

    prompt = f"""You are simulating the customer in an ongoing customer service chat with ApexHome & Electro.
Stay entirely in character as {cust_name}.
Never break character or say you are an AI, language model, or simulator.

Customer Profile:
- Name: {cust_name}
- Product: {product}
- Core Issue / Complaint: {issue}
- Personality & Attitude: {personality}
- Patience Level: {patience}
- Technical Background: {tech_literacy}

Behavioral Guidelines:
- Directly respond to what Apex Support just said:
  * If they asked a question (e.g. asking for serial number, order details, error lights, or what was tried), provide a realistic, authentic answer in character.
  * If they suggested troubleshooting (e.g. power-cycle, check cables, update firmware, toggle settings), react realistically (e.g. test it and report what happened, or challenge it if you have Low patience and lack time).
  * If they offer a concrete resolution (e.g. scheduling a technician, dispatching a replacement, waiving a fee, issuing an RMA, or processing a refund), evaluate it against your needs. If it resolves your issue, acknowledge it and express relief or satisfaction.
- Personality Dynamics:
  * If patience is "Low": Express clear urgency, pushback against delays or burdensome diagnostic steps. Do not surrender easily.
  * If patience is "Moderate": Be reasonable but firm. Push back against unfair fees or long wait times, but cooperate with practical steps.
  * If patience is "High": Polite, analytical, and cooperative, but expect high competence and clear resolution.
- Keep your reply natural, conversational, and concise (1 to 3 sentences maximum), matching real human customer messaging.

Conversation History:
{history_block}

Customer Service Agent just said:
"{last_service_message}"

Respond naturally as {cust_name}:
"""

    try:
        client = _get_genai_client()
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.9,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        reply = response.text.strip()
        # Clean any accidental quotes or role prefixes
        reply = re.sub(r'^(Customer|Me|\b' + re.escape(cust_name) + r'\b):\s*', '', reply, flags=re.IGNORECASE)
        reply = reply.strip('"').strip()
        return reply
    except Exception as e:
        logger.warning(f"Live customer turn fallback: {e}")
        # Contextual procedural fallback
        if patience == "Low":
            return (
                f"I really don't have time for endless steps while my {product} is unusable. "
                "Can you please arrange an immediate technician, replacement, or supervisor escalation?"
            )
        elif patience == "High":
            return (
                f"Understood. I will follow those steps on the {product}. "
                "What is the official reference number in case this does not resolve it?"
            )
        else:
            return (
                f"I appreciate the guidance regarding the {product}. "
                "Please make sure this is documented under my account so we can resolve this today."
            )


def evaluate_customer_experience(
    persona: Dict[str, Any],
    history: List[Dict[str, str]],
    model_name: str = MODEL_NAME,
) -> Tuple[int, str]:
    """Evaluates customer interaction CSAT rating (1-5) and feedback description reflecting authentic user satisfaction."""
    configure_vertex_ai_adc(PROJECT_ID, VERTEX_LOCATION)

    cust_name = persona.get("customer_name", "Customer")
    product = persona.get("product", "product")
    issue = persona.get("issue", "issue")
    patience = persona.get("patience", "Moderate")

    # Format transcript
    transcript = "\n".join(
        f"{'Customer' if t.get('role') == 'customer' else 'Support'}: {t.get('content', '')}"
        for t in history
    )

    prompt = f"""Evaluate this customer service chat from the subjective perspective of customer {cust_name}.
Product: {product}
Issue: {issue}
Customer Patience: {patience}

Chat Transcript:
\"\"\"
{transcript}
\"\"\"

Rubric:
- 5 (Excellent): Knowledgeable specialist resolved defect/issue smoothly without bureaucratic runaround.
- 4 (Good): Practical resolution reached, but required customer effort or compromise.
- 3 (Average): Resolved eventually, but customer had to fight strict policies, fees, or tedious diagnostic steps.
- 2 (Poor): Rigid policies, long delays, unresolved freight issue, or unhelpful response.
- 1 (Terrible): Completely unhelpful or refusal of warranty/service.

Return JSON:
{{
  "rating": <integer 1 to 5>,
  "description": "<1-2 sentences of authentic customer qualitative review explaining the score>"
}}
"""

    try:
        client = _get_genai_client()
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.7,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        data = json.loads(response.text.strip())
        rating = max(1, min(5, int(data.get("rating", 3))))
        description = str(data.get("description", "Interaction concluded."))
        return rating, description
    except Exception as e:
        logger.warning(f"Live rating evaluation fallback: {e}")
        exp_rating = int(persona.get("expected_rating", 3))
        exp_fb = str(persona.get("rating_feedback", "Completed support interaction."))
        return exp_rating, exp_fb


# Backward compatibility catalog alias for legacy imports
PERSONA_CATALOG = [
    {
        "scenario_key": "refrigerator_defrost_22e",
        "category": "Hardware Malfunction",
        "name": "Marcus Vance",
        "patience": "Low",
        "tech_literacy": "Average",
        "product": "Samsung Family Hub 4-Door Smart Refrigerator",
        "issue": "My refrigerator has error code 22E on the display and the upper fan is making a grinding noise. Groceries are getting warm.",
        "order_id": "ORD-1002",
        "opening": "Hi, my smart refrigerator is flashing error code 22E and making a loud grinding sound! My food is spoiling. Can you help me fix this immediately?",
        "expected_rating": 3,
        "rating_feedback": "Technician booked for tomorrow, but agent made me jump through diagnostic hoops while food spoiled.",
    },
    {
        "scenario_key": "laptop_dock_flicker",
        "category": "Hardware Malfunction",
        "name": "Liam O'Connor",
        "patience": "Moderate",
        "tech_literacy": "Average",
        "product": "ApexBook Pro 16 Laptop",
        "issue": "My laptop external monitor is flickering and blacking out when connected via Thunderbolt dock under load.",
        "order_id": "ORD-1010",
        "opening": "Hello, my ApexBook Pro 16 laptop display keeps flickering and going completely black when plugged into my Thunderbolt dock. Can you process an exchange?",
        "expected_rating": 3,
        "rating_feedback": "Resolved dock flicker after extensive troubleshooting, but advance exchange policy is overly rigid.",
    },
]


# =====================================================================
# ADK 2.0 Customer Simulator Agent Definition
# =====================================================================

root_agent = Agent(
    name="customer_agent",
    description=(
        "Simulated Customer Agent for consumer electronics and home appliances. "
        "Generates novel, live customer personas and issues dynamically on every conversation trigger, "
        "simulates realistic multi-turn human pushback and dialogues, and evaluates experiences "
        "with authentic feedback persisted to AlloyDB (cluster 'apex', database 'postgres', table 'customer_ratings')."
    ),
    model=Gemini(
        model="gemini-3.8-flash",
        client_kwargs={
            "vertexai": True,
            "project": PROJECT_ID,
            "location": VERTEX_LOCATION,
        },
    ),
    generate_content_config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    ),
    instruction=(
        "You are an authentic, realistic customer contacting ApexHome & Electro support. "
        "Speak naturally from your persona's perspective. You possess authentic human emotions: "
        "if customer service offers bureaucratic hurdles, imposes unexpected restocking fees, "
        "delays an investigation, or asks you to perform tedious troubleshooting, express pushback "
        "and frustration according to your patience level. Do not easily surrender or settle on turn 1. "
        "Engage in a realistic multi-turn dialogue. Never say you are an AI or simulator. "
        "You also provide live dynamic persona generation and post-conversation rating evaluations."
    ),
    tools=[
        generate_customer_persona,
        generate_customer_turn,
        evaluate_customer_experience,
        write_customer_rating_to_alloydb,
    ],
)

app = App(
    name="customer_agent",
    root_agent=root_agent,
)


if __name__ == "__main__":
    print(f"Customer Simulator Agent ready: {root_agent.name}")
    print("Testing live persona generation with Gemini 3.8 Flash...")
    p = generate_customer_persona()
    print("Generated Persona:")
    for k, v in p.items():
        print(f"  {k}: {v}")
