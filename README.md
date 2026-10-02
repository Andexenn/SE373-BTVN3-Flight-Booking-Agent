# SE373 - Lab Assignment 3: Intelligent Flight Booking Agent

- **Student:** Phan Huỳnh Hưng
- **Student ID:** 24520623
- **Course:** Agentic AI Engineering (SE373)

---

## Lab Report

📄 **Detailed lab report is available here:** [REPORT.md](./BTTH_Buoi3_SE373_PhanHuynhHung_24520623.pdf)

---

## Getting Started & Execution Guide

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. API Key Configuration (Optional):
   - Rename or copy `.env.example` to `.env`:
     ```bash
     cp .env.example .env
     ```
   - Fill in your API Key (`GOOGLE_API_KEY` or `OPENAI_API_KEY`).
   - *Note:* The system includes a built-in offline deterministic reasoning simulation (`MockReasoningModel`), allowing full test and benchmark execution without an API key.

3. Test Live API Connection (like BT2):
   ```bash
   python test_connection.py
   ```

4. Run independent unit tests for all Harness safety layers:
   ```bash
   python test_manual.py
   ```

5. Run empirical benchmark comparing the 3 Agent design patterns (ReAct, Plan-then-Execute, Hybrid):
   ```bash
   python benchmark.py
   ```

6. Run interactive human-in-the-loop CLI demo:
   ```bash
   python main.py
   ```
