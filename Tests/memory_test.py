"""
Tests for the memory package.

Run: python -m Tests.memory_test
"""

from memory import short_term


def test_add_and_get_context():

    short_term.clear()

    short_term.add_exchange("hello", "hi there")
    short_term.add_exchange("what is 2 plus 2", "four")

    context = short_term.get_context()

    assert "hello" in context
    assert "four" in context

    print("PASS: memory stores and returns context")


def test_maxlen_eviction():

    short_term.clear()

    for i in range(short_term.MAX_EXCHANGES + 5):
        short_term.add_exchange(f"q{i}", f"a{i}")

    assert len(short_term.get_exchanges()) == short_term.MAX_EXCHANGES

    print("PASS: memory evicts old exchanges beyond max length")


def test_clear():

    short_term.add_exchange("x", "y")

    short_term.clear()

    assert short_term.get_exchanges() == []
    assert short_term.get_summary() == ""

    print("PASS: memory clear resets state")


if __name__ == "__main__":

    test_add_and_get_context()
    test_maxlen_eviction()
    test_clear()

    print("\nAll memory tests done.")
