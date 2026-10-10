import logging

from utils import (
    FLASH_END,
    PAGE_SIZE,
    FrameError,
    build_frame,
    chunk_memory,
    parse_read_response,
    parse_write_response,
    send_frame,
)

logger = logging.getLogger(__name__)


def read_sbv(ser):
    """Read the Software Boot Vector via send_frame, and interpret the result."""
    response = send_frame(ser, record_type=0x05, data=bytes([0x07, 0x02]))
    sbv = parse_read_response(response)
    logger.debug("SBV = %#04x", sbv)
    return sbv


def read_id(ser):
    """Read the Manufactuer and Device ID via send_frame, and interpret the result."""
    id_dict = {
        "Manufactuer's ID:": 0x00,
        "Device ID 1:": 0x01,
        "Device ID 2:": 0x02,
        "Device ID 3:": 0x03,
    }
    for k, v in id_dict.items():
        response = send_frame(ser, record_type=0x05, data=bytes([0x00, v]))
        id = parse_read_response(response)
        logger.debug("%s = %#04x", k, id)


def blank_check(ser, start=0x0000, end=FLASH_END):
    """
    Blank Check (Record Type 04h, Data[4]=01h), per Table 73 (page 104)
    and Figure 43 (page 101). Data = start addr (2B, big-endian) +
    end addr (2B) + 0x01.

    Returns None if the range is blank ('.' CR LF), or the address of the
    first non-erased byte ('xxxx' CR LF) -- the bootloader aborts at the
    first mismatch. Raises RuntimeError on 'X' (checksum error).
    """
    data = start.to_bytes(2, "big") + end.to_bytes(2, "big") + b"\x01"
    response = send_frame(ser, record_type=0x04, data=data)
    if response == b".\r\n":
        logger.info("Flash %#06x-%#06x is blank", start, end)
        return None
    if response == b"X\r\n":
        raise RuntimeError("Bootloader reported a checksum error on our frame")
    try:
        addr = int(response[:-2].decode("ascii"), 16)
    except ValueError:
        raise RuntimeError(f"Unexpected blank check response: {response!r}")
    logger.info("Flash not blank: first non-erased byte at %#06x", addr)
    return addr


def chip_erase(ser, timeout=10.0):
    """
    Full Chip Erase (Record Type 03h, Data[0]=07h), per Table 73 (page 104).
    Erases all Flash and resets the SSB. Table 73 says it needs about 6 s,
    so the response timeout is raised well above that. DESTRUCTIVE.
    """
    logger.info("Erasing chip (takes ~6 s)...")
    response = send_frame(
        ser, record_type=0x03, data=bytes([0x07]), response_timeout=timeout
    )
    parse_write_response(response)
    logger.info("Chip erase complete")


def program_data(ser, address, data):
    """Program Data (Record Type 00h), per Table 73 (page 104) and the
    worked example on page 100. LoadOffset carries the Flash address."""
    if not 0 < len(data) <= PAGE_SIZE:
        raise ValueError("Program Data frame must carry 1-128 bytes")
    if address // PAGE_SIZE != (address + len(data) - 1) // PAGE_SIZE:
        raise ValueError("Program Data frame must not cross a 128-byte page")
    response = send_frame(ser, record_type=0x00, data=data, load_offset=address)
    parse_write_response(response)


def program_flash(ser, memory):
    """Program every chunk of `memory`, which must fit in Flash."""
    top = max(memory)
    if top > FLASH_END:
        raise ValueError(
            f"Hex file reaches {top:#06x}, beyond Flash end {FLASH_END:#06x}"
        )
    chunks = chunk_memory(memory)
    logger.info("Programming %d bytes in %d frames", len(memory), len(chunks))
    for i, (addr, data) in enumerate(chunks, 1):
        logger.debug("Frame %d/%d: %#06x (%d bytes)", i, len(chunks), addr, len(data))
        program_data(ser, addr, data)
    logger.info("Programming complete")


def program_bsb(ser, value=0x00):
    """
    Program the Boot Status Byte (Record Type 03h, Data=[06h, 00h, value]),
    per Table 73 (page 104) and the worked example on page 100.

    Required after ISP programming: Full Chip Erase leaves BSB=FFh (page 97),
    and the bootloader only jumps to the application at 0000h when BSB=00h
    (page 89, Figure 39 on page 94). Without this the chip keeps booting
    into the bootloader on every reset.
    """
    response = send_frame(ser, record_type=0x03, data=bytes([0x06, 0x00, value]))
    parse_write_response(response)
    logger.debug("BSB set to %#04x", value)


def hardware_reset(ser):
    """
    Hardware Reset (Record Type 03h, Data=[03h, 00h]), Table 73 (page 104):
    starts the user application. The bootloader jumps away, so a trailing
    '.' may or may not arrive; only the echo is required.
    """
    frame = build_frame(0x03, bytes([0x03, 0x00]))
    ser.reset_input_buffer()
    ser.write(frame)
    ser.flush()
    echo = ser.read(len(frame))
    if echo != frame:
        raise FrameError(f"Echo mismatch: sent {frame!r}, got {echo!r}")
    logger.info("Hardware reset sent")
