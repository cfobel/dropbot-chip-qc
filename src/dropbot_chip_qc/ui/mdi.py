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
import dropbot.move
import dropbot_chip_qc as dq
import dropbot_chip_qc as qc
import dropbot_chip_qc.connect
import dropbot_chip_qc.video
import dropbot_monitor as dbm
import dropbot_monitor.mqtt_proxy
import matplotlib as mpl
import networkx as nx
import numpy as np
import pandas as pd
import path_helpers as ph
import si_prefix as si
import trollius as asyncio

from .mqtt_proxy import DropBotMqttProxy


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


def launch(aproxy, chip_file, signals=None):
    if signals is None:
        signals = blinker.Namespace()

    proxy = DropBotMqttProxy.from_uri('dropbot', aproxy.__client__._host)

    def on_voltage_changed(sender, **message):
        if 'value' in message and proxy is not None:
            proxy.voltage = message['value']

    def draw_chip(chip_info, ax, **kwargs):
        chip_info_ = dc.to_unit(chip_info, 'mm')

        plot_result = dc.draw(chip_info_, ax=ax)

        labels = {t.get_text(): t for t in plot_result['axis'].texts}
        electrode_channels = {e['id']: e['channels'][0]
                              for e in chip_info['electrodes']}

        for id_i, label_i in labels.items():
            label_i.set_text(electrode_channels[id_i])

        for id_i, electrode_patch_i in plot_result['patches'].items():
            electrode_patch_i.set_facecolor(light_blue)
            electrode_patch_i.set_edgecolor('none')
            # XXX Need to explicitly enabled "picking" for patch.
            electrode_patch_i.set_picker(True)

        x_coords = [p[0] for e in chip_info_['electrodes'] for p in e['points']]
        y_coords = [p[1] for e in chip_info_['electrodes'] for p in e['points']]
        ax.set_xlim(min(x_coords), max(x_coords))
        ax.set_ylim(max(y_coords), min(y_coords))
        ax.get_figure().tight_layout()
        return plot_result

    def dump(*args, **kwargs):
        print('\r%-100s' % ('args: `%s`, kwargs: `%s`' % (args, kwargs)), end='')

    for k in ('dropbot.voltage', 'chip-detected'):
        if k in signals:
            del signals[k]
        signals.signal(k).connect(ft.partial(dump, k), weak=False)

    chip_info, electrodes_graph, electrode_neighbours = \
        qc.connect.load_device(chip_file)

    # Convert `electrode_neighbours` to channel numbers instead of electrode ids.
    electrode_channels = pd.Series({e['id']: e['channels'][0]
                                    for e in chip_info['electrodes']})
    channel_electrodes = pd.Series(electrode_channels.index,
                                   index=electrode_channels)
    index = pd.MultiIndex\
        .from_arrays([electrode_channels[electrode_neighbours.index
                                         .get_level_values('id')],
                      electrode_neighbours.index.get_level_values('direction')],
                     names=('channel', 'direction'))
    channel_neighbours = pd.Series(electrode_channels[electrode_neighbours].values,
                                   index=index)

    signals.signal('dropbot.voltage').connect(on_voltage_changed, weak=False)

    window = MainWindow()
    viewer = window.createMdiChild(signals)
    window.show()
    window.tileVertically()

    def on_key_press(event):
        for k in ('up', 'down', 'left', 'right'):
            if event.key() == QtGui.QKeySequence(k):
                break
        else:
            return

        if proxy is None:
            return

        with proxy.transaction_lock:
            states = proxy.state_of_channels
            neighbours = channel_neighbours.loc[states[states > 0].index.tolist(),
                                                k]
            proxy.set_state_of_channels(pd.Series(1, index=neighbours),
                                        append=False)

    window.mdiArea.keyPressed.connect(on_key_press)

    def tile_key(event):
        modifiers_ = QtWidgets.QApplication.keyboardModifiers()
        modifiers = []

        if modifiers_ & QtCore.Qt.ShiftModifier:
            modifiers.append('Shift')
        if modifiers_ & QtCore.Qt.ControlModifier:
            modifiers.append('Ctrl')
        if modifiers_ & QtCore.Qt.AltModifier:
            modifiers.append('Alt')
        if modifiers_ & QtCore.Qt.MetaModifier:
            modifiers.append('Meta')

        modifiers.append(QtGui.QKeySequence(event.key()).toString())
        key_seq = QtGui.QKeySequence('+'.join(map(str, modifiers)))

        if key_seq == QtGui.QKeySequence('Ctrl+T'):
            window.mdiArea.tileSubWindows()

    window.mdiArea.keyPressed.connect(tile_key)

    dropbot_settings = DropBotSettings(signals)
    window.mdiArea.addSubWindow(dropbot_settings)
    dropbot_settings.show()
    window.mdiArea.tileSubWindows()

    def on_chip_detected(sender, decoded_objects=tuple()):
        if decoded_objects:
            dropbot_settings.fields['Chip UUID:'].setText(decoded_objects[0].data)

    signals.signal('chip-detected').connect(on_chip_detected, weak=False)

    thread = threading.Thread(target=qc.video.chip_video_process,
                              args=(signals, 1280, 720, 0))
    thread.start()
    window.show()

    figure = FigureMdi()

    window.mdiArea.addSubWindow(figure)
    figure.show()

    plot_result = draw_chip(chip_info, figure._ax)
    figure._ax.figure.canvas.draw()

    window.fit()
    window.mdiArea.tileSubWindows()

    def on_channels_updated(patches, sender, **message):
        def _update_ui():
            actuated_ids = set(channel_electrodes[message['actuated']])
            for id_i, patch_i in patches.items():
                alpha_i = 1. if id_i in actuated_ids else .3
                patch_i.set_alpha(alpha_i)
            figure._ax.figure.canvas.draw()
        viewer._invoker.invoke(_update_ui)

    proxy.__client__.signals.signal('channels-updated')\
        .connect(ft.partial(on_channels_updated, plot_result['patches']),
                            weak=False)

    def onpick(event):
        if proxy is not None and event.mouseevent.button == 1:
            electrode_id = event.artist.get_label()
            channels = electrode_channels[[electrode_id]]
            with proxy.transaction_lock:
                states = proxy.state_of_channels
                states[channels] = ~(states[channels].astype(bool))
                proxy.state_of_channels = states

    figure._ax.figure.canvas.mpl_connect('pick_event', onpick)

    patches = plot_result['patches']
    channel_patches = pd.Series(patches.values(),
                                index=electrode_channels[patches.keys()])

    channels_graph = nx.Graph([tuple(map(electrode_channels.get, e))
                               for e in electrodes_graph.edges])
    chip_info_mm = dc.to_unit(chip_info, 'mm')

    # Find center of electrode associated with each DropBot channel.
    df_electrode_centers = pd.DataFrame([e['pole_of_accessibility']
                                         for e in chip_info_mm['electrodes']],
                                        index=[e['id'] for e in
                                               chip_info_mm['electrodes']])
    df_electrode_centers.index.name = 'id'
    s_electrode_channels = pd.Series(electrode_channels)
    df_channel_centers = df_electrode_centers.loc[s_electrode_channels.index]
    df_channel_centers.index = s_electrode_channels.values
    df_channel_centers.sort_index(inplace=True)
    df_channel_centers.index.name = 'channel'

    def on_transfer_complete(sender, **message):
        channel_plan = message['channel_plan']
        completed_transfers = message['completed_transfers']

        # Remove existing quiver arrows.
        for collection in list(figure._ax.collections):
            if isinstance(collection, mpl.quiver.Quiver):
                collection.remove()

        qc.ui.render.render_plan(figure._ax, df_channel_centers,
                                 channel_patches, channel_plan,
                                 completed_transfers)
        figure._ax.figure.canvas.draw()

    signals.signal('transfer-complete').connect(on_transfer_complete, weak=False)

    # # Cleanup
    # import time

    # # Request webcam input process to stop.
    # s = signals.signal('exit-request')

    # # Wait for video processing thread to stop.
    # while thread.is_alive():
        # time.sleep(.1)
    # time.sleep(.1)

    # # Clear exit request receivers.
    # [s.disconnect(r) for r in s.receivers.values()]

    # viewer._invoker.invoke(viewer.setPhoto)

    return {'window': window, 'figure': figure, 'channel_patches': channel_patches,
            'chip_info': chip_info, 'chip_info_mm': chip_info_mm,
            'channels_graph': channels_graph, 'signals': signals,
            'dropbot_settings': dropbot_settings,
            'channel_electrodes': channel_electrodes,
            'electrode_channels': electrode_channels}
