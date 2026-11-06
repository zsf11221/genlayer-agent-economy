# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

"""AgentStakeWork: a stake-to-work agent task market on GenLayer.

An agent stakes TEST GEN to be allowed to claim paid tasks. A requester
escrows the reward when posting a task. The agent delivers, and GenLayer
validators independently judge the delivery against the task's written
requirements and acceptance criteria. Only a consensus verdict settles
the money: a pass pays the agent (95% of the reward, 5% to the platform
pool) and raises the agent's reputation; a fail refunds the requester and
slashes 20% of the agent's stake into the pool. A failed verdict can be
appealed once with new evidence; the appeal verdict is final.

Category / mechanism / interaction / evolution (four lines):
- Category: agent infrastructure.
- Mechanism: consensus decides whether an agent's delivery meets the
  task requirements; the verdict moves real (nominal TEST) money --
  pay-out with a split on pass, refund plus stake slashing on fail.
- Interaction model: a task lifecycle (register/stake -> post/escrow ->
  claim -> deliver -> adjudicate -> settle/appeal), not a form + list.
- Evolution state: agent reputation, stake, completed/failed counts and
  the platform pool change with every settled task, and decide whether
  the agent may claim the next one.

Money design (all integers, no floats anywhere):
- GEN is accounted in microGEN: 1 GEN = 1_000_000 microGEN.
- All amounts are stored as strings of integers and parsed back to int.
- GEN balances are a nominal in-contract TEST ledger.
  claim_test_gen() credits 1_000 GEN once per address; staking, escrow,
  payment, refund and slashing only move ledger entries. No real GEN is
  transferred by this contract.
- Minimum stake to claim a task: 10 GEN. Minimum reward: 1 GEN.
  Maximum reward per task: 10_000 GEN.
- On a pass, the reward splits 95% to the agent and 5% to the platform
  pool. On a fail, the reward is refunded in full and 20% of the
  agent's current stake is slashed into the platform pool.
- Reputation starts at 1000. Pass: +50 (cap 2000). Fail: -200
  (floor 0). Voluntary abandon: -100 (floor 0).

Consensus (adjudicate / adjudicate_appeal):
- The leader asks an LLM to judge the stored delivery against the
  stored requirements and acceptance criteria and return exactly one
  line: "PASS|<CODE>" or "FAIL|<CODE>", where <CODE> is one of a fixed
  set of reason codes. Each validator independently re-runs the same
  prompt on the same stored evidence and the verdicts must be strictly
  equal as strings. Free-text reasons are deliberately NOT part of the
  verdict: two independent LLM calls never word a sentence identically,
  so strict equality applies to the canonical decision + reason code.
- Any failure (empty delivery, unparsable verdict, consensus
  disagreement) raises before any write, so the task stays DELIVERED /
  APPEALED and can be retried.
- A decided task can never be re-adjudicated. An appeal is allowed
  exactly once, only after a FAIL verdict, and only before settlement.
  The appeal verdict is final. New evidence submitted after a final
  verdict is kept as a witness entry in the task history while the
  standing verdict stays untouched.

No clock source:
- There is no wall-clock deadline anywhere in this contract. A stale
  claim is ended only by an explicit call: the agent may abandon the
  task (reputation -100, task reopens), and the requester may cancel
  only while the task is still OPEN.
"""

from dataclasses import dataclass

from genlayer import *

# ---------------------------------------------------------------- units
MICRO_PER_GEN = 1_000_000

CLAIM_AMOUNT = 1_000 * MICRO_PER_GEN  # 1000 GEN test credit, once per address
MIN_STAKE = 10 * MICRO_PER_GEN  # 10 GEN minimum stake to claim tasks
MIN_REWARD = 1 * MICRO_PER_GEN  # 1 GEN minimum task reward
MAX_REWARD = 10_000 * MICRO_PER_GEN  # 10_000 GEN maximum task reward

PLATFORM_FEE_BP = 500  # 5% of a passed reward goes to the platform pool
SLASH_BP = 2000  # 20% of stake slashed on a failed delivery

REPUTATION_START = 1000
REPUTATION_MAX = 2000
REPUTATION_PASS_DELTA = 50
REPUTATION_FAIL_DELTA = 200
REPUTATION_ABANDON_DELTA = 100

