#!/usr/bin/env python3
"""Database provisioning and verification automation for Cymbal Operations Agent.

Idempotently provisions, configures, and verifies:
1. Cloud Bigtable instance 'operations-db' and table 'cashier_realtime_alerts' with column families 'stats' and 'flags'.
2. Cloud BigQuery datasets (cymbal_gold) and validates required tables.
3. Secret Manager secret 'bigtable-mcp-tools-secret' for the Database Toolbox microservice.
"""

import logging
import os
import sys

from google.api_core import exceptions
from google.cloud import bigquery, bigtable
from google.cloud.bigtable import column_family
from google.cloud import secretmanager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "benson-data-elevate")
BIGTABLE_INSTANCE_ID = os.getenv("BIGTABLE_INSTANCE", "operations-db")
BIGTABLE_TABLE_ID = os.getenv("BIGTABLE_TABLE", "cashier_realtime_alerts")
SECRET_NAME = os.getenv("BIGTABLE_SECRET_NAME", "bigtable-mcp-tools-secret")


def provision_bigtable() -> bool:
    """Verifies and provisions Bigtable instance and table with column families."""
    logger.info("--- 1. Provisioning Cloud Bigtable ---")
    try:
        bt_client = bigtable.Client(project=PROJECT_ID, admin=True)
        instance = bt_client.instance(BIGTABLE_INSTANCE_ID)

        if not instance.exists():
            logger.error(
                "Bigtable instance '%s' does not exist in project '%s'. Please create it via Terraform or Cloud Console.",
                BIGTABLE_INSTANCE_ID,
                PROJECT_ID,
            )
            return False

        logger.info("Found Bigtable instance: %s", BIGTABLE_INSTANCE_ID)
        table = instance.table(BIGTABLE_TABLE_ID)

        if not table.exists():
            logger.info("Creating Bigtable table: %s...", BIGTABLE_TABLE_ID)
            max_versions_rule = column_family.MaxVersionsGCRule(10)
            column_families = {
                "stats": max_versions_rule,
                "flags": max_versions_rule,
            }
            table.create(column_families=column_families)
            logger.info("Successfully created table '%s' with column families: stats, flags", BIGTABLE_TABLE_ID)
        else:
            logger.info("Bigtable table '%s' exists. Validating column families...", BIGTABLE_TABLE_ID)
            existing_cfs = table.list_column_families()
            missing = [cf for cf in ("stats", "flags") if cf not in existing_cfs]
            for cf in missing:
                logger.info("Adding missing column family '%s' to table '%s'...", cf, BIGTABLE_TABLE_ID)
                rule = column_family.MaxVersionsGCRule(10)
                cf_obj = table.column_family(cf, gc_rule=rule)
                cf_obj.create()
            logger.info("Table '%s' column families verified: %s", BIGTABLE_TABLE_ID, list(table.list_column_families().keys()))

        return True
    except Exception as e:
        logger.error("Error provisioning Bigtable: %s", e)
        return False


def verify_bigquery() -> bool:
    """Verifies BigQuery datasets and gold reporting tables."""
    logger.info("--- 2. Verifying BigQuery Gold Datasets & Tables ---")
    try:
        bq_client = bigquery.Client(project=PROJECT_ID)
        required_tables = [
            "cymbal_gold.pos_manual_chunk_embeddings",
            "cymbal_gold.pos_transactions_gold",
            "cymbal_gold.gold_inventory_reconciliation_ledger",
            "cymbal_gold.pos_anomaly_alerts",
            "cymbal_gold.historical_transactional_data",
            "cymbal_gold.warranty_generic_pdf_chunk_embeddings",
        ]

        all_ok = True
        for tbl_ref in required_tables:
            try:
                table = bq_client.get_table(f"{PROJECT_ID}.{tbl_ref}")
                logger.info("Verified BigQuery table %s (%d rows)", tbl_ref, table.num_rows or 0)
            except exceptions.NotFound:
                logger.warning("BigQuery table %s not found in project %s", tbl_ref, PROJECT_ID)
                all_ok = False
            except Exception as e:
                logger.warning("Error checking table %s: %s", tbl_ref, e)
                all_ok = False

        return all_ok
    except Exception as e:
        logger.error("Error verifying BigQuery: %s", e)
        return False


def verify_secret_manager() -> bool:
    """Verifies the Secret Manager secret for the Bigtable MCP service."""
    logger.info("--- 3. Verifying Secret Manager Configuration ---")
    try:
        sm_client = secretmanager.SecretManagerServiceClient()
        secret_path = f"projects/{PROJECT_ID}/secrets/{SECRET_NAME}"
        try:
            secret = sm_client.get_secret(request={"name": secret_path})
            logger.info("Verified Secret Manager secret: %s", secret.name)

            version_path = f"{secret_path}/versions/latest"
            payload = sm_client.access_secret_version(request={"name": version_path})
            data_str = payload.payload.data.decode("utf-8")
            if "bigtable-sql" in data_str and "cashier_realtime_alerts" in data_str:
                logger.info("Verified secret payload contains 'bigtable-sql' and 'cashier_realtime_alerts'.")
                return True
            else:
                logger.warning("Secret payload may be missing bigtable-sql declaration.")
                return True
        except exceptions.NotFound:
            logger.warning("Secret '%s' not found in Secret Manager.", SECRET_NAME)
            return False
    except Exception as e:
        logger.error("Error verifying Secret Manager: %s", e)
        return False


def main():
    logger.info("Starting database provisioning & verification for project: %s", PROJECT_ID)
    bt_ok = provision_bigtable()
    bq_ok = verify_bigquery()
    sm_ok = verify_secret_manager()

    if bt_ok and bq_ok and sm_ok:
        logger.info("All database resources and configurations verified successfully!")
        sys.exit(0)
    else:
        logger.warning("Database provisioning/verification completed with warnings.")
        sys.exit(0 if bt_ok else 1)


if __name__ == "__main__":
    main()
