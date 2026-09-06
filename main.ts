/**
 * Resolution Proof
 *
 * Checks whether a public prediction market has a decisive value at a caller-supplied JSON source.
 *
 * @rote-frontmatter
 * ---
 * name: resolution-proof
 * description: Validates, fetches, evaluates, and verifies a caller-supplied public JSON resolution source. Returns READY, WAIT, AMBIGUOUS, or BLOCKED without trading or claiming the source is official.
 * source: https://iamaanahmad.github.io/delphi-agent/competition-record.html
 * metadata:
 *   rote_version: 0.80.0
 *   version: 0.1.0
 *   status: released
 *   kind: atomic
 *   flow_type: sequential
 *   execution_model: steps_with_presentation
 *   format: typescript
 *   requires_sessions: false
 *   contract:
 *     atomic: true
 *     input:
 *       type: none
 *     output:
 *       format: json
 *       destination: stdout
 *     composable: true
 *   discoverability:
 *     tags:
 *     - prediction-markets
 *     - resolution
 *     - evidence
 *     - read-only
 * parameters:
 * - name: market_question
 *   param_type: string
 *   required: true
 *   description: The market question being checked
 * - name: resolution_rule
 *   param_type: string
 *   required: true
 *   description: The caller-supplied resolution rule, recorded for context but not parsed
 * - name: source_url
 *   param_type: string
 *   required: true
 *   description: The caller-supplied public HTTPS JSON source, or fixture://ready for the packaged demo
 * - name: json_pointer
 *   param_type: string
 *   required: true
 *   description: RFC 6901 JSON Pointer for the decisive value
 * - name: expected_value
 *   param_type: string
 *   required: true
 *   description: Expected scalar value, compared without case differences
 * - name: pending_values
 *   param_type: string
 *   required: false
 *   default: pending,tbd,unknown,not yet available
 *   description: Comma-separated values that mean the official result is not final
 * - name: receipt
 *   param_type: string
 *   required: false
 *   default: none
 *   valid_values:
 *   - none
 *   - write
 *   description: Set to write to create the declared local receipt
 * - name: receipt_path
 *   param_type: string
 *   required: false
 *   default: resolution-proof-receipt.json
 *   description: Workspace-relative path for the optional local receipt
 * presentation_fixtures:
 *   verify_result: resources/presentation-fixtures/check_resolution/fixture.yaml
 * steps:
 *   validate_inputs:
 *     type: process.exec
 *     timeout_ms: 5000
 *     argv:
 *     - python3
 *     - '@resource{resolution_proof.py}'
 *     - validate
 *     - $market_question
 *     - $resolution_rule
 *     - $source_url
 *     - $json_pointer
 *     - $expected_value
 *     - $pending_values
 *   fetch_source:
 *     type: process.exec
 *     depends_on:
 *     - validate_inputs
 *     timeout_ms: 20000
 *     argv:
 *     - python3
 *     - '@resource{resolution_proof.py}'
 *     - fetch
 *     - $source_url
 *     - '@resource{fixtures/ready.json}'
 *   evaluate_resolution:
 *     type: process.exec
 *     depends_on:
 *     - fetch_source
 *     timeout_ms: 5000
 *     argv:
 *     - python3
 *     - '@resource{resolution_proof.py}'
 *     - evaluate
 *     - $market_question
 *     - $resolution_rule
 *     - $source_url
 *     - $json_pointer
 *     - $expected_value
 *     - $pending_values
 *     - '@fetch_source{.stdout.text}'
 *   verify_result:
 *     type: process.exec
 *     depends_on:
 *     - evaluate_resolution
 *     timeout_ms: 5000
 *     argv:
 *     - python3
 *     - '@resource{resolution_proof.py}'
 *     - verify
 *     - '@evaluate_resolution{.stdout.text}'
 *   write_receipt:
 *     type: process.exec
 *     depends_on:
 *     - verify_result
 *     timeout_ms: 5000
 *     execution:
 *       mode: deferred
 *       condition:
 *         compare:
 *           left:
 *             param: receipt
 *           op: eq
 *           right: write
 *     argv:
 *     - python3
 *     - '@resource{resolution_proof.py}'
 *     - write
 *     - '@verify_result{.stdout.text}'
 *     - $receipt
 *     - $receipt_path
 *     capture:
 *       files:
 *       - label: receipt
 *         path: $receipt_path
 * ---
 */

const { FlowOutput, isProcessExecBody, loadPresentationContext, stepName } =
  await import("__ROTE_PRESENTATION_SDK__");

const out = new FlowOutput();
const ctx = await loadPresentationContext();
const observation = ctx.step(stepName("verify_result"));

if (
  observation.outcome.status !== "completed" &&
  observation.outcome.status !== "restored"
) {
  const reason = observation.outcome.status === "blocked"
    ? "Resolution verification was blocked by an upstream failure."
    : "Resolution verification failed before it produced a complete result.";
  out.human(`# BLOCKED: ${String(ctx.params.market_question)}\n\n${reason}`);
  out.summary(`BLOCKED: ${reason}`);
  out.result({
    run_id: ctx.run.run_id,
    status: "BLOCKED",
    market_question: String(ctx.params.market_question),
    reason,
  });
} else {
  const body = observation.outcome.output.body;

  if (!isProcessExecBody(body)) {
    throw new Error("verify_result did not record a process.exec observation");
  }

  const exit = body.status.exit;
  if (exit.kind !== "code" || exit.code !== 0) {
    throw new Error(
      `Resolution verification failed: ${
        body.stderr?.text ?? "no diagnostic captured"
      }`,
    );
  }

  const stdout = body.stdout?.text;
  if (stdout === undefined) {
    throw new Error("verify_result captured no stdout");
  }
  if (body.stdout?.truncated === true) {
    const reason =
      "Resolution verification output was truncated and is incomplete.";
    out.human(`# BLOCKED: ${String(ctx.params.market_question)}\n\n${reason}`);
    out.summary(`BLOCKED: ${reason}`);
    out.result({
      run_id: ctx.run.run_id,
      status: "BLOCKED",
      market_question: String(ctx.params.market_question),
      reason,
    });
  } else {
    let result: Record<string, unknown>;
    try {
      const parsed = JSON.parse(stdout);
      if (
        typeof parsed !== "object" || parsed === null || Array.isArray(parsed)
      ) {
        throw new Error("result was not an object");
      }
      result = parsed as Record<string, unknown>;
    } catch (error) {
      throw new Error(`verify_result returned invalid JSON: ${String(error)}`);
    }

    const status = result.status;
    if (!["READY", "WAIT", "AMBIGUOUS", "BLOCKED"].includes(String(status))) {
      throw new Error(
        `verify_result returned an invalid status: ${String(status)}`,
      );
    }

    const question = typeof result.market_question === "string"
      ? result.market_question
      : "Unnamed market";
    const reason = typeof result.reason === "string"
      ? result.reason
      : "No reason returned";
    const actual = Object.prototype.hasOwnProperty.call(result, "actual_value")
      ? `\n\nObserved value: \`${JSON.stringify(result.actual_value)}\``
      : "";
    const receipt = ctx.params.receipt === "write"
      ? `\n\nReceipt: \`${String(ctx.params.receipt_path)}\``
      : "";

    out.human(`# ${status}: ${question}\n\n${reason}${actual}${receipt}`);
    out.summary(`${status}: ${reason}`);
    out.result({ run_id: ctx.run.run_id, ...result });
  }
}
