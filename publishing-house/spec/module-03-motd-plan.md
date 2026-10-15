# Module 03 rework: Vacation Anyone? becomes Message of the Day

Status: phase 1 (content) starting 2026-10-14. Written on `main` at
`261e3cb`.

**Split into two phases deliberately.** Phase 1 is everything that
lives in this repo and can be built against a hand-made job template on
one dev GUID. It lands with the new workflow `enabled: false`, so it is
safe to merge on its own. Phase 2 is the AgnosticV change that makes
the job template reproducible, and the one-line flip to `enabled: true`
that depends on it. Roger will supply AgnosticV repo access when phase
1 is done.

## Why

Module 03 teaches the right thing but with the wrong subject. "Ask an
agent for a city to visit" is not IT Ops, and it leaves the lab's thesis
(automation orchestrator decides, AAP changes something real) to land in
module 04 instead of in the student's first workflow.

Converting rather than deleting, because every cross-module callback
survives a conversion and breaks under a deletion. The module keeps its
shape: build three steps from an empty canvas.

## The scenario

The student builds a workflow that writes a login banner on a real RHEL
node. The agent supplies the human wording; AAP supplies the live host
facts. Neither could produce the banner alone, which is the lesson.

Three sharpenings agreed during design:

1. **Shorthand in, polished output out.** The student types a scrap, not
   a brief. This makes the *run step with mock data* figure actually
   prove something, where today it just shows a model naming a city.
2. **Agent prose mixed with gathered truth.** Real MOTDs show system
   information. The banner carries both, so the output is half
   verifiable rather than "whatever the model said".
3. **Colour and box drawing.** `/etc/motd` is cat'd to the terminal at
   login, so ANSI escapes render. This is the "nicer visual" that does
   not require exposing a web server.

### Example input

```
lab web tier, patching sat 2am utc, reboot, ping platform team if issues
```

Fleet-level wording, not host-level. The banner goes to every node in
the job template's inventory, so a note naming one host would produce a
banner claiming all of them are that host.

### Example rendered banner

```
╔══════════════════════════════════════════════════════════════╗
║  LAB WEB TIER                                       node1    ║
╚══════════════════════════════════════════════════════════════╝

  RHEL 9.4    kernel 5.14.0-427.el9    up 4 days    10.0.1.21
  /  18% used of 40G

  ***  PATCHING SATURDAY 02:00-04:00 UTC  ***

  This host is patched and rebooted weekly. Expect a short
  reboot inside the window. Do not schedule long-running
  jobs across it.

  Owner: platform team
```

Three lines come from the agent: the headline, the notice paragraph and
the owner. Everything else is `gather_facts` output the agent never
saw, rendered per host, so `node1` in the header is that node's own
`inventory_hostname` and each node's banner names itself.

## Agent contract

Trigger: one free-text field, `banner_request`.

Response schema, three strings (same count and shape as the old
`city` / `reason` / `fun_fact`, so the "copy three expressions" lesson is
untouched):

- `headline` - short, capitals, the banner's top line
- `notice` - two or three sentences on what to expect and when
- `owner` - the team to contact

Draft prompt:

```
You are a RHEL systems administrator writing the login banner for a
server. An engineer has given you this note:

${trigger.banner_request}

Write the banner. Give a short headline in capitals, a notice of two or
three sentences telling anyone who logs in what to expect and when, and
the name of the team to contact. Do not invent facts about the host.
The banner already shows its real configuration.
```

The last two sentences matter: without them the model invents kernel
versions, which AAP is supplying for real.

## Extra vars on the AAP step

```
motd_headline: ${motd_agent.result.content.headline}
motd_notice:   ${motd_agent.result.content.notice}
motd_owner:    ${motd_agent.result.content.owner}
```

Three expressions, nothing else. **No host is passed.** The job
template carries an inventory and the playbook runs against it.

This matches what the rest of the lab already does. Not one AAP step in
the disk utilization workflow passes a host: `Disk Utilization Check`
passes no extra vars at all, and the remediation steps pass only
`disk_tier`, `disk_mount` and `disk_use_percent`. Every playbook is
`hosts: "{{ _host | default('all') }}"`, with `_host` present as an
override the workflow never sets.

The direction of travel is the opposite of what an extra var would do.
`check_disk.yml` line 63 publishes `notify_host: ansible_play_hosts |
join(',')`, so host identity comes *out* of AAP as an artifact,
discovered from the inventory, rather than being told to it.

