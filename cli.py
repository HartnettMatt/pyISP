import argparse
import logging
from pathlib import Path

from main import main as run
from utils import get_serial_port, pick_hex_files

logger = logging.getLogger(__name__)

BAUD_RATE = 9600  # default, overridable with command line arg


def parse_args():
    parser = argparse.ArgumentParser(
        description="Python based 8051 ISP programmer over RS232"
    )
    parser.add_argument(
        "hexfiles",
        nargs="*",
        help="Intel HEX file(s) to program, merged into one image "
        "(omit to only probe the chip)",
    )
    parser.add_argument(
        "--pick",
        metavar="DIR",
        help="Interactively choose hex file(s) from those found under DIR",
    )
    parser.add_argument(
        "-br",
        "--baud-rate",
        type=int,
        default=BAUD_RATE,
        help="Baud rate",
    )
    parser.add_argument(
        "-e",
        "--erase",
        action="store_true",
        help="Perform a full chip erase (destructive) before any programming",
    )
    parser.add_argument(
        "--get-port",
        action="store_true",
        help="Print the serial device to use (SERIAL_PORT_8051, or prompt) and exit",
    )
    parser.add_argument(
        "--save-port",
        action="store_true",
        help="Store a prompted serial device selection in SERIAL_PORT_8051",
    )
    parser.add_argument(
        "-l",
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity (default: INFO)",
    )
    args = parser.parse_args()

    for hexfile in args.hexfiles:
        if not Path(hexfile).is_file():
            parser.error(f"hex file not found: {hexfile}")
    if args.pick and not Path(args.pick).is_dir():
        parser.error(f"--pick directory not found: {args.pick}")
    if args.baud_rate <= 0:
        parser.error(f"baud rate must be positive: {args.baud_rate}")
    return args


def main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="[%(levelname)s] %(message)s",
    )
    if args.get_port:
        try:
            print(get_serial_port(save=args.save_port))
        except (OSError, ValueError) as e:
            logger.error("%s", e)
            raise SystemExit(1)
        return
    if args.pick:
        try:
            args.hexfiles += pick_hex_files(args.pick)
        except (OSError, ValueError) as e:
            logger.error("%s", e)
            return
    run(args.hexfiles, args.baud_rate, args.erase, args.save_port)


if __name__ == "__main__":
    main()
