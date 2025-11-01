import errno
import socket
import sys
import threading
import time
from tabulate import tabulate
import json

def listen(connection: "UDPConnection", localTable: "RRTable"):
    try:
        while True:
            #receive and deserialize the data
            data, address = connection.receive_message()
            message = deserialize(data)


            #lookup name in local table
            hostname = message.get("name")
            record = localTable.get_record(hostname)

            # If it exists and its type is A, serialize and return it
            if record and record["type"] == "A": 
                response = {
                    "name": record["name"],
                    "type": record["type"],
                    "result": record["result"],
                    "ttl": 60,
                    "static": 0,
                }
                connection.send_message(serialize(response), address)
                localTable.display_table()
                continue

            #Reformat the hostname (by period) and check again
            domain = ".".join(hostname.split(".")[-2:])
            ns_record = localTable.get_record(domain)

            if not ns_record:
                continue

            ns_name = ns_record["result"]
            ns_a_record = localTable.get_record(ns_name)
            if not ns_a_record:
                continue

            #Contact authoritative DNS server by port
            amazone_addr = (ns_a_record["result"], ns_a_record["port"])
            connection.send_message(serialize(message), amazone_addr)

            #save the receieved message and deserialize
            data, _ = connection.receive_message()
            response = deserialize(data)

            if response.get("result"):
                #Add to local cache
                response_for_local = dict(response)
                response_for_local["static"] = False
                localTable.add_record(**response_for_local)

                #Send same response to client
                response_to_client = {
                    "name": response["name"],
                    "type": response["type"],
                    "result": response["result"],
                    "ttl": int(response.get("ttl", 60)),
                    "static": 0,
                }
                connection.send_message(serialize(response_to_client), address)
                localTable.display_table()
            else:
                print("Record not found")
                response = {"status": "NOT_FOUND", "name": hostname}
                connection.send_message(serialize(response), address)

    except KeyboardInterrupt:
        print("Keyboard interrupt received, exiting...")
    finally:
        connection.close()


def main():
    initial_records = [
        {"name": "www.csusm.edu", "type": "A", "result": "144.37.5.45", "ttl": None, "static": True},
        {"name": "my.csusm.edu", "type": "A", "result": "144.37.5.150", "ttl": None, "static": True},
        {"name": "amazone.com", "type": "NS", "result": "dns.amazone.com", "ttl": None, "static": True},
        {"name": "dns.amazone.com", "type": "A", "result": "127.0.0.1", "port": 22000, "ttl": None, "static": True},
    ]

    local_dns_address = ("127.0.0.1", 21000)

    connection = UDPConnection()
    localTable = RRTable()

    #add our initial records into our record object
    for record in initial_records:
        localTable.add_record(**record)

    #bind our connction and listen
    connection.bind(local_dns_address)
    listen(connection, localTable)


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

        self.thread = threading.Thread(target=self.__decrement_ttl, daemon=True)
        self.thread.start()

    def add_record(self, name, type, result, ttl=60, static=False, **kwargs):
        with self.lock:
            #avoid repeats
            if name in self.records:
                return
            else:
                self.record_number += 1
                #increase record number
                record = {
                    "record_number": self.record_number,
                    "name": name,
                    "type": type,
                    "result": result,
                    #if the record isnt static, add our 60 second ttl
                    "ttl": None if static else int(ttl),
                    "static": bool(static),
                }
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

    def __decrement_ttl(self):
        while True:
            time.sleep(1)
            with self.lock:
                #save expired records
                expired = []
                for name, record in list(self.records.items()):
                    #decrease record ttl by 1
                    if not record["static"] and record["ttl"] is not None:
                        record["ttl"] -= 1
                        #if record is expired, add toexpired
                        if record["ttl"] <= 0:
                            expired.append(name)
                #delete all expired records
                for name in expired:
                    del self.records[name]


class DNSTypes:
    """DNS type codes and names."""
    name_to_code = {
        "A": 0b1000,
        "AAAA": 0b0100,
        "CNAME": 0b0010,
        "NS": 0b0001,
    }
    code_to_name = {code: name for name, code in name_to_code.items()}

    @staticmethod
    def get_type_code(type_name: str):
        return DNSTypes.name_to_code.get(type_name, None)

    @staticmethod
    def get_type_name(type_code: int):
        return DNSTypes.code_to_name.get(type_code, None)


class UDPConnection:
    """Handles UDP communication for both client and server."""

    def __init__(self, timeout: int = 1):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(timeout)
        self.is_bound = False

    def send_message(self, message: str, address: tuple[str, int]):
        self.socket.sendto(message.encode(), address)

    def receive_message(self):
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
        if self.is_bound:
            print(f"Socket is already bound to address: {self.socket.getsockname()}")
            return
        self.socket.bind(address)
        self.is_bound = True

    def close(self):
        self.socket.close()


if __name__ == "__main__":
    main()
