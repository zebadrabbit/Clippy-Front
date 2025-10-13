def test_safe_count_filter(app):
    # Access Jinja environment and the filter
    f = app.jinja_env.filters.get("safe_count")
    assert f is not None
    # Works on list
    assert f([1, 2, 3]) == 3
    # Works on None
    assert f(None) == 0

    # Works on object with count()
    class Dummy:
        def count(self):
            return 7

    assert f(Dummy()) == 7
