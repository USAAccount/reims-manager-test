"""Authored sockets only: no phone, service, driver or VM is contacted."""
import importlib.util
from pathlib import Path
import plistlib
import socket
import struct
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("identity", Path(__file__).parents[1] / "iphone-usb-identity.py")
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)
UDID = "00008120-000000000000BEEF"
INSTANCE = "USB\\VID_05AC&PID_12A8\\" + UDID.replace("-", "")


def mux_reply(value, tag):
    data = plistlib.dumps(value)
    return struct.pack("<IIII", len(data) + 16, 1, 8, tag) + data


def phone_reply(value=None, error=False):
    data = plistlib.dumps({"Request": "GetValue", **({"Error": "NotTrusted"} if error else {"Value": value})})
    return struct.pack(">I", len(data)) + data


def row(serial=UDID):
    return {"DeviceID": 42, "Properties": {"ConnectionType": "USB", "ProductID": 0x12A8, "SerialNumber": serial}}


class Peer:
    def __init__(self, data):
        self.data, self.writes, self.closed = bytearray(data), [], False

    def recv(self, size):
        size = min(size, 7, len(self.data))
        result = bytes(self.data[:size])
        del self.data[:size]
        return result

    def sendall(self, value):
        self.writes.append(value)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True


class IdentityTests(unittest.TestCase):
    def run_case(self, devices=None, actual=UDID, ecid=0xBEEF, error=False):
        peers = [Peer(mux_reply({"DeviceList": [row()] if devices is None else devices}, 1)),
                 Peer(mux_reply({"MessageType": "Result", "Number": 0}, 2) +
                      phone_reply(actual) + phone_reply(ecid, error))]
        pending = iter(peers)

        def connect(endpoint, timeout):
            self.assertEqual(endpoint, ("127.0.0.1", 27015))
            self.assertEqual(timeout, 5)
            return next(pending)
        return peers, lambda: identity.identify(INSTANCE, connect)

    def test_selected_identity_and_ecid(self):
        peers, run = self.run_case()
        self.assertEqual(run()["ecid"], "000000000000beef")
        self.assertTrue(all(p.closed for p in peers))
        request = plistlib.loads(peers[1].writes[0][16:])
        self.assertEqual(request["DeviceID"], 42)
        self.assertEqual(request["PortNumber"], socket.htons(62078))
        self.assertEqual([plistlib.loads(v[4:])["Key"] for v in peers[1].writes[1:]], ["UniqueDeviceID", "UniqueChipID"])

    def test_absent_and_ambiguous(self):
        for devices in ([], [row(), row()]):
            peers, run = self.run_case(devices=devices)
            with self.assertRaisesRegex(ValueError, "absent or ambiguous"):
                run()
            self.assertFalse(peers[1].writes)

    def test_reused_device_number_refuses_before_ecid(self):
        peers, run = self.run_case(actual="00008120-000000000000CAFE")
        with self.assertRaisesRegex(ValueError, "changed"):
            run()
        self.assertEqual(len(peers[1].writes), 2)
        self.assertTrue(peers[1].closed)

    def test_untrusted_phone(self):
        peers, run = self.run_case(error=True)
        with self.assertRaisesRegex(ValueError, "unlock and trust"):
            run()
        self.assertTrue(peers[1].closed)

    def test_invalid_ecids(self):
        for ecid in (0, -1, True, "beef"):
            _, run = self.run_case(ecid=ecid)
            with self.assertRaisesRegex(ValueError, "ECID"):
                run()
        _, run = self.run_case()
        with patch.object(identity, "lockdown", side_effect=[UDID, 2**64]):
            with self.assertRaisesRegex(ValueError, "ECID"):
                run()

    def test_bad_instance_never_connects(self):
        def unexpected(*args, **kwargs):
            self.fail("invalid selection contacted the Apple service")
        for value in ("USB\\VID_05AC&PID_12A8\\*", INSTANCE.replace("12A8", "1227"),
                      INSTANCE.replace("12A8", "12A8&MI_01")):
            with self.assertRaisesRegex(ValueError, "exactly one"):
                identity.identify(value, unexpected)

    def test_oversized_and_truncated_packets(self):
        for data in (struct.pack("<IIII", identity.LIMIT + 1, 1, 8, 1), b"abc"):
            with self.assertRaises(ValueError):
                identity.mux(Peer(data), {}, 1)


if __name__ == "__main__":
    unittest.main()
