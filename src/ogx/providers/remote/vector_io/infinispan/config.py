# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

from typing import Any

from pydantic import BaseModel, Field, HttpUrl, SecretStr, model_validator

from ogx.core.storage.datatypes import KVStoreReference, SqlStoreReference
from ogx_api import json_schema_type


@json_schema_type
class InfinispanVectorIOConfig(BaseModel):
    """Configuration for the Infinispan vector I/O provider."""

    url: HttpUrl = Field(
        default=HttpUrl("http://localhost:11222"), description="Infinispan server URL (e.g., http://localhost:11222)"
    )
    username: str | None = Field(default=None, description="Authentication username")
    password: SecretStr | None = Field(default=None, description="Authentication password")
    use_https: bool = Field(default=False, description="Enable HTTPS/TLS connection")
    auth_mechanism: str = Field(default="digest", description="Authentication mechanism: 'digest' or 'basic'")
    verify_tls: bool = Field(
        default=True,
        description="Verify TLS certificates for HTTPS connections (set to False only for development/testing with self-signed certificates)",
    )
    persistence: KVStoreReference = Field(description="Config for KV store backend")
    metadata_store: SqlStoreReference | None = Field(
        default=None,
        description="SQL store reference for tenant-isolated vector store metadata",
    )

    @model_validator(mode="after")
    def _validate_tls_consistency(self) -> "InfinispanVectorIOConfig":
        url_scheme = str(self.url).split("://")[0] if self.url else "http"
        url_is_https = url_scheme == "https"
        if self.use_https and not url_is_https:
            raise ValueError(
                f"use_https=True but URL scheme is '{url_scheme}'. Use an https:// URL or set use_https=False."
            )
        if url_is_https and not self.use_https:
            raise ValueError("URL uses https:// but use_https=False. Set use_https=True or use an http:// URL.")
        return self

    @classmethod
    def sample_run_config(cls, __distro_dir__: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "url": "${env.INFINISPAN_URL:=http://localhost:11222}",
            "username": "${env.INFINISPAN_USERNAME:=admin}",
            "password": "${env.INFINISPAN_PASSWORD:=}",
            "use_https": False,
            "auth_mechanism": "digest",
            "verify_tls": True,
            "persistence": KVStoreReference(
                backend="kv_default",
                namespace="vector_io::infinispan",
            ).model_dump(exclude_none=True),
        }