An earlier draft of this plan had the student type `target_host: node1`
as a literal beside the three expressions, and justified it as teaching
the difference between a value and a reference. That was wrong. It
contradicted the lab's own convention and hardcoded something the
inventory already knows. The teaching point is recovered better by
having the playbook publish the rendered banner back as an artifact,
which shows results flowing back from AAP and sets up module 04.

Consequence: the banner lands on every node in the inventory, not one.
That is more realistic (a maintenance banner goes to the fleet) and it
removes the risk of the student picking the wrong host. It also means
the finale works whichever node they log in to. node2 being the disk
utilization victim no longer matters, since writing `/etc/motd` there
is harmless.

## Repo change inventory

### New

A new scenario directory, `lab-setup/message-of-the-day/`. The existing
three are kebab-case and named after the scenario, not the action:
`disk-utilization`, `cve-remediation`, `ticket-enrichment`. Playbook
files inside them are mostly snake_case verb_noun (`check_disk.yml`,
`notify_chatroom.yml`, `cve_fetch_and_commit.yml`), so `set_motd.yml`
fits.

This is also a cleanup, not only an addition. Today module 03 has no
directory of its own: it borrows `disk-utilization/notify_chatroom.yml`
and its card lives at `disk-utilization/tasks/notify/hello.yml`, which
is why the `notify_card` override exists at all. Giving module 03 its
own scenario directory stops it squatting in the disk tree.

- `automation/ansible/playbooks/lab-setup/message-of-the-day/set_motd.yml`
  (~30 lines)
  - `hosts: "{{ _host | default('all:!localhost') }}"`, `gather_facts: true`.
    The `_host` override matches the disk playbooks; the
    `all:!localhost` default matches the ticket-enrichment ones and is
    the safer of the two, since `all` alone would try to write
    `/etc/motd` on the control node.
  - writes `/etc/motd` from a template, needs become
  - **also prints the rendered banner via debug**, so a figure exists
    even if ssh to a node is unavailable
  - publishes the rendered banner back as an artifact via `set_stats`,
    the way `check_disk.yml` publishes `notify_host`. Gives the student
    something to see in the Output panel and foreshadows module 04.
- `automation/ansible/playbooks/lab-setup/message-of-the-day/templates/motd.j2`
  - ANSI colour, box drawing, facts: distribution + version, kernel,
    uptime, default IPv4, root mount usage, hostname
  - **This is the first `.j2` in the playbooks tree.** None of the
    existing lab-setup playbooks render a file; they post JSON to APIs
    or set facts inline, which is why `hello.yml` builds its card as a
    `set_fact` string. Roles already use templates
    (`ocp4_workload_openflake_mcp/templates/deploy.yaml.j2`), so this
    is new to the directory rather than new to the repo. Ansible
    resolves `templates/` relative to the playbook's own directory, so
    `template: src=motd.j2` works with no path juggling.
  - Worth preferring over an inline `set_fact` string: a multi-line
    banner with box drawing and escape codes is unreadable crammed
    into YAML.
- AAP job template `Linux - Set Message of the Day`
  - **External dependency.** Job templates are not created in this repo.
    Only `cve_sync_and_deploy.yml` creates one at runtime; the rest
    arrive pre-made from whatever provisions AAP. Same conversation as
    the `ao-extra-vars` PATH install.
  - Naming follows the existing `Linux - Remediate - Disk Expand`.
  - Whoever creates it needs two things: the playbook path
    `automation/ansible/playbooks/lab-setup/message-of-the-day/set_motd.yml`,
    and an inventory containing the RHEL nodes, since the workflow
    passes no host.

### Renamed

- `files/workflows/vacation-suggestion.json` -> `message-of-the-day.json`
- `vars/bindings_vacation_suggestion.yml` -> `bindings_message_of_the_day.yml`
- `pages/module-03-your-first-workflow-hello-world.adoc` -> `...-motd.adoc`
  (decision, see below)

### Edited, strings only

- `defaults/main.yml` - the one workflow entry: key, name, file,
  description. `student_copy: false` stays as is.
- `tests/test_ao_workflow.py` - `TestWireVacationSuggestion` becomes
  `TestWireMessageOfTheDay`, same assertions with new strings. The two
  tests guarding `student_copy: false` only need the key renamed.
- `tests/import_solutions_workflow.py` - three docstring examples
- `tasks/setup_workflows.yml` - two comments naming Vacation / module 03
- `qa-automation/healthcheck.yml` line 107 - comment
- `content/antora.yml` line 54 - comment naming Vacation Suggestion
- `content/modules/ROOT/nav.adoc` line 3 - label
- `content/modules/ROOT/pages/index.adoc` - line 53 bullet, lines 117-120
  table row

