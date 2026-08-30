from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from jwt import PyJWKClient

from app.models import Actor, ActorRole
from app.settings import Settings


@lru_cache(maxsize=8)
def _jwks_client(issuer: str) -> PyJWKClient:
    return PyJWKClient(f"{issuer}/.well-known/jwks.json")


def _parse_local_roles(value: str) -> set[ActorRole]:
    roles: set[ActorRole] = set()
    for raw in value.split(","):
        try:
            roles.add(ActorRole(raw.strip()))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown local role: {raw}") from exc
    return roles or {ActorRole.CITIZEN}


def get_actor(
    request: Request,
    authorization: str | None = Header(default=None),
    x_actor_id: str = Header(default="anonymous"),
    x_actor_role: str = Header(default="citizen"),
) -> Actor:
    settings: Settings = request.app.state.settings
    if settings.auth_mode == "local":
        return Actor(actor_id=x_actor_id[:160], roles=_parse_local_roles(x_actor_role))

    if not authorization:
        # Public disaster reports and privacy-safe searches must remain usable without an account.
        # Privileged routes still reject this citizen-only actor through require_roles().
        return Actor(actor_id=x_actor_id[:160], roles={ActorRole.CITIZEN})
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token is required"
        )
    token = authorization.removeprefix("Bearer ").strip()
    issuer = (
        f"https://cognito-idp.{settings.aws_region}.amazonaws.com/{settings.cognito_user_pool_id}"
    )
    try:
        jwks = _jwks_client(issuer)
        signing_key = jwks.get_signing_key_from_jwt(token)
        unverified = jwt.decode(token, options={"verify_signature": False})
        token_use = unverified.get("token_use")
        audience = settings.cognito_app_client_id if token_use == "id" else None
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={
                "verify_aud": token_use == "id",
                "require": ["exp", "sub", "token_use"],
            },
        )
        if token_use not in {"id", "access"}:
            raise jwt.InvalidTokenError("unsupported token_use")
        if token_use == "access" and claims.get("client_id") != settings.cognito_app_client_id:
            raise jwt.InvalidTokenError("wrong app client")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    groups = claims.get("cognito:groups", [])
    roles = {ActorRole(group) for group in groups if group in {role.value for role in ActorRole}}
    roles.add(ActorRole.CITIZEN)
    return Actor(actor_id=str(claims["sub"]), roles=roles)


def require_roles(*allowed: ActorRole) -> Callable[[Actor], Actor]:
    def dependency(actor: Annotated[Actor, Depends(get_actor)]) -> Actor:
        if not actor.roles.intersection(allowed):
            raise HTTPException(status_code=403, detail="Insufficient role")
        return actor

    return dependency
