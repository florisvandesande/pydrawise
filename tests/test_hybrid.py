import asyncio
import time
from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import call, create_autospec

from freezegun import freeze_time
from pytest import fixture

from pydrawise.auth import HybridAuth
from pydrawise.client import Hydrawise
from pydrawise.hybrid import HybridClient, ThrottleConfig, Throttler
from pydrawise.schema import Zone

FROZEN_TIME = "2023-01-01 01:00:00"


@fixture
def hybrid_auth():
    mock_auth = create_autospec(HybridAuth, instance=True, api_key="__api_key__")
    mock_auth.token.return_value = "__token__"
    yield mock_auth


@fixture
def mock_gql_client():
    yield create_autospec(Hydrawise, instance=True, spec_set=True)


@fixture
def api(hybrid_auth, mock_gql_client):
    yield HybridClient(
        hybrid_auth,
        gql_client=mock_gql_client,
        gql_throttle=Throttler(
            epoch_interval=timedelta(minutes=30), tokens_per_epoch=2
        ),
        rest_throttle=Throttler(
            epoch_interval=timedelta(minutes=1), tokens_per_epoch=2
        ),
    )


def test_throttler():
    with freeze_time(FROZEN_TIME) as frozen_time:
        throttle = Throttler(epoch_interval=timedelta(seconds=60))
        assert throttle.check()
        throttle.mark()
        assert not throttle.check()

        # Increasing tokens_per_epoch allows another token to be consumed
        throttle.tokens_per_epoch = 2
        assert throttle.check()

        # Advancing time resets the throttler, allowing 2 tokens again
        frozen_time.tick(timedelta(seconds=61))
        assert throttle.check(2)


def test_custom_throttle_kwargs(hybrid_auth, mock_gql_client):
    api = HybridClient(
        hybrid_auth,
        gql_client=mock_gql_client,
        gql_throttle={
            "epoch_interval": timedelta(minutes=10),
            "tokens_per_epoch": 3,
        },
        rest_throttle={
            "epoch_interval": timedelta(seconds=30),
            "tokens_per_epoch": 4,
        },
    )
    assert api._gql_throttle.epoch_interval == timedelta(minutes=10)
    assert api._gql_throttle.tokens_per_epoch == 3
    assert api._rest_throttle.epoch_interval == timedelta(seconds=30)
    assert api._rest_throttle.tokens_per_epoch == 4


def test_custom_throttle_config(hybrid_auth, mock_gql_client):
    cfg = ThrottleConfig(epoch_interval=timedelta(minutes=5), tokens_per_epoch=6)
    api = HybridClient(
        hybrid_auth,
        gql_client=mock_gql_client,
        rest_throttle=cfg,
    )
    assert api._rest_throttle.epoch_interval == timedelta(minutes=5)
    assert api._rest_throttle.tokens_per_epoch == 6


async def test_get_user(api, hybrid_auth, mock_gql_client, user, zone, status_schedule):
    with freeze_time(FROZEN_TIME):
        user.controllers[0].zones = [zone]
        assert user.controllers[0].zones[0].status.suspended_until != datetime.max

        # First fetch should query the GraphQL API
        mock_gql_client.get_user.return_value = deepcopy(user)
        assert await api.get_user() == user
        mock_gql_client.get_user.assert_awaited_once_with(fetch_zones=True)

        # Second fetch should also query the GraphQL API
        mock_gql_client.get_user.reset_mock()
        assert await api.get_user() == user
        mock_gql_client.get_user.assert_awaited_once_with(fetch_zones=True)

        # Third fetch should query the REST API because we're out of tokens
        mock_gql_client.get_user.reset_mock()
        status_schedule["relays"] = [status_schedule["relays"][0]]
        status_schedule["relays"][0]["time"] = 1576800000
        status_schedule["relays"][0]["name"] = "Zone A from REST API"
        hybrid_auth.get.return_value = status_schedule
        user2 = await api.get_user()
        mock_gql_client.get_user.assert_not_awaited()
        hybrid_auth.get.assert_awaited_once_with(
            "statusschedule.php", controller_id=user.controllers[0].id
        )
        assert user2.controllers[0].zones[0].status.suspended_until == datetime.max
        assert user2.controllers[0].zones[0].name == "Zone A"

        # Fourth fetch should query the REST API again
        hybrid_auth.get.reset_mock()
        assert await api.get_user() == user2
        mock_gql_client.get_user.assert_not_awaited()
        hybrid_auth.get.assert_awaited_once_with(
            "statusschedule.php", controller_id=user.controllers[0].id
        )

        # Fifth fetch should not make any calls and instead return cached data
        hybrid_auth.get.reset_mock()
        assert await api.get_user() == user2
        mock_gql_client.get_user.assert_not_awaited()
        hybrid_auth.get.assert_not_awaited()


