import io
import json
from unittest.mock import patch

import pytest

from backend import launcher


def response(current, state):
    return io.BytesIO(json.dumps({'current': current, 'progress': {'state': state}}).encode())


def test_windows_launcher_waits_until_old_updating_collector_stops():
    with patch.object(launcher.LOCAL, 'open', return_value=response('1.4.0', 'restarting')), \
         patch.object(launcher, 'healthy', side_effect=[True, False]) as healthy, \
         patch.object(launcher.time, 'sleep'):
        assert launcher.wait_for_previous_update('http://127.0.0.1:8765')
    assert healthy.call_count == 2


@pytest.mark.parametrize(('current', 'state'), [('1.5.0', 'restarting'), ('1.4.0', 'idle')])
def test_windows_launcher_does_not_wait_for_unrelated_collector(current, state):
    with patch.object(launcher.LOCAL, 'open', return_value=response(current, state)), \
         patch.object(launcher, 'healthy') as healthy:
        assert launcher.wait_for_previous_update('http://127.0.0.1:8765')
    healthy.assert_not_called()


def test_windows_launcher_stops_waiting_at_deadline():
    with patch.object(launcher.LOCAL, 'open', return_value=response('1.4.0', 'restarting')), \
         patch.object(launcher, 'healthy', return_value=True), \
         patch.object(launcher.time, 'monotonic', side_effect=[0, launcher.STARTUP_SECONDS]), \
         patch.object(launcher.time, 'sleep'):
        assert not launcher.wait_for_previous_update('http://127.0.0.1:8765')


def test_windows_update_launcher_starts_after_previous_collector_stops():
    with patch.object(launcher.sys, 'platform', 'win32'), \
         patch.object(launcher, 'healthy', side_effect=[True, False, True]), \
         patch.object(launcher, 'wait_for_previous_update', return_value=True) as wait, \
         patch.object(launcher, 'spawn') as spawn:
        assert launcher.main(['--no-open', '--port', '8765']) == 0
    wait.assert_called_once_with('http://127.0.0.1:8765')
    spawn.assert_called_once_with(8765)
