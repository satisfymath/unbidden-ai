from humanize.filesize import naturalsize
from humanize.number import ordinal
from humanize.number import intcomma
from humanize.number import intword
from humanize.number import apnumber
from humanize.number import fractional
from humanize.time import naturaldelta
from humanize.lists import natural_list
import datetime as dt
from hypothesis import given, settings, strategies as st


@settings(max_examples=300, deadline=None)
@given(
    value=st.one_of(st.integers(), st.floats(allow_nan=False, allow_infinity=False), st.text()),
    binary=st.booleans(),
    gnu=st.booleans(),
    format=st.text(),
)
def test_naturalsize_never_crashes(value, binary, gnu, format):
    naturalsize(value, binary=binary, gnu=gnu, format=format)


@settings(max_examples=300, deadline=None)
@given(
    value=st.one_of(st.integers(), st.floats(allow_nan=False, allow_infinity=False), st.text()),
    gender=st.text(),
)
def test_ordinal_never_crashes(value, gender):
    ordinal(value, gender=gender)


@settings(max_examples=300, deadline=None)
@given(
    value=st.one_of(st.integers(), st.floats(allow_nan=False, allow_infinity=False), st.text()),
    ndigits=st.one_of(st.none(), st.integers()),
)
def test_intcomma_never_crashes(value, ndigits):
    intcomma(value, ndigits=ndigits)


@settings(max_examples=300, deadline=None)
@given(
    value=st.one_of(st.integers(), st.floats(allow_nan=False, allow_infinity=False), st.text()),
    format=st.text(),
)
def test_intword_never_crashes(value, format):
    intword(value, format=format)


@settings(max_examples=300, deadline=None)
@given(value=st.one_of(st.integers(), st.floats(allow_nan=False, allow_infinity=False), st.text()))
def test_apnumber_never_crashes(value):
    apnumber(value)


@settings(max_examples=300, deadline=None)
@given(value=st.one_of(st.integers(), st.floats(allow_nan=False, allow_infinity=False), st.text()))
def test_fractional_never_crashes(value):
    fractional(value)


@settings(max_examples=300, deadline=None)
@given(
    value=st.one_of(
        st.integers(),
        st.floats(allow_nan=False, allow_infinity=False),
        st.builds(
            dt.timedelta,
            days=st.integers(min_value=-1000000, max_value=1000000),
            seconds=st.integers(min_value=-1000000, max_value=1000000),
            microseconds=st.integers(min_value=-1000000, max_value=1000000),
        ),
    ),
    months=st.booleans(),
    minimum_unit=st.text(),
)
def test_naturaldelta_never_crashes(value, months, minimum_unit):
    naturaldelta(value, months=months, minimum_unit=minimum_unit)


@settings(max_examples=300, deadline=None)
@given(items=st.one_of(st.lists(st.text()), st.text(), st.lists(st.integers()), st.lists(st.none())))
def test_natural_list_never_crashes(items):
    natural_list(items)
