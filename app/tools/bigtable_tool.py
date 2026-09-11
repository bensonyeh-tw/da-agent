"""Cloud Bigtable Real-Time Alerts Tool (bigtable_mcp_toolset / read_cashier_realtime_alerts).

Connects to the Cloud Bigtable Database Toolbox GoogleSQL MCP microservice
to retrieve live 1-hour sliding-window cashier metrics, promo override rates, and audit flags.
Executes standard declaration queries via SQL over the MCP service layer.
"""

import base64
import json
import logging
import os
import struct
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "benson-data-elevate")
BIGTABLE_INSTANCE = os.getenv("BIGTABLE_INSTANCE", "operations-db")
BIGTABLE_TABLE = os.getenv("BIGTABLE_TABLE", "cashier_realtime_alerts")
BIGTABLE_MCP_URL = os.getenv(
    "BIGTABLE_MCP_URL",
    "https://mcp-toolbox-bigtable-364623295357.us-central1.run.app",
)


def _get_oidc_token(target_audience: str) -> str:
    """Acquires a Google OIDC ID token for Cloud Run service invocation."""
    # 1. Environment variable override
    env_token = os.getenv("BIGTABLE_MCP_TOKEN")
    if env_token:
        return env_token

    # 2. If running on Cloud Run / GCE, use id_token.fetch_id_token
    is_cloud_runtime = bool(os.getenv("K_SERVICE") or os.getenv("FUNCTION_TARGET"))
    if is_cloud_runtime:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import id_token
            auth_req = Request()
            return id_token.fetch_id_token(auth_req, target_audience)
        except Exception as e:
            logger.debug("Cloud runtime fetch_id_token failed: %s", e)

    # 3. If running locally or on developer workstation, use gcloud CLI helper
    try:
        import subprocess
        impersonate_sa = os.getenv(
            "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT",
            "cymbal-sa-data@benson-data-elevate.iam.gserviceaccount.com",
        )
        cmd = ["gcloud", "auth", "print-identity-token"]
        if impersonate_sa:
            cmd.append(f"--impersonate-service-account={impersonate_sa}")
        cmd.append(f"--audiences={target_audience}")
        token = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        if token:
            return token
    except Exception as e:
        logger.debug("gcloud identity-token helper failed: %s", e)

    # 4. Fallback attempt with fetch_id_token if not on cloud runtime
    if not is_cloud_runtime:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import id_token
            auth_req = Request()
            return id_token.fetch_id_token(auth_req, target_audience)
        except Exception as e:
            logger.debug("Fallback fetch_id_token failed: %s", e)

    return ""


def _decode_mcp_field(col_name: str, raw_val: Any) -> Any:
    """Decodes string, base64-encoded, and big-endian encoded numerical values from Bigtable cells."""
    if raw_val is None:
        return "" if col_name in ("audit_status", "last_event_ts") else 0.0

    # If it's already a float or int
    if isinstance(raw_val, (int, float)):
        return round(raw_val, 4) if isinstance(raw_val, float) else raw_val

    # If string, try base64 decode first
    raw_bytes = None
    if isinstance(raw_val, str):
        try:
            raw_bytes = base64.b64decode(raw_val)
        except Exception:
            raw_bytes = raw_val.encode("utf-8")
    elif isinstance(raw_val, bytes):
        raw_bytes = raw_val

    if raw_bytes is not None:
        if col_name in ("last_event_ts", "audit_status", "_key"):
            try:
                return raw_bytes.decode("utf-8", errors="replace")
            except Exception:
                return str(raw_val)

        # 8-byte big-endian binary integers and floats
        if len(raw_bytes) == 8:
            if "count" in col_name or "txn" in col_name or "manual" in col_name:
                try:
                    return struct.unpack(">q", raw_bytes)[0]
                except Exception:
                    pass
            else:
                try:
                    val = struct.unpack(">d", raw_bytes)[0]
                    return round(val, 4)
                except Exception:
                    try:
                        return struct.unpack(">q", raw_bytes)[0]
                    except Exception:
                        pass

        try:
            decoded_str = raw_bytes.decode("utf-8")
            if decoded_str.isdigit():
                return int(decoded_str)
            try:
                return round(float(decoded_str), 4)
            except ValueError:
                return decoded_str
        except Exception:
            pass

    return raw_val


