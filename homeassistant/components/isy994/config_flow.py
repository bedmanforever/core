"""Config flow for Universal Devices ISY994 integration."""
import logging
from urllib.parse import urlparse, urlunparse

from aiohttp import CookieJar
import async_timeout
from pyisy import ISYConnectionError, ISYInvalidAuthError, ISYResponseParseError
from pyisy.configuration import Configuration
from pyisy.connection import Connection
import voluptuous as vol

from homeassistant import config_entries, core, data_entry_flow, exceptions
from homeassistant.components import dhcp, ssdp
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client

from .const import (
    CONF_IGNORE_STRING,
    CONF_RESTORE_LIGHT_STATE,
    CONF_SENSOR_STRING,
    CONF_TLS_VER,
    CONF_VAR_SENSOR_STRING,
    DEFAULT_IGNORE_STRING,
    DEFAULT_RESTORE_LIGHT_STATE,
    DEFAULT_SENSOR_STRING,
    DEFAULT_TLS_VERSION,
    DEFAULT_VAR_SENSOR_STRING,
    DOMAIN,
    HTTP_PORT,
    HTTPS_PORT,
    ISY_URL_POSTFIX,
    SCHEME_HTTP,
    SCHEME_HTTPS,
    UDN_UUID_PREFIX,
)

_LOGGER = logging.getLogger(__name__)


def _data_schema(schema_input):
    """Generate schema with defaults."""
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=schema_input.get(CONF_HOST, "")): str,
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional(CONF_TLS_VER, default=DEFAULT_TLS_VERSION): vol.In([1.1, 1.2]),
        },
        extra=vol.ALLOW_EXTRA,
    )


async def validate_input(hass: core.HomeAssistant, data):
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    user = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]
    host = urlparse(data[CONF_HOST])
    tls_version = data.get(CONF_TLS_VER)

    if host.scheme == SCHEME_HTTP:
        https = False
        port = host.port or HTTP_PORT
        session = aiohttp_client.async_create_clientsession(
            hass, verify_ssl=None, cookie_jar=CookieJar(unsafe=True)
        )
    elif host.scheme == SCHEME_HTTPS:
        https = True
        port = host.port or HTTPS_PORT
        session = aiohttp_client.async_get_clientsession(hass)
    else:
        _LOGGER.error("The isy994 host value in configuration is invalid")
        raise InvalidHost

    # Connect to ISY controller.
    isy_conn = Connection(
        host.hostname,
        port,
        user,
        password,
        use_https=https,
        tls_ver=tls_version,
        webroot=host.path,
        websession=session,
    )

    try:
        async with async_timeout.timeout(30):
            isy_conf_xml = await isy_conn.test_connection()
    except ISYInvalidAuthError as error:
        raise InvalidAuth from error
    except ISYConnectionError as error:
        raise CannotConnect from error

    try:
        isy_conf = Configuration(xml=isy_conf_xml)
    except ISYResponseParseError as error:
        raise CannotConnect from error
    if not isy_conf or "name" not in isy_conf or not isy_conf["name"]:
        raise CannotConnect

    # Return info that you want to store in the config entry.
    return {"title": f"{isy_conf['name']} ({host.hostname})", "uuid": isy_conf["uuid"]}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Universal Devices ISY994."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the isy994 config flow."""
        self.discovered_conf = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        info = None
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidHost:
                errors["base"] = "invalid_host"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

            if not errors:
                await self.async_set_unique_id(info["uuid"], raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=_data_schema(self.discovered_conf),
            errors=errors,
        )

    async def async_step_import(self, user_input):
        """Handle import."""
        return await self.async_step_user(user_input)

    async def _async_set_unique_id_or_update(self, isy_mac, ip_address, port) -> None:
        """Abort and update the ip address on change."""
        existing_entry = await self.async_set_unique_id(isy_mac)
        if not existing_entry:
            return
        parsed_url = urlparse(existing_entry.data[CONF_HOST])
        if parsed_url.hostname != ip_address:
            new_netloc = ip_address
            if port:
                new_netloc = f"{ip_address}:{port}"
            elif parsed_url.port:
                new_netloc = f"{ip_address}:{parsed_url.port}"
            self.hass.config_entries.async_update_entry(
                existing_entry,
                data={
                    **existing_entry.data,
                    CONF_HOST: urlunparse(
                        (
                            parsed_url.scheme,
                            new_netloc,
                            parsed_url.path,
                            parsed_url.query,
                            parsed_url.fragment,
                            None,
                        )
                    ),
                },
            )
        raise data_entry_flow.AbortFlow("already_configured")

    async def async_step_dhcp(
        self, discovery_info: dhcp.DhcpServiceInfo
    ) -> data_entry_flow.FlowResult:
        """Handle a discovered isy994 via dhcp."""
        friendly_name = discovery_info.hostname
        url = f"http://{discovery_info.ip}"
        mac = discovery_info.macaddress
        isy_mac = (
            f"{mac[0:2]}:{mac[2:4]}:{mac[4:6]}:{mac[6:8]}:{mac[8:10]}:{mac[10:12]}"
        )
        await self._async_set_unique_id_or_update(isy_mac, discovery_info.ip, None)

        self.discovered_conf = {
            CONF_NAME: friendly_name,
            CONF_HOST: url,
        }

        self.context["title_placeholders"] = self.discovered_conf
        return await self.async_step_user()

    async def async_step_ssdp(
        self, discovery_info: ssdp.SsdpServiceInfo
    ) -> data_entry_flow.FlowResult:
        """Handle a discovered isy994."""
        friendly_name = discovery_info.upnp[ssdp.ATTR_UPNP_FRIENDLY_NAME]
        url = discovery_info.ssdp_location
        parsed_url = urlparse(url)
        mac = discovery_info.upnp[ssdp.ATTR_UPNP_UDN]
        if mac.startswith(UDN_UUID_PREFIX):
            mac = mac[len(UDN_UUID_PREFIX) :]
        if url.endswith(ISY_URL_POSTFIX):
            url = url[: -len(ISY_URL_POSTFIX)]

        port = HTTP_PORT
        if parsed_url.port:
            port = parsed_url.port
        elif parsed_url.scheme == SCHEME_HTTPS:
            port = HTTPS_PORT

        await self._async_set_unique_id_or_update(mac, parsed_url.hostname, port)

        self.discovered_conf = {
            CONF_NAME: friendly_name,
            CONF_HOST: url,
        }

        self.context["title_placeholders"] = self.discovered_conf
        return await self.async_step_user()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a option flow for isy994."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Handle options flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        restore_light_state = options.get(
            CONF_RESTORE_LIGHT_STATE, DEFAULT_RESTORE_LIGHT_STATE
        )
        ignore_string = options.get(CONF_IGNORE_STRING, DEFAULT_IGNORE_STRING)
        sensor_string = options.get(CONF_SENSOR_STRING, DEFAULT_SENSOR_STRING)
        var_sensor_string = options.get(
            CONF_VAR_SENSOR_STRING, DEFAULT_VAR_SENSOR_STRING
        )

        options_schema = vol.Schema(
            {
                vol.Optional(CONF_IGNORE_STRING, default=ignore_string): str,
                vol.Optional(CONF_SENSOR_STRING, default=sensor_string): str,
                vol.Optional(CONF_VAR_SENSOR_STRING, default=var_sensor_string): str,
                vol.Required(
                    CONF_RESTORE_LIGHT_STATE, default=restore_light_state
                ): bool,
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate the host value is invalid."""


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
