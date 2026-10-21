# WMS interface specification

## Message transport

Order lines are exchanged as JSON messages over a REST API. The WMS sends new order lines with
POST /orders; the automation system confirms each pick with a callback to the WMS within two
seconds.

## Error handling

A message the automation system cannot process is answered with HTTP 422 and a reason code.
The WMS must retry transient failures with exponential backoff, starting at one second and
capped at one minute.

## Inventory reconciliation

Once per night the automation system sends a full stock snapshot. Differences above
0.5 percent of a SKU's quantity raise a reconciliation task for the inventory controller.
