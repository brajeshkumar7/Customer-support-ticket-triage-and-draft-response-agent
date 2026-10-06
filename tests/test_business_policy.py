"""Shared policy and generated evidence contracts; no network calls."""
import hashlib
import json
from pathlib import Path
import pytest
from pypdf import PdfReader
from src.knowledge.policy import (load_policy, policy_configuration, PolicySourceError,
                                  policy_evidence_findings, is_active_policy_chunk, policy_text)
from src.knowledge.export_policy import export_policy
from src.tools.policy_checker import PolicyCheckerTool
from src.tools.base import ToolInputError

@pytest.mark.parametrize('days,reason,expected,window', [
    (29,'changed mind',True,30),(30,'changed mind',True,30),(31,'changed mind',False,30),
    (6,'damaged',True,7),(7,'damaged',True,7),(8,'damaged',False,7),
])
def test_inclusive_policy_boundaries(monkeypatch,days,reason,expected,window):
    monkeypatch.setattr('src.tools.policy_checker.find_order',lambda *a,**k: {
        'order_id':'ORD-TEST','status':'delivered','delivered_days_ago':days})
    result=PolicyCheckerTool()._execute(order_id='ORD-TEST',reason=reason)
    assert result['eligible'] is expected
    assert result['policy_window_days']==window
    assert result['policy_sha256']==policy_configuration()['policy_sha256']

@pytest.mark.parametrize('reason',['speaker is smoking','please make a policy exception'])
def test_window_eligibility_does_not_authorize_safety_or_exception(reason):
    result=PolicyCheckerTool()._execute(order_id='ORD-1006',reason=reason)
    assert result['eligible'] is True
    assert result['requires_human_review'] is True

@pytest.mark.parametrize('days',[-1,True,'3'])
def test_invalid_delivery_age(monkeypatch,days):
    monkeypatch.setattr('src.tools.policy_checker.find_order',lambda *a,**k: {
        'order_id':'ORD-TEST','status':'delivered','delivered_days_ago':days})
    with pytest.raises(ToolInputError):PolicyCheckerTool()._execute(order_id='ORD-TEST',reason='return')

@pytest.mark.parametrize('field,value',[('version','unknown'),('review_status','approved'),('requires_delivered',False),('rules',{})])
def test_invalid_policy_source(tmp_path,field,value):
    data=load_policy();data.pop('policy_sha256');data[field]=value
    path=tmp_path/'policy.json';path.write_text(json.dumps(data))
    with pytest.raises(PolicySourceError):load_policy(path)

def test_missing_and_malformed_policy(tmp_path):
    path=tmp_path/'missing.json'
    with pytest.raises(PolicySourceError):load_policy(path)
    path.write_text('{')
    with pytest.raises(PolicySourceError):load_policy(path)

def test_checker_does_not_fallback_on_policy_failure(monkeypatch):
    def unavailable():raise PolicySourceError('unavailable')
    monkeypatch.setattr('src.tools.policy_checker.load_policy',unavailable)
    with pytest.raises(PolicySourceError):PolicyCheckerTool()._execute(order_id='ORD-1002',reason='return')

