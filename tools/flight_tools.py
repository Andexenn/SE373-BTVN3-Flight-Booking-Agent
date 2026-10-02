import json
import copy
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool

# Initial Mock Flights Database (slightly updated schedules, fares, and additional flight)
INITIAL_MOCK_FLIGHTS: List[Dict[str, Any]] = [
    {
        "flight_id": "VN122",
        "airline": "Vietnam Airlines",
        "origin": "SGN",
        "dest": "DAD",
        "date": "2026-10-07",
        "dep_time": "08:45",
        "price": 1850000,
        "refundable": False,
        "seats": ["12A", "12B"],
        "baggage_rate_per_kg": 25000
    },
    {
        "flight_id": "VJ604",
        "airline": "Vietjet Air",
        "origin": "HAN",
        "dest": "DAD",
        "date": "2026-10-07",
        "dep_time": "11:20",
        "price": 2200000,
        "refundable": True,
        "seats": ["15C", "15D"],
        "baggage_rate_per_kg": 20000
    },
    {
        "flight_id": "QH118",
        "airline": "Bamboo Airways",
        "origin": "SGN",
        "dest": "DAD",
        "date": "2026-10-07",
        "dep_time": "10:15",
        "price": 1750000,
        "refundable": True,
        "seats": ["05D", "05E", "05F"],
        "baggage_rate_per_kg": 22000
    },
    {
        "flight_id": "QH224",
        "airline": "Bamboo Airways",
        "origin": "SGN",
        "dest": "DAD",
        "date": "2026-10-07",
        "dep_time": "15:30",
        "price": 1700000,
        "refundable": True,
        "seats": ["07A", "07B"],
        "baggage_rate_per_kg": 22000
    },
    {
        "flight_id": "VN214",
        "airline": "Vietnam Airlines",
        "origin": "HAN",
        "dest": "SGN",
        "date": "2026-10-08",
        "dep_time": "09:15",
        "price": 1950000,
        "refundable": True,
        "seats": ["14A", "14B"],
        "baggage_rate_per_kg": 25000
    },
    {
        "flight_id": "VJ180",
        "airline": "Vietjet Air",
        "origin": "DAD",
        "dest": "SGN",
        "date": "2026-10-10",
        "dep_time": "14:15",
        "price": 1650000,
        "refundable": True,
        "seats": ["18A", "18C"],
        "baggage_rate_per_kg": 20000
    }
]

# Runtime state
MOCK_FLIGHTS: List[Dict[str, Any]] = copy.deepcopy(INITIAL_MOCK_FLIGHTS)
MOCK_BOOKINGS: Dict[str, Dict[str, Any]] = {}


# --- Pydantic Argument Schemas for Tools ---

class SearchFlightsInput(BaseModel):
    origin: str = Field(description="Departure airport code (e.g., SGN, HAN, DAD)")
    dest: str = Field(description="Destination airport code (e.g., DAD, SGN, HAN)")
    date: str = Field(description="Departure date in YYYY-MM-DD format (e.g., 2026-10-07)")


class CheckSeatInput(BaseModel):
    flight_id: str = Field(description="Flight code identifier (e.g., VN122, QH118, VJ604)")


class CalculateBaggageInput(BaseModel):
    flight_id: str = Field(description="Flight code identifier (e.g., VN122, QH118)")
    baggage_kg: int = Field(default=0, ge=0, description="Additional checked baggage weight in kg")


class BookTicketInput(BaseModel):
    flight_id: str = Field(description="Flight code identifier to book (e.g., VN122, QH118)")
    seat_number: str = Field(description="Selected seat number (e.g., 05D, 12A)")
    passenger_name: str = Field(default="Nguyen Van A", description="Full name of the passenger")
    baggage_kg: int = Field(default=0, ge=0, description="Checked baggage weight in kg")


# --- Mock Tools Definitions ---

@tool(args_schema=SearchFlightsInput)
def search_flights(origin: str, dest: str, date: str) -> str:
    """Search available flights by origin, destination, and departure date (YYYY-MM-DD)."""
    origin_clean = origin.strip().upper()
    dest_clean = dest.strip().upper()
    date_clean = date.strip()

    matches = [
        f for f in MOCK_FLIGHTS
        if f["origin"] == origin_clean and f["dest"] == dest_clean and f["date"] == date_clean
    ]
    if not matches:
        return json.dumps({
            "status": "empty",
            "matched": 0,
            "message": f"No flights found from {origin_clean} to {dest_clean} on {date_clean}.",
            "flights": []
        }, ensure_ascii=False)

    return json.dumps({
        "status": "success",
        "matched": len(matches),
        "flights": matches
    }, ensure_ascii=False)


@tool(args_schema=CheckSeatInput)
def check_seat_availability(flight_id: str) -> str:
    """Check seat availability, base ticket fare, departure time, and refund policy for a flight."""
    fid = flight_id.strip().upper()
    flight = next((f for f in MOCK_FLIGHTS if f["flight_id"] == fid), None)
    if not flight:
        return json.dumps({
            "status": "not_found",
            "flight_id": fid,
            "message": f"Flight {fid} not found."
        }, ensure_ascii=False)

    return json.dumps({
        "status": "success",
        "flight_id": fid,
        "airline": flight["airline"],
        "available_seats": flight["seats"],
        "seat_count": len(flight["seats"]),
        "base_price": flight["price"],
        "dep_time": flight["dep_time"],
        "refundable": flight["refundable"]
    }, ensure_ascii=False)


