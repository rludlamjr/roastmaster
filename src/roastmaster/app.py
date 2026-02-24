"""Main application entry point and game loop.

Wires together the HAL (keyboard/GPIO input), serial device (real Kaleido or
simulator), engine (FSM, RoR, PID, events), and display (renderer) into a
single roast-control loop running at 30 fps.

Input flow:   HAL  -->  Engine  -->  Device
Display flow: Device readings  -->  Engine state  -->  Renderer
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import signal
import sys
from pathlib import Path

import pygame

from roastmaster.config import FPS, SCREEN_HEIGHT, SCREEN_WIDTH, WINDOW_TITLE
from roastmaster.display.renderer import Renderer
from roastmaster.engine.events import EventManager, EventType
from roastmaster.engine.pid import PIDController
from roastmaster.engine.roast import RoastPhase, RoastStateMachine
from roastmaster.engine.ror import RoRCalculator
from roastmaster.hal.base import InputEvent
from roastmaster.hal.keyboard import KeyboardInput
from roastmaster.profiles.manager import ProfileManager
from roastmaster.profiles.schema import ProfileEvent, ProfileSample, RoastProfile
from roastmaster.serial.protocol import RoasterDevice, RoasterReading
from roastmaster.sim.device_adapter import SimulatedRoasterDevice

# ---------------------------------------------------------------------------
# Read-only device wrapper (--test mode)
# ---------------------------------------------------------------------------


class ReadOnlyDevice:
    """Wrapper that reads from a real device but silently drops all control commands.

    Used in ``--test`` mode so the operator can verify connectivity and
    temperature readings before sending any commands to the roaster.
    """

    def __init__(self, device: RoasterDevice) -> None:
        self._device = device

    def connect(self) -> None:
        self._device.connect()

    def disconnect(self) -> None:
        self._device.disconnect()

    @property
    def connected(self) -> bool:
        return self._device.connected

    def read_temperatures(self) -> RoasterReading:
        return self._device.read_temperatures()

    def set_heater(self, power: int) -> None:
        pass  # read-only

    def set_drum(self, speed: int) -> None:
        pass  # read-only

    def set_fan(self, speed: int) -> None:
        pass  # read-only

# ---------------------------------------------------------------------------
# Roast session: bundles all engine state for a single roast
# ---------------------------------------------------------------------------


class RoastSession:
    """Coordinates engine components for one roasting session."""

    def __init__(self) -> None:
        self.fsm = RoastStateMachine()
        self.events = EventManager()
        self.ror = RoRCalculator()
        self.pid = PIDController()
        self.auto_mode = False

        # Latest readings (updated each sample)
        self.bt: float | None = None
        self.et: float | None = None
        self.current_ror: float | None = None

        # Accumulated samples for profile saving
        self.samples: list[ProfileSample] = []

    def reset(self) -> None:
        self.fsm.reset()
        self.events.reset()
        self.ror.reset()
        self.pid.reset()
        self.auto_mode = False
        self.bt = None
        self.et = None
        self.current_ror = None
        self.samples = []

    def build_profile(self) -> RoastProfile:
        """Build a RoastProfile from the current session data."""
        profile_events = [
            ProfileEvent(
                event_type=e.event_type.name,
                elapsed=e.elapsed,
                temperature=e.temperature,
            )
            for e in self.events.events
        ]
        return RoastProfile(
            samples=list(self.samples),
            events=profile_events,
        )


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------

_DEFAULT_MESSAGE = "F1:CHARGE  F2:FC  F3:SC  F4:DROP  M:MODE  Q:QUIT  F12:DEBUG"


def _handle_input(
    event: InputEvent,
    session: RoastSession,
    device: RoasterDevice,
    hal: KeyboardInput,
) -> str | None:
    """Process a single HAL input event. Returns a status message if relevant."""
    phase = session.fsm.phase
    elapsed = session.fsm.elapsed

    if event == InputEvent.CHARGE:
        if phase == RoastPhase.IDLE:
            session.fsm.start_preheat(elapsed)
            session.fsm.charge(elapsed)
        elif phase == RoastPhase.PREHEAT:
            session.fsm.charge(elapsed)
        else:
            return None
        if session.bt is not None:
            session.events.mark_event(EventType.CHARGE, elapsed, session.bt)
        return "CHARGE MARKED"

    if event == InputEvent.FIRST_CRACK:
        if phase == RoastPhase.ROASTING and session.bt is not None:
            session.events.mark_event(EventType.FIRST_CRACK, elapsed, session.bt)
            return "FIRST CRACK"
        return None

    if event == InputEvent.SECOND_CRACK:
        if phase == RoastPhase.ROASTING and session.bt is not None:
            session.events.mark_event(EventType.SECOND_CRACK, elapsed, session.bt)
            return "SECOND CRACK"
        return None

    if event == InputEvent.DROP:
        if phase == RoastPhase.ROASTING:
            session.fsm.start_cooling(elapsed)
            if session.bt is not None:
                session.events.mark_event(EventType.DROP, elapsed, session.bt)
            device.set_heater(0)
            return "DROP"
        return None

    if event == InputEvent.MODE_TOGGLE:
        session.auto_mode = not session.auto_mode
        if session.auto_mode:
            session.pid.enable()
        else:
            session.pid.disable()
        return f"MODE: {'AUTO' if session.auto_mode else 'MANUAL'}"

    if event == InputEvent.PROFILE_SAVE:
        if session.samples:
            return "SAVE"  # signal handled by main loop
        return "NO DATA TO SAVE"

    if event == InputEvent.PROFILE_LOAD:
        return "BROWSE"  # signal handled by main loop

    # Auto-transition IDLE -> PREHEAT on first burner adjustment
    if event in (InputEvent.BURNER_UP, InputEvent.BURNER_DOWN):
        if phase == RoastPhase.IDLE:
            session.fsm.start_preheat(elapsed)
            return "PREHEAT"

    return None


# ---------------------------------------------------------------------------
# Sampling & engine update
# ---------------------------------------------------------------------------


logger = logging.getLogger(__name__)

# Maximum consecutive read errors before we stop retrying within a tick
_MAX_CONSECUTIVE_ERRORS = 3


def _sample(
    session: RoastSession,
    device: RoasterDevice,
    hal: KeyboardInput,
    renderer: Renderer,
) -> None:
    """Read temperatures from device, update engine state, push to renderer."""
    reading = device.read_temperatures()
    elapsed = session.fsm.elapsed

    session.bt = reading.bean_temp
    session.et = reading.env_temp

    # Update RoR
    session.ror.add_sample(elapsed, reading.bean_temp)
    session.current_ror = session.ror.current_ror

    # Auto-detect turning point during CHARGE phase
    if session.fsm.phase == RoastPhase.CHARGE:
        tp = session.events.update_bt(elapsed, reading.bean_temp)
        if tp is not None:
            session.fsm.begin_roasting(elapsed)

    # PID auto-control: adjust heater based on RoR target
    if session.auto_mode and session.pid.active and session.current_ror is not None:
        pid_output = session.pid.compute(session.current_ror, 1.0)
        device.set_heater(int(pid_output))

    # Record sample for profile saving
    session.samples.append(
        ProfileSample(
            elapsed=elapsed,
            bt=reading.bean_temp,
            et=reading.env_temp,
            ror=session.current_ror,
            burner=float(hal.state.burner),
            drum=float(hal.state.drum),
            air=float(hal.state.air),
        )
    )

    # Push data point to renderer graph traces
    renderer.push_data(
        {
            "elapsed": elapsed,
            "bt": session.bt,
            "et": session.et,
            "ror": session.current_ror,
        }
    )


def _is_valid_reading(bt: float, et: float) -> bool:
    """Return True if the reading contains plausible sensor data."""
    if math.isnan(bt) or math.isnan(et):
        return False
    if bt < -50 or bt > 700 or et < -50 or et > 700:
        return False
    return True


def _safe_sample(
    session: RoastSession,
    device: RoasterDevice,
    hal: KeyboardInput,
    renderer: Renderer,
    error_count: int,
) -> tuple[str, int]:
    """Wrap _sample() with error handling for resilience.

    Returns:
        A (message, new_error_count) tuple.  The message is non-empty if
        the sample produced a warning; error_count tracks consecutive failures.
    """
    try:
        reading = device.read_temperatures()
    except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
        error_count += 1
        logger.warning("Read error (%d): %s", error_count, exc)
        if error_count >= _MAX_CONSECUTIVE_ERRORS:
            return "SENSOR OFFLINE", error_count
        return "READ ERROR", error_count

    bt = reading.bean_temp
    et = reading.env_temp

    if not _is_valid_reading(bt, et):
        error_count += 1
        logger.warning("Invalid reading: BT=%.1f ET=%.1f", bt, et)
        return "BAD SENSOR DATA", error_count

    # Good reading — reset error counter and proceed
    error_count = 0
    elapsed = session.fsm.elapsed

    session.bt = bt
    session.et = et

    session.ror.add_sample(elapsed, bt)
    session.current_ror = session.ror.current_ror

    if session.fsm.phase == RoastPhase.CHARGE:
        tp = session.events.update_bt(elapsed, bt)
        if tp is not None:
            session.fsm.begin_roasting(elapsed)

    if session.auto_mode and session.pid.active and session.current_ror is not None:
        pid_output = session.pid.compute(session.current_ror, 1.0)
        try:
            device.set_heater(int(pid_output))
        except (ConnectionError, OSError, RuntimeError):
            pass  # best-effort control

    session.samples.append(
        ProfileSample(
            elapsed=elapsed,
            bt=bt,
            et=et,
            ror=session.current_ror,
            burner=float(hal.state.burner),
            drum=float(hal.state.drum),
            air=float(hal.state.air),
        )
    )

    renderer.push_data(
        {
            "elapsed": elapsed,
            "bt": session.bt,
            "et": session.et,
            "ror": session.current_ror,
        }
    )

    return "", error_count


# ---------------------------------------------------------------------------
# Render data builder
# ---------------------------------------------------------------------------


def _build_render_data(
    session: RoastSession,
    hal: KeyboardInput,
    message: str,
    *,
    test_mode: bool = False,
) -> dict:
    """Build the data dict expected by the Renderer."""
    mode_tag = "AUTO" if session.auto_mode else "MANUAL"
    if test_mode:
        mode_tag = "TEST (READ ONLY)"
    status = f"{message}  |  {mode_tag}" if message else f"{_DEFAULT_MESSAGE}  |  {mode_tag}"

    return {
        "bt": session.bt,
        "et": session.et,
        "ror": session.current_ror,
        "elapsed": session.fsm.elapsed,
        "phase": session.fsm.phase.name,
        "burner": float(hal.state.burner),
        "drum": float(hal.state.drum),
        "air": float(hal.state.air),
        "message": status,
    }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _get_serial_ports() -> list[tuple[str, str]]:
    """Return a list of (device_path, description) for available serial ports."""
    from serial.tools.list_ports import comports

    return [
        (p.device, p.description if p.description != "n/a" else p.device)
        for p in sorted(comports(), key=lambda p: p.device)
    ]


def _select_device() -> str | None:
    """Interactive device selector. Returns a serial port path, or None for simulator."""
    ports = _get_serial_ports()

    print("\n  ROASTMASTER — Device Selection\n")  # noqa: T201
    print("  [0]  Simulator (no hardware)")  # noqa: T201
    for i, (path, desc) in enumerate(ports, start=1):
        label = f"{desc}  ({path})" if desc != path else path
        print(f"  [{i}]  {label}")  # noqa: T201
    print()  # noqa: T201

    while True:
        try:
            choice = input(f"  Select device [0-{len(ports)}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()  # noqa: T201
            return None
        if not choice:
            continue
        try:
            idx = int(choice)
        except ValueError:
            continue
        if idx == 0:
            return None
        if 1 <= idx <= len(ports):
            return ports[idx - 1][0]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="roastmaster",
        description="RoastMaster — retro coffee roasting control system",
    )
    parser.add_argument(
        "--device",
        metavar="PORT",
        help="Serial port for Kaleido hardware (e.g. /dev/tty.usbserial-1234). "
        "Omit to show interactive device selector.",
    )
    parser.add_argument(
        "--sim",
        action="store_true",
        help="Skip device selection and run in simulator mode",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=9600,
        help="Baud rate for serial connection (default: 9600)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Read-only test mode: connect and display temperatures but "
        "do not send any control commands to the roaster",
    )
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="List available serial ports and exit",
    )
    parser.add_argument(
        "--serial-log",
        action="store_true",
        help="Log raw Kaleido RX/TX traffic (very verbose; use for debugging)",
    )
    parser.add_argument(
        "--log-file",
        default="logs/roastmaster.log",
        help="Write logs to this file (default: logs/roastmaster.log). "
        "Pass an empty string to disable file logging.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    return parser.parse_args(argv)


def _configure_logging(*, log_file: str, level: str) -> Path | None:
    """Configure console + (optional) file logging.

    Returns the resolved log path if file logging is enabled.
    """
    import logging.handlers

    root_level = getattr(logging, level.upper(), logging.INFO)
    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handlers: list[logging.Handler] = []

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.setLevel(root_level)
    handlers.append(console)

    log_path: Path | None = None
    if log_file:
        log_path = Path(os.path.expanduser(log_file)).resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        file_handler.setLevel(logging.DEBUG)
        handlers.append(file_handler)

    logging.basicConfig(level=logging.DEBUG, handlers=handlers, force=True)
    return log_path


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    if args.list_ports:
        ports = _get_serial_ports()
        if not ports:
            print("No serial ports found.")  # noqa: T201
        else:
            print(f"{'PORT':<30} {'DESCRIPTION'}")  # noqa: T201
            print("-" * 60)  # noqa: T201
            for path, desc in ports:
                print(f"{path:<30} {desc}")  # noqa: T201
        return

    log_path = _configure_logging(log_file=str(args.log_file).strip(), level=args.log_level)
    if log_path is not None:
        logger.info("Logging to %s", log_path)

    # Determine which device to use
    serial_port: str | None = args.device
    if not serial_port and not args.sim:
        serial_port = _select_device()

    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption(WINDOW_TITLE)
    clock = pygame.time.Clock()

    renderer = Renderer(surface=screen, window_seconds=600.0)
    hal = KeyboardInput()

    device: RoasterDevice
    device_label = "SIM"
    if serial_port:
        from roastmaster.serial.kaleido import KaleidoDevice

        raw_device: RoasterDevice = KaleidoDevice(port=serial_port, baud_rate=args.baud)
        if args.serial_log and hasattr(raw_device, "set_logging"):
            try:
                raw_device.set_logging(True)  # type: ignore[attr-defined]
                logger.info("Serial traffic logging enabled")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to enable serial traffic logging: %s", exc)
        if args.test:
            device = ReadOnlyDevice(raw_device)
            logger.info("TEST MODE (read-only) on %s", serial_port)
            pygame.display.set_caption(f"{WINDOW_TITLE}  [TEST MODE - READ ONLY]")
        else:
            device = raw_device
            logger.info("Using Kaleido device on %s", serial_port)
        device_label = Path(serial_port).name or serial_port
    else:
        device = SimulatedRoasterDevice()
        logger.info("Using simulated device")
    device.connect()

    test_mode = args.test and serial_port is not None

    session = RoastSession()
    profile_mgr = ProfileManager()

    start_ticks = pygame.time.get_ticks()
    last_sample_s = -1
    message = ""
    message_expire: float = 0.0
    error_count = 0
    debug_overlay = False

    # Clean shutdown on Ctrl-C
    running = True

    def _sigint_handler(signum: int, frame: object) -> None:
        nonlocal running
        logger.info("SIGINT received, shutting down gracefully")
        running = False

    signal.signal(signal.SIGINT, _sigint_handler)

    try:
        while running:
            # 1. Update elapsed time
            elapsed_ms = pygame.time.get_ticks() - start_ticks
            session.fsm.elapsed = elapsed_ms / 1000.0

            # 2. Process input events
            for event in hal.poll_events():
                if event == InputEvent.QUIT:
                    running = False
                    break
                if event == InputEvent.HELP_TOGGLE:
                    debug_overlay = not debug_overlay
                    message = "DEBUG ON" if debug_overlay else "DEBUG OFF"
                    message_expire = session.fsm.elapsed + 2.0
                    continue

                # Profile browser intercepts input while visible
                if renderer.browser_visible:
                    if event in (InputEvent.BURNER_UP, InputEvent.NAV_UP):
                        renderer.browser.move_up()
                    elif event in (InputEvent.BURNER_DOWN, InputEvent.NAV_DOWN):
                        renderer.browser.move_down()
                    elif event == InputEvent.CONFIRM:
                        name = renderer.browser.selected_name
                        if name is not None:
                            try:
                                profile = profile_mgr.load(name)
                                renderer.set_reference_profile(profile.samples)
                                message = f"REF: {name}"
                            except (FileNotFoundError, KeyError, ValueError) as exc:
                                logger.warning("Failed to load profile %s: %s", name, exc)
                                message = "LOAD FAILED"
                            message_expire = session.fsm.elapsed + 3.0
                        renderer.hide_browser()
                    elif event == InputEvent.PROFILE_LOAD:
                        renderer.hide_browser()
                    continue

                msg = _handle_input(event, session, device, hal)
                if msg == "SAVE":
                    try:
                        profile = session.build_profile()
                        path = profile_mgr.save(profile)
                        msg = f"SAVED: {path.name}"
                    except OSError as exc:
                        logger.warning("Failed to save profile: %s", exc)
                        msg = "SAVE FAILED"
                elif msg == "BROWSE":
                    profiles = profile_mgr.list_profiles()
                    renderer.show_browser(profiles)
                    msg = None
                if msg:
                    message = msg
                    message_expire = session.fsm.elapsed + 3.0
            if not running:
                break

            # 3. Send current control state to device
            state = hal.state
            try:
                if session.fsm.phase in (RoastPhase.COOLING, RoastPhase.DONE):
                    device.set_heater(0)
                elif not session.auto_mode:
                    device.set_heater(state.burner)
                device.set_drum(state.drum)
                device.set_fan(state.air)
            except (ConnectionError, OSError, RuntimeError) as exc:
                logger.warning("Control write error: %s", exc)

            # 4. Sample temperatures at ~1 Hz (with error handling)
            current_s = int(session.fsm.elapsed)
            if current_s != last_sample_s:
                last_sample_s = current_s
                sample_msg, error_count = _safe_sample(
                    session, device, hal, renderer, error_count
                )
                if sample_msg and not message:
                    message = sample_msg
                    message_expire = session.fsm.elapsed + 3.0

            # 5. Expire status message
            if message and session.fsm.elapsed > message_expire:
                message = ""

            # 6. Render
            data = _build_render_data(session, hal, message, test_mode=test_mode)
            data["connected"] = bool(getattr(device, "connected", False))
            data["device_label"] = device_label
            data["debug_visible"] = debug_overlay
            if debug_overlay:
                conn = "ONLINE" if data["connected"] else "OFFLINE"
                lines = [
                    f"DEV: {device_label}",
                    f"CONN: {conn}",
                    f"MODE: {'TEST' if test_mode else ('AUTO' if session.auto_mode else 'MANUAL')}",
                    f"ERRS: {error_count}",
                    f"BT: {session.bt:.1f}F" if session.bt is not None else "BT: --",
                    f"ET: {session.et:.1f}F" if session.et is not None else "ET: --",
                ]
                if log_path is not None:
                    lines.append(f"LOG: {log_path.name}")
                if serial_port and args.serial_log:
                    lines.append("SERIAL: RAW LOG ON")
                data["debug_lines"] = lines
            renderer.render(data)
            pygame.display.flip()
            clock.tick(FPS)

    finally:
        # Ensure clean shutdown regardless of how we exit
        logger.info("Shutting down...")
        try:
            device.disconnect()
        except Exception:  # noqa: BLE001
            pass
        pygame.quit()

    sys.exit()


if __name__ == "__main__":
    main()
