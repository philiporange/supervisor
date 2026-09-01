"""Dotted Caddy subdomains are full hostnames; bare labels sit under the base domain."""

from supervisor import caddy
from supervisor.config import config


def test_bare_label_uses_base_domain():
    assert caddy.service_host("myapp") == f"myapp.{config.caddy_base_domain}"
    assert caddy.service_url("myapp") == f"https://myapp.{config.caddy_base_domain}:{config.caddy_port}"


def test_dotted_name_is_verbatim_host():
    assert caddy.service_host("test.castpl.us") == "test.castpl.us"
    assert caddy.service_url("test.castpl.us") == f"https://test.castpl.us:{config.caddy_port}"
