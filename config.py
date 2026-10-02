import os
import sys
import json
import re
from pathlib import Path
from typing import List, Optional, Any
from dotenv import load_dotenv

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, ToolMessage, SystemMessage
from langchain_core.outputs import ChatResult, ChatGeneration

# Load .env file from project root
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)


class MockReasoningModel(BaseChatModel):
    """Deterministic offline reasoning model for testing and benchmarking all 3 agent architectures."""

    def bind_tools(self, tools: Any, **kwargs: Any):
        return self

    @property
    def _llm_type(self) -> str:
        return "mock-reasoning-llm"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any
    ) -> ChatResult:
        text_content = ""
        for m in messages:
            if isinstance(m, (HumanMessage, ToolMessage, SystemMessage)):
                text_content += "\n" + str(m.content)

        # Dynamically extract constraints from prompt context
        passenger_match = re.search(r"Passenger Name:\s*([^\n\r]+)", text_content, re.IGNORECASE)
        if not passenger_match:
            passenger_match = re.search(r"passenger\s+([A-Z][a-zA-Z\s]+)", text_content)
        extracted_passenger = passenger_match.group(1).strip() if passenger_match else "Nguyen Van A"

        baggage_match = re.search(r"Checked Baggage:\s*(\d+)", text_content, re.IGNORECASE)
        extracted_baggage = int(baggage_match.group(1)) if baggage_match else (15 if "15" in text_content else 0)

        origin_match = re.search(r"Departure Airport:\s*([A-Za-z]{3})", text_content, re.IGNORECASE)
        extracted_origin = origin_match.group(1).upper() if origin_match else "SGN"

        dest_match = re.search(r"Destination Airport:\s*([A-Za-z]{3})", text_content, re.IGNORECASE)
        extracted_dest = dest_match.group(1).upper() if dest_match else "DAD"

        date_match = re.search(r"Departure Date:\s*([\d-]+)", text_content, re.IGNORECASE)
        extracted_date = date_match.group(1).strip() if date_match else "2026-10-07"

        # -------------------------------------------------------------
        # BRANCH 1: Plan-then-Execute Agent (Planner & Re-Planner)
        # -------------------------------------------------------------
        if "Flight Planner AI" in text_content or ("plan" in text_content.lower() and "step executor" not in text_content.lower()):
            if "Re-Planner" in text_content or "issue" in text_content.lower() or "obstacle" in text_content.lower() or "broken" in text_content.lower():
                plan_json = json.dumps({
                    "plan_summary": "Adaptive plan: Switch to backup flight VN122",
                    "steps": [
                        {"step_id": 1, "tool_name": "check_seat_availability", "purpose": "Check backup flight availability for VN122"},
                        {"step_id": 2, "tool_name": "calculate_baggage_fee", "purpose": "Calculate checked baggage fee for VN122"},
                        {"step_id": 3, "tool_name": "book_ticket", "purpose": "Confirm booking for flight VN122"}
                    ]
                }, ensure_ascii=False)
            else:
                plan_json = json.dumps({
                    "plan_summary": f"Sequential flight booking plan for {extracted_origin} -> {extracted_dest}",
                    "steps": [
                        {"step_id": 1, "tool_name": "search_flights", "purpose": "Search available flights by route and date"},
                        {"step_id": 2, "tool_name": "check_seat_availability", "purpose": "Verify seat availability and fare"},
                        {"step_id": 3, "tool_name": "calculate_baggage_fee", "purpose": "Calculate checked baggage fee"},
                        {"step_id": 4, "tool_name": "book_ticket", "purpose": "Finalize booking and obtain booking reference code"}
                    ]
                }, ensure_ascii=False)
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=plan_json))])

        # -------------------------------------------------------------
        # BRANCH 2: Plan-then-Execute Agent (Step Executor)
        # -------------------------------------------------------------
        if "Step Executor AI" in text_content:
            target_match = re.search(r"Current step to execute: \[(\w+)\]", text_content, re.IGNORECASE)
            target_tool = target_match.group(1) if target_match else "search_flights"

            qh118_sold_out = ('"flight_id": "QH118"' in text_content and '"available_seats": []' in text_content)
            current_fid = "VN122" if qh118_sold_out else "QH118"
            current_seat = "12A" if current_fid == "VN122" else "05D"

            if target_tool == "search_flights":
                thought = "Executing flight search according to plan."
                tool_calls = [{
                    "name": "search_flights",
                    "args": {"origin": extracted_origin, "dest": extracted_dest, "date": extracted_date},
                    "id": "exec_search",
                    "type": "tool_call"
                }]
            elif target_tool == "check_seat_availability":
                thought = f"Checking available seats for flight {current_fid} as assigned."
                tool_calls = [{
                    "name": "check_seat_availability",
                    "args": {"flight_id": current_fid},
                    "id": f"exec_seat_{current_fid}",
                    "type": "tool_call"
                }]
            elif target_tool == "calculate_baggage_fee":
                thought = f"Calculating baggage fee for {extracted_baggage}kg on flight {current_fid}."
                tool_calls = [{
                    "name": "calculate_baggage_fee",
                    "args": {"flight_id": current_fid, "baggage_kg": extracted_baggage},
                    "id": f"exec_baggage_{current_fid}",
                    "type": "tool_call"
                }]
            elif target_tool == "book_ticket":
                thought = f"Proceeding to finalize booking for flight {current_fid}, seat {current_seat} for {extracted_passenger}."
                tool_calls = [{
                    "name": "book_ticket",
                    "args": {
                        "flight_id": current_fid,
                        "seat_number": current_seat,
                        "passenger_name": extracted_passenger,
                        "baggage_kg": extracted_baggage
                    },
                    "id": f"exec_book_{current_fid}",
                    "type": "tool_call"
                }]
            else:
                thought = "Completed planned step."
                tool_calls = []

            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=thought, tool_calls=tool_calls))])

        # -------------------------------------------------------------
        # BRANCH 3: Hybrid Agent (Micro ReAct Sub-Agents per Milestone)
        # -------------------------------------------------------------
        if "Sub-Agent" in text_content:
            called_in_sub = []
            for m in messages:
                if isinstance(m, AIMessage) and m.tool_calls:
                    for tc in m.tool_calls:
                        called_in_sub.append(tc["name"])

            qh118_sold_out = ('"flight_id": "QH118"' in text_content and '"available_seats": []' in text_content)
            current_fid = "VN122" if qh118_sold_out else "QH118"
            current_seat = "12A" if current_fid == "VN122" else "05D"

            if "Stage 1" in text_content:
                if "search_flights" not in called_in_sub:
                    return ChatResult(generations=[ChatGeneration(message=AIMessage(
                        content=f"Discovering flights {extracted_origin} -> {extracted_dest}.",
                        tool_calls=[{
                            "name": "search_flights",
                            "args": {"origin": extracted_origin, "dest": extracted_dest, "date": extracted_date},
                            "id": "hybrid_c1_search",
                            "type": "tool_call"
                        }]
                    ))])
                return ChatResult(generations=[ChatGeneration(message=AIMessage(
                    content="Available flights found. Stage 1 completed.",
                    tool_calls=[]
                ))])

            elif "Stage 2" in text_content:
                if "check_seat_availability" not in called_in_sub:
                    return ChatResult(generations=[ChatGeneration(message=AIMessage(
                        content=f"Checking available seats for preferred flight {current_fid}.",
                        tool_calls=[{
                            "name": "check_seat_availability",
                            "args": {"flight_id": current_fid},
                            "id": f"hybrid_c2_seat_{current_fid}",
                            "type": "tool_call"
                        }]
                    ))])
                # If sold out, check backup flight
                if qh118_sold_out and current_fid == "QH118":
                    return ChatResult(generations=[ChatGeneration(message=AIMessage(
                        content="Flight QH118 is sold out, checking backup flight VN122.",
                        tool_calls=[{
                            "name": "check_seat_availability",
                            "args": {"flight_id": "VN122"},
                            "id": "hybrid_c2_seat_VN122",
                            "type": "tool_call"
                        }]
                    ))])
                if "calculate_baggage_fee" not in called_in_sub and extracted_baggage > 0:
                    return ChatResult(generations=[ChatGeneration(message=AIMessage(
                        content=f"Calculating baggage fee for {extracted_baggage}kg on flight {current_fid}.",
                        tool_calls=[{
                            "name": "calculate_baggage_fee",
                            "args": {"flight_id": current_fid, "baggage_kg": extracted_baggage},
                            "id": f"hybrid_c2_baggage_{current_fid}",
                            "type": "tool_call"
                        }]
                    ))])
                return ChatResult(generations=[ChatGeneration(message=AIMessage(
                    content="Seats and baggage fees verified. Stage 2 completed.",
                    tool_calls=[]
                ))])

            elif "Stage 3" in text_content:
                if "book_ticket" not in called_in_sub:
                    return ChatResult(generations=[ChatGeneration(message=AIMessage(
                        content=f"Finalizing booking for flight {current_fid}, seat {current_seat} for {extracted_passenger}.",
                        tool_calls=[{
                            "name": "book_ticket",
                            "args": {
                                "flight_id": current_fid,
                                "seat_number": current_seat,
                                "passenger_name": extracted_passenger,
                                "baggage_kg": extracted_baggage
                            },
                            "id": f"hybrid_c3_book_{current_fid}",
                            "type": "tool_call"
                        }]
                    ))])
                return ChatResult(generations=[ChatGeneration(message=AIMessage(
                    content="Flight booked successfully!",
                    tool_calls=[]
                ))])

        # -------------------------------------------------------------
        # BRANCH 4: ReAct Agent (Standard Thought-Action-Observation Loop)
        # -------------------------------------------------------------
        tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
        called_tools = []
        for m in messages:
            if isinstance(m, AIMessage) and m.tool_calls:
                for tc in m.tool_calls:
                    called_tools.append(tc["name"])

        checked_flight_id = None
        available_seats = []
        baggage_calculated = False
        booked_ticket = False

        for tm in tool_messages:
            try:
                data = json.loads(tm.content)
                if "available_seats" in data:
                    checked_flight_id = data.get("flight_id")
                    available_seats = data.get("available_seats", [])
                if "baggage_fee" in data:
                    baggage_calculated = True
                if "booking_code" in data:
                    booked_ticket = True
            except Exception:
                pass

        # Step 1: Not yet searched -> search_flights
        if "search_flights" not in called_tools:
            thought = f"I need to search for available flights from {extracted_origin} to {extracted_dest} on {extracted_date}."
            tool_calls = [{
                "name": "search_flights",
                "args": {"origin": extracted_origin, "dest": extracted_dest, "date": extracted_date},
                "id": "react_search_1",
                "type": "tool_call"
            }]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=thought, tool_calls=tool_calls))])

        # Step 2: Not yet checked seats -> check_seat_availability for QH118
        if not checked_flight_id:
            target = "QH118"
            thought = f"Flight {target} departs in the morning with a favorable fare. Checking seat availability."
            tool_calls = [{
                "name": "check_seat_availability",
                "args": {"flight_id": target},
                "id": "react_seat_1",
                "type": "tool_call"
            }]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=thought, tool_calls=tool_calls))])

        # Step 3: If no available seats -> switch to backup VN122 (Dynamic Fault Recovery)
        if not available_seats:
            alt_target = "VN122" if checked_flight_id == "QH118" else "VJ604"
            thought = f"Flight {checked_flight_id} is currently sold out. Switching to check backup flight {alt_target}."
            tool_calls = [{
                "name": "check_seat_availability",
                "args": {"flight_id": alt_target},
                "id": f"react_seat_alt_{alt_target}",
                "type": "tool_call"
            }]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=thought, tool_calls=tool_calls))])

        # Step 4: Seats available, compute baggage fee if requested
        if "calculate_baggage_fee" not in called_tools and extracted_baggage > 0:
            thought = f"Flight {checked_flight_id} has available seats {available_seats}. Passenger requests {extracted_baggage}kg baggage, calculating fee."
            tool_calls = [{
                "name": "calculate_baggage_fee",
                "args": {"flight_id": checked_flight_id, "baggage_kg": extracted_baggage},
                "id": "react_baggage_1",
                "type": "tool_call"
            }]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=thought, tool_calls=tool_calls))])

        # Step 5: Finalize booking via book_ticket
        if not booked_ticket:
            seat_to_book = available_seats[0] if available_seats else "05D"
            thought = (
                f"All constraints satisfied: Flight {checked_flight_id}, seat {seat_to_book}, passenger {extracted_passenger}. "
                "Proceeding to finalize booking."
            )
            tool_calls = [{
                "name": "book_ticket",
                "args": {
                    "flight_id": checked_flight_id,
                    "seat_number": seat_to_book,
                    "passenger_name": extracted_passenger,
                    "baggage_kg": extracted_baggage
                },
                "id": "react_book_1",
                "type": "tool_call"
            }]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=thought, tool_calls=tool_calls))])

        # Step 6: Conclude
        thought = "Flight has been successfully booked and confirmed in the system. Task complete!"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=thought, tool_calls=[]))])


