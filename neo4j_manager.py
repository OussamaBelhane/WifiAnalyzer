import os
from neo4j import GraphDatabase
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

class Neo4jManager:
    def __init__(self):
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = os.getenv("NEO4J_USERNAME", "neo4j")
        self.password = os.getenv("NEO4J_PASSWORD", "password")
        self.driver = None
        self.device_manager = None
        self.scan_manager = None
        self.connection = self # Alias for direct query execution if needed

        try:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            self.driver.verify_connectivity()
            print("Connected to Neo4j successfully.")
            
            self.device_manager = DeviceManager(self.driver)
            self.scan_manager = ScanManager(self.driver)
            
        except Exception as e:
            print(f"Failed to connect to Neo4j: {e}")
            self.driver = None

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
            print(f"Query execution error: {e}")
            return None

class DeviceManager:
    def __init__(self, driver):
        self.driver = driver

    def get_all_devices(self):
        query = """
        MATCH (d:Device)
        RETURN d.mac as mac, d.vendor as vendor, d.status as status, 
               d.first_seen as first_seen, d.last_seen as last_seen
        """
        try:
            with self.driver.session() as session:
                result = session.run(query)
                return [record.data() for record in result]
        except Exception as e:
            print(f"Error fetching devices: {e}")
            return []

    def get_known_devices(self):
        query = "MATCH (d:Device) WHERE d.status = 'Known' RETURN d.vendor as vendor, d.mac as mac, d.status as status"
        with self.driver.session() as session:
            result = session.run(query)
            return [record.data() for record in result]

    def get_unknown_devices(self):
        query = "MATCH (d:Device) WHERE d.status = 'Unknown' RETURN d.vendor as vendor, d.mac as mac, d.status as status"
        with self.driver.session() as session:
            result = session.run(query)
            return [record.data() for record in result]

    def get_devices_by_date_range(self, start_date, end_date):
        """Gets all devices seen within a date range."""
        query = """
        MATCH (d:Device)-[r:DETECTED_IN]->(s:NetworkScan)
        WHERE s.timestamp >= $start_date AND s.timestamp <= $end_date
        RETURN DISTINCT d.mac as mac, d.vendor as vendor, d.status as status,
               d.first_seen as first_seen, d.last_seen as last_seen,
               r.ip_at_scan as ip, s.timestamp as scan_time
        ORDER BY s.timestamp DESC
        """
        try:
            with self.driver.session() as session:
                result = session.run(query, start_date=start_date, end_date=end_date)
                return [record.data() for record in result]
        except Exception as e:
            print(f"Error fetching devices by date: {e}")
            return []

    def get_device_appearance_count(self, mac):
        query = """
        MATCH (d:Device {mac: $mac})-[r:DETECTED_IN]->(s:NetworkScan)
        RETURN count(r) as count
        """
        try:
            with self.driver.session() as session:
                result = session.run(query, mac=mac)
                record = result.single()
                return record["count"] if record else 0
        except Exception as e:
            print(f"Error counting appearances: {e}")
            return 0

    def mark_device_as_known(self, mac):
        query = "MERGE (d:Device {mac: $mac}) SET d.status = 'Known'"
        try:
            with self.driver.session() as session:
                session.run(query, mac=mac)
        except Exception as e:
            print(f"Error marking device as known: {e}")

class ScanManager:
    def __init__(self, driver):
        self.driver = driver

    def create_scan(self, devices, duration):
        scan_id = f"SCAN_{int(time.time())}"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        query_scan = """
        CREATE (s:NetworkScan {id: $scan_id, timestamp: $timestamp, duration: $duration})
        """
        
        query_device = """
        MERGE (d:Device {mac: $mac})
        ON CREATE SET d.vendor = $vendor, d.status = 'Unknown', d.first_seen = $timestamp
        ON MATCH SET d.last_seen = $timestamp
        WITH d
        MATCH (s:NetworkScan {id: $scan_id})
        MERGE (d)-[:DETECTED_IN {ip_at_scan: $ip}]->(s)
        """
        
        try:
            with self.driver.session() as session:
                # Create Scan Node
                session.run(query_scan, scan_id=scan_id, timestamp=timestamp, duration=duration)
                
                # Link Devices
                for device in devices:
                    session.run(query_device, 
                                mac=device['mac'], 
                                vendor=device.get('vendor', 'Unknown'), 
                                ip=device.get('ip', 'Unknown'),
                                timestamp=timestamp,
                                scan_id=scan_id)
                                
            return scan_id
        except Exception as e:
            print(f"Error saving scan: {e}")
            return None

    def get_scan_history(self, limit=10):
        query = """
        MATCH (s:NetworkScan)
        RETURN s.id as id, s.timestamp as timestamp, s.duration as duration
        ORDER BY s.timestamp DESC
        LIMIT $limit
        """
        try:
            with self.driver.session() as session:
                result = session.run(query, limit=limit)
                return [record.data() for record in result]
        except Exception as e:
            print(f"Error fetching scan history: {e}")
            return []

def create_neo4j_manager():
    return Neo4jManager()