### Deleted

- `playbooks/lab-setup/disk-utilization/tasks/notify/hello.yml`
- `notify_chatroom.yml` lines 40-47, the `notify_title` / `notify_text` /
  `notify_fact` defaults that only `hello.yml` consumed
- `notify_chatroom.yml` lines 12-19, the `notify_card` override plumbing.
  Decision: module 03 was its only consumer, but it is harmless generic
  code and was a deliberate commit (`85ebf0b`).

### Unchanged, which is the point

- `module-02` closing line 332-333, "in the next module you put both of
  these to work, building a workflow from an empty canvas"
- `module-04` line 5, the "previous module built from an empty canvas"
  contrast, and line 72, the callback to the run-step-with-mock-data
  moment
- the `student_copy: false` machinery and both tests guarding it
- the whole AO import, wire, validate and publish pipeline
- the module page's section structure
- 23 of the 25 image filenames

### Re-recorded

Unavoidable. The workflow name sits in the header bar of every step
panel and `vacation_request` is in the left Input panel throughout, so
all 25 figures are contaminated regardless of how small the code change
is. This is the same cost as any change at all, including a bare rename.

- one new recording into `shots-review/` (gitignored)
- `tools/module-03.shots` re-fit, 24 shot lines
- 25 PNGs re-cut, of which only two change filename:
  - `15-job-template-notify` -> `15-job-template-motd`
  - `22-chatroom-card` -> `22-motd-banner`

## Order of work

### Phase 1: content, in this repo, now

Everything here works against a hand-made job template on one dev GUID.
Nothing here needs AgnosticV. The phase ends with a branch that is safe
to merge because the new workflow is still `enabled: false`.

**Steps 0 to 4 are done, verified end to end on GUID j58q7 on
2026-10-15.** A manual trigger with the example note produced
`WEB TIER PATCHING SCHEDULED` plus a written notice in the banner on
node1, over that host's own gathered facts. What the live run taught:

- **The job template needs `ask_variables_on_launch: true`.** Without
  it AAP silently discards the three `motd_*` extra vars and the
  banner renders the playbook defaults, with nothing failing. Every
  other template in this lab that takes workflow extra vars already
  has it set. **Phase 2's dispatch entry must set it**; it is the
  easiest thing in this whole plan to lose.
- `limit` is `node1,node2,localhost`. The playbook's `all:!localhost`
  drops localhost, so both nodes get the banner and each names itself.
- No IP in the banner. `ansible_default_ipv4` is the NAT gateway and
  reads 10.0.2.2 on every node, which proved nothing and overflowed
  the box once a real kernel string was in the line.
- `debug` must use `splitlines()`. `split("\n")` never matches:
  YAML keeps the escape literal and the templar does not expand it.
- Both AO and AAP have valid certificates. No insecure TLS flag is
  needed against this lab.
- `import_solutions_workflow.py` could not wire a job template the
  lab had never used, because it scraped IDs off already-published
  workflows. It now asks the controller the way the role does.

0. ~~Confirm ssh~~. Done, confirmed working.
1. **Create `Linux - Set Message of the Day` in AAP by hand** on the dev
   GUID. Needs the playbook path and an inventory holding the RHEL
   nodes. Throwaway: phase 2 replaces it with a dispatched one.
2. **Delete the live Vacation Suggestion from `solutions`:**
   `python3 tests/import_solutions_workflow.py vacation_suggestion --delete`.
   **Must run before step 5**, while the `vacation_suggestion` key
   still exists in `defaults/main.yml`.
3. Write `set_motd.yml` and `motd.j2`, test against the nodes directly,
   outside AO.
4. Write the workflow JSON and bindings, import into `solutions`,
   verify an end-to-end run through AO.
5. Rename and re-point everything: the workflow entry in
   `defaults/main.yml` (**with `enabled: false`**), the two renamed
   automation files, the page filename, and the string edits listed
   above.
6. Rewrite the module page prose against the real UI.
7. ~~Record.~~ Done: `motd-student.mp4`, 1920x1080, 60fps, 319.5s,
   cursor suppressed.
