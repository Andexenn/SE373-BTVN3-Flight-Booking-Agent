from typing import Optional
from pydantic import BaseModel, Field


class BookingConstraint(BaseModel):
    """Input constraints and requirements model for the flight booking process."""
    origin: str = Field(default="SGN", description="Origin airport IATA code (e.g., SGN, HAN)")
    dest: str = Field(default="DAD", description="Destination airport IATA code (e.g., DAD, SGN)")
    date: str = Field(default="2026-10-07", description="Departure date YYYY-MM-DD")
    max_price: int = Field(default=2000000, description="Maximum budget in VND")
    depart_before: str = Field(default="12:00", description="Latest acceptable departure time (HH:MM)")
    passenger_name: str = Field(default="Nguyen Van A", description="Passenger full name")
    baggage_kg: int = Field(default=0, ge=0, description="Checked baggage allowance in kg")
    require_refundable: bool = Field(default=False, description="Whether a refundable ticket is required")

    def to_natural_language(self) -> str:
        """Convert constraints to natural language description for LLM prompts."""
        details = [
            f"Departure Airport: {self.origin}",
            f"Destination Airport: {self.dest}",
            f"Departure Date: {self.date}",
            f"Departure Time: before {self.depart_before}",
            f"Maximum Budget: {self.max_price:,.0f} VND",
            f"Passenger Name: {self.passenger_name}",
        ]
        if self.baggage_kg > 0:
            details.append(f"Checked Baggage: {self.baggage_kg} kg")
        if self.require_refundable:
            details.append("Policy Requirement: Refundable ticket required")
        return "\n".join(details)
