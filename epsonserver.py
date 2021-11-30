import socket
import sys

from dataclasses import dataclass
from typing import Optional

@dataclass
class PrintJob:
    name: str


def decode_packbits(buf: bytes) -> bytes:
    """
    Decode a PackBits compressed buffer.

    Returns an uncompressed buffer.
    """
    rbuf = b""
    i = -1
    while i < len(buf)-1:
        i += 1

        byteval = ord(buf[i:i+1])
        if byteval >= 0 and byteval <= 127:
            # next byteval+1 bytes needs to be copied
            rbuf += buf[i+1:i+2+byteval]
            i += byteval+1
        else:
            byteval = 256 - byteval
            if byteval == 128:
                continue # 128 means skip this byte
            else:
                # repeat the next byte of data 1+byteval types
                i += 1
                rbuf += buf[i:i+1] * (byteval+1)

#        print(repr(rbuf))

    return rbuf


print(repr(decode_packbits(b"\xfe\xaa\x02\x80\x00\x2a\xfd\xaa\x03\x80\x00\x2a\x22\xf7\xaa")))
#with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
#    s.bind(("127.0.0.1", 9100))
#    s.listen()
#    print("listening to 0.0.0.0:9100")
#
#    conn, addr = s.accept()
#    with conn:
#        print("job accepted!")
#        count = 1
#
#        with open("out.epson", "wb") as out:
#            while count > 0:
#                msg = conn.recv(10240)
#
#                print("Receiving message")
#
#                count = len(msg)
#                out.write(msg)
#
#            print("Received everything.")

class Printing:
    """
    Represents some printing operation
    """
    pass


def parse_until_enable_printing(stream):
    """
    To enable printing on Epson printers, the driver must send this command:

    > ESC 01@EJL[space]1284.4[newline]@EJL[space][space][space][space]
[space][newline]ESC@

    This command receives a byte stream (file or socket) and receives data
    from it until it finds this pattern.

    We return the stream, left right after this message.
    If EOF is reached, it will return an exception.
    """
    lines = [
        b"\x1b\x01@EJL 1284.4\n",
        b"@EJL\x20\x20\x20\x20\x20\n",
        b"\x1b@"
    ]

    messageidx = 0

    while messageidx <= 2:
        print("l {} pos {}".format(messageidx, stream.tell()))
        if messageidx < 2:
            line = stream.readline()
        else:
            line = stream.read(2) # the last line does not end with a readline()

        compline = lines[messageidx]
        if messageidx == 0:
            cond = line.endswith(compline)
        else:
            cond = line == compline

        if cond is True:
            print("l {} pos {}".format(messageidx, stream.tell()))
            messageidx += 1


    return stream


remote_mode = False

@dataclass
class Command:
    name: str
    ctype: str
    parameters: bytes

    @staticmethod
    def parse_remote(buf: bytes) -> Optional:
        """
        Parse a remote command.

        Remote commands control extra attributes, like print size, etc.

        Returns a command if the command seems valid (it has the right size),
        and None if it is not

        A remote command always has two bytes of type, two bytes of count and
        the remaining data are parameters.
        """
        if len(buf) < 4:
            return None

        if buf == b'\x1b\x00\x00\x00':
            """
            The remote command mode ends if we read bytes '\x1b \x00 \x00 \x00'.
            """
            return Command('remote-end', 'remote', b'')


        name = buf[0:2].decode('ascii')
        bytecount = buf[2] + buf[3]*256
        params = buf[4:]

        if len(params) != bytecount:
            return None

        return Command(name, 'remote', params)

    @staticmethod
    def parse_normal(buf: bytes) -> Optional:
        """
        Tries to parse a normal command.

        Returns a command if the command seems valid (it has the right size),
        and None if it is not
        """

        sizelist = {
            'U': 1,
            '@': 0,
            '\\': 1,
            'r': 1,
            '\r': 0,
            'i': 7,
        }

        restart = b"\x01@EJL 1284.4\n@EJL\x20\x20\x20\x20\x20\n"
        if buf.endswith(restart):
            print("1284.4 mode command recognized, acting as it was a reset")
            name = "@"
            params = []
            bytecount = 0

        elif buf[0] == ord('('):
            if len(buf) < 4:
                return None

            name = buf[0:2].decode('ascii')
            bytecount = buf[2] + buf[3]*256
            params = buf[4:]
        else:
            if len(buf) < 1:
                return None

            name = buf[0:1].decode('ascii')
            bytecount = sizelist.get(name, 99)
            params = buf[1:1+bytecount]


        if len(params) != bytecount:
            return None

        return Command(name, 'normal', params)

