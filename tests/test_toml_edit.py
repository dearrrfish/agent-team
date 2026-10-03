import tomllib
import unittest

from agent_team.diagnostics import ValidationFailure
from agent_team.toml_edit import upsert_strings


class TomlEditTests(unittest.TestCase):
    def test_replacement_preserves_spacing_comments_and_other_values(self) -> None:
        original = '# intro\n[models] # header\nmodel  =  "old"   # keep\ncount = 4\n'
        result = upsert_strings(original, {("models", "model"): "new"})
        self.assertEqual(result, original.replace('"old"', '"new"'))

    def test_literal_string_replacement_and_unicode_escapes(self) -> None:
        value = 'new "quoted" \\ model\n😺\x7f'
        original = "name = 'old' # comment\n"
        result = upsert_strings(original, {("name",): value})
        self.assertEqual(tomllib.loads(result), {"name": value})
        self.assertTrue(result.endswith(" # comment\n"))

    def test_missing_root_key_precedes_first_table(self) -> None:
        original = '# top\n[models]\nname = "old"\n'
        result = upsert_strings(original, {("root",): "new"})
        self.assertEqual(result, '# top\nroot = "new"\n[models]\nname = "old"\n')

    def test_insert_leaf_in_existing_table_before_next_header(self) -> None:
        original = '[models]\nname = "old"\n\n[other]\nkeep = true\n'
        result = upsert_strings(original, {("models", "added"): "new"})
        self.assertEqual(
            result,
            '[models]\nname = "old"\n\nadded = "new"\n[other]\nkeep = true\n',
        )

    def test_new_nested_tables_and_implicit_parent(self) -> None:
        original = '[models.deep]\nname = "old"\n'
        changes = {
            ("models", "balanced", "name"): "balanced",
            ("models", "coordinator"): "main",
            ("models", "balanced", "effort"): "medium",
        }
        result = upsert_strings(original, changes)
        self.assertEqual(
            tomllib.loads(result),
            {
                "models": {
                    "deep": {"name": "old"},
                    "balanced": {"name": "balanced", "effort": "medium"},
                    "coordinator": "main",
                }
            },
        )
        self.assertTrue(result.startswith(original))

    def test_existing_quoted_components_and_insert_quoted_keys(self) -> None:
        original = '["models.with.dot".\'space key\'] # keep\n"a=b" = \'old\'\n'
        result = upsert_strings(
            original,
            {
                ("models.with.dot", "space key", "a=b"): "new",
                ("models.with.dot", "space key", "#added"): "yes",
                ("new.table", "", 'quote"key'): "new",
            },
        )
        parsed = tomllib.loads(result)
        self.assertEqual(parsed["models.with.dot"]["space key"], {"a=b": "new", "#added": "yes"})
        self.assertEqual(parsed["new.table"][""]['quote"key'], "new")
        self.assertTrue(result.startswith(original.replace("'old'", '"new"')))

    def test_multiline_strings_and_array_values_do_not_create_fake_keys(self) -> None:
        original = '''description = """
[models]
name = "fake"
"""
literal = ''' + "'''\n[models]\nname = \"fake too\"\n'''\n" + '''array = [
  "name = 'inside'", # bracket ] ignored
  {name = "nested"},
]
[models]
name = "real" # keep
'''
        result = upsert_strings(original, {("models", "name"): "new"})
        self.assertEqual(result, original.replace('name = "real"', 'name = "new"'))

    def test_no_op_and_repeated_edits_preserve_exact_text(self) -> None:
        original = "[models]\nname = 'old' # keep\n"
        self.assertEqual(upsert_strings(original, {}), original)
        self.assertEqual(upsert_strings(original, {("models", "name"): "old"}), original)
        changes = {("models", "name"): "new", ("models", "effort"): "high"}
        once = upsert_strings(original, changes)
        self.assertEqual(upsert_strings(once, changes), once)

    def test_empty_document_and_missing_final_newline(self) -> None:
        self.assertEqual(upsert_strings("", {("name",): "new"}), 'name = "new"\n')
        result = upsert_strings('name = "old"', {("added",): "new"})
        self.assertEqual(result, 'name = "old"\nadded = "new"\n')

    def test_crlf_is_preserved_for_insertions(self) -> None:
        original = '[models]\r\nname = "old"\r\n'
        result = upsert_strings(original, {("models", "effort"): "high"})
        self.assertEqual(result, original + 'effort = "high"\r\n')

    def test_affected_inline_table_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationFailure, "inline table"):
            upsert_strings('models = { name = "old" }\n', {("models", "name"): "new"})
        with self.assertRaisesRegex(ValidationFailure, "inline table"):
            upsert_strings('models = {}\n', {("models", "name"): "new"})

    def test_affected_dotted_assignment_is_rejected(self) -> None:
        for path in (("models", "name"), ("models", "effort")):
            with self.subTest(path=path), self.assertRaisesRegex(ValidationFailure, "dotted assignment"):
                upsert_strings('models.name = "old"\n', {path: "new"})

    def test_affected_multiline_string_is_rejected(self) -> None:
        for literal in ('"""old\nmodel"""', "'''old\nmodel'''"):
            with self.subTest(literal=literal), self.assertRaisesRegex(
                ValidationFailure, "single-line TOML string"
            ):
                upsert_strings(f"name = {literal}\n", {("name",): "new"})

    def test_unrelated_exotic_layout_is_preserved(self) -> None:
        original = 'inline = { name = "old" }\ndotted.name = "old"\n[[array]]\nname = "old"\n'
        result = upsert_strings(original, {("root",): "new", ("new", "name"): "new"})
        self.assertEqual(result.replace('root = "new"\n', '').split('\n[new]')[0], original)
        parsed = tomllib.loads(result)
        self.assertEqual(parsed["array"], [{"name": "old"}])
        self.assertEqual(parsed["root"], "new")

    def test_nonstring_leaves_and_scalar_parents_are_rejected(self) -> None:
        for original, changes in (
            ("name = 4\n", {("name",): "new"}),
            ('name = "old"\n', {("name", "nested"): "new"}),
            ('[[array]]\nname = "old"\n', {("array", "name"): "new"}),
        ):
            with self.subTest(original=original), self.assertRaises(ValidationFailure):
                upsert_strings(original, changes)

    def test_malformed_original_is_rejected_even_without_changes(self) -> None:
        with self.assertRaisesRegex(ValidationFailure, "Invalid original TOML"):
            upsert_strings('[bad\nname = "x"', {})

    def test_invalid_change_contract_is_rejected(self) -> None:
        for changes in ({(): "x"}, {("name",): 4}, {"name": "x"}, {(4,): "x"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationFailure):
                upsert_strings("", changes)

    def test_insert_at_eof_table_with_new_table_has_correct_ownership(self) -> None:
        original = '[existing]\nname = "old"'
        result = upsert_strings(
            original,
            {("existing", "added"): "yes", ("new", "name"): "new"},
        )
        self.assertEqual(
            tomllib.loads(result),
            {"existing": {"name": "old", "added": "yes"}, "new": {"name": "new"}},
        )

    def test_unrelated_nan_remains_semantically_unchanged(self) -> None:
        original = 'special = nan\nname = "old"\n'
        self.assertEqual(upsert_strings(original, {("name",): "new"}), original.replace('"old"', '"new"'))

    def test_multiline_closing_quote_runs_are_handled(self) -> None:
        for quotes in ('"', "'"):
            for extra in (1, 2):
                original = f"description = {quotes * 3}text{quotes * (3 + extra)}\nname = 'old'\n"
                with self.subTest(quotes=quotes, extra=extra):
                    result = upsert_strings(original, {("name",): "new"})
                    self.assertEqual(result, original.replace("'old'", '"new"'))


if __name__ == "__main__":
    unittest.main()
