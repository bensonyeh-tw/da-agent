"""Integration tests for Cymbal Operations Multi-Tool ADK Agent."""

import os
import sys
import unittest

# Ensure app package is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.tools.analytics_tool import cymbal_analytics_tool
from app.tools.bigtable_tool import read_cashier_realtime_alerts
from app.tools.rag_tool import pos_troubleshooting_rag_tool


class TestCymbalOperationsAgent(unittest.TestCase):

    def test_uc1_1a_hardware_error(self):
        """UC 1.1a: Hardware Error ERR-PAY-4001 EMV contactless payment freeze."""
        query = "What is the immediate field recovery protocol when a cashier encounters an ERR-PAY-4001 EMV contactless payment freeze, and how do we ensure the customer is not double-charged?"
        res = pos_troubleshooting_rag_tool(query)
        print("\n--- UC 1.1a Hardware Error Result ---")
        print(res[:500])
        self.assertIn("Toshiba", res)
        self.assertIn("ERR-PAY-4001", res)
        self.assertIn("https://storage.cloud.google.com/", res)

    def test_uc1_1c_out_of_scope_hardware(self):
        """UC 1.1c: Out-of-Scope Hardware Ford F-150 engine oil replacement."""
        query = "How do I replace the engine oil on a Ford F-150 truck?"
        res = pos_troubleshooting_rag_tool(query)
        print("\n--- UC 1.1c Out-of-Scope Hardware Result ---")
        print(res)
        self.assertIn("Out of Scope Hardware", res)

    def test_uc1_2a_stockout_risk(self):
        """UC 1.2a: Store Inventory Stockout Risk (<20h) & Total On-Hand Inventory."""
        query = "What is the estimated cover hours remaining for store inventory positions experiencing stockout risk of less than 20 hours, and what is their total on-hand inventory?"
        res = cymbal_analytics_tool(query)
        print("\n--- UC 1.2a Stockout Risk Result ---")
        print(res[:500])
        self.assertTrue(len(res) > 50)

    def test_uc1_3_realtime_cashier_metrics(self):
        """UC 1.3: Real-Time Cashier Metrics from Cloud Bigtable."""
        res = read_cashier_realtime_alerts(store_id="STORE_048", cashier_id="CASH_1190")
        print("\n--- UC 1.3 Real-Time Cashier Metrics Result ---")
        print(res)
        self.assertIn("Bigtable", res)
        self.assertIn("STORE_048", res)
        self.assertIn("CASH_1190", res)

    def test_uc2_1a_warranty_transaction(self):
        """UC 2.1a: Past Purchase & Warranty Policy Triage for TXN-20260312-0015811."""
        query = "Check transaction details for TXN-20260312-0015811 and show the warranty coverage policy for the purchased item."
        res = cymbal_analytics_tool(query)
        print("\n--- UC 2.1a Warranty Transaction Result ---")
        print(res[:500])
        self.assertTrue(len(res) > 50)


if __name__ == "__main__":
    unittest.main()
