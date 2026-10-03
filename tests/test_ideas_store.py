import os
from uuid import uuid4
import pytest
from harness.ideas import store
from harness.ideas.roster import parse_roster


def test_roster_preserves_repeated_fund_views():
    rows=parse_roster('<p>🔹 Acme (ACM US) by Alpha</p><p>🔹 Acme (ACM US) by Beta</p>')
    assert [r.fund for r in rows]==['Alpha','Beta']
    assert rows[0].symbol=='ACM US'


def test_artifacts_immutable_and_portable(tmp_path):
    assert store.write_artifact(tmp_path,'research/a.txt',b'one')=='research/a.txt'
    store.write_artifact(tmp_path,'research/a.txt',b'one')
    with pytest.raises(ValueError):store.write_artifact(tmp_path,'research/a.txt',b'two')
    assert (tmp_path/'research/a.txt').read_bytes()==b'one'


@pytest.mark.skipif(not os.getenv('MINERVA_TEST_DATABASE_URL'),reason='Postgres integration test requires explicit test database')
def test_postgres_import_is_atomic_and_idempotent(tmp_path,monkeypatch):
    monkeypatch.setenv('MINERVA_DATABASE_URL',os.environ['MINERVA_TEST_DATABASE_URL'])
    monkeypatch.setenv('MINERVA_IDEAS_ROOT',str(tmp_path))
    store.initialize()
    run_id=uuid4()
    issue={'url':'https://hfbestideas.substack.com/p/test','date':'2026-09-30','roster':[{'company':'Acme','fund':'Alpha'},{'company':'Acme','fund':'Beta'}]}
    try:
        store.import_issue(issue,run_id=run_id)
        store.import_issue(issue,run_id=run_id)
        assert len(store.items(run_id))==2
        assert store.status(run_id)['counts']['pending']==2
        issue['roster'][0]['fund']='Changed'
        with pytest.raises(ValueError):store.import_issue(issue,run_id=run_id)
        assert store.items(run_id)[0]['fund']=='Alpha'
    finally:
        with store.connect() as conn:
            conn.execute('DELETE FROM minerva_ideas.items WHERE run_id=%s',(run_id,))
            conn.execute('DELETE FROM minerva_ideas.runs WHERE id=%s',(run_id,))
