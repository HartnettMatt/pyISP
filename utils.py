from serial.tools import list_ports
import serial
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

SERIAL_PORT_ENV = "SERIAL_PORT_8051"

FLASH_END = 0x7FFF  # device dependent
PAGE_SIZE = 0x80  # Table 73 (page 104): max 128 bytes/frame, page-aligned


def get_serial_port(save=False):
    """Return the serial device named by the SERIAL_PORT_8051 environment
    variable. If it is unset, prompt the user to select one, and store the
    selection in the variable when `save` is set."""
    port = os.environ.get(SERIAL_PORT_ENV)
    if port:
        logger.info(f"Using port from {SERIAL_PORT_ENV}: {port}")
        return port

    comports = list_ports.comports()
    if not comports:
        raise OSError("No serial devices found")
    print("Select serial device:", file=sys.stderr)
    for i, comport in enumerate(comports):
        print(f"[{i}]: {comport.device}", file=sys.stderr)
    print(f"Enter value from 0 to {len(comports) - 1}", file=sys.stderr)
    user_input = sys.stdin.readline().strip()
    if not user_input.isdigit() or int(user_input) >= len(comports):
        raise ValueError(f'"{user_input}" invalid type or out of range')
    port = comports[int(user_input)].device
    print(f"You have selected serial port: {port}", file=sys.stderr)
    if save:
        os.environ[SERIAL_PORT_ENV] = port
    return port


def open_serial_port(port, baudrate=9600, timeout=2):
    """Open the serial port and confirm the OS will give it to us."""
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
        )
    except serial.SerialException as e:
        logger.error(f"Failed to open {port}: {e}")
        return None

    logger.info(f"Opened {port} at {baudrate} baud, is_open={ser.is_open}")
    return ser


def do_handshake(ser, retry_interval=0.2, max_attempts=20):
    """Perform the autobaud handshake. Ensure the board is in bootloader
    mode (PSEN low, EA high at reset) before this stage"""

    logger.info("Waiting for bootloader...")
    for attempt in range(max_attempts):
        ser.write(b"U")
        ser.flush()
        response = ser.read(1)  # respects the Serial timeout you set
        if response == b"U":
            logger.info(f"Handshake succeeded after {attempt + 1} attempt(s).")
            return True
        time.sleep(retry_interval)

    logger.error(
        f"Handshake failed: no 'U' echo received after {attempt + 1} attempt(s)."
    )
    return False


def ihex_checksum(body: bytes) -> int:
    """
    Compute the frame checksum per the AT89C51RB2/RC2 datasheet
    (Atmel doc. 4180E-8051-10/06), "ISP Protocol Description" ->
    "Frame Description", Table 70, pages 95-96: the checksum is the
    value that makes the sum of Reclen..Checksum equal 0 mod 256.

    `body` = Reclen + LoadOffset(2B) + RecordType + Data (NOT including
    the checksum byte itself).
    """
    return (0x100 - (sum(body) & 0xFF)) & 0xFF


def build_frame(
    record_type: int,
    data: bytes = b"",
    load_offset: int = 0x0000,
) -> bytes:
    """
    Build one ISP command frame as the ASCII byte string that actually
    goes on the wire, per Table 70 (pages 95-96):

        ':' Reclen(1B) LoadOffset(2B) RecordType(1B) Data(nB) Checksum(1B)

    Every field after ':' is encoded as a pair of ASCII hex digits per
    byte (Table 70: "Data/Info ... encoded as pairs of hexadecimal
    digits"). The datasheet's printed examples show spaces between
    fields for readability only -- on the wire it's one continuous hex
    string, per the standard Intel-Hex convention this format is based on.
    """
    if len(data) > 0xFF:
        raise ValueError("data too long for a single frame (max 255 bytes)")

    reclen = len(data)
    body = (
        bytes([reclen]) + load_offset.to_bytes(2, "big") + bytes([record_type]) + data
    )
    chk = ihex_checksum(body)
    frame = body + bytes([chk])

    return b":" + frame.hex().upper().encode("ascii")


