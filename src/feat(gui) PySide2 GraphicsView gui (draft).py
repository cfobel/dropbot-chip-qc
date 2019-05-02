# -*- coding: utf-8 -*-
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
from __future__ import print_function, division
import functools as ft
import threading
import time

from PySide2 import QtGui, QtCore, QtWidgets

from matplotlib.backends.backend_qt5agg import (FigureCanvas,
                                                NavigationToolbar2QT as
                                                NavigationToolbar)
from matplotlib.figure import Figure

# %gui qt5

from dropbot_chip_qc.ui.viewer import QCVideoViewer
import asyncio_helpers as aioh
import dmf_chip as dc
import dropbot as db
import dropbot.move
import dropbot_chip_qc as dq
import dropbot_chip_qc as qc
import dropbot_chip_qc.connect
import dropbot_chip_qc.video
import networkx as nx
import numpy as np
import pandas as pd
import si_prefix as si
import trollius as asyncio

# For colors, see: https://gist.github.com/cfobel/fd939073cf13a309d7a9
light_blue = '#88bde6'
light_green = '#90cd97'

# +
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

        # self.mdiArea.subWindowActivated.connect(self.updateMenus)

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
        for sub_window in window.mdiArea.subWindowList():
            for c in sub_window.children():
                if hasattr(c, 'fitInView'):
                    c.fitInView()

    def resizeEvent(self, event):
        self.tileVertically()
        return super(MainWindow, self).resizeEvent(event)


# -

# ## Create DropBot monitor process
#
# The `monitor_task` below is a **cancellable**<sup>1</sup> task that includes
# the following attributes (among others):
#
#  - `monitor_task.signals`: DropBot `blinker` signals namespace shared w/UI code
#  - `monitor_task.proxy`: DropBot control handle
#  - `monitor_task.proxy.chip_info`: chip info loaded from `chip_file` using `dmf_chip.load()`
#  - `monitor_task.proxy.channels_graph`: `networkx` graph connecting channels mapped to adjacent electrodes in `chip_file`
#
# <sup>1</sup> A **cancellable task** is created using the `asyncio_helpers.cancellable()` decorator.  The resulting function has the following attributes:
#
#  - `cancel()`: raise a `CancelledError` exception within the task to stop it
#  - `started`: `threading.Event`, which is set once the task has started execution

# +
chip_file = r'C:\Users\chris\Dropbox (Sci-Bots)\SCI-BOTS\manufacturing\chips\MicroDrop SVGs\sci-bots-90-pin-array-with_interdigitation.svg'


monitor_task = qc.connect.connect(svg_source=chip_file)
chip_info_mm = dc.to_unit(monitor_task.proxy.chip_info, 'mm')
electrode_channels = pd.Series((e['channels'][0] for e in
                                monitor_task.proxy.chip_info['electrodes']),
                               index=(e['id'] for e in monitor_task.proxy
                                      .chip_info['electrodes']),
                               name='channel').sort_values()
electrode_channels.index.name = 'id'
channel_electrodes = pd.Series(electrode_channels.index,
                               index=electrode_channels)
electrode_neighbours = dc.get_neighbours(monitor_task.proxy.chip_info)
channels_index = pd.MultiIndex.from_tuples([(electrode_channels[id_],
                                             direction) for id_, direction in
                                            electrode_neighbours.index.values])
channels_index.names = 'channel', 'direction'
channel_neighbours = pd.Series(electrode_channels[electrode_neighbours].values,
                               index=channels_index,
                               name='neighbour_channel').sort_index()


def on_voltage_changed(sender, **message):
    if 'value' in message:
        monitor_task.proxy.voltage = message['value']

monitor_task.signals.signal('dropbot.voltage').connect(on_voltage_changed,
                                                       weak=False)


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
#     print('\r%-50s' % ('[`%s` from `%s`] %s' % (event, sender, kwargs)),
#           end='')
    print('\r%-100s' % ('args: `%s`, kwargs: `%s`' % (args, kwargs)), end='')


