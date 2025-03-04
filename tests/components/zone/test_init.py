"""Test zone component."""
from unittest.mock import patch

import pytest

from homeassistant import setup
from homeassistant.components import zone
from homeassistant.components.zone import DOMAIN
from homeassistant.const import (
    ATTR_EDITABLE,
    ATTR_FRIENDLY_NAME,
    ATTR_ICON,
    ATTR_NAME,
    SERVICE_RELOAD,
)
from homeassistant.core import Context
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import entity_registry as er

from tests.common import MockConfigEntry


@pytest.fixture
def storage_setup(hass, hass_storage):
    """Storage setup."""

    async def _storage(items=None, config=None):
        if items is None:
            hass_storage[DOMAIN] = {
                "key": DOMAIN,
                "version": 1,
                "data": {
                    "items": [
                        {
                            "id": "from_storage",
                            "name": "from storage",
                            "latitude": 1,
                            "longitude": 2,
                            "radius": 3,
                            "passive": False,
                            "icon": "mdi:from-storage",
                        }
                    ]
                },
            }
        else:
            hass_storage[DOMAIN] = {
                "key": DOMAIN,
                "version": 1,
                "data": {"items": items},
            }
        if config is None:
            config = {}
        return await setup.async_setup_component(hass, DOMAIN, config)

    return _storage


async def test_setup_no_zones_still_adds_home_zone(hass):
    """Test if no config is passed in we still get the home zone."""
    assert await setup.async_setup_component(hass, zone.DOMAIN, {"zone": None})
    assert len(hass.states.async_entity_ids("zone")) == 1
    state = hass.states.get("zone.home")
    assert hass.config.location_name == state.name
    assert hass.config.latitude == state.attributes["latitude"]
    assert hass.config.longitude == state.attributes["longitude"]
    assert not state.attributes.get("passive", False)


async def test_setup(hass):
    """Test a successful setup."""
    info = {
        "name": "Test Zone",
        "latitude": 32.880837,
        "longitude": -117.237561,
        "radius": 250,
        "passive": True,
    }
    assert await setup.async_setup_component(hass, zone.DOMAIN, {"zone": info})

    assert len(hass.states.async_entity_ids("zone")) == 2
    state = hass.states.get("zone.test_zone")
    assert info["name"] == state.name
    assert info["latitude"] == state.attributes["latitude"]
    assert info["longitude"] == state.attributes["longitude"]
    assert info["radius"] == state.attributes["radius"]
    assert info["passive"] == state.attributes["passive"]


async def test_setup_zone_skips_home_zone(hass):
    """Test that zone named Home should override hass home zone."""
    info = {"name": "Home", "latitude": 1.1, "longitude": -2.2}
    assert await setup.async_setup_component(hass, zone.DOMAIN, {"zone": info})

    assert len(hass.states.async_entity_ids("zone")) == 1
    state = hass.states.get("zone.home")
    assert info["name"] == state.name


async def test_setup_name_can_be_same_on_multiple_zones(hass):
    """Test that zone named Home should override hass home zone."""
    info = {"name": "Test Zone", "latitude": 1.1, "longitude": -2.2}
    assert await setup.async_setup_component(hass, zone.DOMAIN, {"zone": [info, info]})
    assert len(hass.states.async_entity_ids("zone")) == 3


async def test_active_zone_skips_passive_zones(hass):
    """Test active and passive zones."""
    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Passive Zone",
                    "latitude": 32.880600,
                    "longitude": -117.237561,
                    "radius": 250,
                    "passive": True,
                }
            ]
        },
    )
    await hass.async_block_till_done()
    active = zone.async_active_zone(hass, 32.880600, -117.237561)
    assert active is None


async def test_active_zone_skips_passive_zones_2(hass):
    """Test active and passive zones."""
    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Active Zone",
                    "latitude": 32.880800,
                    "longitude": -117.237561,
                    "radius": 500,
                }
            ]
        },
    )
    await hass.async_block_till_done()
    active = zone.async_active_zone(hass, 32.880700, -117.237561)
    assert active.entity_id == "zone.active_zone"


async def test_active_zone_prefers_smaller_zone_if_same_distance(hass):
    """Test zone size preferences."""
    latitude = 32.880600
    longitude = -117.237561
    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Small Zone",
                    "latitude": latitude,
                    "longitude": longitude,
                    "radius": 250,
                },
                {
                    "name": "Big Zone",
                    "latitude": latitude,
                    "longitude": longitude,
                    "radius": 500,
                },
            ]
        },
    )

    active = zone.async_active_zone(hass, latitude, longitude)
    assert active.entity_id == "zone.small_zone"


