import unittest
from unittest.mock import MagicMock, patch, mock_open
import sys
import os

# Mock ctypes before importing wifi_scanner because it's used at top level or in __init__
sys.modules['ctypes'] = MagicMock()
sys.modules['ctypes'].windll.shell32.IsUserAnAdmin.return_value = 1

from wifi_scanner import WindowsNetworkScanner

class TestWindowsNetworkScanner(unittest.TestCase):

    @patch('wifi_scanner.os.path.exists')
    @patch('wifi_scanner.requests.get')
    @patch('builtins.open', new_callable=mock_open, read_data="00-50-56   (hex)\tVMware, Inc.\n")
    def test_init_and_load_oui(self, mock_file, mock_get, mock_exists):
        # Case 1: File exists
        mock_exists.return_value = True
        scanner = WindowsNetworkScanner()
        self.assertEqual(scanner.vendors.get("00:50:56"), "VMware, Inc.")
        
        # Case 2: File missing, download it
        # Mock first URL failing (418), second succeeding (200)
        mock_exists.side_effect = [False, True] 
        
        # Mock responses
        mock_response_fail = MagicMock()
        mock_response_fail.status_code = 418
        
        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.content = b"00-50-56   (hex)\tVMware, Inc.\n"
        
        mock_get.side_effect = [mock_response_fail, mock_response_success]
        
        scanner = WindowsNetworkScanner()
        
        # Should have called get twice
        self.assertEqual(mock_get.call_count, 2)
        # Check if headers were used (just check one call)
        args, kwargs = mock_get.call_args_list[0]
        self.assertIn('User-Agent', kwargs['headers'])

    @patch('wifi_scanner.socket.socket')
    def test_get_local_ip_range(self, mock_socket):
        mock_sock_instance = MagicMock()
        mock_socket.return_value = mock_sock_instance
        mock_sock_instance.getsockname.return_value = ["192.168.1.105", 0]
        
        scanner = WindowsNetworkScanner()
        ip_range = scanner._get_local_ip_range()
        self.assertEqual(ip_range, "192.168.1.0/24")

    @patch('wifi_scanner.srp')
    def test_arp_scan(self, mock_srp):
        scanner = WindowsNetworkScanner()
        
        # Mock ARP response
        # srp returns (answered, unanswered)
        # answered is a list of (sent, received) packets
        mock_sent_packet = MagicMock()
        mock_received_packet = MagicMock()
        mock_received_packet.psrc = "192.168.1.1"
        mock_received_packet.hwsrc = "00:50:56:C0:00:01"
        
        mock_srp.return_value = ([(mock_sent_packet, mock_received_packet)], [])
        
        # Pre-populate vendors for lookup test
        scanner.vendors = {"00:50:56": "VMware"}
        
        results = scanner._arp_scan("192.168.1.0/24")
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['ip'], "192.168.1.1")
        self.assertEqual(results[0]['vendor'], "VMware")

    @patch('wifi_scanner.subprocess.run')
    def test_ping_host(self, mock_subprocess):
        scanner = WindowsNetworkScanner()
        
        # Mock successful ping
        mock_subprocess.return_value.returncode = 0
        result = scanner._ping_host("192.168.1.5")
        self.assertEqual(result, "192.168.1.5")
        
        # Mock failed ping
        mock_subprocess.return_value.returncode = 1
        result = scanner._ping_host("192.168.1.99")
        self.assertIsNone(result)

    @patch('wifi_scanner.WindowsNetworkScanner._ping_host')
    def test_ping_sweep(self, mock_ping_host):
        scanner = WindowsNetworkScanner()
        
        # Mock ping results for a small range to speed up test if it actually ran loop
        # But _ping_sweep generates 254 IPs. We can check if it calls _ping_host.
        
        # We'll mock map to return a specific list to avoid waiting for 254 calls
        # However, ThreadPoolExecutor.map is hard to mock directly on the instance.
        # Easier to let it run and mock _ping_host to be fast.
        
        mock_ping_host.side_effect = lambda ip: ip if ip == "192.168.1.50" else None
        
        results = scanner._ping_sweep("192.168.1.0/24")
        self.assertIn("192.168.1.50", results)
        self.assertEqual(len(results), 1)

    @patch('wifi_scanner.WindowsNetworkScanner._get_mac_from_system_arp')
    @patch('wifi_scanner.WindowsNetworkScanner._arp_scan')
    @patch('wifi_scanner.WindowsNetworkScanner._ping_sweep')
    @patch('wifi_scanner.WindowsNetworkScanner._get_local_ip_range')
    def test_scan_integration(self, mock_get_ip, mock_ping, mock_arp, mock_system_arp):
        scanner = WindowsNetworkScanner()
        mock_get_ip.return_value = "192.168.1.0/24"
        
        # ARP finds .1
        mock_arp.return_value = [{"ip": "192.168.1.1", "mac": "AA:BB:CC:DD:EE:FF", "vendor": "TestVendor"}]
        
        # Ping finds .1 and .50 (so .50 is new)
        mock_ping.return_value = ["192.168.1.1", "192.168.1.50"]
        
        # Mock system ARP for .50
        mock_system_arp.side_effect = lambda ip: "00:11:22:33:44:55" if ip == "192.168.1.50" else None
        
        # Pre-populate vendor for system ARP found mac
        scanner.vendors["00:11:22"] = "SystemArpVendor"
        
        results = scanner.scan()
        
        # Should have 2 devices
        self.assertEqual(len(results), 2)
        
        # Check .1 details
        dev1 = next(d for d in results if d['ip'] == "192.168.1.1")
        self.assertEqual(dev1['mac'], "AA:BB:CC:DD:EE:FF")
        
        # Check .50 details (should be resolved via system ARP)
        dev2 = next(d for d in results if d['ip'] == "192.168.1.50")
        self.assertEqual(dev2['mac'], "00:11:22:33:44:55")
        self.assertEqual(dev2['vendor'], "SystemArpVendor")

    @patch('wifi_scanner.subprocess.check_output')
    def test_get_mac_from_system_arp(self, mock_check_output):
        scanner = WindowsNetworkScanner()
        
        # Mock arp -a output
        mock_output = b"""
Interface: 192.168.1.105 --- 0x10
  Internet Address      Physical Address      Type
  192.168.1.50          00-11-22-33-44-55     dynamic
  192.168.1.254         ff-ff-ff-ff-ff-ff     static
"""
        mock_check_output.return_value = mock_output
        
        mac = scanner._get_mac_from_system_arp("192.168.1.50")
        self.assertEqual(mac, "00:11:22:33:44:55")
        
        mac_not_found = scanner._get_mac_from_system_arp("192.168.1.99")
        self.assertIsNone(mac_not_found)

if __name__ == '__main__':
    unittest.main()
