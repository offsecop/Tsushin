"""
Container Runtime Abstraction Layer
Phase: GKE Readiness

Provides a pluggable interface for container orchestration backends.
Currently supports Docker (default, local dev) with a Kubernetes stub
for future GKE deployment.

Usage:
    from services.container_runtime import get_container_runtime
    runtime = get_container_runtime()
    container = runtime.create_container(...)
"""

import os
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class ContainerRuntime(ABC):
    """
    Abstract base class for container runtime backends.

    All container lifecycle operations go through this interface,
    allowing the application to run on Docker (local) or Kubernetes (GKE)
    without changing service-layer code.
    """

    @abstractmethod
    def create_container(
        self,
        image: str,
        name: str,
        *,
        volumes: Optional[Dict[str, Dict[str, str]]] = None,
        environment: Optional[Dict[str, str]] = None,
        ports: Optional[Dict[str, Any]] = None,
        network: Optional[str] = None,
        restart_policy: Optional[Dict[str, str]] = None,
        mem_limit: Optional[str] = None,
        memswap_limit: Optional[str] = None,
        cpu_quota: Optional[int] = None,
        command: Optional[List[str]] = None,
        labels: Optional[Dict[str, str]] = None,
        detach: bool = True,
    ) -> Any:
        """
        Create and start a container.

        Args:
            image: Container image name/tag
            name: Container name
            volumes: Volume mount mapping {host_path: {bind, mode}}
            environment: Environment variables
            ports: Port mapping {container_port: (host_ip, host_port)}
            network: Network name to attach to
            restart_policy: Restart policy dict (e.g. {"Name": "unless-stopped"})
            mem_limit: Memory limit (e.g. "2g")
            memswap_limit: Memory + swap limit
            cpu_quota: CPU quota in microseconds
            command: Command to run in container
            labels: Container labels
            detach: Run in background (always True for our use cases)

        Returns:
            Container object (Docker Container or K8s Pod wrapper)
        """
        ...

    @abstractmethod
    def get_container(self, name_or_id: str) -> Any:
        """
        Get a container by name or ID.

        Args:
            name_or_id: Container name or ID

        Returns:
            Container object

        Raises:
            ContainerNotFoundError: If container doesn't exist
        """
        ...

    @abstractmethod
    def stop_container(self, name_or_id: str, timeout: int = 30) -> None:
        """
        Stop a running container.

        Args:
            name_or_id: Container name or ID
            timeout: Graceful shutdown timeout in seconds

        Raises:
            ContainerNotFoundError: If container doesn't exist
        """
        ...

    @abstractmethod
    def remove_container(self, name_or_id: str, force: bool = False) -> None:
        """
        Remove a container.

        Args:
            name_or_id: Container name or ID
            force: Force remove even if running

        Raises:
            ContainerNotFoundError: If container doesn't exist
        """
        ...

    @abstractmethod
    def start_container(self, name_or_id: str) -> None:
        """
        Start a stopped container.

        Args:
            name_or_id: Container name or ID

        Raises:
            ContainerNotFoundError: If container doesn't exist
        """
        ...

    @abstractmethod
    def restart_container(self, name_or_id: str, timeout: int = 30) -> None:
        """
        Restart a container.

        Args:
            name_or_id: Container name or ID
            timeout: Graceful shutdown timeout in seconds
        """
        ...

    @abstractmethod
    def get_container_status(self, name_or_id: str) -> str:
        """
        Get container status string.

        Args:
            name_or_id: Container name or ID

        Returns:
            Status string: "running", "exited", "not_found", etc.
        """
        ...

    @abstractmethod
    def get_container_attrs(self, name_or_id: str) -> Dict[str, Any]:
        """
        Get full container attributes/metadata.

        Args:
            name_or_id: Container name or ID

        Returns:
            Dict of container attributes (image tags, state, created timestamp, etc.)
        """
        ...

    @abstractmethod
    def exec_run(
        self,
        name_or_id: str,
        cmd: List[str],
        *,
        workdir: Optional[str] = None,
        user: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        demux: bool = False,
        detach: bool = False,
    ) -> Any:
        """
        Execute a command inside a running container.

        Args:
            name_or_id: Container name or ID
            cmd: Command and arguments
            workdir: Working directory inside container
            user: User to run as (e.g. "root")
            environment: Additional environment variables
            demux: Separate stdout/stderr
            detach: Run in background

        Returns:
            Exec result with exit_code and output
        """
        ...

    @abstractmethod
    def exec_create_and_start(
        self,
        name_or_id: str,
        cmd: List[str],
        *,
        workdir: Optional[str] = None,
        stream: bool = False,
        demux: bool = False,
    ) -> Any:
        """
        Low-level exec create + start for streaming use cases.

        Args:
            name_or_id: Container name or ID
            cmd: Command and arguments
            workdir: Working directory
            stream: Enable output streaming
            demux: Separate stdout/stderr

        Returns:
            Tuple of (exec_id, output_generator_or_bytes)
        """
        ...

    @abstractmethod
    def exec_inspect(self, exec_id: str) -> Dict[str, Any]:
        """
        Inspect an exec instance to get exit code etc.

        Args:
            exec_id: Exec instance ID

        Returns:
            Dict with ExitCode and other exec metadata
        """
        ...

    @abstractmethod
    def commit_container(
        self,
        name_or_id: str,
        repository: str,
        tag: str,
        message: str = "",
    ) -> Any:
        """
        Commit a container's current state as a new image.

        Args:
            name_or_id: Container name or ID
            repository: Image repository name
            tag: Image tag
            message: Commit message

        Returns:
            Image object/reference
        """
        ...

    @abstractmethod
    def image_exists(self, image_name: str) -> bool:
        """
        Check if a container image exists locally.

        Args:
            image_name: Full image name with tag

        Returns:
            True if image exists
        """
        ...

    @abstractmethod
    def remove_image(self, image_name: str, force: bool = False) -> None:
        """
        Remove a container image.

        Args:
            image_name: Full image name with tag
            force: Force removal
        """
        ...

    @abstractmethod
    def list_containers(self, filters: Optional[Dict[str, Any]] = None) -> List[Any]:
        """
        List containers, optionally filtered.

        Args:
            filters: Docker-style filters dict

        Returns:
            List of container objects
        """
        ...

    @abstractmethod
    def get_logs(self, name_or_id: str, tail: int = 100) -> str:
        """
        Get container logs.

        Args:
            name_or_id: Container name or ID
            tail: Number of lines from the end

        Returns:
            Log output as string
        """
        ...

    @abstractmethod
    def health_check(self, name_or_id: str) -> Dict[str, Any]:
        """
        Perform a basic health check on a container.

        Args:
            name_or_id: Container name or ID

        Returns:
            Dict with status, container_state, and optional error
        """
        ...

    @abstractmethod
    def get_or_create_network(self, network_name: str) -> Any:
        """
        Get an existing network or create it.

        Args:
            network_name: Network name

        Returns:
            Network object
        """
        ...

    @abstractmethod
    def ensure_container_on_network(self, name_or_id: str, network_name: str) -> None:
        """
        Ensure a container is connected to a specific network.

        Args:
            name_or_id: Container name or ID
            network_name: Network to connect to
        """
        ...

    @abstractmethod
    def get_container_network_ip(self, name_or_id: str, network_name: str) -> str:
        """
        Get a container's IP address on a specific network.

        Args:
            name_or_id: Container name or ID
            network_name: Network name

        Returns:
            IP address string, or empty string if not found
        """
        ...


