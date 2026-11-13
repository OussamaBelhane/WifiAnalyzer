import warnings
warnings.filterwarnings("ignore")

import sys
import os
import time
import socket
import struct
import threading
import subprocess
import requests
import concurrent.futures
import uuid
import re
from scapy.all import ARP, Ether, srp, conf, get_if_hwaddr
conf.verb = 0

# Try to import ctypes for Windows admin check
try:
    import ctypes
except ImportError:
    ctypes = None

class NetworkScanner:
    def __init__(self, oui_file=None):
        if oui_file is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.oui_file = os.path.join(base_dir, "oui.txt")
        else:
            self.oui_file = oui_file
        self.vendors = {}
        self.my_ip = None
        self.my_mac = None
        self.interface = None
        self.has_admin = False
        
        self._check_admin()
        self._detect_self()
        self._load_oui()

    def _check_admin(self):
        """
        Verifies if the script is running with necessary privileges.
        Windows: Administrator
        Linux: Root (uid 0)
        """
        is_admin = False
        if os.name == 'nt':
            try:
                is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception:
                pass
        else:
            try:
                is_admin = os.geteuid() == 0
            except AttributeError:
                pass

        self.has_admin = is_admin
        if not is_admin:
            print("[!] Warning: Root/Administrator privileges not detected. Network raw packet operations may be restricted.")

    def _detect_self(self):
        """
        Detects own active network interface, IP, and real hardware MAC address.
        """
        try:
            # 1. Attempt Scapy route lookup to find the active interface and IP
            try:
                route_info = conf.route.route("0.0.0.0")
                if route_info and len(route_info) >= 3:
                    self.interface = route_info[0]
                    self.my_ip = route_info[1]
            except Exception:
                pass

            # 2. Fallback IP detection via UDP socket
            if not self.my_ip:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                self.my_ip = s.getsockname()[0]
                s.close()

            # 3. Detect real hardware MAC for the active interface
            if self.interface:
                try:
                    hw = get_if_hwaddr(self.interface)
                    if hw and hw != "00:00:00:00:00:00":
                        self.my_mac = hw.upper()
                except Exception:
                    pass

            # On Linux, fallback to /sys/class/net/{interface}/address
            if not self.my_mac and self.interface and os.name != 'nt':
                try:
                    sys_mac_path = f"/sys/class/net/{self.interface}/address"
                    if os.path.exists(sys_mac_path):
                        with open(sys_mac_path, "r") as f:
                            mac_str = f.read().strip()
                            if mac_str:
                                self.my_mac = mac_str.upper()
                except Exception:
                    pass

            # 4. Final fallback to uuid.getnode()
            if not self.my_mac:
                mac_int = uuid.getnode()
                mac_hex = "{:012x}".format(mac_int)
                self.my_mac = ":".join(mac_hex[i:i+2] for i in range(0, 12, 2)).upper()

            iface_str = f" [{self.interface}]" if self.interface else ""
            print(f"[*] Self Detected: {self.my_ip} ({self.my_mac}){iface_str}")
        except Exception as e:
            print(f"[-] Error detecting self: {e}")

    def _load_oui(self):
        """
        Loads OUI data from local file or downloads it if missing.
        """
        if not os.path.exists(self.oui_file):
            print("[*] OUI file not found. Downloading...")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            urls = [
                "https://linuxnet.ca/ieee/oui.txt",
                "http://standards-oui.ieee.org/oui/oui.txt"
            ]
            
            downloaded = False
            for url in urls:
                try:
                    print(f"[*] Trying to download from {url}...")
                    response = requests.get(url, headers=headers, timeout=15)
                    if response.status_code == 200:
                        with open(self.oui_file, "wb") as f:
                            f.write(response.content)
                        print("[+] Download complete.")
                        downloaded = True
                        break
                    else:
                        print(f"[-] Failed to download from {url}. Status: {response.status_code}")
                except Exception as e:
                    print(f"[-] Error downloading from {url}: {e}")
            
            if not downloaded:
                print("[-] Could not download OUI file. Vendor lookup will be limited.")

        if os.path.exists(self.oui_file):
            print("[*] Parsing OUI file...")
            try:
                with open(self.oui_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if "(hex)" in line:
                            parts = line.split("(hex)")
                            mac_prefix = parts[0].strip().replace("-", ":")
                            vendor = parts[1].strip()
                            self.vendors[mac_prefix] = vendor
                print(f"[+] Loaded {len(self.vendors)} vendor entries.")
            except Exception as e:
                print(f"[-] Error parsing OUI file: {e}")

    def _get_vendor(self, mac):
        """
        Looks up vendor by MAC address.
        """
        if not mac or mac == "Unknown":
            return "Unknown"
        
        # Check if it's me
        if self.my_mac and mac.upper() == self.my_mac.upper():
            return "THIS COMPUTER"
            
        prefix = mac[:8].upper()
        return self.vendors.get(prefix, "Unknown")

    def _get_local_ip_range(self):
        """
        Auto-detects the local IP range (e.g., 192.168.1.0/24).
        """
        if self.my_ip:
            ip_parts = self.my_ip.split(".")
            base_ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0/24"
            return base_ip
        return "192.168.1.0/24"

    def _arp_scan(self, target_ip_range):
        """
        Step 1: Send ARP requests to the local subnet using Scapy.
        """
        print(f"[*] Starting ARP scan on {target_ip_range}...")
        devices = []
        try:
            # Create ARP request packet
            arp = ARP(pdst=target_ip_range)
            ether = Ether(dst="ff:ff:ff:ff:ff:ff")
            packet = ether/arp

            # Send packet and wait for response
            result = srp(packet, timeout=3, verbose=0)[0]

            for sent, received in result:
                devices.append({
                    "ip": received.psrc,
                    "mac": received.hwsrc.upper(),
                    "vendor": self._get_vendor(received.hwsrc)
                })
        except Exception as e:
            print(f"[-] ARP scan failed: {e}")
        
        return devices

    def _ping_host(self, ip):
        """
        Pings a single host.
        """
        try:
            kwargs = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL
            }
            if os.name == 'nt':
                command = ["ping", "-n", "1", "-w", "200", ip]
                kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
            else:
                command = ["ping", "-c", "1", "-W", "1", ip]
            
            result = subprocess.run(command, **kwargs)
            if result.returncode == 0:
                return ip
        except Exception:
            pass
        return None

    def _ping_sweep(self, target_ip_range):
        """
        Step 2: Run a multi-threaded ICMP Ping Sweep.
        """
        print("[*] Starting Ping Sweep...")
        active_ips = []
        
        try:
            base_ip = target_ip_range.split("/")[0]
            subnet_parts = base_ip.split(".")
            prefix = f"{subnet_parts[0]}.{subnet_parts[1]}.{subnet_parts[2]}"
            
            # Generate IPs .1 to .254
            ips_to_scan = [f"{prefix}.{i}" for i in range(1, 255)]
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
                results = executor.map(self._ping_host, ips_to_scan)
                
            for ip in results:
                if ip:
                    active_ips.append(ip)
                    
        except Exception as e:
            print(f"[-] Ping sweep failed: {e}")
            
        return active_ips

    def _get_mac_from_system(self, ip):
        """
        Step 2 (Fallback): Get MAC from system ARP cache.
        """
        try:
            if os.name == 'nt':
                # Windows: Parse arp -a <ip>
                command = ["arp", "-a", ip]
                creation_flags = 0x08000000
                output = subprocess.check_output(
                    command, 
                    creationflags=creation_flags,
                    stderr=subprocess.DEVNULL
                ).decode("utf-8", errors="ignore")
                
                for line in output.splitlines():
                    if ip in line:
                        # Look for MAC
                        parts = line.split()
                        for part in parts:
                            if "-" in part and len(part) == 17:
                                return part.replace("-", ":").upper()
            else:
                # Linux: Read /proc/net/arp
                with open("/proc/net/arp", "r") as f:
                    # Skip header
                    next(f) 
                    for line in f:
                        parts = line.split()
                        # Format: IP address       HW type     Flags       HW address            Mask     Device
                        #         192.168.1.1      0x1         0x2         00:50:56:c0:00:08     *        ens33
                        if len(parts) >= 4 and parts[0] == ip:
                            mac = parts[3]
                            if mac != "00:00:00:00:00:00":
                                return mac.upper()
                                
        except Exception:
            pass
        return None

    def scan(self):
        """
        Main scanning method.
        """
        target_ip_range = self._get_local_ip_range()
        print(f"[*] Target Range: {target_ip_range}")
        
        # Step 1: ARP Scan (Scapy)
        arp_devices = self._arp_scan(target_ip_range)
        arp_ips = {d["ip"] for d in arp_devices}
        
        # Step 2: Ping Sweep
        ping_ips = self._ping_sweep(target_ip_range)
        
        final_results = arp_devices
        
        for ip in ping_ips:
            if ip not in arp_ips:
                # Device found via Ping but blocked Scapy ARP
                # Step 3: System ARP Fallback
                mac = self._get_mac_from_system(ip)
                
                # If still unknown, check if it's me (Ping sweep finds me)
                if not mac and ip == self.my_ip:
                    mac = self.my_mac
                
                vendor = "Unknown (ICMP Response)"
                if mac:
                    vendor = self._get_vendor(mac)
                else:
                    mac = "Unknown"
                
                final_results.append({
                    "ip": ip,
                    "mac": mac,
                    "vendor": vendor
                })
                
        return final_results

if __name__ == "__main__":
    scanner = NetworkScanner()
    if not scanner.has_admin:
        print("[-] Error: Running a standalone scan requires Administrator (Windows) or Root (Linux) privileges.")
        print("    Windows: Right-click terminal -> 'Run as Administrator'")
        print("    Linux:   sudo python3 wifi_scanner.py")
        sys.exit(1)
    results = scanner.scan()
    print("\n[+] Scan Results:")
    for device in results:
        print(device)