def read_cashier_realtime_alerts(store_id: str, cashier_id: str) -> str:
    """Reads live 1-hour sliding-window cashier metrics, override rates, and audit status flags from Cloud Bigtable.

    Invokes the Bigtable MCP Toolbox GoogleSQL microservice to query the operations-db
    cashier_realtime_alerts table with standard SQL declarations.

    Args:
        store_id: Store identifier, formatted as STORE_XXX (e.g., 'STORE_048' or '48').
        cashier_id: Cashier identifier, formatted as CASH_YYYY (e.g., 'CASH_1190' or '1190').

    Returns:
        Structured operational report with live 1-hour rolling metrics and audit status flags.
    """
    logger.info("read_cashier_realtime_alerts: store=%s, cashier=%s", store_id, cashier_id)

    # Normalize identifiers
    s_id = store_id.strip()
    if not s_id.upper().startswith("STORE_"):
        s_id = f"STORE_{int(s_id):03d}" if s_id.isdigit() else f"STORE_{s_id}"

    c_id = cashier_id.strip()
    if not c_id.upper().startswith("CASH_"):
        c_id = f"CASH_{int(c_id):04d}" if c_id.isdigit() else f"CASH_{c_id}"

    # 1. Query the Bigtable MCP Toolbox microservice via standard JSON-RPC
    mcp_endpoint = f"{BIGTABLE_MCP_URL.rstrip('/')}/mcp"
    token = _get_oidc_token(BIGTABLE_MCP_URL)

    headers = {
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    json_rpc_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "read_cashier_realtime_alerts",
            "arguments": {
                "store_id": s_id,
                "cashier_id": c_id,
            },
        },
        "id": int(time.time()),
    }

    try:
        response = requests.post(
            mcp_endpoint,
            headers=headers,
            json=json_rpc_payload,
            timeout=15,
        )

        if response.status_code == 200:
            rpc_res = response.json()
            result = rpc_res.get("result", {})
            content = result.get("content", [])

            if content:
                first_item = content[0]
                item_text = first_item.get("text", "")
                try:
                    record = json.loads(item_text)
                except Exception:
                    record = {}

                if record:
                    audit_status = _decode_mcp_field("audit_status", record.get("audit_status", "clear"))
                    promo_rate = _decode_mcp_field("promo_rate", record.get("promo_rate", 0.0))
                    manual_count = _decode_mcp_field("manual_count", record.get("manual_count", 0))
                    risk_score = _decode_mcp_field("risk_score", record.get("risk_score", 0.0))
                    last_event_ts = _decode_mcp_field("last_event_ts", record.get("last_event_ts", "Unknown"))
                    row_key = record.get("_key", f"{s_id}#{c_id}")

                    # Determine audit evaluation
                    is_review = str(audit_status).lower() in ("review", "escalate", "flagged") or float(promo_rate) >= 0.80
                    evaluation_msg = (
                        "⚠️ ACTIVE REVIEW REQUIRED: Cashier exhibits elevated real-time promo abuse."
                        if is_review
                        else "✅ CLEAR: Cashier activity within normal parameters."
                    )

                    return (
                        f"### Cloud Bigtable Live 1-Hour Operational Metrics\n"
                        f"**Target:** {s_id} | Cashier {c_id}\n"
                        f"**Bigtable Row Key:** `{row_key}`\n"
                        f"**Audit Status Flag:** `{str(audit_status).upper()}`\n"
                        f"**Live 1-Hour Override Rate:** {float(promo_rate) * 100:.1f}%\n"
                        f"**1-Hour Manual Override Count:** {manual_count}\n"
                        f"**1-Hour Total Transactions:** 1\n"
                        f"**Real-Time ML Risk Score:** {float(risk_score):.4f}\n"
                        f"**Last Event Timestamp:** {last_event_ts}\n\n"
                        f"**Audit Evaluation:** {evaluation_msg}"
                    )

            return (
                f"No live alerts found in Cloud Bigtable for {s_id} Cashier {c_id}.\n"
                f"Status: Normal (no active fraud flags or anomalies detected in the last 1 hour)."
            )

        logger.warning(
            "Bigtable MCP service returned HTTP %d: %s",
            response.status_code,
            response.text[:200],
        )

    except Exception as e:
        logger.warning("Bigtable MCP microservice invocation error: %s", e)

    # Graceful fallback: Bigtable direct point lookup
    try:
        from google.cloud import bigtable
        from google.cloud.bigtable import row_filters

        client = bigtable.Client(project=PROJECT_ID)
        instance = client.instance(BIGTABLE_INSTANCE)
        table = instance.table(BIGTABLE_TABLE)

        prefix = f"{s_id}#{c_id}"
        row_filter = row_filters.RowKeyRegexFilter(f"^{prefix}.*".encode())
        rows = list(table.read_rows(filter_=row_filter, limit=5))

        if not rows:
            return (
                f"No live alerts found in Cloud Bigtable for {s_id} Cashier {c_id}.\n"
                f"Status: Normal (no active fraud flags or anomalies detected in the last 1 hour)."
            )

        latest_row = rows[0]
        parsed_stats: dict[str, Any] = {}
        parsed_flags: dict[str, Any] = {}

        for cf, cols in latest_row.cells.items():
            for col, cells in cols.items():
                col_name = col.decode("utf-8")
                val = _decode_mcp_field(col_name, cells[0].value)
                if cf == "stats":
                    parsed_stats[col_name] = val
                elif cf == "flags":
                    parsed_flags[col_name] = val

        audit_status = parsed_flags.get("audit_status", "clear")
        promo_rate = parsed_stats.get("cashier_1h_promo_rate", 0.0)
        override_count = parsed_stats.get("cashier_1h_manual_override_count", 0)
        txn_count = parsed_stats.get("cashier_1h_txn_count", 0)
        risk_score = parsed_stats.get("risk_score", 0.0)
        last_ts = parsed_stats.get("last_event_ts", "Unknown")

        is_review = str(audit_status).lower() in ("review", "escalate") or float(promo_rate) >= 0.80
        evaluation_msg = (
            "⚠️ ACTIVE REVIEW REQUIRED: Cashier exhibits elevated real-time promo abuse."
            if is_review
            else "✅ CLEAR: Cashier activity within normal parameters."
        )

        return (
            f"### Cloud Bigtable Live 1-Hour Operational Metrics\n"
            f"**Target:** {s_id} | Cashier {c_id}\n"
            f"**Bigtable Row Key:** `{latest_row.row_key.decode('utf-8')}`\n"
            f"**Audit Status Flag:** `{str(audit_status).upper()}`\n"
            f"**Live 1-Hour Override Rate:** {float(promo_rate) * 100:.1f}%\n"
            f"**1-Hour Manual Override Count:** {override_count}\n"
            f"**1-Hour Total Transactions:** {txn_count}\n"
            f"**Real-Time ML Risk Score:** {float(risk_score):.4f}\n"
            f"**Last Event Timestamp:** {last_ts}\n\n"
            f"**Audit Evaluation:** {evaluation_msg}"
        )

    except Exception as e:
        logger.error("Error reading Bigtable %s:%s: %s", BIGTABLE_INSTANCE, BIGTABLE_TABLE, e)
        # Exception context {e} is NOT leaked to user stream
        return "Cloud Bigtable operational query temporarily unavailable. Please retry shortly."