class ContainerNotFoundError(Exception):
    """Raised when a container is not found by the runtime."""
    pass


class ContainerRuntimeError(Exception):
    """Raised for general container runtime errors."""
    pass


# ---------------------------------------------------------------------------
# Docker Runtime — wraps the existing docker-py behavior exactly
# ---------------------------------------------------------------------------

class DockerRuntime(ContainerRuntime):
    """
    Docker runtime implementation using docker-py.

    This preserves the exact behavior of the existing direct Docker calls
    in ToolboxContainerService and MCPContainerManager.
    """

    def __init__(self):
        import docker as docker_lib
        try:
            self._client = docker_lib.from_env()
            logger.info("DockerRuntime: Docker client initialized")
        except docker_lib.errors.DockerException as e:
            logger.error(f"DockerRuntime: Failed to initialize Docker client: {e}")
            raise RuntimeError(
                f"Docker is not available. Please ensure Docker is installed and running. Error: {e}"
            )

    @property
    def raw_client(self):
        """Access the underlying docker.DockerClient for advanced/legacy operations."""
        return self._client

    def create_container(
        self,
        image: str,
        name: str,
        *,
        volumes: Optional[Dict[str, Dict[str, str]]] = None,
        environment: Optional[Dict[str, str]] = None,
        ports: Optional[Dict[str, Any]] = None,
        network: Optional[str] = None,
        restart_policy: Optional[Dict[str, str]] = None,
        mem_limit: Optional[str] = None,
        memswap_limit: Optional[str] = None,
        cpu_quota: Optional[int] = None,
        command: Optional[List[str]] = None,
        labels: Optional[Dict[str, str]] = None,
        detach: bool = True,
    ) -> Any:
        import docker as docker_lib
        try:
            kwargs = {
                "image": image,
                "name": name,
                "detach": detach,
            }
            if volumes is not None:
                kwargs["volumes"] = volumes
            if environment is not None:
                kwargs["environment"] = environment
            if ports is not None:
                kwargs["ports"] = ports
            if network is not None:
                kwargs["network"] = network
            if restart_policy is not None:
                kwargs["restart_policy"] = restart_policy
            if mem_limit is not None:
                kwargs["mem_limit"] = mem_limit
            if memswap_limit is not None:
                kwargs["memswap_limit"] = memswap_limit
            if cpu_quota is not None:
                kwargs["cpu_quota"] = cpu_quota
            if command is not None:
                kwargs["command"] = command
            if labels is not None:
                kwargs["labels"] = labels

            container = self._client.containers.run(**kwargs)
            logger.info(f"DockerRuntime: Created container {name} (ID: {container.id})")
            return container
        except docker_lib.errors.APIError as e:
            logger.error(f"DockerRuntime: Failed to create container {name}: {e}")
            raise ContainerRuntimeError(f"Failed to create container: {e}")

    def get_container(self, name_or_id: str) -> Any:
        import docker as docker_lib
        try:
            return self._client.containers.get(name_or_id)
        except docker_lib.errors.NotFound:
            raise ContainerNotFoundError(f"Container {name_or_id} not found")
        except docker_lib.errors.APIError as e:
            raise ContainerRuntimeError(f"Docker API error: {e}")

    def stop_container(self, name_or_id: str, timeout: int = 30) -> None:
        import docker as docker_lib
        try:
            container = self._client.containers.get(name_or_id)
            container.stop(timeout=timeout)
        except docker_lib.errors.NotFound:
            raise ContainerNotFoundError(f"Container {name_or_id} not found")
        except docker_lib.errors.APIError as e:
            raise ContainerRuntimeError(f"Failed to stop container: {e}")

    def remove_container(self, name_or_id: str, force: bool = False) -> None:
        import docker as docker_lib
        try:
            container = self._client.containers.get(name_or_id)
            container.remove(force=force)
        except docker_lib.errors.NotFound:
            raise ContainerNotFoundError(f"Container {name_or_id} not found")
        except docker_lib.errors.APIError as e:
            raise ContainerRuntimeError(f"Failed to remove container: {e}")

    def start_container(self, name_or_id: str) -> None:
        import docker as docker_lib
        try:
            container = self._client.containers.get(name_or_id)
            container.start()
        except docker_lib.errors.NotFound:
            raise ContainerNotFoundError(f"Container {name_or_id} not found")
        except docker_lib.errors.APIError as e:
            raise ContainerRuntimeError(f"Failed to start container: {e}")

    def restart_container(self, name_or_id: str, timeout: int = 30) -> None:
        import docker as docker_lib
        try:
            container = self._client.containers.get(name_or_id)
            container.restart(timeout=timeout)
        except docker_lib.errors.NotFound:
            raise ContainerNotFoundError(f"Container {name_or_id} not found")
        except docker_lib.errors.APIError as e:
            raise ContainerRuntimeError(f"Failed to restart container: {e}")

    def get_container_status(self, name_or_id: str) -> str:
        import docker as docker_lib
        try:
            container = self._client.containers.get(name_or_id)
            container.reload()
            return container.status
        except docker_lib.errors.NotFound:
            return "not_found"
        except docker_lib.errors.APIError:
            return "error"

    def get_container_attrs(self, name_or_id: str) -> Dict[str, Any]:
        import docker as docker_lib
        try:
            container = self._client.containers.get(name_or_id)
            container.reload()
            return {
                "id": container.id,
                "name": container.name,
                "status": container.status,
                "image_tags": container.image.tags if container.image.tags else [str(container.image.id)[:12]],
                "created": container.attrs.get("Created"),
                "state": container.attrs.get("State", {}),
                "network_settings": container.attrs.get("NetworkSettings", {}),
            }
        except docker_lib.errors.NotFound:
            raise ContainerNotFoundError(f"Container {name_or_id} not found")
        except docker_lib.errors.APIError as e:
            raise ContainerRuntimeError(f"Docker API error: {e}")

    def exec_run(
        self,
        name_or_id: str,
        cmd: List[str],
        *,
        workdir: Optional[str] = None,
        user: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        demux: bool = False,
        detach: bool = False,
    ) -> Any:
        import docker as docker_lib
        try:
            container = self._client.containers.get(name_or_id)
            kwargs = {"cmd": cmd, "demux": demux, "detach": detach}
            if workdir is not None:
                kwargs["workdir"] = workdir
            if user is not None:
                kwargs["user"] = user
            if environment is not None:
                kwargs["environment"] = environment
            return container.exec_run(**kwargs)
        except docker_lib.errors.NotFound:
            raise ContainerNotFoundError(f"Container {name_or_id} not found")
        except docker_lib.errors.APIError as e:
            raise ContainerRuntimeError(f"Docker API error during exec: {e}")

    def exec_create_and_start(
        self,
        name_or_id: str,
        cmd: List[str],
        *,
        workdir: Optional[str] = None,
        stream: bool = False,
        demux: bool = False,
    ) -> Any:
        import docker as docker_lib
        try:
            container = self._client.containers.get(name_or_id)
            exec_id = container.client.api.exec_create(
                container.id,
                cmd,
                workdir=workdir,
                tty=False,
                stdout=True,
                stderr=True,
            )
            output = container.client.api.exec_start(exec_id, stream=stream, demux=demux)
            return exec_id, output
        except docker_lib.errors.NotFound:
            raise ContainerNotFoundError(f"Container {name_or_id} not found")
        except docker_lib.errors.APIError as e:
            raise ContainerRuntimeError(f"Docker API error during exec: {e}")

    def exec_inspect(self, exec_id: str) -> Dict[str, Any]:
        return self._client.api.exec_inspect(exec_id)

    def commit_container(
        self,
        name_or_id: str,
        repository: str,
        tag: str,
        message: str = "",
    ) -> Any:
        import docker as docker_lib
        try:
            container = self._client.containers.get(name_or_id)
            return container.commit(repository=repository, tag=tag, message=message)
        except docker_lib.errors.NotFound:
            raise ContainerNotFoundError(f"Container {name_or_id} not found")
        except docker_lib.errors.APIError as e:
            raise ContainerRuntimeError(f"Failed to commit container: {e}")

    def image_exists(self, image_name: str) -> bool:
        import docker as docker_lib
        try:
            self._client.images.get(image_name)
            return True
        except docker_lib.errors.ImageNotFound:
            return False

    def remove_image(self, image_name: str, force: bool = False) -> None:
        import docker as docker_lib
        try:
            self._client.images.remove(image_name, force=force)
        except docker_lib.errors.APIError as e:
            raise ContainerRuntimeError(f"Failed to remove image: {e}")

    def list_containers(self, filters: Optional[Dict[str, Any]] = None) -> List[Any]:
        kwargs = {}
        if filters:
            kwargs["filters"] = filters
        return self._client.containers.list(**kwargs)

    def get_logs(self, name_or_id: str, tail: int = 100) -> str:
        import docker as docker_lib
        try:
            container = self._client.containers.get(name_or_id)
            logs = container.logs(tail=tail)
            return logs.decode("utf-8", errors="replace") if isinstance(logs, bytes) else str(logs)
        except docker_lib.errors.NotFound:
            raise ContainerNotFoundError(f"Container {name_or_id} not found")
        except docker_lib.errors.APIError as e:
            raise ContainerRuntimeError(f"Failed to get logs: {e}")

    def health_check(self, name_or_id: str) -> Dict[str, Any]:
        import docker as docker_lib
        result = {"status": "unknown", "container_state": "unknown", "error": None}
        try:
            container = self._client.containers.get(name_or_id)
            container.reload()
            result["container_state"] = container.status
            if container.status == "running":
                result["status"] = "healthy"
            elif container.status == "exited":
                result["status"] = "stopped"
            else:
                result["status"] = container.status
        except docker_lib.errors.NotFound:
            result["status"] = "not_found"
            result["container_state"] = "not_found"
            result["error"] = "Container not found"
        except docker_lib.errors.APIError as e:
            result["status"] = "error"
            result["error"] = str(e)
        return result

    def get_or_create_network(self, network_name: str) -> Any:
        import docker as docker_lib
        try:
            return self._client.networks.get(network_name)
        except docker_lib.errors.NotFound:
            logger.info(f"DockerRuntime: Creating network {network_name}")
            return self._client.networks.create(network_name, driver="bridge")

    def ensure_container_on_network(self, name_or_id: str, network_name: str) -> None:
        import docker as docker_lib
        try:
            container = self._client.containers.get(name_or_id)
            container.reload()
            networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
            if network_name not in networks:
                logger.info(f"DockerRuntime: Connecting {name_or_id} to {network_name}")
                network = self.get_or_create_network(network_name)
                network.connect(container)
        except docker_lib.errors.NotFound:
            raise ContainerNotFoundError(f"Container {name_or_id} not found")
        except Exception as e:
            logger.error(f"DockerRuntime: Failed to ensure container on network: {e}")

    def get_container_network_ip(self, name_or_id: str, network_name: str) -> str:
        import docker as docker_lib
        try:
            container = self._client.containers.get(name_or_id)
            container.reload()
            networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
            if network_name in networks:
                return networks[network_name].get("IPAddress", "")
            # Fallback: first available network IP
            for net_name, net_config in networks.items():
                ip = net_config.get("IPAddress", "")
                if ip:
                    logger.warning(
                        f"DockerRuntime: Container not on {network_name}, using {net_name} IP: {ip}"
                    )
                    return ip
            return ""
        except docker_lib.errors.NotFound:
            raise ContainerNotFoundError(f"Container {name_or_id} not found")
        except Exception as e:
            logger.error(f"DockerRuntime: Failed to get container IP: {e}")
            return ""


