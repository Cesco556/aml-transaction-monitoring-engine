# CI run log (Docs Sync Agent)

**Command run:** `./scripts/ci.sh`

**Date:** Generated during docs consistency sync.

**Exit code:** 2 (lint failed; see below). *CI failed due to pre-existing lint in `src/` (E402, UP038, SIM108, I001). Docs Sync Agent did not modify source code.*

---

## Final 30 lines of output

```
src/aml_monitoring/run_rules.py:21:1: E402 Module level import not at top of file
   |
19 | from aml_monitoring.models import Account, Alert, AuditLog, Transaction
20 | from aml_monitoring.rules import get_all_rules
21 | from aml_monitoring.rules.base import RuleContext
   | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
22 | from aml_monitoring.schemas import RuleResult
23 | from aml_monitoring.scoring import compute_transaction_risk
   |

src/aml_monitoring/run_rules.py:22:1: E402 Module level import not at top of file
   |
20 | from aml_monitoring.rules import get_all_rules
21 | from aml_monitoring.rules.base import RuleContext
22 | from aml_monitoring.schemas import RuleResult
   | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
23 | from aml_monitoring.scoring import compute_transaction_risk
   |

src/aml_monitoring/run_rules.py:23:1: E402 Module level import not at top of file
   |
21 | from aml_monitoring.rules.base import RuleContext
22 | from aml_monitoring.schemas import RuleResult
23 | from aml_monitoring.scoring import compute_transaction_risk
   | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   |

Found 20 errors.
[*] 1 fixable with the `--fix` option (3 hidden fixes can be enabled with the `--unsafe-fixes` option).
make: *** [lint] Error 1
```

---

*To get exit code 0: fix lint in `src/` (e.g. `make format` and address E402/UP038/SIM108/I001) then re-run `./scripts/ci.sh`.*
