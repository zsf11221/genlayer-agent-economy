"""Direct-mode tests for contracts/agent_stake_work.py (no simulator, no network).

LLM calls are mocked with direct_vm.mock_llm; the consensus validator is
exercised explicitly with direct_vm.run_validator().

Money is microGEN (1 GEN = 1_000_000 microGEN), stored as strings.
"""

import pytest

CONTRACT = "contracts/agent_stake_work.py"

GEN = 1_000_000
CLAIM = 1_000 * GEN
STAKE = 50 * GEN
REWARD = 100 * GEN

TASK_TITLE = "Summarize the Olas Mech Marketplace fee model"
TASK_REQUIREMENTS = (
    "Write a summary of 150 to 250 words of how the Olas Mech Marketplace charges "
    "for agent-to-agent work. The summary must name the marketplace fee, the "
    "priority response window, and the Karma reputation ledger."
)
TASK_CRITERIA = (
    "The summary names the 15 percent marketplace fee, the priority response "
    "window, and Karma, and is between 150 and 250 words."
)

GOOD_DELIVERY = (
    "The Olas Mech Marketplace lets one autonomous agent hire another to run an AI "
    "task, such as generating a forecast or scoring a prediction market, and pays "
    "for it on-chain. When a requester posts a job, the payment is escrowed and "
    "the named priority mech gets an exclusive response window to deliver first. "
    "The marketplace charges a 15 percent fee on each completed request, which is "
    "taken from the payment before the mech is paid. If the priority mech does not "
    "deliver inside its window, any other registered mech may take the job, and "
    "the absent mech loses one point of Karma, the marketplace reputation ledger "
    "that tracks reliability. Karma therefore prices no-shows: agents that miss "
    "deadlines lose standing and future work, while reliable mechs keep their "
    "score and keep earning. Across more than two million requests the completion "
    "rate is about 97 percent, which shows the fee plus Karma design clears most "
    "work without any human court or dispute process."
)

THIN_DELIVERY = "done, trust me, it is good"


def _hex(addr):
    return addr.as_hex if hasattr(addr, "as_hex") else "0x" + bytes(addr).hex()


@pytest.fixture
def work(direct_deploy):
    return direct_deploy(CONTRACT)


def _claim(direct_vm, contract, who):
    direct_vm.sender = who
    return contract.claim_test_gen()


def _setup_task(direct_vm, contract, agent, reward=REWARD, stake=STAKE):
    """Requester (default sender) posts a task; agent registers and claims it."""
    owner = direct_vm.sender
    _claim(direct_vm, contract, owner)
    _claim(direct_vm, contract, agent)
    direct_vm.sender = agent
    contract.register_agent(str(stake))
    direct_vm.sender = owner
    task_id = contract.post_task(TASK_TITLE, TASK_REQUIREMENTS, TASK_CRITERIA, str(reward))
    direct_vm.sender = agent
    contract.claim_task(task_id)
    direct_vm.sender = owner
    return task_id


def _mock_verdict(direct_vm, verdict):
    direct_vm.mock_llm("judge an AI agent", verdict)


def _agent(direct_vm, contract, agent):
    return contract.get_agent(_hex(agent))


# ------------------------------------------------------------ setup
def test_claim_and_register(direct_vm, work, direct_alice):
    owner = direct_vm.sender
    assert _claim(direct_vm, work, owner) == str(CLAIM)
    assert work.get_balance(_hex(owner)) == str(CLAIM)
    with direct_vm.expect_revert("already claimed"):
        _claim(direct_vm, work, owner)

    _claim(direct_vm, work, direct_alice)
    direct_vm.sender = direct_alice
    assert work.register_agent(str(STAKE)) == str(STAKE)
    agent = _agent(direct_vm, work, direct_alice)
    assert agent["stake"] == str(STAKE)
    assert agent["reputation"] == "1000"
    assert agent["completed"] == "0"
    assert agent["failed"] == "0"
    assert work.get_balance(_hex(direct_alice)) == str(CLAIM - STAKE)


def test_register_requires_balance(direct_vm, work, direct_alice):
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Insufficient GEN"):
        work.register_agent(str(STAKE))