8. ~~Cut shots, fit boxes.~~ Done. 26 figures: the 25 carried over
   plus `22b-back-to-editor`, because the run view is still open after
   the detour to the host and the student has to click back into the
   editor before they can publish. Notes worth keeping:
   - Figure 03 is in-frame this time. The Vacation take had no frame
     showing the filled field row and *Create* together, so it was a
     native screenshot; here it is at t=30. Not t=29: *Required* is
     still unticked a second earlier and the page says to tick it.
   - **Figure 22 is cut by hand, not by `batch`.** It is the only
     figure showing the Showroom, whose credential panel is on the
     left of that screen with the OpenFlake password and the LLM API
     key both legible. `batch` can only draw boxes, so this one uses
     `grab --redact`. The command is in `tools/module-03.shots`.
   - The panel geometry is unchanged from the Vacation recording, so
     most boxes were carried over rather than remeasured. Four were
     not and had to be fixed after the first cut: 12 boxed *Task
     Agent* instead of *AAP Execution*, 15 boxed the wrong row of the
     job template list, 18 sat on a frame where only one of the three
     extra vars was filled, and 21 boxed the *View job in AAP* link
     instead of the Status column.
   - The page said to filter the job template list by typing
     `message`. The recording types `Linux`. Prose changed to match.
   - Roger's review caught four more box errors after that: 04 was not
     on the `+` handle, 08 clipped the prompt's bottom and the
     schema's right edge, 18 was offset on both boxes, and 22 wanted
     the terminal tab boxed as well as the banner. The *Create* and
     *Update* button box was also too generous at `1822,119,94,45`;
     the button is `1818,124,82,34`.
9. ~~Build, verify figure count and no em dashes.~~ Done: 26 figures,
   all resolving, no orphans, 0 em dashes.
10. Merge. Safe, because `enabled: false` keeps the missing job
    template out of the preflight.

Steps 3 and 4 must finish before 7, because you record against a
working environment.

### Phase 2: AgnosticV, later

Blocked on repo access, which Roger will supply after phase 1.

11. Add `Linux - Set Message of the Day` to
    `infra.aap_configuration.dispatch`, pointed at
    `automation/ansible/playbooks/lab-setup/message-of-the-day/set_motd.yml`
    with an inventory holding the RHEL nodes.
12. Provision a clean GUID and confirm the template arrives from
    dispatch rather than by hand.
13. Flip the `message_of_the_day` entry to `enabled: true` and merge.
14. Provision one more clean GUID end to end, confirming the preflight
    resolves and all four workflows import.

## Decisions settled 2026-10-14

- **ssh works.** Confirmed by Roger: the Showroom terminal can reach a
  node over ssh. The module's finale is a real login showing the
  banner. The debug print and the `set_stats` artifact stay anyway, as
  belt and braces and because the artifact earns its keep on its own.
- **Job template created manually for now.** Roger will make
  `Linux - Set Message of the Day` by hand rather than waiting on the
  provisioning owner. Means it is not yet reproducible from a clean
  provision; see the open item below.
- **Page filename is renamed** to `module-03-your-first-workflow-motd.adoc`.
- **`notify_card` stays.** Generic, harmless when unused.

### Still open

- **Reproducible job template. This is a merge blocker, not a loose
  end.** See the section below.
- **Mattermost as a second destination.** The same playbook could also
  post the rendered banner as a card. Additive, deferrable, and less
  needed now that ssh is confirmed.
- ~~**Workflow name in AO.**~~ Settled: `Message of the Day`. Roger
  first chose `Hello World - Message of the Day`, then recorded the
  build typing `Message of the Day`. That name is in the title bar of
  all 25 figures, so the recording won and everything else was renamed
  to match: the page, `defaults/main.yml`, the export, two tests and
  the live copy in `solutions`.
- ~~**Module title.**~~ Settled: "Your First Workflow: Message of the
  Day".

## The job template is a merge blocker

A new provision will **not** have `Linux - Set Message of the Day`.
Creating it by hand puts it on one GUID and nowhere else.

The failure is worse than a broken module.
`tasks/resolve_job_templates.yml` is a preflight that runs across every
enabled workflow before any of them is imported, and it ends in
`ansible.builtin.fail` listing anything that did not resolve. So on a
fresh GUID the AO config role dies at preflight and **no workflows
import at all**: not Message of the Day, and not CVE, Disk or Ticket
either. One missing template takes the whole lab down.

The templates are created by **AgnosticV's
`infra.aap_configuration.dispatch`**, named in the comment at the top
of `resolve_job_templates.yml`, which is also why this role must run
after dispatch. That is a different repo and not ours to change here.

### The safety valve

The `enabled` flag on each workflow entry in `defaults/main.yml` is the
way out. `setup_workflows.yml` builds `_ao_enabled_workflows` by
filtering on it, and `ao_collect_job_templates.yml` loops over exactly
that list, so a disabled entry never reaches the preflight.