def eval_command(cmd: Command, state):
    """
    Evaluate a printer command

    Return the new printer state after that command.
    """
    remote = state.get('remote', False)

    printing = state.get('printing', False)
    printinfo = {}

    graphics = state.get('graphics', False)
    vunit = hunit = pageunits = state.get('pageunits', False)


    if cmd.name == 'remote-end':
        print("Leaving remote mode.")
        remote = False

    elif cmd.ctype == 'remote':
        if cmd.name == 'SN' and cmd.parameters[0] == 0 and len(cmd.parameters) == 3:
            print("Select Mechanism Sequence: operation={:02x}, value(yy)={:02x}".format(
                cmd.parameters[1], cmd.parameters[2]
            ))
        elif cmd.name == 'FP' and cmd.parameters[0] == 0:
            value = cmd.parameters[1] + cmd.parameters[2]*256

            if value == 0xffb0:
                print("Horizontal Left Margin: Borderless")
            else:
                print("Horizontal Left Margin: {} inches ({} units of 1/360 inches)".format(
                    value*360.0, value
                ))
        elif cmd.name == 'PP' and cmd.parameters[0] == 0:
            print("Select Paper Path: tray={:02x}, number(yy)={:02x}".format(
                cmd.parameters[1], cmd.parameters[2]
            ))
        else:
            print("unknown remote command evaluated: ", repr(cmd))


    else:
        if cmd.name == "@":
            print("Printer reset")
            graphics = False
            remote = False
            printing = False

        if cmd.name == "\r":
            print("\n\n\nPrinter carriage return (back to the start of the line)\n\n")
            state.update(headleft=0)
            graphics = False
            remote = False
            printing = False
            print(" ", end="", file=sys.stderr)

        elif cmd.name == "(R" and cmd.parameters == b'\x00REMOTE1':
            print("Entering remote mode.")
            remote = True

        elif cmd.name == "(G" and cmd.parameters[0] == 1:
            print("Graphics Mode Enabled")
            graphics = True

        elif cmd.name == "(U":
            if len(cmd.parameters) == 1:
                value = cmd.parameters[0]
                print("Basic Unit of Measurement (multiples of 1/3600 inch)")
                print("aka the printer DPI")
                print("setting value to {} ({} dpi)".format(value, 3600/value))
                pageunit = vunit = hunit = value/3600
            elif len(cmd.parameters) == 5:
                pageunit = cmd.parameters[0]
                vunit = cmd.parameters[1]
                hunit = cmd.parameters[2]
                baseunit = cmd.parameters[3] + cmd.parameters[4]*256
                print("Basic Unit of Measurement (multiples of 1/BASEUNIT inch)")
                print("aka the printer DPI")
                print("pageunit={}, vunit={}, hunit={}, baseunit={}".format(
                    pageunit, vunit, hunit, baseunit
                ))
                print("dpis: pageunit={}, vunit={}, hunit={}".format(
                    baseunit/pageunit, baseunit/vunit, baseunit/hunit
                ))
                pageunits = pageunit

                # We save the units in inches, not in terms of baseunits, because we
                # want to treat all values the same, and depending on the command,
                # the scale changes.

                vunit = vunit / baseunit
                hunit = hunit / baseunit
                pageunit = pageunit / baseunit

            print(f"\tin inches: pageunit={pageunit}, vunit={vunit}, hunit={hunit}")

            state.update(
                vunits=vunit,
                hunits=hunit,
                pageunits=pageunit
            )

        elif cmd.name == "U":
            print("Print direction: {}".format(
                "unidirectional" if cmd.parameters[0] == 1 else "bidirectional"
            ))

        elif cmd.name == "(d":
            # We have a (d command, but omitting it caused no changes to the actual
            # printing process.
            print("Unknown command (d with params len {}",
                  len(cmd.parameters))

        elif cmd.name == "(i":
            print("Interleave mode enabled (mode {})".format(
                cmd.parameters[0]
            ))

        elif cmd.name == '(C' and len(cmd.parameters) in [2,4]:
            print(repr(cmd))
            params = cmd.parameters
            if len(params) == 2:
                length = params[0] + (params[1] << 8)
            elif len(params) == 4:
                length = params[0] + (params[1] << 8) + (params[2] << 16) + (params[3] << 24)

            print("Page length: {} pageunits".format(length))
            print("\t this means {} inches".format(length*state["pageunits"]))

        elif cmd.name == '(c' and len(cmd.parameters) in [4,8]:
            params = cmd.parameters
            top = 0
            pagelength = 0

            if len(params) == 2:
                top = params[0] + (params[1] << 8)
                pagelength = params[2] + (params[3] << 8)
            elif len(params) == 4:
                top = params[0] + (params[1] << 8) + (params[2] << 16) + (params[3] << 24)
                pagelength = params[4] + (params[5] << 8) + (params[6] << 16) + (params[7] << 24)

            print("Vertical page margin in pageunits: top={}, pagelength={}".format(top, pagelength))
            print("\t in inches: top={}, pagelength={}".format(top*state["pageunits"],
                                                               pagelength*state["pageunits"]))


        elif cmd.name == '(S' and len(cmd.parameters) == 8:
            print(repr(cmd))
            params = cmd.parameters
            width = params[0] + (params[1] << 8) + (params[2] << 16) + (params[3] << 24)
            length = params[4] + (params[5] << 8) + (params[6] << 16) + (params[7] << 24)

            print("Printed page size in pageunits: width={}, length={}".format(width, length))
            print("\t in inches: width={}, length={}".format(width*state["pageunits"],
                                                             length*state["pageunits"]))

            state.update(
                pagelen=length,
                pagewidth=width
            )



        elif cmd.name == '(K' and cmd.parameters[0] == 0 and len(cmd.parameters) == 2:
            print("Setting color mode: ", end='')
            mode = cmd.parameters[1]
            if mode == 1:
                print("grayscale")
            elif mode in [0,2]:
                print(f"color ({mode})")
            else:
                print(f"unknown ({mode})")

        elif cmd.name == '(D' and len(cmd.parameters) == 4:
            params = cmd.parameters
            baseunit = params[0] + (params[1] << 8) #baseunit must be 14400
            vertical = params[2]
            horizontal = params[3]

            print("Setting printer horizontal and vertical spacing")
            print("baseunit={} (should be 14400), vertical={}, horizontal={}".format(
                baseunit, vertical, horizontal
            ))

            nozzle_horizontal = horizontal / baseunit
            nozzle_vertical = vertical * 720 / baseunit

            print("nozzle distance (in inches): vertical=1/{}, horizontal=1/{}".format(
                nozzle_horizontal, nozzle_vertical
            ))

            # What exactly is this above?


        elif cmd.name == '(e' and cmd.parameters[0] == 0:
            print("Printer dotsize: {}".format(cmd.parameters[1]))


        elif cmd.name == '(v' and len(cmd.parameters) in [2,4]:
            print(repr(cmd))
            params = cmd.parameters
            if len(params) == 2:
                feed = params[0] + (params[1] << 8)
            elif len(params) == 4:
                feed = params[0] + (params[1] << 8) + (params[2] << 16) + (params[3] << 24)

            print("Advancing {} VUNITs vertically".format(feed))
            print("\t aka {} inches".format(feed*state["vunits"]))

            # We need to subtract the line count of the printer head?
            state.update(
                headtop = state["headtop"] + feed
            )

            print("\n{:04d}| ".format(state["headtop"]), end="", file=sys.stderr)
            print("<< Head is now at pageunit {} {} >>".format(state["headtop"], state["headleft"]))


        elif cmd.name == '($' and len(cmd.parameters) == 4:
            print(repr(cmd))
            params = cmd.parameters
            feed = params[0] + (params[1] << 8) + (params[2] << 16) + (params[3] << 24)

            print("Advancing {} HUNITs horizontally".format(feed))
            print("\t aka {} inches".format(feed*state["hunits"]))

            state.update(
                headleft = state["headleft"] + feed
            )

            print("<< Head is now at pageunit {} {} >>".format(state["headtop"], state["headleft"]))


        elif cmd.name == 'i':
            import math

            print("Printing data")
            color = cmd.parameters[0]
            compress= cmd.parameters[1]
            bits = cmd.parameters[2]
            pbytes = cmd.parameters[3] + (cmd.parameters[4] << 8)
            plines= cmd.parameters[5] + (cmd.parameters[6] << 8)

            print("\t color={}, compress={}, bpp={}, bytesline={}, lines={}".format(
                color, compress, bits, pbytes, plines
            ))

            # Remember that this is the uncompressed total size!!!
            # not the received.
            #
            # So we need to uncompress until we get this size, if the compression
            # is enabled.
            #
            # After this line, we usually have a \r to move the printer head, or
            # a (v to move it down.
            toread = pbytes*plines

            printing = True
            printinfo = dict(color=color, compress=compress,
                             bpp=bits, bytesline=pbytes, lines=plines, toread=toread)

        else:
            print("unknown command evaluated: ", repr(cmd))


    state.update(
        remote=remote,
        printing=printing,
        graphics=graphics,


        printinfo=printinfo
    )
    return state

