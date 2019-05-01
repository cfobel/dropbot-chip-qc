# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:light
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.3'
#       jupytext_version: 1.0.2
#   kernelspec:
#     display_name: Python 2
#     language: python
#     name: python2
# ---

# ## Initialize Jupyter notebook Qt support

# +
from PySide2 import QtGui, QtCore, QtWidgets

# %gui qt

from IPython.lib.guisupport import start_event_loop_qt4
from dropbot_chip_qc.ui.viewer import QCVideoViewer

app = QtCore.QCoreApplication.instance()
start_event_loop_qt4()
# -

# ## Create Qt Window

# +
import trollius as asyncio
import threading
import blinker

signals = blinker.Namespace()

window = QtWidgets.QWidget()
VBlayout = QtWidgets.QVBoxLayout(window)
viewer = QCVideoViewer(window, signals)
VBlayout.addWidget(viewer)

window.setGeometry(500, 300, 800, 600)
window.show()
window.setWindowTitle('DMF chip quality control')
# -

# ## Start video monitor process and update Qt Window async

# +
import cv2
import asyncio_helpers as ah
import dropbot_chip_qc as dq
import dropbot_chip_qc.video


thread = threading.Thread(target=dq.video.chip_video_process,
                          args=(signals, 1280, 720, 0))
thread.start()

# Wait for first frame before scaling frame to fill window view.
frame_received = threading.Event()
def on_frame_received(sender, **record):
    if 'frame' in record:
        frame_received.set()
signals.signal('frame-ready').connect(on_frame_received)
frame_received.wait()
signals.signal('frame-ready').disconnect(on_frame_received)

window.show()
viewer.fitInView()
# -

# ## Clean up

s = signals.signal('exit-request')
display(s.send('main'))
# Clear exit request receivers.
[s.disconnect(r) for r in s.receivers.values()]

# -------------------------------------------
#
# # Misc

# +
# Load font

# db = QtGui.QFontDatabase()
# db.addApplicationFont(r'C:/Users/chris/Downloads/Orbitron-Regular.ttf')
# db.addApplicationFont(r'C:/Users/chris/Downloads/FontAwesome.ttf')

# +
# window.btnLoad.setAttribute(QtCore.Qt.WA_StyleSheet)
# window.btnLoad.setFont('Lato')
# window.btnLoad.setToolTip('Hello, world!')
# window.btnLoad.setToolTipDuration(.5)

#     '''
#     QWidget {
#         font-family: bold;
#         font-family: 'FontAwesome';
#     }''')
# style = window.btnLoad.style()