class FrameError(Exception):
    """Raised when the bootloader's echo doesn't match what was sent,
    or when a response never arrives."""

    pass


def send_frame(
    ser,
    record_type: int,
    data: bytes = b"",
    load_offset: int = 0x0000,
    response_timeout: float = None,
) -> bytes:
    """
    Send one ISP command frame and return its raw response bytes.

    Verifies the echo byte-for-byte before trusting anything else --
    per "Command Data Stream Protocol" (page 98) and Figure 42,
    "Write/Program Flow" (pages 99-100), the bootloader echoes the
    leading ':' and then every byte of the frame as it receives it.
    A mismatch here means the bootloader did not receive what you
    think it did, and nothing past this point can be trusted.

    This function deliberately does NOT interpret the command-specific
    result that follows the echo (a read value, 'L'/'X'/'P' error
    codes, "COMMAND_OK", etc. -- see Figures 43-45, pages 101-103).
    It just reads raw bytes up through the CR LF terminator that every
    documented response flow ends with, and hands them back to you to
    parse per-command.

    response_timeout lets you override the port's configured timeout
    for slow commands -- e.g. Full Chip Erase (Table 73, page 104)
    is documented as needing ~6 seconds to complete.
    """
    frame = build_frame(record_type, data, load_offset)

    original_timeout = ser.timeout
    if response_timeout is not None:
        ser.timeout = response_timeout

    try:
        ser.reset_input_buffer()
        ser.write(frame)
        ser.flush()

        echo = ser.read(len(frame))
        if echo != frame:
            raise FrameError(f"Echo mismatch: sent {frame!r}, got {echo!r}")

        response = bytearray()
        while not response.endswith(b"\r\n"):
            b = ser.read(1)
            if not b:
                raise FrameError(
                    f"Timed out waiting for response; got {bytes(response)!r} so far"
                )
            response += b

        return bytes(response)
    finally:
        ser.timeout = original_timeout


def parse_read_response(response: bytes) -> int:
    """Shared interpreter for 'Read Function' (Record Type 05h) responses,
    per the Read Flow (Figure 45, page 103) and Checksum Error note (page 97)."""
    if response == b"L\r\n":
        raise RuntimeError(
            "Read blocked: RD_WR_SECURITY (SSB level 2) is set on this chip"
        )
    if response == b"X\r\n":
        raise RuntimeError("Bootloader reported a checksum error on our frame")
    if response.endswith(b".\r\n"):
        return int(response[:-3].decode("ascii"), 16)
    raise RuntimeError(f"Unexpected response: {response!r}")


def parse_write_response(response: bytes) -> None:
    """Shared interpreter for 'Write Function' (Record Type 03h) responses,
    per Figure 42 (pages 99-100) and the SSB behavior on page 96:
    '.' CR LF on success, 'P' if blocked by write security (SSB level 1+),
    'L' if blocked by read/write security (level 2), 'X' on checksum error."""
    if response == b".\r\n":
        return
    if response == b"P\r\n":
        raise RuntimeError("Write blocked: WRITE_SECURITY (SSB level 1) is set")
    if response == b"L\r\n":
        raise RuntimeError("Write blocked: RD_WR_SECURITY (SSB level 2) is set")
    if response == b"X\r\n":
        raise RuntimeError("Bootloader reported a checksum error on our frame")
    raise RuntimeError(f"Unexpected response: {response!r}")


