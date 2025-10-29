
import errno
import socket
import sys
import threading
import time
import json
import random
from tabulate import tabulate

#Summary:
# The DNS client program allows users to look up info about hostnames/domains. 
# After receiving a hostname from users, it first checks its own RR table. 
# If it’s not found, it asks the local DNS server. When it gets a response, it saves the result/record in its RR table and then prints out its RR table.

def handle_request(hostname, query_code, records):
    # Check RR table for record
    if(records.get_record(hostname) != None):
        records.display_table()
        return
    
    # If not found, ask the local DNS server, then save the record if valid
    local_dns_address = ("127.0.0.1", 21000)
    connection = UDPConnection()

    query = {
        "trans_id": random.randint(1000, 9999), #generate a random transaction id between 1000 and 9999
        "flag": "QUERY",
       "name": hostname,
        "type": DNSTypes.get_type_name(query_code),
    }
    
    message = serialize(query)
    connection.send_message(message, local_dns_address)

    data, address = connection.receive_message()
    response = deserialize(data)

    print(response)
    record_get = {
        "name": response["name"],
        "type": response["type"],
        "result": response["result"],
        "ttl": 60,
        "static": response.get("static", 0)
    }
    records.add_record(record_get)

    # Display RR table
    records.display_table()
    connection.close()
    


def main():
    try:
        while True:
            input_value = input("Enter the hostname (or type 'quit' to exit) ")
            if input_value.lower() == "quit":
                break

            hostname = input_value
            query_code = DNSTypes.get_type_code("A")

            # For extra credit, let users decide the query type (e.g. A, AAAA, NS, CNAME)
            # This means input_value will be two values separated by a space

            handle_request(hostname)

    except KeyboardInterrupt:
        print("Keyboard interrupt received, exiting...")


def serialize(data: dict) -> str:
    # Create a serialize function
    # This can help prepare data to send through the socket
    return json.dumps(data)


def deserialize(data: str) -> dict:
    # Create a deserialize function
    # This can help prepare data that is received from the socket
    return json.loads(data)



class RRTable:
    def __init__(self):
        self.records = []
        self.record_number = 0

        # Start the background thread
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.__decrement_ttl, daemon=True)
        self.thread.start()

    def add_record(self, name, type, result, ttl = 60, static = False):
        with self.lock:
         self.record_number += 1
         record = {
         'record_number': self.record_number,
         'name': name,
         'type': type,
         'result': result,
         'ttl': None if static else ttl,
         'static': static,
        }
        self.records.append(record)

    def get_record(self, name):
        with self.lock:
            for record in self.records:
                if record["name"]  == name:
                    return record
        return None

    def display_table(self):
        with self.lock:
           if not self.records:
                print("[RR Table Empty]")
                return
        headers = ["record_number", "name", "type", "result", "ttl", "static"]
        print(tabulate(self.records, headers=headers, tablefmt="grid"))

    def __decrement_ttl(self):
        while True:
            with self.lock:
                for record in self.records:
                    if not record["static"] and record["ttl"] > 0:
                        record["ttl"] -= 1
                self.__remove_expired_records()
            time.sleep(1)

    def __remove_expired_records(self, name):
        rec_number = self.records[name]["record_number"]
        self.records.pop(name)
        for record in self.records.values():
            if record["record_number"] > rec_number:
                record["record_number"] -= 1


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
