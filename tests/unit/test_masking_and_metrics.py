"""Unit tests for PII masking, metrics tracking, and agent callbacks."""

import unittest

from app.app_utils.masking import mask_sensitive_data, sanitize_response_payload
from app.app_utils.metrics import metrics_tracker
from app.tools.rag_tool import RAG_DECLINE_STRING


class TestMaskingAndMetrics(unittest.TestCase):

    def test_credit_card_masking(self):
        raw = "Customer card 4111-2222-3333-4444 charged $120."
        masked = mask_sensitive_data(raw)
        self.assertNotIn("4111-2222-3333", masked)
        self.assertIn("****-****-****-4444", masked)

    def test_email_masking(self):
        raw = "Notify lead cashier at john.doe@cymbalretail.com immediately."
        masked = mask_sensitive_data(raw)
        self.assertNotIn("john.doe@", masked)
        self.assertIn("jo***@cymbalretail.com", masked)

    def test_ssn_masking(self):
        raw = "Verification SSN: 123-45-6789 verified."
        masked = mask_sensitive_data(raw)
        self.assertNotIn("123-45-6789", masked)
        self.assertIn("***-**-****", masked)

    def test_phone_masking(self):
        raw = "Store manager phone: 415-555-1234."
        masked = mask_sensitive_data(raw)
        self.assertNotIn("415-555-1234", masked)
        self.assertIn("[REDACTED_PHONE]", masked)

    def test_bearer_token_masking(self):
        raw = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.fake_token_payload"
        masked = mask_sensitive_data(raw)
        self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", masked)
        self.assertIn("[REDACTED_TOKEN]", masked)

    def test_sanitize_response_payload_nested(self):
        payload = {
            "user": "alice@cymbal.com",
            "card": "5555 4444 3333 2222",
            "nested": [
                {"token": "secret: abcdefghijklmnopqrstuvwxyz123456"}
            ]
        }
        sanitized = sanitize_response_payload(payload)
        self.assertIn("al***@cymbal.com", sanitized["user"])
        self.assertIn("****-****-****-2222", sanitized["card"])
        self.assertIn("[REDACTED_TOKEN]", sanitized["nested"][0]["token"])

    def test_metrics_tracker(self):
        metrics_tracker.record_metric(
            "custom.googleapis.com/cymbal_ops/tool_execution_latency",
            0.125,
            {"tool_name": "bigtable", "status": "success"},
        )
        # Should not raise exception
        self.assertTrue(True)

    def test_rag_decline_string_definition(self):
        self.assertIn("Out of Scope Hardware", RAG_DECLINE_STRING)
        self.assertIn("No certified POS hardware documentation found", RAG_DECLINE_STRING)


if __name__ == "__main__":
    unittest.main()
