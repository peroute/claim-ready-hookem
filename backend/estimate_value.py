"""Value estimation module — DEFERRED TO V2.

In V1, per-item replacement values are entered by the claimant in the
frontend review step ("user verifies values and adds receipts before
submission"), not produced by this module. The packet template handles
`InventoryItem.estimated_value is None` by rendering an em-dash, so the
end-to-end pipeline runs and renders without this stage.

V2 plans for this module:

- For each item with `brand_recognized=True`, run a web search for the
  specific brand/model (e.g. "Lenovo Legion Slim 5 price"), parse top
  retailer results, and pick a median price.
- For items without a brand, fall back to a category-based average
  (e.g. electronics median, furniture median) trained from historical
  claim data or a static seed table.
- Cache lookups per (brand, model) to avoid redundant web calls across
  items and across claims.
- Populate `InventoryItem.estimated_value` and set
  `InventoryItem.value_source` to "web_lookup" or "user_input".

Until then, this module intentionally provides no public functions so
that callers (pipeline.py) skip it cleanly.
"""

# Intentionally no implementation. See module docstring for V2 plan.
