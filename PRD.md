# Product Requirements Document

## Product

**Working Name:** TBD\
**Hackathon:** HackGT 13\
**Current State:** We already have the foundation for an iMessage-based agent using BlueBubbles, originally focused on helping group chats turn conversations into completed plans. We are expanding that system into a broader **AI relationship manager**.

## 1. Product Direction

The product helps users maintain the relationships they already care about. It uses message history and calendar context to understand who matters to the user, notice when relationships need attention, and help the user follow through.

The existing group-chat planning agent becomes one part of this system rather than the entire product.

## 2. Core Loop

**Understand → Notice → Act**

The user defines important relationships and how they want to maintain them. The system observes messages and calendar activity, detects when something needs attention, and recommends a concrete action.

Examples:

- Haven’t talked to a parent in several days → suggest calling or texting.
- Told a friend “we should get dinner” → detect that no plan was created.
- Group chat has been discussing plans without deciding → find a time and help finalize it.
- Promised to follow up with someone → remind the user.
- Conversation ended awkwardly or unresolved → privately suggest following up.

## 3. Relationship Profiles

Users can assign people to categories such as:

- Close friends
- Family
- Parents
- Siblings
- Cousins
- Grandparents

More importantly, each person gets a **relationship intention**, such as:

- Talk twice a week
- Call every weekend
- Meet at least once every two weeks
- Stay in touch after moving away
- Become closer over time

The system evaluates actual interactions against those intentions.

## 4. Existing System We Keep

The existing BlueBubbles/iMessage integration remains the primary message interface.

The current group-chat agent becomes the **Planning Agent**, responsible for:

1. Detecting when people are trying to make plans.
2. Detecting when those plans stall.
3. Identifying participants.
4. Finding calendar availability.
5. Suggesting a concrete time or next step.
6. Drafting the message needed to move the plan forward.
7. Creating the calendar event after approval.

We should build on this rather than replace it.

## 5. What We Add

### Relationship Memory

Maintain state for important people:

- Who they are
- Relationship type
- Desired interaction frequency
- Last meaningful interaction
- Recent commitments or plans
- Pending follow-ups

### Relationship Dashboard

A single screen showing the relationships currently needing attention.

Example:

**Mom**\
Haven’t talked in 5 days.\
`Text` `Call`

**Jake**\
You discussed getting dinner but never scheduled it.\
`Finish Plan`

**Friend Group**\
Saturday plans stalled.\
`Resolve`

### Follow-Up Detection

Extract commitments and unfinished actions from conversations:

- “I’ll text you later.”
- “Let’s hang next week.”
- “Let me know how your interview goes.”
- “We should talk about this later.”

The system remembers these and resurfaces them at the right time.

### Calendar Awareness

Use calendar context to turn relationship intentions into concrete actions.

Example:

> You haven’t seen Alex in three weeks, and you’re both free Thursday evening.

`Suggest Hangout`

## 6. MVP Demo

For the hackathon, we do **not** need to build every relationship-management feature.

The demo should show three connected moments:

### 1. Relationship Awareness

The dashboard shows an important person the user has not contacted recently.

### 2. Conversation Intelligence

The system identifies a stalled plan from an iMessage conversation.

### 3. Action

It checks calendar availability, proposes a time, drafts the message, and creates the event after approval.

This demonstrates that the system does more than summarize messages: it turns relationship intent into action.

## 7. Architecture

**BlueBubbles / iMessage**\
↓\
**Conversation State + Relationship Memory**\
↓\
**Agent Orchestrator**

Agents:

- Conversation Agent
- Relationship Agent
- Planning Agent
- Calendar Agent

↓\
**Suggested Action**

- Text
- Call
- Follow up
- Make plan
- Schedule event

## 8. Product Principle

**The AI should not replace human relationships. It should notice when life gets in the way of them and help the user follow through.**

For the hackathon, every feature should reinforce that idea.
