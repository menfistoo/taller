#!/usr/bin/env python
"""A fake `claude` for tests.

Records the argv it was given to $STUB_CLAUDE_ARGV and answers from
$STUB_CLAUDE_RESPONSE, so a test can assert on the generated argument list —
which spec 15.1 requires, because the argument list *is* the mechanism spec
9.7's guarantee rests on.
"""

import json
import os
import sys


def main() -> int:
    argv_path = os.environ.get("STUB_CLAUDE_ARGV")
    if argv_path:
        with open(argv_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(sys.argv[1:]) + "\n")

    if os.environ.get("STUB_CLAUDE_FAIL_EXIT"):
        sys.stderr.write("stub failure\n")
        return int(os.environ["STUB_CLAUDE_FAIL_EXIT"])

    if os.environ.get("STUB_CLAUDE_BAD_JSON"):
        sys.stdout.write("this is not json")
        return 0

    payload = os.environ.get("STUB_CLAUDE_RESPONSE")
    if payload:
        sys.stdout.write(payload)
        return 0

    sys.stdout.write(json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "session_id": "11111111-2222-3333-4444-555555555555",
        "result": "ok",
        "total_cost_usd": 0.01,
        "usage": {
            "input_tokens": 10,
            "cache_creation_input_tokens": 20,
            "cache_read_input_tokens": 30,
            "output_tokens": 40,
        },
        "modelUsage": {
            "claude-sonnet-5": {
                "inputTokens": 10,
                "cacheCreationInputTokens": 20,
                "cacheReadInputTokens": 30,
                "outputTokens": 40,
            }
        },
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
