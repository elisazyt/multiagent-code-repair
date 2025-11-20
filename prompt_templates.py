SYSTEM_DESCRIPTION = """
TASK:
Generate a patch for the buggy Java code.

Do not assume any methods exist unless they are explicitly called or defined.
If the patch calls a new method, it should be explicitly defined and fully implemented,
without any placeholder logic.

All buggy locations should be fixed. Refactoring and commenting should not be considered fixes.

The user cannot modify your code, so do not suggest incomplete code which requires others to modify.
Suggest the full code instead of partial code or code changes.

RETURN FORMAT:
For every single bug location, return the patch for the entire buggy node in markdown format, with the following syntax:
```java
[patch]
```
Do not use markdown format for anything that is not a patch. Only use markdown format for the patches.
The number of markdown blocks should equal the number of bug locations.
The patch should contain the full code for the bug location.
"""


BASIC_PROMPT = "Carry out the given task given by the system description."


API_PROMPT = f"""
You are an agent that retrieves and uses any necessary APIs to carry out the task given by the system
description. Some bug fixes don't require API usage, so you should first analyze the context and determine
if new APIs are needed.

Whenever possible, use the retrieved APIs instead of creating your own functions."""


CONTEXT_PROMPT = "" # TODO: add context prompt