async def test_active_zone_prefers_smaller_zone_if_same_distance_2(hass):
    """Test zone size preferences."""
    latitude = 32.880600
    longitude = -117.237561
    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Smallest Zone",
                    "latitude": latitude,
                    "longitude": longitude,
                    "radius": 50,
                }
            ]
        },
    )

    active = zone.async_active_zone(hass, latitude, longitude)
    assert active.entity_id == "zone.smallest_zone"


async def test_in_zone_works_for_passive_zones(hass):
    """Test working in passive zones."""
    latitude = 32.880600
    longitude = -117.237561
    assert await setup.async_setup_component(
        hass,
        zone.DOMAIN,
        {
            "zone": [
                {
                    "name": "Passive Zone",
                    "latitude": latitude,
                    "longitude": longitude,
                    "radius": 250,
                    "passive": True,
                }
            ]
        },
    )

    assert zone.in_zone(hass.states.get("zone.passive_zone"), latitude, longitude)


async def test_core_config_update(hass):
    """Test updating core config will update home zone."""
    assert await setup.async_setup_component(hass, "zone", {})

    home = hass.states.get("zone.home")

    await hass.config.async_update(
        location_name="Updated Name", latitude=10, longitude=20
    )
    await hass.async_block_till_done()

    home_updated = hass.states.get("zone.home")

    assert home is not home_updated
    assert home_updated.name == "Updated Name"
    assert home_updated.attributes["latitude"] == 10
    assert home_updated.attributes["longitude"] == 20


async def test_reload(hass, hass_admin_user, hass_read_only_user):
    """Test reload service."""
    count_start = len(hass.states.async_entity_ids())
    ent_reg = er.async_get(hass)

    assert await setup.async_setup_component(
        hass,
        DOMAIN,
        {
            DOMAIN: [
                {"name": "yaml 1", "latitude": 1, "longitude": 2},
                {"name": "yaml 2", "latitude": 3, "longitude": 4},
            ],
        },
    )

    assert count_start + 3 == len(hass.states.async_entity_ids())

    state_1 = hass.states.get("zone.yaml_1")
    state_2 = hass.states.get("zone.yaml_2")
    state_3 = hass.states.get("zone.yaml_3")

    assert state_1 is not None
    assert state_1.attributes["latitude"] == 1
    assert state_1.attributes["longitude"] == 2
    assert state_2 is not None
    assert state_2.attributes["latitude"] == 3
    assert state_2.attributes["longitude"] == 4
    assert state_3 is None
    assert len(ent_reg.entities) == 0

    with patch(
        "homeassistant.config.load_yaml_config_file",
        autospec=True,
        return_value={
            DOMAIN: [
                {"name": "yaml 2", "latitude": 3, "longitude": 4},
                {"name": "yaml 3", "latitude": 5, "longitude": 6},
            ]
        },
    ):
        with pytest.raises(Unauthorized):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_RELOAD,
                blocking=True,
                context=Context(user_id=hass_read_only_user.id),
            )
        await hass.services.async_call(
            DOMAIN,
            SERVICE_RELOAD,
            blocking=True,
            context=Context(user_id=hass_admin_user.id),
        )
        await hass.async_block_till_done()

    assert count_start + 3 == len(hass.states.async_entity_ids())

    state_1 = hass.states.get("zone.yaml_1")
    state_2 = hass.states.get("zone.yaml_2")
    state_3 = hass.states.get("zone.yaml_3")

    assert state_1 is None
    assert state_2 is not None
    assert state_2.attributes["latitude"] == 3
    assert state_2.attributes["longitude"] == 4
    assert state_3 is not None
    assert state_3.attributes["latitude"] == 5
    assert state_3.attributes["longitude"] == 6


async def test_load_from_storage(hass, storage_setup):
    """Test set up from storage."""
    assert await storage_setup()
    state = hass.states.get(f"{DOMAIN}.from_storage")
    assert state.state == "0"
    assert state.name == "from storage"
    assert state.attributes.get(ATTR_EDITABLE)


