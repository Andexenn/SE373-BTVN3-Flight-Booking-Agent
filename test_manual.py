import sys
import json

# Ensure UTF-8 output encoding for Windows terminal
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from harness.constraints import BookingConstraint
from harness.permission import PermissionGuard
from harness.loop_detector import LoopDetector
from harness.completion_sensor import CompletionSensor
from harness.handoff import HandoffReport
from tools import flight_tools


def test_all():
    print("==================================================")
    print("   STARTING INDEPENDENT UNIT TESTS FOR HARNESS")
    print("==================================================")

    # 1. TEST CONSTRAINT VALIDATION LAYER
    constraint = BookingConstraint(
        origin="SGN", dest="DAD", date="2026-10-07",
        max_price=2200000, depart_before="12:00", baggage_kg=15
    )
    print("\n[1] Constraint Validation Layer (BookingConstraint):")
    print(f"    -> Initialized Pydantic target constraints: {constraint.model_dump()}")
    assert constraint.max_price == 2200000, "Price ceiling initialization error!"
    assert constraint.baggage_kg == 15, "Baggage weight initialization error!"

    # 2. TEST PERMISSION GUARD LAYER
    guard = PermissionGuard(price_limit=2000000, auto_approve=False)
    print("\n[2] Permission Guard Layer (PermissionGuard):")

    # Test 2.1: Sensitive payment tool (pay) -> MUST BE INTERCEPTED
    allowed_pay, msg_pay = guard.check_permission("pay", {}, {})
    print(f"    - Attempting 'pay': Allowed = {allowed_pay} | Reason: {msg_pay}")
    assert allowed_pay is False, "ERROR: Payment tool was not blocked!"

    # Test 2.2: Non-refundable ticket -> MUST BE INTERCEPTED FOR APPROVAL
    allowed_book, msg_book = guard.check_permission(
        "book_ticket",
        {"flight_id": "VN122", "seat_number": "12A"},
        {"current_price": 1850000, "refundable": False}
    )
    print(f"    - Attempting non-refundable booking: Allowed = {allowed_book} | Reason: {msg_book}")
    assert allowed_book is False, "ERROR: Non-refundable ticket was not blocked!"

    # Test 2.3: auto_approve mode -> MUST PERMIT EXECUTION
    guard_auto = PermissionGuard(auto_approve=True)
    allowed_auto, _ = guard_auto.check_permission("book_ticket", {"flight_id": "QH118"})
    print(f"    - Attempting booking with auto_approve=True: Allowed = {allowed_auto}")
    assert allowed_auto is True, "ERROR: Auto approve failed to permit execution!"

    # 3. TEST LOOP DETECTOR LAYER
    detector = LoopDetector(repeat_k=2)
    print("\n[3] Loop Detector Layer (LoopDetector):")

    res1 = detector.check("search_flights", {"origin": "SGN", "dest": "DAD"})
    print(f"    - Round 1 calling 'search_flights': {res1}")
    assert res1 is None, "Round 1 should not trigger loop warning!"

    res2 = detector.check("search_flights", {"origin": "SGN", "dest": "DAD"})
    print(f"    - Round 2 repeating identical arguments: {res2}")
    assert res2 == "LOOP", "ERROR: Loop was not detected!"

    # 4. TEST COMPLETION SENSOR LAYER
    print("\n[4] Completion Sensor Layer (CompletionSensor):")
    flight_tools.reset_mock_db()

    # Test 4.1: Verify non-existent booking code -> MUST REPORT FAILURE
    success_fake, msg_fake = CompletionSensor.verify("BK_NON_EXISTENT", constraint)
    print(f"    - Verifying invalid booking code: Success = {success_fake} | Detail: {msg_fake}")
    assert success_fake is False, "ERROR: Sensor accepted non-existent booking code!"

    # Test 4.2: Verify genuine valid booking
    book_res = flight_tools.book_ticket.invoke({
        "flight_id": "QH118",
        "seat_number": "05D",
        "passenger_name": "Nguyen Van A",
        "baggage_kg": 15
    })
    book_data = json.loads(book_res)
    real_code = book_data["booking_code"]

    success_real, msg_real = CompletionSensor.verify(real_code, constraint)
    print(f"    - Verifying confirmed QH118 booking: Success = {success_real} | Detail: {msg_real}")
    assert success_real is True, f"ERROR: Sensor rejected valid booking! ({msg_real})"

    # 5. TEST HANDOFF REPORT LAYER
    print("\n[5] Human Handoff Report Layer (HandoffReport):")
    report = HandoffReport(
        status="HANDOFF_TEST",
        current_stage="Unit Testing",
        actions_taken=[{"tool": "search_flights", "args": {"origin": "SGN"}}],
        failed_attempts=["Searched flights but none matched criteria"],
        specific_question="Would you like to increase budget to continue search?"
    )
    terminal_output = report.format_terminal()
    print("    - Validated terminal output format:")
    print(terminal_output)
    assert "HUMAN HANDOFF REPORT" in terminal_output

    print("\n==================================================")
    print(">>> ALL HARNESS SAFETY LAYERS PASSED TESTS (100% PASS) <<<")
    print("==================================================")


if __name__ == "__main__":
    test_all()
