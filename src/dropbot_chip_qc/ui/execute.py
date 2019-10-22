import functools as ft
import itertools as it
import threading

from logging_helpers import _L, caller_name
import asyncio_helpers as aioh
import dropbot_chip_qc as qc
import dropbot_chip_qc.ui.plan
import dropbot_chip_qc.ui.render
import networkx as nx
import pandas as pd
import path_helpers as ph
import trollius as asyncio


class Executor(object):
    def __init__(self, channels_graph, channel_plan):
        self.base_channels_graph = channels_graph.copy()
        self.channels_graph = channels_graph.copy()
        self.base_channel_plan = list(channel_plan)
        self.completed_results = []
        self._thread = None
        self._task = None

    def is_alive(self):
        return self._thread is not None and self._thread.is_alive()

    def remove_channels(self, bad_channels):
        self.channels_graph.remove_nodes_from(bad_channels)

    def channel_plan(self):
        if self.completed_results:
            channel_plan = self.completed_results[-1]['channel_plan']
            completed_transfers = \
                self.completed_results[-1]['completed_transfers']
        else:
            channel_plan = self.base_channel_plan
            completed_transfers = []

        channel_plan_ = [c for c in channel_plan if c in self.channels_graph]
        if len(channel_plan_) < len(channel_plan):
            _L().debug('reroute around missing channels')
            channel_plan = list(qc.ui.plan\
                .create_channel_plan(self.channels_graph, channel_plan_,
                                     loop=False))
        return channel_plan, completed_transfers

    def start(self, aproxy, signals, bad_channels=None, min_duration=.15):
        '''
        # TODO

         - incorporate `execute()` coroutine
         - add
        '''
        if self.is_alive():
            raise RuntimeError('Executor is already running.')

        channel_plan, completed_transfers = self.channel_plan()

        @asyncio.coroutine
        def execute_test(*args, **kwargs):
            yield asyncio.From(set_capacitance_update_interval())
            try:
                result = yield asyncio\
                    .From(qc.ui.plan.transfer_windows(*args, **kwargs))
            except qc.ui.plan.TransferFailed as exception:
                # Save intermediate result.
                result = dict(channel_plan=exception.channel_plan,
                              completed_transfers=exception.completed_transfers)
                signals.signal('test-interrupt').send(caller_name(0), **result)
            self.completed_results.append(result)
            yield asyncio.From(aproxy.set_state_of_channels(pd.Series(), append=False))
            # result = dict(channel_plan=channel_plan_i,
                          # completed_transfers=completed_transfers_i)
            raise asyncio.Return(result)

        @asyncio.coroutine
        def set_capacitance_update_interval():
            state = yield asyncio.From(aproxy.state)
            max_update_interval = int(.5 * min_duration * 1e3)
            if state.capacitance_update_interval_ms > max_update_interval \
                    or state.capacitance_update_interval_ms == 0:
                yield asyncio\
                    .From(aproxy.update_state(capacitance_update_interval_ms=
                                              max_update_interval))

        looped_channel_plan = (channel_plan +
                               nx.shortest_path(self.channels_graph,
                                                channel_plan[-1],
                                                self.base_channel_plan[0])[1:])
        self._task = aioh.cancellable(execute_test)
        transfer_liquid = ft.partial(qc.ui.plan.transfer_liquid, aproxy,
                                     min_duration=min_duration)
        self._thread = threading.Thread(target=self._task,
                                        args=(signals, looped_channel_plan,
                                              completed_transfers,
                                              transfer_liquid),
                                        kwargs={'n': 3})

        self._thread.daemon = True
        self._thread.start()

    def pause(self):
        if self.is_alive():
            self._task.cancel()

    def reset(self):
        self.pause()
        del self.completed_results[:]
        self.channels_graph = self.base_channels_graph.copy()
