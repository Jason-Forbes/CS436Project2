import errno
import socket
import sys
import threading
import time
import json
import random
from tabulate import tabulate


def handle_request(hostname: str, query_code: int, records: "RRTable", connection: "UDPConnection"):
    #check record within client RR
    ourRecord = records.get_record(hostname)
    if ourRecord:
        records.display_table()
        return
    local_dns_address = ("127.0.0.1", 21000)
    #query with a randomly generated value as a transaction id
    query = {
        "trans_id": random.randint(1000, 9999),
        "flag": "QUERY",
        "name": hostname,
        "type": DNSTypes.get_type_name(query_code),
    }

    #Since we couldnt find it in client RR, check local
    message = serialize(query)
    connection.send_message(message, local_dns_address)

    #Receive and deserialize data
    data, _ = connection.receive_message()
    response = deserialize(data)

    #if it isnt found, close that connection
    if "name" not in response or "result" not in response:
        connection.close()
        return

    #Add received record our RRTable
    records.add_record(
        name=response["name"],
        type=response["type"],
        result=response["result"],
        ttl=int(response.get("ttl", 60)),
        static=0  
    )

    #display our table
    print("Record for {hostname} received and cached.") 
    records.display_table()

def main():
    records = RRTable()
    connection = UDPConnection()

    try:
        while True:
            #changed input value to hostname since it seemed redundant
            hostname = input("Enter the hostname (or type 'quit' to exit) ")
            if hostname.lower() == "quit":
                break
            
            #get our query code and send it with our records object , connection and our hostname to handle request
            query_code = DNSTypes.get_type_code("A")
            handle_request(hostname, query_code, records, connection)

    except KeyboardInterrupt:
        print("Keyboard interrupt received, exiting...")
    finally:
        connection.close()


#standard json dump serialization, found through https://www.reddit.com/r/learnpython/comments/194t79i/what_data_can_be_send_with_python_socket/
#returned as string
def serialize(data: dict) -> str:
    return json.dumps(data)

#returned as dict
def deserialize(data: str) -> dict:
    return json.loads(data)


class RRTable:
    def __init__(self):
        self.records = []
        self.record_number = 0
        self.lock = threading.Lock()

        # Background TTL thread
        self.thread = threading.Thread(target=self.__decrement_ttl, daemon=True)
        self.thread.start()

    def add_record(self, name, type, result, ttl=60, static=0, **kwargs):
       # avoid duplicates
        with self.lock:
            for r in self.records:
                if r["name"] == name:
                    return 
            self.record_number += 1
            record = {
                "record_number": self.record_number,
                "name": name,
                "type": type,
                "result": result,
                #if the record isnt static, add our 60 second ttl
                "ttl": None if static else int(ttl),
                "static": int(static),
            }
            #add to list of records
            record.update(kwargs)
            self.records.append(record)

    def get_record(self, name):
        with self.lock:
            for record in self.records:
                if record["name"] == name:
                    return record
        return None

    def display_table(self):
        with self.lock:
            #print nothing if empty
            if not self.records:
                return
            displayTable = []
            RRheaders = [" ", "Name", "Type", "Result", "TTL", "Static"]
            for record in self.records:
                 #convert our ttl and static variable into displayable values, if theres no ttl just print None
                ttl_display = record["ttl"] if record["ttl"] is not None else "None"
                #convert from true/false to int to match the output image provided
                static_display = 1 if record["static"] else 0
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
                expired_names = []
                for record in list(self.records):
                    #decrease record ttl by 1
                    if not record["static"] and record["ttl"] is not None:
                        record["ttl"] -= 1
                     #if record is expired, add to expired
                        if record["ttl"] <= 0:
                            expired_names.append(record["name"])
                #delete all expired records
                for name in expired_names:
                    self.__remove_expired_records(name)

    def __remove_expired_records(self, name):
        for i, record in enumerate(self.records):
            if record["name"] == name:
                del self.records[i]
                break

        #Fix record indexes
        for idx, record in enumerate(self.records, start=1):
            record["record_number"] = idx
        self.record_number = len(self.records)


class DNSTypes:
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
                    print("[Client] Error: Unable to reach the other socket. It might not be up and running.")
                else:
                    print(f"[Client] Socket error: {e}")
                self.close()
                sys.exit(1)
            except KeyboardInterrupt:
                raise

    def close(self):
        self.socket.close()


if __name__ == "__main__":
    main()