def test_post_task_escrows_reward(direct_vm, work):
    owner = direct_vm.sender
    _claim(direct_vm, work, owner)
    task_id = work.post_task(TASK_TITLE, TASK_REQUIREMENTS, TASK_CRITERIA, str(REWARD))
    assert task_id == "1"
    task = work.get_task("1")
    assert task["status"] == "OPEN"
    assert task["reward"] == str(REWARD)
    assert task["requester"].lower() == _hex(owner).lower()
    assert work.get_balance(_hex(owner)) == str(CLAIM - REWARD)
    assert work.get_next_task_id() == "2"


def test_post_task_rejects_bad_reward(direct_vm, work):
    _claim(direct_vm, work, direct_vm.sender)
    with direct_vm.expect_revert("Reward must be between"):
        work.post_task(TASK_TITLE, TASK_REQUIREMENTS, TASK_CRITERIA, "0")
    with direct_vm.expect_revert("Reward must be between"):
        work.post_task(TASK_TITLE, TASK_REQUIREMENTS, TASK_CRITERIA, str(20_001 * GEN))


# ------------------------------------------------------------ claim guards
def test_claim_task_guards(direct_vm, work, direct_alice, direct_bob):
    owner = direct_vm.sender
    _claim(direct_vm, work, owner)
    _claim(direct_vm, work, direct_alice)
    _claim(direct_vm, work, direct_bob)
    direct_vm.sender = owner
    task_id = work.post_task(TASK_TITLE, TASK_REQUIREMENTS, TASK_CRITERIA, str(REWARD))
    # Unregistered address cannot claim.
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("Unknown agent"):
        work.claim_task(task_id)
    # Requester cannot claim their own task.
    direct_vm.sender = owner
    with direct_vm.expect_revert("own task"):
        work.claim_task(task_id)
    # Registered agent with too little stake cannot claim.
    direct_vm.sender = direct_alice
    work.register_agent(str(5 * GEN))
    with direct_vm.expect_revert("below the 10 GEN minimum"):
        work.claim_task(task_id)
    # Top up to the minimum and claim.
    work.register_agent(str(5 * GEN))
    assert work.claim_task(task_id) == "CLAIMED"
    # Second claim is refused.
    direct_vm.sender = direct_bob
    work.register_agent(str(STAKE))
    with direct_vm.expect_revert("Only an OPEN task"):
        work.claim_task(task_id)


# ------------------------------------------------------------ happy path
def test_happy_path_pass_settle(direct_vm, work, direct_alice):
    owner = direct_vm.sender
    task_id = _setup_task(direct_vm, work, direct_alice)
    direct_vm.sender = direct_alice
    assert work.deliver(task_id, GOOD_DELIVERY, "https://example.invalid/summary") == "DELIVERED"
    _mock_verdict(direct_vm, "PASS|MEETS_CRITERIA")
    verdict = work.adjudicate(task_id)
    assert verdict == "PASS|MEETS_CRITERIA"
    assert direct_vm.run_validator() is True
    task = work.get_task(task_id)
    assert task["status"] == "ADJUDICATED_PASS"
    assert task["verdict_reason"] == "MEETS_CRITERIA"
    assert "ADJUDICATED|PASS|MEETS_CRITERIA" in task["history"]

    direct_vm.sender = owner
    assert work.settle(task_id) == "SETTLED_PAID"
    task = work.get_task(task_id)
    assert task["status"] == "SETTLED_PAID"
    # 95% of 100 GEN to the agent, 5% to the pool.
    assert work.get_balance(_hex(direct_alice)) == str(CLAIM - STAKE + 95 * GEN)
    assert work.get_platform_pool() == str(5 * GEN)
    agent = _agent(direct_vm, work, direct_alice)
    assert agent["completed"] == "1"
    assert agent["reputation"] == "1050"
    assert agent["stake"] == str(STAKE)
    # Requester keeps the escrowed reward out: 1000 - 100 = 900 GEN.
    assert work.get_balance(_hex(owner)) == str(CLAIM - REWARD)
    # Settling twice is refused.
    with direct_vm.expect_revert("Only an adjudicated task"):
        work.settle(task_id)


def test_fee_split_integer_math(direct_vm, work, direct_alice):
    task_id = _setup_task(direct_vm, work, direct_alice, reward=7 * GEN)
    direct_vm.sender = direct_alice
    work.deliver(task_id, GOOD_DELIVERY, "")
    _mock_verdict(direct_vm, "PASS|EXCEEDS_CRITERIA")
    assert work.adjudicate(task_id) == "PASS|EXCEEDS_CRITERIA"
    work.settle(task_id)
    # 7 GEN reward: fee = 7_000_000 * 500 // 10000 = 350_000; agent gets 6_650_000.
    assert work.get_balance(_hex(direct_alice)) == str(CLAIM - STAKE + 6_650_000)
    assert work.get_platform_pool() == "350000"