from PIL import Image



def plot_to_image(image: Image, imgx: int, imgy: int, width: int,
                  height: int, inkcolor: int, buf: bytes, bpp: int) -> Image:
    import math

    """
    Plot an to-be-printed image, from the buffer 'buf' into 'image',
    in the specified position, and using the specified inkcolor.
    """

    def split_color(colorhex):
        colorhex = colorhex.replace("#", "")
        r, g, b = (colorhex[0:2], colorhex[2:4], colorhex[4:6])

        return [int(r, 16), int(g, 16), int(b, 16)]

    def generate_color(hexmin, hexmax, proportion):
        cmin = split_color(hexmin)
        cmax = split_color(hexmax)
        pinv = 1-proportion

        return [
            int(cmin[0]*proportion + cmax[0]*pinv),
            int(cmin[1]*proportion + cmax[1]*pinv),
            int(cmin[2]*proportion + cmax[2]*pinv)
        ]


    # min and max values for this cartridge
    inkvalues = [
        ["#000000", "#ffffff"], # black
        ["#ff00ff", "#ffffff"], # magenta
        ["#00ffff", "#ffffff"], # cyan
        ["#000000", "#ffffff"], # ????
        ["#ffff00", "#ffffff"], # yellow
        ["#111111", "#ffffff"], # alternate black
        ["#222222", "#ffffff"], # alternate black
    ]

    for py in range(int(height)):
        for px in range(int(width)):
            offset = math.ceil((py*width+px))

