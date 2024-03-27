from typing import Any

import pytest


@pytest.fixture(scope="module")
def backend_testing_vlans_ports() -> Any:
    """Return a list of VLANs and ports for backend testing."""

    backend_testing_vlans_ports = {
        # List of ports and VLANs for backend being used actually.
        "src_port_id": "Ethernet 1",
        "dst_port_id": "Ethernet 2",
        "dst_vlan": 1798,
        "src_vlan": 1798, # Must equal to dst_vlan.
        # Parameters not used.
        "circuit_id": "circuit_id",
        "connection_id": "0000",
        "bandwidth": 1000,
    }

    yield backend_testing_vlans_ports


def pytest_addoption(parser):
    parser.addoption("--src_port_id", action="store", default="Ethernet 1")
    parser.addoption("--dst_port_id", action="store", default="Ethernet 2")
    parser.addoption("--dst_vlan", action="store", default=1799)


@pytest.fixture(scope="module")
def src_port_id(request):
    return request.config.getoption("--src_port_id")

@pytest.fixture(scope="module")
def dst_port_id(request):
    return request.config.getoption("--dst_port_id")

@pytest.fixture(scope="module")
def dst_vlan(request):
    return request.config.getoption("--dst_vlan")

# def pytest_generate_tests(metafunc):
#     # This is called for every test. Only get/set command line arguments
#     # if the argument is specified in the list of test "fixturenames".
#     option_value = metafunc.config.option.name
#     if 'src_port_id' in metafunc.fixturenames and 'dst_port_id' in metafunc.fixturenames and 'dst_vlan' in metafunc.fixturenames and option_value is not None:
#         metafunc.parametrize("name", [option_value])

