import json
from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from harness.constraints import BookingConstraint
from harness.permission import PermissionGuard
from harness.loop_detector import LoopDetector
from harness.completion_sensor import CompletionSensor
from harness.handoff import HandoffReport
from tools.flight_tools import AGENT_TOOLS
from config import get_model


class HybridAgent:
    """Hybrid Agent coordinating high-level milestones with ReAct Sub-agents."""

    def __init__(
        self,
        constraints: BookingConstraint,
        max_turns: int = 12,
        enable_guard: bool = True,
        auto_approve: bool = False,
        interactive: bool = False
    ):
        self.constraints = constraints
        self.max_turns = max_turns
        self.enable_guard = enable_guard
        self.auto_approve = auto_approve
        self.interactive = interactive

        self.permission_guard = PermissionGuard(
            price_limit=constraints.max_price,
            auto_approve=auto_approve
        )
        self.loop_detector = LoopDetector(repeat_k=2)

        self.tools = AGENT_TOOLS
        self.tool_map = {t.name: t for t in self.tools}

        base_model = get_model(temperature=0.0)
        self.model = base_model.bind_tools(self.tools)

    def _run_sub_goal(
        self,
        sub_goal_name: str,
        goal_instructions: str,
        shared_state: Dict[str, Any],
        history: List[Dict[str, Any]],
        current_turns: int
    ) -> Dict[str, Any]:
        """Execute a milestone using a localized ReAct sub-agent."""
        prompt = (
            f"You are Sub-Agent responsible for stage: [{sub_goal_name}].\n"
            f"Original constraints:\n{self.constraints.to_natural_language()}\n\n"
            f"State gathered from previous stages:\n{json.dumps(shared_state, ensure_ascii=False, indent=2)}\n\n"
            f"Specific stage task: {goal_instructions}\n"
            "Reason and invoke necessary tools to accomplish this stage."
        )

        messages = [
            SystemMessage(content="You are an autonomous ReAct Sub-Agent responsible for completely resolving this stage's objective."),
            HumanMessage(content=prompt)
        ]

        sub_turns = 0
        while sub_turns < 4 and current_turns + sub_turns < self.max_turns:
            sub_turns += 1
            ai_msg = self.model.invoke(messages)
            messages.append(ai_msg)

            if not ai_msg.tool_calls:
                break

            for tc in ai_msg.tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                call_id = tc.get("id", f"call_sub_{sub_turns}")

                # Harness 1: Loop Detector
                loop_res = self.loop_detector.check(tool_name, tool_args, progress_metric=len(history))
                if loop_res == "LOOP":
                    return {"status": "LOOP", "turns": sub_turns, "tool": tool_name, "args": tool_args}

                # Harness 2: Permission Guard
                if self.enable_guard:
                    allowed, guard_msg = self.permission_guard.check_permission(tool_name, tool_args, shared_state)
                    if not allowed:
                        if self.interactive:
                            approved = self.permission_guard.request_approval_interactive(guard_msg)
                            if not approved:
                                return {"status": "REJECTED_BY_USER", "turns": sub_turns, "guard_msg": guard_msg}
                        else:
                            return {"status": "WAIT_APPROVAL", "turns": sub_turns, "guard_msg": guard_msg}

                # Execute tool
                fn = self.tool_map.get(tool_name)
                try:
                    obs_str = fn.invoke(tool_args)
                    obs = json.loads(obs_str)
                except Exception as e:
                    obs_str = json.dumps({"status": "error", "message": str(e)})
                    obs = {"status": "error", "message": str(e)}

                # Record shared state
                if tool_name == "search_flights" and obs.get("status") == "success":
                    shared_state["found_flights"] = obs.get("flights", [])
                elif tool_name == "check_seat_availability" and obs.get("status") == "success":
                    shared_state["selected_flight_id"] = obs.get("flight_id")
                    shared_state["current_price"] = obs.get("base_price", 0)
                    shared_state["refundable"] = obs.get("refundable", True)
                    shared_state["available_seats"] = obs.get("available_seats", [])
                elif tool_name == "calculate_baggage_fee" and obs.get("status") == "success":
                    shared_state["baggage_fee"] = obs.get("baggage_fee", 0)
                elif tool_name == "book_ticket" and obs.get("status") == "success":
                    shared_state["booking_code"] = obs.get("booking_code")

                history.append({
                    "sub_goal": sub_goal_name,
                    "thought": ai_msg.content,
                    "action": tool_name,
                    "args": tool_args,
                    "obs": obs
                })
                messages.append(ToolMessage(content=obs_str, tool_call_id=call_id))

        return {"status": "DONE", "turns": sub_turns}

    def run(self) -> Dict[str, Any]:
        trace: List[Dict[str, Any]] = []
        shared_state: Dict[str, Any] = {}
        total_turns = 0

        # High-level strategic milestones
        milestones = [
            {
                "name": "Stage 1: Search & Discover Flights",
                "instructions": (
                    f"Invoke tool 'search_flights' to find all flights from {self.constraints.origin} "
                    f"to {self.constraints.dest} on {self.constraints.date}."
                )
            },
            {
                "name": "Stage 2: Verify Seat Availability & Baggage",
                "instructions": (
                    "Select the most suitable flight meeting departure time and budget. "
                    "Invoke 'check_seat_availability' to check open seats. "
                    + (f"Then invoke 'calculate_baggage_fee' for {self.constraints.baggage_kg} kg luggage."
                       if self.constraints.baggage_kg > 0 else "")
                )
            },
            {
                "name": "Stage 3: Finalize Booking & Issue Reference",
                "instructions": (
                    f"Invoke tool 'book_ticket' to book for passenger {self.constraints.passenger_name} "
                    "with verified seat and baggage."
                )
            }
        ]

        for m in milestones:
            res = self._run_sub_goal(
                sub_goal_name=m["name"],
                goal_instructions=m["instructions"],
                shared_state=shared_state,
                history=trace,
                current_turns=total_turns
            )
            total_turns += res.get("turns", 1)

            if res.get("status") == "LOOP":
                report = HandoffReport(
                    status="LOOP_DETECTED",
                    current_stage=m["name"],
                    actions_taken=trace,
                    failed_attempts=[f"Repeated tool '{res.get('tool')}' with arguments: {res.get('args')}"],
                    specific_question="ReAct Sub-agent detected an infinite loop. Escalating to human agent."
                )
                return {"status": "ABORT_LOOP", "report": report, "turns": total_turns, "trace": trace}

            if res.get("status") == "WAIT_APPROVAL":
                report = HandoffReport(
                    status="WAIT_APPROVAL",
                    current_stage=m["name"],
                    actions_taken=trace,
                    failed_attempts=[],
                    specific_question=f"{res.get('guard_msg')} Do you authorize execution?"
                )
                return {"status": "WAIT_APPROVAL", "report": report, "turns": total_turns, "trace": trace}

            if res.get("status") == "REJECTED_BY_USER":
                report = HandoffReport(
                    status="REJECTED_BY_USER",
                    current_stage=m["name"],
                    actions_taken=trace,
                    failed_attempts=["User rejected authorization."],
                    specific_question="Booking safely aborted per user direction."
                )
                return {"status": "REJECTED_BY_USER", "report": report, "turns": total_turns, "trace": trace}

            if total_turns >= self.max_turns:
                report = HandoffReport(
                    status="OUT_OF_BUDGET",
                    current_stage=f"Reached maximum turn limit ({self.max_turns} turns)",
                    actions_taken=trace,
                    failed_attempts=["Turn limit exceeded before task completion."],
                    specific_question="Human intervention required to complete booking."
                )
                return {"status": "OUT_OF_BUDGET", "report": report, "turns": total_turns, "trace": trace}

        booking_code = shared_state.get("booking_code")
        success, reason = CompletionSensor.verify(booking_code, self.constraints)
        return {
            "status": "SUCCESS" if success else "SENSOR_FAILED",
            "booking_code": booking_code,
            "turns": total_turns,
            "trace": trace,
            "reason": reason
        }