async def test_editable_state_attribute(hass, storage_setup):
    """Test editable attribute."""
    assert await storage_setup(
        config={DOMAIN: [{"name": "yaml option", "latitude": 3, "longitude": 4}]}
    )

    state = hass.states.get(f"{DOMAIN}.from_storage")
    assert state.state == "0"
    assert state.attributes.get(ATTR_FRIENDLY_NAME) == "from storage"
    assert state.attributes.get(ATTR_EDITABLE)

    state = hass.states.get(f"{DOMAIN}.yaml_option")
    assert state.state == "0"
    assert not state.attributes.get(ATTR_EDITABLE)


async def test_ws_list(hass, hass_ws_client, storage_setup):
    """Test listing via WS."""
    assert await storage_setup(
        config={DOMAIN: [{"name": "yaml option", "latitude": 3, "longitude": 4}]}
    )

    client = await hass_ws_client(hass)

    await client.send_json({"id": 6, "type": f"{DOMAIN}/list"})
    resp = await client.receive_json()
    assert resp["success"]

    storage_ent = "from_storage"
    yaml_ent = "from_yaml"
    result = {item["id"]: item for item in resp["result"]}

    assert len(result) == 1
    assert storage_ent in result
    assert yaml_ent not in result
    assert result[storage_ent][ATTR_NAME] == "from storage"


async def test_ws_delete(hass, hass_ws_client, storage_setup):
    """Test WS delete cleans up entity registry."""
    assert await storage_setup()

    input_id = "from_storage"
    input_entity_id = f"{DOMAIN}.{input_id}"
    ent_reg = er.async_get(hass)

    state = hass.states.get(input_entity_id)
    assert state is not None
    assert ent_reg.async_get_entity_id(DOMAIN, DOMAIN, input_id) is not None

    client = await hass_ws_client(hass)

    await client.send_json(
        {"id": 6, "type": f"{DOMAIN}/delete", f"{DOMAIN}_id": f"{input_id}"}
    )
    resp = await client.receive_json()
    assert resp["success"]

    state = hass.states.get(input_entity_id)
    assert state is None
    assert ent_reg.async_get_entity_id(DOMAIN, DOMAIN, input_id) is None


async def test_update(hass, hass_ws_client, storage_setup):
    """Test updating min/max updates the state."""

    items = [
        {
            "id": "from_storage",
            "name": "from storage",
            "latitude": 1,
            "longitude": 2,
            "radius": 3,
            "passive": False,
        }
    ]
    assert await storage_setup(items)

    input_id = "from_storage"
    input_entity_id = f"{DOMAIN}.{input_id}"
    ent_reg = er.async_get(hass)

    state = hass.states.get(input_entity_id)
    assert state.attributes["latitude"] == 1
    assert state.attributes["longitude"] == 2
    assert ent_reg.async_get_entity_id(DOMAIN, DOMAIN, input_id) is not None

    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 6,
            "type": f"{DOMAIN}/update",
            f"{DOMAIN}_id": f"{input_id}",
            "latitude": 3,
            "longitude": 4,
            "passive": True,
        }
    )
    resp = await client.receive_json()
    assert resp["success"]

    state = hass.states.get(input_entity_id)
    assert state.attributes["latitude"] == 3
    assert state.attributes["longitude"] == 4
    assert state.attributes["passive"] is True


async def test_ws_create(hass, hass_ws_client, storage_setup):
    """Test create WS."""
    assert await storage_setup(items=[])

    input_id = "new_input"
    input_entity_id = f"{DOMAIN}.{input_id}"
    ent_reg = er.async_get(hass)

    state = hass.states.get(input_entity_id)
    assert state is None
    assert ent_reg.async_get_entity_id(DOMAIN, DOMAIN, input_id) is None

    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 6,
            "type": f"{DOMAIN}/create",
            "name": "New Input",
            "latitude": 3,
            "longitude": 4,
            "passive": True,
        }
    )
    resp = await client.receive_json()
    assert resp["success"]

    state = hass.states.get(input_entity_id)
    assert state.state == "0"
    assert state.attributes["latitude"] == 3
    assert state.attributes["longitude"] == 4
    assert state.attributes["passive"] is True


async def test_import_config_entry(hass):
    """Test we import config entry and then delete it."""
    entry = MockConfigEntry(
        domain="zone",
        data={
            "name": "from config entry",
            "latitude": 1,
            "longitude": 2,
            "radius": 3,
            "passive": False,
            "icon": "mdi:from-config-entry",
        },
    )
    entry.add_to_hass(hass)
    assert await setup.async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert len(hass.config_entries.async_entries()) == 0

    state = hass.states.get("zone.from_config_entry")
    assert state is not None
    assert state.attributes[zone.ATTR_LATITUDE] == 1
    assert state.attributes[zone.ATTR_LONGITUDE] == 2
    assert state.attributes[zone.ATTR_RADIUS] == 3
    assert state.attributes[zone.ATTR_PASSIVE] is False
    assert state.attributes[ATTR_ICON] == "mdi:from-config-entry"


