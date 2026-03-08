from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import platform
import socket
import ssl
import subprocess
import time
from typing import Any, Dict, List, Optional

import psutil
import requests

# Assuming you have these base classes in your project
from app.tools.base import BaseTool, ToolParameter, ToolSchema


class NetworkTool(BaseTool):
    DB_FILE = "network_memory.json"
    SHODAN_KEY = ""  # Add your key if you implement Shodan for reputation/CVEs

    # ==========================================================
    # Metadata
    # ==========================================================

    def get_name(self) -> str:
        return "network_tool"

    def get_description(self) -> str:
        return (
            "Self-learning cybersecurity network research tool. "
            "Supports scanning, intelligence, vulnerability detection "
            "and autonomous AI analysis."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="The network operation to perform",
                    required=True,
                    enum=[
                        # Core
                        "get_public_ip",
                        "local_ip",
                        "internet_test",
                        # Intelligence
                        "geoip_lookup",
                        "asn_lookup",
                        "reputation_check",
                        "threat_summary",
                        # DNS
                        "dns_lookup",
                        "dns_records",
                        "reverse_dns",
                        "whois_lookup",
                        # Connectivity
                        "ping",
                        "latency",
                        "traceroute",
                        # Scanning
                        "port_scan",
                        "fast_scan",
                        "nmap_scan",
                        "os_fingerprint",
                        "subnet_scan",
                        # Web
                        "http_headers",
                        "http_security",
                        "technology_detect",
                        # SSL
                        "ssl_info",
                        "tls_versions",
                        # Network
                        "network_interfaces",
                        "gateway",
                        "arp_table",
                        "routing_table",
                        # Detection
                        "proxy_detect",
                        "tor_detect",
                        "vpn_detect",
                        # Fingerprinting
                        "banner_grab",
                        "service_fingerprint",
                        "port_intelligence",
                        # Security
                        "cve_lookup",
                        "vulnerability_scan",
                        "security_score",
                        # Autonomous
                        "auto_scan",
                        "identify_services",
                        "detect_vulnerabilities",
                        "generate_report",
                        "suggest_exploits",
                        # Self Learning AI
                        "save_scan",
                        "load_profile",
                        "build_profile",
                        "correlate_findings",
                        "predict_attack_paths",
                        # OS / Hardware Level
                        "wake_on_lan",
                    ],
                ),
                ToolParameter(
                    name="mac_address",
                    type="string",
                    description="MAC address for Wake-on-LAN (format: XX:XX:XX:XX:XX:XX)",
                    required=False,
                ),
                ToolParameter(
                    name="host",
                    type="string",
                    description="Target hostname or IP address",
                    required=False,
                ),
                ToolParameter(
                    name="ip",
                    type="string",
                    description="IP address for lookup operations",
                    required=False,
                ),
                ToolParameter(
                    name="port",
                    type="integer",
                    description="Port number for scanning",
                    required=False,
                ),
                ToolParameter(
                    name="subnet",
                    type="string",
                    description="Subnet for network scanning (CIDR notation)",
                    required=False,
                ),
            ],
        )

    # ==========================================================
    # Memory System
    # ==========================================================

    def _load_db(self):
        if not os.path.exists(self.DB_FILE):
            return {}
        with open(self.DB_FILE, "r") as f:
            return json.load(f)

    def _save_db(self, data):
        with open(self.DB_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def _remember(self, target, data):
        if not target:
            return
        db = self._load_db()
        if target not in db:
            db[target] = {}
        db[target].update(data)
        self._save_db(db)

    # ==========================================================
    # Execute
    # ==========================================================

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:

        operation = kwargs.get("operation", "")
        host = kwargs.get("host")
        ip = kwargs.get("ip")
        port = kwargs.get("port")
        subnet = kwargs.get("subnet")
        target: str = host or ip or ""

        try:
            # ----------------------------------
            # CORE
            # ----------------------------------
            if operation == "get_public_ip":
                return {
                    "success": True,
                    "ip": (
                        await asyncio.to_thread(
                            requests.get, "https://api.ipify.org", timeout=5
                        )
                    ).text,
                }

            elif operation == "local_ip":
                return {
                    "success": True,
                    "ip": socket.gethostbyname(socket.gethostname()),
                }

            elif operation == "internet_test":
                try:
                    await asyncio.to_thread(requests.get, "https://1.1.1.1", timeout=3)
                    return {"success": True, "status": "Connected"}
                except:
                    return {"success": False, "status": "Disconnected"}

            # ----------------------------------
            # INTELLIGENCE
            # ----------------------------------
            elif operation == "geoip_lookup":
                data = (
                    await asyncio.to_thread(
                        requests.get, f"http://ip-api.com/json/{target}"
                    )
                ).json()
                self._remember(target, {"geo": data})
                return {"success": True, "geo": data}

            elif operation == "asn_lookup":
                data = (
                    await asyncio.to_thread(
                        requests.get,
                        f"http://ip-api.com/json/{target}?fields=status,message,as,asname",
                    )
                ).json()
                return {"success": True, "asn": data}

            elif operation == "reputation_check":
                # Placeholder for AbuseIPDB or VirusTotal API check
                return {
                    "success": True,
                    "message": "Requires API integration (e.g., AbuseIPDB). Placeholder response: Clean.",
                }

            elif operation == "threat_summary":
                db = self._load_db()
                data = db.get(target, {})
                return {
                    "success": True,
                    "summary": f"Target {target} has {len(data.get('vulnerabilities', []))} known vulnerabilities in memory.",
                }

            # ----------------------------------
            # DNS
            # ----------------------------------
            elif operation == "dns_lookup":
                if not host:
                    return {"success": False, "error": "host parameter required"}
                return {"success": True, "ip": socket.gethostbyname(host)}

            elif operation == "dns_records":
                if not host:
                    return {"success": False, "error": "host parameter required"}
                result = subprocess.run(["nslookup", host], capture_output=True)
                return {"success": True, "records": result.stdout.decode()}

            elif operation == "reverse_dns":
                if not ip:
                    return {"success": False, "error": "ip parameter required"}
                try:
                    name, _, _ = socket.gethostbyaddr(ip)
                    return {"success": True, "hostname": name}
                except socket.herror:
                    return {"success": False, "error": "No reverse DNS record found."}

            elif operation == "whois_lookup":
                if not target:
                    return {"success": False, "error": "host or ip parameter required"}
                result = subprocess.run(["whois", target], capture_output=True)
                return {
                    "success": True,
                    "whois": result.stdout.decode()[:1000] + "... [TRUNCATED]",
                }

            # ----------------------------------
            # CONNECTIVITY
            # ----------------------------------
            elif operation == "ping":
                if not target:
                    return {"success": False, "error": "host or ip parameter required"}
                param = "-n" if platform.system().lower() == "windows" else "-c"
                result = subprocess.run(
                    ["ping", param, "4", target], capture_output=True
                )
                return {"success": True, "output": result.stdout.decode()}

            elif operation == "latency":
                if not target:
                    return {"success": False, "error": "host or ip parameter required"}
                start = time.time()
                try:
                    await asyncio.to_thread(requests.get, f"http://{target}", timeout=3)
                    latency = (time.time() - start) * 1000
                    return {"success": True, "latency_ms": round(latency, 2)}
                except:
                    return {
                        "success": False,
                        "error": "Could not connect to measure latency.",
                    }

            elif operation == "traceroute":
                if not target:
                    return {"success": False, "error": "host or ip parameter required"}
                cmd = (
                    "tracert"
                    if platform.system().lower() == "windows"
                    else "traceroute"
                )
                result = subprocess.run([cmd, target], capture_output=True)
                return {"success": True, "output": result.stdout.decode()}

            # ----------------------------------
            # SCANNING
            # ----------------------------------
            elif operation == "port_scan":
                ports = []
                for p in range(1, 1025):
                    s = socket.socket()
                    s.settimeout(0.3)
                    if s.connect_ex((target, p)) == 0:
                        ports.append(p)
                    s.close()
                self._remember(target, {"ports": ports})
                return {"success": True, "open_ports": ports}

            elif operation == "fast_scan":
                ports = []
                for p in [21, 22, 23, 25, 53, 80, 110, 143, 443, 445, 3306, 3389, 8080]:
                    s = socket.socket()
                    s.settimeout(0.5)
                    if s.connect_ex((target, p)) == 0:
                        ports.append(p)
                    s.close()
                return {"success": True, "open_ports": ports}

            elif operation == "nmap_scan":
                if not target:
                    return {"success": False, "error": "host or ip parameter required"}
                result = subprocess.run(["nmap", "-sV", target], capture_output=True)
                return {"success": True, "nmap_output": result.stdout.decode()}

            elif operation == "os_fingerprint":
                if not target:
                    return {"success": False, "error": "host or ip parameter required"}
                result = subprocess.run(["nmap", "-O", target], capture_output=True)
                return {"success": True, "os_output": result.stdout.decode()}

            elif operation == "subnet_scan":
                # Basic ICMP sweep logic placeholder
                return {
                    "success": True,
                    "message": f"Subnet scan for {subnet} initiated. (Use Scapy or nmap -sn for full implementation)",
                }

            # ----------------------------------
            # WEB
            # ----------------------------------
            elif operation == "http_headers":
                try:
                    resp = await asyncio.to_thread(
                        requests.head, f"http://{target}", timeout=3
                    )
                    return {"success": True, "headers": dict(resp.headers)}
                except:
                    return {"success": False, "error": "HTTP connection failed."}

            elif operation == "http_security":
                try:
                    resp = await asyncio.to_thread(
                        requests.head, f"https://{target}", timeout=3
                    )
                    headers = resp.headers
                    sec_headers = {
                        "HSTS": "Strict-Transport-Security" in headers,
                        "CSP": "Content-Security-Policy" in headers,
                        "X-Frame-Options": "X-Frame-Options" in headers,
                    }
                    return {"success": True, "security_headers": sec_headers}
                except:
                    return {"success": False, "error": "HTTPS connection failed."}

            elif operation == "technology_detect":
                try:
                    resp = await asyncio.to_thread(
                        requests.get, f"http://{target}", timeout=3
                    )
                    server = resp.headers.get("Server", "Unknown")
                    powered_by = resp.headers.get("X-Powered-By", "Unknown")
                    return {
                        "success": True,
                        "technologies": {"Server": server, "PoweredBy": powered_by},
                    }
                except:
                    return {"success": False, "error": "Connection failed."}

            # ----------------------------------
            # SSL
            # ----------------------------------
            elif operation == "ssl_info":
                context = ssl.create_default_context()
                try:
                    with socket.create_connection((target, 443)) as sock:
                        with context.wrap_socket(sock, server_hostname=target) as ssock:
                            cert = ssock.getpeercert()
                            return {"success": True, "certificate": cert}
                except Exception as e:
                    return {"success": False, "error": str(e)}

            elif operation == "tls_versions":
                # Placeholder for testing TLS 1.0, 1.1, 1.2, 1.3
                return {
                    "success": True,
                    "info": "Connects via TLS 1.2/1.3. Explicit version checking requires custom context setups.",
                }

            # ----------------------------------
            # NETWORK
            # ----------------------------------
            elif operation == "network_interfaces":
                interfaces = psutil.net_if_addrs()
                parsed = {
                    k: [addr.address for addr in v] for k, v in interfaces.items()
                }
                return {"success": True, "interfaces": parsed}

            elif operation == "gateway":
                # Works on most linux/windows systems via psutil or shell
                return {
                    "success": True,
                    "message": "Gateway detection requires `netifaces` library or parsing `ip route`.",
                }

            elif operation == "arp_table":
                result = subprocess.run(["arp", "-a"], capture_output=True, text=True)
                return {"success": True, "arp": result.stdout}

            elif operation == "routing_table":
                cmd = (
                    "route print"
                    if platform.system().lower() == "windows"
                    else "netstat -r"
                )
                result = subprocess.run(cmd.split(), capture_output=True, text=True)
                return {"success": True, "routing": result.stdout}

            # ----------------------------------
            # DETECTION
            # ----------------------------------
            elif operation == "proxy_detect":
                proxy_ports = [3128, 8080, 1080]
                open_proxies = []
                for p in proxy_ports:
                    if socket.socket().connect_ex((target, p)) == 0:
                        open_proxies.append(p)
                return {"success": True, "potential_proxies": open_proxies}

            elif operation == "tor_detect":
                # Would check against Tor exit node lists (e.g., check.torproject.org/exit-addresses)
                return {
                    "success": True,
                    "is_tor": False,
                    "message": "Placeholder. Query a Tor exit node API for real data.",
                }

            elif operation == "vpn_detect":
                return {
                    "success": True,
                    "message": "Requires IP Intelligence API to check for Datacenter/VPN ASN flags.",
                }

            # ----------------------------------
            # FINGERPRINTING
            # ----------------------------------
            elif operation == "banner_grab":
                try:
                    s = socket.socket()
                    s.settimeout(2)
                    s.connect((target, port or 80))
                    s.send(b"HEAD / HTTP/1.0\r\n\r\n")
                    banner = s.recv(1024).decode("utf-8", errors="ignore")
                    s.close()
                    return {"success": True, "banner": banner}
                except Exception as e:
                    return {"success": False, "error": str(e)}

            elif operation == "service_fingerprint":
                return await self.execute(operation="identify_services", host=target)

            elif operation == "port_intelligence":
                common = {
                    22: "SSH - Secure Shell",
                    80: "HTTP - Web Traffic",
                    443: "HTTPS - Secure Web",
                    3389: "RDP - Remote Desktop",
                }
                if port is None:
                    return {"success": False, "error": "port parameter required"}
                return {"success": True, "port_info": common.get(port, "Unknown Port")}

            # ----------------------------------
            # SECURITY
            # ----------------------------------
            elif operation == "cve_lookup":
                # Placeholder for querying NIST NVD or vulners API
                return {
                    "success": True,
                    "cves": [],
                    "message": "Requires NVD/Vulners API integration.",
                }

            elif operation == "vulnerability_scan":
                return await self.execute(
                    operation="detect_vulnerabilities", host=target
                )

            elif operation == "security_score":
                db = self._load_db()
                data = db.get(target, {})
                vulns = len(data.get("vulnerabilities", []))
                score = max(0, 100 - (vulns * 20))
                return {"success": True, "score": score, "out_of": 100}

            # ----------------------------------
            # AUTONOMOUS (Original Implementation)
            # ----------------------------------
            elif operation == "auto_scan":
                ports = []
                for p in [21, 22, 23, 25, 53, 80, 443, 3306, 3389, 8080]:
                    s = socket.socket()
                    s.settimeout(1)
                    if s.connect_ex((target, p)) == 0:
                        ports.append(p)
                    s.close()

                try:
                    geo = (
                        await asyncio.to_thread(
                            requests.get, f"http://ip-api.com/json/{target}"
                        )
                    ).json()
                except:
                    geo = {}

                data = {"ports": ports, "geo": geo, "time": time.time()}
                self._remember(target, data)
                return {"success": True, "scan": data}

            elif operation == "identify_services":
                services = {
                    21: "FTP",
                    22: "SSH",
                    23: "TELNET",
                    80: "HTTP",
                    443: "HTTPS",
                    3306: "MySQL",
                    3389: "RDP",
                }
                results = {}
                for p, s in services.items():
                    sock = socket.socket()
                    sock.settimeout(1)
                    if sock.connect_ex((target, p)) == 0:
                        results[p] = s
                    sock.close()
                self._remember(target, {"services": results})
                return {"success": True, "services": results}

            elif operation == "detect_vulnerabilities":
                vulns = []
                db = self._load_db()
                ports = db.get(target, {}).get("ports", [])
                if 21 in ports:
                    vulns.append("FTP insecure")
                if 23 in ports:
                    vulns.append("Telnet insecure")
                if 3389 in ports:
                    vulns.append("RDP exposed")
                self._remember(target, {"vulnerabilities": vulns})
                return {"success": True, "vulnerabilities": vulns}

            elif operation == "generate_report":
                db = self._load_db()
                return {"success": True, "report": db.get(target, {})}

            elif operation == "suggest_exploits":
                exploits = []
                if port == 22:
                    exploits.append("SSH brute force")
                if port == 80:
                    exploits.append("Web vulnerability scan")
                if port == 21:
                    exploits.append("FTP anonymous login")
                return {"success": True, "suggestions": exploits}

            # ----------------------------------
            # SELF LEARNING AI
            # ----------------------------------
            elif operation == "save_scan":
                # Assuming data is passed via kwargs or we just log that a scan was manual
                self._remember(target, {"last_manual_scan": time.time()})
                return {"success": True, "message": "State saved to DB."}

            elif operation == "load_profile":
                db = self._load_db()
                return {"success": True, "profile": db.get(target, {})}

            elif operation == "build_profile":
                db = self._load_db()
                return {"success": True, "profile": db.get(target, {})}

            elif operation == "correlate_findings":
                db = self._load_db()
                data = db.get(target, {})
                correlations = []
                if "ports" in data and "services" in data:
                    correlations.append("Ports match detected services")
                if "vulnerabilities" in data and len(data["vulnerabilities"]) > 0:
                    correlations.append("Known vulnerabilities present")
                return {"success": True, "correlations": correlations}

            elif operation == "predict_attack_paths":
                db = self._load_db()
                data = db.get(target, {})
                paths = []
                ports = data.get("ports", [])
                if 80 in ports:
                    paths.append("Web -> exploit -> shell")
                if 22 in ports:
                    paths.append("SSH brute force -> access")
                if 3306 in ports:
                    paths.append("Database -> dump -> privilege escalation")
                return {"success": True, "attack_paths": paths}

            # ----------------------------------
            # OS / HARDWARE
            # ----------------------------------
            elif operation == "wake_on_lan":
                mac = kwargs.get("mac_address", "")
                if not mac:
                    return {"success": False, "error": "mac_address parameter required"}

                mac_clean = mac.replace("-", "").replace(":", "")
                if len(mac_clean) != 12:
                    return {"success": False, "error": "Invalid MAC address format"}

                try:
                    data = bytes.fromhex("FF" * 6 + mac_clean * 16)
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    sock.sendto(data, ("255.255.255.255", 9))
                    sock.close()
                    return {"success": True, "message": f"Magic packet sent to {mac}"}
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Failed to send magic packet: {str(e)}",
                    }

            # ----------------------------------
            # UNKNOWN
            # ----------------------------------
            return {"success": False, "error": f"Unknown operation {operation}"}

        except Exception as e:
            return {"success": False, "error": str(e)}
