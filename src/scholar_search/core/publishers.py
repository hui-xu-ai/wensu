"""Publisher domains the page reader may visit, and the DOI prefixes that lead there.

The whitelist is curated on purpose (ADR 0019). A DOI that maps to no entry is answered
with `unsupported_site` instead of being tried: guessing at an unknown site is how an
automated reader ends up on a page whose terms forbid it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Publisher:
    """One publisher: the domains it serves articles from and its front page."""

    name: str
    domains: tuple[str, ...]
    homepage: str
    doi_prefixes: tuple[str, ...] = ()

    def hosts(self) -> tuple[str, ...]:
        # `www.` never appears here: the matcher treats a domain as "itself or any
        # subdomain", the same rule the kernel and the extension use.
        return self.domains


PUBLISHERS: tuple[Publisher, ...] = (
    Publisher(
        "elsevier",
        ("sciencedirect.com",),
        "https://www.sciencedirect.com/",
        ("10.1016",),
    ),
    Publisher("springer", ("link.springer.com",), "https://link.springer.com/", ("10.1007",)),
    Publisher("nature", ("nature.com",), "https://www.nature.com/", ("10.1038",)),
    Publisher(
        "wiley",
        ("onlinelibrary.wiley.com",),
        "https://onlinelibrary.wiley.com/",
        ("10.1002", "10.1111", "10.1002"),
    ),
    Publisher("acs", ("pubs.acs.org",), "https://pubs.acs.org/", ("10.1021",)),
    Publisher("rsc", ("pubs.rsc.org",), "https://pubs.rsc.org/", ("10.1039",)),
    Publisher(
        "taylor-francis",
        ("tandfonline.com",),
        "https://www.tandfonline.com/",
        ("10.1080",),
    ),
    Publisher("sage", ("journals.sagepub.com",), "https://journals.sagepub.com/", ("10.1177",)),
    Publisher("mdpi", ("mdpi.com",), "https://www.mdpi.com/", ("10.3390",)),
    Publisher("frontiers", ("frontiersin.org",), "https://www.frontiersin.org/", ("10.3389",)),
    Publisher("plos", ("journals.plos.org",), "https://journals.plos.org/", ("10.1371",)),
    Publisher("arxiv", ("arxiv.org",), "https://arxiv.org/", ("10.48550",)),
    Publisher("ieee", ("ieeexplore.ieee.org",), "https://ieeexplore.ieee.org/", ("10.1109",)),
    Publisher("acm", ("dl.acm.org",), "https://dl.acm.org/", ("10.1145",)),
    Publisher("science", ("science.org",), "https://www.science.org/", ("10.1126",)),
    Publisher("pnas", ("pnas.org",), "https://www.pnas.org/", ("10.1073",)),
    Publisher("bmj", ("bmj.com",), "https://www.bmj.com/", ("10.1136",)),
    Publisher("nejm", ("nejm.org",), "https://www.nejm.org/", ("10.1056",)),
    Publisher("jama", ("jamanetwork.com",), "https://jamanetwork.com/", ("10.1001",)),
    Publisher("cambridge", ("cambridge.org",), "https://www.cambridge.org/", ("10.1017",)),
    Publisher("oxford", ("academic.oup.com",), "https://academic.oup.com/", ("10.1093",)),
    Publisher("iop", ("iopscience.iop.org",), "https://iopscience.iop.org/", ("10.1088",)),
    Publisher("aps", ("journals.aps.org",), "https://journals.aps.org/", ("10.1103",)),
    Publisher("aip", ("pubs.aip.org",), "https://pubs.aip.org/", ("10.1063",)),
    Publisher("karger", ("karger.com",), "https://karger.com/", ("10.1159",)),
)


def publisher_domains() -> tuple[str, ...]:
    """Every host the page reader may navigate to, deduplicated and sorted."""

    hosts: dict[str, None] = {}
    for publisher in PUBLISHERS:
        for host in publisher.hosts():
            hosts.setdefault(host, None)
    return tuple(sorted(hosts))


def publisher_for_host(host: str) -> Publisher | None:
    """The publisher that serves `host`, or None when the site is not on the list."""

    candidate = (host or "").casefold().rstrip(".")
    if not candidate:
        return None
    for publisher in PUBLISHERS:
        for domain in publisher.hosts():
            domain = domain.casefold()
            if candidate == domain or candidate.endswith("." + domain):
                return publisher
    return None


def publisher_for_doi(doi: str) -> Publisher | None:
    """The publisher a DOI prefix belongs to, or None when the prefix is unknown."""

    value = (doi or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if value.casefold().startswith(prefix):
            value = value[len(prefix) :]
    if not value.casefold().startswith("10."):
        return None
    head = value.split("/", 1)[0].strip()
    for publisher in PUBLISHERS:
        if head in publisher.doi_prefixes:
            return publisher
    return None