async def test_zone_empty_setup(hass):
    """Set up zone with empty config."""
    assert await setup.async_setup_component(hass, DOMAIN, {"zone": {}})


async def test_unavailable_zone(hass):
    """Test active zone with unavailable zones."""
    assert await setup.async_setup_component(hass, DOMAIN, {"zone": {}})
    hass.states.async_set("zone.bla", "unavailable", {"restored": True})

    assert zone.async_active_zone(hass, 0.0, 0.01) is None

    assert zone.in_zone(hass.states.get("zone.bla"), 0, 0) is False


async def test_state(hass):
    """Test the state of a zone."""
    info = {
        "name": "Test Zone",
        "latitude": 32.880837,
        "longitude": -117.237561,
        "radius": 250,
        "passive": True,
    }
    assert await setup.async_setup_component(hass, zone.DOMAIN, {"zone": info})

    assert len(hass.states.async_entity_ids("zone")) == 2
    state = hass.states.get("zone.test_zone")
    assert state.state == "0"

    # Person entity enters zone
    hass.states.async_set("person.person1", "test_zone")
    await hass.async_block_till_done()
    state = hass.states.get("zone.test_zone")
    assert state.state == "1"

    # Person entity enters zone
    hass.states.async_set("person.person2", "test_zone")
    await hass.async_block_till_done()
    state = hass.states.get("zone.test_zone")
    assert state.state == "2"

    # Person entity enters another zone
    hass.states.async_set("person.person1", "home")
    await hass.async_block_till_done()
    state = hass.states.get("zone.test_zone")
    assert state.state == "1"

    # Person entity removed
    hass.states.async_remove("person.person2")
    await hass.async_block_till_done()
    state = hass.states.get("zone.test_zone")
    assert state.state == "0"


async def test_state_2(hass):
    """Test the state of a zone."""
    hass.states.async_set("person.person1", "unknown")
    hass.states.async_set("person.person2", "unknown")

    info = {
        "name": "Test Zone",
        "latitude": 32.880837,
        "longitude": -117.237561,
        "radius": 250,
        "passive": True,
    }
    assert await setup.async_setup_component(hass, zone.DOMAIN, {"zone": info})

    assert len(hass.states.async_entity_ids("zone")) == 2
    state = hass.states.get("zone.test_zone")
    assert state.state == "0"

    # Person entity enters zone
    hass.states.async_set("person.person1", "test_zone")
    await hass.async_block_till_done()
    state = hass.states.get("zone.test_zone")
    assert state.state == "1"

    # Person entity enters zone
    hass.states.async_set("person.person2", "test_zone")
    await hass.async_block_till_done()
    state = hass.states.get("zone.test_zone")
    assert state.state == "2"

    # Person entity enters another zone
    hass.states.async_set("person.person1", "home")
    await hass.async_block_till_done()
    state = hass.states.get("zone.test_zone")
    assert state.state == "1"

    # Person entity removed
    hass.states.async_remove("person.person2")
    await hass.async_block_till_done()
    state = hass.states.get("zone.test_zone")
    assert state.state == "0"


async def test_state_3(hass):
    """Test the state of a zone."""
    hass.states.async_set("person.person1", "test_zone")
    hass.states.async_set("person.person2", "test_zone")

    info = {
        "name": "Test Zone",
        "latitude": 32.880837,
        "longitude": -117.237561,
        "radius": 250,
        "passive": True,
    }
    assert await setup.async_setup_component(hass, zone.DOMAIN, {"zone": info})

    assert len(hass.states.async_entity_ids("zone")) == 2
    state = hass.states.get("zone.test_zone")
    assert state.state == "2"

    # Person entity enters another zone
    hass.states.async_set("person.person1", "home")
    await hass.async_block_till_done()
    state = hass.states.get("zone.test_zone")
    assert state.state == "1"

    # Person entity removed
    hass.states.async_remove("person.person2")
    await hass.async_block_till_done()
    state = hass.states.get("zone.test_zone")
    assert state.state == "0"
