# Rally — Product Requirements Document

**Hackathon:** HackGT 13  
**Target Tracks:** Meta — Human Connection with AI; SpaceXAI — Agentic AI / Grok  
**Platform:** iMessage via BlueBubbles  
**Build Window:** <48 hours

## 1. Product Summary

**Rally turns “we should” into “we did.”**

Rally is a shared AI agent that lives inside an iMessage group chat. It understands when a group is trying to make plans, tracks preferences and constraints from natural conversation, detects when a plan has stalled, and proposes the smallest next step needed to move the group forward.

After explicit user approval, Rally can execute real-world actions such as finding a venue, making a reservation, and creating a calendar event.

Rally is not designed to be another chatbot that waits for questions. Its purpose is to reduce the coordination burden that prevents friends from actually spending time together.

---

## 2. Problem

Group chats are where social plans begin, but many plans never happen.

Typical conversation:

- “We should get dinner Friday.”
- “I’m down.”
- “Same.”
- “Anything but sushi.”
- “I’m not free until 7.”

Then the conversation stops.

Everyone may want the plan to happen, but somebody must manually:

- determine who is interested,
- reconcile schedules,
- remember preferences,
- select a venue,
- get agreement,
- make the reservation,
- communicate the final plan.

Because nobody wants to become the default organizer, plans frequently die.

---

## 3. Product Goal

Rally converts **unstructured group conversation into coordinated action**.

The core loop is:

**Understand → Detect Blocker → Propose → Confirm → Act → Report**

The AI should perform the administrative work of coordination while leaving social decisions and final approval to the group.

---

## 4. Target User

Existing friend groups of approximately **3–8 people** who already use iMessage to coordinate social plans.

Primary use case:

> A group expresses interest in doing something together but fails to convert that interest into a concrete plan.

---

## 5. Core Product Behavior

Rally maintains a structured **Group Plan State** derived from recent chat messages.

Example:

```json
{
  "goal": "Friday dinner",
  "participants": ["Nick", "Sarah", "Alex", "Maya"],
  "constraints": [
    "Nick available after 7 PM",
    "Sarah does not want sushi",
    "Midtown preferred"
  ],
  "status": "BLOCKED",
  "blockers": [
    "restaurant not selected",
    "exact time not confirmed"
  ],
  "next_action": "propose venue and time"
}
```

Rally chooses one of five behaviors:

- **WAIT** — no intervention needed
- **NUDGE** — plan has stalled and enough context exists
- **ASK** — one essential piece of information is missing
- **PROPOSE** — suggest a concrete next step
- **ACT** — execute an approved tool call

The default behavior should be **WAIT**. Rally should intervene only when useful.

---

## 6. Plan State Machine

Each active plan progresses through:

1. **SPARK** — someone proposes an activity
2. **INTEREST** — multiple people express interest
3. **ALIGNMENT** — schedule or preferences emerge
4. **BLOCKED** — group interest exists, but a decision is missing
5. **READY** — Rally has enough information to present an executable plan
6. **EXECUTING** — group explicitly authorizes the action
7. **DONE** — plan is confirmed
8. **ABANDONED** — insufficient interest; Rally stops intervening

This state should drive both agent behavior and the demo visualization.

---

## 7. MVP User Flow

### Primary Demo: Revive a Dead Dinner Plan

The iMessage group contains an unfinished conversation:

> “Dinner Friday?”  
> “I’m down.”  
> “Anything except sushi.”  
> “I can’t until after 7.”  
> “Midtown?”

Rally extracts:

- activity: dinner
- date: Friday
- earliest time: after 7 PM
- cuisine restriction: no sushi
- location preference: Midtown
- status: BLOCKED

Rally sends:

> **Rally:** Friday seems to work after 7, and Midtown came up earlier. I found a good option at 8 PM. Want me to book it?

A group member replies:

> “Book it.”

Rally:

1. calls the reservation tool,
2. receives a confirmation,
3. optionally creates a calendar event,
4. posts the completed plan back to iMessage.

Example:

> ✅ **Booked**  
> Barcelona Wine Bar  
> Friday · 8:00 PM  
> Party of 4  
> Confirmation: RLY-38241  
> 📅 Calendar event created

---

## 8. AI Architecture

### Conversation Understanding

The model converts recent iMessage conversation into structured group state:

- activity or goal,
- participants,
- expressed interest,
- availability,
- preferences,
- objections,
- unresolved decisions,
- current plan state.

### Agentic Reasoning

Grok acts as the primary decision and tool-use agent.

Inputs:

- recent messages,
- current structured plan state,
- available tools,
- previous action results.

Outputs should be structured rather than free-form.

Example:

