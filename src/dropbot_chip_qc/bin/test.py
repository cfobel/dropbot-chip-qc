# -*- encoding: utf-8 -*-
from __future__ import print_function, absolute_import
import argparse
import copy
import datetime as dt
import functools as ft
import io
import json
import logging
import pkgutil
import sys
import threading
import time

from asyncio_helpers import cancellable
from PySide2.QtWidgets import QMessageBox, QMainWindow, QApplication
import blinker
import dmf_chip as dc
import dropbot as db
import dropbot.self_test
import lxml.etree
import mutagen
import networkx as nx
import path_helpers as ph
import trollius as asyncio

from ..connect import connect
from ..render import render_summary
from ..video import chip_video_process, show_chip
from ..single_drop import _run_test as _single_run_test
from ..multi_sensing import _run_test as _multi_run_test
from .video import VIDEO_PARSER
from .._version import get_versions
__version__ = get_versions()['version']
del get_versions


def _date_subs_dict(datetime_=None):
    if datetime_ is None:
        datetime_ = dt.datetime.utcnow()
    return {'Y': datetime_.strftime('%Y'),
            'm': datetime_.strftime('%m'),
            'd': datetime_.strftime('%d'),
            'H': datetime_.strftime('%H'),
            'I': datetime_.strftime('%I'),
            'M': datetime_.strftime('%M'),
            'S': datetime_.strftime('%S')}


def question(text, title='Question', flags=QMessageBox.StandardButton.Yes |
             QMessageBox.StandardButton.No):
    return QMessageBox.question(QMainWindow(), title, text, flags)