async def test_get_controllers(
    api, hybrid_auth, mock_gql_client, controller, zone, status_schedule
):
    with freeze_time(FROZEN_TIME) as frozen_time:
        controller.zones = [deepcopy(zone)]
        assert controller.zones[0].status.suspended_until != datetime.max

        # First fetch should query the GraphQL API
        mock_gql_client.get_controllers.return_value = [deepcopy(controller)]
        assert await api.get_controllers() == [controller]
        mock_gql_client.get_controllers.assert_awaited_once_with(True, True)

        # Second fetch should also query the GraphQL API
        mock_gql_client.get_controllers.reset_mock()
        assert await api.get_controllers() == [controller]
        mock_gql_client.get_controllers.assert_awaited_once_with(True, True)

        # Third fetch should query the REST API because we're out of tokens
        mock_gql_client.get_controllers.reset_mock()
        status_schedule["relays"] = [status_schedule["relays"][0]]
        status_schedule["relays"][0]["time"] = 1576800000
        status_schedule["relays"][0]["name"] = "Zone A from REST API"
        hybrid_auth.get.return_value = status_schedule
        [controller2] = await api.get_controllers()
        mock_gql_client.get_controllers.assert_not_awaited()
        hybrid_auth.get.assert_awaited_once_with(
            "statusschedule.php", controller_id=controller.id
        )
        assert controller2.zones[0].status.suspended_until == datetime.max
        assert controller2.zones[0].name == "Zone A"

        # Fourth fetch should query the REST API again
        hybrid_auth.get.reset_mock()
        assert await api.get_controllers() == [controller2]
        mock_gql_client.get_controllers.assert_not_awaited()
        hybrid_auth.get.assert_awaited_once_with(
            "statusschedule.php", controller_id=controller.id
        )

        # Fifth fetch should not make any calls and instead return cached data
        hybrid_auth.get.reset_mock()
        assert await api.get_controllers() == [controller2]
        mock_gql_client.get_controllers.assert_not_awaited()
        hybrid_auth.get.assert_not_awaited()

        # After 1 minute, we can query the REST API again.
        # But it thinks we're polling too fast and tells us to back off.
        # Make sure that we listen.
        frozen_time.tick(timedelta(seconds=61))
        hybrid_auth.get.reset_mock()
        status_schedule["nextpoll"] = 120
        assert await api.get_controllers() == [controller2]
        mock_gql_client.get_controllers.assert_not_awaited()
        hybrid_auth.get.assert_awaited_once_with(
            "statusschedule.php", controller_id=controller.id
        )
        # We can still make one more call
        hybrid_auth.get.reset_mock()
        assert await api.get_controllers() == [controller2]
        mock_gql_client.get_controllers.assert_not_awaited()
        hybrid_auth.get.assert_awaited_once_with(
            "statusschedule.php", controller_id=controller.id
        )
        # Now we have to return cached data until the throttler resets.
        hybrid_auth.get.reset_mock()
        assert await api.get_controllers() == [controller2]
        mock_gql_client.get_controllers.assert_not_awaited()
        hybrid_auth.get.assert_not_awaited()

        # Allow the throttler to refresh. Now we can make more calls.
        frozen_time.tick(timedelta(seconds=121))
        hybrid_auth.get.reset_mock()
        assert await api.get_controllers() == [controller2]
        mock_gql_client.get_controllers.assert_not_awaited()
        hybrid_auth.get.assert_awaited_once_with(
            "statusschedule.php", controller_id=controller.id
        )


