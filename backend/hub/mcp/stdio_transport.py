"""Stdio MCP transport -- runs MCP server binaries inside tenant toolbox containers."""
import asyncio
import json
import logging
import time
from typing import Any, Optional, List, Dict
from hub.mcp.transport_base import MCPTransport

logger = logging.getLogger(__name__)

ALLOWED_MCP_STDIO_BINARIES = ["uvx", "npx", "node"]


class StdioTransport(MCPTransport):
    """
    Stdio-based MCP transport that delegates to ToolboxContainerService.

    Binary must be in ALLOWED_MCP_STDIO_BINARIES.
    Process runs as UID 1000 (toolbox user) inside the tenant container.
    """

    def __init__(self, server_config):
        super().__init__(server_config)
        self._process = None
        self._last_activity = time.time()
        self._idle_watchdog_task = None
        self._tenant_id = None

    async def connect(self) -> Any:
        """Start MCP server process inside tenant container."""
        binary = self.server_config.stdio_binary
        args = self.server_config.stdio_args or []

        # Security: Validate binary
        if not binary:
            raise ValueError("No binary specified for stdio transport")

        if binary not in ALLOWED_MCP_STDIO_BINARIES:
            raise ValueError(
                f"Binary '{binary}' not in allowed list: {ALLOWED_MCP_STDIO_BINARIES}"
            )

        # Security: Path traversal rejection
        if '/' in binary or '..' in binary or '\\' in binary:
            raise ValueError(f"Binary name contains path characters: '{binary}'")

        # Security: Validate args don't contain injection
        for arg in args:
            if any(c in str(arg) for c in [';', '|', '&', '`', '$', '(', ')']):
                raise ValueError(f"Argument contains shell metacharacters: '{arg}'")

        self._connected = True
        self._last_activity = time.time()
        self._tenant_id = self.server_config.tenant_id

        # Start idle watchdog
        idle_timeout = self.server_config.idle_timeout_seconds or 300
        self._idle_watchdog_task = asyncio.create_task(
            self._idle_watchdog(idle_timeout)
        )

        logger.info(
            f"Stdio transport ready: {binary} {' '.join(str(a) for a in args)}"
        )
        return self

    async def disconnect(self) -> None:
        """Stop the MCP server process."""
        if self._idle_watchdog_task:
            self._idle_watchdog_task.cancel()
            try:
                await self._idle_watchdog_task
            except asyncio.CancelledError:
                pass
            self._idle_watchdog_task = None
        self._connected = False
        self._session = None
        logger.info(
            f"Stdio transport disconnected for {self.server_config.server_name}"
        )

    async def ping(self) -> bool:
        return self._connected

    async def list_tools(self) -> list:
        """Execute tools/list via container exec.

        For stdio transport, tools are pre-configured in the DB.
        The actual tool listing happens during initial connection.
        """
        return []

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Execute tool via container command."""
        self._last_activity = time.time()

        binary = self.server_config.stdio_binary
        args = self.server_config.stdio_args or []

        # Build command with resource limits
        cmd_parts = [
            "ulimit -v 1048576 -t 60;",  # 1GB vmem, 60s CPU
            binary,
        ] + [str(a) for a in args]

        # Pass tool call as JSON-RPC to stdin
        tool_input = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
            "id": 1,
        })

        # Execute in tenant container
        from services.toolbox_container_service import ToolboxContainerService

        container_service = ToolboxContainerService()

        try:
            # Use printf to safely pipe JSON without shell interpretation issues
            cmd = f"printf '%s' {_shell_escape(tool_input)} | {' '.join(cmd_parts)}"
            result = await container_service.execute_command(
                tenant_id=self.server_config.tenant_id,
                command=cmd,
                timeout=self.server_config.timeout_seconds or 30,
            )

            exit_code = result.get("exit_code", -1)
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")

            if exit_code != 0:
                return {"error": stderr or f"Process exited with code {exit_code}"}

            # Parse MCP response
            try:
                parsed = json.loads(stdout)
                return parsed.get("result", parsed)
            except json.JSONDecodeError:
                return {"output": stdout}
        except Exception as e:
            logger.error(f"Stdio tool execution failed: {e}")
            return {"error": str(e)}

    async def _idle_watchdog(self, timeout_seconds: int):
        """Kill process after idle timeout."""
        try:
            while True:
                await asyncio.sleep(60)  # Check every minute
                if time.time() - self._last_activity > timeout_seconds:
                    logger.info(
                        f"Stdio transport idle timeout ({timeout_seconds}s) "
                        f"for {self.server_config.server_name}"
                    )
                    await self.disconnect()
                    break
        except asyncio.CancelledError:
            pass


def _shell_escape(value: str) -> str:
    """Escape a string for safe shell usage via single-quoting."""
    import shlex
    return shlex.quote(value)