def run_test(way_points, start_electrode, output_dir, video_dir=None,
             overwrite=False, svg_source=None, launch=False,
             resolution=(1280, 720), device_id=0, multi_sensing=False):
    '''
    Parameters
    ----------
    way_points : list[int]
        Contiguous list of waypoints, where test is routed as the shortest path
        between each consecutive pair of waypoints.
    start_electrode : int
        Waypoint to treat as starting point.

        If not the first waypoint in ``way_points``, the test route will "wrap
        around" until the ``start_electrode`` is reached again.
    output_dir : str
        Directory to write output files to.

        May include ``'%(uuid)s'`` as placeholder for chip UUID, e.g.,
        ``~/my_output_dir/%(uuid)s-results``.
    video_dir : str, optional
        Directory within which to search for videos corresponding to the start
        time of the test.

        If a related video is found, offer to move/rename the video with the
        same name and location as the output results file.
    overwrite : bool, optional
        If ``True``, overwrite output files.  Otherwise, ask before
        overwriting.
    svg_source : str or file-like, optional
        A file path, URI, or file-like object containing DropBot chip SVG
        source.
    launch : bool, optional
        Launch output path after creation (default: `False`).
    resolution : tuple[int, int], optional
        Target video resolution (may be ignored if not supported by device).
    device_id : int, optional
        OpenCV video capture device identifier (default=0).
    multi_sensing : bool, optional
        If `True`, run multi-sensing test.  Otherwise, run single-drop test
        (default: `False`).


    .. versionchanged:: 0.2
        Add ``video_dir`` keyword argument.
    .. versionchanged:: 0.3
        Add ``output_dir`` argument; and ``overwrite`` and ``svg_source``
        keyword arguments.
    .. versionchanged:: 0.4
        Write each test result a self-contained HTML file in the specified
        output directory.
    .. versionchanged:: 1.6.0
        Add ``launch`` keyword argument.
    .. versionchanged:: 0.7.0
        Add ``resolution`` and ``device_id`` keyword arguments.
    .. versionchanged:: 0.8.0
        Add ``multi_sensing`` keyword argument.
    .. versionchanged:: 0.9.0
        Update to support new return type from `connect()`, use ``proxy``
        attribute of ``monitor_task``, and ``channels_graph`` attribute of
        ``proxy``.
    .. versionchanged:: X.X.X
        Explicitly execute a shorts detection test at the start of a chip test.
    .. versionchanged:: X.X.X
        Add chip info to logged ``test-start`` message.
    '''
    output_dir = ph.path(output_dir)

    if video_dir is not None:
        video_dir = ph.path(video_dir)

    ready = threading.Event()
    closed = threading.Event()

    loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(loop)

    signals = blinker.Namespace()

    signals.signal('closed').connect(lambda sender: closed.set(), weak=False)

    logging.info('Wait for connection to DropBot...')
    monitor_task = connect(svg_source=svg_source)
    proxy = monitor_task.proxy
    G = proxy.channels_graph
    proxy.voltage = 115

    def update_video(video, uuid):
        response = question('Attempt to set UUID in title of video file, '
                            '`%s`?' % video, title='Update video?')
        if response == QMessageBox.StandardButton.Yes:
            try:
                f = mutagen.File(video)
                if ('\xa9nam' not in f.tags) or ('UUID' not in
                                                 f.tags['\xa9nam']):
                    f.tags['\xa9nam'] = \
                        'DMF chip QC - UUID: %s' % uuid
                    f.save()
                    logging.info('wrote UUID to video title: `%s`', video)
            except Exception:
                logging.warning('Error setting video title.', exc_info=True)
            # Substitute UUID into output directory path as necessary.
            path_subs_dict = {'uuid': uuid}
            path_subs_dict.update(_date_subs_dict())
            output_dir_ = ph.path(output_dir %
                                  path_subs_dict).expand().realpath()
            output_dir_.makedirs_p()
            output_path = output_dir_.joinpath('%s.mp4' % uuid)
            if not output_path.exists() or overwrite or \
                    (question('Output `%s` exists.  Overwrite?' % output_path,
                              title='Overwrite?') ==
                     QMessageBox.StandardButton.Yes):
                if output_path.exists():
                    output_path.remove()
                ph.path(video).move(output_path)
                logging.info('moved video to : `%s`', output_path)

    def on_chip_detected(sender, **kwargs):
        @ft.wraps(on_chip_detected)
        def wrapped(sender, **kwargs):
            signals.signal('chip-detected').disconnect(on_chip_detected)
            uuid = kwargs['decoded_objects'][0].data
            ready.uuid = uuid
            ready.set()

            # Wait for chip to be detected.
            response = None

            while response != QMessageBox.StandardButton.Yes:
                response = question('Chip detected: `%s`.\n\nReady to load '
                                    'electrode %s?' % (uuid, start_electrode),
                                    title='Chip detected')

            proxy.stop_switching_matrix()
            proxy.turn_off_all_channels()

            @asyncio.coroutine
            def _run():
                dropbot_events = []

                def log_event(message):
                    # Add UTC timestamp to each event.
                    message['utc_time'] = dt.datetime.utcnow().isoformat()
                    dropbot_events.append(message)

                # Log route events in memory.
                def log_route_event(event, message):
                    # Tag kwargs with route event name.
                    message['event'] = event
                    # Add chip, DropBot, and version info to `test-start`
                    # message.
                    if event == 'test-start':
                        message['uuid'] = uuid
                        message['dropbot.__version__'] = db.__version__
                        message['dropbot_chip_qc.__version__'] = __version__
                        message['dropbot'] = {'system_info':
                                              db.self_test.system_info(proxy),
                                              'i2c_scan':
                                              db.self_test.test_i2c(proxy)}
                        message['dmf_chip.__version'] = dc.__version__
                        message['chip-info'] = copy.deepcopy(proxy.chip_info)
                    log_event(message)

                # Log results of shorts detection tests.
                proxy.signals.signal('shorts-detected').connect(log_event)

                if multi_sensing:
                    # Log multi-sensing capacitance events (in memory).
                    proxy.signals.signal('sensitive-capacitances')\
                        .connect(log_event)

                    # Use multi-sensing test implementation.
                    _run_test = _multi_run_test
                else:
                    # Use single-drop test implementation.
                    _run_test = _single_run_test

                loggers = {e: ft.partial(lambda event, sender, **kwargs:
                                         log_route_event(event, kwargs), e)
                           for e in ('electrode-success', 'electrode-fail',
                                     'electrode-skip', 'test-start',
                                     'test-complete')}
                for event, logger in loggers.items():
                    signals.signal(event).connect(logger)

                # Explicitly execute a shorts detection test.
                proxy.detect_shorts()

                try:
                    start = time.time()
                    yield asyncio.From(_run_test(signals, proxy, G, way_points,
                                                 start=start_electrode))
                    if video_dir:
                        # A video directory was provided.  Look for a video
                        # corresponding to the same timeline as the test.
                        # Only consider videos that were created within 1
                        # minute of the start of the test.
                        videos = sorted((p for p in
                                         video_dir.expand().files('*.mp4')
                                         if abs(p.ctime - start) < 60),
                                        key=lambda x: -x.ctime)
                        if videos:
                            loop.call_soon_threadsafe(update_video, videos[-1],
                                                      uuid)
                except nx.NetworkXNoPath as exception:
                    logging.error('QC test failed: `%s`', exception,
                                  exc_info=True)

                def write_results():
                    # Substitute UUID into output directory path as necessary.
                    path_subs_dict = {'uuid': uuid}
                    path_subs_dict.update(_date_subs_dict())
                    output_dir_ = ph.path(output_dir %
                                          path_subs_dict).expand().realpath()
                    output_dir_.makedirs_p()

                    # Write logged events to file.
                    output_path = \
                        output_dir_.joinpath('Chip test report - %s.html' %
                                             uuid)
                    if not output_path.exists() or overwrite or \
                            (question('Output `%s` exists.  Overwrite?' %
                                     output_path, title='Overwrite?') ==
                             QMessageBox.StandardButton.Yes):
                        render_summary(dropbot_events, output_path,
                                       svg_source=svg_source)
                        logging.info('wrote events log to: `%s`', output_path)
                        if launch:
                            # Launch result using default system viewer.
                            output_path.launch()

                loop.call_soon_threadsafe(write_results)

                signals.signal('chip-detected').connect(on_chip_detected)

            qc_task = cancellable(_run)
            thread = threading.Thread(target=qc_task)
            thread.daemon = True
            thread.start()

        loop.call_soon_threadsafe(ft.partial(wrapped, sender, **kwargs))

    signals.signal('chip-detected').connect(on_chip_detected)

    thread = threading.Thread(target=chip_video_process,
                              args=(signals, resolution[0], resolution[1],
                                    device_id))
    thread.start()

    # Launch window to view chip video.
    loop.run_until_complete(show_chip(signals))

    # Close background thread.
    signals.signal('exit-request').send('main')
    closed.wait()


