# PortShift app screens

Screenshots of the app in `app/`, built from the Figma Make design:
https://www.figma.com/make/cgRfeOzVsBuuJHSI8U6gdJ/PortShift-Logistics-Dashboard

The same screenshots are laid out as named frames, iterations first, in a Figma file on the track lead's account:
https://www.figma.com/design/54jCELYjFeJPS78UUfOOv1

These are screenshots of the running app, not designs drawn in Figma. They were taken at 1440 px wide on the demo fixtures (demo fleet for an example UK and Europe operator, sample disruptions).

## Current screens

| File | Shows |
|---|---|
| `01-live-operations.png` | Live operations: left navigation, vector map opening on the UK and north-west Europe, legend that filters by risk level and by mode, shipment list sorted by urgency |
| `02-possible-disruptions.png` | Possible disruptions: one card per disruption with when it starts, shipments hit and estimated cost, sortable and filterable |
| `03-shipment-details.png` | Opening a disruption: the shipment sidebar on Shipment details, with evidence, why that risk level, the journey line with progress and stop times, and citations |
| `04-ask-agent.png` | Ask agent: "lower the risk but keep the cost low" turned into a setting, options with a Submit button each |
| `05-reschedule.png` | Reschedule: presets, risk level with its description, options, and the new ETA, cost and stop times for the picked one |
| `06-plan-a-shipment.png` | Plan a shipment: Edinburgh to Brussels, with suggested routes by road and ferry, sea and air |
| `07-plan-ship-then-truck.png` | Plan a shipment: a ship leg chained with a truck leg, flagged by the Felixstowe closure |
| `08-insights.png` | Insights: fleet statistics |
| `09-dark-theme.png` | Dark theme, the look of the original Figma design |
| `10-planned-shipments.png` | Planned shipments (15 Nov): a plan kept from Plan a shipment, with status, cost, risk, stops and Show on map; the dashed route on the map |
| `11-fleet.png` | Fleet (15 Nov): the operator's own vehicles with status, depots on the map |
| `12-truck-route-on-roads.png` | S-1005 opened (15 Nov): the truck route now follows real roads round the Thames estuary and through the Channel Tunnel |

## Iterations (14 Nov)

Each is the same screen (shipment S-1005 opened) at an earlier version of the app, taken by checking out that commit.

| File | Version | What changed |
|---|---|---|
| `iterations/01-triage-view.png` | PR #22 | First operator view: events on the map, stats strip, permanent right sidebar |
| `iterations/02-decluttered.png` | PR #24 | Less on screen: risk chips on the map instead of the strip, shipment detail replaces the list |
| `iterations/03-figma-language-light.png` | PR #26 | Figma design language in a light theme; limits control, plan options, insights |
| `iterations/04-figma-make-layout.png` | PR #28 | Layout of the Figma Make design: full-bleed vector map, floating panels, slide-in shipment panel |
| `iterations/05-left-nav-three-part-sidebar.png` | PR #33 | Left navigation, Possible disruptions, sidebar with Shipment details / Ask agent / Reschedule |
| current screens above | PRs #38, #40 | UK and Europe demo data with a demo clock, filter by mode, Plan a shipment |

What the app keeps from the Figma design: wordmark, view title and risk legend on the map, floating panels, the shipment panel sliding in from the right, the focused-route chip, the agent activity card (shown only when the monitor has recorded a run).

What the app changes: light theme by default, larger type, navigation with names instead of an icon-only rail, a shipment list that is always there, evidence basis in place of a confidence percentage, options from the agent in place of one fixed scenario.

All costs on these screens are estimates at illustrative rates. Nothing is booked.
