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

# +
from __future__ import print_function, division
import logging
logging.basicConfig(level=logging.INFO)
import os
import time

from PySide2 import QtGui, QtCore, QtWidgets
from dropbot_chip_qc.ui.mdi import launch, DropBotMqttProxy

# %gui qt5

import dropbot_chip_qc as qc
import dropbot_chip_qc.ui.execute
import dropbot_chip_qc.ui.notebook
import dropbot_chip_qc.ui.plan
import path_helpers as ph

# +
chip_file = ph.path('~/Dropbox (Sci-Bots)/SCI-BOTS/manufacturing/chips/'
                    'MicroDrop SVGs/'
                    'sci-bots-90-pin-array-with_interdigitation.svg').expand()
aproxy = DropBotMqttProxy.from_uri('dropbot', 'localhost', async_=True)
ui = launch(aproxy, chip_file)

output_directory = ph.path('~/Dropbox (Sci-Bots)/chip-qc').expand()
# -

waypoints = map(int,
                ui['chip_info']['__metadata__']['test-routes'][0]['waypoints'])
full_channel_plan = list(qc.ui.plan.create_channel_plan(ui['channels_graph'],
                                                        waypoints, loop=False))
executor = qc.ui.execute.Executor(ui['channels_graph'], full_channel_plan)
try:
    # Detach existing callbacks (if applicable).
    del control.pause_on_complete
    del control.start_on_complete
except NameError:
    pass
control = qc.ui.notebook.executor_control(aproxy, ui,
                                          executor, output_directory)
display(control)
