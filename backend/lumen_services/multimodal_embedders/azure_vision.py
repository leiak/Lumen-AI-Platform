"""M38.4: Azure Computer Vision embedder (cloud stub).

Documented in spec §3.4 and listed in the ``provider`` enum, but no
real call yet — see ``_cloud_stub.py`` docstring for why.

When a real impl lands it will hit the Azure ``vision/vectorize`` endpoint
under the configured ``base_url`` (``https://<region>.api.cognitive.
microsoft.com/`` typically — overridable per deployment). Azure
returns 1024 dim for the standard "image retrieval" vectorise call.
"""
from __future__ import annotations

from ._cloud_stub import _CloudStubEmbedder


class AzureVisionEmbedder(_CloudStubEmbedder):
    """Azure Computer Vision embedding — stub, raises NotImplementedError.

    Real impl will hit Azure ``vectorizeImage`` / ``vectorizeText`` and
    parse the 1024-dim float vector from the JSON response. The
    configured ``base_url`` must point at the regional endpoint that
    matches the deployment — admins usually override per tenant.
    """

    provider_name: str = "azure_vision"
    dimension: int = 1024