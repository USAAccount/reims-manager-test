"""Read the selected normal iPhone's identity through Windows' Apple service."""
import json
import plistlib
import re
import socket
import struct
import sys

LIMIT = 1024 * 1024


def read_exact(stream, size):
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.recv(size - len(chunks))
        if not chunk:
            raise ValueError("Apple service closed an incomplete reply")
        chunks.extend(chunk)
    return bytes(chunks)


def mux(stream, request, tag):
    payload = plistlib.dumps(request)
    stream.sendall(struct.pack("<IIII", 16 + len(payload), 1, 8, tag) + payload)
    size, version, kind, reply_tag = struct.unpack("<IIII", read_exact(stream, 16))
    if not 16 <= size <= LIMIT or (version, kind, reply_tag) != (1, 8, tag):
        raise ValueError("Invalid Apple USB service reply")
    result = plistlib.loads(read_exact(stream, size - 16))
    if not isinstance(result, dict):
        raise ValueError("Apple USB service reply is not a dictionary")
    return result


def lockdown(stream, key):
    payload = plistlib.dumps({"Label": "ReimsManager", "Request": "GetValue", "Key": key})
    stream.sendall(struct.pack(">I", len(payload)) + payload)
    size, = struct.unpack(">I", read_exact(stream, 4))
    if not 1 <= size <= LIMIT:
        raise ValueError("Invalid iPhone identity reply size")
    result = plistlib.loads(read_exact(stream, size))
    if not isinstance(result, dict) or result.get("Request") != "GetValue" or "Error" in result:
        raise ValueError("iPhone identity is unavailable; unlock and trust this Windows computer")
    return result.get("Value")


def normalized_udid(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9A-Fa-f-]{16,64}", value):
        raise ValueError("Invalid iPhone USB identity")
    return value.replace("-", "").upper()


def identify(instance_id, connect=socket.create_connection):
    match = re.fullmatch(r"USB\\VID_05AC&PID_12A8(?:&REV_[0-9A-F]{4})?\\([0-9A-F-]{16,64})", instance_id, re.I)
    if not match:
        raise ValueError("Select exactly one normal iPhone parent instance")
    expected = normalized_udid(match[1])
    endpoint = ("127.0.0.1", 27015)
    with connect(endpoint, timeout=5) as stream:
        result = mux(stream, {"MessageType": "ListDevices", "ProgName": "ReimsManager", "kLibUSBMuxVersion": 3}, 1)
    devices = result.get("DeviceList")
    if not isinstance(devices, list) or len(devices) > 128:
        raise ValueError("Invalid Apple USB device list")
    matches = []
    for row in devices:
        if not isinstance(row, dict) or not isinstance(row.get("Properties"), dict):
            raise ValueError("Invalid Apple USB device entry")
        properties = row["Properties"]
        if properties.get("ConnectionType") != "USB" or properties.get("ProductID") != 0x12A8:
            continue
        if normalized_udid(properties.get("SerialNumber")) == expected:
            matches.append(row)
    if len(matches) != 1:
        raise ValueError("Selected iPhone is absent or ambiguous in the Apple service")
    device_id = matches[0].get("DeviceID")
    if type(device_id) is not int or not 0 < device_id <= 0xFFFFFFFF:
        raise ValueError("Invalid Apple USB device number")
    with connect(endpoint, timeout=5) as stream:
        reply = mux(stream, {"MessageType": "Connect", "DeviceID": device_id,
                             "PortNumber": socket.htons(62078), "ProgName": "ReimsManager"}, 2)
        if reply.get("MessageType") != "Result" or type(reply.get("Number")) is not int or reply["Number"] != 0:
            raise ValueError("Could not open the selected iPhone identity service")
        actual = lockdown(stream, "UniqueDeviceID")
        if normalized_udid(actual) != expected:
            raise ValueError("iPhone changed before identity confirmation")
        ecid = lockdown(stream, "UniqueChipID")
    if type(ecid) is not int or not 0 < ecid < 2**64:
        raise ValueError("Invalid iPhone ECID")
    return {"schema": 1, "instance_id": instance_id, "udid": actual, "ecid": f"{ecid:016x}"}


if __name__ == "__main__":
    request = sys.stdin.buffer.read(4097)
    if len(request) > 4096:
        raise SystemExit("Identity request exceeds its size limit")
    value = json.loads(request)
    print(json.dumps(identify(value["instance_id"])))
