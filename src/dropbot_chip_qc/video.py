# -*- encoding: utf-8 -*-
from __future__ import print_function, absolute_import, unicode_literals
import logging
import threading
import time

import blinker
import numpy as np
import pandas as pd
import pyzbar.pyzbar as pyzbar

try:
    import cv2
except ImportError:
    raise Exception('Error: OpenCv is not installed')

from .async import asyncio, show_chip


# XXX The `device_corners` device AruCo marker locations in the normalized
# video frame were determined empirically.
delta = 2 * 45
device_height = 480 - 3.925 * delta
corner_indices = [
                  (1, 'top-right'),
                  (1, 'top-left'),
                  (0, 'top-left'),
                  (0, 'top-right'),
                 ]


def bbox_corners(x, y, width, height):
    return pd.DataFrame([(x, y), (x + delta, y), (x + delta, y + 1.5 * delta), (x, y + 1.5 * delta)],
                        columns=['x', 'y'],
                        index=['top-left', 'bottom-left', 'bottom-right', 'top-right'],  # Top/bottom of top plate
                        dtype='float32')


x_zoom_delta = 50
y_zoom_delta = 45
y_zoom_offset = -37.5
device_corners = pd.concat((bbox_corners(x, y, delta, delta)
                            for x, y in
                            # Top/bottom of top-plate
                            [(640 + x_zoom_delta,
                              y_zoom_offset + 480 - delta -
                              .5 * device_height + y_zoom_delta),
                             (-delta - x_zoom_delta,
                              y_zoom_offset + .5 * device_height -
                              y_zoom_delta)]),
                           keys=range(2))
device_corners.loc[1, :] = np.roll(device_corners.loc[1].values, -4)
device_corners /= 640, 480


class FPS(object):
    def __init__(self):
        self._times = []

    def update(self):
        self._times.append(time.time())
        self._times = self._times[-10:]

    @property
    def framerate(self):
        if len(self._times) > 1:
            return 1 / np.diff(self._times).mean()
        else:
            return 0.


