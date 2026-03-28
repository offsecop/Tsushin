"""
Secret Provider Abstraction Layer
Phase: GKE Readiness

Provides a pluggable interface for secret/credential retrieval.
Currently supports environment variables (default, local dev) with
a GCP Secret Manager stub for future GKE deployment.

Usage:
    from services.secret_provider import get_secret_provider
    provider = get_secret_provider()
    value = provider.get_secret("TSN_APP_HOST")
    values = provider.get_secrets(["TSN_APP_HOST", "TSN_APP_PORT"])
"""

import os
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


class SecretProvider(ABC):
    """
    Abstract base class for secret/credential providers.

    All secret retrieval goes through this interface, allowing the
    application to read from environment variables (local) or
    GCP Secret Manager (GKE) without changing application code.
    """

    @abstractmethod
    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Retrieve a single secret by key.

        Args:
            key: Secret key / environment variable name
            default: Default value if secret is not found

        Returns:
            Secret value, or default if not found
        """
        ...

    @abstractmethod
    def get_secrets(self, keys: List[str]) -> Dict[str, Optional[str]]:
        """
        Retrieve multiple secrets at once.

        Args:
            keys: List of secret keys

        Returns:
            Dict mapping each key to its value (None if not found)
        """
        ...


# ---------------------------------------------------------------------------
# Environment Variable Provider — reads from os.environ (current behavior)
# ---------------------------------------------------------------------------

class EnvSecretProvider(SecretProvider):
    """
    Secret provider that reads from environment variables.

    This is the default provider and preserves the exact current behavior
    of os.getenv() calls throughout settings.py and the rest of the app.
    """

    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return os.getenv(key, default)

    def get_secrets(self, keys: List[str]) -> Dict[str, Optional[str]]:
        return {key: os.getenv(key) for key in keys}


# ---------------------------------------------------------------------------
# GCP Secret Manager Provider — stub for future GKE deployment
# ---------------------------------------------------------------------------

class GCPSecretProvider(SecretProvider):
    """
    GCP Secret Manager provider stub for future GKE deployment.

    All methods raise NotImplementedError. This will be implemented
    when we deploy to GKE, mapping secret keys to GCP Secret Manager
    secret versions.

    Will require:
        pip install google-cloud-secret-manager
        TSN_GCP_PROJECT_ID env var for the GCP project
    """

    def __init__(self):
        logger.info("GCPSecretProvider: Initializing (stub)")
        # Future implementation:
        # from google.cloud import secretmanager
        # self._client = secretmanager.SecretManagerServiceClient()
        # self._project_id = os.getenv("TSN_GCP_PROJECT_ID")

    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        raise NotImplementedError(
            "GCPSecretProvider.get_secret not yet implemented. "
            "Set TSN_SECRET_BACKEND=env to use environment variables."
        )

    def get_secrets(self, keys: List[str]) -> Dict[str, Optional[str]]:
        raise NotImplementedError(
            "GCPSecretProvider.get_secrets not yet implemented. "
            "Set TSN_SECRET_BACKEND=env to use environment variables."
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

import threading

_provider_instance: Optional[SecretProvider] = None
_provider_lock = threading.Lock()


def get_secret_provider() -> SecretProvider:
    """
    Factory: return the configured secret provider singleton.

    Reads TSN_SECRET_BACKEND env var (directly from os.environ, since
    the provider itself may not be initialized yet):
        - "env" (default) -> EnvSecretProvider
        - "gcp"           -> GCPSecretProvider

    Returns:
        SecretProvider instance
    """
    global _provider_instance
    if _provider_instance is not None:
        return _provider_instance

    with _provider_lock:
        if _provider_instance is not None:
            return _provider_instance

        # Read backend choice directly from os.environ (bootstrap — can't use
        # the provider to read its own config)
        backend = os.environ.get("TSN_SECRET_BACKEND", "env").lower().strip()

        if backend == "env":
            _provider_instance = EnvSecretProvider()
        elif backend == "gcp":
            _provider_instance = GCPSecretProvider()
        else:
            raise ValueError(
                f"Unknown secret backend: '{backend}'. "
                f"Set TSN_SECRET_BACKEND to 'env' or 'gcp'."
            )

        logger.info(f"Secret provider initialized: {backend}")
    return _provider_instance
