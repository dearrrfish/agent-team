from __future__ import annotations

import tempfile
import tomllib
import unittest
from dataclasses import replace
from importlib import resources
from pathlib import Path
from unittest.mock import patch

from agent_team.adapters import _mapped_role, _render_agent, render_target
from agent_team.config import (
    DEFAULT_TEAM_TOML,
    load_builtin_roles,
    load_roles,
    load_team_config,
    parse_team_config,
    resolve_target_profile,
)
from agent_team.diagnostics import ValidationFailure
from agent_team.models import PRESETS, TARGETS, RoleOverride


class RoleOverrideTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / 'home'
        self.project = self.root / 'project'
        self.user = self.home / '.agent-team'
        self.user.mkdir(parents=True)
        (self.project / '.agent-team').mkdir(parents=True)
        home_patch = patch('pathlib.Path.home', return_value=self.home)
        home_patch.start()
        self.addCleanup(home_patch.stop)
        self.write_project('schema_version = 1\n')

    def write_project(self, text):
        (self.project / '.agent-team/team.toml').write_text(text)

    def write_user(self, text):
        (self.user / 'team.toml').write_text(text)

    def roles(self):
        config = load_team_config(self.project)
        return config, {r.role_id: r for r in load_roles(config, self.project)}

    def make_role(self, scope, role_id, instructions):
        source = resources.files('agent_team.assets').joinpath(
            'definitions', 'roles', 'implementer', 'role.toml'
        ).read_text()
        directory = scope / 'definitions' / role_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'role.toml').write_text(source.replace('id = "implementer"', f'id = "{role_id}"'))
        (directory / 'instructions.md').write_text(instructions)
        return directory / 'role.toml'

    def test_defaults_optional_and_empty_tables(self):
        config = parse_team_config(tomllib.loads(DEFAULT_TEAM_TOML), self.project)
        self.assertEqual(config.role_overrides, {})
        self.assertEqual(RoleOverride(), RoleOverride(None, None))
        self.write_project('[roles.implementer]\n')
        config, roles = self.roles()
        self.assertEqual(config.role_overrides, {'implementer': RoleOverride()})
        self.assertEqual(roles['implementer'].routing_override_origins, {})
        self.assertEqual(roles['implementer'], load_builtin_roles()[3])

    def test_leaf_inheritance_and_opt_out(self):
        self.write_user('[roles.implementer]\nmodel_class = "fast"\neffort = "low"\n')
        self.write_project('[roles.implementer]\nmodel_class = "balanced"\n')
        config, roles = self.roles()
        self.assertEqual(config.role_overrides['implementer'], RoleOverride('balanced', 'low'))
        role = roles['implementer']
        self.assertEqual((role.model_class, role.effort), ('balanced', 'low'))
        self.assertEqual(role.routing_override_origins, {'model_class': 'project', 'effort': 'user'})
        self.write_project('inherit_user_defaults = false\n[roles.implementer]\nmodel_class = "fast"\n')
        config, roles = self.roles()
        self.assertEqual(config.role_overrides['implementer'], RoleOverride('fast', None))
        self.assertEqual(roles['implementer'].effort, load_builtin_roles()[3].effort)
        self.assertEqual(roles['implementer'].routing_override_origins, {'model_class': 'project'})

    def test_strict_validation_including_masked_layers(self):
        invalid = (
            'roles = 2', 'roles = []', '[roles.implementer]\nmodel_class = true',
            '[roles.implementer]\neffort = 3', '[roles.implementer]\nmodel_class = "unknown"',
            '[roles.implementer]\neffort = "xhigh"', '[roles.implementer]\ninstructions = "new"',
            '[roles."Wrong ID"]\nmodel_class = "fast"', 'roles = {implementer = "fast"}',
        )
        for text in invalid:
            with self.subTest(text=text):
                self.write_user(text)
                self.write_project('[roles.implementer]\nmodel_class = "deep"\neffort = "high"\n')
                with self.assertRaises(ValidationFailure):
                    load_team_config(self.project)
                self.write_user('')
                self.write_project(text)
                with self.assertRaises(ValidationFailure):
                    load_team_config(self.project)

    def test_whole_definition_precedence_then_overlay(self):
        self.make_role(self.user, 'implementer', 'user instructions\n')
        project_source = self.make_role(self.project, 'implementer', 'project instructions\n')
        self.write_user('role_sources = ["definitions"]\n[roles.implementer]\neffort = "low"\n')
        _config, roles = self.roles()
        self.assertEqual(roles['implementer'].instructions, 'user instructions\n')
        self.write_project('role_sources = ["definitions"]\n[roles.implementer]\nmodel_class = "fast"\n')
        _config, roles = self.roles()
        role = roles['implementer']
        base = load_builtin_roles()[3]
        self.assertEqual(role.instructions, 'project instructions\n')
        self.assertEqual(role.source, str(project_source))
        self.assertEqual((role.write_policy, role.capabilities, role.delegation),
                         (base.write_policy, base.capabilities, base.delegation))
        self.assertEqual(role.routing_override_origins, {'model_class': 'project', 'effort': 'user'})

    def test_custom_role_supported_and_missing_role_rejected_after_sources(self):
        self.write_user('[roles.analyst]\nmodel_class = "fast"\neffort = "low"\n')
        self.make_role(self.project, 'analyst', 'custom instructions')
        self.write_project('role_sources = ["definitions"]\n')
        config, roles = self.roles()
        self.assertEqual(roles['analyst'].model_class, 'fast')
        self.assertEqual(roles['analyst'].routing_override_origins, {'model_class': 'user', 'effort': 'user'})
        self.write_project('[roles.absent]\n')
        config = load_team_config(self.project)
        with self.assertRaises(ValidationFailure) as error:
            load_roles(config, self.project)
        self.assertTrue(any(d.path == 'roles.absent' for d in error.exception.diagnostics))

    def test_all_targets_and_presets_overlay_rendering(self):
        self.write_project('[roles.implementer]\nmodel_class = "fast"\neffort = "low"\n')
        config, roles = self.roles()
        for target in TARGETS:
            profile = resolve_target_profile(config, target, self.project)
            for preset_name in PRESETS:
                with self.subTest(target=target, preset=preset_name):
                    preset = profile.presets[preset_name]
                    model, effort = _mapped_role(profile, preset_name, roles['implementer'])
                    self.assertEqual(model, preset.models['fast'])
                    expected = preset.effort.get('low') if profile.supports_effort else None
                    if model in profile.models_without_effort:
                        expected = None
                    self.assertEqual(effort, expected)
                    output = render_target(target, config, self.project, preset_name)
                    content = next(value for path, value in output.items()
                                   if 'implementer' in str(path))
                    self.assertIn(model, content)
                    if effort:
                        self.assertIn(effort, content)

    def test_no_overlay_rendered_output_compatibility(self):
        config, roles = self.roles()
        for target in TARGETS:
            profile = resolve_target_profile(config, target, self.project)
            for preset_name in PRESETS:
                preset = profile.presets[preset_name]
                for role in roles.values():
                    with self.subTest(target=target, preset=preset_name, role=role.role_id):
                        model = (preset.coordinator_model if role.role_id == 'coordinator'
                                 else preset.models[role.model_class])
                        effort = (preset.coordinator_effort if role.role_id == 'coordinator'
                                  else preset.effort.get(role.effort) if profile.supports_effort else None)
                        if model in profile.models_without_effort:
                            effort = None
                        self.assertEqual(_mapped_role(profile, preset_name, role), (model, effort))
                        baseline = load_builtin_roles()[list(roles).index(role.role_id)]
                        self.assertEqual(_render_agent(target, role, profile, preset_name),
                                         _render_agent(target, baseline, profile, preset_name))

    def test_coordinator_independent_explicit_and_same_base_fields(self):
        config, roles = self.roles()
        base = roles['coordinator']
        profile = resolve_target_profile(config, 'codex', self.project)
        preset = profile.presets['balanced']
        profile = replace(profile, presets={
            **profile.presets,
            'balanced': replace(preset, coordinator_model='dedicated-model', coordinator_effort='medium'),
        })
        for model_class, effort in ((None, None), ('fast', None), (None, 'low'),
                                    ('balanced', 'medium'), (base.model_class, base.effort)):
            with self.subTest(model_class=model_class, effort=effort):
                fields = {key: value for key, value in {'model_class': model_class, 'effort': effort}.items()
                          if value is not None}
                role = replace(base, **fields, routing_override_origins=dict.fromkeys(fields, 'project'))
                expected_model = preset.models[model_class] if model_class else 'dedicated-model'
                expected_effort = preset.effort[effort] if effort else 'medium'
                self.assertEqual(_mapped_role(profile, 'balanced', role), (expected_model, expected_effort))

    def test_model_effort_suppression_and_no_effort_target(self):
        self.write_project('[roles.coordinator]\nmodel_class = "fast"\neffort = "high"\n')
        config, roles = self.roles()
        profile = resolve_target_profile(config, 'codex', self.project)
        preset = profile.presets['balanced']
        profile = replace(profile, models_without_effort=(preset.models['fast'],))
        self.assertEqual(_mapped_role(profile, 'balanced', roles['coordinator']), (preset.models['fast'], None))
        profile = replace(profile, supports_effort=False, models_without_effort=())
        self.assertEqual(_mapped_role(profile, 'balanced', roles['coordinator']), (preset.models['fast'], None))
        self.assertIsNone(_mapped_role(profile, 'balanced', roles['implementer'])[1])

    def target_roles(self, target):
        config = load_team_config(self.project)
        return config, {r.role_id: r for r in load_roles(config, self.project, target)}

    def test_target_isolation_fallback_inheritance_and_specificity(self):
        self.write_user('[roles.implementer.targets.codex]\nmodel_class = "fast"\neffort = "low"\n')
        self.write_project('[roles.implementer]\nmodel_class = "deep"\neffort = "high"\n'
                           '[roles.implementer.targets.codex]\neffort = "medium"\n'
                           '[roles.implementer.targets.claude]\nmodel_class = "balanced"\n')
        config, roles = self.target_roles('codex')
        self.assertEqual(config.target_role_overrides['codex']['implementer'], RoleOverride('fast', 'medium'))
        role = roles['implementer']
        self.assertEqual((role.model_class, role.effort), ('fast', 'medium'))
        self.assertEqual(role.routing_override_origins, {'model_class': 'user', 'effort': 'project'})
        _, roles = self.target_roles('claude')
        self.assertEqual((roles['implementer'].model_class, roles['implementer'].effort), ('balanced', 'high'))
        _, roles = self.target_roles('antigravity')
        self.assertEqual((roles['implementer'].model_class, roles['implementer'].effort), ('deep', 'high'))
        _, roles = self.roles()
        self.assertEqual((roles['implementer'].model_class, roles['implementer'].effort), ('deep', 'high'))
        self.write_project('inherit_user_defaults = false\n[roles.implementer.targets.codex]\neffort = "medium"\n')
        config, roles = self.target_roles('codex')
        self.assertEqual(config.target_role_overrides['codex']['implementer'], RoleOverride(None, 'medium'))
        self.assertEqual(roles['implementer'].model_class, load_builtin_roles()[3].model_class)

    def test_target_strict_validation_masked_layers(self):
        invalid = (
            'targets = true', 'targets = []', 'targets = {codex = 1}',
            '[roles.implementer.targets.unknown]\neffort = "low"',
            '[roles.implementer.targets.codex]\nmodel_class = true',
            '[roles.implementer.targets.codex]\neffort = "xhigh"',
            '[roles.implementer.targets.codex]\neffort = 3',
            '[roles.implementer.targets.codex]\nmodel_class = "unknown"',
            '[roles.implementer.targets.codex]\ntargets = {}',
            '[roles.implementer.targets.codex]\ninstructions = "bad"',
        )
        for text in invalid:
            if text.startswith('targets'):
                text = '[roles.implementer]\n' + text
            with self.subTest(text=text):
                self.write_user(text)
                self.write_project('[roles.implementer.targets.codex]\nmodel_class = "deep"\neffort = "high"\n')
                with self.assertRaises(ValidationFailure):
                    load_team_config(self.project)
                self.write_user('')
                self.write_project(text)
                with self.assertRaises(ValidationFailure):
                    load_team_config(self.project)
        data = tomllib.loads(DEFAULT_TEAM_TOML)
        data['enabled_targets'] = ['claude']
        del data['target_profiles']['codex']
        data['roles'] = {'implementer': {'targets': {'codex': {'effort': 'low'}}}}
        with self.assertRaises(ValidationFailure):
            parse_team_config(data, self.project)

    def test_unselected_unknown_role_and_invalid_target(self):
        self.write_project('[roles.absent.targets.claude]\n')
        config = load_team_config(self.project)
        for target in (None, 'codex', 'claude'):
            with self.subTest(target=target), self.assertRaises(ValidationFailure):
                load_roles(config, self.project, target)
        self.write_project('schema_version = 1\n')
        config = load_team_config(self.project)
        with self.assertRaises(ValidationFailure):
            load_roles(config, self.project, 'unknown')
        config = replace(config, target_profiles={'claude': 'builtin:claude'})
        with self.assertRaises(ValidationFailure):
            load_roles(config, self.project, 'codex')

    def test_target_custom_role_preserves_complete_definition(self):
        source = self.make_role(self.project, 'analyst', 'custom instructions')
        self.write_user('[roles.analyst.targets.codex]\nmodel_class = "fast"\n')
        self.write_project('role_sources = ["definitions"]\n[roles.analyst]\neffort = "low"\n')
        _, roles = self.target_roles('codex')
        role = roles['analyst']
        self.assertEqual((role.model_class, role.effort), ('fast', 'low'))
        self.assertEqual((role.source, role.instructions), (str(source), 'custom instructions'))
        base = load_builtin_roles()[3]
        self.assertEqual((role.write_policy, role.capabilities, role.delegation),
                         (base.write_policy, base.capabilities, base.delegation))

    def test_target_coordinator_pins_independent_fields_and_suppression(self):
        base = load_builtin_roles()[0]
        for fields in ({'model_class': base.model_class}, {'effort': base.effort}):
            with self.subTest(fields=fields):
                self.write_project('[roles.coordinator.targets.codex]\n' +
                                   ''.join(f'{key} = "{value}"\n' for key, value in fields.items()))
                config, roles = self.target_roles('codex')
                profile = resolve_target_profile(config, 'codex', self.project)
                preset = profile.presets['balanced']
                profile = replace(profile, presets={**profile.presets, 'balanced': replace(
                    preset, coordinator_model='dedicated-model', coordinator_effort='dedicated-effort')})
                role = roles['coordinator']
                self.assertEqual(role.routing_override_origins, dict.fromkeys(fields, 'project'))
                expected_model = preset.models[base.model_class] if 'model_class' in fields else 'dedicated-model'
                expected_effort = preset.effort[base.effort] if 'effort' in fields else 'dedicated-effort'
                self.assertEqual(_mapped_role(profile, 'balanced', role), (expected_model, expected_effort))
                profile = replace(profile, models_without_effort=(expected_model,))
                self.assertEqual(_mapped_role(profile, 'balanced', role), (expected_model, None))
                profile = replace(profile, models_without_effort=(), supports_effort=False)
                self.assertEqual(_mapped_role(profile, 'balanced', role), (expected_model, None))
                _, other_roles = self.target_roles('claude')
                self.assertEqual(other_roles['coordinator'].routing_override_origins, {})

    def test_target_rendering_all_targets_and_presets(self):
        classes = dict(zip(TARGETS, ('fast', 'balanced', 'deep'), strict=True))
        self.write_project(''.join(
            f'[roles.implementer.targets.{target}]\nmodel_class = "{model_class}"\neffort = "low"\n'
            for target, model_class in classes.items()))
        config = load_team_config(self.project)
        for target, model_class in classes.items():
            profile = resolve_target_profile(config, target, self.project)
            for preset in PRESETS:
                with self.subTest(target=target, preset=preset):
                    rendered = render_target(target, config, self.project, preset)
                    content = next(value for path, value in rendered.items() if 'implementer' in str(path))
                    self.assertIn(profile.presets[preset].models[model_class], content)


if __name__ == '__main__':
    unittest.main()
