
import errno
import socket
import sys
import threading
import time
from tabulate import tabulate
import struct
import json
import random

class RRTable:
    def __init__(self):
        # Changed self.records to a dictionary for O(1) lookups by name
        self.records = {} # Changed from list to dict
        self.record_number = 0

        # Start the background thread
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.__decrement_ttl, daemon=True)
        self.thread.start()

    def add_record(self, name, type, result, ttl = 60, static = False, **kwargs):
        # Fix 2: Updated method signature to match the call in LocalDNSServer.__init__
        # Added **kwargs to accept 'port' and other potential fields
        with self.lock:
            # Check if record already exists to avoid re-adding statics
            if name in self.records and self.records[name].get('static', False):
                return
            
            self.record_number += 1
            record = {
                'record_number': self.record_number,
                'name': name,
                'type': type,
                'result': result,
                'ttl': None if static else ttl,
                'static': static,
            }
            # Add any extra keyword arguments (like 'port')
            record.update(kwargs) 
            
            # Store in the dictionary, keyed by name
            self.records[name] = record # Store in dictionary

    def get_record(self, name):
        with self.lock:
            # O(1) dictionary lookup
            return self.records.get(name)
        return None

    def display_table(self):
        with self.lock:
            # Get list of all records for tabulate, as it expects a list of dicts
            record_list = list(self.records.values())
            if not record_list:
                print("[RR Table Empty]")
                return
            headers = ["record_number", "name", "type", "result", "ttl", "static"]
            print(tabulate(record_list, headers=headers, tablefmt="grid"))

    def __decrement_ttl(self):
        # Fix 1: Removed the 'name' argument from __remove_expired_records() call
        while True:
            with self.lock:
                # Use list(self.records.values()) to iterate over a copy of values 
                # to avoid changing the dict size during iteration, although 
                # the dictionary keys themselves aren't being deleted here.
                for record in self.records.values():
                    # Handle the case where ttl is None (static record)
                    if record.get("static") is not True and record["ttl"] is not None and record["ttl"] > 0:
                        record["ttl"] -= 1
                self.__remove_expired_records() # Removed 'name' argument
            time.sleep(1)

    def __remove_expired_records(self):
        # Fix 1: Updated method signature to take no arguments
        with self.lock:
            # Use list(self.records.keys()) to iterate over keys while potentially modifying the dict
            expired_names = [name for name, record in self.records.items() 
                             if record.get("static") is not True and record["ttl"] is not None and record["ttl"] <= 0]
            
            if expired_names:
                # Remove all expired records
                for name in expired_names:
                    del self.records[name]
                
                # Re-calculate record_number for remaining records
                # This logic is complex with a dict, simplified by re-indexing
                # Only strictly necessary if record_number is used as a sequential ID
                self.record_number = 0
                temp_records = {}
                for record in self.records.values():
                    self.record_number += 1
                    record['record_number'] = self.record_number
                    temp_records[record['name']] = record
                self.records = temp_records
                print(f"Removed {len(expired_names)} expired record(s).")


def serialize(data: dict) -> str:
    # Create a serialize function
    # This can help prepare data to send through the socket
    return json.dumps(data)

def deserialize(data: str) -> dict:
    # Create a deserialize function
    # This can help prepare data that is received from the socket
    return json.loads(data)

