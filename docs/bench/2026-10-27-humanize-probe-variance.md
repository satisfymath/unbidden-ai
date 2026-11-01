# humanize: is the probe's KeyError real, and how often would a probe find it?

Record: `2026-10-27-humanize-probe-variance.json` (seeds, test digests, image, model, prompt, outputs).
humanize at `6b817b963dbb`, image `unbidden-deps-python` for Python 3.11, Muse Spark 1.3 (profile frontier).

| Measurement | Result |
|---|---|
| Direct: `naturaldelta(0, minimum_unit='')` in the sandbox | `KeyError: ''`, deterministic |
| Replay of the test file that found it, Hypothesis seeds 0-9 | found 10/10 |
| Fresh probes (new tests each time, seed 0), this study | found 0/10 |
| All fresh probes of humanize so far (method checks 4 and 5, pilot, this study) | 1/13 = 8 % (95 % CI 1.4 %-33 %) |
| Cost of the 10 fresh probes | US$0.153, 10 calls, 8.2k tokens in, 33.5k out |

**Why fresh probes miss it.** In 10 of 10, the model drew `minimum_unit` only from the documented units
(`sampled_from(["seconds", "minutes", ...])`). The probe that found it used `st.text()`. The probe asks for crashes on
inputs a caller could pass; an undocumented unit is an invalid argument.

**What the finding is.** humanize validates `minimum_unit` and raises `ValueError` for a unit it does not support
("Minimum unit 'minutes' not supported"), but an unknown string such as `''` raises `KeyError` from a dictionary
lookup. Real and reproducible (L2), and narrow: inconsistent validation of an invalid argument, not a crash on valid
input. It is kept as an observation, not promoted, and the probe prompt is not changed to chase it.

**For the benchmark.** One probe per commit is a sample. A repository where the probe finds nothing is reported as
"nothing found by one probe", not as "no crash exists".
