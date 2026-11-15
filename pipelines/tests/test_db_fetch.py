"""db.fetch decodes ARRAY/MAP/STRUCT columns the connector returns as JSON text (no pyarrow)."""
import db


class FakeCursor:
    def __init__(self, description, rows):
        self.description, self._rows = description, rows

    def execute(self, query):
        pass

    def fetchall(self):
        return self._rows


def test_array_column_returned_as_json_text_is_decoded():
    cur = FakeCursor([("geometry", "array"), ("event_ids", "array")], [("[[51.9,4.1],[52.0,4.2]]", '["E-1"]')])
    assert db.fetch(cur, "q") == [{"geometry": [[51.9, 4.1], [52.0, 4.2]], "event_ids": ["E-1"]}]


def test_string_column_that_looks_like_json_is_left_alone():
    cur = FakeCursor([("summary", "string")], [('["not an array"]',)])
    assert db.fetch(cur, "q") == [{"summary": '["not an array"]'}]


def test_native_tuples_become_lists_and_nulls_stay_null():
    cur = FakeCursor([("geometry", "array"), ("error", "string")], [(((1.0, 2.0), (3.0, 4.0)), None)])
    assert db.fetch(cur, "q") == [{"geometry": [[1.0, 2.0], [3.0, 4.0]], "error": None}]


def test_description_without_type_code_still_works():
    cur = FakeCursor([("n",)], [(3,)])
    assert db.fetch(cur, "q") == [{"n": 3}]
