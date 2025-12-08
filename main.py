import customtkinter as ctk
import tkinter as tk
from threading import Thread
import time
import random
import math
import json
import os

# WiFi Blocker Integration
try:
    from wifi_blocker import WiFiBlocker
    WIFI_BLOCKER_AVAILABLE = True
except Exception as e:
    print(f"[!] WiFi Blocker not available: {e}")
    WIFI_BLOCKER_AVAILABLE = False

# --- Configuration & Mock Data ---

# Modern Color Palette (Sleek Dark Theme)
COLOR_BG_DEEP_BLACK = "#0a0a0f"       # Deeper, richer black
COLOR_PANEL_DARK_CHARCOAL = "#16161e" # Slightly warmer charcoal
COLOR_ACCENT_RED = "#e63946"          # Modern coral red
COLOR_ACCENT_GREEN = "#06d6a0"        # Vibrant teal-green
COLOR_ACCENT_BLUE = "#4cc9f0"         # Bright cyan blue  
COLOR_ACCENT_PURPLE = "#7b2cbf"       # Rich purple for variety
COLOR_TEXT_LIGHT = "#f8f9fa"          # Softer white
COLOR_TEXT_GRAY = "#adb5bd"           # Warmer gray
COLOR_BUTTON_HOVER = "#2d2d3a"        # Sleek hover
COLOR_CARD_BG = "#1a1a24"             # Subtle card background
COLOR_BORDER_SUBTLE = "#2a2a3a"       # Subtle borders

# Modern Font
FONT_FAMILY = "Segoe UI"  # Clean modern font (fallback to system default)

# Set default appearance mode and color theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue") 

# Mock Data for testing (fallback if Neo4j not available)
# Mock Data (EMPTY - Waiting for Real Scan)
MOCK_DEVICES = []



# --- Backend Integration Classes ---

class DatabaseManager:
    """Database manager using Neo4j for persistent storage."""
    BLOCKED_DEVICES_FILE = "blocked_devices.json"
    DEVICE_STATUSES_FILE = "device_statuses.json"  # For offline persistence
    DEVICE_HISTORY_FILE = "device_history.json"    # For device history with dates
    
    def __init__(self, app_instance):
        self.app = app_instance
        self.neo4j_manager = None
        self.use_neo4j = False
        self.local_cache = [] # In-memory cache for current session
        self.device_statuses = {}  # Separate dict for status persistence: {mac: status}
        self.device_history = {}   # Device history with timestamps: {mac: {vendor, first_seen, last_seen, status}}
        
        # Load persisted device statuses and history from file (works without Neo4j)
        self._load_device_statuses()
        self._load_device_history()
        
        # Try to initialize Neo4j
        try:
            from neo4j_manager import create_neo4j_manager
            self.neo4j_manager = create_neo4j_manager()
            if self.neo4j_manager and self.neo4j_manager.is_available():
                self.use_neo4j = True
                self.app.log("DatabaseManager: Connected to Neo4j database.")
                # Pre-load device statuses from Neo4j into local cache
                self._load_initial_cache()
            else:
                self.app.log("DatabaseManager: Neo4j not available. Using local session cache.")
        except Exception as e:
            self.app.log(f"DatabaseManager: Neo4j initialization failed: {e}")
            self.app.log("DatabaseManager: Falling back to local session cache.")

    def _load_device_statuses(self):
        """Loads device statuses from JSON file for offline persistence."""
        if os.path.exists(self.DEVICE_STATUSES_FILE):
            try:
                with open(self.DEVICE_STATUSES_FILE, 'r') as f:
                    self.device_statuses = json.load(f)
                self.app.log(f"DatabaseManager: Loaded {len(self.device_statuses)} saved device statuses.")
            except Exception as e:
                self.app.log(f"DatabaseManager: Error loading device statuses: {e}")
                self.device_statuses = {}

    def _save_device_statuses(self):
        """Saves device statuses to JSON file for offline persistence."""
        try:
            with open(self.DEVICE_STATUSES_FILE, 'w') as f:
                json.dump(self.device_statuses, f, indent=2)
        except Exception as e:
            self.app.log(f"DatabaseManager: Error saving device statuses: {e}")

    def _load_device_history(self):
        """Loads device history from JSON file."""
        if os.path.exists(self.DEVICE_HISTORY_FILE):
            try:
                with open(self.DEVICE_HISTORY_FILE, 'r') as f:
                    self.device_history = json.load(f)
                self.app.log(f"DatabaseManager: Loaded history for {len(self.device_history)} devices.")
            except Exception as e:
                self.app.log(f"DatabaseManager: Error loading device history: {e}")
                self.device_history = {}

    def _save_device_history(self):
        """Saves device history to JSON file."""
        try:
            with open(self.DEVICE_HISTORY_FILE, 'w') as f:
                json.dump(self.device_history, f, indent=2)
        except Exception as e:
            self.app.log(f"DatabaseManager: Error saving device history: {e}")

    def get_all_history_devices(self):
        """Returns all devices from history as a list."""
        devices = []
        for mac, data in self.device_history.items():
            devices.append({
                'mac': mac,
                'vendor': data.get('vendor', 'Unknown'),
                'status': self.device_statuses.get(mac, data.get('status', 'Unknown')),
                'first_seen': data.get('first_seen', 'N/A'),
                'last_seen': data.get('last_seen', 'N/A')
            })
        return devices

    def get_history_by_date_range(self, start_date, end_date):
        """Returns devices from history filtered by date range."""
        devices = []
        for mac, data in self.device_history.items():
            first_seen = data.get('first_seen', '')
            last_seen = data.get('last_seen', '')
            
            # Check if device was seen within the date range
            # A device is included if it was seen (last_seen) within the range
            # or if it first appeared (first_seen) within the range
            try:
                if last_seen >= start_date and first_seen <= end_date:
                    devices.append({
                        'mac': mac,
                        'vendor': data.get('vendor', 'Unknown'),
                        'status': self.device_statuses.get(mac, data.get('status', 'Unknown')),
                        'first_seen': first_seen,
                        'last_seen': last_seen
                    })
            except:
                # If comparison fails, include the device anyway
                pass
        
        self.app.log(f"History: Found {len(devices)} devices in date range.")
        return devices

    def _load_initial_cache(self):
        """Pre-loads device statuses from Neo4j into the local cache."""
        try:
            devices = self.neo4j_manager.device_manager.get_all_devices()
            if devices:
                for d in devices:
                    self.local_cache.append({
                        'mac': d['mac'],
                        'vendor': d.get('vendor', 'Unknown'),
                        'status': d.get('status', 'Unknown'),
                        'ip': 'Unknown'
                    })
                    # Also sync to device_statuses dict
                    self.device_statuses[d['mac']] = d.get('status', 'Unknown')
                self.app.log(f"DatabaseManager: Pre-loaded {len(devices)} device statuses from DB.")
                self._save_device_statuses()  # Sync to file
        except Exception as e:
            self.app.log(f"DatabaseManager: Error pre-loading cache: {e}")

    def fetch_devices(self):
        """Returns a list of device dictionaries from Neo4j or local cache."""
        self.app.log("DatabaseManager: Fetching known devices list...")
        
        if self.use_neo4j:
            try:
                devices = self.neo4j_manager.device_manager.get_all_devices()
                if devices:
                    # Convert Neo4j format to app format
                    formatted_devices = []
                    for d in devices:
                        # Get appearance count
                        count = self.neo4j_manager.device_manager.get_device_appearance_count(d['mac'])
                        
                        formatted_devices.append({
                            'vendor': d.get('vendor', 'Unknown'),
                            'ip': 'Unknown',  # Will be updated from latest scan
                            'mac': d['mac'],
                            'status': d.get('status', 'Unknown'),
                            'angle': 0,
                            'distance': 0.5,
                            'appearances': count,
                            'first_seen': str(d.get('first_seen', '')),
                            'last_seen': str(d.get('last_seen', ''))
                        })
                    
                    self.app.log(f"DatabaseManager: Found {len(formatted_devices)} devices in Neo4j.")
                    return formatted_devices
                else:
                    self.app.log("DatabaseManager: No devices found in Neo4j.")
                    return []
            except Exception as e:
                self.app.log(f"DatabaseManager: Error fetching from Neo4j: {e}")
                return self.local_cache
        else:
            # Fallback to local cache
            self.app.log(f"DatabaseManager: Found {len(self.local_cache)} devices in local cache.")
            return self.local_cache
    
    def delete_device(self, mac):
        """Deletes a device from Neo4j."""
        if not self.use_neo4j:
             # Remove from local cache
             self.local_cache = [d for d in self.local_cache if d['mac'] != mac]
             return True
             
        try:
             query = "MATCH (d:Device {mac: $mac}) DETACH DELETE d"
             self.neo4j_manager.connection.execute_query(query, {"mac": mac})
             return True
        except Exception as e:
             self.app.log(f"DatabaseManager: Error deleting device: {e}")
             return False

    def save_scan_results(self, devices, duration=0.0):
        """Saves scan results to Neo4j database, local cache, and device history."""
        import time
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Merge logic: Create a map of existing cache to preserve 'status'
        existing_cache_map = {d['mac']: d for d in self.local_cache}
        
        merged_devices = []
        for new_device in devices:
            mac = new_device['mac']
            
            # Update device history with timestamps
            if mac in self.device_history:
                # Existing device - update last_seen
                self.device_history[mac]['last_seen'] = current_time
                self.device_history[mac]['vendor'] = new_device.get('vendor', self.device_history[mac].get('vendor', 'Unknown'))
            else:
                # New device - set first_seen and last_seen
                self.device_history[mac] = {
                    'vendor': new_device.get('vendor', 'Unknown'),
                    'first_seen': current_time,
                    'last_seen': current_time,
                    'status': 'Unknown'
                }
            
            if mac in existing_cache_map:
                # Preserve known status from cache
                cached_status = existing_cache_map[mac].get('status', 'Unknown')
                if cached_status != 'Unknown':
                    new_device['status'] = cached_status
            
            merged_devices.append(new_device)
        
        # Save device history to file
        self._save_device_history()
            
        # Update local cache with the merged list
        self.local_cache = merged_devices
        
        if not self.use_neo4j:
            self.app.log("DatabaseManager: Neo4j not available. Saved to local cache only.")
            return None
        
        try:
            scan_id = self.neo4j_manager.scan_manager.create_scan(devices, duration)
            self.app.log(f"DatabaseManager: Scan saved to Neo4j (ID: {scan_id[:8]}...).")
            return scan_id
        except Exception as e:
            self.app.log(f"DatabaseManager: Error saving scan: {e}")
            return None
    
    def mark_device_as_known(self, mac):
        """Marks a device as 'Known' in the database."""
        # Update local cache regardless
        for d in self.local_cache:
            if d['mac'] == mac:
                d['status'] = 'Known'
        
        # Update device_statuses dict and persist to file
        self.device_statuses[mac] = 'Known'
        self._save_device_statuses()
                
        if not self.use_neo4j:
            self.app.log(f"DatabaseManager: Device {mac} marked as Known (Local Cache).")
            return True
        
        try:
            self.neo4j_manager.device_manager.mark_device_as_known(mac)
            self.app.log(f"DatabaseManager: Device {mac} marked as Known.")
            return True
        except Exception as e:
            self.app.log(f"DatabaseManager: Error marking device: {e}")
            # We still return True if local cache succeeded, to keep UI responsive
            return True

    def mark_device_as_unknown(self, mac):
        """Marks a device as 'Unknown' in the database."""
        # Update local cache regardless
        for d in self.local_cache:
            if d['mac'] == mac:
                d['status'] = 'Unknown'

        # Update device_statuses dict and persist to file
        self.device_statuses[mac] = 'Unknown'
        self._save_device_statuses()

        if not self.use_neo4j:
            self.app.log(f"DatabaseManager: Device {mac} marked as Unknown (Local Cache).")
            return True
            
        try:
            query = "MATCH (d:Device {mac: $mac}) SET d.status = 'Unknown' RETURN d"
            self.neo4j_manager.connection.execute_query(query, {"mac": mac})
            self.app.log(f"DatabaseManager: Device {mac} marked as Unknown.")
            return True
        except Exception as e:
            self.app.log(f"DatabaseManager: Error marking device as Unknown: {e}")
            return True
    
    def get_scan_history(self, limit=10):
        """Retrieves scan history from database."""
        if not self.use_neo4j:
            return []
        
        try:
            return self.neo4j_manager.scan_manager.get_scan_history(limit)
        except Exception as e:
            self.app.log(f"DatabaseManager: Error fetching scan history: {e}")
            return []
    
    def close(self):
        """Closes database connection."""
        if self.neo4j_manager:
            self.neo4j_manager.close()

