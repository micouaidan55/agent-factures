from agent_factures.agent.tool_defs import INVOICE_SCHEMA, TOOL_NAMES, TOOLS, VERDICT_SCHEMA
from agent_factures.extraction.models import Invoice, Status


def test_invoice_schema_covers_every_model_field():
    assert set(INVOICE_SCHEMA["properties"]) == set(Invoice.model_fields)


def test_invoice_schema_requires_the_model_required_fields():
    model_required = {name for name, field in Invoice.model_fields.items() if field.is_required()}
    assert set(INVOICE_SCHEMA["required"]) == model_required


def test_verdict_schema_lists_all_statuses():
    assert VERDICT_SCHEMA["properties"]["status"]["enum"] == [s.value for s in Status]


def test_tools_are_well_formed_and_unique():
    names = [tool["name"] for tool in TOOLS]
    assert len(names) == len(set(names))
    assert set(names) == TOOL_NAMES
    for tool in TOOLS:
        assert tool["description"]
        assert tool["input_schema"]["type"] == "object"