MAX_TEXT_LEN = 3000
MAX_TITLE_LEN = 200
MAX_REF_LEN = 500

STATUS_OPEN = "OPEN"
STATUS_CLAIMED = "CLAIMED"
STATUS_DELIVERED = "DELIVERED"
STATUS_ADJUDICATED_PASS = "ADJUDICATED_PASS"
STATUS_ADJUDICATED_FAIL = "ADJUDICATED_FAIL"
STATUS_APPEALED = "APPEALED"
STATUS_SETTLED_PAID = "SETTLED_PAID"
STATUS_SETTLED_REFUNDED = "SETTLED_REFUNDED"
STATUS_CANCELLED = "CANCELLED"

ACTIVE_STATUSES = (
    STATUS_CLAIMED,
    STATUS_DELIVERED,
    STATUS_ADJUDICATED_PASS,
    STATUS_ADJUDICATED_FAIL,
    STATUS_APPEALED,
)

PASS_CODES = ("MEETS_CRITERIA", "EXCEEDS_CRITERIA")
FAIL_CODES = ("INCOMPLETE", "OFF_SPEC", "THIN_EVIDENCE", "UNVERIFIABLE")


@allow_storage
@dataclass
class Agent:
    address: str
    stake: str
    reputation: str
    completed: str
    failed: str


@allow_storage
@dataclass
class Task:
    id: str
    title: str
    requirements: str
    acceptance_criteria: str
    requester: str
    agent: str
    reward: str
    status: str
    delivery: str
    evidence_ref: str
    verdict: str
    verdict_reason: str
    appeal_evidence: str
    appeal_count: str
    history: str


def _parse_int(value: str, what: str) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        raise gl.vm.UserError("[EXPECTED] " + what + " must be a string integer, got: " + str(value))


def _parse_verdict(raw: str) -> str:
    """Normalize raw LLM output to the strict verdict string.

    Only "PASS|<CODE>" / "FAIL|<CODE>" with a code from the fixed sets
    is accepted. Anything else is an LLM error: raise before writing.
    """
    if not isinstance(raw, str):
        raise gl.vm.UserError("[LLM_ERROR] Verdict is not a string")
    line = raw.strip().split("\n")[0].strip()
    parts = line.split("|")
    if len(parts) != 2:
        raise gl.vm.UserError("[LLM_ERROR] Verdict must be DECISION|CODE, got: " + line[:120])
    decision = parts[0].strip().upper()
    code = parts[1].strip().upper()
    if decision == "PASS" and code in PASS_CODES:
        return "PASS|" + code
    if decision == "FAIL" and code in FAIL_CODES:
        return "FAIL|" + code
    raise gl.vm.UserError("[LLM_ERROR] Unknown verdict: " + line[:120])


def _adjudication_prompt(
    title: str,
    requirements: str,
    acceptance_criteria: str,
    delivery: str,
    evidence_ref: str,
    extra_evidence: str,
) -> str:
    prompt = (
        "You judge an AI agent's delivery for a paid task. "
        "Judge ONLY the task requirements, acceptance criteria and delivery below; "
        "do not use outside knowledge.\n"
        "Task: " + title + "\n"
        "Requirements:\n" + requirements + "\n"
        "Acceptance criteria:\n" + acceptance_criteria + "\n"
        "Delivery:\n" + delivery + "\n"
        "Evidence reference: " + evidence_ref + "\n"
    )
    if extra_evidence.strip() != "":
        prompt = prompt + "Additional evidence submitted on appeal:\n" + extra_evidence + "\n"
    prompt = prompt + (
        "Rules:\n"
        "1. PASS only if the delivery credibly meets the acceptance criteria.\n"
        "2. FAIL with INCOMPLETE if part of the requirements is missing.\n"
        "3. FAIL with OFF_SPEC if the delivery answers a different task.\n"
        "4. FAIL with THIN_EVIDENCE if the delivery is generic, empty of substance, or says nothing verifiable.\n"
        "5. FAIL with UNVERIFIABLE if the delivery claims results with no checkable evidence.\n"
        "Reply with EXACTLY ONE LINE and nothing else, no markdown, no extra words:\n"
        "PASS|MEETS_CRITERIA or PASS|EXCEEDS_CRITERIA or "
        "FAIL|INCOMPLETE or FAIL|OFF_SPEC or FAIL|THIN_EVIDENCE or FAIL|UNVERIFIABLE"
    )
    return prompt


