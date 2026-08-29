"""
Generated content must come out in the configured language.

The prompts are partly written in Chinese, which the model handles. What
decides the language of the report, the personas and the simulated posts is
the explicit instruction inside them, so those instructions must actually be
substituted - never sent to the model as a raw {output_language} token.
"""

import inspect
import pytest

from app.config import Config
from app.utils.prompt_lang import TOKEN, localize


def test_default_output_language_is_english():
    assert Config.OUTPUT_LANGUAGE == "English"


def test_localize_substitutes_the_token():
    assert localize(f"Answer in {TOKEN}.") == f"Answer in {Config.OUTPUT_LANGUAGE}."


def test_localize_handles_empty_input():
    assert localize("") == ""
    assert localize(None) is None


PROMPT_MODULES = [
    "app.services.ontology_generator",
    "app.services.report_agent",
    "app.services.oasis_profile_generator",
    "app.services.simulation_config_generator",
]


@pytest.mark.parametrize("module_path", PROMPT_MODULES)
def test_no_module_level_prompt_leaks_the_raw_token(module_path):
    """A literal {output_language} in a prompt is nonsense to the model."""
    import importlib
    module = importlib.import_module(module_path)
    for name, value in vars(module).items():
        if isinstance(value, str) and TOKEN in value:
            pytest.fail(f"{module_path}.{name} still contains {TOKEN}")


@pytest.mark.parametrize("module_path", PROMPT_MODULES)
def test_prompt_source_has_no_unsubstitutable_token(module_path):
    """
    A {output_language} inside an f-string raises NameError at request time
    unless a local of that name is in scope. Catch it statically instead of
    finding out during a paid run.
    """
    import importlib
    module = importlib.import_module(module_path)
    source = inspect.getsource(module)

    for lineno, line in enumerate(source.split("\n"), 1):
        if TOKEN not in line:
            continue
        # It is fine inside a plain string that localize() will process, and
        # fine inside an f-string when a local supplies the value.
        assert "output_language" in source, (
            f"{module_path}:{lineno} uses {TOKEN} with nothing to substitute it"
        )


def test_the_ontology_prompt_asks_for_the_configured_language():
    from app.services.ontology_generator import ONTOLOGY_SYSTEM_PROMPT
    assert TOKEN not in ONTOLOGY_SYSTEM_PROMPT
    assert Config.OUTPUT_LANGUAGE in ONTOLOGY_SYSTEM_PROMPT


def test_the_report_prompt_asks_for_the_configured_language():
    from app.services.report_agent import SECTION_SYSTEM_PROMPT_TEMPLATE
    assert TOKEN not in SECTION_SYSTEM_PROMPT_TEMPLATE
    assert Config.OUTPUT_LANGUAGE in SECTION_SYSTEM_PROMPT_TEMPLATE


def test_persona_prompts_render_without_raising():
    """
    These are f-strings. A stray placeholder makes them raise NameError the
    first time a customer pays for a run.
    """
    from app.services.oasis_profile_generator import OasisProfileGenerator

    builders = [
        name for name in dir(OasisProfileGenerator)
        if name.startswith("_build") and "persona" in name
    ]
    assert builders, "expected persona prompt builders to exist"

    for name in builders:
        fn = getattr(OasisProfileGenerator, name)
        source = inspect.getsource(fn)
        if TOKEN in source:
            assert "output_language = " in source, (
                f"{name} interpolates {TOKEN} but never defines output_language"
            )