Safe landing sequence:

1. Land the repo change with `enabled: false` on the
   `message_of_the_day` entry. Everything merges, nothing breaks, new
   provisions carry on importing the other three workflows.
2. Get AgnosticV dispatch updated to create
   `Linux - Set Message of the Day`, pointed at
   `automation/ansible/playbooks/lab-setup/message-of-the-day/set_motd.yml`
   with an inventory holding the RHEL nodes.
3. Flip to `enabled: true` once dispatch is creating it.

Do **not** merge the bindings rename with `enabled: true` ahead of the
AgnosticV change. The hand-made template on the dev GUID will mask the
problem locally right up until someone provisions a fresh one.

## Removing Vacation Suggestion from solutions

Two separate layers. Only one needs work.

**Fresh provisions: already handled.** The plan renames the
`vacation_suggestion` entry in `defaults/main.yml` rather than adding a
new one beside it. With no entry, nothing imports it. No extra task
needed.

**Existing instances: needs an explicit delete.** `setup_workflows.yml`
imports what is listed and never prunes, so re-running against an
already-provisioned lab leaves Vacation Suggestion orphaned in
`solutions` next to the new Message of the Day. In practice this only
affects the dev GUID being tested against, since student instances are
provisioned fresh.

The tool already exists:

```
python3 tests/import_solutions_workflow.py vacation_suggestion --delete
```

**Sequencing trap.** That command resolves the key through
`defaults/main.yml` (line 223, `filename, name, description =
table[args.key]`) to get the workflow's name. It does not read the JSON
file, so deleting the export is fine, but **renaming the entry is not**.
Run the delete *before* the `defaults/main.yml` rename lands. After
that the only routes are the AO UI or a direct
`DELETE /api/v1/workflows/{id}`.

The full teardown path, `remove_workload.yml`, deletes the whole
`solutions` project and everything it owns. Correct but a sledgehammer.

**QA is unaffected.** `ao_expected_workflows` in
`qa-automation/healthcheck.yml` lists only RHEL CVE Remediation, Disk
Utilization Remediation and Ticket Enrichment Demo. Vacation Suggestion
was never in it. The assertion is a subset check
(`expected | difference(found) | length == 0`), so extra workflows in
`solutions` do not fail it. Removing Vacation breaks nothing, and by
the same token the healthcheck will not catch a lingering copy either.

Minor, while in that file: the success message reads "Both solutions
workflows are present" while the list holds three. Stale string from
when there were two.

## Template injection in set_motd.yml, accepted deliberately

Flagged by an automated review on 2026-10-14. Recorded here rather
than in the playbook, which carries a two line pointer to this
section.

**The mechanism is real, verified against ansible-core 2.21.** The
three `motd_*` values are LLM output. They reach the playbook as job
template extra vars, which ansible-runner passes as `-e @extravars`,
and `ansible/utils/vars.py` line 193 loads that file with
`trusted_as_template=True`. Trusted values have their embedded Jinja
evaluated rather than printed, so a headline reading
`{{ lookup('pipe', ...) }}` runs on every host in the inventory.

Tested, with the value trusted and carrying a `lookup('pipe')`
payload:

```
bare reference               EXECUTED
regex_replace on the value   EXECUTED
| string first               EXECUTED
lookup('vars', 'motd_...')   EXECUTED
| ansible.builtin.unsafe     no such filter in this version
```

**No in-playbook mitigation exists.** Evaluation happens when the
variable is dereferenced, which is before any filter in the pipeline
runs, so sanitising filters clean a result that has already executed.
The review's suggested `regex_replace` fix was tested and does not
work. Shipping it would have added code that looks protective and is
not.

**Accepted because no boundary is crossed.** Module 04 hands the
student `{aap_controller_admin_user}` / `{aap_controller_admin_password}`,
and module 03's own finale tells them to `ssh node1`. With AAP admin
they can already run any playbook as root on these nodes, and the
nodes are torn down with the lab. The same reasoning covers the ANSI
escape half of the finding.

If the pattern is ever lifted into a real estate, the fix has to be
upstream of AAP: the model's output must arrive untrusted, or the
agent's response must be constrained before it becomes an extra var.
Nothing in the playbook can do it.

## Rejected during design

