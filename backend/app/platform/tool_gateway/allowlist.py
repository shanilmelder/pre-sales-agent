"""The research allowlist (Story 5.4): which hosts the research fetch may read.

`ops/research-allowlist.yaml`, loaded from `PSA_RESEARCH_ALLOWLIST_PATH`:

    version: 1
    topics:
      <topic>: [host, …]

A host matches exactly or as a subdomain (`docs.example.com` matches `example.com`). Only
`https` URLs on the default port, with no user info, are allowed. A missing path or file is
an empty allowlist: every fetch is denied.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

import yaml

_HOST_RE_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-")


class AllowlistError(ValueError):
    """The allowlist file is malformed."""


def _host(value: object) -> str:
    if not isinstance(value, str):
        raise AllowlistError("an allowlisted host must be a string")
    host = value.strip().lower().rstrip(".")
    if not host or not set(host) <= _HOST_RE_CHARS or host.startswith(("-", ".")):
        raise AllowlistError("an allowlisted host must be a plain DNS name")
    return host


@dataclass(frozen=True, slots=True)
class Allowlist:
    version: int = 0
    topics: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def parse(cls, data: object) -> "Allowlist":
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise AllowlistError("the allowlist must be a mapping")
        version = data.get("version", 0)
        topics = data.get("topics") or {}
        if not isinstance(version, int) or not isinstance(topics, Mapping):
            raise AllowlistError("the allowlist needs an integer version and a topics mapping")
        parsed: dict[str, tuple[str, ...]] = {}
        for topic, hosts in topics.items():
            if not isinstance(topic, str) or not isinstance(hosts, Sequence):
                raise AllowlistError("each topic maps to a list of hosts")
            if isinstance(hosts, str):
                raise AllowlistError("each topic maps to a list of hosts")
            parsed[topic] = tuple(_host(h) for h in hosts)
        return cls(version=version, topics=MappingProxyType(parsed))

    @classmethod
    def load(cls, path: Path | None) -> "Allowlist":
        if path is None or not path.is_file():
            return cls()
        return cls.parse(yaml.safe_load(path.read_text(encoding="utf-8")))

    def hosts(self, topic: str | None = None) -> tuple[str, ...]:
        """The hosts of `topic`, or of every topic when None (an unknown topic has none)."""
        if topic is not None:
            return self.topics.get(topic, ())
        return tuple(h for hosts in self.topics.values() for h in hosts)

    def allows(self, url: str, topic: str | None = None) -> bool:
        """Whether `url` is an `https` URL on the default port, with no user info, whose host
        is one of the topic's hosts or a subdomain of one."""
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return False
        if parts.scheme != "https" or parts.username or parts.password:
            return False
        if port not in (None, 443):
            return False
        host = (parts.hostname or "").rstrip(".")
        if not host:
            return False
        return any(host == h or host.endswith("." + h) for h in self.hosts(topic))