async def test_get_controllers_many(
    api, hybrid_auth, mock_gql_client, controllers, status_schedule
):
    with freeze_time(FROZEN_TIME):
        mock_gql_client.get_controllers.return_value = deepcopy(controllers)
        result = await api.get_controllers()
        mock_gql_client.get_controllers.assert_awaited_once_with(True, True)
        assert result == controllers
        assert api._rest_throttle.tokens_per_epoch == len(controllers) + 1

        mock_gql_client.get_controllers.reset_mock()
        assert await api.get_controllers() == controllers
        mock_gql_client.get_controllers.assert_awaited_once_with(True, True)

        mock_gql_client.get_controllers.reset_mock()
        schedules = {}
        for ctrl in controllers:
            sched = deepcopy(status_schedule)
            relay = deepcopy(status_schedule["relays"][0])
            relay["relay_id"] = ctrl.zones[0].id
            relay["relay"] = ctrl.zones[0].number.value
            relay["time"] = 1576800000
            sched["relays"] = [relay]
            schedules[ctrl.id] = sched

        async def fake_get(path, controller_id):
            return schedules[controller_id]

        hybrid_auth.get.side_effect = fake_get
        result2 = await api.get_controllers()
        mock_gql_client.get_controllers.assert_not_awaited()
        assert hybrid_auth.get.await_count == len(controllers)
        for ctrl in result2:
            assert ctrl.zones[0].status.suspended_until == datetime.max
        assert api._rest_throttle.tokens == len(controllers)

        hybrid_auth.get.reset_mock()
        assert await api.get_controllers() == result2
        mock_gql_client.get_controllers.assert_not_awaited()
        hybrid_auth.get.assert_not_awaited()


async def test_rest_tokens_reset_on_controller_increase(
    api, hybrid_auth, mock_gql_client, controller, zone, status_schedule
):
    """Ensure REST tokens reset when controller count grows."""
    with freeze_time(FROZEN_TIME):
        # Start with a single controller and consume all REST tokens.
        controller1 = deepcopy(controller)
        controller1.zones = [deepcopy(zone)]
        mock_gql_client.get_controllers.return_value = [controller1]
        await api.get_controllers()

        # Exhaust REST tokens to simulate prior updates.
        api._rest_throttle.tokens = api._rest_throttle.tokens_per_epoch

        # Discover a new controller and ensure tokens reset.
        controller2 = deepcopy(controller)
        controller2.id += 1
        controller2.zones = [deepcopy(zone)]
        controller2.zones[0].id += 0x100
        controller2.zones[0].number.value += 1
        controller2.zones[0].number.label = f"Zone {controller2.zones[0].number.value}"

        mock_gql_client.get_controllers.return_value = [controller1, controller2]
        await api.get_controllers()
        assert api._rest_throttle.tokens_per_epoch == 3
        assert api._rest_throttle.tokens == 0

        # Force REST usage by exhausting GraphQL tokens.
        api._gql_throttle.tokens = api._gql_throttle.tokens_per_epoch
        mock_gql_client.get_controllers.reset_mock()

        schedules = {}
        for ctrl in (controller1, controller2):
            sched = deepcopy(status_schedule)
            relay = deepcopy(status_schedule["relays"][0])
            relay["relay_id"] = ctrl.zones[0].id
            relay["relay"] = ctrl.zones[0].number.value
            relay["time"] = 1576800000
            sched["relays"] = [relay]
            schedules[ctrl.id] = sched

        async def fake_get(path, controller_id):
            return schedules[controller_id]

        hybrid_auth.get.side_effect = fake_get
        result = await api.get_controllers()
        mock_gql_client.get_controllers.assert_not_awaited()
        assert hybrid_auth.get.await_count == 2
        assert api._rest_throttle.tokens == 2
        assert len(result) == 2