- **A website on node1 serving a config report.** Every clickable URL in
  this lab is an OpenShift Route; nothing exposes a CNV VM to the
  student's browser. Would need httpd, firewalld, a Service plus Route
  or NodePort against a VM, and a new `%GUID%` attribute in
  `antora.yml`. That is lab topology work in a layer this repo does not
  touch, landing on the provisioning owner as a third ask.
  - If the clickable page is ever wanted: cheaper to run a small nginx
    pod with a Route and push rendered HTML into a ConfigMap, copying
    the existing pattern in `ocp4_workload_openflake_mcp`, than to
    expose the VM.
  - The good idea inside it, the agent translating a natural-language
    question into structured parameters, is preserved in the shorthand
    input above.
- **Giving the module 03 agent MCP tools.** Module 02 does build the AAP
  MCP integration, so it is possible, but it would steal module 05's
  lesson and make a first workflow much heavier.
- **Deleting module 03 outright.** Breaks three cross-module callbacks
  and throws away a working module for no gain over converting it.

## Conventions that apply to all of this

Standing rules for this lab, recorded here because they otherwise live
only in conversation.

- **"automation orchestrator", lower case.** Never "Ansible Automation
  Orchestrator". "AO" is fine in comments and code, not in
  student-facing prose.
- **No em dashes anywhere**, prose or comments. That is codepoint
  U+2014. Grep for it before calling anything done. Do not paste the
  literal character into this file, not even as an example, or the
  check trips on its own rule.
- **STEPS, not NODES**, in student-facing content. The product calls
  them steps.
- **AAP must never sound lacking.** Automation orchestrator adds to
  AAP; it does not compensate for it. The Why section was rewritten
  several times over exactly this.
- **Every module gets a `solutions` TIP** telling the student where the
  finished reference copy lives.
- **The recording is the source of truth.** If the prose and the figure
  disagree, the figure wins, or the prose gets rewritten to match what
  the student will actually see.
- **Figures are referred to by ordinal position on the rendered page**,
  not by filename. "Figure 11" means the eleventh image, whatever it is
  called.
- **Roger commits and pushes by hand.** Do not commit, do not push, do
  not open PRs unless asked.
- `tools/*.shots` and `shots-review/` are gitignored on purpose.
  `tools/shot.py`, `tools/box-png.sh` and `tools/ao-extra-vars` are
  tracked.

### Screenshot tooling

- `tools/shot.py` cuts figures from a recording and draws the callout
  boxes as it cuts. Subcommands: `probe`, `fit`, `grab`, `batch`,
  `sheet`. `BOX_COLOR = "#EE0000"`, `BOX_THICKNESS = 4`.
- `tools/module-03.shots` is the cut list: one line of
  `<seconds> <name> <x,y,w,h ...>`. Fractional seconds are legal and
  sometimes necessary.
- `tools/box-png.sh SRC DST x,y,w,h ...` boxes a hand-taken screenshot
  in the same red at the same weight. Coordinates are in the source
  image's own pixels, not 1920x1080. Never run it over its own output.
- Measure box coordinates off the pixels. Boxes eyeballed from a
  contact sheet have been wrong every time.
- Antora build:
  `rm -rf www && npx antora site.yml`. The `rm -rf www` is mandatory;
  Antora does not clean its output.

## Unrelated items still outstanding

Carried forward so they are not lost:

- Four tracked `.DS_Store` files reached `main` in the merge. Clear with
  `git rm --cached`; they are already in `.gitignore` but were committed
  before the rule existed.
- Module 04: `./ao-extra-vars` versus `ao-extra-vars` on PATH. The page
  says `./ao-extra-vars` to match the screenshot, which contradicts the
  plan to install it on PATH. Figure and text must agree either way.
- Module 04 *What You Learned*: whether the bullet beginning "An extra
  variables expression is a *reference into the graph*" should stay now
  that the validation-error moment it taught has been removed. The MOTD
  rework does not give it a second home, since that module passes three
  expressions and no literals, so this is still open.
- `index.adoc` advertises six modules; only 02 through 05 have pages.
- `publishing-house/spec.yaml` still describes the old four-module
  structure and says "nodes" rather than STEPS.
- `ph-check.py` has never been run against these modules.
- Em dashes remain in the `.gitignore` comment, a `workload.yml`
  comment, and the `tools/box-png.sh` header.
- The terminal tab is named `">_ terminal"` in `ui-config.yml` while
  module 04 line 260 says "Switch to the *Terminal* tab". Pre-existing
  mismatch, worth fixing in one place.
- The RHDP catalog item's git ref lives in agnosticv, not here. Worth
  confirming whether it points at `main` now that content has landed.
