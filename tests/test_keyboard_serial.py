"""验证 Windows 键码解析、主程序分派和假串口的停车行为。"""

from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call

import pytest
import serial

import hand_eye_preview
from interaction import keyboard_serial
from test_serial_link import FakeSerial, make_link, movement_letters


@pytest.mark.parametrize(("options", "answers", "open_error"), [
    ([], [""], False),
    ([], ["2", "COM9"], False),
    ([], ["2", "COM9"], True),
    (["--port", "COM9"], [], False),
])
def test_standalone_keyboard_uses_selected_output_mode(monkeypatch, capsys, options, answers, open_error):
    project = Path(__file__).resolve().parents[1]
    path = project / "firmware/eye_gesture_control/ardino_demo/serial_wsad/keyboard_serial.py"
    main = runpy.run_path(str(path))["main"]
    keys = Mock(side_effect=[{"F"}, {"F"}, set(), {"ESC"}])
    monkeypatch.setitem(main.__globals__, "make_key_reader", lambda: keys)
    monkeypatch.setitem(main.__globals__, "time", SimpleNamespace(sleep=Mock(), monotonic=lambda: 0.0))
    monkeypatch.setattr(sys, "argv", [str(path), *options])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", Mock(side_effect=answers))
    port = MagicMock(in_waiting=0)
    port.__enter__.return_value = port
    port.write.side_effect = len
    open_port = Mock(return_value=port, side_effect=serial.SerialException("test error") if open_error else None)
    monkeypatch.setattr(serial, "Serial", open_port)

    assert main() == 0

    output = capsys.readouterr().out
    if options or answers[0] == "2":
        open_port.assert_called_once_with("COM9", 9600, timeout=0, write_timeout=0.5)
    else:
        open_port.assert_not_called()
    if open_port.called and not open_error:
        assert port.write.call_args_list == [call(b"S"), call(b"F"), call(b"S"), call(b"S")]
        port.flush.assert_called_once()
        port.__exit__.assert_called_once()
        assert "[TX] F" in output
    else:
        port.write.assert_not_called()
        assert "[模拟] 指令 F" in output
        if open_error:
            assert "test error" in output


def test_read_key_decodes_extended_arrows_and_letters():
    console = SimpleNamespace(
        kbhit=Mock(side_effect=[False, True, True, True, True]),
        getwch=Mock(side_effect=["\xe0", "H", "\x00", "K", "\xe0", "X", "R"]),
    )
    assert [keyboard_serial.read_key(console) for _ in range(5)] == [None, "up", "left", None, "r"]


def test_keyboard_cli_routes_to_console_mode_with_serial_port(monkeypatch):
    run = Mock()
    monkeypatch.setattr(keyboard_serial, "main", run)
    monkeypatch.setattr(sys, "argv", [
        hand_eye_preview.__file__, "--keyboard", "--serial-port", "COM9", "--firmware", "motor-test",
    ])

    runpy.run_path(hand_eye_preview.__file__, run_name="__main__")

    run.assert_called_once_with("COM9", firmware="motor-test")


def test_keyboard_sends_commands_and_stops_when_input_expires_or_exits(monkeypatch, capsys):
    port = FakeSerial()
    link = keyboard_serial.WheelchairLink("COM9", firmware="wheelchair", port_factory=lambda *args, **kwargs: port)
    transport = Mock(return_value=link)
    keys = ["up", "up", None, None, "right", "down", "left", "q"]
    times = Mock(side_effect=[0.0, 0.4, 0.8, 1.12, 1.14, 1.16, 1.18])
    monkeypatch.setattr(keyboard_serial, "sys", SimpleNamespace(platform="win32", stdin=Mock(isatty=lambda: True)))
    monkeypatch.setitem(sys.modules, "msvcrt", Mock())
    monkeypatch.setattr(keyboard_serial, "WheelchairLink", transport)
    monkeypatch.setattr(keyboard_serial, "time", SimpleNamespace(perf_counter=times, sleep=Mock()))
    monkeypatch.setattr(keyboard_serial, "read_key", Mock(side_effect=keys))

    keyboard_serial.main("COM9", firmware="wheelchair")

    transport.assert_called_once_with("COM9", firmware="wheelchair")
    assert movement_letters(port) == ["S", "F", "S", "R", "S", "L", "S"]
    assert "[串口 COM9] 已发送 F" in capsys.readouterr().out
    assert port.closed


def test_keyboard_checks_low_battery_before_sending_direction(monkeypatch):
    link, port = make_link(rx=b"BATTERY:10,188\n")
    monkeypatch.setattr(keyboard_serial, "time", SimpleNamespace(perf_counter=lambda: 0.0, sleep=Mock()))
    monkeypatch.setattr(keyboard_serial, "read_key", Mock(side_effect=["w", "q"]))
    try:
        keyboard_serial.run_keyboard(Mock(), link)
        assert movement_letters(port) == ["S"]
    finally:
        link.close()


def test_motor_test_keyboard_uses_digit_keys_and_ignores_turns(monkeypatch):
    link, port = make_link(firmware="motor-test")
    keys = Mock(side_effect=["left", "1", "right", "s", "2", "q"])
    times = Mock(side_effect=[0.0, 0.1, 0.3, 0.5, 1.2])
    monkeypatch.setattr(keyboard_serial, "read_key", keys)
    monkeypatch.setattr(keyboard_serial, "time", SimpleNamespace(perf_counter=times, sleep=Mock()))
    try:
        keyboard_serial.run_keyboard(Mock(), link)
    finally:
        link.close()
    assert port.tx == [b"1", b"S", b"2", b"S"]