async def test_get_controller(api, hybrid_auth, mock_gql_client, controller, zone):
    with freeze_time(FROZEN_TIME):
        controller.zones = [deepcopy(zone)]
        assert controller.zones[0].status.suspended_until != datetime.max

        # First fetch should query the GraphQL API
        mock_gql_client.get_controller.return_value = deepcopy(controller)
        assert await api.get_controller(controller.id) == controller
        mock_gql_client.get_controller.assert_awaited_once_with(controller.id)

        # Second fetch should also query the GraphQL API
        mock_gql_client.get_controller.reset_mock()
        assert await api.get_controller(controller.id) == controller
        mock_gql_client.get_controller.assert_awaited_once_with(controller.id)

        # Third fetch should not make any calls and instead return cached data
        mock_gql_client.get_controller.reset_mock()
        assert await api.get_controller(controller.id) == controller
        mock_gql_client.get_controller.assert_not_awaited()
        hybrid_auth.get.assert_not_awaited()


async def test_get_zones(
    api, hybrid_auth, mock_gql_client, controller, zone, status_schedule
):
    with freeze_time(FROZEN_TIME):
        assert zone.status.suspended_until != datetime.max

        # First fetch should query the GraphQL API
        mock_gql_client.get_zones.return_value = [deepcopy(zone)]
        assert await api.get_zones(controller) == [zone]
        mock_gql_client.get_zones.assert_awaited_once_with(controller)

        # Second fetch should also query the GraphQL API
        mock_gql_client.get_zones.reset_mock()
        assert await api.get_zones(controller) == [zone]
        mock_gql_client.get_zones.assert_awaited_once_with(controller)

        # Third fetch should query the REST API because we're out of tokens
        mock_gql_client.get_zones.reset_mock()
        status_schedule["relays"] = [status_schedule["relays"][0]]
        status_schedule["relays"][0]["time"] = 1576800000
        status_schedule["relays"][0]["name"] = "Zone A from REST API"
        hybrid_auth.get.return_value = status_schedule
        [zone2] = await api.get_zones(controller)
        mock_gql_client.get_zones.assert_not_awaited()
        hybrid_auth.get.assert_awaited_once_with(
            "statusschedule.php", controller_id=controller.id
        )
        assert zone2.status.suspended_until == datetime.max
        assert zone2.name == "Zone A"

        # Fourth fetch should query the REST API again
        hybrid_auth.get.reset_mock()
        assert await api.get_zones(controller) == [zone2]
        mock_gql_client.get_zones.assert_not_awaited()
        hybrid_auth.get.assert_awaited_once_with(
            "statusschedule.php", controller_id=controller.id
        )

        # Fifth fetch should not make any calls and instead return cached data
        hybrid_auth.get.reset_mock()
        assert await api.get_zones(controller) == [zone2]
        mock_gql_client.get_zones.assert_not_awaited()
        hybrid_auth.get.assert_not_awaited()


async def test_get_user_get_zones(
    api, hybrid_auth, mock_gql_client, user, status_schedule
):
    with freeze_time(FROZEN_TIME):
        [controller] = user.controllers
        controller.zones = []

        # Fetch the user twice without zones to deplete tokens.
        mock_gql_client.get_user.return_value = deepcopy(user)
        assert await api.get_user(fetch_zones=False) == user
        assert await api.get_user(fetch_zones=False) == user
        mock_gql_client.get_user.assert_has_awaits(
            [call(fetch_zones=False), call(fetch_zones=False)]
        )

        # Fetching zones should fall back to REST and still return zones.
        mock_gql_client.get_user.reset_mock()
        status_schedule["relays"] = [status_schedule["relays"][0]]
        status_schedule["relays"][0]["time"] = 1576800000
        status_schedule["relays"][0]["name"] = "Zone A from REST API"
        zone = Zone.from_json(status_schedule["relays"][0])
        hybrid_auth.get.return_value = status_schedule
        assert await api.get_zones(controller) == [zone]
        mock_gql_client.get_zones.assert_not_awaited()
        hybrid_auth.get.assert_awaited_once_with(
            "statusschedule.php", controller_id=controller.id
        )


