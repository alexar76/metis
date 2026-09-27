"""deploy/prod.jury.example.yaml is copied into production by hand, so it is tested here.

Both fragments must load as real RuntimeConfigs (a roster that is not a jury would fail
at the Metis host's next restart, not here), and the two courts must not share a vendor:
an appeal heard by the lab that decided the first instance is a re-roll, not an appeal.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from metis.config import RuntimeConfig
from metis.verify import jury

EXAMPLE = Path(__file__).resolve().parents[1] / "deploy" / "prod.jury.example.yaml"


def _fragments():
    data = yaml.safe_load(EXAMPLE.read_text())
    return data["metis_1"], data["metis_2"]


def _vendors(cfg: RuntimeConfig) -> set:
    return {seat.vendor for seat in jury.juror_seats(cfg)}


def test_both_fragments_load_as_juries():
    for fragment in _fragments():
        cfg = RuntimeConfig(**fragment)
        assert cfg.jury_default_for_verify is True
        assert len(cfg.jury_models) >= cfg.jury_min_vendors >= 3
        assert len(cfg.jury_models) % 2 == 1          # an even roster only adds splits


def test_the_appeal_court_shares_no_vendor_with_the_first_instance():
    first, appeal = (RuntimeConfig(**f) for f in _fragments())
    assert _vendors(first).isdisjoint(_vendors(appeal)), (_vendors(first), _vendors(appeal))


def test_the_first_instance_is_not_all_behind_one_gateway():
    first, _ = (RuntimeConfig(**f) for f in _fragments())
    assert len({seat.slot.base_url for seat in jury.juror_seats(first)}) >= 2


def test_every_seat_reads_its_key_from_the_environment():
    for fragment in _fragments():
        for juror in RuntimeConfig(**fragment).jury_models:
            assert juror.api_key_env and not juror.api_key, juror.model
