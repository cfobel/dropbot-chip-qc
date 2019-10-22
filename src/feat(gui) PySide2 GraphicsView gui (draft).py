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
import logging
logging.basicConfig(level=logging.INFO)

from PySide2 import QtGui, QtCore, QtWidgets
from dropbot_chip_qc.ui.mdi import (FigureMdi, DropBotSettings, MdiArea,
                                    MainWindow, DropBotMqttProxy)

# %gui qt5

from asyncio_helpers import asyncio
from dropbot_chip_qc.ui.viewer import QCVideoViewer
from logging_helpers import caller_name
import asyncio_helpers as aioh
import dmf_chip as dc
import dropbot.move
import dropbot_chip_qc as qc
import dropbot_chip_qc.connect
import dropbot_chip_qc.ui.plan
import dropbot_chip_qc.video
import matplotlib as mpl
import networkx as nx
import numpy as np
import pandas as pd
import si_prefix as si

# For colors, see: https://gist.github.com/cfobel/fd939073cf13a309d7a9
light_blue = '#88bde6'
light_green = '#90cd97'
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
import functools as ft

import blinker


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
#     print('\r%-50s' % ('[`%s` from `%s`] %s' % (event, sender, kwargs)),
#           end='')
    print('\r%-100s' % ('args: `%s`, kwargs: `%s`' % (args, kwargs)), end='')


signals = blinker.Namespace()

for k in ('dropbot.voltage', 'chip-detected'):
    if k in signals:
        del signals[k]
    signals.signal(k).connect(ft.partial(dump, k), weak=False)

chip_file = r'C:\Users\chris\Dropbox (Sci-Bots)\SCI-BOTS\manufacturing\chips\MicroDrop SVGs\sci-bots-90-pin-array-with_interdigitation.svg'

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
channels_graph = nx.Graph([tuple(map(electrode_channels.get, e))
                           for e in electrodes_graph.edges])
chip_info_mm = dc.to_unit(chip_info, 'mm')

proxy = None
signals.signal('dropbot.voltage').connect(on_voltage_changed, weak=False)
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
        proxy.set_state_of_channels(pd.Series(1,
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


d = DropBotSettings(signals)
window.mdiArea.addSubWindow(d)
d.show()
window.mdiArea.tileSubWindows()


def on_chip_detected(sender, decoded_objects=tuple()):
    if decoded_objects:
        d.fields['Chip UUID:'].setText(decoded_objects[0].data)

signals.signal('chip-detected').connect(on_chip_detected, weak=False)
# -


# ### Launch background video process
#
# Launch background process to handle video, including:
#
#  - Reading frames from webcam
#  - Registering chip view using AruCo markers (if detected)
#  - Emitting `chip-detected` signal in `monitor_task.signals` namespace if a
#    new QR code is detected

# +
import threading

thread = threading.Thread(target=qc.video.chip_video_process,
                          args=(signals, 1280, 720, 0))
thread.start()
window.show()
# -

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

proxy = DropBotMqttProxy.from_uri('dropbot', 'localhost')
aproxy = DropBotMqttProxy.from_uri('dropbot', 'localhost', async_=True)

# +
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
#             colour_i = light_green if id_i in actuated_ids else light_blue
#             patch_i.set_facecolor(colour_i)
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
states = proxy.state_of_channels
channels = states[states > 0].index.tolist()
electrodes_by_id = pd.Series(chip_info_mm['electrodes'],
                             index=(e['id'] for e in
                                    chip_info_mm['electrodes']))
actuated_area = (electrodes_by_id[channel_electrodes[channels]]
                 .map(lambda x: x['area'])).sum()
capacitance = pd.Series(proxy.capacitance(0)
                        for i in range(20)).median()
sheet_capacitance = capacitance / actuated_area
message = ('Measured %s sheet capacitance: %sF/%.1f mm^2 = %sF/mm^2'
           % (name, si.si_format(capacitance), actuated_area,
              si.si_format(sheet_capacitance)))
print(message)
target_force = 30e-6  # i.e., 30 μN
voltage = np.sqrt(target_force / (1e3 * 0.5 * sheet_capacitance))
# Set voltage in DropBot settings UI
d.fields['Voltage:'].setValue(voltage)

# ## Attempt to move liquid along tour, capturing capacitance
#

# +
patches = plot_result['patches']
channel_patches = pd.Series(patches.values(),
                            index=electrode_channels[patches.keys()])

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
# -

import dropbot_chip_qc.ui.execute
reload(dropbot_chip_qc.ui.plan)
reload(dropbot_chip_qc.ui.execute)


# +
def on_transfer_complete(sender, **message):
    channel_plan = message['channel_plan']
    completed_transfers = message['completed_transfers']

    # Remove existing quiver arrows.
    for c in list(figure._ax.collections):
        if isinstance(c, mpl.quiver.Quiver):
            c.remove()

    q1, q2 = qc.ui.render.render_plan(figure._ax, df_channel_centers,
                                      channel_patches, channel_plan,
                                      completed_transfers)
    figure._ax.figure.canvas.draw()

signals.signal('transfer-complete').connect(on_transfer_complete, weak=False)
# -

# # Execute test on channel plan through waypoints

# +
import path_helpers as ph
import itertools as it


import ipywidgets as ipw

import dropbot_chip_qc.ui.execute
import dropbot_chip_qc.ui.notebook
import dropbot_chip_qc.ui.render
reload(qc.ui.execute)
reload(qc.ui.notebook)
reload(qc.ui.plan)

# +
output_directory = ph.path('~/Dropbox (Sci-Bots)/chip-qc').expand()

# waypoints = map(int, chip_info['__metadata__']['test-routes'][0]['waypoints'])
waypoints = [110, 113, 18]
full_channel_plan = list(qc.ui.plan.create_channel_plan(channels_graph,
                                                        waypoints, loop=False))
executor = qc.ui.execute.Executor(channels_graph, full_channel_plan)
try:
    # Detach existing callbacks (if applicable).
    del control.pause_on_complete
    del control.start_on_complete
except NameError:
    pass
control = qc.ui.notebook.executor_control(chip_info, aproxy, signals, figure,
                                          channel_patches, executor,
                                          output_directory,
                                          d.fields['Chip UUID:'].text)
display(control)
# -

# ## Clean up

# +
import time

s = signals.signal('exit-request')
display(s.send(caller_name(0)))

# Wait for video processing thread to stop.
while thread.is_alive():
    time.sleep(.1)
time.sleep(.1)

# Clear exit request receivers.
[s.disconnect(r) for r in s.receivers.values()]

viewer._invoker.invoke(viewer.setPhoto)
