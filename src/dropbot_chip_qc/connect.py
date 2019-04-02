from __future__ import (absolute_import, print_function, unicode_literals,
                        division)
import logging
import threading
import time

from asyncio_helpers import cancellable
import blinker
import dmf_chip as dc
import dropbot as db
import dropbot.chip
import dropbot.monitor
import networkx as nx
import pandas as pd
import trollius as asyncio


def load_device(chip_file):
    '''
    .. versionchanged:: 0.9.0
        Delegate SVG parsing and neighbour extraction to the `dmf_chip`
        package; using the :func:`load()` and :func:`get_neighbours()`
        functions, respectively.
    '''
    chip_info = dc.load(chip_file)
    neighbours = dc.get_neighbours(chip_info)

    G = nx.Graph([(c['source']['id'], c['target']['id'])
                  for c in chip_info['connections']])
    G.add_nodes_from(e['id'] for e in chip_info['electrodes'])
    return chip_info, G, neighbours


def connect(svg_source=None):
    '''
    .. versionchanged:: 0.9.0
        Attach ``electrodes_graph``, ``channels_graph``, and ``chip_info``
        attributes to ``proxy`` to expose adjacent electrode ids and channel
        numbers, along with detailed chip design info parsed from SVG file.
    .. versionchanged:: 0.9.0
        Attach ``proxy`` attribute to monitor task to DropBot handle.
    .. versionchanged:: 0.9.0
        Attach ``signals`` attribute to monitor task to expose signals
        namespace to calling code.
    '''
    signals = blinker.Namespace()

    connected = threading.Event()
    proxy = None

    @asyncio.coroutine
    def dump(*args, **kwargs):
        print('args=`%s`, kwargs=`%s`' % (args, kwargs))

    @asyncio.coroutine
    def on_connected(*args, **kwargs):
        proxy = kwargs['dropbot']
        proxy.chip_info = chip_info
        proxy.electrodes_graph = electrodes_graph
        proxy.channels_graph = channels_graph
        proxy.turn_off_all_channels()
        proxy.stop_switching_matrix()
        proxy.neighbours = channel_neighbours
        proxy.electrode_neighbours = neighbours

        proxy.enable_events()

        proxy.update_state(hv_output_enabled=True, hv_output_selected=True,
                           voltage=100, frequency=10e3)

        # Disable channels in contact with copper tape.
        disabled_channels_mask_i = proxy.disabled_channels_mask
        # Disable channels with no neighbours defined.
        neighbour_counts = channel_neighbours.groupby(level='channel').count()
        disabled_channels_mask_i[neighbour_counts.loc[neighbour_counts <
                                                      1].index] = 1
        proxy.disabled_channels_mask = disabled_channels_mask_i

        connected.proxy = proxy
        connected.set()

    @asyncio.coroutine
    def on_disconnected(*args, **kwargs):
        raise IOError('Lost DropBot connection.')


    @asyncio.coroutine
    def ignore(*args, **kwargs):
        raise asyncio.Return('ignore')


    def _connect(*args):
        signals.clear()
        signals.signal('chip-inserted').connect(dump, weak=False)
        signals.signal('connected').connect(on_connected, weak=False)
        signals.signal('disconnected').connect(on_disconnected, weak=False)
        signals.signal('version-mismatch').connect(ignore, weak=False)

        monitor_task = cancellable(db.monitor.monitor)
        thread = threading.Thread(target=monitor_task, args=(signals, ))
        thread.daemon = True
        thread.start()

        while not connected.wait(1):
            pass

        monitor_task.proxy = connected.proxy
        return monitor_task

    def close(*args):
        connected.clear()
        proxy.stop_switching_matrix()
        proxy.update_state(drops_update_interval_ms=int(0))
        time.sleep(1.)
        monitor_task.cancel()

    chip_info, electrodes_graph, neighbours = load_device(svg_source)

    # Convert `neighbours` to use channel numbers instead of electrode ids.
    electrode_channels = pd.Series({e['id']: e['channels'][0]
                                    for e in chip_info['electrodes']})
    index = pd.MultiIndex\
        .from_arrays([electrode_channels[neighbours.index
                                         .get_level_values('id')],
                      neighbours.index.get_level_values('direction')],
                     names=('channel', 'direction'))
    channel_neighbours = pd.Series(electrode_channels[neighbours].values,
                                   index=index)
    channels_graph = nx.Graph([tuple(map(electrode_channels.get, e))
                               for e in electrodes_graph.edges])

    monitor_task = _connect()
    monitor_task.signals = signals
    return monitor_task


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)

    connect()
