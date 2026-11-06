"""Deploy AgentStakeWork to Stable Studionet and verify the lifecycle live.

Ephemeral accounts are generated in memory only. Private keys are never
written to disk, logs, or the repository. Only addresses, transaction
hashes, and read-back state are recorded.

Run from the repository root:
    python3 scripts/verify_studionet.py

Output: evidence/live-verification.json (updated after every step).
Requires: genlayer-py, eth-account. Network: Stable Studionet (61999).
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

from eth_account import Account

from genlayer_py import create_client
from genlayer_py.chains import studionet
from genlayer_py.types.transactions import TransactionStatus

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "contracts" / "agent_stake_work.py"
EVIDENCE_PATH = ROOT / "evidence" / "live-verification.json"
RPC = "https://studio.genlayer.com/api"
CHAIN_ID = 61999

GEN = 1_000_000
WAIT_INTERVAL_MS = 5000
WAIT_RETRIES = 240  # 240 x 5s = up to 20 minutes per transaction

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


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def tx_hash_str(tx) -> str:
    if isinstance(tx, bytes):
        return "0x" + tx.hex()
    return str(tx)


def leader_execution_result(receipt: dict):
    try:
        return receipt["consensus_data"]["leader_receipt"][0]["execution_result"]
    except (KeyError, IndexError, TypeError):
        return None


def receipt_summary(receipt: dict) -> dict:
    return {
        "hash": receipt.get("hash") or receipt.get("tx_id"),
        "status": str(receipt.get("status_name") or receipt.get("status")),
        "execution_result": leader_execution_result(receipt),
        "contract_address": (receipt.get("data") or {}).get("contract_address"),
    }


class Runner:
    def __init__(self, contract_address: str | None = None):
        self.requester = Account.create()
        self.agent = Account.create()
        self.contract_address = contract_address
        self.evidence = {
            "network": "Stable Studionet",
            "chain_id": CHAIN_ID,
            "rpc": RPC,
            "contract_address": contract_address,
            "deploy_tx": None,
            "deploy_source_sha256": hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest(),
            "accounts": {
                "requester": self.requester.address,
                "agent": self.agent.address,
            },
            "steps": [],
            "final_readback": {},
            "notes": [],
        }
        self._save()

    def _save(self) -> None:
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_PATH.write_text(json.dumps(self.evidence, indent=2, sort_keys=False))

    def client_for(self, account):
        return create_client(chain=studionet, account=account, endpoint=RPC)

    def wait_finalized(self, client, tx_hash: str, label: str) -> dict:
        """Wait for FINALIZED, tolerating transient RPC failures (502s, bad
        gateway HTML, dropped connections). Retries the poll; never resends
        the transaction."""
        last_error = None
        for attempt in range(30):
            try:
                receipt = client.wait_for_transaction_receipt(
                    tx_hash,
                    status=TransactionStatus.FINALIZED,
                    interval=WAIT_INTERVAL_MS,
                    retries=12,  # 60s of polling per attempt
                )
                summary = receipt_summary(receipt)
                log(f"  -> {label}: status={summary['status']} execution={summary['execution_result']}")
                if summary["status"] != "FINALIZED":
                    raise RuntimeError(f"{label}: not FINALIZED: {summary}")
                if summary["execution_result"] != "SUCCESS":
                    raise RuntimeError(f"{label}: execution not SUCCESS: {json.dumps(receipt, default=str)[:2000]}")
                return summary
            except RuntimeError:
                raise
            except Exception as e:  # transient RPC failure: retry the poll
                last_error = e
                log(f"  !! {label}: RPC poll failed (attempt {attempt + 1}/30): {str(e)[:200]}; retrying in 10s")
                time.sleep(10)
        raise RuntimeError(f"{label}: receipt poll kept failing: {last_error}")

    def write(self, account, method: str, args, label: str) -> dict:
        client = self.client_for(account)
        tx = client.write_contract(
            self.contract_address, method, account=account, args=list(args)
        )
        tx_hash = tx_hash_str(tx)
        # Record the hash before waiting, so a crash still leaves it behind.
        step = {"step": label, "method": method, "args": [str(a)[:120] for a in args],
                "tx_hash": tx_hash, "status": "SENT", "execution_result": None}
        self.evidence["steps"].append(step)
        self._save()
        summary = self.wait_finalized(client, tx_hash, label)
        step.update(summary)
        self._save()
        return summary

    def read(self, method: str, args=None):
        last_error = None
        for attempt in range(10):
            try:
                client = self.client_for(self.requester)
                return client.read_contract(self.contract_address, method, args=list(args or []))
            except Exception as e:
                last_error = e
                log(f"  !! read {method}: RPC failed (attempt {attempt + 1}/10): {str(e)[:200]}; retrying in 5s")
                time.sleep(5)
        raise RuntimeError(f"read {method} kept failing: {last_error}")

    def deploy(self) -> None:
        code = CONTRACT_PATH.read_bytes()
        client = self.client_for(self.requester)
        log("deploying contract...")
        tx = client.deploy_contract(code, account=self.requester)
        tx_hash = tx_hash_str(tx)
        summary = self.wait_finalized(client, tx_hash, "deploy")
        address = summary.get("contract_address")
        if not address:
            raise RuntimeError(f"deploy receipt has no contract address: {summary}")
        self.contract_address = address
        self.evidence["contract_address"] = address
        self.evidence["deploy_tx"] = tx_hash
        self.evidence["steps"].append(
            {"step": "deploy", "method": "__init__", "args": [],
             "tx_hash": tx_hash, **summary}
        )
        self._save()
        log(f"deployed at {address}")

    def post_and_claim(self, reward_gen: int, label: str) -> str:
        task_id = self.read("get_next_task_id")
        self.write(self.requester, "post_task",
                   [TASK_TITLE, TASK_REQUIREMENTS, TASK_CRITERIA, str(reward_gen * GEN)],
                   f"{label}: post_task")
        self.write(self.agent, "claim_task", [task_id], f"{label}: claim_task")
        return task_id

    def adjudicate_and_read(self, task_id: str, method: str, label: str) -> str:
        self.write(self.requester, method, [task_id], label)
        task = self.read("get_task", [task_id])
        return task["verdict"]

    def settle_and_read(self, task_id: str, label: str) -> dict:
        self.write(self.requester, "settle", [task_id], label)
        return self.read("get_task", [task_id])


def main() -> int:
    contract_address = None
    if len(sys.argv) > 2 and sys.argv[1] == "--contract-address":
        contract_address = sys.argv[2]
    runner = Runner(contract_address)
    log(f"requester: {runner.requester.address}")
    log(f"agent:     {runner.agent.address}")

    if not runner.contract_address:
        runner.deploy()

    # Fund both actors with TEST GEN (nominal in-contract ledger).
    runner.write(runner.requester, "claim_test_gen", [], "requester claim_test_gen")
    runner.write(runner.agent, "claim_test_gen", [], "agent claim_test_gen")
    runner.write(runner.agent, "register_agent", [str(50 * GEN)], "agent register_agent 50 GEN")

    demos = {"pass_settled": False, "fail_settled": False, "appeal_adjudicated": False}

    # --- Task 1: happy path (good delivery, expect PASS) ---
    t1 = runner.post_and_claim(100, "task1")
    runner.write(runner.agent, "deliver", [t1, GOOD_DELIVERY, "https://example.invalid/summary"],
                 "task1: deliver (good)")
    verdict1 = runner.adjudicate_and_read(t1, "adjudicate", "task1: adjudicate")
    log(f"task1 verdict: {verdict1}")
    settled1 = runner.settle_and_read(t1, "task1: settle")
    log(f"task1 settled: {settled1['status']}")
    if settled1["status"] == "SETTLED_PAID":
        demos["pass_settled"] = True
    elif settled1["status"] == "SETTLED_REFUNDED":
        demos["fail_settled"] = True

    # --- Task 2: thin delivery, expect FAIL, then appeal with good evidence ---
    t2 = runner.post_and_claim(20, "task2")
    runner.write(runner.agent, "deliver", [t2, THIN_DELIVERY, ""], "task2: deliver (thin)")
    verdict2 = runner.adjudicate_and_read(t2, "adjudicate", "task2: adjudicate")
    log(f"task2 verdict: {verdict2}")
    if verdict2.startswith("FAIL"):
        runner.write(runner.agent, "appeal", [t2, GOOD_DELIVERY], "task2: appeal")
        verdict2b = runner.adjudicate_and_read(t2, "adjudicate_appeal", "task2: adjudicate_appeal")
        log(f"task2 appeal verdict: {verdict2b}")
        demos["appeal_adjudicated"] = True
        settled2 = runner.settle_and_read(t2, "task2: settle")
        log(f"task2 settled: {settled2['status']}")
        if settled2["status"] == "SETTLED_PAID":
            demos["pass_settled"] = True
        else:
            demos["fail_settled"] = True
    else:
        settled2 = runner.settle_and_read(t2, "task2: settle")
        log(f"task2 settled (unexpected PASS on thin delivery): {settled2['status']}")
        demos["pass_settled"] = True
        runner.evidence["notes"].append(
            "task2 thin delivery was adjudicated PASS; appeal path not demonstrated on task2."
        )

    # --- Task 3: thin delivery, expect FAIL, settle directly (refund + slash) ---
    t3 = runner.post_and_claim(20, "task3")
    runner.write(runner.agent, "deliver", [t3, THIN_DELIVERY, ""], "task3: deliver (thin)")
    verdict3 = runner.adjudicate_and_read(t3, "adjudicate", "task3: adjudicate")
    log(f"task3 verdict: {verdict3}")
    settled3 = runner.settle_and_read(t3, "task3: settle")
    log(f"task3 settled: {settled3['status']}")
    if settled3["status"] == "SETTLED_REFUNDED":
        demos["fail_settled"] = True
    elif settled3["status"] == "SETTLED_PAID":
        demos["pass_settled"] = True

    # --- Fallback: one extra task for any demo still missing ---
    missing = [k for k, v in demos.items() if not v]
    if missing:
        runner.evidence["notes"].append(f"missing demos after task3: {missing}; running fallback task4.")
        t4 = runner.post_and_claim(20, "task4-fallback")
        delivery = THIN_DELIVERY if "fail_settled" in missing else GOOD_DELIVERY
        runner.write(runner.agent, "deliver", [t4, delivery, ""], "task4: deliver")
        verdict4 = runner.adjudicate_and_read(t4, "adjudicate", "task4: adjudicate")
        log(f"task4 verdict: {verdict4}")
        if verdict4.startswith("FAIL") and "appeal_adjudicated" in missing:
            runner.write(runner.agent, "appeal", [t4, GOOD_DELIVERY], "task4: appeal")
            verdict4b = runner.adjudicate_and_read(t4, "adjudicate_appeal", "task4: adjudicate_appeal")
            log(f"task4 appeal verdict: {verdict4b}")
            demos["appeal_adjudicated"] = True
        settled4 = runner.settle_and_read(t4, "task4: settle")
        log(f"task4 settled: {settled4['status']}")
        if settled4["status"] == "SETTLED_PAID":
            demos["pass_settled"] = True
        else:
            demos["fail_settled"] = True

    # --- Final read-back ---
    final = {
        "tasks": {},
        "agent": runner.read("get_agent", [runner.agent.address]),
        "platform_pool_microgen": runner.read("get_platform_pool"),
        "requester_balance_microgen": runner.read("get_balance", [runner.requester.address]),
        "agent_balance_microgen": runner.read("get_balance", [runner.agent.address]),
        "demos": demos,
    }
    for tid in ["1", "2", "3", "4"]:
        try:
            final["tasks"][tid] = runner.read("get_task", [tid])
        except Exception as e:  # task may not exist
            log(f"get_task {tid}: {e}")
    runner.evidence["final_readback"] = final
    runner.evidence["notes"].append(f"demos demonstrated: {demos}")
    runner._save()
    log("DONE")
    log(json.dumps(final, indent=2)[:4000])
    if not all(demos.values()):
        log(f"WARNING: not all demos were demonstrated: {demos}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
