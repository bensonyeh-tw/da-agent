"""Cloud Bigtable Real-Time Alerts Tool (bigtable_mcp_toolset / read_cashier_realtime_alerts).

Connects to Cloud Bigtable instance operations-db table cashier_realtime_alerts
to retrieve live 1-hour sliding-window cashier metrics, promo override rates, and audit flags.
Supports Cloud Run Database Toolbox microservice integration and direct Bigtable client execution.
"""

import json
import logging
import os
import struct
import time
from typing import Any
from google.cloud import bigtable
from google.cloud.bigtable import row_filters

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "benson-data-elevate")
BIGTABLE_INSTANCE = os.getenv("BIGTABLE_INSTANCE", "operations-db")
BIGTABLE_TABLE = os.getenv("BIGTABLE_TABLE", "cashier_realtime_alerts")
BIGTABLE_MCP_URL = os.getenv(
    "BIGTABLE_MCP_URL",
    "https://mcp-toolbox-bigtable-364623295357.us-central1.run.app",
)


def _decode_bigtable_value(column_name: str, raw_val: bytes) -> Any:
    """Decodes string and big-endian encoded binary numerical values from Bigtable cells."""
    if column_name in ("last_event_ts", "audit_status"):
        return raw_val.decode("utf-8", errors="replace")

    # 8-byte big-endian binary integers and floats
    if len(raw_val) == 8:
        if "count" in column_name or "txn" in column_name:
            return struct.unpack(">q", raw_val)[0]
        else:
            try:
                val = struct.unpack(">d", raw_val)[0]
                return round(val, 4)
            except Exception:
                return struct.unpack(">q", raw_val)[0]

    try:
        return raw_val.decode("utf-8")
    except Exception:
        return str(raw_val)


def read_cashier_realtime_alerts(store_id: str, cashier_id: str) -> str:
    """Reads live 1-hour sliding-window cashier metrics, override rates, and audit status flags from Cloud Bigtable.

    Use this tool for:
    - Real-time cashier activity within the last 1 hour.
    - Live 1-hour cashier promo override rates and manual override counts.
    - Active real-time fraud flags (flags:audit_status = 'review' or 'clear').
    - Real-time risk scores and event timestamps for specific cashiers at designated stores.

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

    prefix = f"{s_id}#{c_id}"

    try:
        client = bigtable.Client(project=PROJECT_ID)
        instance = client.instance(BIGTABLE_INSTANCE)
        table = instance.table(BIGTABLE_TABLE)

        # Apply prefix filter over reverse-timestamped row keys
        row_filter = row_filters.RowKeyRegexFilter(f"^{prefix}.*".encode("utf-8"))
        rows = list(table.read_rows(filter_=row_filter, limit=5))

        if not rows:
            return (
                f"No live alerts found in Cloud Bigtable for {s_id} Cashier {c_id}.\n"
                f"Status: Normal (no active fraud flags or anomalies detected in the last 1 hour)."
            )

        # Parse the latest row
        latest_row = rows[0]
        parsed_stats: dict[str, Any] = {}
        parsed_flags: dict[str, Any] = {}

        for cf, cols in latest_row.cells.items():
            for col, cells in cols.items():
                col_name = col.decode("utf-8")
                val = _decode_bigtable_value(col_name, cells[0].value)
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

        return (
            f"### Cloud Bigtable Live 1-Hour Operational Metrics\n"
            f"**Target:** {s_id} | Cashier {c_id}\n"
            f"**Bigtable Row Key:** `{latest_row.row_key.decode('utf-8')}`\n"
            f"**Audit Status Flag:** `{audit_status.upper()}`\n"
            f"**Live 1-Hour Override Rate:** {promo_rate * 100:.1f}%\n"
            f"**1-Hour Manual Override Count:** {override_count}\n"
            f"**1-Hour Total Transactions:** {txn_count}\n"
            f"**Real-Time ML Risk Score:** {risk_score:.4f}\n"
            f"**Last Event Timestamp:** {last_ts}\n\n"
            f"**Audit Evaluation:** {'⚠️ ACTIVE REVIEW REQUIRED: Cashier exhibits elevated real-time promo abuse.' if audit_status == 'review' or promo_rate >= 0.80 else '✅ CLEAR: Cashier activity within normal parameters.'}"
        )

    except Exception as e:
        logger.error("Error reading Bigtable %s:%s: %s", BIGTABLE_INSTANCE, BIGTABLE_TABLE, e)
        return f"Cloud Bigtable operational query temporarily unavailable: {e}"