# The correct way, sort of
#            offset = math.ceil((py*width+px)*bpp/8)
            if bpp == 2:
                byteoffset = int(offset/4)
                bitoffset = offset%4

                masks = [0b00000011, 0b00001100,
                         0b00110000, 0b11000000]

#                value = buf[byteoffset] & 0x4
                value = (buf[byteoffset] >> (bitoffset*2)) & 0x3
            elif bpp == 8:
                value = buf[offset]
            else:
                raise RuntimeError(f"bpp {bpp} not handled!")


            proportion = value / ((1 << bpp) - 1)
            cartridge = inkvalues[inkcolor]
            color = generate_color(cartridge[0], cartridge[1], proportion)


            try:
                r, g, b = image.getpixel((imgx+px, imgy+(py*2)))

                # emulate printing on paper
                # on printer world, colors subtract, not add
                r -= 255-color[0]
                g -= 255-color[1]
                b -= 255-color[2]

                image.putpixel((imgx+px, imgy+(py*2)), (r, g, b))

                if py < height-1:
                    image.putpixel((imgx+px, imgy+(py*2)+1), (r, g, b))

#                if py == 0:
#                    image.putpixel((imgx+px, imgy+py), (127, 0, 0))
#
#                if py == height-1:
#                    image.putpixel((imgx+px, imgy+py), (0, 0, 127))


            except IndexError:
                continue


    return image


