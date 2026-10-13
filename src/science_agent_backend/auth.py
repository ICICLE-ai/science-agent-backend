import asyncio
from dataclasses import dataclass
from functools import lru_cache
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jwt

from . import config


class TapisAuthenticationError(Exception):
    pass


@dataclass(frozen=True)
class TapisIdentity:
    subject: str
    username: str
    tenant_id: str
    expires_at: int
    token: str

    def public_dict(self):
        return {
            "subject": self.subject,
            "username": self.username,
            "tenant_id": self.tenant_id,
            "expires_at": self.expires_at,
        }


def normalize_tapis_token(token: str) -> str:
    """Remove harmless formatting introduced when a JWT is copied from Markdown."""
    return str(token or "").strip().replace("\\_", "_")


@lru_cache(maxsize=1)
def tapis_tenants():
    url = f"{config.TAPIS_BASE_URL.rstrip('/')}/v3/tenants"
    try:
        with urlopen(
            Request(url, headers={"Accept": "application/json"}),
            timeout=15,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise TapisAuthenticationError(
            "The Tapis tenant registry is unavailable."
        ) from exc

    tenants = payload.get("result", []) if isinstance(payload, dict) else []
    return {
        tenant.get("tenant_id"): tenant
        for tenant in tenants
        if tenant.get("tenant_id")
    }


def validate_tapis_token(token: str) -> TapisIdentity:
    token = normalize_tapis_token(token)
    if not token:
        raise TapisAuthenticationError("A Tapis token is required.")

    try:
        unverified = jwt.decode(
            token,
            options={"verify_signature": False, "verify_exp": False},
            algorithms=["RS256"],
        )
    except jwt.PyJWTError as exc:
        raise TapisAuthenticationError("The Tapis token is malformed.") from exc

    tenant_id = str(unverified.get("tapis/tenant_id") or "")
    if tenant_id not in config.TAPIS_ALLOWED_TENANTS:
        raise TapisAuthenticationError("This Tapis tenant is not allowed.")

    tenant = tapis_tenants().get(tenant_id)
    if not tenant or tenant.get("status") != "ACTIVE":
        raise TapisAuthenticationError("The Tapis tenant is not active.")

    public_key = tenant.get("public_key")
    issuer = tenant.get("token_service")
    if not public_key or not issuer:
        raise TapisAuthenticationError(
            "The Tapis tenant does not provide token verification metadata."
        )

    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"require": ["exp", "iss", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TapisAuthenticationError("The Tapis token has expired.") from exc
    except jwt.PyJWTError as exc:
        raise TapisAuthenticationError("The Tapis token is not valid.") from exc

    subject = str(claims.get("sub") or "")
    username = str(claims.get("tapis/username") or "")
    if (
        not subject
        or not username
        or claims.get("tapis/tenant_id") != tenant_id
        or claims.get("tapis/token_type") != "access"
        or claims.get("tapis/account_type") != "user"
        or not subject.endswith(f"@{tenant_id}")
    ):
        raise TapisAuthenticationError(
            "The token is not a supported Tapis user access token."
        )

    return TapisIdentity(
        subject=subject,
        username=username,
        tenant_id=tenant_id,
        expires_at=int(claims["exp"]),
        token=token,
    )


async def validate_tapis_token_async(token: str) -> TapisIdentity:
    identity = await asyncio.to_thread(validate_tapis_token, token)
    from .database import remember_identity
    await remember_identity(identity)
    return identity


async def identity_for(connection):
    token = connection.cookies.get('X-Tapis-Token', '')
    return await validate_tapis_token_async(token)


def origin_is_allowed(origin: str | None) -> bool:
    if not origin:
        return True
    return origin.rstrip("/") in config.FRONTEND_ORIGINS
