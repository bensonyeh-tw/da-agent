"""POS Hardware Troubleshooting RAG Tool (pos_troubleshooting_rag_tool).

Performs dense vector similarity search over fine-grained chunk embeddings in BigQuery
(cymbal_gold.pos_manual_chunk_embeddings) with adjacent context stitching (N-1 to N+1),
similarity score guardrails, keyword SEARCH fallback, and clickable GCS documentation links.
"""

import logging
import os
import time

from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "benson-data-elevate")
SIMILARITY_THRESHOLD = 0.70


RAG_DECLINE_STRING = os.getenv(
    "RAG_DECLINE_STRING",
    "Out of Scope Hardware: No certified POS hardware documentation found for this query in the Cymbal Retail operations repository.",
)


def pos_troubleshooting_rag_tool(query: str) -> str:
    """Searches official POS hardware manuals and service guides for error codes, diagnostics, and recovery protocols.

    Use this tool for:
    - Hardware fault codes (e.g. ERR-PAY-4001, ERR-DN-PRNT-24V, ERR-CLV-EMV-TIMEOUT).
    - Field recovery protocols for payment terminals, EMV PIN pads, receipt printers, touchscreens, and cash drawers.
    - Verified hardware maintenance and FRU procedures for Toshiba TCx 810, HP Engage One Pro, NCR RealPOS XR7, Diebold Nixdorf Beetle, and Clover Station Solo.

    Args:
        query: Technical error code or hardware troubleshooting question.

    Returns:
        Certified procedural runbook with steps, equipment specs, and clickable GCS documentation links.
    """
    logger.info("pos_troubleshooting_rag_tool query: %s", query)
    client = bigquery.Client(project=PROJECT_ID)

    # 1. Primary Vector Search with Adjacent Context Window Stitching
    vector_query = f"""
    WITH query_emb AS (
      SELECT AI.EMBED(@query, connection_id => "{PROJECT_ID}.us-central1.biglake-iceberg-connection", endpoint => "text-embedding-005").result AS q_emb
    ),
    matched_chunks AS (
      SELECT
        t.document_filename,
        t.document_title,
        t.equipment_covered,
        t.source_pdf_uri,
        t.chunk_index,
        ROUND(1 - ML.DISTANCE(t.embedding, q.q_emb, "COSINE"), 4) AS similarity_score
      FROM `{PROJECT_ID}.cymbal_gold.pos_manual_chunk_embeddings` t
      CROSS JOIN query_emb q
      ORDER BY similarity_score DESC
      LIMIT 1
    )
    SELECT
      m.document_filename,
      m.document_title,
      m.equipment_covered,
      REPLACE(m.source_pdf_uri, "gs://", "https://storage.cloud.google.com/") AS documentation_link,
      m.similarity_score,
      STRING_AGG(c.chunk_content, "\\n" ORDER BY c.chunk_index ASC) AS stitched_runbook
    FROM matched_chunks m
    JOIN `{PROJECT_ID}.cymbal_gold.pos_manual_chunk_embeddings` c
      ON m.document_filename = c.document_filename
      AND c.chunk_index BETWEEN (m.chunk_index - 1) AND (m.chunk_index + 1)
    GROUP BY m.document_filename, m.document_title, m.equipment_covered, m.source_pdf_uri, m.similarity_score
    """

    # Retry loop with exponential backoff (3 attempts)
    max_retries = 3
    backoff = 1.0

    for attempt in range(1, max_retries + 1):
        try:
            job_config = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("query", "STRING", query)],
                labels={"datacloud": "jetski"},
            )
            query_job = client.query(vector_query, job_config=job_config)
            rows = list(query_job.result())

            if rows:
                top_row = rows[0]
                similarity = top_row.similarity_score
                logger.info("Top vector match: %s (score: %.4f)", top_row.document_title, similarity)

                # Check safety threshold
                if similarity >= SIMILARITY_THRESHOLD:
                    return (
                        f"### Certified POS Hardware Runbook: {top_row.document_title}\n"
                        f"**Equipment Covered:** {top_row.equipment_covered}\n"
                        f"**Documentation Source:** [{top_row.document_filename}]({top_row.documentation_link})\n"
                        f"**Relevance Score:** {similarity:.4f}\n\n"
                        f"#### Procedural Runbook:\n"
                        f"{top_row.stitched_runbook}\n"
                    )

                # If below threshold, fall through to keyword SEARCH fallback
                logger.info("Similarity %.4f below threshold %.2f, attempting full-text SEARCH fallback...", similarity, SIMILARITY_THRESHOLD)

            # 2. Fallback: Full-text keyword SEARCH across chunks
            import re
            error_codes = re.findall(r"\b[A-Z][A-Z0-9]*-[A-Z0-9-]+\b", query)
            if error_codes:
                search_term = " OR ".join([f"`{code}`" for code in error_codes])
            else:
                clean_query = re.sub(r"[-&|!*~:()^\"`]", " ", query)
                words = [w for w in clean_query.split() if len(w) > 2 and w.lower() not in {"what", "when", "where", "which", "how", "the", "and", "for", "with", "this", "that"}]
                search_term = " ".join(words) if words else query

            search_query = f"""
            WITH matched_chunks AS (
              SELECT
                document_filename,
                document_title,
                equipment_covered,
                source_pdf_uri,
                chunk_index
              FROM `{PROJECT_ID}.cymbal_gold.pos_manual_chunk_embeddings`
              WHERE SEARCH(chunk_content, @search_term)
              ORDER BY chunk_index ASC
              LIMIT 1
            )
            SELECT
              m.document_filename,
              m.document_title,
              m.equipment_covered,
              REPLACE(m.source_pdf_uri, "gs://", "https://storage.cloud.google.com/") AS documentation_link,
              STRING_AGG(c.chunk_content, "\\n" ORDER BY c.chunk_index ASC) AS stitched_runbook
            FROM matched_chunks m
            JOIN `{PROJECT_ID}.cymbal_gold.pos_manual_chunk_embeddings` c
              ON m.document_filename = c.document_filename
              AND c.chunk_index BETWEEN (m.chunk_index - 1) AND (m.chunk_index + 1)
            GROUP BY m.document_filename, m.document_title, m.equipment_covered, m.source_pdf_uri
            """
            search_job_config = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("search_term", "STRING", search_term)],
                labels={"datacloud": "jetski"},
            )
            search_job = client.query(search_query, job_config=search_job_config)
            search_rows = list(search_job.result())

            if search_rows:
                s_row = search_rows[0]
                return (
                    f"### Certified POS Hardware Runbook (Keyword Match): {s_row.document_title}\n"
                    f"**Equipment Covered:** {s_row.equipment_covered}\n"
                    f"**Documentation Source:** [{s_row.document_filename}]({s_row.documentation_link})\n\n"
                    f"#### Procedural Runbook:\n"
                    f"{s_row.stitched_runbook}\n"
                )

            # Neither vector search above 0.70 nor keyword search found matches -> Exact decline string
            return RAG_DECLINE_STRING

        except Exception as e:
            logger.warning("BigQuery RAG query error (attempt %d/%d): %s", attempt, max_retries, e)
            if attempt == max_retries:
                return "Hardware runbook lookup temporarily unavailable. Please retry shortly."
            time.sleep(backoff)
            backoff *= 2.0

    return RAG_DECLINE_STRING