imageout = None

with open("out.epson", "rb") as instream:
    parse_until_enable_printing(instream)
    print("printer initialized (at position {0} ({0:02x}))".format(instream.tell()), file=sys.stderr)

    state = dict(
        remote=False,
        printing=False,
        graphics=False,

        pageunits=0,

        # The page size, expressed in PAGEUNITS
        pagelen=0,
        pagewidth=0,

        # The printer head current location
        headtop=-80,
        headleft=0,

        previous_color=None,

        # How much the head will walk after each draw operation
        headstep=0
    )

    command_buf = b''

    char = True
    while True:
        remote = state.get('remote')
        printing = state.get('printing')

        if printing is True:
            if imageout is None:
                imageout = Image.new("RGB", (state["pagewidth"], state["pagelen"]),
                                     (255, 255, 255))

            printinfo = state["printinfo"]
            toread = printinfo.get('toread', 0)

            if printinfo["compress"] == 0:
                print("\tReceiving uncompressed data")
                data = instream.read(toread)
            elif printinfo["compress"] == 1:
                print("\tReceiving packbits compressed data")

                data = b''
                error = False
                while len(data) < toread:
                    recv = instream.read(1)
                    if len(recv) == 0:
                        error = True
                        break

                    if recv[0] > 0x80:
                        recv += instream.read(1)
                    elif recv[0] >= 0x0 and recv[0] < 0x80:
                        recv += instream.read(recv[0]+1)


                    data += decode_packbits(recv)

            print("\tNow position is {:04x}".format(instream.tell()))
            print("\tPrinting data: ", len(data))

            state["printing"] = False

            vert_spacing = 80


            previous_color = state["previous_color"]

            print("{}".format(printinfo["color"]), end="", file=sys.stderr)


            # Add those random offsets to certain ink types
            # The row count is 60, and they are multiples of the row count, so they
            # probably are related
            #
            # Probably the printer process them 4 lines at a time?
            # Or it has different starting offsets for each color (this actually makes more sense)
            if printinfo["color"] == 5:
                extraY = -120
            elif printinfo["color"] == 6:
                extraY = -240
            elif printinfo["color"] == 1:
                extraY = -120
            elif printinfo["color"] == 4:
                extraY = -240
            else:
                extraY = 0

            # Width of the row, in hunits.
            rowwidth = printinfo["bytesline"] * 8 / printinfo["bpp"]
            rowheight = printinfo["lines"]
            print("rowwidth:", rowwidth)
            imageout = plot_to_image(imageout, state["headleft"],
                                     int(state["headtop"]+extraY),
                                     rowwidth,
                                     rowheight, printinfo["color"],
                                     data,
                                     printinfo["bpp"])


            # state["headleft"] += rowwidth
            state["previous_color"] = printinfo["color"]

            continue


        char = instream.read(1)

        if len(char) == 0:
            if len(command_buf) > 0:
                cmd = Command.parse_normal(command_buf)
                if cmd is not None:
                    eval_command(cmd, state)
            break

        if char == b'\x1b' and remote is False:
            pass
            #print("command incoming (at pos {0} ({0:02x}))".format(instream.tell()), file=sys.stderr)
        else:
            command_buf += char

        if remote is True:
#            import time; time.sleep(0.09)
            print(repr(char), repr(command_buf))

        if len(command_buf) > 0:
            if remote is True:
                command = Command.parse_remote(command_buf)
            else:
                command = Command.parse_normal(command_buf)

            if command is not None:
                state = eval_command(command, state)
                command_buf = b''



imageout.save("out.png")
