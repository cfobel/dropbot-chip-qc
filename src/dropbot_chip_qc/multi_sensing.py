# -*- encoding: utf-8 -*-
'''
Quality control functions using DropBot multi-sensing.

Requires `dropbot>=2.2.0`.
'''
from __future__ import print_function, absolute_import
import itertools as it
import logging
import time

import dropbot as db
import dropbot.dispense
import dropbot.move
import functools as ft
import networkx as nx
import numpy as np
import pandas as pd
import trollius as asyncio
import winsound

from .single_drop import _run_test as _single_run_test


@asyncio.coroutine
def _run_test(signals, proxy, G, way_points, start=None,
              move_liquid=db.dispense.move_liquid):
    '''
    Signals
    -------

    The following signals are sent during the test:

    * ``test-start``; test has started:

      - ``route``: planned list of electrodes to visit consecutively
      - ``way_points``: contiguous list of waypoints, where test is routed as
        the shortest path between each consecutive pair of waypoints

    * ``electrode-success``; movement of liquid to electrode has
      completed:

      - ``source``: electrode where liquid is moving **from**
      - ``target``: electrode where liquid is moving **to**
      - ``start``: **start** time for electrode movement attempt
      - ``end``: **end** time for electrode movement attempt
      - ``attempt``: attempts required for successful movement

    * ``electrode-attempt-fail``; single attempt to move liquid to target
      electrode has failed:

      - ``source``: electrode where liquid is moving **from**
      - ``target``: electrode where liquid is moving **to**
      - ``start``: **start** time for electrode movement attempt
      - ``end``: **end** time for electrode movement attempt
      - ``attempt``: attempts required for successful movement

    * ``electrode-fail``; movement of liquid to electrode has failed:

      - ``source``: electrode where liquid is moving **from**
      - ``target``: electrode where liquid is moving **to**
      - ``start``: **start** time for electrode movement attempt
      - ``end``: **end** time for electrode movement attempt
      - ``attempt``: attempts made for electrode movement

    * ``electrode-skip``; skip unreachable electrode:

      - ``source``: electrode where liquid is moving **from**
      - ``target``: electrode where liquid is moving **to**

    * ``test-complete``; test has completed:

      - ``success_route``: list of electrodes visited consecutively
      - ``failed_electrodes``: list of electrodes where movement failed
      - ``success_electrodes``: list of electrodes where movement succeeded


    Returns
    -------
    dict
        Test summary including the same fields as the ``test-complete`` signal
        above.


    .. versionchanged:: 0.3
        Send the following signals: ``electrode-success``,
        ``electrode-attempt-fail``, ``electrode-fail``, ``test-complete``.
    .. versionchanged:: 0.3
        Rename results dictionary keys::
        - ``route`` -> ``success_route``, i.e., actual route taken including
          re-routes
        - ``failed_nodes`` -> ``failed_electrodes``
        - ``success_nodes`` -> ``success_electrodes``
    .. versionchanged:: 0.5
        Send the ``electrode-skip`` signal.
    .. versionchanged:: 0.5
        Prune unreachable electrodes from test route (e.g., after liquid
        movement to a bottleneck electrode has failed; cutting off the only
        path to other electrodes on the test route).
    '''
    def _move_liquid(*args, **kwargs):
        proxy.update_state(capacitance_update_interval_ms=0)
        return move_liquid(*args, **kwargs)

    result = _single_run_test(signals, proxy, G, way_points, start=start,
                              move_liquid=_move_liquid)
    proxy.stop_switching_matrix()
    proxy.turn_off_all_channels()
    return result
