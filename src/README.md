# Source code

The monitor has not been implemented yet.

Initial implementation target:
- Accept a structured synthetic action record.
- Validate the record schema.
- Apply explicit path and operation policies without executing the requested action.
- Return a clear allow/block decision with a reason.
- Support deterministic unit tests.

Keep policy decisions separate from file operations. The first version should classify proposed actions only; it should not run shell commands or connect to an external AI service.
