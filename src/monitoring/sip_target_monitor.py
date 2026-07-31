"""SIP platform probe composition."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from src.monitoring.dns_monitor import resolve_once
from src.monitoring.ping_monitor import ping_once
from src.monitoring.tcp_monitor import tcp_connect_once
from src.storage.models import ProbeResult, TargetDefinition
from src.utils.networking import is_ip_address


async def probe_sip_target(target: TargetDefinition) -> list[ProbeResult]:
    """Probe SIP target with DNS, TCP and ICMP when meaningful."""
    tcp_target = replace(target, name=f"{target.name} TCP")
    ping_target = replace(target, name=f"{target.name} Ping")
    probes = [tcp_connect_once(tcp_target)]
    if not is_ip_address(target.host):
        dns_target = replace(target, name=f"{target.name} DNS", protocol="DNS")
        probes.append(resolve_once(dns_target))
    probes.append(ping_once(ping_target))
    return list(await asyncio.gather(*probes))
