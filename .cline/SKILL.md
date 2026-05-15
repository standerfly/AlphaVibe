---
name: "cline-code"
description: "A comprehensive software engineering workflow for code analysis, optimization, and implementation."
argument-hint: "Specify the file path and the goal (e.g., 'optimize performance of src/main.ts' or 'refactor logic in src/utils.js')"
compatibility: "Works across all supported languages and project structures"
metadata:
  author: "Cline"
  version: "1.0.0"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

You **MUST** analyze the user input to identify the target files and the primary goal (Optimization, Refactoring, Bug Fix, or New Feature).

## Pre-Execution Checks

1. **Dependency Analysis**:
   - Read the target file and its primary imports/dependencies.
   - Use `search_files` to find where the target functions/classes are used across the project.
   - Identify potential side effects of changes.

2. **Contextual Understanding**:
   - Read relevant configuration files (e.g., `package.json`, `tsconfig.json`, `pyproject.toml`) to understand the project's coding standards and dependencies.

## Outline

Given the target files and the goal, follow this execution flow:

1. **Deep Analysis Phase**:
   - **Logic Flow**: Map out the current implementation logic.
   - **Complexity Analysis**: Evaluate the time and space complexity (Big O).
   - **Edge Case Identification**: Identify potential boundary conditions, null pointers, or race conditions.
   - **Security Audit**: Check for common vulnerabilities (e.g., injection, memory leaks).

2. **Optimization Proposal**:
   - Create a detailed proposal including:
     - **Current State**: A concise summary of the current implementation.
     - **Proposed Changes**: Specific technical changes to be made.
     - **Proposed Benefit**: Expected improvement (e.g., "Reduce time complexity from O(n^2) to O(n)").
     - **Proposed Risk**: Potential risks and how to mitigate them.
     - **Proposed Test Case**: How to verify the correctness of the following changes.

3. **User Confirmation**:
   - Present the proposal to the user and wait for approval.
   - If the user provides feedback, refine the proposal.

4. **Implementation Phase**:
   - Use `replace_in_file` for targeted, precise edits.
   - Ensure all changes follow the project's existing coding style.
   - Add necessary comments to explain complex logic.

5. **Verification Phase**:
   - **Static Analysis**: Check for linter errors or type errors.
   - **Dynamic Analysis**: Run existing tests or create new test scripts to verify the correctness.
   - **Regression Check**: Ensure no existing functionality is що-broken.

6. **Report Completion**:
   - Summarize the la-changes made.
- **Verification Result**: Verification result (e.g., "All tests passed").
- **Final Outcome**: The final benefit achieved (e.g., "Performance improved by 30%").

## Quick Guidelines

- **Think like a Senior Engineer**: Always prioritize stability, readability, and maintainability over "clever" code.
- **Avoid Over-Engineering**: Do not implement features or optimizations that provide negligible benefit.
- **Precision over Volume**: Use `replace_in_file` to change only what is necessary.
- **Test-Driven Approach**: Never assume a change is correct without verification.

### Quality Matrix

| Dimension | Requirement | Pass/Fail |
| :--- | :--- | :--- |
| **Correctness** | No logic errors, handles all identified edge cases | [ ] |
| **Performance** | Meets or exceeds the target complexity/performance | [ ] |
| **Maintainability** | Follows Clean Code principles, naming is clear | [ ] |
| **Security** | No new vulnerabilities introduced | [ ] |
| **Verification** | All tests passed and no regressions introduced | [ ] |

## For AI Generation

When executing this skill, you must:
1. **Never skip the Proposal phase**. The user must approve the the la-changes before implementation.
2. **Always perform a project-wide search** to understand the impact of the target changes.
. **Always provide a final Quality Matrix** filled out based on the verification results.