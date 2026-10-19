# ocp4_workload_ao_lab_tools

Installs the lab's helper scripts into the student's home directory on the
bastion, executable, so the Showroom terminal tab can run them by name.

Today that is one script, `ao-extra-vars`, which module 04 runs to read the
*Notify Chatroom* extra variables out of a workflow instead of copying them out
of the *Input* panel by hand.

## What this role does

**Provision (`ACTION: provision`)**

1. Adds the bastion to the in-memory inventory from `bastion_ansible_host`,
   `bastion_ansible_user` and `bastion_ansible_ssh_pass` — the same three
   variables `infra_add_nodes` asserts
2. Checks that the bastion has a python3 that can import what the scripts need
3. Copies each script in `ocp4_workload_ao_lab_tools_scripts` from this role's
   `files/` to `/home/lab-user/`, owned by `lab-user`, mode `0755`

**Destroy (`ACTION: destroy`)**

Nothing. The scripts are plain files in a home directory and go away with the
bastion.

## Where the scripts live

The real files are in this role's `files/` directory. `tools/ao-extra-vars` in
the repository root is a symlink to `files/ao-extra-vars`, so the script can
still be run from a checkout the way it always could, and there is only one
copy to keep current.

Do not invert this. A symlink pointing the other way would leave the collection
with a link to a target outside its own root, which does not survive
`ansible-galaxy collection build`.

## Requirements

**Collections**

- None beyond `ansible.builtin`

**Variables** (set by whatever provisions the bastion)

| Variable | Purpose |
| --- | --- |
| `bastion_ansible_host` | Bastion address |
| `bastion_ansible_user` | SSH user on the bastion |
| `bastion_ansible_ssh_pass` | SSH password for that user |
| `bastion_ansible_port` | Optional, defaults to 22 |

The SSH user needs passwordless sudo, since the copy sets `owner` and `group`
on a file in another account's home directory. If the bastion user *is*
`lab-user`, that `become` is a no-op in practice but still runs.

## Defaults worth knowing

| Variable | Default | Notes |
| --- | --- | --- |
| `ocp4_workload_ao_lab_tools_user` | `lab-user` | The account the terminal tab logs in as |
| `ocp4_workload_ao_lab_tools_dest_dir` | `/home/lab-user` | Changing this breaks `./ao-extra-vars` in module 04 |
| `ocp4_workload_ao_lab_tools_scripts` | `[ao-extra-vars]` | Add to the list rather than writing another copy task |
| `ocp4_workload_ao_lab_tools_mode` | `0755` | |
| `ocp4_workload_ao_lab_tools_host_key_checking` | `accept-new` | See below |
| `ocp4_workload_ao_lab_tools_known_hosts` | `~/.ssh/known_hosts` | Real file, not `/dev/null` |

## A note on the bastion host key

The connection is password-authenticated, so the host key is what stands
between the bastion password and anything that can answer on that address.
`accept-new` pins the key on first contact and refuses a *changed* key
afterwards; if the deploy has already reached this bastion, which it usually
has by the time workloads run, the key is already in `known_hosts` and the
connection is verified outright.

`infra_add_nodes` uses `StrictHostKeyChecking=no` with
`UserKnownHostsFile=/dev/null` for its ProxyCommand, which verifies nothing on
any connection. This role deliberately does not copy that. Switching to
key-based auth with `ansible_ssh_private_key_file` would be better still, but
the variables this role is handed are password-based.

## A note on the destination

Module 04 tells the student to run `./ao-extra-vars`, and the figure under that
step shows exactly that. Installing to `/usr/local/bin` instead would put the
script on `PATH` and make the page and its figure both wrong. If that trade is
ever worth making, the page text and the screenshot have to change together.
