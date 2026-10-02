import json
from typing import Tuple, Optional
from harness.constraints import BookingConstraint
from tools.flight_tools import get_booking


class CompletionSensor:
    """Independent programmatic verification layer for flight booking completion."""

    @staticmethod
    def verify(booking_code: Optional[str], constraints: BookingConstraint) -> Tuple[bool, str]:
        if not booking_code:
            return False, "Booking code is empty (None or empty string)."

        raw = get_booking(booking_code)
        res = json.loads(raw)
        if res.get("status") != "found":
            return False, f"Booking code '{booking_code}' was not found in Mock DB."

        b = res["data"]
        is_confirmed = (b.get("status") == "confirmed")
        is_paid = (b.get("paid") is True)
        total_price = b.get("total_price", b.get("price", float("inf")))
        is_price_ok = (total_price <= constraints.max_price)
        is_date_ok = (b.get("date") == constraints.date)
        is_time_ok = (b.get("dep_time", "99:99") <= constraints.depart_before)
        is_route_ok = (
            b.get("origin", "").upper() == constraints.origin.upper() and
            b.get("dest", "").upper() == constraints.dest.upper()
        )

        if not (is_confirmed and is_paid):
            return False, f"Ticket '{booking_code}' is not confirmed or payment is incomplete."

        if not is_route_ok:
            return False, f"Route mismatch: Actual {b.get('origin')}->{b.get('dest')}, expected {constraints.origin}->{constraints.dest}."

        if not is_date_ok:
            return False, f"Date mismatch: Actual {b.get('date')}, expected {constraints.date}."

        if not is_time_ok:
            return False, f"Departure time {b.get('dep_time')} is later than required ({constraints.depart_before})."

        if not is_price_ok:
            return False, f"Total price {total_price:,.0f} VND exceeds budget ceiling ({constraints.max_price:,.0f} VND)."

        if constraints.require_refundable and not b.get("refundable", False):
            return False, "Booked ticket does not meet customer's refundability requirement."

        if constraints.baggage_kg > 0 and b.get("baggage_kg", 0) < constraints.baggage_kg:
            return False, f"Checked baggage ({b.get('baggage_kg', 0)} kg) is less than required ({constraints.baggage_kg} kg)."

        return True, (
            f"VERIFIED VALID (100% PASS): Confirmed booking {booking_code} for {b.get('passenger_name')}, "
            f"flight {b.get('flight_id')} on {b.get('date')} at {b.get('dep_time')}, "
            f"total fare {total_price:,.0f} VND."
        )