def parse_intel_hex(path):
    """
    Parse a standard Intel HEX file (as produced by Keil C51 / SDCC) into a
    sparse {address: byte} dict. NOT the Atmel ISP frame format.
    Record types here mean:
        00=data,
        01=EOF,
        02=extended segment address,
        04=extended linear address.
    Checksums are verified (same rule as
    Table 70: all bytes sum to 0 mod 256).
    """
    memory = {}
    base = 0
    saw_eof = False
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            if not line.startswith(":"):
                raise ValueError(f"{path}:{lineno}: missing ':' start code")
            try:
                raw = bytes.fromhex(line[1:])
            except ValueError:
                raise ValueError(f"{path}:{lineno}: invalid hex digits")
            if len(raw) < 5 or len(raw) != raw[0] + 5:
                raise ValueError(f"{path}:{lineno}: bad record length")
            if sum(raw) & 0xFF:
                raise ValueError(f"{path}:{lineno}: checksum mismatch")
            length, offset, rtype = raw[0], int.from_bytes(raw[1:3], "big"), raw[3]
            data = raw[4:-1]
            if rtype == 0x00:
                for i in range(length):
                    memory[base + offset + i] = data[i]
            elif rtype == 0x01:
                saw_eof = True
                break
            elif rtype == 0x02:
                base = int.from_bytes(data, "big") << 4
            elif rtype == 0x04:
                base = int.from_bytes(data, "big") << 16
            elif rtype in (0x03, 0x05):
                pass  # start address records: irrelevant to an 8051 flash load
            else:
                raise ValueError(
                    f"{path}:{lineno}: unsupported record type {rtype:#04x}"
                )
    if not saw_eof:
        raise ValueError(f"{path}: no EOF record")
    if not memory:
        raise ValueError(f"{path}: no data records")
    return memory


def merge_hex_files(paths):
    """
    Parse several Intel HEX files and stitch them into one sparse
    {address: byte} map. Files may interleave or abut freely, but two files
    writing *different* values to the same address is an error; identical
    overlapping bytes are tolerated with a warning.
    """
    merged = {}
    owner = {}
    for path in paths:
        memory = parse_intel_hex(path)
        logger.info(
            "%s: %d bytes, %#06x-%#06x", path, len(memory), min(memory), max(memory)
        )
        for addr, value in memory.items():
            if addr in merged:
                if merged[addr] != value:
                    raise ValueError(
                        f"Conflict at {addr:#06x}: {owner[addr]} has "
                        f"{merged[addr]:#04x}, {path} has {value:#04x}"
                    )
                logger.warning(
                    "Duplicate identical byte at %#06x in %s and %s",
                    addr,
                    owner[addr],
                    path,
                )
            else:
                merged[addr] = value
                owner[addr] = path
    return merged


def chunk_memory(memory):
    """
    Split a sparse {address: byte} map into (address, bytes) chunks for
    Program Data frames. Each chunk is contiguous, <= 128 bytes, and never
    crosses a 128-byte page boundary (Table 73, page 104).
    """
    chunks = []
    start = None
    buf = bytearray()
    for addr in sorted(memory):
        contiguous = start is not None and addr == start + len(buf)
        same_page = contiguous and (addr % PAGE_SIZE) != 0
        if not (contiguous and same_page):
            if buf:
                chunks.append((start, bytes(buf)))
            start, buf = addr, bytearray()
        buf.append(memory[addr])
    if buf:
        chunks.append((start, bytes(buf)))
    return chunks


def pick_hex_files(directory):
    """Interactively choose one or more .hex files found under `directory`.
    Returns the list of chosen paths. Prompts on stdin, so it needs a TTY."""
    found = sorted(p for p in Path(directory).rglob("*.hex") if ".venv" not in p.parts)
    if not found:
        raise FileNotFoundError(f"No .hex files found under {directory}")
    if len(found) == 1:
        logger.info("Using %s", found[0])
        return [str(found[0])]
    print("Select hex file(s) to program:")
    for i, p in enumerate(found):
        print(f"[{i}]: {p}")
    answer = input("Enter numbers separated by spaces/commas, or 'a' for all: ")
    if answer.strip().lower() == "a":
        return [str(p) for p in found]
    try:
        picks = [int(tok) for tok in answer.replace(",", " ").split()]
        return [str(found[i]) for i in dict.fromkeys(picks)]
    except (ValueError, IndexError):
        raise ValueError(f"Invalid selection: {answer!r}")