@tool(args_schema=CalculateBaggageInput)
def calculate_baggage_fee(flight_id: str, baggage_kg: int) -> str:
    """Calculate checked baggage fee based on airline rate and weight in kg."""
    fid = flight_id.strip().upper()
    flight = next((f for f in MOCK_FLIGHTS if f["flight_id"] == fid), None)
    if not flight:
        return json.dumps({
            "status": "not_found",
            "flight_id": fid,
            "message": f"Flight {fid} not found for baggage fee calculation."
        }, ensure_ascii=False)

    if baggage_kg <= 0:
        return json.dumps({
            "status": "success",
            "flight_id": fid,
            "baggage_kg": 0,
            "baggage_fee": 0,
            "message": "No additional checked baggage requested (0 VND)."
        }, ensure_ascii=False)

    rate = flight.get("baggage_rate_per_kg", 20000)
    fee = int(baggage_kg * rate)
    return json.dumps({
        "status": "success",
        "flight_id": fid,
        "airline": flight["airline"],
        "baggage_kg": baggage_kg,
        "rate_per_kg": rate,
        "baggage_fee": fee
    }, ensure_ascii=False)


@tool(args_schema=BookTicketInput)
def book_ticket(flight_id: str, seat_number: str, passenger_name: str = "Nguyen Van A", baggage_kg: int = 0) -> str:
    """Finalize an official flight booking and deduct payment. This is a sensitive action requiring approval."""
    fid = flight_id.strip().upper()
    seat = seat_number.strip().upper()

    flight = next((f for f in MOCK_FLIGHTS if f["flight_id"] == fid), None)
    if not flight:
        return json.dumps({
            "status": "failed",
            "reason": "flight_not_found",
            "message": f"Flight {fid} not found."
        }, ensure_ascii=False)

    if seat not in flight["seats"]:
        return json.dumps({
            "status": "failed",
            "reason": "seat_unavailable",
            "message": f"Seat {seat} is unavailable on flight {fid}. Available seats: {flight['seats']}"
        }, ensure_ascii=False)

    # Calculate baggage fee
    baggage_rate = flight.get("baggage_rate_per_kg", 20000)
    baggage_fee = int(baggage_kg * baggage_rate) if baggage_kg > 0 else 0
    total_price = flight["price"] + baggage_fee

    booking_code = f"BK_{fid}_{seat}"
    booking_record = {
        "booking_code": booking_code,
        "flight_id": fid,
        "airline": flight["airline"],
        "passenger_name": passenger_name,
        "seat": seat,
        "origin": flight["origin"],
        "dest": flight["dest"],
        "date": flight["date"],
        "dep_time": flight["dep_time"],
        "ticket_price": flight["price"],
        "baggage_kg": baggage_kg,
        "baggage_fee": baggage_fee,
        "total_price": total_price,
        "refundable": flight["refundable"],
        "status": "confirmed",
        "paid": True
    }

    # Record in mock database and update seat inventory
    MOCK_BOOKINGS[booking_code] = booking_record
    flight["seats"].remove(seat)

    return json.dumps({
        "status": "success",
        "booking_code": booking_code,
        "flight_id": fid,
        "passenger_name": passenger_name,
        "seat": seat,
        "date": flight["date"],
        "dep_time": flight["dep_time"],
        "total_price": total_price,
        "paid": True,
        "message": f"Booking successful! Reference code: {booking_code}, total charged: {total_price:,.0f} VND."
    }, ensure_ascii=False)


# --- Backward compatibility aliases for existing tests ---
@tool
def check_seat(flight_id: str) -> str:
    """Backward compatibility alias for check_seat_availability."""
    return check_seat_availability.invoke({"flight_id": flight_id})


@tool
def book_seat(flight_id: str, seat_number: str) -> str:
    """Backward compatibility alias for book_ticket."""
    return book_ticket.invoke({"flight_id": flight_id, "seat_number": seat_number})


@tool
def pay(booking_code: str) -> str:
    """Backward compatibility alias: Confirm payment for a booking code."""
    if booking_code not in MOCK_BOOKINGS:
        return json.dumps({"status": "error", "message": "booking_not_found"}, ensure_ascii=False)
    MOCK_BOOKINGS[booking_code]["status"] = "confirmed"
    MOCK_BOOKINGS[booking_code]["paid"] = True
    return json.dumps({"status": "paid", "booking_code": booking_code, "paid": True}, ensure_ascii=False)


def get_booking(booking_code: str) -> str:
    """Helper query function for Harness Sensor state verification."""
    if booking_code in MOCK_BOOKINGS:
        return json.dumps({"status": "found", "data": MOCK_BOOKINGS[booking_code]}, ensure_ascii=False)
    return json.dumps({"status": "not_found"}, ensure_ascii=False)


def set_flight_seats(flight_id: str, seats: List[str]):
    """Adjust available seats for a specific flight in Mock DB."""
    for f in MOCK_FLIGHTS:
        if f["flight_id"] == flight_id:
            f["seats"] = list(seats)


def reset_mock_db():
    """Reset the Mock Database state back to initial values."""
    global MOCK_BOOKINGS
    MOCK_BOOKINGS.clear()
    MOCK_FLIGHTS.clear()
    MOCK_FLIGHTS.extend(copy.deepcopy(INITIAL_MOCK_FLIGHTS))


# Standard tools list exposed to Agents
AGENT_TOOLS = [
    search_flights,
    check_seat_availability,
    calculate_baggage_fee,
    book_ticket
]
