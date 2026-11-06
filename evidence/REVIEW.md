# Reviewer quick path

Shortest re-check, in order.

1. Read the contract: `contracts/agent_stake_work.py` (single file). The header comment states the category, mechanism, interaction model and evolution state, plus the money rules.
2. Confirm the deployed source matches: `sha256sum contracts/agent_stake_work.py` must equal `9b7108c726c8b6f45d5d439aba96c7459d8da90f8ee6eac3cc724ce247c6c235` (recorded in `evidence/DEPLOYMENT.md`).
3. Read the live state (no transaction needed — read-only calls against Stable Studionet, RPC `https://studio.genlayer.com/api`, contract `0x54aDe626b746b11b328921440d15c57850CE0384`):
   - `get_task("1")` → `SETTLED_PAID`, verdict `PASS|MEETS_CRITERIA`
   - `get_task("2")` → `SETTLED_PAID`, first verdict `FAIL|THIN_EVIDENCE`, appeal verdict `PASS|MEETS_CRITERIA`
   - `get_task("3")` → `SETTLED_REFUNDED`, verdict `FAIL|THIN_EVIDENCE`
   - `get_agent("0xF20b2829Cfd4daEb2d700365910e0394E3c5Cb9F")` → reputation 900, stake 40000000 microGEN, completed 2, failed 1
   - `get_platform_pool()` → 16000000 microGEN (16 GEN)
4. Check any transaction receipt from `evidence/DEPLOYMENT.md` via `eth_getTransactionReceipt` on the Studio RPC; each is FINALIZED with leader execution `SUCCESS`. The full receipt record is in `evidence/live-verification.json`.
5. Re-run the local tests: `pip install -r requirements.txt && python -m pytest tests/ -q` (17 tests, direct mode, mocked LLM).
