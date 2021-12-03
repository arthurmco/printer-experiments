import logging
import time

from snmp import Manager
from snmp.exceptions import Timeout
from snmp.types import ASN1

import struct

# uncomment this for verbose output
# logging.basicConfig(level=logging.DEBUG)

# REPLACE 'public' with your community string
manager = Manager(b"public")


def parse_printer_info(text: str):
    rows = {
        cmd[0]: cmd[1]
        for cmd in [t.split(":") for t in text.split(";")]
        if len(cmd) == 2
    }
    return {"commandset": rows["CMD"], "model": rows["MDL"], "class": rows["CLS"]}


def parse_printer_status(blob: bytes):
    if not blob.startswith(b"@BDC ST2\r\n"):
        return None

    blobr = blob[10:]

    ret = {
        "status": "unknown",
        "error": None,
        "has_ink": {"cyan": True, "magenta": True, "yellow": True, "black": True},
        "current_job": None,
        "stats": {},
    }

    length = struct.unpack("H", blobr[:2])[0]

    offset = 0
    while offset < length:
        stype = blobr[2 + offset]
        ssize = blobr[2 + offset + 1]
        sdata = blobr[2 + offset + 2 : 2 + offset + 2 + ssize]

        if stype == 1:
            ret["status"] = {
                0: "error",
                2: "busy",  # might be for maintenance pas
                3: "printing",  # waiting is more like "printing"
                4: "idle",
                10: "shutting down",
            }.get(sdata[0], "unknown")

        elif stype == 2:
            ret["error"] = {
                0: "fatal error",
                4: "paper jam",
                5: "no ink",
                6: "no paper",
                16: "ink overflow",
                0x4B: "driver mismatch",
            }.get(sdata[0], "unknown")

        elif stype == 15:
            blocksize = sdata[0]
            inktypes = int(ssize / blocksize)

            for i in range(inktypes):
                istart = 1 + (i * blocksize)
                iend = 1 + ((i + 1) * blocksize)

                inkblock = sdata[istart:iend]
                inkname = ["black", "cyan", "magenta", "yellow"][inkblock[1]]
                ret["has_ink"][inkname] = True if inkblock[2] == 0x69 else False

        elif stype == 25:
            print(repr(sdata))
            ret["current_job"] = (
                "printing" if sdata != b"\x00\x00\x00\x00\x00unknown" else None
            )

        elif stype == 54:
            _unsupp1, _unsupp2, printed_color, printed_monochrome = struct.unpack(
                "IIII", sdata[:16]
            )
            ret["stats"] = {
                "printed_color_pages": printed_color,
                "printed_monochrome_pages": printed_monochrome,
            }

        offset += 2 + ssize

    return ret


try:
    host = "192.168.1.237"  # REPLACE these IPs with real IPs
    oids = [
        "1.3.6.1.2.1.1.1.0",  # Get Service Name
        "1.3.6.1.4.1.1248.1.2.2.1.1.1.2.1",  # Get Printer Name
        "1.3.6.1.4.1.1248.1.2.2.1.1.1.1.1",  # Get Printer ID
        "1.3.6.1.4.1.1248.1.2.2.1.1.1.4.1",  # Get Printer Status
    ]

    start = time.time()

    system = manager.get(
        host,
        "1.3.6.1.2.1.1.1.0",  # sysDescr
        "1.3.6.1.2.1.1.2.0",  # sysObjectID
        "1.3.6.1.2.1.1.3.0",  # sysUptime
        "1.3.6.1.2.1.1.4.0",  # sysContact
        "1.3.6.1.2.1.1.5.0",  # sysName
        "1.3.6.1.2.1.1.6.0",  # sysLocation
        "1.3.6.1.2.1.1.7.0",  # sysServices
        timeout=1,
    )

    print(repr(system))

    printer_name = manager.get(host, "1.3.6.1.4.1.1248.1.2.2.1.1.1.2.1", timeout=1)
    print("Printer name: {}".format(str(printer_name[0].value)[2:-1]))

    printer_info = manager.get(host, "1.3.6.1.4.1.1248.1.2.2.1.1.1.1.1", timeout=1)
    print(
        "Printer information: ",
        repr(parse_printer_info(str(printer_info[0].value)[2:-1])),
    )

    printer_status = manager.get(host, "1.3.6.1.4.1.1248.1.2.2.1.1.1.4.1", timeout=1)
    print(repr(printer_status))
    print(
        "Printer status: ",
        repr(parse_printer_status(printer_status[0].encoding[19:])),
    )

    end = time.time()
    print("Took {} seconds".format(end - start))

except Timeout as e:
    print("Request for {} from host {} timed out".format(e, host))

finally:
    manager.close()
