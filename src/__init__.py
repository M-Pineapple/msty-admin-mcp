"""
Msty Admin MCP Server

AI-administered Msty Studio Desktop management system with database insights,
configuration management, local model orchestration, and tiered AI workflows.

Phase 1: Foundational Tools (Read-Only)
Phase 2: Configuration Management
Phase 3: Automation Bridge (Sidecar Integration)
Phase 4: Intelligence Layer (Analytics)
Phase 5: Tiered AI Workflow (Calibration)

Created by M-Pineapple 🍍
"""

__version__ = "6.0.0"
__author__ = "M-Pineapple 🍍"

from .server import mcp, main

__all__ = ["mcp", "main", "__version__", "__author__"]