# ---------------------------------------------------------------------------
# Kubernetes Runtime — stub for future GKE implementation
# ---------------------------------------------------------------------------

class K8sRuntime(ContainerRuntime):
    """
    Kubernetes runtime stub for future GKE deployment.

    All methods raise NotImplementedError. This will be implemented
    when we deploy to GKE, mapping container operations to K8s Pod/Job
    lifecycle management.
    """

    def __init__(self):
        logger.info("K8sRuntime: Initializing Kubernetes runtime (stub)")
        # Future: from kubernetes import client, config

    def create_container(self, image, name, **kwargs):
        raise NotImplementedError("K8sRuntime.create_container not yet implemented")

    def get_container(self, name_or_id):
        raise NotImplementedError("K8sRuntime.get_container not yet implemented")

    def stop_container(self, name_or_id, timeout=30):
        raise NotImplementedError("K8sRuntime.stop_container not yet implemented")

    def remove_container(self, name_or_id, force=False):
        raise NotImplementedError("K8sRuntime.remove_container not yet implemented")

    def start_container(self, name_or_id):
        raise NotImplementedError("K8sRuntime.start_container not yet implemented")

    def restart_container(self, name_or_id, timeout=30):
        raise NotImplementedError("K8sRuntime.restart_container not yet implemented")

    def get_container_status(self, name_or_id):
        raise NotImplementedError("K8sRuntime.get_container_status not yet implemented")

    def get_container_attrs(self, name_or_id):
        raise NotImplementedError("K8sRuntime.get_container_attrs not yet implemented")

    def exec_run(self, name_or_id, cmd, **kwargs):
        raise NotImplementedError("K8sRuntime.exec_run not yet implemented")

    def exec_create_and_start(self, name_or_id, cmd, **kwargs):
        raise NotImplementedError("K8sRuntime.exec_create_and_start not yet implemented")

    def exec_inspect(self, exec_id):
        raise NotImplementedError("K8sRuntime.exec_inspect not yet implemented")

    def commit_container(self, name_or_id, repository, tag, message=""):
        raise NotImplementedError("K8sRuntime.commit_container not yet implemented")

    def image_exists(self, image_name):
        raise NotImplementedError("K8sRuntime.image_exists not yet implemented")

    def remove_image(self, image_name, force=False):
        raise NotImplementedError("K8sRuntime.remove_image not yet implemented")

    def list_containers(self, filters=None):
        raise NotImplementedError("K8sRuntime.list_containers not yet implemented")

    def get_logs(self, name_or_id, tail=100):
        raise NotImplementedError("K8sRuntime.get_logs not yet implemented")

    def health_check(self, name_or_id):
        raise NotImplementedError("K8sRuntime.health_check not yet implemented")

    def get_or_create_network(self, network_name):
        raise NotImplementedError("K8sRuntime.get_or_create_network not yet implemented")

    def ensure_container_on_network(self, name_or_id, network_name):
        raise NotImplementedError("K8sRuntime.ensure_container_on_network not yet implemented")

    def get_container_network_ip(self, name_or_id, network_name):
        raise NotImplementedError("K8sRuntime.get_container_network_ip not yet implemented")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

import threading

_runtime_instance: Optional[ContainerRuntime] = None
_runtime_lock = threading.Lock()


def get_container_runtime() -> ContainerRuntime:
    """
    Factory: return the configured container runtime singleton.

    Reads TSN_CONTAINER_RUNTIME env var:
        - "docker"     (default) -> DockerRuntime
        - "kubernetes" -> K8sRuntime

    Returns:
        ContainerRuntime instance
    """
    global _runtime_instance
    if _runtime_instance is not None:
        return _runtime_instance

    with _runtime_lock:
        if _runtime_instance is not None:
            return _runtime_instance

        backend = os.getenv("TSN_CONTAINER_RUNTIME", "docker").lower().strip()

        if backend == "docker":
            _runtime_instance = DockerRuntime()
        elif backend == "kubernetes":
            _runtime_instance = K8sRuntime()
        else:
            raise ValueError(
                f"Unknown container runtime: '{backend}'. "
                f"Set TSN_CONTAINER_RUNTIME to 'docker' or 'kubernetes'."
            )

        logger.info(f"Container runtime initialized: {backend}")
    return _runtime_instance