class ScannerModule:
    """Real Network Scanner using Scapy/ARP via wifi_scanner.py."""
    def __init__(self, app_instance):
        self.app = app_instance
        self.network_scanner = None
        try:
            from wifi_scanner import NetworkScanner
            self.network_scanner = NetworkScanner()
            self.app.log("ScannerModule: Initialized real NetworkScanner.")
        except Exception as e:
            self.app.log(f"ScannerModule: Failed to init NetworkScanner: {e}")

    def run_network_scan(self):
        """Executes the real network scan."""
        if not self.network_scanner:
            self.app.log("ScannerModule: Real scanner not available. Returning empty.")
            return []

        self.app.log("ScannerModule: Starting real network scan (ARP + Ping)...")
        # No artificial sleep needed, the scan takes time
        
        try:
            # Run the scan
            raw_results = self.network_scanner.scan()
            
            # Format results for the App
            devices_found = []
            for device in raw_results:
                # Calculate a random position for the radar (visual only)
                angle = random.randint(0, 360)
                distance = random.uniform(0.1, 0.9)
                
                devices_found.append({
                    'vendor': device.get('vendor', 'Unknown'),
                    'ip': device.get('ip', 'Unknown'),
                    'mac': device.get('mac', 'Unknown'),
                    'status': 'Unknown', # Will be updated against DB later
                    'angle': angle,
                    'distance': distance
                })
                
            self.app.log(f"ScannerModule: Scan finished. Found {len(devices_found)} active targets.")
            return devices_found
            
        except Exception as e:
            self.app.log(f"ScannerModule: Scan error: {e}")
            return []


# --- Helper Widgets ---

class DeviceCard(ctk.CTkFrame):
    """Modern Card widget for displaying device info."""
    def __init__(self, master, device_data, **kwargs):
        is_known = device_data['status'] == 'Known'
        border_color = COLOR_ACCENT_GREEN if is_known else COLOR_BORDER_SUBTLE
        
        super().__init__(master, 
                         fg_color=COLOR_CARD_BG, 
                         border_color=border_color, 
                         border_width=2 if is_known else 1, 
                         corner_radius=12, 
                         **kwargs)
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)

        # Status indicator bar (left edge visual)
        status_color = COLOR_ACCENT_GREEN if is_known else COLOR_ACCENT_RED
        
        # Truncate long vendor names
        vendor_text = device_data['vendor']
        if len(vendor_text) > 20:
            vendor_text = vendor_text[:18] + "..."
        
        # 1. Vendor Name (Bold/Top) - Modern font
        vendor_label = ctk.CTkLabel(self, text=vendor_text, 
                                     font=ctk.CTkFont(family=FONT_FAMILY, weight="bold", size=14), 
                                     text_color=COLOR_ACCENT_BLUE if is_known else COLOR_TEXT_LIGHT)
        vendor_label.grid(row=0, column=0, padx=15, pady=(12, 2), sticky="w") 

        # 2. IP Address (Below) - Slightly larger
        ip_label = ctk.CTkLabel(self, text=device_data['ip'], 
                                 text_color=COLOR_TEXT_LIGHT, 
                                 font=ctk.CTkFont(family=FONT_FAMILY, size=12))
        ip_label.grid(row=1, column=0, padx=15, pady=(0, 12), sticky="w")

        # 3. MAC Address (Right/Small) - Monospace style
        mac_label = ctk.CTkLabel(self, text=device_data['mac'], 
                                  text_color=COLOR_TEXT_GRAY, 
                                  font=ctk.CTkFont(family="Consolas", size=10))
        mac_label.grid(row=1, column=1, padx=15, pady=(0, 12), sticky="e")
        
        # Status Pill (Top Right) - Modern pill badge
        status_text = "KNOWN" if is_known else "UNKNOWN"
        status_pill = ctk.CTkLabel(self, text=status_text,
                                    font=ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold"),
                                    text_color=COLOR_BG_DEEP_BLACK if is_known else COLOR_TEXT_LIGHT,
                                    fg_color=status_color,
                                    corner_radius=10,
                                    width=70,
                                    height=20)
        status_pill.grid(row=0, column=1, padx=15, pady=(12, 0), sticky="e")


