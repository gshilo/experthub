"""Customer Simulator Agent for electronics and home appliances support.

Built with Google Agent Development Kit (ADK 2.0), powered by Gemini 3.8 Flash (gemini-3.8-flash).
Generates live, highly varied customer personas, issues, and multi-turn human dialogues
on every conversation trigger, with realistic human pacing and automated post-conversation
feedback persistence to BigQuery.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import google.auth
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.cloud import bigquery
from google.cloud import secretmanager
from google import genai
from google.genai import types

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("customer_agent")

PROJECT_ID = (
    os.environ.get("GOOGLE_CLOUD_PROJECT")
    or os.environ.get("GCP_PROJECT")
    or "experthub-510907"
)
BQ_LOCATION = os.environ.get("BQ_LOCATION", "US")
DATASET_ID = "demo"
TABLE_ID = "customer_ratings"
MODEL_NAME = "gemini-3.8-flash"


_SECRET_CACHE: Dict[str, str] = {}
_GENAI_CLIENT: Optional[genai.Client] = None


def get_secret(secret_id: str, project: str = PROJECT_ID) -> str:
    """Retrieves secret from Google Cloud Secret Manager with in-memory cache and fallback to env var.

    API keys and credentials are never stored in static files.
    """
    cache_key = f"{project}:{secret_id}"
    if cache_key in _SECRET_CACHE:
        return _SECRET_CACHE[cache_key]

    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8").strip()
        if secret_value:
            _SECRET_CACHE[cache_key] = secret_value
        logger.info(f"Retrieved secret '{secret_id}' directly from Secret Manager.")
        return secret_value
    except Exception as e:
        logger.info(f"Could not retrieve secret '{secret_id}' from Secret Manager: {e}.")

    # Fallback to env var if secret manager lookup fails
    if secret_id in ("gemini-api-key", "google-api-key"):
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if env_key:
            val = env_key.strip()
            _SECRET_CACHE[cache_key] = val
            return val
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
    existing_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if existing_key and not is_placeholder_token(existing_key):
        return existing_key

    for secret_name in ("gemini-api-key", "google-api-key"):
        val = get_secret(secret_name, project=project_id)
        if val and not is_placeholder_token(val):
            os.environ["GEMINI_API_KEY"] = val
            os.environ["GOOGLE_API_KEY"] = val
            logger.info(f"Dynamically loaded Gemini API key from Secret Manager secret '{secret_name}' (not static files).")
            return val

    logger.warning("No Gemini API key found in Secret Manager ('gemini-api-key') or environment.")
    return None


def _get_genai_client() -> genai.Client:
    """Returns a cached google.genai.Client instance for low-latency connection reuse."""
    global _GENAI_CLIENT
    ensure_gemini_api_key(PROJECT_ID)
    if _GENAI_CLIENT is None:
        _GENAI_CLIENT = genai.Client()
    return _GENAI_CLIENT


# Ensure Gemini API key is loaded into environment from Secret Manager before agent execution
ensure_gemini_api_key(PROJECT_ID)


def ensure_bigquery_ratings_table(project_id: str = PROJECT_ID) -> None:
    """Verifies or programmatically creates BigQuery dataset 'demo' and table 'customer_ratings'."""
    try:
        client = bigquery.Client(project=project_id)
        dataset_ref = bigquery.DatasetReference(project_id, DATASET_ID)

        # Ensure dataset exists
        try:
            client.get_dataset(dataset_ref)
        except Exception:
            dataset = bigquery.Dataset(dataset_ref)
            dataset.location = BQ_LOCATION
            dataset.description = "Customer ratings and feedback dataset"
            client.create_dataset(dataset, exists_ok=True)
            logger.info(f"Created BigQuery dataset '{DATASET_ID}' in {BQ_LOCATION}.")

        # Ensure table exists
        table_ref = dataset_ref.table(TABLE_ID)
        try:
            table = client.get_table(table_ref)
            field_names = [f.name for f in table.schema]
            if "timestamp" not in field_names:
                new_schema = list(table.schema) + [
                    bigquery.SchemaField("timestamp", "TIMESTAMP", mode="NULLABLE")
                ]
                table.schema = new_schema
                client.update_table(table, ["schema"])
                logger.info(f"Added 'timestamp' column to BigQuery table '{DATASET_ID}.{TABLE_ID}'.")
            else:
                logger.info(f"BigQuery table '{DATASET_ID}.{TABLE_ID}' verified.")
        except Exception:
            schema = [
                bigquery.SchemaField("customer_id", "INTEGER", mode="REQUIRED"),
                bigquery.SchemaField("customer_name", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("rating", "INTEGER", mode="REQUIRED"),
                bigquery.SchemaField("description", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("timestamp", "TIMESTAMP", mode="NULLABLE"),
            ]
            table = bigquery.Table(table_ref, schema=schema)
            client.create_table(table, exists_ok=True)
            logger.info(f"Created BigQuery table '{DATASET_ID}.{TABLE_ID}' with timestamp schema.")
    except Exception as e:
        logger.warning(
            f"Could not verify/create BigQuery table '{DATASET_ID}.{TABLE_ID}': {e}. "
            "Ratings will be recorded in local memory fallback."
        )


# Ensure dataset and table exist on startup
ensure_bigquery_ratings_table(PROJECT_ID)


def write_customer_rating_to_bigquery(
    customer_id: int,
    customer_name: str,
    rating: int,
    description: str,
    timestamp: Optional[str] = None,
    project_id: str = PROJECT_ID,
) -> bool:
    """Inserts a customer evaluation row with timestamp into BigQuery table demo.customer_ratings."""
    safe_rating = max(1, min(5, int(rating)))
    now_ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
    row = {
        "customer_id": int(customer_id),
        "customer_name": str(customer_name),
        "rating": safe_rating,
        "description": str(description),
        "timestamp": now_ts,
    }

    try:
        client = bigquery.Client(project=project_id)
        table_id_full = f"{project_id}.{DATASET_ID}.{TABLE_ID}"
        errors = client.insert_rows_json(table_id_full, [row])
        if not errors:
            logger.info(f"Persisted rating ({safe_rating}/5) for {customer_name} at {now_ts} to {table_id_full}.")
            return True
        else:
            logger.error(f"BigQuery insert error for {table_id_full}: {errors}")
            return False
    except Exception as e:
        logger.warning(
            f"Could not write rating to BigQuery '{DATASET_ID}.{TABLE_ID}': {e}. "
            f"Data: {row}"
        )
        return False


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
    ensure_gemini_api_key(PROJECT_ID)

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
    ensure_gemini_api_key(PROJECT_ID)

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
    ensure_gemini_api_key(PROJECT_ID)

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
        "with authentic feedback persisted to BigQuery."
    ),
    model="gemini-3.8-flash",
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
        write_customer_rating_to_bigquery,
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