# ------------------------------------------------------------ fail path
def test_fail_path_refund_and_slash(direct_vm, work, direct_alice):
    owner = direct_vm.sender
    task_id = _setup_task(direct_vm, work, direct_alice)
    direct_vm.sender = direct_alice
    work.deliver(task_id, THIN_DELIVERY, "")
    _mock_verdict(direct_vm, "FAIL|THIN_EVIDENCE")
    verdict = work.adjudicate(task_id)
    assert verdict == "FAIL|THIN_EVIDENCE"
    assert direct_vm.run_validator() is True
    assert work.get_task(task_id)["status"] == "ADJUDICATED_FAIL"

    direct_vm.sender = owner
    assert work.settle(task_id) == "SETTLED_REFUNDED"
    # Requester refunded in full.
    assert work.get_balance(_hex(owner)) == str(CLAIM)
    # 20% of the 50 GEN stake slashed into the pool.
    assert work.get_platform_pool() == str(10 * GEN)
    agent = _agent(direct_vm, work, direct_alice)
    assert agent["stake"] == str(40 * GEN)
    assert agent["failed"] == "1"
    assert agent["reputation"] == "800"
    assert agent["completed"] == "0"


# ------------------------------------------------------------ appeal path
def test_appeal_overturns_to_pass(direct_vm, work, direct_alice):
    owner = direct_vm.sender
    task_id = _setup_task(direct_vm, work, direct_alice)
    direct_vm.sender = direct_alice
    work.deliver(task_id, THIN_DELIVERY, "")
    _mock_verdict(direct_vm, "FAIL|THIN_EVIDENCE")
    work.adjudicate(task_id)
    # Appeal with genuinely improved evidence before settlement.
    assert work.appeal(task_id, GOOD_DELIVERY) == "APPEALED"
    task = work.get_task(task_id)
    assert task["appeal_count"] == "1"
    assert task["appeal_evidence"] == GOOD_DELIVERY
    direct_vm.clear_mocks()
    _mock_verdict(direct_vm, "PASS|MEETS_CRITERIA")
    verdict = work.adjudicate_appeal(task_id)
    assert verdict == "PASS|MEETS_CRITERIA"
    assert direct_vm.run_validator() is True
    assert work.get_task(task_id)["status"] == "ADJUDICATED_PASS"
    assert "APPEAL_ADJUDICATED|PASS|MEETS_CRITERIA" in work.get_task(task_id)["history"]
    work.settle(task_id)
    assert work.get_task(task_id)["status"] == "SETTLED_PAID"
    assert work.get_balance(_hex(direct_alice)) == str(CLAIM - STAKE + 95 * GEN)


def test_appeal_only_once_and_only_after_fail(direct_vm, work, direct_alice):
    owner = direct_vm.sender
    task_id = _setup_task(direct_vm, work, direct_alice)
    direct_vm.sender = direct_alice
    work.deliver(task_id, THIN_DELIVERY, "")
    # No appeal before a verdict.
    with direct_vm.expect_revert("Only a failed adjudication"):
        work.appeal(task_id, GOOD_DELIVERY)
    _mock_verdict(direct_vm, "FAIL|INCOMPLETE")
    work.adjudicate(task_id)
    work.appeal(task_id, GOOD_DELIVERY)
    direct_vm.clear_mocks()
    _mock_verdict(direct_vm, "FAIL|INCOMPLETE")
    work.adjudicate_appeal(task_id)
    # The appeal verdict is final: no second appeal.
    with direct_vm.expect_revert("already been appealed"):
        work.appeal(task_id, GOOD_DELIVERY)
    # Settle the failed appeal: refund + slash.
    direct_vm.sender = owner
    work.settle(task_id)
    assert work.get_task(task_id)["status"] == "SETTLED_REFUNDED"