def parse_args(args=None):
    '''
    .. versionchanged:: 0.7.1
        Fix ``resolution`` argument handling.
    .. versionchanged:: 0.8.0
        Add ``multi-sensing`` (``-M``) argument.
    .. versionchanged:: 0.9.0
        Add support for reading embedded test route waypoints from the chip
        design SVG file (see sci-bots/dmf-chip#1), allowing a test route to be
        specified as either an id of a ``<dmf:TestRoute>`` element in the SVG
        _or_ a JSON list of channel numbers.
    '''
    if args is None:
        args = sys.argv[1:]
    DEFAULT_DEVICE_NAME = 'SCI-BOTS 90-pin array'
    DEFAULT_DEVICE_SOURCE = \
        pkgutil.get_data('dropbot', 'static/SCI-BOTS 90-pin array/device.svg')

    parser = argparse.ArgumentParser(description='DropBot chip quality '
                                     'control', parents=[VIDEO_PARSER])
    parser.add_argument('-d', '--output-dir', type=ph.path,
                        default=ph.path('.'), help="Output directory "
                        "(default='%(default)s').")
    parser.add_argument('--video-dir', type=ph.path, help='Directory to search'
                        ' for recorded videos matching start time of test.')
    parser.add_argument('-s', '--start', type=int, help='Start electrode')
    parser.add_argument('--launch', action='store_true', help='Launch output '
                        'path after creation.')
    parser.add_argument('-f', '--force', action='store_true', help='Force '
                        'overwrite of existing files.')
    parser.add_argument('-M', '--multi-sensing', action='store_true',
                        help='Use multi-sensing test (requires '
                        '`dropbot>=2.2.0`).')
    parser.add_argument('-S', '--svg-path', type=ph.path,
                        default=io.BytesIO(DEFAULT_DEVICE_SOURCE),
                        help="SVG device file (default='%s')" % DEFAULT_DEVICE_NAME)
    parser.add_argument('test_route', help='Test route as either id of '
                        '<dmf:TestRoute> in SVG or JSON list of channel '
                        'numbers, e.g., "[110, 109, 115]" '
                        '(default="%(default)s").', nargs='?',
                        default='default')

    args = parser.parse_args(args)

    args.resolution = tuple(map(int, args.resolution.split('x')))
    try:
        args.way_points = json.loads(args.test_route)
    except ValueError:
        # Assume test route arg specifies id of test route in SVG.
        try:
            doc = lxml.etree.parse(args.svg_path)
        finally:
            if isinstance(args.svg_path, io.BytesIO):
                # "Rewind" file after parsing to pass to remaining code.
                args.svg_path.seek(0)
        root = doc.getroot()
        NSMAP = {k: v for k, v in root.nsmap.items() if k is not None}
        rxpath = ft.wraps(root.xpath)(ft.partial(root.xpath, namespaces=NSMAP))
        # Read test routes.
        test_route_elements = \
            rxpath('//dmf:ChipDesign/dmf:TestRoutes/dmf:TestRoute[@id!=""]')
        for route in test_route_elements:
            xpath_ = ft.wraps(route.xpath)(ft.partial(route.xpath,
                                                      namespaces=NSMAP))
            route_ = dict(route.attrib.items())
            if route_.get('id') == args.test_route:
                # Test route matches specified route id.  Extract waypoints.
                args.way_points = [int(w.text) for w in xpath_('dmf:Waypoint')]
                break
        else:
            parser.error('No test route with `id=%s` found in chip file.' %
                         args.test_route)

    if args.start is None:
        args.start = args.way_points[0]
    elif args.start not in args.way_points:
        parser.error('Start channel must be one of the waypoints: `%s`' %
                     args.way_points)
    return args


def main():
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG,
                        format="[%(asctime)s] %(levelname)s: %(message)s")
    app = QApplication(sys.argv)

    run_test(args.way_points, args.start, args.output_dir, args.video_dir,
             overwrite=args.force, svg_source=args.svg_path,
             launch=args.launch, device_id=args.video_device,
             resolution=args.resolution,
             multi_sensing=args.multi_sensing)


if __name__ == '__main__':
    main()
