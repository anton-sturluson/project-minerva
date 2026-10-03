import pytest
from harness.ideas.extraction import Claim, View, Review, materialize, passages, validate_review


def view(text='Acme has pricing power.'):
    return View(instrument='equity',stance='bull',action='not stated',claims=[Claim(text=text,passages=['p1.1'])],gap='')


def test_model_selects_ids_and_cannot_invent_quotes():
    spans=passages([{'id':'p1','text':'Acme has pricing power.\n\nNext paragraph.'}])
    result=materialize(view(),spans)
    assert result['claims'][0]['evidence']==[{'block':'p1.1','quote':'Acme has pricing power.'}]
    with pytest.raises(ValueError,match='unknown'):
        materialize(view(),{'p2.1':'Acme has pricing power.'})


def test_invented_number_fails_even_with_authentic_passage():
    with pytest.raises(ValueError,match='number'):
        materialize(view('Acme will grow 500%.'),{'p1.1':'Acme has pricing power.'})


def test_semantic_rejection_blocks_authentic_evidence_with_false_claim():
    v=view('The manager guarantees shares will triple next week.')
    materialize(v,{'p1.1':'Acme has pricing power.'})
    r=Review(matching_fund_company_period=True,substantive_equity_view=True,stance_and_action_supported=True,claims_supported=[False],reason='Guarantee is absent from source')
    with pytest.raises(ValueError,match='Guarantee'):validate_review(v,r)
    r.claims_supported=[]
    with pytest.raises(ValueError):validate_review(v,r)
