#!/usr/bin/env python3
"""
wan_throughput_graph.py - CheckMK graph template per WAN_Throughput

Definisce metriche rx_mbps / tx_mbps e un grafico combinato RX+TX.
Deploy: /omd/sites/monitoring/local/lib/python3/cmk_addons/plugins/nsec8_checks/graphing/

Compatibile con CheckMK 2.4+ (cmk.graphing.v1 API)
"""

from cmk.graphing.v1 import Title
from cmk.graphing.v1.graphs import Graph
from cmk.graphing.v1.metrics import Color, DecimalNotation, Metric, StrictPrecision, Unit

metric_rx_mbps = Metric(
    name="rx_mbps",
    title=Title("WAN RX"),
    unit=Unit(DecimalNotation("Mbit/s"), StrictPrecision(2)),
    color=Color.BLUE,
)

metric_tx_mbps = Metric(
    name="tx_mbps",
    title=Title("WAN TX"),
    unit=Unit(DecimalNotation("Mbit/s"), StrictPrecision(2)),
    color=Color.GREEN,
)

graph_wan_throughput = Graph(
    name="wan_throughput",
    title=Title("WAN Throughput"),
    simple_lines=[
        "rx_mbps",
        "tx_mbps",
    ],
)
