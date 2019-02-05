from __future__ import print_function, absolute_import, unicode_literals
import json
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


def show_chip(width=1920, height=1080, device_id=0, signals=None):
    '''
    Parameters
    ----------
    width : int, optional
        Video width.
    height : int, optional
        Video height.
    device_id : int, optional
        OpenCV video source id (starts at zero).
    signals : blinker.Namespace, optional
        If set, the following signals are sent::
        - ``frame-ready``: video frame is ready (frame is passed as ``frame``
          keyword argument).
    '''
    print('Press "q" to quit')
    capture = cv2.VideoCapture(device_id)
    capture.set(cv2.CAP_PROP_AUTOFOCUS, True)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    if capture.isOpened():  # try to get the first frame
        frame_captured, frame = capture.read()
    else:
        raise IOError('No frame.')

    # Display barcode and QR code location
    def draw_detected_barcodes(im, decodedObjects):
        # Loop over all decoded objects
        for decodedObject in decodedObjects:
            points = decodedObject.polygon

            # If the points do not form a quad, find convex hull
            if len(points) > 4 :
                hull = cv2.convexHull(np.array([point for point in points], dtype=np.float32))
                hull = list(map(tuple, np.squeeze(hull)))
            else :
                hull = points;

            # Number of points in the convex hull
            n = len(hull)

            # Draw the convext hull
            for j in range(0,n):
                cv2.line(im, hull[j], hull[ (j+1) % n], (255,0,0), 3)

            object_i = decodedObject.__dict__.copy()
            object_i['polygon'] = [point.__dict__
                                   for point in object_i['polygon']]
            json.dumps(object_i)

            font                   = cv2.FONT_HERSHEY_SIMPLEX
            bottomLeftCornerOfText = tuple([object_i['polygon'][-1][k] for k in 'xy'])
            fontScale              = .5
            fontColor              = (255, 255 ,255)
            lineType               = 2

            cv2.putText(im, object_i['data'],
                        bottomLeftCornerOfText,
                        font,
                        fontScale,
                        fontColor,
                        lineType)

    corners_by_id = {}

    start = time.time()
    frame_count = 0
    decodedObjects = []
    exit_requested = threading.Event()
    chip_detected = threading.Event()

    signals.signal('exit-request').connect(lambda sender: exit_requested.set(),
                                           weak=False)

    while frame_captured and not exit_requested.is_set():
        # Find barcodes and QR codes
        if not chip_detected.is_set():
            decodedObjects = pyzbar.decode(frame)
            if decodedObjects:
                chip_detected.decoded_objects = decodedObjects
                chip_detected.set()
                if signals is not None:
                    signals.signal('chip-detected')\
                        .send(None,
                              decoded_objects=chip_detected.decoded_objects)
                    logging.info('chip detected: %s',
                                 chip_detected.decoded_objects)

        corners, ids, rejectedImgPoints = cv2.aruco.detectMarkers(frame, cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_1000))
        cv2.aruco.drawDetectedMarkers(frame, corners, ids)
        corners_by_id_i = dict(zip(ids[:, 0], corners)) if ids is not None else {}

        updated = False
        for i in range(2):
            if i in corners_by_id_i:
                corners_list_i = corners_by_id.setdefault(i, [])
                corners_list_i.append(corners_by_id_i[i])
                del corners_list_i[:-5]
                updated = True

        if updated and all(i in corners_by_id_i for i in range(2)):
            mean_corners = pd.concat((pd.DataFrame(np.array(corners_by_id[i])
                                                   .mean(axis=0)[0], columns=['x', 'y'],
                                                   index=['top-left', 'top-right',
                                                          'bottom-right', 'bottom-left'])
                                      for i in range(2)), keys=range(2))
            M = cv2.getPerspectiveTransform(mean_corners.loc[corner_indices]
                                            .values,
                                            (device_corners.loc[corner_indices] *
                                             frame.shape[:2][::-1]).values)
        else:
            M = None
            chip_detected.clear()
            if signals is not None:
                signals.signal('chip-removed').send(None)

        if M is not None:
            warped =  cv2.warpPerspective(frame, M, frame.shape[:2][::-1])
        else:
            warped = frame
        display_frame = np.concatenate([frame, warped])
        display_frame = cv2.resize(display_frame,
                                   tuple(np.array(display_frame.shape[:2]) /
                                         2))
        if signals is not None:
            signals.signal('frame-ready').send(None, frame=display_frame,
                                               transform=M)
        frame_captured, frame = capture.read()
        if frame_captured:
            frame_count += 1
        print('\r%-50s' % ('%.2f FPS (%s)' % (frame_count / (time.time() - start), frame_count)), end='')

    # When everything done, release the capture
    capture.release()
    if signals is not None:
        signals.signal('closed').send(None)


def main():
    chip_detected = threading.Event()
    frame_ready = threading.Event()

    signals = blinker.Namespace()
    frame_ready = threading.Event()
    update_lock = threading.Lock()
    closed = threading.Event()

    def on_chip_detected(sender, decoded_objects=None):
        if decoded_objects is not None:
            with update_lock:
                chip_detected.decoded_objects = decoded_objects
                chip_detected.set()

    def on_frame_ready(sender, **message):
        with update_lock:
            frame_ready.message = message
            frame_ready.set()

    signals.signal('frame-ready').connect(on_frame_ready, weak=False)
    signals.signal('chip-detected').connect(on_chip_detected, weak=False)
    signals.signal('chip-removed').connect(lambda sender:
                                           chip_detected.clear(), weak=False)
    signals.signal('closed').connect(lambda sender: closed.set(), weak=False)
    thread = threading.Thread(target=show_chip, args=(1280, 720, 0),
                            kwargs={'signals': signals})
    thread.daemon = True
    thread.start()

    while True:
        if frame_ready.wait(.01):
            with update_lock:
                frame = frame_ready.message['frame']
                font = cv2.FONT_HERSHEY_SIMPLEX
                thickness = 1
                if chip_detected.is_set():
                    text = chip_detected.decoded_objects[0].data
                    scale = 4
                    text_size = cv2.getTextSize(text, font, scale, thickness)
                    while text_size[0][0] > frame.shape[0]:
                        scale *= .95
                        text_size = cv2.getTextSize(text, font, scale, thickness)
                    cv2.putText(frame, text, (10, 10 + text_size[0][-1]), font,
                                scale, (255,255,255), thickness, cv2.LINE_AA)
                cv2.imshow('DMF chip', frame)
                frame_ready.clear()
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    signals.signal('exit-request').send(None)
                    break

    closed.wait()
    cv2.destroyAllWindows()
