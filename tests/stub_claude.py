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

# Write UTF-8 bytes explicitly. Python's default stdout encoding on Windows is
# cp1252, so a stub using sys.stdout.write would mangle a non-ASCII payload
# before it ever reached the code under test - the same defect the test is there
# to catch, hidden in the test harness instead of the product.
def _out(text: str) -> None:
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def main() -> int:
    argv_path = os.environ.get("STUB_CLAUDE_ARGV")
    if argv_path:
        with open(argv_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(sys.argv[1:]) + "\n")

    # The informational flags `cli_probe` reads. The help text lists every flag
    # Taller knows, minus any a test hides, so `taller doctor` can be driven to
    # both verdicts without the real binary.
    if sys.argv[1:] == ["--version"]:
        _out(os.environ.get("STUB_CLAUDE_VERSION", "2.1.74 (Claude Code)") + "\n")
        return 0
    if sys.argv[1:] == ["--help"]:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
        from taller import cli_probe
        hidden = set(os.environ.get("STUB_CLAUDE_HIDE_FLAGS", "").split())
        flags = [f for f in [*cli_probe.REQUIRED_FLAGS, *cli_probe.OPTIONAL_FLAGS]
                 if f not in hidden]
        _out("Usage: claude [options]\n\nOptions:\n"
             + "".join(f"  {flag} <value>   stub\n" for flag in flags))
        return 0

    # Stands in for "this binary would have billed an API key": doctor's live
    # check must prove the dispatch succeeds with none in the environment.
    if os.environ.get("STUB_CLAUDE_REFUSE_API_KEY") and os.environ.get("ANTHROPIC_API_KEY"):
        sys.stderr.write("stub: ANTHROPIC_API_KEY reached the CLI\n")
        return 3

    # A dispatch that never answers, as a real CLI waiting on the network can.
    if os.environ.get("STUB_CLAUDE_HANG"):
        import time
        time.sleep(float(os.environ["STUB_CLAUDE_HANG"]))

    if os.environ.get("STUB_CLAUDE_FAIL_EXIT"):
        sys.stderr.write("stub failure\n")
        return int(os.environ["STUB_CLAUDE_FAIL_EXIT"])

    if os.environ.get("STUB_CLAUDE_BAD_JSON"):
        _out("this is not json")
        return 0

    payload = os.environ.get("STUB_CLAUDE_RESPONSE")
    if payload:
        _out(payload)
        # The real CLI exits non-zero on a failed turn and still prints its JSON.
        return int(os.environ.get("STUB_CLAUDE_EXIT", "0"))

    _out(json.dumps({
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
