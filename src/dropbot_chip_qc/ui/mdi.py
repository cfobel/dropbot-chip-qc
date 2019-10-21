# -*- coding: utf-8 -*-
from __future__ import print_function, division
import functools as ft
from imp import reload
import logging
import threading
import time
import sys

from PySide2 import QtGui, QtCore, QtWidgets
from dropbot_chip_qc.ui.viewer import QCVideoViewer
from dropbot_monitor import asyncio
from matplotlib.backends.backend_qt5agg import (FigureCanvas,
                                                NavigationToolbar2QT as
                                                NavigationToolbar)
from matplotlib.figure import Figure
import asyncio_helpers as aioh
import blinker
import dmf_chip as dc
import dropbot as db
import dropbot as db
import dropbot.move
import dropbot.threshold_async
import dropbot_chip_qc as dq
import dropbot_chip_qc as qc
import dropbot_chip_qc.connect
import dropbot_chip_qc.video
import dropbot_monitor as dbm
import dropbot_monitor.mqtt_proxy
from dropbot_monitor.mqtt_proxy import MqttProxy
import networkx as nx
import numpy as np
import pandas as pd
import si_prefix as si
import trollius as asyncio

# For colors, see: https://gist.github.com/cfobel/fd939073cf13a309d7a9
light_blue = '#88bde6'
light_green = '#90cd97'


class FigureMdi(QtWidgets.QMdiSubWindow):
    def __init__(self):
        super(FigureMdi, self).__init__()
        canvas = FigureCanvas(Figure(figsize=(5, 3), tight_layout=True))
        toolbar = NavigationToolbar(canvas, self)
        self._ax = canvas.figure.subplots()
        layout = self.layout()
        layout.addWidget(toolbar)
        layout.addWidget(canvas)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self.setGeometry(500, 300, 800, 600)


class DropBotSettings(QtWidgets.QWidget):
    def __init__(self, signals, name='form'):
        super(DropBotSettings, self).__init__()
        self.formGroupBox = QtWidgets.QGroupBox("DropBot")
        self.layout = QtWidgets.QFormLayout()
        voltage_spin_box = QtWidgets.QDoubleSpinBox()
        voltage_spin_box.setRange(0, 150);
        voltage_spin_box.setValue(100)

        self.layout.addRow(QtWidgets.QLabel("Voltage:"), voltage_spin_box)
        self.layout.addRow(QtWidgets.QLabel("Chip UUID:"),
                           QtWidgets.QLineEdit())

        self.formGroupBox.setLayout(self.layout)
        self.setLayout(self.layout)

        def on_change(x):
            signals.signal('dropbot.voltage').send(name, value=x)

        voltage_spin_box.valueChanged.connect(on_change)

    @property
    def fields(self):
        return {self.layout.itemAt(i, QtWidgets.QFormLayout.LabelRole).widget()
                .text(): self.layout.itemAt(i, QtWidgets.QFormLayout.FieldRole)
                .widget() for i in range(self.layout.rowCount())}


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


class MdiArea(QtWidgets.QMdiArea):
    keyPressed = QtCore.Signal(QtCore.QEvent)

    def keyPressEvent(self, event):
        self.keyPressed.emit(event)
        return super(MdiArea, self).keyPressEvent(event)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()

        self.mdiArea = MdiArea()
        self.mdiArea.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.mdiArea.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.mdiArea.setActivationOrder(QtWidgets.QMdiArea.WindowOrder.ActivationHistoryOrder)
        self.setCentralWidget(self.mdiArea)
        self.setWindowTitle('DMF chip quality control')

    def createMdiChild(self, signals):
        sub_window = QtWidgets.QMdiSubWindow()
        sub_window.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        sub_window.setGeometry(500, 300, 800, 600)
        child = QCVideoViewer(None, signals)
        sub_window.layout().addWidget(child)
        self.mdiArea.addSubWindow(sub_window)
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
        for sub_window in self.mdiArea.subWindowList():
            for c in sub_window.children():
                if hasattr(c, 'fitInView'):
                    c.fitInView()

    def resizeEvent(self, event):
        self.tileVertically()
        return super(MainWindow, self).resizeEvent(event)


class DropBotMqttProxy(MqttProxy):
    def __init__(self, *args, **kwargs):
        super(DropBotMqttProxy, self).__init__(*args, **kwargs)
        super(DropBotMqttProxy, self).__setattr__('transaction_lock',
                                                  threading.RLock())

    @classmethod
    def from_uri(cls, *args, **kwargs):
        return super(DropBotMqttProxy, cls).from_uri(db.proxy.Proxy, *args,
                                                     **kwargs)
