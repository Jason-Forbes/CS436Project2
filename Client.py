#reference

import socket

clientSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

class ResourceRecord(object):
    def __init__(self, recordNumber, recordName, recordType, recordResult, recordTimeToLive, recordStatic):
        self.recordNumber = recordNumber
        self.recordName = recordName
        self.recordType = recordType
        self.recordResult = recordResult
        self.recordTimeToLive = recordTimeToLive
        self.static = recordStatic
        
clientSocket.close()