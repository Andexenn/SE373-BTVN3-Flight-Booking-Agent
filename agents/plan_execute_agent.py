import json
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from harness.constraints import BookingConstraint
from harness.permission import PermissionGuard
from harness.loop_detector import LoopDetector
from harness.completion_sensor import CompletionSensor
from harness.handoff import HandoffReport
from tools.flight_tools import AGENT_TOOLS
from config import get_model


class PlanStep(BaseModel):
    step_id: int = Field(description="Step sequence number")
    tool_name: str = Field(description="Name of the tool to invoke")
    purpose: str = Field(description="Objective of this step")


class ExecutionPlan(BaseModel):
    plan_summary: str = Field(description="High-level plan summary")
    steps: List[PlanStep] = Field(description="Sequential list of execution steps")


class PlanThenExecuteAgent:
    """Plan-then-Execute Agent with dynamic Re-planning and safety harness integration."""

    def __init__(
        self,
        constraints: BookingConstraint,
        max_replan: int = 3,
        enable_guard: bool = True,
        auto_approve: bool = False,
        interactive: bool = False
    ):
        self.constraints = constraints
        self.max_replan = max_replan
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

        self.planner_model = get_model(temperature=0.0)
        self.executor_model = get_model(temperature=0.0).bind_tools(self.tools)

    def _extract_json_block(self, text: str) -> str:
        """Strip markdown code fence blocks if present."""
        cleaned = text.strip()
        if "```json" in cleaned:
            return cleaned.split("```json")[1].split("```")[0].strip()
        if "```" in cleaned:
            return cleaned.split("```")[1].split("```")[0].strip()
        return cleaned

    def _generate_initial_plan(self) -> ExecutionPlan:
        """Generate initial sequential execution plan via LLM."""
        planner_prompt = (
            "You are Flight Planner AI. Generate a sequential execution plan to book a flight.\n"
            "Available tools:\n"
            "- search_flights: search flights by origin, destination, and date.\n"
            "- check_seat_availability: check seat availability and base fare.\n"
            "- calculate_baggage_fee: calculate baggage fee if customer requires luggage.\n"
            "- book_ticket: finalize booking and obtain booking code.\n\n"
            f"Customer constraints:\n{self.constraints.to_natural_language()}\n\n"
            "Return a valid JSON plan matching this schema:\n"
            "{\n"
            '  "plan_summary": "Summary of plan...",\n'
            '  "steps": [\n'
            '    {"step_id": 1, "tool_name": "search_flights", "purpose": "..."},\n'
            '    {"step_id": 2, "tool_name": "check_seat_availability", "purpose": "..."}\n'
            "  ]\n"
            "}\n"
            "Return only pure JSON without markdown explanation."
        )

        resp = self.planner_model.invoke([HumanMessage(content=planner_prompt)])
        cleaned = self._extract_json_block(resp.content)

        try:
            plan_data = json.loads(cleaned)
            return ExecutionPlan(**plan_data)
        except Exception:
            # Fallback plan if model JSON generation is malformed
            steps = [
                PlanStep(step_id=1, tool_name="search_flights", purpose=f"Search flights {self.constraints.origin}->{self.constraints.dest}"),
                PlanStep(step_id=2, tool_name="check_seat_availability", purpose="Check available seats for best flight"),
            ]
            if self.constraints.baggage_kg > 0:
                steps.append(PlanStep(step_id=3, tool_name="calculate_baggage_fee", purpose="Calculate baggage fee"))
            steps.append(PlanStep(step_id=len(steps) + 1, tool_name="book_ticket", purpose="Confirm booking"))
            return ExecutionPlan(plan_summary="Sequential flight booking plan", steps=steps)

    def _replan(self, current_trace: List[Dict[str, Any]], failed_reason: str) -> ExecutionPlan:
        """Invoke LLM Re-planner to adapt the plan after an obstacle."""
        replan_prompt = (
            "You are Flight Re-Planner AI. The previous plan encountered an issue:\n"
            f"Reason: {failed_reason}\n"
            f"Previous execution history:\n{json.dumps(current_trace, ensure_ascii=False, indent=2)}\n\n"
            f"Original constraints:\n{self.constraints.to_natural_language()}\n\n"
            "Propose a revised plan for remaining steps to achieve the goal (e.g., check an alternate flight with open seats).\n"
            "Return JSON in the exact same format as the initial plan (plan_summary and steps list)."
        )
        resp = self.planner_model.invoke([HumanMessage(content=replan_prompt)])
        cleaned = self._extract_json_block(resp.content)

        try:
            plan_data = json.loads(cleaned)
            return ExecutionPlan(**plan_data)
        except Exception:
            return ExecutionPlan(
                plan_summary="Adaptive plan: Switch to alternate flight",
                steps=[
                    PlanStep(step_id=1, tool_name="check_seat_availability", purpose="Check backup flight availability"),
                    PlanStep(step_id=2, tool_name="calculate_baggage_fee", purpose="Calculate baggage fee for backup flight"),
                    PlanStep(step_id=3, tool_name="book_ticket", purpose="Confirm backup flight booking")
                ]
            )

    def run(self) -> Dict[str, Any]:
        trace: List[Dict[str, Any]] = []
        booking_code = None
        replan_count = 0
        total_turns = 0
        context_meta: Dict[str, Any] = {}

        # 1. Generate initial plan
        current_plan = self._generate_initial_plan()

        while replan_count <= self.max_replan:
            step_idx = 0
            while step_idx < len(current_plan.steps):
                step = current_plan.steps[step_idx]
                total_turns += 1

                # Executor: Prompt LLM to determine tool arguments based on trace
                exec_prompt = (
                    "You are Step Executor AI.\n"
                    f"Customer constraints:\n{self.constraints.to_natural_language()}\n"
                    f"Current step to execute: [{step.tool_name}] - {step.purpose}\n"
                    f"Execution history and observed results:\n{json.dumps(trace, ensure_ascii=False, indent=2)}\n\n"
                    f"Invoke tool '{step.tool_name}' with the most accurate arguments based on observed results."
                )

                exec_resp = self.executor_model.invoke([HumanMessage(content=exec_prompt)])

                if not exec_resp.tool_calls:
                    # Fallback arguments if LLM did not generate tool calls
                    if step.tool_name == "search_flights":
                        tool_args = {"origin": self.constraints.origin, "dest": self.constraints.dest, "date": self.constraints.date}
                    elif step.tool_name == "calculate_baggage_fee":
                        tool_args = {"flight_id": context_meta.get("flight_id", "QH118"), "baggage_kg": self.constraints.baggage_kg}
                    else:
                        tool_args = {}
                else:
                    tc = exec_resp.tool_calls[0]
                    tool_args = tc["args"]

                # --- HARNESS 1: Loop Detector ---
                loop_res = self.loop_detector.check(step.tool_name, tool_args, progress_metric=len(trace))
                if loop_res == "LOOP":
                    report = HandoffReport(
                        status="LOOP_DETECTED",
                        current_stage=f"Step '{step.tool_name}' in plan",
                        actions_taken=trace,
                        failed_attempts=[f"Repeated tool '{step.tool_name}' with arguments: {tool_args}"],
                        specific_question="Agent is repeating this step. Escalating to human agent."
                    )
                    return {
                        "status": "ABORT_LOOP",
                        "report": report,
                        "turns": total_turns,
                        "trace": trace,
                        "booking_code": booking_code
                    }

                # --- HARNESS 2: Permission Guard ---
                if self.enable_guard:
                    allowed, guard_msg = self.permission_guard.check_permission(step.tool_name, tool_args, context_meta)
                    if not allowed:
                        if self.interactive:
                            approved = self.permission_guard.request_approval_interactive(guard_msg)
                            if not approved:
                                report = HandoffReport(
                                    status="REJECTED_BY_USER",
                                    current_stage=f"At step '{step.tool_name}'",
                                    actions_taken=trace,
                                    failed_attempts=[f"User rejected authorization: {guard_msg}"],
                                    specific_question="Operation safely halted per user instruction."
                                )
                                return {
                                    "status": "REJECTED_BY_USER",
                                    "report": report,
                                    "turns": total_turns,
                                    "trace": trace,
                                    "booking_code": booking_code
                                }
                        else:
                            report = HandoffReport(
                                status="WAIT_APPROVAL",
                                current_stage=f"At sensitive step '{step.tool_name}'",
                                actions_taken=trace,
                                failed_attempts=[],
                                specific_question=f"{guard_msg} Do you authorize this action?"
                            )
                            return {
                                "status": "WAIT_APPROVAL",
                                "report": report,
                                "turns": total_turns,
                                "trace": trace,
                                "booking_code": booking_code
                            }

                # Tool Execution
                tool_fn = self.tool_map.get(step.tool_name)
                if not tool_fn:
                    obs = {"status": "error", "message": f"Tool '{step.tool_name}' not found"}
                else:
                    try:
                        raw_obs = tool_fn.invoke(tool_args)
                        obs = json.loads(raw_obs)
                    except Exception as e:
                        obs = {"status": "error", "message": str(e)}

                step_record = {
                    "step_id": step.step_id,
                    "tool": step.tool_name,
                    "args": tool_args,
                    "obs": obs
                }
                trace.append(step_record)

                # Update context_meta
                if step.tool_name == "check_seat_availability" and obs.get("status") == "success":
                    context_meta["flight_id"] = obs.get("flight_id")
                    context_meta["current_price"] = obs.get("base_price", 0)
                    context_meta["refundable"] = obs.get("refundable", True)
                elif step.tool_name == "book_ticket" and obs.get("status") == "success":
                    booking_code = obs.get("booking_code")

                # Check if step failed or encountered obstacle to trigger Re-planner
                needs_replan = False
                fail_reason = ""
                if obs.get("status") in ["failed", "not_found", "empty", "error"]:
                    needs_replan = True
                    fail_reason = f"Tool {step.tool_name} returned failure status: {obs.get('message') or obs.get('reason')}"
                elif step.tool_name == "check_seat_availability" and not obs.get("available_seats"):
                    needs_replan = True
                    fail_reason = f"Flight {obs.get('flight_id')} is sold out."
                elif step.tool_name == "check_seat_availability" and obs.get("base_price", 0) > self.constraints.max_price:
                    needs_replan = True
                    fail_reason = f"Base fare ({obs.get('base_price'):,.0f} VND) exceeds budget ceiling ({self.constraints.max_price:,.0f} VND)."

                if needs_replan:
                    replan_count += 1
                    if replan_count > self.max_replan:
                        report = HandoffReport(
                            status="PLAN_BROKEN",
                            current_stage=f"At step '{step.tool_name}'",
                            actions_taken=trace,
                            failed_attempts=[fail_reason],
                            specific_question="Plan broken repeatedly due to environmental changes. Escalating to human agent."
                        )
                        return {
                            "status": "PLAN_BROKEN",
                            "report": report,
                            "turns": total_turns,
                            "trace": trace,
                            "booking_code": booking_code
                        }

                    # Re-plan execution
                    current_plan = self._replan(trace, fail_reason)
                    break

                step_idx += 1

            if booking_code:
                break

        # --- HARNESS 3: Completion Sensor ---
        success, reason = CompletionSensor.verify(booking_code, self.constraints)
        return {
            "status": "SUCCESS" if success else "SENSOR_FAILED",
            "reason": reason,
            "booking_code": booking_code,
            "turns": total_turns,
            "trace": trace
        }