class LocalDNSServer:
    def __init__(self, local_dns_address: tuple[str, int], initial_records: list):
        self.record_table = RRTable()
        self.connection = UDPConnection()
        
        # Add initial records
        for record in initial_records:
            # Fix 3: Unpack the dictionary 'record' into keyword arguments for add_record
            # This correctly supplies 'name', 'type', 'result', etc.
            self.record_table.add_record(**record) 
        
        # Bind address to UDP socket
        self.connection.bind(local_dns_address)
        print(f"Local DNS Server listening on {local_dns_address[0]}:{local_dns_address[1]}")

    def __resolve_query(self, message: dict, received_address: tuple[str, int]):
        """Handles the logic for resolving a single DNS query."""
        
        # 1. Check local cache
        print("Attempting to fetch record for: " + message["name"])
        record = self.record_table.get_record(message["name"])

        # 2. If record is not in cache or is not an 'A' record (and needs resolution)
        # The original logic checks if not record OR not record["type"] == 'A',
        # which means it will proceed to authoritative server even if it finds an 'NS' record.
        # Keeping this original logic for refactoring purpose.
        if not record or not record["type"] == 'A':
            print("Record not found or requires further resolution. Contacting Authoritative server.", flush=True)
            
            # --- Authoritative Server Lookup Logic ---
            
            # Get the base domain (e.g., 'amazone.com' from 'shop.amazone.com')
            domain_parts = message["name"].split(".")
            # Join the last 2 list items around '.'
            domain_name = ".".join(domain_parts[-2:])

            # Find authoritative server info using NS record for the domain
            ns_record = self.record_table.get_record(domain_name)
            if not ns_record:
                print(f"ERROR: NS record for {domain_name} not found locally. Cannot resolve.")
                # Send a non-existent domain/server error response if needed,
                # but for refactoring, just skip the authoritative query.
                return

            authoritative_server_name = ns_record["result"]
            
            # Find authoritative server address (A record for the NS name)
            a_record = self.record_table.get_record(authoritative_server_name)
            if not a_record:
                print(f"ERROR: A record for NS server {authoritative_server_name} not found locally. Cannot resolve.")
                return

            authoritative_address = (a_record["result"], a_record["port"])

            # Send query to authoritative server
            self.connection.send_message(serialize(message), authoritative_address) # Added serialize()

            # Receive response from authoritative server
            response_data, _ = self.connection.receive_message() # Unpack the tuple
            response = deserialize(response_data) # Deserialize the response

            # Mark as non-static (cacheable)
            # Response should contain the record, not just metadata
            # Assuming the authoritative server returns a full record in its response
            # Fix 4: Unpack and add the received record to the table
            if 'name' in response and 'type' in response and 'result' in response:
                # Assuming 'response' is the record dict received
                response["static"] = 0 
                # Pass all fields from the response dict
                self.record_table.add_record(**response) 
            else:
                print("Received invalid response from authoritative server.")
                return

        # 3. Retrieve final record (either from cache or newly added)
        final_record = self.record_table.get_record(message["name"])
        
        if final_record:
            # 4. Prepare and send response back to client
            final_record["trans_id"] = message["trans_id"]
            final_record["flag"] = "RESPONSE"

            self.record_table.display_table()
            
            # Fix 5: Serialize the final_record before sending
            self.connection.send_message(serialize(final_record), received_address)
        else:
            print(f"ERROR: Final record for {message['name']} not found after resolution attempt.")
            # Could send a negative response here

    def run(self):
        """Starts the server loop to listen for queries."""
        try:
            while True:
                # Wait for query
                data, received_address = self.connection.receive_message()

                if data:
                    # Fix 6: Deserialize the received data
                    message = deserialize(data)
                    
                    # query case
                    if message.get("flag") == "QUERY":
                        self.__resolve_query(message, received_address)

        except KeyboardInterrupt:
            print("Keyboard interrupt received, exiting...")
        finally:
            print("Closing connection...")
            self.connection.close()

# The original listen function is now replaced by LocalDNSServer.run() and __resolve_query()

def main():
    initial_records = [
        {"name": "www.csusm.edu", "type": "A", "result": "144.37.5.45", "ttl": 60, "static": True}, # static: 1 -> True
        {"name": "my.csusm.edu", "type": "A", "result": "144.37.5.150", "ttl": 60, "static": True}, # static: 1 -> True
        {"name": "amazone.com", "type": "NS", "result": "dns.amazone.com", "ttl": 60, "static": True}, # static: 1 -> True
        {"name": "dns.amazone.com", "type": "A", "result": "127.0.0.1", "port": 22000, "ttl": 60, "static": True}, # static: 1 -> True
    ]

    local_dns_address = ("127.0.0.1", 21000)
    
    # Initialize and run the server
    server = LocalDNSServer(local_dns_address, initial_records)
    
    # If testing is required, it should be in a separate block or module.

    server.run()

class DNSTypes:
    """
    A class to manage DNS query types and their corresponding codes.

    Examples:
    >>> DNSTypes.get_type_code('A')
    8
    >>> DNSTypes.get_type_name(0b0100)
    'AAAA'
    """

    name_to_code = {
        "A": 0b1000,
        "AAAA": 0b0100,
        "CNAME": 0b0010,
        "NS": 0b0001,
    }

    code_to_name = {code: name for name, code in name_to_code.items()}

    @staticmethod
    def get_type_code(type_name: str):
        """Gets the code for the given DNS query type name, or None"""
        return DNSTypes.name_to_code.get(type_name, None)

    @staticmethod
    def get_type_name(type_code: int):
        """Gets the DNS query type name for the given code, or None"""
        return DNSTypes.code_to_name.get(type_code, None)


class UDPConnection:
    """A class to handle UDP socket communication, capable of acting as both a client and a server."""

    def __init__(self, timeout: int = 1):
        """Initializes the UDPConnection instance with a timeout. Defaults to 1."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(timeout)
        self.is_bound = False

    def send_message(self, message: str, address: tuple[str, int]):
        """Sends a message to the specified address."""
        self.socket.sendto(message.encode(), address)

    def receive_message(self):
        """
        Receives a message from the socket.

        Returns:
            tuple (data, address): The received message and the address it came from.

        Raises:
            KeyboardInterrupt: If the program is interrupted manually.
        """
        while True:
            try:
                data, address = self.socket.recvfrom(4096)
                return data.decode(), address
            except socket.timeout:
                continue
            except OSError as e:
                if e.errno == errno.ECONNRESET:
                    print("Error: Unable to reach the other socket. It might not be up and running.")
                else:
                    print(f"Socket error: {e}")
                self.close()
                sys.exit(1)
            except KeyboardInterrupt:
                raise

    def bind(self, address: tuple[str, int]):
        """Binds the socket to the given address. This means it will be a server."""
        if self.is_bound:
            print(f"Socket is already bound to address: {self.socket.getsockname()}")
            return
        self.socket.bind(address)
        self.is_bound = True

    def close(self):
        """Closes the UDP socket."""
        self.socket.close()


if __name__ == "__main__":
    main()
