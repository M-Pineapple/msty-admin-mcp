"""Hardware detection for local-model sizing.

macOS uses sysctl and system_profiler. Linux and Windows fall back to psutil
and, where present, nvidia-smi.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Sequence

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore

_APPLE_CHIP_RE = re.compile(r"\b(M[1-9]\s?(?:Pro|Max|Ultra|Extreme)?)\b", re.IGNORECASE)
_KNOWN_BINS = {
    "sysctl": ("/usr/sbin/sysctl", "/sbin/sysctl"),
    "system_profiler": ("/usr/sbin/system_profiler",),
    "nvidia-smi": ("/usr/bin/nvidia-smi", "/usr/local/bin/nvidia-smi"),
}


def _binary(name: str) -> str:
    for candidate in _KNOWN_BINS.get(name, ()):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which(name)
    if found:
        return found
    return name


def _run(argv: Sequence[str], timeout: float = 8.0) -> str:
    try:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return (completed.stdout or "").strip()


def _sysctl(name: str) -> str:
    return _run([_binary("sysctl"), "-n", name])


def _int_or_none(value: str) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _bytes_to_gb(raw: Any) -> Optional[float]:
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if number > 10_000:
        return round(number / (1024 ** 3), 1)
    return round(number, 1)


def _apple_generation(chip: str) -> Optional[str]:
    match = _APPLE_CHIP_RE.search(chip or "")
    if not match:
        return None
    token = re.sub(r"\s+", " ", match.group(1).strip())
    return token[0].upper() + token[1:]


def _parse_profiler_json(raw: str) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _detect_macos() -> Dict[str, Any]:
    mem_bytes = _int_or_none(_sysctl("hw.memsize"))
    physical = _int_or_none(_sysctl("hw.physicalcpu"))
    logical = _int_or_none(_sysctl("hw.logicalcpu"))
    brand = _sysctl("machdep.cpu.brand_string")
    model = _sysctl("hw.model")
    profiler = _binary("system_profiler")
    hardware = _parse_profiler_json(_run([profiler, "SPHardwareDataType", "-json"]))
    displays = _parse_profiler_json(_run([profiler, "SPDisplaysDataType", "-json"]))

    hw_items = hardware.get("SPHardwareDataType") or []
    hw0 = hw_items[0] if hw_items and isinstance(hw_items[0], dict) else {}
    chip = str(hw0.get("chip_type") or hw0.get("cpu_type") or brand or "").strip()
    machine_name = str(hw0.get("machine_name") or hw0.get("machine_model") or model or "").strip()
    if not physical:
        cores = str(hw0.get("number_processors") or hw0.get("packages") or "")
        physical = _int_or_none(cores.split()[0]) if cores else None

    gpu = "unknown"
    vram_gb: Optional[float] = None
    disp_items = displays.get("SPDisplaysDataType") or []
    if disp_items and isinstance(disp_items[0], dict):
        gpu = str(disp_items[0].get("sppci_model") or disp_items[0].get("_name") or gpu)
        vram_raw = disp_items[0].get("spdisplays_vram") or disp_items[0].get("spdisplays_vram_shared")
        if isinstance(vram_raw, str):
            num = re.search(r"([\d.]+)", vram_raw)
            if num:
                amount = float(num.group(1))
                vram_gb = amount * 1024 if "MB" in vram_raw.upper() and amount > 16 else amount

    ram_gb = _bytes_to_gb(mem_bytes) if mem_bytes else None
    if ram_gb is None and psutil is not None:
        ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)

    arch = platform.machine()
    apple_silicon = arch in {"arm64", "aarch64"} or "Apple" in chip
    generation = _apple_generation(chip)
    unified = bool(apple_silicon)

    return {
        "platform": "Darwin",
        "arch": arch,
        "chip": chip or brand or arch,
        "apple_silicon": apple_silicon,
        "apple_generation": generation,
        "cpu_cores_physical": physical or (psutil.cpu_count(logical=False) if psutil else None),
        "cpu_cores_logical": logical or (psutil.cpu_count(logical=True) if psutil else None),
        "ram_gb": ram_gb,
        "unified_memory": unified,
        "gpu": gpu if gpu != "unknown" else (chip or "Apple GPU" if apple_silicon else "unknown"),
        "vram_gb": None if unified else vram_gb,
        "machine": machine_name or model,
        "source": ["sysctl", "system_profiler"],
    }


def _nvidia_vram_gb() -> Optional[float]:
    smi = _binary("nvidia-smi")
    raw = _run([smi, "--query-gpu=memory.total", "--format=csv,noheader,nounits"])
    if not raw:
        return None
    first = raw.splitlines()[0].strip()
    try:
        return round(float(first) / 1024.0, 1)
    except ValueError:
        return None


def _detect_psutil(system: str) -> Dict[str, Any]:
    ram_gb = None
    physical = None
    logical = None
    if psutil is not None:
        ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
        physical = psutil.cpu_count(logical=False)
        logical = psutil.cpu_count(logical=True)
    vram = _nvidia_vram_gb()
    return {
        "platform": system,
        "arch": platform.machine(),
        "chip": platform.processor() or platform.machine(),
        "apple_silicon": False,
        "apple_generation": None,
        "cpu_cores_physical": physical,
        "cpu_cores_logical": logical,
        "ram_gb": ram_gb,
        "unified_memory": False,
        "gpu": "NVIDIA" if vram else "unknown",
        "vram_gb": vram,
        "machine": platform.node(),
        "source": ["psutil"] + (["nvidia-smi"] if vram else []),
    }


def detect_hardware(profile_runner=None) -> Dict[str, Any]:
    """Return a hardware profile dict. ``profile_runner`` is for tests."""
    del profile_runner
    system = platform.system()
    if system == "Darwin":
        profile = _detect_macos()
    else:
        profile = _detect_psutil(system)
    profile["memory_kind"] = (
        "unified" if profile.get("unified_memory") else ("discrete" if profile.get("vram_gb") else "system")
    )
    return profile


def get_hardware_profile() -> Dict[str, Any]:
    """Public helper used by the MCP tool and recommend_model."""
    return detect_hardware()
