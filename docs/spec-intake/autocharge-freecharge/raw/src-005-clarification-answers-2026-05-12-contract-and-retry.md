# AutoCharge FreeCharge Contract And Retry Clarification

**Source ID:** SRC-005
**Source Date:** 2026-05-12
**Source Type:** PO/TPM clarification answer from chat
**Feature Slug:** autocharge-freecharge

## Answers Provided

1. The recommended decisions for CL-001, CL-003, and CL-005 are accepted for the current pre-spec baseline.
2. Business priority is P0 / launch-blocking for the planned 2026-06-10 stage campaign.
3. Acceptance evidence should be a durable PO/TPM record that confirms the product spec, supporting artifacts, and Spec Kit input split are acceptable.
4. Retail eligibility timeout is 3 seconds in the synchronous 203 Checkout path, with no inline retry during the request.
5. Pending retry runs every 5 minutes and stops after 12 attempts or after 60 minutes pending age, whichever comes first.
6. Pending alerting warns after 30 minutes and requires manual recovery after 60 minutes or 12 failed attempts.
7. v1 does not add a FreeCharge trace table. Pending age is based on the existing order timestamps, and retry evidence is based on scheduler/job logs linked by `order_id` and `request_id`.
8. Retail `charging_time` wire format is RFC3339 UTC string derived from the successful 202 ValidateCar request log `requestTime`.
9. Retail 4xx caused by missing or invalid vehicle UUID is not treated as not eligible and does not fall back to normal payment. It creates `EligibilityPending`, blocks payment and invoice, and requires alert/manual recovery.
10. FreeCharge and `EligibilityPending` 203 Checkout responses must preserve the current CPO/LXM checkout success contract: HTTP 200, code `00`, message `success`, and the existing response schema.
11. `data.amount` in the CPO/LXM checkout response remains the original checkout amount. The payment bypass is represented by internal order status and payment/invoice guards, not by changing the external response amount to zero.
12. Duplicate checkout preserves current `EC215` behavior.
13. The project must not change the existing 202 ValidateCar or 203 Checkout HTTP contract. Request paths, required fields, timestamp field semantics, HTTP status behavior, response code meanings, response body shape, and duplicate behavior must remain compatible with existing CPO/LXM integrations.
14. FreeCharge is an additive AutoCharge campaign behavior. It must not impact existing non-FreeCharge 202/203 functionality.

## Interpretation Notes

- The Retail eligibility API is a new side-call from AutoCharge and is not part of the CPO/LXM 202/203 HTTP contract.
- Existing CPO/LXM timestamp fields remain epoch-millisecond strings. Only the new Retail `charging_time` query value is converted to RFC3339 UTC.
- The product baseline can move out of clarification blocking after these decisions are applied, but `product-spec.md` still requires explicit final PO/TPM acceptance before it can be marked `Accepted`.
