import errno
import socket
import sys
import threading
import time
from tabulate import tabulate
import json

def listen(connection: "UDPConnection", amazoneTable: "RRTable"):
    try:
        while True:
            data, address = connection.receive_message()
            #deserializes the data recieved
            message = deserialize(data)

            #grab our hostname and look up its record within our RR
            hostname = message.get("name")
            record = amazoneTable.get_record(hostname)

            if record:
                #if the record is avaliable, store our record values in response
                response = {
                    "name": record["name"],
                    "type": record["type"],
                    "result": record["result"],
                    "ttl": 60, 
                    "static": 0
                }
            else:
                print("Record not found")
                response = {"status": "NOT_FOUND", "name": hostname}

            #send the serialized message back
            connection.send_message(serialize(response), address)
            amazoneTable.display_table()

    except KeyboardInterrupt:
        print("Keyboard interrupt received, exiting...")
    finally:
        connection.close()

def main():
    initial_records = [
        {"name": "shop.amazone.com", "type": "A", "result": "3.33.147.88", "ttl": None, "static": True},
        {"name": "cloud.amazone.com", "type": "A", "result": "15.197.140.28", "ttl": None, "static": True},
    ]

    amazone_dns_address = ("127.0.0.1", 22000)

    #create our UDP connection and an object of a RRTable
    connection = UDPConnection()
    amazoneTable = RRTable()

    #copy our initial records into our object
    for record in initial_records:
        amazoneTable.add_record(**record)

    #bind our connection to the amazone dns
    connection.bind(amazone_dns_address)

    listen(connection, amazoneTable)


#standard json dump serialization, found through https://www.reddit.com/r/learnpython/comments/194t79i/what_data_can_be_send_with_python_socket/
#returned as string
def serialize(data: dict) -> str:
    return json.dumps(data)

#returned as dict
def deserialize(data: str) -> dict:
    return json.loads(data)


class RRTable:
    def __init__(self):
        self.records = {}
        self.record_number = 0
        self.lock = threading.Lock()

    def add_record(self, name, type, result, ttl=None, static=True, **kwargs):
        with self.lock:
            #avoid repeats
            if name in self.records:
                return
            #increase record number
            self.record_number += 1
            record = {
                "record_number": self.record_number,
                "name": name,
                "type": type,
                "result": result,
                #authoritative records are static
                "ttl": None if static else ttl,
                "static": bool(static),
            }
            #store in records
            record.update(kwargs)
            self.records[name] = record

    def get_record(self, name):
        with self.lock:
            return self.records.get(name, None)

    def display_table(self):
        with self.lock:
            #print nothing if empty
            if not self.records:
                return

            RRheaders = [" ", "Name", "Type", "Result", "TTL", "Static"]
            displayTable = []
            for record in self.records.values():
                #convert our ttl and static variable into displayable values, if theres no ttl just print None
                ttl_display = record["ttl"] if record["ttl"] is not None else "None"
                #convert from true/false to int to match the output image provided
                static_display = 1 if record["static"] else 0
                #add to custom display table, we do this to only print the data we need
                displayTable.append(
                    (record["record_number"], record["name"], record["type"], record["result"], ttl_display, static_display)
                )
            #tabulate used for cleaner looking table
            print(tabulate(displayTable, headers=RRheaders, tablefmt="grid"))
            print()

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