async def test_get_zone(api, hybrid_auth, mock_gql_client, zone):
    with freeze_time(FROZEN_TIME):
        assert zone.status.suspended_until != datetime.max

        # First fetch should query the GraphQL API
        mock_gql_client.get_zone.return_value = deepcopy(zone)
        assert await api.get_zone(zone.id) == zone
        mock_gql_client.get_zone.assert_awaited_once_with(zone.id)

        # Second fetch should also query the GraphQL API
        mock_gql_client.get_zone.reset_mock()
        assert await api.get_zone(zone.id) == zone
        mock_gql_client.get_zone.assert_awaited_once_with(zone.id)

        # Third fetch should not make any calls and instead return cached data
        mock_gql_client.get_zone.reset_mock()
        assert await api.get_zone(zone.id) == zone
        mock_gql_client.get_zone.assert_not_awaited()
        hybrid_auth.get.assert_not_awaited()


async def test_get_sensors(api, hybrid_auth, mock_gql_client, controller, rain_sensor):
    sensor = rain_sensor
    with freeze_time(FROZEN_TIME):
        # First fetch should query the GraphQL API
        mock_gql_client.get_sensors.return_value = [deepcopy(sensor)]
        assert await api.get_sensors(controller) == [sensor]
        mock_gql_client.get_sensors.assert_awaited_once_with(controller)

        # Second fetch should also query the GraphQL API
        mock_gql_client.get_sensors.reset_mock()
        assert await api.get_sensors(controller) == [sensor]
        mock_gql_client.get_sensors.assert_awaited_once_with(controller)

        # Third fetch should not make any calls and instead return cached data
        mock_gql_client.get_sensors.reset_mock()
        assert await api.get_sensors(controller) == [sensor]
        mock_gql_client.get_sensors.assert_not_awaited()
        hybrid_auth.get.assert_not_awaited()


async def test_update_zones_concurrent(api, hybrid_auth, controller, status_schedule):
    """Stress test that multiple controllers update within throttle limits."""
    num_controllers = 5

    # Prepare controllers with unique IDs and register them with the client.
    controllers = []
    for idx in range(num_controllers):
        c = deepcopy(controller)
        c.id = controller.id + idx + 1
        controllers.append(c)
        api._controllers[c.id] = c

    # Allow exactly one request per controller.
    api._rest_throttle.tokens_per_epoch = num_controllers
    api._rest_throttle.tokens = 0

    # Generate unique zone IDs for each controller and create side effects.
    schedules = {}
    for idx, c in enumerate(controllers):
        sched = deepcopy(status_schedule)
        for relay in sched["relays"]:
            relay["relay_id"] += (idx + 1) * 0x100
        schedules[c.id] = sched

    async def fake_get(path, controller_id):
        await asyncio.sleep(0.1)
        return schedules[controller_id]

    hybrid_auth.get.side_effect = fake_get

    start = time.perf_counter()
    await api._update_zones()
    duration = time.perf_counter() - start

    # Requests should run concurrently, so duration should be well under the
    # sequential time (0.1s * num_controllers).
    assert duration < 0.1 * num_controllers * 0.8
    assert hybrid_auth.get.await_count == num_controllers
    assert api._rest_throttle.tokens == num_controllers

    # Subsequent update should be throttled and make no additional calls.
    hybrid_auth.get.reset_mock()
    await api._update_zones()
    hybrid_auth.get.assert_not_awaited()


async def test_update_zones_concurrency_limit(
    hybrid_auth, mock_gql_client, controller, status_schedule
):
    """Ensure the update controller concurrency can be limited."""
    api = HybridClient(
        hybrid_auth, gql_client=mock_gql_client, update_controller_concurrency=1
    )

    num_controllers = 5
    controllers = []
    for idx in range(num_controllers):
        c = deepcopy(controller)
        c.id = controller.id + idx + 1
        controllers.append(c)
        api._controllers[c.id] = c

    api._rest_throttle.tokens_per_epoch = num_controllers
    api._rest_throttle.tokens = 0

    schedules = {}
    for idx, c in enumerate(controllers):
        sched = deepcopy(status_schedule)
        for relay in sched["relays"]:
            relay["relay_id"] += (idx + 1) * 0x100
        schedules[c.id] = sched

    async def fake_get(path, controller_id):
        await asyncio.sleep(0.1)
        return schedules[controller_id]

    hybrid_auth.get.side_effect = fake_get

    start = time.perf_counter()
    await api._update_zones()
    duration = time.perf_counter() - start

    assert duration > 0.1 * num_controllers * 0.8
    assert hybrid_auth.get.await_count == num_controllers