class OpenAICompatibleChatModel(BaseChatModel):
    """Chat model wrapper for OpenAI-compatible endpoints (e.g., OpenRouter, OpenAI) with tool binding."""
    model_name: str = "openai/gpt-4o-mini"
    api_key: str = ""
    base_url: str = "https://openrouter.ai/api/v1"
    temperature: float = 0.0
    bound_tools: List[Any] = []

    def bind_tools(self, tools: Any, **kwargs: Any):
        return OpenAICompatibleChatModel(
            model_name=self.model_name,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=self.temperature,
            bound_tools=list(tools)
        )

    @property
    def _llm_type(self) -> str:
        return "openai-compatible"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any
    ) -> ChatResult:
        from openai import OpenAI
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)

        formatted_messages = []
        for m in messages:
            if isinstance(m, SystemMessage):
                formatted_messages.append({"role": "system", "content": str(m.content)})
            elif isinstance(m, HumanMessage):
                formatted_messages.append({"role": "user", "content": str(m.content)})
            elif isinstance(m, ToolMessage):
                formatted_messages.append({
                    "role": "tool",
                    "content": str(m.content),
                    "tool_call_id": getattr(m, "tool_call_id", "call_id")
                })
            elif isinstance(m, AIMessage):
                msg_dict: Dict[str, Any] = {"role": "assistant", "content": m.content or ""}
                if m.tool_calls:
                    msg_dict["tool_calls"] = [
                        {
                            "id": tc.get("id", f"call_{i}"),
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc.get("args", {}))
                            }
                        }
                        for i, tc in enumerate(m.tool_calls)
                    ]
                formatted_messages.append(msg_dict)

        formatted_tools = None
        if self.bound_tools:
            formatted_tools = []
            for t in self.bound_tools:
                schema = t.args_schema.model_json_schema() if hasattr(t, "args_schema") and t.args_schema else {"type": "object", "properties": {}}
                formatted_tools.append({
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": {
                            "type": "object",
                            "properties": schema.get("properties", {}),
                            "required": schema.get("required", [])
                        }
                    }
                })

        call_kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": formatted_messages,
            "temperature": self.temperature
        }
        if formatted_tools:
            call_kwargs["tools"] = formatted_tools

        resp = client.chat.completions.create(**call_kwargs)
        choice = resp.choices[0].message

        tool_calls = []
        if choice.tool_calls:
            for tc in choice.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}
                tool_calls.append({
                    "name": tc.function.name,
                    "args": args,
                    "id": tc.id,
                    "type": "tool_call"
                })

        ai_msg = AIMessage(content=choice.content or "", tool_calls=tool_calls)
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])