```json
{
  "plan_state": "BLOCKED",
  "action": "PROPOSE",
  "blocker": "venue not selected",
  "confidence": 0.93,
  "tool": "search_places"
}
```

If Muse or another Meta model is incorporated, its primary role should be **social-context extraction and group-state understanding**, rather than duplicating Grok's agent behavior.

---

## 9. Tool Scope

### P0 — `search_places`

Find candidate venues based on:

- activity,
- approximate location,
- time,
- party size,
- conversation preferences.

A real places/search API is preferred.

### P0 — `create_reservation`

Creates a reservation after explicit user approval.

For the hackathon, this may be a convincing mock service returning realistic confirmation data.

### P1 — `create_calendar_event`

Creates a calendar event after the plan is finalized.

This provides a strong demonstration that Rally can move from conversation into real-world action.

### P0 — `send_message`

Posts proposals, clarification requests, and confirmations back into the iMessage group through BlueBubbles.

---

## 10. iMessage Integration

BlueBubbles will provide the messaging layer.

Required functionality:

- receive new group-chat messages,
- identify chat and sender,
- fetch or maintain recent conversation history,
- pass messages to the Rally backend,
- send Rally responses back into the same iMessage thread.

BlueBubbles integration should remain thin. Business logic and agent state should live in the Rally backend rather than inside the messaging integration.

---

## 11. Suggested Technical Architecture

```text
iMessage
   ↓
BlueBubbles
   ↓
Rally Backend
   ↓
Conversation History
   ↓
Group State Extraction
   ↓
Rally Agent / Grok
   ↓
Plan State Machine
   ↓
Tools
 ┌───────┬─────────────┬──────────┐
 Search  Reservation   Calendar
 └───────┴─────────────┴──────────┘
   ↓
BlueBubbles
   ↓
iMessage
```

Recommended implementation:

- **Backend:** FastAPI or Next.js API routes
- **Database:** SQLite or Supabase
- **AI:** Grok + optional Muse
- **Messaging:** BlueBubbles
- **Places:** Google Places or equivalent
- **Reservation:** mock for MVP
- **Calendar:** real integration if time permits

---

## 12. Demo Visualization

For judging, include a lightweight developer/debug view showing Rally's current interpretation:

```text
Goal
Dinner Friday

Signals
✓ 4 people interested
✓ Friday
✓ after 7 PM
✓ no sushi
✓ Midtown

Plan State
BLOCKED

Current Blocker
No restaurant selected

Next Action
PROPOSE VENUE

Confidence
93%
```

This makes the AI reasoning visibly different from a generic chatbot.

---

## 13. MVP Scope

### Must Have

- BlueBubbles iMessage ingress and outgoing messages
- recent conversation context
- structured group-state extraction
- plan state machine
- Grok decision loop
- stall/blocker detection
- context-aware proposal
- explicit confirmation before real action
- venue search
- mock reservation
- final confirmation message
- reliable scripted demo

### Nice to Have

- real calendar creation
- automatic proactive nudge after inactivity
- Muse-based social-context extraction
- polished Rally reasoning dashboard
- real reservation API

### Out of Scope

- food delivery
- payments
- WhatsApp/Discord/etc.
- long-term cross-week memory
- complex group permission systems
- automatic actions without user approval
- sophisticated voting systems
- fully general personal assistant behavior

---

## 14. Safety and Interaction Rules

Rally should follow several simple behavioral constraints:

1. Never make a purchase, reservation, or external commitment without explicit approval.
2. Never repeatedly nudge the same stalled plan.
3. Do not force consensus when group preferences genuinely conflict.
4. Prefer asking one targeted clarification over making unsupported assumptions.
5. Default to silence when intervention would not materially help.
6. Preserve the group's agency: Rally coordinates decisions; it does not make social decisions for them.

---

## 15. Hackathon Success Criteria

The project succeeds if judges can understand the value within seconds and see the full loop execute reliably.

Required demo outcome:

**dead group chat → Rally understands intent → detects blocker → proposes solution → user confirms → Rally executes tool → completed plan appears in iMessage**

Judging goals:

- AI is essential rather than decorative.
- Human connection is the central product outcome.
- Grok performs meaningful reasoning and tool use.
- The system demonstrates multi-step agentic behavior.
- The experience feels like a plausible consumer product.
- The live demo completes in under two minutes.

---

## 16. Product Positioning

### Tagline

**Rally — Turn “we should” into “we did.”**

### One-Line Pitch

Rally is a shared AI agent for iMessage that understands what your group is trying to make happen, resolves the coordination blocking it, and—with permission—takes the actions needed to turn conversation into real plans.

### Core Product Thesis

**Social networks made staying in touch easier. Rally makes actually spending time together easier.**
