"""Property-based agreement scoring tests."""

from hypothesis import given, strategies as st

from metis.pipeline.agreement import compute_agreement, compute_proposer_agreement


@given(st.text(min_size=1, max_size=100))
def test_agreement_single_output_bounded(goal: str):
    score = compute_agreement([{"goal": goal, "constraints": []}])
    assert 0.0 <= score <= 1.0
    assert score == 1.0


@given(
    st.lists(
        st.fixed_dictionaries({
            "goal": st.text(min_size=1, max_size=50),
            "constraints": st.lists(st.text(min_size=1, max_size=20), max_size=3),
        }),
        min_size=2,
        max_size=5,
    )
)
def test_agreement_always_bounded(outputs):
    score = compute_agreement(outputs)
    assert 0.0 <= score <= 1.0


@given(
    st.lists(st.text(min_size=1, max_size=80), min_size=2, max_size=4)
)
def test_proposer_agreement_bounded(proposals):
    score = compute_proposer_agreement(proposals)
    assert 0.0 <= score <= 1.0


def test_identical_proposals_max_agreement():
    text = "The answer is forty-two."
    assert compute_proposer_agreement([text, text, text]) == 1.0
