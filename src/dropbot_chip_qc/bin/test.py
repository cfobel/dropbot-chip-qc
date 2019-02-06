import logging
import sys
import threading

from PySide2.QtWidgets import QMessageBox, QMainWindow, QApplication
import blinker
import dropbot as db
import dropbot.dispense
import functools as ft
import pandas as pd
import trollius as asyncio

from ..connect import connect
from ..video import chip_video_process, show_chip


def question(text, title='Question', flags=QMessageBox.StandardButton.Yes |
             QMessageBox.StandardButton.No):
    return QMessageBox.question(QMainWindow(), title, text, flags)


def try_async(*args, **kwargs):
    loop = asyncio.get_event_loop()
    kwargs['timeout'] = kwargs.get('timeout', 5)
    return loop.run_until_complete(asyncio.wait_for(*args, **kwargs))


def try_async_co(*args, **kwargs):
    kwargs['timeout'] = kwargs.get('timeout', 5)
    return asyncio.wait_for(*args, **kwargs)


def run_test():
    ready = threading.Event()
    closed = threading.Event()

    loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(loop)

    signals = blinker.Namespace()

    signals.signal('closed').connect(lambda sender: closed.set(), weak=False)

    monitor_task, proxy, G = connect()
    proxy.voltage = 115

    def on_chip_detected_wrapper(sender, **kwargs):
        @ft.wraps(on_chip_detected_wrapper)
        def wrapped(sender, **kwargs):
            signals.signal('chip-detected').disconnect(on_chip_detected_wrapper)
            uuid = kwargs['decoded_objects'][0].data
            ready.uuid = uuid
            ready.set()

            db.dispense.apply_duty_cycles(proxy, pd.Series(1, index=[110]))

            # Wait for chip to be detected.
            response = question('Chip detected: `%s`.\n\nLiquid loaded into electrode '
                                '110?' % uuid, title='Chip detected')

            proxy.stop_switching_matrix()
            proxy.turn_off_all_channels()
            signals.signal('chip-detected').connect(on_chip_detected_wrapper)

        loop.call_soon_threadsafe(ft.partial(wrapped, sender, **kwargs))

    signals.signal('chip-detected').connect(on_chip_detected_wrapper)

    thread = threading.Thread(target=chip_video_process,
                              args=(signals, 1280, 720, 0))
    thread.start()

    # Launch window to view chip video.
    loop.run_until_complete(show_chip(signals))

    # Close background thread.
    signals.signal('exit-request').send('main')
    closed.wait()

    #########################

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format="[%(asctime)s] %(levelname)s: %(message)s")
    app = QApplication(sys.argv)

    run_test()
