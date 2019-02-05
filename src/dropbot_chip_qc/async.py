# -*- encoding: utf-8 -*-
from __future__ import print_function, absolute_import, unicode_literals

import cv2
import trollius as asyncio


@asyncio.coroutine
def read_frame(signals):
    loop = asyncio.get_event_loop()

    frame_ready = asyncio.Event()
    response = {}

    def on_frame_ready(sender, **message):
        response.update(message)
        loop.call_soon_threadsafe(frame_ready.set)

    signals.signal('frame-ready').connect(on_frame_ready)

    yield asyncio.From(frame_ready.wait())
    raise asyncio.Return(response)


@asyncio.coroutine
def show_chip(signals, title='DMF chip'):
    '''
    Display raw webcam view and corresponding perspective-corrected chip view.

    Press ``q`` key to close window.

    Parameters
    ----------
    signals : blinker.Namespace
        DMF chip webcam monitor signals (see `chip_video_process()`).
    title : str, optional
        Window title.

    See also
    --------
    `read_frame()`, `chip_video_process()`
    '''
    loop = asyncio.get_event_loop()

    print('Press "q" to quit')

    while True:
        try:
            record = yield asyncio.wait_for(read_frame(signals), .01)
            frame = record['frame']
            cv2.imshow(title, frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        except asyncio.TimeoutError:
            continue
    cv2.destroyAllWindows()
