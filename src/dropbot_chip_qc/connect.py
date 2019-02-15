from __future__ import (absolute_import, print_function, unicode_literals,
                        division)
import io
import logging
import lxml
import pkgutil
import re
import threading
import time

from asyncio_helpers import cancellable
import blinker
import dropbot as db
import dropbot.chip
import dropbot.monitor
import joblib
import networkx as nx
import pandas as pd
import pint
import semantic_version
import svg_model
import svg_model.data_frame as sdf
import trollius as asyncio


def load_device(svg_source=None):
    '''
    .. versionchanged:: X.X.X
        Force downcast of `pint` millimeter quantities for `x` and `y`
        coordinates to `float`.
    '''
    if svg_source is None:
        # Load Sci-Bots device file and extract neighbouring channels info.
        svg_data = pkgutil.get_data('dropbot',
                                    'static/SCI-BOTS 90-pin array/device.svg')
        svg_source = io.BytesIO(svg_data)

    # Used cached neighbours result (if available).  Otherwise, cache neighbours.
    memcache = joblib.memory.Memory('.')

    get_channel_neighbours = memcache.cache(db.chip.get_channel_neighbours)
    neighbours = get_channel_neighbours(svg_source)

    ureg = pint.UnitRegistry()
    root = lxml.etree.parse(svg_source)
    namespaces = svg_model.NSMAP
    namespaces.update(svg_model.INKSCAPE_NSMAP)
    inkscape_version = root.xpath('/svg:svg/@inkscape:version',
                                  namespaces=namespaces)[0]

    # See http://wiki.inkscape.org/wiki/index.php/Release_notes/0.92#Important_changes
    pixel_density = (96 if inkscape_version >=
                     semantic_version.Version('0.92.0') else 90) * ureg.PPI

    df_shapes = svg_model.svg_shapes_to_df(svg_source)
    df_shapes.loc[:, ['x', 'y']] = (df_shapes.loc[:, ['x', 'y']].values *
                                    ureg.pixel /
                                    pixel_density).to('mm').magnitude
    df_shape_infos = sdf.get_shape_infos(df_shapes, 'id')

    electrodes_by_channel = \
        pd.concat(pd.Series(p.attrib['id'],
                            index=map(int,
                                      re.split(r',\s*',
                                               p.attrib['data-channels'])))
                for p in root.xpath('//svg:g[@inkscape:label="Device"]'
                                    '/svg:path[not(@data-channels="")]',
                                    namespaces=svg_model.INKSCAPE_NSMAP))
    electrodes_by_channel.sort_index(inplace=True)
    channels_by_electrode = pd.Series(electrodes_by_channel.index,
                                      index=electrodes_by_channel.values)
    channels_by_electrode.sort_index(inplace=True)
    channel_areas = df_shape_infos.loc[channels_by_electrode.index, 'area']
    channel_areas.index = channels_by_electrode
    channel_areas.name = 'area (mm^2)'

    G = nx.Graph()
    adjacency_list = (neighbours.dropna().to_frame().reset_index(level=0)
                      .astype(int).values)
    adjacency_list.sort(axis=1)
    G.add_edges_from(map(tuple, pd.DataFrame(adjacency_list).drop_duplicates().values))
    return G, neighbours


def connect(svg_source=None):
    signals = blinker.Namespace()

    connected = threading.Event()
    proxy = None

    @asyncio.coroutine
    def dump(*args, **kwargs):
        print('args=`%s`, kwargs=`%s`' % (args, kwargs))

    @asyncio.coroutine
    def on_connected(*args, **kwargs):
        proxy = kwargs['dropbot']
        proxy.turn_off_all_channels()
        proxy.stop_switching_matrix()
        proxy.neighbours = neighbours

        proxy.enable_events()

        proxy.update_state(hv_output_enabled=True, hv_output_selected=True,
                        voltage=100, frequency=10e3)

        # Disable channels in contact with copper tape.
        disabled_channels_mask_i = proxy.disabled_channels_mask
        disabled_channels_mask_i[[89, 30]] = 1
        # Disable channels with no neighbours defined.
        neighbour_counts = neighbours.groupby(level='channel').count()
        disabled_channels_mask_i[neighbour_counts.loc[neighbour_counts < 1].index] = 1
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

        return monitor_task, connected.proxy

    def close(*args):
        connected.clear()
        proxy.stop_switching_matrix()
        proxy.update_state(drops_update_interval_ms=int(0))
        time.sleep(1.)
        monitor_task.cancel()

    G, neighbours = load_device(svg_source=svg_source)
    monitor_task, proxy = _connect()
    return monitor_task, proxy, G


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)

    connect()
