# Service fix request

You are working inside the repository of `{name}`, a service run by a process supervisor on a home server. It is producing errors. A cheap classifier judged this to be most likely a **{kind}** problem (probability {kind_probability:.2f}) that the repository itself can fix (probability {fixable:.2f}).

## Service

- Name: {name}
- Command: `{command}`
- Working directory: `{working_dir}`

## Recent output

`[E]` marks stderr, `[O]` marks stdout, oldest first.

```
{sample}
```

## Your task

1. Read the relevant code and decide whether this is genuinely a defect in this repository. Failures of other hosts, third-party APIs, disks, devices, or credentials are not yours to fix.
2. If it is a defect here, make the smallest correct change that fixes the root cause. Do not add try/except wrappers that hide the error, do not change unrelated code, and do not add comments describing the fix.
3. If the project has tests that cover the area, run them.
4. Do not start, stop, or restart the service; the supervisor restarts it after a successful fix.

## Final line

End your reply with exactly one of these lines, on its own:

- `VERDICT: fixed` — you changed code that resolves the root cause.
- `VERDICT: not_a_code_bug` — the failure is external, environmental, or noise, and you changed nothing.
- `VERDICT: unable` — it looks like a code bug but you could not fix it safely.