# --- Main Application ---

class NetworkAnalyzerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- Setup Window ---
        self.title("NETWORK ANALYZER v1.0")
        self.geometry("1000x700")
        self.config(bg=COLOR_BG_DEEP_BLACK)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        
        # --- Variables ---
        self.current_frame = None
        self.current_angle = 0
        self.scan_in_progress = False
        self.detected_devices = []
        self.scan_start_time = 0

        # --- Module Instances ---
        self.db_manager = DatabaseManager(self)
        self.scanner = ScannerModule(self)
        
        # WiFi Blocker instance (optional)
        self.wifi_blocker = None
        if WIFI_BLOCKER_AVAILABLE:
            try:
                self.wifi_blocker = WiFiBlocker()
                self.log("WiFiBlocker: Initialized successfully.")
                # Load persisted blocked devices
                self._load_blocked_devices()
            except Exception as e:
                self.log(f"WiFiBlocker: Initialization failed: {e}")
                self.wifi_blocker = None

        # --- Build UI Components ---
        self.create_sidebar()
        self.create_main_frames()
        
        self.switch_frame(self.radar_frame)
        self.log("System initialization complete. Status: Active")
        self.update_system_status("Active", "green")
        
        # Start Auto-Scan Loop
        self.auto_scan_enabled = True
        self.schedule_next_scan()


    # --- Logging System ---

    def log(self, message):
        """Prints message to console and the System Logs GUI frame."""
        timestamp = time.strftime("[%H:%M:%S]")
        log_message = f"{timestamp} {message}"
        print(log_message)
        
        if hasattr(self, 'log_text_area'):
            self.log_text_area.configure(state="normal")
            self.log_text_area.insert("end", log_message + "\n")
            self.log_text_area.see("end")
            self.log_text_area.configure(state="disabled")

    def update_system_status(self, status, color):
        """Updates the status indicator at the bottom of the sidebar."""
        if hasattr(self, 'system_status_oval'):
            self.system_status_light.itemconfigure(self.system_status_oval, fill=color)
        self.system_status_label.configure(text=f"System Status: {status}", text_color=color)


    # --- UI Layout Methods ---

    def create_sidebar(self):
        """Creates the dark charcoal sidebar on the left."""
        self.sidebar_frame = ctk.CTkFrame(self, fg_color=COLOR_PANEL_DARK_CHARCOAL, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure((5, 6), weight=1)

        # Title Label
        title_label = ctk.CTkLabel(self.sidebar_frame, text="NETWORK ANALYZER", 
                                   font=ctk.CTkFont(size=18, weight="bold"), text_color=COLOR_ACCENT_RED)
        title_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        version_label = ctk.CTkLabel(self.sidebar_frame, text="Network Analyzer v2.0", text_color=COLOR_TEXT_GRAY)
        version_label.grid(row=1, column=0, padx=20, pady=(0, 30))

        # Navigation Buttons
        self.nav_buttons = [
            ("Radar Dashboard", self.show_radar_dashboard),
            ("Device Manager", self.show_device_manager),
            ("History", self.show_history),
            ("System Logs", self.show_system_logs)
        ]
        
        self.button_widgets = {}
        for i, (text, command) in enumerate(self.nav_buttons):
            button = ctk.CTkButton(self.sidebar_frame, text=text, command=command,
                                   fg_color="transparent", 
                                   hover_color=COLOR_BUTTON_HOVER,
                                   text_color=COLOR_TEXT_LIGHT, anchor="w",
                                   font=ctk.CTkFont(size=14, weight="bold"))
            button.grid(row=i+2, column=0, padx=20, pady=10, sticky="ew")
            self.button_widgets[text] = button

        # Status Indicator at the bottom
        status_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        status_frame.grid(row=7, column=0, padx=20, pady=(10, 20), sticky="sw")

        self.system_status_light = tk.Canvas(status_frame, width=10, height=10, bg=COLOR_PANEL_DARK_CHARCOAL, highlightthickness=0)
        self.system_status_oval = self.system_status_light.create_oval(0, 0, 10, 10, fill="green") 
        self.system_status_light.pack(side="left", padx=(0, 8))
        
        self.system_status_label = ctk.CTkLabel(status_frame, text="System Status: Active", text_color="green", font=ctk.CTkFont(size=12))
        self.system_status_label.pack(side="left")

    def create_main_frames(self):
        """Initializes all content frames for switching."""
        self.main_content_frame = ctk.CTkFrame(self, fg_color=COLOR_BG_DEEP_BLACK, corner_radius=0)
        self.main_content_frame.grid(row=0, column=1, sticky="nsew")
        self.main_content_frame.grid_rowconfigure(0, weight=1)
        self.main_content_frame.grid_columnconfigure(0, weight=1)

        self.radar_frame = self.create_radar_dashboard()
        
        # Device Management Frame
        self.device_manager_frame = self.create_device_manager_frame()
        
        # History Frame
        self.history_frame = self.create_history_frame()

        self.logs_frame = self.create_system_logs_frame()

    def switch_frame(self, frame_to_show):
        """Hides the current frame and shows the new one, updates button style."""
        if self.current_frame is not None:
            self.current_frame.grid_forget()
            
        # Update sidebar button aesthetics 
        for text, button in self.button_widgets.items():
            is_active = (frame_to_show == self.radar_frame and text == "Radar Dashboard") or \
                        (frame_to_show == self.device_manager_frame and text == "Device Manager") or \
                        (frame_to_show == self.history_frame and text == "History") or \
                        (frame_to_show == self.logs_frame and text == "System Logs")
            
            if is_active:
                button.configure(fg_color=COLOR_ACCENT_RED) 
            else:
                button.configure(fg_color="transparent")

        self.current_frame = frame_to_show
        self.current_frame.grid(row=0, column=0, sticky="nsew")


    # --- Radar Dashboard Implementation ---

    def create_radar_dashboard(self):
        """Creates the Radar Dashboard layout with Canvas and Device List."""
        radar_dash = ctk.CTkFrame(self.main_content_frame, fg_color=COLOR_BG_DEEP_BLACK)
        radar_dash.grid_columnconfigure(0, weight=3) 
        radar_dash.grid_columnconfigure(1, weight=1) 
        radar_dash.grid_rowconfigure(0, weight=1)
        
        # 1. Radar View (Left Panel)
        radar_panel = ctk.CTkFrame(radar_dash, fg_color=COLOR_PANEL_DARK_CHARCOAL, corner_radius=8)
        radar_panel.grid(row=0, column=0, padx=(20, 10), pady=20, sticky="nsew")
        radar_panel.grid_rowconfigure(0, weight=1)
        radar_panel.grid_columnconfigure(0, weight=1)
        
        self.radar_canvas = tk.Canvas(radar_panel, bg=COLOR_PANEL_DARK_CHARCOAL, highlightthickness=0)
        self.radar_canvas.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.radar_canvas.bind("<Configure>", self.draw_radar) 
        
        # 2. Device List (Right Panel)
        self.device_list_frame = ctk.CTkScrollableFrame(radar_dash, label_text="DETECTED TARGETS", 
                                                        fg_color=COLOR_PANEL_DARK_CHARCOAL, 
                                                        label_text_color=COLOR_ACCENT_RED,
                                                        corner_radius=8)
        self.device_list_frame.grid(row=0, column=1, padx=(10, 20), pady=20, sticky="nsew")
        
        # Helper Frame for Controls
        controls_frame = ctk.CTkFrame(self.device_list_frame, fg_color="transparent")
        controls_frame.pack(fill="x", padx=10, pady=(10, 5))
        
        # Scan Button
        self.scan_button = ctk.CTkButton(controls_frame, text="START SCAN", 
                                          command=self.start_scan_thread,
                                          fg_color=COLOR_ACCENT_RED, hover_color="#800020")
        self.scan_button.pack(side="top", fill="x", pady=(0, 10))
        
        # Auto-Scan Toggle
        self.auto_scan_var = ctk.BooleanVar(value=True)
        self.auto_scan_switch = ctk.CTkSwitch(controls_frame, text="Auto-Scan (60s)", 
                                              command=self.toggle_auto_scan,
                                              variable=self.auto_scan_var,
                                              progress_color=COLOR_ACCENT_BLUE,
                                              onvalue=True, offvalue=False)
        self.auto_scan_switch.pack(side="top", anchor="w")
        
        self.update_device_list(MOCK_DEVICES) 

        self.animate_radar_sweep()
        
        return radar_dash

    def draw_radar(self, event=None):
        """Draws the static grid and device dots."""
        canvas = self.radar_canvas
        canvas.delete("static") 
        
        w, h = canvas.winfo_width(), canvas.winfo_height()
        center_x, center_y = w // 2, h // 2
        radius = min(w, h) // 2 - 20 

        # Draw concentric rings and center marker
        for i in range(1, 5):
            r = radius * i / 4
            canvas.create_oval(center_x - r, center_y - r, center_x + r, center_y + r, 
                               outline=COLOR_TEXT_GRAY, dash=(2, 2), width=1, tags="static")
        
        # Draw axes
        canvas.create_line(center_x, center_y - radius, center_x, center_y + radius, fill=COLOR_TEXT_GRAY, width=1, tags="static")
        canvas.create_line(center_x - radius, center_y, center_x + radius, center_y, fill=COLOR_TEXT_GRAY, width=1, tags="static")

        # Draw 'My PC' center point
        canvas.create_oval(center_x - 5, center_y - 5, center_x + 5, center_y + 5, fill=COLOR_ACCENT_BLUE, tags="static")
        canvas.create_text(center_x, center_y + 15, text="My PC", fill=COLOR_TEXT_LIGHT, tags="static")

        # Draw detected devices
        canvas.delete("dynamic_dots")
        for device in self.detected_devices:
            # Convert polar coordinates (angle, distance) to Cartesian (x, y)
            r_device = radius * device['distance']
            angle_rad = device['angle'] * math.pi / 180
            
            # Simple jitter for visual variety
            jitter_x = random.uniform(-3, 3) * (1 - device['distance'])
            jitter_y = random.uniform(-3, 3) * (1 - device['distance'])
            
            x = center_x + r_device * math.sin(angle_rad) + jitter_x
            y = center_y - r_device * math.cos(angle_rad) + jitter_y 
            
            # Determine color based on status
            color = "green" if device['status'] == 'Known' else COLOR_ACCENT_RED
            
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=color, tags="dynamic_dots")
            canvas.create_text(x + 2, y - 8, text=device['ip'], fill=COLOR_TEXT_LIGHT, anchor="w", tags="dynamic_dots")


    def animate_radar_sweep(self):
        """The animation loop for the radar sweep."""
        canvas = self.radar_canvas
        w, h = canvas.winfo_width(), canvas.winfo_height()
        
        if w == 1 or h == 1:
             self.after(25, self.animate_radar_sweep)
             return
             
        center_x, center_y = w // 2, h // 2
        radius = min(w, h) // 2 - 20 

        # Delete previous sweep line
        canvas.delete("sweep_line")
        
        # Calculate endpoint for the line
        angle_rad = self.current_angle * math.pi / 180
        end_x = center_x + radius * math.sin(angle_rad)
        end_y = center_y - radius * math.cos(angle_rad)
        
        # Draw the sweep line
        canvas.create_line(center_x, center_y, end_x, end_y, 
                           fill=COLOR_ACCENT_BLUE, width=2, tags="sweep_line")

        # Update angle and loop
        self.current_angle = (self.current_angle + 2) % 360
        self.after(25, self.animate_radar_sweep)


    def update_device_list(self, devices):
        """Updates the device list UI element with new data."""
        # Clear existing cards
        controls_frame = self.scan_button.master
        for widget in self.device_list_frame.winfo_children():
            if widget != controls_frame: 
                widget.destroy()

        # Re-pack the controls
        controls_frame.pack_forget() # Unpack the controls frame
        controls_frame.pack(fill="x", padx=10, pady=(10, 5)) # Pack it back at top
        
        # Sync status with device_statuses dictionary (persisted to file)
        for device in devices:
            mac = device['mac']
            # Look up status from persisted dictionary, default to Unknown
            device['status'] = self.db_manager.device_statuses.get(mac, 'Unknown')

        # Add new cards
        for i, device in enumerate(devices):
            card = DeviceCard(self.device_list_frame, device_data=device)
            card.pack(fill="x", padx=10, pady=(0, 10))
            
        self.detected_devices = devices 
        self.draw_radar() 


    # --- Scan Functionality ---

    def start_scan_thread(self):
        """Starts the network scan in a separate thread."""
        if self.scan_in_progress:
            self.log("Scan failed: A scan is already in progress.")
            return

        self.scan_in_progress = True
        self.scan_start_time = time.time()
        self.update_system_status("Scanning...", "orange")
        self.scan_button.configure(text="SCANNING...", state="disabled", fg_color="gray")
        
        scan_thread = Thread(target=self.run_scanner_logic)
        scan_thread.start()

    def run_scanner_logic(self):
        """Called by the thread to perform scan."""
        try:
            # Execute scan
            devices_from_db = self.db_manager.fetch_devices() # fetch first? mostly for merging if needed
            newly_found_devices = self.scanner.run_network_scan()
            
            duration = time.time() - self.scan_start_time
            
            # Save to DB
            self.db_manager.save_scan_results(newly_found_devices, duration)
            
            # Update UI (Must be done in main thread)
            self.after(0, lambda: self.finish_scan_update_gui(newly_found_devices))
            
        except Exception as e:
            self.after(0, lambda: self.log(f"Scan Error: {e}"))

    def finish_scan_update_gui(self, devices):
        """Updates the UI after the scan thread finishes."""
        self.update_device_list(devices)
        
        self.scan_in_progress = False
        self.update_system_status("Active", "green")
        self.scan_button.configure(text="START SCAN", state="normal", fg_color=COLOR_ACCENT_RED)
        
        # Refresh device manager if active
        if self.current_frame == self.device_manager_frame:
             # Just refresh the current tab
             self.refresh_device_list(self.current_tab)
            
        self.log(f"Scan completed. Found {len(devices)} devices.")
        
        # Schedule next scan check
        self.schedule_next_scan()

    def schedule_next_scan(self):
        """Schedules the next auto-scan check."""
        self.after(60000, self.auto_scan_trigger)

    def auto_scan_trigger(self):
        """Triggered by timer. Runs scan if enabled and idle."""
        if self.auto_scan_enabled and not self.scan_in_progress:
            self.log("Auto-Scan: Triggering scheduled scan...")
            self.start_scan_thread()
        else:
            # Just reschedule check if we skipped
            self.schedule_next_scan()
        
    def toggle_auto_scan(self):
        """Toggles the auto-scan feature."""
        self.auto_scan_enabled = self.auto_scan_var.get()
        status = "Enabled" if self.auto_scan_enabled else "Disabled"
        self.log(f"Auto-Scan: {status}")


    # --- System Logs Implementation ---
    
    def create_system_logs_frame(self):
        """Creates the System Logs frame with a non-editable text area."""
        logs_frame = ctk.CTkFrame(self.main_content_frame, fg_color=COLOR_BG_DEEP_BLACK)
        logs_frame.grid_rowconfigure(1, weight=1)
        logs_frame.grid_columnconfigure(0, weight=1)

        # Title
        title = ctk.CTkLabel(logs_frame, text="SYSTEM LOGS", 
                             font=ctk.CTkFont(size=20, weight="bold"), text_color=COLOR_ACCENT_RED)
        title.grid(row=0, column=0, padx=20, pady=20, sticky="w")

        # Text Area for Logs
        self.log_text_area = ctk.CTkTextbox(logs_frame, 
                                            fg_color=COLOR_PANEL_DARK_CHARCOAL, 
                                            text_color=COLOR_TEXT_GRAY, 
                                            font=ctk.CTkFont(family="Consolas", size=14),
                                            corner_radius=8,
                                            wrap="word")
        self.log_text_area.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self.log_text_area.insert("end", "--- Network Analyzer Boot Sequence ---\n")
        self.log_text_area.configure(state="disabled") 

        return logs_frame

    def create_history_frame(self):
        """Creates the History page with date filtering."""
        page_frame = ctk.CTkFrame(self.main_content_frame, fg_color=COLOR_BG_DEEP_BLACK)
        page_frame.grid_rowconfigure(2, weight=1)  # List area
        page_frame.grid_columnconfigure(0, weight=1)
        
        # 1. Header
        header_frame = ctk.CTkFrame(page_frame, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")
        
        title = ctk.CTkLabel(header_frame, text="DEVICE HISTORY", 
                             font=ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold"), 
                             text_color=COLOR_ACCENT_RED)
        title.pack(side="left")
        
        # Refresh Button
        refresh_btn = ctk.CTkButton(header_frame, text="🔄 Refresh", width=100,
                                     command=self.refresh_history_list,
                                     fg_color=COLOR_PANEL_DARK_CHARCOAL, 
                                     hover_color=COLOR_BUTTON_HOVER,
                                     corner_radius=8)
        refresh_btn.pack(side="right", padx=5)
        
        # 2. Filter Controls
        filter_frame = ctk.CTkFrame(page_frame, fg_color=COLOR_CARD_BG, corner_radius=12)
        filter_frame.grid(row=1, column=0, padx=20, pady=(0, 15), sticky="ew")
        
        # From Date
        ctk.CTkLabel(filter_frame, text="From:", 
                     font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                     text_color=COLOR_TEXT_GRAY).pack(side="left", padx=(15, 5), pady=12)
        
        self.history_from_date = ctk.CTkEntry(filter_frame, width=120, 
                                               placeholder_text="YYYY-MM-DD",
                                               font=ctk.CTkFont(family="Consolas", size=12))
        self.history_from_date.pack(side="left", padx=5, pady=12)
        
        # To Date
        ctk.CTkLabel(filter_frame, text="To:", 
                     font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                     text_color=COLOR_TEXT_GRAY).pack(side="left", padx=(20, 5), pady=12)
        
        self.history_to_date = ctk.CTkEntry(filter_frame, width=120, 
                                             placeholder_text="YYYY-MM-DD",
                                             font=ctk.CTkFont(family="Consolas", size=12))
        self.history_to_date.pack(side="left", padx=5, pady=12)
        
        # Filter Button
        ctk.CTkButton(filter_frame, text="🔍 Filter", width=100,
                      fg_color=COLOR_ACCENT_BLUE, hover_color="#3db5d9",
                      text_color=COLOR_BG_DEEP_BLACK,
                      font=ctk.CTkFont(family=FONT_FAMILY, weight="bold", size=12),
                      corner_radius=8,
                      command=self.apply_history_filter).pack(side="left", padx=(20, 10), pady=12)
        
        # Clear Filter Button
        ctk.CTkButton(filter_frame, text="Clear", width=80,
                      fg_color=COLOR_PANEL_DARK_CHARCOAL, hover_color=COLOR_BUTTON_HOVER,
                      font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                      corner_radius=8,
                      command=self.clear_history_filter).pack(side="left", padx=5, pady=12)
        
        # Device Count Label
        self.history_count_label = ctk.CTkLabel(filter_frame, text="", 
                                                 font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                                                 text_color=COLOR_TEXT_GRAY)
        self.history_count_label.pack(side="right", padx=15, pady=12)
        
        # 3. History List Container
        self.history_list_container = ctk.CTkScrollableFrame(page_frame, 
                                                              fg_color=COLOR_BG_DEEP_BLACK, 
                                                              corner_radius=0)
        self.history_list_container.grid(row=2, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self.history_list_container.grid_columnconfigure(0, weight=1)
        
        return page_frame

    def refresh_history_list(self, devices=None):
        """Refreshes the history list with all devices or filtered devices."""
        container = self.history_list_container
        
        # Clear list
        for widget in container.winfo_children():
            widget.destroy()
        
        # Get all devices if not provided
        if devices is None:
            if self.db_manager.use_neo4j:
                try:
                    devices = self.db_manager.neo4j_manager.device_manager.get_all_devices()
                except Exception as e:
                    self.log(f"History: Error fetching devices: {e}")
                    devices = self.db_manager.get_all_history_devices()
            else:
                # Use persistent device history for offline mode
                devices = self.db_manager.get_all_history_devices()
        
        # Update count label
        self.history_count_label.configure(text=f"{len(devices)} devices found")
        
        if not devices:
            ctk.CTkLabel(container, text="No devices found in history.", 
                        text_color=COLOR_TEXT_GRAY,
                        font=ctk.CTkFont(family=FONT_FAMILY, size=14)).pack(pady=40)
            return
        
        # Create cards for each device
        for device in devices:
            self.create_history_card(device, container)

    def create_history_card(self, device, container):
        """Creates a card for the history list."""
        status = device.get('status', 'Unknown')
        is_known = status == 'Known'
        
        card = ctk.CTkFrame(container, 
                            fg_color=COLOR_CARD_BG, 
                            corner_radius=12,
                            border_width=1,
                            border_color=COLOR_ACCENT_GREEN if is_known else COLOR_BORDER_SUBTLE)
        card.pack(fill="x", pady=6, padx=5)
        
        # Info Frame
        info_frame = ctk.CTkFrame(card, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, padx=15, pady=12)
        
        # Vendor (truncated)
        vendor = device.get('vendor', 'Unknown')
        if len(vendor) > 25:
            vendor = vendor[:23] + "..."
        ctk.CTkLabel(info_frame, text=vendor, 
                     font=ctk.CTkFont(family=FONT_FAMILY, weight="bold", size=14),
                     text_color=COLOR_ACCENT_BLUE if is_known else COLOR_TEXT_LIGHT).pack(anchor="w")
        
        # MAC
        ctk.CTkLabel(info_frame, text=device.get('mac', 'Unknown'), 
                     font=ctk.CTkFont(family="Consolas", size=11),
                     text_color=COLOR_TEXT_GRAY).pack(anchor="w", pady=(2, 0))
        
        # Right side - Status & Dates
        right_frame = ctk.CTkFrame(card, fg_color="transparent")
        right_frame.pack(side="right", padx=15, pady=12)
        
        # Status Pill
        status_color = COLOR_ACCENT_GREEN if is_known else COLOR_ACCENT_RED
        status_pill = ctk.CTkLabel(right_frame, text=status.upper(),
                                    font=ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold"),
                                    text_color=COLOR_BG_DEEP_BLACK if is_known else COLOR_TEXT_LIGHT,
                                    fg_color=status_color,
                                    corner_radius=10,
                                    width=70,
                                    height=20)
        status_pill.pack(anchor="e")
        
        # First Seen
        first_seen = device.get('first_seen', 'N/A')
        if first_seen and first_seen != 'N/A':
            ctk.CTkLabel(right_frame, text=f"First: {first_seen}", 
                         font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                         text_color=COLOR_ACCENT_GREEN).pack(anchor="e", pady=(5, 0))
        
        # Last Seen
        last_seen = device.get('last_seen', device.get('scan_time', 'N/A'))
        if last_seen and last_seen != 'N/A':
            ctk.CTkLabel(right_frame, text=f"Last: {last_seen}", 
                         font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                         text_color=COLOR_TEXT_GRAY).pack(anchor="e", pady=(2, 0))

    def apply_history_filter(self):
        """Applies date filter to history list."""
        from_date = self.history_from_date.get().strip()
        to_date = self.history_to_date.get().strip()
        
        if not from_date or not to_date:
            self.log("History: Please enter both From and To dates.")
            return
        
        # Add time component if not present
        if len(from_date) == 10:
            from_date += " 00:00:00"
        if len(to_date) == 10:
            to_date += " 23:59:59"
        
        self.log(f"History: Filtering from {from_date} to {to_date}")
        
        if self.db_manager.use_neo4j:
            try:
                devices = self.db_manager.neo4j_manager.device_manager.get_devices_by_date_range(from_date, to_date)
                self.refresh_history_list(devices)
            except Exception as e:
                self.log(f"History: Filter error: {e}")
        else:
            # Local filtering from device_history
            filtered_devices = self.db_manager.get_history_by_date_range(from_date, to_date)
            self.refresh_history_list(filtered_devices)

    def clear_history_filter(self):
        """Clears the date filter."""
        self.history_from_date.delete(0, 'end')
        self.history_to_date.delete(0, 'end')
        self.refresh_history_list()

    # --- Manage Devices Implementation ---
    
    # --- Device Management Pages ---
    
    def create_device_manager_frame(self):
        """Creates the unified Device Manager interface."""
        page_frame = ctk.CTkFrame(self.main_content_frame, fg_color=COLOR_BG_DEEP_BLACK)
        page_frame.grid_rowconfigure(2, weight=1) # List area
        page_frame.grid_columnconfigure(0, weight=1)
        
        # 1. Header
        header_frame = ctk.CTkFrame(page_frame, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")
        
        title = ctk.CTkLabel(header_frame, text="DEVICE MANAGER", 
                             font=ctk.CTkFont(size=20, weight="bold"), text_color=COLOR_ACCENT_RED)
        title.pack(side="left")
        
        # Action Buttons Container (Right Side)
        self.dm_actions_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        self.dm_actions_frame.pack(side="right")
        
        self.refresh_btn = ctk.CTkButton(self.dm_actions_frame, text="🔄 Refresh", width=100,
                                         command=lambda: self.refresh_device_list(self.current_tab),
                                         fg_color=COLOR_PANEL_DARK_CHARCOAL, hover_color=COLOR_BUTTON_HOVER)
        self.refresh_btn.pack(side="right", padx=5)
        
        # 2. Tabs (Segmented Button)
        self.current_tab = "Unknown"
        self.tab_selector = ctk.CTkSegmentedButton(page_frame, 
                                                   values=["Unknown", "Known", "Blocked"],
                                                   command=self.switch_dm_tab,
                                                   selected_color=COLOR_ACCENT_RED,
                                                   selected_hover_color="#800020",
                                                   unselected_color=COLOR_PANEL_DARK_CHARCOAL,
                                                   unselected_hover_color=COLOR_BUTTON_HOVER)
        self.tab_selector.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")
        self.tab_selector.set("Unknown")
        
        # 3. List Container
        self.device_list_container = ctk.CTkScrollableFrame(page_frame, fg_color=COLOR_BG_DEEP_BLACK, corner_radius=0)
        self.device_list_container.grid(row=2, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self.device_list_container.grid_columnconfigure(0, weight=1)
        
        # Initial Load
        self.refresh_device_list("Unknown")
        
        return page_frame

    def switch_dm_tab(self, value):
        """Callback for tab switching."""
        self.current_tab = value
        self.refresh_device_list(value)
        
        # Update dynamic buttons in header
        for widget in self.dm_actions_frame.winfo_children():
            if widget != self.refresh_btn:
                widget.destroy()
                
        if value == "Unknown":
            unblock_all_btn = ctk.CTkButton(self.dm_actions_frame, text="Unblock All", width=100,
                                          command=self.unblock_all_action,
                                          fg_color="green", hover_color="#006400")
            unblock_all_btn.pack(side="right", padx=5)
            
            block_all_btn = ctk.CTkButton(self.dm_actions_frame, text="Block All", width=100,
                                        command=self.block_all_unknown_action,
                                        fg_color=COLOR_ACCENT_RED, hover_color="#800020")
            block_all_btn.pack(side="right", padx=5)
            
        elif value == "Blocked":
            unblock_all_btn = ctk.CTkButton(self.dm_actions_frame, text="Unblock All", width=100,
                                          command=self.unblock_all_action,
                                          fg_color="green", hover_color="#006400")
            unblock_all_btn.pack(side="right", padx=5)

    def refresh_device_list(self, filter_type):
        """Refreshes the device list based on current tab."""
        container = self.device_list_container
        
        # Clear list
        for widget in container.winfo_children():
            widget.destroy()
            
        # Get devices / Handler specific logic
        if filter_type == "Blocked":
            self.refresh_blocked_list_view(container)
            return

        devices = []
        if self.db_manager.use_neo4j:
            try:
                if filter_type == "Known":
                    devices = self.db_manager.neo4j_manager.device_manager.get_known_devices()
                else: # Unknown
                    devices = self.db_manager.neo4j_manager.device_manager.get_unknown_devices()
            except Exception as e:
                self.log(f"Error fetching {filter_type} devices: {e}")
                vals = [d for d in self.db_manager.local_cache if d.get('status') == filter_type]
                devices = vals
        else:
             devices = [d for d in self.db_manager.local_cache if d.get('status') == filter_type]

        # Sync with current scan results to get live IPs
        for device in devices:
            current_ip = 'Unknown'
            for active_device in self.detected_devices:
                if active_device['mac'] == device['mac']:
                    current_ip = active_device['ip']
                    break
            
            if current_ip != 'Unknown':
                device['ip'] = current_ip
        
        if not devices:
            ctk.CTkLabel(container, text=f"No {filter_type} devices found.", text_color=COLOR_TEXT_GRAY).pack(pady=20)
            return

        for device in devices:
            self.create_device_management_card(device, container, filter_type)

    def refresh_blocked_list_view(self, container):
        """Sub-function to render blocked list."""
        if not self.wifi_blocker or not self.wifi_blocker.blocked_devices:
            ctk.CTkLabel(container, text="No devices are currently being blocked.", text_color=COLOR_TEXT_GRAY).pack(pady=20)
            return
            
        for ip, info in self.wifi_blocker.blocked_devices.items():
            self.create_blocked_card(ip, info, container)

    def create_device_management_card(self, device, container, list_type):
        """Creates a modern card for Known/Unknown lists."""
        is_known = list_type == "Known"
        card_frame = ctk.CTkFrame(container, 
                                   fg_color=COLOR_CARD_BG, 
                                   corner_radius=12,
                                   border_width=1,
                                   border_color=COLOR_ACCENT_GREEN if is_known else COLOR_BORDER_SUBTLE)
        card_frame.pack(fill="x", pady=8, padx=5)
        
        # Left side - Device Info
        info_frame = ctk.CTkFrame(card_frame, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, padx=15, pady=12)
        
        # Vendor Name (Bold)
        vendor = device.get('vendor', 'Unknown')
        ctk.CTkLabel(info_frame, text=vendor, 
                     font=ctk.CTkFont(family=FONT_FAMILY, weight="bold", size=14),
                     text_color=COLOR_ACCENT_BLUE if is_known else COLOR_TEXT_LIGHT).pack(anchor="w")
        
        # MAC Address (Monospace)
        ctk.CTkLabel(info_frame, text=device['mac'], 
                     font=ctk.CTkFont(family="Consolas", size=11),
                     text_color=COLOR_TEXT_GRAY).pack(anchor="w", pady=(2, 0))
        
        # IP Address
        if 'ip' in device and device['ip'] != 'Unknown':
            ctk.CTkLabel(info_frame, text=device['ip'], 
                         font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                         text_color=COLOR_ACCENT_GREEN if is_known else COLOR_TEXT_GRAY).pack(anchor="w")
        
        # Right side - Action Buttons
        btn_frame = ctk.CTkFrame(card_frame, fg_color="transparent")
        btn_frame.pack(side="right", padx=15, pady=12)
        
        # Modern button styling
        btn_radius = 8
        
        if list_type == "Unknown":
            # Mark Known - Modern green button
            ctk.CTkButton(btn_frame, text="✓ Known", width=90, height=32,
                          fg_color=COLOR_ACCENT_GREEN, hover_color="#05b88a",
                          text_color=COLOR_BG_DEEP_BLACK,
                          font=ctk.CTkFont(family=FONT_FAMILY, weight="bold", size=12),
                          corner_radius=btn_radius,
                          command=lambda m=device['mac']: self.mark_device_as_known_action(m)).pack(side="left", padx=4)
            
            # Blocking Toggle
            is_blocked = False
            device_ip = device.get('ip')
            if self.wifi_blocker and device_ip and device_ip != 'Unknown':
                if device_ip in self.wifi_blocker.blocked_devices and self.wifi_blocker.blocked_devices[device_ip]['active']:
                    is_blocked = True
            
            if is_blocked:
                ctk.CTkButton(btn_frame, text="Unblock", width=90, height=32,
                              fg_color=COLOR_ACCENT_GREEN, hover_color="#05b88a",
                              text_color=COLOR_BG_DEEP_BLACK,
                              font=ctk.CTkFont(family=FONT_FAMILY, weight="bold", size=12),
                              corner_radius=btn_radius,
                              command=lambda m=device['mac']: self.unblock_device_by_mac_action(m)).pack(side="left", padx=4)
            else:
                ctk.CTkButton(btn_frame, text="Block", width=90, height=32,
                              fg_color=COLOR_ACCENT_RED, hover_color="#c5303d",
                              text_color=COLOR_TEXT_LIGHT,
                              font=ctk.CTkFont(family=FONT_FAMILY, weight="bold", size=12),
                              corner_radius=btn_radius,
                              command=lambda m=device['mac'], v=device.get('vendor'): self.block_device_action(m, v)).pack(side="left", padx=4)
                              
        elif list_type == "Known":
            # Mark Unknown button
            ctk.CTkButton(btn_frame, text="Remove", width=90, height=32,
                          fg_color=COLOR_ACCENT_RED, hover_color="#c5303d",
                          text_color=COLOR_TEXT_LIGHT,
                          font=ctk.CTkFont(family=FONT_FAMILY, weight="bold", size=12),
                          corner_radius=btn_radius,
                          command=lambda m=device['mac']: self.mark_device_as_unknown_action(m)).pack(side="left", padx=4)
            
            # Blocking Toggle
            is_blocked = False
            device_ip = device.get('ip')
            if self.wifi_blocker and device_ip and device_ip != 'Unknown':
                if device_ip in self.wifi_blocker.blocked_devices and self.wifi_blocker.blocked_devices[device_ip]['active']:
                    is_blocked = True
                    
            if is_blocked:
                ctk.CTkButton(btn_frame, text="Unblock", width=90, height=32,
                              fg_color=COLOR_ACCENT_GREEN, hover_color="#05b88a",
                              text_color=COLOR_BG_DEEP_BLACK,
                              font=ctk.CTkFont(family=FONT_FAMILY, weight="bold", size=12),
                              corner_radius=btn_radius,
                              command=lambda m=device['mac']: self.unblock_device_by_mac_action(m)).pack(side="left", padx=4)
            else:
                ctk.CTkButton(btn_frame, text="Block", width=90, height=32,
                              fg_color=COLOR_ACCENT_RED, hover_color="#c5303d",
                              text_color=COLOR_TEXT_LIGHT,
                              font=ctk.CTkFont(family=FONT_FAMILY, weight="bold", size=12),
                              corner_radius=btn_radius,
                              command=lambda m=device['mac'], v=device.get('vendor'): self.block_device_action(m, v)).pack(side="left", padx=4)

    def refresh_blocked_list(self):
        """Refreshes the blocked devices list."""
        container = self.blocked_list_container 
        
        for widget in container.winfo_children():
            widget.destroy()
            
        if not self.wifi_blocker or not self.wifi_blocker.blocked_devices:
            ctk.CTkLabel(container, text="No devices are currently being blocked.", text_color=COLOR_TEXT_GRAY).pack(pady=20)
            return
            
        for ip, info in self.wifi_blocker.blocked_devices.items():
            self.create_blocked_card(ip, info, container)

    def create_device_management_card(self, device, container, list_type):
        """Creates a card for Known/Unknown lists."""
        card_frame = ctk.CTkFrame(container, fg_color=COLOR_PANEL_DARK_CHARCOAL, corner_radius=8)
        card_frame.pack(fill="x", pady=5)
        
        # Device Info
        info_text = f"{device.get('vendor', 'Unknown')}\n{device['mac']}"
        if 'ip' in device and device['ip'] != 'Unknown':
             info_text += f"\n{device['ip']}"
             
        ctk.CTkLabel(card_frame, text=info_text, justify="left", 
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=10, pady=10)
        
        # Action Buttons
        btn_frame = ctk.CTkFrame(card_frame, fg_color="transparent")
        btn_frame.pack(side="right", padx=10, pady=10)
        
        if list_type == "Unknown":
            # Mark Known
            ctk.CTkButton(btn_frame, text="✓ Known", width=80, fg_color="green",
                          command=lambda m=device['mac']: self.mark_device_as_known_action(m)).pack(side="left", padx=5)
            
            # Blocking Toggle Logic
            is_blocked = False
            device_ip = device.get('ip')
            if self.wifi_blocker and device_ip and device_ip != 'Unknown':
                if device_ip in self.wifi_blocker.blocked_devices and self.wifi_blocker.blocked_devices[device_ip]['active']:
                    is_blocked = True
            
            if is_blocked:
                # Show Unblock
                ctk.CTkButton(btn_frame, text="Unblock", width=80, fg_color="green",
                              command=lambda m=device['mac'], v=device.get('vendor'): self.unblock_device_by_mac_action(m)).pack(side="left", padx=5)
            else:
                # Show Block
                ctk.CTkButton(btn_frame, text="🚫 Block", width=80, fg_color=COLOR_ACCENT_RED,
                              command=lambda m=device['mac'], v=device.get('vendor'): self.block_device_action(m, v)).pack(side="left", padx=5)
                              
        else:
            # Mark Unknown
            ctk.CTkButton(btn_frame, text="? Unknown", width=80, fg_color=COLOR_ACCENT_RED,
                          command=lambda m=device['mac']: self.mark_device_as_unknown_action(m)).pack(side="left", padx=5)
            # Block (Known devices can also be blocked, standard Block button)
            # Note: For known devices, we usually act nicely, but if requested we can add toggle too.
            # For now keeping it standard block as per original design, but let's add toggle capability if it is already blocked.
            is_blocked = False
            device_ip = device.get('ip')
            if self.wifi_blocker and device_ip and device_ip != 'Unknown':
                if device_ip in self.wifi_blocker.blocked_devices and self.wifi_blocker.blocked_devices[device_ip]['active']:
                    is_blocked = True
                    
            if is_blocked:
                 ctk.CTkButton(btn_frame, text="Unblock", width=80, fg_color="green",
                              command=lambda m=device['mac'], v=device.get('vendor'): self.unblock_device_by_mac_action(m)).pack(side="left", padx=5)
            else:
                 ctk.CTkButton(btn_frame, text="🚫 Block", width=80, fg_color=COLOR_ACCENT_RED,
                              command=lambda m=device['mac'], v=device.get('vendor'): self.block_device_action(m, v)).pack(side="left", padx=5)

    def create_blocked_card(self, ip, info, container):
        """Creates a card for the Blocked Manager."""
        card_frame = ctk.CTkFrame(container, fg_color=COLOR_PANEL_DARK_CHARCOAL, border_color=COLOR_ACCENT_RED, border_width=1)
        card_frame.pack(fill="x", pady=5)
        
        status = "Active" if info['active'] else "Inactive"
        
        info_text = f"IP: {ip}\nMAC: {info['mac']}\nStatus: {status}"
        ctk.CTkLabel(card_frame, text=info_text, justify="left", text_color=COLOR_ACCENT_RED).pack(side="left", padx=10, pady=10)
        
        ctk.CTkButton(card_frame, text="Unblock", width=100,
                      command=lambda i=ip: self.unblock_device_action(i)).pack(side="right", padx=20)

    def unblock_device_action(self, ip):
        """Unblocks a specific device."""
        if self.wifi_blocker:
            self.wifi_blocker.unblock_device(ip)
            self.refresh_blocked_list()
            self.log(f"Unblocked device: {ip}")

    def unblock_all_action(self):
        """Unblocks all devices."""
        if self.wifi_blocker:
            self.wifi_blocker.unblock_all()
            self.refresh_blocked_list()
            # Also refresh other lists to update toggle buttons
            self.refresh_device_list("Unknown")
            self.refresh_device_list("Known")
            self.log("Unblocked all devices.")

    def block_all_unknown_action(self):
        """Blocks all devices currently in the Unknown list."""
        self.log("Action: Block All Unknown Devices initiated...")
        
        # Get current unknown devices
        devices = []
        if self.db_manager.use_neo4j:
            try:
                devices = self.db_manager.neo4j_manager.device_manager.get_unknown_devices()
            except:
                devices = [d for d in self.db_manager.local_cache if d.get('status') == 'Unknown']
        else:
            devices = [d for d in self.db_manager.local_cache if d.get('status') == 'Unknown']
            
        count = 0
        skipped = 0
        
        # First sync IPs like we do in refresh
        for device in devices:
            current_ip = None
            for active_device in self.detected_devices:
                if active_device['mac'] == device['mac']:
                    current_ip = active_device['ip']
                    break
            
            if current_ip:
                device['ip'] = current_ip
                
            # Only block if we have a valid IP
            if device.get('ip') and device['ip'] != 'Unknown':
                mac = device['mac']
                vendor = device.get('vendor', 'Unknown')
                self.block_device_action(mac, vendor)
                count += 1
            else:
                skipped += 1
            
        self.log(f"Block All: Requested blocking for {count} devices. Skipped {skipped} offline/unknown IP devices.")
        self.refresh_device_list("Unknown")
        
    def delete_device_action(self, mac):
        """Deletes a device from the database and refreshes list."""
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete device {mac}?"):
            if self.db_manager.delete_device(mac):
                self.log(f"Action: Deleted device {mac}.")
                # Refresh both lists to be safe
                self.refresh_device_list("Known")
                self.refresh_device_list("Unknown")
            else:
                self.log(f"Error: Failed to delete device {mac}.")
        
    def unblock_device_by_mac_action(self, mac):
        """Unblocks a device by looking up its IP from the blocked list."""
        if not self.wifi_blocker: return
        
        target_ip = None
        for ip, info in self.wifi_blocker.blocked_devices.items():
            if info['mac'] == mac:
                target_ip = ip
                break
        
        if target_ip:
            self.unblock_device_action(target_ip)
            self.refresh_device_list(self.current_tab) # Refresh immediate UI
        else:
            self.log("Error: Could not find active block for this MAC.")

    # --- Navigation Methods ---
    def show_radar_dashboard(self): self.switch_frame(self.radar_frame)
    def show_device_manager(self): 
        self.switch_frame(self.device_manager_frame)
        self.refresh_device_list(self.current_tab) # Refresh current tab
    def show_history(self): 
        self.switch_frame(self.history_frame)
        self.refresh_history_list()  # Load history on show
    def show_system_logs(self): self.switch_frame(self.logs_frame)
    
    def mark_device_as_known_action(self, mac):
        """Marks a device as Known and refreshes the list."""
        if self.db_manager.mark_device_as_known(mac):
            self.refresh_device_list(self.current_tab)
            self.log(f"Action: Device {mac} marked as Known.")
        else:
            self.log(f"Error: Could not mark device {mac} as Known.")
    
    def mark_device_as_unknown_action(self, mac):
        """Marks a device as Unknown and refreshes the list."""
        if self.db_manager.mark_device_as_unknown(mac):
             self.refresh_device_list(self.current_tab)
             self.log(f"Action: Device {mac} marked as Unknown.")
        else:
             self.log(f"Error: Could not mark device {mac} as Unknown.")
    
    def block_device_action(self, mac, vendor):
        """Blocks a device using ARP spoofing via wifi_blocker.py."""
        self.log(f"Action: Block request for {vendor} ({mac})")
        
        if not self.wifi_blocker:
            self.log("Error: WiFi blocker not available. Requires admin privileges and Npcap.")
            return
        
        # Get IP address for this MAC
        # 1. Try to find in current scan results first (most reliable for current session)
        device_ip = None
        for device in self.detected_devices:
            if device['mac'] == mac:
                device_ip = device['ip']
                break
        
        # 2. If not in current scan, check DB last known IP (might be stale, but worth a shot)
        if not device_ip and self.db_manager.use_neo4j:
            try:
                query = """
                MATCH (d:Device {mac: $mac})-[r:DETECTED_IN]->(s:NetworkScan)
                WHERE r.ip_at_scan <> 'Unknown'
                RETURN r.ip_at_scan as ip
                ORDER BY s.timestamp DESC
                LIMIT 1
                """
                result = self.db_manager.neo4j_manager.connection.execute_query(query, {"mac": mac.upper()})
                if result and len(result) > 0:
                    device_ip = result[0].get('ip')
            except Exception as e:
                self.log(f"Error finding IP for MAC {mac}: {e}")
        
        if not device_ip or device_ip == 'Unknown':
            self.log(f"Error: Could not find IP address for {vendor} ({mac})")
            self.log("Tip: Run a network scan first to refresh IP addresses.")
            return
            
        # Execute Block
        self.log(f"Attacking {device_ip} ({mac})...")
        success, message = self.wifi_blocker.block_device(device_ip)
        
        if success:
            self.log(f"SUCCESS: {message}. device is being disconnected.")
            self.refresh_device_list(self.current_tab) # Refresh to show status
        else:
            self.log(f"FAILED: {message}")
        
        # Prepare blocking
        self.log(f"Preparing to block {vendor} at {device_ip}...")
        
        # Check basic conditions
        if device_ip == self.wifi_blocker.gateway_ip:
            self.log("FAILED: Cannot block gateway")
            return
        
        if device_ip == self.wifi_blocker.my_ip:
            self.log("FAILED: Cannot block yourself")
            return
        
        if device_ip in self.wifi_blocker.blocked_devices and self.wifi_blocker.blocked_devices[device_ip]["active"]:
            self.log("FAILED: Device already blocked")
            return
        
        # We already have the MAC from Neo4j - use it directly!
        target_mac = mac.upper()
        self.log(f"Using MAC from database: {target_mac}")
        
        # Create blocking entry directly
        import threading
        
        self.wifi_blocker.blocked_devices[device_ip] = {
            "mac": target_mac,
            "active": True,
            "thread": None,
            "success": False
        }
        
        # Start blocking thread
        thread = threading.Thread(
            target=self.wifi_blocker._block_thread,
            args=(device_ip, target_mac),
            daemon=True
        )
        self.wifi_blocker.blocked_devices[device_ip]["thread"] = thread
        thread.start()
        
        # Wait a moment to check if it's working
        import time
        time.sleep(0.5)
        
        if self.wifi_blocker.blocked_devices[device_ip]["active"]:
            self.log(f"SUCCESS: Blocking {vendor} ({target_mac}) at {device_ip}")
            self.log("Device is now being blocked via ARP spoofing")
            self.log("Blocking will continue until you close the application")
            # Save blocked devices to persist across restarts
            self._save_blocked_devices()
        else:
            self.log(f"FAILED: Could not start blocking for {vendor}")

    def _load_blocked_devices(self):
        """Loads blocked devices from JSON file and re-enables blocking."""
        filepath = DatabaseManager.BLOCKED_DEVICES_FILE
        if not os.path.exists(filepath):
            return
        
        try:
            with open(filepath, 'r') as f:
                saved_blocks = json.load(f)
            
            if not saved_blocks:
                return
            
            self.log(f"BlockPersistence: Found {len(saved_blocks)} previously blocked devices.")
            
            for block in saved_blocks:
                ip = block.get('ip')
                mac = block.get('mac')
                
                if ip and mac and self.wifi_blocker:
                    # Re-enable blocking for this device
                    import threading
                    self.wifi_blocker.blocked_devices[ip] = {
                        "mac": mac,
                        "active": True,
                        "thread": None,
                        "success": False
                    }
                    thread = threading.Thread(
                        target=self.wifi_blocker._block_thread,
                        args=(ip, mac),
                        daemon=True
                    )
                    self.wifi_blocker.blocked_devices[ip]["thread"] = thread
                    thread.start()
                    self.log(f"BlockPersistence: Re-blocked {mac} at {ip}")
                    
        except Exception as e:
            self.log(f"BlockPersistence: Error loading blocked devices: {e}")

    def _save_blocked_devices(self):
        """Saves currently blocked devices to JSON file for persistence."""
        filepath = DatabaseManager.BLOCKED_DEVICES_FILE
        
        if not self.wifi_blocker:
            return
        
        try:
            blocks_to_save = []
            for ip, info in self.wifi_blocker.blocked_devices.items():
                if info.get('active'):
                    blocks_to_save.append({
                        'ip': ip,
                        'mac': info.get('mac')
                    })
            
            with open(filepath, 'w') as f:
                json.dump(blocks_to_save, f, indent=2)
            
            self.log(f"BlockPersistence: Saved {len(blocks_to_save)} blocked devices.")
        except Exception as e:
            self.log(f"BlockPersistence: Error saving blocked devices: {e}")

    # --- End of Class ---

if __name__ == "__main__":
    app = NetworkAnalyzerApp()
    app.mainloop()