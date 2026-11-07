"""Catalog of the cold-chain supply and logistics domain.

The model tracks stock, shipments and time spent outside refrigeration.
It does not judge product safety: units are counted as *discarded* when
their exposure exceeds a tolerance that the user sets.
"""

from ..spec import DomainSpec, EntityType, EventType, FieldSpec, InterventionType, MetricDef, RelationshipType

INVENTORY = FieldSpec("inventory", "Starting stock", kind="integer", unit="units", min=0)
REORDER = FieldSpec("reorder_point", "Reorder at", kind="integer", unit="units", min=0,
                    help="When stock on hand plus stock on order falls to this level, an order is placed.")
ORDER_QTY = FieldSpec("order_quantity", "Order size", kind="integer", unit="units", min=1)
HOLDING = FieldSpec("holding_cost", "Holding cost", unit="per unit per hour", min=0, default=0.01)
BACKUP = FieldSpec("backup_power_hours", "Backup power", unit="hours", min=0, default=0,
                   help="How long refrigeration keeps running on backup during a power outage.")


def _stock(type_: str, label: str, short: str, color: str, inventory: int, reorder: int, qty: int,
           backup: float, description: str, demand: float | None = None) -> EntityType:
    fields = []
    if demand is not None:
        fields.append(FieldSpec("demand_rate", "Demand", unit="units/hour", min=0, default=demand,
                                help="Average customer demand per hour (random, Poisson). Unmet demand is lost."))
    fields += [FieldSpec(**{**INVENTORY.__dict__, "default": inventory}),
               FieldSpec(**{**REORDER.__dict__, "default": reorder}),
               FieldSpec(**{**ORDER_QTY.__dict__, "default": qty}),
               HOLDING, FieldSpec(**{**BACKUP.__dict__, "default": backup})]
    return EntityType(type_, label, short, color, tuple(fields), description)


COLDCHAIN_SPEC = DomainSpec(
    name="cold_chain",
    label="Cold-chain logistics",
    description="Refrigerated supply network: suppliers, cold warehouses, distribution centres and stores. "
                "Explore outages, refrigeration failures, route closures and demand spikes.",
    time_unit="hours",
    entity_types=(
        EntityType("supplier", "Supplier", "SU", "#E9B85A", (
            FieldSpec("lead_time", "Dispatch lead time", unit="hours", min=0, default=24,
                      help="Time from order to dispatch. Suppliers never run out."),
        ), "Produces stock on order."),
        _stock("warehouse", "Cold warehouse", "WH", "#8FB8E0", 2000, 800, 1200, 4, "Large refrigerated store."),
        _stock("distribution", "Distribution centre", "DC", "#CFA6E6", 600, 250, 400, 2, "Regional cross-dock."),
        _stock("store", "Store", "ST", "#7CD1AB", 120, 60, 100, 0, "Sells to customers.", demand=4),
    ),
    relationship_types=(
        RelationshipType("ships_to", "Ships to", "A route stock can travel along (source -> target).", "solid", (
            FieldSpec("travel_time", "Travel time", unit="hours", min=0, default=6),
            FieldSpec("cost_per_unit", "Transport cost", unit="per unit", min=0, default=0.5),
            FieldSpec("refrigerated", "Refrigerated", kind="boolean", default=True,
                      help="Off: every hour on this route counts as exposure."),
        )),
    ),
    event_types=(
        EventType("demand_spike", "Demand spike", "More customers at a store.", severity_label="Demand multiplier"),
        EventType("power_outage", "Power outage", "Refrigeration at a site stops once backup power runs out."),
        EventType("reefer_failure", "Refrigeration failure", "Shipments on a route are exposed while it lasts.",
                  target="relationship"),
        EventType("route_closure", "Route closure", "No new shipments can use the route; orders reroute.",
                  target="relationship"),
        EventType("supplier_delay", "Supplier delay", "The supplier takes longer to dispatch.",
                  severity_label="Lead-time multiplier"),
    ),
    intervention_types=(
        InterventionType("set_attribute", "Change a site setting", "e.g. more safety stock or backup power"),
        InterventionType("set_dependency_attribute", "Change a route setting"),
        InterventionType("set_parameter", "Change a system parameter"),
        InterventionType("add_component", "Add a site"),
        InterventionType("remove_component", "Remove a site"),
        InterventionType("add_dependency", "Add a route"),
        InterventionType("remove_dependency", "Remove a route"),
    ),
    metrics=(
        MetricDef("fill_rate", "Fill rate", "higher", format="percent",
                  description="Share of customer demand that was met."),
        MetricDef("lost_sales", "Lost sales", "lower", "units", "count", "Demand that could not be met."),
        MetricDef("stockout_time", "Stockout time", "lower", "store-hours", "duration",
                  "Hours stores spent with no stock, added over stores."),
        MetricDef("units_discarded", "Units discarded", "lower", "units", "count",
                  "Units whose exposure exceeded the tolerance you set."),
        MetricDef("discard_rate", "Discard rate", "lower", format="percent",
                  description="Discarded units as a share of units sold or discarded."),
        MetricDef("exposed_unit_hours", "Exposure", "lower", "unit-hours",
                  description="Units x hours spent without refrigeration."),
        MetricDef("on_time_rate", "On-time deliveries", "higher", format="percent",
                  description="Deliveries that arrived no later than planned (fastest route, no delays)."),
        MetricDef("mean_delivery_time", "Mean delivery time", "lower", "hours", "duration"),
        MetricDef("reroutes", "Delayed or rerouted orders", "lower", format="count"),
        MetricDef("transport_cost", "Transport cost", "lower", format="money"),
        MetricDef("holding_cost", "Holding cost", "lower", format="money"),
        MetricDef("discard_cost", "Discard cost", "lower", format="money",
                  description="Units discarded x unit value."),
        MetricDef("cost", "Intervention cost", "lower", format="money"),
        MetricDef("total_cost", "Total cost", "lower", format="money",
                  description="Transport + holding + discard + intervention cost."),
    ),
    risk_metric="lost_sales",
    default_objectives=(("fill_rate", 3.0), ("units_discarded", 2.0), ("total_cost", 1.0), ("on_time_rate", 1.0)),
    assumptions=(
        "Branchpoint does not judge product safety. 'Discarded' means exposure exceeded the tolerance you "
        "entered; it is not a statement that the product is unsafe.",
        "Demand is random (Poisson) at each store, checked every hour; unmet demand is lost, not back-ordered.",
        "Each site reorders a fixed order size when stock on hand plus on order falls to its reorder point "
        "(an (s, Q) policy). Orders come from the site that can deliver fastest over open routes (Dijkstra), "
        "using stock that is on hand, or from a supplier.",
        "Shipments follow the route chosen when they leave; a closure only affects shipments that have not left. "
        "Stock is sold oldest first.",
        "Exposure: during a power outage, after backup power runs out, every unit on site is exposed; during a "
        "refrigeration failure, shipments on that route are exposed; on unrefrigerated routes the whole trip counts.",
        "Each store's demand uses its own random stream, so every branch sees the same customers.",
        "All quantities and costs are illustrative inputs, not real data.",
    ),
    parameters=(
        FieldSpec("max_excursion_hours", "Exposure tolerance", unit="hours", min=0, default=2,
                  help="Units exposed for longer than this are counted as discarded. This is your rule."),
        FieldSpec("unit_value", "Unit value", unit="per unit", min=0, default=10,
                  help="Used for the discard cost."),
    ),
    default_until=168.0,
    edge_meaning="The arrow shows the direction stock travels.",
)
