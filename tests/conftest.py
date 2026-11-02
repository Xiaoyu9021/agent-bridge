import pytest
from fastapi.testclient import TestClient

from codex_bridge.config import Settings
from codex_bridge.models import DeviceInput
from codex_bridge.server.app import create_app
from codex_bridge.server.control import HostControl
from codex_bridge.storage.store import Store


@pytest.fixture
def bridge(tmp_path):
    settings = Settings(tmp_path / "host", max_file_bytes=1024**2, max_task_bytes=2 * 1024**2)
    store = Store(settings)
    host = DeviceInput(display_name="Windows 主管", platform="windows")
    control = HostControl(store, host)
    mac = DeviceInput(display_name="Mac 执行端", platform="macos")
    other = DeviceInput(display_name="Other", platform="linux")
    mac_token = store.register(mac)
    other_token = store.register(other)
    with TestClient(create_app(control)) as api:
        yield {
            "api": api, "store": store, "control": control, "host": host, "mac": mac, "other": other,
            "host_headers": {"Authorization": "Bearer " + control.token},
            "mac_headers": {"Authorization": "Bearer " + mac_token},
            "other_headers": {"Authorization": "Bearer " + other_token},
        }
