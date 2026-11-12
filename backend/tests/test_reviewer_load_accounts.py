"""Staging-only distinct synthetic student login fixture boundaries.

Only the staging reviewer authentication parser is tested; no hosted logins,
Neon writes, real passwords or academic authority assumptions are involved.
"""
import json
from uuid import NAMESPACE_DNS,uuid5
from unittest.mock import patch
import pytest
from smartpro import reviewer_auth

HASH = "pbkdf2_sha256$1000000$synthetic$not-a-real-password-hash"

def record(actor):
    return {"actor":str(actor),"passwordHash":HASH,"label":"Synthetic fixture"}

def fixture():
    root={"test-student-original":record(uuid5(NAMESPACE_DNS,"smartpro-existing-student"))}
    extra={"test-faculty-original":record(uuid5(NAMESPACE_DNS,"smartpro-existing-faculty"))}
    load={"test-load-"+f"{n:02}":record(uuid5(NAMESPACE_DNS,"smartpro-load-test-"+str(n)))
          for n in range(1,9)}
    return root,extra,load

def parse(base,supplemental,load):
    environment={"SMARTPRO_REVIEWER_ACCOUNTS":json.dumps(base),
                 "SMARTPRO_REVIEWER_TEST_ACCOUNTS":json.dumps(supplemental)}
    if load is not None:environment["SMARTPRO_REVIEWER_LOAD_ACCOUNTS"]=json.dumps(load)
    with patch.object(reviewer_auth,"active",return_value=True),patch.dict("os.environ",environment,clear=False):
        # Explicitly remove any inherited load value for the no-load case.
        if load is None:
            with patch.dict("os.environ",{"SMARTPRO_REVIEWER_LOAD_ACCOUNTS":""}):
                return reviewer_auth._accounts()
        return reviewer_auth._accounts()

def test_no_optional_load_aliases_retains_original_authentication_map():
    base,extra,_=fixture()
    accounts=parse(base,extra,None)
    assert set(accounts)==set(base)|set(extra)

def test_eight_load_aliases_have_distinct_actors_and_preserve_original_aliases():
    base,extra,load=fixture()
    accounts=parse(base,extra,load)
    assert len(accounts)==10
    assert {accounts[x]["actor"] for x in load}=={v["actor"] for v in load.values()}
    assert accounts["test-student-original"]["actor"]==base["test-student-original"]["actor"]

@pytest.mark.parametrize("defect",["duplicate","missing","bad_alias"])
def test_invalid_staging_load_aliases_fail_closed(defect):
    base,extra,load=fixture()
    if defect=="duplicate":
        load["test-load-02"]["actor"]=load["test-load-01"]["actor"]
    elif defect=="missing":
        del load["test-load-08"]
    else:
        load["test-sneaky"]=load.pop("test-load-08")
    with pytest.raises(RuntimeError):
        parse(base,extra,load)

def test_load_actor_cannot_alias_existing_reviewer():
    base,extra,load=fixture()
    load["test-load-01"]["actor"]=base["test-student-original"]["actor"]
    with pytest.raises(RuntimeError,match="different actors"):
        parse(base,extra,load)
