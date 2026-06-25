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
from typing import Any, Dict

import psutil
import requests

# Assuming you have these base classes in your project
from app.tools.base import BaseTool, ToolParameter, ToolSchema


class NetworkTool(BaseTool):
    DB_FILE = "network_memory.json"
    SHODAN_KEY = ""  # Add your key if you implement Shodan for reputation/CVEs

    # ── SSRF Protection ─────────────────────────────────────────────

    @staticmethod
    def _is_private_target(target: str) -> bool:
        """Check if a hostname/IP resolves to a private or loopback address.

        Blocks SSRF to internal networks: 127.x, 10.x, 172.16-31.x, 192.168.x,
        169.254.x (link-local), and cloud metadata IPs.
        """
        # Strip port and protocol
        host = target.split("/")[0].split(":")[0].strip().lower()

        # Block obvious internal hostnames
        if host in {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}:
            return True

        if host.startswith("169.254.") or host == "169.254.169.254":
            return True

        try:
            addr = ipaddress.ip_address(host)
            return addr.is_private or addr.is_loopback or addr.is_link_local
        except ValueError:
            pass

        # Resolve hostname and check all addresses
        try:
            addrs = socket.getaddrinfo(host, None)
            for family, _, _, _, sockaddr in addrs:
                try:
                    ip = ipaddress.ip_address(sockaddr[0])
                    if ip.is_private or ip.is_loopback or ip.is_link_local:
                        return True
                except ValueError:
                    continue
        except (socket.gaierror, OSError):
            pass

        return False

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
                except Exception:
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
                abuse_key = os.environ.get("ABUSEIPDB_API_KEY", "")
                if not abuse_key:
                    return await self.execute(operation="threat_summary", host=target)
                try:
                    resp = await asyncio.to_thread(
                        requests.get,
                        "https://api.abuseipdb.com/api/v2/check",
                        params={"ipAddress": target, "maxAgeInDays": 90},
                        headers={"Key": abuse_key, "Accept": "application/json"},
                        timeout=10,
                    )
                    data = resp.json().get("data", {})
                    return {
                        "success": True,
                        "ip": data.get("ipAddress", target),
                        "abuse_score": data.get("abuseConfidenceScore", 0),
                        "total_reports": data.get("totalReports", 0),
                        "last_reported": data.get("lastReportedAt"),
                        "country": data.get("countryCode"),
                        "domain": data.get("domain"),
                        "is_public": data.get("isPublic", True),
                        "is_whitelisted": data.get("isWhitelisted", False),
                        "categories": data.get("categories", []),
                    }
                except Exception as exc:
                    return {"success": False, "error": f"AbuseIPDB check failed: {exc}"}

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
                if self._is_private_target(host):
                    return {"success": False, "error": "Cannot query internal addresses"}
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
                if self._is_private_target(target):
                    return {"success": False, "error": "Cannot query internal addresses"}
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
                if self._is_private_target(target):
                    return {"success": False, "error": "Cannot probe internal/private addresses"}
                param = "-n" if platform.system().lower() == "windows" else "-c"
                result = subprocess.run(
                    ["ping", param, "4", target], capture_output=True
                )
                return {"success": True, "output": result.stdout.decode()}

            elif operation == "latency":
                if not target:
                    return {"success": False, "error": "host or ip parameter required"}
                if self._is_private_target(target):
                    return {"success": False, "error": "Cannot probe internal/private addresses"}
                start = time.time()
                try:
                    await asyncio.to_thread(requests.get, f"http://{target}", timeout=3)
                    latency = (time.time() - start) * 1000
                    return {"success": True, "latency_ms": round(latency, 2)}
                except Exception:
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
                if not target:
                    return {"success": False, "error": "host or ip parameter required"}
                if self._is_private_target(target):
                    return {"success": False, "error": "Cannot scan internal/private addresses"}
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
                if not target:
                    return {"success": False, "error": "host or ip parameter required"}
                if self._is_private_target(target):
                    return {"success": False, "error": "Cannot scan internal/private addresses"}
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
                if self._is_private_target(target):
                    return {"success": False, "error": "Cannot scan internal/private addresses"}
                result = subprocess.run(["nmap", "-sV", target], capture_output=True)
                return {"success": True, "nmap_output": result.stdout.decode()}

            elif operation == "os_fingerprint":
                if not target:
                    return {"success": False, "error": "host or ip parameter required"}
                if self._is_private_target(target):
                    return {"success": False, "error": "Cannot fingerprint internal/private addresses"}
                result = subprocess.run(["nmap", "-O", target], capture_output=True)
                return {"success": True, "os_output": result.stdout.decode()}

            elif operation == "subnet_scan":
                if not subnet:
                    return {"success": False, "error": "subnet parameter required (CIDR notation, e.g. 192.168.1.0/24)"}
                try:
                    network = ipaddress.ip_network(subnet, strict=False)
                except ValueError as exc:
                    return {"success": False, "error": f"Invalid subnet: {exc}"}
                ping_param = "-n" if platform.system().lower() == "windows" else "-c"
                hosts = []
                for ip_addr in network.hosts():
                    ip_str = str(ip_addr)
                    result = subprocess.run(
                        ["ping", ping_param, "1", "-W", "1", ip_str],
                        capture_output=True, timeout=3,
                    )
                    if result.returncode == 0:
                        hosts.append(ip_str)
                    if len(hosts) >= 50:
                        break
                return {
                    "success": True,
                    "subnet": subnet,
                    "hosts_found": len(hosts),
                    "hosts": hosts,
                }

            # ----------------------------------
            # WEB
            # ----------------------------------
            elif operation == "http_headers":
                if self._is_private_target(target):
                    return {"success": False, "error": "Cannot probe internal/private addresses"}
                try:
                    resp = await asyncio.to_thread(
                        requests.head, f"http://{target}", timeout=3
                    )
                    return {"success": True, "headers": dict(resp.headers)}
                except Exception:
                    return {"success": False, "error": "HTTP connection failed."}

            elif operation == "http_security":
                if self._is_private_target(target):
                    return {"success": False, "error": "Cannot probe internal/private addresses"}
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
                except Exception:
                    return {"success": False, "error": "HTTPS connection failed."}

            elif operation == "technology_detect":
                if self._is_private_target(target):
                    return {"success": False, "error": "Cannot probe internal/private addresses"}
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
                except Exception:
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
                try:
                    if platform.system().lower() == "windows":
                        result = subprocess.run(
                            ["route", "print", "0.0.0.0"],
                            capture_output=True, text=True, timeout=5,
                        )
                        for line in result.stdout.splitlines():
                            if "0.0.0.0" in line and "On-link" not in line:
                                parts = line.split()
                                if len(parts) >= 3:
                                    return {"success": True, "gateway": parts[2], "interface": parts[-1] if len(parts) > 3 else "unknown"}
                    else:
                        result = subprocess.run(
                            ["ip", "route", "show", "default"],
                            capture_output=True, text=True, timeout=5,
                        )
                        for line in result.stdout.splitlines():
                            parts = line.split()
                            if len(parts) >= 3 and parts[0] == "default":
                                gw = parts[2]
                                dev = parts[3] if len(parts) > 3 else "unknown"
                                return {"success": True, "gateway": gw, "interface": dev}
                    return {"success": True, "gateway": None, "message": "No default gateway found"}
                except Exception as exc:
                    return {"success": False, "error": f"Gateway detection failed: {exc}"}

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
                if not target:
                    return {"success": False, "error": "host or ip parameter required"}
                try:
                    ip_to_check = target
                    try:
                        ip_to_check = socket.gethostbyname(target)
                    except socket.gaierror:
                        pass
                    resp = await asyncio.to_thread(
                        requests.get,
                        "https://check.torproject.org/torbulkexitlist",
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        exit_nodes = set(resp.text.strip().splitlines())
                        is_tor = ip_to_check in exit_nodes
                        return {
                            "success": True,
                            "is_tor": is_tor,
                            "ip": ip_to_check,
                            "message": f"IP {'is' if is_tor else 'is not'} a known Tor exit node" if is_tor else "IP is not a known Tor exit node",
                        }
                    return {
                        "success": True,
                        "is_tor": False,
                        "message": "Could not fetch Tor exit list (check.torproject.org unreachable)",
                    }
                except Exception as exc:
                    return {"success": False, "error": f"Tor detection failed: {exc}"}

            elif operation == "vpn_detect":
                if not target:
                    return {"success": False, "error": "host or ip parameter required"}
                try:
                    ip_to_check = target
                    try:
                        ip_to_check = socket.gethostbyname(target)
                    except socket.gaierror:
                        pass
                    resp = await asyncio.to_thread(
                        requests.get,
                        f"https://ipapi.co/{ip_to_check}/json/",
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        org = data.get("org", "")
                        is_vpn = False
                        vpn_indicators = []
                        vpn_keywords = ["vpn", "datacenter", "hosting", "cloud", "server", "proxy"]
                        org_lower = org.lower()
                        for kw in vpn_keywords:
                            if kw in org_lower:
                                vpn_indicators.append(kw)
                                is_vpn = True
                        return {
                            "success": True,
                            "ip": ip_to_check,
                            "is_vpn": is_vpn,
                            "confidence": "high" if len(vpn_indicators) >= 2 else "medium" if vpn_indicators else "low",
                            "indicators": vpn_indicators,
                            "org": org,
                            "country": data.get("country_name"),
                            "city": data.get("city"),
                            "hosting": data.get("org", ""),
                            "asn": data.get("asn"),
                        }
                    fallback_data = (
                        await asyncio.to_thread(
                            requests.get, f"http://ip-api.com/json/{ip_to_check}?fields=status,query,org,as,proxy,hosting",
                            timeout=5,
                        )
                    ).json()
                    return {
                        "success": True,
                        "ip": ip_to_check,
                        "is_vpn": fallback_data.get("proxy", False),
                        "is_hosting": fallback_data.get("hosting", False),
                        "org": fallback_data.get("org", ""),
                        "asn": fallback_data.get("as", ""),
                    }
                except Exception as exc:
                    return {"success": False, "error": f"VPN detection failed: {exc}"}

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
                if not target:
                    return {"success": False, "error": "host, ip, or software name required"}
                try:
                    params: dict = {"resultsPerPage": 20, "startIndex": 0}
                    if ipaddress.ip_address(target).version == 4:
                        params["keywordSearch"] = target
                    else:
                        params["keywordSearch"] = target
                except ValueError:
                    params["keywordSearch"] = target
                try:
                    resp = await asyncio.to_thread(
                        requests.get,
                        "https://services.nvd.nist.gov/rest/json/cves/2.0",
                        params=params,
                        timeout=15,
                    )
                    if resp.status_code != 200:
                        return {"success": False, "error": f"NVD API returned {resp.status_code}"}
                    data = resp.json()
                    vulns = data.get("vulnerabilities", [])
                    cves = []
                    for v in vulns[:15]:
                        cve = v.get("cve", {})
                        cve_id = cve.get("id", "unknown")
                        desc = ""
                        for d in cve.get("descriptions", []):
                            if d.get("lang") == "en":
                                desc = d.get("value", "")
                                break
                        metrics = cve.get("metrics", {})
                        cvss_score = None
                        for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
                            if key in metrics and metrics[key]:
                                cvss_score = metrics[key][0].get("cvssData", {}).get("baseScore")
                                break
                        cves.append({
                            "id": cve_id,
                            "description": desc[:200],
                            "cvss_score": cvss_score,
                            "published": cve.get("published"),
                            "last_modified": cve.get("lastModified"),
                        })
                    return {
                        "success": True,
                        "total_results": data.get("totalResults", 0),
                        "cves": cves,
                    }
                except Exception as exc:
                    return {"success": False, "error": f"CVE lookup failed: {exc}"}

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
                except Exception:
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
