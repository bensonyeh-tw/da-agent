"""NL2SQL Data Agent Tool (cymbal_analytics_tool).

Bound to the published BigQuery Conversational Data Agent in global location:
projects/benson-data-elevate/locations/global/dataAgents/cymbal-retail-analytics-agent
"""

import json
import logging
import os
import time

import google.auth
import requests
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "benson-data-elevate")
LOCATION = os.getenv("DATA_AGENT_LOCATION", "global")
DATA_AGENT_ID = os.getenv("DATA_AGENT_ID", "cymbal-retail-analytics-agent")
DATA_AGENT_RESOURCE = os.getenv(
    "DATA_AGENT_RESOURCE",
    os.getenv(
        "DATA_AGENT_NAME",
        f"projects/{PROJECT_ID}/locations/{LOCATION}/dataAgents/{DATA_AGENT_ID}",
    ),
)


def cymbal_analytics_tool(query: str) -> str:
    """Queries the Cymbal Retail BigQuery Conversational Data Agent for analytical, relational, and cross-cloud questions.

    Use this tool for:
    - Intraday POS sales checkouts and store revenues (pos_transactions_gold).
    - Historical purchases, transaction lookups, and warranty claims (historical_transactional_data).
    - Cashier promo abuse rankings and anomaly alerts (pos_anomaly_alerts).
    - Store inventory positions, stockout risks (<20 hours), and cover hours (gold_inventory_reconciliation_ledger).
    - Manufacturer warranty terms and SLA policies (warranty_generic_sections_extracted).
    - Cross-cloud historical checkout logs in AWS S3 (silver_pos_transactions).

    Args:
        query: Natural language business inquiry passed verbatim to the Data Agent.

    Returns:
        A detailed synthesized answer with analytical findings and SQL execution context.
    """
    logger.info("cymbal_analytics_tool received query: %s", query)

    # Resolve credentials
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    if not creds.valid:
        creds.refresh(Request())

    url = f"https://geminidataanalytics.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}:chat"
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
        "X-Goog-API-Client": "google-adk",
    }
    payload = {
        "messages": [{"userMessage": {"text": query}}],
        "dataAgentContext": {"dataAgent": DATA_AGENT_RESOURCE},
    }

    # Exponential backoff retry loop (3 attempts)
    max_retries = 3
    backoff = 1.0

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            if response.status_code == 200:
                raw_text = response.text
                # Parse JSON array response stream
                try:
                    events = json.loads(raw_text)
                except Exception:
                    events = []

                final_text = ""
                generated_sql = ""

                for event in events:
                    sys_msg = event.get("systemMessage", {})
                    text_obj = sys_msg.get("text", {})
                    parts = text_obj.get("parts", [])
                    text_type = text_obj.get("textType", "")

                    if text_type == "FINAL_RESPONSE":
                        final_text = "\n".join(parts)
                    elif text_type == "THOUGHT":
                        for p in parts:
                            if "SELECT" in p.upper() or "FROM" in p.upper():
                                generated_sql = p

                if final_text:
                    result = final_text
                    if generated_sql:
                        result += f"\n\n[GoogleSQL Generated]:\n```sql\n{generated_sql}\n```"
                    return result
                elif raw_text:
                    return f"Data Agent Response:\n{raw_text[:1500]}"
                else:
                    return "No response returned by the Data Agent."

            elif response.status_code in (429, 500, 502, 503, 504):
                logger.warning(
                    "GDA API transient error (attempt %d/%d): HTTP %d",
                    attempt,
                    max_retries,
                    response.status_code,
                )
                time.sleep(backoff)
                backoff *= 2.0
            else:
                logger.error("GDA API non-retryable error: HTTP %d: %s", response.status_code, response.text)
                return f"Store data is temporarily unreachable (Error {response.status_code}). Please retry shortly."

        except Exception as e:
            logger.warning("GDA API request exception (attempt %d/%d): %s", attempt, max_retries, e)
            if attempt == max_retries:
                return "Store data is temporarily unreachable. Please retry shortly."
            time.sleep(backoff)
            backoff *= 2.0

    return "Store data is temporarily unreachable. Please retry shortly."
