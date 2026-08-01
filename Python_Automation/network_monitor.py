#!/usr/bin/env python3
"""
RATU Network — Health Monitoring Script
=========================================
Connects to every Layer-3-addressable RATU device, checks OSPF adjacency
state and interface status, and prints a pass/fail health report — the
kind of check that would back the AIOps anomaly-detection layer described
in Phase 6 (a real system would run this on a schedule and alert on
failures instead of printing them).

Requirements:
    pip install netmiko --break-system-packages   (Linux/Mac)
    pip install netmiko                            (Windows)

See backup_devices.py's module docstring for the Packet Tracer /
host-network limitation — the same applies here.
"""

import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoTimeoutException,
    NetmikoAuthenticationException,
)

USERNAME = "netadmin"
PASSWORD = "StrongAdmin@RATU2026"
SECRET = "R@TU_C0re2026"

# Expected OSPF neighbor count per device, based on the RATU topology.
# Used to flag adjacencies that have silently dropped.
DEVICES = [
    {"name": "RATU-BORDER-R1", "host": "10.1.1.1", "device_type": "cisco_ios", "expected_neighbors": 3},
    {"name": "RATU-CORE-SW1", "host": "10.1.99.1", "device_type": "cisco_ios", "expected_neighbors": 1},
    {"name": "MUS-BORDER-R1", "host": "10.2.1.1", "device_type": "cisco_ios", "expected_neighbors": 1},
    {"name": "MUS-CORE-SW1", "host": "10.2.99.1", "device_type": "cisco_ios", "expected_neighbors": 1},
    {"name": "HUY-BORDER-R1", "host": "10.3.1.1", "device_type": "cisco_ios", "expected_neighbors": 1},
    {"name": "HUY-CORE-SW1", "host": "10.3.99.1", "device_type": "cisco_ios", "expected_neighbors": 1},
]

CONNECT_TIMEOUT = 10


def count_full_neighbors(ospf_output: str) -> int:
    """Count neighbor lines whose state contains FULL."""
    return len(re.findall(r"FULL", ospf_output))


def count_down_interfaces(brief_output: str) -> int:
    """Count interface lines where status or protocol is 'down' but the
    interface isn't intentionally shut down (skips administratively down)."""
    down = 0
    for line in brief_output.splitlines():
        if "administratively down" in line:
            continue
        if re.search(r"\bdown\b", line):
            down += 1
    return down


def check_device(device: dict) -> dict:
    """Run a small set of health checks against one device and return a
    result dict rather than printing directly, so results can be
    collected and summarised after all threads complete."""
    name = device["name"]
    params = {
        "device_type": device["device_type"],
        "host": device["host"],
        "username": USERNAME,
        "password": PASSWORD,
        "secret": SECRET,
        "timeout": CONNECT_TIMEOUT,
        "conn_timeout": CONNECT_TIMEOUT,
    }

    result = {"name": name, "host": device["host"], "reachable": False}
    connection = None
    try:
        connection = ConnectHandler(**params)
        connection.enable()

        ospf_raw = connection.send_command("show ip ospf neighbor")
        brief_raw = connection.send_command("show ip interface brief")

        neighbors = count_full_neighbors(ospf_raw)
        down_ifaces = count_down_interfaces(brief_raw)

        result.update({
            "reachable": True,
            "ospf_neighbors_full": neighbors,
            "ospf_expected": device["expected_neighbors"],
            "ospf_ok": neighbors >= device["expected_neighbors"],
            "down_interfaces": down_ifaces,
            "interfaces_ok": down_ifaces == 0,
        })

    except NetmikoAuthenticationException:
        result["error"] = "authentication rejected"
    except NetmikoTimeoutException:
        result["error"] = "connection timed out"
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    finally:
        if connection is not None:
            connection.disconnect()

    return result


def print_report(results: list) -> None:
    print(f"\n{'Device':<16}{'Reachable':<11}{'OSPF FULL':<11}{'Down Ifaces':<13}{'Status'}")
    print("-" * 70)

    healthy = 0
    for r in results:
        if not r["reachable"]:
            print(f"{r['name']:<16}{'NO':<11}{'-':<11}{'-':<13}UNREACHABLE ({r.get('error', 'unknown')})")
            continue

        status = "HEALTHY" if r["ospf_ok"] and r["interfaces_ok"] else "ATTENTION NEEDED"
        if status == "HEALTHY":
            healthy += 1

        ospf_ratio = f"{r['ospf_neighbors_full']}/{r['ospf_expected']}"
        print(
            f"{r['name']:<16}{'YES':<11}{ospf_ratio:<11}"
            f"{r['down_interfaces']:<13}{status}"
        )

    print("-" * 70)
    print(f"{healthy}/{len(results)} devices fully healthy.")


def main() -> None:
    print("RATU Network — Health Monitor")
    print(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(check_device, d): d for d in DEVICES}
        for future in as_completed(futures):
            results.append(future.result())

    # Keep report order matching the device list rather than completion order
    order = {d["name"]: i for i, d in enumerate(DEVICES)}
    results.sort(key=lambda r: order[r["name"]])

    print_report(results)


if __name__ == "__main__":
    main()
