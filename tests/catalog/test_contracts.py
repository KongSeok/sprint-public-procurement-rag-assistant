from __future__ import annotations

import json
import unittest
from pathlib import Path


class CatalogSchemaTests(unittest.TestCase):
    def test_catalog_schemas_parse_and_are_closed(self) -> None:
        root = Path(__file__).resolve().parents[2]
        for name in (
            "metadata-fact.schema.json",
            "catalog-query.schema.json",
            "catalog-response.schema.json",
        ):
            with self.subTest(name=name):
                schema = json.loads((root / "contracts" / name).read_text(encoding="utf-8"))
                self.assertEqual(
                    schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
                )
                self.assertEqual(schema["type"], "object")
                self.assertFalse(schema["additionalProperties"])

    def test_fact_contract_has_exact_fields_states_and_private_locator_marker(self) -> None:
        root = Path(__file__).resolve().parents[2]
        schema = json.loads(
            (root / "contracts" / "metadata-fact.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertEqual(len(schema["properties"]["field"]["enum"]), 12)
        self.assertEqual(len(schema["properties"]["state"]["enum"]), 10)
        locator = schema["$defs"]["evidenceRef"]["properties"]["locator"]
        self.assertTrue(locator["writeOnly"])


if __name__ == "__main__":
    unittest.main()
