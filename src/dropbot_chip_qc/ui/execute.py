# -*- encoding: utf-8 -*-
'''
.. versionadded:: X.X.X
'''
import functools as ft
import itertools as it
import threading

from dropbot_chip_qc.ui.render import get_summary_dict, render_summary
from logging_helpers import _L, caller_name
import asyncio_helpers as aioh
import dropbot_chip_qc as qc
import dropbot_chip_qc.ui.plan
import dropbot_chip_qc.ui.render
import networkx as nx
import numpy as np
import pandas as pd
import path_helpers as ph
import si_prefix as si
import trollius as asyncio

from .mqtt_proxy import DropBotMqttProxy


# For colors, see: https://gist.github.com/cfobel/fd939073cf13a309d7a9
light_blue = '#88bde6'
light_green = '#90cd97'


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


class ExecutorController(object):
    def __init__(self, aproxy, ui, executor):
        self.ui = ui
        channel_electrodes = ui['channel_electrodes']
        channel_patches = ui['channel_patches']
        chip_info = ui['chip_info']
        chip_info_mm = ui['chip_info_mm']
        figure = ui['figure']
        signals = ui['signals']

        def calibrate_sheet_capacitance(target_force, *args):
            '''Calibrate sheet capacitance with liquid present

            **NOTE** Prior to running the following cell:

             - _at least_ one electrode **MUST** be **actuated**
             - all actuated electrodes **MUST** be completely covered with liquid

            It may be helpful to use the interactive figure UI to manipulate liquid until
            the above criteria are met.

            This function performs the following steps:

             1. Measure **total capacitance** across **all actuated electrodes**
             2. Compute sheet capacitance with liquid present ($\Omega_L$) based on nominal
                areas of actuated electrodes from `chip_file`
             3. Compute voltage to match 25 μN of force, where
                $F = 10^3 \cdot 0.5 \cdot \Omega_L \cdot V^2$
             4. Set DropBot voltage to match target of 25 μN force.
            '''
            proxy = DropBotMqttProxy.from_uri('dropbot', aproxy.__client__._host)
            name = 'liquid'
            states = proxy.state_of_channels
            channels = states[states > 0].index.tolist()
            electrodes_by_id = pd.Series(chip_info_mm['electrodes'],
                                         index=(e['id'] for e in
                                                chip_info_mm['electrodes']))
            actuated_area = (electrodes_by_id[channel_electrodes[channels]]
                             .map(lambda x: x['area'])).sum()
            capacitance = pd.Series(proxy.capacitance(0)
                                    for i in range(20)).median()
            sheet_capacitance = capacitance / actuated_area
            message = ('Measured %s sheet capacitance: %sF/%.1f mm^2 = %sF/mm^2'
                       % (name, si.si_format(capacitance), actuated_area,
                          si.si_format(sheet_capacitance)))
            print(message)
            voltage = np.sqrt(target_force / (1e3 * 0.5 * sheet_capacitance))
            return sheet_capacitance, voltage

        def pause(*args):
            executor.pause()

        def reset(*args):
            executor.reset()
            channel_patches.map(lambda x: x.set_facecolor(light_blue))
            for collection in list(figure._ax.collections):
                collection.remove()
            figure._ax.figure.canvas.draw()

        def save_results(output_directory, chip_uuid, *args):
            output_dir = ph.path(output_directory)
            channel_plan, completed_transfers = executor.channel_plan()
            proxy = DropBotMqttProxy.from_uri('dropbot', aproxy.__client__._host)
            summary_dict = \
                get_summary_dict(proxy, chip_info,
                                 sorted(set(executor.base_channel_plan)),
                                 channel_plan, completed_transfers,
                                 chip_uuid=chip_uuid)
            output_path = output_dir.joinpath('Chip test report - %s.html' %
                                              summary_dict['chip_uuid'])
            print('save to: `%s`' % output_path)
            render_summary(output_path, **summary_dict)

        def start(bad_channels, *args):
            executor.channels_graph = executor.base_channels_graph.copy()
            executor.remove_channels(bad_channels)
            executor.start(aproxy, signals)

        self.calibrate_sheet_capacitance = calibrate_sheet_capacitance
        self.pause = pause
        self.reset = reset
        self.save_results = save_results
        self.start = start
