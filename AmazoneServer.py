
import errno
import socket
import sys
import threading
import time
from tabulate import tabulate
import json
import random

class RRTable:
    def __init__(self):
        self.records = {}
        self.record_number = 0
        self.lock = threading.Lock()

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
            for record in self.records:
                if record["name"]  == name:
                    return record
            return None

    def display_table(self):
        with self.lock:
            # Get list of all records for tabulate, as it expects a list of dicts
            headers = [" ", "Name", "Type", "Result", "Ttl", "Static"]
            table = []
            for name in self.records:
                record = self.records[name]
                row = name, record["type"], record["result"], record["ttl"], record["static"]
                table.append(row)
            print(tabulate(table, headers=headers, tablefmt="grid"))
            print("\n")

def listen(connection: "UDPConnection", amazoneTable: "RRTable"):
    try:
        while True:
            # Wait for query
            data, address = connection.receive_message()
            message = deserialize(data)

            hostname = message.get("name")
            messageType = message.get("type")

            record = amazoneTable.get_record(hostname)
            # Check RR table for record
            if not record:
                response = {
                    "status": "FOUND",
                    "record": record
                }
            # If not found, add "Record not found" in the DNS response
            else:
                response = {
                    "status": "NOT_FOUND",
                    "message": "Record not found"
                }
            # Else, return record in DNS response
            connection.send_message(serialize(response), address)

            # Display RR table
            amazoneTable.display_table()

    except KeyboardInterrupt:
        print("Keyboard interrupt received, exiting...")
    finally:
        # Close UDP socket
        connection.close()


def main():
    # Add initial records
    initialRecords = [
        {"name": "shop.amazone.com", "type": "A", "result": "3.33.147.88", "ttl": 60, "static": True},
        {"name": "cloud.amazone.com", "type": "A", "result": "15.197.140.28", "ttl": 60, "static": True},
     ]
    
    amazone_dns_address = ("127.0.0.1", 22000)

    connection = UDPConnection()
    amazoneTable = RRTable()


    # Bind address to UDP socket
    connection.bind(amazone_dns_address)

    print("Running....")
    listen(connection, amazoneTable)


def serialize(data: dict) -> str:
    # Consider creating a serialize function
    # This can help prepare data to send through the socket
    return json.dumps(data)


def deserialize(data: str) -> dict:
    # Consider creating a deserialize function
    # This can help prepare data that is received from the socket
    return json.loads(data)

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

if __name__ == "__main__":
    main()