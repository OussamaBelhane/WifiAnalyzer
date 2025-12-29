import os
import time
from neo4j import GraphDatabase
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Neo4jManager:
    """
    Manages the connection to the Neo4j database and ensures schema integrity.
    """
    def __init__(self):
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = os.getenv("NEO4J_USERNAME", "neo4j")
        self.password = os.getenv("NEO4J_PASSWORD", "password")
        self.driver = None
        self.device_manager = None
        self.scan_manager = None
        
        # This alias allows direct query execution if needed by external classes
        self.connection = self 

        try:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            self.driver.verify_connectivity()
            print("[Neo4j] Connected successfully.")
            
            # Initialize sub-managers
            self.device_manager = DeviceManager(self.driver)
            self.scan_manager = ScanManager(self.driver)
            
            # Initialize schema/constraints
            self._init_schema()
            
        except Exception as e:
            print(f"[Neo4j] Connection failed: {e}")
            self.driver = None

    def _init_schema(self):
        """Creates necessary constraints and indexes for data integrity."""
        queries = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Device) REQUIRE d.mac IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Scan) REQUIRE s.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Network) REQUIRE n.name IS UNIQUE"
        ]
        
        with self.driver.session() as session:
            for q in queries:
                try:
                    session.run(q)
                except Exception as e:
                    print(f"[Neo4j] Schema init error: {e}")

    def is_available(self):
        return self.driver is not None

    def close(self):
        if self.driver:
            self.driver.close()

    def execute_query(self, query, parameters=None):
        """Directly executes a Cypher query."""
        if not self.driver:
            return None
        
        try:
            with self.driver.session() as session:
                result = session.run(query, parameters)
                return [record.data() for record in result]
        except Exception as e:
            print(f"[Neo4j] Query execution error: {e}")
            return None


class DeviceManager:
    """
    Handles all operations related to Devices (creation, updates, status changes).
    Uses Neo4j Labels to represent status: :Known, :Blocked.
    """
    def __init__(self, driver):
        self.driver = driver

    def get_all_devices(self):
        """
        Retrieves all devices with their calculated status based on labels.
        Returns a list of dicts compatible with the app.
        """
        query = """
        MATCH (d:Device)
        OPTIONAL MATCH (d)-[r:DETECTED_AT_SCAN]->(s:Scan)
        WITH d, max(s.timestamp) as last_seen_scan
        RETURN d.mac as mac, 
               d.vendor as vendor, 
               d.ip as ip,
               d.first_seen as first_seen,
               coalesce(last_seen_scan, d.last_seen) as last_seen,
               labels(d) as labels
        """
        try:
            with self.driver.session() as session:
                result = session.run(query)
                devices = []
                for record in result:
                    labels = record["labels"]
                    status = "Unknown"
                    if "Known" in labels:
                        status = "Known"
                    if "Blocked" in labels:
                        status = "Blocked" # Blocked overrides Known if both present (though they shouldn't conflict logic-wise, blocked is more important)
                    
                    devices.append({
                        "mac": record["mac"],
                        "vendor": record["vendor"],
                        "ip": record["ip"],
                        "status": status,
                        "first_seen": record["first_seen"],
                        "last_seen": record["last_seen"]
                    })
                return devices
        except Exception as e:
            print(f"[Neo4j] Error fetching devices: {e}")
            return []

    def get_device_appearance_count(self, mac):
        """Counts how many scans a device has appeared in."""
        query = """
        MATCH (d:Device {mac: $mac})-[r:DETECTED_AT_SCAN]->(s:Scan)
        RETURN count(s) as count
        """
        try:
            with self.driver.session() as session:
                result = session.run(query, mac=mac)
                record = result.single()
                return record["count"] if record else 0
        except Exception as e:
            return 0

    def mark_device_as_known(self, mac):
        """Adds 'Known' label to the device."""
        query = """
        MATCH (d:Device {mac: $mac})
        SET d:Known
        RETURN d
        """
        try:
            with self.driver.session() as session:
                session.run(query, mac=mac)
        except Exception as e:
            print(f"[Neo4j] Error marking device known: {e}")

    def mark_device_as_unknown(self, mac):
        """Removes 'Known' label from the device."""
        query = """
        MATCH (d:Device {mac: $mac})
        REMOVE d:Known
        RETURN d
        """
        try:
            with self.driver.session() as session:
                session.run(query, mac=mac)
        except Exception as e:
            print(f"[Neo4j] Error marking device unknown: {e}")

    def set_device_blocked_status(self, mac, blocked: bool):
        """Adds or removes 'Blocked' label."""
        label_action = "SET d:Blocked" if blocked else "REMOVE d:Blocked"
        query = f"""
        MATCH (d:Device {{mac: $mac}})
        {label_action}
        RETURN d
        """
        try:
            with self.driver.session() as session:
                session.run(query, mac=mac)
        except Exception as e:
            print(f"[Neo4j] Error setting block status: {e}")


class ScanManager:
    """
    Handles network scans and linking devices to scans.
    """
    def __init__(self, driver):
        self.driver = driver

    def create_scan(self, devices, duration):
        """
        Creates a Scan node and links all found devices to it.
        Also updates the central 'Network' node to link current devices.
        """
        scan_id = f"SCAN_{int(time.time())}"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            with self.driver.session() as session:
                # 1. Create Scan Node
                session.run("""
                    CREATE (s:Scan {id: $scan_id, name: $scan_id, timestamp: $timestamp, duration: $duration})
                """, scan_id=scan_id, timestamp=timestamp, duration=duration)

                # 2. Ensure Network Node exists
                session.run("MERGE (n:Network {name: 'Local Network'})")

                # 3. Process each device
                for device in devices:
                    mac = device['mac']
                    vendor = device.get('vendor', 'Unknown')
                    ip = device.get('ip', 'Unknown')
                    
                    # Logic:
                    # - Merge Device node (create if not exists)
                    # - Update basic info (IP can change, Vendor usually static but good to ensure)
                    # - Link to Scan (history)
                    # - Link to Network (current topology)
                    
                    query = """
                    MERGE (d:Device {mac: $mac})
                    ON CREATE SET d.name = $mac, d.vendor = $vendor, d.first_seen = $timestamp
                    SET d.last_seen = $timestamp, d.ip = $ip, d.name = $mac
                    
                    WITH d
                    MATCH (s:Scan {id: $scan_id})
                    MATCH (n:Network {name: 'Local Network'})
                    
                    MERGE (d)-[:DETECTED_AT_SCAN]->(s)
                    MERGE (d)-[:CONNECTED_TO]->(n)
                    """
                    
                    session.run(query, 
                                mac=mac, 
                                vendor=vendor, 
                                ip=ip, 
                                scan_id=scan_id, 
                                timestamp=timestamp)
            
            return scan_id
            
        except Exception as e:
            print(f"[Neo4j] Error saving scan: {e}")
            return None

    def get_scan_history(self, limit=10):
        query = """
        MATCH (s:Scan)
        RETURN s.id as id, s.timestamp as timestamp, s.duration as duration
        ORDER BY s.timestamp DESC
        LIMIT $limit
        """
        try:
            with self.driver.session() as session:
                result = session.run(query, limit=limit)
                return [record.data() for record in result]
        except Exception as e:
            print(f"[Neo4j] Error fetching history: {e}")
            return []

def create_neo4j_manager():
    return Neo4jManager()