for k in ('dropbot.voltage', 'chip-detected'):
    if k in monitor_task.signals:
        del monitor_task.signals[k]
    monitor_task.signals.signal(k).connect(ft.partial(dump, k), weak=False)
# -

# ## Create Qt Window
#
# Create Multiple Document Interface (i.e., MDI) window containing the following
# sub-windows:
#
#  1. DMF chip webcam viewer
#  2. DropBot settings form

# +
window = MainWindow()
viewer = window.createMdiChild(monitor_task.signals)
window.show()
window.tileVertically()

def on_key_press(event):
    for k in ('up', 'down', 'left', 'right'):
        if event.key() == QtGui.QKeySequence(k):
            break
    else:
        return

    with monitor_task.proxy.transaction_lock:
        states = monitor_task.proxy.state_of_channels
        neighbours = channel_neighbours.loc[states[states > 0].index.tolist(),
                                            k]
        monitor_task.proxy.set_state_of_channels(pd.Series(1,
                                                           index=neighbours),
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


d = DropBotSettings(monitor_task.signals)
window.mdiArea.addSubWindow(d)
d.show()
window.mdiArea.tileSubWindows()


def on_chip_detected(sender, decoded_objects=tuple()):
    if decoded_objects:
        d.fields['Chip UUID:'].setText(decoded_objects[0].data)

monitor_task.signals.signal('chip-detected').connect(on_chip_detected,
                                                     weak=False)
# -


# ### Launch background video process
#
# Launch background process to handle video, including:
#
#  - Reading frames from webcam
#  - Registering chip view using AruCo markers (if detected)
#  - Emitting `chip-detected` signal in `monitor_task.signals` namespace if a
#    new QR code is detected

thread = threading.Thread(target=dq.video.chip_video_process,
                          args=(monitor_task.signals, 1280, 720, 0))
thread.start()
window.show()

# ## Create interactive chip layout figure
#
# Open new sub-window including an interactive figure representing the layout of
# electrodes in `chip_file`.
#
#  - Each **electrode** label corresponds to the respective DropBot actuation
#    channel
#  - Click on **electrode** to request DropBot to actuate the corresponding
#    **channel**
#  - Use **up**, **down**, **left**, **right** arrow keys to actuate adjacent
#    electrodes in corresponding direction
#  - Colour of each **electrode** represents actuation state:
#    * **blue**: not actuated
#    * **green**: actuated

# +
figure = FigureMdi()

window.mdiArea.addSubWindow(figure)
figure.show()

plot_result = draw_chip(monitor_task.proxy.chip_info, figure._ax)
figure._ax.figure.canvas.draw()

## Start video monitor process and update Qt Window async
window.fit()
window.mdiArea.tileSubWindows()

@asyncio.coroutine
def on_channels_updated(patches, sender, **message):
    def _update_ui():
        actuated_ids = set(channel_electrodes[message['actuated']])
        for id_i, patch_i in patches.items():
            colour_i = light_green if id_i in actuated_ids else light_blue
            patch_i.set_facecolor(colour_i)
        figure._ax.figure.canvas.draw()
    viewer._invoker.invoke(_update_ui)

monitor_task.signals.signal('channels-updated')\
    .connect(ft.partial(on_channels_updated, plot_result['patches']),
                        weak=False)

def onpick(event):
    if event.mouseevent.button == 1:
        electrode_id = event.artist.get_label()
        channels = electrode_channels[[electrode_id]]
        with monitor_task.proxy.transaction_lock:
            states = monitor_task.proxy.state_of_channels
            states[channels] = ~(states[channels].astype(bool))
            monitor_task.proxy.state_of_channels = states

figure._ax.figure.canvas.mpl_connect('pick_event', onpick)
# -

# ## Calibrate sheet capacitance with liquid present
#
# **NOTE** Prior to running the following cell:
#
#  - _at least_ one electrode **MUST** be **actuated**
#  - all actuated electrodes **MUST** be completely covered with liquid
#
# It may be helpful to use the interactive figure UI to manipulate liquid until
# the above criteria are met.
#
# Execution of the following cell performs the following steps:
#
#  1. Measure **total capacitance** across **all actuated electrodes**
#  2. Compute sheet capacitance with liquid present ($\Omega_L$) based on nominal
#     areas of actuated electrodes from `chip_file`
#  3. Compute voltage to match 25 μN of force, where
#     $F = 10^3 \cdot 0.5 \cdot \Omega_L \cdot V^2$
#  4. Set DropBot voltage to match target of 25 μN force.

name = 'liquid'
states = monitor_task.proxy.state_of_channels
channels = states[states > 0].index.tolist()
electrodes_by_id = pd.Series(chip_info_mm['electrodes'],
                             index=(e['id'] for e in
                                    chip_info_mm['electrodes']))
actuated_area = (electrodes_by_id[channel_electrodes[channels]]
                 .map(lambda x: x['area'])).sum()
capacitance = pd.Series(monitor_task.proxy.capacitance(0)
                        for i in range(20)).median()
sheet_capacitance = capacitance / actuated_area
message = ('Measured %s sheet capacitance: %sF/%.1f mm^2 = %sF/mm^2'
           % (name, si.si_format(capacitance), actuated_area,
              si.si_format(sheet_capacitance)))
print(message)
target_force = 25e-6  # i.e., 25 μN
voltage = np.sqrt(target_force / (1e3 * 0.5 * sheet_capacitance))
# Set voltage in DropBot settings UI
d.fields['Voltage:'].setValue(voltage)


# ## Attempt to move liquid along tour, capturing capacitance
#

# +
@asyncio.coroutine
def move_liquid(route):
    proxy = monitor_task.proxy
    try:
        proxy.update_state(capacitance_update_interval_ms=5)

        # Apply each actuation for at least 0.3 seconds; allow up to 5
        # seconds of actuation before attempting to retry.
        messages = yield asyncio\
            .From(db.move.move_liquid(proxy, route, min_duration=.5,
                                      wrapper=ft.partial(asyncio.wait_for,
                                                         timeout=10)))
        monitor_task.signals.signal('move-complete').send('move_liquid',
                                                          messages=messages,
                                                          route=route)
    finally:
        # Disable DropBot capacitance updates.
        proxy.update_state(capacitance_update_interval_ms=0)
        proxy.set_state_of_channels(pd.Series(), append=False)


@asyncio.coroutine
def execute_tour(channels_tour, exclude=tuple()):
    for a, b in db.move.window(channels_tour[~channels_tour.isin(exclude)],
                               2):
        route = nx.shortest_path(monitor_task.proxy.channels_graph, a, b)
        result = yield asyncio.From(move_liquid(route))


# -

# ### Compute tour to visit all electrodes.

# +
tour = dc.compute_tour(chip_info_mm,
                       start_id=chip_info_mm['electrodes'][0]['channels'][0])

move_messages = []

def on_move_complete(sender, **result):
    move_messages.append(result)

monitor_task.signals.signal('move-complete').connect(on_move_complete,
                                                     weak=False)
# -

# ### Execute tour
#
#  - start/finish at `start_channel`
#  - exclude channels listed in `exclude`

# +
start_channel = 82
exclude = [113]

channels_tour = electrode_channels[tour]
channels_tour = pd.Series(np.roll(channels_tour,
                                  -channels_tour.tolist()
                                  .index(start_channel)))

task = aioh.cancellable(execute_tour)
thread = threading.Thread(target=task, args=(channels_tour, ),
                          kwargs={'exclude': exclude})
thread.daemon = True
thread.start()
# -

# ## Clean up

# +
s = monitor_task.signals.signal('exit-request')
display(s.send('main'))

# Wait for video processing thread to stop.
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
