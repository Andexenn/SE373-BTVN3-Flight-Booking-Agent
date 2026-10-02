import json
from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from harness.constraints import BookingConstraint
from harness.permission import PermissionGuard
from harness.loop_detector import LoopDetector
from harness.completion_sensor import CompletionSensor
from harness.handoff import HandoffReport
from tools.flight_tools import AGENT_TOOLS
from config import get_model


class ReActAgent:
    """ReAct (Reasoning + Acting) Agent for automated flight search and booking."""

    def __init__(
        self,
        constraints: BookingConstraint,
        max_turns: int = 10,
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

    def _build_system_prompt(self) -> str:
        return (
            "You are a professional Flight Booking Assistant (ReAct Flight Booking Agent).\n"
            "Your objective is to help the customer search, select flights, compute baggage fees (if applicable), and finalize a valid booking.\n"
            "Standard workflow:\n"
            "1. Use 'search_flights' to find flights for the requested route and date.\n"
            "2. Analyze results: check departure time (dep_time), base fare, and refund policy.\n"
            "3. Use 'check_seat_availability' to check available seats for the preferred flight.\n"
            "4. If checked baggage is requested (> 0 kg), call 'calculate_baggage_fee' to check fees.\n"
            "5. Ensure total cost (ticket fare + baggage fee) <= maximum budget.\n"
            "6. Use 'book_ticket' to finalize the booking and receive a booking code.\n"
            "Note: If a flight is sold out or exceeds budget, reason dynamically to select an alternative flight.\n"
            "Always think carefully before deciding to invoke a tool."
        )

    def _safe_json_loads(self, text: str) -> Dict[str, Any]:
        """Safely parse JSON string into a dictionary with fallback."""
        try:
            return json.loads(text)
        except Exception:
            return {"raw_output": text}

    def run(self) -> Dict[str, Any]:
        system_msg = SystemMessage(content=self._build_system_prompt())
        user_msg = HumanMessage(
            content=f"My flight booking request is as follows:\n{self.constraints.to_natural_language()}\n"
                    "Please find and book the best matching flight for me."
        )

        messages = [system_msg, user_msg]
        history: List[Dict[str, Any]] = []
        turn = 0
        booking_code = None
        context_meta: Dict[str, Any] = {}

        while turn < self.max_turns:
            turn += 1

            # 1. LLM Reasoning
            ai_msg = self.model.invoke(messages)
            thought = ai_msg.content or "Reasoning next action..."
            messages.append(ai_msg)

            # If no tool calls were generated, the agent concludes
            if not ai_msg.tool_calls:
                history.append({
                    "turn": turn,
                    "thought": thought,
                    "action": "FINISH",
                    "args": {},
                    "obs": "No further tool call"
                })
                break

            # 2. Process each generated tool call
            for tc in ai_msg.tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                call_id = tc.get("id", f"call_{turn}")

                # --- HARNESS 1: Loop Detector ---
                loop_res = self.loop_detector.check(tool_name, tool_args, progress_metric=len(history))
                if loop_res == "LOOP":
                    report = HandoffReport(
                        status="LOOP_DETECTED",
                        current_stage=f"Turn {turn} at tool '{tool_name}'",
                        actions_taken=history,
                        failed_attempts=[f"Repeated action '{tool_name}' with identical arguments: {tool_args}"],
                        specific_question="Agent is stuck in an unproductive loop. Human intervention is required."
                    )
                    return {
                        "status": "ABORT_LOOP",
                        "report": report,
                        "turns": turn,
                        "trace": history,
                        "booking_code": booking_code
                    }

                # --- HARNESS 2: Permission Guard ---
                if self.enable_guard:
                    allowed, guard_msg = self.permission_guard.check_permission(tool_name, tool_args, context_meta)
                    if not allowed:
                        if self.interactive:
                            approved = self.permission_guard.request_approval_interactive(guard_msg)
                            if not approved:
                                report = HandoffReport(
                                    status="REJECTED_BY_USER",
                                    current_stage=f"Turn {turn} before tool '{tool_name}'",
                                    actions_taken=history,
                                    failed_attempts=[f"User rejected authorization: {guard_msg}"],
                                    specific_question="Execution safely aborted per user direction."
                                )
                                return {
                                    "status": "REJECTED_BY_USER",
                                    "report": report,
                                    "turns": turn,
                                    "trace": history,
                                    "booking_code": booking_code
                                }
                        else:
                            report = HandoffReport(
                                status="WAIT_APPROVAL",
                                current_stage=f"Turn {turn} at tool '{tool_name}'",
                                actions_taken=history,
                                failed_attempts=[],
                                specific_question=f"{guard_msg} Do you authorize this action?"
                            )
                            return {
                                "status": "WAIT_APPROVAL",
                                "report": report,
                                "turns": turn,
                                "trace": history,
                                "booking_code": booking_code
                            }

                # --- Tool Execution ---
                fn = self.tool_map.get(tool_name)
                if not fn:
                    obs_str = json.dumps({"status": "error", "message": f"Tool '{tool_name}' does not exist."})
                else:
                    try:
                        obs_str = fn.invoke(tool_args)
                    except Exception as e:
                        obs_str = json.dumps({"status": "error", "message": str(e)})

                obs = self._safe_json_loads(obs_str)

                # Update context_meta for subsequent Harness evaluation
                if tool_name == "check_seat_availability" and obs.get("status") == "success":
                    context_meta["current_price"] = obs.get("base_price", 0)
                    context_meta["refundable"] = obs.get("refundable", True)
                elif tool_name == "book_ticket" and obs.get("status") == "success":
                    booking_code = obs.get("booking_code")

                history.append({
                    "turn": turn,
                    "thought": thought,
                    "action": tool_name,
                    "args": tool_args,
                    "obs": obs
                })
                messages.append(ToolMessage(content=obs_str, tool_call_id=call_id))

            # Stop if booking succeeded
            if booking_code:
                break

        # --- HARNESS 3: Completion Sensor ---
        success, reason = CompletionSensor.verify(booking_code, self.constraints)
        if success:
            return {
                "status": "SUCCESS",
                "booking_code": booking_code,
                "turns": turn,
                "trace": history,
                "reason": reason
            }

        # If turn limit reached without completion -> Handoff
        if turn >= self.max_turns:
            report = HandoffReport(
                status="OUT_OF_BUDGET",
                current_stage=f"Reached maximum turn limit ({self.max_turns} turns)",
                actions_taken=history,
                failed_attempts=["Agent could not finalize booking within allowable turn limit."],
                specific_question="Human agent required to assist with customer request."
            )
            return {
                "status": "OUT_OF_BUDGET",
                "report": report,
                "turns": turn,
                "trace": history,
                "booking_code": booking_code
            }

        return {
            "status": "SENSOR_FAILED",
            "reason": reason,
            "turns": turn,
            "trace": history,
            "booking_code": booking_code
        }
