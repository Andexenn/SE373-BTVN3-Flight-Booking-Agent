import sys
import time
from typing import Dict, Any, List

# Ensure UTF-8 output encoding for Windows terminal
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from tabulate import tabulate
from harness.constraints import BookingConstraint
from tools.flight_tools import reset_mock_db, set_flight_seats
from agents.react_agent import ReActAgent
from agents.plan_execute_agent import PlanThenExecuteAgent
from agents.hybrid_agent import HybridAgent


def run_benchmarks():
    print("=" * 85)
    print("   BENCHMARK EVALUATION: 3 AGENT ARCHITECTURES (SE373)")
    print("=" * 85)

    base_constraints = BookingConstraint(
        origin="SGN",
        dest="DAD",
        date="2026-10-07",
        max_price=2300000,
        depart_before="12:00",
        passenger_name="Nguyen Van A",
        baggage_kg=15,
        require_refundable=False
    )

    scenarios = [
        {
            "name": "Scenario 1: Happy Path",
            "description": "Book SGN-DAD with 15kg baggage, 2.3M VND budget. Seats available on all flights.",
            "setup": lambda: None,
            "auto_approve": True
        },
        {
            "name": "Scenario 2: Dynamic Environment (Seat Depletion)",
            "description": "Best-fare flight QH118 suddenly sold out. Agent must adaptively switch to VN122.",
            "setup": lambda: set_flight_seats("QH118", []),
            "auto_approve": True
        },
        {
            "name": "Scenario 3: Permission Guard Interception",
            "description": "Run with auto_approve=False to verify interception before sensitive booking action.",
            "setup": lambda: None,
            "auto_approve": False
        }
    ]

    results_table = []

    for sc_idx, sc in enumerate(scenarios, 1):
        print(f"\n>>> Running {sc['name']}...")
        print(f"    Description: {sc['description']}")

        # 3 Agent architectures to benchmark
        agent_factories = [
            ("ReAct Agent", lambda c, aa: ReActAgent(c, auto_approve=aa, enable_guard=True)),
            ("Plan-then-Execute", lambda c, aa: PlanThenExecuteAgent(c, auto_approve=aa, enable_guard=True)),
            ("Hybrid Agent", lambda c, aa: HybridAgent(c, auto_approve=aa, enable_guard=True))
        ]

        for idx, (agent_name, factory) in enumerate(agent_factories):
            # Strict fairness: Always reset Mock DB and apply scenario setup before each run
            reset_mock_db()
            sc["setup"]()

            start_time = time.time()
            try:
                agent = factory(base_constraints, sc["auto_approve"])
                res = agent.run()
                elapsed = time.time() - start_time
                status = res.get("status", "UNKNOWN")
                turns = res.get("turns", 0)
                booking_code = res.get("booking_code") or "-"
                verified = "PASS" if status == "SUCCESS" else ("SAFE INTERCEPT" if status == "WAIT_APPROVAL" else "FAILED")
            except Exception as e:
                elapsed = time.time() - start_time
                status = f"ERROR: {type(e).__name__}"
                turns = 0
                booking_code = "-"
                verified = "SYSTEM ERROR"
                print(f"    [!] Error running {agent_name}: {e}")

            sc_label = sc["name"] if idx == 0 else ""
            results_table.append([
                sc_label,
                agent_name,
                status,
                turns,
                f"{elapsed:.2f}s",
                booking_code,
                verified
            ])

        results_table.append(["-" * 28, "-" * 18, "-" * 15, "-" * 6, "-" * 7, "-" * 15, "-" * 14])

    headers = [
        "Test Scenario",
        "Agent Architecture",
        "Execution Status",
        "Turns",
        "Latency",
        "Booking Code",
        "Harness Verification"
    ]

    print("\n" + "=" * 105)
    print("                      EXPERIMENTAL BENCHMARK COMPARISON REPORT")
    print("=" * 105)
    print(tabulate(results_table, headers=headers, tablefmt="grid"))
    print("\n[NOTES]:")
    print("- 'PASS': Passed independent programmatic verification by CompletionSensor.")
    print("- 'SAFE INTERCEPT': PermissionGuard successfully intercepted flow prior to sensitive booking action.")
    print("- 'Turns': Number of agent tool interactions and reasoning cycles.")


if __name__ == "__main__":
    run_benchmarks()
