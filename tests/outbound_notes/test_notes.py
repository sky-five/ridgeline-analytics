"""The drafter, the checker and the replay on hand-made facts; no warehouse or key needed."""
import pytest

from analyst.llm import ChatClient, Reply
from outbound_notes import check, draft, leads, notes


def lead(**kw):
    f = {"account_id": "ACC-1", "company": "Test Ridge Roofing", "region": "west", "channel": "referral",
         "came_from": "a referral", "crew_size": "6-15", "days_since_signup": 23, "proposal_wk1": True,
         "measurements_14d": 4, "proposals_14d": 3, "signed_14d": 0, "logins_14d": 7, "active_days_14d": 9,
         "reasons": ["sent a proposal in week 1", "ordered measurements", "came by referral"]}
    return f | kw


GOOD = ("Hi Test Ridge Roofing team, I saw you sent three proposals and ordered 4 measurement reports in your "
        "first two weeks, and your crew was in the app on 9 of your first 14 days. If it would help, I can show "
        "you how measurements flow straight into a proposal. Would a 15-minute call next week work for you?")


def test_template_uses_the_leads_first_two_backed_reasons():
    t = draft.template(lead())
    assert t.startswith("Hi Test Ridge Roofing team, I saw you sent 3 proposals in your first two weeks. "
                        "You also ordered 4 measurement reports. If it")
    assert "referral" not in t  # only two signals
    assert check.check(t, lead()).ok


def test_template_skips_reasons_the_facts_do_not_back():
    f = lead(reasons=["got a proposal signed", "came by referral"], signed_14d=0)
    assert draft.template(f).split(". ")[0].endswith("Thanks for coming to us through a referral")
    f = lead(reasons=["no strong signal"][1:])
    assert "Thanks for trying the app" in draft.template(f)
    assert check.check(draft.template(f), f).ok


def test_a_good_note_passes_and_its_numbers_are_counted():
    r = check.check(GOOD, lead())
    assert r.ok, r.problems
    assert r.numbers == 6  # three, 4, two, 9, 14, 15


@pytest.mark.parametrize("edit, problem", [
    (("three proposals", "eight proposals"), "the number 8 is not one of this lead's facts"),
    (("4 measurement", "12 measurement"), "the number 12 is not one of this lead's facts"),
    (("Test Ridge Roofing", "Test Ridge Roof"), "does not name 'Test Ridge Roofing'"),
    (("work for you?", "work for you."), "does not end with a question"),
    (("If it would help", "Your lead score is high, so if it would help"), "mentions the score or a ranking"),
    (("If it would help", "You were selected for this, and if it would help"), "mentions the score or a ranking"),
    (("If it would help", "Sign this week for 20% off. If it would help"), "offers money, a discount or a deadline"),
    (("If it would help", "Hi [first name]. If it would help"), "leaves a placeholder"),
    (("sent three", "had a customer sign one of the three"), None),
])
def test_edits_that_break_the_rules_fail(edit, problem):
    r = check.check(GOOD.replace(*edit), lead())
    if problem is None:
        assert r.ok, r.problems  # "sign" is not "signed"
    else:
        assert problem in r.problems


def test_claims_need_the_matching_fact():
    f = lead(measurements_14d=0, channel="trade_show")
    r = check.check(GOOD.replace("If it would help", "Glad we met at the trade show. If it would help"), f)
    assert "mentions measurements, which this lead has no fact for" in r.problems
    assert not any("trade show" in p for p in r.problems)
    r = check.check(GOOD.replace("If it would help", "A customer already signed one. If it would help"), lead())
    assert "mentions a signed proposal, which this lead has no fact for" in r.problems
    signed_up = GOOD.replace("If it would help", "Thanks for the trial you signed up for. If it would help")
    assert check.check(signed_up, lead()).ok


def test_length_limits():
    assert check.check("Hi Test Ridge Roofing team, call?", lead()).problems == ["6 words; keep it to 40-90"]
    assert "100 words; keep it to 40-90" in check.check(GOOD + " ok" * 41, lead()).problems


def test_crew_size_and_days_since_signup_may_be_quoted():
    note = GOOD.replace("If it would help", "For a crew of 6-15, 23 days in, if it would help")
    assert check.check(note, lead()).ok


def test_the_prompt_holds_the_facts_but_no_score_or_id():
    p = draft.prompt(lead())
    assert "Test Ridge Roofing" in p and '"measurements_14d": 4' in p
    assert "ACC-1" not in p and "score" not in p.lower() and "decile" not in p.lower()


class FakeClient:
    provider, model = "fake", "m1"

    def __init__(self, texts):
        self.texts, self.calls = list(texts), []

    def complete(self, system, messages, tools):
        self.calls.append((system, messages, tools))
        return Reply(self.texts.pop(0), [], 100, 50)


def test_record_keeps_failing_drafts_with_their_verdict_and_paces():
    facts = [lead(), lead(account_id="ACC-2", company="Other Peak Roofing")]
    slept = []
    out = notes.record(facts, notes.pd.Timestamp("2026-06-30"), FakeClient([GOOD, GOOD]), pace=6, sleep=slept.append)
    assert slept == [6]
    assert out["drafter"] == "fake/m1"
    assert [n["ok"] for n in out["notes"]] == [True, False]
    assert out["notes"][1]["problems"] == ["does not name 'Other Peak Roofing'"]
    assert out["summary"]["passed"] == 1
    assert notes.replay(out, facts) == []


def test_replay_flags_changed_facts_missing_leads_and_edited_text():
    facts = [lead()]
    out = notes.record(facts, notes.pd.Timestamp("2026-06-30"), FakeClient([GOOD]))
    assert notes.replay(out, [lead(proposals_14d=5)]) == ["ACC-1: facts changed since the draft was recorded"]
    assert notes.replay(out, facts + [lead(account_id="ACC-9")])[0].startswith("the recorded leads are not")
    out["notes"][0]["text"] = GOOD.replace("three", "eight")
    assert notes.replay(out, facts)[0].startswith("ACC-1: the checker now says")


def test_fingerprint_is_stable_and_sensitive():
    assert leads.fingerprint(lead()) == leads.fingerprint(dict(reversed(list(lead().items()))))
    assert leads.fingerprint(lead()) != leads.fingerprint(lead(logins_14d=8))


def test_chat_payload_omits_tools_for_a_plain_completion():
    body = ChatClient.payload("m", "sys", [{"role": "user", "content": "hi"}], [])
    assert "tools" not in body
    assert ChatClient.payload("m", "sys", [], [{"name": "t", "description": "", "parameters": {}}])["tools"]