def test_export_is_idempotent_preserves_references_and_rejects_same_version_change(tmp_path):
    folder=tmp_path/'pdfs';folder.mkdir()
    (folder/'returns.pdf').write_bytes(b'preserve this reference')
    (folder/'manifest.json').write_text(json.dumps({'returns.pdf':{'approval_scope':'reference_only'}}))
    original=load_policy();original.pop('policy_sha256')
    source=tmp_path/'policy.json';source.write_text(json.dumps(original))
    assert len(export_policy(folder,source)['created'])==2
    manifest=json.loads((folder/'manifest.json').read_text())
    for name,meta in manifest.items():
        if not name.startswith('policy_'):continue
        text=' '.join(' '.join(page.extract_text() for page in PdfReader(folder/name).pages).split())
        assert policy_text(load_policy(source),meta['rule_ids'][0]) in text
        assert meta['policy_sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
        assert meta['approval_scope']=='reference_only'
    assert len(export_policy(folder,source)['skipped'])==2
    assert (folder/'returns.pdf').read_bytes()==b'preserve this reference'
    original['rules']['returns']['window_days']=31;source.write_text(json.dumps(original))
    before=(folder/'manifest.json').read_bytes()
    with pytest.raises(ValueError):export_policy(folder,source)
    assert (folder/'manifest.json').read_bytes()==before

def evidence():
    config=policy_configuration()
    return {**config,'review_status':'simulation','approval_scope':'reference_only','rule_ids':['returns']}

def result():
    return {'ok':True,'data':{**policy_configuration(),'rule_ids':['returns'],'requires_human_review':False,'eligible':True,'policy_window_days':30}}

def test_matching_policy_evidence():
    assert policy_evidence_findings(result(),[evidence()],use_rag=True)==[]
    assert not is_active_policy_chunk({'knowledge_id':'returns'},policy_configuration())

@pytest.mark.parametrize('field,value',[('policy_version','old'),('policy_sha256','wrong'),('rule_ids',['unknown'])])
def test_conflicting_policy_metadata(field,value):
    item=evidence();item[field]=value
    codes=dict(policy_evidence_findings(result(),[item],use_rag=True))
    assert 'business_policy_evidence_mismatch' in codes

def test_missing_and_wrong_policy_results():
    assert 'business_policy_evidence_missing' in dict(policy_evidence_findings(result(),[],use_rag=True))
    wrong=result();wrong['data']['policy_version']='old'
    assert 'business_policy_mismatch' in dict(policy_evidence_findings(wrong,[evidence()],use_rag=True))
    assert 'business_policy_unavailable' in dict(policy_evidence_findings({'ok':False},[],use_rag=True))


def test_conflicting_window_cannot_be_used_as_policy_evidence():
    conflict=result();conflict['data']['policy_window_days']=999
    assert 'business_policy_result_conflict' in dict(policy_evidence_findings(conflict,[evidence()],use_rag=True))

@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['missing','wrong_version','conflicting_rules'])
async def test_graph_escalates_policy_mismatch_even_with_supervisor_pass(monkeypatch,mode):
    from tests.test_pdf_rag import Client,Memory,Sender,Search,completion,EVIDENCE,REVIEW
    from src.agent.graph import build_graph
    from src.memory.short_term import ShortTermMemory
    from src.tools.base import ToolResult
    monkeypatch.setenv('ZOHO_DESK_SEND_ENABLED','true')
    data=result()['data']
    if mode=='wrong_version':data['policy_version']='old'
    if mode=='conflicting_rules':data['policy_window_days']=999
    class FakePolicy:
        async def run(self,**kwargs):return ToolResult('policy_checker',data)
    client=Client([completion(REVIEW),completion('{"order_id":"ORD-1002","reason":"return"}'),
                   completion('{"draft_response":"A person should review your return.","evidence_ids":[]}')])
    sender=Sender()
    graph=build_graph(short_term_memory=ShortTermMemory('policy-test'),long_term_memory=Memory(),
                      client=client,primary_model='fake',use_rag=True,knowledge_search_tool=Search(),
                      policy_checker_tool=FakePolicy(),reply_sender=sender)
    output=await graph.ainvoke({'ticket_id':'policy-test','ticket_text':'Please return ORD-1002.'})
    assert output['supervisor_status']=='PASS'
    assert output['terminal_status']=='escalated' and not sender.calls
    assert any(item['code'].startswith('business_policy_') for item in output['safety_review']['findings'])


@pytest.mark.asyncio
async def test_obsolete_policy_not_given_to_rag_model():
    from tests.test_pdf_rag import Client,Search,completion,EVIDENCE
    from src.agent.rag import gather_knowledge
    obsolete={**EVIDENCE,'knowledge_id':'returns','chunk_id':'obsolete','text':'obsolete rules'}
    client=Client([completion('{"sufficient":false,"evidence_ids":[],"reason":"No active policy."}')])
    items,review,count=await gather_knowledge(client=client,model='fake',run_id='policy-filter',
                                             ticket_text='return window',category='returns',tool=Search([obsolete]))
    assert not items
    assert 'obsolete rules' not in client.calls[0]['messages'][1]['content']
