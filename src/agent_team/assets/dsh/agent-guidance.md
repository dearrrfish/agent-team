# DeepSeek Harness compatibility

In a DSH session, follow the host's role and tool configuration and use the
instructions below as role guidance. DSH and its presets own dispatch and
subagent creation, `dsh.agentTeams` owns Team tasks, and `dsh-delivery` owns
single-task approvals, receipts, and acceptance. Treat a Team task ID as a
correlation reference. Apply the Agent Teams CLI workflow instructions below
only to CLI-owned work outside DSH.