# ------------------------------------------------------------ consensus guards
def test_adjudicate_guards(direct_vm, work, direct_alice):
    task_id = _setup_task(direct_vm, work, direct_alice)
    # Not delivered yet.
    with direct_vm.expect_revert("Only a DELIVERED task"):
        work.adjudicate(task_id)
    direct_vm.sender = direct_alice
    work.deliver(task_id, GOOD_DELIVERY, "")
    _mock_verdict(direct_vm, "PASS|MEETS_CRITERIA")
    work.adjudicate(task_id)
    # Already decided: no re-adjudication.
    with direct_vm.expect_revert("Only a DELIVERED task"):
        work.adjudicate(task_id)
    # Settle is allowed; a second settle is not.
    work.settle(task_id)
    with direct_vm.expect_revert("Only an adjudicated task"):
        work.settle(task_id)


def test_bad_llm_format_fails_before_write(direct_vm, work, direct_alice):
    task_id = _setup_task(direct_vm, work, direct_alice)
    direct_vm.sender = direct_alice
    work.deliver(task_id, GOOD_DELIVERY, "")
    _mock_verdict(direct_vm, "Looks good to me, approve it!")
    with direct_vm.expect_revert():
        work.adjudicate(task_id)
    assert work.get_task(task_id)["status"] == "DELIVERED"


def test_validator_disagreement_is_detected(direct_vm, work, direct_alice):
    task_id = _setup_task(direct_vm, work, direct_alice)
    direct_vm.sender = direct_alice
    work.deliver(task_id, GOOD_DELIVERY, "")
    _mock_verdict(direct_vm, "PASS|MEETS_CRITERIA")
    assert work.adjudicate(task_id) == "PASS|MEETS_CRITERIA"
    # Swap the mock so the validator sees a different verdict.
    direct_vm.clear_mocks()
    _mock_verdict(direct_vm, "FAIL|INCOMPLETE")
    assert direct_vm.run_validator() is False


def test_witness_kept_after_verdict(direct_vm, work, direct_alice):
    task_id = _setup_task(direct_vm, work, direct_alice)
    direct_vm.sender = direct_alice
    work.deliver(task_id, THIN_DELIVERY, "")
    _mock_verdict(direct_vm, "FAIL|THIN_EVIDENCE")
    work.adjudicate(task_id)
    work.submit_witness(task_id, "Requester note: the delivery was two sentences.")
    task = work.get_task(task_id)
    assert task["status"] == "ADJUDICATED_FAIL"
    assert task["verdict"] == "FAIL|THIN_EVIDENCE"
    assert "WITNESS|Requester note" in task["history"]


# ------------------------------------------------------------ abandon / cancel / withdraw
def test_abandon_reopens_and_penalizes(direct_vm, work, direct_alice):
    task_id = _setup_task(direct_vm, work, direct_alice)
    direct_vm.sender = direct_alice
    assert work.abandon_task(task_id) == "OPEN"
    task = work.get_task(task_id)
    assert task["status"] == "OPEN"
    assert task["agent"] == ""
    agent = _agent(direct_vm, work, direct_alice)
    assert agent["failed"] == "1"
    assert agent["reputation"] == "900"
    # The task can be claimed again.
    assert work.claim_task(task_id) == "CLAIMED"


def test_cancel_refunds_open_task(direct_vm, work):
    owner = direct_vm.sender
    _claim(direct_vm, work, owner)
    task_id = work.post_task(TASK_TITLE, TASK_REQUIREMENTS, TASK_CRITERIA, str(REWARD))
    assert work.cancel_task(task_id) == "CANCELLED"
    assert work.get_balance(_hex(owner)) == str(CLAIM)
    with direct_vm.expect_revert("Only an OPEN task"):
        work.cancel_task(task_id)


def test_withdraw_stake_rules(direct_vm, work, direct_alice):
    owner = direct_vm.sender
    task_id = _setup_task(direct_vm, work, direct_alice)
    # Blocked while a task is active.
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Cannot withdraw while"):
        work.withdraw_stake(str(10 * GEN))
    # Leaving a non-zero remainder below the minimum is refused.
    direct_vm.sender = direct_alice
    work.abandon_task(task_id)
    with direct_vm.expect_revert("Remaining stake must be 0"):
        work.withdraw_stake(str(45 * GEN))
    # A valid partial withdrawal works.
    assert work.withdraw_stake(str(40 * GEN)) == str(10 * GEN)
    assert work.get_balance(_hex(direct_alice)) == str(CLAIM - STAKE + 40 * GEN)
    # Withdrawing everything works too.
    assert work.withdraw_stake(str(10 * GEN)) == "0"
    assert work.get_balance(_hex(direct_alice)) == str(CLAIM)
