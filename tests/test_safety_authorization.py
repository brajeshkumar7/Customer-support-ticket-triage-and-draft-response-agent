"""Safety authorization contracts; no external calls."""
from dataclasses import replace
import pytest
from src.agent.production_policy import (
    decide_public_reply, simulation_knowledge, assess_reply_evidence, validate_outgoing_reply,
)

@pytest.mark.parametrize('ticket,code', [
    ('My ORD-1001 speaker is smoking; get a manager.', 'safety_incident'),
    ('I was charged twice. Which payment methods are available?', 'billing_data_unavailable'),
    ('Please investigate ORD-9999 and tell me which cards you accept.', 'business_action_unavailable'),
    ('Where is my package ORD-1001?', 'customer_facts_unverified'),
])
def test_collects_blockers_and_specific_requirements(ticket, code):
    result = decide_public_reply(ticket, knowledge=simulation_knowledge())
    assert result.kind == 'human'
    assert code in dict(result.findings)
    assert result.required_evidence
    if 'ORD-' in ticket:
        assert 'verified requester-to-record identity' in result.required_evidence


def test_collects_simultaneous_safety_and_identity_findings():
    result = decide_public_reply('My ORD-1001 speaker is smoking; get a manager.', knowledge=simulation_knowledge())
    assert {'safety_incident', 'manager_requested', 'customer_facts_unverified'} <= dict(result.findings).keys()

@pytest.mark.parametrize('ticket', [
    'Which payment methods can I use at checkout?',
    'Where can I find the tracking link?',
    'How long does an approved refund usually take?',
    'Carrier scans are unchanged. Is that normal?',
])
def test_positive_approved_controls(ticket):
    result = decide_public_reply(ticket, knowledge=simulation_knowledge())
    assert validate_outgoing_reply(result, result.body)
    assert not validate_outgoing_reply(result, result.body + ' Your refund is complete.')
    assert not validate_outgoing_reply(replace(result, kind='human'), result.body)

@pytest.mark.parametrize('field,value', [
    ('approval_scope', 'reference_only'), ('approval_scope', 'unspecified'),
    ('approval_scope', ''), ('knowledge_version', 'wrong'),
    ('review_status', 'unreviewed'), ('source', ''), ('text', 'unrelated'),
])
def test_model_pass_cannot_authorize_wrong_evidence(field, value):
    decision = decide_public_reply('Which payment methods can I use at checkout?', knowledge=simulation_knowledge())
    item = dict(chunk_id='c1', knowledge_id='payment_methods', knowledge_version='v1',
                review_status='simulation', approval_scope='automatic_reply_simulation',
                source='local simulation', text=decision.body)
    item[field] = value
    result = assess_reply_evidence(decision, review={'sufficient': True, 'evidence_ids':['c1']}, evidence=[item])
    assert result.kind == 'human'
    assert result.reason_code == 'rag_approval_evidence_missing'


def test_exact_simulation_evidence_and_complete_coverage_required():
    decision = decide_public_reply('Which payment methods can I use at checkout?', knowledge=simulation_knowledge())
    item = dict(chunk_id='c1', knowledge_id='payment_methods', knowledge_version='v1',
                review_status='simulation', approval_scope='automatic_reply_simulation',
                source='local simulation', text=decision.body)
    allowed = assess_reply_evidence(decision, review={'sufficient': True, 'evidence_ids':['c1']}, evidence=[item])
    assert validate_outgoing_reply(allowed, decision.body)
    blocked = assess_reply_evidence(decision, review={'sufficient': False, 'evidence_ids':['c1']}, evidence=[item])
    assert blocked.kind == 'human'
    assert not validate_outgoing_reply(blocked, decision.body)


@pytest.mark.parametrize('ticket', [
    'Which payment methods can I use? Gift wrapping available?',
    'Where can I find the tracking link? Are gift cards available?',
    'Which payment methods can I use at checkout, and can you wrap the gift?',
])
def test_uncovered_separate_questions_block(ticket):
    result = decide_public_reply(ticket, knowledge=simulation_knowledge())
    assert result.kind == 'human'
    assert not validate_outgoing_reply(result, 'Available payment methods are shown at checkout before you place an order.')
