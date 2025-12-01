import unittest
from unittest.mock import MagicMock, patch, mock_open
import sys
import os

# Mock ctypes for Windows admin check
sys.modules['ctypes'] = MagicMock()
sys.modules['ctypes'].windll.shell32.IsUserAnAdmin.return_value = 1

# We need to handle os.geteuid for Linux admin check if running on Linux
if not hasattr(os, 'geteuid'):
    os.geteuid = MagicMock(return_value=0)
else:
    # If we are on Linux, we might not be root, so we mock it
    # But we can't easily patch os.geteuid globally if it's a builtin function in some envs
    # So we patch it in the test setup or use a wrapper in the class.
    # For now, let's assume the class uses os.geteuid directly.
    pass

from wifi_scanner import NetworkScanner

class TestNetworkScanner(unittest.TestCase):

    @patch('wifi_scanner.os.geteuid', return_value=0)
    @patch('wifi_scanner.os.path.exists')
    @patch('wifi_scanner.requests.get')
    @patch('builtins.open', new_callable=mock_open, read_data="00-50-56   (hex)\tVMware, Inc.\n")
    def test_init_and_load_oui(self, mock_file, mock_get, mock_exists, mock_euid):
        # Case 1: File exists
        mock_exists.return_value = True
        scanner = NetworkScanner()
        self.assertEqual(scanner.vendors.get("00:50:56"), "VMware, Inc.")
        
        # Case 2: File missing, download it
        mock_exists.side_effect = [False, True] 
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"00-50-56   (hex)\tVMware, Inc.\n"
        
        scanner = NetworkScanner()
        mock_get.assert_called()

    @patch('wifi_scanner.os.geteuid', return_value=0)
    @patch('wifi_scanner.socket.socket')
    @patch('wifi_scanner.uuid.getnode')
    def test_self_detection(self, mock_getnode, mock_socket, mock_euid):
        mock_sock_instance = MagicMock()
        mock_socket.return_value = mock_sock_instance
        mock_sock_instance.getsockname.return_value = ["192.168.1.105", 0]
        
        # Mock MAC: 00:11:22:33:44:55 -> 73596138045
        mock_getnode.return_value = 0x001122334455
        
        scanner = NetworkScanner()
        self.assertEqual(scanner.my_ip, "192.168.1.105")
        self.assertEqual(scanner.my_mac, "00:11:22:33:44:55")
        self.assertEqual(scanner._get_vendor("00:11:22:33:44:55"), "THIS COMPUTER")

    @patch('wifi_scanner.os.geteuid', return_value=0)
    @patch('wifi_scanner.srp')
    def test_arp_scan(self, mock_srp, mock_euid):
        scanner = NetworkScanner()
        
        mock_sent = MagicMock()
        mock_recv = MagicMock()
        mock_recv.psrc = "192.168.1.1"
        mock_recv.hwsrc = "00:50:56:C0:00:01"
        
        mock_srp.return_value = ([(mock_sent, mock_recv)], [])
        scanner.vendors = {"00:50:56": "VMware"}
        
        results = scanner._arp_scan("192.168.1.0/24")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['vendor'], "VMware")

    @patch('wifi_scanner.os.geteuid', return_value=0)
    @patch('wifi_scanner.subprocess.check_output')
    def test_system_arp_windows(self, mock_check_output, mock_euid):
        # Mock Windows environment
        with patch('wifi_scanner.os.name', 'nt'):
            scanner = NetworkScanner()
            
            mock_output = b"""
Interface: 192.168.1.105 --- 0x10
  Internet Address      Physical Address      Type
  192.168.1.50          00-11-22-33-44-55     dynamic
"""
            mock_check_output.return_value = mock_output
            
            mac = scanner._get_mac_from_system("192.168.1.50")
            self.assertEqual(mac, "00:11:22:33:44:55")

    @patch('wifi_scanner.os.geteuid', return_value=0)
    def test_system_arp_linux(self, mock_euid):
        # Mock Linux environment
        with patch('wifi_scanner.os.name', 'posix'):
            scanner = NetworkScanner()
            
            mock_proc_arp = """IP address       HW type     Flags       HW address            Mask     Device
192.168.1.50     0x1         0x2         00:11:22:33:44:55     *        eth0
192.168.1.1      0x1         0x2         aa:bb:cc:dd:ee:ff     *        eth0
"""
            with patch('builtins.open', mock_open(read_data=mock_proc_arp)):
                mac = scanner._get_mac_from_system("192.168.1.50")
                self.assertEqual(mac, "00:11:22:33:44:55")

    @patch('wifi_scanner.os.geteuid', return_value=0)
    @patch('wifi_scanner.NetworkScanner._get_mac_from_system')
    @patch('wifi_scanner.NetworkScanner._arp_scan')
    @patch('wifi_scanner.NetworkScanner._ping_sweep')
    def test_scan_integration(self, mock_ping, mock_arp, mock_system_arp, mock_euid):
        scanner = NetworkScanner()
        scanner.my_ip = "192.168.1.105"
        scanner.my_mac = "00:11:22:33:44:55"
        
        # ARP finds .1
        mock_arp.return_value = [{"ip": "192.168.1.1", "mac": "AA:BB:CC:DD:EE:FF", "vendor": "Router"}]
        
        # Ping finds .1, .50 (other), .105 (me)
        mock_ping.return_value = ["192.168.1.1", "192.168.1.50", "192.168.1.105"]
        
        # System ARP finds .50
        mock_system_arp.side_effect = lambda ip: "00:99:88:77:66:55" if ip == "192.168.1.50" else None
        
        results = scanner.scan()
        
        self.assertEqual(len(results), 3)
        
        # Check .50 (System ARP)
        dev_50 = next(d for d in results if d['ip'] == "192.168.1.50")
        self.assertEqual(dev_50['mac'], "00:99:88:77:66:55")
        
        # Check .105 (Me)
        dev_me = next(d for d in results if d['ip'] == "192.168.1.105")
        self.assertEqual(dev_me['mac'], "00:11:22:33:44:55")
        self.assertEqual(dev_me['vendor'], "THIS COMPUTER")

if __name__ == '__main__':
    unittest.main()
