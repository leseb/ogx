# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

from typing import Any

from pydantic import BaseModel, Field


class SentenceTransformersInferenceConfig(BaseModel):
    """Configuration for the sentence-transformers inference provider."""

    trust_remote_code: bool = Field(
        default=True,
        description="Whether to trust and execute remote code from model repositories. "
        "Required for the default model (nomic-ai/nomic-embed-text-v1.5). "
        "Set to False only when using models that do not require custom code.",
    )

    @classmethod
    def sample_run_config(cls, **kwargs) -> dict[str, Any]:
        return {"trust_remote_code": True}