def chip_video_process(signals, width=1920, height=1080, device_id=0):
    '''
    Continuously monitor webcam feed for DMF chip.

    Repeatedly perform the following tasks:

     - read video frame from the webcam
     - detect AruCo markers in the frame, and draw overlay to indicate markers
       (if available)
     - apply perspective correction based on detected AruCo marker positions
       (if applicable)
     - detect chip UUID from QR code (if available)
     - combine raw video frame and perspective-corrected frame into a single
       frame
     - write the chip UUID as text in top-left corner of the combined video
       frame

    Layout of the combined video frame::

        ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
        ┃                                               ┃
        ┃  Raw video frame (AruCo markers highlighted)  ┃
        ┃                                               ┃
        ┃                                               ┃
        ┠┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┨
        ┃                                               ┃
        ┃  Perspective-corrected video frame            ┃
        ┃  based on AruCo markers                       ┃
        ┃                                               ┃
        ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

    Parameters
    ----------
    signals : blinker.Namespace
        The following signals are sent::
        - ``frame-ready``: video frame is ready; keyword arguments include::
          - ``frame``: combined video frame
          - ``raw_frame``: raw frame from webcam
          - ``warped``: perspective-corrected frame
          - ``transform``: perspective-correction transformation matrix
          - ``fps``: rate of frame processing in frames per second
          - ``chip_uuid``: UUID currently detected chip (``None`` if no chip is
            detected)
        - ``closed``: process has been closed (in response to a
          ``exit-request`` signal).
        - ``chip-detected``: new chip UUID has been detected
        - ``chip-removed``: chip UUID no longer detected
    width : int, optional
        Video width.
    height : int, optional
        Video height.
    device_id : int, optional
        OpenCV video source id (starts at zero).
    '''
    capture = cv2.VideoCapture(device_id)

    # Set format to MJPG (instead of YUY2) to _dramatically_ improve frame
    # rate.  For example, using Logitech C920 camera, frame rate increases from
    # 10 FPS to 30 FPS (not including QR code detection, warping, etc.).
    #
    # See: https://github.com/opencv/opencv/issues/9084#issuecomment-324477425
    fourcc_int = np.fromstring(bytes('MJPG'), dtype='uint8').view('uint32')[0]
    capture.set(cv2.CAP_PROP_FOURCC, fourcc_int)

    capture.set(cv2.CAP_PROP_AUTOFOCUS, True)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    if capture.isOpened():  # try to get the first frame
        frame_captured, frame = capture.read()
    else:
        raise IOError('No frame.')

    corners_by_id = {}

    start = time.time()
    frame_count = 0
    # Transformation matrix for perspective-corrected device view.
    M = None
    # Counter to debounce detection of missing chip; helps prevent spurious
    # `chip-detected`/`chip-removed` events where chip has not actually moved.
    not_detected_count = 0
    decodedObjects = []
    exit_requested = threading.Event()
    chip_detected = threading.Event()
    fps = 1

    signals.signal('exit-request').connect(lambda sender: exit_requested.set(),
                                           weak=False)

    # Font used for UUID label.
    font = cv2.FONT_HERSHEY_SIMPLEX
    fps = FPS()

    while frame_captured and not exit_requested.is_set():
        # Find barcodes and QR codes
        if not chip_detected.is_set():
            decodedObjects = pyzbar.decode(frame)
            if decodedObjects:
                chip_detected.decoded_objects = decodedObjects
                chip_detected.set()
                # Find font scale to fit UUID to width of frame.
                text = chip_detected.decoded_objects[0].data
                scale = 4
                thickness = 1
                text_size = cv2.getTextSize(text, font, scale, thickness)
                while text_size[0][0] > frame.shape[0]:
                    scale *= .95
                    text_size = cv2.getTextSize(text, font, scale, thickness)
                chip_detected.label = {'uuid': text, 'scale': scale,
                                       'thickness': 1, 'text_size': text_size}
                signals.signal('chip-detected')\
                    .send('chip_video_process',
                          decoded_objects=chip_detected.decoded_objects)
                logging.info('chip detected: `%s`',
                             chip_detected.decoded_objects[0].data)

        detect_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_1000)
        corners, ids, rejectedImgPoints = cv2.aruco.detectMarkers(frame,
                                                                  detect_dict)
        cv2.aruco.drawDetectedMarkers(frame, corners, ids)
        corners_by_id_i = (dict(zip(ids[:, 0], corners)) if ids is not None
                           else {})

        updated = False
        for i in range(2):
            if i in corners_by_id_i:
                corners_list_i = corners_by_id.setdefault(i, [])
                corners_list_i.append(corners_by_id_i[i])
                del corners_list_i[:-5]
                updated = True

        if updated and all(i in corners_by_id_i for i in range(2)):
            not_detected_count = 0
            mean_corners = pd.concat((pd.DataFrame(np.array(corners_by_id[i])
                                                   .mean(axis=0)[0],
                                                   columns=['x', 'y'],
                                                   index=['top-left',
                                                          'top-right',
                                                          'bottom-right',
                                                          'bottom-left'])
                                      for i in range(2)), keys=range(2))
            M = cv2.getPerspectiveTransform(mean_corners.loc[corner_indices]
                                            .values,
                                            (device_corners.loc[corner_indices]
                                             * frame.shape[:2][::-1]).values)
        elif chip_detected.is_set():
            M = None
            not_detected_count += 1

        if M is None and not_detected_count >= 10:
            not_detected_count = 0
            # AruCo markers have not been detected for the previous 10 frames;
            # assume chip has been removed.
            chip_detected.clear()
            signals.signal('chip-removed').send('chip_video_process')

        if M is not None:
            warped =  cv2.warpPerspective(frame, M, frame.shape[:2][::-1])
        else:
            warped = frame
        display_frame = np.concatenate([frame, warped])
        display_frame = cv2.resize(display_frame,
                                   tuple(np.array(display_frame.shape[:2]) /
                                         2))
        if chip_detected.is_set():
            kwargs = chip_detected.label.copy()
            cv2.putText(display_frame, kwargs['uuid'],
                        (10, 10 + kwargs['text_size'][0][-1]), font,
                        kwargs['scale'], (255,255,255),
                        kwargs['thickness'], cv2.LINE_AA)
            chip_uuid = chip_detected.label['uuid']
        else:
            chip_uuid = None
        signals.signal('frame-ready').send('chip_video_process',
                                           frame=display_frame, transform=M,
                                           raw_frame=frame, warped=warped,
                                           fps=fps, chip_uuid=chip_uuid)
        frame_captured, frame = capture.read()
        fps.update()

    # When everything done, release the capture
    capture.release()
    signals.signal('closed').send('chip_video_process')


def main(signals=None, resolution=(1280, 720), device_id=0):
    '''
    Launch chip webcam monitor thread and view window.
    '''
    if signals is None:
        signals = blinker.Namespace()

    thread = threading.Thread(target=chip_video_process,
                              args=(signals, resolution[0], resolution[1],
                                    device_id))
    thread.start()

    loop = asyncio.get_event_loop()

    # Launch window to view chip video.
    loop.run_until_complete(show_chip(signals))

    # Close background thread.
    signals.signal('exit-request').send('main')
