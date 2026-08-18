# intro-ao-workshop

A hands on lab introducing the Ansible Automation Orchestrator (AO), the add-on to Ansible Automation Platform that unifies task-based, event-driven, and AI-driven automation into a single visual workflow experience. Participants build workflows on a drag-and-drop canvas using AAP job template nodes, AI-powered task nodes, approval gates, conditional/switch routing, MCP integrations, and Event Driven Ansible triggers. The lab is needed because AO is a new capability and practitioners need guided experience connecting it to the AAP foundation they already use.

**Owner:** rlopez133

---

## What was set up

1. Repository created
2. `catalog-info.yaml` added to repository
3. Registered in Developer Hub catalog
4. Orchestrator workflow started — your AI-guided content pipeline is running!

## What happens next

Claude will walk you through the entire content lifecycle — from intake and spec creation, through Jira tracking and reviews, all the way to a published lab on RHDP. Just follow the prompts!

## Getting started

### DevSpaces (recommended)

1. Open in DevSpaces: `https://devspaces.apps.ocpv-infra02.wdc07.infra.demo.redhat.com#https://github.com/rhpds/intro-ao-workshop`
2. Use Claude via the **extension** or the **CLI**:
   - **Extension:** Click the **Claude** icon in the sidebar, click **New Session**. If the Claude icon is not visible, open **Extensions** (`Ctrl/Cmd+Shift+X`), find **Claude Code for VS Code** under the DevSpaces section, click it, then click **Enable (Workspace)**.
   - **CLI:** Open a terminal and run `claude`
3. Run `/rhdp-publishing-house` — and you're off!

### Local machine

1. Install the skills:
   ```
   git clone -b prod https://github.com/rhpds/rhdp-publishing-house-skills.git ~/.claude/skills/publishing-house
   ```
2. Clone the repo:
   ```
   git clone https://github.com/rhpds/intro-ao-workshop
   ```
3. `cd intro-ao-workshop`
4. Start Claude CLI: `claude`
5. Run `/rhdp-publishing-house` — and you're off!
