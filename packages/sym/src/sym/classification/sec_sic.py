"""SEC SIC → GICS-sector classification (Story: multi-source classification, AC #2).

A keyless, whole-universe fill source for US-listed names the primary
``financedatabase`` and the Brazil-only ``b3`` sources leave unclassified
(e.g. HON / Honeywell — the non-Brazil GICS gap). The SEC publishes, for every
US filer, a Standard Industrial Classification (SIC) code in its EDGAR
submissions metadata; this module pulls that code and maps it onto the GICS
*sector* taxonomy via a documented crosswalk.

Like :class:`sym.classification.b3.B3GicsSource`, every classification produced
here is **sector-only** (``source='sec_sic'``, all industry levels NULL) and the
source can never overwrite an existing classification — the caller feeds it only
:func:`sym.classification.gics.read_unclassified_identities`, so it is fill-only
by construction and ``financedatabase``/``b3`` always win where they overlap.

Two SEC endpoints (the same ones :mod:`altdata.sources` uses — replicated here,
not imported, because ``sym`` is a peer package that must not depend on
``altdata``):

* ``www.sec.gov/files/company_tickers.json`` — ticker → CIK directory;
* ``data.sec.gov/submissions/CIK{cik}.json`` — per-filer metadata carrying
  ``sic`` + ``sicDescription``.

Both require a `SEC-compliant User-Agent <https://www.sec.gov/os/webmaster-faq#developers>`_
carrying a contact email, or they return 403.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Sequence
from typing import Protocol

from sym.classification._http import RequestThrottle
from sym.classification.gics import GicsClassification, SecurityIdentity

# SEC fair-access policy requires a descriptive UA with a contact address.
_UA = {"User-Agent": "qrp-sym/1.0 (personal research; codex@gladstone-management.com)"}
_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_HTTP_TIMEOUT = 30

# MICs the SEC SIC source is willing to classify. SIC is a US-filer attribute,
# and ``company_tickers.json`` is keyed on bare US tickers — a foreign security
# that happens to share a ticker string must never inherit a US filer's SIC, so
# only US listing venues are in scope. An identity carrying NO mic is trusted
# ticker-only (test fakes / legacy callers), mirroring B3's posture.
US_MICS = frozenset({"XNAS", "XNYS", "XASE", "ARCX", "BATS", "IEXG", "XOTC", "OOTC"})


class SecSicError(RuntimeError):
    """The SEC endpoints were unreachable or returned an unusable shape."""


class SecClient(Protocol):
    """The two SEC lookups the source needs (injectable for DB-free testing)."""

    def company_ciks(self, tickers: Sequence[str]) -> dict[str, str]:
        """Map each requested ticker (upper-cased) to its 10-digit zero-padded CIK."""
        ...

    def sic_for_cik(self, cik: str) -> tuple[str | None, str | None]:
        """Return ``(sic, sic_description)`` for a CIK; ``(None, None)`` if absent."""
        ...


class HttpSecClient:
    """Live :class:`SecClient` over EDGAR (stdlib ``urllib``, SEC-compliant UA).

    Self-throttles to stay under SEC's fair-access ceiling (~10 requests/second):
    the fill pass issues one ``submissions`` request per unclassified US name
    sequentially, so a min gap between requests keeps the run polite even as the
    universe grows. ``min_interval=0`` disables it (tests inject a fake client and
    never reach here, but it keeps the door open).
    """

    def __init__(self, min_interval: float = 0.12) -> None:
        self._throttle = RequestThrottle(min_interval)
        # ticker -> all CIKs the directory carried for it, when >1 (a reassignment
        # collision). Recorded so the source can report the ambiguity; reset per call.
        self.last_ambiguous_ticker: dict[str, list[str]] = {}

    def _get_json(self, url: str) -> object:
        self._throttle.wait()
        req = urllib.request.Request(url, headers=_UA)
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError) as exc:  # URLError/HTTPError/timeout/bad-json
            raise SecSicError(f"SEC request failed for {url}: {exc}") from exc

    def company_ciks(self, tickers: Sequence[str]) -> dict[str, str]:
        wanted = {t.upper() for t in tickers}
        if not wanted:
            return {}
        self.last_ambiguous_ticker = {}
        payload = self._get_json(_CIK_URL)
        if not isinstance(payload, dict):
            raise SecSicError("company_tickers.json was not a JSON object")
        # Collect ALL CIKs the directory carries per ticker — NOT first-wins. SEC can
        # list the same ticker under two CIKs after a reassignment (an old delisted
        # filer + the new active one), and blindly taking the first risks attributing a
        # stale filer's SIC to the new name.
        candidates: dict[str, list[str]] = {}
        for row in payload.values():
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker", "")).upper()
            cik_raw = row.get("cik_str")
            if ticker in wanted and cik_raw is not None:
                try:
                    cik = f"{int(cik_raw):010d}"
                except (TypeError, ValueError):
                    # A non-numeric cik_str is a one-off shape fault — skip that row,
                    # don't fail the whole directory parse.
                    continue
                ciks = candidates.setdefault(ticker, [])
                if cik not in ciks:
                    ciks.append(cik)
        out: dict[str, str] = {}
        for ticker, ciks in candidates.items():
            if len(ciks) == 1:
                # The overwhelming-majority path — one CIK, zero extra calls.
                out[ticker] = ciks[0]
                continue
            # Rare collision: resolve to the active filer (bounded to colliding
            # tickers, so the common path is untouched) and record the ambiguity.
            self.last_ambiguous_ticker[ticker] = list(ciks)
            out[ticker] = self._resolve_active_cik(ticker, ciks)
        return out

    def _resolve_active_cik(self, ticker: str, ciks: Sequence[str]) -> str:
        """Pick the active filer among CIKs sharing a ticker.

        Prefers the filer whose ``submissions`` payload still lists the ticker as
        current, tie-broken by the most-recent filing date; falls back to the first
        candidate when no submissions are reachable. Only ever called for the rare
        duplicate-ticker collision, so the extra ``submissions`` fetches are bounded.
        """
        best_cik = ciks[0]
        best_key: tuple[bool, str] = (False, "")
        for cik in ciks:
            try:
                payload = self._get_json(_SUBMISSIONS_URL.format(cik=cik))
            except SecSicError:
                continue  # a candidate we can't read can't win; keep the fallback
            if not isinstance(payload, dict):
                continue
            # Defensive at every level: a malformed/partial submissions payload (under
            # rate-limit / error envelopes SEC returns odd shapes) must NOT raise here —
            # an exception would escape this method and abort the whole fill pass, the
            # very per-name isolation this source otherwise guarantees.
            raw_tickers = payload.get("tickers")
            current = (
                {str(t).upper() for t in raw_tickers if t}
                if isinstance(raw_tickers, (list, tuple))
                else set()
            )
            recent = payload.get("filings")
            recent = recent.get("recent") if isinstance(recent, dict) else None
            dates = recent.get("filingDate") if isinstance(recent, dict) else None
            valid_dates = [str(d) for d in dates if d] if isinstance(dates, list) else []
            latest = max(valid_dates) if valid_dates else ""
            key = (ticker.upper() in current, latest)
            if key > best_key:
                best_key = key
                best_cik = cik
        return best_cik

    def sic_for_cik(self, cik: str) -> tuple[str | None, str | None]:
        payload = self._get_json(_SUBMISSIONS_URL.format(cik=cik))
        if not isinstance(payload, dict):
            return (None, None)
        sic = payload.get("sic")
        desc = payload.get("sicDescription")
        sic_str = str(sic).strip() if sic not in (None, "") else None
        desc_str = str(desc).strip() if isinstance(desc, str) and desc.strip() else None
        return (sic_str, desc_str)


# ---------------------------------------------------------------------------
# SIC → GICS sector crosswalk
# ---------------------------------------------------------------------------
# SIC is a 4-digit code grouped into major groups (2-digit) and divisions. The
# crosswalk maps it onto the 11 GICS sectors (the exact label strings used by
# financedatabase + b3 — keep them identical so the heatmap/validate group
# cleanly). Specific 4-digit codes take precedence over the range bands, so the
# high-traffic exceptions (semiconductors, software, pharma, REITs, computers)
# are never swept into a coarser parent. Codes that don't map return None — the
# source records them as unmapped and NEVER guesses a sector.

# Exact 4-digit overrides — checked first, beat any range below.
_SIC_OVERRIDES: dict[int, str] = {
    2833: "Health Care",  # medicinal chemicals & botanical products
    2834: "Health Care",  # pharmaceutical preparations
    2835: "Health Care",  # in-vitro & in-vivo diagnostics
    2836: "Health Care",  # biological products
    2844: "Consumer Staples",  # perfumes, cosmetics & toilet preparations
    3571: "Information Technology",  # electronic computers
    3572: "Information Technology",  # computer storage devices
    3576: "Information Technology",  # computer communications equipment
    3577: "Information Technology",  # computer peripheral equipment
    3661: "Information Technology",  # telephone & telegraph apparatus
    3663: "Information Technology",  # radio/TV broadcasting & comms equipment
    3669: "Information Technology",  # communications equipment, nec
    3672: "Information Technology",  # printed circuit boards
    3674: "Information Technology",  # semiconductors & related devices
    3826: "Health Care",  # laboratory analytical instruments
    3827: "Information Technology",  # optical instruments & lenses
    3841: "Health Care",  # surgical & medical instruments
    3842: "Health Care",  # orthopedic, prosthetic & surgical appliances
    3843: "Health Care",  # dental equipment & supplies
    3844: "Health Care",  # x-ray apparatus & tubes
    3845: "Health Care",  # electromedical apparatus
    3851: "Health Care",  # ophthalmic goods
    5912: "Consumer Staples",  # drug stores & proprietary stores
    6798: "Real Estate",  # real estate investment trusts (REITs)
    7311: "Communication Services",  # advertising agencies
    7372: "Information Technology",  # prepackaged software
    8731: "Health Care",  # commercial physical & biological research (biotech)
}

# Inclusive 4-digit range bands → GICS sector, evaluated top-to-bottom; the
# FIRST band that contains the code wins, so narrower bands precede their
# broader neighbours.
_SIC_BANDS: tuple[tuple[int, int, str], ...] = (
    (100, 299, "Consumer Staples"),  # agricultural production (crops/livestock)
    (700, 999, "Materials"),  # agricultural services, forestry, fishing
    (1000, 1099, "Materials"),  # metal mining
    (1200, 1299, "Energy"),  # coal mining
    (1300, 1399, "Energy"),  # oil & gas extraction
    (1400, 1499, "Materials"),  # mining/quarrying of nonmetallic minerals
    (1520, 1549, "Consumer Discretionary"),  # homebuilders / operative builders
    (1500, 1799, "Industrials"),  # general & heavy construction
    (2000, 2199, "Consumer Staples"),  # food & kindred products, tobacco
    (2200, 2399, "Consumer Discretionary"),  # textile mill & apparel
    (2400, 2499, "Materials"),  # lumber & wood products
    (2500, 2599, "Consumer Discretionary"),  # furniture & fixtures
    (2600, 2699, "Materials"),  # paper & allied products
    (2700, 2741, "Communication Services"),  # newspapers, periodicals, books
    (2750, 2799, "Industrials"),  # commercial printing & services
    (2800, 2899, "Materials"),  # chemicals (pharma/cosmetics handled in overrides)
    (2900, 2999, "Energy"),  # petroleum refining & related
    (3000, 3099, "Materials"),  # rubber & plastics
    (3100, 3199, "Consumer Discretionary"),  # leather & leather goods
    (3200, 3299, "Materials"),  # stone, clay, glass & concrete
    (3300, 3499, "Materials"),  # primary & fabricated metal
    (3500, 3569, "Industrials"),  # industrial & commercial machinery
    (3570, 3579, "Information Technology"),  # computer & office equipment
    (3580, 3629, "Industrials"),  # service-industry & electrical industrial apparatus
    (3630, 3651, "Consumer Discretionary"),  # household appliances & audio/video
    (3652, 3699, "Information Technology"),  # electronic components (semis handled above)
    (3710, 3716, "Consumer Discretionary"),  # motor vehicles & equipment
    (3751, 3751, "Consumer Discretionary"),  # motorcycles, bicycles & parts
    (3700, 3799, "Industrials"),  # aircraft, ships, rail & defense equipment
    (3800, 3899, "Industrials"),  # instruments (medical/optical handled in overrides)
    (3900, 3999, "Consumer Discretionary"),  # misc manufacturing (jewelry, toys, sport)
    (4000, 4499, "Industrials"),  # rail, transit, trucking, water transport
    (4500, 4599, "Industrials"),  # air transportation
    (4600, 4699, "Energy"),  # pipelines (except natural gas)
    (4700, 4799, "Industrials"),  # transportation services
    (4800, 4899, "Communication Services"),  # telephone, broadcasting, cable
    (4900, 4949, "Utilities"),  # electric, gas & combination utilities
    (4950, 4999, "Industrials"),  # sanitary services / waste management
    (5000, 5099, "Industrials"),  # wholesale — durable goods
    (5100, 5199, "Consumer Staples"),  # wholesale — nondurable goods
    (5400, 5499, "Consumer Staples"),  # retail — food stores
    (5200, 5999, "Consumer Discretionary"),  # retail trade (food/drug handled above)
    (6000, 6499, "Financials"),  # banks, brokers, insurance
    (6500, 6599, "Real Estate"),  # real estate operators & developers
    (6600, 6799, "Financials"),  # holding & investment offices (REITs in overrides)
    (7000, 7099, "Consumer Discretionary"),  # hotels & lodging
    (7200, 7299, "Consumer Discretionary"),  # personal services
    (7310, 7319, "Communication Services"),  # advertising
    (7370, 7379, "Information Technology"),  # computer programming, software, data
    (7300, 7399, "Industrials"),  # business services
    (7500, 7599, "Consumer Discretionary"),  # automotive repair & services
    (7600, 7699, "Industrials"),  # miscellaneous repair services
    (7800, 7899, "Communication Services"),  # motion pictures
    (7900, 7999, "Consumer Discretionary"),  # amusement & recreation
    (8000, 8099, "Health Care"),  # health services
    (8200, 8299, "Consumer Discretionary"),  # educational services
    (8300, 8399, "Consumer Discretionary"),  # social services
    (8700, 8799, "Industrials"),  # engineering, accounting, management (R&D in overrides)
)


def sic_to_gics_sector(sic: str | None) -> str | None:
    """Map a 4-digit SIC code to a GICS sector label, or None if unmapped.

    Exact-code overrides win over the range bands; the first band containing the
    code wins among bands. A non-numeric/absent SIC, or one no rule covers, maps
    to None — the source records it as unmapped rather than guessing.
    """
    if not sic:
        return None
    try:
        code = int(str(sic).strip())
    except ValueError:
        return None
    if code in _SIC_OVERRIDES:
        return _SIC_OVERRIDES[code]
    for low, high, sector in _SIC_BANDS:
        if low <= code <= high:
            return sector
    return None


class SecSicGicsSource:
    """GICS *sector* classifications derived from SEC EDGAR SIC codes.

    Implements the :class:`sym.classification.gics.GicsSource` protocol. For each
    in-scope (US-listed, ticker-bearing) identity it resolves a CIK, reads the
    filer's SIC, and maps it to a GICS sector. Every produced classification is
    SECTOR-ONLY with ``source='sec_sic'`` (industry levels NULL — SIC has no
    GICS sub-structure).

    Attribution side-channels (reset per ``fetch``, reported by the caller,
    never guessed):

    * ``last_unmapped_sic`` (ticker -> (sic, sic_description)): the filer's SIC
      mapped to no GICS sector — surfaced so a crosswalk gap is visible, not
      silently dropped;
    * ``last_unmatched`` (tickers): in-scope tickers with no CIK in the SEC
      directory, or whose submissions carried no SIC;
    * ``last_skipped_non_us`` (tickers): identities skipped because their MIC is
      not a US venue (SIC would be meaningless / wrong for them);
    * ``last_errors`` (ticker -> message): a per-CIK ``submissions`` lookup that
      errored (404 for a renamed/delisted CIK, a transient SEC blip, a 403/429).
      Isolated so ONE bad CIK never aborts the rest of the pass — the analogue of
      the SCD writer's per-security transaction durability.
    * ``last_ambiguous_ticker`` (ticker -> [cik, …]): a ticker the SEC directory
      carried under more than one CIK (a reassignment collision); the client
      resolved it to the active filer, but the ambiguity is surfaced here so a
      mis-resolution is visible rather than silent.
    """

    def __init__(self, client: SecClient | None = None) -> None:
        self._client = client or HttpSecClient()
        self.last_unmapped_sic: dict[str, tuple[str | None, str | None]] = {}
        self.last_unmatched: list[str] = []
        self.last_skipped_non_us: list[str] = []
        self.last_errors: dict[str, str] = {}
        self.last_ambiguous_ticker: dict[str, list[str]] = {}

    def fetch(self, securities: Sequence[SecurityIdentity]) -> dict[str, GicsClassification]:
        self.last_unmapped_sic = {}
        self.last_unmatched = []
        self.last_skipped_non_us = []
        self.last_errors = {}
        self.last_ambiguous_ticker = {}

        # In-scope = US-listed (or mic-less, trusted ticker-only) with a ticker.
        # Keep the LAST identity per ticker (stable, deterministic) so the result
        # is attributed to a single CompositeFIGI.
        by_ticker: dict[str, SecurityIdentity] = {}
        for s in securities:
            if not s.ticker:
                continue
            if s.mic is not None and s.mic not in US_MICS:
                self.last_skipped_non_us.append(s.ticker.upper())
                continue
            by_ticker[s.ticker.upper()] = s
        if not by_ticker:
            return {}

        ciks = self._client.company_ciks(list(by_ticker))
        # The live client records duplicate-ticker collisions it had to resolve; a
        # test fake won't have the attribute, so default to none.
        self.last_ambiguous_ticker = dict(getattr(self._client, "last_ambiguous_ticker", {}))
        found: dict[str, GicsClassification] = {}
        for ticker, security in by_ticker.items():
            cik = ciks.get(ticker)
            if cik is None:
                self.last_unmatched.append(ticker)
                continue
            try:
                sic, desc = self._client.sic_for_cik(cik)
            except SecSicError as exc:
                # One CIK's submissions failing must not abort the whole fill pass —
                # record it and move on (the company_tickers directory call already
                # succeeded, so this is a per-name fault, not an outage).
                self.last_errors[ticker] = str(exc)
                continue
            if sic is None:
                self.last_unmatched.append(ticker)
                continue
            sector = sic_to_gics_sector(sic)
            if sector is None:
                self.last_unmapped_sic[ticker] = (sic, desc)
                continue
            found[security.composite_figi] = GicsClassification(
                composite_figi=security.composite_figi,
                sector_name=sector,
                industry_group_name=None,
                industry_name=None,
                source="sec_sic",
            )
        return found
