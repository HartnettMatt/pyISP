# pyISP

A Python In-System Programmer (ISP) for 8051-family microcontrollers with the Atmel/Microchip serial bootloader (e.g. AT89C51 series). It talks to the chip's built-in bootloader over an RS-232 / USB-serial connection and programs Intel HEX files into Flash — no dedicated programmer required.

## What you need

- **[uv](https://docs.astral.sh/uv/)**, the only tool you need to install. It fetches Python 3.13+ and pyISP's dependencies for you.
- **git**, which uv uses to download pyISP
- An 8051 board with the serial bootloader, connected to your computer through a serial or USB-to-serial adapter
- One or more compiled Intel HEX (`.hex`) files

## Installation

1. **Install uv** (one time):

   ```sh
   # macOS / Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

   ```powershell
   # Windows (PowerShell)
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   Then open a new terminal so `uv` is on your `PATH`.

2. **Install pyISP**:

   ```sh
   uv tool install git+https://github.com/HartnettMatt/pyISP.git
   ```

   If `pyisp` isn't found afterward, run `uv tool update-shell` and open a new terminal.

3. **Check that it works**:

   ```sh
   pyisp --help
   ```

You don't need to create a virtual environment or run `uv init`. `uv tool install` sets up an isolated environment for pyISP automatically.

To get the latest version later:

```sh
uv tool upgrade pyisp
```

To remove it:

```sh
uv tool uninstall pyisp
```

## Finding your serial port

pyISP needs to know which serial device your board is on. You can either pick it from a list each time, or set it once with the `SERIAL_PORT_8051` environment variable.

List the available ports and choose one:

```sh
pyisp --get-port
```

Typical port names:

| OS      | Example                                  |
| ------- | ---------------------------------------- |
| macOS   | `/dev/cu.usbserial-1410`                 |
| Linux   | `/dev/ttyUSB0` (you may need to be in the `dialout` group) |
| Windows | `COM3`                                   |

To avoid being prompted every time, set the variable in your shell:

```sh
export SERIAL_PORT_8051=/dev/cu.usbserial-1410     # macOS / Linux
setx SERIAL_PORT_8051 COM3                         # Windows (open a new terminal afterward)
```

> `--save-port` only stores the selection for the current process, so it will **not** carry over to your next session. Use `export`/`setx` as shown above for a permanent setting.

## Usage

Put the board into bootloader mode (see your board's documentation — this usually means holding the ISP/PSEN button while resetting), then run:

```sh
# Probe the chip without programming anything
pyisp

# Program a hex file
pyisp path/to/program.hex

# Erase the whole chip first, then program
pyisp --erase path/to/program.hex

# Merge several hex files into one image and program it
pyisp bootstrap.hex app.hex

# Interactively choose hex file(s) from a directory tree
pyisp --pick build/

# Use a different baud rate and show detailed logging
pyisp -br 19200 -l DEBUG program.hex
```

### Options

| Option                  | Description                                                              |
| ----------------------- | ------------------------------------------------------------------------ |
| `hexfiles`              | Intel HEX file(s) to program, merged into one image. Omit to only probe the chip. |
| `--pick DIR`            | Interactively choose hex file(s) found under `DIR`.                      |
| `-br`, `--baud-rate N`  | Baud rate (default `9600`).                                              |
| `-e`, `--erase`         | Full chip erase before programming. **Destructive** — takes about 6 s.   |
| `--get-port`            | Print the serial device that would be used and exit.                     |
| `--save-port`           | Store a prompted port selection in `SERIAL_PORT_8051` (current process only). |
| `-l`, `--log-level L`   | `DEBUG`, `INFO` (default), `WARNING`, `ERROR`, or `CRITICAL`.            |

## Troubleshooting

- **"No serial devices found"** — check the cable/adapter and drivers (e.g. FTDI or CH340 on Windows/macOS), then run `--get-port` again.
- **Permission denied on Linux** — add yourself to the serial group and log back in: `sudo usermod -aG dialout $USER`.
- **Handshake fails / no response** — the board is probably not in bootloader mode. Reset it into ISP mode and retry. Make sure no other program (serial monitor, IDE) has the port open.
- **"Hex file reaches ... beyond Flash end"** — your program is larger than the chip's Flash (default limit `0x7FFF`).
- **Chip keeps booting into the bootloader** — programming must finish fully so the boot status byte gets set; re-run the programming step and watch the log for errors (`-l DEBUG` helps).
- **Anything else** — rerun with `-l DEBUG` and include the output when asking for help.

## Development

To work on pyISP itself, clone the repository and run it from source with uv:

```sh
git clone https://github.com/HartnettMatt/pyISP.git
cd pyISP
uv sync
uv run pyisp --help
```

## Project layout

| File         | Purpose                                                        |
| ------------ | -------------------------------------------------------------- |
| `cli.py`     | Command-line entry point and argument parsing                  |
| `program.py` | Bootloader operations: erase, blank check, program, reset      |
| `utils.py`   | Serial port handling, framing/checksums, Intel HEX parsing     |

## License

See [LICENSE](LICENSE).
