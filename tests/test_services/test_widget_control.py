import json

import pytest

from backend.services import widget_control
from backend.services.widget_control import Widget


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Process:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


class Spawner:
    def __init__(self):
        self.calls, self.process = [], Process()

    def __call__(self, command, **options):
        self.calls.append((command, options))
        return self.process


def make(tmp_path, available=True):
    clock, spawn = Clock(), Spawner()
    widget = Widget(tmp_path, ['widget', '--float'], spawn=spawn, clock=clock, available=lambda: available)
    return widget, clock, spawn


def test_defaults_to_off_and_persists(tmp_path):
    widget, _, spawn = make(tmp_path)
    assert widget.status()['enabled'] is False
    widget.ensure()
    assert spawn.calls == []
    widget.set_enabled(True)
    assert json.loads((tmp_path / 'widget.json').read_text()) == {'enabled': True}
    assert Widget(tmp_path, ['w'], spawn=spawn, clock=Clock(), available=lambda: True).status()['enabled'] is True


@pytest.mark.parametrize('value', ['yes', 1, None, [True]])
def test_set_enabled_requires_a_boolean(tmp_path, value):
    widget, _, _ = make(tmp_path)
    with pytest.raises(ValueError):
        widget.set_enabled(value)
    assert not (tmp_path / 'widget.json').exists()


def test_corrupt_file_means_off(tmp_path):
    (tmp_path / 'widget.json').write_text('{nope')
    assert make(tmp_path)[0].status()['enabled'] is False


def test_enabling_starts_one_detached_process(tmp_path):
    widget, clock, spawn = make(tmp_path)
    widget.set_enabled(True)
    assert len(spawn.calls) == 1
    command, options = spawn.calls[0]
    assert command == ['widget', '--float']
    assert options['stdin'] is not None and options['close_fds'] is True
    assert ('start_new_session' in options) or ('creationflags' in options)
    widget.ensure()
    clock.now += 29
    widget.ensure()
    assert len(spawn.calls) == 1


def test_no_second_process_while_the_first_lives(tmp_path):
    widget, clock, spawn = make(tmp_path)
    widget.set_enabled(True)
    clock.now += 600
    widget.ensure()
    assert len(spawn.calls) == 1


def test_touch_marks_running_then_expires(tmp_path):
    widget, clock, spawn = make(tmp_path)
    widget.set_enabled(True)
    widget.touch()
    assert widget.status()['running'] is True
    clock.now += 31
    assert widget.status()['running'] is False


def test_restarts_after_a_clean_exit(tmp_path):
    widget, clock, spawn = make(tmp_path)
    widget.set_enabled(True)
    spawn.process.code = 0
    clock.now += 60
    spawn.process = Process()
    widget.ensure()
    assert len(spawn.calls) == 2


def test_duplicate_exit_code_is_not_a_failure(tmp_path):
    widget, clock, spawn = make(tmp_path)
    widget.set_enabled(True)
    for _ in range(5):
        spawn.process.code = widget_control.ALREADY_RUNNING
        clock.now += 1
        spawn.process = Process()
        widget.ensure()
    assert widget.status()['error'] is None


def test_three_early_crashes_stop_the_restarts(tmp_path):
    widget, clock, spawn = make(tmp_path)
    widget.set_enabled(True)
    for _ in range(3):
        spawn.process.code = 1
        clock.now += 1
        spawn.process = Process()
        widget.ensure()
    assert widget.status()['error']
    assert len(spawn.calls) == 3
    clock.now += 600
    widget.ensure()
    assert len(spawn.calls) == 3
    widget.set_enabled(True)
    assert widget.status()['error'] is None
    assert len(spawn.calls) == 4


def test_late_crash_is_not_counted(tmp_path):
    widget, clock, spawn = make(tmp_path)
    widget.set_enabled(True)
    for _ in range(4):
        clock.now += 60
        spawn.process.code = 1
        spawn.process = Process()
        widget.ensure()
    assert widget.status()['error'] is None


def test_unavailable_runtime_never_spawns(tmp_path):
    widget, _, spawn = make(tmp_path, available=False)
    widget.set_enabled(True)
    status = widget.status()
    assert spawn.calls == []
    assert status['available'] is False and status['reason']


def test_spawn_failure_is_reported_not_raised(tmp_path):
    def broken(command, **options):
        raise OSError('no such file')

    widget = Widget(tmp_path, ['w'], spawn=broken, clock=Clock(), available=lambda: True)
    widget.set_enabled(True)
    assert 'no such file' in widget.status()['error']


def test_command_matches_how_the_collector_is_spawned(tmp_path):
    command = widget_control.command(8765)
    assert command[-3:] == ['--float', '--port', '8765']


def test_spawned_widget_is_marked_managed(tmp_path):
    widget, _, spawn = make(tmp_path)
    widget.set_enabled(True)
    assert spawn.calls[0][1]['env'][widget_control.MANAGED] == '1'


def test_turning_it_back_on_after_the_widget_exited_restarts_at_once(tmp_path):
    widget, clock, spawn = make(tmp_path)
    widget.set_enabled(True)
    widget.touch()
    clock.now += 12                      # the widget polled recently, so it still counts as running
    widget.set_enabled(False)
    spawn.process.code = 0               # ...then it closed itself because the setting is off
    clock.now += 3
    spawn.process = Process()
    widget.set_enabled(True)
    assert len(spawn.calls) == 2
