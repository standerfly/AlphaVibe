# AutoCharge FreeCharge Codebase Alignment Addendum

**Source ID:** SRC-002
**Feature Slug:** autocharge-freecharge
**Source Date:** 2026-05-12
**Source Type:** Codebase reality check against current project implementation

## Purpose

This addendum records where `raw/autocharge_freecharge_spec.md` needs to be interpreted or corrected to match the current FVS-VAS codebase. It does not replace the original source. Use this addendum as the current-code baseline when drafting `product-spec.md` and future Spec Kit inputs.

## Current Code Facts

### Order Status Storage

- The CPO order table/model stores the logical order status in `lxm_cpo_orders.status`, not `lxm_cpo_orders.order_status`.
- The current Go enum is `model.LxmCpoOrderStatus`.
- Current status values are:
  - `1` = `UnexpectedError`
  - `2` = `OwnerNotFound`
  - `3` = `NoBoundCards`
  - `4` = `Unpaid`
  - `5` = `FailedToPay`
  - `6` = `Paid`
  - `7` = `RefundRequested`
  - `8` = `Refunded`
  - `9` = `CancelRequested`
  - `10` = `Canceled`
  - `11` = `NoCharge`
  - `12` = `NoChargePromotion`
- `FreeCharge` and `EligibilityPending` do not currently exist as enum values.
- There is an existing `NoChargePromotion` status with app-facing promotion copy. PO/TPM must decide whether FreeCharge reuses `NoChargePromotion` or introduces distinct statuses.

### Existing 202 ValidateCar Behavior

- 202 is `POST /ext/lxm-cpo/api/v1/validate/car`.
- It creates `lxm_cpo_request_logs` with `api_type = 202`.
- It validates request fields, CPO authorization, vehicle owner lookup, bound card availability, card expiry, AutoCharge enabled status, and outstanding payments.
- If no bound card is available, 202 returns the existing no-bound-card response (`EC202`).
- If the selected bound card is expired, 202 returns the existing failed-payment response (`EC207` / `FailedToPay`) and sends the existing notification.
- 202 does not perform a live card authorization transaction; live authorization happens later only through the payment flow.
- It does not create an `lxm_cpo_orders` record.
- It does not start payment or issue invoice.

### Existing 203 Checkout Behavior

- 203 is `POST /ext/lxm-cpo/api/v1/checkout`.
- It creates `lxm_cpo_request_logs` with `api_type = 203`.
- `requestId` duplicate and `carId + startTime + endTime` duplicate detection return LXM CPO duplicate code `EC215`; the current implementation does not return the existing checkout result.
- `startTime`, `endTime`, and `requestTime` are JSON strings containing epoch milliseconds and are parsed with `time.UnixMilli`.
- Checkout `amount` is validated as `gte=0`; negative amount is invalid input. Only `amount == 0` can become `NoCharge`.
- The order model keeps both `car_id` and `vehicle_id`. `car_id` comes from the CPO/LXM request. `vehicle_id` is the UUID returned from TSP or copied from the 202 request log.

### Existing Payment And Invoice Entry Points

- Normal 203 Checkout starts the async payment pipeline only when the computed order status is `Unpaid`.
- Live credit-card authorization happens after 203 Checkout for eligible `Unpaid` orders through `EcPayService.CreatePaymentWithCardId`.
- If ECPay authorization fails in the payment flow, the order is updated to `FailedToPay` under the existing behavior.
- `authPaymentForOrder` itself does not currently reject non-`Unpaid` statuses; it assumes callers have already selected an eligible order.
- `issueInvoiceForPayment` checks the payment state before issuing invoice, but does not check the CPO order status.
- `RedoPaymentInvoice` can reprocess `OwnerNotFound`, `NoBoundCards`, `Unpaid`, and `FailedToPay` orders and can create payment/invoice later. It explicitly exits early for `NoCharge` and `NoChargePromotion`.
- FreeCharge implementation must add explicit guards in every entry point that can create payment or invoice, not only in the initial 203 Checkout branch.

### Existing Promotion-Oriented Flow

- A service method `SaveNoChargePromotionOrder` exists and creates `NoChargePromotion` orders.
- No external route to `SaveNoChargePromotionOrder` was found in the current handler/server registration.
- Current app order display adds promotion comments only when status is `NoChargePromotion`.

### Missing Current Capabilities For FreeCharge

- No current Retail FreeCharge eligibility HTTP client/config was found.
- No current `/promotion/api/v1/freecharge/eligibility` integration was found.
- No current `EligibilityPending` retry worker was found.
- Existing abnormal reports and redo jobs do not explicitly detect "FreeCharge or pending order has payment/invoice leakage"; they only cover current status/payment/invoice abnormal categories.

## Required Corrections To SRC-001 Interpretation

1. Replace `lxm_cpo_orders.order_status` wording with `lxm_cpo_orders.status` wherever describing the current database/model.
2. Treat `FreeCharge` and `EligibilityPending` as proposed logical statuses, not current implementation facts.
3. Resolve CL-002 by choosing physical status values. Options include:
   - Reuse current `NoChargePromotion = 12` for FreeCharge and add only a pending status.
   - Add distinct `FreeCharge` and `EligibilityPending` enum values after `NoChargePromotion`.
4. Preserve current duplicate behavior unless PO/TPM intentionally changes it: duplicate checkout currently returns `EC215`, not the existing result payload.
5. Correct the amount rule: `amount == 0` remains `NoCharge`; `amount < 0` is invalid input.
6. Confirm Retail `charging_time` format. Current 203 `startTime` is epoch milliseconds; SRC-001 examples use RFC3339 UTC.
7. Preserve the current credit-card validation boundary: FreeCharge v1 must not relax 202 bound-card, card-expiry, AutoCharge-enabled, or outstanding-payment checks. A 202 FreeCharge precheck that lets eligible vehicles start without those existing checks remains future scope unless PO/TPM reopens it.
8. Add FreeCharge and pending guards to:
   - initial 203 checkout payment dispatch,
   - `authPaymentForOrder`,
   - `issueInvoiceForPayment`,
   - `RedoPaymentInvoice`,
   - scheduled redo,
   - abnormal reporting and duplicate payment/invoice reporting.
9. Update app/admin status exposure once physical statuses are chosen, including Chinese/English status names and app-facing promotion/freecharge copy.

## Code References Used For This Addendum

- `internal/model/lxm_cpo_order_model.go`
- `internal/model/lxm_cpo_request_log_model.go`
- `internal/dto/lxm_cpo_dto.go`
- `internal/service/lxm_cpo_service.go`
- `internal/service/ecpay_service.go`
- `internal/util/ecpay_util.go`
- `internal/repository/lxm_cpo_order_repository.go`
- `internal/repository/reports_repository.go`
- `cmd/server/main.go`
- `diagrams/202_validate_car_flow.md`
- `diagrams/203_checkout_flow.md`
- `diagrams/redo_lxm_cpo_order_payment_invoice_flow.md`