def get_model(temperature: float = 0.0):
    """Retrieve chat model instance (OpenAI/OpenRouter, Google GenAI, or MockReasoningModel)."""
    provider = os.getenv("LLM_PROVIDER", "google").lower()
    model_name = os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL")
    force_mock = os.getenv("USE_MOCK_LLM", "false").lower() in ["1", "true", "yes"]

    if force_mock:
        return MockReasoningModel()

    if provider == "google":
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if api_key and api_key != "your_google_api_key_here":
            from langchain_google_genai import ChatGoogleGenerativeAI
            target_model = model_name or "gemini-2.0-flash"
            return ChatGoogleGenerativeAI(
                model=target_model,
                google_api_key=api_key,
                temperature=temperature,
            )
        return MockReasoningModel()

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key and api_key != "your_openai_api_key_here":
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
            target_model = model_name or "gpt-4o-mini"
            try:
                from langchain_openai import ChatOpenAI
                return ChatOpenAI(
                    model=target_model,
                    api_key=api_key,
                    base_url=base_url,
                    temperature=temperature,
                )
            except Exception:
                return OpenAICompatibleChatModel(
                    model_name=target_model,
                    api_key=api_key,
                    base_url=base_url,
                    temperature=temperature,
                )
        return MockReasoningModel()

    return MockReasoningModel()
