"""Unit tests for Bigtable MCP field decoding and formatting."""

import base64
import struct
import unittest

from app.tools.bigtable_tool import _decode_mcp_field


class TestBigtableDecoding(unittest.TestCase):

    def test_decode_float_big_endian(self):
        # 0.35 packed as 8-byte big-endian double
        raw_bytes = struct.pack(">d", 0.35)
        raw_b64 = base64.b64encode(raw_bytes).decode("ascii")
        decoded = _decode_mcp_field("promo_rate", raw_b64)
        self.assertAlmostEqual(decoded, 0.35, places=4)

    def test_decode_int_big_endian(self):
        # 12 packed as 8-byte big-endian int64
        raw_bytes = struct.pack(">q", 12)
        raw_b64 = base64.b64encode(raw_bytes).decode("ascii")
        decoded = _decode_mcp_field("manual_count", raw_b64)
        self.assertEqual(decoded, 12)

    def test_decode_string_utf8(self):
        raw_bytes = b"REVIEW"
        raw_b64 = base64.b64encode(raw_bytes).decode("ascii")
        decoded = _decode_mcp_field("audit_status", raw_b64)
        self.assertEqual(decoded, "REVIEW")

    def test_decode_timestamp_iso(self):
        ts = "2026-09-10T01:40:13.478Z"
        raw_b64 = base64.b64encode(ts.encode("utf-8")).decode("ascii")
        decoded = _decode_mcp_field("last_event_ts", raw_b64)
        self.assertEqual(decoded, ts)

    def test_decode_none_values(self):
        self.assertEqual(_decode_mcp_field("audit_status", None), "")
        self.assertEqual(_decode_mcp_field("promo_rate", None), 0.0)


if __name__ == "__main__":
    unittest.main()
