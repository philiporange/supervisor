# Service diagnosis request

You are reading the repository of `{name}`, a service run by a process supervisor on a home server. It is producing errors. A cheap classifier judged this to be most likely a **{kind}** problem (probability {kind_probability:.2f}) that the repository itself could fix (probability {fixable:.2f}).

This is a read-only investigation. You cannot write files or run commands, and you must not try to. Your job is to diagnose the fault and plan the fix for a developer who will apply it later.

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

1. Read the code paths named in the output and decide whether this is genuinely a defect in this repository. Failures of other hosts, third-party APIs, disks, devices, or credentials are not code bugs.
2. Identify the root cause as precisely as the evidence allows, naming files and functions.
3. Propose the smallest correct change that fixes the root cause. Describe it concretely enough that a developer can apply it without re-investigating: which file, which function, what changes. Do not propose wrapping the error in try/except to hide it.

## Reply format

Keep the whole reply under 2500 characters. Use exactly these sections:

**Verdict**: one of `code_bug`, `dependency`, `external`, `environment`, `noise`, followed by one sentence.

**Root cause**: two to five sentences citing file paths and function names.

**Proposed fix**: a short numbered list of concrete edits.

**Confidence**: high, medium, or low, with the main uncertainty.
