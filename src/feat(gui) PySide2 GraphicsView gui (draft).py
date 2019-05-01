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
import sys

from PySide2 import QtGui, QtCore, QtWidgets

from matplotlib.backends.backend_qt5agg import (FigureCanvas,
                                                NavigationToolbar2QT as
                                                NavigationToolbar)
from matplotlib.figure import Figure

# %gui qt5

from IPython.lib.guisupport import start_event_loop_qt4
from dropbot_chip_qc.ui.viewer import QCVideoViewer

# app = QtCore.QCoreApplication.instance()
# if app is None:
#     app = QtCore.QCoreApplication(sys.argv)
# start_event_loop_qt4()
# -

# ## Create Qt Window

class FigureMdi(QtWidgets.QMdiSubWindow):
    def __init__(self):
        super(FigureMdi, self).__init__()
        canvas = FigureCanvas(Figure(figsize=(5, 3), tight_layout=True))
        toolbar = NavigationToolbar(canvas, self)
        self._ax = canvas.figure.subplots()
#         layout = QtWidgets.QVBoxLayout()
        layout = self.layout()
        layout.addWidget(toolbar)
        layout.addWidget(canvas)
#         self.setLayout(layout)


# +
import trollius as asyncio
import threading
import blinker

signals = blinker.Namespace()


def tileVertically(mdi):
    windows = mdi.subWindowList()
    if len(windows) < 2: 
        mdi.tileSubWindows()
    else:
        wHeight = mdi.height() / len(windows)
        y = 0
        for widget in windows:
            widget.resize(mdi.width(), wHeight)
            widget.move(0, y)
            y += wHeight


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()

        self.mdiArea = QtWidgets.QMdiArea()
        self.mdiArea.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.mdiArea.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setCentralWidget(self.mdiArea)

        # self.mdiArea.subWindowActivated.connect(self.updateMenus)

        self.setWindowTitle('DMF chip quality control')
    
    def createMdiChild(self, signals):
        child = QCVideoViewer(None, signals)
        sub_window = self.mdiArea.addSubWindow(child)
        sub_window.setGeometry(500, 300, 800, 600)
        return child
        
    def closeEvent(self, event):
        self.mdiArea.closeAllSubWindows()
        if self.activeMdiChild():
            event.ignore()
        else:
            event.accept()
            
    def tileVertically(self):
        tileVertically(self.mdiArea)
            
    def fit(self):
        for sub_window in window.mdiArea.subWindowList():
            for c in sub_window.children():
                if hasattr(c, 'fitInView'):
                    c.fitInView()
    
    def resizeEvent(self, event):
        self.tileVertically()
        return super(MainWindow, self).resizeEvent(event)

        
window = MainWindow()
viewer = window.createMdiChild(signals)
window.show()


figure = FigureMdi()
window.mdiArea.addSubWindow(figure)
figure.show()

window.tileVertically()

figure._ax.plot(range(10))
figure._ax.figure.canvas.draw()
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
window.show()
# -

# ## Clean up

# +
import time

s = signals.signal('exit-request')
display(s.send('main'))

while thread.is_alive():
    time.sleep(.1)
# Clear exit request receivers.
[s.disconnect(r) for r in s.receivers.values()]
viewer._invoker.invoke(viewer.setPhoto)
# -

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
