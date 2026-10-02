from typing import Tuple, Dict, Any, Optional


class PermissionGuard:
    """Security and authorization layer intercepting sensitive actions."""

    def __init__(self, price_limit: int = 2000000, auto_approve: bool = False):
        self.price_limit = price_limit
        self.auto_approve = auto_approve

    def check_permission(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context_meta: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str]:
        """Check if an action is permitted or requires human authorization."""
        context_meta = context_meta or {}

        # If in auto_approve mode (for automated benchmarks), permit immediately
        if self.auto_approve:
            return True, "AUTO_APPROVED"

        # 1. Direct financial payment action
        if tool_name == "pay":
            return False, "Financial payment action (pay) is sensitive and strictly requires human approval."

        # 2. Final booking action (book_ticket or book_seat)
        if tool_name in ["book_ticket", "book_seat"]:
            current_price = context_meta.get("current_price", 0)
            refundable = context_meta.get("refundable", True)

            # Warning 1: Non-refundable ticket
            if not refundable:
                return (
                    False,
                    f"WARNING: Flight '{args.get('flight_id')}' is NON-REFUNDABLE. Explicit human confirmation required."
                )

            # Warning 2: Price exceeds budget ceiling
            if current_price > self.price_limit:
                return (
                    False,
                    f"WARNING: Estimated total cost ({current_price:,.0f} VND) exceeds budget ceiling ({self.price_limit:,.0f} VND)."
                )

            # Warning 3: Financial commitment
            return (
                False,
                f"BOOKING CONFIRMATION: Preparing to finalize flight {args.get('flight_id')} (Seat {args.get('seat_number')}) for passenger {args.get('passenger_name', 'passenger')}."
            )

        return True, "APPROVED"

    def request_approval_interactive(self, question: str) -> bool:
        """Prompt user interactively via CLI terminal for authorization."""
        if self.auto_approve:
            return True
        try:
            choice = input(f"\n[PERMISSION GUARD]: {question}\nDo you authorize this execution? (y/n): ").strip().lower()
            return choice in ["y", "yes", "ok"]
        except (EOFError, KeyboardInterrupt):
            return False
