# Known limitations

Scope and range statements for this contract. These describe what the contract does and does not cover.

- Nominal TEST units. All GEN in this contract is a nominal in-contract TEST ledger (`claim_test_gen` credits 1,000 GEN once per address). Staking, escrow, payment, refund and slashing move ledger entries only; no real GEN is transferred by this contract.
- Delivery evidence is the stored delivery text. Validators judge the delivery text and evidence reference stored on-chain at delivery time. The evidence reference is a link or identifier supplied by the agent; the contract does not fetch the linked page itself.
- No wall-clock deadlines. The contract has no clock source. Stale claims end only through explicit calls (`abandon_task`, `cancel_task` while OPEN).
- Single-contract primitive. There is no frontend. Calls are made with the GenLayer CLI or `genlayer-py`; see `scripts/verify_studionet.py` for the full call sequence.
- Script accounts only. The live run used temporary script-generated accounts. The browser-wallet signing path was not exercised in this run.
- LLM verdicts are consensus decisions. Adjudication verdicts are produced by validators independently running the same prompt on the same stored delivery and agreeing on a canonical `DECISION|CODE` string. They are judgments about whether the delivery meets the written criteria, not deterministic measurements.
- Explorer availability. The network's explorer address page is linked from the README; when last checked it returned HTTP 503, so the on-chain record is verifiable through the Studio RPC (`eth_getTransactionReceipt`, contract reads) as documented in `live-verification.json`.
- Runner version. The contract pins runner `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`. The linter reports a newer runner is available (`1zr6nqk597d97kg0dyxg0shhrykx5v02zjgnyrajapy4wlqvfvwh`); the deployed contract was verified against the pinned runner.
