"""Local LLM-as-judge for `custom_response_quality` (see eval_config.yaml)."""

from google import genai
from google.genai import types
from pydantic import BaseModel


class _Verdict(BaseModel):
    score: int  # 1-5
    explanation: str


def evaluate(instance):
    reference = instance.get("reference")
    rubric = (
        "Grade the agent's final response on a 1-5 scale (1 poor, 5 excellent) for "
        "accuracy, relevance, and clarity."
    )
    if reference:
        rubric += (
            " The response should agree with the expected answer below; penalize "
            "factual disagreement with it."
        )
    prompt = (
        f"You are an expert QA evaluator for an enterprise AI assistant. {rubric}\n"
        f"User Prompt: {instance.get('prompt', '')}\n"
        f"Final Response: {instance.get('response', '')}\n"
    )
    if reference:
        prompt += f"Expected Answer (ground truth): {reference}\n"
    prompt += f"Full Agent Trace: {instance.get('agent_data', '')}\n"

    import os

    vertex_enabled = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "true").lower() in ("true", "1", "yes")
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "benson-data-elevate")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    eval_model = os.getenv("EVAL_JUDGE_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))

    if os.getenv("GEMINI_API_KEY"):
        client = genai.Client()
    else:
        client = genai.Client(vertexai=vertex_enabled, project=project, location=location)

    response = client.models.generate_content(
        model=eval_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,  # deterministic grading
            response_mime_type="application/json",
            response_schema=_Verdict,  # guaranteed schema-valid JSON
        ),
    )
    verdict = response.parsed
    if verdict is None:  # model returned nothing usable
        return {"score": 0, "explanation": response.text or ""}
    return {"score": max(1, min(5, verdict.score)), "explanation": verdict.explanation}
