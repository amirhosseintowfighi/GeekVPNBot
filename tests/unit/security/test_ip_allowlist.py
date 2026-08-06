"""CIDR allowlisting and client address resolution."""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.security.ip_allowlist import (
    AllowlistConfigError,
    IpAllowlist,
    client_ip,
    parse_ip,
)


class TestMatching:
    def test_a_bare_address_matches_itself_only(self):
        allowlist = IpAllowlist.from_entries(["203.0.113.5"])
        assert allowlist.allows("203.0.113.5")
        assert not allowlist.allows("203.0.113.6")

    def test_a_cidr_range_matches_its_members(self):
        allowlist = IpAllowlist.from_entries(["10.0.0.0/8"])
        assert allowlist.allows("10.55.7.1")
        assert not allowlist.allows("11.0.0.1")

    def test_ipv6_works(self):
        allowlist = IpAllowlist.from_entries(["2001:db8::/32"])
        assert allowlist.allows("2001:db8::1")
        assert not allowlist.allows("2001:db9::1")

    def test_an_empty_allowlist_allows_everything(self):
        """Opt-in: an upgrade must not lock existing operators out."""
        assert IpAllowlist().allows("8.8.8.8")
        assert IpAllowlist().is_empty

    def test_an_unparseable_address_is_refused_when_a_list_exists(self):
        """If we cannot tell where it came from, it is not from an approved place."""
        allowlist = IpAllowlist.from_entries(["10.0.0.0/8"])
        assert not allowlist.allows("not-an-ip")
        assert not allowlist.allows(None)
        assert not allowlist.allows("")

    def test_host_bits_in_a_range_are_tolerated(self):
        """10.0.0.5/24 obviously means the /24; refusing to boot is worse."""
        assert IpAllowlist.from_entries(["10.0.0.5/24"]).allows("10.0.0.9")

    def test_a_malformed_entry_fails_loudly_at_configuration_time(self):
        """Silently dropping a bad entry would quietly widen access."""
        with pytest.raises(AllowlistConfigError):
            IpAllowlist.from_entries(["10.0.0.0/8", "banana"])

    def test_a_port_suffix_is_stripped(self):
        assert IpAllowlist.from_entries(["203.0.113.0/24"]).allows("203.0.113.9:54321")

    def test_bracketed_ipv6_with_a_port_is_understood(self):
        assert str(parse_ip("[2001:db8::1]:8443")) == "2001:db8::1"


class TestClientAddressResolution:
    """The forged-header attack, which is the real vulnerability in this area."""

    def test_forwarding_headers_are_ignored_when_no_proxy_is_trusted(self):
        assert (
            client_ip(
                remote_addr="198.51.100.9",
                forwarded_for="203.0.113.7",
                trusted_proxy_count=0,
            )
            == "198.51.100.9"
        )

    def test_a_spoofed_leftmost_entry_cannot_impersonate_an_allowed_address(self):
        """The whole point: the client controls the left of the chain.

        A naive implementation reads the leftmost entry and would admit this
        request to an admin panel from anywhere in the world.
        """
        allowlist = IpAllowlist.from_entries(["203.0.113.0/24"])
        forged = "203.0.113.7, 198.51.100.9"
        resolved = client_ip(remote_addr="172.16.0.2", forwarded_for=forged, trusted_proxy_count=1)
        assert resolved == "198.51.100.9"
        assert not allowlist.allows(resolved)
        # And the naive reading would have let it through, which is why this
        # test exists rather than a comment.
        assert allowlist.allows(forged.split(",")[0].strip())

    def test_one_trusted_proxy_reads_the_address_that_proxy_saw(self):
        assert (
            client_ip(
                remote_addr="172.16.0.2",
                forwarded_for="198.51.100.9",
                trusted_proxy_count=1,
            )
            == "198.51.100.9"
        )

    def test_two_trusted_proxies_step_two_entries_from_the_right(self):
        assert (
            client_ip(
                remote_addr="172.16.0.2",
                forwarded_for="198.51.100.9, 10.1.1.1",
                trusted_proxy_count=2,
            )
            == "198.51.100.9"
        )

    def test_a_short_chain_does_not_crash_or_wrap_around(self):
        """Fewer entries than trusted hops means a misconfiguration, not a crash."""
        resolved = client_ip(
            remote_addr="172.16.0.2", forwarded_for="198.51.100.9", trusted_proxy_count=3
        )
        assert resolved == "198.51.100.9"

    def test_real_ip_is_used_only_when_no_chain_exists(self):
        assert (
            client_ip(remote_addr="172.16.0.2", real_ip="198.51.100.9", trusted_proxy_count=1)
            == "198.51.100.9"
        )

    def test_garbage_in_the_chain_falls_back_rather_than_returning_it(self):
        resolved = client_ip(
            remote_addr="172.16.0.2",
            forwarded_for="not-an-ip",
            real_ip="198.51.100.9",
            trusted_proxy_count=1,
        )
        assert resolved == "198.51.100.9"

    def test_no_information_at_all_yields_none_not_a_guess(self):
        """None means unknown, and callers must never read it as allowed."""
        assert client_ip(remote_addr=None, trusted_proxy_count=1) is None
        assert not IpAllowlist.from_entries(["10.0.0.0/8"]).allows(
            client_ip(remote_addr=None, trusted_proxy_count=1)
        )
