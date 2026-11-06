# Deployment record

- Network: Stable Studionet (Chain ID 61999)
- RPC: https://studio.genlayer.com/api
- Contract: `0x54aDe626b746b11b328921440d15c57850CE0384`
- Explorer: https://genlayer-explorer.vercel.app/address/0x54aDe626b746b11b328921440d15c57850CE0384
- Deploy transaction: `0xe96adf929f286f6357345ac28f7d673d599cc88c095fe464ec028253e17f1726`
- Deployed source: `contracts/agent_stake_work.py`
- Source SHA256: `9b7108c726c8b6f45d5d439aba96c7459d8da90f8ee6eac3cc724ce247c6c235`
- Source commit: `ad58080f89bc31af581d5a8c731c601a93cc20ee` (the deployed file is byte-identical to the file in this repository — see the SHA256 above)
- Runner: `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` (pinned; the network rejects the `latest`/`test` aliases)
- Live actors (ephemeral script accounts, addresses only): requester `0x9EEa93e124fc9642472Ba72C3Ce7534D09658f29`, agent `0xF20b2829Cfd4daEb2d700365910e0394E3c5Cb9F`

## Transactions

Every transaction below reached FINALIZED with leader execution `SUCCESS`. Full receipts and read-back state: [`live-verification.json`](live-verification.json).

| Step | Transaction hash | Status | Execution |
| --- | --- | --- | --- |
| deploy | `0xe96adf929f286f6357345ac28f7d673d599cc88c095fe464ec028253e17f1726` | FINALIZED | SUCCESS |
| requester claim_test_gen | `0x8cf7a45cd37e59e5fc12bfb23b4a2d5b34e10d7640f08d5aeff1b200b7b298cd` | FINALIZED | SUCCESS |
| agent claim_test_gen | `0x446a69ec246b3060ee1619c5921ce0ac22b3f702739bcbe46ccf583c85787b36` | FINALIZED | SUCCESS |
| agent register_agent 50 GEN | `0xa26fa4e8eb78b37c77e1fef9a6f2a6bf52f350a33839dc4fdfe85be6b8e7ae7e` | FINALIZED | SUCCESS |
| task1: post_task | `0x93366ac235c03012dd7d9b8b8b2c7d247a3d146173758904c7ac1d0a5e2804e3` | FINALIZED | SUCCESS |
| task1: claim_task | `0xff5a4ca112ba3d5ffbb9a197504cc6a39e94a5ef4e16c3b7c766f86e24d9dcfb` | FINALIZED | SUCCESS |
| task1: deliver (good) | `0x7294df0d2e30d62bac02dfa72853fcd8d24d53e39a1f7afeba299579d1ba0dae` | FINALIZED | SUCCESS |
| task1: adjudicate | `0xabcc064f7b45aae1892293961a2a94480922a2728a5ba9925d7595c030be629e` | FINALIZED | SUCCESS |
| task1: settle | `0x69e24cfa7c0a5564aa2ff6f75302505ce73e53e9a683de5fe4ebb64c81d14036` | FINALIZED | SUCCESS |
| task2: post_task | `0x9a689a410be794408ac6c95bb40c6494793c6e02c67490a6d530c688b3f5fd23` | FINALIZED | SUCCESS |
| task2: claim_task | `0xedcc66c1afe8bb69cf08ed8ab7d628ff7f726b79c2fd12c34e5f90aceb2ddb45` | FINALIZED | SUCCESS |
| task2: deliver (thin) | `0x7b8338b8ee8d03e4c0e693de8c0855efe3e41ef660f078d0f1ec2be774f255e0` | FINALIZED | SUCCESS |
| task2: adjudicate | `0x50485b19780a8399a4e9566dc5733614672b1bd94a838af2148173d045aafc44` | FINALIZED | SUCCESS |
| task2: appeal | `0xa19d14b1ec725c04abcc697f107c3ae194b54e33d41c93edd3cbe86663623a46` | FINALIZED | SUCCESS |
| task2: adjudicate_appeal | `0x18337e5d30860bf8f4e4cfc8d4c8ad036270a17a1b0b3c11c2a79ef4819f0f56` | FINALIZED | SUCCESS |
| task2: settle | `0x7cc6c2aca0919deed17a2297de225fff4f2b3b88c0a8789164a179a31b479edb` | FINALIZED | SUCCESS |
| task3: post_task | `0x8816d5d3b4da4928ac9db0057dce1fd19aa0c4a87e776fe05f8045c4a59eab49` | FINALIZED | SUCCESS |
| task3: claim_task | `0x6cd906f7838ff7a7040f670314531aad685e28044fb654d1410db826e5298f71` | FINALIZED | SUCCESS |
| task3: deliver (thin) | `0xcf25c4f536cd8392e318c662e00df3f56776061732537fed6df3b09ee97ac42b` | FINALIZED | SUCCESS |
| task3: adjudicate | `0xc32cbccbcd079175b1f593682f65b29a563024b0dbd5faa3d922ea2dd194e1c2` | FINALIZED | SUCCESS |
| task3: settle | `0xdbed782341eafa1564a4caba5ce3caa8351c94452d86944fda397d63629fa96f` | FINALIZED | SUCCESS |

## Final read-back (after all transactions)

- Task 1: `SETTLED_PAID`, verdict `PASS|MEETS_CRITERIA`, reward 100 GEN.
- Task 2: `SETTLED_PAID`, first verdict `FAIL|THIN_EVIDENCE`, appeal verdict `PASS|MEETS_CRITERIA`, reward 20 GEN.
- Task 3: `SETTLED_REFUNDED`, verdict `FAIL|THIN_EVIDENCE`, reward 20 GEN.
- Agent: reputation 900, stake 40 GEN, completed 2, failed 1.
- Platform pool: 16 GEN. Requester balance: 880 GEN. Agent balance: 1,064 GEN.

## Superseded deployments

These deployments happened during development and are not the deliverable contract. They are recorded here rather than deleted.

- `0x64C13974a06eb39d88Dba8e9F8Faed8f037c93a2` — deploy probe from a throwaway account, deploy tx `0x8c67a2f9bf0acba2d32edaa4d0daeb6f7c1574b24889b4c9f94b8ce7d62987f0` (FINALIZED, SUCCESS). Used only to confirm the pinned runner header deploys.
- `0xDc37378af1683407E016F2A1783298F311e5b2b8` — first live-run deployment, deploy tx `0x604ae88ebc27cda065d1aa506b16ce2881aa221f0ec15974d5d0f0b21825fd41` (FINALIZED, SUCCESS). Deploy and both `claim_test_gen` calls finalized; the run was interrupted by a Studio RPC 502 Bad Gateway while polling the `register_agent` receipt, and its ephemeral accounts were not recoverable, so the run was repeated from scratch.
- `0xf36603A4C197D796E61127705214F0d73a7C3C5E` — deploy rejected by the network: the transaction FINALIZED but the leader execution was `ERROR` (`invalid_contract`), because the contract header used the `py-genlayer:latest` alias, which the network rejects. No code was stored at that address. Fixed by pinning the runner version (see above).
