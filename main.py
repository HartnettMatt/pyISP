import logging

from program import (
    blank_check,
    chip_erase,
    hardware_reset,
    program_bsb,
    program_flash,
    read_id,
    read_sbv,
)
from utils import (
    FrameError,
    do_handshake,
    get_serial_port,
    merge_hex_files,
    open_serial_port,
)

logger = logging.getLogger(__name__)


def main(hexfiles, baud_rate, erase, save_port):
    try:
        ser_port = get_serial_port(save=save_port)
    except (OSError, ValueError) as e:
        logger.error("%s", e)
        return
    ser = open_serial_port(ser_port, baudrate=baud_rate)
    if ser is None:
        return
    try:
        if not do_handshake(ser):
            logger.error("Handshake failed, aborting.")
            return
        read_sbv(ser)
        read_id(ser)
        memory = merge_hex_files(hexfiles) if hexfiles else None
        blank = blank_check(ser) is None
        if erase:
            chip_erase(ser)
            if blank_check(ser) is not None:
                raise RuntimeError("Flash not blank after chip erase")
            blank = True
        if memory is not None:
            if not blank:
                raise RuntimeError("Flash is not blank; re-run with --erase")
            program_flash(ser, memory)
            program_bsb(ser, 0x00)
            hardware_reset(ser)
            logger.info("Application should be running, may require manual reset")
    except (FrameError, RuntimeError, ValueError, OSError) as e:
        logger.error("Program failed: %s", e)
    except KeyboardInterrupt:
        logger.info("Interrupted by user, closing serial port.")
    if ser.is_open:
        ser.close()
        logger.info("Closed %s", ser.port)
