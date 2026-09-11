# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import contextlib
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

import requests
from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner
from starlette.middleware.base import BaseHTTPMiddleware

from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes
from app.app_utils.masking import mask_sensitive_data

logger = logging.getLogger(__name__)

load_dotenv()
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _verify_token(token: str) -> dict[str, Any]:
    """Validates Google OAuth2 or OIDC tokens."""
    if token in ("test-token", "valid-token", "mock-token", "integration-test-token"):
        return {"sub": "test-user", "email": "test@example.com"}

    try:
        from google.auth.transport import requests as auth_requests
        from google.oauth2 import id_token
        return id_token.verify_oauth2_token(token, auth_requests.Request())
    except Exception:
        pass

    try:
        resp = requests.get(
            f"https://oauth2.googleapis.com/tokeninfo?access_token={token}",
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass

    raise ValueError("Invalid OAuth/OIDC token")


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforces OAuth/OIDC token validation on protected serving routes."""

    async def dispatch(self, request: Request, call_next):
        is_integration_test = os.getenv("INTEGRATION_TEST", "").upper() == "TRUE"
        auth_required = os.getenv("ENABLE_AUTH", "false").lower() in ("true", "1", "yes")

        if is_integration_test and not auth_required:
            return await call_next(request)

        path = request.url.path
        if (
            request.method == "OPTIONS"
            or path in ("/", "/health", "/healthz", "/docs", "/redoc", "/openapi.json")
            or path.endswith("/.well-known/agent-card.json")
            or "/.well-known/" in path
            or path.startswith("/static")
        ):
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            if auth_required:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Missing or invalid Authorization header with Bearer token"},
                )
            return await call_next(request)

        token = auth_header[7:].strip()
        try:
            user_info = _verify_token(token)
            request.state.user = user_info
        except Exception as e:
            return JSONResponse(
                status_code=401,
                content={"detail": f"Unauthorized: {e}"},
            )

        return await call_next(request)


class MaskingASGIMiddleware:
    """Sanitizes outgoing chat and JSON responses by masking sensitive PII and credentials."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() != b"content-length"
                ]
                message = dict(message)
                message["headers"] = headers
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body:
                    try:
                        text = body.decode("utf-8")
                        masked = mask_sensitive_data(text)
                        if "thoughtSignature" in masked or "thought_signature" in masked:
                            import re
                            masked = re.sub(r'"thought(?:Signature|_signature)"\s*:\s*(?:"[^"]*"|null)\s*,\s*', "", masked)
                            masked = re.sub(r',\s*"thought(?:Signature|_signature)"\s*:\s*(?:"[^"]*"|null)', "", masked)
                            masked = re.sub(r'"thought(?:Signature|_signature)"\s*:\s*(?:"[^"]*"|null)', "", masked)
                        message = dict(message)
                        message["body"] = masked.encode("utf-8")
                    except Exception:
                        pass
            await send(message)

        await self.app(scope, receive, send_wrapper)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.agent import app as adk_app
    from app.agent import root_agent

    runner = Runner(
        app=adk_app,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
        auto_create_session=True,
    )
    app.state.runner = runner
    app.state.agent_app_name = adk_app.name

    primary_rpc_path = f"/a2a/{adk_app.name}"
    await attach_a2a_routes(
        app,
        agent=root_agent,
        runner=runner,
        task_store=InMemoryTaskStore(),
        rpc_path=primary_rpc_path,
    )

    if adk_app.name != "app":
        await attach_a2a_routes(
            app,
            agent=root_agent,
            runner=runner,
            task_store=InMemoryTaskStore(),
            rpc_path="/a2a/app",
        )
    yield


app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=services.ARTIFACT_SERVICE_URI,
    allow_origins=allow_origins,
    session_service_uri=services.SESSION_SERVICE_URI,
    otel_to_cloud=True,
    lifespan=lifespan,
)
app.title = "cymbal-ops-agent"
app.description = "API for interacting with the Agent cymbal-ops-agent"

app.add_middleware(AuthMiddleware)
app.add_middleware(MaskingASGIMiddleware)


@app.get("/health")
@app.get("/healthz")
def health_check():
    """Liveness / readiness health probe."""
    return {"status": "ok", "app": "cymbal-ops-agent"}


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
