import sys
import json

# Ensure UTF-8 output encoding for Windows terminal
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from harness.constraints import BookingConstraint
from tools.flight_tools import reset_mock_db
from agents.react_agent import ReActAgent
from agents.plan_execute_agent import PlanThenExecuteAgent
from agents.hybrid_agent import HybridAgent


def print_banner():
    print("=" * 70)
    print("      INTELLIGENT FLIGHT BOOKING SYSTEM - AGENTIC AI (SE373)      ")
    print("                   (Agent = Model + Harness)                      ")
    print("=" * 70)


def main():
    print_banner()
    reset_mock_db()

    print("\n[SELECT AGENT ARCHITECTURE]:")
    print("1. ReAct Agent (Thought -> Action -> Observation Loop)")
    print("2. Plan-then-Execute (LLM Planner -> Step Executor -> Re-planner)")
    print("3. Hybrid (High-level Coordinator + Micro ReAct Sub-agents)")

    choice = input("\nEnter your choice (1/2/3, default 1): ").strip() or "1"

    print("\n--- ENTER BOOKING REQUIREMENTS ---")
    origin = input("Origin airport (e.g., SGN): ").strip().upper() or "SGN"
    dest = input("Destination airport (e.g., DAD): ").strip().upper() or "DAD"
    date = input("Departure date (e.g., 2026-10-07): ").strip() or "2026-10-07"
    budget_raw = input("Maximum budget (VND, e.g., 2200000): ").strip() or "2200000"
    baggage_raw = input("Checked baggage allowance (kg, e.g., 15): ").strip() or "15"
    passenger = input("Passenger name (e.g., Phan Huynh Hung): ").strip() or "Phan Huynh Hung"

    constraints = BookingConstraint(
        origin=origin,
        dest=dest,
        date=date,
        max_price=int(budget_raw),
        depart_before="12:00",
        passenger_name=passenger,
        baggage_kg=int(baggage_raw)
    )

    print("\n" + "-" * 70)
    print("Configured Parameters:")
    print(constraints.to_natural_language())
    print("-" * 70)

    # Launch selected agent with interactive=True
    if choice == "2":
        print("\n>>> Launching: Plan-then-Execute Agent...")
        agent = PlanThenExecuteAgent(constraints=constraints, enable_guard=True, interactive=True)
    elif choice == "3":
        print("\n>>> Launching: Hybrid Agent...")
        agent = HybridAgent(constraints=constraints, enable_guard=True, interactive=True)
    else:
        print("\n>>> Launching: ReAct Agent...")
        agent = ReActAgent(constraints=constraints, enable_guard=True, interactive=True)

    try:
        res = agent.run()
    except Exception as e:
        print(f"\n[EXECUTION ERROR]: {e}")
        return

    print("\n" + "=" * 70)
    print(f"EXECUTION STATUS: {res.get('status')}")
    print(f"Total Turns: {res.get('turns')}")
    print("=" * 70)

    if "report" in res:
        print(res["report"].format_terminal())
    elif res.get("status") == "SUCCESS":
        print("\n CONGRATULATIONS! FLIGHT BOOKED SUCCESSFULLY!")
        print(f" Booking Reference Code: {res.get('booking_code')}")
        print(f" Independent Verification: {res.get('reason')}")
    else:
        print(f"\n[!] Failed: {res.get('reason')}")

    # Print execution trace summary
    trace = res.get("trace", [])
    if trace:
        print("\n--- EXECUTION TRACE ---")
        for i, step in enumerate(trace, 1):
            tool_name = step.get("action") or step.get("tool") or "UNKNOWN"
            thought = step.get("thought", "")
            if thought:
                print(f"Step {i} [Thought]: {thought[:100]}...")
            print(f"Step {i} [Action ]: {tool_name} -> Args: {step.get('args')}")


if __name__ == "__main__":
    main()