class AgentStakeWork(gl.Contract):
    tasks: TreeMap[str, Task]
    next_task_id: str
    agents: TreeMap[Address, Agent]
    gen_balances: TreeMap[Address, str]
    claimed: TreeMap[Address, str]
    platform_pool: str

    def __init__(self):
        self.next_task_id = "1"
        self.platform_pool = "0"

    # ------------------------------------------------------------ helpers
    def _get_task(self, task_id: str) -> Task:
        if task_id not in self.tasks:
            raise gl.vm.UserError("[EXPECTED] Unknown task: " + task_id)
        return self.tasks[task_id]

    def _save_task(self, task: Task) -> None:
        self.tasks[task.id] = task

    def _get_agent(self, address: Address) -> Agent:
        if address not in self.agents:
            raise gl.vm.UserError("[EXPECTED] Unknown agent: " + address.as_hex)
        return self.agents[address]

    def _gen_balance_of(self, address: Address) -> int:
        return _parse_int(self.gen_balances.get(address, "0"), "GEN balance")

    def _set_gen_balance(self, address: Address, amount: int) -> None:
        if amount < 0:
            raise gl.vm.UserError("[EXPECTED] GEN balance cannot be negative")
        self.gen_balances[address] = str(amount)

    def _has_active_task(self, agent_hex: str) -> bool:
        for _task_id, task in self.tasks.items():
            if task.agent == agent_hex and task.status in ACTIVE_STATUSES:
                return True
        return False

    def _run_consensus(self, prompt: str) -> str:
        def leader_fn():
            raw = gl.nondet.exec_prompt(prompt)
            return _parse_verdict(raw)

        def validator_fn(leaders_res):
            if not isinstance(leaders_res, gl.vm.Return):
                # Leader errored: agree only if we fail the same way.
                try:
                    leader_fn()
                except gl.vm.UserError as e:
                    leader_msg = leaders_res.message if hasattr(leaders_res, "message") else ""
                    mine_msg = e.message if hasattr(e, "message") else str(e)
                    return mine_msg == leader_msg
                except Exception:
                    return False
                return False
            mine = leader_fn()
            return mine == leaders_res.calldata

        return gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

    def _task_dict(self, task: Task) -> dict:
        return {
            "id": task.id,
            "title": task.title,
            "requirements": task.requirements,
            "acceptance_criteria": task.acceptance_criteria,
            "requester": task.requester,
            "agent": task.agent,
            "reward": task.reward,
            "status": task.status,
            "delivery": task.delivery,
            "evidence_ref": task.evidence_ref,
            "verdict": task.verdict,
            "verdict_reason": task.verdict_reason,
            "appeal_evidence": task.appeal_evidence,
            "appeal_count": task.appeal_count,
            "history": task.history,
        }

    def _agent_dict(self, agent: Agent) -> dict:
        return {
            "address": agent.address,
            "stake": agent.stake,
            "reputation": agent.reputation,
            "completed": agent.completed,
            "failed": agent.failed,
        }

    # ------------------------------------------------------------ test GEN
    @gl.public.write
    def claim_test_gen(self) -> str:
        sender = gl.message.sender_address
        if self.claimed.get(sender, "0") == "1":
            raise gl.vm.UserError("[EXPECTED] Test GEN already claimed by this address")
        self.claimed[sender] = "1"
        self._set_gen_balance(sender, self._gen_balance_of(sender) + CLAIM_AMOUNT)
        return str(CLAIM_AMOUNT)

    # ------------------------------------------------------------ agents
    @gl.public.write
    def register_agent(self, stake: str) -> str:
        stake_amount = _parse_int(stake, "stake")
        if stake_amount <= 0:
            raise gl.vm.UserError("[EXPECTED] Stake must be positive")
        sender = gl.message.sender_address
        if self._gen_balance_of(sender) < stake_amount:
            raise gl.vm.UserError("[EXPECTED] Insufficient GEN balance for stake")
        self._set_gen_balance(sender, self._gen_balance_of(sender) - stake_amount)
        if sender in self.agents:
            agent = self.agents[sender]
            agent.stake = str(_parse_int(agent.stake, "stake") + stake_amount)
            self.agents[sender] = agent
        else:
            self.agents[sender] = Agent(
                address=sender.as_hex,
                stake=str(stake_amount),
                reputation=str(REPUTATION_START),
                completed="0",
                failed="0",
            )
        return self.agents[sender].stake

    @gl.public.write
    def withdraw_stake(self, amount: str) -> str:
        amount_int = _parse_int(amount, "withdraw amount")
        if amount_int <= 0:
            raise gl.vm.UserError("[EXPECTED] Withdraw amount must be positive")
        sender = gl.message.sender_address
        agent = self._get_agent(sender)
        stake = _parse_int(agent.stake, "stake")
        if amount_int > stake:
            raise gl.vm.UserError("[EXPECTED] Withdraw amount exceeds stake")
        remaining = stake - amount_int
        if remaining != 0 and remaining < MIN_STAKE:
            raise gl.vm.UserError("[EXPECTED] Remaining stake must be 0 or at least the minimum stake")
        if self._has_active_task(sender.as_hex):
            raise gl.vm.UserError("[EXPECTED] Cannot withdraw while an agent task is active")
        agent.stake = str(remaining)
        self.agents[sender] = agent
        self._set_gen_balance(sender, self._gen_balance_of(sender) + amount_int)
        return agent.stake

    # ------------------------------------------------------------ tasks
    @gl.public.write
    def post_task(
        self, title: str, requirements: str, acceptance_criteria: str, reward: str
    ) -> str:
        if title.strip() == "" or len(title) > MAX_TITLE_LEN:
            raise gl.vm.UserError("[EXPECTED] Title must be non-empty and at most 200 characters")
        if requirements.strip() == "" or len(requirements) > MAX_TEXT_LEN:
            raise gl.vm.UserError("[EXPECTED] Requirements must be non-empty and at most 3000 characters")
        if acceptance_criteria.strip() == "" or len(acceptance_criteria) > MAX_TEXT_LEN:
            raise gl.vm.UserError("[EXPECTED] Acceptance criteria must be non-empty and at most 3000 characters")
        reward_amount = _parse_int(reward, "reward")
        if reward_amount < MIN_REWARD or reward_amount > MAX_REWARD:
            raise gl.vm.UserError("[EXPECTED] Reward must be between 1 and 10000 GEN")
        sender = gl.message.sender_address
        if self._gen_balance_of(sender) < reward_amount:
            raise gl.vm.UserError("[EXPECTED] Insufficient GEN balance for reward escrow")
        self._set_gen_balance(sender, self._gen_balance_of(sender) - reward_amount)
        task_id = self.next_task_id
        self.next_task_id = str(int(task_id) + 1)
        task = Task(
            id=task_id,
            title=title,
            requirements=requirements,
            acceptance_criteria=acceptance_criteria,
            requester=sender.as_hex,
            agent="",
            reward=str(reward_amount),
            status=STATUS_OPEN,
            delivery="",
            evidence_ref="",
            verdict="",
            verdict_reason="",
            appeal_evidence="",
            appeal_count="0",
            history="POSTED",
        )
        self.tasks[task_id] = task
        return task_id

    @gl.public.write
    def cancel_task(self, task_id: str) -> str:
        task = self._get_task(task_id)
        sender = gl.message.sender_address
        if task.requester != sender.as_hex:
            raise gl.vm.UserError("[EXPECTED] Only the requester can cancel this task")
        if task.status != STATUS_OPEN:
            raise gl.vm.UserError("[EXPECTED] Only an OPEN task can be cancelled: " + task.status)
        reward = _parse_int(task.reward, "reward")
        self._set_gen_balance(sender, self._gen_balance_of(sender) + reward)
        task.status = STATUS_CANCELLED
        task.history = task.history + "\nCANCELLED"
        self._save_task(task)
        return task.status

    @gl.public.write
    def claim_task(self, task_id: str) -> str:
        task = self._get_task(task_id)
        sender = gl.message.sender_address
        if task.status != STATUS_OPEN:
            raise gl.vm.UserError("[EXPECTED] Only an OPEN task can be claimed: " + task.status)
        if task.requester == sender.as_hex:
            raise gl.vm.UserError("[EXPECTED] Requester cannot claim their own task")
        agent = self._get_agent(sender)
        if _parse_int(agent.stake, "stake") < MIN_STAKE:
            raise gl.vm.UserError("[EXPECTED] Agent stake is below the 10 GEN minimum")
        task.agent = sender.as_hex
        task.status = STATUS_CLAIMED
        task.history = task.history + "\nCLAIMED|" + sender.as_hex
        self._save_task(task)
        return task.status

    @gl.public.write
    def abandon_task(self, task_id: str) -> str:
        task = self._get_task(task_id)
        sender = gl.message.sender_address
        if task.status != STATUS_CLAIMED:
            raise gl.vm.UserError("[EXPECTED] Only a CLAIMED task can be abandoned: " + task.status)
        if task.agent != sender.as_hex:
            raise gl.vm.UserError("[EXPECTED] Only the claiming agent can abandon this task")
        agent = self._get_agent(sender)
        agent.failed = str(_parse_int(agent.failed, "failed") + 1)
        agent.reputation = str(max(0, _parse_int(agent.reputation, "reputation") - REPUTATION_ABANDON_DELTA))
        self.agents[sender] = agent
        task.agent = ""
        task.status = STATUS_OPEN
        task.history = task.history + "\nABANDONED|" + sender.as_hex
        self._save_task(task)
        return task.status

    @gl.public.write
    def deliver(self, task_id: str, delivery: str, evidence_ref: str) -> str:
        task = self._get_task(task_id)
        sender = gl.message.sender_address
        if task.status != STATUS_CLAIMED:
            raise gl.vm.UserError("[EXPECTED] Only a CLAIMED task can be delivered: " + task.status)
        if task.agent != sender.as_hex:
            raise gl.vm.UserError("[EXPECTED] Only the claiming agent can deliver this task")
        if delivery.strip() == "" or len(delivery) > MAX_TEXT_LEN:
            raise gl.vm.UserError("[EXPECTED] Delivery must be non-empty and at most 3000 characters")
        if len(evidence_ref) > MAX_REF_LEN:
            raise gl.vm.UserError("[EXPECTED] Evidence reference exceeds 500 characters")
        task.delivery = delivery
        task.evidence_ref = evidence_ref
        task.status = STATUS_DELIVERED
        task.history = task.history + "\nDELIVERED"
        self._save_task(task)
        return task.status

    # ------------------------------------------------------------ consensus
    @gl.public.write
    def adjudicate(self, task_id: str) -> str:
        task = self._get_task(task_id)
        if task.status != STATUS_DELIVERED:
            raise gl.vm.UserError("[EXPECTED] Only a DELIVERED task can be adjudicated: " + task.status)
        if task.delivery.strip() == "":
            raise gl.vm.UserError("[EXPECTED] Delivery is empty, cannot adjudicate")
        prompt = _adjudication_prompt(
            task.title,
            task.requirements,
            task.acceptance_criteria,
            task.delivery,
            task.evidence_ref,
            "",
        )
        verdict = self._run_consensus(prompt)
        # Consensus reached. Only now, after agreement, write the outcome.
        decision, code = verdict.split("|")
        task.verdict = verdict
        task.verdict_reason = code
        task.history = task.history + "\nADJUDICATED|" + verdict
        if decision == "PASS":
            task.status = STATUS_ADJUDICATED_PASS
        else:
            task.status = STATUS_ADJUDICATED_FAIL
        self._save_task(task)
        return verdict

    @gl.public.write
    def appeal(self, task_id: str, new_evidence: str) -> str:
        task = self._get_task(task_id)
        if task.status != STATUS_ADJUDICATED_FAIL:
            raise gl.vm.UserError("[EXPECTED] Only a failed adjudication can be appealed: " + task.status)
        if _parse_int(task.appeal_count, "appeal count") >= 1:
            raise gl.vm.UserError("[EXPECTED] This task has already been appealed once")
        if new_evidence.strip() == "" or len(new_evidence) > MAX_TEXT_LEN:
            raise gl.vm.UserError("[EXPECTED] Appeal evidence must be non-empty and at most 3000 characters")
        task.appeal_evidence = new_evidence
        task.appeal_count = "1"
        task.status = STATUS_APPEALED
        task.history = task.history + "\nAPPEAL_SUBMITTED"
        self._save_task(task)
        return task.status

    @gl.public.write
    def adjudicate_appeal(self, task_id: str) -> str:
        task = self._get_task(task_id)
        if task.status != STATUS_APPEALED:
            raise gl.vm.UserError("[EXPECTED] Only an APPEALED task can be re-adjudicated: " + task.status)
        if task.delivery.strip() == "":
            raise gl.vm.UserError("[EXPECTED] Delivery is empty, cannot adjudicate")
        prompt = _adjudication_prompt(
            task.title,
            task.requirements,
            task.acceptance_criteria,
            task.delivery,
            task.evidence_ref,
            task.appeal_evidence,
        )
        verdict = self._run_consensus(prompt)
        # Consensus reached. Only now, after agreement, write the outcome.
        # The appeal verdict is final: no second appeal.
        decision, code = verdict.split("|")
        task.verdict = verdict
        task.verdict_reason = code
        task.history = task.history + "\nAPPEAL_ADJUDICATED|" + verdict
        if decision == "PASS":
            task.status = STATUS_ADJUDICATED_PASS
        else:
            task.status = STATUS_ADJUDICATED_FAIL
        self._save_task(task)
        return verdict

    @gl.public.write
    def submit_witness(self, task_id: str, note: str) -> str:
        """Attach a note after a final verdict. The standing verdict is
        never changed; the note is kept as a witness entry only."""
        if note.strip() == "" or len(note) > MAX_TEXT_LEN:
            raise gl.vm.UserError("[EXPECTED] Witness note must be non-empty and at most 3000 characters")
        task = self._get_task(task_id)
        if task.status not in (
            STATUS_ADJUDICATED_PASS,
            STATUS_ADJUDICATED_FAIL,
            STATUS_SETTLED_PAID,
            STATUS_SETTLED_REFUNDED,
        ):
            raise gl.vm.UserError("[EXPECTED] Witness notes are only kept after a verdict: " + task.status)
        task.history = task.history + "\nWITNESS|" + note
        self._save_task(task)
        return task.status

    # ------------------------------------------------------------ settlement
    @gl.public.write
    def settle(self, task_id: str) -> str:
        task = self._get_task(task_id)
        if task.status not in (STATUS_ADJUDICATED_PASS, STATUS_ADJUDICATED_FAIL):
            raise gl.vm.UserError("[EXPECTED] Only an adjudicated task can be settled: " + task.status)
        reward = _parse_int(task.reward, "reward")
        agent_address = Address(task.agent)
        agent = self._get_agent(agent_address)
        pool = _parse_int(self.platform_pool, "platform pool")
        if task.status == STATUS_ADJUDICATED_PASS:
            fee = reward * PLATFORM_FEE_BP // 10000
            agent_amount = reward - fee
            self._set_gen_balance(agent_address, self._gen_balance_of(agent_address) + agent_amount)
            self.platform_pool = str(pool + fee)
            agent.completed = str(_parse_int(agent.completed, "completed") + 1)
            agent.reputation = str(
                min(REPUTATION_MAX, _parse_int(agent.reputation, "reputation") + REPUTATION_PASS_DELTA)
            )
            task.status = STATUS_SETTLED_PAID
        else:
            requester_address = Address(task.requester)
            self._set_gen_balance(requester_address, self._gen_balance_of(requester_address) + reward)
            stake = _parse_int(agent.stake, "stake")
            slash = stake * SLASH_BP // 10000
            agent.stake = str(stake - slash)
            self.platform_pool = str(pool + slash)
            agent.failed = str(_parse_int(agent.failed, "failed") + 1)
            agent.reputation = str(max(0, _parse_int(agent.reputation, "reputation") - REPUTATION_FAIL_DELTA))
            task.status = STATUS_SETTLED_REFUNDED
        self.agents[agent_address] = agent
        task.history = task.history + "\nSETTLED|" + task.status
        self._save_task(task)
        return task.status

    # ------------------------------------------------------------ views
    @gl.public.view
    def get_task(self, task_id: str) -> dict:
        return self._task_dict(self._get_task(task_id))

    @gl.public.view
    def get_agent(self, agent_address: str) -> dict:
        return self._agent_dict(self._get_agent(Address(agent_address)))

    @gl.public.view
    def get_balance(self, account_address: str) -> str:
        return str(self._gen_balance_of(Address(account_address)))

    @gl.public.view
    def get_platform_pool(self) -> str:
        return self.platform_pool

    @gl.public.view
    def get_next_task_id(self) -> str:
        return self.next_task_id
