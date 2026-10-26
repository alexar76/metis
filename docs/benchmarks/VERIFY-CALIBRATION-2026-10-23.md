# Is verify_score a probability? (2026-10-23)

An outside review asked the right question: the hub pays when a verdict passes with
`verify_score >= 0.7`, which treats the score as "the answer is right with at least this
probability". If the jury said 0.95 to answers that were right 70% of the time, that bar would
mean little. Until today nothing in the repository measured it.

`metis/verify/calibration.py` now does: the Brier score, the expected calibration error (ECE),
the reliability table, and what the bar would have paid. Run it on any recorded jury votes:

```bash
python3 metis/bench/jury_3v5.py calibration --votes metis/bench/results/*.json
```

A score belongs to the side that won, so a `fail` at 0.9 says the answer is right with 0.1.

## What the recorded runs show

Data: the five jury runs of 2026-10-03 in `bench/results/` (see `bench/jury_3v5.py`). Each run
judges the same 12 checkable tasks twice, once with the right output and once with a planted
wrong one: 24 verdicts per run, 120 in all. Pooled, 10 bins of P(answer is right):

| Stated P(right) | Verdicts | Mean stated | Share actually right |
|---|---:|---:|---:|
| [0.0, 0.1) | 25 | 0.000 | 0.000 |
| [0.1, 0.2) | 25 | 0.188 | 0.000 |
| [0.3, 0.4) | 1 | 0.333 | 0.000 |
| [0.4, 0.5) | 2 | 0.475 | 0.000 |
| [0.5, 0.6) | 2 | 0.500 | 0.500 |
| [0.6, 0.7) | 8 | 0.615 | 0.375 |
| [0.8, 0.9) | 17 | 0.812 | 0.941 |
| [0.9, 1.0] | 40 | 0.998 | 1.000 |

Brier 0.047, ECE 0.085 (5 bins). At the 0.7 bar the jury would have paid 57 answers, 1 of
them wrong, and held back 4 right ones.

Read it as follows:

- **Above the bar the score is cautious, not generous.** Verdicts stated at 0.8 to 0.9 were
  right 94% of the time. Most of them are 4 of 5 seats agreeing with the fifth abstaining:
  the score counts agreement over the whole roster, so an abstention lowers it even when every
  vote cast agrees.
- **Between 0.4 and 0.7 it is over-confident**: 12 verdicts stated about 0.58, a third of
  them right. Those are split juries, and all of them are below the bar, so none were paid.
- **On wrong answers it is under-confident**: 25 fails left a stated 0.19 chance that the
  answer was right; none was.
- **The one paid wrong answer** is task 5 in the medium-reasoning Mistral run, asked in its
  original wording ("how many days are there from 2026-01-01 to 2026-03-14?"): five of six
  seats accepted 73 for 72. Counting both ends is a fair reading of that wording, which is why
  the task was reworded after the first runs; `tally --exclude-case 5` leaves it out.

## What this does not show

- **It is not a held-out set from real traffic.** The wrong outputs are planted and mostly
  plain (a wrong sum, a wrong capital); a subtly wrong answer from a capable model is harder
  to catch, and the error rate on such answers is unknown.
- **The 120 verdicts are not independent.** They are the same 24 cases judged five times by
  rosters that share four seats.
- **It covers the jury route only**, the one Pay-on-Verified uses. The council's own
  `verify_score` (critic and grounded checks in `metis/verify/`) is not measured here.
- **Bins are small.** Several hold one or two verdicts; the table prints counts so a 100%
  from two cases is not read as a property of the jury.

So the honest claim is narrower than "verify_score is calibrated": on easy, checkable tasks
the score separates right from wrong answers well, errs on the cautious side above the bar,
and over-states confidence only in the split range the bar already excludes. The next step is
the one the review named: a held-out set of real answers with known truth, large enough for
the 0.7 to 0.9 range to hold dozens of cases, measured with the same command.
